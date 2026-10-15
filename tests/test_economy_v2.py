"""Economy V2 regressions. No Telegram/Firestore/network/credentials required."""
import asyncio
import copy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from aiogram.types import Message
from aiogram.dispatcher.event.bases import UNHANDLED
from db import MockDB
from v2 import model, service, settings, heist
from v2 import router as routes

CHAT = -87654321
NOW = 2_000_000_000.0


@pytest.fixture
def game(monkeypatch, tmp_path):
    rows, locks = {}, {}
    clock = NS(now=NOW)
    rng = NS(random=lambda: 0.0, randint=lambda a, b: a, shuffle=lambda x: None)
    async def get(chat, uid):
        await asyncio.sleep(0)
        return copy.deepcopy(rows.setdefault((chat, uid), {"balance": 5000, "inventory": {}, "skills": {}}))
    def put(chat, uid, data):
        rows[chat, uid] = copy.deepcopy(data)
    def lock(chat, uid):
        # Use real reentrant semantics, including nested storage flush in raids.
        from user_manager import ReentrantLock
        return locks.setdefault((chat, uid), ReentrantLock())
    monkeypatch.setattr(service, "get_user_data", get)
    monkeypatch.setattr(service, "get_user_lock", lock)
    monkeypatch.setattr(service, "set_in_cache", put)
    monkeypatch.setattr(service, "mark_dirty", lambda *a: None)
    monkeypatch.setattr(service, "get_global_tax", AsyncMock(return_value=10))
    monkeypatch.setattr(service, "rng", rng)
    monkeypatch.setattr(service.time, "time", lambda: clock.now)
    monkeypatch.setattr(heist, "get_user_data", get)
    monkeypatch.setattr(heist, "get_user_lock", lock)
    monkeypatch.setattr(settings, "_cache", {})
    monkeypatch.setattr(settings, "_locks", {})
    db = MockDB(str(tmp_path / "db.json"))
    monkeypatch.setattr(settings, "get_db", lambda: db)
    monkeypatch.setattr(heist, "get_db", lambda: db)
    import user_manager
    monkeypatch.setattr(user_manager, "flush_user_cache_immediately", AsyncMock())
    return NS(rows=rows, clock=clock, rng=rng, get=get, put=put, db=db)


@pytest.mark.parametrize("xp,expected", [(0, 1), (99, 1), (100, 2), (1900, 20), (99999, 20), (-1, 1)])
def test_levels(xp, expected):
    assert model.level(xp) == expected


def test_regeneration_preserves_fraction_and_caps():
    data = {}
    s = model.state(data, NOW)
    s.update(energy=0, heat=100)
    model.state(data, NOW + 1250)
    assert s["energy"] == 10
    assert s["energy_at"] == NOW + 1200
    assert s["heat"] == 98
    model.state(data, NOW + 100_000)
    assert s["energy"] == 100 and s["heat"] == 0
    old = s.copy()
    model.state(data, NOW - 1)
    assert s["energy"] == old["energy"] and s["heat"] == old["heat"]


@pytest.mark.parametrize("resource", list(model.RESOURCES))
def test_market_deterministic_daily_prices(resource):
    price = model.market_price(CHAT, resource, NOW)
    assert price > 0
    assert price == model.market_price(CHAT, resource, NOW)
    assert model.event(CHAT, NOW) == model.event(CHAT, NOW)


@pytest.mark.asyncio
async def test_switch_default_off_and_persistent(game):
    assert not await settings.enabled(CHAT)
    await settings.set_enabled(CHAT, True, 1)
    settings._cache.clear()
    assert await settings.enabled(CHAT)
    await settings.set_enabled(CHAT, False, 1)
    settings._cache.clear()
    assert not await settings.enabled(CHAT)


@pytest.mark.asyncio
async def test_switch_failure_does_not_poison_cache(game, monkeypatch):
    await settings.set_enabled(CHAT, False, 1)
    monkeypatch.setattr(settings, "get_db", lambda: NS(collection=lambda _: NS(document=lambda _: NS(set=AsyncMock(side_effect=OSError())))))
    with pytest.raises(OSError):
        await settings.set_enabled(CHAT, True, 1)
    assert not await settings.enabled(CHAT)


@pytest.mark.asyncio
async def test_concurrent_work_only_once_and_shared_legacy_cooldown(game):
    results = await asyncio.gather(*(service.work(CHAT, 1) for _ in range(15)), return_exceptions=True)
    assert sum(not isinstance(x, Exception) for x in results) == 1
    d = await game.get(CHAT, 1)
    assert d["balance"] == 5000 + 216
    assert d["economy_v2"]["energy"] == 92
    assert d["last_work_time"] == NOW
    assert d["economy_v2"]["xp"]["courier"] == 25
    d["last_work_time"] = NOW - 1800
    game.put(CHAT, 1, d)
    await service.work(CHAT, 1)


@pytest.mark.asyncio
async def test_task_concurrent_clicks_once(game):
    _, nonce, choices = await service.work(CHAT, 1)
    before = (await game.get(CHAT, 1))["balance"]
    results = await asyncio.gather(*(service.solve_task(CHAT, 1, nonce, choices[0]) for _ in range(12)), return_exceptions=True)
    assert sum(not isinstance(x, Exception) for x in results) == 1
    assert (await game.get(CHAT, 1))["balance"] == before + 104


@pytest.mark.asyncio
async def test_task_wrong_answer_consumed_and_stale_nonce(game):
    _, nonce, _ = await service.work(CHAT, 1)
    before = (await game.get(CHAT, 1))["balance"]
    with pytest.raises(model.RuleError):
        await service.solve_task(CHAT, 1, "bad", 4)
    await service.solve_task(CHAT, 1, nonce, -999)
    with pytest.raises(model.RuleError):
        await service.solve_task(CHAT, 1, nonce, 4)
    assert (await game.get(CHAT, 1))["balance"] == before


@pytest.mark.asyncio
async def test_task_expiry(game):
    _, nonce, choices = await service.work(CHAT, 1)
    game.clock.now += 91
    with pytest.raises(model.RuleError):
        await service.solve_task(CHAT, 1, nonce, choices[0])


@pytest.mark.asyncio
async def test_daily_concurrent_streak_reset(game):
    results = await asyncio.gather(*(service.daily(CHAT, 1) for _ in range(10)), return_exceptions=True)
    assert sum(not isinstance(x, Exception) for x in results) == 1
    for _ in range(10):
        game.clock.now += 86400
        await service.daily(CHAT, 1)
    assert (await game.get(CHAT, 1))["economy_v2"]["streak"] == 7
    game.clock.now += 172800
    await service.daily(CHAT, 1)
    assert (await game.get(CHAT, 1))["economy_v2"]["streak"] == 1


@pytest.mark.asyncio
async def test_resource_cooldown_shared_and_sale_once(game):
    await service.gather(CHAT, 1, "mushroom")
    with pytest.raises(model.RuleError):
        await service.gather(CHAT, 1, "fish")
    results = await asyncio.gather(*(service.sell(CHAT, 1, "mushroom", "all") for _ in range(12)), return_exceptions=True)
    assert sum(not isinstance(x, Exception) for x in results) == 1
    assert (await game.get(CHAT, 1))["economy_v2"]["resources"]["mushroom"] == 0


@pytest.mark.parametrize("qty", ["-1", "0", "999999999", "NaN", "1.5", None])
@pytest.mark.asyncio
async def test_invalid_sale_no_payment(game, qty):
    await service.gather(CHAT, 1, "fish")
    before = await game.get(CHAT, 1)
    with pytest.raises(model.RuleError):
        await service.sell(CHAT, 1, "fish", qty)
    assert await game.get(CHAT, 1) == before


@pytest.mark.asyncio
async def test_tools_cap_costs_and_concurrent_purchases(game):
    game.put(CHAT, 1, {"balance": 20000})
    results = await asyncio.gather(*(service.purchase(CHAT, 1, "tools") for _ in range(10)), return_exceptions=True)
    assert sum(not isinstance(x, Exception) for x in results) == 5
    d = await game.get(CHAT, 1)
    assert d["balance"] == 20000 - 700 * sum(range(1, 6))
    assert d["economy_v2"]["tools"] == 5


@pytest.mark.asyncio
async def test_shield_no_repeat_charge(game):
    await service.purchase(CHAT, 1, "shield")
    with pytest.raises(model.RuleError):
        await service.purchase(CHAT, 1, "shield")
    assert (await game.get(CHAT, 1))["balance"] == 4750


@pytest.mark.asyncio
async def test_purchase_insufficient_no_partial_mutation(game):
    game.put(CHAT, 1, {"balance": 100})
    with pytest.raises(model.RuleError):
        await service.purchase(CHAT, 1, "tools")
    assert await game.get(CHAT, 1) == {"balance": 100}


@pytest.mark.asyncio
async def test_crime_failure_finite_fine_and_jail_bail(game):
    game.rng.random = lambda: 1.0
    d = {"balance": 30}
    s = model.state(d, NOW)
    s["heat"] = 70
    game.put(CHAT, 1, d)
    await service.crime(CHAT, 1, "convoy")
    d = await game.get(CHAT, 1)
    assert d["balance"] == 0
    assert d["economy_v2"]["jail_until"] == NOW + 900
    with pytest.raises(model.RuleError):
        await service.work(CHAT, 1)
    d["balance"] = 1000
    game.put(CHAT, 1, d)
    await service.purchase(CHAT, 1, "bail")
    d = await game.get(CHAT, 1)
    assert d["balance"] == 100 and d["economy_v2"]["jail_until"] == 0


@pytest.mark.parametrize("kind", list(model.CRIMES))
@pytest.mark.asyncio
async def test_crime_success_and_common_timestamp(game, kind):
    await service.crime(CHAT, 1, kind)
    assert (await game.get(CHAT, 1))["balance"] > 5000
    with pytest.raises(model.RuleError):
        await service.crime(CHAT, 1, "convoy")


@pytest.mark.asyncio
async def test_quests_exact_requirements_and_once(game):
    with pytest.raises(model.RuleError):
        await service.quest_claim(CHAT, 1)
    for _ in range(2):
        await service.work(CHAT, 1)
        await service.gather(CHAT, 1, "ore")
        game.clock.now += 1800
    await service.sell(CHAT, 1, "ore", "all")
    before = (await game.get(CHAT, 1))["balance"]
    results = await asyncio.gather(*(service.quest_claim(CHAT, 1) for _ in range(10)), return_exceptions=True)
    assert sum(not isinstance(x, Exception) for x in results) == 1
    assert (await game.get(CHAT, 1))["balance"] == before + 500
    game.clock.now += 86400
    with pytest.raises(model.RuleError):
        await service.quest_claim(CHAT, 1)


@pytest.mark.asyncio
async def test_theft_conserves_currency_and_chase_once(game):
    text, nonce = await service.steal(CHAT, 1, 2)
    assert nonce and "400" in text
    a, b = await game.get(CHAT, 1), await game.get(CHAT, 2)
    assert a["balance"] + b["balance"] == 10000
    assert (a["balance"], b["balance"]) == (5400, 4600)
    results = await asyncio.gather(*(service.chase(CHAT, 2, nonce) for _ in range(10)), return_exceptions=True)
    assert sum(not isinstance(x, Exception) for x in results) == 1
    assert (await game.get(CHAT, 1))["balance"] == 5000
    assert (await game.get(CHAT, 2))["balance"] == 5000


@pytest.mark.asyncio
async def test_chase_does_not_mint_currency_after_loot_spent(game):
    _, nonce = await service.steal(CHAT, 1, 2)
    d = await game.get(CHAT, 1)
    d["balance"] = 50
    game.put(CHAT, 1, d)
    await service.chase(CHAT, 2, nonce)
    assert (await game.get(CHAT, 1))["balance"] == 0
    assert (await game.get(CHAT, 2))["balance"] == 4650


@pytest.mark.asyncio
async def test_chase_expiry(game):
    _, nonce = await service.steal(CHAT, 1, 2)
    game.clock.now += 121
    with pytest.raises(model.RuleError):
        await service.chase(CHAT, 2, nonce)


@pytest.mark.parametrize("protection", ["newbie", "bunker", "shield", "poor", "victim_cooldown"])
@pytest.mark.asyncio
async def test_theft_protection_no_attacker_charge(game, protection):
    d = {"balance": 5000}
    s = model.state(d, NOW)
    s["joined"] = NOW - 90000
    if protection == "newbie":
        s["joined"] = NOW
    elif protection == "bunker":
        d["inventory"] = {"sec_bunker": 1}
    elif protection == "shield":
        s["shield_until"] = NOW + 100
    elif protection == "poor":
        d["balance"] = 999
    else:
        s["last_victim_at"] = NOW - 10
    game.put(CHAT, 2, d)
    with pytest.raises(model.RuleError):
        await service.steal(CHAT, 1, 2)
    assert (await game.get(CHAT, 1))["balance"] == 5000
    assert (await game.get(CHAT, 1)).get("last_steal_time", 0) == 0


@pytest.mark.asyncio
async def test_theft_failure_consumes_once_items_and_removes_shield(game):
    game.rng.random = lambda: 1.0
    d = {"balance": 5000, "inventory": {"mask": 1, "lockpick": 1}}
    model.state(d, NOW)["shield_until"] = NOW + 1000
    game.put(CHAT, 1, d)
    _, nonce = await service.steal(CHAT, 1, 2)
    assert nonce is None
    d = await game.get(CHAT, 1)
    assert d["balance"] == 4930
    assert d["inventory"] == {"mask": 0, "lockpick": 0}
    assert d["economy_v2"]["shield_until"] == 0
    with pytest.raises(model.RuleError):
        await service.steal(CHAT, 1, 3)


@pytest.mark.asyncio
async def test_opposite_thefts_no_deadlock(game):
    for uid in (1, 2):
        d = {"balance": 5000}
        model.state(d, NOW)["joined"] = NOW - 90000
        game.put(CHAT, uid, d)
    result = await asyncio.wait_for(asyncio.gather(service.steal(CHAT, 1, 2), service.steal(CHAT, 2, 1), return_exceptions=True), 2)
    assert len(result) == 2
    assert (await game.get(CHAT, 1))["balance"] + (await game.get(CHAT, 2))["balance"] == 10000


@pytest.mark.asyncio
async def test_raid_membership_and_idempotency(game):
    await heist.run(CHAT, 1, "create")
    await heist.run(CHAT, 2, "join")
    with pytest.raises(model.RuleError):
        await heist.run(CHAT, 2, "join")
    with pytest.raises(model.RuleError):
        await heist.run(CHAT, 2, "start")
    await heist.run(CHAT, 1, "start")
    before = await game.get(CHAT, 1)
    assert before["economy_v2"]["energy"] == 80
    assert before["balance"] in (5080, 5490)
    with pytest.raises(model.RuleError):
        await heist.run(CHAT, 1, "start")
    assert await game.get(CHAT, 1) == before


@pytest.mark.asyncio
async def test_raid_invalid_member_charges_no_one(game):
    await heist.run(CHAT, 1, "create")
    await heist.run(CHAT, 2, "join")
    d = {"balance": 5000}
    model.state(d, NOW)["energy"] = 0
    game.put(CHAT, 2, d)
    with pytest.raises(model.RuleError):
        await heist.run(CHAT, 1, "start")
    assert (await game.get(CHAT, 1))["balance"] == 5000
    assert (await game.get(CHAT, 1)).get("economy_v2") is None


@pytest.mark.asyncio
async def test_raid_resume_after_flush_failure_no_duplicate(game, monkeypatch):
    import user_manager
    await heist.run(CHAT, 1, "create")
    await heist.run(CHAT, 2, "join")
    monkeypatch.setattr(user_manager, "flush_user_cache_immediately", AsyncMock(side_effect=OSError("storage down")))
    with pytest.raises(OSError):
        await heist.run(CHAT, 1, "start")
    before = await game.get(CHAT, 1)
    assert (await heist.reference(CHAT).get()).to_dict()["status"] == "settling"
    monkeypatch.setattr(user_manager, "flush_user_cache_immediately", AsyncMock())
    await heist.run(CHAT, 1, "start")
    assert await game.get(CHAT, 1) == before


@pytest.mark.asyncio
async def test_raid_capacity_cancel_expiry(game):
    await heist.run(CHAT, 1, "create")
    for uid in range(2, 6):
        await heist.run(CHAT, uid, "join")
    with pytest.raises(model.RuleError):
        await heist.run(CHAT, 6, "join")
    with pytest.raises(model.RuleError):
        await heist.run(CHAT, 2, "cancel")
    await heist.run(CHAT, 1, "cancel")
    await heist.run(CHAT, 1, "create")
    game.clock.now += 601
    with pytest.raises(model.RuleError):
        await heist.run(CHAT, 2, "join")


def message(text, uid=1):
    return NS(text=text, chat=NS(id=CHAT, type="supergroup"),
              from_user=NS(id=uid, is_bot=False), answer=AsyncMock())


@pytest.mark.asyncio
async def test_toggle_authorized_creator_only(game, monkeypatch):
    monkeypatch.setattr(routes, "CREATOR_IDS", {99})
    m = message("/v2 on", uid=1)
    await routes.toggle(m)
    assert not await settings.enabled(CHAT)
    m = message("/v2@kazik_bot on", uid=99)
    await routes.toggle(m)
    assert await settings.enabled(CHAT)
    assert "не отдельная песочница" in m.answer.call_args.args[0]
    await routes.toggle(message("/v2 off", uid=99))
    assert not await settings.enabled(CHAT)


@pytest.mark.asyncio
async def test_execute_off_no_operation_and_chat_isolation(game):
    op = AsyncMock(return_value="done")
    with pytest.raises(model.RuleError):
        await routes.execute(CHAT, 1, op)
    op.assert_not_awaited()
    await settings.set_enabled(CHAT, True, 1)
    assert await routes.execute(CHAT, 1, op) == "done"
    assert not await settings.enabled(CHAT - 1)


@pytest.mark.asyncio
async def test_toggle_waits_for_inflight_action(game):
    await settings.set_enabled(CHAT, True, 1)
    entered, release = asyncio.Event(), asyncio.Event()
    async def op():
        entered.set()
        await release.wait()
        return "ok"
    task = asyncio.create_task(routes.execute(CHAT, 1, op))
    await entered.wait()
    async def off():
        async with settings.switch_lock(CHAT):
            await settings.set_enabled(CHAT, False, 1)
    off_task = asyncio.create_task(off())
    await asyncio.sleep(0)
    assert not off_task.done()
    release.set()
    await asyncio.gather(task, off_task)
    assert not await settings.enabled(CHAT)


@pytest.mark.asyncio
async def test_router_off_falls_through_and_on_handles_work(game, monkeypatch):
    from datetime import datetime, timezone
    reply = AsyncMock()
    monkeypatch.setattr(Message, "answer", reply)
    m = Message(message_id=1, date=datetime.now(timezone.utc),
                chat={"id": CHAT, "type": "supergroup"},
                from_user={"id": 1, "is_bot": False, "first_name": "Test"}, text="/work")
    assert await routes.router.propagate_event("message", m, bot=NS(me=AsyncMock(return_value=NS(username="kazik_bot")))) is UNHANDLED
    await settings.set_enabled(CHAT, True, 1)
    await routes.router.propagate_event("message", m, bot=NS(me=AsyncMock(return_value=NS(username="kazik_bot"))))
    reply.assert_awaited_once()
    assert "Премия за точность" in reply.call_args.args[0]


@pytest.mark.asyncio
async def test_callback_actor_binding_and_off_mode(game):
    # isinstance guard requires a real Telegram Message; outbound methods patched.
    from datetime import datetime, timezone
    m = Message(message_id=1, date=datetime.now(timezone.utc), chat={"id": CHAT, "type": "supergroup"})
    cb = NS(data="v2:menu:2:daily", message=m, from_user=NS(id=1), answer=AsyncMock())
    await settings.set_enabled(CHAT, True, 1)
    await routes.callbacks(cb)
    assert "другому" in cb.answer.call_args.args[0]
    cb.data = "v2:menu:1:daily"
    await settings.set_enabled(CHAT, False, 1)
    await routes.callbacks(cb)
    assert "выключена" in cb.answer.call_args.args[0]
    assert not game.rows


@pytest.mark.asyncio
async def test_steal_api_failure_and_admin_block(game, monkeypatch):
    monkeypatch.setattr(routes, "CREATOR_IDS", {99})
    m = message("/steal")
    m.reply_to_message = NS(from_user=NS(id=2, is_bot=False), sender_chat=None)
    m.bot = NS(get_chat_member=AsyncMock(side_effect=OSError()))
    await routes.steal(m)
    assert "не выполнена" in m.answer.call_args.args[0]
    m.bot.get_chat_member = AsyncMock(return_value=NS(status="administrator"))
    await routes.steal(m)
    assert "защищена" in m.answer.call_args.args[0]
    assert not game.rows


@pytest.mark.parametrize("career,energy", [("courier", 8), ("mechanic", 12), ("analyst", 16)])
@pytest.mark.asyncio
async def test_careers_distinct_cost_and_independent_xp(game, career, energy):
    await service.career(CHAT, 1, career)
    await service.work(CHAT, 1)
    s = (await game.get(CHAT, 1))["economy_v2"]
    assert s["energy"] == 100 - energy
    assert s["xp"][career] == 25
    await service.career(CHAT, 1, "courier")
    assert (await game.get(CHAT, 1))["economy_v2"]["xp"][career] == 25


@pytest.mark.asyncio
async def test_real_cache_flush_reload_includes_task_receipt(monkeypatch, tmp_path):
    from collections import OrderedDict
    import user_manager as um
    db = MockDB(str(tmp_path / "actual.json"))
    monkeypatch.setattr(um, "get_db", lambda: db)
    monkeypatch.setattr(um, "_user_cache", OrderedDict())
    monkeypatch.setattr(um, "_dirty_cache", set())
    monkeypatch.setattr(um, "_user_locks", {})
    monkeypatch.setattr(um, "_username_to_id_cache", {})
    monkeypatch.setattr(service, "get_global_tax", AsyncMock(return_value=10))
    uid = 76543
    await um.get_user_ref(CHAT, uid).set({"balance": 5000, "inventory": {}, "skills": {}})
    _, nonce, choices = await service.work(CHAT, uid)
    task = (await um.get_user_data(CHAT, uid))["economy_v2"]["task"]
    await service.solve_task(CHAT, uid, nonce, task["answer"])
    before = await um.get_user_data(CHAT, uid)
    await um.flush_user_cache_immediately(CHAT, uid)
    # Simulated new process: clear cache AND recreate DB from the JSON file.
    um._user_cache.clear()
    db = MockDB(db.filepath)
    after = await um.get_user_data(CHAT, uid)
    assert after == before
    with pytest.raises(model.RuleError):
        await service.solve_task(CHAT, uid, nonce, choices[0])


@pytest.mark.asyncio
async def test_settings_reload_from_file(game, monkeypatch):
    await settings.set_enabled(CHAT, True, 1)
    restored = MockDB(game.db.filepath)
    settings._cache.clear()
    monkeypatch.setattr(settings, "get_db", lambda: restored)
    assert await settings.enabled(CHAT)


@pytest.mark.asyncio
async def test_menu_task_and_chase_buttons_fit_telegram_limit(game):
    for row in routes.menu_keyboard(999999999999).inline_keyboard:
        assert all(len(b.callback_data.encode()) <= 64 for b in row)
    _, nonce, choices = await service.work(CHAT, 1)
    assert len(f"v2:task:999999999999:{nonce}:{choices[0]}".encode()) <= 64
    _, nonce = await service.steal(CHAT, 2, 3)
    assert len(f"v2:chase:999999999999:{nonce}".encode()) <= 64
