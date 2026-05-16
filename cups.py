import asyncio
import secrets
from enum import Enum
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from user_manager import get_user_data, update_user_balance, invalidate_user_cache
from escape import escape_html
from utils import schedule_delete
from config import CREATOR_ID

router = Router()
secure_random = secrets.SystemRandom()

# Временное хранилище активных сессий (на случай перезагрузки FSM)
active_cups_games = {}

class CupsState(StatesGroup):
    difficulty_select = State()  # Ожидание выбора сложности и настроек
    playing = State()            # Игрок выбирает наперсток

class CupsDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    CRAZY = "crazy"

DIFFICULTIES = {
    CupsDifficulty.EASY: {
        "name": "🟢 ЛЕГКИЙ",
        "cups": 3,
        "balls": 1,
        "multiplier": 2.70,
        "desc": "3 напёрстка, 1 шарик 🔴 (Шанс ~33%)",
        "win_chance": 33
    },
    CupsDifficulty.MEDIUM: {
        "name": "🟡 СРЕДНИЙ",
        "cups": 4,
        "balls": 1,
        "multiplier": 3.60,
        "desc": "4 напёрстка, 1 шарик 🔴 (Шанс ~25%)",
        "win_chance": 25
    },
    CupsDifficulty.HARD: {
        "name": "🔴 СЛОЖНЫЙ",
        "cups": 5,
        "balls": 1,
        "multiplier": 4.50,
        "desc": "5 напёрстков, 1 шарик 🔴 (Шанс ~20%)",
        "win_chance": 20
    },
    CupsDifficulty.CRAZY: {
        "name": "🌀 БЕЗУМНЫЙ",
        "cups": 3,
        "balls": 2,
        "multiplier": 1.40,
        "desc": "3 напёрстка, 2 шарика 🔴🔴 (Шанс ~66%)",
        "win_chance": 66
    }
}

# ─────────────────────────────────────────────────────────────
#  КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────────
def get_difficulty_keyboard(bet: int, current_diff: CupsDifficulty) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # Кнопки выбора сложности
    for diff_key, diff in DIFFICULTIES.items():
        is_selected = "✅ " if diff_key == current_diff else ""
        builder.button(
            text=f"{is_selected}{diff['name']} ({diff['multiplier']:.2f}x)",
            callback_data=f"cups_set_diff_{diff_key.value}_{bet}"
        )
    builder.adjust(2)
    
    # Кнопки управления стартом
    builder.row(types.InlineKeyboardButton(
        text=f"🚀 НАЧАТЬ ИГРУ ({bet} сыр.)",
        callback_data=f"cas_conf_cups_{bet}"
    ))
    builder.row(types.InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="cups_cancel"
    ))
    return builder.as_markup()

def get_cups_choices_keyboard(game_id: str, num_cups: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(num_cups):
        builder.button(text=f"🪣 {i + 1}", callback_data=f"cups_play|{game_id}|{i}")
    builder.adjust(3)
    return builder.as_markup()

# ─────────────────────────────────────────────────────────────
#  РЕНДЕРИНГ МЕНЮ ПОДГОТОВКИ
# ─────────────────────────────────────────────────────────────
def format_pre_game(full_name: str, bet: int, current_diff: CupsDifficulty) -> str:
    diff = DIFFICULTIES[current_diff]
    potential_win = int(bet * diff["multiplier"])
    return (
        f"🪣 <b>ИГРА В НАПЁРСТКИ · Подготовка</b> 🪣\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Игрок: <b>{full_name}</b>\n"
        f"💰 Ставка: <b>{bet}</b> сыр.\n"
        f"🎯 Режим: <b>{diff['name']}</b>\n"
        f"📝 Условия: <i>{diff['desc']}</i>\n"
        f"💸 Потенциальный выигрыш: <b>{potential_win}</b> сыр. ({diff['multiplier']:.2f}x)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Выбери сложность кнопками ниже и нажми <b>🚀 НАЧАТЬ ИГРУ</b>!"
    )

# ─────────────────────────────────────────────────────────────
#  БЕЗОПАСНЫЙ EDIT
# ─────────────────────────────────────────────────────────────
async def safe_edit_message(message: types.Message, text: str, reply_markup=None) -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────
#  СТАРТ КОМАНДЫ
# ─────────────────────────────────────────────────────────────
@router.message(Command("cups"))
async def cmd_cups(message: types.Message, state: FSMContext):
    if await state.get_state() == CupsState.playing.state:
        await state.clear()

    chat_id, user_id = message.chat.id, message.from_user.id
    full_name = escape_html(message.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get('is_banned', False):
        return await message.answer("🚫 Вы заблокированы и не можете играть.")

    from diseases import get_active_diseases
    if 'gonorrhea' in await get_active_diseases(chat_id, user_id):
        return await message.answer("🦠 <b>Гонорея</b>: Крупье брезгует пускать тебя за стол. Лечись!")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("💡 Укажите ставку: <code>/cups 100</code>")

    try:
        bet = int(args[1])
        if bet < 10 or bet > 50_000_000:
            raise ValueError
    except ValueError:
        return await message.answer("Ставка должна быть числом от 10 до 50,000,000 сыроежек.")

    if data.get('balance', 0) - bet < -5000:
        return await message.answer("Ваш кредитный лимит (-5000) исчерпан. Пополните баланс.")

    # По умолчанию ставим EASY режим
    await state.set_state(CupsState.difficulty_select)
    await state.update_data(current_diff=CupsDifficulty.EASY, bet=bet)

    text = format_pre_game(full_name, bet, CupsDifficulty.EASY)
    await message.answer(text, reply_markup=get_difficulty_keyboard(bet, CupsDifficulty.EASY))

# ─────────────────────────────────────────────────────────────
#  ОБРАБОТКА НАСТРОЕК СЛОЖНОСТИ
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cups_set_diff_"))
async def process_cups_diff(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    diff_val = parts[3]
    bet = int(parts[4])
    
    try:
        current_diff = CupsDifficulty(diff_val)
    except ValueError:
        return await callback.answer()

    await state.update_data(current_diff=current_diff)
    full_name = escape_html(callback.from_user.full_name)
    text = format_pre_game(full_name, bet, current_diff)
    
    await safe_edit_message(callback.message, text, reply_markup=get_difficulty_keyboard(bet, current_diff))
    await callback.answer(f"Сложность: {DIFFICULTIES[current_diff]['name']}")

@router.callback_query(F.data == "cups_cancel")
async def process_cups_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer("Игра отменена.")

# ─────────────────────────────────────────────────────────────
#  ПОДТВЕРЖДЕНИЕ СТАРТА И АНИМАЦИЯ
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cas_conf_cups_"))
async def process_cups_confirm(callback: types.CallbackQuery, state: FSMContext):
    try:
        bet = int(callback.data.split("_")[3])
    except:
        return await callback.answer()
        
    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    
    fsm_data = await state.get_data()
    current_diff = fsm_data.get("current_diff", CupsDifficulty.EASY)
    diff = DIFFICULTIES[current_diff]

    new_balance = await update_user_balance(chat_id, user_id, -bet, min_balance=-5000, action="Cups Bet")
    if new_balance is None:
        return await callback.answer("Недостаточно средств!", show_alert=True)

    await callback.message.delete()
    await state.set_state(CupsState.playing)

    # Инициализация выигрышных наперстков
    num_cups = diff["cups"]
    num_balls = diff["balls"]
    
    # Генерируем уникальные выигрышные наперстки
    winning_cups = []
    while len(winning_cups) < num_balls:
        ball_pos = secure_random.randint(0, num_cups - 1)
        if ball_pos not in winning_cups:
            winning_cups.append(ball_pos)

    game_id = f"{chat_id}_{user_id}_{callback.message.message_id}"
    
    game_session = {
        'user_id': user_id,
        'chat_id': chat_id,
        'full_name': full_name,
        'bet': bet,
        'current_diff': current_diff,
        'num_cups': num_cups,
        'winning_cups': winning_cups,
    }
    active_cups_games[game_id] = game_session
    await state.update_data(game_id=game_id)

    # 🎬 Красивая анимация перемешивания
    shuffles = [
        "🔄 <b>[ 🪣   🪣   🪣 ]</b>\n<i>Кручу-верчу, запутать хочу...</i>",
        "🔄 <b>[ 🪣   🔄   🪣 ]</b>\n<i>Быстро перемешиваю наперстки...</i>",
        "🔄 <b>[ 🪣   🪣   🔄 ]</b>\n<i>Следи за руками! Где же шарик?</i>"
    ]
    
    # Для 4 и 5 чашек адаптируем визуальный ряд перемешивания
    if num_cups == 4:
        shuffles = [
            "🔄 <b>[ 🪣   🪣   🪣   🪣 ]</b>\n<i>Кручу-верчу...</i>",
            "🔄 <b>[ 🪣   🔄   🪣   🪣 ]</b>\n<i>Быстрее ветра!</i>",
            "🔄 <b>[ 🪣   🪣   🪣   🔄 ]</b>\n<i>Следи внимательно!</i>"
        ]
    elif num_cups == 5:
        shuffles = [
            "🔄 <b>[ 🪣   🪣   🪣   🪣   🪣 ]</b>\n<i>Уследить за пятью почти невозможно...</i>",
            "🔄 <b>[ 🪣   🔄   🪣   🔄   🪣 ]</b>\n<i>Тасуем наперстки...</i>",
            "🔄 <b>[ 🪣   🪣   🪣   🪣   🔄 ]</b>\n<i>Всё! Выбирай свой вариант!</i>"
        ]

    msg = await callback.message.answer(shuffles[0])
    
    for status_text in shuffles[1:]:
        await asyncio.sleep(0.6)
        await safe_edit_message(msg, status_text)

    await asyncio.sleep(0.6)
    
    text = (
        f"🪣 <b>Игра в наперстки! (Режим: {diff['name']})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Игрок: {full_name}\n"
        f"💰 Ставка: <b>{bet}</b> сыр.\n"
        f"🏆 Коэффициент: <b>{diff['multiplier']:.2f}x</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Выбери напёрсток, под которым спрятан шарик 🔴!"
    )
    
    await safe_edit_message(msg, text, reply_markup=get_cups_choices_keyboard(game_id, num_cups))

# ─────────────────────────────────────────────────────────────
#  ОПРЕДЕЛЕНИЕ РЕЗУЛЬТАТА ИГРЫ
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cups_play|"))
async def process_cups_play(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("|")
    if len(parts) != 3:
        return await callback.answer()

    game_id = parts[1]
    chosen_cup = int(parts[2])

    game = active_cups_games.pop(game_id, None)
    if not game:
        return await callback.answer("Игра уже завершена или устарела.", show_alert=True)

    if callback.from_user.id != game['user_id']:
        active_cups_games[game_id] = game  # Возвращаем сессию на место
        return await callback.answer("Это не ваша игра!", show_alert=True)

    await state.clear()
    
    chat_id = game['chat_id']
    user_id = game['user_id']
    full_name = game['full_name']
    bet = game['bet']
    current_diff = game['current_diff']
    winning_cups = game['winning_cups']
    num_cups = game['num_cups']
    
    diff = DIFFICULTIES[current_diff]

    # Анимация поднятия наперстка
    await safe_edit_message(callback.message, "⏳ <i>Поднимаем выбранный наперсток...</i>")
    await asyncio.sleep(0.8)

    # Алгоритм победы / проигрыша
    is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)
    is_win = False

    if is_creator:
        # Создатель всегда побеждает
        is_win = True
        if chosen_cup not in winning_cups:
            winning_cups[0] = chosen_cup
    else:
        # Управляем шансом выигрыша согласно выбранной сложности
        win_chance = diff["win_chance"]
        forced_win = (secure_random.randint(1, 100) <= win_chance)
        
        if forced_win:
            is_win = True
            if chosen_cup not in winning_cups:
                winning_cups[0] = chosen_cup
        else:
            is_win = False
            # Если игрок случайно угадал, принудительно убираем шарик из этого наперстка
            if chosen_cup in winning_cups:
                winning_cups.remove(chosen_cup)
                # Перемещаем шарик в любой другой наперсток
                available_positions = [pos for pos in range(num_cups) if pos != chosen_cup]
                new_pos = secure_random.choice(available_positions)
                winning_cups.append(new_pos)

    # Визуализируем финальное состояние наперстков
    cups_display = ["🪣" for _ in range(num_cups)]
    for pos in winning_cups:
        cups_display[pos] = "🔴"
        
    # Подчеркиваем выбранный наперсток
    cups_display[chosen_cup] = f"👉{cups_display[chosen_cup]}👈"
    
    display_str = "   ".join(cups_display)

    # Расчет выигрыша
    u_data = await get_user_data(chat_id, user_id)
    is_vip = u_data.get('is_vip', False)
    is_banker = u_data.get('is_banker', False)

    if is_win:
        win_amount = int(bet * diff["multiplier"])
        vip_bonus_text = ""
        
        if is_banker:
            # Банкирам выплачивается только 50% чистой прибыли
            profit = win_amount - bet
            reduced_profit = int(profit * 0.5)
            win_amount = bet + reduced_profit
            vip_bonus_text = f" (🏦 Банкирам выплачивается только 50% прибыли)"
        elif is_vip:
            # VIP получают +10% к чистой прибыли
            profit = win_amount - bet
            vip_bonus = int(profit * 0.1)
            win_amount += vip_bonus
            vip_bonus_text = f" (👑 VIP бонус: +{vip_bonus} сыр.)"

        await update_user_balance(chat_id, user_id, win_amount, action="Cups Win")
        result_text = f"🎉 <b>ПОБЕДА!</b>\nВы угадали! Выиграно: <b>+{win_amount - bet}</b> сыр. (Всего получено: {win_amount}){vip_bonus_text}"
    else:
        result_text = f"💀 <b>ПРОИГРЫШ!</b>\nШарик был под другим напёрстком. Вы потеряли <b>-{bet}</b> сыр."

    final_text = (
        f"🪣 <b>Результат игры (Режим: {diff['name']})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Игрок: <b>{full_name}</b>\n"
        f"Ставка: <b>{bet}</b> сыр.\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Расположение шариков:\n"
        f"<b>[  {display_str}  ]</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}"
    )

    # Кнопка для быстрого повтора той же ставки
    replay_builder = InlineKeyboardBuilder()
    replay_builder.row(types.InlineKeyboardButton(
        text=f"🔁 Сыграть еще (ставка {bet})",
        callback_data=f"cups_set_diff_{current_diff.value}_{bet}"
    ))

    await safe_edit_message(callback.message, final_text, reply_markup=replay_builder.as_markup())
    invalidate_user_cache(chat_id, user_id)
    asyncio.create_task(schedule_delete(callback.message, 60))
    await callback.answer()