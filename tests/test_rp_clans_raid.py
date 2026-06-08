import pytest
import sys
import time
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
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()
sys.modules['config'].CREATOR_ID = 999
import economy_utils

import rp_clans

# --- Helpers ---
def create_mock_message(text, user_id=111, chat_id=123, is_reply=False, target_id=222):
    msg = AsyncMock()
    msg.text = text
    msg.chat.id = chat_id
    msg.from_user.id = user_id
    msg.from_user.full_name = "User"
    if is_reply:
        msg.reply_to_message = AsyncMock()
        msg.reply_to_message.from_user.id = target_id
        msg.reply_to_message.from_user.full_name = "Target"
        msg.reply_to_message.from_user.is_bot = False
    else:
        msg.reply_to_message = None
    return msg

@pytest.fixture(autouse=True)
def cleanup():
    rp_clans.active_clan_raids.clear()
    rp_clans.active_clan_invites.clear()
    yield

# --- Tests for /clan raid ---

@pytest.mark.asyncio
async def test_raid_fail_not_in_clan():
    msg = create_mock_message("/clan raid enemy")
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': None}):
        await rp_clans.cmd_clan(msg)
        assert "не состоите в клане" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_raid_fail_not_leader():
    msg = create_mock_message("/clan raid enemy", user_id=111)
    
    mock_clan_doc = MagicMock()
    mock_clan_doc.exists = True
    mock_clan_doc.to_dict.return_value = {
        'leader_id': 222,
        'deputy_ids': [],
        'members': [111, 222],
        'treasury': 5000
    }
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_clan_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=mock_ref):
        await rp_clans.cmd_clan(msg)
        assert "могут только Лидер и Заместители" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_raid_fail_no_target():
    msg = create_mock_message("/clan raid", user_id=222)
    
    mock_clan_doc = MagicMock()
    mock_clan_doc.exists = True
    mock_clan_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000}
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_clan_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=mock_ref):
        await rp_clans.cmd_clan(msg)
        assert "Укажите клан для нападения" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_raid_fail_self_attack():
    msg = create_mock_message("/clan raid MyClan", user_id=222)
    
    mock_clan_doc = MagicMock()
    mock_clan_doc.exists = True
    mock_clan_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000}
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_clan_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=mock_ref):
        await rp_clans.cmd_clan(msg)
        assert "Нельзя напасть на свой же клан" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_raid_fail_target_not_found():
    msg = create_mock_message("/clan raid Enemy", user_id=222)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    enemy_doc = MagicMock()
    enemy_doc.exists = False
    enemy_ref = AsyncMock()
    enemy_ref.get.return_value = enemy_doc
    
    def get_clan_ref_side_effect(chat_id, clan_name):
        if clan_name == 'MyClan': return my_ref
        return enemy_ref
        
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, side_effect=get_clan_ref_side_effect):
        await rp_clans.cmd_clan(msg)
        assert "Вражеский клан не найден" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_raid_fail_low_own_treasury():
    msg = create_mock_message("/clan raid Enemy", user_id=222)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 500} # < 1000
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    enemy_doc = MagicMock()
    enemy_doc.exists = True
    enemy_doc.to_dict.return_value = {'leader_id': 333, 'treasury': 5000}
    enemy_ref = AsyncMock()
    enemy_ref.get.return_value = enemy_doc
    
    def get_clan_ref_side_effect(chat_id, clan_name):
        if clan_name == 'MyClan': return my_ref
        return enemy_ref
        
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, side_effect=get_clan_ref_side_effect):
        await rp_clans.cmd_clan(msg)
        assert "минимум 1000 сыроежек" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_raid_fail_low_target_treasury():
    msg = create_mock_message("/clan raid Enemy", user_id=222)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    enemy_doc = MagicMock()
    enemy_doc.exists = True
    enemy_doc.to_dict.return_value = {'leader_id': 333, 'treasury': 500} # < 1000
    enemy_ref = AsyncMock()
    enemy_ref.get.return_value = enemy_doc
    
    def get_clan_ref_side_effect(chat_id, clan_name):
        if clan_name == 'MyClan': return my_ref
        return enemy_ref
        
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, side_effect=get_clan_ref_side_effect):
        await rp_clans.cmd_clan(msg)
        assert "слишком бедная казна" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_raid_cooldown():
    msg = create_mock_message("/clan raid Enemy", user_id=222)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    enemy_doc = MagicMock()
    enemy_doc.exists = True
    enemy_doc.to_dict.return_value = {'leader_id': 333, 'treasury': 5000}
    enemy_ref = AsyncMock()
    enemy_ref.get.return_value = enemy_doc
    
    def get_clan_ref_side_effect(chat_id, clan_name):
        if clan_name == 'MyClan': return my_ref
        return enemy_ref
        
    rp_clans.active_clan_raids['123_MyClan'] = time.time() - 100 # Cooldown active
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, side_effect=get_clan_ref_side_effect):
        await rp_clans.cmd_clan(msg)
        assert "Ваши бойцы устали" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_raid_success():
    msg = create_mock_message("/clan raid Enemy", user_id=222)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111]}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    enemy_doc = MagicMock()
    enemy_doc.exists = True
    enemy_doc.to_dict.return_value = {'leader_id': 333, 'treasury': 10000, 'members': [333]}
    enemy_ref = AsyncMock()
    enemy_ref.get.return_value = enemy_doc
    
    def get_clan_ref_side_effect(chat_id, clan_name):
        if clan_name == 'MyClan': return my_ref
        return enemy_ref
        
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, side_effect=get_clan_ref_side_effect), \
         patch("random.randint", side_effect=[1, 20]): # 1 = win (chance > 1), 20 = 20% steal
         
        await rp_clans.cmd_clan(msg)
        enemy_ref.update.assert_called_once_with({'treasury': 8000})
        my_ref.update.assert_called_once_with({'treasury': 7000})
        assert "УСПЕШНЫЙ НАБЕГ" in msg.answer.call_args[0][0]
        assert "2000" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_raid_fail_defense():
    msg = create_mock_message("/clan raid Enemy", user_id=222)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111]}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    enemy_doc = MagicMock()
    enemy_doc.exists = True
    enemy_doc.to_dict.return_value = {'leader_id': 333, 'treasury': 10000, 'members': [333]}
    enemy_ref = AsyncMock()
    enemy_ref.get.return_value = enemy_doc
    
    def get_clan_ref_side_effect(chat_id, clan_name):
        if clan_name == 'MyClan': return my_ref
        return enemy_ref
        
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, side_effect=get_clan_ref_side_effect), \
         patch("random.randint", side_effect=[100, 20]): # 100 = lose (chance < 100), 20 = 20% loss
         
        await rp_clans.cmd_clan(msg)
        my_ref.update.assert_called_once_with({'treasury': 4000})
        assert "ПРОВАЛ НАБЕГА" in msg.answer.call_args[0][0]
        assert "1000" in msg.answer.call_args[0][0]

# --- Tests for other clan commands ---

@pytest.mark.asyncio
async def test_clan_disband_success():
    msg = create_mock_message("/clan disband", user_id=222)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111]}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=my_ref), \
         patch("rp_clans.update_user_field", new_callable=AsyncMock) as mock_field:
        
        await rp_clans.cmd_clan(msg)
        my_ref.delete.assert_called_once()
        assert mock_field.call_count == 2
        assert "распущен" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_clan_disband_fail_not_leader():
    msg = create_mock_message("/clan disband", user_id=111)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111]}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=my_ref):
        
        await rp_clans.cmd_clan(msg)
        assert "только Лидер" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_clan_leave_success():
    msg = create_mock_message("/clan leave", user_id=111)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111], 'deputy_ids': []}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=my_ref), \
         patch("rp_clans.update_user_field", new_callable=AsyncMock) as mock_field:
        
        await rp_clans.cmd_clan(msg)
        my_ref.update.assert_called_once_with({'members': [222], 'deputy_ids': []})
        mock_field.assert_called_once_with(123, 111, 'clan', None)
        assert "Вы покинули клан" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_clan_leave_fail_leader():
    msg = create_mock_message("/clan leave", user_id=222)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111]}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=my_ref):
        
        await rp_clans.cmd_clan(msg)
        assert "Лидер не может просто так покинуть" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_clan_kick_success():
    msg = create_mock_message("/clan kick", user_id=222, is_reply=True, target_id=111)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111], 'deputy_ids': []}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=my_ref), \
         patch("rp_clans.update_user_field", new_callable=AsyncMock) as mock_field:
        
        await rp_clans.cmd_clan(msg)
        my_ref.update.assert_called_once_with({'members': [222], 'deputy_ids': []})
        mock_field.assert_called_once_with(123, 111, 'clan', None)
        assert "изгнан из клана" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_clan_kick_fail_kick_leader():
    msg = create_mock_message("/clan kick", user_id=111, is_reply=True, target_id=222)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111], 'deputy_ids': [111]}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=my_ref):
        
        await rp_clans.cmd_clan(msg)
        assert "Нельзя кикнуть лидера" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_clan_transfer_success():
    msg = create_mock_message("/clan transfer", user_id=222, is_reply=True, target_id=111)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111], 'deputy_ids': []}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': 'MyClan'}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=my_ref):
        
        await rp_clans.cmd_clan(msg)
        my_ref.update.assert_called_once_with({'leader_id': 111, 'deputy_ids': []})
        assert "успешно передано" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_clan_invite_success():
    msg = create_mock_message("/clan invite", user_id=222, is_reply=True, target_id=333)
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'treasury': 5000, 'members': [222, 111]}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    def get_user_data_side_effect(chat_id, user_id, *args):
        if user_id == 222: return {'clan': 'MyClan'}
        return {'clan': None}
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, side_effect=get_user_data_side_effect), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=my_ref):
        
        await rp_clans.cmd_clan(msg)
        assert len(rp_clans.active_clan_invites) == 1
        assert "Приглашение в клан" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_clan_invite_accept():
    cb = AsyncMock()
    cb.data = "claninv_yes_testinvite1"
    cb.from_user.id = 333
    cb.message.chat.id = 123
    cb.from_user.full_name = "Target"
    
    rp_clans.active_clan_invites["testinvite1"] = {'target': 333, 'clan_name': 'MyClan'}
    
    my_doc = MagicMock()
    my_doc.exists = True
    my_doc.to_dict.return_value = {'leader_id': 222, 'members': [222]}
    my_ref = AsyncMock()
    my_ref.get.return_value = my_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock, return_value={'clan': None}), \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock, return_value=my_ref), \
         patch("rp_clans.update_user_field", new_callable=AsyncMock) as mock_field:
        
        await rp_clans.callback_claninv(cb)
        my_ref.update.assert_called_once_with({'members': [222, 333]})
        mock_field.assert_called_once_with(123, 333, 'clan', 'MyClan')
        assert "успешно вступил" in cb.message.edit_text.call_args[0][0]

@pytest.mark.asyncio
async def test_clan_invite_reject():
    cb = AsyncMock()
    cb.data = "claninv_no_testinvite2"
    cb.from_user.id = 333
    cb.message.chat.id = 123
    
    rp_clans.active_clan_invites["testinvite2"] = {'target': 333, 'clan_name': 'MyClan'}
    
    await rp_clans.callback_claninv(cb)
    assert "testinvite2" not in rp_clans.active_clan_invites
    assert "отклонено" in cb.message.edit_text.call_args[0][0]
