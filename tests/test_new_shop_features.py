# -*- coding: utf-8 -*-
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import shop
import pets
import chances
import user_manager
import economy_features

def test_new_items_exist():
    # Verify new businesses exist
    assert "семечки" in shop.ITEMS
    assert "газеты" in shop.ITEMS
    assert "свип" in shop.ITEMS
    assert "пирожки" in shop.ITEMS
    assert "цветы" in shop.ITEMS
    assert "ларек" in shop.ITEMS
    assert "кинотеатр" in shop.ITEMS
    assert "стадион" in shop.ITEMS
    assert "нейросеть" in shop.ITEMS
    assert "sec_bunker" in shop.ITEMS
    assert "империя" in shop.ITEMS
    assert "мегакорп" in shop.ITEMS
    assert "звездные_врата" in shop.ITEMS
    assert "сфера_дайсона" in shop.ITEMS
    assert "сингулярность" in shop.ITEMS
    assert "мультивселенная" in shop.ITEMS

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

@pytest.mark.asyncio
async def test_steal_bunker_protection():
    # Setup mock message and bot
    message = MagicMock()
    message.reply_to_message = MagicMock()
    message.chat.id = 123
    message.from_user.id = 111
    message.from_user.is_bot = False
    message.reply_to_message.from_user.id = 222
    message.reply_to_message.from_user.is_bot = False
    message.reply_to_message.from_user.full_name = "Victim"
    message.answer = AsyncMock()
    
    bot = MagicMock()
    
    # Mock victim member status
    target_member = MagicMock()
    target_member.status = 'member'
    bot.get_chat_member = AsyncMock(return_value=target_member)
    
    # Mock data for thief (111) and victim (222)
    thief_data = {
        "balance": 5000,
        "last_steal_time": 0
    }
    
    victim_data = {
        "balance": 10000,
        "inventory": {"sec_bunker": 1}
    }
    
    def get_user_data_mock(chat_id, user_id, full_name=None):
        if user_id == 111:
            return thief_data
        return victim_data
        
    with patch("economy_features.get_user_data", side_effect=get_user_data_mock), \
         patch("diseases.get_active_diseases", new_callable=AsyncMock, return_value=[]):
        
        await economy_features.cmd_steal(message, bot)
        
        # Verify message.answer was called saying protected by Undergound Bunker
        message.answer.assert_called_once()
        args, kwargs = message.answer.call_args
        msg = args[0]
        assert "Victim" in msg
        assert msg.startswith("🛡")
