import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram import types
import spy
import creator

@pytest.mark.asyncio
async def test_spy_disable_and_toggle():
    mock_db = MagicMock()
    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction
    
    with patch("spy.get_db", return_value=mock_db), \
         patch("spy._doc_ref") as mock_ref:
        
        # Test toggle chat
        with patch("spy._toggle_chat_tx", AsyncMock(return_value=(True, {123}, False))):
            res = await spy.toggle_spy(123)
            assert res is True
            assert await spy.is_spy_enabled(123) is True
            
        # Test disable chat
        with patch("spy._set_chat_tx", AsyncMock(return_value=(False, set(), False))):
            res = await spy.disable_spy(123)
            assert res is False
            assert await spy.is_spy_enabled(123) is False
            
        # Test toggle all
        with patch("spy._toggle_all_tx", AsyncMock(return_value=(True, set()))):
            res = await spy.toggle_spy_all()
            assert res is True
            assert await spy.is_spy_all_enabled() is True
            
        # Test disable all
        with patch("spy._set_all_tx", AsyncMock(return_value=(False, set()))):
            res = await spy.disable_spy_all()
            assert res is False
            assert await spy.is_spy_all_enabled() is False


@pytest.mark.asyncio
async def test_cmd_spy_and_unspy():
    # Mock message
    msg = AsyncMock(spec=types.Message)
    msg.from_user = MagicMock()
    msg.from_user.id = 6652158654  # One of CREATOR_IDS
    msg.chat = MagicMock()
    msg.chat.type = "group"
    msg.chat.id = -10012345
    msg.answer = AsyncMock()

    with patch("creator.is_creator", return_value=True), \
         patch("creator.toggle_spy", AsyncMock(return_value=False)), \
         patch("spy.disable_spy", AsyncMock(return_value=False)), \
         patch("spy.disable_spy_all", AsyncMock(return_value=False)):
        
        # /spy without args in group uses chat.id
        msg.text = "/spy"
        await creator.cmd_spy(msg)
        assert msg.answer.called
        assert "ВЫКЛЮЧЕН" in msg.answer.call_args[0][0]
        
        # /unspy without args in group uses chat.id
        msg.text = "/unspy"
        await creator.cmd_unspy(msg)
        assert msg.answer.called
        assert "ВЫКЛЮЧЕН" in msg.answer.call_args[0][0]

        # /unspyall
        msg.text = "/unspyall"
        await creator.cmd_unspyall(msg)
        assert msg.answer.called
        assert "Глобальный шпионаж ВЫКЛЮЧЕН" in msg.answer.call_args[0][0]
