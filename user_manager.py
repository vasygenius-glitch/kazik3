import time
import asyncio
import secrets
from db import get_db
from utils import fire_and_forget
from admin_logs import log_transaction, check_balance_alert

def get_user_ref(chat_id, user_id):
    db = get_db()
    return db.collection('chats').document(str(chat_id)).collection('users').document(str(user_id))

# Кэш пользователей
_user_cache = {}
_dirty_cache = set()
_user_locks = {} # Хранилище локов для предотвращения race condition
CACHE_TTL = 60.0 

def get_user_lock(chat_id, user_id):
    key = (chat_id, user_id)
    if key not in _user_locks:
        _user_locks[key] = asyncio.Lock()
    return _user_locks[key]

def get_from_cache(chat_id, user_id):
    key = (chat_id, user_id)
    if key in _user_cache:
        cache_entry = _user_cache[key]
        if time.time() - cache_entry["timestamp"] < CACHE_TTL:
            return cache_entry["data"].copy()
    return None

MAX_CACHE_SIZE = 1000

def set_in_cache(chat_id, user_id, data):
    key = (chat_id, user_id)
    if len(_user_cache) >= MAX_CACHE_SIZE and key not in _user_cache:
        # Простая очистка старейшего элемента
        oldest_key = next(iter(_user_cache))
        _user_cache.pop(oldest_key)
    
    _user_cache[key] = {"data": data.copy(), "timestamp": time.time()}

def invalidate_user_cache(chat_id, user_id):
    """Принудительно удаляет профиль из кэша и из грязного списка.
    Используется при банах и вайпах."""
    key = (chat_id, user_id)
    _user_cache.pop(key, None)
    _dirty_cache.discard(key)

    # Также очищаем FSM стейт из redis/memory если сможем
    import os
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        import redis
        try:
            r = redis.from_url(redis_url)
            # Aiogram redis keys for FSM are usually formatted as fsm:{chat_id}:{user_id}:state
            # and fsm:{chat_id}:{user_id}:data. We delete both.
            r.delete(f"fsm:{chat_id}:{user_id}:state", f"fsm:{chat_id}:{user_id}:data")
            r.close()
        except Exception:
            pass

def mark_dirty(chat_id, user_id):
    _dirty_cache.add((chat_id, user_id))

async def flush_user_data_task():
    """Фоновая задача для синхронизации кэша с БД раз в 15 секунд."""
    while True:
        try:
            await asyncio.sleep(15)
            if not _dirty_cache:
                continue
            
            to_flush = list(_dirty_cache)
            for key in to_flush:
                _dirty_cache.discard(key) # Удаляем только то, что собираемся записать
                cached_entry = _user_cache.get(key)
                if cached_entry:
                    ref = get_user_ref(key[0], key[1])
                    # Синхронизируем всё состояние пользователя
                    fire_and_forget(ref.set(cached_entry["data"], merge=True))
        except Exception as e:
            print(f"⚠️ Ошибка при синхронизации кэша: {e}")
            
        # Очистка старых локов для предотвращения утечки памяти
        try:
            current_keys = set(_user_cache.keys())
            lock_keys = list(_user_locks.keys())
            for key in lock_keys:
                if key not in current_keys:
                    lock = _user_locks.get(key)
                    if lock and not lock.locked():
                        _user_locks.pop(key, None)
        except Exception:
            pass

async def get_user_data(chat_id, user_id, full_name=None, username=None):
    cached_data = get_from_cache(chat_id, user_id)
    if cached_data:
        updated = False
        if full_name and cached_data.get('full_name') != full_name:
            cached_data['full_name'] = full_name
            updated = True
        if username and cached_data.get('username') != username:
            cached_data['username'] = username
            updated = True

        if updated:
            set_in_cache(chat_id, user_id, cached_data)
            ref = get_user_ref(chat_id, user_id)
            upd = {}
            if full_name: upd['full_name'] = full_name
            if username: upd['username'] = username
            fire_and_forget(ref.update(upd))
        return cached_data

    ref = get_user_ref(chat_id, user_id)
    doc = await ref.get()

    if doc.exists:
        data = doc.to_dict()
        updated = False
        if full_name and data.get('full_name') != full_name:
            data['full_name'] = full_name
            updated = True
        if username and data.get('username') != username:
            data['username'] = username
            updated = True

        if updated:
            upd = {}
            if full_name: upd['full_name'] = full_name
            if username: upd['username'] = username
            fire_and_forget(ref.update(upd))

        set_in_cache(chat_id, user_id, data)
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
            'username': username,
            'debts': {},
            'escort_count': 0
        }
        set_in_cache(chat_id, user_id, default_data)
        mark_dirty(chat_id, user_id)
        return default_data

async def update_user_balance(chat_id, user_id, amount, min_balance=None, is_debt_repayment=False):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        current_balance = data.get('balance', 0)
        
        if min_balance is not None and current_balance + amount < min_balance:
            return None
            
        new_balance = current_balance + amount
        data['balance'] = new_balance
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

        # WORKER 3: Logging & Anti-Cheat
        if abs(amount) >= 500000:
            fire_and_forget(log_transaction(user_id, data.get('full_name', 'Unknown'), None, "Balance Update", "Change", amount))
        
        fire_and_forget(check_balance_alert(chat_id, user_id, data.get('full_name', 'Player'), new_balance))

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
        
        cached_data = _user_cache.get((chat_id, user_id))
        if cached_data and "data" in cached_data:
            cached_data["data"]['balance'] = new_balance
        
        # WORKER 3: Logging & Anti-Cheat
        if abs(amount) >= 500000:
            fire_and_forget(log_transaction(user_id, data.get('full_name', 'Unknown'), None, "Transaction Update", "Change", amount))
        
        fire_and_forget(check_balance_alert(chat_id, user_id, data.get('full_name', 'Unknown'), new_balance))

        return new_balance
    return None
async def update_user_field(chat_id, user_id, field, value):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        
        # Logging for balance changes in update_user_field (e.g. from admin setbal)
        if field == 'balance':
            old_balance = data.get('balance', 0)
            amount_changed = value - old_balance
            if abs(amount_changed) >= 500000:
                fire_and_forget(log_transaction(user_id, data.get('full_name', 'Unknown'), None, "Balance Set", "Set", amount_changed))
            fire_and_forget(check_balance_alert(chat_id, user_id, data.get('full_name', 'Player'), value))

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

        if current_time - last_bonus >= 14400:
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
            set_in_cache(chat_id, user_id, data)
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
        inv = data.get('inventory', {}).copy()
        from shop import ITEMS
        if item_name not in ITEMS:
            return False

        inv[item_name] = inv.get(item_name, 0) + 1

        data['inventory'] = inv
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)

        # WORKER 3: Inventory Logging
        from shop import ITEMS
        item_info = ITEMS.get(item_name)
        if item_info and item_info.get('price', 0) >= 500000:
            fire_and_forget(log_transaction(user_id, data.get('full_name', 'Unknown'), None, f"Added {item_name}", "Inventory +", item_info['price']))

        return True

async def remove_item_from_inventory(chat_id, user_id, item_name):
    lock = get_user_lock(chat_id, user_id)
    async with lock:
        data = await get_user_data(chat_id, user_id)
        inv = data.get('inventory', {}).copy()
        biz_levels = data.get('biz_levels', {}).copy()

        if inv.get(item_name, 0) > 0:
            inv[item_name] -= 1
            if inv[item_name] <= 0:
                del inv[item_name]
                if item_name in biz_levels:
                    del biz_levels[item_name]

            data['inventory'] = inv
            data['biz_levels'] = biz_levels
            set_in_cache(chat_id, user_id, data)
            mark_dirty(chat_id, user_id)

            # WORKER 3: Inventory Logging
            from shop import ITEMS
            item_info = ITEMS.get(item_name)
            if item_info and item_info.get('price', 0) >= 500000:
                fire_and_forget(log_transaction(user_id, data.get('full_name', 'Unknown'), None, f"Removed {item_name}", "Inventory -", item_info['price']))

            return True
        return False

async def sell_item_tr(transaction, chat_id, user_id, item_id, item_cat, sell_price):
    """Атомарная продажа предмета внутри транзакции."""
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)

    if snapshot.exists:
        data = snapshot.to_dict()
        inv = data.get('inventory', {})
        biz_levels = data.get('biz_levels', {})

        # Verify item exists in inventory
        if inv.get(item_id, 0) > 0:
            inv[item_id] -= 1
            if inv[item_id] <= 0:
                del inv[item_id]
                # If it's a business, we must delete the level too
                if item_cat == 'biz' and item_id in biz_levels:
                    del biz_levels[item_id]

            new_balance = data.get('balance', 0) + sell_price

            updates = {
                'inventory': inv,
                'biz_levels': biz_levels,
                'balance': new_balance
            }

            if transaction:
                transaction.update(ref, updates)
            else:
                await ref.update(updates)

            # Update cache locally
            cached_data = _user_cache.get((chat_id, user_id))
            if cached_data and "data" in cached_data:
                cached_data["data"]['inventory'] = inv
                cached_data["data"]['biz_levels'] = biz_levels
                cached_data["data"]['balance'] = new_balance
                mark_dirty(chat_id, user_id)

            return True
    return False

async def buy_item_tr(transaction, chat_id, user_id, item_id, price_to_deduct, is_vip=False):
    """Атомарная покупка предмета внутри транзакции."""
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    
    if snapshot.exists:
        data = snapshot.to_dict()
        balance = data.get('balance', 0)
        
        if balance < price_to_deduct:
            return False, "Недостаточно денег"
        
        new_balance = balance - price_to_deduct
        updates = {'balance': new_balance}
        
        inv = data.get('inventory', {}).copy()
        if is_vip:
            updates['is_vip'] = True
        else:
            inv[item_id] = inv.get(item_id, 0) + 1
            updates['inventory'] = inv

        if transaction:
            transaction.update(ref, updates)
        else:
            await ref.update(updates)

        # Синхронизация кэша
        cached_data = _user_cache.get((chat_id, user_id))
        if cached_data and "data" in cached_data:
            cached_data["data"]['balance'] = new_balance
            cached_data["data"]['inventory'] = inv
            if is_vip:
                cached_data["data"]['is_vip'] = True
            mark_dirty(chat_id, user_id)
        
        return True, None
    return False, "Пользователь не найден"

async def sell_vip_tr(transaction, chat_id, user_id, sell_price):
    """Атомарная продажа VIP статуса внутри транзакции."""
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    if snapshot.exists:
        data = snapshot.to_dict()
        if not data.get('is_vip'):
            return False
        
        new_balance = data.get('balance', 0) + sell_price
        updates = {'is_vip': False, 'balance': new_balance}
        
        if transaction:
            transaction.update(ref, updates)
        else:
            await ref.update(updates)

        # Синхронизация кэша
        cached_data = _user_cache.get((chat_id, user_id))
        if cached_data and "data" in cached_data:
            cached_data["data"]['is_vip'] = False
            cached_data["data"]['balance'] = new_balance
            mark_dirty(chat_id, user_id)
        
        return True
    return False

async def upgrade_business_tr(transaction, chat_id, user_id, item_id, upgrade_cost, max_level):
    """Атомарное улучшение бизнеса внутри транзакции."""
    ref = get_user_ref(chat_id, user_id)
    snapshot = await safe_get_snapshot(transaction, ref)
    
    if snapshot.exists:
        data = snapshot.to_dict()
        balance = data.get('balance', 0)
        biz_levels = data.get('biz_levels', {}).copy()
        inventory = data.get('inventory', {})
        
        if inventory.get(item_id, 0) <= 0:
            return False, "У вас нет этого бизнеса"
            
        current_level = biz_levels.get(item_id, 1)
        if current_level >= max_level:
            return False, "Максимальный уровень уже достигнут"
            
        if balance < upgrade_cost:
            return False, "Недостаточно сыроежек"
            
        new_balance = balance - upgrade_cost
        biz_levels[item_id] = current_level + 1
        
        updates = {
            'balance': new_balance,
            'biz_levels': biz_levels
        }
        
        if transaction:
            transaction.update(ref, updates)
        else:
            await ref.update(updates)
            
        # Синхронизация кэша
        cached_data = _user_cache.get((chat_id, user_id))
        if cached_data and "data" in cached_data:
            cached_data["data"]['balance'] = new_balance
            cached_data["data"]['biz_levels'] = biz_levels
            mark_dirty(chat_id, user_id)
        return True, None
    return False, "Пользователь не найден"


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

async def get_user_by_username_or_id(chat_id, identifier):
    """
    Поиск пользователя в конкретном чате по ID или юзернейму.
    identifier может быть "12345" или "@username".
    """
    db = get_db()
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')

    # Пытаемся как ID
    target_id = None
    try:
        target_id = int(identifier.replace("@", ""))
    except ValueError:
        pass

    if target_id:
        doc = await users_ref.document(str(target_id)).get()
        if doc.exists:
            return target_id, doc.to_dict()

    # Если не ID или ID не найден, ищем по юзернейму
    username = identifier.replace("@", "").lower()

    # Сначала ищем в кэше (быстрее)
    for key, entry in _user_cache.items():
        if key[0] == chat_id:
            u_name = entry['data'].get('username', '').lower()
            if u_name == username:
                return key[1], entry['data']

    # Если в кэше нет, ищем в БД
    docs = await users_ref.get()
    if hasattr(docs, '__aiter__'):
        async for doc in docs:
            d = doc.to_dict()
            if d.get('username', '').lower() == username:
                return int(doc.id), d
    else:
        for doc in docs:
            d = doc.to_dict()
            if d.get('username', '').lower() == username:
                return int(doc.id), d

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
            'crypto_banned': False
        }
        await ref.set(default_data)
        invalidate_user_cache(chat_id, user_id)
        return True
