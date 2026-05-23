import pytest
import sys
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
sys.modules['economy_utils'] = MagicMock()


import rp_clans

@pytest.fixture
def setup_duel():
    def _setup(duel_id, turn_id, p1_id, p2_id, p1_cover=False, p2_cover=False, p1_acc=10, p2_acc=10):
        rp_clans.active_duels[duel_id] = {
            'state': 'active',
            'bet': 100,
            'p1': {'id': p1_id, 'name': 'Player 1', 'acc': p1_acc, 'cover': p1_cover},
            'p2': {'id': p2_id, 'name': 'Player 2', 'acc': p2_acc, 'cover': p2_cover},
            'turn': turn_id
        }

    yield _setup
    rp_clans.active_duels.clear()

@pytest.mark.asyncio
async def test_duel_god_mode_creator_shoots(setup_duel):
    chat_id = 123
    creator_id = 999
    enemy_id = 456
    # DO NOT USE UNDERSCORES IN DUEL_ID because it splits by underscore!
    duel_id = "testduel1"

    # Creator shoots, enemy is in cover
    setup_duel(duel_id, creator_id, creator_id, enemy_id, p2_cover=True)

    callback = AsyncMock()
    callback.data = f"tduel_{duel_id}_shoot"
    callback.from_user.id = creator_id
    callback.message.chat.id = chat_id

    sys.modules['diseases'].get_active_diseases = AsyncMock(return_value=[])
    sys.modules['economy_utils'].get_global_tax = AsyncMock(return_value=10)

    with patch("rp_clans.update_user_balance", new_callable=AsyncMock) as mock_update, \
         patch("rp_clans.render_tactical_duel", new_callable=AsyncMock) as mock_render:

        await rp_clans.callback_tactical_duel(callback)

        # Win pool = 200, tax = 20, creator gets 180
        mock_update.assert_called_once_with(chat_id, creator_id, 180)
        assert duel_id not in rp_clans.active_duels
        assert mock_render.call_count == 0

@pytest.mark.asyncio
async def test_duel_god_mode_enemy_shoots_creator(setup_duel):
    chat_id = 123
    creator_id = 999
    enemy_id = 456
    duel_id = "testduel2"

    # Enemy shoots creator, enemy has 90% acc
    setup_duel(duel_id, enemy_id, enemy_id, creator_id, p1_acc=90)

    callback = AsyncMock()
    callback.data = f"tduel_{duel_id}_shoot"
    callback.from_user.id = enemy_id
    callback.message.chat.id = chat_id

    sys.modules['diseases'].get_active_diseases = AsyncMock(return_value=[])

    with patch("rp_clans.update_user_balance", new_callable=AsyncMock) as mock_update, \
         patch("rp_clans.secrets.SystemRandom.randint", return_value=1), \
         patch("rp_clans.render_tactical_duel", new_callable=AsyncMock) as mock_render:

        await rp_clans.callback_tactical_duel(callback)

        # Enemy should miss, creator balance is not updated
        mock_update.assert_not_called()
        assert duel_id in rp_clans.active_duels
        assert rp_clans.active_duels[duel_id]['turn'] == creator_id
        mock_render.assert_called_once()


@pytest.mark.asyncio
async def test_clan_info_when_in_clan():
    chat_id = 123
    user_id = 999
    
    message = AsyncMock()
    message.chat.id = chat_id
    message.from_user.id = user_id
    message.from_user.full_name = "Boss"
    message.text = "/clan info"
    
    mock_user_data = {
        'clan': 'GangsOfNY',
        'balance': 100000,
        'full_name': 'Boss'
    }
    
    mock_clan_data = {
        'leader_id': user_id,
        'deputy_ids': [],
        'treasury': 50000,
        'members': [user_id]
    }
    
    # Mock doc snapshot
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = mock_clan_data
    
    # Mock clan ref
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock) as mock_get_user, \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock) as mock_get_clan_ref:
        
        mock_get_user.side_effect = lambda chat, uid, *args: mock_user_data if uid == user_id else {'full_name': 'Player'}
        mock_get_clan_ref.return_value = mock_ref
        
        await rp_clans.cmd_clan(message)
        
        # Verify message answer is called with correct info
        message.answer.assert_called_once()
        args, kwargs = message.answer.call_args
        assert "GangsOfNY" in args[0]
        assert "Boss" in args[0]
        assert "50000" in args[0]


@pytest.mark.asyncio
async def test_clan_promote_demote():
    chat_id = 123
    leader_id = 999
    member_id = 777
    
    message = AsyncMock()
    message.chat.id = chat_id
    message.from_user.id = leader_id
    message.from_user.full_name = "Boss"
    message.text = "/clan promote"
    
    message.reply_to_message = AsyncMock()
    message.reply_to_message.from_user.id = member_id
    message.reply_to_message.from_user.full_name = "Soldier"
    
    mock_leader_data = {'clan': 'GangsOfNY', 'balance': 100000, 'full_name': 'Boss'}
    
    mock_clan_data = {
        'leader_id': leader_id,
        'deputy_ids': [],
        'treasury': 50000,
        'members': [leader_id, member_id]
    }
    
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = mock_clan_data
    
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_doc
    mock_ref.update = AsyncMock()
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock) as mock_get_user, \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock) as mock_get_clan_ref:
         
        mock_get_user.side_effect = lambda chat, uid, *args: mock_leader_data if uid == leader_id else {'full_name': 'Soldier'}
        mock_get_clan_ref.return_value = mock_ref
        
        # Promote
        await rp_clans.cmd_clan(message)
        mock_ref.update.assert_called_with({'deputy_ids': [member_id]})
        
        # Demote
        message.text = "/clan demote"
        mock_clan_data['deputy_ids'] = [member_id]
        await rp_clans.cmd_clan(message)
        mock_ref.update.assert_called_with({'deputy_ids': []})


@pytest.mark.asyncio
async def test_clan_create_enforces_min_balance():
    chat_id = 123
    user_id = 999
    
    message = AsyncMock()
    message.chat.id = chat_id
    message.from_user.id = user_id
    message.text = "/clan create NewClan"
    
    mock_doc = MagicMock()
    mock_doc.exists = False
    
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock) as mock_get_user, \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock) as mock_get_clan_ref, \
         patch("rp_clans.update_user_balance", new_callable=AsyncMock) as mock_update:
         
        mock_get_user.return_value = {'clan': None, 'balance': 60000}
        mock_get_clan_ref.return_value = mock_ref
        
        # When update_user_balance returns None (e.g. min_balance check failed due to concurrent spend)
        mock_update.return_value = None
        
        await rp_clans.cmd_clan(message)
        
        mock_update.assert_called_once_with(chat_id, user_id, -50000, min_balance=0)
        message.answer.assert_called_once_with("Для создания клана нужно 50.000 сыроежек.")


@pytest.mark.asyncio
async def test_clan_deposit_enforces_min_balance():
    chat_id = 123
    user_id = 999
    
    message = AsyncMock()
    message.chat.id = chat_id
    message.from_user.id = user_id
    message.text = "/clan deposit 1000"
    
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {'treasury': 5000}
    
    mock_ref = AsyncMock()
    mock_ref.get.return_value = mock_doc
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock) as mock_get_user, \
         patch("rp_clans.get_clan_ref", new_callable=AsyncMock) as mock_get_clan_ref, \
         patch("rp_clans.update_user_balance", new_callable=AsyncMock) as mock_update:
         
        mock_get_user.return_value = {'clan': 'SomeClan', 'balance': 2000}
        mock_get_clan_ref.return_value = mock_ref
        
        mock_update.return_value = None
        
        await rp_clans.cmd_clan(message)
        
        mock_update.assert_called_once_with(chat_id, user_id, -1000, min_balance=0)
        message.answer.assert_called_once_with("Недостаточно средств.")


@pytest.mark.asyncio
async def test_wedding_gift_enforces_min_balance():
    chat_id = 123
    user_id = 999
    
    message = AsyncMock()
    message.chat.id = chat_id
    message.from_user.id = user_id
    message.text = "подарок 1000"
    
    message.reply_to_message = MagicMock()
    btn = MagicMock()
    btn.callback_data = "marry_yes_m1"
    message.reply_to_message.reply_markup = MagicMock()
    message.reply_to_message.reply_markup.inline_keyboard = [[btn]]
    
    rp_clans.active_marriages["m1"] = {
        'amount': 0,
        'from_id': user_id,
        'to_id': 888
    }
    
    with patch("rp_clans.get_user_data", new_callable=AsyncMock) as mock_get_user, \
         patch("rp_clans.update_user_balance", new_callable=AsyncMock) as mock_update:
         
        mock_get_user.return_value = {'balance': 2000}
        mock_update.return_value = None  # min_balance failure
        
        await rp_clans.cmd_gift(message)
        
        mock_update.assert_called_once_with(chat_id, user_id, -1000, min_balance=0)
        message.answer.assert_called_once_with("У вас недостаточно сыроежек для такого подарка.")
