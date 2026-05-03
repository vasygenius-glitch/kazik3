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
        await bot.ban_chat_member(chat_id=chat_id, user_id=target.id)
        text = f"🔨 Пользователь <b>{escape_html(target.full_name)}</b> забанен навсегда.\n"
        if reason:
            text += f"Причина: <i>{escape_html(reason)}</i>"
        await message.answer(text)
    except Exception as e:
        await message.answer(f"Не удалось забанить: {e}")
