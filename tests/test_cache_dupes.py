import pytest
import sys
import copy
from unittest.mock import AsyncMock, patch, MagicMock

# Mock system dependencies before importing
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = MagicMock()

import user_manager
import creator
import admin
from aiogram import types

@pytest.fixture(autouse=True)
def clean_cache():
    user_manager._user_cache.clear()
    user_manager._dirty_cache.clear()
    yield
    user_manager._user_cache.clear()
    user_manager._dirty_cache.clear()

@pytest.mark.asyncio
async def test_remove_item_from_inventory_biz_levels_dupe_fix():
    chat_id = 123
    user_id = 456
    item_name = "shaurma"

    # 1. Setup user with 5 businesses
    initial_data = {
        'inventory': {item_name: 5},
        'biz_levels': {item_name: 3}
    }
    user_manager.set_in_cache(chat_id, user_id, initial_data)

    # 2. Sell 4 businesses
    with patch("user_manager.get_user_data", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = initial_data

        for _ in range(4):
            success = await user_manager.remove_item_from_inventory(chat_id, user_id, item_name)
            assert success is True
            # Update the mock return value to the new cached data to simulate real db behavior
            mock_get.return_value = user_manager.get_from_cache(chat_id, user_id)

    # 3. Verify exactly 1 business remains
    final_data = user_manager.get_from_cache(chat_id, user_id)
    assert final_data['inventory'].get(item_name) == 1
    # biz_levels must still be present since we didn't sell all of them
    assert final_data['biz_levels'].get(item_name) == 3

    # 4. Sell the last one
    with patch("user_manager.get_user_data", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = final_data
        success = await user_manager.remove_item_from_inventory(chat_id, user_id, item_name)
        assert success is True

    # 5. Verify biz_levels is completely deleted
    final_empty_data = user_manager.get_from_cache(chat_id, user_id)
    assert item_name not in final_empty_data.get('inventory', {})
    assert item_name not in final_empty_data.get('biz_levels', {})

@pytest.mark.asyncio
async def test_wipe_economy_clears_cache():
    chat_id = 123
    user_id = 456

    # Set dummy data in cache
    user_manager.set_in_cache(chat_id, user_id, {'balance': 999999, 'inventory': {'shaurma': 5}})
    assert len(user_manager._user_cache) > 0

    # Mock message for creator
    msg = AsyncMock()
    msg.text = "/wipe_economy CONFIRM"
    msg.from_user.id = 999

    with patch("creator.is_creator", return_value=True), \
         patch("whitelist.get_whitelist", new_callable=AsyncMock) as mock_whitelist, \
         patch("creator.get_db") as mock_get_db:

        mock_whitelist.return_value = {chat_id: True}

        # Build db mock structure to prevent TypeError when it tries to await batch.commit() or db operations
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.set = AsyncMock()

        # users_ref.get() -> AsyncMock returns list of docs
        mock_collection_obj = MagicMock()
        mock_collection_obj.get = AsyncMock(return_value=[])
        mock_db.collection.return_value.document.return_value.collection.return_value = mock_collection_obj

        mock_batch = MagicMock()
        mock_batch.commit = AsyncMock()
        mock_db.batch.return_value = mock_batch

        mock_get_db.return_value = mock_db

        await creator.cmd_wipe_economy(msg)

        # Verify cache is cleared
        assert len(user_manager._user_cache) == 0

@pytest.mark.asyncio
async def test_wipe_mid_clears_cache():
    chat_id = 123
    user_id = 456

    # Set dummy data in cache
    user_manager.set_in_cache(chat_id, user_id, {'balance': 999999, 'inventory': {'shaurma': 5}})
    assert len(user_manager._user_cache) > 0

    # Mock message for creator
    msg = AsyncMock()
    msg.text = "/wipe_mid CONFIRM"
    msg.from_user.id = 999

    with patch("creator.is_creator", return_value=True), \
         patch("whitelist.get_whitelist", new_callable=AsyncMock) as mock_whitelist, \
         patch("creator.get_db") as mock_get_db:

        mock_whitelist.return_value = {chat_id: True}

        # Build db mock structure to prevent TypeError when it tries to await batch.commit() or db operations
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.set = AsyncMock()

        mock_collection_obj = MagicMock()
        mock_collection_obj.get = AsyncMock(return_value=[])
        mock_db.collection.return_value.document.return_value.collection.return_value = mock_collection_obj

        mock_batch = MagicMock()
        mock_batch.commit = AsyncMock()
        mock_db.batch.return_value = mock_batch

        mock_get_db.return_value = mock_db

        await creator.cmd_wipe_mid(msg)

        # Because wipe_mid spawns an asyncio background task to do the wiping,
        # we need to yield to event loop briefly so the task executes and clears the cache
        import asyncio
        await asyncio.sleep(0.1)

        # Verify cache is cleared
        assert len(user_manager._user_cache) == 0

@pytest.mark.asyncio
async def test_ban_user_removes_from_cache():
    # If the system doesn't automatically pop users from cache on ban natively,
    # let's write a mock test to verify the user is banned.
    # The prompt asked "Напиши тест на функцию wipe/ban: профиль должен полностью очищаться из _user_cache после выполнения наказания."
    # If it isn't implemented in admin.py for `cmd_ban_only_creator`, I should add it!
    chat_id = 123
    target_user_id = 456
    creator_id = 999

    user_manager.set_in_cache(chat_id, target_user_id, {'balance': 999})
    assert (chat_id, target_user_id) in user_manager._user_cache

    msg = AsyncMock()
    msg.text = "!!!ban"
    msg.from_user.id = creator_id
    msg.chat.id = chat_id
    msg.reply_to_message.from_user.id = target_user_id
    msg.reply_to_message.from_user.is_bot = False

    bot = AsyncMock()

    with patch("admin.CREATOR_ID", creator_id):
        await admin.cmd_ban_only_creator(msg, bot)

    # The prompt explicitly asks to assert it's cleared from cache
    assert (chat_id, target_user_id) not in user_manager._user_cache
