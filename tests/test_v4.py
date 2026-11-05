"""v4 tests: volume-depletion warning + warn-flag only on successful send.

hourly_check now warns users at >=warn_volume_pct% usage (default 80), and
both warning flags (warned_at / volume_warned_at) are set only when the
Telegram send actually succeeded, so a transient failure retries next hour.
All DB tests use a temp sqlite file; the panel is faked.
"""
import asyncio
import os
import sys
import time
from types import SimpleNamespace

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import jobs
from helpers import volume_pct_used

GB = 1024 ** 3


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "v4.db")
    run(_init(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    return p


async def _init(p):
    await db.init_db(p)
    await db.seed_from_env(p)


# ---------- volume_pct_used ----------
def test_volume_pct_used():
    assert volume_pct_used(0, 10 * GB) == 0
    assert volume_pct_used(8 * GB, 10 * GB) == 80
    assert volume_pct_used(85 * GB // 10, 10 * GB) == 85
    assert volume_pct_used(10 * GB, 10 * GB) == 100
    assert volume_pct_used(12 * GB, 10 * GB) == 100  # capped
    assert volume_pct_used(5 * GB, 0) == 0  # unlimited plan
    assert volume_pct_used(-1, 10 * GB) == 0


# ---------- migration: old DB gains volume_warned_at ----------
def test_migration_adds_volume_warned_at(tmp_path):
    p = str(tmp_path / "old.db")

    async def _make_old():
        async with aiosqlite.connect(p) as con:
            await con.execute(
                "CREATE TABLE invoices(id INTEGER PRIMARY KEY, user_id INTEGER,"
                " kind TEXT, status TEXT, panel_email TEXT DEFAULT '',"
                " expires_at INTEGER DEFAULT 0, warned_at INTEGER DEFAULT 0)")
            await con.commit()

    run(_make_old())
    run(db.init_db(p))

    async def _cols():
        async with aiosqlite.connect(p) as con:
            cur = await con.execute("PRAGMA table_info(invoices)")
            return [r[1] for r in await cur.fetchall()]

    assert "volume_warned_at" in run(_cols())


# ---------- due_for_volume_warn filtering ----------
def test_due_for_volume_warn(dbpath):
    async def _seed():
        pid = await db.add_panel("p1", "http://127.0.0.1:1", "t",
                                 "http://127.0.0.1:1/", "[1]", path=dbpath)
        plan = await db.add_plan("10G", 30, 10, 90000, path=dbpath)
        now = int(time.time())
        # candidate: active, unwarned, has panel account
        a = await db.create_invoice(11, "purchase", plan, 90000, path=dbpath,
                                    status="active", panel_id=pid,
                                    panel_email="a@x", expires_at=now + 30 * 86400)
        # already volume-warned
        b = await db.create_invoice(12, "purchase", plan, 90000, path=dbpath,
                                    status="active", panel_id=pid,
                                    panel_email="b@x", expires_at=now + 30 * 86400,
                                    volume_warned_at=now)
        # no panel account yet
        c = await db.create_invoice(13, "purchase", plan, 90000, path=dbpath,
                                    status="active", panel_id=pid,
                                    panel_email="", expires_at=now + 30 * 86400)
        # not active
        d = await db.create_invoice(14, "purchase", plan, 90000, path=dbpath,
                                    status="pending", panel_id=pid,
                                    panel_email="d@x", expires_at=now + 30 * 86400)
        return a, b, c, d

    a, b, c, d = run(_seed())
    got = run(db.due_for_volume_warn(path=dbpath))
    assert [i["id"] for i in got] == [a]
    # update_invoice accepts the new flag
    run(db.update_invoice(a, path=dbpath, volume_warned_at=123))
    assert run(db.get_invoice(a, path=dbpath))["volume_warned_at"] == 123


# ---------- hourly_check end-to-end with a fake panel ----------
class FakePanel:
    """email -> (total_bytes, used_bytes); None client means 'not on panel'."""

    def __init__(self, data):
        self.data = data

    async def get_client(self, email):
        if email not in self.data:
            return None
        total, _used = self.data[email]
        return {"totalGB": total}

    async def traffic(self, email):
        _total, used = self.data[email]
        return {"up": used // 2, "down": used - used // 2}


class FakeBot:
    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    async def send_message(self, chat_id, text, reply_markup=None):
        if chat_id in self.fail_for:
            raise RuntimeError("send failed (simulated)")
        self.sent.append((chat_id, text))


def test_hourly_check_volume_warn(dbpath, monkeypatch):
    async def _seed():
        pid = await db.add_panel("p1", "http://127.0.0.1:1", "t",
                                 "http://127.0.0.1:1/", "[1]", path=dbpath)
        plan = await db.add_plan("10G", 30, 10, 90000, path=dbpath)
        now = int(time.time())
        far = now + 30 * 86400  # far from expiry: no time-warn interference
        ids = {}
        ids["heavy"] = await db.create_invoice(
            21, "purchase", plan, 90000, path=dbpath, status="active",
            panel_id=pid, panel_email="heavy@x", expires_at=far)
        ids["light"] = await db.create_invoice(
            22, "purchase", plan, 90000, path=dbpath, status="active",
            panel_id=pid, panel_email="light@x", expires_at=far)
        ids["unlimited"] = await db.create_invoice(
            23, "purchase", plan, 90000, path=dbpath, status="active",
            panel_id=pid, panel_email="unl@x", expires_at=far)
        ids["failing"] = await db.create_invoice(
            24, "purchase", plan, 90000, path=dbpath, status="active",
            panel_id=pid, panel_email="fail@x", expires_at=far)
        return ids

    ids = run(_seed())
    fake_panel = FakePanel({
        "heavy@x": (10 * GB, 85 * GB // 10),   # 85% -> warn
        "light@x": (10 * GB, 5 * GB),          # 50% -> silent
        "unl@x": (0, 9 * GB),                  # unlimited -> silent
        "fail@x": (10 * GB, 9 * GB),           # 90% -> warn attempt, send fails
    })
    monkeypatch.setattr(jobs, "panel_client_for", lambda panel: fake_panel)
    bot = FakeBot(fail_for={24})
    ctx = SimpleNamespace(bot=bot)
    run(jobs.hourly_check(ctx))

    warned_users = [uid for uid, _ in bot.sent]
    assert warned_users == [21]  # only the 85% user got the message
    assert "۸۵٪" in bot.sent[0][1] or "85" in bot.sent[0][1]
    assert "فقط" in bot.sent[0][1]  # remaining volume mentioned

    inv = run(db.get_invoice(ids["heavy"], path=dbpath))
    assert inv["volume_warned_at"] > 0
    inv = run(db.get_invoice(ids["light"], path=dbpath))
    assert inv["volume_warned_at"] == 0
    inv = run(db.get_invoice(ids["unlimited"], path=dbpath))
    assert inv["volume_warned_at"] == 0
    # send failed -> flag NOT set, so next hour retries instead of losing it
    inv = run(db.get_invoice(ids["failing"], path=dbpath))
    assert inv["volume_warned_at"] == 0


def test_expiry_warn_retries_after_send_failure(dbpath, monkeypatch):
    """Same mark-only-on-success rule for the pre-existing time warning."""
    async def _seed():
        plan = await db.add_plan("10G", 30, 10, 90000, path=dbpath)
        now = int(time.time())
        return await db.create_invoice(
            31, "purchase", plan, 90000, path=dbpath, status="active",
            panel_id=None, panel_email="",
            expires_at=now + 12 * 3600)  # inside the 24h warn window

    iid = run(_seed())
    monkeypatch.setattr(jobs, "panel_client_for",
                        lambda panel: (_ for _ in ()).throw(AssertionError(
                            "panel must not be touched for this invoice")))
    bot = FakeBot(fail_for={31})
    run(jobs.hourly_check(SimpleNamespace(bot=bot)))
    inv = run(db.get_invoice(iid, path=dbpath))
    assert inv["warned_at"] == 0  # failed send -> retry next hour
    assert bot.sent == []
