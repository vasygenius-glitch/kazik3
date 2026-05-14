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
    "шаурма": {"name": "🏪 Ларёк с шаурмой", "price": 25000, "cat": "biz", "action": "business", "income": 2500},
    "мойка": {"name": "🚿 Автомойка", "price": 125000, "cat": "biz", "action": "business", "income": 12500},
    "вендинг": {"name": "🍬 Вендинг", "price": 200000, "cat": "biz", "action": "business", "income": 20000},
    "кофейня": {"name": "☕️ Кофейня", "price": 375000, "cat": "biz", "action": "business", "income": 37500},
    "ресторан": {"name": "🍽 Ресторан", "price": 750000, "cat": "biz", "action": "business", "income": 75000},
    "отель": {"name": "🏨 Отель", "price": 1750000, "cat": "biz", "action": "business", "income": 175000},
    "ферма": {"name": "🌽 Ферма", "price": 3000000, "cat": "biz", "action": "business", "income": 300000},
    "завод": {"name": "🏭 Завод", "price": 6250000, "cat": "biz", "action": "business", "income": 625000},
    "салон": {"name": "🚙 Автосалон", "price": 12500000, "cat": "biz", "action": "business", "income": 1250000},
    "нефть": {"name": "🛢 Вышка", "price": 25000000, "cat": "biz", "action": "business", "income": 2500000},
    "банк": {"name": "🏦 Банк", "price": 62500000, "cat": "biz", "action": "business", "income": 6250000},
    "айти": {"name": "💻 IT-компания", "price": 125000000, "cat": "biz", "action": "business", "income": 12500000},
    "казино": {"name": "🎰 Казино", "price": 250000000, "cat": "biz", "action": "business", "income": 25000000},
    "космодром": {"name": "🚀 Космодром", "price": 1250000000, "cat": "biz", "action": "business", "income": 125000000},
    "планета": {"name": "🪐 Колония", "price": 2500000000, "cat": "biz", "action": "business", "income": 250000000},
    
    # МАШИНЫ
    "лада": {"name": "🚗 Lada Priora", "price": 12500, "cat": "cars", "action": "car", "income": 500},
    "камри": {"name": "🚙 Toyota Camry", "price": 37500, "cat": "cars", "action": "car", "income": 1750},
    "бмв": {"name": "🚕 BMW M5", "price": 125000, "cat": "cars", "action": "car", "income": 5000},
    "гелик": {"name": "⬛️ Geländewagen", "price": 300000, "cat": "cars", "action": "car", "income": 12500},
    "бугатти": {"name": "🏎 Bugatti Chiron", "price": 1250000, "cat": "cars", "action": "car", "income": 50000},
    "самолет": {"name": "🛩 Частный Jet", "price": 12500000, "cat": "cars", "action": "car", "income": 625000},
    
    # ПРОЧЕЕ
    "вип": {"name": "💎 Статус VIP", "price": 1000000, "cat": "other", "action": "other"},
    "антиварн": {"name": "💊 Снять варн", "price": 250000, "cat": "other", "action": "other"},
    "condom": {"name": "🎈 Презерватив", "price": 340, "cat": "other", "action": "other"}
}

# Кэш для кнопок магазина (чтобы не авейтить каждый раз сезонные строки)
_shop_kb_cache = {"biz": "🏢 Бизнесы", "cars": "🚗 Машины", "ts": 0}

async def get_main_shop_kb():
    global _shop_kb_cache
    if time.time() - _shop_kb_cache["ts"] > 60:
        _shop_kb_cache["biz"] = await get_season_string("shop_biz", "🏢 Бизнесы")
        _shop_kb_cache["cars"] = await get_season_string("shop_cars", "🚗 Машины")
        _shop_kb_cache["ts"] = time.time()
    
    builder = InlineKeyboardBuilder()
    builder.button(text=_shop_kb_cache["biz"], callback_data="shop_cat_biz")
    builder.button(text=_shop_kb_cache["cars"], callback_data="shop_cat_cars")
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
    from economy_utils import calculate_biz_markup
    tax_rate = calculate_progressive_tax(balance, base_tax, negotiation_skill)
    
    for item_id, info in ITEMS.items():
        if info.get('cat') == category:
            # Считаем обычный налог
            markup = int(info['price'] * (tax_rate / 100.0))

            # Налог на роскошь для бизнесов
            if category == "biz":
                biz_markup_percent = calculate_biz_markup(balance)
                markup += int(info['price'] * (biz_markup_percent / 100.0))

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
    pet_data = data.get('pet', {})
    pet_id = pet_data.get('id') if isinstance(pet_data, dict) else None
    tax_rate = calculate_progressive_tax(data.get('balance', 0), base_tax, data.get('skills', {}).get('negotiation', 0), pet_id)

    shop_title = await get_season_string("shop", "🛒 Магазин Сыроежек")
    from seasons import get_glitch_text
    shop_title = await get_glitch_text(shop_title)
    
    await message.answer(
        f"<b>{shop_title}</b>\n\n"
        f"Твой баланс: <b>{data.get('balance', 0)}</b> сыр.\n"
        f"📈 Твоя наценка (Налог на роскошь): <b>{tax_rate}%</b>{warning_text}\n"
        "Выберите категорию товаров:",
        reply_markup=await get_main_shop_kb()
    )

@router.callback_query(F.data == "shop_main")
async def shop_back(callback: types.CallbackQuery):
    await callback.answer()
    data = await get_user_data(callback.message.chat.id, callback.from_user.id)
    base_tax = await get_global_tax()
    pet_data = data.get('pet', {})
    pet_id = pet_data.get('id') if isinstance(pet_data, dict) else None
    tax_rate = calculate_progressive_tax(data.get('balance', 0), base_tax, data.get('skills', {}).get('negotiation', 0), pet_id)
    
    text = (f"🛒 <b>МАГАЗИН СЫРОЕДА</b>\n\n"
            f"Твой баланс: <b>{data.get('balance', 0)}</b> сыр.\n"
            f"📈 Твоя наценка: <b>{tax_rate}%</b>\n"
            f"Выбери категорию:")
    await callback.message.edit_text(text, reply_markup=await get_main_shop_kb())

@router.callback_query(F.data == "shop_to_inv")
async def shop_to_inv(callback: types.CallbackQuery):
    await callback.answer("🎒 Для управления имуществом, продажи и улучшения бизнесов введи команду /inv !", show_alert=True)

@router.callback_query(F.data.startswith("shop_cat_"))
async def show_category(callback: types.CallbackQuery):
    await callback.answer()
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
    pet_data = data.get('pet', {})
    pet_id = pet_data.get('id') if isinstance(pet_data, dict) else None

    balance = data.get('balance', 0)
    tax_rate = calculate_progressive_tax(balance, base_tax, data.get('skills', {}).get('negotiation', 0), pet_id)

    markup = int(item['price'] * (tax_rate / 100.0))
    if item.get('cat') == "biz":
        from economy_utils import calculate_biz_markup
        biz_markup_percent = calculate_biz_markup(balance)
        markup += int(item['price'] * (biz_markup_percent / 100.0))

    final_price = item['price'] + markup

    if data.get('balance', 0) < final_price:
        return await callback.answer(f"Недостаточно денег! Твоя цена: {final_price} сыр.", show_alert=True)

    # Confirmation for expensive items
    if final_price > 1000000 and not callback.data.startswith("buy_conf_"):
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Да, купить", callback_data=f"buy_conf_{item_id}")
        builder.button(text="❌ Отмена", callback_data=f"shop_cat_{item.get('cat', 'other')}")
        builder.adjust(1)
        return await callback.message.edit_text(
            f"❓ Вы уверены, что хотите купить <b>{item['name']}</b> за <b>{final_price}</b> сыр.?",
            reply_markup=builder.as_markup()
        )

    if item.get('cat') == "biz":
        limit = 4 if data.get('is_vip') else 2
        inv = data.get('inventory', {})
        biz_count = sum(1 for k in inv if ITEMS.get(k, {}).get('cat') == 'biz')
        
        if item_id in inv:
            return await callback.answer("У тебя уже есть этот бизнес!", show_alert=True)
        if biz_count >= limit:
            return await callback.answer(f"Лимит бизнесов ({limit}) достигнут!", show_alert=True)

    from db import get_db
    from user_manager import buy_item_tr
    from firebase_admin import firestore_async
    
    db = get_db()
    
    @firestore_async.transactional
    async def run_buy_transaction(transaction, chat_id, user_id, item_id, price, is_vip):
        return await buy_item_tr(transaction, chat_id, user_id, item_id, price, is_vip)

    try:
        is_vip_buy = (item_id == "вип")
        res = run_buy_transaction(db.transaction(), chat_id, user_id, item_id, final_price, is_vip_buy)
        if hasattr(res, "__aiter__"):
            async for r in res: success, error_msg = r
        else:
            success, error_msg = await res
            
        if not success:
            return await callback.answer(f"Ошибка: {error_msg}", show_alert=True)
            
    except Exception as e:
        print(f"Buy error: {e}")
        return await callback.answer("Ошибка при покупке.", show_alert=True)

    await callback.answer(f"Куплено: {item['name']}!", show_alert=True)
    await show_category(callback)

@router.callback_query(F.data.startswith("buy_conf_"))
async def process_buy_confirm(callback: types.CallbackQuery):
    callback.data = callback.data.replace("buy_conf_", "buy_")
    await process_buy(callback)

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

    sell_price = int(item['price'] * 0.75)

    # Verify user still has the item
    if item_id == "вип":
        if not data.get('is_vip'):
            return await callback.answer("У вас больше нет VIP статуса!", show_alert=True)
        await update_user_field(chat_id, user_id, 'is_vip', False)
        await update_user_balance(chat_id, user_id, sell_price)
    else:
        from db import get_db
        from user_manager import sell_item_tr
        from firebase_admin import firestore_async

        db = get_db()

        @firestore_async.transactional
        async def run_sell_transaction(transaction, chat_id, user_id, item_id, item_cat, sell_price):
            return await sell_item_tr(transaction, chat_id, user_id, item_id, item_cat, sell_price)

        try:
            res = run_sell_transaction(db.transaction(), chat_id, user_id, item_id, item.get('cat', ''), sell_price)
            if hasattr(res, "__aiter__"):
                async for r in res: success = r
            else:
                success = await res
        except Exception:
            return await callback.answer('Произошла ошибка при продаже предмета. Попробуйте еще раз.', show_alert=True)

        if not success:
            return await callback.answer("Предмет не найден в вашем инвентаре!", show_alert=True)

    await callback.answer(f"✅ Успешно продано за {sell_price} сыр.!", show_alert=True)
    await show_sell_menu(callback)
