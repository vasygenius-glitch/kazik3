"""Казик V2: подпись Telegram initData, токены чата, анонимные хэндлы, лимитер."""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlencode

import pytest

from config import BOT_TOKEN
from v2 import security
from v2.conf import INIT_DATA_MAX_AGE


def _init_data(user=None, auth_date=None, token=BOT_TOKEN, drop_user=False, **extra):
    """initData по спецификации Telegram: secret = HMAC("WebAppData", token)."""
    params = {"auth_date": str(int(time.time() if auth_date is None else auth_date)), "query_id": "AAHtest"}
    if not drop_user:
        params["user"] = json.dumps(user or {"id": 4242, "first_name": "Груздь", "photo_url": "https://t.me/i/u.jpg"},
                                    ensure_ascii=False, separators=(",", ":"))
    params.update({k: str(v) for k, v in extra.items()})
    check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


def test_init_data_valid():
    token = security.chat_token(-1001234567890)
    d = security.verify_init_data(_init_data(start_param=token, chat_type="supergroup"))
    assert d is not None
    assert d["user"]["id"] == 4242 and d["user"]["first_name"] == "Груздь"
    assert d["start_param"] == token and d["chat_type"] == "supergroup"


def test_init_data_tampered_user_rejected():
    raw = _init_data()
    assert "4242" in raw
    assert security.verify_init_data(raw.replace("4242", "4243")) is None


def test_init_data_tampered_start_param_rejected():
    good = security.chat_token(-100111)
    raw = _init_data(start_param=good)
    forged = raw.replace(good, security.chat_token(-100222))
    assert security.verify_init_data(forged) is None


def test_init_data_foreign_bot_rejected():
    assert security.verify_init_data(_init_data(token="987654321:" + "X" * 35)) is None


@pytest.mark.parametrize("shift", [INIT_DATA_MAX_AGE + 60, -3600])
def test_init_data_expired_or_future_rejected(shift):
    assert security.verify_init_data(_init_data(auth_date=time.time() - shift)) is None


def test_init_data_without_user_rejected():
    assert security.verify_init_data(_init_data(drop_user=True)) is None


@pytest.mark.parametrize("raw", ["", "hash=abc", "a" * 5000, "user=%7B%7D&auth_date=1&hash=00"])
def test_init_data_garbage_rejected(raw):
    assert security.verify_init_data(raw) is None


@pytest.mark.parametrize("chat_id", [-1001234567890, -42, -1, 777, 5_000_000_000])
def test_chat_token_roundtrip(chat_id):
    token = security.chat_token(chat_id)
    assert re.fullmatch(r"[A-Za-z0-9]+", token), token
    assert len("v2_" + token) <= 64  # лимит deep-link /start
    assert security.parse_chat_token(token) == chat_id
    assert security.parse_chat_token("v2_" + token) == chat_id
    assert security.parse_chat_token(f"  {token} ") == chat_id


def test_chat_token_tamper_rejected():
    token = security.chat_token(-1001234567890)
    flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert security.parse_chat_token(flipped) is None
    # другой чат с подписью от первого
    other = security.chat_token(-1009999999999)
    assert security.parse_chat_token(other[:-14] + token[-14:]) is None
    # знак чата нельзя поменять, переписав префикс
    assert security.parse_chat_token("p" + token[1:]) is None


@pytest.mark.parametrize("raw", ["", "g", "gzz", "x" * 20, "g" + "!" * 20, None, "v2_", "q" + "a" * 30])
def test_chat_token_garbage(raw):
    assert security.parse_chat_token(raw) is None


def test_chat_token_depends_on_bot_token(monkeypatch):
    token = security.chat_token(-100555)
    monkeypatch.setattr(security, "BOT_TOKEN", "111:" + "Z" * 35)
    assert security.parse_chat_token(token) is None


def test_handles_are_opaque_and_stable():
    uid = 918273645
    h = security.handle_for(uid)
    assert h == security.handle_for(uid) and h.startswith("h")
    assert str(uid) not in h
    assert h != security.handle_for(uid + 1)
    assert security.user_for_handle(h) == uid
    assert security.user_for_handle("hnope") is None and security.user_for_handle("") is None


def test_rate_limiter(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: clock[0])
    lim = security.RateLimiter(3, 5.0)
    assert all(lim.allow("u") for _ in range(3))
    assert not lim.allow("u")
    assert lim.allow("other")
    clock[0] += 5.1
    assert lim.allow("u")
