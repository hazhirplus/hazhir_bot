"""Discount + gift codes (2026-11-18): db-level creation, validation
matrix, pricing math and atomic gift redemption.

Mirzabot rules ported here: codes normalize to UPPER with no spaces
(at creation AND at entry), the per-user limit is never nullable
(mirzabot's API let a NULL useuser through and the code then rejected
everyone), and the check order is exists -> active -> expired ->
limit_total -> limit_per_user -> first_only -> scope plan/panel ->
buy/renew kind.
"""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "discount.db")
    run(db.init_db(p))
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [999])
    return p


def _mk(code="SAVE20", kind="percent", value=20, **kw):
    return run(db.create_discount_code(code, kind, value, **kw))


def _validate(code, uid=111, **kw):
    return run(db.validate_discount(code, uid, **kw))


# ---------- normalization + creation ----------

def test_normalize_upper_no_spaces(dbpath):
    assert db.normalize_discount_code(" save 20 ") == "SAVE20"
    assert db.normalize_discount_code("gift50") == "GIFT50"


def test_create_percent_and_fixed(dbpath):
    cid = _mk("P20", "percent", 20)
    assert run(db.get_discount_code_by_id(cid))["kind"] == "percent"
    cid2 = _mk("F50K", "fixed", 50000)
    assert run(db.get_discount_code_by_id(cid2))["value"] == 50000


def test_duplicate_code_rejected(dbpath):
    _mk("DUP1")
    with pytest.raises(ValueError):
        _mk(" dup1 ")  # same code after normalization
    assert len(run(db.list_discount_codes())) == 1


def test_percent_range_enforced(dbpath):
    for bad in (0, 101, -5):
        with pytest.raises(ValueError):
            _mk(f"P{bad}", "percent", bad)


def test_fixed_must_be_positive(dbpath):
    with pytest.raises(ValueError):
        _mk("F0", "fixed", 0)
    with pytest.raises(ValueError):
        _mk("FNEG", "fixed", -100)


def test_limit_per_user_never_zero(dbpath):
    with pytest.raises(ValueError):
        _mk("LPU0", limit_per_user=0)
    with pytest.raises(ValueError):
        _mk("LPU-1", limit_per_user=-1)


def test_renew_only_first_only_rejected(dbpath):
    with pytest.raises(ValueError):
        _mk("BAD", scope_kind="renew", first_only=True)


def test_empty_code_rejected(dbpath):
    with pytest.raises(ValueError):
        run(db.create_discount_code("   ", "percent", 10))


# ---------- pricing ----------

def test_calc_percent(dbpath):
    assert db.calc_discounted_price("percent", 20, 90000) == 72000
    assert db.calc_discounted_price("percent", 100, 90000) == 0
    assert db.calc_discounted_price("percent", 33, 100000) == 67000


def test_calc_fixed_and_floor_zero(dbpath):
    assert db.calc_discounted_price("fixed", 50000, 90000) == 40000
    assert db.calc_discounted_price("fixed", 999999, 90000) == 0
    assert db.calc_discounted_price("fixed", 1000, 0) == 0


# ---------- validation matrix ----------

def test_validate_ok_and_case_insensitive(dbpath):
    _mk("SAVE20", "percent", 20)
    ok, row, err, final = _validate(" save20 ", 111, price=90000)
    assert ok and err is None and final == 72000 and row["code"] == "SAVE20"


def test_validate_not_found(dbpath):
    ok, row, err, final = _validate("NOPE", 111, price=90000)
    assert (ok, row, err, final) == (False, None, "not_found", None)


def test_validate_inactive(dbpath):
    cid = _mk("OFF1")
    run(db.set_discount_active(cid, False))
    ok, row, err, final = _validate("OFF1", 111, price=90000)
    assert err == "inactive"


def test_validate_expired(dbpath):
    _mk("OLD1", expires_at=int(time.time()) - 10)
    ok, row, err, final = _validate("OLD1", 111, price=90000)
    assert err == "expired"


def test_validate_unlimited_expiry_ok(dbpath):
    _mk("FOREVER", expires_at=None)
    ok, _, err, _ = _validate("FOREVER", 111, price=90000)
    assert ok and err is None


def test_validate_limit_total(dbpath):
    _mk("ONE1", limit_total=1)
    assert run(db.consume_discount_code(
        run(db.get_discount_code("ONE1"))["id"], 111, 1001))
    ok, row, err, final = _validate("ONE1", 222, price=90000)
    assert err == "limit_total"


def test_validate_limit_per_user(dbpath):
    _mk("TWO2", limit_total=0, limit_per_user=2)
    cid = run(db.get_discount_code("TWO2"))["id"]
    assert run(db.consume_discount_code(cid, 111, 1001))
    assert run(db.consume_discount_code(cid, 111, 1002))
    ok, row, err, final = _validate("TWO2", 111, price=90000)
    assert err == "limit_per_user"
    # another user is still fine
    ok, _, err, _ = _validate("TWO2", 222, price=90000)
    assert ok


def test_validate_first_only(dbpath):
    _mk("FIRST1", first_only=True)
    # user with no paid purchase passes
    ok, _, err, _ = _validate("FIRST1", 111, price=90000)
    assert ok
    # user with a paid purchase is rejected
    iid = run(db.create_invoice(222, "purchase", 1, 90000))
    run(db.update_invoice(iid, status="active"))
    ok, row, err, final = _validate("FIRST1", 222, price=90000)
    assert err == "first_only"
    # a test account does not count as a purchase
    iid = run(db.create_invoice(333, "test", None, 0))
    run(db.update_invoice(iid, status="active"))
    ok, _, err, _ = _validate("FIRST1", 333, price=90000)
    assert ok


def test_validate_scope_plan(dbpath):
    _mk("PLAN2", scope_plan=2)
    ok, _, err, _ = _validate("PLAN2", 111, plan_id=1, price=90000)
    assert err == "scope_plan"
    ok, _, err, _ = _validate("PLAN2", 111, plan_id=2, price=90000)
    assert ok
    # no plan given yet: scope is not checked (checked again at confirm)
    ok, _, err, _ = _validate("PLAN2", 111, price=90000)
    assert ok


def test_validate_scope_panel(dbpath):
    _mk("PANEL2", scope_panel=2)
    ok, _, err, _ = _validate("PANEL2", 111, panel_id=1, price=90000)
    assert err == "scope_panel"
    ok, _, err, _ = _validate("PANEL2", 111, panel_id=2, price=90000)
    assert ok


def test_validate_scope_kind(dbpath):
    _mk("BUYONLY", scope_kind="buy")
    ok, _, err, _ = _validate("BUYONLY", 111, kind="renew", price=90000)
    assert err == "scope_kind"
    ok, _, err, _ = _validate("BUYONLY", 111, kind="buy", price=90000)
    assert ok
    _mk("RENONLY", scope_kind="renew")
    ok, _, err, _ = _validate("RENONLY", 111, kind="buy", price=90000)
    assert err == "scope_kind"
    ok, _, err, _ = _validate("RENONLY", 111, kind="renew", price=90000)
    assert ok


def test_validate_fixed_amount(dbpath):
    _mk("FIX50", "fixed", 50000)
    ok, row, err, final = _validate("FIX50", 111, price=90000)
    assert ok and final == 40000


# ---------- consume / release ----------

def test_consume_and_release_roundtrip(dbpath):
    cid = _mk("USE1", limit_total=1, limit_per_user=1)
    assert run(db.consume_discount_code(cid, 111, 1001)) is True
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 1
    # second use by the same user is blocked
    assert run(db.consume_discount_code(cid, 111, 1002)) is False
    # release frees the code again
    assert run(db.release_discount_for_invoice(1001)) is False  # no such invoice
    assert run(db.release_discount_code(cid, 111, 1001)) is True
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 0
    assert run(db.consume_discount_code(cid, 111, 1001)) is True


def test_release_never_below_zero(dbpath):
    cid = _mk("REL0")
    assert run(db.release_discount_code(cid, 111)) is False
    assert run(db.get_discount_code_by_id(cid))["used_total"] == 0


def test_delete_code_drops_uses(dbpath):
    cid = _mk("DEL1")
    assert run(db.consume_discount_code(cid, 111, 1001))
    run(db.delete_discount_code(cid))
    assert run(db.get_discount_code_by_id(cid)) is None
    assert run(db.count_discount_uses(cid, 111)) == 0


def test_toggle_active(dbpath):
    cid = _mk("TOG1")
    run(db.set_discount_active(cid, False))
    assert run(db.get_discount_code_by_id(cid))["active"] == 0
    run(db.set_discount_active(cid, True))
    assert run(db.get_discount_code_by_id(cid))["active"] == 1


# ---------- gift codes ----------

def test_gift_create_and_redeem(dbpath):
    run(db.upsert_user(111, "buyer"))
    cid = run(db.create_gift_code("GIFT50", 50000))
    ok, amount, err = run(db.redeem_gift_code(" gift50 ", 111))
    assert (ok, amount, err) == (True, 50000, None)
    assert run(db.get_balance(111)) == 50000
    assert run(db.get_gift_code_by_id(cid))["used_total"] == 1


def test_gift_once_per_user(dbpath):
    run(db.create_gift_code("ONCE1", 10000))
    assert run(db.redeem_gift_code("ONCE1", 111))[0] is True
    ok, amount, err = run(db.redeem_gift_code("ONCE1", 111))
    assert (ok, err) == (False, "already_used")
    # another user can still take it
    assert run(db.redeem_gift_code("ONCE1", 222))[0] is True
    assert run(db.get_balance(111)) == 10000  # credited only once


def test_gift_limit_total(dbpath):
    run(db.create_gift_code("LIM1", 10000, limit_total=1))
    assert run(db.redeem_gift_code("LIM1", 111))[0] is True
    ok, amount, err = run(db.redeem_gift_code("LIM1", 222))
    assert (ok, err) == (False, "limit_total")


def test_gift_not_found_and_inactive(dbpath):
    ok, amount, err = run(db.redeem_gift_code("NOPE", 111))
    assert err == "not_found"
    cid = run(db.create_gift_code("OFFG", 10000))
    run(db.set_gift_active(cid, False))
    ok, amount, err = run(db.redeem_gift_code("OFFG", 111))
    assert err == "inactive"


def test_gift_duplicate_and_bad_amount(dbpath):
    run(db.create_gift_code("DUPG", 10000))
    with pytest.raises(ValueError):
        run(db.create_gift_code(" dupg ", 20000))
    with pytest.raises(ValueError):
        run(db.create_gift_code("ZERO", 0))
    with pytest.raises(ValueError):
        run(db.create_gift_code("NEG", -5))


def test_gift_delete_drops_uses(dbpath):
    cid = run(db.create_gift_code("DELG", 10000))
    assert run(db.redeem_gift_code("DELG", 111))[0] is True
    run(db.delete_gift_code(cid))
    assert run(db.get_gift_code_by_id(cid)) is None
    # redeeming the deleted code is a plain not-found
    assert run(db.redeem_gift_code("DELG", 222))[2] == "not_found"


def test_gift_redeem_creates_user_row(dbpath):
    # redeeming works even for a user with no users row yet
    run(db.create_gift_code("NEWU", 7000))
    ok, amount, err = run(db.redeem_gift_code("NEWU", 4242))
    assert ok and amount == 7000
    assert run(db.get_balance(4242)) == 7000
