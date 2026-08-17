import pytest
import time
from prestige import (
    PRESTIGE_TIERS,
    get_user_prestige,
    get_prestige_perks,
    get_unsettled_transfers_24h,
    get_required_business_count,
    count_user_businesses,
    calculate_user_net_worth,
    render_progress_bar,
)
from user_manager import preserve_protected_inventory


# ============================================================
#  1. PRESTIGE TIERS DATA & PERKS (20 Tests)
# ============================================================

def test_prestige_tiers_total_count():
    assert len(PRESTIGE_TIERS) == 6


@pytest.mark.parametrize("tier,name,roman,cost,mult,tax_disc,luck,bonus", [
    (1, "Барон", "I", 50_000_000, 1.15, 5, 5, 10_000),
    (2, "Магнат", "II", 250_000_000, 1.30, 10, 10, 50_000),
    (3, "Олигарх", "III", 1_000_000_000, 1.50, 15, 15, 250_000),
    (4, "Владыка", "IV", 5_000_000_000, 1.75, 20, 20, 1_000_000),
    (5, "Титан", "V", 25_000_000_000, 2.00, 25, 25, 5_000_000),
    (6, "Абсолют", "VI", 100_000_000_000, 2.50, 35, 35, 25_000_000),
])
def test_prestige_tier_parameters(tier, name, roman, cost, mult, tax_disc, luck, bonus):
    info = PRESTIGE_TIERS[tier]
    assert info["name"] == name
    assert info["roman"] == roman
    assert info["cost"] == cost
    assert info["income_multiplier"] == mult
    assert info["tax_discount"] == tax_disc
    assert info["luck_bonus"] == luck
    assert info["starting_bonus"] == bonus


def test_prestige_level_getter_valid():
    assert get_user_prestige({"prestige_level": 3}) == 3
    assert get_user_prestige({"prestige_level": 6}) == 6


def test_prestige_level_getter_empty_or_invalid():
    assert get_user_prestige({}) == 0
    assert get_user_prestige({"prestige_level": None}) == 0
    assert get_user_prestige({"prestige_level": "invalid"}) == 0
    assert get_user_prestige({"prestige_level": -5}) == -5


def test_prestige_perks_level_0():
    perks = get_prestige_perks({"prestige_level": 0})
    assert perks["level"] == 0
    assert perks["name"] == "Обыватель"
    assert perks["income_multiplier"] == 1.0
    assert perks["tax_discount"] == 0
    assert perks["luck_bonus"] == 0


@pytest.mark.parametrize("tier", [1, 2, 3, 4, 5, 6])
def test_prestige_perks_all_tiers(tier):
    perks = get_prestige_perks({"prestige_level": tier})
    expected = PRESTIGE_TIERS[tier]
    assert perks["level"] == tier
    assert perks["name"] == expected["name"]
    assert perks["income_multiplier"] == expected["income_multiplier"]
    assert perks["tax_discount"] == expected["tax_discount"]
    assert perks["luck_bonus"] == expected["luck_bonus"]


def test_prestige_perks_overflow_level():
    perks = get_prestige_perks({"prestige_level": 99})
    assert perks["name"] == "Абсолют"
    assert perks["income_multiplier"] == 2.50


# ============================================================
#  2. UNSETTLED TRANSFERS QUARANTINE (15 Tests)
# ============================================================

def test_unsettled_transfers_empty():
    assert get_unsettled_transfers_24h({}) == 0
    assert get_unsettled_transfers_24h({"unsettled_transfers": []}) == 0
    assert get_unsettled_transfers_24h({"unsettled_transfers": "invalid"}) == 0


def test_unsettled_transfers_recent_valid():
    now = time.time()
    user_data = {
        "unsettled_transfers": [
            {"amount": 1_000_000, "ts": now - 100},
            {"amount": 5_000_000, "ts": now - 3600},
            {"amount": 2_500_000, "ts": now - 72000},
        ]
    }
    assert get_unsettled_transfers_24h(user_data) == 8_500_000


def test_unsettled_transfers_expired():
    now = time.time()
    user_data = {
        "unsettled_transfers": [
            {"amount": 50_000_000, "ts": now - 86401},
            {"amount": 100_000_000, "ts": now - 200000},
        ]
    }
    assert get_unsettled_transfers_24h(user_data) == 0


def test_unsettled_transfers_mixed_active_and_expired():
    now = time.time()
    user_data = {
        "unsettled_transfers": [
            {"amount": 10_000_000, "ts": now - 3600},       # active
            {"amount": 20_000_000, "ts": now - 90000},      # expired
            {"amount": 5_000_000, "ts": now - 80000},       # active
            {"amount": 0, "ts": now - 10},                  # zero amount
            {"amount": -500, "ts": now - 10},               # negative
        ]
    }
    assert get_unsettled_transfers_24h(user_data) == 15_000_000


@pytest.mark.parametrize("amount,offset,is_active", [
    (100, 10, True),
    (200, 43200, True),
    (300, 86399, True),
    (400, 86400, False),
    (500, 86401, False),
    (600, 100000, False),
])
def test_unsettled_transfer_boundary_condition(amount, offset, is_active):
    now = time.time()
    user_data = {"unsettled_transfers": [{"amount": amount, "ts": now - offset}]}
    expected = amount if is_active else 0
    assert get_unsettled_transfers_24h(user_data) == expected


# ============================================================
#  3. BUSINESS REQUIREMENTS & COUNTING (15 Tests)
# ============================================================

@pytest.mark.parametrize("target_tier,req_count", [
    (1, 3),
    (2, 5),
    (3, 7),
    (4, 9),
    (5, 12),
    (6, 15),
    (7, 3),  # fallback
])
def test_required_business_count(target_tier, req_count):
    assert get_required_business_count(target_tier) == req_count


def test_count_user_businesses_empty():
    assert count_user_businesses({}) == 0
    assert count_user_businesses({"inventory": {}}) == 0


def test_count_user_businesses_standard():
    user_data = {
        "inventory": {
            "семечки": 2,
            "газеты": 1,
            "лада": 3,
            "condom": 50,  # other, not counted
            "lockpick": 5, # other, not counted
        }
    }
    assert count_user_businesses(user_data) == 6


def test_count_user_businesses_prestige_items():
    user_data = {
        "inventory": {
            "prestige_mine": 2,
            "prestige_kopter": 1,
            "prestige_tower": 1,
            "dictor_legendary": 3, # other, not counted
        }
    }
    assert count_user_businesses(user_data) == 4


def test_count_user_businesses_invalid_quantities():
    user_data = {
        "inventory": {
            "семечки": -5,
            "мойка": 0,
            "ларек": "invalid",
            "казино": 2,
        }
    }
    assert count_user_businesses(user_data) == 2


# ============================================================
#  4. NET WORTH & PROGRESS BAR (15 Tests)
# ============================================================

def test_calculate_user_net_worth_basic():
    user_data = {
        "balance": 1_000_000,
        "bank_deposit": 5_000_000,
        "inventory": {
            "мойка": 1,  # 125,000
        },
        "biz_levels": {
            "мойка": 1,
        }
    }
    worth = calculate_user_net_worth(user_data)
    assert worth == 6_125_000


def test_calculate_user_net_worth_with_upgraded_business():
    # мойка: price 125,000. Upgrades to lvl 3: + 0.5 * 125k * 1 (lvl 2) + 0.5 * 125k * 2 (lvl 3)
    user_data = {
        "balance": 0,
        "bank_deposit": 0,
        "inventory": {"мойка": 1},
        "biz_levels": {"мойка": 3},
    }
    worth = calculate_user_net_worth(user_data)
    expected = 125_000 + int(125_000 * 0.5 * 1) + int(125_000 * 0.5 * 2)
    assert worth == expected


def test_calculate_user_net_worth_with_crypto_and_stocks():
    user_data = {
        "balance": 100_000,
        "bank_deposit": 0,
        "inventory": {},
        "crypto_portfolio": {"TON": 10},
        "stocks_portfolio": {"GAZP": 5},
    }
    worth = calculate_user_net_worth(user_data)
    assert worth >= 100_000


@pytest.mark.parametrize("current,target,pct_str", [
    (0, 100, "(0%)"),
    (50, 100, "(50%)"),
    (100, 100, "(100%)"),
    (150, 100, "(100%)"),
    (0, 0, "▰▰▰▰▰▰▰▰▰▰"),
])
def test_render_progress_bar(current, target, pct_str):
    bar = render_progress_bar(current, target)
    if target > 0:
        assert pct_str in bar
    else:
        assert bar == pct_str


# ============================================================
#  5. INVENTORY & BIZ LEVEL PRESERVATION (15 Tests)
# ============================================================

def test_preserve_inventory_wipe_mode():
    inv = {
        "семечки": 5,
        "мойка": 2,
        "prestige_mine": 1,
        "dictor_legendary": 1,
        "condom": 10,
    }
    # Regular wipe preserves only Dictors
    saved = preserve_protected_inventory(inv, preserve_prestige=False)
    assert "dictor_legendary" in saved
    assert "prestige_mine" not in saved
    assert "семечки" not in saved
    assert "мойка" not in saved


def test_preserve_inventory_prestige_mode():
    inv = {
        "семечки": 5,
        "мойка": 2,
        "prestige_mine": 1,
        "prestige_reactor": 2,
        "dictor_divine": 1,
        "condom": 10,
    }
    # Prestige ascension preserves Dictors + Prestige items
    saved = preserve_protected_inventory(inv, preserve_prestige=True)
    assert "dictor_divine" in saved
    assert "prestige_mine" in saved
    assert "prestige_reactor" in saved
    assert "семечки" not in saved
    assert "мойка" not in saved
    assert "condom" not in saved


def test_prestige_biz_levels_retained_properly():
    old_inv = {
        "семечки": 1,
        "мойка": 1,
        "prestige_mine": 1,
        "prestige_tower": 1,
    }
    old_biz_levels = {
        "семечки": 5,
        "мойка": 3,
        "prestige_mine": 4,
        "prestige_tower": 2,
    }

    new_inv = preserve_protected_inventory(old_inv, preserve_prestige=True)
    new_biz_levels = {k: v for k, v in old_biz_levels.items() if k in new_inv}

    assert "prestige_mine" in new_biz_levels
    assert new_biz_levels["prestige_mine"] == 4
    assert "prestige_tower" in new_biz_levels
    assert new_biz_levels["prestige_tower"] == 2
    assert "семечки" not in new_biz_levels
    assert "мойка" not in new_biz_levels


@pytest.mark.parametrize("item_id,req_tier,cat,action,price", [
    ("prestige_mine", 1, "prestige", "business", 5_000_000),
    ("prestige_kopter", 1, "prestige", "car", 2_500_000),
    ("prestige_factory", 2, "prestige", "business", 25_000_000),
    ("prestige_hypercar", 2, "prestige", "car", 15_000_000),
    ("prestige_tower", 3, "prestige", "business", 100_000_000),
    ("prestige_yacht", 3, "prestige", "car", 50_000_000),
    ("prestige_station", 4, "prestige", "business", 500_000_000),
    ("prestige_shuttle", 4, "prestige", "car", 250_000_000),
    ("prestige_reactor", 5, "prestige", "business", 2_500_000_000),
    ("prestige_dreadnought", 5, "prestige", "car", 1_200_000_000),
    ("prestige_monolith", 6, "prestige", "business", 10_000_000_000),
    ("prestige_ark", 6, "prestige", "car", 5_000_000_000),
])
def test_prestige_shop_catalog_definitions(item_id, req_tier, cat, action, price):
    from shop import ITEMS
    item = ITEMS[item_id]
    assert item["req_prestige"] == req_tier
    assert item["cat"] == cat
    assert item["action"] == action
    assert item["price"] == price


@pytest.mark.parametrize("tier_from,tier_to", [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),
    (4, 5),
    (5, 6),
])
def test_prestige_sequential_progression(tier_from, tier_to):
    assert tier_to == tier_from + 1
    assert PRESTIGE_TIERS[tier_to]["cost"] > (PRESTIGE_TIERS[tier_from]["cost"] if tier_from > 0 else 0)


@pytest.mark.parametrize("tier", [1, 2, 3, 4, 5, 6])
def test_prestige_tier_descriptions_present(tier):
    info = PRESTIGE_TIERS[tier]
    assert "desc" in info
    assert len(info["desc"]) > 5
    assert "badge" in info
    assert len(info["badge"]) > 0


@pytest.mark.parametrize("tier,biz_req", [
    (1, 3),
    (2, 5),
    (3, 7),
    (4, 9),
    (5, 12),
    (6, 15),
])
def test_prestige_tier_business_requirements_strict(tier, biz_req):
    assert get_required_business_count(tier) == biz_req


def test_preserve_inventory_empty_dict():
    assert preserve_protected_inventory({}) == {}
    assert preserve_protected_inventory(None) == {}
    assert preserve_protected_inventory("invalid") == {}

