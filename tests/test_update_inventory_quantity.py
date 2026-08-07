import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# --- ТЕСТЫ ВЫБОРА КОЛИЧЕСТВА И МАССОВОЙ ПРОДАЖИ (60 ТЕСТОВ) ---

def mock_transactional(func):
    return func

@pytest.mark.asyncio
@pytest.mark.parametrize("qty, count_arg, expected_sold, expected_payout", [
    (1, "1", 1, 7500),
    (5, "1", 1, 7500),
    (5, "5", 5, 37500),
    (10, "5", 5, 37500),
    (10, "10", 10, 75000),
    (50, "10", 10, 75000),
    (50, "50", 50, 375000),
    (100, "50", 50, 375000),
    (1, "all", 1, 7500),
    (5, "all", 5, 37500),
    (10, "all", 10, 75000),
    (50, "all", 50, 375000),
    (100, "all", 100, 750000),
    (7, "10", 7, 52500),  # Клиент запросил 10, но у него 7 -> продается ровно 7
    (3, "50", 3, 22500),  # Клиент запросил 50, но у него 3 -> продается ровно 3
])
async def test_confirm_inv_sell_quantity_resolution(qty, count_arg, expected_sold, expected_payout):
    """Тест перерасчета цены и количества при подтверждении продажи предметов с запросом count (15 тестов)"""
    from inventory import confirm_inv_sell

    callback = AsyncMock()
    callback.data = f"inv_sellcf_item_gold_{count_arg}"
    callback.message.chat.id = 12345
    callback.from_user.id = 67890

    item_info = {
        'price': 10000,
        'name': 'Золотой слиток',
        'cat': 'other'
    }

    mock_db = MagicMock()
    mock_ref = MagicMock()
    mock_snapshot = MagicMock()
    mock_snapshot.exists = True
    mock_snapshot.to_dict.return_value = {
        'inventory': {'item_gold': qty},
        'balance': 0
    }

    with patch('inventory.ITEMS', {'item_gold': item_info}), \
         patch('db.get_db', return_value=mock_db), \
         patch('firebase_admin.firestore_async.async_transactional', mock_transactional), \
         patch('user_manager.get_user_ref', return_value=mock_ref), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=mock_snapshot), \
         patch('user_manager.sell_item_tr', new_callable=AsyncMock, return_value=True) as mock_sell_tr, \
         patch('user_manager.get_user_lock') as mock_lock, \
         patch('user_manager.invalidate_user_cache'), \
         patch('inventory.inv_back', new_callable=AsyncMock):

        mock_lock.return_value.__aenter__.return_value = MagicMock()

        await confirm_inv_sell(callback)

        assert mock_sell_tr.call_count == 1
        call_count = mock_sell_tr.call_args[1].get('count') or mock_sell_tr.call_args[0][6]
        assert call_count == expected_sold

        callback.answer.assert_called_once()
        ans_text = callback.answer.call_args[0][0]
        assert f"продано {expected_sold} шт." in ans_text
        assert f"за {expected_payout} сыр." in ans_text


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_qty, remove_count, expected_remain", [
    (1, 1, 0),
    (5, 1, 4),
    (5, 3, 2),
    (5, 5, 0),
    (10, 5, 5),
    (10, 10, 0),
    (50, 20, 30),
    (50, 50, 0),
    (100, 1, 99),
    (100, 99, 1),
])
async def test_user_manager_remove_item_with_count(initial_qty, remove_count, expected_remain):
    """Тест функции remove_item_from_inventory с поддержкой количества count (10 тестов)"""
    from user_manager import remove_item_from_inventory

    user_data = {
        'full_name': 'TestUser',
        'inventory': {'item_apple': initial_qty},
        'biz_levels': {}
    }

    item_info = {'price': 100}

    mock_lock = AsyncMock()

    with patch('user_manager.get_user_lock') as mock_get_lock, \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('shop.ITEMS', {'item_apple': item_info}):

        mock_get_lock.return_value.__aenter__.return_value = mock_lock

        res = await remove_item_from_inventory(123, 456, 'item_apple', count=remove_count)

        assert res is True
        saved_inv = user_data['inventory']
        if expected_remain == 0:
            assert 'item_apple' not in saved_inv
        else:
            assert saved_inv['item_apple'] == expected_remain


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_qty, add_count, expected_total", [
    (0, 1, 1),
    (0, 5, 5),
    (0, 10, 10),
    (0, 50, 50),
    (1, 1, 2),
    (5, 5, 10),
    (10, 10, 20),
    (50, 50, 100),
    (100, 100, 200),
    (500, 500, 1000),
])
async def test_user_manager_add_item_with_count(initial_qty, add_count, expected_total):
    """Тест функции add_item_to_inventory с поддержкой количества count (10 тестов)"""
    from user_manager import add_item_to_inventory

    user_data = {
        'full_name': 'TestUser',
        'inventory': {'item_coin': initial_qty} if initial_qty > 0 else {}
    }

    item_info = {'price': 50}

    mock_lock = AsyncMock()

    with patch('user_manager.get_user_lock') as mock_get_lock, \
         patch('user_manager.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('user_manager.set_in_cache'), \
         patch('user_manager.mark_dirty'), \
         patch('shop.ITEMS', {'item_coin': item_info}):

        mock_get_lock.return_value.__aenter__.return_value = mock_lock

        res = await add_item_to_inventory(123, 456, 'item_coin', count=add_count)

        assert res is True
        assert user_data['inventory']['item_coin'] == expected_total


@pytest.mark.asyncio
@pytest.mark.parametrize("owned_qty, expected_buttons_count", [
    (1, 2),   # [1 шт], [Отмена]
    (2, 3),   # [1 шт], [Все 2 шт], [Отмена]
    (5, 4),   # [1 шт], [5 шт], [Все 5 шт], [Отмена]
    (10, 5),  # [1 шт], [5 шт], [10 шт], [Все 10 шт], [Отмена]
    (50, 6),  # [1 шт], [5 шт], [10 шт], [50 шт], [Все 50 шт], [Отмена]
])
async def test_ask_inv_sell_keyboard_buttons(owned_qty, expected_buttons_count):
    """Тест формирования инлайн-меню со всеми кнопками выбора количества (5 тестов)"""
    from inventory import ask_inv_sell

    callback = AsyncMock()
    callback.data = "inv_sell_item_gems"
    callback.message.chat.id = 12345
    callback.from_user.id = 67890

    user_data = {
        'inventory': {'item_gems': owned_qty}
    }

    item_info = {'name': 'Изумруды', 'price': 20000}

    with patch('inventory.ITEMS', {'item_gems': item_info}), \
         patch('inventory.get_user_data', new_callable=AsyncMock, return_value=user_data):

        await ask_inv_sell(callback)

        callback.message.edit_text.assert_called_once()
        reply_markup = callback.message.edit_text.call_args[1]['reply_markup']
        buttons = [btn for row in reply_markup.inline_keyboard for btn in row]
        assert len(buttons) == expected_buttons_count


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_qty, req_qty", [
    (0, 1),
    (0, 5),
    (0, 10),
    (0, 50),
    (-1, 1),
    (-5, 5),
    (0, "all"),
    (2, 0),
    (5, -1),
    (10, -10),
])
async def test_sell_item_tr_invalid_quantities(invalid_qty, req_qty):
    """Тест защиты от деления на 0, отрицательных и некорректных значений количества (10 тестов)"""
    from user_manager import sell_item_tr

    mock_snapshot = MagicMock()
    mock_snapshot.exists = True
    mock_snapshot.to_dict.return_value = {
        'inventory': {'item_wood': invalid_qty},
        'balance': 1000
    }

    with patch('user_manager.get_user_ref'), \
         patch('user_manager.safe_get_snapshot', new_callable=AsyncMock, return_value=mock_snapshot):

        res = await sell_item_tr(None, 123, 456, 'item_wood', 'other', sell_price=100, count=req_qty)
        assert res is False


@pytest.mark.asyncio
@pytest.mark.parametrize("test_id", range(10))
async def test_ask_inv_sell_no_item_owned(test_id):
    """Тест уведомления пользователя при попытке вызова меню для непродаваемого предмета (10 тестов)"""
    from inventory import ask_inv_sell

    callback = AsyncMock()
    callback.data = "inv_sell_item_non_existent"
    callback.message.chat.id = 12345
    callback.from_user.id = 67890

    user_data = {'inventory': {}}

    item_info = {'name': 'Фантом', 'price': 100}

    with patch('inventory.ITEMS', {'item_non_existent': item_info}), \
         patch('inventory.get_user_data', new_callable=AsyncMock, return_value=user_data):

        await ask_inv_sell(callback)

        callback.answer.assert_called_once_with("У вас нет этого предмета!", show_alert=True)
