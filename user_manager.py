"""
user_manager.py — управление данными пользователей с кэшированием.

Архитектура:
- LRU-кэш в памяти (OrderedDict) с TTL.
- Грязные записи (_dirty_cache) периодически сбрасываются в Firestore пачками.
- Per-user asyncio.Lock защищает от гонок при модификации одной записи.
- Транзакционные операции НЕ трогают кэш: инвалидация должна происходить
  ТОЛЬКО после успешного коммита транзакции (на стороне вызывающего кода),
  иначе можно поймать гонку: пока транзакция ещё не закомитилась в Firestore,
  параллельный запрос вычитает старые данные и положит их обратно в кэш.
"""
from __future__ import annotations

import os
import copy
import time
import asyncio
import logging
from typing import Any, Dict, Optional, Set, Tuple
from collections import OrderedDict

from db import get_db
from utils import fire_and_forget
from admin_logs import log_transaction, check_balance_alert
from game_ai import default_ai_memory

logger = logging.getLogger(__name__)

# ============================================================
# КОНСТАНТЫ
# ============================================================
CACHE_TTL: float = 300.0
MAX_CACHE_SIZE: int = 1000
FLUSH_BATCH_SIZE: int = 100
FLUSH_INTERVAL: float = 15.0
LOCK_CLEANUP_THRESHOLD: int = 2000     # чистим словарь локов, когда вырос

# Денежные пороги
LARGE_TX_THRESHOLD: int = 500_000      # логировать транзакции от этой суммы
DEFAULT_START_BALANCE: int = 500
BASE_BONUS: int = 150

# Кулдауны (сек)
BONUS_COOLDOWN: int = 14400            # 4 часа
DAILY_COOLDOWN: int = 79200            # 22 часа

# Бизнес-параметры
BIZ_COUNT_CAP: int = 10                # максимум одинаковых бизнесов, дающих доход
BIZ_LEVEL_BONUS: float = 0.5           # +50% на каждый уровень

UserKey = Tuple[Any, Any]              # (chat_id, user_id)

# ============================================================
# СТРУКТУРЫ КЭША
# ============================================================
_user_cache: "OrderedDict[UserKey, dict]" = OrderedDict()
_username_to_id_cache: Dict[Tuple[Any, str], Any] = {}
_dirty_cache: Set[UserKey] = set()
class ReentrantLock:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: Optional[asyncio.Task[Any]] = None
        self._count: int = 0

    def locked(self) -> bool:
        return self._lock.locked()

    @property
    def _waiters(self) -> Optional[list]:
        return getattr(self._lock, "_waiters", None)

    async def acquire(self) -> bool:
        current_task = asyncio.current_task()
        if self._owner == current_task:
            self._count += 1
            return True
        await self._lock.acquire()
        self._owner = current_task
        self._count = 1
        return True

    def release(self) -> None:
        current_task = asyncio.current_task()
        if self._owner != current_task:
            raise RuntimeError("Cannot release un-owned lock")
        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self) -> ReentrantLock:
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


_user_locks: Dict[UserKey, ReentrantLock] = {}
_flush_lock = asyncio.Lock()


def _normalize_ids(chat_id, user_id):
    try:
        chat_id = int(chat_id)
    except (ValueError, TypeError):
        pass
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        pass
    return chat_id, user_id


def get_user_ref(chat_id, user_id):
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    db = get_db()
    return (
        db.collection('chats')
        .document(str(chat_id))
        .collection('users')
        .document(str(user_id))
    )


# ============================================================
# ЛОКИ
# ============================================================
def get_user_lock(chat_id, user_id) -> ReentrantLock:
    """
    Возвращает per-user lock. В однопоточном asyncio чтение-и-вставка
    в dict атомарны между await, поэтому отдельной защиты не нужно.
    """
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    return _user_locks.setdefault((chat_id, user_id), ReentrantLock())


# ============================================================
# КЭШ: чтение/запись/инвалидация
# ============================================================
def _remove_username_from_index(chat_id, data: Optional[dict]) -> None:
    if not isinstance(data, dict):
        return
    uname = data.get("username")
    if uname:
        _username_to_id_cache.pop((chat_id, str(uname).lower()), None)


def _drop_cache_entry(key: UserKey) -> None:
    """Удаляет ключ из кэша + чистит username-индекс + dirty-флаг.

    ВНИМАНИЕ: НИКОГДА не вызывайте эту функцию внутри открытой транзакции
    Firestore! Транзакция ещё не закомитилась, а параллельный запрос вычитает
    старые данные из БД и положит их обратно в кэш — получим рассинхрон.
    Инвалидация должна происходить ПОСЛЕ успешного коммита транзакции
    (см. invalidate_user_cache, вызываемую на стороне вызывающего кода).
    """
    entry = _user_cache.pop(key, None)
    if entry:
        _remove_username_from_index(key[0], entry["data"])
    _dirty_cache.discard(key)


def get_from_cache(chat_id, user_id) -> Optional[dict]:
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    key = (chat_id, user_id)
    entry = _user_cache.get(key)
    if entry is None:
        return None

    if time.time() - entry["timestamp"] >= CACHE_TTL:
        if key in _dirty_cache:
            # Если запись грязная — НЕ удаляем и НЕ возвращаем None (чтобы
            # не перетереть актуальные локальные данные устаревшими из БД).
            _user_cache.move_to_end(key)  # LRU
            return copy.deepcopy(entry["data"])
        
        _drop_cache_entry(key)
        return None

    _user_cache.move_to_end(key)  # LRU
    return copy.deepcopy(entry["data"])


def set_in_cache(chat_id, user_id, data: dict) -> None:
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    key = (chat_id, user_id)

    # Сняли старый username из индекса
    old = _user_cache.get(key)
    if old:
        _remove_username_from_index(chat_id, old["data"])

    # Eviction: только если ключа ещё нет и кэш переполнен
    if key not in _user_cache and len(_user_cache) >= MAX_CACHE_SIZE:
        for k in list(_user_cache.keys()):  # порядок = LRU
            if k not in _dirty_cache:
                _drop_cache_entry(k)
                break
        # Если все грязные — позволим временно вырасти, переполнение лучше потери данных.

    _user_cache[key] = {"data": copy.deepcopy(data), "timestamp": time.time()}
    _user_cache.move_to_end(key)

    new_uname = data.get("username")
    if new_uname:
        _username_to_id_cache[(chat_id, str(new_uname).lower())] = user_id


def invalidate_user_cache(chat_id, user_id) -> None:
    """Полная инвалидация: кэш + dirty + FSM-состояния в Redis.

    Вызывайте ЭТУ функцию ПОСЛЕ успешного коммита транзакции Firestore,
    чтобы гарантировать, что следующее чтение пойдёт в БД и подтянет
    актуальные данные.
    """
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    _drop_cache_entry((chat_id, user_id))

    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return

    def _cleanup() -> None:
        try:
            import redis as _redis
            r = _redis.from_url(redis_url, socket_timeout=5)
            try:
                r.delete(
                    f"fsm:{chat_id}:{user_id}:state",
                    f"fsm:{chat_id}:{user_id}:data",
                )
            finally:
                try:
                    r.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error("Redis cleanup error for %s:%s — %s", chat_id, user_id, e)

    try:
        fire_and_forget(asyncio.to_thread(_cleanup))
    except Exception as e:
        logger.error("Failed to schedule redis cleanup: %s", e)


def mark_dirty(chat_id, user_id) -> None:
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    _dirty_cache.add((chat_id, user_id))


async def flush_user_cache_immediately(chat_id, user_id) -> None:
    """Немедленно сбрасывает грязные данные конкретного пользователя в Firestore.
    Используется перед транзакционным чтением, чтобы Firestore-транзакция
    не прочитала устаревшие данные и не перезаписала свежий кэш."""
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    key = (chat_id, user_id)
    if key not in _dirty_cache:
        return
    entry = _user_cache.get(key)
    if not entry:
        _dirty_cache.discard(key)
        return
    _dirty_cache.discard(key)
    try:
        await _flush_single_user(chat_id, user_id, entry["timestamp"])
    except Exception as e:
        logger.error("flush_user_cache_immediately error for %s: %s", key, e)
        _dirty_cache.add(key)  # повторим позже


async def _flush_single_user(chat_id, user_id, expected_timestamp) -> None:
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        entry = _user_cache.get((chat_id, user_id))
        if not entry or entry.get("timestamp") != expected_timestamp:
            return
        ref = get_user_ref(chat_id, user_id)
        await ref.set(entry["data"], merge=True)


# ============================================================
# FLUSH В БД
# ============================================================
_quota_backoff: float = FLUSH_INTERVAL


async def flush_user_data() -> bool:
    """Сбрасывает _dirty_cache в Firestore пачками. Возвращает True, если была поймана квота 429."""
    if not _dirty_cache:
        return False

    if _flush_lock.locked():
        return False

    quota_exceeded_hit = False

    async with _flush_lock:
        to_flush = list(_dirty_cache)
        for i in range(0, len(to_flush), FLUSH_BATCH_SIZE):
            batch = to_flush[i:i + FLUSH_BATCH_SIZE]
            tasks, task_keys = [], []

            for key in batch:
                _dirty_cache.discard(key)
                entry = _user_cache.get(key)
                if not entry:
                    continue

                tasks.append(_flush_single_user(key[0], key[1], entry["timestamp"]))
                task_keys.append(key)

            if not tasks:
                continue

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for key, result in zip(task_keys, results):
                if isinstance(result, Exception):
                    err_str = str(result)
                    if "Quota exceeded" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        quota_exceeded_hit = True
                        logger.warning("⚠️ Квота записи Firestore (429) превышена для %s. Данные сохранены в памяти.", key)
                    else:
                        logger.error("⚠️ Ошибка записи пользователя %s: %s", key, result)
                    _dirty_cache.add(key)  # повторим в следующем тике

    return quota_exceeded_hit


def _cleanup_unused_locks() -> None:
    """Удаляет локи пользователей, которых нет в кэше и которые никем не удерживаются."""
    if len(_user_locks) < LOCK_CLEANUP_THRESHOLD:
        return
    current = set(_user_cache.keys())
    removed = 0
    for key in list(_user_locks.keys()):
        if key in current:
            continue
        lock = _user_locks.get(key)
        if lock is None or lock.locked():
            continue
        waiters = getattr(lock, "_waiters", None)
        if waiters:
            continue
        _user_locks.pop(key, None)
        removed += 1
    if removed:
        logger.debug("Cleaned %s unused user locks (now=%s)", removed, len(_user_locks))


async def flush_user_data_task() -> None:
    """Фоновая периодическая синхронизация + чистка локов с защитой от 429 Quota Exceeded."""
    global _quota_backoff
    while True:
        try:
            await asyncio.sleep(_quota_backoff)
            quota_hit = await flush_user_data()
            if quota_hit:
                _quota_backoff = min(120.0, _quota_backoff * 2)
                logger.warning("⏳ Квота БД (429) исчерпана. Увеличиваем паузу фонового сброса до %.0f сек. Данные игроков в кэше без потерь!", _quota_backoff)
            else:
                _quota_backoff = FLUSH_INTERVAL

            _cleanup_unused_locks()
        except asyncio.CancelledError:
            try:
                await flush_user_data()
            except Exception as e:
                logger.error("Final flush on cancellation error: %s", e)
            break
        except Exception as exc:
            logger.error("Ошибка в фоновой задаче сброса БД: %s", exc)



# ============================================================
# CRUD
# ============================================================
async def get_user_data(chat_id, user_id, full_name: Optional[str] = None, username: Optional[str] = None) -> dict:
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    """
    Возвращает данные пользователя (создаёт дефолт, если нет).
    Защищено от гонок — конкурентные вызовы для одного юзера сериализуются.
    """
    # 1. Быстрая проверка кэша без лока
    cached = get_from_cache(chat_id, user_id)
    if cached is not None:
        updated = False
        if full_name and cached.get('full_name') != full_name:
            cached['full_name'] = full_name
            updated = True
        if username is not None and cached.get('username') != username:
            cached['username'] = username
            updated = True
        if updated:
            set_in_cache(chat_id, user_id, cached)
            mark_dirty(chat_id, user_id)
        return cached

    # 2. Под локом — чтение из БД / создание дефолта
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        # double-check после захвата лока
        cached = get_from_cache(chat_id, user_id)
        if cached is not None:
            updated = False
            if full_name and cached.get('full_name') != full_name:
                cached['full_name'] = full_name
                updated = True
            if username is not None and cached.get('username') != username:
                cached['username'] = username
                updated = True
            if updated:
                set_in_cache(chat_id, user_id, cached)
                mark_dirty(chat_id, user_id)
            return cached

        ref = get_user_ref(chat_id, user_id)
        try:
            doc = await ref.get()
        except Exception as e:
            logger.error("Firestore read failed for %s:%s — %s", chat_id, user_id, e)
            raise

        if doc.exists:
            data = doc.to_dict() or {}
            updated = False
            updates_dict = {}
            if full_name and data.get('full_name') != full_name:
                data['full_name'] = full_name
                updates_dict['full_name'] = full_name
                updated = True
            if username is not None and data.get('username') != username:
                data['username'] = username
                updates_dict['username'] = username
                updated = True
            if updated:
                fire_and_forget(ref.update(updates_dict))
            set_in_cache(chat_id, user_id, data)
            return copy.deepcopy(data)

        default_data = _default_user_data(full_name or "Игрок")
        if username is not None:
            default_data['username'] = username
        set_in_cache(chat_id, user_id, default_data)
        mark_dirty(chat_id, user_id)
        return copy.deepcopy(default_data)



def _default_user_data(full_name: str) -> dict:
    return {
        'balance': DEFAULT_START_BALANCE,
        'bank_deposit': 0,
        'bank_name': None,
        'last_bonus_time': 0,
        'last_daily_time': 0,
        'last_work_time': 0,
        'last_crime_time': 0,
        'inventory': {},
        'biz_levels': {},
        'warns': [],
        'is_banned': False,
        'hide_in_top': False,
        'full_name': full_name,
        'is_vip': False,
        'is_banker': False,
        'debts': {},
        'escort_count': 0,
        'meme_cards': {},
        'opened_cases_count': 0,
        'ai_memory': default_ai_memory(),
    }


async def safe_get_snapshot(transaction, ref):
    """
    Получает snapshot документа внутри транзакции, обходя различия
    версий google-cloud-firestore (sync/async, генератор и т.д.).

    Перед чтением из Firestore проверяет, есть ли у данного пользователя
    несброшенные (dirty) данные в кэше, и если да — немедленно сбрасывает их,
    чтобы транзакция не прочитала устаревший документ.
    """
    # --- Flush dirty cache for user documents before transactional read ---
    try:
        path = ref.path  # e.g. 'chats/123/users/456'
        parts = path.split('/')
        if len(parts) == 4 and parts[0] == 'chats' and parts[2] == 'users':
            _chat_id = int(parts[1])
            _user_id = int(parts[3])
            if (_chat_id, _user_id) in _dirty_cache:
                await flush_user_cache_immediately(_chat_id, _user_id)
    except (ValueError, AttributeError, IndexError):
        pass

    if not transaction:
        return await ref.get()

    # Вариант 1: transaction.get(ref) — стандартный путь.
    try:
        res = transaction.get(ref)
        if hasattr(res, '__aiter__'):
            async for s in res:
                return s
        if asyncio.iscoroutine(res) or hasattr(res, '__await__'):
            return await res
        return res
    except (TypeError, AttributeError):
        pass

    # Вариант 2: ref.get(transaction=transaction)
    try:
        res = ref.get(transaction=transaction)
        if hasattr(res, '__aiter__'):
            async for s in res:
                return s
        if asyncio.iscoroutine(res) or hasattr(res, '__await__'):
            return await res
        return res
    except (TypeError, AttributeError):
        pass

    # Вариант 3: низкоуровневый batch_get (fallback для багов библиотеки).
    from google.cloud.firestore_v1.base_client import _parse_batch_get
    request, kwargs = ref._prep_batch_get(None, transaction, None, None, None)
    gen = ref._client._firestore_api.batch_get_documents(
        request=request,
        metadata=ref._client._rpc_metadata,
        **kwargs,
    )
    async for resp in gen:
        return _parse_batch_get(resp, {ref._document_path: ref}, ref._client)

    raise RuntimeError(f"Не удалось получить snapshot документа {ref.path}")


# ============================================================
# БАЛАНС
# ============================================================
async def update_user_balance(
    chat_id,
    user_id,
    amount: int,
    min_balance: Optional[int] = None,
    is_debt_repayment: bool = False,    # сохранено для обратной совместимости
    action: str = "Balance Update",
    transaction=None,
) -> Optional[int]:
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    """
    Универсальное обновление баланса.
    Возвращает новый баланс или None, если min_balance нарушен / юзера нет.

    ВАЖНО про транзакционный путь:
      - Кэш НЕ трогаем здесь. Транзакция ещё не закомичена, и любая
        инвалидация в этот момент может привести к тому, что параллельный
        запрос подтянет старые данные из БД и положит их в кэш.
      - Инвалидацию (invalidate_user_cache) ОБЯЗАТЕЛЬНО выполняйте на
        стороне вызывающего кода ПОСЛЕ успешного коммита транзакции.
      - Логирование/алерты в транзакционном пути также не выполняются
        (вызывайте их после commit).
    """
    # ----- Транзакционный путь -----
    if transaction:
        ref = get_user_ref(chat_id, user_id)
        snapshot = await safe_get_snapshot(transaction, ref)
        if not snapshot.exists:
            return None

        data = snapshot.to_dict() or {}
        current = int(data.get('balance', 0) or 0)
        if min_balance is not None and current + amount < min_balance:
            return None

        new_balance = current + amount
        transaction.update(ref, {'balance': new_balance})
        # NB: НЕ инвалидируем кэш внутри транзакции — см. docstring.
        return new_balance

    # ----- Обычный путь -----
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        current = int(data.get('balance', 0) or 0)
        if min_balance is not None and current + amount < min_balance:
            return None

        new_balance = current + amount
        data['balance'] = new_balance
        full_name = data.get('full_name', 'Unknown')
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

    if abs(amount) >= LARGE_TX_THRESHOLD:
        fire_and_forget(log_transaction(user_id, full_name, None, action, "Change", amount))
    fire_and_forget(check_balance_alert(chat_id, user_id, full_name, new_balance))
    return new_balance


async def update_user_balance_tr(transaction, chat_id, user_id, amount,
                                 min_balance=None, action="Transaction Update"):
    """DEPRECATED. Используйте update_user_balance(transaction=...)."""
    return await update_user_balance(
        chat_id, user_id, amount,
        min_balance=min_balance, transaction=transaction, action=action,
    )


async def update_user_field(chat_id, user_id, field: str, value: Any) -> None:
    chat_id, user_id = _normalize_ids(chat_id, user_id)
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)

        if field == 'balance':
            old_balance = int(data.get('balance', 0) or 0)
            diff = int(value) - old_balance
            full_name = data.get('full_name', 'Unknown')
            if abs(diff) >= LARGE_TX_THRESHOLD:
                fire_and_forget(log_transaction(
                    user_id, full_name, None, "Balance Set", "Set", diff,
                ))
            fire_and_forget(check_balance_alert(chat_id, user_id, full_name, value))

        data[field] = value
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)


# ============================================================
# БОНУС
# ============================================================
async def _fetch_active_lobby_type(chat_id, user_id, current_time: float) -> str:
    """Возвращает тип активного лобби банкиров (golden / tax / none)."""
    db = get_db()
    banks_ref = db.collection('chats').document(str(chat_id)).collection('banks')
    try:
        active_lobbies = await banks_ref.where('lobby_until', '>', current_time).get()
    except Exception as e:
        logger.error("Lobby query error: %s", e)
        return 'none'

    for b_doc in active_lobbies:
        b_data = b_doc.to_dict() or {}
        if user_id in (b_data.get('lobby_blacklist') or []):
            continue
        ltype = b_data.get('lobby_type', 'golden')
        if ltype in ('golden', 'tax'):
            return ltype
    return 'none'


async def check_and_give_bonus(chat_id, user_id, full_name=None):
    """
    Начисляет бонус (с учётом бизнесов, машин, банка, болезней, лобби, налогов).
    Возвращает (True, info) при успехе, (False, {}) при кулдауне/бане.
    """
    from config import CREATOR_ID

    # Быстрая проверка без лока: кулдаун + бан
    pre = await get_user_data(chat_id, user_id, full_name)
    if pre.get('is_banned', False):
        return False, {}
    current_time = time.time()
    if user_id != CREATOR_ID and current_time - pre.get('last_bonus_time', 0) < BONUS_COOLDOWN:
        return False, {}

    # Тяжёлые операции — ДО лока, чтобы не блокировать запись
    from shop import ITEMS
    from economy_utils import get_global_tax, calculate_progressive_tax
    from diseases import get_active_diseases

    base_tax = await get_global_tax()
    active_diseases = await get_active_diseases(chat_id, user_id)
    lobby_type = await _fetch_active_lobby_type(chat_id, user_id, current_time)

    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id, full_name)
        if data.get('is_banned', False):
            return False, {}

        # Double-check кулдауна после захвата лока
        if user_id != CREATOR_ID and current_time - data.get('last_bonus_time', 0) < BONUS_COOLDOWN:
            return False, {}

        bank_deposit = int(data.get('bank_deposit', 0) or 0)
        bank_income = 0
        is_daily = (user_id == CREATOR_ID) or (current_time - data.get('last_daily_time', 0) >= DAILY_COOLDOWN)

        # Проценты по старым системным вкладам (когда юзер не в кастомном банке)
        if is_daily and bank_deposit > 0 and not data.get('bank_name'):
            if bank_deposit <= 100_000_000:
                bank_income = int(bank_deposit * 0.01)
            elif bank_deposit <= 1_000_000_000:
                bank_income = int(bank_deposit * 0.005)
            else:
                bank_income = int(bank_deposit * 0.002)

        base_bonus = BASE_BONUS

        neg_lvl = (data.get('skills') or {}).get('negotiation', 0)
        pet_data = data.get('pet') or {}
        pet_id = pet_data.get('id') if isinstance(pet_data, dict) else None
        tax_percent = calculate_progressive_tax(
            data.get('balance', 0) or 0, base_tax, neg_lvl, pet_id
        )

        # Доход с бизнесов / машин
        biz_income = 0
        car_income = 0
        inventory = data.get('inventory') or {}
        biz_levels = data.get('biz_levels') or {}

        for item_id, count in inventory.items():
            item = ITEMS.get(item_id)
            if not item:
                continue
            atype = item.get('action')
            if atype == 'business':
                level = biz_levels.get(item_id, 1)
                mult = 1.0 + BIZ_LEVEL_BONUS * (level - 1)
                biz_income += int(item.get('income', 0) * mult) * min(count, BIZ_COUNT_CAP)
            elif atype == 'car':
                car_income += int(item.get('income', 0)) * count

        # Банкиры платят 10% от пассивного дохода
        if data.get('is_banker', False):
            biz_income = int(biz_income * 0.1)
            car_income = int(car_income * 0.1)

        # Болезни
        if 'candidiasis' in active_diseases:
            base_bonus //= 2

        # Бонус хомяка
        if pet_id == 'hamster' and 'hpv' not in active_diseases:
            base_bonus += 500

        # Эффекты лобби
        if lobby_type == 'golden':
            base_bonus = int(base_bonus * 1.2)
            biz_income = int(biz_income * 1.2)
            car_income = int(car_income * 1.2)
        elif lobby_type == 'tax':
            tax_percent = max(0, tax_percent // 2)

        extra_income = biz_income + car_income + bank_income
        tax_amt = int(extra_income * (tax_percent / 100.0))

        # Перенаправление налогов в кастомный банк юзера
        bank_id = data.get('bank_name')
        if tax_amt > 0 and bank_id:
            try:
                from profile_bank import get_bank_info, create_or_update_bank
                b_info = await get_bank_info(chat_id, bank_id)
                if b_info:
                    await create_or_update_bank(
                        chat_id, bank_id,
                        {'capital': int(b_info.get('capital', 0) or 0) + tax_amt},
                    )
            except Exception as e:
                logger.error("Tax redirect to bank error: %s", e)

        # Meme bonuses
        meme_bonuses = get_user_meme_bonuses(data)
        meme_mult = meme_bonuses['multiplier']
        meme_flat = meme_bonuses['flat']
        card_boost = int((base_bonus + extra_income) * meme_mult) + meme_flat

        total = base_bonus + extra_income - tax_amt + card_boost
        if inventory.get('kovcheg', 0) > 0:
            total = int(total * 1.2)
        if total <= 0:
            total = 0

        data['balance'] = int(data.get('balance', 0) or 0) + total
        data['last_bonus_time'] = current_time
        if is_daily:
            data['last_daily_time'] = current_time
            if bank_deposit > 0 and not data.get('bank_name'):
                data['bank_deposit'] = bank_deposit + bank_income

        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)
        await flush_user_cache_immediately(chat_id, user_id)

    return True, {
        'base': base_bonus,
        'business': biz_income,
        'car': car_income,
        'tax_percent': tax_percent,
        'tax_amount': tax_amt,
        'meme_bonus': card_boost,
        'total': total,
        'is_banker_bonus': False,
    }


# ============================================================
# ИНВЕНТАРЬ
# ============================================================
async def add_item_to_inventory(chat_id, user_id, item_name: str, count: int = 1) -> bool:
    from shop import ITEMS
    if count <= 0:
        return False
    if item_name not in ITEMS and not item_name.startswith("dictor_"):
        return False

    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        inv = dict(data.get('inventory') or {})
        inv[item_name] = inv.get(item_name, 0) + count
        data['inventory'] = inv
        full_name = data.get('full_name', 'Unknown')
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)


    item_info = ITEMS.get(item_name) or {}
    total_price = int(item_info.get('price', 0) or 0) * count
    if total_price >= LARGE_TX_THRESHOLD:
        fire_and_forget(log_transaction(
            user_id, full_name, None,
            f"Added {count}x {item_name}", "Inventory +", total_price,
        ))
    return True


async def remove_item_from_inventory(chat_id, user_id, item_name: str, count: int = 1) -> bool:
    from shop import ITEMS

    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        inv = dict(data.get('inventory') or {})
        biz_levels = dict(data.get('biz_levels') or {})
        if inv.get(item_name, 0) < count or count <= 0:
            return False

        inv[item_name] -= count
        if inv[item_name] <= 0:
            inv.pop(item_name, None)
            biz_levels.pop(item_name, None)

        data['inventory'] = inv
        data['biz_levels'] = biz_levels
        full_name = data.get('full_name', 'Unknown')
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

    item_info = ITEMS.get(item_name) or {}
    total_price = int(item_info.get('price', 0) or 0) * count
    if total_price >= LARGE_TX_THRESHOLD:
        fire_and_forget(log_transaction(
            user_id, full_name, None,
            f"Removed {count}x {item_name}", "Inventory -", total_price,
        ))
    return True


# ============================================================
# ТРАНЗАКЦИОННЫЕ ОПЕРАЦИИ
# ============================================================
# ВАЖНО (общее для всех *_tr функций):
#   - Внутри транзакции мы НИКОГДА не трогаем кэш (_drop_cache_entry /
#     invalidate_user_cache / set_in_cache / mark_dirty).
#   - Транзакция Firestore может быть ещё не закоммичена в момент возврата
#     из этой функции — её коммитит обёртка (@firestore.async_transactional
#     или ручной .commit()). Если сбросить кэш сейчас, параллельный запрос
#     успеет вычитать СТАРЫЕ данные из БД и положить их обратно в кэш.
#   - Поэтому инвалидация ОБЯЗАТЕЛЬНА на стороне вызывающего кода ПОСЛЕ
#     успешного коммита транзакции, например:
#
#         @firestore.async_transactional
#         async def _txn(tr):
#             return await buy_item_tr(tr, chat_id, user_id, ...)
#         ok, err = await _txn(transaction)
#         if ok:
#             invalidate_user_cache(chat_id, user_id)   # <-- здесь
# ============================================================
async def sell_item_tr(transaction, chat_id, user_id, item_id, item_cat, sell_price: int, count: int = 1) -> bool:
    try:
        count = int(count)
    except (ValueError, TypeError):
        return False

    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False

    data = snapshot.to_dict() or {}
    inv = dict(data.get('inventory') or {})
    biz_levels = dict(data.get('biz_levels') or {})
    curr_qty = inv.get(item_id, 0)
    if curr_qty < count or count <= 0:
        return False


    inv[item_id] -= count
    if inv[item_id] <= 0:
        inv.pop(item_id, None)
        if item_cat == 'biz':
            biz_levels.pop(item_id, None)

    total_payout = int(sell_price) * count
    updates = {
        'inventory': inv,
        'biz_levels': biz_levels,
        'balance': int(data.get('balance', 0) or 0) + total_payout,
    }
    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    # NB: кэш НЕ инвалидируем здесь — это сделает вызывающий код после commit.
    return True



async def buy_item_tr(transaction, chat_id, user_id, item_id,
                      price_to_deduct: int, is_vip: bool = False):
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False, "Пользователь не найден"

    data = snapshot.to_dict() or {}
    balance = int(data.get('balance', 0) or 0)
    if balance < price_to_deduct:
        return False, "Недостаточно денег"

    updates = {'balance': balance - int(price_to_deduct)}
    if is_vip:
        updates['is_vip'] = True
    else:
        inv = dict(data.get('inventory') or {})
        inv[item_id] = inv.get(item_id, 0) + 1
        updates['inventory'] = inv

    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    # NB: кэш НЕ инвалидируем здесь — это сделает вызывающий код после commit.
    return True, None


async def sell_vip_tr(transaction, chat_id, user_id, sell_price: int) -> bool:
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False

    data = snapshot.to_dict() or {}
    if not data.get('is_vip'):
        return False

    updates = {
        'is_vip': False,
        'balance': int(data.get('balance', 0) or 0) + int(sell_price),
    }
    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    # NB: кэш НЕ инвалидируем здесь — это сделает вызывающий код после commit.
    return True


async def upgrade_business_tr(transaction, chat_id, user_id, item_id,
                              upgrade_cost: int, max_level: int):
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False, "Пользователь не найден"

    data = snapshot.to_dict() or {}
    balance = int(data.get('balance', 0) or 0)
    biz_levels = dict(data.get('biz_levels') or {})
    inventory = data.get('inventory') or {}

    if inventory.get(item_id, 0) <= 0:
        return False, "У вас нет этого бизнеса"

    current_level = biz_levels.get(item_id, 1)
    if current_level >= max_level:
        return False, "Максимальный уровень уже достигнут"
    if balance < upgrade_cost:
        return False, "Недостаточно сыроежек"

    biz_levels[item_id] = current_level + 1
    updates = {'balance': balance - int(upgrade_cost), 'biz_levels': biz_levels}

    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    # NB: кэш НЕ инвалидируем здесь — это сделает вызывающий код после commit.
    return True, None


# ============================================================
# ВЫБОРКИ / ПОИСК
# ============================================================
async def get_top_users(chat_id, limit: int = 10):
    """Топ по балансу, фильтрует hidden/banned/banker.
    Если после фильтра набралось мало — добирает следующей страницей."""
    db = get_db()
    ref = db.collection('chats').document(str(chat_id)).collection('users')

    fetch_limit = max(limit * 3, limit + 30)
    users: list = []
    last_doc = None
    rounds = 0

    while len(users) < limit and rounds < 3:
        rounds += 1
        q = ref.order_by('balance', direction='DESCENDING').limit(fetch_limit)
        if last_doc is not None:
            q = q.start_after(last_doc)
        try:
            docs = await q.get()
        except Exception as e:
            logger.error("get_top_users query failed: %s", e)
            break
        if not docs:
            break
        for doc in docs:
            data = doc.to_dict() or {}
            last_doc = doc
            if (data.get('hide_in_top') or data.get('is_banned')
                    or data.get('is_banker')):
                continue
            users.append({'user_id': doc.id, **data})
            if len(users) >= limit:
                break

    return users


async def is_user_banker(chat_id, user_id) -> bool:
    data = await get_user_data(chat_id, user_id)
    return bool(data.get('is_banker', False))


async def get_all_users_in_chat(chat_id):
    db = get_db()
    ref = db.collection('chats').document(str(chat_id)).collection('users')
    return await ref.get()


async def get_user_by_username_or_id(chat_id, identifier):
    """Поиск пользователя по ID или @username. Возвращает (user_id, data) или (None, None)."""
    if not identifier:
        return None, None

    identifier = str(identifier).strip()
    if not identifier:
        return None, None

    # 1) Пытаемся как числовой ID
    raw = identifier.lstrip("@")
    target_id: Optional[int] = None
    try:
        target_id = int(raw)
    except (ValueError, TypeError):
        pass

    if target_id is not None:
        db = get_db()
        doc = await (
            db.collection('chats').document(str(chat_id))
              .collection('users').document(str(target_id)).get()
        )
        if doc.exists:
            return target_id, (doc.to_dict() or {})

    # 2) Поиск по username
    username = raw.lower()
    if not username:
        return None, None

    cached_uid = _username_to_id_cache.get((chat_id, username))
    if cached_uid is not None:
        entry = _user_cache.get((chat_id, cached_uid))
        if entry:
            return cached_uid, copy.deepcopy(entry['data'])

    db = get_db()
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')
    try:
        docs = await users_ref.where('username', '==', username).limit(1).get()
    except Exception as e:
        logger.error("Username search failed for %s: %s", username, e)
        return None, None

    async def _yield(docs):
        if hasattr(docs, '__aiter__'):
            async for d in docs:
                yield d
        else:
            for d in docs:
                yield d

    async for doc in _yield(docs):
        data = doc.to_dict() or {}
        try:
            uid = int(doc.id)
        except (ValueError, TypeError):
            uid = doc.id
        # Освежим индекс
        _username_to_id_cache[(chat_id, username)] = uid
        return uid, data

    return None, None


# ============================================================
# СБРОС
# ============================================================
async def wipe_user_data(chat_id, user_id, preserve_dictors: bool = True) -> bool:
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        ref = get_user_ref(chat_id, user_id)
        data = await get_user_data(chat_id, user_id)
        full_name = data.get('full_name', 'Player')
        was_banned = bool(data.get('is_banned', False))

        default_data = _default_user_data(full_name)
        if preserve_dictors:
            curr_inv = data.get('inventory') or {}
            preserved_dictors = {k: v for k, v in curr_inv.items() if k.startswith('dictor_')}
            default_data['inventory'] = preserved_dictors

        # расширяем дефолт дополнительными полями, нужными при wipe
        default_data.update({
            'crypto_portfolio': {},
            'stocks_portfolio': {},
            'pet': {},
            'skills': {},
            'diseases': {},
            'crypto_banned': False,
            'is_banned': was_banned,   # сохраняем бан
        })

        try:
            await ref.set(default_data)
        except Exception as e:
            logger.error("wipe_user_data write failed for %s:%s — %s",
                         chat_id, user_id, e)
            return False

        invalidate_user_cache(chat_id, user_id)
        return True



# ============================================================
# КОЛЛЕКЦИОННЫЕ КАРТОЧКИ
# ============================================================
def get_user_meme_bonuses(user_data: dict) -> dict:
    """
    Возвращает суммарные бонусы от карточек пользователя.
    """
    from cards_system import CARDS
    meme_cards = user_data.get('meme_cards', {})
    
    total_multiplier = 0.0
    total_flat = 0
    
    for card_id, count in meme_cards.items():
        if count > 0 and card_id in CARDS:
            card_info = CARDS[card_id]
            total_multiplier += card_info.get('bonus_multiplier', 0.0) * count
            total_flat += card_info.get('bonus_flat', 0) * count
            
    return {
        'multiplier': total_multiplier,
        'flat': total_flat
    }


async def buy_and_open_case_tr(transaction, chat_id, user_id, price_to_deduct: int, card_id: str):
    """
    Транзакционное списание денег и добавление мем-карточки в инвентарь пользователя.
    """
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False, "Пользователь не найден"

    data = snapshot.to_dict() or {}
    balance = int(data.get('balance', 0) or 0)
    if balance < price_to_deduct:
        return False, "Недостаточно денег"

    meme_cards = dict(data.get('meme_cards') or {})
    meme_cards[card_id] = meme_cards.get(card_id, 0) + 1
    
    opened_count = int(data.get('opened_cases_count', 0) or 0) + 1

    updates = {
        'balance': balance - price_to_deduct,
        'meme_cards': meme_cards,
        'opened_cases_count': opened_count
    }

    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    return True, None


async def open_free_case_tr(transaction, chat_id: int, user_id: int, card_id: str, cooldown_seconds: int = 43200):
    """
    Транзакционное открытие бесплатного кейса с проверкой 12-часового кулдауна.
    """
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False, "Пользователь не найден"

    data = snapshot.to_dict() or {}
    now = time.time()
    last_ts = float(data.get('last_free_card_case_ts', 0) or 0)
    
    if last_ts > 0 and (now - last_ts < cooldown_seconds):
        rem = int(cooldown_seconds - (now - last_ts))
        h = rem // 3600
        m = (rem % 3600) // 60
        return False, f"⏳ Бесплатный кейс будет доступен через {h}ч {m}мин!"


    meme_cards = dict(data.get('meme_cards') or {})
    meme_cards[card_id] = meme_cards.get(card_id, 0) + 1
    
    opened_count = int(data.get('opened_cases_count', 0) or 0) + 1

    updates = {
        'last_free_card_case_ts': now,
        'meme_cards': meme_cards,
        'opened_cases_count': opened_count
    }

    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    return True, None

