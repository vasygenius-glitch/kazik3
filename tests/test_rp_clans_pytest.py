import pytest
import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Mock external dependencies
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
