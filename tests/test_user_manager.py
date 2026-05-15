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
