import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from admin_dashboard import show_chat_select_screen, cb_select_chat_route, CREATOR_ID


@pytest.mark.asyncio
async def test_show_chat_select_screen_pagination_and_priority():
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()

    callback = MagicMock(spec=CallbackQuery)
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.data = "db_sc_0"

    fake_whitelist = {
        -1002321279920: "Puxxzz chat",
        -1004314722890: "Точка сбора телеграфов работников СГО",
        -1003727608618: "Братство 😼",
        -1002334014281: "Злобные ге(ни)и",
        -1003858124622: "Высший совет ПУКСИ!",
        -1003977425981: "Что? Где? Когда?",
        -1003954383304: "свиньи",
        -1004474797397: "Bobette Flood",
        -1002525881392: "Стая",
        -1002999023820: "Интроверты",
    }

    with patch("admin_dashboard.get_whitelist", AsyncMock(return_value=fake_whitelist)):
        # Page 0
        await show_chat_select_screen(callback, state, page=0)
        assert callback.message.edit_text.called
        args, kwargs = callback.message.edit_text.call_args
        markup = kwargs.get("reply_markup")
        assert markup is not None

        # Verify buttons on page 0
        # Priority chat -1004314722890 must be the first button
        first_btn = markup.inline_keyboard[0][0]
        assert first_btn.callback_data == "db_m_-1004314722890"
        assert "Точка сбора" in first_btn.text

        # Verify pagination row exists (total items = 10, page_size = 8 -> 2 pages)
        page_nav_found = False
        for row in markup.inline_keyboard:
            row_texts = [btn.text for btn in row]
            if "1/2" in " ".join(row_texts):
                page_nav_found = True
                break
        assert page_nav_found, "Pagination navigation row should be present on page 0"

        # Page 1
        callback.message.edit_text.reset_mock()
        await show_chat_select_screen(callback, state, page=1)
        assert callback.message.edit_text.called
        _, kwargs_p1 = callback.message.edit_text.call_args
        markup_p1 = kwargs_p1.get("reply_markup")

        page_nav_found_p1 = False
        for row in markup_p1.inline_keyboard:
            row_texts = [btn.text for btn in row]
            if "2/2" in " ".join(row_texts):
                page_nav_found_p1 = True
                break
        assert page_nav_found_p1, "Pagination navigation row should show 2/2 on page 1"


@pytest.mark.asyncio
async def test_cb_select_chat_route():
    state = MagicMock(spec=FSMContext)
    callback = MagicMock(spec=CallbackQuery)
    callback.data = "db_sc_1"
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.from_user = MagicMock(id=CREATOR_ID)

    with patch("admin_dashboard.show_chat_select_screen", AsyncMock()) as mock_show:
        await cb_select_chat_route(callback, state)
        mock_show.assert_called_once_with(callback, state, page=1)
