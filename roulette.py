import asyncio
import secrets
from aiogram import Router, F, types
from aiogram.filters import Command

from user_manager import get_user_data, update_user_balance
from chances import get_game_chance
from escape import escape_html
from config import CREATOR_ID
from utils import schedule_delete

router = Router()
secure_random = secrets.SystemRandom()

def get_roulette_frame(ball_pos, status, bet, title, guess):
    wheel = ["🌑"] * 8
    if ball_pos != -1: wheel[ball_pos % 8] = "🌕"
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
    chat_id, user_id = message.chat.id, message.from_user.id
    full_name = escape_html(message.from_user.full_name)

    data = await get_user_data(chat_id, user_id, full_name)
    if data.get('is_banned'): return await message.answer("🚫")

    from diseases import get_active_diseases
    if 'gonorrhea' in await get_active_diseases(chat_id, user_id): return await message.answer("🦠")

    args = message.text.split()
    if len(args) < 3: return await message.answer("Использование: <code>/roulette [ставка] [1-36]</code>")

    try:
        bet, guess = int(args[1]), int(args[2])
        if bet < 100 or not (1 <= guess <= 36): return await message.answer("Ошибка параметров.")
    except Exception: return await message.answer("Нужны числа.")

    if data.get('balance', 0) - bet < -5000: return await message.answer("Лимит!")
    
    from casino_utils import ask_casino_confirmation
    await ask_casino_confirmation(message, "roulette", bet, guess=guess)

@router.callback_query(F.data.startswith("cas_conf_roulette_"))
async def process_roulette_confirm(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    try:
        bet = int(parts[3])
        guess = int(parts[4])
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
    
        from seasons import get_season_string, get_glitch_text
        title = await get_season_string("roulette_start", "ВИХРЬ СУДЬБЫ")
    
        msg = await callback.message.answer(get_roulette_frame(-1, "??", bet, title, guess))
        
        # Оптимизированная анимация: 4 шага вместо 8
        for i in range(4):
            await asyncio.sleep(0.5)
            try:
                await msg.edit_text(get_roulette_frame(i * 2, secure_random.randint(1,36), bet, title, guess))
            except Exception: break
    
        chance = await get_game_chance('roulette')
        is_creator = CREATOR_ID and int(user_id) == int(CREATOR_ID)
    
        if is_creator: result_number = guess
        elif chance != -1:
            if secure_random.randint(1, 100) <= chance:
                result_number = guess + secure_random.choice([-1, 0, 1])
                result_number = max(1, min(36, result_number))
            else:
                result_number = secure_random.randint(1, 36)
                # Избегаем бесконечного цикла: максимум 50 попыток
                attempts = 0
                while abs(result_number - guess) <= 4 and attempts < 50:
                    result_number = secure_random.randint(1, 36)
                    attempts += 1
        else: result_number = secure_random.randint(1, 36)
    
        diff = abs(result_number - guess)
        total_win, mult_text = 0, ""
    
        if diff == 0: total_win, mult_text = bet * 3, "ТОЧНО! x3 🎯"
        elif diff <= 2: total_win, mult_text = int(bet * 1.5), "РЯДОМ! x1.5 ✨"
        elif diff <= 4: total_win, mult_text = int(bet * 1.1), "БЛИЗКО! x1.1 🔹"
        else: mult_text = "МИМО 💨"
    
        if total_win > 0:
            profit = total_win - bet
            if data.get('is_banker'): profit = int(profit * 0.5)
            elif data.get('is_vip'): profit += int(profit * 0.1)
            await update_user_balance(chat_id, user_id, bet + profit, action="Roulette Win")
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
        except Exception: pass
        asyncio.create_task(schedule_delete(msg, callback.message))
    finally:
        release_confirm_lock(chat_id, message_id)
