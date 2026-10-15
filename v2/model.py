"""Pure balancing rules. All amounts are integer game currency, never real money."""
import hashlib

CAREERS = {
    "courier": ("🚲 Курьер", 240, 400),
    "mechanic": ("🔧 Механик", 260, 440),
    "analyst": ("💻 Аналитик", 280, 480),
}
CAREER_ENERGY = {"courier": 8, "mechanic": 12, "analyst": 16}
TOOL_BONUS = {"courier": 20, "mechanic": 60, "analyst": 35}
CRIMES = {
    "pickpocket": ("🪙 Карманная кража", 0.78, 300, 650, 12, 150),
    "burglary": ("🏠 Взлом склада", 0.57, 650, 1250, 24, 300),
    "convoy": ("🚚 Налёт на конвой", 0.38, 1200, 2100, 38, 550),
}
RESOURCES = {
    "mushroom": ("🍄 Грибы", 42, 3, 7),
    "fish": ("🐟 Рыба", 72, 2, 5),
    "ore": ("⛏ Руда", 105, 1, 4),
}
EVENTS = (
    ("Тихий день", None, 1.0),
    ("Грибной дождь: грибы дороже на 25%", "mushroom", 1.25),
    ("Рыбная ярмарка: рыба дороже на 25%", "fish", 1.25),
    ("Стройка века: руда дороже на 25%", "ore", 1.25),
)
WORK_COOLDOWN = 1800
CRIME_COOLDOWN = 3600
STEAL_COOLDOWN = 3600
GATHER_COOLDOWN = 1200


class RuleError(Exception):
    """Expected player-facing rule violation."""


def level(xp):
    return min(20, max(0, int(xp)) // 100 + 1)


def event(chat_id, now):
    index = int.from_bytes(hashlib.sha256(f"{chat_id}:{int(now) // 86400}".encode()).digest()[:4], "big")
    return EVENTS[index % len(EVENTS)]


def market_price(chat_id, resource, now):
    _, base, _, _ = RESOURCES[resource]
    # Price changes daily, cannot be rerolled by a restart. Selling never mints items.
    seed = hashlib.sha256(f"{chat_id}:{resource}:{int(now) // 86400}".encode()).digest()[0]
    _, boosted, multiplier = event(chat_id, now)
    return max(1, int(base * (0.85 + seed / 255 * 0.3) * (multiplier if boosted == resource else 1)))


def state(data, now):
    s = data.setdefault("economy_v2", {})
    defaults = {
        "joined": now, "energy": 100, "energy_at": now,
        "heat": 0, "heat_at": now, "jail_until": 0,
        "career": "courier", "xp": {}, "tools": 0,
        "resources": {}, "streak": 0, "daily_day": -1,
        "shield_until": 0, "last_victim_at": 0, "actions": {},
        "quest_day": -1, "quests": {}, "quest_claimed": False,
        "income": 0, "spent": 0,
    }
    for key, value in defaults.items():
        s.setdefault(key, value.copy() if isinstance(value, dict) else value)
    ticks = max(0, int((now - s["energy_at"]) // 600))
    if ticks:
        s["energy"] = min(100, s["energy"] + ticks * 5)
        s["energy_at"] += ticks * 600
    heat_ticks = max(0, int((now - s["heat_at"]) // 450))
    if heat_ticks:
        s["heat"] = max(0, s["heat"] - heat_ticks)
        s["heat_at"] += heat_ticks * 450
    day = int(now) // 86400
    if s["quest_day"] != day:
        s.update(quest_day=day, quests={}, quest_claimed=False)
    return s


def cooldown(last, duration, now):
    left = int(last + duration - now)
    if last and left > 0:
        raise RuleError(f"⏳ Повторить можно через {(left + 59) // 60} мин.")


def active(s, now, cost=0):
    if s["jail_until"] > now:
        raise RuleError(f"🚔 Ты под арестом ещё {int((s['jail_until'] - now + 59) // 60)} мин. /bail — залог.")
    if s["energy"] < cost:
        raise RuleError(f"⚡ Нужно {cost} энергии, сейчас {s['energy']}. +5 каждые 10 минут; /rest — отдых.")
    s["energy"] -= cost


def spend(data, s, amount):
    if amount <= 0 or data.get("balance", 0) < amount:
        raise RuleError(f"💸 Нужно {amount} сыроежек на балансе.")
    data["balance"] -= amount
    s["spent"] += amount


def credit(data, s, amount):
    amount = max(0, int(amount))
    data["balance"] = int(data.get("balance", 0)) + amount
    s["income"] += amount
    return amount


def progress(s, key):
    s["quests"][key] = s["quests"].get(key, 0) + 1


def experience(s, key, amount):
    s["xp"][key] = s["xp"].get(key, 0) + amount
    return level(s["xp"][key])
