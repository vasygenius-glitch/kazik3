"""Opt-in game service; serialized against the existing per-user locks.

Cache writes use the same write-behind persistence as the original economy.
Multi-user changes are atomic inside ONE event loop (no await between commits),
not distributed Firestore transactions. Run exactly one bot process.
"""
import secrets
import time
from contextlib import AsyncExitStack
from user_manager import get_user_data, get_user_lock, set_in_cache, mark_dirty
from economy_utils import get_global_tax, calculate_progressive_tax
from v2.model import (
    CAREERS, CAREER_ENERGY, TOOL_BONUS, CRIMES, RESOURCES, RuleError, WORK_COOLDOWN, CRIME_COOLDOWN,
    STEAL_COOLDOWN, GATHER_COOLDOWN, state, level, active, cooldown,
    spend, credit, progress, experience, market_price,
)

rng = secrets.SystemRandom()


def commit(chat_id, uid, data):
    set_in_cache(chat_id, uid, data)
    mark_dirty(chat_id, uid)


async def payout(chat_id, data, s, gross, kind):
    """V2 keeps existing tax, negotiation and work-cat effects, with bounded payouts."""
    pet = data.get("pet") or {}
    pet_id = pet.get("id") if isinstance(pet, dict) else None
    if kind == "work" and pet_id == "cat":
        gross = int(gross * 1.2)
    rate = calculate_progressive_tax(
        data.get("balance", 0), await get_global_tax(),
        (data.get("skills") or {}).get("negotiation", 0), pet_id,
    )
    net = max(0, int(gross) - int(gross * rate / 100))
    credit(data, s, net)
    return net, int(gross) - net


async def profile(chat_id, uid):
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, time.time())
        commit(chat_id, uid, data)
        return data, s


async def career(chat_id, uid, name):
    if name not in CAREERS:
        raise RuleError("Профессии: /career courier, /career mechanic, /career analyst")
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, time.time())
        active(s, time.time())
        s["career"] = name
        commit(chat_id, uid, data)
    return f"Профессия: {CAREERS[name][0]}. Опыт каждой профессии сохраняется отдельно."


async def work(chat_id, uid):
    now = time.time()
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, now)
        cooldown(data.get("last_work_time", 0), WORK_COOLDOWN, now)
        key = s["career"]
        active(s, now, CAREER_ENERGY[key])
        name, low, high = CAREERS[key]
        lvl = level(s["xp"].get(key, 0))
        gross = rng.randint(low, high) + (lvl - 1) * 45 + s["tools"] * TOOL_BONUS[key]
        net, tax = await payout(chat_id, data, s, gross, "work")
        data["last_work_time"] = now
        s["heat"] = max(0, s["heat"] - 8)
        new_lvl = experience(s, key, 25)
        progress(s, "work")
        nonce = secrets.token_hex(5)
        a, b = rng.randint(2, 9), rng.randint(2, 9)
        choices = [a + b, a + b + 1, a + b - 1]
        rng.shuffle(choices)
        # Store only one active task. Repeated clicks are consumed before payment.
        s["task"] = {"id": nonce, "answer": a + b, "expires": now + 90, "bonus": (200 + lvl * 25) if key == "analyst" else (100 + lvl * 15)}
        commit(chat_id, uid, data)
    return (f"{name} • уровень {new_lvl}\n💰 +{net} сыр. (налог {tax}) • +25 опыта\n"
            f"⚡ {s['energy']}/100 • розыск −8\n\n🧠 Премия за точность: {a} + {b} = ? (90 секунд)", nonce, choices)


async def solve_task(chat_id, uid, nonce, answer):
    now = time.time()
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, now)
        task = s.get("task")
        if not task or task["id"] != nonce:
            raise RuleError("Задание уже закрыто или заменено новой сменой.")
        if now > task["expires"]:
            raise RuleError("Время на премию вышло.")
        s.pop("task")
        if answer == task["answer"]:
            net, _ = await payout(chat_id, data, s, task["bonus"], "task")
            text = f"✅ Верно! Премия +{net} сыр."
        else:
            text = "❌ Ошибка. Зарплата остаётся у тебя, но премии не будет."
        commit(chat_id, uid, data)
        return text


async def crime(chat_id, uid, kind):
    if kind not in CRIMES:
        raise RuleError("Выбери риск: /crime pickpocket, /crime burglary или /crime convoy")
    now = time.time()
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, now)
        cooldown(data.get("last_crime_time", 0), CRIME_COOLDOWN, now)
        active(s, now, 18)
        name, chance, low, high, heat, fine = CRIMES[kind]
        stealth = min(10, (data.get("skills") or {}).get("stealth", 0))
        chance = max(.12, min(.88, chance + stealth * .02 - s["heat"] * .004))
        s["heat"] = min(100, s["heat"] + heat)
        data["last_crime_time"] = now
        success = rng.random() < chance
        if success:
            net, tax = await payout(chat_id, data, s, rng.randint(low, high), "crime")
            text = f"{name}: успех! +{net} сыр. (налог {tax})."
            experience(s, "crime", 30)
        else:
            loss = min(max(0, int(data.get("balance", 0))), fine)
            data["balance"] -= loss
            s["spent"] += loss
            s["heat"] = min(100, s["heat"] + 12)
            text = f"{name}: провал! Штраф {loss} сыр."
            experience(s, "crime", 10)
        if s["heat"] >= 80:
            s["jail_until"] = now + 900
            text += "\n🚔 Арест на 15 минут. Можно подождать или /bail."
        progress(s, "crime")
        commit(chat_id, uid, data)
        return text + f"\n🚨 Розыск {s['heat']}/100 (−1 за 7,5 минуты)."


async def gather(chat_id, uid, resource):
    if resource not in RESOURCES:
        raise RuleError("Добыча: /gather mushroom, /gather fish, /gather ore")
    now = time.time()
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, now)
        cooldown(s["actions"].get("gather", 0), GATHER_COOLDOWN, now)
        active(s, now, 8)
        name, _, low, high = RESOURCES[resource]
        count = rng.randint(low, high) + min(3, (level(s["xp"].get("gather", 0)) - 1) // 3)
        rare = rng.random() < .06
        if rare:
            count *= 2
        s["resources"][resource] = s["resources"].get(resource, 0) + count
        s["actions"]["gather"] = now
        experience(s, "gather", 20)
        progress(s, "gather")
        commit(chat_id, uid, data)
        return f"{name}: +{count} шт." + (" ✨ Редкая находка!" if rare else "") + "\nПродай на /market командой /sell."


async def sell(chat_id, uid, resource, quantity):
    if resource not in RESOURCES:
        raise RuleError("Пример: /sell mushroom all или /sell fish 3")
    now = time.time()
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, now)
        active(s, now)
        have = s["resources"].get(resource, 0)
        if quantity == "all":
            amount = have
        else:
            try:
                amount = int(quantity)
            except (ValueError, TypeError):
                raise RuleError("Количество — целое положительное число или all.") from None
        if amount <= 0 or amount > have:
            raise RuleError(f"В рюкзаке {have} шт. Нельзя продать больше или отрицательное количество.")
        gross = amount * market_price(chat_id, resource, now)
        net, tax = await payout(chat_id, data, s, gross, "market")
        s["resources"][resource] = have - amount
        progress(s, "sell")
        commit(chat_id, uid, data)
        return f"📦 Продано {amount} шт.: +{net} сыр. (налог {tax})."


async def daily(chat_id, uid):
    now = time.time()
    day = int(now) // 86400
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, now)
        if s["daily_day"] == day:
            raise RuleError("🎁 Награда уже получена. Новая — после 00:00 UTC.")
        s["streak"] = min(7, s["streak"] + 1) if s["daily_day"] == day - 1 else 1
        s["daily_day"] = day
        reward = 150 + 50 * s["streak"]
        credit(data, s, reward)
        s["energy"] = min(100, s["energy"] + 20)
        commit(chat_id, uid, data)
        return f"🎁 Серия {s['streak']}/7: +{reward} сыр. и +20 энергии. Пропуск дня сбрасывает серию."


async def quest_claim(chat_id, uid):
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, time.time())
        if s["quest_claimed"]:
            raise RuleError("Награда за задания сегодня уже получена.")
        if any(s["quests"].get(key, 0) < need for key, need in (("work", 2), ("gather", 2), ("sell", 1))):
            raise RuleError("Нужно: 2 смены, 2 добычи и 1 продажа. Прогресс — /eco.")
        s["quest_claimed"] = True
        credit(data, s, 500)
        commit(chat_id, uid, data)
        return "🏆 Дневные задания выполнены: +500 сыр.!"


async def purchase(chat_id, uid, kind):
    now = time.time()
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, now)
        if kind == "bail":
            if s["jail_until"] <= now:
                raise RuleError("Ты не под арестом.")
            cost = 400 + s["heat"] * 5
            spend(data, s, cost)
            s.update(jail_until=0, heat=35)
            text = f"🔓 Залог {cost} сыр. уплачен. Розыск снижен до 35."
        elif kind == "shield":
            if s["shield_until"] > now:
                raise RuleError("Щит уже действует. Продление доступно после истечения.")
            spend(data, s, 250)
            s["shield_until"] = now + 86400
            text = "🛡 Защита от краж на 24 часа за 250 сыр. Атака снимает её."
        elif kind == "tools":
            active(s, now)
            if s["tools"] >= 5:
                raise RuleError("Инструменты уже максимального уровня 5.")
            cost = 700 * (s["tools"] + 1)
            spend(data, s, cost)
            s["tools"] += 1
            text = f"🧰 Инструменты ур. {s['tools']}/5 за {cost} сыр. Бонус за уровень: курьер +20, механик +60, аналитик +35."
        else:
            raise RuleError("Неизвестная покупка.")
        commit(chat_id, uid, data)
        return text


async def rest(chat_id, uid):
    now = time.time()
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = state(data, now)
        cooldown(s["actions"].get("rest", 0), 3600, now)
        if s["energy"] >= 100:
            raise RuleError("Энергия уже полная.")
        s["energy"] = min(100, s["energy"] + 20)
        s["heat"] = max(0, s["heat"] - 10)
        s["actions"]["rest"] = now
        commit(chat_id, uid, data)
        return f"🛏 Отдых: +20 энергии, −10 розыска. Энергия {s['energy']}/100."


async def steal(chat_id, uid, victim):
    if uid == victim:
        raise RuleError("У себя воровать нельзя.")
    now = time.time()
    async with AsyncExitStack() as stack:
        for who in sorted((uid, victim)):
            await stack.enter_async_context(get_user_lock(chat_id, who))
        data = await get_user_data(chat_id, uid)
        target = await get_user_data(chat_id, victim)
        target_had_v2 = bool(target.get("economy_v2"))
        s, t = state(data, now), state(target, now)
        cooldown(data.get("last_steal_time", 0), STEAL_COOLDOWN, now)
        cooldown(t["last_victim_at"], 7200, now)
        inv = target.get("inventory") or {}
        if inv.get("sec_bunker", 0) or t["shield_until"] > now:
            raise RuleError("🛡 Цель защищена бункером или щитом.")
        if target.get("balance", 0) < 1000:
            raise RuleError("🕊 Баланс ниже 1000 сыр. защищён от краж.")
        # V2 newcomers are protected for a day; legacy players without V2 remain protected
        # by balance floor and victim cooldown, not an invented registration timestamp.
        if target_had_v2 and not t.get("newbie_waived") and now - t["joined"] < 86400:
            raise RuleError("🕊 Первый день в новой экономике: новичка грабить нельзя.")
        if data.get("balance", 0) < 300:
            raise RuleError("Для риска нужно минимум 300 сыр.")
        active(s, now, 15)
        s["shield_until"] = 0
        s["newbie_waived"] = True
        data["last_steal_time"] = now
        t["last_victim_at"] = now
        stealth = min(10, (data.get("skills") or {}).get("stealth", 0))
        pet = data.get("pet") or {}
        pet_id = pet.get("id") if isinstance(pet, dict) else None
        chance = .35 + stealth * .025 + (.1 if pet_id == "fox" else 0) - s["heat"] * .003
        chance -= .08 if target.get("is_vip") else 0
        inventory = data.get("inventory") or {}
        if inventory.get("lockpick", 0) > 0:
            inventory["lockpick"] -= 1
            data["inventory"] = inventory
            chance += .1
        masked = inventory.get("mask", 0) > 0
        if masked:
            inventory["mask"] -= 1
            data["inventory"] = inventory
        s["heat"] = min(100, s["heat"] + (10 if masked else 20))
        success = rng.random() < max(.1, min(.7, chance))
        nonce = None
        if success:
            # Preserve 500 currency for the victim. No newly minted PvP money.
            loot = min(800, int(target["balance"] * .08), max(0, target["balance"] - 500))
            target["balance"] -= loot
            credit(data, s, loot)
            nonce = secrets.token_hex(5)
            t["chase"] = {"id": nonce, "thief": uid, "amount": loot, "expires": now + 120}
            text = f"🥷 Украдено {loot} сыр. У жертвы 2 минуты на погоню!"
        else:
            fine = min(70 if masked else 200, max(0, data.get("balance", 0)))
            data["balance"] -= fine
            s["spent"] += fine
            text = f"🚨 Попался! Штраф {fine} сыр. Защита цели от повторных атак: 2 часа."
        if s["heat"] >= 80:
            s["jail_until"] = now + 900
            text += "\n🚔 Арест на 15 минут. /bail — залог."
        experience(s, "steal", 20 if success else 5)
        # No await between the two cache changes: concurrent legacy balance updates
        # cannot interleave here. Both dirty entries are persisted by the standard flusher.
        commit(chat_id, uid, data)
        commit(chat_id, victim, target)
        return text, nonce


async def chase(chat_id, victim, nonce):
    # Re-read after obtaining both locks; stale/changed chase must never be paid.
    target = await get_user_data(chat_id, victim)
    pending = (target.get("economy_v2") or {}).get("chase")
    if not pending or pending["id"] != nonce:
        raise RuleError("Погоня уже закрыта.")
    thief = pending["thief"]
    async with AsyncExitStack() as stack:
        for who in sorted((victim, thief)):
            await stack.enter_async_context(get_user_lock(chat_id, who))
        target = await get_user_data(chat_id, victim)
        data = await get_user_data(chat_id, thief)
        now = time.time()
        t, s = state(target, now), state(data, now)
        pending = t.get("chase")
        if not pending or pending["id"] != nonce:
            raise RuleError("Погоня уже закрыта.")
        if pending["expires"] < now:
            raise RuleError("Вор ушёл: на погоню давалось 2 минуты.")
        t.pop("chase")
        # Deterministic restitution, but never create debt if the loot was spent.
        amount = min(pending["amount"], max(0, int(data.get("balance", 0))))
        data["balance"] -= amount
        target["balance"] = int(target.get("balance", 0)) + amount
        s["spent"] += amount
        s["heat"] = min(100, s["heat"] + 15)
        if s["heat"] >= 80:
            s["jail_until"] = now + 900
        commit(chat_id, thief, data)
        commit(chat_id, victim, target)
        return f"🚓 Погоня завершена! Возвращено {amount} из {pending['amount']} сыр. (в пределах остатка у вора)."
