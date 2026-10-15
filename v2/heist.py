"""Cost-free co-op expeditions. Journaled outcome, idempotent per-user rewards.

The router holds the per-chat switch lock, so membership and settlement cannot
race on the supported single-process deployment. No background timer is needed.
"""
import secrets
import time
from contextlib import AsyncExitStack
from db import get_db
from user_manager import get_user_data, get_user_lock
from v2.model import RuleError, state, active, cooldown, credit, experience
from v2.service import commit


def reference(chat):
    return get_db().collection("chats").document(str(chat)).collection("v2").document("heist")


async def run(chat, uid, action):
    ref = reference(chat)
    snap = await ref.get()
    h = (snap.to_dict() or {}) if snap.exists else {}
    now = time.time()
    if action == "create":
        if h.get("status") == "settling":
            raise RuleError("Предыдущий рейд требует завершения: лидер должен ввести /heist start.")
        if h.get("status") == "open" and h.get("expires", 0) > now:
            raise RuleError("Сбор уже идёт. /heist join — вступить; /heist start — начать.")
        h = {"id": secrets.token_hex(8), "leader": uid, "members": [uid],
             "expires": now + 600, "status": "open"}
        await ref.set(h)
        return "🤝 Кооперативный рейд! Сбор 10 минут, 2–5 игроков.\n/heist join — вступить; лидер: /heist start. Взноса нет; затраты 20 энергии, откат 2 часа."
    if action == "join":
        if h.get("status") != "open" or h.get("expires", 0) <= now:
            raise RuleError("Открытого сбора нет. /heist create")
        if uid in h["members"]:
            raise RuleError("Ты уже в команде.")
        if len(h["members"]) >= 5:
            raise RuleError("Команда уже полная: 5 игроков.")
        # Admission does not charge anything. Recheck energy/cooldown at settlement.
        h["members"].append(uid)
        await ref.set(h)
        return f"🤝 Ты в команде! Участников: {len(h['members'])}/5."
    if action == "cancel":
        if h.get("leader") != uid or h.get("status") != "open":
            raise RuleError("Отменить открытый сбор может только лидер.")
        h["status"] = "cancelled"
        await ref.set(h)
        return "Сбор отменён. Взносов не было."
    if action != "start":
        raise RuleError("Рейд: /heist create, /heist join, /heist start, /heist cancel")
    if h.get("leader") != uid:
        raise RuleError("Начать рейд может только лидер.")
    if h.get("status") not in ("open", "settling"):
        raise RuleError("Сбор уже закрыт. /heist create — новый рейд.")
    if h["status"] == "open" and h["expires"] < now:
        raise RuleError("Время сбора вышло. /heist create — новый рейд.")
    if len(h["members"]) < 2:
        raise RuleError("Нужно минимум 2 участника.")
    async with AsyncExitStack() as stack:
        for member in sorted(h["members"]):
            await stack.enter_async_context(get_user_lock(chat, member))
        rows = {}
        if h["status"] == "open":
            # Validate everyone before spending anyone's energy.
            for member in h["members"]:
                data = await get_user_data(chat, member)
                s = state(data, now)
                cooldown(s["actions"].get("heist", 0), 7200, now)
                active(s, now, 20)
                rows[member] = data
            # Persist outcome first. Retrying after an error cannot reroll it.
            h.update(status="settling", success=secrets.randbelow(100) < 55 + len(h["members"]) * 5,
                     reward=350 + len(h["members"]) * 70, settled_at=now)
            await ref.set(h)
        for member in h["members"]:
            data = rows.get(member) or await get_user_data(chat, member)
            s = state(data, now)
            if s.get("heist_receipt") == h["id"]:
                continue
            if member not in rows:
                # Recovery of an already journaled settlement. Charge energy once,
                # without blocking a partially completed raid on later jail status.
                s["energy"] = max(0, s["energy"] - 20)
            s["heist_receipt"] = h["id"]
            s["actions"]["heist"] = h["settled_at"]
            credit(data, s, h["reward"] if h["success"] else 80)
            experience(s, "heist", 30)
            commit(chat, member, data)
        # Flush receipts together with their reward before closing the journal.
        from user_manager import flush_user_cache_immediately
        for member in h["members"]:
            await flush_user_cache_immediately(chat, member)
        h["status"] = "done"
        await ref.set(h)
    return (f"🏆 Рейд удался! Каждый из {len(h['members'])} участников получил {h['reward']} сыр."
            if h["success"] else "🧯 Рейд сорвался. Каждый получил утешительные 80 сыр.; денег никто не потерял.")
