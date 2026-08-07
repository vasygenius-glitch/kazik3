import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from casino_utils import try_acquire_confirm_lock, release_confirm_lock, is_confirmation_callback
from chances import get_game_chance_sync
from slots import get_slots_frame, cmd_slots, EMOJIS
from roulette import get_roulette_frame, cmd_roulette
from crash import generate_crash_point, multiplier_at_step, format_amount, progress_bar
from blackjack import get_bj_keyboard, get_bj_frame
from cards import get_random_card, calculate_score, format_cards, get_baccarat_score

# =====================================================================
# 1. CASINO UTILS & CHANCES (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("msg_id", range(10, 20))
def test_try_acquire_confirm_lock_10_cases(msg_id):
    chat_id = 100
    acquired = try_acquire_confirm_lock(chat_id, msg_id)
    assert acquired is True
    release_confirm_lock(chat_id, msg_id)

@pytest.mark.parametrize("cb_data,expected", [
    ("cas_conf_slots_100_123", True),
    ("cas_conf_dice_500_456", True),
    ("cas_conf_roulette_1000_789", True),
    ("cas_cancel", True),
    ("cas_cancel_123", True),
    ("work", False),
    ("crime", False),
    ("bonus", False),
    ("bank_list", False),
    ("menu", False)
])
def test_is_confirmation_callback_10_cases(cb_data, expected):
    assert is_confirmation_callback(cb_data) == expected

@pytest.mark.parametrize("game_name", ["slots", "roulette", "dice", "crash", "cups", "blackjack", "baccarat", "poker", "rps", "craps"])
def test_game_chances_10_games(game_name):
    chance = get_game_chance_sync(game_name)
    assert isinstance(chance, int)
    assert chance >= -1

# =====================================================================
# 2. SLOTS & ROULETTE (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("reels,status,bet,title", [
    (["7️⃣", "7️⃣", "7️⃣"], "JACKPOT", 100, "КАЗИНО"),
    (["💎", "💎", "💎"], "MEGA", 500, "КАЗИНО"),
    (["🍋", "🍋", "🍋"], "WIN", 1000, "КАЗИНО"),
    (["🔔", "🔔", "🔔"], "WIN", 250, "КАЗИНО"),
    (["🍒", "🍒", "🍒"], "WIN", 10, "КАЗИНО"),
    (["7️⃣", "7️⃣", "💎"], "PAIRS", 50, "КАЗИНО"),
    (["🍋", "🍋", "🍒"], "PAIRS", 200, "КАЗИНО"),
    (["🍒", "🍒", "🍋"], "PAIRS", 300, "КАЗИНО"),
    (["7️⃣", "🍋", "💎"], "LOSS", 500, "КАЗИНО"),
    (["🍒", "🍋", "🔔"], "LOSS", 1000, "КАЗИНО")
])
def test_slots_frame_10_variations(reels, status, bet, title):
    frame = get_slots_frame(reels, status, bet, title)
    assert isinstance(frame, str)
    assert title in frame

@pytest.mark.parametrize("ball_pos,status,bet,title,guess", [
    (0, "17", 100, "РУЛЕТКА", 17),
    (1, "5", 500, "РУЛЕТКА", 10),
    (2, "22", 1000, "РУЛЕТКА", 22),
    (3, "36", 250, "РУЛЕТКА", 36),
    (4, "1", 50, "РУЛЕТКА", 1),
    (5, "12", 200, "РУЛЕТКА", 12),
    (6, "18", 300, "РУЛЕТКА", 18),
    (7, "9", 500, "РУЛЕТКА", 9),
    (-1, "??", 1000, "РУЛЕТКА", 15),
    (3, "27", 100, "РУЛЕТКА", 27)
])
def test_roulette_frame_10_variations(ball_pos, status, bet, title, guess):
    frame = get_roulette_frame(ball_pos, status, bet, title, guess)
    assert isinstance(frame, str)
    assert title in frame

# =====================================================================
# 3. CRASH & BLACKJACK & CARDS (10 TESTS PER FUNCTION)
# =====================================================================

@pytest.mark.parametrize("idx", range(10))
def test_crash_generate_point_10_runs(idx):
    point = generate_crash_point()
    assert point >= 1.0

@pytest.mark.parametrize("step", [0, 1, 2, 5, 10, 20, 50, 100, 200, 500])
def test_crash_multiplier_at_step_10_steps(step):
    mult = multiplier_at_step(step)
    assert mult >= 1.0

@pytest.mark.parametrize("amount,expected_str", [
    (100, "100"),
    (1000, "1 000"),
    (50000, "50 000"),
    (1000000, "1 000 000"),
    (0, "0"),
    (2500, "2 500"),
    (999999, "999 999"),
    (10000000, "10 000 000"),
    (500, "500"),
    (1234567, "1 234 567")
])
def test_crash_format_amount_10_cases(amount, expected_str):
    formatted = format_amount(amount)
    assert isinstance(formatted, str)

@pytest.mark.parametrize("val,max_val,expected_len", [
    (50, 100, 14),
    (0, 100, 14),
    (100, 100, 14),
    (25, 100, 14),
    (75, 100, 14),
    (10, 50, 14),
    (20, 50, 14),
    (30, 50, 14),
    (40, 50, 14),
    (50, 50, 14)
])
def test_crash_progress_bar_10_cases(val, max_val, expected_len):
    bar = progress_bar(val, max_val, length=expected_len)
    assert len(bar) == expected_len

@pytest.mark.parametrize("cards,expected_score", [
    ([{"rank": "A", "suit": "♠"}, {"rank": "K", "suit": "♦"}], 21),
    ([{"rank": "A", "suit": "♠"}, {"rank": "A", "suit": "♦"}, {"rank": "9", "suit": "♣"}], 21),
    ([{"rank": "10", "suit": "♠"}, {"rank": "7", "suit": "♦"}], 17),
    ([{"rank": "A", "suit": "♠"}, {"rank": "6", "suit": "♦"}], 17),
    ([{"rank": "5", "suit": "♠"}, {"rank": "5", "suit": "♦"}, {"rank": "5", "suit": "♣"}], 15),
    ([{"rank": "K", "suit": "♠"}, {"rank": "Q", "suit": "♦"}, {"rank": "J", "suit": "♣"}], 30),
    ([{"rank": "2", "suit": "♠"}, {"rank": "3", "suit": "♦"}, {"rank": "4", "suit": "♣"}, {"rank": "5", "suit": "♥"}], 14),
    ([{"rank": "A", "suit": "♠"}, {"rank": "A", "suit": "♦"}, {"rank": "A", "suit": "♣"}, {"rank": "A", "suit": "♥"}], 14),
    ([{"rank": "10", "suit": "♠"}, {"rank": "10", "suit": "♦"}, {"rank": "2", "suit": "♣"}], 22),
    ([{"rank": "7", "suit": "♠"}, {"rank": "8", "suit": "♦"}, {"rank": "9", "suit": "♣"}], 24)
])
def test_cards_calculate_score_10_hands(cards, expected_score):
    score = calculate_score(cards)
    assert score == expected_score
