"""Channel lock (قفل کانال): users must join the listed channels first.

Port of the shopbot design (~/workspace/shopbot/CHANNEL_LOCK_DESIGN.md):
default OFF, admins exempt, fail-closed on get_chat_member errors (a
private channel the bot is not admin of stays in the missing list, and
the admin has to make the bot an admin of that channel).
"""
from __future__ import annotations
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
import db


def parse_channel_lock_list(raw):
    """«@a, @b\\n@c» -> clean unique list, in input order.

    A numeric id («-100...») is accepted too; «پاک»/empty means an empty
    list. Pure, for testability.
    """
    if not raw or (raw or "").strip() in ("پاک", "-"):
        return []
    out = []
    for part in (raw or "").replace("\n", ",").split(","):
        ch = part.strip()
        if ch and ch not in out:
            out.append(ch)
    return out


async def channel_lock_list() -> list[str]:
    """Locked channels from settings — broken JSON means an empty list."""
    try:
        v = json.loads(await db.get_setting("channel_lock_list", "") or "[]")
    except Exception:
        return []
    return [str(x).strip() for x in v if str(x).strip()]


async def channel_lock_active() -> bool:
    """The lock only bites when the toggle is on AND the list is non-empty."""
    if await db.get_setting("channel_lock_enabled", "0") == "0":
        return False
    return bool(await channel_lock_list())


def is_member_status(status) -> bool:
    """get_chat_member statuses that count as «a member»."""
    return status in ("member", "administrator", "creator")


async def missing_lock_channels(bot, uid: int) -> list[str]:
    """Channels from the lock list the user is not a member of.

    A get_chat_member error (e.g. a private channel the bot is not an
    admin of) means «membership cannot be verified» — fail-closed: the
    channel stays in the missing list.
    """
    missing = []
    for ch in await channel_lock_list():
        try:
            m = await bot.get_chat_member(ch, uid)
            if not is_member_status(getattr(m, "status", None)):
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return missing


def lock_join_rows(missing) -> InlineKeyboardMarkup:
    """Join button per @username channel + the recheck button."""
    rows = []
    for ch in missing:
        if ch.startswith("@"):
            rows.append([InlineKeyboardButton(
                f"📣 عضویت در {ch}", url=f"https://t.me/{ch[1:]}")])
    rows.append([InlineKeyboardButton("✅ عضو شدم — بررسی عضویت",
                                      callback_data="u:chklock")])
    return InlineKeyboardMarkup(rows)


async def show_channel_lock(msg, missing) -> None:
    """Lock message: missing channels + join buttons + recheck."""
    lines = ["🔒 برای استفاده از ربات، اول در این کانال‌ها عضو شو:\n"]
    for ch in missing:
        lines.append(f"• {ch}")
    lines.append("\nبعد از عضویت، «✅ عضو شدم — بررسی عضویت» رو بزن.")
    await msg.reply_text("\n".join(lines), reply_markup=lock_join_rows(missing))


async def enforce_channel_lock(msg, context, uid: int) -> bool:
    """Show the lock message when a non-admin is missing a channel.

    Returns True when the caller must stop handling this update.
    """
    if config.is_admin(uid):
        return False
    if not await channel_lock_active():
        return False
    missing = await missing_lock_channels(context.bot, uid)
    if not missing:
        return False
    await show_channel_lock(msg, missing)
    return True
