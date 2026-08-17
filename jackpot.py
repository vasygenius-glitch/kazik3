import asyncio
import logging
import secrets
import time
from aiogram import Router, F, types, Bot
from aiogram.filters import Command, or_f
from aiogram.utils.keyboard import InlineKeyboardBuilder

from escape import escape_html
from user_manager import (
    get_user_data,
    update_user_balance,
    get_user_ref,
    safe_get_snapshot,
    get_user_lock,
    invalidate_user_cache,
)
from prestige import get_prestige_perks
from diseases import get_active_diseases

logger = logging.getLogger(__name__)
router = Router()
secure_random = secrets.SystemRandom()

# Активные лобби джекпота: {chat_id: {...}}
active_jackpots: dict[int, dict] = {}
_chat_locks: dict[int, asyncio.Lock] = {}

def get_jackpot_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]


def format_num(val: int) -> str:
    return f"{val:,}".replace(",", " ")


def calculate_jackpot_tickets(players: list[dict]) -> tuple[list[tuple[dict, int, int]], int]:
    """
    Рассчитывает распределение билетов с учётом бонуса удачи Престижа.
    Возвращает: ([(player, start_ticket, end_ticket)], total_tickets)
    """
    ticket_ranges = []
    current_ticket = 1

    for p in players:
        bet = int(p.get("bet", 0))
        luck_bonus = int(p.get("luck_bonus", 0) or 0)
        # Бонус удачи престижа дает мультипликатор к количеству билетов
        weight = int(bet * (1.0 + (luck_bonus / 100.0)))
        if weight <= 0:
            weight = 1

        start_t = current_ticket
        end_t = current_ticket + weight - 1
        ticket_ranges.append((p, start_t, end_t))
        current_ticket = end_t + 1

    total_tickets = current_ticket - 1
    return ticket_ranges, total_tickets


def pick_jackpot_winner(ticket_ranges: list[tuple[dict, int, int]], total_tickets: int) -> dict:
    """Выбирает победителя на основе криптографического RNG среди всех билетов."""
    if not ticket_ranges or total_tickets <= 0:
        return {}
    winning_ticket = secure_random.randint(1, total_tickets)
    for p, start_t, end_t in ticket_ranges:
        if start_t <= winning_ticket <= end_t:
            return p
    return ticket_ranges[-1][0]


async def safe_refund_jackpot(chat_id: int, reason: str = "Отмена игры") -> bool:
    """Безопасно возвращает ставки всем участникам."""
    lock = get_jackpot_lock(chat_id)
    async with lock:
        lobby = active_jackpots.pop(chat_id, None)
        if not lobby:
            return False

        # Отменяем фоновый таймер
        timer_task = lobby.get("timer_task")
        if timer_task and not timer_task.done():
            timer_task.cancel()

        for p in lobby.get("players", []):
            uid = p.get("id")
            amt = int(p.get("bet", 0) or 0)
            if uid and amt > 0:
                try:
                    await update_user_balance(chat_id, uid, amt, is_debt_repayment=False)
                except Exception as e:
                    logger.error(f"[JACKPOT REFUND ERROR] chat={chat_id}, user={uid}: {e}")
        return True


def build_jackpot_kb(chat_id: int, min_bet: int, host_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # Быстрые кнопки ставок
    b1 = max(100, min_bet)
    b2 = b1 * 5
    b3 = b1 * 25
    b4 = b1 * 100

    builder.button(text=f"+{format_num(b1)}", callback_data=f"jp_bet_{chat_id}_{b1}")
    builder.button(text=f"+{format_num(b2)}", callback_data=f"jp_bet_{chat_id}_{b2}")
    builder.button(text=f"+{format_num(b3)}", callback_data=f"jp_bet_{chat_id}_{b3}")
    builder.button(text=f"+{format_num(b4)}", callback_data=f"jp_bet_{chat_id}_{b4}")
    builder.button(text="💰 All-in", callback_data=f"jp_allin_{chat_id}")
    builder.button(text="🎲 Крутить барабан", callback_data=f"jp_roll_{chat_id}")
    builder.button(text="❌ Отменить", callback_data=f"jp_cancel_{chat_id}")
    builder.adjust(2, 2, 1, 1, 1)
    return builder.as_markup()


def render_jackpot_lobby_text(lobby: dict) -> str:
    total_pot = sum(int(p.get("bet", 0)) for p in lobby.get("players", []))
    min_bet = lobby.get("min_bet", 100)
    players = lobby.get("players", [])
    now = time.time()
    expires = lobby.get("expires", now + 60)
    rem_sec = max(0, int(expires - now))

    # Считаем шансы с учетом билетов/престижа
    ticket_ranges, total_tickets = calculate_jackpot_tickets(players)

    players_text = ""
    if not players:
        players_text = "<i>Пока никто не сделал ставку. Будьте первым!</i>\n"
    else:
        for i, (p, start_t, end_t) in enumerate(ticket_ranges, 1):
            user_bet = p["bet"]
            luck = p.get("luck_bonus", 0)
            luck_badge = f" [+{luck}% 🍀]" if luck > 0 else ""
            tickets_cnt = end_t - start_t + 1
            pct = (tickets_cnt / total_tickets * 100.0) if total_tickets > 0 else 0.0
            players_text += (
                f"{i}. <b>{escape_html(p['name'])}</b>: {format_num(user_bet)} сыр. "
                f"({pct:.1f}%){luck_badge}\n"
            )

    text = (
        f"🎰 <b>ДЖЕКПОТ (ОБЩИЙ БАНК)</b> 🎰\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Банк: <b>{format_num(total_pot)}</b> сыроежек\n"
        f"👥 Участников: <b>{len(players)}</b>\n"
        f"🪙 Минимальная ставка: <b>{format_num(min_bet)}</b> сыр.\n"
        f"⏳ До авто-ролла: <b>{rem_sec}</b> сек.\n\n"
        f"📊 <b>Участники и шансы:</b>\n"
        f"{players_text}\n"
        f"💡 <i>Чем больше ваш вклад, тем выше шанс сорвать весь банк! Перк удачи Престижа дает дополнительные билеты.</i>"
    )
    return text


async def _jackpot_timer_loop(bot: Bot, chat_id: int, message_id: int):
    """Фоновый таймер авто-прокрутки джекпота."""
    try:
        while True:
            await asyncio.sleep(5)
            lobby = active_jackpots.get(chat_id)
            if not lobby or lobby.get("state") != "lobby":
                break

            now = time.time()
            if now >= lobby.get("expires", 0):
                # Время вышло: если участников >= 2, крутим, иначе отменяем и возвращаем
                if len(lobby.get("players", [])) >= 2:
                    await run_jackpot_drawing(bot, chat_id, message_id)
                else:
                    await safe_refund_jackpot(chat_id, "Недостаточно участников")
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text="⏱ <b>Время вышло!</b> В джекпоте не набралось минимум 2 участника. Все ставки возвращены.",
                        )
                    except Exception:
                        pass
                break
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in jackpot timer loop: {e}")


async def run_jackpot_drawing(bot: Bot, chat_id: int, message_id: int):
    """Запускает процесс выбора победителя с анимацией."""
    lock = get_jackpot_lock(chat_id)
    async with lock:
        lobby = active_jackpots.get(chat_id)
        if not lobby or lobby.get("state") != "lobby":
            return
        lobby["state"] = "rolling"

        timer_task = lobby.get("timer_task")
        if timer_task and not timer_task.done():
            timer_task.cancel()

        players = lobby.get("players", [])
        if len(players) < 2:
            active_jackpots.pop(chat_id, None)
            # Возврат
            for p in players:
                amt = int(p.get("bet", 0) or 0)
                if amt > 0:
                    await update_user_balance(chat_id, p["id"], amt, is_debt_repayment=False)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="❌ Для запуска джекпота необходимо минимум 2 игрока! Ставки возвращены.",
                )
            except Exception:
                pass
            return

        total_pot = sum(int(p.get("bet", 0)) for p in players)
        ticket_ranges, total_tickets = calculate_jackpot_tickets(players)
        winner = pick_jackpot_winner(ticket_ranges, total_tickets)

        # Удаляем лобби из активных
        active_jackpots.pop(chat_id, None)

    # Анимация прокрутки барабана
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                f"🎰 <b>СТАВКИ ЗАКРЫТЫ!</b>\n"
                f"💰 Общий банк: <b>{format_num(total_pot)}</b> сыроежек!\n\n"
                f"🎲 <i>Запускаем колесо фортуны...</i>\n"
                f"🌀 [ ░ ░ ░ ░ ░ ░ ░ ░ ░ ░ ]"
            ),
        )
        await asyncio.sleep(1.2)

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                f"🎰 <b>СТАВКИ ЗАКРЫТЫ!</b>\n"
                f"💰 Общий банк: <b>{format_num(total_pot)}</b> сыроежек!\n\n"
                f"🎲 <i>Барабан набирает обороты...</i>\n"
                f"🌀 [ █ █ █ █ █ ░ ░ ░ ░ ░ ]"
            ),
        )
        await asyncio.sleep(1.2)

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=(
                f"🎰 <b>СТАВКИ ЗАКРЫТЫ!</b>\n"
                f"💰 Общий банк: <b>{format_num(total_pot)}</b> сыроежек!\n\n"
                f"🎯 <i>Колесо замедляется... Выбираем счастливчика...</i>\n"
                f"🌀 [ █ █ █ █ █ █ █ █ █ █ ]"
            ),
        )
        await asyncio.sleep(1.5)
    except Exception:
        pass

    # Начисляем весь банк победителю
    winner_id = winner["id"]
    winner_name = winner["name"]
    winner_bet = winner["bet"]

    # Рассчитываем шанс победителя
    winner_tickets = 0
    for p, st, et in ticket_ranges:
        if p["id"] == winner_id:
            winner_tickets = et - st + 1
            break
    winner_pct = (winner_tickets / total_tickets * 100.0) if total_tickets > 0 else 0.0

    await update_user_balance(chat_id, winner_id, total_pot, is_debt_repayment=False, action="Jackpot Win")

    result_text = (
        f"👑 <b>ДЖЕКПОТ СОРВАН! ПОЗДРАВЛЯЕМ!</b> 👑\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Победитель: <b>{escape_html(winner_name)}</b>\n"
        f"💰 Выигрыш: <b>+{format_num(total_pot)}</b> сыроежек!\n"
        f"🎯 Шанс на победу: <b>{winner_pct:.1f}%</b> (вклад: {format_num(winner_bet)} сыр.)\n"
        f"👥 Всего участников: <b>{len(players)}</b>\n\n"
        f"🎉 <i>Все средства из общего банка успешно переведены на баланс победителя!</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Сыграть ещё раз", callback_data=f"jp_new_{chat_id}")
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=result_text,
            reply_markup=builder.as_markup(),
        )
    except Exception:
        await bot.send_message(chat_id, result_text, reply_markup=builder.as_markup())


# ============================================================
#  ХЕНДЛЕРЫ КОМАНД И КНОПОК
# ============================================================

@router.message(Command("jackpot", "джекпот", "pot", "пот", "банк_игра", "куш", "складчина"))
@router.message(F.text.lower().in_(["джекпот", "пот", "/jackpot", "/pot", "банк игра", "/куш", "куш"]))
async def cmd_jackpot(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = message.from_user.full_name

    if message.chat.type not in ["group", "supergroup"]:
        return await message.answer("❌ Игра в Джекпот доступна только в групповых чатах!")

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get("is_banned", False):
        return await message.answer("🚫 Вы заблокированы.")

    # Парсинг минимальной ставки
    args = (message.text or "").split()
    min_bet = 1000
    if len(args) > 1:
        try:
            val = int(args[1])
            if val > 0:
                min_bet = min(val, 100_000_000_000)
        except ValueError:
            pass

    lock = get_jackpot_lock(chat_id)
    async with lock:
        if chat_id in active_jackpots:
            lobby = active_jackpots[chat_id]
            text = render_jackpot_lobby_text(lobby)
            kb = build_jackpot_kb(chat_id, lobby.get("min_bet", 1000), lobby.get("host_id", user_id))
            return await message.answer(
                f"⚠️ В этом чате уже запущена игра!\n\n{text}",
                reply_markup=kb,
            )

        # Создаём новое лобби
        lobby = {
            "chat_id": chat_id,
            "host_id": user_id,
            "host_name": full_name,
            "min_bet": min_bet,
            "state": "lobby",
            "players": [],
            "expires": time.time() + 60,
            "message_id": None,
        }
        active_jackpots[chat_id] = lobby

    text = render_jackpot_lobby_text(lobby)
    kb = build_jackpot_kb(chat_id, min_bet, user_id)
    sent_msg = await message.answer(text, reply_markup=kb)

    lobby["message_id"] = sent_msg.message_id
    # Запускаем фоновый таймер
    lobby["timer_task"] = asyncio.create_task(_jackpot_timer_loop(message.bot, chat_id, sent_msg.message_id))


@router.callback_query(F.data.startswith("jp_bet_"))
async def process_jp_bet_btn(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4:
        return await callback.answer()

    chat_id = int(parts[2])
    bet_amount = int(parts[3])
    user_id = callback.from_user.id
    full_name = callback.from_user.full_name

    await handle_jackpot_deposit(callback, chat_id, user_id, full_name, bet_amount)


@router.callback_query(F.data.startswith("jp_allin_"))
async def process_jp_allin_btn(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 3:
        return await callback.answer()

    chat_id = int(parts[2])
    user_id = callback.from_user.id
    full_name = callback.from_user.full_name

    data = await get_user_data(chat_id, user_id, full_name)
    bal = int(data.get("balance", 0) or 0)
    if bal <= 0:
        return await callback.answer("💸 У вас нет сыроежек для ставки!", show_alert=True)

    await handle_jackpot_deposit(callback, chat_id, user_id, full_name, bal)


async def handle_jackpot_deposit(
    callback: types.CallbackQuery,
    chat_id: int,
    user_id: int,
    full_name: str,
    amount: int,
):
    if amount <= 0:
        return await callback.answer("Сумма должна быть больше нуля.", show_alert=True)

    lock = get_jackpot_lock(chat_id)
    async with lock:
        lobby = active_jackpots.get(chat_id)
        if not lobby or lobby.get("state") != "lobby":
            return await callback.answer("Игра уже завершена или не активна.", show_alert=True)

        min_bet = lobby.get("min_bet", 100)
        # Проверяем баланс
        user_lock = get_user_lock(chat_id, user_id)
        async with user_lock:
            data = await get_user_data(chat_id, user_id, full_name)
            if data.get("is_banned", False):
                return await callback.answer("🚫 Вы заблокированы.", show_alert=True)

            bal = int(data.get("balance", 0) or 0)
            if bal < amount:
                return await callback.answer(
                    f"💸 Недостаточно сыроежек! Ваш баланс: {format_num(bal)} сыр.",
                    show_alert=True,
                )

            # Списываем средства
            await update_user_balance(chat_id, user_id, -amount, is_debt_repayment=False, action="Jackpot Bet")

        # Добавляем или увеличиваем ставку игрока в лобби
        pperks = get_prestige_perks(data)
        luck_bonus = pperks.get("luck_bonus", 0)

        existing_player = next((p for p in lobby["players"] if p["id"] == user_id), None)
        if existing_player:
            existing_player["bet"] += amount
            existing_player["luck_bonus"] = luck_bonus
            existing_player["name"] = full_name
        else:
            lobby["players"].append({
                "id": user_id,
                "name": full_name,
                "bet": amount,
                "luck_bonus": luck_bonus,
            })

        # Продлеваем таймер при ставке (добавляем 30 сек, максимум 120)
        lobby["expires"] = min(time.time() + 120, max(lobby["expires"], time.time() + 30))

        text = render_jackpot_lobby_text(lobby)
        kb = build_jackpot_kb(chat_id, lobby.get("min_bet", 1000), lobby.get("host_id", user_id))

    await callback.answer(f"✅ Ставка {format_num(amount)} сыр. принята!")
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data.startswith("jp_roll_"))
async def process_jp_roll_btn(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 3:
        return await callback.answer()

    chat_id = int(parts[2])
    user_id = callback.from_user.id

    lobby = active_jackpots.get(chat_id)
    if not lobby or lobby.get("state") != "lobby":
        return await callback.answer("Игра уже не активна.", show_alert=True)

    if len(lobby.get("players", [])) < 2:
        return await callback.answer("❌ Для запуска нужно минимум 2 участника!", show_alert=True)

    # Запускать может создатель лобби или любой участник если прошло > 15 сек
    host_id = lobby.get("host_id")
    if user_id != host_id and not any(p["id"] == user_id for p in lobby["players"]):
        return await callback.answer("⛔ Вы не являетесь участником этой игры!", show_alert=True)

    await callback.answer("🎲 Запускаем колесо фортуны!")
    await run_jackpot_drawing(callback.bot, chat_id, callback.message.message_id)


@router.callback_query(F.data.startswith("jp_cancel_"))
async def process_jp_cancel_btn(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 3:
        return await callback.answer()

    chat_id = int(parts[2])
    user_id = callback.from_user.id

    lobby = active_jackpots.get(chat_id)
    if not lobby:
        return await callback.answer("Игра уже завершена.")

    host_id = lobby.get("host_id")
    from config import CREATOR_ID
    if user_id != host_id and user_id != CREATOR_ID:
        return await callback.answer("⛔ Только создатель игры может её отменить!", show_alert=True)

    await safe_refund_jackpot(chat_id, "Отменено создателем")
    await callback.answer("❌ Игра отменена. Все ставки возвращены.")
    try:
        await callback.message.edit_text("❌ <b>Джекпот отменён создателем.</b> Все сделанные ставки возвращены участникам.")
    except Exception:
        pass


@router.callback_query(F.data.startswith("jp_new_"))
async def process_jp_new_btn(callback: types.CallbackQuery):
    await callback.answer()
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    full_name = callback.from_user.full_name

    lock = get_jackpot_lock(chat_id)
    async with lock:
        if chat_id in active_jackpots:
            return await callback.answer("Игра уже запущена!", show_alert=True)

        lobby = {
            "chat_id": chat_id,
            "host_id": user_id,
            "host_name": full_name,
            "min_bet": 1000,
            "state": "lobby",
            "players": [],
            "expires": time.time() + 60,
            "message_id": callback.message.message_id,
        }
        active_jackpots[chat_id] = lobby

    text = render_jackpot_lobby_text(lobby)
    kb = build_jackpot_kb(chat_id, 1000, user_id)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    lobby["timer_task"] = asyncio.create_task(_jackpot_timer_loop(callback.bot, chat_id, callback.message.message_id))
