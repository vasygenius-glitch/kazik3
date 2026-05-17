# crash.py — optimized
import asyncio
import io
import json
import logging
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from matplotlib.figure import Figure
from matplotlib.patches import Circle

from aiogram import F, Router, types
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


class CrashState(StatesGroup):
    playing = State()
    awaiting_auto = State()


# ───────────────────────── CONSTANTS ─────────────────────────
MIN_BET = 100
MAX_BET = 50_000_000
CREDIT_LIMIT = -5000
AUTO_DELETE_DELAY = 60
FRAME_DELAY = 0.85
MAX_FLIGHT_STEPS = 28
INSTANT_CRASH_CHANCE = 10
GROWTH_BASE = 0.046
GROWTH_EXP = 1.36
STATS_FILE = Path("data/crash_stats.json")
HISTORY_FILE = Path("data/crash_history.json")
STATS_FILE.parent.mkdir(parents=True, exist_ok=True)

_rng = secrets.SystemRandom()
_stats_lock = asyncio.Lock()
_history_lock = asyncio.Lock()
_active_games: dict[str, "GameSession"] = {}

# Один поток для рендера: matplotlib не thread-safe, плюс позволяет переиспользовать Figure
_render_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="crash-render")

# Предвычисленные мультипликаторы по шагам
_MULT_BY_STEP: tuple[float, ...] = tuple(
    round(1.00 + (s ** GROWTH_EXP) * GROWTH_BASE, 2) for s in range(MAX_FLIGHT_STEPS + 8)
)


class Theme(str, Enum):
    NEON = "neon"
    SUNSET = "sunset"
    MATRIX = "matrix"
    OCEAN = "ocean"
    INFERNO = "inferno"


THEMES: dict[Theme, dict[str, Any]] = {
    Theme.NEON: {"bg_top": "#0b0420", "bg_bot": "#1a0b3d", "grid": "#3d2a6b", "line": "#00fff7",
                 "line_glow": "#9d4dff", "fill_top": "#ff00d4", "fill_bot": "#00fff7",
                 "text": "#f0f0ff", "accent": "#ff2bd6", "crash": "#ff3355", "win": "#33ff99",
                 "rocket": "#ffdd33"},
    Theme.SUNSET: {"bg_top": "#1d0030", "bg_bot": "#ff5e3a", "grid": "#5a2a4d", "line": "#ffd166",
                   "line_glow": "#ff6b6b", "fill_top": "#ff006e", "fill_bot": "#ffbe0b",
                   "text": "#fff7e6", "accent": "#ff9e00", "crash": "#d00000", "win": "#90ee90",
                   "rocket": "#ffd700"},
    Theme.MATRIX: {"bg_top": "#000000", "bg_bot": "#001a00", "grid": "#003300", "line": "#00ff41",
                   "line_glow": "#39ff14", "fill_top": "#00ff41", "fill_bot": "#003b00",
                   "text": "#b6ffb6", "accent": "#00ff88", "crash": "#ff0040", "win": "#00ff41",
                   "rocket": "#80ff80"},
    Theme.OCEAN: {"bg_top": "#001f3f", "bg_bot": "#0074d9", "grid": "#0a3d62", "line": "#7fdbff",
                  "line_glow": "#39c0ed", "fill_top": "#01baef", "fill_bot": "#003b73",
                  "text": "#e8f6ff", "accent": "#48cae4", "crash": "#ff4d6d", "win": "#caffbf",
                  "rocket": "#ffdd00"},
    Theme.INFERNO: {"bg_top": "#1a0000", "bg_bot": "#5a0000", "grid": "#3d0a0a", "line": "#ff6b35",
                    "line_glow": "#ff4d00", "fill_top": "#ffba08", "fill_bot": "#d00000",
                    "text": "#ffe0b3", "accent": "#ff9500", "crash": "#ff0a54", "win": "#ffe066",
                    "rocket": "#ffe066"},
}

# Кэш cmap-ов и fill_top rgba (создаются один раз)
_THEME_CMAP: dict[Theme, LinearSegmentedColormap] = {
    t: LinearSegmentedColormap.from_list(f"bg_{t.value}", [p["bg_top"], p["bg_bot"]])
    for t, p in THEMES.items()
}
_THEME_FILL_RGBA: dict[Theme, tuple] = {
    t: to_rgba(p["fill_top"], alpha=0.18) for t, p in THEMES.items()
}
_GRADIENT_BUF = np.linspace(0, 1, 256).reshape(-1, 1)

PRESET_BETS = [100, 500, 1000, 5000, 10_000, 50_000, 100_000, 500_000]
AUTO_PRESETS = [1.5, 2.0, 3.0, 5.0, 10.0, 25.0]


# ───────────────────────── DATACLASSES ─────────────────────────
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
    streak_wins: int = 0
    streak_losses: int = 0
    current_streak: int = 0
    current_streak_type: str = "none"
    last_played: float = 0.0
    achievements: list[str] = field(default_factory=list)
    favorite_theme: str = Theme.NEON.value
    auto_default: Optional[float] = None

    @property
    def win_rate(self) -> float:
        return self.games_won / self.games_total * 100.0 if self.games_total else 0.0

    @property
    def profit(self) -> int:
        return self.total_won - self.total_bet

    @property
    def avg_bet(self) -> float:
        return self.total_bet / self.games_total if self.games_total else 0.0


ACHIEVEMENTS = {
    "first_flight": ("✈️ Первый полет", "Сыграть свою первую партию"),
    "first_win": ("🥇 Первая победа", "Обналичить хотя бы раз"),
    "high_roller": ("💎 Хайроллер", "Сделать ставку 1,000,000+"),
    "lucky_seven": ("7️⃣ Лаки-Севен", "Обналичить на коэф. 7.77x+"),
    "to_the_moon": ("🌙 На луну", "Обналичить на коэф. 25x+"),
    "diamond_hands": ("💎 Алмазные руки", "Обналичить на коэф. 50x+"),
    "godlike": ("👑 Богоподобный", "Обналичить на коэф. 100x"),
    "ironman": ("🦾 Железный", "Выиграть 10 раз подряд"),
    "phoenix": ("🔥 Феникс", "Проиграть 10 раз подряд"),
    "marathon": ("🏃 Марафонец", "Сыграть 100 партий"),
    "veteran": ("🎖️ Ветеран", "Сыграть 500 партий"),
    "millionaire": ("💰 Миллионер", "Выиграть 1,000,000+ за раз"),
    "speedrun": ("⚡ Спидранер", "Обналичить меньше чем за 2 секунды"),
    "patience": ("🧘 Терпеливый", "Обналичить после 15 секунд полета"),
}


# ───────────────────────── MANAGERS ─────────────────────────
class StatsManager:
    """Кэширует статистику; flush делается периодически, а не на каждой игре."""

    __slots__ = ("_cache", "_dirty")

    def __init__(self) -> None:
        self._cache: dict[int, PlayerStats] = {}
        self._dirty = False

    async def load(self) -> None:
        async with _stats_lock:
            if not STATS_FILE.exists():
                return
            try:
                raw = json.loads(STATS_FILE.read_text(encoding="utf-8"))
                for uid_str, payload in raw.items():
                    uid = int(uid_str)
                    payload.pop("user_id", None)
                    self._cache[uid] = PlayerStats(user_id=uid, **payload)
            except Exception as exc:
                logger.warning("Failed loading crash stats: %s", exc)

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

    def get(self, user_id: int) -> PlayerStats:
        st = self._cache.get(user_id)
        if st is None:
            st = PlayerStats(user_id=user_id)
            self._cache[user_id] = st
            self._dirty = True
        return st

    def _bump_win(self, st: PlayerStats, bet: int, win: int, multiplier: float) -> int:
        st.games_total += 1
        st.games_won += 1
        st.total_bet += bet
        st.total_won += win
        if multiplier > st.best_multiplier:
            st.best_multiplier = multiplier
        net = win - bet
        if net > st.best_win:
            st.best_win = net
        if st.current_streak_type == "win":
            st.current_streak += 1
        else:
            st.current_streak = 1
            st.current_streak_type = "win"
        if st.current_streak > st.streak_wins:
            st.streak_wins = st.current_streak
        st.last_played = time.time()
        return net

    def update_on_win(self, user_id: int, bet: int, win: int, multiplier: float, duration: float) -> list[str]:
        st = self.get(user_id)
        net = self._bump_win(st, bet, win, multiplier)
        unlocked = self._check_achievements(st, bet, multiplier, net, duration)
        self._dirty = True
        return unlocked

    def update_on_loss(self, user_id: int, bet: int) -> list[str]:
        st = self.get(user_id)
        st.games_total += 1
        st.games_lost += 1
        st.total_bet += bet
        st.total_lost += bet
        if bet > st.worst_loss:
            st.worst_loss = bet
        if st.current_streak_type == "loss":
            st.current_streak += 1
        else:
            st.current_streak = 1
            st.current_streak_type = "loss"
        if st.current_streak > st.streak_losses:
            st.streak_losses = st.current_streak
        st.last_played = time.time()
        unlocked = self._check_achievements(st, bet, 0, -bet, 0)
        self._dirty = True
        return unlocked

    @staticmethod
    def _check_achievements(st: PlayerStats, bet: int, multiplier: float,
                            win_net: int, duration: float) -> list[str]:
        ach = st.achievements
        ach_set = set(ach)
        unlocked: list[str] = []

        def grant(code: str) -> None:
            if code not in ach_set:
                ach_set.add(code)
                ach.append(code)
                unlocked.append(code)

        if st.games_total >= 1:
            grant("first_flight")
        if st.games_won >= 1:
            grant("first_win")
        if bet >= 1_000_000:
            grant("high_roller")
        if multiplier >= 7.77:
            grant("lucky_seven")
            if multiplier >= 25:
                grant("to_the_moon")
                if multiplier >= 50:
                    grant("diamond_hands")
                    if multiplier >= 100:
                        grant("godlike")
        if st.current_streak >= 10:
            if st.current_streak_type == "win":
                grant("ironman")
            elif st.current_streak_type == "loss":
                grant("phoenix")
        if st.games_total >= 100:
            grant("marathon")
            if st.games_total >= 500:
                grant("veteran")
        if win_net >= 1_000_000:
            grant("millionaire")
        if multiplier > 0 and 0 < duration < 2:
            grant("speedrun")
        if duration >= 15:
            grant("patience")
        return unlocked


class HistoryManager:
    __slots__ = ("capacity", "_items", "_badges_cache", "_last_cache")

    def __init__(self, capacity: int = 50) -> None:
        self.capacity = capacity
        self._items: list[dict[str, Any]] = []
        self._badges_cache: Optional[str] = None
        self._last_cache: Optional[list[float]] = None

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
        self._last_cache = None

    def last_n(self, n: int = 20) -> list[float]:
        return [it["mult"] for it in self._items[-n:]]

    def average(self) -> float:
        if not self._items:
            return 0.0
        return sum(it["mult"] for it in self._items) / len(self._items)

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


stats_manager = StatsManager()
history_manager = HistoryManager()


# ───────────────────────── HELPERS ─────────────────────────
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
    if step < len(_MULT_BY_STEP):
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
    if a >= 1_000_000:
        return f"{sign}{a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"{sign}{a / 1_000:.1f}K"
    return f"{sign}{a}"


def progress_bar(value: float, maximum: float, length: int = 14) -> str:
    if maximum <= 0:
        return "░" * length
    ratio = value / maximum
    if ratio < 0:
        ratio = 0
    elif ratio > 1:
        ratio = 1
    filled = int(ratio * length)
    return "█" * filled + "░" * (length - filled)


# ───────────────────────── RENDERER (reused Figure) ─────────────────────────
class ChartRenderer:
    """Один Figure переиспользуется между рендерами (single-thread executor)."""

    WIDTH = 10.0
    HEIGHT = 6.0
    DPI = 110  # был 120 — снижение DPI даёт ~30% ускорение без визуальной потери

    _fig: Optional[Figure] = None
    _canvas: Optional[FigureCanvasAgg] = None
    _ax = None

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
        # Один цикл вместо двух
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
            # Для in-flight кадров меньше точек интерполяции
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

        # Меньше слоёв glow для in-flight (2 вместо 4)
        glow_pairs = ((10, 0.16), (4, 0.5)) if fast else ((14, 0.08), (10, 0.16), (7, 0.28), (4, 0.55))
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
            if cashed_out:
                footer = f"Чистая прибыль: +{format_amount(win_amount - session.bet)} сыр."
            else:
                footer = f"Потеря: -{format_amount(session.bet)} сыр."
        else:
            footer = f"Ставка: {format_amount(session.bet)} · {session.full_name}"

        cls._draw_chrome(ax, palette, xmax, ymax, session.current_multiplier, status, footer)
        ax.set_xlim(0, xmax)
        ax.set_ylim(1.0, ymax)

        fig.patch.set_facecolor(palette["bg_top"])

        buf = io.BytesIO()
        # Без tight_layout каждый раз: ставим constrained-ish padding один раз через subplots_adjust
        fig.subplots_adjust(left=0.07, right=0.97, top=0.95, bottom=0.06)
        cls._canvas.draw()
        fig.savefig(buf, format="png", facecolor=palette["bg_top"], edgecolor="none")
        return buf.getvalue()


def _render_blocking(session: GameSession, status: str, crashed: bool,
                     cashed_out: bool, summary: bool, win_amount: int) -> bytes:
    return ChartRenderer.render(session, status, crashed, cashed_out, summary, win_amount)


async def render_chart(session: GameSession, status: str = "В ПОЛЕТЕ",
                       crashed: bool = False, cashed_out: bool = False) -> bytes:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_render_executor, _render_blocking,
                                      session, status, crashed, cashed_out, False, 0)


async def render_summary(session: GameSession, won: bool, win_amount: int) -> bytes:
    loop = asyncio.get_running_loop()
    status = "✅ ОБНАЛИЧЕНО" if won else "💥 КРАШ"
    return await loop.run_in_executor(_render_executor, _render_blocking,
                                      session, status, not won, won, True, win_amount)


# ───────────────────────── KEYBOARDS ─────────────────────────
def get_crash_keyboard(game_id: str, current_mult: float, auto: Optional[float]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text=f"💰 ОБНАЛИЧИТЬ × {current_mult:.2f}",
        callback_data=f"crash_cashout_{game_id}",
    ))
    if auto:
        builder.row(types.InlineKeyboardButton(
            text=f"🤖 Авто: {auto:.2f}x · отключить",
            callback_data=f"crash_auto_off_{game_id}",
        ))
    return builder.as_markup()


def get_pre_game_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🎨 Тема", callback_data=f"crash_theme_menu_{bet}"),
        types.InlineKeyboardButton(text="🤖 Авто-cashout", callback_data=f"crash_auto_menu_{bet}"),
    )
    builder.row(types.InlineKeyboardButton(text="🚀 ВЗЛЕТЕТЬ!", callback_data=f"cas_conf_crash_{bet}"))
    builder.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data="crash_cancel"))
    return builder.as_markup()


def get_replay_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text=f"🔁 Повтор ({format_amount(bet)})", callback_data=f"crash_replay_{bet}"),
        types.InlineKeyboardButton(text="× 2", callback_data=f"crash_replay_{bet * 2}"),
    )
    builder.row(
        types.InlineKeyboardButton(text="📊 Статистика", callback_data="crash_my_stats"),
        types.InlineKeyboardButton(text="📜 История", callback_data="crash_history"),
    )
    return builder.as_markup()


def get_theme_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for theme in Theme:
        builder.add(types.InlineKeyboardButton(
            text=f"🎨 {theme.value.title()}",
            callback_data=f"crash_theme_set_{theme.value}_{bet}",
        ))
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="↩️ Назад", callback_data=f"crash_back_{bet}"))
    return builder.as_markup()


def get_auto_keyboard(bet: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for preset in AUTO_PRESETS:
        builder.add(types.InlineKeyboardButton(
            text=f"× {preset:.1f}",
            callback_data=f"crash_auto_set_{preset}_{bet}",
        ))
    builder.adjust(3)
    builder.row(types.InlineKeyboardButton(text="🚫 Отключить", callback_data=f"crash_auto_set_0_{bet}"))
    builder.row(types.InlineKeyboardButton(text="↩️ Назад", callback_data=f"crash_back_{bet}"))
    return builder.as_markup()


def get_stats_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🏆 Достижения", callback_data="crash_achievements"),
        types.InlineKeyboardButton(text="📜 История", callback_data="crash_history"),
    )
    builder.row(types.InlineKeyboardButton(text="❌ Закрыть", callback_data="crash_close"))
    return builder.as_markup()


# ───────────────────────── TEXT FORMATTERS ─────────────────────────
_SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━"


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
    streak_emoji = "🔥" if st.current_streak_type == "win" else "🥶" if st.current_streak_type == "loss" else "⚪"
    return (
        f"📊 <b>Статистика КРАШ-АВИАТОРА</b>\n{_SEP}\n"
        f"👤 {full_name}\n"
        f"🎮 Всего полетов: <b>{st.games_total}</b>\n"
        f"✅ Выигрышей: <b>{st.games_won}</b> ({st.win_rate:.1f}%)\n"
        f"<code>{win_bar}</code>\n"
        f"❌ Поражений: <b>{st.games_lost}</b>\n{_SEP}\n"
        f"💰 Общий оборот: <b>{format_amount(st.total_bet)}</b>\n"
        f"{profit_color} Чистая прибыль: <b>{format_amount(st.profit)}</b>\n"
        f"📈 Средняя ставка: <b>{format_amount(int(st.avg_bet))}</b>\n{_SEP}\n"
        f"🏆 Лучший коэф.: <b>{st.best_multiplier:.2f}x</b>\n"
        f"💎 Лучший выигрыш: <b>+{format_amount(st.best_win)}</b>\n"
        f"💀 Худший проигрыш: <b>-{format_amount(st.worst_loss)}</b>\n{_SEP}\n"
        f"{streak_emoji} Текущий стрик: <b>{st.current_streak}</b> ({st.current_streak_type})\n"
        f"🔥 Макс. winstreak: <b>{st.streak_wins}</b>\n"
        f"🥶 Макс. losestreak: <b>{st.streak_losses}</b>\n{_SEP}\n"
        f"🏅 Достижения: <b>{len(st.achievements)}/{len(ACHIEVEMENTS)}</b>"
    )


def format_achievements_card(user_id: int, full_name: str) -> str:
    st = stats_manager.get(user_id)
    ach_set = set(st.achievements)
    lines = [f"🏅 <b>Достижения · {full_name}</b>", _SEP]
    for code, (title, desc) in ACHIEVEMENTS.items():
        mark = "✅" if code in ach_set else "🔒"
        lines.append(f"{mark} <b>{title}</b>\n   <i>{desc}</i>")
    lines.append(_SEP)
    lines.append(f"Открыто: <b>{len(st.achievements)}/{len(ACHIEVEMENTS)}</b>")
    return "\n".join(lines)


def format_history_card() -> str:
    items = history_manager.last_n(25)
    if not items:
        return "📜 История пуста."
    lines = ["📜 <b>История последних полетов</b>", _SEP]
    chunks = [(f"🟣{m:.2f}x" if m >= 10 else f"🟢{m:.2f}x" if m >= 2 else f"🔴{m:.2f}x") for m in items]
    for i in range(0, len(chunks), 5):
        lines.append("<code>" + "  ".join(chunks[i:i + 5]) + "</code>")
    lines.append(_SEP)
    lines.append(f"Среднее: <b>{history_manager.average():.2f}x</b>")
    return "\n".join(lines)


# ───────────────────────── EDIT HELPERS ─────────────────────────
async def safe_edit_message(message: types.Message, text: str, reply_markup=None) -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except Exception as exc:
        logger.debug("Crash edit failed: %s", exc)
        return False


async def safe_edit_media(message: types.Message, image: bytes, caption: str, reply_markup=None) -> bool:
    try:
        await message.edit_media(
            media=InputMediaPhoto(
                media=BufferedInputFile(image, filename="crash.png"),
                caption=caption,
            ),
            reply_markup=reply_markup,
        )
        return True
    except Exception as exc:
        logger.debug("Crash media edit failed: %s", exc)
        try:
            await message.edit_caption(caption=caption, reply_markup=reply_markup)
            return True
        except Exception as exc2:
            logger.debug("Crash caption edit failed: %s", exc2)
            return False


async def announce_achievements(message: types.Message, codes: list[str]) -> None:
    if not codes:
        return
    parts = [f"🏅 <b>{ACHIEVEMENTS[c][0]}</b> — <i>{ACHIEVEMENTS[c][1]}</i>"
             for c in codes if c in ACHIEVEMENTS]
    if not parts:
        return
    try:
        notice = await message.answer("✨ <b>Новые достижения!</b>\n" + "\n".join(parts))
        asyncio.create_task(schedule_delete(notice, AUTO_DELETE_DELAY))
    except Exception as exc:
        logger.debug("Achievement notify failed: %s", exc)


def _parse_int(parts: list[str], idx: int) -> Optional[int]:
    try:
        return int(parts[idx])
    except (ValueError, IndexError):
        return None


# ───────────────────────── HANDLERS ─────────────────────────
@router.message(Command("crash"))
async def cmd_crash(message: types.Message, state: FSMContext):
    if await state.get_state() == CrashState.playing.state:
        await state.clear()

    chat_id, user_id = message.chat.id, message.from_user.id
    full_name = escape_html(message.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get("is_banned"):
        return

    from diseases import get_active_diseases
    if "gonorrhea" in await get_active_diseases(chat_id, user_id):
        return await message.answer("🦠 <b>Гонорея</b>: Пилоты самолета отказываются сажать тебя на борт. Лечись!")

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
        return await message.answer(f"Ставка должна быть числом от {MIN_BET} до {MAX_BET:,} сыроежек.")

    if data.get("balance", 0) - bet < CREDIT_LIMIT:
        return await message.answer("Ваш кредитный лимит (-5000) исчерпан. Пополните баланс.")

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
    await safe_edit_message(callback.message,
                            format_pre_game(bet, theme, auto, full_name),
                            reply_markup=get_pre_game_keyboard(bet))
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
    await safe_edit_message(callback.message, "🎨 <b>Выбери визуальную тему</b>:",
                            reply_markup=get_theme_keyboard(bet))
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
    stats_manager._dirty = True
    await safe_edit_message(callback.message,
                            format_pre_game(bet, theme, st.auto_default, full_name),
                            reply_markup=get_pre_game_keyboard(bet))
    await callback.answer(f"Тема: {theme.value}")


@router.callback_query(F.data.startswith("crash_auto_menu_"))
async def cb_auto_menu(callback: types.CallbackQuery):
    bet = _parse_int(callback.data.split("_"), 3)
    if bet is None:
        return await callback.answer()
    await safe_edit_message(
        callback.message,
        "🤖 <b>Авто-cashout</b> — выбери множитель, на котором система автоматически обналичит ставку:",
        reply_markup=get_auto_keyboard(bet),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crash_auto_set_"))
async def cb_auto_set(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 5:
        return await callback.answer()
    try:
        value = float(parts[3])
        bet = int(parts[4])
    except (ValueError, IndexError):
        return await callback.answer()
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    st = stats_manager.get(user_id)
    st.auto_default = value if value > 1.0 else None
    stats_manager._dirty = True
    theme = pick_theme_for(user_id)
    await safe_edit_message(callback.message,
                            format_pre_game(bet, theme, st.auto_default, full_name),
                            reply_markup=get_pre_game_keyboard(bet))
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
    await safe_edit_message(callback.message,
                            format_pre_game(bet, theme, auto, full_name),
                            reply_markup=get_pre_game_keyboard(bet))
    await callback.answer()


@router.callback_query(F.data.startswith("cas_conf_crash_"))
async def process_crash_confirm(callback: types.CallbackQuery, state: FSMContext):
    bet = _parse_int(callback.data.split("_"), 3)
    if bet is None:
        return

    chat_id, user_id = callback.message.chat.id, callback.from_user.id
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


async def run_crash_loop(message: types.Message, state: FSMContext, game_id: str):
    try:
        session = _active_games.get(game_id)
        if session is None:
            return

        for step in range(1, MAX_FLIGHT_STEPS):
            # Объединяем оба await
            data = await state.get_data()
            if data.get("game_id") != game_id:
                break
            if (await state.get_state()) != CrashState.playing.state:
                break
            if session.cashed_out or session.cancelled:
                break

            current_mult = multiplier_at_step(step)
            crash_pt = session.crash_point

            if session.auto_cashout and current_mult >= session.auto_cashout and current_mult < crash_pt:
                session.current_multiplier = round(min(session.auto_cashout, current_mult), 2)
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

            # Параллельно: рендер + ожидание следующего тика
            render_task = asyncio.create_task(render_chart(session, status="🚀 В ПОЛЕТЕ"))
            try:
                image = await render_task
                await safe_edit_media(
                    message, image, format_inflight(session),
                    reply_markup=get_crash_keyboard(game_id, current_mult, session.auto_cashout),
                )
            except Exception as exc:
                logger.debug("Inflight update failed: %s", exc)

            await asyncio.sleep(FRAME_DELAY)

        if (await state.get_state()) == CrashState.playing.state and not session.cashed_out and not session.cancelled:
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
    unlocked = stats_manager.update_on_loss(session.user_id, session.bet)
    # I/O в фоне — не блокируем юзера
    asyncio.create_task(stats_manager.flush())
    asyncio.create_task(history_manager.flush())

    try:
        image = await render_summary(session, won=False, win_amount=0)
        await safe_edit_media(message, image, format_crash(session),
                              reply_markup=get_replay_keyboard(session.bet))
    except Exception as exc:
        logger.debug("Crash summary edit failed: %s", exc)

    asyncio.create_task(schedule_delete(message, AUTO_DELETE_DELAY))
    await announce_achievements(message, unlocked)


async def cashout_session(message: types.Message, state: FSMContext, session: GameSession,
                          auto: bool = False, forced: bool = False):
    if session.cashed_out:
        return
    session.cashed_out = True
    session.finished = True
    session.cashout_at = session.current_multiplier
    await state.clear()

    win_amount = int(session.bet * session.current_multiplier)
    await update_user_balance(session.chat_id, session.user_id, win_amount, action="Crash Cashout")
    invalidate_user_cache(session.chat_id, session.user_id)
    history_manager.add(session.current_multiplier)
    unlocked = stats_manager.update_on_win(
        session.user_id, session.bet, win_amount, session.current_multiplier, session.duration,
    )
    asyncio.create_task(stats_manager.flush())
    asyncio.create_task(history_manager.flush())

    try:
        image = await render_summary(session, won=True, win_amount=win_amount)
        caption = format_cashout(session, win_amount)
        if auto:
            caption = ("🛬 ФОРСИРОВАННЫЙ CASHOUT" if forced else "🛬 АВТО-CASHOUT") + "\n\n" + caption
        await safe_edit_media(message, image, caption,
                              reply_markup=get_replay_keyboard(session.bet))
    except Exception as exc:
        logger.debug("Cashout summary edit failed: %s", exc)

    asyncio.create_task(schedule_delete(message, AUTO_DELETE_DELAY))
    await announce_achievements(message, unlocked)


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


@router.callback_query(F.data == "crash_achievements")
async def cb_achievements(callback: types.CallbackQuery):
    full_name = escape_html(callback.from_user.full_name)
    try:
        await callback.message.answer(format_achievements_card(callback.from_user.id, full_name))
    except Exception:
        pass
    await callback.answer()


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
    await message.answer(format_achievements_card(message.from_user.id, full_name))


@router.message(Command("crash_top"))
async def cmd_crash_top(message: types.Message):
    top = sorted(stats_manager._cache.values(), key=lambda s: s.profit, reverse=True)[:10]
    if not top:
        return await message.answer("Топ пуст.")
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
    await message.answer("🎨 <b>Выбери предпочитаемую тему оформления</b>:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("crash_theme_pref_"))
async def cb_theme_pref(callback: types.CallbackQuery):
    try:
        theme = Theme(callback.data.removeprefix("crash_theme_pref_"))
    except ValueError:
        return await callback.answer()
    st = stats_manager.get(callback.from_user.id)
    st.favorite_theme = theme.value
    stats_manager._dirty = True
    asyncio.create_task(stats_manager.flush())
    try:
        await callback.message.edit_text(f"✅ Тема сохранена: <b>{theme.value.title()}</b>")
    except Exception:
        pass
    await callback.answer("Сохранено.")


# ───────────────────────── LIFECYCLE ─────────────────────────
async def _periodic_flush():
    while True:
        await asyncio.sleep(60)
        try:
            await stats_manager.flush()
        except Exception as exc:
            logger.debug("Periodic flush failed: %s", exc)


async def on_startup_crash() -> None:
    await stats_manager.load()
    await history_manager.load()
    asyncio.create_task(_periodic_flush())
    logger.info("Crash module initialized. Stats loaded for %d players.", len(stats_manager._cache))