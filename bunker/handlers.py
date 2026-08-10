# bunker/handlers.py
from __future__ import annotations

import asyncio
import time
from aiogram import Router, types, F, Bot
from aiogram.filters import Command, or_f
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from config import CREATOR_ID, CREATOR_IDS
from bunker import engine
from bunker.models import Game, Player, Phase, escape_html
from bunker import ui
from bunker.ui import BunkerCB
from bunker.cards_img import render_player_dossier_png

router = Router()


def is_bot_creator(user_id: int) -> bool:
    """Проверяет, является ли пользователь Создателем бота."""
    try:
        uid = int(user_id)
        return uid in CREATOR_IDS or (CREATOR_ID and uid == int(CREATOR_ID))
    except Exception:
        return False


async def safe_edit_text(bot: Bot, chat_id: int, message_id: int, text: str, reply_markup=None):
    """Безопасное редактирование сообщения с перехватом TelegramBadRequest."""
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            raise e
    except Exception:
        pass


async def process_and_update_bots(game: Game, bot: Bot):
    """Выполняет авто-ходы за всех тестовых ботов и продвигает фазы игры."""
    engine.process_bot_actions(game)

    # Проверка фазы REVEAL
    if game.phase is Phase.REVEAL and engine.check_reveal_complete(game):
        engine.set_phase(game, Phase.DISCUSSION)
        game.log("⏳ Все участники раскрыли карты! Началась фаза обсуждения.")
        engine.process_bot_actions(game)

    # Проверка фазы DISCUSSION
    if game.phase is Phase.DISCUSSION:
        alive = game.alive_players()
        if all(p.has_skipped for p in alive):
            engine.set_phase(game, Phase.VOTING)
            game.votes.clear()
            game.log("🗳 Обсуждение завершено досрочно! Переход к голосованию.")
            engine.process_bot_actions(game)

    # Проверка фазы VOTING
    if game.phase.is_voting and engine.check_voting_complete(game):
        kicked_id, is_tie = engine.process_voting_results(game)
        if is_tie:
            engine.set_phase(game, Phase.TIEBREAK)
            game.votes.clear()
            game.log("⚖️ Ничья при голосовании! Запущено повторное переголосование среди лидирующих.")
            engine.process_bot_actions(game)
            if engine.check_voting_complete(game):
                kicked_id_2, _ = engine.process_voting_results(game)
                if kicked_id_2:
                    engine.kick_player_from_game(game, kicked_id_2)
                cont = engine.advance_round(game)
                if not cont:
                    epilogue_text = engine.calculate_epilogue(game)
                    engine.finish_game(game)
                    await bot.send_message(chat_id=game.chat_id, text=epilogue_text, parse_mode="HTML")
                else:
                    engine.process_bot_actions(game)
        else:
            if kicked_id:
                engine.kick_player_from_game(game, kicked_id)

            cont = engine.advance_round(game)
            if not cont:
                epilogue_text = engine.calculate_epilogue(game)
                engine.finish_game(game)
                await bot.send_message(chat_id=game.chat_id, text=epilogue_text, parse_mode="HTML")
            else:
                engine.process_bot_actions(game)


@router.message(Command("start"), F.text.regexp(r"^/start\s+b"))
async def cmd_start_bunker_deep_link(message: types.Message, bot: Bot):
    """Обработка deep-link в ЛС бота: /start <game_id>"""
    parts = message.text.split()
    if len(parts) < 2:
        return

    game_id = parts[1].strip()
    game = engine.get_game(game_id)
    if not game:
        return await message.answer("❌ Игра не найдена или уже завершена.")

    player = game.players.get(message.from_user.id)
    if not player:
        return await message.answer("❌ Вы не являетесь участником этой игры.")

    if game.phase is Phase.LOBBY or not game.scenario or not player.cards:
        return await message.answer(
            f"⌛ <b>Вы успешно перешли в ЛС бота!</b>\n"
            f"Сейчас идет подготовка к игре. Как только организатор нажмет «НАЧАТЬ ИГРУ», вам сюда придут ваши секретные карты!"
        )

    png_buf = render_player_dossier_png(player, game.scenario)
    photo_file = BufferedInputFile(png_buf.getvalue(), filename=f"dossier_{player.user_id}.png")

    builder = InlineKeyboardBuilder()
    if game.phase is Phase.REVEAL:
        builder.button(text="🔓 Раскрыть карту", callback_data=BunkerCB(action="reveal_menu", game_id=game_id).pack())

    await message.answer_photo(
        photo=photo_file,
        caption=(
            f"☢️ <b>ТВОЕ ЛИЧНОЕ ДЕЛО</b>\n"
            f"Катастрофа: <b>{escape_html(game.scenario.title)}</b>\n"
            f"Бункер: <b>{escape_html(game.scenario.bunker_name)}</b>\n\n"
            f"Используй кнопки в чате для действий!"
        ),
        reply_markup=builder.as_markup() if builder.export() else None,
        parse_mode="HTML"
    )


@router.message(or_f(Command("bunker123"), Command("bunker"), F.text.regexp(r"^[!/]+(bunker123|bunker|бункер)(\s|$)")))
async def cmd_bunker_create(message: types.Message, bot: Bot):
    """Создание игры Бункер в чате."""
    chat_id = message.chat.id
    existing_game = engine.get_game_by_chat(chat_id)
    if existing_game and existing_game.phase is not Phase.FINISHED:
        return await message.answer(
            "⚠️ В этом чате уже запущена подготовка или игра «Бункер»!\n"
            "Завершите текущую партию или используйте существующее лобби."
        )

    short_cid = abs(chat_id) % 1000000
    short_time = int(time.time()) % 100000
    game_id = f"b{short_cid}_{short_time}"

    host_name = message.from_user.full_name
    game = engine.create_new_game(game_id, chat_id, message.from_user.id, host_name)
    engine.add_player(game, message.from_user.id, host_name, message.from_user.username or "")

    bot_info = await bot.get_me()
    text = ui.format_lobby_text(game)
    kb = ui.get_lobby_keyboard(game_id, is_host=True, is_creator=is_bot_creator(message.from_user.id), bot_username=bot_info.username or "")

    msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    game.stage_message_id = msg.message_id


@router.message(Command("bunker_bot"))
async def cmd_bunker_add_bot(message: types.Message, bot: Bot):
    """Быстрое добавление тестового бота через команду /bunker_bot."""
    if not is_bot_creator(message.from_user.id):
        return await message.answer("❌ Функция добавления тестовых ботов доступна только Создателю бота.")

    game = engine.get_game_by_chat(message.chat.id)
    if not game:
        return await message.answer("❌ В этом чате нет активного лобби Бункера.")

    async with game.lock:
        ok, msg = engine.add_test_bot(game)
        if not ok:
            return await message.answer(f"❌ {msg}")

        bot_info = await bot.get_me()
        is_host = (message.from_user.id == game.host_id)
        text = ui.format_lobby_text(game)
        kb = ui.get_lobby_keyboard(game.game_id, is_host=is_host, is_creator=is_bot_creator(message.from_user.id), bot_username=bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)


@router.callback_query(BunkerCB.filter(F.action == "join"))
async def cb_join(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        ok, msg = engine.add_player(game, cb.from_user.id, cb.from_user.full_name, cb.from_user.username or "")
        if not ok:
            return await cb.answer(msg, show_alert=True)

        bot_info = await bot.get_me()
        is_host = (cb.from_user.id == game.host_id)
        text = ui.format_lobby_text(game)
        kb = ui.get_lobby_keyboard(game.game_id, is_host=is_host, is_creator=is_bot_creator(cb.from_user.id), bot_username=bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)

    await cb.answer(msg)


@router.callback_query(BunkerCB.filter(F.action == "leave"))
async def cb_leave(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        ok, msg = engine.remove_player(game, cb.from_user.id)
        if not ok:
            return await cb.answer(msg, show_alert=True)

        if not game.players:
            engine.drop_game(game.game_id)
            if game.stage_message_id:
                try:
                    await bot.edit_message_text(
                        chat_id=game.chat_id,
                        message_id=game.stage_message_id,
                        text="🚪 Все игроки покинули лобби. Игра отменена."
                    )
                except Exception:
                    pass
            return await cb.answer("Вы покинули лобби. Лобби закрыто.")

        bot_info = await bot.get_me()
        is_host = (cb.from_user.id == game.host_id)
        text = ui.format_lobby_text(game)
        kb = ui.get_lobby_keyboard(game.game_id, is_host=is_host, is_creator=is_bot_creator(cb.from_user.id), bot_username=bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)

    await cb.answer(msg)


@router.callback_query(BunkerCB.filter(F.action == "add_bot"))
async def cb_add_bot(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    if not is_bot_creator(cb.from_user.id):
        return await cb.answer("❌ Управлять тестовыми ботами может только Создатель бота!", show_alert=True)

    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        ok, msg = engine.add_test_bot(game)
        if not ok:
            return await cb.answer(msg, show_alert=True)

        bot_info = await bot.get_me()
        is_host = (cb.from_user.id == game.host_id)
        text = ui.format_lobby_text(game)
        kb = ui.get_lobby_keyboard(game.game_id, is_host=is_host, is_creator=is_bot_creator(cb.from_user.id), bot_username=bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)

    await cb.answer(msg)


@router.callback_query(BunkerCB.filter(F.action == "remove_bot"))
async def cb_remove_bot(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    if not is_bot_creator(cb.from_user.id):
        return await cb.answer("❌ Управлять тестовыми ботами может только Создатель бота!", show_alert=True)

    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    async with game.lock:
        ok, msg = engine.remove_test_bot(game)
        if not ok:
            return await cb.answer(msg, show_alert=True)

        bot_info = await bot.get_me()
        is_host = (cb.from_user.id == game.host_id)
        text = ui.format_lobby_text(game)
        kb = ui.get_lobby_keyboard(game.game_id, is_host=is_host, is_creator=is_bot_creator(cb.from_user.id), bot_username=bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)

    await cb.answer(msg)


@router.callback_query(BunkerCB.filter(F.action == "start"))
async def cb_start(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    if cb.from_user.id != game.host_id:
        return await cb.answer("❌ Только организатор может начать игру!", show_alert=True)

    async with game.lock:
        ok, msg = engine.start_game_engine(game)
        if not ok:
            return await cb.answer(msg, show_alert=True)

        bot_info = await bot.get_me()

        # Рассылка карт живым игрокам
        for p in game.players.values():
            if p.is_bot:
                continue
            try:
                png_buf = render_player_dossier_png(p, game.scenario)
                photo_file = BufferedInputFile(png_buf.getvalue(), filename=f"dossier_{p.user_id}.png")
                await bot.send_photo(
                    chat_id=p.user_id,
                    photo=photo_file,
                    caption=(
                        f"☢️ <b>ТВОЕ ЛИЧНОЕ ДЕЛО ВЫЖИВАЮЩЕГО</b>\n"
                        f"Катастрофа: <b>{escape_html(game.scenario.title)}</b>\n"
                        f"Бункер: <b>{escape_html(game.scenario.bunker_name)}</b> ({escape_html(game.scenario.bunker_size)})\n\n"
                        f"Секретные карты выданы! Никому их не показывай до фазы раскрытия."
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # Выполняем действия ботов при старте (например раскрытие карт в 1 фазе)
        await process_and_update_bots(game, bot)

        text = ui.format_stage_text(game, bot_info.username or "")
        kb = ui.get_stage_keyboard(game, bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)

    await cb.answer("🚀 Игра «Бункер» началась!")


@router.callback_query(BunkerCB.filter(F.action == "my_cards"))
async def cb_my_cards(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    p = game.players.get(cb.from_user.id)
    if not p:
        return await cb.answer("Вы не являетесь участником данной игры. Нажмите «Вступить»!", show_alert=True)

    if game.phase is Phase.LOBBY or not game.scenario or not p.cards:
        return await cb.answer(
            "⌛ Игра еще не началась! Ваши секретные карты будут выданы после нажатия «НАЧАТЬ ИГРУ».",
            show_alert=True
        )

    bot_info = await bot.get_me()
    try:
        png_buf = render_player_dossier_png(p, game.scenario)
        photo_file = BufferedInputFile(png_buf.getvalue(), filename=f"dossier_{p.user_id}.png")
        await bot.send_photo(
            chat_id=cb.from_user.id,
            photo=photo_file,
            caption="🃏 Ваша личная карточка выживающего.",
            parse_mode="HTML"
        )
        await cb.answer("Карточка отправлена вам в ЛС! 📩")
    except Exception:
        username = bot_info.username or ""
        await cb.answer(
            f"❌ Сначала нажмите /start в боте: t.me/{username}?start={game.game_id}",
            show_alert=True
        )


@router.callback_query(BunkerCB.filter(F.action == "reveal_menu"))
async def cb_reveal_menu(cb: types.CallbackQuery, callback_data: BunkerCB):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    kb = ui.get_reveal_keyboard(game, cb.from_user.id)
    if not kb:
        return await cb.answer("У вас нет доступных карт для раскрытия.", show_alert=True)

    await cb.message.answer("Выберите карту для публичного раскрытия:", reply_markup=kb)
    await cb.answer()


@router.callback_query(BunkerCB.filter(F.action == "reveal_do"))
async def cb_reveal_do(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    async with game.lock:
        ok, msg = engine.reveal_player_card(game, cb.from_user.id, callback_data.extra)
        if not ok:
            return await cb.answer(msg, show_alert=True)

        await process_and_update_bots(game, bot)

        bot_info = await bot.get_me()
        text = ui.format_stage_text(game, bot_info.username or "")
        kb = ui.get_stage_keyboard(game, bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)

    try:
        await cb.message.delete()
    except Exception:
        pass

    await cb.answer(msg)


@router.callback_query(BunkerCB.filter(F.action == "skip"))
async def cb_skip(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    async with game.lock:
        ok, msg, all_done = engine.register_skip(game, cb.from_user.id)
        if not ok:
            return await cb.answer(msg, show_alert=True)

        await process_and_update_bots(game, bot)

        bot_info = await bot.get_me()
        text = ui.format_stage_text(game, bot_info.username or "")
        kb = ui.get_stage_keyboard(game, bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)

    await cb.answer(msg)


@router.callback_query(BunkerCB.filter(F.action == "vote_menu"))
async def cb_vote_menu(cb: types.CallbackQuery, callback_data: BunkerCB):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    targets = engine.allowed_targets(game, cb.from_user.id)
    kb = ui.get_vote_keyboard(game, cb.from_user.id, targets)
    if not kb:
        return await cb.answer("Вы не можете голосовать сейчас.", show_alert=True)

    await cb.message.answer("🗳 <b>Голосование:</b> выберите кандидата на изгнание из бункера:", reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(BunkerCB.filter(F.action == "vote_do"))
async def cb_vote_do(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    try:
        target_id = int(callback_data.extra)
    except ValueError:
        return await cb.answer("Неверная цель голосования.", show_alert=True)

    async with game.lock:
        ok, msg = engine.cast_vote(game, cb.from_user.id, target_id)
        if not ok:
            return await cb.answer(msg, show_alert=True)

        await process_and_update_bots(game, bot)

        bot_info = await bot.get_me()
        text = ui.format_stage_text(game, bot_info.username or "")
        kb = ui.get_stage_keyboard(game, bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)

    try:
        await cb.message.delete()
    except Exception:
        pass

    await cb.answer(msg)


@router.callback_query(BunkerCB.filter(F.action == "refresh"))
async def cb_refresh(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = engine.get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    async with game.lock:
        await process_and_update_bots(game, bot)
        bot_info = await bot.get_me()
        text = ui.format_stage_text(game, bot_info.username or "")
        kb = ui.get_stage_keyboard(game, bot_info.username or "")

    if game.stage_message_id:
        await safe_edit_text(bot, game.chat_id, game.stage_message_id, text, reply_markup=kb)

    await cb.answer("Сцена обновлена 🔄")
