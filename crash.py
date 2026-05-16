import asyncio
import io
import json
import math
import os
import secrets
import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, Circle, FancyArrowPatch
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, to_rgba
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InputMediaPhoto

from user_manager import get_user_data, update_user_balance, invalidate_user_cache
from escape import escape_html
from utils import schedule_delete

logger = logging.getLogger(__name__)
router = Router()


class CrashState(StatesGroup):
    playing = State()
    awaiting_auto = State()


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


class Theme(str, Enum):
    NEON = "neon"
    SUNSET = "sunset"
    MATRIX = "matrix"
    OCEAN = "ocean"
    INFERNO = "inferno"


THEMES: dict[Theme, dict[str, Any]] = {
    Theme.NEON: {
        "bg_top": "#0b0420",
        "bg_bot": "#1a0b3d",
        "grid": "#3d2a6b",
        "line": "#00fff7",
        "line_glow": "#9d4dff",
        "fill_top": "#ff00d4",
        "fill_bot": "#00fff7",
        "text": "#f0f0ff",
        "accent": "#ff2bd6",
        "crash": "#ff3355",
        "win": "#33ff99",
        "rocket": "#ffdd33",
    },
    Theme.SUNSET: {
        "bg_top": "#1d0030",
        "bg_bot": "#ff5e3a",
        "grid": "#5a2a4d",
        "line": "#ffd166",
        "line_glow": "#ff6b6b",
        "fill_top": "#ff006e",
        "fill_bot": "#ffbe0b",
        "text": "#fff7e6",
        "accent": "#ff9e00",
        "crash": "#d00000",
        "win": "#90ee90",
        "rocket": "#ffd700",
    },
    Theme.MATRIX: {
        "bg_top": "#000000",
        "bg_bot": "#001a00",
        "grid": "#003300",
        "line": "#00ff41",
        "line_glow": "#39ff14",
        "fill_top": "#00ff41",
        "fill_bot": "#003b00",
        "text": "#b6ffb6",
        "accent": "#00ff88",
        "crash": "#ff0040",
        "win": "#00ff41",
        "rocket": "#80ff80",
    },
    Theme.OCEAN: {
        "bg_top": "#001f3f",
        "bg_bot": "#0074d9",
        "grid": "#0a3d62",
        "line": "#7fdbff",
        "line_glow": "#39c0ed",
        "fill_top": "#01baef",
        "fill_bot": "#003b73",
        "text": "#e8f6ff",
        "accent": "#48cae4",
        "crash": "#ff4d6d",
        "win": "#caffbf",
        "rocket": "#ffdd00",
    },
    Theme.INFERNO: {
        "bg_top": "#1a0000",
        "bg_bot": "#5a0000",
        "grid": "#3d0a0a",
        "line": "#ff6b35",
        "line_glow": "#ff4d00",
        "fill_top": "#ffba08",
        "fill_bot": "#d00000",
        "text": "#ffe0b3",
        "accent": "#ff9500",
        "crash": "#ff0a54",
        "win": "#ffe066",
        "rocket": "#ffe066",
    },
}


PRESET_BETS = [100, 500, 1000, 5000, 10_000, 50_000, 100_000, 500_000]
AUTO_PRESETS = [1.5, 2.0, 3.0, 5.0, 10.0, 25.0]


@dataclass
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


@dataclass
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
        if self.games_total == 0:
            return 0.0
        return self.games_won / self.games_total * 100.0

    @property
    def profit(self) -> int:
        return self.total_won - self.total_bet

    @property
    def avg_bet(self) -> float:
        if self.games_total == 0:
            return 0.0
        return self.total_bet / self.games_total


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


class StatsManager:
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
                    self._cache[uid] = PlayerStats(user_id=uid, **{
                        k: v for k, v in payload.items() if k != "user_id"
                    })
            except Exception as exc:
                logger.warning("Failed loading crash stats: %s", exc)

    async def flush(self) -> None:
        async with _stats_lock:
            if not self._dirty:
                return
            payload = {
                str(uid): asdict(st) for uid, st in self._cache.items()
            }
            try:
                STATS_FILE.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self._dirty = False
            except Exception as exc:
                logger.warning("Failed saving crash stats: %s", exc)

    def get(self, user_id: int) -> PlayerStats:
        if user_id not in self._cache:
            self._cache[user_id] = PlayerStats(user_id=user_id)
            self._dirty = True
        return self._cache[user_id]

    def update_on_win(self, user_id: int, bet: int, win: int, multiplier: float, duration: float) -> list[str]:
        st = self.get(user_id)
        st.games_total += 1
        st.games_won += 1
        st.total_bet += bet
        st.total_won += win
        st.best_multiplier = max(st.best_multiplier, multiplier)
        net = win - bet
        st.best_win = max(st.best_win, net)
        if st.current_streak_type == "win":
            st.current_streak += 1
        else:
            st.current_streak = 1
            st.current_streak_type = "win"
        st.streak_wins = max(st.streak_wins, st.current_streak)
        st.last_played = time.time()
        unlocked = self._check_achievements(st, bet=bet, multiplier=multiplier, win_net=net, duration=duration)
        self._dirty = True
        return unlocked

    def update_on_loss(self, user_id: int, bet: int) -> list[str]:
        st = self.get(user_id)
        st.games_total += 1
        st.games_lost += 1
        st.total_bet += bet
        st.total_lost += bet
        st.worst_loss = max(st.worst_loss, bet)
        if st.current_streak_type == "loss":
            st.current_streak += 1
        else:
            st.current_streak = 1
            st.current_streak_type = "loss"
        st.streak_losses = max(st.streak_losses, st.current_streak)
        st.last_played = time.time()
        unlocked = self._check_achievements(st, bet=bet, multiplier=0, win_net=-bet, duration=0)
        self._dirty = True
        return unlocked

    def _check_achievements(
        self,
        st: PlayerStats,
        bet: int,
        multiplier: float,
        win_net: int,
        duration: float,
    ) -> list[str]:
        unlocked: list[str] = []

        def grant(code: str) -> None:
            if code not in st.achievements:
                st.achievements.append(code)
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
        if st.current_streak_type == "win" and st.current_streak >= 10:
            grant("ironman")
        if st.current_streak_type == "loss" and st.current_streak >= 10:
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
    def __init__(self, capacity: int = 50) -> None:
        self.capacity = capacity
        self._items: list[dict[str, Any]] = []

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
            try:
                HISTORY_FILE.write_text(
                    json.dumps(self._items[-self.capacity:], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.warning("Failed saving crash history: %s", exc)

    def add(self, multiplier: float) -> None:
        self._items.append({
            "mult": round(multiplier, 2),
            "ts": time.time(),
        })
        if len(self._items) > self.capacity:
            self._items = self._items[-self.capacity:]

    def last_n(self, n: int = 20) -> list[float]:
        return [item["mult"] for item in self._items[-n:]]

    def average(self) -> float:
        if not self._items:
            return 0.0
        return sum(it["mult"] for it in self._items) / len(self._items)


stats_manager = StatsManager()
history_manager = HistoryManager()


def generate_crash_point() -> float:
    if _rng.randint(1, 100) <= INSTANT_CRASH_CHANCE:
        return 1.00
    u = _rng.random()
    if u < 0.5:
        return round(_rng.uniform(1.01, 2.00), 2)
    elif u < 0.8:
        return round(_rng.uniform(2.00, 5.00), 2)
    elif u < 0.95:
        return round(_rng.uniform(5.00, 15.00), 2)
    else:
        return round(_rng.uniform(15.00, 100.00), 2)


def multiplier_at_step(step: int) -> float:
    return round(1.00 + (step ** GROWTH_EXP) * GROWTH_BASE, 2)


def pick_theme_for(user_id: int) -> Theme:
    st = stats_manager.get(user_id)
    try:
        return Theme(st.favorite_theme)
    except ValueError:
        return Theme.NEON


def color_for_mult(mult: float, palette: dict[str, Any]) -> str:
    if mult >= 50:
        return "#ffd700"
    if mult >= 10:
        return palette["accent"]
    if mult >= 5:
        return palette["line"]
    if mult >= 2:
        return palette["line_glow"]
    return palette["fill_bot"]


def format_amount(amount: int) -> str:
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1_000_000:
        return f"{sign}{amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{sign}{amount / 1_000:.1f}K"
    return f"{sign}{amount}"


class ChartRenderer:
    WIDTH = 10.0
    HEIGHT = 6.0
    DPI = 120

    def __init__(self, theme: Theme = Theme.NEON) -> None:
        self.theme = theme
        self.palette = THEMES[theme]

    def _make_figure(self) -> tuple[plt.Figure, plt.Axes]:
        fig, ax = plt.subplots(figsize=(self.WIDTH, self.HEIGHT), dpi=self.DPI)
        fig.patch.set_facecolor(self.palette["bg_top"])
        ax.set_facecolor(self.palette["bg_bot"])
        return fig, ax

    def _gradient_background(self, ax: plt.Axes, xmax: float, ymax: float) -> None:
        cmap = LinearSegmentedColormap.from_list(
            "bg",
            [self.palette["bg_top"], self.palette["bg_bot"]],
        )
        gradient = np.linspace(0, 1, 256).reshape(-1, 1)
        ax.imshow(
            gradient,
            aspect="auto",
            cmap=cmap,
            extent=[0, xmax, 1.0, ymax],
            origin="lower",
            zorder=0,
            alpha=0.95,
        )

    def _draw_grid(self, ax: plt.Axes, xmax: float, ymax: float) -> None:
        grid_color = self.palette["grid"]
        for i in range(1, 7):
            y = 1.0 + (ymax - 1.0) * i / 7
            ax.axhline(y=y, color=grid_color, linestyle="--", linewidth=0.6, alpha=0.45, zorder=1)
        for i in range(1, 7):
            x = xmax * i / 7
            ax.axvline(x=x, color=grid_color, linestyle="--", linewidth=0.6, alpha=0.3, zorder=1)

    def _draw_trajectory(
        self,
        ax: plt.Axes,
        path: list[float],
        crashed: bool,
        cashed_out: bool,
    ) -> tuple[float, float]:
        if len(path) < 2:
            xs = np.array([0.0, 0.01])
            ys = np.array([1.0, 1.0])
        else:
            xs = np.linspace(0, len(path) - 1, num=max(150, len(path) * 8))
            ys = np.interp(xs, np.arange(len(path)), path)

        points = np.array([xs, ys]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)

        glow_color = self.palette["line_glow"]
        line_color = self.palette["line"]
        if crashed:
            line_color = self.palette["crash"]
            glow_color = "#ff0033"
        elif cashed_out:
            line_color = self.palette["win"]
            glow_color = "#33ff66"

        for width, alpha in [(14, 0.08), (10, 0.16), (7, 0.28), (4, 0.55)]:
            lc = LineCollection(
                segments,
                colors=glow_color,
                linewidth=width,
                alpha=alpha,
                zorder=2,
            )
            ax.add_collection(lc)

        lc_main = LineCollection(
            segments,
            colors=line_color,
            linewidth=2.4,
            zorder=4,
        )
        ax.add_collection(lc_main)

        fill_color = to_rgba(self.palette["fill_top"], alpha=0.18)
        ax.fill_between(xs, 1.0, ys, color=fill_color, zorder=1)

        return xs[-1], ys[-1]

    def _draw_rocket(
        self,
        ax: plt.Axes,
        x: float,
        y: float,
        crashed: bool,
        cashed_out: bool,
    ) -> None:
        if crashed:
            for radius, alpha in [(0.5, 0.7), (0.35, 0.85), (0.2, 1.0)]:
                circ = Circle(
                    (x, y),
                    radius=radius,
                    color=self.palette["crash"],
                    alpha=alpha,
                    zorder=6,
                )
                ax.add_patch(circ)
            ax.text(
                x,
                y,
                "💥",
                fontsize=28,
                ha="center",
                va="center",
                zorder=7,
            )
        else:
            color = self.palette["win"] if cashed_out else self.palette["rocket"]
            for radius, alpha in [(0.32, 0.35), (0.22, 0.55), (0.13, 0.85)]:
                circ = Circle(
                    (x, y),
                    radius=radius,
                    color=color,
                    alpha=alpha,
                    zorder=5,
                )
                ax.add_patch(circ)
            symbol = "💰" if cashed_out else "🚀"
            ax.text(
                x,
                y,
                symbol,
                fontsize=22,
                ha="center",
                va="center",
                zorder=8,
            )

    def _draw_axes_labels(self, ax: plt.Axes, xmax: float, ymax: float) -> None:
        text_color = self.palette["text"]
        ax.tick_params(colors=text_color, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(self.palette["grid"])
            spine.set_linewidth(1.2)

        yticks = []
        for i in range(0, 6):
            yticks.append(round(1.0 + (ymax - 1.0) * i / 5, 2))
        ax.set_yticks(yticks)
        ax.set_yticklabels([f"{v:.2f}x" for v in yticks])
        ax.set_xticks([])

    def _draw_watermark(self, ax: plt.Axes, xmax: float, ymax: float, mult: float) -> None:
        ax.text(
            xmax / 2,
            (1.0 + ymax) / 2,
            f"{mult:.2f}x",
            fontsize=72,
            color=self.palette["text"],
            alpha=0.07,
            ha="center",
            va="center",
            fontweight="bold",
            zorder=2,
        )

    def _draw_header(self, ax: plt.Axes, mult: float, status: str) -> None:
        ax.text(
            0.02,
            0.95,
            f"{mult:.2f}x",
            transform=ax.transAxes,
            fontsize=36,
            color=self.palette["text"],
            fontweight="bold",
            ha="left",
            va="top",
            zorder=10,
        )
        ax.text(
            0.02,
            0.83,
            status,
            transform=ax.transAxes,
            fontsize=14,
            color=self.palette["accent"],
            ha="left",
            va="top",
            zorder=10,
        )

    def _draw_footer(self, ax: plt.Axes, info: str) -> None:
        ax.text(
            0.98,
            0.04,
            info,
            transform=ax.transAxes,
            fontsize=10,
            color=self.palette["text"],
            alpha=0.7,
            ha="right",
            va="bottom",
            zorder=10,
        )

    def render(
        self,
        session: GameSession,
        status: str = "В ПОЛЕТЕ",
        crashed: bool = False,
        cashed_out: bool = False,
    ) -> bytes:
        path = session.path_points or [1.00]
        peak = max(path) if path else 1.0
        ymax = max(peak * 1.18, 1.2)
        xmax = max(len(path) - 1, 1) * 1.05

        fig, ax = self._make_figure()
        self._gradient_background(ax, xmax, ymax)
        self._draw_grid(ax, xmax, ymax)
        self._draw_watermark(ax, xmax, ymax, session.current_multiplier)
        x_end, y_end = self._draw_trajectory(ax, path, crashed, cashed_out)
        self._draw_rocket(ax, x_end, y_end, crashed, cashed_out)
        self._draw_axes_labels(ax, xmax, ymax)
        self._draw_header(ax, session.current_multiplier, status)
        self._draw_footer(
            ax,
            f"Ставка: {format_amount(session.bet)} · {session.full_name}",
        )

        ax.set_xlim(0, xmax)
        ax.set_ylim(1.0, ymax)

        buf = io.BytesIO()
        fig.tight_layout(pad=0.5)
        fig.savefig(
            buf,
            format="png",
            facecolor=fig.get_facecolor(),
            edgecolor="none",
            bbox_inches="tight",
        )
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    def render_summary(
        self,
        session: GameSession,
        won: bool,
        win_amount: int,
    ) -> bytes:
        path = session.path_points or [1.00]
        peak = max(path) if path else 1.0
        ymax = max(peak * 1.2, 1.2)
        xmax = max(len(path) - 1, 1) * 1.05

        fig, ax = self._make_figure()
        self._gradient_background(ax, xmax, ymax)
        self._draw_grid(ax, xmax, ymax)
        self._draw_watermark(ax, xmax, ymax, session.current_multiplier)
        x_end, y_end = self._draw_trajectory(ax, path, crashed=not won, cashed_out=won)
        self._draw_rocket(ax, x_end, y_end, crashed=not won, cashed_out=won)
        self._draw_axes_labels(ax, xmax, ymax)

        status = "✅ ОБНАЛИЧЕНО" if won else "💥 КРАШ"
        self._draw_header(ax, session.current_multiplier, status)

        if won:
            footer = f"Чистая прибыль: +{format_amount(win_amount - session.bet)} сыр."
        else:
            footer = f"Потеря: -{format_amount(session.bet)} сыр."
        self._draw_footer(ax, footer)

        ax.set_xlim(0, xmax)
        ax.set_ylim(1.0, ymax)

        buf = io.BytesIO()
        fig.tight_layout(pad=0.5)
        fig.savefig(
            buf,
            format="png",
            facecolor=fig.get_facecolor(),
            edgecolor="none",
            bbox_inches="tight",
        )
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()


def render_chart_blocking(session: GameSession, status: str, crashed: bool, cashed_out: bool) -> bytes:
    renderer = ChartRenderer(session.theme)
    return renderer.render(session, status=status, crashed=crashed, cashed_out=cashed_out)


def render_summary_blocking(session: GameSession, won: bool, win_amount: int) -> bytes:
    renderer = ChartRenderer(session.theme)
    return renderer.render_summary(session, won=won, win_amount=win_amount)


async def render_chart(session: GameSession, status: str = "В ПОЛЕТЕ", crashed: bool = False, cashed_out: bool = False) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, render_chart_blocking, session, status, crashed, cashed_out)


async def render_summary(session: GameSession, won: bool, win_amount: int) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, render_summary_blocking, session, won, win_amount)


def draw_ascii_chart(path_points: list[float]) -> str:
    rows = 6
    cols = 22
    grid = [[" " for _ in range(cols)] for _ in range(rows)]
    n_points = len(path_points)
    if n_points > 0:
        max_val = max(path_points) if max(path_points) > 1.0 else 2.0
        min_val = 1.0
        val_range = max_val - min_val if max_val > min_val else 1.0
        for col_idx in range(min(n_points, cols)):
            val = path_points[col_idx]
            norm = (val - min_val) / val_range
            row_idx = int((rows - 1) - (norm * (rows - 1)))
            row_idx = max(0, min(rows - 1, row_idx))
            if col_idx == n_points - 1:
                grid[row_idx][col_idx] = "🚀"
            else:
                grid[row_idx][col_idx] = "•"
    lines = []
    max_val = max(path_points) if path_points else 1.0
    for r in range(rows):
        val_at_row = 1.0 + ((rows - 1 - r) / (rows - 1)) * (max_val - 1.0)
        label = f"{val_at_row:.2f}x"
        row_str = "".join(grid[r])
        lines.append(f"{label:<7} │ {row_str}")
    lines.append("        └" + "─" * cols)
    return "\n".join(lines)


def history_badges() -> str:
    last = history_manager.last_n(15)
    if not last:
        return "—"
    badges = []
    for m in last:
        if m >= 10:
            badges.append(f"🟣{m:.2f}x")
        elif m >= 2:
            badges.append(f"🟢{m:.2f}x")
        else:
            badges.append(f"🔴{m:.2f}x")
    return " ".join(badges)


def progress_bar(value: float, maximum: float, length: int = 14) -> str:
    if maximum <= 0:
        return "░" * length
    ratio = max(0.0, min(1.0, value / maximum))
    filled = int(ratio * length)
    return "█" * filled + "░" * (length - filled)


def get_crash_keyboard(game_id: str, current_mult: float, auto: Optional[float]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    potential = int(current_mult * 100)
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


def format_pre_game(bet: int, theme: Theme, auto: Optional[float], full_name: str) -> str:
    auto_text = f"<b>× {auto:.2f}</b>" if auto else "<i>выключен</i>"
    badges = history_badges()
    avg = history_manager.average()
    return (
        f"✈️ <b>КРАШ-АВИАТОР · Подготовка к полету</b> ✈️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Пилот: <b>{full_name}</b>\n"
        f"💰 Ставка: <b>{format_amount(bet)}</b> сыр.\n"
        f"🎨 Тема: <b>{theme.value.title()}</b>\n"
        f"🤖 Авто-cashout: {auto_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Среднее за сессию: <b>{avg:.2f}x</b>\n"
        f"🕘 Последние полеты:\n<code>{badges}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Готов? Нажми <b>🚀 ВЗЛЕТЕТЬ!</b>"
    )


def format_inflight(session: GameSession) -> str:
    return (
        f"🚀 <b>В ПОЛЕТЕ · {session.current_multiplier:.2f}x</b>\n"
        f"👤 {session.full_name}\n"
        f"💰 Ставка: <b>{format_amount(session.bet)}</b> сыр.\n"
        f"📈 Потенциал: <b>{format_amount(int(session.bet * session.current_multiplier))}</b>\n"
        f"⏱ Время: <b>{session.duration:.1f}с</b>\n"
        f"🎯 Авто: " + (f"<b>×{session.auto_cashout:.2f}</b>" if session.auto_cashout else "<i>—</i>") + "\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👉 Жми ОБНАЛИЧИТЬ пока не поздно!"
    )


def format_crash(session: GameSession) -> str:
    return (
        f"💥 <b>КРАШ · {session.crash_point:.2f}x</b>\n"
        f"👤 {session.full_name}\n"
        f"💸 Потеряно: <b>-{format_amount(session.bet)}</b> сыр.\n"
        f"⏱ Длительность: <b>{session.duration:.1f}с</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕘 Последние полеты:\n<code>{history_badges()}</code>"
    )


def format_cashout(session: GameSession, win_amount: int) -> str:
    net = win_amount - session.bet
    return (
        f"🎉 <b>ОБНАЛИЧЕНО · {session.current_multiplier:.2f}x</b>\n"
        f"👤 {session.full_name}\n"
        f"💰 Ставка: <b>{format_amount(session.bet)}</b> сыр.\n"
        f"✨ Чистая прибыль: <b>+{format_amount(net)}</b> сыр.\n"
        f"💎 Всего получено: <b>{format_amount(win_amount)}</b> сыр.\n"
        f"⏱ Время полета: <b>{session.duration:.1f}с</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕘 Последние полеты:\n<code>{history_badges()}</code>"
    )


def format_stats_card(user_id: int, full_name: str) -> str:
    st = stats_manager.get(user_id)
    win_bar = progress_bar(st.win_rate, 100)
    profit_color = "🟢" if st.profit >= 0 else "🔴"
    streak_emoji = "🔥" if st.current_streak_type == "win" else "🥶" if st.current_streak_type == "loss" else "⚪"
    achievements_count = len(st.achievements)
    achievements_total = len(ACHIEVEMENTS)
    return (
        f"📊 <b>Статистика КРАШ-АВИАТОРА</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 {full_name}\n"
        f"🎮 Всего полетов: <b>{st.games_total}</b>\n"
        f"✅ Выигрышей: <b>{st.games_won}</b> ({st.win_rate:.1f}%)\n"
        f"<code>{win_bar}</code>\n"
        f"❌ Поражений: <b>{st.games_lost}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Общий оборот: <b>{format_amount(st.total_bet)}</b>\n"
        f"{profit_color} Чистая прибыль: <b>{format_amount(st.profit)}</b>\n"
        f"📈 Средняя ставка: <b>{format_amount(int(st.avg_bet))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Лучший коэф.: <b>{st.best_multiplier:.2f}x</b>\n"
        f"💎 Лучший выигрыш: <b>+{format_amount(st.best_win)}</b>\n"
        f"💀 Худший проигрыш: <b>-{format_amount(st.worst_loss)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{streak_emoji} Текущий стрик: <b>{st.current_streak}</b> ({st.current_streak_type})\n"
        f"🔥 Макс. winstreak: <b>{st.streak_wins}</b>\n"
        f"🥶 Макс. losestreak: <b>{st.streak_losses}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏅 Достижения: <b>{achievements_count}/{achievements_total}</b>"
    )


def format_achievements_card(user_id: int, full_name: str) -> str:
    st = stats_manager.get(user_id)
    lines = [f"🏅 <b>Достижения · {full_name}</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for code, (title, desc) in ACHIEVEMENTS.items():
        mark = "✅" if code in st.achievements else "🔒"
        lines.append(f"{mark} <b>{title}</b>\n   <i>{desc}</i>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Открыто: <b>{len(st.achievements)}/{len(ACHIEVEMENTS)}</b>")
    return "\n".join(lines)


def format_history_card() -> str:
    items = history_manager.last_n(25)
    if not items:
        return "📜 История пуста."
    lines = ["📜 <b>История последних полетов</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━"]
    chunks: list[str] = []
    for m in items:
        if m >= 10:
            chunks.append(f"🟣{m:.2f}x")
        elif m >= 2:
            chunks.append(f"🟢{m:.2f}x")
        else:
            chunks.append(f"🔴{m:.2f}x")
    for i in range(0, len(chunks), 5):
        lines.append("<code>" + "  ".join(chunks[i:i + 5]) + "</code>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Среднее: <b>{history_manager.average():.2f}x</b>")
    return "\n".join(lines)


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
    parts = []
    for code in codes:
        if code in ACHIEVEMENTS:
            title, desc = ACHIEVEMENTS[code]
            parts.append(f"🏅 <b>{title}</b> — <i>{desc}</i>")
    if not parts:
        return
    text = "✨ <b>Новые достижения!</b>\n" + "\n".join(parts)
    try:
        notice = await message.answer(text)
        asyncio.create_task(schedule_delete(notice, AUTO_DELETE_DELAY))
    except Exception as exc:
        logger.debug("Achievement notify failed: %s", exc)


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
        keyboard_builder = InlineKeyboardBuilder()
        for preset in PRESET_BETS:
            keyboard_builder.add(types.InlineKeyboardButton(
                text=f"💵 {format_amount(preset)}",
                callback_data=f"crash_preset_{preset}",
            ))
        keyboard_builder.adjust(2)
        return await message.answer(
            "💡 <b>Укажи ставку</b>: <code>/crash 1000</code>\n"
            "Или выбери из пресетов ниже:",
            reply_markup=keyboard_builder.as_markup(),
        )

    try:
        bet = int(args[1])
        if bet < MIN_BET or bet > MAX_BET:
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
    try:
        bet = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
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
    try:
        bet = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        return await callback.answer()
    await safe_edit_message(
        callback.message,
        "🎨 <b>Выбери визуальную тему</b>:",
        reply_markup=get_theme_keyboard(bet),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crash_theme_set_"))
async def cb_theme_set(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 5:
        return await callback.answer()
    theme_value = parts[3]
    try:
        bet = int(parts[4])
        theme = Theme(theme_value)
    except (ValueError, IndexError):
        return await callback.answer()
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    st = stats_manager.get(user_id)
    st.favorite_theme = theme.value
    stats_manager._dirty = True
    auto = st.auto_default
    await safe_edit_message(
        callback.message,
        format_pre_game(bet, theme, auto, full_name),
        reply_markup=get_pre_game_keyboard(bet),
    )
    await callback.answer(f"Тема: {theme.value}")


@router.callback_query(F.data.startswith("crash_auto_menu_"))
async def cb_auto_menu(callback: types.CallbackQuery):
    try:
        bet = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
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
    await safe_edit_message(
        callback.message,
        format_pre_game(bet, theme, st.auto_default, full_name),
        reply_markup=get_pre_game_keyboard(bet),
    )
    await callback.answer("Сохранено.")


@router.callback_query(F.data.startswith("crash_back_"))
async def cb_back(callback: types.CallbackQuery):
    try:
        bet = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
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
    try:
        bet = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        return

    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)

    new_balance = await update_user_balance(
        chat_id,
        user_id,
        -bet,
        min_balance=CREDIT_LIMIT,
        action="Crash Bet",
    )
    if new_balance is None:
        return await callback.answer("Недостаточно средств!", show_alert=True)

    try:
        await callback.message.delete()
    except Exception:
        pass

    theme = pick_theme_for(user_id)
    auto = stats_manager.get(user_id).auto_default
    crash_point = generate_crash_point()
    game_id = f"{chat_id}_{user_id}_{int(time.time() * 1000)}"

    session = GameSession(
        game_id=game_id,
        chat_id=chat_id,
        user_id=user_id,
        full_name=full_name,
        bet=bet,
        crash_point=crash_point,
        theme=theme,
        auto_cashout=auto,
    )
    _active_games[game_id] = session

    await state.set_state(CrashState.playing)
    await state.update_data(game_id=game_id)

    image = await render_chart(session, status="🛫 ВЗЛЕТ", crashed=False, cashed_out=False)
    caption = format_inflight(session)
    keyboard = get_crash_keyboard(game_id, 1.00, auto)

    try:
        msg = await callback.message.answer_photo(
            photo=BufferedInputFile(image, filename="crash.png"),
            caption=caption,
            reply_markup=keyboard,
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
            st = await state.get_state()
            if st != CrashState.playing.state:
                break

            data = await state.get_data()
            if data.get("game_id") != game_id:
                break
            if session.cashed_out or session.cancelled:
                break

            current_mult = multiplier_at_step(step)

            if session.auto_cashout and current_mult >= session.auto_cashout and current_mult < session.crash_point:
                session.current_multiplier = round(min(session.auto_cashout, current_mult), 2)
                session.add_point(session.current_multiplier)
                await cashout_session(message, state, session, auto=True)
                return

            if current_mult >= session.crash_point:
                session.current_multiplier = session.crash_point
                session.add_point(session.crash_point)
                await crash_session(message, state, session)
                return

            session.current_multiplier = current_mult
            session.add_point(current_mult)

            try:
                image = await render_chart(session, status="🚀 В ПОЛЕТЕ", crashed=False, cashed_out=False)
                await safe_edit_media(
                    message,
                    image,
                    format_inflight(session),
                    reply_markup=get_crash_keyboard(game_id, current_mult, session.auto_cashout),
                )
            except Exception as exc:
                logger.debug("Inflight update failed: %s", exc)

            await asyncio.sleep(FRAME_DELAY)

        st = await state.get_state()
        if st == CrashState.playing.state and not session.cashed_out and not session.cancelled:
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
    await stats_manager.flush()
    await history_manager.flush()

    try:
        image = await render_summary(session, won=False, win_amount=0)
        await safe_edit_media(
            message,
            image,
            format_crash(session),
            reply_markup=get_replay_keyboard(session.bet),
        )
    except Exception as exc:
        logger.debug("Crash summary edit failed: %s", exc)

    asyncio.create_task(schedule_delete(message, AUTO_DELETE_DELAY))
    await announce_achievements(message, unlocked)


async def cashout_session(
    message: types.Message,
    state: FSMContext,
    session: GameSession,
    auto: bool = False,
    forced: bool = False,
):
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
        session.user_id,
        session.bet,
        win_amount,
        session.current_multiplier,
        session.duration,
    )
    await stats_manager.flush()
    await history_manager.flush()

    try:
        image = await render_summary(session, won=True, win_amount=win_amount)
        caption = format_cashout(session, win_amount)
        if auto:
            tag = "🛬 АВТО-CASHOUT" if not forced else "🛬 ФОРСИРОВАННЫЙ CASHOUT"
            caption = f"{tag}\n\n" + caption
        await safe_edit_media(
            message,
            image,
            caption,
            reply_markup=get_replay_keyboard(session.bet),
        )
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
    try:
        bet = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        return await callback.answer()

    chat_id, user_id = callback.message.chat.id, callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    data = await get_user_data(chat_id, user_id, full_name)

    if data.get("is_banned"):
        return await callback.answer("⛔ Вы заблокированы.", show_alert=True)
    if data.get("balance", 0) - bet < CREDIT_LIMIT:
        return await callback.answer("💳 Недостаточно средств.", show_alert=True)
    if bet < MIN_BET or bet > MAX_BET:
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
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    text = format_stats_card(user_id, full_name)
    try:
        await callback.message.answer(text, reply_markup=get_stats_keyboard())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "crash_achievements")
async def cb_achievements(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    full_name = escape_html(callback.from_user.full_name)
    text = format_achievements_card(user_id, full_name)
    try:
        await callback.message.answer(text)
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
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)
    await message.answer(
        format_stats_card(user_id, full_name),
        reply_markup=get_stats_keyboard(),
    )


@router.message(Command("crash_history"))
async def cmd_crash_history(message: types.Message):
    await message.answer(format_history_card())


@router.message(Command("crash_achievements"))
async def cmd_crash_achievements(message: types.Message):
    user_id = message.from_user.id
    full_name = escape_html(message.from_user.full_name)
    await message.answer(format_achievements_card(user_id, full_name))


@router.message(Command("crash_top"))
async def cmd_crash_top(message: types.Message):
    top = sorted(
        stats_manager._cache.values(),
        key=lambda s: s.profit,
        reverse=True,
    )[:10]
    if not top:
        return await message.answer("Топ пуст.")
    lines = ["🏆 <b>Топ-10 пилотов · по чистой прибыли</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━"]
    medals = ["🥇", "🥈", "🥉"] + [f"#{i}" for i in range(4, 11)]
    for i, st in enumerate(top):
        medal = medals[i] if i < len(medals) else f"#{i + 1}"
        lines.append(
            f"{medal} ID <code>{st.user_id}</code> · "
            f"💰 {format_amount(st.profit)} · "
            f"🎯 {st.win_rate:.1f}%"
        )
    await message.answer("\n".join(lines))


@router.message(Command("crash_themes"))
async def cmd_crash_themes(message: types.Message):
    builder = InlineKeyboardBuilder()
    for theme in Theme:
        builder.add(types.InlineKeyboardButton(
            text=f"🎨 {theme.value.title()}",
            callback_data=f"crash_theme_pref_{theme.value}",
        ))
    builder.adjust(2)
    await message.answer(
        "🎨 <b>Выбери предпочитаемую тему оформления</b>:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("crash_theme_pref_"))
async def cb_theme_pref(callback: types.CallbackQuery):
    value = callback.data.removeprefix("crash_theme_pref_")
    try:
        theme = Theme(value)
    except ValueError:
        return await callback.answer()
    st = stats_manager.get(callback.from_user.id)
    st.favorite_theme = theme.value
    stats_manager._dirty = True
    await stats_manager.flush()
    try:
        await callback.message.edit_text(f"✅ Тема сохранена: <b>{theme.value.title()}</b>")
    except Exception:
        pass
    await callback.answer("Сохранено.")


async def on_startup_crash() -> None:
    await stats_manager.load()
    await history_manager.load()
    logger.info("Crash module initialized. Stats loaded for %d players.", len(stats_manager._cache))


asyncio.get_event_loop().create_task(on_startup_crash()) if False else None