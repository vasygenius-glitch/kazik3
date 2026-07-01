import asyncio
import logging
import random
import secrets
from typing import Optional, Tuple, Dict, Any

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from user_manager import (
    get_user_data,
    update_user_balance,
    set_in_cache,
    mark_dirty,
    invalidate_user_cache,
)
from game_ai import (
    play_round,
    get_ai_stats,
    reset_ai_memory,
)
from escape import escape_html
from utils import schedule_delete

router = Router()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# КОНСТАНТЫ И НАСТРОЙКИ
# ─────────────────────────────────────────────────────────────────────────────
MIN_BET = 100
CREDIT_LIMIT = -5000

# VIP-бонус (10% к чистой прибыли)
VIP_PROFIT_BONUS_PCT = 0.10

# Смайлики ходов
MOVES_INFO = {
    "r": {"emoji": "🪨", "name": "Камень"},
    "s": {"emoji": "✂️", "name": "Ножницы"},
    "p": {"emoji": "🧻", "name": "Бумага"},
}

PROFILE_TRANSLATIONS = {
    "unknown": "Неопределенный (мало игр)",
    "random": "🎲 Непредсказуемый (Случайный)",
    "sticky": "📌 Прилипчивый (повторяет ходы)",
    "biased": "⚖️ Предвзятый (есть любимый ход)",
    "predictable": "📉 Предсказуемый (шаблонный)",
    "balanced": "⚖️ Сбалансированный",
}

# ─────────────────────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────────────────────
def _format_money(value: int) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,}".replace(",", " ")

def get_rps_keyboard(bet: int, uid: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🪨 Камень", callback_data=f"rps_play_{bet}_{uid}_r")
    builder.button(text="✂️ Ножницы", callback_data=f"rps_play_{bet}_{uid}_s")
    builder.button(text="🧻 Бумага", callback_data=f"rps_play_{bet}_{uid}_p")
    builder.button(text="❌ Отмена", callback_data=f"cas_cancel_{uid}")
    builder.adjust(3, 1)
    return builder.as_markup()

def get_post_game_keyboard(bet: int, uid: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Ещё раз", callback_data=f"rps_again_{bet}_{uid}")
    builder.button(text="2️⃣ Удвоить", callback_data=f"rps_again_{bet * 2}_{uid}")
    builder.button(text="📊 Статистика ИИ", callback_data=f"rps_stats_{uid}")
    builder.button(text="❌ Выйти", callback_data=f"cas_cancel_{uid}")
    builder.adjust(2, 2)
    return builder.as_markup()

def _parse_bet(text: str) -> Tuple[Optional[int], Optional[str]]:
    parts = text.split()
    if len(parts) < 2:
        return None, (
            "Укажите ставку: <code>/rps 100</code>"
        )
    raw = parts[1].lower().replace("_", "").replace(" ", "")
    multiplier = 1
    if raw.endswith("k"):
        multiplier = 1_000
        raw = raw[:-1]
    elif raw.endswith("m") or raw.endswith("кк"):
        multiplier = 1_000_000
        raw = raw.rstrip("mкк")
    try:
        value = int(float(raw) * multiplier)
    except ValueError:
        return None, "Ставка должна быть числом. Пример: <code>/rps 100</code>"
    if value < MIN_BET:
        return None, f"Минимальная ставка — {MIN_BET} сыроежек."
    return value, None

# ─────────────────────────────────────────────────────────────────────────────
# КОМАНДА /rps
# ─────────────────────────────────────────────────────────────────────────────
@router.message(Command("rps"))
async def cmd_rps(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get("is_banned", False):
        await message.answer("🚫 Вы забанены и не можете играть.")
        return

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id, u_data=data)
    if "gonorrhea" in active_diseases:
        await message.answer("🦠 <b>Гонорея</b>: Крупье брезгует играть с вами. Лечитесь!")
        return
    if "rabies" in active_diseases:
        await message.answer("🦠 <b>Бешенство</b>: Вы пугаете других игроков. Лечитесь!")
        return

    bet, err = _parse_bet(message.text)
    if err:
        await message.answer(err)
        return

    balance = data.get("balance", 0)
    if balance - bet < CREDIT_LIMIT:
        await message.answer(
            f"💸 Ваш кредитный лимит ({_format_money(CREDIT_LIMIT)}) исчерпан. Пополните баланс."
        )
        return

    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(message, "rps", bet)

# ─────────────────────────────────────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ СТАВКИ ЧЕРЕЗ CASINO_UTILS
# ─────────────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cas_conf_rps_"))
async def on_rps_confirm(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    try:
        bet = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Ошибка обработки ставки.")
        return

    # --- Проверка: только тот, кто вызвал /rps, может подтвердить ---
    owner_id = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
    if owner_id and callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не ваша ставка!", show_alert=True)
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    message_id = callback.message.message_id

    from casino_utils import try_acquire_confirm_lock, release_confirm_lock
    if not try_acquire_confirm_lock(chat_id, message_id):
        await callback.answer("Ваша ставка уже обрабатывается...", show_alert=True)
        return

    try:
        full_name = escape_html(callback.from_user.full_name)
        data = await get_user_data(chat_id, user_id, full_name)
        if data.get("is_banned", False):
            await callback.answer("Вы забанены.", show_alert=True)
            return

        # Снимаем баланс за ставку
        new_balance = await update_user_balance(
            chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="RPS Bet"
        )
        if new_balance is None:
            await callback.answer("Недостаточно средств!", show_alert=True)
            return

        invalidate_user_cache(chat_id, user_id)
        
        # Удаляем подтверждающее сообщение
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass

        # Отправляем интерфейс игры
        text = (
            f"🪨✂️🧻 <b>Камень-Ножницы-Бумага против ИИ</b>\n\n"
            f"Игрок: <b>{full_name}</b>\n"
            f"Ставка: <b>{_format_money(bet)}</b> сыроежек\n\n"
            f"<i>Сделайте ваш выбор! ИИ уже сделал свой скрытый прогноз.</i>"
        )
        await callback.message.answer(text, reply_markup=get_rps_keyboard(bet, user_id))
        await callback.answer()
    finally:
        release_confirm_lock(chat_id, message_id)

# ─────────────────────────────────────────────────────────────────────────────
# ИГРА ЕЩЕ РАЗ (БЕЗ ДВОЙНОГО ПОДТВЕРЖДЕНИЯ ДЛЯ СКОРОСТИ)
# ─────────────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("rps_again_"))
async def on_rps_again(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    try:
        bet = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer()
        return

    # --- Проверка владельца ---
    owner_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
    if owner_id and callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не ваша игра!", show_alert=True)
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get("is_banned", False):
        await callback.answer("Вы забанены.", show_alert=True)
        return

    balance = data.get("balance", 0)
    if balance - bet < CREDIT_LIMIT:
        await callback.answer("Недостаточно средств для этой ставки!", show_alert=True)
        return

    new_balance = await update_user_balance(
        chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="RPS Bet Again"
    )
    if new_balance is None:
        await callback.answer("Недостаточно средств!", show_alert=True)
        return

    invalidate_user_cache(chat_id, user_id)

    # Меняем текущее сообщение на выбор хода
    text = (
        f"🪨✂️🧻 <b>Камень-Ножницы-Бумага против ИИ</b>\n\n"
        f"Игрок: <b>{full_name}</b>\n"
        f"Ставка: <b>{_format_money(bet)}</b> сыроежек\n\n"
        f"<i>Сделайте ваш выбор! ИИ уже сделал свой скрытый прогноз.</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_rps_keyboard(bet, user_id))
    except Exception:
        await callback.message.answer(text, reply_markup=get_rps_keyboard(bet, user_id))
    
    await callback.answer()

# ─────────────────────────────────────────────────────────────────────────────
# ОБРАБОТКА ХОДА ИГРОКА
# ─────────────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("rps_play_"))
async def on_rps_play(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    try:
        bet = int(parts[2])
        owner_id = int(parts[3])
        player_move = parts[4]
    except (ValueError, IndexError):
        await callback.answer()
        return

    # --- Проверка владельца ---
    if callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не ваша игра!", show_alert=True)
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)

    if player_move not in MOVES_INFO:
        await callback.answer()
        return

    # Загружаем данные пользователя
    data = await get_user_data(chat_id, user_id, full_name)
    ai_mem = data.get("ai_memory")

    # Выполняем раунд через модуль ИИ
    new_ai_mem, report = play_round(ai_mem, "rps", player_move)
    
    # Сохраняем обновленную память ИИ в кэш
    data["ai_memory"] = new_ai_mem
    set_in_cache(chat_id, user_id, data)
    mark_dirty(chat_id, user_id)

    # Извлекаем результаты раунда
    ai_move = report["ai_move"]
    outcome = report["outcome"]  # -1 = игрок победил ИИ (ИИ проиграл), 1 = ИИ победил, 0 = ничья
    confidence = report["confidence"]
    profile = report["profile"]
    totals = report["totals"]

    ai_move_str = f"{MOVES_INFO[ai_move]['emoji']} {MOVES_INFO[ai_move]['name']}"
    player_move_str = f"{MOVES_INFO[player_move]['emoji']} {MOVES_INFO[player_move]['name']}"

    profit = 0
    vip_bonus = 0
    outcome_text = ""

    # Выплаты
    if outcome == -1:  # Игрок победил ИИ
        profit = bet  # чистая прибыль (ставка возвращается + ставка выигрывается)
        is_vip = data.get("is_vip", False)
        if is_vip:
            vip_bonus = int(profit * VIP_PROFIT_BONUS_PCT)
            profit += vip_bonus

        await update_user_balance(chat_id, user_id, bet + profit, action="RPS Win")
        outcome_text = "🎉 <b>ВЫ ВЫИГРАЛИ!</b>"
    elif outcome == 1:  # ИИ победил игрока
        # Ставка уже списана, ничего не возвращаем
        outcome_text = "💀 <b>ИИ ОБЫГРАЛ ВАС!</b>"
    else:  # Ничья
        await update_user_balance(chat_id, user_id, bet, action="RPS Draw Refund")
        outcome_text = "🤝 <b>НИЧЬЯ!</b>"

    invalidate_user_cache(chat_id, user_id)

    # Формируем итоговый фрейм
    streak = totals["streak"]
    if streak > 0:
        streak_line = f"🔥 Серия побед ИИ: <b>{streak}</b>"
    elif streak < 0:
        streak_line = f"👑 Ваша серия побед: <b>{abs(streak)}</b>"
    else:
        streak_line = ""

    vip_line = f"\n👑 VIP-бонус: +{_format_money(vip_bonus)} сыроежек" if vip_bonus > 0 else ""

    profile_desc = PROFILE_TRANSLATIONS.get(profile, profile)

    # Имитация "думающего" ИИ (небольшая задержка перед выводом результата)
    try:
        await callback.message.edit_text("⏳ <i>ИИ анализирует ваш паттерн и просчитывает вероятность...</i>")
        await asyncio.sleep(0.8)
    except Exception:
        pass

    result_text = (
        f"🪨✂️🧻 <b>Камень-Ножницы-Бумага</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>Ход ИИ:</b> {ai_move_str}\n"
        f"👤 <b>Ваш ход:</b> {player_move_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ставка: <b>{_format_money(bet)}</b> сыр.\n"
        f"✨ {outcome_text}\n"
        f"📈 Изменение баланса: <b>{'+' if outcome == -1 else '-' if outcome == 1 else ''}{_format_money(profit if outcome == -1 else bet if outcome == 1 else 0)}</b>{vip_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 <b>Анализ вашего стиля ИИ:</b>\n"
        f"• Ваш профиль: <b>{profile_desc}</b>\n"
        f"• Уверенность ИИ в вашем ходе: <b>{int(confidence * 100)}%</b>\n"
        f"• Точность прогнозов ИИ: <b>{int(totals['winrate_ai'] * 100)}%</b>\n"
        f"• Сыграно раундов: <b>{totals['n']}</b> (ИИ: {totals['ai_wins']} | Вы: {totals['player_wins']})\n"
        f"{streak_line}"
    )

    try:
        await callback.message.edit_text(result_text, reply_markup=get_post_game_keyboard(bet, user_id))
    except Exception:
        await callback.message.answer(result_text, reply_markup=get_post_game_keyboard(bet, user_id))

    await callback.answer()

# ─────────────────────────────────────────────────────────────────────────────
# СТАТИСТИКА ИИ ДЛЯ ИГРОКА
# ─────────────────────────────────────────────────────────────────────────────
@router.message(Command("rps_stats"))
async def cmd_rps_stats(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    ai_mem = data.get("ai_memory")
    stats = get_ai_stats(ai_mem)

    profile_desc = PROFILE_TRANSLATIONS.get(stats["profile"], stats["profile"])

    text = (
        f"🧠 <b>Статистика ИИ-анализа игрока {full_name}</b>\n\n"
        f"• Выявленный профиль: <b>{profile_desc}</b>\n"
        f"• Всего ходов проанализировано: <b>{stats['total_moves']}</b>\n"
        f"• Побед ИИ над вами: <b>{stats['ai_wins']}</b> ({int(stats['winrate_ai'] * 100)}%)\n"
        f"• Ваших побед над ИИ: <b>{stats['player_wins']}</b>\n"
        f"• Ничьих: <b>{stats['draws']}</b>\n"
        f"• Текущая серия: <b>{stats['streak']}</b>\n"
        f"• Занимаемый объем памяти: <b>{stats['doc_size_bytes']} байт</b>\n"
        f"• Уникальных цепочек переходов: <b>{stats['transition_keys']}</b>"
    )
    await message.reply(text)

@router.callback_query(F.data.startswith("rps_stats_"))
async def on_rps_show_stats(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    owner_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if owner_id and callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не ваша игра!", show_alert=True)
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    ai_mem = data.get("ai_memory")
    stats = get_ai_stats(ai_mem)

    profile_desc = PROFILE_TRANSLATIONS.get(stats["profile"], stats["profile"])

    text = (
        f"🧠 <b>ИИ-Анализ: {full_name}</b>\n\n"
        f"• Профиль стиля: <b>{profile_desc}</b>\n"
        f"• Анализ ходов: <b>{stats['total_moves']}</b>\n"
        f"• Точность ИИ: <b>{int(stats['winrate_ai'] * 100)}%</b>\n"
        f"• ИИ выиграл: <b>{stats['ai_wins']}</b> раундов\n"
        f"• Вы выиграли: <b>{stats['player_wins']}</b> раундов\n"
        f"• Ничьих: <b>{stats['draws']}</b>\n"
        f"• Серия: <b>{stats['streak']}</b>\n"
        f"• Узлы связей модели: <b>{stats['transition_keys']}</b>"
    )
    await callback.message.answer(text)
    await callback.answer()

# ─────────────────────────────────────────────────────────────────────────────
# СБРОС ПАМЯТИ ИИ
# ─────────────────────────────────────────────────────────────────────────────
@router.message(Command("rps_reset"))
async def cmd_rps_reset(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    data["ai_memory"] = reset_ai_memory()
    set_in_cache(chat_id, user_id, data)
    mark_dirty(chat_id, user_id)
    invalidate_user_cache(chat_id, user_id)

    await message.reply("🧠 <b>Память ИИ успешно сброшена!</b> Теперь ИИ начнет обучаться вашему поведению с нуля.")
