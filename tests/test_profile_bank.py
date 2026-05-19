import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import time

# Mock dependencies before importing profile_bank
mock_fa_async = MagicMock()
mock_fa_async.transactional = lambda f: f

firebase_admin_mock = MagicMock()
firebase_admin_mock.firestore_async = mock_fa_async

sys.modules['firebase_admin'] = firebase_admin_mock
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = mock_fa_async
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()

import profile_bank

@pytest.mark.asyncio
async def test_process_deposit_tx_success():
    chat_id = 111
    user_id = 222
    target_banker_id = 333
    amount = 500

    # Mock snapshots
    mock_bank_snap = MagicMock()
    mock_bank_snap.exists = True
    mock_bank_snap.to_dict.return_value = {'capital': 1000}

    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {
        'balance': 1000,
        'bank_deposit': 200,
        'bank_name': None
    }

    mock_transaction = MagicMock()

    # Define an async side effect function
    async def mock_get_snapshot(tx, ref):
        if ref == mock_bank_ref:
            return mock_bank_snap
        return mock_user_snap

    with patch('profile_bank.get_db') as mock_get_db, \
         patch('user_manager.safe_get_snapshot', side_effect=mock_get_snapshot) as mock_safe_get_snapshot, \
         patch('user_manager.get_user_ref') as mock_get_user_ref:

        # Mock db references
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        global mock_bank_ref
        mock_bank_ref = MagicMock()
        mock_user_ref = MagicMock()
        mock_get_user_ref.return_value = mock_user_ref
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_bank_ref

        actual_amount, total_dep = await profile_bank.process_deposit_tx(
            mock_transaction, chat_id, user_id, target_banker_id, amount
        )

        assert actual_amount == amount
        assert total_dep == 700

        # Verify that only a single update to user document was made
        mock_transaction.update.assert_any_call(mock_user_ref, {
            'balance': 500,
            'bank_deposit': 700,
            'bank_name': target_banker_id
        })

        # Verify that capital was updated
        mock_transaction.update.assert_any_call(mock_bank_ref, {
            'capital': 1500
        })


@pytest.mark.asyncio
async def test_process_withdraw_tx_success():
    chat_id = 111
    user_id = 222
    current_banker_id = 333
    amount = 300

    # Mock snapshots
    mock_bank_snap = MagicMock()
    mock_bank_snap.exists = True
    mock_bank_snap.to_dict.return_value = {'capital': 1000}

    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {
        'balance': 1000,
        'bank_deposit': 500,
        'bank_name': current_banker_id
    }

    mock_transaction = MagicMock()

    # Define an async side effect function
    async def mock_get_snapshot(tx, ref):
        if ref == mock_bank_ref:
            return mock_bank_snap
        return mock_user_snap

    with patch('profile_bank.get_db') as mock_get_db, \
         patch('user_manager.safe_get_snapshot', side_effect=mock_get_snapshot) as mock_safe_get_snapshot, \
         patch('user_manager.get_user_ref') as mock_get_user_ref:

        # Mock db references
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        global mock_bank_ref
        mock_bank_ref = MagicMock()
        mock_user_ref = MagicMock()
        mock_get_user_ref.return_value = mock_user_ref
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_bank_ref

        actual_amount = await profile_bank.process_withdraw_tx(
            mock_transaction, chat_id, user_id, current_banker_id, amount
        )

        assert actual_amount == amount

        # Verify that only a single update to user document was made
        mock_transaction.update.assert_any_call(mock_user_ref, {
            'balance': 1300,
            'bank_deposit': 200
        })

        # Verify that capital was updated
        mock_transaction.update.assert_any_call(mock_bank_ref, {
            'capital': 700
        })
