"""Panel sales-cap race (N1) + wallet auto-reject on failed approval (N6).

- N1: two simultaneous wallet purchases on the last cap slot must not
  both create clients — the cap check and the activation must be
  serialized per panel.
- N6: a wallet purchase whose approval fails (cap full / panel error)
  is refunded AND the invoice is auto-rejected, so it cannot sit in
  the admin queue where approving it later would hand out a free
  service for money already refunded.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import text as T


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    """Empty DB (init only — no env seeding) unless a test seeds it."""
    p = str(tmp_path / "caprace.db")
    run(db.init_db(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [999])
    return p


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None,
                           parse_mode=None):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, photo, caption=None):
        self.sent.append((chat_id, caption or ""))


class FakeMsg:
    def __init__(self, text=""):
        self.text = text
        self.replies = []
        self.edits = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append((text, reply_markup))
        return None

    async def edit_message_text(self, text, reply_markup=None,
                                parse_mode=None):
        self.edits.append((text, reply_markup))
        return None

    async def delete(self):
        return None


class FakeQuery:
    def __init__(self, msg, data="", user_id=111):
        self.message = msg
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.answered = 0

    async def answer(self, *a, **kw):
        self.answered += 1

    async def edit_message_text(self, text, reply_markup=None,
                                parse_mode=None):
        return await self.message.edit_message_text(text, reply_markup,
                                                    parse_mode=parse_mode)


def _ctx(bot=None):
    return SimpleNamespace(bot=bot or FakeBot(), user_data={})


def _cb_update(data, msg, user_id=111):
    upd = SimpleNamespace(callback_query=FakeQuery(msg, data, user_id),
                          message=None,
                          effective_user=SimpleNamespace(id=user_id))
    return upd


def _seed_panel(name="پر", cap=None, path=None):
    pid = run(db.add_panel(name, "https://p.example:8443/x", "tok",
                           "https://p.example:2096/hard/", [1], path=path))
    if cap is not None:
        run(db.update_panel(pid, path=path, sales_cap=cap))
    return pid


def _seed_plan(path=None):
    return run(db.add_plan("۱۰ گیگ یک‌ماهه", 30, 10, 90000, path=path))


def _invoice(user_id, panel_id, kind="purchase", status="pending", path=None):
    iid = run(db.create_invoice(user_id=user_id, kind=kind, plan_id=1,
                                price_toman=90000, path=path))
    run(db.update_invoice(iid, path=path, panel_id=panel_id, status=status))
    return iid


class SlowFakePC:
    """Panel client that yields inside add_client, so two concurrent
    approvals genuinely interleave between the cap check and activation."""

    def __init__(self):
        self.added = []

    async def get_client(self, email):
        return None

    async def add_client(self, inbounds, email, total_bytes, expiry_ms,
                         sub_id, tg_id=None, comment=None):
        await asyncio.sleep(0.05)
        self.added.append(email)
        return {}


# ---------------- N1: cap race ----------------
def test_concurrent_approvals_last_cap_slot_only_one_succeeds(dbpath,
                                                              monkeypatch):
    import handlers_admin as ha
    pid = _seed_panel(cap=1, path=dbpath)
    _seed_plan(path=dbpath)
    iid1 = _invoice(111, pid, path=dbpath)
    iid2 = _invoice(222, pid, path=dbpath)
    inv1 = run(db.get_invoice(iid1, path=dbpath))
    inv2 = run(db.get_invoice(iid2, path=dbpath))
    monkeypatch.setattr(ha, "panel_client_for", lambda p: SlowFakePC())

    async def _both():
        return await asyncio.gather(
            ha.approve_invoice(_ctx(), inv1, 999),
            ha.approve_invoice(_ctx(), inv2, 999),
        )

    res1, res2 = run(_both())
    ok = [r for r in (res1, res2) if "فعال شد" in r]
    capped = [r for r in (res1, res2) if T.PANEL_CAP_FULL in r]
    assert len(ok) == 1 and len(capped) == 1
    assert run(db.count_panel_sales(pid, path=dbpath)) == 1
    assert len(run(db.list_invoices(status="active", kind="purchase",
                                    path=dbpath))) == 1


def test_concurrent_wallet_buys_last_slot_one_active_one_refunded_rejected(
        dbpath, monkeypatch):
    """End-to-end N1+N6: two wallet buys race for the last slot — the
    loser is refunded in full and its invoice is auto-rejected."""
    import handlers_admin as ha
    import handlers_user as hu
    pid = _seed_panel(cap=1, path=dbpath)
    plan_id = _seed_plan(path=dbpath)
    run(db.add_balance(111, 200000, path=dbpath))
    run(db.add_balance(222, 200000, path=dbpath))
    monkeypatch.setattr(ha, "panel_client_for", lambda p: SlowFakePC())

    async def _both():
        return await asyncio.gather(
            hu.wallet_buy(_cb_update(f"u:walletbuy:{plan_id}", FakeMsg(), 111),
                          _ctx()),
            hu.wallet_buy(_cb_update(f"u:walletbuy:{plan_id}", FakeMsg(), 222),
                          _ctx()),
        )

    run(_both())
    actives = run(db.list_invoices(status="active", kind="purchase",
                                   path=dbpath))
    rejected = run(db.list_invoices(status="rejected", kind="purchase",
                                    path=dbpath))
    assert len(actives) == 1
    assert len(rejected) == 1
    winner = actives[0]["user_id"]
    loser = rejected[0]["user_id"]
    assert {winner, loser} == {111, 222}
    assert run(db.get_balance(winner, path=dbpath)) == 200000 - 90000
    assert run(db.get_balance(loser, path=dbpath)) == 200000
    assert run(db.count_panel_sales(pid, path=dbpath)) == 1


# ---------------- N6: auto-reject on failed wallet approval ----------------
def test_wallet_buy_failed_approval_refunds_and_rejects(dbpath, monkeypatch):
    import handlers_admin as ha
    import handlers_user as hu
    _seed_panel(path=dbpath)
    plan_id = _seed_plan(path=dbpath)
    run(db.add_balance(111, 200000, path=dbpath))

    async def fake_approve(context, inv, admin_id):
        return T.PANEL_CAP_FULL

    monkeypatch.setattr(ha, "approve_invoice", fake_approve)
    ctx = _ctx()
    msg = FakeMsg()
    run(hu.wallet_buy(_cb_update(f"u:walletbuy:{plan_id}", msg), ctx))
    rejected = run(db.list_invoices(status="rejected", kind="purchase",
                                    path=dbpath))
    assert len(rejected) == 1
    assert run(db.get_balance(111, path=dbpath)) == 200000
    assert "برگشت" in msg.edits[-1][0]


def test_wallet_renew_failed_approval_refunds_and_rejects(dbpath, monkeypatch):
    import handlers_admin as ha
    import handlers_user as hu
    pid = _seed_panel(path=dbpath)
    plan_id = _seed_plan(path=dbpath)
    target = _invoice(111, pid, status="active", path=dbpath)
    run(db.update_invoice(target, path=dbpath, panel_email="u_111",
                          sub_id="abcd1234abcd1234", expires_at=9999999999))
    run(db.add_balance(111, 200000, path=dbpath))

    async def fake_approve(context, inv, admin_id):
        return "⚠️ خطای پنل: connection failed"

    monkeypatch.setattr(ha, "approve_invoice", fake_approve)
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "renew_pay", "plan_id": plan_id,
                           "target_inv": target}
    msg = FakeMsg()
    run(hu.renew_pay_wallet(_cb_update("u:renewwallet", msg), ctx))
    rejected = run(db.list_invoices(status="rejected", kind="renew",
                                    path=dbpath))
    assert len(rejected) == 1
    assert run(db.get_balance(111, path=dbpath)) == 200000
