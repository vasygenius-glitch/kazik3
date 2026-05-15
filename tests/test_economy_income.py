import pytest
from shop import ITEMS
from economy_utils import calculate_biz_markup, calculate_progressive_tax

def test_items_nerf_balance():
    # Verify values were correctly nerfed by checking a few known instances
    # Shawarma was 100,000 price and 10,000 income, now it should be 25,000 and 2,500
    shawarma = ITEMS['шаурма']
    assert shawarma['price'] == 25000
    assert shawarma['income'] == 2500

    # Car check
    lada = ITEMS['лада']
    assert lada['price'] == 12500
    assert lada['income'] == 500

def test_biz_markup():
    assert calculate_biz_markup(0) == 0
    assert calculate_biz_markup(50_000_000) == 0
    assert calculate_biz_markup(150_000_000) == 20
    assert calculate_biz_markup(600_000_000) == 50

def test_progressive_tax_threshold_nerf():
    # Was +5% per 1,000,000. Now +5% per 250,000.
    # So 250,000 should give 10 (base) + 5 = 15
    tax = calculate_progressive_tax(balance=250_000, base_tax=10, negotiation_skill=0)
    assert tax == 15

    tax = calculate_progressive_tax(balance=500_000, base_tax=10, negotiation_skill=0)
    assert tax == 20 # 10 + 10 = 20

    # Check cap
    tax = calculate_progressive_tax(balance=50_000_000, base_tax=10, negotiation_skill=0)
    assert tax == 20 # Max is 20
