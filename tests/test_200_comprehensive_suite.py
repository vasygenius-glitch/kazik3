import pytest
from shop import ITEMS
from cards_system import CARDS
from creator import DICTORS_LIST, resolve_dictor_id
from user_manager import (
    is_dictor_item,
    preserve_protected_inventory,
    add_item_to_inventory,
    remove_item_from_inventory,
    get_user_data,
    update_user_field,
    get_unsettled_transfers_24h,
)
from prestige import (
    PRESTIGE_TIERS,
    get_user_prestige,
    get_prestige_perks,
    get_required_business_count,
    count_user_businesses,
)
from inventory import get_inventory_main_kb

# ==============================================================================
#  1. 70 ТЕСТОВ: КАЖДЫЙ ДИКТОР ИНДИВИДУАЛЬНО (1..70)
# ==============================================================================
@pytest.mark.parametrize("index,item_tuple", enumerate(DICTORS_LIST, start=1))
def test_dictor_individual_rank(index, item_tuple):
    dictor_id, title = item_tuple
    assert dictor_id in ITEMS, f"Диктор {dictor_id} отсутствует в ITEMS!"
    cfg = ITEMS[dictor_id]
    assert cfg.get("cat") == "tayniy_baniy"
    assert cfg.get("action") in ("other", "dictor")
    assert len(cfg.get("name", "")) > 0
    assert len(cfg.get("desc", "")) > 0
    assert resolve_dictor_id(str(index)) == dictor_id
    assert is_dictor_item(dictor_id) is True
    preserved = preserve_protected_inventory({dictor_id: 5, "junk": 10})
    assert preserved.get(dictor_id) == 5
    assert "junk" not in preserved


# ==============================================================================
#  2. 200 ТЕСТОВ: КАЖДАЯ ИЗ 200 МЕМ-КАРТ ИНДИВИДУАЛЬНО
# ==============================================================================
@pytest.mark.parametrize("card_id,card_cfg", list(CARDS.items()))
def test_card_individual(card_id, card_cfg):
    assert "name" in card_cfg
    assert "rarity" in card_cfg
    assert "description" in card_cfg
    assert "bonus_multiplier" in card_cfg
    assert "bonus_flat" in card_cfg
    assert card_cfg["bonus_multiplier"] >= 0
    assert card_cfg["bonus_flat"] >= 0


# ==============================================================================
#  3. 12 ТЕСТОВ: КАЖДЫЙ ПРЕДМЕТ ПРЕСТИЖА (1..12)
# ==============================================================================
prestige_items_list = [(k, v) for k, v in ITEMS.items() if v.get("cat") == "prestige"]
@pytest.mark.parametrize("p_id,p_cfg", prestige_items_list)
def test_prestige_item_individual(p_id, p_cfg):
    assert p_cfg.get("cat") == "prestige"
    assert p_cfg.get("req_prestige") in (1, 2, 3, 4, 5, 6)
    assert p_cfg.get("income", 0) > 0
    assert p_cfg.get("price", 0) > 0


# ==============================================================================
#  4. 10 ТЕСТОВ: БИЗНЕСЫ (1..10)
# ==============================================================================
biz_items_list = [(k, v) for k, v in ITEMS.items() if v.get("cat") == "biz"]
@pytest.mark.parametrize("b_id,b_cfg", biz_items_list)
def test_biz_item_individual(b_id, b_cfg):
    assert b_cfg.get("action") == "business"
    assert b_cfg.get("income", 0) > 0
    assert b_cfg.get("price", 0) > 0


# ==============================================================================
#  5. 12 ТЕСТОВ: МАШИНЫ И ТРАНСПОРТ (1..12)
# ==============================================================================
car_items_list = [(k, v) for k, v in ITEMS.items() if v.get("cat") == "cars"]
@pytest.mark.parametrize("c_id,c_cfg", car_items_list)
def test_car_item_individual(c_id, c_cfg):
    assert c_cfg.get("action") == "car"
    assert c_cfg.get("price", 0) > 0


# ==============================================================================
#  6. 6 ТЕСТОВ: РАНГИ ПРЕСТИЖА 1..6
# ==============================================================================
@pytest.mark.parametrize("tier", [1, 2, 3, 4, 5, 6])
def test_prestige_tier_integrity(tier):
    assert tier in PRESTIGE_TIERS
    t_info = PRESTIGE_TIERS[tier]
    assert t_info["income_multiplier"] > 1.0
    assert t_info["luck_bonus"] >= 0
    assert len(t_info["badge"]) > 0
    assert len(t_info["name"]) > 0
    assert get_required_business_count(tier) >= 3


# ==============================================================================
#  7. 10 ТЕСТОВ: КАРАНТИН И ANTI-BOOST
# ==============================================================================
@pytest.mark.parametrize("amt", [1000, 50000, 1000000, 5000000, 10000000, 50000000, 100000000, 500000000, 1000000000, 5000000000])
def test_quarantine_amounts(amt):
    u_data = {"unsettled_transfers": [{"amount": amt, "ts": 1000000000}]}
    # Для старых меток времени сумма должна быть 0
    assert get_unsettled_transfers_24h(u_data) == 0


# ==============================================================================
#  8. 15 ТЕСТОВ: ИММУНИТЕТ ДИКТОРОВ И ИНВЕНТАРЬ
# ==============================================================================
@pytest.mark.parametrize("dictor_id", [
    "dictor_common", "dictor_rare", "dictor_epic", "dictor_legendary", "dictor_mythic",
    "dictor_cosmic", "dictor_divine", "dictor_abyss", "dictor_void", "dictor_infinity",
    "dictor_sovereign", "dictor_godlike", "dictor_antigravity", "dictor_creation", "dictor_destruction"
])
@pytest.mark.asyncio
async def test_dictor_persistence_and_grant(dictor_id):
    from user_manager import set_in_cache
    chat_id = -100111222
    user_id = 999333
    set_in_cache(chat_id, user_id, {"inventory": {}, "balance": 1000, "full_name": "Тестер"})
    
    # Добавление
    ok = await add_item_to_inventory(chat_id, user_id, dictor_id, count=2)
    assert ok is True
    
    data = await get_user_data(chat_id, user_id)
    assert data["inventory"].get(dictor_id) == 2
    
    # Проверка инвентаря
    kb = get_inventory_main_kb(data["inventory"], {})
    assert kb is not None
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any(ITEMS[dictor_id]["name"] in t for t in button_texts)
    
    # Проверка списания 1 шт
    rem = await remove_item_from_inventory(chat_id, user_id, dictor_id, count=1)
    assert rem is True
    data2 = await get_user_data(chat_id, user_id)
    assert data2["inventory"].get(dictor_id) == 1


# ==============================================================================
#  9. 10 ТЕСТОВ: РЕЗОЛВЕР И КОМАНДЫ
# ==============================================================================
@pytest.mark.parametrize("query,expected_id", [
    ("1", "dictor_common"),
    ("70", "dictor_antigravity"),
    ("69", "dictor_godlike"),
    ("68", "dictor_sovereign"),
    ("67", "dictor_destruction"),
    ("66", "dictor_creation"),
    ("antigravity", "dictor_antigravity"),
    ("godlike", "dictor_godlike"),
    ("легендарный", "dictor_legendary"),
    ("божественный", "dictor_divine"),
])
def test_dictor_smart_resolver(query, expected_id):
    assert resolve_dictor_id(query) == expected_id
