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
    chat_id, user_id = message.chat.id, message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    from utils import schedule_delete, check_maintenance
    if await check_maintenance() and user_id != CREATOR_ID:
        return await message.answer("🛠 <b>Бот на техническом обслуживании.</b>\nИгровые команды временно отключены.")

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned', False): return await message.answer("🚫")

    from diseases import get_active_diseases
    if 'gonorrhea' in await get_active_diseases(chat_id, user_id):
        return await message.answer("🦠 Крупье брезгует вами.")

    args = message.text.split()
    if len(args) < 2: return await message.answer("Укажите ставку: <code>/slots 100</code>")
    try:
        bet = int(args[1])
        if bet < 10: return await message.answer("Минимальная ставка — 10.")
    except Exception: return await message.answer("Числом!")

    if data.get('balance', 0) - bet < -5000: return await message.answer("Кредит!")
    await update_user_balance(chat_id, user_id, -bet)

    from seasons import get_season_string, get_glitch_text, get_season_config
    cfg = await get_season_config()
    casino_title = await get_season_string("bj_start", "КАЗИНО ЗАКУЛИСЬЕ")
    
    msg = await message.answer(get_slots_frame(["❓", "❓", "❓"], "Подготовка...", bet, casino_title))
    
    # Оптимизированная анимация: 3 шага
    frames = ["▓░░░░", "▓▓▓░░", "▓▓▓▓▓"]
    for status in frames:
        await asyncio.sleep(0.5)
        temp_slots = [secure_random.choice(EMOJIS) for _ in range(3)]
        if random.random() < 0.15:
            glitches = ["ζ", "⧫", "☠", "⌬", "╳"]
            temp_slots[random.randint(0,2)] = secure_random.choice(glitches)
            
        try:
            await msg.edit_text(get_slots_frame(temp_slots, f"Вращение: {status}", bet, casino_title))
        except Exception: break

    chance = await get_game_chance('slots')
    is_forced_win = False
    is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)

    if is_creator: is_forced_win = True
    elif chance != -1 and secure_random.randint(1, 100) <= chance: is_forced_win = True

    if is_forced_win:
        if is_creator: final_slots = ["7️⃣", "7️⃣", "7️⃣"]
        else:
            win_types = ["jackpot", "mega", "three"]
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
        if chance != -1:
            while final_slots[0] == final_slots[1] == final_slots[2]:
                final_slots = [secure_random.choice(EMOJIS) for _ in range(3)]

    profit = 0
    if final_slots[0] == final_slots[1] == final_slots[2]:
        if final_slots[0] == "7️⃣": profit, mult = bet * 20, "JACKPOT x20! 🏆"
        elif final_slots[0] in ["💎", "🔔"]: profit, mult = bet * 10, "MEGA x10! 💎"
        else: profit, mult = bet * 5, "WIN x5! 🍒"
        status = f"🎉 <b>ПОБЕДА!</b>\n  +{profit} сыр. | {mult}"
    elif final_slots[0] == final_slots[1] or final_slots[1] == final_slots[2] or final_slots[0] == final_slots[2]:
        if final_slots[0] == final_slots[1] or final_slots[0] == final_slots[2]: pair = final_slots[0]
        else: pair = final_slots[1]
        if pair == "7️⃣": profit, mult = bet * 2, "PAIRS x2!"
        elif pair in ["💎", "🔔"]: profit, mult = int(bet * 1.5), "PAIRS x1.5!"
        else: profit, mult = int(bet * 0.5), "PAIRS x0.5!"
        
        if profit > 0: status = f"🎉 <b>ПОБЕДА!</b>\n  +{profit} сыр. | {mult}"
        else: status = f"💀 <b>ПРОИГРЫШ</b>\n  -{bet} сыр."
    else:
        status = f"💀 <b>ПРОИГРЫШ</b>\n  -{bet} сыр."

    if profit > 0:
        if data.get('is_banker'): profit = int(profit * 0.5)
        elif data.get('is_vip'): profit += int(profit * 0.1)
        await update_user_balance(chat_id, user_id, bet + profit)

    final_text = get_slots_frame(final_slots, status, bet, casino_title)
    final_text = await get_glitch_text(final_text)

    try:
        await msg.edit_text(final_text)
    except Exception: pass
    asyncio.create_task(schedule_delete(msg, message))
