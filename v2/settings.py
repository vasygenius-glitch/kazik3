"""Включение V2 и анонсов — отдельно для каждого чата (по умолчанию выключено)."""
import asyncio
import time

from db import get_db

_cache: dict = {}
_locks: dict = {}
TTL = 30


def switch_lock(chat_id):
    return _locks.setdefault(chat_id, asyncio.Lock())


def _ref(chat_id):
    return get_db().collection("bot_settings").document(f"economy_v2_{chat_id}")


async def _load(chat_id) -> dict:
    cached = _cache.get(chat_id)
    if cached and time.monotonic() - cached[1] < TTL:
        return cached[0]
    doc = await _ref(chat_id).get()
    value = (doc.to_dict() or {}) if doc.exists else {}
    _cache[chat_id] = (value, time.monotonic())
    return value


async def enabled(chat_id) -> bool:
    return bool((await _load(chat_id)).get("enabled", False))


async def announce_enabled(chat_id) -> bool:
    return bool((await _load(chat_id)).get("announce", True))


async def _set(chat_id, actor, **fields):
    fields.update(changed_by=actor, changed_at=int(time.time()), schema=2)
    await _ref(chat_id).set(fields, merge=True)
    current = dict((_cache.get(chat_id) or ({}, 0))[0])
    current.update(fields)
    _cache[chat_id] = (current, time.monotonic())


async def set_enabled(chat_id, value, actor):
    await _set(chat_id, actor, enabled=bool(value))


async def set_announce(chat_id, value, actor):
    await _set(chat_id, actor, announce=bool(value))
    from v2 import live
    h = live.peek(chat_id)
    if h is not None:
        h.announce = bool(value)
