import unittest
import sys
import itertools
from unittest.mock import AsyncMock, patch, MagicMock

# Mock external dependencies
mock_fa_async = MagicMock()
mock_fa_async.transactional = lambda f: f
mock_fa_async.async_transactional = lambda f: f

firebase_admin_mock = MagicMock()
firebase_admin_mock.firestore_async = mock_fa_async

sys.modules['firebase_admin'] = firebase_admin_mock
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = mock_fa_async
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()
sys.modules['config'].CREATOR_ID = 999

import slots

class TestSlots(unittest.IsolatedAsyncioTestCase):
    async def test_slots_forced_win(self):
        with patch("slots.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("slots.update_user_balance", new_callable=AsyncMock) as mock_update, \
             patch("slots.secrets.SystemRandom.randint") as mock_randint, \
             patch("slots.secrets.SystemRandom.choice") as mock_choice:

            mock_get_data.return_value = {'balance': 1000}
            sys.modules['diseases'].get_active_diseases = AsyncMock(return_value=[])

            # Callback
            callback = AsyncMock()
            callback.data = "cas_conf_slots_100"
            callback.message.chat.id = 123
            callback.from_user.id = 456

            # mock_randint calls:
            # 1. win chance check: 35 <= 35 (forced win)
            # 2. 3-of-a-kind check: 16 > 15 (leads to pair)
            mock_randint.side_effect = [35, 16]
            # choice mock for EMOJIS (Cherry/Lemon/Watermelon/etc.)
            # Cycle makes it infinite, returning "🍒", "🍒", "🍋" repeatedly.
            mock_choice.side_effect = itertools.cycle(["🍒", "🍒", "🍋"])

            await slots.process_slots_confirm(callback)
            # update_user_balance is called with -100 for bet deduction, then +150 for win (100 * 1.5 - wait, cherries payout is x0.5 profit, i.e. bet + profit = 150)
            mock_update.assert_any_call(123, 456, 150, action='Slots Win')

    async def test_slots_forced_loss(self):
        with patch("slots.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("slots.update_user_balance", new_callable=AsyncMock) as mock_update, \
             patch("slots.secrets.SystemRandom.randint") as mock_randint, \
             patch("slots.secrets.SystemRandom.choice") as mock_choice:

            mock_get_data.return_value = {'balance': 1000}
            sys.modules['diseases'].get_active_diseases = AsyncMock(return_value=[])

            # Callback
            callback = AsyncMock()
            callback.data = "cas_conf_slots_100"
            callback.message.chat.id = 123
            callback.from_user.id = 456

            # mock_randint: win chance check: 36 > 35 (forced loss)
            mock_randint.side_effect = [36]
            # Cycle makes it infinite, returning "🍒", "🍋", "🍉" repeatedly (no pairs).
            mock_choice.side_effect = itertools.cycle(["🍒", "🍋", "🍉"])

            await slots.process_slots_confirm(callback)
            mock_update.assert_any_call(123, 456, -100, min_balance=-5000)

if __name__ == '__main__':
    unittest.main()
