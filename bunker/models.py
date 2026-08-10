# bunker/models.py
from __future__ import annotations

import asyncio
import html
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set

MIN_PLAYERS = 2
MAX_PLAYERS = 16
TELEGRAM_TEXT_LIMIT = 4096


def escape_html(text: object) -> str:
    """Безопасная вставка пользовательских данных в parse_mode=HTML."""
    return html.escape(str(text), quote=False)


class Phase(Enum):
    LOBBY = auto()
    DEALING = auto()
    INTRO = auto()
    REVEAL = auto()
    DISCUSSION = auto()
    DEFENSE = auto()
    VOTING = auto()
    TIEBREAK = auto()
    KICK = auto()
    FINAL_SPEECH = auto()
    EPILOGUE = auto()
    FINISHED = auto()

    @property
    def is_voting(self) -> bool:
        return self in (Phase.VOTING, Phase.TIEBREAK)

    @property
    def is_over(self) -> bool:
        return self in (Phase.EPILOGUE, Phase.FINISHED)


@dataclass
class Card:
    category_id: str
    category_name: str       # без эмодзи! иконка хранится отдельно
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
    is_rat: bool = False
    voted_for: Optional[int] = None
    has_skipped: bool = False
    ready: bool = False
    reveals_this_round: int = 0

    @property
    def safe_name(self) -> str:
        return escape_html(self.name)

    def hidden_cards(self) -> List[Card]:
        return [c for c in self.cards.values() if not c.revealed]

    def revealed_cards(self) -> List[Card]:
        return [c for c in self.cards.values() if c.revealed]

    def reset_round_state(self) -> None:
        self.voted_for = None
        self.has_skipped = False
        self.reveals_this_round = 0
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
    # "категория:подстрока" -> модификатор очков
    weights: Dict[str, int] = field(default_factory=dict)


@dataclass
class Game:
    game_id: str
    chat_id: int
    host_id: int
    host_name: str
    phase: Phase = Phase.LOBBY
    players: Dict[int, Player] = field(default_factory=dict)
    scenario: Optional[Scenario] = None
    current_round: int = 1
    total_rounds: int = 1
    capacity: int = 1
    current_speaker_id: Optional[int] = None
    votes: Dict[int, int] = field(default_factory=dict)
    nominees: List[int] = field(default_factory=list)
    tie_candidates: List[int] = field(default_factory=list)
    tie_attempts: int = 0
    stage_message_id: Optional[int] = None
    logs: List[str] = field(default_factory=list)
    timer_seconds: int = 0
    phase_deadline: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # защита от гонок при одновременных нажатиях кнопок
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    # ---------- helpers ----------
    def touch(self) -> None:
        self.updated_at = time.time()

    def alive_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.alive]

    def dead_players(self) -> List[Player]:
        return [p for p in self.players.values() if not p.alive]

    @property
    def alive_count(self) -> int:
        return sum(1 for p in self.players.values() if p.alive)

    @property
    def host_safe_name(self) -> str:
        return escape_html(self.host_name)

    def log(self, message: str, keep: int = 40) -> None:
        """Пишет событие, ограничивая размер журнала (иначе он растёт бесконечно)."""
        self.logs.append(message)
        if len(self.logs) > keep:
            del self.logs[:-keep]
        self.touch()

    def reset_round_state(self) -> None:
        self.votes.clear()
        self.nominees.clear()
        self.tie_candidates.clear()
        self.tie_attempts = 0
        for p in self.players.values():
            p.reset_round_state()
