import math
from typing import Dict, Any, Tuple

# Const core currency name
BASE_CURRENCY = "Сыроежки"

# Constant configs
BOT_BASE_COST = 100
BOT_COST_MULTIPLIER = 1.15
BOT_INCOME_RATE = 2  # Сыроежки per bot per tick

SERVER_BASE_COST = 1000
SERVER_COST_MULTIPLIER = 1.5
SERVER_BOT_CAPACITY = 5

CLICK_BASE_VALUE = 1
FEED_COST = 50
SANITY_HEAL_COST = 150

def calculate_bot_price(owned_bots: int) -> int:
    """Calculates exponential price of bot based on owned bots."""
    if owned_bots < 0:
        return BOT_BASE_COST
    return int(round(BOT_BASE_COST * (BOT_COST_MULTIPLIER ** owned_bots)))

def calculate_server_price(owned_servers: int) -> int:
    """Calculates exponential price of server based on owned servers."""
    if owned_servers < 0:
        return SERVER_BASE_COST
    return int(round(SERVER_BASE_COST * (SERVER_COST_MULTIPLIER ** owned_servers)))

def init_game_state(balance: int = 500) -> Dict[str, Any]:
    """Initializes new guinea pig state with default variables."""
    return {
        "balance": max(0, balance),
        "currency": BASE_CURRENCY,
        "bots": 0,
        "servers": 1,
        "click_power": 1,
        "hunger": 0,
        "energy": 100,
        "sanity": 100,
        "horror_level": 0,
        "total_clicks": 0,
        "total_earned": 0
    }

def process_click(state: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Processes user manual click, generating currency and consuming energy."""
    if state["energy"] <= 0:
        # Energy exhausted: click is ineffective
        return state, 0
    
    # Calculate horror bonus (sanity modifier)
    multiplier = 1.0
    if state["sanity"] < 30:
        multiplier = 2.0 + (state["horror_level"] * 0.1)
    
    earned = int(state["click_power"] * CLICK_BASE_VALUE * multiplier)
    earned = max(1, earned)
    
    state["balance"] += earned
    state["total_earned"] += earned
    state["total_clicks"] += 1
    
    # Click consumes energy and increases hunger
    state["energy"] = max(0, state["energy"] - 2)
    state["hunger"] = min(100, state["hunger"] + 1)
    
    # Analog horror theme: low sanity increases horror level randomly
    if state["sanity"] < 50 and state["total_clicks"] % 5 == 0:
        state["horror_level"] = min(10, state["horror_level"] + 1)
        
    return state, earned

def buy_bot(state: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
    """Attempts to buy a helper bot to automate currency generation."""
    cost = calculate_bot_price(state["bots"])
    
    # Bug resolved: previously allowed buying bots with insufficient servers
    max_capacity = state["servers"] * SERVER_BOT_CAPACITY
    if state["bots"] >= max_capacity:
        return state, False, "Недостаточно серверов для размещения новых ботов"
        
    if state["balance"] < cost:
        return state, False, f"Недостаточно валюты {BASE_CURRENCY}"
        
    state["balance"] -= cost
    state["bots"] += 1
    return state, True, "Успешно куплен бот"

def buy_server(state: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
    """Attempts to buy a server, expanding bot capacity."""
    cost = calculate_server_price(state["servers"])
    
    if state["balance"] < cost:
        return state, False, f"Недостаточно валюты {BASE_CURRENCY}"
        
    state["balance"] -= cost
    state["servers"] += 1
    return state, True, "Успешно куплен сервер"

def feed_pig(state: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
    """Feeds the guinea pig to reduce hunger and restore energy."""
    if state["balance"] < FEED_COST:
        return state, False, f"Недостаточно валюты {BASE_CURRENCY}"
        
    if state["hunger"] == 0 and state["energy"] == 100:
        return state, False, "Свинка не голодна и полна сил"
        
    state["balance"] -= FEED_COST
    state["hunger"] = max(0, state["hunger"] - 40)
    state["energy"] = min(100, state["energy"] + 30)
    return state, True, "Свинка накормлена"

def heal_sanity(state: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
    """Restores sanity by spending currency on soothing environment."""
    if state["balance"] < SANITY_HEAL_COST:
        return state, False, f"Недостаточно валюты {BASE_CURRENCY}"
        
    if state["sanity"] >= 100:
        return state, False, "Психика полностью стабильна"
        
    state["balance"] -= SANITY_HEAL_COST
    state["sanity"] = min(100, state["sanity"] + 50)
    state["horror_level"] = max(0, state["horror_level"] - 2)
    return state, True, "Психическое здоровье восстановлено"

def tick_economy(state: Dict[str, Any], seconds: int = 1) -> Tuple[Dict[str, Any], int]:
    """Updates game economy state over elapsed seconds (passive income, stats drain)."""
    if seconds <= 0:
        return state, 0
        
    # Calculate bot passive income
    # Bug resolved: previously ignored server limit check during ticks
    active_bots = min(state["bots"], state["servers"] * SERVER_BOT_CAPACITY)
    
    # Passive income formula
    income = active_bots * BOT_INCOME_RATE * seconds
    
    # Efficiency modifier based on sanity and hunger
    # Severe hunger reduces bot efficiency (maintenance neglected by starving guinea pig)
    if state["hunger"] > 80:
        income = income // 2
        
    # Horror multiplier
    if state["sanity"] < 20:
        income = int(income * 1.5)
        
    state["balance"] += income
    state["total_earned"] += income
    
    # Guinea pig physical drain over time
    state["hunger"] = min(100, state["hunger"] + (seconds * 0.1))
    
    # If starving, energy and sanity drain rapidly
    if state["hunger"] > 70:
        state["energy"] = max(0, state["energy"] - (seconds * 0.5))
        state["sanity"] = max(0, state["sanity"] - (seconds * 0.3))
    else:
        # Normal passive drain
        state["energy"] = max(0, state["energy"] - (seconds * 0.1))
        
    # Analog Horror passive sanity decay (accelerates with horror level)
    sanity_decay = 0.05 * (1 + state["horror_level"]) * seconds
    state["sanity"] = max(0, state["sanity"] - sanity_decay)
    
    # Round float values for sanity, hunger, energy
    state["hunger"] = round(state["hunger"], 2)
    state["energy"] = round(state["energy"], 2)
    state["sanity"] = round(state["sanity"], 2)
    
    return state, income
