from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
import asyncio
from aiogram import Router, F, types
from aiogram.filters import Command
from config import CREATOR_ID, CREATOR_IDS
from user_manager import update_user_field, get_user_data, update_user_balance, flush_user_cache_immediately
from escape import escape_html
from db import get_db
from whitelist import get_whitelist
from utils import fire_and_forget

router = Router()

# Фильтр: только ЛС и только владелец (Creator)
# Проверяем что CREATOR_ID задан (не 0), иначе фильтр пропустит всех
if CREATOR_IDS:
    router.message.filter(F.chat.type == "private", F.from_user.id.in_(CREATOR_IDS))
else:
    # Если CREATOR_ID не задан, блокируем весь роутер невозможным условием
    router.message.filter(F.chat.type == "private", F.from_user.id == -1)

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
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer("❌ Введите текст для рассылки.")
    
    announcement = parts[2]
    whitelist = await get_whitelist()
    
    await message.answer(f"📡 <b>Рассылка запущена в фоновом режиме!</b>\nОжидаемое количество чатов: {len(whitelist)}\n\n<i>Я уведомлю вас о завершении.</i>")
    
    async def run_broadcast():
        success, fail = 0, 0
        for chat_id in whitelist:
            try:
                await message.bot.send_message(chat_id, announcement)
                success += 1
                await asyncio.sleep(0.1) # Чуть больше задержка для безопасности
            except Exception:
                fail += 1
        
        await message.bot.send_message(CREATOR_ID, f"✅ <b>Фоновая рассылка завершена!</b>\n\nУспешно: {success}\nОшибок: {fail}")

    fire_and_forget(run_broadcast())

@router.message(F.text.lower().startswith("creator maintenance"))
async def creator_maintenance(message: types.Message):
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("❌ <code>creator maintenance [on/off]</code>")
    
    status = parts[2].lower()
    if status not in {"on", "off"}:
        return await message.answer("Допустимые значения: on / off.")
    is_on = status == "on"
    
    db = get_db()
    await db.collection('bot_settings').document('maintenance').set({"active": is_on})
    
    await message.answer(f"🛠 <b>Режим тех. работ:</b> {'ВКЛЮЧЕН 🔴' if is_on else 'ВЫКЛЮЧЕН 🟢'}")

@router.message(F.text.lower().startswith("creator setbal"))
async def creator_setbal(message: types.Message):
    parts = message.text.split()
    if len(parts) < 5: return await message.answer("❌ <code>creator setbal [chat] [user] [val]</code>")
    try:
        cid, uid, val = int(parts[2]), int(parts[3]), int(parts[4])
        if uid <= 0 or val < 0 or val > 2**63 - 1:
            return await message.answer("Нужны положительный ID и неотрицательный баланс в пределах лимита.")
        await update_user_field(cid, uid, "balance", val)
        await message.answer(f"✅ Установлен баланс <b>{val}</b> для <code>{uid}</code> в <code>{cid}</code>.")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")

@router.message(F.text.lower().startswith("creator givebal"))
async def creator_givebal(message: types.Message):
    parts = message.text.split()
    if len(parts) < 5: return await message.answer("❌ <code>creator givebal [chat] [user] [val]</code>")
    try:
        cid, uid, val = int(parts[2]), int(parts[3]), int(parts[4])
        if uid <= 0 or abs(val) > 2**63 - 1:
            return await message.answer("Неверный ID или сумма.")
        result = await update_user_balance(cid, uid, val, min_balance=0)
        if result is None:
            return await message.answer("Недостаточно средств для списания.")
        await flush_user_cache_immediately(cid, uid)
        await message.answer(f"✅ Добавлено <b>{val}</b> сыр. юзеру <code>{uid}</code> в <code>{cid}</code>.")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")

@router.message(F.text.lower().startswith("creator self"))
async def creator_self_bal(message: types.Message):
    parts = message.text.split()
    if len(parts) < 4: return await message.answer("❌ <code>creator self [chat] [val]</code>")
    try:
        cid, val = int(parts[2]), int(parts[3])
        if not 0 <= val <= 2**63 - 1:
            return await message.answer("Баланс должен быть неотрицательным числом в пределах лимита.")
        await update_user_field(cid, CREATOR_ID, "balance", val)
        await message.answer(f"👑 Баланс <b>{val}</b> установлен вам в чате <code>{cid}</code>.")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")

@router.message(F.text.lower().startswith("creator vip"))
async def creator_vip(message: types.Message):
    parts = message.text.split()
    if len(parts) < 5: return await message.answer("❌ <code>creator vip [chat] [user] [1/0]</code>")
    try:
        cid, uid, status = int(parts[2]), int(parts[3]), int(parts[4])
        if uid <= 0 or status not in {0, 1}:
            return await message.answer("Нужны положительный ID и статус 0 или 1.")
        is_vip = (status == 1)
        await update_user_field(cid, uid, "is_vip", is_vip)
        await message.answer(f"✅ VIP для <code>{uid}</code> в <code>{cid}</code> -> <b>{is_vip}</b>.")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")

@router.message(Command("reset_game"))
async def cmd_reset_game(message: types.Message, state: FSMContext):
    if not CREATOR_IDS or not message.from_user or message.from_user.id not in CREATOR_IDS:
        return await message.answer("Эта команда доступна только Создателю.")

    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split()
        if len(args) > 1:
            try:
                target_id = int(args[1])
            except ValueError:
                return await message.answer("Неверный ID.")
        else:
            return await message.answer("Сделайте реплай или укажите ID: /reset_game [ID]")

    args = (message.text or "").split()
    if len(args) < 3:
        return await message.answer("Укажите целевой чат: /reset_game USER_ID CHAT_ID")
    try:
        target_chat_id = int(args[2])
    except ValueError:
        return await message.answer("Неверный ID чата.")

    try:
         # Нужен доступ к диспетчеру для FSM
        state = FSMContext(storage=state.storage, key=StorageKey(bot_id=message.bot.id, chat_id=target_chat_id, user_id=target_id))
        await state.clear()

        await message.answer(f"✅ FSM стейт (включая зависший блэкджек) для пользователя <code>{target_id}</code> успешно сброшен.")
    except Exception as e:
        await message.answer(f"❌ Ошибка сброса стейта: {e}")
