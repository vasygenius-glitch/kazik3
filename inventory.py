from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from shop import ITEMS, MAX_BIZ_LEVEL
from user_manager import get_user_data, get_effective_chat_id
from typing import Optional

router = Router()

PAGE_SIZE = 15


def parse_owner_from_cb(data: str) -> tuple[str, Optional[int]]:
    parts = data.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])
    return data, None


def get_inventory_main_kb(inventory, biz_levels, meme_cards=None, page: int = 0, user_id: Optional[int] = None):
    builder = InlineKeyboardBuilder()
    uid_suffix = f"_{user_id}" if user_id is not None else ""

    # Кнопка открытия 12-часового кейса
    builder.button(text="🎁 Бесплатный кейс карт (12ч)", callback_data=f"open_free_case_cb{uid_suffix}")

    meme_cards = meme_cards or {}
    unique_cards = sum(1 for c, qty in meme_cards.items() if qty > 0)
    if unique_cards > 0:
        builder.button(text=f"🎴 Моя коллекция карт ({unique_cards}/200)", callback_data=f"card_page_0{uid_suffix}")

    valid_items = [(k, v) for k, v in inventory.items() if v > 0 and k in ITEMS]
    total_pages = max(1, (len(valid_items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    page_items = valid_items[start_idx:end_idx]

    for item_id, count in page_items:
        info = ITEMS[item_id]
        if info.get('action') == 'business':
            level = biz_levels.get(item_id, 1)
            text = f"{info['name']} (Ур. {level}) ({count} шт)"
        else:
            text = f"{info['name']} ({count} шт)"
        builder.button(text=text, callback_data=f"inv_item_{item_id}{uid_suffix}")

    if total_pages > 1:
        if page > 0:
            builder.button(text="⬅️ Назад", callback_data=f"inv_page_{page - 1}{uid_suffix}")
        else:
            builder.button(text="⛔️", callback_data="none")

        builder.button(text=f"📄 {page + 1}/{total_pages}", callback_data="none")

        if page < total_pages - 1:
            builder.button(text="Вперед ➡️", callback_data=f"inv_page_{page + 1}{uid_suffix}")
        else:
            builder.button(text="⛔️", callback_data="none")

    builder.button(text="❌ Закрыть", callback_data=f"inv_close{uid_suffix}")

    layout = [1]
    if unique_cards > 0:
        layout.append(1)
    layout.extend([1] * len(page_items))
    if total_pages > 1:
        layout.append(3)
    layout.append(1)
    builder.adjust(*layout)
    return builder.as_markup()


def get_item_kb(item_id: str, biz_level: int, user_id: Optional[int] = None):
    builder = InlineKeyboardBuilder()
    info = ITEMS.get(item_id)
    uid_suffix = f"_{user_id}" if user_id is not None else ""

    if info and info.get('action') == 'business':
        if biz_level < MAX_BIZ_LEVEL:
            upgrade_cost = int(info['price'] * 0.5 * biz_level)
            builder.button(text=f"⬆️ Улучшить ({upgrade_cost} сыр.)", callback_data=f"inv_upg_{item_id}{uid_suffix}")
        else:
            builder.button(text="🌟 Макс. уровень", callback_data="none")

    builder.button(text="💰 Продать", callback_data=f"inv_sell_{item_id}{uid_suffix}")
    builder.button(text="⬅️ Назад в инвентарь", callback_data=f"inv_main{uid_suffix}")
    builder.adjust(1)
    return builder.as_markup()


@router.message(Command("inventory", "inv", "инвентарь"))
async def cmd_inventory(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    data = await get_user_data(chat_id, user_id)
    if data.get('is_banned'):
        return

    inventory = data.get('inventory', {})
    biz_levels = data.get('biz_levels', {})
    meme_cards = data.get('meme_cards', {}) or {}

    has_items = any(count > 0 and item_id in ITEMS for item_id, count in inventory.items())
    unique_cards = sum(1 for c, qty in meme_cards.items() if qty > 0)

    if not has_items and unique_cards == 0:
        return await message.answer(
            "🎒 <b>Ваш инвентарь пуст.</b>\n\n"
            "Загляните в /cases, чтобы получить бесплатный 12-часовой кейс с карточками свинок!"
        )

    total_cards = sum(qty for qty in meme_cards.values() if qty > 0)
    text = "🎒 <b>ВАШ ИНВЕНТАРЬ И КОЛЛЕКЦИЯ</b>\n\n"
    if unique_cards > 0:
        text += f"🎴 <b>Коллекция карточек свинок:</b> <code>{unique_cards}/200</code> (всего {total_cards} шт.)\n\n"
    text += "Нажмите на предмет для управления или откройте карточки:"

    await message.answer(text, reply_markup=get_inventory_main_kb(inventory, biz_levels, meme_cards, user_id=user_id))


@router.callback_query(F.data.startswith("inv_main"))
async def inv_back(callback: types.CallbackQuery):
    _, owner_id = parse_owner_from_cb(callback.data)
    if owner_id is not None and callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваш инвентарь! Откройте свой через /inv", show_alert=True)

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = await get_user_data(chat_id, user_id)
    inventory = data.get('inventory', {})
    biz_levels = data.get('biz_levels', {})
    meme_cards = data.get('meme_cards', {}) or {}

    unique_cards = sum(1 for c, qty in meme_cards.items() if qty > 0)
    total_cards = sum(qty for qty in meme_cards.values() if qty > 0)

    text = "🎒 <b>ВАШ ИНВЕНТАРЬ И КОЛЛЕКЦИЯ</b>\n\n"
    if unique_cards > 0:
        text += f"🎴 <b>Коллекция карточек свинок:</b> <code>{unique_cards}/200</code> (всего {total_cards} шт.)\n\n"
    text += "Нажмите на предмет для управления или откройте карточки:"

    await callback.message.edit_text(text, reply_markup=get_inventory_main_kb(inventory, biz_levels, meme_cards, user_id=user_id))


@router.callback_query(F.data.startswith("inv_page_"))
async def inv_page_cb(callback: types.CallbackQuery):
    raw = callback.data.removeprefix("inv_page_")
    prefix, owner_id = parse_owner_from_cb(raw)
    if owner_id is not None and callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваш инвентарь! Откройте свой через /inv", show_alert=True)

    try:
        page = int(prefix)
    except ValueError:
        page = 0

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = await get_user_data(chat_id, user_id)
    inventory = data.get('inventory', {})
    biz_levels = data.get('biz_levels', {})
    meme_cards = data.get('meme_cards', {}) or {}

    unique_cards = sum(1 for c, qty in meme_cards.items() if qty > 0)
    total_cards = sum(qty for qty in meme_cards.values() if qty > 0)

    text = "🎒 <b>ВАШ ИНВЕНТАРЬ И КОЛЛЕКЦИЯ</b>\n\n"
    if unique_cards > 0:
        text += f"🎴 <b>Коллекция карточек свинок:</b> <code>{unique_cards}/200</code> (всего {total_cards} шт.)\n\n"
    text += "Нажмите на предмет для управления или откройте карточки:"

    await callback.message.edit_text(text, reply_markup=get_inventory_main_kb(inventory, biz_levels, meme_cards, page=page, user_id=user_id))


@router.callback_query(F.data.startswith("inv_close"))
async def inv_close(callback: types.CallbackQuery):
    _, owner_id = parse_owner_from_cb(callback.data)
    if owner_id is not None and callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваш инвентарь!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        await callback.answer("Закрыто.")


@router.callback_query(F.data.startswith("inv_item_"))
async def inv_item_info(callback: types.CallbackQuery):
    raw = callback.data.removeprefix("inv_item_")
    item_id, owner_id = parse_owner_from_cb(raw)
    if owner_id is not None and callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваш инвентарь! Откройте свой через /inv", show_alert=True)

    info = ITEMS.get(item_id)
    if not info:
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = await get_user_data(chat_id, user_id)
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

    await callback.message.edit_text(text, reply_markup=get_item_kb(item_id, biz_levels.get(item_id, 1), user_id=user_id))


@router.callback_query(F.data == "none")
async def dummy_callback(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("inv_upg_"))
async def inv_upgrade(callback: types.CallbackQuery):
    raw = callback.data.removeprefix("inv_upg_")
    item_id, owner_id = parse_owner_from_cb(raw)
    if owner_id is not None and callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваш инвентарь!", show_alert=True)

    info = ITEMS.get(item_id)
    if not info or info.get('action') != 'business':
        return

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
        callback.data = f"inv_item_{item_id}_{user_id}"
        await inv_item_info(callback)

    except Exception as e:
        print(f"Upgrade error: {e}")
        return await callback.answer("Ошибка при улучшении.", show_alert=True)


@router.callback_query(F.data.startswith("inv_sellcf_"))
async def confirm_inv_sell(callback: types.CallbackQuery):
    raw_data = callback.data.removeprefix("inv_sellcf_")
    parts = raw_data.split("_")
    # format: inv_sellcf_{item_id}_{count}_{owner_id} or inv_sellcf_{item_id}_{count}
    if len(parts) >= 3 and parts[-1].isdigit():
        owner_id = int(parts[-1])
        req_count_str = parts[-2]
        item_id = "_".join(parts[:-2])
    elif len(parts) >= 2:
        owner_id = None
        req_count_str = parts[-1]
        item_id = "_".join(parts[:-1])
    else:
        owner_id = None
        item_id = raw_data
        req_count_str = "1"

    if owner_id is not None and callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваш инвентарь!", show_alert=True)

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
        if not snapshot.exists:
            return False, 0, 0

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
        base_unit_price = int(item_info['price'] * 0.75)
        upgrade_refund = 0
        if item_info.get('action') == 'business':
            level = biz_levels.get(item_id, 1)
            upgrade_invested = sum(int(item_info['price'] * 0.5 * l) for l in range(1, level))
            if sell_count >= owned_qty:
                upgrade_refund = int(upgrade_invested * 0.75)

        total_payout = (base_unit_price * sell_count) + upgrade_refund
        success = await sell_item_tr(transaction, chat_id, user_id, item_id, item_info.get('cat', ''), base_unit_price, count=sell_count, total_payout=total_payout)
        return success, total_payout, sell_count

    try:
        from user_manager import get_user_lock, invalidate_user_cache
        lock = get_user_lock(chat_id, user_id)
        async with lock:
            res = run_sell_transaction(db.transaction(), chat_id, user_id, item_id, info, req_count_str)
            if hasattr(res, "__aiter__"):
                async for r in res:
                    success, total_payout, sold_count = r
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
    raw = callback.data.removeprefix("inv_sell_")
    item_id, owner_id = parse_owner_from_cb(raw)
    if owner_id is not None and callback.from_user.id != owner_id:
        return await callback.answer("⚠️ Это не ваш инвентарь!", show_alert=True)

    info = ITEMS.get(item_id)
    if not info:
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    u_data = await get_user_data(chat_id, user_id)
    inv = u_data.get('inventory', {})
    owned_qty = inv.get(item_id, 0)

    if owned_qty <= 0:
        return await callback.answer("У вас нет этого предмета!", show_alert=True)

    base_unit_price = int(info['price'] * 0.75)
    upgrade_refund = 0
    if info.get('action') == 'business':
        biz_levels = u_data.get('biz_levels', {})
        level = biz_levels.get(item_id, 1)
        upgrade_invested = sum(int(info['price'] * 0.5 * l) for l in range(1, level))
        upgrade_refund = int(upgrade_invested * 0.75)

    uid_suffix = f"_{user_id}"
    builder = InlineKeyboardBuilder()
    if owned_qty == 1:
        total_payout_1 = base_unit_price + upgrade_refund
        builder.button(text=f"✅ Продать 1 шт. ({total_payout_1} сыр.)", callback_data=f"inv_sellcf_{item_id}_1{uid_suffix}")
    else:
        builder.button(text=f"1 шт. ({base_unit_price} сыр.)", callback_data=f"inv_sellcf_{item_id}_1{uid_suffix}")
        if owned_qty >= 5:
            payout_5 = (base_unit_price * 5) + (upgrade_refund if owned_qty == 5 else 0)
            builder.button(text=f"5 шт. ({payout_5} сыр.)", callback_data=f"inv_sellcf_{item_id}_5{uid_suffix}")
        if owned_qty >= 10:
            payout_10 = (base_unit_price * 10) + (upgrade_refund if owned_qty == 10 else 0)
            builder.button(text=f"10 шт. ({payout_10} сыр.)", callback_data=f"inv_sellcf_{item_id}_10{uid_suffix}")
        if owned_qty >= 50:
            payout_50 = (base_unit_price * 50) + (upgrade_refund if owned_qty == 50 else 0)
            builder.button(text=f"50 шт. ({payout_50} сыр.)", callback_data=f"inv_sellcf_{item_id}_50{uid_suffix}")
        payout_all = (base_unit_price * owned_qty) + upgrade_refund
        builder.button(text=f"Все ({owned_qty} шт. = {payout_all} сыр.)", callback_data=f"inv_sellcf_{item_id}_all{uid_suffix}")

    builder.button(text="❌ Отмена", callback_data=f"inv_item_{item_id}{uid_suffix}")
    builder.adjust(1) if owned_qty == 1 else builder.adjust(2)

    upgrade_note = f"\n<i>Включает возврат за улучшения при продаже всех шт.: {upgrade_refund} сыр.</i>" if upgrade_refund > 0 else ""
    await callback.message.edit_text(
        f"💰 <b>Продажа предмета:</b> <code>{info['name']}</code>\n"
        f"У вас в наличии: <b>{owned_qty} шт.</b>\n"
        f"Базовая цена продажи: <b>{base_unit_price}</b> сыр./шт.{upgrade_note}\n\n"
        f"Выберите количество для продажи:",
        reply_markup=builder.as_markup()
    )
