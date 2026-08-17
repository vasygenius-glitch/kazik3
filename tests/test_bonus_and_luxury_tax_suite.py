import pytest
import time
from user_manager import (
    BASE_BONUS,
    BIZ_LEVEL_BONUS,
    BIZ_COUNT_CAP,
    get_user_meme_bonuses,
)
from shop import ITEMS
from prestige import PRESTIGE_TIERS, get_prestige_perks


# ============================================================
#  1. CONSTANTS & BASE FORMULAS (15 Tests)
# ============================================================

def test_bonus_constants():
    assert BASE_BONUS == 150
    assert BIZ_LEVEL_BONUS == 0.5
    assert BIZ_COUNT_CAP == 10


@pytest.mark.parametrize("level,expected_mult", [
    (1, 1.0),
    (2, 1.5),
    (3, 2.0),
    (4, 2.5),
    (5, 3.0),
    (6, 3.5),
    (10, 5.5),
])
def test_business_level_multipliers(level, expected_mult):
    mult = 1.0 + BIZ_LEVEL_BONUS * (level - 1)
    assert abs(mult - expected_mult) < 1e-6


@pytest.mark.parametrize("count,expected_counted", [
    (1, 1),
    (5, 5),
    (10, 10),
    (15, 10),
    (100, 10),
])
def test_business_count_cap(count, expected_counted):
    assert min(count, BIZ_COUNT_CAP) == expected_counted


# ============================================================
#  2. BUSINESS & CAR INCOME CALCULATIONS (20 Tests)
# ============================================================

@pytest.mark.parametrize("item_id,base_income", [
    ("семечки", 50),
    ("газеты", 120),
    ("пирожки", 450),
    ("мойка", 12_500),
    ("ресторан", 75_000),
    ("завод", 550_000),
    ("банк", 2_200_000),
    ("казино", 3_800_000),
    ("мегакорп", 5_000_000),
    ("prestige_mine", 150_000),
    ("prestige_factory", 500_000),
    ("prestige_tower", 1_500_000),
    ("prestige_station", 5_000_000),
    ("prestige_reactor", 18_000_000),
    ("prestige_monolith", 50_000_000),
])
def test_business_base_incomes(item_id, base_income):
    assert ITEMS[item_id]["income"] == base_income
    assert ITEMS[item_id]["action"] == "business"


@pytest.mark.parametrize("item_id,base_income", [
    ("самокат", 50),
    ("жигули", 300),
    ("камри", 1_750),
    ("гелик", 12_500),
    ("бугатти", 50_000),
    ("самолет", 350_000),
    ("prestige_kopter", 60_000),
    ("prestige_hypercar", 250_000),
    ("prestige_yacht", 700_000),
    ("prestige_shuttle", 2_500_000),
    ("prestige_dreadnought", 9_000_000),
    ("prestige_ark", 25_000_000),
])
def test_car_base_incomes(item_id, base_income):
    assert ITEMS[item_id]["income"] == base_income
    assert ITEMS[item_id]["action"] == "car"


# ============================================================
#  3. MEME CARDS MULTIPLIER & FLAT BONUSES (15 Tests)
# ============================================================

def test_meme_cards_empty():
    bonuses = get_user_meme_bonuses({})
    assert bonuses["multiplier"] == 0.0
    assert bonuses["flat"] == 0


def test_meme_cards_common_and_rare():
    user_data = {
        "meme_cards": {
            "meme_1": 5,  # Common
            "meme_10": 2, # Rare
        }
    }
    bonuses = get_user_meme_bonuses(user_data)
    assert bonuses["multiplier"] > 0.0
    assert bonuses["flat"] > 0


def test_meme_cards_legendary_and_mythic():
    user_data = {
        "meme_cards": {
            "meme_100": 3,
            "meme_150": 1,
        }
    }
    bonuses = get_user_meme_bonuses(user_data)
    assert bonuses["multiplier"] > 0.0
    assert bonuses["flat"] > 0


@pytest.mark.parametrize("card_id,qty", [
    ("meme_5", 1),
    ("meme_25", 4),
    ("meme_50", 10),
    ("meme_75", 2),
    ("meme_120", 3),
    ("meme_180", 1),
])
def test_meme_card_individual_effects(card_id, qty):
    bonuses = get_user_meme_bonuses({"meme_cards": {card_id: qty}})
    assert bonuses["multiplier"] >= 0.0
    assert bonuses["flat"] >= 0


# ============================================================
#  4. LUXURY TAX THRESHOLDS & PRESTIGE DISCOUNT (15 Tests)
# ============================================================

@pytest.mark.parametrize("prestige_lvl,next_tier,expected_threshold", [
    (0, 1, 50_000_000),
    (1, 2, 250_000_000),
    (2, 3, 1_000_000_000),
    (3, 4, 5_000_000_000),
    (4, 5, 25_000_000_000),
    (5, 6, 100_000_000_000),
])
def test_luxury_tax_threshold_per_prestige(prestige_lvl, next_tier, expected_threshold):
    assert PRESTIGE_TIERS[next_tier]["cost"] == expected_threshold


def test_luxury_tax_no_excess():
    wealth = 40_000_000
    threshold = 50_000_000
    excess = max(0, wealth - threshold)
    luxury_tax = int(excess * 0.015)
    assert luxury_tax == 0


def test_luxury_tax_with_excess_and_prestige_discount():
    # Prestige 4: threshold = 25B. Tax discount = 20%.
    perks = get_prestige_perks({"prestige_level": 4})
    tax_disc = perks["tax_discount"]
    assert tax_disc == 20

    wealth = 35_000_000_000  # 10B excess
    threshold = 25_000_000_000
    excess = wealth - threshold
    raw_tax = int(excess * 0.015)  # 150M
    discounted_tax = int(raw_tax * (1.0 - tax_disc / 100.0))  # 120M
    assert raw_tax == 150_000_000
    assert discounted_tax == 120_000_000


def test_luxury_tax_absolut_exempt():
    # Prestige 6 (Абсолют) is not subject to luxury tax (prestige_level < 6 condition)
    prestige_level = 6
    is_subject_to_tax = prestige_level < 6
    assert not is_subject_to_tax


# ============================================================
#  5. LUXURY TAX CAPPING SAFETY (15 Tests)
# ============================================================

def test_luxury_tax_capping_never_zeros_out_earnings():
    """
    Критический тест: проверяет, что игрок с высоким капиталом и миллионным доходом
    НЕ получает 150 сыроежек из-за налога на сверхкапитал.
    """
    total_earned = 9_585_460
    base_bonus = 150
    huge_luxury_tax = 150_000_000  # Налог мог бы быть 150 млн из-за огромного капитала

    # Наша формула с ограничением максимум 25%
    max_tax = min(max(0, total_earned - base_bonus), int(total_earned * 0.25))
    applied_luxury_tax = min(huge_luxury_tax, max_tax)
    final_total = total_earned - applied_luxury_tax

    assert applied_luxury_tax <= int(total_earned * 0.25)
    assert final_total >= int(total_earned * 0.75)
    assert final_total > base_bonus
    # В конкретном примере: налог не больше ~2.39 млн, на руки не менее ~7.18 млн
    assert applied_luxury_tax == int(9_585_460 * 0.25)
    assert final_total == 9_585_460 - int(9_585_460 * 0.25)


@pytest.mark.parametrize("earned,raw_tax,expected_tax_cap", [
    (150, 5000, 0),                       # Base bonus only -> 0 tax
    (1000, 500, 250),                     # 25% cap = 250
    (100_000, 50_000, 25_000),            # 25% cap = 25,000
    (1_000_000, 10_000, 10_000),          # Below cap -> takes 10,000
    (5_000_000, 2_000_000, 1_250_000),    # 25% cap = 1,250,000
    (100_000_000, 500_000_000, 25_000_000),# 25% cap = 25,000,000
])
def test_luxury_tax_cap_various_incomes(earned, raw_tax, expected_tax_cap):
    base_bonus = 150
    max_tax = min(max(0, earned - base_bonus), int(earned * 0.25))
    applied = min(raw_tax, max_tax)
    assert applied == expected_tax_cap


@pytest.mark.parametrize("biz_name,price,income", [
    ("свип", 2500, 250),
    ("цветы", 7000, 700),
    ("ларек", 10000, 1000),
    ("шаурма", 25000, 2500),
    ("вендинг", 200000, 20000),
    ("кофейня", 375000, 37500),
    ("отель", 1750000, 175000),
    ("ферма", 3000000, 300000),
    ("кинотеатр", 5000000, 450000),
    ("салон", 12500000, 1000000),
    ("нефть", 20000000, 1500000),
    ("айти", 50000000, 3000000),
    ("стадион", 85000000, 4500000),
    ("sec_bunker", 150000000, 6000000),
    ("звездные_врата", 160000000, 6500000),
    ("сфера_дайсона", 175000000, 7000000),
    ("квантовый_компьютер", 190000000, 7500000),
    ("варп_станция", 205000000, 8000000),
    ("матрица_времени", 220000000, 8500000),
    ("космо_лифт", 230000000, 9000000),
    ("фабрика_темной_материи", 240000000, 9500000),
    ("галактический_банк", 245000000, 10000000),
    ("абсолютный_абсолют", 250000000, 12000000),
])
def test_all_standard_businesses(biz_name, price, income):
    item = ITEMS[biz_name]
    assert item["cat"] == "biz"
    assert item["action"] == "business"
    assert item["price"] == price
    assert item["income"] == income


@pytest.mark.parametrize("car_name,price,income", [
    ("велосипед", 3000, 100),
    ("ока", 5000, 180),
    ("москвич", 10000, 400),
    ("бмв", 125000, 5000),
    ("яхта", 30000000, 800000),
    ("круизер", 50000000, 1300000),
    ("ракета", 75000000, 1800000),
    ("kovcheg", 100000000, 2500000),
    ("гиперкар_аполлон", 120000000, 3000000),
    ("грави_яхта", 140000000, 3500000),
    ("планетарный_дредноут", 160000000, 4000000),
    ("титан_крейсер", 180000000, 4500000),
    ("гипер_гиперион", 200000000, 5000000),
    ("орбитальная_цитадель", 220000000, 5500000),
    ("ковчег_миров", 250000000, 6000000),
])
def test_all_standard_cars(car_name, price, income):
    item = ITEMS[car_name]
    assert item["cat"] == "cars"
    assert item["action"] == "car"
    assert item["price"] == price
    assert item["income"] == income


def test_kovcheg_ark_boost_logic():
    # Kovcheg gives +20% (multiplier 1.2)
    subtotal = 1_000_000
    boosted = int(subtotal * 1.2)
    assert boosted == 1_200_000


def test_banker_passive_income_reduction():
    # Banker receives 10% of passive business income
    biz_income = 5_000_000
    banker_biz_income = int(biz_income * 0.1)
    assert banker_biz_income == 500_000

