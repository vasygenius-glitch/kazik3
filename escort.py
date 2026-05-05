import time
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from escape import escape_html
from user_manager import get_user_data, update_user_balance, update_user_field
from db import get_db

router = Router()
active_escorts = {}

@router.message(F.text & (F.text.lower().startswith("нанять") | F.text.lower().startswith("заказать")))
async def cmd_rent(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("Сделай реплай на того, кого хочешь нанять.")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажи цену: нанять [сумма]")

    chat_id = message.chat.id
    client_id = message.from_user.id
    hooker_id = message.reply_to_message.from_user.id

    if client_id == hooker_id: return await message.answer("Самоудовлетворение это бесплатно.")
    if message.reply_to_message.from_user.is_bot: return await message.answer("Бот не оказывает интим-услуги.")

    try:
        amount = int(args[1])
        if amount <= 0: return
    except: return

    client_data = await get_user_data(chat_id, client_id)
    if client_data.get('balance', 0) < amount:
        return await message.answer("У тебя не хватает сыроежек на оплату таких услуг.")

    deal_id = str(int(time.time() * 1000))[-8:]
    active_escorts[deal_id] = {
        'amount': amount,
        'client_id': client_id,
        'hooker_id': hooker_id,
        'type': 'rent'
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="Согласиться 💋", callback_data=f"esc_yes_{deal_id}")
    builder.button(text="Отказаться ❌", callback_data=f"esc_no_{deal_id}")

    await message.answer(
        f"🔞 <b>Заказ интим-услуг!</b>\n\n"
        f"<b>{escape_html(message.from_user.full_name)}</b> хочет нанять <b>{escape_html(message.reply_to_message.from_user.full_name)}</b> за <b>{amount}</b> сыроежек!\n\n"
        f"Согласен(на) на сделку?",
        reply_markup=builder.as_markup()
    )

@router.message(F.text & (F.text.lower().startswith("эскорт") | F.text.lower().startswith("проститут")))
async def cmd_offer(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("Сделай реплай на потенциального клиента.")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажи цену: эскорт [сумма]")

    chat_id = message.chat.id
    hooker_id = message.from_user.id
    client_id = message.reply_to_message.from_user.id

    if client_id == hooker_id: return
    if message.reply_to_message.from_user.is_bot: return

    try:
        amount = int(args[1])
        if amount <= 0: return
    except: return

    deal_id = str(int(time.time() * 1000))[-8:]
    active_escorts[deal_id] = {
        'amount': amount,
        'client_id': client_id,
        'hooker_id': hooker_id,
        'type': 'offer'
    }

    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить 💸", callback_data=f"esc_yes_{deal_id}")
    builder.button(text="Отказаться ❌", callback_data=f"esc_no_{deal_id}")

    await message.answer(
        f"🔞 <b>Предложение интим-услуг!</b>\n\n"
        f"<b>{escape_html(message.from_user.full_name)}</b> предлагает свои услуги <b>{escape_html(message.reply_to_message.from_user.full_name)}</b> за <b>{amount}</b> сыроежек!\n\n"
        f"Будешь брать?",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("esc_yes_") | F.data.startswith("esc_no_"))
async def callback_escort(callback: types.CallbackQuery):
    action = callback.data.split("_")[1]
    deal_id = callback.data.split("_")[2]

    if deal_id not in active_escorts:
        return await callback.answer("Сделка уже неактуальна.", show_alert=True)

    deal_info = active_escorts[deal_id]
    client_id = deal_info['client_id']
    hooker_id = deal_info['hooker_id']
    deal_type = deal_info['type']
    amount = deal_info['amount']
    chat_id = callback.message.chat.id

    if deal_type == 'rent' and callback.from_user.id != hooker_id:
        return await callback.answer("Решают не за тебя!", show_alert=True)
    if deal_type == 'offer' and callback.from_user.id != client_id:
        return await callback.answer("Это предложение не для тебя!", show_alert=True)

    del active_escorts[deal_id]

    if action == "no":
        return await callback.message.edit_text("❌ Сделка сорвалась. Стороны не сошлись в цене.")

    client_data = await get_user_data(chat_id, client_id)
    if client_data.get('balance', 0) < amount:
        return await callback.message.edit_text("❌ У клиента не хватило денег на оплату!")

    await update_user_balance(chat_id, client_id, -amount)
    
    try:
        from economy_utils import get_global_tax
        tax_percent = await get_global_tax()
    except:
        tax_percent = 10

    tax_amount = int(amount * (tax_percent / 100.0))
    net_amount = amount - tax_amount
    await update_user_balance(chat_id, hooker_id, net_amount)

    hooker_data = await get_user_data(chat_id, hooker_id)
    new_count = hooker_data.get('escort_count', 0) + 1
    await update_user_field(chat_id, hooker_id, 'escort_count', new_count)

    tax_text = f" (Налог сутенеру: {tax_amount})" if tax_amount > 0 else ""
    
    result_msg = f"🔞 <b>ЖЕСТКИЙ ИНТИМ!</b>\n\nСделка состоялась! Клиент оплатил <b>{amount}</b> сыроежек.\nПутана получила <b>{net_amount}</b> сыроежек{tax_text}."

    # --- Логика заражения ЗППП ---
    import random
    from diseases import infect_user, infect_full_house, get_active_diseases
    from config import CREATOR_ID
    from user_manager import remove_item_from_inventory

    new_infections_client = []
    new_infections_hooker = []
    is_creator_involved = False

    # Проверка презервативов
    client_has_condom = await remove_item_from_inventory(chat_id, client_id, "condom")
    hooker_has_condom = await remove_item_from_inventory(chat_id, hooker_id, "condom")

    if client_has_condom:
        result_msg += "\n\n🎈 Клиент использовал презерватив! 100% защита от ЗППП на один раз."
    if hooker_has_condom:
        result_msg += "\n\n🎈 Путана использовала презерватив! 100% защита от ЗППП на один раз."

    if client_has_condom or hooker_has_condom:
        await callback.message.edit_text(result_msg)
        return

    if CREATOR_ID:
        if int(client_id) == int(CREATOR_ID):
            is_creator_involved = True
            new_infections_hooker = await infect_full_house(chat_id, hooker_id)
            result_msg += "\n\n🌟 <b>КЛИЕНТ-БОГ:</b> Мощная энергетика Создателя подавила иммунитет путаны! Она мгновенно получила весь букет ЗППП на 15 минут!"
        elif int(hooker_id) == int(CREATOR_ID):
            is_creator_involved = True
            new_infections_client = await infect_full_house(chat_id, client_id)
            result_msg += "\n\n🌟 <b>ПУТАНА-БОГИНЯ:</b> Невероятная аура Создателя сожгла защиту клиента! Он заразился абсолютно всем на 15 минут!"

    if not is_creator_involved:
        client_diseases = await get_active_diseases(chat_id, client_id)
        hooker_diseases = await get_active_diseases(chat_id, hooker_id)

        # Если один из них болен, шанс заразить другого ОЧЕНЬ высок (80%)
        # Если оба здоровы, есть 30% шанс подхватить случайную болезнь
        if client_diseases or hooker_diseases:
            if random.randint(1, 100) <= 80:
                if not client_diseases:
                    new_infections_client = await infect_user(chat_id, client_id)
                if not hooker_diseases:
                    new_infections_hooker = await infect_user(chat_id, hooker_id)
        else:
            if random.randint(1, 100) <= 30:
                infected = random.choice([client_id, hooker_id, "both"])
                if infected == client_id or infected == "both":
                    new_infections_client = await infect_user(chat_id, client_id)
                if infected == hooker_id or infected == "both":
                    new_infections_hooker = await infect_user(chat_id, hooker_id)

    if (new_infections_client or new_infections_hooker) and not is_creator_involved:
        result_msg += "\n\n⚠️ <b>ОХ НЕПРИЯТНОСТЬ...</b> Кто-то пренебрег защитой!\n"

        if new_infections_client:
            penalty_client = int(max(0, client_data.get('balance', 0)) * 0.1) # теряет 10% на врачей (только положительный баланс)
            await update_user_balance(chat_id, client_id, -penalty_client)
            result_msg += f"👨‍💼 Клиент подцепил: {', '.join(new_infections_client)}. (Потерял {penalty_client} сыр. на лечение)\n"

        if new_infections_hooker:
            penalty_hooker = int(max(0, hooker_data.get('balance', 0)) * 0.1)
            await update_user_balance(chat_id, hooker_id, -penalty_hooker)
            result_msg += f"💃 Путана подцепила: {', '.join(new_infections_hooker)}. (Потеряла {penalty_hooker} сыр. на лечение)\n"

        result_msg += "<i>Проверьте свой статус: /зппп</i>"

    await callback.message.edit_text(result_msg)

@router.message(F.text & (F.text.lower().startswith("топ путан") | F.text.lower().startswith("топ эскорт") | F.text.lower().startswith("/top_escort")))
async def cmd_top_escort(message: types.Message):
    chat_id = message.chat.id
    db = get_db()
    
    users_ref = db.collection('chats').document(str(chat_id)).collection('users')
    
    try:
        docs = await users_ref.get()
    except Exception as e:
        return await message.answer(f"❌ Ошибка базы данных: {e}")

    top_list = []
    for doc in docs:
        try:
            data = doc.to_dict()
            count = data.get('escort_count', 0)
            
            # Фильтруем пустые, скрытые и забаненные аккаунты
            if count > 0 and not data.get('hide_in_top') and not data.get('is_banned'):
                name = escape_html(data.get('full_name', 'Инкогнито'))
                top_list.append((name, count))
        except:
            continue

    # Сортируем средствами Python (безопасно для любых БД без индексов)
    top_list.sort(key=lambda x: x[1], reverse=True)
    
    # Оставляем только топ-10
    top_list = top_list[:10]

    if not top_list:
        return await message.answer("🔞 <b>В этом чате пока нет заслуженных тружеников эскорта.</b>\nВсё еще впереди!")

    text = "🔞 <b>ТОП-10 ПУТАН ЧАТА</b> 🔞\n\n"
    for i, (name, count) in enumerate(top_list, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔹"
        text += f"{medal} <b>{name}</b> — выебан(а) {count} раз(а)\n"

    await message.answer(text)