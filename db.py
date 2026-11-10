"""SQLite persistence layer (aiosqlite). All queries parameterized."""
from __future__ import annotations
import json
import time
import aiosqlite

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    tg_id INTEGER PRIMARY KEY,
    username TEXT,
    joined INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS panels(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    token TEXT NOT NULL,
    sub_base TEXT NOT NULL DEFAULT '',
    inbounds_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS plans(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    days INTEGER NOT NULL,
    gb INTEGER NOT NULL,
    price_toman INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS invoices(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,            -- purchase | renew | test
    plan_id INTEGER,
    panel_id INTEGER,
    panel_email TEXT DEFAULT '',
    sub_id TEXT DEFAULT '',
    price_toman INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,          -- pending | active | rejected | expired
    receipt_file_id TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    activated_at INTEGER NOT NULL DEFAULT 0,
    expires_at INTEGER NOT NULL DEFAULT 0,
    warned_at INTEGER NOT NULL DEFAULT 0,
    volume_warned_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    status TEXT NOT NULL,          -- pending | approved | rejected
    decided_by INTEGER,
    decided_at INTEGER
);
CREATE TABLE IF NOT EXISTS cards(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL,
    holder TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tutorials(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    photo_file_id TEXT DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS referrals(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER NOT NULL,
    referred_id INTEGER NOT NULL UNIQUE,
    gift_invoice_id INTEGER,
    gifted_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
"""


async def init_db(path: str | None = None) -> None:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.executescript(SCHEMA)
        # migration-safe: add columns that older DBs lack
        for table, col, ddl in (
            ("users", "referred_by", "INTEGER DEFAULT NULL"),
            ("users", "balance_toman", "INTEGER NOT NULL DEFAULT 0"),
            ("invoices", "pay_method", "TEXT DEFAULT 'card'"),
            ("invoices", "crypto_chain", "TEXT DEFAULT ''"),
            ("invoices", "crypto_currency", "TEXT DEFAULT ''"),
            ("invoices", "crypto_amount", "TEXT DEFAULT ''"),
            ("invoices", "crypto_address", "TEXT DEFAULT ''"),
            ("invoices", "crypto_expires_at", "INTEGER NOT NULL DEFAULT 0"),
            ("invoices", "crypto_tx", "TEXT DEFAULT ''"),
            ("invoices", "crypto_meta", "TEXT DEFAULT ''"),
            ("invoices", "volume_warned_at", "INTEGER NOT NULL DEFAULT 0"),
        ):
            cur = await con.execute(f"PRAGMA table_info({table})")
            have = [r[1] for r in await cur.fetchall()]
            if col not in have:
                await con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        await con.commit()


async def seed_from_env(path: str | None = None) -> None:
    """First-run seeding from env vars. Never overwrites existing rows."""
    import text as T  # local import: text.py imports panel (heavy); avoid cycles
    path = path or config.DB_PATH
    now = int(time.time())
    async with aiosqlite.connect(path) as con:
        # settings defaults
        defaults = {
            "test_enabled": "1",
            "test_days": "1",
            "test_gb": "2",
            "warn_hours": "24",
            "warn_volume_pct": "80",
            "welcome_text": T.WELCOME_DEFAULT,
            "support_text": T.SUPPORT_TEXT_DEFAULT,
            "buy_guide": T.BUY_GUIDE_DEFAULT,
            "delivery_guide": T.DELIVERY_GUIDE_DEFAULT,
            "dl_android": T.DL_DEFAULTS["dl_android"],
            "dl_ios": T.DL_DEFAULTS["dl_ios"],
            "dl_windows": T.DL_DEFAULTS["dl_windows"],
            "ref_enabled": "1",
            "ref_gift_gb": "10",
            "ref_gift_days": "30",
            # crypto rail (v2.3): disabled until the owner enables it in settings
            "crypto_enabled": "0",
            "evm_address": config.EVM_ADDRESS,
            "etherscan_key": config.ETHERSCAN_API_KEY,
            "crypto_expiry_min": "90",
            "crypto_usd_toman": "",
        }
        for k, v in defaults.items():
            await con.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v)
            )
        # v2: refresh the welcome text if it still holds the v1 default
        await con.execute(
            "UPDATE settings SET value=? WHERE key='welcome_text' AND value=?",
            (T.WELCOME_DEFAULT,
             "به «هژیر وی پی ان» خوش اومدی 🌐\n\nاز منوی زیر انتخاب کن:"),
        )
        # panel from env
        if config.PANEL_URL and config.PANEL_TOKEN:
            cur = await con.execute("SELECT COUNT(*) FROM panels")
            if (await cur.fetchone())[0] == 0:
                await con.execute(
                    "INSERT INTO panels(name, url, token, sub_base, inbounds_json, active)"
                    " VALUES(?,?,?,?,?,1)",
                    (
                        "پنل اصلی",
                        config.PANEL_URL,
                        config.PANEL_TOKEN,
                        config.SUB_BASE,
                        json.dumps(config.INBOUNDS or [1]),
                    ),
                )
        # card from env
        if config.CARD_NUMBER:
            cur = await con.execute("SELECT COUNT(*) FROM cards")
            if (await cur.fetchone())[0] == 0:
                await con.execute(
                    "INSERT INTO cards(number, holder, active) VALUES(?,?,1)",
                    (config.CARD_NUMBER, config.CARD_HOLDER),
                )
        # plans
        cur = await con.execute("SELECT COUNT(*) FROM plans")
        if (await cur.fetchone())[0] == 0:
            plans = [
                ("۱۰ گیگ یک‌ماهه", 30, 10, 90000, 1),
                ("۳۰ گیگ یک‌ماهه", 30, 30, 270000, 2),
                ("۵۰ گیگ یک‌ماهه", 30, 50, 490000, 3),
                ("۸۰ گیگ یک‌ماهه", 30, 80, 700000, 4),
            ]
            for name, days, gb, price, sort in plans:
                await con.execute(
                    "INSERT INTO plans(name, days, gb, price_toman, active, sort)"
                    " VALUES(?,?,?,?,1,?)",
                    (name, days, gb, price, sort),
                )
        # tutorial seeds (only when table is empty)
        cur = await con.execute("SELECT COUNT(*) FROM tutorials")
        if (await cur.fetchone())[0] == 0:
            for title, body, sort in T.TUTORIAL_SEEDS:
                await con.execute(
                    "INSERT INTO tutorials(title, body, photo_file_id, sort, active)"
                    " VALUES(?,?,'',?,1)",
                    (title, body, sort),
                )
        await con.commit()
        _ = now


# ---------------- users ----------------
async def upsert_user(tg_id: int, username: str | None, path: str | None = None) -> None:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(
            "INSERT INTO users(tg_id, username, joined) VALUES(?,?,?)"
            " ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username",
            (tg_id, username or "", int(time.time())),
        )
        await con.commit()


async def get_user(tg_id: int, path: str | None = None):
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def count_new_users_since(ts: int, path: str | None = None) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute("SELECT COUNT(*) FROM users WHERE joined>=?", (ts,))
        return (await cur.fetchone())[0]


async def list_users(limit: int = 30, path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(
            "SELECT * FROM users ORDER BY joined DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cur.fetchall()]


# ---------------- panels ----------------
def _row_panel(r) -> dict:
    d = dict(r)
    try:
        d["inbounds"] = json.loads(d.get("inbounds_json") or "[]")
    except Exception:
        d["inbounds"] = []
    return d


async def list_panels(active_only: bool = True, path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    q = "SELECT * FROM panels" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(q)
        return [_row_panel(r) for r in await cur.fetchall()]


async def get_panel(pid: int, path: str | None = None):
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute("SELECT * FROM panels WHERE id=?", (pid,))
        row = await cur.fetchone()
        return _row_panel(row) if row else None


async def get_active_panel(path: str | None = None):
    panels = await list_panels(True, path)
    return panels[0] if panels else None


async def add_panel(name, url, token, sub_base, inbounds, path: str | None = None) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "INSERT INTO panels(name,url,token,sub_base,inbounds_json,active)"
            " VALUES(?,?,?,?,?,1)",
            (name, url.rstrip("/"), token, sub_base.rstrip("/"), json.dumps(inbounds)),
        )
        await con.commit()
        return cur.lastrowid


async def update_panel(pid: int, path: str | None = None, **fields) -> None:
    allowed = {"name", "url", "token", "sub_base", "inbounds_json", "active"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(pid)
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(f"UPDATE panels SET {','.join(sets)} WHERE id=?", vals)
        await con.commit()


async def delete_panel(pid: int, path: str | None = None) -> None:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute("DELETE FROM panels WHERE id=?", (pid,))
        await con.commit()


# ---------------- plans ----------------
async def list_plans(active_only: bool = True, path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    q = "SELECT * FROM plans" + (" WHERE active=1" if active_only else "") + " ORDER BY sort, id"
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(q)
        return [dict(r) for r in await cur.fetchall()]


async def get_plan(pid: int, path: str | None = None):
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute("SELECT * FROM plans WHERE id=?", (pid,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def add_plan(name, days, gb, price, path: str | None = None) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute("SELECT COALESCE(MAX(sort),0)+1 FROM plans")
        sort = (await cur.fetchone())[0]
        cur = await con.execute(
            "INSERT INTO plans(name,days,gb,price_toman,active,sort) VALUES(?,?,?, ?,1,?)",
            (name, days, gb, price, sort),
        )
        await con.commit()
        return cur.lastrowid


async def update_plan(pid: int, path: str | None = None, **fields) -> None:
    allowed = {"name", "days", "gb", "price_toman", "active", "sort"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(pid)
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(f"UPDATE plans SET {','.join(sets)} WHERE id=?", vals)
        await con.commit()


async def delete_plan(pid: int, path: str | None = None) -> None:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute("DELETE FROM plans WHERE id=?", (pid,))
        await con.commit()


# ---------------- invoices ----------------
async def create_invoice(user_id, kind, plan_id, price_toman, receipt_file_id="",
                         path: str | None = None, **extra) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "INSERT INTO invoices(user_id,kind,plan_id,price_toman,status,receipt_file_id,created_at)"
            " VALUES(?,?,?,?,'pending',?,?)",
            (user_id, kind, plan_id, price_toman, receipt_file_id, int(time.time())),
        )
        iid = cur.lastrowid
        await con.execute(
            "INSERT INTO payments(invoice_id,status) VALUES(?,'pending')", (iid,)
        )
        await con.commit()
    if extra:
        await update_invoice(iid, path=path, **extra)
    return iid


async def get_invoice(iid: int, path: str | None = None):
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute("SELECT * FROM invoices WHERE id=?", (iid,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def find_invoice_by_receipt(receipt_file_id: str,
                                  exclude_id: int | None = None,
                                  path: str | None = None) -> list[dict]:
    """Live (pending/active/paid) invoices that already used this receipt.

    Used for the reuse-fraud warning: the same receipt photo/file_id or the
    same typed tracking number submitted for more than one order. Rejected and
    expired invoices don't count (legit retry after a rejection is allowed).
    """
    path = path or config.DB_PATH
    q = ("SELECT * FROM invoices WHERE receipt_file_id=? "
         "AND status NOT IN ('rejected','expired')")
    vals: list = [receipt_file_id]
    if exclude_id is not None:
        q += " AND id != ?"
        vals.append(exclude_id)
    q += " ORDER BY id DESC"
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(q, vals)
        return [dict(r) for r in await cur.fetchall()]


async def list_invoices(status: str | None = None, kind: str | None = None,
                        limit: int = 50, path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    q, vals = "SELECT * FROM invoices WHERE 1=1", []
    if status:
        q += " AND status=?"; vals.append(status)
    if kind:
        q += " AND kind=?"; vals.append(kind)
    q += " ORDER BY id DESC LIMIT ?"; vals.append(limit)
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(q, vals)
        return [dict(r) for r in await cur.fetchall()]


async def update_invoice(iid: int, path: str | None = None, **fields) -> None:
    allowed = {"kind", "plan_id", "panel_id", "panel_email", "sub_id", "price_toman",
               "status", "receipt_file_id", "activated_at", "expires_at", "warned_at",
               "volume_warned_at",
               "pay_method", "crypto_chain", "crypto_currency", "crypto_amount",
               "crypto_address", "crypto_expires_at", "crypto_tx", "crypto_meta"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(iid)
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(f"UPDATE invoices SET {','.join(sets)} WHERE id=?", vals)
        await con.commit()


async def set_payment(iid: int, status: str, decided_by: int | None = None,
                      path: str | None = None) -> None:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(
            "UPDATE payments SET status=?, decided_by=?, decided_at=? WHERE invoice_id=?",
            (status, decided_by, int(time.time()), iid),
        )
        await con.commit()


async def user_invoices(tg_id: int, statuses=("active",), path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    q = f"SELECT * FROM invoices WHERE user_id=? AND status IN ({','.join('?'*len(statuses))}) ORDER BY id DESC"
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(q, (tg_id, *statuses))
        return [dict(r) for r in await cur.fetchall()]


async def user_had_test(tg_id: int, path: str | None = None) -> bool:
    """True if the user already holds (or awaits) a test account. One per user ever."""
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "SELECT COUNT(*) FROM invoices WHERE user_id=? AND kind='test'"
            " AND status IN ('pending','paid','active')",
            (tg_id,),
        )
        return (await cur.fetchone())[0] > 0


async def migrate_expire_stuck_tests(path: str | None = None) -> int:
    """One-time v2 migration: legacy test invoices stuck in 'pending' (the old
    admin-approval flow) are marked expired so they never block the user."""
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "UPDATE invoices SET status='expired'"
            " WHERE kind='test' AND status='pending'"
        )
        await con.commit()
        return cur.rowcount


async def count_pending_payments(path: str | None = None) -> int:
    """Pending purchase/renew invoices (test accounts need no approval;
    crypto invoices are auto-verified, not admin-approved)."""
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "SELECT COUNT(*) FROM invoices WHERE status='pending'"
            " AND kind IN ('purchase','renew')"
            " AND (pay_method IS NULL OR pay_method != 'crypto')"
        )
        return (await cur.fetchone())[0]


async def list_pending_crypto(limit: int = 200, path: str | None = None) -> list[dict]:
    """Pending crypto invoices, oldest first (for the chainwatch job)."""
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(
            "SELECT * FROM invoices WHERE status='pending' AND pay_method='crypto'"
            " ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def sales_since(ts: int, path: str | None = None) -> tuple[int, int]:
    """(count, sum_toman) of paid/active purchase+renew invoices created since ts."""
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "SELECT COUNT(*), COALESCE(SUM(price_toman),0) FROM invoices"
            " WHERE created_at>=? AND status IN ('active','expired')"
            " AND kind IN ('purchase','renew')",
            (ts,),
        )
        row = await cur.fetchone()
        return row[0], row[1]


async def renewals_since(ts: int, path: str | None = None) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "SELECT COUNT(*) FROM invoices WHERE created_at>=? AND kind='renew'"
            " AND status IN ('active','expired')",
            (ts,),
        )
        return (await cur.fetchone())[0]


async def expiring_soon(hours: int, path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    now = int(time.time())
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(
            "SELECT * FROM invoices WHERE status='active' AND expires_at>? AND expires_at<?",
            (now, now + hours * 3600),
        )
        return [dict(r) for r in await cur.fetchall()]


async def due_for_warn(warn_hours: int, path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    now = int(time.time())
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(
            "SELECT * FROM invoices WHERE status='active' AND warned_at=0"
            " AND expires_at>? AND expires_at<?",
            (now, now + warn_hours * 3600),
        )
        return [dict(r) for r in await cur.fetchall()]


async def due_for_volume_warn(path: str | None = None) -> list[dict]:
    """Active invoices never warned about volume, with a panel account.

    Volume itself lives on the panel (client.totalGB), so the caller checks
    actual usage; this only narrows the candidates. volume_warned_at=-1
    marks an orphan (panel account gone) — excluded, see jobs.hourly_check.
    """
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(
            "SELECT * FROM invoices WHERE status='active' AND volume_warned_at=0"
            " AND panel_email<>''",
        )
        return [dict(r) for r in await cur.fetchall()]


async def due_for_expire(path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    now = int(time.time())
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(
            "SELECT * FROM invoices WHERE status='active' AND expires_at>0 AND expires_at<=?",
            (now,),
        )
        return [dict(r) for r in await cur.fetchall()]


# ---------------- cards ----------------
async def list_cards(active_only: bool = True, path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    q = "SELECT * FROM cards" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(q)
        return [dict(r) for r in await cur.fetchall()]


async def get_active_card(path: str | None = None):
    cards = await list_cards(True, path)
    return cards[0] if cards else None


async def add_card(number: str, holder: str, path: str | None = None) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "INSERT INTO cards(number,holder,active) VALUES(?,?,1)",
            (number.replace(" ", ""), holder),
        )
        await con.commit()
        return cur.lastrowid


async def update_card(cid: int, path: str | None = None, **fields) -> None:
    allowed = {"number", "holder", "active"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(cid)
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(f"UPDATE cards SET {','.join(sets)} WHERE id=?", vals)
        await con.commit()


async def delete_card(cid: int, path: str | None = None) -> None:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute("DELETE FROM cards WHERE id=?", (cid,))
        await con.commit()


# ---------------- settings ----------------
async def get_setting(key: str, default: str = "", path: str | None = None) -> str:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str, path: str | None = None) -> None:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(
            "INSERT INTO settings(key,value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await con.commit()


# ---------------- tutorials ----------------
async def list_tutorials(active_only: bool = True, path: str | None = None) -> list[dict]:
    path = path or config.DB_PATH
    q = "SELECT * FROM tutorials" + (" WHERE active=1" if active_only else "") \
        + " ORDER BY sort, id"
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(q)
        return [dict(r) for r in await cur.fetchall()]


async def get_tutorial(tid: int, path: str | None = None):
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute("SELECT * FROM tutorials WHERE id=?", (tid,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def add_tutorial(title: str, body: str, photo_file_id: str = "",
                       path: str | None = None) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute("SELECT COALESCE(MAX(sort),0)+1 FROM tutorials")
        sort = (await cur.fetchone())[0]
        cur = await con.execute(
            "INSERT INTO tutorials(title,body,photo_file_id,sort,active)"
            " VALUES(?,?,?,?,1)",
            (title, body, photo_file_id, sort),
        )
        await con.commit()
        return cur.lastrowid


async def update_tutorial(tid: int, path: str | None = None, **fields) -> None:
    allowed = {"title", "body", "photo_file_id", "sort", "active"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(tid)
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(f"UPDATE tutorials SET {','.join(sets)} WHERE id=?", vals)
        await con.commit()


async def delete_tutorial(tid: int, path: str | None = None) -> None:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute("DELETE FROM tutorials WHERE id=?", (tid,))
        await con.commit()


# ---------------- wallet ----------------
async def get_balance(tg_id: int, path: str | None = None) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "SELECT balance_toman FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        return int(row[0] or 0) if row else 0


async def add_balance(tg_id: int, delta: int, path: str | None = None) -> int:
    """Add (or subtract) balance. Returns the new balance."""
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(
            "INSERT INTO users(tg_id, username, joined, balance_toman)"
            " VALUES(?,?,?,?)"
            " ON CONFLICT(tg_id) DO UPDATE SET"
            " balance_toman = users.balance_toman + excluded.balance_toman",
            (tg_id, "", int(time.time()), int(delta)),
        )
        await con.commit()
        cur = await con.execute(
            "SELECT balance_toman FROM users WHERE tg_id=?", (tg_id,))
        return int((await cur.fetchone())[0] or 0)


async def debit_balance(tg_id: int, amount: int, path: str | None = None) -> bool:
    """Atomically debit `amount` if the balance covers it. True on success.

    Single conditional UPDATE: the funds check and the debit happen in one
    statement, so two concurrent debits cannot both pass — the second sees
    the reduced balance and affects 0 rows. Returns False (no change) when
    funds are short or the user has no row yet. Fixes the wallet double-spend
    (vibe-check check 32, 2026-11-10).
    """
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "UPDATE users SET balance_toman = balance_toman - ? "
            "WHERE tg_id = ? AND balance_toman >= ?",
            (int(amount), tg_id, int(amount)),
        )
        await con.commit()
        return cur.rowcount == 1


# ---------------- referrals ----------------
async def attribute_referral(referred_id: int, referrer_id: int,
                             path: str | None = None) -> bool:
    """Attribute a new user to a referrer. First join only, no self-referral."""
    if not referrer_id or referrer_id == referred_id:
        return False
    path = path or config.DB_PATH
    if not await get_user(referrer_id, path):
        return False
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "UPDATE users SET referred_by=? WHERE tg_id=? AND referred_by IS NULL",
            (referrer_id, referred_id),
        )
        if cur.rowcount:
            await con.execute(
                "INSERT OR IGNORE INTO referrals(referrer_id, referred_id, created_at)"
                " VALUES(?,?,?)",
                (referrer_id, referred_id, int(time.time())),
            )
            await con.commit()
            return True
        return False


async def get_pending_referral(referred_id: int, path: str | None = None):
    """Referral row awaiting its gift (gifted_at=0), or None."""
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(
            "SELECT * FROM referrals WHERE referred_id=? AND gifted_at=0",
            (referred_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def mark_referral_gifted(ref_id: int, gift_invoice_id: int,
                               path: str | None = None) -> None:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        await con.execute(
            "UPDATE referrals SET gifted_at=?, gift_invoice_id=? WHERE id=?",
            (int(time.time()), gift_invoice_id, ref_id),
        )
        await con.commit()


async def count_referrals(referrer_id: int, path: str | None = None) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (referrer_id,))
        return (await cur.fetchone())[0]


async def count_referral_gifts(referrer_id: int, path: str | None = None) -> int:
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND gifted_at>0",
            (referrer_id,),
        )
        return (await cur.fetchone())[0]


async def count_paid_purchases(tg_id: int, path: str | None = None) -> int:
    """Paid purchase/renew invoices (active or expired) for gift eligibility."""
    path = path or config.DB_PATH
    async with aiosqlite.connect(path) as con:
        cur = await con.execute(
            "SELECT COUNT(*) FROM invoices WHERE user_id=?"
            " AND kind IN ('purchase','renew') AND status IN ('active','expired')",
            (tg_id,),
        )
        return (await cur.fetchone())[0]
