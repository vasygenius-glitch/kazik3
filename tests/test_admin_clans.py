import pytest
import sys
import hashlib
from unittest.mock import AsyncMock, patch, MagicMock

# Mock external dependencies
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
sys.modules['config'].CREATOR_ID = 999
sys.modules['config'].CREATOR_USERNAME = 'admin_creator'

import admin_dashboard
from chances import get_game_chance_sync

@pytest.mark.asyncio
async def test_get_game_chance_sync():
    import chances
    chances._chances_cache = {'slots': 45}
    assert get_game_chance_sync('slots') == 45
    assert get_game_chance_sync('craps') == -1

@pytest.mark.asyncio
async def test_cb_clan_view_parsing_with_underscores():
    clan_name = "Awesome_Clan_Name"
    clan_hash = hashlib.md5(clan_name.encode('utf-8')).hexdigest()[:16]
    
    callback = AsyncMock()
    callback.data = f"db_clan_view_12345_{clan_hash}"
    callback.from_user.id = 999
    callback.from_user.username = 'admin_creator'
    callback.message.chat.id = 12345
    
    state = AsyncMock()
    
    with patch("admin_dashboard.show_clan_detail_screen", new_callable=AsyncMock) as mock_show, \
         patch("admin_dashboard.get_clan_name_by_hash", return_value="Awesome_Clan_Name") as mock_hash:
        await admin_dashboard.cb_clan_view(callback, state)
        mock_hash.assert_called_once_with(12345, clan_hash)
        mock_show.assert_called_once_with(callback, state, 12345, "Awesome_Clan_Name")

@pytest.mark.asyncio
async def test_cb_clan_treasury_parsing_with_underscores():
    clan_name = "My_New_Clan"
    clan_hash = hashlib.md5(clan_name.encode('utf-8')).hexdigest()[:16]
    
    callback = AsyncMock()
    callback.data = f"db_clan_treasury_12345_{clan_hash}"
    callback.from_user.id = 999
    callback.from_user.username = 'admin_creator'
    
    state = AsyncMock()
    
    with patch("admin_dashboard.AdminPanelState.waiting_for_clan_treasury", new=MagicMock()) as mock_state, \
         patch("admin_dashboard.get_clan_name_by_hash", return_value="My_New_Clan") as mock_hash:
        await admin_dashboard.cb_clan_treasury_prompt(callback, state)
        state.set_state.assert_called_once()
        state.update_data.assert_called_once_with(chat_id=12345, clan_name="My_New_Clan", menu_message_id=callback.message.message_id)

@pytest.mark.asyncio
async def test_cb_clan_promote_demote():
    clan_name = "Clan_A"
    clan_hash = hashlib.md5(clan_name.encode('utf-8')).hexdigest()[:16]
    
    callback = AsyncMock()
    callback.data = f"db_clan_prom_12345_77777_{clan_hash}"
    callback.from_user.id = 999
    callback.from_user.username = 'admin_creator'
    
    state = AsyncMock()
    
    mock_clan_data = {
        'leader_id': 999,
        'deputy_ids': [],
        'members': [999, 77777],
        'treasury': 1000
    }
    
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = mock_clan_data
    
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_doc
    mock_ref.update = AsyncMock()
    
    # Mock Firestore Collection
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_ref
    
    with patch("admin_dashboard.get_db", return_value=mock_db), \
         patch("admin_dashboard.get_clan_name_by_hash", return_value="Clan_A") as mock_hash, \
         patch("admin_dashboard.cb_clan_member_view", new_callable=AsyncMock) as mock_view:
        
        await admin_dashboard.cb_clan_promote(callback, state)
        mock_hash.assert_called_once_with(12345, clan_hash)
        mock_ref.update.assert_called_once_with({'deputy_ids': [77777]})
        mock_view.assert_called_once_with(callback, state)

@pytest.mark.asyncio
async def test_cb_clan_kick():
    clan_name = "Clan_A"
    clan_hash = hashlib.md5(clan_name.encode('utf-8')).hexdigest()[:16]
    
    callback = AsyncMock()
    callback.data = f"db_clan_kck_12345_77777_{clan_hash}"
    callback.from_user.id = 999
    callback.from_user.username = 'admin_creator'
    
    state = AsyncMock()
    
    mock_clan_data = {
        'leader_id': 999,
        'deputy_ids': [77777],
        'members': [999, 77777],
        'treasury': 1000
    }
    
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = mock_clan_data
    
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_doc
    mock_ref.update = AsyncMock()
    
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_ref
    
    with patch("admin_dashboard.get_db", return_value=mock_db), \
         patch("admin_dashboard.get_clan_name_by_hash", return_value="Clan_A") as mock_hash, \
         patch("admin_dashboard.update_user_field", new_callable=AsyncMock) as mock_update_field, \
         patch("admin_dashboard.flush_user_cache_immediately", new_callable=AsyncMock) as mock_flush, \
         patch("admin_dashboard.cb_clan_members_list", new_callable=AsyncMock) as mock_list:
        
        await admin_dashboard.cb_clan_kick(callback, state)
        mock_hash.assert_called_once_with(12345, clan_hash)
        mock_ref.update.assert_called_once_with({'members': [999], 'deputy_ids': []})
        mock_update_field.assert_called_once_with(12345, 77777, 'clan', None)
        mock_flush.assert_called_once_with(12345, 77777)
        mock_list.assert_called_once_with(callback, state)


@pytest.mark.asyncio
async def test_parse_clan_callback_compatibility():
    from admin_dashboard import parse_clan_callback, get_clan_hash
    
    clan_name = "My_Special_Clan"
    clan_hash = get_clan_hash(clan_name)
    
    # Mock get_clan_name_by_hash to resolve clan_hash to clan_name
    with patch("admin_dashboard.get_clan_name_by_hash", return_value=clan_name) as mock_hash:
        # Test new format (hashed)
        chat_id, resolved_name, member_id = await parse_clan_callback(f"db_clan_view_12345_{clan_hash}")
        assert chat_id == 12345
        assert resolved_name == clan_name
        assert member_id is None
        
        chat_id, resolved_name, member_id = await parse_clan_callback(f"db_clan_mem_12345_77777_{clan_hash}")
        assert chat_id == 12345
        assert resolved_name == clan_name
        assert member_id == 77777
        
        chat_id, resolved_name, member_id = await parse_clan_callback(f"db_clan_kck_12345_77777_{clan_hash}")
        assert chat_id == 12345
        assert resolved_name == clan_name
        assert member_id == 77777

    # Mock get_clan_name_by_hash to return None (meaning hash not found, or it's old format)
    with patch("admin_dashboard.get_clan_name_by_hash", return_value=None):
        # Test old format (raw name with underscores/spaces)
        chat_id, resolved_name, member_id = await parse_clan_callback("db_clan_view_12345_My_Special_Clan")
        assert chat_id == 12345
        assert resolved_name == "My_Special_Clan"
        assert member_id is None
        
        # Test old format with spaces
        chat_id, resolved_name, member_id = await parse_clan_callback("db_clan_view_12345_DICKторы Тайний Баний")
        assert chat_id == 12345
        assert resolved_name == "DICKторы Тайний Баний"
        assert member_id is None
        
        chat_id, resolved_name, member_id = await parse_clan_callback("db_clan_members_list_12345_My_Special_Clan")
        assert chat_id == 12345
        assert resolved_name == "My_Special_Clan"
        assert member_id is None
        
        # Test old format with spaces
        chat_id, resolved_name, member_id = await parse_clan_callback("db_clan_members_list_12345_DICKторы Тайний Баний")
        assert chat_id == 12345
        assert resolved_name == "DICKторы Тайний Баний"
        assert member_id is None

        chat_id, resolved_name, member_id = await parse_clan_callback("db_clan_member_12345_77777_My_Special_Clan")
        assert chat_id == 12345
        assert resolved_name == "My_Special_Clan"
        assert member_id == 77777

        # Test old format with spaces
        chat_id, resolved_name, member_id = await parse_clan_callback("db_clan_member_12345_77777_DICKторы Тайний Баний")
        assert chat_id == 12345
        assert resolved_name == "DICKторы Тайний Баний"
        assert member_id == 77777

        chat_id, resolved_name, member_id = await parse_clan_callback("db_clan_kick_12345_77777_My_Special_Clan")
        assert chat_id == 12345
        assert resolved_name == "My_Special_Clan"
        assert member_id == 77777


