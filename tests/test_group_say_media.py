import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from admin_dashboard import (
    process_group_say_text,
    AdminPanelState,
    CREATOR_ID,
)


@pytest.mark.asyncio
async def test_process_group_say_text_with_gif():
    """Проверяет, что GIF/анимация успешно транслируется в группу без ошибки текстового ввода."""
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock(return_value={"chat_id": -1004314722890})

    # Message representing a GIF
    msg = MagicMock()
    msg.from_user = MagicMock(id=CREATOR_ID)
    msg.text = None
    msg.caption = None
    msg.animation = MagicMock()
    msg.send_copy = AsyncMock()
    msg.answer = AsyncMock()
    msg.delete = AsyncMock()

    await process_group_say_text(msg, state)

    # Must call send_copy with the target chat_id
    msg.send_copy.assert_awaited_once_with(chat_id=-1004314722890)
    # Must NOT ask for text value
    assert not any("Отправьте текстовое значение" in str(call) for call in msg.answer.call_args_list)


@pytest.mark.asyncio
async def test_process_group_say_text_with_photo():
    """Проверяет, что фото и стикеры также успешно транслируются."""
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock(return_value={"chat_id": -1002321279920})

    msg = MagicMock()
    msg.from_user = MagicMock(id=CREATOR_ID)
    msg.text = None
    msg.photo = [MagicMock()]
    msg.send_copy = AsyncMock()
    msg.answer = AsyncMock()
    msg.delete = AsyncMock()

    await process_group_say_text(msg, state)

    msg.send_copy.assert_awaited_once_with(chat_id=-1002321279920)
    assert not any("Отправьте текстовое значение" in str(call) for call in msg.answer.call_args_list)
