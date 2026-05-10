from aiogram import Router, F, types
from aiogram.filters import Command
from config import CREATOR_ID
from user_manager import update_user_field, get_user_data
from escape import escape_html

router = Router()

# Фильтр: только ЛС и только владелец
@router.message(F.chat.type == "private", F.from_user.id == CREATOR_ID)
async def admin_pm_handler(message: types.Message):
    text = message.text.lower()
    
    if text.startswith("админ баланс"):
        # Формат: админ баланс -100123456789 500000
        parts = message.text.split()
        if len(parts) < 4:
            return await message.answer("❌ Формат: <code>админ баланс [chat_id] [сумма]</code>")
        
        try:
            target_chat_id = int(parts[2])
            amount = int(parts[3])
            
            # Обновляем поле напрямую в базе через user_manager
            await update_user_field(target_chat_id, CREATOR_ID, "balance", amount)
            
            await message.answer(f"✅ Баланс в чате <code>{target_chat_id}</code> успешно изменен на <b>{amount}</b> сыр.\n(В чат уведомление не отправлялось)")
        except ValueError:
            await message.answer("❌ Ошибка: ID чата и сумма должны быть числами.")
        except Exception as e:
            await message.answer(f"❌ Ошибка выполнения: {e}")

    elif text.startswith("админ инфо"):
        # Формат: админ инфо -100123456789
        parts = message.text.split()
        if len(parts) < 3:
            return await message.answer("❌ Формат: <code>админ инфо [chat_id]</code>")
        
        try:
            target_chat_id = int(parts[2])
            data = await get_user_data(target_chat_id, CREATOR_ID)
            
            balance = data.get('balance', 0)
            rep = data.get('reputation', 0)
            vip = "💎" if data.get('is_vip') else "Нет"
            
            res = (
                f"📊 <b>Ваши данные в чате {target_chat_id}:</b>\n\n"
                f"💰 Баланс: <b>{balance}</b>\n"
                f"📈 Репутация: <b>{rep}</b>\n"
                f"🌟 VIP: {vip}\n"
            )
            await message.answer(res)
        except ValueError:
            await message.answer("❌ Ошибка: ID чата должен быть числом.")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

    elif text == "админ помощь":
        await message.answer(
            "🛠 <b>Панель управления (ЛС):</b>\n\n"
            "<code>админ баланс [chat_id] [сумма]</code> — поставить себе баланс\n"
            "<code>админ инфо [chat_id]</code> — проверить статы в чате\n"
            "<code>админ помощь</code> — этот список"
        )
