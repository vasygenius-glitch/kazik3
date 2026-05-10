import asyncio
import random
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from user_manager import get_user_data, update_user_balance
from cards import get_random_card, calculate_score, format_cards
from escape import escape_html
from config import CREATOR_ID
from utils import schedule_delete

router = Router()

class BlackjackState(StatesGroup):
    playing = State()

def get_bj_keyboard(game_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Взять", callback_data=f"bj_hit_{game_id}")
    builder.button(text="✋ Хватит", callback_data=f"bj_stand_{game_id}")
    builder.adjust(2)
    return builder.as_markup()

def get_bj_frame(player_cards, dealer_cards, p_score, d_score, status, user_name, bet, title, hide_dealer=True):
    d_cards_str = format_cards(dealer_cards)
    if hide_dealer:
        d_cards_str = f"{dealer_cards[0]['rank']}{dealer_cards[0]['suit']} 🂠 (?)"
        d_score_str = "?"
    else:
        d_score_str = str(d_score)

    return (
        f"🃏 <b>{title}</b> 🃏\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤵 <b>Дилер:</b> {d_cards_str} (<b>{d_score_str}</b>)\n"
        f"👤 <b>{user_name}:</b> {format_cards(player_cards)} (<b>{p_score}</b>)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ставка: <b>{bet}</b>\n"
        f"✨ {status}"
    )

@router.message(Command("bj"))
async def cmd_bj(message: types.Message, state: FSMContext):
    if await state.get_state() == BlackjackState.playing.state:
        return await message.answer("Завершите прошлую игру!")

    chat_id, user_id = message.chat.id, message.from_user.id
    full_name = escape_html(message.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get('is_banned'): return
    from diseases import get_active_diseases
    if 'gonorrhea' in await get_active_diseases(chat_id, user_id): return

    args = message.text.split()
    if len(args) < 2: return await message.answer("Ставка?")
    try:
        bet = int(args[1])
        if bet < 100: return await message.answer("От 100.")
    except Exception: return

    if data.get('balance', 0) - bet < -5000: return await message.answer("Кредит!")
    await update_user_balance(chat_id, user_id, -bet)

    game_id = f"{chat_id}_{user_id}_{message.message_id}"
    player_cards = [get_random_card(), get_random_card()]
    dealer_cards = [get_random_card()]
    
    if CREATOR_ID and int(user_id) == int(CREATOR_ID):
        player_cards = [{'rank': 'A', 'suit': '♠'}, {'rank': 'K', 'suit': '♠'}]

    p_score = calculate_score(player_cards)
    d_score = calculate_score(dealer_cards)

    from seasons import get_season_string
    title = await get_season_string("bj_start", "БЛЭКДЖЕК: LEVEL 0")

    if p_score == 21:
        profit = int(bet * 1.5)
        if data.get('is_banker'): profit = int(profit * 0.5)
        elif data.get('is_vip'): profit += int(profit * 0.1)
        await update_user_balance(chat_id, user_id, bet + profit)
        text = get_bj_frame(player_cards, dealer_cards, 21, d_score, "🎊 <b>БЛЭКДЖЕК!</b>", full_name, bet, title, False)
        msg = await message.answer(text)
        asyncio.create_task(schedule_delete(msg, message))
        return

    await state.set_state(BlackjackState.playing)
    await state.update_data(user_id=user_id, chat_id=chat_id, full_name=full_name, bet=bet, player_cards=player_cards, dealer_cards=dealer_cards, title=title)

    text = get_bj_frame(player_cards, dealer_cards, p_score, d_score, "Ваш ход...", full_name, bet, title)
    await message.answer(text, reply_markup=get_bj_keyboard(game_id))
    asyncio.create_task(schedule_delete(message))

@router.callback_query(F.data.startswith("bj_hit_"))
async def process_bj_hit(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != BlackjackState.playing.state: return await callback.answer()
    game = await state.get_data()
    if callback.from_user.id != game['user_id']: return await callback.answer()

    game['player_cards'].append(get_random_card())
    p_score = calculate_score(game['player_cards'])
    
    if p_score > 21:
        is_creator = CREATOR_ID and int(game['user_id']) == int(CREATOR_ID)
        if is_creator or random.randint(1, 100) <= 5:
             game['player_cards'].pop()
             game['player_cards'].append({'rank': '2', 'suit': '♣'})
             p_score = calculate_score(game['player_cards'])

    if p_score > 21:
        await state.clear()
        text = get_bj_frame(game['player_cards'], game['dealer_cards'], p_score, 0, f"💀 <b>ПЕРЕБОР! -{game['bet']}</b>", game['full_name'], game['bet'], game['title'], False)
        await callback.message.edit_text(text)
    elif p_score == 21:
        await finish_dealer_turn(callback, game)
    else:
        await state.update_data(player_cards=game['player_cards'])
        text = get_bj_frame(game['player_cards'], game['dealer_cards'], p_score, 0, "Еще карту?", game['full_name'], game['bet'], game['title'])
        await callback.message.edit_text(text, reply_markup=get_bj_keyboard(""))
    await callback.answer()

@router.callback_query(F.data.startswith("bj_stand_"))
async def process_bj_stand(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != BlackjackState.playing.state: return await callback.answer()
    game = await state.get_data()
    if callback.from_user.id != game['user_id']: return await callback.answer()
    await state.clear()
    await finish_dealer_turn(callback, game)
    await callback.answer()

async def finish_dealer_turn(callback: types.CallbackQuery, game: dict):
    from seasons import get_glitch_text
    p_score = calculate_score(game['player_cards'])
    dealer_cards = game['dealer_cards']
    
    while calculate_score(dealer_cards) <= 16:
        dealer_cards.append(get_random_card())
        d_score = calculate_score(dealer_cards)
        text = get_bj_frame(game['player_cards'], dealer_cards, p_score, d_score, "Дилер берет карту...", game['full_name'], game['bet'], game['title'], False)
        try:
            await callback.message.edit_text(text)
            await asyncio.sleep(0.7) # Снизил до 0.7 для скорости
        except Exception: break

    d_score = calculate_score(dealer_cards)
    bet = game['bet']
    data = await get_user_data(game['chat_id'], game['user_id'])

    if d_score > 21 or p_score > d_score:
        profit = bet
        if data.get('is_banker'): profit = int(profit * 0.5)
        elif data.get('is_vip'): profit += int(profit * 0.1)
        await update_user_balance(game['chat_id'], game['user_id'], bet + profit)
        res = f"✅ <b>ПОБЕДА! +{profit}</b>"
    elif p_score < d_score:
        res = f"❌ <b>ПРОИГРЫШ! -{bet}</b>"
    else:
        await update_user_balance(game['chat_id'], game['user_id'], bet)
        res = "🤝 <b>НИЧЬЯ!</b>"

    text = get_bj_frame(game['player_cards'], dealer_cards, p_score, d_score, res, game['full_name'], bet, game['title'], False)
    try:
        await callback.message.edit_text(await get_glitch_text(text))
    except Exception: pass
    asyncio.create_task(schedule_delete(callback.message))
