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
                          lock_join_rows, enforce_channel_lock)


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
    def __init__(self, statuses=None, fail_on=()):
        # statuses: {channel: status}; fail_on: channels raising an error
        self.statuses = statuses or {}
        self.fail_on = set(fail_on)
        self.sent = []

    async def get_chat_member(self, chat_id, user_id):
        if chat_id in self.fail_on:
            raise RuntimeError("Forbidden: bot is not an admin")
        return SimpleNamespace(status=self.statuses.get(chat_id, "left"))

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
    kb = lock_join_rows(["@a", "-100123"])
    rows = kb.inline_keyboard
    assert rows[0][0].url == "https://t.me/a"
    assert len(rows) == 2  # one join button + recheck
    assert rows[1][0].callback_data == "u:chklock"


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
