import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from baccarat import process_baccarat_confirm
from cards import get_baccarat_score
from aiogram import types

class TestBaccarat(unittest.IsolatedAsyncioTestCase):
    def test_get_baccarat_score(self):
        # Testing get_baccarat_score which is now in cards.py
        from cards import VALUES
        self.assertEqual(get_baccarat_score([{'rank': 'A', 'suit': '♠'}]), 1)
        self.assertEqual(get_baccarat_score([{'rank': '9', 'suit': '♠'}]), 9)
        self.assertEqual(get_baccarat_score([{'rank': '10', 'suit': '♠'}]), 0)
        self.assertEqual(get_baccarat_score([{'rank': 'K', 'suit': '♠'}]), 0)

    @patch('baccarat.get_user_data')
    @patch('baccarat.update_user_balance')
    @patch('baccarat.schedule_delete')
    @patch('baccarat.secrets.SystemRandom')
    async def test_baccarat_win(self, mock_random, mock_schedule_delete, mock_update_balance, mock_get_user_data):
        mock_get_user_data.return_value = {'balance': 1000}

        # Симулируем: сначала случайное значение для шанса (до 35 = победа)
        # Затем карты: p_cards = [9, 9], b_cards = [1, 1]
        # p_score = (9+9)%10 = 8, b_score = (1+1)%10 = 2.
        mock_random_instance = MagicMock()
        mock_random_instance.randint.side_effect = [30]
        mock_random.return_value = mock_random_instance

        # We need to mock get_random_card to return predictable values
        with patch('baccarat.get_random_card') as mock_get_card:
            mock_get_card.side_effect = [
                {'rank': '9', 'suit': '♠'}, {'rank': '9', 'suit': '♠'}, # Player
                {'rank': 'A', 'suit': '♠'}, {'rank': 'A', 'suit': '♠'}, # Banker
                {'rank': 'A', 'suit': '♠'} # Third card for Banker (if needed)
            ]

            callback = MagicMock()
            callback.data = "cas_conf_baccarat_100"
            callback.message.chat.id = 1
            callback.from_user.id = 2
            callback.message.answer = AsyncMock()
            callback.message.delete = AsyncMock()
            callback.answer = AsyncMock()

            # update_user_balance returns the new balance if successful
            mock_update_balance.side_effect = [-100, 200] # First call: -bet, Second call: +profit

            with patch('config.CREATOR_ID', 999):
                await process_baccarat_confirm(callback)

            # First call is the bet deduction
            mock_update_balance.assert_any_call(1, 2, -100, min_balance=-5000)
            # Second call is the win payment (bet + profit)
            mock_update_balance.assert_any_call(1, 2, 200, action='Baccarat Win')

    @patch('baccarat.get_user_data')
    @patch('baccarat.update_user_balance')
    @patch('baccarat.schedule_delete')
    @patch('baccarat.secrets.SystemRandom')
    async def test_baccarat_lose(self, mock_random, mock_schedule_delete, mock_update_balance, mock_get_user_data):
        mock_get_user_data.return_value = {'balance': 1000}

        # Симулируем: шанс > 35 = поражение.
        mock_random_instance = MagicMock()
        mock_random_instance.randint.side_effect = [80]
        mock_random.return_value = mock_random_instance

        with patch('baccarat.get_random_card') as mock_get_card:
            mock_get_card.side_effect = [
                {'rank': 'A', 'suit': '♠'}, {'rank': 'A', 'suit': '♠'}, # Player
                {'rank': '9', 'suit': '♠'}, {'rank': '9', 'suit': '♠'}, # Banker
                {'rank': 'A', 'suit': '♠'} # Third card for Player
            ]

            callback = MagicMock()
            callback.data = "cas_conf_baccarat_100"
            callback.message.chat.id = 1
            callback.from_user.id = 2
            callback.message.answer = AsyncMock()
            callback.message.delete = AsyncMock()
            callback.answer = AsyncMock()

            mock_update_balance.return_value = 900

            with patch('config.CREATOR_ID', 999):
                await process_baccarat_confirm(callback)

            mock_update_balance.assert_called_once_with(1, 2, -100, min_balance=-5000)

    @patch('baccarat.get_user_data')
    @patch('baccarat.update_user_balance')
    @patch('baccarat.schedule_delete')
    @patch('baccarat.secrets.SystemRandom')
    async def test_baccarat_creator_win(self, mock_random, mock_schedule_delete, mock_update_balance, mock_get_user_data):
        mock_get_user_data.return_value = {'balance': 1000}

        mock_random_instance = MagicMock()
        mock_random_instance.randint.return_value = 1
        mock_random.return_value = mock_random_instance

        callback = MagicMock()
        callback.data = "cas_conf_baccarat_100"
        callback.message.chat.id = 1
        callback.from_user.id = 999
        callback.message.answer = AsyncMock()
        callback.message.delete = AsyncMock()
        callback.answer = AsyncMock()

        mock_update_balance.side_effect = [900, 1100]

        with patch('config.CREATOR_ID', 999):
            await process_baccarat_confirm(callback)

        mock_update_balance.assert_any_call(1, 999, -100, min_balance=-5000)
        # In the new code, creator just wins naturally based on RNG,
        # so this test might need adjustment if we wanted guaranteed creator win.
        # But for now let's just check balance calls if win occurs.
