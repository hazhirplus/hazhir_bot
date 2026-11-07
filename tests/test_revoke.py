"""Admin-only sub-link rotation (revokeSub).

User decision 2026-11-06: customers must NOT rotate their own sub link;
only the admin does it from the user-service panel (adm_users_revoke).
Mechanism: 3x-ui updateClient with a fresh 16-hex subId (no dedicated
revoke endpoint; see REVIEW.md API cheat-sheet). The old link dies
immediately, so the new link is re-delivered to the customer at once.

⚠️ FRAGILITY (same as test_orphan.py): the crypto tests rely on
handlers_admin being lazily imported, so `handlers_admin` is imported
inside the test functions here, NOT at module level — importing it
at module level breaks 2 crypto tests (helpers.panel_client_for
patch stops taking effect).
"""
import asyncio
import os
import re
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import helpers
from panel import PanelClient, PanelError, gen_subid

GB = 1024 ** 3


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "revoke.db")
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


class FakePanel:
    """Records update_client calls; sub_links returns one dummy link."""

    def __init__(self, fail_update=None):
        self.updates = []  # (email, fields)
        self.fail_update = fail_update

    async def update_client(self, email, fields):
        if self.fail_update:
            raise self.fail_update
        self.updates.append((email, dict(fields)))
        return {"success": True}

    async def revoke_sub(self, email):
        # mirror of the real PanelClient.revoke_sub: fresh subId + update
        new_sub = gen_subid()
        await self.update_client(email, {"subId": new_sub})
        return new_sub

    async def sub_links(self, sub_id):
        return ["vless://u@h:443#x"]

    async def links(self, email):
        return []


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append(text)


class FakeQuery:
    def __init__(self, data, user_id=999):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answers = []  # (text, show_alert)

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def make_update(data, user_id=999):
    q = FakeQuery(data, user_id)
    upd = SimpleNamespace(callback_query=q,
                          effective_user=SimpleNamespace(id=user_id),
                          effective_message=q.message)
    return upd, q


# ---------- panel.revoke_sub ----------
def test_revoke_sub_rotates_subid():
    panel = FakePanel()
    # exercise the real PanelClient method with the transport stubbed
    client = PanelClient("http://127.0.0.1:1", "t")
    client.update_client = panel.update_client
    old = "aabbccddeeff0011"
    new = run(client.revoke_sub("u@x"))
    assert re.fullmatch(r"[0-9a-f]{16}", new)
    assert new != old
    assert panel.updates == [("u@x", {"subId": new})]


def test_gen_subid_format():
    assert re.fullmatch(r"[0-9a-f]{16}", gen_subid())


# ---------- admin handler: revoke updates DB + redelivers ----------
def _seed_invoice(dbpath):
    async def _seed():
        pid = await db.add_panel("p1", "http://127.0.0.1:1", "t",
                                 "http://127.0.0.1:1/", "[1]", path=dbpath)
        plan = await db.add_plan("10G", 30, 10, 90000, path=dbpath)
        now = int(time.time())
        return await db.create_invoice(
            42, "purchase", plan, 90000, path=dbpath, status="active",
            panel_id=pid, panel_email="u@x", sub_id="aabbccddeeff0011",
            expires_at=now + 30 * 86400)
    return run(_seed())


def test_admin_revoke_updates_db_and_redelivers(dbpath, monkeypatch):
    import handlers_admin  # lazy: see module docstring fragility note
    iid = _seed_invoice(dbpath)
    fake_panel = FakePanel()
    monkeypatch.setattr(handlers_admin, "panel_client_for",
                        lambda panel: fake_panel)
    monkeypatch.setattr(helpers, "panel_client_for", lambda panel: fake_panel)
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot, user_data={})
    upd, q = make_update(f"adm_users_revoke:{iid}")
    run(handlers_admin.user_service_action(upd, ctx))

    inv = run(db.get_invoice(iid, path=dbpath))
    assert re.fullmatch(r"[0-9a-f]{16}", inv["sub_id"])
    assert inv["sub_id"] != "aabbccddeeff0011"
    assert fake_panel.updates == [("u@x", {"subId": inv["sub_id"]})]
    # admin got the confirmation
    assert any("عوض شد" in t for t in q.message.replies)
    assert any("عوض شد" in (a[0] or "") for a in q.answers)
    # customer got the new link (deliver_service → send_message + QR photo)
    cust_msgs = [t for uid, t in bot.sent if uid == 42]
    assert cust_msgs, "customer was not notified"
    assert inv["sub_id"] in cust_msgs[0]


def test_admin_revoke_orphan_reports_not_found(dbpath, monkeypatch):
    import handlers_admin  # lazy: see module docstring fragility note
    iid = _seed_invoice(dbpath)
    fake_panel = FakePanel(
        fail_update=PanelError("Obtain (record not found)", code="api"))
    monkeypatch.setattr(handlers_admin, "panel_client_for",
                        lambda panel: fake_panel)
    monkeypatch.setattr(helpers, "panel_client_for", lambda panel: fake_panel)
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot, user_data={})
    upd, q = make_update(f"adm_users_revoke:{iid}")
    run(handlers_admin.user_service_action(upd, ctx))

    inv = run(db.get_invoice(iid, path=dbpath))
    assert inv["sub_id"] == "aabbccddeeff0011"  # unchanged
    assert bot.sent == []  # nobody told a wrong new link
    assert any("یافت نشد" in (a[0] or "") for a in q.answers)
