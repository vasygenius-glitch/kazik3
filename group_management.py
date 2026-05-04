import time
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from db import get_db
from escape import escape_html
from user_manager import update_user_field
from config import CREATOR_ID

router = Router()

from utils import fire_and_forget

_group_settings_cache = {}
_group_settings_cache_time = {}
GROUP_SETTINGS_CACHE_TTL = 60.0

async def get_group_settings(chat_id: int):
    global _group_settings_cache, _group_settings_cache_time
    chat_key = str(chat_id)
    if chat_key in _group_settings_cache and time.time() - _group_settings_cache_time.get(chat_key, 0) < GROUP_SETTINGS_CACHE_TTL:
        return _group_settings_cache[chat_key]

    db = get_db()
    doc = await db.collection('chats').document(chat_key).collection('settings').document('config').get()

    if doc.exists:
        data = doc.to_dict()
    else:
        data = {}

    _group_settings_cache[chat_key] = data
    _group_settings_cache_time[chat_key] = time.time()
    return data

async def update_group_settings(chat_id: int, field: str, value):
    global _group_settings_cache, _group_settings_cache_time
    chat_key = str(chat_id)

    if chat_key not in _group_settings_cache:
        _group_settings_cache[chat_key] = {}

    _group_settings_cache[chat_key][field] = value
    _group_settings_cache_time[chat_key] = time.time()

    db = get_db()
    fire_and_forget(db.collection('chats').document(chat_key).collection('settings').document('config').set({field: value}, merge=True))

# 1. ПРИВЕТСТВИЕ И ПРАВИЛА
@router.message(F.text.lower().startswith("приветствие ") | F.text.lower().startswith("!приветствие "))
async def set_welcome(message: types.Message, bot: Bot):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if int(user_id) != int(CREATOR_ID):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return
    text = parts[1]

    await update_group_settings(chat_id, 'welcome_text', text)
    await message.answer("✅ Приветствие установлено!")

@router.message(F.new_chat_members)
async def welcome_new_member(message: types.Message):
    settings = await get_group_settings(message.chat.id)
    welcome_text = settings.get('welcome_text')

    if welcome_text:
        for user in message.new_chat_members:
            if user.is_bot: continue
            text = welcome_text.replace("{name}", escape_html(user.full_name)).replace("{username}", f"@{user.username}" if user.username else escape_html(user.full_name))
            await message.answer(f"Привет, {escape_html(user.full_name)}!\n\n{text}")

@router.message(F.text.lower().startswith("+правила "))
async def set_rules(message: types.Message, bot: Bot):
    if int(message.from_user.id) != int(CREATOR_ID):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return
    text = parts[1]

    db = get_db()
    fire_and_forget(db.collection('bot_settings').document('global_rules').set({'text': text}))

    global _global_rules_cache, _global_rules_cache_time
    _global_rules_cache = text
    _global_rules_cache_time = time.time()

    await message.answer("✅ Глобальные правила успешно обновлены!")

_global_rules_cache = None
_global_rules_cache_time = 0
GLOBAL_RULES_CACHE_TTL = 300.0

@router.message(F.text.lower().in_(["правила", "!правила", "/rules"]))
async def show_rules(message: types.Message):
    global _global_rules_cache, _global_rules_cache_time

    if _global_rules_cache is not None and time.time() - _global_rules_cache_time < GLOBAL_RULES_CACHE_TTL:
        text = _global_rules_cache
    else:
        db = get_db()
        doc = await db.collection('bot_settings').document('global_rules').get()
        if doc.exists:
            text = doc.to_dict().get('text', "Правила пока не установлены.")
        else:
            text = "Правила пока не установлены."
        _global_rules_cache = text
        _global_rules_cache_time = time.time()

    await message.answer(f"📜 <b>Правила:</b>\n\n{text}")

# 2. ЗАМЕТКИ
@router.message(F.text.lower().startswith("заметка ") | F.text.lower().startswith("!заметка "))
async def set_note(message: types.Message, bot: Bot):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if int(user_id) != int(CREATOR_ID):
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3: return await message.answer("Использование: заметка [имя] [текст]")

    note_name = parts[1].lower()
    note_text = parts[2]

    db = get_db()
    fire_and_forget(db.collection('chats').document(str(chat_id)).collection('notes').document(note_name).set({'text': note_text}))
    await message.answer(f"📝 Заметка <b>{escape_html(note_name)}</b> сохранена! Вызов: <code>?{escape_html(note_name)}</code>")

@router.message(F.text.startswith("?"))
async def get_note(message: types.Message):
    note_name = message.text[1:].strip().lower()
    if not note_name: return

    db = get_db()
    doc = await db.collection('chats').document(str(message.chat.id)).collection('notes').document(note_name).get()
    if doc.exists:
        text = doc.to_dict().get('text', "")
        await message.answer(text)

# 3. АВТОМОДЕРАЦИЯ (Антилинк)
@router.message(F.text.lower().in_(["антилинк вкл", "антилинк выкл"]))
async def toggle_antilink(message: types.Message, bot: Bot):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if int(user_id) != int(CREATOR_ID):
        return

    is_on = "вкл" in message.text.lower()
    await update_group_settings(chat_id, 'antilink', is_on)
    await message.answer(f"🛡 Анти-ссылки {'включены' if is_on else 'выключены'}.")

@router.message(F.text & (F.text.lower().contains("http://") | F.text.lower().contains("https://") | F.text.lower().contains("t.me/")))
async def antilink_check(message: types.Message, bot: Bot):
    if not message.text: return

    settings = await get_group_settings(message.chat.id)
    if settings.get('antilink', False):
        user_id = message.from_user.id
        # Создателя не наказываем за ссылки
        if int(user_id) == int(CREATOR_ID):
            return

        await message.delete()
        msg = await message.answer(f"⚠️ <b>{escape_html(message.from_user.full_name)}</b>, ссылки в этом чате запрещены!")
        import asyncio
        await asyncio.sleep(10)
        try: await msg.delete()
        except: pass

# 4. БИО ПРОФИЛЯ
@router.message(F.text.lower().startswith("/bio ") | F.text.lower().startswith("био "))
async def set_bio(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return

    bio_text = parts[1][:100] # Лимит 100 символов
    await update_user_field(message.chat.id, message.from_user.id, 'bio', bio_text)
    await message.answer("✅ Биография обновлена!")

# 5. АНТИВОЙС
@router.message(F.text.lower().in_(["антивойс вкл", "антивойс выкл"]))
async def toggle_antivoice(message: types.Message, bot: Bot):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if int(user_id) != int(CREATOR_ID):
        return

    is_on = "вкл" in message.text.lower()
    await update_group_settings(chat_id, 'antivoice', is_on)
    await message.answer(f"🎙 Анти-голосовые {'включены' if is_on else 'выключены'}.")

@router.message(F.voice | F.video_note)
async def antivoice_check(message: types.Message, bot: Bot):
    settings = await get_group_settings(message.chat.id)
    if settings.get('antivoice', False):
        user_id = message.from_user.id
        if int(user_id) == int(CREATOR_ID):
            return

        await message.delete()
        msg = await message.answer(f"⚠️ <b>{escape_html(message.from_user.full_name)}</b>, голосовые и видеосообщения в этом чате запрещены!")
        import asyncio
        await asyncio.sleep(10)
        try: await msg.delete()
        except: pass
