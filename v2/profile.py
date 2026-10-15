"""Прогресс V2 внутри профиля игрока: уровень, кешбэк, задания, лига, история.

Данные лежат в user['v2'] и пишутся тем же отложенным сохранением user_manager.
Удалённые записи храним списками или None: Firestore set(merge=True) не удаляет
ключи вложенных словарей.
"""
import math
import random
import time
from datetime import datetime, timezone

from v2.conf import (HISTORY_LEN, RAKE_BASE, RAKE_FACTOR, RAKE_LEVEL_CAP, RAKE_LUCK_POINT, RAKE_MAX,
                     RAKE_PER_LEVEL, RAKE_UNICORN, RAKE_VIP, TZ_OFFSET)

GAME_NAMES = {
    "bj": "Блэкджек", "slots": "Слоты", "roulette": "Рулетка", "crash": "Краш",
    "dice": "Кости", "cups": "Напёрстки", "mines": "Тихая охота", "baccarat": "Баккара",
    "poker": "Видео-покер", "rps": "КНБ с ИИ", "jackpot": "Складчина", "duel": "Дуэль",
    "wheel": "Колесо",
}

TITLES = [
    (1, "Грибной новичок"), (3, "Собиратель"), (5, "Грибник"), (8, "Лесник"),
    (12, "Шулер с опушки"), (16, "Картёжник"), (20, "Крупье"), (25, "Хозяин стола"),
    (30, "Барон поляны"), (40, "Король сыроежек"), (50, "Легенда Казика"),
]

# id, текст, счётчик, цель
TASKS = [
    ("bets10", "Сделай 10 ставок в любых играх", "bets", 10),
    ("wins5", "Выиграй 5 раз в любых играх", "wins", 5),
    ("bj5", "Сыграй 5 раздач в Блэкджек", "g:bj", 5),
    ("bjwin3", "Выиграй 3 раздачи в Блэкджек", "w:bj", 3),
    ("crash3", "Сыграй 3 раунда Краша", "g:crash", 3),
    ("crash2x", "Забери x2 или больше в Краше", "x:crash:2", 1),
    ("mines4", "Найди 4 сыроежки за один заход", "x:mines:4", 1),
    ("roul3", "Поставь в 3 раундах Рулетки", "g:roulette", 3),
    ("slots10", "Крутани Слоты 10 раз", "g:slots", 10),
    ("dice5", "Брось Кости 5 раз", "g:dice", 5),
    ("cups2", "Угадай напёрсток 2 раза", "w:cups", 2),
    ("poker3", "Сыграй 3 руки в Видео-покер", "g:poker", 3),
    ("bacc3", "Сыграй 3 раздачи Баккары", "g:baccarat", 3),
    ("rps2", "Обыграй ИИ в КНБ 2 раза", "w:rps", 2),
    ("x5", "Поймай множитель x5 и выше", "x:any:5", 1),
    ("pvp1", "Сыграй Дуэль или Складчину", "pvp", 1),
]
TASK_BY_ID = {t[0]: t for t in TASKS}

ACHIEVEMENTS = {
    "first": ("Первая ставка", "Сделать первую ставку в V2"),
    "bj": ("Натуральный", "Собрать блэкджек с раздачи"),
    "crash10": ("Ракетчик", "Забрать x10 в Краше"),
    "crash100": ("Космонавт", "Забрать x100 в Краше"),
    "mines10": ("Тихий охотник", "Найти 10 сыроежек за заход"),
    "royal": ("Роял-флеш", "Собрать роял-флеш"),
    "zero": ("Зеро", "Выиграть ставкой на 0"),
    "slots": ("Сыроежечный джекпот", "Три сыроежки в слотах"),
    "pot": ("Сорвал куш", "Выиграть Складчину"),
    "duel10": ("Дуэлянт", "Выиграть 10 дуэлей"),
    "million": ("Миллион за раз", "Выиграть 1 000 000+ одной ставкой"),
    "streak7": ("На раздаче", "7 побед подряд"),
    "lvl10": ("Свой человек", "Достичь 10 уровня"),
    "tasks": ("Работяга", "Закрыть все задания дня"),
}


def now() -> float:
    return time.time()


def day_key(ts: float | None = None) -> str:
    ts = now() if ts is None else ts
    return datetime.fromtimestamp(ts + TZ_OFFSET, tz=timezone.utc).strftime("%Y-%m-%d")


def week_key(ts: float | None = None) -> str:
    ts = now() if ts is None else ts
    y, w, _ = datetime.fromtimestamp(ts + TZ_OFFSET, tz=timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def week_ends_at(ts: float | None = None) -> int:
    ts = now() if ts is None else ts
    local = datetime.fromtimestamp(ts + TZ_OFFSET, tz=timezone.utc)
    start_of_day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    days_left = 7 - local.weekday()
    return int(start_of_day.timestamp() + days_left * 86400 - TZ_OFFSET)


def xp_for_level(level: int) -> int:
    level = max(1, int(level))
    return int(60 * (level - 1) ** 1.6 + 40 * (level - 1))


def level_for_xp(xp: int) -> int:
    level = 1
    while level < 99 and xp >= xp_for_level(level + 1):
        level += 1
    return level


def title_for(level: int) -> str:
    title = TITLES[0][1]
    for need, name in TITLES:
        if level >= need:
            title = name
    return title


def st(data: dict) -> dict:
    """Нормализованное состояние V2 (создаёт недостающие поля)."""
    s = data.get("v2")
    if not isinstance(s, dict):
        s = {}
        data["v2"] = s
    s.setdefault("xp", 0)
    s.setdefault("stats", {})
    for k in ("n", "w", "wag", "won", "best", "streak", "bstreak", "duels_won"):
        s["stats"].setdefault(k, 0)
    s["stats"].setdefault("bestx", 0.0)
    if not isinstance(s.get("games"), dict):
        s["games"] = {}
    s.setdefault("rake", 0)
    s.setdefault("rake_total", 0)
    if not isinstance(s.get("day"), dict):
        s["day"] = {}
    for k in ("hist", "pend", "ach", "rps", "tasks"):
        if not isinstance(s.get(k), list):
            s[k] = []
    if not isinstance(s.get("act"), dict):
        s["act"] = {}
    s.setdefault("wheel", 0)
    return s


def level_info(s: dict) -> dict:
    xp = int(s.get("xp", 0) or 0)
    level = level_for_xp(xp)
    lo, hi = xp_for_level(level), xp_for_level(level + 1)
    return {"level": level, "title": title_for(level), "xp": xp, "xp_lo": lo, "xp_hi": hi}


def rake_rate(data: dict, s: dict, pet_ok: bool = True) -> float:
    level = level_for_xp(int(s.get("xp", 0) or 0))
    rate = RAKE_BASE + min(level, RAKE_LEVEL_CAP) * RAKE_PER_LEVEL
    if data.get("is_vip"):
        rate += RAKE_VIP
    pet = data.get("pet") if isinstance(data.get("pet"), dict) else {}
    if pet_ok and pet.get("id") == "unicorn":
        rate += RAKE_UNICORN
    try:
        from prestige import get_prestige_perks
        rate += int(get_prestige_perks(data).get("luck_bonus", 0) or 0) * RAKE_LUCK_POINT
    except Exception:
        pass
    return min(rate, RAKE_MAX)


def ensure_day(s: dict, uid: int) -> dict:
    today = day_key()
    day = s["day"]
    if day.get("k") != today:
        rng = random.Random(f"{today}:{uid}")
        picks = rng.sample(TASKS, 3)
        day.clear()
        day.update({"k": today, "q": 0, "bets": 0})
        s["tasks"] = [{"id": t[0], "p": 0, "c": False} for t in picks]
    return day


def tasks_view(s: dict, uid: int, level: int) -> list:
    ensure_day(s, uid)
    out = []
    for t in s["tasks"]:
        spec = TASK_BY_ID.get(t.get("id"))
        if not spec:
            continue
        out.append({"id": spec[0], "text": spec[1], "goal": spec[3], "p": min(int(t.get("p", 0)), spec[3]),
                    "claimed": bool(t.get("c")), "reward": task_reward(level)})
    return out


def task_reward(level: int) -> int:
    return int(400 + 150 * max(1, level) ** 1.15)


def _bump_tasks(s: dict, counters: dict):
    for t in s["tasks"]:
        spec = TASK_BY_ID.get(t.get("id"))
        if spec and not t.get("c"):
            t["p"] = min(spec[3], int(t.get("p", 0)) + int(counters.get(spec[2], 0)))


def award(s: dict, ach: str, events: list):
    if ach in ACHIEVEMENTS and ach not in s["ach"]:
        s["ach"].append(ach)
        s["xp"] = int(s.get("xp", 0)) + 150
        events.append({"type": "ach", "id": ach, "name": ACHIEVEMENTS[ach][0]})


def record_bet(data: dict, uid: int, gid: str, bet: int, payout: int, *, mult: float | None = None,
               pet_ok: bool = True, xp_frozen: bool = False, extra: dict | None = None,
               season_xp: float = 1.0) -> dict:
    """Учёт сыгранной ставки. Возвращает события для клиента (уровень, ачивки)."""
    s = st(data)
    events: list = []
    day = ensure_day(s, uid)
    bet, payout = int(bet), int(payout)
    win = payout > bet
    if mult is None:
        mult = round(payout / bet, 2) if bet else 0.0

    stats = s["stats"]
    stats["n"] += 1
    stats["wag"] += bet
    stats["won"] += payout
    if win:
        stats["w"] += 1
        stats["streak"] += 1
        stats["bstreak"] = max(stats["bstreak"], stats["streak"])
        stats["best"] = max(stats["best"], payout - bet)
        stats["bestx"] = max(float(stats.get("bestx", 0) or 0), float(mult))
    elif payout < bet:
        stats["streak"] = 0
    g = s["games"].setdefault(gid, {"n": 0, "w": 0, "wag": 0, "won": 0})
    g["n"] += 1
    g["w"] += 1 if win else 0
    g["wag"] += bet
    g["won"] += payout

    # Кешбэк копится от оборота и забирается кнопкой.
    rake = int(bet * rake_rate(data, s, pet_ok) * RAKE_FACTOR.get(gid, 1.0))
    s["rake"] = int(s.get("rake", 0)) + rake

    level_before = level_for_xp(int(s["xp"]))
    if not xp_frozen:
        gain = 2 + 2 * math.log10(max(bet, 10))
        if win:
            gain *= 1.5
        s["xp"] = int(s["xp"]) + max(3, int(round(gain * season_xp)))
    level_after = level_for_xp(int(s["xp"]))
    if level_after > level_before:
        events.append({"type": "level", "level": level_after, "title": title_for(level_after)})
        if level_after >= 10:
            award(s, "lvl10", events)

    # Задания дня
    balance = int(data.get("balance", 0) or 0)
    day["bets"] = int(day.get("bets", 0)) + 1
    if bet >= max(100, int((balance + bet - payout) * 0.001)):
        day["q"] = int(day.get("q", 0)) + 1
    counters = {"bets": 1, f"g:{gid}": 1}
    if win:
        counters["wins"] = 1
        counters[f"w:{gid}"] = 1
    if gid in ("duel", "jackpot"):
        counters["pvp"] = 1
    for spec in TASKS:
        key = spec[2]
        if not key.startswith("x:"):
            continue
        _, game, need = key.split(":")
        if game == "mines":
            value = float((extra or {}).get("found", 0)) if gid == "mines" else 0.0
        else:
            value = float(mult) if win and game in (gid, "any") else 0.0
        if value >= float(need):
            counters[key] = 1
    _bump_tasks(s, counters)

    award(s, "first", events)
    if stats["streak"] >= 7:
        award(s, "streak7", events)
    if win and payout - bet >= 1_000_000:
        award(s, "million", events)
    for ach in (extra or {}).get("ach", ()):
        award(s, ach, events)

    s["hist"].append([int(now()), gid, bet, payout, round(float(mult), 2)])
    del s["hist"][:-HISTORY_LEN]
    return {"events": events, "rake": rake, "win": win}


def history_view(s: dict) -> list:
    out = []
    for row in reversed(s.get("hist", [])):
        if isinstance(row, list) and len(row) >= 5:
            out.append({"ts": row[0], "g": row[1], "name": GAME_NAMES.get(row[1], row[1]),
                        "bet": row[2], "pay": row[3], "x": row[4]})
    return out
