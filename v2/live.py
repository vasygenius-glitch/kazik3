"""Живое состояние чатов: кто в приложении, лента событий, лига недели, анонсы."""
import asyncio
import html
import logging
import time
from collections import deque

from db import get_db
from v2 import profile
from v2.conf import (ANNOUNCE_BIG_WIN, ANNOUNCE_GAP, ANNOUNCE_MIN_MULT, ANNOUNCE_MIN_WIN, ONLINE_WINDOW,
                     POOL_PRIZES, POOL_SHARE)

log = logging.getLogger(__name__)
_hubs: dict[int, "Hub"] = {}
_announce_queue: asyncio.Queue | None = None
bot_ref = {"bot": None}


def fmt(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


def plain(name: str) -> str:
    return html.unescape(str(name or "Игрок"))[:40]


class Hub:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.presence: dict[int, dict] = {}
        self.feed: deque = deque(maxlen=40)
        self.title = ""
        self.crash = None
        self.roulette = None
        self.jackpot = None
        self.duels: dict = {}
        self.league: dict | None = None
        self.dirty = False
        self.lock = asyncio.Lock()
        self.last_announce = 0.0
        self.announce = True

    # ── присутствие ──
    def touch(self, uid: int, handle: str, name: str, act: str = "lobby"):
        prev = self.presence.get(uid)
        since = prev["since"] if prev and prev.get("act") == act else time.time()
        self.presence[uid] = {"h": handle, "name": name, "act": act, "ts": time.time(), "since": since}

    def online(self) -> list:
        now = time.time()
        for uid in [u for u, p in self.presence.items() if now - p["ts"] > ONLINE_WINDOW * 4]:
            self.presence.pop(uid, None)
        rows = [p for p in self.presence.values() if now - p["ts"] <= ONLINE_WINDOW]
        rows.sort(key=lambda p: p["since"])
        return [{"h": p["h"], "name": p["name"], "act": p["act"]} for p in rows][:60]

    # ── лента ──
    def push(self, kind: str, name: str, handle: str, text: str, amount: int = 0, mult: float = 0, gid: str = ""):
        self.feed.appendleft({"ts": int(time.time()), "kind": kind, "name": name, "h": handle, "text": text,
                              "amount": int(amount), "x": round(float(mult), 2), "g": gid})

    def feed_view(self, limit: int = 25) -> list:
        return list(self.feed)[:limit]

    # ── лига недели ──
    def _empty_league(self, week: str) -> dict:
        return {"week": week, "players": {}, "pool": 0, "prev": (self.league or {}).get("prev")}

    async def ensure_league(self):
        if self.league is not None and self.league.get("week") == profile.week_key():
            return
        async with self.lock:
            week = profile.week_key()
            if self.league is None:
                try:
                    doc = await _league_ref(self.chat_id).get()
                    self.league = doc.to_dict() if doc.exists else None
                except Exception:
                    log.exception("league load failed")
                    self.league = None
                if not isinstance(self.league, dict) or not isinstance(self.league.get("players"), dict):
                    self.league = self._empty_league(week)
                    self.dirty = True
            if self.league.get("week") != week:
                await self._close_week(week)

    async def _close_week(self, new_week: str):
        old = self.league
        ranked = sorted(((int(uid), p) for uid, p in old.get("players", {}).items() if int(p.get("net", 0)) > 0),
                        key=lambda x: -int(x[1].get("net", 0)))[:3]
        pool = int(old.get("pool", 0))
        winners = []
        for (uid, p), share in zip(ranked, POOL_PRIZES):
            winners.append({"uid": uid, "name": p.get("n", "Игрок"), "net": int(p.get("net", 0)),
                            "prize": int(pool * share), "paid": False})
        self.league = {"week": new_week, "players": {}, "pool": 0,
                       "prev": {"week": old.get("week"), "winners": winners}}
        self.dirty = True
        await self.save()
        from v2.wallet import settle_prize
        for w in winners:
            if w["prize"] > 0:
                try:
                    await settle_prize(self.chat_id, w["uid"], w["prize"])
                    w["paid"] = True
                except Exception:
                    log.exception("league prize failed")
        self.dirty = True
        if winners:
            lines = [f"{['🥇', '🥈', '🥉'][i]} {html.escape(w['name'])} — +{fmt(w['net'])}, приз {fmt(w['prize'])}"
                     for i, w in enumerate(winners)]
            self.queue_announce("🏆 <b>Итоги лиги недели в Казике</b>\n\n" + "\n".join(lines)
                                + f"\n\nФонд недели: {fmt(pool)} сыроежек. Новая неделя уже идёт!", force=True)

    def add_result(self, uid: int, name: str, handle: str, clan: str | None, wager: int, payout: int):
        if self.league is None:
            return
        players = self.league.setdefault("players", {})
        p = players.setdefault(str(uid), {"n": name, "net": 0, "wag": 0, "games": 0})
        p["n"], p["h"] = name, handle
        p["clan"] = clan or None
        p["net"] = int(p.get("net", 0)) + int(payout) - int(wager)
        p["wag"] = int(p.get("wag", 0)) + int(wager)
        p["games"] = int(p.get("games", 0)) + 1
        self.league["pool"] = int(self.league.get("pool", 0)) + int(wager * POOL_SHARE)
        self.dirty = True

    def add_pool(self, amount: int):
        if self.league is not None and amount > 0:
            self.league["pool"] = int(self.league.get("pool", 0)) + int(amount)
            self.dirty = True

    async def save(self):
        if not self.dirty or self.league is None:
            return
        self.dirty = False
        try:
            await _league_ref(self.chat_id).set(self.league)
        except Exception:
            self.dirty = True
            log.exception("league save failed")

    def queue_announce(self, text: str, force: bool = False):
        if _announce_queue is None or not (self.announce or force):
            return
        now = time.time()
        if not force and now - self.last_announce < ANNOUNCE_GAP:
            return
        self.last_announce = now
        try:
            _announce_queue.put_nowait((self.chat_id, text))
        except asyncio.QueueFull:
            pass


def _league_ref(chat_id: int):
    return get_db().collection("chats").document(str(chat_id)).collection("v2").document("league")


async def hub(chat_id: int) -> Hub:
    h = _hubs.get(chat_id)
    if h is None:
        h = _hubs[chat_id] = Hub(chat_id)
        try:
            from v2 import settings
            h.announce = await settings.announce_enabled(chat_id)
        except Exception:
            pass
    await h.ensure_league()
    return h


def peek(chat_id: int) -> "Hub | None":
    return _hubs.get(chat_id)


def all_hubs() -> list:
    return list(_hubs.values())


async def save_all():
    for h in all_hubs():
        await h.save()


def result(h: Hub, ctx_uid: int, name: str, handle: str, clan, gid: str, bet: int, payout: int, mult: float,
           events: list | None = None):
    """Учёт исхода в лиге, ленте и анонсах группы."""
    h.add_result(ctx_uid, name, handle, clan, bet, payout)
    gname = profile.GAME_NAMES.get(gid, gid)
    win = payout - bet
    if win > 0 and (mult >= 3 or win >= 5_000):
        xs = f"x{mult:g}".replace(".", ",")
        h.push("win", name, handle, f"{gname}: {xs}", win, mult, gid)
        if (mult >= ANNOUNCE_MIN_MULT and win >= ANNOUNCE_MIN_WIN) or win >= ANNOUNCE_BIG_WIN:
            h.queue_announce(f"🍄 <b>{html.escape(name)}</b> сорвал(а) <b>{xs}</b> в игре «{gname}» "
                             f"и забрал(а) <b>+{fmt(win)}</b> сыроежек!")
    for ev in events or ():
        if ev.get("type") == "level":
            h.push("level", name, handle, f"новый уровень {ev['level']} · {ev['title']}")
        elif ev.get("type") == "ach":
            h.push("ach", name, handle, f"достижение «{ev['name']}»")


async def announcer(bot):
    """Фоновая отправка анонсов в группы (с кнопкой открытия приложения)."""
    global _announce_queue
    _announce_queue = asyncio.Queue(maxsize=100)
    bot_ref["bot"] = bot
    from v2.links import open_markup
    while True:
        chat_id, text = await _announce_queue.get()
        try:
            await bot.send_message(chat_id, text, reply_markup=open_markup(chat_id, "🎰 Играть в Казик"),
                                   disable_notification=True)
        except Exception as exc:
            log.warning("V2 announce failed (%s)", type(exc).__name__)
        await asyncio.sleep(1.5)


async def saver():
    while True:
        await asyncio.sleep(20)
        await save_all()
