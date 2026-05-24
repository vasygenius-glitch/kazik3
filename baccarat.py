import asyncio
import secrets
from aiogram import Router, F, types
from aiogram.filters import Command
from user_manager import get_user_data, update_user_balance
from utils import schedule_delete
from cards import get_random_card, get_baccarat_score, format_cards
from chances import get_game_chance

router = Router()

@router.message(Command("baccarat"))
async def cmd_baccarat(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажите ставку: <code>/baccarat 100</code>")

    try:
        bet = int(args[1])
        if bet < 100 or bet > 50000000:
            raise ValueError
    except ValueError:
        return await message.answer("Ставка должна быть числом от 100 до 50,000,000 сыроежек.")

    chat_id = message.chat.id
    user_id = message.from_user.id
    data = await get_user_data(chat_id, user_id)

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)
    if 'gonorrhea' in active_diseases:
        return await message.answer("🦠 <b>Гонорея</b>: Крупье брезгует пускать тебя за стол. Игра запрещена!")

    if data.get('balance', 0) - bet < -5000:
        return await message.answer("Ваш кредитный лимит (-5000) исчерпан. Пополните баланс.")

    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(message, "baccarat", bet)

@router.callback_query(F.data.startswith("cas_conf_baccarat_"))
async def process_baccarat_confirm(callback: types.CallbackQuery):
    try:
        bet = int(callback.data.split("_")[3])
    except: return
    
    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    message_id = callback.message.message_id
    
    from casino_utils import try_acquire_confirm_lock, release_confirm_lock
    if not try_acquire_confirm_lock(chat_id, message_id):
        return await callback.answer("Ваша ставка уже обрабатывается...", show_alert=True)
        
    try:
        data = await get_user_data(chat_id, user_id)
        
        new_balance = await update_user_balance(chat_id, user_id, -bet, min_balance=-5000)
        if new_balance is None:
            return await callback.answer("Недостаточно средств!", show_alert=True)
            
        try:
            await callback.message.delete()
        except Exception:
            pass
        
        secure_random = secrets.SystemRandom()
        from config import CREATOR_ID
        is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)

        chance = await get_game_chance('baccarat')
        target_chance = 35 if chance == -1 else chance
        is_win = (secure_random.randint(1, 100) <= target_chance) or is_creator

        while True:
            p_cards = [get_random_card(), get_random_card()]
            b_cards = [get_random_card(), get_random_card()]

            p_score = get_baccarat_score(p_cards)
            b_score = get_baccarat_score(b_cards)

            # Draw third card logic
            if p_score < 6:
                p_cards.append(get_random_card())
                p_score = get_baccarat_score(p_cards)

            if b_score < 6:
                b_cards.append(get_random_card())
                b_score = get_baccarat_score(b_cards)

            if is_win and p_score > b_score:
                break
            elif not is_win and b_score > p_score:
                break
            elif not is_win and p_score == b_score:
                 break # Tie is also not a player win
        
        text = (
            f"🃏 <b>Баккара</b>\n\n"
            f"Игрок: {format_cards(p_cards)} (<b>{p_score}</b>)\n"
            f"Банкир: {format_cards(b_cards)} (<b>{b_score}</b>)\n\n"
        )

        if p_score > b_score:
            profit = bet
            await update_user_balance(chat_id, user_id, bet + profit, action="Baccarat Win")
            text += f"🎉 Игрок побеждает! Вы выиграли <b>{profit}</b> сыроежек."
        elif b_score > p_score:
            text += f"❌ Банкир побеждает! Вы проиграли <b>{bet}</b> сыроежек."
        else:
            await update_user_balance(chat_id, user_id, bet)
            text += "🤝 Ничья! Ваша ставка возвращена."

        msg = await callback.message.answer(text)
        asyncio.create_task(schedule_delete(msg, callback.message))
    finally:
        release_confirm_lock(chat_id, message_id)
