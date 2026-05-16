import os
import time
import copy
import asyncio
import logging
from collections import OrderedDict

from db import get_db
from utils import fire_and_forget
from admin_logs import log_transaction, check_balance_alert

logger = logging.getLogger(__name__)


def get_user_ref(chat_id, user_id):
    db = get_db()
    return db.collection('chats').document(str(chat_id)).collection('users').document(str(user_id))


# ---------------- КЭШ ----------------
# OrderedDict для корректного LRU
_user_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_username_to_id_cache = {}        # (chat_id, username_lower) -> user_id
_dirty_cache = set()
_user_locks = {}                  # (chat_id, user_id) -> asyncio.Lock
_flush_lock = asyncio.Lock()      # Защита от одновременных flush

CACHE_TTL = 60.0
MAX_CACHE_SIZE = 1000
FLUSH_BATCH_SIZE = 100            # Конкурентные записи в gather


def get_user_lock(chat_id, user_id):
    """В asyncio (однопоточно) check-and-set атомарен между await,
    поэтому отдельный creation-lock не нужен."""
    key = (chat_id, user_id)
    lock = _user_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[key] = lock
    return lock


def get_from_cache(chat_id, user_id):
    key = (chat_id, user_id)
    entry = _user_cache.get(key)
    if entry is None:
        return None
    if time.time() - entry["timestamp"] >= CACHE_TTL:
        return None
    # LRU: помечаем как недавно использованный
    _user_cache.move_to_end(key)
    # deepcopy чтобы изменения caller-а не порушили кэш
    return copy.deepcopy(entry["data"])


def _remove_username_from_index(chat_id, data):
    if not isinstance(data, dict):
        return
    uname = data.get("username")
    if uname:
        _username_to_id_cache.pop((chat_id, uname.lower()), None)


def set_in_cache(chat_id, user_id, data):
    key = (chat_id, user_id)

    # Удаляем старый юзернейм из индекса, если был
    old_entry = _user_cache.get(key)
    if old_entry:
        _remove_username_from_index(chat_id, old_entry["data"])

    # Eviction (только если ключа ещё нет и кэш переполнен)
    if key not in _user_cache and len(_user_cache) >= MAX_CACHE_SIZE:
        evict_key = None
        for k in _user_cache:  # порядок = LRU
            if k not in _dirty_cache:
                evict_key = k
                break
        if evict_key is not None:
            evicted = _user_cache.pop(evict_key)
            _remove_username_from_index(evict_key[0], evicted["data"])

    # Записываем глубокую копию, чтобы дальнейшие мутации caller-а не задели кэш
    _user_cache[key] = {"data": copy.deepcopy(data), "timestamp": time.time()}
    _user_cache.move_to_end(key)

    new_uname = data.get("username")
    if new_uname:
        _username_to_id_cache[(chat_id, new_uname.lower())] = user_id


def invalidate_user_cache(chat_id, user_id):
    """Удаляет пользователя из кэша и FSM."""
    key = (chat_id, user_id)
    entry = _user_cache.pop(key, None)
    if entry:
        _remove_username_from_index(chat_id, entry["data"])
    _dirty_cache.discard(key)

    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return

    def _cleanup():
        try:
            import redis as _redis
            r = _redis.from_url(redis_url)
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
            logger.error(f"Redis cleanup error: {e}")

    # Не блокируем event loop
    try:
        fire_and_forget(asyncio.to_thread(_cleanup))
    except Exception as e:
        logger.error(f"Failed to schedule redis cleanup: {e}")


def mark_dirty(chat_id, user_id):
    _dirty_cache.add((chat_id, user_id))


async def flush_user_data():
    """Синхронизирует грязный кэш с БД пачками."""
    if not _dirty_cache:
        return

    # Защита от параллельных flush
    if _flush_lock.locked():
        return
    async with _flush_lock:
        to_flush = list(_dirty_cache)
        for i in range(0, len(to_flush), FLUSH_BATCH_SIZE):
            batch_keys = to_flush[i:i + FLUSH_BATCH_SIZE]
            tasks = []
            task_keys = []

            for key in batch_keys:
                # Снимаем "грязный" флаг ДО записи; если запись упадёт — вернём.
                # Если кэш изменится во время записи, mark_dirty снова поставит флаг.
                _dirty_cache.discard(key)
                cached_entry = _user_cache.get(key)
                if not cached_entry:
                    continue
                ref = get_user_ref(key[0], key[1])
                # Передаём ссылку на dict — на момент await будут актуальные данные
                tasks.append(ref.set(cached_entry["data"], merge=True))
                task_keys.append(key)

            if not tasks:
                continue

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for key, result in zip(task_keys, results):
                if isinstance(result, Exception):
                    logger.error(f"⚠️ Ошибка записи пользователя {key}: {result}")
                    _dirty_cache.add(key)  # повторим позже


async def flush_user_data_task():
    """Фоновая задача: синхронизация раз в 15с + чистка локов."""
    while True:
        try:
            await asyncio.sleep(15)
            await flush_user_data()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"⚠️ Ошибка при синхронизации кэша: {e}")

        # Очистка локов — только тех, что точно никем не используются
        try:
            current_keys = set(_user_cache.keys())
            for key in list(_user_locks.keys()):
                if key in current_keys:
                    continue
                lock = _user_locks.get(key)
                if lock is None:
                    continue
                if lock.locked():
                    continue
                # Проверка приватного _waiters — на случай ожидающих корутин
                waiters = getattr(lock, "_waiters", None)
                if waiters:
                    continue
                _user_locks.pop(key, None)
        except Exception as e:
            logger.error(f"Lock cleanup error: {e}")


async def get_user_data(chat_id, user_id, full_name=None):
    cached_data = get_from_cache(chat_id, user_id)
    if cached_data is not None:
        if full_name and cached_data.get('full_name') != full_name:
            cached_data['full_name'] = full_name
            set_in_cache(chat_id, user_id, cached_data)
            ref = get_user_ref(chat_id, user_id)
            fire_and_forget(ref.update({'full_name': full_name}))
        return cached_data

    ref = get_user_ref(chat_id, user_id)
    doc = await ref.get()

    if doc.exists:
        data = doc.to_dict() or {}
        if full_name and data.get('full_name') != full_name:
            data['full_name'] = full_name
            fire_and_forget(ref.update({'full_name': full_name}))
        set_in_cache(chat_id, user_id, data)
        # Возвращаем независимую копию
        return copy.deepcopy(data)

    default_name = full_name if full_name else "Игрок"
    default_data = {
        'balance': 500,
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
        'full_name': default_name,
        'is_vip': False,
        'is_banker': False,
        'debts': {},
        'escort_count': 0,
    }
    set_in_cache(chat_id, user_id, default_data)
    mark_dirty(chat_id, user_id)
    return copy.deepcopy(default_data)


async def safe_get_snapshot(transaction, ref):
    """
    Безопасно получает snapshot документа внутри транзакции.
    Обрабатывает баги версий firestore_async (async_generator error).
    """
    if not transaction:
        return await ref.get()

    try:
        res = transaction.get(ref)
        if hasattr(res, '__aiter__'):
            async for s in res:
                return s
        return await res
    except (TypeError, AttributeError):
        try:
            res = ref.get(transaction=transaction)
            if hasattr(res, '__aiter__'):
                async for s in res:
                    return s
            return await res
        except (TypeError, AttributeError):
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


async def update_user_balance(
    chat_id, user_id, amount,
    min_balance=None,
    is_debt_repayment=False,
    action="Balance Update",
    transaction=None,
):
    """
    Универсальная функция обновления баланса.
    - При min_balance нарушении: возвращает None (единообразно для обоих путей).
    - В transaction-пути НЕ обновляет кэш оптимистично (инвалидирует),
      чтобы избежать рассинхрона при откате транзакции.
    """
    new_balance = None
    full_name = "Unknown"

    if transaction:
        ref = get_user_ref(chat_id, user_id)
        snapshot = await safe_get_snapshot(transaction, ref)
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        full_name = data.get('full_name', 'Unknown')

        current_balance = data.get('balance', 0)
        if min_balance is not None and current_balance + amount < min_balance:
            return None  # унифицировано с не-транзакционным путём

        new_balance = current_balance + amount
        transaction.update(ref, {'balance': new_balance})

        # Инвалидируем кэш: следующее чтение возьмёт свежие данные из БД (после commit)
        _user_cache.pop((chat_id, user_id), None)
        _dirty_cache.discard((chat_id, user_id))

        # В транзакционном пути НЕ логируем — транзакция может откатиться/повторяться.
        # Логирование должно выполнять caller после успешного commit.
        return new_balance

    # Не-транзакционный путь
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        current_balance = data.get('balance', 0)

        if min_balance is not None and current_balance + amount < min_balance:
            return None

        new_balance = current_balance + amount
        data['balance'] = new_balance
        full_name = data.get('full_name', 'Unknown')
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

    if abs(amount) >= 500_000:
        fire_and_forget(log_transaction(user_id, full_name, None, action, "Change", amount))
    fire_and_forget(check_balance_alert(chat_id, user_id, full_name, new_balance))

    return new_balance


async def update_user_balance_tr(transaction, chat_id, user_id, amount, min_balance=None, action="Transaction Update"):
    """
    DEPRECATED: используйте update_user_balance(transaction=...).
    Оставлено для совместимости.
    """
    return await update_user_balance(
        chat_id, user_id, amount,
        min_balance=min_balance,
        transaction=transaction,
        action=action,
    )


async def update_user_field(chat_id, user_id, field, value):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)

        if field == 'balance':
            old_balance = data.get('balance', 0)
            amount_changed = value - old_balance
            if abs(amount_changed) >= 500_000:
                fire_and_forget(log_transaction(
                    user_id, data.get('full_name', 'Unknown'),
                    None, "Balance Set", "Set", amount_changed,
                ))
            fire_and_forget(check_balance_alert(
                chat_id, user_id, data.get('full_name', 'Player'), value
            ))

        data[field] = value
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)


async def check_and_give_bonus(chat_id, user_id, full_name=None):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id, full_name)
        if data.get('is_banned', False):
            return False, {}

        current_time = time.time()
        last_bonus = data.get('last_bonus_time', 0)

        if current_time - last_bonus < 14400:
            return False, {}

        bank_deposit = data.get('bank_deposit', 0)
        bank_income = 0
        is_daily = False

        base_bonus = 1000  # фиксированный бонус для всех

        # Ежедневные проценты по старым системным вкладам (без банка)
        if current_time - data.get('last_daily_time', 0) >= 79200:
            is_daily = True
            if bank_deposit > 0 and not data.get('bank_name'):
                if bank_deposit <= 100_000_000:
                    bank_income = int(bank_deposit * 0.01)
                elif bank_deposit <= 1_000_000_000:
                    bank_income = int(bank_deposit * 0.005)
                else:
                    bank_income = int(bank_deposit * 0.002)

        from shop import ITEMS
        from economy_utils import get_global_tax, calculate_progressive_tax
        from diseases import get_active_diseases

        base_tax = await get_global_tax()
        neg_lvl = data.get('skills', {}).get('negotiation', 0)
        pet_data = data.get('pet', {})
        pet_id = pet_data.get('id') if isinstance(pet_data, dict) else None
        tax_percent = calculate_progressive_tax(
            data.get('balance', 0), base_tax, neg_lvl, pet_id
        )

        active_diseases = await get_active_diseases(chat_id, user_id)

        biz_income = 0
        car_income = 0
        inventory = data.get('inventory', {}) or {}
        biz_levels = data.get('biz_levels', {}) or {}

        for item_id, count in inventory.items():
            item = ITEMS.get(item_id)
            if not item:
                continue
            action_type = item.get('action')
            if action_type == 'business':
                level = biz_levels.get(item_id, 1)
                level_multiplier = 1.0 + 0.5 * (level - 1)
                inc = int(item.get('income', 0) * level_multiplier) * min(count, 10)
                biz_income += inc
            elif action_type == 'car':
                car_income += item.get('income', 0) * count

        if data.get('is_banker', False):
            biz_income = int(biz_income * 0.1)
            car_income = int(car_income * 0.1)

        if 'candidiasis' in active_diseases:
            base_bonus = base_bonus // 2

        pet = data.get('pet')
        if 'hpv' in active_diseases:
            pet = None  # noqa: F841 (на будущее)

        # --- ЛОББИРОВАНИЕ БАНКИРОВ ---
        db = get_db()
        banks_ref = db.collection('chats').document(str(chat_id)).collection('banks')
        try:
            active_lobbies = await banks_ref.where('lobby_until', '>', current_time).get()
        except Exception as e:
            logger.error(f"Lobby query error: {e}")
            active_lobbies = []

        lobby_type = 'none'
        for b_doc in active_lobbies:
            b_data = b_doc.to_dict() or {}
            blacklist = b_data.get('lobby_blacklist', []) or []
            if user_id not in blacklist:
                lobby_type = b_data.get('lobby_type', 'golden')
                if lobby_type in ('golden', 'tax'):
                    break

        if lobby_type == 'golden':
            lobby_boost = 1.2
            base_bonus = int(base_bonus * lobby_boost)
            biz_income = int(biz_income * lobby_boost)
            car_income = int(car_income * lobby_boost)
        elif lobby_type == 'tax':
            tax_percent = max(0, tax_percent // 2)

        extra_income = biz_income + car_income + bank_income
        tax_amt = int(extra_income * (tax_percent / 100.0))

        # --- ПЕРЕНАПРАВЛЕНИЕ НАЛОГОВ В БАНК ---
        if tax_amt > 0:
            bank_id = data.get('bank_name')
            if bank_id:
                try:
                    from profile_bank import get_bank_info, create_or_update_bank
                    b_info = await get_bank_info(chat_id, bank_id)
                    if b_info:
                        await create_or_update_bank(
                            chat_id, bank_id,
                            {'capital': b_info.get('capital', 0) + tax_amt},
                        )
                except Exception as e:
                    logger.error(f"Tax redirect to bank error: {e}")

        total_to_hand = base_bonus + extra_income - tax_amt
        if total_to_hand <= 0:
            return False, {}

        upd = {
            'balance': data.get('balance', 0) + total_to_hand,
            'last_bonus_time': current_time,
        }
        if is_daily:
            upd['last_daily_time'] = current_time
            if bank_deposit > 0 and not data.get('bank_name'):
                upd['bank_deposit'] = bank_deposit + bank_income

        data.update(upd)
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

        return True, {
            'base': base_bonus,
            'business': biz_income,
            'car': car_income,
            'tax_percent': tax_percent,
            'tax_amount': tax_amt,
            'total': total_to_hand,
            'is_banker_bonus': False,
        }


async def add_item_to_inventory(chat_id, user_id, item_name):
    from shop import ITEMS
    if item_name not in ITEMS:
        return False

    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        inv = dict(data.get('inventory', {}) or {})
        inv[item_name] = inv.get(item_name, 0) + 1

        data['inventory'] = inv
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

        item_info = ITEMS.get(item_name)
        if item_info and item_info.get('price', 0) >= 500_000:
            fire_and_forget(log_transaction(
                user_id, data.get('full_name', 'Unknown'),
                None, f"Added {item_name}", "Inventory +", item_info['price'],
            ))

    return True


async def remove_item_from_inventory(chat_id, user_id, item_name):
    from shop import ITEMS

    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        inv = dict(data.get('inventory', {}) or {})
        biz_levels = dict(data.get('biz_levels', {}) or {})

        if inv.get(item_name, 0) <= 0:
            return False

        inv[item_name] -= 1
        if inv[item_name] <= 0:
            del inv[item_name]
            biz_levels.pop(item_name, None)

        data['inventory'] = inv
        data['biz_levels'] = biz_levels
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

        item_info = ITEMS.get(item_name)
        if item_info and item_info.get('price', 0) >= 500_000:
            fire_and_forget(log_transaction(
                user_id, data.get('full_name', 'Unknown'),
                None, f"Removed {item_name}", "Inventory -", item_info['price'],
            ))

    return True


async def sell_item_tr(transaction, chat_id, user_id, item_id, item_cat, sell_price):
    """Атомарная продажа предмета внутри транзакции."""
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False

    data = snapshot.to_dict() or {}
    inv = dict(data.get('inventory', {}) or {})
    biz_levels = dict(data.get('biz_levels', {}) or {})

    if inv.get(item_id, 0) <= 0:
        return False

    inv[item_id] -= 1
    if inv[item_id] <= 0:
        del inv[item_id]
        if item_cat == 'biz':
            biz_levels.pop(item_id, None)

    new_balance = data.get('balance', 0) + sell_price
    updates = {'inventory': inv, 'biz_levels': biz_levels, 'balance': new_balance}

    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    # Инвалидируем кэш — пусть следующее чтение возьмёт актуальное из БД
    _user_cache.pop((chat_id, user_id), None)
    _dirty_cache.discard((chat_id, user_id))
    return True


async def buy_item_tr(transaction, chat_id, user_id, item_id, price_to_deduct, is_vip=False):
    """Атомарная покупка предмета внутри транзакции."""
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False, "Пользователь не найден"

    data = snapshot.to_dict() or {}
    balance = data.get('balance', 0)
    if balance < price_to_deduct:
        return False, "Недостаточно денег"

    new_balance = balance - price_to_deduct
    updates = {'balance': new_balance}

    if is_vip:
        updates['is_vip'] = True
    else:
        inv = dict(data.get('inventory', {}) or {})
        inv[item_id] = inv.get(item_id, 0) + 1
        updates['inventory'] = inv

    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    _user_cache.pop((chat_id, user_id), None)
    _dirty_cache.discard((chat_id, user_id))
    return True, None


async def sell_vip_tr(transaction, chat_id, user_id, sell_price):
    """Атомарная продажа VIP статуса."""
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False

    data = snapshot.to_dict() or {}
    if not data.get('is_vip'):
        return False

    new_balance = data.get('balance', 0) + sell_price
    updates = {'is_vip': False, 'balance': new_balance}

    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    _user_cache.pop((chat_id, user_id), None)
    _dirty_cache.discard((chat_id, user_id))
    return True


async def upgrade_business_tr(transaction, chat_id, user_id, item_id, upgrade_cost, max_level):
    """Атомарное улучшение бизнеса."""
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if not snapshot.exists:
        return False, "Пользователь не найден"

    data = snapshot.to_dict() or {}
    balance = data.get('balance', 0)
    biz_levels = dict(data.get('biz_levels', {}) or {})
    inventory = data.get('inventory', {}) or {}

    if inventory.get(item_id, 0) <= 0:
        return False, "У вас нет этого бизнеса"

    current_level = biz_levels.get(item_id, 1)
    if current_level >= max_level:
        return False, "Максимальный уровень уже достигнут"

    if balance < upgrade_cost:
        return False, "Недостаточно сыроежек"

    new_balance = balance - upgrade_cost
    biz_levels[item_id] = current_level + 1
    updates = {'balance': new_balance, 'biz_levels': biz_levels}

    if transaction:
        transaction.update(ref, updates)
    else:
        await ref.update(updates)

    _user_cache.pop((chat_id, user_id), None)
    _dirty_cache.discard((chat_id, user_id))
    return True, None


async def get_top_users(chat_id, limit=10):
    db = get_db()
    ref = db.collection('chats').document(str(chat_id)).collection('users')
    # Адаптивный буфер: запас, чтобы пропустить hidden/banned/banker
    fetch_limit = max(limit * 3, limit + 30)
    docs = await ref.order_by('balance', direction='DESCENDING').limit(fetch_limit).get()

    users = []
    for doc in docs:
        data = doc.to_dict() or {}
        if (
            not data.get('hide_in_top', False)
            and not data.get('is_banned', False)
            and not data.get('is_banker', False)
        ):
            users.append({'user_id': doc.id, **data})
        if len(users) >= limit:
            break
    return users


async def is_user_banker(chat_id, user_id):
    data = await get_user_data(chat_id, user_id)
    return data.get('is_banker', False)


async def get_all_users_in_chat(chat_id):
    db = get_db()
    ref = db.collection('chats').document(str(chat_id)).collection('users')
    return await ref.get()


async def get_user_by_username_or_id(chat_id, identifier):
    """
    Поиск пользователя в чате по ID или @username.
    """
    if not identifier:
        return None, None

    identifier = identifier.strip()

    # Пытаемся как ID
    target_id = None
    try:
        target_id = int(identifier.lstrip("@"))
    except (ValueError, AttributeError):
        pass

    if target_id is not None:
        db = get_db()
        users_ref = db.collection('chats').document(str(chat_id)).collection('users')
        doc = await users_ref.document(str(target_id)).get()
        if doc.exists:
            return target_id, doc.to_dict() or {}

    # Поиск по юзернейму
    username = identifier.lstrip("@").lower()
    if not username:
        return None, None

    # O(1) через индекс кэша
    cached_user_id = _username_to_id_cache.get((chat_id, username))
    if cached_user_id is not None:
        entry = _user_cache.get((chat_id, cached_user_id))
        if entry:
            return cached_user_id, copy.deepcopy(entry['data'])

    # Запрос к БД
    db = get_db()
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')
    query = users_ref.where('username', '==', username).limit(1)
    docs = await query.get()

    if hasattr(docs, '__aiter__'):
        async for doc in docs:
            try:
                return int(doc.id), doc.to_dict() or {}
            except ValueError:
                return doc.id, doc.to_dict() or {}
    else:
        for doc in docs:
            try:
                return int(doc.id), doc.to_dict() or {}
            except ValueError:
                return doc.id, doc.to_dict() or {}

    return None, None


async def wipe_user_data(chat_id, user_id):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        ref = get_user_ref(chat_id, user_id)
        data = await get_user_data(chat_id, user_id)
        full_name = data.get('full_name', 'Player')
        default_data = {
            'balance': 500,
            'bank_deposit': 0,
            'bank_name': None,
            'last_bonus_time': 0,
            'last_daily_time': 0,
            'last_work_time': 0,
            'last_crime_time': 0,
            'inventory': {},
            'biz_levels': {},
            'crypto_portfolio': {},
            'stocks_portfolio': {},
            'pet': {},
            'skills': {},
            'diseases': [],
            'warns': [],
            'is_banned': data.get('is_banned', False),
            'hide_in_top': False,
            'full_name': full_name,
            'is_vip': False,
            'is_banker': False,
            'debts': {},
            'escort_count': 0,
            'crypto_banned': False,
        }
        await ref.set(default_data)
        invalidate_user_cache(chat_id, user_id)
        return True