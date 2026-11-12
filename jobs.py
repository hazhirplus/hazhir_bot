"""Scheduled jobs: expiry warnings/disables (hourly) + daily report (09:00 Tehran)."""
from __future__ import annotations
import datetime
import logging
import time
from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

import config
import db
import text as T
import keyboards as K
from backup import nightly_backup_job
from helpers import notify_admins, panel_client_for, volume_pct_used
from panel import PanelError

log = logging.getLogger("hozhir")
TEHRAN = ZoneInfo("Asia/Tehran")


async def crypto_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every 3 min: expire overdue crypto invoices, auto-verify the rest."""
    import chainwatch
    from helpers import activate_crypto_invoice
    now = int(time.time())
    for inv in await db.list_pending_crypto():
        if inv.get("crypto_expires_at") and now > inv["crypto_expires_at"]:
            await db.update_invoice(inv["id"], status="expired")
            await db.set_payment(inv["id"], "rejected", None)
            try:
                await context.bot.send_message(inv["user_id"], T.CRYPTO_EXPIRED)
            except Exception as e:
                log.warning("crypto expiry notice failed: %s", e)
            continue
        try:
            tx = await chainwatch.find_payment_for_invoice(inv)
        except Exception as e:
            log.warning("chainwatch check failed for invoice #%s: %s",
                        inv["id"], e)
            continue
        if tx:
            try:
                await activate_crypto_invoice(context, inv, tx)
            except Exception as e:
                log.warning("crypto activation failed for invoice #%s: %s",
                            inv["id"], e)


async def hourly_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    # 1) warn users whose service expires within warn_hours
    try:
        warn_hours = int(await db.get_setting("warn_hours", "24"))
    except ValueError:
        warn_hours = 24
    for inv in await db.due_for_warn(warn_hours):
        plan = await db.get_plan(inv["plan_id"]) if inv.get("plan_id") else None
        try:
            await context.bot.send_message(
                inv["user_id"],
                T.WARN_SOON.format(plan=plan["name"] if plan else "تست",
                                   hours=warn_hours),
                reply_markup=K.renew_one_kb(inv["id"]))
        except Exception as e:
            log.warning("warn send failed: %s", e)
            continue  # don't mark warned: retry next hour (transient failure)
        await db.update_invoice(inv["id"], warned_at=int(time.time()))
    # 1b) warn users whose volume is nearly used up (mirzabot parity: warn on
    #     both time and volume; before this, a burned-through quota just
    #     silently stopped working)
    try:
        warn_pct = int(await db.get_setting("warn_volume_pct", "80"))
    except ValueError:
        warn_pct = 80
    warn_pct = max(1, min(100, warn_pct))
    orphans: list[dict] = []  # active invoices whose panel account is gone
    for inv in await db.due_for_volume_warn():
        panel = await db.get_panel(inv["panel_id"]) if inv.get("panel_id") \
            else await db.get_active_panel()
        if not panel or not inv.get("panel_email"):
            continue
        try:
            pc = panel_client_for(panel)
            try:
                client = await pc.get_client(inv["panel_email"])
            except PanelError as e:
                if e.is_not_found:
                    client = None  # deleted from the panel: orphan
                else:
                    raise
            if not client:
                # Mark volume_warned_at=-1 (sentinel: "panel record
                # missing") so due_for_volume_warn() stops returning
                # it every hour; the admin is told once, below.
                await db.update_invoice(inv["id"], volume_warned_at=-1)
                orphans.append(inv)
                continue
            total = client.get("totalGB", 0) or 0
            if not total:
                continue  # unlimited plan: nothing to warn about
            traf = await pc.traffic(inv["panel_email"])
            used = (traf.get("up", 0) or 0) + (traf.get("down", 0) or 0)
            used_pct = volume_pct_used(used, total)
            if used_pct < warn_pct:
                continue
        except Exception as e:
            log.warning("volume warn check failed: %s", e)
            continue
        plan = await db.get_plan(inv["plan_id"]) if inv.get("plan_id") else None
        try:
            await context.bot.send_message(
                inv["user_id"],
                T.WARN_VOLUME_SOON.format(
                    plan=plan["name"] if plan else "تست",
                    pct=used_pct,
                    gb_left=T.fmt_gb(max(0, total - used))),
                reply_markup=K.renew_one_kb(inv["id"]))
        except Exception as e:
            log.warning("volume warn send failed: %s", e)
            continue  # don't mark warned: retry next hour
        await db.update_invoice(inv["id"], volume_warned_at=int(time.time()))
    if orphans:
        lines = "\n".join(
            f"• فاکتور #{i['id']} — کاربر {i['user_id']} — {i['panel_email']}"
            for i in orphans)
        await notify_admins(
            context,
            "⚠️ سرویس‌هایی در پنل پیدا نشد:\n" + lines +
            "\n\nاین سرویس‌ها فعال‌اند ولی اکانتشان از پنل حذف شده؛ "
            "بررسی ساعتی حجم برایشان متوقف شد تا لاگ شلوغ نشود. "
            "تمدیدشان به‌صورت خودکار اکانت تازه می‌سازد.")
    # 2) disable expired services on the panel
    for inv in await db.due_for_expire():
        panel = await db.get_panel(inv["panel_id"]) if inv.get("panel_id") \
            else await db.get_active_panel()
        if panel and inv.get("panel_email"):
            try:
                await panel_client_for(panel).set_enable(inv["panel_email"], False)
            except Exception as e:
                if isinstance(e, PanelError) and e.is_not_found:
                    log.info("disable expired #%s: already gone from panel",
                             inv["id"])
                else:
                    log.warning("disable expired failed: %s", e)
        await db.update_invoice(inv["id"], status="expired")
        plan = await db.get_plan(inv["plan_id"]) if inv.get("plan_id") else None
        try:
            await context.bot.send_message(
                inv["user_id"],
                T.EXPIRED_NOTICE.format(plan=plan["name"] if plan else "تست"))
        except Exception as e:
            log.warning("expire notice failed: %s", e)
        await notify_admins(context, f"⌛ فاکتور #{inv['id']} منقضی و در پنل غیرفعال شد.")


async def daily_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = int(time.time())
    day_ago = now - 86400
    cnt, total = await db.sales_since(day_ago)
    renewals = await db.renewals_since(day_ago)
    new_users = await db.count_new_users_since(day_ago)
    tests_today = [i for i in await db.list_invoices(kind="test", limit=1000)
                   if i["created_at"] >= day_ago]
    await notify_admins(
        context,
        T.DAILY_REPORT.format(count=cnt, total=T.fmt_price(total),
                              renewals=renewals, new_users=new_users,
                              tests=len(tests_today)))


def schedule_jobs(job_queue) -> None:
    job_queue.run_repeating(hourly_check, interval=3600, first=60,
                            name="hourly_check")
    job_queue.run_repeating(crypto_check, interval=180, first=120,
                            name="crypto_check")
    job_queue.run_daily(daily_report,
                        time=datetime.time(9, 0, tzinfo=TEHRAN),
                        name="daily_report")
    # بکاپ شبانه دیتابیس (درخواست کاربر ۲۰۲۶-۱۱-۱۲): هر شب ساعت ۰۰:۰۰ تهران
    # فایل بکاپ برای ادمین‌ها فرستاده می‌شود (بازیابی بعد از مرگ/تعویض سرور).
    job_queue.run_daily(nightly_backup_job,
                        time=datetime.time(0, 0, tzinfo=TEHRAN),
                        name="nightly_backup")
