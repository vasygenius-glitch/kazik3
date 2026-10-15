"""Per-chat persistent switch. Off until explicitly enabled by the creator."""
import asyncio
import time
from db import get_db

_cache = {}
_locks = {}


def switch_lock(chat_id):
    return _locks.setdefault(chat_id, asyncio.Lock())


async def enabled(chat_id):
    cached = _cache.get(chat_id)
    if cached and time.monotonic() - cached[1] < 30:
        return cached[0]
    doc = await get_db().collection("bot_settings").document(f"economy_v2_{chat_id}").get()
    value = bool((doc.to_dict() or {}).get("enabled", False)) if doc.exists else False
    _cache[chat_id] = (value, time.monotonic())
    return value


async def set_enabled(chat_id, value, actor):
    await get_db().collection("bot_settings").document(f"economy_v2_{chat_id}").set({
        "enabled": bool(value), "changed_by": actor, "changed_at": int(time.time()), "schema": 1,
    }, merge=True)
    _cache[chat_id] = (bool(value), time.monotonic())
