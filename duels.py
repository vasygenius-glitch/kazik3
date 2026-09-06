# duels.py
# Production-ready Telegram Duel System for kazik3-main
# Framework: aiogram v3 | Designed by GPT-6 Astra

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from config import (
    MIN_DUEL_BET,
    DUEL_TIMEOUT_SECONDS,
    DUEL_TAX_PERCENT,
)
from user_manager import (
    get_user_data,
    update_user_balance,
)
from escape import escape_html

logger = logging.getLogger(__name__)

DICE_EMOJI = "🎲"

# ─────────────────────────────────────────────
#  Data Models & Store
# ─────────────────────────────────────────────

@dataclass
class DuelSession:
    chat_id: int
    challenger_id: int
    challenger_name: str
    target_id: int
    target_name: str
    bet: int
    message_id: Optional[int] = None
    challenger_roll: Optional[int] = None
    target_roll: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    timeout_task: Optional[asyncio.Task] = field(default=None, repr=False)

    @property
    def is_expired(self) -> bool:
        diff = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return diff > DUEL_TIMEOUT_SECONDS


# Key: (chat_id, challenger_id) -> DuelSession
active_duels: Dict[tuple[int, int], DuelSession] = {}
pending_for_target: Dict[tuple[int, int], tuple[int, int]] = {}


def _session_key(chat_id: int, challenger_id: int) -> tuple[int, int]:
    return (chat_id, challenger_id)


def _cleanup_session(session: DuelSession) -> None:
    key = _session_key(session.chat_id, session.challenger_id)
    active_duels.pop(key, None)
    target_key = (session.chat_id, session.target_id)
    pending_for_target.pop(target_key, None)
    if session.timeout_task and not session.timeout_task.done():
        session.timeout_task.cancel()


def _accept_keyboard(challenger_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⚔️ Принять вызов",
                callback_data=f"duel_accept:{challenger_id}",
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"duel_decline:{challenger_id}",
            ),
        ]
    ])


def _mention(user_id: int, name: str) -> str:
    safe_name = escape_html(name or "Игрок")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


# ─────────────────────────────────────────────
#  Router
# ─────────────────────────────────────────────

router = Router(name="duels")


@router.message(Command("duel", "дуэль"))
async def cmd_duel(message: Message, bot: Bot) -> None:
    """
    Создание дуэли:
    /duel [ставка] (в ответ на сообщение)
    /duel @username [ставка]
    """
    if message.chat.type in ("private",):
        await message.reply("⚔️ Дуэли доступны только в групповых чатах!")
        return

    challenger = message.from_user
    if not challenger:
        return

    target: Optional[User] = None
    bet: int = MIN_DUEL_BET

    # 1. Поиск оппонента (ответ на сообщение или упоминание)
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
    elif message.entities:
        for entity in message.entities:
            if entity.type == "text_mention" and entity.user:
                target = entity.user
                break

    # 2. Разбор ставки из текста
    parts = (message.text or "").split()
    for token in parts[1:]:
        cleaned = token.replace(",", "").replace("_", "")
        if cleaned.isdigit():
            val = int(cleaned)
            if val > 0:
                bet = val
                break

    if target is None:
        await message.reply(
            "⚔️ <b>Как вызвать на дуэль:</b>\n\n"
            "• Ответьте на сообщение игрока командой <code>/duel 1000</code>\n"
            "• Либо напишите: <code>/duel @username 1000</code>",
            parse_mode="HTML",
        )
        return

    if target.id == challenger.id:
        await message.reply("🤡 Нельзя вызвать на дуэль самого себя!")
        return

    if target.is_bot:
        await message.reply("🤖 Боты не принимают дуэльные вызовы.")
        return

    if bet < MIN_DUEL_BET:
        await message.reply(f"⚠️ Минимальная ставка для дуэли: <b>{MIN_DUEL_BET}</b> монет.", parse_mode="HTML")
        return

    # Проверка активных дуэлей
    c_key = _session_key(message.chat.id, challenger.id)
    if c_key in active_duels:
        await message.reply("⏳ У вас уже есть активный дуэльный вызов. Дождитесь его завершения.")
        return

    t_key = (message.chat.id, target.id)
    if t_key in pending_for_target:
        await message.reply(f"⚠️ {_mention(target.id, target.full_name)} уже ожидает ответа в другой дуэли.", parse_mode="HTML")
        return

    # 3. Проверка и блокировка ставки у инициатора
    c_data = await get_user_data(message.chat.id, challenger.id)
    c_balance = int(c_data.get("balance", 0) or 0)
    if c_balance < bet:
        await message.reply(
            f"💸 Недостаточно монет для дуэли!\nУ вас: <b>{c_balance:,}</b> монет, ставка: <b>{bet:,}</b>.",
            parse_mode="HTML",
        )
        return

    # Списываем ставку инициатора на время ожидания
    res_debit = await update_user_balance(
        message.chat.id,
        challenger.id,
        -bet,
        min_balance=0,
        action="Duel Lock Bet",
    )
    if res_debit is None:
        await message.reply("❌ Ошибка списания средств. Попробуйте снова.")
        return

    # Создание сессии
    session = DuelSession(
        chat_id=message.chat.id,
        challenger_id=challenger.id,
        challenger_name=challenger.full_name,
        target_id=target.id,
        target_name=target.full_name,
        bet=bet,
    )
    active_duels[c_key] = session
    pending_for_target[t_key] = c_key

    text = (
        f"⚔️ <b>ДУЭЛЬНЫЙ ВЫЗОВ!</b>\n\n"
        f"🔴 {_mention(challenger.id, challenger.full_name)} вызывает "
        f"{_mention(target.id, target.full_name)} на смертельную дуэль!\n\n"
        f"💰 Ставка: <b>{bet:,}</b> монет\n"
        f"🏆 Победитель забирает банк: <b>{int(bet * 2 * (1 - DUEL_TAX_PERCENT)):,}</b> монет\n"
        f"⏰ Вызов действителен: <b>{DUEL_TIMEOUT_SECONDS}с</b>"
    )

    sent = await message.answer(
        text,
        reply_markup=_accept_keyboard(challenger.id),
        parse_mode="HTML",
    )
    session.message_id = sent.message_id

    # Фоновая задача авто-отмены по таймауту
    session.timeout_task = asyncio.create_task(
        _auto_cancel_duel(bot, session, sent.message_id)
    )


async def _auto_cancel_duel(bot: Bot, session: DuelSession, message_id: int) -> None:
    await asyncio.sleep(DUEL_TIMEOUT_SECONDS)

    key = _session_key(session.chat_id, session.challenger_id)
    if key not in active_duels:
        return

    _cleanup_session(session)

    # Возврат ставки создателю
    await update_user_balance(session.chat_id, session.challenger_id, session.bet, action="Duel Timeout Refund")

    text = (
        f"⏰ <b>Время вызова истекло!</b>\n\n"
        f"{_mention(session.target_id, session.target_name)} проигнорировал вызов.\n"
        f"Ставка <b>{session.bet:,}</b> монет возвращена {_mention(session.challenger_id, session.challenger_name)}."
    )
    try:
        await bot.edit_message_text(
            chat_id=session.chat_id,
            message_id=message_id,
            text=text,
            reply_markup=None,
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("duel_accept:"))
async def cb_duel_accept(callback: CallbackQuery, bot: Bot) -> None:
    challenger_id = int(callback.data.split(":")[1])
    key = _session_key(callback.message.chat.id, challenger_id)
    session = active_duels.get(key)

    if not session:
        await callback.answer("❌ Дуэль уже завершена или отменена.", show_alert=True)
        return

    if callback.from_user.id != session.target_id:
        await callback.answer("🚫 Этот вызов брошен не вам!", show_alert=True)
        return

    if session.is_expired:
        _cleanup_session(session)
        await update_user_balance(session.chat_id, session.challenger_id, session.bet, action="Duel Expired Refund")
        await callback.answer("⏰ Время вызова истекло.", show_alert=True)
        return

    # Проверка баланса вызванного игрока
    t_data = await get_user_data(session.chat_id, session.target_id)
    t_balance = int(t_data.get("balance", 0) or 0)
    if t_balance < session.bet:
        await callback.answer(
            f"💸 У вас недостаточно монет (нужно {session.bet:,}, у вас {t_balance:,})!",
            show_alert=True,
        )
        return

    # Списываем ставку оппонента
    res_debit = await update_user_balance(
        session.chat_id,
        session.target_id,
        -session.bet,
        min_balance=0,
        action="Duel Accept Bet",
    )
    if res_debit is None:
        await callback.answer("❌ Ошибка списания ставки.", show_alert=True)
        return

    # Отменяем таймаут
    if session.timeout_task and not session.timeout_task.done():
        session.timeout_task.cancel()

    await callback.answer("⚔️ Вызов принят! Кубики брошены!")

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    await _run_duel(bot, session)


@router.callback_query(F.data.startswith("duel_decline:"))
async def cb_duel_decline(callback: CallbackQuery, bot: Bot) -> None:
    challenger_id = int(callback.data.split(":")[1])
    key = _session_key(callback.message.chat.id, challenger_id)
    session = active_duels.get(key)

    if not session:
        await callback.answer("❌ Дуэль уже завершена.", show_alert=True)
        return

    if callback.from_user.id not in (session.target_id, session.challenger_id):
        await callback.answer("🚫 Вы не участник этой дуэли.", show_alert=True)
        return

    _cleanup_session(session)

    # Возврат ставки инициатору
    await update_user_balance(session.chat_id, session.challenger_id, session.bet, action="Duel Decline Refund")

    decliner_name = callback.from_user.full_name
    text = (
        f"🏳️ {_mention(callback.from_user.id, decliner_name)} отклонил дуэль.\n\n"
        f"Ставка <b>{session.bet:,}</b> монет возвращена {_mention(session.challenger_id, session.challenger_name)}."
    )
    try:
        await callback.message.edit_text(text, reply_markup=None, parse_mode="HTML")
    except TelegramBadRequest:
        pass

    await callback.answer("Дуэль отменена.")


async def _run_duel(bot: Bot, session: DuelSession) -> None:
    chat_id = session.chat_id

    intro = (
        f"⚔️ <b>ДУЭЛЬ НАЧАЛАСЬ!</b>\n\n"
        f"🔴 {_mention(session.challenger_id, session.challenger_name)}\n"
        f"🔵 {_mention(session.target_id, session.target_name)}\n\n"
        f"💰 Банк дуэли: <b>{session.bet * 2:,}</b> монет\n"
        f"Бросаем кубики..."
    )
    await bot.send_message(chat_id, intro, parse_mode="HTML")
    await asyncio.sleep(1.0)

    # Бросок инициатора
    await bot.send_message(
        chat_id,
        f"🔴 {_mention(session.challenger_id, session.challenger_name)} бросает кубик...",
        parse_mode="HTML",
    )
    c_dice = await bot.send_dice(chat_id, emoji=DICE_EMOJI)
    c_roll = c_dice.dice.value
    session.challenger_roll = c_roll

    await asyncio.sleep(3.5)

    # Бросок оппонента
    await bot.send_message(
        chat_id,
        f"🔵 {_mention(session.target_id, session.target_name)} бросает кубик...",
        parse_mode="HTML",
    )
    t_dice = await bot.send_dice(chat_id, emoji=DICE_EMOJI)
    t_roll = t_dice.dice.value
    session.target_roll = t_roll

    await asyncio.sleep(3.5)

    # Расчет результата
    total_pot = session.bet * 2
    tax = int(total_pot * DUEL_TAX_PERCENT)
    win_prize = total_pot - tax

    c_mention = _mention(session.challenger_id, session.challenger_name)
    t_mention = _mention(session.target_id, session.target_name)

    scores = (
        f"\n\n📊 <b>Результаты бросков:</b>\n"
        f"🔴 {c_mention}: <b>{c_roll}</b> 🎲\n"
        f"🔵 {t_mention}: <b>{t_roll}</b> 🎲"
    )

    if c_roll > t_roll:
        await update_user_balance(chat_id, session.challenger_id, win_prize, action="Duel Win Prize")
        result = (
            f"🏆 <b>ПОБЕДИТЕЛЬ: {c_mention}!</b>\n"
            f"Выигрыш: <b>+{win_prize:,}</b> монет!\n"
            f"<i>(Комиссия стола: {tax:,} монет)</i>"
        )
    elif t_roll > c_roll:
        await update_user_balance(chat_id, session.target_id, win_prize, action="Duel Win Prize")
        result = (
            f"🏆 <b>ПОБЕДИТЕЛЬ: {t_mention}!</b>\n"
            f"Выигрыш: <b>+{win_prize:,}</b> монет!\n"
            f"<i>(Комиссия стола: {tax:,} монет)</i>"
        )
    else:
        # Ничья - возврат ставок
        await update_user_balance(chat_id, session.challenger_id, session.bet, action="Duel Draw Refund")
        await update_user_balance(chat_id, session.target_id, session.bet, action="Duel Draw Refund")
        result = (
            f"🤝 <b>НИЧЬЯ!</b>\n"
            f"Оба выбросили <b>{c_roll}</b>! Ставки полностью возвращены игрокам."
        )

    _cleanup_session(session)
    await bot.send_message(chat_id, f"⚔️ <b>ИТОГ ДУЭЛИ</b>{scores}\n\n{result}", parse_mode="HTML")
