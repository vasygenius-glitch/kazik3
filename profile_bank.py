import time
import random
import traceback
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
from config import CREATOR_ID

router = Router()

# ===================== КОНСТАНТЫ =====================
BANK_CACHE_TTL = 10.0

# Banking
MIN_DEPOSIT_RATE = 3.0
MAX_DEPOSIT_RATE = 13.0
DEFAULT_DEPOSIT_RATE = 3.0
OFFSHORE_PRICE = 500_000

# Incassation
INCASS_COOLDOWN = 18_000        # 5 ч
INCASS_MIN_CAPITAL = 1_000_000
INCASS_MIN_BALANCE = 500_000
INCASS_BASE_RISK = 15
INCASS_MIN_RISK = 5
INCASS_MAX_RISK = 100           # cap при отображении/проверке
INCASS_REWARD_MIN = 400_000
INCASS_REWARD_MAX = 1_000_000
INCASS_PENALTY_MIN = 600_000
INCASS_PENALTY_MAX = 1_000_000
INCASS_BANKER_BASE_CUT = 0.20
INCASS_BANKER_LVL_CUT = 0.05

# Shadow audit
AUDIT_COOLDOWN = 3600
AUDIT_MIN_TARGET_BALANCE = 1000
AUDIT_SUCCESS_CHANCE = 0.25
AUDIT_CONFISCATE_RATE = 0.10
AUDIT_CONFISCATE_MAX = 1_000_000
AUDIT_FAIL_PENALTY = 200_000

# Forge
FORGE_COOLDOWN = 36_000        # 10 ч
FORGE_AMOUNT = 7_000_000
FORGE_AUDIT_DURATION = 7200    # 2 ч
FORGE_AUDIT_FINE_CHANCE = 0.10
FORGE_AUDIT_FINE = 15_000_000

# Investments
INVEST_MIN_CAPITAL = 5_000_000
INVEST_RATIO = 0.3
INVEST_LOSS_RATIO = 0.8

# Upgrades
MAX_UPGRADE_LEVEL = 5
UPGRADES_CFG = {
    'armor':  {'field': 'upgrade_armor',     'price': 10_000_000, 'name': 'Броневики'},
    'earn':   {'field': 'upgrade_earnings',  'price': 12_000_000, 'name': 'Вместимость'},
    'banker': {'field': 'upgrade_banker',    'price': 20_000_000, 'name': 'Доля банкира'},
    'market': {'field': 'upgrade_marketing', 'price': 15_000_000, 'name': 'Маркетинг'},
    'sec':    {'field': 'upgrade_security',  'price': 15_000_000, 'name': 'Охрана сейфа'},
}

# Investment config
INVEST_CFG = {
    'safe': {'chance': 0.95, 'profit': 0.07, 'name': "Гос. Облигации"},
    'mid':  {'chance': 0.55, 'profit': 0.35, 'name': "Венчурный Фонд"},
    'risk': {'chance': 0.22, 'profit': 1.10, 'name': "Крипто-Арбитраж"},
}

# Lobby
LOBBY_CFG = {
    'golden': {'price': 15_000_000, 'hours': 4, 'name': "Золотой Век"},
    'tax':    {'price': 10_000_000, 'hours': 6, 'name': "Налоговый Рай"},
    'work':   {'price': 12_000_000, 'hours': 4, 'name': "Индустриализация"},
    'crime':  {'price': 20_000_000, 'hours': 3, 'name': "Криминальная Амнистия"},
}

ALL_KEYWORDS = {"all", "всё", "все"}

# ===================== КЭШ =====================
_bank_cache = {}

def get_bank_from_cache(chat_id, identifier):
    key = (chat_id, str(identifier).lower())
    cache_entry = _bank_cache.get(key)
    if cache_entry:
        if time.time() - cache_entry["timestamp"] < BANK_CACHE_TTL:
            return cache_entry["data"].copy()
        # удаляем протухшую запись
        _bank_cache.pop(key, None)
    return None

def set_bank_in_cache(chat_id, identifier, data):
    now = time.time()
    banker_id_key = (chat_id, str(data.get('banker_id', identifier)).lower())
    _bank_cache[banker_id_key] = {"data": data.copy(), "timestamp": now}
    name = data.get('name')
    if name:
        name_key = (chat_id, str(name).lower())
        _bank_cache[name_key] = {"data": data.copy(), "timestamp": now}

def invalidate_bank_cache(chat_id, banker_id=None, name=None):
    if banker_id is not None:
        _bank_cache.pop((chat_id, str(banker_id).lower()), None)
    if name:
        _bank_cache.pop((chat_id, str(name).lower()), None)

# ===================== ВСПОМОГАТЕЛЬНОЕ =====================
async def _collect_docs(docs):
    """Унифицирует обход документов Firestore (sync/async iterable)."""
    result = []
    if hasattr(docs, '__aiter__'):
        async for d in docs:
            result.append(d)
    else:
        for d in docs:
            result.append(d)
    return result

def _parse_amount(amount_str: str, current_value: int):
    """Парсит сумму: число или 'all/все/всё' → current_value, иначе ValueError."""
    if amount_str.lower() in ALL_KEYWORDS:
        return current_value
    return int(amount_str)

# ===================== /profile =====================
@router.message(Command("profile"))
async def cmd_profile(message: types.Message):
    chat_id = message.chat.id
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = escape_html(message.reply_to_message.from_user.full_name)
    else:
        target_id = message.from_user.id
        target_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, target_id, target_name)

    vip_status = "💎 VIP" if data.get('is_vip') else "Обычный"

    role_text = ""
    if data.get('is_frontman'):
        role_text = "\n🎭 Роль: <b>Фронтмен</b>"
    elif str(target_id) == str(CREATOR_ID):
        role_text = "\n👑 Роль: <b>Создатель</b>"

    balance = data.get('balance', 0)
    rep = data.get('reputation', 0)
    clan = escape_html(data.get('clan', 'Нет'))
    warns = len(data.get('warns', []))

    escort_count = data.get('escort_count', 0)
    escort_text = f"\n🔞 Выебан(а): {escort_count} раз" if escort_count > 0 else ""

    # --- ДОЛГИ ---
    debts = data.get('debts', {})
    debt_display = ""
    if debts:
        debt_list = []
        for lender_id_str, amount in debts.items():
            if amount <= 0:
                continue
            if lender_id_str.startswith("bank_"):
                try:
                    banker_id = int(lender_id_str.split("_")[1])
                except (ValueError, IndexError):
                    continue
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

    # --- БРАК ---
    partner_id = data.get('partner')
    partner_text = "Нет"
    if partner_id:
        p_data = await get_user_data(chat_id, partner_id)
        partner_text = escape_html(p_data.get('full_name', f"ID: {partner_id}"))

    # --- ИМУЩЕСТВО ---
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

    # Оффшор виден только владельцу
    if data.get('is_offshore', False) and message.from_user.id != target_id:
        bank_text = f"{bank_label}: <i>Скрыто (Оффшор)</i>\n\n"
    else:
        bank_text = f"{bank_label}: <b>{bank_deposit}</b> сыр.\n\n"

    # Статистика сообщений
    db = get_db()
    stats_doc = await db.collection('chats').document(str(chat_id)) \
                        .collection('stats').document(str(target_id)).get()
    msg_count = stats_doc.to_dict().get('all_time', 0) if stats_doc.exists else 0

    bio = escape_html(data.get('bio', 'Нет описания.'))
    bio = await get_glitch_text(bio)

    text = (
        f"👤 <b>{profile_header}: {target_name}</b>\n"
        f"<i>{bio}</i>\n\n"
        f"Статус: {vip_status}{role_text}\n"
        f"Репутация: {rep} 📈\n"
        f"Предупреждения: {warns}/3 ⚠️{escort_text}\n"
        f"{debt_display}\n"
        f"{balance_label}: <b>{balance}</b> сыр.\n"
        f"{bank_text}"
        f"🛡 Клан: {clan}\n"
        f"💍 Брак: {partner_text}\n\n"
        f"🚗 Машин: {cars}\n"
        f"🏢 Бизнесов: {biz}\n\n"
        f"💬 Сообщений в чате: {msg_count}"
    )

    await message.answer(text)

# ===================== РАБОТА С БАНКАМИ =====================
async def get_bank_info(chat_id: int, identifier):
    cached_data = get_bank_from_cache(chat_id, identifier)
    if cached_data:
        return cached_data

    db = get_db()
    banks_ref = db.collection('chats').document(str(chat_id)).collection('banks')

    # 1) Пробуем по ID банкира
    try:
        banker_id = int(identifier)
        doc = await banks_ref.document(str(banker_id)).get()
        if doc.exists:
            data = doc.to_dict()
            data['banker_id'] = banker_id
            set_bank_in_cache(chat_id, banker_id, data)
            return data
    except (ValueError, TypeError):
        pass

    # 2) Поиск по имени
    search_name = str(identifier).lower().strip()
    if not search_name:
        return None
    docs_raw = await banks_ref.get()
    docs = await _collect_docs(docs_raw)
    for doc in docs:
        b_data = doc.to_dict() or {}
        b_name = (b_data.get('name') or '').lower()
        if b_name and (b_name.startswith(search_name) or search_name in b_name):
            try:
                b_data['banker_id'] = int(doc.id)
            except ValueError:
                b_data['banker_id'] = doc.id
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

# ===================== ТРАНЗАКЦИИ ВКЛАДОВ =====================
@firestore_async.async_transactional
async def process_deposit_tx(transaction, chat_id, user_id, target_banker_id, amount):
    from user_manager import get_user_ref, safe_get_snapshot
    db = get_db()
    bank_ref = db.collection('chats').document(str(chat_id)).collection('banks').document(str(target_banker_id))
    user_ref = get_user_ref(chat_id, user_id)

    # ВСЕ чтения сначала
    doc_snapshot = await safe_get_snapshot(transaction, bank_ref)
    if not doc_snapshot.exists:
        raise ValueError("Банк не найден.")
    bank_data = doc_snapshot.to_dict() or {}

    user_snapshot = await safe_get_snapshot(transaction, user_ref)
    user_data = user_snapshot.to_dict() if user_snapshot and user_snapshot.exists else {}

    current_balance = int(user_data.get('balance', 0) or 0)

    if amount == -1:  # all
        amount = current_balance

    if amount <= 0:
        raise ValueError("Сумма должна быть положительной.")
    if current_balance < amount:
        raise ValueError("Недостаточно средств на балансе.")

    current_deposit = user_data.get('bank_deposit', 0)
    current_banker_id = user_data.get('bank_name')

    if current_banker_id and str(current_banker_id) != str(target_banker_id) and current_deposit > 0:
        raise ValueError("У вас уже есть активный вклад в другом банке! Сначала снимите все средства.")

    # Записи
    updates = {
        'balance': current_balance - amount,
        'bank_deposit': current_deposit + amount,
        'bank_name': target_banker_id,
    }
    if current_deposit == 0:
        updates['deposit_start_time'] = int(time.time())

    if transaction:
        transaction.update(user_ref, updates)
    else:
        await user_ref.update(updates)

    new_capital = bank_data.get('capital', 0) + amount
    if transaction:
        transaction.update(bank_ref, {'capital': new_capital})
    else:
        await bank_ref.update({'capital': new_capital})

    return amount, current_deposit + amount


@firestore_async.async_transactional
async def process_withdraw_tx(transaction, chat_id, user_id, current_banker_id, amount):
    from user_manager import get_user_ref, safe_get_snapshot
    db = get_db()
    bank_ref = db.collection('chats').document(str(chat_id)).collection('banks').document(str(current_banker_id))
    user_ref = get_user_ref(chat_id, user_id)

    # Все чтения первыми
    doc_snapshot = await safe_get_snapshot(transaction, bank_ref)
    bank_data = doc_snapshot.to_dict() if doc_snapshot.exists else {}

    user_snapshot = await safe_get_snapshot(transaction, user_ref)
    user_data = user_snapshot.to_dict() if user_snapshot and user_snapshot.exists else {}

    current_deposit = user_data.get('bank_deposit', 0)
    current_balance = int(user_data.get('balance', 0) or 0)

    if amount == -1:  # all
        amount = current_deposit

    if amount <= 0:
        raise ValueError("Сумма должна быть положительной.")
    if current_deposit < amount:
        raise ValueError(f"На вашем вкладе только {current_deposit} сыроежек.")

    # Если банк есть — проверяем ликвидность; если нет — система-гарант выдаёт
    if doc_snapshot.exists:
        if bank_data.get('capital', 0) < amount:
            raise ValueError("У банка недостаточно ликвидности (капитала), чтобы выдать вам деньги сейчас.")
        new_capital = bank_data.get('capital', 0) - amount
        if transaction:
            transaction.update(bank_ref, {'capital': new_capital})
        else:
            await bank_ref.update({'capital': new_capital})

    updates = {
        'balance': current_balance + amount,
        'bank_deposit': current_deposit - amount
    }
    if current_deposit - amount <= 0:
        updates['bank_name'] = None
        updates['deposit_start_time'] = 0

    if transaction:
        transaction.update(user_ref, updates)
    else:
        await user_ref.update(updates)

    return amount

# ===================== /bank =====================
@router.message(Command("bank", prefix="!/"))
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
            "<i>(Вы можете иметь вклад только в одном банке одновременно.\n"
            "Каждый день хранения средств увеличивает ваш процент на +0.5%)</i>"
        )

    action = args[1].lower()

    # ---------- LIST ----------
    if action == "list":
        try:
            db = get_db()
            banks_ref = db.collection('chats').document(str(chat_id)).collection('banks')
            docs_raw = await banks_ref.get()
            docs = await _collect_docs(docs_raw)

            if not docs:
                return await message.answer("🏦 В этом чате пока нет банков.")

            text = "🏦 <b>Список Банков:</b>\n\n"
            for doc in docs:
                b_data = doc.to_dict() or {}
                rate = b_data.get('deposit_rate', DEFAULT_DEPOSIT_RATE)
                text += (
                    f"🏛 <b>{escape_html(b_data.get('name', 'Банк'))}</b>\n"
                    f"ID Банкира: <code>{doc.id}</code>\n"
                    f"Ставка по вкладу: <b>{rate}%</b> в день\n"
                    f"Капитал: <b>{b_data.get('capital', 0)}</b> сыр.\n\n"
                )
            return await message.answer(text)
        except Exception as e:
            print(f"Error in /bank list: {e}\n{traceback.format_exc()}")
            return await message.answer(f"❌ Ошибка получения списка банков:\n<code>{escape_html(str(e))}</code>")

    # ---------- INFO ----------
    if action == "info":
        try:
            if len(args) < 3:
                return await message.answer("Укажите название банка или ID: <code>/bank info [Название]</code>")

            identifier = " ".join(args[2:])
            bank_data = await get_bank_info(chat_id, identifier)
            if not bank_data:
                return await message.answer("🏦 Банк не найден.")

            rate = bank_data.get('deposit_rate', DEFAULT_DEPOSIT_RATE)
            text = (
                f"🏛 <b>{escape_html(bank_data.get('name', 'Банк'))}</b>\n\n"
                f"Владелец (ID): <code>{bank_data.get('banker_id', '?')}</code>\n"
                f"Ставка по вкладу: <b>{rate}%</b> в день\n"
                f"Капитал банка: <b>{bank_data.get('capital', 0)}</b> сыр.\n"
            )
            return await message.answer(text)
        except Exception as e:
            print(f"Error in /bank info: {e}\n{traceback.format_exc()}")
            return await message.answer(f"❌ Ошибка получения инфо:\n<code>{escape_html(str(e))}</code>")

    # ---------- DEPOSIT / WITHDRAW ----------
    if len(args) < 3:
        return await message.answer("Укажите сумму или 'all'.")

    data = await get_user_data(chat_id, user_id)
    current_deposit = data.get('bank_deposit', 0)
    current_banker_id = data.get('bank_name')

    amount_str = args[2].lower()
    is_all = amount_str in ALL_KEYWORDS

    if is_all:
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

    # ---------- DEPOSIT ----------
    if action == "deposit":
        try:
            if len(args) < 4:
                usage = "deposit all [Название]" if is_all else "deposit [сумма] [Название]"
                return await message.answer(f"Укажите название банка или ID: <code>/bank {usage}</code>")

            identifier = " ".join(args[3:])
            bank_data = await get_bank_info(chat_id, identifier)
            if not bank_data:
                return await message.answer("🏦 Банк не найден.")

            target_banker_id = bank_data['banker_id']
            tx_amount = -1 if is_all else amount

            db = get_db()
            tx = db.transaction() if hasattr(db, 'transaction') else None
            try:
                from user_manager import get_user_lock, invalidate_user_cache
                lock = get_user_lock(chat_id, user_id)
                async with lock:
                    actual_amount, total_dep = await process_deposit_tx(
                        tx, chat_id, user_id, target_banker_id, tx_amount
                    )
                    invalidate_user_cache(chat_id, user_id)

                invalidate_bank_cache(chat_id, target_banker_id, bank_data.get('name'))

                await message.answer(
                    f"✅ Депозит пополнен на {actual_amount} сыр. "
                    f"в банке <b>{escape_html(bank_data.get('name', 'Банк'))}</b>.\n"
                    f"Ваш общий вклад: {total_dep}."
                )
            except ValueError as ve:
                await message.answer(f"❌ {ve}")
            except Exception as e:
                print(f"Error in /bank deposit: {e}\n{traceback.format_exc()}")
                await message.answer(f"❌ Произошла ошибка при пополнении вклада:\n<code>{escape_html(str(e))}</code>")
        except Exception as e:
            print(f"Error in /bank deposit block: {e}\n{traceback.format_exc()}")
            await message.answer(f"❌ Непредвиденная ошибка в депозите:\n<code>{escape_html(str(e))}</code>")

    # ---------- WITHDRAW ----------
    elif action == "withdraw":
        try:
            tx_amount = -1 if is_all else amount

            if not current_banker_id:
                # Старый системный счёт
                if current_deposit <= 0:
                    return await message.answer("У вас нет средств на банковском счете.")
                actual_withdraw = min(current_deposit if is_all else amount, current_deposit)
                await update_user_field(chat_id, user_id, 'bank_deposit', current_deposit - actual_withdraw)
                await update_user_balance(chat_id, user_id, actual_withdraw)
                return await message.answer(f"💸 Снято {actual_withdraw} сыроежек со старого системного счета.")

            db = get_db()
            tx = db.transaction() if hasattr(db, 'transaction') else None
            try:
                from user_manager import get_user_lock, invalidate_user_cache
                lock = get_user_lock(chat_id, user_id)
                async with lock:
                    actual_withdrawn = await process_withdraw_tx(
                        tx, chat_id, user_id, current_banker_id, tx_amount
                    )
                    invalidate_user_cache(chat_id, user_id)

                invalidate_bank_cache(chat_id, current_banker_id)

                await message.answer(f"💸 Снято {actual_withdrawn} сыроежек со счета.")
            except ValueError as ve:
                await message.answer(f"❌ {ve}")
            except Exception as e:
                print(f"Error in /bank withdraw: {e}\n{traceback.format_exc()}")
                await message.answer(f"❌ Произошла ошибка при снятии со вклада:\n<code>{escape_html(str(e))}</code>")
        except Exception as e:
            print(f"Error in /bank withdraw block: {e}\n{traceback.format_exc()}")
            await message.answer(f"❌ Непредвиденная ошибка при снятии вклада:\n<code>{escape_html(str(e))}</code>")
    else:
        await message.answer("Неизвестное действие. Используйте /bank без аргументов для справки.")


# ===================== СОЗДАНИЕ БАНКА =====================
@router.message(F.text.lower().startswith("создать банк"))
async def cmd_create_bank(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    data = await get_user_data(chat_id, user_id)
    if not data.get('is_banker', False):
        return await message.answer("❌ Только официально назначенные Банкиры могут создавать банки.")

    args = message.text.split(maxsplit=2)
    if len(args) < 3 or not args[2].strip():
        return await message.answer("Использование: <code>создать банк [Название]</code>")

    # Сохраняем сырое имя, экранируем только при выводе
    bank_name_raw = args[2].strip()[:60]  # обрезаем по длине

    existing = await get_bank_info(chat_id, user_id)
    if existing:
        return await message.answer(f"❌ У вас уже есть банк: <b>{escape_html(existing.get('name', 'Банк'))}</b>")

    await create_or_update_bank(chat_id, user_id, {
        'name': bank_name_raw,
        'capital': 0,
        'banker_name': message.from_user.full_name,
        'deposit_rate': DEFAULT_DEPOSIT_RATE,
    })

    await message.answer(
        f"🏛 <b>Банк успешно создан!</b>\n"
        f"Название: {escape_html(bank_name_raw)}\n"
        f"Теперь игроки могут вкладывать деньги в ваш банк:\n"
        f"<code>/bank deposit [сумма] {user_id}</code>"
    )


# ===================== /bankrate =====================
@router.message(Command("bankrate"))
async def cmd_bank_rate(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    args = message.text.split()
    if len(args) < 2:
        return await message.answer(f"Использование: <code>/bankrate [процент {int(MIN_DEPOSIT_RATE)}-{int(MAX_DEPOSIT_RATE)}]</code>")

    data = await get_user_data(chat_id, user_id)
    if not data.get('is_banker', False):
        return await message.answer("❌ Вы не банкир.")

    try:
        rate = float(args[1].replace(',', '.'))
    except ValueError:
        return await message.answer("Процент должен быть числом.")

    if rate < MIN_DEPOSIT_RATE or rate > MAX_DEPOSIT_RATE:
        return await message.answer(f"Процент должен быть от {MIN_DEPOSIT_RATE} до {MAX_DEPOSIT_RATE}.")

    bank_data = await get_bank_info(chat_id, user_id)
    if not bank_data:
        return await message.answer("❌ У вас нет открытого банка.")

    await create_or_update_bank(chat_id, user_id, {'deposit_rate': rate})
    await message.answer(f"📈 Процент по вкладам в вашем банке установлен на <b>{rate}%</b> в день.")


# ===================== ОФФШОР =====================
@router.message(Command("bank_offshore"))
async def cmd_bank_offshore(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    data = await get_user_data(chat_id, user_id)
    is_offshore = data.get('is_offshore', False)

    if is_offshore:
        await update_user_field(chat_id, user_id, 'is_offshore', False)
        return await message.answer("🏝 Вы отключили оффшорный статус. Ваш банковский счет снова виден всем.")

    if data.get('balance', 0) < OFFSHORE_PRICE:
        return await message.answer(f"❌ Оформление оффшорного счета стоит {OFFSHORE_PRICE} сыроежек. У вас недостаточно средств.")

    db = get_db()
    from user_manager import update_user_balance, get_user_ref

    @firestore_async.async_transactional
    async def activate_offshore_tx(transaction, chat_id, user_id, price):
        from user_manager import safe_get_snapshot
        user_ref = get_user_ref(chat_id, user_id)
        snapshot = await safe_get_snapshot(transaction, user_ref)
        if not snapshot.exists:
            raise ValueError("Пользователь не найден")
        user_data = snapshot.to_dict() or {}
        current_balance = int(user_data.get('balance', 0) or 0)
        if current_balance < price:
            raise ValueError("Недостаточно средств")
        updates = {
            'balance': current_balance - price,
            'is_offshore': True
        }
        transaction.update(user_ref, updates)

    try:
        from user_manager import get_user_lock, invalidate_user_cache
        lock = get_user_lock(chat_id, user_id)
        async with lock:
            await activate_offshore_tx(db.transaction(), chat_id, user_id, OFFSHORE_PRICE)
            invalidate_user_cache(chat_id, user_id)

        await message.answer(
            f"🏝 <b>Оффшорный счет активирован!</b>\n"
            f"Списано {OFFSHORE_PRICE} сыр. Теперь ваш вклад скрыт от других игроков в /profile.\n"
            f"<i>(Банк будет снимать 0.5% от вашего депозита при начислении процентов за обслуживание)</i>"
        )
    except ValueError as ve:
        await message.answer(f"❌ {ve}")
    except Exception as e:
        print(f"Offshore error: {e}\n{traceback.format_exc()}")
        await message.answer("❌ Ошибка при активации оффшора.")


# ===================== KEYBOARD =====================
def get_bank_stats_kb(banker_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Главная", callback_data=f"bstat_main_{banker_id}")
    builder.button(text="👥 Вкладчики", callback_data=f"bstat_deps_{banker_id}")
    builder.button(text="🤝 Должники", callback_data=f"bstat_loans_{banker_id}")
    builder.button(text="⚙️ Настройки", callback_data=f"bstat_settings_{banker_id}")
    builder.button(text="⬆️ Улучшения", callback_data=f"bstat_upgrades_{banker_id}")
    builder.button(text="💼 Схемы", callback_data=f"bstat_schemes_{banker_id}")
    builder.adjust(2, 2, 2)
    return builder.as_markup()


# ===================== ГЛАВНАЯ СТАТИСТИКА БАНКА =====================
async def generate_bank_main_stats(chat_id: int, user_id: int, bank_data: dict) -> str:
    current_time = int(time.time())
    audit_risk = bank_data.get('audit_risk_until', 0)
    audit_warning = ""
    if current_time < audit_risk:
        audit_warning = "\n⚠️ <b>ВНИМАНИЕ: ЦБ ведет проверку ваших счетов!</b>"
        if random.random() < FORGE_AUDIT_FINE_CHANCE:
            new_capital = max(0, bank_data.get('capital', 0) - FORGE_AUDIT_FINE)
            await create_or_update_bank(chat_id, user_id, {
                'capital': new_capital,
                'audit_risk_until': 0,
            })
            bank_data['capital'] = new_capital
            bank_data['audit_risk_until'] = 0
            audit_warning = (
                f"\n🚨 <b>АУДИТ ПРОВАЛЕН!</b> ЦБ обнаружил нарушения и выписал штраф "
                f"<b>{FORGE_AUDIT_FINE}</b> сыр.!"
            )

    db = get_db()
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')

    # --- Вкладчики ---
    dep_docs_raw = await users_ref.where('bank_name', '==', user_id).get()
    dep_docs = await _collect_docs(dep_docs_raw)
    total_deposits = 0
    total_depositors = 0
    for doc in dep_docs:
        d = doc.to_dict() or {}
        total_deposits += d.get('bank_deposit', 0)
        total_depositors += 1

    # --- Должники ---
    debt_docs_raw = await users_ref.where('debts', '!=', {}).get()
    debt_docs = await _collect_docs(debt_docs_raw)
    total_loans_given = 0
    overdue_loans = 0
    bank_debt_prefix = f"bank_{user_id}_"
    for doc in debt_docs:
        d = doc.to_dict() or {}
        debts = d.get('debts', {}) or {}
        for k, v in debts.items():
            if not (isinstance(v, (int, float)) and v > 0):
                continue
            if not k.startswith(bank_debt_prefix):
                continue
            total_loans_given += v
            parts = k.split("_")
            if len(parts) >= 3:
                try:
                    due_date = int(parts[2])
                    if current_time > due_date:
                        overdue_loans += v
                except ValueError:
                    pass

    rate = bank_data.get('deposit_rate', DEFAULT_DEPOSIT_RATE)
    capital = bank_data.get('capital', 0)

    return (
        f"📊 <b>Панель управления банком: {escape_html(bank_data.get('name', 'Банк'))}</b>\n\n"
        f"💰 <b>Ликвидность (Капитал):</b> {capital} сыр.\n"
        f"📈 <b>Ставка по вкладам:</b> {rate}%\n\n"
        f"👥 <b>Вкладчиков:</b> {total_depositors}\n"
        f"🏦 <b>Сумма на вкладах:</b> {total_deposits} сыр.\n\n"
        f"🤝 <b>Раздано кредитов:</b> {total_loans_given} сыр.\n"
        f"🚨 <b>Просроченных долгов:</b> {overdue_loans} сыр.\n"
        f"{audit_warning}"
    )


# ===================== /bank_stats =====================
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


# ===================== CALLBACK МЕНЮ БАНКА =====================
@router.callback_query(F.data.startswith("bstat_"))
async def cb_bank_stats(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    if len(data_parts) < 3:
        return await callback.answer()

    action = data_parts[1]

    # Действия с подтипом: bstat_<action>_<sub>_<banker_id>
    sub_actions = {"buyupg", "doinv", "actlobby"}
    try:
        if action in sub_actions:
            if len(data_parts) < 4:
                return await callback.answer()
            sub_type = data_parts[2]
            banker_id = int(data_parts[3])
        else:
            sub_type = None
            banker_id = int(data_parts[2])
    except ValueError:
        return await callback.answer("❌ Некорректные данные.", show_alert=True)

    if callback.from_user.id != banker_id:
        return await callback.answer("❌ Это не ваш банк!", show_alert=True)

    chat_id = callback.message.chat.id
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        return await callback.answer("❌ Банк не найден.", show_alert=True)

    db = get_db()
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')

    # ---------- MAIN ----------
    if action == "main":
        text = await generate_bank_main_stats(chat_id, banker_id, bank_data)
        try:
            await callback.message.edit_text(text, reply_markup=get_bank_stats_kb(banker_id))
        except Exception:
            pass
        return await callback.answer()

    # ---------- DEPOSITS ----------
    if action == "deps":
        user_docs_raw = await users_ref.where('bank_name', '==', banker_id).get()
        user_docs = await _collect_docs(user_docs_raw)
        depositors = []
        for doc in user_docs:
            u = doc.to_dict() or {}
            depositors.append({
                'name': u.get('full_name', 'Unknown'),
                'deposit': u.get('bank_deposit', 0),
            })
        depositors.sort(key=lambda x: x['deposit'], reverse=True)

        text = f"👥 <b>Топ вкладчиков банка {escape_html(bank_data.get('name', 'Банк'))}</b>\n\n"
        if not depositors:
            text += "<i>Вкладов пока нет.</i>"
        else:
            for i, dep in enumerate(depositors[:10], 1):
                text += f"{i}. <b>{escape_html(dep['name'])}</b>: {dep['deposit']} сыр.\n"

        try:
            await callback.message.edit_text(text, reply_markup=get_bank_stats_kb(banker_id))
        except Exception:
            pass
        return await callback.answer()

    # ---------- LOANS ----------
    if action == "loans":
        user_docs_raw = await users_ref.where('debts', '!=', {}).get()
        user_docs = await _collect_docs(user_docs_raw)
        bank_debt_prefix = f"bank_{banker_id}_"
        debtors = []
        for doc in user_docs:
            u = doc.to_dict() or {}
            debts = u.get('debts', {}) or {}
            total_debt = sum(
                v for k, v in debts.items()
                if k.startswith(bank_debt_prefix) and isinstance(v, (int, float)) and v > 0
            )
            if total_debt > 0:
                debtors.append({'name': u.get('full_name', 'Unknown'), 'debt': total_debt})
        debtors.sort(key=lambda x: x['debt'], reverse=True)

        text = f"🤝 <b>Топ должников банка {escape_html(bank_data.get('name', 'Банк'))}</b>\n\n"
        if not debtors:
            text += "<i>Должников пока нет.</i>"
        else:
            for i, deb in enumerate(debtors[:10], 1):
                text += f"{i}. <b>{escape_html(deb['name'])}</b>: {deb['debt']} сыр.\n"

        try:
            await callback.message.edit_text(text, reply_markup=get_bank_stats_kb(banker_id))
        except Exception:
            pass
        return await callback.answer()

    # ---------- SETTINGS ----------
    if action == "settings":
        rate = bank_data.get('deposit_rate', DEFAULT_DEPOSIT_RATE)
        text = (
            f"⚙️ <b>Настройки банка {escape_html(bank_data.get('name', 'Банк'))}</b>\n\n"
            f"Текущая ставка: <b>{rate}%</b>\n\n"
            f"📌 <i>Команды:</i>\n"
            f"<code>/bankrate [{int(MIN_DEPOSIT_RATE)}-{int(MAX_DEPOSIT_RATE)}]</code> - Изменить ставку по вкладам.\n"
            f"<code>/bank_offshore</code> - Скрыть свои средства в оффшоре.\n"
            f"<code>/incass</code> - Запустить рейс инкассаторов.\n"
            f"Выдавать кредиты можно реплаем: <code>кредит [сумма] [%] [срок]</code>"
        )
        try:
            await callback.message.edit_text(text, reply_markup=get_bank_stats_kb(banker_id))
        except Exception:
            pass
        return await callback.answer()

    # ---------- SCHEMES ----------
    if action == "schemes":
        await show_bank_schemes(callback, chat_id, banker_id)
        return await callback.answer()

    # ---------- INV MENU ----------
    if action == "invmenu":
        await show_investment_menu(callback, banker_id)
        return await callback.answer()

    # ---------- DO INVEST ----------
    if action == "doinv":
        cfg = INVEST_CFG.get(sub_type)
        if not cfg:
            return await callback.answer("Неизвестная инвестиция.", show_alert=True)

        capital = bank_data.get('capital', 0)
        if capital < INVEST_MIN_CAPITAL:
            return await callback.answer(
                f"❌ Нужно минимум {INVEST_MIN_CAPITAL} капитала!", show_alert=True
            )

        invest_amt = int(capital * INVEST_RATIO)
        if random.random() < cfg['chance']:
            profit = int(invest_amt * cfg['profit'])
            await create_or_update_bank(chat_id, banker_id, {'capital': capital + profit})
            await callback.answer(f"📈 {cfg['name']}: УСПЕХ!\nПрибыль: +{profit} сыр.", show_alert=True)
        else:
            loss = int(invest_amt * INVEST_LOSS_RATIO)
            await create_or_update_bank(chat_id, banker_id, {'capital': max(0, capital - loss)})
            await callback.answer(f"📉 {cfg['name']}: ПРОВАЛ!\nПотеряно: -{loss} сыр.", show_alert=True)
        return await show_bank_schemes(callback, chat_id, banker_id)

    # ---------- FORGE ----------
    if action == "forge":
        current_time = int(time.time())
        last_forge = bank_data.get('last_forge_time', 0)
        if current_time - last_forge < FORGE_COOLDOWN:
            rem = (FORGE_COOLDOWN - (current_time - last_forge)) // 60
            return await callback.answer(f"⏳ Станок перегрет! Остынет через {rem} мин.", show_alert=True)

        new_capital = bank_data.get('capital', 0) + FORGE_AMOUNT
        audit_time = current_time + FORGE_AUDIT_DURATION
        await create_or_update_bank(chat_id, banker_id, {
            'capital': new_capital,
            'last_forge_time': current_time,
            'audit_risk_until': audit_time,
        })
        await callback.answer(
            f"🖨 Тр-р-р... Напечатано {FORGE_AMOUNT} сыр.!\n"
            f"⚠️ ОСТОРОЖНО: Риск аудита ЦБ на 2 часа!", show_alert=True
        )
        return await show_bank_schemes(callback, chat_id, banker_id)

    # ---------- AUDIT (подсказка) ----------
    if action == "audit":
        return await callback.answer(
            "Чтобы провести аудит, используйте команду:\nаудит [ID/реплай]", show_alert=True
        )

    # ---------- LOBBY MENU ----------
    if action == "lobbymenu":
        await show_lobbying_menu(callback, banker_id)
        return await callback.answer()

    # ---------- ACT LOBBY ----------
    if action == "actlobby":
        cfg = LOBBY_CFG.get(sub_type)
        if not cfg:
            return await callback.answer("Неизвестная программа.", show_alert=True)

        capital = bank_data.get('capital', 0)
        if capital < cfg['price']:
            return await callback.answer(
                f"❌ Нужно {cfg['price']} капитала для {cfg['name']}!", show_alert=True
            )

        current_time = int(time.time())
        if current_time < bank_data.get('lobby_until', 0):
            return await callback.answer("⏳ Лобби уже активно!", show_alert=True)

        lobby_until = current_time + (cfg['hours'] * 3600)
        await create_or_update_bank(chat_id, banker_id, {
            'capital': capital - cfg['price'],
            'lobby_until': lobby_until,
            'lobby_type': sub_type,
        })

        msg_text = (
            f"📢 <b>ЛОББИРОВАНИЕ!</b>\n\n"
            f"Банк <b>{escape_html(bank_data.get('name', 'Банк'))}</b> "
            f"пролоббировал программу <b>{cfg['name']}</b>!\n"
            f"🚀 В ближайшие {cfg['hours']} ч. в чате действуют особые условия!"
        )
        try:
            await callback.message.edit_text(msg_text)
        except Exception:
            pass
        await callback.message.answer(msg_text)
        return await callback.answer()

    # ---------- UPGRADES ----------
    if action == "upgrades":
        await show_bank_upgrades(callback, chat_id, banker_id)
        return await callback.answer()

    # ---------- BUY UPGRADE ----------
    if action == "buyupg":
        cfg = UPGRADES_CFG.get(sub_type)
        if not cfg:
            return await callback.answer("Неизвестное улучшение.", show_alert=True)

        lvl = bank_data.get(cfg['field'], 0)
        if lvl >= MAX_UPGRADE_LEVEL:
            return await callback.answer("Максимальный уровень!", show_alert=True)

        price = cfg['price'] * (lvl + 1)
        capital = bank_data.get('capital', 0)
        if capital < price:
            return await callback.answer("❌ Недостаточно капитала банка!", show_alert=True)

        await create_or_update_bank(chat_id, banker_id, {
            'capital': capital - price,
            cfg['field']: lvl + 1,
        })
        await callback.answer(f"✅ {cfg['name']}: уровень {lvl + 1}!")
        return await show_bank_upgrades(callback, chat_id, banker_id)

    await callback.answer()


# ===================== UI: УЛУЧШЕНИЯ =====================
async def show_bank_upgrades(callback: types.CallbackQuery, chat_id: int, banker_id: int):
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        return await callback.answer("❌ Банк не найден.", show_alert=True)

    capital = bank_data.get('capital', 0)

    def fmt(key, descr):
        cfg = UPGRADES_CFG[key]
        lvl = bank_data.get(cfg['field'], 0)
        status = f"{lvl}/{MAX_UPGRADE_LEVEL}" if lvl < MAX_UPGRADE_LEVEL else "МАКС."
        price = cfg['price'] * (lvl + 1) if lvl < MAX_UPGRADE_LEVEL else None
        price_str = f"{price} сыр." if price is not None else "—"
        return lvl, status, price_str, descr

    armor_lvl, armor_status, armor_price, _ = fmt('armor', '')
    earn_lvl, earn_status, earn_price, _ = fmt('earn', '')
    banker_lvl, banker_status, banker_price, _ = fmt('banker', '')
    market_lvl, market_status, market_price, _ = fmt('market', '')
    sec_lvl, sec_status, sec_price, _ = fmt('sec', '')

    text = (
        f"⬆️ <b>Улучшения банка</b>\n"
        f"Капитал: <b>{capital}</b> сыр.\n\n"

        f"🛡 <b>Броневики (Инкассация)</b>: Ур. {armor_status}\n"
        f"<i>Снижает начальный риск нападения при /incass.</i>\n"
        f"Цена: {armor_price}\n\n"

        f"💼 <b>Вместимость мешков</b>: Ур. {earn_status}\n"
        f"<i>+10% к добыче при инкассации за уровень.</i>\n"
        f"Цена: {earn_price}\n\n"

        f"👔 <b>Доля Банкира</b>: Ур. {banker_status}\n"
        f"<i>+5% к вашей личной премии от инкассации.</i>\n"
        f"Цена: {banker_price}\n\n"

        f"📈 <b>Маркетинг (Субсидии)</b>: Ур. {market_status}\n"
        f"<i>+20% к ежедневным субсидиям ЦБ.</i>\n"
        f"Цена: {market_price}\n\n"

        f"🔐 <b>Сейфовая Охрана</b>: Ур. {sec_status}\n"
        f"<i>Снижает шанс кражи через /steal (до 5% при макс ур).</i>\n"
        f"Цена: {sec_price}"
    )

    builder = InlineKeyboardBuilder()
    if armor_lvl < MAX_UPGRADE_LEVEL:
        builder.button(text="🛡 Броневики", callback_data=f"bstat_buyupg_armor_{banker_id}")
    if earn_lvl < MAX_UPGRADE_LEVEL:
        builder.button(text="💼 Вместимость", callback_data=f"bstat_buyupg_earn_{banker_id}")
    if banker_lvl < MAX_UPGRADE_LEVEL:
        builder.button(text="👔 Доля", callback_data=f"bstat_buyupg_banker_{banker_id}")
    if market_lvl < MAX_UPGRADE_LEVEL:
        builder.button(text="📈 Маркетинг", callback_data=f"bstat_buyupg_market_{banker_id}")
    if sec_lvl < MAX_UPGRADE_LEVEL:
        builder.button(text="🔐 Охрана", callback_data=f"bstat_buyupg_sec_{banker_id}")
    builder.button(text="⬅️ Назад", callback_data=f"bstat_main_{banker_id}")
    builder.adjust(2, 2, 1, 1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except Exception:
        pass


# ===================== UI: СХЕМЫ =====================
async def show_bank_schemes(callback: types.CallbackQuery, chat_id: int, banker_id: int):
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        return await callback.answer("❌ Банк не найден.", show_alert=True)

    current_time = int(time.time())
    audit_until = bank_data.get('audit_risk_until', 0)
    audit_status = "🟢 Чист" if current_time > audit_until else "🔴 ПРОВЕРКА ЦБ (Риск штрафа!)"

    lobby_until = bank_data.get('lobby_until', 0)
    lobby_type = bank_data.get('lobby_type', 'none')
    lobby_status = "⚪️ Нет активных программ"
    if current_time < lobby_until:
        types_map = {
            'golden': "🌟 Золотой Век (+20% ко всему)",
            'tax': "📉 Налоговый Рай (-50% налог)",
            'work': "🏭 Индустриализация (+40% к работе)",
            'crime': "🥷 Амнистия (Крайм-буст)",
        }
        lobby_status = f"✅ Активно: {types_map.get(lobby_type, 'Неизвестно')}"

    capital = bank_data.get('capital', 0)

    text = (
        f"💼 <b>Теневые и политические схемы: {escape_html(bank_data.get('name', 'Банк'))}</b>\n\n"
        f"💰 Капитал: <b>{capital}</b> сыр.\n"
        f"🕵️ Статус аудита: {audit_status}\n"
        f"📢 Статус лобби: {lobby_status}\n\n"
        f"📈 <b>Управление Инвестициями</b>\n"
        f"<i>Разместите капитал в фондах разной степени риска.</i>\n\n"
        f"🖨 <b>Печатный станок</b>\n"
        f"<i>Мгновенная эмиссия {FORGE_AMOUNT} сыр. Это вызовет интерес ЦБ.</i>\n\n"
        f"🕵️ <b>Теневой аудит</b>\n"
        f"<i>Команда: <code>аудит [ID/реплай]</code> для поиска «грязных» денег.</i>\n\n"
        f"📢 <b>Политическое Лоббирование</b>\n"
        f"<i>Продвигайте законы, выгодные вашему банку или чату.</i>\n"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Инвестиции", callback_data=f"bstat_invmenu_{banker_id}")
    builder.button(text="🖨 Включить станок", callback_data=f"bstat_forge_{banker_id}")
    builder.button(text="📢 Лоббирование", callback_data=f"bstat_lobbymenu_{banker_id}")
    builder.button(text="⬅️ Назад", callback_data=f"bstat_main_{banker_id}")
    builder.adjust(2, 1, 1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except Exception:
        pass


async def show_lobbying_menu(callback: types.CallbackQuery, banker_id: int):
    text = (
        "📢 <b>Центр Политического Лоббирования</b>\n\n"
        "Выберите программу для продвижения в правительстве:\n\n"
        "1️⃣ <b>Золотой Век</b>\n"
        "<i>+20% прибыли ко всем действиям (/bonus, /work, /crime) для всего чата.</i>\n"
        f"💰 Цена: <b>{LOBBY_CFG['golden']['price']:,}</b> | ⏱ {LOBBY_CFG['golden']['hours']} ч\n\n"
        "2️⃣ <b>Налоговый Рай</b>\n"
        "<i>Снижает глобальный налог на переводы и бонусы на 50%.</i>\n"
        f"💰 Цена: <b>{LOBBY_CFG['tax']['price']:,}</b> | ⏱ {LOBBY_CFG['tax']['hours']} ч\n\n"
        "3️⃣ <b>План Индустриализации</b>\n"
        "<i>+40% прибыли только от работы (/work). Идеально для поднятия экономики.</i>\n"
        f"💰 Цена: <b>{LOBBY_CFG['work']['price']:,}</b> | ⏱ {LOBBY_CFG['work']['hours']} ч\n\n"
        "4️⃣ <b>Криминальная Амнистия</b>\n"
        "<i>+20% шанс успеха крайма и -80% штрафы при поимке.</i>\n"
        f"💰 Цена: <b>{LOBBY_CFG['crime']['price']:,}</b> | ⏱ {LOBBY_CFG['crime']['hours']} ч"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="1️⃣ Золотой Век", callback_data=f"bstat_actlobby_golden_{banker_id}")
    builder.button(text="2️⃣ Налоговый Рай", callback_data=f"bstat_actlobby_tax_{banker_id}")
    builder.button(text="3️⃣ Индустрия", callback_data=f"bstat_actlobby_work_{banker_id}")
    builder.button(text="4️⃣ Амнистия", callback_data=f"bstat_actlobby_crime_{banker_id}")
    builder.button(text="⬅️ К схемам", callback_data=f"bstat_schemes_{banker_id}")
    builder.adjust(2, 2, 1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except Exception:
        pass


async def show_investment_menu(callback: types.CallbackQuery, banker_id: int):
    text = (
        "📈 <b>Инвестиционный Портфель Банка</b>\n\n"
        f"Разместите свободный капитал ({int(INVEST_RATIO * 100)}% от текущего):\n\n"
        "🏛 <b>Гос. Облигации</b>\n"
        "<i>Минимальный риск, стабильный доход.</i>\n"
        f"💰 Профит: <b>+{int(INVEST_CFG['safe']['profit']*100)}%</b> | 🎯 Шанс: <b>{int(INVEST_CFG['safe']['chance']*100)}%</b>\n\n"
        "🚀 <b>Венчурный Фонд</b>\n"
        "<i>Инвестиции в технологические стартапы.</i>\n"
        f"💰 Профит: <b>+{int(INVEST_CFG['mid']['profit']*100)}%</b> | 🎯 Шанс: <b>{int(INVEST_CFG['mid']['chance']*100)}%</b>\n\n"
        "💎 <b>Крипто-Арбитраж</b>\n"
        "<i>Высокорисковые операции на бирже.</i>\n"
        f"💰 Профит: <b>+{int(INVEST_CFG['risk']['profit']*100)}%</b> | 🎯 Шанс: <b>{int(INVEST_CFG['risk']['chance']*100)}%</b>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🏛 Облигации", callback_data=f"bstat_doinv_safe_{banker_id}")
    builder.button(text="🚀 Венчур", callback_data=f"bstat_doinv_mid_{banker_id}")
    builder.button(text="💎 Крипто", callback_data=f"bstat_doinv_risk_{banker_id}")
    builder.button(text="⬅️ К схемам", callback_data=f"bstat_schemes_{banker_id}")
    builder.adjust(1)

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except Exception:
        pass


# ===================== ИНКАССАЦИЯ =====================
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

    if current_time - last_time < INCASS_COOLDOWN:
        rem_min = (INCASS_COOLDOWN - (current_time - last_time)) // 60
        return await message.answer(
            f"🚛 Машины на техобслуживании. Следующий рейс будет доступен через {rem_min} мин."
        )

    if bank_data.get('capital', 0) < INCASS_MIN_CAPITAL:
        return await message.answer(
            f"❌ В капитале банка должно быть минимум {INCASS_MIN_CAPITAL} сыроежек (залог на случай ремонта)."
        )

    if data.get('balance', 0) < INCASS_MIN_BALANCE:
        return await message.answer(
            f"❌ У вас на личном счету должно быть минимум {INCASS_MIN_BALANCE} сыр. "
            f"для оплаты личной страховки рейса."
        )

    await create_or_update_bank(chat_id, user_id, {'incass_last_time': current_time})

    lvl_armor = bank_data.get('upgrade_armor', 0)
    base_risk = max(INCASS_BASE_RISK - (lvl_armor * 2), INCASS_MIN_RISK)

    lvl_earnings = bank_data.get('upgrade_earnings', 0)
    earning_mult = 1.0 + (lvl_earnings * 0.1)

    start_money = int(random.randint(INCASS_REWARD_MIN, INCASS_REWARD_MAX) * earning_mult)
    next_risk_jump = random.randint(5, 25)

    incass_id = f"incass_{chat_id}_{user_id}"
    active_incass[incass_id] = {
        'money': start_money,
        'risk': base_risk,
        'step': 1,
        'earning_mult': earning_mult,
        'next_jump': next_risk_jump,
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
    if len(parts) < 3:
        return await callback.answer()

    action = parts[1]
    try:
        banker_id = int(parts[2])
    except ValueError:
        return await callback.answer()

    if callback.from_user.id != banker_id:
        return await callback.answer("Это не ваш рейс!", show_alert=True)

    chat_id = callback.message.chat.id
    incass_id = f"incass_{chat_id}_{banker_id}"

    if incass_id not in active_incass:
        try:
            await callback.message.edit_text("❌ Этот рейс уже завершён.")
        except Exception:
            pass
        return await callback.answer()

    state = active_incass[incass_id]
    bank_data = await get_bank_info(chat_id, banker_id)
    if not bank_data:
        active_incass.pop(incass_id, None)
        try:
            await callback.message.edit_text("❌ Банк больше не существует. Рейс отменён.")
        except Exception:
            pass
        return await callback.answer()

    lvl_banker = bank_data.get('upgrade_banker', 0)
    banker_cut = INCASS_BANKER_BASE_CUT + (lvl_banker * INCASS_BANKER_LVL_CUT)

    # ---------- CASHOUT ----------
    if action == "cashout":
        money = state['money']
        active_incass.pop(incass_id, None)

        banker_profit = int(money * banker_cut)
        bank_profit = money - banker_profit

        await create_or_update_bank(chat_id, banker_id, {
            'capital': bank_data.get('capital', 0) + bank_profit
        })
        await update_user_balance(chat_id, banker_id, banker_profit, action="Incass Payout")

        try:
            await callback.message.edit_text(
                f"🏦 <b>Машина благополучно вернулась!</b>\n\n"
                f"Общий куш: <b>{money}</b> сыр.\n"
                f"💼 Капитал банка пополнен на: <b>{bank_profit}</b> сыр.\n"
                f"💵 Личная премия банкира: <b>{banker_profit}</b> сыр."
            )
        except Exception:
            pass
        return await callback.answer()

    # ---------- NEXT ----------
    if action == "next":
        state['risk'] = min(state['risk'] + state['next_jump'], INCASS_MAX_RISK)
        current_risk = state['risk']

        if random.randint(1, 100) <= current_risk:
            active_incass.pop(incass_id, None)

            total_penalty = random.randint(INCASS_PENALTY_MIN, INCASS_PENALTY_MAX)
            bank_penalty = total_penalty // 2
            personal_penalty = total_penalty - bank_penalty

            new_capital = max(0, bank_data.get('capital', 0) - bank_penalty)
            await create_or_update_bank(chat_id, banker_id, {'capital': new_capital})
            await update_user_balance(chat_id, banker_id, -personal_penalty, action="Incass Loss")

            try:
                await callback.message.edit_text(
                    f"💥 <b>НАПАДЕНИЕ ОПГ! (Шанс был {current_risk}%)</b>\n\n"
                    f"Вооруженные бандиты подорвали броневик и украли все собранные "
                    f"<b>{state['money']}</b> сыр.\n\n"
                    f"💸 Банк оплатил часть ремонта: <b>-{bank_penalty}</b> сыр. из капитала.\n"
                    f"💸 Вы оплатили остаток из своего кармана: <b>-{personal_penalty}</b> сыр."
                )
            except Exception:
                pass
        else:
            state['step'] += 1
            add_money = int(random.randint(INCASS_REWARD_MIN, INCASS_REWARD_MAX) * state['earning_mult'])
            state['money'] += add_money
            next_risk_jump = random.randint(5, 25)
            state['next_jump'] = next_risk_jump

            builder = InlineKeyboardBuilder()
            builder.button(text="🛣 Ехать на следующую точку", callback_data=f"incass_next_{banker_id}")
            builder.button(text="🏦 Вернуться в банк", callback_data=f"incass_cashout_{banker_id}")
            builder.adjust(1)

            try:
                await callback.message.edit_text(
                    f"🚛 <b>Рейс продолжается...</b>\n\n"
                    f"📍 Точка {state['step']} пройдена.\n"
                    f"💰 Найдено: +{add_money}\n"
                    f"💵 Всего в кузове: <b>{state['money']}</b> сыр.\n"
                    f"🚨 Текущий риск: <b>{current_risk}%</b> (Прыжок на след. шаге: +{next_risk_jump}%)\n\n"
                    f"Рискуем дальше?",
                    reply_markup=builder.as_markup()
                )
            except Exception:
                pass
        return await callback.answer()

    await callback.answer()


# ===================== ТЕНЕВОЙ АУДИТ =====================
@router.message(F.text.lower().startswith("аудит"))
async def cmd_shadow_audit(message: types.Message):
    text_lower = message.text.lower()
    # Защита от ложных срабатываний (аудитория и т.п.)
    if not (text_lower == "аудит" or text_lower.startswith("аудит ") or text_lower.startswith("аудит\n")):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    bank_data = await get_bank_info(chat_id, user_id)
    if not bank_data:
        return await message.answer("❌ Эта команда доступна только банкирам.")

    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split()
        if len(args) < 2:
            return await message.answer("Использование: <code>аудит [ID/реплай]</code>")
        try:
            target_id = int(args[1])
        except ValueError:
            return await message.answer("Неверный ID пользователя.")

    if target_id == user_id:
        return await message.answer("Вы не можете провести аудит самого себя.")

    target_data = await get_user_data(chat_id, target_id)
    if not target_data:
        return await message.answer("Пользователь не найден.")

    target_balance = target_data.get('balance', 0)
    if target_balance < AUDIT_MIN_TARGET_BALANCE:
        return await message.answer("У цели слишком мало денег для аудита.")

    current_time = int(time.time())
    last_audit = bank_data.get('last_audit_time', 0)
    if current_time - last_audit < AUDIT_COOLDOWN:
        rem = (AUDIT_COOLDOWN - (current_time - last_audit)) // 60
        return await message.answer(f"⏳ Ваши аудиторы еще заняты прошлым делом. Попробуйте через {rem} мин.")

    await create_or_update_bank(chat_id, user_id, {'last_audit_time': current_time})

    if random.random() < AUDIT_SUCCESS_CHANCE:
        confiscate_amt = min(int(target_balance * AUDIT_CONFISCATE_RATE), AUDIT_CONFISCATE_MAX)
        if confiscate_amt <= 0:
            return await message.answer("🕵️ Аудит не дал значимых результатов.")

        await update_user_balance(chat_id, target_id, -confiscate_amt, action="Shadow Audit Confiscation")
        await create_or_update_bank(chat_id, user_id, {
            'capital': bank_data.get('capital', 0) + confiscate_amt
        })

        await message.answer(
            f"🕵️ <b>ТЕНЕВОЙ АУДИТ ЗАВЕРШЕН!</b>\n\n"
            f"Ваши люди нашли неучтенные средства у "
            f"<b>{escape_html(target_data.get('full_name', f'ID:{target_id}'))}</b>.\n"
            f"💼 В капитал банка конфисковано: <b>{confiscate_amt}</b> сыр.!"
        )
    else:
        await create_or_update_bank(chat_id, user_id, {
            'capital': max(0, bank_data.get('capital', 0) - AUDIT_FAIL_PENALTY)
        })
        await message.answer(
            f"🕵️ <b>АУДИТ ПРОВАЛЕН!</b>\n\n"
            f"Игрок <b>{escape_html(target_data.get('full_name', f'ID:{target_id}'))}</b> "
            f"оказался чист, а ваши действия сочли давлением.\n"
            f"💸 Банк выплатил компенсацию и штрафы: <b>{AUDIT_FAIL_PENALTY}</b> сыр."
        )


# ===================== ЛОББИ-БЛЭКЛИСТ =====================
@router.message(F.text.lower().startswith("лобби бан") | F.text.lower().startswith("лобби разбан"))
async def cmd_lobby_blacklist_mgmt(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    bank_data = await get_bank_info(chat_id, user_id)
    if not bank_data:
        return await message.answer("❌ Эта команда доступна только банкирам.")

    text_lower = message.text.lower()
    # Определяем по началу строки (исправлено: иначе "разбан" мог парситься как "бан")
    if text_lower.startswith("лобби разбан"):
        action = "unban"
    elif text_lower.startswith("лобби бан"):
        action = "ban"
    else:
        return

    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split()
        if len(args) < 3:
            return await message.answer(f"Использование: <code>лобби {action} [ID/реплай]</code>")
        try:
            target_id = int(args[2])
        except ValueError:
            return await message.answer("Неверный ID пользователя.")

    blacklist = list(bank_data.get('lobby_blacklist', []) or [])

    if action == "ban":
        if target_id not in blacklist:
            blacklist.append(target_id)
            await create_or_update_bank(chat_id, user_id, {'lobby_blacklist': blacklist})
            await message.answer(
                f"🚫 Пользователь <b>{target_id}</b> добавлен в черный список лоббирования. "
                f"Он не будет получать бонус +20%."
            )
        else:
            await message.answer("Пользователь уже в списке.")
    else:
        if target_id in blacklist:
            blacklist.remove(target_id)
            await create_or_update_bank(chat_id, user_id, {'lobby_blacklist': blacklist})
            await message.answer(f"✅ Пользователь <b>{target_id}</b> удален из черного списка лоббирования.")
        else:
            await message.answer("Пользователь не найден в черном списке.")