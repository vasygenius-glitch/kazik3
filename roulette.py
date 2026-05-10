import asyncio
import random
import secrets
from aiogram import Router, types
from aiogram.filters import Command

from user_manager import get_user_data, update_user_balance
from chances import get_game_chance
from escape import escape_html
from config import CREATOR_ID
from utils import schedule_delete

router = Router()
secure_random = secrets.SystemRandom()

def get_roulette_frame(ball_pos, status, bet, title, guess):
    # Рисуем "колесо" из эмодзи
    wheel = ["🌑"] * 8
    if ball_pos != -1:
        wheel[ball_pos % 8] = "🌕"
    wheel_str = " ".join(wheel)
    
    return (
        f"🌀 <b>{title}</b> 🌀\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"  {wheel_str}\n"
        f"  [ Число: {status} ]\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Ставка: <b>{bet}</b> на <b>{guess}</b>\n"
        f"✨ <i>Шарик в пути...</i>"
    )

@router.message(Command("roulette"))
async def cmd_roulette(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False): return await message.answer("🚫")

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)
    if 'gonorrhea' in active_diseases: return await message.answer("🦠")

    args = message.text.split()
    if len(args) < 3:
        return await message.answer("Использование: <code>/roulette [ставка] [1-36]</code>")

    try:
        bet, guess = int(args[1]), int(args[2])
        if bet < 100 or not (1 <= guess <= 36): return await message.answer("Неверные параметры.")
    except ValueError: return await message.answer("Нужны числа.")

    if data.get('balance', 0) - bet < -5000: return await message.answer("Лимит!")

    await update_user_balance(chat_id, user_id, -bet)

    from seasons import get_season_string, get_glitch_text
    title = await get_season_string("roulette_start", "ВИХРЬ СУДЬБЫ")

    # Анимация
    msg = await message.answer(get_roulette_frame(-1, "??", bet, title, guess))
    
    for i in range(8):
        await asyncio.sleep(0.35)
        rand_num = random.randint(1, 36)
        try:
            await msg.edit_text(get_roulette_frame(i, rand_num, bet, title, guess))
        except: break

    # Логика
    chance = await get_game_chance('roulette')
    is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)

    if is_creator: result_number = guess
    elif chance != -1:
        if secure_random.randint(1, 100) <= chance:
            diff = secure_random.randint(0, 4)
            result_number = guess + secure_random.choice([-diff, diff])
        else:
            result_number = secure_random.randint(1, 36)
            while abs(result_number - guess) <= 4: result_number = secure_random.randint(1, 36)
    else: result_number = secure_random.randint(1, 36)

    diff = abs(result_number - guess)
    total_win, mult_text = 0, ""

    if diff == 0: total_win, mult_text = bet * 3, "ТОЧНО! x3 🎯"
    elif diff <= 2: total_win, mult_text = int(bet * 1.5), "РЯДОМ! x1.5 ✨"
    elif diff <= 4: total_win, mult_text = int(bet * 1.1), "БЛИЗКО! x1.1 🔹"
    else: mult_text = "МИМО 💨"

    if total_win > 0:
        profit = total_win - bet
        if data.get('is_banker', False): profit = int(profit * 0.5)
        elif data.get('is_vip', False): profit += int(profit * 0.1)

        await update_user_balance(chat_id, user_id, bet + profit)
        res_text = f"✅ <b>ВЫИГРЫШ: +{profit}</b>\n{mult_text}"
    else:
        res_text = f"❌ <b>ПРОИГРЫШ: -{bet}</b>\n{mult_text}"

    final_text = (
        f"🌀 <b>{title}</b> 🌀\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"  🌟 🌟 🌟 🌟 🌟 🌟 🌟 🌟\n"
        f"  [ ВЫПАЛО: <b>{result_number}</b> ]\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{res_text}"
    )
    final_text = await get_glitch_text(final_text)

    try:
        await msg.edit_text(final_text)
    except: pass
    asyncio.create_task(schedule_delete(msg, message))
