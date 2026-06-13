import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import poker

# Mock db and external services for safety
@pytest.fixture(autouse=True)
def mock_db_and_services():
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_doc.to_dict.return_value = {}
    mock_get = AsyncMock(return_value=mock_doc)
    mock_db.collection.return_value.document.return_value.get = mock_get
    mock_db.collection.return_value.document.return_value.set = AsyncMock()
    mock_db.collection.return_value.document.return_value.update = AsyncMock()
    with patch('db.get_db', return_value=mock_db), \
         patch('user_manager.get_user_data', new_callable=AsyncMock) as m_get, \
         patch('user_manager.update_user_balance', new_callable=AsyncMock) as m_upd:
        m_get.return_value = {'balance': 10000, 'is_banned': False}
        m_upd.return_value = 10000
        yield

def test_poker_001():
    assert poker is not None

def test_poker_002():
    assert hasattr(poker, 'router')
    assert poker.router is not None

def test_poker_003():
    assert hasattr(poker, 'is_better_combo')
    assert callable(getattr(poker, 'is_better_combo'))

def test_poker_004():
    assert hasattr(poker, 'update_stats')
    assert callable(getattr(poker, 'update_stats'))

def test_poker_005():
    assert hasattr(poker, 'calc_win_rate')
    assert callable(getattr(poker, 'calc_win_rate'))

def test_poker_006():
    assert hasattr(poker, 'get_stats_block')
    assert callable(getattr(poker, 'get_stats_block'))

def test_poker_007():
    assert hasattr(poker, 'make_random_card')
    assert callable(getattr(poker, 'make_random_card'))

def test_poker_008():
    assert hasattr(poker, 'is_card_in_list')
    assert callable(getattr(poker, 'is_card_in_list'))

def test_poker_009():
    assert hasattr(poker, 'get_unique_card')
    assert callable(getattr(poker, 'get_unique_card'))

def test_poker_010():
    assert hasattr(poker, 'deal_initial_hand')
    assert callable(getattr(poker, 'deal_initial_hand'))
