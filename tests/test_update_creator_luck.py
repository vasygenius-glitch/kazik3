import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# --- 100 ТЕСТОВ ПРИВИЛЕГИЙ И ТОПОВОЙ ВЫПАДАЕМОСТИ ДЛЯ CREATOR ID ---

CREATOR_TEST_ID = 5416583030

@pytest.mark.parametrize("test_id", range(50))
def test_roll_card_from_case_top_rarity_for_creator(test_id):
    """Тест: функция roll_card_from_case возвращает ТОЛЬКО топовые редкости для Creator ID (50 тестов)"""
    from cards_system import roll_card_from_case, CASES, CARDS

    case_info = CASES["free_case"]

    with patch('cards_system.CREATOR_ID', CREATOR_TEST_ID), \
         patch('cards_system.CREATOR_IDS', {CREATOR_TEST_ID}):

        card_id = roll_card_from_case(case_info, user_id=CREATOR_TEST_ID)
        assert card_id is not None

        card = CARDS[card_id]
        rarity = card["rarity"]

        # Проверяем, что редкость входит в список топовых
        assert rarity in ("LEGENDARY", "MYTHIC", "EPIC")


@pytest.mark.asyncio
@pytest.mark.parametrize("test_id", range(50))
async def test_cmd_banya_case_top_dictor_for_creator(test_id):
    """Тест: команда /banya_case в seasons.py выдает ТОЛЬКО топовых дикторов Создателю бота (50 тестов)"""
    from seasons import cmd_banya_case

    message = AsyncMock()
    message.chat.id = 50000 + test_id
    message.from_user.id = CREATOR_TEST_ID
    message.from_user.full_name = "Creator Admin"

    user_data = {
        'balance': 100000,
        'inventory': {},
        'is_banned': False
    }

    season_cfg = {
        'active': True,
        'id': 'tayniy_baniy'
    }

    mock_msg = AsyncMock()
    message.answer.return_value = mock_msg

    with patch('seasons.CREATOR_ID', CREATOR_TEST_ID), \
         patch('seasons.CREATOR_IDS', {CREATOR_TEST_ID}), \
         patch('seasons.get_season_config', new_callable=AsyncMock, return_value=season_cfg), \
         patch('seasons.get_user_data', new_callable=AsyncMock, return_value=user_data), \
         patch('seasons.update_user_balance', new_callable=AsyncMock), \
         patch('user_manager.add_item_to_inventory', new_callable=AsyncMock, return_value=True), \
         patch('asyncio.sleep', new_callable=AsyncMock):

        await cmd_banya_case(message)

        mock_msg.edit_text.assert_called_once()
        res_text = mock_msg.edit_text.call_args[0][0]

        # Убеждаемся, что выпал топовый диктор
        top_rarities = [
            "Бессмертный", "Императорский", "Секретный", "Божественный",
            "Бесконечный", "Призрачный", "Хаоса", "Пустоты", "Космический", "Мифический", "Легендарный"
        ]
        assert any(r in res_text for r in top_rarities)
