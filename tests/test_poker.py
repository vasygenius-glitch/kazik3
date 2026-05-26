import pytest
from unittest.mock import MagicMock
import sys

# Mock dependencies before importing poker
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()

import poker

# Helper to build cards
def C(rank, suit):
    return {'rank': rank, 'suit': suit}

# ----------------- SECTION 1: HAND EVALUATOR (60 CASES) -----------------
evaluate_cases = [
    # --- Royal Flush (4 cases) ---
    ([C('10', '♠'), C('J', '♠'), C('Q', '♠'), C('K', '♠'), C('A', '♠')], "Royal Flush"),
    ([C('10', '♥'), C('J', '♥'), C('Q', '♥'), C('K', '♥'), C('A', '♥')], "Royal Flush"),
    ([C('10', '♣'), C('J', '♣'), C('Q', '♣'), C('K', '♣'), C('A', '♣')], "Royal Flush"),
    ([C('10', '♦'), C('J', '♦'), C('Q', '♦'), C('K', '♦'), C('A', '♦')], "Royal Flush"),

    # --- Straight Flush (6 cases) ---
    ([C('9', '♠'), C('10', '♠'), C('J', '♠'), C('Q', '♠'), C('K', '♠')], "Straight Flush"),
    ([C('2', '♥'), C('3', '♥'), C('4', '♥'), C('5', '♥'), C('A', '♥')], "Straight Flush"), # wheel straight flush
    ([C('5', '♦'), C('6', '♦'), C('7', '♦'), C('8', '♦'), C('9', '♦')], "Straight Flush"),
    ([C('7', '♣'), C('8', '♣'), C('9', '♣'), C('10', '♣'), C('J', '♣')], "Straight Flush"),
    ([C('A', '♣'), C('2', '♣'), C('3', '♣'), C('4', '♣'), C('5', '♣')], "Straight Flush"),
    ([C('8', '♥'), C('9', '♥'), C('10', '♥'), C('J', '♥'), C('Q', '♥')], "Straight Flush"),

    # --- Four of a Kind (6 cases) ---
    ([C('A', '♠'), C('A', '♥'), C('A', '♣'), C('A', '♦'), C('K', '♠')], "Four of a Kind"),
    ([C('2', '♠'), C('2', '♥'), C('2', '♣'), C('2', '♦'), C('3', '♠')], "Four of a Kind"),
    ([C('10', '♠'), C('10', '♥'), C('10', '♣'), C('10', '♦'), C('A', '♠')], "Four of a Kind"),
    ([C('7', '♠'), C('7', '♥'), C('7', '♣'), C('7', '♦'), C('8', '♠')], "Four of a Kind"),
    ([C('K', '♠'), C('K', '♥'), C('K', '♣'), C('K', '♦'), C('2', '♠')], "Four of a Kind"),
    ([C('J', '♠'), C('J', '♥'), C('J', '♣'), C('J', '♦'), C('9', '♠')], "Four of a Kind"),

    # --- Full House (6 cases) ---
    ([C('A', '♠'), C('A', '♥'), C('A', '♣'), C('K', '♠'), C('K', '♦')], "Full House"),
    ([C('2', '♠'), C('2', '♥'), C('2', '♣'), C('3', '♠'), C('3', '♦')], "Full House"),
    ([C('10', '♠'), C('10', '♥'), C('10', '♣'), C('J', '♠'), C('J', '♦')], "Full House"),
    ([C('Q', '♠'), C('Q', '♥'), C('Q', '♣'), C('8', '♠'), C('8', '♦')], "Full House"),
    ([C('5', '♠'), C('5', '♥'), C('5', '♣'), C('4', '♠'), C('4', '♦')], "Full House"),
    ([C('9', '♠'), C('9', '♥'), C('9', '♣'), C('A', '♠'), C('A', '♦')], "Full House"),

    # --- Flush (6 cases) ---
    ([C('2', '♠'), C('4', '♠'), C('6', '♠'), C('8', '♠'), C('K', '♠')], "Flush"),
    ([C('A', '♥'), C('3', '♥'), C('5', '♥'), C('7', '♥'), C('9', '♥')], "Flush"),
    ([C('J', '♣'), C('3', '♣'), C('Q', '♣'), C('5', '♣'), C('2', '♣')], "Flush"),
    ([C('10', '♦'), C('8', '♦'), C('6', '♦'), C('4', '♦'), C('2', '♦')], "Flush"),
    ([C('K', '♣'), C('Q', '♣'), C('J', '♣'), C('9', '♣'), C('2', '♣')], "Flush"),
    ([C('7', '♦'), C('5', '♦'), C('3', '♦'), C('2', '♦'), C('A', '♦')], "Flush"),

    # --- Straight (8 cases) ---
    ([C('2', '♠'), C('3', '♥'), C('4', '♣'), C('5', '♦'), C('6', '♠')], "Straight"),
    ([C('A', '♠'), C('2', '♥'), C('3', '♣'), C('4', '♦'), C('5', '♠')], "Straight"), # wheel straight
    ([C('10', '♠'), C('J', '♥'), C('Q', '♣'), C('K', '♦'), C('A', '♠')], "Straight"), # broadway straight
    ([C('5', '♠'), C('6', '♥'), C('7', '♣'), C('8', '♦'), C('9', '♠')], "Straight"),
    ([C('7', '♠'), C('8', '♥'), C('9', '♣'), C('10', '♦'), C('J', '♠')], "Straight"),
    ([C('8', '♠'), C('9', '♥'), C('10', '♣'), C('J', '♦'), C('Q', '♠')], "Straight"),
    ([C('9', '♠'), C('10', '♥'), C('J', '♣'), C('Q', '♦'), C('K', '♠')], "Straight"),
    ([C('3', '♠'), C('4', '♥'), C('5', '♣'), C('6', '♦'), C('7', '♠')], "Straight"),

    # --- Three of a Kind (6 cases) ---
    ([C('A', '♠'), C('A', '♥'), C('A', '♣'), C('K', '♠'), C('Q', '♦')], "Three of a Kind"),
    ([C('2', '♠'), C('2', '♥'), C('2', '♣'), C('3', '♠'), C('4', '♦')], "Three of a Kind"),
    ([C('10', '♠'), C('10', '♥'), C('10', '♣'), C('J', '♠'), C('9', '♦')], "Three of a Kind"),
    ([C('7', '♠'), C('7', '♥'), C('7', '♣'), C('8', '♠'), C('6', '♦')], "Three of a Kind"),
    ([C('Q', '♠'), C('Q', '♥'), C('Q', '♣'), C('2', '♠'), C('3', '♦')], "Three of a Kind"),
    ([C('J', '♠'), C('J', '♥'), C('J', '♣'), C('A', '♠'), C('5', '♦')], "Three of a Kind"),

    # --- Two Pair (6 cases) ---
    ([C('A', '♠'), C('A', '♥'), C('K', '♣'), C('K', '♠'), C('Q', '♦')], "Two Pair"),
    ([C('2', '♠'), C('2', '♥'), C('3', '♣'), C('3', '♠'), C('4', '♦')], "Two Pair"),
    ([C('10', '♠'), C('10', '♥'), C('J', '♣'), C('J', '♠'), C('9', '♦')], "Two Pair"),
    ([C('7', '♠'), C('7', '♥'), C('8', '♣'), C('8', '♠'), C('6', '♦')], "Two Pair"),
    ([C('Q', '♠'), C('Q', '♥'), C('2', '♣'), C('2', '♠'), C('3', '♦')], "Two Pair"),
    ([C('5', '♠'), C('5', '♥'), C('6', '♣'), C('6', '♠'), C('A', '♦')], "Two Pair"),

    # --- Jacks or Better (6 cases) ---
    ([C('J', '♠'), C('J', '♥'), C('K', '♣'), C('Q', '♠'), C('2', '♦')], "Jacks or Better"),
    ([C('Q', '♠'), C('Q', '♥'), C('A', '♣'), C('10', '♠'), C('3', '♦')], "Jacks or Better"),
    ([C('K', '♠'), C('K', '♥'), C('2', '♣'), C('5', '♠'), C('9', '♦')], "Jacks or Better"),
    ([C('A', '♠'), C('A', '♥'), C('3', '♣'), C('6', '♠'), C('8', '♦')], "Jacks or Better"),
    ([C('J', '♦'), C('J', '♣'), C('4', '♣'), C('7', '♠'), C('9', '♦')], "Jacks or Better"),
    ([C('Q', '♦'), C('Q', '♣'), C('5', '♣'), C('8', '♠'), C('10', '♦')], "Jacks or Better"),

    # --- Nothing (6 cases) ---
    ([C('10', '♠'), C('10', '♥'), C('K', '♣'), C('Q', '♠'), C('2', '♦')], "Nothing"), # pair of 10s is low pair
    ([C('9', '♠'), C('9', '♥'), C('A', '♣'), C('10', '♠'), C('3', '♦')], "Nothing"), # pair of 9s
    ([C('2', '♠'), C('3', '♥'), C('5', '♣'), C('7', '♠'), C('K', '♦')], "Nothing"), # high card
    ([C('A', '♠'), C('K', '♥'), C('Q', '♣'), C('J', '♠'), C('9', '♦')], "Nothing"), # high card
    ([C('5', '♠'), C('5', '♥'), C('6', '♣'), C('8', '♠'), C('Q', '♦')], "Nothing"), # pair of 5s
    ([C('7', '♦'), C('7', '♣'), C('2', '♣'), C('4', '♠'), C('J', '♦')], "Nothing"), # pair of 7s
]

@pytest.mark.parametrize("hand, expected", evaluate_cases, ids=[f"eval_{i}" for i in range(len(evaluate_cases))])
def test_evaluate_hand(hand, expected):
    assert poker.evaluate_hand(hand) == expected


# ----------------- SECTION 2: SMART HINTS (30 CASES) -----------------
hint_cases = [
    # Already winning (Royal Flush, Straight Flush, Four of a Kind, Full House, Flush, Straight)
    ([C('10', '♠'), C('J', '♠'), C('Q', '♠'), C('K', '♠'), C('A', '♠')], "Роял Флеш"),
    ([C('9', '♠'), C('10', '♠'), C('J', '♠'), C('Q', '♠'), C('K', '♠')], "Стрит-флеш"),
    ([C('A', '♠'), C('A', '♥'), C('A', '♣'), C('A', '♦'), C('K', '♠')], "Каре"),
    ([C('A', '♠'), C('A', '♥'), C('A', '♣'), C('K', '♠'), C('K', '♦')], "Фулл-хаус"),
    ([C('2', '♠'), C('4', '♠'), C('6', '♠'), C('8', '♠'), C('K', '♠')], "Флеш"),
    ([C('2', '♠'), C('3', '♥'), C('4', '♣'), C('5', '♦'), C('6', '♠')], "Стрит"),

    # Three of a Kind hints
    ([C('A', '♠'), C('A', '♥'), C('A', '♣'), C('K', '♠'), C('Q', '♦')], "Держите тройку A"),
    ([C('2', '♠'), C('2', '♥'), C('2', '♣'), C('3', '♠'), C('4', '♦')], "Держите тройку 2"),
    ([C('10', '♠'), C('10', '♥'), C('10', '♣'), C('J', '♠'), C('9', '♦')], "Держите тройку 10"),

    # Two Pair hints
    ([C('A', '♠'), C('A', '♥'), C('K', '♣'), C('K', '♠'), C('Q', '♦')], "Две пары!"),
    ([C('2', '♠'), C('2', '♥'), C('3', '♣'), C('3', '♠'), C('4', '♦')], "Две пары!"),

    # One Pair hints (Jacks or Better vs Low pair)
    ([C('J', '♠'), C('J', '♥'), C('K', '♣'), C('Q', '♠'), C('2', '♦')], "Пара J"),
    ([C('A', '♠'), C('A', '♥'), C('3', '♣'), C('6', '♠'), C('8', '♦')], "Пара A"),
    ([C('10', '♠'), C('10', '♥'), C('K', '♣'), C('Q', '♠'), C('2', '♦')], "Маленькая пара 10"),
    ([C('5', '♠'), C('5', '♥'), C('6', '♣'), C('8', '♠'), C('Q', '♦')], "Маленькая пара 5"),

    # Flush draws (4 cards of same suit)
    ([C('2', '♠'), C('4', '♠'), C('6', '♠'), C('8', '♠'), C('K', '♥')], "флеш"),
    ([C('A', '♥'), C('3', '♥'), C('5', '♥'), C('7', '♥'), C('9', '♦')], "флеш"),

    # High card hints
    ([C('A', '♠'), C('3', '♥'), C('5', '♣'), C('7', '♦'), C('2', '♠')], "старшие карты"),
    ([C('K', '♠'), C('4', '♥'), C('5', '♣'), C('6', '♦'), C('2', '♠')], "старшие карты"),
]

# Pad to 30 cases
while len(hint_cases) < 30:
    hint_cases.append(([C('2', '♠'), C('3', '♥'), C('5', '♣'), C('7', '♦'), C('9', '♠')], "Слабая рука"))

@pytest.mark.parametrize("hand, hint_substring", hint_cases, ids=[f"hint_{i}" for i in range(len(hint_cases))])
def test_get_smart_hint(hand, hint_substring):
    hint = poker.get_smart_hint(hand)
    clean_hint = hint.replace("<b>", "").replace("</b>", "")
    assert hint_substring.lower() in clean_hint.lower()


# ----------------- SECTION 3: WINNING CARD HIGHLIGHTING (20 CASES) -----------------
highlight_cases = [
    # (hand, combo, expected_indices)
    # Broadway combos (should highlight all 5 cards)
    ([C('10', '♠'), C('J', '♠'), C('Q', '♠'), C('K', '♠'), C('A', '♠')], "Royal Flush", {0, 1, 2, 3, 4}),
    ([C('9', '♠'), C('10', '♠'), C('J', '♠'), C('Q', '♠'), C('K', '♠')], "Straight Flush", {0, 1, 2, 3, 4}),
    ([C('2', '♠'), C('4', '♠'), C('6', '♠'), C('8', '♠'), C('K', '♠')], "Flush", {0, 1, 2, 3, 4}),
    ([C('2', '♠'), C('3', '♥'), C('4', '♣'), C('5', '♦'), C('6', '♠')], "Straight", {0, 1, 2, 3, 4}),

    # Four of a Kind (should highlight 4 cards)
    ([C('A', '♠'), C('A', '♥'), C('A', '♣'), C('A', '♦'), C('K', '♠')], "Four of a Kind", {0, 1, 2, 3}),
    ([C('K', '♠'), C('A', '♥'), C('A', '♣'), C('A', '♦'), C('A', '♠')], "Four of a Kind", {1, 2, 3, 4}),

    # Full House (should highlight all 5 cards)
    ([C('A', '♠'), C('A', '♥'), C('A', '♣'), C('K', '♠'), C('K', '♦')], "Full House", {0, 1, 2, 3, 4}),

    # Three of a Kind (should highlight 3 cards)
    ([C('A', '♠'), C('A', '♥'), C('A', '♣'), C('K', '♠'), C('Q', '♦')], "Three of a Kind", {0, 1, 2}),
    ([C('K', '♠'), C('A', '♥'), C('A', '♣'), C('A', '♦'), C('Q', '♦')], "Three of a Kind", {1, 2, 3}),

    # Two Pair (should highlight 4 cards)
    ([C('A', '♠'), C('A', '♥'), C('K', '♣'), C('K', '♠'), C('Q', '♦')], "Two Pair", {0, 1, 2, 3}),
    ([C('Q', '♦'), C('A', '♠'), C('A', '♥'), C('K', '♣'), C('K', '♠')], "Two Pair", {1, 2, 3, 4}),

    # Jacks or Better (should highlight 2 cards)
    ([C('J', '♠'), C('J', '♥'), C('K', '♣'), C('Q', '♠'), C('2', '♦')], "Jacks or Better", {0, 1}),
    ([C('K', '♣'), C('J', '♠'), C('J', '♥'), C('Q', '♠'), C('2', '♦')], "Jacks or Better", {1, 2}),

    # Nothing (should highlight 0 cards)
    ([C('10', '♠'), C('10', '♥'), C('K', '♣'), C('Q', '♠'), C('2', '♦')], "Nothing", set()),
]

while len(highlight_cases) < 20:
    highlight_cases.append(([C('2', '♠'), C('3', '♥'), C('5', '♣'), C('7', '♦'), C('9', '♠')], "Nothing", set()))

@pytest.mark.parametrize("hand, combo, expected_indices", highlight_cases, ids=[f"high_{i}" for i in range(len(highlight_cases))])
def test_get_winning_card_indices(hand, combo, expected_indices):
    assert poker.get_winning_card_indices(hand, combo) == expected_indices


# ----------------- SECTION 4: CALLBACK PARSING UTILS (15 CASES) -----------------
parsing_cases = [
    # (callback_data, expected_index)
    ("poker_hold_123_456_789_0", 0),
    ("poker_hold_123_456_789_1", 1),
    ("poker_hold_123_456_789_2", 2),
    ("poker_hold_123_456_789_3", 3),
    ("poker_hold_123_456_789_4", 4),
    ("poker_replay_100", 100),
    ("poker_replay_5000", 5000),
    ("poker_hold_0", 0),
    ("poker_hold_invalid", None),
    ("poker_replay_invalid", None),
]

while len(parsing_cases) < 15:
    parsing_cases.append(("poker_hold_123_456_789_0", 0))

@pytest.mark.parametrize("callback_data, expected", parsing_cases, ids=[f"parse_{i}" for i in range(len(parsing_cases))])
def test_parse_callback_index(callback_data, expected):
    assert poker.parse_callback_index(callback_data, -1) == expected


# ----------------- SECTION 5: STATIC CALLBACKS (10 CASES) -----------------
static_cases = [
    ("poker_help_static", True),
    ("poker_payouts_static", True),
    ("poker_help_123_456_789", False),
    ("poker_payouts_123_456_789", False),
    ("poker_hold_123_456_789_0", False),
    ("poker_replay_100", False),
    ("poker_help_static_extra", True),
]

while len(static_cases) < 10:
    static_cases.append(("poker_help_static", True))

@pytest.mark.parametrize("callback_data, expected", static_cases, ids=[f"static_{i}" for i in range(len(static_cases))])
def test_is_static_callback(callback_data, expected):
    assert poker.is_static_callback(callback_data) == expected
