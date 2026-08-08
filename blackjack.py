import asyncio
import secrets
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from user_manager import get_user_data, update_user_balance, set_in_cache, mark_dirty
from cards import get_random_card, calculate_score, format_cards
from escape import escape_html
from config import CREATOR_ID
from utils import schedule_delete
from chances import get_user_win_chance
from game_ai import train_on_move, predict_move, register_outcome
import logging

logger = logging.getLogger(__name__)

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
        # Автоматический сброс залипшей игры
        await state.clear()
        # return await message.answer("Завершите прошлую игру!")

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
    
    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(message, "blackjack", bet)

@router.callback_query(F.data.startswith("cas_conf_blackjack_"))
async def process_bj_confirm(callback: types.CallbackQuery, state: FSMContext):
    try:
        bet = int(callback.data.split("_")[3])
    except: return
    
    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    message_id = callback.message.message_id
    
    from casino_utils import try_acquire_confirm_lock, release_confirm_lock
    if not try_acquire_confirm_lock(chat_id, message_id):
        return await callback.answer("Ваша ставка уже обрабатывается...", show_alert=True)
        
    try:
        full_name = escape_html(callback.from_user.full_name)
        data = await get_user_data(chat_id, user_id, full_name)
        
        new_balance = await update_user_balance(chat_id, user_id, -bet, min_balance=-5000)
        if new_balance is None:
            return await callback.answer("Недостаточно средств!", show_alert=True)
    
        try:
            await callback.message.delete()
        except Exception:
            pass
    
        game_id = f"{chat_id}_{user_id}_{callback.message.message_id}"
        player_cards = [get_random_card(), get_random_card()]
        dealer_cards = [get_random_card(), get_random_card()]
    
        if CREATOR_ID and int(user_id) == int(CREATOR_ID):
            player_cards = [{'rank': 'A', 'suit': '♠'}, {'rank': 'K', 'suit': '♠'}]
    
        p_score = calculate_score(player_cards)
        d_score = calculate_score(dealer_cards)
    
        from seasons import get_season_string
        title = await get_season_string("bj_start", "БЛЭКДЖЕК: LEVEL 0")
    
        if p_score == 21:
            profit = int(bet * 1.5)
            if data.get('is_vip'): profit += int(profit * 0.1)
            await update_user_balance(chat_id, user_id, bet + profit, action="Blackjack Win")
            try:
                data['ai_memory'] = register_outcome(data.get('ai_memory'), -1, "blackjack")
                set_in_cache(chat_id, user_id, data)
                mark_dirty(chat_id, user_id)
            except Exception as e:
                logger.warning(f"Error registering outcome on natural blackjack: {e}")
            text = get_bj_frame(player_cards, dealer_cards, 21, d_score, "🎊 <b>БЛЭКДЖЕК!</b>", full_name, bet, title, False)
            msg = await callback.message.answer(text)
            asyncio.create_task(schedule_delete(msg, callback.message))
            return
    
        await state.set_state(BlackjackState.playing)
        await state.update_data(game_id=game_id, user_id=user_id, chat_id=chat_id, full_name=full_name, bet=bet, player_cards=player_cards, dealer_cards=dealer_cards, title=title)
    
        text = get_bj_frame(player_cards, dealer_cards, p_score, d_score, "Ваш ход...", full_name, bet, title)
        await callback.message.answer(text, reply_markup=get_bj_keyboard(game_id))
        asyncio.create_task(schedule_delete(callback.message))
    finally:
        release_confirm_lock(chat_id, message_id)

@router.callback_query(F.data.startswith("bj_hit_"))
async def process_bj_hit(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != BlackjackState.playing.state: return await callback.answer()
    game = await state.get_data()
    if game.get('processing'): return await callback.answer()
    if callback.from_user.id != game['user_id']: return await callback.answer()

    # Train AI on player choosing hit ('h')
    try:
        chat_id, user_id = game['chat_id'], game['user_id']
        data = await get_user_data(chat_id, user_id)
        data['ai_memory'] = train_on_move(data.get('ai_memory'), 'h', 'blackjack')
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)
    except Exception as e:
        logger.warning(f"Error training AI on hit: {e}")

    game['player_cards'].append(get_random_card())
    p_score = calculate_score(game['player_cards'])
    
    if p_score > 21:
        secure_random = secrets.SystemRandom()
        is_creator = CREATOR_ID and int(game['user_id']) == int(CREATOR_ID)
        if is_creator or secure_random.randint(1, 100) <= 5:
             game['player_cards'].pop()
             game['player_cards'].append({'rank': '2', 'suit': '♣'})
             p_score = calculate_score(game['player_cards'])

    if p_score > 21:
        await state.clear()
        
        # Register outcome: AI (dealer) wins (+1) because player busted
        try:
            chat_id, user_id = game['chat_id'], game['user_id']
            data = await get_user_data(chat_id, user_id)
            data['ai_memory'] = register_outcome(data.get('ai_memory'), 1, "blackjack")
            set_in_cache(chat_id, user_id, data)
            mark_dirty(chat_id, user_id)
        except Exception as e:
            logger.warning(f"Error registering outcome on bust: {e}")

        text = get_bj_frame(game['player_cards'], game['dealer_cards'], p_score, 0, f"💀 <b>ПЕРЕБОР! -{game['bet']}</b>", game['full_name'], game['bet'], game['title'], False)
        await callback.message.edit_text(text)
    elif p_score == 21:
        await state.update_data(processing=True)
        await finish_dealer_turn(callback, game, state)
    else:
        await state.update_data(player_cards=game['player_cards'])
        text = get_bj_frame(game['player_cards'], game['dealer_cards'], p_score, 0, "Еще карту?", game['full_name'], game['bet'], game['title'])
        await callback.message.edit_text(text, reply_markup=get_bj_keyboard(game['game_id']))
    await callback.answer()

@router.callback_query(F.data.startswith("bj_stand_"))
async def process_bj_stand(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != BlackjackState.playing.state: return await callback.answer()
    game = await state.get_data()
    if game.get('processing'): return await callback.answer()
    if callback.from_user.id != game['user_id']: return await callback.answer()
    
    await state.update_data(processing=True)
    
    # Train AI on player choosing stand ('s')
    try:
        chat_id, user_id = game['chat_id'], game['user_id']
        data = await get_user_data(chat_id, user_id)
        data['ai_memory'] = train_on_move(data.get('ai_memory'), 's', 'blackjack')
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)
    except Exception as e:
        logger.warning(f"Error training AI on stand: {e}")

    await finish_dealer_turn(callback, game, state)
    await callback.answer()

async def finish_dealer_turn(callback: types.CallbackQuery, game: dict, state: FSMContext):
    import secrets
    from seasons import get_glitch_text
    p_score = calculate_score(game['player_cards'])
    dealer_cards = game['dealer_cards']
    
    is_creator = CREATOR_ID and int(game['user_id']) == int(CREATOR_ID)
    secure_random = secrets.SystemRandom()

    chat_id = game['chat_id']
    user_id = game['user_id']
    data = await get_user_data(chat_id, user_id)

    # Get target win chance
    target_chance = await get_user_win_chance(chat_id, user_id, 'blackjack', 35)
    
    # AI adaptation: if player is predictable, decrease player win chance
    try:
        pred = predict_move(data.get('ai_memory'), 'blackjack')
        confidence = pred.get('confidence', 0.0)
        profile = pred.get('profile', 'unknown')
        
        # Decrease target chance by up to 15% based on AI confidence
        adjustment = int(confidence * 15)
        target_chance = max(10, target_chance - adjustment)
        
        ai_info = f"\n🤖 <b>ИИ-Дилер:</b> стиль {profile.capitalize()} | уверенность {int(confidence * 100)}%"
    except Exception as e:
        logger.warning(f"Error predicting AI in BJ: {e}")
        confidence = 0.0
        profile = 'unknown'
        ai_info = ""

    if is_creator:
        target_win = True
    else:
        target_win = secure_random.randint(1, 100) <= target_chance

    # Pre-calculate the outcome using a while loop to match the target_win condition
    # Keep only the first (face-up) card and reroll the rest
    max_retries = 100
    retries = 0
    while True:
        temp_dealer_cards = [dealer_cards[0], get_random_card()]
        while calculate_score(temp_dealer_cards) <= 16:
            temp_dealer_cards.append(get_random_card())

        d_score = calculate_score(temp_dealer_cards)
        player_wins = d_score > 21 or p_score > d_score

        # In a tie, we'll keep rerolling since we want a strict win/loss, or accept it if target_win is False
        if target_win and player_wins:
            dealer_cards = temp_dealer_cards
            break
        elif not target_win and not player_wins:
            dealer_cards = temp_dealer_cards
            break

        retries += 1
        if retries > max_retries:
             # Fallback just to avoid freezing the event loop if odds are very weird
             dealer_cards = temp_dealer_cards
             break

    # Animate the pre-calculated sequence
    drawn_cards_count = len(game['dealer_cards'])
    for i in range(drawn_cards_count, len(dealer_cards) + 1):
        current_dealer_cards = dealer_cards[:i]
        d_score = calculate_score(current_dealer_cards)
        text = get_bj_frame(game['player_cards'], current_dealer_cards, p_score, d_score, "Дилер берет карту...", game['full_name'], game['bet'], game['title'], False)
        try:
            await callback.message.edit_text(text)
            if i < len(dealer_cards):
                await asyncio.sleep(0.7) # Снизил до 0.7 для скорости
        except Exception: break

    d_score = calculate_score(dealer_cards)
    bet = game['bet']

    if d_score > 21 or p_score > d_score:
        profit = bet
        if data.get('is_vip'): profit += int(profit * 0.1)
        await update_user_balance(game['chat_id'], game['user_id'], bet + profit, action="Blackjack Win")
        res = f"✅ <b>ПОБЕДА! +{profit}</b>"
        ai_outcome = -1  # AI (dealer) lost
    elif p_score < d_score:
        res = f"❌ <b>ПРОИГРЫШ! -{bet}</b>"
        ai_outcome = 1  # AI (dealer) won
    else:
        await update_user_balance(game['chat_id'], game['user_id'], bet)
        res = "🤝 <b>НИЧЬЯ!</b>"
        ai_outcome = 0

    # Register blackjack outcome in AI memory
    try:
        data = await get_user_data(chat_id, user_id)
        data['ai_memory'] = register_outcome(data.get('ai_memory'), ai_outcome, "blackjack")
        set_in_cache(chat_id, user_id, data)
        mark_dirty(chat_id, user_id)
    except Exception as e:
        logger.warning(f"Error registering outcome in BJ: {e}")

    # Add AI analysis info to the result
    if ai_info:
        res += ai_info

    text = get_bj_frame(game['player_cards'], dealer_cards, p_score, d_score, res, game['full_name'], bet, game['title'], False)
    try:
        await callback.message.edit_text(await get_glitch_text(text))
    except Exception: pass
    await state.clear()
    asyncio.create_task(schedule_delete(callback.message))
