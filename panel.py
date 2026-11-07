"""Async client for the 3x-ui panel API (clean-room implementation).

Verified contracts (3x-ui v3.x):
  - base: {PANEL_URL}/panel/api ; auth: Authorization: Bearer <admin-scope token>
  - bad token -> 401 ; no token (non-XHR) -> 404 by design
  - expiryTime: milliseconds (0 = unlimited) ; totalGB: BYTES (0 = unlimited)
  - subId: 16 hex chars ; success envelope: {"success": true, ...}
"""
from __future__ import annotations
import base64
import random
import re
import secrets
import time

import httpx


class PanelError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code  # auth | notfound | timeout | unreachable | api | error

    @property
    def is_not_found(self) -> bool:
        """True when the panel says the record does not exist.

        3x-ui reports a missing client as success:false with
        msg "Obtain (record not found)" (code "api"), or as HTTP 404
        (code "notfound"). Either way the account is gone from the
        panel, which callers must treat differently from a transient
        failure: retrying every hour only spams the log.
        """
        return self.code == "notfound" or "not found" in str(self).lower()


# ---------------- pure helpers (unit-testable) ----------------
def days_to_ms(days: int) -> int:
    return int(days) * 86400 * 1000


def gb_to_bytes(gb) -> int:
    """GB (int or float, e.g. 0.5) -> bytes. Must NOT int() before multiply."""
    return int(round(float(gb) * 1024 ** 3))


def bytes_to_gb(b: int) -> float:
    return round(b / 1024 ** 3, 1)


def gen_subid() -> str:
    return secrets.token_hex(8)


def gen_email(username: str | None, tg_id: int) -> str:
    """Service username = telegram username + random 4 digits (fallback: id<tgid>)."""
    base = re.sub(r"[^A-Za-z0-9_]", "", (username or ""))[:20] or f"id{tg_id}"
    return f"{base}_{random.randint(0, 9999):04d}"


def ms_to_days_left(expiry_ms: int, now_s: int | None = None) -> int | None:
    if not expiry_ms or expiry_ms <= 0:
        return None
    now_s = now_s if now_s is not None else int(time.time())
    import math
    return max(0, math.ceil(expiry_ms / 1000 - now_s) // 86400 + (1 if (expiry_ms / 1000 - now_s) % 86400 else 0))


def derive_status(client: dict, traffic: dict | None, now_s: int | None = None) -> str:
    """active | disabled | limited | expired (mirrors panel semantics)."""
    now_s = now_s if now_s is not None else int(time.time())
    if not client.get("enable", True):
        return "disabled"
    total = client.get("totalGB", 0) or 0
    up = (traffic or {}).get("up", 0) or 0
    down = (traffic or {}).get("down", 0) or 0
    if total > 0 and total - (up + down) <= 0:
        return "limited"
    exp_ms = client.get("expiryTime", 0) or 0
    if exp_ms > 0 and exp_ms / 1000 - now_s <= 0:
        return "expired"
    return "active"


def decode_sub_links(raw: str) -> list[str]:
    """Subscription body is usually base64(vless://...\\nvless://...)."""
    raw = (raw or "").strip()
    if not raw:
        return []
    text = raw
    if "://" not in raw.split("\n")[0]:
        try:
            padded = raw + "=" * (-len(raw) % 4)
            text = base64.b64decode(padded).decode("utf-8", errors="ignore")
        except Exception:
            text = raw
    return [ln.strip() for ln in text.splitlines() if "://" in ln]


# ---------------- client ----------------
class PanelClient:
    def __init__(self, base_url: str, token: str, verify: bool = True,
                 timeout: float = 25.0, trust_env: bool = True):
        self.base_url = base_url.rstrip("/")
        self.api = self.base_url + "/panel/api"
        self.token = token
        self.verify = verify
        self.timeout = timeout
        self.trust_env = trust_env

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }

    async def _call(self, method: str, path: str, **kw) -> dict:
        try:
            async with httpx.AsyncClient(verify=self.verify,
                                         timeout=self.timeout,
                                         trust_env=self.trust_env) as c:
                r = await c.request(method, self.api + path,
                                    headers=self._headers(), **kw)
        except httpx.TimeoutException:
            raise PanelError("timeout", code="timeout")
        except httpx.ConnectError:
            raise PanelError("unreachable", code="unreachable")
        except httpx.HTTPError as e:
            raise PanelError(str(e), code="error")
        if r.status_code == 401:
            raise PanelError("bad token", code="auth")
        if r.status_code == 404:
            raise PanelError("not found", code="notfound")
        if r.status_code >= 400:
            raise PanelError(f"http {r.status_code}", code="api")
        try:
            data = r.json()
        except Exception:
            raise PanelError("bad json", code="api")
        if isinstance(data, dict) and data.get("success") is False:
            raise PanelError(str(data.get("msg", "api error")), code="api")
        return data if isinstance(data, dict) else {"obj": data}

    # -- diagnostics -----------------------------------------------------
    async def test_connection(self) -> dict:
        """Return {ok, kind, fa} with a Persian diagnosis."""
        try:
            data = await self._call("GET", "/server/status")
            ok = data.get("success") is True
            return {
                "ok": ok,
                "kind": "ok" if ok else "api",
                "fa": "✅ اتصال به پنل برقرار شد." if ok else "⚠️ پنل پاسخ داد ولی نامعتبر بود.",
            }
        except PanelError as e:
            fa = {
                "auth": "❌ توکن نامعتبر است (401) — توکن admin از Settings ← API بساز.",
                "notfound": "❌ آدرس پنل اشتباه است (404) — آدرس و webBasePath را چک کن.",
                "timeout": "❌ پنل پاسخ نداد (timeout).",
                "unreachable": "❌ اتصال به پنل ممکن نیست — آدرس/پورت را چک کن.",
            }
            return {"ok": False, "kind": e.code,
                    "fa": fa.get(e.code, f"❌ خطای پنل: {e}")}

    # -- server ----------------------------------------------------------
    async def server_status(self) -> dict:
        return await self._call("GET", "/server/status")

    # -- clients ---------------------------------------------------------
    async def add_client(self, inbound_ids: list[int], email: str, total_bytes: int,
                         expiry_ms: int, sub_id: str, tg_id: int = 0,
                         comment: str = "") -> dict:
        payload = {
            "inboundIds": inbound_ids,
            "client": {
                "email": email,
                "totalGB": total_bytes,
                "expiryTime": expiry_ms,
                "enable": True,
                "tgId": tg_id,
                "subId": sub_id,
                "comment": comment,
            },
        }
        return await self._call("POST", "/clients/add", json=payload)

    async def get_client(self, email: str) -> dict | None:
        data = await self._call("GET", f"/clients/get/{email}")
        obj = data.get("obj") or {}
        if isinstance(obj, dict) and "client" in obj and isinstance(obj["client"], dict):
            return obj["client"]
        return obj if isinstance(obj, dict) and obj.get("email") else None

    async def traffic(self, email: str) -> dict:
        data = await self._call("GET", f"/clients/traffic/{email}")
        obj = data.get("obj") or {}
        return obj if isinstance(obj, dict) else {}

    async def update_client(self, email: str, fields: dict) -> dict:
        # the panel requires the email inside the body as well
        body = {"email": email}
        body.update(fields or {})
        return await self._call("POST", f"/clients/update/{email}", json=body)

    async def set_enable(self, email: str, enable: bool) -> dict:
        return await self.update_client(email, {"enable": enable})

    async def revoke_sub(self, email: str) -> str:
        """Rotate the client's subscription id (mirzabot's revokeSub).

        3x-ui has no dedicated revoke endpoint; the verified mechanism is
        updateClient with a fresh 16-hex subId (REVIEW.md API cheat-sheet:
        update/{email} accepts "subId?"). The old sub link stops working
        immediately, so callers must re-deliver the new link to the user.
        Returns the new subId.
        """
        new_sub = gen_subid()
        await self.update_client(email, {"subId": new_sub})
        return new_sub

    async def reset_traffic(self, email: str) -> dict:
        return await self._call("POST", f"/clients/resetTraffic/{email}", json=[])

    async def delete_client(self, email: str) -> dict:
        return await self._call("POST", f"/clients/del/{email}", json={})

    async def attach(self, email: str, inbound_ids: list[int]) -> dict:
        return await self._call("POST", f"/clients/{email}/attach",
                                json={"inboundIds": inbound_ids})

    async def sub_links(self, sub_id: str) -> list[str]:
        """Links via panel API."""
        try:
            data = await self._call("GET", f"/clients/subLinks/{sub_id}")
        except PanelError:
            return []
        obj = data.get("obj")
        links: list[str] = []
        if isinstance(obj, list):
            links = [str(x) for x in obj]
        elif isinstance(obj, dict):
            for k in ("links", "subLinks", "data"):
                v = obj.get(k)
                if isinstance(v, list):
                    links = [str(x) for x in v]
                    break
                if isinstance(v, str) and "://" in v:
                    links = decode_sub_links(v)
                    break
        return [ln for ln in links if "://" in ln]

    async def links(self, email: str) -> list[str]:
        try:
            data = await self._call("GET", f"/clients/links/{email}")
        except PanelError:
            return []
        obj = data.get("obj")
        if isinstance(obj, list):
            return [str(x) for x in obj if "://" in str(x)]
        if isinstance(obj, dict):
            for k in ("links", "data"):
                v = obj.get(k)
                if isinstance(v, list):
                    return [str(x) for x in v if "://" in str(x)]
        return []

    async def fetch_sub_http(self, sub_base: str, sub_id: str) -> list[str]:
        """Direct GET {sub_base}/{sub_id} (no auth) with base64 decode fallback."""
        url = sub_base.rstrip("/") + "/" + sub_id
        try:
            async with httpx.AsyncClient(verify=self.verify,
                                         timeout=self.timeout,
                                         trust_env=self.trust_env) as c:
                r = await c.get(url)
        except httpx.HTTPError:
            return []
        if r.status_code != 200:
            return []
        return decode_sub_links(r.text)
