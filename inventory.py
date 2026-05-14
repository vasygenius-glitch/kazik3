import asyncio
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from user_manager import get_user_data, update_user_balance, update_user_field
from shop import ITEMS
from escape import escape_html

_inv_locks = {}
def get_inv_lock(chat_id, user_id):
    key = (chat_id, user_id)
    if key not in _inv_locks:
        _inv_locks[key] = asyncio.Lock()
    return _inv_locks[key]

router = Router()

MAX_BIZ_LEVEL = 5

def get_inventory_main_kb(inventory, biz_levels):
    builder = InlineKeyboardBuilder()
    
    for item_id, count in inventory.items():
        if count > 0 and item_id in ITEMS:
            info = ITEMS[item_id]
            if info.get('action') == 'business':
                level = biz_levels.get(item_id, 1)
                text = f"{info['name']} (Ур. {level})"
            else:
                text = f"{info['name']} ({count} шт)"
            builder.button(text=text, callback_data=f"inv_item_{item_id}")

    builder.button(text="❌ Закрыть", callback_data="inv_close")
    builder.adjust(1)
    return builder.as_markup()

def get_item_kb(item_id, biz_level):
    builder = InlineKeyboardBuilder()
    info = ITEMS.get(item_id)
    if info.get('action') == 'business':
        if biz_level < MAX_BIZ_LEVEL:
            upgrade_cost = int(info['price'] * 0.5 * biz_level)
            builder.button(text=f"⬆️ Улучшить ({upgrade_cost} сыр.)", callback_data=f"inv_upg_{item_id}")
        else:
            builder.button(text="🌟 Макс. уровень", callback_data="none")
            
    builder.button(text="💰 Продать", callback_data=f"inv_sell_{item_id}")
    builder.button(text="⬅️ Назад в инвентарь", callback_data="inv_main")
    builder.adjust(1)
    return builder.as_markup()

@router.message(Command("inventory", "inv", "инвентарь"))
async def cmd_inventory(message: types.Message):
    data = await get_user_data(message.chat.id, message.from_user.id)
    if data.get('is_banned'): return

    inventory = data.get('inventory', {})
    biz_levels = data.get('biz_levels', {})

    has_items = any(count > 0 and item_id in ITEMS for item_id, count in inventory.items())

    if not has_items:
        return await message.answer("🎒 <b>Ваш инвентарь пуст.</b>\nЗагляните в /shop, чтобы купить что-нибудь!")

    text = "🎒 <b>ВАШ ИНВЕНТАРЬ</b>\n\nНажмите на предмет, чтобы управлять им:"
    await message.answer(text, reply_markup=get_inventory_main_kb(inventory, biz_levels))

@router.callback_query(F.data == "inv_main")
async def inv_back(callback: types.CallbackQuery):
    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    inventory = data.get('inventory', {})
    biz_levels = data.get('biz_levels', {})
    text = "🎒 <b>ВАШ ИНВЕНТАРЬ</b>\n\nНажмите на предмет, чтобы управлять им:"
    await callback.message.edit_text(text, reply_markup=get_inventory_main_kb(inventory, biz_levels))

@router.callback_query(F.data == "inv_close")
async def inv_close(callback: types.CallbackQuery):
    await callback.message.delete()

@router.callback_query(F.data.startswith("inv_item_"))
async def inv_item_info(callback: types.CallbackQuery):
    item_id = callback.data.replace("inv_item_", "")
    info = ITEMS.get(item_id)
    if not info: return

    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    inventory = data.get('inventory', {})
    if inventory.get(item_id, 0) <= 0:
        return await callback.answer("У вас нет этого предмета!", show_alert=True)

    biz_levels = data.get('biz_levels', {})
    
    text = f"📦 <b>Предмет:</b> {info['name']}\n"
    if info.get('action') == 'business':
        level = biz_levels.get(item_id, 1)
        level_multiplier = 1.0 + 0.5 * (level - 1)
        income = int(info.get('income', 0) * level_multiplier)
        text += f"📈 <b>Уровень:</b> {level} / {MAX_BIZ_LEVEL}\n"
        text += f"💸 <b>Доход в час:</b> {income} сыр.\n"
        
        # Calculate total invested for sell info
        total_invested = info['price']
        for l in range(1, level):
            total_invested += int(info['price'] * 0.5 * l)
        sell_price = int(total_invested * 0.75)
        text += f"💵 <b>Цена продажи:</b> {sell_price} сыр. (75% от всех вложений)\n\n"
        
        if level < MAX_BIZ_LEVEL:
            text += f"<i>Улучшение увеличит базовый доход на +50%.</i>"
    else:
        text += f"Количество: {inventory[item_id]} шт.\n"
        sell_price = int(info['price'] * 0.75)
        text += f"💵 <b>Цена продажи:</b> {sell_price} сыр.\n"

    await callback.message.edit_text(text, reply_markup=get_item_kb(item_id, biz_levels.get(item_id, 1)))

@router.callback_query(F.data == "none")
async def dummy_callback(callback: types.CallbackQuery):
    await callback.answer()

@router.callback_query(F.data.startswith("inv_upg_"))
async def inv_upgrade(callback: types.CallbackQuery):
    item_id = callback.data.replace("inv_upg_", "")
    info = ITEMS.get(item_id)
    if not info or info.get('action') != 'business': return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    lock = get_inv_lock(chat_id, user_id)
    if lock.locked():
        return await callback.answer("⏳ Обработка...", show_alert=False)
        
    async with lock:
        data = await get_user_data(chat_id, user_id)
        
        inventory = data.get('inventory', {})
        if inventory.get(item_id, 0) <= 0:
            return await callback.answer("У вас нет этого бизнеса!", show_alert=True)

        biz_levels = data.get('biz_levels', {})
        current_level = biz_levels.get(item_id, 1)
        
        if current_level >= MAX_BIZ_LEVEL:
            return await callback.answer("Достигнут максимальный уровень!", show_alert=True)

        upgrade_cost = int(info['price'] * 0.5 * current_level)
        
        if data.get('balance', 0) < upgrade_cost:
            return await callback.answer("Недостаточно сыроежек для улучшения!", show_alert=True)

        await update_user_balance(chat_id, user_id, -upgrade_cost)
        
        biz_levels[item_id] = current_level + 1
        await update_user_field(chat_id, user_id, 'biz_levels', biz_levels)
        
        await callback.answer(f"🎉 Бизнес {info['name']} улучшен до уровня {current_level + 1}!", show_alert=True)
        
        # We can fake the callback data to reload item info
        callback.data = f"inv_item_{item_id}"
        await inv_item_info(callback)

@router.callback_query(F.data.startswith("inv_sellcf_"))
async def confirm_inv_sell(callback: types.CallbackQuery):
    item_id = callback.data.replace("inv_sellcf_", "")
    info = ITEMS.get(item_id)
    if not info: 
        return await callback.answer("Ошибка: Предмет не существует!", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    from db import get_db
    from user_manager import sell_item_tr, get_user_ref, safe_get_snapshot
    from firebase_admin import firestore_async
    
    db = get_db()
    
    @firestore_async.transactional
    async def run_sell_transaction(transaction, chat_id, user_id, item_id, item_info):
        ref = get_user_ref(chat_id, user_id)
        snapshot = await safe_get_snapshot(transaction, ref)
        if not snapshot.exists: return False, 0
        
        data = snapshot.to_dict()
        biz_levels = data.get('biz_levels', {})
        
        sell_price = 0
        if item_info.get('action') == 'business':
            level = biz_levels.get(item_id, 1)
            total_invested = item_info['price']
            for l in range(1, level):
                total_invested += int(item_info['price'] * 0.5 * l)
            sell_price = int(total_invested * 0.75)
        else:
            sell_price = int(item_info['price'] * 0.75)
            
        success = await sell_item_tr(transaction, chat_id, user_id, item_id, item_info.get('cat', ''), sell_price)
        return success, sell_price

    try:
        res = run_sell_transaction(db.transaction(), chat_id, user_id, item_id, info)
        if hasattr(res, "__aiter__"):
            async for r in res: success, sell_price = r
        else:
            success, sell_price = await res
            
        if not success:
            return await callback.answer("Предмет не найден в инвентаре!", show_alert=True)
            
    except Exception as e:
        print(f"Sell error: {e}")
        return await callback.answer("Ошибка при продаже.", show_alert=True)

    await callback.answer(f"✅ Успешно продано за {sell_price} сыр.!", show_alert=True)
    await inv_back(callback)

@router.callback_query(F.data.startswith("inv_sell_"))
async def ask_inv_sell(callback: types.CallbackQuery):
    item_id = callback.data.replace("inv_sell_", "")
    info = ITEMS.get(item_id)
    if not info: return
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить продажу", callback_data=f"inv_sellcf_{item_id}")
    builder.button(text="❌ Отмена", callback_data=f"inv_item_{item_id}")
    builder.adjust(1)
    
    await callback.message.edit_text(f"❓ Вы уверены, что хотите продать <b>{info['name']}</b>?", reply_markup=builder.as_markup())
