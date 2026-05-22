import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from user_manager import remove_item_from_inventory

class TestUserManager(unittest.IsolatedAsyncioTestCase):
    @patch('user_manager.get_user_lock')
    @patch('user_manager.get_user_data')
    @patch('user_manager.set_in_cache')
    @patch('user_manager.mark_dirty')
    async def test_remove_item_from_inventory_success(self, mock_mark_dirty, mock_set_in_cache, mock_get_user_data, mock_get_lock):
        # Мокаем async context manager для лока
        mock_lock = AsyncMock()
        mock_lock.__aenter__.return_value = None
        mock_lock.__aexit__.return_value = None
        mock_get_lock.return_value = mock_lock

        # Инвентарь пользователя до удаления
        mock_get_user_data.return_value = {
            'inventory': {'shawarma': 1, 'condom': 2},
            'biz_levels': {'shawarma': 3}
        }

        result = await remove_item_from_inventory(1, 2, 'shawarma')

        # Проверяем, что предмет был успешно удален
        self.assertTrue(result)

        # Проверяем, что данные обновились (shawarma удалилась из inventory, а также удалился biz_levels)
        updated_data = mock_set_in_cache.call_args[0][2]
        self.assertNotIn('shawarma', updated_data['inventory'])
        self.assertIn('condom', updated_data['inventory'])
        self.assertEqual(updated_data['inventory']['condom'], 2)
        self.assertNotIn('shawarma', updated_data['biz_levels'])

        mock_mark_dirty.assert_called_once_with(1, 2)

    @patch('user_manager.get_user_lock')
    @patch('user_manager.get_user_data')
    @patch('user_manager.set_in_cache')
    @patch('user_manager.mark_dirty')
    async def test_remove_item_from_inventory_not_found(self, mock_mark_dirty, mock_set_in_cache, mock_get_user_data, mock_get_lock):
        mock_lock = AsyncMock()
        mock_lock.__aenter__.return_value = None
        mock_lock.__aexit__.return_value = None
        mock_get_lock.return_value = mock_lock

        # Инвентарь пользователя без удаляемого предмета
        mock_get_user_data.return_value = {
            'inventory': {'condom': 2},
            'biz_levels': {}
        }

        result = await remove_item_from_inventory(1, 2, 'shawarma')

        # Проверяем, что метод вернул False, и кэш не обновлялся
        self.assertFalse(result)
        mock_set_in_cache.assert_not_called()
        mock_mark_dirty.assert_not_called()

    @patch('user_manager.get_user_lock')
    @patch('user_manager.get_user_data')
    @patch('user_manager.set_in_cache')
    @patch('user_manager.mark_dirty')
    async def test_remove_item_from_inventory_decrease_count(self, mock_mark_dirty, mock_set_in_cache, mock_get_user_data, mock_get_lock):
        mock_lock = AsyncMock()
        mock_lock.__aenter__.return_value = None
        mock_lock.__aexit__.return_value = None
        mock_get_lock.return_value = mock_lock

        # У пользователя несколько предметов одного типа
        mock_get_user_data.return_value = {
            'inventory': {'condom': 2},
            'biz_levels': {}
        }

        result = await remove_item_from_inventory(1, 2, 'condom')

        # Проверяем, что количество уменьшилось
        self.assertTrue(result)
        updated_data = mock_set_in_cache.call_args[0][2]
        self.assertEqual(updated_data['inventory']['condom'], 1)

    async def test_reentrant_lock_nesting(self):
        from user_manager import ReentrantLock
        import asyncio

        lock = ReentrantLock()
        
        # Test basic acquisition and release
        self.assertFalse(lock.locked())
        await lock.acquire()
        self.assertTrue(lock.locked())
        lock.release()
        self.assertFalse(lock.locked())

        # Test nesting
        async with lock:
            self.assertTrue(lock.locked())
            async with lock:
                self.assertTrue(lock.locked())
                self.assertEqual(lock._count, 2)
            self.assertTrue(lock.locked())
            self.assertEqual(lock._count, 1)
        self.assertFalse(lock.locked())
        self.assertEqual(lock._count, 0)
        self.assertIsNone(lock._owner)

        # Test release unowned error
        with self.assertRaises(RuntimeError):
            lock.release()

    @patch('user_manager.get_user_data')
    @patch('user_manager.set_in_cache')
    @patch('user_manager.mark_dirty')
    @patch('user_manager._fetch_active_lobby_type')
    @patch('economy_utils.get_global_tax', new_callable=AsyncMock)
    @patch('diseases.get_active_diseases')
    async def test_creator_bonus_cooldown_bypass(self, mock_diseases, mock_tax, mock_lobby_type, mock_mark_dirty, mock_set_in_cache, mock_get_user_data):
        from user_manager import check_and_give_bonus
        from config import CREATOR_ID
        import time

        mock_diseases.return_value = []
        mock_tax.return_value = 10
        mock_lobby_type.return_value = 'none'

        # Set user data with last_bonus_time in the past but within cooldown
        current_time = time.time()
        mock_get_user_data.return_value = {
            'balance': 1000,
            'last_bonus_time': current_time - 100, # 100 seconds ago, within cooldown
            'last_daily_time': current_time - 100,
            'is_banned': False,
        }

        # First, normal user gets rejected (False) due to cooldown
        success, info = await check_and_give_bonus(chat_id=111, user_id=999999, full_name="User")
        self.assertFalse(success)
        self.assertEqual(info, {})

        # Now, creator ID bypasses the cooldown check
        success, info = await check_and_give_bonus(chat_id=111, user_id=CREATOR_ID, full_name="Creator")
        self.assertTrue(success)
        self.assertGreater(info.get('total', 0), 0)

    async def test_cache_ttl_behavior(self):
        import user_manager
        import time

        chat_id = 99999
        user_id = 88888
        key = (chat_id, user_id)

        # Ensure clean state
        user_manager._user_cache.pop(key, None)
        user_manager._dirty_cache.discard(key)

        # 1. Test non-dirty entry TTL expiration
        user_manager._user_cache[key] = {
            "data": {"balance": 100, "full_name": "Test"},
            "timestamp": time.time() - (user_manager.CACHE_TTL + 10)
        }
        res = user_manager.get_from_cache(chat_id, user_id)
        self.assertIsNone(res)
        self.assertNotIn(key, user_manager._user_cache)

        # 2. Test dirty entry TTL expiration (should NOT be dropped and should return data)
        user_manager._user_cache[key] = {
            "data": {"balance": 200, "full_name": "Test Dirty"},
            "timestamp": time.time() - (user_manager.CACHE_TTL + 10)
        }
        user_manager._dirty_cache.add(key)
        
        res = user_manager.get_from_cache(chat_id, user_id)
        self.assertIsNotNone(res)
        self.assertEqual(res["balance"], 200)
        self.assertIn(key, user_manager._user_cache)

        # Clean up
        user_manager._user_cache.pop(key, None)
        user_manager._dirty_cache.discard(key)
