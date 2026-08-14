import pytest
from shop import ITEMS, CATEGORY_NAMES, SELL_RATIO

def test_shop_items_integrity():
    """Проверка структуры и цен всех товаров в каталоге магазина."""
    assert len(ITEMS) >= 40
    for item_id, item in ITEMS.items():
        assert "name" in item
        assert "price" in item
        assert "cat" in item
        assert "action" in item
        assert item["price"] >= 0

        # Бизнесы и машины должны иметь базовый доход
        if item["action"] in ("business", "car"):
            assert "income" in item
            assert item["income"] >= 0

def test_prestige_category_and_items():
    """Проверка наличия категории 'prestige' и 12 товаров Престижа."""
    assert "prestige" in CATEGORY_NAMES
    prestige_items = [k for k, v in ITEMS.items() if v.get("cat") == "prestige"]
    assert len(prestige_items) == 12

    # У каждого предмета престижа должен быть указан req_prestige (1..6)
    for p_id in prestige_items:
        p_info = ITEMS[p_id]
        req = p_info.get("req_prestige")
        assert req is not None
        assert 1 <= req <= 6

def test_sell_ratio():
    """Проверка коэффициента продажи имущества."""
    assert SELL_RATIO == 0.75
    # Продажа товара за 100k должна приносить 75k
    price = 100_000
    payout = int(price * SELL_RATIO)
    assert payout == 75_000
