import pytest
import sys
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import roulette

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
async def test_roulette_banned():
    msg = create_mock_message("/roulette 100 5")
    with patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'is_banned': True}):
        await roulette.cmd_roulette(msg)
        assert "🚫" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_gonorrhea():
    msg = create_mock_message("/roulette 100 5")
    with patch("roulette.get_user_data", new_callable=AsyncMock, return_value={}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=['gonorrhea']):
        await roulette.cmd_roulette(msg)
        assert "🦠" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_invalid_args_count():
    msg = create_mock_message("/roulette 100")
    with patch("roulette.get_user_data", new_callable=AsyncMock, return_value={}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        await roulette.cmd_roulette(msg)
        assert "Использование:" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_invalid_bet_nan():
    msg = create_mock_message("/roulette abc 5")
    with patch("roulette.get_user_data", new_callable=AsyncMock, return_value={}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        await roulette.cmd_roulette(msg)
        assert "Нужны числа" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_invalid_bet_small():
    msg = create_mock_message("/roulette 50 5")
    with patch("roulette.get_user_data", new_callable=AsyncMock, return_value={}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        await roulette.cmd_roulette(msg)
        assert "Ошибка параметров" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_invalid_guess():
    msg = create_mock_message("/roulette 100 37")
    with patch("roulette.get_user_data", new_callable=AsyncMock, return_value={}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        await roulette.cmd_roulette(msg)
        assert "Ошибка параметров" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_limit():
    msg = create_mock_message("/roulette 100 5")
    with patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'balance': -4950}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        await roulette.cmd_roulette(msg)
        assert "Лимит!" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_success_ask_confirm():
    msg = create_mock_message("/roulette 100 5")
    with patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]), \
         patch("casino_utils.ask_casino_confirmation", new_callable=AsyncMock) as mock_ask:
        await roulette.cmd_roulette(msg)
        mock_ask.assert_called_once_with(msg, "roulette", 100, guess=5)

@pytest.mark.asyncio
async def test_roulette_process_insufficient_funds():
    cb = create_mock_callback("cas_conf_roulette_100_5")
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'balance': 0}), \
         patch("roulette.update_user_balance", new_callable=AsyncMock, return_value=None):
        await roulette.process_roulette_confirm(cb)
        cb.answer.assert_called_with("Недостаточно средств!", show_alert=True)

@pytest.mark.asyncio
async def test_roulette_process_win_exact():
    cb = create_mock_callback("cas_conf_roulette_100_5")
    mock_msg = AsyncMock()
    cb.message.answer.return_value = mock_msg
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000, 'is_vip': False}), \
         patch("roulette.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("seasons.get_season_string", new_callable=AsyncMock, return_value="TITLE"), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("roulette.get_game_chance", new_callable=AsyncMock, return_value=-1), \
         patch("roulette.CREATOR_ID", 999), \
         patch("roulette.secure_random.randint", side_effect=[1, 2, 3, 4, 5]):
         
         await roulette.process_roulette_confirm(cb)
         mock_update.assert_called_with(123, 111, 300, action="Roulette Win")
         final_text = mock_msg.edit_text.call_args[0][0]
         assert "ТОЧНО!" in final_text

@pytest.mark.asyncio
async def test_roulette_process_win_close_2():
    cb = create_mock_callback("cas_conf_roulette_100_5")
    mock_msg = AsyncMock()
    cb.message.answer.return_value = mock_msg
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("roulette.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("seasons.get_season_string", new_callable=AsyncMock, return_value="TITLE"), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("roulette.get_game_chance", new_callable=AsyncMock, return_value=-1), \
         patch("roulette.CREATOR_ID", 999), \
         patch("roulette.secure_random.randint", side_effect=[1, 2, 3, 4, 7]):
         
         await roulette.process_roulette_confirm(cb)
         mock_update.assert_called_with(123, 111, 150, action="Roulette Win")
         assert "РЯДОМ!" in mock_msg.edit_text.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_process_win_close_4():
    cb = create_mock_callback("cas_conf_roulette_100_5")
    mock_msg = AsyncMock()
    cb.message.answer.return_value = mock_msg
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("roulette.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("seasons.get_season_string", new_callable=AsyncMock, return_value="TITLE"), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("roulette.get_game_chance", new_callable=AsyncMock, return_value=-1), \
         patch("roulette.CREATOR_ID", 999), \
         patch("roulette.secure_random.randint", side_effect=[1, 2, 3, 4, 9]):
         
         await roulette.process_roulette_confirm(cb)
         mock_update.assert_called_with(123, 111, 110, action="Roulette Win")
         assert "БЛИЗКО!" in mock_msg.edit_text.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_process_loss():
    cb = create_mock_callback("cas_conf_roulette_100_5")
    mock_msg = AsyncMock()
    cb.message.answer.return_value = mock_msg
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("roulette.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("seasons.get_season_string", new_callable=AsyncMock, return_value="TITLE"), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("roulette.get_game_chance", new_callable=AsyncMock, return_value=-1), \
         patch("roulette.CREATOR_ID", 999), \
         patch("roulette.secure_random.randint", side_effect=[1, 2, 3, 4, 20]):
         
         await roulette.process_roulette_confirm(cb)
         assert mock_update.call_count == 1
         assert "МИМО" in mock_msg.edit_text.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_creator_win():
    cb = create_mock_callback("cas_conf_roulette_100_5", user_id=999)
    mock_msg = AsyncMock()
    cb.message.answer.return_value = mock_msg
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("roulette.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("seasons.get_season_string", new_callable=AsyncMock, return_value="TITLE"), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("roulette.get_game_chance", new_callable=AsyncMock, return_value=-1), \
         patch("roulette.CREATOR_ID", 999):
         
         await roulette.process_roulette_confirm(cb)
         mock_update.assert_called_with(123, 999, 300, action="Roulette Win")
         assert "ТОЧНО!" in mock_msg.edit_text.call_args[0][0]

@pytest.mark.asyncio
async def test_roulette_vip_bonus():
    cb = create_mock_callback("cas_conf_roulette_100_5")
    mock_msg = AsyncMock()
    cb.message.answer.return_value = mock_msg
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("roulette.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000, 'is_vip': True}), \
         patch("roulette.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("seasons.get_season_string", new_callable=AsyncMock, return_value="TITLE"), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("roulette.get_game_chance", new_callable=AsyncMock, return_value=-1), \
         patch("roulette.CREATOR_ID", 999), \
         patch("roulette.secure_random.randint", side_effect=[1, 2, 3, 4, 5]):
         
         await roulette.process_roulette_confirm(cb)
         mock_update.assert_called_with(123, 111, 320, action="Roulette Win")
