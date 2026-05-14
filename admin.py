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

@router.message(F.text.lower().startswith(("мут", "!мут", "!!!мут")))
async def cmd_mute(message: types.Message, bot: Bot):
    from crypto import is_admin
    # Проверка прав: создатель или админ группы
    if int(message.from_user.id) != int(CREATOR_ID) and not await is_admin(message):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для мута.")

    target = message.reply_to_message.from_user
    if int(target.id) == int(CREATOR_ID):
        return await message.answer("Создателя нельзя мутить.")

    # Извлекаем время (по умолчанию 60 минут)
    args = message.text.split()
    minutes = 60
    if len(args) > 1:
        try:
            minutes = int(args[1])
        except ValueError:
            pass

    until_date = int(time.time()) + (minutes * 60)
    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            permissions=types.ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await message.answer(f"🔇 Пользователь <b>{escape_html(target.full_name)}</b> отправлен в мут на {minutes} мин.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@router.message(F.text.lower().startswith(("размут", "!размут", "!!!размут")))
async def cmd_unmute(message: types.Message, bot: Bot):
    from crypto import is_admin
    if int(message.from_user.id) != int(CREATOR_ID) and not await is_admin(message):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для размута.")

    target = message.reply_to_message.from_user
    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        await message.answer(f"🔊 С пользователя <b>{escape_html(target.full_name)}</b> сняты ограничения.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@router.message(F.text.lower().startswith(("варн", "!варн", "!!!варн")))
async def cmd_warn(message: types.Message, bot: Bot):
    from crypto import is_admin
    if int(message.from_user.id) != int(CREATOR_ID) and not await is_admin(message):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для варрна.")

    target = message.reply_to_message.from_user
    if int(target.id) == int(CREATOR_ID):
        return await message.answer("Создателю нельзя выдать варн.")

    from user_manager import get_user_data, update_user_field, invalidate_user_cache
    data = await get_user_data(message.chat.id, target.id)
    warns = data.get('warns', [])
    
    reason = extract_args(message.text)
    warns.append({"reason": reason, "time": int(time.time()), "by": message.from_user.id})
    
    await update_user_field(message.chat.id, target.id, 'warns', warns)
    
    count = len(warns)
    if count >= 3:
        # Авто-бан при 3 варнах
        try:
            await update_user_field(message.chat.id, target.id, 'is_banned', True)
            invalidate_user_cache(message.chat.id, target.id)
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=target.id)
            await message.answer(f"🔨 Пользователь <b>{escape_html(target.full_name)}</b> получил 3/3 варна и был забанен.")
        except Exception as e:
            await message.answer(f"Ошибка при авто-бане: {e}")
    else:
        await message.answer(f"⚠️ Пользователь <b>{escape_html(target.full_name)}</b> получил варн ({count}/3).\nПричина: <i>{escape_html(reason or 'Не указана')}</i>")

@router.message(F.text.lower().startswith(("снять варн", "!снять варн", "!!!снять варн")))
async def cmd_unwarn(message: types.Message):
    from crypto import is_admin
    if int(message.from_user.id) != int(CREATOR_ID) and not await is_admin(message):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для снятия варна.")

    target = message.reply_to_message.from_user
    from user_manager import get_user_data, update_user_field
    data = await get_user_data(message.chat.id, target.id)
    warns = data.get('warns', [])
    
    if not warns:
        return await message.answer("У пользователя нет варнов.")
    
    warns.pop()
    await update_user_field(message.chat.id, target.id, 'warns', warns)
    await message.answer(f"✅ У пользователя <b>{escape_html(target.full_name)}</b> снят один варн (осталось {len(warns)}/3).")
