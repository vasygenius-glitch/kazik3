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
import db
import user_manager

@pytest.mark.asyncio
async def test_process_transfer_tx_sender_insufficient_funds():
    chat_id = 111
    sender_id = 222
    target_id = 333
    total_cost = 100
    amount = 90
    commission = 10

    mock_transaction = MagicMock()

    db_store = {
        f"chats/{chat_id}/users/{sender_id}": {"balance": 50},  # 50 < total_cost 100
        f"chats/{chat_id}/users/{target_id}": {"balance": 200},
    }

    async def mock_get_snapshot(tx, ref):
        path = ref.path
        if path in db_store:
            snap = MagicMock()
            snap.exists = True
            snap.to_dict.return_value = db_store[path]
            return snap
        snap = MagicMock()
        snap.exists = False
        return snap

    mock_db = MagicMock()
    mock_db.collection().document().collection().document().path = f"chats/{chat_id}/users/{sender_id}"
    
    orig_db_get_db = db.get_db
    orig_um_get_db = user_manager.get_db
    db.get_db = lambda: mock_db
    user_manager.get_db = lambda: mock_db

    def make_mock_ref(path):
        ref = MagicMock()
        ref.path = path
        return ref

    with patch('economy.get_user_ref', side_effect=lambda c, u: make_mock_ref(f"chats/{c}/users/{u}")), \
         patch('economy.safe_get_snapshot', side_effect=mock_get_snapshot):
        try:
            with pytest.raises(ValueError) as excinfo:
                await economy.process_transfer_tx(
                    mock_transaction, chat_id, sender_id, target_id,
                    total_cost, amount, [], commission
                )
            assert "Недостаточно средств" in str(excinfo.value)
        finally:
            db.get_db = orig_db_get_db
            user_manager.get_db = orig_um_get_db


@pytest.mark.asyncio
async def test_process_transfer_tx_target_not_found():
    chat_id = 111
    sender_id = 222
    target_id = 333
    total_cost = 100
    amount = 90
    commission = 10

    mock_transaction = MagicMock()

    # Sender exists but target does not
    db_store = {
        f"chats/{chat_id}/users/{sender_id}": {"balance": 500},
    }

    async def mock_get_snapshot(tx, ref):
        path = ref.path
        if path in db_store:
            snap = MagicMock()
            snap.exists = True
            snap.to_dict.return_value = db_store[path]
            return snap
        snap = MagicMock()
        snap.exists = False
        return snap

    mock_db = MagicMock()
    
    orig_db_get_db = db.get_db
    orig_um_get_db = user_manager.get_db
    db.get_db = lambda: mock_db
    user_manager.get_db = lambda: mock_db

    def make_mock_ref(path):
        ref = MagicMock()
        ref.path = path
        return ref

    with patch('economy.get_user_ref', side_effect=lambda c, u: make_mock_ref(f"chats/{c}/users/{u}")), \
         patch('economy.safe_get_snapshot', side_effect=mock_get_snapshot):
        try:
            with pytest.raises(ValueError) as excinfo:
                await economy.process_transfer_tx(
                    mock_transaction, chat_id, sender_id, target_id,
                    total_cost, amount, [], commission
                )
            assert "Получатель не найден" in str(excinfo.value)
        finally:
            db.get_db = orig_db_get_db
            user_manager.get_db = orig_um_get_db
