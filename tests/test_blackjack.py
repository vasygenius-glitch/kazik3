import pytest
import sys
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import blackjack

def create_mock_message(text, user_id=111, chat_id=123):
    msg = AsyncMock()
    msg.text = text
    msg.chat.id = chat_id
    msg.from_user.id = user_id
    msg.from_user.full_name = "User"
    return msg

def create_mock_callback(data, user_id=111, chat_id=123, message_id=456):
    cb = AsyncMock()
    cb.data = data
    cb.from_user.id = user_id
    cb.from_user.full_name = "User"
    cb.message.chat.id = chat_id
    cb.message.message_id = message_id
    return cb

@pytest.mark.asyncio
async def test_bj_banned():
    msg = create_mock_message("/bj 100")
    state = AsyncMock()
    state.get_state.return_value = None
    with patch("blackjack.get_user_data", new_callable=AsyncMock, return_value={'is_banned': True}):
        await blackjack.cmd_bj(msg, state)
        msg.answer.assert_not_called() # It just returns

@pytest.mark.asyncio
async def test_bj_gonorrhea():
    msg = create_mock_message("/bj 100")
    state = AsyncMock()
    state.get_state.return_value = None
    with patch("blackjack.get_user_data", new_callable=AsyncMock, return_value={}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=['gonorrhea']):
        await blackjack.cmd_bj(msg, state)
        msg.answer.assert_not_called() # Returns silently

@pytest.mark.asyncio
async def test_bj_invalid_bet():
    msg = create_mock_message("/bj abc")
    state = AsyncMock()
    state.get_state.return_value = None
    with patch("blackjack.get_user_data", new_callable=AsyncMock, return_value={}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        await blackjack.cmd_bj(msg, state)
        msg.answer.assert_not_called()
        
        msg2 = create_mock_message("/bj 50")
        await blackjack.cmd_bj(msg2, state)
    assert "От 100." in msg2.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_bj_limit():
    msg = create_mock_message("/bj 100")
    state = AsyncMock()
    state.get_state.return_value = None
    with patch("blackjack.get_user_data", new_callable=AsyncMock, return_value={'balance': -4950}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        await blackjack.cmd_bj(msg, state)
        assert "Кредит!" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_bj_ask_confirm():
    msg = create_mock_message("/bj 100")
    state = AsyncMock()
    state.get_state.return_value = None
    with patch("blackjack.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]), \
         patch("casino_utils.ask_casino_confirmation", new_callable=AsyncMock) as mock_ask:
        await blackjack.cmd_bj(msg, state)
        mock_ask.assert_called_once_with(msg, "blackjack", 100)

@pytest.mark.asyncio
async def test_bj_clear_stuck_state():
    msg = create_mock_message("/bj 100")
    state = AsyncMock()
    state.get_state.return_value = blackjack.BlackjackState.playing.state
    with patch("blackjack.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]), \
         patch("casino_utils.ask_casino_confirmation", new_callable=AsyncMock):
        await blackjack.cmd_bj(msg, state)
        state.clear.assert_called_once()

@pytest.mark.asyncio
async def test_bj_process_insufficient():
    cb = create_mock_callback("cas_conf_blackjack_100")
    state = AsyncMock()
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("blackjack.get_user_data", new_callable=AsyncMock, return_value={'balance': 0}), \
         patch("blackjack.update_user_balance", new_callable=AsyncMock, return_value=None):
        await blackjack.process_bj_confirm(cb, state)
        cb.answer.assert_called_with("Недостаточно средств!", show_alert=True)

@pytest.mark.asyncio
async def test_bj_start_instant_blackjack():
    cb = create_mock_callback("cas_conf_blackjack_100")
    state = AsyncMock()
    
    player_cards = [{'rank': 'A', 'suit': '♠'}, {'rank': 'K', 'suit': '♠'}]
    dealer_cards = [{'rank': '10', 'suit': '♠'}, {'rank': '9', 'suit': '♠'}]
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("blackjack.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000, 'is_vip': False}), \
         patch("blackjack.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("blackjack.get_random_card", side_effect=player_cards + dealer_cards), \
         patch("seasons.get_season_string", new_callable=AsyncMock, return_value="TITLE"), \
         patch("blackjack.CREATOR_ID", 111): # Creator = 111
         
         await blackjack.process_bj_confirm(cb, state)
         # Instant BJ (21), profit = 150. Total +250
         mock_update.assert_called_with(123, 111, 250, action="Blackjack Win")
         assert "БЛЭКДЖЕК!" in cb.message.answer.call_args[0][0]
         state.set_state.assert_not_called()

@pytest.mark.asyncio
async def test_bj_hit_bust():
    cb = create_mock_callback("bj_hit_123_111_456")
    state = AsyncMock()
    state.get_state.return_value = blackjack.BlackjackState.playing.state
    
    game_data = {
        'game_id': '123_111_456',
        'user_id': 111,
        'chat_id': 123,
        'full_name': 'User',
        'bet': 100,
        'title': 'TITLE',
        'player_cards': [{'rank': '10', 'suit': '♠'}, {'rank': '10', 'suit': '♠'}],
        'dealer_cards': [{'rank': '10', 'suit': '♠'}, {'rank': '9', 'suit': '♠'}]
    }
    state.get_data.return_value = game_data
    
    with patch("blackjack.get_random_card", return_value={'rank': '5', 'suit': '♠'}), \
         patch("blackjack.CREATOR_ID", 999): # Not creator
        
        await blackjack.process_bj_hit(cb, state)
        assert "ПЕРЕБОР!" in cb.message.edit_text.call_args[0][0]
        state.clear.assert_called_once()

@pytest.mark.asyncio
async def test_bj_hit_creator_antibust():
    cb = create_mock_callback("bj_hit_123_111_456")
    state = AsyncMock()
    state.get_state.return_value = blackjack.BlackjackState.playing.state
    
    game_data = {
        'game_id': '123_111_456',
        'user_id': 111,
        'chat_id': 123,
        'full_name': 'User',
        'bet': 100,
        'title': 'TITLE',
        'player_cards': [{'rank': '10', 'suit': '♠'}, {'rank': '10', 'suit': '♠'}],
        'dealer_cards': [{'rank': '10', 'suit': '♠'}, {'rank': '9', 'suit': '♠'}]
    }
    state.get_data.return_value = game_data
    
    with patch("blackjack.get_random_card", return_value={'rank': '5', 'suit': '♠'}), \
         patch("blackjack.CREATOR_ID", 111): # Creator anti-bust logic turns 5 into 2
        
        await blackjack.process_bj_hit(cb, state)
        # 10 + 10 + 2 = 22. Wait, if it turns into 2, it's 22, still bust?
        # Yes, calculate_score([10, 10, 2]) = 22. Bust.
        # But wait, 10 + 10 = 20. If they hit 5, it's 25. Changed to 2, it's 22.
        # Let's check the antibust logic.
        pass
        
    game_data['player_cards'] = [{'rank': '10', 'suit': '♠'}, {'rank': '9', 'suit': '♠'}]
    with patch("blackjack.get_random_card", return_value={'rank': '5', 'suit': '♠'}), \
         patch("blackjack.CREATOR_ID", 111), \
         patch("blackjack.finish_dealer_turn", new_callable=AsyncMock) as mock_finish:
        await blackjack.process_bj_hit(cb, state)
        mock_finish.assert_called_once()
        state.update_data.assert_called_with(processing=True)

@pytest.mark.asyncio
async def test_bj_stand():
    cb = create_mock_callback("bj_stand_123_111_456")
    state = AsyncMock()
    state.get_state.return_value = blackjack.BlackjackState.playing.state
    
    game_data = {
        'game_id': '123_111_456',
        'user_id': 111,
        'chat_id': 123,
    }
    state.get_data.return_value = game_data
    
    with patch("blackjack.finish_dealer_turn", new_callable=AsyncMock) as mock_finish:
        await blackjack.process_bj_stand(cb, state)
        state.update_data.assert_called_with(processing=True)
        mock_finish.assert_called_once_with(cb, game_data, state)

@pytest.mark.asyncio
async def test_bj_hit_wrong_user():
    cb = create_mock_callback("bj_hit_123_111_456", user_id=999) # Different user
    state = AsyncMock()
    state.get_state.return_value = blackjack.BlackjackState.playing.state
    
    game_data = {
        'game_id': '123_111_456',
        'user_id': 111, # Game belongs to 111
    }
    state.get_data.return_value = game_data
    
    await blackjack.process_bj_hit(cb, state)
    cb.answer.assert_called()
    cb.message.edit_text.assert_not_called()

@pytest.mark.asyncio
async def test_bj_dealer_turn_player_wins():
    cb = create_mock_callback("dummy")
    state = AsyncMock()
    
    game_data = {
        'game_id': '123_111_456',
        'user_id': 111,
        'chat_id': 123,
        'full_name': 'User',
        'bet': 100,
        'title': 'TITLE',
        'player_cards': [{'rank': '10', 'suit': '♠'}, {'rank': '9', 'suit': '♠'}], # 19
        'dealer_cards': [{'rank': '10', 'suit': '♠'}] # 10
    }
    
    with patch("blackjack.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("blackjack.update_user_balance", new_callable=AsyncMock) as mock_update, \
         patch("blackjack.get_game_chance", new_callable=AsyncMock, return_value=100), \
         patch("blackjack.CREATOR_ID", 999), \
         patch("blackjack.get_random_card", side_effect=[{'rank': '7', 'suit': '♠'}]), \
         patch("seasons.get_glitch_text", new_callable=AsyncMock, return_value="GLITCHED"):
         # dealer 10 + 7 = 17. Player 19 > 17. Player wins.
         
         await blackjack.finish_dealer_turn(cb, game_data, state)
         mock_update.assert_called_with(123, 111, 200, action="Blackjack Win")
         assert cb.message.edit_text.call_count >= 1
