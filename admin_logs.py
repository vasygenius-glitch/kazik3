import time
import asyncio
from db import get_db
from utils import fire_and_forget
from aiogram import Bot

# Очередь алертов для фоновой отправки
alert_queue = []

async def log_transaction(who_id, who_name, to_id, to_name, action, amount):
    """
    Записывает крупную транзакцию (> 500,000) в отдельную коллекцию Firestore.
    """
    db = get_db()
    if not db:
        return
        
    ref = db.collection('admin_transactions').document()
    data = {
        'who_id': str(who_id),
        'who_name': who_name,
        'to_id': str(to_id) if to_id else None,
        'to_name': to_name,
        'action': action,
        'amount': amount,
        'timestamp': time.time(),
        'readable_time': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    # Используем fire_and_forget чтобы не блокировать основной поток
    fire_and_forget(ref.set(data))
    
    from log_system import log_action
    log_action(f"💸 <b>Крупный перевод:</b> {who_name} ({who_id}) ➡️ {to_name} ({to_id if to_id else 'нет'}): <code>{amount:,}</code> ({action})")

async def check_balance_alert(chat_id, user_id, full_name, balance):
    """
    Проверяет баланс на аномалии (< -500,000) и добавляет в очередь алертов.
    """
    if balance < -500000:
        # Избегаем дубликатов в очереди за короткий промежуток
        if not any(a['user_id'] == user_id and a['chat_id'] == chat_id for a in alert_queue):
            alert_queue.append({
                'chat_id': chat_id,
                'user_id': user_id,
                'full_name': full_name,
                'balance': balance
            })
            from log_system import log_action
            log_action(f"🚨 <b>Аномалия баланса:</b> {full_name} ({user_id}) в чате <code>{chat_id}</code>. Баланс: <code>{balance:,}</code>")

async def admin_alert_worker(bot: Bot):
    """
    Фоновый воркер для отправки уведомлений админам.
    """
    while True:
        await asyncio.sleep(10)
        if not alert_queue:
            continue
            
        from log_system import get_log_chat_id
        from config import CREATOR_ID
        from escape import escape_html
        
        log_chat_id = await get_log_chat_id()
        target_chat_id = log_chat_id or CREATOR_ID
        
        if not target_chat_id:
            alert_queue.clear()
            continue
            
        while alert_queue:
            alert = alert_queue.pop(0)
            try:
                from user_manager import get_user_data
                try:
                    u_data = await get_user_data(alert['chat_id'], alert['user_id'])
                    username = u_data.get('username')
                    bank_deposit = u_data.get('bank_deposit', 0)
                except Exception as e:
                    print(f"Ошибка получения данных пользователя в алерт-воркере: {e}")
                    username = None
                    bank_deposit = 0

                try:
                    chat_info = await bot.get_chat(alert['chat_id'])
                    chat_title = chat_info.title or "Unknown"
                    chat_username = chat_info.username
                    if chat_username:
                        chat_link = f"<a href=\"https://t.me/{chat_username}\">@{chat_username}</a>"
                    else:
                        chat_link = "<i>приватная группа</i>"
                except Exception as e:
                    print(f"Ошибка получения инфо о чате {alert['chat_id']}: {e}")
                    chat_title = f"Группа {alert['chat_id']}"
                    chat_link = "<i>неизвестно</i>"

                user_mention = f"@{username}" if username else "нет"
                escaped_name = escape_html(alert['full_name'])
                group_title = escape_html(chat_title)

                text = (
                    f"🚨 <b>ВОЗМОЖНЫЙ ДЮП / БАГ БАЛАНСА</b> 🚨\n\n"
                    f"👤 <b>Игрок:</b> {escaped_name}\n"
                    f"🆔 <b>ID:</b> <code>{alert['user_id']}</code>\n"
                    f"📧 <b>Юзернейм:</b> {user_mention}\n"
                    f"💰 <b>Баланс кошелька:</b> <code>{alert['balance']:,}</code> сыр.\n"
                    f"🏦 <b>Банковский вклад:</b> <code>{bank_deposit:,}</code> сыр.\n\n"
                    f"📍 <b>Группа:</b> «{group_title}»\n"
                    f"🆔 <b>ID Группы:</b> <code>{alert['chat_id']}</code>\n"
                    f"🔗 <b>Ссылка на группу:</b> {chat_link}\n\n"
                    f"⚡ <i>Требуется немедленная проверка администратором!</i>"
                )
                await bot.send_message(target_chat_id, text)
            except Exception as e:
                print(f"Ошибка отправки алерта: {e}")

