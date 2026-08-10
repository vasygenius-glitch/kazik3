# bunker/handlers.py
import asyncio
from aiogram import Router, types, F, Bot
from aiogram.filters import Command, or_f
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from bunker.models import Game, Player, Phase
from bunker.engine import (
    create_new_game, get_game, get_game_by_chat, start_game_engine,
    reveal_player_card, cast_vote, check_voting_complete, process_voting_results,
    kick_player_from_game, calculate_epilogue
)
from bunker.ui import (
    BunkerCB, format_lobby_text, get_lobby_keyboard,
    format_stage_text, get_stage_keyboard
)
from bunker.cards_img import render_player_dossier_png

router = Router()

@router.message(Command("start"), F.text.contains("bnk_"))
async def cmd_start_bunker_deep_link(message: types.Message, bot: Bot):
    """Обработка deep-link в ЛС бота: /start bnk_<game_id>"""
    args = message.text.split("bnk_")
    if len(args) < 2:
        return
        
    game_id = args[1].strip()
    game = get_game(game_id)
    if not game:
        return await message.answer("❌ Игра не найдена или уже завершена.")
        
    player = game.players.get(message.from_user.id)
    if not player:
        return await message.answer("❌ Вы не являетесь участником этой игры.")

    # Отправляем карточку игроку в ЛС
    png_buf = render_player_dossier_png(player, game.scenario)
    photo_file = BufferedInputFile(png_buf.getvalue(), filename=f"dossier_{player.user_id}.png")

    builder = InlineKeyboardBuilder()
    builder.button(text="🔓 Раскрыть карту", callback_data=BunkerCB(action="reveal_menu", game_id=game_id).pack())
    builder.adjust(1)

    await message.answer_photo(
        photo=photo_file,
        caption=(
            f"☢️ <b>ТВОЕ ЛИЧНОЕ ДЕЛО</b>\n"
            f"Катастрофа: <b>{game.scenario.title}</b>\n"
            f"Бункер: <b>{game.scenario.bunker_name}</b>\n\n"
            f"Используй кнопку ниже, чтобы выбрать карту для раскрытия в чате!"
        ),
        reply_markup=builder.as_markup()
    )

@router.message(or_f(Command("bunker123"), Command("bunker"), F.text.regexp(r"^[!/]+(bunker123|bunker|бункер)(\s|$)")))
async def cmd_bunker_create(message: types.Message, bot: Bot):
    """Создание игры Бункер в чате."""
    chat_id = message.chat.id
    existing_game = get_game_by_chat(chat_id)
    if existing_game:
        return await message.answer(
            f"⚠️ В этом чате уже запущена подготовка или игра «Бункер»!\n"
            f"Завершите текущую партию или используйте существующее лобби."
        )

    game_id = f"bnk_{chat_id}_{int(message.date.timestamp())}"
    host_name = message.from_user.full_name
    game = create_new_game(game_id, chat_id, message.from_user.id, host_name)
    
    # Автоматически добавляем создателя в лобби
    game.players[message.from_user.id] = Player(
        user_id=message.from_user.id,
        name=host_name,
        username=message.from_user.username or "",
        seat=1
    )

    text = format_lobby_text(game)
    kb = get_lobby_keyboard(game_id, is_host=True)
    
    msg = await message.answer(text, reply_markup=kb)
    game.stage_message_id = msg.message_id

@router.callback_query(BunkerCB.filter(F.action == "join"))
async def cb_join(cb: types.CallbackQuery, callback_data: BunkerCB):
    game = get_game(callback_data.game_id)
    if not game or game.phase != Phase.LOBBY:
        return await cb.answer("❌ Игра не доступна для входа.", show_alert=True)

    uid = cb.from_user.id
    if uid in game.players:
        return await cb.answer("Вы уже в лобби!", show_alert=True)

    game.players[uid] = Player(
        user_id=uid,
        name=cb.from_user.full_name,
        username=cb.from_user.username or "",
        seat=len(game.players) + 1
    )

    is_host = (uid == game.host_id)
    text = format_lobby_text(game)
    kb = get_lobby_keyboard(game.game_id, is_host=is_host)
    
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass

    await cb.answer("✅ Вы успешно вошли в лобби игры!")

@router.callback_query(BunkerCB.filter(F.action == "leave"))
async def cb_leave(cb: types.CallbackQuery, callback_data: BunkerCB):
    game = get_game(callback_data.game_id)
    if not game or game.phase != Phase.LOBBY:
        return await cb.answer("❌ Нельзя покинуть игру сейчас.", show_alert=True)

    uid = cb.from_user.id
    if uid not in game.players:
        return await cb.answer("Вы не состоите в лобби.", show_alert=True)

    del game.players[uid]

    is_host = (cb.from_user.id == game.host_id)
    text = format_lobby_text(game)
    kb = get_lobby_keyboard(game.game_id, is_host=is_host)

    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass

    await cb.answer("Вы покинули лобби.")

@router.callback_query(BunkerCB.filter(F.action == "start"))
async def cb_start(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = get_game(callback_data.game_id)
    if not game or game.phase != Phase.LOBBY:
        return await cb.answer("❌ Игра уже запущена.", show_alert=True)

    if cb.from_user.id != game.host_id:
        return await cb.answer("❌ Только организатор может начать игру!", show_alert=True)

    if len(game.players) < 2:
        return await cb.answer("❌ Для старта нужно минимум 2 игрока!", show_alert=True)

    success = start_game_engine(game)
    if not success:
        return await cb.answer("❌ Ошибка при старте игры.", show_alert=True)

    bot_info = await bot.get_me()
    
    # Рассылка тайных карт в ЛС каждому игроку
    for p in game.players.values():
        try:
            png_buf = render_player_dossier_png(p, game.scenario)
            photo_file = BufferedInputFile(png_buf.getvalue(), filename=f"dossier_{p.user_id}.png")

            builder = InlineKeyboardBuilder()
            builder.button(text="🔓 Раскрыть карту", callback_data=BunkerCB(action="reveal_menu", game_id=game.game_id).pack())

            await bot.send_photo(
                chat_id=p.user_id,
                photo=photo_file,
                caption=(
                    f"☢️ <b>ТВОЕ ЛИЧНОЕ ДЕЛО ВЫЖИВАЮЩЕГО</b>\n"
                    f"Катастрофа: <b>{game.scenario.title}</b>\n"
                    f"Бункер: <b>{game.scenario.bunker_name}</b> ({game.scenario.bunker_size})\n\n"
                    f"Никому не показывай закрытые характеристики раньше времени!"
                ),
                reply_markup=builder.as_markup()
            )
        except Exception:
            # Пользователь не начал диалог с ботом
            pass

    game.phase = Phase.REVEAL
    text = format_stage_text(game, bot_info.username)
    kb = get_stage_keyboard(game, bot_info.username)
    
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer("🚀 Игра «Бункер» началась! Картам присвоены грифы секретности.")

@router.callback_query(BunkerCB.filter(F.action == "my_cards"))
async def cb_my_cards(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = get_game(callback_data.game_id)
    if not game:
        return await cb.answer("❌ Игра не найдена.", show_alert=True)

    p = game.players.get(cb.from_user.id)
    if not p:
        return await cb.answer("Вы не являетесь участником данной игры.", show_alert=True)

    bot_info = await bot.get_me()
    try:
        png_buf = render_player_dossier_png(p, game.scenario or Game.scenario)
        photo_file = BufferedInputFile(png_buf.getvalue(), filename=f"dossier_{p.user_id}.png")
        await bot.send_photo(
            chat_id=cb.from_user.id,
            photo=photo_file,
            caption="🃏 Ваша личная карточка выживающего."
        )
        await cb.answer("Карточка отправлена вам в ЛС! 📩")
    except Exception:
        await cb.answer(
            f"❌ Не удалось отправить карточку в ЛС! Сначала нажмите /start в боте: t.me/{bot_info.username}?start=bnk_{game.game_id}",
            show_alert=True
        )

@router.callback_query(BunkerCB.filter(F.action == "reveal_menu"))
async def cb_reveal_menu(cb: types.CallbackQuery, callback_data: BunkerCB):
    game = get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    p = game.players.get(cb.from_user.id)
    if not p or not p.alive:
        return await cb.answer("Вы не можете раскрывать карты.", show_alert=True)

    builder = InlineKeyboardBuilder()
    for cat_id, card in p.cards.items():
        if not card.revealed:
            builder.button(
                text=f"{card.icon} {card.category_name}",
                callback_data=BunkerCB(action="reveal_do", game_id=game.game_id, extra=cat_id).pack()
            )
            
    builder.adjust(2)
    if not builder.export():
        return await cb.answer("У вас все карты уже раскрыты!", show_alert=True)

    await cb.message.answer("Выберите карту для публичного раскрытия в чате:", reply_markup=builder.as_markup())
    await cb.answer()

@router.callback_query(BunkerCB.filter(F.action == "reveal_do"))
async def cb_reveal_do(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    cat_id = callback_data.extra
    success, msg = reveal_player_card(game, cb.from_user.id, cat_id)
    if not success:
        return await cb.answer(msg, show_alert=True)

    bot_info = await bot.get_me()
    text = format_stage_text(game, bot_info.username)
    kb = get_stage_keyboard(game, bot_info.username)

    # Обновляем сцену в чате
    try:
        await bot.edit_message_text(chat_id=game.chat_id, message_id=game.stage_message_id, text=text, reply_markup=kb)
    except Exception:
        pass

    await cb.answer(msg, show_alert=True)

@router.callback_query(BunkerCB.filter(F.action == "skip"))
async def cb_skip(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = get_game(callback_data.game_id)
    if not game or game.phase != Phase.DISCUSSION:
        return await cb.answer("Сейчас не фаза обсуждения.", show_alert=True)

    p = game.players.get(cb.from_user.id)
    if not p or not p.alive:
        return await cb.answer("Вы не участвуете в игре.", show_alert=True)

    p.has_skipped = True
    skips_count = sum(1 for pl in game.players.values() if pl.alive and pl.has_skipped)
    alive_count = sum(1 for pl in game.players.values() if pl.alive)

    bot_info = await bot.get_me()
    
    if skips_count >= alive_count:
        # Все пропустили — переходим к голосованию
        game.phase = Phase.VOTING
        game.votes.clear()
        game.logs.append("⏳ Игроки единогласно пропустили обсуждение! Переход к голосованию.")

    text = format_stage_text(game, bot_info.username)
    kb = get_stage_keyboard(game, bot_info.username)
    
    try:
        await bot.edit_message_text(chat_id=game.chat_id, message_id=game.stage_message_id, text=text, reply_markup=kb)
    except Exception:
        pass

    await cb.answer("Вы проголосовали за пропуск обсуждения.")

@router.callback_query(BunkerCB.filter(F.action == "vote_menu"))
async def cb_vote_menu(cb: types.CallbackQuery, callback_data: BunkerCB):
    game = get_game(callback_data.game_id)
    if not game or game.phase not in [Phase.VOTING, Phase.TIEBREAK]:
        return await cb.answer("Голосование сейчас недоступно.", show_alert=True)

    voter = game.players.get(cb.from_user.id)
    if not voter or not voter.alive:
        return await cb.answer("Вы не можете голосовать.", show_alert=True)

    builder = InlineKeyboardBuilder()
    for p in game.players.values():
        if p.alive and p.user_id != cb.from_user.id:
            builder.button(
                text=f"❌ Изгнать {p.name}",
                callback_data=BunkerCB(action="vote_do", game_id=game.game_id, extra=str(p.user_id)).pack()
            )
            
    builder.adjust(1)
    await cb.message.answer("🗳 <b>Голосование:</b> выберите кандидата на изгнание из бункера:", reply_markup=builder.as_markup())
    await cb.answer()

@router.callback_query(BunkerCB.filter(F.action == "vote_do"))
async def cb_vote_do(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    target_id = int(callback_data.extra)
    success, msg = cast_vote(game, cb.from_user.id, target_id)
    if not success:
        return await cb.answer(msg, show_alert=True)

    bot_info = await bot.get_me()

    # Если проголосовали все
    if check_voting_complete(game):
        kicked_id, is_tie = process_voting_results(game)
        if is_tie:
            game.phase = Phase.TIEBREAK
            game.votes.clear()
            game.logs.append("⚖️ Ничья при голосовании! Запущено повторное переголосование.")
        else:
            kick_msg = kick_player_from_game(game, kicked_id)
            
            # Проверка условий завершения (осталось выживших == вместимости бункера)
            alive_count = sum(1 for p in game.players.values() if p.alive)
            if alive_count <= game.capacity:
                game.phase = Phase.EPILOGUE
                epilogue_text = calculate_epilogue(game)
                game.logs.append("📖 Игра завершена! Состав бункера сформирован.")
                
                # Публикуем эпилог в чат
                await bot.send_message(chat_id=game.chat_id, text=epilogue_text)
            else:
                game.current_round += 1
                game.phase = Phase.REVEAL
                game.votes.clear()
                for p in game.players.values():
                    p.has_skipped = False
                    p.voted_for = None

    text = format_stage_text(game, bot_info.username)
    kb = get_stage_keyboard(game, bot_info.username)
    
    try:
        await bot.edit_message_text(chat_id=game.chat_id, message_id=game.stage_message_id, text=text, reply_markup=kb)
    except Exception:
        pass

    await cb.answer(msg, show_alert=True)

@router.callback_query(BunkerCB.filter(F.action == "refresh"))
async def cb_refresh(cb: types.CallbackQuery, callback_data: BunkerCB, bot: Bot):
    game = get_game(callback_data.game_id)
    if not game:
        return await cb.answer("Игра не найдена.", show_alert=True)

    bot_info = await bot.get_me()
    text = format_stage_text(game, bot_info.username)
    kb = get_stage_keyboard(game, bot_info.username)
    
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass

    await cb.answer("Сцена обновлена 🔄")
