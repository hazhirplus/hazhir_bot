"""Discount race conditions (2026-11-18): atomic consume.

The consume is one BEGIN IMMEDIATE transaction (total + per-user
limits re-checked inside), so two simultaneous consumes of the last
use cannot both win — same pattern as db.debit_balance's single
conditional UPDATE for the wallet double-spend.
"""
import asyncio
import os
import sys
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
    p = str(tmp_path / "discrace.db")
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


class FakeQuery:
    def __init__(self, data="", user_id=111):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(reply_text=self._noop_reply)
        self.answered = []
        self.edited = []

    async def _noop_reply(self, *a, **kw):
        return None

    async def answer(self, text=None, show_alert=False):
        self.answered.append(text)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.edited.append(text)


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


def _patch_panel(monkeypatch, panel):
    import helpers
    for mod in (ha, helpers, hu):
        monkeypatch.setattr(mod, "panel_client_for", lambda p: panel)


def test_concurrent_consumes_of_last_use_only_one_wins(dbpath):
    """Two simultaneous consumes of a 1-use code: exactly one wins."""
    cid = run(db.create_discount_code("LAST1", "percent", 20, limit_total=1))

    async def _two():
        return await asyncio.gather(
            db.consume_discount_code(cid, 111, 1001),
            db.consume_discount_code(cid, 222, 1002))

    results = run(_two())
    assert sorted(results) == [False, True]
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 1
    assert run(db.count_discount_uses(cid)) == 1


def test_concurrent_consumes_same_user_per_user_limit(dbpath):
    """Two simultaneous consumes by the SAME user against a
    limit_per_user=1 code: exactly one wins (the per-user check is
    inside the same transaction as the counter)."""
    cid = run(db.create_discount_code("MINE1", "percent", 20,
                                      limit_total=0, limit_per_user=1))

    async def _two():
        return await asyncio.gather(
            db.consume_discount_code(cid, 111, 1001),
            db.consume_discount_code(cid, 111, 1002))

    results = run(_two())
    assert sorted(results) == [False, True]
    assert run(db.count_discount_uses(cid, 111)) == 1


def test_concurrent_gift_redeems_of_last_use_only_one_wins(dbpath):
    """Two simultaneous redeems of a 1-use gift code: one credit only."""
    run(db.create_gift_code("GIFTLAST", 50000, limit_total=1))

    async def _two():
        return await asyncio.gather(
            db.redeem_gift_code("GIFTLAST", 111),
            db.redeem_gift_code("GIFTLAST", 222))

    results = run(_two())
    oks = [r[0] for r in results]
    assert sorted(oks) == [False, True]
    winner = 111 if results[0][0] else 222
    loser = 222 if winner == 111 else 111
    assert run(db.get_balance(winner)) == 50000
    assert run(db.get_balance(loser)) == 0


def test_double_wallet_buy_tap_with_code_only_one_succeeds(dbpath, monkeypatch):
    """Two rapid wallet-buy taps with a code, balance covering exactly
    one discounted price: one service, no double spend, code used once."""
    cid = run(db.create_discount_code("SAVE20", "percent", 20))
    _patch_panel(monkeypatch, GoodPanel())
    run(db.add_balance(111, 72000))

    async def _two_taps():
        q1 = FakeQuery(data=f"u:walletbuy:{dbpath['plan_id']}", user_id=111)
        q2 = FakeQuery(data=f"u:walletbuy:{dbpath['plan_id']}", user_id=111)
        st = {"k": "discount_applied", "plan_id": dbpath["plan_id"],
              "discount": {"code": "SAVE20", "code_id": cid, "kind": "percent",
                           "value": 20, "final_price": 72000,
                           "plan_id": dbpath["plan_id"],
                           "panel_id": dbpath["panel_id"]}}
        ctx1 = SimpleNamespace(bot=FakeBot(), user_data={"st": dict(st)})
        ctx2 = SimpleNamespace(bot=FakeBot(), user_data={"st": dict(st)})
        await asyncio.gather(
            hu.wallet_buy(SimpleNamespace(callback_query=q1, message=None,
                                          effective_user=SimpleNamespace(id=111)),
                          ctx1),
            hu.wallet_buy(SimpleNamespace(callback_query=q2, message=None,
                                          effective_user=SimpleNamespace(id=111)),
                          ctx2))
        return q1, q2

    q1, q2 = run(_two_taps())
    assert run(db.get_balance(111)) == 0  # spent once, never negative
    invs = run(db.user_invoices(111, ("pending", "active", "expired")))
    assert sum(1 for i in invs if i["status"] == "active") == 1
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 1
    assert any("موجودی کیف پول کافی نیست" in (a or "")
               for a in q1.answered + q2.answered)
