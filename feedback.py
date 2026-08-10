# feedback.py
"""
Модуль обратной связи: отправка предложений и сообщений об ошибках создателю бота.
"""
import html
import logging
from aiogram import Bot, Router, F, types
from aiogram.filters import Command, CommandObject, or_f

try:
    from config import CREATOR_ID, CREATOR_IDS
except ImportError:
    CREATOR_ID = 5416583030
    CREATOR_IDS = {CREATOR_ID}

log = logging.getLogger(__name__)
router = Router(name="feedback")


@router.message(or_f(
    Command("предложение", "suggest", "feedback", "отзыв", "баг", "bug"),
    F.text.regexp(r"^[!./]?\s*(предложение|предложка|отзыв|баг|suggest|feedback)\b", flags=2)
))
async def cmd_feedback(message: types.Message, command: CommandObject = None, bot: Bot = None):
    # Извлекаем текст после команды
    text = ""
    if command and command.args:
        text = command.args.strip()
    elif message.text:
        parts = message.text.strip().split(maxsplit=1)
        if len(parts) > 1:
            text = parts[1].strip()

    if not text:
        return await message.answer(
            "💡 <b>Напишите свои предложения по боту или ошибки в боте.</b>\n"
            "<i>(Шуточные предложения будут наказываться!)</i>\n\n"
            "<b>Как отправить:</b>\n"
            "<code>/предложение [текст вашего предложения или найденного бага]</code>\n\n"
            "<i>Пример:</i> <code>/предложение добавьте больше катастроф в игры</code>",
            parse_mode="HTML"
        )

    # Информация об отправителе
    user = message.from_user
    user_name = html.escape(user.full_name) if user else "Неизвестный"
    username = f"@{html.escape(user.username)}" if user and user.username else "нет"
    user_id = user.id if user else 0

    if message.chat.type in ("group", "supergroup"):
        chat_info = f"Группа «{html.escape(message.chat.title or '')}» (ID: <code>{message.chat.id}</code>)"
    else:
        chat_info = "Личные сообщения (ЛС)"

    report = (
        "💡 <b>НОВОЕ ПРЕДЛОЖЕНИЕ / ОТЗЫВ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>От:</b> {user_name} ({username} | ID: <code>{user_id}</code>)\n"
        f"💬 <b>Источник:</b> {chat_info}\n\n"
        f"📝 <b>Текст предложения:</b>\n"
        f"<i>{html.escape(text)}</i>"
    )

    # Сбор ID администраторов / создателей
    destinations = set()
    if CREATOR_ID:
        try:
            destinations.add(int(CREATOR_ID))
        except (ValueError, TypeError):
            pass
    if CREATOR_IDS:
        for cid in CREATOR_IDS:
            try:
                destinations.add(int(cid))
            except (ValueError, TypeError):
                pass

    sent_count = 0
    if bot and destinations:
        for cid in destinations:
            try:
                await bot.send_message(cid, report, parse_mode="HTML")
                sent_count += 1
            except Exception as e:
                log.warning("Не удалось отправить отзыв создателю %s: %s", cid, e)

    await message.answer(
        "✅ <b>Спасибо! Ваше предложение отправлено разработчику.</b>",
        parse_mode="HTML"
    )


CHANGELOG_TEXT = (
    "🚀 ОБНОВЛЕНИЕ БОТА\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "☢️ Новая игра «Бункер»:\n"
    "• /bunker — Начать игру\n"
    "• /bunker_stop — Остановить игру\n\n"
    "💡 Предложения и ошибки:\n"
    "• /предложение [текст] — Написать разработчикам\n\n"
    "📢 Информация:\n"
    "• /новости — Последние обновления"
)


@router.message(or_f(
    Command("новости", "обновления", "changelog", "news"),
    F.text.regexp(r"^[!./]?\s*(новости|обновления|changelog|news)\b", flags=2)
))
async def cmd_changelog(message: types.Message):
    await message.answer(CHANGELOG_TEXT, parse_mode="HTML")
