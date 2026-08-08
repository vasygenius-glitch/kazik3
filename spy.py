"""Управление списком «шпионских» чатов: Firestore + локальный кэш с TTL."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Set, List, Tuple

from google.cloud.firestore import async_transactional

from db import get_db

logger = logging.getLogger(__name__)

_COLLECTION = "bot_settings"
_DOCUMENT = "spy_chats"
_CACHE_TTL = 60.0  # сек; 0 — отключить кэш

_lock = asyncio.Lock()
_chats: Optional[Set[int]] = None
_spy_all: bool = False
_loaded_at: float = 0.0


# ---------- вспомогательное ----------

def _doc_ref():
    return get_db().collection(_COLLECTION).document(_DOCUMENT)


def _snapshot_data(snap) -> dict:
    return (snap.to_dict() or {}) if getattr(snap, "exists", False) else {}


def _parse_chats(raw) -> Set[int]:
    chats: Set[int] = set()
    for item in raw or []:
        try:
            chats.add(int(item))
        except (TypeError, ValueError):
            logger.warning("spy: некорректный chat_id в БД: %r", item)
    return chats


def _store(data: dict) -> None:
    global _chats, _spy_all, _loaded_at
    _chats = _parse_chats(data.get("chats"))
    _spy_all = bool(data.get("spy_all", False))
    _loaded_at = time.monotonic()


def _cache_valid() -> bool:
    return _chats is not None and (time.monotonic() - _loaded_at) < _CACHE_TTL


def invalidate_cache() -> None:
    """Сбросить кэш (например, по внешнему событию/админ-команде)."""
    global _chats, _loaded_at
    _chats = None
    _loaded_at = 0.0


async def _ensure_loaded(force: bool = False) -> None:
    if not force and _cache_valid():
        return
    async with _lock:                      # double-checked locking
        if not force and _cache_valid():
            return
        snap = await _doc_ref().get()
        _store(_snapshot_data(snap))


# ---------- чтение ----------

async def get_spy_chats() -> List[int]:
    """Список чатов со включённой слежкой (копия, безопасно мутировать)."""
    await _ensure_loaded()
    return sorted(_chats or ())


async def is_spy_all_enabled() -> bool:
    await _ensure_loaded()
    return _spy_all


async def is_spy_enabled(chat_id: int) -> bool:
    """Удобный O(1)-хелпер: глобальный режим или конкретный чат."""
    await _ensure_loaded()
    return _spy_all or int(chat_id) in (_chats or ())


# ---------- запись (атомарно, в транзакции) ----------

@async_transactional
async def _toggle_chat_tx(transaction, doc_ref, chat_id: int) -> Tuple[bool, Set[int], bool]:
    data = _snapshot_data(await doc_ref.get(transaction=transaction))
    chats = _parse_chats(data.get("chats"))
    enabled = chat_id not in chats
    if enabled:
        chats.add(chat_id)
    else:
        chats.discard(chat_id)
    transaction.set(doc_ref, {"chats": sorted(chats)}, merge=True)
    return enabled, chats, bool(data.get("spy_all", False))


@async_transactional
async def _toggle_all_tx(transaction, doc_ref) -> Tuple[bool, Set[int]]:
    data = _snapshot_data(await doc_ref.get(transaction=transaction))
    new_state = not bool(data.get("spy_all", False))
    transaction.set(doc_ref, {"spy_all": new_state}, merge=True)
    return new_state, _parse_chats(data.get("chats"))


async def toggle_spy(chat_id: int) -> bool:
    """Переключить слежку для чата. Возвращает новое состояние."""
    global _chats, _spy_all, _loaded_at
    chat_id = int(chat_id)
    db = get_db()
    try:
        enabled, chats, spy_all = await _toggle_chat_tx(db.transaction(), _doc_ref(), chat_id)
    except Exception:
        logger.exception("spy: не удалось переключить слежку для чата %s", chat_id)
        invalidate_cache()
        raise
    _chats, _spy_all, _loaded_at = chats, spy_all, time.monotonic()
    return enabled


async def toggle_spy_all() -> bool:
    """Переключить глобальный режим слежки. Возвращает новое состояние."""
    global _chats, _spy_all, _loaded_at
    db = get_db()
    try:
        new_state, chats = await _toggle_all_tx(db.transaction(), _doc_ref())
    except Exception:
        logger.exception("spy: не удалось переключить глобальную слежку")
        invalidate_cache()
        raise
    _chats, _spy_all, _loaded_at = chats, new_state, time.monotonic()
    return new_state
