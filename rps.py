"""
🪨✂️🧻 Камень-Ножницы-Бумага против адаптивного ИИ.

Изменения относительно исходной версии:
  • Серверный реестр активных игр — фикс эксплойта с повторной отправкой callback.
  • Защита от даблклика (atomic-pop + pending-guard).
  • Типизированные CallbackData вместо ручного split("_").
  • Корректный парсер ставок (к/кк/k/kk/m/м) через regex.
  • Валидация MIN_BET/MAX_BET во всех точках входа.
  • Устранено дублирование кода (общие рендеры текста/клавиатур).
  • Guard на недоступные сообщения, точечный отлов TelegramBadRequest.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional, Tuple

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder

from user_manager import (
    get_user_data,
    update_user_balance,
    set_in_cache,
    mark_dirty,
)
from game_ai import play_round, get_ai_stats, reset_ai_memory
from escape import escape_html

router = Router()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────────────────────────────────────
MIN_BET = 100
MAX_BET = 1_000_000_000          # защита от переполнения/абсурдных ставок
CREDIT_LIMIT = -5_000
VIP_PROFIT_BONUS_PCT = 0.10      # +10% к чистой прибыли для VIP
AI_THINK_DELAY = 0.8             # сек. "раздумий" ИИ
GAME_TTL = 3600.0                # сек. жизни незавершённой игры в реестре

# Исходы раунда (семантика game_ai.play_round)
PLAYER_WIN, DRAW, AI_WIN = -1, 0, 1

MOVES_INFO = {
    "r": {"emoji": "🪨", "name": "Камень"},
    "s": {"emoji": "✂️", "name": "Ножницы"},
    "p": {"emoji": "🧻", "name": "Бумага"},
}

PROFILE_TRANSLATIONS = {
    "unknown": "Неопределённый (мало игр)",
    "random": "🎲 Непредсказуемый (Случайный)",
    "sticky": "📌 Прилипчивый (повторяет ходы)",
    "biased": "⚖️ Предвзятый (есть любимый ход)",
    "predictable": "📉 Предсказуемый (шаблонный)",
    "balanced": "⚖️ Сбалансированный",
}

DISEASE_BLOCKS = {
    "gonorrhea": "🦠 <b>Гонорея</b>: Крупье брезгует играть с вами. Лечитесь!",
    "rabies": "🦠 <b>Бешенство</b>: Вы пугаете других игроков. Лечитесь!",
}

_SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"

# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK-ФАБРИКИ (типобезопасно, вместо split("_"))
# ─────────────────────────────────────────────────────────────────────────────
class RpsPlayCB(CallbackData, prefix="rpsP"):
    bet: int
    uid: int
    move: str


class RpsAgainCB(CallbackData, prefix="rpsA"):
    bet: int
    uid: int


class RpsStatsCB(CallbackData, prefix="rpsS"):
    uid: int


# ─────────────────────────────────────────────────────────────────────────────
# РЕЕСТР АКТИВНЫХ ИГР — защита от replay-эксплойта и даблкликов
# ─────────────────────────────────────────────────────────────────────────────
_ACTIVE_GAMES: dict[tuple[int, int], dict] = {}   # (chat_id, message_id) -> game
_PENDING_BETS: set[tuple[int, int]] = set()       # ставки в процессе списания


def _purge_stale_games() -> None:
    """Ленивая чистка зависших игр (ставка при этом уже списана — как и раньше)."""
    now = time.monotonic()
    stale = [k for k, g in _ACTIVE_GAMES.items() if now - g["ts"] > GAME_TTL]
    for k in stale:
        _ACTIVE_GAMES.pop(k, None)


def _register_game(chat_id: int, message_id: int, uid: int, bet: int) -> None:
    _purge_stale_games()
    _ACTIVE_GAMES[(chat_id, message_id)] = {"uid": uid, "bet": bet, "ts": time.monotonic()}


def _consume_game(chat_id: int, message_id: int) -> Optional[dict]:
    """Атомарно забирает игру: повторный клик/replay получит None."""
    return _ACTIVE_GAMES.pop((chat_id, message_id), None)


# ─────────────────────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────────────────────
def _format_money(value: int) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,}".replace(",", " ")


def _get_message(callback: types.CallbackQuery) -> Optional[types.Message]:
    """Guard: в aiogram 3 сообщение может быть недоступным."""
    msg = callback.message
    return msg if isinstance(msg, types.Message) else None


def _move_label(move: str) -> str:
    info = MOVES_INFO[move]
    return f"{info['emoji']} {info['name']}"


def _streak_line(streak: int) -> str:
    if streak > 0:
        return f"🔥 Серия побед ИИ: <b>{streak}</b>"
    if streak < 0:
        return f"👑 Ваша серия побед: <b>{-streak}</b>"
    return ""


def _pct(value: float) -> int:
    return round(value * 100)


def _rps_keyboard(bet: int, uid: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for move in ("r", "s", "p"):
        builder.button(text=_move_label(move), callback_data=RpsPlayCB(bet=bet, uid=uid, move=move))
    builder.button(text="❌ Отмена", callback_data=f"cas_cancel_{uid}")
    builder.adjust(3, 1)
    return builder.as_markup()


def _post_game_keyboard(bet: int, uid: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Ещё раз", callback_data=RpsAgainCB(bet=bet, uid=uid))
    if bet * 2 <= MAX_BET:
        builder.button(text="2️⃣ Удвоить", callback_data=RpsAgainCB(bet=bet * 2, uid=uid))
    builder.button(text="📊 Статистика ИИ", callback_data=RpsStatsCB(uid=uid))
    builder.button(text="❌ Выйти", callback_data=f"cas_cancel_{uid}")
    builder.adjust(2, 2)
    return builder.as_markup()


def _intro_text(full_name: str, bet: int) -> str:
    return (
        f"🪨✂️🧻 <b>Камень-Ножницы-Бумага против ИИ</b>\n\n"
        f"Игрок: <b>{full_name}</b>\n"
        f"Ставка: <b>{_format_money(bet)}</b> сыроежек\n\n"
        f"<i>Сделайте ваш выбор! ИИ уже сделал свой скрытый прогноз.</i>"
    )


# Regex-парсер ставки: число + опциональный суффикс (к/k = тыс., кк/kk/м/m = млн.)
_BET_RE = re.compile(r"^(\d+(?:[.,]\d+)?)(кк|kk|к|k|м|m)?$", re.IGNORECASE)
_SUFFIX_MULT = {"к": 1_000, "k": 1_000, "кк": 1_000_000, "kk": 1_000_000, "м": 1_000_000, "m": 1_000_000}


def _parse_bet(text: str) -> Tuple[Optional[int], Optional[str]]:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return None, "Укажите ставку: <code>/rps 100</code> (можно <code>5к</code>, <code>2кк</code>)"

    raw = parts[1].strip().lower().replace("_", "").replace(" ", "")
    match = _BET_RE.match(raw)
    if not match:
        return None, "Ставка должна быть числом. Пример: <code>/rps 100</code>"

    number, suffix = match.groups()
    multiplier = _SUFFIX_MULT.get(suffix, 1) if suffix else 1
    value = int(float(number.replace(",", ".")) * multiplier)

    if value < MIN_BET:
        return None, f"Минимальная ставка — {_format_money(MIN_BET)} сыроежек."
    if value > MAX_BET:
        return None, f"Максимальная ставка — {_format_money(MAX_BET)} сыроежек."
    return value, None


async def _get_block_reason(chat_id: int, user_id: int, data: dict) -> Optional[str]:
    """Единая проверка бана и болезней. Возвращает текст блокировки или None."""
    if data.get("is_banned", False):
        return "🚫 Вы забанены и не можете играть."

    from diseases import get_active_diseases  # lazy import (циклические зависимости)
    active = await get_active_diseases(chat_id, user_id, u_data=data)
    for disease, text in DISEASE_BLOCKS.items():
        if disease in active:
            return text
    return None


def _render_stats(full_name: str, stats: dict) -> str:
    profile_desc = PROFILE_TRANSLATIONS.get(stats["profile"], stats["profile"])
    return (
        f"🧠 <b>ИИ-Анализ: {full_name}</b>\n\n"
        f"• Профиль стиля: <b>{profile_desc}</b>\n"
        f"• Ходов проанализировано: <b>{stats['total_moves']}</b>\n"
        f"• Точность ИИ: <b>{_pct(stats['winrate_ai'])}%</b>\n"
        f"• Побед ИИ: <b>{stats['ai_wins']}</b> | Ваших побед: <b>{stats['player_wins']}</b> | Ничьих: <b>{stats['draws']}</b>\n"
        f"• {_streak_line(stats['streak']) or 'Серия: <b>0</b>'}\n"
        f"• Память модели: <b>{stats['slot_size_bytes']} байт</b>, узлов: <b>{stats['transition_keys']}</b>"
    )


def _save_ai_memory(chat_id: int, user_id: int, data: dict, ai_mem) -> None:
    data["ai_memory"] = ai_mem
    set_in_cache(chat_id, user_id, data)
    mark_dirty(chat_id, user_id)


# ─────────────────────────────────────────────────────────────────────────────
# КОМАНДА /rps
# ─────────────────────────────────────────────────────────────────────────────
@router.message(Command("rps"))
async def cmd_rps(message: types.Message):
    # Парсим ставку ДО обращения к БД — дёшево и отсекает мусор сразу
    bet, err = _parse_bet(message.text or "")
    if err:
        await message.answer(err)
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    block = await _get_block_reason(chat_id, user_id, data)
    if block:
        await message.answer(block)
        return

    if data.get("balance", 0) - bet < CREDIT_LIMIT:
        await message.answer(
            f"💸 Ваш кредитный лимит ({_format_money(CREDIT_LIMIT)}) исчерпан. Пополните баланс."
        )
        return

    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(message, "rps", bet)


# ─────────────────────────────────────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ СТАВКИ
# ─────────────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cas_conf_rps_"))
async def on_rps_confirm(callback: types.CallbackQuery):
    msg = _get_message(callback)
    if msg is None:
        await callback.answer("⌛ Сообщение устарело.", show_alert=True)
        return

    parts = callback.data.split("_")
    try:
        bet = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Ошибка обработки ставки.")
        return

    # Только автор /rps может подтвердить
    owner_id = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
    if owner_id is not None and callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не ваша ставка!", show_alert=True)
        return

    # Валидация ставки на случай подделки callback-данных
    if not (MIN_BET <= bet <= MAX_BET):
        await callback.answer("Некорректная ставка.", show_alert=True)
        return

    chat_id, message_id = msg.chat.id, msg.message_id
    user_id = callback.from_user.id

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

        new_balance = await update_user_balance(
            chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="RPS Bet"
        )
        if new_balance is None:
            await callback.answer("Недостаточно средств!", show_alert=True)
            return

        try:
            await msg.delete()
        except TelegramBadRequest:
            pass

        sent = await msg.answer(_intro_text(full_name, bet), reply_markup=_rps_keyboard(bet, user_id))
        _register_game(chat_id, sent.message_id, user_id, bet)  # игра валидна только для этого сообщения
        await callback.answer()
    finally:
        release_confirm_lock(chat_id, message_id)


# ─────────────────────────────────────────────────────────────────────────────
# "ЕЩЁ РАЗ" / "УДВОИТЬ"
# ─────────────────────────────────────────────────────────────────────────────
@router.callback_query(RpsAgainCB.filter())
async def on_rps_again(callback: types.CallbackQuery, callback_data: RpsAgainCB):
    if callback.from_user.id != callback_data.uid:
        await callback.answer("⛔ Это не ваша игра!", show_alert=True)
        return

    msg = _get_message(callback)
    if msg is None:
        await callback.answer("⌛ Сообщение устарело.", show_alert=True)
        return

    bet = callback_data.bet
    if not (MIN_BET <= bet <= MAX_BET):
        await callback.answer("Некорректная ставка.", show_alert=True)
        return

    chat_id, user_id = msg.chat.id, callback.from_user.id
    key = (chat_id, msg.message_id)

    # Защита от даблклика: ставка уже списывается или игра уже идёт
    if key in _PENDING_BETS or key in _ACTIVE_GAMES:
        await callback.answer("Ставка уже обрабатывается...", show_alert=True)
        return
    _PENDING_BETS.add(key)

    try:
        full_name = escape_html(callback.from_user.full_name)
        data = await get_user_data(chat_id, user_id, full_name)
        block = await _get_block_reason(chat_id, user_id, data)
        if block:
            await callback.answer(block.replace("<b>", "").replace("</b>", ""), show_alert=True)
            return

        # min_balance сам проверит лимит — предварительная сверка избыточна
        new_balance = await update_user_balance(
            chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="RPS Bet Again"
        )
        if new_balance is None:
            await callback.answer("Недостаточно средств для этой ставки!", show_alert=True)
            return

        intro = _intro_text(full_name, bet)
        keyboard = _rps_keyboard(bet, user_id)
        try:
            await msg.edit_text(intro, reply_markup=keyboard)
            game_message_id = msg.message_id
        except TelegramBadRequest:
            sent = await msg.answer(intro, reply_markup=keyboard)
            game_message_id = sent.message_id

        _register_game(chat_id, game_message_id, user_id, bet)
        await callback.answer()
    finally:
        _PENDING_BETS.discard(key)


# ─────────────────────────────────────────────────────────────────────────────
# ХОД ИГРОКА
# ─────────────────────────────────────────────────────────────────────────────
@router.callback_query(RpsPlayCB.filter())
async def on_rps_play(callback: types.CallbackQuery, callback_data: RpsPlayCB):
    if callback.from_user.id != callback_data.uid:
        await callback.answer("⛔ Это не ваша игра!", show_alert=True)
        return

    msg = _get_message(callback)
    if msg is None:
        await callback.answer("⌛ Сообщение устарело.", show_alert=True)
        return

    move = callback_data.move
    if move not in MOVES_INFO:
        await callback.answer()
        return

    chat_id, user_id = msg.chat.id, callback.from_user.id

    # Атомарно забираем игру: replay-атака и даблклик получат None
    game = _consume_game(chat_id, msg.message_id)
    if game is None or game["uid"] != user_id or game["bet"] != callback_data.bet:
        await callback.answer("⌛ Игра не найдена или уже завершена.", show_alert=True)
        return

    bet = game["bet"]
    full_name = escape_html(callback.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    # Раунд против ИИ + сохранение его памяти
    new_ai_mem, report = play_round(data.get("ai_memory"), "rps", move)
    _save_ai_memory(chat_id, user_id, data, new_ai_mem)

    ai_move = report["ai_move"]
    outcome = report["outcome"]        # PLAYER_WIN / DRAW / AI_WIN
    confidence = report["confidence"]
    totals = report["totals"]
    profile_desc = PROFILE_TRANSLATIONS.get(report["profile"], report["profile"])

    # ── Выплаты ──────────────────────────────────────────────────────────────
    vip_bonus = 0
    if outcome == PLAYER_WIN:
        profit = bet
        if data.get("is_vip", False):
            vip_bonus = int(bet * VIP_PROFIT_BONUS_PCT)
            profit += vip_bonus
        await update_user_balance(chat_id, user_id, bet + profit, action="RPS Win")
        delta, outcome_text = profit, "🎉 <b>ВЫ ВЫИГРАЛИ!</b>"
    elif outcome == AI_WIN:
        delta, outcome_text = -bet, "💀 <b>ИИ ОБЫГРАЛ ВАС!</b>"
    else:
        await update_user_balance(chat_id, user_id, bet, action="RPS Draw Refund")
        delta, outcome_text = 0, "🤝 <b>НИЧЬЯ!</b>"

    # ── Анимация "раздумий" ИИ ───────────────────────────────────────────────
    try:
        await msg.edit_text("⏳ <i>ИИ анализирует ваш паттерн и просчитывает вероятность...</i>")
        await asyncio.sleep(AI_THINK_DELAY)
    except TelegramBadRequest:
        pass

    # ── Итоговый фрейм ───────────────────────────────────────────────────────
    delta_str = f"{'+' if delta > 0 else ''}{_format_money(delta)}"
    vip_line = f"\n👑 VIP-бонус: +{_format_money(vip_bonus)} сыроежек" if vip_bonus else ""
    streak = _streak_line(totals["streak"])

    result_text = (
        f"🪨✂️🧻 <b>Камень-Ножницы-Бумага</b>\n"
        f"{_SEPARATOR}\n"
        f"🤖 <b>Ход ИИ:</b> {_move_label(ai_move)}\n"
        f"👤 <b>Ваш ход:</b> {_move_label(move)}\n"
        f"{_SEPARATOR}\n"
        f"💰 Ставка: <b>{_format_money(bet)}</b> сыр.\n"
        f"✨ {outcome_text}\n"
        f"📈 Изменение баланса: <b>{delta_str}</b>{vip_line}\n"
        f"{_SEPARATOR}\n"
        f"🧠 <b>Анализ вашего стиля ИИ:</b>\n"
        f"• Ваш профиль: <b>{profile_desc}</b>\n"
        f"• Уверенность ИИ в вашем ходе: <b>{_pct(confidence)}%</b>\n"
        f"• Точность прогнозов ИИ: <b>{_pct(totals['winrate_ai'])}%</b>\n"
        f"• Сыграно раундов: <b>{totals['n']}</b> (ИИ: {totals['ai_wins']} | Вы: {totals['player_wins']})"
        + (f"\n{streak}" if streak else "")
    )

    keyboard = _post_game_keyboard(bet, user_id)
    try:
        await msg.edit_text(result_text, reply_markup=keyboard)
    except TelegramBadRequest:
        await msg.answer(result_text, reply_markup=keyboard)

    await callback.answer()


# ─────────────────────────────────────────────────────────────────────────────
# СТАТИСТИКА ИИ
# ─────────────────────────────────────────────────────────────────────────────
@router.message(Command("rps_stats"))
async def cmd_rps_stats(message: types.Message):
    full_name = escape_html(message.from_user.full_name)
    data = await get_user_data(message.chat.id, message.from_user.id, full_name)
    stats = get_ai_stats(data.get("ai_memory"), "rps")
    await message.reply(_render_stats(full_name, stats))


@router.callback_query(RpsStatsCB.filter())
async def on_rps_show_stats(callback: types.CallbackQuery, callback_data: RpsStatsCB):
    if callback.from_user.id != callback_data.uid:
        await callback.answer("⛔ Это не ваша игра!", show_alert=True)
        return

    msg = _get_message(callback)
    if msg is None:
        await callback.answer("⌛ Сообщение устарело.", show_alert=True)
        return

    full_name = escape_html(callback.from_user.full_name)
    data = await get_user_data(msg.chat.id, callback.from_user.id, full_name)
    stats = get_ai_stats(data.get("ai_memory"), "rps")
    await msg.answer(_render_stats(full_name, stats))
    await callback.answer()


# ─────────────────────────────────────────────────────────────────────────────
# СБРОС ПАМЯТИ ИИ
# ─────────────────────────────────────────────────────────────────────────────
@router.message(Command("rps_reset"))
async def cmd_rps_reset(message: types.Message):
    chat_id, user_id = message.chat.id, message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    _save_ai_memory(chat_id, user_id, data, reset_ai_memory())

    await message.reply(
        "🧠 <b>Память ИИ успешно сброшена!</b> "
        "Теперь ИИ начнёт обучаться вашему поведению с нуля."
    )