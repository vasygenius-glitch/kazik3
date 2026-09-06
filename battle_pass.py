# battle_pass.py
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from escape import escape_html
from user_manager import get_user_data, update_user_balance

logger = logging.getLogger(__name__)

router = Router(name="battle_pass")

# ─────────────────────────── Constants ────────────────────────────────────────

BP_FILE = Path("data/battle_pass.json")
PREMIUM_PRICE = 25_000
MAX_LEVEL = 20
XP_PER_LEVEL = 1_000

# Free-track rewards per level (level 1–20, index 0 = level 1)
FREE_REWARDS: list[dict] = [
    {"coins": 500,   "xp_boost": 0,   "perk": None},
    {"coins": 750,   "xp_boost": 0,   "perk": None},
    {"coins": 1_000, "xp_boost": 0,   "perk": None},
    {"coins": 1_000, "xp_boost": 5,   "perk": None},
    {"coins": 1_500, "xp_boost": 0,   "perk": None},
    {"coins": 1_500, "xp_boost": 0,   "perk": None},
    {"coins": 2_000, "xp_boost": 10,  "perk": None},
    {"coins": 2_000, "xp_boost": 0,   "perk": None},
    {"coins": 2_500, "xp_boost": 0,   "perk": None},
    {"coins": 2_500, "xp_boost": 15,  "perk": "🎖️ Ветеран"},
    {"coins": 3_000, "xp_boost": 0,   "perk": None},
    {"coins": 3_000, "xp_boost": 0,   "perk": None},
    {"coins": 3_500, "xp_boost": 20,  "perk": None},
    {"coins": 3_500, "xp_boost": 0,   "perk": None},
    {"coins": 4_000, "xp_boost": 0,   "perk": None},
    {"coins": 4_000, "xp_boost": 25,  "perk": None},
    {"coins": 5_000, "xp_boost": 0,   "perk": None},
    {"coins": 5_000, "xp_boost": 0,   "perk": None},
    {"coins": 6_000, "xp_boost": 30,  "perk": None},
    {"coins": 10_000,"xp_boost": 0,   "perk": "🏆 Легенда сезона"},
]

# Premium-track rewards per level
PREMIUM_REWARDS: list[dict] = [
    {"coins": 1_500,  "xp_boost": 10,  "perk": None},
    {"coins": 2_000,  "xp_boost": 0,   "perk": None},
    {"coins": 2_500,  "xp_boost": 0,   "perk": None},
    {"coins": 3_000,  "xp_boost": 15,  "perk": None},
    {"coins": 3_500,  "xp_boost": 0,   "perk": None},
    {"coins": 4_000,  "xp_boost": 0,   "perk": None},
    {"coins": 5_000,  "xp_boost": 20,  "perk": "⭐ Элита"},
    {"coins": 5_000,  "xp_boost": 0,   "perk": None},
    {"coins": 6_000,  "xp_boost": 0,   "perk": None},
    {"coins": 7_000,  "xp_boost": 25,  "perk": "💎 Алмазный статус"},
    {"coins": 7_000,  "xp_boost": 0,   "perk": None},
    {"coins": 8_000,  "xp_boost": 0,   "perk": None},
    {"coins": 9_000,  "xp_boost": 30,  "perk": None},
    {"coins": 9_000,  "xp_boost": 0,   "perk": None},
    {"coins": 10_000, "xp_boost": 0,   "perk": None},
    {"coins": 11_000, "xp_boost": 35,  "perk": None},
    {"coins": 12_000, "xp_boost": 0,   "perk": None},
    {"coins": 13_000, "xp_boost": 0,   "perk": None},
    {"coins": 15_000, "xp_boost": 40,  "perk": "👑 Королевский статус"},
    {"coins": 25_000, "xp_boost": 50,  "perk": "🌟 Абсолютный чемпион"},
]

# Daily quest definitions
QUEST_POOL: list[dict] = [
    {
        "id": "play_games",
        "name": "Сыграть 5 любых игр в казино",
        "goal": 5,
        "xp": 500,
        "coins": 1_000,
        "emoji": "🎰",
    },
    {
        "id": "win_duel",
        "name": "Победить в дуэли (/duel)",
        "goal": 1,
        "xp": 750,
        "coins": 1_500,
        "emoji": "⚔️",
    },
    {
        "id": "total_bets",
        "name": "Сделать суммарно ставок на 5,000 монет",
        "goal": 5_000,
        "xp": 600,
        "coins": 2_000,
        "emoji": "💸",
    },
    {
        "id": "win_streak",
        "name": "Выиграть 3 раза подряд в любой игре",
        "goal": 3,
        "xp": 800,
        "coins": 1_800,
        "emoji": "🔥",
    },
]

# ─────────────────────────── Persistence ──────────────────────────────────────

_bp_data: dict = {}
_save_lock = asyncio.Lock()


def _ensure_data_dir() -> None:
    BP_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_bp_data_sync() -> dict:
    _ensure_data_dir()
    if BP_FILE.exists():
        try:
            with BP_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Не удалось загрузить battle_pass.json: %s", exc)
    return {}


async def _save_bp_data() -> None:
    async with _save_lock:
        _ensure_data_dir()
        try:
            tmp = BP_FILE.with_suffix(".tmp")
            loop = asyncio.get_event_loop()
            data_snapshot = dict(_bp_data)
            await loop.run_in_executor(None, _write_json_sync, tmp, data_snapshot)
            await loop.run_in_executor(None, tmp.replace, BP_FILE)
        except OSError as exc:
            logger.error("Не удалось сохранить battle_pass.json: %s", exc)


def _write_json_sync(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _init_bp_data() -> None:
    global _bp_data
    _bp_data = _load_bp_data_sync()


_init_bp_data()

# ─────────────────────────── User BP record helpers ───────────────────────────

def _user_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}:{user_id}"


def _get_user_bp(chat_id: int, user_id: int) -> dict:
    key = _user_key(chat_id, user_id)
    if key not in _bp_data:
        _bp_data[key] = {
            "xp": 0,
            "level": 1,
            "premium": False,
            "claimed_free": [],
            "claimed_premium": [],
            "quests": {},
        }
    return _bp_data[key]


def _today_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _get_user_quests(chat_id: int, user_id: int) -> dict:
    bp = _get_user_bp(chat_id, user_id)
    today = _today_str()
    quest_data = bp.setdefault("quests", {})

    if quest_data.get("date") != today:
        quest_data.clear()
        quest_data["date"] = today
        quest_data["quests"] = {
            q["id"]: {"progress": 0, "claimed": False}
            for q in QUEST_POOL
        }

    return quest_data


# ─────────────────────────── Core XP logic ────────────────────────────────────

async def add_bp_xp(chat_id: int, user_id: int, xp: int) -> tuple[int, bool]:
    """
    Award XP to a user's Battle Pass.
    Returns (current_level, leveled_up).
    """
    bp = _get_user_bp(chat_id, user_id)

    xp_boost_pct = _calc_xp_boost(bp)
    boosted_xp = int(xp * (1 + xp_boost_pct / 100))

    bp["xp"] += boosted_xp
    old_level = bp["level"]

    while bp["level"] < MAX_LEVEL and bp["xp"] >= bp["level"] * XP_PER_LEVEL:
        bp["xp"] -= bp["level"] * XP_PER_LEVEL
        bp["level"] += 1

    if bp["level"] >= MAX_LEVEL:
        bp["level"] = MAX_LEVEL

    leveled_up = bp["level"] > old_level
    await _save_bp_data()
    return bp["level"], leveled_up


def _calc_xp_boost(bp: dict) -> int:
    """Sum all unlocked XP boost percentages from claimed rewards."""
    total_boost = 0
    for lvl_idx in bp.get("claimed_free", []):
        if 0 <= lvl_idx < MAX_LEVEL:
            total_boost += FREE_REWARDS[lvl_idx].get("xp_boost", 0)
    if bp.get("premium"):
        for lvl_idx in bp.get("claimed_premium", []):
            if 0 <= lvl_idx < MAX_LEVEL:
                total_boost += PREMIUM_REWARDS[lvl_idx].get("xp_boost", 0)
    return total_boost


# ─────────────────────────── Quest progress ───────────────────────────────────

async def record_quest_progress(
    chat_id: int, user_id: int, quest_type: str, amount: int = 1
) -> None:
    """
    Record progress on a quest by its id (e.g. 'play_games', 'win_duel').
    Automatically awards XP when a quest is completed for the first time.
    """
    quest_data = _get_user_quests(chat_id, user_id)
    quests = quest_data.get("quests", {})

    if quest_type not in quests:
        return

    entry = quests[quest_type]
    if entry["claimed"]:
        return

    quest_def = next((q for q in QUEST_POOL if q["id"] == quest_type), None)
    if quest_def is None:
        return

    entry["progress"] = min(entry["progress"] + amount, quest_def["goal"])
    await _save_bp_data()


# ─────────────────────────── Progress bar ─────────────────────────────────────

def _make_progress_bar(current: int, total: int, length: int = 10) -> str:
    filled = int(length * current / total) if total else 0
    filled = max(0, min(filled, length))
    return "█" * filled + "░" * (length - filled)


# ─────────────────────────── Keyboard builders ────────────────────────────────

def _bp_main_keyboard(has_premium: bool, has_claimable: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_claimable:
        builder.button(text="🎁 Забрать награды", callback_data="bp:claim_all")
    if not has_premium:
        builder.button(text=f"👑 Купить Premium (25,000 🪙)", callback_data="bp:buy_premium")
    builder.button(text="📜 Ежедневные квесты", callback_data="bp:quests")
    builder.button(text="📊 Таблица уровней", callback_data="bp:levels_table")
    builder.adjust(1)
    return builder.as_markup()


def _quests_keyboard(quests_state: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for q in quests_state:
        if q["done"] and not q["claimed"]:
            builder.button(
                text=f"✅ Забрать: {q['name']}",
                callback_data=f"bp:claim_quest:{q['id']}",
            )
    builder.button(text="🔙 Назад к Боевому пропуску", callback_data="bp:main")
    builder.adjust(1)
    return builder.as_markup()


def _levels_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к Боевому пропуску", callback_data="bp:main")
    builder.adjust(1)
    return builder.as_markup()


# ─────────────────────────── Message composers ────────────────────────────────

def _compose_bp_message(chat_id: int, user_id: int) -> str:
    bp = _get_user_bp(chat_id, user_id)
    level = bp["level"]
    xp = bp["xp"]
    premium = bp["premium"]
    xp_for_next = XP_PER_LEVEL

    bar = _make_progress_bar(xp, xp_for_next)
    boost = _calc_xp_boost(bp)

    claimable_free = _get_claimable_levels(bp, track="free")
    claimable_premium = _get_claimable_levels(bp, track="premium") if premium else []
    total_claimable = len(claimable_free) + len(claimable_premium)

    lines = [
        "🎮 <b>Боевой пропуск — Сезон 1</b>",
        "",
        f"👤 Уровень: <b>{level}</b> / {MAX_LEVEL}",
        f"{'👑 Premium' if premium else '🆓 Бесплатный'} пропуск",
        "",
        f"📈 Опыт: <b>[{bar}] {xp}/{xp_for_next} XP</b>",
        f"⚡ Бонус XP: +{boost}%" if boost else "",
        "",
    ]
    if total_claimable:
        lines.append(f"🎁 Доступно наград для получения: <b>{total_claimable}</b>")
    else:
        lines.append("✅ Все доступные награды уже получены!")

    if level >= MAX_LEVEL:
        lines.append("\n🏆 <b>Максимальный уровень достигнут!</b>")

    return "\n".join(ln for ln in lines if ln is not None)


def _get_claimable_levels(bp: dict, track: str) -> list[int]:
    """Return 0-based level indices that are unlocked and not yet claimed."""
    level = bp["level"]
    if track == "free":
        rewards = FREE_REWARDS
        claimed = bp.get("claimed_free", [])
    else:
        rewards = PREMIUM_REWARDS
        claimed = bp.get("claimed_premium", [])

    claimable = []
    for idx in range(MAX_LEVEL):
        lvl_required = idx + 1
        if lvl_required <= level and idx not in claimed and rewards[idx]["coins"] > 0:
            claimable.append(idx)
    return claimable


def _compose_quests_message(chat_id: int, user_id: int) -> tuple[str, list[dict]]:
    quest_data = _get_user_quests(chat_id, user_id)
    quests_raw = quest_data.get("quests", {})
    today = quest_data.get("date", _today_str())

    lines = [
        "📜 <b>Ежедневные задания</b>",
        f"📅 {escape_html(today)}",
        "",
    ]

    quests_state: list[dict] = []

    for q_def in QUEST_POOL:
        entry = quests_raw.get(q_def["id"], {"progress": 0, "claimed": False})
        progress = entry["progress"]
        goal = q_def["goal"]
        claimed = entry["claimed"]
        done = progress >= goal

        if claimed:
            icon = "✅"
            status = "Награда получена!"
        elif done:
            icon = "🎉"
            status = "Готово — забери награду!"
        else:
            icon = "⏳"
            status = "В процессе"

        progress_str = f"{progress}/{goal}"
        lines.append(
            f"{icon} <b>{escape_html(q_def['name'])}</b> ({progress_str})\n"
            f"   💰 {q_def['coins']:,} монет | ✨ {q_def['xp']} XP — {escape_html(status)}"
        )
        lines.append("")

        quests_state.append(
            {
                "id": q_def["id"],
                "name": q_def["name"],
                "done": done,
                "claimed": claimed,
            }
        )

    return "\n".join(lines), quests_state


def _compose_levels_table() -> str:
    lines = [
        "📊 <b>Таблица уровней Боевого пропуска</b>",
        "",
        "<code>Лвл │ Бесплатно         │ Premium</code>",
        "<code>────┼───────────────────┼───────────────────</code>",
    ]
    for idx in range(MAX_LEVEL):
        lvl = idx + 1
        fr = FREE_REWARDS[idx]
        pr = PREMIUM_REWARDS[idx]

        def fmt(r: dict) -> str:
            parts = [f"{r['coins']:>6,}🪙"]
            if r["xp_boost"]:
                parts.append(f"+{r['xp_boost']}%XP")
            if r["perk"]:
                parts.append(r["perk"])
            return " ".join(parts)

        lines.append(
            f"<code>{lvl:>3} │ {fmt(fr):<17} │ {fmt(pr)}</code>"
        )

    return "\n".join(lines)


# ─────────────────────────── Handlers ─────────────────────────────────────────

@router.message(Command(commands=["bp", "battlepass", "pass"]))
async def cmd_battlepass(message: Message) -> None:
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    bp = _get_user_bp(chat_id, user_id)
    has_claimable = bool(
        _get_claimable_levels(bp, "free")
        or (bp["premium"] and _get_claimable_levels(bp, "premium"))
    )

    text = _compose_bp_message(chat_id, user_id)
    kb = _bp_main_keyboard(has_premium=bp["premium"], has_claimable=has_claimable)

    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command(commands=["quests", "daily"]))
async def cmd_quests(message: Message) -> None:
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    text, quests_state = _compose_quests_message(chat_id, user_id)
    kb = _quests_keyboard(quests_state)

    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command(commands=["bp_buy"]))
async def cmd_bp_buy(message: Message) -> None:
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id

    await _process_buy_premium(message, chat_id, user_id)


# ─────────────────────────── Callback handlers ────────────────────────────────

@router.callback_query(F.data == "bp:main")
async def cb_bp_main(call: CallbackQuery) -> None:
    if not call.from_user or not call.message:
        await call.answer()
        return
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    bp = _get_user_bp(chat_id, user_id)
    has_claimable = bool(
        _get_claimable_levels(bp, "free")
        or (bp["premium"] and _get_claimable_levels(bp, "premium"))
    )

    text = _compose_bp_message(chat_id, user_id)
    kb = _bp_main_keyboard(has_premium=bp["premium"], has_claimable=has_claimable)

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "bp:claim_all")
async def cb_claim_all(call: CallbackQuery) -> None:
    if not call.from_user or not call.message:
        await call.answer()
        return
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    bp = _get_user_bp(chat_id, user_id)
    free_levels = _get_claimable_levels(bp, "free")
    premium_levels = _get_claimable_levels(bp, "premium") if bp["premium"] else []

    if not free_levels and not premium_levels:
        await call.answer("🤷 Нет доступных наград для получения.", show_alert=True)
        return

    total_coins = 0
    total_xp_boost_gained = 0
    perks_gained: list[str] = []

    for idx in free_levels:
        r = FREE_REWARDS[idx]
        total_coins += r["coins"]
        total_xp_boost_gained += r["xp_boost"]
        if r["perk"]:
            perks_gained.append(r["perk"])
        bp.setdefault("claimed_free", []).append(idx)

    for idx in premium_levels:
        r = PREMIUM_REWARDS[idx]
        total_coins += r["coins"]
        total_xp_boost_gained += r["xp_boost"]
        if r["perk"]:
            perks_gained.append(r["perk"])
        bp.setdefault("claimed_premium", []).append(idx)

    if total_coins > 0:
        new_balance = await update_user_balance(
            chat_id, user_id, total_coins, action="Battle Pass — получение наград"
        )
    else:
        new_balance = None

    await _save_bp_data()

    lines = [
        "🎁 <b>Награды получены!</b>",
        "",
        f"💰 +{total_coins:,} монет",
    ]
    if new_balance is not None:
        lines.append(f"💳 Баланс: {new_balance:,} монет")
    if total_xp_boost_gained:
        lines.append(f"⚡ +{total_xp_boost_gained}% бонус XP активирован!")
    for perk in perks_gained:
        lines.append(f"✨ Статус: {perk}")

    await call.answer("\n".join(lines), show_alert=True)

    # Refresh the main BP panel
    has_claimable = bool(
        _get_claimable_levels(bp, "free")
        or (bp["premium"] and _get_claimable_levels(bp, "premium"))
    )
    text = _compose_bp_message(chat_id, user_id)
    kb = _bp_main_keyboard(has_premium=bp["premium"], has_claimable=has_claimable)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "bp:buy_premium")
async def cb_buy_premium(call: CallbackQuery) -> None:
    if not call.from_user or not call.message:
        await call.answer()
        return
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    await _process_buy_premium(call.message, chat_id, user_id, call=call)


async def _process_buy_premium(
    message: Message,
    chat_id: int,
    user_id: int,
    call: Optional[CallbackQuery] = None,
) -> None:
    bp = _get_user_bp(chat_id, user_id)

    if bp["premium"]:
        text = "👑 У вас уже есть <b>Premium Боевой пропуск</b>!"
        if call:
            await call.answer(text, show_alert=True)
        else:
            await message.answer(text, parse_mode="HTML")
        return

    new_balance = await update_user_balance(
        chat_id,
        user_id,
        -PREMIUM_PRICE,
        min_balance=PREMIUM_PRICE,
        action="Покупка Premium Боевого пропуска",
    )

    if new_balance is None:
        text = (
            f"❌ <b>Недостаточно монет!</b>\n"
            f"Для покупки Premium пропуска нужно <b>{PREMIUM_PRICE:,} 🪙</b>."
        )
        if call:
            await call.answer("❌ Недостаточно монет!", show_alert=True)
            await message.edit_text(text, parse_mode="HTML")
        else:
            await message.answer(text, parse_mode="HTML")
        return

    bp["premium"] = True
    await _save_bp_data()

    success_text = (
        "👑 <b>Premium Боевой пропуск активирован!</b>\n\n"
        f"💳 Баланс: {new_balance:,} монет\n\n"
        "🎁 Теперь вам доступны эксклюзивные Premium-награды за каждый уровень!\n"
        "Используйте /bp чтобы забрать их."
    )

    if call:
        await call.answer("👑 Premium активирован!", show_alert=False)
        await message.edit_text(success_text, parse_mode="HTML")
    else:
        await message.answer(success_text, parse_mode="HTML")


@router.callback_query(F.data == "bp:quests")
async def cb_quests(call: CallbackQuery) -> None:
    if not call.from_user or not call.message:
        await call.answer()
        return
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    text, quests_state = _compose_quests_message(chat_id, user_id)
    kb = _quests_keyboard(quests_state)

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "bp:levels_table")
async def cb_levels_table(call: CallbackQuery) -> None:
    if not call.message:
        await call.answer()
        return

    text = _compose_levels_table()
    kb = _levels_keyboard()

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("bp:claim_quest:"))
async def cb_claim_quest(call: CallbackQuery) -> None:
    if not call.from_user or not call.message:
        await call.answer()
        return

    quest_id = call.data.split(":", 2)[2]
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    quest_def = next((q for q in QUEST_POOL if q["id"] == quest_id), None)
    if quest_def is None:
        await call.answer("❌ Квест не найден.", show_alert=True)
        return

    quest_data = _get_user_quests(chat_id, user_id)
    quests_raw = quest_data.get("quests", {})
    entry = quests_raw.get(quest_id)

    if entry is None:
        await call.answer("❌ Квест не найден на сегодня.", show_alert=True)
        return

    if entry["claimed"]:
        await call.answer("✅ Награда уже получена!", show_alert=True)
        return

    if entry["progress"] < quest_def["goal"]:
        await call.answer("⏳ Квест ещё не выполнен!", show_alert=True)
        return

    # Award coins
    new_balance = await update_user_balance(
        chat_id,
        user_id,
        quest_def["coins"],
        action=f"Квест: {quest_def['name']}",
    )

    # Award XP
    new_level, leveled_up = await add_bp_xp(chat_id, user_id, quest_def["xp"])

    entry["claimed"] = True
    await _save_bp_data()

    lines = [
        f"🎉 Квест выполнен: <b>{escape_html(quest_def['name'])}</b>",
        "",
        f"💰 +{quest_def['coins']:,} монет",
        f"✨ +{quest_def['xp']} XP к Боевому пропуску",
    ]
    if new_balance is not None:
        lines.append(f"💳 Баланс: {new_balance:,} монет")
    if leveled_up:
        lines.append(f"\n🎊 Новый уровень: {new_level}! Проверь /bp для наград!")

    alert_text = "\n".join(lines)
    # Telegram alert supports plain text only — strip tags for the alert popup
    plain_alert = alert_text.replace("<b>", "").replace("</b>", "")
    await call.answer(plain_alert[:200], show_alert=True)

    # Refresh quest list
    text, quests_state = _compose_quests_message(chat_id, user_id)
    kb = _quests_keyboard(quests_state)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)