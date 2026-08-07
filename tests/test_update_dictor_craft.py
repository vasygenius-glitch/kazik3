import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# --- ТЕСТЫ ИНТЕРАКТИВНОГО КРАФТА И АПГРЕЙДЕРА ДИКТОРОВ ---

DICTOR_RANKS = [
    "dictor_common", "dictor_simple", "dictor_basic",
    "dictor_uncommon", "dictor_rare", "dictor_epic", "dictor_legendary", "dictor_mythic", "dictor_cosmic", "dictor_divine",
    "dictor_shadow", "dictor_abyss", "dictor_elder", "dictor_chaos", "dictor_void", "dictor_infinity", "dictor_secret", "dictor_emperor", "dictor_ghost", "dictor_immortal"
]

@pytest.mark.asyncio
@pytest.mark.parametrize("rank_idx", range(len(DICTOR_RANKS) - 1))
async def test_dictor_craft_success_all_ranks(rank_idx):
    """Тест успешного крафта дикторов для каждого ранга от обычного до призрачного (19 тестов)"""
    from seasons import callback_banya_craft_do
    
    curr_rank = DICTOR_RANKS[rank_idx]
    next_rank = DICTOR_RANKS[rank_idx + 1]

    callback = AsyncMock()
    callback.message = AsyncMock()
    callback.message.chat.id = 12345
    callback.from_user.id = 67890

    # banya_craft_do_{d_id}_{qty}
    parts = curr_rank.split("_")
    callback.data = f"banya_craft_do_{parts[0]}_{parts[1]}_1"

    user_data = {
        'is_banned': False,
        'inventory': {curr_rank: 3}
    }

    with patch('seasons.get_season_config', new_callable=AsyncMock) as mock_cfg, \
         patch('seasons.get_user_data', new_callable=AsyncMock) as mock_user_data, \
         patch('user_manager.remove_item_from_inventory', new_callable=AsyncMock) as mock_remove, \
         patch('user_manager.add_item_to_inventory', new_callable=AsyncMock) as mock_add, \
         patch('random.random', return_value=0.1):  # 0.1 < 0.85 -> Успех

        mock_cfg.return_value = {"active": True, "id": "tayniy_baniy"}
        mock_user_data.return_value = user_data
        mock_remove.return_value = True
        mock_add.return_value = True

        await callback_banya_craft_do(callback)

        mock_remove.assert_called_once_with(12345, 67890, curr_rank, count=3)
        mock_add.assert_called_once_with(12345, 67890, next_rank, count=1)
        callback.message.edit_text.assert_called_once()
        assert "РЕЗУЛЬТАТЫ МАССОВОГО АПГРЕЙДА" in callback.message.edit_text.call_args[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("rank_idx", range(len(DICTOR_RANKS) - 1))
async def test_dictor_craft_failure_all_ranks(rank_idx):
    """Тест неудачи крафта дикторов (19 тестов): сгорают 2 штуки, 1 спасается"""
    from seasons import callback_banya_craft_do
    
    curr_rank = DICTOR_RANKS[rank_idx]

    callback = AsyncMock()
    callback.message = AsyncMock()
    callback.message.chat.id = 12345
    callback.from_user.id = 67890

    parts = curr_rank.split("_")
    callback.data = f"banya_craft_do_{parts[0]}_{parts[1]}_1"

    user_data = {
        'is_banned': False,
        'inventory': {curr_rank: 5}
    }

    with patch('seasons.get_season_config', new_callable=AsyncMock) as mock_cfg, \
         patch('seasons.get_user_data', new_callable=AsyncMock) as mock_user_data, \
         patch('user_manager.remove_item_from_inventory', new_callable=AsyncMock) as mock_remove, \
         patch('user_manager.add_item_to_inventory', new_callable=AsyncMock) as mock_add, \
         patch('random.random', return_value=0.95):  # 0.95 >= 0.85 -> Неудача

        mock_cfg.return_value = {"active": True, "id": "tayniy_baniy"}
        mock_user_data.return_value = user_data
        mock_remove.return_value = True

        await callback_banya_craft_do(callback)

        mock_remove.assert_called_once_with(12345, 67890, curr_rank, count=2)
        mock_add.assert_not_called()
        assert "РЕЗУЛЬТАТЫ МАССОВОГО АПГРЕЙДА" in callback.message.edit_text.call_args[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("qty", [0, 1, 2])
async def test_dictor_craft_not_enough_items(qty):
    """Тест отмены крафта при недостаточном количестве дикторов (< 3) (3 теста)"""
    from seasons import cmd_banya_craft

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890
    message.text = "/banya_craft"

    user_data = {
        'is_banned': False,
        'inventory': {'dictor_common': qty}
    }

    with patch('seasons.get_season_config', new_callable=AsyncMock) as mock_cfg, \
         patch('seasons.get_user_data', new_callable=AsyncMock) as mock_user_data:

        mock_cfg.return_value = {"active": True, "id": "tayniy_baniy"}
        mock_user_data.return_value = user_data

        await cmd_banya_craft(message)

        message.answer.assert_called_once()
        assert "У вас пока нет 3 одинаковых дикторов" in message.answer.call_args[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("season_active, season_id", [
    (False, "tayniy_baniy"),
    (True, "backrooms"),
    (False, "off")
])
async def test_dictor_craft_inactive_season(season_active, season_id):
    """Тест отклонения команды крафта при неактивном банном сезоне (3 теста)"""
    from seasons import cmd_banya_craft

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890

    with patch('seasons.get_season_config', new_callable=AsyncMock) as mock_cfg:
        mock_cfg.return_value = {"active": season_active, "id": season_id}

        await cmd_banya_craft(message)

        message.answer.assert_called_once()
        assert "Сезон Дикторов Тайний Баний сейчас не активен" in message.answer.call_args[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd_alias", ["/banya_craft", "/dictor_craft", "/upgrade_dictor"])
async def test_dictor_craft_command_aliases(cmd_alias):
    """Тест обработки всех алиасов команды крафта (3 теста)"""
    from seasons import cmd_banya_craft

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890
    message.text = cmd_alias

    with patch('seasons.get_season_config', new_callable=AsyncMock) as mock_cfg, \
         patch('seasons.get_user_data', new_callable=AsyncMock) as mock_user_data:

        mock_cfg.return_value = {"active": True, "id": "tayniy_baniy"}
        mock_user_data.return_value = {'is_banned': False, 'inventory': {'dictor_common': 4}}

        await cmd_banya_craft(message)

        message.answer.assert_called_once()
        assert "АПГРЕЙДЕР ДИКТОРОВ ТАЙНИЙ БАНИЙ" in message.answer.call_args[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("test_id", range(3))
async def test_dictor_craft_banned_user(test_id):
    """Тест блокировки забаненных пользователей при попытке крафта (3 теста)"""
    from seasons import cmd_banya_craft

    message = AsyncMock()
    message.chat.id = 12345
    message.from_user.id = 67890
    message.text = "/banya_craft"

    with patch('seasons.get_season_config', new_callable=AsyncMock) as mock_cfg, \
         patch('seasons.get_user_data', new_callable=AsyncMock) as mock_user_data:

        mock_cfg.return_value = {"active": True, "id": "tayniy_baniy"}
        mock_user_data.return_value = {'is_banned': True, 'inventory': {'dictor_common': 5}}

        await cmd_banya_craft(message)

        message.answer.assert_not_called()
