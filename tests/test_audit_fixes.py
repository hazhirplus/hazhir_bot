"""Audit fixes (2026-11-07): same bug classes as the two fixed today.

A. Wallet purchase/renewal refunded only when the invoice ended up
   "expired" — but approve_invoice leaves a panel-failed invoice
   "pending", so a wallet-paid order the panel rejected kept the
   user's money with no service and no refund.
B. collect_links: one link source raising an unexpected error aborted
   the whole delivery instead of falling through to the next source.
C. Markdown parse failures from free text (plan names, card holders,
   admin-written guides containing _ * [ ]) killed the tap silently:
   the buy/renew/topup screens, the crypto pay screen, the service
   card and the card detail all sent Markdown with no plain-text
   fallback, and the buy/renew/topup flows stored the wait-for-input
   state BEFORE the screen was delivered (dangling state).
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
import handlers_user
import handlers_admin
from panel import PanelError

GB = 1024 ** 3


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "audit.db")
    run(_init(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [999])
    return p


async def _init(p):
    await db.init_db(p)
    await db.seed_from_env(p)


class FakeBot:
    """send_message/send_photo that can simulate a Telegram Markdown
    parse failure (an underscore in the text)."""

    def __init__(self, fail_markdown=False):
        self.sent = []
        self.fail_markdown = fail_markdown

    async def send_message(self, chat_id, text, reply_markup=None,
                           parse_mode=None):
        if parse_mode == "Markdown" and self.fail_markdown:
            raise Exception("can't parse entities")
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, photo, caption=None):
        self.sent.append((chat_id, caption or ""))


class FakeMsg:
    def __init__(self, text="", fail_markdown=False, always_fail=False):
        self.text = text
        self.replies = []
        self.edits = []
        self.fail_markdown = fail_markdown
        self.always_fail = always_fail

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        if self.always_fail:
            raise Exception("network down")
        if parse_mode == "Markdown" and self.fail_markdown:
            raise Exception("can't parse entities")
        self.replies.append(text)

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        if self.always_fail:
            raise Exception("network down")
        if parse_mode == "Markdown" and self.fail_markdown:
            raise Exception("can't parse entities")
        self.edits.append(text)


class FakeQuery:
    def __init__(self, data="", user_id=111, fail_markdown=False,
                 always_fail=False):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMsg(fail_markdown=fail_markdown,
                               always_fail=always_fail)
        self.answered = []
        self.edited = []
        self.fail_markdown = fail_markdown
        self.always_fail = always_fail

    async def answer(self, text=None, show_alert=False):
        self.answered.append(text)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        if self.always_fail:
            raise Exception("network down")
        if parse_mode == "Markdown" and self.fail_markdown:
            raise Exception("can't parse entities")
        self.edited.append(text)


class FailingPanel:
    """Panel that rejects every client creation (e.g. all inbounds gone)."""

    def __init__(self):
        self.clients = {}

    async def get_client(self, email):
        if email not in self.clients:
            raise PanelError("Obtain (record not found)", code="api")
        return self.clients[email]

    async def client_inbounds(self, email):
        raise PanelError("Obtain (record not found)", code="api")

    async def add_client(self, *a, **kw):
        raise PanelError("inbound 9 does not exist", code="api")

    async def attach(self, *a, **kw):
        raise PanelError("inbound 9 does not exist", code="api")

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


class GoodPanel(FailingPanel):
    """Panel that accepts clients and serves links."""

    async def add_client(self, inbound_ids, email, total_bytes, expiry_ms,
                         sub_id, tg_id=0, comment=""):
        self.clients[email] = {"email": email, "subId": sub_id,
                               "totalGB": total_bytes,
                               "expiryTime": expiry_ms, "enable": True}
        return {}


def _patch_panel(monkeypatch, panel):
    for mod in (handlers_admin, helpers, handlers_user):
        monkeypatch.setattr(mod, "panel_client_for", lambda p: panel)


def _upd(q=None, msg=None, uid=111):
    return SimpleNamespace(callback_query=q, message=msg,
                          effective_user=SimpleNamespace(id=uid))


# ---------- A. wallet refund on panel failure ----------
def test_wallet_buy_panel_failure_refunds(dbpath, monkeypatch):
    uid = 111
    run(db.upsert_user(uid, "buyer"))
    plan = run(db.get_plan(1))  # seeded 10GB / 90000
    run(db.add_balance(uid, plan["price_toman"]))
    _patch_panel(monkeypatch, FailingPanel())
    q = FakeQuery(data=f"u:walletbuy:{plan['id']}", user_id=uid)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    run(handlers_user.wallet_buy(_upd(q=q, uid=uid), ctx))
    assert run(db.get_balance(uid)) == plan["price_toman"]  # refunded
    invs = run(db.user_invoices(uid, ("pending", "active", "expired")))
    assert invs and invs[0]["status"] != "active"
    assert any("برگشت" in t for t in q.edited)


def test_wallet_buy_success_no_refund(dbpath, monkeypatch):
    uid = 111
    run(db.upsert_user(uid, "buyer"))
    plan = run(db.get_plan(1))
    run(db.add_balance(uid, plan["price_toman"]))
    _patch_panel(monkeypatch, GoodPanel())
    q = FakeQuery(data=f"u:walletbuy:{plan['id']}", user_id=uid)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    run(handlers_user.wallet_buy(_upd(q=q, uid=uid), ctx))
    assert run(db.get_balance(uid)) == 0
    invs = run(db.user_invoices(uid, ("pending", "active", "expired")))
    assert invs and invs[0]["status"] == "active"
    assert any("فعال شد" in t for t in q.edited)


def test_wallet_renew_panel_failure_refunds(dbpath, monkeypatch):
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
    _patch_panel(monkeypatch, FailingPanel())
    q = FakeQuery(data="u:renewwallet", user_id=uid)
    ctx = SimpleNamespace(
        bot=FakeBot(),
        user_data={"st": {"k": "renew_pay", "target_inv": target,
                          "plan_id": plan["id"]}})
    run(handlers_user.renew_pay_wallet(_upd(q=q, uid=uid), ctx))
    assert run(db.get_balance(uid)) == plan["price_toman"]  # refunded
    assert any("برگشت" in t for t in q.edited)


# ---------- B. collect_links degrades per source ----------
def test_collect_links_survives_failing_source(monkeypatch):
    class Flaky:
        async def sub_links(self, sub_id):
            raise RuntimeError("boom")

        async def fetch_sub_http(self, base, sub_id):
            return ["vless://fallback@x:1"]

        async def links(self, email):
            raise RuntimeError("boom")

    monkeypatch.setattr(helpers, "panel_client_for", lambda p: Flaky())
    url, links = run(helpers.collect_links(
        {"sub_base": "https://h:2096/base"}, "abc12345", "u_1"))
    assert url == "https://h:2096/base/abc12345"
    assert links == ["vless://fallback@x:1"]


def test_collect_links_all_sources_fail(monkeypatch):
    class Dead:
        async def sub_links(self, sub_id):
            raise RuntimeError("boom")

        async def fetch_sub_http(self, *a):
            raise RuntimeError("boom")

        async def links(self, email):
            raise RuntimeError("boom")

    monkeypatch.setattr(helpers, "panel_client_for", lambda p: Dead())
    url, links = run(helpers.collect_links(
        {"sub_base": "https://h:2096/base"}, "abc12345", "u_1"))
    assert url == "https://h:2096/base/abc12345"
    assert links == []


# ---------- C. Markdown parse failures from free text ----------
def test_deliver_service_bad_guide_still_delivers(dbpath, monkeypatch):
    run(db.set_setting("delivery_guide", "پشتیبانی: @sahar_hoad"))
    _patch_panel(monkeypatch, GoodPanel())
    iid = run(db.create_invoice(111, "purchase", 1, 90000))
    run(db.update_invoice(iid, status="active", panel_id=1,
                          panel_email="buyer_1234",
                          sub_id="abcdef0123456789",
                          activated_at=int(time.time()),
                          expires_at=int(time.time()) + 86400))
    bot = FakeBot(fail_markdown=True)
    ctx = SimpleNamespace(bot=bot, user_data={})
    ok = run(helpers.deliver_service(ctx, run(db.get_invoice(iid))))
    assert ok is True
    assert bot.sent  # delivered via the plain-text fallback
    assert any("sahar_hoad" in t for _, t in bot.sent)


def test_buy_start_bad_plan_name_still_shows(dbpath):
    run(db.update_plan(1, name="۱۰ گیگ _ویژه_"))
    q = FakeQuery(data="u:buy:1", user_id=111, fail_markdown=True)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    run(handlers_user.buy_start(_upd(q=q), ctx))
    assert q.edited and "ویژه" in q.edited[0]
    assert ctx.user_data["st"] == {"k": "receipt", "plan_id": 1,
                                   "kind": "purchase"}


def test_buy_start_total_failure_sets_no_state(dbpath):
    q = FakeQuery(data="u:buy:1", user_id=111, always_fail=True)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    with pytest.raises(Exception):
        run(handlers_user.buy_start(_upd(q=q), ctx))
    assert "st" not in ctx.user_data  # no dangling wait-for-receipt state


def test_renew_payment_bad_guide_still_shows(dbpath):
    run(db.set_setting("buy_guide", "راهنما: @sahar_hoad"))
    plan = run(db.get_plan(1))
    inv = {"id": 7, "panel_id": 1, "panel_email": "buyer_1234",
           "sub_id": "abcdef0123456789", "expires_at": 0}
    q = FakeQuery(fail_markdown=True)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    run(handlers_user._start_renew_payment(q, ctx, inv, plan))
    assert q.edited and "sahar_hoad" in q.edited[0]
    assert ctx.user_data["st"]["k"] == "receipt"
    assert ctx.user_data["st"]["kind"] == "renew"


def test_topup_bad_holder_still_shows(dbpath):
    run(db.update_card(1, holder="SHAHIN_HIZHAA"))
    msg = FakeMsg(text="100000", fail_markdown=True)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    run(handlers_user._handle_state(_upd(msg=msg),
                                    ctx, {"k": "wallet_amount"}))
    assert msg.replies and "SHAHIN_HIZHAA" in msg.replies[0]
    assert ctx.user_data["st"] == {"k": "receipt", "kind": "topup",
                                   "plan_id": None, "amount": 100000}


def test_topup_total_failure_keeps_amount_state(dbpath):
    msg = FakeMsg(text="100000", always_fail=True)
    # production: main.py reads st from user_data and passes it in
    ctx = SimpleNamespace(bot=FakeBot(),
                          user_data={"st": {"k": "wallet_amount"}})
    with pytest.raises(Exception):
        run(handlers_user._handle_state(
            _upd(msg=msg), ctx, {"k": "wallet_amount"}))
    # still waiting for the amount, not stuck in receipt state
    assert ctx.user_data.get("st") == {"k": "wallet_amount"}


def test_crypto_pay_bad_plan_name_still_shows():
    plan = {"id": 1, "name": "۵۰ گیگ _ویژه_", "days": 30, "gb": 50,
            "price_toman": 490000}
    inv = {"id": 5, "crypto_chain": 8453, "crypto_currency": "ETH",
           "crypto_amount": "0.01", "crypto_address": "0xabc",
           "crypto_expires_at": int(time.time()) + 3600}
    q = FakeQuery(fail_markdown=True)
    run(handlers_user._show_crypto_pay(q, inv, plan))
    assert q.edited and "ویژه" in q.edited[0]


def test_service_card_bad_plan_name_still_shows(dbpath, monkeypatch):
    run(db.update_plan(1, name="۱۰ گیگ _ویژه_"))
    panel = GoodPanel()
    panel.clients["buyer_1234"] = {
        "email": "buyer_1234", "totalGB": 10 * GB,
        "expiryTime": (int(time.time()) + 86400) * 1000, "enable": True}
    _patch_panel(monkeypatch, panel)
    iid = run(db.create_invoice(111, "purchase", 1, 90000))
    run(db.update_invoice(iid, status="active", panel_id=1,
                          panel_email="buyer_1234",
                          sub_id="abcdef0123456789",
                          activated_at=int(time.time()),
                          expires_at=int(time.time()) + 86400))
    target = FakeMsg(fail_markdown=True)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    run(handlers_user.send_service_card(
        target, ctx, run(db.get_invoice(iid)), edit=False))
    assert target.replies and "ویژه" in target.replies[0]


def test_card_detail_bad_holder_still_shows(dbpath):
    run(db.update_card(1, holder="SHAHIN_HIZHAA"))
    q = FakeQuery(fail_markdown=True)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    run(handlers_admin.card_detail(_upd(q=q, uid=999), ctx, 1))
    assert q.edited and "SHAHIN_HIZHAA" in q.edited[0]
