"""Orphaned panel accounts: active invoices whose client was deleted
from the 3x-ui panel (3x-ui answers get_client with success:false,
msg "Obtain (record not found)").

Before this fix:
  - hourly_check logged "volume warn check failed" for them EVERY hour;
  - renewing one failed with "panel error" even though the customer
    paid, because the recreate-fresh fallback was unreachable
    (get_client raises instead of returning None);
  - the service card showed a generic "status read error".

After: the volume check marks them once (volume_warned_at=-1) and
tells the admin once; renew recreates the client; the card says
"not found in the panel". All DB tests use a temp sqlite file;
the panel and the Telegram bot are faked.
"""
import asyncio
import os
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import helpers
import jobs
from panel import PanelError

GB = 1024 ** 3


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "orphan.db")
    run(_init(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [999])
    return p


async def _init(p):
    await db.init_db(p)
    await db.seed_from_env(p)


class FakeBot:
    def __init__(self):
        self.sent = []  # (chat_id, text)

    async def send_message(self, chat_id, text, reply_markup=None,
                           parse_mode=None):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, photo, caption=None):
        self.sent.append((chat_id, caption or ""))


# ---------- PanelError.is_not_found ----------
def test_is_not_found():
    assert PanelError("Obtain (record not found)", code="api").is_not_found
    assert PanelError("not found", code="notfound").is_not_found
    assert not PanelError("bad token", code="auth").is_not_found
    assert not PanelError("timeout", code="timeout").is_not_found
    assert not PanelError("http 500", code="api").is_not_found


# ---------- hourly_check: orphan marked once, admin told once ----------
class RaisingPanel:
    """get_client raises the exact 3x-ui error for missing clients."""

    def __init__(self, present):
        self.present = present  # email -> (total, used)

    async def get_client(self, email):
        if email not in self.present:
            raise PanelError("Obtain (record not found)", code="api")
        total, _used = self.present[email]
        return {"totalGB": total}

    async def traffic(self, email):
        _total, used = self.present[email]
        return {"up": used // 2, "down": used - used // 2}


class NonePanel:
    """get_client returns None for missing clients (other panel versions)."""

    def __init__(self, present):
        self.present = present

    async def get_client(self, email):
        if email not in self.present:
            return None
        total, _used = self.present[email]
        return {"totalGB": total}

    async def traffic(self, email):
        _total, used = self.present[email]
        return {"up": used // 2, "down": used - used // 2}


def _seed_two(dbpath):
    async def _seed():
        pid = await db.add_panel("p1", "http://127.0.0.1:1", "t",
                                 "http://127.0.0.1:1/", "[1]", path=dbpath)
        plan = await db.add_plan("10G", 30, 10, 90000, path=dbpath)
        now = int(time.time())
        far = now + 30 * 86400  # far from expiry: no time-warn interference
        gone = await db.create_invoice(
            41, "purchase", plan, 90000, path=dbpath, status="active",
            panel_id=pid, panel_email="gone@x", expires_at=far)
        ok = await db.create_invoice(
            42, "purchase", plan, 90000, path=dbpath, status="active",
            panel_id=pid, panel_email="ok@x", expires_at=far)
        return gone, ok

    return run(_seed())


def test_hourly_check_orphan_marked_and_admin_alerted_once(dbpath, monkeypatch):
    gone, ok = _seed_two(dbpath)
    panel = RaisingPanel({"ok@x": (10 * GB, 1 * GB)})  # low usage: silent
    monkeypatch.setattr(jobs, "panel_client_for", lambda p: panel)
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot)

    run(jobs.hourly_check(ctx))

    inv = run(db.get_invoice(gone, path=dbpath))
    assert inv["volume_warned_at"] == -1  # orphan sentinel, stops re-checks
    assert inv["status"] == "active"  # still active: only the check stopped
    inv = run(db.get_invoice(ok, path=dbpath))
    assert inv["volume_warned_at"] == 0
    # admin (999) got exactly one alert listing the orphan invoice
    admin_msgs = [t for uid, t in bot.sent if uid == 999]
    assert len(admin_msgs) == 1
    assert f"#{gone}" in admin_msgs[0] and "gone@x" in admin_msgs[0]
    assert "پنل" in admin_msgs[0]
    # no user was warned about volume
    assert [uid for uid, _ in bot.sent if uid in (41, 42)] == []

    # second hour: invoice is no longer due -> no duplicate alert, no spam
    n_before = len(bot.sent)
    run(jobs.hourly_check(ctx))
    assert len(bot.sent) == n_before
    due = run(db.due_for_volume_warn(path=dbpath))
    assert gone not in [i["id"] for i in due]  # orphan excluded from now on


def test_hourly_check_none_client_is_orphan_too(dbpath, monkeypatch):
    gone, _ok = _seed_two(dbpath)
    monkeypatch.setattr(jobs, "panel_client_for",
                        lambda p: NonePanel({"ok@x": (10 * GB, 1 * GB)}))
    bot = FakeBot()
    run(jobs.hourly_check(SimpleNamespace(bot=bot)))
    assert run(db.get_invoice(gone, path=dbpath))["volume_warned_at"] == -1
    assert any(uid == 999 for uid, _ in bot.sent)


# ---------- renew of an orphan recreates the panel client ----------
class RenewPanel:
    """No client exists on the panel; add_client records what it creates."""

    def __init__(self):
        self.added = []

    async def get_client(self, email):
        raise PanelError("Obtain (record not found)", code="api")

    async def add_client(self, inbound_ids, email, total_bytes, expiry_ms,
                         sub_id, tg_id=0, comment=""):
        self.added.append(email)
        return {}

    async def update_client(self, email, fields):
        return {}

    async def sub_links(self, sub_id):
        return []

    async def fetch_sub_http(self, base, sub_id):
        return []

    async def links(self, email):
        return []


def test_renew_orphan_creates_fresh_client(dbpath, monkeypatch):
    # NOTE: handlers_admin is imported lazily, inside the test, on purpose:
    # test_crypto.py relies on it being first imported AFTER it patches
    # helpers.panel_client_for (its from-import then picks up the fake).
    # A module-level import here would bind the real client and break it.
    import handlers_admin

    async def _seed():
        pid = await db.add_panel("p1", "http://127.0.0.1:1", "t",
                                 "http://127.0.0.1:1/", "[1]", path=dbpath)
        plan = await db.add_plan("10G", 30, 10, 90000, path=dbpath)
        now = int(time.time())
        return await db.create_invoice(
            41, "renew", plan, 90000, path=dbpath, status="pending",
            panel_id=pid, panel_email="gone@x", sub_id="oldsub",
            expires_at=now + 10 * 86400)

    iid = run(_seed())
    panel = RenewPanel()
    monkeypatch.setattr(handlers_admin, "panel_client_for", lambda p: panel)
    monkeypatch.setattr(helpers, "panel_client_for", lambda p: panel)
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot)

    inv = run(db.get_invoice(iid, path=dbpath))
    res = run(handlers_admin.approve_invoice(ctx, inv, 999))

    assert "فعال شد" in res
    inv = run(db.get_invoice(iid, path=dbpath))
    assert inv["status"] == "active"
    assert inv["panel_email"] != "gone@x"  # fresh client, not the deleted one
    assert inv["panel_email"] in panel.added
    assert inv["sub_id"] != "oldsub"
    assert inv["volume_warned_at"] == 0  # orphan marker cleared on renewal
    # user got the delivery message with the new sub link
    assert any(uid == 41 for uid, _ in bot.sent)
