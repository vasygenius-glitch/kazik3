import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import types
from creator import cmd_chiki_brik, check_and_send_pending_actions


@pytest.mark.asyncio
async def test_cmd_chiki_brik_not_creator():
    msg = AsyncMock(spec=types.Message)
    msg.from_user = MagicMock(id=99999999, full_name="Regular User", username="regular")
    msg.text = "/чикибрик"
    await cmd_chiki_brik(msg)
    msg.answer.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_chiki_brik_success():
    msg = AsyncMock(spec=types.Message)
    msg.answer = AsyncMock()
    msg.answer_photo = AsyncMock()
    msg.from_user = MagicMock(id=5416583030, full_name="Creator", username="creator")
    msg.chat = MagicMock(id=-1002321279920)
    msg.text = "/чикибрик @Elliot_badMentalHealth 50%"
    msg.reply_to_message = None

    with patch("creator._resolve_user_target", new=AsyncMock(return_value=(-1002321279920, 8532826882, "Elliot", "Elliot_badMentalHealth"))), \
         patch("creator.get_user_data", new=AsyncMock(return_value={"balance": 10000000})), \
         patch("creator.update_user_balance", new=AsyncMock(return_value=5000000)) as mock_update, \
         patch("log_system.log_action"):

        await cmd_chiki_brik(msg)
        mock_update.assert_awaited_once_with(-1002321279920, 8532826882, -5000000, min_balance=0, action="Chiki-brik 50% cut")
        assert msg.answer_photo.called or msg.answer.called


@pytest.mark.asyncio
async def test_check_and_send_pending_actions_already_sent():
    bot = AsyncMock()
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.get = AsyncMock(return_value=MagicMock(to_dict=lambda: {"sent": True}))
    mock_db.collection.return_value.document.return_value = mock_doc

    with patch("db.get_db", return_value=mock_db):
        await check_and_send_pending_actions(bot)
        bot.send_photo.assert_not_called()
        bot.send_message.assert_not_called()
