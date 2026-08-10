from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Set, Optional, Any

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

@dataclass
class Card:
    category_id: str  # e.g., "profession", "health"
    category_name: str # e.g., "Профессия", "Здоровье"
    value: str        # e.g., "Хирург (12 лет опыта)"
    icon: str         # e.g., "💼"
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
    username: str
    seat: int
    cards: Dict[str, Card] = field(default_factory=dict)
    special_card: Optional[SpecialCard] = None
    alive: bool = True
    shielded: bool = False
    vote_weight: float = 1.0
    is_rat: bool = False  # Secret role "Крыса"
    voted_for: Optional[int] = None
    has_skipped: bool = False
    ready: bool = False

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
    weights: Dict[str, int]  # key prefix -> score modification

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
    votes: Dict[int, int] = field(default_factory=dict) # voter_id -> target_id
    nominees: List[int] = field(default_factory=list) # players facing kick
    tie_candidates: List[int] = field(default_factory=list)
    stage_message_id: Optional[int] = None
    logs: List[str] = field(default_factory=list)
    timer_seconds: int = 0
    created_at: float = 0.0
