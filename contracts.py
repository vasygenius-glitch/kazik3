import time
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from escape import escape_html
from user_manager import get_user_data, update_user_balance, update_user_field

router = Router()
active_deals = {}

# 1. ПРОСТОЙ ДОГОВОР (Словесный)
@router.message(F.text.lower().startswith("договор"))
async def cmd_contract(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("Сделай реплай на того, с кем заключаешь договор.")

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(message.chat.id, message.from_user.id)
    if 'donovanosis' in active_diseases:
        return await message.answer("🦠 <b>Донованоз</b>: Строгий запрет на заключение договоров. Партнер боится подписывать с вами бумаги.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("Напиши суть договора: договор [текст]")

    text = parts[1]
    deal_id = f"con_{int(time.time() * 1000)}"[-10:]
    
    active_deals[deal_id] = {
        'type': 'contract',
        'text': text,
        'from_id': message.from_user.id,
        'to_id': message.reply_to_message.from_user.id
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="Подписать ✍️", callback_data=f"deal_yes_{deal_id}")
    builder.button(text="Отказаться ❌", callback_data=f"deal_no_{deal_id}")

    await message.answer(
        f"📜 <b>ОФИЦИАЛЬНЫЙ ДОГОВОР</b>\n\n"
        f"Между <b>{escape_html(message.from_user.full_name)}</b> и <b>{escape_html(message.reply_to_message.from_user.full_name)}</b>\n\n"
        f"<b>Суть:</b> {escape_html(text)}\n\n"
        f"Второй стороне нужно подписать документ.",
        reply_markup=builder.as_markup()
    )

# 2. СДЕЛКА (Деньги + Имущество)
@router.message(F.text.lower().startswith("сделка"))
async def cmd_deal(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("Сделай реплай на партнера по сделке.")

    args = message.text.split()
    # формат: сделка [цена] [предмет] [условие/натура]
    if len(args) < 3:
        return await message.answer("Использование: сделка [цена] [предмет] [доп. условия]")

    try:
        price = int(args[1])
        if price <= 0:
            return await message.answer("Цена должна быть больше нуля.")
        item_name = args[2].lower()
        condition = " ".join(args[3:]) if len(args) > 3 else "Нет"
    except Exception: return

    chat_id = message.chat.id
    seller_id = message.from_user.id
    buyer_id = message.reply_to_message.from_user.id

    # Проверка наличия предмета у продавца
    seller_data = await get_user_data(chat_id, seller_id)
    if item_name not in seller_data.get('inventory', {}):
        return await message.answer(f"У тебя нет предмета '{item_name}' в инвентаре.")

    deal_id = f"sell_{int(time.time() * 1000)}"[-10:]
    active_deals[deal_id] = {
        'type': 'trade',
        'price': price,
        'item': item_name,
        'condition': condition,
        'from_id': seller_id,
        'to_id': buyer_id
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="Принять сделку ✅", callback_data=f"deal_yes_{deal_id}")
    builder.button(text="Отмена ❌", callback_data=f"deal_no_{deal_id}")

    await message.answer(
        f"🤝 <b>КУПЛЯ-ПРОДАЖА</b>\n\n"
        f"Продавец: <b>{escape_html(message.from_user.full_name)}</b>\n"
        f"Покупатель: <b>{escape_html(message.reply_to_message.from_user.full_name)}</b>\n\n"
        f"📦 Предмет: <b>{item_name}</b>\n"
        f"💰 Цена: <b>{price}</b> сыр.\n"
        f"📝 Доп. условия: {escape_html(condition)}\n\n"
        f"Покупатель, ты согласен?",
        reply_markup=builder.as_markup()
    )

# 3. НАСЛЕДСТВО
@router.message(F.text.lower().startswith("наследство"))
async def cmd_will(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("Сделай реплай на того, кому передаешь всё имущество.")

    deal_id = f"will_{int(time.time() * 1000)}"[-10:]
    chat_id = message.chat.id
    sender_id = message.from_user.id
    sender_data = await get_user_data(chat_id, sender_id)
    
    if sender_data.get('balance', 0) < 0 or sender_data.get('bank_deposit', 0) < 0:
        return await message.answer("❌ Нельзя передать наследство с долгами! Сначала закройте свои кредиты.")

    active_deals[deal_id] = {
        'type': 'inheritance',
        'from_id': sender_id,
        'to_id': message.reply_to_message.from_user.id
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="Принять всё 🏰", callback_data=f"deal_yes_{deal_id}")
    builder.button(text="Отказаться 🚫", callback_data=f"deal_no_{deal_id}")

    await message.answer(
        f"⚰️ <b>ПЕРЕДАЧА НАСЛЕДСТВА</b>\n\n"
        f"<b>{escape_html(message.from_user.full_name)}</b> хочет передать ВСЁ своё имущество (деньги, банк, инвентарь) пользователю <b>{escape_html(message.reply_to_message.from_user.full_name)}</b>.\n\n"
        f"Это действие нельзя отменить. Ты принимаешь дар?",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("deal_yes_") | F.data.startswith("deal_no_"))
async def process_all_deals(callback: types.CallbackQuery):
    action = callback.data.split("_")[1]
    deal_id = callback.data.split("_")[2]

    if deal_id not in active_deals:
        return await callback.answer("Сделка просрочена.", show_alert=True)

    info = active_deals.pop(deal_id)
    chat_id = callback.message.chat.id

    if callback.from_user.id != info['to_id']:
        return await callback.answer("Эта кнопка не для тебя!", show_alert=True)

    if action == "no":
        return await callback.message.edit_text("❌ Сделка отклонена второй стороной.")

    # ЛОГИКА ПОДТВЕРЖДЕНИЯ
    if info['type'] == 'contract':
        await callback.message.edit_text(f"✅ <b>Договор подписан обеими сторонами!</b>\n\nСуть: {info['text']}")

    elif info['type'] == 'trade':
        buyer_id = info['to_id']
        seller_id = info['from_id']
        price = info['price']
        item = info['item']

        # Сначала списываем деньги у покупателя с защитой от ухода в минус
        res = await update_user_balance(chat_id, buyer_id, -price, min_balance=0)
        if res is None:
            return await callback.message.edit_text("❌ У покупателя не хватило денег!")

        # Передача предмета
        from user_manager import remove_item_from_inventory, add_item_to_inventory
        if await remove_item_from_inventory(chat_id, seller_id, item):
            await update_user_balance(chat_id, seller_id, price)
            await add_item_to_inventory(chat_id, buyer_id, item)

            # --- Логирование сделки ---
            try:
                seller_data_after = await get_user_data(chat_id, seller_id)
                buyer_data_after = await get_user_data(chat_id, buyer_id)
                seller_name = seller_data_after.get('full_name', 'Unknown')
                seller_username = seller_data_after.get('username', '')
                buyer_name = buyer_data_after.get('full_name', 'Unknown')
                buyer_username = buyer_data_after.get('username', '')
                try:
                    message_link = callback.message.link or ""
                except Exception:
                    message_link = ""
                
                from log_system import log_trade
                log_trade(
                    chat_id=chat_id,
                    chat_title=callback.message.chat.title or "Unknown",
                    seller_id=seller_id,
                    seller_name=seller_name,
                    seller_username=seller_username,
                    buyer_id=buyer_id,
                    buyer_name=buyer_name,
                    buyer_username=buyer_username,
                    item_name=item,
                    price=price,
                    message_link=message_link
                )
            except Exception as log_e:
                print(f"Error logging trade: {log_e}")

            await callback.message.edit_text(f"✅ <b>Сделка завершена!</b>\nПредмет <b>{item}</b> перешел к новому владельцу за <b>{price}</b> сыр.")
        else:
            # Возвращаем деньги покупателю
            await update_user_balance(chat_id, buyer_id, price)
            await callback.message.edit_text("❌ Произошла ошибка: предмета больше нет у продавца.")

    elif info['type'] == 'inheritance':
        sender_id = info['from_id']
        target_id = info['to_id']

        # Избегаем дедлоков, блокируя пользователей в строго упорядоченном виде по ID
        from user_manager import get_user_lock, set_in_cache, mark_dirty
        first_id, second_id = sorted([sender_id, target_id])
        lock_first = get_user_lock(chat_id, first_id)
        lock_second = get_user_lock(chat_id, second_id)
        
        async with lock_first:
            async with lock_second:
                s_data = await get_user_data(chat_id, sender_id)
                total_cash = s_data.get('balance', 0)
                total_bank = s_data.get('bank_deposit', 0)
                
                # Защита от передачи долгов
                if total_cash < 0 or total_bank < 0:
                    return await callback.message.edit_text("❌ Наследство отклонено: у завещателя обнаружены долги по кредитам или балансу.")
                
                t_data = await get_user_data(chat_id, target_id)
                
                # Перенос балансов получателю
                t_data['balance'] = t_data.get('balance', 0) + total_cash
                t_data['bank_deposit'] = t_data.get('bank_deposit', 0) + total_bank
                
                # Перенос инвентаря получателю
                inv = s_data.get('inventory', {})
                target_inv = dict(t_data.get('inventory', {}))
                items_transferred = []
                for item_name, count in inv.items():
                    target_inv[item_name] = target_inv.get(item_name, 0) + count
                    items_transferred.append(f"{item_name} (x{count})")
                t_data['inventory'] = target_inv
                
                # Обнуление отправителя
                s_data['balance'] = 0
                s_data['bank_deposit'] = 0
                s_data['inventory'] = {}
                
                # Сохраняем в кэш и помечаем грязными для фоновой записи
                set_in_cache(chat_id, target_id, t_data)
                mark_dirty(chat_id, target_id)
                
                set_in_cache(chat_id, sender_id, s_data)
                mark_dirty(chat_id, sender_id)

                # --- Логирование наследства ---
                try:
                    sender_name = s_data.get('full_name', 'Unknown')
                    sender_username = s_data.get('username', '')
                    recipient_name = t_data.get('full_name', 'Unknown')
                    recipient_username = t_data.get('username', '')
                    try:
                        message_link = callback.message.link or ""
                    except Exception:
                        message_link = ""
                    
                    from log_system import log_inheritance
                    log_inheritance(
                        chat_id=chat_id,
                        chat_title=callback.message.chat.title or "Unknown",
                        sender_id=sender_id,
                        sender_name=sender_name,
                        sender_username=sender_username,
                        recipient_id=target_id,
                        recipient_name=recipient_name,
                        recipient_username=recipient_username,
                        amount=total_cash,
                        bank_deposit=total_bank,
                        items_list=items_transferred,
                        message_link=message_link
                    )
                except Exception as log_e:
                    print(f"Error logging inheritance: {log_e}")

        await callback.message.edit_text(f"🏰 <b>Наследство принято!</b>\nВсе активы перешли к новому владельцу. Бывший владелец теперь нищий.")