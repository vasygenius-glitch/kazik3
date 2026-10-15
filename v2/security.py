"""Проверка Telegram initData, подписанные токены чата и анонимные хэндлы игроков.

Фронтенд никогда не получает Telegram ID: игроки видны только как имя, аватар
и непрозрачный хэндл (HMAC от ID), которые нельзя превратить обратно в ID.
"""
import base64
import hashlib
import hmac
import json
import time
from collections import deque
from urllib.parse import parse_qsl

from aiogram.utils.web_app import check_webapp_signature

from config import BOT_TOKEN
from v2.conf import INIT_DATA_MAX_AGE

_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"
_handles: dict[str, int] = {}


def _key(purpose: str) -> bytes:
    return hmac.new(b"kazik-v2:" + purpose.encode(), BOT_TOKEN.encode(), hashlib.sha256).digest()


def _sig(purpose: str, payload: str, size: int) -> str:
    raw = hmac.new(_key(purpose), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")[:size].replace("-", "x").replace("_", "y")


def _b36(n: int) -> str:
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = _B36[r] + out
        if not n:
            return out


def verify_init_data(init_data: str, now: float | None = None) -> dict | None:
    """Возвращает {'user': {...}, 'start_param': ..., 'auth_date': ...} или None."""
    if not init_data or len(init_data) > 4096 or not BOT_TOKEN:
        return None
    try:
        if not check_webapp_signature(BOT_TOKEN, init_data):
            return None
        data = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        user = json.loads(data.get("user") or "null")
        auth_date = int(data.get("auth_date") or 0)
    except (ValueError, TypeError):
        return None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        return None
    now = time.time() if now is None else now
    if auth_date <= 0 or now - auth_date > INIT_DATA_MAX_AGE or auth_date - now > 300:
        return None
    return {
        "user": user,
        "start_param": data.get("start_param") or "",
        "chat_type": data.get("chat_type") or "",
        "auth_date": auth_date,
    }


def chat_token(chat_id: int) -> str:
    """Токен для startapp/start: только [A-Za-z0-9], подпись не даёт подменить чат."""
    body = ("g" if chat_id < 0 else "p") + _b36(abs(int(chat_id)))
    return f"{body}{_sig('chat', body, 14)}"


def parse_chat_token(token: str) -> int | None:
    token = (token or "").strip()
    if token.startswith("v2_"):
        token = token[3:]
    if len(token) < 16 or len(token) > 64 or token[0] not in "gp":
        return None
    body, sig = token[:-14], token[-14:]
    if not hmac.compare_digest(sig, _sig("chat", body, 14)):
        return None
    try:
        value = int(body[1:], 36)
    except ValueError:
        return None
    return -value if body[0] == "g" else value


def handle_for(user_id: int) -> str:
    h = "h" + _sig("handle", str(int(user_id)), 12)
    _handles[h] = int(user_id)
    return h


def user_for_handle(handle: str) -> int | None:
    return _handles.get(handle or "")


class RateLimiter:
    """Простое скользящее окно по ключу: защищает от авто-кликеров."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self.hits: dict = {}

    def allow(self, key) -> bool:
        now = time.monotonic()
        q = self.hits.get(key)
        if q is None:
            if len(self.hits) > 5000:
                self.hits.clear()
            q = self.hits[key] = deque()
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
