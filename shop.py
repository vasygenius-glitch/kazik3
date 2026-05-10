from aiogram import Router, F, types
from aiogram.filters import Command
import time
from aiogram.utils.keyboard import InlineKeyboardBuilder
from user_manager import get_user_data, update_user_balance, add_item_to_inventory, update_user_field
from economy_utils import calculate_progressive_tax, get_global_tax
from escape import escape_html
from seasons import get_season_string

router = Router()

ITEMS = {
    # БИЗНЕСЫ (Окупаемость - 10 сборов)
    "шаурма": {"name": "🏪 Ларёк с шаурмой", "price": 100000, "cat": "biz", "action": "business", "income": 10000},
    "мойка": {"name": "🚿 Автомойка", "price": 500000, "cat": "biz", "action": "business", "income": 50000},
    "вендинг": {"name": "🍬 Вендинг", "price": 800000, "cat": "biz", "action": "business", "income": 80000},
    "кофейня": {"name": "☕️ Кофейня", "price": 1500000, "cat": "biz", "action": "business", "income": 150000},
    "ресторан": {"name": "🍽 Ресторан", "price": 3000000, "cat": "biz", "action": "business", "income": 300000},
    "отель": {"name": "🏨 Отель", "price": 7000000, "cat": "biz", "action": "business", "income": 700000},
    "ферма": {"name": "🌽 Ферма", "price": 12000000, "cat": "biz", "action": "business", "income": 1200000},
    "завод": {"name": "🏭 Завод", "price": 25000000, "cat": "biz", "action": "business", "income": 2500000},
    "салон": {"name": "🚙 Автосалон", "price": 50000000, "cat": "biz", "action": "business", "income": 5000000},
    "нефть": {"name": "🛢 Вышка", "price": 100000000, "cat": "biz", "action": "business", "income": 10000000},
    "банк": {"name": "🏦 Банк", "price": 250000000, "cat": "biz", "action": "business", "income": 25000000},
    "айти": {"name": "💻 IT-компания", "price": 500000000, "cat": "biz", "action": "business", "income": 50000000},
    "казино": {"name": "🎰 Казино", "price": 1000000000, "cat": "biz", "action": "business", "income": 100000000},
    "космодром": {"name": "🚀 Космодром", "price": 5000000000, "cat": "biz", "action": "business", "income": 500000000},
    "планета": {"name": "🪐 Колония", "price": 10000000000, "cat": "biz", "action": "business", "income": 1000000000},
    
    # МАШИНЫ
    "лада": {"name": "🚗 Lada Priora", "price": 50000, "cat": "cars", "action": "car", "income": 2000},
    "камри": {"name": "🚙 Toyota Camry", "price": 150000, "cat": "cars", "action": "car", "income": 7000},
    "бмв": {"name": "🚕 BMW M5", "price": 500000, "cat": "cars", "action": "car", "income": 20000},
    "гелик": {"name": "⬛️ Geländewagen", "price": 1200000, "cat": "cars", "action": "car", "income": 50000},
    "бугатти": {"name": "🏎 Bugatti Chiron", "price": 5000000, "cat": "cars", "action": "car", "income": 200000},
    "самолет": {"name": "🛩 Частный Jet", "price": 50000000, "cat": "cars", "action": "car", "income": 2500000},
    
    # ПРОЧЕЕ
    "вип": {"name": "💎 Статус VIP", "price": 1000000, "cat": "other", "action": "other"},
    "антиварн": {"name": "💊 Снять варн", "price": 250000, "cat": "other", "action": "other"},
    "condom": {"name": "🎈 Презерватив", "price": 340, "cat": "other", "action": "other"}
}

async def get_main_shop_kb():
    biz_label = await get_season_string("shop_biz", "🏢 Бизнесы")
    cars_label = await get_season_string("shop_cars", "🚗 Машины")
    
    builder = InlineKeyboardBuilder()
    builder.button(text=biz_label, callback_data="shop_cat_biz")
    builder.button(text=cars_label, callback_data="shop_cat_cars")
    builder.button(text="💎 Прочее", callback_data="shop_cat_other")
    builder.button(text="🎒 Мой инвентарь", callback_data="shop_to_inv")
    builder.adjust(2, 2)
    return builder.as_markup()

def get_sell_menu_kb(inventory, is_vip):
    builder = InlineKeyboardBuilder()
    has_items = False

    for item_id, count in inventory.items():
        if count > 0 and item_id in ITEMS:
            info = ITEMS[item_id]
            sell_price = int(info['price'] * 0.75)
            builder.button(text=f"Продать: {info['name']} ({count} шт) - {sell_price} сыр.", callback_data=f"sell_ask_{item_id}")
            has_items = True

    if is_vip:
        info = ITEMS["вип"]
        sell_price = int(info['price'] * 0.75)
        builder.button(text=f"Продать: {info['name']} - {sell_price} сыр.", callback_data="sell_ask_вип")
        has_items = True

    builder.button(text="⬅️ Назад", callback_data="shop_main")
    builder.adjust(1)
    return builder.as_markup(), has_items

def get_sell_confirm_kb(item_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, продать", callback_data=f"sell_confirm_{item_id}")
    builder.button(text="❌ Отмена", callback_data="shop_sell_menu")
    builder.adjust(2)
    return builder.as_markup()

def get_category_kb(category, balance, base_tax, negotiation_skill=0):
    builder = InlineKeyboardBuilder()
    tax_rate = calculate_progressive_tax(balance, base_tax, negotiation_skill)
    
    for item_id, info in ITEMS.items():
        if info.get('cat') == category:
            markup = int(info['price'] * (tax_rate / 100.0))
            final_price = info['price'] + markup
            builder.button(text=f"{info['name']} - {final_price} сыр.", callback_data=f"buy_{item_id}")
    builder.button(text="⬅️ Назад", callback_data="shop_main")
    builder.adjust(1)
    return builder.as_markup()

@router.message(Command("shop"))
async def cmd_shop(message: types.Message):
    data = await get_user_data(message.chat.id, message.from_user.id)

    if data.get('is_banned'): return

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(message.chat.id, message.from_user.id)
    if 'ureaplasmosis' in active_diseases:
        return await message.answer("🦠 <b>Уреаплазмоз</b>: Продавцы боятся заразиться и не пускают вас в магазин!")

    debts = data.get('debts', {})
    current_time = time.time()
    has_overdue_debt = False

    for k, v in debts.items():
        if k.startswith("bank_") and v > 0:
            parts = k.split("_")
            if len(parts) >= 3:
                due_date = int(parts[2])
                if current_time > due_date:
                    has_overdue_debt = True
                    break

    warning_text = ""
    if has_overdue_debt:
        warning_text = "\n\n⚠️ <b>ВНИМАНИЕ: На вас наложен арест за просроченный долг! Вы не можете покупать новые вещи, но можете продать старые для погашения долга.</b>"

    base_tax = await get_global_tax()
    tax_rate = calculate_progressive_tax(data.get('balance', 0), base_tax, data.get('skills', {}).get('negotiation', 0))

    shop_title = await get_season_string("shop", "🛒 Магазин Сыроежек")
    
    await message.answer(
        f"<b>{shop_title}</b>\n\n"
        f"Твой баланс: <b>{data.get('balance', 0)}</b> сыр.\n"
        f"📈 Твоя наценка (Налог на роскошь): <b>{tax_rate}%</b>{warning_text}\n"
        "Выберите категорию товаров:",
        reply_markup=await get_main_shop_kb()
    )

@router.callback_query(F.data == "shop_main")
async def shop_back(callback: types.CallbackQuery):
    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    base_tax = await get_global_tax()
    tax_rate = calculate_progressive_tax(data.get('balance', 0), base_tax, data.get('skills', {}).get('negotiation', 0))
    
    text = (f"🛒 <b>МАГАЗИН СЫРОЕДА</b>\n\n"
            f"Твой баланс: <b>{data.get('balance', 0)}</b> сыр.\n"
            f"📈 Твоя наценка: <b>{tax_rate}%</b>\n"
            f"Выбери категорию:")
    await callback.message.edit_text(text, reply_markup=get_main_shop_kb())

@router.callback_query(F.data == "shop_to_inv")
async def shop_to_inv(callback: types.CallbackQuery):
    await callback.answer("🎒 Для управления имуществом, продажи и улучшения бизнесов введи команду /inv !", show_alert=True)

@router.callback_query(F.data.startswith("shop_cat_"))
async def show_category(callback: types.CallbackQuery):
    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    base_tax = await get_global_tax()
    
    category = callback.data.replace("shop_cat_", "")
    cats_names = {"biz": "Бизнесы", "cars": "Машины", "other": "Разное"}
    
    text = f"📂 <b>Категория: {cats_names.get(category)}</b>\n\nВыбери товар для покупки (цены указаны с учетом твоего налога):"
    await callback.message.edit_text(text, reply_markup=get_category_kb(category, data.get('balance', 0), base_tax, data.get('skills', {}).get('negotiation', 0)))

@router.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    item_id = callback.data.replace("buy_", "")
    item = ITEMS.get(item_id)
    if not item: return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    data = await get_user_data(chat_id, user_id)

    debts = data.get('debts', {})
    current_time = time.time()
    has_overdue_debt = False

    for k, v in debts.items():
        if k.startswith("bank_") and v > 0:
            parts = k.split("_")
            if len(parts) >= 3:
                due_date = int(parts[2])
                if current_time > due_date:
                    has_overdue_debt = True
                    break

    if has_overdue_debt:
        return await callback.answer("❌ У вас просроченный долг! Покупки запрещены.", show_alert=True)

    base_tax = await get_global_tax()
    tax_rate = calculate_progressive_tax(data.get('balance', 0), base_tax, data.get('skills', {}).get('negotiation', 0))
    final_price = item['price'] + int(item['price'] * (tax_rate / 100.0))

    if data.get('balance', 0) < final_price:
        return await callback.answer(f"Недостаточно денег! Твоя цена: {final_price} сыр.", show_alert=True)

    if item.get('cat') == "biz":
        limit = 4 if data.get('is_vip') else 2
        inv = data.get('inventory', {})
        biz_count = sum(1 for k in inv if ITEMS.get(k, {}).get('cat') == 'biz')
        
        if item_id in inv:
            return await callback.answer("У тебя уже есть этот бизнес!", show_alert=True)
        if biz_count >= limit:
            return await callback.answer(f"Лимит бизнесов ({limit}) достигнут!", show_alert=True)

    await update_user_balance(chat_id, user_id, -final_price)
    
    if item_id == "вип":
        await update_user_field(chat_id, user_id, 'is_vip', True)
    else:
        await add_item_to_inventory(chat_id, user_id, item_id)

    await callback.answer(f"Куплено: {item['name']}!", show_alert=True)
    await show_category(callback)
@router.callback_query(F.data == "shop_sell_menu")
async def show_sell_menu(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    data = await get_user_data(chat_id, user_id)

    inventory = data.get('inventory', {})
    is_vip = data.get('is_vip', False)

    kb, has_items = get_sell_menu_kb(inventory, is_vip)

    if not has_items:
        text = "🤷‍♂️ У вас нет имущества для продажи."
    else:
        text = "💰 <b>ПРОДАЖА ИМУЩЕСТВА</b>\n\nВыбери предмет, который хочешь продать (ты получишь 75% от его стоимости):"

    await callback.message.edit_text(text, reply_markup=kb)

@router.callback_query(F.data.startswith("sell_ask_"))
async def ask_sell_confirm(callback: types.CallbackQuery):
    item_id = callback.data.replace("sell_ask_", "")
    item = ITEMS.get(item_id)
    if not item: return

    sell_price = int(item['price'] * 0.75)
    text = f"❓ Вы уверены, что хотите продать <b>{item['name']}</b> за <b>{sell_price}</b> сыр.?"

    await callback.message.edit_text(text, reply_markup=get_sell_confirm_kb(item_id))

@router.callback_query(F.data.startswith("sell_confirm_"))
async def process_sell_confirm(callback: types.CallbackQuery):
    item_id = callback.data.replace("sell_confirm_", "")
    item = ITEMS.get(item_id)
    if not item: return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    data = await get_user_data(chat_id, user_id)

    # Verify user still has the item
    if item_id == "вип":
        if not data.get('is_vip'):
            return await callback.answer("У вас больше нет VIP статуса!", show_alert=True)
        await update_user_field(chat_id, user_id, 'is_vip', False)
    else:
        from user_manager import remove_item_from_inventory
        success = await remove_item_from_inventory(chat_id, user_id, item_id)
        if not success:
            return await callback.answer("Предмет не найден в вашем инвентаре!", show_alert=True)

    sell_price = int(item['price'] * 0.75)
    await update_user_balance(chat_id, user_id, sell_price)

    await callback.answer(f"✅ Успешно продано за {sell_price} сыр.!", show_alert=True)
    await show_sell_menu(callback)
