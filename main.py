"""هژیر وی پی ان — minimal Persian Telegram VPN shop bot. Entry: python main.py (polling)."""
from __future__ import annotations
import logging
import os

from telegram import Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import config
import db
import text as T
from throttle import FloodGuard
from handlers_user import start, on_callback, _handle_state
from handlers_admin import admin_home
from jobs import schedule_jobs

log = logging.getLogger("hozhir")

# Anti-flood: per-user sliding-window rate limiter on all user-driven updates.
_flood = FloodGuard()


def _guarded(fn):
    """Drop flood updates; warn the user at most once per cooldown."""
    async def inner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else None
        if uid is not None and not _flood.allow(uid, admin=uid in config.ADMIN_IDS):
            if _flood.warn_due(uid):
                try:
                    if update.effective_message:
                        await update.effective_message.reply_text(T.FLOOD_WARN)
                except Exception:
                    log.warning("flood warn failed for %s", uid)
            return
        await fn(update, context)
    return inner


async def post_init(app) -> None:
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    await db.init_db()
    await db.seed_from_env()
    # v2 one-time migration: legacy test invoices stuck in 'pending'
    n = await db.migrate_expire_stuck_tests()
    if n:
        log.info("migrated %d stuck test invoices to expired", n)
    # v2.3: seed crypto amount-uniqueness registry from still-pending invoices
    try:
        import chainwatch
        sn = await chainwatch.seed_issued_amounts()
        if sn:
            log.info("seeded %d pending crypto amounts", sn)
    except Exception as e:
        log.warning("crypto amount seeding failed: %s", e)
    # بکاپ شبانه: اگر شبی از دست رفته باشد (یا اولین اجراست)، در استارت
    # جبرانی بفرست — نشانه‌اش رسیدن فایل بکاپ به ادمین بعد از استارت است.
    try:
        import backup
        if await backup.maybe_send_catchup_backup(app.bot):
            log.info("catch-up nightly backup sent at startup")
    except Exception as e:
        log.warning("catch-up backup failed: %s", e)
    log.info("DB ready; admins=%d", len(config.ADMIN_IDS))


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Admin bottom-menu navigation always wins (cancels any pending input).
    from handlers_admin import admin_menu_text
    if await admin_menu_text(update, context):
        return
    st = context.user_data.get("st")
    if st:
        await _handle_state(update, context, st)
        return
    t = (update.message.text or "").strip()
    # user menu routing lives in handlers_user.menu_text
    from handlers_user import menu_text
    await menu_text(update, context)


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = context.user_data.get("st")
    if not st:
        return
    k = st.get("k")
    if k == "receipt":
        await _handle_state(update, context, st)
    elif k in ("a_tutadd_photo", "a_tutedit", "a_bc_msg"):
        from handlers_admin import handle_admin_state
        await handle_admin_state(update, context, st)
    # otherwise ignore stray media


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        level=logging.INFO)
    # never log secrets
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", _guarded(start)))
    app.add_handler(CommandHandler("admin", _guarded(admin_home)))
    app.add_handler(CallbackQueryHandler(_guarded(on_callback)))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, _guarded(on_media)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _guarded(on_text)))
    schedule_jobs(app.job_queue)
    log.info("starting polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
