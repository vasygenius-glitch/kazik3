"""Single-process safety boundaries for creator-panel handlers."""
import functools
import inspect
import time
import weakref
from aiogram import types
from aiogram.fsm.context import FSMContext
from user_manager import ReentrantLock

_locks = weakref.WeakValueDictionary()
_DESTRUCTIVE = {"cb_perform_player_wipe", "cb_perform_bank_delete", "cb_perform_clan_delete",
                "cb_crypto_del_execute", "cb_backup_restore_execute", "cb_player_execute_do"}


async def arm_confirmation(state, callback, markup):
    await state.update_data(admin_confirmation={
        "actions": [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data],
        "message_id": callback.message.message_id, "user_id": callback.from_user.id,
        "expires": time.time() + 120,
    })


async def consume_confirmation(state, callback):
    data = await state.get_data()
    pending = data.get("admin_confirmation") or {}
    valid = (callback.data in pending.get("actions", [])
             and pending.get("user_id") == callback.from_user.id
             and pending.get("message_id") == callback.message.message_id
             and pending.get("expires", 0) > time.time())
    if valid:
        await state.update_data(admin_confirmation=None)
    return valid


def protect_admin_handler(handler, authorized, answer_callback, logger, input_states):
    params = list(inspect.signature(handler).parameters)
    state_index = params.index("state") - 1 if "state" in params else -1
    @functools.wraps(handler)
    async def wrapper(event, *args, **kwargs):
        is_callback = isinstance(event, types.CallbackQuery) or (
            not isinstance(event, types.Message) and hasattr(event, "data") and hasattr(event, "message"))
        if not authorized(event):
            if is_callback:
                await answer_callback(event, "Нет доступа.", show_alert=True)
            return None
        if is_callback and not callable(getattr(getattr(event, "message", None), "edit_text", None)):
            return await answer_callback(event, "Сообщение недоступно. Откройте /admin заново.")
        state = kwargs.get("state")
        if state is None and state_index >= 0 and len(args) > state_index:
            state = args[state_index]
        actor = event.from_user.id
        lock = _locks.get(actor)
        if lock is None:
            lock = ReentrantLock()
            _locks[actor] = lock
        async with lock:
            expected = input_states.get(handler.__name__)
            try:
                if isinstance(state, FSMContext):
                    if is_callback:
                        destructive = handler.__name__ in _DESTRUCTIVE or (
                            handler.__name__ == "cb_global_wipe_action" and (event.data or "").endswith("_confirmed"))
                        if destructive and not await consume_confirmation(state, event):
                            return await answer_callback(event, "Подтверждение устарело. Откройте действие заново.", show_alert=True)
                        if not destructive:
                            await state.update_data(admin_confirmation=None)
                        await state.set_state(None)
                    elif expected:
                        if await state.get_state() != expected:
                            return await event.answer("Сессия ввода устарела. Откройте /admin заново.")
                        if not isinstance(event.text, str):
                            return await event.answer("Отправьте текстовое значение или /cancel.")
                return await handler(event, *args, **kwargs)
            except Exception:
                logger.exception("Admin handler %s failed", handler.__name__)
                if expected and state is not None:
                    await state.clear()
                if is_callback:
                    await answer_callback(event, "Ошибка операции. Подробности в журнале; не повторяйте начисление без проверки.", show_alert=True)
                else:
                    try:
                        await event.answer("Ошибка операции. Подробности в журнале; откройте меню заново.")
                    except Exception:
                        pass
                return None
    return wrapper


async def default_chat_permissions(bot, chat_id):
    chat = await bot.get_chat(chat_id)
    if chat.permissions is not None:
        return chat.permissions
    return types.ChatPermissions(
        can_send_messages=True, can_send_audios=True, can_send_documents=True,
        can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
        can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
        can_add_web_page_previews=True,
    )
