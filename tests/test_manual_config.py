"""Deleted-inbound resilience + manual config attach.

Bug 1 (reported 2026-11-07): the admin deleted inbound 9 from the
3x-ui panel; every new order then failed with "inbound 9 does not
exist" because create_panel_client sent ALL configured inbounds in
one /clients/add call and 3x-ui rejects the whole call when any id
is unknown. After the fix the client is created on the inbounds
that still exist, the missing ones are skipped and reported.

Feature 2 (same report): when panel creation fails, the admin can
paste a hand-built subscription link (+ the panel client email) from
the admin panel; the bot registers it on the invoice and delivers
it, so the customer is not stuck waiting — and renewals later extend
that same config (looked up by panel_email).

All DB tests use a temp sqlite file; the panel and the Telegram bot
are faked. handlers_admin is imported lazily inside the tests (see
test_orphan.py: test_crypto relies on import order).
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
from panel import PanelClient, PanelError, extract_sub_id

GB = 1024 ** 3


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "manual.db")
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


class FakeMsg:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append(text)
        return None


class MissingInboundPanel:
    """3x-ui behaviour: add/attach fails when any id is unknown."""

    def __init__(self, missing, ref_inbounds=None):
        self.missing = set(missing)
        self.add_calls = []
        self.attached = []
        self.clients = {}
        self.updated = []
        self.ref_inbounds = ref_inbounds or {}  # email -> [inbound ids]

    async def get_client(self, email):
        if email not in self.clients:
            raise PanelError("Obtain (record not found)", code="api")
        return self.clients[email]

    async def client_inbounds(self, email):
        if email not in self.ref_inbounds:
            raise PanelError("Obtain (record not found)", code="api")
        return list(self.ref_inbounds[email])

    async def add_client(self, inbound_ids, email, total_bytes, expiry_ms,
                         sub_id, tg_id=0, comment=""):
        self.add_calls.append(list(inbound_ids))
        if any(ib in self.missing for ib in inbound_ids):
            raise PanelError(
                f"inbound {sorted(set(inbound_ids) & self.missing)[0]} "
                "does not exist", code="api")
        self.clients[email] = {"email": email, "subId": sub_id,
                               "totalGB": total_bytes, "expiryTime": expiry_ms,
                               "enable": True}
        return {}

    async def attach(self, email, inbound_ids):
        self.attached.append((email, list(inbound_ids)))
        if any(ib in self.missing for ib in inbound_ids):
            raise PanelError("not found", code="notfound")
        return {}

    async def update_client(self, email, fields):
        self.updated.append((email, dict(fields)))
        if email not in self.clients:
            raise PanelError("Obtain (record not found)", code="api")
        self.clients[email].update(fields)
        return {}

    async def sub_links(self, sub_id):
        return []

    async def fetch_sub_http(self, base, sub_id):
        return []

    async def links(self, email):
        return []


def _seed_panel_plan(dbpath, inbounds=(1, 9, 11)):
    async def _seed():
        pid = await db.add_panel("p1", "http://127.0.0.1:1", "t",
                                 "http://127.0.0.1:1/", list(inbounds),
                                 path=dbpath)
        plan = await db.add_plan("10G", 30, 10, 90000, path=dbpath)
        return pid, plan

    return run(_seed())


# ---------- extract_sub_id ----------
def test_extract_sub_id():
    assert extract_sub_id(
        "https://host:2096/hard/abcdef0123456789") \
        == "abcdef0123456789"
    # case is preserved: the panel treats the id case-sensitively
    assert extract_sub_id(
        "https://host:2096/hard/ABCDEF0123456789/") == "ABCDEF0123456789"
    assert extract_sub_id("abcdef0123456789") == "abcdef0123456789"
    assert extract_sub_id(
        "https://host:2096/hard/abcdef0123456789?x=1") == "abcdef0123456789"
    # a client built by hand in 3x-ui gets a panel-generated id with
    # letters beyond a-f (and mixed case) — a real link, must be accepted
    assert extract_sub_id(
        "https://host:2096/hard/aB3xQ9gZ7kLmN2pR") == "aB3xQ9gZ7kLmN2pR"
    assert extract_sub_id("aB3xQ9gZ7kLmN2pR") == "aB3xQ9gZ7kLmN2pR"
    assert extract_sub_id(
        "https://host:2096/hard/550e8400-e29b-41d4-a716-446655440000") \
        == "550e8400-e29b-41d4-a716-446655440000"
    assert extract_sub_id(
        "vless://uuid@host:443?security=tls#name") is None
    assert extract_sub_id("not a link") is None
    assert extract_sub_id("") is None
    assert extract_sub_id("https://host/sub/short") is None
    assert extract_sub_id("abc123") is None  # too short to be an id


# ---------- resilient create_panel_client ----------
def test_create_panel_client_skips_missing_inbound(dbpath):
    pid, plan = _seed_panel_plan(dbpath)
    panel = MissingInboundPanel(missing={9})
    inv = {"user_id": 41}

    async def _go():
        p = await db.get_panel(pid, path=dbpath)
        return await helpers.create_panel_client(panel, p, inv, 30, 10,
                                                 int(time.time()))

    email, sub_id, skipped = run(_go())
    assert skipped == [9]
    assert email in panel.clients
    # first attempt tried everything, then per-inbound: 1 created it
    assert panel.add_calls[0] == [1, 9, 11]
    assert panel.add_calls[1] == [1]
    # the surviving inbounds were attached; the missing one was not fatal
    assert (email, [11]) in panel.attached
    assert len(sub_id) == 16


def test_create_panel_client_all_inbounds_missing_raises(dbpath):
    pid, _plan = _seed_panel_plan(dbpath)
    panel = MissingInboundPanel(missing={1, 9, 11})

    async def _go():
        p = await db.get_panel(pid, path=dbpath)
        return await helpers.create_panel_client(
            panel, p, {"user_id": 41}, 30, 10, int(time.time()))

    with pytest.raises(PanelError):
        run(_go())


# ---------- approve_invoice survives a deleted inbound ----------
def test_approve_invoice_skips_missing_inbound(dbpath, monkeypatch):
    import handlers_admin

    pid, plan = _seed_panel_plan(dbpath)
    iid = run(db.create_invoice(41, "purchase", plan, 90000, path=dbpath,
                                status="pending", panel_id=pid))
    panel = MissingInboundPanel(missing={9})
    monkeypatch.setattr(handlers_admin, "panel_client_for", lambda p: panel)
    monkeypatch.setattr(helpers, "panel_client_for", lambda p: panel)
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot)

    inv = run(db.get_invoice(iid, path=dbpath))
    res = run(handlers_admin.approve_invoice(ctx, inv, 999))

    assert "فعال شد" in res
    assert "9" in res  # the admin is told which inbound was skipped
    inv = run(db.get_invoice(iid, path=dbpath))
    assert inv["status"] == "active"
    assert inv["panel_email"] in panel.clients
    assert any(uid == 41 for uid, _ in bot.sent)  # customer got the link


# ---------- manual config attach ----------
def _manual_ctx(bot):
    return SimpleNamespace(bot=bot, user_data={})


def _manual_update(text):
    return SimpleNamespace(message=FakeMsg(text),
                           effective_user=SimpleNamespace(id=999))


def test_manual_attach_happy_path(dbpath, monkeypatch):
    import handlers_admin

    pid, plan = _seed_panel_plan(dbpath)
    iid = run(db.create_invoice(41, "purchase", plan, 90000, path=dbpath,
                                status="pending", panel_id=pid))
    panel = MissingInboundPanel(missing=set())
    panel.clients["shahin_1234"] = {"email": "shahin_1234",
                                    "subId": "abcdef0123456789"}
    monkeypatch.setattr(handlers_admin, "panel_client_for", lambda p: panel)
    monkeypatch.setattr(helpers, "panel_client_for", lambda p: panel)
    bot = FakeBot()
    ctx = _manual_ctx(bot)

    # step 1: paste the hand-built sub link
    ctx.user_data["st"] = {"k": "a_manual_sub", "iid": iid}
    run(handlers_admin.handle_admin_state(
        _manual_update("https://host:2096/hard/abcdef0123456789"),
        ctx, ctx.user_data["st"]))
    assert ctx.user_data["st"]["k"] == "a_manual_email"
    assert ctx.user_data["st"]["sub_id"] == "abcdef0123456789"

    # step 2: the panel client email
    upd = _manual_update("shahin_1234")
    run(handlers_admin.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "ثبت شد" in upd.message.replies[-1]
    assert "st" not in ctx.user_data

    inv = run(db.get_invoice(iid, path=dbpath))
    assert inv["status"] == "active"
    assert inv["panel_email"] == "shahin_1234"
    assert inv["sub_id"] == "abcdef0123456789"
    # the customer got the delivery with the manual sub link
    assert any(uid == 41 and "abcdef0123456789" in t
               for uid, t in bot.sent)


def test_manual_attach_bad_sublink_asks_again(dbpath):
    import handlers_admin

    pid, plan = _seed_panel_plan(dbpath)
    iid = run(db.create_invoice(41, "purchase", plan, 90000, path=dbpath,
                                status="pending", panel_id=pid))
    bot = FakeBot()
    ctx = _manual_ctx(bot)
    ctx.user_data["st"] = {"k": "a_manual_sub", "iid": iid}
    upd = _manual_update("vless://uuid@host:443#x")
    run(handlers_admin.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "معتبر نیست" in upd.message.replies[-1]
    assert ctx.user_data["st"]["k"] == "a_manual_sub"  # state kept
    assert run(db.get_invoice(iid, path=dbpath))["status"] == "pending"


def test_manual_attach_unknown_email_asks_again(dbpath, monkeypatch):
    import handlers_admin

    pid, plan = _seed_panel_plan(dbpath)
    iid = run(db.create_invoice(41, "purchase", plan, 90000, path=dbpath,
                                status="pending", panel_id=pid))
    panel = MissingInboundPanel(missing=set())  # no clients at all
    monkeypatch.setattr(handlers_admin, "panel_client_for", lambda p: panel)
    monkeypatch.setattr(helpers, "panel_client_for", lambda p: panel)
    bot = FakeBot()
    ctx = _manual_ctx(bot)
    ctx.user_data["st"] = {"k": "a_manual_email", "iid": iid,
                           "sub_id": "abcdef0123456789"}
    upd = _manual_update("nobody_0000")
    run(handlers_admin.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "پیدا نشد" in upd.message.replies[-1]
    assert ctx.user_data["st"]["k"] == "a_manual_email"  # state kept
    assert run(db.get_invoice(iid, path=dbpath))["status"] == "pending"


def test_renew_after_manual_attach_extends_same_client(dbpath, monkeypatch):
    """Renewal looks the client up by the registered panel_email."""
    import handlers_admin

    pid, plan = _seed_panel_plan(dbpath)
    panel = MissingInboundPanel(missing=set())
    panel.clients["shahin_1234"] = {"email": "shahin_1234",
                                    "subId": "abcdef0123456789",
                                    "totalGB": 10 * GB,
                                    "expiryTime": int(time.time() * 1000)}
    monkeypatch.setattr(handlers_admin, "panel_client_for", lambda p: panel)
    monkeypatch.setattr(helpers, "panel_client_for", lambda p: panel)
    bot = FakeBot()
    ctx = SimpleNamespace(bot=bot)

    now = int(time.time())
    iid = run(db.create_invoice(
        41, "renew", plan, 90000, path=dbpath, status="pending",
        panel_id=pid, panel_email="shahin_1234",
        sub_id="abcdef0123456789", expires_at=now + 5 * 86400))
    inv = run(db.get_invoice(iid, path=dbpath))
    res = run(handlers_admin.approve_invoice(ctx, inv, 999))

    assert "فعال شد" in res
    assert panel.updated  # update_client, not a fresh add_client
    assert panel.updated[0][0] == "shahin_1234"
    assert panel.add_calls == []  # no new client was created
    inv = run(db.get_invoice(iid, path=dbpath))
    assert inv["panel_email"] == "shahin_1234"
    assert inv["sub_id"] == "abcdef0123456789"


# ---------- reference client inbounds (mirzabot-style) ----------
def test_client_inbounds_parses_response(monkeypatch):
    pc = PanelClient("http://127.0.0.1:1", "t")

    async def _ok(self, method, path, **kw):
        assert path == "/clients/get/shahin_1234"
        return {"success": True,
                "obj": {"client": {"email": "shahin_1234"},
                        "inboundIds": [1, 11]}}

    monkeypatch.setattr(PanelClient, "_call", _ok)
    assert run(pc.client_inbounds("shahin_1234")) == [1, 11]

    async def _noids(self, method, path, **kw):
        return {"success": True, "obj": {"client": {"email": "x"}}}

    monkeypatch.setattr(PanelClient, "_call", _noids)
    assert run(pc.client_inbounds("x")) is None


def test_reference_inbounds_used_for_new_client(dbpath):
    pid, _plan = _seed_panel_plan(dbpath)  # stored [1, 9, 11]
    run(db.set_setting("ref_client_email", "shahin_1234", path=dbpath))
    panel = MissingInboundPanel(missing={9},
                                ref_inbounds={"shahin_1234": [1, 11]})

    async def _go():
        p = await db.get_panel(pid, path=dbpath)
        return await helpers.create_panel_client(
            panel, p, {"user_id": 41}, 30, 10, int(time.time()))

    email, _sub, skipped = run(_go())
    assert skipped == []
    # the reference's inbounds were used, not the stale stored list
    assert panel.add_calls[0] == [1, 11]
    assert email in panel.clients
    # the stored list was synced to the reference, so the admin screen
    # shows the truth
    assert run(db.get_panel(pid, path=dbpath))["inbounds"] == [1, 11]


def test_reference_unreadable_falls_back_to_stored(dbpath):
    pid, _plan = _seed_panel_plan(dbpath)
    run(db.set_setting("ref_client_email", "ghost_0000", path=dbpath))
    panel = MissingInboundPanel(missing={9})  # no ref client on the panel

    async def _go():
        p = await db.get_panel(pid, path=dbpath)
        return await helpers.create_panel_client(
            panel, p, {"user_id": 41}, 30, 10, int(time.time()))

    _email, _sub, skipped = run(_go())
    assert skipped == [9]  # stored list + per-inbound fallback saved it


def test_set_reference_from_inbounds_state(dbpath, monkeypatch):
    import handlers_admin

    pid, _plan = _seed_panel_plan(dbpath)
    panel = MissingInboundPanel(missing=set(),
                                ref_inbounds={"shahin_1234": [1, 11]})
    monkeypatch.setattr(handlers_admin, "panel_client_for", lambda p: panel)
    bot = FakeBot()
    ctx = _manual_ctx(bot)
    ctx.user_data["st"] = {"k": "a_inbref", "pid": pid}
    upd = _manual_update("shahin_1234")
    run(handlers_admin.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "مرجع ثبت شد" in upd.message.replies[-1]
    assert "st" not in ctx.user_data
    assert run(db.get_setting("ref_client_email", path=dbpath)) == "shahin_1234"
    assert run(db.get_panel(pid, path=dbpath))["inbounds"] == [1, 11]


def test_set_reference_unknown_client_asks_again(dbpath, monkeypatch):
    import handlers_admin

    pid, _plan = _seed_panel_plan(dbpath)
    panel = MissingInboundPanel(missing=set())
    monkeypatch.setattr(handlers_admin, "panel_client_for", lambda p: panel)
    bot = FakeBot()
    ctx = _manual_ctx(bot)
    ctx.user_data["st"] = {"k": "a_inbref", "pid": pid}
    upd = _manual_update("ghost_0000")
    run(handlers_admin.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "پیدا نشد" in upd.message.replies[-1]
    assert ctx.user_data["st"]["k"] == "a_inbref"  # state kept
    assert run(db.get_setting("ref_client_email", path=dbpath)) == ""


# ---------- manual send to any user ----------
def test_manual_send_to_user(dbpath, monkeypatch):
    import handlers_admin

    pid, plan = _seed_panel_plan(dbpath)
    panel = MissingInboundPanel(missing=set())
    panel.clients["friend_7777"] = {"email": "friend_7777",
                                    "subId": "abcdef0123456789"}
    monkeypatch.setattr(handlers_admin, "panel_client_for", lambda p: panel)
    monkeypatch.setattr(helpers, "panel_client_for", lambda p: panel)
    bot = FakeBot()
    ctx = _manual_ctx(bot)

    # plan already picked; step 1: paste the hand-built sub link
    ctx.user_data["st"] = {"k": "a_manual_sub", "tgid": 41, "plan_id": plan}
    run(handlers_admin.handle_admin_state(
        _manual_update("https://host:2096/hard/abcdef0123456789"),
        ctx, ctx.user_data["st"]))
    assert ctx.user_data["st"]["k"] == "a_manual_email"
    assert ctx.user_data["st"]["tgid"] == 41
    assert ctx.user_data["st"]["plan_id"] == plan

    # step 2: the panel client email
    upd = _manual_update("friend_7777")
    run(handlers_admin.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "ثبت شد" in upd.message.replies[-1]
    assert "st" not in ctx.user_data

    # a subscription invoice was created for that user, active
    invs = run(db.user_invoices(41, ("active",), path=dbpath))
    assert len(invs) == 1
    assert invs[0]["panel_email"] == "friend_7777"
    assert invs[0]["sub_id"] == "abcdef0123456789"
    assert invs[0]["plan_id"] == plan
    assert any(uid == 41 and "abcdef0123456789" in t
               for uid, t in bot.sent)


# ---------- ask_state: a Markdown failure must not kill the tap ----------
class MarkdownFailingMsg(FakeMsg):
    """Simulates Telegram rejecting Markdown (unclosed underscore)."""

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        if parse_mode == "Markdown":
            raise Exception("can't parse entities")
        self.replies.append(text)


class FakeQuery:
    def __init__(self, msg):
        self.message = msg
        self.answered = 0

    async def answer(self, *a, **kw):
        self.answered += 1


def test_ask_state_markdown_failure_falls_back_to_plain():
    import handlers_admin

    msg = MarkdownFailingMsg("x")
    q = FakeQuery(msg)
    upd = SimpleNamespace(callback_query=q, message=None,
                          effective_user=SimpleNamespace(id=999))
    ctx = SimpleNamespace(user_data={})
    run(handlers_admin.ask_state(upd, ctx, "a_inbref",
                                 "ایمیل (`shahin_1234`)؟", pid=1))
    assert msg.replies == ["ایمیل (`shahin_1234`)؟"]
    assert ctx.user_data["st"] == {"k": "a_inbref", "pid": 1}


def test_ask_state_total_failure_sets_no_state():
    import handlers_admin

    class DeadMsg(FakeMsg):
        async def reply_text(self, text, reply_markup=None, parse_mode=None):
            raise Exception("network down")

    msg = DeadMsg("x")
    q = FakeQuery(msg)
    upd = SimpleNamespace(callback_query=q, message=None,
                          effective_user=SimpleNamespace(id=999))
    ctx = SimpleNamespace(user_data={})
    with pytest.raises(Exception):
        run(handlers_admin.ask_state(upd, ctx, "a_inbref", "ایمیل؟", pid=1))
    assert "st" not in ctx.user_data  # no dangling wait-for-input state
