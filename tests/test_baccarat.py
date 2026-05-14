import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from baccarat import get_baccarat_value, cmd_baccarat

class TestBaccarat(unittest.IsolatedAsyncioTestCase):
    def test_get_baccarat_value(self):
        self.assertEqual(get_baccarat_value(1), 1)
        self.assertEqual(get_baccarat_value(9), 9)
        self.assertEqual(get_baccarat_value(10), 0)
        self.assertEqual(get_baccarat_value(13), 0)

    @patch('baccarat.get_user_data')
    @patch('baccarat.update_user_balance')
    @patch('baccarat.schedule_delete')
    @patch('diseases.get_active_diseases', new_callable=AsyncMock)
    @patch('baccarat.secrets.SystemRandom')
    async def test_baccarat_win(self, mock_random, mock_diseases, mock_schedule_delete, mock_update_balance, mock_get_user_data):
        mock_get_user_data.return_value = {'balance': 1000}
        mock_diseases.return_value = []

        # Симулируем: сначала случайное значение для шанса (до 35 = победа)
        # Затем карты: p_cards = [9, 9], b_cards = [1, 1]
        # p_score = (9+9)%10 = 8, b_score = (1+1)%10 = 2.
        # Цикл while прервется на первой итерации, так как p_score > b_score.
        # p_cards = [9, 9] (сумма 18 -> 8), b_cards = [1, 1] (сумма 2)
        # Третья карта для b_cards: 1 (сумма 3)
        mock_random_instance = MagicMock()
        mock_random_instance.randint.side_effect = [30, 9, 9, 1, 1, 1]
        mock_random.return_value = mock_random_instance

        message = MagicMock()
        message.answer = AsyncMock()
        message.text = "/baccarat 100"
        message.chat.id = 1
        message.from_user.id = 2

        # Патчим CREATOR_ID, чтобы тест не падал из-за создателя
        with patch('config.CREATOR_ID', 999):
            await cmd_baccarat(message)

        mock_update_balance.assert_called_with(1, 2, 100)

    @patch('baccarat.get_user_data')
    @patch('baccarat.update_user_balance')
    @patch('baccarat.schedule_delete')
    @patch('diseases.get_active_diseases', new_callable=AsyncMock)
    @patch('baccarat.secrets.SystemRandom')
    async def test_baccarat_lose(self, mock_random, mock_diseases, mock_schedule_delete, mock_update_balance, mock_get_user_data):
        mock_get_user_data.return_value = {'balance': 1000}
        mock_diseases.return_value = []

        # Симулируем: шанс > 35 = поражение.
        # Карты: p_cards = [1, 1], b_cards = [9, 9]
        # p_score = (1+1)%10 = 2, b_score = (9+9)%10 = 8.
        # Доп карта для игрока: 1 (p_score = 3)
        # Доп карта для банкира: не тянется
        mock_random_instance = MagicMock()
        mock_random_instance.randint.side_effect = [80, 1, 1, 9, 9, 1]
        mock_random.return_value = mock_random_instance

        message = MagicMock()
        message.answer = AsyncMock()
        message.text = "/baccarat 100"
        message.chat.id = 1
        message.from_user.id = 2

        with patch('config.CREATOR_ID', 999):
            await cmd_baccarat(message)

        mock_update_balance.assert_called_with(1, 2, -100)

    @patch('baccarat.get_user_data')
    @patch('baccarat.update_user_balance')
    @patch('baccarat.schedule_delete')
    @patch('diseases.get_active_diseases', new_callable=AsyncMock)
    @patch('baccarat.secrets.SystemRandom')
    async def test_baccarat_creator_win(self, mock_random, mock_diseases, mock_schedule_delete, mock_update_balance, mock_get_user_data):
        mock_get_user_data.return_value = {'balance': 1000}
        mock_diseases.return_value = []

        # Симулируем: шанс любой, карты любые, создатель выигрывает 9 к 1
        mock_random_instance = MagicMock()
        mock_random_instance.randint.return_value = 1
        mock_random.return_value = mock_random_instance

        message = MagicMock()
        message.answer = AsyncMock()
        message.text = "/baccarat 100"
        message.chat.id = 1
        message.from_user.id = 999

        with patch('config.CREATOR_ID', 999):
            await cmd_baccarat(message)

        mock_update_balance.assert_called_with(1, 999, 100)
