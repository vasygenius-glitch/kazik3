import pytest
from rpg_economy import (
    BASE_CURRENCY, calculate_bot_price, calculate_server_price,
    init_game_state, process_click, buy_bot, buy_server,
    feed_pig, heal_sanity, tick_economy
)

# GROUP 1: Pricing calculations for Bots (001 - 010)
def test_economy_001():
    assert calculate_bot_price(0) == 100

def test_economy_002():
    assert calculate_bot_price(1) == 115

def test_economy_003():
    assert calculate_bot_price(2) == 132

def test_economy_004():
    assert calculate_bot_price(3) == 152

def test_economy_005():
    assert calculate_bot_price(4) == 175

def test_economy_006():
    assert calculate_bot_price(5) == 201

def test_economy_007():
    assert calculate_bot_price(10) == 405

def test_economy_008():
    assert calculate_bot_price(-1) == 100

def test_economy_009():
    assert calculate_bot_price(-100) == 100

def test_economy_010():
    assert calculate_bot_price(50) == 108366



# GROUP 2: Pricing calculations for Servers (011 - 020)
def test_economy_011():
    assert calculate_server_price(0) == 1000

def test_economy_012():
    assert calculate_server_price(1) == 1500

def test_economy_013():
    assert calculate_server_price(2) == 2250

def test_economy_014():
    assert calculate_server_price(3) == 3375

def test_economy_015():
    assert calculate_server_price(4) == 5062

def test_economy_016():
    assert calculate_server_price(5) == 7594

def test_economy_017():
    assert calculate_server_price(-5) == 1000

def test_economy_018():
    assert calculate_server_price(-100) == 1000

def test_economy_019():
    assert calculate_server_price(10) == 57665

def test_economy_020():
    assert calculate_server_price(15) == 437894



# GROUP 3: Game State Initialization (021 - 030)
def test_economy_021():
    state = init_game_state()
    assert state["balance"] == 500

def test_economy_022():
    state = init_game_state()
    assert state["currency"] == BASE_CURRENCY

def test_economy_023():
    state = init_game_state(1000)
    assert state["balance"] == 1000

def test_economy_024():
    state = init_game_state(-500)
    assert state["balance"] == 0

def test_economy_025():
    state = init_game_state()
    assert state["bots"] == 0
    assert state["servers"] == 1

def test_economy_026():
    state = init_game_state()
    assert state["hunger"] == 0
    assert state["energy"] == 100

def test_economy_027():
    state = init_game_state()
    assert state["sanity"] == 100
    assert state["horror_level"] == 0

def test_economy_028():
    state = init_game_state()
    assert state["total_clicks"] == 0
    assert state["total_earned"] == 0

def test_economy_029():
    state = init_game_state(0)
    assert state["balance"] == 0

def test_economy_030():
    state = init_game_state(999999)
    assert state["balance"] == 999999



# GROUP 4: Manual Clicking Mechanics (031 - 050)
def test_economy_031():
    state = init_game_state(100)
    state, earned = process_click(state)
    assert earned == 1
    assert state["balance"] == 101

def test_economy_032():
    state = init_game_state(100)
    state, _ = process_click(state)
    assert state["energy"] == 98

def test_economy_033():
    state = init_game_state(100)
    state, _ = process_click(state)
    assert state["hunger"] == 1

def test_economy_034():
    state = init_game_state(100)
    state, _ = process_click(state)
    assert state["total_clicks"] == 1

def test_economy_035():
    state = init_game_state(100)
    state["energy"] = 0
    state, earned = process_click(state)
    assert earned == 0
    assert state["balance"] == 100

def test_economy_036():
    state = init_game_state(100)
    state["energy"] = 1
    state, earned = process_click(state)
    assert earned == 1
    assert state["energy"] == 0

def test_economy_037():
    state = init_game_state(100)
    state["click_power"] = 10
    state, earned = process_click(state)
    assert earned == 10

def test_economy_038():
    state = init_game_state(100)
    state["sanity"] = 20
    state, earned = process_click(state)
    assert earned == 2  # multiplier 2.0x

def test_economy_039():
    state = init_game_state(100)
    state["sanity"] = 20
    state["horror_level"] = 5
    state, earned = process_click(state)
    assert earned == 2  # multiplier 2.5x -> int(1 * 2.5) = 2

def test_economy_040():
    state = init_game_state(100)
    state["click_power"] = 10
    state["sanity"] = 10
    state["horror_level"] = 10
    state, earned = process_click(state)
    assert earned == 30  # power 10 * multiplier (2.0 + 1.0) = 30

def test_economy_041():
    state = init_game_state(100)
    state["sanity"] = 40
    for _ in range(5):
        state, _ = process_click(state)
    assert state["horror_level"] == 1

def test_economy_042():
    state = init_game_state(100)
    state["sanity"] = 80
    for _ in range(5):
        state, _ = process_click(state)
    assert state["horror_level"] == 0

def test_economy_043():
    state = init_game_state(100)
    state["hunger"] = 99
    state, _ = process_click(state)
    assert state["hunger"] == 100

def test_economy_044():
    state = init_game_state(100)
    state["hunger"] = 100
    state, _ = process_click(state)
    assert state["hunger"] == 100

def test_economy_045():
    state = init_game_state(100)
    state["energy"] = 100
    for _ in range(50):
        state, _ = process_click(state)
    assert state["energy"] == 0

def test_economy_046():
    state = init_game_state(100)
    state["energy"] = 5
    state, _ = process_click(state)
    state, _ = process_click(state)
    state, _ = process_click(state)
    assert state["energy"] == 0

def test_economy_047():
    state = init_game_state(100)
    state, earned = process_click(state)
    assert state["total_earned"] == earned

def test_economy_048():
    state = init_game_state(100)
    state, _ = process_click(state)
    state, _ = process_click(state)
    assert state["total_clicks"] == 2

def test_economy_049():
    state = init_game_state(100)
    state["sanity"] = 0
    state["horror_level"] = 10
    state, earned = process_click(state)
    assert earned == 3

def test_economy_050():
    state = init_game_state(100)
    state["energy"] = 0
    state, earned = process_click(state)
    assert earned == 0
    assert state["total_clicks"] == 0



# GROUP 5: Bot Purchases (051 - 070)
def test_economy_051():
    state = init_game_state(500)
    state, success, msg = buy_bot(state)
    assert success is True
    assert state["bots"] == 1
    assert state["balance"] == 400

def test_economy_052():
    state = init_game_state(50)
    state, success, msg = buy_bot(state)
    assert success is False
    assert state["bots"] == 0
    assert state["balance"] == 50

def test_economy_053():
    state = init_game_state(1000)
    # Buy 5 bots (capacity of 1 server is 5)
    for _ in range(5):
        state, success, _ = buy_bot(state)
        assert success is True
    assert state["bots"] == 5

def test_economy_054():
    state = init_game_state(1000)
    for _ in range(5):
        state, _, _ = buy_bot(state)
    # 6th bot should fail due to server capacity limit
    state, success, msg = buy_bot(state)
    assert success is False
    assert "серверов" in msg
    assert state["bots"] == 5

def test_economy_055():
    state = init_game_state(1000)
    state["servers"] = 2
    for _ in range(6):
        state, success, _ = buy_bot(state)
        assert success is True
    assert state["bots"] == 6

def test_economy_056():
    state = init_game_state(100)
    state, success, _ = buy_bot(state)
    assert success is True
    assert state["balance"] == 0

def test_economy_057():
    state = init_game_state(500)
    state, _, _ = buy_bot(state)  # cost 100
    state, _, _ = buy_bot(state)  # cost 115
    assert state["balance"] == 285

def test_economy_058():
    state = init_game_state(1000)
    state, _, _ = buy_bot(state)  # 100
    state, _, _ = buy_bot(state)  # 115
    state, _, _ = buy_bot(state)  # 132
    assert state["balance"] == 653

def test_economy_059():
    state = init_game_state(500)
    state["bots"] = 5
    state, success, _ = buy_bot(state)
    assert success is False  # capacity check

def test_economy_060():
    state = init_game_state(500)
    state["bots"] = 4
    state, success, _ = buy_bot(state)
    assert success is True

def test_economy_061():
    state = init_game_state(5)
    state, success, msg = buy_bot(state)
    assert msg == f"Недостаточно валюты {BASE_CURRENCY}"

def test_economy_062():
    state = init_game_state(1000)
    state["servers"] = 0
    state, success, msg = buy_bot(state)
    assert success is False
    assert state["bots"] == 0

def test_economy_063():
    state = init_game_state(500)
    state, _, _ = buy_bot(state)
    state, success, _ = buy_bot(state)
    assert state["bots"] == 2

def test_economy_064():
    state = init_game_state(200)
    state, _, _ = buy_bot(state)  # 100
    state, success, _ = buy_bot(state)  # 115 -> fails
    assert success is False
    assert state["bots"] == 1

def test_economy_065():
    state = init_game_state(215)
    state, _, _ = buy_bot(state)  # 100
    state, success, _ = buy_bot(state)  # 115 -> succeeds
    assert success is True
    assert state["bots"] == 2

def test_economy_066():
    state = init_game_state(1000)
    state["bots"] = 10
    state, success, _ = buy_bot(state)
    assert success is False

def test_economy_067():
    state = init_game_state(1000)
    state["servers"] = 3
    state["bots"] = 14
    state, success, _ = buy_bot(state)
    assert success is True

def test_economy_068():
    state = init_game_state(1000)
    state["servers"] = 3
    state["bots"] = 15
    state, success, _ = buy_bot(state)
    assert success is False

def test_economy_069():
    state = init_game_state(10000)
    for _ in range(5):
        state, _, _ = buy_bot(state)
    assert state["bots"] == 5

def test_economy_070():
    state = init_game_state(10000)
    state["servers"] = 10
    for _ in range(10):
        state, _, _ = buy_bot(state)
    assert state["bots"] == 10



# GROUP 6: Server Purchases (071 - 090)
def test_economy_071():
    state = init_game_state(1500)
    state, success, msg = buy_server(state)
    assert success is True
    assert state["servers"] == 2
    assert state["balance"] == 0

def test_economy_072():
    state = init_game_state(500)
    state, success, msg = buy_server(state)
    assert success is False
    assert state["servers"] == 1
    assert state["balance"] == 500

def test_economy_073():
    state = init_game_state(5000)
    state, _, _ = buy_server(state)  # cost 1500 (servers: 2)
    state, _, _ = buy_server(state)  # cost 2250 (servers: 3)
    assert state["servers"] == 3
    assert state["balance"] == 1250

def test_economy_074():
    state = init_game_state(100)
    state, success, msg = buy_server(state)
    assert msg == f"Недостаточно валюты {BASE_CURRENCY}"

def test_economy_075():
    state = init_game_state(10000)
    state["servers"] = 4
    state, success, _ = buy_server(state)  # cost is calculate_server_price(4) = 5062
    assert success is True
    assert state["balance"] == 4938

def test_economy_076():
    state = init_game_state(10000)
    state["servers"] = 4
    state, success, _ = buy_server(state)
    state, success2, _ = buy_server(state)  # cost 7593 -> fails
    assert success2 is False

def test_economy_077():
    state = init_game_state(1500)
    state, success, _ = buy_server(state)
    assert state["servers"] == 2

def test_economy_078():
    state = init_game_state(4000)
    state, _, _ = buy_server(state)
    state, success, _ = buy_server(state)
    assert state["servers"] == 3

def test_economy_079():
    state = init_game_state(3750)
    state, _, _ = buy_server(state)  # 1500 -> balance 2250
    state, success, _ = buy_server(state)  # 2250 -> balance 0
    assert success is True
    assert state["servers"] == 3

def test_economy_080():
    state = init_game_state(3749)
    state, _, _ = buy_server(state)
    state, success, _ = buy_server(state)
    assert success is False

def test_economy_081():
    state = init_game_state(0)
    state, success, _ = buy_server(state)
    assert success is False

def test_economy_082():
    state = init_game_state(100000)
    for _ in range(5):
        state, _, _ = buy_server(state)
    assert state["servers"] == 6

def test_economy_083():
    state = init_game_state(1500)
    state, _, _ = buy_server(state)
    # bot capacity is now 10
    state["balance"] = 10000
    for _ in range(10):
        state, success, _ = buy_bot(state)
        assert success is True
    assert state["bots"] == 10

def test_economy_084():
    state = init_game_state(1500)
    state, _, _ = buy_server(state)
    state["balance"] = 10000
    for _ in range(10):
        state, _, _ = buy_bot(state)
    state, success, _ = buy_bot(state)
    assert success is False

def test_economy_085():
    state = init_game_state(10000)
    state["servers"] = 2
    state, success, _ = buy_server(state)
    assert success is True

def test_economy_086():
    state = init_game_state(2249)
    state["servers"] = 2
    state, success, _ = buy_server(state)
    assert success is False

def test_economy_087():
    state = init_game_state(2250)
    state["servers"] = 2
    state, success, _ = buy_server(state)
    assert success is True

def test_economy_088():
    state = init_game_state(3374)
    state["servers"] = 3
    state, success, _ = buy_server(state)
    assert success is False

def test_economy_089():
    state = init_game_state(3375)
    state["servers"] = 3
    state, success, _ = buy_server(state)
    assert success is True

def test_economy_090():
    state = init_game_state(1000)
    state["servers"] = 0
    state, success, _ = buy_server(state)  # cost 1000
    assert success is True
    assert state["servers"] == 1



# GROUP 7: Feeding and Mental Health (091 - 105)
def test_economy_091():
    state = init_game_state(100)
    state["hunger"] = 50
    state, success, msg = feed_pig(state)
    assert success is True
    assert state["hunger"] == 10
    assert state["balance"] == 50

def test_economy_092():
    state = init_game_state(100)
    state["hunger"] = 20
    state, success, _ = feed_pig(state)
    assert state["hunger"] == 0

def test_economy_093():
    state = init_game_state(10)
    state["hunger"] = 50
    state, success, msg = feed_pig(state)
    assert success is False
    assert state["hunger"] == 50

def test_economy_094():
    state = init_game_state(100)
    state["hunger"] = 0
    state["energy"] = 100
    state, success, _ = feed_pig(state)
    assert success is False

def test_economy_095():
    state = init_game_state(100)
    state["energy"] = 50
    state, success, _ = feed_pig(state)
    assert success is True
    assert state["energy"] == 80

def test_economy_096():
    state = init_game_state(100)
    state["energy"] = 90
    state, success, _ = feed_pig(state)
    assert state["energy"] == 100

def test_economy_097():
    state = init_game_state(200)
    state["sanity"] = 40
    state, success, msg = heal_sanity(state)
    assert success is True
    assert state["sanity"] == 90
    assert state["balance"] == 50

def test_economy_098():
    state = init_game_state(200)
    state["sanity"] = 90
    state, success, _ = heal_sanity(state)
    assert state["sanity"] == 100

def test_economy_099():
    state = init_game_state(10)
    state["sanity"] = 40
    state, success, msg = heal_sanity(state)
    assert success is False
    assert state["sanity"] == 40

def test_economy_100():
    state = init_game_state(200)
    state["sanity"] = 100
    state, success, _ = heal_sanity(state)
    assert success is False

def test_economy_101():
    state = init_game_state(200)
    state["horror_level"] = 5
    state["sanity"] = 50
    state, success, _ = heal_sanity(state)
    assert state["horror_level"] == 3

def test_economy_102():
    state = init_game_state(200)
    state["horror_level"] = 1
    state["sanity"] = 50
    state, success, _ = heal_sanity(state)
    assert state["horror_level"] == 0

def test_economy_103():
    state = init_game_state(500)
    state["hunger"] = 10
    state["energy"] = 50
    state, success, _ = feed_pig(state)
    assert success is True

def test_economy_104():
    state = init_game_state(500)
    state["hunger"] = 10
    state["energy"] = 100
    state, success, _ = feed_pig(state)
    assert success is True
    assert state["hunger"] == 0

def test_economy_105():
    state = init_game_state(0)
    state, success, _ = heal_sanity(state)
    assert success is False



# GROUP 8: Economy ticks and passive updates (106 - 120)
def test_economy_106():
    state = init_game_state(100)
    state["bots"] = 2
    state, income = tick_economy(state, 10)
    assert income == 40  # 2 bots * 2 rate * 10s
    assert state["balance"] == 140

def test_economy_107():
    state = init_game_state(100)
    state["bots"] = 10  # capacity 5
    state, income = tick_economy(state, 10)
    assert income == 100  # 5 bots * 2 rate * 10s
    assert state["balance"] == 200

def test_economy_108():
    state = init_game_state(100)
    state["bots"] = 2
    state, income = tick_economy(state, 0)
    assert income == 0
    assert state["balance"] == 100

def test_economy_109():
    state = init_game_state(100)
    state["bots"] = 2
    state, income = tick_economy(state, -10)
    assert income == 0

def test_economy_110():
    state = init_game_state(100)
    state["hunger"] = 0
    state, _ = tick_economy(state, 10)
    assert state["hunger"] == 1.0

def test_economy_111():
    state = init_game_state(100)
    state["hunger"] = 99
    state, _ = tick_economy(state, 20)
    assert state["hunger"] == 100

def test_economy_112():
    state = init_game_state(100)
    state["hunger"] = 80
    state["energy"] = 50
    state, _ = tick_economy(state, 10)
    assert state["energy"] == 45.0  # starving drain: 0.5/sec * 10

def test_economy_113():
    state = init_game_state(100)
    state["hunger"] = 80
    state["sanity"] = 50
    state, _ = tick_economy(state, 10)
    assert state["sanity"] < 50

def test_economy_114():
    state = init_game_state(100)
    state["hunger"] = 50
    state["energy"] = 50
    state, _ = tick_economy(state, 10)
    assert state["energy"] == 49.0  # normal drain: 0.1/sec * 10

def test_economy_115():
    state = init_game_state(100)
    state["sanity"] = 100
    state, _ = tick_economy(state, 10)
    assert state["sanity"] == 99.5  # decay 0.05/sec * 10

def test_economy_116():
    state = init_game_state(100)
    state["sanity"] = 100
    state["horror_level"] = 4
    state, _ = tick_economy(state, 10)
    assert state["sanity"] == 97.5  # decay 0.05 * (1 + 4) * 10 = 2.5

def test_economy_117():
    state = init_game_state(100)
    state["hunger"] = 90
    state["bots"] = 2
    state, income = tick_economy(state, 10)
    assert income == 20  # efficiency half due to hunger > 80

def test_economy_118():
    state = init_game_state(100)
    state["sanity"] = 10
    state["bots"] = 2
    state, income = tick_economy(state, 10)
    assert income == 60  # efficiency 1.5x due to horror state (sanity < 20)

def test_economy_119():
    state = init_game_state(100)
    state["hunger"] = 90
    state["sanity"] = 10
    state["bots"] = 2
    state, income = tick_economy(state, 10)
    # hunger > 80 -> income = 40 // 2 = 20. Then sanity < 20 -> 20 * 1.5 = 30
    assert income == 30

def test_economy_120():
    state = init_game_state(100)
    state, _ = tick_economy(state, 1000)
    assert state["hunger"] == 100
    assert state["energy"] == 0
    assert state["sanity"] == 0
