import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
import types
mock_fa = types.ModuleType('firebase_admin')
mock_fa.firestore_async = types.ModuleType('firestore_async')
mock_fa.firestore_async.transactional = lambda f: f
mock_fa.credentials = types.ModuleType('credentials')
mock_fa.credentials.Certificate = lambda x: None
mock_fa.initialize_app = lambda x: None
sys.modules['firebase_admin'] = mock_fa
sys.modules['firebase_admin.credentials'] = mock_fa.credentials
sys.modules['firebase_admin.firestore_async'] = mock_fa.firestore_async

from court import cmd_judge

@pytest.mark.asyncio
async def test_cmd_judge():
    message = MagicMock()
    message.chat.id = 123
    message.from_user.id = 456
    message.from_user.full_name = "Judge"
    message.answer = AsyncMock()

    reply_to = MagicMock()
    reply_to.from_user.id = 789
    reply_to.from_user.full_name = "Defendant"
    reply_to.from_user.is_bot = False
    message.reply_to_message = reply_to

    message.text = "/judge 100"

    with patch('court.get_chat_judge', new_callable=AsyncMock) as mock_get_judge:
        mock_get_judge.return_value = 456
        with patch('court.update_user_balance', new_callable=AsyncMock) as mock_update_balance:
            mock_update_balance.return_value = 500
            await cmd_judge(message)

            mock_update_balance.assert_called_once_with(123, 789, -100, min_balance=0, is_debt_repayment=False)


@pytest.mark.asyncio
async def test_cmd_set_judge():
    from config import CREATOR_ID
    message = MagicMock()
    message.chat.id = 123
    message.from_user.id = CREATOR_ID

    reply_to = MagicMock()
    reply_to.from_user.id = 789
    reply_to.from_user.full_name = "Defendant"
    reply_to.from_user.is_bot = False
    message.reply_to_message = reply_to

    message.text = "/set_judge"
    message.answer = AsyncMock()

    from court import cmd_set_judge
    with patch('court.set_chat_judge', new_callable=AsyncMock) as mock_set_chat_judge:
        await cmd_set_judge(message)
        mock_set_chat_judge.assert_called_once_with(123, 789)

@pytest.mark.asyncio
async def test_cmd_remove_judge():
    from config import CREATOR_ID
    message = MagicMock()
    message.chat.id = 123
    message.from_user.id = CREATOR_ID

    message.text = "/remove_judge"
    message.answer = AsyncMock()

    from court import cmd_remove_judge
    with patch('court.set_chat_judge', new_callable=AsyncMock) as mock_set_chat_judge:
        await cmd_remove_judge(message)
        mock_set_chat_judge.assert_called_once_with(123, None)

@pytest.mark.asyncio
async def test_cmd_sue():
    message = MagicMock()
    message.chat.id = 123
    message.from_user.id = 456
    message.from_user.full_name = "Plaintiff"

    reply_to = MagicMock()
    reply_to.from_user.id = 789
    reply_to.from_user.full_name = "Defendant"
    reply_to.from_user.is_bot = False
    message.reply_to_message = reply_to

    message.text = "/sue reason why"
    message.answer = AsyncMock()

    from court import cmd_sue
    await cmd_sue(message)
    message.answer.assert_called()
    assert "ИСК ПОДАН" in message.answer.call_args[0][0]
    assert "reason why" in message.answer.call_args[0][0]
