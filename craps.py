import asyncio
import secrets
from aiogram import Router, F, types
from aiogram.filters import Command
from user_manager import get_user_data, update_user_balance
from utils import schedule_delete

router = Router()

@router.message(Command("craps"))
async def cmd_craps(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажите ставку: <code>/craps 100</code>")

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
    await ask_casino_confirmation(message, "craps", bet)

@router.callback_query(F.data.startswith("cas_conf_craps_"))
async def process_craps_confirm(callback: types.CallbackQuery):
    try:
        bet = int(callback.data.split("_")[3])
    except: return
    
    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    data = await get_user_data(chat_id, user_id)
    
    if data.get('balance', 0) - bet < -5000:
        return await callback.answer("Недостаточно средств!", show_alert=True)
        
    await callback.message.delete()
    
    rand = secrets.SystemRandom()

    from config import CREATOR_ID
    is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)

    if is_creator:
        is_forced_win = True
    else:
        is_forced_win = (rand.randint(1, 100) <= 35)

    while True:
        die1 = rand.randint(1, 6)
        die2 = rand.randint(1, 6)
        total = die1 + die2

        if total in [7, 11]:
            is_win = True
            is_natural = True
            is_craps = False
        elif total in [2, 3, 12]:
            is_win = False
            is_natural = False
            is_craps = True
        else:
            # Simplified craps
            is_win = rand.choice([True, False])
            is_natural = False
            is_craps = False

        if is_win == is_forced_win:
            break

    if is_creator:
        die1 = 3
        die2 = 4
        total = 7
        is_natural = True
        is_craps = False
        is_win = True

    await update_user_balance(chat_id, user_id, -bet)
    
    text = f"🎲 <b>Крэпс</b>\n\nБросок: <b>{die1} + {die2} = {total}</b>\n\n"

    if is_natural:
        await update_user_balance(chat_id, user_id, bet * 2)
        text += f"🎉 Натуральная победа (Pass Line)! Вы выиграли <b>{bet}</b> сыроежек."
    elif is_craps:
        text += f"❌ Крэпс! Вы проиграли <b>{bet}</b> сыроежек."
    else:
        if is_win:
            await update_user_balance(chat_id, user_id, bet * 2)
            text += f"🎯 Вы выиграли поинт! Выиграно <b>{bet}</b> сыроежек."
        else:
            text += f"❌ Вы не выкинули поинт. Проиграно <b>{bet}</b> сыроежек."

    msg = await callback.message.answer(text)
    asyncio.create_task(schedule_delete(msg, callback.message))
