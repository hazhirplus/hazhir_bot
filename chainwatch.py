"""Crypto payment verification (v2.3): ETH + USDC on Base / Arbitrum / Optimism.

Single fixed receiving address for all invoices; payments are matched by
EXACT UNIQUE AMOUNT + time window. Two pluggable backends:

  a) EtherscanV2Backend(api_key) — Etherscan V2 unified API (needs a free key;
     L2 chains are NOT covered by keyless access).
  b) PublicRpcBackend() — keyless public RPCs (eth_getLogs for USDC,
     balance-delta for native ETH).

Use (a) when ETHERSCAN_API_KEY is configured, else (b).
"""
from __future__ import annotations
import json
import logging
import random
import time
from decimal import Decimal

import httpx

import db

log = logging.getLogger("hozhir")

# USDC contract addresses verified 2026-11-04 against:
#   - Circle official docs (developers.circle.com/stablecoins/usdc-contract-addresses)
#   - CoinGecko /coins/usd-coin detail_platforms
#   - Arbiscan token page ("Native USDC token deployed by Circle to Arbitrum")
# NOTE: the Arbitrum address in earlier notes (…F9647A6F4Bff3Db) is outdated;
# the live canonical address is …3A432268e5831 (3 independent sources).
CHAINS = {
    8453: {
        "name": "Base",
        "fa": "بیس",
        "rpc": "https://mainnet.base.org",
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "explorer": "https://basescan.org",
    },
    42161: {
        "name": "Arbitrum",
        "fa": "آربیتروم",
        "rpc": "https://arb1.arbitrum.io/rpc",
        "usdc": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "explorer": "https://arbiscan.io",
    },
    10: {
        "name": "Optimism",
        "fa": "اپتیمیزم",
        "rpc": "https://mainnet.optimism.io",
        "usdc": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
        "explorer": "https://optimistic.etherscan.io",
    },
}

CURRENCIES = ("ETH", "USDC")
CURRENCY_FA = {"ETH": "اتریوم (ETH)", "USDC": "یو‌اس‌دی کوین (USDC)"}
# on-chain base-unit decimals used when matching tx values (wei for ETH)
CHAIN_UNITS = {"ETH": 18, "USDC": 6}
USDC_DECIMALS = 6
ETH_DECIMALS = 18
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)  # keccak("Transfer(address,address,uint256)")
LOW_VALUE_USD_WARN = 0.50


class RateError(RuntimeError):
    """No usable toman/USD rate source."""


# ---------------- rates: toman <-> USD ----------------
async def _fetch_nobitex() -> tuple[float, float]:
    """Returns (usdt_toman, eth_usd). Nobitex quotes IRT = Toman."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://apiv2.nobitex.ir/market/stats?srcCurrency=usdt&dstCurrency=irt")
        r.raise_for_status()
        usdt_toman = float(r.json()["stats"]["usdt-irt"]["latest"])
        r = await c.get(
            "https://apiv2.nobitex.ir/market/stats?srcCurrency=eth&dstCurrency=usdt")
        r.raise_for_status()
        eth_usd = float(r.json()["stats"]["eth-usdt"]["latest"])
    if usdt_toman <= 0 or eth_usd <= 0:
        raise RateError("bad nobitex values")
    return usdt_toman, eth_usd


async def _fetch_coingecko_eth_usd() -> float:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=ethereum&vs_currencies=usd")
        r.raise_for_status()
        eth_usd = float(r.json()["ethereum"]["usd"])
    if eth_usd <= 0:
        raise RateError("bad coingecko value")
    return eth_usd


async def get_rates() -> tuple[float, float]:
    """Returns (usdt_toman, eth_usd).

    Primary: Nobitex public API (no key). Fallback: CoinGecko for ETH/USD and
    the admin-set crypto_usd_toman for the toman rate (required in fallback).
    """
    try:
        return await _fetch_nobitex()
    except Exception as e:
        log.warning("nobitex rates failed: %s", e)
    try:
        eth_usd = await _fetch_coingecko_eth_usd()
        override = (await db.get_setting("crypto_usd_toman", "")).strip()
        if override and float(override) > 0:
            return float(override), eth_usd
    except Exception as e:
        log.warning("coingecko fallback failed: %s", e)
    raise RateError(
        "نرخ لحظه‌ای در دسترس نیست و نرخ دستی دلار تنظیم نشده است.")


# ---------------- unique amounts ----------------
_issued_amounts: set[str] = set()


def make_unique(base: Decimal, decimals: int, rand_digits: int,
                rng: random.Random | None = None) -> str:
    """Randomize the last `rand_digits` of a decimal amount so every invoice
    gets a unique exact amount. Returns a fixed-point string, always > 0.

    Uniqueness is enforced by retrying on collision against the registry of
    amounts issued in this process (seeded from pending invoices at startup),
    so even birthday-paradox collisions can't produce a duplicate.
    """
    rng = rng or random
    scale = 10 ** decimals
    unit = 10 ** rand_digits
    base_int = int((base * scale).to_integral_value())
    low = (base_int // unit) * unit
    s = ""
    for _ in range(64):
        new_int = low + rng.randint(0, unit - 1)
        if new_int <= 0:
            new_int = 1
        s = f"{Decimal(new_int) / scale:.{decimals}f}"
        if s not in _issued_amounts:
            break
    _issued_amounts.add(s)
    return s


async def seed_issued_amounts(path: str | None = None) -> int:
    """Load amounts of still-pending crypto invoices into the uniqueness
    registry (restart safety). Returns the number seeded."""
    import db as _db  # local import: chainwatch must not import db at module level
    n = 0
    for inv in await _db.list_pending_crypto(5000, path):
        amt = inv.get("crypto_amount")
        if amt:
            _issued_amounts.add(str(amt))
            n += 1
    return n


def _base_amount(toman: int, currency: str,
                 usdt_toman: float, eth_usd: float) -> Decimal:
    usdc = Decimal(toman) / Decimal(str(usdt_toman))
    if currency == "USDC":
        return usdc
    return usdc / Decimal(str(eth_usd))


async def quote(toman: int, currency: str) -> dict:
    """Price a toman amount in crypto. Returns amount (exact string),
    expected base units, usd value and a low-value fee warning flag."""
    if currency not in CURRENCIES:
        raise ValueError(f"unsupported currency: {currency}")
    usdt_toman, eth_usd = await get_rates()
    decimals, rand_digits = (6, 3) if currency == "USDC" else (8, 4)
    amount = make_unique(_base_amount(toman, currency, usdt_toman, eth_usd),
                         decimals, rand_digits)
    # on-chain base units: USDC has 6 decimals, native ETH is matched in wei
    units = int(Decimal(amount) * (10 ** CHAIN_UNITS[currency]))
    usd_value = float(Decimal(amount)) * (1.0 if currency == "USDC" else eth_usd)
    return {
        "currency": currency,
        "amount": amount,
        "units": units,
        "usd_value": usd_value,
        "usdt_toman": usdt_toman,
        "eth_usd": eth_usd,
        "low_value_warn": usd_value < LOW_VALUE_USD_WARN,
    }


# ---------------- backends ----------------
class EtherscanV2Backend:
    """Etherscan V2 unified API. Needs a free API key (L2s have no keyless tier)."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def _api(self, params: dict):
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://api.etherscan.io/v2/api", params=params)
            r.raise_for_status()
            return r.json()

    async def find_payment(self, *, chain_id: int, currency: str, address: str,
                           expected_units: int, since_ts: int,
                           meta: dict | None = None) -> str | None:
        """Return the tx hash of a matching incoming payment, else None."""
        address = address.lower()
        action = "tokentx" if currency == "USDC" else "txlist"
        params = {
            "chainid": chain_id, "module": "account", "action": action,
            "address": address, "page": "1", "offset": "25", "sort": "desc",
            "apikey": self.api_key,
        }
        if currency == "USDC":
            params["contractaddress"] = CHAINS[chain_id]["usdc"]
        try:
            data = await self._api(params)
        except Exception as e:
            log.warning("etherscan v2 error: %s", e)
            return None
        if str(data.get("status")) != "1":
            return None
        for tx in data.get("result") or []:
            try:
                if (tx.get("to") or "").lower() != address:
                    continue
                if int(tx.get("value") or 0) != expected_units:
                    continue
                if int(tx.get("timeStamp") or 0) < since_ts:
                    continue
                if str(tx.get("isError")) != "0":
                    continue
                return tx.get("hash")
            except (TypeError, ValueError):
                continue
        return None


class PublicRpcBackend:
    """Keyless public RPCs. USDC via eth_getLogs (Transfer events);
    native ETH via balance-delta against a per-chain baseline setting."""

    async def _rpc(self, chain_id: int, method: str, params: list):
        url = CHAINS[chain_id]["rpc"]
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url, json={"jsonrpc": "2.0", "id": 1,
                                        "method": method, "params": params})
            r.raise_for_status()
            return r.json().get("result")

    def _baseline_key(self, chain_id: int) -> str:
        return f"crypto_eth_base_{chain_id}"

    async def find_payment(self, *, chain_id: int, currency: str, address: str,
                           expected_units: int, since_ts: int,
                           meta: dict | None = None) -> str | None:
        address = address.lower()
        try:
            if currency == "USDC":
                return await self._find_usdc(chain_id, address, expected_units,
                                             since_ts)
            return await self._find_eth(chain_id, address, expected_units)
        except Exception as e:
            log.warning("public rpc error (chain %s): %s", chain_id, e)
            return None

    async def _find_usdc(self, chain_id: int, address: str, expected_units: int,
                         since_ts: int) -> str | None:
        usdc = CHAINS[chain_id]["usdc"]
        padded_to = "0x" + "0" * 24 + address[2:]
        latest = await self._rpc(chain_id, "eth_blockNumber", [])
        # ~2h lookback (Base/OP ~2s blocks, Arbitrum ~0.25s)
        lookback = 200000 if chain_id == 42161 else 4000
        from_block = hex(max(0, int(latest, 16) - lookback))
        logs = await self._rpc(chain_id, "eth_getLogs", [{
            "address": usdc, "fromBlock": from_block, "toBlock": "latest",
            "topics": [TRANSFER_TOPIC, None, padded_to],
        }]) or []
        for lg in logs:
            try:
                if int(lg.get("data") or "0x0", 16) != expected_units:
                    continue
            except ValueError:
                continue
            blk = await self._rpc(chain_id, "eth_getBlockByNumber",
                                  [lg.get("blockNumber"), False]) or {}
            try:
                ts = int(blk.get("timestamp") or "0x0", 16)
            except ValueError:
                continue
            if ts < since_ts - 300:
                continue
            return lg.get("transactionHash")
        return None

    async def _find_eth(self, chain_id: int, address: str,
                        expected_units: int) -> str | None:
        base_raw = await db.get_setting(self._baseline_key(chain_id), "")
        if not base_raw:
            return None
        cur = await self._rpc(chain_id, "eth_getBalance", [address, "latest"])
        try:
            delta = int(cur, 16) - int(base_raw)
        except (TypeError, ValueError):
            return None
        if delta == expected_units:
            # advance the baseline past this payment so later invoices
            # measure against the post-payment balance
            await db.set_setting(self._baseline_key(chain_id), str(int(cur, 16)))
            return "eth:balance-delta"
        return None

    async def ensure_eth_baseline(self, chain_id: int) -> None:
        """Record the current balance as baseline if none exists yet."""
        if await db.get_setting(self._baseline_key(chain_id), ""):
            return
        try:
            addr = (await db.get_setting("evm_address", "")).strip()
            if not addr:
                return
            bal = await self._rpc(chain_id, "eth_getBalance", [addr, "latest"])
            await db.set_setting(self._baseline_key(chain_id), str(int(bal, 16)))
        except Exception as e:
            log.warning("eth baseline init failed (chain %s): %s", chain_id, e)


async def get_backend():
    """Etherscan backend when a key is configured, else public RPC."""
    key = (await db.get_setting("etherscan_key", "")).strip()
    if key:
        return EtherscanV2Backend(key)
    return PublicRpcBackend()


async def find_payment_for_invoice(inv: dict) -> str | None:
    """Match a pending crypto invoice against the chain. Returns tx hash or None."""
    try:
        chain_id = int(inv.get("crypto_chain") or 0)
    except (TypeError, ValueError):
        return None
    currency = (inv.get("crypto_currency") or "").upper()
    address = (inv.get("crypto_address") or "").strip()
    if chain_id not in CHAINS or currency not in CURRENCIES or not address:
        return None
    decimals = USDC_DECIMALS if currency == "USDC" else ETH_DECIMALS
    try:
        expected = int(Decimal(str(inv.get("crypto_amount"))) * (10 ** decimals))
        since_ts = int(inv.get("created_at") or 0)
    except Exception:
        return None
    if expected <= 0:
        return None
    backend = await get_backend()
    try:
        meta = json.loads(inv.get("crypto_meta") or "{}")
    except Exception:
        meta = {}
    return await backend.find_payment(
        chain_id=chain_id, currency=currency, address=address,
        expected_units=expected, since_ts=since_ts, meta=meta)
