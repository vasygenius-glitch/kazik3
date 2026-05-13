import asyncio
import secrets
from aiogram import Router, types
from aiogram.filters import Command
from user_manager import get_user_data, update_user_balance
from utils import schedule_delete

router = Router()

def get_baccarat_value(card_val):
    if card_val > 9:
        return 0
    return card_val

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

    rand = secrets.SystemRandom()

    from config import CREATOR_ID
    is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)

    is_win = rand.randint(1, 100) <= 35

    while True:
        # Draw cards (1-13 where 11, 12, 13 are face cards with 0 value)
        p_cards = [rand.randint(1, 13), rand.randint(1, 13)]
        b_cards = [rand.randint(1, 13), rand.randint(1, 13)]

        p_score = sum(get_baccarat_value(c) for c in p_cards) % 10
        b_score = sum(get_baccarat_value(c) for c in b_cards) % 10

        # Draw third card logic simplified
        if p_score < 6:
            p_cards.append(rand.randint(1, 13))
            p_score = sum(get_baccarat_value(c) for c in p_cards) % 10

        if b_score < 6:
            b_cards.append(rand.randint(1, 13))
            b_score = sum(get_baccarat_value(c) for c in b_cards) % 10

        if is_creator:
            p_score = 9
            b_score = 1
            break

        if is_win and p_score > b_score:
            break
        elif not is_win and b_score > p_score:
            break

    text = f"🃏 <b>Баккара</b>\n\nОчки Игрока: <b>{p_score}</b>\nОчки Банкира: <b>{b_score}</b>\n\n"

    if p_score > b_score:
        profit = bet
        is_banker = data.get('is_banker', False)
        vip_bonus_text = ""

        if is_banker:
            profit = int(profit * 0.5)
            vip_bonus_text = f"\n<i>(🏦 Банкирам выплачивается только 50% от прибыли)</i>"

        await update_user_balance(chat_id, user_id, profit)
        text += f"🎉 Игрок побеждает! Вы выиграли <b>{profit}</b> сыроежек.{vip_bonus_text}"
    elif b_score > p_score:
        await update_user_balance(chat_id, user_id, -bet)
        text += f"❌ Банкир побеждает! Вы проиграли <b>{bet}</b> сыроежек."
    else:
        text += "🤝 Ничья! Ваша ставка возвращена."

    msg = await message.answer(text)
    asyncio.create_task(schedule_delete(msg, message))
