import re
import time
from config import CREATOR_ID
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from escape import escape_html

router = Router()

def extract_args(text: str):
    """Извлекает причину из текста (с учетом SHIFT+ENTER)."""
    parts = text.split('\n', 1)
    first_line = parts[0].split()
    reason = parts[1].strip() if len(parts) > 1 else ""
    if len(first_line) > 1 and not reason:
        reason = " ".join(first_line[1:])
    return reason

@router.message(F.text.startswith("!!!ban"))
async def cmd_ban_only_creator(message: types.Message, bot: Bot):
    # Команда работает ТОЛЬКО для создателя
    if int(message.from_user.id) != int(CREATOR_ID):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для бана.")

    chat_id = message.chat.id
    target = message.reply_to_message.from_user

    if target.is_bot:
        return await message.answer("Нельзя забанить бота.")

    if int(target.id) == int(CREATOR_ID):
        return await message.answer("Создателя нельзя забанить.")

    reason = extract_args(message.text)

    try:
        from user_manager import update_user_field, invalidate_user_cache
        # Mark as banned internally too to match creator.py behavior
        await update_user_field(chat_id, target.id, 'is_banned', True)
        invalidate_user_cache(chat_id, target.id)

        await bot.ban_chat_member(chat_id=chat_id, user_id=target.id)
        text = f"🔨 Пользователь <b>{escape_html(target.full_name)}</b> забанен навсегда.\n"
        if reason:
            text += f"Причина: <i>{escape_html(reason)}</i>"
        await message.answer(text)
    except Exception as e:
        await message.answer(f"Не удалось забанить: {e}")

@router.message(F.text.startswith("!!!wipe"))
async def cmd_wipe_only_creator(message: types.Message, bot: Bot):
    if int(message.from_user.id) != int(CREATOR_ID):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для вайпа.")

    chat_id = message.chat.id
    target = message.reply_to_message.from_user

    if int(target.id) == int(CREATOR_ID):
        return await message.answer("Создателя нельзя вайпнуть.")

    try:
        from user_manager import wipe_user_data
        await wipe_user_data(chat_id, target.id)
        
        await message.answer(f"🧹 Данные пользователя <b>{escape_html(target.full_name)}</b> полностью обнулены.")
    except Exception as e:
        await message.answer(f"Ошибка при вайпе: {e}")
