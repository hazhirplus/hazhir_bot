"""Integration tests against a LOCAL 3x-ui sandbox panel.

Run only when PANEL_TEST_URL and PANEL_TEST_TOKEN are set, e.g.:
  PANEL_TEST_URL=http://127.0.0.1:20999 PANEL_TEST_TOKEN=<token> pytest tests/test_integration.py

NEVER point these at a real/production panel.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from panel import PanelClient, PanelError, derive_status  # noqa: E402

URL = os.environ.get("PANEL_TEST_URL", "")
TOKEN = os.environ.get("PANEL_TEST_TOKEN", "")

needs_panel = pytest.mark.skipif(not URL or not TOKEN,
                                 reason="PANEL_TEST_URL/TOKEN not set")

EMAIL = "pytest_sandbox_01"
SUBID = "a1b2c3d4e5f60718"


def _client() -> PanelClient:
    # local sandbox is plain HTTP -> verify off (production uses verify=True);
    # trust_env off: this dev VM's no_proxy contains bracketed IPv6 httpx can't parse
    return PanelClient(URL, TOKEN, verify=False, timeout=20, trust_env=False)


@needs_panel
@pytest.mark.asyncio
async def test_connection_ok():
    pc = _client()
    res = await pc.test_connection()
    assert res["ok"], res


@needs_panel
@pytest.mark.asyncio
async def test_bad_token_gives_401():
    pc = PanelClient(URL, "wrong-token", verify=False, timeout=10, trust_env=False)
    res = await pc.test_connection()
    assert not res["ok"] and res["kind"] == "auth", res


@needs_panel
@pytest.mark.asyncio
async def test_client_lifecycle():
    pc = _client()
    # pick an existing inbound
    data = await pc._call("GET", "/inbounds/list")
    obj = data.get("obj") or []
    assert obj, "sandbox panel has no inbounds to attach to"
    inb_id = obj[0]["id"]

    # cleanup from previous runs (best effort)
    try:
        await pc.delete_client(EMAIL)
    except PanelError:
        pass

    # add
    await pc.add_client([inb_id], EMAIL, 1 * 1024 ** 3,
                        int(time.time() * 1000) + 86400000, SUBID,
                        tg_id=4242, comment="pytest")
    c = await pc.get_client(EMAIL)
    assert c is not None and c["email"] == EMAIL
    assert c["subId"] == SUBID

    # traffic shape
    t = await pc.traffic(EMAIL)
    assert "up" in t and "down" in t

    # status derivation on live data
    assert derive_status(c, t) == "active"

    # disable -> enable
    await pc.set_enable(EMAIL, False)
    c = await pc.get_client(EMAIL)
    assert c["enable"] is False
    assert derive_status(c, t) == "disabled"
    await pc.set_enable(EMAIL, True)

    # reset traffic
    await pc.reset_traffic(EMAIL)

    # sub links (list type, may be empty on fresh client)
    links = await pc.sub_links(SUBID)
    assert isinstance(links, list)

    # delete + verify gone
    await pc.delete_client(EMAIL)
    try:
        gone = await pc.get_client(EMAIL)
    except PanelError:
        gone = None
    assert gone is None
