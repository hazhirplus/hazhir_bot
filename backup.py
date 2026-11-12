"""Nightly DB backup for «هژیر وی پی ان» (user request 2026-11-12).

Every night at 00:00 Tehran the bot sends the database file to the admins
inside the bot itself, so a dead server or a server move doesn't mean
re-entering everything from zero. A manual backup button + an auto-backup
toggle live in the admin settings menu.

Design notes:
- Scheduling uses PTB job_queue.run_daily (00:00 Asia/Tehran) — no manual
  UTC math, no daemon thread.
- The live DB is aiosqlite; the backup itself uses the synchronous
  sqlite3.backup API in a thread (safe against concurrent readers — the
  same approach as the shopbot). Only the .db file is ever sent — never
  env files or tokens.
- The auto toggle is the settings key `auto_backup_enabled` (default ON);
  the last-sent Tehran date is `last_nightly_backup`. If a night was
  missed (bot down at midnight) the next startup sends a catch-up.
"""
from __future__ import annotations
import asyncio
import datetime
import logging
import os
import sqlite3
from zoneinfo import ZoneInfo

import aiosqlite

import config
import db

log = logging.getLogger("hozhir")
TEHRAN = ZoneInfo("Asia/Tehran")
BACKUP_KEEP = 7  # فقط ۷ بکاپ آخر نگه داشته می‌شود (مصرف دیسک کم)
LAST_NIGHTLY_KEY = "last_nightly_backup"
AUTO_BACKUP_KEY = "auto_backup_enabled"


def backup_dir(db_path: str | None = None) -> str:
    base = db_path or config.DB_PATH
    return os.path.join(os.path.dirname(base) or ".", "backups")


def backup_db_file(db_path: str | None = None,
                   dest_dir: str | None = None) -> str | None:
    """بکاپ دیتابیس با API رسمی sqlite3.backup (کپی فایل خام در WAL امن
    نیست). فایل: backups/hozhir-YYYY-MM-DD.db. برمی‌گرداند مسیر فایل یا
    None در صورت خطا. همگام است — از کد async با asyncio.to_thread صدا بزن."""
    src_path = db_path or config.DB_PATH
    dest = dest_dir or backup_dir(db_path)
    try:
        os.makedirs(dest, exist_ok=True)
        out = os.path.join(
            dest, "hozhir-%s.db" % datetime.datetime.now().strftime("%Y-%m-%d"))
        src = sqlite3.connect(src_path, timeout=30)
        dst = sqlite3.connect(out)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        files = sorted(f for f in os.listdir(dest)
                       if f.startswith("hozhir-") and f.endswith(".db"))
        for old in files[:-BACKUP_KEEP]:
            try:
                os.remove(os.path.join(dest, old))
            except OSError:
                pass
        log.info("db backup written: %s", out)
        return out
    except Exception as e:
        log.warning("db backup failed: %s", e)
        return None


def tehran_today() -> str:
    return datetime.datetime.now(TEHRAN).strftime("%Y-%m-%d")


def tehran_yesterday() -> str:
    return (datetime.datetime.now(TEHRAN)
            - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def needs_catchup_backup(last_sent: str | None, today: str,
                         yesterday: str) -> bool:
    """آیا بکاپ شبانه از دست رفته؟ last_sent تاریخ تهران آخرین ارسال است
    (رشته YYYY-MM-DD یا ""/None). اگر دیشب یا امشب فرستاده شده، نه."""
    if not last_sent:
        return True
    return last_sent != today and last_sent != yesterday


async def auto_backup_on(path: str | None = None) -> bool:
    """بکاپ خودکار (شبانه) روشن است؟ پیش‌فرض روشن؛ ادمین با دکمه پنل خاموشش می‌کند."""
    return (await db.get_setting(AUTO_BACKUP_KEY, "1", path=path)) != "0"


async def backup_caption(path: str | None = None) -> str:
    """متن همراه فایل بکاپ: تاریخ/ساعت تهران + تعدادها + راهنمای بازیابی."""
    try:
        async with aiosqlite.connect(path or config.DB_PATH) as con:
            n_users = (await (await con.execute(
                "SELECT COUNT(*) FROM users")).fetchone())[0]
            n_inv = (await (await con.execute(
                "SELECT COUNT(*) FROM invoices")).fetchone())[0]
            n_active = (await (await con.execute(
                "SELECT COUNT(*) FROM invoices WHERE status='active'")).fetchone())[0]
    except Exception:
        n_users = n_inv = n_active = "؟"
    ts = datetime.datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M")
    db_name = os.path.basename(config.DB_PATH)
    return (f"💾 بکاپ دیتابیس «هژیر وی پی ان»\n📅 {ts} تهران\n"
            f"👥 {n_users} کاربر | 🧾 {n_inv} فاکتور | ✅ {n_active} سرویس فعال\n"
            f"برای بازیابی روی سرور جدید: فایل را با نام {db_name} جایگزین فایل دیتابیس ربات کنید.")


async def send_backup_to_admins(bot, db_path: str | None = None,
                                dest_dir: str | None = None) -> int:
    """بکاپ می‌گیرد و فایل را برای همه ادمین‌ها می‌فرستد. برمی‌گرداند تعداد
    ارسال‌های موفق (۰ یعنی بکاپ ساخته نشد یا ادمینی نیست)."""
    out = await asyncio.to_thread(backup_db_file, db_path, dest_dir)
    if not out:
        return 0
    cap = await backup_caption(db_path)
    sent = 0
    for aid in config.ADMIN_IDS:
        try:
            with open(out, "rb") as f:
                await bot.send_document(aid, f,
                                        filename=os.path.basename(out),
                                        caption=cap)
            sent += 1
        except Exception as e:
            log.warning("backup send to admin %s failed: %s", aid, e)
    return sent


async def send_nightly_backup(bot, db_path: str | None = None) -> bool:
    """ارسال شبانه با گاردها: خودکار خاموش → هیچ؛ امروز فرستاده شده → هیچ.
    در صورت موفقیت تاریخ تهران امروز ثبت می‌شود. True یعنی فرستاده شد یا
    همین امروز قبلاً فرستاده شده بود (یا خودکار خاموش است)."""
    if not await auto_backup_on(path=db_path):
        return True
    today = tehran_today()
    if (await db.get_setting(LAST_NIGHTLY_KEY, "", path=db_path)) == today:
        return True
    if await send_backup_to_admins(bot, db_path=db_path) > 0:
        try:
            await db.set_setting(LAST_NIGHTLY_KEY, today, path=db_path)
        except Exception:
            pass
        log.info("nightly backup sent")
        return True
    return False


async def nightly_backup_job(context) -> None:
    """job_queue callback (run_daily ساعت ۰۰:۰۰ تهران). در صورت خطا تا ۲ بار
    با فاصله یک ساعت دوباره تلاش می‌کند (run_once با شمارنده در job.data)."""
    retries = 0
    if context.job is not None and context.job.data:
        retries = context.job.data.get("retries", 0)
    if await send_nightly_backup(context.bot):
        return
    if retries < 2:
        context.job_queue.run_once(
            nightly_backup_job, when=3600,
            data={"retries": retries + 1}, name="nightly_backup_retry")


async def maybe_send_catchup_backup(bot, db_path: str | None = None) -> bool:
    """در استارت: اگر شبی از دست رفته باشد (یا اولین اجراست) و خودکار روشن
    باشد، همان موقع جبرانی می‌فرستد."""
    if not await auto_backup_on(path=db_path):
        return False
    last = await db.get_setting(LAST_NIGHTLY_KEY, "", path=db_path)
    if needs_catchup_backup(last, tehran_today(), tehran_yesterday()):
        return await send_nightly_backup(bot, db_path=db_path)
    return False
