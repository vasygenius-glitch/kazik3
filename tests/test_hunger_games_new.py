import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hunger_games import join_hg_tr, distribute_prizes_tr
import time

@pytest.mark.asyncio
async def test_join_hg_tr_success():
    transaction = MagicMock()
    chat_id = 123
    user_id = 456
    base_bet = 1000

    # Mock snapshot
    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.to_dict.return_value = {
        'balance': 2000,
        'is_vip': False,
        'inventory': {'condom': 1},
        'diseases': {},
        'full_name': 'Test User'
    }

    with patch('hunger_games.get_user_ref') as mock_ref, \
         patch('hunger_games.safe_get_snapshot', new_callable=AsyncMock) as mock_snap:

        # For mock_snap, AsyncMock should return snapshot directly but since side_effect is sometimes used
        async def mock_safe_get_snapshot(*args, **kwargs):
            return snapshot
        mock_snap.side_effect = mock_safe_get_snapshot

        # Extract unwrapped function because @firestore_async.transactional wraps it
        from hunger_games import join_hg_tr
        unwrapped = join_hg_tr.__dict__.get('to_wrap', join_hg_tr)

        # Check if the unwrapped function is still awaitable, and call it
        res = unwrapped(transaction, chat_id, user_id, base_bet)
        if hasattr(res, '__await__'):
            player_data, error, updates = await res
        else:
            player_data, error, updates = res

        assert error is None
        assert player_data['id'] == user_id
        assert player_data['bet_paid'] == 1000
        assert player_data['has_condom'] is True
        transaction.update.assert_called_once()
        # Check that balance was deducted and condom removed
        assert updates['balance'] == 1000
        assert 'condom' not in updates['inventory']

@pytest.mark.asyncio
async def test_join_hg_tr_vip_discount():
    transaction = MagicMock()
    chat_id = 123
    user_id = 456
    base_bet = 1000

    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.to_dict.return_value = {
        'balance': 2000,
        'is_vip': True,
        'inventory': {},
        'diseases': {},
        'full_name': 'VIP User'
    }

    with patch('hunger_games.get_user_ref'), \
         patch('hunger_games.safe_get_snapshot', new_callable=AsyncMock) as mock_snap:

        # For mock_snap, AsyncMock should return snapshot directly but since side_effect is sometimes used
        async def mock_safe_get_snapshot(*args, **kwargs):
            return snapshot
        mock_snap.side_effect = mock_safe_get_snapshot

        # Extract unwrapped function because @firestore_async.transactional wraps it
        from hunger_games import join_hg_tr
        unwrapped = join_hg_tr.__dict__.get('to_wrap', join_hg_tr)

        res = unwrapped(transaction, chat_id, user_id, base_bet)
        if hasattr(res, '__await__'):
            player_data, error, updates = await res
        else:
            player_data, error, updates = res

        assert error is None
        assert player_data['bet_paid'] == 800 # 20% discount
        assert updates['balance'] == 1200

@pytest.mark.asyncio
async def test_distribute_prizes_tr():
    transaction = MagicMock()
    chat_id = 123
    winner_id = 1
    prize = 5000
    host_id = 2
    fee = 250
    winner_diseases = ['hiv']

    winner_snap = MagicMock()
    winner_snap.exists = True
    winner_snap.to_dict.return_value = {'balance': 0, 'diseases': {}}

    host_snap = MagicMock()
    host_snap.exists = True
    host_snap.to_dict.return_value = {'balance': 0}

    with patch('hunger_games.get_user_ref'), \
         patch('hunger_games.safe_get_snapshot', new_callable=AsyncMock) as mock_snap:

        async def mock_safe_get_snapshot(*args, **kwargs):
            if mock_safe_get_snapshot.call_count == 0:
                mock_safe_get_snapshot.call_count += 1
                return winner_snap
            else:
                return host_snap
        mock_safe_get_snapshot.call_count = 0
        mock_snap.side_effect = mock_safe_get_snapshot

        # Extract unwrapped function because @firestore_async.transactional wraps it
        from hunger_games import distribute_prizes_tr
        unwrapped = distribute_prizes_tr.__dict__.get('to_wrap', distribute_prizes_tr)

        res = unwrapped(transaction, chat_id, winner_id, prize, host_id, fee, winner_diseases)
        if hasattr(res, '__await__'):
            winner_upd, host_upd = await res
        else:
            winner_upd, host_upd = res

        assert winner_upd['balance'] == 5000
        assert 'hiv' in winner_upd['diseases']
        assert host_upd['balance'] == 250
        assert transaction.update.call_count == 2
