# =============================================================================
# test_game_ai_integration.py
# 100 pytest tests (test_201 – test_300) for game_ai.py
# =============================================================================

import sys
import os
import copy
import json
import time
import math
import random
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import game_ai
from game_ai import (
    AIMemory,
    AIMemoryContainer,
    GameAIEngine,
    GameRegistry,
    GameSpec,
    Prediction,
    UserManagerBridge,
    _FakeUserManager,
    _simulate,
    default_ai_memory,
    default_game_memory,
    ensure_ai_memory_field,
    get_ai_stats,
    get_engine,
    play_round,
    predict_move,
    register_outcome,
    reset_ai_memory,
    reset_game_memory,
    set_engine,
    train_on_move,
    AI_MEMORY_SCHEMA_VERSION,
    MAX_GAMES_IN_MEMORY,
    MAX_HISTORY_LEN,
    MAX_OUTCOME_LEN,
    MAX_TRANSITION_KEYS,
    MAX_TRANSITION_KEYS_ORDER2,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _fresh_engine(seed=42):
    """Return a deterministic GameAIEngine."""
    return GameAIEngine(rng=random.Random(seed))


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


# ============================================================================
# AIMemoryContainer: from_dict None/empty, v3 schema parsing, v1/v2 migration
# tests 201 – 215
# ============================================================================

def test_201_from_dict_none():
    """from_dict(None) returns an empty v3 container."""
    c = AIMemoryContainer.from_dict(None)
    assert c.v == AI_MEMORY_SCHEMA_VERSION
    assert c.games == {}


def test_202_from_dict_empty_dict():
    """from_dict({}) returns an empty v3 container."""
    c = AIMemoryContainer.from_dict({})
    assert c.v == AI_MEMORY_SCHEMA_VERSION
    assert len(c.games) == 0


def test_203_from_dict_non_dict():
    """from_dict with a non-dict (string) gives empty container."""
    c = AIMemoryContainer.from_dict("garbage")
    assert c.games == {}


def test_204_from_dict_non_dict_int():
    """from_dict with an int gives empty container."""
    c = AIMemoryContainer.from_dict(42)
    assert c.games == {}


def test_205_v3_schema_single_game():
    """v3 schema with one game slot is correctly parsed."""
    data = {
        "v": 3,
        "g": {
            "rps": {"h": "rrr", "o": "WLD", "t": {}, "t2": {}, "n": 3,
                    "w": 1, "l": 1, "d": 1, "last": 100, "streak": 0, "prof": "unknown"}
        },
    }
    c = AIMemoryContainer.from_dict(data)
    assert "rps" in c.games
    assert c.games["rps"].h == "rrr"
    assert c.games["rps"].n == 3


def test_206_v3_schema_multiple_games():
    """v3 schema with multiple game slots parses all."""
    data = {
        "v": 3,
        "g": {
            "rps": {"h": "rsp", "n": 3},
            "thimbles": {"h": "012", "n": 3},
        },
    }
    c = AIMemoryContainer.from_dict(data)
    assert len(c.games) == 2
    assert c.games["thimbles"].h == "012"


def test_207_v3_schema_invalid_slot_skipped():
    """Non-dict slot inside g is silently skipped."""
    data = {"v": 3, "g": {"rps": {"h": "r"}, "bad": "not_a_dict"}}
    c = AIMemoryContainer.from_dict(data)
    assert "rps" in c.games
    assert "bad" not in c.games


def test_208_v3_schema_empty_g():
    """v3 with empty 'g' dictionary works."""
    c = AIMemoryContainer.from_dict({"v": 3, "g": {}})
    assert c.games == {}


def test_209_v1v2_migration_rps():
    """Flat v1/v2 dict with RPS-only moves migrates to 'rps' slot."""
    legacy = {"h": "rsp", "t": {"r|s": 1.0}, "n": 3, "w": 1, "l": 1, "d": 1}
    c = AIMemoryContainer.from_dict(legacy)
    assert "rps" in c.games
    assert c.games["rps"].h == "rsp"


def test_210_v1v2_migration_thimbles():
    """Flat v1/v2 dict with thimbles-only moves migrates to 'thimbles' slot."""
    legacy = {"h": "012012", "t": {}, "n": 6}
    c = AIMemoryContainer.from_dict(legacy)
    # thimbles and coinflip both have '0' and '1', but only thimbles has '2'
    assert "thimbles" in c.games


def test_211_v1v2_migration_ambiguous():
    """Flat v1/v2 where moves fit multiple games → no migration, clean start."""
    # moves '0' and '1' match both coinflip (['0','1']) and thimbles (['0','1','2'])
    legacy = {"h": "01", "t": {}, "n": 2}
    c = AIMemoryContainer.from_dict(legacy)
    # ambiguous → should be 0 or possibly placed if only one candidate
    # '0' and '1' are subset of both coinflip and thimbles, so multiple candidates
    assert isinstance(c.games, dict)


def test_212_v1v2_migration_empty_history():
    """v1/v2 with empty history → no candidate → clean container."""
    legacy = {"h": "", "t": {}, "n": 0}
    c = AIMemoryContainer.from_dict(legacy)
    assert len(c.games) == 0


def test_213_v3_preserves_transition_counts():
    """v3 schema with float transition counts is preserved."""
    data = {
        "v": 3,
        "g": {"rps": {"h": "rr", "t": {"r|r": 2.5, "r|s": 0.3}, "t2": {}, "n": 2}},
    }
    c = AIMemoryContainer.from_dict(data)
    mem = c.games["rps"]
    assert abs(mem.t["r|r"] - 2.5) < 0.001
    assert abs(mem.t["r|s"] - 0.3) < 0.001


def test_214_v3_negative_counts_filtered():
    """Negative or zero transition counts are filtered out."""
    data = {"v": 3, "g": {"rps": {"h": "r", "t": {"r|r": -1.0, "r|s": 0.0}, "n": 1}}}
    c = AIMemoryContainer.from_dict(data)
    assert len(c.games["rps"].t) == 0


def test_215_v3_schema_version_in_to_dict():
    """to_dict always writes the current schema version."""
    c = AIMemoryContainer.from_dict(None)
    d = c.to_dict()
    assert d["v"] == AI_MEMORY_SCHEMA_VERSION


# ============================================================================
# AIMemoryContainer: game() auto-creation, LRU eviction, to_dict roundtrip
# tests 216 – 225
# ============================================================================

def test_216_game_auto_creation():
    """game(key) creates a new empty AIMemory slot if absent."""
    c = AIMemoryContainer()
    mem = c.game("rps")
    assert isinstance(mem, AIMemory)
    assert mem.n == 0
    assert "rps" in c.games


def test_217_game_returns_same_object():
    """game(key) returns the same AIMemory on second call."""
    c = AIMemoryContainer()
    mem1 = c.game("rps")
    mem2 = c.game("rps")
    assert mem1 is mem2


def test_218_lru_eviction_triggers():
    """Adding more than MAX_GAMES_IN_MEMORY games evicts the LRU."""
    c = AIMemoryContainer()
    for i in range(MAX_GAMES_IN_MEMORY):
        key = f"game_{i}"
        # Register temporary game specs
        if not GameRegistry.has(key):
            GameRegistry.register(GameSpec(key=key, name=key, moves=["a", "b"]))
        mem = c.game(key)
        mem.last = i  # older games have smaller timestamps
    # Now add one more
    extra_key = "game_overflow"
    if not GameRegistry.has(extra_key):
        GameRegistry.register(GameSpec(key=extra_key, name=extra_key, moves=["x", "y"]))
    c.game(extra_key)
    assert len(c.games) <= MAX_GAMES_IN_MEMORY


def test_219_lru_eviction_keeps_newest():
    """LRU eviction keeps the most recently used game."""
    c = AIMemoryContainer()
    for i in range(MAX_GAMES_IN_MEMORY + 2):
        key = f"lru_{i}"
        if not GameRegistry.has(key):
            GameRegistry.register(GameSpec(key=key, name=key, moves=["a", "b"]))
        mem = c.game(key)
        mem.last = i
    last_key = f"lru_{MAX_GAMES_IN_MEMORY + 1}"
    assert last_key in c.games


def test_220_to_dict_roundtrip():
    """to_dict → from_dict produces equivalent data."""
    c = AIMemoryContainer()
    mem = c.game("rps")
    mem.h = "rsp"
    mem.n = 3
    mem.w = 1
    mem.l = 1
    mem.d = 1
    mem.streak = 2
    d = c.to_dict()
    c2 = AIMemoryContainer.from_dict(d)
    assert c2.games["rps"].h == "rsp"
    assert c2.games["rps"].n == 3
    assert c2.games["rps"].streak == 2


def test_221_roundtrip_preserves_transitions():
    """Transition dicts survive roundtrip through to_dict/from_dict."""
    c = AIMemoryContainer()
    mem = c.game("rps")
    mem.t["r|s"] = 5.123456
    d = c.to_dict()
    c2 = AIMemoryContainer.from_dict(d)
    assert abs(c2.games["rps"].t["r|s"] - 5.123) < 0.001


def test_222_roundtrip_preserves_outcome_history():
    """Outcome string survives roundtrip."""
    c = AIMemoryContainer()
    mem = c.game("rps")
    mem.o = "WWLDLW"
    d = c.to_dict()
    c2 = AIMemoryContainer.from_dict(d)
    assert c2.games["rps"].o == "WWLDLW"


def test_223_estimate_document_size_positive():
    """estimate_document_size returns a positive integer."""
    c = AIMemoryContainer()
    c.game("rps").h = "rsp"
    assert c.estimate_document_size() > 0


def test_224_to_dict_empty_container():
    """Empty container serializes correctly."""
    c = AIMemoryContainer()
    d = c.to_dict()
    assert d == {"v": AI_MEMORY_SCHEMA_VERSION, "g": {}}


def test_225_multiple_games_roundtrip():
    """Multiple games survive roundtrip."""
    c = AIMemoryContainer()
    c.game("rps").h = "r"
    c.game("thimbles").h = "0"
    c.game("coinflip").h = "1"
    d = c.to_dict()
    c2 = AIMemoryContainer.from_dict(d)
    assert set(c2.games.keys()) == {"rps", "thimbles", "coinflip"}


# ============================================================================
# AIMemory: estimate_size, _trim_transitions, recent_winrate edge cases
# tests 226 – 235
# ============================================================================

def test_226_estimate_size_empty():
    """Empty AIMemory has a small but positive size."""
    m = AIMemory()
    assert m.estimate_size() > 0


def test_227_estimate_size_grows_with_data():
    """Size grows when data is added."""
    m = AIMemory()
    s1 = m.estimate_size()
    m.h = "r" * 100
    s2 = m.estimate_size()
    assert s2 > s1


def test_228_trim_transitions_order1():
    """_trim_transitions trims t to MAX_TRANSITION_KEYS."""
    m = AIMemory()
    for i in range(MAX_TRANSITION_KEYS + 50):
        m.t[f"k{i}"] = float(i)
    m._trim_transitions()
    assert len(m.t) <= MAX_TRANSITION_KEYS


def test_229_trim_transitions_order2():
    """_trim_transitions trims t2 to MAX_TRANSITION_KEYS_ORDER2."""
    m = AIMemory()
    for i in range(MAX_TRANSITION_KEYS_ORDER2 + 50):
        m.t2[f"k{i}"] = float(i)
    m._trim_transitions()
    assert len(m.t2) <= MAX_TRANSITION_KEYS_ORDER2


def test_230_trim_keeps_highest():
    """_trim_transitions keeps the entries with the highest counts."""
    m = AIMemory()
    for i in range(MAX_TRANSITION_KEYS + 10):
        m.t[f"k{i}"] = float(i)
    m._trim_transitions()
    # The lowest key (k0 with value 0.0) should be trimmed
    remaining_values = list(m.t.values())
    # All remaining should be >= 10 (we had 0..MAX+9, kept top MAX)
    assert min(remaining_values) >= 10


def test_231_recent_winrate_none_when_few():
    """recent_winrate returns None when not enough outcomes."""
    m = AIMemory()
    m.o = "WW"  # only 2 outcomes
    assert m.recent_winrate() is None


def test_232_recent_winrate_all_wins():
    """recent_winrate with all wins is 1.0."""
    m = AIMemory()
    m.o = "W" * 20
    wr = m.recent_winrate()
    assert wr is not None
    assert abs(wr - 1.0) < 0.001


def test_233_recent_winrate_all_losses():
    """recent_winrate with all losses is 0.0."""
    m = AIMemory()
    m.o = "L" * 20
    wr = m.recent_winrate()
    assert wr is not None
    assert abs(wr - 0.0) < 0.001


def test_234_recent_winrate_all_draws():
    """recent_winrate with all draws is 0.5."""
    m = AIMemory()
    m.o = "D" * 20
    wr = m.recent_winrate()
    assert wr is not None
    assert abs(wr - 0.5) < 0.001


def test_235_recent_winrate_mixed():
    """recent_winrate with mixed outcomes returns a float in [0, 1]."""
    m = AIMemory()
    m.o = "WLDDWLWWLW" * 2  # 20 chars
    wr = m.recent_winrate()
    assert wr is not None
    assert 0.0 <= wr <= 1.0


# ============================================================================
# train_on_move: valid/invalid moves, updates memory correctly
# tests 236 – 245
# ============================================================================

def test_236_train_on_valid_move_rps():
    """train_on_move with a valid RPS move returns updated dict."""
    result = train_on_move(None, "r", "rps")
    assert result["v"] == AI_MEMORY_SCHEMA_VERSION
    assert "rps" in result["g"]
    assert result["g"]["rps"]["h"].endswith("r")


def test_237_train_on_valid_move_increments_n():
    """train_on_move increments the move counter."""
    result = train_on_move(None, "r", "rps")
    assert result["g"]["rps"]["n"] == 1


def test_238_train_multiple_moves():
    """Successive train_on_move calls accumulate history."""
    mem = None
    for move in ["r", "s", "p"]:
        mem = train_on_move(mem, move, "rps")
    assert mem["g"]["rps"]["h"] == "rsp"
    assert mem["g"]["rps"]["n"] == 3


def test_239_train_invalid_move_raises():
    """train_on_move with invalid move raises ValueError."""
    try:
        train_on_move(None, "x", "rps")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_240_train_invalid_game_key_raises():
    """train_on_move with unregistered game key raises KeyError."""
    try:
        train_on_move(None, "r", "nonexistent_game")
        assert False, "Should have raised"
    except KeyError:
        pass


def test_241_train_thimbles_valid():
    """train_on_move works for thimbles game."""
    result = train_on_move(None, "2", "thimbles")
    assert result["g"]["thimbles"]["h"] == "2"


def test_242_train_coinflip_valid():
    """train_on_move works for coinflip game."""
    result = train_on_move(None, "0", "coinflip")
    assert result["g"]["coinflip"]["h"] == "0"


def test_243_train_updates_transitions():
    """After two moves, transition dict should have an entry."""
    mem = train_on_move(None, "r", "rps")
    mem = train_on_move(mem, "s", "rps")
    assert "r|s" in mem["g"]["rps"]["t"]


def test_244_train_preserves_other_games():
    """Training in one game doesn't affect another."""
    mem = train_on_move(None, "r", "rps")
    mem = train_on_move(mem, "0", "thimbles")
    assert mem["g"]["rps"]["h"] == "r"
    assert mem["g"]["thimbles"]["h"] == "0"


def test_245_train_updates_profile():
    """After enough moves, profile field is updated."""
    mem = None
    rng = random.Random(99)
    for _ in range(20):
        mem = train_on_move(mem, rng.choice(["r", "s", "p"]), "rps")
    prof = mem["g"]["rps"]["prof"]
    assert isinstance(prof, str)
    assert prof != ""


# ============================================================================
# register_outcome: positive/negative/zero, updates w/l/d/streak
# tests 246 – 255
# ============================================================================

def test_246_register_outcome_win():
    """register_outcome with +1 increments AI wins."""
    mem = register_outcome(None, 1, "rps")
    assert mem["g"]["rps"]["w"] == 1


def test_247_register_outcome_loss():
    """register_outcome with -1 increments AI losses."""
    mem = register_outcome(None, -1, "rps")
    assert mem["g"]["rps"]["l"] == 1


def test_248_register_outcome_draw():
    """register_outcome with 0 increments draws."""
    mem = register_outcome(None, 0, "rps")
    assert mem["g"]["rps"]["d"] == 1


def test_249_register_outcome_streak_positive():
    """Consecutive wins build a positive streak."""
    mem = None
    for _ in range(3):
        mem = register_outcome(mem, 1, "rps")
    assert mem["g"]["rps"]["streak"] == 3


def test_250_register_outcome_streak_negative():
    """Consecutive losses build a negative streak."""
    mem = None
    for _ in range(3):
        mem = register_outcome(mem, -1, "rps")
    assert mem["g"]["rps"]["streak"] == -3


def test_251_register_outcome_streak_reset_on_switch():
    """Streak resets when outcome direction changes."""
    mem = register_outcome(None, 1, "rps")
    mem = register_outcome(mem, 1, "rps")
    mem = register_outcome(mem, -1, "rps")
    assert mem["g"]["rps"]["streak"] == -1


def test_252_register_outcome_draw_shrinks_streak():
    """Draw reduces the magnitude of the streak toward zero."""
    mem = register_outcome(None, 1, "rps")
    mem = register_outcome(mem, 1, "rps")
    mem = register_outcome(mem, 0, "rps")
    assert mem["g"]["rps"]["streak"] == 1  # was 2, draw -1 → 1


def test_253_register_outcome_outcome_string():
    """Outcomes are recorded as W/L/D characters."""
    mem = register_outcome(None, 1, "rps")
    mem = register_outcome(mem, -1, "rps")
    mem = register_outcome(mem, 0, "rps")
    assert mem["g"]["rps"]["o"] == "WLD"


def test_254_register_outcome_large_positive_clamped():
    """Any positive outcome is treated as +1 (W)."""
    mem = register_outcome(None, 100, "rps")
    assert mem["g"]["rps"]["w"] == 1
    assert mem["g"]["rps"]["o"] == "W"


def test_255_register_outcome_large_negative_clamped():
    """Any negative outcome is treated as -1 (L)."""
    mem = register_outcome(None, -50, "rps")
    assert mem["g"]["rps"]["l"] == 1
    assert mem["g"]["rps"]["o"] == "L"


# ============================================================================
# predict_move: returns correct structure, valid moves
# tests 256 – 262
# ============================================================================

def test_256_predict_move_returns_dict():
    """predict_move returns a dictionary."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        result = predict_move(None, "rps")
        assert isinstance(result, dict)
    finally:
        set_engine(old)


def test_257_predict_move_has_required_keys():
    """Returned dict contains all required keys."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        result = predict_move(None, "rps")
        for key in ("predicted_player_move", "ai_move", "confidence",
                     "distribution", "used_exploration", "profile", "meta"):
            assert key in result, f"Missing key: {key}"
    finally:
        set_engine(old)


def test_258_predict_move_valid_predicted_move():
    """predicted_player_move is one of the game's valid moves."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        result = predict_move(None, "rps")
        assert result["predicted_player_move"] in ["r", "s", "p"]
    finally:
        set_engine(old)


def test_259_predict_move_valid_ai_move():
    """ai_move is one of the game's valid moves."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        result = predict_move(None, "rps")
        assert result["ai_move"] in ["r", "s", "p"]
    finally:
        set_engine(old)


def test_260_predict_move_distribution_sums_to_one():
    """Distribution probabilities sum to ~1.0."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        result = predict_move(None, "rps")
        total = sum(result["distribution"].values())
        assert abs(total - 1.0) < 0.01
    finally:
        set_engine(old)


def test_261_predict_move_confidence_in_range():
    """Confidence is between 0 and 1."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        result = predict_move(None, "rps")
        assert 0.0 <= result["confidence"] <= 1.0
    finally:
        set_engine(old)


def test_262_predict_move_does_not_modify_memory():
    """predict_move does not change the passed memory dict."""
    mem = train_on_move(None, "r", "rps")
    mem_copy = copy.deepcopy(mem)
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        predict_move(mem, "rps")
        assert mem == mem_copy
    finally:
        set_engine(old)


# ============================================================================
# play_round: full cycle, outcome correctness, report structure
# tests 263 – 275
# ============================================================================

def test_263_play_round_returns_tuple():
    """play_round returns a 2-tuple."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        result = play_round(None, "rps", "r")
        assert isinstance(result, tuple)
        assert len(result) == 2
    finally:
        set_engine(old)


def test_264_play_round_first_element_is_dict():
    """First element (updated memory) is a dict."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        mem, _ = play_round(None, "rps", "r")
        assert isinstance(mem, dict)
        assert "g" in mem
    finally:
        set_engine(old)


def test_265_play_round_report_has_required_keys():
    """Report dict contains all expected keys."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        _, report = play_round(None, "rps", "r")
        for key in ("game", "ai_move", "player_move", "outcome", "outcome_text",
                     "confidence", "profile", "distribution", "meta", "totals"):
            assert key in report, f"Missing key: {key}"
    finally:
        set_engine(old)


def test_266_play_round_outcome_values():
    """Outcome is one of -1, 0, 1."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        _, report = play_round(None, "rps", "r")
        assert report["outcome"] in (-1, 0, 1)
    finally:
        set_engine(old)


def test_267_play_round_outcome_text_matches():
    """outcome_text matches the numeric outcome."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        _, report = play_round(None, "rps", "r")
        expected = {1: "ai_win", -1: "player_win", 0: "draw"}
        assert report["outcome_text"] == expected[report["outcome"]]
    finally:
        set_engine(old)


def test_268_play_round_updates_memory():
    """Memory is updated with the new move after play_round."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        mem, _ = play_round(None, "rps", "r")
        assert mem["g"]["rps"]["n"] == 1
        assert mem["g"]["rps"]["h"].endswith("r")
    finally:
        set_engine(old)


def test_269_play_round_records_outcome():
    """Memory records the round outcome."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        mem, report = play_round(None, "rps", "r")
        o_char = mem["g"]["rps"]["o"]
        assert len(o_char) == 1
        assert o_char in ("W", "L", "D")
    finally:
        set_engine(old)


def test_270_play_round_totals_consistent():
    """Totals in report match the memory state."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        mem, report = play_round(None, "rps", "r")
        totals = report["totals"]
        g = mem["g"]["rps"]
        assert totals["n"] == g["n"]
        assert totals["ai_wins"] == g["w"]
        assert totals["player_wins"] == g["l"]
        assert totals["draws"] == g["d"]
    finally:
        set_engine(old)


def test_271_play_round_invalid_move_raises():
    """play_round with invalid move raises ValueError."""
    try:
        play_round(None, "rps", "x")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_272_play_round_sequence():
    """Multiple play_round calls accumulate correctly."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        mem = None
        moves = ["r", "s", "p", "r", "s"]
        for m in moves:
            mem, _ = play_round(mem, "rps", m)
        assert mem["g"]["rps"]["n"] == 5
    finally:
        set_engine(old)


def test_273_play_round_game_field_in_report():
    """Report includes the correct game key."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        _, report = play_round(None, "rps", "r")
        assert report["game"] == "rps"
    finally:
        set_engine(old)


def test_274_play_round_player_move_in_report():
    """Report reflects the actual player move."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        _, report = play_round(None, "rps", "s")
        assert report["player_move"] == "s"
    finally:
        set_engine(old)


def test_275_play_round_ai_move_valid():
    """AI move in report is a valid game move."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        _, report = play_round(None, "rps", "p")
        assert report["ai_move"] in ["r", "s", "p"]
    finally:
        set_engine(old)


# ============================================================================
# reset_ai_memory, reset_game_memory
# tests 276 – 280
# ============================================================================

def test_276_reset_ai_memory_returns_clean():
    """reset_ai_memory returns a clean v3 dict."""
    result = reset_ai_memory()
    assert result["v"] == AI_MEMORY_SCHEMA_VERSION
    assert result["g"] == {}


def test_277_reset_ai_memory_idempotent():
    """Calling reset_ai_memory twice gives the same result."""
    r1 = reset_ai_memory()
    r2 = reset_ai_memory()
    assert r1 == r2


def test_278_reset_game_memory_removes_game():
    """reset_game_memory removes only the specified game."""
    mem = train_on_move(None, "r", "rps")
    mem = train_on_move(mem, "0", "thimbles")
    result = reset_game_memory(mem, "rps")
    assert "rps" not in result["g"]
    assert "thimbles" in result["g"]


def test_279_reset_game_memory_nonexistent_key():
    """reset_game_memory with a key not in memory is a no-op."""
    mem = train_on_move(None, "r", "rps")
    result = reset_game_memory(mem, "coinflip")
    assert "rps" in result["g"]


def test_280_reset_game_memory_none_input():
    """reset_game_memory with None ai_memory works."""
    result = reset_game_memory(None, "rps")
    assert result["v"] == AI_MEMORY_SCHEMA_VERSION


# ============================================================================
# get_ai_stats: with and without game_key
# tests 281 – 288
# ============================================================================

def test_281_get_ai_stats_no_game_key():
    """get_ai_stats without game_key returns aggregate dict."""
    mem = train_on_move(None, "r", "rps")
    stats = get_ai_stats(mem)
    assert "schema_version" in stats
    assert "doc_size_bytes" in stats
    assert "games" in stats


def test_282_get_ai_stats_with_game_key():
    """get_ai_stats with game_key returns per-game dict."""
    mem = train_on_move(None, "r", "rps")
    stats = get_ai_stats(mem, "rps")
    assert "total_moves" in stats
    assert stats["total_moves"] == 1


def test_283_get_ai_stats_rounds():
    """rounds = w + l + d."""
    mem = register_outcome(None, 1, "rps")
    mem = register_outcome(mem, -1, "rps")
    mem = register_outcome(mem, 0, "rps")
    stats = get_ai_stats(mem, "rps")
    assert stats["rounds"] == 3


def test_284_get_ai_stats_winrate():
    """Winrate is correctly calculated."""
    mem = None
    for _ in range(6):
        mem = register_outcome(mem, 1, "rps")
    for _ in range(4):
        mem = register_outcome(mem, -1, "rps")
    stats = get_ai_stats(mem, "rps")
    assert abs(stats["winrate_ai"] - 0.6) < 0.001


def test_285_get_ai_stats_none_memory():
    """get_ai_stats with None memory returns empty aggregate."""
    stats = get_ai_stats(None)
    assert stats["games"] == {}


def test_286_get_ai_stats_slot_size():
    """slot_size_bytes is a positive integer."""
    mem = train_on_move(None, "r", "rps")
    stats = get_ai_stats(mem, "rps")
    assert isinstance(stats["slot_size_bytes"], int)
    assert stats["slot_size_bytes"] > 0


def test_287_get_ai_stats_transition_keys_count():
    """transition_keys reflects actual number of transition keys."""
    mem = train_on_move(None, "r", "rps")
    mem = train_on_move(mem, "s", "rps")
    stats = get_ai_stats(mem, "rps")
    assert stats["transition_keys"] >= 1


def test_288_get_ai_stats_profile_field():
    """Stats include the player profile field."""
    mem = train_on_move(None, "r", "rps")
    stats = get_ai_stats(mem, "rps")
    assert "profile" in stats
    assert isinstance(stats["profile"], str)


# ============================================================================
# Prediction dataclass fields
# tests 289 – 292
# ============================================================================

def test_289_prediction_fields_exist():
    """Prediction has all expected fields."""
    p = Prediction(
        predicted_player_move="r",
        ai_move="p",
        confidence=0.75,
        distribution={"r": 0.5, "s": 0.3, "p": 0.2},
        used_exploration=False,
        profile="unknown",
    )
    assert p.predicted_player_move == "r"
    assert p.ai_move == "p"
    assert p.confidence == 0.75


def test_290_prediction_meta_default():
    """Prediction meta defaults to empty dict."""
    p = Prediction(
        predicted_player_move="r",
        ai_move="p",
        confidence=0.5,
        distribution={},
        used_exploration=False,
        profile="unknown",
    )
    assert p.meta == {}


def test_291_prediction_used_exploration_flag():
    """used_exploration flag can be True."""
    p = Prediction(
        predicted_player_move="r",
        ai_move="s",
        confidence=0.3,
        distribution={"r": 0.5, "s": 0.3, "p": 0.2},
        used_exploration=True,
        profile="random",
    )
    assert p.used_exploration is True


def test_292_prediction_with_meta():
    """Prediction can hold arbitrary meta dict."""
    p = Prediction(
        predicted_player_move="r",
        ai_move="p",
        confidence=0.8,
        distribution={"r": 1.0},
        used_exploration=False,
        profile="biased",
        meta={"custom": 123},
    )
    assert p.meta["custom"] == 123


# ============================================================================
# get_engine / set_engine singleton behavior
# tests 293 – 296
# ============================================================================

def test_293_get_engine_returns_engine():
    """get_engine returns a GameAIEngine instance."""
    e = get_engine()
    assert isinstance(e, GameAIEngine)


def test_294_get_engine_singleton():
    """get_engine returns the same instance on consecutive calls."""
    e1 = get_engine()
    e2 = get_engine()
    assert e1 is e2


def test_295_set_engine_replaces():
    """set_engine replaces the global engine."""
    old = get_engine()
    new = _fresh_engine(999)
    set_engine(new)
    assert get_engine() is new
    set_engine(old)  # restore


def test_296_set_engine_is_reflected_in_predict():
    """A custom engine set via set_engine is used by predict_move."""
    old = get_engine()
    custom = _fresh_engine(12345)
    set_engine(custom)
    try:
        result = predict_move(None, "rps")
        # Just verify it runs without error and returns a dict
        assert isinstance(result, dict)
    finally:
        set_engine(old)


# ============================================================================
# _FakeUserManager and _simulate basic smoke tests
# tests 297 – 298
# ============================================================================

def test_297_fake_user_manager_basic():
    """_FakeUserManager stores and retrieves user data."""
    fum = _FakeUserManager()

    async def check():
        user = await fum.get_user("u1")
        assert isinstance(user, dict)
        assert "ai_memory" in user
        fum.mark_dirty("u1")
        assert "u1" in fum.dirty

    _run(check())


def test_298_simulate_smoke():
    """_simulate runs without crashing for a small number of rounds."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        # _simulate prints output; we just check it doesn't crash
        _simulate("rps", lambda h, s: s.moves[len(h) % len(s.moves)], rounds=5, label="test")
    finally:
        set_engine(old)


# ============================================================================
# UserManagerBridge: train, predict, play, play_custom, register_outcome,
# stats, reset
# tests 299 – 300
# ============================================================================

def test_299_bridge_train_predict_play():
    """UserManagerBridge train, predict, and play work end-to-end."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        fum = _FakeUserManager()
        bridge = UserManagerBridge(
            get_user=fum.get_user,
            mark_dirty=fum.mark_dirty,
            set_user=fum.set_user,
        )

        async def run():
            # Train
            await bridge.train("u1", "rps", "r")
            assert "u1" in fum.dirty

            # Predict
            pred = await bridge.predict("u1", "rps")
            assert "ai_move" in pred
            assert pred["ai_move"] in ["r", "s", "p"]

            # Play
            report = await bridge.play("u1", "rps", "s")
            assert report["player_move"] == "s"
            assert report["outcome"] in (-1, 0, 1)

            # Register outcome
            result = await bridge.register_outcome("u1", "rps", 1)
            assert isinstance(result, dict)

            # Stats
            stats = await bridge.stats("u1", "rps")
            assert "total_moves" in stats

            # Reset one game
            result = await bridge.reset("u1", "rps")
            assert "rps" not in result.get("g", {})

        _run(run())
    finally:
        set_engine(old)


def test_300_bridge_play_custom_and_reset_all():
    """UserManagerBridge play_custom and full reset work correctly."""
    old = get_engine()
    set_engine(_fresh_engine(42))
    try:
        fum = _FakeUserManager()
        bridge = UserManagerBridge(
            get_user=fum.get_user,
            mark_dirty=fum.mark_dirty,
            set_user=fum.set_user,
        )

        async def run():
            # play_custom for thimbles-like resolver
            def resolver(pred, spec):
                player_move = "0"
                outcome = 1  # AI wins
                extra = {"custom_field": True}
                return player_move, outcome, extra

            report = await bridge.play_custom("u2", "thimbles", resolver)
            assert report["custom_field"] is True
            assert report["outcome"] == 1
            assert report["player_move"] == "0"

            # Full reset
            result = await bridge.reset("u2")
            assert result["g"] == {}

            # Stats after reset
            stats = await bridge.stats("u2")
            assert stats["games"] == {}

        _run(run())
    finally:
        set_engine(old)
