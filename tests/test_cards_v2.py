import pytest
import time
from unittest.mock import AsyncMock, patch

import cards_system
from cards_system import (
    CARDS,
    CARDS_BY_RARITY,
    CASES,
    CARD_SETS,
    CRAFT_COSTS,
    PITY_THRESHOLD,
    RARITIES,
    TOTAL_CARDS,
    cooldowns,
    roll_card_from_case,
    _get_filtered_keys,
    _pick_best_or_fav_card,
    get_rarity_shards,
    get_rarity_emoji,
    get_rarity_name,
)


def test_cards_configuration_and_rarities():
    assert len(CARDS) == 200
    assert len(RARITIES) == 7
    expected_rarities = {"COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC", "SECRET"}
    assert set(RARITIES.keys()) == expected_rarities

    for card_id, card in CARDS.items():
        assert card["rarity"] in RARITIES
        assert card["bonus_multiplier"] >= 0
        assert card["bonus_flat"] >= 0
        assert card.get("power", 0) > 0


def test_cases_and_chances():
    assert "free_case" in CASES
    assert "common_case" in CASES
    assert "epic_case" in CASES
    assert "royal_case" in CASES
    assert "secret_case" in CASES

    for case_id, case in CASES.items():
        assert "chances" in case
        total_chances = sum(case["chances"].values())
        # Total chances sum to approximately 100%
        assert 95 <= total_chances <= 101


def test_cooldown_manager_basic():
    cd = cards_system.CooldownManager()
    chat_id = -100123
    user_id = 99999999

    ok, left = cd.check(chat_id, user_id, "case_open")
    assert ok is True
    assert left == 0.0

    cd.trigger(chat_id, user_id, "case_open", duration=2.0)
    ok2, left2 = cd.check(chat_id, user_id, "case_open")
    assert ok2 is False
    assert 0.0 < left2 <= 2.0


def test_cooldown_manager_creator_bypass():
    cd = cards_system.CooldownManager()
    from config import CREATOR_ID
    chat_id = -100123
    
    cd.trigger(chat_id, CREATOR_ID, "case_open", duration=10.0)
    ok, left = cd.check(chat_id, CREATOR_ID, "case_open")
    assert ok is True
    assert left == 0.0


def test_pity_guarantee():
    case = CASES["epic_case"]
    # With pity_count = PITY_THRESHOLD - 1, next roll triggers pity
    card_id, triggered = roll_card_from_case(case, user_id=11111, pity_count=PITY_THRESHOLD - 1)
    assert card_id is not None
    assert triggered is True
    assert CARDS[card_id]["rarity"] in ("LEGENDARY", "MYTHIC", "SECRET")

    # Common case has no pity
    common_case = CASES["common_case"]
    card_id_c, triggered_c = roll_card_from_case(common_case, user_id=11111, pity_count=PITY_THRESHOLD - 1)
    assert triggered_c is False


def test_card_filters():
    fake_cards = {"meme_1": 1, "meme_2": 2}
    all_keys = _get_filtered_keys(fake_cards, "all")
    assert len(all_keys) == 200

    owned_keys = _get_filtered_keys(fake_cards, "owned")
    assert owned_keys == ["meme_1", "meme_2"]

    missing_keys = _get_filtered_keys(fake_cards, "missing")
    assert len(missing_keys) == 198
    assert "meme_1" not in missing_keys

    top_keys = _get_filtered_keys(fake_cards, "top")
    assert len(top_keys) > 0
    for k in top_keys:
        assert CARDS[k]["rarity"] in {"RARE", "EPIC", "LEGENDARY", "MYTHIC", "SECRET"}


def test_sets_configuration():
    assert len(CARD_SETS) == 5
    for set_id, s in CARD_SETS.items():
        assert "name" in s
        assert "cards" in s
        assert len(s["cards"]) >= 4
        for cid in s["cards"]:
            assert cid in CARDS


def test_best_and_favorite_card_selection():
    data_no_cards = {"meme_cards": {}}
    assert _pick_best_or_fav_card(data_no_cards) is None

    data_cards = {
        "meme_cards": {"meme_4": 1, "meme_1": 1},  # meme_4 is Common, meme_1 is Legendary
    }
    best = _pick_best_or_fav_card(data_cards)
    assert best == "meme_1"

    data_fav = {
        "meme_cards": {"meme_4": 1, "meme_1": 1},
        "favorite_card_id": "meme_4",
    }
    fav = _pick_best_or_fav_card(data_fav)
    assert fav == "meme_4"


@pytest.mark.asyncio
async def test_process_drop_rewards_shards_and_pity():
    with patch("cards_system.update_user_field") as mock_update, \
         patch("cards_system.invalidate_user_cache") as mock_inv:

        # User owns card, rarity = RARE -> 30 shards
        pre_data = {"card_shards": 50, "card_pity": 3}
        mock_update.return_value = None

        rare_card = CARDS_BY_RARITY["RARE"][0]
        shards, pity = await cards_system._process_drop_rewards(
            chat_id=-1001,
            user_id=123,
            card_id=rare_card,
            was_already_owned=True,
            triggered_pity=False,
            pre_data=pre_data,
        )

        assert shards == 30
        assert pity == 4
        mock_update.assert_any_call(-1001, 123, "card_pity", 4)
        mock_update.assert_any_call(-1001, 123, "card_shards", 80)


def test_card_tempering_and_power():
    data_lvl1 = {"card_levels": {}}
    assert cards_system.get_card_level(data_lvl1, "meme_1") == 1

    data_lvl3 = {"card_levels": {"meme_1": 3}}
    assert cards_system.get_card_level(data_lvl3, "meme_1") == 3

    base_power = CARDS["meme_1"]["power"]
    lvl1_power = cards_system.get_effective_power("meme_1", 1)
    lvl3_power = cards_system.get_effective_power("meme_1", 3)
    assert lvl1_power == base_power
    assert lvl3_power > lvl1_power

    # Level 5 is max
    assert cards_system.MAX_CARD_LEVEL == 5
    cost = cards_system.get_temper_cost("LEGENDARY", 2)
    assert cost > 0


def test_set_rewards_configuration():
    for set_id, s in CARD_SETS.items():
        assert "reward_shards" in s
        assert s["reward_shards"] > 0

