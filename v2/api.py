"""HTTP API и статика Mini App. Висит на том же aiohttp-сервере, что и /health.

Каждый запрос подписан Telegram (initData). Чат берётся только из подписанного
токена (startapp / ?c=), поэтому приложение, открытое из /v2 в группе, работает
строго с экономикой этой группы. Telegram ID наружу не отдаются никогда.
"""
import asyncio
import gzip
import hashlib
import html
import json
import logging
import mimetypes
import os
import time
from functools import partial
from pathlib import Path
from urllib.parse import unquote

from aiohttp import web

from escape import escape_html
from v2 import eco, live, profile, security, settings, wallet
from v2.conf import DUEL_TTL, MAX_BET, MEMBER_CACHE_TTL, MIN_BET, RTP
from v2.games import cards, solo, tables
from v2.wallet import Ctx, GameError

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent / "web"
AV_DIR = Path(os.getenv("V2_AVATAR_DIR", "/tmp/kazik_v2_avatars"))
state = {"bot": None, "version": ""}
_members: dict = {}
_titles: dict = {}
_cache: dict = {}
_assets: dict = {}
_av_mem: dict = {}
_av_lock: dict = {}
_limiter = security.RateLimiter(45, 5.0)
_dumps = partial(json.dumps, ensure_ascii=False, separators=(",", ":"))
ACTS = {"lobby", "games", "top", "profile", *profile.GAME_NAMES}

CSP = ("default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob: https:; connect-src 'self'; font-src 'self'; media-src 'self' data: blob:; "
       "object-src 'none'; base-uri 'none'")


class ApiError(Exception):
    def __init__(self, status: int, code: str, text: str):
        super().__init__(text)
        self.status, self.code, self.text = status, code, text


def dev_mode() -> bool:
    return os.getenv("V2_DEV") == "1"


def _json(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=_dumps, headers={"Cache-Control": "no-store"})


def plain(name) -> str:
    return html.unescape(str(name or "Игрок")).strip()[:40] or "Игрок"


# ───────────────────────── авторизация ─────────────────────────
def _dev_user(request) -> dict | None:
    if not dev_mode() or request.remote not in ("127.0.0.1", "::1") or "X-Forwarded-For" in request.headers:
        return None
    raw = unquote(request.headers.get("X-Dev-User", ""))
    uid, _, name = raw.partition(":")
    try:
        return {"id": int(uid), "first_name": name or "Тестер"}
    except ValueError:
        return None


async def _is_member(chat_id: int, uid: int) -> bool:
    bot = state["bot"]
    if bot is None:
        return dev_mode()
    key = (chat_id, uid)
    hit = _members.get(key)
    if hit and time.monotonic() - hit[1] < MEMBER_CACHE_TTL:
        return hit[0]
    try:
        member = await bot.get_chat_member(chat_id, uid)
        status = getattr(member.status, "value", member.status)
        ok = status in ("creator", "administrator", "member") or (
            status == "restricted" and bool(getattr(member, "is_member", False)))
    except Exception as exc:
        from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
        if isinstance(exc, (TelegramBadRequest, TelegramForbiddenError)):
            ok = False
        else:
            # Telegram недоступен — пускаем только тех, кто уже играл в этом чате.
            from user_manager import get_from_cache
            ok = get_from_cache(chat_id, uid) is not None
            if not ok:
                return False
    if len(_members) > 20000:
        _members.clear()
    _members[key] = (ok, time.monotonic())
    return ok


async def chat_title(chat_id: int) -> str:
    hit = _titles.get(chat_id)
    if hit and time.monotonic() - hit[1] < 3600:
        return hit[0]
    title = "Казик"
    if state["bot"] is not None:
        try:
            title = (await state["bot"].get_chat(chat_id)).title or title
        except Exception:
            pass
    _titles[chat_id] = (title, time.monotonic())
    return title


async def _context(request, body: dict):
    auth = security.verify_init_data(request.headers.get("X-Init-Data", ""))
    user = auth["user"] if auth else _dev_user(request)
    if not user:
        raise ApiError(401, "auth", "Открой Казик через Telegram — сессия не подтверждена.")
    uid = int(user["id"])
    if not _limiter.allow(uid):
        raise ApiError(429, "slow", "Слишком быстро! Дай крупье передохнуть.")
    chat_id = None
    for token in ((auth or {}).get("start_param"), request.headers.get("X-Chat")):
        parsed = security.parse_chat_token(token or "")
        if parsed is not None and parsed < 0:
            chat_id = parsed
            break
    # Чат — только из подписанного токена той группы, где нажали /v2. Без него не угадываем.
    if chat_id is None:
        raise ApiError(403, "no_chat", "Открой Казик из своей группы командой /v2.")
    if not await settings.enabled(chat_id):
        raise ApiError(403, "disabled", "В этом чате Казик V2 выключен. Админ может включить его командой /v2 on.")
    if not await _is_member(chat_id, uid):
        raise ApiError(403, "not_member", "Этот Казик — для участников группы. Вступи в чат, чтобы играть.")
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x).strip()
    name = (name or user.get("username") or "Игрок")[:64]
    from config import CREATOR_IDS
    ctx = Ctx(chat_id, uid, name, escape_html(name), security.handle_for(uid), uid in CREATOR_IDS,
              str(user.get("photo_url") or ""))
    data = await wallet.load(ctx)
    ctx.clan = data.get("clan") if isinstance(data.get("clan"), str) else None
    hub = await live.hub(chat_id)
    return ctx, hub, data


async def _body(request) -> dict:
    if request.method != "POST" or not request.can_read_body:
        return {}
    if (request.content_length or 0) > 16384:
        raise ApiError(413, "big", "Слишком большой запрос.")
    try:
        body = json.loads(await request.text() or "{}")
    except ValueError:
        raise ApiError(400, "json", "Неверный запрос.") from None
    return body if isinstance(body, dict) else {}


def endpoint(act: str | None = None):
    def deco(fn):
        async def handler(request):
            try:
                body = await _body(request)
                ctx, hub, data = await _context(request, body)
                if act:
                    hub.touch(ctx.uid, ctx.handle, ctx.name, act)
                res = await fn(request, ctx, hub, data, body)
                res.setdefault("ok", True)
                res.setdefault("now", time.time())
                return _json(res)
            except GameError as exc:
                return _json({"ok": False, "error": str(exc), "now": time.time()})
            except ApiError as exc:
                return _json({"ok": False, "error": exc.text, "code": exc.code}, exc.status)
            except Exception:
                log.exception("V2 API %s failed", request.path)
                return _json({"ok": False, "error": "Что-то пошло не так. Попробуй ещё раз."}, 500)
        handler.__name__ = fn.__name__
        return handler
    return deco


def _int(body: dict, key: str, default=None) -> int:
    value = body.get(key, default)
    if isinstance(value, bool):
        raise GameError("Неверное значение.")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise GameError("Неверное значение.") from None


def _bet(body: dict) -> int:
    return wallet.parse_bet(body.get("bet"))


# ───────────────────────── представления ─────────────────────────
def _prestige(data: dict) -> dict:
    try:
        from prestige import get_prestige_perks
        p = get_prestige_perks(data)
        return {"level": int(p.get("level", 0)), "name": p.get("name"), "badge": p.get("badge"),
                "mult": p.get("income_multiplier", 1.0)}
    except Exception:
        return {"level": 0, "name": "Обыватель", "badge": "", "mult": 1.0}


def _disease_names(ids) -> list:
    try:
        from diseases import DISEASES
    except Exception:
        DISEASES = {}
    return [{"id": d, "name": (DISEASES.get(d) or {}).get("name", d), "desc": (DISEASES.get(d) or {}).get("desc", "")}
            for d in ids]


async def _me(ctx: Ctx, data: dict, s: dict) -> dict:
    sick = await wallet.active_diseases(ctx.chat_id, ctx.uid, data)
    return {"h": ctx.handle, "name": ctx.name, "balance": int(data.get("balance", 0) or 0), **profile.level_info(s),
            "vip": bool(data.get("is_vip")), "clan": ctx.clan, "prestige": _prestige(data),
            "sick": _disease_names(sick), "creator": ctx.is_creator,
            "rake": int(s.get("rake", 0) or 0),
            "rake_rate": round(profile.rake_rate(data, s, "hpv" not in sick) * 100, 2)}


def _cfg() -> dict:
    return {
        "min_bet": MIN_BET, "max_bet": MAX_BET, "rtp": RTP, "duel_ttl": DUEL_TTL,
        "slots": {"three": solo.SLOT_3, "pair": solo.SLOT_PAIR, "two_shrooms": solo.SLOT_TWO_SHROOMS,
                  "one_shroom": solo.SLOT_ONE_SHROOM},
        "dice": {k: {"label": v[1], "mult": solo.dice_mult(k)} for k, v in solo.DICE_PICKS.items()},
        "cups": {str(k): v for k, v in solo.CUPS_MULT.items()},
        "rps": solo.RPS_WIN, "baccarat": solo.BAC_MULT, "wheel": solo.WHEEL,
        "poker": [[k, name, mult] for k, name, mult in cards.POKER_PAYTABLE],
        "roulette": {"order": tables.WHEEL_ORDER, "red": sorted(tables.RED)},
        "crash": {"growth": tables.GROWTH},
        "ach": {k: {"name": v[0], "desc": v[1]} for k, v in profile.ACHIEVEMENTS.items()},
        "games": profile.GAME_NAMES,
    }


def _tables_summary(hub) -> dict:
    out = {}
    c, r, j = hub.crash, hub.roulette, hub.jackpot
    if c is not None:
        out["crash"] = {"phase": c.phase, "start": c.t_start, "bet_end": c.t_bet_end, "growth": tables.GROWTH,
                        "players": len(c.bets), "history": list(c.history)[:6],
                        "point": c.point if c.phase == "end" else None}
    if r is not None:
        out["roulette"] = {"phase": r.phase, "t_next": r.t_next, "players": len(r.bets),
                           "history": list(r.history)[:6], "result": r.result if r.phase == "show" else None}
    if j is not None:
        out["jackpot"] = {"phase": j.phase, "t_next": j.t_next, "total": j.total,
                          "players": [{"h": b["h"], "name": b["name"]} for b in j.bets.values()][:8]}
    out["duels"] = sum(1 for d in hub.duels.values() if d["state"] == "open")
    return out


def _after_game(hub, ctx: Ctx, gid: str, res: dict):
    wager = int(res.get("wager") or res.get("bet") or 0)
    if not wager or not res.get("done", True):
        return
    payout = int(res.get("payout", 0) or 0)
    mult = float(res.get("mult") or (round(payout / wager, 2) if wager else 0))
    live.result(hub, ctx.uid, ctx.name, ctx.handle, ctx.clan, gid, wager, payout, mult, res.get("events"))


# ───────────────────────── эндпоинты ─────────────────────────
@endpoint("lobby")
async def api_me(request, ctx, hub, data, body):
    data, s = await wallet.touch(ctx)
    level = profile.level_for_xp(int(s.get("xp", 0)))
    hub.title = await chat_title(ctx.chat_id)
    return {"chat": {"title": hub.title, "token": security.chat_token(ctx.chat_id)},
            "me": await _me(ctx, data, s), "cfg": _cfg(), "active": solo.active_views(s),
            "timers": eco.timers(data), "tasks": profile.tasks_view(s, ctx.uid, level),
            "fire": eco.fire_view(s, ctx.uid), "online": hub.online(), "feed": hub.feed_view(),
            "tables": _tables_summary(hub)}


@endpoint()
async def api_poll(request, ctx, hub, data, body):
    scope = str(body.get("scope") or "lobby")
    screen = str(body.get("screen") or scope)
    hub.touch(ctx.uid, ctx.handle, ctx.name, screen if screen in ACTS else "lobby")
    s = profile.st(data)
    res = {"balance": int(data.get("balance", 0) or 0), "online": hub.online(), "rake": int(s.get("rake", 0) or 0)}
    if scope == "lobby":
        for kind in ("crash", "roulette", "jackpot"):
            tables.table(hub, kind).ping()
        level = profile.level_for_xp(int(s.get("xp", 0)))
        res.update(feed=hub.feed_view(), fire=eco.fire_view(s, ctx.uid), timers=eco.timers(data),
                   tasks=profile.tasks_view(s, ctx.uid, level), duels=tables.duels_view(hub, ctx.uid)[:6])
    elif scope in ("crash", "roulette", "jackpot"):
        t = tables.table(hub, scope)
        t.ping()
        res[scope] = t.view(ctx.uid)
    elif scope == "duels":
        res["duels"] = tables.duels_view(hub, ctx.uid)
    res["tables"] = _tables_summary(hub)
    return res


async def _rich(chat_id: int) -> list:
    key = ("rich", chat_id)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[1] < 30:
        return hit[0]
    from db import get_db
    from user_manager import get_from_cache
    ref = get_db().collection("chats").document(str(chat_id)).collection("users")
    try:
        docs = await ref.order_by("balance", direction="DESCENDING").limit(60).get()
    except Exception:
        docs = await ref.get()
    rows = []
    for doc in docs:
        try:
            uid = int(doc.id)
        except (TypeError, ValueError):
            continue
        d = get_from_cache(chat_id, uid) or doc.to_dict() or {}
        if d.get("hide_in_top") or d.get("is_banned") or d.get("is_banker"):
            continue
        rows.append((uid, d))
    rows.sort(key=lambda x: -int(x[1].get("balance", 0) or 0))
    out = []
    for uid, d in rows[:30]:
        s = profile.st(d)
        p = _prestige(d)
        out.append({"h": security.handle_for(uid), "name": plain(d.get("full_name")),
                    "balance": int(d.get("balance", 0) or 0), "level": profile.level_for_xp(int(s.get("xp", 0))),
                    "clan": d.get("clan") if isinstance(d.get("clan"), str) else None,
                    "badge": p["badge"] if p["level"] else "", "vip": bool(d.get("is_vip"))})
    _cache[key] = (out, time.monotonic())
    return out


async def _clan_docs(chat_id: int) -> dict:
    key = ("clans", chat_id)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[1] < 300:
        return hit[0]
    out = {}
    try:
        from db import get_db
        for doc in await get_db().collection("chats").document(str(chat_id)).collection("clans").get():
            d = doc.to_dict() or {}
            out[doc.id] = {"members": len(d.get("members") or []), "treasury": int(d.get("treasury", 0) or 0)}
    except Exception:
        log.exception("clans load failed")
    _cache[key] = (out, time.monotonic())
    return out


def _league_view(hub, uid: int) -> dict:
    lg = hub.league or {}
    players = []
    for key, p in (lg.get("players") or {}).items():
        try:
            puid = int(key)
        except ValueError:
            continue
        players.append({"uid": puid, "h": security.handle_for(puid), "name": p.get("n", "Игрок"),
                        "net": int(p.get("net", 0)), "wag": int(p.get("wag", 0)), "games": int(p.get("games", 0)),
                        "clan": p.get("clan")})
    players.sort(key=lambda p: (-p["net"], -p["wag"]))
    me = next(({"pos": i + 1, **{k: v for k, v in p.items() if k != "uid"}}
               for i, p in enumerate(players) if p["uid"] == uid), None)
    pool = int(lg.get("pool", 0))
    prev = lg.get("prev") or {}
    winners = [{"h": security.handle_for(int(w["uid"])), "name": w.get("name"), "net": w.get("net"),
                "prize": w.get("prize")} for w in (prev.get("winners") or []) if isinstance(w, dict) and "uid" in w]
    return {"week": lg.get("week"), "ends": profile.week_ends_at(), "pool": pool,
            "prizes": [int(pool * x) for x in (0.5, 0.3, 0.2)],
            "rows": [{k: v for k, v in p.items() if k != "uid"} for p in players[:30]], "me": me,
            "prev": {"week": prev.get("week"), "winners": winners} if prev else None}


@endpoint("top")
async def api_top(request, ctx, hub, data, body):
    tab = str(body.get("tab") or "rich")
    if tab == "league":
        return {"league": _league_view(hub, ctx.uid)}
    if tab == "clans":
        docs = await _clan_docs(ctx.chat_id)
        agg: dict = {}
        for p in ((hub.league or {}).get("players") or {}).values():
            clan = p.get("clan")
            if not clan:
                continue
            a = agg.setdefault(clan, {"name": clan, "net": 0, "wag": 0, "active": 0})
            a["net"] += int(p.get("net", 0))
            a["wag"] += int(p.get("wag", 0))
            a["active"] += 1
        for name, d in docs.items():
            a = agg.setdefault(name, {"name": name, "net": 0, "wag": 0, "active": 0})
            a.update(d)
        rows = sorted(agg.values(), key=lambda a: (-a["wag"], -a.get("treasury", 0)))[:30]
        for a in rows:
            a["name"] = plain(a["name"])
            a.setdefault("members", 0)
            a.setdefault("treasury", 0)
        return {"clans": rows, "mine": ctx.clan}
    rows = await _rich(ctx.chat_id)
    pos = next((i + 1 for i, r in enumerate(rows) if r["h"] == ctx.handle), None)
    return {"rich": rows, "pos": pos}


def _legacy(data: dict, sick: list) -> dict:
    inv = data.get("inventory") if isinstance(data.get("inventory"), dict) else {}
    biz, cars, income = [], [], 0
    try:
        from shop import ITEMS
        for item_id, count in inv.items():
            item = ITEMS.get(item_id)
            if not item or not count:
                continue
            row = {"name": item.get("name", item_id), "count": int(count)}
            if item.get("action") == "business":
                biz.append(row)
                income += int(item.get("income", 0) or 0) * int(count)
            elif item.get("action") == "car":
                cars.append(row)
                income += int(item.get("income", 0) or 0) * int(count)
    except Exception:
        log.exception("legacy items failed")
    pet = data.get("pet") if isinstance(data.get("pet"), dict) else None
    pet_view = None
    if pet and pet.get("id"):
        try:
            from pets import PETS_SHOP
            spec = PETS_SHOP.get(pet["id"], {})
        except Exception:
            spec = {}
        pet_view = {"id": pet["id"], "name": spec.get("name", pet["id"]), "bonus": spec.get("bonus", "")}
    cards_owned = data.get("meme_cards") if isinstance(data.get("meme_cards"), dict) else {}
    return {"balance": int(data.get("balance", 0) or 0), "bank": int(data.get("bank_deposit", 0) or 0),
            "bank_name": plain(data.get("bank_name")) if data.get("bank_name") else None,
            "vip": bool(data.get("is_vip")), "banker": bool(data.get("is_banker")), "prestige": _prestige(data),
            "pet": pet_view, "clan": data.get("clan") if isinstance(data.get("clan"), str) else None,
            "biz": biz[:30], "cars": cars[:30], "income": income,
            "cards": sum(int(v or 0) for v in cards_owned.values() if isinstance(v, (int, float))),
            "debts": sum(int(v or 0) for v in (data.get("debts") or {}).values() if isinstance(v, (int, float))),
            "diseases": _disease_names(sick)}


def _stats_view(s: dict) -> dict:
    games = [{"g": gid, "name": profile.GAME_NAMES.get(gid, gid), **g} for gid, g in (s.get("games") or {}).items()
             if isinstance(g, dict)]
    games.sort(key=lambda g: -int(g.get("n", 0)))
    return {"stats": s["stats"], "games": games, "ach": list(s.get("ach") or []), "hist": profile.history_view(s),
            **profile.level_info(s), "rake_total": int(s.get("rake_total", 0) or 0)}


@endpoint("profile")
async def api_profile(request, ctx, hub, data, body):
    target = str(body.get("h") or "")
    if target and target != ctx.handle:
        uid = security.user_for_handle(target)
        if uid is None:
            raise GameError("Игрок не найден.")
        from user_manager import get_from_cache, get_user_data, get_user_ref
        if get_from_cache(ctx.chat_id, uid) is None and not (await get_user_ref(ctx.chat_id, uid).get()).exists:
            raise GameError("Игрок не найден.")
        other = await get_user_data(ctx.chat_id, uid)
        s = profile.st(other)
        view = _stats_view(s)
        view.pop("hist", None)
        return {"player": {"h": target, "name": plain(other.get("full_name")),
                           "balance": int(other.get("balance", 0) or 0), "vip": bool(other.get("is_vip")),
                           "clan": other.get("clan") if isinstance(other.get("clan"), str) else None,
                           "prestige": _prestige(other), **view}}
    data, s = await wallet.touch(ctx)
    sick = await wallet.active_diseases(ctx.chat_id, ctx.uid, data)
    return {"me": await _me(ctx, data, s), "player": {"h": ctx.handle, "name": ctx.name, **_stats_view(s)},
            "legacy": _legacy(data, sick)}


@endpoint("lobby")
async def api_bonus(request, ctx, hub, data, body):
    res = await eco.bonus(ctx)
    total = int(res["receipt"].get("total") or 0) + res["boost"]
    if total >= 100_000:
        hub.push("bonus", ctx.name, ctx.handle, "собрал(а) доход", total)
    return res


@endpoint("lobby")
async def api_work(request, ctx, hub, data, body):
    return await eco.work(ctx)


@endpoint("lobby")
async def api_crime(request, ctx, hub, data, body):
    return await eco.crime(ctx)


@endpoint("lobby")
async def api_premium(request, ctx, hub, data, body):
    return await eco.premium(ctx, str(body.get("token") or ""), _int(body, "pick", -1))


@endpoint("lobby")
async def api_rake(request, ctx, hub, data, body):
    return await eco.claim_rake(ctx)


@endpoint("lobby")
async def api_task(request, ctx, hub, data, body):
    return await eco.claim_task(ctx, str(body.get("id") or ""))


@endpoint("wheel")
async def api_wheel(request, ctx, hub, data, body):
    res = await solo.wheel(ctx)
    if res["mult"] >= 10:
        hub.push("wheel", ctx.name, ctx.handle, f"Колесо дня: x{res['mult']:g}".replace(".", ","), res["prize"], res["mult"], "wheel")
    return res


async def _play_one(ctx: Ctx, game: str, body: dict) -> dict:
    action = str(body.get("action") or "")
    if game == "slots":
        return await solo.slots(ctx, _bet(body))
    if game == "dice":
        return await solo.dice(ctx, _bet(body), str(body.get("pick") or ""))
    if game == "cups":
        return await solo.cups(ctx, _bet(body), _int(body, "count", 3), _int(body, "pick", -1))
    if game == "rps":
        return await solo.rps(ctx, _bet(body), str(body.get("move") or ""))
    if game == "baccarat":
        return await solo.baccarat(ctx, _bet(body), str(body.get("side") or ""))
    if game == "mines":
        if action == "start":
            return await solo.mines_start(ctx, _bet(body), _int(body, "mines", 3))
        if action == "pick":
            return await solo.mines_pick(ctx, _int(body, "cell", -1))
        if action == "cash":
            return await solo.mines_cash(ctx)
    if game == "bj":
        if action == "start":
            return await solo.bj_start(ctx, _bet(body))
        if action in ("hit", "stand", "double", "split"):
            return await solo.bj_act(ctx, action)
    if game == "poker":
        if action == "deal":
            return await solo.poker_deal(ctx, _bet(body))
        if action == "draw":
            return await solo.poker_draw(ctx, body.get("hold"))
    raise GameError("Неизвестная игра или действие.")


async def api_play(request):
    game = request.match_info["game"]

    @endpoint(game if game in profile.GAME_NAMES else None)
    async def run(request, ctx, hub, data, body):
        res = await _play_one(ctx, game, body)
        _after_game(hub, ctx, game, res)
        return res
    return await run(request)


@endpoint("crash")
async def api_crash(request, ctx, hub, data, body):
    t = tables.table(hub, "crash")
    t.ping()
    if body.get("action") == "cash":
        return await t.cashout(ctx)
    auto = body.get("auto")
    try:
        auto = round(float(auto), 2) if auto not in (None, "", 0) else None
    except (TypeError, ValueError):
        raise GameError("Автовывод — число, например 2.5.") from None
    return {"balance": await t.bet(ctx, _bet(body), auto, ctx.clan), "crash": t.view(ctx.uid)}


@endpoint("roulette")
async def api_roulette(request, ctx, hub, data, body):
    t = tables.table(hub, "roulette")
    t.ping()
    value = body.get("value")
    if value is not None:
        value = _int(body, "value")
    balance = await t.bet(ctx, str(body.get("kind") or ""), value, _bet(body), ctx.clan)
    return {"balance": balance, "roulette": t.view(ctx.uid)}


@endpoint("jackpot")
async def api_jackpot(request, ctx, hub, data, body):
    t = tables.table(hub, "jackpot")
    return {"balance": await t.bet(ctx, _bet(body), ctx.clan), "jackpot": t.view(ctx.uid)}


@endpoint("duel")
async def api_duel(request, ctx, hub, data, body):
    action = str(body.get("action") or "")
    if action == "create":
        target_uid, target_name = None, ""
        target = str(body.get("target") or "")
        if target:
            target_uid = security.user_for_handle(target)
            if target_uid is None:
                raise GameError("Соперник не найден.")
            p = hub.presence.get(target_uid)
            target_name = p["name"] if p else "сопернику"
        res = await tables.duel_create(hub, ctx, _bet(body), target_uid, target_name, ctx.clan)
    elif action == "accept":
        res = await tables.duel_accept(hub, ctx, str(body.get("id") or ""), ctx.clan)
    elif action == "cancel":
        res = await tables.duel_cancel(hub, ctx, str(body.get("id") or ""))
    else:
        raise GameError("Неизвестное действие.")
    res["duels"] = tables.duels_view(hub, ctx.uid)
    return res


# ───────────────────────── аватарки ─────────────────────────
async def _fetch_avatar(uid: int) -> bytes | None:
    bot = state["bot"]
    if bot is None:
        return None
    photos = await bot.get_user_profile_photos(uid, limit=1)
    if not photos.total_count or not photos.photos:
        return None
    sizes = sorted(photos.photos[0], key=lambda p: p.width)
    pick = next((p for p in sizes if p.width >= 150), sizes[-1])
    buf = await bot.download(pick.file_id)
    return buf.getvalue() if buf else None


async def api_avatar(request):
    h = request.match_info["h"]
    uid = security.user_for_handle(h)
    if uid is None:
        raise web.HTTPNotFound()
    now = time.time()
    hit = _av_mem.get(uid)
    if not hit or now - hit[0] > (21600 if hit[1] else 3600):
        path = AV_DIR / f"{h}.jpg"
        lock = _av_lock.setdefault(uid, asyncio.Lock())
        async with lock:
            hit = _av_mem.get(uid)
            if not hit or now - hit[0] > (21600 if hit[1] else 3600):
                body = None
                try:
                    if path.exists() and now - path.stat().st_mtime < 86400:
                        body = path.read_bytes()
                    else:
                        body = await asyncio.wait_for(_fetch_avatar(uid), 8)
                        if body:
                            AV_DIR.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(body)
                except Exception as exc:
                    log.debug("avatar fetch failed: %s", type(exc).__name__)
                if len(_av_mem) > 600:
                    _av_mem.clear()
                hit = _av_mem[uid] = (now, body)
        _av_lock.pop(uid, None)
    if not hit[1]:
        return web.Response(status=404, headers={"Cache-Control": "public, max-age=1800"})
    return web.Response(body=hit[1], content_type="image/jpeg", headers={"Cache-Control": "public, max-age=21600"})


# ───────────────────────── статика ─────────────────────────
def _version() -> str:
    if not state["version"] or dev_mode():
        digest = hashlib.sha1()
        for path in sorted(WEB_DIR.rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(WEB_DIR).as_posix().encode())
                digest.update(path.read_bytes())
        state["version"] = digest.hexdigest()[:10]
    return state["version"]


def _asset(rel: str):
    if rel in _assets and not dev_mode():
        return _assets[rel]
    path = (WEB_DIR / rel).resolve()
    if WEB_DIR not in path.parents or not path.is_file():
        return None
    raw = path.read_bytes()
    ctype = {".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml",
             ".html": "text/html", ".json": "application/json"}.get(path.suffix) or \
        mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    packed = gzip.compress(raw, 6) if path.suffix in (".js", ".css", ".svg", ".html", ".json") else None
    _assets[rel] = (raw, packed, ctype)
    return _assets[rel]


def _send(request, asset, cache: str, body: bytes | None = None) -> web.Response:
    raw, packed, ctype = asset
    headers = {"Cache-Control": cache, "X-Content-Type-Options": "nosniff", "Vary": "Accept-Encoding"}
    if body is not None:
        raw, packed = body, gzip.compress(body, 6)
    if packed and "gzip" in request.headers.get("Accept-Encoding", ""):
        headers["Content-Encoding"] = "gzip"
        return web.Response(body=packed, content_type=ctype, charset="utf-8" if ctype.startswith("text") else None,
                            headers=headers)
    return web.Response(body=raw, content_type=ctype, charset="utf-8" if ctype.startswith("text") else None,
                        headers=headers)


async def app_index(request):
    asset = _asset("index.html")
    if asset is None:
        raise web.HTTPNotFound()
    page = asset[0].decode().replace("{{V}}", _version()).encode()
    resp = _send(request, asset, "no-cache", page)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


async def app_redirect(request):
    raise web.HTTPFound("/app/" + (f"?{request.query_string}" if request.query_string else ""))


async def app_static(request):
    rel = request.match_info["path"]
    asset = _asset(rel) if rel and not rel.startswith(".") else None
    if asset is None:
        raise web.HTTPNotFound()
    immutable = request.match_info["ver"] == _version()
    return _send(request, asset, "public, max-age=31536000, immutable" if immutable else "no-cache")


def setup(app: web.Application, bot=None):
    """Регистрирует маршруты Mini App на существующем aiohttp-приложении."""
    state["bot"] = bot
    r = app.router
    r.add_get("/app", app_redirect)
    r.add_get("/app/", app_index)
    r.add_get("/app/v/{ver}/{path:.+}", app_static)
    r.add_get("/api/v2/av/{h}", api_avatar)
    for name, fn in (("me", api_me), ("poll", api_poll), ("top", api_top), ("profile", api_profile),
                     ("bonus", api_bonus), ("work", api_work), ("crime", api_crime), ("premium", api_premium),
                     ("rake", api_rake), ("task", api_task), ("wheel", api_wheel), ("crash", api_crash),
                     ("roulette", api_roulette), ("jackpot", api_jackpot), ("duel", api_duel)):
        r.add_post(f"/api/v2/{name}", fn)
    r.add_post("/api/v2/play/{game}", api_play)
    return app
