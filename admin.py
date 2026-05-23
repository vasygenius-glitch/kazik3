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

def is_creator(user_id: int):
    return int(user_id) == int(CREATOR_ID)

@router.message(F.text.startswith("!!!ban"))
async def cmd_ban_only_creator(message: types.Message, bot: Bot):
    if not is_creator(message.from_user.id):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для бана.")

    chat_id = message.chat.id
    target = message.reply_to_message.from_user

    if target.is_bot:
        return await message.answer("Нельзя забанить бота.")

    if is_creator(target.id):
        return await message.answer("Создателя нельзя забанить.")

    reason = extract_args(message.text)

    try:
        from user_manager import update_user_field, invalidate_user_cache
        await update_user_field(chat_id, target.id, 'is_banned', True)
        invalidate_user_cache(chat_id, target.id)

        await bot.ban_chat_member(chat_id=chat_id, user_id=target.id)
        text = f"🔨 Пользователь <b>{escape_html(target.full_name)}</b> забанен навсегда.\n"
        if reason:
            text += f"Причина: <i>{escape_html(reason)}</i>"
        await message.answer(text)
        from log_system import log_action
        log_action(f"🔨 <b>Бан:</b> {message.from_user.full_name} ({message.from_user.id}) забанил {target.full_name} ({target.id}) в чате {chat_id}. Причина: {reason or 'Не указана'}")
    except Exception as e:
        await message.answer(f"Не удалось забанить: {e}")

@router.message(F.text.startswith("!!!wipe"))
async def cmd_wipe_only_creator(message: types.Message, bot: Bot):
    if not is_creator(message.from_user.id):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для вайпа.")

    chat_id = message.chat.id
    target = message.reply_to_message.from_user

    if is_creator(target.id):
        return await message.answer("Создателя нельзя вайпнуть.")

    try:
        from user_manager import wipe_user_data
        await wipe_user_data(chat_id, target.id)
        await message.answer(f"🧹 Данные пользователя <b>{escape_html(target.full_name)}</b> полностью обнулены.")
        from log_system import log_action
        log_action(f"🧹 <b>Вайп игрока:</b> {message.from_user.full_name} ({message.from_user.id}) вайпнул {target.full_name} ({target.id}) в чате {chat_id}")
    except Exception as e:
        await message.answer(f"Ошибка при вайпе: {e}")

# Изменяем фильтры на более строгие, чтобы не реагировать на обычную речь
@router.message(F.text.regexp(r"^[!/]+мут(\s|$)"))
async def cmd_mute(message: types.Message, bot: Bot):
    if not is_creator(message.from_user.id):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для мута.")

    target = message.reply_to_message.from_user
    if is_creator(target.id):
        return await message.answer("Создателя нельзя мутить.")

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
        from log_system import log_action
        log_action(f"🔇 <b>Мут:</b> {message.from_user.full_name} ({message.from_user.id}) замутил {target.full_name} ({target.id}) на {minutes} мин. в чате {message.chat.id}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@router.message(F.text.regexp(r"^[!/]+размут(\s|$)"))
async def cmd_unmute(message: types.Message, bot: Bot):
    if not is_creator(message.from_user.id):
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
        from log_system import log_action
        log_action(f"🔊 <b>Размут:</b> {message.from_user.full_name} ({message.from_user.id}) размутил {target.full_name} ({target.id}) в чате {message.chat.id}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@router.message(F.text.regexp(r"^[!/]+варн(\s|$)"))
async def cmd_warn(message: types.Message, bot: Bot):
    if not is_creator(message.from_user.id):
        return

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя для варрна.")

    target = message.reply_to_message.from_user
    if is_creator(target.id):
        return await message.answer("Создателю нельзя выдать варн.")

    from user_manager import get_user_data, update_user_field, invalidate_user_cache
    data = await get_user_data(message.chat.id, target.id)
    warns = data.get('warns', [])
    
    reason = extract_args(message.text)
    warns.append({"reason": reason, "time": int(time.time()), "by": message.from_user.id})
    
    await update_user_field(message.chat.id, target.id, 'warns', warns)
    
    count = len(warns)
    if count >= 3:
        try:
            await update_user_field(message.chat.id, target.id, 'is_banned', True)
            invalidate_user_cache(message.chat.id, target.id)
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=target.id)
            await message.answer(f"🔨 Пользователь <b>{escape_html(target.full_name)}</b> получил 3/3 варна и был забанен.")
            from log_system import log_action
            log_action(f"🔨 <b>Авто-бан за варны:</b> {target.full_name} ({target.id}) получил 3/3 варна и был забанен в чате {message.chat.id}")
        except Exception as e:
            await message.answer(f"Ошибка при авто-бане: {e}")
    else:
        await message.answer(f"⚠️ Пользователь <b>{escape_html(target.full_name)}</b> получил варн ({count}/3).\nПричина: <i>{escape_html(reason or 'Не указана')}</i>")
        from log_system import log_action
        log_action(f"⚠️ <b>Варн:</b> {message.from_user.full_name} ({message.from_user.id}) выдал варн ({count}/3) {target.full_name} ({target.id}) в чате {message.chat.id}. Причина: {reason or 'Не указана'}")

@router.message(F.text.regexp(r"^[!/]+снять варн(\s|$)"))
async def cmd_unwarn(message: types.Message):
    if not is_creator(message.from_user.id):
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
    from log_system import log_action
    log_action(f"✅ <b>Снятие варна:</b> {message.from_user.full_name} ({message.from_user.id}) снял варн с {target.full_name} ({target.id}) в чате {message.chat.id} (осталось {len(warns)}/3)")
