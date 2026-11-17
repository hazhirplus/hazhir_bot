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


async def channel_join_url(bot, ch: str) -> str | None:
    """Join URL for a locked channel, or None when the bot cannot make one.

    @username channels link straight to t.me. A numeric id (-100...)
    needs the bot to read the channel: a public channel's username,
    else its invite link (the bot must be an admin to see it). When
    neither is available, None — the lock message shows the id with
    guidance instead of a dead end (N4b).
    """
    if ch.startswith("@"):
        return f"https://t.me/{ch[1:]}"
    try:
        chat = await bot.get_chat(ch)
    except Exception:
        return None
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}"
    return getattr(chat, "invite_link", None)


async def lock_join_rows(bot, missing) -> InlineKeyboardMarkup:
    """Join button per channel that has a URL + the recheck button."""
    rows = []
    for ch in missing:
        url = await channel_join_url(bot, ch)
        if url:
            rows.append([InlineKeyboardButton(
                f"📣 عضویت در {ch}", url=url)])
    rows.append([InlineKeyboardButton("✅ عضو شدم — بررسی عضویت",
                                      callback_data="u:chklock")])
    return InlineKeyboardMarkup(rows)


async def show_channel_lock(msg, missing, bot) -> None:
    """Lock message: missing channels + join buttons + recheck."""
    lines = ["🔒 برای استفاده از ربات، اول در این کانال‌ها عضو شو:\n"]
    for ch in missing:
        lines.append(f"• {ch}")
    kb = await lock_join_rows(bot, missing)
    got_button = {b.text.removeprefix("📣 عضویت در ")
                  for row in kb.inline_keyboard for b in row if b.url}
    if any(ch not in got_button for ch in missing):
        lines.append("\n⚠️ کانالی که دکمه ندارد را با همین آیدی در تلگرام "
                     "جستجو کن یا از ادمین لینک دعوت بگیر.")
    lines.append("\nبعد از عضویت، «✅ عضو شدم — بررسی عضویت» رو بزن.")
    await msg.reply_text("\n".join(lines), reply_markup=kb)


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
    await show_channel_lock(msg, missing, context.bot)
    return True
