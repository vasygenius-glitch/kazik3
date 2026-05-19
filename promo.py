from aiogram import Router, types
from aiogram.filters import Command
from db import get_db
from user_manager import update_user_balance
from creator import is_creator
from escape import escape_html
from utils import fire_and_forget

router = Router()

@router.message(Command("createpromo"))
async def cmd_createpromo(message: types.Message):
    if not is_creator(message):
        return

    args = message.text.split()
    if len(args) < 4:
        await message.answer("Использование: <code>/createpromo [код] [награда] [кол-во активаций]</code>")
        return

    code = args[1]
    try:
        reward = int(args[2])
        max_activations = int(args[3])
    except ValueError:
        await message.answer("Награда и количество активаций должны быть числами.")
        return

    db = get_db()
    ref = db.collection('bot_settings').document('promocodes').collection('active').document(code)

    fire_and_forget(ref.set({
        'reward': reward,
        'max_activations': max_activations,
        'used_by': []
    }))

    await message.answer(f"✅ Промокод <b>{code}</b> успешно создан!\nНаграда: {reward} сыроежек\nКоличество активаций: {max_activations}")

@router.message(Command("promo"))
async def cmd_promo(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите промокод: <code>/promo КОД</code>")
        return

    code = args[1]
    chat_id = message.chat.id
    user_id = message.from_user.id

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)
    if 'tripper' in active_diseases:
        return await message.answer("🦠 <b>Триппер</b>: Временный запрет на активацию любых промокодов. Вылечитесь!")

    db = get_db()
    ref = db.collection('bot_settings').document('promocodes').collection('active').document(code)

    from firebase_admin import firestore_async
    from user_manager import safe_get_snapshot

    @firestore_async.transactional
    async def process_promo_activation_tx(transaction, promo_ref, u_id):
        snap = await safe_get_snapshot(transaction, promo_ref)
        if not snap.exists:
            return None, "❌ Такого промокода не существует или он был удален."
        
        p_data = snap.to_dict()
        u_by = list(p_data.get('used_by', []))
        max_act = p_data.get('max_activations', 0)
        rwd = p_data.get('reward', 0)

        if u_id in u_by:
            return None, "❌ Вы уже активировали этот промокод!"

        if len(u_by) >= max_act:
            return None, "❌ Этот промокод больше не действителен (превышен лимит активаций)."

        u_by.append(u_id)
        transaction.update(promo_ref, {'used_by': u_by})
        return rwd, None

    try:
        reward, error_msg = await process_promo_activation_tx(db.transaction(), ref, user_id)
        if error_msg:
            return await message.answer(error_msg)

        await update_user_balance(chat_id, user_id, reward)
        await message.answer(f"🎉 Вы успешно активировали промокод <b>{code}</b> и получили <b>{reward}</b> сыроежек!")
    except Exception as e:
        print(f"Promo activation error: {e}")
        await message.answer("❌ Произошла ошибка при активации промокода. Попробуйте позже.")
