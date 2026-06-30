import asyncio
import secrets
from aiogram import Router, F, types
from aiogram.filters import Command
from user_manager import get_user_data, update_user_balance
from utils import schedule_delete
from chances import get_user_win_chance

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
    
        target_chance = await get_user_win_chance(chat_id, user_id, 'craps', 35)
        if is_creator:
            is_forced_win = True
        else:
            is_forced_win = (secure_random.randint(1, 100) <= target_chance)
    
        while True:
            die1 = secure_random.randint(1, 6)
            die2 = secure_random.randint(1, 6)
            point = die1 + die2
            
            is_natural = point in (7, 11)
            is_craps = point in (2, 3, 12)
            
            if is_forced_win and not is_craps:
                break
            elif not is_forced_win and not is_natural:
                break
                
        dice_emoji = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣"}
        text = (
            f"🎲 <b>Крэпс (кости)</b>\n\n"
            f"Бросок: {dice_emoji[die1]} + {dice_emoji[die2]} = <b>{point}</b>\n\n"
        )
    
        is_win = False
        if not is_natural and not is_craps:
            # Point phase simulation
            target_point = point
            text += f"Установлен Point: <b>{target_point}</b>\n"
            
            attempts = []
            while True:
                r1 = secure_random.randint(1, 6)
                r2 = secure_random.randint(1, 6)
                sum_r = r1 + r2
                attempts.append(f"{dice_emoji[r1]} + {dice_emoji[r2]} = {sum_r}")
                
                if sum_r == target_point:
                    is_win = True
                    break
                if sum_r == 7:
                    is_win = False
                    break
                    
                if len(attempts) > 10:
                    is_win = is_forced_win
                    break
            
            text += "\n".join(attempts) + "\n\n"
    
        if is_natural:
            await update_user_balance(chat_id, user_id, bet * 2, action="Craps Win")
            text += f"🎉 Натуральная победа (Pass Line)! Вы выиграли <b>{bet}</b> сыроежек."
        elif is_craps:
            text += f"❌ Крэпс! Вы проиграли <b>{bet}</b> сыроежек."
        else:
            if is_win:
                await update_user_balance(chat_id, user_id, bet * 2, action="Craps Win")
                text += f"🎯 Вы выиграли поинт! Выиграно <b>{bet}</b> сыроежек."
            else:
                text += f"❌ Вы не выкинули поинт. Проиграно <b>{bet}</b> сыроежек."
    
        msg = await callback.message.answer(text)
        asyncio.create_task(schedule_delete(msg, callback.message))
    finally:
        release_confirm_lock(chat_id, message_id)
