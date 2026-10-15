"""Старые источники дохода внутри Mini App: бонус, работа, «дело» и премии.

Логика повторяет команды /bonus, /work и /crime (коллекторы, банкиры, питомцы,
лобби, сезоны, болезни), поэтому чат-команды и приложение дают одно и то же.
Новое — только «огонёк»: активная игра в казино поднимает следующий бонус.
"""
import html
import re
import secrets
import time
import uuid

from user_manager import get_user_lock
from v2 import profile
from v2.wallet import Ctx, GameError, active_diseases, guard, load, save

rng = secrets.SystemRandom()
FIRE_STEP = 10          # ставок на одну ступень огонька
FIRE_PCT = 5            # % к бонусу за ступень
FIRE_MAX_STEPS = 5      # максимум +25%
PREMIUM_TTL = 30
_premium: dict = {}


def left_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} ч {m} мин"
    if m:
        return f"{m} мин {s} сек"
    return f"{s} сек"


def plain_text(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _notes(*parts) -> list:
    out = []
    for part in parts:
        for line in plain_text(part).split("\n"):
            line = line.strip()
            if line:
                out.append(line)
    return out


def fire_view(s: dict, uid: int) -> dict:
    day = profile.ensure_day(s, uid)
    q = int(day.get("q", 0) or 0)
    steps = min(FIRE_MAX_STEPS, q // FIRE_STEP)
    return {"q": q, "step": FIRE_STEP, "pct": steps * FIRE_PCT, "max_pct": FIRE_MAX_STEPS * FIRE_PCT,
            "to_next": 0 if steps >= FIRE_MAX_STEPS else FIRE_STEP - q % FIRE_STEP}


def timers(data: dict) -> dict:
    from economy import CRIME_COOLDOWN, WORK_COOLDOWN
    from user_manager import BONUS_COOLDOWN
    from v2.conf import WHEEL_COOLDOWN
    s = profile.st(data)
    return {
        "bonus": int(float(data.get("last_bonus_time", 0) or 0) + BONUS_COOLDOWN),
        "work": int(float(data.get("last_work_time", 0) or 0) + WORK_COOLDOWN),
        "crime": int(float(data.get("last_crime_time", 0) or 0) + CRIME_COOLDOWN),
        "wheel": int(float(s.get("wheel", 0) or 0) + WHEEL_COOLDOWN),
    }


# ───────────────────────── Бонус ─────────────────────────
async def bonus(ctx: Ctx) -> dict:
    from user_manager import BONUS_COOLDOWN, check_and_give_bonus
    data = await load(ctx)
    await guard(ctx, data, casino=False)
    if "gonorrhea" in await active_diseases(ctx.chat_id, ctx.uid, data):
        raise GameError("🦠 Из-за болезни тебе отказано в бонусе.")
    ok, receipt = await check_and_give_bonus(ctx.chat_id, ctx.uid, ctx.esc_name)
    if not ok:
        left = float(data.get("last_bonus_time", 0) or 0) + BONUS_COOLDOWN - time.time()
        raise GameError(f"⏳ Бонус пока недоступен. Осталось {left_text(left)}." if left > 0
                        else "❌ Ты уже собирал доход недавно.")
    boost = pct = 0
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        s = profile.st(data)
        day = profile.ensure_day(s, ctx.uid)
        steps = min(FIRE_MAX_STEPS, int(day.get("q", 0) or 0) // FIRE_STEP)
        total = int(receipt.get("total", 0) or 0)
        if steps and total > 0:
            pct = steps * FIRE_PCT
            boost = int(total * pct / 100)
            day["q"] = int(day.get("q", 0)) - steps * FIRE_STEP
            data["balance"] = int(data.get("balance", 0) or 0) + boost
        save(ctx, data=data)
        balance = int(data.get("balance", 0) or 0)
        fire = fire_view(s, ctx.uid)
    keys = ("base", "business", "car", "meme_bonus", "prestige_bonus", "prestige_badge", "prestige_level",
            "tax_percent", "tax_amount", "luxury_tax", "total")
    return {"receipt": {k: receipt.get(k) for k in keys}, "boost": boost, "boost_pct": pct, "balance": balance,
            "next": int(time.time() + BONUS_COOLDOWN), "fire": fire}


# ───────────────────────── Работа и «дело» ─────────────────────────
async def _bank_bonus(ctx: Ctx, lo: int, hi: int, text: str) -> str:
    contribution = rng.randint(lo, hi)
    try:
        from profile_bank import create_or_update_bank, get_bank_info
        bank = await get_bank_info(ctx.chat_id, ctx.uid)
        if bank:
            await create_or_update_bank(ctx.chat_id, ctx.uid, {"capital": bank.get("capital", 0) + contribution})
            return text.format(contribution)
    except Exception:
        pass
    return ""


def _premium_game(ctx: Ctx, kind: str, bonus_amount: int, data: dict) -> dict:
    now = time.time()
    for token in [t for t, g in _premium.items() if g["exp"] < now]:
        _premium.pop(token, None)
    if kind == "banker":
        a, b = rng.randint(100, 500), rng.randint(100, 500)
        correct = a + b
        options = [correct, correct + rng.randint(10, 50), correct - rng.randint(10, 50)]
        prompt = f"Сведи баланс: {a} + {b} = ?"
    elif kind == "work":
        fruits = ["🍏", "🍎", "🍐", "🍊", "🍋", "🍌", "🍉", "🍇", "🍓", "🫐"]
        target = rng.choice(fruits)
        options = rng.sample([f for f in fruits if f != target], 2) + [target]
        correct = target
        prompt = f"Собери нужный товар: {target}"
    else:
        tools = ["🔧", "🪛", "🔑", "🔨", "🪚", "🧲"]
        target = rng.choice(["🔑", "🧲", "🪛"])
        options = rng.sample([t for t in tools if t != target], 2) + [target]
        correct = target
        prompt = f"Вскрой сейф: нужен {target}"
    rng.shuffle(options)
    token = uuid.uuid4().hex[:12]
    _premium[token] = {"uid": ctx.uid, "chat": ctx.chat_id, "bonus": bonus_amount, "ok": options.index(correct),
                       "exp": now + PREMIUM_TTL}
    return {"token": token, "prompt": prompt, "options": [str(o) for o in options], "bonus": bonus_amount,
            "ttl": PREMIUM_TTL}


async def work(ctx: Ctx) -> dict:
    from economy import WORK_COOLDOWN, _get_active_lobby, _process_collectors
    from seasons import apply_season_logic, get_season_config
    from user_manager import update_user_balance, update_user_field
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        await guard(ctx, data, casino=False)
        sick = await active_diseases(ctx.chat_id, ctx.uid, data)
        if "hiv" in sick:
            raise GameError("🦠 ВИЧ: у тебя нет сил работать. Зарплата обнулена.")
        now = time.time()
        left = float(data.get("last_work_time", 0) or 0) + WORK_COOLDOWN - now
        if left > 0:
            raise GameError(f"⏳ Ты устал. Отдохни ещё {left_text(left)}.")
        is_banker = bool(data.get("is_banker"))
        base = int(rng.randint(100, 700) * 0.8) if is_banker else rng.randint(100, 700)
        bank_msg = await _bank_bonus(ctx, 500, 2000, "🏢 Твоя работа принесла банку +{} сыр. в капитал!") \
            if is_banker else ""
        pet = data.get("pet") if isinstance(data.get("pet"), dict) else {}
        pet_id, pet_msg = pet.get("id"), ""
        if "hpv" in sick:
            pet_id, pet_msg = None, "🦠 ВПЧ: питомец не подходит к тебе."
        if pet_id == "cat":
            base = int(base * 1.2)
            pet_msg = "🐱 Кот помог заработать на 20% больше!"
        final, collector_msg, dragon = await _process_collectors(ctx.chat_id, ctx.uid, data, base, pet_id, 30)
        if dragon and (data.get("debts") or int(data.get("balance", 0) or 0) < 0):
            pet_msg += "\n🐉 Дракон отпугнул коллекторов!"
        lobby = await _get_active_lobby(ctx.chat_id, ctx.uid)
        lobby_msg = ""
        if lobby == "golden":
            final, lobby_msg = int(final * 1.2), "🌟 Золотой век: +20% к зарплате!"
        elif lobby == "work":
            final, lobby_msg = int(final * 1.4), "🏭 Индустриализация: +40% к зарплате!"
        final, season_msg = await apply_season_logic(ctx.chat_id, ctx.uid, final)
        if final > 0:
            await update_user_balance(ctx.chat_id, ctx.uid, final, is_debt_repayment=True)
        await update_user_field(ctx.chat_id, ctx.uid, "last_work_time", now)
        cfg = await get_season_config()
        jobs = (cfg.get("strings", {}) or {}).get("job_list") if cfg and cfg.get("active") else None
        if not jobs:
            jobs = (["поработал с документами", "провёл встречу с инвесторами", "свёл дебет с кредитом",
                     "продал акции банка"] if is_banker else
                    ["разгрузил вагоны", "написал код за еду", "доставил пиццу", "отработал смену на заводе",
                     "собрал металлолом", "перебрал корзину сыроежек"])
        boost = 1.4 if lobby == "work" else (1.2 if lobby == "golden" else 1.0)
        prem = int((rng.randint(500, 1250) if is_banker else rng.randint(1000, 2500)) * boost)
        game = _premium_game(ctx, "banker" if is_banker else "work", prem, data)
        balance = int((await load(ctx)).get("balance", 0) or 0)
    return {"amount": int(final), "job": rng.choice(jobs), "notes": _notes(pet_msg, lobby_msg, collector_msg,
                                                                            bank_msg, season_msg),
            "balance": balance, "next": int(now + WORK_COOLDOWN), "game": game}


async def crime(ctx: Ctx) -> dict:
    from economy import CRIME_COOLDOWN, _get_active_lobby, _process_collectors
    from seasons import apply_season_logic
    from user_manager import update_user_balance, update_user_field
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        await guard(ctx, data, casino=False)
        sick = await active_diseases(ctx.chat_id, ctx.uid, data)
        now = time.time()
        left = float(data.get("last_crime_time", 0) or 0) + CRIME_COOLDOWN - now
        if left > 0:
            raise GameError(f"⏳ Копы ищут тебя. Заляг на дно ещё {left_text(left)}.")
        skills = data.get("skills") if isinstance(data.get("skills"), dict) else {}
        chance = 0.5 + min(int(skills.get("stealth", 0) or 0), 20) * 0.02
        pet = data.get("pet") if isinstance(data.get("pet"), dict) else {}
        pet_id, pet_msg = pet.get("id"), ""
        if "hpv" in sick:
            pet_id, pet_msg = None, "🦠 ВПЧ: питомец отказался помогать."
        if pet_id == "dragon":
            chance += 0.10
            pet_msg = "🐉 Дракон помогает провернуть дело!"
        lobby = await _get_active_lobby(ctx.chat_id, ctx.uid)
        if lobby == "crime":
            chance += 0.20
        if "syphilis" in sick:
            chance /= 2.0
            pet_msg += "\n🦠 Сифилис: шанс успеха урезан вдвое."
        chance = max(0.05, min(chance, 0.95))
        if rng.random() >= chance:
            fine = rng.randint(500, 1500)
            if lobby == "crime":
                fine = max(1, int(fine * 0.2))
                text = f"🚔 Почти поймали, но благодаря Амнистии отделался штрафом {fine} сыр."
            else:
                text = f"🚔 Тебя поймали! Суд выписал штраф в {fine} сыр."
            await update_user_balance(ctx.chat_id, ctx.uid, -fine, min_balance=0, is_debt_repayment=True)
            await update_user_field(ctx.chat_id, ctx.uid, "last_crime_time", now)
            balance = int((await load(ctx)).get("balance", 0) or 0)
            return {"ok_crime": False, "amount": -fine, "text": text, "notes": _notes(pet_msg),
                    "chance": round(chance * 100), "balance": balance, "next": int(now + CRIME_COOLDOWN)}
        is_banker = bool(data.get("is_banker"))
        base = int(rng.randint(200, 500) * 0.8) if is_banker else rng.randint(200, 500)
        bank_msg = await _bank_bonus(ctx, 500, 1500, "🏢 Часть теневой добычи (+{} сыр.) отмыта в капитал банка!") \
            if is_banker else ""
        final, collector_msg, dragon = await _process_collectors(ctx.chat_id, ctx.uid, data, base, pet_id, 40)
        if dragon and (data.get("debts") or int(data.get("balance", 0) or 0) < 0):
            pet_msg += " И отпугнул коллекторов!"
        lobby_msg = ""
        if lobby == "golden":
            final, lobby_msg = int(final * 1.2), "🌟 Золотой век: +20% к кушу!"
        elif lobby == "crime":
            final, lobby_msg = int(final * 1.2), "🥷 Амнистия: куш увеличен!"
        final, season_msg = await apply_season_logic(ctx.chat_id, ctx.uid, final)
        if final > 0:
            await update_user_balance(ctx.chat_id, ctx.uid, final, is_debt_repayment=True)
        await update_user_field(ctx.chat_id, ctx.uid, "last_crime_time", now)
        boost = 1.2 if lobby in ("golden", "crime") else 1.0
        game = _premium_game(ctx, "crime", int(rng.randint(1500, 4000) * boost), data)
        balance = int((await load(ctx)).get("balance", 0) or 0)
    return {"ok_crime": True, "amount": int(final), "text": f"🥷 Успешное проникновение! Добыча: {final} сыр.",
            "notes": _notes(pet_msg, lobby_msg, collector_msg, bank_msg, season_msg), "chance": round(chance * 100),
            "balance": balance, "next": int(now + CRIME_COOLDOWN), "game": game}


async def premium(ctx: Ctx, token: str, pick: int) -> dict:
    from user_manager import update_user_balance
    game = _premium.pop(str(token or ""), None)
    if not game or game["uid"] != ctx.uid or game["chat"] != ctx.chat_id:
        raise GameError("⏳ Время вышло или премия уже разыграна.")
    if time.time() > game["exp"]:
        raise GameError("⏳ Время вышло — премия сгорела.")
    if pick != game["ok"]:
        data = await load(ctx)
        return {"win": False, "correct": game["ok"], "bonus": 0, "balance": int(data.get("balance", 0) or 0)}
    balance = await update_user_balance(ctx.chat_id, ctx.uid, game["bonus"])
    return {"win": True, "correct": game["ok"], "bonus": game["bonus"], "balance": int(balance or 0)}


# ───────────────────────── Кешбэк и задания ─────────────────────────
async def claim_rake(ctx: Ctx) -> dict:
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        await guard(ctx, data, casino=False)
        s = profile.st(data)
        amount = int(s.get("rake", 0) or 0)
        if amount < 1:
            raise GameError("Кешбэк копится с каждой ставки. Пока забирать нечего.")
        s["rake"] = 0
        s["rake_total"] = int(s.get("rake_total", 0) or 0) + amount
        data["balance"] = int(data.get("balance", 0) or 0) + amount
        save(ctx, data=data)
        return {"amount": amount, "balance": data["balance"]}


async def claim_task(ctx: Ctx, task_id: str) -> dict:
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        await guard(ctx, data, casino=False)
        s = profile.st(data)
        level = profile.level_for_xp(int(s.get("xp", 0) or 0))
        profile.ensure_day(s, ctx.uid)
        for t in s["tasks"]:
            spec = profile.TASK_BY_ID.get(t.get("id"))
            if not spec or t.get("id") != task_id:
                continue
            if t.get("c"):
                raise GameError("Награда за это задание уже получена.")
            if int(t.get("p", 0)) < spec[3]:
                raise GameError("Задание ещё не выполнено.")
            t["c"] = True
            reward = profile.task_reward(level)
            data["balance"] = int(data.get("balance", 0) or 0) + reward
            s["xp"] = int(s.get("xp", 0)) + 60
            events = []
            if all(x.get("c") for x in s["tasks"]):
                profile.award(s, "tasks", events)
            save(ctx, data=data)
            return {"reward": reward, "balance": data["balance"], "tasks": profile.tasks_view(s, ctx.uid, level),
                    "events": events}
    raise GameError("Такого задания сегодня нет.")
