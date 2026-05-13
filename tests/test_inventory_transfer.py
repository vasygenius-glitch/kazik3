import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_biz_level_removal_on_shop_sell():
    from shop import process_sell_confirm

    mock_items = {
        'киоск': {'name': 'Киоск', 'price': 1000}
    }

    mock_callback = MagicMock()
    mock_callback.data = "sell_confirm_киоск"
    mock_callback.from_user.id = 123
    mock_callback.message.chat.id = 456
    mock_callback.answer = AsyncMock()

    mock_data = {
        'inventory': {'киоск': 1},
        'biz_levels': {'киоск': 5, 'шаурмичная': 2}
    }

    with patch('shop.ITEMS', mock_items):
        with patch('shop.get_user_data', AsyncMock(return_value=mock_data)):
            with patch('shop.update_user_field', AsyncMock()) as mock_update_field:
                with patch('user_manager.remove_item_from_inventory', AsyncMock(return_value=True)):
                    with patch('shop.update_user_balance', AsyncMock()):
                        with patch('shop.show_sell_menu', AsyncMock()):
                            # Process uses local update_user_field reference which we didn't patch fully correctly.
                            # Oh, shop.py actually imports update_user_field from user_manager. Let's patch user_manager.
                            with patch('user_manager.update_user_field', AsyncMock()) as real_update_field:
                                await process_sell_confirm(mock_callback)
                                real_update_field.assert_called_with(456, 123, 'biz_levels', {'шаурмичная': 2})

@pytest.mark.asyncio
async def test_biz_level_removal_on_trade():
    from contracts import process_all_deals
    import contracts

    contracts.active_deals['123'] = {
        'type': 'trade',
        'from_id': 111,
        'to_id': 222,
        'price': 100,
        'item': 'киоск'
    }

    mock_callback = MagicMock()
    mock_callback.data = "deal_yes_123"
    mock_callback.from_user.id = 222
    mock_callback.message.chat.id = 456
    mock_callback.message.edit_text = AsyncMock()

    mock_buyer_data = {'balance': 200}
    mock_seller_data = {
        'inventory': {'киоск': 1},
        'biz_levels': {'киоск': 3, 'бар': 1}
    }

    async def mock_get_user_data(chat_id, user_id):
        if user_id == 222: return mock_buyer_data
        if user_id == 111: return mock_seller_data
        return {}

    with patch('contracts.get_user_data', side_effect=mock_get_user_data):
        with patch('contracts.update_user_field', AsyncMock()) as mock_update_field:
            with patch('user_manager.remove_item_from_inventory', AsyncMock(return_value=True)):
                with patch('user_manager.add_item_to_inventory', AsyncMock()):
                    with patch('contracts.update_user_balance', AsyncMock()):
                        with patch('user_manager.update_user_field', AsyncMock()) as real_update_field:
                            await process_all_deals(mock_callback)
                            mock_update_field.assert_called_with(456, 111, 'biz_levels', {'бар': 1})

@pytest.mark.asyncio
async def test_biz_level_removal_on_inheritance():
    from contracts import process_all_deals
    import contracts

    contracts.active_deals['999'] = {
        'type': 'inheritance',
        'from_id': 111,
        'to_id': 222
    }

    mock_callback = MagicMock()
    mock_callback.data = "deal_yes_999"
    mock_callback.from_user.id = 222
    mock_callback.message.chat.id = 456
    mock_callback.message.edit_text = AsyncMock()

    mock_seller_data = {
        'balance': 100,
        'bank_deposit': 50,
        'inventory': {'киоск': 1},
        'biz_levels': {'киоск': 3}
    }
    mock_target_data = {
        'balance': 0,
        'bank_deposit': 0,
        'inventory': {}
    }

    async def mock_get_user_data(chat_id, user_id):
        if user_id == 111: return mock_seller_data
        if user_id == 222: return mock_target_data
        return {}

    with patch('contracts.get_user_data', side_effect=mock_get_user_data):
        with patch('contracts.update_user_field', AsyncMock()) as mock_update_field:
            with patch('contracts.update_user_balance', AsyncMock()):
                await process_all_deals(mock_callback)

                # Check that the sender's biz_levels are zeroed out
                mock_update_field.assert_any_call(456, 111, 'biz_levels', {})
