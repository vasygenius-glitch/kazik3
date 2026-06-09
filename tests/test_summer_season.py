import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Mock firebase_admin.firestore_async before any imports to avoid transactional wrapper errors
mock_fa_async = MagicMock()
mock_fa_async.transactional = lambda f: f
mock_fa_async.async_transactional = lambda f: f

sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin'].firestore_async = mock_fa_async
sys.modules['firebase_admin.firestore_async'] = mock_fa_async

# Ensure config module (which might be a MagicMock from other tests) has real summer config values
import config
config.SUMMER_COURAGE_ENABLED = True
config.SUMMER_WIN_CHANCE_BOOST = 15
config.SUMMER_DEPOSIT_BOOST = 0.20

import pytest
import time
from chances import get_game_chance
from profile_bank import process_deposit_tx
from seasons import cmd_beach_spin, cmd_summer_case, cmd_resort_invest
from promo import cmd_promo

class MockFirestoreTransaction:
    def __init__(self, *args, **kwargs):
        pass
    async def _begin(self, *args, **kwargs):
        pass
    async def _commit(self, *args, **kwargs):
        pass
    async def _rollback(self, *args, **kwargs):
        pass
    async def get(self, *args, **kwargs):
        pass
    def update(self, *args, **kwargs):
        pass
    def set(self, *args, **kwargs):
        pass

@pytest.mark.asyncio
async def test_summer_win_chance_boost():
    mock_season = {"active": True, "id": "summer"}
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"slots": 35}
    mock_db.collection.return_value.document.return_value.get = AsyncMock(return_value=mock_doc)
    with patch("seasons.get_season_config", new_callable=AsyncMock, return_value=mock_season), \
         patch("chances.get_db", return_value=mock_db):
        chance = await get_game_chance("slots")
        assert chance == 50

@pytest.mark.asyncio
async def test_summer_deposit_boost():
    mock_season = {"active": True, "id": "summer"}
    mock_tx = MagicMock()
    mock_db = MagicMock()
    
    mock_user_ref = MagicMock()
    mock_bank_ref = MagicMock()
    
    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {"balance": 10000, "bank_deposit": 0, "bank_name": None}
    
    mock_bank_snap = MagicMock()
    mock_bank_snap.exists = True
    mock_bank_snap.to_dict.return_value = {"capital": 5000}
    
    async def mock_get_snapshot(tx, ref):
        if ref == mock_user_ref:
            return mock_user_snap
        return mock_bank_snap

    with patch("seasons.get_season_config", new_callable=AsyncMock, return_value=mock_season), \
         patch("profile_bank.get_db", return_value=mock_db), \
         patch("user_manager.get_user_ref", return_value=mock_user_ref), \
         patch("user_manager.safe_get_snapshot", side_effect=mock_get_snapshot):
        
        # Mock collection references
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_bank_ref
        
        actual, total = await process_deposit_tx(mock_tx, 123, 456, 789, 1000)
        
        assert actual == 1000
        assert total == 1200
        mock_tx.update.assert_any_call(mock_user_ref, {
            'balance': 9000,
            'bank_deposit': 1200,
            'bank_name': 789,
            'deposit_start_time': pytest.approx(time.time(), abs=2)
        })
        mock_tx.update.assert_any_call(mock_bank_ref, {'capital': 6200})

@pytest.mark.asyncio
async def test_summer_promo_boost():
    mock_season = {"active": True, "id": "summer"}
    message = AsyncMock()
    message.text = "/promo MYCODE"
    message.chat.id = 123
    message.from_user.id = 456
    
    mock_user_snap = MagicMock()
    mock_user_snap.exists = True
    mock_user_snap.to_dict.return_value = {
        'reward': 1000,
        'max_activations': 10,
        'used_by': []
    }
    
    mock_tx = MockFirestoreTransaction()
    mock_tx.get = AsyncMock(return_value=mock_user_snap)
    mock_db = MagicMock()
    mock_db.transaction.return_value = mock_tx

    with patch("promo.get_db", return_value=mock_db), \
         patch("promo.update_user_balance", new_callable=AsyncMock) as mock_update_bal, \
         patch("promo.safe_get_snapshot", new_callable=AsyncMock, return_value=mock_user_snap), \
         patch("seasons.get_season_config", new_callable=AsyncMock, return_value=mock_season), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        
        await cmd_promo(message)
        
        mock_update_bal.assert_called_once_with(123, 456, 1200)
        assert "1200" in message.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_beach_spin_command():
    mock_season = {"active": True, "id": "summer"}
    message = AsyncMock()
    message.text = "/beach_spin 100"
    message.chat.id = 123
    message.from_user.id = 456
    
    mock_user_data = {"balance": 1000}
    
    with patch("seasons.get_season_config", new_callable=AsyncMock, return_value=mock_season), \
         patch("seasons.get_user_data", new_callable=AsyncMock, return_value=mock_user_data, create=True), \
         patch("seasons.update_user_balance", new_callable=AsyncMock, create=True) as mock_update_bal, \
         patch("random.random", return_value=0.98), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        
        await cmd_beach_spin(message)
        
        mock_update_bal.assert_any_call(123, 456, -100, action='Beach Spin Bet')
        mock_update_bal.assert_any_call(123, 456, 500, action='Beach Spin Win')

@pytest.mark.asyncio
async def test_summer_case_command():
    mock_season = {"active": True, "id": "summer"}
    message = AsyncMock()
    message.text = "/summer_case"
    message.chat.id = 123
    message.from_user.id = 456
    
    mock_user_data = {"balance": 15000}
    
    with patch("seasons.get_season_config", new_callable=AsyncMock, return_value=mock_season), \
         patch("seasons.get_user_data", new_callable=AsyncMock, return_value=mock_user_data, create=True), \
         patch("seasons.update_user_balance", new_callable=AsyncMock, create=True) as mock_update_bal, \
         patch("random.random", return_value=0.97), \
         patch("random.randint", return_value=12000), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        
        await cmd_summer_case(message)
        
        mock_update_bal.assert_any_call(123, 456, -10000, action='Summer Case Open')
        mock_update_bal.assert_any_call(123, 456, 12000, action='Summer Case Reward')

@pytest.mark.asyncio
async def test_resort_invest_command():
    mock_season = {"active": True, "id": "summer"}
    message = AsyncMock()
    message.text = "/resort_invest 10000"
    message.chat.id = 123
    message.from_user.id = 456
    
    mock_user_data = {"balance": 50000, "last_resort_invest_time": 0}
    
    with patch("seasons.get_season_config", new_callable=AsyncMock, return_value=mock_season), \
         patch("seasons.get_user_data", new_callable=AsyncMock, return_value=mock_user_data, create=True), \
         patch("seasons.update_user_balance", new_callable=AsyncMock, create=True) as mock_update_bal, \
         patch("seasons.update_user_field", new_callable=AsyncMock, create=True) as mock_update_field, \
         patch("random.random", return_value=0.1), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        
        await cmd_resort_invest(message)
        
        mock_update_bal.assert_any_call(123, 456, -10000, action='Resort Invest')
        mock_update_field.assert_called_once()
        mock_update_bal.assert_any_call(123, 456, 15000, action='Resort Invest Profit')
