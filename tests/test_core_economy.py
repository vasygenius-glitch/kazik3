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


@pytest.mark.asyncio
async def test_game_win_chance_fair_random():
    """Проверка, что честный рандом (-1) в покере и рулетке не превращается в 0% проигрыш."""
    from chances import get_user_win_chance
    from user_manager import set_in_cache

    chat_id = -100555666
    user_id = 888999

    # Обычный игрок без питомцев
    set_in_cache(chat_id, user_id, {"balance": 1000})
    chance_poker = await get_user_win_chance(chat_id, user_id, "poker", -1)
    assert chance_poker == -1, f"Ожидался -1 (честный рандом), получено {chance_poker}"

    chance_roulette = await get_user_win_chance(chat_id, user_id, "roulette", -1)
    assert chance_roulette == -1, f"Ожидался -1 (честный рандом), получено {chance_roulette}"

    # Игра с базовым шансом 35%
    chance_slots = await get_user_win_chance(chat_id, user_id, "slots", 35)
    assert chance_slots == 35

    # Игрок с питомцем единорогом (+10%)
    set_in_cache(chat_id, user_id, {"balance": 1000, "pet": {"id": "unicorn"}})
    chance_unicorn_poker = await get_user_win_chance(chat_id, user_id, "poker", -1)
    assert chance_unicorn_poker == 55, f"Ожидался 55% с единорогом, получено {chance_unicorn_poker}"

    chance_unicorn_slots = await get_user_win_chance(chat_id, user_id, "slots", 35)
    assert chance_unicorn_slots == 45, f"Ожидался 45% с единорогом, получено {chance_unicorn_slots}"

