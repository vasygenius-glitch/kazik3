import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import sys

# Mock system dependencies before importing
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = MagicMock()

import rp_clans
from rp_clans import callback_tactical_duel

class TestRpClans(unittest.IsolatedAsyncioTestCase):
    @patch('economy_utils.get_global_tax', new_callable=AsyncMock)
    @patch('rp_clans.get_user_data')
    @patch('rp_clans.update_user_balance')
    @patch('rp_clans.is_frontman')
    @patch('diseases.get_active_diseases', new_callable=AsyncMock)
    @patch('rp_clans.render_tactical_duel')
    @patch('rp_clans.secrets.SystemRandom')
    async def test_duel_shoot_creator_guaranteed_hit(self, mock_random, mock_render, mock_diseases, mock_fm, mock_update, mock_get_user_data, mock_get_tax):
        # Настраиваем дуэль, где атакующий - Создатель, а противник - обычный игрок
        mock_get_user_data.side_effect = lambda chat, uid: {'balance': 1000, 'full_name': f'User{uid}'}
        mock_fm.side_effect = lambda chat, uid: uid == 999
        mock_diseases.return_value = []
        mock_get_tax.return_value = 5

        # Симулируем: случайный ролл 99 (по умолчанию это был бы промах, но для Создателя это 0 (попадание))
        mock_random_instance = MagicMock()
        mock_random_instance.randint.return_value = 99
        mock_random.return_value = mock_random_instance

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        callback.data = "tduel_1_shoot"
        callback.message.chat.id = 1
        callback.from_user.id = 999  # CREATOR_ID
        callback.message.message_id = 100
        callback.bot = MagicMock()

        # Мокаем глобальный словарь дуэлей
        rp_clans.active_duels = {
            "1": {
                'id': 1,
                'chat_id': 1,
                'p1': {'id': 999, 'hp': 100, 'acc': 50, 'cover': False, 'name': 'Boss'},
                'p2': {'id': 2, 'hp': 100, 'acc': 50, 'cover': False, 'name': 'Target'},
                'turn': 999,
                'bet': 100,
                'msg_id': 100,
                'state': 'active'
            }
        }

        with patch('config.CREATOR_ID', 999):
            await callback_tactical_duel(callback)

        # Win pool = 200, tax = 10, winner gets 190
        mock_update.assert_called_once_with(1, 999, 190)

    @patch('economy_utils.get_global_tax', new_callable=AsyncMock)
    @patch('rp_clans.get_user_data')
    @patch('rp_clans.update_user_balance')
    @patch('rp_clans.is_frontman')
    @patch('diseases.get_active_diseases', new_callable=AsyncMock)
    @patch('rp_clans.render_tactical_duel')
    @patch('rp_clans.secrets.SystemRandom')
    async def test_duel_shoot_creator_guaranteed_miss(self, mock_random, mock_render, mock_diseases, mock_fm, mock_update, mock_get_user_data, mock_get_tax):
        # Настраиваем дуэль, где атакующий - обычный игрок, а противник - Создатель
        mock_get_user_data.side_effect = lambda chat, uid: {'balance': 1000, 'full_name': f'User{uid}'}
        mock_fm.side_effect = lambda chat, uid: uid == 999
        mock_diseases.return_value = []
        mock_get_tax.return_value = 5

        # Симулируем: случайный ролл 1 (по умолчанию это было бы 100% попадание)
        mock_random_instance = MagicMock()
        mock_random_instance.randint.return_value = 1
        mock_random.return_value = mock_random_instance

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        callback.data = "tduel_1_shoot"
        callback.message.chat.id = 1
        callback.from_user.id = 2  # Обычный игрок
        callback.message.message_id = 100
        callback.bot = MagicMock()

        # Мокаем глобальный словарь дуэлей
        rp_clans.active_duels = {
            "1": {
                'id': 1,
                'chat_id': 1,
                'p1': {'id': 2, 'hp': 100, 'acc': 90, 'cover': False, 'name': 'Shooter'},
                'p2': {'id': 999, 'hp': 100, 'acc': 50, 'cover': False, 'name': 'Boss'},
                'turn': 2,
                'bet': 100,
                'msg_id': 100,
                'state': 'active'
            }
        }

        with patch('config.CREATOR_ID', 999):
            await callback_tactical_duel(callback)

        # Промах: баланс не обновляется
        mock_update.assert_not_called()

if __name__ == '__main__':
    unittest.main()
