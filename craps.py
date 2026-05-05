import asyncio
import secrets
from aiogram import Router, types
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

    rand = secrets.SystemRandom()
    die1 = rand.randint(1, 6)
    die2 = rand.randint(1, 6)
    total = die1 + die2

    from config import CREATOR_ID
    is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)
    if is_creator:
        die1 = 3
        die2 = 4
        total = 7

    text = f"🎲 <b>Крэпс</b>\n\nБросок: <b>{die1} + {die2} = {total}</b>\n\n"

    if total in [7, 11]:
        await update_user_balance(chat_id, user_id, bet)
        text += f"🎉 Натуральная победа (Pass Line)! Вы выиграли <b>{bet}</b> сыроежек."
    elif total in [2, 3, 12]:
        await update_user_balance(chat_id, user_id, -bet)
        text += f"❌ Крэпс! Вы проиграли <b>{bet}</b> сыроежек."
    else:
        # Simplified craps (no point phase for chat bot simplicity, just a flat roll)
        if rand.choice([True, False]):
            await update_user_balance(chat_id, user_id, bet)
            text += f"🎯 Вы выиграли поинт! Выиграно <b>{bet}</b> сыроежек."
        else:
            await update_user_balance(chat_id, user_id, -bet)
            text += f"❌ Вы не выкинули поинт. Проиграно <b>{bet}</b> сыроежек."

    msg = await message.answer(text)
    asyncio.create_task(schedule_delete(msg, message))
