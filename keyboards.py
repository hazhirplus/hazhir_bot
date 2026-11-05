"""Keyboards (Persian)."""
from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        ["🛒 خرید سرویس"],
        ["📦 سرویس‌های من", "👜 کیف پول"],
        ["🎁 اکانت تست", "👥 دعوت دوستان"],
        ["📚 آموزش اتصال", "💬 پشتیبانی"],
    ]
    if is_admin:
        rows.append(["🛠 مدیریت"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def admin_sections() -> ReplyKeyboardMarkup:
    """Admin bottom-menu (mirzabot-style): grouped sections, 2 per row."""
    return ReplyKeyboardMarkup(
        [["📊 گزارش‌ها", "💳 پرداخت‌های در انتظار"],
         ["🖥 مدیریت پنل", "📡 اینباندها"],
         ["📦 پلن‌ها", "💳 کارت‌ها"],
         ["👥 کاربران", "📚 آموزش‌ها"],
         ["📢 پیام همگانی", "⚙️ تنظیمات"],
         ["🔙 منوی اصلی"]],
        resize_keyboard=True,
    )


def admin_hub(pending_n: int = 0) -> InlineKeyboardMarkup:
    """Top-level admin inline hub (2 buttons per row)."""
    pay_label = f"💳 پرداخت‌های در انتظار ({pending_n})" if pending_n else "💳 پرداخت‌های در انتظار"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 گزارش‌ها", callback_data="adm_rep_home"),
         InlineKeyboardButton(pay_label, callback_data="adm_pay_home")],
        [InlineKeyboardButton("🖥 مدیریت پنل", callback_data="adm_panel_home"),
         InlineKeyboardButton("📡 اینباندها", callback_data="adm_inb_home")],
        [InlineKeyboardButton("📦 پلن‌ها", callback_data="adm_plan_home"),
         InlineKeyboardButton("💳 کارت‌ها", callback_data="adm_card_home")],
        [InlineKeyboardButton("👥 کاربران", callback_data="adm_users_home"),
         InlineKeyboardButton("📚 آموزش‌ها", callback_data="adm_tut_home")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="adm_bc_home"),
         InlineKeyboardButton("⚙️ تنظیمات", callback_data="adm_set_home")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="adm_tomain")],
    ])


def back_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data="adm_home")]])


def plans_kb(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        f"{p['name']} — {p['price_toman']:,} تومان", callback_data=f"u:plan:{p['id']}")]
        for p in plans]
    return InlineKeyboardMarkup(rows)


def buy_kb(plan_id: int, wallet_ok: bool = False, balance: int = 0,
           crypto_ok: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if wallet_ok:
        rows.append([InlineKeyboardButton(
            f"👜 پرداخت با کیف پول ({balance:,} تومان)",
            callback_data=f"u:walletbuy:{plan_id}")])
    if crypto_ok:
        rows.append([InlineKeyboardButton(
            "💎 ارز دیجیتال", callback_data=f"u:cryptobuy:{plan_id}")])
    rows.append([InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data=f"u:buy:{plan_id}")])
    rows.append([InlineKeyboardButton("◀️ برگشت", callback_data="u:plans")])
    return InlineKeyboardMarkup(rows)


def crypto_currency_kb(back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ETH", callback_data="u:crycur:ETH"),
         InlineKeyboardButton("USDC", callback_data="u:crycur:USDC")],
        [InlineKeyboardButton("◀️ برگشت", callback_data=back_cb)],
    ])


def crypto_network_kb(back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Base", callback_data="u:crynet:8453"),
         InlineKeyboardButton("آربیتروم", callback_data="u:crynet:42161")],
        [InlineKeyboardButton("اپتیمیزم", callback_data="u:crynet:10")],
        [InlineKeyboardButton("◀️ برگشت", callback_data=back_cb)],
    ])


def crypto_pay_kb(invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بررسی پرداخت",
                              callback_data=f"u:crycheck:{invoice_id}")],
        [InlineKeyboardButton("❌ انصراف",
                              callback_data=f"u:crycancel:{invoice_id}")],
    ])


def pay_decision_kb(invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأیید", callback_data=f"adm_pay_ok:{invoice_id}"),
        InlineKeyboardButton("❌ رد", callback_data=f"adm_pay_no:{invoice_id}"),
    ]])


def service_kb(invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 تمدید", callback_data=f"u:renew:{invoice_id}"),
        InlineKeyboardButton("🔗 لینک‌ها", callback_data=f"u:links:{invoice_id}"),
    ]])


def renew_one_kb(invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 تمدید همین سرویس",
                             callback_data=f"u:renewone:{invoice_id}")]])


def quick_guide_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📚 آموزش کامل اتصال", callback_data="u:tuts")]])


def tutorials_kb(tuts: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(t["title"], callback_data=f"u:tut:{t['id']}")]
            for t in tuts]
    rows.append([InlineKeyboardButton("📥 دانلود برنامه‌ها", callback_data="u:tutlinks")])
    return InlineKeyboardMarkup(rows)


def back_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 منو", callback_data="u:home")]])


def tut_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 لیست آموزش‌ها", callback_data="u:tuts")]])


def confirm_kb(action: str, obj_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ بله", callback_data=f"{action}:yes:{obj_id}"),
        InlineKeyboardButton("◀️ انصراف", callback_data=f"{action}:no:{obj_id}"),
    ]])
