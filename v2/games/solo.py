"""Одиночные игры против казино. Исход считается только на сервере."""
import math
import secrets
import time
import uuid

from v2 import profile
from v2.conf import RTP
from v2.games import cards as C
from v2.wallet import Ctx, GameError, instant, session

rng = secrets.SystemRandom()

# ───────────────────────── Слоты ─────────────────────────
SLOT_W = {"berry": 10, "acorn": 8, "bell": 6, "gem": 4, "seven": 3, "shroom": 2}
SLOT_3 = {"berry": 6, "acorn": 10, "bell": 20, "gem": 35, "seven": 70, "shroom": 160}
SLOT_PAIR = {"berry": 0.5, "acorn": 1.5, "bell": 2, "gem": 3, "seven": 5}
SLOT_TWO_SHROOMS = 8
SLOT_ONE_SHROOM = 0.5
_slot_bag = [k for k, w in SLOT_W.items() for _ in range(w)]


def slot_pay(line: list) -> tuple[float, str]:
    a, b, c = line
    if a == b == c:
        return SLOT_3[a], "three"
    shrooms = line.count("shroom")
    if shrooms == 2:
        return SLOT_TWO_SHROOMS, "two_shrooms"
    if a == b and a != "shroom":
        return SLOT_PAIR.get(a, 0), "pair"
    if shrooms == 1:
        return SLOT_ONE_SHROOM, "one_shroom"
    return 0, "none"


async def slots(ctx: Ctx, bet: int) -> dict:
    def resolve(data, s):
        reels = [[rng.choice(_slot_bag) for _ in range(3)] for _ in range(3)]
        line = [r[1] for r in reels]
        mult, kind = slot_pay(line)
        ach = ["slots"] if kind == "three" and line[0] == "shroom" else []
        return {"payout": int(bet * mult), "mult": mult, "reels": reels, "kind": kind, "extra": {"ach": ach}}
    return await instant(ctx, "slots", bet, resolve)


# ───────────────────────── Кости ─────────────────────────
DICE_PICKS = {"lo": (15 / 36, "Меньше 7"), "seven": (6 / 36, "Ровно 7"), "hi": (15 / 36, "Больше 7"),
              "double": (6 / 36, "Дубль")}


def dice_mult(pick: str) -> float:
    return math.floor(RTP / DICE_PICKS[pick][0] * 100) / 100


async def dice(ctx: Ctx, bet: int, pick: str) -> dict:
    if pick not in DICE_PICKS:
        raise GameError("Выбери исход.")
    mult = dice_mult(pick)

    def resolve(data, s):
        d1, d2 = rng.randint(1, 6), rng.randint(1, 6)
        total = d1 + d2
        hit = {"lo": total < 7, "seven": total == 7, "hi": total > 7, "double": d1 == d2}[pick]
        return {"payout": int(bet * mult) if hit else 0, "mult": mult if hit else 0, "dice": [d1, d2],
                "sum": total}
    return await instant(ctx, "dice", bet, resolve)


# ───────────────────────── Напёрстки ─────────────────────────
CUPS_MULT = {3: 2.9, 4: 3.85, 5: 4.8}


async def cups(ctx: Ctx, bet: int, count: int, pick: int) -> dict:
    if count not in CUPS_MULT or not 0 <= pick < count:
        raise GameError("Выбери напёрсток.")

    def resolve(data, s):
        ball = rng.randrange(count)
        mult = CUPS_MULT[count] if ball == pick else 0
        return {"payout": int(bet * mult), "mult": mult, "ball": ball,
                "swaps": [rng.sample(range(count), 2) for _ in range(5 + count)]}
    return await instant(ctx, "cups", bet, resolve)


# ───────────────────────── КНБ против ИИ ─────────────────────────
BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
COUNTER = {v: k for k, v in BEATS.items()}
MOVES = tuple(BEATS)
RPS_WIN = 1.94


def rps_predict(history: list) -> tuple[str | None, float]:
    moves = [m for m in history if m in BEATS][-30:]
    if len(moves) < 4:
        return None, 0.0
    last = moves[-1]
    follow = [moves[i + 1] for i in range(len(moves) - 1) if moves[i] == last]
    pool = follow if len(follow) >= 3 else moves
    counts = {m: pool.count(m) for m in MOVES}
    guess = max(counts, key=counts.get)
    return guess, counts[guess] / max(1, len(pool))


async def rps(ctx: Ctx, bet: int, move: str) -> dict:
    if move not in BEATS:
        raise GameError("Камень, ножницы или бумага?")

    def resolve(data, s):
        guess, conf = rps_predict(s["rps"])
        read = max(0.0, min(0.6, (conf - 0.34) * 1.5)) if guess else 0.0
        ai = COUNTER[guess] if guess and rng.random() < read else rng.choice(MOVES)
        s["rps"].append(move)
        del s["rps"][:-30]
        if ai == move:
            payout, outcome = bet, "draw"
        elif BEATS[move] == ai:
            payout, outcome = int(bet * RPS_WIN), "win"
        else:
            payout, outcome = 0, "lose"
        return {"payout": payout, "mult": RPS_WIN if outcome == "win" else (1 if outcome == "draw" else 0),
                "ai": ai, "outcome": outcome, "read": round(conf * 100) if guess else 0}
    return await instant(ctx, "rps", bet, resolve)


# ───────────────────────── Баккара ─────────────────────────
BAC_MULT = {"player": 2.0, "banker": 1.95, "tie": 10.2}   # RTP: 98,8% · 98,9% · 97,3%


def baccarat_deal():
    p, b = [C.draw(), C.draw()], [C.draw(), C.draw()]
    ps, bs = C.bac_score(p), C.bac_score(b)
    if ps < 8 and bs < 8:
        p3 = None
        if ps <= 5:
            p3 = C.draw()
            p.append(p3)
        if p3 is None:
            if bs <= 5:
                b.append(C.draw())
        else:
            v = C.bac_value(p3)
            draw = (bs <= 2 or (bs == 3 and v != 8) or (bs == 4 and 2 <= v <= 7)
                    or (bs == 5 and 4 <= v <= 7) or (bs == 6 and v in (6, 7)))
            if draw:
                b.append(C.draw())
    return p, b, C.bac_score(p), C.bac_score(b)


async def baccarat(ctx: Ctx, bet: int, side: str) -> dict:
    if side not in BAC_MULT:
        raise GameError("Ставка на Игрока, Банкира или Ничью.")

    def resolve(data, s):
        p, b, ps, bs = baccarat_deal()
        result = "tie" if ps == bs else ("player" if ps > bs else "banker")
        if result == side:
            payout = int(bet * BAC_MULT[side])
        elif result == "tie":
            payout = bet  # ставки на игрока/банкира возвращаются при ничьей
        else:
            payout = 0
        return {"payout": payout, "mult": round(payout / bet, 2), "player": p, "banker": b,
                "ps": ps, "bs": bs, "result": result}
    return await instant(ctx, "baccarat", bet, resolve)


# ───────────────────────── Колесо дня ─────────────────────────
WHEEL = [1, 2, 1, 3, 1, 5, 1, 2, 1, 10, 2, 25]


def wheel_base(data: dict, s: dict) -> int:
    level = profile.level_for_xp(int(s.get("xp", 0)))
    base = 150 + 60 * level
    try:
        from prestige import get_prestige_perks
        base = int(base * float(get_prestige_perks(data).get("income_multiplier", 1.0) or 1.0))
    except Exception:
        pass
    return base


async def wheel(ctx: Ctx) -> dict:
    from v2.conf import WHEEL_COOLDOWN
    from v2.wallet import guard, load, save
    from user_manager import get_user_lock
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        await guard(ctx, data, casino=False)
        s = profile.st(data)
        left = int(s.get("wheel", 0) or 0) + WHEEL_COOLDOWN - time.time()
        if left > 0:
            raise GameError(f"Колесо снова закрутится через {int(left // 3600)} ч {int(left % 3600 // 60)} мин.")
        idx = rng.randrange(len(WHEEL))
        prize = wheel_base(data, s) * WHEEL[idx]
        s["wheel"] = int(time.time())
        data["balance"] = int(data.get("balance", 0) or 0) + prize
        save(ctx, data=data)
        return {"index": idx, "prize": prize, "mult": WHEEL[idx], "balance": data["balance"],
                "next": s["wheel"] + WHEEL_COOLDOWN}


# ───────────────────────── Тихая охота (мины) ─────────────────────────
CELLS = 25


def mines_mult(mines: int, picks: int) -> float:
    x = RTP
    for i in range(picks):
        x *= (CELLS - i) / (CELLS - mines - i)
    return math.floor(x * 100) / 100


def _mines_view(st, reveal=False):
    view = {"bet": st["bet"], "mines": st["m"], "open": st["open"], "mult": mines_mult(st["m"], len(st["open"])),
            "next": mines_mult(st["m"], len(st["open"]) + 1) if len(st["open"]) < CELLS - st["m"] else None}
    if reveal:
        view["field"] = st["mines"]
    return view


async def mines_start(ctx: Ctx, bet: int, mines: int) -> dict:
    if not 1 <= mines <= 20:
        raise GameError("Мухоморов: от 1 до 20.")

    def step(data, s, state, flags):
        if state:
            raise GameError("Сначала закончи текущую охоту.")
        st = {"id": uuid.uuid4().hex[:10], "bet": bet, "m": mines, "mines": rng.sample(range(CELLS), mines),
              "open": [], "ts": int(time.time())}
        return {"state": st, "debit": bet, "view": _mines_view(st)}
    return await session(ctx, "mines", step, bet=bet)


async def mines_pick(ctx: Ctx, cell: int) -> dict:
    def step(data, s, st, flags):
        if not st:
            raise GameError("Охота не начата.")
        if not isinstance(cell, int) or not 0 <= cell < CELLS or cell in st["open"]:
            raise GameError("Эта клетка уже открыта.")
        if cell in st["mines"]:
            view = _mines_view(st, True)
            view.update(boom=cell, mult=0)
            return {"state": None, "payout": 0, "wager": st["bet"], "mult": 0,
                    "extra": {"found": len(st["open"])}, "view": view}
        st["open"].append(cell)
        if len(st["open"]) >= CELLS - st["m"]:
            return _mines_cash(st)
        return {"state": st, "view": _mines_view(st)}
    return await session(ctx, "mines", step)


def _mines_cash(st):
    mult = mines_mult(st["m"], len(st["open"]))
    found = len(st["open"])
    ach = ["mines10"] if found >= 10 else []
    view = _mines_view(st, True)
    view.update(cashed=True)
    return {"state": None, "payout": int(st["bet"] * mult), "wager": st["bet"], "mult": mult,
            "extra": {"found": found, "ach": ach}, "view": view}


async def mines_cash(ctx: Ctx) -> dict:
    def step(data, s, st, flags):
        if not st or not st["open"]:
            raise GameError("Найди хотя бы одну сыроежку.")
        return _mines_cash(st)
    return await session(ctx, "mines", step)


# ───────────────────────── Блэкджек ─────────────────────────
def _hand_view(h):
    score, soft = C.bj_score(h["c"])
    return {"cards": h["c"], "bet": h["b"], "score": score, "soft": soft, "done": h["done"], "res": h.get("res"),
            "dbl": h.get("dbl", False)}


def _bj_view(st, reveal=False):
    dealer = st["d"] if reveal else [st["d"][0], "??"]
    dscore = C.bj_score(st["d"])[0] if reveal else C.bj_score([st["d"][0]])[0]
    hand = st["hands"][st["cur"]] if st["cur"] < len(st["hands"]) else None
    can = {}
    if hand and not reveal:
        two = len(hand["c"]) == 2
        can = {"double": two, "split": two and len(st["hands"]) == 1 and hand["c"][0][0] == hand["c"][1][0]}
    return {"hands": [_hand_view(h) for h in st["hands"]], "cur": st["cur"], "dealer": dealer, "dscore": dscore,
            "can": can}


def _bj_finish(st, natural=False):
    """Ход дилера (стоит на всех 17) и расчёт рук."""
    alive = [h for h in st["hands"] if C.bj_score(h["c"])[0] <= 21]
    if alive and not natural:
        while C.bj_score(st["d"])[0] < 17:
            st["d"].append(C.draw())
    d = C.bj_score(st["d"])[0]
    d_bj = C.is_blackjack(st["d"])
    payout = 0
    for h in st["hands"]:
        p = C.bj_score(h["c"])[0]
        p_bj = C.is_blackjack(h["c"]) and len(st["hands"]) == 1
        if p > 21:
            h["res"] = "bust"
        elif p_bj and not d_bj:
            h["res"], amount = "bj", int(h["b"] * 2.5)
            payout += amount
        elif d_bj and not p_bj:
            h["res"] = "lose"
        elif d > 21 or p > d:
            h["res"] = "win"
            payout += h["b"] * 2
        elif p == d:
            h["res"] = "push"
            payout += h["b"]
        else:
            h["res"] = "lose"
        h["done"] = True
    wager = sum(h["b"] for h in st["hands"])
    ach = ["bj"] if any(h.get("res") == "bj" for h in st["hands"]) else []
    view = _bj_view(st, True)
    return {"state": None, "payout": payout, "wager": wager, "mult": round(payout / wager, 2) if wager else 0,
            "extra": {"ach": ach}, "view": view}


def _bj_advance(st):
    while st["cur"] < len(st["hands"]) and st["hands"][st["cur"]]["done"]:
        st["cur"] += 1
    if st["cur"] >= len(st["hands"]):
        return _bj_finish(st)
    return {"state": st, "view": _bj_view(st)}


async def bj_start(ctx: Ctx, bet: int) -> dict:
    def step(data, s, state, flags):
        if state:
            raise GameError("Сначала доиграй текущую раздачу.")
        st = {"id": uuid.uuid4().hex[:10], "hands": [{"c": [C.draw(), C.draw()], "b": bet, "done": False}],
              "d": [C.draw(), C.draw()], "cur": 0, "ts": int(time.time())}
        player_bj = C.is_blackjack(st["hands"][0]["c"])
        dealer_bj = C.is_blackjack(st["d"])  # дилер подсматривает при тузе/десятке
        if player_bj or dealer_bj:
            res = _bj_finish(st, natural=True)
            res["debit"] = bet
            return res
        return {"state": st, "debit": bet, "view": _bj_view(st)}
    return await session(ctx, "bj", step, bet=bet)


async def bj_act(ctx: Ctx, action: str) -> dict:
    def step(data, s, st, flags):
        if not st:
            raise GameError("Раздача не начата.")
        hand = st["hands"][st["cur"]]
        debit = 0
        if action == "hit":
            hand["c"].append(C.draw())
            if C.bj_score(hand["c"])[0] >= 21:
                hand["done"] = True
        elif action == "stand":
            hand["done"] = True
        elif action == "double":
            if len(hand["c"]) != 2:
                raise GameError("Удвоить можно только на двух картах.")
            debit = hand["b"]
            hand["b"] *= 2
            hand["dbl"] = True
            hand["c"].append(C.draw())
            hand["done"] = True
        elif action == "split":
            if len(st["hands"]) != 1 or len(hand["c"]) != 2 or hand["c"][0][0] != hand["c"][1][0]:
                raise GameError("Сплит — только пара одного ранга.")
            debit = hand["b"]
            a, b = hand["c"]
            aces = a[0] == "A"
            st["hands"] = [{"c": [a, C.draw()], "b": hand["b"], "done": aces},
                           {"c": [b, C.draw()], "b": hand["b"], "done": aces}]
            for h in st["hands"]:
                if C.bj_score(h["c"])[0] == 21:
                    h["done"] = True
        else:
            raise GameError("Неизвестное действие.")
        res = _bj_advance(st)
        res["debit"] = debit
        return res
    return await session(ctx, "bj", step)


# ───────────────────────── Видео-покер ─────────────────────────
def _poker_view(st, rank=None, final=False):
    view = {"hand": st["hand"], "bet": st["bet"]}
    rank = rank if rank is not None else C.poker_rank(st["hand"])
    view["rank"] = rank
    view["rank_name"] = C.POKER_PAY[rank][0] if rank else None
    if final:
        view["final"] = True
    return view


async def poker_deal(ctx: Ctx, bet: int) -> dict:
    def step(data, s, state, flags):
        if state:
            raise GameError("Сначала доиграй руку.")
        d = C.deck()
        st = {"id": uuid.uuid4().hex[:10], "bet": bet, "hand": d[:5], "deck": d[5:15], "ts": int(time.time())}
        return {"state": st, "debit": bet, "view": _poker_view(st)}
    return await session(ctx, "poker", step, bet=bet)


async def poker_draw(ctx: Ctx, hold: list) -> dict:
    if not isinstance(hold, list) or len(hold) != 5:
        raise GameError("Выбери карты, которые оставить.")
    keep = [bool(x) for x in hold]

    def step(data, s, st, flags):
        if not st:
            raise GameError("Рука не раздана.")
        deck = list(st["deck"])
        st["hand"] = [c if keep[i] else deck.pop(0) for i, c in enumerate(st["hand"])]
        rank = C.poker_rank(st["hand"])
        mult = C.POKER_PAY[rank][1] if rank else 0
        ach = ["royal"] if rank == "royal" else []
        return {"state": None, "payout": st["bet"] * mult, "wager": st["bet"], "mult": mult,
                "extra": {"ach": ach}, "view": _poker_view(st, rank, True)}
    return await session(ctx, "poker", step)


def active_views(s: dict) -> dict:
    """Незаконченные игры (вернуться после закрытия приложения)."""
    out = {}
    act = s.get("act") or {}
    if act.get("bj"):
        out["bj"] = _bj_view(act["bj"])
    if act.get("mines"):
        out["mines"] = _mines_view(act["mines"])
    if act.get("poker"):
        out["poker"] = _poker_view(act["poker"])
    return out
