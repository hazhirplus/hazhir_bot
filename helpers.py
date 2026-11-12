"""Shared helpers: panel access, admin notify, service delivery, QR."""
from __future__ import annotations
import io
import json
import logging
import time
from functools import partial

import qrcode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import db
import text as T
import keyboards as K
from panel import (PanelClient, PanelError, gen_email, gen_subid,
                   decode_sub_links, gb_to_bytes, days_to_ms)

log = logging.getLogger("hozhir")


def _to_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_int(v, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def panel_client_for(panel: dict, verify: bool = True) -> PanelClient:
    return PanelClient(panel["url"], panel["token"], verify=verify)


async def send_md(send, text, **kwargs):
    """Send/edit a message as Markdown, falling back to plain text.

    Free text (plan names, card holders, admin-written guides) can
    contain Markdown metacharacters (_ * [ ]) that make Telegram
    reject the whole message; without a fallback the tap silently
    dies — the callback query was already answered, so even the error
    alert cannot be shown. `send` is any send/edit callable taking
    (text, parse_mode=..., **kwargs); for bot.send_message bind the
    chat id first, e.g. partial(context.bot.send_message, chat_id).
    """
    try:
        await send(text, parse_mode="Markdown", **kwargs)
    except Exception:
        await send(text, **kwargs)


def volume_pct_used(used: int, total: int) -> int:
    """Percent of a volume quota already used (0-100). 0 when unlimited."""
    if total <= 0 or used <= 0:
        return 0
    return min(100, round(used * 100 / total))


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str,
                        reply_markup=None) -> None:
    for aid in config.ADMIN_IDS:
        try:
            await context.bot.send_message(aid, text, reply_markup=reply_markup)
        except Exception as e:
            log.warning("notify admin %s failed: %s", aid, e)


def qr_png(data: str) -> io.BytesIO:
    img = qrcode.make(data)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    bio.name = "qr.png"
    return bio


async def _safe_links(fn, *args) -> list[str]:
    """One link source failing must not abort the delivery.

    Each source already handles its own expected errors, but an
    unexpected one (a malformed panel reply, a network quirk) used to
    escape collect_links and kill the whole approval silently — the
    invoice was already active, yet the customer got nothing. Fall
    through to the next source instead.
    """
    try:
        return await fn(*args) or []
    except Exception as e:
        log.warning("link source %s failed: %s",
                    getattr(fn, "__name__", fn), e)
        return []


async def collect_links(panel: dict, sub_id: str, email: str) -> tuple[str, list[str]]:
    """Return (sub_url, links). Tries API subLinks, then direct sub HTTP, then links(email)."""
    pc = panel_client_for(panel)
    sub_url = panel.get("sub_base", "").rstrip("/") + "/" + sub_id
    links = await _safe_links(pc.sub_links, sub_id)
    if not links and panel.get("sub_base"):
        links = await _safe_links(pc.fetch_sub_http, panel["sub_base"], sub_id)
    if not links and email:
        links = await _safe_links(pc.links, email)
    return sub_url, links


async def activate_crypto_invoice(context: ContextTypes.DEFAULT_TYPE,
                                  inv: dict, txhash: str) -> bool:
    """Shared crypto activation path (manual check + background job).

    Re-runs the standard invoice-approval pipeline (approve_invoice) — no
    duplicated activation logic. Returns True only if the invoice became active.
    """
    inv = await db.get_invoice(inv["id"])
    if not inv or inv.get("status") != "pending" or inv.get("pay_method") != "crypto":
        return False
    from handlers_admin import approve_invoice  # lazy: avoid import cycle
    res = await approve_invoice(context, inv, None)
    inv2 = await db.get_invoice(inv["id"])
    if inv2["status"] != "active":
        log.warning("crypto activation failed for invoice #%s: %s", inv["id"], res)
        return False  # stays pending; the job retries on the next round
    await db.update_invoice(inv["id"], crypto_tx=txhash)
    try:
        await context.bot.send_message(inv["user_id"], T.CRYPTO_CONFIRMED)
    except Exception:
        pass
    return True


async def deliver_service(context: ContextTypes.DEFAULT_TYPE, invoice: dict) -> bool:
    """Send subscription URL + links + QR to the user. Returns success."""
    panel = await db.get_panel(invoice["panel_id"]) if invoice.get("panel_id") \
        else await db.get_available_panel()
    if not panel:
        return False
    plan = await db.get_plan(invoice["plan_id"]) if invoice.get("plan_id") else None
    if invoice.get("kind") == "gift":
        days = _to_int(await db.get_setting("ref_gift_days", "30"), 30)
        gb = _to_float(await db.get_setting("ref_gift_gb", "10"), 10.0)
    else:
        days = plan["days"] if plan else _to_int(await db.get_setting("test_days", "1"), 1)
        gb = plan["gb"] if plan else _to_float(await db.get_setting("test_gb", "2"), 2.0)
    sub_url, links = await collect_links(panel, invoice["sub_id"], invoice["panel_email"])
    link_block = "\n".join(f"`{ln}`" for ln in links[:8]) if links else "—"
    guide = await db.get_setting("delivery_guide", T.DELIVERY_GUIDE_DEFAULT)
    msg = T.SERVICE_DELIVERED.format(
        email=invoice["panel_email"],
        days=days,
        gb=T.fmt_gb_num(gb),
        sub_url=sub_url,
        links=link_block,
    )
    if guide.strip():
        msg += f"\n\n{guide.strip()}"
    msg += f"\n\n{T.QUICK_GUIDE}"
    try:
        await send_md(partial(context.bot.send_message, invoice["user_id"]),
                      msg, reply_markup=K.quick_guide_kb())
        await context.bot.send_photo(
            invoice["user_id"], photo=qr_png(sub_url),
            caption="📷 QR لینک اشتراک — با دوربین اپ اسکن کن")
        return True
    except Exception as e:
        log.warning("deliver_service failed: %s", e)
        return False


async def unique_panel_email(pc: PanelClient, username: str | None,
                             tg_id: int) -> str:
    """Generate a panel email not already taken on the panel."""
    for _ in range(6):
        email = gen_email(username, tg_id)
        try:
            if await pc.get_client(email) is None:
                return email
        except PanelError:
            return email
    return gen_email(username, tg_id) + str(int(time.time()) % 100)


async def resolve_inbounds(pc: PanelClient, panel: dict) -> list[int]:
    """Inbounds a new client should be built on (mirzabot-style reference).

    When the admin set a reference client (setting `ref_client_email`,
    e.g. his own config), the panel's live truth wins: whatever
    inbounds that client uses right now is what new clients get. So
    deleting an inbound from the panel automatically stops it being
    used — no stale bot config, no failed orders. The stored list is
    synced to the resolved one so the inbounds screen stays truthful.
    Falls back to the panel's stored inbounds when no reference is set
    or the reference cannot be read.
    """
    ref = (await db.get_setting("ref_client_email", "") or "").strip()
    if ref:
        try:
            ids = await pc.client_inbounds(ref)
        except PanelError as e:
            log.warning("reference client %s unreadable: %s", ref, e)
            ids = None
        if ids:
            stored = list(panel.get("inbounds") or [])
            if sorted(ids) != sorted(stored):
                await db.update_panel(panel["id"],
                                      inbounds_json=json.dumps(sorted(ids)))
                log.info("inbounds synced from reference %s: %s", ref, ids)
            return sorted(ids)
        log.warning("reference client %s has no inbounds; using stored list",
                    ref)
    return list(panel.get("inbounds") or [])


async def create_panel_client(pc: PanelClient, panel: dict, inv: dict,
                              days: int, gb: int, now: int) -> tuple[str, str, list[int]]:
    """Create the client on the panel. Returns (email, sub_id, skipped).

    Resilient to a deleted inbound: 3x-ui fails the whole /clients/add
    when ANY inbound id in the list no longer exists on the panel, so
    one deleted inbound used to break every new order. Inbounds come
    from the reference client when one is configured (see
    resolve_inbounds); the call first tries all of them, then falls
    back to adding the client on the inbounds one by one and attaching
    the rest, skipping the ones the panel no longer has. `skipped`
    lists those inbound ids so the caller can tell the admin to fix
    the panel config. Raises PanelError only when NO inbound accepts
    the client.
    """
    from panel import gb_to_bytes, days_to_ms
    user = await db.get_user(inv["user_id"])
    username = (user or {}).get("username")
    email = await unique_panel_email(pc, username, inv["user_id"])
    sub_id = gen_subid()
    inbounds = await resolve_inbounds(pc, panel)
    if not inbounds:
        raise PanelError("no inbounds configured", code="api")
    expiry_ms = now * 1000 + days_to_ms(days)
    total_bytes = gb_to_bytes(gb)
    first_err: PanelError | None = None
    try:
        await pc.add_client(inbounds, email, total_bytes, expiry_ms, sub_id,
                            tg_id=inv["user_id"], comment=f"hozhir:{inv['user_id']}")
        return email, sub_id, []
    except PanelError as e:
        first_err = e
        log.warning("add_client all-inbounds failed (%s); retrying per-inbound", e)
    skipped: list[int] = []
    created = False
    for ib in inbounds:
        if created:
            try:
                await pc.attach(email, [ib])
            except PanelError as e:
                log.warning("attach inbound %s failed: %s", ib, e)
                skipped.append(ib)
            continue
        try:
            await pc.add_client([ib], email, total_bytes, expiry_ms, sub_id,
                                tg_id=inv["user_id"], comment=f"hozhir:{inv['user_id']}")
            created = True
        except PanelError as e:
            log.warning("add_client inbound %s failed: %s", ib, e)
            skipped.append(ib)
    if not created:
        raise first_err
    return email, sub_id, skipped


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        uid = update.effective_user.id if update.effective_user else None
        if not config.is_admin(uid):
            if update.callback_query:
                await update.callback_query.answer(T.NEED_ADMIN, show_alert=True)
            elif update.message:
                await update.message.reply_text(T.NEED_ADMIN)
            return
        return await func(update, context, *a, **kw)
    return wrapper


async def maybe_grant_referral_gift(context: ContextTypes.DEFAULT_TYPE, inv: dict) -> None:
    """Gift the referrer a service on the referred user's FIRST paid purchase.

    Call after any paid activation (admin approval, wallet purchase, wallet renew).
    Silent to the purchase flow; logs to admins; one gift per referred user.
    """
    if not inv or inv.get("kind") not in ("purchase", "renew"):
        return
    if (await db.get_setting("ref_enabled", "1")) != "1":
        return
    uid = inv["user_id"]
    # only the very first paid purchase of this user triggers a gift
    if await db.count_paid_purchases(uid) != 1:
        return
    ref = await db.get_pending_referral(uid)
    if not ref:
        return
    referrer = ref["referrer_id"]
    try:
        days = _to_int(await db.get_setting("ref_gift_days", "30"), 30)
        gb = _to_float(await db.get_setting("ref_gift_gb", "10"), 10.0)
    except (TypeError, ValueError):
        days, gb = 30, 10.0
    panel = await db.get_available_panel()
    if not panel:
        log.warning("referral gift skipped: no active panel")
        return
    gid = await db.create_invoice(user_id=referrer, kind="gift",
                                  plan_id=None, price_toman=0)
    pc = panel_client_for(panel)
    now = int(time.time())
    try:
        email, sub_id, skipped = await create_panel_client(
            pc, panel, await db.get_invoice(gid), days, gb, now)
        if skipped:
            log.warning("referral gift skipped inbounds %s", skipped)
    except PanelError as e:
        log.warning("referral gift panel error: %s", e)
        await db.update_invoice(gid, status="expired")
        return
    await db.update_invoice(gid, status="active", panel_id=panel["id"],
                            panel_email=email, sub_id=sub_id,
                            activated_at=now, expires_at=now + days_to_ms(days) // 1000,
                            warned_at=0)
    await db.mark_referral_gifted(ref["id"], gid)
    await deliver_service(context, await db.get_invoice(gid))
    await notify_admins(context, "🎁 هدیه رفرال ساخته شد",
                        f"👤 دعوت‌کننده: {referrer}\n🆕 دعوت‌شده: {uid}\n🎁 {T.fmt_gb_num(gb)} گیگ / {days} روزه")
