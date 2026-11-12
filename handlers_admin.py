"""Admin flows (Persian): hub + submenus.

Sections: reports (adm_rep_), payments (adm_pay_), panels (adm_panel_),
inbounds (adm_inb_), plans (adm_plan_), cards (adm_card_), users (adm_users_),
tutorials (adm_tut_), broadcast (adm_bc_), settings (adm_set_),
setup guide (adm_setup_).
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import backup
import db
import text as T
import keyboards as K
from channel_lock import channel_lock_list, parse_channel_lock_list
from helpers import (admin_only, notify_admins, deliver_service,
                     panel_client_for, create_panel_client,
                     maybe_grant_referral_gift, send_md)
from panel import PanelError, gb_to_bytes, days_to_ms, extract_sub_id

log = logging.getLogger("hozhir")

SETTING_LABELS = {
    "welcome_text": "👋 متن خوش‌آمد",
    "support_text": "💬 متن پشتیبانی",
    "buy_guide": "🛒 راهنمای خرید",
    "delivery_guide": "📦 توضیح لینک دائمی",
    "test_enabled": "🎁 اکانت تست فعال باشد",
    "test_days": "🎁 مدت اکانت تست (روز)",
    "test_gb": "🎁 حجم اکانت تست (گیگ)",
    "warn_hours": "⏰ هشدار انقضا (ساعت قبل)",
    "warn_volume_pct": "📊 هشدار اتمام حجم (٪ مصرف)",
    "dl_android": "📱 لینک دانلود اندروید",
    "dl_ios": "🍎 لینک دانلود آیفون",
    "dl_windows": "💻 لینک دانلود ویندوز",
    "sub_base": "🔗 بیس لینک ساب",
    "ref_enabled": "👥 رفرال فعال باشد",
    "ref_gift_gb": "🎁 حجم هدیه رفرال (گیگ)",
    "ref_gift_days": "🎁 مدت هدیه رفرال (روز)",
    "crypto_enabled": "💎 پرداخت ارز دیجیتال فعال باشد",
    "evm_address": "📥 آدرس EVM دریافت",
    "etherscan_key": "🔑 کلید Etherscan",
    "crypto_expiry_min": "⏳ مهلت پرداخت (دقیقه)",
    "crypto_usd_toman": "💵 نرخ دستی دلار (تومان)",
}
NUMERIC_SETTINGS = {"test_days", "test_gb", "warn_hours", "warn_volume_pct",
                    "ref_gift_gb", "ref_gift_days",
                    "crypto_expiry_min"}
# GB settings accept fractions (e.g. 0.5); the rest are whole numbers.
GB_FLOAT_SETTINGS = {"test_gb", "ref_gift_gb"}


def _with_back(rows: list) -> InlineKeyboardMarkup:
    rows = [list(r) for r in rows]
    rows.append([InlineKeyboardButton("🔙 بازگشت به مدیریت",
                                      callback_data="adm_home")])
    return InlineKeyboardMarkup(rows)


async def _show(update: Update, text: str, kb=None, parse_mode=None) -> None:
    """Edit the message on callback, else send a new one."""
    q = update.callback_query
    if q:
        await q.answer()
        try:
            await q.edit_message_text(text, reply_markup=kb,
                                      parse_mode=parse_mode)
            return
        except Exception:
            pass
    await update.effective_message.reply_text(text, reply_markup=kb,
                                              parse_mode=parse_mode)


# ---------------- hub ----------------
@admin_only
async def admin_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin menu = bottom reply keyboard (mirzabot-style), not inline."""
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass
        try:
            await q.message.delete()
        except Exception:
            pass
    context.user_data.pop("st", None)
    await update.effective_message.reply_text(
        "🛠 پنل مدیریت «هژیر وی پی ان»", reply_markup=K.admin_sections())


async def to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass
        try:
            await q.message.delete()
        except Exception:
            pass
    context.user_data.pop("st", None)
    uid = update.effective_user.id
    await update.effective_message.reply_text(
        "🏠 منوی اصلی",
        reply_markup=K.main_menu(is_admin=config.is_admin(uid)))


# Bottom-menu admin navigation: section label -> section screen.
ADMIN_SECTIONS = {
    "📊 گزارش‌ها": "report_screen",
    "💳 پرداخت‌های در انتظار": "pending_payments",
    "🖥 مدیریت پنل": "panels_menu",
    "📡 اینباندها": "inbounds_menu",
    "📦 پلن‌ها": "plans_menu",
    "💳 کارت‌ها": "cards_menu",
    "👥 کاربران": "users_menu",
    "📚 آموزش‌ها": "tutorials_menu",
    "📢 پیام همگانی": "broadcast_home",
    "⚙️ تنظیمات": "settings_menu",
    "📖 آموزش راه‌اندازی": "setup_guide_home",
}


async def admin_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle admin bottom-menu buttons. Returns True if the text was handled."""
    t = (update.message.text or "").strip()
    uid = update.effective_user.id
    if t == "🔙 منوی اصلی":
        await to_main_menu(update, context)
        return True
    if not config.is_admin(uid):
        return False
    if t == "🛠 مدیریت":
        await admin_home(update, context)
        return True
    fname = ADMIN_SECTIONS.get(t)
    if fname:
        context.user_data.pop("st", None)
        await globals()[fname](update, context)
        return True
    return False


# ---------------- reports ----------------
@admin_only
async def report_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now = int(time.time())
    day_ago = now - 86400
    cnt, total = await db.sales_since(day_ago)
    renewals = await db.renewals_since(day_ago)
    new_users = await db.count_new_users_since(day_ago)
    tests_today = [i for i in await db.list_invoices(kind="test", limit=1000)
                   if i["created_at"] >= day_ago]
    exp = await db.expiring_soon(48)
    pend = await db.count_pending_payments()
    await _show(
        update,
        T.DAILY_REPORT.format(count=cnt, total=T.fmt_price(total),
                              renewals=renewals, new_users=new_users,
                              tests=len(tests_today))
        + f"\n\n⏳ در انتظار تأیید: {pend}\n⌛ در آستانه انقضا (۴۸ ساعت): {len(exp)}",
        K.back_admin_kb())


# ---------------- payments ----------------
@admin_only
async def pending_payments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # crypto invoices are auto-verified by chainwatch — not admin-approved
    pend = [i for i in await db.list_invoices(status="pending", limit=20)
            if i["kind"] != "test" and i.get("pay_method") != "crypto"]
    if not pend:
        await _show(update, "✅ پرداخت در انتظاری نیست.", K.back_admin_kb())
        return
    await _show(update, f"💳 {len(pend)} پرداخت در انتظار:",
                K.back_admin_kb())
    for inv in pend:
        plan = await db.get_plan(inv["plan_id"]) if inv.get("plan_id") else None
        label = (f"🧾 فاکتور #{inv['id']} — {T.KIND_FA.get(inv['kind'], inv['kind'])}\n"
                 f"👤 {inv['user_id']} | 📦 {plan['name'] if plan else '—'} | "
                 f"💰 {T.fmt_price(inv['price_toman'])}")
        kb = K.pay_decision_kb(inv["id"], manual=(inv["kind"] != "topup"))
        if inv["receipt_file_id"] and not inv["receipt_file_id"].startswith("text:"):
            try:
                await update.effective_message.reply_photo(
                    inv["receipt_file_id"], caption=label, reply_markup=kb)
                continue
            except Exception:
                pass
        extra = ""
        if inv["receipt_file_id"].startswith("text:"):
            extra = f"\n📝 {inv['receipt_file_id'][5:]}"
        await update.effective_message.reply_text(label + extra, reply_markup=kb)


async def approve_invoice(context: ContextTypes.DEFAULT_TYPE, inv: dict,
                          admin_id: int) -> str:
    """Create/extend the panel client. Returns Persian result message."""
    now = int(time.time())
    if inv.get("kind") == "topup":
        # wallet top-up: credit balance, no panel client needed
        new_bal = await db.add_balance(inv["user_id"], inv["price_toman"])
        await db.update_invoice(inv["id"], status="active", activated_at=now)
        await db.set_payment(inv["id"], "approved", admin_id)
        try:
            await context.bot.send_message(
                inv["user_id"],
                f"✅ کیف پولت {T.fmt_price(inv['price_toman'])} شارژ شد.\n"
                f"👜 موجودی فعلی: {T.fmt_price(new_bal)}")
        except Exception:
            pass
        return (f"✅ کیف پول کاربر {inv['user_id']} "
                f"{T.fmt_price(inv['price_toman'])} شارژ شد. "
                f"موجودی جدید: {T.fmt_price(new_bal)}")
    panel = await db.get_panel(inv["panel_id"]) if inv.get("panel_id") \
        else await db.get_active_panel()
    if not panel:
        return "⚠️ پنل فعالی ثبت نشده."
    if inv.get("kind") == "purchase" and not await db.panel_has_capacity(panel):
        # the cap filled up between payment and approval: refuse to build
        # a new client here; the invoice stays pending so the admin can
        # reject it (wallet buys refund automatically on non-active)
        return T.PANEL_CAP_FULL
    plan = await db.get_plan(inv["plan_id"]) if inv.get("plan_id") else None
    days = plan["days"] if plan else int(_to_float(await db.get_setting("test_days", "1"), 1))
    gb = plan["gb"] if plan else _to_float(await db.get_setting("test_gb", "2"), 2.0)
    pc = panel_client_for(panel)
    now = int(time.time())
    skipped: list[int] = []
    try:
        if inv["kind"] == "renew" and inv.get("panel_email"):
            # extend existing client; a client deleted from the panel
            # (get_client raises not-found) is recreated fresh instead
            # of failing the paid renewal
            try:
                client = await pc.get_client(inv["panel_email"])
            except PanelError as e:
                if e.is_not_found:
                    client = None
                else:
                    raise
            if client:
                cur_exp = client.get("expiryTime", 0) or 0
                base_ms = max(cur_exp, now * 1000)
                new_exp = base_ms + days_to_ms(days)
                cur_total = client.get("totalGB", 0) or 0
                new_total = (cur_total if cur_total > 0 else 0) + gb_to_bytes(gb)
                await pc.update_client(inv["panel_email"], {
                    "expiryTime": new_exp, "totalGB": new_total, "enable": True})
                email, sub_id = inv["panel_email"], inv["sub_id"]
            else:
                email, sub_id, skipped = await create_panel_client(pc, panel, inv, days, gb, now)
        else:
            email, sub_id, skipped = await create_panel_client(pc, panel, inv, days, gb, now)
    except PanelError as e:
        log.warning("panel op failed: %s", e)
        return f"⚠️ خطای پنل: {e}"
    expires_at = now + days * 86400
    if inv["kind"] == "renew" and inv.get("expires_at"):
        # stack on previous expiry if still in future
        expires_at = max(inv["expires_at"], now) + days * 86400
    await db.update_invoice(inv["id"], status="active", panel_id=panel["id"],
                            panel_email=email, sub_id=sub_id,
                            activated_at=now, expires_at=expires_at, warned_at=0,
                            volume_warned_at=0)  # clear orphan marker on (re)activation
    await db.set_payment(inv["id"], "approved", admin_id)
    ok = await deliver_service(context, await db.get_invoice(inv["id"]))
    extra = "" if ok else "\n⚠️ ارسال لینک‌ها ناموفق بود — از «سرویس‌های من» دوباره بگیر."
    if skipped:
        extra += ("\n⚠️ اینباندهای جاافتاده (توی پنل نیستن؛ سرویس فقط روی "
                  "بقیه اینباندها ساخته شد): "
                  + "، ".join(map(str, skipped))
                  + " — از «📡 اینباندها» حذفشون کن یا توی پنل دوباره بسازشون.")
    # referral: first paid purchase → gift for the referrer (silent to the buyer)
    await maybe_grant_referral_gift(context, inv)
    return f"✅ فاکتور #{inv['id']} فعال شد.{extra}"


async def on_pay_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not config.is_admin(q.from_user.id):
        await q.answer(T.NEED_ADMIN, show_alert=True)
        return
    parts = q.data.split(":")  # adm_pay_ok:<id> / adm_pay_no:<id>
    action = parts[0].rsplit("_", 1)[1]  # ok / no
    inv = await db.get_invoice(int(parts[1]))
    if not inv or inv["status"] != "pending":
        # legacy stuck buttons: acknowledge + remove the dead buttons
        await q.answer(T.PAYMENT_REVIEWED, show_alert=True)
        try:
            await q.edit_message_reply_markup(None)
        except Exception:
            pass
        return
    await q.answer("⏳ در حال پردازش…")
    if action == "ok":
        result = await approve_invoice(context, inv, q.from_user.id)
        for edit in (q.edit_message_caption, q.edit_message_text):
            try:
                await edit(f"✅ بررسی شد: فاکتور #{inv['id']}")
                break
            except Exception:
                continue
        await q.message.reply_text(result)
    else:
        await db.update_invoice(inv["id"], status="rejected")
        await db.set_payment(inv["id"], "rejected", q.from_user.id)
        try:
            await context.bot.send_message(inv["user_id"], T.PAYMENT_REJECTED)
        except Exception:
            pass
        for edit in (q.edit_message_caption, q.edit_message_text):
            try:
                await edit(f"❌ رد شد: فاکتور #{inv['id']}")
                break
            except Exception:
                continue
        await q.message.reply_text(f"❌ فاکتور #{inv['id']} رد شد.")


# ---------------- manual config attach ----------------
async def start_manual_config(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              iid: int) -> None:
    """Step 1 of the manual-config flow: ask the admin for the sub link.

    For a paid order whose panel creation failed (e.g. a deleted
    inbound), the admin builds the client in the panel by hand and
    pastes its subscription link here; the bot registers it on the
    invoice and delivers it to the customer, so renewals later extend
    the same config instead of the customer waiting on a bugfix.
    """
    inv = await db.get_invoice(iid)
    if not inv:
        await update.callback_query.answer("یافت نشد.", show_alert=True)
        return
    if inv.get("kind") == "topup":
        await update.callback_query.answer(
            "شارژ کیف پول کانفیگ ندارد.", show_alert=True)
        return
    if inv.get("status") not in ("pending", "active", "expired"):
        await update.callback_query.answer(
            "این فاکتور رد شده.", show_alert=True)
        return
    await ask_state(
        update, context, "a_manual_sub",
        "📎 لینک سابسکریپشن دستی رو بفرست:\n"
        "همون لینکی که از پنل کپی کردی (مثل "
        "https://host:2096/base/abcdef0123456789).\n\n"
        "بعدش ایمیل کلاینت توی پنل رو می‌پرسم تا تمدید هم روی همین "
        "کانفیگ کار کنه.",
        iid=iid)


async def _activate_manual_config(context: ContextTypes.DEFAULT_TYPE,
                                  inv: dict, panel: dict, email: str,
                                  sub_id: str, admin_id: int) -> str:
    """Register a hand-built panel client on an invoice and deliver it.

    Mirrors the tail of approve_invoice: mark active, store the panel
    identity, deliver the sub link + QR to the customer. Renewals later
    extend this same client (they look it up by panel_email).
    """
    now = int(time.time())
    plan = await db.get_plan(inv["plan_id"]) if inv.get("plan_id") else None
    days = plan["days"] if plan else int(_to_float(await db.get_setting("test_days", "1"), 1))
    expires_at = now + days * 86400
    if inv["kind"] == "renew" and inv.get("expires_at"):
        expires_at = max(inv["expires_at"], now) + days * 86400
    old_email = inv.get("panel_email") or ""
    await db.update_invoice(inv["id"], status="active", panel_id=panel["id"],
                            panel_email=email, sub_id=sub_id,
                            activated_at=now, expires_at=expires_at, warned_at=0,
                            volume_warned_at=0)
    await db.set_payment(inv["id"], "approved", admin_id)
    ok = await deliver_service(context, await db.get_invoice(inv["id"]))
    extra = "" if ok else "\n⚠️ ارسال لینک‌ها ناموفق بود — از «سرویس‌های من» دوباره بگیر."
    if old_email and old_email != email:
        extra += (f"\nℹ️ کلاینت قبلی ({old_email}) همچنان توی پنله — اگه "
                  "نمی‌خوایش، از دکمه 🗑 حذفش کن.")
    await maybe_grant_referral_gift(context, inv)
    return f"✅ کانفیگ دستی برای فاکتور #{inv['id']} ثبت شد.{extra}"


async def start_manual_send(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            tgid: int) -> None:
    """Send a hand-built config to any user (mirzabot's add-order-manual).

    The admin picks a plan first (it sets the expiry and the renewal
    price); then the sub link + panel email are collected exactly like
    the invoice flow, and the config is registered as the user's
    subscription so renewals later extend it.
    """
    q = update.callback_query
    plans = await db.list_plans(True)
    if not plans:
        await q.answer("پلن فعالی نیست.", show_alert=True)
        return
    rows = [[InlineKeyboardButton(
        f"📦 {p['name']} — {p['price_toman']:,} تومان",
        callback_data=f"adm_manual_plan:{tgid}:{p['id']}")] for p in plans]
    rows.append([InlineKeyboardButton("◀️ برگشت",
                                      callback_data=f"adm_users_view:{tgid}")])
    await q.edit_message_text(
        f"📎 ارسال کانفیگ دستی به کاربر {tgid}\n\nپلن رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(rows))


# ---------------- panels ----------------
@admin_only
async def panels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    panels = await db.list_panels(False)
    rows = []
    for p in panels:
        sold = await db.count_panel_sales(p["id"])
        full = not await db.panel_has_capacity(p, sold=sold)
        label = f"{'🟢' if p['active'] else '⚪'} {p['name']}"
        if full:
            label += " — 🔒 تکمیل ظرفیت"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"adm_panel_view:{p['id']}")])
    rows.append([InlineKeyboardButton("➕ افزودن پنل", callback_data="adm_panel_add")])
    await _show(update, "🖥 پنل‌ها:", _with_back(rows))


async def panel_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: int) -> None:
    q = update.callback_query
    p = await db.get_panel(pid)
    if not p:
        await q.answer("یافت نشد.", show_alert=True)
        return
    sold = await db.count_panel_sales(pid)
    cap = db.cap_of(p)
    cap_txt = f"{cap:,}" if cap else "نامحدود"
    txt = (f"🖥 {p['name']}\n🔗 {p['url']}\n"
           f"🔑 توکن: {config.mask_token(p['token'])}\n"
           f"📡 ساب: {p['sub_base'] or '—'}\n"
           f"🔌 اینباندها: {', '.join(map(str, p['inbounds'])) or '—'}\n"
           f"📊 فروش: {sold:,} / {cap_txt}\n"
           f"{'🟢 فعال' if p['active'] else '⚪ غیرفعال'}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔌 تست اتصال", callback_data=f"adm_panel_test:{pid}")],
        [InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"adm_panel_name:{pid}"),
         InlineKeyboardButton("📊 سقف فروش", callback_data=f"adm_panel_cap:{pid}")],
        [InlineKeyboardButton("✏️ ویرایش توکن", callback_data=f"adm_panel_token:{pid}"),
         InlineKeyboardButton("✏️ ویرایش آدرس", callback_data=f"adm_panel_url:{pid}")],
        [InlineKeyboardButton("✏️ ویرایش ساب", callback_data=f"adm_panel_sub:{pid}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"adm_panel_del:{pid}"),
         InlineKeyboardButton("◀️ برگشت", callback_data="adm_panel_home")],
    ])
    await q.edit_message_text(txt, reply_markup=kb)


async def panel_test(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: int) -> None:
    q = update.callback_query
    await q.answer("⏳ تست اتصال…")
    p = await db.get_panel(pid)
    pc = panel_client_for(p)
    res = await pc.test_connection()
    await q.message.reply_text(f"تست اتصال «{p['name']}»:\n{res['fa']}")


# ---------------- inbounds ----------------
@admin_only
async def inbounds_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    panels = await db.list_panels(False)
    rows = [[InlineKeyboardButton(f"📡 {p['name']}",
                                  callback_data=f"adm_inb_view:{p['id']}")]
            for p in panels]
    await _show(update, "📡 مدیریت اینباندها — پنل رو انتخاب کن:",
                _with_back(rows))


async def inbounds_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: int) -> None:
    q = update.callback_query
    p = await db.get_panel(pid)
    if not p:
        await q.answer("یافت نشد.", show_alert=True)
        return
    ref = (await db.get_setting("ref_client_email", "") or "").strip()
    rows = [[InlineKeyboardButton(f"❌ حذف {ib}",
                                  callback_data=f"adm_inb_del:{pid}:{ib}")]
            for ib in p["inbounds"]]
    rows.append([InlineKeyboardButton("➕ افزودن اینباند",
                                      callback_data=f"adm_inb_add:{pid}")])
    rows.append([InlineKeyboardButton("🎯 تنظیم مرجع از روی کانفیگ",
                                      callback_data=f"adm_inb_ref:{pid}")])
    rows.append([InlineKeyboardButton("◀️ برگشت", callback_data="adm_inb_home")])
    await q.edit_message_text(
        f"📡 اینباندهای «{p['name']}»:\n{', '.join(map(str, p['inbounds'])) or '—'}\n"
        f"🎯 مرجع: {ref or '—'}",
        reply_markup=InlineKeyboardMarkup(rows))


# ---------------- plans ----------------
@admin_only
async def plans_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plans = await db.list_plans(False)
    rows = [[InlineKeyboardButton(
        f"{'🟢' if p['active'] else '⚪'} {p['name']} — {p['price_toman']:,} تومان",
        callback_data=f"adm_plan_view:{p['id']}")] for p in plans]
    rows.append([InlineKeyboardButton("➕ پلن جدید", callback_data="adm_plan_add")])
    await _show(update, "📦 پلن‌ها:", _with_back(rows))


async def plan_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: int) -> None:
    q = update.callback_query
    p = await db.get_plan(pid)
    if not p:
        await q.answer("یافت نشد.", show_alert=True)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 فعال/غیرفعال",
                              callback_data=f"adm_plan_toggle:{pid}"),
         InlineKeyboardButton("🗑 حذف", callback_data=f"adm_plan_del:{pid}")],
        [InlineKeyboardButton("◀️ برگشت", callback_data="adm_plan_home")],
    ])
    await q.edit_message_text(T.plan_line(p), reply_markup=kb)


# ---------------- cards ----------------
@admin_only
async def cards_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cards = await db.list_cards(False)
    rows = [[InlineKeyboardButton(
        f"{'🟢' if c['active'] else '⚪'} {c['number']} — {c['holder']}",
        callback_data=f"adm_card_view:{c['id']}")] for c in cards]
    rows.append([InlineKeyboardButton("➕ کارت جدید", callback_data="adm_card_add")])
    await _show(update, "💳 کارت‌ها:", _with_back(rows))


async def card_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, cid: int) -> None:
    q = update.callback_query
    cards = {c["id"]: c for c in await db.list_cards(False)}
    c = cards.get(cid)
    if not c:
        await q.answer("یافت نشد.", show_alert=True)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 فعال/غیرفعال",
                              callback_data=f"adm_card_toggle:{cid}"),
         InlineKeyboardButton("🗑 حذف", callback_data=f"adm_card_del:{cid}")],
        [InlineKeyboardButton("◀️ برگشت", callback_data="adm_card_home")],
    ])
    await send_md(q.edit_message_text,
                  f"💳 `{c['number']}`\n👤 {c['holder']}", reply_markup=kb)


# ---------------- users ----------------
@admin_only
async def users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = await db.list_users(20)
    rows = [[InlineKeyboardButton(
        f"👤 {u['username'] or u['tg_id']} ({u['tg_id']})",
        callback_data=f"adm_users_view:{u['tg_id']}")] for u in users]
    await _show(update, f"👥 کاربران (آخرین {len(users)}):", _with_back(rows))


async def user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, tgid: int) -> None:
    q = update.callback_query
    bal = await db.get_balance(tgid)
    invs = await db.user_invoices(tgid, ("active", "expired"))
    rows = [[InlineKeyboardButton(
        f"📦 {plan_name} — {inv['panel_email']} ({inv['status']})",
        callback_data=f"adm_users_svc:{inv['id']}")]
        for inv in invs
        for plan_name in [((await db.get_plan(inv["plan_id"]) or {}).get("name")
                           if inv.get("plan_id") else "تست")]]
    rows.append([InlineKeyboardButton("💰 تغییر موجودی",
                                      callback_data=f"adm_users_bal:{tgid}")])
    rows.append([InlineKeyboardButton("📎 ارسال کانفیگ دستی",
                                      callback_data=f"adm_users_manualsend:{tgid}")])
    rows.append([InlineKeyboardButton("◀️ برگشت", callback_data="adm_users_home")])
    head = f"👤 {tgid}\n👜 موجودی کیف پول: {T.fmt_price(bal)}"
    if invs:
        await q.edit_message_text(f"{head}\n\nسرویس‌ها:",
                                  reply_markup=InlineKeyboardMarkup(rows))
    else:
        await q.edit_message_text(f"{head}\nسرویس فعالی ندارد.",
                                  reply_markup=InlineKeyboardMarkup(rows))


async def user_service_detail(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              iid: int) -> None:
    q = update.callback_query
    inv = await db.get_invoice(iid)
    if not inv:
        await q.answer("یافت نشد.", show_alert=True)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 غیرفعال در پنل",
                              callback_data=f"adm_users_dis:{iid}"),
         InlineKeyboardButton("✅ فعال در پنل",
                              callback_data=f"adm_users_en:{iid}")],
        [InlineKeyboardButton("🗑 حذف از پنل", callback_data=f"adm_users_del:{iid}"),
         InlineKeyboardButton("🔄 تعویض لینک اشتراک",
                              callback_data=f"adm_users_revoke:{iid}")],
        [InlineKeyboardButton("📎 ثبت کانفیگ دستی",
                              callback_data=f"adm_users_manual:{iid}")],
        [InlineKeyboardButton("◀️ برگشت",
                              callback_data=f"adm_users_view:{inv['user_id']}")],
    ])
    await q.edit_message_text(
        f"📦 فاکتور #{inv['id']}\n👤 {inv['user_id']}\n🔌 {inv['panel_email']}\n"
        f"📌 {inv['status']}", reply_markup=kb)


async def user_service_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not config.is_admin(q.from_user.id):
        await q.answer(T.NEED_ADMIN, show_alert=True)
        return
    parts = q.data.split(":")  # adm_users_dis:<id> etc.
    action = parts[0].rsplit("_", 1)[1]  # dis / en / del
    iid = int(parts[1])
    inv = await db.get_invoice(iid)
    if not inv or not inv.get("panel_email"):
        await q.answer("سرویس پنل ندارد.", show_alert=True)
        return
    panel = await db.get_panel(inv["panel_id"]) if inv.get("panel_id") \
        else await db.get_active_panel()
    if not panel:
        await q.answer("پنل یافت نشد.", show_alert=True)
        return
    pc = panel_client_for(panel)
    if action == "revoke":
        # Admin-only (user decision 2026-11-06): rotate the customer's
        # sub link when it leaked. The old link dies immediately, so the
        # new link is re-delivered to the customer right away.
        try:
            new_sub = await pc.revoke_sub(inv["panel_email"])
        except PanelError as e:
            if e.is_not_found:
                await q.answer("⚠️ سرویس در پنل یافت نشد — اول با تمدید، "
                               "اکانت تازه بساز.", show_alert=True)
            else:
                await q.answer(f"خطای پنل: {e}", show_alert=True)
            return
        await db.update_invoice(inv["id"], sub_id=new_sub)
        ok = await deliver_service(context, await db.get_invoice(iid))
        await q.answer("✅ لینک اشتراک عوض شد.")
        await q.message.reply_text(
            f"🔄 لینک اشتراک فاکتور #{iid} عوض شد.\n"
            + ("✅ لینک جدید برای مشتری ارسال شد."
               if ok else
               "⚠️ ارسال لینک جدید به مشتری ناموفق بود — "
               "از «سرویس‌های من» دوباره بگیر."))
        return
    try:
        if action == "dis":
            await pc.set_enable(inv["panel_email"], False)
            await q.answer("غیرفعال شد.")
        elif action == "en":
            await pc.set_enable(inv["panel_email"], True)
            await q.answer("فعال شد.")
        elif action == "del":
            await pc.delete_client(inv["panel_email"])
            await db.update_invoice(inv["id"], status="expired")
            await q.answer("از پنل حذف شد.")
    except PanelError as e:
        await q.answer(f"خطای پنل: {e}", show_alert=True)


# ---------------- tutorials ----------------
@admin_only
async def tutorials_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tuts = await db.list_tutorials(False)
    rows = [[InlineKeyboardButton(
        f"{'🟢' if t['active'] else '⚪'} {t['title']}",
        callback_data=f"adm_tut_view:{t['id']}")] for t in tuts]
    rows.append([InlineKeyboardButton("➕ افزودن آموزش", callback_data="adm_tut_add")])
    await _show(update, "📚 آموزش‌ها:", _with_back(rows))


async def tutorial_detail(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          tid: int) -> None:
    q = update.callback_query
    t = await db.get_tutorial(tid)
    if not t:
        await q.answer("یافت نشد.", show_alert=True)
        return
    preview = (t["body"][:200] + "…") if len(t["body"]) > 200 else t["body"]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ویرایش", callback_data=f"adm_tut_edit:{tid}")],
        [InlineKeyboardButton("🔄 فعال/غیرفعال",
                              callback_data=f"adm_tut_toggle:{tid}"),
         InlineKeyboardButton("🗑 حذف", callback_data=f"adm_tut_del:{tid}")],
        [InlineKeyboardButton("◀️ برگشت", callback_data="adm_tut_home")],
    ])
    await q.edit_message_text(
        f"{'🟢' if t['active'] else '⚪'} {t['title']}\n\n{preview}"
        f"\n\n🖼 عکس: {'دارد' if t['photo_file_id'] else 'ندارد'}",
        reply_markup=kb)


async def tutorial_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             tid: int) -> None:
    q = update.callback_query
    t = await db.get_tutorial(tid)
    if not t:
        await q.answer("یافت نشد.", show_alert=True)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ عنوان", callback_data=f"adm_tut_field:{tid}:title"),
         InlineKeyboardButton("📝 متن", callback_data=f"adm_tut_field:{tid}:body")],
        [InlineKeyboardButton("🖼 عکس", callback_data=f"adm_tut_field:{tid}:photo")],
        [InlineKeyboardButton("◀️ برگشت", callback_data=f"adm_tut_view:{tid}")],
    ])
    await q.edit_message_text(f"✏️ ویرایش «{t['title']}» — کدوم بخش؟",
                              reply_markup=kb)


# ---------------- broadcast ----------------
@admin_only
async def broadcast_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    n = len(await db.list_users(100000))
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ انصراف", callback_data="adm_bc_cancel")]])
    await ask_state(update, context, "a_bc_msg",
                    f"📢 پیام همگانی\n\nپیامی که می‌خوای برای **{n}** کاربر بفرستی رو "
                    "همین‌جا بفرست (متن، عکس، ویدیو...).\n"
                    "اول پیش‌نمایش می‌بینی، بعد تأیید می‌کنی.",
                    extra_kb=kb)


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    bc = context.user_data.pop("bc", None)
    context.user_data.pop("st", None)
    if not bc:
        await q.edit_message_text("⚠️ پیامی برای ارسال نیست.")
        return
    users = await db.list_users(100000)
    prog = await q.edit_message_text(f"⏳ در حال ارسال به {len(users)} کاربر…")
    ok = fail = 0
    for u in users:
        try:
            await context.bot.copy_message(chat_id=u["tg_id"],
                                           from_chat_id=bc["chat_id"],
                                           message_id=bc["message_id"])
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await prog.edit_text(f"📢 پیام همگانی تمام شد.\n✅ موفق: {ok}\n❌ ناموفق: {fail}",
                         reply_markup=K.back_admin_kb())


# ---------------- settings ----------------
@admin_only
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_on = await backup.auto_backup_on()
    chlock_on = await db.get_setting("channel_lock_enabled", "0") != "0"
    chlock_n = len(await channel_lock_list())
    chlock_label = (f"🔒 قفل کانال: {'✅ روشن' if chlock_on else '⚪️ خاموش'}"
                    + (f" ({chlock_n} کانال)" if chlock_n else ""))
    kb = _with_back([
        [InlineKeyboardButton("💬 متن‌ها", callback_data="adm_set_texts"),
         InlineKeyboardButton("🎁 اکانت تست", callback_data="adm_set_test")],
        [InlineKeyboardButton("⏰ هشدارها", callback_data="adm_set_warn"),
         InlineKeyboardButton("🔗 لینک ساب", callback_data="adm_set_sub")],
        [InlineKeyboardButton("📥 لینک دانلود برنامه‌ها", callback_data="adm_set_dl"),
         InlineKeyboardButton("👥 رفرال", callback_data="adm_set_ref")],
        [InlineKeyboardButton("💎 ارز دیجیتال", callback_data="adm_set_crypto")],
        [InlineKeyboardButton(chlock_label, callback_data="adm_set_chlock")],
        [InlineKeyboardButton("💾 بکاپ دیتابیس", callback_data="adm_set_backup"),
         InlineKeyboardButton(f"💾 بکاپ خودکار: {'✅ روشن' if auto_on else '⚪️ خاموش'}",
                              callback_data="adm_set_autobackup")],
    ])
    await _show(update, "⚙️ تنظیمات:", kb)


async def chlock_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Channel-lock settings: toggle + channel list (default OFF)."""
    on = await db.get_setting("channel_lock_enabled", "0") != "0"
    lst = await channel_lock_list()
    lines = [f"🔒 قفل کانال: {'✅ روشن' if on else '⚪️ خاموش'}"]
    if lst:
        lines.append("\nکانال‌ها:")
        for ch in lst:
            lines.append(f"• {ch}")
    else:
        lines.append("\nهنوز کانالی تنظیم نشده — قفل تا وقتی لیست خالی است بی‌اثر است.")
    if on and not lst:
        lines.append("\n⚠️ قفل روشن است ولی لیست خالی است؛ اول کانال اضافه کن.")
    lines.append("\nکاربر تا عضو همه کانال‌ها نباشد نمی‌تواند از ربات استفاده کند؛ ادمین‌ها معاف‌اند.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔒 قفل: {'✅ روشن' if on else '⚪️ خاموش'} — تغییر وضعیت",
            callback_data="adm_set_chlock_tgl")],
        [InlineKeyboardButton("✏️ تنظیم کانال‌ها",
                              callback_data="adm_set_chlock_set")],
        [InlineKeyboardButton("◀️ برگشت", callback_data="adm_set_home")],
    ])
    await _show(update, "\n".join(lines), kb)


async def _setting_value(key: str) -> str:
    if key == "sub_base":
        p = await db.get_active_panel()
        return (p or {}).get("sub_base", "")
    if key in ("test_enabled", "ref_enabled", "crypto_enabled"):
        return "فعال ✅" if await db.get_setting(key, "1") == "1" else "غیرفعال ❌"
    if key == "etherscan_key":
        return config.mask_token(await db.get_setting(key, ""))
    return await db.get_setting(key, "")


@admin_only
async def settings_group(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         group: str) -> None:
    groups = {
        "texts": ("💬 متن‌ها:", ["welcome_text", "support_text", "buy_guide",
                                 "delivery_guide"]),
        "test": ("🎁 اکانت تست:", ["test_enabled", "test_days", "test_gb"]),
        "warn": ("⏰ هشدارها:", ["warn_hours", "warn_volume_pct"]),
        "sub": ("🔗 لینک ساب:", ["sub_base"]),
        "dl": ("📥 لینک دانلود برنامه‌ها:", ["dl_android", "dl_ios", "dl_windows"]),
        "ref": ("👥 رفرال:", ["ref_enabled", "ref_gift_gb", "ref_gift_days"]),
        "crypto": ("💎 ارز دیجیتال:", ["crypto_enabled", "evm_address",
                                       "etherscan_key", "crypto_expiry_min",
                                       "crypto_usd_toman"]),
    }
    title, keys = groups[group]
    if group == "crypto":
        title += ("\n\n🔐 کلید خصوصی را هرگز وارد نکنید — "
                  "فقط همین آدرس عمومی کافی است.")
    rows = []
    for key in keys:
        if key in ("test_enabled", "ref_enabled", "crypto_enabled"):
            val = await _setting_value(key)
            rows.append([InlineKeyboardButton(
                f"{SETTING_LABELS[key]}: {val}",
                callback_data=f"adm_set_toggle:{key}:{group}")])
            continue
        val = await _setting_value(key)
        shown = (val[:35] + "…") if len(val) > 35 else (val or "—")
        rows.append([InlineKeyboardButton(f"{SETTING_LABELS[key]}: {shown}",
                                          callback_data=f"adm_set_key:{key}")])
    rows.append([InlineKeyboardButton("◀️ برگشت", callback_data="adm_set_home")])
    await _show(update, title, _with_back(rows))


# ---------------- setup guide (first-run wizard) ----------------
# Entry: "📖 آموزش راه‌اندازی" in the admin bottom menu. The wizard
# walks a new admin through the first setup step by step — panel name,
# panel URL, API token, sub base, inbounds, bank card — then tests the
# panel connection. Every step can be skipped; answers are saved as they
# come in, so leaving mid-way keeps the progress.
SETUP_ORDER = ["name", "url", "token", "sub", "inb", "card", "holder"]

SETUP_PROMPTS = {
    "name": ("🖥 قدم ۱ از ۷ — اسم این سرور چیه؟\n"
             "مثلاً «سرور کانادا» — همین اسم موقع خرید به مشتری نشون داده می‌شه."),
    "url": ("🔗 قدم ۲ از ۷ — آدرس پنل چیه؟\n"
            "مثلاً `https://host:port/base`\n"
            "همون آدرسی که باهاش وارد پنل 3x-ui می‌شی."),
    "token": ("🔑 قدم ۳ از ۷ — توکن API پنل چیه؟\n"
              "از پنل: Settings ← API — یه توکن با دسترسی admin بساز و بفرست."),
    "sub": ("📡 قدم ۴ از ۷ — بیس لینک ساب چیه؟\n"
            "مثلاً `https://host:2096/hard/`\n"
            "همون لینکی که توی پنل، بخش Subscription می‌بینی."),
    "inb": ("🔌 قدم ۵ از ۷ — آیدی اینباندها چیه؟\n"
            "با کاما جدا کن، مثلاً `1,9,11`.\n"
            "اگه هنوز اینباند نساختی، این قدم رو رد کن و بعداً از «📡 اینباندها» اضافه کن."),
    "card": ("💳 قدم ۶ از ۷ — شماره کارتت چیه؟\n"
             "همون کارتی که مشتری‌ها مبلغ رو بهش واریز می‌کنن."),
    "holder": "👤 قدم ۷ از ۷ — نام صاحب کارت چیه؟",
}


def _setup_next(step: str) -> str:
    i = SETUP_ORDER.index(step)
    return SETUP_ORDER[i + 1] if i + 1 < len(SETUP_ORDER) else "test"


async def _setup_advance(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         step: str, carried: dict) -> None:
    """Go to the next wizard step — or straight to the test when done.

    A card step is skipped when a card already exists (the wizard is
    for the first setup, not for adding a second card).
    """
    nxt = _setup_next(step)
    if step == "inb" and nxt == "card" and await db.list_cards(False):
        await _setup_finish(update, context)
        return
    if nxt == "test":
        await _setup_finish(update, context)
        return
    await _setup_ask(update, context, nxt, carried)


async def _setup_checklist() -> list[str]:
    p = await db.get_active_panel()
    cards = await db.list_cards(False)
    plans = await db.list_plans(False)

    def chk(ok: bool, label: str, cur: str = "") -> str:
        return f"{'✅' if ok else '⬜'} {label}" + (f" — {cur}" if cur else "")

    return [
        chk(bool(p and p.get("url")), "آدرس پنل", (p or {}).get("url", "")),
        chk(bool(p and p.get("token")), "توکن API پنل",
            config.mask_token(p["token"]) if p and p.get("token") else ""),
        chk(bool(p and p.get("sub_base")), "بیس لینک ساب",
            (p or {}).get("sub_base", "")),
        chk(bool(p and p.get("inbounds")), "اینباندها",
            ", ".join(map(str, (p or {}).get("inbounds") or []))),
        chk(bool(cards), "کارت بانکی",
            f"{len(cards)} کارت" if cards else ""),
        chk(bool(plans), "پلن‌ها",
            f"{len(plans)} پلن" if plans else "۴ پلن پیش‌فرض در اولین اجرا ساخته می‌شن"),
    ]


@admin_only
async def setup_guide_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = await _setup_checklist()
    text = ("📖 آموزش راه‌اندازی — قدم‌به‌قدم\n\n" + "\n".join(lines) +
            "\n\nدکمه‌ی شروع رو بزن؛ هر قدم رو می‌تونی رد کنی و هر وقت خواستی "
            "با ❌ خارج بشی. جواب‌هایی که تا اینجا دادی ذخیره می‌مونن.")
    kb = _with_back([[InlineKeyboardButton("▶️ شروع راه‌اندازی",
                                           callback_data="adm_setup_start")]])
    await _show(update, text, kb)


async def _setup_ask(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     step: str, carried: dict) -> None:
    """Ask one wizard step; `carried` values travel in the state dict."""
    p = await db.get_active_panel()
    cur = ""
    if step == "name" and p and p.get("name"):
        cur = f"\nفعلی: {p['name']}"
    elif step == "url" and p and p.get("url"):
        cur = f"\nفعلی: {p['url']}"
    elif step == "token" and p and p.get("token"):
        cur = f"\nفعلی: {config.mask_token(p['token'])}"
    elif step == "sub" and p and p.get("sub_base"):
        cur = f"\nفعلی: {p['sub_base']}"
    elif step == "inb" and p and p.get("inbounds"):
        cur = "\nفعلی: " + ", ".join(map(str, p["inbounds"]))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ رد کردن",
                              callback_data=f"adm_setup_skip:{step}"),
         InlineKeyboardButton("❌ خروج", callback_data="adm_setup_exit")],
    ])
    await ask_state(update, context, f"a_setup_{step}",
                    SETUP_PROMPTS[step] + cur, extra_kb=kb, **carried)


async def _setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Begin at the first incomplete step (or the first step, to redo)."""
    p = await db.get_active_panel()
    cards = await db.list_cards(False)
    done = {
        # the env-seeded default name is not a real choice yet
        "name": bool(p and p.get("name") and p["name"] != "پنل اصلی"),
        "url": bool(p and p.get("url")),
        "token": bool(p and p.get("token")),
        "sub": bool(p and p.get("sub_base")),
        "inb": bool(p and p.get("inbounds")),
        "card": bool(cards),
        "holder": bool(cards),
    }
    step = next((s for s in SETUP_ORDER if not done[s]), "url")
    await _setup_ask(update, context, step, {})


async def _setup_save_panel(st: dict, inb: list[int]) -> None:
    """Persist the wizard's panel answers (create or update the active panel)."""
    p = await db.get_active_panel()
    fields = {"inbounds_json": json.dumps(sorted(set(inb)))}
    if st.get("name"):
        fields["name"] = st["name"]
    if st.get("url"):
        fields["url"] = st["url"]
    if st.get("token"):
        fields["token"] = st["token"]
    if st.get("sub"):
        fields["sub_base"] = st["sub"]
    if p:
        await db.update_panel(p["id"], **fields)
    else:
        await db.add_panel(st.get("name") or "پنل اصلی", st.get("url", ""),
                           st.get("token", ""), st.get("sub", ""),
                           sorted(set(inb)))


async def _setup_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Last step: test the panel connection and show the summary."""
    context.user_data.pop("st", None)
    p = await db.get_active_panel()
    if not p or not p.get("url"):
        await _show(update,
                    "⚠️ هنوز پنلی ثبت نشده — از «🖥 مدیریت پنل» یا همین آموزش، "
                    "اول آدرس پنل رو کامل کن.",
                    _with_back([]))
        return
    pc = panel_client_for(p)
    res = await pc.test_connection()
    cards = await db.list_cards(False)
    plans = await db.list_plans(False)
    text = ("🎉 راه‌اندازی کامل شد!\n\n"
            f"🖥 پنل: {p['name']} ({p['url']})\n"
            f"📡 اینباندها: {', '.join(map(str, p['inbounds'])) or '—'}\n"
            f"💳 کارت: {len(cards)} عدد\n"
            f"📦 پلن: {len(plans)} عدد (قیمت‌ها رو از «📦 پلن‌ها» عوض کن)\n\n"
            f"🔌 تست اتصال: {res['fa']}\n\n"
            "یه خرید آزمایشی با یه اکانت تلگرام دیگه بگیر تا مطمئن بشی "
            "لینک ساب تحویل داده می‌شه.")
    await _show(update, text, _with_back([]))


async def _setup_answer(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        st: dict, step: str, txt: str) -> None:
    """One wizard answer: validate, save, advance. `st` is user_data['st']."""
    msg = update.message
    carried = {k: v for k, v in st.items() if k != "k"}
    if step == "name":
        if not txt:
            await msg.reply_text("❌ اسم خالیه — یه اسم بفرست:")
            return
        carried["name"] = txt[:60]
    elif step == "url":
        if not txt or not txt.startswith(("http://", "https://")):
            await msg.reply_text(
                "❌ آدرس معتبر نیست — باید با http:// یا https:// شروع بشه. "
                "دوباره بفرست:")
            return
        carried["url"] = txt.rstrip("/")
    elif step == "token":
        if not txt:
            await msg.reply_text("❌ توکن خالیه — توکن API پنل رو بفرست:")
            return
        carried["token"] = txt
    elif step == "sub":
        if not txt:
            await msg.reply_text("❌ بیس ساب خالیه — لینک ساب رو بفرست:")
            return
        carried["sub"] = txt.rstrip("/")
    elif step == "inb":
        inb = [int(x) for x in txt.split(",") if x.strip().isdigit()]
        if not inb:
            await msg.reply_text("❌ آیدی معتبر نیست — مثلاً `1,9,11` بفرست:")
            return
        await _setup_save_panel(carried, inb)
    elif step == "card":
        if not txt.replace(" ", "").isdigit():
            await msg.reply_text("شماره کارت فقط عدد باشه:")
            return
        carried["number"] = txt.replace(" ", "")
    elif step == "holder":
        await db.add_card(carried.get("number", ""), txt)
        await _setup_finish(update, context)
        return
    await _setup_advance(update, context, step, carried)


async def _setup_skip(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      step: str) -> None:
    """Skip one wizard step (from the ⏭ button on the prompt message)."""
    st = context.user_data.get("st") or {}
    if st.get("k") != f"a_setup_{step}":
        await setup_guide_home(update, context)
        return
    carried = {k: v for k, v in st.items() if k != "k"}
    if step == "inb":
        p = await db.get_active_panel()
        if p or carried.get("url") or carried.get("token") or carried.get("sub"):
            await _setup_save_panel(carried, list(p["inbounds"]) if p else [])
    elif step == "card":
        # no card at all — go straight to the test
        await _setup_finish(update, context)
        return
    elif step == "holder":
        if carried.get("number"):
            await db.add_card(carried["number"], "—")
        await _setup_finish(update, context)
        return
    await _setup_advance(update, context, step, carried)


# ---------------- state machine (admin text/media input) ----------------
async def ask_state(update: Update, context: ContextTypes.DEFAULT_TYPE,
                    kind: str, prompt: str, extra_kb=None, **extra) -> None:
    """Ask the admin for the next input and remember what it is for.

    The prompt is sent as Markdown, with a plain-text retry: a literal
    underscore in an example (shahin_1234) breaks Markdown parsing and
    used to fail the whole tap silently (the error alert could not be
    shown either, because the query was already answered). The state is
    only stored after the prompt was actually delivered, so a failed
    prompt never leaves the bot waiting for input the admin never saw.
    """
    q = update.callback_query
    msg = q.message if q else update.message
    if q:
        await q.answer()
    try:
        await msg.reply_text(prompt, reply_markup=extra_kb,
                             parse_mode="Markdown")
    except Exception:
        await msg.reply_text(prompt, reply_markup=extra_kb)
    context.user_data["st"] = {"k": kind, **extra}


def _num(txt: str) -> int | None:
    t = txt.strip().replace(",", "").replace("٬", "")
    fa = "۰۱۲۳۴۵۶۷۸۹"
    for i, ch in enumerate(fa):
        t = t.replace(ch, str(i))
    return int(t) if t.isdigit() else None


def _fnum(txt: str) -> float | None:
    """Parse a (possibly fractional) number; accepts 0.5 / ۰.۵ / 0,5."""
    t = txt.strip().replace("٬", ",").replace("٫", ",")
    fa = "۰۱۲۳۴۵۶۷۸۹"
    for i, ch in enumerate(fa):
        t = t.replace(ch, str(i))
    if "," in t and "." not in t:
        t = t.replace(",", ".")  # decimal comma
    else:
        t = t.replace(",", "")  # thousand separator
    try:
        return float(t)
    except ValueError:
        return None


def _to_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _snum(txt: str) -> int | None:
    """Signed number (Persian digits ok). None on invalid."""
    t = txt.strip().replace(",", "").replace("٬", "")
    fa = "۰۱۲۳۴۵۶۷۸۹"
    for i, ch in enumerate(fa):
        t = t.replace(ch, str(i))
    body = t[1:] if t[:1] in ("-", "+") else t
    if not body.isdigit():
        return None
    n = int(body)
    return -n if t.startswith("-") else n


async def handle_admin_state(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             st: dict) -> bool:
    """Returns True if the state was an admin state (handled or not)."""
    k = st.get("k", "")
    if not (k.startswith("a_") or k in ("admin_reply",)):
        return False
    if not config.is_admin(update.effective_user.id):
        context.user_data.pop("st", None)
        return True
    msg = update.message
    txt = (msg.text or "").strip() if msg else ""
    try:
        if k == "a_padd_name":
            context.user_data["st"] = {"k": "a_padd_url", "name": txt}
            await msg.reply_text("🔗 آدرس پنل (مثل https://host:port/base):")
        elif k == "a_padd_url":
            context.user_data["st"] = {"k": "a_padd_token", "name": st["name"],
                                       "url": txt.rstrip("/")}
            await msg.reply_text("🔑 توکن API پنل (دسترسی admin):")
        elif k == "a_padd_token":
            context.user_data["st"] = {"k": "a_padd_sub", "name": st["name"],
                                       "url": st["url"], "token": txt}
            await msg.reply_text("📡 بیس لینک ساب (مثل https://host:2096/xxxx):")
        elif k == "a_padd_sub":
            context.user_data["st"] = {"k": "a_padd_inb", "name": st["name"],
                                       "url": st["url"], "token": st["token"],
                                       "sub": txt.rstrip("/")}
            await msg.reply_text("🔌 آیدی اینباندها با کاما (مثل 1,9,11):")
        elif k == "a_padd_inb":
            inb = [int(x) for x in txt.split(",") if x.strip().isdigit()]
            pid = await db.add_panel(st["name"], st["url"], st["token"],
                                     st["sub"], inb)
            context.user_data.pop("st", None)
            await msg.reply_text(f"✅ پنل «{st['name']}» اضافه شد (#{pid}).")
        elif k == "a_ptoken":
            await db.update_panel(st["pid"], token=txt)
            context.user_data.pop("st", None)
            await msg.reply_text("✅ توکن به‌روز شد.")
        elif k == "a_purl":
            await db.update_panel(st["pid"], url=txt.rstrip("/"))
            context.user_data.pop("st", None)
            await msg.reply_text("✅ آدرس به‌روز شد.")
        elif k == "a_psub":
            await db.update_panel(st["pid"], sub_base=txt.rstrip("/"))
            context.user_data.pop("st", None)
            await msg.reply_text("✅ بیس ساب به‌روز شد.")
        elif k == "a_pname":
            name = txt[:60]
            if not name:
                await msg.reply_text("❌ نام خالیه — یه اسم بفرست:")
                return True
            await db.update_panel(st["pid"], name=name)
            context.user_data.pop("st", None)
            await msg.reply_text(f"✅ نام پنل شد «{name}».")
        elif k == "a_pcap":
            # 0 / empty = unlimited (stored as NULL)
            if txt in ("0", "۰", "نامحدود", "—", ""):
                n = None
            else:
                n = _num(txt)
                if n is None or n < 0:
                    await msg.reply_text("❌ یه عدد بفرست — صفر یعنی نامحدود:")
                    return True
                n = n or None
            await db.update_panel(st["pid"], sales_cap=n)
            context.user_data.pop("st", None)
            await msg.reply_text("✅ سقف فروش برداشته شد — نامحدود."
                                 if n is None else
                                 f"✅ سقف فروش شد {n:,} کانفیگ.")
        elif k == "a_chlock_set":
            lst = parse_channel_lock_list(txt)
            await db.set_setting("channel_lock_list",
                                 json.dumps(lst, ensure_ascii=False))
            context.user_data.pop("st", None)
            await msg.reply_text(f"✅ {len(lst)} کانال ثبت شد."
                                 if lst else "✅ لیست کانال‌ها خالی شد.")
        elif k == "a_inbadd":
            p = await db.get_panel(st["pid"])
            inb = p["inbounds"] + [int(txt)] if txt.isdigit() else p["inbounds"]
            await db.update_panel(st["pid"],
                                  inbounds_json=json.dumps(sorted(set(inb))))
            context.user_data.pop("st", None)
            await msg.reply_text("✅ اینباند اضافه شد.")
        elif k == "a_inbref":
            email = txt.strip()
            if not email or any(ch.isspace() for ch in email) \
                    or "/" in email or ":" in email:
                await msg.reply_text(
                    "❌ ایمیل معتبر نیست — فقط خود ایمیل رو بفرست:")
                return True
            p = await db.get_panel(st["pid"])
            if not p:
                context.user_data.pop("st", None)
                await msg.reply_text("⚠️ پنل پیدا نشد.")
                return True
            pc = panel_client_for(p)
            try:
                ids = await pc.client_inbounds(email)
            except PanelError as e:
                if e.is_not_found:
                    await msg.reply_text(
                        "❌ این ایمیل توی پنل پیدا نشد — ایمیل رو چک کن و "
                        "دوباره بفرست:")
                    return True
                await msg.reply_text(f"⚠️ خطای پنل: {e} — دوباره تلاش کن:")
                return True
            if not ids:
                await msg.reply_text(
                    "⚠️ این کانفیگ اینباندی نداره — یه کانفیگ دیگه بفرست:")
                return True
            await db.set_setting("ref_client_email", email)
            await db.update_panel(p["id"],
                                  inbounds_json=json.dumps(sorted(ids)))
            context.user_data.pop("st", None)
            await msg.reply_text(
                f"✅ مرجع ثبت شد: {email}\n"
                f"📡 اینباندها از روی این کانفیگ: "
                f"{', '.join(map(str, sorted(ids)))}\n"
                "از این به بعد سرویس‌های جدید با همین اینباندها ساخته می‌شن.")
        elif k == "a_planadd_name":
            context.user_data["st"] = {"k": "a_planadd_days", "name": txt}
            await msg.reply_text("⏱ مدت (روز)؟")
        elif k == "a_planadd_days":
            n = _num(txt)
            if n is None or n <= 0:
                await msg.reply_text("عدد معتبر بفرست:")
                return True
            context.user_data["st"] = {"k": "a_planadd_gb", "name": st["name"],
                                       "days": n}
            await msg.reply_text("💾 حجم (گیگ)؟")
        elif k == "a_planadd_gb":
            n = _fnum(txt)
            if n is None or n <= 0:
                await msg.reply_text("عدد معتبر بفرست (مثلاً 0.5):")
                return True
            context.user_data["st"] = {"k": "a_planadd_price", "name": st["name"],
                                       "days": st["days"], "gb": n}
            await msg.reply_text("💰 قیمت (تومان)؟")
        elif k == "a_planadd_price":
            n = _num(txt)
            if n is None or n < 0:
                await msg.reply_text("عدد معتبر بفرست:")
                return True
            pid = await db.add_plan(st["name"], st["days"], st["gb"], n)
            context.user_data.pop("st", None)
            await msg.reply_text(f"✅ پلن اضافه شد (#{pid}).")
        elif k == "a_cardadd_num":
            if not txt.replace(" ", "").isdigit():
                await msg.reply_text("شماره کارت فقط عدد باشه:")
                return True
            context.user_data["st"] = {"k": "a_cardadd_holder",
                                       "number": txt.replace(" ", "")}
            await msg.reply_text("👤 نام صاحب کارت؟")
        elif k == "a_cardadd_holder":
            await db.add_card(st["number"], txt)
            context.user_data.pop("st", None)
            await msg.reply_text("✅ کارت اضافه شد.")
        elif k == "a_setkey":
            key = st["key"]
            if key == "evm_address":
                txt = txt.strip()
                if not re.fullmatch(r"0x[0-9a-fA-F]{40}", txt):
                    await msg.reply_text(
                        "❌ آدرس معتبر نیست. باید با 0x شروع بشه و ۴۰ کاراکتر هگز باشه.")
                    return True
            elif key == "crypto_usd_toman":
                txt = txt.strip()
                if txt:
                    n = _fnum(txt)
                    if n is None or n <= 0:
                        await msg.reply_text("عدد معتبر بفرست یا خالی بذار:")
                        return True
                    txt = "%g" % n
            elif key in NUMERIC_SETTINGS:
                if key in GB_FLOAT_SETTINGS:
                    n = _fnum(txt)
                    if n is None or n <= 0:
                        await msg.reply_text("عدد معتبر بفرست (مثلاً 0.5):")
                        return True
                    txt = "%g" % n
                else:
                    n = _num(txt)
                    if n is None or n <= 0:
                        await msg.reply_text("عدد معتبر بفرست:")
                        return True
                    txt = str(n)
            if key == "sub_base":
                p = await db.get_active_panel()
                if p:
                    await db.update_panel(p["id"], sub_base=txt.rstrip("/"))
            else:
                await db.set_setting(key, txt)
            context.user_data.pop("st", None)
            await msg.reply_text("✅ ذخیره شد.")
        elif k == "a_tutadd_title":
            context.user_data["st"] = {"k": "a_tutadd_body", "title": txt}
            await msg.reply_text("📝 متن آموزش؟ (می‌تونی از {dl_android}، {dl_ios}، "
                                 "{dl_windows} برای لینک دانلود استفاده کنی)")
        elif k == "a_tutadd_body":
            context.user_data["st"] = {"k": "a_tutadd_photo", "title": st["title"],
                                       "body": txt}
            await msg.reply_text(T.TUTORIAL_PHOTOS_HINT)
        elif k == "a_tutadd_photo":
            photo_id = ""
            if msg and msg.photo:
                photo_id = msg.photo[-1].file_id
            elif txt.lower() not in ("رد", "بدون عکس", "skip", "⏭"):
                await msg.reply_text("🖼 عکس بفرست یا بنویس «رد».")
                return True
            tid = await db.add_tutorial(st["title"], st["body"], photo_id)
            context.user_data.pop("st", None)
            await msg.reply_text(f"✅ آموزش اضافه شد (#{tid}).")
        elif k == "a_tutedit":
            field, tid = st["field"], st["tid"]
            if field == "photo":
                if msg and msg.photo:
                    await db.update_tutorial(tid,
                                             photo_file_id=msg.photo[-1].file_id)
                elif txt.lower() in ("حذف", "رد", "بدون عکس"):
                    await db.update_tutorial(tid, photo_file_id="")
                else:
                    await msg.reply_text("🖼 عکس بفرست یا بنویس «حذف».")
                    return True
            else:
                await db.update_tutorial(tid, **{field: txt})
            context.user_data.pop("st", None)
            await msg.reply_text("✅ ذخیره شد.")
        elif k == "a_bc_msg":
            if not msg:
                return True
            context.user_data["bc"] = {"chat_id": msg.chat.id,
                                       "message_id": msg.message_id}
            context.user_data.pop("st", None)
            try:
                await context.bot.copy_message(
                    chat_id=msg.chat.id, from_chat_id=msg.chat.id,
                    message_id=msg.message_id)
            except Exception as e:
                await msg.reply_text(f"⚠️ پیش‌نمایش ناموفق بود: {e}")
                return True
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ارسال به همه",
                                      callback_data="adm_bc_yes"),
                 InlineKeyboardButton("❌ لغو", callback_data="adm_bc_no")],
            ])
            await msg.reply_text("👆 پیش‌نمایش بالا. ارسال بشه؟",
                                 reply_markup=kb)
        elif k == "admin_reply":
            try:
                await context.bot.send_message(st["tgid"], f"💬 پشتیبانی:\n{txt}")
                await msg.reply_text("✅ جواب ارسال شد.")
            except Exception as e:
                await msg.reply_text(f"⚠️ ارسال نشد: {e}")
            context.user_data.pop("st", None)
        elif k == "a_manual_sub":
            sub_id = extract_sub_id(txt)
            if not sub_id:
                await msg.reply_text(
                    "❌ لینک ساب معتبر نیست.\n"
                    "لینک سابسکریپشن رو کامل بفرست — مثل:\n"
                    "https://host:2096/base/abcdef0123456789")
                return True
            context.user_data["st"] = {"k": "a_manual_email",
                                       "iid": st.get("iid"),
                                       "tgid": st.get("tgid"),
                                       "plan_id": st.get("plan_id"),
                                       "sub_id": sub_id}
            await msg.reply_text(
                "🔌 ایمیل کلاینت توی پنل چیه؟\n"
                "همون ایمیلی که موقع ساخت دستی توی 3x-ui وارد کردی "
                "(مثلاً `name_1234`).")
        elif k == "a_manual_email":
            email = txt.strip()
            if not email or any(ch.isspace() for ch in email) \
                    or "/" in email or ":" in email:
                await msg.reply_text(
                    "❌ ایمیل معتبر نیست — فقط خود ایمیل رو بفرست:")
                return True
            if st.get("iid"):
                inv = await db.get_invoice(st["iid"])
                if not inv:
                    context.user_data.pop("st", None)
                    await msg.reply_text("⚠️ فاکتور پیدا نشد.")
                    return True
            else:
                # per-user send: no invoice yet — created after the
                # email checks out, so an abandoned flow leaves nothing
                inv = None
            panel = await db.get_panel(inv["panel_id"]) if inv and inv.get("panel_id") \
                else await db.get_active_panel()
            if not panel:
                context.user_data.pop("st", None)
                await msg.reply_text("⚠️ پنل فعالی ثبت نشده.")
                return True
            pc = panel_client_for(panel)
            unverified = False
            try:
                client = await pc.get_client(email)
                if not client:
                    raise PanelError("not found", code="notfound")
            except PanelError as e:
                if e.is_not_found:
                    await msg.reply_text(
                        "❌ این ایمیل توی پنل پیدا نشد — ایمیل رو چک کن و "
                        "دوباره بفرست:")
                    return True
                unverified = True
                log.warning("manual config: panel verify failed (%s); "
                            "proceeding unverified", e)
            if inv is None:
                plan = await db.get_plan(st["plan_id"])
                if not plan:
                    context.user_data.pop("st", None)
                    await msg.reply_text("⚠️ پلن پیدا نشد.")
                    return True
                iid = await db.create_invoice(st["tgid"], "purchase",
                                              plan["id"], plan["price_toman"])
                inv = await db.get_invoice(iid)
            res = await _activate_manual_config(context, inv, panel, email,
                                                st["sub_id"],
                                                update.effective_user.id)
            context.user_data.pop("st", None)
            if unverified:
                res += ("\n⚠️ پنل موقع ثبت در دسترس نبود و ایمیل تأیید نشد — "
                        "اگه تمدید به مشکل خورد، ایمیل رو چک کن.")
            await msg.reply_text(res)
        elif k == "a_bal":
            n = _snum(txt)
            if n is None or n == 0:
                await msg.reply_text("عدد معتبر بفرست (مثبت=افزایش، منفی=کاهش):")
                return True
            new_bal = await db.add_balance(st["tgid"], n)
            context.user_data.pop("st", None)
            try:
                await context.bot.send_message(
                    st["tgid"],
                    f"👜 موجودی کیف پولت {'+' if n > 0 else ''}{n:,} تومان تغییر کرد.\n"
                    f"💰 موجودی فعلی: {T.fmt_price(new_bal)}")
            except Exception:
                pass
            await msg.reply_text(
                f"✅ موجودی کاربر {st['tgid']} به {T.fmt_price(new_bal)} رسید.")
        elif k.startswith("a_setup_"):
            await _setup_answer(update, context, st, k[len("a_setup_"):], txt)
        else:
            return False
    except Exception as e:
        log.warning("admin state error: %s", e)
        await msg.reply_text(f"⚠️ خطا: {e}")
    return True


# ---------------- admin callback router ----------------
async def on_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data or ""
    if not config.is_admin(q.from_user.id):
        await q.answer(T.NEED_ADMIN, show_alert=True)
        return
    parts = data.split(":")
    try:
        if data == "adm_home":
            await admin_home(update, context)
        elif data == "adm_tomain":
            await to_main_menu(update, context)
        # reports
        elif data == "adm_rep_home":
            await report_screen(update, context)
        # payments
        elif data == "adm_pay_home":
            await pending_payments(update, context)
        elif data.startswith("adm_pay_ok:") or data.startswith("adm_pay_no:"):
            await on_pay_decision(update, context)
        elif data.startswith("adm_pay_manual:"):
            await start_manual_config(update, context, int(parts[1]))
        # panels
        elif data == "adm_panel_home":
            await panels_menu(update, context)
        elif data.startswith("adm_panel_view:"):
            await panel_detail(update, context, int(parts[1]))
        elif data.startswith("adm_panel_test:"):
            await panel_test(update, context, int(parts[1]))
        elif data.startswith("adm_panel_del:"):
            await db.delete_panel(int(parts[1]))
            await q.answer("حذف شد.")
            await panels_menu(update, context)
        elif data == "adm_panel_add":
            await ask_state(update, context, "a_padd_name", "📝 نام پنل؟")
        elif data.startswith("adm_panel_name:"):
            await ask_state(update, context, "a_pname", "📝 نام جدید پنل؟",
                            pid=int(parts[1]))
        elif data.startswith("adm_panel_cap:"):
            await ask_state(update, context, "a_pcap",
                            "📊 سقف فروش این پنل چندتا باشه؟\n"
                            "صفر یعنی نامحدود.", pid=int(parts[1]))
        elif data.startswith("adm_panel_token:"):
            await ask_state(update, context, "a_ptoken", "🔑 توکن جدید؟",
                            pid=int(parts[1]))
        elif data.startswith("adm_panel_url:"):
            await ask_state(update, context, "a_purl", "🔗 آدرس جدید؟",
                            pid=int(parts[1]))
        elif data.startswith("adm_panel_sub:"):
            await ask_state(update, context, "a_psub", "📡 بیس ساب جدید؟",
                            pid=int(parts[1]))
        # inbounds
        elif data == "adm_inb_home":
            await inbounds_menu(update, context)
        elif data.startswith("adm_inb_view:"):
            await inbounds_detail(update, context, int(parts[1]))
        elif data.startswith("adm_inb_add:"):
            await ask_state(update, context, "a_inbadd", "🔌 آیدی اینباند؟",
                            pid=int(parts[1]))
        elif data.startswith("adm_inb_del:"):
            pid, ib = int(parts[1]), int(parts[2])
            p = await db.get_panel(pid)
            inb = [x for x in p["inbounds"] if x != ib]
            await db.update_panel(pid, inbounds_json=json.dumps(inb))
            await inbounds_detail(update, context, pid)
        elif data.startswith("adm_inb_ref:"):
            await ask_state(update, context, "a_inbref",
                            "🎯 ایمیل کانفیگ مرجع توی پنل چیه؟\n"
                            "مثلاً همون کانفیگ خودت (`shahin_1234`).\n"
                            "از این به بعد هر سرویس جدید با همون اینباندهایی "
                            "ساخته می‌شه که این کانفیگ استفاده می‌کنه.",
                            pid=int(parts[1]))
        # plans
        elif data == "adm_plan_home":
            await plans_menu(update, context)
        elif data.startswith("adm_plan_view:"):
            await plan_detail(update, context, int(parts[1]))
        elif data.startswith("adm_plan_toggle:"):
            p = await db.get_plan(int(parts[1]))
            await db.update_plan(p["id"], active=0 if p["active"] else 1)
            await plan_detail(update, context, p["id"])
        elif data.startswith("adm_plan_del:"):
            await db.delete_plan(int(parts[1]))
            await q.answer("حذف شد.")
            await plans_menu(update, context)
        elif data == "adm_plan_add":
            await ask_state(update, context, "a_planadd_name", "📝 نام پلن؟")
        # cards
        elif data == "adm_card_home":
            await cards_menu(update, context)
        elif data.startswith("adm_card_view:"):
            await card_detail(update, context, int(parts[1]))
        elif data.startswith("adm_card_toggle:"):
            cards = {c["id"]: c for c in await db.list_cards(False)}
            c = cards[int(parts[1])]
            await db.update_card(c["id"], active=0 if c["active"] else 1)
            await card_detail(update, context, c["id"])
        elif data.startswith("adm_card_del:"):
            await db.delete_card(int(parts[1]))
            await q.answer("حذف شد.")
            await cards_menu(update, context)
        elif data == "adm_card_add":
            await ask_state(update, context, "a_cardadd_num", "💳 شماره کارت؟")
        # users
        elif data == "adm_users_home":
            await users_menu(update, context)
        elif data.startswith("adm_users_svc:"):
            await user_service_detail(update, context, int(parts[1]))
        elif data.startswith("adm_users_view:"):
            await user_detail(update, context, int(parts[1]))
        elif data.startswith("adm_users_bal:"):
            tgid = int(parts[1])
            bal = await db.get_balance(tgid)
            await ask_state(update, context, "a_bal",
                            f"💰 تغییر موجودی کیف پول کاربر {tgid}\n"
                            f"موجودی فعلی: {T.fmt_price(bal)}\n\n"
                            "عدد مثبت برای افزایش، منفی برای کاهش (تومان):",
                            tgid=tgid)
        elif data.startswith("adm_users_manual:"):
            await start_manual_config(update, context, int(parts[1]))
        elif data.startswith("adm_users_manualsend:"):
            await start_manual_send(update, context, int(parts[1]))
        elif data.startswith("adm_manual_plan:"):
            tgid, plan_id = int(parts[1]), int(parts[2])
            plan = await db.get_plan(plan_id)
            if not plan:
                await q.answer("پلن پیدا نشد.", show_alert=True)
            else:
                await ask_state(
                    update, context, "a_manual_sub",
                    f"📦 پلن «{plan['name']}» انتخاب شد.\n\n"
                    "📎 لینک سابسکریپشن دستی رو بفرست:\n"
                    "همون لینکی که از پنل کپی کردی.",
                    tgid=tgid, plan_id=plan_id)
        elif data.startswith("adm_users_dis:") or \
                data.startswith("adm_users_en:") or \
                data.startswith("adm_users_del:") or \
                data.startswith("adm_users_revoke:"):
            await user_service_action(update, context)
        # tutorials
        elif data == "adm_tut_home":
            await tutorials_menu(update, context)
        elif data.startswith("adm_tut_view:"):
            await tutorial_detail(update, context, int(parts[1]))
        elif data == "adm_tut_add":
            await ask_state(update, context, "a_tutadd_title", "📝 عنوان آموزش؟")
        elif data.startswith("adm_tut_edit:"):
            await tutorial_edit_menu(update, context, int(parts[1]))
        elif data.startswith("adm_tut_field:"):
            tid, field = int(parts[1]), parts[2]
            labels = {"title": "✏️ عنوان جدید؟", "body": "📝 متن جدید؟",
                      "photo": "🖼 عکس جدید بفرست (یا بنویس «حذف»)؟"}
            await ask_state(update, context, "a_tutedit",
                            labels.get(field, "؟"), tid=tid, field=field)
        elif data.startswith("adm_tut_toggle:"):
            t = await db.get_tutorial(int(parts[1]))
            await db.update_tutorial(t["id"], active=0 if t["active"] else 1)
            await tutorial_detail(update, context, t["id"])
        elif data.startswith("adm_tut_del:"):
            await db.delete_tutorial(int(parts[1]))
            await q.answer("حذف شد.")
            await tutorials_menu(update, context)
        # broadcast
        elif data == "adm_bc_home":
            await broadcast_home(update, context)
        elif data == "adm_bc_yes":
            await broadcast_send(update, context)
        elif data in ("adm_bc_no", "adm_bc_cancel"):
            context.user_data.pop("bc", None)
            context.user_data.pop("st", None)
            await q.answer("لغو شد.")
            await admin_home(update, context)
        # settings
        elif data == "adm_set_home":
            await settings_menu(update, context)
        elif data.startswith("adm_set_texts"):
            await settings_group(update, context, "texts")
        elif data.startswith("adm_set_test"):
            await settings_group(update, context, "test")
        elif data.startswith("adm_set_warn"):
            await settings_group(update, context, "warn")
        elif data.startswith("adm_set_sub"):
            await settings_group(update, context, "sub")
        elif data.startswith("adm_set_dl"):
            await settings_group(update, context, "dl")
        elif data.startswith("adm_set_ref"):
            await settings_group(update, context, "ref")
        elif data.startswith("adm_set_crypto"):
            await settings_group(update, context, "crypto")
        elif data == "adm_set_backup":
            await q.answer("⏳ در حال ساخت بکاپ…")
            sent = await backup.send_backup_to_admins(context.bot)
            if sent:
                await _show(update, T.BACKUP_MANUAL_OK, K.back_admin_kb())
            else:
                await _show(update, T.BACKUP_MANUAL_FAIL, K.back_admin_kb())
        elif data == "adm_set_autobackup":
            cur = await backup.auto_backup_on()
            await db.set_setting(backup.AUTO_BACKUP_KEY,
                                 "0" if cur else "1")
            await settings_menu(update, context)
        elif data == "adm_set_chlock":
            await chlock_view(update, context)
        elif data == "adm_set_chlock_tgl":
            cur = await db.get_setting("channel_lock_enabled", "0")
            await db.set_setting("channel_lock_enabled",
                                 "0" if cur != "0" else "1")
            await chlock_view(update, context)
        elif data == "adm_set_chlock_set":
            await ask_state(update, context, "a_chlock_set",
                            "📣 کانال‌ها رو بفرست — با کاما یا خط جدید جدا کن "
                            "(مثلاً @a, @b).\n«پاک» یعنی خالی کردن لیست.")
        elif data.startswith("adm_set_toggle:"):
            key = parts[1]
            group = parts[2] if len(parts) > 2 else "test"
            cur = await db.get_setting(key, "1")
            await db.set_setting(key, "0" if cur == "1" else "1")
            await settings_group(update, context, group)
        elif data.startswith("adm_set_key:"):
            key = parts[1]
            cur = await _setting_value(key)
            shown = (cur[:60] + "…") if len(cur) > 60 else cur
            await ask_state(update, context, "a_setkey",
                            f"{SETTING_LABELS.get(key, key)}؟\nفعلی: {shown or '—'}",
                            key=key)
        # setup guide
        elif data == "adm_setup_start":
            await _setup_start(update, context)
        elif data.startswith("adm_setup_skip:"):
            await _setup_skip(update, context, parts[1])
        elif data == "adm_setup_exit":
            context.user_data.pop("st", None)
            await q.answer("خارج شدی — چیزی که تا اینجا ذخیره شده سر جاشه.")
            await setup_guide_home(update, context)
        # support reply
        elif data.startswith("adm_reply:"):
            await ask_state(update, context, "admin_reply", T.SUPPORT_REPLY_ASK,
                            tgid=int(parts[1]))
        else:
            await q.answer()
    except Exception as e:
        log.warning("admin callback error %s: %s", data, e)
        try:
            await q.answer("⚠️ خطا", show_alert=True)
        except Exception:
            pass
