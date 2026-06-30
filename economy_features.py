import random
import time
from aiogram import Router, types, Bot, F
from escape import escape_html
from user_manager import get_user_data, update_user_balance, update_user_field, remove_item_from_inventory

router = Router()

@router.message(F.text.lower().startswith("диктор"))
async def cmd_dictor(message: types.Message):
    answers = [
        "Бесспорно", "Предрешено", "Никаких сомнений", "Определённо да", "Можешь быть уверен в этом",
        "Мне кажется — «да»", "Вероятнее всего", "Хорошие перспективы", "Знаки говорят — «да»", "Да",
        "Пока не ясно, попробуй снова", "Спроси позже", "Лучше не рассказывать", "Сейчас нельзя предсказать",
        "Сконцентрируйся и спроси опять", "Даже не думай", "Мой ответ — «нет»", "По моим данным — «нет»",
        "Перспективы не очень хорошие", "Весьма сомнительно"
    ]
    await message.answer(f"🎱 <b>Диктор говорит:</b> {random.choice(answers)}")

@router.message(F.text.lower().startswith("украсть") | F.text.lower().startswith("/steal"))
async def cmd_steal(message: types.Message, bot: Bot):
    if not message.reply_to_message:
        return await message.answer("Сделайте реплай на сообщение того, кого хотите ограбить.")

    chat_id = message.chat.id
    user_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    target_name = escape_html(message.reply_to_message.from_user.full_name)

    if user_id == target_id: return await message.answer("Вы не можете украсть у себя.")
    if message.reply_to_message.from_user.is_bot: return await message.answer("У бота денег нет.")

    from config import CREATOR_ID
    if int(target_id) == int(CREATOR_ID):
        return await message.answer("Невозможно ограбить Создателя!")

    try:
        target_member = await bot.get_chat_member(chat_id, target_id)
        if target_member.status in['administrator', 'creator']:
            return await message.answer("Невозможно ограбить Администрацию!")
    except Exception: pass

    data = await get_user_data(chat_id, user_id)
    last_steal = data.get('last_steal_time', 0)
    current_time = int(time.time())

    from diseases import get_active_diseases
    active_diseases = await get_active_diseases(chat_id, user_id)
    cooldown = 7200 if 'treponema' in active_diseases else 3600

    if current_time - last_steal < cooldown:
        remaining = cooldown - (current_time - last_steal)
        if remaining < 60:
            time_str = f"{remaining} сек."
        else:
            time_str = f"{remaining // 60} мин."
        
        disease_msg = "🦠 <b>Бледная трепонема</b> увеличила кулдаун. " if 'treponema' in active_diseases else ""
        return await message.answer(f"Вы уже пытались воровать недавно. Залягте на дно. {disease_msg}(Осталось {time_str})")

    target_data = await get_user_data(chat_id, target_id)
    target_balance = target_data.get('balance', 0)

    if target_balance <= 0:
        return await message.answer("У жертвы пустые карманы, воровать нечего.")

    user_balance = data.get('balance', 0)
    if user_balance < 1000:
        return await message.answer("Вам нужно минимум 1000 сыроежек на балансе для совершения кражи.")

    await update_user_field(chat_id, user_id, 'last_steal_time', current_time)

    # --- ШАНСЫ ---
    chance = 25
    stealth_lvl = data.get('skills', {}).get('stealth', 0)
    chance += (stealth_lvl * 3) # +15% макс

    # Питомец Лиса
    pet = data.get('pet') or {}
    pet_id = pet.get('id') if isinstance(pet, dict) else None
    if pet_id == 'fox' and 'hpv' not in active_diseases:
        chance += 15

    inventory = data.get('inventory', {})
    has_lockpick = inventory.get('lockpick', 0) > 0
    if has_lockpick:
        await remove_item_from_inventory(chat_id, user_id, 'lockpick')
        chance += 15
    
    if 'syphilis' in active_diseases:
        chance = chance // 2

    if target_data.get('is_vip'): chance -= 10

    if target_data.get('is_banker'):
        from profile_bank import get_bank_info
        bank_data = await get_bank_info(chat_id, target_id)
        if bank_data:
            sec_lvl = bank_data.get('upgrade_security', 0)
            chance -= (sec_lvl * 4)

    roll = random.randint(1, 100)
    
    # Реверс-кража (жертва ловит вора и грабит его)
    if roll > 95: 
        reverse_amount = random.randint(int(user_balance * 0.1), int(user_balance * 0.2))
        reverse_amount = min(reverse_amount, user_balance)
        
        await update_user_balance(chat_id, user_id, -reverse_amount)
        await update_user_balance(chat_id, target_id, reverse_amount)
        
        return await message.answer(
            f"🧤 <b>ОЙ-ОЙ!</b>\n"
            f"Вы попытались вытащить кошелек у {target_name}, но он оказался мастером боевых искусств! "
            f"Он заломил вам руку и, пока вы корчились от боли, сам обчистил ваши карманы на <b>{reverse_amount}</b> сыроежек!"
        )

    if roll <= chance:
        # Успех
        steal_percent = random.uniform(0.05, 0.15)
        steal_amount = int(target_balance * steal_percent)
        steal_amount = max(steal_amount, 100)
        steal_amount = min(steal_amount, target_balance, 1000)

        await update_user_balance(chat_id, target_id, -steal_amount)
        await update_user_balance(chat_id, user_id, steal_amount)

        success_msgs = [
            f"💰 <b>Ловкость рук!</b>\nВы незаметно вытащили <b>{steal_amount}</b> сыроежек из заднего кармана {target_name}!",
            f"🕵️‍♂️ <b>Тише воды, ниже травы...</b>\nПока {target_name} отвлекся, вы прибрали к рукам его <b>{steal_amount}</b> сыроежек!",
            f"🧤 <b>Чистая работа!</b>\nВы виртуозно обчистили {target_name}, пополнив свой баланс на <b>{steal_amount}</b> сыроежек!"
        ]
        
        lockpick_msg = "\n\n<i>(Использована отмычка: +15% к шансу)</i>" if has_lockpick else ""
        await message.answer(random.choice(success_msgs) + lockpick_msg)
    else:
        # Провал
        penalty_percent = 0.10
        has_mask = inventory.get('mask', 0) > 0
        
        if has_mask:
            await remove_item_from_inventory(chat_id, user_id, 'mask')
            penalty_percent = 0.03
            mask_msg = "🎭 <b>Ваша маска помогла скрыться!</b> Штраф значительно снижен.\n"
        else:
            mask_msg = ""

        penalty = int(user_balance * penalty_percent)
        penalty = max(penalty, 1000)
        penalty = min(penalty, user_balance)

        await update_user_balance(chat_id, user_id, -penalty, is_debt_repayment=True)
        await update_user_balance(chat_id, target_id, penalty)

        fail_msgs = [
            f"🚨 <b>Вас поймали!</b>\n{target_name} заметил вашу руку в своем кармане и заставил выплатить <b>{penalty}</b> сыроежек компенсации!",
            f"👮‍♂️ <b>Провал!</b>\nПолиция (или просто бдительные граждане) скрутили вас. Пришлось отдать <b>{penalty}</b> сыроежек {target_name}, чтобы замять дело.",
            f"🤡 <b>Неудача!</b>\nВы споткнулись и выронили все, что пытались украсть, да еще и свой кошелек потеряли. {target_name} теперь богаче на <b>{penalty}</b> сыроежек."
        ]
        
        if target_data.get('is_banker') and target_data.get('bank_security'):
            final_msg = f"🚨 <b>Сработала сигнализация!</b>\nОхрана банка скрутила вас на месте. {mask_msg}Вы выплачиваете <b>{penalty}</b> сыроежек в пользу банка."
        else:
            final_msg = mask_msg + random.choice(fail_msgs)

        await message.answer(final_msg)

