"""v2.3 crypto rail tests: amount math, unique amounts, backend parsing,
invoice lifecycle, expiry, validation, rate fallback. Temp sqlite DBs only."""
import asyncio
import os
import re
import sys
import time
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db
import chainwatch
import text as T
from chainwatch import CHAINS, CURRENCIES


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def dbpath(tmp_path):
    p = str(tmp_path / "crypto.db")
    run(_init(p))
    return p


@pytest.fixture(autouse=True)
def _fresh_amount_registry():
    chainwatch._issued_amounts.clear()
    yield
    chainwatch._issued_amounts.clear()


async def _init(p):
    await db.init_db(p)
    await db.seed_from_env(p)


# ---------- fakes ----------
class _FakeBot:
    def __init__(self):
        self.sent = []
        self.photos = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, photo, **kw):
        self.photos.append(chat_id)


class _FakeCtx:
    def __init__(self):
        self.bot = _FakeBot()
        self.user_data = {}


class _FakePanel:
    def __init__(self):
        self.clients = {}

    async def add_client(self, inbound_ids, email, total_bytes, expiry_ms,
                         sub_id, tg_id=0, comment=""):
        self.clients[email] = {"email": email, "subId": sub_id}
        return {"success": True}

    async def get_client(self, email):
        return self.clients.get(email)

    async def sub_links(self, sub_id):
        return []

    async def links(self, email):
        return []

    async def fetch_sub_http(self, base, sub_id):
        return []


# ---------- amount math ----------
def test_base_amount_math():
    # 90,000 toman @ 2,700,000 t/USDT, ETH @ $2333
    usdc = chainwatch._base_amount(90000, "USDC", 2700000.0, 2333.0)
    assert usdc == Decimal(90000) / Decimal("2700000")
    eth = chainwatch._base_amount(90000, "ETH", 2700000.0, 2333.0)
    assert eth == Decimal(90000) / Decimal("2700000") / Decimal("2333")


def test_unique_amounts():
    seen = set()
    for _ in range(100):
        s = chainwatch.make_unique(Decimal("3.4521"), 6, 3)
        assert re.fullmatch(r"\d+\.\d{6}", s), s
        assert Decimal(s) > 0
        seen.add(s)
    assert len(seen) == 100  # all unique
    seen8 = {chainwatch.make_unique(Decimal("0.01429"), 8, 4) for _ in range(100)}
    assert len(seen8) == 100
    assert all(re.fullmatch(r"\d+\.\d{8}", s) for s in seen8)


def test_quote_mocked_rates(monkeypatch):
    async def fake_rates():
        return (2700000.0, 2333.0)
    monkeypatch.setattr(chainwatch, "get_rates", fake_rates)
    q = run(chainwatch.quote(90000, "USDC"))
    assert q["currency"] == "USDC"
    assert re.fullmatch(r"\d+\.\d{6}", q["amount"])
    assert q["units"] == int(Decimal(q["amount"]) * 10 ** 6)
    assert abs(q["usd_value"] - 90000 / 2700000) < 0.01
    qe = run(chainwatch.quote(90000, "ETH"))
    assert re.fullmatch(r"\d+\.\d{8}", qe["amount"])
    assert qe["units"] == int(Decimal(qe["amount"]) * 10 ** 18)
    with pytest.raises(ValueError):
        run(chainwatch.quote(90000, "USDT"))  # only ETH/USDC allowed


def test_quote_low_value_warn(monkeypatch):
    async def fake_rates():
        return (2700000.0, 2333.0)
    monkeypatch.setattr(chainwatch, "get_rates", fake_rates)
    q = run(chainwatch.quote(1000, "USDC"))  # ~$0.0004
    assert q["low_value_warn"] is True
    q2 = run(chainwatch.quote(50_000_000, "USDC"))  # ~$18.5
    assert q2["low_value_warn"] is False


# ---------- rate fallback ----------
def test_rate_fallback_coingecko(monkeypatch, dbpath):
    async def boom():
        raise RuntimeError("down")
    async def cg():
        return 2500.0
    monkeypatch.setattr(chainwatch, "_fetch_nobitex", boom)
    monkeypatch.setattr(chainwatch, "_fetch_coingecko_eth_usd", cg)
    monkeypatch.setattr(config, "DB_PATH", dbpath)
    run(db.set_setting("crypto_usd_toman", "2800000", dbpath))
    assert run(chainwatch.get_rates()) == (2800000.0, 2500.0)
    # no override -> RateError
    run(db.set_setting("crypto_usd_toman", "", dbpath))
    with pytest.raises(chainwatch.RateError):
        run(chainwatch.get_rates())


# ---------- validation ----------
def test_chain_currency_validation():
    assert set(CURRENCIES) == {"ETH", "USDC"}
    assert "USDT" not in CURRENCIES
    assert set(CHAINS) == {8453, 42161, 10}
    assert 999 not in CHAINS
    # verified live 2026-11-04 (Circle docs + CoinGecko + Arbiscan)
    assert CHAINS[8453]["usdc"].lower() == \
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    assert CHAINS[42161]["usdc"].lower() == \
        "0xaf88d065e77c8cc2239327c5edb3a432268e5831"
    assert CHAINS[10]["usdc"].lower() == \
        "0x0b2c639c533813f4aa9d7837caf62653d097ff85"


# ---------- etherscan backend parsing ----------
def _es_tx(to, value, ts, h="0xabc", err="0"):
    return {"to": to, "value": str(value), "timeStamp": str(ts),
            "hash": h, "isError": err, "confirmations": "12"}


@pytest.mark.asyncio
async def test_etherscan_usdc_match(monkeypatch):
    be = chainwatch.EtherscanV2Backend("KEY")
    addr = "0x1111111111111111111111111111111111111111"
    good = _es_tx(addr, 3452100, 1793786000)
    bad_val = _es_tx(addr, 3452101, 1793786000)
    bad_time = _es_tx(addr, 3452100, 1793785000)
    bad_err = _es_tx(addr, 3452100, 1793786000, err="1")
    seen = {}

    async def fake_api(params):
        seen.update(params)
        assert params["action"] == "tokentx"
        assert params["chainid"] == 8453
        assert "contractaddress" in params
        return {"status": "1",
                "result": [bad_val, bad_time, bad_err, good]}

    monkeypatch.setattr(be, "_api", fake_api)
    got = await be.find_payment(chain_id=8453, currency="USDC", address=addr,
                                expected_units=3452100, since_ts=1793785900,
                                meta={})
    assert got == "0xabc"


@pytest.mark.asyncio
async def test_etherscan_no_match(monkeypatch):
    be = chainwatch.EtherscanV2Backend("KEY")
    addr = "0x1111111111111111111111111111111111111111"

    async def fake_api(params):
        assert params["action"] == "txlist"  # native ETH path
        assert "contractaddress" not in params
        return {"status": "1", "result": [_es_tx(addr, 999, 1793786000)]}

    monkeypatch.setattr(be, "_api", fake_api)
    got = await be.find_payment(chain_id=10, currency="ETH", address=addr,
                                expected_units=10 ** 15, since_ts=1793785900,
                                meta={})
    assert got is None


# ---------- public rpc backend parsing ----------
@pytest.mark.asyncio
async def test_publicrpc_usdc_log_match(monkeypatch):
    be = chainwatch.PublicRpcBackend()
    addr = "0x1111111111111111111111111111111111111111"
    padded = "0x" + "0" * 24 + addr[2:]
    log_ok = {
        "transactionHash": "0xdead",
        "blockNumber": "0x100",
        "topics": [chainwatch.TRANSFER_TOPIC,
                   "0x" + "0" * 24 + "ab" * 20,
                   padded],
        "data": hex(3452100),
    }
    log_wrong = dict(log_ok, data=hex(3452101), transactionHash="0xnope")

    async def fake_rpc(chain_id, method, params):
        if method == "eth_blockNumber":
            return "0x200"
        if method == "eth_getLogs":
            assert params[0]["topics"][2] == padded
            return [log_wrong, log_ok]
        if method == "eth_getBlockByNumber":
            return {"timestamp": hex(1793786000)}
        raise AssertionError(method)

    monkeypatch.setattr(be, "_rpc", fake_rpc)
    got = await be.find_payment(chain_id=8453, currency="USDC", address=addr,
                                expected_units=3452100, since_ts=1793785900,
                                meta={})
    assert got == "0xdead"


@pytest.mark.asyncio
async def test_publicrpc_eth_balance_delta(monkeypatch, dbpath):
    be = chainwatch.PublicRpcBackend()
    monkeypatch.setattr(config, "DB_PATH", dbpath)
    addr = "0x1111111111111111111111111111111111111111"
    base = 10 ** 18
    await db.set_setting(be._baseline_key(8453), str(base), dbpath)

    async def fake_rpc(chain_id, method, params):
        assert method == "eth_getBalance"
        return hex(base + 123456)

    monkeypatch.setattr(be, "_rpc", fake_rpc)
    got = await be.find_payment(chain_id=8453, currency="ETH", address=addr,
                                expected_units=123456, since_ts=0, meta={})
    assert got == "eth:balance-delta"
    # baseline advanced past the payment
    assert await db.get_setting(be._baseline_key(8453), dbpath) == str(base + 123456)
    # same check again -> no double match
    got2 = await be.find_payment(chain_id=8453, currency="ETH", address=addr,
                                 expected_units=123456, since_ts=0, meta={})
    assert got2 is None


# ---------- invoice lifecycle ----------
async def _acrypto_invoice(p, **kw):
    now = int(time.time())
    d = dict(kind="purchase", plan_id=None, price_toman=90000,
             pay_method="crypto", crypto_chain="8453", crypto_currency="USDC",
             crypto_amount="0.033333", crypto_address="0xabc",
             crypto_expires_at=now + 3600, crypto_meta="{}")
    d.update(kw)
    uid = d.pop("user_id", 777001)
    return await db.create_invoice(uid, path=p, **d)


def _mk_crypto_invoice(p, **kw):
    return run(_acrypto_invoice(p, **kw))


@pytest.mark.asyncio
async def test_crypto_lifecycle_activate(monkeypatch, tmp_path):
    import helpers
    p = str(tmp_path / "life.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [])
    await db.add_panel("t", "http://127.0.0.1:1", "tok",
                       "http://127.0.0.1:1/sub", [1], p)
    pid = await db.add_plan("p", 30, 10, 90000, p)
    await db.upsert_user(777001, "buyer", p)
    fake = _FakePanel()
    monkeypatch.setattr(helpers, "panel_client_for", lambda panel: fake)

    iid = await _acrypto_invoice(p, plan_id=pid)
    inv = await db.get_invoice(iid, p)
    ctx = _FakeCtx()
    ok = await helpers.activate_crypto_invoice(ctx, inv, "0xtxhash")
    assert ok is True
    inv2 = await db.get_invoice(iid, p)
    assert inv2["status"] == "active"
    assert inv2["crypto_tx"] == "0xtxhash"
    assert any("تأیید شد" in t for _, t in ctx.bot.sent)
    # second activation attempt -> rejected (no double provisioning)
    assert await helpers.activate_crypto_invoice(ctx, inv2, "0xother") is False


@pytest.mark.asyncio
async def test_crypto_expiry_job(monkeypatch, tmp_path):
    import jobs
    p = str(tmp_path / "exp.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    monkeypatch.setattr(config, "DB_PATH", p)
    await db.upsert_user(777002, "late", p)
    iid = await _acrypto_invoice(p, user_id=777002,
                                 crypto_expires_at=int(time.time()) - 10)
    ctx = _FakeCtx()
    await jobs.crypto_check(ctx)
    inv = await db.get_invoice(iid, p)
    assert inv["status"] == "expired"
    assert any("تموم شد" in t for _, t in ctx.bot.sent)


@pytest.mark.asyncio
async def test_crypto_job_activates(monkeypatch, tmp_path):
    import helpers
    import jobs
    p = str(tmp_path / "job.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(config, "ADMIN_IDS", [])
    await db.add_panel("t", "http://127.0.0.1:1", "tok",
                       "http://127.0.0.1:1/sub", [1], p)
    pid = await db.add_plan("p", 30, 10, 90000, p)
    await db.upsert_user(777003, "jobbuyer", p)
    fake = _FakePanel()
    monkeypatch.setattr(helpers, "panel_client_for", lambda panel: fake)

    async def fake_find(inv):
        return "0xjobtx"

    monkeypatch.setattr(chainwatch, "find_payment_for_invoice", fake_find)
    iid = await _acrypto_invoice(p, user_id=777003, plan_id=pid)
    ctx = _FakeCtx()
    await jobs.crypto_check(ctx)
    inv = await db.get_invoice(iid, p)
    assert inv["status"] == "active"
    assert inv["crypto_tx"] == "0xjobtx"


# ---------- db migration ----------
def test_invoice_crypto_columns_migrated(dbpath):
    inv = _mk_crypto_invoice(dbpath)
    row = run(db.get_invoice(inv, dbpath))
    assert row["pay_method"] == "crypto"
    assert row["crypto_currency"] == "USDC"
    assert row["crypto_chain"] == "8453"
    assert run(db.list_pending_crypto(10, dbpath))[0]["id"] == inv
    # legacy rows default to card
    iid2 = run(db.create_invoice(1, "purchase", None, 100, path=dbpath))
    assert run(db.get_invoice(iid2, dbpath))["pay_method"] == "card"


def test_crypto_settings_seeded(dbpath):
    assert run(db.get_setting("crypto_enabled", "?", dbpath)) == "0"
    # No personal wallet baked in: default EVM address is empty, set via env.
    assert run(db.get_setting("evm_address", "?", dbpath)) == ""
    assert run(db.get_setting("crypto_expiry_min", "?", dbpath)) == "90"


@pytest.mark.asyncio
async def test_seed_issued_amounts(tmp_path):
    p = str(tmp_path / "seed.db")
    await db.init_db(p)
    await db.seed_from_env(p)
    await db.upsert_user(777009, "seeder", p)
    iid = await _acrypto_invoice(p, user_id=777009,
                                 crypto_amount="1.234567")
    n = await chainwatch.seed_issued_amounts(p)
    assert n == 1
    assert "1.234567" in chainwatch._issued_amounts
    # new amounts from the same base never collide with the seeded one
    for _ in range(20):
        s = chainwatch.make_unique(Decimal("1.234567"), 6, 3)
        assert s != "1.234567"
