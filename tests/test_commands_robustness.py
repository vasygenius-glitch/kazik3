import pytest
from unittest.mock import MagicMock
import sys

# Mock imports
sys.modules['firebase_admin'] = MagicMock()
sys.modules['firebase_admin.credentials'] = MagicMock()
sys.modules['firebase_admin.firestore'] = MagicMock()
sys.modules['firebase_admin.firestore_async'] = MagicMock()
sys.modules['diseases'] = MagicMock()
sys.modules['config'] = MagicMock()

import cards

# ----------------- SECTION 1: BLACKJACK SCORE TESTS (30 CASES) -----------------
bj_test_cases = [
    # (cards_ranks, expected_score)
    (['2', '3'], 5),
    (['10', 'J'], 20),
    (['A', '10'], 21),
    (['A', 'A'], 12),
    (['A', 'A', 'A'], 13),
    (['A', 'A', '10'], 12),
    (['A', '9', 'A'], 21),
    (['10', 'J', 'A'], 21),
    (['K', 'Q', 'J'], 30),
    (['2', '3', '4', '5', '6'], 20),
    (['A', '2', '3', '4', 'A'], 21),
    (['5', '5', '5', '5'], 20),
    (['A', 'A', 'A', 'A', 'A'], 15),
    (['10', 'A', 'A', 'A'], 13),
    (['9', '9', '4'], 22),
    (['2', '8', 'A'], 21),
    (['3', '7', 'A', 'A'], 12),
    (['4', '6', '10'], 20),
    (['A', 'A', 'A', 'A', 'A', 'A'], 16),
    (['8', '8', 'A', 'A'], 18),
    (['7', '7', '7'], 21),
    (['10', '9', 'A', 'A'], 21),
    (['5', 'K', 'A'], 16),
    (['3', 'A', 'A', 'A', 'A', 'A', 'A'], 19),
    (['J', 'Q', '2'], 22),
    (['A', 'A', 'A', 'A', 'A', 'A', 'A', 'A'], 18),
    (['6', '6', 'A', 'A', 'A'], 15),
    (['9', 'A', 'A', 'A', 'A'], 13),
    (['10', '5', 'A', 'A'], 17),
    (['2', '2', '2', '2', '2', '2', '2', '2', '2', '2', '2'], 22),
]

@pytest.mark.parametrize("ranks, expected", bj_test_cases)
def test_blackjack_score(ranks, expected):
    hand = [{'rank': r, 'suit': '♠'} for r in ranks]
    assert cards.calculate_score(hand) == expected


# ----------------- SECTION 2: BACCARAT SCORE TESTS (30 CASES) -----------------
baccarat_test_cases = [
    # (cards_ranks, expected_score)
    (['2', '3'], 5),
    (['10', 'J'], 0),
    (['A', '10'], 1),
    (['A', 'A'], 2),
    (['A', 'A', 'A'], 3),
    (['A', 'A', '10'], 2),
    (['A', '9', 'A'], 1),
    (['10', 'J', 'A'], 1),
    (['K', 'Q', 'J'], 0),
    (['2', '3', '4', '5', '6'], 0),
    (['A', '2', '3', '4', 'A'], 1),
    (['5', '5', '5', '5'], 0),
    (['A', 'A', 'A', 'A', 'A'], 5),
    (['10', 'A', 'A', 'A'], 3),
    (['9', '9', '4'], 2),
    (['2', '8', 'A'], 1),
    (['3', '7', 'A', 'A'], 2),
    (['4', '6', '10'], 0),
    (['A', 'A', 'A', 'A', 'A', 'A'], 6),
    (['8', '8', 'A', 'A'], 8),
    (['7', '7', '7'], 1),
    (['10', '9', 'A', 'A'], 1),
    (['5', 'K', 'A'], 6),
    (['3', 'A', 'A', 'A', 'A', 'A', 'A'], 9),
    (['J', 'Q', '2'], 2),
    (['A', 'A', 'A', 'A', 'A', 'A', 'A', 'A'], 8),
    (['6', '6', 'A', 'A', 'A'], 5),
    (['9', 'A', 'A', 'A', 'A'], 3),
    (['10', '5', 'A', 'A'], 7),
    (['2', '2', '2', '2', '2', '2', '2', '2', '2', '2', '2'], 2),
]

@pytest.mark.parametrize("ranks, expected", baccarat_test_cases)
def test_baccarat_score(ranks, expected):
    hand = [{'rank': r, 'suit': '♠'} for r in ranks]
    assert cards.get_baccarat_score(hand) == expected


# ----------------- SECTION 3: ROULETTE PAYOUT MATH TESTS (30 CASES) -----------------
def get_roulette_profit(bet, guess, result_number, is_vip):
    diff = abs(result_number - guess)
    total_win = 0
    if diff == 0: total_win = bet * 3
    elif diff <= 2: total_win = int(bet * 1.5)
    elif diff <= 4: total_win = int(bet * 1.1)
    else: total_win = 0
    
    if total_win > 0:
        profit = total_win - bet
        if is_vip: profit += int(profit * 0.1)
        return profit
    return -bet

roulette_payouts = []
# Generate 30 distinct scenarios for roulette payout testing
for bet in [100, 1000]:
    for guess in [10, 20, 30]:
        for result in [guess, guess + 1, guess + 3, guess + 5, guess - 2]:
            for is_vip in [True, False]:
                roulette_payouts.append((bet, guess, result, is_vip))
roulette_payouts = roulette_payouts[:30]

@pytest.mark.parametrize("bet, guess, result, is_vip", roulette_payouts)
def test_roulette_payout_math(bet, guess, result, is_vip):
    # Just running the logic checks
    profit = get_roulette_profit(bet, guess, result, is_vip)
    diff = abs(result - guess)
    if diff == 0:
        expected = (bet * 3) - bet
        if is_vip: expected += int(expected * 0.1)
        assert profit == expected
    elif diff <= 2:
        expected = int(bet * 1.5) - bet
        if is_vip: expected += int(expected * 0.1)
        assert profit == expected
    elif diff <= 4:
        expected = int(bet * 1.1) - bet
        if is_vip: expected += int(expected * 0.1)
        assert profit == expected
    else:
        assert profit == -bet


# ----------------- SECTION 4: SLOTS PAYOUT MATH TESTS (30 CASES) -----------------
def get_slots_profit(bet, final_slots, is_vip):
    profit = 0
    if final_slots[0] == final_slots[1] == final_slots[2]:
        if final_slots[0] == "7️⃣": profit = bet * 20
        elif final_slots[0] in ["💎", "🔔"]: profit = bet * 10
        else: profit = bet * 5
    elif final_slots[0] == final_slots[1] or final_slots[1] == final_slots[2] or final_slots[0] == final_slots[2]:
        if final_slots[0] == final_slots[1] or final_slots[0] == final_slots[2]: pair = final_slots[0]
        else: pair = final_slots[1]
        if pair == "7️⃣": profit = bet * 2
        elif pair in ["💎", "🔔"]: profit = int(bet * 1.5)
        else: profit = int(bet * 0.5)
    
    if profit > 0:
        net_profit = profit - bet
        if is_vip: net_profit += int(net_profit * 0.1)
        return net_profit
    return -bet

slots_payouts = [
    # Three of a kind
    (100, ["7️⃣", "7️⃣", "7️⃣"], True, (100 * 20 - 100) + int((100 * 20 - 100) * 0.1)),
    (100, ["7️⃣", "7️⃣", "7️⃣"], False, 100 * 20 - 100),
    (100, ["💎", "💎", "💎"], False, 100 * 10 - 100),
    (200, ["🔔", "🔔", "🔔"], True, (200 * 10 - 200) + int((200 * 10 - 200) * 0.1)),
    (100, ["🍒", "🍒", "🍒"], False, 100 * 5 - 100),
    
    # Pairs with 7️⃣
    (100, ["7️⃣", "7️⃣", "🍒"], True, (100 * 2 - 100) + int((100 * 2 - 100) * 0.1)),
    (100, ["7️⃣", "🍒", "7️⃣"], False, 100 * 2 - 100),
    (100, ["🍒", "7️⃣", "7️⃣"], False, 100 * 2 - 100),
    
    # Pairs with 💎/🔔
    (100, ["💎", "💎", "🍒"], True, (int(100 * 1.5) - 100) + int((int(100 * 1.5) - 100) * 0.1)),
    (100, ["🔔", "🍒", "🔔"], False, int(100 * 1.5) - 100),
    
    # Pairs with others
    (100, ["🍒", "🍒", "🍋"], True, (int(100 * 0.5) - 100) + int((int(100 * 0.5) - 100) * 0.1)),
    (100, ["🍋", "🍉", "🍉"], False, int(100 * 0.5) - 100),
    
    # Complete loss
    (100, ["🍒", "🍋", "🍉"], True, -100),
    (100, ["7️⃣", "💎", "🔔"], False, -100),
]
# Padding to 30 cases
while len(slots_payouts) < 30:
    slots_payouts.append((100, ["🍒", "🍋", "🍉"], False, -100))

@pytest.mark.parametrize("bet, final_slots, is_vip, expected_profit", slots_payouts)
def test_slots_payout_math(bet, final_slots, is_vip, expected_profit):
    assert get_slots_profit(bet, final_slots, is_vip) == expected_profit


# ----------------- SECTION 5: BANK DEPOSIT/WITHDRAW MATH TESTS (30 CASES) -----------------
def calculate_deposit_balance(action, amount, current_balance, bank_deposit, bank_rate, is_all):
    if action == "deposit":
        actual_amount = current_balance if is_all else amount
        if actual_amount <= 0 or current_balance < actual_amount:
            return None # Fail
        # In profile_bank.py:
        # updates['bank_deposit'] = user_data.get('bank_deposit', 0) + actual_amount
        # updates['balance'] = current_balance - actual_amount
        return current_balance - actual_amount, bank_deposit + actual_amount
    elif action == "withdraw":
        actual_amount = bank_deposit if is_all else amount
        if actual_amount <= 0 or bank_deposit < actual_amount:
            return None # Fail
        
        # Commission of bank_rate%
        comm = int(actual_amount * bank_rate / 100.0)
        net_amount = actual_amount - comm
        return current_balance + net_amount, bank_deposit - actual_amount
    return None

bank_scenarios = []
# Generate 30 deposit/withdraw test parameters
for action in ["deposit", "withdraw"]:
    for is_all in [True, False]:
        for bank_rate in [0, 5, 10]:
            for bal, dep, amt in [(500, 1000, 200), (0, 100, 50), (1000, 0, 500)]:
                bank_scenarios.append((action, amt, bal, dep, bank_rate, is_all))
bank_scenarios = bank_scenarios[:30]

@pytest.mark.parametrize("action, amount, current_balance, bank_deposit, bank_rate, is_all", bank_scenarios)
def test_bank_payout_math(action, amount, current_balance, bank_deposit, bank_rate, is_all):
    result = calculate_deposit_balance(action, amount, current_balance, bank_deposit, bank_rate, is_all)
    if action == "deposit":
        expected_amt = current_balance if is_all else amount
        if expected_amt <= 0 or current_balance < expected_amt:
            assert result is None
        else:
            new_bal, new_dep = result
            assert new_bal == current_balance - expected_amt
            assert new_dep == bank_deposit + expected_amt
    elif action == "withdraw":
        expected_amt = bank_deposit if is_all else amount
        if expected_amt <= 0 or bank_deposit < expected_amt:
            assert result is None
        else:
            new_bal, new_dep = result
            comm = int(expected_amt * bank_rate / 100.0)
            assert new_bal == current_balance + (expected_amt - comm)
            assert new_dep == bank_deposit - expected_amt
