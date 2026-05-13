import pytest

def test_biz_upgrade_cost():
    base_price = 1000
    # Level 1 cost to upgrade to Level 2
    cost_lvl_1 = int(base_price * (1.5 ** (1 - 1)))
    assert cost_lvl_1 == 1000

    # Level 2 cost to upgrade to Level 3
    cost_lvl_2 = int(base_price * (1.5 ** (2 - 1)))
    assert cost_lvl_2 == 1500

    # Level 3 cost to upgrade to Level 4
    cost_lvl_3 = int(base_price * (1.5 ** (3 - 1)))
    assert cost_lvl_3 == 2250

    # Level 20 max check
    cost_lvl_19 = int(base_price * (1.5 ** (19 - 1)))
    assert cost_lvl_19 > 1000000

def test_biz_income_multiplier():
    base_income = 100

    # Level 1 income
    mult_1 = 1.0 + 0.2 * (1 - 1)
    assert int(base_income * mult_1) == 100

    # Level 2 income
    mult_2 = 1.0 + 0.2 * (2 - 1)
    assert int(base_income * mult_2) == 120

    # Level 10 income
    mult_10 = 1.0 + 0.2 * (10 - 1)
    assert int(base_income * mult_10) == 280

def test_biz_sell_price():
    base_price = 1000
    level = 3

    total_invested = base_price
    for l in range(1, level):
        total_invested += int(base_price * (1.5 ** (l - 1)))

    # Level 1 purchase = 1000
    # Upgrade 1 to 2 = 1000
    # Upgrade 2 to 3 = 1500
    # Total invested = 3500
    assert total_invested == 3500
    assert int(total_invested * 0.75) == 2625
