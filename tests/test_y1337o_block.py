import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message, CallbackQuery, Chat, User

import whitelist_middleware
import creator


@pytest.mark.asyncio
async def test_y1337o_blocked_on_commands_and_callbacks():
    whitelist_middleware._y1337o_block_loaded = True
    whitelist_middleware._y1337o_blocked_until = time.time() + 9 * 86400
    whitelist_middleware._y1337o_user_id = None

    mw = whitelist_middleware.WhitelistMiddleware()
    handler = AsyncMock()

    user_target = MagicMock(spec=User)
    user_target.id = 999111222
    user_target.username = "Y1337O"
    user_target.full_name = "Y1337O"

    chat_group = MagicMock(spec=Chat)
    chat_group.id = -1002321279920
    chat_group.type = "supergroup"
    chat_group.title = "пукси чат"

    # 1. Command message in group is blocked
    msg_cmd = MagicMock(spec=Message)
    msg_cmd.from_user = user_target
    msg_cmd.chat = chat_group
    msg_cmd.text = "/profile"
    msg_cmd.caption = None
    msg_cmd.reply = AsyncMock()

    await mw(handler, msg_cmd, {})
    handler.assert_not_awaited()
    msg_cmd.reply.assert_awaited_once()
    assert "9 дней" in msg_cmd.reply.call_args[0][0]

    # 2. Text command in PM is blocked too
    chat_pm = MagicMock(spec=Chat)
    chat_pm.id = 999111222
    chat_pm.type = "private"

    msg_pm = MagicMock(spec=Message)
    msg_pm.from_user = user_target
    msg_pm.chat = chat_pm
    msg_pm.text = "профиль"
    msg_pm.caption = None
    msg_pm.reply = AsyncMock()

    await mw(handler, msg_pm, {})
    handler.assert_not_awaited()
    msg_pm.reply.assert_awaited_once()

    # 3. CallbackQuery is blocked with alert
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = user_target
    cb.message = MagicMock()
    cb.message.chat = chat_group
    cb.answer = AsyncMock()

    await mw(handler, cb, {})
    handler.assert_not_awaited()
    cb.answer.assert_awaited_once()
    assert cb.answer.call_args.kwargs.get("show_alert") is True

    # 4. Non-command regular chat message passes through
    msg_chat = MagicMock(spec=Message)
    msg_chat.from_user = user_target
    msg_chat.chat = chat_group
    msg_chat.text = "привет всем"
    msg_chat.caption = None
    msg_chat.reply_to_message = None
    msg_chat.reply = AsyncMock()

    with patch("user_manager.record_user_chat_activity", AsyncMock()), \
         patch("whitelist_middleware.get_whitelist", AsyncMock(return_value={-1002321279920: "пукси чат"})), \
         patch("whitelist_middleware.get_spy_chats", AsyncMock(return_value=[])), \
         patch("whitelist_middleware.is_spy_all_enabled", AsyncMock(return_value=False)), \
         patch("whitelist_middleware.get_locked_chats", AsyncMock(return_value=[])):
        await mw(handler, msg_chat, {})
        handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_action_sends_to_puksi_chat():
    mock_doc_y = MagicMock()
    mock_doc_y.exists = False
    mock_doc_y.to_dict.return_value = {}

    mock_doc_done = MagicMock()
    mock_doc_done.exists = True
    mock_doc_done.to_dict.return_value = {"sent": True}

    mock_ref_y = MagicMock()
    mock_ref_y.get = AsyncMock(return_value=mock_doc_y)
    mock_ref_y.set = AsyncMock()

    mock_ref_done = MagicMock()
    mock_ref_done.get = AsyncMock(return_value=mock_doc_done)

    def _doc(name):
        if name == "y1337o_accounts_block_puxxzz":
            return mock_ref_y
        return mock_ref_done

    mock_col = MagicMock()
    mock_col.document.side_effect = _doc
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_col

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch("db.get_db", return_value=mock_db), \
         patch("whitelist.get_whitelist", AsyncMock(return_value={-100999888: "Puxxzz chat"})):
        await creator.check_and_send_pending_actions(bot)

    bot.send_message.assert_awaited_once_with(
        chat_id=-100999888,
        text="У одного человека заблокировали счета",
    )
    mock_ref_y.set.assert_awaited_once()
