from aiogram import Router, F, types
from aiogram.filters import Command
from config import CREATOR_ID
from user_manager import update_user_field, get_user_data, update_user_balance
from escape import escape_html
from db import get_db

router = Router()

# Фильтр: только ЛС и только владелец (Creator)
@router.message(F.chat.type == "private", F.from_user.id == CREATOR_ID)
async def creator_pm_handler(message: types.Message):
    text = message.text.lower()
    
    # 1. ПОМОЩЬ
    if text == "creator help" or text == "creator помощь":
        await message.answer(
            "👑 <b>CREATOR CONTROL PANEL</b>\n\n"
            "<code>creator chats</code> — Список всех чатов (ID + Имя)\n"
            "<code>creator info [chat_id] [user_id]</code> — Инфо о юзере в чате\n"
            "<code>creator setbal [chat_id] [user_id] [amount]</code> — Поставить баланс\n"
            "<code>creator givebal [chat_id] [user_id] [amount]</code> — Добавить к балансу\n"
            "<code>creator vip [chat_id] [user_id] [1/0]</code> — Выдать(1)/Забрать(0) VIP\n"
            "<code>creator self [chat_id] [amount]</code> — Поставить себе баланс в чате"
        )

    # 2. СПИСОК ЧАТОВ
    elif text == "creator chats":
        db = get_db()
        try:
            chats_ref = db.collection('chats')
            docs = await chats_ref.get()
            
            res = "📁 <b>Список активных чатов:</b>\n\n"
            count = 0
            for doc in docs:
                chat_data = doc.to_dict()
                # Название чата обычно хранится в настройках чата или берется из логов
                title = chat_data.get('title', 'Без названия')
                res += f"🔹 <code>{doc.id}</code> — <b>{escape_html(title)}</b>\n"
                count += 1
            
            if count == 0:
                res += "<i>Чаты не найдены в БД.</i>"
            else:
                res += f"\nВсего: {count}"
            
            await message.answer(res)
        except Exception as e:
            await message.answer(f"❌ Ошибка получения чатов: {e}")

    # 3. ИНФО О ЮЗЕРЕ
    elif text.startswith("creator info"):
        parts = message.text.split()
        if len(parts) < 4:
            return await message.answer("❌ Формат: <code>creator info [chat_id] [user_id]</code>")
        
        try:
            cid, uid = int(parts[2]), int(parts[3])
            data = await get_user_data(cid, uid)
            
            balance = data.get('balance', 0)
            rep = data.get('reputation', 0)
            vip = "💎 VIP" if data.get('is_vip') else "Обычный"
            name = escape_html(data.get('full_name', 'Неизвестно'))
            
            res = (
                f"👤 <b>Юзер:</b> {name} (ID: <code>{uid}</code>)\n"
                f"📍 <b>Чат:</b> <code>{cid}</code>\n\n"
                f"💰 Баланс: <b>{balance}</b> сыр.\n"
                f"📈 Репутация: <b>{rep}</b>\n"
                f"🌟 Статус: {vip}"
            )
            await message.answer(res)
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

    # 4. УСТАНОВИТЬ БАЛАНС (ЛЮБОМУ)
    elif text.startswith("creator setbal"):
        parts = message.text.split()
        if len(parts) < 5:
            return await message.answer("❌ Формат: <code>creator setbal [chat_id] [user_id] [amount]</code>")
        
        try:
            cid, uid, val = int(parts[2]), int(parts[3]), int(parts[4])
            await update_user_field(cid, uid, "balance", val)
            await message.answer(f"✅ Установлен баланс <b>{val}</b> для юзера <code>{uid}</code> в чате <code>{cid}</code>.")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

    # 5. ДОБАВИТЬ К БАЛАНСУ
    elif text.startswith("creator givebal"):
        parts = message.text.split()
        if len(parts) < 5:
            return await message.answer("❌ Формат: <code>creator givebal [chat_id] [user_id] [amount]</code>")
        
        try:
            cid, uid, val = int(parts[2]), int(parts[3]), int(parts[4])
            await update_user_balance(cid, uid, val)
            await message.answer(f"✅ Юзеру <code>{uid}</code> добавлено <b>{val}</b> сыр. в чате <code>{cid}</code>.")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

    # 6. УПРАВЛЕНИЕ VIP
    elif text.startswith("creator vip"):
        parts = message.text.split()
        if len(parts) < 5:
            return await message.answer("❌ Формат: <code>creator vip [chat_id] [user_id] [1/0]</code>")
        
        try:
            cid, uid, status = int(parts[2]), int(parts[3]), int(parts[4])
            is_vip = True if status == 1 else False
            await update_user_field(cid, uid, "is_vip", is_vip)
            await message.answer(f"✅ Статус VIP для <code>{uid}</code> изменен на <b>{is_vip}</b> в чате <code>{cid}</code>.")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

    # 7. БЫСТРЫЙ БАЛАНС СЕБЕ
    elif text.startswith("creator self"):
        parts = message.text.split()
        if len(parts) < 4:
            return await message.answer("❌ Формат: <code>creator self [chat_id] [amount]</code>")
        
        try:
            cid, val = int(parts[2]), int(parts[3])
            await update_user_field(cid, CREATOR_ID, "balance", val)
            await message.answer(f"👑 Баланс <b>{val}</b> успешно начислен вам в чате <code>{cid}</code>.")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
