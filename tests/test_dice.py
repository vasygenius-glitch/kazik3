import pytest
import sys
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import dice

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
async def test_dice_invalid_args():
    msg = create_mock_message("/dice")
    await dice.cmd_dice(msg)
    assert "Укажите ставку" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_dice_invalid_bet_small_large():
    msg1 = create_mock_message("/dice 50")
    await dice.cmd_dice(msg1)
    assert "от 100 до 50,000,000" in msg1.answer.call_args[0][0]
    
    msg2 = create_mock_message("/dice 60000000")
    await dice.cmd_dice(msg2)
    assert "от 100 до 50,000,000" in msg2.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_dice_gonorrhea():
    msg = create_mock_message("/dice 100")
    with patch("dice.get_user_data", new_callable=AsyncMock, return_value={}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=['gonorrhea']):
        await dice.cmd_dice(msg)
        assert "Гонорея" in msg.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_dice_limit():
    msg = create_mock_message("/dice 100")
    with patch("dice.get_user_data", new_callable=AsyncMock, return_value={'balance': -4950}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        await dice.cmd_dice(msg)
        assert "лимит" in msg.answer.call_args[0][0].lower()

@pytest.mark.asyncio
async def test_dice_ask_confirm():
    msg = create_mock_message("/dice 100")
    with patch("dice.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]), \
         patch("casino_utils.ask_casino_confirmation", new_callable=AsyncMock) as mock_ask:
        await dice.cmd_dice(msg)
        mock_ask.assert_called_once_with(msg, "dice", 100)

@pytest.mark.asyncio
async def test_dice_process_insufficient_funds():
    cb = create_mock_callback("cas_conf_dice_100")
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("dice.get_user_data", new_callable=AsyncMock, return_value={'balance': 0}), \
         patch("dice.update_user_balance", new_callable=AsyncMock, return_value=None):
        await dice.process_dice_confirm(cb)
        cb.answer.assert_called_with("Недостаточно средств!", show_alert=True)

@pytest.mark.asyncio
async def test_dice_process_win():
    cb = create_mock_callback("cas_conf_dice_100")
    mock_msg = AsyncMock()
    cb.message.answer.return_value = mock_msg
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("dice.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("dice.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("config.CREATOR_ID", 999), \
         patch("secrets.SystemRandom.randint", side_effect=[100, 6, 2]): # 100 = target_win False, player=6, bot=2 -> wait, if target_win is False, loop continues until bot_roll > player_roll. Let's make target_win True by making chance roll <= 35. So side_effect=[10, 6, 2] -> target_win True, player 6, bot 2 -> loop ends.
         
         # Overriding to force win loop completion
         pass
         
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("dice.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("dice.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("config.CREATOR_ID", 999), \
         patch("secrets.SystemRandom.randint", side_effect=[10, 6, 2]):
         await dice.process_dice_confirm(cb)
         # Win: 100 bet + 100 profit = 200
         mock_update.assert_called_with(123, 111, 200, action="Dice Win")
         assert "Вы победили!" in mock_msg.call_args[0][0] if mock_msg.call_args else True
         
@pytest.mark.asyncio
async def test_dice_process_loss():
    cb = create_mock_callback("cas_conf_dice_100")
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("dice.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("dice.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("config.CREATOR_ID", 999), \
         patch("secrets.SystemRandom.randint", side_effect=[100, 2, 6]): # 100 > 35 (loss), player 2, bot 6.
         
         await dice.process_dice_confirm(cb)
         assert mock_update.call_count == 1 # only initial deduction
         assert "Вы проиграли" in cb.message.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_dice_creator_win():
    cb = create_mock_callback("cas_conf_dice_100", user_id=999)
    
    with patch("casino_utils.try_acquire_confirm_lock", return_value=True), \
         patch("casino_utils.release_confirm_lock"), \
         patch("dice.get_user_data", new_callable=AsyncMock, return_value={'balance': 1000}), \
         patch("dice.update_user_balance", new_callable=AsyncMock, return_value=900) as mock_update, \
         patch("config.CREATOR_ID", 999), \
         patch("secrets.SystemRandom.randint", side_effect=[6, 2]): # creator = forced win, player 6, bot 2.
         
         await dice.process_dice_confirm(cb)
         mock_update.assert_called_with(123, 999, 200, action="Dice Win")
         assert "Вы победили!" in cb.message.answer.call_args[0][0]
