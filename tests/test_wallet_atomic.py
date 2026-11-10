"""Wallet double-spend (vibe-check check 32, 2026-11-10).

The old flow checked the balance and debited it in two separate steps
(get_balance, then add_balance(-price)), so two rapid taps could both pass
the check and spend the same balance twice — negative balance, two services
for the price of one. The fix is db.debit_balance: one conditional UPDATE
that checks and debits atomically. These tests pin that behaviour at the db
level and at the handler level (two concurrent taps).
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
import handlers_user
import handlers_admin
from panel import PanelError


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "atomic.db")
    run(_init(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [999])
    return p


async def _init(p):
    await db.init_db(p)
    await db.seed_from_env(p)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None,
                           parse_mode=None):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, photo, caption=None):
        self.sent.append((chat_id, caption or ""))


class FakeQuery:
    def __init__(self, data="", user_id=111):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.answered = []
        self.edited = []

    async def answer(self, text=None, show_alert=False):
        self.answered.append(text)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.edited.append(text)


class GoodPanel:
    """Panel that accepts clients and serves links."""

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


def _patch_panel(monkeypatch, panel):
    import helpers
    for mod in (handlers_admin, helpers, handlers_user):
        monkeypatch.setattr(mod, "panel_client_for", lambda p: panel)


def _upd(q=None, uid=111):
    return SimpleNamespace(callback_query=q,
                          effective_user=SimpleNamespace(id=uid))


# ---------- db.debit_balance ----------

def test_debit_succeeds_when_covered(dbpath):
    uid = 111
    run(db.upsert_user(uid, "buyer"))
    run(db.add_balance(uid, 250000))
    assert run(db.debit_balance(uid, 90000)) is True
    assert run(db.get_balance(uid)) == 160000


def test_debit_fails_when_short(dbpath):
    uid = 111
    run(db.upsert_user(uid, "buyer"))
    run(db.add_balance(uid, 50000))
    assert run(db.debit_balance(uid, 90000)) is False
    assert run(db.get_balance(uid)) == 50000  # unchanged


def test_debit_fails_for_unknown_user(dbpath):
    assert run(db.debit_balance(999999, 90000)) is False


def test_concurrent_debits_only_one_wins(dbpath):
    """Two simultaneous 90k debits against a 100k balance: exactly one wins."""
    uid = 111
    run(db.upsert_user(uid, "buyer"))
    run(db.add_balance(uid, 100000))

    async def _two():
        return await asyncio.gather(
            db.debit_balance(uid, 90000),
            db.debit_balance(uid, 90000))

    results = run(_two())
    assert sorted(results) == [False, True]
    assert run(db.get_balance(uid)) == 10000  # never negative


# ---------- handler level: double-tap ----------

def test_wallet_buy_double_tap_only_one_succeeds(dbpath, monkeypatch):
    uid = 111
    run(db.upsert_user(uid, "buyer"))
    plan = run(db.get_plan(1))  # seeded 10GB / 90000
    run(db.add_balance(uid, plan["price_toman"]))
    _patch_panel(monkeypatch, GoodPanel())

    async def _two_taps():
        q1 = FakeQuery(data=f"u:walletbuy:{plan['id']}", user_id=uid)
        q2 = FakeQuery(data=f"u:walletbuy:{plan['id']}", user_id=uid)
        ctx1 = SimpleNamespace(bot=FakeBot(), user_data={})
        ctx2 = SimpleNamespace(bot=FakeBot(), user_data={})
        await asyncio.gather(
            handlers_user.wallet_buy(_upd(q=q1, uid=uid), ctx1),
            handlers_user.wallet_buy(_upd(q=q2, uid=uid), ctx2))
        return q1, q2

    q1, q2 = run(_two_taps())
    assert run(db.get_balance(uid)) == 0  # spent once, never negative
    invs = run(db.user_invoices(uid, ("pending", "active", "expired")))
    assert sum(1 for i in invs if i["status"] == "active") == 1
    assert any("موجودی کیف پول کافی نیست" in (a or "")
               for a in q1.answered + q2.answered)


def test_wallet_renew_double_tap_only_one_succeeds(dbpath, monkeypatch):
    uid = 111
    run(db.upsert_user(uid, "buyer"))
    plan = run(db.get_plan(3))  # seeded 50GB / 490000
    target = run(db.create_invoice(uid, "purchase", plan["id"],
                                   plan["price_toman"]))
    run(db.update_invoice(target, status="active", panel_id=1,
                          panel_email="buyer_1234",
                          sub_id="abcdef0123456789",
                          expires_at=int(time.time()) + 86400))
    run(db.add_balance(uid, plan["price_toman"]))
    _patch_panel(monkeypatch, GoodPanel())

    async def _two_taps():
        st = {"k": "renew_pay", "target_inv": target,
              "plan_id": plan["id"]}
        q1 = FakeQuery(data="u:renewwallet", user_id=uid)
        q2 = FakeQuery(data="u:renewwallet", user_id=uid)
        ctx1 = SimpleNamespace(bot=FakeBot(), user_data={"st": dict(st)})
        ctx2 = SimpleNamespace(bot=FakeBot(), user_data={"st": dict(st)})
        await asyncio.gather(
            handlers_user.renew_pay_wallet(_upd(q=q1, uid=uid), ctx1),
            handlers_user.renew_pay_wallet(_upd(q=q2, uid=uid), ctx2))
        return q1, q2

    q1, q2 = run(_two_taps())
    assert run(db.get_balance(uid)) == 0  # spent once, never negative
    invs = run(db.user_invoices(uid, ("pending", "active", "expired")))
    renews = [i for i in invs if i["kind"] == "renew"
              and i["status"] == "active"]
    assert len(renews) == 1
    assert any("موجودی کیف پول کافی نیست" in (a or "")
               for a in q1.answered + q2.answered)
