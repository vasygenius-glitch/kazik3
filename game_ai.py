# ============================================================================
# game_ai.py
# ----------------------------------------------------------------------------
# Интеллектуальная система предсказания ходов игрока для экономического бота.
#
# Архитектура памяти (СХЕМА v3):
#   - Память хранится ВНУТРИ документа пользователя в поле "ai_memory".
#   - КЛЮЧЕВОЕ ОТЛИЧИЕ от v2: память теперь РАЗДЕЛЕНА ПО ИГРАМ. Раньше ходы
#     разных игр ("r","s","p" из RPS и "0","1","2" из наперстков) смешивались
#     в одной истории и портили модель. Теперь у каждой игры свой слот.
#   - Все изменения происходят в оперативной памяти (LRU-кэш user_manager.py),
#     после чего вызывается mark_dirty(uid); фоновый flush сбрасывает пакетом.
#
# Модель предсказания:
#   - Марковские цепи порядка 1 и 2 с бэк-оффом и ЗАТУХАНИЕМ счётчиков
#     (модель адаптируется, если игрок сменил стратегию).
#   - Частотный анализ с экспоненциальным сглаживанием.
#   - Детектор повторяющихся паттернов (с весом по свежести совпадения).
#   - НОВОЕ: Win-Stay/Lose-Shift предиктор — ловит самую частую людскую
#     эвристику «выиграл — повторяю, проиграл — меняю».
#   - НОВОЕ: выбор хода ИИ по максимуму ожидаемого выигрыша (EV) против
#     ПОЛНОГО распределения, а не наивный контр-ход против argmax.
#   - НОВОЕ: адаптивная эксплорация — если игрок начал эксплуатировать ИИ
#     (низкий недавний winrate), ИИ автоматически повышает случайность.
#
# Формат ai_memory (компактный, укладывается в лимиты Firestore):
#   {
#     "v": 3,
#     "g": {
#       "rps": {
#         "h": "rpsrps",            # история ходов игрока
#         "o": "WLDWLW",            # история исходов (W/L/D с точки зрения ИИ)
#         "t":  {"r|p": 3.2},       # переходы order-1 (затухающие float-счётчики)
#         "t2": {"rp|s": 1.7},      # переходы order-2
#         "n": 42, "w": 20, "l": 15, "d": 7,
#         "last": 1700000000, "streak": 3, "prof": "sticky"
#       },
#       ...
#     }
#   }
#
# Миграция: v1/v2 (плоская схема) распознаётся и переносится автоматически.
# ============================================================================

from __future__ import annotations

import math
import time
import json
import random
import inspect
import logging
import asyncio
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

__all__ = [
    "GameSpec",
    "GameRegistry",
    "AIMemory",
    "AIMemoryContainer",
    "GameAIEngine",
    "Prediction",
    "UserManagerBridge",
    "BaseGameAdapter",
    "ThimblesAdapter",
    "CoinflipAdapter",
    "RPSAdapter",
    "default_ai_memory",
    "default_game_memory",
    "ensure_ai_memory_field",
    "patch_default_user_structure",
    "train_on_move",
    "register_outcome",
    "predict_move",
    "play_round",
    "reset_ai_memory",
    "reset_game_memory",
    "get_ai_stats",
    "get_engine",
    "set_engine",
    "build_adapter",
]

# Библиотечный логгер: не навязываем хэндлеры приложению (best practice).
logger = logging.getLogger("game_ai")
logger.addHandler(logging.NullHandler())


# ============================================================================
# КОНСТАНТЫ И КОНФИГУРАЦИЯ
# ============================================================================

# Максимальная длина хранимой истории ходов/исходов (символов).
MAX_HISTORY_LEN = 160
MAX_OUTCOME_LEN = 160

# Максимальное число ключей переходов в словарях t / t2.
MAX_TRANSITION_KEYS = 240
MAX_TRANSITION_KEYS_ORDER2 = 160

# Максимальное количество игр, хранящихся в памяти одного пользователя.
# При превышении вытесняется игра, в которую дольше всего не играли.
MAX_GAMES_IN_MEMORY = 8

# Максимальный порядок марковской цепи по умолчанию.
DEFAULT_MAX_ORDER = 2

# Экспоненциальное сглаживание недавних ходов (для частотного и WSLS-анализа).
RECENCY_DECAY = 0.94

# Затухание счётчиков переходов на каждый ход: модель "забывает" старые
# привычки и адаптируется к смене стратегии игрока.
TRANSITION_DECAY = 0.985
TRANSITION_MIN_COUNT = 0.05  # ниже этого значения ключ удаляется

# Аддитивное сглаживание (Лапласа).
LAPLACE_ALPHA = 0.35

# Веса источников предсказания при смешивании.
BLEND_WEIGHTS = {
    "markov2": 0.38,   # марковская цепь порядка 2
    "markov1": 0.24,   # марковская цепь порядка 1
    "freq":    0.12,   # глобальная частота ходов
    "pattern": 0.14,   # детектор повторяющихся паттернов
    "wsls":    0.12,   # win-stay / lose-shift
}

# Порог уверенности, ниже которого предсказание считается «слабым».
LOW_CONFIDENCE_THRESHOLD = 0.40

# Базовая доля случайности.
EXPLORATION_EPSILON = 0.10
# Потолок эксплорации даже при сильной адаптации.
MAX_EXPLORATION_EPSILON = 0.35
# Размер окна для оценки недавней результативности ИИ.
RECENT_WINDOW = 20

# Версия схемы ai_memory.
AI_MEMORY_SCHEMA_VERSION = 3

# Символы исходов в строке "o" (с точки зрения ИИ).
_OUTCOME_CHARS = {1: "W", -1: "L", 0: "D"}
_OUTCOME_VALUES = {"W": 1, "L": -1, "D": 0}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ============================================================================
# ОПИСАНИЕ ИГРЫ (GameSpec)
# ============================================================================

@dataclass
class GameSpec:
    """Формальное описание игры для ИИ-движка."""

    key: str                                   # уникальный идентификатор игры
    name: str                                  # человекочитаемое имя
    moves: List[str]                           # алфавит допустимых ходов
    beats: Dict[str, List[str]] = field(default_factory=dict)  # кто кого бьёт
    symmetric: bool = True                     # симметрична ли игра
    max_order: int = DEFAULT_MAX_ORDER         # макс. порядок марковской цепи

    def __post_init__(self) -> None:
        if not self.moves:
            raise ValueError(f"GameSpec('{self.key}').moves не может быть пустым")
        for m in self.moves:
            if not isinstance(m, str) or len(m) != 1:
                raise ValueError(
                    f"Ход {m!r} в игре '{self.key}' должен быть строкой из "
                    f"ровно 1 символа (для компактного хранения истории)."
                )
        # Дедупликация с сохранением порядка.
        seen: set = set()
        self.moves = [m for m in self.moves if not (m in seen or seen.add(m))]
        # Нормализация и валидация таблицы побед.
        norm: Dict[str, List[str]] = {}
        move_set = set(self.moves)
        for m in self.moves:
            targets = [t for t in self.beats.get(m, []) if t in move_set]
            if m in targets:
                # Ход не может «бить сам себя» — это ломает outcome().
                logger.warning(
                    "Игра '%s': ход '%s' указан бьющим сам себя — исключено. "
                    "Для игр-угадаек используйте пустой beats и адаптер.",
                    self.key, m,
                )
                targets = [t for t in targets if t != m]
            norm[m] = targets
        self.beats = norm

    # ------------------------------------------------------------------ util
    def is_valid_move(self, move: str) -> bool:
        return move in self.moves

    def has_beats_table(self) -> bool:
        """Есть ли у игры осмысленная таблица побед."""
        return any(self.beats.get(m) for m in self.moves)

    def counter_move(self, predicted_player_move: str, rng: Optional[random.Random] = None) -> str:
        """
        Ход ИИ, который бьёт предсказанный ход игрока.
        Если такого нет — случайный ход.
        """
        rng = rng or random
        counters = self.all_counters(predicted_player_move)
        if counters:
            return rng.choice(counters)
        return rng.choice(self.moves)

    def outcome(self, ai_move: str, player_move: str) -> int:
        """Исход раунда с точки зрения ИИ: +1 победа, -1 поражение, 0 ничья."""
        if ai_move == player_move:
            return 0
        if player_move in self.beats.get(ai_move, ()):
            return 1
        if ai_move in self.beats.get(player_move, ()):
            return -1
        return 0

    def all_counters(self, predicted_player_move: str) -> List[str]:
        """Все ходы ИИ, которые бьют указанный ход игрока."""
        return [m for m in self.moves if predicted_player_move in self.beats.get(m, ())]


# ============================================================================
# РЕЕСТР ИГР
# ============================================================================

class GameRegistry:
    """Хранилище зарегистрированных GameSpec."""

    _games: Dict[str, GameSpec] = {}

    @classmethod
    def register(cls, spec: GameSpec) -> GameSpec:
        if spec.key in cls._games:
            logger.warning("Игра '%s' перерегистрирована.", spec.key)
        cls._games[spec.key] = spec
        logger.info("Зарегистрирована игра: %s (%s)", spec.key, spec.name)
        return spec

    @classmethod
    def get(cls, key: str) -> GameSpec:
        spec = cls._games.get(key)
        if spec is None:
            raise KeyError(
                f"Игра '{key}' не зарегистрирована. Доступно: {list(cls._games)}"
            )
        return spec

    @classmethod
    def has(cls, key: str) -> bool:
        return key in cls._games

    @classmethod
    def all(cls) -> Dict[str, GameSpec]:
        return dict(cls._games)


# --------------------------- Предустановленные игры -------------------------

# 1) Наперстки: игрок выбирает наперсток 0/1/2, ИИ прячет шарик там, куда
#    игрок (по прогнозу) НЕ ткнёт. Контр-логика — в адаптере.
THIMBLES = GameRegistry.register(
    GameSpec(
        key="thimbles",
        name="Наперстки",
        moves=["0", "1", "2"],
        beats={},            # особая контр-логика, см. ThimblesAdapter
        symmetric=False,
        max_order=2,
    )
)

# 2) Камень-ножницы-бумага — классическая симметричная игра.
RPS = GameRegistry.register(
    GameSpec(
        key="rps",
        name="Камень-Ножницы-Бумага",
        moves=["r", "s", "p"],
        beats={
            "r": ["s"],      # камень бьёт ножницы
            "s": ["p"],      # ножницы бьют бумагу
            "p": ["r"],      # бумага бьёт камень
        },
        symmetric=True,
        max_order=2,
    )
)

# 3) Орёл-решка: ИИ пытается УГАДАТЬ выбор игрока. Таблица побед пустая
#    (в v2 здесь была противоречивая таблица beats={"0":["0"]}, которая
#    конфликтовала с проверкой ничьей в outcome() — исправлено):
#    победа определяется адаптером как совпадение прогноза с выбором.
COINFLIP = GameRegistry.register(
    GameSpec(
        key="coinflip",
        name="Орёл-Решка",
        moves=["0", "1"],
        beats={},            # особая контр-логика, см. CoinflipAdapter
        symmetric=False,
        max_order=2,
    )
)


# ============================================================================
# СТРУКТУРА ПАМЯТИ ИИ
# ============================================================================

def default_game_memory() -> Dict[str, Any]:
    """Дефолтный слот памяти для одной игры."""
    return {
        "h": "",             # история ходов игрока (строка)
        "o": "",             # история исходов W/L/D (с точки зрения ИИ)
        "t": {},             # переходы order-1: "prev|cur" -> float count
        "t2": {},            # переходы order-2: "p2p1|cur" -> float count
        "n": 0,              # всего ходов
        "w": 0,              # победы ИИ
        "l": 0,              # поражения ИИ
        "d": 0,              # ничьи
        "last": 0,           # ts последнего обновления
        "streak": 0,         # серия (>0 серия ИИ, <0 серия игрока)
        "prof": "unknown",   # профиль игрока
    }


def default_ai_memory() -> Dict[str, Any]:
    """
    Дефолтная структура ai_memory (контейнер по играм) для нового пользователя.
    Именно её нужно добавить в дефолтный документ user_manager.py.
    """
    return {"v": AI_MEMORY_SCHEMA_VERSION, "g": {}}


class AIMemory:
    """
    Память ИИ по ОДНОЙ игре. Работает только в оперативной памяти:
    сохранение в Firestore обеспечивает mark_dirty() + фоновый flush.
    """

    __slots__ = ("h", "o", "t", "t2", "n", "w", "l", "d", "last", "streak", "prof")

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        data = data if isinstance(data, dict) else {}
        self.h: str = str(data.get("h", "") or "")[-MAX_HISTORY_LEN:]
        self.o: str = "".join(
            c for c in str(data.get("o", "") or "") if c in _OUTCOME_VALUES
        )[-MAX_OUTCOME_LEN:]
        self.t: Dict[str, float] = self._load_counts(data.get("t"))
        self.t2: Dict[str, float] = self._load_counts(data.get("t2"))
        self.n: int = max(0, _safe_int(data.get("n")))
        self.w: int = max(0, _safe_int(data.get("w")))
        self.l: int = max(0, _safe_int(data.get("l")))
        self.d: int = max(0, _safe_int(data.get("d")))
        self.last: int = max(0, _safe_int(data.get("last")))
        self.streak: int = _safe_int(data.get("streak"))
        self.prof: str = str(data.get("prof", "unknown") or "unknown")

    @staticmethod
    def _load_counts(raw: Any) -> Dict[str, float]:
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, float] = {}
        for k, v in raw.items():
            fv = _safe_float(v)
            if fv > 0:
                out[str(k)] = fv
        return out

    # --------------------------------------------------------------- factory
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AIMemory":
        return cls(data)

    def to_dict(self) -> Dict[str, Any]:
        """Компактная сериализация (float-счётчики округляются до 3 знаков)."""
        return {
            "h": self.h,
            "o": self.o,
            "t": {k: round(v, 3) for k, v in self.t.items()},
            "t2": {k: round(v, 3) for k, v in self.t2.items()},
            "n": self.n,
            "w": self.w,
            "l": self.l,
            "d": self.d,
            "last": self.last,
            "streak": self.streak,
            "prof": self.prof,
        }

    # ----------------------------------------------------------------- utils
    def history_list(self) -> List[str]:
        return list(self.h)

    def last_move(self) -> Optional[str]:
        return self.h[-1] if self.h else None

    def last_two(self) -> Optional[str]:
        return self.h[-2:] if len(self.h) >= 2 else None

    def total_games(self) -> int:
        return self.w + self.l + self.d

    def winrate_ai(self) -> float:
        """
        Winrate ИИ. ИСПРАВЛЕНО: делим на число завершённых раундов (w+l+d),
        а не на число ходов n — эти счётчики могут расходиться, если ход и
        исход регистрируются раздельно.
        """
        rounds = self.total_games()
        return self.w / rounds if rounds > 0 else 0.0

    def recent_winrate(self, window: int = RECENT_WINDOW) -> Optional[float]:
        """Недавняя результативность ИИ по окну исходов (ничья = 0.5)."""
        tail = self.o[-window:]
        if len(tail) < max(6, window // 3):
            return None
        score = sum(1.0 if c == "W" else 0.5 if c == "D" else 0.0 for c in tail)
        return score / len(tail)

    # ------------------------------------------------------------- обновление
    def record_move(self, player_move: str) -> None:
        """
        Регистрирует новый ход игрока: затухание старых счётчиков, обновление
        переходов и истории. НЕ пишет в БД — только меняет объект в памяти.
        """
        # Затухание — модель адаптируется к смене стратегии игрока.
        self._decay_transitions()

        prev1 = self.last_move()
        prev2 = self.last_two()

        if prev1 is not None:
            key1 = f"{prev1}|{player_move}"
            self.t[key1] = self.t.get(key1, 0.0) + 1.0

        if prev2 is not None and len(prev2) == 2:
            key2 = f"{prev2}|{player_move}"
            self.t2[key2] = self.t2.get(key2, 0.0) + 1.0

        self.h += player_move
        if len(self.h) > MAX_HISTORY_LEN:
            self.h = self.h[-MAX_HISTORY_LEN:]

        self.n += 1
        self.last = int(time.time())
        self._trim_transitions()

    def record_outcome(self, outcome: int) -> None:
        """
        Регистрирует исход раунда (с точки зрения ИИ): +1 / -1 / 0.
        Обновляет статистику, серии и строку исходов.
        """
        outcome = 1 if outcome > 0 else -1 if outcome < 0 else 0
        if outcome > 0:
            self.w += 1
            self.streak = self.streak + 1 if self.streak >= 0 else 1
        elif outcome < 0:
            self.l += 1
            self.streak = self.streak - 1 if self.streak <= 0 else -1
        else:
            self.d += 1
            if self.streak > 0:
                self.streak -= 1
            elif self.streak < 0:
                self.streak += 1

        self.o += _OUTCOME_CHARS[outcome]
        if len(self.o) > MAX_OUTCOME_LEN:
            self.o = self.o[-MAX_OUTCOME_LEN:]

        self.last = int(time.time())

    # -------------------------------------------------------------- internal
    def _decay_transitions(self) -> None:
        if TRANSITION_DECAY >= 1.0:
            return
        for d in (self.t, self.t2):
            dead = []
            for k in d:
                d[k] *= TRANSITION_DECAY
                if d[k] < TRANSITION_MIN_COUNT:
                    dead.append(k)
            for k in dead:
                del d[k]

    def _trim_transitions(self) -> None:
        """Если словари переходов раздулись — оставляем самые частые ключи."""
        if len(self.t) > MAX_TRANSITION_KEYS:
            top = sorted(self.t.items(), key=lambda kv: kv[1], reverse=True)
            self.t = dict(top[:MAX_TRANSITION_KEYS])
        if len(self.t2) > MAX_TRANSITION_KEYS_ORDER2:
            top2 = sorted(self.t2.items(), key=lambda kv: kv[1], reverse=True)
            self.t2 = dict(top2[:MAX_TRANSITION_KEYS_ORDER2])

    def estimate_size(self) -> int:
        """Грубая оценка размера сериализованного слота в байтах."""
        return len(json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8"))


class AIMemoryContainer:
    """
    Контейнер памяти пользователя: слоты AIMemory по ключам игр.
    Понимает и мигрирует старые схемы v1/v2 (плоский словарь без "g").
    """

    __slots__ = ("v", "games")

    def __init__(self) -> None:
        self.v: int = AI_MEMORY_SCHEMA_VERSION
        self.games: Dict[str, AIMemory] = {}

    # --------------------------------------------------------------- factory
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AIMemoryContainer":
        cont = cls()
        if not isinstance(data, dict) or not data:
            return cont

        if isinstance(data.get("g"), dict):
            # Схема v3.
            for game_key, slot in data["g"].items():
                if isinstance(slot, dict):
                    cont.games[str(game_key)] = AIMemory.from_dict(slot)
            return cont

        if "h" in data or "t" in data:
            # Плоская схема v1/v2 — пробуем однозначно определить игру
            # по алфавиту истории и мигрировать без потери данных.
            legacy = AIMemory.from_dict(data)
            hset = set(legacy.h)
            candidates = [
                key for key, spec in GameRegistry.all().items()
                if hset and hset <= set(spec.moves)
            ]
            if len(candidates) == 1:
                cont.games[candidates[0]] = legacy
                logger.info("ai_memory v1/v2 мигрирована в слот '%s'.", candidates[0])
            else:
                logger.info(
                    "ai_memory v1/v2 не удалось однозначно привязать к игре "
                    "(кандидаты: %s) — начата чистая память v3.", candidates,
                )
        return cont

    def to_dict(self) -> Dict[str, Any]:
        return {
            "v": self.v,
            "g": {k: m.to_dict() for k, m in self.games.items()},
        }

    # ------------------------------------------------------------------- api
    def game(self, game_key: str) -> AIMemory:
        """Возвращает слот памяти игры, создавая при необходимости."""
        mem = self.games.get(game_key)
        if mem is None:
            mem = AIMemory()
            self.games[game_key] = mem
            self._evict_if_needed(keep=game_key)
        return mem

    def _evict_if_needed(self, keep: str) -> None:
        """LRU-вытеснение: убираем игру, в которую дольше всего не играли."""
        while len(self.games) > MAX_GAMES_IN_MEMORY:
            victim = min(
                (k for k in self.games if k != keep),
                key=lambda k: self.games[k].last,
                default=None,
            )
            if victim is None:
                break
            logger.info("Вытеснен слот памяти игры '%s' (LRU).", victim)
            del self.games[victim]

    def estimate_document_size(self) -> int:
        return len(json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8"))


# ============================================================================
# ПРЕДСКАЗАТЕЛИ (Predictors)
# ----------------------------------------------------------------------------
# Каждый предсказатель отдаёт распределение вероятностей следующего хода
# игрока: dict[move] -> prob. Движок смешивает их с весами.
# ============================================================================

class BasePredictor:
    """Базовый интерфейс предсказателя."""

    name: str = "base"

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        raise NotImplementedError

    # ------------------------------------------------------------ helpers
    @staticmethod
    def uniform(spec: GameSpec) -> Dict[str, float]:
        p = 1.0 / len(spec.moves)
        return {m: p for m in spec.moves}

    @staticmethod
    def normalize(dist: Dict[str, float], spec: GameSpec) -> Dict[str, float]:
        full = {m: max(0.0, dist.get(m, 0.0)) for m in spec.moves}
        s = sum(full.values())
        if s <= 0 or not math.isfinite(s):
            return BasePredictor.uniform(spec)
        return {m: v / s for m, v in full.items()}


class MarkovOrder1Predictor(BasePredictor):
    """Марковская цепь порядка 1 с аддитивным сглаживанием."""

    name = "markov1"

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        prev = mem.last_move()
        if prev is None:
            return self.uniform(spec)
        counts = {m: mem.t.get(f"{prev}|{m}", 0.0) + LAPLACE_ALPHA for m in spec.moves}
        return self.normalize(counts, spec)


class MarkovOrder2Predictor(BasePredictor):
    """Марковская цепь порядка 2 с плавным бэк-оффом к order-1."""

    name = "markov2"

    def __init__(self) -> None:
        self._fallback = MarkovOrder1Predictor()

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        ctx = mem.last_two()
        if ctx is None or len(ctx) < 2 or spec.max_order < 2:
            return self._fallback.predict(mem, spec)

        raw = {m: mem.t2.get(f"{ctx}|{m}", 0.0) for m in spec.moves}
        observed = sum(raw.values())
        o2 = self.normalize({m: c + LAPLACE_ALPHA for m, c in raw.items()}, spec)

        if observed < 3.0:
            # Плавный бэк-офф: чем меньше наблюдений, тем больше вес order-1.
            o1 = self._fallback.predict(mem, spec)
            beta = min(1.0, observed / 3.0)
            return self.normalize(
                {m: beta * o2[m] + (1.0 - beta) * o1[m] for m in spec.moves}, spec
            )
        return o2


class FrequencyPredictor(BasePredictor):
    """Глобальная частота ходов с экспоненциальным затуханием по свежести."""

    name = "freq"

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        if not mem.h:
            return self.uniform(spec)
        weights: Dict[str, float] = defaultdict(float)
        n = len(mem.h)
        for i, move in enumerate(mem.h):
            if move in spec.moves:
                weights[move] += RECENCY_DECAY ** (n - 1 - i)
        return self.normalize({m: weights.get(m, 0.0) for m in spec.moves}, spec)


class PatternPredictor(BasePredictor):
    """
    Детектор повторяющихся паттернов: ищет последний суффикс истории среди
    прошлых вхождений и смотрит, какой ход следовал за ним.
    УЛУЧШЕНО: свежие совпадения получают больший вес, чем древние.
    """

    name = "pattern"

    def __init__(self, min_len: int = 2, max_len: int = 6) -> None:
        self.min_len = max(1, min_len)
        self.max_len = max(self.min_len, max_len)

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        h = mem.h
        if len(h) < self.min_len + 1:
            return self.uniform(spec)

        scores: Dict[str, float] = defaultdict(float)
        found_any = False
        n = len(h)

        for L in range(min(self.max_len, n - 1), self.min_len - 1, -1):
            suffix = h[-L:]
            base_weight = float(L * L)  # длинные паттерны экспоненциально ценнее
            search_zone = h[:-1]        # исключаем «поимку самого себя»
            idx = 0
            while True:
                pos = search_zone.find(suffix, idx)
                if pos == -1:
                    break
                nxt_index = pos + L
                if nxt_index < n:
                    nxt = h[nxt_index]
                    if nxt in spec.moves:
                        # чем ближе совпадение к концу истории, тем оно ценнее
                        recency = RECENCY_DECAY ** (n - 1 - nxt_index)
                        scores[nxt] += base_weight * recency
                        found_any = True
                idx = pos + 1

        if not found_any:
            return self.uniform(spec)
        return self.normalize({m: scores.get(m, 0.0) for m in spec.moves}, spec)


class WinStayLoseShiftPredictor(BasePredictor):
    """
    НОВОЕ: предиктор «выиграл — повторяю, проиграл — меняю» (WSLS).
    Это самая распространённая человеческая эвристика в играх типа RPS.
    Оценивает фактическую склонность игрока к stay/shift после побед,
    поражений и ничьих (с затуханием по свежести) и строит прогноз.
    """

    name = "wsls"

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        h, o = mem.h, mem.o
        L = min(len(h), len(o))
        if L < 3 or len(spec.moves) < 2:
            return self.uniform(spec)

        # Категория исхода с точки зрения ИГРОКА:
        # 'W' у ИИ = поражение игрока; 'L' у ИИ = победа игрока.
        stats = {"win": [0.0, 0.0], "loss": [0.0, 0.0], "draw": [0.0, 0.0]}
        for i in range(L - 1):
            if h[i] not in spec.moves or h[i + 1] not in spec.moves:
                continue
            cat = "win" if o[i] == "L" else "loss" if o[i] == "W" else "draw"
            w = RECENCY_DECAY ** (L - 2 - i)
            stats[cat][1] += w
            if h[i + 1] == h[i]:
                stats[cat][0] += w

        last_move = h[L - 1]
        if last_move not in spec.moves:
            return self.uniform(spec)
        last_cat = "win" if o[L - 1] == "L" else "loss" if o[L - 1] == "W" else "draw"

        stayed, total = stats[last_cat]
        if total < 1.5:
            return self.uniform(spec)

        p_stay = (stayed + LAPLACE_ALPHA) / (total + 2.0 * LAPLACE_ALPHA)
        others = [m for m in spec.moves if m != last_move]
        p_other = (1.0 - p_stay) / len(others) if others else 0.0

        dist = {m: p_other for m in spec.moves}
        dist[last_move] = p_stay
        return self.normalize(dist, spec)


# ============================================================================
# ПРОФИЛИРОВАНИЕ ИГРОКА
# ============================================================================

def classify_player_profile(mem: AIMemory, spec: GameSpec) -> str:
    """
    Классификатор поведения. ИСПРАВЛЕНО: энтропия нормируется корректно
    (log base k через отношение натуральных логарифмов), анализируется
    недавнее окно истории (игрок мог сменить стиль).
    """
    if mem.n < 8:
        return "unknown"

    h = mem.h[-48:]  # недавнее окно
    if len(h) < 8:
        return "unknown"

    counts = Counter(c for c in h if c in spec.moves)
    if not counts:
        return "unknown"
    total = sum(counts.values())

    # 1) любимый ход
    _, most_common_count = counts.most_common(1)[0]
    repeat_ratio = most_common_count / total

    # 2) повтор предыдущего хода подряд
    same_as_prev = sum(1 for i in range(1, len(h)) if h[i] == h[i - 1])
    streak_ratio = same_as_prev / max(1, len(h) - 1)

    # 3) нормированная энтропия в [0, 1]
    k = len(spec.moves)
    if k > 1:
        ent = 0.0
        for m in spec.moves:
            p = counts.get(m, 0) / total
            if p > 0:
                ent -= p * math.log(p)
        ent /= math.log(k)
    else:
        ent = 0.0

    if ent > 0.92 and streak_ratio < 0.5:
        return "random"
    if streak_ratio > 0.55:
        return "sticky"        # часто повторяет предыдущий ход
    if repeat_ratio > 0.55:
        return "biased"        # есть явно любимый ход
    if ent < 0.6:
        return "predictable"
    return "balanced"


# ============================================================================
# ДВИЖОК ПРЕДСКАЗАНИЯ (GameAIEngine)
# ============================================================================

@dataclass
class Prediction:
    """Результат работы движка."""

    predicted_player_move: str          # наиболее вероятный ход игрока
    ai_move: str                        # выбранный ход ИИ
    confidence: float                   # уверенность [0..1]
    distribution: Dict[str, float]      # итоговое распределение ходов игрока
    used_exploration: bool              # была ли применена случайность
    profile: str                        # профиль игрока
    meta: Dict[str, Any] = field(default_factory=dict)


class GameAIEngine:
    """
    Основной движок: смешивает предсказатели, применяет адаптивную
    эксплорацию и выбирает ход ИИ по максимуму ожидаемого выигрыша (EV).
    Состояние игрока живёт в AIMemory, движок stateless.
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        exploration_epsilon: float = EXPLORATION_EPSILON,
        low_conf_threshold: float = LOW_CONFIDENCE_THRESHOLD,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.weights = dict(weights or BLEND_WEIGHTS)
        self.exploration_epsilon = exploration_epsilon
        self.low_conf_threshold = low_conf_threshold
        self.rng = rng or random.Random()

        self.predictors: Dict[str, BasePredictor] = {
            "markov2": MarkovOrder2Predictor(),
            "markov1": MarkovOrder1Predictor(),
            "freq": FrequencyPredictor(),
            "pattern": PatternPredictor(),
            "wsls": WinStayLoseShiftPredictor(),
        }

    # --------------------------------------------------------------- predict
    def predict(self, mem: AIMemory, spec: GameSpec) -> Prediction:
        """Главный метод: возвращает Prediction с ходом ИИ."""
        # 1) Распределения от всех предсказателей (с защитой от падений).
        dists: Dict[str, Dict[str, float]] = {}
        for key, predictor in self.predictors.items():
            try:
                dists[key] = BasePredictor.normalize(predictor.predict(mem, spec), spec)
            except Exception:  # noqa: BLE001
                logger.exception("Предсказатель '%s' упал — заменён uniform.", key)
                dists[key] = BasePredictor.uniform(spec)

        # 2) Смешивание с весами.
        blended = self._blend(dists, spec)

        # 3) Наиболее вероятный ход игрока и уверенность (со случайным
        #    разрешением ничьих, чтобы не было систематического смещения).
        predicted_move, confidence = self._argmax_conf(blended, spec)

        # 4) Выбор хода ИИ: максимизация EV против ПОЛНОГО распределения.
        ai_move, expected_value = self._best_response(blended, predicted_move, spec)

        # 5) Адаптивная эксплорация: усиливается при низкой уверенности и
        #    при признаках того, что игрок эксплуатирует ИИ.
        eff_eps = (
            self.exploration_epsilon
            if confidence < self.low_conf_threshold
            else self.exploration_epsilon * 0.25
        )
        recent_wr = mem.recent_winrate()
        if recent_wr is not None and recent_wr < 0.40:
            eff_eps += (0.40 - recent_wr) * 1.2
        eff_eps = max(0.0, min(MAX_EXPLORATION_EPSILON, eff_eps))

        used_exploration = False
        if eff_eps > 0 and self.rng.random() < eff_eps:
            ai_move = self.rng.choice(spec.moves)
            used_exploration = True

        profile = classify_player_profile(mem, spec)

        return Prediction(
            predicted_player_move=predicted_move,
            ai_move=ai_move,
            confidence=round(confidence, 4),
            distribution={m: round(p, 4) for m, p in blended.items()},
            used_exploration=used_exploration,
            profile=profile,
            meta={
                "n": mem.n,
                "winrate_ai": round(mem.winrate_ai(), 4),
                "recent_winrate_ai": round(recent_wr, 4) if recent_wr is not None else None,
                "streak": mem.streak,
                "expected_value": round(expected_value, 4),
                "effective_epsilon": round(eff_eps, 4),
                "per_predictor": {
                    k: {mm: round(pp, 3) for mm, pp in v.items()}
                    for k, v in dists.items()
                },
            },
        )

    # ---------------------------------------------------------------- helpers
    def _blend(self, dists: Dict[str, Dict[str, float]], spec: GameSpec) -> Dict[str, float]:
        blended = {m: 0.0 for m in spec.moves}
        total_w = 0.0
        for key, dist in dists.items():
            w = self.weights.get(key, 0.0)
            if w <= 0:
                continue
            total_w += w
            for m in spec.moves:
                blended[m] += w * dist.get(m, 0.0)
        if total_w <= 0:
            return BasePredictor.uniform(spec)
        return BasePredictor.normalize(blended, spec)

    def _argmax_conf(self, dist: Dict[str, float], spec: GameSpec) -> Tuple[str, float]:
        best_p = max(dist.get(m, 0.0) for m in spec.moves)
        best_moves = [m for m in spec.moves if dist.get(m, 0.0) >= best_p - 1e-12]
        best_move = self.rng.choice(best_moves)  # случайный тай-брейк
        if len(spec.moves) > 1:
            uniform_p = 1.0 / len(spec.moves)
            confidence = (best_p - uniform_p) / (1.0 - uniform_p)
        else:
            confidence = best_p
        return best_move, max(0.0, min(1.0, confidence))

    def _best_response(
        self,
        dist: Dict[str, float],
        predicted_move: str,
        spec: GameSpec,
    ) -> Tuple[str, float]:
        """
        Ход ИИ с максимальным ожидаемым выигрышем против распределения.
        Для игр без таблицы побед (наперстки, coinflip) возвращает сам
        предсказанный ход — интерпретация остаётся за адаптером.
        """
        if not spec.has_beats_table():
            return predicted_move, dist.get(predicted_move, 0.0)

        best_ev = -math.inf
        best_moves: List[str] = []
        for ai_m in spec.moves:
            ev = sum(dist.get(pm, 0.0) * spec.outcome(ai_m, pm) for pm in spec.moves)
            if ev > best_ev + 1e-12:
                best_ev = ev
                best_moves = [ai_m]
            elif ev >= best_ev - 1e-12:
                best_moves.append(ai_m)
        return self.rng.choice(best_moves), best_ev


# Глобальный singleton-движок (можно заменить через set_engine).
_engine_singleton: Optional[GameAIEngine] = None


def get_engine() -> GameAIEngine:
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = GameAIEngine()
    return _engine_singleton


def set_engine(engine: GameAIEngine) -> None:
    """Позволяет подменить глобальный движок (например, с фиксированным rng)."""
    global _engine_singleton
    _engine_singleton = engine


# ============================================================================
# ЭКСПОРТИРУЕМЫЕ ФУНКЦИИ: ОБУЧЕНИЕ И ПРОГНОЗ
# ----------------------------------------------------------------------------
# Высокоуровневый API. Функции принимают сырой dict ai_memory (как он лежит
# в кэше user_manager.py) и возвращают обновлённый dict — его нужно положить
# обратно в кэш и вызвать mark_dirty().
# ============================================================================

def train_on_move(
    ai_memory: Optional[Dict[str, Any]],
    player_move: str,
    game_key: str,
) -> Dict[str, Any]:
    """
    Обучение модели на одном ходе игрока.

    :param ai_memory: текущий dict ai_memory из документа пользователя (или None).
    :param player_move: ход игрока (символ из алфавита игры).
    :param game_key: ключ зарегистрированной игры.
    :return: обновлённый dict ai_memory.
    """
    spec = GameRegistry.get(game_key)
    if not spec.is_valid_move(player_move):
        raise ValueError(f"Недопустимый ход '{player_move}' для игры '{game_key}'")

    cont = AIMemoryContainer.from_dict(ai_memory)
    mem = cont.game(game_key)
    mem.record_move(player_move)
    mem.prof = classify_player_profile(mem, spec)
    return cont.to_dict()


def register_outcome(
    ai_memory: Optional[Dict[str, Any]],
    outcome: int,
    game_key: str,
) -> Dict[str, Any]:
    """
    Регистрирует исход раунда (для статистики, серий и WSLS-модели).
    ИСПРАВЛЕНО: теперь требует game_key — исходы больше не смешиваются
    между разными играми.

    :param outcome: +1 победа ИИ, -1 поражение, 0 ничья.
    """
    GameRegistry.get(game_key)  # валидация ключа
    cont = AIMemoryContainer.from_dict(ai_memory)
    cont.game(game_key).record_outcome(int(outcome))
    return cont.to_dict()


def predict_move(
    ai_memory: Optional[Dict[str, Any]],
    game_key: str,
) -> Dict[str, Any]:
    """
    Прогнозирует ход игрока и выбирает ход ИИ (без изменения памяти).

    :return: dict c полями predicted_player_move, ai_move, confidence,
             distribution, used_exploration, profile, meta.
    """
    spec = GameRegistry.get(game_key)
    cont = AIMemoryContainer.from_dict(ai_memory)
    pred = get_engine().predict(cont.game(game_key), spec)
    return {
        "predicted_player_move": pred.predicted_player_move,
        "ai_move": pred.ai_move,
        "confidence": pred.confidence,
        "distribution": pred.distribution,
        "used_exploration": pred.used_exploration,
        "profile": pred.profile,
        "meta": pred.meta,
    }


def play_round(
    ai_memory: Optional[Dict[str, Any]],
    game_key: str,
    player_move: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Полный цикл раунда «в один вызов» (для игр с таблицей побед):
      1) предсказать ход игрока и выбрать ход ИИ (ДО учёта этого хода);
      2) вычислить исход; 3) обучиться; 4) зарегистрировать исход.

    :return: (обновлённый ai_memory, отчёт о раунде)

    Использование:
        new_mem, report = play_round(user.get("ai_memory"), "rps", player_move)
        user["ai_memory"] = new_mem
        user_manager.mark_dirty(uid)
    """
    spec = GameRegistry.get(game_key)
    if not spec.is_valid_move(player_move):
        raise ValueError(f"Недопустимый ход '{player_move}' для игры '{game_key}'")

    cont = AIMemoryContainer.from_dict(ai_memory)
    mem = cont.game(game_key)

    pred = get_engine().predict(mem, spec)               # 1) прогноз ДО учёта
    outcome = spec.outcome(pred.ai_move, player_move)    # 2) исход
    mem.record_move(player_move)                         # 3) обучение
    mem.prof = classify_player_profile(mem, spec)
    mem.record_outcome(outcome)                          # 4) исход в память

    report = _build_report(spec, mem, pred, player_move, outcome)
    return cont.to_dict(), report


def _build_report(
    spec: GameSpec,
    mem: AIMemory,
    pred: Prediction,
    player_move: str,
    outcome: int,
) -> Dict[str, Any]:
    return {
        "game": spec.key,
        "ai_move": pred.ai_move,
        "player_move": player_move,
        "predicted_player_move": pred.predicted_player_move,
        "outcome": outcome,
        "outcome_text": {1: "ai_win", -1: "player_win", 0: "draw"}[outcome],
        "confidence": pred.confidence,
        "profile": pred.profile,
        "used_exploration": pred.used_exploration,
        "distribution": pred.distribution,
        "meta": pred.meta,
        "totals": {
            "n": mem.n,
            "ai_wins": mem.w,
            "player_wins": mem.l,
            "draws": mem.d,
            "streak": mem.streak,
            "winrate_ai": round(mem.winrate_ai(), 4),
        },
    }


def reset_ai_memory() -> Dict[str, Any]:
    """Полный сброс памяти ИИ по всем играм."""
    return default_ai_memory()


def reset_game_memory(ai_memory: Optional[Dict[str, Any]], game_key: str) -> Dict[str, Any]:
    """НОВОЕ: сброс памяти только по одной игре (остальные не трогаем)."""
    cont = AIMemoryContainer.from_dict(ai_memory)
    cont.games.pop(game_key, None)
    return cont.to_dict()


def get_ai_stats(
    ai_memory: Optional[Dict[str, Any]],
    game_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Статистика памяти ИИ. Без game_key — агрегат по всем играм,
    с game_key — детальная статистика по конкретной игре.
    """
    cont = AIMemoryContainer.from_dict(ai_memory)

    def _one(mem: AIMemory) -> Dict[str, Any]:
        recent = mem.recent_winrate()
        return {
            "total_moves": mem.n,
            "rounds": mem.total_games(),
            "ai_wins": mem.w,
            "player_wins": mem.l,
            "draws": mem.d,
            "winrate_ai": round(mem.winrate_ai(), 4),
            "recent_winrate_ai": round(recent, 4) if recent is not None else None,
            "streak": mem.streak,
            "profile": mem.prof,
            "history_len": len(mem.h),
            "transition_keys": len(mem.t),
            "transition_keys_order2": len(mem.t2),
            "slot_size_bytes": mem.estimate_size(),
        }

    if game_key is not None:
        return _one(cont.game(game_key))

    return {
        "schema_version": cont.v,
        "doc_size_bytes": cont.estimate_document_size(),
        "games": {k: _one(m) for k, m in cont.games.items()},
    }


# ============================================================================
# ИНТЕГРАЦИЯ С КЭШЕМ user_manager.py
# ----------------------------------------------------------------------------
# Тонкий асинхронный слой-адаптер. НЕ пишет в Firestore напрямую: читает
# пользователя из кэша, меняет ai_memory в памяти и вызывает mark_dirty.
#
# Ожидаемый интерфейс user_manager:
#   async def get_user(uid) -> dict     (или sync — оба варианта поддержаны)
#   def mark_dirty(uid) -> None
#   (опц.) def set_user(uid, data) -> None
# ============================================================================

# Резольвер особой механики: (Prediction, GameSpec) -> (player_move, outcome, extra)
CustomResolver = Callable[["Prediction", GameSpec], Tuple[str, int, Dict[str, Any]]]


class UserManagerBridge:
    """
    Мост между game_ai и user_manager. Инкапсулирует чтение/запись поля
    ai_memory, соблюдая правило: менять в памяти -> mark_dirty -> flush.
    ИСПРАВЛЕНО: словарь per-user блокировок больше не растёт бесконечно.
    НОВОЕ: play_custom() — атомарный раунд для игр с особой механикой
    (раньше наперстки делали predict/train/outcome тремя отдельными
    захватами лока, что допускало гонки между шагами).
    """

    def __init__(
        self,
        get_user: Callable[[Any], Union[Dict[str, Any], Awaitable[Dict[str, Any]]]],
        mark_dirty: Callable[[Any], None],
        set_user: Optional[Callable[[Any, Dict[str, Any]], None]] = None,
        memory_field: str = "ai_memory",
        lock_factory: Optional[Callable[[], asyncio.Lock]] = None,
        max_locks: int = 512,
    ) -> None:
        self._get_user = get_user
        self._mark_dirty = mark_dirty
        self._set_user = set_user
        self.memory_field = memory_field
        self._locks: Dict[Any, asyncio.Lock] = {}
        self._lock_factory = lock_factory or asyncio.Lock
        self._max_locks = max(16, max_locks)

    # ------------------------------------------------------------- locking
    def _get_lock(self, uid: Any) -> asyncio.Lock:
        lock = self._locks.get(uid)
        if lock is None:
            self._cleanup_locks()
            lock = self._lock_factory()
            self._locks[uid] = lock
        return lock

    def _cleanup_locks(self) -> None:
        """Удаляем свободные локи, если словарь разросся (защита от утечки)."""
        if len(self._locks) < self._max_locks:
            return
        for key in list(self._locks.keys()):
            lk = self._locks.get(key)
            if lk is not None and not lk.locked():
                del self._locks[key]
            if len(self._locks) < self._max_locks // 2:
                break

    # ------------------------------------------------------------- reading
    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _read(self, uid: Any) -> Tuple[Dict[str, Any], AIMemoryContainer]:
        """Возвращает (user_doc, контейнер памяти). Гарантирует наличие поля."""
        user = await self._maybe_await(self._get_user(uid))
        if user is None:
            raise KeyError(f"Пользователь {uid} не найден в кэше/БД")
        cont = AIMemoryContainer.from_dict(user.get(self.memory_field))
        return user, cont

    def _write(self, uid: Any, user: Dict[str, Any], cont: AIMemoryContainer) -> None:
        """Пишет ai_memory обратно В КЭШ и помечает грязным (БЕЗ записи в БД)."""
        user[self.memory_field] = cont.to_dict()
        if self._set_user is not None:
            self._set_user(uid, user)
        self._mark_dirty(uid)

    # --------------------------------------------------------- public API
    async def train(self, uid: Any, game_key: str, player_move: str) -> Dict[str, Any]:
        """Обучение на одном ходе игрока (в памяти + mark_dirty)."""
        spec = GameRegistry.get(game_key)
        if not spec.is_valid_move(player_move):
            raise ValueError(f"Недопустимый ход '{player_move}' для игры '{game_key}'")
        async with self._get_lock(uid):
            user, cont = await self._read(uid)
            mem = cont.game(game_key)
            mem.record_move(player_move)
            mem.prof = classify_player_profile(mem, spec)
            self._write(uid, user, cont)
            return cont.to_dict()

    async def predict(self, uid: Any, game_key: str) -> Dict[str, Any]:
        """Прогноз хода игрока и хода ИИ (чтение из кэша, без записи)."""
        async with self._get_lock(uid):
            _user, cont = await self._read(uid)
            return predict_move(cont.to_dict(), game_key)

    async def play(self, uid: Any, game_key: str, player_move: str) -> Dict[str, Any]:
        """
        Полный раунд для игр с таблицей побед:
        предсказать -> сыграть -> обучиться -> сохранить в кэш.
        """
        async with self._get_lock(uid):
            user, cont = await self._read(uid)
            new_mem, report = play_round(cont.to_dict(), game_key, player_move)
            user[self.memory_field] = new_mem
            if self._set_user is not None:
                self._set_user(uid, user)
            self._mark_dirty(uid)
            return report

    async def play_custom(
        self,
        uid: Any,
        game_key: str,
        resolver: CustomResolver,
    ) -> Dict[str, Any]:
        """
        НОВОЕ: атомарный раунд для игр с особой механикой (наперстки, coinflip).
        resolver получает Prediction и GameSpec и возвращает
        (player_move, outcome_for_ai, extra_report_fields).
        Всё выполняется под ОДНИМ локом — никаких гонок между шагами.
        """
        spec = GameRegistry.get(game_key)
        async with self._get_lock(uid):
            user, cont = await self._read(uid)
            mem = cont.game(game_key)

            pred = get_engine().predict(mem, spec)
            player_move, outcome, extra = resolver(pred, spec)

            if not spec.is_valid_move(player_move):
                raise ValueError(
                    f"Резольвер вернул недопустимый ход '{player_move}' "
                    f"для игры '{game_key}'"
                )

            mem.record_move(player_move)
            mem.prof = classify_player_profile(mem, spec)
            mem.record_outcome(outcome)
            self._write(uid, user, cont)

            report = _build_report(spec, mem, pred, player_move, outcome)
            report.update(extra)
            return report

    async def register_outcome(self, uid: Any, game_key: str, outcome: int) -> Dict[str, Any]:
        """Отдельная регистрация исхода (если раунд считается вне play())."""
        async with self._get_lock(uid):
            user, cont = await self._read(uid)
            cont.game(game_key).record_outcome(int(outcome))
            self._write(uid, user, cont)
            return cont.to_dict()

    async def stats(self, uid: Any, game_key: Optional[str] = None) -> Dict[str, Any]:
        """Статистика памяти ИИ игрока."""
        async with self._get_lock(uid):
            _user, cont = await self._read(uid)
            return get_ai_stats(cont.to_dict(), game_key)

    async def reset(self, uid: Any, game_key: Optional[str] = None) -> Dict[str, Any]:
        """Сброс памяти ИИ: всей или только по одной игре."""
        async with self._get_lock(uid):
            user, cont = await self._read(uid)
            if game_key is None:
                cont = AIMemoryContainer()
            else:
                cont.games.pop(game_key, None)
            self._write(uid, user, cont)
            return cont.to_dict()


# ============================================================================
# ПАТЧ ДЛЯ user_manager.py: ДЕФОЛТНАЯ СТРУКТУРА ПОЛЬЗОВАТЕЛЯ
# ============================================================================

def ensure_ai_memory_field(user_doc: Dict[str, Any], field_name: str = "ai_memory") -> Dict[str, Any]:
    """
    Гарантирует наличие корректного поля ai_memory в документе пользователя.
    Идемпотентна: не перетирает валидную память, мягко мигрирует старые схемы.
    """
    mem = user_doc.get(field_name)
    if not isinstance(mem, dict):
        user_doc[field_name] = default_ai_memory()
    else:
        user_doc[field_name] = AIMemoryContainer.from_dict(mem).to_dict()
    return user_doc


def patch_default_user_structure(
    default_factory: Callable[[], Dict[str, Any]],
) -> Callable[[], Dict[str, Any]]:
    """
    Оборачивает функцию создания дефолтного пользователя так, чтобы поле
    ai_memory всегда присутствовало.

    Пример в user_manager.py:
        _make_default_user = patch_default_user_structure(_make_default_user)
    """
    def wrapper() -> Dict[str, Any]:
        return ensure_ai_memory_field(default_factory())
    return wrapper


# ============================================================================
# АДАПТЕРЫ КОНКРЕТНЫХ ИГР
# ============================================================================

class BaseGameAdapter:
    """Базовый адаптер игры: связывает механику с движком предсказания."""

    game_key: str = ""

    def __init__(self, bridge: UserManagerBridge) -> None:
        if not self.game_key:
            raise ValueError(f"{type(self).__name__}: game_key не задан")
        self.bridge = bridge
        self.spec = GameRegistry.get(self.game_key)
        self.rng = random.Random()

    async def ai_decide(self, uid: Any) -> Dict[str, Any]:
        """Возвращает решение ИИ (без изменения статистики)."""
        return await self.bridge.predict(uid, self.game_key)

    async def resolve(self, uid: Any, player_move: str) -> Dict[str, Any]:
        """Разрешает раунд полностью (переопределяется при особой механике)."""
        return await self.bridge.play(uid, self.game_key, player_move)


class ThimblesAdapter(BaseGameAdapter):
    """
    Наперстки. Игрок выбирает наперсток 0/1/2, ИИ прячет шарик так, чтобы
    игрок НЕ угадал.
    УЛУЧШЕНО:
      - весь раунд атомарен (один захват лока вместо трёх);
      - шарик размещается взвешенно-обратно к прогнозируемому распределению
        (менее эксплуатируемо, чем равновероятный выбор из «не-предсказанных»).
    """

    game_key = "thimbles"

    async def resolve(self, uid: Any, player_pick: str) -> Dict[str, Any]:
        if not self.spec.is_valid_move(player_pick):
            raise ValueError("Наперсток должен быть '0', '1' или '2'")

        rng = self.rng

        def resolver(pred: Prediction, spec: GameSpec) -> Tuple[str, int, Dict[str, Any]]:
            # Вероятность спрятать шарик обратна вероятности выбора игроком.
            weights = [max(1e-4, 1.0 - pred.distribution.get(m, 0.0)) for m in spec.moves]
            ball_position = rng.choices(spec.moves, weights=weights, k=1)[0]

            player_won = (player_pick == ball_position)
            outcome = -1 if player_won else 1
            extra = {
                "player_pick": player_pick,
                "ball_position": ball_position,
                "predicted_pick": pred.predicted_player_move,
                "player_won": player_won,
                "outcome_for_ai": outcome,
            }
            return player_pick, outcome, extra

        return await self.bridge.play_custom(uid, self.game_key, resolver)


class CoinflipAdapter(BaseGameAdapter):
    """
    Орёл-решка. Игрок выбирает 0/1, ИИ пытается угадать его выбор.
    ИИ выигрывает при совпадении. Раунд атомарен.
    """

    game_key = "coinflip"

    async def resolve(self, uid: Any, player_move: str) -> Dict[str, Any]:
        if not self.spec.is_valid_move(player_move):
            raise ValueError("Ход должен быть '0' или '1'")

        def resolver(pred: Prediction, spec: GameSpec) -> Tuple[str, int, Dict[str, Any]]:
            ai_guess = pred.ai_move  # с учётом эксплорации движка
            ai_correct = (ai_guess == player_move)
            outcome = 1 if ai_correct else -1
            extra = {
                "ai_guess": ai_guess,
                "ai_correct": ai_correct,
                "outcome_for_ai": outcome,
            }
            return player_move, outcome, extra

        return await self.bridge.play_custom(uid, self.game_key, resolver)


class RPSAdapter(BaseGameAdapter):
    """Камень-ножницы-бумага — прямое использование симметричной механики."""

    game_key = "rps"


ADAPTERS: Dict[str, type] = {
    "thimbles": ThimblesAdapter,
    "coinflip": CoinflipAdapter,
    "rps": RPSAdapter,
}


def build_adapter(game_key: str, bridge: UserManagerBridge) -> BaseGameAdapter:
    """Фабрика адаптеров игр."""
    adapter_cls = ADAPTERS.get(game_key)
    if adapter_cls is None:
        raise KeyError(f"Нет адаптера для игры '{game_key}'. Доступно: {list(ADAPTERS)}")
    return adapter_cls(bridge)


# ============================================================================
# ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ / САМОПРОВЕРКА (без Firestore)
# ============================================================================

class _FakeUserManager:
    """Простейшая имитация user_manager для локальных тестов."""

    def __init__(self) -> None:
        self._store: Dict[Any, Dict[str, Any]] = {}
        self.dirty: set = set()

    async def get_user(self, uid: Any) -> Dict[str, Any]:
        if uid not in self._store:
            self._store[uid] = ensure_ai_memory_field({})
        return self._store[uid]

    def mark_dirty(self, uid: Any) -> None:
        self.dirty.add(uid)

    def set_user(self, uid: Any, data: Dict[str, Any]) -> None:
        self._store[uid] = data


def _simulate(
    game_key: str,
    player_strategy: Callable[[List[str], GameSpec], str],
    rounds: int = 300,
    label: str = "",
) -> None:
    """Симуляция серии раундов против заданной стратегии игрока."""
    spec = GameRegistry.get(game_key)
    fum = _FakeUserManager()
    bridge = UserManagerBridge(
        get_user=fum.get_user,
        mark_dirty=fum.mark_dirty,
        set_user=fum.set_user,
    )
    adapter = build_adapter(game_key, bridge)

    async def run() -> None:
        uid = "tester"
        history: List[str] = []
        for _ in range(rounds):
            move = player_strategy(history, spec)
            await adapter.resolve(uid, move)
            history.append(move)
        stats = await bridge.stats(uid, game_key)
        wr = stats["winrate_ai"]
        print(f"\n=== {spec.name} ({game_key}) | стратегия: {label} ===")
        print(f"    winrate ИИ: {wr:.3f} | профиль: {stats['profile']} "
              f"| раундов: {stats['rounds']}")
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    asyncio.run(run())


def _strategy_cyclic(history: List[str], spec: GameSpec) -> str:
    """Игрок ходит циклически — идеально предсказуемо."""
    return spec.moves[len(history) % len(spec.moves)]


def _strategy_biased(history: List[str], spec: GameSpec) -> str:
    """Игрок в 70% случаев выбирает первый ход, иначе случайно."""
    if random.random() < 0.7:
        return spec.moves[0]
    return random.choice(spec.moves)


def _strategy_random(history: List[str], spec: GameSpec) -> str:
    """Полностью случайный игрок — верхняя граница «непредсказуемости»."""
    return random.choice(spec.moves)


def _strategy_sticky(history: List[str], spec: GameSpec) -> str:
    """Игрок склонен повторять предыдущий ход."""
    if history and random.random() < 0.75:
        return history[-1]
    return random.choice(spec.moves)


def _strategy_pattern(history: List[str], spec: GameSpec) -> str:
    """Игрок повторяет фиксированный паттерн (например, r r p s s ...)."""
    pattern_idx = [0, 0, 1, 2, 2]
    idx = pattern_idx[len(history) % len(pattern_idx)]
    return spec.moves[idx % len(spec.moves)]


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(name)s %(levelname)s: %(message)s",
    )
    print(">>> Демонстрация движка предсказания game_ai.py")
    print(">>> Против предсказуемых стратегий winrate ИИ должен быть заметно")
    print(">>> выше 1/3 (RPS) — против случайной около базовой линии.\n")

    for strat_name, strat in [
        ("cyclic", _strategy_cyclic),
        ("biased", _strategy_biased),
        ("sticky", _strategy_sticky),
        ("pattern", _strategy_pattern),
        ("random", _strategy_random),
    ]:
        _simulate("rps", strat, rounds=400, label=strat_name)

    print("\n>>> Наперстки:")
    _simulate("thimbles", _strategy_cyclic, rounds=300, label="cyclic")
    _simulate("thimbles", _strategy_biased, rounds=300, label="biased")

    print("\n>>> Coinflip:")
    _simulate("coinflip", _strategy_sticky, rounds=300, label="sticky")