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

async def check_balance_alert(chat_id, user_id, full_name, balance):
    """
    Проверяет баланс на аномалии (< -10,000) и добавляет в очередь алертов.
    """
    if balance < -10000:
        # Избегаем дубликатов в очереди за короткий промежуток
        if not any(a['user_id'] == user_id and a['chat_id'] == chat_id for a in alert_queue):
            alert_queue.append({
                'chat_id': chat_id,
                'user_id': user_id,
                'full_name': full_name,
                'balance': balance
            })

async def admin_alert_worker(bot: Bot):
    """
    Фоновый воркер для отправки уведомлений админам.
    """
    while True:
        await asyncio.sleep(10)
        if not alert_queue:
            continue
            
        while alert_queue:
            alert = alert_queue.pop(0)
            try:
                text = (
                    f"⚠️ <b>ВНИМАНИЕ: КРИТИЧЕСКАЯ АНОМАЛИЯ!</b>\n\n"
                    f"🚨 <b>Тип:</b> Возможный дюп / Баг баланса\n"
                    f"👤 <b>Игрок:</b> {alert['full_name']} (<code>{alert['user_id']}</code>)\n"
                    f"💰 <b>Баланс:</b> <code>{alert['balance']}</code>\n"
                    f"📍 <b>ID Чата:</b> <code>{alert['chat_id']}</code>\n\n"
                    f"@admin, требуется немедленная проверка!"
                )
                await bot.send_message(alert['chat_id'], text)
            except Exception as e:
                print(f"Ошибка отправки алерта: {e}")
