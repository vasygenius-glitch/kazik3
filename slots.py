import asyncio
import random
import secrets
from aiogram import Router, F, types
from aiogram.filters import Command

from user_manager import get_user_data, update_user_balance

from escape import escape_html
from config import CREATOR_ID
from utils import schedule_delete
from chances import get_user_win_chance

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
    
    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(message, "slots", bet)

@router.callback_query(F.data.startswith("cas_conf_slots_"))
async def process_slots_confirm(callback: types.CallbackQuery):
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
        
        from seasons import get_season_string
        casino_title = await get_season_string("bj_start", "КАЗИНО ЗАКУЛИСЬЕ")
        
        msg = await callback.message.answer(get_slots_frame(["❓", "❓", "❓"], "Подготовка...", bet, casino_title))
        
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
    
        target_chance = await get_user_win_chance(chat_id, user_id, 'slots', 35)
        is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)
        is_forced_win = False
        if is_creator:
            is_forced_win = True
        elif secure_random.randint(1, 100) <= target_chance:
            is_forced_win = True
    
        if is_forced_win:
            if is_creator or secure_random.randint(1, 100) <= 15:
                # 3-of-a-kind
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
                # Pair
                while True:
                    final_slots = [secure_random.choice(EMOJIS) for _ in range(3)]
                    # Check if it's a pair but NOT a 3-of-a-kind
                    if (final_slots[0] == final_slots[1] or final_slots[1] == final_slots[2] or final_slots[0] == final_slots[2]) and not (final_slots[0] == final_slots[1] == final_slots[2]):
                        break
        else:
            # Complete loss
            while True:
                final_slots = [secure_random.choice(EMOJIS) for _ in range(3)]
                if not (final_slots[0] == final_slots[1] or final_slots[1] == final_slots[2] or final_slots[0] == final_slots[2]):
                    break
    
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
            if data.get('is_vip'): profit += int(profit * 0.1)
            await update_user_balance(chat_id, user_id, bet + profit, action="Slots Win")
    
        final_text = get_slots_frame(final_slots, status, bet, casino_title)
        from seasons import get_glitch_text
        final_text = await get_glitch_text(final_text)
    
        try:
            await msg.edit_text(final_text)
        except Exception: pass
        asyncio.create_task(schedule_delete(msg, callback.message))
    finally:
        release_confirm_lock(chat_id, message_id)
