import pytest
import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Mocks
mock_fa_async = MagicMock()
mock_fa_async.transactional = lambda f: f
mock_fa_async.async_transactional = lambda f: f

firebase_admin_mock = MagicMock()
firebase_admin_mock.firestore_async = mock_fa_async

sys.modules['firebase_admin'] = firebase_admin_mock
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = mock_fa_async
sys.modules['config'] = MagicMock()
sys.modules['config'].CREATOR_ID = 999

import court

# --- Helpers ---
def create_mock_message(text, user_id=111, chat_id=123, is_reply=True, target_id=222, target_bot=False):
    msg = AsyncMock()
    msg.text = text
    msg.chat.id = chat_id
    msg.from_user.id = user_id
    msg.from_user.full_name = "User"
    
    if is_reply:
        msg.reply_to_message = AsyncMock()
        msg.reply_to_message.from_user.id = target_id
        msg.reply_to_message.from_user.is_bot = target_bot
        msg.reply_to_message.from_user.full_name = "Target"
    else:
        msg.reply_to_message = None
        
    return msg

# --- Tests for /set_judge ---

@pytest.mark.asyncio
async def test_set_judge_success_creator():
    msg = create_mock_message("/set_judge", user_id=999, target_id=222)
    with patch("court.set_chat_judge", new_callable=AsyncMock) as mock_set:
        await court.cmd_set_judge(msg)
        mock_set.assert_called_once_with(123, 222)
        assert "назначен официальным судьей" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_set_judge_fail_not_creator():
    msg = create_mock_message("/set_judge", user_id=111, target_id=222)
    with patch("court.set_chat_judge", new_callable=AsyncMock) as mock_set:
        await court.cmd_set_judge(msg)
        mock_set.assert_not_called()
        assert "Только Создатель" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_set_judge_fail_no_reply():
    msg = create_mock_message("/set_judge", user_id=999, is_reply=False)
    await court.cmd_set_judge(msg)
    assert "Ответьте на сообщение" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_set_judge_fail_bot():
    msg = create_mock_message("/set_judge", user_id=999, target_bot=True)
    await court.cmd_set_judge(msg)
    assert "Бот не может быть" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_remove_judge_success_creator():
    msg = create_mock_message("/remove_judge", user_id=999, is_reply=False)
    with patch("court.set_chat_judge", new_callable=AsyncMock) as mock_set:
        await court.cmd_remove_judge(msg)
        mock_set.assert_called_once_with(123, None)
        assert "отстранен" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_remove_judge_fail_not_creator():
    msg = create_mock_message("/remove_judge", user_id=111, is_reply=False)
    with patch("court.set_chat_judge", new_callable=AsyncMock) as mock_set:
        await court.cmd_remove_judge(msg)
        mock_set.assert_not_called()
        assert "Только Создатель" in msg.answer.call_args[0][0]

# --- Tests for /sue ---

@pytest.mark.asyncio
async def test_sue_success():
    msg = create_mock_message("/sue fraud", user_id=111, target_id=222)
    await court.cmd_sue(msg)
    assert "ИСК ПОДАН" in msg.answer.call_args[0][0]
    assert "fraud" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_sue_fail_no_reply():
    msg = create_mock_message("/sue fraud", user_id=111, is_reply=False)
    await court.cmd_sue(msg)
    assert "Ответьте на сообщение" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_sue_fail_self():
    msg = create_mock_message("/sue fraud", user_id=111, target_id=111)
    await court.cmd_sue(msg)
    assert "на самого себя" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_sue_fail_bot():
    msg = create_mock_message("/sue fraud", user_id=111, target_bot=True)
    await court.cmd_sue(msg)
    assert "Нельзя судить бота" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_sue_with_long_reason():
    msg = create_mock_message("/sue very long reason here", user_id=111, target_id=222)
    await court.cmd_sue(msg)
    assert "very long reason here" in msg.answer.call_args[0][0]

# --- Tests for /judge ---

@pytest.mark.asyncio
async def test_judge_success_by_judge():
    msg = create_mock_message("/judge 5000", user_id=333, target_id=222)
    
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333), \
         patch("court.update_user_balance", new_callable=AsyncMock, return_value=True) as mock_update:
        await court.cmd_judge(msg)
        mock_update.assert_called_once_with(123, 222, -5000, min_balance=0)
        assert "СУДЕБНЫЙ ПРИГОВОР" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_judge_success_by_admin():
    msg = create_mock_message("/judge 5000", user_id=444, target_id=222)
    msg.chat.get_member = AsyncMock()
    msg.chat.get_member.return_value.status = "administrator"
    
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333), \
         patch("court.update_user_balance", new_callable=AsyncMock, return_value=True) as mock_update:
        await court.cmd_judge(msg)
        mock_update.assert_called_once_with(123, 222, -5000, min_balance=0)
        assert "СУДЕБНЫЙ ПРИГОВОР" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_judge_fail_not_judge():
    msg = create_mock_message("/judge 5000", user_id=444, target_id=222)
    msg.chat.get_member = AsyncMock()
    msg.chat.get_member.return_value.status = "member"
    
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333):
        await court.cmd_judge(msg)
        assert "Вы не являетесь судьей" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_judge_fail_no_reply():
    msg = create_mock_message("/judge 5000", user_id=333, is_reply=False)
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333):
        await court.cmd_judge(msg)
        assert "Ответьте на сообщение подсудимого" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_judge_fail_self():
    msg = create_mock_message("/judge 5000", user_id=333, target_id=333)
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333):
        await court.cmd_judge(msg)
        assert "не может осудить самого себя" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_judge_fail_bot():
    msg = create_mock_message("/judge 5000", user_id=333, target_bot=True)
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333):
        await court.cmd_judge(msg)
        assert "Нельзя судить бота" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_judge_fail_no_amount():
    msg = create_mock_message("/judge", user_id=333, target_id=222)
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333):
        await court.cmd_judge(msg)
        assert "Укажите сумму" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_judge_fail_invalid_amount():
    msg = create_mock_message("/judge abc", user_id=333, target_id=222)
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333):
        await court.cmd_judge(msg)
        assert "Сумма штрафа должна быть числом" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_judge_fail_negative_amount():
    msg = create_mock_message("/judge -100", user_id=333, target_id=222)
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333):
        await court.cmd_judge(msg)
        msg.answer.assert_not_called() # Should return silently

@pytest.mark.asyncio
async def test_judge_partial_balance_fallback():
    msg = create_mock_message("/judge 5000", user_id=333, target_id=222)
    
    with patch("court.get_chat_judge", new_callable=AsyncMock, return_value=333), \
         patch("court.update_user_balance", new_callable=AsyncMock, return_value=None) as mock_update, \
         patch("court.get_user_data", new_callable=AsyncMock, return_value={'balance': 1500}):
        
        await court.cmd_judge(msg)
        
        assert mock_update.call_count == 2
        # First call with -5000
        assert mock_update.call_args_list[0][0] == (123, 222, -5000)
        # Second call with -1500 (taking all remaining)
        assert mock_update.call_args_list[1][0] == (123, 222, -1500)
        
        assert "1500" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_get_chat_judge_missing():
    # Test get_chat_judge directly when doc doesn't exist
    court.get_db = MagicMock()
    mock_db = MagicMock()
    court.get_db.return_value = mock_db
    
    mock_doc = MagicMock()
    mock_doc.exists = False
    
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_doc
    mock_db.collection().document.return_value = mock_ref
    
    res = await court.get_chat_judge(123)
    assert res is None
