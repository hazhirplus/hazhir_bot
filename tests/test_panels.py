"""Multi-panel: server names, per-panel sales cap, server picker at buy time.

- panels.sales_cap (NULL = unlimited), counted sales = delivered
  purchase invoices only (renewals extend a client, tests/gifts are free)
- buy flow: no sellable panel -> NO_PANELS; one -> plans directly;
  several -> server picker first, then plans for that server
- approve_invoice refuses a new client on a capped-out panel
- admin: rename panel, set cap; wizard asks the server name first
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
    p = str(tmp_path / "panels.db")
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
        self.replies = []  # (text, reply_markup)
        self.edits = []    # (text, reply_markup)

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


def _msg_update(text, user_id=111):
    msg = FakeMsg(text)
    return SimpleNamespace(message=msg, callback_query=None,
                            effective_user=SimpleNamespace(id=user_id))


def _seed_panel(name="سرور کانادا", cap=None, active=True, path=None):
    pid = run(db.add_panel(name, "https://p.example:8443/x", "tok",
                           "https://p.example:2096/hard/", [1], path=path))
    if cap is not None or not active:
        run(db.update_panel(pid, path=path,
                            **({"sales_cap": cap} if cap is not None else {}),
                            **({} if active else {"active": 0})))
    return pid


def _seed_plan(path=None):
    return run(db.add_plan("۱۰ گیگ یک‌ماهه", 30, 10, 90000, path=path))


def _seed_card(path=None):
    return run(db.add_card("6037991122334455", "شاهین", path=path))


def _invoice(panel_id, kind="purchase", status="active", path=None):
    iid = run(db.create_invoice(user_id=111, kind=kind, plan_id=1,
                                price_toman=90000, path=path))
    run(db.update_invoice(iid, path=path, panel_id=panel_id, status=status))
    return iid


# ---------------- schema / counting ----------------
def test_sales_cap_column_defaults_to_unlimited(dbpath):
    pid = run(db.add_panel("A", "https://a:1", "t", "", [1], path=dbpath))
    p = run(db.get_panel(pid, path=dbpath))
    assert p["sales_cap"] is None
    assert db.cap_of(p) is None
    assert run(db.panel_has_capacity(p, path=dbpath)) is True


def test_update_panel_sales_cap(dbpath):
    pid = _seed_panel(path=dbpath)
    run(db.update_panel(pid, path=dbpath, sales_cap=5))
    assert run(db.get_panel(pid, path=dbpath))["sales_cap"] == 5
    run(db.update_panel(pid, path=dbpath, sales_cap=None))
    assert run(db.get_panel(pid, path=dbpath))["sales_cap"] is None


def test_cap_of_treats_zero_and_negative_as_unlimited():
    assert db.cap_of({"sales_cap": 0}) is None
    assert db.cap_of({"sales_cap": -3}) is None
    assert db.cap_of({"sales_cap": "abc"}) is None
    assert db.cap_of({"sales_cap": 50}) == 50


def test_count_panel_sales_only_delivered_purchases(dbpath):
    pid = _seed_panel(path=dbpath)
    _seed_plan(path=dbpath)
    _invoice(pid, "purchase", "active", dbpath)
    _invoice(pid, "purchase", "expired", dbpath)
    _invoice(pid, "purchase", "pending", dbpath)
    _invoice(pid, "renew", "active", dbpath)
    _invoice(pid, "test", "active", dbpath)
    _invoice(pid, "gift", "active", dbpath)
    assert run(db.count_panel_sales(pid, path=dbpath)) == 2


def test_panel_capacity_and_available_list(dbpath):
    full = _seed_panel("پر", cap=1, path=dbpath)
    free = _seed_panel("خالی", cap=10, path=dbpath)
    open_ = _seed_panel("باز", path=dbpath)  # unlimited
    _seed_plan(path=dbpath)
    _invoice(full, "purchase", "active", dbpath)  # cap reached
    assert run(db.panel_has_capacity(
        run(db.get_panel(full, path=dbpath)), path=dbpath)) is False
    avail = run(db.list_available_panels(path=dbpath))
    assert [p["id"] for p in avail] == [free, open_]
    assert run(db.get_available_panel(path=dbpath))["id"] == free


def test_inactive_panel_is_not_available(dbpath):
    _seed_panel("خاموش", active=False, path=dbpath)
    assert run(db.list_available_panels(path=dbpath)) == []
    assert run(db.get_available_panel(path=dbpath)) is None


# ---------------- buy flow: server picker ----------------
def test_show_plans_no_panel(dbpath):
    import handlers_user as hu
    ctx = _ctx()
    upd = _msg_update("🛒 خرید سرویس")
    run(hu.show_plans(upd, ctx))
    # no plans seeded — NO_PLANS wins before the panel check
    assert T.NO_PLANS in upd.message.replies[-1][0]


def test_show_plans_no_sellable_panel(dbpath):
    import handlers_user as hu
    _seed_plan(path=dbpath)
    ctx = _ctx()
    upd = _msg_update("🛒 خرید سرویس")
    run(hu.show_plans(upd, ctx))
    assert T.NO_PANELS in upd.message.replies[-1][0]


def test_show_plans_single_panel_goes_straight_to_plans(dbpath):
    import handlers_user as hu
    pid = _seed_panel(path=dbpath)
    _seed_plan(path=dbpath)
    ctx = _ctx()
    upd = _msg_update("🛒 خرید سرویس")
    run(hu.show_plans(upd, ctx))
    assert ctx.user_data["panel_id"] == pid
    kb = upd.message.replies[-1][1]
    assert kb.inline_keyboard[0][0].callback_data == "u:plan:1"
    # no «back to servers» row with a single panel
    assert all(b.callback_data != "u:servers"
               for row in kb.inline_keyboard for b in row)


def test_show_plans_many_panels_shows_picker_first(dbpath):
    import handlers_user as hu
    _seed_panel("سرور کانادا", path=dbpath)
    _seed_panel("سرور امریکا", path=dbpath)
    _seed_plan(path=dbpath)
    ctx = _ctx()
    upd = _msg_update("🛒 خرید سرویس")
    run(hu.show_plans(upd, ctx))
    assert "panel_id" not in ctx.user_data
    text, kb = upd.message.replies[-1]
    assert T.PICK_SERVER in text
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "🌐 سرور کانادا" in labels and "🌐 سرور امریکا" in labels
    assert kb.inline_keyboard[0][0].callback_data.startswith("u:server:")


def test_server_picked_shows_plans_and_remembers(dbpath):
    import handlers_user as hu
    pid = _seed_panel("سرور کانادا", path=dbpath)
    _seed_panel("سرور امریکا", path=dbpath)
    _seed_plan(path=dbpath)
    ctx = _ctx()
    msg = FakeMsg()
    run(hu.server_picked(_cb_update(f"u:server:{pid}", msg), ctx))
    assert ctx.user_data["panel_id"] == pid
    text, kb = msg.edits[-1]
    assert "پلن انتخاب کن" in text
    assert kb.inline_keyboard[0][0].callback_data == "u:plan:1"
    # back row returns to the server picker
    assert any(b.callback_data == "u:servers"
               for row in kb.inline_keyboard for b in row)


def test_server_picked_full_panel_is_refused(dbpath):
    import handlers_user as hu
    pid = _seed_panel("پر", cap=1, path=dbpath)
    _seed_plan(path=dbpath)
    _invoice(pid, "purchase", "active", dbpath)
    ctx = _ctx()
    msg = FakeMsg()
    run(hu.server_picked(_cb_update(f"u:server:{pid}", msg), ctx))
    assert "panel_id" not in ctx.user_data
    assert T.PANEL_SOLD_OUT in msg.edits[-1][0]


def test_buy_start_carries_panel_into_receipt_state(dbpath):
    import handlers_user as hu
    pid = _seed_panel(path=dbpath)
    _seed_plan(path=dbpath)
    _seed_card(path=dbpath)
    ctx = _ctx()
    msg = FakeMsg()
    run(hu.buy_start(_cb_update("u:buy:1", msg), ctx))
    assert ctx.user_data["st"] == {"k": "receipt", "plan_id": 1,
                                   "kind": "purchase", "panel_id": pid}


def test_wallet_buy_invoice_gets_picked_panel(dbpath, monkeypatch):
    import handlers_user as hu
    import handlers_admin as ha
    pid = _seed_panel("سرور کانادا", path=dbpath)
    _seed_panel("سرور امریکا", path=dbpath)
    plan_id = _seed_plan(path=dbpath)
    run(db.add_balance(111, 200000, path=dbpath))

    async def fake_approve(context, inv, admin_id):
        await db.update_invoice(inv["id"], path=dbpath, status="active")
        return "✅ فعال شد."

    monkeypatch.setattr(ha, "approve_invoice", fake_approve)
    ctx = _ctx()
    ctx.user_data["panel_id"] = pid
    msg = FakeMsg()
    run(hu.wallet_buy(_cb_update(f"u:walletbuy:{plan_id}", msg), ctx))
    invs = run(db.user_invoices(111, ("active",), path=dbpath))
    assert len(invs) == 1
    assert invs[0]["panel_id"] == pid


def test_approve_invoice_refuses_capped_panel(dbpath):
    import handlers_admin as ha
    pid = _seed_panel("پر", cap=1, path=dbpath)
    _seed_plan(path=dbpath)
    _invoice(pid, "purchase", "active", dbpath)  # cap reached
    iid = _invoice(pid, "purchase", "pending", dbpath)
    inv = run(db.get_invoice(iid, path=dbpath))
    res = run(ha.approve_invoice(_ctx(), inv, 999))
    assert T.PANEL_CAP_FULL in res
    assert run(db.get_invoice(iid, path=dbpath))["status"] == "pending"


def test_approve_invoice_renew_ignores_cap(dbpath, monkeypatch):
    """A renewal extends an existing client — no new config, no cap."""
    import handlers_admin as ha
    pid = _seed_panel("پر", cap=1, path=dbpath)
    _seed_plan(path=dbpath)
    _invoice(pid, "purchase", "active", dbpath)  # cap reached
    iid = _invoice(pid, "renew", "pending", dbpath)
    run(db.update_invoice(iid, path=dbpath, panel_email="u_1234",
                          sub_id="abcd1234abcd1234"))
    inv = run(db.get_invoice(iid, path=dbpath))

    class FakePC:
        async def get_client(self, email):
            return {"email": email, "expiryTime": 9999999999000,
                    "totalGB": 10 * 1024 ** 3, "enable": True}

        async def update_client(self, email, fields):
            return {}

    monkeypatch.setattr(ha, "panel_client_for", lambda p: FakePC())
    res = run(ha.approve_invoice(_ctx(), inv, 999))
    assert "فعال شد" in res
    assert run(db.get_invoice(iid, path=dbpath))["status"] == "active"


# ---------------- admin: name + cap ----------------
def test_admin_rename_panel(dbpath):
    import handlers_admin as ha
    pid = _seed_panel("قدیمی", path=dbpath)
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_pname", "pid": pid}
    msg = FakeMsg("سرور آلمان")
    run(ha.handle_admin_state(
        SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=999)),
        ctx, ctx.user_data["st"]))
    assert run(db.get_panel(pid, path=dbpath))["name"] == "سرور آلمان"
    assert "st" not in ctx.user_data


def test_admin_set_cap_persian_digits_and_unlimited(dbpath):
    import handlers_admin as ha
    pid = _seed_panel(path=dbpath)
    ctx = _ctx()

    def _set(txt):
        ctx.user_data["st"] = {"k": "a_pcap", "pid": pid}
        msg = FakeMsg(txt)
        run(ha.handle_admin_state(
            SimpleNamespace(message=msg,
                            effective_user=SimpleNamespace(id=999)),
            ctx, ctx.user_data["st"]))
        return msg

    _set("۵۰")
    assert run(db.get_panel(pid, path=dbpath))["sales_cap"] == 50
    _set("0")
    assert run(db.get_panel(pid, path=dbpath))["sales_cap"] is None
    msg = _set("abc")
    assert "❌" in msg.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_pcap"  # re-ask, state kept


def test_wizard_name_step_carries_into_panel(dbpath):
    import handlers_admin as ha
    ctx = _ctx()
    st = {"k": "a_setup_name"}
    msg = FakeMsg("سرور کانادا")
    run(ha._setup_answer(
        SimpleNamespace(message=msg, callback_query=None,
                        effective_user=SimpleNamespace(id=999)),
        ctx, st, "name", "سرور کانادا"))
    assert ctx.user_data["st"]["k"] == "a_setup_url"
    assert ctx.user_data["st"]["name"] == "سرور کانادا"
    run(ha._setup_save_panel({"name": "سرور کانادا",
                              "url": "https://h:1", "token": "t",
                              "sub": "https://h:1/s"}, [1]))
    panels = run(db.list_panels(False, path=dbpath))
    assert len(panels) == 1
    assert panels[0]["name"] == "سرور کانادا"
