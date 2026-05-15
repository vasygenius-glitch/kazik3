import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import time
import chances

class TestChances(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Reset cache before each test
        chances._chances_cache = {}
        chances._chances_cache_time = 0

    @patch('chances.get_db')
    async def test_get_game_chance_cache_miss_exists(self, mock_get_db):
        mock_db = MagicMock()
        mock_ref = MagicMock()
        mock_doc = AsyncMock()

        mock_doc.exists = True
        # For an AsyncMock, if you just assign a dictionary to a return_value
        # that should be synchronous, use MagicMock for it
        mock_doc.to_dict = MagicMock(return_value={'slots': 35})
        mock_ref.get = AsyncMock(return_value=mock_doc)
        mock_db.collection.return_value.document.return_value = mock_ref
        mock_get_db.return_value = mock_db

        chance = await chances.get_game_chance('slots')
        self.assertEqual(chance, 35)
        self.assertEqual(chances._chances_cache, {'slots': 35})
        mock_get_db.assert_called_once()

    @patch('chances.get_db')
    async def test_get_game_chance_cache_miss_not_exists(self, mock_get_db):
        mock_db = MagicMock()
        mock_ref = MagicMock()
        mock_doc = AsyncMock()

        mock_doc.exists = False
        mock_ref.get = AsyncMock(return_value=mock_doc)
        mock_db.collection.return_value.document.return_value = mock_ref
        mock_get_db.return_value = mock_db

        chance = await chances.get_game_chance('slots')
        self.assertEqual(chance, -1)
        self.assertEqual(chances._chances_cache, {})
        mock_get_db.assert_called_once()

    @patch('chances.get_db')
    async def test_get_game_chance_cache_hit(self, mock_get_db):
        chances._chances_cache = {'blackjack': 40}
        chances._chances_cache_time = time.time() # Recent cache

        chance = await chances.get_game_chance('blackjack')
        self.assertEqual(chance, 40)
        mock_get_db.assert_not_called()

    @patch('chances.get_db')
    @patch('utils.fire_and_forget')
    async def test_set_game_chance(self, mock_fire_and_forget, mock_get_db):
        mock_db = MagicMock()
        mock_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_ref
        mock_get_db.return_value = mock_db

        # mock_ref.set return value can be anything, fire_and_forget takes it
        mock_ref.set.return_value = "coroutine_placeholder"

        await chances.set_game_chance('roulette', 50)

        self.assertEqual(chances._chances_cache['roulette'], 50)
        mock_get_db.assert_called_once()
        mock_ref.set.assert_called_once_with({'roulette': 50}, merge=True)
        mock_fire_and_forget.assert_called_once_with("coroutine_placeholder")
