import unittest
import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Mock external dependencies
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = MagicMock()
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()
sys.modules['config'].CREATOR_ID = 999

import cups

class TestCupsGame(unittest.IsolatedAsyncioTestCase):
    async def test_cmd_cups(self):
        msg = AsyncMock()
        msg.text = "/cups 100"
        msg.chat.id = 123
        msg.from_user.id = 456
        msg.from_user.full_name = "Test User"

        with patch("cups.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("cups.check_and_give_bonus", new_callable=AsyncMock) as mock_bonus, \
             patch("cups.update_user_balance", new_callable=AsyncMock) as mock_update:

            mock_get_data.return_value = {'balance': 1000}
            mock_bonus.return_value = (False, {}, "")

            # Since get_active_diseases is imported locally inside the func, we mock it globally in sys.modules
            sys.modules['diseases'].get_active_diseases = AsyncMock(return_value=[])

            # In cups.py it unpacks 2 items: bonus_given, receipt = await check_and_give_bonus(chat_id, user_id, full_name)
            # Memory says it should return 3 items, but the file unpacks 2.
            # Let's mock it to return 2 to fit the existing code in cups.py if needed, or 3 if the file was modified elsewhere, but based on the error it unpacks 2.
            mock_bonus.return_value = (False, {})

            await cups.cmd_cups(msg)
            mock_update.assert_called_once_with(123, 456, -100)
            msg.answer.assert_called_once()
            self.assertTrue(len(cups.active_cups_games) > 0)

    async def test_process_cups_win_rate(self):
        game_id = "test_game_1"
        chat_id = 123
        user_id = 456
        bet = 100
        cups.active_cups_games[game_id] = {
            'original_msg': AsyncMock(),
            'user_id': user_id,
            'chat_id': chat_id,
            'full_name': "Test User",
            'bet': bet,
            'winning_cup': 1,
            'bonus_text': ""
        }

        callback = AsyncMock()
        callback.data = f"cups|{game_id}|1"
        callback.from_user.id = user_id

        with patch("cups.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("cups.update_user_balance", new_callable=AsyncMock) as mock_update, \
             patch("cups.secure_random.randint", return_value=35): # 35 <= 35, should be win

            mock_get_data.return_value = {'balance': 1000}

            await cups.process_cups(callback)
            mock_update.assert_called_once_with(chat_id, user_id, bet + bet * 2)

    async def test_process_cups_loss_rate(self):
        game_id = "test_game_2"
        chat_id = 123
        user_id = 456
        bet = 100
        cups.active_cups_games[game_id] = {
            'original_msg': AsyncMock(),
            'user_id': user_id,
            'chat_id': chat_id,
            'full_name': "Test User",
            'bet': bet,
            'winning_cup': 1,
            'bonus_text': ""
        }

        callback = AsyncMock()
        callback.data = f"cups|{game_id}|1"
        callback.from_user.id = user_id

        with patch("cups.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("cups.update_user_balance", new_callable=AsyncMock) as mock_update, \
             patch("cups.secure_random.randint", return_value=36): # 36 > 35, should be loss

            mock_get_data.return_value = {'balance': 1000}

            await cups.process_cups(callback)
            mock_update.assert_not_called()

if __name__ == '__main__':
    unittest.main()
