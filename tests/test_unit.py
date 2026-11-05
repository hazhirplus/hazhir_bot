import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from panel import (bytes_to_gb, days_to_ms, decode_sub_links, derive_status,
                   gb_to_bytes, gen_email, gen_subid, ms_to_days_left)
import config


def test_days_to_ms():
    assert days_to_ms(30) == 30 * 86400 * 1000
    assert days_to_ms(1) == 86400000


def test_gb_to_bytes():
    assert gb_to_bytes(10) == 10 * 1024 ** 3
    assert gb_to_bytes(0) == 0


def test_bytes_to_gb():
    assert bytes_to_gb(10 * 1024 ** 3) == 10.0


def test_gen_subid():
    s = gen_subid()
    assert re.fullmatch(r"[0-9a-f]{16}", s), s
    assert gen_subid() != gen_subid()


def test_gen_email_username():
    e = gen_email("testuser", 123)
    assert re.fullmatch(r"testuser_\d{4}", e), e


def test_gen_email_fallback_no_username():
    e = gen_email(None, 123456789)
    assert re.fullmatch(r"id123456789_\d{4}", e), e
    e2 = gen_email("", 99)
    assert e2.startswith("id99_")


def test_gen_email_sanitizes():
    e = gen_email("a$b!c@x", 1)
    assert "$" not in e and "!" not in e and "@" not in e
    assert e.startswith("abcx_")


def _client(**kw):
    base = {"enable": True, "totalGB": 10 * 1024 ** 3,
            "expiryTime": (int(time.time()) + 86400) * 1000}
    base.update(kw)
    return base


def test_derive_active():
    assert derive_status(_client(), {"up": 100, "down": 200}) == "active"


def test_derive_disabled():
    assert derive_status(_client(enable=False), {"up": 0, "down": 0}) == "disabled"


def test_derive_limited():
    c = _client(totalGB=1000)
    assert derive_status(c, {"up": 600, "down": 400}) == "limited"
    assert derive_status(c, {"up": 600, "down": 401}) == "limited"


def test_derive_expired():
    c = _client(expiryTime=(int(time.time()) - 3600) * 1000)
    assert derive_status(c, {"up": 0, "down": 0}) == "expired"


def test_derive_unlimited_is_active():
    c = _client(totalGB=0, expiryTime=0)
    assert derive_status(c, {"up": 10 ** 12, "down": 0}) == "active"


def test_derive_limited_beats_expiry_order():
    # limited checked before expired (matches panel semantics: quota first)
    c = _client(totalGB=100, expiryTime=(int(time.time()) - 10) * 1000)
    assert derive_status(c, {"up": 60, "down": 50}) == "limited"


def test_decode_sub_links_base64():
    raw_links = "vless://aaa@1.2.3.4:443?x=1#n1\nvless://bbb@1.2.3.4:443?x=2#n2"
    import base64
    enc = base64.b64encode(raw_links.encode()).decode()
    out = decode_sub_links(enc)
    assert out == ["vless://aaa@1.2.3.4:443?x=1#n1", "vless://bbb@1.2.3.4:443?x=2#n2"]


def test_decode_sub_links_plain():
    out = decode_sub_links("vless://aaa@h:443#n1\nnotalink\n")
    assert out == ["vless://aaa@h:443#n1"]


def test_decode_sub_links_empty():
    assert decode_sub_links("") == []
    assert decode_sub_links("   ") == []


def test_ms_to_days_left():
    now = int(time.time())
    assert ms_to_days_left((now + 3 * 86400) * 1000, now) == 3
    assert ms_to_days_left(0) is None


def test_mask_token():
    assert config.mask_token("abcdefghij") == "…ghij"
    assert config.mask_token("") == "—"
    assert "abcdef" not in config.mask_token("abcdefghij")
