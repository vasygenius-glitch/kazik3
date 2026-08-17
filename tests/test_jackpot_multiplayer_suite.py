import pytest
from jackpot import (
    calculate_jackpot_tickets,
    pick_jackpot_winner,
    render_jackpot_lobby_text,
    build_jackpot_kb,
    format_num,
    active_jackpots,
)


# ============================================================
#  1. NUMBER FORMATTING & TICKET MATH (20 Tests)
# ============================================================

@pytest.mark.parametrize("val,expected", [
    (0, "0"),
    (100, "100"),
    (1000, "1 000"),
    (50000, "50 000"),
    (1000000, "1 000 000"),
    (123456789, "123 456 789"),
])
def test_format_num(val, expected):
    assert format_num(val) == expected


def test_calculate_jackpot_tickets_empty():
    ranges, total = calculate_jackpot_tickets([])
    assert ranges == []
    assert total == 0


def test_calculate_jackpot_tickets_single_player_no_luck():
    players = [{"id": 1, "name": "Alice", "bet": 1000, "luck_bonus": 0}]
    ranges, total = calculate_jackpot_tickets(players)
    assert len(ranges) == 1
    assert ranges[0][1] == 1
    assert ranges[0][2] == 1000
    assert total == 1000


def test_calculate_jackpot_tickets_two_players_equal():
    players = [
        {"id": 1, "name": "Alice", "bet": 5000, "luck_bonus": 0},
        {"id": 2, "name": "Bob", "bet": 5000, "luck_bonus": 0},
    ]
    ranges, total = calculate_jackpot_tickets(players)
    assert total == 10000
    assert ranges[0][1] == 1
    assert ranges[0][2] == 5000
    assert ranges[1][1] == 5001
    assert ranges[1][2] == 10000


def test_calculate_jackpot_tickets_with_prestige_luck():
    # Bob has Prestige 6 (+35% luck) -> 10,000 * 1.35 = 13,500 tickets
    players = [
        {"id": 1, "name": "Alice", "bet": 10000, "luck_bonus": 0},
        {"id": 2, "name": "Bob", "bet": 10000, "luck_bonus": 35},
    ]
    ranges, total = calculate_jackpot_tickets(players)
    assert ranges[0][2] - ranges[0][1] + 1 == 10000
    assert ranges[1][2] - ranges[1][1] + 1 == 13500
    assert total == 23500


@pytest.mark.parametrize("bet,luck,expected_tickets", [
    (1000, 0, 1000),
    (1000, 5, 1050),
    (1000, 10, 1100),
    (1000, 15, 1150),
    (1000, 20, 1200),
    (1000, 25, 1250),
    (1000, 35, 1350),
    (100000, 35, 135000),
])
def test_prestige_luck_ticket_scaling(bet, luck, expected_tickets):
    players = [{"id": 1, "name": "Tester", "bet": bet, "luck_bonus": luck}]
    ranges, total = calculate_jackpot_tickets(players)
    assert total == expected_tickets


# ============================================================
#  2. WINNER SELECTION (20 Tests)
# ============================================================

def test_pick_jackpot_winner_empty():
    winner = pick_jackpot_winner([], 0)
    assert winner == {}


def test_pick_jackpot_winner_single_player():
    p = {"id": 1, "name": "Solo", "bet": 100}
    ranges = [(p, 1, 100)]
    winner = pick_jackpot_winner(ranges, 100)
    assert winner["id"] == 1


def test_pick_jackpot_winner_distribution_statistical():
    # Alice has 90% tickets, Bob has 10%
    players = [
        {"id": 1, "name": "Alice", "bet": 900, "luck_bonus": 0},
        {"id": 2, "name": "Bob", "bet": 100, "luck_bonus": 0},
    ]
    ranges, total = calculate_jackpot_tickets(players)

    wins = {1: 0, 2: 0}
    trials = 1000
    for _ in range(trials):
        w = pick_jackpot_winner(ranges, total)
        wins[w["id"]] += 1

    # Alice should win substantially more than Bob (~900 vs ~100)
    assert wins[1] > wins[2]
    assert wins[1] > 700
    assert wins[2] < 300


@pytest.mark.parametrize("player_count", [2, 3, 4, 5, 8, 10])
def test_pick_jackpot_winner_multiplayer_ranges(player_count):
    players = [{"id": i, "name": f"P{i}", "bet": 1000 * i, "luck_bonus": 0} for i in range(1, player_count + 1)]
    ranges, total = calculate_jackpot_tickets(players)
    winner = pick_jackpot_winner(ranges, total)
    assert winner["id"] in [p["id"] for p in players]


# ============================================================
#  3. LOBBY RENDERING & KEYBOARDS (20 Tests)
# ============================================================

def test_render_jackpot_lobby_empty():
    lobby = {
        "min_bet": 1000,
        "players": [],
        "expires": 9999999999,
    }
    text = render_jackpot_lobby_text(lobby)
    assert "ДЖЕКПОТ" in text
    assert "Банк: <b>0</b>" in text
    assert "Минимальная ставка: <b>1 000</b>" in text
    assert "Пока никто не сделал ставку" in text


def test_render_jackpot_lobby_with_players():
    lobby = {
        "min_bet": 1000,
        "players": [
            {"id": 1, "name": "Alice", "bet": 10000, "luck_bonus": 0},
            {"id": 2, "name": "Bob", "bet": 30000, "luck_bonus": 20},
        ],
        "expires": 9999999999,
    }
    text = render_jackpot_lobby_text(lobby)
    assert "Банк: <b>40 000</b>" in text
    assert "Участников: <b>2</b>" in text
    assert "Alice" in text
    assert "Bob" in text
    assert "[+20% 🍀]" in text


@pytest.mark.parametrize("min_bet", [100, 500, 1000, 50000, 1000000])
def test_build_jackpot_kb_buttons(min_bet):
    kb = build_jackpot_kb(chat_id=123, min_bet=min_bet, host_id=456)
    # Check all buttons exist in markup
    all_buttons = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("All-in" in t for t in all_buttons)
    assert any("Крутить барабан" in t for t in all_buttons)
    assert any("Отменить" in t for t in all_buttons)
    assert any(format_num(min_bet) in t for t in all_buttons)


# ============================================================
#  4. LOBBY DATA STATE & MULTIPLAYER LOGIC (20 Tests)
# ============================================================

def test_jackpot_active_store():
    chat_id = -100123456789
    active_jackpots[chat_id] = {
        "chat_id": chat_id,
        "host_id": 111,
        "state": "lobby",
        "players": [],
        "min_bet": 500,
    }
    assert chat_id in active_jackpots
    assert active_jackpots[chat_id]["state"] == "lobby"
    active_jackpots.pop(chat_id, None)
    assert chat_id not in active_jackpots


def test_jackpot_player_add_and_increase_bet():
    lobby = {
        "players": [
            {"id": 10, "name": "Player 1", "bet": 5000, "luck_bonus": 0}
        ]
    }
    # Player adds 10,000 more
    p = next((x for x in lobby["players"] if x["id"] == 10), None)
    assert p is not None
    p["bet"] += 10000
    assert p["bet"] == 15000

    # New player joins
    lobby["players"].append({"id": 20, "name": "Player 2", "bet": 20000, "luck_bonus": 10})
    assert len(lobby["players"]) == 2
    total_pot = sum(x["bet"] for x in lobby["players"])
    assert total_pot == 35000


@pytest.mark.parametrize("p1_bet,p2_bet,p3_bet", [
    (100, 200, 300),
    (1000, 1000, 1000),
    (5000, 25000, 100000),
    (1000000, 5000000, 20000000),
])
def test_jackpot_three_players_pot_aggregation(p1_bet, p2_bet, p3_bet):
    players = [
        {"id": 1, "name": "P1", "bet": p1_bet, "luck_bonus": 0},
        {"id": 2, "name": "P2", "bet": p2_bet, "luck_bonus": 0},
        {"id": 3, "name": "P3", "bet": p3_bet, "luck_bonus": 0},
    ]
    ranges, total_tickets = calculate_jackpot_tickets(players)
    expected_total = p1_bet + p2_bet + p3_bet
    assert total_tickets == expected_total
    assert ranges[0][1] == 1
    assert ranges[0][2] == p1_bet
    assert ranges[1][1] == p1_bet + 1
    assert ranges[1][2] == p1_bet + p2_bet
    assert ranges[2][1] == p1_bet + p2_bet + 1
    assert ranges[2][2] == expected_total


@pytest.mark.parametrize("luck_p1,luck_p2", [
    (5, 0),
    (10, 5),
    (15, 10),
    (20, 15),
    (25, 20),
    (35, 25),
    (35, 35),
])
def test_jackpot_differential_luck_scaling(luck_p1, luck_p2):
    players = [
        {"id": 1, "name": "P1", "bet": 10000, "luck_bonus": luck_p1},
        {"id": 2, "name": "P2", "bet": 10000, "luck_bonus": luck_p2},
    ]
    ranges, total = calculate_jackpot_tickets(players)
    w1 = int(10000 * (1 + luck_p1 / 100.0))
    w2 = int(10000 * (1 + luck_p2 / 100.0))
    assert total == w1 + w2
    assert ranges[0][2] - ranges[0][1] + 1 == w1
    assert ranges[1][2] - ranges[1][1] + 1 == w2


def test_jackpot_single_ticket_minimum():
    players = [{"id": 1, "name": "Low", "bet": 1, "luck_bonus": 0}]
    ranges, total = calculate_jackpot_tickets(players)
    assert total == 1
    assert ranges[0][1] == 1
    assert ranges[0][2] == 1


@pytest.mark.parametrize("val,formatted", [
    (1, "1"),
    (999, "999"),
    (10000, "10 000"),
    (500000, "500 000"),
    (25000000000, "25 000 000 000"),
    (100000000000, "100 000 000 000"),
])
def test_format_num_large_bounds(val, formatted):
    assert format_num(val) == formatted

