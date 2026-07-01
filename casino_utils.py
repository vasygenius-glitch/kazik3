from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram import Router, F

router = Router()

_processing_confirms = set()

def try_acquire_confirm_lock(chat_id: int, message_id: int) -> bool:
    key = (chat_id, message_id)
    if key in _processing_confirms:
        return False
    _processing_confirms.add(key)
    return True

def release_confirm_lock(chat_id: int, message_id: int):
    key = (chat_id, message_id)
    _processing_confirms.discard(key)

@router.callback_query(F.data.startswith("cas_cancel"))
async def process_cas_cancel(callback: types.CallbackQuery):
    # cas_cancel or cas_cancel_{uid}
    parts = callback.data.split("_")
    if len(parts) > 2 and parts[2].isdigit():
        owner_id = int(parts[2])
        if callback.from_user.id != owner_id:
            await callback.answer("⛔ Это не ваша игра!", show_alert=True)
            return
    await callback.answer("Ставка отменена.")
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    except Exception:
        pass

async def ask_casino_confirmation(message: types.Message, game_name: str, bet: int, **kwargs):
    builder = InlineKeyboardBuilder()
    # Serialize kwargs into callback data if needed, but for now just game and bet
    # We use a compact format to fit in callback_data limit (64 chars)
    cb_data = f"cas_conf_{game_name}_{bet}_{message.from_user.id}"
    
    # Add any extra params if needed
    for k, v in kwargs.items():
        cb_data += f"_{v}"
    
    builder.button(text="✅ Подтвердить ставку", callback_data=cb_data)
    builder.button(text="❌ Отмена", callback_data="cas_cancel")
    builder.adjust(1)
    
    await message.answer(
        f"🎰 <b>ПОДТВЕРЖДЕНИЕ СТАВКИ</b>\n\n"
        f"Игра: <b>{game_name.upper()}</b>\n"
        f"Ставка: <b>{bet}</b> сыр.\n\n"
        f"<i>Вы уверены, что хотите сделать ставку?</i>",
        reply_markup=builder.as_markup()
    )

def is_confirmation_callback(data: str):
    return data.startswith("cas_conf_") or data.startswith("cas_cancel")
