from aiogram import Router, types, F
from aiogram.filters import and_f, or_f
from escape import escape_html
from user_manager import get_user_data, update_user_balance
from db import get_db

router = Router()

async def set_chat_judge(chat_id: int, user_id: int):
    db = get_db()
    chat_ref = db.collection('chats').document(str(chat_id))
    await chat_ref.set({'judge_id': user_id}, merge=True)

async def get_chat_judge(chat_id: int) -> int:
    db = get_db()
    chat_ref = db.collection('chats').document(str(chat_id))
    doc = await chat_ref.get()
    if doc.exists:
        return doc.to_dict().get('judge_id')
    return None

@router.message(and_f(F.text, or_f(F.text.lower().startswith("назначить судью"), F.text.lower().startswith("/set_judge"))))
async def cmd_set_judge(message: types.Message):
    from config import CREATOR_ID
    if message.from_user.id != CREATOR_ID:
        return await message.answer("Только Создатель бота может назначать судью.")

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя, которого хотите назначить судьей.")

    target_id = message.reply_to_message.from_user.id
    if message.reply_to_message.from_user.is_bot:
        return await message.answer("Бот не может быть судьей.")

    await set_chat_judge(message.chat.id, target_id)
    target_name = escape_html(message.reply_to_message.from_user.full_name)
    await message.answer(f"👨‍⚖️ Пользователь <b>{target_name}</b> назначен официальным судьей этого чата!")

@router.message(and_f(F.text, or_f(F.text.lower().startswith("снять судью"), F.text.lower().startswith("/remove_judge"))))
async def cmd_remove_judge(message: types.Message):
    from config import CREATOR_ID
    if message.from_user.id != CREATOR_ID:
        return await message.answer("Только Создатель бота может снимать судью.")

    await set_chat_judge(message.chat.id, None)
    await message.answer("👨‍⚖️ Текущий судья чата был отстранен от своих обязанностей!")


@router.message(and_f(F.text, or_f(F.text.lower().startswith("подать иск"), F.text.lower().startswith("/sue"), F.text.lower().startswith("суд"), F.text.lower().startswith("/court"))))
async def cmd_sue(message: types.Message):
    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение пользователя, на которого хотите подать в суд.")

    plaintiff_id = message.from_user.id
    defendant_id = message.reply_to_message.from_user.id

    if plaintiff_id == defendant_id:
        return await message.answer("Вы не можете подать в суд на самого себя.")
    if message.reply_to_message.from_user.is_bot:
        return await message.answer("Нельзя судить бота.")

    args = message.text.split(maxsplit=1)
    reason = escape_html(args[1]) if len(args) > 1 else "Причина не указана"

    plaintiff_name = escape_html(message.from_user.full_name)
    defendant_name = escape_html(message.reply_to_message.from_user.full_name)

    text = (
        f"⚖️ <b>ИСК ПОДАН!</b> ⚖️\n\n"
        f"<b>Истец:</b> {plaintiff_name}\n"
        f"<b>Ответчик:</b> {defendant_name}\n\n"
        f"<b>Обвинение:</b> <i>{reason}</i>\n\n"
        f"<i>Ожидаем решения судьи. Судья может использовать команду <code>/judge [реплай на ответчика] [штраф]</code>, чтобы вынести приговор.</i>"
    )
    await message.answer(text)


@router.message(and_f(F.text, or_f(F.text.lower().startswith("приговор"), F.text.lower().startswith("/judge"), F.text.lower().startswith("осудить"))))
async def cmd_judge(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    from config import CREATOR_ID
    is_bot_creator = (user_id == CREATOR_ID)

    judge_id = await get_chat_judge(chat_id)
    
    is_judge = (judge_id == user_id) or is_bot_creator
    if not is_judge:
        member = await message.chat.get_member(user_id)
        if member.status not in ["creator", "administrator"]:
            return await message.answer("Вы не являетесь судьей или администратором в этом чате.")

    if not message.reply_to_message:
        return await message.answer("Ответьте на сообщение подсудимого, чтобы вынести приговор.")

    target_id = message.reply_to_message.from_user.id
    if target_id == user_id:
        return await message.answer("Судья не может осудить самого себя.")
    if message.reply_to_message.from_user.is_bot:
        return await message.answer("Нельзя судить бота.")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Укажите сумму штрафа: <code>/judge [штраф]</code>")

    try:
        fine = int(args[-1])
        if fine <= 0: return
    except ValueError:
        return await message.answer("Сумма штрафа должна быть числом.")

    res = await update_user_balance(chat_id, target_id, -fine, min_balance=0, is_debt_repayment=False)
    actual_fine = fine
    if res is None:
        def_data = await get_user_data(chat_id, target_id)
        actual_fine = def_data.get('balance', 0)
        await update_user_balance(chat_id, target_id, -actual_fine, min_balance=0, is_debt_repayment=False)

    target_name = escape_html(message.reply_to_message.from_user.full_name)
    judge_name = escape_html(message.from_user.full_name)

    await message.answer(
        f"💥 <b>СУДЕБНЫЙ ПРИГОВОР!</b> 💥\n\n"
        f"Судья <b>{judge_name}</b> признал виновным пользователя <b>{target_name}</b>.\n"
        f"Назначен штраф в размере <b>{actual_fine}</b> сыроежек. ⚖️"
    )
