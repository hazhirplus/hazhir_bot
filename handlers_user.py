"""User-facing flows (Persian)."""
from __future__ import annotations
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram import Update
from telegram.ext import ContextTypes

import config
import db
import text as T
import keyboards as K
import chainwatch
from channel_lock import (enforce_channel_lock, missing_lock_channels,
                          show_channel_lock)
from helpers import (notify_admins, deliver_service, panel_client_for,
                     create_panel_client, activate_crypto_invoice, send_md)
from panel import PanelError, gb_to_bytes, days_to_ms, derive_status, bytes_to_gb

log = logging.getLogger("hozhir")


def _mm(update) -> ReplyKeyboardMarkup:
    """Main bottom menu, admin-aware (admins get the 🛠 مدیریت entry)."""
    return K.main_menu(is_admin=config.is_admin(update.effective_user.id))


async def _crypto_available() -> bool:
    """Crypto pay method is offered only when enabled AND an address is set."""
    if await db.get_setting("crypto_enabled", "0") != "1":
        return False
    return bool((await db.get_setting("evm_address", "")).strip())


# ---------------- /start & main menu ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    if await enforce_channel_lock(update.message, context, u.id):
        return
    existing = await db.get_user(u.id)
    await db.upsert_user(u.id, u.username)
    # referral attribution: first-ever /start with ref_<tgid>
    if not existing and context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                rid = int(arg[4:])
            except ValueError:
                rid = 0
            if rid and rid != u.id and await db.attribute_referral(u.id, rid):
                try:
                    await context.bot.send_message(
                        rid, "👥 یه نفر با لینک دعوت تو وارد شد!\n"
                             "با اولین خریدش، هدیه‌ات فعال می‌شه 🎁")
                except Exception:
                    pass
    welcome = await db.get_setting("welcome_text", T.WELCOME_DEFAULT)
    await update.message.reply_text(welcome or "سلام 👋",
                                    reply_markup=_mm(update))


async def menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route main-menu buttons and state-driven text input."""
    msg = update.message
    if not msg or not msg.text:
        return
    if await enforce_channel_lock(msg, context, msg.from_user.id):
        return
    st = context.user_data.get("st")
    if st:
        await _handle_state(update, context, st)
        return
    t = msg.text.strip()
    if t == "🛒 خرید سرویس":
        await show_plans(update, context)
    elif t == "📦 سرویس‌های من":
        await my_services(update, context)
    elif t == "👜 کیف پول":
        await wallet_menu(update, context)
    elif t == "👥 دعوت دوستان":
        await referral_menu(update, context)
    elif t == "🎁 اکانت تست":
        await test_account(update, context)
    elif t == "📚 آموزش اتصال":
        await tutorials_menu(update, context)
    elif t == "💬 پشتیبانی":
        context.user_data["st"] = {"k": "support"}
        sup = await db.get_setting("support_text", T.SUPPORT_TEXT_DEFAULT)
        await msg.reply_text(f"{sup}\n\n{T.SUPPORT_ASK}")
    elif t.startswith("/"):
        return  # commands handled elsewhere
    else:
        await msg.reply_text(T.MAIN_MENU_HINT, reply_markup=_mm(update))


# ---------------- buy flow ----------------
async def _show_or_edit(update, text, reply_markup=None) -> None:
    """Edit the callback message, or reply when the entry was a text tap."""
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup)
            return
        except Exception:
            pass
    target = update.message or (update.callback_query.message
                                if update.callback_query else None)
    await target.reply_text(text, reply_markup=reply_markup)


async def show_servers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Server picker (only reached when more than one panel can sell)."""
    available = await db.list_available_panels()
    if not available:
        await _show_or_edit(update, T.NO_PANELS)
        return
    await _show_or_edit(update, T.PICK_SERVER,
                        reply_markup=K.panels_kb(available))


async def server_picked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:server:<pid> — remember the server, then show its plans."""
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[2])
    p = await db.get_panel(pid)
    if not p or not p.get("active") or not await db.panel_has_capacity(p):
        await q.edit_message_text(T.PANEL_SOLD_OUT)
        return
    context.user_data["panel_id"] = pid
    await show_plans(update, context, panel_id=pid)


async def _chosen_panel(context) -> dict | None:
    """The panel this purchase goes to: the picked server while it can
    still sell, else the first available panel (None when all are full)."""
    pid = context.user_data.get("panel_id")
    if pid:
        p = await db.get_panel(pid)
        if p and p.get("active") and await db.panel_has_capacity(p):
            return p
    return await db.get_available_panel()


async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     panel_id: int | None = None) -> None:
    """Plan list for the purchase — after the server pick, if any.

    With no sellable panel the user gets NO_PANELS; with exactly one,
    its plans show directly; with several, the server picker comes
    first. A stale stored panel (sold out / deleted) falls back to the
    same count logic instead of breaking the flow.
    """
    plans = await db.list_plans(True)
    if not plans:
        await _show_or_edit(update, T.NO_PLANS)
        return
    if panel_id is None:
        panel_id = context.user_data.get("panel_id")
    panel = None
    if panel_id:
        p = await db.get_panel(panel_id)
        if p and p.get("active") and await db.panel_has_capacity(p):
            panel = p
    if panel is None:
        available = await db.list_available_panels()
        if not available:
            await _show_or_edit(update, T.NO_PANELS)
            return
        if len(available) == 1:
            panel = available[0]
        else:
            context.user_data.pop("panel_id", None)
            await _show_or_edit(update, T.PICK_SERVER,
                                reply_markup=K.panels_kb(available))
            return
    context.user_data["panel_id"] = panel["id"]
    multi = len(await db.list_available_panels()) > 1
    await _show_or_edit(update, "📦 یه پلن انتخاب کن:",
                        reply_markup=K.plans_kb(plans, show_server_back=multi))


async def plan_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[2])
    plan = await db.get_plan(pid)
    if not plan or not plan["active"]:
        await q.edit_message_text(T.NO_PLANS)
        return
    bal = await db.get_balance(q.from_user.id)
    crypto_ok = await _crypto_available()
    await q.edit_message_text(
        T.plan_line(plan),
        reply_markup=K.buy_kb(pid, bal >= plan["price_toman"], bal, crypto_ok))


async def _card_block() -> str | None:
    card = await db.get_active_card()
    if not card:
        return None
    return f"💳 کارت:\n`{card['number']}`\n👤 {card['holder']}"


async def buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[2])
    plan = await db.get_plan(pid)
    card_block = await _card_block()
    if not plan or not card_block:
        await q.edit_message_text(T.NO_CARD if not card_block else T.NO_PLANS)
        return
    panel = await _chosen_panel(context)
    if not panel:
        await q.edit_message_text(T.NO_PANEL)
        return
    guide = (await db.get_setting("buy_guide", T.BUY_GUIDE_DEFAULT)).strip()
    head = f"{guide}\n\n" if guide else ""
    # State only after the screen was delivered: if the edit fails the
    # user is not left waiting for a receipt they never saw the card for.
    await send_md(
        q.edit_message_text,
        f"{head}{T.plan_line(plan)}\n\n{card_block}\n\n"
        f"💰 مبلغ: {T.fmt_price(plan['price_toman'])}\n\n{T.RECEIPT_ASK}")
    context.user_data["st"] = {"k": "receipt", "plan_id": pid, "kind": "purchase",
                               "panel_id": panel["id"]}


async def _start_renew_payment(q, context, inv: dict, plan: dict) -> None:
    """Jump straight into the renew pay-flow for an invoice + plan."""
    card_block = await _card_block()
    if not card_block:
        await q.edit_message_text(T.NO_CARD)
        return
    guide = (await db.get_setting("buy_guide", T.BUY_GUIDE_DEFAULT)).strip()
    head = f"{guide}\n\n" if guide else ""
    # State only after the screen was delivered: if the edit fails the
    # user is not left waiting for a receipt they never saw the card for.
    await send_md(
        q.edit_message_text,
        f"{head}{T.plan_line(plan)}\n\n{card_block}\n\n"
        f"💰 مبلغ تمدید: {T.fmt_price(plan['price_toman'])}\n\n{T.RECEIPT_ASK}")
    context.user_data["st"] = {
        "k": "receipt", "plan_id": plan["id"], "kind": "renew",
        "panel_id": inv.get("panel_id"),
        "panel_email": inv.get("panel_email", ""),
        "sub_id": inv.get("sub_id", ""),
        "base_expires": inv.get("expires_at", 0),
    }


async def renew_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    inv_id = int(q.data.split(":")[2])
    inv = await db.get_invoice(inv_id)
    if not inv or inv["user_id"] != q.from_user.id:
        await q.answer("یافت نشد.", show_alert=True)
        return
    context.user_data["st"] = {"k": "renew_pick", "target_inv": inv_id}
    plans = await db.list_plans(True)
    await q.edit_message_text("🔄 برای تمدید، پلن جدید رو انتخاب کن:",
                              reply_markup=K.plans_kb(plans))


async def renew_plan_picked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """After picking a renew plan: choose payment method (wallet vs card-to-card)."""
    # routed via callback u:plan: when state is renew_pick
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("st") or {}
    pid = int(q.data.split(":")[2])
    plan = await db.get_plan(pid)
    target = await db.get_invoice(st.get("target_inv"))
    if not plan or not target:
        await q.edit_message_text(T.NO_PLANS)
        return
    context.user_data["st"] = {"k": "renew_pay", "target_inv": target["id"], "plan_id": pid}
    bal = await db.get_balance(q.from_user.id)
    rows = []
    if bal >= plan["price_toman"]:
        rows.append([InlineKeyboardButton(
            f"👜 پرداخت با کیف پول ({bal:,} تومان)", callback_data="u:renewwallet")])
    if await _crypto_available():
        rows.append([InlineKeyboardButton("💎 ارز دیجیتال", callback_data="u:renewcrypto")])
    rows.append([InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data="u:renewcard")])
    rows.append([InlineKeyboardButton("◀️ برگشت", callback_data=f"u:renew:{target['id']}")])
    await q.edit_message_text(
        f"{T.plan_line(plan)}\n\n💰 مبلغ تمدید: {T.fmt_price(plan['price_toman'])}\n\n"
        "روش پرداخت رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(rows))


async def renew_pay_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:renewcard — card-to-card receipt flow for a pending renew choice."""
    q = update.callback_query
    st = context.user_data.get("st") or {}
    if st.get("k") != "renew_pay":
        await q.answer("منقضی شد.", show_alert=True)
        return
    plan = await db.get_plan(st.get("plan_id"))
    target = await db.get_invoice(st.get("target_inv"))
    if not plan or not target:
        await q.edit_message_text(T.NO_PLANS)
        return
    await _start_renew_payment(q, context, target, plan)


async def renew_pay_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:renewwallet — instant renew paid from wallet balance."""
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("st") or {}
    if st.get("k") != "renew_pay":
        await q.answer("منقضی شد.", show_alert=True)
        return
    plan = await db.get_plan(st.get("plan_id"))
    target = await db.get_invoice(st.get("target_inv"))
    if not plan or not target:
        await q.edit_message_text(T.NO_PLANS)
        return
    uid = q.from_user.id
    # Atomic conditional debit: the funds check and the debit are one SQL
    # statement, so two rapid taps cannot both pass (vibe-check 32).
    if not await db.debit_balance(uid, plan["price_toman"]):
        await q.answer("موجودی کیف پول کافی نیست.", show_alert=True)
        return
    from handlers_admin import approve_invoice
    iid = await db.create_invoice(
        user_id=uid, kind="renew", plan_id=plan["id"],
        price_toman=plan["price_toman"],
        panel_id=target.get("panel_id"),
        panel_email=target.get("panel_email", ""),
        sub_id=target.get("sub_id", ""),
        expires_at=target.get("expires_at", 0))
    context.user_data.pop("st", None)
    try:
        res = await approve_invoice(context, await db.get_invoice(iid), None)
    except Exception as e:
        log.warning("wallet renew approval failed: %s", e)
        res = f"⚠️ خطا: {e}"
    inv = await db.get_invoice(iid)
    # approve_invoice leaves a failed invoice "pending" (it never sets
    # "expired") — refund whenever the service did not become active,
    # or the wallet keeps money for a service that was never created.
    if inv["status"] != "active":
        await db.add_balance(uid, plan["price_toman"])
        await q.edit_message_text(f"⚠️ {res}\nمبلغ به کیف پولت برگشت.")
        return
    await q.edit_message_text(f"👜 {res}")


async def wallet_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:walletbuy:<pid> — instant purchase paid from wallet balance."""
    q = update.callback_query
    await q.answer()
    plan = await db.get_plan(int(q.data.split(":")[2]))
    if not plan or not plan["active"]:
        await q.edit_message_text(T.NO_PLANS)
        return
    uid = q.from_user.id
    panel = await _chosen_panel(context)
    if not panel:
        await q.edit_message_text(T.NO_PANEL)
        return
    # Atomic conditional debit (see renew_pay_wallet): check + debit in one
    # statement so a double-tap cannot spend the same balance twice.
    if not await db.debit_balance(uid, plan["price_toman"]):
        await q.answer("موجودی کیف پول کافی نیست.", show_alert=True)
        return
    from handlers_admin import approve_invoice
    iid = await db.create_invoice(user_id=uid, kind="purchase",
                                  plan_id=plan["id"],
                                  price_toman=plan["price_toman"],
                                  panel_id=panel["id"])
    try:
        res = await approve_invoice(context, await db.get_invoice(iid), None)
    except Exception as e:
        log.warning("wallet buy approval failed: %s", e)
        res = f"⚠️ خطا: {e}"
    inv = await db.get_invoice(iid)
    # approve_invoice leaves a failed invoice "pending" (it never sets
    # "expired") — refund whenever the service did not become active,
    # or the wallet keeps money for a service that was never created.
    if inv["status"] != "active":
        await db.add_balance(uid, plan["price_toman"])
        await q.edit_message_text(f"⚠️ {res}\nمبلغ به کیف پولت برگشت.")
        return
    await q.edit_message_text(f"👜 {res}")


# ---------------- crypto pay flow (v2.3) ----------------
async def crypto_buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:cryptobuy:<pid> — start the crypto flow for a purchase."""
    q = update.callback_query
    await q.answer()
    if not await _crypto_available():
        await q.answer(T.CRYPTO_DISABLED, show_alert=True)
        return
    st = context.user_data.get("st") or {}
    pid = int(q.data.split(":")[2])
    if st.get("k") == "crypto_cur" and st.get("flow") == "buy":
        pid = st.get("plan_id", pid)
    plan = await db.get_plan(pid)
    if not plan or not plan["active"]:
        await q.edit_message_text(T.NO_PLANS)
        return
    panel = await _chosen_panel(context)
    if not panel:
        await q.edit_message_text(T.NO_PANEL)
        return
    context.user_data["st"] = {"k": "crypto_cur", "flow": "buy",
                               "plan_id": plan["id"],
                               "panel_id": panel["id"]}
    await q.edit_message_text(
        f"{T.plan_line(plan)}\n\n{T.CRYPTO_PICK_CURRENCY}",
        reply_markup=K.crypto_currency_kb(f"u:plan:{plan['id']}"))


async def crypto_renew_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:renewcrypto — start the crypto flow for a renew."""
    q = update.callback_query
    await q.answer()
    if not await _crypto_available():
        await q.answer(T.CRYPTO_DISABLED, show_alert=True)
        return
    st = context.user_data.get("st") or {}
    if st.get("k") == "renew_pay":
        plan_id, target_id = st.get("plan_id"), st.get("target_inv")
    elif st.get("k") == "crypto_cur" and st.get("flow") == "renew":
        plan_id, target_id = st.get("plan_id"), st.get("target_inv")
    else:
        await q.answer("منقضی شد.", show_alert=True)
        return
    plan = await db.get_plan(plan_id)
    target = await db.get_invoice(target_id)
    if not plan or not target:
        await q.edit_message_text(T.NO_PLANS)
        return
    context.user_data["st"] = {"k": "crypto_cur", "flow": "renew",
                               "plan_id": plan["id"],
                               "target_inv": target["id"]}
    await q.edit_message_text(
        f"{T.plan_line(plan)}\n\n{T.CRYPTO_PICK_CURRENCY}",
        reply_markup=K.crypto_currency_kb(f"u:renew:{target['id']}"))


async def crypto_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:crycur:ETH|USDC — currency picked, now choose the network."""
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("st") or {}
    if st.get("k") != "crypto_cur":
        await q.answer("منقضی شد.", show_alert=True)
        return
    cur = q.data.split(":")[2].upper()
    if cur not in chainwatch.CURRENCIES:
        await q.answer("این ارز پشتیبانی نمی‌شود.", show_alert=True)
        return
    st["currency"] = cur
    context.user_data["st"] = st
    back = (f"u:cryptobuy:{st['plan_id']}" if st.get("flow") == "buy"
            else "u:renewcrypto")
    await q.edit_message_text(
        f"💎 {chainwatch.CURRENCY_FA[cur]}\n\n{T.CRYPTO_PICK_NETWORK}\n\n"
        "⚠️ فقط از یکی از همین شبکه‌ها واریز کنید:\n"
        "Base ، آربیتروم ، اپتیمیزم",
        reply_markup=K.crypto_network_kb(back))


async def _show_crypto_pay(q, inv: dict, plan: dict,
                           low_value_warn: bool = False) -> None:
    """Render the crypto pay screen (exact amount, address, warnings)."""
    chain = chainwatch.CHAINS[int(inv["crypto_chain"])]
    cur = inv["crypto_currency"]
    remain_min = max(1, (inv["crypto_expires_at"] - int(time.time())) // 60)
    lines = [
        T.CRYPTO_PAY_TITLE,
        "",
        f"📦 {plan['name']}",
        f"💰 مبلغ دقیق: `{inv['crypto_amount']}` {cur}",
        f"🌐 شبکه: {chain['fa']} ({chain['name']})",
        "📥 آدرس:",
        f"`{inv['crypto_address']}`",
        f"⏳ مهلت پرداخت: {remain_min} دقیقه",
        "",
        T.CRYPTO_WARN_NETWORK.format(net=chain['fa']),
        T.CRYPTO_WARN_CURRENCY.format(cur=chainwatch.CURRENCY_FA[cur]),
        T.CRYPTO_WARN_EXACT,
    ]
    if low_value_warn:
        lines.append(T.CRYPTO_WARN_FEE)
    await send_md(q.edit_message_text, "\n".join(lines),
                  reply_markup=K.crypto_pay_kb(inv["id"]))


async def crypto_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:crynet:<chain_id> — price the order, create the invoice, show pay screen."""
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("st") or {}
    if st.get("k") != "crypto_cur" or "currency" not in st:
        await q.answer("منقضی شد.", show_alert=True)
        return
    try:
        chain_id = int(q.data.split(":")[2])
    except (ValueError, IndexError):
        chain_id = 0
    if chain_id not in chainwatch.CHAINS:
        await q.answer("این شبکه پشتیبانی نمی‌شود.", show_alert=True)
        return
    plan = await db.get_plan(st.get("plan_id"))
    if not plan or not plan["active"]:
        await q.edit_message_text(T.NO_PLANS)
        return
    addr = (await db.get_setting("evm_address", "")).strip()
    if not addr:
        await q.edit_message_text(T.CRYPTO_NO_ADDRESS)
        return
    try:
        qinfo = await chainwatch.quote(plan["price_toman"], st["currency"])
    except Exception as e:
        log.warning("crypto quote failed: %s", e)
        await q.edit_message_text(T.CRYPTO_RATE_FAIL)
        return
    now = int(time.time())
    try:
        exp_min = int(await db.get_setting("crypto_expiry_min", "90") or 90)
    except ValueError:
        exp_min = 90
    extra = dict(
        pay_method="crypto",
        crypto_chain=str(chain_id),
        crypto_currency=st["currency"],
        crypto_amount=qinfo["amount"],
        crypto_address=addr,
        crypto_expires_at=now + exp_min * 60,
        crypto_meta="{}",
    )
    kind = "purchase"
    if st.get("flow") == "renew":
        kind = "renew"
        target = await db.get_invoice(st.get("target_inv"))
        if not target:
            await q.edit_message_text(T.NO_PLANS)
            return
        extra.update(
            panel_id=target.get("panel_id"),
            panel_email=target.get("panel_email", ""),
            sub_id=target.get("sub_id", ""),
            expires_at=target.get("expires_at", 0),
        )
    elif st.get("panel_id"):
        extra["panel_id"] = st["panel_id"]
    # best-effort: seed the ETH baseline for the keyless RPC backend
    try:
        backend = await chainwatch.get_backend()
        if (isinstance(backend, chainwatch.PublicRpcBackend)
                and st["currency"] == "ETH"):
            await backend.ensure_eth_baseline(chain_id)
    except Exception as e:
        log.warning("eth baseline init failed: %s", e)
    iid = await db.create_invoice(
        user_id=q.from_user.id, kind=kind, plan_id=plan["id"],
        price_toman=plan["price_toman"], **extra)
    context.user_data.pop("st", None)
    await _show_crypto_pay(q, await db.get_invoice(iid), plan,
                           qinfo["low_value_warn"])


async def crypto_check_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:crycheck:<iid> — user-triggered immediate chain check."""
    q = update.callback_query
    iid = int(q.data.split(":")[2])
    inv = await db.get_invoice(iid)
    if (not inv or inv["user_id"] != q.from_user.id
            or inv.get("pay_method") != "crypto"):
        await q.answer("یافت نشد.", show_alert=True)
        return
    if inv["status"] != "pending":
        await q.answer("این فاکتور دیگه فعال نیست.", show_alert=True)
        return
    await q.edit_message_text("⏳ در حال بررسی شبکه... چند ثانیه صبر کن.")
    try:
        tx = await chainwatch.find_payment_for_invoice(inv)
    except Exception as e:
        log.warning("manual crypto check failed: %s", e)
        tx = None
    if not tx:
        plan = await db.get_plan(inv["plan_id"])
        await _show_crypto_pay(q, inv, plan)
        await q.answer("⏳ پرداختی پیدا نشد.", show_alert=True)
        return
    ok = await activate_crypto_invoice(context, inv, tx)
    if ok:
        await q.edit_message_text(
            "✅ پرداخت تأیید شد! لینک‌های سرویس‌ت رو بالا فرستادم 👆")
    else:
        plan = await db.get_plan(inv["plan_id"])
        await _show_crypto_pay(q, inv, plan)
        await q.answer("⚠️ خطا در فعال‌سازی؛ چند دقیقه دیگه دوباره تلاش کن.",
                       show_alert=True)


async def crypto_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:crycancel:<iid> — user cancels a pending crypto invoice."""
    q = update.callback_query
    await q.answer()
    iid = int(q.data.split(":")[2])
    inv = await db.get_invoice(iid)
    if (inv and inv["user_id"] == q.from_user.id
            and inv.get("status") == "pending"
            and inv.get("pay_method") == "crypto"):
        await db.update_invoice(iid, status="expired")
        await db.set_payment(iid, "rejected", None)
    await q.edit_message_text(T.CRYPTO_CANCELLED)


# ---------------- wallet menu ----------------
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bal = await db.get_balance(update.effective_user.id)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("➕ شارژ کیف پول", callback_data="u:wallettop")]])
    await update.message.reply_text(
        f"👜 کیف پول\n\n💰 موجودی: {T.fmt_price(bal)}", reply_markup=kb)


async def wallet_topup_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:wallettop — ask for the top-up amount, then the card/receipt flow."""
    q = update.callback_query
    await q.answer()
    context.user_data["st"] = {"k": "wallet_amount"}
    await q.message.reply_text("💰 مبلغ شارژ به تومان؟\n(مثلاً ۱۰۰۰۰۰)")


# ---------------- referral menu ----------------
async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    try:
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{uid}" if me.username else "—"
    except Exception:
        link = "—"
    invited = await db.count_referrals(uid)
    gifts = await db.count_referral_gifts(uid)
    days = await db.get_setting("ref_gift_days", "30")
    gb = await db.get_setting("ref_gift_gb", "10")
    await update.message.reply_text(
        f"👥 دعوت دوستان\n\n🔗 لینک اختصاصی تو:\n`{link}`\n\n"
        f"👥 دعوت‌شده‌ها: {invited}\n🎁 هدیه‌های گرفته‌شده: {gifts}\n\n"
        f"💡 با اولین خرید هر دعوت‌شده، یه سرویس هدیه ({T.fmt_gb_num(gb)} گیگ / {days} روزه) می‌گیری!",
        parse_mode="Markdown")


async def renew_one(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """One-click renew from the expiry-warning button: same plan, straight to pay."""
    q = update.callback_query
    await q.answer()
    inv = await db.get_invoice(int(q.data.split(":")[2]))
    if not inv or inv["user_id"] != q.from_user.id or inv["status"] != "active":
        await q.answer("یافت نشد.", show_alert=True)
        return
    plan = await db.get_plan(inv["plan_id"]) if inv.get("plan_id") else None
    if not plan or not plan["active"]:
        # fall back to plan picker
        context.user_data["st"] = {"k": "renew_pick", "target_inv": inv["id"]}
        plans = await db.list_plans(True)
        await q.edit_message_text("🔄 پلن تمدید رو انتخاب کن:",
                                  reply_markup=K.plans_kb(plans))
        return
    await _start_renew_payment(q, context, inv, plan)


async def _handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE, st: dict) -> None:
    msg = update.message
    file_id = ""
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document:
        file_id = msg.document.file_id
    elif msg.text and msg.text.strip() and not msg.text.startswith("/"):
        file_id = "text:" + msg.text.strip()[:500]
    else:
        await msg.reply_text("🧾 رسید رو به صورت عکس یا متن بفرست.")
        return
    plan = await db.get_plan(st["plan_id"]) if st.get("plan_id") else None
    if not plan and st.get("kind") != "topup":
        context.user_data.pop("st", None)
        await msg.reply_text(T.NO_PLANS)
        return
    # Anti-abuse: same receipt photo/file or tracking number already used?
    # Still accept the invoice (could be an honest resend), but warn the admin.
    dup_warn = ""
    if file_id:
        dups = await db.find_invoice_by_receipt(file_id)
        if dups:
            first = dups[0]
            dup_warn = T.DUP_RECEIPT_WARN.format(iid=first["id"],
                                                uid=first["user_id"])
    price = plan["price_toman"] if plan else st.get("amount", 0)
    plan_name = plan["name"] if plan else "شارژ کیف پول"
    iid = await db.create_invoice(
        user_id=msg.from_user.id, kind=st["kind"],
        plan_id=plan["id"] if plan else None,
        price_toman=price, receipt_file_id=file_id)
    # prefill panel identity for renewals
    if st["kind"] == "renew":
        await db.update_invoice(iid, panel_id=st.get("panel_id"),
                                panel_email=st.get("panel_email", ""),
                                sub_id=st.get("sub_id", ""),
                                expires_at=st.get("base_expires", 0))
    elif st["kind"] == "purchase" and st.get("panel_id"):
        # the server the customer picked — approve_invoice builds the
        # client on this panel instead of the first active one
        await db.update_invoice(iid, panel_id=st.get("panel_id"))
    context.user_data.pop("st", None)
    u = msg.from_user
    uname = f"@{u.username}" if u.username else str(u.id)
    receipt_note = "📷 عکس رسید" if not file_id.startswith("text:") else f"📝 {file_id[5:]}"
    await notify_admins(
        context,
        T.ADMIN_NEW_PAYMENT.format(user=f"{uname} ({u.id})", plan=plan_name,
                                   kind=T.KIND_FA.get(st["kind"], st["kind"]),
                                   price=T.fmt_price(price),
                                   receipt=receipt_note) + dup_warn,
        reply_markup=K.pay_decision_kb(iid, manual=(st["kind"] != "topup")))
    if file_id and not file_id.startswith("text:"):
        for aid in config.ADMIN_IDS:
            try:
                await context.bot.send_photo(aid, file_id,
                                             caption=f"🧾 رسید فاکتور #{iid}")
            except Exception as e:
                log.warning("forward receipt failed: %s", e)
    await msg.reply_text("✅ رسیدت ثبت شد. بعد از تأیید، سرویس‌ت فعال می‌شه.",
                         reply_markup=_mm(update))


# ---------------- my services ----------------
async def my_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    invs = await db.user_invoices(update.effective_user.id, ("active",))
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if not invs:
        await target.reply_text(T.NO_SERVICES)
        return
    for inv in invs:
        await send_service_card(target, context, inv, edit=False)


async def send_service_card(target, context, inv: dict, edit: bool = False) -> None:
    plan = await db.get_plan(inv["plan_id"]) if inv.get("plan_id") else None
    if plan:
        plan_name = plan["name"]
    elif inv.get("kind") == "gift":
        plan_name = "🎁 هدیه دعوت دوستان"
    else:
        plan_name = "اکانت تست"
    panel = await db.get_panel(inv["panel_id"]) if inv.get("panel_id") else None
    status_fa, gb_left, days_left = "—", "—", "—"
    if panel and inv.get("panel_email"):
        try:
            pc = panel_client_for(panel)
            client = await pc.get_client(inv["panel_email"])
            if client:
                traf = await pc.traffic(inv["panel_email"])
                st = derive_status(client, traf)
                status_fa = T.STATUS_FA.get(st, st)
                total = client.get("totalGB", 0) or 0
                used = (traf.get("up", 0) or 0) + (traf.get("down", 0) or 0)
                gb_left = T.fmt_gb(max(0, total - used)) if total else "نامحدود"
                exp = client.get("expiryTime", 0) or 0
                if exp:
                    import math
                    d = math.ceil(exp / 1000 - time.time()) / 86400
                    days_left = f"{max(0, math.ceil(d))} روز"
                else:
                    days_left = "نامحدود"
            else:
                status_fa = "⚠️ در پنل یافت نشد"
        except PanelError as e:
            status_fa = ("⚠️ در پنل یافت نشد" if e.is_not_found
                         else "⚠️ خطا در خواندن وضعیت")
        except Exception as e:
            log.warning("service status failed: %s", e)
            status_fa = "⚠️ خطا در خواندن وضعیت"
    txt = T.service_card(inv, plan_name, status_fa, gb_left, days_left)
    kb = K.service_kb(inv["id"])
    if edit and hasattr(target, "edit_text"):
        try:
            await send_md(target.edit_text, txt, reply_markup=kb)
            return
        except Exception:
            pass
    await send_md(target.reply_text, txt, reply_markup=kb)


async def service_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("🔄 به‌روزرسانی…")
    inv = await db.get_invoice(int(q.data.split(":")[2]))
    if inv and inv["user_id"] == q.from_user.id:
        await send_service_card(q.message, context, inv, edit=True)


async def resend_links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    inv = await db.get_invoice(int(q.data.split(":")[2]))
    if not inv or inv["user_id"] != q.from_user.id or inv["status"] != "active":
        await q.answer("یافت نشد.", show_alert=True)
        return
    ok = await deliver_service(context, inv)
    await q.message.reply_text("✅ لینک‌ها دوباره ارسال شد." if ok else "⚠️ خطا در دریافت لینک‌ها.")


# ---------------- test account (instant, one per user, no admin approval) ----------------
async def test_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if await db.get_setting("test_enabled", "1") != "1":
        await update.message.reply_text(T.TEST_DISABLED)
        return
    if await db.user_had_test(uid):
        await update.message.reply_text(T.TEST_ALREADY)
        return
    days = await db.get_setting("test_days", "1")
    gb = await db.get_setting("test_gb", "2")
    prog = await update.message.reply_text(
        T.TEST_INFO.format(days=days, gb=T.fmt_gb_num(gb)) + "\n\n" + T.TEST_CREATING)
    err = await grant_test_account(context, uid)
    if err:
        await prog.edit_text(err)
    else:
        try:
            await prog.delete()
        except Exception:
            pass


async def grant_test_account(context: ContextTypes.DEFAULT_TYPE,
                             uid: int) -> str | None:
    """Create + deliver a test account immediately. Returns error text or None."""
    if await db.user_had_test(uid):
        return T.TEST_ALREADY
    try:
        days = int(float(await db.get_setting("test_days", "1")))
    except (TypeError, ValueError):
        days = 1
    try:
        gb = float(await db.get_setting("test_gb", "2"))
    except (TypeError, ValueError):
        gb = 2.0
    panel = await db.get_available_panel()
    if not panel:
        return "⚠️ پنل فعالی ثبت نشده."
    iid = await db.create_invoice(user_id=uid, kind="test", plan_id=None,
                                  price_toman=0, receipt_file_id="")
    inv = await db.get_invoice(iid)
    pc = panel_client_for(panel)
    now = int(time.time())
    try:
        email, sub_id, skipped = await create_panel_client(pc, panel, inv, days, gb, now)
        if skipped:
            log.warning("test account skipped inbounds %s", skipped)
    except PanelError as e:
        log.warning("test account panel error: %s", e)
        await db.update_invoice(iid, status="expired")
        return T.TEST_FAIL
    await db.update_invoice(iid, status="active", panel_id=panel["id"],
                            panel_email=email, sub_id=sub_id,
                            activated_at=now, expires_at=now + days * 86400,
                            warned_at=0)
    await db.set_payment(iid, "approved", None)
    ok = await deliver_service(context, await db.get_invoice(iid))
    user = await db.get_user(uid)
    uname = f"@{(user or {}).get('username')}" if (user or {}).get("username") else str(uid)
    await notify_admins(
        context,
        T.TEST_NOTIFY_ADMIN.format(user=uname, uid=uid, email=email))
    if not ok:
        return "⚠️ اکانت ساخته شد ولی ارسال لینک‌ها ناموفق بود — از «سرویس‌های من» دوباره بگیر."
    return None


# ---------------- tutorials ----------------
async def _render_tutorial(tut: dict) -> str:
    body = tut.get("body") or ""
    for key in ("dl_android", "dl_ios", "dl_windows"):
        body = body.replace("{" + key + "}", await db.get_setting(key, ""))
    return body


async def tutorials_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tuts = await db.list_tutorials(True)
    q = update.callback_query
    if not tuts:
        txt = "فعلاً آموزشی ثبت نشده."
        kb = None
    else:
        txt = "📚 آموزش اتصال — سیستم‌عاملت رو انتخاب کن:"
        kb = K.tutorials_kb(tuts)
    if q:
        await q.answer()
        await q.message.reply_text(txt, reply_markup=kb)
    else:
        await update.message.reply_text(txt, reply_markup=kb)


async def tutorial_view(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        tid: int) -> None:
    q = update.callback_query
    await q.answer()
    tut = await db.get_tutorial(tid)
    if not tut or not tut["active"]:
        await q.answer("یافت نشد.", show_alert=True)
        return
    body = await _render_tutorial(tut)
    if tut.get("photo_file_id"):
        try:
            await q.message.reply_photo(tut["photo_file_id"])
        except Exception as e:
            log.warning("tutorial photo failed: %s", e)
    await q.message.reply_text(f"{tut['title']}\n\n{body}",
                               reply_markup=K.tut_back_kb())


async def tutorial_links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    txt = T.DL_LINKS_TEXT.format(
        dl_android=await db.get_setting("dl_android", ""),
        dl_ios=await db.get_setting("dl_ios", ""),
        dl_windows=await db.get_setting("dl_windows", ""),
    )
    await q.message.reply_text(txt, reply_markup=K.tut_back_kb())


# ---------------- support ----------------
async def _handle_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg.text or msg.text.startswith("/"):
        await msg.reply_text(T.SUPPORT_ASK)
        return
    context.user_data.pop("st", None)
    u = msg.from_user
    uname = f"@{u.username}" if u.username else str(u.id)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✉️ پاسخ", callback_data=f"adm_reply:{u.id}")]])
    await notify_admins(context, f"💬 پیام پشتیبانی از {uname} ({u.id}):\n\n{msg.text}",
                        reply_markup=kb)
    await msg.reply_text(T.SUPPORT_SENT, reply_markup=_mm(update))


async def _handle_state(update: Update, context: ContextTypes.DEFAULT_TYPE, st: dict) -> None:
    k = st.get("k")
    if k == "receipt":
        await _handle_receipt(update, context, st)
    elif k == "support":
        await _handle_support(update, context)
    elif k == "wallet_amount":
        from handlers_admin import _num
        n = _num(update.message.text)
        if not n or n <= 0:
            await update.message.reply_text("❌ یه عدد معتبر بفرست (تومان).")
            return
        card_block = await _card_block()
        if not card_block:
            context.user_data.pop("st", None)
            await update.message.reply_text(T.NO_CARD)
            return
        # State only after the card screen was delivered: if the reply
        # fails the user stays in wallet_amount and can send it again,
        # instead of being stuck waiting for a receipt they never saw.
        await send_md(
            update.message.reply_text,
            f"{card_block}\n\n💰 مبلغ شارژ: {T.fmt_price(n)}\n\n{T.RECEIPT_ASK}")
        context.user_data["st"] = {"k": "receipt", "kind": "topup",
                                   "plan_id": None, "amount": n}
    else:
        # admin states are handled in handlers_admin
        from handlers_admin import handle_admin_state
        handled = await handle_admin_state(update, context, st)
        if not handled:
            context.user_data.pop("st", None)
            await update.message.reply_text(T.MAIN_MENU_HINT, reply_markup=_mm(update))


# ---------------- callback router ----------------
async def chklock_recheck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """u:chklock — recheck membership after the user joined the channels."""
    q = update.callback_query
    await q.answer()
    missing = await missing_lock_channels(context.bot, q.from_user.id)
    if missing:
        await show_channel_lock(q.message, missing)
        return
    await q.message.reply_text(
        "✅ عضویتت تایید شد! از منوی زیر شروع کن 👇", reply_markup=_mm(update))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data or ""
    st = context.user_data.get("st") or {}
    if data == "u:chklock":
        await chklock_recheck(update, context)
        return
    # channel lock gates every user callback (admins are exempt inside);
    # the lock's own recheck button above is the only exception
    if await enforce_channel_lock(q.message, context, q.from_user.id):
        return
    if data == "u:plans":
        await show_plans(update, context)
    elif data == "u:servers":
        await show_servers(update, context)
    elif data.startswith("u:server:"):
        await server_picked(update, context)
    elif data.startswith("u:plan:"):
        if st.get("k") == "renew_pick":
            await renew_plan_picked(update, context)
        else:
            await plan_detail(update, context)
    elif data.startswith("u:buy:"):
        await buy_start(update, context)
    elif data.startswith("u:walletbuy:"):
        await wallet_buy(update, context)
    elif data.startswith("u:cryptobuy:"):
        await crypto_buy_start(update, context)
    elif data == "u:renewcrypto":
        await crypto_renew_start(update, context)
    elif data.startswith("u:crycur:"):
        await crypto_currency(update, context)
    elif data.startswith("u:crynet:"):
        await crypto_create(update, context)
    elif data.startswith("u:crycheck:"):
        await crypto_check_manual(update, context)
    elif data.startswith("u:crycancel:"):
        await crypto_cancel(update, context)
    elif data == "u:wallettop":
        await wallet_topup_start(update, context)
    elif data == "u:renewcard":
        await renew_pay_card(update, context)
    elif data == "u:renewwallet":
        await renew_pay_wallet(update, context)
    elif data == "u:my":
        await my_services(update, context)
    elif data.startswith("u:svc:"):
        await service_refresh(update, context)
    elif data.startswith("u:renew:"):
        await renew_start(update, context)
    elif data.startswith("u:renewone:"):
        await renew_one(update, context)
    elif data.startswith("u:links:"):
        await resend_links(update, context)
    elif data == "u:tuts":
        await tutorials_menu(update, context)
    elif data.startswith("u:tut:"):
        await tutorial_view(update, context, int(data.split(":")[2]))
    elif data == "u:tutlinks":
        await tutorial_links(update, context)
    elif data == "u:home":
        await q.answer()
        await q.message.reply_text("🏠", reply_markup=_mm(update))
    else:
        # admin callbacks
        from handlers_admin import on_admin_callback
        await on_admin_callback(update, context)
