"""
test_game_ai_core.py – 100 pytest tests for game_ai.py core API.
Covers GameSpec, GameRegistry, pre-registered games, default memory helpers,
and AIMemory construction / querying / mutation.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import copy
import math
import random
import logging
import pytest

from game_ai import (
    GameSpec,
    GameRegistry,
    AIMemory,
    AIMemoryContainer,
    default_ai_memory,
    default_game_memory,
    THIMBLES,
    RPS,
    COINFLIP,
    AI_MEMORY_SCHEMA_VERSION,
    MAX_HISTORY_LEN,
    MAX_OUTCOME_LEN,
    TRANSITION_DECAY,
    TRANSITION_MIN_COUNT,
    _OUTCOME_CHARS,
    _safe_int,
    _safe_float,
)


# =====================================================================
# HELPERS
# =====================================================================

def _make_rps():
    """Fresh RPS-like GameSpec (not touching the global registry)."""
    return GameSpec(
        key="test_rps",
        name="Test RPS",
        moves=["r", "s", "p"],
        beats={"r": ["s"], "s": ["p"], "p": ["r"]},
    )


# =====================================================================
# GameSpec creation, validation, dedup, beats normalisation (1-15)
# =====================================================================

def test_001_gamespec_basic_creation():
    spec = _make_rps()
    assert spec.key == "test_rps"
    assert spec.moves == ["r", "s", "p"]


def test_002_gamespec_empty_moves_raises():
    with pytest.raises(ValueError, match="не может быть пустым"):
        GameSpec(key="bad", name="Bad", moves=[])


def test_003_gamespec_multichar_move_raises():
    with pytest.raises(ValueError, match="ровно 1 символа"):
        GameSpec(key="bad", name="Bad", moves=["ab"])


def test_004_gamespec_non_string_move_raises():
    with pytest.raises(ValueError):
        GameSpec(key="bad", name="Bad", moves=[1])  # type: ignore[list-item]


def test_005_gamespec_dedup_preserves_order():
    spec = GameSpec(key="dup", name="Dup", moves=["a", "b", "a", "c", "b"])
    assert spec.moves == ["a", "b", "c"]


def test_006_gamespec_beats_normalised_to_known_moves():
    spec = GameSpec(
        key="norm", name="Norm", moves=["a", "b"],
        beats={"a": ["b", "x"], "b": ["a"]},
    )
    assert spec.beats["a"] == ["b"]  # "x" dropped


def test_007_gamespec_self_beat_removed(caplog):
    with caplog.at_level(logging.WARNING, logger="game_ai"):
        spec = GameSpec(
            key="selfbeat", name="SB", moves=["a", "b"],
            beats={"a": ["a", "b"]},
        )
    assert "a" not in spec.beats["a"]
    assert "b" in spec.beats["a"]


def test_008_gamespec_empty_beats():
    spec = GameSpec(key="eb", name="EB", moves=["0", "1"])
    assert spec.beats == {"0": [], "1": []}


def test_009_gamespec_symmetric_default_true():
    spec = GameSpec(key="sym", name="Sym", moves=["a"])
    assert spec.symmetric is True


def test_010_gamespec_max_order_default():
    spec = GameSpec(key="mo", name="MO", moves=["a"])
    assert spec.max_order == 2


def test_011_gamespec_custom_max_order():
    spec = GameSpec(key="co", name="CO", moves=["a"], max_order=3)
    assert spec.max_order == 3


def test_012_gamespec_beats_missing_move_key_filled_empty():
    spec = GameSpec(key="fill", name="Fill", moves=["a", "b", "c"], beats={"a": ["b"]})
    assert spec.beats["b"] == []
    assert spec.beats["c"] == []


def test_013_gamespec_has_beats_table_true():
    spec = _make_rps()
    assert spec.has_beats_table() is True


def test_014_gamespec_has_beats_table_false():
    spec = GameSpec(key="nb", name="NB", moves=["0", "1"])
    assert spec.has_beats_table() is False


def test_015_gamespec_single_move_no_beats():
    spec = GameSpec(key="one", name="One", moves=["x"])
    assert spec.moves == ["x"]
    assert spec.beats == {"x": []}


# =====================================================================
# GameSpec.is_valid_move, counter_move, outcome, all_counters (16-30)
# =====================================================================

def test_016_is_valid_move_true():
    spec = _make_rps()
    assert spec.is_valid_move("r") is True


def test_017_is_valid_move_false():
    spec = _make_rps()
    assert spec.is_valid_move("z") is False


def test_018_counter_move_returns_correct():
    spec = _make_rps()
    rng = random.Random(42)
    counter = spec.counter_move("r", rng)
    # "r" is beaten by "p"
    assert counter == "p"


def test_019_counter_move_no_counter_returns_random():
    spec = GameSpec(key="nobeat", name="NB", moves=["a", "b"])
    rng = random.Random(0)
    move = spec.counter_move("a", rng)
    assert move in spec.moves


def test_020_outcome_win():
    spec = _make_rps()
    assert spec.outcome("r", "s") == 1


def test_021_outcome_loss():
    spec = _make_rps()
    assert spec.outcome("r", "p") == -1


def test_022_outcome_draw():
    spec = _make_rps()
    assert spec.outcome("r", "r") == 0


def test_023_outcome_no_beats_same_is_draw():
    spec = GameSpec(key="d", name="D", moves=["0", "1"])
    assert spec.outcome("0", "0") == 0


def test_024_outcome_no_beats_diff_is_draw():
    spec = GameSpec(key="d2", name="D2", moves=["0", "1"])
    assert spec.outcome("0", "1") == 0


def test_025_all_counters_rps():
    spec = _make_rps()
    assert spec.all_counters("s") == ["r"]


def test_026_all_counters_empty_beats():
    spec = GameSpec(key="e", name="E", moves=["a", "b"])
    assert spec.all_counters("a") == []


def test_027_all_counters_multiple():
    spec = GameSpec(
        key="multi", name="Multi",
        moves=["a", "b", "c"],
        beats={"a": ["c"], "b": ["c"]},
    )
    assert spec.all_counters("c") == ["a", "b"]


def test_028_counter_move_deterministic_with_seed():
    spec = _make_rps()
    results = [spec.counter_move("s", random.Random(99)) for _ in range(5)]
    assert all(r == results[0] for r in results)


def test_029_outcome_symmetric_rps():
    spec = _make_rps()
    pairs = [("r", "s"), ("s", "p"), ("p", "r")]
    for ai, pl in pairs:
        assert spec.outcome(ai, pl) == 1
        assert spec.outcome(pl, ai) == -1


def test_030_counter_move_uses_rng_arg():
    spec = _make_rps()
    rng1 = random.Random(1)
    rng2 = random.Random(1)
    assert spec.counter_move("p", rng1) == spec.counter_move("p", rng2)


# =====================================================================
# GameRegistry (31-40)
# =====================================================================

def test_031_registry_has_registered():
    assert GameRegistry.has("rps") is True


def test_032_registry_get_returns_spec():
    spec = GameRegistry.get("rps")
    assert isinstance(spec, GameSpec)
    assert spec.key == "rps"


def test_033_registry_has_missing():
    assert GameRegistry.has("nonexistent_game_xyz") is False


def test_034_registry_get_missing_raises():
    with pytest.raises(KeyError, match="nonexistent_game_xyz"):
        GameRegistry.get("nonexistent_game_xyz")


def test_035_registry_all_returns_dict():
    games = GameRegistry.all()
    assert isinstance(games, dict)
    assert "rps" in games


def test_036_registry_all_is_copy():
    a = GameRegistry.all()
    b = GameRegistry.all()
    assert a is not b


def test_037_registry_register_new():
    spec = GameSpec(key="__test_37__", name="T37", moves=["x", "y"])
    result = GameRegistry.register(spec)
    assert result is spec
    assert GameRegistry.has("__test_37__")
    # Cleanup
    del GameRegistry._games["__test_37__"]


def test_038_registry_re_registration_warning(caplog):
    spec = GameSpec(key="__test_38__", name="T38", moves=["a"])
    GameRegistry.register(spec)
    with caplog.at_level(logging.WARNING, logger="game_ai"):
        GameRegistry.register(GameSpec(key="__test_38__", name="T38v2", moves=["b"]))
    assert any("перерегистрирована" in r.message for r in caplog.records)
    # Cleanup
    del GameRegistry._games["__test_38__"]


def test_039_registry_get_after_register():
    spec = GameSpec(key="__test_39__", name="T39", moves=["z"])
    GameRegistry.register(spec)
    assert GameRegistry.get("__test_39__").name == "T39"
    del GameRegistry._games["__test_39__"]


def test_040_registry_all_contains_pre_registered():
    games = GameRegistry.all()
    assert "thimbles" in games
    assert "rps" in games
    assert "coinflip" in games


# =====================================================================
# Pre-registered games: THIMBLES, RPS, COINFLIP (41-55)
# =====================================================================

def test_041_thimbles_moves():
    assert THIMBLES.moves == ["0", "1", "2"]


def test_042_thimbles_empty_beats():
    assert THIMBLES.has_beats_table() is False


def test_043_thimbles_not_symmetric():
    assert THIMBLES.symmetric is False


def test_044_rps_moves():
    assert RPS.moves == ["r", "s", "p"]


def test_045_rps_beats_rock():
    assert "s" in RPS.beats["r"]


def test_046_rps_beats_scissors():
    assert "p" in RPS.beats["s"]


def test_047_rps_beats_paper():
    assert "r" in RPS.beats["p"]


def test_048_rps_symmetric():
    assert RPS.symmetric is True


def test_049_rps_has_beats_table():
    assert RPS.has_beats_table() is True


def test_050_coinflip_moves():
    assert COINFLIP.moves == ["0", "1"]


def test_051_coinflip_empty_beats():
    assert COINFLIP.has_beats_table() is False


def test_052_coinflip_not_symmetric():
    assert COINFLIP.symmetric is False


def test_053_thimbles_key():
    assert THIMBLES.key == "thimbles"


def test_054_rps_key():
    assert RPS.key == "rps"


def test_055_coinflip_key():
    assert COINFLIP.key == "coinflip"


# =====================================================================
# default_game_memory / default_ai_memory (56-60)
# =====================================================================

def test_056_default_game_memory_structure():
    gm = default_game_memory()
    assert gm["h"] == ""
    assert gm["o"] == ""
    assert gm["t"] == {}
    assert gm["t2"] == {}
    assert gm["n"] == 0


def test_057_default_game_memory_stats():
    gm = default_game_memory()
    assert gm["w"] == 0
    assert gm["l"] == 0
    assert gm["d"] == 0


def test_058_default_game_memory_meta():
    gm = default_game_memory()
    assert gm["streak"] == 0
    assert gm["prof"] == "unknown"
    assert gm["last"] == 0


def test_059_default_ai_memory_version():
    am = default_ai_memory()
    assert am["v"] == AI_MEMORY_SCHEMA_VERSION


def test_060_default_ai_memory_empty_games():
    am = default_ai_memory()
    assert am["g"] == {}


# =====================================================================
# AIMemory construction & field validation (61-75)
# =====================================================================

def test_061_aimemory_from_none():
    mem = AIMemory(None)
    assert mem.h == ""
    assert mem.n == 0


def test_062_aimemory_from_empty_dict():
    mem = AIMemory({})
    assert mem.h == ""
    assert mem.o == ""
    assert mem.t == {}
    assert mem.t2 == {}


def test_063_aimemory_from_valid_data():
    mem = AIMemory({"h": "rsp", "n": 3, "w": 1, "l": 1, "d": 1})
    assert mem.h == "rsp"
    assert mem.n == 3


def test_064_aimemory_negative_n_clamped():
    mem = AIMemory({"n": -5})
    assert mem.n == 0


def test_065_aimemory_negative_w_clamped():
    mem = AIMemory({"w": -1})
    assert mem.w == 0


def test_066_aimemory_negative_l_clamped():
    mem = AIMemory({"l": -10})
    assert mem.l == 0


def test_067_aimemory_negative_d_clamped():
    mem = AIMemory({"d": -3})
    assert mem.d == 0


def test_068_aimemory_last_non_negative():
    mem = AIMemory({"last": -100})
    assert mem.last == 0


def test_069_aimemory_streak_can_be_negative():
    mem = AIMemory({"streak": -5})
    assert mem.streak == -5


def test_070_aimemory_history_truncated_to_max():
    long_h = "r" * (MAX_HISTORY_LEN + 50)
    mem = AIMemory({"h": long_h})
    assert len(mem.h) == MAX_HISTORY_LEN


def test_071_aimemory_outcome_filtered():
    mem = AIMemory({"o": "WLDxyz"})
    assert mem.o == "WLD"  # only W/L/D kept


def test_072_aimemory_outcome_truncated_to_max():
    long_o = "W" * (MAX_OUTCOME_LEN + 50)
    mem = AIMemory({"o": long_o})
    assert len(mem.o) == MAX_OUTCOME_LEN


def test_073_aimemory_prof_default():
    mem = AIMemory({})
    assert mem.prof == "unknown"


def test_074_aimemory_prof_from_data():
    mem = AIMemory({"prof": "sticky"})
    assert mem.prof == "sticky"


def test_075_aimemory_to_dict_roundtrip():
    orig = {"h": "rsp", "o": "WLD", "t": {"r|s": 1.5}, "t2": {},
            "n": 3, "w": 1, "l": 1, "d": 1, "last": 100, "streak": 2, "prof": "balanced"}
    mem = AIMemory(orig)
    d = mem.to_dict()
    mem2 = AIMemory(d)
    assert mem2.h == mem.h
    assert mem2.n == mem.n
    assert mem2.w == mem.w


# =====================================================================
# AIMemory: _load_counts edge cases, history_list, last_move, etc (76-90)
# =====================================================================

def test_076_load_counts_non_dict():
    result = AIMemory._load_counts("not a dict")
    assert result == {}


def test_077_load_counts_none():
    result = AIMemory._load_counts(None)
    assert result == {}


def test_078_load_counts_filters_zero():
    result = AIMemory._load_counts({"a": 0, "b": 1.5})
    assert "a" not in result
    assert result["b"] == 1.5


def test_079_load_counts_filters_negative():
    result = AIMemory._load_counts({"x": -2.0, "y": 3.0})
    assert "x" not in result
    assert result["y"] == 3.0


def test_080_load_counts_converts_string_values():
    result = AIMemory._load_counts({"k": "2.5"})
    assert result["k"] == 2.5


def test_081_history_list():
    mem = AIMemory({"h": "rsp"})
    assert mem.history_list() == ["r", "s", "p"]


def test_082_history_list_empty():
    mem = AIMemory({})
    assert mem.history_list() == []


def test_083_last_move():
    mem = AIMemory({"h": "rsp"})
    assert mem.last_move() == "p"


def test_084_last_move_empty():
    mem = AIMemory({})
    assert mem.last_move() is None


def test_085_last_two():
    mem = AIMemory({"h": "rsp"})
    assert mem.last_two() == "sp"


def test_086_last_two_single_char():
    mem = AIMemory({"h": "r"})
    assert mem.last_two() is None


def test_087_total_games():
    mem = AIMemory({"w": 5, "l": 3, "d": 2})
    assert mem.total_games() == 10


def test_088_winrate_ai_with_games():
    mem = AIMemory({"w": 6, "l": 3, "d": 1})
    assert abs(mem.winrate_ai() - 0.6) < 1e-9


def test_089_winrate_ai_zero_games():
    mem = AIMemory({})
    assert mem.winrate_ai() == 0.0


def test_090_from_dict_factory():
    mem = AIMemory.from_dict({"h": "abc", "n": 3})
    assert mem.h == "abc"
    assert mem.n == 3


# =====================================================================
# AIMemory: record_move, history trimming, decay, record_outcome (91-100)
# =====================================================================

def test_091_record_move_updates_history():
    mem = AIMemory({"h": "rs"})
    mem.record_move("p")
    assert mem.h.endswith("rsp")


def test_092_record_move_increments_n():
    mem = AIMemory({"n": 5})
    mem.record_move("r")
    assert mem.n == 6


def test_093_record_move_updates_transitions_order1():
    mem = AIMemory({"h": "r"})
    mem.record_move("s")
    assert "r|s" in mem.t
    assert mem.t["r|s"] >= 1.0


def test_094_record_move_updates_transitions_order2():
    mem = AIMemory({"h": "rs"})
    mem.record_move("p")
    assert "rs|p" in mem.t2


def test_095_record_move_trims_long_history():
    mem = AIMemory({"h": "r" * MAX_HISTORY_LEN})
    mem.record_move("s")
    assert len(mem.h) == MAX_HISTORY_LEN
    assert mem.h[-1] == "s"


def test_096_record_move_decay_reduces_counts():
    mem = AIMemory({"h": "r", "t": {"r|s": 10.0}})
    mem.record_move("s")
    # After decay, old value should be 10.0 * TRANSITION_DECAY then +1
    expected_approx = 10.0 * TRANSITION_DECAY + 1.0
    assert abs(mem.t["r|s"] - expected_approx) < 0.01


def test_097_record_outcome_win():
    mem = AIMemory({})
    mem.record_outcome(1)
    assert mem.w == 1
    assert mem.l == 0
    assert mem.d == 0
    assert mem.o == "W"


def test_098_record_outcome_loss():
    mem = AIMemory({})
    mem.record_outcome(-1)
    assert mem.l == 1
    assert mem.o == "L"


def test_099_record_outcome_draw():
    mem = AIMemory({})
    mem.record_outcome(0)
    assert mem.d == 1
    assert mem.o == "D"


def test_100_record_outcome_streak_logic():
    mem = AIMemory({})
    mem.record_outcome(1)
    assert mem.streak == 1
    mem.record_outcome(1)
    assert mem.streak == 2
    mem.record_outcome(-1)
    assert mem.streak == -1
    mem.record_outcome(-1)
    assert mem.streak == -2
    mem.record_outcome(0)
    assert mem.streak == -1
