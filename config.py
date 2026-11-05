"""Environment-based configuration. Secrets live ONLY in env vars, never in code/db."""
from __future__ import annotations
import os


def _get(name: str, default: str = "", required: bool = False) -> str:
    v = os.environ.get(name, default)
    if required and not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


def _int_list(raw: str) -> list[int]:
    out: list[int] = []
    for x in raw.split(","):
        x = x.strip()
        if x.lstrip("-").isdigit():
            out.append(int(x))
    return out


BOT_TOKEN: str = _get("BOT_TOKEN", required=True)
PANEL_URL: str = _get("PANEL_URL", "").rstrip("/")
PANEL_TOKEN: str = _get("PANEL_TOKEN", "")
ADMIN_IDS: list[int] = _int_list(_get("ADMIN_IDS", ""))
CARD_NUMBER: str = _get("CARD_NUMBER", "").replace(" ", "")
CARD_HOLDER: str = _get("CARD_HOLDER", "")
SUB_BASE: str = _get("SUB_BASE", "").rstrip("/")
INBOUNDS: list[int] = _int_list(_get("INBOUNDS", ""))
DB_PATH: str = _get("DB_PATH", "data/hozhir.db")
# Crypto rail (v2.3): EVM receiving address is PUBLIC (like a card number).
# NEVER put a private key / seed phrase anywhere near this codebase.
# No address is baked in by default — set EVM_ADDRESS in env.
EVM_ADDRESS: str = _get("EVM_ADDRESS", "")
ETHERSCAN_API_KEY: str = _get("ETHERSCAN_API_KEY", "")


def is_admin(tg_id: int | None) -> bool:
    return bool(tg_id) and tg_id in ADMIN_IDS


def mask_token(token: str) -> str:
    """Show only last 4 chars of a secret."""
    if not token:
        return "—"
    return "…" + token[-4:] if len(token) > 4 else "…"
