from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from firebase_admin import firestore_async
from datetime import timedelta
import secrets
import time
import uuid
import logging

from economy_utils import get_global_tax, calculate_progressive_tax, format_time_left
from user_manager import (
    get_user_data, update_user_balance, check_and_give_bonus,
    update_user_field, get_user_ref, safe_get_snapshot,
)
from seasons import apply_season_logic, get_season_config, get_glitch_text
from diseases import get_active_diseases
from escape import escape_html

logger = logging.getLogger(__name__)
router = Router()

# ============================================================
#  ХРАНИЛИЩА АКТИВНЫХ МИНИ-ИГР
# ============================================================
active_work_games: dict = {}
active_crime_games: dict = {}

# Кулдауны
WORK_COOLDOWN = 1800        # 30 мин
CRIME_COOLDOWN = 3600       # 1 ч
BONUS_COOLDOWN = 14400      # 4 ч
ROB_BANK_COOLDOWN = 43200   # 12 ч
GAME_TTL = 60               # сек на мини-игру


def _cleanup_expired_games() -> None:
    """Удаляет просроченные мини-игры из памяти."""
    now = time.time()
    for store in (active_work_games, active_crime_games):
        expired = []
        for k, v in list(store.items()):
            if not isinstance(v, dict):
                expired.append(k)
                continue
            exp = v.get('expires')
            if exp is None or now > exp:
                expired.append(k)
        for k in expired:
            store.pop(k, None)


# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
async def _calc_transfer_tax(chat_id: int, user_id: int, sender_data: dict) -> int:
    """Считает итоговый процент налога для перевода с учётом болезней."""
    base_tax = await get_global_tax()
    active_diseases = await get_active_diseases(chat_id, user_id)

    neg_lvl = sender_data.get('skills', {}).get('negotiation', 0)
    pet_data = sender_data.get('pet') or {}
    pet_id = pet_data.get('id') if isinstance(pet_data, dict) else None

    tax_percent = calculate_progressive_tax(
        sender_data.get('balance', 0), base_tax, neg_lvl, pet_id
    )
    if 'herpes' in active_diseases:
        # Герпес — минимум 30%
        tax_percent = max(tax_percent, 30)
    return max(0, int(tax_percent))


def _calc_commission(amount: int, tax_percent: int) -> int:
    """Считает комиссию. Если налог > 0, минимум 1 сыроежка."""
    if tax_percent <= 0 or amount <= 0:
        return 0
    commission = int(amount * tax_percent / 100.0)
    return commission if commission > 0 else 1


def _max_amount_for_balance(balance: int, tax_percent: int) -> int:
    """Максимальная сумма перевода, чтобы amount + commission <= balance."""
    if balance <= 0:
        return 0
    if tax_percent <= 0:
        return balance
    # Учитываем, что комиссия минимум 1 при ненулевом налоге
    amount = int(balance / (1 + tax_percent / 100.0))
    while amount > 0 and amount + _calc_commission(amount, tax_percent) > balance:
        amount -= 1
    return max(amount, 0)


# ============================================================
#  /start /help /balance
# ============================================================
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    await get_user_data(chat_id, user_id, full_name)
    await message.answer(
        f"👋 <b>Привет, {full_name}!</b>\n\n"
        "Я бот для экономики и мини-игр! Твой стартовый баланс — <b>500</b> сыроежек.\n\n"
        "Пиши <code>/help</code> чтобы увидеть список всех команд."
    )


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📜 <b>ПОЛНЫЙ СПИСОК КОМАНД БОТА</b> 📜\n\n"
        "🚀 <b>ПОСЛЕДНИЕ ОБНОВЛЕНИЯ:</b>\n"
        "• 📈 <b>КРАШ-АВИАТОР:</b> <code>/crash</code>\n"
        "• 🃏 <b>ВИДЕО-ПОКЕР:</b> <code>/poker</code>\n"
        "• 📈 <b>Фондовая Биржа:</b> <code>/stocks</code> — Инвестируй в ГазСыр и SpaceMilk!\n"
        "• 📅 <b>Сезоны:</b> <code>/season</code> — Тематические события с бонусами!\n\n"

        "💰 <b>ЭКОНОМИКА И БАНК:</b>\n"
        "<code>/profile</code> — Профиль.\n"
        "<code>/bank</code> — Меню банков.\n"
        "<code>/bank_offshore</code> — Скрыть счёт.\n"
        "<code>ограбить банк [Имя]</code> — Кража из банка.\n"
        "<code>/bonus</code> — Доход с бизнесов.\n"
        "<code>/work</code>, <code>/crime</code> — Работа и криминал.\n"
        "<code>/pay [сумма|all]</code> — Перевод (реплай).\n"
        "<code>долг [сумма] [%]</code> — Дать в долг.\n"
        "<code>выплатить [сумма]</code> — Вернуть долг.\n"
        "<code>украсть</code> — Кража у игрока.\n\n"

        "📈 <b>БИРЖА:</b>\n"
        "<code>/stocks</code>, <code>/криптосыроежка</code>, "
        "<code>/createcoin</code>, <code>/cr_send</code>.\n\n"

        "🏦 <b>БАНКИРАМ:</b>\n"
        "<code>создать банк [Имя]</code>, <code>/bankrate</code>, "
        "<code>/bank_stats</code>, <code>кредит ...</code>.\n\n"

        "🛒 <b>МАГАЗИН:</b> <code>/shop</code>, <code>/inv</code>, "
        "<code>/skills</code>, <code>/pets</code>, <code>/feed</code>.\n\n"

        "🛡 <b>КЛАНЫ:</b> <code>/clan</code>, "
        "<code>Брак</code>, <code>Развод</code>, <code>Подарок</code>.\n\n"

        "🎰 <b>ИГРЫ:</b> <code>/poker</code>, <code>/crash</code>, <code>/bj</code>, <code>/slots</code>, "
        "<code>/roulette</code>, <code>Вызвать на дуэль</code>, <code>/lottery</code>.\n\n"

        "👮 <b>АДМИНКА:</b> <code>мут</code>, <code>бан</code>, "
        "<code>варн</code>, <code>повысить</code>, <code>+правила</code>.\n\n"

        "🎭 <b>РП:</b> <code>Обнять</code>, <code>Поцеловать</code>, "
        "<code>Ударить</code>, <code>/bio</code>, репутация — <code>+</code>."
    )
    await message.answer(text)


@router.message(Command("balance"))
async def cmd_balance(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    balance = data.get('balance', 0)
    is_vip = data.get('is_vip', False)
    vip_icon = " 👑 VIP" if is_vip else ""
    await message.answer(f"💰 Твой баланс: <b>{balance}</b> сыроежек.{vip_icon}")


# ============================================================
#  /pay — ПЕРЕВОД С НАЛОГОМ
# ============================================================
@router.message(Command("pay"))
async def cmd_pay(message: types.Message):
    chat_id = message.chat.id
    sender_id = message.from_user.id
    sender_name = escape_html(message.from_user.full_name)

    # --- Базовые проверки ---
    sender_data = await get_user_data(chat_id, sender_id, sender_name)
    if sender_data.get('is_banned', False):
        return await message.answer("Ты в бане и не можешь переводить деньги.")

    if not message.reply_to_message:
        return await message.answer(
            "Ответь на сообщение человека, которому хочешь перевести сыроежки.\n"
            "Использование: <code>/pay 100</code> или <code>/pay all</code>"
        )

    target_user = message.reply_to_message.from_user
    if target_user is None:
        return await message.answer("Не удалось определить получателя.")
    target_name = escape_html(target_user.full_name)

    if target_user.is_bot:
        return await message.answer("🤖 Ботам деньги не нужны.")
    if target_user.id == sender_id:
        return await message.answer("🚫 Нельзя перевести деньги самому себе.")

    # --- Парсинг аргументов ---
    args = (message.text or "").split()
    if len(args) < 2:
        return await message.answer(
            "Укажи сумму: <code>/pay 100</code> или <code>/pay all</code>"
        )

    balance = int(sender_data.get('balance', 0))
    if balance <= 0:
        return await message.answer("💸 У тебя нет денег для перевода.")

    # Считаем налог ОДИН раз
    tax_percent = await _calc_transfer_tax(chat_id, sender_id, sender_data)

    amount_str = args[1].lower().strip()
    if amount_str in {"all", "всё", "все", "max"}:
        amount = _max_amount_for_balance(balance, tax_percent)
        if amount <= 0:
            return await message.answer(
                "После уплаты налога отправлять нечего."
            )
    else:
        try:
            amount = int(amount_str)
        except ValueError:
            return await message.answer("Сумма должна быть числом или <code>all</code>.")
        if amount <= 0:
            return await message.answer("Сумма должна быть больше нуля.")
        if amount > 10_000_000_000:
            return await message.answer("Слишком большая сумма.")

    commission = _calc_commission(amount, tax_percent)
    total_cost = amount + commission

    if balance < total_cost:
        return await message.answer(
            f"💸 Недостаточно средств.\n"
            f"Требуется: <b>{total_cost}</b> (перевод {amount} + налог {commission}).\n"
            f"На балансе: <b>{balance}</b>.\n"
            f"Налог: <b>{tax_percent}%</b>."
        )

    # --- Гарантируем существование получателя ---
    await get_user_data(chat_id, target_user.id, target_name, target_user.username)

    # --- Получаем список админов для распределения комиссии ---
    try:
        admins = await message.chat.get_administrators()
        human_admins = [a.user.id for a in admins if not a.user.is_bot]
    except Exception as e:
        logger.warning(f"Не удалось получить администраторов чата {chat_id}: {e}")
        human_admins = []

    # --- Выполняем перевод транзакционно ---
    from db import get_db
    db = get_db()

    try:
        if hasattr(db, "transaction"):
            from user_manager import get_user_lock, invalidate_user_cache
            ids = sorted([sender_id, target_user.id])
            lock1 = get_user_lock(chat_id, ids[0])
            lock2 = get_user_lock(chat_id, ids[1])
            async with lock1:
                async with lock2:
                    await process_transfer_tx(
                        db.transaction(),
                        chat_id, sender_id, target_user.id,
                        total_cost, amount, human_admins, commission,
                    )
                    # Инвалидация кэша после успешного перевода
                    invalidate_user_cache(chat_id, sender_id)
                    invalidate_user_cache(chat_id, target_user.id)

            if commission > 0:
                bank_id = sender_data.get('bank_name')
                if bank_id:
                    from profile_bank import invalidate_bank_cache
                    invalidate_bank_cache(chat_id, bank_id)
                elif human_admins:
                    for aid in human_admins:
                        invalidate_user_cache(chat_id, aid)
        else:
            # Fallback (локальный мок)
            await update_user_balance(chat_id, sender_id, -total_cost, min_balance=0)
            await update_user_balance(chat_id, target_user.id, amount)
            if commission > 0 and human_admins:
                per = commission // len(human_admins)
                if per > 0:
                    for aid in human_admins:
                        await update_user_balance(chat_id, aid, per)
    except ValueError as ve:
        logger.warning(f"Контролируемая ошибка перевода {sender_id}->{target_user.id}: {ve}")
        return await message.answer(f"❌ Перевод не выполнен: {ve}.")
    except Exception as e:
        logger.exception(f"Ошибка перевода {sender_id}->{target_user.id}: {e}")
        return await message.answer(f"❌ Ошибка перевода. Попробуй позже.")

    # --- Логирование перевода ---
    try:
        sender_data_after = await get_user_data(chat_id, sender_id)
        recipient_data_after = await get_user_data(chat_id, target_user.id)
        sender_bal_after = sender_data_after.get('balance')
        recipient_bal_after = recipient_data_after.get('balance')
        try:
            message_link = message.link or ""
        except Exception:
            message_link = ""
        
        from log_system import log_financial_transaction
        log_financial_transaction(
            action_type="pay",
            sender_id=sender_id,
            sender_name=sender_name,
            sender_username=message.from_user.username or "",
            recipient_id=target_user.id,
            recipient_name=target_name,
            recipient_username=target_user.username or "",
            amount=amount,
            commission=commission,
            chat_id=chat_id,
            chat_title=message.chat.title or "Unknown",
            message_link=message_link,
            sender_balance=sender_bal_after,
            recipient_balance=recipient_bal_after
        )
    except Exception as e:
        logger.error(f"Ошибка логирования перевода: {e}")

    # --- Сообщение об успехе ---
    if commission > 0:
        phrase = secrets.choice([
            f"Налоговая откусила кусок в {commission} сыроежек.",
            f"Гоблины-сборщики забрали {commission} сыроежек в казну.",
            f"Крыша требует свою долю. Удержано {commission} сыроежек.",
            f"Банкирский дом взял {commission} сыроежек за услуги.",
            f"Местные рэкетиры взыскали налог: {commission} сыроежек.",
            f"Комиссия в {commission} сыроежек ушла на развитие экономики.",
        ])
        tax_note = f"<i>{phrase}</i> (Налог {tax_percent}%)."
    else:
        tax_note = "Налог отменён — перевод дошёл без потерь."

    await message.answer(
        f"💸 <b>Успешный перевод!</b>\n\n"
        f"Отправлено: <b>{amount}</b> сыроежек пользователю {target_name}.\n"
        f"{tax_note}"
    )


@firestore_async.async_transactional
async def process_transfer_tx(transaction, chat_id, sender_id, target_id,
                              total_cost, amount, human_admins, commission):
    """Атомарный перевод с защитой от отрицательного баланса и соблюдением порядка чтения/записи Firestore."""
    from db import get_db
    db = get_db()

    # --- 1. ЧТЕНИЯ (READS) ---
    # Читаем отправителя
    sender_ref = get_user_ref(chat_id, sender_id)
    sender_snap = await safe_get_snapshot(transaction, sender_ref)
    
    # Читаем получателя
    target_ref = get_user_ref(chat_id, target_id)
    target_snap = await safe_get_snapshot(transaction, target_ref)

    # Читаем банк (если есть)
    sender_data = sender_snap.to_dict() if sender_snap and sender_snap.exists else {}
    bank_id = sender_data.get('bank_name')
    bank_ref = None
    bank_snap = None
    if bank_id:
        bank_ref = (db.collection('chats').document(str(chat_id))
                      .collection('banks').document(str(bank_id)))
        bank_snap = await safe_get_snapshot(transaction, bank_ref)

    # Читаем админов (если будет комиссия)
    admin_refs = {}
    admin_snaps = {}
    use_admin_commission = False
    
    # Проверяем, существует ли банк
    bank_exists = bank_snap and bank_snap.exists
    
    if commission > 0 and not bank_exists and human_admins:
        use_admin_commission = True
        for aid in human_admins:
            ref = get_user_ref(chat_id, aid)
            admin_refs[aid] = ref
            admin_snaps[aid] = await safe_get_snapshot(transaction, ref)

    # --- 2. ПРОВЕРКИ И ВЫЧИСЛЕНИЯ ---
    if not sender_snap or not sender_snap.exists:
        raise ValueError("Отправитель не найден")
    
    sender_bal = int(sender_data.get('balance', 0) or 0)
    if sender_bal < total_cost:
        raise ValueError("Недостаточно средств для перевода")

    if not target_snap or not target_snap.exists:
        raise ValueError("Получатель не найден")

    # Инициализируем словарь обновлений балансов из прочитанных данных для избежания перезаписи
    updates = {}
    updates[sender_id] = sender_bal
    
    target_data = target_snap.to_dict() or {}
    updates[target_id] = int(target_data.get('balance', 0) or 0)
    
    if use_admin_commission:
        for aid in human_admins:
            a_snap = admin_snaps.get(aid)
            if a_snap and a_snap.exists:
                updates[aid] = int(a_snap.to_dict().get('balance', 0) or 0)

    # --- 3. ЗАПИСИ (WRITES) ---
    # Снимаем баланс у отправителя
    updates[sender_id] -= total_cost

    # Добавляем баланс получателю
    updates[target_id] += amount

    # Начисляем комиссию
    if commission > 0:
        if bank_exists and bank_ref:
            new_cap = int(bank_snap.to_dict().get('capital', 0) or 0) + commission
            transaction.update(bank_ref, {'capital': new_cap})
        elif use_admin_commission:
            per = commission // len(human_admins)
            if per > 0:
                for aid in human_admins:
                    if aid in updates:
                        updates[aid] += per

    # Выполняем все обновления балансов в транзакции
    for uid, new_bal in updates.items():
        ref = get_user_ref(chat_id, uid)
        transaction.update(ref, {'balance': new_bal})


# ============================================================
#  /bonus
# ============================================================
@router.message(Command("bonus"))
async def cmd_bonus(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False):
        return

    if 'gonorrhea' in await get_active_diseases(chat_id, user_id):
        return await message.answer("🦠 Из-за болезни тебе отказано в бонусе.")

    last_bonus = data.get('last_bonus_time', 0)
    current_time = time.time()
    from config import CREATOR_ID
    if user_id != CREATOR_ID and current_time - last_bonus < BONUS_COOLDOWN:
        time_left = format_time_left(BONUS_COOLDOWN - (current_time - last_bonus))
        return await message.answer(f"⏳ Бонус пока недоступен.\nОсталось {time_left}")

    secret = secrets.token_hex(8)
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Забрать бонус",
                   callback_data=f"claim_bonus_{user_id}_{secret}")
    await message.answer(
        "Нажмите кнопку ниже, чтобы забрать свой доход и бонус:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("claim_bonus_"))
async def process_claim_bonus(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4:
        return await callback.answer()

    try:
        target_user_id = int(parts[2])
    except ValueError:
        return await callback.answer()

    if callback.from_user.id != target_user_id:
        return await callback.answer("Это не ваш бонус!", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)

    success, receipt = await check_and_give_bonus(chat_id, user_id, full_name)
    if success:
        text = "🧾 <b>Квитанция о доходах</b>\n\n"
        if receipt.get('base', 0) > 0:
            text += f"🎁 Ежедневный бонус: <b>{receipt['base']}</b>\n"
        text += (
            f"🏢 Доход с бизнесов: <b>{receipt['business']}</b>\n"
            f"🚗 Доход с машин: <b>{receipt['car']}</b>\n"
        )
        if receipt.get('meme_bonus', 0) > 0:
            text += f"🃏 Бонус от карточек: <b>+{receipt['meme_bonus']}</b>\n"
        text += (
            f"➖ Налог ({receipt['tax_percent']}%): <b>-{receipt['tax_amount']}</b>\n"
            f"-----------------------\n"
            f"💰 Итого на руки: <b>{receipt['total']}</b> сыроежек"
        )
        try:
            await callback.message.edit_text(text)
        except Exception:
            await callback.message.answer(text)
    else:
        try:
            await callback.message.edit_text("❌ Ты уже собирал доход недавно.")
        except Exception:
            pass
    await callback.answer()


# ============================================================
#  ОБЩАЯ ЛОГИКА КОЛЛЕКТОРОВ (для /work и /crime)
# ============================================================
async def _process_collectors(chat_id: int, user_id: int, data: dict,
                              base_earnings: int, pet_id: str,
                              trigger_chance: int):
    """
    Обрабатывает коллекторов: списывает с дохода в счёт долга
    или штрафует, если долгов нет, но баланс отрицательный.

    Возвращает: (final_earnings, collector_msg, dragon_blocked)
    """
    rand = secrets.SystemRandom()
    debts = data.get('debts', {}) or {}
    balance = data.get('balance', 0)

    has_target = bool(debts) or balance < 0
    if not has_target:
        return base_earnings, "", False

    # Дракон отпугивает
    if pet_id == 'dragon':
        return base_earnings, "", True

    if rand.randint(1, 100) > trigger_chance:
        return base_earnings, "", False

    if debts:
        lender_id_str = secrets.choice(list(debts.keys()))
        debt_amount = int(debts[lender_id_str])
        is_bank = lender_id_str.startswith("bank_")

        collector_cut = max(int(base_earnings * 0.5), 1)
        pay_amount = min(collector_cut, debt_amount)

        if pay_amount <= 0:
            return base_earnings, "", False

        final_earnings = max(0, base_earnings - pay_amount)
        debts[lender_id_str] -= pay_amount
        if debts[lender_id_str] <= 0:
            debts.pop(lender_id_str, None)
        await update_user_field(chat_id, user_id, 'debts', debts)

        if is_bank:
            try:
                banker_id = int(lender_id_str.split("_")[1])
            except (IndexError, ValueError):
                return final_earnings, "", False
            from profile_bank import get_bank_info, create_or_update_bank
            bank_data = await get_bank_info(chat_id, banker_id)
            if bank_data:
                lender_name = bank_data.get('name', 'Неизвестный Банк')
                await create_or_update_bank(
                    chat_id, banker_id,
                    {'capital': bank_data.get('capital', 0) + pay_amount}
                )
            else:
                lender_name = 'Банк'
            msg = (f"\n\n🦹‍♂️ <b>КОЛЛЕКТОРЫ БАНКА!</b> Забрали "
                   f"<b>{pay_amount}</b> сыр. в счёт долга "
                   f"для <b>{escape_html(lender_name)}</b>.")
        else:
            try:
                lender_id = int(lender_id_str)
            except ValueError:
                return final_earnings, "", False
            lender_data = await get_user_data(chat_id, lender_id)
            lender_name = lender_data.get('full_name', 'Кредитор')
            await update_user_balance(chat_id, lender_id, pay_amount,
                                       is_debt_repayment=True)
            msg = (f"\n\n🦹‍♂️ <b>ЧАСТНЫЕ КОЛЛЕКТОРЫ!</b> Забрали "
                   f"<b>{pay_amount}</b> сыр. в счёт долга "
                   f"для <b>{escape_html(lender_name)}</b>.")
        return final_earnings, msg, False

    # Долгов нет, но баланс < 0 — штраф
    penalty = rand.randint(100, 300)
    await update_user_balance(chat_id, user_id, -penalty,
                               min_balance=0, is_debt_repayment=True)
    msg = (f"\n\n🦹‍♂️ <b>КОЛЛЕКТОРЫ БАНКА!</b> Отобрали весь заработок "
           f"и выбили ещё <b>{penalty}</b> сыр. сверху.")
    return 0, msg, False


async def _get_active_lobby(chat_id: int, user_id: int):
    """Возвращает тип активного лобби для игрока или 'none'."""
    try:
        from db import get_db
        banks_ref = (get_db().collection('chats').document(str(chat_id))
                              .collection('banks'))
        active = await banks_ref.where('lobby_until', '>', time.time()).get()
        for doc in active:
            b = doc.to_dict() or {}
            if user_id in (b.get('lobby_blacklist') or []):
                continue
            return b.get('lobby_type', 'golden')
    except Exception as e:
        logger.warning(f"Ошибка получения лобби: {e}")
    return 'none'


# ============================================================
#  /work
# ============================================================
@router.message(Command("work"))
async def cmd_work(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False):
        return await message.answer("Ты в бане и не можешь работать.")

    active_diseases = await get_active_diseases(chat_id, user_id)
    if 'hiv' in active_diseases:
        return await message.answer(
            "🦠 <b>ВИЧ</b>: У тебя нет сил работать. Зарплата обнулена."
        )

    last_work = data.get('last_work_time', 0)
    current_time = time.time()
    if current_time - last_work < WORK_COOLDOWN:
        remain = int(WORK_COOLDOWN - (current_time - last_work))
        mins, secs = divmod(remain, 60)
        return await message.answer(
            f"⏳ Ты устал. Отдохни ещё {mins} мин. {secs} сек."
        )


    rand = secrets.SystemRandom()
    is_banker = data.get('is_banker', False)
    base_earnings = (rand.randint(50, 350) if is_banker
                     else rand.randint(100, 700))

    # --- Бонус банкира ---
    bank_profit_msg = ""
    if is_banker:
        contribution = rand.randint(1000, 5000)
        try:
            from profile_bank import get_bank_info, create_or_update_bank
            bank_data = await get_bank_info(chat_id, user_id)
            if bank_data:
                await create_or_update_bank(
                    chat_id, user_id,
                    {'capital': bank_data.get('capital', 0) + contribution}
                )
                bank_profit_msg = (f"\n🏢 Ваша работа принесла банку "
                                   f"<b>{contribution}</b> сыр.!")
        except Exception as e:
            logger.warning(f"Bank profit error: {e}")

    # --- Питомец ---
    pet = data.get('pet') or {}
    pet_id = pet.get('id') if isinstance(pet, dict) else None
    pet_msg = ""

    if 'hpv' in active_diseases:
        pet_id = None
        pet_msg = "\n🦠 <b>ВПЧ</b>: Питомец не подходит к тебе."

    if pet_id == 'cat':
        base_earnings = int(base_earnings * 1.2)
        pet_msg = "\n🐱 Кот помог заработать на 20% больше!"

    # --- Коллекторы (срабатывают на base_earnings) ---
    final_earnings, collector_msg, dragon_blocked = await _process_collectors(
        chat_id, user_id, data, base_earnings, pet_id, trigger_chance=30
    )
    if dragon_blocked and (data.get('debts') or data.get('balance', 0) < 0):
        pet_msg += "\n🐉 Дракон отпугнул коллекторов!"

    # --- Лобби (применяется К ИТОГОВОЙ сумме, а не к base!) ---
    lobby_type = await _get_active_lobby(chat_id, user_id)
    lobby_msg = ""
    if lobby_type == 'golden':
        final_earnings = int(final_earnings * 1.2)
        lobby_msg = "\n🌟 Золотой век: +20% к зарплате!"
    elif lobby_type == 'work':
        final_earnings = int(final_earnings * 1.4)
        lobby_msg = "\n🏭 Индустриализация: +40% к зарплате!"

    # --- Сезоны ---
    final_earnings, season_msg = await apply_season_logic(
        chat_id, user_id, final_earnings
    )
    if final_earnings > 0:
        await update_user_balance(chat_id, user_id, final_earnings,
                                   is_debt_repayment=True)
    await update_user_field(chat_id, user_id, 'last_work_time', current_time)

    # --- Название работы ---
    cfg = await get_season_config()
    job_list = (cfg.get('strings', {}) or {}).get('job_list') if cfg.get('active') else None
    if job_list:
        job = rand.choice(job_list)
    else:
        jobs = ([
            "поработал с документами", "провёл встречу с инвесторами",
            "свёл дебет с кредитом", "продал акции банка"
        ] if is_banker else [
            "разгрузил вагоны", "написал код за еду", "доставил пиццу",
            "отработал смену на заводе", "собрал металлолом"
        ])
        job = rand.choice(jobs)

    afk_text = (
        f"💼 Ты <b>{job}</b> и заработал <b>{final_earnings}</b> сыроежек!"
        f"{pet_msg}{lobby_msg}{collector_msg}{bank_profit_msg}{season_msg}"
    )
    afk_text = await get_glitch_text(afk_text)

    # --- Мини-игра ---
    builder = InlineKeyboardBuilder()
    game_id = uuid.uuid4().hex[:8]
    lobby_boost = 1.4 if lobby_type == 'work' else (1.2 if lobby_type == 'golden' else 1.0)
    bonus = (rand.randint(500, 1250) if is_banker
             else rand.randint(1000, 2500))
    bonus = int(bonus * lobby_boost)

    if is_banker:
        a = rand.randint(100, 500)
        b = rand.randint(100, 500)
        correct = a + b
        options = [correct,
                   correct + rand.randint(10, 50),
                   correct - rand.randint(10, 50)]
        rand.shuffle(options)
        game_text = f"\n\n🎮 <b>ПРЕМИЯ:</b> Сведите баланс! <b>{a} + {b} = ?</b>"
        for opt in options:
            flag = "1" if opt == correct else "0"
            builder.button(text=str(opt),
                           callback_data=f"work_btn_{game_id}_{flag}")
    else:
        fruits = ["🍏", "🍎", "🍐", "🍊", "🍋", "🍌", "🍉", "🍇", "🍓", "🫐"]
        target = rand.choice(fruits)
        options = rand.sample(fruits, 3)
        if target not in options:
            options[0] = target
        rand.shuffle(options)
        game_text = (f"\n\n🎮 <b>ПРЕМИЯ:</b> Собери нужный товар! "
                     f"Нажми на <b>{target}</b>")
        for opt in options:
            flag = "1" if opt == target else "0"
            builder.button(text=opt,
                           callback_data=f"work_btn_{game_id}_{flag}")

    builder.adjust(3)

    _cleanup_expired_games()
    active_work_games[game_id] = {
        'user_id': user_id,
        'bonus': bonus,
        'expires': time.time() + GAME_TTL,
    }
    await message.answer(afk_text + game_text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("work_btn_"))
async def process_work_btn(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4:
        return await callback.answer()

    game_id = parts[2]
    is_correct = parts[3] == "1"

    game = active_work_games.get(game_id)
    if not game:
        return await callback.answer(
            "⏳ Время вышло или игра уже завершена!", show_alert=True
        )
    if game['user_id'] != callback.from_user.id:
        return await callback.answer("Это не твоя работа!", show_alert=True)
    if time.time() > game['expires']:
        active_work_games.pop(game_id, None)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return await callback.answer("⏳ Время вышло!", show_alert=True)

    # Атомарно удаляем, чтобы кнопку нельзя было нажать дважды
    if active_work_games.pop(game_id, None) is None:
        return await callback.answer()

    original = (callback.message.html_text
                if hasattr(callback.message, 'html_text')
                else callback.message.text) or ""

    chat_id = callback.message.chat.id
    if is_correct:
        await update_user_balance(chat_id, callback.from_user.id, game['bonus'])
        new_text = (original +
                    f"\n\n✅ <b>Успех!</b> Премия <b>{game['bonus']}</b> сыр.!")
    else:
        new_text = original + "\n\n❌ <b>Ошибка!</b> Премия сгорела."

    try:
        await callback.message.edit_text(new_text, reply_markup=None)
    except Exception:
        await callback.message.answer(new_text)
    await callback.answer()


# ============================================================
#  /crime
# ============================================================
@router.message(Command("crime"))
async def cmd_crime(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False):
        return await message.answer("Ты в бане и не можешь совершать преступления.")
    if data.get('is_banker', False):
        return await message.answer(
            "🏦 Вы — уважаемый Банкир. Воровать не по статусу."
        )

    active_diseases = await get_active_diseases(chat_id, user_id)

    last_crime = data.get('last_crime_time', 0)
    current_time = time.time()
    if current_time - last_crime < CRIME_COOLDOWN:
        remain = int(CRIME_COOLDOWN - (current_time - last_crime))
        mins, secs = divmod(remain, 60)
        return await message.answer(
            f"⏳ Копы ищут тебя. Заляг на дно ещё {mins} мин. {secs} сек."
        )


    rand = secrets.SystemRandom()
    stealth_level = data.get('skills', {}).get('stealth', 0)

    # --- ИНИЦИАЛИЗАЦИЯ success_chance (БЫЛО БАГОМ!) ---
    success_chance = 0.5 + min(stealth_level, 20) * 0.02  # макс +40%

    # --- Питомец ---
    pet = data.get('pet') or {}
    pet_id = pet.get('id') if isinstance(pet, dict) else None
    pet_msg = ""

    if 'hpv' in active_diseases:
        pet_id = None
        pet_msg = "\n🦠 <b>ВПЧ</b>: Питомец отказался помогать."

    if pet_id == 'dragon':
        success_chance += 0.10
        pet_msg = "\n🐉 Дракон помогает провернуть дело!"

    # --- Лобби ---
    lobby_type = await _get_active_lobby(chat_id, user_id)
    if lobby_type == 'crime':
        success_chance += 0.20

    if 'syphilis' in active_diseases:
        success_chance /= 2.0
        pet_msg += "\n🦠 <b>Сифилис</b>: шанс успеха урезан вдвое."

    success_chance = max(0.05, min(success_chance, 0.95))

    if rand.random() >= success_chance:
        # ПРОВАЛ
        fine = rand.randint(500, 1500)
        if lobby_type == 'crime':
            fine = max(1, int(fine * 0.2))
            msg = (f"🚔 Тебя почти поймали, но благодаря <b>Амнистии</b> "
                   f"ты отделался штрафом: <b>{fine}</b> сыр.")
        else:
            msg = f"🚔 Тебя поймали! Суд выписал штраф в <b>{fine}</b> сыр."
        await update_user_balance(chat_id, user_id, -fine,
                                   min_balance=0, is_debt_repayment=True)
        await update_user_field(chat_id, user_id, 'last_crime_time', current_time)
        return await message.answer(msg)

    # УСПЕХ
    base_earnings = rand.randint(200, 500)

    # Коллекторы
    final_earnings, collector_msg, dragon_blocked = await _process_collectors(
        chat_id, user_id, data, base_earnings, pet_id, trigger_chance=40
    )
    if dragon_blocked and (data.get('debts') or data.get('balance', 0) < 0):
        pet_msg += " И отпугнул коллекторов!"

    # Лобби-буст применяется к ИТОГУ
    lobby_msg = ""
    if lobby_type == 'golden':
        final_earnings = int(final_earnings * 1.2)
        lobby_msg = "\n🌟 Золотой век: +20% к кушу!"
    elif lobby_type == 'crime':
        final_earnings = int(final_earnings * 1.2)
        lobby_msg = "\n🥷 Амнистия: куш увеличен!"

    # Сезоны
    final_earnings, season_msg = await apply_season_logic(
        chat_id, user_id, final_earnings
    )
    if final_earnings > 0:
        await update_user_balance(chat_id, user_id, final_earnings,
                                   is_debt_repayment=True)
    await update_user_field(chat_id, user_id, 'last_crime_time', current_time)

    afk_text = (
        f"🥷 <b>Успешное проникновение!</b> Ты нашёл "
        f"<b>{final_earnings}</b> сыр.{pet_msg}{lobby_msg}"
        f"{collector_msg}{season_msg}"
    )
    afk_text = await get_glitch_text(afk_text)

    # Мини-игра «вскрытие сейфа»
    builder = InlineKeyboardBuilder()
    game_id = uuid.uuid4().hex[:8]
    lobby_boost = 1.2 if lobby_type in ('golden', 'crime') else 1.0
    bonus = int(rand.randint(1500, 4000) * lobby_boost)

    tools = ["🔧", "🪛", "🔑", "🔨", "🪚", "🧲"]
    target = rand.choice(["🔑", "🧲", "🪛"])
    options = rand.sample(tools, 3)
    if target not in options:
        options[0] = target
    rand.shuffle(options)

    game_text = (f"\n\n🔒 <b>ВЗЛОМ СЕЙФА:</b> Выбери правильный "
                 f"инструмент (<b>{target}</b>)!")
    for opt in options:
        flag = "1" if opt == target else "0"
        builder.button(text=opt, callback_data=f"crime_btn_{game_id}_{flag}")
    builder.adjust(3)

    _cleanup_expired_games()
    active_crime_games[game_id] = {
        'user_id': user_id,
        'bonus': bonus,
        'expires': time.time() + GAME_TTL,
    }
    await message.answer(afk_text + game_text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("crime_btn_"))
async def process_crime_btn(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4:
        return await callback.answer()

    game_id = parts[2]
    is_correct = parts[3] == "1"

    game = active_crime_games.get(game_id)
    if not game:
        return await callback.answer(
            "⏳ Слишком поздно! Сейф заблокировался.", show_alert=True
        )
    if game['user_id'] != callback.from_user.id:
        return await callback.answer("Это не твой сейф!", show_alert=True)
    if time.time() > game['expires']:
        active_crime_games.pop(game_id, None)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return await callback.answer("⏳ Время вышло, копы уже здесь!", show_alert=True)

    if active_crime_games.pop(game_id, None) is None:
        return await callback.answer()

    original = (callback.message.html_text
                if hasattr(callback.message, 'html_text')
                else callback.message.text) or ""

    chat_id = callback.message.chat.id
    rand = secrets.SystemRandom()

    if is_correct:
        await update_user_balance(chat_id, callback.from_user.id, game['bonus'])
        new_text = (original +
                    f"\n\n💎 <b>ДЖЕКПОТ!</b> Ты вытащил "
                    f"<b>{game['bonus']}</b> сыр.!")
    else:
        penalty = rand.randint(500, 1500)
        await update_user_balance(chat_id, callback.from_user.id, -penalty,
                                   is_debt_repayment=True)
        new_text = (original +
                    f"\n\n🚨 <b>ПРОВАЛ!</b> Сирена! Ты потерял "
                    f"<b>{penalty}</b> сыр.")

    try:
        await callback.message.edit_text(new_text, reply_markup=None)
    except Exception:
        await callback.message.answer(new_text)
    await callback.answer()


# ============================================================
#  ОГРАБЛЕНИЕ БАНКА
# ============================================================
@router.message(F.text.lower().startswith("ограбить банк"))
async def cmd_rob_bank(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False):
        return await message.answer("Ты в бане и не можешь грабить банки.")
    if data.get('is_banker', False):
        return await message.answer("🏦 Банкирам запрещено грабить коллег!")

    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        return await message.answer(
            "Использование: <code>ограбить банк [Название]</code>"
        )

    last_rob = data.get('last_bank_rob_time', 0)
    current_time = time.time()
    if current_time - last_rob < ROB_BANK_COOLDOWN:
        remain = int(ROB_BANK_COOLDOWN - (current_time - last_rob))
        hours, rem = divmod(remain, 3600)
        mins, _ = divmod(rem, 60)
        return await message.answer(
            f"⏳ Полиция патрулирует. Заляг на дно ещё на "
            f"{hours} ч. {mins} мин."
        )

    identifier = args[2].strip()
    from profile_bank import get_bank_info, create_or_update_bank
    bank_data = await get_bank_info(chat_id, identifier)
    if not bank_data:
        return await message.answer("🏦 Банк не найден. Проверь название.")

    target_banker_id = bank_data.get('banker_id')
    capital = int(bank_data.get('capital', 0))
    if capital < 10000:
        return await message.answer(
            "В этом банке слишком мало денег, грабить нечего!"
        )

    await update_user_field(chat_id, user_id, 'last_bank_rob_time', current_time)

    rand = secrets.SystemRandom()
    stealth_level = data.get('skills', {}).get('stealth', 0)
    success_chance = min(0.5, 0.05 + stealth_level * 0.02)

    if rand.random() < success_chance:
        steal_percent = rand.uniform(0.01, 0.05)
        stolen = int(capital * steal_percent)
        await create_or_update_bank(
            chat_id, target_banker_id,
            {'capital': capital - stolen}
        )
        await update_user_balance(chat_id, user_id, stolen)
        await message.answer(
            f"🥷 <b>УСПЕШНОЕ ОГРАБЛЕНИЕ!</b>\n\n"
            f"Вы вынесли из <b>{escape_html(bank_data.get('name', '?'))}</b> "
            f"<b>{stolen}</b> сыроежек!"
        )
    else:
        penalty = rand.randint(50_000, 150_000)
        await update_user_balance(chat_id, user_id, -penalty, min_balance=0)
        try:
            await message.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=types.ChatPermissions(can_send_messages=False),
                until_date=timedelta(minutes=30),
            )
            mute_text = "\nВас посадили в тюрьму (мут) на 30 минут."
        except Exception as e:
            logger.warning(f"Не смог замутить {user_id}: {e}")
            mute_text = "\nВам удалось сбежать, но деньги вы потеряли."

        await message.answer(
            f"🚔 <b>ОБЛАВА!</b>\n\n"
            f"Ограбление <b>{escape_html(bank_data.get('name', '?'))}</b> "
            f"провалилось. Потеряно <b>{penalty}</b> сыр.{mute_text}"
        )