"""v3 tests: anti-flood rate limiter + duplicate-receipt detection.
All DB tests use a temp sqlite file; FloodGuard uses injected timestamps."""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
from throttle import FloodGuard


@pytest.fixture()
def dbpath(tmp_path):
    p = str(tmp_path / "v3.db")
    asyncio.get_event_loop().run_until_complete(_init(p))
    return p


async def _init(p):
    await db.init_db(p)
    await db.seed_from_env(p)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------- FloodGuard ----------
def test_allow_up_to_limit_then_deny():
    g = FloodGuard(limit=3, window=60.0)
    t = 1000.0
    assert g.allow(1, now=t)
    assert g.allow(1, now=t + 1)
    assert g.allow(1, now=t + 2)
    assert not g.allow(1, now=t + 3)
    assert not g.allow(1, now=t + 4)


def test_window_slides_and_reallows():
    g = FloodGuard(limit=2, window=10.0)
    t = 1000.0
    assert g.allow(1, now=t)
    assert g.allow(1, now=t + 1)
    assert not g.allow(1, now=t + 2)
    # both old hits expired after the window
    assert g.allow(1, now=t + 11)
    assert g.allow(1, now=t + 11.5)
    assert not g.allow(1, now=t + 12)


def test_users_are_isolated():
    g = FloodGuard(limit=1, window=60.0)
    t = 1000.0
    assert g.allow(1, now=t)
    assert not g.allow(1, now=t + 1)
    assert g.allow(2, now=t + 1)  # other user unaffected


def test_admin_gets_higher_limit():
    g = FloodGuard(limit=1, admin_limit=5, window=60.0)
    t = 1000.0
    assert g.allow(9, admin=False, now=t)
    assert not g.allow(9, admin=False, now=t + 1)
    for i in range(5):
        assert g.allow(7, admin=True, now=t + i)
    assert not g.allow(7, admin=True, now=t + 5)


def test_warn_due_cooldown():
    g = FloodGuard(warn_cooldown=120.0)
    t = 1000.0
    assert g.warn_due(1, now=t)
    assert not g.warn_due(1, now=t + 60)
    assert g.warn_due(1, now=t + 120)
    assert g.warn_due(2, now=t + 1)  # per-user cooldown


def test_old_hits_do_not_leak_memory():
    g = FloodGuard(limit=1, window=1.0)
    g.allow(1, now=1000.0)
    assert 1 in g._hits
    g.allow(1, now=2000.0)  # old hit pruned
    assert len(g._hits[1]) == 1


# ---------- duplicate receipts ----------
def test_find_invoice_by_receipt_matches_live_ones(dbpath):
    iid = run(db.create_invoice(111, "purchase", 1, 90000,
                                receipt_file_id="photoABC", path=dbpath))
    found = run(db.find_invoice_by_receipt("photoABC", path=dbpath))
    assert [i["id"] for i in found] == [iid]


def test_find_invoice_by_receipt_ignores_rejected_and_expired(dbpath):
    iid1 = run(db.create_invoice(111, "purchase", 1, 90000,
                                 receipt_file_id="photoXYZ", path=dbpath))
    iid2 = run(db.create_invoice(222, "topup", None, 50000,
                                 receipt_file_id="photoXYZ", path=dbpath))
    run(db.update_invoice(iid1, path=dbpath, status="rejected"))
    run(db.update_invoice(iid2, path=dbpath, status="expired"))
    assert run(db.find_invoice_by_receipt("photoXYZ", path=dbpath)) == []


def test_find_invoice_by_receipt_exclude_id(dbpath):
    iid = run(db.create_invoice(111, "purchase", 1, 90000,
                                receipt_file_id="photoQ", path=dbpath))
    assert run(db.find_invoice_by_receipt("photoQ", path=dbpath))
    assert run(db.find_invoice_by_receipt("photoQ", exclude_id=iid,
                                          path=dbpath)) == []


def test_find_invoice_by_receipt_text_numbers(dbpath):
    iid = run(db.create_invoice(111, "purchase", 1, 90000,
                                receipt_file_id="text:1234567890", path=dbpath))
    found = run(db.find_invoice_by_receipt("text:1234567890", path=dbpath))
    assert [i["id"] for i in found] == [iid]
    assert run(db.find_invoice_by_receipt("text:0000", path=dbpath)) == []


def test_dup_warn_text_formats():
    import text as T
    s = T.DUP_RECEIPT_WARN.format(iid=7, uid=123)
    assert "#7" in s and "123" in s and "تکراری" in s
    assert T.FLOOD_WARN.strip()
