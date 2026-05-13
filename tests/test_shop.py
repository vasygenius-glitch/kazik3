import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from shop import process_sell_confirm

class TestShop(unittest.IsolatedAsyncioTestCase):
    @patch('shop.get_user_data')
    @patch('shop.update_user_balance')
    @patch('shop.update_user_field')
    @patch('shop.show_sell_menu')
    @patch('shop.ITEMS')
    async def test_sell_vip(self, mock_items, mock_show_menu, mock_update_field, mock_update_balance, mock_get_user_data):
        # Настраиваем продажу VIP статуса
        mock_items.get.return_value = {'name': 'VIP Статус', 'price': 10000}
        mock_get_user_data.return_value = {'is_vip': True}

        callback = MagicMock()
        callback.data = "sell_confirm_вип"
        callback.message.chat.id = 1
        callback.from_user.id = 2
        callback.answer = AsyncMock()

        await process_sell_confirm(callback)

        # Проверяем, что поле is_vip обновлено на False, а баланс увеличен на 75% от цены
        mock_update_field.assert_called_once_with(1, 2, 'is_vip', False)
        mock_update_balance.assert_called_once_with(1, 2, 7500)
        callback.answer.assert_called_once()
        mock_show_menu.assert_called_once()

    @patch('shop.get_user_data')
    @patch('shop.update_user_balance')
    @patch('user_manager.remove_item_from_inventory', new_callable=AsyncMock)
    @patch('shop.show_sell_menu')
    @patch('shop.ITEMS')
    async def test_sell_regular_item(self, mock_items, mock_show_menu, mock_remove_item, mock_update_balance, mock_get_user_data):
        # Настраиваем продажу обычного предмета (например, бизнеса)
        mock_items.get.return_value = {'name': 'Шаурмечная', 'price': 10000}
        mock_remove_item.return_value = True  # Успешное удаление

        callback = MagicMock()
        callback.data = "sell_confirm_shawarma"
        callback.message.chat.id = 1
        callback.from_user.id = 2
        callback.answer = AsyncMock()

        await process_sell_confirm(callback)

        # Проверяем вызовы
        mock_remove_item.assert_called_once_with(1, 2, 'shawarma')
        mock_update_balance.assert_called_once_with(1, 2, 7500)
        callback.answer.assert_called_once()
        mock_show_menu.assert_called_once()

    @patch('shop.get_user_data')
    @patch('user_manager.remove_item_from_inventory', new_callable=AsyncMock)
    @patch('shop.ITEMS')
    async def test_sell_regular_item_not_in_inventory(self, mock_items, mock_remove_item, mock_get_user_data):
        # Если предмета нет в инвентаре
        mock_items.get.return_value = {'name': 'Шаурмечная', 'price': 10000}
        mock_remove_item.return_value = False  # Предмет не найден

        callback = MagicMock()
        callback.data = "sell_confirm_shawarma"
        callback.message.chat.id = 1
        callback.from_user.id = 2
        callback.answer = AsyncMock()

        await process_sell_confirm(callback)

        # Проверяем, что ответили об ошибке и не начисляли деньги
        mock_remove_item.assert_called_once_with(1, 2, 'shawarma')
        callback.answer.assert_called_once_with("Предмет не найден в вашем инвентаре!", show_alert=True)
