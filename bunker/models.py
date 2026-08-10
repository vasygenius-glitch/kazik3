# bunker/models.py
from __future__ import annotations

import asyncio
import html
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional

MIN_PLAYERS = 2
MAX_PLAYERS = 16
TG_TEXT_LIMIT = 4096
BOARD_SOFT_LIMIT = 3400      # дальше табло сжимается
EVENTS_SHOW = 3              # сколько событий видно на табло
EVENTS_KEEP = 6


def escape_html(text: object) -> str:
    return html.escape(str(text), quote=False)


def shorten(text: object, limit: int = 60) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


class Phase(Enum):
    LOBBY = auto()
    INTRO = auto()
    REVEAL = auto()
    DISCUSSION = auto()
    VOTING = auto()
    TIEBREAK = auto()
    EPILOGUE = auto()
    FINISHED = auto()

    @property
    def is_voting(self) -> bool:
        return self in (Phase.VOTING, Phase.TIEBREAK)

    @property
    def is_over(self) -> bool:
        return self in (Phase.EPILOGUE, Phase.FINISHED)

    @property
    def in_game(self) -> bool:
        return self not in (Phase.LOBBY, Phase.EPILOGUE, Phase.FINISHED)

    @property
    def title(self) -> str:
        return PHASE_TITLES.get(self, "—")


PHASE_TITLES: Dict[Phase, str] = {
    Phase.LOBBY: "🚪 Лобби",
    Phase.INTRO: "📜 Брифинг",
    Phase.REVEAL: "🔓 Раскрытие",
    Phase.DISCUSSION: "💬 Обсуждение",
    Phase.VOTING: "🗳 Голосование",
    Phase.TIEBREAK: "⚖️ Переголосование",
    Phase.EPILOGUE: "📖 Эпилог",
    Phase.FINISHED: "🏁 Завершена",
}

# наборы значений для меню настроек (переключаются по кругу)
REVEAL_CHOICES = (30, 45, 60, 90, 120)
DISCUSSION_CHOICES = (30, 60, 90, 120, 180, 300)
VOTING_CHOICES = (30, 45, 60, 90)
FIRST_REVEAL_CHOICES = (1, 2, 3)
ROUND_REVEAL_CHOICES = (1, 2)


@dataclass
class GameSettings:
    intro_seconds: int = 20
    reveal_seconds: int = 60
    discussion_seconds: int = 60        # обсуждение по умолчанию — 1 минута
    voting_seconds: int = 45
    tiebreak_seconds: int = 30
    reveals_first_round: int = 2
    reveals_per_round: int = 1
    allow_no_reveal: bool = True        # можно «ничего не открывать»
    use_special_cards: bool = True
    open_votes: bool = False            # показывать, кто за кого голосовал
    phase_pings: bool = False           # доп. сообщение в чат на каждой фазе


@dataclass
class Card:
    category_id: str
    category_name: str
    value: str
    icon: str
    revealed: bool = False


@dataclass
class SpecialCard:
    id: str
    name: str
    icon: str
    description: str
    used: bool = False


@dataclass
class Player:
    user_id: int
    name: str
    username: str = ""
    seat: int = 0
    cards: Dict[str, Card] = field(default_factory=dict)
    special_card: Optional[SpecialCard] = None
    alive: bool = True
    shielded: bool = False
    vote_weight: float = 1.0
    voted_for: Optional[int] = None
    has_skipped: bool = False
    is_bot: bool = False
    reveals_this_round: int = 0
    no_reveal_choice: bool = False
    # ЛС
    dm_available: bool = False
    dm_warned: bool = False
    prompt_message_id: Optional[int] = None
    prompt_signature: str = ""
    dossier_message_id: Optional[int] = None

    @property
    def safe_name(self) -> str:
        return escape_html(self.name)

    @property
    def mention(self) -> str:
        if self.username:
            return f"@{escape_html(self.username)}"
        return f'<a href="tg://user?id={self.user_id}">{self.safe_name}</a>'

    def hidden_cards(self) -> List[Card]:
        return [c for c in self.cards.values() if not c.revealed]

    def revealed_cards(self) -> List[Card]:
        return [c for c in self.cards.values() if c.revealed]

    def reset_round_state(self) -> None:
        self.voted_for = None
        self.has_skipped = False
        self.reveals_this_round = 0
        self.no_reveal_choice = False
        self.shielded = False
        self.vote_weight = 1.0


@dataclass
class Scenario:
    id: str
    title: str
    icon: str
    rarity: str
    intro_text: str
    duration_years: int
    bunker_name: str
    bunker_size: str
    bunker_rooms: List[str]
    supplies: str
    problems: List[str]
    weights: Dict[str, int] = field(default_factory=dict)


@dataclass
class Game:
    game_id: str
    chat_id: int
    host_id: int
    host_name: str
    phase: Phase = Phase.LOBBY
    settings: GameSettings = field(default_factory=GameSettings)
    players: Dict[int, Player] = field(default_factory=dict)
    scenario: Optional[Scenario] = None
    current_round: int = 1
    total_rounds: int = 1
    capacity: int = 1
    votes: Dict[int, int] = field(default_factory=dict)
    tie_candidates: List[int] = field(default_factory=list)
    tie_attempts: int = 0
    consecutive_no_reveals: int = 0

    lobby_message_id: Optional[int] = None
    board_message_id: Optional[int] = None
    board_signature: str = ""
    board_edited_at: float = 0.0

    events: List[str] = field(default_factory=list)
    timer_seconds: int = 0
    phase_deadline: float = 0.0
    phase_started_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
    timer_task: Optional[asyncio.Task] = field(default=None, repr=False, compare=False)

    # ---------- helpers ----------
    def touch(self) -> None:
        self.updated_at = time.time()

    def alive_players(self) -> List[Player]:
        return sorted((p for p in self.players.values() if p.alive), key=lambda p: p.seat)

    def dead_players(self) -> List[Player]:
        return sorted((p for p in self.players.values() if not p.alive), key=lambda p: p.seat)

    def ordered_players(self) -> List[Player]:
        return sorted(self.players.values(), key=lambda p: p.seat)

    def humans(self) -> List[Player]:
        return [p for p in self.players.values() if not p.is_bot]

    @property
    def alive_count(self) -> int:
        return sum(1 for p in self.players.values() if p.alive)

    @property
    def host_safe_name(self) -> str:
        return escape_html(self.host_name)

    def push_event(self, text: str) -> None:
        """Событие попадает в ленту на табло, а не отдельным сообщением в чат."""
        if not text:
            return
        self.events.append(text)
        del self.events[:-EVENTS_KEEP]
        self.touch()

    def clear_events(self) -> None:
        self.events.clear()

    def reset_round_state(self) -> None:
        self.votes.clear()
        self.tie_candidates.clear()
        self.tie_attempts = 0
        for p in self.players.values():
            p.reset_round_state()
