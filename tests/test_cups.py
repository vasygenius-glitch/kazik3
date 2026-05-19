import unittest
import sys
import asyncio
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

import cups
from cups import CupsGame, Difficulty

class TestCupsGame(unittest.IsolatedAsyncioTestCase):
    async def test_cmd_cups(self):
        msg = AsyncMock()
        msg.text = "/cups 100 easy"
        msg.chat.id = 123
        msg.from_user.id = 456
        msg.from_user.full_name = "Test User"

        with patch("cups.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("cups.check_and_give_bonus", new_callable=AsyncMock) as mock_bonus, \
             patch("cups.update_user_balance", new_callable=AsyncMock) as mock_update, \
             patch("casino_utils.ask_casino_confirmation", new_callable=AsyncMock) as mock_conf:

            mock_get_data.return_value = {'balance': 1000}
            mock_bonus.return_value = (False, {})

            sys.modules['diseases'].get_active_diseases = AsyncMock(return_value=[])

            await cups.cmd_cups(msg)
            mock_update.assert_not_called()
            mock_conf.assert_called_once_with(msg, "cups_easy", 100)

    async def test_process_cups_win_rate(self):
        game_id = "test_game_1"
        chat_id = 123
        user_id = 456
        bet = 100
        
        diff = Difficulty(
            code="easy",
            title="Easy",
            emoji="🟢",
            cups=3,
            balls=1,
            multiplier=2.0,
            base_win_chance=35,
            description="3 cups, 1 ball"
        )
        
        game = CupsGame(
            game_id=game_id,
            chat_id=chat_id,
            user_id=user_id,
            full_name="Test User",
            bet=bet,
            difficulty=diff,
            winning_cups=[1]
        )
        
        cups.active_cups_games[game_id] = game

        callback = AsyncMock()
        callback.data = f"cups|{game_id}|1"
        callback.from_user.id = user_id

        with patch("cups.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("cups.update_user_balance", new_callable=AsyncMock) as mock_update, \
             patch("cups._animate_lift", new_callable=AsyncMock), \
             patch("cups._animate_reveal_all", new_callable=AsyncMock), \
             patch("cups.invalidate_user_cache_safe", new_callable=AsyncMock), \
             patch("cups.secure_random.randint", return_value=35): # 35 <= 35 (win)

            mock_get_data.return_value = {'balance': 1000, 'is_vip': False, 'is_banker': False}

            await cups.process_cups_choice(callback)
            mock_update.assert_called_once_with(chat_id, user_id, 200, action='Cups Win (easy)')

    async def test_process_cups_loss_rate(self):
        game_id = "test_game_2"
        chat_id = 123
        user_id = 456
        bet = 100
        
        diff = Difficulty(
            code="easy",
            title="Easy",
            emoji="🟢",
            cups=3,
            balls=1,
            multiplier=2.0,
            base_win_chance=35,
            description="3 cups, 1 ball"
        )
        
        game = CupsGame(
            game_id=game_id,
            chat_id=chat_id,
            user_id=user_id,
            full_name="Test User",
            bet=bet,
            difficulty=diff,
            winning_cups=[1]
        )
        
        cups.active_cups_games[game_id] = game

        callback = AsyncMock()
        callback.data = f"cups|{game_id}|1"
        callback.from_user.id = user_id

        with patch("cups.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("cups.update_user_balance", new_callable=AsyncMock) as mock_update, \
             patch("cups._animate_lift", new_callable=AsyncMock), \
             patch("cups._animate_reveal_all", new_callable=AsyncMock), \
             patch("cups.invalidate_user_cache_safe", new_callable=AsyncMock), \
             patch("cups.secure_random.randint", return_value=36): # 36 > 35 (loss)

            mock_get_data.return_value = {'balance': 1000, 'is_vip': False, 'is_banker': False}

            await cups.process_cups_choice(callback)
            mock_update.assert_not_called()

if __name__ == '__main__':
    unittest.main()
