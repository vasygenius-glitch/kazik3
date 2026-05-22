# crash.py — fully optimized with advanced achievement system
from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import secrets
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from enum import Enum
from functools import lru_cache, partial
from pathlib import Path
from typing import Any, Callable, ClassVar, Iterable, NamedTuple, Optional

import matplotlib
matplotlib.use("Agg")
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from matplotlib.figure import Figure
from matplotlib.patches import Circle

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder

from user_manager import get_user_data, update_user_balance, invalidate_user_cache
from escape import escape_html
from utils import schedule_delete

logger = logging.getLogger(__name__)
router = Router()


# ═════════════════════════════════════════════════════════════════════
#                              FSM STATES
# ═════════════════════════════════════════════════════════════════════
class CrashState(StatesGroup):
    playing = State()
    awaiting_auto = State()


# ═════════════════════════════════════════════════════════════════════
#                              CONSTANTS
# ═════════════════════════════════════════════════════════════════════
MIN_BET = 100
MAX_BET = 50_000_000
CREDIT_LIMIT = -5000
AUTO_DELETE_DELAY = 60
ACHIEVEMENT_NOTIFY_DELAY = 90
FRAME_DELAY = 0.85
MAX_FLIGHT_STEPS = 28
INSTANT_CRASH_CHANCE = 10
GROWTH_BASE = 0.046
GROWTH_EXP = 1.36

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATS_FILE = DATA_DIR / "crash_stats.json"
HISTORY_FILE = DATA_DIR / "crash_history.json"
ACHIEVEMENTS_FILE = DATA_DIR / "crash_achievements.json"

# RNG and sync primitives
_rng = secrets.SystemRandom()
_stats_lock = asyncio.Lock()
_history_lock = asyncio.Lock()
_ach_lock = asyncio.Lock()
_active_games: dict[str, "GameSession"] = {}

# Dedicated single-thread executor (matplotlib is not thread safe)
_render_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="crash-render")
_io_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="crash-io")

# Pre-computed multiplier sequence to avoid recomputation
_MULT_BY_STEP: tuple[float, ...] = tuple(
    round(1.00 + (s ** GROWTH_EXP) * GROWTH_BASE, 2) for s in range(MAX_FLIGHT_STEPS + 16)
)


# ═════════════════════════════════════════════════════════════════════
#                              THEMES
# ═════════════════════════════════════════════════════════════════════
class Theme(str, Enum):
    NEON = "neon"
    SUNSET = "sunset"
    MATRIX = "matrix"
    OCEAN = "ocean"
    INFERNO = "inferno"
    GALAXY = "galaxy"
    AURORA = "aurora"
    CYBERPUNK = "cyberpunk"


THEMES: dict[Theme, dict[str, Any]] = {
    Theme.NEON: {
        "bg_top": "#0b0420", "bg_bot": "#1a0b3d", "grid": "#3d2a6b",
        "line": "#00fff7", "line_glow": "#9d4dff", "fill_top": "#ff00d4",
        "fill_bot": "#00fff7", "text": "#f0f0ff", "accent": "#ff2bd6",
        "crash": "#ff3355", "win": "#33ff99", "rocket": "#ffdd33",
    },
    Theme.SUNSET: {
        "bg_top": "#1d0030", "bg_bot": "#ff5e3a", "grid": "#5a2a4d",
        "line": "#ffd166", "line_glow": "#ff6b6b", "fill_top": "#ff006e",
        "fill_bot": "#ffbe0b", "text": "#fff7e6", "accent": "#ff9e00",
        "crash": "#d00000", "win": "#90ee90", "rocket": "#ffd700",
    },
    Theme.MATRIX: {
        "bg_top": "#000000", "bg_bot": "#001a00", "grid": "#003300",
        "line": "#00ff41", "line_glow": "#39ff14", "fill_top": "#00ff41",
        "fill_bot": "#003b00", "text": "#b6ffb6", "accent": "#00ff88",
        "crash": "#ff0040", "win": "#00ff41", "rocket": "#80ff80",
    },
    Theme.OCEAN: {
        "bg_top": "#001f3f", "bg_bot": "#0074d9", "grid": "#0a3d62",
        "line": "#7fdbff", "line_glow": "#39c0ed", "fill_top": "#01baef",
        "fill_bot": "#003b73", "text": "#e8f6ff", "accent": "#48cae4",
        "crash": "#ff4d6d", "win": "#caffbf", "rocket": "#ffdd00",
    },
    Theme.INFERNO: {
        "bg_top": "#1a0000", "bg_bot": "#5a0000", "grid": "#3d0a0a",
        "line": "#ff6b35", "line_glow": "#ff4d00", "fill_top": "#ffba08",
        "fill_bot": "#d00000", "text": "#ffe0b3", "accent": "#ff9500",
        "crash": "#ff0a54", "win": "#ffe066", "rocket": "#ffe066",
    },
    Theme.GALAXY: {
        "bg_top": "#0a0a23", "bg_bot": "#231942", "grid": "#5e548e",
        "line": "#e0aaff", "line_glow": "#c77dff", "fill_top": "#9d4edd",
        "fill_bot": "#240046", "text": "#f3e8ff", "accent": "#b298dc",
        "crash": "#ff006e", "win": "#80ed99", "rocket": "#ffd60a",
    },
    Theme.AURORA: {
        "bg_top": "#011627", "bg_bot": "#082c3a", "grid": "#1a4d5c",
        "line": "#a0ffe6", "line_glow": "#5eead4", "fill_top": "#67e8f9",
        "fill_bot": "#0e7490", "text": "#ecfeff", "accent": "#7ee7d5",
        "crash": "#fb7185", "win": "#bbf7d0", "rocket": "#fef3c7",
    },
    Theme.CYBERPUNK: {
        "bg_top": "#0d0221", "bg_bot": "#330066", "grid": "#5d2a8e",
        "line": "#fffb00", "line_glow": "#ff00ff", "fill_top": "#ff006e",
        "fill_bot": "#3a0ca3", "text": "#f8f8ff", "accent": "#ff2bd6",
        "crash": "#ff003c", "win": "#39ff14", "rocket": "#fffb00",
    },
}

_THEME_CMAP: dict[Theme, LinearSegmentedColormap] = {
    t: LinearSegmentedColormap.from_list(f"bg_{t.value}", [p["bg_top"], p["bg_bot"]])
    for t, p in THEMES.items()
}
_THEME_FILL_RGBA: dict[Theme, tuple] = {
    t: to_rgba(p["fill_top"], alpha=0.18) for t, p in THEMES.items()
}
_GRADIENT_BUF = np.linspace(0, 1, 256).reshape(-1, 1)

PRESET_BETS = (100, 500, 1000, 5000, 10_000, 50_000, 100_000, 500_000)
AUTO_PRESETS = (1.5, 2.0, 3.0, 5.0, 10.0, 25.0)


# ═════════════════════════════════════════════════════════════════════
#                          ACHIEVEMENT SYSTEM
# ═════════════════════════════════════════════════════════════════════
class Rarity(str, Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    MYTHIC = "mythic"


RARITY_META: dict[Rarity, dict[str, Any]] = {
    Rarity.COMMON:    {"label": "Обычное",     "color": "⬜", "weight": 1, "reward_mult": 1.0},
    Rarity.UNCOMMON:  {"label": "Необычное",   "color": "🟩", "weight": 2, "reward_mult": 1.5},
    Rarity.RARE:      {"label": "Редкое",      "color": "🟦", "weight": 3, "reward_mult": 2.5},
    Rarity.EPIC:      {"label": "Эпическое",   "color": "🟪", "weight": 4, "reward_mult": 4.0},
    Rarity.LEGENDARY: {"label": "Легендарное", "color": "🟧", "weight": 5, "reward_mult": 7.0},
    Rarity.MYTHIC:    {"label": "Мифическое",  "color": "🟥", "weight": 6, "reward_mult": 12.0},
}


class AchCategory(str, Enum):
    PROGRESSION = "progression"
    SKILL = "skill"
    STREAK = "streak"
    ECONOMY = "economy"
    SPECIAL = "special"
    SECRET = "secret"


CATEGORY_META: dict[AchCategory, dict[str, str]] = {
    AchCategory.PROGRESSION: {"icon": "📈", "label": "Прогресс"},
    AchCategory.SKILL:       {"icon": "🎯", "label": "Мастерство"},
    AchCategory.STREAK:      {"icon": "🔥", "label": "Серии"},
    AchCategory.ECONOMY:     {"icon": "💰", "label": "Экономика"},
    AchCategory.SPECIAL:     {"icon": "✨", "label": "Особые"},
    AchCategory.SECRET:      {"icon": "🔮", "label": "Тайные"},
}


@dataclass(slots=True, frozen=True)
class AchievementContext:
    """Snapshot passed to every achievement check function."""
    stats: "PlayerStats"
    bet: int
    win_amount: int
    multiplier: float
    duration: float
    net_profit: int
    is_win: bool
    crash_point: float
    auto_used: bool
    near_miss: bool          # cashed out within 0.1x of crash
    session_peak: float


class Achievement(NamedTuple):
    code: str
    title: str
    description: str
    icon: str
    category: AchCategory
    rarity: Rarity
    reward: int
    check: Callable[[AchievementContext], bool]
    progress: Callable[["PlayerStats"], float]   # 0.0 … 1.0
    hidden: bool = False
    chain_next: Optional[str] = None             # next tier achievement
    chain_prev: Optional[str] = None


# ── helpers used inside lambda checks ───────────────────────────────
def _safe_ratio(value: float, target: float) -> float:
    if target <= 0:
        return 1.0
    r = value / target
    return 0.0 if r < 0 else (1.0 if r > 1 else r)


# ── full achievements registry ──────────────────────────────────────
_ACHIEVEMENTS_LIST: tuple[Achievement, ...] = (
    # ── Progression ────────────────────────────────────────────────
    Achievement(
        "first_flight", "Первый полет", "Сыграй свою первую партию", "✈️",
        AchCategory.PROGRESSION, Rarity.COMMON, 100,
        check=lambda c: c.stats.games_total >= 1,
        progress=lambda s: _safe_ratio(s.games_total, 1),
        chain_next="rookie_pilot",
    ),
    Achievement(
        "rookie_pilot", "Юный пилот", "Сыграй 10 партий", "🛩️",
        AchCategory.PROGRESSION, Rarity.COMMON, 500,
        check=lambda c: c.stats.games_total >= 10,
        progress=lambda s: _safe_ratio(s.games_total, 10),
        chain_prev="first_flight", chain_next="experienced_pilot",
    ),
    Achievement(
        "experienced_pilot", "Опытный пилот", "Сыграй 50 партий", "🛫",
        AchCategory.PROGRESSION, Rarity.UNCOMMON, 2_500,
        check=lambda c: c.stats.games_total >= 50,
        progress=lambda s: _safe_ratio(s.games_total, 50),
        chain_prev="rookie_pilot", chain_next="marathon",
    ),
    Achievement(
        "marathon", "Марафонец", "Сыграй 100 партий", "🏃",
        AchCategory.PROGRESSION, Rarity.RARE, 7_500,
        check=lambda c: c.stats.games_total >= 100,
        progress=lambda s: _safe_ratio(s.games_total, 100),
        chain_prev="experienced_pilot", chain_next="veteran",
    ),
    Achievement(
        "veteran", "Ветеран", "Сыграй 500 партий", "🎖️",
        AchCategory.PROGRESSION, Rarity.EPIC, 25_000,
        check=lambda c: c.stats.games_total >= 500,
        progress=lambda s: _safe_ratio(s.games_total, 500),
        chain_prev="marathon", chain_next="grandmaster",
    ),
    Achievement(
        "grandmaster", "Гроссмейстер неба", "Сыграй 1000 партий", "🏅",
        AchCategory.PROGRESSION, Rarity.LEGENDARY, 100_000,
        check=lambda c: c.stats.games_total >= 1000,
        progress=lambda s: _safe_ratio(s.games_total, 1000),
        chain_prev="veteran", chain_next="immortal_aviator",
    ),
    Achievement(
        "immortal_aviator", "Бессмертный авиатор", "Сыграй 5000 партий", "👑",
        AchCategory.PROGRESSION, Rarity.MYTHIC, 1_000_000,
        check=lambda c: c.stats.games_total >= 5000,
        progress=lambda s: _safe_ratio(s.games_total, 5000),
        chain_prev="grandmaster",
    ),

    # ── Skill / Multipliers ───────────────────────────────────────
    Achievement(
        "first_win", "Первая победа", "Обналичь хотя бы раз", "🥇",
        AchCategory.SKILL, Rarity.COMMON, 200,
        check=lambda c: c.is_win and c.stats.games_won >= 1,
        progress=lambda s: _safe_ratio(s.games_won, 1),
    ),
    Achievement(
        "double_up", "Удвоение", "Обналичь на коэф. 2.00x+", "✌️",
        AchCategory.SKILL, Rarity.COMMON, 300,
        check=lambda c: c.is_win and c.multiplier >= 2.0,
        progress=lambda s: _safe_ratio(s.best_multiplier, 2.0),
        chain_next="lucky_five",
    ),
    Achievement(
        "lucky_five", "Высокий полет", "Обналичь на коэф. 5.00x+", "🖐️",
        AchCategory.SKILL, Rarity.UNCOMMON, 1_000,
        check=lambda c: c.is_win and c.multiplier >= 5.0,
        progress=lambda s: _safe_ratio(s.best_multiplier, 5.0),
        chain_prev="double_up", chain_next="lucky_seven",
    ),
    Achievement(
        "lucky_seven", "Лаки-Севен", "Обналичь на коэф. 7.77x+", "7️⃣",
        AchCategory.SKILL, Rarity.RARE, 5_000,
        check=lambda c: c.is_win and c.multiplier >= 7.77,
        progress=lambda s: _safe_ratio(s.best_multiplier, 7.77),
        chain_prev="lucky_five", chain_next="to_the_moon",
    ),
    Achievement(
        "to_the_moon", "На луну", "Обналичь на коэф. 25.00x+", "🌙",
        AchCategory.SKILL, Rarity.EPIC, 25_000,
        check=lambda c: c.is_win and c.multiplier >= 25.0,
        progress=lambda s: _safe_ratio(s.best_multiplier, 25.0),
        chain_prev="lucky_seven", chain_next="diamond_hands",
    ),
    Achievement(
        "diamond_hands", "Алмазные руки", "Обналичь на коэф. 50.00x+", "💎",
        AchCategory.SKILL, Rarity.LEGENDARY, 75_000,
        check=lambda c: c.is_win and c.multiplier >= 50.0,
        progress=lambda s: _safe_ratio(s.best_multiplier, 50.0),
        chain_prev="to_the_moon", chain_next="godlike",
    ),
    Achievement(
        "godlike", "Богоподобный", "Обналичь на коэф. 100.00x+", "👑",
        AchCategory.SKILL, Rarity.MYTHIC, 500_000,
        check=lambda c: c.is_win and c.multiplier >= 100.0,
        progress=lambda s: _safe_ratio(s.best_multiplier, 100.0),
        chain_prev="diamond_hands",
    ),

    # ── Streaks ───────────────────────────────────────────────────
    Achievement(
        "three_in_row", "Триплет", "Выиграй 3 раза подряд", "🎲",
        AchCategory.STREAK, Rarity.COMMON, 500,
        check=lambda c: c.stats.current_streak_type == "win" and c.stats.current_streak >= 3,
        progress=lambda s: _safe_ratio(s.streak_wins, 3),
        chain_next="five_combo",
    ),
    Achievement(
        "five_combo", "Пятёрочка", "Выиграй 5 раз подряд", "🖐️",
        AchCategory.STREAK, Rarity.UNCOMMON, 2_000,
        check=lambda c: c.stats.current_streak_type == "win" and c.stats.current_streak >= 5,
        progress=lambda s: _safe_ratio(s.streak_wins, 5),
        chain_prev="three_in_row", chain_next="ironman",
    ),
    Achievement(
        "ironman", "Железный", "Выиграй 10 раз подряд", "🦾",
        AchCategory.STREAK, Rarity.EPIC, 15_000,
        check=lambda c: c.stats.current_streak_type == "win" and c.stats.current_streak >= 10,
        progress=lambda s: _safe_ratio(s.streak_wins, 10),
        chain_prev="five_combo", chain_next="unstoppable",
    ),
    Achievement(
        "unstoppable", "Неудержимый", "Выиграй 20 раз подряд", "⚡",
        AchCategory.STREAK, Rarity.LEGENDARY, 100_000,
        check=lambda c: c.stats.current_streak_type == "win" and c.stats.current_streak >= 20,
        progress=lambda s: _safe_ratio(s.streak_wins, 20),
        chain_prev="ironman",
    ),
    Achievement(
        "phoenix", "Феникс", "Проиграй 10 раз подряд (не сдавайся)", "🔥",
        AchCategory.STREAK, Rarity.RARE, 3_000,
        check=lambda c: c.stats.current_streak_type == "loss" and c.stats.current_streak >= 10,
        progress=lambda s: _safe_ratio(s.streak_losses, 10),
        chain_next="dark_phoenix",
    ),
    Achievement(
        "dark_phoenix", "Темный феникс", "Проиграй 20 раз подряд", "🖤",
        AchCategory.STREAK, Rarity.EPIC, 20_000,
        check=lambda c: c.stats.current_streak_type == "loss" and c.stats.current_streak >= 20,
        progress=lambda s: _safe_ratio(s.streak_losses, 20),
        chain_prev="phoenix",
    ),

    # ── Economy ───────────────────────────────────────────────────
    Achievement(
        "first_thousand", "Первая тысяча", "Накопи 1,000 сыр. оборота", "💵",
        AchCategory.ECONOMY, Rarity.COMMON, 200,
        check=lambda c: c.stats.total_bet >= 1_000,
        progress=lambda s: _safe_ratio(s.total_bet, 1_000),
        chain_next="high_roller",
    ),
    Achievement(
        "high_roller", "Хайроллер", "Сделай ставку 1,000,000+", "💎",
        AchCategory.ECONOMY, Rarity.EPIC, 50_000,
        check=lambda c: c.bet >= 1_000_000,
        progress=lambda s: _safe_ratio(s.biggest_bet, 1_000_000),
    ),
    Achievement(
        "whale", "Кит", "Сделай ставку 10,000,000+", "🐳",
        AchCategory.ECONOMY, Rarity.LEGENDARY, 250_000,
        check=lambda c: c.bet >= 10_000_000,
        progress=lambda s: _safe_ratio(s.biggest_bet, 10_000_000),
        chain_prev="high_roller",
    ),
    Achievement(
        "millionaire", "Миллионер", "Выиграй 1,000,000+ за раз", "💰",
        AchCategory.ECONOMY, Rarity.EPIC, 100_000,
        check=lambda c: c.net_profit >= 1_000_000,
        progress=lambda s: _safe_ratio(s.best_win, 1_000_000),
        chain_next="tycoon",
    ),
    Achievement(
        "tycoon", "Магнат", "Выиграй 10,000,000+ за раз", "🏦",
        AchCategory.ECONOMY, Rarity.LEGENDARY, 500_000,
        check=lambda c: c.net_profit >= 10_000_000,
        progress=lambda s: _safe_ratio(s.best_win, 10_000_000),
        chain_prev="millionaire",
    ),
    Achievement(
        "frugal", "Бережливый", "Совокупная прибыль 5,000,000+", "🪙",
        AchCategory.ECONOMY, Rarity.RARE, 25_000,
        check=lambda c: (c.stats.total_won - c.stats.total_bet) >= 5_000_000,
        progress=lambda s: _safe_ratio(max(0, s.total_won - s.total_bet), 5_000_000),
    ),

    # ── Special / Skill ───────────────────────────────────────────
    Achievement(
        "speedrun", "Спидранер", "Обналичь меньше чем за 2 секунды", "⚡",
        AchCategory.SPECIAL, Rarity.RARE, 5_000,
        check=lambda c: c.is_win and 0 < c.duration < 2.0,
        progress=lambda s: 1.0 if "speedrun" in s.achievements else 0.0,
    ),
    Achievement(
        "patience", "Терпеливый", "Обналичь после 15 секунд полета", "🧘",
        AchCategory.SPECIAL, Rarity.RARE, 5_000,
        check=lambda c: c.is_win and c.duration >= 15.0,
        progress=lambda s: 1.0 if "patience" in s.achievements else 0.0,
    ),
    Achievement(
        "automate", "Автоматизатор", "Обналичь через авто-cashout", "🤖",
        AchCategory.SPECIAL, Rarity.UNCOMMON, 1_000,
        check=lambda c: c.is_win and c.auto_used,
        progress=lambda s: 1.0 if "automate" in s.achievements else 0.0,
    ),
    Achievement(
        "near_miss", "На волосок", "Обналичь в 0.10x от краша", "😰",
        AchCategory.SPECIAL, Rarity.EPIC, 15_000,
        check=lambda c: c.is_win and c.near_miss,
        progress=lambda s: 1.0 if "near_miss" in s.achievements else 0.0,
    ),
    Achievement(
        "lucky_dog", "Везунчик", "Выиграй с коэф. 3x+ при шансе мгновенного краша", "🍀",
        AchCategory.SPECIAL, Rarity.RARE, 4_000,
        check=lambda c: c.is_win and c.multiplier >= 3.0 and c.session_peak >= 3.0,
        progress=lambda s: 1.0 if "lucky_dog" in s.achievements else 0.0,
    ),
    Achievement(
        "perfectionist", "Перфекционист", "Win-rate 70%+ при 50+ играх", "🎯",
        AchCategory.SPECIAL, Rarity.LEGENDARY, 100_000,
        check=lambda c: c.stats.games_total >= 50 and c.stats.win_rate >= 70.0,
        progress=lambda s: _safe_ratio(s.win_rate, 70.0) if s.games_total >= 50 else 0.0,
    ),

    # ── Secret / Hidden ───────────────────────────────────────────
    Achievement(
        "exact_1x", "Чудовищный краш", "Поймай мгновенный краш на 1.00x", "💀",
        AchCategory.SECRET, Rarity.EPIC, 10_000,
        check=lambda c: (not c.is_win) and c.crash_point <= 1.01,
        progress=lambda s: 1.0 if "exact_1x" in s.achievements else 0.0,
        hidden=True,
    ),
    Achievement(
        "nightowl", "Ночная сова", "Сыграй между 00:00 и 05:00", "🦉",
        AchCategory.SECRET, Rarity.UNCOMMON, 1_500,
        check=lambda c: 0 <= time.localtime().tm_hour < 5,
        progress=lambda s: 1.0 if "nightowl" in s.achievements else 0.0,
        hidden=True,
    ),
    Achievement(
        "early_bird", "Ранняя пташка", "Сыграй между 05:00 и 08:00", "🐦",
        AchCategory.SECRET, Rarity.UNCOMMON, 1_500,
        check=lambda c: 5 <= time.localtime().tm_hour < 8,
        progress=lambda s: 1.0 if "early_bird" in s.achievements else 0.0,
        hidden=True,
    ),
    Achievement(
        "comeback", "Камбэк", "Победа после серии из 5+ проигрышей", "🔄",
        AchCategory.SECRET, Rarity.RARE, 5_000,
        check=lambda c: c.is_win and c.stats.last_loss_streak >= 5,
        progress=lambda s: 1.0 if "comeback" in s.achievements else 0.0,
        hidden=True,
    ),
    Achievement(
        "all_themes", "Коллекционер", "Поиграй на каждой из 8 тем", "🎨",
        AchCategory.SECRET, Rarity.RARE, 7_500,
        check=lambda c: len(c.stats.themes_used) >= len(Theme),
        progress=lambda s: _safe_ratio(len(s.themes_used), len(Theme)),
        hidden=True,
    ),
    Achievement(
        "double_dip", "Удача в кубе", "Два хайролла подряд на 10x+", "🎰",
        AchCategory.SECRET, Rarity.EPIC, 20_000,
        check=lambda c: c.is_win and c.multiplier >= 10.0 and c.stats.last_high_mult >= 10.0,
        progress=lambda s: 1.0 if "double_dip" in s.achievements else 0.0,
        hidden=True,
    ),
)

ACHIEVEMENTS: dict[str, Achievement] = {a.code: a for a in _ACHIEVEMENTS_LIST}
ACHIEVEMENTS_BY_CATEGORY: dict[AchCategory, list[Achievement]] = defaultdict(list)
for _a in _ACHIEVEMENTS_LIST:
    ACHIEVEMENTS_BY_CATEGORY[_a.category].append(_a)


# ═════════════════════════════════════════════════════════════════════
#                              DATACLASSES
# ═════════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class GameSession:
    game_id: str
    chat_id: int
    user_id: int
    full_name: str
    bet: int
    crash_point: float
    current_multiplier: float = 1.00
    path_points: list[float] = field(default_factory=lambda: [1.00])
    timestamps: list[float] = field(default_factory=lambda: [0.0])
    cashed_out: bool = False
    cashout_at: Optional[float] = None
    started_at: float = field(default_factory=time.time)
    theme: Theme = Theme.NEON
    auto_cashout: Optional[float] = None
    message_id: Optional[int] = None
    step: int = 0
    finished: bool = False
    cancelled: bool = False
    near_miss: bool = False

    def add_point(self, mult: float) -> None:
        self.path_points.append(round(mult, 2))
        self.timestamps.append(time.time() - self.started_at)
        self.step += 1

    @property
    def peak(self) -> float:
        return max(self.path_points) if self.path_points else 1.00

    @property
    def duration(self) -> float:
        return time.time() - self.started_at


@dataclass(slots=True)
class PlayerStats:
    user_id: int
    games_total: int = 0
    games_won: int = 0
    games_lost: int = 0
    total_bet: int = 0
    total_won: int = 0
    total_lost: int = 0
    best_multiplier: float = 0.0
    best_win: int = 0
    worst_loss: int = 0
    biggest_bet: int = 0
    streak_wins: int = 0
    streak_losses: int = 0
    current_streak: int = 0
    current_streak_type: str = "none"
    last_loss_streak: int = 0
    last_high_mult: float = 0.0
    last_played: float = 0.0
    achievements: list[str] = field(default_factory=list)
    achievement_dates: dict[str, float] = field(default_factory=dict)
    favorite_theme: str = Theme.NEON.value
    themes_used: list[str] = field(default_factory=list)
    auto_default: Optional[float] = None
    reward_received: int = 0

    @property
    def win_rate(self) -> float:
        return self.games_won / self.games_total * 100.0 if self.games_total else 0.0

    @property
    def loss_rate(self) -> float:
        return self.games_lost / self.games_total * 100.0 if self.games_total else 0.0

    @property
    def profit(self) -> int:
        return self.total_won - self.total_bet

    @property
    def avg_bet(self) -> float:
        return self.total_bet / self.games_total if self.games_total else 0.0

    @property
    def avg_multiplier(self) -> float:
        return (self.total_won / self.total_bet) if self.total_bet else 0.0

    @property
    def achievement_score(self) -> int:
        score = 0
        for code in self.achievements:
            ach = ACHIEVEMENTS.get(code)
            if ach is not None:
                score += RARITY_META[ach.rarity]["weight"] * 10
        return score


# ═════════════════════════════════════════════════════════════════════
#                          ACHIEVEMENT MANAGER
# ═════════════════════════════════════════════════════════════════════
class AchievementManager:
    """Central authority for evaluating, granting and persisting achievements."""

    __slots__ = ("_unlock_log", "_dirty", "_recent_unlocks")

    def __init__(self) -> None:
        self._unlock_log: list[dict[str, Any]] = []
        self._dirty: bool = False
        # cache of last N global unlocks (user_id, code, ts)
        self._recent_unlocks: deque = deque(maxlen=100)

    # ─────────────── lifecycle ───────────────
    async def load(self) -> None:
        async with _ach_lock:
            if not ACHIEVEMENTS_FILE.exists():
                return
            try:
                raw = json.loads(ACHIEVEMENTS_FILE.read_text(encoding="utf-8"))
                self._unlock_log = raw.get("log", [])
                for item in self._unlock_log[-100:]:
                    self._recent_unlocks.append(item)
            except Exception as exc:
                logger.warning("Failed loading achievement log: %s", exc)

    async def flush(self, force: bool = False) -> None:
        if not (self._dirty or force):
            return
        async with _ach_lock:
            if not (self._dirty or force):
                return
            payload = {"log": self._unlock_log[-1000:]}
            try:
                await asyncio.to_thread(
                    ACHIEVEMENTS_FILE.write_text,
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self._dirty = False
            except Exception as exc:
                logger.warning("Failed saving achievement log: %s", exc)

    # ─────────────── evaluation ──────────────
    def evaluate(self, ctx: AchievementContext) -> list[str]:
        """Returns codes that were *newly* unlocked for this user in this event."""
        st = ctx.stats
        already = set(st.achievements)
        unlocked: list[str] = []

        # Iterate in a deterministic order for predictable chains
        for ach in _ACHIEVEMENTS_LIST:
            if ach.code in already:
                continue
            try:
                if ach.check(ctx):
                    st.achievements.append(ach.code)
                    st.achievement_dates[ach.code] = time.time()
                    already.add(ach.code)
                    unlocked.append(ach.code)
                    self._log_unlock(st.user_id, ach.code)
            except Exception as exc:
                logger.debug("Achievement %s check failed: %s", ach.code, exc)
        return unlocked

    def _log_unlock(self, user_id: int, code: str) -> None:
        entry = {"user_id": user_id, "code": code, "ts": time.time()}
        self._unlock_log.append(entry)
        self._recent_unlocks.append(entry)
        self._dirty = True

    # ─────────────── rewards ─────────────────
    @staticmethod
    def compute_reward(codes: Iterable[str]) -> int:
        """Sum reward of unlocked achievements (rarity multiplier already in reward field)."""
        total = 0
        for c in codes:
            ach = ACHIEVEMENTS.get(c)
            if ach is not None:
                total += ach.reward
        return total

    # ─────────────── queries ─────────────────
    def progress_of(self, st: PlayerStats, code: str) -> float:
        ach = ACHIEVEMENTS.get(code)
        if ach is None:
            return 0.0
        if code in st.achievements:
            return 1.0
        try:
            return max(0.0, min(1.0, float(ach.progress(st))))
        except Exception:
            return 0.0

    def unlocked_count(self, st: PlayerStats) -> int:
        return len(st.achievements)

    def total_count(self) -> int:
        return len(ACHIEVEMENTS)

    def completion(self, st: PlayerStats) -> float:
        total = self.total_count()
        return (len(st.achievements) / total) * 100.0 if total else 0.0

    def by_category(self, st: PlayerStats, cat: AchCategory) -> tuple[int, int]:
        all_ach = ACHIEVEMENTS_BY_CATEGORY.get(cat, [])
        unlocked = sum(1 for a in all_ach if a.code in st.achievements)
        return unlocked, len(all_ach)

    def recent_global_unlocks(self, n: int = 10) -> list[dict[str, Any]]:
        return list(self._recent_unlocks)[-n:]


# ═════════════════════════════════════════════════════════════════════
#                            STATS MANAGER
# ═════════════════════════════════════════════════════════════════════
class StatsManager:
    """In-memory player stats cache with periodic flushing."""

    __slots__ = ("_cache", "_dirty", "_ach", "_pending_reward")

    def __init__(self, ach_manager: AchievementManager) -> None:
        self._cache: dict[int, PlayerStats] = {}
        self._dirty: bool = False
        self._ach: AchievementManager = ach_manager
        self._pending_reward: dict[int, int] = defaultdict(int)

    async def load(self) -> None:
        async with _stats_lock:
            if not STATS_FILE.exists():
                return
            try:
                raw = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed loading crash stats: %s", exc)
                return
            for uid_str, payload in raw.items():
                try:
                    uid = int(uid_str)
                except ValueError:
                    continue
                payload.pop("user_id", None)
                # Backward compat for new fields
                payload.setdefault("biggest_bet", 0)
                payload.setdefault("last_loss_streak", 0)
                payload.setdefault("last_high_mult", 0.0)
                payload.setdefault("achievement_dates", {})
                payload.setdefault("themes_used", [])
                payload.setdefault("reward_received", 0)
                try:
                    self._cache[uid] = PlayerStats(user_id=uid, **payload)
                except TypeError as exc:
                    logger.debug("Skipping malformed stats row %s: %s", uid_str, exc)

    async def flush(self, force: bool = False) -> None:
        if not (self._dirty or force):
            return
        async with _stats_lock:
            if not (self._dirty or force):
                return
            payload = {str(uid): asdict(st) for uid, st in self._cache.items()}
            try:
                await asyncio.to_thread(
                    STATS_FILE.write_text,
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self._dirty = False
            except Exception as exc:
                logger.warning("Failed saving crash stats: %s", exc)

    def mark_dirty(self) -> None:
        self._dirty = True

    def get(self, user_id: int) -> PlayerStats:
        st = self._cache.get(user_id)
        if st is None:
            st = PlayerStats(user_id=user_id)
            self._cache[user_id] = st
            self._dirty = True
        return st

    def all_players(self) -> list[PlayerStats]:
        return list(self._cache.values())

    # ─────────────── update flows ────────────
    def _track_theme(self, st: PlayerStats, theme: Theme) -> None:
        if theme.value not in st.themes_used:
            st.themes_used.append(theme.value)

    def update_on_win(self, session: GameSession, win_amount: int) -> tuple[list[str], int]:
        st = self.get(session.user_id)
        bet = session.bet
        multiplier = session.current_multiplier
        duration = session.duration
        net = win_amount - bet

        st.games_total += 1
        st.games_won += 1
        st.total_bet += bet
        st.total_won += win_amount
        if multiplier > st.best_multiplier:
            st.best_multiplier = multiplier
        if net > st.best_win:
            st.best_win = net
        if bet > st.biggest_bet:
            st.biggest_bet = bet

        if st.current_streak_type == "win":
            st.current_streak += 1
        else:
            # store last loss streak length before resetting
            if st.current_streak_type == "loss":
                st.last_loss_streak = st.current_streak
            st.current_streak = 1
            st.current_streak_type = "win"
        if st.current_streak > st.streak_wins:
            st.streak_wins = st.current_streak

        st.last_played = time.time()
        self._track_theme(st, session.theme)

        ctx = AchievementContext(
            stats=st,
            bet=bet,
            win_amount=win_amount,
            multiplier=multiplier,
            duration=duration,
            net_profit=net,
            is_win=True,
            crash_point=session.crash_point,
            auto_used=session.auto_cashout is not None and multiplier >= (session.auto_cashout or 0),
            near_miss=session.near_miss,
            session_peak=session.peak,
        )
        unlocked = self._ach.evaluate(ctx)
        reward = AchievementManager.compute_reward(unlocked)
        if reward:
            st.reward_received += reward
            self._pending_reward[session.user_id] += reward
        st.last_high_mult = multiplier if multiplier >= 10.0 else 0.0
        self._dirty = True
        return unlocked, reward

    def update_on_loss(self, session: GameSession) -> tuple[list[str], int]:
        st = self.get(session.user_id)
        bet = session.bet

        st.games_total += 1
        st.games_lost += 1
        st.total_bet += bet
        st.total_lost += bet
        if bet > st.worst_loss:
            st.worst_loss = bet
        if bet > st.biggest_bet:
            st.biggest_bet = bet

        if st.current_streak_type == "loss":
            st.current_streak += 1
        else:
            st.current_streak = 1
            st.current_streak_type = "loss"
        if st.current_streak > st.streak_losses:
            st.streak_losses = st.current_streak

        st.last_played = time.time()
        self._track_theme(st, session.theme)
        st.last_high_mult = 0.0

        ctx = AchievementContext(
            stats=st,
            bet=bet,
            win_amount=0,
            multiplier=0.0,
            duration=session.duration,
            net_profit=-bet,
            is_win=False,
            crash_point=session.crash_point,
            auto_used=False,
            near_miss=False,
            session_peak=session.peak,
        )
        unlocked = self._ach.evaluate(ctx)
        reward = AchievementManager.compute_reward(unlocked)
        if reward:
            st.reward_received += reward
            self._pending_reward[session.user_id] += reward
        self._dirty = True
        return unlocked, reward

    def consume_reward(self, user_id: int) -> int:
        return self._pending_reward.pop(user_id, 0)


# ═════════════════════════════════════════════════════════════════════
#                          HISTORY MANAGER
# ═════════════════════════════════════════════════════════════════════
class HistoryManager:
    __slots__ = ("capacity", "_items", "_badges_cache")

    def __init__(self, capacity: int = 50) -> None:
        self.capacity = capacity
        self._items: list[dict[str, Any]] = []
        self._badges_cache: Optional[str] = None

    async def load(self) -> None:
        async with _history_lock:
            if not HISTORY_FILE.exists():
                return
            try:
                self._items = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed loading crash history: %s", exc)

    async def flush(self) -> None:
        async with _history_lock:
            data = json.dumps(self._items[-self.capacity:], ensure_ascii=False, indent=2)
            try:
                await asyncio.to_thread(HISTORY_FILE.write_text, data, encoding="utf-8")
            except Exception as exc:
                logger.warning("Failed saving crash history: %s", exc)

    def add(self, multiplier: float) -> None:
        self._items.append({"mult": round(multiplier, 2), "ts": time.time()})
        if len(self._items) > self.capacity:
            del self._items[: len(self._items) - self.capacity]
        self._badges_cache = None

    def last_n(self, n: int = 20) -> list[float]:
        return [it["mult"] for it in self._items[-n:]]

    def average(self) -> float:
        if not self._items:
            return 0.0
        return sum(it["mult"] for it in self._items) / len(self._items)

    def median(self) -> float:
        if not self._items:
            return 0.0
        vals = sorted(it["mult"] for it in self._items)
        n = len(vals)
        return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2

    def max_recent(self, n: int = 50) -> float:
        if not self._items:
            return 0.0
        return max(it["mult"] for it in self._items[-n:])

    def badges(self) -> str:
        if self._badges_cache is None:
            self._badges_cache = _build_badges(self._items[-15:])
        return self._badges_cache


def _build_badges(items: list[dict[str, Any]]) -> str:
    if not items:
        return "—"
    out = []
    for it in items:
        m = it["mult"] if isinstance(it, dict) else it
        if m >= 10:
            out.append(f"🟣{m:.2f}x")
        elif m >= 2:
            out.append(f"🟢{m:.2f}x")
        else:
            out.append(f"🔴{m:.2f}x")
    return " ".join(out)


# ═════════════════════════════════════════════════════════════════════
#                          GLOBAL MANAGERS
# ═════════════════════════════════════════════════════════════════════
achievement_manager = AchievementManager()
stats_manager = StatsManager(achievement_manager)
history_manager = HistoryManager()


# ═════════════════════════════════════════════════════════════════════
#                              HELPERS
# ═════════════════════════════════════════════════════════════════════
def generate_crash_point() -> float:
    if _rng.randint(1, 100) <= INSTANT_CRASH_CHANCE:
        return 1.00
    u = _rng.random()
    if u < 0.5:
        return round(_rng.uniform(1.01, 2.00), 2)
    if u < 0.8:
        return round(_rng.uniform(2.00, 5.00), 2)
    if u < 0.95:
        return round(_rng.uniform(5.00, 15.00), 2)
    return round(_rng.uniform(15.00, 100.00), 2)


def multiplier_at_step(step: int) -> float:
    if 0 <= step < len(_MULT_BY_STEP):
        return _MULT_BY_STEP[step]
    return round(1.00 + (step ** GROWTH_EXP) * GROWTH_BASE, 2)


def pick_theme_for(user_id: int) -> Theme:
    try:
        return Theme(stats_manager.get(user_id).favorite_theme)
    except ValueError:
        return Theme.NEON


@lru_cache(maxsize=2048)
def format_amount(amount: int) -> str:
    sign = "-" if amount < 0 else ""
    a = -amount if amount < 0 else amount
    if a >= 1_000_000_000:
        return f"{sign}{a / 1_000_000_000:.2f}B"
    if a >= 1_000_000:
        return f"{sign}{a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"{sign}{a / 1_000:.1f}K"
    return f"{sign}{a}"


def progress_bar(value: float, maximum: float, length: int = 14,
                 fill: str = "█", empty: str = "░") -> str:
    if maximum <= 0:
        return empty * length
    ratio = value / maximum
    if ratio < 0:
        ratio = 0
    elif ratio > 1:
        ratio = 1
    filled = int(round(ratio * length))
    return fill * filled + empty * (length - filled)


def progress_bar_pct(pct: float, length: int = 12) -> str:
    return progress_bar(pct, 100.0, length)


def _parse_int(parts: list[str], idx: int) -> Optional[int]:
    try:
        return int(parts[idx])
    except (ValueError, IndexError):
        return None


def _parse_float(parts: list[str], idx: int) -> Optional[float]:
    try:
        return float(parts[idx])
    except (ValueError, IndexError):
        return None


def _classify_multiplier(m: float) -> str:
    if m >= 50:
        return "🟥"
    if m >= 10:
        return "🟣"
    if m >= 5:
        return "🟡"
    if m >= 2:
        return "🟢"
    return "🔴"


# ═════════════════════════════════════════════════════════════════════
#                        CHART RENDERER (reused Figure)
# ═════════════════════════════════════════════════════════════════════
class ChartRenderer:
    WIDTH = 10.0
    HEIGHT = 6.0
    DPI = 110

    _fig: ClassVar[Optional[Figure]] = None
    _canvas: ClassVar[Optional[FigureCanvasAgg]] = None
    _ax: ClassVar[Any] = None

    @classmethod
    def _ensure(cls):
        if cls._fig is None:
            cls._fig = Figure(figsize=(cls.WIDTH, cls.HEIGHT), dpi=cls.DPI)
            cls._canvas = FigureCanvasAgg(cls._fig)
            cls._ax = cls._fig.add_subplot(111)
        return cls._fig, cls._ax

    @staticmethod
    def _draw_static(ax, palette, theme, xmax, ymax):
        ax.set_facecolor(palette["bg_bot"])
        ax.imshow(_GRADIENT_BUF, aspect="auto", cmap=_THEME_CMAP[theme],
                  extent=(0, xmax, 1.0, ymax), origin="lower", zorder=0, alpha=0.95)
        grid_color = palette["grid"]
        for i in range(1, 7):
            r = i / 7
            ax.axhline(y=1.0 + (ymax - 1.0) * r, color=grid_color,
                       linestyle="--", linewidth=0.6, alpha=0.45, zorder=1)
            ax.axvline(x=xmax * r, color=grid_color,
                       linestyle="--", linewidth=0.6, alpha=0.3, zorder=1)

    @staticmethod
    def _draw_trajectory(ax, palette, theme, path, crashed, cashed_out, fast=False):
        n = len(path)
        if n < 2:
            xs = np.array([0.0, 0.01])
            ys = np.array([1.0, 1.0])
        else:
            num = max(80 if fast else 150, n * (6 if fast else 8))
            xs = np.linspace(0, n - 1, num=num)
            ys = np.interp(xs, np.arange(n), path)

        points = np.column_stack([xs, ys]).reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)

        glow_color = palette["line_glow"]
        line_color = palette["line"]
        if crashed:
            line_color, glow_color = palette["crash"], "#ff0033"
        elif cashed_out:
            line_color, glow_color = palette["win"], "#33ff66"

        glow_pairs = ((10, 0.16), (4, 0.5)) if fast else (
            (14, 0.08), (10, 0.16), (7, 0.28), (4, 0.55)
        )
        for width, alpha in glow_pairs:
            ax.add_collection(LineCollection(segments, colors=glow_color,
                                             linewidth=width, alpha=alpha, zorder=2))
        ax.add_collection(LineCollection(segments, colors=line_color,
                                         linewidth=2.4, zorder=4))
        ax.fill_between(xs, 1.0, ys, color=_THEME_FILL_RGBA[theme], zorder=1)
        return xs[-1], ys[-1]

    @staticmethod
    def _draw_rocket(ax, palette, x, y, crashed, cashed_out):
        if crashed:
            for radius, alpha in ((0.5, 0.7), (0.35, 0.85), (0.2, 1.0)):
                ax.add_patch(Circle((x, y), radius=radius, color=palette["crash"],
                                    alpha=alpha, zorder=6))
            ax.text(x, y, "💥", fontsize=28, ha="center", va="center", zorder=7)
        else:
            color = palette["win"] if cashed_out else palette["rocket"]
            for radius, alpha in ((0.32, 0.35), (0.22, 0.55), (0.13, 0.85)):
                ax.add_patch(Circle((x, y), radius=radius, color=color,
                                    alpha=alpha, zorder=5))
            ax.text(x, y, "💰" if cashed_out else "🚀",
                    fontsize=22, ha="center", va="center", zorder=8)

    @staticmethod
    def _draw_chrome(ax, palette, xmax, ymax, mult, status, footer):
        ax.tick_params(colors=palette["text"], labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(palette["grid"])
            spine.set_linewidth(1.2)
        yticks = [round(1.0 + (ymax - 1.0) * i / 5, 2) for i in range(6)]
        ax.set_yticks(yticks)
        ax.set_yticklabels([f"{v:.2f}x" for v in yticks])
        ax.set_xticks([])

        ax.text(xmax / 2, (1.0 + ymax) / 2, f"{mult:.2f}x",
                fontsize=72, color=palette["text"], alpha=0.07,
                ha="center", va="center", fontweight="bold", zorder=2)
        ax.text(0.02, 0.95, f"{mult:.2f}x", transform=ax.transAxes, fontsize=36,
                color=palette["text"], fontweight="bold", ha="left", va="top", zorder=10)
        ax.text(0.02, 0.83, status, transform=ax.transAxes, fontsize=14,
                color=palette["accent"], ha="left", va="top", zorder=10)
        ax.text(0.98, 0.04, footer, transform=ax.transAxes, fontsize=10,
                color=palette["text"], alpha=0.7, ha="right", va="bottom", zorder=10)

    @classmethod
    def render(cls, session: GameSession, status: str, crashed: bool,
               cashed_out: bool, summary: bool = False, win_amount: int = 0) -> bytes:
        path = session.path_points or [1.00]
        peak = max(path)
        ymax = max(peak * (1.2 if summary else 1.18), 1.2)
        xmax = max(len(path) - 1, 1) * 1.05

        fig, ax = cls._ensure()
        ax.clear()
        palette = THEMES[session.theme]

        cls._draw_static(ax, palette, session.theme, xmax, ymax)
        x_end, y_end = cls._draw_trajectory(
            ax, palette, session.theme, path, crashed, cashed_out, fast=not summary
        )
        cls._draw_rocket(ax, palette, x_end, y_end, crashed, cashed_out)

        if summary:
            footer = (
                f"Чистая прибыль: +{format_amount(win_amount - session.bet)} сыр."
                if cashed_out else
                f"Потеря: -{format_amount(session.bet)} сыр."
            )
        else:
            footer = f"Ставка: {format_amount(session.bet)} · {session.full_name}"

        cls._draw_chrome(ax, palette, xmax, ymax, session.current_multiplier, status, footer)
        ax.set_xlim(0, xmax)
        ax.set_ylim(1.0, ymax)
        fig.patch.set_facecolor(palette["bg_top"])
        fig.subplots_adjust(left=0.07, right=0.97, top=0.95, bottom=0.06)

        buf = io.BytesIO()
        cls._canvas.draw()
        fig.savefig(buf, format="png", facecolor=palette["bg_top"], edgecolor="none")
        return buf.getvalue()


def _render_blocking(session: GameSession, status: str, crashed: bool,
                     cashed_out: bool, summary: bool, win_amount: int) -> bytes:
    return ChartRenderer.render(session, status, crashed, cashed_out, summary, win_amount)


async def render_chart(session: GameSession, status: str = "В ПОЛЕТЕ",
                       crashed: bool = False, cashed_out: bool = False) -> bytes:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _render_executor, _render_blocking, session, status, crashed, cashed_out, False, 0,
    )


async def render_summary(session: GameSession, won: bool, win_amount: int) -> bytes:
    loop = asyncio.get_running_loop()
    status = "✅ ОБНАЛИЧЕНО" if won else "💥 КРАШ"
    return await loop.run_in_executor(
        _render_executor, _render_blocking, session, status, not won, won, True, win_amount,
    )


# ═════════════════════════════════════════════════════════════════════
#                              KEYBOARDS
# ═════════════════════════════════════════════════════════════════════
def get_crash_keyboard(game_id: str, current_mult: float, auto: Optional[float]) -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(
        text=f"💰 ОБНАЛИЧИТЬ × {current_mult:.2f}",
        callback_data=f"crash_cashout_{game_id}",
    ))
    if auto:
        b.row(types.InlineKeyboardButton(
            text=f"🤖 Авто: {auto:.2f}x · отключить",
            callback_data=f"crash_auto_off_{game_id}",
        ))
    return b.as_markup()


def get_pre_game_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="🎨 Тема", callback_data=f"crash_theme_menu_{bet}"),
        types.InlineKeyboardButton(text="🤖 Авто-cashout", callback_data=f"crash_auto_menu_{bet}"),
    )
    b.row(types.InlineKeyboardButton(text="🚀 ВЗЛЕТЕТЬ!", callback_data=f"cas_conf_crash_{bet}"))
    b.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data="crash_cancel"))
    return b.as_markup()


def get_replay_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text=f"🔁 Повтор ({format_amount(bet)})",
                                   callback_data=f"crash_replay_{bet}"),
        types.InlineKeyboardButton(text="× 2", callback_data=f"crash_replay_{bet * 2}"),
    )
    b.row(
        types.InlineKeyboardButton(text="📊 Статистика", callback_data="crash_my_stats"),
        types.InlineKeyboardButton(text="🏅 Достижения", callback_data="crash_ach_0"),
    )
    b.row(types.InlineKeyboardButton(text="📜 История", callback_data="crash_history"))
    return b.as_markup()


def get_theme_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for theme in Theme:
        b.add(types.InlineKeyboardButton(
            text=f"🎨 {theme.value.title()}",
            callback_data=f"crash_theme_set_{theme.value}_{bet}",
        ))
    b.adjust(2)
    b.row(types.InlineKeyboardButton(text="↩️ Назад", callback_data=f"crash_back_{bet}"))
    return b.as_markup()


def get_auto_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for preset in AUTO_PRESETS:
        b.add(types.InlineKeyboardButton(
            text=f"× {preset:.1f}",
            callback_data=f"crash_auto_set_{preset}_{bet}",
        ))
    b.adjust(3)
    b.row(types.InlineKeyboardButton(text="🚫 Отключить",
                                     callback_data=f"crash_auto_set_0_{bet}"))
    b.row(types.InlineKeyboardButton(text="↩️ Назад", callback_data=f"crash_back_{bet}"))
    return b.as_markup()


def get_stats_keyboard() -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="🏅 Достижения", callback_data="crash_ach_0"),
        types.InlineKeyboardButton(text="📜 История", callback_data="crash_history"),
    )
    b.row(types.InlineKeyboardButton(text="❌ Закрыть", callback_data="crash_close"))
    return b.as_markup()


def get_achievements_keyboard(page: int, total_pages: int,
                              category: Optional[AchCategory] = None) -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    # Category filter row
    cat_buttons = []
    cat_buttons.append(types.InlineKeyboardButton(
        text=("• Все •" if category is None else "Все"),
        callback_data="crash_ach_cat_all",
    ))
    for c in AchCategory:
        meta = CATEGORY_META[c]
        label = f"{meta['icon']}{meta['label']}"
        if c == category:
            label = "• " + label + " •"
        cat_buttons.append(types.InlineKeyboardButton(
            text=label,
            callback_data=f"crash_ach_cat_{c.value}",
        ))
    for btn in cat_buttons:
        b.add(btn)
    b.adjust(3)

    # Pagination row
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(
            text="⬅️", callback_data=f"crash_ach_{page - 1}" + (
                f"_{category.value}" if category else ""
            ),
        ))
    nav.append(types.InlineKeyboardButton(
        text=f"{page + 1}/{max(1, total_pages)}", callback_data="crash_noop",
    ))
    if page + 1 < total_pages:
        nav.append(types.InlineKeyboardButton(
            text="➡️", callback_data=f"crash_ach_{page + 1}" + (
                f"_{category.value}" if category else ""
            ),
        ))
    if nav:
        b.row(*nav)

    b.row(
        types.InlineKeyboardButton(text="📊 Статистика", callback_data="crash_my_stats"),
        types.InlineKeyboardButton(text="🏆 Лидеры", callback_data="crash_ach_top"),
    )
    b.row(types.InlineKeyboardButton(text="❌ Закрыть", callback_data="crash_close"))
    return b.as_markup()


def get_close_keyboard() -> types.InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="❌ Закрыть", callback_data="crash_close"))
    return b.as_markup()


# ═════════════════════════════════════════════════════════════════════
#                          TEXT FORMATTERS
# ═════════════════════════════════════════════════════════════════════
_SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━"
ACH_PAGE_SIZE = 6


def format_pre_game(bet: int, theme: Theme, auto: Optional[float], full_name: str) -> str:
    auto_text = f"<b>× {auto:.2f}</b>" if auto else "<i>выключен</i>"
    return (
        f"✈️ <b>КРАШ-АВИАТОР · Подготовка к полету</b> ✈️\n{_SEP}\n"
        f"👤 Пилот: <b>{full_name}</b>\n"
        f"💰 Ставка: <b>{format_amount(bet)}</b> сыр.\n"
        f"🎨 Тема: <b>{theme.value.title()}</b>\n"
        f"🤖 Авто-cashout: {auto_text}\n{_SEP}\n"
        f"📈 Среднее за сессию: <b>{history_manager.average():.2f}x</b>\n"
        f"🕘 Последние полеты:\n<code>{history_manager.badges()}</code>\n{_SEP}\n"
        f"Готов? Нажми <b>🚀 ВЗЛЕТЕТЬ!</b>"
    )


def format_inflight(session: GameSession) -> str:
    auto_txt = f"<b>×{session.auto_cashout:.2f}</b>" if session.auto_cashout else "<i>—</i>"
    return (
        f"🚀 <b>В ПОЛЕТЕ · {session.current_multiplier:.2f}x</b>\n"
        f"👤 {session.full_name}\n"
        f"💰 Ставка: <b>{format_amount(session.bet)}</b> сыр.\n"
        f"📈 Потенциал: <b>{format_amount(int(session.bet * session.current_multiplier))}</b>\n"
        f"⏱ Время: <b>{session.duration:.1f}с</b>\n"
        f"🎯 Авто: {auto_txt}\n{_SEP}\n"
        f"👉 Жми ОБНАЛИЧИТЬ пока не поздно!"
    )


def format_crash(session: GameSession) -> str:
    return (
        f"💥 <b>КРАШ · {session.crash_point:.2f}x</b>\n"
        f"👤 {session.full_name}\n"
        f"💸 Потеряно: <b>-{format_amount(session.bet)}</b> сыр.\n"
        f"⏱ Длительность: <b>{session.duration:.1f}с</b>\n{_SEP}\n"
        f"🕘 Последние полеты:\n<code>{history_manager.badges()}</code>"
    )


def format_cashout(session: GameSession, win_amount: int) -> str:
    net = win_amount - session.bet
    return (
        f"🎉 <b>ОБНАЛИЧЕНО · {session.current_multiplier:.2f}x</b>\n"
        f"👤 {session.full_name}\n"
        f"💰 Ставка: <b>{format_amount(session.bet)}</b> сыр.\n"
        f"✨ Чистая прибыль: <b>+{format_amount(net)}</b> сыр.\n"
        f"💎 Всего получено: <b>{format_amount(win_amount)}</b> сыр.\n"
        f"⏱ Время полета: <b>{session.duration:.1f}с</b>\n{_SEP}\n"
        f"🕘 Последние полеты:\n<code>{history_manager.badges()}</code>"
    )


def format_stats_card(user_id: int, full_name: str) -> str:
    st = stats_manager.get(user_id)
    win_bar = progress_bar(st.win_rate, 100)
    profit_color = "🟢" if st.profit >= 0 else "🔴"
    streak_emoji = "🔥" if st.current_streak_type == "win" else (
        "🥶" if st.current_streak_type == "loss" else "⚪"
    )
    completion = achievement_manager.completion(st)
    ach_bar = progress_bar(completion, 100)
    return (
        f"📊 <b>Статистика КРАШ-АВИАТОРА</b>\n{_SEP}\n"
        f"👤 {full_name}\n"
        f"🎮 Всего полетов: <b>{st.games_total}</b>\n"
        f"✅ Выигрышей: <b>{st.games_won}</b> ({st.win_rate:.1f}%)\n"
        f"<code>{win_bar}</code>\n"
        f"❌ Поражений: <b>{st.games_lost}</b>\n{_SEP}\n"
        f"💰 Общий оборот: <b>{format_amount(st.total_bet)}</b>\n"
        f"{profit_color} Чистая прибыль: <b>{format_amount(st.profit)}</b>\n"
        f"📈 Средняя ставка: <b>{format_amount(int(st.avg_bet))}</b>\n"
        f"💎 Макс. ставка: <b>{format_amount(st.biggest_bet)}</b>\n{_SEP}\n"
        f"🏆 Лучший коэф.: <b>{st.best_multiplier:.2f}x</b>\n"
        f"💎 Лучший выигрыш: <b>+{format_amount(st.best_win)}</b>\n"
        f"💀 Худший проигрыш: <b>-{format_amount(st.worst_loss)}</b>\n{_SEP}\n"
        f"{streak_emoji} Текущий стрик: <b>{st.current_streak}</b> ({st.current_streak_type})\n"
        f"🔥 Макс. winstreak: <b>{st.streak_wins}</b>\n"
        f"🥶 Макс. losestreak: <b>{st.streak_losses}</b>\n{_SEP}\n"
        f"🏅 Достижений: <b>{len(st.achievements)}/{achievement_manager.total_count()}</b> "
        f"({completion:.1f}%)\n"
        f"<code>{ach_bar}</code>\n"
        f"🪙 Награды получено: <b>{format_amount(st.reward_received)}</b> сыр.\n"
        f"⭐ Рейтинг достижений: <b>{st.achievement_score}</b>"
    )


def _format_ach_line(ach: Achievement, st: PlayerStats, show_progress: bool = True) -> str:
    is_unlocked = ach.code in st.achievements
    rarity_mark = RARITY_META[ach.rarity]["color"]
    rarity_label = RARITY_META[ach.rarity]["label"]

    if is_unlocked:
        date = st.achievement_dates.get(ach.code)
        date_txt = ""
        if date:
            date_txt = f" · <i>{time.strftime('%d.%m.%Y', time.localtime(date))}</i>"
        return (
            f"✅ {ach.icon} <b>{ach.title}</b> {rarity_mark}\n"
            f"   <i>{ach.description}</i>\n"
            f"   <b>+{format_amount(ach.reward)}</b> · {rarity_label}{date_txt}"
        )

    if ach.hidden:
        return (
            f"🔒 ❓ <b>???</b> {rarity_mark}\n"
            f"   <i>Тайное достижение</i>\n"
            f"   <b>+{format_amount(ach.reward)}</b> · {rarity_label}"
        )

    prog = achievement_manager.progress_of(st, ach.code)
    bar = progress_bar(prog * 100, 100, 10)
    prog_txt = f"\n   <code>{bar}</code> {prog * 100:.0f}%" if show_progress else ""
    return (
        f"🔒 {ach.icon} <b>{ach.title}</b> {rarity_mark}\n"
        f"   <i>{ach.description}</i>\n"
        f"   <b>+{format_amount(ach.reward)}</b> · {rarity_label}{prog_txt}"
    )


def format_achievements_page(user_id: int, full_name: str, page: int,
                             category: Optional[AchCategory] = None) -> tuple[str, int]:
    st = stats_manager.get(user_id)

    if category is None:
        items = list(_ACHIEVEMENTS_LIST)
    else:
        items = ACHIEVEMENTS_BY_CATEGORY.get(category, [])

    # sort: unlocked first (by date desc), then by rarity weight ascending, then by code
    def _sort_key(a: Achievement):
        unlocked = a.code in st.achievements
        date = st.achievement_dates.get(a.code, 0.0)
        rarity_w = RARITY_META[a.rarity]["weight"]
        # unlocked first → 0, locked → 1
        return (0 if unlocked else 1, -date, rarity_w, a.code)

    items = sorted(items, key=_sort_key)
    total = len(items)
    total_pages = max(1, math.ceil(total / ACH_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    start = page * ACH_PAGE_SIZE
    slice_items = items[start:start + ACH_PAGE_SIZE]

    completion = achievement_manager.completion(st)
    header_cat = f" · {CATEGORY_META[category]['label']}" if category else ""
    lines = [
        f"🏅 <b>Достижения{header_cat} · {full_name}</b>",
        _SEP,
        f"Прогресс: <b>{len(st.achievements)}/{achievement_manager.total_count()}</b> "
        f"({completion:.1f}%)",
        f"<code>{progress_bar(completion, 100)}</code>",
        f"⭐ Рейтинг: <b>{st.achievement_score}</b>",
        _SEP,
    ]
    if not slice_items:
        lines.append("<i>В этой категории нет достижений.</i>")
    else:
        for ach in slice_items:
            lines.append(_format_ach_line(ach, st))
            lines.append("")
    lines.append(_SEP)
    lines.append(f"Страница {page + 1}/{total_pages}")
    return "\n".join(lines), total_pages


def format_history_card() -> str:
    items = history_manager.last_n(25)
    if not items:
        return "📜 История пуста."
    lines = ["📜 <b>История последних полетов</b>", _SEP]
    chunks = [
        (f"🟥{m:.2f}x" if m >= 50 else
         f"🟣{m:.2f}x" if m >= 10 else
         f"🟡{m:.2f}x" if m >= 5 else
         f"🟢{m:.2f}x" if m >= 2 else
         f"🔴{m:.2f}x")
        for m in items
    ]
    for i in range(0, len(chunks), 5):
        lines.append("<code>" + "  ".join(chunks[i:i + 5]) + "</code>")
    lines.append(_SEP)
    lines.append(f"Среднее: <b>{history_manager.average():.2f}x</b>")
    lines.append(f"Медиана: <b>{history_manager.median():.2f}x</b>")
    lines.append(f"Максимум: <b>{history_manager.max_recent():.2f}x</b>")
    return "\n".join(lines)


def format_achievement_leaderboard() -> str:
    players = stats_manager.all_players()
    if not players:
        return "🏆 Лидерборд пуст."
    top = sorted(players, key=lambda s: (-s.achievement_score, -len(s.achievements)))[:10]
    medals = ("🥇", "🥈", "🥉")
    lines = ["🏆 <b>Топ-10 по достижениям</b>", _SEP]
    for i, st in enumerate(top):
        medal = medals[i] if i < 3 else f"#{i + 1}"
        lines.append(
            f"{medal} ID <code>{st.user_id}</code> · "
            f"⭐ {st.achievement_score} · "
            f"🏅 {len(st.achievements)}/{achievement_manager.total_count()}"
        )
    return "\n".join(lines)


def format_achievement_notification(codes: list[str], total_reward: int) -> str:
    """Beautiful notification message for newly unlocked achievements."""
    if not codes:
        return ""
    lines = ["✨ <b>НОВЫЕ ДОСТИЖЕНИЯ!</b> ✨", _SEP]
    for c in codes:
        ach = ACHIEVEMENTS.get(c)
        if ach is None:
            continue
        rarity = RARITY_META[ach.rarity]
        lines.append(
            f"{rarity['color']} {ach.icon} <b>{ach.title}</b>\n"
            f"   <i>{ach.description}</i>\n"
            f"   💎 <b>{rarity['label']}</b> · 🪙 +{format_amount(ach.reward)} сыр."
        )
    if total_reward:
        lines.append(_SEP)
        lines.append(f"💰 <b>Итого награда: +{format_amount(total_reward)} сыр.</b>")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
#                          EDIT HELPERS
# ═════════════════════════════════════════════════════════════════════
async def safe_edit_message(message: types.Message, text: str, reply_markup=None) -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return True
        logger.debug("Crash edit failed: %s", exc)
    except Exception as exc:
        logger.debug("Crash edit failed: %s", exc)
    return False


async def safe_edit_media(message: types.Message, image: bytes, caption: str,
                          reply_markup=None) -> bool:
    try:
        await message.edit_media(
            media=InputMediaPhoto(
                media=BufferedInputFile(image, filename="crash.png"),
                caption=caption,
            ),
            reply_markup=reply_markup,
        )
        return True
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return True
        logger.debug("Crash media edit failed: %s", exc)
    except Exception as exc:
        logger.debug("Crash media edit failed: %s", exc)
    try:
        await message.edit_caption(caption=caption, reply_markup=reply_markup)
        return True
    except Exception as exc2:
        logger.debug("Crash caption edit failed: %s", exc2)
    return False


async def announce_achievements(message: types.Message, codes: list[str],
                                reward: int, user_id: int) -> None:
    """Posts a single rich notification with all newly unlocked achievements + grants reward."""
    if not codes:
        return
    text = format_achievement_notification(codes, reward)
    if not text:
        return

    # Credit reward immediately and invalidate cache
    if reward > 0:
        try:
            await update_user_balance(
                message.chat.id, user_id, reward,
                action=f"Crash Achievement Reward x{len(codes)}",
            )
            invalidate_user_cache(message.chat.id, user_id)
            stats_manager.consume_reward(user_id)
        except Exception as exc:
            logger.debug("Failed crediting achievement reward: %s", exc)

    try:
        notice = await message.answer(text)
        asyncio.create_task(schedule_delete(notice, ACHIEVEMENT_NOTIFY_DELAY))
    except Exception as exc:
        logger.debug("Achievement notify failed: %s", exc)


# ═════════════════════════════════════════════════════════════════════
#                              HANDLERS
# ═════════════════════════════════════════════════════════════════════
@router.message(Command("crash"))
async def cmd_crash(message: types.Message, state: FSMContext):
    if await state.get_state() == CrashState.playing.state:
        await state.clear()

    chat_id, user_id = message.chat.id, message.from_user.id
    full_name = escape_html(message.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get("is_banned"):
        return

    try:
        from diseases import get_active_diseases
        if "gonorrhea" in await get_active_diseases(chat_id, user_id):
            return await message.answer(
                "🦠 <b>Гонорея</b>: Пилоты самолета отказываются сажать тебя на борт. Лечись!"
            )
    except Exception as exc:
        logger.debug("Disease check skipped: %s", exc)

    args = message.text.split()
    if len(args) < 2:
        kb = InlineKeyboardBuilder()
        for preset in PRESET_BETS:
            kb.add(types.InlineKeyboardButton(
                text=f"💵 {format_amount(preset)}",
                callback_data=f"crash_preset_{preset}",
            ))
        kb.adjust(2)
        return await message.answer(
            "💡 <b>Укажи ставку</b>: <code>/crash 1000</code>\nИли выбери из пресетов ниже:",
            reply_markup=kb.as_markup(),
        )

    try:
        bet = int(args[1])
        if not (MIN_BET <= bet <= MAX_BET):
            raise ValueError
    except ValueError:
        return await message.answer(
            f"Ставка должна быть числом от {MIN_BET} до {MAX_BET:,} сыроежек."
        )

    if data.get("balance", 0) - bet < CREDIT_LIMIT:
        return await message.answer(
            "Ваш кредитный лимит (-5000) исчерпан. Пополните баланс."
        )

    theme = pick_theme_for(user_id)
    auto = stats_manager.get(user_id).auto_default
    await message.answer(
        format_pre_game(bet, theme, auto, full_name),
        reply_markup=get_pre_game_keyboard(bet),
    )


@router.callback_query(F.data.startswith("crash_preset_"))
async def cb_preset(callback: types.CallbackQuery):
    bet = _parse_int(callback.data.split("_"), 2)
    if bet is None:
        return await callback.answer()
    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)
    if data.get("balance", 0) - bet < CREDIT_LIMIT:
        return await callback.answer("Кредитный лимит исчерпан!", show_alert=True)
    theme = pick_theme_for(user_id)
    auto = stats_manager.get(user_id).auto_default
    await safe_edit_message(
        callback.message,
        format_pre_game(bet, theme, auto, full_name),
        reply_markup=get_pre_game_keyboard(bet),
    )
    await callback.answer()


@router.callback_query(F.data == "crash_cancel")
async def cb_cancel(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Отменено.")


@router.callback_query(F.data.startswith("crash_theme_menu_"))
async def cb_theme_menu(callback: types.CallbackQuery):
    bet = _parse_int(callback.data.split("_"), 3)
    if bet is None:
        return await callback.answer()
    await safe_edit_message(
        callback.message, "🎨 <b>Выбери визуальную тему</b>:",
        reply_markup=get_theme_keyboard(bet),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crash_theme_set_"))
async def cb_theme_set(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 5:
        return await callback.answer()
    try:
        theme = Theme(parts[3])
        bet = int(parts[4])
    except (ValueError, IndexError):
        return await callback.answer()
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    st = stats_manager.get(user_id)
    st.favorite_theme = theme.value
    if theme.value not in st.themes_used:
        st.themes_used.append(theme.value)
    stats_manager.mark_dirty()
    await safe_edit_message(
        callback.message,
        format_pre_game(bet, theme, st.auto_default, full_name),
        reply_markup=get_pre_game_keyboard(bet),
    )
    await callback.answer(f"Тема: {theme.value}")


@router.callback_query(F.data.startswith("crash_auto_menu_"))
async def cb_auto_menu(callback: types.CallbackQuery):
    bet = _parse_int(callback.data.split("_"), 3)
    if bet is None:
        return await callback.answer()
    await safe_edit_message(
        callback.message,
        "🤖 <b>Авто-cashout</b> — выбери множитель, на котором система "
        "автоматически обналичит ставку:",
        reply_markup=get_auto_keyboard(bet),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crash_auto_set_"))
async def cb_auto_set(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 5:
        return await callback.answer()
    value = _parse_float(parts, 3)
    bet = _parse_int(parts, 4)
    if value is None or bet is None:
        return await callback.answer()
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    st = stats_manager.get(user_id)
    st.auto_default = value if value > 1.0 else None
    stats_manager.mark_dirty()
    theme = pick_theme_for(user_id)
    await safe_edit_message(
        callback.message,
        format_pre_game(bet, theme, st.auto_default, full_name),
        reply_markup=get_pre_game_keyboard(bet),
    )
    await callback.answer("Сохранено.")


@router.callback_query(F.data.startswith("crash_back_"))
async def cb_back(callback: types.CallbackQuery):
    bet = _parse_int(callback.data.split("_"), 2)
    if bet is None:
        return await callback.answer()
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    theme = pick_theme_for(user_id)
    auto = stats_manager.get(user_id).auto_default
    await safe_edit_message(
        callback.message,
        format_pre_game(bet, theme, auto, full_name),
        reply_markup=get_pre_game_keyboard(bet),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cas_conf_crash_"))
async def process_crash_confirm(callback: types.CallbackQuery, state: FSMContext):
    bet = _parse_int(callback.data.split("_"), 3)
    if bet is None:
        return

    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    message_id = callback.message.message_id
    
    from casino_utils import try_acquire_confirm_lock, release_confirm_lock
    if not try_acquire_confirm_lock(chat_id, message_id):
        return await callback.answer("Ваша ставка уже обрабатывается...", show_alert=True)
        
    try:
        full_name = escape_html(callback.from_user.full_name)
    
        new_balance = await update_user_balance(
            chat_id, user_id, -bet, min_balance=CREDIT_LIMIT, action="Crash Bet",
        )
        if new_balance is None:
            return await callback.answer("Недостаточно средств!", show_alert=True)
    
        try:
            await callback.message.delete()
        except Exception:
            pass
    
        theme = pick_theme_for(user_id)
        st = stats_manager.get(user_id)
        auto = st.auto_default
        crash_point = generate_crash_point()
        game_id = f"{chat_id}_{user_id}_{int(time.time() * 1000)}"
    
        session = GameSession(
            game_id=game_id, chat_id=chat_id, user_id=user_id, full_name=full_name,
            bet=bet, crash_point=crash_point, theme=theme, auto_cashout=auto,
        )
        _active_games[game_id] = session
    
        await state.set_state(CrashState.playing)
        await state.update_data(game_id=game_id)
    
        image = await render_chart(session, status="🛫 ВЗЛЕТ")
        caption = format_inflight(session)
        keyboard = get_crash_keyboard(game_id, 1.00, auto)
    
        try:
            msg = await callback.message.answer_photo(
                photo=BufferedInputFile(image, filename="crash.png"),
                caption=caption, reply_markup=keyboard,
            )
            session.message_id = msg.message_id
        except Exception as exc:
            logger.error("Failed to send crash photo: %s", exc)
            msg = await callback.message.answer(caption, reply_markup=keyboard)
            session.message_id = msg.message_id
    
        asyncio.create_task(run_crash_loop(msg, state, game_id))
    finally:
        release_confirm_lock(chat_id, message_id)


async def run_crash_loop(message: types.Message, state: FSMContext, game_id: str):
    try:
        session = _active_games.get(game_id)
        if session is None:
            return

        for step in range(1, MAX_FLIGHT_STEPS):
            data = await state.get_data()
            if data.get("game_id") != game_id:
                break
            if (await state.get_state()) != CrashState.playing.state:
                break
            if session.cashed_out or session.cancelled:
                break

            current_mult = multiplier_at_step(step)
            crash_pt = session.crash_point

            if (session.auto_cashout and current_mult >= session.auto_cashout
                    and current_mult < crash_pt):
                session.current_multiplier = round(min(session.auto_cashout, current_mult), 2)
                # Detect near-miss: very close to crash
                if crash_pt - session.current_multiplier <= 0.10:
                    session.near_miss = True
                session.add_point(session.current_multiplier)
                await cashout_session(message, state, session, auto=True)
                return

            if current_mult >= crash_pt:
                session.current_multiplier = crash_pt
                session.add_point(crash_pt)
                await crash_session(message, state, session)
                return

            session.current_multiplier = current_mult
            session.add_point(current_mult)

            try:
                image = await render_chart(session, status="🚀 В ПОЛЕТЕ")
                await safe_edit_media(
                    message, image, format_inflight(session),
                    reply_markup=get_crash_keyboard(game_id, current_mult, session.auto_cashout),
                )
            except Exception as exc:
                logger.debug("Inflight update failed: %s", exc)

            await asyncio.sleep(FRAME_DELAY)

        if ((await state.get_state()) == CrashState.playing.state
                and not session.cashed_out and not session.cancelled):
            await cashout_session(message, state, session, auto=True, forced=True)
    except asyncio.CancelledError:
        logger.debug("Crash loop cancelled for %s", game_id)
        raise
    except Exception as exc:
        logger.exception("Crash loop error: %s", exc)
    finally:
        _active_games.pop(game_id, None)


async def crash_session(message: types.Message, state: FSMContext, session: GameSession):
    session.finished = True
    await state.clear()
    invalidate_user_cache(session.chat_id, session.user_id)
    history_manager.add(session.crash_point)

    unlocked, reward = stats_manager.update_on_loss(session)

    # I/O в фоне
    asyncio.create_task(stats_manager.flush())
    asyncio.create_task(history_manager.flush())
    asyncio.create_task(achievement_manager.flush())

    try:
        image = await render_summary(session, won=False, win_amount=0)
        await safe_edit_media(
            message, image, format_crash(session),
            reply_markup=get_replay_keyboard(session.bet),
        )
    except Exception as exc:
        logger.debug("Crash summary edit failed: %s", exc)

    asyncio.create_task(schedule_delete(message, AUTO_DELETE_DELAY))
    await announce_achievements(message, unlocked, reward, session.user_id)


async def cashout_session(message: types.Message, state: FSMContext, session: GameSession,
                          auto: bool = False, forced: bool = False):
    if session.cashed_out:
        return
    session.cashed_out = True
    session.finished = True
    session.cashout_at = session.current_multiplier
    await state.clear()

    # Detect near-miss if not yet set
    if not session.near_miss:
        if session.crash_point - session.current_multiplier <= 0.10:
            session.near_miss = True

    win_amount = int(session.bet * session.current_multiplier)
    await update_user_balance(
        session.chat_id, session.user_id, win_amount, action="Crash Cashout",
    )
    invalidate_user_cache(session.chat_id, session.user_id)
    history_manager.add(session.current_multiplier)

    unlocked, reward = stats_manager.update_on_win(session, win_amount)

    asyncio.create_task(stats_manager.flush())
    asyncio.create_task(history_manager.flush())
    asyncio.create_task(achievement_manager.flush())

    try:
        image = await render_summary(session, won=True, win_amount=win_amount)
        caption = format_cashout(session, win_amount)
        if auto:
            prefix = "🛬 ФОРСИРОВАННЫЙ CASHOUT" if forced else "🛬 АВТО-CASHOUT"
            caption = prefix + "\n\n" + caption
        await safe_edit_media(
            message, image, caption,
            reply_markup=get_replay_keyboard(session.bet),
        )
    except Exception as exc:
        logger.debug("Cashout summary edit failed: %s", exc)

    asyncio.create_task(schedule_delete(message, AUTO_DELETE_DELAY))
    await announce_achievements(message, unlocked, reward, session.user_id)


@router.callback_query(F.data.startswith("crash_cashout_"))
async def process_crash_cashout(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() != CrashState.playing.state:
        return await callback.answer()

    data = await state.get_data()
    game_id = data.get("game_id")
    session = _active_games.get(game_id) if game_id else None
    if session is None:
        return await callback.answer("Игра не найдена.", show_alert=True)
    if callback.from_user.id != session.user_id:
        return await callback.answer("Это не ваш полет!", show_alert=True)
    if session.cashed_out or session.finished:
        return await callback.answer("Уже завершено.")

    await callback.answer("💰 Обналичено!")
    await cashout_session(callback.message, state, session, auto=False)


@router.callback_query(F.data.startswith("crash_auto_off_"))
async def cb_auto_off_inflight(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    game_id = data.get("game_id")
    session = _active_games.get(game_id) if game_id else None
    if session is None or callback.from_user.id != session.user_id:
        return await callback.answer()
    session.auto_cashout = None
    await callback.answer("Авто-cashout отключен.")


@router.callback_query(F.data.startswith("crash_replay_"))
async def process_crash_replay(callback: types.CallbackQuery, state: FSMContext):
    bet = _parse_int(callback.data.split("_"), 2)
    if bet is None:
        return await callback.answer()

    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get("is_banned"):
        return await callback.answer("⛔ Вы заблокированы.", show_alert=True)
    if data.get("balance", 0) - bet < CREDIT_LIMIT:
        return await callback.answer("💳 Недостаточно средств.", show_alert=True)
    if not (MIN_BET <= bet <= MAX_BET):
        return await callback.answer("Ставка вне диапазона.", show_alert=True)

    try:
        await callback.message.delete()
    except Exception:
        pass

    theme = pick_theme_for(user_id)
    auto = stats_manager.get(user_id).auto_default
    await callback.message.answer(
        format_pre_game(bet, theme, auto, full_name),
        reply_markup=get_pre_game_keyboard(bet),
    )
    await callback.answer("🔁 Поехали!")


@router.callback_query(F.data == "crash_my_stats")
async def cb_my_stats(callback: types.CallbackQuery):
    full_name = escape_html(callback.from_user.full_name)
    try:
        await callback.message.answer(
            format_stats_card(callback.from_user.id, full_name),
            reply_markup=get_stats_keyboard(),
        )
    except Exception:
        pass
    await callback.answer()


# ───────────────── Achievement page handlers ─────────────────
async def _send_achievement_page(message: types.Message, user_id: int, full_name: str,
                                 page: int, category: Optional[AchCategory],
                                 edit: bool = False) -> None:
    text, total_pages = format_achievements_page(user_id, full_name, page, category)
    kb = get_achievements_keyboard(page, total_pages, category)
    if edit:
        ok = await safe_edit_message(message, text, reply_markup=kb)
        if ok:
            return
    try:
        await message.answer(text, reply_markup=kb)
    except Exception as exc:
        logger.debug("Achievement send failed: %s", exc)


@router.callback_query(F.data.regexp(r"^crash_ach_\d+(?:_[a-z]+)?$"))
async def cb_achievements_page(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    page = _parse_int(parts, 2) or 0
    category: Optional[AchCategory] = None
    if len(parts) >= 4:
        try:
            category = AchCategory(parts[3])
        except ValueError:
            category = None
    full_name = escape_html(callback.from_user.full_name)
    await _send_achievement_page(
        callback.message, callback.from_user.id, full_name, page, category, edit=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crash_ach_cat_"))
async def cb_achievements_category(callback: types.CallbackQuery):
    raw = callback.data.removeprefix("crash_ach_cat_")
    category: Optional[AchCategory] = None
    if raw != "all":
        try:
            category = AchCategory(raw)
        except ValueError:
            category = None
    full_name = escape_html(callback.from_user.full_name)
    await _send_achievement_page(
        callback.message, callback.from_user.id, full_name, 0, category, edit=True,
    )
    await callback.answer()


@router.callback_query(F.data == "crash_ach_top")
async def cb_achievements_top(callback: types.CallbackQuery):
    try:
        await callback.message.answer(
            format_achievement_leaderboard(),
            reply_markup=get_close_keyboard(),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "crash_noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


# ───────────────── Other navigation handlers ─────────────────
@router.callback_query(F.data == "crash_history")
async def cb_history(callback: types.CallbackQuery):
    try:
        await callback.message.answer(format_history_card())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "crash_close")
async def cb_close(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


# ───────────────── Standalone slash commands ─────────────────
@router.message(Command("crash_stats"))
async def cmd_crash_stats(message: types.Message):
    full_name = escape_html(message.from_user.full_name)
    await message.answer(
        format_stats_card(message.from_user.id, full_name),
        reply_markup=get_stats_keyboard(),
    )


@router.message(Command("crash_history"))
async def cmd_crash_history(message: types.Message):
    await message.answer(format_history_card())


@router.message(Command("crash_achievements"))
async def cmd_crash_achievements(message: types.Message):
    full_name = escape_html(message.from_user.full_name)
    await _send_achievement_page(
        message, message.from_user.id, full_name, 0, None, edit=False,
    )


@router.message(Command("crash_ach_top"))
async def cmd_crash_ach_top(message: types.Message):
    await message.answer(
        format_achievement_leaderboard(),
        reply_markup=get_close_keyboard(),
    )


@router.message(Command("crash_top"))
async def cmd_crash_top(message: types.Message):
    players = stats_manager.all_players()
    if not players:
        return await message.answer("Топ пуст.")
    top = sorted(players, key=lambda s: s.profit, reverse=True)[:10]
    medals = ("🥇", "🥈", "🥉")
    lines = ["🏆 <b>Топ-10 пилотов · по чистой прибыли</b>", _SEP]
    for i, st in enumerate(top):
        medal = medals[i] if i < 3 else f"#{i + 1}"
        lines.append(
            f"{medal} ID <code>{st.user_id}</code> · "
            f"💰 {format_amount(st.profit)} · 🎯 {st.win_rate:.1f}%"
        )
    await message.answer("\n".join(lines))


@router.message(Command("crash_themes"))
async def cmd_crash_themes(message: types.Message):
    kb = InlineKeyboardBuilder()
    for theme in Theme:
        kb.add(types.InlineKeyboardButton(
            text=f"🎨 {theme.value.title()}",
            callback_data=f"crash_theme_pref_{theme.value}",
        ))
    kb.adjust(2)
    await message.answer(
        "🎨 <b>Выбери предпочитаемую тему оформления</b>:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("crash_theme_pref_"))
async def cb_theme_pref(callback: types.CallbackQuery):
    try:
        theme = Theme(callback.data.removeprefix("crash_theme_pref_"))
    except ValueError:
        return await callback.answer()
    st = stats_manager.get(callback.from_user.id)
    st.favorite_theme = theme.value
    if theme.value not in st.themes_used:
        st.themes_used.append(theme.value)
    stats_manager.mark_dirty()
    asyncio.create_task(stats_manager.flush())
    try:
        await callback.message.edit_text(f"✅ Тема сохранена: <b>{theme.value.title()}</b>")
    except Exception:
        pass
    await callback.answer("Сохранено.")


# ═════════════════════════════════════════════════════════════════════
#                              LIFECYCLE
# ═════════════════════════════════════════════════════════════════════
async def _periodic_flush():
    while True:
        await asyncio.sleep(60)
        try:
            await stats_manager.flush()
            await achievement_manager.flush()
        except Exception as exc:
            logger.debug("Periodic flush failed: %s", exc)


async def on_startup_crash() -> None:
    await achievement_manager.load()
    await stats_manager.load()
    await history_manager.load()
    asyncio.create_task(_periodic_flush())
    logger.info(
        "Crash module initialized. Stats: %d players, achievements: %d defs.",
        len(stats_manager._cache), len(ACHIEVEMENTS),
    )


async def on_shutdown_crash() -> None:
    try:
        await stats_manager.flush(force=True)
        await history_manager.flush()
        await achievement_manager.flush(force=True)
    except Exception as exc:
        logger.debug("Shutdown flush failed: %s", exc)
    try:
        _render_executor.shutdown(wait=False)
        _io_executor.shutdown(wait=False)
    except Exception:
        pass