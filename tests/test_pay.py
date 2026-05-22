import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import sys

# Mock dependencies
mock_fa_async = MagicMock()
mock_fa_async.transactional = lambda f: f
mock_fa_async.async_transactional = lambda f: f

firebase_admin_mock = MagicMock()
firebase_admin_mock.firestore_async = mock_fa_async

sys.modules['firebase_admin'] = firebase_admin_mock
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = mock_fa_async
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()

import economy

@pytest.mark.asyncio
async def test_process_transfer_tx_sender_insufficient_funds():
    chat_id = 111
    sender_id = 222
    target_id = 333
    total_cost = 100
    amount = 90
    commission = 10

    mock_transaction = MagicMock()

    # We mock update_user_balance to return None for the sender
    async def mock_update_balance(c_id, u_id, amt, min_balance=None, transaction=None, action=None):
        if u_id == sender_id:
            return None # Insufficient funds
        return 1000

    with patch('economy.update_user_balance', side_effect=mock_update_balance):
        with pytest.raises(ValueError) as excinfo:
            await economy.process_transfer_tx(
                mock_transaction, chat_id, sender_id, target_id,
                total_cost, amount, [], commission
            )
        assert "Недостаточно средств" in str(excinfo.value)

@pytest.mark.asyncio
async def test_process_transfer_tx_target_not_found():
    chat_id = 111
    sender_id = 222
    target_id = 333
    total_cost = 100
    amount = 90
    commission = 10

    mock_transaction = MagicMock()

    # We mock update_user_balance to succeed for sender but return None for target
    async def mock_update_balance(c_id, u_id, amt, min_balance=None, transaction=None, action=None):
        if u_id == sender_id:
            return 500
        return None # Target not found

    with patch('economy.update_user_balance', side_effect=mock_update_balance):
        with pytest.raises(ValueError) as excinfo:
            await economy.process_transfer_tx(
                mock_transaction, chat_id, sender_id, target_id,
                total_cost, amount, [], commission
            )
        assert "Получатель не найден" in str(excinfo.value)
