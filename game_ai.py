# ============================================================================
# game_ai.py
# ----------------------------------------------------------------------------
# Интеллектуальная система предсказания ходов игрока для экономического бота.
#
# Архитектура памяти:
#   - Память каждого игрока хранится ВНУТРИ основного документа пользователя
#     в поле "ai_memory" (компактная строка ходов + плоский словарь вероятностей).
#   - Все изменения происходят в оперативной памяти (LRU-кэш user_manager.py),
#     после чего вызывается mark_dirty(uid), а фоновый flush сам сбрасывает
#     всё в Firestore пакетом раз в 15 секунд.
#
# Модель предсказания (Улучшенная версия 3):
#   - Марковская цепь переменного порядка (order 1..3) с бэк-оффом.
#   - Динамическое Hedge-обновление весов экспертов на основе их точности.
#   - Математический выбор хода по максимизации математического ожидания исхода (EV).
#   - Экспоненциальное сглаживание, поиск циклов, эвристическая эксплорация.
# ============================================================================

from __future__ import annotations

import math
import time
import json
import random
import logging
import asyncio
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Callable,
    Iterable,
    Sequence,
    Union,
)

logger = logging.getLogger("game_ai")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)


# ============================================================================
# КОНСТАНТЫ И КОНФИГУРАЦИЯ
# ============================================================================

# Максимальная длина хранимой истории ходов (символов) — контроль размера документа.
MAX_HISTORY_LEN = 120

# Максимальное число ключей переходов, которое храним в словарях t / t2 / t3.
MAX_TRANSITION_KEYS = 200
MAX_TRANSITION_KEYS_ORDER2 = 120
MAX_TRANSITION_KEYS_ORDER3 = 90

# Порядок марковской цепи по умолчанию.
DEFAULT_MAX_ORDER = 3

# Коэффициент экспоненциального сглаживания недавних ходов.
RECENCY_DECAY = 0.92

# Сила аддитивного сглаживания (Лапласа) для вероятностей переходов.
LAPLACE_ALPHA = 0.35

# Базовые (стартовые) веса — приор, который адаптируется Hedge-движком.
BLEND_WEIGHTS = {
    "markov3": 0.28,
    "markov2": 0.26,
    "markov1": 0.18,
    "freq":    0.12,
    "pattern": 0.16,
}

# Скорость обучения адаптивных весов (Hedge). Больше -> быстрее переобучается.
EXPERT_LEARNING_RATE = 0.9
# Минимальный/сглаживающий вес эксперта, чтобы он не «умирал» навсегда.
EXPERT_FLOOR = 0.02
# Порог EV, ниже которого включаем эксплорацию.
LOW_EV_THRESHOLD = 0.05

# Доля случайности при слабой уверенности.
EXPLORATION_EPSILON = 0.12

# Версия схемы ai_memory.
AI_MEMORY_SCHEMA_VERSION = 3


# ============================================================================
# ОПИСАНИЕ ИГРЫ (GameSpec)
# ============================================================================

@dataclass
class GameSpec:
    """Формальное описание игры для ИИ-движка."""

    key: str                                   # уникальный идентификатор игры
    name: str                                  # человекочитаемое имя
    moves: List[str]                           # алфавит допустимых ходов (символы)
    beats: Dict[str, List[str]] = field(default_factory=dict)  # кто кого бьёт
    symmetric: bool = True                     # симметрична ли игра (RPS-подобная)
    max_order: int = DEFAULT_MAX_ORDER         # макс. порядок марковской цепи

    def __post_init__(self) -> None:
        if not self.moves:
            raise ValueError("GameSpec.moves не может быть пустым")
        # Гарантируем, что все ходы — односимвольные.
        for m in self.moves:
            if len(m) != 1:
                raise ValueError(
                    f"Ход '{m}' в игре '{self.key}' должен быть односимвольным "
                    f"для компактного хранения."
                )
        # Дедуп.
        seen = set()
        uniq = []
        for m in self.moves:
            if m not in seen:
                seen.add(m)
                uniq.append(m)
        self.moves = uniq
        # Нормализуем таблицу побед.
        norm: Dict[str, List[str]] = {}
        for m in self.moves:
            norm[m] = list(self.beats.get(m, []))
        self.beats = norm

    def is_valid_move(self, move: str) -> bool:
        return move in self.moves

    def counter_move(self, predicted_player_move: str) -> str:
        """Возвращает ход ИИ, который бьёт предсказанный ход игрока."""
        for m in self.moves:
            if predicted_player_move in self.beats.get(m, []):
                return m
        return random.choice(self.moves)

    def outcome(self, ai_move: str, player_move: str) -> int:
        """+1 — победа ИИ, -1 — поражение ИИ, 0 — ничья."""
        if ai_move == player_move:
            return 0
        if player_move in self.beats.get(ai_move, []):
            return 1
        if ai_move in self.beats.get(player_move, []):
            return -1
        return 0

    def all_counters(self, predicted_player_move: str) -> List[str]:
        """Все ходы ИИ, которые бьют указанный ход игрока."""
        res = []
        for m in self.moves:
            if predicted_player_move in self.beats.get(m, []):
                res.append(m)
        return res


# ============================================================================
# РЕЕСТР ИГР
# ============================================================================

class GameRegistry:
    """Хранилище зарегистрированных GameSpec."""

    _games: Dict[str, GameSpec] = {}

    @classmethod
    def register(cls, spec: GameSpec) -> GameSpec:
        cls._games[spec.key] = spec
        logger.info("Зарегистрирована игра: %s (%s)", spec.key, spec.name)
        return spec

    @classmethod
    def get(cls, key: str) -> GameSpec:
        if key not in cls._games:
            raise KeyError(f"Игра '{key}' не зарегистрирована. Доступно: {list(cls._games)}")
        return cls._games[key]

    @classmethod
    def has(cls, key: str) -> bool:
        return key in cls._games

    @classmethod
    def all(cls) -> Dict[str, GameSpec]:
        return dict(cls._games)


# --------------------------- Предустановленные игры -------------------------

THIMBLES = GameRegistry.register(
    GameSpec(
        key="thimbles",
        name="Наперстки",
        moves=["0", "1", "2"],
        beats={},
        symmetric=False,
        max_order=3,
    )
)

RPS = GameRegistry.register(
    GameSpec(
        key="rps",
        name="Камень-Ножницы-Бумага",
        moves=["r", "s", "p"],
        beats={
            "r": ["s"],
            "s": ["p"],
            "p": ["r"],
        },
        symmetric=True,
        max_order=3,
    )
)

COINFLIP = GameRegistry.register(
    GameSpec(
        key="coinflip",
        name="Орёл-Решка",
        moves=["0", "1"],
        beats={"0": ["0"], "1": ["1"]},
        symmetric=False,
        max_order=3,
    )
)

BLACKJACK = GameRegistry.register(
    GameSpec(
        key="blackjack",
        name="Блэкджек",
        moves=["h", "s"],
        beats={},
        symmetric=False,
        max_order=3,
    )
)


# ============================================================================
# СТРУКТУРА ПАМЯТИ ИИ (AIMemory)
# ============================================================================

def default_ai_memory() -> Dict[str, Any]:
    return {
        "v": AI_MEMORY_SCHEMA_VERSION,
        "h": "",
        "t": {},
        "t2": {},
        "t3": {},
        "wts": {},          # адаптивные веса предсказателей
        "n": 0,
        "w": 0,
        "l": 0,
        "d": 0,
        "last": 0,
        "streak": 0,
        "prof": "unknown",
    }


class AIMemory:
    __slots__ = ("v", "h", "t", "t2", "t3", "wts",
                 "n", "w", "l", "d", "last", "streak", "prof")

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        data = data or default_ai_memory()
        self.v = int(data.get("v", AI_MEMORY_SCHEMA_VERSION))
        self.h = str(data.get("h", ""))
        self.t = dict(data.get("t") or {})
        self.t2 = dict(data.get("t2") or {})
        self.t3 = dict(data.get("t3") or {})
        self.wts = {k: float(v) for k, v in dict(data.get("wts") or {}).items()}
        self.n = int(data.get("n", 0))
        self.w = int(data.get("w", 0))
        self.l = int(data.get("l", 0))
        self.d = int(data.get("d", 0))
        self.last = int(data.get("last", 0))
        self.streak = int(data.get("streak", 0))
        self.prof = str(data.get("prof", "unknown"))

    @classmethod
    def from_dict(cls, data): 
        m = cls(data)
        m.migrate()
        return m

    def to_dict(self) -> Dict[str, Any]:
        return {
            "v": self.v,
            "h": self.h,
            "t": self.t,
            "t2": self.t2,
            "t3": self.t3,
            "wts": {k: round(v, 5) for k, v in self.wts.items()},
            "n": self.n,
            "w": self.w,
            "l": self.l,
            "d": self.d,
            "last": self.last,
            "streak": self.streak,
            "prof": self.prof,
        }

    def migrate(self) -> None:
        if self.v < 2:
            if not isinstance(self.t2, dict): self.t2 = {}
            if not self.prof: self.prof = "unknown"
        if self.v < 3:
            if not isinstance(self.t3, dict): self.t3 = {}
            if not isinstance(self.wts, dict): self.wts = {}
        self.v = AI_MEMORY_SCHEMA_VERSION

    def last_move(self):  return self.h[-1] if self.h else None
    def last_two(self):   return self.h[-2:] if len(self.h) >= 2 else None
    def last_three(self): return self.h[-3:] if len(self.h) >= 3 else None
    def total_games(self): return self.n
    def winrate_ai(self):  return self.w / self.n if self.n > 0 else 0.0
    def history_list(self): return list(self.h)

    def record_move(self, player_move: str) -> None:
        p1, p2, p3 = self.last_move(), self.last_two(), self.last_three()
        if p1 is not None:
            k = f"{p1}|{player_move}"; self.t[k] = self.t.get(k, 0) + 1
        if p2 and len(p2) == 2:
            k = f"{p2}|{player_move}"; self.t2[k] = self.t2.get(k, 0) + 1
        if p3 and len(p3) == 3:
            k = f"{p3}|{player_move}"; self.t3[k] = self.t3.get(k, 0) + 1
        self.h = (self.h + player_move)[-MAX_HISTORY_LEN:]
        self.n += 1
        self.last = int(time.time())
        self._trim_transitions()

    def record_outcome(self, outcome: int) -> None:
        if outcome > 0:
            self.w += 1; self.streak = self.streak + 1 if self.streak >= 0 else 1
        elif outcome < 0:
            self.l += 1; self.streak = self.streak - 1 if self.streak <= 0 else -1
        else:
            self.d += 1
            self.streak += -1 if self.streak > 0 else (1 if self.streak < 0 else 0)
        self.last = int(time.time())

    def _trim_transitions(self) -> None:
        def trim(d, cap):
            if len(d) > cap:
                return dict(sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:cap])
            return d
        self.t  = trim(self.t,  MAX_TRANSITION_KEYS)
        self.t2 = trim(self.t2, MAX_TRANSITION_KEYS_ORDER2)
        self.t3 = trim(self.t3, MAX_TRANSITION_KEYS_ORDER3)

    def estimate_document_size(self) -> int:
        return len(json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8"))


# ============================================================================
# ПРЕДСКАЗАТЕЛИ (Predictors)
# ============================================================================

class BasePredictor:
    """Базовый интерфейс предсказателя."""

    name: str = "base"

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        raise NotImplementedError

    @staticmethod
    def uniform(spec: GameSpec) -> Dict[str, float]:
        p = 1.0 / len(spec.moves)
        return {m: p for m in spec.moves}

    @staticmethod
    def normalize(dist: Dict[str, float], spec: GameSpec) -> Dict[str, float]:
        full = {m: max(0.0, dist.get(m, 0.0)) for m in spec.moves}
        s = sum(full.values())
        if s <= 0:
            return BasePredictor.uniform(spec)
        return {m: v / s for m, v in full.items()}


class MarkovPredictor(BasePredictor):
    """Марковская цепь порядка `order` с плавным бэк-оффом к младшему порядку."""

    def __init__(self, order: int, fallback: Optional["MarkovPredictor"] = None):
        self.order = order
        self.name = f"markov{order}"
        self._fallback = fallback
        self._table_attr = {1: "t", 2: "t2", 3: "t3"}[order]

    def _ctx(self, mem: AIMemory):
        return {1: mem.last_move, 2: mem.last_two, 3: mem.last_three}[self.order]()

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        ctx = self._ctx(mem)
        if ctx is None or len(ctx) < self.order:
            return self._fallback.predict(mem, spec) if self._fallback else self.uniform(spec)

        table = getattr(mem, self._table_attr)
        counts, total, observed = {}, 0.0, 0
        for m in spec.moves:
            c = table.get(f"{ctx}|{m}", 0)
            observed += c
            counts[m] = c + LAPLACE_ALPHA
            total += counts[m]

        hi = {m: c / total for m, c in counts.items()} if total > 0 else self.uniform(spec)
        if self._fallback is None:
            return hi
        # Бэк-офф: чем меньше наблюдений в этом контексте, тем сильнее доверяем младшему порядку.
        lo = self._fallback.predict(mem, spec)
        beta = min(1.0, observed / (3.0 * self.order))
        return self.normalize({m: beta * hi[m] + (1 - beta) * lo[m] for m in spec.moves}, spec)


class FrequencyPredictor(BasePredictor):
    """Глобальная частота ходов с экспоненциальным затуханием."""

    name = "freq"

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        if not mem.h:
            return self.uniform(spec)
        weights = defaultdict(float)
        n = len(mem.h)
        for i, move in enumerate(mem.h):
            w = RECENCY_DECAY ** (n - 1 - i)
            if move in spec.moves:
                weights[move] += w
        total = sum(weights.values())
        if total <= 0:
            return self.uniform(spec)
        return self.normalize({m: weights.get(m, 0.0) for m in spec.moves}, spec)


class PatternPredictor(BasePredictor):
    """Детектор повторяющихся паттернов (N-граммы)."""

    name = "pattern"

    def __init__(self, min_len: int = 2, max_len: int = 5) -> None:
        self.min_len = min_len
        self.max_len = max_len

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        h = mem.h
        if len(h) < self.min_len + 1:
            return self.uniform(spec)

        scores = defaultdict(float)
        found_any = False

        for L in range(min(self.max_len, len(h) - 1), self.min_len - 1, -1):
            suffix = h[-L:]
            weight = float(L)
            search_zone = h[:-1]
            idx = 0
            while True:
                pos = search_zone.find(suffix, idx)
                if pos == -1:
                    break
                nxt_index = pos + L
                if nxt_index < len(h):
                    nxt = h[nxt_index]
                    if nxt in spec.moves:
                        scores[nxt] += weight
                        found_any = True
                idx = pos + 1

        if not found_any:
            return self.uniform(spec)
        return self.normalize({m: scores.get(m, 0.0) for m in spec.moves}, spec)


# ============================================================================
# ПРОФИЛИРОВАНИЕ ИГРОКА
# ============================================================================

def classify_player_profile(mem: AIMemory, spec: GameSpec) -> str:
    if mem.n < 8:
        return "unknown"

    h = mem.h
    counts = Counter(h)
    most_common_move, most_common_count = counts.most_common(1)[0]
    repeat_ratio = most_common_count / len(h)

    same_as_prev = sum(1 for i in range(1, len(h)) if h[i] == h[i - 1])
    streak_ratio = same_as_prev / max(1, len(h) - 1)

    total = len(h)
    ent = 0.0
    for m in spec.moves:
        p = counts.get(m, 0) / total
        if p > 0:
            ent -= p * math.log(p, len(spec.moves) if len(spec.moves) > 1 else 2)

    if ent > 0.92:
        return "random"
    if streak_ratio > 0.55:
        return "sticky"
    if repeat_ratio > 0.55:
        return "biased"
    if ent < 0.6:
        return "predictable"
    return "balanced"


# ============================================================================
# ДВИЖОК ПРЕДСКАЗАНИЯ (GameAIEngine)
# ============================================================================

@dataclass
class Prediction:
    predicted_player_move: str
    ai_move: str
    confidence: float
    distribution: Dict[str, float]
    used_exploration: bool
    profile: str
    per_predictor: Dict[str, Dict[str, float]] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)


class GameAIEngine:
    def __init__(self, weights=None, rng=None):
        self.base_weights = dict(weights or BLEND_WEIGHTS)
        self.rng = rng or random.Random()
        m1 = MarkovPredictor(1)
        m2 = MarkovPredictor(2, fallback=m1)
        m3 = MarkovPredictor(3, fallback=m2)
        self.predictors: Dict[str, BasePredictor] = {
            "markov3": m3,
            "markov2": m2,
            "markov1": m1,
            "freq": FrequencyPredictor(),
            "pattern": PatternPredictor(),
        }

    def _effective_weights(self, mem: AIMemory) -> Dict[str, float]:
        eff = {}
        for name, base in self.base_weights.items():
            eff[name] = base * mem.wts.get(name, 1.0)
        s = sum(eff.values()) or 1.0
        return {k: v / s for k, v in eff.items()}

    def predict(self, mem: AIMemory, spec: GameSpec) -> Prediction:
        dists = {}
        for key, p in self.predictors.items():
            try:
                dists[key] = p.predict(mem, spec)
            except Exception as e:  # noqa: BLE001
                logger.warning("Предсказатель %s упал: %s", key, e)
                dists[key] = BasePredictor.uniform(spec)

        weights = self._effective_weights(mem)
        blended = self._blend(dists, weights, spec)

        # Ход ИИ выбираем по матожиданию исхода против ВСЕГО распределения.
        ai_move, best_ev = self._choose_by_ev(blended, spec)
        predicted_move, _ = self._argmax(blended, spec)

        used_exploration = False
        if best_ev < LOW_EV_THRESHOLD:
            # реально неуверенны — подмешиваем случайность
            if self.rng.random() < EXPLORATION_EPSILON:
                ai_move = self.rng.choice(spec.moves)
                used_exploration = True

        confidence = max(0.0, min(1.0, best_ev))
        profile = classify_player_profile(mem, spec)

        return Prediction(
            predicted_player_move=predicted_move,
            ai_move=ai_move,
            confidence=round(confidence, 4),
            distribution={m: round(v, 4) for m, v in blended.items()},
            used_exploration=used_exploration,
            profile=profile,
            per_predictor=dists,
            meta={"n": mem.n, "winrate_ai": round(mem.winrate_ai(), 4),
                  "streak": mem.streak, "weights": {k: round(v, 3) for k, v in weights.items()}},
        )

    def update_experts(self, mem: AIMemory, per_predictor: Dict[str, Dict[str, float]],
                       actual_move: str) -> None:
        """Hedge-обновление весов по фактическому ходу игрока."""
        for name, dist in per_predictor.items():
            reward = dist.get(actual_move, 0.0)
            w = mem.wts.get(name, 1.0) * math.exp(EXPERT_LEARNING_RATE * (reward - 0.5))
            mem.wts[name] = max(EXPERT_FLOOR, w)
        # нормализация к среднему = 1
        vals = list(mem.wts.values())
        avg = sum(vals) / len(vals) if vals else 1.0
        if avg > 0:
            mem.wts = {k: v / avg for k, v in mem.wts.items()}

    def _blend(self, dists, weights, spec):
        blended = {m: 0.0 for m in spec.moves}
        for key, dist in dists.items():
            w = weights.get(key, 0.0)
            for m in spec.moves:
                blended[m] += w * dist.get(m, 0.0)
        s = sum(blended.values())
        return {m: v / s for m, v in blended.items()} if s > 0 else BasePredictor.uniform(spec)

    def _choose_by_ev(self, dist, spec):
        best_move, best_ev = spec.moves[0], -2.0
        for ai_move in spec.moves:
            ev = sum(dist[pm] * spec.outcome(ai_move, pm) for pm in spec.moves)
            if ev > best_ev:
                best_ev, best_move = ev, ai_move
        return best_move, best_ev

    def _argmax(self, dist, spec):
        best = max(spec.moves, key=lambda m: dist.get(m, 0.0))
        return best, dist.get(best, 0.0)


# Глобальный singleton-движок.
_engine_singleton: Optional[GameAIEngine] = None


def get_engine() -> GameAIEngine:
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = GameAIEngine()
    return _engine_singleton


# ============================================================================
# ЭКСПОРТИРУЕМЫЕ ФУНКЦИИ: ОБУЧЕНИЕ И ПРОГНОЗ
# ============================================================================

def train_on_move(
    ai_memory: Optional[Dict[str, Any]],
    player_move: str,
    game_key: str,
) -> Dict[str, Any]:
    spec = GameRegistry.get(game_key)
    if not spec.is_valid_move(player_move):
        raise ValueError(f"Недопустимый ход '{player_move}' для игры '{game_key}'")

    mem = AIMemory.from_dict(ai_memory)
    mem.record_move(player_move)
    mem.prof = classify_player_profile(mem, spec)
    return mem.to_dict()


def register_outcome(
    ai_memory: Optional[Dict[str, Any]],
    outcome: int,
) -> Dict[str, Any]:
    mem = AIMemory.from_dict(ai_memory)
    mem.record_outcome(int(outcome))
    return mem.to_dict()


def predict_move(
    ai_memory: Optional[Dict[str, Any]],
    game_key: str,
) -> Dict[str, Any]:
    spec = GameRegistry.get(game_key)
    mem = AIMemory.from_dict(ai_memory)
    pred = get_engine().predict(mem, spec)
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
    spec = GameRegistry.get(game_key)
    if not spec.is_valid_move(player_move):
        raise ValueError(f"Недопустимый ход '{player_move}' для игры '{game_key}'")

    mem = AIMemory.from_dict(ai_memory)
    engine = get_engine()

    pred = engine.predict(mem, spec)
    outcome = spec.outcome(pred.ai_move, player_move)

    # hedge-обновление весов экспертов по фактическому ходу
    engine.update_experts(mem, pred.per_predictor, player_move)

    mem.record_move(player_move)
    mem.prof = classify_player_profile(mem, spec)
    mem.record_outcome(outcome)

    report = {
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
    return mem.to_dict(), report


def reset_ai_memory() -> Dict[str, Any]:
    return default_ai_memory()


def get_ai_stats(ai_memory: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    mem = AIMemory.from_dict(ai_memory)
    return {
        "total_moves": mem.n,
        "ai_wins": mem.w,
        "player_wins": mem.l,
        "draws": mem.d,
        "winrate_ai": round(mem.winrate_ai(), 4),
        "streak": mem.streak,
        "profile": mem.prof,
        "history_len": len(mem.h),
        "doc_size_bytes": mem.estimate_document_size(),
        "transition_keys": len(mem.t),
        "transition_keys_order2": len(mem.t2),
        "transition_keys_order3": len(mem.t3),
    }


# ============================================================================
# ИНТЕГРАЦИЯ С КЭШЕМ user_manager.py
# ============================================================================

class UserManagerBridge:
    def __init__(
        self,
        get_user: Callable[[Any], "asyncio.Future"],
        mark_dirty: Callable[[Any], None],
        set_user: Optional[Callable[[Any, Dict[str, Any]], None]] = None,
        memory_field: str = "ai_memory",
        lock_factory: Optional[Callable[[], "asyncio.Lock"]] = None,
    ) -> None:
        self._get_user = get_user
        self._mark_dirty = mark_dirty
        self._set_user = set_user
        self.memory_field = memory_field
        self._locks: Dict[Any, asyncio.Lock] = {}
        self._lock_factory = lock_factory or (lambda: asyncio.Lock())

    def _get_lock(self, uid: Any) -> asyncio.Lock:
        lock = self._locks.get(uid)
        if lock is None:
            lock = self._lock_factory()
            self._locks[uid] = lock
        return lock

    async def _read_memory(self, uid: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        user = await self._maybe_await(self._get_user(uid))
        if user is None:
            raise KeyError(f"Пользователь {uid} не найден в кэше/БД")
        mem = user.get(self.memory_field)
        if not isinstance(mem, dict):
            mem = default_ai_memory()
            user[self.memory_field] = mem
        return user, mem

    def _write_memory(self, uid: Any, user: Dict[str, Any], new_mem: Dict[str, Any]) -> None:
        user[self.memory_field] = new_mem
        if self._set_user is not None:
            self._set_user(uid, user)
        self._mark_dirty(uid)

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
            return await value
        return value

    async def train(self, uid: Any, game_key: str, player_move: str) -> Dict[str, Any]:
        async with self._get_lock(uid):
            user, mem = await self._read_memory(uid)
            new_mem = train_on_move(mem, player_move, game_key)
            self._write_memory(uid, user, new_mem)
            return new_mem

    async def predict(self, uid: Any, game_key: str) -> Dict[str, Any]:
        async with self._get_lock(uid):
            _user, mem = await self._read_memory(uid)
            return predict_move(mem, game_key)

    async def play(self, uid: Any, game_key: str, player_move: str) -> Dict[str, Any]:
        async with self._get_lock(uid):
            user, mem = await self._read_memory(uid)
            new_mem, report = play_round(mem, game_key, player_move)
            self._write_memory(uid, user, new_mem)
            return report

    async def register_outcome(self, uid: Any, outcome: int) -> Dict[str, Any]:
        async with self._get_lock(uid):
            user, mem = await self._read_memory(uid)
            new_mem = register_outcome(mem, outcome)
            self._write_memory(uid, user, new_mem)
            return new_mem

    async def stats(self, uid: Any) -> Dict[str, Any]:
        async with self._get_lock(uid):
            _user, mem = await self._read_memory(uid)
            return get_ai_stats(mem)

    async def reset(self, uid: Any) -> Dict[str, Any]:
        async with self._get_lock(uid):
            user, _mem = await self._read_memory(uid)
            new_mem = reset_ai_memory()
            self._write_memory(uid, user, new_mem)
            return new_mem


# ============================================================================
# ПАТЧ ДЛЯ user_manager.py
# ============================================================================

def ensure_ai_memory_field(user_doc: Dict[str, Any], field_name: str = "ai_memory") -> Dict[str, Any]:
    mem = user_doc.get(field_name)
    if not isinstance(mem, dict) or "v" not in mem:
        user_doc[field_name] = default_ai_memory()
    else:
        m = AIMemory.from_dict(mem)
        user_doc[field_name] = m.to_dict()
    return user_doc


def patch_default_user_structure(default_factory: Callable[[], Dict[str, Any]]) -> Callable[[], Dict[str, Any]]:
    def wrapper() -> Dict[str, Any]:
        doc = default_factory()
        return ensure_ai_memory_field(doc)
    return wrapper


# ============================================================================
# АДАПТЕРЫ КОНКРЕТНЫХ ИГР
# ============================================================================

class BaseGameAdapter:
    game_key: str = ""

    def __init__(self, bridge: UserManagerBridge) -> None:
        self.bridge = bridge
        self.spec = GameRegistry.get(self.game_key)

    async def ai_decide(self, uid: Any) -> Dict[str, Any]:
        return await self.bridge.predict(uid, self.game_key)

    async def resolve(self, uid: Any, player_move: str) -> Dict[str, Any]:
        return await self.bridge.play(uid, self.game_key, player_move)


class ThimblesAdapter(BaseGameAdapter):
    game_key = "thimbles"

    async def resolve(self, uid: Any, player_pick: str) -> Dict[str, Any]:
        if not self.spec.is_valid_move(player_pick):
            raise ValueError("Наперсток должен быть '0', '1' или '2'")

        pred = await self.bridge.predict(uid, self.game_key)
        predicted_pick = pred["predicted_player_move"]

        candidates = [m for m in self.spec.moves if m != predicted_pick]
        ball_position = random.choice(candidates) if candidates else random.choice(self.spec.moves)

        player_guessed = (player_pick == ball_position)
        outcome = -1 if player_guessed else 1

        await self.bridge.train(uid, self.game_key, player_pick)
        await self.bridge.register_outcome(uid, outcome)

        return {
            "game": self.game_key,
            "player_pick": player_pick,
            "ball_position": ball_position,
            "predicted_pick": predicted_pick,
            "player_won": player_guessed,
            "outcome_for_ai": outcome,
            "confidence": pred["confidence"],
            "profile": pred["profile"],
        }


class CoinflipAdapter(BaseGameAdapter):
    game_key = "coinflip"

    async def resolve(self, uid: Any, player_move: str) -> Dict[str, Any]:
        if not self.spec.is_valid_move(player_move):
            raise ValueError("Ход должен быть '0' или '1'")

        pred = await self.bridge.predict(uid, self.game_key)
        ai_guess = pred["predicted_player_move"]

        ai_correct = (ai_guess == player_move)
        outcome = 1 if ai_correct else -1

        await self.bridge.train(uid, self.game_key, player_move)
        await self.bridge.register_outcome(uid, outcome)

        return {
            "game": self.game_key,
            "player_move": player_move,
            "ai_guess": ai_guess,
            "ai_correct": ai_correct,
            "outcome_for_ai": outcome,
            "confidence": pred["confidence"],
            "profile": pred["profile"],
        }


class RPSAdapter(BaseGameAdapter):
    game_key = "rps"

    async def resolve(self, uid: Any, player_move: str) -> Dict[str, Any]:
        report = await self.bridge.play(uid, self.game_key, player_move)
        report["game"] = self.game_key
        return report


ADAPTERS: Dict[str, type] = {
    "thimbles": ThimblesAdapter,
    "coinflip": CoinflipAdapter,
    "rps": RPSAdapter,
}


def build_adapter(game_key: str, bridge: UserManagerBridge) -> BaseGameAdapter:
    if game_key not in ADAPTERS:
        raise KeyError(f"Нет адаптера для игры '{game_key}'. Доступно: {list(ADAPTERS)}")
    return ADAPTERS[game_key](bridge)


# ============================================================================
# ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ / САМОПРОВЕРКА (без Firestore)
# ============================================================================

class _FakeUserManager:
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


def _simulate(game_key: str, player_strategy: Callable[[List[str], GameSpec], str], rounds: int = 300) -> None:
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
        stats = await bridge.stats(uid)
        print(f"\n=== Игра: {spec.name} ({game_key}) | стратегия игрока ===")
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    asyncio.run(run())


def _strategy_cyclic(history: List[str], spec: GameSpec) -> str:
    return spec.moves[len(history) % len(spec.moves)]


def _strategy_biased(history: List[str], spec: GameSpec) -> str:
    if random.random() < 0.7:
        return spec.moves[0]
    return random.choice(spec.moves)


def _strategy_random(history: List[str], spec: GameSpec) -> str:
    return random.choice(spec.moves)


def _strategy_sticky(history: List[str], spec: GameSpec) -> str:
    if history and random.random() < 0.75:
        return history[-1]
    return random.choice(spec.moves)


if __name__ == "__main__":
    print(">>> Демонстрация движка предсказания game_ai.py (Версия 3)\n")

    for strat_name, strat in [
        ("cyclic", _strategy_cyclic),
        ("biased", _strategy_biased),
        ("sticky", _strategy_sticky),
        ("random", _strategy_random),
    ]:
        print(f"\n########## Стратегия игрока: {strat_name} ##########")
        _simulate("rps", strat, rounds=400)

    print("\n>>> Наперстки:")
    _simulate("thimbles", _strategy_cyclic, rounds=300)

    print("\n>>> Coinflip:")
    _simulate("coinflip", _strategy_sticky, rounds=300)
