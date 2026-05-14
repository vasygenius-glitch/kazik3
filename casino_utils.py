from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram import Router, F

router = Router()

class CasinoState(StatesGroup):
    playing = State()

@router.callback_query(F.data == "cas_cancel")
async def process_cas_cancel(callback: types.CallbackQuery):
    await callback.answer("Ставка отменена.")
    await callback.message.delete()

async def ask_casino_confirmation(message: types.Message, game_name: str, bet: int, **kwargs):
    builder = InlineKeyboardBuilder()
    # Serialize kwargs into callback data if needed, but for now just game and bet
    # We use a compact format to fit in callback_data limit (64 chars)
    cb_data = f"cas_conf_{game_name}_{bet}"
    
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
    return data.startswith("cas_conf_") or data == "cas_cancel"
