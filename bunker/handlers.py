# bunker/handlers.py
from __future__ import annotations

import logging

from aiogram import Bot, F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandObject, or_f

from bunker import engine, runner, ui
from bunker.models import Phase
from bunker.ui import BunkerCB

try:
    from config import CREATOR_ID, CREATOR_IDS
except Exception:                                            # noqa: BLE001
    CREATOR_ID, CREATOR_IDS = 0, []

log = logging.getLogger(__name__)
router = Router(name="bunker")


def is_bot_creator(user_id: int) -> bool:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    if uid in {int(x) for x in (CREATOR_IDS or [])}:
        return True
    return bool(CREATOR_ID) and uid == int(CREATOR_ID)


def can_manage(game, user_id: int) -> bool:
    return user_id == game.host_id or is_bot_creator(user_id)


async def _refresh_lobby(bot: Bot, game) -> None:
    if not game.lobby_message_id:
        return
    username = await runner.get_bot_username(bot)
    await runner.safe_edit(
        bot, game.chat_id, game.lobby_message_id,
        ui.format_lobby_text(game),
        ui.get_lobby_keyboard(game, username, is_bot_creator(game.host_id)),
    )


# --------------------------------- команды ---------------------------------- #
@router.message(Command("bunker_stop", "bunkerstop", "stop_bunker", "stopbunker"))
async def cmd_bunker_stop(message: types.Message, bot: Bot):
    game = engine.get_game_by_chat(message.chat.id)
    if not game:
        return await message.answer("❌ Активной игры нет.")
    if not can_manage(game, message.from_user.id):
        return await message.answer("❌ Остановить может только организатор.")
    async with game.lock:
        runner.cancel_timer(game)
        engine.cancel_game(game)
        engine.drop_game(game.game_id)
        if game.lobby_message_id:
            await runner.safe_edit(bot, game.chat_id, game.lobby_message_id, "🚪 Лобби закрыто (игра остановлена).", None)
        if game.board_message_id:
            await runner.safe_edit(bot, game.chat_id, game.board_message_id, "🚫 Партия «Бункер» остановлена.", None)
    await message.answer("🚫 Партия «Бункер» остановлена.")


@router.message(Command("bunker", "bunker123"))
async def cmd_bunker_create(message: types.Message, bot: Bot):
    if message.chat.type == "private":
        return await message.answer("☢️ «Бункер» — групповая игра. "
                                    "Добавьте меня в чат и напишите там /bunker.")

    existing = engine.get_game_by_chat(message.chat.id)
    if existing:
        if existing.phase is Phase.LOBBY:
            await _refresh_lobby(bot, existing)
            return await message.answer("⚠️ Лобби уже открыто (см. сообщение выше).")
        async with existing.lock:
            await runner.post_board(bot, existing)
        return await message.answer("⚠️ Партия уже идёт. Остановить: /bunker_stop")

    host_name = message.from_user.full_name
    game = engine.create_new_game(engine.new_game_id(message.chat.id), message.chat.id,
                                  message.from_user.id, host_name)
    engine.add_player(game, message.from_user.id, host_name, message.from_user.username or "")

    username = await runner.get_bot_username(bot)
    msg = await message.answer(
        ui.format_lobby_text(game),
        reply_markup=ui.get_lobby_keyboard(game, username, is_bot_creator(game.host_id)),
        parse_mode="HTML",
    )
    game.lobby_message_id = msg.message_id


@router.message(Command("bunker_board"))
async def cmd_bunker_board(message: types.Message, bot: Bot):
    game = engine.get_game_by_chat(message.chat.id)
    if not game or game.phase is Phase.LOBBY:
        return await message.answer("❌ Идущей партии нет.")
    async with game.lock:
        await runner.post_board(bot, game)


@router.message(Command("start"), F.chat.type == "private")
async def cmd_start_deeplink(message: types.Message, command: CommandObject, bot: Bot):
    payload = (command.args or "").strip()
    game = engine.get_game(payload) if payload.startswith("b") else None
    game = game or engine.find_player_game(message.from_user.id)
    if game is None:
        raise SkipHandler                    # отдаём /start основному роутеру бота

    player = game.players.get(message.from_user.id)
    if not player:
        return await message.answer("❌ Вас нет в этой партии — нажмите «✅ Вступить» в чате.")
    player.dm_available = True
    player.dm_warned = False

    if game.phase is Phase.LOBBY or not player.cards:
        return await message.answer("✅ <b>ЛС открыто.</b> Как только организатор нажмёт «🚀 НАЧАТЬ», "
                                    "сюда придёт личное дело.", parse_mode="HTML")
    await runner.send_dossier(bot, game, player)
    text, kb = ui.prompt_for(game, player)
    if text:
        await runner.dm(bot, game, player, text, kb, fresh=True)


# ------------------------------ лобби: коллбэки ----------------------------- #
@router.callback_query(BunkerCB.filter(F.action.in_({"join", "leave"})))
async def cb_join_leave(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        if callback_data.action == "join":
            ok, msg = engine.add_player(game, cb.from_user.id, cb.from_user.full_name,
                                        cb.from_user.username or "")
        else:
            ok, msg = engine.remove_player(game, cb.from_user.id)
            if ok and not game.players:
                runner.cancel_timer(game)
                engine.drop_game(game.game_id)
                if game.lobby_message_id:
                    await runner.safe_edit(bot, game.chat_id, game.lobby_message_id,
                                           "🚪 Лобби пусто — игра отменена.", None)
                return await cb.answer("Лобби закрыто.")
        if ok:
            await _refresh_lobby(bot, game)
    await cb.answer(msg if ok else msg, show_alert=not ok)


@router.callback_query(BunkerCB.filter(F.action.in_({"add_bot", "remove_bot"})))
async def cb_bots(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    if not is_bot_creator(cb.from_user.id):
        return await cb.answer("❌ Только Создатель бота.", show_alert=True)
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    async with game.lock:
        ok, msg = (engine.add_test_bot(game) if callback_data.action == "add_bot"
                   else engine.remove_test_bot(game))
        if ok:
            await _refresh_lobby(bot, game)
    await cb.answer(msg, show_alert=not ok)


@router.callback_query(BunkerCB.filter(F.action.in_({"settings", "lobby", "set"})))
async def cb_settings(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    if not can_manage(game, cb.from_user.id):
        return await cb.answer("❌ Настройки меняет организатор.", show_alert=True)

    notice = "⚙️"
    async with game.lock:
        if callback_data.action == "set":
            ok, notice = engine.cycle_setting(game, callback_data.extra)
            if not ok:
                return await cb.answer(notice, show_alert=True)
        if callback_data.action == "lobby":
            await _refresh_lobby(bot, game)
        else:
            await runner.safe_edit(bot, game.chat_id, cb.message.message_id,
                                   ui.format_settings_text(game),
                                   ui.get_settings_keyboard(game))
    await cb.answer(notice)


@router.callback_query(BunkerCB.filter(F.action == "cancel"))
async def cb_cancel(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    if not can_manage(game, cb.from_user.id):
        return await cb.answer("❌ Только организатор.", show_alert=True)
    async with game.lock:
        runner.cancel_timer(game)
        engine.cancel_game(game)
        engine.drop_game(game.game_id)
        if game.lobby_message_id:
            await runner.safe_edit(bot, game.chat_id, game.lobby_message_id,
                                   "🚫 Игра «Бункер» отменена.", None)
    await cb.answer("Отменено.")


@router.callback_query(BunkerCB.filter(F.action == "start"))
async def cb_start(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    if not can_manage(game, cb.from_user.id):
        return await cb.answer("❌ Начать может только организатор.", show_alert=True)

    async with game.lock:
        ok, msg = engine.start_game_engine(game)
        if not ok:
            return await cb.answer(msg, show_alert=True)
        if game.lobby_message_id:
            await runner.safe_edit(bot, game.chat_id, game.lobby_message_id,
                                   "🚀 <b>Партия началась!</b> Табло ниже 👇", None)
        await runner.start_game_flow(bot, game)
    await cb.answer("🚀 Поехали!")


# ------------------------------ игровые коллбэки ---------------------------- #
def _get(cb_data: BunkerCB, user_id: int):
    game = engine.get_game(cb_data.game_id)
    return game, (game.players.get(user_id) if game else None)


async def _open_in_dm(bot: Bot, cb: types.CallbackQuery, game, player,
                      text: str, kb) -> None:
    """Если нажали в ЛС — правим текущее меню, если в чате — шлём в ЛС."""
    if cb.message and cb.message.chat.type == "private":
        player.prompt_message_id = cb.message.message_id
        await runner.dm(bot, game, player, text, kb)
        return await cb.answer()
    if await runner.dm(bot, game, player, text, kb, fresh=True):
        return await cb.answer("📩 Меню отправлено в ЛС!")
    username = await runner.get_bot_username(bot)
    await cb.answer(f"❌ Сначала откройте ЛС: t.me/{username}?start={game.game_id}",
                    show_alert=True)


@router.callback_query(BunkerCB.filter(F.action.in_({"pause", "next_phase"})))
async def cb_control(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    if not can_manage(game, cb.from_user.id):
        return await cb.answer("❌ Управлять игрой может только организатор.", show_alert=True)

    async with game.lock:
        if callback_data.action == "pause":
            ok, msg = engine.toggle_pause(game)
        else:
            ok, msg = engine.force_next_phase(game)
        if ok:
            await runner.render_board(bot, game, force=True)
    await cb.answer(msg, show_alert=not ok)


@router.callback_query(BunkerCB.filter(F.action == "my_cards"))
async def cb_my_cards(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game, player = _get(callback_data, cb.from_user.id)
    if not game or not player:
        return await cb.answer("❌ Вы не в этой партии.", show_alert=True)
    if not player.cards:
        return await cb.answer("⌛ Карты выдаются после старта.", show_alert=True)
    if await runner.send_dossier(bot, game, player):
        return await cb.answer("📩 Личное дело в ЛС!" if cb.message.chat.type != "private" else "🃏")
    username = await runner.get_bot_username(bot)
    await cb.answer(f"❌ Откройте ЛС: t.me/{username}?start={game.game_id}", show_alert=True)


@router.callback_query(BunkerCB.filter(F.action.in_({"reveal_menu", "vote_menu", "prompt"})))
async def cb_prompt(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game, player = _get(callback_data, cb.from_user.id)
    if not game or not player:
        return await cb.answer("❌ Вы не в этой партии.", show_alert=True)
    if not player.alive:
        return await cb.answer("💀 Вы изгнаны — только наблюдаете.", show_alert=True)
    text, kb = ui.prompt_for(game, player)
    if not text:
        return await cb.answer("Сейчас от вас ничего не требуется.", show_alert=True)
    await _open_in_dm(bot, cb, game, player, text, kb)


@router.callback_query(BunkerCB.filter(F.action.in_({"reveal_do", "reveal_none"})))
async def cb_reveal_do(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game, player = _get(callback_data, cb.from_user.id)
    if not game or not player:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        if callback_data.action == "reveal_none":
            ok, private, event = engine.declare_no_reveal(game, cb.from_user.id)
        else:
            ok, private, event = engine.reveal_player_card(game, cb.from_user.id,
                                                           callback_data.extra)
        if not ok:
            return await cb.answer(private, show_alert=True)

        game.push_event(event)                       # в чат — только через табло
        if cb.message and cb.message.chat.type == "private":
            player.prompt_message_id = cb.message.message_id
        text, kb = ui.prompt_for(game, player)
        if text:
            await runner.dm(bot, game, player, text, kb)
        await runner.render_board(bot, game, force=True)
    await cb.answer(private)


@router.callback_query(BunkerCB.filter(F.action == "skip"))
async def cb_skip(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game, _player = _get(callback_data, cb.from_user.id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    async with game.lock:
        ok, msg = engine.register_skip(game, cb.from_user.id)
        if not ok:
            return await cb.answer(msg, show_alert=True)
        await runner.render_board(bot, game, force=True)
    await cb.answer("⏭ " + msg)


@router.callback_query(BunkerCB.filter(F.action == "vote_do"))
async def cb_vote_do(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game, player = _get(callback_data, cb.from_user.id)
    if not game or not player:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    try:
        target_id = int(callback_data.extra)
    except (TypeError, ValueError):
        return await cb.answer("Неверная цель.", show_alert=True)

    async with game.lock:
        ok, private, event = engine.cast_vote(game, cb.from_user.id, target_id)
        if not ok:
            return await cb.answer(private, show_alert=True)
        game.push_event(event)
        if cb.message and cb.message.chat.type == "private":
            player.prompt_message_id = cb.message.message_id
        text, kb = ui.prompt_for(game, player)
        if text:
            await runner.dm(bot, game, player, text, kb)
        await runner.render_board(bot, game, force=True)
    await cb.answer("✅ " + private)


# -------------------------------- спецкарты --------------------------------- #
@router.callback_query(BunkerCB.filter(F.action == "spec"))
async def cb_special_menu(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game, player = _get(callback_data, cb.from_user.id)
    if not game or not player:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    kb = ui.get_special_keyboard(game, player)
    if kb is None:
        return await cb.answer("Спецкарта недоступна.", show_alert=True)
    await _open_in_dm(bot, cb, game, player, ui.format_special_prompt(game, player), kb)


@router.callback_query(BunkerCB.filter(F.action == "spec_go"))
async def cb_special_use(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game, player = _get(callback_data, cb.from_user.id)
    if not game or not player:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        ok, private, event = engine.use_special_card(game, cb.from_user.id, callback_data.extra)
        if not ok:
            return await cb.answer(private, show_alert=True)
        game.push_event(event)
        if cb.message and cb.message.chat.type == "private":
            player.prompt_message_id = cb.message.message_id
        text, kb = ui.prompt_for(game, player)
        await runner.dm(bot, game, player,
                        f"✨ {private}" + (f"\n\n{text}" if text else ""), kb, fresh=True)
        await runner.render_board(bot, game, force=True)
    await cb.answer("✨ Применено")


@router.callback_query(BunkerCB.filter(F.action == "refresh"))
async def cb_refresh(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    async with game.lock:
        await runner.render_board(bot, game, force=True)
        runner.ensure_timer(bot, game)
    await cb.answer("🔄")
