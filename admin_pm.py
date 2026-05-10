import asyncio
from aiogram import Router, F, types
from aiogram.filters import Command
from config import CREATOR_ID
from user_manager import update_user_field, get_user_data, update_user_balance
from escape import escape_html
from db import get_db
from whitelist import get_whitelist

router = Router()

# Фильтр: только ЛС и только владелец (Creator)
router.message.filter(F.chat.type == "private", F.from_user.id == CREATOR_ID)

@router.message(F.text.lower().in_(["creator help", "creator помощь"]))
async def creator_help(message: types.Message):
    await message.answer(
        "👑 <b>CREATOR CONTROL PANEL</b>\n\n"
        "📁 <b>Чаты и Юзеры:</b>\n"
        "<code>creator chats</code> — Список всех чатов\n"
        "<code>creator info [chat] [user]</code> — Инфо о юзере\n\n"
        "💰 <b>Экономика:</b>\n"
        "<code>creator setbal [chat] [user] [val]</code>\n"
        "<code>creator givebal [chat] [user] [val]</code>\n"
        "<code>creator self [chat] [val]</code>\n\n"
        "💎 <b>Статус:</b>\n"
        "<code>creator vip [chat] [user] [1/0]</code>\n\n"
        "📢 <b>Система:</b>\n"
        "<code>creator broadcast [текст]</code> — Рассылка во все чаты\n"
        "<code>creator maintenance [on/off]</code> — Тех. работы"
    )

@router.message(F.text.lower() == "creator chats")
async def creator_list_chats(message: types.Message):
    db = get_db()
    try:
        chats_ref = db.collection('chats')
        docs = await chats_ref.get()
        
        res = "📁 <b>Список активных чатов:</b>\n\n"
        count = 0
        for doc in docs:
            chat_data = doc.to_dict()
            title = chat_data.get('title', 'Без названия')
            res += f"🔹 <code>{doc.id}</code> — <b>{escape_html(title)}</b>\n"
            count += 1
        
        if count == 0: res += "<i>Чаты не найдены.</i>"
        else: res += f"\nВсего: {count}"
        await message.answer(res)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@router.message(F.text.lower().startswith("creator info"))
async def creator_user_info(message: types.Message):
    parts = message.text.split()
    if len(parts) < 4:
        return await message.answer("❌ <code>creator info [chat_id] [user_id]</code>")
    
    try:
        cid, uid = int(parts[2]), int(parts[3])
        data = await get_user_data(cid, uid)
        
        res = (
            f"👤 <b>Юзер:</b> {escape_html(data.get('full_name', '?'))} (ID: <code>{uid}</code>)\n"
            f"📍 <b>Чат:</b> <code>{cid}</code>\n\n"
            f"💰 Баланс: <b>{data.get('balance', 0)}</b> сыр.\n"
            f"📈 Репутация: <b>{data.get('reputation', 0)}</b>\n"
            f"🌟 Статус: {'💎 VIP' if data.get('is_vip') else 'Обычный'}"
        )
        await message.answer(res)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@router.message(F.text.lower().startswith("creator broadcast"))
async def creator_broadcast(message: types.Message):
    # Убираем первые два слова "creator broadcast"
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer("❌ Введите текст для рассылки.")
    
    announcement = parts[2]
    whitelist = await get_whitelist()
    
    msg = await message.answer(f"📡 <b>Начинаю рассылку в {len(whitelist)} чатов...</b>")
    
    success, fail = 0, 0
    for chat_id in whitelist:
        try:
            await message.bot.send_message(chat_id, announcement)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    
    await msg.edit_text(f"✅ <b>Рассылка завершена!</b>\n\nУспешно: {success}\nОшибок: {fail}")

@router.message(F.text.lower().startswith("creator maintenance"))
async def creator_maintenance(message: types.Message):
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("❌ <code>creator maintenance [on/off]</code>")
    
    status = parts[2].lower()
    is_on = True if status == "on" else False
    
    db = get_db()
    await db.collection('bot_settings').document('maintenance').set({"active": is_on})
    
    await message.answer(f"🛠 <b>Режим тех. работ:</b> {'ВКЛЮЧЕН 🔴' if is_on else 'ВЫКЛЮЧЕН 🟢'}")

@router.message(F.text.lower().startswith("creator setbal"))
async def creator_setbal(message: types.Message):
    parts = message.text.split()
    if len(parts) < 5: return await message.answer("❌ <code>creator setbal [chat] [user] [val]</code>")
    try:
        cid, uid, val = int(parts[2]), int(parts[3]), int(parts[4])
        await update_user_field(cid, uid, "balance", val)
        await message.answer(f"✅ Установлен баланс <b>{val}</b> для <code>{uid}</code> в <code>{cid}</code>.")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")

@router.message(F.text.lower().startswith("creator givebal"))
async def creator_givebal(message: types.Message):
    parts = message.text.split()
    if len(parts) < 5: return await message.answer("❌ <code>creator givebal [chat] [user] [val]</code>")
    try:
        cid, uid, val = int(parts[2]), int(parts[3]), int(parts[4])
        await update_user_balance(cid, uid, val)
        await message.answer(f"✅ Добавлено <b>{val}</b> сыр. юзеру <code>{uid}</code> в <code>{cid}</code>.")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")

@router.message(F.text.lower().startswith("creator self"))
async def creator_self_bal(message: types.Message):
    parts = message.text.split()
    if len(parts) < 4: return await message.answer("❌ <code>creator self [chat] [val]</code>")
    try:
        cid, val = int(parts[2]), int(parts[3])
        await update_user_field(cid, CREATOR_ID, "balance", val)
        await message.answer(f"👑 Баланс <b>{val}</b> начислен вам в чате <code>{cid}</code>.")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")

@router.message(F.text.lower().startswith("creator vip"))
async def creator_vip(message: types.Message):
    parts = message.text.split()
    if len(parts) < 5: return await message.answer("❌ <code>creator vip [chat] [user] [1/0]</code>")
    try:
        cid, uid, status = int(parts[2]), int(parts[3]), int(parts[4])
        is_vip = (status == 1)
        await update_user_field(cid, uid, "is_vip", is_vip)
        await message.answer(f"✅ VIP для <code>{uid}</code> в <code>{cid}</code> -> <b>{is_vip}</b>.")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")
