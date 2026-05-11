import time
from firebase_admin import firestore_async
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import get_db
from escape import escape_html
from user_manager import get_user_data, update_user_balance, update_user_field
from shop import ITEMS
from utils import fire_and_forget
from seasons import get_season_string

router = Router()

_bank_cache = {}
BANK_CACHE_TTL = 10.0

def get_bank_from_cache(chat_id, identifier):
    key = (chat_id, str(identifier).lower())
    if key in _bank_cache:
        cache_entry = _bank_cache[key]
        if time.time() - cache_entry["timestamp"] < BANK_CACHE_TTL:
            return cache_entry["data"].copy()
    return None

def set_bank_in_cache(chat_id, identifier, data):
    # Cache by ID
    banker_id_key = (chat_id, str(data.get('banker_id', identifier)).lower())
    _bank_cache[banker_id_key] = {"data": data.copy(), "timestamp": time.time()}
    # Cache by Name
    if 'name' in data:
        name_key = (chat_id, str(data['name']).lower())
        _bank_cache[name_key] = {"data": data.copy(), "timestamp": time.time()}

@router.message(Command("profile"))
async def cmd_profile(message: types.Message):
    chat_id = message.chat.id
    # Определяем, чей профиль смотрим (свой или чужой через реплай)
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = escape_html(message.reply_to_message.from_user.full_name)
    else:
        target_id = message.from_user.id
        target_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, target_id, target_name)

    vip_status = "💎 VIP" if data.get('is_vip') else "Обычный"
    balance = data.get('balance', 0)
    rep = data.get('reputation', 0)
    clan = escape_html(data.get('clan', 'Нет'))
    warns = len(data.get('warns', []))
    
    # Счётчик эскорта
    escort_count = data.get('escort_count', 0)
    escort_text = f"\n🔞 Выебан(а): {escort_count} раз" if escort_count > 0 else ""

    # --- НОВАЯ ЛОГИКА ДОЛГОВ (ПЕРЕД ИГРОКАМИ И БАНКАМИ) ---
    debts = data.get('debts', {})
    debt_display = ""
    if debts:
        debt_list = []
        for lender_id_str, amount in debts.items():
            if amount > 0:
                if lender_id_str.startswith("bank_"):
                    banker_id = int(lender_id_str.split("_")[1])
                    bank_data = await get_bank_info(chat_id, banker_id)
                    lender_name = escape_html(bank_data.get('name', 'Банк')) if bank_data else 'Банк'
                    debt_list.append(f"🏦 <b>{lender_name}</b> ({amount} сыр.)")
                else:
                    try:
                        lender_data = await get_user_data(chat_id, int(lender_id_str))
                        lender_name = escape_html(lender_data.get('full_name', f"Юзер {lender_id_str}"))
                        debt_list.append(f"👤 <b>{lender_name}</b> ({amount} сыр.)")
                    except ValueError:
                        pass
        
        if debt_list:
            debt_display = f"\n💸 <b>Долги:</b> {', '.join(debt_list)}"
    # --------------------------------------------

    # Брак
    partner_id = data.get('partner')
    partner_text = "Нет"
    if partner_id:
        p_data = await get_user_data(chat_id, partner_id)
        partner_text = escape_html(p_data.get('full_name', f"ID: {partner_id}"))

    # Имущество
    inventory = data.get('inventory', {})
    cars = sum(v for k, v in inventory.items() if ITEMS.get(k, {}).get('cat') == 'cars')
    biz = sum(v for k, v in inventory.items() if ITEMS.get(k, {}).get('cat') == 'biz')

    bank_deposit = data.get('bank_deposit', 0)

    balance_label = await get_season_string("balance", "💰 Баланс")
    bank_label = await get_season_string("bank_label", "🏦 В банке")
    profile_header = await get_season_string("profile", "Профиль")
    
    from seasons import get_glitch_text
    profile_header = await get_glitch_text(profile_header)
    target_name = await get_glitch_text(target_name)

    # Скрываем банк если оффшор и мы смотрим чужой профиль
    if data.get('is_offshore', False) and message.from_user.id != target_id:
        bank_text = f"{bank_label}: <i>Скрыто (Оффшор)</i>\n\n"
    else:
        bank_text = f"{bank_label}: <b>{bank_deposit}</b> сыр.\n\n"
    
    # Статистика сообщений (из отдельной коллекции)
    db = get_db()
    stats_doc = await db.collection('chats').document(str(chat_id)).collection('stats').document(str(target_id)).get()
    msg_count = stats_doc.to_dict().get('all_time', 0) if stats_doc.exists else 0
    
    bio = escape_html(data.get('bio', 'Нет описания.'))
    bio = await get_glitch_text(bio)
    
    text = (
        f"👤 <b>{profile_header}: {target_name}</b>\n"
        f"<i>{bio}</i>\n\n"
        f"Статус: {vip_status}\n"
        f"Репутация: {rep} 📈\n"
        f"Предупреждения: {warns}/3 ⚠️{escort_text}\n"
        f"{debt_display}\n" # Список реальных долгов перед людьми
        f"{balance_label}: <b>{balance}</b> сыр.\n"
        f"{bank_text}"
        f"🛡 Клан: {clan}\n"
        f"💍 Брак: {partner_text}\n\n"
        f"🚗 Машин: {cars}\n"
        f"🏢 Бизнесов: {biz}\n\n"
        f"💬 Сообщений в чате: {msg_count}"
    )

    await message.answer(text)

async def get_bank_info(chat_id: int, identifier):
    cached_data = get_bank_from_cache(chat_id, identifier)
    if cached_data:
        return cached_data

    db = get_db()
    banks_ref = db.collection('chats').document(str(chat_id)).collection('banks')

    # Сначала пробуем по ID банкира
    try:
        banker_id = int(identifier)
        doc = await banks_ref.document(str(banker_id)).get()
        if doc.exists:
            data = doc.to_dict()
            data['banker_id'] = banker_id
            set_bank_in_cache(chat_id, banker_id, data)
            return data
    except ValueError:
        pass

    # Если не ID, ищем по имени банка
    search_name = str(identifier).lower()
    docs = await banks_ref.get()
    for doc in docs:
        b_data = doc.to_dict()
        b_name = b_data.get('name', '').lower()
        if b_name.startswith(search_name) or search_name in b_name:
            b_data['banker_id'] = int(doc.id)
            set_bank_in_cache(chat_id, identifier, b_data)
            return b_data

    return None

async def create_or_update_bank(chat_id: int, banker_id: int, data: dict):
    current_data = await get_bank_info(chat_id, banker_id) or {}
    current_data.update(data)
    current_data['banker_id'] = banker_id
    set_bank_in_cache(chat_id, banker_id, current_data)

    db = get_db()
    bank_ref = db.collection('chats').document(str(chat_id)).collection('banks').document(str(banker_id))
    fire_and_forget(bank_ref.set(data, merge=True))

@firestore_async.transactional
async def process_deposit_tx(transaction, chat_id, user_id, target_banker_id, amount, current_deposit, bank_data):
    from user_manager import update_user_balance_tr, get_user_ref
    # Списываем у игрока
    await update_user_balance_tr(transaction, chat_id, user_id, -amount)
    
    # Обновляем поля игрока
    user_ref = get_user_ref(chat_id, user_id)
    updates = {
        'bank_deposit': current_deposit + amount,
        'bank_name': target_banker_id
    }
    if current_deposit == 0:
        updates['deposit_start_time'] = int(time.time())
    
    if transaction:
        transaction.update(user_ref, updates)
    else:
        await user_ref.update(updates)

    # Обновляем капитал банка
    db = get_db()
    bank_ref = db.collection('chats').document(str(chat_id)).collection('banks').document(str(target_banker_id))
    if transaction:
        transaction.update(bank_ref, {'capital': bank_data.get('capital', 0) + amount})
    else:
        await bank_ref.update({'capital': bank_data.get('capital', 0) + amount})

@firestore_async.transactional
async def process_withdraw_tx(transaction, chat_id, user_id, current_banker_id, amount, current_deposit, bank_data):
    from user_manager import update_user_balance_tr, get_user_ref
    # Добавляем игроку
    await update_user_balance_tr(transaction, chat_id, user_id, amount)
    
    # Обновляем поля игрока
    user_ref = get_user_ref(chat_id, user_id)
    updates = {'bank_deposit': current_deposit - amount}
    if current_deposit - amount == 0:
        updates['bank_name'] = None
        updates['deposit_start_time'] = 0
    
    if transaction:
        transaction.update(user_ref, updates)
    else:
        await user_ref.update(updates)
    
    # Обновляем капитал банка
    db = get_db()
    bank_ref = db.collection('chats').document(str(chat_id)).collection('banks').document(str(current_banker_id))
    if transaction:
        transaction.update(bank_ref, {'capital': bank_data.get('capital', 0) - amount})
    else:
        await bank_ref.update({'capital': bank_data.get('capital', 0) - amount})

@router.message(Command("bank"))
async def cmd_bank(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    args = message.text.split()
    bank_title = await get_season_string("bank_title", "🏦 Банки Сыроежек")
    if len(args) < 2:
        return await message.answer(
            f"{bank_title}\n\n"
            "Вы можете вложить свои деньги в банк под процент.\n"
            "Команды:\n"
            "<code>/bank info [Название или ID]</code> - Информация о банке\n"
            "<code>/bank list</code> - Список всех банков в чате\n"
            "<code>/bank deposit [сумма] [Название или ID]</code>\n"
            "<code>/bank withdraw [сумма]</code> - Снять со своего вклада\n"
            "<code>/bank withdraw all</code> - Снять все деньги\n\n"
            "<i>(Вы можете иметь вклад только в одном банке одновременно.\nКаждый день хранения средств увеличивает ваш процент на +0.5%)</i>"
        )

    action = args[1].lower()

    if action == "list":
        try:
            db = get_db()
            banks_ref = db.collection('chats').document(str(chat_id)).collection('banks')
            docs_iterable = await banks_ref.get()

            docs = []
            if hasattr(docs_iterable, '__aiter__'):
                async for d in docs_iterable:
                    docs.append(d)
            else:
                for d in docs_iterable:
                    docs.append(d)

            if not docs:
                return await message.answer("🏦 В этом чате пока нет банков.")

            text = "🏦 <b>Список Банков:</b>\n\n"
            for doc in docs:
                b_data = doc.to_dict()
                rate = b_data.get('deposit_rate', 3.0)
                text += f"🏛 <b>{escape_html(b_data.get('name', 'Банк'))}</b>\n"
                text += f"ID Банкира: <code>{doc.id}</code>\n"
                text += f"Ставка по вкладу: <b>{rate}%</b> в день\n"
                text += f"Капитал: <b>{b_data.get('capital', 0)}</b> сыр.\n\n"
            return await message.answer(text)
        except Exception as e:
            import traceback
            print(f"Error in /bank list: {e}")
            return await message.answer(f"❌ Ошибка получения списка банков:\n<code>{e}</code>\n{traceback.format_exc()[:300]}")

    if action == "info":
        try:
            if len(args) < 3:
                return await message.answer("Укажите название банка или ID: <code>/bank info [Название]</code>")

            identifier = " ".join(args[2:])
            bank_data = await get_bank_info(chat_id, identifier)
            if not bank_data:
                return await message.answer("🏦 Банк не найден.")

            rate = bank_data.get('deposit_rate', 3.0)
            text = f"🏛 <b>{escape_html(bank_data.get('name', 'Банк'))}</b>\n\n"
            text += f"Владелец (ID): <code>{bank_data['banker_id']}</code>\n"
            text += f"Ставка по вкладу: <b>{rate}%</b> в день\n"
            text += f"Капитал банка: <b>{bank_data.get('capital', 0)}</b> сыр.\n"
            return await message.answer(text)
        except Exception as e:
            return await message.answer(f"❌ Ошибка получения инфо:\n<code>{e}</code>")

    if len(args) < 3: return await message.answer("Укажите сумму или 'all'.")

    data = await get_user_data(chat_id, user_id)
    current_deposit = data.get('bank_deposit', 0)
    current_banker_id = data.get('bank_name') # Храним ID банкира, где лежит вклад

    amount_str = args[2].lower()
    if amount_str == "all" or amount_str == "всё" or amount_str == "все":
        if action == "withdraw":
            amount = current_deposit
        elif action == "deposit":
            amount = data.get('balance', 0)
        else:
            amount = 0
    else:
        try:
            amount = int(args[2])
        except ValueError:
            return await message.answer("Сумма должна быть числом или 'all'.")

    if amount <= 0:
        return await message.answer("Недостаточно средств для этой операции.")

    if action == "deposit":
        try:
            if amount_str == "all" or amount_str == "всё" or amount_str == "все":
                if len(args) < 4:
                    return await message.answer("Укажите название банка или ID: <code>/bank deposit all [Название]</code>")
                identifier = " ".join(args[3:])
            else:
                if len(args) < 4:
                    return await message.answer("Укажите название банка или ID: <code>/bank deposit [сумма] [Название]</code>")
                identifier = " ".join(args[3:])

            bank_data = await get_bank_info(chat_id, identifier)

            if not bank_data:
                return await message.answer("🏦 Банк не найден.")

            target_banker_id = bank_data['banker_id']

            if current_banker_id and current_banker_id != target_banker_id and current_deposit > 0:
                return await message.answer("❌ У вас уже есть активный вклад в другом банке! Сначала снимите все средства.")

            if data.get('balance', 0) < amount:
                return await message.answer("Недостаточно средств на балансе.")

            db = get_db()
            try:
                if hasattr(db, 'transaction'):
                    res = process_deposit_tx(db.transaction(), chat_id, user_id, target_banker_id, amount, current_deposit, bank_data)
                    if hasattr(res, '__aiter__'):
                        async for _ in res: pass
                    else:
                        await res
                else:
                    await process_deposit_tx(None, chat_id, user_id, target_banker_id, amount, current_deposit, bank_data)
                await message.answer(f"✅ Депозит пополнен на {amount} сыр. в банке <b>{escape_html(bank_data.get('name'))}</b>.\nВаш общий вклад: {current_deposit + amount}.")
            except Exception as e:
                import traceback
                print(f"Error in /bank deposit: {e}")
                await message.answer(f"❌ Произошла ошибка при пополнении вклада:\n<code>{e}</code>\n{traceback.format_exc()[:300]}")
        except Exception as e:
            import traceback
            print(f"Error in /bank deposit block: {e}")
            await message.answer(f"❌ Произошла непредвиденная ошибка в депозите:\n<code>{e}</code>\n{traceback.format_exc()[:300]}")

    elif action == "withdraw":
        try:
            if amount <= 0:
                return await message.answer("У вас нет средств на банковском счете.")

            if current_deposit < amount:
                return await message.answer(f"На вашем вкладе только {current_deposit} сыроежек.")

            if not current_banker_id:
                # Для старых вкладов без привязки к банку (сделанных до обновления)
                await update_user_field(chat_id, user_id, 'bank_deposit', current_deposit - amount)
                await update_user_balance(chat_id, user_id, amount)
                return await message.answer(f"💸 Снято {amount} сыроежек со старого системного счета.")

            bank_data = await get_bank_info(chat_id, current_banker_id)
            if not bank_data:
                # Если банк удален, отдаем деньги из "воздуха" как гарантия ЦБ
                await update_user_field(chat_id, user_id, 'bank_deposit', current_deposit - amount)
                await update_user_balance(chat_id, user_id, amount)
                if current_deposit - amount == 0:
                    await update_user_field(chat_id, user_id, 'bank_name', None)
                return await message.answer(f"💸 Ваш банк закрылся, но ЦБ гарантирует вклады. Снято {amount} сыроежек.")

            if bank_data.get('capital', 0) < amount:
                return await message.answer(" У банка недостаточно ликвидности (капитала), чтобы выдать вам деньги сейчас! Банкир выдал слишком много кредитов.")

            db = get_db()
            try:
                if hasattr(db, 'transaction'):
                    res = process_withdraw_tx(db.transaction(), chat_id, user_id, current_banker_id, amount, current_deposit, bank_data)
                    if hasattr(res, '__aiter__'):
                        async for _ in res: pass
                    else:
                        await res
                else:
                    await process_withdraw_tx(None, chat_id, user_id, current_banker_id, amount, current_deposit, bank_data)
                await message.answer(f"💸 Снято {amount} сыроежек со счета.")
            except Exception as e:
                import traceback
                print(f"Error in /bank withdraw: {e}")
                await message.answer(f"❌ Произошла ошибка при снятии со вклада:\n<code>{e}</code>\n{traceback.format_exc()[:300]}")
        except Exception as e:
            import traceback
            print(f"Error in /bank withdraw block: {e}")
            await message.answer(f"❌ Произошла непредвиденная ошибка при снятии вклада:\n<code>{e}</code>\n{traceback.format_exc()[:300]}")
@router.message(F.text.lower().startswith("создать банк"))
async def cmd_create_bank(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    data = await get_user_data(chat_id, user_id)
    if not data.get('is_banker', False):
        return await message.answer("❌ Только официально назначенные Банкиры могут создавать банки.")

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        return await message.answer("Использование: <code>создать банк [Название]</code>")

    bank_name = escape_html(args[2])

    bank_data = await get_bank_info(chat_id, user_id)
    if bank_data:
        return await message.answer(f"❌ У вас уже есть банк: <b>{escape_html(bank_data.get('name'))}</b>")

    await create_or_update_bank(chat_id, user_id, {
        'name': bank_name,
        'capital': 0,
        'banker_name': escape_html(message.from_user.full_name)
    })

    await message.answer(f"🏛 <b>Банк успешно создан!</b>\nНазвание: {bank_name}\nТеперь игроки могут вкладывать деньги в ваш банк с помощью:\n<code>/bank deposit [сумма] {user_id}</code>")

# Удалено снятие прибыли, так как банкиры больше не могут выводить капитал банка напрямую себе

@router.message(Command("bankrate"))
async def cmd_bank_rate(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: <code>/bankrate [процент 3-13]</code>")

    data = await get_user_data(chat_id, user_id)
    if not data.get('is_banker', False):
        return await message.answer("❌ Вы не банкир.")

    try:
        rate = float(args[1])
        if rate < 3 or rate > 13:
            return await message.answer("Процент должен быть от 3 до 13.")
    except ValueError:
        return await message.answer("Процент должен быть числом.")

    bank_data = await get_bank_info(chat_id, user_id)
    if not bank_data:
        return await message.answer("❌ У вас нет открытого банка.")

    await create_or_update_bank(chat_id, user_id, {'deposit_rate': rate})
    await message.answer(f"📈 Процент по вкладам в вашем банке установлен на <b>{rate}%</b> в день.")


@router.message(Command("bank_offshore"))
async def cmd_bank_offshore(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    data = await get_user_data(chat_id, user_id)
    is_offshore = data.get('is_offshore', False)

    if is_offshore:
        await update_user_field(chat_id, user_id, 'is_offshore', False)
        await message.answer("🏝 Вы отключили оффшорный статус. Ваш банковский счет снова виден всем.")
    else:
        price = 500000
        if data.get('balance', 0) < price:
            return await message.answer(f"❌ Оформление оффшорного счета стоит {price} сыроежек. У вас недостаточно средств.")

        await update_user_balance(chat_id, user_id, -price)
        await update_user_field(chat_id, user_id, 'is_offshore', True)
        await message.answer(f"🏝 <b>Оффшорный счет активирован!</b>\nСписано {price} сыр. Теперь ваш вклад скрыт от других игроков в `/profile`.\n<i>(Банк будет снимать 0.5% от вашего депозита при начислении процентов за обслуживание)</i>")

def get_bank_stats_kb(banker_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Главная", callback_data=f"bstat_main_{banker_id}")
    builder.button(text="👥 Вкладчики", callback_data=f"bstat_deps_{banker_id}")
    builder.button(text="🤝 Должники", callback_data=f"bstat_loans_{banker_id}")
    builder.button(text="⚙️ Настройки", callback_data=f"bstat_settings_{banker_id}")
    builder.button(text="⬆️ Улучшения", callback_data=f"bstat_upgrades_{banker_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

async def generate_bank_main_stats(chat_id: int, user_id: int, bank_data: dict) -> str:
    db = get_db()
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')
    user_docs = await users_ref.get()

    total_deposits = 0
    total_depositors = 0
    total_loans_given = 0
    overdue_loans = 0

    import time
    current_time = time.time()

    for user_doc in user_docs:
        u_data = user_doc.to_dict()

        if str(u_data.get('bank_name')) == str(user_id):
            total_deposits += u_data.get('bank_deposit', 0)
            total_depositors += 1

        debts = u_data.get('debts', {})
        for k, v in debts.items():
            if k.startswith(f"bank_{user_id}_") and v > 0:
                total_loans_given += v
                parts = k.split("_")
                if len(parts) >= 3:
                    due_date = int(parts[2])
                    if current_time > due_date:
                        overdue_loans += v

    rate = bank_data.get('deposit_rate', 3.0)
    capital = bank_data.get('capital', 0)

    text = (
        f"📊 <b>Панель управления банком: {escape_html(bank_data.get('name'))}</b>\n\n"
        f"💰 <b>Ликвидность (Капитал):</b> {capital} сыр.\n"
        f"📈 <b>Ставка по вкладам:</b> {rate}%\n\n"
        f"👥 <b>Вкладчиков:</b> {total_depositors}\n"
        f"🏦 <b>Сумма на вкладах:</b> {total_deposits} сыр.\n\n"
        f"🤝 <b>Раздано кредитов:</b> {total_loans_given} сыр.\n"
        f"🚨 <b>Просроченных долгов:</b> {overdue_loans} сыр.\n"
    )
    return text

@router.message(Command("bank_stats"))
async def cmd_bank_stats(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    data = await get_user_data(chat_id, user_id)
    if not data.get('is_banker', False):
        return await message.answer("❌ Эта команда доступна только банкирам.")

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)
    if 'hepatitis' in active_diseases:
        return await message.answer("🦠 <b>Гепатит</b>: У вас нет сил на инкассацию, вам нужен покой.")

    bank_data = await get_bank_info(chat_id, user_id)
    if not bank_data:
        return await message.answer("❌ У вас нет открытого банка.")

    text = await generate_bank_main_stats(chat_id, user_id, bank_data)
    await message.answer(text, reply_markup=get_bank_stats_kb(user_id))


@router.callback_query(F.data.startswith("bstat_"))
async def cb_bank_stats(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    action = parts[1]

    if action == "buyupg":
        upg_type = parts[2]
        banker_id = int(parts[3])
    else:
        banker_id = int(parts[2])


    if callback.from_user.id != banker_id:
        return await callback.answer("❌ Это не ваш банк!", show_alert=True)

    chat_id = callback.message.chat.id
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        return await callback.answer("❌ Банк не найден.", show_alert=True)

    db = get_db()
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')

    if action == "main":
        text = await generate_bank_main_stats(chat_id, banker_id, bank_data)
        await callback.message.edit_text(text, reply_markup=get_bank_stats_kb(banker_id))

    elif action == "deps":
        user_docs = await users_ref.get()
        depositors = []
        for doc in user_docs:
            u_data = doc.to_dict()
            if str(u_data.get('bank_name')) == str(banker_id):
                depositors.append({
                    'name': u_data.get('full_name', 'Unknown'),
                    'deposit': u_data.get('bank_deposit', 0)
                })

        depositors.sort(key=lambda x: x['deposit'], reverse=True)
        text = f"👥 <b>Топ вкладчиков банка {escape_html(bank_data.get('name'))}</b>\n\n"
        if not depositors:
            text += "<i>Вкладов пока нет.</i>"
        else:
            for i, dep in enumerate(depositors[:10], 1):
                text += f"{i}. <b>{escape_html(dep['name'])}</b>: {dep['deposit']} сыр.\n"

        await callback.message.edit_text(text, reply_markup=get_bank_stats_kb(banker_id))

    elif action == "loans":
        user_docs = await users_ref.get()
        debtors = []
        for doc in user_docs:
            u_data = doc.to_dict()
            debts = u_data.get('debts', {})
            total_debt = sum(v for k, v in debts.items() if k.startswith(f"bank_{banker_id}_") and v > 0)
            if total_debt > 0:
                debtors.append({
                    'name': u_data.get('full_name', 'Unknown'),
                    'debt': total_debt
                })

        debtors.sort(key=lambda x: x['debt'], reverse=True)
        text = f"🤝 <b>Топ должников банка {escape_html(bank_data.get('name'))}</b>\n\n"
        if not debtors:
            text += "<i>Должников пока нет.</i>"
        else:
            for i, deb in enumerate(debtors[:10], 1):
                text += f"{i}. <b>{escape_html(deb['name'])}</b>: {deb['debt']} сыр.\n"

        await callback.message.edit_text(text, reply_markup=get_bank_stats_kb(banker_id))

    elif action == "settings":
        rate = bank_data.get('deposit_rate', 3.0)
        text = (
            f"⚙️ <b>Настройки банка {escape_html(bank_data.get('name'))}</b>\n\n"
            f"Текущая ставка: <b>{rate}%</b>\n\n"
            f"📌 <i>Команды:</i>\n"
            f"<code>/bankrate [3-13]</code> - Изменить ставку по вкладам.\n"
            f"<code>/bank_offshore</code> - Скрыть свои средства в оффшоре.\n"
            f"<code>/incass</code> - Запустить рейс инкассаторов.\n"
            f"Выдавать кредиты можно реплаем: <code>кредит [сумма] [%] [срок]</code>"
        )
        await callback.message.edit_text(text, reply_markup=get_bank_stats_kb(banker_id))

    elif action == "upgrades":
        lvl_armor = bank_data.get('upgrade_armor', 0)
        lvl_market = bank_data.get('upgrade_marketing', 0)
        lvl_earnings = bank_data.get('upgrade_earnings', 0)
        lvl_banker = bank_data.get('upgrade_banker', 0)
        lvl_security = bank_data.get('upgrade_security', 0)

        armor_price = 10000000 * (lvl_armor + 1)
        market_price = 15000000 * (lvl_market + 1)
        earn_price = 12000000 * (lvl_earnings + 1)
        banker_price = 20000000 * (lvl_banker + 1)
        sec_price = 15000000 * (lvl_security + 1)

        armor_status = f"{lvl_armor}/5" if lvl_armor < 5 else "МАКС."
        market_status = f"{lvl_market}/5" if lvl_market < 5 else "МАКС."
        earn_status = f"{lvl_earnings}/5" if lvl_earnings < 5 else "МАКС."
        banker_status = f"{lvl_banker}/5" if lvl_banker < 5 else "МАКС."
        sec_status = f"{lvl_security}/5" if lvl_security < 5 else "МАКС."

        text = (
            f"⬆️ <b>Улучшения банка</b>\n"
            f"Капитал: <b>{bank_data.get('capital', 0)}</b> сыр.\n\n"

            f"🛡 <b>Броневики (Инкассация)</b>: Ур. {armor_status}\n"
            f"<i>Снижает начальный риск нападения при /incass.</i>\n"
            f"Цена: {armor_price if lvl_armor < 5 else '—'} сыр.\n\n"

            f"💼 <b>Вместимость мешков</b>: Ур. {earn_status}\n"
            f"<i>+10% к добыче при инкассации за уровень.</i>\n"
            f"Цена: {earn_price if lvl_earnings < 5 else '—'} сыр.\n\n"

            f"👔 <b>Доля Банкира</b>: Ур. {banker_status}\n"
            f"<i>+5% к вашей личной премии от инкассации.</i>\n"
            f"Цена: {banker_price if lvl_banker < 5 else '—'} сыр.\n\n"

            f"📈 <b>Маркетинг (Субсидии)</b>: Ур. {market_status}\n"
            f"<i>+20% к ежедневным субсидиям ЦБ.</i>\n"
            f"Цена: {market_price if lvl_market < 5 else '—'} сыр.\n\n"

            f"🔐 <b>Сейфовая Охрана</b>: Ур. {sec_status}\n"
            f"<i>Снижает шанс, что игроки украдут ваши деньги через /steal (до 5% при макс ур).</i>\n"
            f"Цена: {sec_price if lvl_security < 5 else '—'} сыр."
        )

        builder = InlineKeyboardBuilder()
        if lvl_armor < 5: builder.button(text=f"🛡 Броневики", callback_data=f"bstat_buyupg_armor_{banker_id}")
        if lvl_earnings < 5: builder.button(text=f"💼 Вместимость", callback_data=f"bstat_buyupg_earn_{banker_id}")
        if lvl_banker < 5: builder.button(text=f"👔 Доля", callback_data=f"bstat_buyupg_banker_{banker_id}")
        if lvl_market < 5: builder.button(text=f"📈 Маркетинг", callback_data=f"bstat_buyupg_market_{banker_id}")
        if lvl_security < 5: builder.button(text=f"🔐 Охрана", callback_data=f"bstat_buyupg_sec_{banker_id}")

        builder.button(text="⬅️ Назад", callback_data=f"bstat_main_{banker_id}")
        builder.adjust(2, 2, 1, 1)

        await callback.message.edit_text(text, reply_markup=builder.as_markup())

    elif action == "buyupg":
        upg_type = parts[2]
        banker_id = int(parts[3])

        if callback.from_user.id != banker_id: return

        bank_data = await get_bank_info(chat_id, banker_id)
        capital = bank_data.get('capital', 0)

        if upg_type == "armor":
            lvl = bank_data.get('upgrade_armor', 0)
            if lvl >= 5: return await callback.answer("Максимальный уровень!", show_alert=True)
            price = 10000000 * (lvl + 1)
            if capital < price: return await callback.answer("❌ Недостаточно капитала банка!", show_alert=True)
            await create_or_update_bank(chat_id, banker_id, {'capital': capital - price, 'upgrade_armor': lvl + 1})
            await callback.answer(f"✅ Броневики улучшены до уровня {lvl + 1}!")

        elif upg_type == "earn":
            lvl = bank_data.get('upgrade_earnings', 0)
            if lvl >= 5: return await callback.answer("Максимальный уровень!", show_alert=True)
            price = 12000000 * (lvl + 1)
            if capital < price: return await callback.answer("❌ Недостаточно капитала банка!", show_alert=True)
            await create_or_update_bank(chat_id, banker_id, {'capital': capital - price, 'upgrade_earnings': lvl + 1})
            await callback.answer(f"✅ Вместимость улучшена до уровня {lvl + 1}!")

        elif upg_type == "banker":
            lvl = bank_data.get('upgrade_banker', 0)
            if lvl >= 5: return await callback.answer("Максимальный уровень!", show_alert=True)
            price = 20000000 * (lvl + 1)
            if capital < price: return await callback.answer("❌ Недостаточно капитала банка!", show_alert=True)
            await create_or_update_bank(chat_id, banker_id, {'capital': capital - price, 'upgrade_banker': lvl + 1})
            await callback.answer(f"✅ Доля банкира улучшена до уровня {lvl + 1}!")

        elif upg_type == "market":
            lvl = bank_data.get('upgrade_marketing', 0)
            if lvl >= 5: return await callback.answer("Максимальный уровень!", show_alert=True)
            price = 15000000 * (lvl + 1)
            if capital < price: return await callback.answer("❌ Недостаточно капитала банка!", show_alert=True)
            await create_or_update_bank(chat_id, banker_id, {'capital': capital - price, 'upgrade_marketing': lvl + 1})
            await callback.answer(f"✅ Маркетинг улучшен до уровня {lvl + 1}!")

        elif upg_type == "sec":
            lvl = bank_data.get('upgrade_security', 0)
            if lvl >= 5: return await callback.answer("Максимальный уровень!", show_alert=True)
            price = 15000000 * (lvl + 1)
            if capital < price: return await callback.answer("❌ Недостаточно капитала банка!", show_alert=True)
            await create_or_update_bank(chat_id, banker_id, {'capital': capital - price, 'upgrade_security': lvl + 1})
            await callback.answer(f"✅ Охрана сейфа улучшена до уровня {lvl + 1}!")

        callback.data = f"bstat_upgrades_{banker_id}"
        await cb_bank_stats(callback)

import random
import time

# ================= ИНКАССАЦИЯ (ИГРА ДЛЯ БАНКИРОВ) =================
active_incass = {}

@router.message(Command("incass"))
async def cmd_incass(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    data = await get_user_data(chat_id, user_id)
    if not data.get('is_banker', False):
        return await message.answer("❌ Эта команда доступна только банкирам.")

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)
    if 'hepatitis' in active_diseases:
        return await message.answer("🦠 <b>Гепатит</b>: Вы госпитализированы. Доступ к управлению банком временно закрыт.")

    bank_data = await get_bank_info(chat_id, user_id)
    if not bank_data:
        return await message.answer("❌ У вас нет открытого банка.")

    current_time = int(time.time())
    last_time = bank_data.get('incass_last_time', 0)

    # Кулдаун 5 часов (18000 сек)
    if current_time - last_time < 18000:
        rem_min = (18000 - (current_time - last_time)) // 60
        return await message.answer(f"🚛 Машины на техобслуживании. Следующий рейс будет доступен через {rem_min} мин.")

    if bank_data.get('capital', 0) < 1000000:
        return await message.answer("❌ В капитале банка должно быть минимум 1.000.000 сыроежек (залог на случай ремонта).")

    if data.get('balance', 0) < 500000:
        return await message.answer("❌ У вас на личном счету должно быть минимум 500.000 сыр. для оплаты личной страховки рейса.")

    await create_or_update_bank(chat_id, user_id, {'incass_last_time': current_time})

    lvl_armor = bank_data.get('upgrade_armor', 0)
    base_risk = 15 - (lvl_armor * 2) # Уменьшаем начальный риск с 15%
    if base_risk < 5: base_risk = 5

    lvl_earnings = bank_data.get('upgrade_earnings', 0)
    earning_mult = 1.0 + (lvl_earnings * 0.1) # +10% заработка за каждый уровень

    start_money = int(random.randint(400000, 1000000) * earning_mult)

    # Храним состояние рейса
    incass_id = f"incass_{chat_id}_{user_id}"
    next_risk_jump = random.randint(5, 25) # Случайный прыжок риска
    active_incass[incass_id] = {
        'money': start_money,
        'risk': base_risk,
        'step': 1,
        'earning_mult': earning_mult,
        'next_jump': next_risk_jump
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="🛣 Ехать на следующую точку", callback_data=f"incass_next_{user_id}")
    builder.button(text="🏦 Вернуться в банк", callback_data=f"incass_cashout_{user_id}")
    builder.adjust(1)

    await message.answer(
        f"🚛 <b>Рейс инкассаторов начат!</b>\n\n"
        f"📍 Точка 1 пройдена.\n"
        f"💰 Собрано: <b>{start_money}</b> сыр.\n"
        f"🚨 Текущий риск: <b>{base_risk}%</b> (Прыжок на след. шаге: +{next_risk_jump}%)\n\n"
        f"Что делаем дальше?",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("incass_"))
async def cb_incass(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    action = parts[1]
    banker_id = int(parts[2])

    if callback.from_user.id != banker_id:
        return await callback.answer("Это не ваш рейс!", show_alert=True)

    chat_id = callback.message.chat.id
    incass_id = f"incass_{chat_id}_{banker_id}"

    if incass_id not in active_incass:
        return await callback.message.edit_text("❌ Этот рейс уже завершён.")

    state = active_incass[incass_id]

    bank_data = await get_bank_info(chat_id, banker_id)

    # Бонус банкира от улучшения "Заработок"
    lvl_banker = bank_data.get('upgrade_banker', 0)
    banker_cut = 0.20 + (lvl_banker * 0.05) # База 20%, +5% за уровень (до 45%)

    if action == "cashout":
        money = state['money']
        del active_incass[incass_id]

        banker_profit = int(money * banker_cut)
        bank_profit = money - banker_profit

        await create_or_update_bank(chat_id, banker_id, {'capital': bank_data.get('capital', 0) + bank_profit})
        await update_user_balance(chat_id, banker_id, banker_profit)

        await callback.message.edit_text(
            f"🏦 <b>Машина благополучно вернулась!</b>\n\n"
            f"Общий куш: <b>{money}</b> сыр.\n"
            f"💼 Капитал банка пополнен на: <b>{bank_profit}</b> сыр.\n"
            f"💵 Личная премия банкира: <b>{banker_profit}</b> сыр."
        )

    elif action == "next":
        # Увеличиваем риск
        state['risk'] += state['next_jump']
        current_risk = state['risk']

        # Проверяем нападение
        if random.randint(1, 100) <= current_risk:
            del active_incass[incass_id]

            # Штраф 600к-1млн.
            total_penalty = random.randint(600000, 1000000)

            # 50% платит банк, 50% платит лично банкир (нерф банкиров)
            bank_penalty = total_penalty // 2
            personal_penalty = total_penalty - bank_penalty

            new_capital = max(0, bank_data.get('capital', 0) - bank_penalty)
            await create_or_update_bank(chat_id, banker_id, {'capital': new_capital})

            # Снимаем деньги с личного счета (даже если уйдет в минус)
            await update_user_balance(chat_id, banker_id, -personal_penalty)

            await callback.message.edit_text(
                f"💥 <b>НАПАДЕНИЕ ОПГ! (Шанс был {current_risk}%)</b>\n\n"
                f"Вооруженные бандиты подорвали броневик и украли все собранные <b>{state['money']}</b> сыр.\n\n"
                f"💸 Банк оплатил часть ремонта: <b>-{bank_penalty}</b> сыр. из капитала.\n"
                f"💸 Вы оплатили остаток из своего кармана: <b>-{personal_penalty}</b> сыр."
            )
        else:
            state['step'] += 1
            add_money = int(random.randint(400000, 1000000) * state['earning_mult'])
            state['money'] += add_money

            # Генерируем следующий случайный прыжок риска
            next_risk_jump = random.randint(5, 25)
            state['next_jump'] = next_risk_jump

            builder = InlineKeyboardBuilder()
            builder.button(text="🛣 Ехать на следующую точку", callback_data=f"incass_next_{banker_id}")
            builder.button(text="🏦 Вернуться в банк", callback_data=f"incass_cashout_{banker_id}")
            builder.adjust(1)

            await callback.message.edit_text(
                f"🚛 <b>Рейс продолжается...</b>\n\n"
                f"📍 Точка {state['step']} пройдена.\n"
                f"💰 Найдено: +{add_money}\n"
                f"💵 Всего в кузове: <b>{state['money']}</b> сыр.\n"
                f"🚨 Текущий риск: <b>{current_risk}%</b> (Прыжок на след. шаге: +{next_risk_jump}%)\n\n"
                f"Рискуем дальше?",
                reply_markup=builder.as_markup()
            )
