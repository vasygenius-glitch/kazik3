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
# Модель предсказания:
#   - Марковская цепь переменного порядка (order 1..N) с бэк-оффом.
#   - Частотный анализ, детектор паттернов, антиповторный эвристический слой.
#   - Экспоненциальное сглаживание (недавние ходы весомее старых).
#   - Контр-стратегия: система предсказывает ход игрока и выбирает ход,
#     который его "бьёт" по заданной таблице побед конкретной игры.
#
# Формат ai_memory (компактный, укладывается в лимиты Firestore):
#   {
#     "v": 2,                       # версия схемы
#     "h": "10212010",              # история ходов (строка символов-алфавита)
#     "t": {"1|0": 12, "0|2": 3},   # счётчики переходов order-1 (плоский словарь)
#     "t2": {"10|2": 4},            # счётчики переходов order-2 (опционально)
#     "n": 42,                      # всего сыгранных ходов
#     "w": 20,                      # побед ИИ
#     "l": 15,                      # поражений ИИ
#     "d": 7,                       # ничьих
#     "last": 1700000000,           # ts последнего обновления
#     "streak": 3,                  # текущая серия (знак = чья серия)
#     "prof": "aggressive"          # предполагаемый профиль игрока
#   }
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

# Максимальное число ключей переходов, которое храним в словарях t / t2.
# Если превышаем — «обрезаем» самые редкие ключи, чтобы не раздувать документ.
MAX_TRANSITION_KEYS = 200
MAX_TRANSITION_KEYS_ORDER2 = 120

# Максимальный порядок марковской цепи, который используется по умолчанию.
DEFAULT_MAX_ORDER = 2

# Коэффициент экспоненциального сглаживания недавних ходов.
# Чем ближе к 1.0 — тем «длиннее память»; чем меньше — тем важнее свежие ходы.
RECENCY_DECAY = 0.92

# Сила аддитивного сглаживания (Лапласа) для вероятностей переходов.
LAPLACE_ALPHA = 0.35

# Веса источников предсказания при смешивании (blend).
BLEND_WEIGHTS = {
    "markov2": 0.45,   # марковская цепь порядка 2
    "markov1": 0.30,   # марковская цепь порядка 1
    "freq": 0.15,      # глобальная частота ходов
    "pattern": 0.10,   # детектор повторяющихся паттернов
}

# Порог уверенности, ниже которого система считает предсказание "слабым"
# и добавляет элемент случайности (эксплорация), чтобы не быть предсказуемой.
LOW_CONFIDENCE_THRESHOLD = 0.40

# Доля случайности при слабой уверенности.
EXPLORATION_EPSILON = 0.12

# Версия схемы ai_memory.
AI_MEMORY_SCHEMA_VERSION = 2


# ============================================================================
# ОПИСАНИЕ ИГРЫ (GameSpec)
# ----------------------------------------------------------------------------
# Каждая игра описывается набором допустимых ходов (алфавит) и таблицей побед:
# beats[move] -> множество ходов, которые данный ход побеждает.
# Это позволяет ИИ, предсказав ход игрока, выбрать контр-ход.
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
        # Гарантируем, что все ходы — односимвольные (для компактной строки истории).
        for m in self.moves:
            if len(m) != 1:
                raise ValueError(
                    f"Ход '{m}' в игре '{self.key}' должен быть односимвольным "
                    f"для компактного хранения. Используйте алфавит из 1 символа."
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

    # ------------------------------------------------------------------ util
    def is_valid_move(self, move: str) -> bool:
        return move in self.moves

    def counter_move(self, predicted_player_move: str) -> str:
        """
        Возвращает ход ИИ, который бьёт предсказанный ход игрока.
        Если такого нет (или игра не симметрична) — возвращает случайный ход.
        """
        for m in self.moves:
            if predicted_player_move in self.beats.get(m, []):
                return m
        return random.choice(self.moves)

    def outcome(self, ai_move: str, player_move: str) -> int:
        """
        Определяет исход раунда с точки зрения ИИ.
        Возвращает: +1 — победа ИИ, -1 — поражение ИИ, 0 — ничья.
        """
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
# ----------------------------------------------------------------------------
# Здесь регистрируются конкретные игры. Пока предзаданы «болванки», которые
# легко заменить/дополнить под финальный выбор (наперстки, блэкджек и т.д.).
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

# 1) Наперстки (Thimbles): игрок выбирает наперсток 0/1/2, ИИ прячет шарик.
#    Ходы игрока — куда он ткнёт; ИИ хочет спрятать шарик там, куда игрок НЕ ткнёт.
#    Здесь "beats" интерпретируется иначе — логика контр-хода задаётся в адаптере игры.
THIMBLES = GameRegistry.register(
    GameSpec(
        key="thimbles",
        name="Наперстки",
        moves=["0", "1", "2"],
        beats={},           # для наперстков контр-логика особая (см. адаптер ниже)
        symmetric=False,
        max_order=2,
    )
)

# 2) Камень-ножницы-бумага (демо симметричной игры для теста движка).
RPS = GameRegistry.register(
    GameSpec(
        key="rps",
        name="Камень-Ножницы-Бумага",
        moves=["r", "s", "p"],   # rock, scissors, paper
        beats={
            "r": ["s"],          # камень бьёт ножницы
            "s": ["p"],          # ножницы бьют бумагу
            "p": ["r"],          # бумага бьёт камень
        },
        symmetric=True,
        max_order=2,
    )
)

# 3) Чёт-нечет / орёл-решка (бинарная игра для быстрого прогнозирования).
COINFLIP = GameRegistry.register(
    GameSpec(
        key="coinflip",
        name="Орёл-Решка",
        moves=["0", "1"],
        beats={"0": ["0"], "1": ["1"]},  # ИИ "угадывает" -> совпадение = победа ИИ
        symmetric=False,
        max_order=2,
    )
)

# 4) Блэкджек (Blackjack): игрок выбирает взять карту ('h' - hit) или остановиться ('s' - stand).
BLACKJACK = GameRegistry.register(
    GameSpec(
        key="blackjack",
        name="Блэкджек",
        moves=["h", "s"],  # 'h' - hit, 's' - stand
        beats={},          # несимметричная
        symmetric=False,
        max_order=2,
    )
)



# ============================================================================
# СТРУКТУРА ПАМЯТИ ИИ (AIMemory)
# ----------------------------------------------------------------------------
# Обёртка над плоским словарём ai_memory, который лежит внутри документа юзера.
# Отвечает за сериализацию/десериализацию, обрезку размеров и обновление.
# ============================================================================

def default_ai_memory() -> Dict[str, Any]:
    """
    Возвращает дефолтную структуру ai_memory для нового пользователя.
    Именно её нужно добавить в дефолтный документ user_manager.py.
    """
    return {
        "v": AI_MEMORY_SCHEMA_VERSION,
        "h": "",             # история ходов (строка)
        "t": {},             # переходы order-1: "prev|cur" -> count
        "t2": {},            # переходы order-2: "p2p1|cur" -> count
        "n": 0,              # всего ходов
        "w": 0,              # победы ИИ
        "l": 0,              # поражения ИИ
        "d": 0,              # ничьи
        "last": 0,           # ts последнего обновления
        "streak": 0,         # текущая серия (>0 серия ИИ, <0 серия игрока)
        "prof": "unknown",   # профиль игрока
    }


class AIMemory:
    """
    Объектная обёртка над ai_memory-словарём.

    ВАЖНО: этот объект работает ТОЛЬКО в оперативной памяти. Сохранение в
    Firestore обеспечивается механизмом mark_dirty()+background flush внутри
    user_manager.py. Сам AIMemory в БД не пишет.
    """

    __slots__ = ("v", "h", "t", "t2", "n", "w", "l", "d", "last", "streak", "prof")

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        data = data or default_ai_memory()
        self.v: int = int(data.get("v", AI_MEMORY_SCHEMA_VERSION))
        self.h: str = str(data.get("h", ""))
        self.t: Dict[str, int] = dict(data.get("t", {}))
        self.t2: Dict[str, int] = dict(data.get("t2", {}))
        self.n: int = int(data.get("n", 0))
        self.w: int = int(data.get("w", 0))
        self.l: int = int(data.get("l", 0))
        self.d: int = int(data.get("d", 0))
        self.last: int = int(data.get("last", 0))
        self.streak: int = int(data.get("streak", 0))
        self.prof: str = str(data.get("prof", "unknown"))

    # --------------------------------------------------------------- factory
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AIMemory":
        mem = cls(data)
        mem.migrate()
        return mem

    def to_dict(self) -> Dict[str, Any]:
        """Компактная сериализация обратно в поле ai_memory документа."""
        return {
            "v": self.v,
            "h": self.h,
            "t": self.t,
            "t2": self.t2,
            "n": self.n,
            "w": self.w,
            "l": self.l,
            "d": self.d,
            "last": self.last,
            "streak": self.streak,
            "prof": self.prof,
        }

    # --------------------------------------------------------------- migrate
    def migrate(self) -> None:
        """Миграция старых версий схемы к текущей."""
        if self.v < 2:
            # v1 -> v2: добавили t2 (order-2) и prof.
            if not isinstance(self.t2, dict):
                self.t2 = {}
            if not self.prof:
                self.prof = "unknown"
            self.v = AI_MEMORY_SCHEMA_VERSION

    # ----------------------------------------------------------------- utils
    def history_list(self) -> List[str]:
        return list(self.h)

    def last_move(self) -> Optional[str]:
        return self.h[-1] if self.h else None

    def last_two(self) -> Optional[str]:
        return self.h[-2:] if len(self.h) >= 2 else None

    def total_games(self) -> int:
        return self.n

    def winrate_ai(self) -> float:
        if self.n <= 0:
            return 0.0
        return self.w / self.n

    # ------------------------------------------------------------- обновление
    def record_move(self, player_move: str) -> None:
        """
        Регистрирует новый ход игрока: обновляет историю и счётчики переходов.
        НЕ пишет в БД — только меняет объект в памяти.
        """
        prev1 = self.last_move()
        prev2 = self.last_two()

        # order-1
        if prev1 is not None:
            key1 = f"{prev1}|{player_move}"
            self.t[key1] = self.t.get(key1, 0) + 1

        # order-2
        if prev2 is not None and len(prev2) == 2:
            key2 = f"{prev2}|{player_move}"
            self.t2[key2] = self.t2.get(key2, 0) + 1

        # история
        self.h += player_move
        if len(self.h) > MAX_HISTORY_LEN:
            self.h = self.h[-MAX_HISTORY_LEN:]

        self.n += 1
        self.last = int(time.time())

        # контроль размеров словарей
        self._trim_transitions()

    def record_outcome(self, outcome: int) -> None:
        """
        Регистрирует исход раунда с точки зрения ИИ:
        +1 победа ИИ, -1 поражение, 0 ничья. Обновляет серии.
        """
        if outcome > 0:
            self.w += 1
            self.streak = self.streak + 1 if self.streak >= 0 else 1
        elif outcome < 0:
            self.l += 1
            self.streak = self.streak - 1 if self.streak <= 0 else -1
        else:
            self.d += 1
            # ничья серию не сбрасывает жёстко, но затухает к нулю
            if self.streak > 0:
                self.streak -= 1
            elif self.streak < 0:
                self.streak += 1
        self.last = int(time.time())

    def _trim_transitions(self) -> None:
        """Если словари переходов раздулись — оставляем только самые частые ключи."""
        if len(self.t) > MAX_TRANSITION_KEYS:
            top = sorted(self.t.items(), key=lambda kv: kv[1], reverse=True)[:MAX_TRANSITION_KEYS]
            self.t = dict(top)
        if len(self.t2) > MAX_TRANSITION_KEYS_ORDER2:
            top2 = sorted(self.t2.items(), key=lambda kv: kv[1], reverse=True)[:MAX_TRANSITION_KEYS_ORDER2]
            self.t2 = dict(top2)

    def estimate_document_size(self) -> int:
        """Грубая оценка размера сериализованного ai_memory в байтах."""
        return len(json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8"))


# ============================================================================
# ПРЕДСКАЗАТЕЛИ (Predictors)
# ----------------------------------------------------------------------------
# Каждый предсказатель отдаёт распределение вероятностей по следующему ходу
# игрока в виде dict[move] -> prob. Затем движок смешивает их с весами.
# ============================================================================

class BasePredictor:
    """Базовый интерфейс предсказателя."""

    name: str = "base"

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        raise NotImplementedError

    # ------------------------------------------------------------ helper
    @staticmethod
    def uniform(spec: GameSpec) -> Dict[str, float]:
        p = 1.0 / len(spec.moves)
        return {m: p for m in spec.moves}

    @staticmethod
    def normalize(dist: Dict[str, float], spec: GameSpec) -> Dict[str, float]:
        # гарантируем присутствие всех ходов
        full = {m: max(0.0, dist.get(m, 0.0)) for m in spec.moves}
        s = sum(full.values())
        if s <= 0:
            return BasePredictor.uniform(spec)
        return {m: v / s for m, v in full.items()}


class MarkovOrder1Predictor(BasePredictor):
    """Марковская цепь порядка 1 с аддитивным сглаживанием."""

    name = "markov1"

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        prev = mem.last_move()
        if prev is None:
            return self.uniform(spec)
        counts = {}
        total = 0.0
        for m in spec.moves:
            c = mem.t.get(f"{prev}|{m}", 0) + LAPLACE_ALPHA
            counts[m] = c
            total += c
        if total <= 0:
            return self.uniform(spec)
        return {m: c / total for m, c in counts.items()}


class MarkovOrder2Predictor(BasePredictor):
    """Марковская цепь порядка 2 с бэк-оффом к order-1 при нехватке данных."""

    name = "markov2"

    def __init__(self) -> None:
        self._fallback = MarkovOrder1Predictor()

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        ctx = mem.last_two()
        if ctx is None or len(ctx) < 2:
            return self._fallback.predict(mem, spec)

        counts = {}
        total = 0.0
        observed = 0
        for m in spec.moves:
            c = mem.t2.get(f"{ctx}|{m}", 0)
            observed += c
            c += LAPLACE_ALPHA
            counts[m] = c
            total += c

        # Если по контексту order-2 почти нет наблюдений — используем order-1.
        if observed < 3:
            o1 = self._fallback.predict(mem, spec)
            o2 = {m: c / total for m, c in counts.items()} if total > 0 else self.uniform(spec)
            # линейное смешивание с бэк-оффом
            beta = min(1.0, observed / 3.0)
            return self.normalize(
                {m: beta * o2[m] + (1 - beta) * o1[m] for m in spec.moves}, spec
            )

        return {m: c / total for m, c in counts.items()}


class FrequencyPredictor(BasePredictor):
    """
    Глобальная частота ходов с экспоненциальным затуханием:
    недавние ходы важнее старых.
    """

    name = "freq"

    def predict(self, mem: AIMemory, spec: GameSpec) -> Dict[str, float]:
        if not mem.h:
            return self.uniform(spec)
        weights = defaultdict(float)
        n = len(mem.h)
        for i, move in enumerate(mem.h):
            # чем свежее ход (больше i), тем больше вес
            w = RECENCY_DECAY ** (n - 1 - i)
            if move in spec.moves:
                weights[move] += w
        total = sum(weights.values())
        if total <= 0:
            return self.uniform(spec)
        return self.normalize({m: weights.get(m, 0.0) for m in spec.moves}, spec)


class PatternPredictor(BasePredictor):
    """
    Детектор повторяющихся паттернов: ищет последний суффикс истории среди
    прошлых вхождений и смотрит, какой ход следовал за ним.
    Позволяет ловить циклы вида "012012012" или "aabbaabb".
    """

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

        # Пробуем суффиксы разной длины; длинные совпадения ценнее.
        for L in range(min(self.max_len, len(h) - 1), self.min_len - 1, -1):
            suffix = h[-L:]
            weight = float(L)  # длинный паттерн — выше вес
            # ищем все прошлые вхождения suffix, кроме самого хвоста
            search_zone = h[:-1]  # чтобы не поймать сам себя целиком
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
# ----------------------------------------------------------------------------
# Простейший классификатор поведения: агрессивный/осторожный/повторяющийся/
# случайный. Используется только для аналитики и лёгкой подстройки стратегии.
# ============================================================================

def classify_player_profile(mem: AIMemory, spec: GameSpec) -> str:
    if mem.n < 8:
        return "unknown"

    h = mem.h
    # 1) склонность к повтору одного и того же хода
    counts = Counter(h)
    most_common_move, most_common_count = counts.most_common(1)[0]
    repeat_ratio = most_common_count / len(h)

    # 2) склонность повторять предыдущий ход подряд
    same_as_prev = sum(1 for i in range(1, len(h)) if h[i] == h[i - 1])
    streak_ratio = same_as_prev / max(1, len(h) - 1)

    # 3) энтропия распределения ходов (мера случайности)
    total = len(h)
    ent = 0.0
    for m in spec.moves:
        p = counts.get(m, 0) / total
        if p > 0:
            ent -= p * math.log(p, len(spec.moves) if len(spec.moves) > 1 else 2)
    # ent в [0,1]: 1 — максимально случайно

    if ent > 0.92:
        return "random"
    if streak_ratio > 0.55:
        return "sticky"        # часто повторяет один и тот же ход подряд
    if repeat_ratio > 0.55:
        return "biased"        # явно любимый ход
    if ent < 0.6:
        return "predictable"
    return "balanced"


# ============================================================================
# ДВИЖОК ПРЕДСКАЗАНИЯ (GameAIEngine)
# ----------------------------------------------------------------------------
# Смешивает предсказатели, применяет эксплорацию и выбирает контр-ход.
# ============================================================================

@dataclass
class Prediction:
    """Результат работы движка."""

    predicted_player_move: str          # наиболее вероятный ход игрока
    ai_move: str                        # выбранный ход ИИ (контр-ход)
    confidence: float                   # уверенность [0..1]
    distribution: Dict[str, float]      # итоговое распределение по ходам игрока
    used_exploration: bool              # была ли применена случайность
    profile: str                        # профиль игрока
    meta: Dict[str, Any] = field(default_factory=dict)


class GameAIEngine:
    """
    Основной движок. Объединяет предсказатели и выдаёт итоговое решение.
    Хранит предсказатели, не хранит состояние конкретного игрока (оно в AIMemory).
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
        }

    # --------------------------------------------------------------- predict
    def predict(self, mem: AIMemory, spec: GameSpec) -> Prediction:
        """
        Главный метод предсказания. Возвращает Prediction с ходом ИИ.
        """
        # 1) Собираем распределения от всех предсказателей.
        dists: Dict[str, Dict[str, float]] = {}
        for key, predictor in self.predictors.items():
            try:
                dists[key] = predictor.predict(mem, spec)
            except Exception as e:  # noqa: BLE001
                logger.warning("Предсказатель %s упал: %s", key, e)
                dists[key] = BasePredictor.uniform(spec)

        # 2) Смешиваем с весами.
        blended = self._blend(dists, spec)

        # 3) Определяем наиболее вероятный ход игрока и уверенность.
        predicted_move, confidence = self._argmax_conf(blended, spec)

        # 4) Эксплорация: если уверенность низкая, иногда действуем случайно,
        #    чтобы ИИ сам не стал предсказуемым.
        used_exploration = False
        ai_move = self._choose_counter(predicted_move, spec)
        if confidence < self.low_conf_threshold and self.rng.random() < self.exploration_epsilon:
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
                "streak": mem.streak,
                "per_predictor": {
                    k: {mm: round(pp, 3) for mm, pp in v.items()} for k, v in dists.items()
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
        # нормализация
        s = sum(blended.values())
        if s <= 0:
            return BasePredictor.uniform(spec)
        return {m: v / s for m, v in blended.items()}

    def _argmax_conf(self, dist: Dict[str, float], spec: GameSpec) -> Tuple[str, float]:
        best_move = spec.moves[0]
        best_p = -1.0
        for m in spec.moves:
            p = dist.get(m, 0.0)
            if p > best_p:
                best_p = p
                best_move = m
        # уверенность = отрыв лидера от равномерного распределения (нормированный)
        uniform_p = 1.0 / len(spec.moves)
        confidence = (best_p - uniform_p) / (1.0 - uniform_p) if len(spec.moves) > 1 else best_p
        confidence = max(0.0, min(1.0, confidence))
        return best_move, confidence

    def _choose_counter(self, predicted_player_move: str, spec: GameSpec) -> str:
        counters = spec.all_counters(predicted_player_move)
        if counters:
            return self.rng.choice(counters)
        # если игра не описывает "кто кого бьёт" — вернём предсказанный ход
        # (используется адаптерами игр вроде наперстков/coinflip).
        return predicted_player_move


# Глобальный singleton-движок (можно переопределить при необходимости).
_engine_singleton: Optional[GameAIEngine] = None


def get_engine() -> GameAIEngine:
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = GameAIEngine()
    return _engine_singleton


# ============================================================================
# ЭКСПОРТИРУЕМЫЕ ФУНКЦИИ: ОБУЧЕНИЕ И ПРОГНОЗ
# ----------------------------------------------------------------------------
# Это высокоуровневый API, который вызывает игровой код бота. Функции работают
# с сырым dict ai_memory (как он лежит в кэше user_manager.py) и возвращают
# обновлённый dict — который затем нужно положить обратно в кэш + mark_dirty().
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
    :return: обновлённый dict ai_memory для записи обратно в кэш.
    """
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
    """
    Регистрирует исход раунда (для статистики и серий).
    :param outcome: +1 победа ИИ, -1 поражение, 0 ничья.
    """
    mem = AIMemory.from_dict(ai_memory)
    mem.record_outcome(int(outcome))
    return mem.to_dict()


def predict_move(
    ai_memory: Optional[Dict[str, Any]],
    game_key: str,
) -> Dict[str, Any]:
    """
    Прогнозирует ход игрока и выбирает ход ИИ.

    :return: dict с полями:
        {
          "predicted_player_move": "...",
          "ai_move": "...",
          "confidence": 0.0..1.0,
          "distribution": {...},
          "used_exploration": bool,
          "profile": "...",
          "meta": {...}
        }
    """
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
    """
    Полный цикл раунда «в один вызов»:
      1) предсказать ход игрока и выбрать ход ИИ (ДО того как учтём этот ход);
      2) вычислить исход;
      3) обучиться на фактическом ходе игрока;
      4) зарегистрировать исход.

    :return: (обновлённый ai_memory, отчёт о раунде)

    Использование в игровом коде:
        new_mem, report = play_round(user["ai_memory"], "rps", player_move)
        user["ai_memory"] = new_mem
        user_manager.mark_dirty(uid)     # фоновый flush сам сохранит
    """
    spec = GameRegistry.get(game_key)
    if not spec.is_valid_move(player_move):
        raise ValueError(f"Недопустимый ход '{player_move}' для игры '{game_key}'")

    mem = AIMemory.from_dict(ai_memory)

    # 1) предсказание ДО учёта нового хода
    pred = get_engine().predict(mem, spec)

    # 2) исход
    outcome = spec.outcome(pred.ai_move, player_move)

    # 3) обучение на фактическом ходе
    mem.record_move(player_move)
    mem.prof = classify_player_profile(mem, spec)

    # 4) регистрация исхода
    mem.record_outcome(outcome)

    report = {
        "ai_move": pred.ai_move,
        "player_move": player_move,
        "predicted_player_move": pred.predicted_player_move,
        "outcome": outcome,  # +1 ИИ выиграл, -1 проиграл, 0 ничья
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
    """Сброс памяти ИИ (например, по команде игрока «начать заново»)."""
    return default_ai_memory()


def get_ai_stats(ai_memory: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Возвращает читаемую статистику по памяти ИИ конкретного игрока."""
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
    }


# ============================================================================
# ИНТЕГРАЦИЯ С КЭШЕМ user_manager.py
# ----------------------------------------------------------------------------
# Ниже — тонкий асинхронный слой-адаптер, который связывает game_ai с вашим
# user_manager (LRU-кэш + mark_dirty + фоновый flush). Он НЕ пишет в Firestore
# напрямую: только читает пользователя из кэша, меняет ai_memory в памяти и
# помечает документ грязным. Реальное сохранение делает фоновый flush.
#
# Ожидаемый интерфейс user_manager (адаптируйте имена под ваш модуль):
#   async def get_user(uid) -> dict          # берёт из кэша (или БД -> кэш)
#   def mark_dirty(uid) -> None               # помечает грязным для flush
#   (опционально) def set_user(uid, data)     # обновляет запись в кэше
# ============================================================================

class UserManagerBridge:
    """
    Мост между game_ai и user_manager. Инкапсулирует чтение/запись поля
    ai_memory внутри документа пользователя, соблюдая правило:
    менять в памяти -> mark_dirty -> фоновый flush сохранит.
    """

    def __init__(
        self,
        get_user: Callable[[Any], "asyncio.Future"],
        mark_dirty: Callable[[Any], None],
        set_user: Optional[Callable[[Any, Dict[str, Any]], None]] = None,
        memory_field: str = "ai_memory",
        lock_factory: Optional[Callable[[], "asyncio.Lock"]] = None,
    ) -> None:
        """
        :param get_user: async-функция получения документа пользователя из кэша.
        :param mark_dirty: функция пометки пользователя «грязным».
        :param set_user: (опц.) функция обновления документа в кэше целиком.
        :param memory_field: имя поля памяти ИИ в документе.
        :param lock_factory: (опц.) фабрика asyncio.Lock для защиты от гонок.
        """
        self._get_user = get_user
        self._mark_dirty = mark_dirty
        self._set_user = set_user
        self.memory_field = memory_field
        self._locks: Dict[Any, asyncio.Lock] = {}
        self._lock_factory = lock_factory or (lambda: asyncio.Lock())

    # ------------------------------------------------------------- locking
    def _get_lock(self, uid: Any) -> asyncio.Lock:
        lock = self._locks.get(uid)
        if lock is None:
            lock = self._lock_factory()
            self._locks[uid] = lock
        return lock

    # ------------------------------------------------------------- reading
    async def _read_memory(self, uid: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Возвращает (user_doc, ai_memory_dict). Гарантирует наличие поля."""
        user = await self._maybe_await(self._get_user(uid))
        if user is None:
            raise KeyError(f"Пользователь {uid} не найден в кэше/БД")
        mem = user.get(self.memory_field)
        if not isinstance(mem, dict):
            mem = default_ai_memory()
            user[self.memory_field] = mem
        return user, mem

    def _write_memory(self, uid: Any, user: Dict[str, Any], new_mem: Dict[str, Any]) -> None:
        """Пишет ai_memory обратно В КЭШ и помечает грязным (без записи в БД!)."""
        user[self.memory_field] = new_mem
        if self._set_user is not None:
            self._set_user(uid, user)
        self._mark_dirty(uid)  # фоновый flush сам сохранит пакетом в Firestore

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
            return await value
        return value

    # --------------------------------------------------------- public API
    async def train(self, uid: Any, game_key: str, player_move: str) -> Dict[str, Any]:
        """Обучение на одном ходе игрока (в памяти + mark_dirty)."""
        async with self._get_lock(uid):
            user, mem = await self._read_memory(uid)
            new_mem = train_on_move(mem, player_move, game_key)
            self._write_memory(uid, user, new_mem)
            return new_mem

    async def predict(self, uid: Any, game_key: str) -> Dict[str, Any]:
        """Прогноз хода игрока и хода ИИ (чтение из кэша, без записи)."""
        async with self._get_lock(uid):
            _user, mem = await self._read_memory(uid)
            return predict_move(mem, game_key)

    async def play(self, uid: Any, game_key: str, player_move: str) -> Dict[str, Any]:
        """
        Полный раунд: предсказать -> сыграть -> обучиться -> сохранить в кэш.
        Возвращает отчёт о раунде. Данные уедут в Firestore фоновым flush'ем.
        """
        async with self._get_lock(uid):
            user, mem = await self._read_memory(uid)
            new_mem, report = play_round(mem, game_key, player_move)
            self._write_memory(uid, user, new_mem)
            return report

    async def register_outcome(self, uid: Any, outcome: int) -> Dict[str, Any]:
        """Отдельная регистрация исхода (если раунд считается вне play())."""
        async with self._get_lock(uid):
            user, mem = await self._read_memory(uid)
            new_mem = register_outcome(mem, outcome)
            self._write_memory(uid, user, new_mem)
            return new_mem

    async def stats(self, uid: Any) -> Dict[str, Any]:
        """Статистика памяти ИИ игрока."""
        async with self._get_lock(uid):
            _user, mem = await self._read_memory(uid)
            return get_ai_stats(mem)

    async def reset(self, uid: Any) -> Dict[str, Any]:
        """Сброс памяти ИИ игрока (в памяти + mark_dirty)."""
        async with self._get_lock(uid):
            user, _mem = await self._read_memory(uid)
            new_mem = reset_ai_memory()
            self._write_memory(uid, user, new_mem)
            return new_mem


# ============================================================================
# ПАТЧ ДЛЯ user_manager.py: ДЕФОЛТНАЯ СТРУКТУРА ПОЛЬЗОВАТЕЛЯ
# ----------------------------------------------------------------------------
# Вызовите ensure_ai_memory_field(default_user_dict) внутри функции создания
# нового пользователя в user_manager.py, чтобы гарантированно добавить поле.
# ============================================================================

def ensure_ai_memory_field(user_doc: Dict[str, Any], field_name: str = "ai_memory") -> Dict[str, Any]:
    """
    Гарантирует наличие корректного поля ai_memory в документе пользователя.
    Идемпотентна: не перетирает существующую валидную память.
    """
    mem = user_doc.get(field_name)
    if not isinstance(mem, dict) or "v" not in mem:
        user_doc[field_name] = default_ai_memory()
    else:
        # мягкая миграция при необходимости
        m = AIMemory.from_dict(mem)
        user_doc[field_name] = m.to_dict()
    return user_doc


def patch_default_user_structure(default_factory: Callable[[], Dict[str, Any]]) -> Callable[[], Dict[str, Any]]:
    """
    Оборачивает вашу функцию создания дефолтного пользователя так, чтобы поле
    ai_memory всегда присутствовало.

    Пример в user_manager.py:
        _make_default_user = patch_default_user_structure(_make_default_user)
    """
    def wrapper() -> Dict[str, Any]:
        doc = default_factory()
        return ensure_ai_memory_field(doc)
    return wrapper


# ============================================================================
# АДАПТЕРЫ КОНКРЕТНЫХ ИГР (готовые «розетки» под будущий выбор)
# ----------------------------------------------------------------------------
# Когда вы выберете финальную игру, будет достаточно доработать соответствующий
# адаптер. Ниже показаны шаблоны для наперстков и coinflip, где логика победы
# отличается от симметричной RPS.
# ============================================================================

class BaseGameAdapter:
    """Базовый адаптер игры: связывает игровую механику с движком предсказания."""

    game_key: str = ""

    def __init__(self, bridge: UserManagerBridge) -> None:
        self.bridge = bridge
        self.spec = GameRegistry.get(self.game_key)

    async def ai_decide(self, uid: Any) -> Dict[str, Any]:
        """Возвращает решение ИИ (без изменения статистики)."""
        return await self.bridge.predict(uid, self.game_key)

    async def resolve(self, uid: Any, player_move: str) -> Dict[str, Any]:
        """Разрешает раунд полностью (переопределяется при особой механике)."""
        return await self.bridge.play(uid, self.game_key, player_move)


class ThimblesAdapter(BaseGameAdapter):
    """
    Наперстки. Игрок выбирает наперсток 0/1/2. ИИ прячет шарик так, чтобы игрок
    НЕ угадал. Значит ИИ прогнозирует ход игрока и прячет шарик В ДРУГОМ месте.
    """

    game_key = "thimbles"

    async def resolve(self, uid: Any, player_pick: str) -> Dict[str, Any]:
        if not self.spec.is_valid_move(player_pick):
            raise ValueError("Наперсток должен быть '0', '1' или '2'")

        # 1) прогнозируем, какой наперсток выберет игрок
        pred = await self.bridge.predict(uid, self.game_key)
        predicted_pick = pred["predicted_player_move"]

        # 2) ИИ прячет шарик там, где игрок (по прогнозу) НЕ выберет
        candidates = [m for m in self.spec.moves if m != predicted_pick]
        ball_position = random.choice(candidates) if candidates else random.choice(self.spec.moves)

        # 3) исход: игрок выигрывает, если угадал позицию шарика
        player_guessed = (player_pick == ball_position)
        outcome = -1 if player_guessed else 1  # с точки зрения ИИ

        # 4) обучаемся на фактическом выборе игрока и фиксируем исход
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
    """
    Орёл-решка. Игрок выбирает 0/1, ИИ пытается угадать выбор игрока.
    ИИ «выигрывает», если предсказал верно.
    """

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
    """Камень-ножницы-бумага — прямое использование симметричной механики движка."""

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
    """Фабрика адаптеров игр."""
    if game_key not in ADAPTERS:
        raise KeyError(f"Нет адаптера для игры '{game_key}'. Доступно: {list(ADAPTERS)}")
    return ADAPTERS[game_key](bridge)


# ============================================================================
# ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ / САМОПРОВЕРКА (без Firestore)
# ----------------------------------------------------------------------------
# Позволяет проверить движок офлайн, симулируя игрока с разными паттернами.
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


def _simulate(game_key: str, player_strategy: Callable[[List[str], GameSpec], str], rounds: int = 300) -> None:
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
        stats = await bridge.stats(uid)
        print(f"\n=== Игра: {spec.name} ({game_key}) | стратегия игрока ===")
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    asyncio.run(run())


def _strategy_cyclic(history: List[str], spec: GameSpec) -> str:
    """Игрок ходит циклически: 0,1,2,0,1,2,... — идеально предсказуемо."""
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


if __name__ == "__main__":
    # Быстрая демонстрация: против предсказуемых стратегий winrate ИИ должен
    # быть заметно выше 0.5; против случайной — около 0.5.
    print(">>> Демонстрация движка предсказания game_ai.py\n")

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
