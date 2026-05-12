import asyncio
import os
import sys

# Mock sys modules
from unittest.mock import MagicMock, AsyncMock

class MockFirestore:
    pass
sys.modules['google.cloud.firestore'] = MagicMock()
sys.modules['google.cloud'] = MagicMock()
sys.modules['firebase_admin'] = MagicMock()

from shop import process_buy

async def test():
    # Mock callback
    callback = MagicMock()
    callback.data = "buy_вип"
    callback.message.chat.id = 1
    callback.from_user.id = 1
    callback.answer = AsyncMock()

    # Mock get_user_data via patching module
    import shop
    shop.get_user_data = AsyncMock(return_value={'is_vip': True, 'balance': 1000000000})

    # Call
    await process_buy(callback)

    # Assert that answer was called with duplicate VIP message
    callback.answer.assert_called_with("У вас уже есть VIP", show_alert=True)
    print("Test passed successfully")

if __name__ == "__main__":
    asyncio.run(test())
