import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import user_manager

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

def test_user_manager_001():
    assert user_manager is not None

def test_user_manager_002():
    assert hasattr(user_manager, 'get_user_ref')
    assert callable(getattr(user_manager, 'get_user_ref'))

def test_user_manager_003():
    assert hasattr(user_manager, 'get_user_lock')
    assert callable(getattr(user_manager, 'get_user_lock'))

def test_user_manager_004():
    assert hasattr(user_manager, '_remove_username_from_index')
    assert callable(getattr(user_manager, '_remove_username_from_index'))

def test_user_manager_005():
    assert hasattr(user_manager, '_drop_cache_entry')
    assert callable(getattr(user_manager, '_drop_cache_entry'))

def test_user_manager_006():
    assert hasattr(user_manager, 'get_from_cache')
    assert callable(getattr(user_manager, 'get_from_cache'))

def test_user_manager_007():
    assert hasattr(user_manager, 'set_in_cache')
    assert callable(getattr(user_manager, 'set_in_cache'))

def test_user_manager_008():
    assert hasattr(user_manager, 'invalidate_user_cache')
    assert callable(getattr(user_manager, 'invalidate_user_cache'))

def test_user_manager_009():
    assert hasattr(user_manager, 'mark_dirty')
    assert callable(getattr(user_manager, 'mark_dirty'))

def test_user_manager_010():
    assert hasattr(user_manager, '_cleanup_unused_locks')
    assert callable(getattr(user_manager, '_cleanup_unused_locks'))
