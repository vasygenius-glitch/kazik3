import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import shop
import pets
import chances
import user_manager

def test_new_items_exist():
    # Verify new businesses exist
    assert "ларек" in shop.ITEMS
    assert "кинотеатр" in shop.ITEMS
    assert "стадион" in shop.ITEMS
    assert "нейросеть" in shop.ITEMS
    assert "империя" in shop.ITEMS

    # Verify new cars exist
    assert "самокат" in shop.ITEMS
    assert "велосипед" in shop.ITEMS
    assert "ока" in shop.ITEMS
    assert "жигули" in shop.ITEMS
    assert "москвич" in shop.ITEMS
    assert "яхта" in shop.ITEMS
    assert "круизер" in shop.ITEMS
    assert "ракета" in shop.ITEMS
    assert "звезда" in shop.ITEMS
    assert "галактика" in shop.ITEMS
    assert "kovcheg" in shop.ITEMS

    # Verify new pets exist
    assert "hamster" in pets.PETS_SHOP
    assert "fox" in pets.PETS_SHOP
    assert "unicorn" in pets.PETS_SHOP

@pytest.mark.asyncio
async def test_unicorn_win_chance_boost():
    # Mock get_user_data and get_active_diseases
    mock_user_data = {
        "pet": {"id": "unicorn"},
        "balance": 1000
    }
    with patch("user_manager.get_user_data", new_callable=AsyncMock, return_value=mock_user_data), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]), \
         patch("chances.get_game_chance", new_callable=AsyncMock, return_value=35):
        
        # Unicorn boosts 35% by +10% -> 45%
        res_chance = await chances.get_user_win_chance(123, 456, "slots", 35)
        assert res_chance == 45

@pytest.mark.asyncio
async def test_hamster_and_kovcheg_daily_bonus():
    # Mock database and cache methods
    mock_user_data_without_kovcheg = {
        "balance": 1000,
        "pet": {"id": "hamster"},
        "inventory": {},
        "last_daily_time": 0
    }
    
    mock_user_data_with_kovcheg = {
        "balance": 1000,
        "pet": {"id": "hamster"},
        "inventory": {"kovcheg": 1},
        "last_daily_time": 0
    }
    
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value.collection.return_value.where.return_value.get = AsyncMock(return_value=[])
    
    # 1. Test without kovcheg
    with patch("user_manager.get_db", return_value=mock_db), \
         patch("user_manager.get_user_data", new_callable=AsyncMock, return_value=mock_user_data_without_kovcheg), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]), \
         patch("user_manager.get_user_meme_bonuses", return_value={"multiplier": 0.0, "flat": 0}), \
         patch("user_manager.set_in_cache"), \
         patch("user_manager.mark_dirty"), \
         patch("user_manager.flush_user_cache_immediately", new_callable=AsyncMock), \
         patch("economy_utils.get_global_tax", new_callable=AsyncMock, return_value=0):
        
        success, result_without = await user_manager.check_and_give_bonus(123, 456, "User")
        assert success is True
        # Base daily bonus: 150 (BASE_BONUS) + Hamster: 500 = 650
        assert result_without['total'] == 650

    # 2. Test with kovcheg
    with patch("user_manager.get_db", return_value=mock_db), \
         patch("user_manager.get_user_data", new_callable=AsyncMock, return_value=mock_user_data_with_kovcheg), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]), \
         patch("user_manager.get_user_meme_bonuses", return_value={"multiplier": 0.0, "flat": 0}), \
         patch("user_manager.set_in_cache"), \
         patch("user_manager.mark_dirty"), \
         patch("user_manager.flush_user_cache_immediately", new_callable=AsyncMock), \
         patch("economy_utils.get_global_tax", new_callable=AsyncMock, return_value=0):
        
        success, result_with = await user_manager.check_and_give_bonus(123, 456, "User")
        assert success is True
        # Base daily bonus: 150 + Hamster: 500 = 650
        # Plus kovcheg car income: 1,000,000,000 = 1_000_000_650
        # Progressive Tax: 1% on 1B -> 10,000,000 -> 990,000,650
        # Multiplied by 1.2 = 1_188_000_780
        assert result_with['total'] == 1188000780
