"""Channel lock (قفل کانال) for the VPN bot — port of the shopbot design.

Default OFF, admins exempt, fail-closed on get_chat_member errors,
lock message with join buttons + a recheck button.
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
from channel_lock import (parse_channel_lock_list, channel_lock_list,
                          channel_lock_active, missing_lock_channels,
                          lock_join_rows, show_channel_lock,
                          enforce_channel_lock)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "chlock.db")
    run(db.init_db(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [999])
    return p


class FakeMsg:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append((text, reply_markup))
        return None


class FakeBot:
    def __init__(self, statuses=None, fail_on=(), chats=None):
        # statuses: {channel: status}; fail_on: channels raising an error
        # chats: {chat_id: SimpleNamespace(username=..., invite_link=...)}
        self.statuses = statuses or {}
        self.fail_on = set(fail_on)
        self.chats = chats or {}
        self.sent = []

    async def get_chat_member(self, chat_id, user_id):
        if chat_id in self.fail_on:
            raise RuntimeError("Forbidden: bot is not an admin")
        return SimpleNamespace(status=self.statuses.get(chat_id, "left"))

    async def get_chat(self, chat_id):
        if chat_id in self.chats:
            return self.chats[chat_id]
        raise RuntimeError("Chat not found")

    async def send_message(self, chat_id, text, reply_markup=None,
                           parse_mode=None):
        self.sent.append((chat_id, text))


def _ctx(bot):
    return SimpleNamespace(bot=bot, user_data={})


def _enable(channels, dbpath):
    run(db.set_setting("channel_lock_enabled", "1", path=dbpath))
    run(db.set_setting("channel_lock_list", json.dumps(channels),
                       path=dbpath))


# ---------------- parsing / activation ----------------
def test_parse_channel_lock_list():
    assert parse_channel_lock_list("@a, @b\n@c") == ["@a", "@b", "@c"]
    assert parse_channel_lock_list("@a, @a, @b") == ["@a", "@b"]
    assert parse_channel_lock_list("-100123") == ["-100123"]
    assert parse_channel_lock_list("پاک") == []
    assert parse_channel_lock_list("") == []
    assert parse_channel_lock_list(None) == []


def test_lock_off_by_default(dbpath):
    assert run(channel_lock_active()) is False
    assert run(channel_lock_list()) == []


def test_lock_needs_enabled_and_nonempty_list(dbpath):
    run(db.set_setting("channel_lock_enabled", "1", path=dbpath))
    assert run(channel_lock_active()) is False  # list empty -> inert
    run(db.set_setting("channel_lock_list", '["@a"]', path=dbpath))
    assert run(channel_lock_active()) is True
    run(db.set_setting("channel_lock_enabled", "0", path=dbpath))
    assert run(channel_lock_active()) is False


def test_lock_broken_json_means_empty_list(dbpath):
    run(db.set_setting("channel_lock_enabled", "1", path=dbpath))
    run(db.set_setting("channel_lock_list", "not-json{{", path=dbpath))
    assert run(channel_lock_list()) == []
    assert run(channel_lock_active()) is False


# ---------------- membership ----------------
def test_missing_channels(dbpath):
    _enable(["@a", "@b", "@c"], dbpath)
    bot = FakeBot({"@a": "member", "@b": "left", "@c": "creator"})
    assert run(missing_lock_channels(bot, 111)) == ["@b"]


def test_member_statuses_count(dbpath):
    _enable(["@a", "@b", "@c"], dbpath)
    bot = FakeBot({"@a": "administrator", "@b": "member", "@c": "kicked"})
    assert run(missing_lock_channels(bot, 111)) == ["@c"]


def test_get_chat_member_error_is_fail_closed(dbpath):
    """A private channel the bot is not admin of stays in the missing list."""
    _enable(["@a", "@priv"], dbpath)
    bot = FakeBot({"@a": "member"}, fail_on=("@priv",))
    assert run(missing_lock_channels(bot, 111)) == ["@priv"]


def test_lock_join_rows_only_username_channels_get_links():
    kb = run(lock_join_rows(FakeBot(), ["@a", "-100123"]))
    rows = kb.inline_keyboard
    assert rows[0][0].url == "https://t.me/a"
    assert len(rows) == 2  # one join button + recheck
    assert rows[1][0].callback_data == "u:chklock"


# ---------------- numeric-id channels (N4b) ----------------
def test_lock_join_rows_numeric_channel_with_invite_link():
    bot = FakeBot(chats={"-100123": SimpleNamespace(
        username=None, invite_link="https://t.me/+abc123")})
    kb = run(lock_join_rows(bot, ["-100123"]))
    rows = kb.inline_keyboard
    assert rows[0][0].url == "https://t.me/+abc123"
    assert rows[0][0].text == "📣 عضویت در -100123"


def test_lock_join_rows_numeric_public_channel_uses_username():
    bot = FakeBot(chats={"-100123": SimpleNamespace(
        username="mychannel", invite_link=None)})
    kb = run(lock_join_rows(bot, ["-100123"]))
    assert kb.inline_keyboard[0][0].url == "https://t.me/mychannel"


def test_lock_join_rows_numeric_unreachable_channel_no_button(dbpath):
    """No invite link and get_chat fails: no button, but the lock message
    still shows the id with guidance — no UX dead end."""
    _enable(["-100123"], dbpath)
    msg = FakeMsg()
    run(show_channel_lock(msg, ["-100123"], FakeBot()))
    text, kb = msg.replies[-1]
    assert "-100123" in text
    assert "دکمه ندارد" in text
    assert all(b.url is None for row in kb.inline_keyboard for b in row)
    assert kb.inline_keyboard[-1][0].callback_data == "u:chklock"


# ---------------- enforcement ----------------
def test_enforce_admin_exempt(dbpath):
    _enable(["@a"], dbpath)
    bot = FakeBot({"@a": "left"})
    msg = FakeMsg()
    assert run(enforce_channel_lock(msg, _ctx(bot), 999)) is False
    assert msg.replies == []


def test_enforce_blocks_nonmember_and_shows_lock(dbpath):
    _enable(["@a", "@b"], dbpath)
    bot = FakeBot({"@a": "member", "@b": "left"})
    msg = FakeMsg()
    assert run(enforce_channel_lock(msg, _ctx(bot), 111)) is True
    text, kb = msg.replies[-1]
    assert "🔒" in text and "@b" in text and "@a" not in text
    assert kb.inline_keyboard[-1][0].callback_data == "u:chklock"


def test_enforce_passes_member(dbpath):
    _enable(["@a"], dbpath)
    bot = FakeBot({"@a": "member"})
    msg = FakeMsg()
    assert run(enforce_channel_lock(msg, _ctx(bot), 111)) is False
    assert msg.replies == []


def test_enforce_inactive_lock_passes_everyone(dbpath):
    bot = FakeBot({"@a": "left"})
    msg = FakeMsg()
    assert run(enforce_channel_lock(msg, _ctx(bot), 111)) is False


# ---------------- receipt path must not bypass the lock (N4a) ----------------
def _receipt_ctx(bot):
    ctx = _ctx(bot)
    ctx.user_data["st"] = {"k": "receipt", "iid": 1}
    return ctx


def test_receipt_photo_blocked_by_channel_lock(dbpath, monkeypatch):
    """on_media: a receipt photo from a non-member is rejected — the
    receipt state must not bypass the channel lock."""
    import main as main_mod
    _enable(["@a"], dbpath)
    bot = FakeBot({"@a": "left"})
    msg = FakeMsg()
    upd = SimpleNamespace(message=msg,
                          effective_user=SimpleNamespace(id=111))
    calls = []

    async def fake_handle_state(update, context, st):
        calls.append(st)

    monkeypatch.setattr(main_mod, "_handle_state", fake_handle_state)
    run(main_mod.on_media(upd, _receipt_ctx(bot)))
    assert calls == []
    assert msg.replies and "🔒" in msg.replies[-1][0]


def test_receipt_photo_passes_for_member(dbpath, monkeypatch):
    import main as main_mod
    _enable(["@a"], dbpath)
    bot = FakeBot({"@a": "member"})
    msg = FakeMsg()
    upd = SimpleNamespace(message=msg,
                          effective_user=SimpleNamespace(id=111))
    calls = []

    async def fake_handle_state(update, context, st):
        calls.append(st)

    monkeypatch.setattr(main_mod, "_handle_state", fake_handle_state)
    run(main_mod.on_media(upd, _receipt_ctx(bot)))
    assert len(calls) == 1 and calls[0]["k"] == "receipt"
    assert msg.replies == []


def test_receipt_tracking_text_blocked_by_channel_lock(dbpath, monkeypatch):
    """on_text: the same hole exists for a typed tracking number — the
    lock is checked there too (extension beyond the letter of N4)."""
    import main as main_mod
    _enable(["@a"], dbpath)
    bot = FakeBot({"@a": "left"})
    msg = FakeMsg()
    msg.text = "123456789"
    upd = SimpleNamespace(message=msg,
                          effective_user=SimpleNamespace(id=111))
    calls = []

    async def fake_handle_state(update, context, st):
        calls.append(st)

    monkeypatch.setattr(main_mod, "_handle_state", fake_handle_state)
    run(main_mod.on_text(upd, _receipt_ctx(bot)))
    assert calls == []
    assert msg.replies and "🔒" in msg.replies[-1][0]
