"""Discount admin section (2026-11-18): creation wizards (discount +
gift), list/detail/toggle/delete, and the who-can-create setting.

The wizard is the mirzabot order minus agent groups (none exist here):
code -> kind -> value -> limit_total -> limit_per_user -> first_only?
-> scope (buy/renew/all) -> panel -> plan -> expiry hours -> create.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import handlers_admin as ha


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "discadmin.db")
    run(db.init_db(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    # owner 999, second admin 111
    monkeypatch.setattr(config, "ADMIN_IDS", [999, 111])
    pid = run(db.add_panel("سرور تست", "https://p.example:8443/x", "tok",
                           "https://p.example:2096/hard/", [1], path=p))
    plan_id = run(db.add_plan("۱۰ گیگ یک‌ماهه", 30, 10, 90000, path=p))
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
    def __init__(self, text="", user_id=999):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id, username="admin")
        self.replies = []
        self.edits = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append((text, reply_markup))
        return None

    async def edit_message_text(self, text, reply_markup=None,
                                parse_mode=None):
        self.edits.append(text)


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
        self.edited.append((text, reply_markup))

    async def edit_message_caption(self, caption, reply_markup=None):
        self.edited.append((caption, reply_markup))


def _ctx(bot=None, user_data=None):
    return SimpleNamespace(bot=bot or FakeBot(),
                           user_data=user_data if user_data is not None else {})


def _cb(data, uid=999):
    q = FakeQuery(data, uid)
    return (SimpleNamespace(callback_query=q, message=None,
                            effective_user=SimpleNamespace(id=uid)), q)


def _text(txt, uid=999, ctx=None):
    msg = FakeMsg(txt, uid)
    upd = SimpleNamespace(message=msg, callback_query=None,
                          effective_user=SimpleNamespace(id=uid))
    return upd, msg, ctx


def _send_text(ctx, txt, uid=999):
    """Feed one admin text input through handle_admin_state."""
    upd, msg, _ = _text(txt, uid, ctx)
    run(ha.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    return msg


def _tap(ctx, data, uid=999):
    upd, q = _cb(data, uid)
    run(ha.on_admin_callback(upd, ctx))
    return q


def _run_wizard(ctx, code="SAVE20", kind="percent", value="20",
                limit_total="10", limit_user="", first="no",
                scope="all", panel="all", plan="all", expiry="0"):
    """Drive the discount wizard to creation; returns the created row."""
    _tap(ctx, "adm_disc_add")
    assert ctx.user_data["st"]["k"] == "a_disc_code"
    _send_text(ctx, code)
    assert ctx.user_data["st"]["k"] == "a_disc_kind"
    _tap(ctx, f"adm_disc_kind:{kind}")
    assert ctx.user_data["st"]["k"] == "a_disc_value"
    _send_text(ctx, value)
    assert ctx.user_data["st"]["k"] == "a_disc_limit_total"
    _send_text(ctx, limit_total)
    assert ctx.user_data["st"]["k"] == "a_disc_limit_user"
    _send_text(ctx, limit_user)
    assert ctx.user_data["st"]["k"] == "a_disc_first"
    _tap(ctx, f"adm_disc_first:{first}")
    if first == "no":
        assert ctx.user_data["st"]["k"] == "a_disc_scopekind"
        _tap(ctx, f"adm_disc_scopekind:{scope}")
    assert ctx.user_data["st"]["k"] == "a_disc_panel"
    _tap(ctx, f"adm_disc_panel:{panel}")
    assert ctx.user_data["st"]["k"] == "a_disc_plan"
    _tap(ctx, f"adm_disc_plan:{plan}")
    assert ctx.user_data["st"]["k"] == "a_disc_expiry"
    msg = _send_text(ctx, expiry)
    assert "st" not in ctx.user_data
    assert "ساخته شد" in msg.replies[-1][0]
    return run(db.get_discount_code(code))


# ---------- wizard happy paths ----------

def test_wizard_creates_percent_code(dbpath):
    ctx = _ctx()
    row = _run_wizard(ctx)
    assert row["code"] == "SAVE20"
    assert row["kind"] == "percent" and row["value"] == 20
    assert row["limit_total"] == 10 and row["limit_per_user"] == 1
    assert row["first_only"] == 0 and row["scope_kind"] == "all"
    assert row["scope_panel"] is None and row["scope_plan"] is None
    assert row["expires_at"] is None and row["active"] == 1


def test_wizard_creates_fixed_code_with_scopes_and_expiry(dbpath):
    ctx = _ctx()
    row = _run_wizard(ctx, code="FIX30", kind="fixed", value="30000",
                      limit_total="5", limit_user="2", first="no",
                      scope="renew", panel=str(dbpath["panel_id"]),
                      plan=str(dbpath["plan_id"]), expiry="48")
    assert row["kind"] == "fixed" and row["value"] == 30000
    assert row["limit_total"] == 5 and row["limit_per_user"] == 2
    assert row["scope_kind"] == "renew"
    assert row["scope_panel"] == dbpath["panel_id"]
    assert row["scope_plan"] == dbpath["plan_id"]
    assert row["expires_at"] is not None
    import time
    assert 47 * 3600 < row["expires_at"] - int(time.time()) <= 48 * 3600


def test_wizard_first_only_skips_scope_and_forces_buy(dbpath):
    ctx = _ctx()
    row = _run_wizard(ctx, code="FIRST1", first="yes")
    assert row["first_only"] == 1
    assert row["scope_kind"] == "buy"


def test_wizard_rejects_bad_code_and_bad_value(dbpath):
    ctx = _ctx()
    _tap(ctx, "adm_disc_add")
    msg = _send_text(ctx, "bad code!")
    assert "فقط حروف و عدد" in msg.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_disc_code"
    _send_text(ctx, "OK20")
    _tap(ctx, "adm_disc_kind:percent")
    msg = _send_text(ctx, "150")
    assert "۱ تا ۱۰۰" in msg.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_disc_value"
    msg = _send_text(ctx, "abc")
    assert "۱ تا ۱۰۰" in msg.replies[-1][0]


def test_wizard_rejects_duplicate_code(dbpath):
    run(db.create_discount_code("DUP1", "percent", 10))
    ctx = _ctx()
    _tap(ctx, "adm_disc_add")
    msg = _send_text(ctx, "dup1")
    assert "قبلاً ساخته شده" in msg.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_disc_code"


# ---------- gift wizard ----------

def test_gift_wizard_creates_code(dbpath):
    ctx = _ctx()
    _tap(ctx, "adm_disc_gift_add")
    assert ctx.user_data["st"]["k"] == "a_gift_code"
    _send_text(ctx, "GIFT50")
    assert ctx.user_data["st"]["k"] == "a_gift_amount"
    _send_text(ctx, "50000")
    assert ctx.user_data["st"]["k"] == "a_gift_limit"
    msg = _send_text(ctx, "0")
    assert "ساخته شد" in msg.replies[-1][0]
    row = run(db.get_gift_code("GIFT50"))
    assert row["amount"] == 50000 and row["limit_total"] == 0


def test_gift_wizard_rejects_bad_amount(dbpath):
    ctx = _ctx()
    _tap(ctx, "adm_disc_gift_add")
    _send_text(ctx, "G1")
    msg = _send_text(ctx, "0")
    assert "بیشتر از صفر" in msg.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_gift_amount"


# ---------- list / detail / toggle / delete ----------

def test_list_detail_toggle_delete(dbpath):
    cid = run(db.create_discount_code("SAVE20", "percent", 20))
    ctx = _ctx()
    q = _tap(ctx, "adm_disc_list")
    kb = q.edited[-1][1]  # _show edits the callback message
    assert any("SAVE20" in b.text for row in kb.inline_keyboard for b in row)
    q = _tap(ctx, f"adm_disc_view:{cid}")
    assert "SAVE20" in q.edited[-1][0]
    assert "۲۰٪" in q.edited[-1][0] or "20٪" in q.edited[-1][0]
    _tap(ctx, f"adm_disc_toggle:{cid}")
    assert run(db.get_discount_code_by_id(cid))["active"] == 0
    _tap(ctx, f"adm_disc_toggle:{cid}")
    assert run(db.get_discount_code_by_id(cid))["active"] == 1
    _tap(ctx, f"adm_disc_del:{cid}")
    assert run(db.get_discount_code_by_id(cid)) is None


def test_gift_list_detail_toggle_delete(dbpath):
    cid = run(db.create_gift_code("G1", 10000))
    ctx = _ctx()
    _tap(ctx, "adm_disc_gift_list")
    q = _tap(ctx, f"adm_gift_view:{cid}")
    assert "G1" in q.edited[-1][0]
    _tap(ctx, f"adm_gift_toggle:{cid}")
    assert run(db.get_gift_code_by_id(cid))["active"] == 0
    _tap(ctx, f"adm_gift_del:{cid}")
    assert run(db.get_gift_code_by_id(cid)) is None


# ---------- bottom-menu routing ----------

def test_bottom_menu_routes_to_discounts_section(dbpath):
    """The new admin bottom-menu button reaches discounts_menu."""
    ctx = _ctx()
    msg = FakeMsg("🎁 کدهای تخفیف", 999)
    upd = SimpleNamespace(message=msg, callback_query=None,
                          effective_message=msg,
                          effective_user=SimpleNamespace(id=999))
    assert run(ha.admin_menu_text(upd, ctx)) is True
    assert "کدهای تخفیف" in msg.replies[-1][0]


# ---------- who can create ----------

def test_non_owner_admin_cannot_start_wizard_by_default(dbpath):
    ctx = _ctx()
    q = _tap(ctx, "adm_disc_add", uid=111)
    assert "فقط برای مالکه" in (q.answered[-1] or "")
    assert "st" not in ctx.user_data


def test_owner_can_flip_who_can_create_and_admin_can_then_create(dbpath):
    ctx = _ctx()
    # owner-only toggle: non-owner is refused
    q = _tap(ctx, "adm_disc_who", uid=111)
    assert run(db.get_setting("discount_create_by", "owner")) == "owner"
    # owner flips it to admins
    _tap(ctx, "adm_disc_who", uid=999)
    assert run(db.get_setting("discount_create_by", "owner")) == "admins"
    # now the second admin can start the wizard
    q = _tap(ctx, "adm_disc_add", uid=111)
    assert ctx.user_data["st"]["k"] == "a_disc_code"
    # flip back
    _tap(ctx, "adm_disc_who", uid=999)
    assert run(db.get_setting("discount_create_by", "owner")) == "owner"


def test_discounts_menu_hides_create_buttons_for_non_creator(dbpath):
    ctx = _ctx()
    msg = FakeMsg()
    upd = SimpleNamespace(callback_query=None, message=msg,
                          effective_message=msg,
                          effective_user=SimpleNamespace(id=111))
    run(ha.discounts_menu(upd, ctx))
    sent = msg.replies[-1]
    labels = [b.text for row in sent[1].inline_keyboard for b in row]
    assert not any("ساخت کد تخفیف" in t for t in labels)
    assert not any("ساخت کد هدیه" in t for t in labels)
    assert any("لیست کدهای تخفیف" in t for t in labels)
    # owner sees the create buttons + the who toggle
    msg2 = FakeMsg()
    upd2 = SimpleNamespace(callback_query=None, message=msg2,
                           effective_message=msg2,
                           effective_user=SimpleNamespace(id=999))
    run(ha.discounts_menu(upd2, ctx))
    labels2 = [b.text for row in msg2.replies[-1][1].inline_keyboard
               for b in row]
    assert any("ساخت کد تخفیف" in t for t in labels2)
    assert any("ساخت کد:" in t for t in labels2)
