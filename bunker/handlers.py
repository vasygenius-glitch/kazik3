# bunker/handlers.py
from __future__ import annotations

import logging
import time

from aiogram import Bot, F, Router, types
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


async def _refresh_lobby(bot: Bot, game, viewer_id: int) -> None:
    username = await runner.get_bot_username(bot)
    text = ui.format_lobby_text(game)
    kb = ui.get_lobby_keyboard(game, is_host=(viewer_id == game.host_id),
                               is_creator=is_bot_creator(viewer_id), bot_username=username)
    if game.lobby_message_id:
        await runner.safe_edit(bot, game.chat_id, game.lobby_message_id, text, kb)


def _get_game_or_none(game_id: str):
    return engine.get_game(game_id)


# --------------------------------------------------------------------------- #
#                                команды                                      #
# --------------------------------------------------------------------------- #
@router.message(or_f(Command("bunker", "bunker123", "бункер"),
                     F.text.regexp(r"^[!.]\s*(бункер|bunker)\b")))
async def cmd_bunker_create(message: types.Message, bot: Bot):
    if message.chat.type == "private":
        return await message.answer(
            "☢️ «Бункер» — групповая игра. Добавьте меня в чат и напишите там /bunker."
        )

    existing = engine.get_game_by_chat(message.chat.id)
    if existing:
        if existing.phase is Phase.LOBBY:
            await _refresh_lobby(bot, existing, message.from_user.id)
            return await message.answer("⚠️ В этом чате уже открыто лобби «Бункера».")
        return await message.answer(
            "⚠️ В этом чате уже идёт партия «Бункер».\n"
            "Организатор может завершить её кнопкой «❌ Отменить» или командой /bunker_stop."
        )

    game_id = f"b{abs(message.chat.id) % 1000000}_{int(time.time()) % 100000}"
    host_name = message.from_user.full_name
    game = engine.create_new_game(game_id, message.chat.id, message.from_user.id, host_name)
    engine.add_player(game, message.from_user.id, host_name, message.from_user.username or "")

    username = await runner.get_bot_username(bot)
    msg = await message.answer(
        ui.format_lobby_text(game),
        reply_markup=ui.get_lobby_keyboard(game, True, is_bot_creator(message.from_user.id), username),
        parse_mode="HTML",
    )
    game.lobby_message_id = msg.message_id


@router.message(Command("bunker_stop"))
async def cmd_bunker_stop(message: types.Message, bot: Bot):
    game = engine.get_game_by_chat(message.chat.id)
    if not game:
        return await message.answer("❌ В этом чате нет активной игры.")
    if message.from_user.id != game.host_id and not is_bot_creator(message.from_user.id):
        return await message.answer("❌ Остановить партию может только организатор.")

    async with game.lock:
        runner.cancel_timer(game)
        engine.cancel_game(game)
        engine.drop_game(game.game_id)
    await message.answer("🚫 Партия «Бункер» остановлена.")


@router.message(Command("bunker_bot"))
async def cmd_bunker_add_bot(message: types.Message, bot: Bot):
    if not is_bot_creator(message.from_user.id):
        return await message.answer("❌ Тестовых ботов может добавлять только Создатель.")
    game = engine.get_game_by_chat(message.chat.id)
    if not game:
        return await message.answer("❌ В этом чате нет активного лобби «Бункера».")

    async with game.lock:
        ok, msg = engine.add_test_bot(game)
        await _refresh_lobby(bot, game, message.from_user.id)
    await message.answer(("✅ " if ok else "❌ ") + msg)


@router.message(Command("start"), F.chat.type == "private")
async def cmd_start_deeplink(message: types.Message, command: CommandObject, bot: Bot):
    """Deep-link /start b12345_678 из лобби."""
    payload = (command.args or "").strip()
    game = engine.get_game(payload) if payload.startswith("b") else None
    if game is None:
        game = engine.find_player_game(message.from_user.id)
    if game is None:
        return  # обычный /start обработает основной роутер бота

    player = game.players.get(message.from_user.id)
    if not player:
        return await message.answer(
            "❌ Вы не в этой партии. Нажмите «✅ Вступить» в лобби чата."
        )
    player.dm_available = True

    if game.phase is Phase.LOBBY or not player.cards:
        return await message.answer(
            "✅ <b>ЛС открыто!</b>\nКак только организатор нажмёт «🚀 НАЧАТЬ ИГРУ», "
            "сюда придёт ваше личное дело и меню раскрытия карт.",
            parse_mode="HTML",
        )

    await runner.send_dossier(bot, game, player)


# --------------------------------------------------------------------------- #
#                            лобби: коллбэки                                  #
# --------------------------------------------------------------------------- #
@router.callback_query(BunkerCB.filter(F.action.in_({"join", "leave"})))
async def cb_join_leave(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена или уже завершена.", show_alert=True)

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
                                           "🚪 Все покинули лобби. Игра отменена.")
                return await cb.answer("Лобби закрыто.")
        if ok:
            await _refresh_lobby(bot, game, cb.from_user.id)

    if callback_data.action == "join" and ok:
        username = await runner.get_bot_username(bot)
        await cb.answer(f"{msg} Не забудьте открыть ЛС бота!", show_alert=not True)
        return
    await cb.answer(msg, show_alert=not ok)


@router.callback_query(BunkerCB.filter(F.action.in_({"add_bot", "remove_bot"})))
async def cb_bots(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    if not is_bot_creator(cb.from_user.id):
        return await cb.answer("❌ Только Создатель бота управляет тестовыми ботами.", show_alert=True)
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        if callback_data.action == "add_bot":
            ok, msg = engine.add_test_bot(game)
        else:
            ok, msg = engine.remove_test_bot(game)
        if ok:
            await _refresh_lobby(bot, game, cb.from_user.id)
    await cb.answer(msg, show_alert=not ok)


@router.callback_query(BunkerCB.filter(F.action.in_({"settings", "lobby", "set"})))
async def cb_settings(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    if cb.from_user.id != game.host_id and not is_bot_creator(cb.from_user.id):
        return await cb.answer("❌ Настройки меняет только организатор.", show_alert=True)

    notice = ""
    async with game.lock:
        if callback_data.action == "set":
            ok, notice = engine.cycle_setting(game, callback_data.extra)
            if not ok:
                return await cb.answer(notice, show_alert=True)

        if callback_data.action == "lobby":
            await _refresh_lobby(bot, game, cb.from_user.id)
        else:
            await runner.safe_edit(bot, game.chat_id, cb.message.message_id,
                                   ui.format_settings_text(game),
                                   ui.get_settings_keyboard(game))
    await cb.answer(notice or "⚙️")


@router.callback_query(BunkerCB.filter(F.action == "cancel"))
async def cb_cancel(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    if cb.from_user.id != game.host_id and not is_bot_creator(cb.from_user.id):
        return await cb.answer("❌ Только организатор может отменить игру.", show_alert=True)

    async with game.lock:
        runner.cancel_timer(game)
        engine.cancel_game(game)
        engine.drop_game(game.game_id)
        if game.lobby_message_id:
            await runner.safe_edit(bot, game.chat_id, game.lobby_message_id,
                                   "🚫 Игра «Бункер» отменена организатором.")
    await cb.answer("Игра отменена.")


@router.callback_query(BunkerCB.filter(F.action == "start"))
async def cb_start(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    if cb.from_user.id != game.host_id:
        return await cb.answer("❌ Начать игру может только организатор!", show_alert=True)

    async with game.lock:
        ok, msg = engine.start_game_engine(game)
        if not ok:
            return await cb.answer(msg, show_alert=True)
        if game.lobby_message_id:
            await runner.safe_edit(bot, game.chat_id, game.lobby_message_id,
                                   "🚀 <b>Партия «Бункер» началась!</b> Смотрите табло ниже 👇")
        await runner.start_game_flow(bot, game)
        await runner.sync_locked(bot, game)
    await cb.answer("🚀 Поехали!")


# --------------------------------------------------------------------------- #
#                            игровые коллбэки                                 #
# --------------------------------------------------------------------------- #
@router.callback_query(BunkerCB.filter(F.action == "my_cards"))
async def cb_my_cards(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    player = game.players.get(cb.from_user.id)
    if not player:
        return await cb.answer("Вы не участник этой партии.", show_alert=True)
    if game.phase is Phase.LOBBY or not player.cards:
        return await cb.answer("⌛ Карты выдаются после старта игры.", show_alert=True)

    sent = await runner.send_dossier(bot, game, player)
    if sent:
        return await cb.answer("📩 Личное дело отправлено в ЛС!")
    username = await runner.get_bot_username(bot)
    await cb.answer(f"❌ Откройте ЛС: t.me/{username}?start={game.game_id}", show_alert=True)


@router.callback_query(BunkerCB.filter(F.action == "reveal_menu"))
async def cb_reveal_menu(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    player = game.players.get(cb.from_user.id)
    if not player or not player.alive:
        return await cb.answer("Вы не участвуете в раскрытии.", show_alert=True)
    if game.phase is not Phase.REVEAL:
        return await cb.answer("Сейчас не фаза раскрытия карт.", show_alert=True)

    kb = ui.get_reveal_keyboard(game, cb.from_user.id)
    if kb is None:
        return await cb.answer("Вы уже сделали выбор в этом раунде.", show_alert=True)

    if cb.message and cb.message.chat.type == "private":
        await runner.safe_edit(bot, cb.message.chat.id, cb.message.message_id,
                               ui.format_reveal_prompt(game, player), kb)
        return await cb.answer()

    ok = await runner._dm(bot, game, player, ui.format_reveal_prompt(game, player),
                          kb, replace_prompt=True)
    if ok:
        return await cb.answer("📩 Меню раскрытия отправлено в ЛС!")
    username = await runner.get_bot_username(bot)
    await cb.answer(f"❌ Откройте ЛС: t.me/{username}?start={game.game_id}", show_alert=True)


@router.callback_query(BunkerCB.filter(F.action.in_({"reveal_do", "reveal_none"})))
async def cb_reveal_do(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        if callback_data.action == "reveal_none":
            ok, private, public = engine.declare_no_reveal(game, cb.from_user.id)
        else:
            ok, private, public = engine.reveal_player_card(game, cb.from_user.id,
                                                            callback_data.extra)
        if not ok:
            return await cb.answer(private, show_alert=True)

        if public:
            await runner.safe_send(bot, game.chat_id, public, disable_notification=True)

        player = game.players[cb.from_user.id]
        if cb.message and cb.message.chat.type == "private":
            kb = ui.get_reveal_keyboard(game, cb.from_user.id)
            if kb is None:
                await runner.safe_edit(bot, cb.message.chat.id, cb.message.message_id,
                                       f"✅ {private}\n\n<i>Ждём остальных…</i>")
            else:
                await runner.safe_edit(bot, cb.message.chat.id, cb.message.message_id,
                                       ui.format_reveal_prompt(game, player), kb)
        await runner.sync_locked(bot, game)
    await cb.answer(private)


@router.callback_query(BunkerCB.filter(F.action == "skip"))
async def cb_skip(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        ok, msg, _done = engine.register_skip(game, cb.from_user.id)
        if not ok:
            return await cb.answer(msg, show_alert=True)
        await runner.sync_locked(bot, game)
    await cb.answer(msg)


@router.callback_query(BunkerCB.filter(F.action == "vote_menu"))
async def cb_vote_menu(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    player = game.players.get(cb.from_user.id)
    if not player or not player.alive:
        return await cb.answer("Вы не голосуете в этом раунде.", show_alert=True)
    if not game.phase.is_voting:
        return await cb.answer("Сейчас не фаза голосования.", show_alert=True)

    kb = ui.get_vote_keyboard(game, cb.from_user.id)
    if kb is None:
        return await cb.answer("Вы уже проголосовали.", show_alert=True)

    if cb.message and cb.message.chat.type == "private":
        await runner.safe_edit(bot, cb.message.chat.id, cb.message.message_id,
                               ui.format_vote_prompt(game), kb)
        return await cb.answer()

    ok = await runner._dm(bot, game, player, ui.format_vote_prompt(game), kb, replace_prompt=True)
    if ok:
        return await cb.answer("📩 Бюллетень отправлен в ЛС!")
    username = await runner.get_bot_username(bot)
    await cb.answer(f"❌ Откройте ЛС: t.me/{username}?start={game.game_id}", show_alert=True)


@router.callback_query(BunkerCB.filter(F.action == "vote_do"))
async def cb_vote_do(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    try:
        target_id = int(callback_data.extra)
    except (TypeError, ValueError):
        return await cb.answer("Неверная цель голосования.", show_alert=True)

    async with game.lock:
        ok, private, public = engine.cast_vote(game, cb.from_user.id, target_id)
        if not ok:
            return await cb.answer(private, show_alert=True)
        if public:
            await runner.safe_send(bot, game.chat_id, public, disable_notification=True)
        if cb.message and cb.message.chat.type == "private":
            await runner.safe_edit(bot, cb.message.chat.id, cb.message.message_id,
                                   f"✅ {private}\n\n<i>Ждём остальных…</i>")
        await runner.sync_locked(bot, game)
    await cb.answer(private)


@router.callback_query(BunkerCB.filter(F.action == "refresh"))
async def cb_refresh(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = _get_game_or_none(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)
    async with game.lock:
        await runner.sync_locked(bot, game)
        runner.ensure_timer(bot, game)
    await cb.answer("🔄 Обновлено")
