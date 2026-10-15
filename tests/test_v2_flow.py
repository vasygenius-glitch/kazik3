"""Казик V2: деньги, сессии игр, общие столы и HTTP API (локальная БД, dev-авторизация)."""
import json
import time
from urllib.parse import quote

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from user_manager import get_from_cache, get_user_data
from v2 import api, eco, live, profile, security, settings, wallet
from v2.conf import PVP_FEE, RTP
from v2.games import cards as C
from v2.games import solo, tables
from v2.wallet import Ctx, GameError

START = 10_000


@pytest.fixture(autouse=True)
def _dev(monkeypatch):
    monkeypatch.setenv("V2_DEV", "1")
    monkeypatch.setattr(api, "_limiter", security.RateLimiter(100_000, 5.0))
    live._hubs.clear()
    yield
    live._hubs.clear()


async def _chat(chat_id, *players):
    await settings.set_enabled(chat_id, True, 1)
    for uid, name in players:
        data = await get_user_data(chat_id, uid, name)
        data.update(balance=START, full_name=name)
        data.pop("v2", None)
        wallet.save(chat_id, uid, data)


def _ctx(chat_id, uid, name):
    return Ctx(chat_id, uid, name, name, security.handle_for(uid))


def _h(chat_id, uid, name):
    return {"X-Dev-User": quote(f"{uid}:{name}"), "X-Chat": security.chat_token(chat_id)}


def _bal(chat_id, uid):
    return int(get_from_cache(chat_id, uid)["balance"])


def _client():
    app = web.Application()
    api.setup(app, None)
    return TestClient(TestServer(app))


async def _post(c, path, headers, **body):
    r = await c.post(path, json=body, headers=headers)
    return r.status, await r.json()


# ───────────────────────── авторизация и привязка к чату ─────────────────────────
@pytest.mark.asyncio
async def test_me_works_and_never_leaks_ids():
    chat, uid = -100500600701, 987654321
    await _chat(chat, (uid, "Лисичка"))
    async with _client() as c:
        r = await c.post("/api/v2/me", json={}, headers=_h(chat, uid, "Лисичка"))
        text = await r.text()
        d = json.loads(text)
    assert r.status == 200 and d["ok"]
    assert d["me"]["balance"] == START and d["me"]["name"] == "Лисичка" and d["me"]["h"] == security.handle_for(uid)
    assert d["cfg"]["rtp"] == RTP and d["chat"]["token"] == security.chat_token(chat)
    assert d["online"] and d["online"][0]["name"] == "Лисичка"
    assert str(uid) not in text and str(chat) not in text


@pytest.mark.asyncio
async def test_context_errors(monkeypatch):
    chat, off_chat, uid = -100500600702, -100500600703, 5551
    await _chat(chat, (uid, "Тест"))
    async with _client() as c:
        st, d = await _post(c, "/api/v2/me", {})
        assert st == 401 and d["code"] == "auth"
        h = _h(chat, uid, "Тест")
        h.pop("X-Chat")
        st, d = await _post(c, "/api/v2/me", h)
        assert st == 403 and d["code"] == "no_chat"
        h = _h(chat, uid, "Тест")
        h["X-Chat"] = h["X-Chat"][:-1] + ("A" if h["X-Chat"][-1] != "A" else "B")
        st, d = await _post(c, "/api/v2/me", h)
        assert st == 403 and d["code"] == "no_chat"
        h["X-Chat"] = security.chat_token(uid)          # личка вместо группы
        st, d = await _post(c, "/api/v2/me", h)
        assert st == 403 and d["code"] == "no_chat"
        st, d = await _post(c, "/api/v2/me", _h(off_chat, uid, "Тест"))
        assert st == 403 and d["code"] == "disabled"
        st, d = await _post(c, "/api/v2/me", {**_h(chat, uid, "Тест"), "X-Forwarded-For": "1.2.3.4"})
        assert st == 401
        monkeypatch.delenv("V2_DEV")
        st, d = await _post(c, "/api/v2/me", _h(chat, uid, "Тест"))
        assert st == 401


@pytest.mark.asyncio
async def test_v2_switch_is_per_chat():
    a, b = -100500600704, -100500600705
    await settings.set_enabled(a, True, 1)
    assert await settings.enabled(a) and not await settings.enabled(b)
    await settings.set_enabled(a, False, 1)
    assert not await settings.enabled(a)


# ───────────────────────── одиночные игры через API ─────────────────────────
@pytest.mark.asyncio
async def test_slots_accounting_and_feed(monkeypatch):
    chat, uid = -100500600710, 6001
    await _chat(chat, (uid, "Сыроежкин"))
    h = _h(chat, uid, "Сыроежкин")
    async with _client() as c:
        st, d = await _post(c, "/api/v2/play/slots", h, bet=500)
        assert st == 200 and d["ok"] and d["balance"] == START - 500 + d["payout"]
        assert _bal(chat, uid) == d["balance"]
        monkeypatch.setattr(solo.rng, "choice", lambda seq: "shroom")
        before = d["balance"]
        st, d = await _post(c, "/api/v2/play/slots", h, bet=100)
        assert d["kind"] == "three" and d["payout"] == 100 * solo.SLOT_3["shroom"]
        assert d["balance"] == before - 100 + d["payout"]
        assert any(e["type"] == "ach" and e["id"] == "slots" for e in d["events"])
        for bad in (5, "abc", None, 10 ** 12, d["balance"] + 1):
            st, e = await _post(c, "/api/v2/play/slots", h, bet=bad)
            assert st == 200 and e["ok"] is False and e["error"]
        st, e = await _post(c, "/api/v2/play/nope", h, bet=100)
        assert e["ok"] is False
        st, lg = await _post(c, "/api/v2/top", h, tab="league")
    hub = live.peek(chat)
    assert any(f["kind"] == "win" and f["name"] == "Сыроежкин" and f["g"] == "slots" for f in hub.feed)
    row = lg["league"]["rows"][0]
    assert row["name"] == "Сыроежкин" and "uid" not in row and row["games"] == 2
    s = get_from_cache(chat, uid)["v2"]
    assert s["stats"]["n"] == 2 and s["stats"]["wag"] == 600 and s["rake"] > 0 and s["xp"] > 0


@pytest.mark.asyncio
async def test_mines_session(monkeypatch):
    chat, uid = -100500600711, 6002
    await _chat(chat, (uid, "Охотник"))
    h = _h(chat, uid, "Охотник")
    monkeypatch.setattr(solo.rng, "sample", lambda pop, k: list(range(k)))   # мухоморы в клетках 0..k-1
    async with _client() as c:
        st, d = await _post(c, "/api/v2/play/mines", h, action="start", bet=1000, mines=3)
        assert d["ok"] and d["balance"] == START - 1000 and "field" not in d
        st, me = await _post(c, "/api/v2/me", h)
        assert me["active"]["mines"]["bet"] == 1000 and "field" not in me["active"]["mines"]
        st, d = await _post(c, "/api/v2/play/mines", h, action="start", bet=1000, mines=3)
        assert d["ok"] is False
        st, d = await _post(c, "/api/v2/play/mines", h, action="pick", cell=10)
        assert d["open"] == [10] and d["mult"] == solo.mines_mult(3, 1)
        st, d = await _post(c, "/api/v2/play/mines", h, action="pick", cell=10)
        assert d["ok"] is False
        await _post(c, "/api/v2/play/mines", h, action="pick", cell=11)
        st, d = await _post(c, "/api/v2/play/mines", h, action="cash")
        win = int(1000 * solo.mines_mult(3, 2))
        assert d["done"] and d["payout"] == win and sorted(d["field"]) == [0, 1, 2]
        assert d["balance"] == START - 1000 + win
        await _post(c, "/api/v2/play/mines", h, action="start", bet=500, mines=3)
        st, d = await _post(c, "/api/v2/play/mines", h, action="pick", cell=1)
        assert d["done"] and d["boom"] == 1 and d["payout"] == 0
        assert d["balance"] == START - 1000 + win - 500
        st, d = await _post(c, "/api/v2/play/mines", h, action="cash")
        assert d["ok"] is False


@pytest.mark.asyncio
async def test_blackjack_hides_hole_card_and_pays(monkeypatch):
    chat, uid = -100500600712, 6003
    await _chat(chat, (uid, "Картёжник"))
    h = _h(chat, uid, "Картёжник")
    seq = iter(["Ts", "9h", "7c", "Ts",            # 19 против 17
                "5s", "6h", "Ts", "7d", "Kd"])     # 11 → дабл → 21 против 17
    monkeypatch.setattr(C, "draw", lambda: next(seq))
    async with _client() as c:
        st, d = await _post(c, "/api/v2/play/bj", h, action="start", bet=1000)
        assert d["ok"] and not d["done"] and d["dealer"] == ["7c", "??"]
        st, d = await _post(c, "/api/v2/play/bj", h, action="stand")
        assert d["done"] and d["payout"] == 2000 and d["hands"][0]["res"] == "win"
        await _post(c, "/api/v2/play/bj", h, action="start", bet=1000)
        st, d = await _post(c, "/api/v2/play/bj", h, action="double")
        assert d["done"] and d["wager"] == 2000 and d["payout"] == 4000
    assert _bal(chat, uid) == START + 1000 + 2000


@pytest.mark.asyncio
async def test_poker_hides_deck_and_pays(monkeypatch):
    chat, uid = -100500600713, 6004
    await _chat(chat, (uid, "Покерист"))
    h = _h(chat, uid, "Покерист")
    top = ["As", "Ad", "Kc", "7h", "2s", "Ah", "3c", "4d"]
    fixed = top + [r + s for r in C.RANKS for s in C.SUITS if r + s not in top]
    monkeypatch.setattr(C, "deck", lambda: list(fixed))
    async with _client() as c:
        st, d = await _post(c, "/api/v2/play/poker", h, action="deal", bet=100)
        assert d["hand"] == top[:5] and d["rank"] == "jacks" and "deck" not in d
        st, d = await _post(c, "/api/v2/play/poker", h, action="draw", hold=[1, 1, 0, 0, 0])
        assert d["hand"] == ["As", "Ad", "Ah", "3c", "4d"] and d["rank"] == "three" and d["payout"] == 300
        st, d = await _post(c, "/api/v2/play/poker", h, action="draw", hold=[1, 1, 1, 1, 1])
        assert d["ok"] is False
    assert _bal(chat, uid) == START + 200


# ───────────────────────── общие столы ─────────────────────────
@pytest.mark.asyncio
async def test_crash_round_auto_cashout_and_loss():
    chat, a, b = -100500600720, 7001, 7002
    await _chat(chat, (a, "Пилот"), (b, "Штурман"))
    async with _client() as c:
        hub = await live.hub(chat)
        t = tables.table(hub, "crash")
        t._new_round(time.time())
        t.point = 3.0
        st, d = await _post(c, "/api/v2/crash", _h(chat, a, "Пилот"), bet=1000, auto=2)
        assert d["ok"] and d["balance"] == START - 1000
        st, d = await _post(c, "/api/v2/crash", _h(chat, a, "Пилот"), bet=1000)
        assert d["ok"] is False
        st, d = await _post(c, "/api/v2/crash", _h(chat, b, "Штурман"), bet=500)
        assert d["ok"] and "point" not in d["crash"]
    await t.tick(t.t_bet_end + 0.01)
    assert t.phase == "run"
    await t.tick(t.t_crash + 0.01)
    assert t.phase == "end" and t.history[0] == 3.0
    assert _bal(chat, a) == START - 1000 + 2000 and _bal(chat, b) == START - 500
    assert t.view(a)["me"]["cash"] == 2.0 and t.view(b)["me"]["lost"]
    assert not profile.st(get_from_cache(chat, a))["pend"] and not profile.st(get_from_cache(chat, b))["pend"]


@pytest.mark.asyncio
async def test_roulette_round(monkeypatch):
    chat, a, b = -100500600721, 7101, 7102
    await _chat(chat, (a, "Красный"), (b, "Чёрный"))
    hub = await live.hub(chat)
    r = tables.table(hub, "roulette")
    r._new_round(time.time())
    async with _client() as c:
        ha, hb = _h(chat, a, "Красный"), _h(chat, b, "Чёрный")
        assert (await _post(c, "/api/v2/roulette", ha, kind="red", bet=1000))[1]["ok"]
        assert (await _post(c, "/api/v2/roulette", ha, kind="n", value=7, bet=100))[1]["ok"]
        assert (await _post(c, "/api/v2/roulette", hb, kind="black", bet=500))[1]["ok"]
        assert (await _post(c, "/api/v2/roulette", hb, kind="n", value=40, bet=100))[1]["ok"] is False
        monkeypatch.setattr(tables.rng, "randrange", lambda n: 7)
        await r.tick(r.t_next + 0.01)
        assert r.phase == "spin"
        st, d = await _post(c, "/api/v2/roulette", hb, kind="red", bet=100)
        assert d["ok"] is False
    await r.tick(r.t_next + 0.01)
    assert r.phase == "show" and r.view(a)["me"]["payout"] == 1000 * 2 + 100 * 36
    assert _bal(chat, a) == START - 1100 + 5600 and _bal(chat, b) == START - 500


@pytest.mark.asyncio
async def test_jackpot_round(monkeypatch):
    chat, a, b = -100500600722, 7201, 7202
    await _chat(chat, (a, "Банкир"), (b, "Вкладчик"))
    hub = await live.hub(chat)
    j = tables.table(hub, "jackpot")
    pool0 = hub.league["pool"]
    async with _client() as c:
        assert (await _post(c, "/api/v2/jackpot", _h(chat, a, "Банкир"), bet=3000))[1]["ok"]
        assert j.phase == "open"
        assert (await _post(c, "/api/v2/jackpot", _h(chat, b, "Вкладчик"), bet=1000))[1]["ok"]
        assert j.phase == "count"
    monkeypatch.setattr(tables.rng, "random", lambda: 0.1)   # билет 400 из 4000 → первый вкладчик
    await j.tick(j.t_next + 0.01)
    fee = int(4000 * PVP_FEE)
    assert j.phase == "draw" and j.winner == a and j.prize == 4000 - fee
    await j.tick(j.t_next + 0.01)
    assert j.phase == "done"
    assert _bal(chat, a) == START - 3000 + 4000 - fee and _bal(chat, b) == START - 1000
    assert hub.league["pool"] >= pool0 + fee


@pytest.mark.asyncio
async def test_duels(monkeypatch):
    chat, a, b, x = -100500600723, 7301, 7302, 7303
    await _chat(chat, (a, "Дуэлянт"), (b, "Соперник"), (x, "Зритель"))
    ha, hb, hx = _h(chat, a, "Дуэлянт"), _h(chat, b, "Соперник"), _h(chat, x, "Зритель")
    monkeypatch.setattr(tables.rng, "random", lambda: 0.3)   # монетка за создателя вызова
    async with _client() as c:
        await _post(c, "/api/v2/me", hb)
        st, d = await _post(c, "/api/v2/duel", ha, action="create", bet=2000)
        did = d["id"]
        assert d["ok"] and d["balance"] == START - 2000
        assert (await _post(c, "/api/v2/duel", ha, action="accept", id=did))[1]["ok"] is False
        st, d = await _post(c, "/api/v2/duel", hb, action="accept", id=did)
        assert d["ok"] and d["win"] is False and d["duel"]["winner_name"] == "Дуэлянт"
        assert (await _post(c, "/api/v2/duel", hx, action="accept", id=did))[1]["ok"] is False
        fee = int(4000 * PVP_FEE)
        assert _bal(chat, a) == START - 2000 + 4000 - fee and _bal(chat, b) == START - 2000
        # адресный вызов: чужой принять не может, создатель может отменить
        st, d = await _post(c, "/api/v2/duel", ha, action="create", bet=1000, target=security.handle_for(b))
        did = d["id"]
        assert d["duels"][0]["target_name"] == "Соперник"
        assert (await _post(c, "/api/v2/duel", hx, action="accept", id=did))[1]["ok"] is False
        st, d = await _post(c, "/api/v2/duel", ha, action="cancel", id=did)
        assert d["ok"] and d["balance"] == START - 2000 + 4000 - fee
        assert (await _post(c, "/api/v2/duel", ha, action="create", bet=100, target=security.handle_for(a)))[1]["ok"] is False


@pytest.mark.asyncio
async def test_shutdown_refunds_open_bets():
    chat, a = -100500600724, 7401
    await _chat(chat, (a, "Осторожный"))
    hub = await live.hub(chat)
    t = tables.table(hub, "crash")
    t._new_round(time.time())
    ctx = _ctx(chat, a, "Осторожный")
    await t.bet(ctx, 700, None)
    await tables.duel_create(hub, ctx, 300, None)
    assert _bal(chat, a) == START - 1000
    await tables.shutdown()
    assert _bal(chat, a) == START


# ───────────────────────── кошелёк, прогресс, экономика ─────────────────────────
@pytest.mark.asyncio
async def test_settle_is_idempotent_and_stale_refund():
    chat, a = -100500600730, 7501
    await _chat(chat, (a, "Аккуратный"))
    ctx = _ctx(chat, a, "Аккуратный")
    await wallet.stake(ctx, "crash", 1000, "crash:test1")
    res = await wallet.settle(chat, a, "Аккуратный", "crash", "crash:test1", 1000, 2500, mult=2.5)
    assert res["balance"] == START + 1500
    dup = await wallet.settle(chat, a, "Аккуратный", "crash", "crash:test1", 1000, 2500, mult=2.5)
    assert dup.get("dup") and _bal(chat, a) == START + 1500
    with pytest.raises(GameError):
        await wallet.stake(ctx, "crash", START * 10, "crash:test2")
    data = get_from_cache(chat, a)
    s = profile.st(data)
    s["pend"] = [{"id": "crash:gone", "g": "crash", "a": 400, "ts": int(time.time()) - 600},
                 {"id": "crash:fresh", "g": "crash", "a": 200, "ts": int(time.time())}]
    wallet.register_live("roul:alive")
    s["pend"].append({"id": "roul:alive:7501", "g": "roulette", "a": 300, "ts": int(time.time()) - 600})
    assert wallet.refund_stale(data, s) == 400
    assert [p["id"] for p in s["pend"]] == ["crash:fresh", "roul:alive:7501"]
    wallet.unregister_live("roul:alive")


@pytest.mark.asyncio
async def test_rake_tasks_and_fire():
    chat, a = -100500600731, 7601
    await _chat(chat, (a, "Работяга"))
    ctx = _ctx(chat, a, "Работяга")
    with pytest.raises(GameError):
        await eco.claim_rake(ctx)
    data = get_from_cache(chat, a)
    profile.st(data)["rake"] = 321
    wallet.save(chat, a, data)
    res = await eco.claim_rake(ctx)
    assert res["amount"] == 321 and res["balance"] == START + 321
    data = get_from_cache(chat, a)
    s = profile.st(data)
    assert s["rake"] == 0 and s["rake_total"] == 321
    profile.ensure_day(s, a)
    task = s["tasks"][0]
    with pytest.raises(GameError):
        await eco.claim_task(ctx, task["id"])
    task["p"] = profile.TASK_BY_ID[task["id"]][3]
    wallet.save(chat, a, data)
    res = await eco.claim_task(ctx, task["id"])
    assert res["reward"] == profile.task_reward(1) and res["balance"] == START + 321 + res["reward"]
    with pytest.raises(GameError):
        await eco.claim_task(ctx, task["id"])
    with pytest.raises(GameError):
        await eco.claim_task(ctx, "no_such_task")
    s["day"]["q"] = 27
    fire = eco.fire_view(s, a)
    assert fire["pct"] == 2 * eco.FIRE_PCT and fire["to_next"] == 3
    s["day"]["q"] = 10_000
    assert eco.fire_view(s, a)["pct"] == eco.FIRE_MAX_STEPS * eco.FIRE_PCT


def test_record_bet_progress():
    data = {"balance": 5000}
    s = profile.st(data)
    rec = profile.record_bet(data, 1, "slots", 1000, 3000, mult=3)
    assert rec["win"] and rec["rake"] == int(1000 * profile.rake_rate(data, s))
    assert s["stats"]["n"] == 1 and s["stats"]["w"] == 1 and s["stats"]["best"] == 2000
    assert s["games"]["slots"]["n"] == 1 and s["hist"][-1][1:] == ["slots", 1000, 3000, 3.0]
    assert any(e["type"] == "ach" and e["id"] == "first" for e in rec["events"])
    rec = profile.record_bet(data, 1, "bj", 100, 0)
    assert not rec["win"] and s["stats"]["streak"] == 0
    assert profile.record_bet(data, 1, "duel", 100, 0)["rake"] == 0


def test_levels_and_daily_tasks():
    for level in range(1, 60):
        assert profile.level_for_xp(profile.xp_for_level(level)) == level
        assert profile.xp_for_level(level + 1) > profile.xp_for_level(level)
    s1, s2 = profile.st({}), profile.st({})
    profile.ensure_day(s1, 42)
    profile.ensure_day(s2, 42)
    assert [t["id"] for t in s1["tasks"]] == [t["id"] for t in s2["tasks"]]
    assert len({t["id"] for t in s1["tasks"]}) == 3


def test_vip_unicorn_prestige_give_rakeback_not_odds():
    base = profile.rake_rate({}, profile.st({}))
    vip = profile.rake_rate({"is_vip": True, "pet": {"id": "unicorn"}}, profile.st({}))
    assert vip == pytest.approx(base + 0.006)
    assert profile.rake_rate({"is_vip": True, "pet": {"id": "unicorn"}}, profile.st({"v2": {"xp": 10 ** 9}})) <= 0.024


# ───────────────────────── статика и прочее ─────────────────────────
@pytest.mark.asyncio
async def test_static_and_avatar_routes():
    async with _client() as c:
        r = await c.get("/app/")
        html_text = await r.text()
        assert r.status == 200 and "Content-Security-Policy" in r.headers and "{{V}}" not in html_text
        ver = api._version()
        r = await c.get(f"/app/v/{ver}/js/main.js")
        assert r.status == 200 and "immutable" in r.headers["Cache-Control"]
        for bad in (f"/app/v/{ver}/%2e%2e/api.py", f"/app/v/{ver}/.hidden", f"/app/v/{ver}/nope.js"):
            assert (await c.get(bad)).status == 404
        assert (await c.get("/api/v2/av/hnope")).status == 404


def test_router_registers_v2_command():
    from v2.router import router
    assert router.name == "kazik_v2" and len(router.message.handlers) >= 2
