import time
import asyncio
from aiogram import Router, types, Bot
from aiogram.filters import Command
from db import get_db
from escape import escape_html
from config import CREATOR_ID
from utils import fire_and_forget

router = Router()

async def get_user_stats_ref(chat_id: int, user_id: int):
    db = get_db()
    return db.collection('chats').document(str(chat_id)).collection('stats').document(str(user_id))

# В памяти будем хранить {chat_id: {user_id: {"count": X, "full_name": "Name"}}}
_stats_batch = {}
_batch_lock = asyncio.Lock()

async def increment_message_count(chat_id: int, user_id: int, full_name: str):
    async with _batch_lock:
        if chat_id not in _stats_batch:
            _stats_batch[chat_id] = {}
        if user_id not in _stats_batch[chat_id]:
            _stats_batch[chat_id][user_id] = {"count": 0, "full_name": full_name}

        _stats_batch[chat_id][user_id]["count"] += 1
        _stats_batch[chat_id][user_id]["full_name"] = full_name

async def flush_stats_task():
    """Background task to periodically flush message stats to the DB."""
    while True:
        await asyncio.sleep(30)
        async with _batch_lock:
            # Copy and clear the batch
            if not _stats_batch:
                continue
            batch_to_process = _stats_batch.copy()
            _stats_batch.clear()

        current_time = int(time.time())
        db = get_db()
        from diseases import get_active_diseases
        from user_manager import update_user_balance

        for chat_id, users in batch_to_process.items():
            for user_id, data in users.items():
                try:
                    ref = db.collection('chats').document(str(chat_id)).collection('stats').document(str(user_id))
                    doc = await ref.get()

                    if doc.exists:
                        db_data = doc.to_dict()
                        fire_and_forget(ref.update({
                            'all_time': db_data.get('all_time', 0) + data["count"],
                            'week': db_data.get('week', 0) + data["count"],
                            'full_name': data["full_name"]
                        }))
                    else:
                        fire_and_forget(ref.set({
                            'all_time': data["count"],
                            'week': data["count"],
                            'join_date': current_time,
                            'full_name': data["full_name"]
                        }))
                except Exception as e:
                    print(f"Error flushing stats for user {user_id} in chat {chat_id}: {e}")

@router.message(Command("top"))
async def cmd_top(message: types.Message):
    args = message.text.split()
    chat_id = message.chat.id

    if len(args) < 2:
        from user_manager import get_top_users
        top_users = await get_top_users(chat_id, limit=10)

        if not top_users:
            return await message.answer("🏆 Топ игроков пуст.")

        text = "🏆 <b>Топ-10 богачей чата:</b>\n\n"
        for i, user in enumerate(top_users, start=1):
            vip_icon = " 👑" if user.get('is_vip') else ""
            text += f"{i}. {escape_html(user.get('full_name', 'Unknown'))}{vip_icon} — <b>{user.get('balance', 0)}</b> сыроежек\n"

        text += "\n<i>Используйте /top week, /top all, /top old, /top young для топов активности.</i>"
        return await message.answer(text)

    mode = args[1].lower()
    chat_id = message.chat.id
    db = get_db()
    stats_ref = db.collection('chats').document(str(chat_id)).collection('stats')

    if mode == "all":
        docs = await stats_ref.order_by('all_time', direction='DESCENDING').limit(10).get()
        title = "🏆 Топ по сообщениям (за всё время)"
        key = 'all_time'
    elif mode == "week":
        docs = await stats_ref.order_by('week', direction='DESCENDING').limit(10).get()
        title = "🔥 Топ по сообщениям (за неделю)"
        key = 'week'
    elif mode == "old":
        docs = await stats_ref.order_by('join_date', direction='ASCENDING').limit(10).get()
        title = "👴 Самые старые участники чата"
        key = 'join_date'
    elif mode == "young":
        docs = await stats_ref.order_by('join_date', direction='DESCENDING').limit(10).get()
        title = "👶 Самые новые участники чата"
        key = 'join_date'
    else:
        return await message.answer("Неизвестный режим топа.")

    if not docs:
        return await message.answer("Статистика пока пуста.")

    text = f"<b>{title}:</b>\n\n"
    for i, doc in enumerate(docs, 1):
        data = doc.to_dict()
        name = escape_html(data.get('full_name', 'Unknown'))
        if mode in ["old", "young"]:
            date_str = time.strftime('%d.%m.%Y', time.localtime(data.get('join_date', 0)))
            text += f"{i}. <b>{name}</b> — с {date_str}\n"
        else:
            text += f"{i}. <b>{name}</b> — {data.get(key, 0)} сообщений\n"

    await message.answer(text)

async def weekly_reset_task(bot: Bot):
    while True:
        await asyncio.sleep(60) # Проверяем каждую минуту
        import datetime
        # Получаем время по МСК (UTC+3)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_msk = now_utc + datetime.timedelta(hours=3)
        current_time = now_msk.timetuple()

        # --- 10-минутные задачи (Чесотка и т.д.) ---
        if current_time.tm_min % 10 == 0:
            try:
                db = get_db()
                from diseases import get_active_diseases
                from user_manager import update_user_balance
                chats = await db.collection('chats').get()
                for chat in chats:
                    chat_id = int(chat.id)
                    # ОПТИМИЗАЦИЯ: Ищем только тех, у кого ЕСТЬ болезни
                    users = await db.collection('chats').document(str(chat_id)).collection('users').where('diseases.scabies', '!=', None).get()
                    for user in users:
                        user_id = int(user.id)
                        data = user.to_dict()
                        active_diseases = await get_active_diseases(chat_id, user_id)
                        if 'scabies' in active_diseases:
                            if data.get('balance', 0) >= 50:
                                await update_user_balance(chat_id, user_id, -50)
            except Exception as e:
                print(f"Ошибка в 10-минутной таске (Чесотка): {e}")

        # --- Ежедневное пополнение капитала банков и начисление % по вкладам ---
        if current_time.tm_hour == 0 and current_time.tm_min == 0:
            db = get_db()
            from whitelist import get_whitelist
            from user_manager import update_user_field_batch, update_user_balance_batch
            whitelist = await get_whitelist()
            for chat_id in whitelist.keys():
                try:
                    # 1. Загружаем все банки в чате
                    banks_ref = db.collection('chats').document(str(chat_id)).collection('banks')
                    bank_docs = await banks_ref.get()
                    banks_data = {doc.id: doc.to_dict() for doc in bank_docs}

                    # 2. Начисляем % только тем, у кого ЕСТЬ вклад
                    users_ref = db.collection('chats').document(str(chat_id)).collection('users')
                    users_with_deposits = await users_ref.where('bank_deposit', '>', 0).get()
                    
                    batch = db.batch()
                    op_count = 0

                    for user_doc in users_with_deposits:
                        u_data = user_doc.to_dict()
                        deposit = u_data.get('bank_deposit', 0)
                        bank_id_str = str(u_data.get('bank_name', ''))

                        if bank_id_str in banks_data:
                            base_rate = banks_data[bank_id_str].get('deposit_rate', 3.0)

                            # Лояльность (бонус за дни)
                            deposit_start_time = u_data.get('deposit_start_time', time.time())
                            days_held = (time.time() - deposit_start_time) // 86400
                            loyalty_bonus = min(5.0, days_held * 0.5) 

                            final_rate = base_rate + loyalty_bonus
                            profit = int(deposit * (final_rate / 100))

                            if profit > 0:
                                if banks_data[bank_id_str].get('capital', 0) >= profit:
                                    banks_data[bank_id_str]['capital'] -= profit
                                    new_dep = deposit + profit
                                    
                                    if u_data.get('is_offshore', False):
                                        fee = int(new_dep * 0.005)
                                        new_dep -= fee
                                    
                                    update_user_field_batch(batch, chat_id, int(user_doc.id), 'bank_deposit', max(0, new_dep))
                                    op_count += 1
                                    if op_count >= 450:
                                        await batch.commit()
                                        batch = db.batch()
                                        op_count = 0

                    # 3. Обновляем капитал банков и проверяем банкротство
                    for b_id, b_data in banks_data.items():
                        current_cap = b_data.get('capital', 0)

                        # Банкротство
                        if current_cap < 0:
                            # Оптимизация: ищем только вкладчиков этого конкретного банка
                            bankrupt_vips = await users_ref.where('bank_name', '==', b_id).get()
                            count_refunded = 0
                            for v_doc in bankrupt_vips:
                                dep = v_doc.to_dict().get('bank_deposit', 0)
                                refund = int(dep * 0.5)
                                update_user_field_batch(batch, chat_id, int(v_doc.id), 'bank_deposit', 0)
                                update_user_balance_batch(batch, chat_id, int(v_doc.id), refund)
                                update_user_field_batch(batch, chat_id, int(v_doc.id), 'bank_name', None)
                                op_count += 3
                                if op_count >= 450:
                                    await batch.commit()
                                    batch = db.batch()
                                    op_count = 0
                                count_refunded += 1

                            batch.delete(banks_ref.document(b_id))
                            update_user_field_batch(batch, chat_id, int(b_id), 'is_banker', False)
                            op_count += 2
                            if op_count >= 450:
                                await batch.commit()
                                batch = db.batch()
                                op_count = 0

                            try:
                                await bot.send_message(chat_id, f"💥 <b>ДЕФОЛТ!</b> Банк <b>{b_data.get('name')}</b> признан банкротом и закрыт. ЦБ компенсировал 50% вкладов для {count_refunded} чел.")
                            except Exception: pass
                            continue

                        # Проверяем репутацию банкира (если меньше 0, субсидии не будет)
                        banker_doc = await users_ref.document(b_id).get()
                        banker_data = banker_doc.to_dict() if banker_doc.exists else {}
                        banker_rep = banker_data.get('reputation', 0)

                        # Подсчет выданных кредитов для мультипликатора субсидии
                        total_loans_given = 0
                        debt_users = await users_ref.where('debts', '!=', {}).get()
                        for user_doc in debt_users:
                            u_data = user_doc.to_dict()
                            debts = u_data.get('debts', {})
                            for k, v in debts.items():
                                if k.startswith(f"bank_{b_id}_") and v > 0:
                                    total_loans_given += 1

                        # Базовая субсидия 10 лямов + бонус за кредиты (допустим 1 лям за каждый выданный кредит)
                        base_subsidy = 10000000 + (total_loans_given * 1000000)

                        # Бонус от улучшения "Маркетинг" (Ур. 1-5, по +20% за уровень)
                        lvl_market = b_data.get('upgrade_marketing', 0)
                        market_mult = 1.0 + (lvl_market * 0.20)

                        subsidy = int(base_subsidy * market_mult)

                        # Ежедневный налог на лицензию: 5.000.000
                        license_tax = 5000000

                        new_capital = current_cap - license_tax

                        msg_text = f"📄 С банка <b>{b_data.get('name')}</b> списан ежедневный налог на лицензию: <b>{license_tax}</b> сыр.\n"

                        if banker_rep < 0:
                            msg_text += "🚫 <b>ЦБ отказал в субсидии</b> из-за отрицательной репутации банкира!"
                        else:
                            new_capital += subsidy
                            msg_text += f"🏦 ЦентроЖБРОМ выдал субсидию в размере <b>{subsidy}</b> сыр. (Кредитов: {total_loans_given})."

                        # Жесткая инфляция: Налог на роскошь (сверхприбыль > 500 млн) - 20%
                        if new_capital > 500000000:
                            luxury_tax = int((new_capital - 500000000) * 0.20) # 20% с суммы превышающей 500 млн
                            new_capital -= luxury_tax
                            msg_text += f"\n💸 <b>Налог на излишки:</b> списано <b>{luxury_tax}</b> сыр. (20% от суммы свыше 500м)."

                        batch.update(banks_ref.document(b_id), {'capital': new_capital})
                        op_count += 1
                        if op_count >= 450:
                            await batch.commit()
                            batch = db.batch()
                            op_count = 0

                        try:
                            await bot.send_message(chat_id, msg_text)
                        except Exception: pass

                    if op_count > 0:
                        await batch.commit()

                except Exception as e:
                    print(f"Ошибка ежедневных банковских операций в чате {chat_id}: {e}")

            await asyncio.sleep(60) # Чтобы не сработало дважды
            continue

        # Проверяем, является ли день воскресеньем (6) и время 23:59
        if current_time.tm_wday == 6 and current_time.tm_hour == 23 and current_time.tm_min == 59:
            from whitelist import get_whitelist
            from user_manager import update_user_balance
            db = get_db()
            whitelist = await get_whitelist()

            for chat_id in whitelist.keys():
                try:
                    stats_ref = db.collection('chats').document(str(chat_id)).collection('stats')
                    # Находим победителя недели
                    docs = await stats_ref.order_by('week', direction='DESCENDING').limit(1).get()
                    if docs:
                        winner_doc = docs[0]
                        winner_id = int(winner_doc.id)
                        winner_data = winner_doc.to_dict()
                        winner_name = winner_data.get('full_name', 'Unknown')
                        msg_count = winner_data.get('week', 0)

                        if msg_count > 0:
                            # Выдаем 1500 сыроежек
                            await update_user_balance(chat_id, winner_id, 1500)
                            
                            from seasons import get_season_string, get_glitch_text
                            seasonal_reward_title = await get_season_string("top_winner", "Самый активный участник")
                            seasonal_reward_title = await get_glitch_text(seasonal_reward_title)
                            winner_name = await get_glitch_text(winner_name)

                            try:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=f"🎉 <b>Итоги недели!</b>\n\n{seasonal_reward_title}: <b>{escape_html(winner_name)}</b> ({msg_count} сообщений).\nОн получает премию: <b>1500</b> сыроежек! 💰"
                                )
                            except Exception:
                                pass

                    # Обнуляем счетчики недели для всех
                    batch = db.batch()
                    op_count = 0
                    all_docs = await stats_ref.get()
                    for d in all_docs:
                        batch.update(stats_ref.document(d.id), {'week': 0})
                        op_count += 1
                        if op_count >= 450:
                            await batch.commit()
                            batch = db.batch()
                            op_count = 0

                    if op_count > 0:
                        await batch.commit()
                except Exception as e:
                    print(f"Weekly reset error for chat {chat_id}: {e}")

            # Ждем 60 секунд, чтобы не сработало дважды
            await asyncio.sleep(60)
