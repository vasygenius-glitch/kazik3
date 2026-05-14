import asyncio
import secrets
from aiogram import Router, F, types
from aiogram.filters import Command
from user_manager import get_user_data, update_user_balance
from utils import schedule_delete

router = Router()

@router.message(Command("dice"))
async def cmd_dice(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажите ставку: <code>/dice 100</code>")

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
    await ask_casino_confirmation(message, "dice", bet)

@router.callback_query(F.data.startswith("cas_conf_dice_"))
async def process_dice_confirm(callback: types.CallbackQuery):
    try:
        bet = int(callback.data.split("_")[3])
    except: return
    
    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    data = await get_user_data(chat_id, user_id)
    
    if data.get('balance', 0) - bet < -5000:
        return await callback.answer("Недостаточно средств!", show_alert=True)
        
    await callback.message.delete()
    
    from escape import escape_html
    full_name = escape_html(callback.from_user.full_name)
    
    rand = secrets.SystemRandom()
    player_roll = rand.randint(1, 6)
    bot_roll = rand.randint(1, 6)

    from config import CREATOR_ID
    is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)
    if is_creator:
        player_roll = 6
        bot_roll = 1

    await update_user_balance(chat_id, user_id, -bet)
    
    text = f"🎲 <b>Игра в кости</b>\n\nВы бросили: <b>{player_roll}</b>\nБот бросил: <b>{bot_roll}</b>\n\n"

    if player_roll > bot_roll:
        profit = bet
        is_banker = data.get('is_banker', False)
        vip_bonus_text = ""
        if is_banker:
            profit = int(profit * 0.5)
            vip_bonus_text = f"\n<i>(🏦 Банкирам выплачивается только 50% от прибыли)</i>"

        await update_user_balance(chat_id, user_id, bet + profit)
        text += f"🎉 Вы победили! Выиграно: <b>{profit}</b> сыроежек.{vip_bonus_text}"
    elif player_roll < bot_roll:
        text += f"❌ Вы проиграли <b>{bet}</b> сыроежек."
    else:
        await update_user_balance(chat_id, user_id, bet)
        text += "🤝 Ничья! Ставка возвращена."

    msg = await callback.message.answer(text)
    from utils import schedule_delete
    asyncio.create_task(schedule_delete(msg, callback.message))
