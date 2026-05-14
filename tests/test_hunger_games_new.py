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

        mock_snap.return_value = snapshot

        player_data, error = await join_hg_tr(transaction, chat_id, user_id, base_bet)

        assert error is None
        assert player_data['id'] == user_id
        assert player_data['bet_paid'] == 1000
        assert player_data['has_condom'] is True
        transaction.update.assert_called_once()
        # Check that balance was deducted and condom removed
        updates = transaction.update.call_args[0][1]
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

        mock_snap.return_value = snapshot

        player_data, error = await join_hg_tr(transaction, chat_id, user_id, base_bet)

        assert error is None
        assert player_data['bet_paid'] == 800 # 20% discount
        updates = transaction.update.call_args[0][1]
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

    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.to_dict.return_value = {'diseases': {}}

    with patch('hunger_games.update_user_balance_tr', new_callable=AsyncMock) as mock_upd_bal, \
         patch('hunger_games.get_user_ref'), \
         patch('hunger_games.safe_get_snapshot', new_callable=AsyncMock) as mock_snap:

        mock_snap.return_value = snapshot

        await distribute_prizes_tr(transaction, chat_id, winner_id, prize, host_id, fee, winner_diseases)

        assert mock_upd_bal.call_count == 2
        # Check that HIV was added to winner
        transaction.update.assert_called_once()
        updates = transaction.update.call_args[0][1]
        assert 'hiv' in updates['diseases']
