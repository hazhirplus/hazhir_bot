"""Discount codes at the handler level (2026-11-18): code entry, card
buy, wallet buy, renew, gift redemption, and the refund+release path.

Follows the test_wallet_atomic.py fake style: fake env, fake panel,
fake Telegram objects — never a real token or panel.
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
import keyboards as K
from panel import PanelError


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    """Empty DB with one panel, one plan and one card — no env seeding."""
    p = str(tmp_path / "discbuy.db")
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
    def __init__(self, data="", user_id=111):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMsg(user_id=user_id)
        self.answered = []
        self.edited = []

    async def answer(self, text=None, show_alert=False):
        self.answered.append(text)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.edited.append((text, reply_markup))

    async def edit_message_caption(self, caption, reply_markup=None):
        self.edited.append((caption, reply_markup))


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

    async def update_client(self, email, fields):
        self.clients[email].update(fields)
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


def _upd_msg(msg, uid=111):
    return SimpleNamespace(message=msg, callback_query=None,
                          effective_user=SimpleNamespace(id=uid))


def _upd_q(q, uid=111):
    return SimpleNamespace(callback_query=q, message=None,
                          effective_user=SimpleNamespace(id=uid))


def _mk(code="SAVE20", kind="percent", value=20, **kw):
    return run(db.create_discount_code(code, kind, value, **kw))


# ---------- code entry ----------

def test_discount_entry_buy_applies_and_shows_final_price(dbpath, monkeypatch):
    _mk("SAVE20", "percent", 20)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={
        "st": {"k": "discount_buy", "plan_id": dbpath["plan_id"],
               "panel_id": dbpath["panel_id"]}})
    msg = FakeMsg(text=" save20 ")
    run(hu._handle_state(_upd_msg(msg), ctx,
                         ctx.user_data["st"]))
    st = ctx.user_data["st"]
    assert st["k"] == "discount_applied"
    assert st["discount"]["final_price"] == 72000
    assert st["discount"]["code"] == "SAVE20"
    assert "72,000" in msg.replies[-1][0]
    # crypto is hidden once a discount is applied
    kb = msg.replies[-1][1]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert not any("ارز دیجیتال" in t for t in labels)
    assert any("کارت‌به‌کارت" in t for t in labels)


def test_discount_entry_invalid_keeps_state_for_retry(dbpath):
    ctx = SimpleNamespace(bot=FakeBot(), user_data={
        "st": {"k": "discount_buy", "plan_id": dbpath["plan_id"],
               "panel_id": dbpath["panel_id"]}})
    msg = FakeMsg(text="NOPE")
    run(hu._handle_state(_upd_msg(msg), ctx, ctx.user_data["st"]))
    assert ctx.user_data["st"]["k"] == "discount_buy"
    assert "نامعتبر" in msg.replies[-1][0]


def test_discount_entry_expired_message(dbpath):
    _mk("OLD1", expires_at=int(time.time()) - 5)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={
        "st": {"k": "discount_buy", "plan_id": dbpath["plan_id"],
               "panel_id": dbpath["panel_id"]}})
    msg = FakeMsg(text="OLD1")
    run(hu._handle_state(_upd_msg(msg), ctx, ctx.user_data["st"]))
    assert "به پایان رسیده" in msg.replies[-1][0]


def test_discount_applied_text_is_ignored(dbpath):
    _mk("SAVE20")
    ctx = SimpleNamespace(bot=FakeBot(), user_data={
        "st": {"k": "discount_applied", "plan_id": dbpath["plan_id"],
               "discount": {"code": "SAVE20", "code_id": 1, "kind": "percent",
                            "value": 20, "final_price": 72000,
                            "plan_id": dbpath["plan_id"],
                            "panel_id": dbpath["panel_id"]}}})
    msg = FakeMsg(text="hello?")
    run(hu._handle_state(_upd_msg(msg), ctx, ctx.user_data["st"]))
    assert ctx.user_data["st"]["k"] == "discount_applied"
    assert "روش پرداخت" in msg.replies[-1][0]


def test_buy_kb_hides_crypto_and_discount_button_when_applied():
    kb = K.buy_kb(1, wallet_ok=True, balance=100000, crypto_ok=True,
                  discount_applied=True)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert not any("ارز دیجیتال" in t for t in labels)
    assert not any("کد تخفیف" in t for t in labels)
    kb2 = K.buy_kb(1, wallet_ok=True, balance=100000, crypto_ok=True)
    labels2 = [b.text for row in kb2.inline_keyboard for b in row]
    assert any("ارز دیجیتال" in t for t in labels2)
    assert any("کد تخفیف" in t for t in labels2)


# ---------- card buy with code ----------

def test_card_buy_with_code_creates_discounted_invoice(dbpath, monkeypatch):
    cid = _mk("SAVE20", "percent", 20)
    _patch_panel(monkeypatch, GoodPanel())
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    st = {"k": "receipt", "plan_id": dbpath["plan_id"], "kind": "purchase",
          "panel_id": dbpath["panel_id"],
          "discount": {"code": "SAVE20", "code_id": cid, "kind": "percent",
                       "value": 20, "final_price": 72000,
                       "plan_id": dbpath["plan_id"],
                       "panel_id": dbpath["panel_id"]}}
    msg = FakeMsg(user_id=111, photo=[SimpleNamespace(file_id="photo1")])
    run(hu._handle_receipt(_upd_msg(msg), ctx, st))
    invs = run(db.list_invoices(status="pending", kind="purchase"))
    assert len(invs) == 1
    inv = invs[0]
    assert inv["price_toman"] == 72000
    assert inv["discount_code"] == "SAVE20"
    assert inv["price_before"] == 90000
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 1
    # the admin notification carries the discount line
    assert any("SAVE20" in t for _, t in ctx.bot.sent)


def test_card_buy_code_expired_between_entry_and_receipt(dbpath):
    cid = _mk("SHORT1", "percent", 50, expires_at=int(time.time()) + 3600)
    # the code expires before the receipt arrives: rewrite expires_at
    # to the past via direct SQL
    async def _expire():
        import aiosqlite
        async with aiosqlite.connect(dbpath["path"]) as con:
            await con.execute(
                "UPDATE discount_codes SET expires_at=? WHERE id=?",
                (int(time.time()) - 5, cid))
            await con.commit()
    run(_expire())
    ctx = SimpleNamespace(bot=FakeBot(), user_data={})
    st = {"k": "receipt", "plan_id": dbpath["plan_id"], "kind": "purchase",
          "panel_id": dbpath["panel_id"],
          "discount": {"code": "SHORT1", "code_id": cid, "kind": "percent",
                       "value": 50, "final_price": 45000,
                       "plan_id": dbpath["plan_id"],
                       "panel_id": dbpath["panel_id"]}}
    msg = FakeMsg(user_id=111, photo=[SimpleNamespace(file_id="photo1")])
    run(hu._handle_receipt(_upd_msg(msg), ctx, st))
    # no invoice recorded; the user is told to resend without the code
    assert run(db.list_invoices(status="pending", kind="purchase")) == []
    assert "به پایان رسیده" in msg.replies[-1][0]
    assert "discount" not in ctx.user_data.get("st", {})


# ---------- wallet buy with code ----------

def test_wallet_buy_with_code_debits_discounted_price(dbpath, monkeypatch):
    _mk("SAVE20", "percent", 20)
    _patch_panel(monkeypatch, GoodPanel())
    run(db.add_balance(111, 72000))
    q = FakeQuery(data=f"u:walletbuy:{dbpath['plan_id']}", user_id=111)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={
        "st": {"k": "discount_applied", "plan_id": dbpath["plan_id"],
               "discount": {"code": "SAVE20", "code_id": 1, "kind": "percent",
                            "value": 20, "final_price": 72000,
                            "plan_id": dbpath["plan_id"],
                            "panel_id": dbpath["panel_id"]}}})
    run(hu.wallet_buy(_upd_q(q), ctx))
    assert run(db.get_balance(111)) == 0
    invs = run(db.user_invoices(111, ("active",)))
    assert len(invs) == 1
    assert invs[0]["price_toman"] == 72000
    assert invs[0]["discount_code"] == "SAVE20"
    assert invs[0]["price_before"] == 90000
    assert run(db.get_discount_code_by_id(1))["used_total"] == 1


def test_wallet_buy_failed_approval_refunds_and_releases_code(
        dbpath, monkeypatch):
    cid = _mk("SAVE20", "percent", 20)
    run(db.add_balance(111, 72000))

    async def fake_approve(context, inv, admin_id):
        return "⚠️ خطای پنل: connection failed"

    monkeypatch.setattr(ha, "approve_invoice", fake_approve)
    q = FakeQuery(data=f"u:walletbuy:{dbpath['plan_id']}", user_id=111)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={
        "st": {"k": "discount_applied", "plan_id": dbpath["plan_id"],
               "discount": {"code": "SAVE20", "code_id": cid, "kind": "percent",
                            "value": 20, "final_price": 72000,
                            "plan_id": dbpath["plan_id"],
                            "panel_id": dbpath["panel_id"]}}})
    run(hu.wallet_buy(_upd_q(q), ctx))
    assert run(db.get_balance(111)) == 72000  # refunded in full
    assert run(db.list_invoices(status="rejected", kind="purchase")) != []
    # the code is released: the user can use it again
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 0
    ok, _, err, _ = run(db.validate_discount("SAVE20", 111, price=90000))
    assert ok


def test_wallet_buy_fixed_code(dbpath, monkeypatch):
    _mk("FIX30", "fixed", 30000)
    _patch_panel(monkeypatch, GoodPanel())
    run(db.add_balance(111, 60000))
    q = FakeQuery(data=f"u:walletbuy:{dbpath['plan_id']}", user_id=111)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={
        "st": {"k": "discount_applied", "plan_id": dbpath["plan_id"],
               "discount": {"code": "FIX30", "code_id": 1, "kind": "fixed",
                            "value": 30000, "final_price": 60000,
                            "plan_id": dbpath["plan_id"],
                            "panel_id": dbpath["panel_id"]}}})
    run(hu.wallet_buy(_upd_q(q), ctx))
    assert run(db.get_balance(111)) == 0
    invs = run(db.user_invoices(111, ("active",)))
    assert invs[0]["price_toman"] == 60000


# ---------- renew with code ----------

def _active_target(dbpath, uid=111):
    iid = run(db.create_invoice(uid, "purchase", dbpath["plan_id"], 90000))
    run(db.update_invoice(iid, status="active", panel_id=dbpath["panel_id"],
                          panel_email="buyer_1234",
                          sub_id="abcdef0123456789",
                          expires_at=int(time.time()) + 86400))
    return iid


def test_renew_entry_rejects_buy_only_code(dbpath):
    _mk("BUYONLY", scope_kind="buy")
    target = _active_target(dbpath)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={
        "st": {"k": "discount_renew", "plan_id": dbpath["plan_id"],
               "target_inv": target, "panel_id": dbpath["panel_id"]}})
    msg = FakeMsg(text="BUYONLY")
    run(hu._handle_state(_upd_msg(msg), ctx, ctx.user_data["st"]))
    assert "فقط برای خرید" in msg.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "discount_renew"


def test_wallet_renew_with_code_debits_discounted_price(dbpath, monkeypatch):
    cid = _mk("REN10", "percent", 10, scope_kind="renew")
    _patch_panel(monkeypatch, GoodPanel())
    target = _active_target(dbpath)
    run(db.add_balance(111, 81000))
    q = FakeQuery(data="u:renewwallet", user_id=111)
    ctx = SimpleNamespace(bot=FakeBot(), user_data={
        "st": {"k": "renew_pay", "target_inv": target,
               "plan_id": dbpath["plan_id"],
               "discount": {"code": "REN10", "code_id": cid, "kind": "percent",
                            "value": 10, "final_price": 81000,
                            "plan_id": dbpath["plan_id"],
                            "panel_id": dbpath["panel_id"]}}})
    run(hu.renew_pay_wallet(_upd_q(q), ctx))
    assert run(db.get_balance(111)) == 0
    renews = run(db.user_invoices(111, ("active",)))
    ren = [i for i in renews if i["kind"] == "renew"]
    assert len(ren) == 1
    assert ren[0]["price_toman"] == 81000
    assert ren[0]["discount_code"] == "REN10"
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 1


# ---------- gift codes ----------

def test_gift_code_entry_credits_wallet(dbpath):
    run(db.create_gift_code("GIFT50", 50000))
    ctx = SimpleNamespace(bot=FakeBot(), user_data={"st": {"k": "gift_code"}})
    msg = FakeMsg(text=" gift50 ")
    run(hu._handle_state(_upd_msg(msg), ctx, ctx.user_data["st"]))
    assert run(db.get_balance(111)) == 50000
    assert "st" not in ctx.user_data
    assert "50,000" in msg.replies[-1][0]


def test_gift_code_second_use_rejected(dbpath):
    run(db.create_gift_code("ONCE1", 10000))
    ctx = SimpleNamespace(bot=FakeBot(), user_data={"st": {"k": "gift_code"}})
    run(hu._handle_state(_upd_msg(FakeMsg(text="ONCE1")), ctx,
                         ctx.user_data["st"]))
    assert run(db.get_balance(111)) == 10000
    ctx2 = SimpleNamespace(bot=FakeBot(), user_data={"st": {"k": "gift_code"}})
    msg2 = FakeMsg(text="ONCE1")
    run(hu._handle_state(_upd_msg(msg2), ctx2, ctx2.user_data["st"]))
    assert "قبلاً گرفتی" in msg2.replies[-1][0]
    assert run(db.get_balance(111)) == 10000  # credited only once
