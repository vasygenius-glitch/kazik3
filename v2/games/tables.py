"""Общие столы чата: Краш, Рулетка, Складчина и Дуэли.

Все видят один раунд: ставки других игроков (аватар + имя), один множитель,
одно вращение. Состояние в памяти; ставки в v2.pend профиля — после рестарта
незакрытые ставки возвращаются автоматически.
"""
import asyncio
import logging
import math
import secrets
import time
import uuid
from collections import deque

from v2 import live, profile
from v2.conf import DUEL_TTL, MAX_BET, PVP_FEE, RTP
from v2.wallet import Ctx, GameError, register_live, settle, stake, unregister_live

log = logging.getLogger(__name__)
rng = secrets.SystemRandom()
VIEW_GRACE = 20


def _clan(data_clan):
    return data_clan if isinstance(data_clan, str) else None


async def _result(hub, uid, name, handle, gid, wager, payout, mult, events, clan=None):
    live.result(hub, uid, name, handle, clan, gid, wager, payout, mult, events)


# ───────────────────────── Краш ─────────────────────────
GROWTH = 0.07
CRASH_MAX = 1000.0


def crash_point() -> float:
    """P(точка ≥ x) = RTP / x: любая цель автовывода возвращает ровно RTP (~4% раундов — сразу x1.00)."""
    u = 1.0 - rng.random()
    return min(CRASH_MAX, max(1.0, math.floor(RTP / u * 100) / 100))


def crash_mult(elapsed: float) -> float:
    return math.floor(math.exp(GROWTH * max(0.0, elapsed)) * 100) / 100


class CrashTable:
    BET_TIME = 7.0
    END_TIME = 4.0

    def __init__(self, hub):
        self.hub = hub
        self.phase = "idle"
        self.rid = ""
        self.t_bet_end = self.t_start = self.t_crash = self.t_end = 0.0
        self.point = 1.0
        self.bets: dict[int, dict] = {}
        self.history: deque = deque(maxlen=16)
        self.viewed = 0.0

    def ping(self):
        self.viewed = time.time()

    def _new_round(self, now):
        self.rid = f"crash:{uuid.uuid4().hex[:10]}"
        self.phase, self.bets = "bet", {}
        self.t_bet_end = now + self.BET_TIME
        self.point = crash_point()
        register_live(self.rid)

    async def tick(self, now):
        watched = now - self.viewed < VIEW_GRACE
        if self.phase == "idle":
            if watched:
                self._new_round(now)
        elif self.phase == "bet" and now >= self.t_bet_end:
            if not self.bets and not watched:
                unregister_live(self.rid)
                self.phase = "idle"
                return
            self.phase, self.t_start = "run", now
            self.t_crash = now + math.log(self.point) / GROWTH
        elif self.phase == "run":
            m = crash_mult(now - self.t_start)
            for uid, b in list(self.bets.items()):
                if b["cash"] is None and b["auto"] and b["auto"] <= self.point and m >= b["auto"]:
                    await self._cash(uid, b, b["auto"])
            if now >= self.t_crash:
                self.phase, self.t_end = "end", now + self.END_TIME
                self.history.appendleft(self.point)
                for uid, b in list(self.bets.items()):
                    # Автовывод ровно на точке краша засчитывается (погрешность float не должна съедать выигрыш).
                    if b["cash"] is None and b["auto"] and b["auto"] <= self.point:
                        await self._cash(uid, b, b["auto"])
                    if b["cash"] is None:
                        b["lost"] = True
                        res = await settle(self.hub.chat_id, uid, b["name"], "crash", self.rid, b["amount"], 0, mult=0)
                        await _result(self.hub, uid, b["name"], b["h"], "crash", b["amount"], 0, 0,
                                      res.get("events"), b.get("clan"))
                unregister_live(self.rid)
        elif self.phase == "end" and now >= self.t_end:
            if watched:
                self._new_round(now)
            else:
                self.phase = "idle"

    async def _cash(self, uid, b, m):
        b["cash"] = m
        payout = int(b["amount"] * m)
        b["payout"] = payout
        ach = ["crash100"] if m >= 100 else (["crash10"] if m >= 10 else [])
        res = await settle(self.hub.chat_id, uid, b["name"], "crash", self.rid, b["amount"], payout, mult=m,
                           extra={"ach": ach})
        b["events"] = res.get("events", [])
        await _result(self.hub, uid, b["name"], b["h"], "crash", b["amount"], payout, m, b["events"], b.get("clan"))
        return res

    async def bet(self, ctx: Ctx, amount: int, auto: float | None, clan=None):
        if self.phase != "bet":
            raise GameError("Ставки принимаются до взлёта. Дождись следующего раунда.")
        if ctx.uid in self.bets:
            raise GameError("Ты уже в этом раунде.")
        if auto is not None and not 1.01 <= auto <= CRASH_MAX:
            raise GameError("Автовывод: от x1.01 до x1000.")
        rid = self.rid
        balance = await stake(ctx, "crash", amount, rid)
        if self.rid != rid or self.phase != "bet":
            await settle(self.hub.chat_id, ctx.uid, ctx.name, "crash", rid, 0, amount, record=False)
            raise GameError("Раунд уже стартовал — ставка возвращена.")
        self.bets[ctx.uid] = {"h": ctx.handle, "name": ctx.name, "amount": amount, "auto": auto, "cash": None,
                              "payout": 0, "lost": False, "clan": clan}
        return balance

    async def cashout(self, ctx: Ctx):
        b = self.bets.get(ctx.uid)
        if self.phase != "run" or not b or b["cash"] is not None:
            raise GameError("Нечего забирать.")
        now = time.time()
        if now >= self.t_crash:
            raise GameError("Поздно — улетело!")
        res = await self._cash(ctx.uid, b, crash_mult(now - self.t_start))
        return {"cash": b["cash"], "payout": b["payout"], "balance": res["balance"], "events": res.get("events", [])}

    def view(self, uid):
        v = {"phase": self.phase, "rid": self.rid, "bet_end": self.t_bet_end, "start": self.t_start,
             "growth": GROWTH, "history": list(self.history),
             "bets": [{"h": b["h"], "name": b["name"], "amount": b["amount"], "cash": b["cash"],
                       "payout": b["payout"], "lost": b["lost"]} for b in self.bets.values()]}
        if self.phase == "end":
            v["point"] = self.point
        mine = self.bets.get(uid)
        if mine:
            v["me"] = {"amount": mine["amount"], "auto": mine["auto"], "cash": mine["cash"],
                       "payout": mine["payout"], "lost": mine["lost"]}
        return v


# ───────────────────────── Рулетка ─────────────────────────
RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14,
               31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
ROUL_KINDS = {"n", "red", "black", "odd", "even", "low", "high", "dozen", "col"}


def roulette_mult(kind: str, value, n: int) -> int:
    if kind == "n":
        return 36 if n == value else 0
    if n == 0:
        return 0
    return {
        "red": 2 if n in RED else 0,
        "black": 2 if n not in RED else 0,
        "odd": 2 if n % 2 else 0,
        "even": 0 if n % 2 else 2,
        "low": 2 if n <= 18 else 0,
        "high": 2 if n >= 19 else 0,
        "dozen": 3 if (n - 1) // 12 + 1 == value else 0,
        "col": 3 if (n - 1) % 3 + 1 == value else 0,
    }.get(kind, 0)


def validate_roulette_bet(kind, value):
    if kind not in ROUL_KINDS:
        raise GameError("Неизвестная ставка.")
    if kind == "n" and not (isinstance(value, int) and 0 <= value <= 36):
        raise GameError("Число от 0 до 36.")
    if kind in ("dozen", "col") and value not in (1, 2, 3):
        raise GameError("Дюжина/колонка: 1, 2 или 3.")


class RouletteTable:
    BET_TIME = 18.0
    SPIN_TIME = 7.0
    SHOW_TIME = 5.0

    def __init__(self, hub):
        self.hub = hub
        self.phase = "idle"
        self.rid = ""
        self.t_next = 0.0
        self.result = None
        self.bets: dict[int, dict] = {}
        self.history: deque = deque(maxlen=14)
        self.viewed = 0.0

    def ping(self):
        self.viewed = time.time()

    def _new_round(self, now):
        self.rid = f"roul:{uuid.uuid4().hex[:10]}"
        self.phase, self.t_next, self.bets, self.result = "bet", now + self.BET_TIME, {}, None
        register_live(self.rid)

    async def tick(self, now):
        watched = now - self.viewed < VIEW_GRACE
        if self.phase == "idle":
            if watched:
                self._new_round(now)
        elif self.phase == "bet" and now >= self.t_next:
            if not self.bets and not watched:
                unregister_live(self.rid)
                self.phase = "idle"
                return
            self.result = rng.randrange(37)
            self.phase, self.t_next = "spin", now + self.SPIN_TIME
        elif self.phase == "spin" and now >= self.t_next:
            n = self.result
            self.history.appendleft(n)
            for uid, b in list(self.bets.items()):
                wager = sum(x["amount"] for x in b["list"])
                payout = sum(x["amount"] * roulette_mult(x["kind"], x.get("value"), n) for x in b["list"])
                b["payout"] = payout
                ach = ["zero"] if n == 0 and any(x["kind"] == "n" and x.get("value") == 0 for x in b["list"]) else []
                mult = round(payout / wager, 2) if wager else 0
                res = await settle(self.hub.chat_id, uid, b["name"], "roulette", f"{self.rid}:{uid}", wager, payout,
                                   mult=mult, extra={"ach": ach})
                b["events"] = res.get("events", [])
                await _result(self.hub, uid, b["name"], b["h"], "roulette", wager, payout, mult, b["events"],
                              b.get("clan"))
            unregister_live(self.rid)
            self.phase, self.t_next = "show", now + self.SHOW_TIME
        elif self.phase == "show" and now >= self.t_next:
            if watched:
                self._new_round(now)
            else:
                self.phase = "idle"

    async def bet(self, ctx: Ctx, kind: str, value, amount: int, clan=None):
        validate_roulette_bet(kind, value)
        if self.phase != "bet":
            raise GameError("Ставки закрыты — шарик уже крутится.")
        rid = self.rid
        mine = self.bets.get(ctx.uid)
        total = sum(x["amount"] for x in mine["list"]) if mine else 0
        if total + amount > MAX_BET:
            raise GameError("Лимит ставок на раунд исчерпан.")
        if mine and len(mine["list"]) >= 30:
            raise GameError("Слишком много фишек на столе.")
        balance = await stake(ctx, "roulette", amount, f"{rid}:{ctx.uid}")
        if self.rid != rid or self.phase != "bet":
            await settle(self.hub.chat_id, ctx.uid, ctx.name, "roulette", f"{rid}:{ctx.uid}", 0, amount,
                         record=False)
            raise GameError("Не успел — ставка возвращена.")
        b = self.bets.setdefault(ctx.uid, {"h": ctx.handle, "name": ctx.name, "list": [], "payout": 0,
                                           "clan": clan})
        b["list"].append({"kind": kind, "value": value, "amount": amount})
        return balance

    def view(self, uid):
        v = {"phase": self.phase, "rid": self.rid, "t_next": self.t_next, "history": list(self.history),
             "order": WHEEL_ORDER,
             "bets": [{"h": b["h"], "name": b["name"], "total": sum(x["amount"] for x in b["list"]),
                       "chips": [[x["kind"], x.get("value"), x["amount"]] for x in b["list"]][-12:],
                       "payout": b["payout"] if self.phase == "show" else None} for b in self.bets.values()]}
        if self.phase in ("spin", "show"):
            v["result"] = self.result
            v["spin_end"] = self.t_next if self.phase == "spin" else None
        mine = self.bets.get(uid)
        if mine:
            v["me"] = {"list": [[x["kind"], x.get("value"), x["amount"]] for x in mine["list"]],
                       "payout": mine["payout"] if self.phase == "show" else None}
        return v


# ───────────────────────── Складчина (джекпот) ─────────────────────────
class JackpotTable:
    COUNT_TIME = 30.0
    DRAW_TIME = 7.0
    DONE_TIME = 6.0
    ALONE_TIMEOUT = 600.0
    MAX_PLAYERS = 20

    def __init__(self, hub):
        self.hub = hub
        self.history: deque = deque(maxlen=10)
        self._reset()

    def _reset(self):
        self.phase = "open"
        self.rid = f"pot:{uuid.uuid4().hex[:10]}"
        self.t_next = 0.0
        self.t_open = time.time()
        self.bets: dict[int, dict] = {}
        self.winner = None
        self.ticket = 0.0
        self.prize = 0
        register_live(self.rid)

    def ping(self):
        pass

    @property
    def total(self):
        return sum(b["amount"] for b in self.bets.values())

    async def tick(self, now):
        if self.phase == "open":
            if len(self.bets) == 1 and now - self.t_open > self.ALONE_TIMEOUT:
                for uid, b in list(self.bets.items()):
                    await settle(self.hub.chat_id, uid, b["name"], "jackpot", f"{self.rid}:{uid}", 0, b["amount"],
                                 record=False)
                unregister_live(self.rid)
                self._reset()
        elif self.phase == "count" and now >= self.t_next:
            total = self.total
            self.ticket = rng.random() * total
            acc = 0
            for uid, b in self.bets.items():
                acc += b["amount"]
                if self.ticket < acc:
                    self.winner = uid
                    break
            if self.winner is None:
                self.winner = next(iter(self.bets))
            fee = int(total * PVP_FEE)
            self.prize = total - fee
            self.hub.add_pool(fee)
            self.phase, self.t_next = "draw", now + self.DRAW_TIME
        elif self.phase == "draw" and now >= self.t_next:
            total = self.total
            for uid, b in list(self.bets.items()):
                payout = self.prize if uid == self.winner else 0
                mult = round(payout / b["amount"], 2) if payout else 0
                res = await settle(self.hub.chat_id, uid, b["name"], "jackpot", f"{self.rid}:{uid}", b["amount"],
                                   payout, mult=mult, extra={"ach": ["pot"] if payout else []}, flush=bool(payout))
                if payout:
                    await _result(self.hub, uid, b["name"], b["h"], "jackpot", b["amount"], payout, mult,
                                  res.get("events"), b.get("clan"))
                    if total >= 10_000:
                        self.hub.queue_announce(
                            f"🍯 <b>{live.html.escape(b['name'])}</b> забрал(а) Складчину: "
                            f"<b>{live.fmt(payout)}</b> сыроежек (шанс был {b['amount'] * 100 // max(1, total)}%)!")
                else:
                    self.hub.add_result(uid, b["name"], b["h"], b.get("clan"), b["amount"], 0)
            w = self.bets.get(self.winner, {})
            self.history.appendleft({"name": w.get("name"), "h": w.get("h"), "prize": self.prize, "total": total})
            unregister_live(self.rid)
            self.phase, self.t_next = "done", now + self.DONE_TIME
        elif self.phase == "done" and now >= self.t_next:
            self._reset()

    async def bet(self, ctx: Ctx, amount: int, clan=None):
        if self.phase not in ("open", "count"):
            raise GameError("Идёт розыгрыш — подожди следующую складчину.")
        if ctx.uid not in self.bets and len(self.bets) >= self.MAX_PLAYERS:
            raise GameError("В складчине уже 20 человек.")
        mine = self.bets.get(ctx.uid)
        if (mine["amount"] if mine else 0) + amount > MAX_BET:
            raise GameError("Лимит вклада исчерпан.")
        rid = self.rid
        balance = await stake(ctx, "jackpot", amount, f"{rid}:{ctx.uid}")
        if self.rid != rid or self.phase not in ("open", "count"):
            await settle(self.hub.chat_id, ctx.uid, ctx.name, "jackpot", f"{rid}:{ctx.uid}", 0, amount, record=False)
            raise GameError("Розыгрыш уже начался — вклад возвращён.")
        b = self.bets.setdefault(ctx.uid, {"h": ctx.handle, "name": ctx.name, "amount": 0, "clan": clan})
        b["amount"] += amount
        if self.phase == "open" and len(self.bets) >= 2:
            self.phase, self.t_next = "count", time.time() + self.COUNT_TIME
        if len(self.bets) == 1:
            self.t_open = time.time()
            self.hub.push("pot", ctx.name, ctx.handle, "открыл(а) Складчину — заходи!", amount, 0, "jackpot")
        return balance

    def view(self, uid):
        total = self.total
        v = {"phase": self.phase, "rid": self.rid, "t_next": self.t_next, "total": total, "history": list(self.history),
             "players": [{"h": b["h"], "name": b["name"], "amount": b["amount"],
                          "share": round(b["amount"] / total, 4) if total else 0} for b in self.bets.values()]}
        if self.phase in ("draw", "done"):
            w = self.bets.get(self.winner, {})
            v.update(winner={"h": w.get("h"), "name": w.get("name")}, ticket=self.ticket / total if total else 0,
                     prize=self.prize)
        if uid in self.bets:
            v["me"] = {"amount": self.bets[uid]["amount"]}
        return v


# ───────────────────────── Дуэли ─────────────────────────
async def duel_create(hub, ctx: Ctx, amount: int, target_uid: int | None, target_name: str = "", clan=None):
    mine = [d for d in hub.duels.values() if d["state"] == "open" and d["uid"] == ctx.uid]
    if len(mine) >= 3:
        raise GameError("У тебя уже 3 открытых вызова.")
    if target_uid == ctx.uid:
        raise GameError("С собой дуэль не устроить.")
    did = uuid.uuid4().hex[:8]
    ref = f"duel:{did}:{ctx.uid}"
    register_live(ref)
    try:
        balance = await stake(ctx, "duel", amount, ref)
    except Exception:
        unregister_live(ref)
        raise
    hub.duels[did] = {"id": did, "uid": ctx.uid, "h": ctx.handle, "name": ctx.name, "amount": amount,
                      "target": target_uid, "target_name": target_name, "state": "open", "ts": time.time(),
                      "expires": time.time() + DUEL_TTL, "clan": clan}
    who = f" против {target_name}" if target_name else ""
    hub.push("duel", ctx.name, ctx.handle, f"бросил(а) вызов на дуэль{who}", amount, 0, "duel")
    return {"id": did, "balance": balance}


async def duel_accept(hub, ctx: Ctx, did: str, clan=None):
    d = hub.duels.get(did)
    if not d or d["state"] != "open":
        raise GameError("Вызов уже неактуален.")
    if d["uid"] == ctx.uid:
        raise GameError("Это твой вызов.")
    if d["target"] and d["target"] != ctx.uid:
        raise GameError("Этот вызов адресован другому игроку.")
    d["state"] = "busy"
    ref = f"duel:{did}:{ctx.uid}"
    register_live(ref)
    try:
        await stake(ctx, "duel", d["amount"], ref)
    except Exception:
        unregister_live(ref)
        d["state"] = "open"
        raise
    amount = d["amount"]
    first_wins = rng.random() < 0.5
    winner, loser = ((d["uid"], d["name"], d["h"], d.get("clan"), f"duel:{did}:{d['uid']}"),
                     (ctx.uid, ctx.name, ctx.handle, clan, ref))
    if not first_wins:
        winner, loser = loser, winner
    fee = int(amount * 2 * PVP_FEE)
    prize = amount * 2 - fee
    hub.add_pool(fee)
    rw = await settle(hub.chat_id, winner[0], winner[1], "duel", winner[4], amount, prize, mult=round(prize / amount, 2),
                      flush=True)
    rl = await settle(hub.chat_id, loser[0], loser[1], "duel", loser[4], amount, 0, mult=0)
    unregister_live(winner[4])
    unregister_live(loser[4])
    await _bump_duel_wins(hub.chat_id, winner[0])
    d.update(state="done", opp_h=ctx.handle, opp_name=ctx.name, winner_h=winner[2], winner_name=winner[1],
             side="heads" if first_wins else "tails", prize=prize, done_ts=time.time())
    live.result(hub, winner[0], winner[1], winner[2], winner[3], "duel", amount, prize, round(prize / amount, 2),
                rw.get("events"))
    hub.add_result(loser[0], loser[1], loser[2], loser[3], amount, 0)
    hub.push("win", winner[1], winner[2], f"победил(а) в дуэли против {loser[1]}", prize - amount, 0, "duel")
    if amount >= 100_000:
        hub.queue_announce(f"⚔️ Дуэль на <b>{live.fmt(amount)}</b>: <b>{live.html.escape(winner[1])}</b> "
                           f"обыграл(а) <b>{live.html.escape(loser[1])}</b>!")
    mine = rw if winner[0] == ctx.uid else rl
    return {"duel": duel_public(d), "balance": mine["balance"], "events": mine.get("events", []),
            "win": winner[0] == ctx.uid}


async def _bump_duel_wins(chat_id, uid):
    from user_manager import get_user_data, get_user_lock
    from v2.wallet import save
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = profile.st(data)
        s["stats"]["duels_won"] = int(s["stats"].get("duels_won", 0)) + 1
        events = []
        if s["stats"]["duels_won"] >= 10:
            profile.award(s, "duel10", events)
        save(chat_id, uid, data)


async def duel_cancel(hub, ctx: Ctx, did: str):
    d = hub.duels.get(did)
    if not d or d["uid"] != ctx.uid or d["state"] != "open":
        raise GameError("Отменить нельзя.")
    d["state"] = "cancel"
    ref = f"duel:{did}:{ctx.uid}"
    res = await settle(hub.chat_id, ctx.uid, ctx.name, "duel", ref, 0, d["amount"], record=False)
    unregister_live(ref)
    return {"balance": res["balance"]}


async def duels_tick(hub, now):
    for did, d in list(hub.duels.items()):
        if d["state"] == "open" and now >= d["expires"]:
            d["state"] = "expired"
            ref = f"duel:{did}:{d['uid']}"
            await settle(hub.chat_id, d["uid"], d["name"], "duel", ref, 0, d["amount"], record=False)
            unregister_live(ref)
        if d["state"] in ("done", "cancel", "expired") and now - d.get("done_ts", d["expires"]) > 600:
            hub.duels.pop(did, None)


def duel_public(d):
    out = {"id": d["id"], "h": d["h"], "name": d["name"], "amount": d["amount"], "state": d["state"],
           "expires": d["expires"], "target_name": d.get("target_name") or None}
    if d["state"] == "done":
        out.update(opp_h=d["opp_h"], opp_name=d["opp_name"], winner_h=d["winner_h"], winner_name=d["winner_name"],
                   side=d["side"], prize=d["prize"])
    return out


def duels_view(hub, uid):
    rows = sorted(hub.duels.values(), key=lambda d: -d["ts"])
    out = []
    for d in rows:
        if d["state"] in ("open", "busy", "done"):
            item = duel_public(d)
            item["mine"] = d["uid"] == uid
            item["for_me"] = d.get("target") == uid
            item["locked"] = bool(d.get("target")) and d.get("target") != uid and d["uid"] != uid
            out.append(item)
    return out[:20]


# ───────────────────────── Цикл столов ─────────────────────────
def table(hub, kind):
    if kind == "crash":
        if hub.crash is None:
            hub.crash = CrashTable(hub)
        return hub.crash
    if kind == "roulette":
        if hub.roulette is None:
            hub.roulette = RouletteTable(hub)
        return hub.roulette
    if kind == "jackpot":
        if hub.jackpot is None:
            hub.jackpot = JackpotTable(hub)
        return hub.jackpot
    raise KeyError(kind)


async def loop():
    while True:
        await asyncio.sleep(0.15)
        now = time.time()
        for hub in live.all_hubs():
            for t in (hub.crash, hub.roulette, hub.jackpot):
                if t is not None:
                    try:
                        await t.tick(now)
                    except Exception:
                        log.exception("table tick failed")
            try:
                await duels_tick(hub, now)
            except Exception:
                log.exception("duels tick failed")


async def shutdown():
    """Перед остановкой бота возвращает ставки незавершённых раундов."""
    for hub in live.all_hubs():
        c, r, j = hub.crash, hub.roulette, hub.jackpot
        jobs = []
        if c is not None and c.phase in ("bet", "run"):
            jobs += [(uid, b["name"], "crash", c.rid, b["amount"]) for uid, b in c.bets.items() if b["cash"] is None]
        if r is not None and r.phase in ("bet", "spin"):
            jobs += [(uid, b["name"], "roulette", f"{r.rid}:{uid}", sum(x["amount"] for x in b["list"]))
                     for uid, b in r.bets.items()]
        if j is not None and j.phase in ("open", "count", "draw"):
            jobs += [(uid, b["name"], "jackpot", f"{j.rid}:{uid}", b["amount"]) for uid, b in j.bets.items()]
        jobs += [(d["uid"], d["name"], "duel", f"duel:{did}:{d['uid']}", d["amount"])
                 for did, d in hub.duels.items() if d["state"] == "open"]
        for uid, name, gid, ref, amount in jobs:
            try:
                await settle(hub.chat_id, uid, name, gid, ref, 0, amount, record=False)
            except Exception:
                log.exception("V2 shutdown refund failed")
