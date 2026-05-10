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

EMOJIS = ["🍒", "🍋", "🍉", "🍇", "🔔", "💎", "7️⃣"]

def get_slots_frame(slots, status_text, bet, title):
    return (
        f"🏆 <b>{title}</b> 🏆\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"  [ {slots[0]} | {slots[1]} | {slots[2]} ]\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ставка: <b>{bet}</b>\n"
        f"✨ {status_text}"
    )

@router.message(Command("slots"))
async def cmd_slots(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False):
        return await message.answer("🚫 Вы забанены.")

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)
    if 'gonorrhea' in active_diseases:
        return await message.answer("🦠 <b>Гонорея</b>: Крупье брезгует пускать тебя за стол.")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажите ставку: <code>/slots 100</code>")

    try:
        bet = int(args[1])
        if bet < 10: return await message.answer("Минимальная ставка — 10 сыроежек.")
    except ValueError: return await message.answer("Ставка должна быть числом.")

    if data.get('balance', 0) - bet < -5000:
        return await message.answer("Кредитный лимит исчерпан.")

    await update_user_balance(chat_id, user_id, -bet)

    from seasons import get_season_string, get_glitch_text
    casino_title = await get_season_string("bj_start", "КАЗИНО ЗАКУЛИСЬЕ")
    
    # Анимация 1: Запуск
    msg = await message.answer(get_slots_frame(["❓", "❓", "❓"], "Подготовка барабанов...", bet, casino_title))
    
    # Анимация 2: Вращение с прогресс-баром
    frames = ["░░░░░", "▓░░░░", "▓▓░░░", "▓▓▓░░", "▓▓▓▓░", "▓▓▓▓▓"]
    for i in range(len(frames)):
        await asyncio.sleep(0.4)
        temp_slots = [secure_random.choice(EMOJIS) for _ in range(3)]
        if i % 2 == 0: # Глитчим через раз
            temp_slots = [await get_glitch_text(s) if random.random() < 0.3 else s for s in temp_slots]
        
        status = f"Вращение: {frames[i]}"
        try:
            await msg.edit_text(get_slots_frame(temp_slots, status, bet, casino_title))
        except: break

    # Логика результата
    chance = await get_game_chance('slots')
    is_forced_win = False
    is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)

    if is_creator: is_forced_win = True
    elif chance != -1 and secure_random.randint(1, 100) <= chance: is_forced_win = True

    if is_forced_win:
        if is_creator: final_slots = ["7️⃣", "7️⃣", "7️⃣"]
        else:
            win_types = ["jackpot", "mega", "three", "pair_mega", "pair_7"]
            chosen_win = secure_random.choice(win_types)
            if chosen_win == "jackpot": final_slots = ["7️⃣", "7️⃣", "7️⃣"]
            elif chosen_win == "mega":
                sym = secure_random.choice(["💎", "🔔"])
                final_slots = [sym, sym, sym]
            else:
                sym = secure_random.choice(["🍒", "🍋", "🍉", "🍇"])
                final_slots = [sym, sym, sym]
    else:
        final_slots = [secure_random.choice(EMOJIS) for _ in range(3)]
        if chance != -1: # Гарантируем проигрыш
            while final_slots[0] == final_slots[1] or final_slots[1] == final_slots[2] or final_slots[0] == final_slots[2]:
                final_slots = [secure_random.choice(["🍒", "🍋"]), secure_random.choice(["🍉", "🍇"]), secure_random.choice(["💎", "🔔"])]

    profit = 0
    multiplier_text = ""

    if final_slots[0] == final_slots[1] == final_slots[2]:
        if final_slots[0] == "7️⃣": profit, multiplier_text = bet * 20, "JACKPOT x20! 🏆🏆🏆"
        elif final_slots[0] in ["💎", "🔔"]: profit, multiplier_text = bet * 10, "MEGA WIN x10! 💎💎"
        else: profit, multiplier_text = bet * 5, "WIN x5! 🍇"
    elif final_slots[0] == final_slots[1] or final_slots[1] == final_slots[2] or final_slots[0] == final_slots[2]:
        if final_slots[0] == final_slots[1] or final_slots[0] == final_slots[2]: pair_emoji = final_slots[0]
        else: pair_emoji = final_slots[1]
        if pair_emoji == "7️⃣": profit, multiplier_text = bet * 2, "PAIRS x2! 7️⃣"
        elif pair_emoji in ["💎", "🔔"]: profit, multiplier_text = int(bet * 1.5), "PAIRS x1.5! 🔔"

    if profit > 0:
        is_banker = data.get('is_banker', False)
        if is_banker: profit = int(profit * 0.5)
        elif data.get('is_vip', False): profit += int(profit * 0.1)

        await update_user_balance(chat_id, user_id, bet + profit)
        status = f"🎉 <b>ПОБЕДА!</b>\n  +{profit} сыр. | {multiplier_text}"
    else:
        status = f"💀 <b>ПРОИГРЫШ</b>\n  -{bet} сыр. Попробуй еще раз!"

    final_text = get_slots_frame(final_slots, status, bet, casino_title)
    final_text = await get_glitch_text(final_text)

    try:
        await msg.edit_text(final_text)
    except: pass
    asyncio.create_task(schedule_delete(msg, message))