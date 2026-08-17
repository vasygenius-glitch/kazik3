import pytest
import time
from chances import (
    get_game_chance_sync,
    _chances_cache,
    get_user_win_chance,
)
from prestige import PRESTIGE_TIERS, get_prestige_perks


# ============================================================
#  1. GAME CHANCE CACHE & SYNC GETTER (20 Tests)
# ============================================================

def test_game_chance_sync_default():
    _chances_cache.clear()
    assert get_game_chance_sync("roulette") == -1
    assert get_game_chance_sync("slots") == -1
    assert get_game_chance_sync("blackjack") == -1


@pytest.mark.parametrize("game,chance", [
    ("slots", 35),
    ("roulette", 40),
    ("blackjack", 45),
    ("poker", 50),
    ("cups", 33),
    ("craps", 42),
    ("baccarat", 48),
    ("crash", 30),
])
def test_game_chance_sync_custom(game, chance):
    _chances_cache[game] = chance
    assert get_game_chance_sync(game) == chance


# ============================================================
#  2. PRESTIGE LUCK BONUS IN WIN CHANCES (30 Tests)
# ============================================================

@pytest.mark.parametrize("tier,expected_luck", [
    (0, 0),
    (1, 5),
    (2, 10),
    (3, 15),
    (4, 20),
    (5, 25),
    (6, 35),
])
def test_prestige_luck_perk_tiers(tier, expected_luck):
    perks = get_prestige_perks({"prestige_level": tier})
    assert perks["luck_bonus"] == expected_luck


@pytest.mark.asyncio
async def test_get_user_win_chance_honest_random_no_prestige(monkeypatch):
    async def mock_get_game_chance(game):
        return -1
    async def mock_get_user_data(chat_id, user_id):
        return {"prestige_level": 0, "pet": {}}
    monkeypatch.setattr("chances.get_game_chance", mock_get_game_chance)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)
    
    chance = await get_user_win_chance(123, 456, "roulette", -1)
    assert chance == -1


@pytest.mark.asyncio
@pytest.mark.parametrize("tier,expected_chance", [
    (1, 50),  # 45 base + 5 luck
    (2, 55),  # 45 base + 10 luck
    (3, 60),  # 45 base + 15 luck
    (4, 65),  # 45 base + 20 luck
    (5, 70),  # 45 base + 25 luck
    (6, 80),  # 45 base + 35 luck
])
async def test_get_user_win_chance_honest_random_with_prestige(monkeypatch, tier, expected_chance):
    async def mock_get_game_chance(game):
        return -1
    async def mock_get_user_data(chat_id, user_id):
        return {"prestige_level": tier, "pet": {}}
    monkeypatch.setattr("chances.get_game_chance", mock_get_game_chance)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)

    chance = await get_user_win_chance(123, 456, "roulette", -1)
    assert chance == expected_chance


@pytest.mark.asyncio
@pytest.mark.parametrize("tier,expected_chance", [
    (0, 45),  # 35 base + 10 unicorn
    (1, 50),  # 35 base + 10 unicorn + 5 luck
    (3, 60),  # 35 base + 10 unicorn + 15 luck
    (6, 80),  # 35 base + 10 unicorn + 35 luck
])
async def test_get_user_win_chance_fixed_base_with_unicorn_and_prestige(monkeypatch, tier, expected_chance):
    async def mock_get_game_chance(game):
        return 35
    async def mock_get_user_data(chat_id, user_id):
        return {"prestige_level": tier, "pet": {"id": "unicorn"}}
    async def mock_get_active_diseases(chat_id, user_id, data=None):
        return []
    monkeypatch.setattr("chances.get_game_chance", mock_get_game_chance)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)
    monkeypatch.setattr("diseases.get_active_diseases", mock_get_active_diseases)

    chance = await get_user_win_chance(123, 456, "slots", 35)
    assert chance == expected_chance


@pytest.mark.asyncio
async def test_get_user_win_chance_hpv_blocks_unicorn_but_keeps_prestige(monkeypatch):
    async def mock_get_game_chance(game):
        return 35
    async def mock_get_user_data(chat_id, user_id):
        return {"prestige_level": 4, "pet": {"id": "unicorn"}}  # Prestige 4 (+20 luck)
    async def mock_get_active_diseases(chat_id, user_id, data=None):
        return ["hpv"]  # HPV blocks unicorn (+10)
    monkeypatch.setattr("chances.get_game_chance", mock_get_game_chance)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)
    monkeypatch.setattr("diseases.get_active_diseases", mock_get_active_diseases)

    chance = await get_user_win_chance(123, 456, "slots", 35)
    # 35 base + 0 unicorn (blocked by HPV) + 20 prestige = 55
    assert chance == 55


# ============================================================
#  3. CAP & BOUNDARY VALIDATIONS (20 Tests)
# ============================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("base,luck,expected", [
    (90, 35, 100),  # Capped at 100
    (80, 25, 100),  # Capped at 100
    (10, 5, 15),
    (0, 0, 0),
])
async def test_get_user_win_chance_capping(monkeypatch, base, luck, expected):
    async def mock_get_game_chance(game):
        return base
    async def mock_get_user_data(chat_id, user_id):
        return {"prestige_level": 6 if luck == 35 else (5 if luck == 25 else (1 if luck == 5 else 0)), "pet": {}}
    monkeypatch.setattr("chances.get_game_chance", mock_get_game_chance)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)

    chance = await get_user_win_chance(123, 456, "test_game", base)
    assert chance == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("game", [
    "slots",
    "roulette",
    "blackjack",
    "poker",
    "cups",
    "craps",
    "baccarat",
])
@pytest.mark.parametrize("prestige_tier,luck", [
    (0, 0),
    (1, 5),
    (2, 10),
    (3, 15),
    (4, 20),
    (5, 25),
    (6, 35),
])
async def test_all_casino_games_prestige_luck_integration(monkeypatch, game, prestige_tier, luck):
    base_chance = 35
    async def mock_get_game_chance(g):
        return base_chance
    async def mock_get_user_data(chat_id, user_id):
        return {"prestige_level": prestige_tier, "pet": {}}
    monkeypatch.setattr("chances.get_game_chance", mock_get_game_chance)
    monkeypatch.setattr("user_manager.get_user_data", mock_get_user_data)

    chance = await get_user_win_chance(123, 456, game, base_chance)
    assert chance == base_chance + luck

