import asyncio
from aiogram import Router, types, F, Bot, BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from config import CREATOR_ID
from escape import escape_html
from db import get_db
import time

router = Router()

log_buffer = []

async def get_log_chat_id():
    db = get_db()
    doc = await db.collection('bot_settings').document('logchat').get()
    if doc.exists:
        return doc.to_dict().get('chat_id')
    return None

@router.message(Command("setlogchat"))
async def cmd_setlogchat(message: types.Message):
    if CREATOR_ID and int(message.from_user.id) != int(CREATOR_ID):
        return

    args = message.text.split()
    if len(args) > 1:
        try:
            chat_id = int(args[1])
        except ValueError:
            await message.answer("❌ Неверный формат ID чата.")
            return
    else:
        chat_id = message.chat.id

    db = get_db()
    from utils import fire_and_forget
    fire_and_forget(db.collection('bot_settings').document('logchat').set({'chat_id': chat_id}, merge=True))
    await message.answer(f"✅ Чат {chat_id} успешно назначен глобальным Лог-Чатом.")

def log_action(text: str):
    log_buffer.append(f"[{time.strftime('%H:%M:%S')}] {text}")

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            text = event.text or event.caption or ""
            from utils import is_valid_command
            if is_valid_command(text):
                from_user = event.from_user
                user_id = from_user.id if from_user else 0
                username = f"@{from_user.username}" if from_user and from_user.username else ""
                full_name = escape_html(from_user.full_name) if from_user else "Unknown"
                chat_title = escape_html(event.chat.title) if event.chat.title else "Private"
                chat_id = event.chat.id
                
                log_text = f"💬 Команда: <b>{full_name}</b> ({user_id}) {username} в чате «{chat_title}» ({chat_id}): <code>{escape_html(text)}</code>"
                log_action(log_text)
                
        elif isinstance(event, CallbackQuery):
            from_user = event.from_user
            user_id = from_user.id if from_user else 0
            username = f"@{from_user.username}" if from_user and from_user.username else ""
            full_name = escape_html(from_user.full_name) if from_user else "Unknown"
            chat_title = escape_html(event.message.chat.title) if event.message and event.message.chat and event.message.chat.title else "Private"
            chat_id = event.message.chat.id if event.message and event.message.chat else 0
            data_str = event.data or ""
            
            log_text = f"🔘 Кнопка: <b>{full_name}</b> ({user_id}) {username} в чате «{chat_title}» ({chat_id}): <code>{escape_html(data_str)}</code>"
            log_action(log_text)
            
        return await handler(event, data)

async def flush_logs(bot: Bot):
    while True:
        await asyncio.sleep(60) # раз в минуту
        if not log_buffer:
            continue

        log_chat_id = await get_log_chat_id()
        if not log_chat_id:
            log_buffer.clear()
            continue

        logs_to_send = "\n\n".join(log_buffer)
        log_buffer.clear()

        # Разбиваем на чанки по 4000 символов, если нужно
        chunks = [logs_to_send[i:i+4000] for i in range(0, len(logs_to_send), 4000)]
        for chunk in chunks:
            try:
                await bot.send_message(chat_id=log_chat_id, text=f"📜 <b>Логи за минуту:</b>\n\n{chunk}")
            except Exception as e:
                print(f"Failed to send logs: {e}")

