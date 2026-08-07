import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from seasons import (
    BANYA_DICTORS_LIST, DICTOR_RANKS, allocate_batch_drops,
    cmd_banya_spin, cmd_banya_case, callback_banya_craft_do
)
from cards import get_random_card, calculate_score, format_cards, get_baccarat_score
from cards_system import get_rarity_emoji, get_rarity_name, roll_card_from_case, format_card_bonuses, build_shop_keyboard
from inventory import get_inventory_main_kb, cmd_inventory
from shop import cmd_shop

# =====================================================================
# 1. BANYA SEASON & CASES (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("case_qty", [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000])
def test_allocate_batch_drops_10_quantities(case_qty):
    weights = [d["weight"] for d in BANYA_DICTORS_LIST]
    drops = allocate_batch_drops(case_qty, BANYA_DICTORS_LIST, weights=weights)
    assert sum(drops.values()) == case_qty

@pytest.mark.parametrize("idx", range(10))
def test_banya_dictors_list_structure(idx):
    item = BANYA_DICTORS_LIST[idx % len(BANYA_DICTORS_LIST)]
    assert "id" in item
    assert "name" in item
    assert "weight" in item
    assert "rarity" in item

@pytest.mark.parametrize("rank_idx", range(10))
def test_dictor_ranks_10_items(rank_idx):
    rank = DICTOR_RANKS[rank_idx % len(DICTOR_RANKS)]
    assert isinstance(rank, str)

@pytest.mark.asyncio
@pytest.mark.parametrize("qty", [1, 2, 3, 5, 10, 15, 20, 25, 30, 50])
async def test_cmd_banya_case_openings_10_cases(qty):
    message = AsyncMock()
    message.chat.id = 777000
    message.from_user.id = 666000
    message.text = f"/banya_case {qty}"
    
    user_data = {"inventory": {"banya_case": qty}, "balance": 100000}
    with patch("seasons.get_user_data", new_callable=AsyncMock, return_value=user_data), \
         patch("user_manager.add_item_to_inventory", new_callable=AsyncMock, return_value=True), \
         patch("user_manager.remove_item_from_inventory", new_callable=AsyncMock, return_value=True):
        await cmd_banya_case(message)
        message.answer.assert_called_once()

# =====================================================================
# 2. CARDS & CARDS SYSTEM (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("idx", range(10))
def test_get_random_card_10_runs(idx):
    card = get_random_card()
    assert isinstance(card, dict)
    assert "rank" in card
    assert "suit" in card

@pytest.mark.parametrize("rarity", ["common", "uncommon", "rare", "epic", "legendary", "mythic", "exotic", "godly", "secret", "unique"])
def test_get_rarity_emoji_10_rarities(rarity):
    emoji = get_rarity_emoji(rarity)
    assert isinstance(emoji, str)

@pytest.mark.parametrize("rarity", ["common", "uncommon", "rare", "epic", "legendary", "mythic", "exotic", "godly", "secret", "unique"])
def test_get_rarity_name_10_rarities(rarity):
    name = get_rarity_name(rarity)
    assert isinstance(name, str)

@pytest.mark.parametrize("idx", range(10))
def test_build_shop_keyboard_10_runs(idx):
    kb = build_shop_keyboard()
    assert kb is not None

# =====================================================================
# 3. INVENTORY & SHOP (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("page_num", range(10))
def test_get_inventory_main_kb_10_pages(page_num):
    inv = {f"car_1": 1, "house_1": 1}
    biz = {}
    kb = get_inventory_main_kb(inv, biz, page=page_num)
    assert kb is not None

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_inventory_10_runs(idx):
    message = AsyncMock()
    message.chat.id = 888000 + idx
    message.from_user.id = 999000 + idx
    message.text = "/inventory"
    
    user_data = {"inventory": {"car_1": 1}, "balance": 1000}
    with patch("inventory.get_user_data", new_callable=AsyncMock, return_value=user_data):
        await cmd_inventory(message)
        message.answer.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("idx", range(10))
async def test_cmd_shop_10_runs(idx):
    message = AsyncMock()
    message.chat.id = 777000 + idx
    message.from_user.id = 666000 + idx
    message.text = "/shop"
    
    user_data = {"inventory": {}, "balance": 50000}
    with patch("shop.get_user_data", new_callable=AsyncMock, return_value=user_data):
        await cmd_shop(message)
        message.answer.assert_called_once()
