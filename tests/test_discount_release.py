"""Discount release (2026-11-18): a consumed code comes back when the
order it was spent on does not turn into a service.

- admin rejects the invoice -> counter back, user can reuse the code
- admin removes the service from the panel -> same release
- a rejected invoice without a code is a harmless no-op
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
import handlers_user as hu
import handlers_admin as ha
from panel import PanelError


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "discrel.db")
    run(db.init_db(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [999])
    pid = run(db.add_panel("سرور تست", "https://p.example:8443/x", "tok",
                           "https://p.example:2096/hard/", [1], path=p))
    plan_id = run(db.add_plan("۱۰ گیگ یک‌ماهه", 30, 10, 90000, path=p))
    run(db.add_card("6037991234567890", "Test", path=p))
    return {"path": p, "panel_id": pid, "plan_id": plan_id}


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None,
                           parse_mode=None):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, photo, caption=None):
        self.sent.append((chat_id, caption or ""))


class FakeMsg:
    def __init__(self, text="", user_id=111, photo=None):
        self.text = text
        self.photo = photo or []
        self.document = None
        self.from_user = SimpleNamespace(id=user_id, username="buyer")
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append((text, reply_markup))
        return None


class FakeQuery:
    def __init__(self, data="", user_id=999):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMsg(user_id=user_id)
        self.answered = []
        self.edited = []

    async def answer(self, text=None, show_alert=False):
        self.answered.append(text)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.edited.append(text)

    async def edit_message_caption(self, caption, reply_markup=None):
        self.edited.append(caption)


class GoodPanel:
    def __init__(self):
        self.clients = {}

    async def get_client(self, email):
        if email not in self.clients:
            raise PanelError("Obtain (record not found)", code="api")
        return self.clients[email]

    async def client_inbounds(self, email):
        return [1]

    async def add_client(self, inbound_ids, email, total_bytes, expiry_ms,
                         sub_id, tg_id=0, comment=""):
        self.clients[email] = {"email": email, "subId": sub_id,
                               "totalGB": total_bytes,
                               "expiryTime": expiry_ms, "enable": True}
        return {}

    async def attach(self, *a, **kw):
        return {}

    async def sub_links(self, sub_id):
        return ["vless://x@y:1"]

    async def fetch_sub_http(self, *a, **kw):
        return []

    async def links(self, email):
        return []

    async def traffic(self, email):
        return {"up": 0, "down": 0}

    async def set_enable(self, *a, **kw):
        return {}

    async def delete_client(self, email):
        self.clients.pop(email, None)
        return {}


def _patch_panel(monkeypatch, panel):
    import helpers
    for mod in (ha, helpers, hu):
        monkeypatch.setattr(mod, "panel_client_for", lambda p: panel)


def _mk(code="SAVE20", kind="percent", value=20, **kw):
    return run(db.create_discount_code(code, kind, value, **kw))


def _receipt_invoice(dbpath, uid=111, cid=None):
    """A pending card-buy invoice whose code was consumed at receipt."""
    st = {"k": "receipt", "plan_id": dbpath["plan_id"], "kind": "purchase",
          "panel_id": dbpath["panel_id"]}
    if cid is not None:
        st["discount"] = {"code": "SAVE20", "code_id": cid, "kind": "percent",
                          "value": 20, "final_price": 72000,
                          "plan_id": dbpath["plan_id"],
                          "panel_id": dbpath["panel_id"]}
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    msg = FakeMsg(user_id=uid, photo=[SimpleNamespace(file_id="photo1")])
    upd = SimpleNamespace(message=msg, callback_query=None,
                          effective_user=SimpleNamespace(id=uid))
    run(hu._handle_receipt(upd, ctx, st))
    invs = run(db.list_invoices(status="pending", kind="purchase"))
    assert len(invs) == 1
    return invs[0]


# ---------- admin reject ----------

def test_admin_reject_releases_code_and_user_can_reuse(dbpath, monkeypatch):
    cid = _mk("SAVE20", "percent", 20, limit_total=0, limit_per_user=1)
    inv = _receipt_invoice(dbpath, cid=cid)
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 1
    # the same code is now unusable for this user (per-user limit hit)
    ok, _, err, _ = run(db.validate_discount("SAVE20", 111, price=90000))
    assert err == "limit_per_user"

    q = FakeQuery(data=f"adm_pay_no:{inv['id']}", user_id=999)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    upd = SimpleNamespace(callback_query=q, message=None,
                          effective_user=SimpleNamespace(id=999))
    run(ha.on_pay_decision(upd, ctx))

    assert run(db.get_invoice(inv["id"]))["status"] == "rejected"
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 0
    # the user can use the same code again
    ok, _, err, final = run(db.validate_discount("SAVE20", 111, price=90000))
    assert ok and final == 72000


def test_admin_reject_without_code_is_noop(dbpath):
    inv = _receipt_invoice(dbpath)
    q = FakeQuery(data=f"adm_pay_no:{inv['id']}", user_id=999)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    upd = SimpleNamespace(callback_query=q, message=None,
                          effective_user=SimpleNamespace(id=999))
    run(ha.on_pay_decision(upd, ctx))
    assert run(db.get_invoice(inv["id"]))["status"] == "rejected"


# ---------- service removal ----------

def test_service_removal_releases_code(dbpath, monkeypatch):
    cid = _mk("SAVE20", "percent", 20, limit_total=0, limit_per_user=1)
    _patch_panel(monkeypatch, GoodPanel())
    # an active service bought with the code
    iid = run(db.create_invoice(111, "purchase", dbpath["plan_id"], 72000,
                                discount_code="SAVE20", price_before=90000))
    run(db.update_invoice(iid, status="active", panel_id=dbpath["panel_id"],
                          panel_email="buyer_1234",
                          sub_id="abcdef0123456789",
                          expires_at=int(time.time()) + 86400))
    assert run(db.consume_discount_code(cid, 111, iid)) is True
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 1

    q = FakeQuery(data=f"adm_users_del:{iid}", user_id=999)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    upd = SimpleNamespace(callback_query=q, message=None,
                          effective_user=SimpleNamespace(id=999))
    run(ha.user_service_action(upd, ctx))

    assert run(db.get_invoice(iid))["status"] == "expired"
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 0
    ok, _, err, _ = run(db.validate_discount("SAVE20", 111, price=90000))
    assert ok


def test_service_removal_without_code_is_noop(dbpath, monkeypatch):
    _patch_panel(monkeypatch, GoodPanel())
    iid = run(db.create_invoice(111, "purchase", dbpath["plan_id"], 90000))
    run(db.update_invoice(iid, status="active", panel_id=dbpath["panel_id"],
                          panel_email="buyer_1234",
                          sub_id="abcdef0123456789",
                          expires_at=int(time.time()) + 86400))
    q = FakeQuery(data=f"adm_users_del:{iid}", user_id=999)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    upd = SimpleNamespace(callback_query=q, message=None,
                          effective_user=SimpleNamespace(id=999))
    run(ha.user_service_action(upd, ctx))
    assert run(db.get_invoice(iid))["status"] == "expired"


# ---------- release helper ----------

def test_release_discount_for_invoice_noop_when_no_code(dbpath):
    iid = run(db.create_invoice(111, "purchase", dbpath["plan_id"], 90000))
    assert run(db.release_discount_for_invoice(iid)) is False
    assert run(db.release_discount_for_invoice(999999)) is False
