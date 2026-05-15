import unittest
import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock
import user_manager

class TestUsernameCache(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Clear caches before each test
        user_manager._user_cache.clear()
        if hasattr(user_manager, '_username_to_id_cache'):
            user_manager._username_to_id_cache.clear()
        else:
            user_manager._username_to_id_cache = {}

    def tearDown(self):
        user_manager._user_cache.clear()
        user_manager._username_to_id_cache.clear()

    def test_set_in_cache_adds_to_username_index(self):
        chat_id = 123
        user_id = 456
        data = {'username': 'testuser', 'balance': 1000}

        user_manager.set_in_cache(chat_id, user_id, data)

        self.assertIn((chat_id, user_id), user_manager._user_cache)
        self.assertEqual(user_manager._username_to_id_cache.get((chat_id, 'testuser')), user_id)

    def test_set_in_cache_updates_username_index_on_change(self):
        chat_id = 123
        user_id = 456

        # Initial set
        user_manager.set_in_cache(chat_id, user_id, {'username': 'oldname'})
        self.assertEqual(user_manager._username_to_id_cache.get((chat_id, 'oldname')), user_id)

        # Update with new username
        user_manager.set_in_cache(chat_id, user_id, {'username': 'newname'})
        self.assertNotIn((chat_id, 'oldname'), user_manager._username_to_id_cache)
        self.assertEqual(user_manager._username_to_id_cache.get((chat_id, 'newname')), user_id)

    def test_set_in_cache_removes_from_index_on_eviction(self):
        chat_id = 123

        # Mock MAX_CACHE_SIZE to a small number
        with patch('user_manager.MAX_CACHE_SIZE', 2):
            user_manager.set_in_cache(chat_id, 1, {'username': 'user1'})
            user_manager.set_in_cache(chat_id, 2, {'username': 'user2'})

            self.assertEqual(user_manager._username_to_id_cache.get((chat_id, 'user1')), 1)
            self.assertEqual(user_manager._username_to_id_cache.get((chat_id, 'user2')), 2)

            # This should evict user1
            user_manager.set_in_cache(chat_id, 3, {'username': 'user3'})

            self.assertNotIn((chat_id, 1), user_manager._user_cache)
            self.assertNotIn((chat_id, 'user1'), user_manager._username_to_id_cache)
            self.assertEqual(user_manager._username_to_id_cache.get((chat_id, 'user2')), 2)
            self.assertEqual(user_manager._username_to_id_cache.get((chat_id, 'user3')), 3)

    def test_invalidate_user_cache_removes_from_index(self):
        chat_id = 123
        user_id = 456
        user_manager.set_in_cache(chat_id, user_id, {'username': 'testuser'})

        user_manager.invalidate_user_cache(chat_id, user_id)

        self.assertNotIn((chat_id, user_id), user_manager._user_cache)
        self.assertNotIn((chat_id, 'testuser'), user_manager._username_to_id_cache)

    @patch('user_manager.get_db')
    async def test_get_user_by_username_or_id_uses_index(self, mock_get_db):
        chat_id = 123
        user_id = 456
        data = {'username': 'testuser', 'balance': 1000}

        user_manager.set_in_cache(chat_id, user_id, data)

        # Now call get_user_by_username_or_id
        # It should return from cache index without calling DB if it's O(1)

        uid, udata = await user_manager.get_user_by_username_or_id(chat_id, "@testuser")

        self.assertEqual(uid, user_id)
        self.assertEqual(udata['username'], 'testuser')
        mock_get_db.assert_not_called() # Should not need DB if found in cache

    async def test_username_is_case_insensitive_in_lookups(self):
        chat_id = 123
        user_id = 456
        user_manager.set_in_cache(chat_id, user_id, {'username': 'TestUser'})

        # The key in index should be lowercase
        self.assertEqual(user_manager._username_to_id_cache.get((chat_id, 'testuser')), user_id)

        # Lookups should be case-insensitive
        uid1, _ = await user_manager.get_user_by_username_or_id(chat_id, "@TestUser")
        uid2, _ = await user_manager.get_user_by_username_or_id(chat_id, "@testuser")

        self.assertEqual(uid1, user_id)
        self.assertEqual(uid2, user_id)

if __name__ == '__main__':
    unittest.main()
