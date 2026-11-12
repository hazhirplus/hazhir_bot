"""Setup guide wizard (📖 آموزش راه‌اندازی).

The admin bottom menu gets a step-by-step first-setup wizard: panel
URL, API token, sub base, inbounds, bank card (+ holder), then an
automatic panel connection test. Every step can be skipped; answers
are saved as they come in, so leaving mid-way keeps the progress.
A card step is skipped when a card already exists.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import keyboards as K


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    """Empty DB (init only — no env seeding) unless a test seeds it."""
    p = str(tmp_path / "setup.db")
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
    def __init__(self, msg, data="", user_id=999):
        self.message = msg
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.answered = 0

    async def answer(self, *a, **kw):
        self.answered += 1

    async def edit_message_text(self, text, reply_markup=None,
                                parse_mode=None):
        return await self.message.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode)


class FakePanel:
    """Panel client that always answers the connection test."""

    def __init__(self, fa="✅ اتصال برقراره"):
        self.fa = fa

    async def test_connection(self):
        return {"ok": True, "fa": self.fa}


def _ctx(bot):
    return SimpleNamespace(bot=bot, user_data={})


def _text_update(text):
    msg = FakeMsg(text)
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_user=SimpleNamespace(id=999),
                           callback_query=None)


def _cb_update(data, msg=None):
    msg = msg or FakeMsg()
    q = FakeQuery(msg, data=data)
    return SimpleNamespace(callback_query=q, message=msg,
                           effective_message=msg,
                           effective_user=SimpleNamespace(id=999))


def _answer(ha, ctx, text):
    """Drive one wizard answer through the state machine."""
    upd = _text_update(text)
    run(ha.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    return upd


def test_guide_button_in_admin_menu():
    rows = K.admin_sections().keyboard
    flat = [b.text for row in rows for b in row]
    assert "📖 آموزش راه‌اندازی" in flat


def test_guide_home_checklist_empty(dbpath):
    import handlers_admin as ha

    upd = _text_update("📖 آموزش راه‌اندازی")
    ctx = _ctx(FakeBot())
    assert run(ha.admin_menu_text(upd, ctx)) is True
    text = upd.message.replies[-1][0]
    assert "آموزش راه‌اندازی" in text
    # nothing configured yet: every step unchecked
    assert text.count("⬜") == 6
    assert "✅" not in text
    kb = upd.message.replies[-1][1]
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "adm_setup_start" in cbs


def test_wizard_full_flow(dbpath, monkeypatch):
    import handlers_admin as ha

    monkeypatch.setattr(ha, "panel_client_for", lambda p: FakePanel())
    ctx = _ctx(FakeBot())
    ctx.user_data["st"] = {"k": "a_setup_name"}

    upd = _answer(ha, ctx, "سرور کانادا")
    assert ctx.user_data["st"]["k"] == "a_setup_url"
    assert "قدم ۲" in upd.message.replies[-1][0]

    upd = _answer(ha, ctx, "https://panel.example:8443/web")
    assert ctx.user_data["st"]["k"] == "a_setup_token"
    assert "قدم ۳" in upd.message.replies[-1][0]

    upd = _answer(ha, ctx, "tok123")
    assert ctx.user_data["st"]["k"] == "a_setup_sub"

    upd = _answer(ha, ctx, "https://panel.example:2096/hard/")
    assert ctx.user_data["st"]["k"] == "a_setup_inb"

    upd = _answer(ha, ctx, "1,9,11")
    assert ctx.user_data["st"]["k"] == "a_setup_card"
    panel = run(db.get_active_panel(path=dbpath))
    assert panel["name"] == "سرور کانادا"
    assert panel["url"] == "https://panel.example:8443/web"
    assert panel["token"] == "tok123"
    assert panel["sub_base"] == "https://panel.example:2096/hard"
    assert panel["inbounds"] == [1, 9, 11]

    upd = _answer(ha, ctx, "6037991122334455")
    assert ctx.user_data["st"]["k"] == "a_setup_holder"

    upd = _answer(ha, ctx, "شاهین")
    assert "st" not in ctx.user_data
    text = upd.message.replies[-1][0]
    assert "راه‌اندازی کامل شد" in text
    assert "✅ اتصال برقراره" in text
    assert "https://panel.example:8443/web" in text
    cards = run(db.list_cards(False, path=dbpath))
    assert len(cards) == 1
    assert cards[0]["number"] == "6037991122334455"
    assert cards[0]["holder"] == "شاهین"


def test_wizard_invalid_answers_reask(dbpath):
    import handlers_admin as ha

    ctx = _ctx(FakeBot())
    ctx.user_data["st"] = {"k": "a_setup_url"}
    upd = _answer(ha, ctx, "panel.example")
    assert "معتبر نیست" in upd.message.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_setup_url"

    ctx.user_data["st"] = {"k": "a_setup_inb", "url": "https://h:1",
                           "token": "t", "sub": "https://h:1/s"}
    upd = _answer(ha, ctx, "abc")
    assert "معتبر نیست" in upd.message.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_setup_inb"

    ctx.user_data["st"] = {"k": "a_setup_card"}
    upd = _answer(ha, ctx, "6037-xxxx")
    assert "فقط عدد" in upd.message.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_setup_card"


def test_wizard_skip_all(dbpath, monkeypatch):
    import handlers_admin as ha

    monkeypatch.setattr(ha, "panel_client_for", lambda p: FakePanel())
    ctx = _ctx(FakeBot())
    msg = FakeMsg()

    # start: first incomplete step is the name
    run(ha.on_admin_callback(_cb_update("adm_setup_start", msg), ctx))
    assert ctx.user_data["st"]["k"] == "a_setup_name"

    for step in ("name", "url", "token", "sub", "inb", "card"):
        run(ha.on_admin_callback(_cb_update(f"adm_setup_skip:{step}", msg),
                                 ctx))
    # skipping the card jumps straight to the test; no panel exists
    assert "st" not in ctx.user_data
    assert run(db.get_active_panel(path=dbpath)) is None
    # the finish edits the wizard message (callback path)
    assert "پنلی ثبت نشده" in msg.edits[-1][0]


def test_wizard_skip_holder_adds_card_without_name(dbpath, monkeypatch):
    import handlers_admin as ha

    monkeypatch.setattr(ha, "panel_client_for", lambda p: FakePanel())
    ctx = _ctx(FakeBot())
    ctx.user_data["st"] = {"k": "a_setup_holder",
                           "number": "6037991122334455"}
    msg = FakeMsg()
    run(ha.on_admin_callback(_cb_update("adm_setup_skip:holder", msg), ctx))
    assert "st" not in ctx.user_data
    cards = run(db.list_cards(False, path=dbpath))
    assert len(cards) == 1
    assert cards[0]["holder"] == "—"


def test_wizard_updates_existing_panel(dbpath, monkeypatch):
    import handlers_admin as ha

    run(db.seed_from_env(dbpath))
    monkeypatch.setattr(ha, "panel_client_for", lambda p: FakePanel())
    panels = run(db.list_panels(False, path=dbpath))
    assert len(panels) == 1  # env-seeded «پنل اصلی»
    ctx = _ctx(FakeBot())

    # start: the env-seeded default name («پنل اصلی») counts as unset,
    # so the wizard begins at the name step, then redoes the rest
    run(ha.on_admin_callback(
        _cb_update("adm_setup_start", FakeMsg()), ctx))
    assert ctx.user_data["st"]["k"] == "a_setup_name"

    _answer(ha, ctx, "سرور جدید")
    _answer(ha, ctx, "https://new.example:8443/panel")
    _answer(ha, ctx, "newtok")
    _answer(ha, ctx, "https://new.example:2096/hard/")
    _answer(ha, ctx, "2,3")
    # a card already exists (seeded) — the wizard jumps to the test
    assert "st" not in ctx.user_data
    panels = run(db.list_panels(False, path=dbpath))
    assert len(panels) == 1  # updated in place, not duplicated
    assert panels[0]["name"] == "سرور جدید"
    assert panels[0]["url"] == "https://new.example:8443/panel"
    assert panels[0]["token"] == "newtok"
    assert panels[0]["inbounds"] == [2, 3]


def test_wizard_exit_keeps_progress(dbpath):
    import handlers_admin as ha

    ctx = _ctx(FakeBot())
    ctx.user_data["st"] = {"k": "a_setup_token", "url": "https://h:1"}
    msg = FakeMsg()
    run(ha.on_admin_callback(_cb_update("adm_setup_exit", msg), ctx))
    assert "st" not in ctx.user_data
    # exit redraws the guide home (edits the wizard message)
    assert any("آموزش راه‌اندازی" in t for t, _ in msg.edits)
