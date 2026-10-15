"""Денежные операции V2: всё под per-user локом user_manager, одной записью профиля.

Ставка, результат и прогресс меняются в одном словаре профиля, поэтому
отложенное сохранение пишет их вместе. Ставки общих столов (краш, рулетка,
складчина, дуэли) заносятся в v2.pend и возвращаются, если раунд потерян
перезапуском.
"""
import logging
import time
from dataclasses import dataclass

from admin_logs import check_balance_alert, log_transaction
from user_manager import (flush_user_cache_immediately, get_user_data, get_user_lock, mark_dirty,
                          set_in_cache)
from utils import fire_and_forget
from v2 import profile
from v2.conf import MAX_BET, MIN_BET, SICK_MAX_BET

log = logging.getLogger(__name__)
LARGE_TX = 500_000
_live_refs: set[str] = set()
_disease_cache: dict = {}


class GameError(Exception):
    """Ошибка, текст которой показывается игроку."""


@dataclass
class Ctx:
    chat_id: int
    uid: int
    name: str          # обычный текст для интерфейса
    esc_name: str      # как хранит старый код (HTML-экранированное)
    handle: str
    is_creator: bool = False
    photo_url: str = ""
    clan: str | None = None


def register_live(ref: str):
    _live_refs.add(ref)


def unregister_live(ref: str):
    _live_refs.discard(ref)


async def load(ctx: Ctx) -> dict:
    return await get_user_data(ctx.chat_id, ctx.uid, ctx.esc_name)


def save(ctx_or_chat, uid: int | None = None, data: dict | None = None):
    chat_id, user_id = (ctx_or_chat.chat_id, ctx_or_chat.uid) if uid is None else (ctx_or_chat, uid)
    set_in_cache(chat_id, user_id, data)
    mark_dirty(chat_id, user_id)


async def active_diseases(chat_id: int, uid: int, data: dict) -> list:
    if not isinstance(data.get("diseases"), dict) or not data.get("diseases"):
        return []
    key = (chat_id, uid)
    hit = _disease_cache.get(key)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    try:
        from diseases import get_active_diseases
        value = list(await get_active_diseases(chat_id, uid, data))
    except Exception:
        log.exception("disease lookup failed")
        value = []
    if len(_disease_cache) > 4000:
        _disease_cache.clear()
    _disease_cache[key] = (time.monotonic(), value)
    return value


async def season_xp() -> float:
    try:
        from seasons import get_season_config
        cfg = await get_season_config()
        return 1.25 if cfg and cfg.get("active") else 1.0
    except Exception:
        return 1.0


async def guard(ctx: Ctx, data: dict, bet: int | None = None, casino: bool = True) -> dict:
    """Общие проверки старого бота: бан, техработы, болезни, лимиты ставки."""
    if data.get("is_banned"):
        raise GameError("🚫 Ты в бане и не можешь играть.")
    if not ctx.is_creator:
        try:
            from utils import check_maintenance
            if await check_maintenance():
                raise GameError("🛠 Бот на техобслуживании. Игры временно выключены.")
        except GameError:
            raise
        except Exception:
            pass
    sick = await active_diseases(ctx.chat_id, ctx.uid, data)
    if casino and "gonorrhea" in sick:
        raise GameError("🦠 Гонорея: крупье брезгует пускать тебя за стол.")
    flags = {"pet_ok": "hpv" not in sick, "xp_frozen": "gardnerellosis" in sick,
             "cap": SICK_MAX_BET if "balanoposthitis" in sick else MAX_BET, "sick": sick}
    if bet is not None:
        check_bet(data, bet, flags["cap"])
    return flags


def parse_bet(value) -> int:
    try:
        bet = int(value)
    except (TypeError, ValueError):
        raise GameError("Ставка должна быть целым числом.") from None
    return bet


def check_bet(data: dict, bet: int, cap: int = MAX_BET):
    if bet < MIN_BET:
        raise GameError(f"Минимальная ставка — {MIN_BET}.")
    if bet > cap:
        if cap < MAX_BET:
            raise GameError(f"🦠 Баланопостит: ставка не больше {cap:,}.".replace(",", " "))
        raise GameError(f"Максимальная ставка — {cap:,}.".replace(",", " "))
    if int(data.get("balance", 0) or 0) < bet:
        raise GameError("Не хватает сыроежек на балансе.")


def _after(ctx_chat: int, uid: int, name: str, delta: int, balance: int, action: str):
    if abs(delta) >= LARGE_TX:
        fire_and_forget(log_transaction(uid, name, None, None, action, delta))
    fire_and_forget(check_balance_alert(ctx_chat, uid, name, balance))


async def instant(ctx: Ctx, gid: str, bet: int, resolve) -> dict:
    """Мгновенный раунд: списать ставку, вычислить исход, выплатить, записать прогресс."""
    sxp = await season_xp()
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        flags = await guard(ctx, data, bet)
        s = profile.st(data)
        out = resolve(data, s)
        payout = max(0, int(out.get("payout", 0)))
        data["balance"] = int(data.get("balance", 0) or 0) - bet + payout
        rec = profile.record_bet(data, ctx.uid, gid, bet, payout, mult=out.get("mult"), pet_ok=flags["pet_ok"],
                                 xp_frozen=flags["xp_frozen"], extra=out.get("extra"), season_xp=sxp)
        save(ctx, data=data)
        balance = data["balance"]
    _after(ctx.chat_id, ctx.uid, ctx.name, payout - bet, balance, f"V2 {gid}")
    out.update(balance=balance, events=rec["events"], payout=payout, bet=bet, win=rec["win"])
    out.pop("extra", None)
    return out


async def session(ctx: Ctx, gid: str, step, *, bet: int | None = None) -> dict:
    """Многошаговая игра (блэкджек, охота, покер). Состояние хранится в профиле.

    step(data, s, state, flags) -> dict с полями:
      state  — новое состояние (None, если игра закончена),
      debit  — сколько списать сейчас (ставка, дабл, сплит),
      payout — выплата при завершении, wager — итоговая ставка раунда,
      view   — данные для клиента.
    """
    sxp = await season_xp()
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        flags = await guard(ctx, data, bet)
        s = profile.st(data)
        state = s["act"].get(gid)
        res = step(data, s, state, flags)
        debit = int(res.get("debit", 0))
        if debit:
            if int(data.get("balance", 0) or 0) < debit:
                raise GameError("Не хватает сыроежек на балансе.")
            data["balance"] = int(data["balance"]) - debit
        new_state = res.get("state")
        events, win = [], False
        payout = 0
        if new_state is None:
            payout = max(0, int(res.get("payout", 0)))
            data["balance"] = int(data.get("balance", 0) or 0) + payout
            wager = int(res.get("wager", 0))
            if wager:
                rec = profile.record_bet(data, ctx.uid, gid, wager, payout, mult=res.get("mult"),
                                         pet_ok=flags["pet_ok"], xp_frozen=flags["xp_frozen"],
                                         extra=res.get("extra"), season_xp=sxp)
                events, win = rec["events"], rec["win"]
        s["act"][gid] = new_state
        save(ctx, data=data)
        balance = data["balance"]
    if new_state is None:
        _after(ctx.chat_id, ctx.uid, ctx.name, payout - int(res.get("wager", 0)), balance, f"V2 {gid}")
    view = res.get("view", {})
    view.update(balance=balance, events=events, done=new_state is None, payout=payout,
                wager=int(res.get("wager", 0)), win=win)
    return view


async def stake(ctx: Ctx, gid: str, amount: int, ref: str, *, check=None) -> int:
    """Списывает ставку общего стола и запоминает её как незавершённую."""
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        await guard(ctx, data, amount)
        s = profile.st(data)
        if check:
            check(data, s)
        data["balance"] = int(data["balance"]) - amount
        s["pend"].append({"id": ref, "g": gid, "a": amount, "ts": int(time.time())})
        del s["pend"][:-30]
        save(ctx, data=data)
        return data["balance"]


async def settle(chat_id: int, uid: int, name: str, gid: str, ref: str, wager: int, payout: int, *,
                 mult: float | None = None, extra: dict | None = None, record: bool = True,
                 flush: bool = False) -> dict:
    """Закрывает ставку общего стола: выплата + прогресс, снятие из v2.pend."""
    sxp = await season_xp()
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        s = profile.st(data)
        before = len(s["pend"])
        s["pend"] = [p for p in s["pend"] if not (isinstance(p, dict) and p.get("id") == ref)]
        if len(s["pend"]) == before:
            # Уже закрыто (или возвращено после рестарта) — второй выплаты не будет.
            return {"balance": int(data.get("balance", 0) or 0), "events": [], "dup": True}
        sick = await active_diseases(chat_id, uid, data)
        data["balance"] = int(data.get("balance", 0) or 0) + max(0, int(payout))
        events = []
        if record and wager:
            rec = profile.record_bet(data, uid, gid, wager, payout, mult=mult, pet_ok="hpv" not in sick,
                                     xp_frozen="gardnerellosis" in sick, extra=extra, season_xp=sxp)
            events = rec["events"]
        save(chat_id, uid, data)
        balance = data["balance"]
    _after(chat_id, uid, name, int(payout) - int(wager), balance, f"V2 {gid}")
    if flush or payout >= LARGE_TX:
        fire_and_forget(flush_user_cache_immediately(chat_id, uid))
    return {"balance": balance, "events": events}


def refund_stale(data: dict, s: dict) -> int:
    """Возврат ставок раундов, которых больше нет (перезапуск бота)."""
    now = time.time()
    keep, refund = [], 0
    for p in s["pend"]:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        if pid in _live_refs or pid.rsplit(":", 1)[0] in _live_refs or now - float(p.get("ts", 0) or 0) < 15:
            keep.append(p)
        else:
            refund += max(0, int(p.get("a", 0) or 0))
    if refund or len(keep) != len(s["pend"]):
        s["pend"] = keep
        data["balance"] = int(data.get("balance", 0) or 0) + refund
    return refund


async def touch(ctx: Ctx) -> tuple[dict, dict]:
    """Загрузка профиля для экранов: возвраты зависших ставок, задания дня."""
    async with get_user_lock(ctx.chat_id, ctx.uid):
        data = await load(ctx)
        s = profile.st(data)
        refunded = refund_stale(data, s)
        before = s.get("day", {}).get("k")
        profile.tasks_view(s, ctx.uid, profile.level_for_xp(int(s.get("xp", 0))))
        if refunded or before != s["day"].get("k"):
            save(ctx, data=data)
        if refunded:
            log.warning("V2 refunded %s stale stake(s) for %s:%s", refunded, ctx.chat_id, ctx.uid)
    return data, s


async def settle_prize(chat_id: int, uid: int, amount: int):
    async with get_user_lock(chat_id, uid):
        data = await get_user_data(chat_id, uid)
        data["balance"] = int(data.get("balance", 0) or 0) + int(amount)
        save(chat_id, uid, data)
    fire_and_forget(flush_user_cache_immediately(chat_id, uid))
