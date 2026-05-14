import pytest
from unittest.mock import AsyncMock, patch
from user_manager import remove_item_from_inventory

@pytest.mark.asyncio
async def test_remove_item_from_inventory_mutability():
    # Setup mock data to represent what's in the cache
    mock_cache_data = {
        'inventory': {'бизнес_1': 1, 'бизнес_2': 1},
        'biz_levels': {'бизнес_1': 2}
    }

    # Store the original dictionaries exactly as they are in memory
    original_inv = mock_cache_data['inventory']
    original_biz_levels = mock_cache_data['biz_levels']

    with patch('user_manager.get_user_lock', return_value=AsyncMock()):
        with patch('user_manager.get_user_data', AsyncMock(return_value=mock_cache_data)):
            with patch('user_manager.set_in_cache'):
                with patch('user_manager.mark_dirty'):
                    # Call the function
                    success = await remove_item_from_inventory(123, 456, 'бизнес_1')

                    assert success is True

                    # Because we used .copy(), the original dictionary reference
                    # should STILL be unchanged from when it was fetched
                    # Actually, we mutated `inv` (the copy) and reassigned `data['inventory'] = inv`.
                    # So `mock_cache_data['inventory']` is now the new dictionary.
                    # BUT `original_inv` should be unchanged!
                    assert 'бизнес_1' in original_inv
                    assert 'бизнес_1' in original_biz_levels

                    # And the new assigned dictionary in data should NOT have it
                    new_inv = mock_cache_data['inventory']
                    new_biz_levels = mock_cache_data['biz_levels']

                    assert 'бизнес_1' not in new_inv
                    assert 'бизнес_1' not in new_biz_levels
                    assert new_inv is not original_inv
                    assert new_biz_levels is not original_biz_levels
