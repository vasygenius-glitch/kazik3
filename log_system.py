import asyncio
from aiogram import Router, types, F, Bot, BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from config import CREATOR_ID
from escape import escape_html
from db import get_db
import time

router = Router()

log_buffer = []

async def get_log_chat_id():
    db = get_db()
    doc = await db.collection('bot_settings').document('logchat').get()
    if doc.exists:
        return doc.to_dict().get('chat_id')
    return None

@router.message(Command("setlogchat"))
async def cmd_setlogchat(message: types.Message):
    if CREATOR_ID and int(message.from_user.id) != int(CREATOR_ID):
        return

    args = message.text.split()
    if len(args) > 1:
        try:
            chat_id = int(args[1])
        except ValueError:
            await message.answer("❌ Неверный формат ID чата.")
            return
    else:
        chat_id = message.chat.id

    db = get_db()
    from utils import fire_and_forget
    fire_and_forget(db.collection('bot_settings').document('logchat').set({'chat_id': chat_id}, merge=True))
    await message.answer(f"✅ Чат {chat_id} успешно назначен глобальным Лог-Чатом.")

def log_action(text: str):
    log_buffer.append(f"[{time.strftime('%H:%M:%S')}] {text}")

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            text = event.text or event.caption or ""
            from utils import is_valid_command
            if is_valid_command(text):
                from_user = event.from_user
                user_id = from_user.id if from_user else 0
                username = f"@{from_user.username}" if from_user and from_user.username else ""
                full_name = escape_html(from_user.full_name) if from_user else "Unknown"
                chat_title = escape_html(event.chat.title) if event.chat.title else "Private"
                chat_id = event.chat.id
                
                log_text = f"💬 Команда: <b>{full_name}</b> ({user_id}) {username} в чате «{chat_title}» ({chat_id}): <code>{escape_html(text)}</code>"
                log_action(log_text)
                
        elif isinstance(event, CallbackQuery):
            from_user = event.from_user
            user_id = from_user.id if from_user else 0
            username = f"@{from_user.username}" if from_user and from_user.username else ""
            full_name = escape_html(from_user.full_name) if from_user else "Unknown"
            chat_title = escape_html(event.message.chat.title) if event.message and event.message.chat and event.message.chat.title else "Private"
            chat_id = event.message.chat.id if event.message and event.message.chat else 0
            data_str = event.data or ""
            
            log_text = f"🔘 Кнопка: <b>{full_name}</b> ({user_id}) {username} в чате «{chat_title}» ({chat_id}): <code>{escape_html(data_str)}</code>"
            log_action(log_text)
            
        return await handler(event, data)

async def flush_logs(bot: Bot):
    while True:
        await asyncio.sleep(60) # раз в минуту
        if not log_buffer:
            continue

        log_chat_id = await get_log_chat_id()
        if not log_chat_id:
            log_buffer.clear()
            continue

        logs_to_send = "\n\n".join(log_buffer)
        log_buffer.clear()

        # Разбиваем на чанки по 4000 символов, если нужно
        chunks = [logs_to_send[i:i+4000] for i in range(0, len(logs_to_send), 4000)]
        for chunk in chunks:
            try:
                await bot.send_message(chat_id=log_chat_id, text=f"📜 <b>Логи за минуту:</b>\n\n{chunk}")
            except Exception as e:
                print(f"Failed to send logs: {e}")


def log_financial_transaction(
    action_type: str,
    sender_id: int,
    sender_name: str,
    sender_username: str,
    recipient_id: int,
    recipient_name: str,
    recipient_username: str,
    amount: int,
    commission: int,
    chat_id: int,
    chat_title: str,
    message_link: str,
    sender_balance: int = None,
    recipient_balance: int = None
):
    sender_user = f"@{sender_username}" if sender_username else "нет"
    recipient_user = f"@{recipient_username}" if recipient_username else "нет"
    msg_link_html = f' <a href="{message_link}">[Ссылка]</a>' if message_link else ""
    
    if action_type == "pay":
        text = (
            f"💸 <b>[ПЕРЕВОД] /pay</b>\n"
            f"👤 <b>Отправитель:</b> {escape_html(sender_name)} (ID: <code>{sender_id}</code>, {sender_user})\n"
            f"👥 <b>Получатель:</b> {escape_html(recipient_name)} (ID: <code>{recipient_id}</code>, {recipient_user})\n"
            f"💰 <b>Сумма:</b> <code>{amount:,}</code> сыр.\n"
            f"⚡ <b>Комиссия:</b> <code>{commission:,}</code> сыр.\n"
            f"📍 <b>Группа:</b> «{escape_html(chat_title)}» (ID: <code>{chat_id}</code>){msg_link_html}\n"
        )
        if sender_balance is not None:
            text += f"📉 Баланс отправителя после: <code>{sender_balance:,}</code> сыр.\n"
        if recipient_balance is not None:
            text += f"📈 Баланс получателя после: <code>{recipient_balance:,}</code> сыр.\n"
            
    elif action_type == "deposit":
        text = (
            f"🏦 <b>[ДЕПОЗИТ] /bank deposit</b>\n"
            f"👤 <b>Игрок:</b> {escape_html(sender_name)} (ID: <code>{sender_id}</code>, {sender_user})\n"
            f"🏛 <b>Банкир:</b> ID <code>{recipient_id}</code>\n"
            f"💰 <b>Сумма пополнения:</b> <code>{amount:,}</code> сыр.\n"
            f"📍 <b>Группа:</b> «{escape_html(chat_title)}» (ID: <code>{chat_id}</code>){msg_link_html}\n"
        )
        if sender_balance is not None:
            text += f"📉 Баланс игрока после: <code>{sender_balance:,}</code> сыр.\n"
        if recipient_balance is not None:
            text += f"🏛 Вклад игрока после: <code>{recipient_balance:,}</code> сыр.\n"
            
    elif action_type == "withdraw":
        text = (
            f"💰 <b>[СНЯТИЕ] /bank withdraw</b>\n"
            f"👤 <b>Игрок:</b> {escape_html(sender_name)} (ID: <code>{sender_id}</code>, {sender_user})\n"
            f"🏛 <b>Банкир:</b> ID <code>{recipient_id}</code>\n"
            f"💰 <b>Сумма снятия:</b> <code>{amount:,}</code> сыр.\n"
            f"📍 <b>Группа:</b> «{escape_html(chat_title)}» (ID: <code>{chat_id}</code>){msg_link_html}\n"
        )
        if sender_balance is not None:
            text += f"📈 Баланс игрока после: <code>{sender_balance:,}</code> сыр.\n"
        if recipient_balance is not None:
            text += f"🏛 Вклад игрока после: <code>{recipient_balance:,}</code> сыр.\n"
    else:
        text = f"🔄 Финансовая транзакция: {action_type} - {amount} сыр."
        
    log_action(text)


def log_trade(
    chat_id: int,
    chat_title: str,
    seller_id: int,
    seller_name: str,
    seller_username: str,
    buyer_id: int,
    buyer_name: str,
    buyer_username: str,
    item_name: str,
    price: int,
    message_link: str
):
    seller_user = f"@{seller_username}" if seller_username else "нет"
    buyer_user = f"@{buyer_username}" if buyer_username else "нет"
    msg_link_html = f' <a href="{message_link}">[Ссылка]</a>' if message_link else ""
    
    text = (
        f"🤝 <b>[СДЕЛКА] /deal</b>\n"
        f"👤 <b>Продавец:</b> {escape_html(seller_name)} (ID: <code>{seller_id}</code>, {seller_user})\n"
        f"👤 <b>Покупатель:</b> {escape_html(buyer_name)} (ID: <code>{buyer_id}</code>, {buyer_user})\n"
        f"📦 <b>Предмет:</b> <code>{escape_html(item_name)}</code>\n"
        f"💰 <b>Цена:</b> <code>{price:,}</code> сыр.\n"
        f"📍 <b>Группа:</b> «{escape_html(chat_title)}» (ID: <code>{chat_id}</code>){msg_link_html}\n"
    )
    log_action(text)


def log_inheritance(
    chat_id: int,
    chat_title: str,
    sender_id: int,
    sender_name: str,
    sender_username: str,
    recipient_id: int,
    recipient_name: str,
    recipient_username: str,
    amount: int,
    bank_deposit: int,
    items_list: list,
    message_link: str
):
    sender_user = f"@{sender_username}" if sender_username else "нет"
    recipient_user = f"@{recipient_username}" if recipient_username else "нет"
    msg_link_html = f' <a href="{message_link}">[Ссылка]</a>' if message_link else ""
    
    items_str = ", ".join(items_list) if items_list else "нет"
    
    text = (
        f"⚰️ <b>[НАСЛЕДСТВО] /will</b>\n"
        f"👤 <b>Завещатель:</b> {escape_html(sender_name)} (ID: <code>{sender_id}</code>, {sender_user})\n"
        f"👤 <b>Наследник:</b> {escape_html(recipient_name)} (ID: <code>{recipient_id}</code>, {recipient_user})\n"
        f"💰 <b>Баланс:</b> <code>{amount:,}</code> сыр.\n"
        f"🏦 <b>Банковский вклад:</b> <code>{bank_deposit:,}</code> сыр.\n"
        f"📦 <b>Предметы:</b> <code>{escape_html(items_str)}</code>\n"
        f"📍 <b>Группа:</b> «{escape_html(chat_title)}» (ID: <code>{chat_id}</code>){msg_link_html}\n"
    )
    log_action(text)


def log_loan(
    action_type: str,
    chat_id: int,
    chat_title: str,
    lender_id: int,
    lender_name: str,
    lender_username: str,
    borrower_id: int,
    borrower_name: str,
    borrower_username: str,
    amount: int,
    total_debt: int,
    term_days: int = 0,
    guarantor_id: int = None,
    message_link: str = ""
):
    lender_user = f"@{lender_username}" if lender_username else "нет"
    borrower_user = f"@{borrower_username}" if borrower_username else "нет"
    msg_link_html = f' <a href="{message_link}">[Ссылка]</a>' if message_link else ""
    
    if action_type == "issue":
        guarantor_str = f" (Поручитель: <code>{guarantor_id}</code>)" if guarantor_id else ""
        text = (
            f"🤝 <b>[ВЫДАЧА КРЕДИТА] /credit</b>\n"
            f"🏦 <b>Банкир:</b> {escape_html(lender_name)} (ID: <code>{lender_id}</code>, {lender_user})\n"
            f"👤 <b>Заемщик:</b> {escape_html(borrower_name)} (ID: <code>{borrower_id}</code>, {borrower_user}){guarantor_str}\n"
            f"💰 <b>Сумма:</b> <code>{amount:,}</code> сыр.\n"
            f"📈 <b>Долг к возврату:</b> <code>{total_debt:,}</code> сыр.\n"
            f"⏳ <b>Срок:</b> {term_days} дней\n"
            f"📍 <b>Группа:</b> «{escape_html(chat_title)}» (ID: <code>{chat_id}</code>){msg_link_html}\n"
        )
    else:
        text = (
            f"✅ <b>[ПОГАШЕНИЕ КРЕДИТА] /repay</b>\n"
            f"👤 <b>Заемщик:</b> {escape_html(borrower_name)} (ID: <code>{borrower_id}</code>, {borrower_user})\n"
            f"👤 <b>Кредитор:</b> {escape_html(lender_name)} (ID: <code>{lender_id}</code>, {lender_user})\n"
            f"💰 <b>Выплачено:</b> <code>{amount:,}</code> сыр.\n"
            f"📉 <b>Остаток долга:</b> <code>{total_debt:,}</code> сыр.\n"
            f"📍 <b>Группа:</b> «{escape_html(chat_title)}» (ID: <code>{chat_id}</code>){msg_link_html}\n"
        )
    log_action(text)


