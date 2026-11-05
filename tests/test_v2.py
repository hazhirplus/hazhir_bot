"""v2 tests: test-account once-per-user, tutorials CRUD, broadcast flow,
menu keyboards, renew-one routing. All DB tests use a temp sqlite file."""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import keyboards as K
import text as T
from telegram import InlineKeyboardMarkup


@pytest.fixture()
def dbpath(tmp_path):
    p = str(tmp_path / "v2.db")
    asyncio.get_event_loop().run_until_complete(_init(p))
    return p


async def _init(p):
    await db.init_db(p)
    await db.seed_from_env(p)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------- test-account once-per-user ----------
def test_user_had_test_only_counts_live_ones(dbpath):
    # active test -> True
    iid = run(db.create_invoice(111, "test", None, 0, path=dbpath))
    run(db.update_invoice(iid, path=dbpath, status="active"))
    assert run(db.user_had_test(111, dbpath)) is True
    # pending test -> True (blocks double-claim)
    iid2 = run(db.create_invoice(222, "test", None, 0, path=dbpath))
    assert run(db.user_had_test(222, dbpath)) is True
    # rejected/expired tests do NOT block
    run(db.update_invoice(iid2, path=dbpath, status="rejected"))
    assert run(db.user_had_test(222, dbpath)) is False
    # purchase invoices never count
    iid3 = run(db.create_invoice(333, "purchase", 1, 90000, path=dbpath))
    run(db.update_invoice(iid3, path=dbpath, status="active"))
    assert run(db.user_had_test(333, dbpath)) is False


def test_migrate_expire_stuck_tests(dbpath):
    iid = run(db.create_invoice(444, "test", None, 0, path=dbpath))  # pending
    iid2 = run(db.create_invoice(444, "purchase", 1, 90000, path=dbpath))  # pending
    n = run(db.migrate_expire_stuck_tests(dbpath))
    assert n == 1
    assert run(db.get_invoice(iid, dbpath))["status"] == "expired"
    assert run(db.get_invoice(iid2, dbpath))["status"] == "pending"
    assert run(db.user_had_test(444, dbpath)) is False


def test_count_pending_payments_excludes_tests(dbpath):
    run(db.create_invoice(555, "purchase", 1, 90000, path=dbpath))
    run(db.create_invoice(555, "test", None, 0, path=dbpath))
    assert run(db.count_pending_payments(dbpath)) == 1


def test_test_enabled_setting_default(dbpath):
    assert run(db.get_setting("test_enabled", "0", dbpath)) == "1"


# ---------- tutorials ----------
def test_tutorial_crud(dbpath):
    tid = run(db.add_tutorial("t1", "body1", "photoid", dbpath))
    t = run(db.get_tutorial(tid, dbpath))
    assert t["title"] == "t1" and t["body"] == "body1"
    assert t["photo_file_id"] == "photoid" and t["active"] == 1
    run(db.update_tutorial(tid, dbpath, title="t2"))
    assert run(db.get_tutorial(tid, dbpath))["title"] == "t2"
    run(db.update_tutorial(tid, dbpath, active=0))
    assert run(db.list_tutorials(True, dbpath)) == [
        x for x in run(db.list_tutorials(True, dbpath)) if x["id"] != tid
    ]
    assert len(run(db.list_tutorials(False, dbpath))) >= 1
    run(db.delete_tutorial(tid, dbpath))
    assert run(db.get_tutorial(tid, dbpath)) is None


def test_tutorial_seeds_present(dbpath):
    tuts = run(db.list_tutorials(True, dbpath))
    assert len(tuts) >= 3
    titles = " ".join(t["title"] for t in tuts)
    assert "اندروید" in titles and "آیفون" in titles and "ویندوز" in titles
    # bodies carry the {dl_*} placeholders for display-time substitution
    assert "{dl_android}" in tuts[0]["body"]


def test_tutorial_body_placeholder_render():
    body = T.TUTORIAL_SEEDS[0][1]
    rendered = body.replace("{dl_android}", "ANDROID_LINK")
    assert "ANDROID_LINK" in rendered and "{dl_android}" not in rendered


# ---------- keyboards ----------
def _all_callbacks(kb: InlineKeyboardMarkup):
    out = []
    for row in kb.inline_keyboard:
        for b in row:
            if b.callback_data:
                out.append(b.callback_data)
    return out


def test_admin_hub_structure():
    kb = K.admin_hub(3)
    cbs = _all_callbacks(kb)
    assert "adm_rep_home" in cbs and "adm_panel_home" in cbs
    assert "adm_inb_home" in cbs and "adm_plan_home" in cbs
    assert "adm_card_home" in cbs and "adm_users_home" in cbs
    assert "adm_tut_home" in cbs and "adm_bc_home" in cbs
    assert "adm_set_home" in cbs and "adm_tomain" in cbs
    # pending badge shows the count
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("(3)" in t for t in labels)
    kb0 = K.admin_hub(0)
    labels0 = [b.text for row in kb0.inline_keyboard for b in row]
    assert not any("(0)" in t for t in labels0)


def test_admin_callback_namespace_tidy():
    kb = K.admin_hub(1)
    for cb in _all_callbacks(kb):
        assert cb.startswith("adm_"), cb
    assert _all_callbacks(K.back_admin_kb()) == ["adm_home"]
    assert _all_callbacks(K.pay_decision_kb(7)) == ["adm_pay_ok:7", "adm_pay_no:7"]
    assert _all_callbacks(K.renew_one_kb(9)) == ["u:renewone:9"]
    assert _all_callbacks(K.quick_guide_kb()) == ["u:tuts"]
    assert _all_callbacks(K.tut_back_kb()) == ["u:tuts"]


def test_tutorials_kb():
    tuts = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]
    kb = K.tutorials_kb(tuts)
    cbs = _all_callbacks(kb)
    assert cbs == ["u:tut:1", "u:tut:2", "u:tutlinks"]


def test_main_menu_has_tutorials():
    labels = [b.text for row in K.main_menu().keyboard for b in row]
    assert "📚 آموزش اتصال" in labels


# ---------- broadcast flow (mocked bot) ----------
class _FakeBot:
    def __init__(self):
        self.copied = []

    async def copy_message(self, chat_id, from_chat_id, message_id):
        if chat_id == 999:  # simulate a blocked user
            raise RuntimeError("blocked")
        self.copied.append(chat_id)


class _FakeContext:
    def __init__(self):
        self.bot = _FakeBot()
        self.user_data = {}


@pytest.mark.asyncio
async def test_broadcast_loop_counts(tmp_path):
    p = str(tmp_path / "bc.db")
    await db.init_db(p)
    for tg in (101, 102, 999):
        await db.upsert_user(tg, None, p)
    users = await db.list_users(100000, p)
    assert len(users) == 3
    ctx = _FakeContext()
    ok = fail = 0
    for u in users:
        try:
            await ctx.bot.copy_message(chat_id=u["tg_id"], from_chat_id=1,
                                       message_id=5)
            ok += 1
        except Exception:
            fail += 1
    assert ok == 2 and fail == 1
    assert ctx.bot.copied == [101, 102]


# ---------- texts ----------
def test_welcome_mentions_brand_and_features():
    assert "هژیر وی پی ان" in T.WELCOME_DEFAULT
    assert "🎁" in T.WELCOME_DEFAULT and "📚" in T.WELCOME_DEFAULT


def test_quick_guide_present():
    assert "لینک اشتراک" in T.QUICK_GUIDE and "u:tuts" in _all_callbacks(
        K.quick_guide_kb())


# ---------- grant_test_account end-to-end (mocked panel + bot) ----------
from types import SimpleNamespace

from panel import PanelError


class _FakePanel:
    """In-memory stand-in for PanelClient."""

    def __init__(self):
        self.clients = {}

    async def add_client(self, inbound_ids, email, total_bytes, expiry_ms,
                         sub_id, tg_id=0, comment=""):
        if email in self.clients:
            raise PanelError("exists")
        self.clients[email] = {"email": email, "subId": sub_id}
        return {"success": True}

    async def get_client(self, email):
        return self.clients.get(email)

    async def traffic(self, email):
        return {"up": 0, "down": 0}

    async def sub_links(self, sub_id):
        return []

    async def links(self, email):
        return []

    async def fetch_sub_http(self, sub_base, sub_id):
        return []


class _FakeBot2:
    def __init__(self):
        self.sent = []
        self.photos = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, photo, **kw):
        self.photos.append(chat_id)


class _FakeCtx2:
    def __init__(self):
        self.bot = _FakeBot2()
        self.user_data = {}


@pytest.mark.asyncio
async def test_grant_test_account_e2e(monkeypatch, tmp_path):
    import handlers_user
    import helpers

    p = str(tmp_path / "g.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [])
    await db.add_panel("t", "http://127.0.0.1:1", "tok",
                       "http://127.0.0.1:1/sub", [1], p)
    await db.upsert_user(777001, "tester", p)
    fake = _FakePanel()
    monkeypatch.setattr(handlers_user, "panel_client_for",
                        lambda panel, verify=True: fake)
    monkeypatch.setattr(helpers, "panel_client_for",
                        lambda panel, verify=True: fake)

    ctx = _FakeCtx2()
    err = await handlers_user.grant_test_account(ctx, 777001)
    assert err is None, err
    invs = await db.user_invoices(777001, ("active",), p)
    assert len(invs) == 1 and invs[0]["kind"] == "test"
    assert invs[0]["panel_email"] in fake.clients
    assert ctx.bot.sent  # delivery message reached the user
    assert ctx.bot.photos  # QR sent

    # second attempt: blocked, no duplicate client on panel
    err2 = await handlers_user.grant_test_account(ctx, 777001)
    assert err2 == T.TEST_ALREADY
    assert len(fake.clients) == 1


@pytest.mark.asyncio
async def test_pay_decision_legacy_stuck_buttons(monkeypatch, tmp_path):
    """The reported bug: approve on a non-pending invoice left dead buttons."""
    import handlers_admin

    p = str(tmp_path / "pay.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [1])
    iid = await db.create_invoice(555, "purchase", 1, 90000)
    await db.update_invoice(iid, status="active")  # handled elsewhere already

    answered = []

    class _CQ:
        data = f"adm_pay_ok:{iid}"
        from_user = SimpleNamespace(id=1)
        edited_markup = "not-called"

        async def answer(self, text=None, show_alert=False):
            answered.append(text)

        async def edit_message_reply_markup(self, markup):
            _CQ.edited_markup = markup

    await handlers_admin.on_pay_decision(SimpleNamespace(callback_query=_CQ()),
                                         _FakeCtx2())
    assert T.PAYMENT_REVIEWED in answered
    assert _CQ.edited_markup is None  # dead buttons removed


# ---------- referral ----------
def test_referral_attribution_guards(dbpath):
    run(db.upsert_user(111, "referrer", dbpath))
    run(db.upsert_user(222, "newbie", dbpath))
    # success: first join attribution
    assert run(db.attribute_referral(222, 111, dbpath)) is True
    assert run(db.get_user(222, dbpath))["referred_by"] == 111
    assert run(db.count_referrals(111, dbpath)) == 1
    assert run(db.count_referral_gifts(111, dbpath)) == 0
    # first-join-only: second attribution is a no-op
    assert run(db.attribute_referral(222, 111, dbpath)) is False
    # self-referral rejected
    assert run(db.attribute_referral(111, 111, dbpath)) is False
    assert run(db.attribute_referral(111, 0, dbpath)) is False
    # unknown referrer rejected
    run(db.upsert_user(333, "x", dbpath))
    assert run(db.attribute_referral(333, 999, dbpath)) is False
    assert run(db.get_user(333, dbpath))["referred_by"] is None


def test_migration_adds_new_columns(dbpath):
    # simulate an OLD db: users table without the new columns
    import aiosqlite
    old = str(dbpath) + ".old"
    run(_old_schema(old))
    run(db.init_db(old))
    async def cols():
        async with aiosqlite.connect(old) as con:
            cur = await con.execute("PRAGMA table_info(users)")
            return {r[1] for r in await cur.fetchall()}
    got = run(cols())
    assert "referred_by" in got and "balance_toman" in got


async def _old_schema(p):
    import aiosqlite
    async with aiosqlite.connect(p) as con:
        await con.execute(
            "CREATE TABLE users(tg_id INTEGER PRIMARY KEY, username TEXT DEFAULT '',"
            " joined INTEGER NOT NULL DEFAULT 0)")
        await con.commit()


def test_wallet_balance_arithmetic(dbpath):
    assert run(db.get_balance(777, dbpath)) == 0
    assert run(db.add_balance(777, 250000, dbpath)) == 250000
    assert run(db.add_balance(777, -50000, dbpath)) == 200000
    assert run(db.get_balance(777, dbpath)) == 200000
    # username preserved through balance-only upserts
    run(db.upsert_user(777, "keepme", dbpath))
    run(db.add_balance(777, 1000, dbpath))
    assert run(db.get_user(777, dbpath))["username"] == "keepme"


def test_buy_kb_wallet_variant():
    kb = K.buy_kb(3, True, 50000)
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "u:walletbuy:3" in data and "u:buy:3" in data
    kb2 = K.buy_kb(3, False, 0)
    data2 = [b.callback_data for row in kb2.inline_keyboard for b in row]
    assert "u:walletbuy:3" not in data2 and "u:buy:3" in data2


def test_main_menu_has_wallet_and_referral_tidy():
    rows = K.main_menu().keyboard
    texts = [b.text for row in rows for b in row]
    assert "👜 کیف پول" in texts and "👥 دعوت دوستان" in texts
    assert all(len(row) <= 2 for row in rows)  # standing rule: max 2 per row


def test_admin_hub_still_tidy():
    kb = K.admin_hub(7)
    assert all(len(row) <= 2 for row in kb.inline_keyboard)


@pytest.mark.asyncio
async def test_topup_approve_credits_wallet(monkeypatch, tmp_path):
    import handlers_admin
    p = str(tmp_path / "topup.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    monkeypatch.setattr(config, "DB_PATH", p)
    ctx = _FakeCtx2()
    iid = await db.create_invoice(555, "topup", None, 250000, path=p)
    res = await handlers_admin.approve_invoice(ctx, await db.get_invoice(iid, p), 1)
    assert await db.get_balance(555, p) == 250000
    assert (await db.get_invoice(iid, p))["status"] == "active"
    assert "شارژ" in res
    assert any(m[0] == 555 for m in ctx.bot.sent)  # user notified


@pytest.mark.asyncio
async def test_referral_gift_first_purchase_only(monkeypatch, tmp_path):
    import handlers_user  # noqa: F401  (ensures handler import chain ok)
    import helpers
    p = str(tmp_path / "ref.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [])
    await db.add_panel("t", "https://x.example", "tok", "https://sub.example",
                       [1], path=p)
    fake = _FakePanel()
    monkeypatch.setattr(helpers, "panel_client_for", lambda panel: fake)
    await db.upsert_user(111, "referrer", p)
    await db.upsert_user(222, "newbie", p)
    assert await db.attribute_referral(222, 111, p)
    ctx = _FakeCtx2()

    # first paid purchase of 222 -> gift for 111
    iid = await db.create_invoice(222, "purchase", None, 90000, path=p)
    await db.update_invoice(iid, path=p, status="active")
    await helpers.maybe_grant_referral_gift(ctx, await db.get_invoice(iid, p))
    gifts = [g for g in await db.user_invoices(111, ("active",), p)
             if g["kind"] == "gift"]
    assert len(gifts) == 1
    assert gifts[0]["price_toman"] == 0
    assert await db.count_referral_gifts(111, p) == 1
    assert any(m[0] == 111 for m in ctx.bot.sent)  # referrer got delivery

    # repeat call on the same invoice -> no duplicate
    await helpers.maybe_grant_referral_gift(ctx, await db.get_invoice(iid, p))
    assert await db.count_referral_gifts(111, p) == 1

    # second purchase (not the first) -> no gift
    iid2 = await db.create_invoice(222, "purchase", None, 90000, path=p)
    await db.update_invoice(iid2, path=p, status="active")
    await helpers.maybe_grant_referral_gift(ctx, await db.get_invoice(iid2, p))
    assert await db.count_referral_gifts(111, p) == 1


@pytest.mark.asyncio
async def test_referral_gift_respects_toggle(monkeypatch, tmp_path):
    import helpers
    p = str(tmp_path / "ref2.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [])
    await db.add_panel("t", "https://x.example", "tok", "https://sub.example",
                       [1], path=p)
    fake = _FakePanel()
    monkeypatch.setattr(helpers, "panel_client_for", lambda panel: fake)
    await db.set_setting("ref_enabled", "0", path=p)
    await db.upsert_user(111, "referrer", p)
    await db.upsert_user(222, "newbie", p)
    assert await db.attribute_referral(222, 111, p)
    iid = await db.create_invoice(222, "purchase", None, 90000, path=p)
    await db.update_invoice(iid, path=p, status="active")
    await helpers.maybe_grant_referral_gift(_FakeCtx2(),
                                            await db.get_invoice(iid, p))
    assert await db.count_referral_gifts(111, p) == 0


# ---------- admin bottom-menu navigation (mirzabot-style) ----------
class _FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.username = "tester"


class _FakeMsg:
    def __init__(self, text, uid):
        self.text = text
        self.from_user = _FakeUser(uid)
        self.sent = []
        self.deleted = False

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return None

    async def delete(self):
        self.deleted = True


class _FakeUpdate:
    def __init__(self, text, uid):
        self.message = _FakeMsg(text, uid)
        self.callback_query = None

    @property
    def effective_user(self):
        return self.message.from_user

    @property
    def effective_message(self):
        return self.message


class _FakeCtx:
    def __init__(self):
        self.user_data = {}


def _labels(kb):
    return [[b.text for b in row] for row in kb.keyboard]


def test_main_menu_admin_button():
    import handlers_admin  # noqa: F401  (ensures no import cycle)
    admin_kb = K.main_menu(is_admin=True)
    user_kb = K.main_menu(is_admin=False)
    flat_admin = [b for row in _labels(admin_kb) for b in row]
    flat_user = [b for row in _labels(user_kb) for b in row]
    assert "🛠 مدیریت" in flat_admin
    assert "🛠 مدیریت" not in flat_user
    assert all(len(r) <= 2 for r in _labels(admin_kb))


def test_admin_sections_tidy():
    rows = _labels(K.admin_sections())
    assert all(len(r) <= 2 for r in rows)
    assert rows[-1] == ["🔙 منوی اصلی"]
    flat = [b for r in rows for b in r]
    assert len(flat) == 11  # 10 sections + back


def test_admin_menu_text_routing(dbpath, monkeypatch):
    import handlers_admin as HA
    monkeypatch.setattr(config, "DB_PATH", dbpath)
    # admin opens the hub
    upd = _FakeUpdate("🛠 مدیریت", 1)
    ctx = _FakeCtx()
    assert run(HA.admin_menu_text(upd, ctx)) is True
    assert upd.message.sent
    kb = upd.message.sent[-1][1]
    assert kb is not None and "📊 گزارش‌ها" in [b for r in _labels(kb) for b in r]
    # section via plain message (no callback) must not crash
    upd2 = _FakeUpdate("📊 گزارش‌ها", 1)
    assert run(HA.admin_menu_text(upd2, _FakeCtx())) is True
    assert upd2.message.sent
    # back to main
    upd3 = _FakeUpdate("🔙 منوی اصلی", 1)
    ctx3 = _FakeCtx()
    ctx3.user_data["st"] = {"k": "whatever"}
    assert run(HA.admin_menu_text(upd3, ctx3)) is True
    assert "st" not in ctx3.user_data
    flat = [b for r in _labels(upd3.message.sent[-1][1]) for b in r]
    assert "🛠 مدیریت" in flat
    # non-admin cannot open admin nav
    assert run(HA.admin_menu_text(_FakeUpdate("🛠 مدیریت", 999), _FakeCtx())) is False
    assert run(HA.admin_menu_text(_FakeUpdate("📊 گزارش‌ها", 999), _FakeCtx())) is False


# ---------- fractional GB regression (0.5 GB test account) ----------
def test_gb_to_bytes_fractional():
    from panel import gb_to_bytes
    assert gb_to_bytes(0.5) == 536870912
    assert gb_to_bytes("0.5") == 536870912
    assert gb_to_bytes(2) == 2 * 1024 ** 3
    assert gb_to_bytes(10) == 10 * 1024 ** 3


def test_fnum_parses_fractions():
    from handlers_admin import _fnum
    assert _fnum("0.5") == 0.5
    assert _fnum("۰.۵") == 0.5
    assert _fnum("0,5") == 0.5
    assert _fnum("2") == 2.0
    assert _fnum("abc") is None
    assert _fnum("") is None


def test_fmt_gb_num():
    assert T.fmt_gb_num(0.5) == "0.5"
    assert T.fmt_gb_num(2.0) == "2"
    assert T.fmt_gb_num("0.5") == "0.5"
    assert T.fmt_gb_num(10) == "10"


@pytest.mark.asyncio
async def test_grant_test_fractional_gb(monkeypatch, tmp_path):
    """Setting test_gb=0.5 must create a 0.5 GB (536870912 B) panel client."""
    import handlers_user
    import helpers

    p = str(tmp_path / "frac.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [])
    await db.set_setting("test_gb", "0.5", p)
    await db.set_setting("test_days", "1", p)
    await db.add_panel("t", "http://127.0.0.1:1", "tok",
                       "http://127.0.0.1:1/sub", [1], p)
    await db.upsert_user(777002, "fracuser", p)

    seen = {}

    class RecPanel(_FakePanel):
        async def add_client(self, inbound_ids, email, total_bytes,
                             expiry_ms, sub_id, tg_id=0, comment=""):
            seen["total_bytes"] = total_bytes
            return await super().add_client(
                inbound_ids, email, total_bytes, expiry_ms, sub_id,
                tg_id, comment)

    fake = RecPanel()
    monkeypatch.setattr(handlers_user, "panel_client_for",
                        lambda panel, verify=True: fake)
    monkeypatch.setattr(helpers, "panel_client_for",
                        lambda panel, verify=True: fake)
    ctx = _FakeCtx2()
    err = await handlers_user.grant_test_account(ctx, 777002)
    assert err is None, err
    assert seen.get("total_bytes") == 536870912
    # the user-facing text must show 0.5, not 2
    texts = [m[1] for m in ctx.bot.sent if isinstance(m[1], str)]
    assert any("0.5" in t for t in texts)
