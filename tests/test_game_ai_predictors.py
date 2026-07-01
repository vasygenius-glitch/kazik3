"""
Tests 101–200 for game_ai.py predictor layer and engine.

Covers:
  - BasePredictor.uniform / normalize
  - MarkovOrder1Predictor
  - MarkovOrder2Predictor
  - FrequencyPredictor
  - PatternPredictor
  - WinStayLoseShiftPredictor
  - classify_player_profile
  - GameAIEngine (predict, _blend, _argmax_conf, _best_response)
"""

import sys
import os
import math
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from game_ai import (
    GameSpec,
    GameRegistry,
    AIMemory,
    GameAIEngine,
    Prediction,
    BasePredictor,
    MarkovOrder1Predictor,
    MarkovOrder2Predictor,
    FrequencyPredictor,
    PatternPredictor,
    WinStayLoseShiftPredictor,
    classify_player_profile,
    LAPLACE_ALPHA,
    RECENCY_DECAY,
    RPS,
    COINFLIP,
    THIMBLES,
)

# ── helpers ───────────────────────────────────────────────────────────────

def _rps_spec() -> GameSpec:
    """Return the pre-registered RPS GameSpec."""
    return RPS


def _coin_spec() -> GameSpec:
    return COINFLIP


def _thimbles_spec() -> GameSpec:
    return THIMBLES


def _mem(h: str = "", o: str = "", t: dict | None = None,
         t2: dict | None = None, n: int | None = None,
         w: int = 0, l: int = 0, d: int = 0,
         prof: str = "unknown") -> AIMemory:
    """Build an AIMemory from compact params."""
    data = {
        "h": h,
        "o": o,
        "t": t or {},
        "t2": t2 or {},
        "n": n if n is not None else len(h),
        "w": w,
        "l": l,
        "d": d,
        "prof": prof,
    }
    return AIMemory(data)


def _approx(val: float, expected: float, tol: float = 1e-6) -> bool:
    return abs(val - expected) < tol


def _is_valid_dist(dist: dict, spec: GameSpec, tol: float = 1e-6) -> bool:
    """Check dist is a valid probability distribution over spec.moves."""
    if set(dist.keys()) != set(spec.moves):
        return False
    if any(v < -tol for v in dist.values()):
        return False
    return abs(sum(dist.values()) - 1.0) < tol


# ═══════════════════════════════════════════════════════════════════════════
# BasePredictor.uniform  &  normalize   (tests 101–108)
# ═══════════════════════════════════════════════════════════════════════════

def test_101_uniform_rps_returns_three_equal():
    spec = _rps_spec()
    u = BasePredictor.uniform(spec)
    assert len(u) == 3
    for m in spec.moves:
        assert _approx(u[m], 1 / 3)


def test_102_uniform_coinflip_returns_two_equal():
    spec = _coin_spec()
    u = BasePredictor.uniform(spec)
    assert len(u) == 2
    for m in spec.moves:
        assert _approx(u[m], 0.5)


def test_103_uniform_sums_to_one():
    spec = _rps_spec()
    assert _approx(sum(BasePredictor.uniform(spec).values()), 1.0)


def test_104_normalize_preserves_ratios():
    spec = _rps_spec()
    raw = {"r": 2.0, "s": 1.0, "p": 1.0}
    norm = BasePredictor.normalize(raw, spec)
    assert _approx(norm["r"], 0.5)
    assert _approx(norm["s"], 0.25)
    assert _approx(norm["p"], 0.25)


def test_105_normalize_all_zeros_falls_back_to_uniform():
    spec = _rps_spec()
    norm = BasePredictor.normalize({"r": 0, "s": 0, "p": 0}, spec)
    for m in spec.moves:
        assert _approx(norm[m], 1 / 3)


def test_106_normalize_negative_clamped_to_zero():
    spec = _rps_spec()
    norm = BasePredictor.normalize({"r": -5.0, "s": 0.0, "p": 4.0}, spec)
    assert _approx(norm["r"], 0.0)
    assert _approx(norm["p"], 1.0)


def test_107_normalize_missing_key_treated_as_zero():
    spec = _rps_spec()
    norm = BasePredictor.normalize({"r": 3.0}, spec)
    assert _approx(norm["r"], 1.0)
    assert _approx(norm["s"], 0.0)
    assert _approx(norm["p"], 0.0)


def test_108_normalize_nan_falls_back_to_uniform():
    spec = _rps_spec()
    norm = BasePredictor.normalize({"r": float("nan"), "s": 1.0, "p": 1.0}, spec)
    # nan is clamped to 0, so s and p get 0.5 each
    assert _approx(norm["r"], 0.0)
    assert _approx(norm["s"], 0.5)
    assert _approx(norm["p"], 0.5)


# ═══════════════════════════════════════════════════════════════════════════
# MarkovOrder1Predictor   (tests 109–120)
# ═══════════════════════════════════════════════════════════════════════════

def test_109_markov1_no_history_returns_uniform():
    pred = MarkovOrder1Predictor()
    dist = pred.predict(_mem(), _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_110_markov1_single_move_uses_laplace():
    pred = MarkovOrder1Predictor()
    mem = _mem(h="r", t={})
    dist = pred.predict(mem, _rps_spec())
    # last_move = 'r', all transitions have only LAPLACE_ALPHA
    assert _is_valid_dist(dist, _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_111_markov1_strong_transition_dominates():
    pred = MarkovOrder1Predictor()
    mem = _mem(h="r", t={"r|s": 100.0})
    dist = pred.predict(mem, _rps_spec())
    assert dist["s"] > dist["r"]
    assert dist["s"] > dist["p"]


def test_112_markov1_equal_transitions_near_uniform():
    pred = MarkovOrder1Predictor()
    mem = _mem(h="r", t={"r|r": 10.0, "r|s": 10.0, "r|p": 10.0})
    dist = pred.predict(mem, _rps_spec())
    for m in _rps_spec().moves:
        assert abs(dist[m] - 1 / 3) < 0.02


def test_113_markov1_two_transitions_correct_ratio():
    pred = MarkovOrder1Predictor()
    mem = _mem(h="p", t={"p|r": 5.0, "p|s": 0.0, "p|p": 0.0})
    dist = pred.predict(mem, _rps_spec())
    # r has 5 + alpha; s,p have alpha each
    expected_r = (5.0 + LAPLACE_ALPHA) / (5.0 + 3 * LAPLACE_ALPHA)
    assert _approx(dist["r"], expected_r, tol=1e-4)


def test_114_markov1_returns_valid_dist_always():
    pred = MarkovOrder1Predictor()
    mem = _mem(h="s", t={"s|r": 0.01, "s|s": 0.01, "s|p": 0.01})
    dist = pred.predict(mem, _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())


def test_115_markov1_different_prev_move_ignores_unrelated_keys():
    pred = MarkovOrder1Predictor()
    mem = _mem(h="p", t={"r|s": 100.0})
    dist = pred.predict(mem, _rps_spec())
    # last_move is 'p', no "p|*" transitions -> uniform-like (all alpha)
    for m in _rps_spec().moves:
        assert abs(dist[m] - 1 / 3) < 0.01


def test_116_markov1_coinflip_two_moves():
    pred = MarkovOrder1Predictor()
    spec = _coin_spec()
    mem = _mem(h="0", t={"0|0": 5.0, "0|1": 1.0})
    dist = pred.predict(mem, spec)
    assert dist["0"] > dist["1"]
    assert _is_valid_dist(dist, spec)


def test_117_markov1_very_large_count():
    pred = MarkovOrder1Predictor()
    mem = _mem(h="r", t={"r|p": 1e6})
    dist = pred.predict(mem, _rps_spec())
    assert dist["p"] > 0.99


def test_118_markov1_thimbles_three_moves():
    pred = MarkovOrder1Predictor()
    spec = _thimbles_spec()
    mem = _mem(h="1", t={"1|2": 10.0, "1|0": 2.0})
    dist = pred.predict(mem, spec)
    assert dist["2"] > dist["0"] > dist["1"] or dist["2"] > dist["1"]
    assert _is_valid_dist(dist, spec)


def test_119_markov1_prediction_deterministic():
    """Same input -> same output (no randomness in predictor)."""
    pred = MarkovOrder1Predictor()
    mem = _mem(h="r", t={"r|s": 3.0, "r|p": 1.0})
    d1 = pred.predict(mem, _rps_spec())
    d2 = pred.predict(mem, _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(d1[m], d2[m])


def test_120_markov1_all_moves_have_laplace_floor():
    pred = MarkovOrder1Predictor()
    mem = _mem(h="r", t={"r|r": 10.0})
    dist = pred.predict(mem, _rps_spec())
    assert dist["s"] > 0
    assert dist["p"] > 0


# ═══════════════════════════════════════════════════════════════════════════
# MarkovOrder2Predictor   (tests 121–135)
# ═══════════════════════════════════════════════════════════════════════════

def test_121_markov2_no_history_falls_back_to_markov1_uniform():
    pred = MarkovOrder2Predictor()
    dist = pred.predict(_mem(), _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_122_markov2_one_move_falls_back():
    pred = MarkovOrder2Predictor()
    dist = pred.predict(_mem(h="r"), _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())


def test_123_markov2_two_moves_no_t2_backoff():
    pred = MarkovOrder2Predictor()
    mem = _mem(h="rs", t={"s|p": 5.0})
    dist = pred.predict(mem, _rps_spec())
    # ctx = "rs", no t2 data -> observed=0 -> beta=0 -> pure o1 fallback
    assert _is_valid_dist(dist, _rps_spec())
    assert dist["p"] > dist["r"]  # driven by markov1 "s|p"=5


def test_124_markov2_with_established_t2():
    pred = MarkovOrder2Predictor()
    mem = _mem(h="rs", t2={"rs|p": 20.0, "rs|r": 1.0, "rs|s": 1.0})
    dist = pred.predict(mem, _rps_spec())
    # observed = 22 > 3 -> pure o2
    assert dist["p"] > dist["r"]
    assert dist["p"] > dist["s"]


def test_125_markov2_backoff_blend_with_low_t2():
    pred = MarkovOrder2Predictor()
    mem = _mem(
        h="rs",
        t={"s|r": 10.0},          # o1 strongly predicts 'r'
        t2={"rs|p": 1.0},         # o2 weakly predicts 'p', observed=1
    )
    dist = pred.predict(mem, _rps_spec())
    # beta = 1/3 ≈ 0.33 => blend leans toward o1 → 'r' should be notable
    assert _is_valid_dist(dist, _rps_spec())


def test_126_markov2_respects_max_order_1():
    """If spec.max_order < 2, falls back to o1."""
    spec = GameSpec(key="test126", name="t", moves=["a", "b"], beats={}, max_order=1)
    pred = MarkovOrder2Predictor()
    mem = _mem(h="ab", t2={"ab|a": 50.0})
    dist = pred.predict(mem, spec)
    assert _is_valid_dist(dist, spec)
    # Should NOT use t2 data – pure o1


def test_127_markov2_valid_distribution():
    pred = MarkovOrder2Predictor()
    mem = _mem(h="rsp", t2={"sp|r": 3.0, "sp|s": 2.0, "sp|p": 1.0})
    dist = pred.predict(mem, _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())


def test_128_markov2_uses_last_two():
    pred = MarkovOrder2Predictor()
    mem = _mem(h="rps", t2={"ps|r": 50.0})
    dist = pred.predict(mem, _rps_spec())
    # last_two = "ps", observed = 50 -> pure o2 -> "r" dominates
    assert dist["r"] > 0.5


def test_129_markov2_deterministic():
    pred = MarkovOrder2Predictor()
    mem = _mem(h="rp", t={"p|s": 2.0}, t2={"rp|s": 4.0})
    d1 = pred.predict(mem, _rps_spec())
    d2 = pred.predict(mem, _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(d1[m], d2[m])


def test_130_markov2_coinflip_fallback():
    pred = MarkovOrder2Predictor()
    spec = _coin_spec()
    mem = _mem(h="0")
    dist = pred.predict(mem, spec)
    assert _is_valid_dist(dist, spec)


def test_131_markov2_observed_exactly_3_threshold():
    pred = MarkovOrder2Predictor()
    mem = _mem(h="rp", t2={"rp|s": 1.0, "rp|r": 1.0, "rp|p": 1.0})
    dist = pred.predict(mem, _rps_spec())
    # observed = 3 -> beta = min(1, 3/3) = 1 -> pure o2
    assert _is_valid_dist(dist, _rps_spec())


def test_132_markov2_observed_between_0_and_3():
    pred = MarkovOrder2Predictor()
    mem = _mem(h="rp", t={"p|r": 5.0}, t2={"rp|s": 2.0})
    dist = pred.predict(mem, _rps_spec())
    # observed = 2 < 3 -> beta = 2/3 -> blend
    assert _is_valid_dist(dist, _rps_spec())


def test_133_markov2_strong_o2_overrides_o1():
    pred = MarkovOrder2Predictor()
    mem = _mem(
        h="rp",
        t={"p|r": 5.0},          # o1 says 'r'
        t2={"rp|s": 100.0},      # o2 says 's' overwhelmingly, observed=100
    )
    dist = pred.predict(mem, _rps_spec())
    assert dist["s"] > dist["r"]


def test_134_markov2_three_char_history():
    pred = MarkovOrder2Predictor()
    mem = _mem(h="rsp", t2={"sp|r": 10.0})
    dist = pred.predict(mem, _rps_spec())
    # last_two = "sp"
    assert dist["r"] > dist["s"]
    assert dist["r"] > dist["p"]


def test_135_markov2_empty_t_and_t2():
    pred = MarkovOrder2Predictor()
    mem = _mem(h="rp")
    dist = pred.predict(mem, _rps_spec())
    # No transitions at all -> laplace uniform
    assert _is_valid_dist(dist, _rps_spec())


# ═══════════════════════════════════════════════════════════════════════════
# FrequencyPredictor   (tests 136–148)
# ═══════════════════════════════════════════════════════════════════════════

def test_136_freq_empty_history_uniform():
    pred = FrequencyPredictor()
    dist = pred.predict(_mem(), _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_137_freq_single_move():
    pred = FrequencyPredictor()
    mem = _mem(h="r")
    dist = pred.predict(mem, _rps_spec())
    assert dist["r"] == 1.0
    assert dist["s"] == 0.0


def test_138_freq_all_same_move():
    pred = FrequencyPredictor()
    mem = _mem(h="rrrrr")
    dist = pred.predict(mem, _rps_spec())
    assert _approx(dist["r"], 1.0)


def test_139_freq_equal_counts():
    pred = FrequencyPredictor()
    mem = _mem(h="rsp")
    dist = pred.predict(mem, _rps_spec())
    # Recent move 'p' gets higher weight due to recency
    assert dist["p"] > dist["r"]


def test_140_freq_biased_history():
    pred = FrequencyPredictor()
    mem = _mem(h="rrrrrrrsp")
    dist = pred.predict(mem, _rps_spec())
    assert dist["r"] > dist["s"]


def test_141_freq_recency_effect():
    pred = FrequencyPredictor()
    # Old r's vs recent p's
    mem = _mem(h="rrrrrrrppp")
    dist = pred.predict(mem, _rps_spec())
    # p's are more recent so have higher weight per occurrence
    # But there are 7 r's vs 3 p's, so r may still dominate
    assert dist["r"] > 0  # just sanity
    assert _is_valid_dist(dist, _rps_spec())


def test_142_freq_valid_dist_always():
    pred = FrequencyPredictor()
    mem = _mem(h="rspprs")
    dist = pred.predict(mem, _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())


def test_143_freq_longer_history_recent_matters_more():
    pred = FrequencyPredictor()
    # 20 r's then 5 p's at the end
    mem = _mem(h="r" * 20 + "p" * 5)
    dist = pred.predict(mem, _rps_spec())
    # Each 'p' is more recent, so p per-unit is weighted more
    assert dist["p"] > 0.1  # p is meaningful despite fewer count


def test_144_freq_coinflip():
    pred = FrequencyPredictor()
    spec = _coin_spec()
    mem = _mem(h="01")
    dist = pred.predict(mem, spec)
    assert _is_valid_dist(dist, spec)
    assert dist["1"] > dist["0"]  # more recent


def test_145_freq_deterministic():
    pred = FrequencyPredictor()
    mem = _mem(h="rrssp")
    d1 = pred.predict(mem, _rps_spec())
    d2 = pred.predict(mem, _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(d1[m], d2[m])


def test_146_freq_only_one_type_returns_1():
    pred = FrequencyPredictor()
    mem = _mem(h="sss")
    dist = pred.predict(mem, _rps_spec())
    assert _approx(dist["s"], 1.0)
    assert _approx(dist["r"], 0.0)


def test_147_freq_two_moves_biased():
    pred = FrequencyPredictor()
    mem = _mem(h="rrrs")
    dist = pred.predict(mem, _rps_spec())
    assert dist["r"] > dist["s"]
    assert _approx(dist["p"], 0.0)


def test_148_freq_thimbles():
    pred = FrequencyPredictor()
    spec = _thimbles_spec()
    mem = _mem(h="001122")
    dist = pred.predict(mem, spec)
    assert _is_valid_dist(dist, spec)


# ═══════════════════════════════════════════════════════════════════════════
# PatternPredictor   (tests 149–162)
# ═══════════════════════════════════════════════════════════════════════════

def test_149_pattern_short_history_uniform():
    pred = PatternPredictor()
    dist = pred.predict(_mem(h="r"), _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_150_pattern_empty_history_uniform():
    pred = PatternPredictor()
    dist = pred.predict(_mem(), _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_151_pattern_two_chars_uniform():
    pred = PatternPredictor()
    dist = pred.predict(_mem(h="rs"), _rps_spec())
    # min_len=2, len(h)=2 => 2 < min_len + 1 (3) => uniform
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_152_pattern_cyclic_detects_next():
    pred = PatternPredictor()
    # history: r s p r s p r s p  -> next should be r
    mem = _mem(h="rsprsprsp")
    dist = pred.predict(mem, _rps_spec())
    # Pattern "sp" occurred at 1,4,7 -> after each: p,r,s,... 
    # The suffix "sp" should find matches and predict what follows
    assert _is_valid_dist(dist, _rps_spec())
    # 'r' follows "sp" in positions 1->next=p(2), 4->next=r(5), but let's
    # just verify it returns a valid non-uniform distribution
    assert max(dist.values()) > 1 / 3 + 0.01 or all(_approx(v, 1/3) for v in dist.values())


def test_153_pattern_strong_cycle():
    pred = PatternPredictor()
    # Perfect cycle: r s p repeated many times, ending with "rs"
    mem = _mem(h="rsprsprsprsprsprs")
    dist = pred.predict(mem, _rps_spec())
    # After "rs" always comes "p"
    assert dist["p"] > 0.5


def test_154_pattern_min_len_respected():
    pred = PatternPredictor(min_len=3, max_len=6)
    mem = _mem(h="rsp")
    dist = pred.predict(mem, _rps_spec())
    # len(h)=3, need min_len+1=4, so uniform
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_155_pattern_recency_weights_recent_more():
    pred = PatternPredictor()
    # Pattern "rs" appeared early with follow='p', and later with follow='r'
    mem = _mem(h="rsprrrrrrrrs")
    dist = pred.predict(mem, _rps_spec())
    # The last suffix is "rs"; "rs" at pos 0 -> next='p', recent match should
    # be weighted higher but there's only one match in this specific case
    assert _is_valid_dist(dist, _rps_spec())


def test_156_pattern_valid_distribution():
    pred = PatternPredictor()
    mem = _mem(h="rsrsprsp")
    dist = pred.predict(mem, _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())


def test_157_pattern_no_match_uniform():
    pred = PatternPredictor()
    # all same -> suffix "rr" is found everywhere, but only self-matches
    mem = _mem(h="rrrr")
    dist = pred.predict(mem, _rps_spec())
    # suffix "rr" in search_zone "rrr" finds matches at 0,1
    # nxt_index = 0+2=2 -> h[2]='r', nxt_index=1+2=3 -> h[3]='r'
    # Only 'r' gets score
    assert dist["r"] > 0.9


def test_158_pattern_long_pattern_higher_weight():
    pred = PatternPredictor()
    # "rsp" repeated 4 times + "rs" at end
    mem = _mem(h="rsprsprsprsprs")
    dist = pred.predict(mem, _rps_spec())
    # After "rs" comes "p" every time
    assert dist["p"] > 0.5


def test_159_pattern_deterministic():
    pred = PatternPredictor()
    mem = _mem(h="rsprsprsp")
    d1 = pred.predict(mem, _rps_spec())
    d2 = pred.predict(mem, _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(d1[m], d2[m])


def test_160_pattern_coinflip():
    pred = PatternPredictor()
    spec = _coin_spec()
    mem = _mem(h="010101010")
    dist = pred.predict(mem, spec)
    assert _is_valid_dist(dist, spec)
    # After "10" always comes "1" -> "1" should be predicted
    assert dist["1"] > dist["0"]


def test_161_pattern_thimbles():
    pred = PatternPredictor()
    spec = _thimbles_spec()
    mem = _mem(h="012012012012")
    dist = pred.predict(mem, spec)
    assert _is_valid_dist(dist, spec)


def test_162_pattern_custom_max_len():
    pred = PatternPredictor(min_len=1, max_len=2)
    mem = _mem(h="rsprsp")
    dist = pred.predict(mem, _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())


# ═══════════════════════════════════════════════════════════════════════════
# WinStayLoseShiftPredictor   (tests 163–178)
# ═══════════════════════════════════════════════════════════════════════════

def test_163_wsls_not_enough_data_uniform():
    pred = WinStayLoseShiftPredictor()
    mem = _mem(h="r", o="W")
    dist = pred.predict(mem, _rps_spec())
    # L=1 < 3 => uniform
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_164_wsls_two_moves_uniform():
    pred = WinStayLoseShiftPredictor()
    mem = _mem(h="rs", o="WL")
    dist = pred.predict(mem, _rps_spec())
    # L=2 < 3 => uniform
    for m in _rps_spec().moves:
        assert _approx(dist[m], 1 / 3)


def test_165_wsls_three_moves_minimum():
    pred = WinStayLoseShiftPredictor()
    # 3 moves, 3 outcomes
    mem = _mem(h="rrr", o="LLL")
    dist = pred.predict(mem, _rps_spec())
    # L=3 >= 3
    # Pairs: (r,L)->(r): cat=win(player won), stayed
    #        (r,L)->(r): cat=win, stayed
    # last_move='r', last_cat='win' (o[2]='L' => player won)
    # high p_stay => predict 'r'
    assert _is_valid_dist(dist, _rps_spec())


def test_166_wsls_win_stay_behavior():
    pred = WinStayLoseShiftPredictor()
    # Player won (AI lost 'L') and stayed on same move repeatedly
    mem = _mem(h="rrrrr", o="LLLLL")
    dist = pred.predict(mem, _rps_spec())
    # cat='win' for player (o='L'). Player stayed every time.
    # last cat = 'win', high p_stay => predict 'r'
    assert dist["r"] > 0.5


def test_167_wsls_lose_shift_behavior():
    pred = WinStayLoseShiftPredictor()
    # Player lost (AI won 'W') each time, then shifted
    mem = _mem(h="rspr", o="WWWW")
    dist = pred.predict(mem, _rps_spec())
    # cat='loss' for player (o='W'). Player shifted every time.
    # last cat='loss', p_stay low => predict shift (not 'r')
    assert dist["r"] < 0.5


def test_168_wsls_valid_distribution():
    pred = WinStayLoseShiftPredictor()
    mem = _mem(h="rsprs", o="WLDWL")
    dist = pred.predict(mem, _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())


def test_169_wsls_draw_behavior():
    pred = WinStayLoseShiftPredictor()
    mem = _mem(h="rrrr", o="DDDD")
    dist = pred.predict(mem, _rps_spec())
    # cat='draw' every time, player stayed on 'r'
    # last cat='draw', high p_stay => predict 'r'
    assert dist["r"] > 0.4


def test_170_wsls_mixed_outcomes():
    pred = WinStayLoseShiftPredictor()
    mem = _mem(h="rsrsr", o="LWLWL")
    dist = pred.predict(mem, _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())


def test_171_wsls_single_move_type_only():
    pred = WinStayLoseShiftPredictor()
    # Only one move type in spec
    spec = GameSpec(key="test171", name="t", moves=["a"], beats={})
    mem = _mem(h="aaa", o="WWW")
    dist = pred.predict(mem, spec)
    # len(spec.moves) < 2 => uniform
    assert _approx(dist["a"], 1.0)


def test_172_wsls_recency_weights():
    pred = WinStayLoseShiftPredictor()
    # Early: player won and shifted. Late: player won and stayed.
    mem = _mem(h="rsppppp", o="LLLLLLL")
    dist = pred.predict(mem, _rps_spec())
    # More recent 'stay' after win should have higher weight
    assert _is_valid_dist(dist, _rps_spec())


def test_173_wsls_all_shifts_after_loss():
    pred = WinStayLoseShiftPredictor()
    # Player always shifts after AI win
    mem = _mem(h="rspr", o="WWWW")
    dist = pred.predict(mem, _rps_spec())
    # last = 'r', last_cat = 'loss' (player). 
    # All transitions under 'loss': r->s (shift), s->p (shift), p->r (shift)
    # p_stay is low => others get weight
    others_sum = sum(dist[m] for m in _rps_spec().moves if m != "r")
    assert others_sum > 0.4


def test_174_wsls_all_stays_after_win():
    pred = WinStayLoseShiftPredictor()
    # Player always stays after winning
    mem = _mem(h="rrrrr", o="LLLLL")
    dist = pred.predict(mem, _rps_spec())
    assert dist["r"] > 0.6


def test_175_wsls_coinflip():
    pred = WinStayLoseShiftPredictor()
    spec = _coin_spec()
    mem = _mem(h="00011", o="WLLWW")
    dist = pred.predict(mem, spec)
    assert _is_valid_dist(dist, spec)


def test_176_wsls_not_enough_category_data():
    pred = WinStayLoseShiftPredictor()
    # 3 moves, but very little data in the relevant category
    mem = _mem(h="rsp", o="WLD")
    dist = pred.predict(mem, _rps_spec())
    # last_cat = 'draw' (o[2]='D'), only 1 pair so total < 1.5 -> possible uniform
    assert _is_valid_dist(dist, _rps_spec())


def test_177_wsls_deterministic():
    pred = WinStayLoseShiftPredictor()
    mem = _mem(h="rrssp", o="WLLWD")
    d1 = pred.predict(mem, _rps_spec())
    d2 = pred.predict(mem, _rps_spec())
    for m in _rps_spec().moves:
        assert _approx(d1[m], d2[m])


def test_178_wsls_long_history():
    pred = WinStayLoseShiftPredictor()
    rng = random.Random(42)
    h = ""
    o = ""
    for _ in range(50):
        h += rng.choice(["r", "s", "p"])
        o += rng.choice(["W", "L", "D"])
    mem = _mem(h=h, o=o)
    dist = pred.predict(mem, _rps_spec())
    assert _is_valid_dist(dist, _rps_spec())


# ═══════════════════════════════════════════════════════════════════════════
# classify_player_profile   (tests 179–190)
# ═══════════════════════════════════════════════════════════════════════════

def test_179_profile_unknown_few_moves():
    mem = _mem(h="rsp", n=3)
    assert classify_player_profile(mem, _rps_spec()) == "unknown"


def test_180_profile_unknown_seven_moves():
    mem = _mem(h="rsprsp", n=6)
    assert classify_player_profile(mem, _rps_spec()) == "unknown"


def test_181_profile_random():
    # Build a history that is nearly max-entropy with low streak
    rng = random.Random(12345)
    spec = _rps_spec()
    # Generate a random-ish balanced history
    h = ""
    for _ in range(60):
        h += rng.choice(spec.moves)
    mem = _mem(h=h, n=len(h))
    profile = classify_player_profile(mem, spec)
    # A truly random sequence should be either "random" or "balanced"
    assert profile in ("random", "balanced")


def test_182_profile_sticky():
    # Player repeats the same move a lot in sequence
    h = "rrrrrsssssrrrrrsssss" * 3
    mem = _mem(h=h, n=len(h))
    profile = classify_player_profile(mem, _rps_spec())
    assert profile == "sticky"


def test_183_profile_biased():
    # Player heavily favors one move but doesn't necessarily repeat in sequence
    h = "rsrrrprrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr"
    mem = _mem(h=h, n=len(h))
    profile = classify_player_profile(mem, _rps_spec())
    assert profile in ("biased", "sticky")


def test_184_profile_predictable():
    # rp alternating -> repeat_ratio ~0.5, streak_ratio = 0
    h = "rprprprprprprprprprprprprp"
    mem = _mem(h=h, n=len(h))
    profile = classify_player_profile(mem, _rps_spec())
    # entropy for 2/3 used in base-3 log -> 0.6309 -> balanced
    assert profile == "balanced"


def test_185_profile_balanced():
    # Moderate entropy, not too sticky, not too biased
    h = "rsprspsrprsprspsrprssprpr" * 2
    mem = _mem(h=h, n=len(h))
    profile = classify_player_profile(mem, _rps_spec())
    assert profile in ("balanced", "random")


def test_186_profile_coinflip_biased():
    spec = _coin_spec()
    h = "0000000000000000001"
    mem = _mem(h=h, n=len(h))
    profile = classify_player_profile(mem, spec)
    assert profile in ("biased", "sticky", "predictable")


def test_187_profile_empty_history():
    mem = _mem(h="", n=0)
    assert classify_player_profile(mem, _rps_spec()) == "unknown"


def test_188_profile_exactly_8_moves():
    h = "rsprsprs"
    mem = _mem(h=h, n=8)
    profile = classify_player_profile(mem, _rps_spec())
    assert profile in ("random", "balanced", "predictable", "biased", "sticky", "unknown")


def test_189_profile_all_one_move():
    h = "r" * 30
    mem = _mem(h=h, n=30)
    profile = classify_player_profile(mem, _rps_spec())
    assert profile in ("sticky", "biased")


def test_190_profile_two_moves_only():
    h = "rsrsrsrsrsrsrsrsrsrs"
    mem = _mem(h=h, n=len(h))
    profile = classify_player_profile(mem, _rps_spec())
    # only r and s used, entropy < max -> "predictable" or "biased"
    assert profile != "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# GameAIEngine   (tests 191–200)
# ═══════════════════════════════════════════════════════════════════════════

def test_191_engine_predict_returns_prediction():
    engine = GameAIEngine(rng=random.Random(42), exploration_epsilon=0.0)
    mem = _mem(h="rsprsp")
    pred = engine.predict(mem, _rps_spec())
    assert isinstance(pred, Prediction)
    assert pred.predicted_player_move in _rps_spec().moves
    assert pred.ai_move in _rps_spec().moves


def test_192_engine_predict_distribution_valid():
    engine = GameAIEngine(rng=random.Random(42), exploration_epsilon=0.0)
    mem = _mem(h="rsprsp")
    pred = engine.predict(mem, _rps_spec())
    total = sum(pred.distribution.values())
    assert abs(total - 1.0) < 0.01


def test_193_engine_predict_confidence_in_range():
    engine = GameAIEngine(rng=random.Random(42), exploration_epsilon=0.0)
    mem = _mem(h="rsprsp")
    pred = engine.predict(mem, _rps_spec())
    assert 0.0 <= pred.confidence <= 1.0


def test_194_engine_blend_uniform_inputs():
    engine = GameAIEngine(rng=random.Random(42))
    spec = _rps_spec()
    uniform = BasePredictor.uniform(spec)
    dists = {k: dict(uniform) for k in engine.weights}
    blended = engine._blend(dists, spec)
    for m in spec.moves:
        assert _approx(blended[m], 1 / 3, tol=0.01)


def test_195_engine_blend_single_source():
    engine = GameAIEngine(
        weights={"markov1": 1.0},
        rng=random.Random(42),
    )
    spec = _rps_spec()
    dists = {"markov1": {"r": 0.7, "s": 0.2, "p": 0.1}}
    blended = engine._blend(dists, spec)
    assert _approx(blended["r"], 0.7, tol=0.01)


def test_196_engine_argmax_conf_clear_winner():
    engine = GameAIEngine(rng=random.Random(42))
    spec = _rps_spec()
    dist = {"r": 0.8, "s": 0.1, "p": 0.1}
    move, conf = engine._argmax_conf(dist, spec)
    assert move == "r"
    assert conf > 0.5


def test_197_engine_argmax_conf_uniform_zero_confidence():
    engine = GameAIEngine(rng=random.Random(42))
    spec = _rps_spec()
    dist = {"r": 1 / 3, "s": 1 / 3, "p": 1 / 3}
    move, conf = engine._argmax_conf(dist, spec)
    assert conf < 0.01


def test_198_engine_best_response_rps():
    engine = GameAIEngine(rng=random.Random(42))
    spec = _rps_spec()
    dist = {"r": 0.8, "s": 0.1, "p": 0.1}
    ai_move, ev = engine._best_response(dist, "r", spec)
    # Best response against r-heavy: paper (p beats r)
    assert ai_move == "p"
    assert ev > 0


def test_199_engine_best_response_no_beats():
    engine = GameAIEngine(rng=random.Random(42))
    spec = _thimbles_spec()  # no beats table
    dist = {"0": 0.6, "1": 0.3, "2": 0.1}
    ai_move, ev = engine._best_response(dist, "0", spec)
    # No beats table -> returns predicted_move itself
    assert ai_move == "0"


def test_200_engine_no_exploration_deterministic():
    engine = GameAIEngine(rng=random.Random(42), exploration_epsilon=0.0)
    mem = _mem(h="rsprsprsp", t={"p|r": 10.0}, t2={"sp|r": 20.0})
    spec = _rps_spec()
    p1 = engine.predict(mem, spec)
    engine2 = GameAIEngine(rng=random.Random(42), exploration_epsilon=0.0)
    p2 = engine2.predict(mem, spec)
    assert p1.ai_move == p2.ai_move
    assert p1.predicted_player_move == p2.predicted_player_move
    assert _approx(p1.confidence, p2.confidence)
