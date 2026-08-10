# bunker/runner.py
"""Оркестрация: табло, таймеры, ЛС. Единственный модуль, что говорит с Telegram."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup, Message

from bunker import engine, ui
from bunker.models import TG_TEXT_LIMIT, Game, Phase, Player

log = logging.getLogger(__name__)

TICK = 1.0
BOARD_MIN_INTERVAL = 3.0        # не чаще одной правки табло в 3 с
BOT_THINK_DELAY = 1.5           # пауза перед ходами ботов
_bot_username: str = ""


# ------------------------------ низкий уровень ------------------------------ #
async def get_bot_username(bot: Bot) -> str:
    global _bot_username
    if not _bot_username:
        try:
            _bot_username = (await bot.me()).username or ""
        except TelegramAPIError:
            return ""
    return _bot_username


async def safe_send(bot: Bot, chat_id: int, text: str,
                    kb: Optional[InlineKeyboardMarkup] = None, **kw) -> Optional[Message]:
    for attempt in (1, 2):
        try:
            return await bot.send_message(chat_id, text[:TG_TEXT_LIMIT], reply_markup=kb,
                                          parse_mode="HTML",
                                          disable_web_page_preview=True, **kw)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramForbiddenError:
            return None
        except TelegramAPIError as e:
            log.warning("send_message %s: %s", chat_id, e)
            return None
    return None


async def safe_edit(bot: Bot, chat_id: int, message_id: int, text: str,
                    kb: Optional[InlineKeyboardMarkup] = None) -> bool:
    try:
        await bot.edit_message_text(text[:TG_TEXT_LIMIT], chat_id=chat_id,
                                    message_id=message_id, reply_markup=kb,
                                    parse_mode="HTML", disable_web_page_preview=True)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        return False
    except TelegramBadRequest as e:
        return "not modified" in str(e).lower()
    except TelegramForbiddenError:
        return False
    except TelegramAPIError as e:
        log.warning("edit_message %s/%s: %s", chat_id, message_id, e)
        return False


# ---------------------------------- ТАБЛО ----------------------------------- #
async def post_board(bot: Bot, game: Game) -> None:
    """Публикует новое табло (старое теряет кнопки)."""
    text = ui.format_board_text(game)
    kb = ui.get_board_keyboard(game, await get_bot_username(bot))
    if game.board_message_id:
        await safe_edit(bot, game.chat_id, game.board_message_id,
                        "☢️ <i>Табло перенесено ниже 👇</i>", None)
    msg = await safe_send(bot, game.chat_id, text, kb)
    if msg:
        game.board_message_id = msg.message_id
        game.board_signature = text
        game.board_edited_at = time.time()


async def render_board(bot: Bot, game: Game, *, force: bool = False) -> None:
    """Обновляет табло на месте. Вызывать, держа game.lock."""
    text = ui.format_board_text(game)
    if not force:
        if text == game.board_signature:
            return
        if time.time() - game.board_edited_at < BOARD_MIN_INTERVAL:
            return
    if not game.board_message_id:
        return await post_board(bot, game)

    kb = ui.get_board_keyboard(game, await get_bot_username(bot))
    ok = await safe_edit(bot, game.chat_id, game.board_message_id, text, kb)
    if ok:
        game.board_signature = text
        game.board_edited_at = time.time()
    else:
        game.board_message_id = None
        await post_board(bot, game)


async def refresh(bot: Bot, game: Game, *, force: bool = False) -> None:
    async with game.lock:
        await render_board(bot, game, force=force)


# ----------------------------------- ЛС ------------------------------------- #
async def dm(bot: Bot, game: Game, player: Player, text: str,
             kb: Optional[InlineKeyboardMarkup] = None, *, fresh: bool = False) -> bool:
    """Одно редактируемое меню на игрока — никакого спама в ЛС."""
    if player.is_bot:
        return False
    sig = text + (str(kb) if kb else "")
    if not fresh and player.prompt_message_id and sig == player.prompt_signature:
        return True
    if not fresh and player.prompt_message_id:
        if await safe_edit(bot, player.user_id, player.prompt_message_id, text, kb):
            player.prompt_signature = sig
            player.dm_available = True
            return True
    msg = await safe_send(bot, player.user_id, text, kb)
    if msg:
        player.prompt_message_id = msg.message_id
        player.prompt_signature = sig
        player.dm_available = True
        return True
    player.dm_available = False
    return False


async def send_dossier(bot: Bot, game: Game, player: Player) -> bool:
    text = ui.format_dossier_text(game, player)
    kb = ui.get_dossier_keyboard(game, player)
    if player.dossier_message_id and await safe_edit(
            bot, player.user_id, player.dossier_message_id, text, kb):
        player.dm_available = True
        return True
    msg = await safe_send(bot, player.user_id, text, kb)
    if msg:
        player.dossier_message_id = msg.message_id
        player.dm_available = True
        return True
    player.dm_available = False
    return False


async def broadcast_prompts(bot: Bot, game: Game) -> None:
    """Рассылает/обновляет личные меню всем живым людям."""
    for p in game.alive_players():
        text, kb = ui.prompt_for(game, p)
        if text:
            await dm(bot, game, p, text, kb)
            await asyncio.sleep(0.05)
    await warn_closed_dms(bot, game)


async def warn_closed_dms(bot: Bot, game: Game) -> None:
    """Одно предупреждение в чат на всех, у кого закрыт ЛС."""
    lost = [p for p in game.alive_players()
            if not p.is_bot and not p.dm_available and not p.dm_warned]
    if not lost:
        return
    for p in lost:
        p.dm_warned = True
    username = await get_bot_username(bot)
    link = ui.deep_link(username, game.game_id) if username else ""
    names = ", ".join(p.mention for p in lost)
    await safe_send(bot, game.chat_id,
                    f"📩 {names} — откройте ЛС бота, иначе не получите карты."
                    + (f'\n<a href="{link}">Нажмите здесь</a>' if link else ""),
                    disable_notification=True)


# ------------------------------- ПОТОК ИГРЫ --------------------------------- #
async def start_game_flow(bot: Bot, game: Game) -> None:
    """Вызывать, держа game.lock, сразу после engine.start_game_engine."""
    game.push_event(ui.format_intro_text(game))
    await post_board(bot, game)
    for p in game.ordered_players():
        if not p.is_bot:
            await send_dossier(bot, game, p)
            await asyncio.sleep(0.05)
    await warn_closed_dms(bot, game)
    ensure_timer(bot, game)


def ensure_timer(bot: Bot, game: Game) -> None:
    if game.timer_task is None or game.timer_task.done():
        game.timer_task = asyncio.create_task(_loop(bot, game), name=f"bunker:{game.game_id}")


def cancel_timer(game: Game) -> None:
    task, game.timer_task = game.timer_task, None
    if task and not task.done():
        task.cancel()


async def _loop(bot: Bot, game: Game) -> None:
    try:
        while True:
            await asyncio.sleep(TICK)
            if game.phase.is_over or game.phase is Phase.LOBBY:
                return
            async with game.lock:
                if game.phase.is_over or game.phase is Phase.LOBBY:
                    return
                if time.time() - game.phase_started_at > BOT_THINK_DELAY:
                    for ev in engine.process_bot_actions(game):
                        game.push_event(ev)
                if engine.phase_complete(game) or engine.phase_expired(game):
                    await advance_phase(bot, game)
                    if game.phase.is_over:
                        return
                else:
                    await render_board(bot, game)
    except asyncio.CancelledError:
        raise
    except Exception:                                            # noqa: BLE001
        log.exception("bunker loop crashed (game=%s)", game.game_id)
        await safe_send(bot, game.chat_id,
                        "⚠️ Внутренняя ошибка движка. Партия остановлена: /bunker_stop")


async def advance_phase(bot: Bot, game: Game) -> None:
    """Переход к следующей фазе. Вызывать, держа game.lock."""
    phase = game.phase

    if phase is Phase.INTRO:
        engine.set_phase(game, Phase.REVEAL)
        game.clear_events()
        await _announce(bot, game, f"🔓 Раунд {game.current_round}: раскрытие карт в ЛС.")
        await broadcast_prompts(bot, game)

    elif phase is Phase.REVEAL:
        late = engine.auto_close_reveal(game)
        if late:
            game.push_event(f"⌛ Не успели определиться: {late}")
        engine.set_phase(game, Phase.DISCUSSION)
        await _announce(bot, game,
                        f"💬 Обсуждение — {ui.fmt_timer(game.settings.discussion_seconds)}.")
        await broadcast_prompts(bot, game)

    elif phase is Phase.DISCUSSION:
        engine.set_phase(game, Phase.VOTING)
        await _announce(bot, game, "🗳 Голосование в ЛС бота.")
        await broadcast_prompts(bot, game)

    elif phase.is_voting:
        await _resolve_votes(bot, game)
        return

    await render_board(bot, game, force=True)


async def _announce(bot: Bot, game: Game, text: str) -> None:
    """Короткий пинг в чат — только если организатор включил их в настройках."""
    if game.settings.phase_pings:
        await safe_send(bot, game.chat_id, text, disable_notification=True)


async def _resolve_votes(bot: Bot, game: Game) -> None:
    kicked_id, tie, comment = engine.process_voting_results(game)

    if tie:
        engine.start_tiebreak(game)
        game.push_event(comment)
        await render_board(bot, game, force=True)
        await broadcast_prompts(bot, game)
        return

    parts = [f"📊 <b>Итоги раунда {game.current_round}</b>"]
    if game.settings.open_votes and game.votes:
        for voter_id, target_id in game.votes.items():
            v = game.players.get(voter_id)
            t = "никого" if target_id == 0 else game.players[target_id].name
            if v:
                parts.append(f"• {v.safe_name} → {t}")
    if comment:
        parts.append(comment)
    if kicked_id:
        parts.append(engine.kick_player_from_game(game, kicked_id))

    going_on = engine.advance_round(game)
    if going_on:
        parts.append(f"\n🔁 <b>Раунд {game.current_round}</b> — открывайте карты в ЛС.")

    # единственное сообщение в чат за раунд
    await safe_send(bot, game.chat_id, "\n".join(p for p in parts if p))
    await render_board(bot, game, force=True)

    if going_on:
        await broadcast_prompts(bot, game)
    else:
        await _finish(bot, game)


async def _finish(bot: Bot, game: Game) -> None:
    await safe_send(bot, game.chat_id, engine.calculate_epilogue(game))
    engine.finish_game(game)
    await render_board(bot, game, force=True)
    for p in game.humans():
        if p.prompt_message_id:
            await safe_edit(bot, p.user_id, p.prompt_message_id,
                            "🏁 Партия завершена. Спасибо за игру!", None)
    cancel_timer(game)
