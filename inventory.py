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
                text = f"{info['name']} (Ур. {level}) ({count} шт)"
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
    qty = inventory.get(item_id, 0)
    text += f"🎒 <b>Количество:</b> {qty} шт.\n"
    if info.get('desc'):
        text += f"✨ <b>Эффект:</b> {info['desc']}\n"
    if info.get('action') == 'business':
        level = biz_levels.get(item_id, 1)
        level_multiplier = 1.0 + 0.5 * (level - 1)
        income = int(info.get('income', 0) * level_multiplier)
        text += f"📈 <b>Уровень:</b> {level} / {MAX_BIZ_LEVEL}\n"
        text += f"💸 <b>Доход в час (за шт):</b> {income} сыр. (Всего: {income * qty} сыр./ч)\n"
        
        # Calculate total invested for sell info
        total_invested = info['price']
        for l in range(1, level):
            total_invested += int(info['price'] * 0.5 * l)
        sell_price = int(total_invested * 0.75)
        text += f"💵 <b>Цена продажи:</b> {sell_price} сыр. за шт. (75% от всех вложений)\n\n"
        
        if level < MAX_BIZ_LEVEL:
            text += f"<i>Улучшение увеличит базовый доход на +50%.</i>"
    else:
        sell_price = int(info['price'] * 0.75)
        text += f"💵 <b>Цена продажи:</b> {sell_price} сыр. за шт.\n"

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
    
    from db import get_db
    from user_manager import upgrade_business_tr, get_user_data
    from firebase_admin import firestore_async
    
    db = get_db()
    
    @firestore_async.async_transactional
    async def run_upgrade_transaction(transaction, chat_id, user_id, item_id, cost, max_lvl):
        return await upgrade_business_tr(transaction, chat_id, user_id, item_id, cost, max_lvl)

    try:
        data = await get_user_data(chat_id, user_id)
        current_level = data.get('biz_levels', {}).get(item_id, 1)
        upgrade_cost = int(info['price'] * 0.5 * current_level)

        from user_manager import get_user_lock, invalidate_user_cache
        lock = get_user_lock(chat_id, user_id)
        async with lock:
            success, error_msg = await run_upgrade_transaction(db.transaction(), chat_id, user_id, item_id, upgrade_cost, MAX_BIZ_LEVEL)
            if success:
                invalidate_user_cache(chat_id, user_id)
        
        if not success:
            return await callback.answer(f"Ошибка: {error_msg}", show_alert=True)
            
        await callback.answer(f"🎉 Бизнес {info['name']} успешно улучшен!", show_alert=True)
        
        # Reload UI
        callback.data = f"inv_item_{item_id}"
        await inv_item_info(callback)

    except Exception as e:
        print(f"Upgrade error: {e}")
        return await callback.answer("Ошибка при улучшении.", show_alert=True)

@router.callback_query(F.data.startswith("inv_sellcf_"))
async def confirm_inv_sell(callback: types.CallbackQuery):
    raw_data = callback.data.replace("inv_sellcf_", "")
    parts = raw_data.rsplit("_", 1)
    if len(parts) == 2 and (parts[1].isdigit() or parts[1] == "all"):
        item_id = parts[0]
        req_count_str = parts[1]
    else:
        item_id = raw_data
        req_count_str = "1"

    info = ITEMS.get(item_id)
    if not info: 
        return await callback.answer("Ошибка: Предмет не существует!", show_alert=True)

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    from db import get_db
    from user_manager import sell_item_tr, get_user_ref, safe_get_snapshot
    from firebase_admin import firestore_async
    
    db = get_db()
    
    @firestore_async.async_transactional
    async def run_sell_transaction(transaction, chat_id, user_id, item_id, item_info, req_count_str):
        ref = get_user_ref(chat_id, user_id)
        snapshot = await safe_get_snapshot(transaction, ref)
        if not snapshot.exists: return False, 0, 0
        
        data = snapshot.to_dict() or {}
        inv = data.get('inventory', {})
        owned_qty = inv.get(item_id, 0)
        if owned_qty <= 0:
            return False, 0, 0

        if req_count_str == "all":
            sell_count = owned_qty
        else:
            try:
                sell_count = int(req_count_str)
            except ValueError:
                sell_count = 1

        sell_count = min(sell_count, owned_qty)
        if sell_count <= 0:
            return False, 0, 0

        biz_levels = data.get('biz_levels', {})
        sell_unit_price = 0
        if item_info.get('action') == 'business':
            level = biz_levels.get(item_id, 1)
            total_invested = item_info['price']
            for l in range(1, level):
                total_invested += int(item_info['price'] * 0.5 * l)
            sell_unit_price = int(total_invested * 0.75)
        else:
            sell_unit_price = int(item_info['price'] * 0.75)
            
        success = await sell_item_tr(transaction, chat_id, user_id, item_id, item_info.get('cat', ''), sell_unit_price, count=sell_count)
        total_payout = sell_unit_price * sell_count
        return success, total_payout, sell_count

    try:
        from user_manager import get_user_lock, invalidate_user_cache
        lock = get_user_lock(chat_id, user_id)
        async with lock:
            res = run_sell_transaction(db.transaction(), chat_id, user_id, item_id, info, req_count_str)
            if hasattr(res, "__aiter__"):
                async for r in res: success, total_payout, sold_count = r
            else:
                success, total_payout, sold_count = await res
                
            if success:
                invalidate_user_cache(chat_id, user_id)
            
        if not success:
            return await callback.answer("Предмет не найден в инвентаре!", show_alert=True)
            
    except Exception as e:
        print(f"Sell error: {e}")
        return await callback.answer("Ошибка при продаже.", show_alert=True)

    await callback.answer(f"✅ Успешно продано {sold_count} шт. за {total_payout} сыр.!", show_alert=True)
    await inv_back(callback)

@router.callback_query(F.data.startswith("inv_sell_"))
async def ask_inv_sell(callback: types.CallbackQuery):
    item_id = callback.data.replace("inv_sell_", "")
    info = ITEMS.get(item_id)
    if not info: return
    
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    u_data = await get_user_data(chat_id, user_id)
    inv = u_data.get('inventory', {})
    owned_qty = inv.get(item_id, 0)
    
    if owned_qty <= 0:
        return await callback.answer("У вас нет этого предмета!", show_alert=True)

    if info.get('action') == 'business':
        biz_levels = u_data.get('biz_levels', {})
        level = biz_levels.get(item_id, 1)
        total_invested = info['price']
        for l in range(1, level):
            total_invested += int(info['price'] * 0.5 * l)
        sell_unit_price = int(total_invested * 0.75)
    else:
        sell_unit_price = int(info['price'] * 0.75)

    builder = InlineKeyboardBuilder()
    if owned_qty == 1:
        builder.button(text=f"✅ Продать 1 шт. ({sell_unit_price} сыр.)", callback_data=f"inv_sellcf_{item_id}_1")
    else:
        builder.button(text=f"1 шт. ({sell_unit_price} сыр.)", callback_data=f"inv_sellcf_{item_id}_1")
        if owned_qty >= 5:
            builder.button(text=f"5 шт. ({sell_unit_price * 5} сыр.)", callback_data=f"inv_sellcf_{item_id}_5")
        if owned_qty >= 10:
            builder.button(text=f"10 шт. ({sell_unit_price * 10} сыр.)", callback_data=f"inv_sellcf_{item_id}_10")
        if owned_qty >= 50:
            builder.button(text=f"50 шт. ({sell_unit_price * 50} сыр.)", callback_data=f"inv_sellcf_{item_id}_50")
        builder.button(text=f"Все ({owned_qty} шт. = {sell_unit_price * owned_qty} сыр.)", callback_data=f"inv_sellcf_{item_id}_all")

    builder.button(text="❌ Отмена", callback_data=f"inv_item_{item_id}")
    builder.adjust(1) if owned_qty == 1 else builder.adjust(2)
    
    await callback.message.edit_text(
        f"💰 <b>Продажа предмета:</b> <code>{info['name']}</code>\n"
        f"У вас в наличии: <b>{owned_qty} шт.</b>\n"
        f"Цена продажи: <b>{sell_unit_price}</b> сыр./шт.\n\n"
        f"Выберите количество для продажи:", 
        reply_markup=builder.as_markup()
    )

