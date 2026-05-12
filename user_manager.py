import time
import asyncio
import os
import json
import secrets
import logging
from db import get_db
from utils import fire_and_forget

logger = logging.getLogger(__name__)

def get_user_ref(chat_id, user_id):
    db = get_db()
    return db.collection('chats').document(str(chat_id)).collection('users').document(str(user_id))

# Redis setup
redis_client = None
REDIS_URL = os.environ.get("REDIS_URL")
if REDIS_URL:
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.error(f"⚠️ Ошибка подключения к Redis: {e}")

# Гибридный кэш
_user_cache = {}
_dirty_cache = set()
_user_locks = {} # Хранилище локов для предотвращения race condition
CACHE_TTL = 3600 # Увеличим TTL до 1 часа при гибридном хранении
MAX_CACHE_SIZE = 2000

def get_user_lock(chat_id, user_id):
    key = (chat_id, user_id)
    if key not in _user_locks:
        _user_locks[key] = asyncio.Lock()
    return _user_locks[key]

async def get_from_cache(chat_id, user_id):
    key = (chat_id, user_id)
    # 1. Primary: Локальный кэш
    if key in _user_cache:
        cache_entry = _user_cache[key]
        if time.time() - cache_entry["timestamp"] < CACHE_TTL:
            return cache_entry["data"].copy()

    # 2. Secondary: Redis кэш
    if redis_client:
        try:
            redis_key = f"user:{chat_id}:{user_id}"
            val = await redis_client.get(redis_key)
            if val:
                data = json.loads(val)
                # Восстанавливаем в локальный кэш
                await set_in_cache(chat_id, user_id, data, write_to_redis=False)
                return data.copy()
        except Exception as e:
            logger.error(f"⚠️ Ошибка чтения из Redis: {e}")

    return None

async def set_in_cache(chat_id, user_id, data, write_to_redis=True):
    key = (chat_id, user_id)

    # Локальное сохранение (Primary)
    if len(_user_cache) >= MAX_CACHE_SIZE and key not in _user_cache:
        oldest_key = next(iter(_user_cache))
        _user_cache.pop(oldest_key, None)
    
    _user_cache[key] = {"data": data.copy(), "timestamp": time.time()}

    # Опциональное сохранение в Redis
    if write_to_redis and redis_client:
        try:
            redis_key = f"user:{chat_id}:{user_id}"
            await redis_client.setex(redis_key, CACHE_TTL, json.dumps(data))
        except Exception as e:
            logger.error(f"⚠️ Ошибка записи в Redis: {e}")

def mark_dirty(chat_id, user_id):
    _dirty_cache.add((chat_id, user_id))

async def flush_user_data_task():
    """Фоновая задача для синхронизации локального кэша с БД раз в 60 секунд."""
    while True:
        try:
            await asyncio.sleep(60)
            if not _dirty_cache:
                continue
            
            # Собираем пачку
            to_flush = list(_dirty_cache)
            batch = get_db().batch()
            batch_count = 0

            for key in to_flush:
                if key in _user_cache:
                    cached_data = _user_cache[key]["data"]
                    _dirty_cache.discard(key)

                    chat_id, user_id = key
                    ref = get_user_ref(chat_id, user_id)
                    batch.set(ref, cached_data, merge=True)
                    batch_count += 1

                    if batch_count >= 450:
                        await batch.commit()
                        batch = get_db().batch()
                        batch_count = 0
                        await asyncio.sleep(0.5)

            if batch_count > 0:
                await batch.commit()

        except Exception as e:
            logger.error(f"⚠️ Ошибка при пакетной синхронизации кэша: {e}")

async def get_user_data(chat_id, user_id, full_name=None):
    cached_data = await get_from_cache(chat_id, user_id)
    if cached_data:
        if full_name and cached_data.get('full_name') != full_name:
            cached_data['full_name'] = full_name
            await set_in_cache(chat_id, user_id, cached_data)
            mark_dirty(chat_id, user_id)
        return cached_data

    ref = get_user_ref(chat_id, user_id)
    doc = await ref.get()

    if doc.exists:
        data = doc.to_dict()
        if full_name and data.get('full_name') != full_name:
            data['full_name'] = full_name
            mark_dirty(chat_id, user_id)
        await set_in_cache(chat_id, user_id, data)
        return data
    else:
        default_name = full_name if full_name else "Игрок"
        default_data = {
            'balance': 500,
            'bank_deposit': 0,
            'bank_name': None, # Название банка, где открыт счет
            'last_bonus_time': 0,
            'last_daily_time': 0,
            'last_work_time': 0,
            'last_crime_time': 0,
            'inventory': {},
            'biz_levels': {},
            'warns':[],
            'is_banned': False,
            'hide_in_top': False,
            'full_name': default_name,
            'is_vip': False,
            'is_banker': False, # НОВАЯ РОЛЬ БАНКИРА
            'debts': {},
            'escort_count': 0
        }
        await set_in_cache(chat_id, user_id, default_data)
        mark_dirty(chat_id, user_id)
        return default_data

async def update_user_balance(chat_id, user_id, amount, is_debt_repayment=False):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        new_balance = data.get('balance', 0) + amount
        data['balance'] = new_balance
        await set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)
        return new_balance

async def safe_get_snapshot(transaction, ref):
    """
    Безопасно получает snapshot документа внутри транзакции.
    Обрабатывает баги различных версий firestore_async (async_generator error).
    """
    if not transaction:
        return await ref.get()
    
    try:
        # Сначала пробуем через transaction.get()
        res = transaction.get(ref)
        if hasattr(res, '__aiter__'):
            async for s in res: return s
        return await res
    except TypeError:
        # Если упало при await, значит в этой версии библиотеки баг в transaction.get()
        # Пробуем через ref.get()
        try:
            res = ref.get(transaction=transaction)
            if hasattr(res, '__aiter__'):
                async for s in res: return s
            return await res
        except TypeError:
            # Если и это упало, значит баг фундаментальный. Вызываем API напрямую.
            from google.cloud.firestore_v1.base_client import _parse_batch_get
            request, kwargs = ref._prep_batch_get(None, transaction, None, None, None)
            # batch_get_documents обычно возвращает асинхронный итератор
            gen = ref._client._firestore_api.batch_get_documents(request=request, metadata=ref._client._rpc_metadata, **kwargs)
            async for resp in gen:
                return _parse_batch_get(resp, {ref._document_path: ref}, ref._client)
    return None

async def update_user_balance_tr(transaction, chat_id, user_id, amount):
    """Атомарное обновление баланса внутри транзакции Firestore."""
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    
    if snapshot.exists:
        data = snapshot.to_dict()
        new_balance = data.get('balance', 0) + amount
        
        if transaction:
            transaction.update(ref, {'balance': new_balance})
        else:
            await ref.update({'balance': new_balance})
        
        # Обновляем локальный кэш, чтобы он был актуален
        data['balance'] = new_balance
        await set_in_cache(chat_id, user_id, data)
        # Убираем флаг грязного кэша, так как запись уже произведена транзакцией
        _dirty_cache.discard((chat_id, user_id))
        return new_balance
    return None

async def update_user_field(chat_id, user_id, field, value):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        data[field] = value
        await set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

async def check_and_give_bonus(chat_id, user_id, full_name=None):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id, full_name)
        if data.get('is_banned', False):
            return False, {}

        current_time = time.time()
        
        last_bonus = data.get('last_bonus_time', 0)

        if current_time - last_bonus >= 3600:
            bank_deposit = data.get('bank_deposit', 0)
            bank_income = 0
            is_daily = False

            # ФИКСИРОВАННЫЙ БОНУС ДЛЯ ВСЕХ (без налогов на эту сумму)
            base_bonus = 1000 

            # Ежедневные проверки (проценты по старым системным вкладам, не привязанным к банкам)
            if current_time - data.get('last_daily_time', 0) >= 79200:
                is_daily = True
                if bank_deposit > 0 and not data.get('bank_name'):
                    if bank_deposit <= 100000000: bank_income = int(bank_deposit * 0.01)
                    elif bank_deposit <= 1000000000: bank_income = int(bank_deposit * 0.005)
                    else: bank_income = int(bank_deposit * 0.002)

            from shop import ITEMS
            from economy_utils import get_global_tax, calculate_progressive_tax

            base_tax = await get_global_tax()
            neg_lvl = data.get('skills', {}).get('negotiation', 0)
            pet_data = data.get('pet', {})
            pet_id = pet_data.get('id') if isinstance(pet_data, dict) else None
            tax_percent = calculate_progressive_tax(data.get('balance', 0), base_tax, neg_lvl, pet_id)

            from diseases import get_active_diseases
            active_diseases = await get_active_diseases(chat_id, user_id)

            biz_income = 0
            car_income = 0
            inventory = data.get('inventory', {})
            biz_levels = data.get('biz_levels', {})

            for item_id, count in inventory.items():
                item = ITEMS.get(item_id)
                if not item: continue
                if item.get('action') == 'business':
                    level = biz_levels.get(item_id, 1)
                    level_multiplier = 1.0 + 0.5 * (level - 1)
                    inc = int(item.get('income', 0) * level_multiplier) * min(count, 10)
                    if data.get('is_banker', False):
                        inc = int(inc * 0.20)
                    biz_income += inc
                elif item.get('action') == 'car':
                    car_income += item.get('income', 0) * count

            if data.get('is_banker', False):
                # Доходы банкиров от бизнесов и машин урезаны до 10%
                biz_income = int(biz_income * 0.1)
                car_income = int(car_income * 0.1)

            if 'candidiasis' in active_diseases:
                base_bonus = base_bonus // 2

            pet = data.get('pet')
            if 'hpv' in active_diseases:
                pet = None

            # Собака теперь дает бонус только к налогам, убираем множитель к базе
            # if pet and pet.get('id') == 'dog':
            #     base_bonus = int(base_bonus * 1.5)

            extra_income = biz_income + car_income + bank_income
            tax_amt = int(extra_income * (tax_percent / 100.0))
            total_to_hand = base_bonus + extra_income - tax_amt

            if total_to_hand <= 0: return False, {}

            ref = get_user_ref(chat_id, user_id)
            upd = {
                'balance': data.get('balance', 0) + total_to_hand,
                'last_bonus_time': current_time
            }
            if is_daily:
                upd['last_daily_time'] = current_time
                if bank_deposit > 0 and not data.get('bank_name'):
                    upd['bank_deposit'] = bank_deposit + bank_income

            data.update(upd)
            await set_in_cache(chat_id, user_id, data)
            mark_dirty(chat_id, user_id)

            return True, {
                'base': base_bonus, 'business': biz_income, 'car': car_income,
                'tax_percent': tax_percent, 'tax_amount': tax_amt, 'total': total_to_hand,
                'is_banker_bonus': False
            }
        return False, {}

async def add_item_to_inventory(chat_id, user_id, item_name):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        inv = data.get('inventory', {})
        inv[item_name] = inv.get(item_name, 0) + 1

        data['inventory'] = inv
        await set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

async def remove_item_from_inventory(chat_id, user_id, item_name):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        inv = data.get('inventory', {})
        biz_levels = data.get('biz_levels', {})

        if inv.get(item_name, 0) > 0:
            inv[item_name] -= 1
            if inv[item_name] <= 0:
                del inv[item_name]
                if item_name in biz_levels:
                    del biz_levels[item_name]

            data['inventory'] = inv
            data['biz_levels'] = biz_levels
            await set_in_cache(chat_id, user_id, data)
            mark_dirty(chat_id, user_id)
            return True
        return False

async def get_top_users(chat_id, limit=10):
    db = get_db()
    ref = db.collection('chats').document(str(chat_id)).collection('users')
    docs = await ref.order_by('balance', direction='DESCENDING').limit(limit + 10).get()
    
    users =[]
    for doc in docs:
        data = doc.to_dict()
        if not data.get('hide_in_top', False) and not data.get('is_banned', False) and not data.get('is_banker', False):
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
    docs = await ref.get()
    return docs