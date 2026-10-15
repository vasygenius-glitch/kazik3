"""Казик V2: честные шансы (RTP ~97%) и правила игр — без БД."""
import itertools
import math
import random

import pytest

from v2.conf import RTP
from v2.games import cards as C
from v2.games import solo, tables
from v2.wallet import GameError


# ───────────────────────── RTP ─────────────────────────
def test_slots_rtp_exact():
    w = solo.SLOT_W
    total = sum(w.values())
    ev = sum(w[a] * w[b] * w[c] * solo.slot_pay([a, b, c])[0]
             for a, b, c in itertools.product(w, repeat=3)) / total ** 3
    assert 0.95 <= ev <= RTP


@pytest.mark.parametrize("line,expected", [
    (["shroom", "shroom", "shroom"], (solo.SLOT_3["shroom"], "three")),
    (["seven", "seven", "seven"], (solo.SLOT_3["seven"], "three")),
    (["shroom", "berry", "shroom"], (solo.SLOT_TWO_SHROOMS, "two_shrooms")),
    (["shroom", "shroom", "bell"], (solo.SLOT_TWO_SHROOMS, "two_shrooms")),
    (["gem", "gem", "berry"], (solo.SLOT_PAIR["gem"], "pair")),
    (["gem", "gem", "shroom"], (solo.SLOT_PAIR["gem"], "pair")),
    (["berry", "shroom", "acorn"], (solo.SLOT_ONE_SHROOM, "one_shroom")),
    (["berry", "acorn", "bell"], (0, "none")),
])
def test_slot_pay(line, expected):
    assert solo.slot_pay(line) == expected


@pytest.mark.parametrize("pick", list(solo.DICE_PICKS))
def test_dice_probabilities_and_rtp(pick):
    hits = {"lo": lambda a, b: a + b < 7, "seven": lambda a, b: a + b == 7, "hi": lambda a, b: a + b > 7,
            "double": lambda a, b: a == b}[pick]
    p = sum(hits(a, b) for a in range(1, 7) for b in range(1, 7)) / 36
    assert p == pytest.approx(solo.DICE_PICKS[pick][0])
    assert RTP - 0.01 <= p * solo.dice_mult(pick) <= RTP


@pytest.mark.parametrize("n", list(solo.CUPS_MULT))
def test_cups_rtp(n):
    assert RTP - 0.015 <= solo.CUPS_MULT[n] / n <= RTP


@pytest.mark.parametrize("mines", [1, 3, 5, 10, 20, 24])
def test_mines_multipliers_fair_and_growing(mines):
    prev = 0.0
    for k in range(1, solo.CELLS - mines + 1):
        p = math.prod((solo.CELLS - mines - i) / (solo.CELLS - i) for i in range(k))
        x = solo.mines_mult(mines, k)
        assert x > prev
        assert RTP - 0.01 <= p * x <= RTP + 1e-9
        prev = x


def test_crash_point_formula(monkeypatch):
    class Fixed:
        def __init__(self, v):
            self.v = v

        def random(self):
            return self.v

    monkeypatch.setattr(tables, "rng", Fixed(0.5))        # u = 0.5
    assert tables.crash_point() == math.floor(RTP / 0.5 * 100) / 100
    monkeypatch.setattr(tables, "rng", Fixed(0.0))        # u = 1 → сразу x1.00
    assert tables.crash_point() == 1.0
    monkeypatch.setattr(tables, "rng", Fixed(1 - 1e-9))   # огромный множитель упирается в потолок
    assert tables.crash_point() == tables.CRASH_MAX


def test_crash_rtp_any_target(monkeypatch):
    monkeypatch.setattr(tables, "rng", random.Random(2024))
    pts = [tables.crash_point() for _ in range(200_000)]
    assert min(pts) == 1.0 and max(pts) <= tables.CRASH_MAX
    for target in (1.5, 2.0, 5.0, 10.0):
        share = sum(p >= target for p in pts) / len(pts)
        assert share * target == pytest.approx(RTP, abs=0.02), target
    instant = sum(p < 1.01 for p in pts) / len(pts)
    assert 0.03 < instant < 0.05


def test_crash_mult_curve():
    assert tables.crash_mult(0) == 1.0 and tables.crash_mult(-3) == 1.0
    assert tables.crash_mult(10) == 2.01
    xs = [tables.crash_mult(t / 10) for t in range(0, 600)]
    assert xs == sorted(xs)


def test_roulette_payouts():
    m = tables.roulette_mult
    assert m("n", 17, 17) == 36 and m("n", 17, 18) == 0 and m("n", 0, 0) == 36
    for kind in ("red", "black", "odd", "even", "low", "high"):
        assert m(kind, None, 0) == 0
    assert m("red", None, 1) == 2 and m("black", None, 1) == 0 and m("black", None, 2) == 2
    assert m("odd", None, 3) == 2 and m("even", None, 3) == 0
    assert m("low", None, 18) == 2 and m("high", None, 19) == 2
    assert m("dozen", 2, 13) == 3 and m("dozen", 2, 12) == 0
    assert m("col", 1, 34) == 3 and m("col", 3, 36) == 3 and m("col", 2, 36) == 0


def test_roulette_every_bet_has_same_rtp():
    bets = ([("n", v) for v in range(37)] + [(k, None) for k in ("red", "black", "odd", "even", "low", "high")]
            + [("dozen", d) for d in (1, 2, 3)] + [("col", c) for c in (1, 2, 3)])
    for kind, value in bets:
        ev = sum(tables.roulette_mult(kind, value, n) for n in range(37)) / 37
        assert ev == pytest.approx(36 / 37), (kind, value)


def test_roulette_wheel_layout():
    assert sorted(tables.WHEEL_ORDER) == list(range(37))
    assert len(tables.RED) == 18 and 0 not in tables.RED


@pytest.mark.parametrize("kind,value", [("n", 37), ("n", -1), ("n", "5"), ("n", None), ("dozen", 4), ("col", 0),
                                        ("color", None), ("", None)])
def test_roulette_bad_bets(kind, value):
    with pytest.raises(GameError):
        tables.validate_roulette_bet(kind, value)


def test_roulette_good_bets():
    for kind, value in (("n", 0), ("n", 36), ("red", None), ("dozen", 3), ("col", 1)):
        tables.validate_roulette_bet(kind, value)


def _bac_exact():
    """Точные вероятности исходов баккары (бесконечная колода, классические правила)."""
    pv = [4 / 13] + [1 / 13] * 9
    res = {"player": 0.0, "banker": 0.0, "tie": 0.0}

    def put(p, ps, bs):
        res["tie" if ps == bs else ("player" if ps > bs else "banker")] += p

    for p1, p2, b1, b2 in itertools.product(range(10), repeat=4):
        pr = pv[p1] * pv[p2] * pv[b1] * pv[b2]
        ps, bs = (p1 + p2) % 10, (b1 + b2) % 10
        if ps >= 8 or bs >= 8:
            put(pr, ps, bs)
        elif ps <= 5:
            for v in range(10):
                draw = (bs <= 2 or (bs == 3 and v != 8) or (bs == 4 and 2 <= v <= 7) or (bs == 5 and 4 <= v <= 7)
                        or (bs == 6 and v in (6, 7)))
                if draw:
                    for b3 in range(10):
                        put(pr * pv[v] * pv[b3], (ps + v) % 10, (bs + b3) % 10)
                else:
                    put(pr * pv[v], (ps + v) % 10, bs)
        elif bs <= 5:
            for b3 in range(10):
                put(pr * pv[b3], ps, (bs + b3) % 10)
        else:
            put(pr, ps, bs)
    return res


def test_baccarat_rtp():
    p = _bac_exact()
    assert sum(p.values()) == pytest.approx(1.0)
    assert 0.96 <= p["player"] * solo.BAC_MULT["player"] + p["tie"] <= 0.995
    assert 0.96 <= p["banker"] * solo.BAC_MULT["banker"] + p["tie"] <= 0.995
    assert 0.96 <= p["tie"] * solo.BAC_MULT["tie"] <= 0.98


def test_rps_uniform_rtp_and_predictor():
    assert (solo.RPS_WIN + 1) / 3 == pytest.approx(0.98)
    assert solo.rps_predict(["rock"] * 3) == (None, 0.0)
    assert solo.rps_predict(["rock"] * 10) == ("rock", 1.0)
    guess, conf = solo.rps_predict(["rock", "paper"] * 6)
    assert guess == "rock" and conf == 1.0
    assert solo.rps_predict(["lizard"] * 10) == (None, 0.0)


# ───────────────────────── карты ─────────────────────────
def test_bj_score_and_blackjack():
    assert C.bj_score(["As", "Kd"]) == (21, True)
    assert C.bj_score(["As", "Ad"]) == (12, True)
    assert C.bj_score(["As", "9d", "Kc"]) == (20, False)
    assert C.bj_score(["As", "Ad", "9c"]) == (21, True)
    assert C.bj_score(["Ts", "9d", "5c"]) == (24, False)
    assert C.is_blackjack(["Ah", "Qs"]) and not C.is_blackjack(["7h", "7s", "7c"])


def test_baccarat_values():
    assert C.bac_score(["9h", "8d"]) == 7
    assert C.bac_score(["Kh", "Qd"]) == 0
    assert C.bac_score(["Ah", "5d", "Tc"]) == 6


def test_deck_is_full():
    d = C.deck()
    assert len(d) == 52 and len(set(d)) == 52


@pytest.mark.parametrize("hand,rank", [
    (["Ts", "Js", "Qs", "Ks", "As"], "royal"),
    (["9h", "Th", "Jh", "Qh", "Kh"], "sflush"),
    (["Ad", "2d", "3d", "4d", "5d"], "sflush"),
    (["9s", "9h", "9d", "9c", "2s"], "four"),
    (["3s", "3h", "3d", "Kc", "Ks"], "full"),
    (["2c", "7c", "9c", "Jc", "Kc"], "flush"),
    (["5s", "6h", "7d", "8c", "9s"], "straight"),
    (["As", "2h", "3d", "4c", "5s"], "straight"),
    (["7s", "7h", "7d", "2c", "Ks"], "three"),
    (["4s", "4h", "9d", "9c", "Ks"], "twopair"),
    (["Js", "Jh", "2d", "5c", "9s"], "jacks"),
    (["As", "Ah", "2d", "5c", "9s"], "jacks"),
    (["Ts", "Th", "2d", "5c", "9s"], None),
    (["Qs", "Kh", "Ad", "2c", "3s"], None),
    (["2s", "5h", "9d", "Jc", "Ks"], None),
])
def test_poker_rank(hand, rank):
    assert C.poker_rank(hand) == rank


def _feed(monkeypatch, seq):
    it = iter(seq)
    monkeypatch.setattr(C, "draw", lambda: next(it))


@pytest.mark.parametrize("seq,plen,blen", [
    (["9s", "Kd", "2h", "3c"], 2, 2),            # натуральные 9 — без добора
    (["2s", "3d", "Kh", "6c", "8h"], 3, 2),      # игрок 5 берёт, банкир 6 стоит при третьей 8
    (["Ks", "6d", "2h", "2c", "9d"], 2, 3),      # игрок стоит на 6, банкир 4 берёт
    (["As", "2d", "Ts", "3h", "8c"], 3, 2),      # банкир 3 не берёт против третьей 8
    (["As", "2d", "Ts", "3h", "7c", "4d"], 3, 3),  # банкир 3 берёт против третьей 7
])
def test_baccarat_third_card_rules(monkeypatch, seq, plen, blen):
    _feed(monkeypatch, seq)
    p, b, ps, bs = solo.baccarat_deal()
    assert (len(p), len(b)) == (plen, blen)
    assert ps == C.bac_score(p) and bs == C.bac_score(b)


def _bj(player, dealer, hands=None, bet=100):
    hs = hands or [player]
    return {"hands": [{"c": list(c), "b": bet, "done": True} for c in hs], "d": list(dealer), "cur": len(hs)}


def test_bj_win_push_bust(monkeypatch):
    _feed(monkeypatch, [])
    assert solo._bj_finish(_bj(["Ts", "Qh"], ["9c", "Ts"]))["payout"] == 200
    assert solo._bj_finish(_bj(["Ts", "8h"], ["9c", "9s"]))["payout"] == 100
    res = solo._bj_finish(_bj(["Ts", "6h", "Kd"], ["6c", "Ts"]))   # перебор: дилер не добирает
    assert res["payout"] == 0 and res["view"]["hands"][0]["res"] == "bust"


def test_bj_dealer_draws_to_17_and_stands_soft_17(monkeypatch):
    _feed(monkeypatch, ["5d"])
    res = solo._bj_finish(_bj(["Ts", "Qh"], ["6c", "Ts"]))
    assert res["view"]["dealer"] == ["6c", "Ts", "5d"] and res["payout"] == 0
    _feed(monkeypatch, [])
    res = solo._bj_finish(_bj(["Ts", "8h"], ["As", "6d"]))
    assert res["payout"] == 200 and len(res["view"]["dealer"]) == 2


def test_bj_natural_pays_3_to_2_but_not_after_split(monkeypatch):
    _feed(monkeypatch, [])
    res = solo._bj_finish(_bj(["As", "Kd"], ["9c", "7s"]), natural=True)
    assert res["payout"] == 250 and res["view"]["hands"][0]["res"] == "bj"
    res = solo._bj_finish(_bj(None, ["Ts", "Qs"], hands=[["As", "Kd"], ["As", "8d"]]))
    assert [h["res"] for h in res["view"]["hands"]] == ["win", "lose"] and res["payout"] == 200
    res = solo._bj_finish(_bj(["7s", "7h", "7d"], ["As", "Kd"]))
    assert res["payout"] == 0
