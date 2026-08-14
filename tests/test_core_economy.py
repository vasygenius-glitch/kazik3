import pytest
import time
from user_manager import (
    get_user_data,
    update_user_balance,
    get_user_meme_bonuses,
    is_dictor_item,
    preserve_protected_inventory,
)
from economy_utils import calculate_progressive_tax, calculate_biz_markup
from prestige import get_prestige_perks

def test_progressive_tax_calculation():
    """Проверка ступенчатого прогрессивного налога на капитал."""
    # Бедный игрок: базовая ставка
    tax_poor = calculate_progressive_tax(balance=1000, base_tax=13.0)
    assert tax_poor == 13.0

    # Навык переговоров снижает налог
    tax_discounted = calculate_progressive_tax(balance=1000, base_tax=13.0, negotiation_skill=2)
    assert tax_discounted < 13.0

    # Сверхбогатый игрок: повышенная ставка
    tax_rich = calculate_progressive_tax(balance=100_000_000, base_tax=13.0)
    assert tax_rich > 13.0

def test_biz_markup():
    """Проверка наценки на покупку бизнесов при сверхкапитале."""
    assert calculate_biz_markup(balance=500_000) == 0
    assert calculate_biz_markup(balance=150_000_000) == 20

def test_prestige_bonus_application():
    """Проверка корректности применения множителя дохода и скидок на налог."""
    user_p3 = {"prestige_level": 3}
    perks = get_prestige_perks(user_p3)
    assert perks["income_multiplier"] == 1.50
    assert perks["tax_discount"] == 15

    # Доход 100k с престижем 3 должен стать 150k
    base_income = 100_000
    boosted_income = int(base_income * perks["income_multiplier"])
    assert boosted_income == 150_000
