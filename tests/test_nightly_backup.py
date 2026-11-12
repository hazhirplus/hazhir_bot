"""Nightly DB backup for the VPN bot (user request 2026-11-12):

Every night at 00:00 Tehran the bot sends the database file to the admins
inside the bot itself, so a dead server or a server move doesn't mean
re-entering everything from zero. A manual backup button + an auto-backup
toggle live in the admin settings menu.

Expected behaviour after the fix:
- Scheduling: job_queue.run_daily at 00:00 Asia/Tehran (no manual UTC math).
- Catch-up: a missed night (or first run) sends at startup; if last night
  or tonight was already sent, no duplicate.
- Only the hozhir-YYYY-MM-DD.db file is ever sent — never env/config.
- Caption carries Tehran date/time + user/invoice/active counts + restore hint.
- The two settings-menu buttons exist only for admins; the toggle flips
  auto_backup_enabled and the manual button works even when auto is off.
- Failures (network/token/unreadable file) return 0/False, never crash.

Run: .venv/bin/python -m pytest tests/test_nightly_backup.py -q
"""
import asyncio
import datetime
import os
import sqlite3
import sys
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backup
import config
import db
import handlers_admin
import jobs


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "vpn.db")
    asyncio.get_event_loop().run_until_complete(db.init_db(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [999])
    return p


async def _seed(p):
    now = int(time.time())
    async with aiosqlite.connect(p) as con:
        await con.execute(
            "INSERT INTO users(tg_id, username, joined) VALUES(111, 'u1', ?)", (now,))
        await con.execute(
            "INSERT INTO users(tg_id, username, joined) VALUES(222, 'u2', ?)", (now,))
        await con.execute(
            "INSERT INTO users(tg_id, username, joined) VALUES(333, 'u3', ?)", (now,))
        await con.execute(
            "INSERT INTO invoices(user_id, kind, price_toman, status, created_at)"
            " VALUES(111, 'purchase', 90000, 'active', ?)", (now,))
        await con.execute(
            "INSERT INTO invoices(user_id, kind, price_toman, status, created_at)"
            " VALUES(222, 'purchase', 270000, 'pending', ?)", (now,))
        await con.commit()


class FakeBot:
    def __init__(self):
        self.docs = []  # (chat_id, filename, caption, data)
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None,
                           parse_mode=None):
        self.sent.append((chat_id, text))

    async def send_document(self, chat_id, doc, filename=None, caption=None):
        data = doc.read()
        self.docs.append((chat_id, filename, caption, data))
        return True


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


class FakeJobQueue:
    def __init__(self):
        self.daily = []
        self.repeating = []
        self.once = []

    def run_daily(self, cb, time, name=None, **kw):
        self.daily.append({"cb": cb, "time": time, "name": name})

    def run_repeating(self, cb, interval, first=None, name=None, **kw):
        self.repeating.append({"cb": cb, "name": name})

    def run_once(self, cb, when, data=None, name=None, **kw):
        self.once.append({"cb": cb, "when": when, "data": data,
                          "name": name})


def _kb_callbacks(markup):
    out = []
    for row in markup.inline_keyboard:
        for btn in row:
            out.append((btn.text, btn.callback_data))
    return out


def _ctx(bot):
    return SimpleNamespace(bot=bot, user_data={}, job=None,
                           job_queue=FakeJobQueue())


def _update(msg, user_id=999, query=None):
    return SimpleNamespace(callback_query=query,
                           effective_user=SimpleNamespace(id=user_id),
                           effective_message=msg)


# ---------- backup file ----------
async def test_backup_file_created_and_restorable(dbpath, tmp_path):
    await _seed(dbpath)
    dest = str(tmp_path / "backups")
    out = backup.backup_db_file(db_path=dbpath, dest_dir=dest)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    assert out is not None
    assert out.endswith(f"hozhir-{today}.db")
    assert os.path.isfile(out)
    b = sqlite3.connect(out)
    assert b.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    assert b.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 2
    b.close()


async def test_backup_keeps_only_7(dbpath, tmp_path):
    dest = str(tmp_path / "backups")
    os.makedirs(dest, exist_ok=True)
    for day in range(1, 10):
        open(os.path.join(dest, f"hozhir-2026-10-{day:02d}.db"), "w").write("x")
    backup.backup_db_file(db_path=dbpath, dest_dir=dest)
    files = sorted(f for f in os.listdir(dest)
                   if f.startswith("hozhir-") and f.endswith(".db"))
    assert len(files) == 7
    assert "hozhir-2026-10-01.db" not in files


async def test_backup_invalid_dest_returns_none(dbpath, tmp_path):
    blocker = str(tmp_path / "blocker")
    open(blocker, "w").write("x")
    assert backup.backup_db_file(db_path=dbpath, dest_dir=blocker) is None


# ---------- scheduling helpers ----------
def test_needs_catchup():
    assert backup.needs_catchup_backup("", "2026-11-12", "2026-11-11") is True
    assert backup.needs_catchup_backup(None, "2026-11-12", "2026-11-11") is True
    assert backup.needs_catchup_backup("2026-11-11", "2026-11-12", "2026-11-11") is False
    assert backup.needs_catchup_backup("2026-11-12", "2026-11-12", "2026-11-11") is False
    assert backup.needs_catchup_backup("2026-11-10", "2026-11-12", "2026-11-11") is True


def test_tehran_dates():
    today = backup.tehran_today()
    assert today == datetime.datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d")
    assert backup.tehran_yesterday() != today


# ---------- auto toggle ----------
async def test_auto_backup_default_on(dbpath):
    assert await backup.auto_backup_on(path=dbpath) is True


async def test_auto_backup_toggle(dbpath):
    await db.set_setting(backup.AUTO_BACKUP_KEY, "0", path=dbpath)
    assert await backup.auto_backup_on(path=dbpath) is False
    await db.set_setting(backup.AUTO_BACKUP_KEY, "1", path=dbpath)
    assert await backup.auto_backup_on(path=dbpath) is True


# ---------- caption ----------
async def test_backup_caption(dbpath):
    await _seed(dbpath)
    cap = await backup.backup_caption(path=dbpath)
    assert "بکاپ" in cap
    assert "3 کاربر" in cap
    assert "2 فاکتور" in cap
    assert "1 سرویس فعال" in cap
    assert os.path.basename(dbpath) in cap  # نام فایل دیتابیس پویا است (تست: vpn.db، واقعی: hozhir.db)


# ---------- sending ----------
async def test_send_backup_to_admins(dbpath, tmp_path):
    await _seed(dbpath)
    bot = FakeBot()
    n = await backup.send_backup_to_admins(
        bot, db_path=dbpath, dest_dir=str(tmp_path / "backups"))
    assert n == 1
    assert len(bot.docs) == 1
    chat_id, filename, caption, data = bot.docs[0]
    assert chat_id == 999
    assert filename.startswith("hozhir-") and filename.endswith(".db")
    assert "config" not in filename
    assert caption and "بکاپ" in caption
    tmpdb = str(tmp_path / "sent.db")
    open(tmpdb, "wb").write(data)
    b = sqlite3.connect(tmpdb)
    assert b.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    assert b.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 2
    b.close()


async def test_send_backup_no_admins(dbpath, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", [])
    bot = FakeBot()
    n = await backup.send_backup_to_admins(
        bot, db_path=dbpath, dest_dir=str(tmp_path / "backups"))
    assert n == 0
    assert bot.docs == []


async def test_send_backup_failing_bot(dbpath, tmp_path):
    class FailingBot:
        async def send_document(self, *a, **k):
            raise RuntimeError("network down")

    n = await backup.send_backup_to_admins(
        FailingBot(), db_path=dbpath, dest_dir=str(tmp_path / "backups"))
    assert n == 0


# ---------- nightly send + date guard ----------
async def test_nightly_send_records_date(dbpath, tmp_path):
    await _seed(dbpath)
    bot = FakeBot()
    assert await backup.send_nightly_backup(bot, db_path=dbpath) is True
    assert len(bot.docs) == 1
    assert (await db.get_setting(backup.LAST_NIGHTLY_KEY, "",
                                  path=dbpath)) == backup.tehran_today()


async def test_nightly_send_skips_same_day(dbpath, tmp_path):
    await _seed(dbpath)
    bot = FakeBot()
    assert await backup.send_nightly_backup(bot, db_path=dbpath) is True
    assert await backup.send_nightly_backup(bot, db_path=dbpath) is True
    assert len(bot.docs) == 1  # second call sent nothing


async def test_nightly_send_respects_toggle_off(dbpath, tmp_path):
    await _seed(dbpath)
    await db.set_setting(backup.AUTO_BACKUP_KEY, "0", path=dbpath)
    bot = FakeBot()
    assert await backup.send_nightly_backup(bot, db_path=dbpath) is True
    assert bot.docs == []


# ---------- catch-up ----------
async def test_catchup_first_run_sends(dbpath, tmp_path):
    await _seed(dbpath)
    bot = FakeBot()
    assert await backup.maybe_send_catchup_backup(bot, db_path=dbpath) is True
    assert len(bot.docs) == 1


async def test_catchup_yesterday_sent_skips(dbpath, tmp_path):
    await db.set_setting(backup.LAST_NIGHTLY_KEY, backup.tehran_yesterday(),
                         path=dbpath)
    bot = FakeBot()
    assert await backup.maybe_send_catchup_backup(bot, db_path=dbpath) is False
    assert bot.docs == []


async def test_catchup_two_days_ago_sends(dbpath, tmp_path):
    two_ago = (datetime.datetime.now(ZoneInfo("Asia/Tehran"))
               - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    await db.set_setting(backup.LAST_NIGHTLY_KEY, two_ago, path=dbpath)
    bot = FakeBot()
    assert await backup.maybe_send_catchup_backup(bot, db_path=dbpath) is True
    assert len(bot.docs) == 1


async def test_catchup_toggle_off_sends_nothing(dbpath, tmp_path):
    await db.set_setting(backup.AUTO_BACKUP_KEY, "0", path=dbpath)
    bot = FakeBot()
    assert await backup.maybe_send_catchup_backup(bot, db_path=dbpath) is False
    assert bot.docs == []


# ---------- job queue ----------
async def test_nightly_job_retries_on_failure(dbpath, monkeypatch):
    async def _fail_send(bot, db_path=None):
        return False

    monkeypatch.setattr(backup, "send_nightly_backup", _fail_send)
    jq = FakeJobQueue()
    ctx = SimpleNamespace(bot=FakeBot(), job=SimpleNamespace(data={}),
                          job_queue=jq)
    await backup.nightly_backup_job(ctx)
    assert len(jq.once) == 1
    assert jq.once[0]["data"] == {"retries": 1}
    assert jq.once[0]["when"] == 3600


async def test_nightly_job_no_retry_after_two(dbpath, monkeypatch):
    async def _fail_send(bot, db_path=None):
        return False

    monkeypatch.setattr(backup, "send_nightly_backup", _fail_send)
    jq = FakeJobQueue()
    ctx = SimpleNamespace(bot=FakeBot(),
                          job=SimpleNamespace(data={"retries": 2}),
                          job_queue=jq)
    await backup.nightly_backup_job(ctx)
    assert jq.once == []


def test_schedule_jobs_registers_nightly():
    jq = FakeJobQueue()
    jobs.schedule_jobs(jq)
    nightly = [j for j in jq.daily if j["name"] == "nightly_backup"]
    assert len(nightly) == 1
    t = nightly[0]["time"]
    assert (t.hour, t.minute) == (0, 0)
    assert str(t.tzinfo) == "Asia/Tehran"
    assert nightly[0]["cb"] is backup.nightly_backup_job
    assert any(j["name"] == "daily_report" for j in jq.daily)
    assert any(j["name"] == "hourly_check" for j in jq.repeating)


# ---------- settings menu buttons ----------
async def test_settings_menu_has_backup_buttons(dbpath):
    msg = FakeMsg()
    upd = _update(msg)
    await handlers_admin.settings_menu(upd, _ctx(FakeBot()))
    assert msg.replies
    btns = _kb_callbacks(msg.replies[0][1])
    assert "adm_set_backup" in [cb for _, cb in btns]
    assert "adm_set_autobackup" in [cb for _, cb in btns]
    assert any(cb == "adm_set_autobackup" and "روشن" in t for t, cb in btns)


async def test_settings_menu_toggle_label_off(dbpath):
    await db.set_setting(backup.AUTO_BACKUP_KEY, "0", path=dbpath)
    msg = FakeMsg()
    await handlers_admin.settings_menu(_update(msg), _ctx(FakeBot()))
    btns = _kb_callbacks(msg.replies[0][1])
    assert any(cb == "adm_set_autobackup" and "خاموش" in t for t, cb in btns)


# ---------- callback dispatch ----------
async def test_callback_manual_backup_sends_file(dbpath, tmp_path):
    await _seed(dbpath)
    bot = FakeBot()
    msg = FakeMsg()
    q = FakeQuery(msg, data="adm_set_backup")
    upd = _update(msg, query=q)
    await handlers_admin.on_admin_callback(upd, _ctx(bot))
    assert len(bot.docs) == 1
    assert bot.docs[0][0] == 999
    assert any("بکاپ ساخته و فرستاده شد" in t for t, _ in msg.edits)


async def test_callback_toggle_flips_and_rerenders(dbpath):
    bot = FakeBot()
    msg = FakeMsg()
    q = FakeQuery(msg, data="adm_set_autobackup")
    await handlers_admin.on_admin_callback(_update(msg, query=q), _ctx(bot))
    assert (await db.get_setting(backup.AUTO_BACKUP_KEY, "",
                                 path=dbpath)) == "0"
    btns = _kb_callbacks(msg.edits[-1][1])
    assert any(cb == "adm_set_autobackup" and "خاموش" in t for t, cb in btns)
    msg2 = FakeMsg()
    q2 = FakeQuery(msg2, data="adm_set_autobackup")
    await handlers_admin.on_admin_callback(_update(msg2, query=q2), _ctx(bot))
    assert (await db.get_setting(backup.AUTO_BACKUP_KEY, "",
                                 path=dbpath)) == "1"


async def test_callback_non_admin_gets_nothing(dbpath, tmp_path):
    bot = FakeBot()
    msg = FakeMsg()
    q = FakeQuery(msg, data="adm_set_backup", user_id=555)
    await handlers_admin.on_admin_callback(_update(msg, user_id=555, query=q),
                                          _ctx(bot))
    assert bot.docs == []
    assert q.answered == 1
