"""Panel URL / sub-base validation (N5).

Every admin path that accepts a panel URL or a sub base must accept
only https:// — plain http:// would leak the panel API token (sent in
the Authorization header) and the service links on the wire.

Paths covered: setup wizard (url + sub steps), add-panel flow
(a_padd_url + a_padd_sub), edit panel (a_purl + a_psub), settings
(a_setkey with key "sub_base"). The DB layer itself stays
unvalidated — add_panel/update_panel are also used internally.
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
    p = str(tmp_path / "urlval.db")
    run(db.init_db(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [999])
    return p


class FakeMsg:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append((text, reply_markup))
        return None


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None,
                           parse_mode=None):
        self.sent.append((chat_id, text))


def _ctx():
    return SimpleNamespace(bot=FakeBot(), user_data={})


def _text_update(text):
    msg = FakeMsg(text)
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_user=SimpleNamespace(id=999),
                           callback_query=None)


def _seed_panel(path):
    return run(db.add_panel("پنل اصلی", "https://p.example:8443/x",
                            "tok", "https://p.example:2096/hard", [1],
                            path=path))


# ---------------- the validator itself ----------------
def test_https_url():
    assert ha._https_url("https://p.example:8443/x/") == \
        "https://p.example:8443/x"
    assert ha._https_url("  https://p.example:2096/hard  ") == \
        "https://p.example:2096/hard"
    assert ha._https_url("http://p.example:8443/x") is None
    assert ha._https_url("https://") is None
    assert ha._https_url("") is None
    assert ha._https_url("p.example:8443/x") is None
    assert ha._https_url("ftp://p.example/x") is None


# ---------------- setup wizard ----------------
def test_wizard_url_rejects_http(dbpath):
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_setup_url"}
    upd = _text_update("http://p.example:8443/x")
    run(ha._setup_answer(upd, ctx, ctx.user_data["st"], "url",
                         "http://p.example:8443/x"))
    assert "https://" in upd.message.replies[-1][0]
    assert "url" not in ctx.user_data["st"]  # step not advanced


def test_wizard_url_accepts_https(dbpath):
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_setup_url"}
    upd = _text_update("https://p.example:8443/x/")
    run(ha._setup_answer(upd, ctx, ctx.user_data["st"], "url",
                         "https://p.example:8443/x/"))
    assert ctx.user_data["st"].get("url") == "https://p.example:8443/x"


def test_wizard_sub_rejects_http(dbpath):
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_setup_sub", "url": "https://p.example:1",
                           "token": "tok"}
    upd = _text_update("http://p.example:2096/hard")
    run(ha._setup_answer(upd, ctx, ctx.user_data["st"], "sub",
                         "http://p.example:2096/hard"))
    assert "https://" in upd.message.replies[-1][0]
    assert "sub" not in ctx.user_data["st"]


# ---------------- add-panel flow ----------------
def test_add_panel_url_rejects_http(dbpath):
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_padd_url", "name": "پنل ۲"}
    upd = _text_update("http://p.example:8443/x")
    run(ha.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "https://" in upd.message.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_padd_url"  # still waiting


def test_add_panel_sub_rejects_http(dbpath):
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_padd_sub", "name": "پنل ۲",
                           "url": "https://p.example:8443/x",
                           "token": "tok"}
    upd = _text_update("http://p.example:2096/hard")
    run(ha.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "https://" in upd.message.replies[-1][0]
    assert ctx.user_data["st"]["k"] == "a_padd_sub"


# ---------------- edit panel ----------------
def test_edit_panel_url_rejects_http(dbpath):
    pid = _seed_panel(dbpath)
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_purl", "pid": pid}
    upd = _text_update("http://evil.example/x")
    run(ha.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "https://" in upd.message.replies[-1][0]
    assert run(db.get_panel(pid, path=dbpath))["url"] == \
        "https://p.example:8443/x"  # unchanged


def test_edit_panel_url_accepts_https(dbpath):
    pid = _seed_panel(dbpath)
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_purl", "pid": pid}
    upd = _text_update("https://new.example:8443/x/")
    run(ha.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert run(db.get_panel(pid, path=dbpath))["url"] == \
        "https://new.example:8443/x"


def test_edit_panel_sub_rejects_http(dbpath):
    pid = _seed_panel(dbpath)
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_psub", "pid": pid}
    upd = _text_update("http://evil.example/hard")
    run(ha.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "https://" in upd.message.replies[-1][0]
    assert run(db.get_panel(pid, path=dbpath))["sub_base"] == \
        "https://p.example:2096/hard"  # unchanged


# ---------------- settings (a_setkey sub_base) ----------------
def test_setkey_sub_base_rejects_http(dbpath):
    _seed_panel(dbpath)
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_setkey", "key": "sub_base"}
    upd = _text_update("http://evil.example/hard")
    run(ha.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    assert "https://" in upd.message.replies[-1][0]
    p = run(db.get_active_panel(path=dbpath))
    assert p["sub_base"] == "https://p.example:2096/hard"  # unchanged


def test_setkey_sub_base_accepts_https(dbpath):
    _seed_panel(dbpath)
    ctx = _ctx()
    ctx.user_data["st"] = {"k": "a_setkey", "key": "sub_base"}
    upd = _text_update("https://new.example:2096/hard/")
    run(ha.handle_admin_state(upd, ctx, ctx.user_data["st"]))
    p = run(db.get_active_panel(path=dbpath))
    assert p["sub_base"] == "https://new.example:2096/hard"
