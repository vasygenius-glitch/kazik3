from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from config import CREATOR_ID, CREATOR_IDS
from user_manager import get_user_data, update_user_field
from escape import escape_html
from profile_bank import get_bank_info, create_or_update_bank

router = Router()

def is_creator(message: types.Message):
    return int(message.from_user.id) in CREATOR_IDS

# 1. Добавить долг банку
@router.message(Command("add_bank_debt"))
async def cmd_add_bank_debt(message: types.Message):
    if not is_creator(message): return
    if not message.reply_to_message: return await message.answer("Сделайте реплай на пользователя.")
    args = message.text.split()
    if len(args) < 3: return await message.answer("Использование: /add_bank_debt [Сумма] [Название Банка или ID]")

    try:
        amount = int(args[1])
    except Exception: return await message.answer("Сумма должна быть числом.")

    bank_identifier = " ".join(args[2:])
    chat_id = message.chat.id
    bank_data = await get_bank_info(chat_id, bank_identifier)

    if not bank_data:
        return await message.answer("❌ Банк не найден.")

    banker_id = bank_data['banker_id']
    target_id = message.reply_to_message.from_user.id
    data = await get_user_data(chat_id, target_id)
    debts = data.get('debts', {})

    key = f"bank_{banker_id}_0_none_{amount}"
    debts[key] = debts.get(key, 0) + amount
    await update_user_field(chat_id, target_id, 'debts', debts)
    await message.answer(f"✅ Добавлен долг банку <b>{escape_html(bank_data.get('name'))}</b> в размере {amount} для {escape_html(message.reply_to_message.from_user.full_name)}.")

# 2. Добавить долг игроку (кредитору)
@router.message(Command("add_user_debt"))
async def cmd_add_user_debt(message: types.Message):
    if not is_creator(message): return
    if not message.reply_to_message: return await message.answer("Сделайте реплай на пользователя.")
    args = message.text.split()
    if len(args) < 3: return await message.answer("Использование: /add_user_debt [ID_Игрока_Кредитора] [Сумма]")
    try:
        creditor_id = str(int(args[1]))
        amount = int(args[2])
    except Exception: return

    target_id = message.reply_to_message.from_user.id
    chat_id = message.chat.id
    data = await get_user_data(chat_id, target_id)
    debts = data.get('debts', {})

    debts[creditor_id] = debts.get(creditor_id, 0) + amount
    await update_user_field(chat_id, target_id, 'debts', debts)
    await message.answer(f"✅ Добавлен личный долг (Кредитор ID {creditor_id}) в размере {amount} для {escape_html(message.reply_to_message.from_user.full_name)}.")

# 3. Списать все долги (прощение долгов)
@router.message(Command("clear_debts"))
async def cmd_clear_debts(message: types.Message):
    if not is_creator(message): return
    if not message.reply_to_message: return await message.answer("Сделайте реплай на пользователя.")

    target_id = message.reply_to_message.from_user.id
    chat_id = message.chat.id
    await update_user_field(chat_id, target_id, 'debts', {})
    await message.answer(f"✅ Все долги пользователя {escape_html(message.reply_to_message.from_user.full_name)} обнулены.")

# 4. Списать конкретный долг банку
@router.message(Command("del_bank_debt"))
async def cmd_del_bank_debt(message: types.Message):
    if not is_creator(message): return
    if not message.reply_to_message: return await message.answer("Сделайте реплай на пользователя.")
    args = message.text.split()
    if len(args) < 2: return await message.answer("Использование: /del_bank_debt [Название Банка или ID]")

    bank_identifier = " ".join(args[1:])
    chat_id = message.chat.id
    bank_data = await get_bank_info(chat_id, bank_identifier)

    if not bank_data:
        return await message.answer("❌ Банк не найден.")

    banker_id = bank_data['banker_id']
    target_id = message.reply_to_message.from_user.id
    data = await get_user_data(chat_id, target_id)
    debts = data.get('debts', {})

    keys_to_delete = [k for k in debts.keys() if k.startswith(f"bank_{banker_id}_")]
    for k in keys_to_delete:
        del debts[k]

    await update_user_field(chat_id, target_id, 'debts', debts)
    await message.answer(f"✅ Все долги перед банком <b>{escape_html(bank_data.get('name'))}</b> удалены.")

# 5. Списать конкретный долг игроку
@router.message(Command("del_user_debt"))
async def cmd_del_user_debt(message: types.Message):
    if not is_creator(message): return
    if not message.reply_to_message: return await message.answer("Сделайте реплай на пользователя.")
    args = message.text.split()
    if len(args) < 2: return await message.answer("Использование: /del_user_debt [ID_Игрока_Кредитора]")
    try:
        creditor_id = str(int(args[1]))
    except Exception: return

    target_id = message.reply_to_message.from_user.id
    chat_id = message.chat.id
    data = await get_user_data(chat_id, target_id)
    debts = data.get('debts', {})

    if creditor_id in debts:
        del debts[creditor_id]

    await update_user_field(chat_id, target_id, 'debts', debts)
    await message.answer(f"✅ Долг перед игроком (ID {creditor_id}) удален.")

# 6. Изменить сумму конкретного долга банку
@router.message(Command("set_bank_debt"))
async def cmd_set_bank_debt(message: types.Message):
    if not is_creator(message): return
    if not message.reply_to_message: return await message.answer("Сделайте реплай на пользователя.")
    args = message.text.split()
    if len(args) < 3: return await message.answer("Использование: /set_bank_debt [Новая_Сумма] [Название Банка или ID]")

    try:
        new_amount = int(args[1])
    except Exception: return await message.answer("Сумма должна быть числом.")

    bank_identifier = " ".join(args[2:])
    chat_id = message.chat.id
    bank_data = await get_bank_info(chat_id, bank_identifier)

    if not bank_data:
        return await message.answer("❌ Банк не найден.")

    banker_id = bank_data['banker_id']
    target_id = message.reply_to_message.from_user.id
    data = await get_user_data(chat_id, target_id)
    debts = data.get('debts', {})

    found = False
    for k in list(debts.keys()):
        if k.startswith(f"bank_{banker_id}_"):
            debts[k] = new_amount
            found = True
            break

    if not found:
        key = f"bank_{banker_id}_0_none_{new_amount}"
        debts[key] = new_amount

    await update_user_field(chat_id, target_id, 'debts', debts)
    await message.answer(f"✅ Долг банку <b>{escape_html(bank_data.get('name'))}</b> изменен на {new_amount}.")

# 7. Изменить сумму конкретного долга игроку
@router.message(Command("set_user_debt"))
async def cmd_set_user_debt(message: types.Message):
    if not is_creator(message): return
    if not message.reply_to_message: return await message.answer("Сделайте реплай на пользователя.")
    args = message.text.split()
    if len(args) < 3: return await message.answer("Использование: /set_user_debt [ID_Игрока_Кредитора] [Новая_Сумма]")
    try:
        creditor_id = str(int(args[1]))
        new_amount = int(args[2])
    except Exception: return

    target_id = message.reply_to_message.from_user.id
    chat_id = message.chat.id
    data = await get_user_data(chat_id, target_id)
    debts = data.get('debts', {})

    debts[creditor_id] = new_amount
    await update_user_field(chat_id, target_id, 'debts', debts)
    await message.answer(f"✅ Долг перед игроком (ID {creditor_id}) изменен на {new_amount}.")

# 8. Увеличить/уменьшить капитал банка
@router.message(Command("add_bank_cap"))
async def cmd_add_bank_cap(message: types.Message):
    if not is_creator(message): return
    args = message.text.split()
    if len(args) < 3: return await message.answer("Использование: /add_bank_cap [Сумма] [Название Банка или ID]")

    try:
        amount = int(args[1])
    except Exception: return await message.answer("Сумма должна быть числом.")

    bank_identifier = " ".join(args[2:])
    chat_id = message.chat.id
    bank_data = await get_bank_info(chat_id, bank_identifier)

    if not bank_data:
        return await message.answer("❌ Банк не найден.")

    banker_id = bank_data['banker_id']
    new_cap = bank_data.get('capital', 0) + amount
    await create_or_update_bank(chat_id, banker_id, {'capital': new_cap})
    await message.answer(f"✅ Капитал банка <b>{escape_html(bank_data.get('name'))}</b> изменен. Текущий: {new_cap}.")

# 9. Узнать список всех долгов (Дебаг)
@router.message(Command("view_debts"))
async def cmd_view_debts(message: types.Message):
    if not is_creator(message): return
    if not message.reply_to_message: return await message.answer("Сделайте реплай на пользователя.")

    target_id = message.reply_to_message.from_user.id
    chat_id = message.chat.id
    data = await get_user_data(chat_id, target_id)
    debts = data.get('debts', {})

    if not debts:
        return await message.answer("У пользователя нет долгов.")

    text = "📋 <b>Сырые данные о долгах:</b>\n"
    for k, v in debts.items():
        text += f"Ключ: <code>{k}</code> -> Сумма: <b>{v}</b>\n"

    await message.answer(text)
