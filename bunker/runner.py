# bunker/runner.py
"""Оркестратор: рассылка сообщений, табло и автопереходы фаз по таймеру.

ВАЖНО про блокировки:
  * функции с префиксом «_» ДОЛЖНЫ вызываться при уже захваченном game.lock;
  * публичные `sync_locked()` вызывается ПОД локом (из хендлеров),
    `tick()` берёт лок сам (фоновая задача).
asyncio.Lock не реентрантный — повторный захват = дедлок.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

from bunker import engine, ui
from bunker.cards_img import render_player_dossier_png
from bunker.models import Game, Phase, Player

log = logging.getLogger(__name__)

TICK_SECONDS = 3
MAX_TRANSITIONS_PER_TICK = 8
_bot_username_cache: dict[int, str] = {}


async def get_bot_username(bot: Bot) -> str:
    if bot.id in _bot_username_cache:
        return _bot_username_cache[bot.id]
    try:
        me = await bot.get_me()
        _bot_username_cache[bot.id] = me.username or ""
    except TelegramAPIError:
        return ""
    return _bot_username_cache[bot.id]


# --------------------------------------------------------------------------- #
#                            безопасные врапперы                              #
# --------------------------------------------------------------------------- #
async def safe_send(bot: Bot, chat_id: int, text: str, reply_markup=None,
                    disable_notification: bool = False):
    try:
        return await bot.send_message(chat_id, text, reply_markup=reply_markup,
                                      parse_mode="HTML",
                                      disable_web_page_preview=True,
                                      disable_notification=disable_notification)
    except TelegramForbiddenError:
        return None
    except TelegramAPIError as e:
        log.warning("send_message failed (%s): %s", chat_id, e)
        return None


async def safe_edit(bot: Bot, chat_id: int, message_id: int, text: str, reply_markup=None) -> bool:
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text,
                                    reply_markup=reply_markup, parse_mode="HTML",
                                    disable_web_page_preview=True)
        return True
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return True
        return False
    except TelegramAPIError:
        return False


async def safe_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        pass


# --------------------------------------------------------------------------- #
#                            личные сообщения                                 #
# --------------------------------------------------------------------------- #
async def _dm(bot: Bot, game: Game, player: Player, text: str, reply_markup=None,
              replace_prompt: bool = False) -> bool:
    """Отправка в ЛС. Возвращает False, если ЛС закрыто."""
    if player.is_bot:
        return True
    if replace_prompt and player.prompt_message_id:
        await safe_delete(bot, player.user_id, player.prompt_message_id)
        player.prompt_message_id = None

    msg = await safe_send(bot, player.user_id, text, reply_markup)
    if msg is None:
        player.dm_available = False
        return False

    player.dm_available = True
    if replace_prompt:
        player.prompt_message_id = msg.message_id
    return True


async def _warn_no_dm(bot: Bot, game: Game, player: Player) -> None:
    if player.dm_warned or player.is_bot:
        return
    player.dm_warned = True
    username = await get_bot_username(bot)
    link = ui.deep_link(username, game.game_id) if username else "ЛС бота"
    await safe_send(
        bot, game.chat_id,
        f"⚠️ {player.mention}, у меня закрыт доступ в ваши личные сообщения — "
        f"я не могу прислать карты.\n👉 Откройте: {link} и нажмите <b>Start</b>.",
    )


async def send_dossier(bot: Bot, game: Game, player: Player,
                       reply_markup=None, with_image: Optional[bool] = None) -> bool:
    """Личное дело в ЛС: текст (всегда) + PNG (опционально)."""
    if player.is_bot or not player.cards:
        return False

    if with_image is None:
        with_image = game.settings.show_card_images
    if with_image:
        try:
            from aiogram.types import BufferedInputFile
            buf = render_player_dossier_png(player, game.scenario)
            data = buf.getvalue() if buf else b""
            if len(data) > 500:
                await bot.send_photo(
                    chat_id=player.user_id,
                    photo=BufferedInputFile(data, filename=f"dossier_{player.user_id}.png"),
                    caption="☢️ Ваше личное дело (секретно)",
                )
        except TelegramForbiddenError:
            player.dm_available = False
            return False
        except Exception as e:                              # noqa: BLE001
            log.debug("dossier image skipped: %s", e)

    text = ui.format_dossier_text(game, player)
    kb = reply_markup if reply_markup is not None else ui.get_dossier_keyboard(game, player)
    return await _dm(bot, game, player, text, kb)


async def _send_phase_prompts(bot: Bot, game: Game) -> None:
    """Личное меню действий по текущей фазе."""
    for p in game.alive_players():
        if p.is_bot:
            continue
        if game.phase is Phase.REVEAL:
            kb = ui.get_reveal_keyboard(game, p.user_id)
            if kb is None:
                continue
            ok = await _dm(bot, game, p, ui.format_reveal_prompt(game, p), kb, replace_prompt=True)
        elif game.phase.is_voting:
            kb = ui.get_vote_keyboard(game, p.user_id)
            if kb is None:
                continue
            ok = await _dm(bot, game, p, ui.format_vote_prompt(game), kb, replace_prompt=True)
        else:
            continue
        if not ok:
            await _warn_no_dm(bot, game, p)


async def _clear_prompts(bot: Bot, game: Game) -> None:
    for p in game.players.values():
        if p.prompt_message_id:
            await safe_delete(bot, p.user_id, p.prompt_message_id)
            p.prompt_message_id = None


# --------------------------------------------------------------------------- #
#                                 табло                                       #
# --------------------------------------------------------------------------- #
async def _render_board(bot: Bot, game: Game, force_new: bool = False) -> None:
    username = await get_bot_username(bot)
    text = ui.format_board_text(game)
    kb = ui.get_board_keyboard(game, username)

    if force_new or not game.board_message_id:
        if game.board_message_id:
            await safe_delete(bot, game.chat_id, game.board_message_id)
        msg = await safe_send(bot, game.chat_id, text, kb)
        if msg:
            game.board_message_id = msg.message_id
            game.board_signature = text
        return

    if text == game.board_signature:
        return
    if await safe_edit(bot, game.chat_id, game.board_message_id, text, kb):
        game.board_signature = text
    else:
        msg = await safe_send(bot, game.chat_id, text, kb)
        if msg:
            game.board_message_id = msg.message_id
            game.board_signature = text


# --------------------------------------------------------------------------- #
#                          переходы между фазами                              #
# --------------------------------------------------------------------------- #
async def _begin_reveal(bot: Bot, game: Game) -> None:
    engine.set_phase(game, Phase.REVEAL)
    limit = engine.reveals_allowed(game)
    await safe_send(
        bot, game.chat_id,
        f"🔓 <b>РАУНД {game.current_round}/{game.total_rounds} · РАСКРЫТИЕ КАРТ</b>\n"
        f"Каждый обязан раскрыть <b>{limit}</b> карт(ы) "
        f"{'или отказаться' if game.settings.allow_no_reveal else ''}.\n"
        f"⏳ {ui.fmt_timer(game.timer_seconds)} · выбор делается <b>в ЛС бота</b>.",
    )
    await _send_phase_prompts(bot, game)


async def _begin_discussion(bot: Bot, game: Game) -> None:
    await _clear_prompts(bot, game)
    engine.set_phase(game, Phase.DISCUSSION)
    await safe_send(
        bot, game.chat_id,
        f"💬 <b>ОБСУЖДЕНИЕ · {ui.fmt_timer(game.timer_seconds)}</b>\n"
        f"Доказывайте свою полезность, ищите слабых, договаривайтесь.\n"
        f"Когда все нажмут «⏭ Я готов(а)» — перейдём к голосованию досрочно.",
    )


async def _begin_voting(bot: Bot, game: Game, tiebreak: bool = False) -> None:
    await _clear_prompts(bot, game)
    game.votes.clear()
    for p in game.players.values():
        p.voted_for = None
    engine.set_phase(game, Phase.TIEBREAK if tiebreak else Phase.VOTING)
    title = "⚖️ <b>ПЕРЕГОЛОСОВАНИЕ</b>" if tiebreak else "🗳 <b>ГОЛОСОВАНИЕ</b>"
    await safe_send(
        bot, game.chat_id,
        f"{title} · {ui.fmt_timer(game.timer_seconds)}\n"
        f"Голосуем тайно в ЛС бота. Кто наберёт больше голосов — покидает бункер.",
    )
    await _send_phase_prompts(bot, game)


async def _finish_voting(bot: Bot, game: Game) -> None:
    kicked_id, is_tie, comment = engine.process_voting_results(game)
    if comment:
        await safe_send(bot, game.chat_id, comment)

    if is_tie:
        await _begin_voting(bot, game, tiebreak=True)
        return

    await _clear_prompts(bot, game)
    if kicked_id:
        text = engine.kick_player_from_game(game, kicked_id)
        if text:
            await safe_send(bot, game.chat_id, text)

    if engine.advance_round(game):
        await _render_board(bot, game, force_new=True)
        await _begin_reveal(bot, game)
    else:
        await _begin_epilogue(bot, game)


async def _begin_epilogue(bot: Bot, game: Game) -> None:
    await _clear_prompts(bot, game)
    engine.set_phase(game, Phase.EPILOGUE, timer=0)
    epilogue = engine.calculate_epilogue(game)
    await _render_board(bot, game, force_new=True)          # финальное табло: всё открыто
    await safe_send(bot, game.chat_id, epilogue)
    engine.finish_game(game)
    engine.drop_game(game.game_id)


async def _resolve_transitions(bot: Bot, game: Game) -> bool:
    """Двигает фазы, пока есть что двигать. -> True, если фаза менялась."""
    changed = False
    for _ in range(MAX_TRANSITIONS_PER_TICK):
        public = engine.process_bot_actions(game)
        for line in public:
            await safe_send(bot, game.chat_id, line, disable_notification=True)

        phase = game.phase
        expired = engine.phase_expired(game)

        if phase is Phase.INTRO:
            if expired:
                await _begin_reveal(bot, game)
                changed = True
                continue
            break

        if phase is Phase.REVEAL:
            if engine.check_reveal_complete(game):
                await _begin_discussion(bot, game)
                changed = True
                continue
            if expired:
                for line in engine.auto_close_reveal(game):
                    await safe_send(bot, game.chat_id, line, disable_notification=True)
                await _begin_discussion(bot, game)
                changed = True
                continue
            break

        if phase is Phase.DISCUSSION:
            if engine.discussion_complete(game) or expired:
                await _begin_voting(bot, game)
                changed = True
                continue
            break

        if phase.is_voting:
            if engine.check_voting_complete(game) or expired:
                await _finish_voting(bot, game)
                changed = True
                continue
            break

        if phase is Phase.EPILOGUE:
            await _begin_epilogue(bot, game)
            changed = True
            break

        break
    return changed


# --------------------------------------------------------------------------- #
#                              публичный API                                  #
# --------------------------------------------------------------------------- #
async def sync_locked(bot: Bot, game: Game, force_new_board: bool = False) -> None:
    """Вызывать ТОЛЬКО при захваченном game.lock."""
    if game.phase is Phase.LOBBY:
        return
    changed = await _resolve_transitions(bot, game)
    if game.phase is Phase.FINISHED:
        return
    await _render_board(bot, game, force_new=force_new_board or changed)


async def start_game_flow(bot: Bot, game: Game) -> None:
    """Первый запуск партии. Вызывать под локом."""
    await safe_send(bot, game.chat_id, ui.format_intro_text(game))
    for p in game.players.values():
        if p.is_bot:
            continue
        ok = await send_dossier(bot, game, p)
        if not ok:
            await _warn_no_dm(bot, game, p)
    game.board_message_id = None
    await _render_board(bot, game, force_new=True)
    ensure_timer(bot, game)


def ensure_timer(bot: Bot, game: Game) -> None:
    if game.timer_task and not game.timer_task.done():
        return
    game.timer_task = asyncio.create_task(_timer_loop(bot, game), name=f"bunker-{game.game_id}")


def cancel_timer(game: Game) -> None:
    task = game.timer_task
    game.timer_task = None
    if task and not task.done() and task is not asyncio.current_task():
        task.cancel()


async def _timer_loop(bot: Bot, game: Game) -> None:
    try:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            if game.phase is Phase.FINISHED:
                return
            async with game.lock:
                if game.phase is Phase.FINISHED:
                    return
                try:
                    await sync_locked(bot, game)
                except Exception as e:                       # noqa: BLE001
                    log.exception("bunker tick error: %s", e)
                if game.phase is Phase.FINISHED:
                    return
    except asyncio.CancelledError:
        raise
    finally:
        if game.timer_task is asyncio.current_task():
            game.timer_task = None
