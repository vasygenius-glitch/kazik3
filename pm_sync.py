import time
import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from user_manager import (
    get_user_primary_chat,
    load_user_primary_chat,
    _user_known_chats_cache,
    _user_primary_chat_cache,
    get_db,
)
from escape import escape_html

logger = logging.getLogger(__name__)
pm_sync_router = Router()


@pm_sync_router.message(Command("chats", "link_chat", "sync"), F.chat.type == "private")
async def cmd_chats_menu(message: types.Message):
    user_id = message.from_user.id
    current_chat = await load_user_primary_chat(user_id)
    known = _user_known_chats_cache.get(user_id, {})

    if not known:
        db = get_db()
        if db:
            try:
                doc = await db.collection("user_mappings").document(str(user_id)).get()
                if doc.exists:
                    doc_data = doc.to_dict() or {}
                    known = doc_data.get("known_chats", {})
                    _user_known_chats_cache[user_id] = known
            except Exception as e:
                logger.error("Error loading user mappings: %s", e)

    builder = InlineKeyboardBuilder()

    text = "🌐 <b>Синхронизация профиля с групповыми чатами</b>\n\n"
    if current_chat:
        current_title = known.get(str(current_chat), {}).get("title", f"ID: {current_chat}")
        text += f"📍 <b>Текущий активный чат:</b> «{escape_html(current_title)}»\n"
        text += "<i>Все ваши действия в ЛС (баланс, работа, инвентарь, банк, казино) синхронизированы с этим чатом.</i>\n\n"
    else:
        text += "⚠️ <i>У вас пока нет привязанных групп. Напишите любое сообщение в вашей группе с ботом, чтобы привязать её!</i>\n\n"

    if known:
        text += "<b>Выберите группу для синхронизации в ЛС:</b>\n"
        for cid_str, info in known.items():
            cid = int(cid_str)
            title = info.get("title", f"Чат {cid}")
            is_active = (cid == current_chat)
            icon = "🔘" if is_active else "⚪️"
            builder.button(
                text=f"{icon} {title}",
                callback_data=f"sync_set_{cid}"
            )
        builder.adjust(1)

    builder.button(text="🔄 Обновить", callback_data="sync_refresh")
    builder.adjust(1)

    await message.answer(text, reply_markup=builder.as_markup())


@pm_sync_router.callback_query(F.data.startswith("sync_set_"))
async def cb_sync_set_chat(callback: types.CallbackQuery):
    target_chat_id = int(callback.data.removeprefix("sync_set_"))
    user_id = callback.from_user.id

    db = get_db()
    if db:
        try:
            await db.collection("user_mappings").document(str(user_id)).set({
                "primary_chat_id": target_chat_id,
                "is_pinned": True,
                "last_updated": time.time(),
            }, merge=True)
        except Exception as e:
            logger.error("Error setting primary chat: %s", e)

    _user_primary_chat_cache[user_id] = target_chat_id

    await callback.answer("✅ Чат успешно привязан к ЛС!", show_alert=True)
    await cmd_chats_menu(callback.message)


@pm_sync_router.callback_query(F.data == "sync_refresh")
async def cb_sync_refresh(callback: types.CallbackQuery):
    await callback.answer("🔄 Обновлено")
    await cmd_chats_menu(callback.message)
