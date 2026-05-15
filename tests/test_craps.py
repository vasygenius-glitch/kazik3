import unittest
import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Mock external dependencies
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = MagicMock()
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()
sys.modules['config'].CREATOR_ID = 999

import craps

class TestCrapsGame(unittest.IsolatedAsyncioTestCase):
    async def test_craps_win_rate(self):
        msg = AsyncMock()
        msg.text = "/craps 100"
        msg.chat.id = 123
        msg.from_user.id = 456

        with patch("craps.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("craps.update_user_balance", new_callable=AsyncMock) as mock_update, \
             patch("craps.secrets.SystemRandom.randint") as mock_randint, \
             patch("craps.secrets.SystemRandom.choice") as mock_choice:

            mock_get_data.return_value = {'balance': 1000}
            sys.modules['diseases'].get_active_diseases = AsyncMock(return_value=[])

            # Setup mock to simulate a win roll (total 7) on the first try
            # mock_randint is called for 1-100 (win chance), then for die1, die2
            mock_randint.side_effect = [35, 3, 4] # 35 <= 35 (forced win), die1=3, die2=4 => total 7 (natural win)

            await craps.cmd_craps(msg)
            mock_update.assert_called_once_with(123, 456, 100)

    async def test_craps_loss_rate(self):
        msg = AsyncMock()
        msg.text = "/craps 100"
        msg.chat.id = 123
        msg.from_user.id = 456

        with patch("craps.get_user_data", new_callable=AsyncMock) as mock_get_data, \
             patch("craps.update_user_balance", new_callable=AsyncMock) as mock_update, \
             patch("craps.secrets.SystemRandom.randint") as mock_randint, \
             patch("craps.secrets.SystemRandom.choice") as mock_choice:

            mock_get_data.return_value = {'balance': 1000}
            sys.modules['diseases'].get_active_diseases = AsyncMock(return_value=[])

            # Setup mock to simulate a loss roll
            # mock_randint is called for 1-100 (win chance), then for die1, die2
            mock_randint.side_effect = [36, 1, 1] # 36 > 35 (forced loss), die1=1, die2=1 => total 2 (craps loss)

            await craps.cmd_craps(msg)
            mock_update.assert_called_once_with(123, 456, -100)

if __name__ == '__main__':
    unittest.main()
