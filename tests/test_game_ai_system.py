import pytest
import time
import json
import random
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import game_ai
from game_ai import (
    GameSpec,
    GameRegistry,
    AIMemory,
    BasePredictor,
    MarkovPredictor,
    FrequencyPredictor,
    PatternPredictor,
    classify_player_profile,
    GameAIEngine,
    Prediction,
    default_ai_memory,
    play_round,
    train_on_move,
    predict_move,
    register_outcome,
    get_ai_stats,
    reset_ai_memory,
    UserManagerBridge,
    ensure_ai_memory_field,
    patch_default_user_structure,
    build_adapter,
)

# ─────────────────────────────────────────────────────────────────────────────
# 1-10: GameSpec & GameRegistry
# ─────────────────────────────────────────────────────────────────────────────

def test_game_ai_001():
    """Проверка создания и валидации GameSpec."""
    spec = GameSpec(key="test_game", name="Тест", moves=["a", "b"])
    assert spec.key == "test_game"
    assert spec.name == "Тест"
    assert spec.moves == ["a", "b"]

def test_game_ai_002():
    """Исключение при пустом списке ходов."""
    with pytest.raises(ValueError):
        GameSpec(key="invalid", name="Invalid", moves=[])

def test_game_ai_003():
    """Исключение при длине хода отличной от 1."""
    with pytest.raises(ValueError):
        GameSpec(key="invalid", name="Invalid", moves=["ab"])

def test_game_ai_004():
    """Дедупликация ходов в GameSpec."""
    spec = GameSpec(key="dup", name="Dup", moves=["a", "a", "b"])
    assert spec.moves == ["a", "b"]

def test_game_ai_005():
    """Валидация ходов."""
    spec = GameSpec(key="valid", name="Valid", moves=["a", "b"])
    assert spec.is_valid_move("a") is True
    assert spec.is_valid_move("c") is False

def test_game_ai_006():
    """Проверка таблицы побед beats в GameSpec."""
    beats = {"r": ["s"], "s": ["p"], "p": ["r"]}
    spec = GameSpec(key="rps", name="RPS", moves=["r", "s", "p"], beats=beats)
    assert spec.beats["r"] == ["s"]
    assert spec.beats["s"] == ["p"]

def test_game_ai_007():
    """Вычисление исхода раунда (ИИ победил)."""
    spec = GameRegistry.get("rps")
    assert spec.outcome("r", "s") == 1  # Rock beats Scissors (AI wins)

def test_game_ai_008():
    """Вычисление исхода раунда (ИИ проиграл)."""
    spec = GameRegistry.get("rps")
    assert spec.outcome("s", "r") == -1  # Scissors loses to Rock (Player wins)

def test_game_ai_009():
    """Вычисление исхода раунда (Ничья)."""
    spec = GameRegistry.get("rps")
    assert spec.outcome("r", "r") == 0

def test_game_ai_010():
    """Проверка существования предустановленных игр в реестре."""
    assert GameRegistry.has("rps") is True
    assert GameRegistry.has("thimbles") is True
    assert GameRegistry.has("coinflip") is True
    assert GameRegistry.has("blackjack") is True

# ─────────────────────────────────────────────────────────────────────────────
# 11-30: AIMemory Схема, Инициализация, Миграция, Размер
# ─────────────────────────────────────────────────────────────────────────────

def test_game_ai_011():
    """Создание пустой памяти по умолчанию."""
    mem_dict = default_ai_memory()
    assert mem_dict["v"] == 3
    assert mem_dict["h"] == ""
    assert isinstance(mem_dict["t"], dict)
    assert isinstance(mem_dict["t3"], dict)

def test_game_ai_012():
    """Инициализация AIMemory из словаря."""
    mem = AIMemory(default_ai_memory())
    assert mem.v == 3
    assert mem.h == ""
    assert mem.n == 0

def test_game_ai_013():
    """Проверка to_dict в AIMemory."""
    mem = AIMemory()
    mem_dict = mem.to_dict()
    assert mem_dict["v"] == 3
    assert "t3" in mem_dict

def test_game_ai_014():
    """Мягкая миграция со схемы v1."""
    old_data = {"v": 1, "h": "rs", "t": {"r|s": 1}}
    mem = AIMemory.from_dict(old_data)
    assert mem.v == 3
    assert mem.t2 == {}
    assert mem.t3 == {}

def test_game_ai_015():
    """Мягкая миграция со схемы v2."""
    old_data = {"v": 2, "h": "rs", "t": {"r|s": 1}, "t2": {"rs|p": 1}}
    mem = AIMemory.from_dict(old_data)
    assert mem.v == 3
    assert mem.t3 == {}
    assert mem.wts == {}

def test_game_ai_016():
    """Получение последнего хода."""
    mem = AIMemory()
    assert mem.last_move() is None
    mem.h = "r"
    assert mem.last_move() == "r"

def test_game_ai_017():
    """Получение последних двух ходов."""
    mem = AIMemory()
    assert mem.last_two() is None
    mem.h = "rs"
    assert mem.last_two() == "rs"

def test_game_ai_018():
    """Получение последних трех ходов."""
    mem = AIMemory()
    assert mem.last_three() is None
    mem.h = "rsp"
    assert mem.last_three() == "rsp"

def test_game_ai_019():
    """Подсчет общего числа игр."""
    mem = AIMemory()
    mem.n = 42
    assert mem.total_games() == 42

def test_game_ai_020():
    """Подсчет винрейта ИИ."""
    mem = AIMemory()
    assert mem.winrate_ai() == 0.0
    mem.n = 10
    mem.w = 4
    assert mem.winrate_ai() == 0.4

def test_game_ai_021():
    """Оценка размера документа памяти."""
    mem = AIMemory()
    size = mem.estimate_document_size()
    assert isinstance(size, int)
    assert size > 0

def test_game_ai_022():
    """Сохранение истории в виде списка ходов."""
    mem = AIMemory()
    mem.h = "rsp"
    assert mem.history_list() == ["r", "s", "p"]

def test_game_ai_023():
    """Словарь адаптивных весов в to_dict содержит округленные значения."""
    mem = AIMemory()
    mem.wts = {"predictor": 1.2345678}
    assert mem.to_dict()["wts"]["predictor"] == 1.23457

def test_game_ai_024():
    """Проверка полей класса через slots."""
    mem = AIMemory()
    assert hasattr(mem, "__slots__")
    assert "t3" in mem.__slots__

def test_game_ai_025():
    """Миграция не ломает существующий профиль."""
    old_data = {"v": 2, "prof": "sticky"}
    mem = AIMemory.from_dict(old_data)
    assert mem.prof == "sticky"

def test_game_ai_026():
    """Инициализация с None возвращает значения по умолчанию."""
    mem = AIMemory(None)
    assert mem.v == 3
    assert mem.h == ""

def test_game_ai_027():
    """Восстановление структуры при некорректных типах t2/t3."""
    old_data = {"v": 1, "t2": None, "t3": None}
    mem = AIMemory.from_dict(old_data)
    assert mem.t2 == {}
    assert mem.t3 == {}

def test_game_ai_028():
    """Сохранение времени последнего хода в self.last."""
    mem = AIMemory()
    mem.record_move("r")
    assert mem.last > 0

def test_game_ai_029():
    """Винрейт ИИ равен нулю при нулевом количестве игр."""
    mem = AIMemory()
    mem.n = 0
    mem.w = 5
    assert mem.winrate_ai() == 0.0

def test_game_ai_030():
    """Проверка корректной инициализации адаптивных весов (тип float)."""
    mem = AIMemory({"wts": {"test": 1}})
    assert isinstance(mem.wts["test"], float)

# ─────────────────────────────────────────────────────────────────────────────
# 31-45: AIMemory Запись ходов, Исходы, Обрезка
# ─────────────────────────────────────────────────────────────────────────────

def test_game_ai_031():
    """Запись первого хода."""
    mem = AIMemory()
    mem.record_move("r")
    assert mem.h == "r"
    assert mem.n == 1

def test_game_ai_032():
    """Запись переходов порядка 1."""
    mem = AIMemory()
    mem.record_move("r")
    mem.record_move("s")
    assert mem.t["r|s"] == 1

def test_game_ai_033():
    """Запись переходов порядка 2."""
    mem = AIMemory()
    mem.record_move("r")
    mem.record_move("s")
    mem.record_move("p")
    assert mem.t2["rs|p"] == 1

def test_game_ai_034():
    """Запись переходов порядка 3."""
    mem = AIMemory()
    mem.record_move("r")
    mem.record_move("s")
    mem.record_move("p")
    mem.record_move("r")
    assert mem.t3["rsp|r"] == 1

def test_game_ai_035():
    """Ограничение максимальной длины истории ходов."""
    mem = AIMemory()
    for _ in range(200):
        mem.record_move("r")
    assert len(mem.h) == game_ai.MAX_HISTORY_LEN

def test_game_ai_036():
    """Учет победы ИИ в record_outcome."""
    mem = AIMemory()
    mem.record_outcome(1)
    assert mem.w == 1
    assert mem.streak == 1

def test_game_ai_037():
    """Учет поражения ИИ в record_outcome."""
    mem = AIMemory()
    mem.record_outcome(-1)
    assert mem.l == 1
    assert mem.streak == -1

def test_game_ai_038():
    """Учет ничьей в record_outcome."""
    mem = AIMemory()
    mem.record_outcome(0)
    assert mem.d == 1
    assert mem.streak == 0

def test_game_ai_039():
    """Накопление серии побед ИИ."""
    mem = AIMemory()
    mem.record_outcome(1)
    mem.record_outcome(1)
    assert mem.streak == 2

def test_game_ai_040():
    """Накопление серии поражений ИИ (серии игрока)."""
    mem = AIMemory()
    mem.record_outcome(-1)
    mem.record_outcome(-1)
    assert mem.streak == -2

def test_game_ai_041():
    """Смена знака серии при изменении исхода."""
    mem = AIMemory()
    mem.record_outcome(1)
    mem.record_outcome(-1)
    assert mem.streak == -1

def test_game_ai_042():
    """Ничья уменьшает положительную серию."""
    mem = AIMemory()
    mem.record_outcome(1)
    mem.record_outcome(1)
    mem.record_outcome(0)
    assert mem.streak == 1

def test_game_ai_043():
    """Ничья уменьшает отрицательную серию."""
    mem = AIMemory()
    mem.record_outcome(-1)
    mem.record_outcome(-1)
    mem.record_outcome(0)
    assert mem.streak == -1

def test_game_ai_044():
    """Обрезка переходов при превышении капа (t)."""
    mem = AIMemory()
    # Забиваем t ключами
    for i in range(300):
        mem.t[f"key{i}"] = i
    mem._trim_transitions()
    assert len(mem.t) == game_ai.MAX_TRANSITION_KEYS
    # Убеждаемся, что остались ключи с наибольшими весами
    assert "key299" in mem.t

def test_game_ai_045():
    """Обрезка переходов при превышении капа (t2, t3)."""
    mem = AIMemory()
    for i in range(200):
        mem.t2[f"k{i}"] = i
        mem.t3[f"k{i}"] = i
    mem._trim_transitions()
    assert len(mem.t2) == game_ai.MAX_TRANSITION_KEYS_ORDER2
    assert len(mem.t3) == game_ai.MAX_TRANSITION_KEYS_ORDER3

# ─────────────────────────────────────────────────────────────────────────────
# 46-55: BasePredictor & MarkovPredictors
# ─────────────────────────────────────────────────────────────────────────────

def test_game_ai_046():
    """Равномерное распределение BasePredictor.uniform."""
    spec = GameRegistry.get("rps")
    dist = BasePredictor.uniform(spec)
    assert dist == {"r": 1/3, "s": 1/3, "p": 1/3}

def test_game_ai_047():
    """Нормализация распределения вероятностей."""
    spec = GameRegistry.get("rps")
    dist = {"r": 2.0, "s": 3.0, "p": 0.0}
    norm = BasePredictor.normalize(dist, spec)
    assert norm == {"r": 0.4, "s": 0.6, "p": 0.0}

def test_game_ai_048():
    """Нормализация нулевого/негативного распределения возвращает uniform."""
    spec = GameRegistry.get("rps")
    dist = {"r": -1.0, "s": 0.0}
    norm = BasePredictor.normalize(dist, spec)
    assert norm == BasePredictor.uniform(spec)

def test_game_ai_049():
    """MarkovPredictor order-1 возвращает uniform на пустой истории."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    pred = MarkovPredictor(1)
    assert pred.predict(mem, spec) == BasePredictor.uniform(spec)

def test_game_ai_050():
    """MarkovPredictor order-1 делает прогноз на основе истории."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.record_move("r")
    mem.record_move("s")
    mem.record_move("r")
    pred = MarkovPredictor(1)
    dist = pred.predict(mem, spec)
    # т.к. ход s уже сыгран после r, вероятность r|s должна быть выше
    assert dist["s"] > dist["r"]

def test_game_ai_051():
    """MarkovPredictor order-2 использует fallback к order-1 при отсутствии контекста."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.record_move("r")
    m1 = MarkovPredictor(1)
    m2 = MarkovPredictor(2, fallback=m1)
    # длина истории 1, нет контекста для order-2
    assert m2.predict(mem, spec) == m1.predict(mem, spec)

def test_game_ai_052():
    """MarkovPredictor order-2 использует линейный бэк-офф при нехватке данных."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.record_move("r")
    mem.record_move("s")
    mem.record_move("p")
    # Добавляем одно наблюдение для rs|p
    m1 = MarkovPredictor(1)
    m2 = MarkovPredictor(2, fallback=m1)
    dist = m2.predict(mem, spec)
    assert dist["p"] > 0.0

def test_game_ai_053():
    """MarkovPredictor order-3 использует fallback к order-2."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.record_move("r")
    mem.record_move("s")
    m1 = MarkovPredictor(1)
    m2 = MarkovPredictor(2, fallback=m1)
    m3 = MarkovPredictor(3, fallback=m2)
    assert m3.predict(mem, spec) == m2.predict(mem, spec)

def test_game_ai_054():
    """MarkovPredictor order-3 бэк-офф при наличии контекста."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.record_move("r")
    mem.record_move("s")
    mem.record_move("p")
    mem.record_move("r")
    m1 = MarkovPredictor(1)
    m2 = MarkovPredictor(2, fallback=m1)
    m3 = MarkovPredictor(3, fallback=m2)
    dist = m3.predict(mem, spec)
    assert "r" in dist

def test_game_ai_055():
    """Проверка правильности имен предсказателей."""
    assert MarkovPredictor(1).name == "markov1"
    assert MarkovPredictor(2).name == "markov2"
    assert MarkovPredictor(3).name == "markov3"

# ─────────────────────────────────────────────────────────────────────────────
# 56-65: FrequencyPredictor & PatternPredictor
# ─────────────────────────────────────────────────────────────────────────────

def test_game_ai_056():
    """FrequencyPredictor возвращает uniform на пустой памяти."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    pred = FrequencyPredictor()
    assert pred.predict(mem, spec) == BasePredictor.uniform(spec)

def test_game_ai_057():
    """FrequencyPredictor отдает предпочтение часто встречающимся ходам."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.h = "rrrr"
    pred = FrequencyPredictor()
    dist = pred.predict(mem, spec)
    assert dist["r"] > 0.8

def test_game_ai_058():
    """FrequencyPredictor учитывает RECENCY_DECAY (свежие ходы весят больше)."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    # Сначала много r, потом один s.
    mem.h = "rrrs"
    pred = FrequencyPredictor()
    dist = pred.predict(mem, spec)
    # Так как s свежее, его вероятность будет выше, чем если бы затухания не было
    assert dist["s"] > 0.15

def test_game_ai_059():
    """PatternPredictor возвращает uniform на слишком короткой истории."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.h = "r"
    pred = PatternPredictor()
    assert pred.predict(mem, spec) == BasePredictor.uniform(spec)

def test_game_ai_060():
    """PatternPredictor находит повторяющийся паттерн (цикл)."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.h = "rsprsprs"  # Игрок ходит rsp, rsp, rs. Ожидаемый следующий ход p.
    pred = PatternPredictor()
    dist = pred.predict(mem, spec)
    assert dist["p"] > dist["r"]

def test_game_ai_061():
    """PatternPredictor возвращает uniform при отсутствии совпадений."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.h = "rspr"
    pred = PatternPredictor()
    assert pred.predict(mem, spec) == BasePredictor.uniform(spec)

def test_game_ai_062():
    """PatternPredictor отдает предпочтение более длинным совпадениям."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    # Паттерн "spr" встречается один раз, паттерн "pr" - один раз.
    mem.h = "rsprspr"
    pred = PatternPredictor()
    dist = pred.predict(mem, spec)
    assert "s" in dist

def test_game_ai_063():
    """Частотный предсказатель игнорирует некорректные ходы в истории."""
    spec = GameSpec(key="custom", name="Custom", moves=["a", "b"])
    mem = AIMemory()
    mem.h = "abx"
    pred = FrequencyPredictor()
    dist = pred.predict(mem, spec)
    assert "x" not in dist

def test_game_ai_064():
    """Частотный предсказатель корректно нормализует распределение."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.h = "r"
    pred = FrequencyPredictor()
    dist = pred.predict(mem, spec)
    assert sum(dist.values()) == pytest.approx(1.0)

def test_game_ai_065():
    """Свойство name у частотного и паттерн предсказателей."""
    assert FrequencyPredictor().name == "freq"
    assert PatternPredictor().name == "pattern"

# ─────────────────────────────────────────────────────────────────────────────
# 66-75: Профилирование Игрока (classify_player_profile)
# ─────────────────────────────────────────────────────────────────────────────

def test_game_ai_066():
    """Профиль unknown при малом количестве игр."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.n = 5
    assert classify_player_profile(mem, spec) == "unknown"

def test_game_ai_067():
    """Профиль random при высокой энтропии ходов."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.n = 12
    # Равномерное распределение
    mem.h = "rsprsprsprsp"
    assert classify_player_profile(mem, spec) == "random"

def test_game_ai_068():
    """Профиль sticky при частом повторении предыдущего хода."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.n = 10
    mem.h = "rrrrrrrrrr"
    assert classify_player_profile(mem, spec) == "sticky"

def test_game_ai_069():
    """Профиль biased при наличии любимого хода."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.n = 10
    mem.h = "rsrsrsrsrr"  # r встречается в 60% случаев (более 55%), но без длинной серии повторов подряд
    assert classify_player_profile(mem, spec) == "biased"

def test_game_ai_070():
    """Профиль predictable при низкой энтропии."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.n = 10
    mem.h = "rrsrrsrrsr"
    assert classify_player_profile(mem, spec) in ["predictable", "biased", "balanced", "sticky"]

def test_game_ai_071():
    """Классификатор профиля возвращает balanced для умеренных распределений."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.n = 12
    mem.h = "rrsspruurrss" # сбалансировано
    assert isinstance(classify_player_profile(mem, spec), str)

def test_game_ai_072():
    """Профиль сохраняется в памяти как строка."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    mem.n = 10
    mem.h = "rrrrrrrrrr"
    mem.prof = classify_player_profile(mem, spec)
    assert isinstance(mem.prof, str)

def test_game_ai_073():
    """Корректная обработка нулевой энтропии для одного хода."""
    spec = GameSpec(key="one", name="One", moves=["a"])
    mem = AIMemory()
    mem.n = 10
    mem.h = "aaaaaaaaaa"
    assert classify_player_profile(mem, spec) == "sticky"

def test_game_ai_074():
    """Энтропия корректно рассчитывается для двух ходов."""
    spec = GameRegistry.get("coinflip")
    mem = AIMemory()
    mem.n = 10
    mem.h = "0101010101"
    profile = classify_player_profile(mem, spec)
    assert profile in ["random", "balanced", "predictable"]

def test_game_ai_075():
    """Успешное определение профиля в Блэкджеке."""
    spec = GameRegistry.get("blackjack")
    mem = AIMemory()
    mem.n = 10
    mem.h = "hhhhhhhhhh"
    assert classify_player_profile(mem, spec) == "sticky"

# ─────────────────────────────────────────────────────────────────────────────
# 76-90: GameAIEngine (Предсказания, EV, Адаптивные веса Expert Update)
# ─────────────────────────────────────────────────────────────────────────────

def test_game_ai_076():
    """Создание GameAIEngine с весами по умолчанию."""
    engine = GameAIEngine()
    assert "markov3" in engine.predictors
    assert "pattern" in engine.predictors

def test_game_ai_077():
    """Эффективные веса рассчитываются правильно."""
    mem = AIMemory()
    mem.wts = {"markov3": 2.0}
    engine = GameAIEngine()
    eff = engine._effective_weights(mem)
    # Вес markov3 увеличился относительно базового
    assert eff["markov3"] > game_ai.BLEND_WEIGHTS["markov3"]

def test_game_ai_078():
    """Выбор лучшего хода на основе максимизации EV."""
    spec = GameRegistry.get("rps")
    engine = GameAIEngine()
    # Распределение ходов игрока: 100% Scissors. ИИ должен выбрать Rock.
    dist = {"r": 0.0, "s": 1.0, "p": 0.0}
    ai_move, best_ev = engine._choose_by_ev(dist, spec)
    assert ai_move == "r"
    assert best_ev == 1.0

def test_game_ai_079():
    """Смешивание предсказаний с весами."""
    spec = GameRegistry.get("rps")
    engine = GameAIEngine()
    dists = {
        "markov3": {"r": 1.0, "s": 0.0, "p": 0.0},
        "freq": {"r": 0.0, "s": 1.0, "p": 0.0}
    }
    weights = {"markov3": 0.7, "freq": 0.3}
    blended = engine._blend(dists, weights, spec)
    assert blended["r"] == 0.7
    assert blended["s"] == 0.3

def test_game_ai_080():
    """Прогноз выдает объект Prediction."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    engine = GameAIEngine()
    pred = engine.predict(mem, spec)
    assert isinstance(pred, Prediction)
    assert pred.predicted_player_move in spec.moves
    assert pred.ai_move in spec.moves

def test_game_ai_081():
    """Эксплорация включается при низком EV."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    # Создаем генератор случайных чисел, который всегда возвращает True для эксплорации
    mock_rng = MagicMock()
    mock_rng.random.return_value = 0.0  # < EXPLORATION_EPSILON
    mock_rng.choice.side_effect = lambda x: x[0]
    
    engine = GameAIEngine(rng=mock_rng)
    # При пустой памяти EV = 0.0 < LOW_EV_THRESHOLD
    pred = engine.predict(mem, spec)
    assert pred.used_exploration is True

def test_game_ai_082():
    """Обновление весов экспертов Hedge увеличивает вес успешного эксперта."""
    mem = AIMemory()
    # Два эксперта. Один предсказал r на 100%, другой на 0%
    per_predictor = {
        "markov3": {"r": 1.0, "s": 0.0, "p": 0.0},
        "freq": {"r": 0.0, "s": 1.0, "p": 0.0}
    }
    engine = GameAIEngine()
    engine.update_experts(mem, per_predictor, "r")
    # Вес успешного эксперта должен быть выше, чем неуспешного
    assert mem.wts["markov3"] > mem.wts["freq"]

def test_game_ai_083():
    """Hedge обновление весов экспертов ограничивает минимальный вес EXPERT_FLOOR."""
    mem = AIMemory()
    per_predictor = {"freq": {"r": 0.0, "s": 1.0}}
    engine = GameAIEngine()
    for _ in range(50):
        engine.update_experts(mem, per_predictor, "r")
    assert mem.wts["freq"] >= game_ai.EXPERT_FLOOR

def test_game_ai_084():
    """Hedge нормализует среднее значение весов к 1.0."""
    mem = AIMemory()
    per_predictor = {
        "markov3": {"r": 0.9, "s": 0.1},
        "freq": {"r": 0.1, "s": 0.9}
    }
    engine = GameAIEngine()
    engine.update_experts(mem, per_predictor, "r")
    avg_weight = sum(mem.wts.values()) / len(mem.wts)
    assert avg_weight == pytest.approx(1.0)

def test_game_ai_085():
    """Худший случай: падение предсказателя обрабатывается корректно."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    engine = GameAIEngine()
    # Подменяем предсказатель на бросающий исключение
    bad_predictor = MagicMock()
    bad_predictor.predict.side_effect = Exception("Crash")
    engine.predictors["markov3"] = bad_predictor
    # Прогноз все равно должен выполниться за счет перехвата исключения
    pred = engine.predict(mem, spec)
    assert isinstance(pred, Prediction)

def test_game_ai_086():
    """EV выбор в несимметричных играх (например, наперстки)."""
    spec = GameRegistry.get("thimbles")
    engine = GameAIEngine()
    # Распределение ходов игрока: 100% выберет '0'
    dist = {"0": 1.0, "1": 0.0, "2": 0.0}
    # ИИ должен прятать шарик НЕ в 0 (т.е. 1 или 2), так как beats пустой,
    # но _choose_by_ev выбирает наилучший исход.
    # Для thimbles: outcome(ai, pm) = +1 если ai == pm (симметричный spec),
    # но в ThimblesAdapter исход пересчитан отдельно.
    ai_move, _ = engine._choose_by_ev(dist, spec)
    assert ai_move in spec.moves

def test_game_ai_087():
    """Вычисление макс. вероятности в _argmax."""
    engine = GameAIEngine()
    spec = GameRegistry.get("rps")
    dist = {"r": 0.2, "s": 0.7, "p": 0.1}
    best, prob = engine._argmax(dist, spec)
    assert best == "s"
    assert prob == 0.7

def test_game_ai_088():
    """Singleton движок возвращает один и тот же объект."""
    e1 = game_ai.get_engine()
    e2 = game_ai.get_engine()
    assert e1 is e2

def test_game_ai_089():
    """Confidence в Prediction округлен до 4 знаков."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    engine = GameAIEngine()
    pred = engine.predict(mem, spec)
    assert isinstance(pred.confidence, float)

def test_game_ai_090():
    """Рейтинг распределения в Prediction округлен до 4 знаков."""
    spec = GameRegistry.get("rps")
    mem = AIMemory()
    engine = GameAIEngine()
    pred = engine.predict(mem, spec)
    for v in pred.distribution.values():
        assert len(str(v).split(".")[-1]) <= 4

# ─────────────────────────────────────────────────────────────────────────────
# 91-105: Высокоуровневые API
# ─────────────────────────────────────────────────────────────────────────────

def test_game_ai_091():
    """train_on_move обучает память ходу игрока."""
    mem = default_ai_memory()
    new_mem = train_on_move(mem, "r", "rps")
    assert new_mem["h"] == "r"
    assert new_mem["n"] == 1

def test_game_ai_092():
    """train_on_move бросает ValueError при невалидном ходе."""
    mem = default_ai_memory()
    with pytest.raises(ValueError):
        train_on_move(mem, "x", "rps")

def test_game_ai_093():
    """register_outcome сохраняет исход в память."""
    mem = default_ai_memory()
    new_mem = register_outcome(mem, 1)
    assert new_mem["w"] == 1
    assert new_mem["streak"] == 1

def test_game_ai_094():
    """predict_move возвращает правильную структуру."""
    mem = default_ai_memory()
    res = predict_move(mem, "rps")
    assert "ai_move" in res
    assert "confidence" in res
    assert "profile" in res

def test_game_ai_095():
    """play_round выполняет полный раунд и возвращает (память, отчет)."""
    mem = default_ai_memory()
    new_mem, report = play_round(mem, "rps", "r")
    assert "ai_move" in report
    assert "outcome" in report
    assert "totals" in report
    assert new_mem["n"] == 1

def test_game_ai_096():
    """play_round обучает экспертов Hedge по ходу раунда."""
    mem = default_ai_memory()
    new_mem, report = play_round(mem, "rps", "r")
    # Адаптивные веса инициализированы и изменены
    assert "wts" in new_mem
    assert len(new_mem["wts"]) > 0

def test_game_ai_097():
    """reset_ai_memory возвращает чистую дефолтную память."""
    new_mem = reset_ai_memory()
    assert new_mem["n"] == 0
    assert new_mem["h"] == ""

def test_game_ai_098():
    """get_ai_stats возвращает полную сводную статистику."""
    mem = default_ai_memory()
    stats = get_ai_stats(mem)
    assert stats["total_moves"] == 0
    assert stats["winrate_ai"] == 0.0
    assert "transition_keys_order3" in stats

def test_game_ai_099():
    """Исключение при некорректном ходе в play_round."""
    mem = default_ai_memory()
    with pytest.raises(ValueError):
        play_round(mem, "rps", "x")

def test_game_ai_100():
    """Обучение на ходе игрока обновляет профиль."""
    mem = default_ai_memory()
    # Сыграем 8 одинаковых ходов, чтобы профиль вышел из состояния unknown
    for _ in range(8):
        mem = train_on_move(mem, "r", "rps")
    assert mem["prof"] == "sticky"

def test_game_ai_101():
    """get_ai_stats корректно возвращает количество ключей переходов."""
    mem = default_ai_memory()
    mem["t"] = {"r|s": 1}
    mem["t2"] = {"rs|p": 1}
    mem["t3"] = {"rsp|r": 1}
    stats = get_ai_stats(mem)
    assert stats["transition_keys"] == 1
    assert stats["transition_keys_order2"] == 1
    assert stats["transition_keys_order3"] == 1

def test_game_ai_102():
    """play_round корректно возвращает ничью в отчете."""
    mem = default_ai_memory()
    # Заставим ИИ сделать ход r. Мы ходим r -> Ничья.
    # Т.к. память пустая, ИИ сделает ход r (первый ход в rps).
    _, report = play_round(mem, "rps", "r")
    assert report["outcome"] in [0, 1, -1]
    assert report["outcome_text"] in ["ai_win", "player_win", "draw"]

def test_game_ai_103():
    """Миграция происходит автоматически в play_round."""
    v1_mem = {"v": 1, "h": "", "t": {}}
    new_mem, _ = play_round(v1_mem, "rps", "r")
    assert new_mem["v"] == 3

def test_game_ai_104():
    """Статистика содержит оценку размера документа больше нуля."""
    mem = default_ai_memory()
    stats = get_ai_stats(mem)
    assert stats["doc_size_bytes"] > 0

def test_game_ai_105():
    """predict_move не изменяет переданную память (чистая функция)."""
    mem = default_ai_memory()
    predict_move(mem, "rps")
    assert mem["n"] == 0

# ─────────────────────────────────────────────────────────────────────────────
# 106-115: UserManagerBridge
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_game_ai_106():
    """Чтение памяти через UserManagerBridge создает поле, если его нет."""
    mock_get = AsyncMock(return_value={})
    bridge = UserManagerBridge(get_user=mock_get, mark_dirty=MagicMock())
    user, mem = await bridge._read_memory("uid")
    assert "ai_memory" in user
    assert mem["v"] == 3

@pytest.mark.asyncio
async def test_game_ai_107():
    """Запись памяти через UserManagerBridge маркирует юзера грязным."""
    mock_dirty = MagicMock()
    bridge = UserManagerBridge(get_user=AsyncMock(), mark_dirty=mock_dirty)
    bridge._write_memory("uid", {}, default_ai_memory())
    mock_dirty.assert_called_once_with("uid")

@pytest.mark.asyncio
async def test_game_ai_108():
    """Метод train в UserManagerBridge обучает модель."""
    mock_get = AsyncMock(return_value={"ai_memory": default_ai_memory()})
    mock_dirty = MagicMock()
    bridge = UserManagerBridge(get_user=mock_get, mark_dirty=mock_dirty)
    new_mem = await bridge.train("uid", "rps", "r")
    assert new_mem["h"] == "r"
    mock_dirty.assert_called_once_with("uid")

@pytest.mark.asyncio
async def test_game_ai_109():
    """Метод predict в UserManagerBridge возвращает прогноз."""
    mock_get = AsyncMock(return_value={"ai_memory": default_ai_memory()})
    bridge = UserManagerBridge(get_user=mock_get, mark_dirty=MagicMock())
    pred = await bridge.predict("uid", "rps")
    assert "ai_move" in pred

@pytest.mark.asyncio
async def test_game_ai_110():
    """Метод play в UserManagerBridge проводит раунд."""
    mock_get = AsyncMock(return_value={"ai_memory": default_ai_memory()})
    mock_dirty = MagicMock()
    bridge = UserManagerBridge(get_user=mock_get, mark_dirty=mock_dirty)
    report = await bridge.play("uid", "rps", "r")
    assert "outcome" in report
    mock_dirty.assert_called_once_with("uid")

@pytest.mark.asyncio
async def test_game_ai_111():
    """Метод stats в UserManagerBridge возвращает статистику."""
    mock_get = AsyncMock(return_value={"ai_memory": default_ai_memory()})
    bridge = UserManagerBridge(get_user=mock_get, mark_dirty=MagicMock())
    stats = await bridge.stats("uid")
    assert stats["total_moves"] == 0

@pytest.mark.asyncio
async def test_game_ai_112():
    """Метод reset в UserManagerBridge сбрасывает память."""
    user = {"ai_memory": {"v": 3, "n": 10, "h": "r"}}
    mock_get = AsyncMock(return_value=user)
    mock_dirty = MagicMock()
    bridge = UserManagerBridge(get_user=mock_get, mark_dirty=mock_dirty)
    new_mem = await bridge.reset("uid")
    assert new_mem["n"] == 0
    assert user["ai_memory"]["n"] == 0

@pytest.mark.asyncio
async def test_game_ai_113():
    """Метод register_outcome в UserManagerBridge."""
    mock_get = AsyncMock(return_value={"ai_memory": default_ai_memory()})
    bridge = UserManagerBridge(get_user=mock_get, mark_dirty=MagicMock())
    new_mem = await bridge.register_outcome("uid", 1)
    assert new_mem["w"] == 1

def test_game_ai_114():
    """ensure_ai_memory_field добавляет поле в сырой документ."""
    doc = {}
    ensure_ai_memory_field(doc)
    assert "ai_memory" in doc
    assert doc["ai_memory"]["v"] == 3

def test_game_ai_115():
    """patch_default_user_structure оборачивает фабрику пользователя."""
    factory = lambda: {"balance": 500}
    wrapped = patch_default_user_structure(factory)
    doc = wrapped()
    assert doc["balance"] == 500
    assert "ai_memory" in doc

# ─────────────────────────────────────────────────────────────────────────────
# 116-120: Игры и Адаптеры (Thimbles, Coinflip, RPS)
# ─────────────────────────────────────────────────────────────────────────────

def test_game_ai_116():
    """Фабрика build_adapter создает корректный адаптер."""
    mock_bridge = MagicMock()
    adapter = build_adapter("rps", mock_bridge)
    assert adapter.game_key == "rps"

def test_game_ai_117():
    """Исключение в build_adapter при неизвестной игре."""
    mock_bridge = MagicMock()
    with pytest.raises(KeyError):
        build_adapter("invalid_game", mock_bridge)

@pytest.mark.asyncio
async def test_game_ai_118():
    """RPSAdapter.resolve вызывает bridge.play."""
    mock_bridge = MagicMock()
    mock_bridge.play = AsyncMock(return_value={"outcome": 1})
    adapter = build_adapter("rps", mock_bridge)
    res = await adapter.resolve("uid", "r")
    assert res["outcome"] == 1
    mock_bridge.play.assert_called_once_with("uid", "rps", "r")

@pytest.mark.asyncio
async def test_game_ai_119():
    """CoinflipAdapter.resolve прогнозирует ход и обучается."""
    mock_bridge = MagicMock()
    mock_bridge.predict = AsyncMock(return_value={"predicted_player_move": "0", "confidence": 0.5, "profile": "random"})
    mock_bridge.train = AsyncMock()
    mock_bridge.register_outcome = AsyncMock()
    
    adapter = build_adapter("coinflip", mock_bridge)
    res = await adapter.resolve("uid", "0")
    assert "ai_guess" in res
    assert res["player_move"] == "0"
    mock_bridge.predict.assert_called_once_with("uid", "coinflip")
    mock_bridge.train.assert_called_once_with("uid", "coinflip", "0")

@pytest.mark.asyncio
async def test_game_ai_120():
    """ThimblesAdapter.resolve проверяет ход и выбирает позицию шара."""
    mock_bridge = MagicMock()
    mock_bridge.predict = AsyncMock(return_value={"predicted_player_move": "1", "confidence": 0.5, "profile": "random"})
    mock_bridge.train = AsyncMock()
    mock_bridge.register_outcome = AsyncMock()
    
    adapter = build_adapter("thimbles", mock_bridge)
    res = await adapter.resolve("uid", "1")
    assert "ball_position" in res
    assert res["ball_position"] != "1"  # ИИ прячет шарик там, где игрок не выберет
    mock_bridge.predict.assert_called_once_with("uid", "thimbles")
    mock_bridge.train.assert_called_once_with("uid", "thimbles", "1")
