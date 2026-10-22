"""Builder C: match chain, predict, live paths, tournament and season simulators, markets, backtest."""
from __future__ import annotations

import json
import math
import time
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from oddsmarkets.tennis.models import backtest as BT
from oddsmarkets.tennis.models import live as LV
from oddsmarkets.tennis.models import match_chain as mc
from oddsmarkets.tennis.models import predict as PR
from oddsmarkets.tennis.models import season_sim as SS
from oddsmarkets.tennis.models import tournament_sim as TS
from oddsmarkets.tennis.sources import markets as MK

FIX = Path(__file__).parent / "fixtures"


# ── independent references ──────────────────────────────────────────────────

def ref_game(p):
    q = 1 - p
    return p ** 4 * (1 + 4 * q + 10 * q ** 2) + 20 * p ** 3 * q ** 3 * p ** 2 / (p ** 2 + q ** 2)


def ref_tiebreak(pa, pb, a_first=True, to=7, cap=400):
    """Brute-force tiebreak: walk the point lattice far beyond `to` (no closed-form tail)."""
    from functools import lru_cache

    @lru_cache(None)
    def v(i, j):
        if i >= to and i - j >= 2:
            return 1.0
        if j >= to and j - i >= 2:
            return 0.0
        if i + j > cap:
            return 0.5
        k = i + j
        a_srv = (((k + 1) // 2) % 2 == 0) == a_first
        q = pa if a_srv else 1 - pb
        return q * v(i + 1, j) + (1 - q) * v(i, j + 1)
    return v(0, 0)


def ref_set(pa, pb, a_first=True, to_tb=7):
    """Brute-force set-score distribution (tiebreak at 6-6), from the game-level recursion."""
    ha, hb = ref_game(pa), ref_game(pb)
    out = {}

    def go(g1, g2, pr):
        if (max(g1, g2) >= 6 and abs(g1 - g2) >= 2) or max(g1, g2) == 7:
            out[(g1, g2)] = out.get((g1, g2), 0) + pr
            return
        a_srv = ((g1 + g2) % 2 == 0) == a_first
        if g1 == g2 == 6:
            w = ref_tiebreak(pa, pb, a_srv, to_tb)
            go(7, 6, pr * w)
            go(6, 7, pr * (1 - w))
            return
        w = ha if a_srv else 1 - hb
        go(g1 + 1, g2, pr * w)
        go(g1, g2 + 1, pr * (1 - w))
    go(0, 0, 1.0)
    return out


# ── match chain ─────────────────────────────────────────────────────────────

def test_game_closed_form():
    assert abs(float(mc.game_win(0.6)) - 0.7357) < 1e-4
    for p in (0.3, 0.5, 0.62, 0.75, 0.9):
        assert abs(float(mc.game_win(p)) - ref_game(p)) < 1e-12
        assert abs(float(mc.game_from(p, 0, 0)) - ref_game(p)) < 1e-12
        assert abs(float(mc.game_from(p, 3, 3)) - p * p / (p * p + (1 - p) ** 2)) < 1e-12
    assert float(mc.game_from(0.6, 3, 0)) > float(mc.game_from(0.6, 2, 0)) > float(mc.game_from(0.6, 0, 0))
    assert float(mc.game_from(0.6, 4, 2)) == 1.0 and float(mc.game_from(0.6, 1, 4)) == 0.0


def test_tiebreak_matches_bruteforce():
    for pa, pb in ((0.6, 0.6), (0.65, 0.58), (0.7, 0.66)):
        for fs in (0, 1):
            for to in (7, 10):
                assert abs(float(mc.tiebreak_win(pa, pb, to, fs)) - ref_tiebreak(pa, pb, fs == 0, to)) < 1e-9
    assert abs(float(mc.tiebreak_win(0.6, 0.6)) - 0.5) < 1e-12


def test_set_distribution_matches_bruteforce_table():
    for pa, pb in ((0.62, 0.58), (0.7, 0.55)):
        for fs in (0, 1):
            d = {k: float(v[0]) for k, v in mc.set_dist(pa, pb, fs, "tb7").items()}
            r = ref_set(pa, pb, fs == 0)
            assert set(d) == set(r)
            for k in r:
                assert abs(d[k] - r[k]) < 1e-10, k
            assert abs(sum(d.values()) - 1) < 1e-12
    # equal servers: a set is a coin flip
    assert abs(float(mc.set_win(0.63, 0.63, 0)[0]) - 0.5) < 1e-12


def test_match_against_independent_simulator():
    """Builder B's point-by-point simulator (synthetic.simulate_match) agrees with the exact chain."""
    syn = pytest.importorskip("oddsmarkets.tennis.models.synthetic")
    rng = np.random.default_rng(7)
    pa, pb, n = 0.64, 0.6, 20000
    exact = mc.match(pa, pb, 3, "tb7")
    wins, straight, games = 0, 0, []
    for _ in range(n):
        r = syn.simulate_match(pa, pb, 3, "tb7", rng)
        wins += r["a_won"]
        straight += len(r["sets"]) == 2
        games.append(sum(s[0] + s[1] for s in r["sets"]))
    se = math.sqrt(0.25 / n)
    assert abs(wins / n - exact["p1_win"]) < 4 * se
    assert abs(straight / n - exact["p_straight"]) < 4 * se
    assert abs(np.mean(games) - exact["exp_games"]) < 0.15


@pytest.mark.parametrize("bo,rule", [(3, "tb7"), (5, "tb7"), (5, "tb10"), (5, "adv"), (5, "tb12"), (3, "tb10")])
def test_distributions_sum_to_one(bo, rule):
    m = mc.match(0.66, 0.61, bo, rule)
    assert abs(m["p1_win"] + m["p2_win"] - 1) < 1e-12
    assert abs(sum(m["sets"].values()) - 1) < 1e-10
    assert abs(sum(m["games"].values()) - 1) < 1e-8
    assert abs(sum(m["handicap"].values()) - 1) < 1e-8
    assert abs(sum(v for k, v in m["sets"].items() if int(k.split("-")[0]) == bo // 2 + 1) - m["p1_win"]) < 1e-12
    assert 0 < m["p_tiebreak"] < 1 and 0 < m["p_straight"] < 1
    # the fast path agrees
    assert abs(float(mc.match_win_prob(0.66, 0.61, bo, rule)[0]) - m["p1_win"]) < 1e-12


def test_symmetry():
    a = mc.match(0.67, 0.6, 5, "tb10")
    b = mc.match(0.6, 0.67, 5, "tb10")
    assert abs(a["p1_win"] + b["p1_win"] - 1) < 1e-12
    for k, v in a["sets"].items():
        x, y = k.split("-")
        assert abs(v - b["sets"][f"{y}-{x}"]) < 1e-12
    for k, v in a["handicap"].items():
        assert abs(v - b["handicap"].get(-k, 0.0)) < 1e-9
    assert a["games"] == pytest.approx(b["games"], abs=1e-12)


def test_best_of_five_amplifies_favourites():
    for pa, pb in ((0.65, 0.62), (0.7, 0.6), (0.58, 0.55)):
        assert mc.match(pa, pb, 5)["p1_win"] > mc.match(pa, pb, 3)["p1_win"] > 0.5
        assert mc.match(pb, pa, 5)["p1_win"] < mc.match(pb, pa, 3)["p1_win"] < 0.5


def test_final_set_rules():
    # in the deciding set at 6-6 the tb10 rule is exactly a 10-point tiebreak
    st = {"sets": [2, 2], "games": [6, 6], "server": 0}
    p10 = mc.match(0.66, 0.63, 5, "tb10", state=st)["p1_win"]
    assert abs(p10 - float(mc.tiebreak_win(0.66, 0.63, 10, 0))) < 1e-12
    p7 = mc.match(0.66, 0.63, 5, "tb7", state=st)["p1_win"]
    assert abs(p7 - float(mc.tiebreak_win(0.66, 0.63, 7, 0))) < 1e-12
    assert p10 > p7 > 0.5                             # longer tiebreaks favour the better server
    # with tb10 a 7-6 decider still counts 13 games; an advantage decider has no tiebreak there
    adv = mc.match(0.66, 0.63, 5, "adv")
    tb = mc.match(0.66, 0.63, 5, "tb7")
    assert adv["p_tiebreak"] < tb["p_tiebreak"]
    assert max(adv["games"]) > max(tb["games"])
    # Wimbledon 2019-21: no tiebreak before 12-12 in the decider
    st12 = {"sets": [2, 2], "games": [6, 6], "server": 0}
    assert mc.match(0.66, 0.63, 5, "tb12", state=st12)["p1_win"] != pytest.approx(p7)
    d = mc.set_dist(0.7, 0.7, 0, "tb12")
    assert (7, 6) not in d and (13, 12) in d


def test_live_state_monotonic_and_table_agrees():
    pa, pb = 0.64, 0.62
    lt = mc.LiveTable(pa, pb, 3, "tb7")
    p0 = float(lt.p_pre()[0])
    assert abs(p0 - mc.match(pa, pb)["p1_win"]) < 1e-12
    assert float(lt.p((1, 0))[0]) > p0 > float(lt.p((0, 1))[0])
    # within a game: more points on serve -> higher
    seq = [float(lt.p((0, 0), (2, 2), 0, (a, 0))[0]) for a in range(4)]
    assert all(x < y for x, y in zip(seq, seq[1:]))
    # a break up beats on serve
    assert float(lt.p((1, 1), (3, 1), 0)[0]) > float(lt.p((1, 1), (2, 2), 0)[0])
    for st in ({"sets": [1, 1], "games": [4, 3], "points": ["30", "40"], "server": 1},
               {"sets": [0, 1], "games": [6, 6], "points": [3, 5], "server": 0},
               {"sets": [1, 0], "games": [5, 5], "server": None}):
        a = mc.match(pa, pb, 3, "tb7", state=st)["p1_win"]
        b = float(lt.p(st["sets"], st["games"], st["server"], st.get("points"))[0])
        assert abs(a - b) < 1e-12
    # finished states
    assert float(lt.p((2, 0))[0]) == 1.0 and float(lt.p((1, 2))[0]) == 0.0


def test_chain_speed_5000_matches():
    rng = np.random.default_rng(0)
    a, b = rng.uniform(0.5, 0.75, 5000), rng.uniform(0.5, 0.75, 5000)
    t0 = time.perf_counter()
    r = mc.match(a, b, 5, "tb10")
    assert time.perf_counter() - t0 < 6.0
    assert np.allclose(r["games"].sum(1), 1.0)
    t0 = time.perf_counter()
    mc.match_win_prob(a, b, 3, "tb7")
    assert time.perf_counter() - t0 < 1.0


def test_solve_shift_hits_target():
    tgt = np.array([0.3, 0.5, 0.8, 0.95])
    pa = np.array([0.64, 0.6, 0.62, 0.66])
    pb = np.array([0.61, 0.63, 0.62, 0.6])
    d = mc.solve_shift(tgt, pa, pb, 3, "tb7")
    assert np.allclose(mc.match_win_prob(pa + d, pb - d, 3, "tb7"), tgt, atol=1e-6)


# ── predict ─────────────────────────────────────────────────────────────────

def test_predict_blend_and_consistent_distribution():
    ctx = PR.Context("atp", "2026-10-01", elo_fn=lambda a, b, s, bo: 0.72, p_srv_fn=lambda a, b, s, l, bo: (0.66, 0.62),
                     blend={"w_elo": 0.6, "w_sr": 0.5})
    r = PR.predict("atp", "a", "b", "hard", 3, "2026-10-01", "500", ctx=ctx)
    sr = mc.match(0.66, 0.62)["p1_win"]
    want = float(PR.blend(0.72, sr, 0.6, 0.5))
    assert abs(r["p1_win"] - want) < 1e-6
    assert abs(r["dist"]["p1_win"] - want) < 1e-6
    assert abs(sum(r["p_srv"]) - (0.66 + 0.62)) < 1e-9          # the edge moves, the serve level stays
    assert r["elo_p"] == 0.72 and abs(r["sr_p"] - sr) < 1e-12 and r["blend_w"] == pytest.approx(0.6 / 1.1, abs=1e-4)
    # matrix is a proper pairwise table
    M = PR.prob_matrix(ctx, ["a", "b", "c"], "hard", 3, "250")
    assert np.allclose(M + M.T, 1.0)


def test_fit_blend_recovers_weights():
    rng = np.random.default_rng(1)
    e = rng.uniform(0.1, 0.9, 20000)
    s = np.clip(e + rng.normal(0, 0.15, 20000), 0.02, 0.98)
    p = PR.blend(e, s, 0.7, 0.4)
    y = (rng.random(20000) < p).astype(int)
    f = PR.fit_blend(e, s, y)
    assert abs(f["w_elo"] - 0.7) < 0.12 and abs(f["w_sr"] - 0.4) < 0.12


def test_default_final_rules():
    assert PR.default_final_rule("slam", 5, 2024, "wimbledon") == "tb10"
    assert PR.default_final_rule("slam", 5, 2020, "wimbledon") == "tb12"
    assert PR.default_final_rule("slam", 5, 2017, "roland-garros") == "adv"
    assert PR.default_final_rule("250", 3, 2017, "doha") == "tb7"


# ── live ────────────────────────────────────────────────────────────────────

def test_live_path_finished_match():
    m = {"p1": "a", "p2": "b", "winner": "a", "status": "done", "best_of": 3, "final_set_rule": "tb7",
         "sets": [[3, 6, None, None], [7, 6, 7, 4], [6, 4, None, None]]}
    r = LV.path(m, (0.64, 0.63))
    st = r["steps"]
    assert st[0]["kind"] == "start" and st[-1]["p1"] == 1.0
    # replayed games reach the set scores
    by_set: dict = {}
    for s in st[1:]:
        if s["kind"] in ("hold", "break", "tiebreak"):
            by_set[s["set"]] = s["games"]
    assert by_set == {1: [3, 6], 2: [7, 6], 3: [6, 4]}
    ps = np.array([s["p1"] for s in st])
    assert abs(r["excitement"] - np.abs(np.diff(ps)).sum()) < 1e-4
    assert r["excitement"] >= abs(1 - r["p_pre"]) - 1e-9
    assert r["comeback"]["min_p"] == pytest.approx(ps.min(), abs=1e-5) and r["comeback"]["min_p"] < 0.5
    assert all(s["leverage"] is None or s["leverage"] >= 0 for s in st)
    assert r["reconstructed"] is True and len(r["swings"]) <= LV.MAX_SWINGS


def test_live_path_observed_sequence_and_live_points():
    m = {"p1": "a", "p2": "b", "status": "live", "best_of": 3, "sets": [[6, 0]],
         "live": {"set": 2, "games": [1, 0], "points": ["15", "40"], "server": "b"}}
    seq = [[0, 0, 0, 0, 0, 0], [0]]
    r = LV.path(m, (0.62, 0.62), sequence=seq, first_server=0)
    assert r["reconstructed"] is False
    assert [s["kind"] for s in r["steps"][1:7]] == ["hold", "break", "hold", "break", "hold", "break"]
    last = r["steps"][-1]
    assert last["kind"] == "points" and last["server"] == 1
    lt = mc.LiveTable(0.62, 0.62, 3)
    assert last["p1"] == pytest.approx(float(lt.p((1, 0), (1, 0), 1, ("15", "40"))[0]), abs=1e-5)


def test_set_sequence_respects_score_and_serve():
    s = LV.set_sequence(6, 4, 0, 0.8, 0.8)
    g = s["games"]
    assert len(g) == 10 and g.count(0) == 6 and g[-1] == 0
    breaks = [i for i, w in enumerate(g) if w != (0 if i % 2 == 0 else 1)]
    assert len(breaks) == 1                         # holds as served, one break
    s = LV.set_sequence(7, 6, 1, 0.8, 0.8)
    assert len(s["games"]) == 12 and s["tiebreak"] == 0
    s = LV.set_sequence(10, 8, 0, 0.85, 0.85, "adv")
    assert len(s["games"]) == 18 and s["games"].count(0) == 10


# ── tournament simulator ────────────────────────────────────────────────────

def _prob_from(P, names):
    def prob(pids):
        ix = [names.index(p) for p in pids]
        return P[np.ix_(ix, ix)]
    return prob


def _exact_bracket(P, leaves):
    """{player: P(title)} for a bracket of player indices (no byes), by recursion."""
    def win(lo, hi):
        if hi - lo == 1:
            return {leaves[lo]: 1.0}
        mid = (lo + hi) // 2
        L, R = win(lo, mid), win(mid, hi)
        out = {}
        for i, pi in L.items():
            out[i] = pi * sum(pj * P[i, j] for j, pj in R.items())
        for j, pj in R.items():
            out[j] = pj * sum(pi * P[j, i] for i, pi in L.items())
        return out
    return win(0, len(leaves))


def test_tournament_reproduces_planted_odds_4_and_8():
    P4 = np.array([[.5, .7, .6, .8], [.3, .5, .55, .65], [.4, .45, .5, .6], [.2, .35, .4, .5]])
    n4 = ["a", "b", "c", "d"]
    ev = {"id": "e-2026", "level": "250", "draw": {"size": 4, "slots": [[i + 1, p, None, None] for i, p in enumerate(n4)]}}
    r = TS.simulate(ev, n=200000, prob=_prob_from(P4, n4), seed=1)
    ex = _exact_bracket(P4, [0, 1, 2, 3])
    for i, p in enumerate(n4):
        assert abs(r["players"][p]["p_title"] - ex[i]) < 0.005
    # interventional next-match odds: a's title odds if a beats b = E over the other semi
    if_win = P4[2, 3] * P4[0, 2] + P4[3, 2] * P4[0, 3]
    assert abs(r["players"]["a"]["next"]["if_win"]["p_title"] - if_win) < 0.006
    rng = np.random.default_rng(3)
    s = rng.normal(0, 1, 8)
    P8 = 1 / (1 + np.exp(-(s[:, None] - s[None, :])))
    n8 = [f"p{i}" for i in range(8)]
    ev8 = {"id": "e8", "level": "500", "draw": {"size": 8, "slots": [[i + 1, p, None, None] for i, p in enumerate(n8)]}}
    r8 = TS.simulate(ev8, n=200000, prob=_prob_from(P8, n8), seed=2)
    ex8 = _exact_bracket(P8, list(range(8)))
    for i, p in enumerate(n8):
        assert abs(r8["players"][p]["p_title"] - ex8[i]) < 0.006
    assert abs(sum(v["p_title"] for v in r8["players"].values()) - 1) < 1e-4          # values rounded to 5 dp
    assert abs(sum(v["p_sf"] for v in r8["players"].values()) - 4) < 1e-4


def test_tournament_byes_fixed_results_and_points():
    n = ["a", "b", "c", "d", "e", "f"]
    P = np.full((6, 6), 0.5)
    ev = {"id": "e8", "level": "500", "draw": {"size": 8, "slots": [[1, "a", 1, None], [2, None, None, None], [3, "b", None, None],
                                                                      [4, "c", None, None], [5, "d", None, None], [6, "e", None, None],
                                                                      [7, None, None, None], [8, "f", 2, None]]}}
    ms = [{"event": "e8", "round": "QF", "p1": "c", "p2": "b", "winner": "c", "status": "done"}]
    r = TS.simulate(ev, n=40000, prob=_prob_from(P, n), matches=ms, seed=4)
    pl = r["players"]
    assert pl["b"]["eliminated"] and pl["b"]["p_sf"] == 0.0 and pl["c"]["p_sf"] == 1.0 and pl["a"]["p_sf"] == 1.0
    assert pl["a"]["p_final"] == pytest.approx(0.5, abs=0.01)
    # a (bye) losing his first match gets first-round (QF) points: 100; b lost in the QF: 100
    tab = r["points_table"]
    exp_a = 0.5 * tab["QF"] + 0.25 * tab["F"] + 0.25 * tab["W"]
    assert pl["a"]["exp_points"] == pytest.approx(exp_a, rel=0.03)
    assert pl["b"]["exp_points"] == pytest.approx(tab["QF"])
    assert pl["a"]["next"]["round"] == "SF" and list(pl["a"]["next"]["opponents"]) == ["c"]


def test_bracket_from_results_rebuilds_tree():
    ms = [{"round": "QF", "p1": "a", "p2": "b", "winner": "a"}, {"round": "QF", "p1": "c", "p2": "d", "winner": "c"},
          {"round": "QF", "p1": "e", "p2": "f", "winner": "e"}, {"round": "SF", "p1": "a", "p2": "c", "winner": "a"},
          {"round": "SF", "p1": "e", "p2": "g", "winner": "e"}, {"round": "F", "p1": "a", "p2": "e", "winner": "a"}]
    d = TS.bracket_from_results(ms)
    leaves = [s[1] for s in d["slots"]]
    assert d["size"] == 8 and set(leaves) - {None} == set("abcdefg")
    # g had a bye into the semi-final
    gi = leaves.index("g")
    assert leaves[gi ^ 1] is None
    r = TS.simulate({"id": "x", "draw": d, "level": "250"}, n=2000, matches=[dict(m, status="done") for m in ms],
                    prob=lambda pids: np.full((len(pids), len(pids)), 0.5))
    assert r["players"]["a"]["p_title"] == 1.0


def test_round_robin_tiebreak_rules():
    h = np.zeros((4, 4), int)
    # two tied on wins: head to head
    h[1, 0] = 1
    o = TS.rr_order([2, 2, 1, 1], [4, 4, 2, 2], [2, 2, 3, 3], [30, 30, 20, 20], [20, 20, 25, 25], h, [1, 2, 3, 4])
    assert o[:2] == [1, 0]
    # three tied: sets %, then head to head between the two left
    h = np.zeros((4, 4), int)
    h[2, 1] = 1
    o = TS.rr_order([2, 2, 2, 0], [5, 4, 4, 0], [2, 3, 3, 6], [40, 30, 31, 10], [20, 30, 30, 40], h, [1, 2, 3, 4])
    assert o == [0, 2, 1, 3]
    # three tied on sets %: games % decides
    o = TS.rr_order([2, 2, 2, 0], [4, 4, 4, 0], [3, 3, 3, 6], [40, 41, 39, 10], [30, 30, 30, 40], np.zeros((4, 4)), [1, 2, 3, 4])
    assert o == [1, 0, 2, 3]
    # everything tied: seed order
    o = TS.rr_order([2, 2, 2, 0], [4, 4, 4, 0], [3, 3, 3, 6], [40, 40, 40, 10], [30, 30, 30, 40], np.zeros((4, 4)), [3, 1, 2, 4])
    assert o == [1, 2, 0, 3]


def test_round_robin_simulation():
    names = [f"p{i}" for i in range(8)]
    s = np.linspace(1, -1, 8)
    P = 1 / (1 + np.exp(-(s[:, None] - s[None, :])))
    ev = {"id": "finals-2026", "level": "finals", "groups": {"A": ["p0", "p3", "p4", "p7"], "B": ["p1", "p2", "p5", "p6"]}}
    ms = [{"event": "finals-2026", "round": "RR", "p1": "p7", "p2": "p0", "winner": "p7", "status": "done", "sets": [[7, 6], [6, 4]]}]
    r = TS.simulate(ev, n=8000, prob=_prob_from(P, names), matches=ms, seed=5)
    pl = r["players"]
    assert r["format"] == "round_robin"
    assert abs(sum(v["p_title"] for v in pl.values()) - 1) < 1e-4
    assert abs(sum(v["p_sf"] for v in pl.values()) - 4) < 1e-4
    assert pl["p7"]["exp_rr_wins"] >= 1.0 and pl["p0"]["exp_rr_wins"] <= 2.0
    assert pl["p1"]["p_sf"] > pl["p6"]["p_sf"]
    assert pl["p0"]["exp_points"] == pytest.approx(200 * pl["p0"]["exp_rr_wins"] + 400 * pl["p0"]["p_final"] + 500 * pl["p0"]["p_title"], abs=0.1)
    nx = pl["p1"]["next"]
    assert nx["if_win"]["p_sf"] > nx["if_loss"]["p_sf"]


# ── season simulator ────────────────────────────────────────────────────────

def test_season_hand_worked_points():
    pids = ["p0", "p1", "p2", "p3"]
    s = np.array([300.0, 200.0, 100.0, 0.0])                    # effectively deterministic

    def logit(surface, bo):
        return SS._field_logit(s[:, None] - s[None, :], 0, 4)
    st = {"tour": "wta", "players": pids, "rank_pts": {"p0": 1000, "p1": 1200, "p2": 800, "p3": 100},
          "race_pts": {"p0": 900, "p1": 700, "p2": 650, "p3": 10}, "drops": {"p0": 100, "p1": 500},
          "earned_since_snapshot": {"p2": 30}, "use_snapshot": True,
          "events": [{"id": "x-2026", "level": "250", "draw_size": 4, "accept": 1.0, "surface": "hard", "best_of": 3,
                      "start": "2026-10-20", "entry": {p: 1.0 for p in pids}, "points": {"W": 250, "F": 163, "SF": 98}}],
          "logit": logit, "slam_winners": [], "finals": None, "as_of": "2026-10-01"}
    r = SS.simulate_season(st, n=300)
    # p0 (seed 1) beats p3 then p1 (seed 2). Year-end = race + new: p0 900 + 250, p1 700 + 163, p2 650 + 98, p3 10 + 98
    pts = r["points"]
    assert (pts["p0"]["mean"], pts["p1"]["mean"], pts["p2"]["mean"], pts["p3"]["mean"]) == (1150, 863, 748, 108)
    # the snapshot check: official - drops + since + new: 1000 - 100 + 250, 1200 - 500 + 163, 800 + 30 + 98, 100 + 98
    assert (pts["p0"]["via_snapshot_mean"], pts["p1"]["via_snapshot_mean"], pts["p2"]["via_snapshot_mean"],
            pts["p3"]["via_snapshot_mean"]) == (1150, 863, 928, 198)
    assert pts["p0"]["added_mean"] == 250 and pts["p1"]["drops"] == 500
    assert r["year_end_no1"] == {"p0": 1.0}
    assert r["race"]["p0"]["mean"] == 1150 and r["race"]["p3"]["mean"] == 108


def test_season_finals_and_slam_winner_rule():
    pids = [f"p{i}" for i in range(12)]
    s = np.zeros(12)
    st = {"tour": "atp", "players": pids, "rank_pts": {}, "race_pts": {p: 5000 - 300 * i for i, p in enumerate(pids)},
          "drops": {}, "use_snapshot": False, "events": [], "logit": lambda a, b: SS._field_logit(np.zeros((12, 12)), 0, 12),
          "slam_winners": ["p10"], "finals": {"points": {"RR_win": 200, "SF_win": 400, "F_win": 500}}, "as_of": "2026-10-01"}
    r = SS.simulate_season(st, n=4000)
    q = r["finals_qual"]
    assert q["p10"] == 1.0 and "p7" not in q and all(q[f"p{i}"] == 1.0 for i in range(7))
    assert abs(sum(r["finals_title"].values()) - 1) < 1e-4
    assert r["points"]["p0"]["mean"] > 5000


def test_event_points_from_results_bye_rule():
    ev = {"level": "500", "year": 2026, "draw_size": 28}
    ms = [{"round": "R32", "p1": "b", "p2": "c", "winner": "b", "status": "done"},
          {"round": "R16", "p1": "b", "p2": "a", "winner": "b", "status": "done"},        # a had a bye, lost first match
          {"round": "QF", "p1": "b", "p2": "d", "winner": None, "status": "upcoming"}]
    pts, alive, rnd = SS.event_points(ev, ms, "atp")
    tab = SS._points.table("atp", "500", 28)
    assert pts["a"] == tab["R32"] and pts["c"] == tab["R32"]
    assert alive == {"b", "d"} and rnd == "QF"


def test_seeded_brackets_positions():
    pos = SS.std_positions(32)
    assert pos[0] == 0 and pos[1] >= 16                       # seeds 1 and 2 in opposite halves
    assert len({pos[k] // 8 for k in range(4)}) == 4          # seeds 1-4 in four different quarters
    assert len({pos[k] // 4 for k in range(8)}) == 8          # seeds 1-8 in eight different eighths
    rng = np.random.default_rng(0)
    order = np.tile(np.arange(28), (50, 1))
    lv = SS.seeded_brackets(order, 28, rng)
    assert lv.shape == (50, 32)
    for row in lv:
        assert sorted(x for x in row if x >= 0) == list(range(28))
        for seed in range(4):                                   # 4 byes to the top 4 seeds
            slot = list(row).index(seed)
            assert row[slot ^ 1] == -1


# ── markets ─────────────────────────────────────────────────────────────────

def _fixture():
    return json.loads((FIX / "markets_c.json").read_text(encoding="utf-8"))


def _store_from_fixture(fx):
    names = sorted({m["yes_sub_title"] for v in fx["kalshi"].values() for e in v for m in e["markets"]}
                   | {x for e in fx["polymarket"] for m in e["markets"]
                      for x in ([m["groupItemTitle"]] if m.get("groupItemTitle") else
                                (json.loads(m["outcomes"]) if m.get("sportsMarketType") == "moneyline" else []))})
    names = [n for n in names if n and n not in ("A", "B", "Other") and n != "Felix Auger Aliassime"]

    def td(n):                                                    # tennis-data style for every other player
        t = n.split()
        return " ".join(t[1:]) + " " + t[0][0] + "."
    players = {f"x:{i}": {"name": td(n) if i % 2 else n, "aliases": []} for i, n in enumerate(names)}
    ids = {n: f"x:{i}" for i, n in enumerate(names)}
    return players, ids


def test_map_player_initials_and_orders():
    players = {"1": {"name": "De Minaur A."}, "2": {"name": "Wang Xinyu"}, "3": {"name": "Felix Auger-Aliassime"},
               "4": {"name": "Jannik Sinner", "short": "J. Sinner"}, "5": {"name": "Wang Xiyu"}, "6": {"name": "Zverev A."},
               "7": {"name": "Zverev M."}}
    assert MK.map_player("Alex de Minaur", players) == "1"
    assert MK.map_player("Xinyu Wang", players) == "2"
    assert MK.map_player("Felix Auger Aliassime", players) == "3"
    assert MK.map_player("Sinner J.", players) == "4"
    assert MK.map_player("Alexander Zverev", players) == "6"
    assert MK.map_player("Zverev", players) is None                       # two Zverevs: refuse
    assert MK.map_player("Zverev", players, field=["6", "4"]) == "6"      # within the match's field
    assert MK.map_player("Nobody Here", players) is None
    more = {"8": {"name": "Tomas Barrios Vera"}, "9": {"name": "Mateus De Carvalho Cardoso Alves"}, "10": {"name": "Felipe Meligeni Alves"}}
    assert MK.map_player("Tomas Barrios", more) == "8"
    assert MK.map_player("Mateus Cardoso Alves", more) == "9"
    assert MK.map_player("Juan Alves", more) is None


def test_markets_futures_from_fixture(monkeypatch):
    fx = _fixture()
    players, ids = _store_from_fixture(fx)
    monkeypatch.setattr(MK, "kalshi_events", lambda s, **kw: fx["kalshi"].get(s, []))
    stores = {2026: {"players": players, "events": {"tokyo-2026": {"tid": "tokyo", "name": "Japan Open", "city": "Tokyo", "level": "500"}}}}
    f = MK.futures("atp", 2026, stores=stores, poly_events=fx["polymarket"])
    no1 = f["year_end_no1"]
    assert no1["available"] and set(no1["markets"]) == {"kalshi", "polymarket"}
    assert abs(sum(no1["probs"].values()) - 1) < 1e-3
    assert max(no1["probs"], key=no1["probs"].get) in (ids["Alexander Zverev"], ids["Jannik Sinner"])
    q = f["finals_qual"]
    assert q["probs"][ids["Carlos Alcaraz"]] > 0.9 and 5 < q["implied_total"] < 11
    assert "tokyo-2026" in f["tournaments"] and f["tournaments"]["tokyo-2026"]["markets"]["kalshi"] == "KXATP-26TOKYO"
    assert f["tournaments"]["wimbledon-2027"]["event"] == "wimbledon-2027"
    # every tournament field either passes the thin-market rule or says why not
    for v in f["tournaments"].values():
        assert v["available"] or v["reason"]
    usopen = f["tournaments"].get("us-open-2026")
    assert usopen is not None and str(usopen.get("reason", "")).startswith("settled")
    assert f["top10"]["available"] and f["top10"]["implied_total"] > 5


def test_markets_match_prices_from_fixture(monkeypatch):
    fx = _fixture()
    players, ids = _store_from_fixture(fx)
    monkeypatch.setattr(MK, "kalshi_events", lambda s, **kw: fx["kalshi"].get(s, []))
    m1 = {"id": "beijing-2026-R32-a", "event": "beijing-2026", "date": "2026-09-28", "round": "R32",
          "p1": ids["Jakub Mensik"], "p2": ids["Alexander Bublik"], "status": "upcoming",
          "odds": {"ps": [1.6, 2.5], "avg": [1.62, 2.3]}}
    m2 = {"id": "beijing-2026-R32-b", "event": "beijing-2026", "date": "2026-10-01", "round": "R32",
          "p1": ids["Ekaterina Alexandrova"], "p2": ids["Aliaksandra Sasnovich"], "status": "upcoming", "odds": None}
    store = {"players": players, "matches": {m1["id"]: m1}}
    r = MK.match_prices("atp", "2026-09-29", store=store, poly_events=fx["polymarket"])
    rec = r[m1["id"]]
    srcs = {x["source"]: x["p1"] for x in rec["sources"]}
    assert set(srcs) == {"kalshi", "polymarket"}
    assert 0.55 < srcs["kalshi"] < 0.67 and 0.55 < srcs["polymarket"] < 0.67      # Mensik ~ 0.61
    assert rec["basis"] == "prediction_markets" and rec["bookmakers"]["ps"] == pytest.approx((1 / 1.6) / (1 / 1.6 + 1 / 2.5), abs=1e-4)
    rw = MK.match_prices("wta", "2026-10-01", store={"players": players, "matches": {m2["id"]: m2}}, poly_events=fx["polymarket"])
    assert 0.55 < rw[m2["id"]]["p1"] < 0.62


def test_thin_market_rule():
    src = {"x": {"mid": {"a": 0.3, "b": 0.2}, "floor": set(), "eliminated": set(), "winner": None, "unmatched": []}}
    out = MK.assemble(src, ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"], "t")
    assert not out["available"] and out["reason"].startswith("thin")
    src["x"]["mid"].update({"c": 0.2, "d": 0.15, "e": 0.1})
    out = MK.assemble(src, ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"], "t")
    assert out["available"] and abs(sum(out["probs"].values()) - 1) < 1e-4


# ── backtest ────────────────────────────────────────────────────────────────

def test_score_and_orientation():
    s = BT.score([(0.8, 1), (0.2, 0), (0.6, 1), (0.4, 1)])
    assert s["n"] == 4 and 0 < s["logloss"] < 0.7 and len(s["reliability"]) == 4
    fl = [BT.flip(f"m{i}") for i in range(2000)]
    assert 0.45 < np.mean(fl) < 0.55
    assert BT.devig2([1.5, 2.5]) == pytest.approx((1 / 1.5) / (1 / 1.5 + 1 / 2.5))
    assert BT.observed({"best_of": 3, "sets": [[6, 4], [3, 6], [7, 6, 7, 3]]}) == {"sets": (2, 1), "games": 32, "margin": 0, "tb": True}


def test_backtest_on_synthetic_tour(tmp_path, monkeypatch):
    syn = pytest.importorskip("oddsmarkets.tennis.models.synthetic")
    pytest.importorskip("oddsmarkets.tennis.models.elo")
    monkeypatch.setenv("ACE_CACHE", str(tmp_path))
    ms, truth = syn.make_tour(n_players=36, n_matches=1800, seed=11, start=date(2017, 1, 1), days=900, bo5_share=0.2)
    rng = np.random.default_rng(0)
    for m in ms:                                        # a bookmaker that knows nothing: 50/50 at a 5% margin
        m["odds"] = {"avg": [1.9, 1.9]} if rng.random() < 0.5 else None
        m["rank1"], m["rank2"] = int(rng.integers(1, 200)), int(rng.integers(1, 200))
    r = BT.backtest("atp", years=[2018, 2019], matches=ms, events={}, warmup_years=1, refit_days=90, write=False,
                    use_cache=False, tournament_sims=0)
    mt = r["metrics"]
    assert mt["model"]["n"] > 800
    assert mt["model"]["logloss"] < mt["rank"]["logloss"] - 0.05
    assert mt["model"]["logloss"] < r["vs_avg"]["avg"]["logloss"]
    assert r["vs_avg"]["avg"]["logloss"] == pytest.approx(math.log(2), abs=1e-5)
    d = r["distributions"]
    for k, v in d["set_scores"]["3"].items():
        assert abs(v["pred"] - v["obs"]) < 0.06, k
    assert abs(d["total_games"]["mean"]["3"]["pred"] - d["total_games"]["mean"]["3"]["obs"]) < 1.0
    assert r["blend_by_year"]["2019"]["fitted"]
    lv = d["live_by_sets"]
    assert lv["all"]["n"] >= mt["model"]["n"] and lv["all"]["logloss"] < mt["model"]["logloss"]   # a set in, sharper
    for b in lv["all"]["reliability"]:
        if b["n"] >= 100:
            assert abs(b["mean_p"] - b["freq"]) < 0.08


def test_validate_hold_on_synthetic():
    syn = pytest.importorskip("oddsmarkets.tennis.models.synthetic")
    ms, truth = syn.make_tour(n_players=30, n_matches=2500, seed=5, start=date(2020, 1, 1), days=700, with_stats=True)
    v = BT.validate_hold("wta", ms, through="2021-12-31", window_days=800, min_matches=40)
    assert v["n_players"] >= 20
    assert v["hold"]["pearson"] > 0.8 and v["spw"]["pearson"] > 0.8


def test_binary_ceiling_and_placeholders():
    ev = {"markets": [{"yes_sub_title": "Carlos Alcaraz", "yes_bid_dollars": "0.9600", "yes_ask_dollars": "1.0000"},
                      {"yes_sub_title": "Casper Ruud", "yes_bid_dollars": "0.3000", "yes_ask_dollars": "0.3400"},
                      {"yes_sub_title": "Tommy Paul", "yes_bid_dollars": "0.0000", "yes_ask_dollars": "1.0000", "result": "no"},
                      {"yes_sub_title": "A", "yes_bid_dollars": "0.1", "yes_ask_dollars": "0.12"}]}
    players = {"1": {"name": "Carlos Alcaraz"}, "2": {"name": "Ruud C."}, "3": {"name": "Tommy Paul"}}
    src = MK.parse_kalshi_binary(ev, lambda lab: MK.map_player(lab, players))
    b = MK.binary({"kalshi": src}, "finals_qual")
    assert b["probs"] == {"1": 0.98, "2": 0.32, "3": 0.0} and b["ceiling"] == ["1"] and b["unmatched"] == []
    # a field market never uses the ceiling: a 1.00 ask is not a two-sided quote there
    f = MK.parse_kalshi_field(ev, lambda lab: MK.map_player(lab, players))
    assert "1" not in f["mid"] and f["eliminated"] == {"3"}


def test_dispersion_mixture():
    d0 = mc.solve_shift(0.7, 0.64, 0.62, 3, "tb7")
    base = mc.match(0.64 + d0, 0.62 - d0, 3, "tb7")
    prev = base["p_straight"]
    for sg in (0.02, 0.05):
        d = mc.solve_shift(0.7, 0.64, 0.62, 3, "tb7", sigma=sg)
        r = mc.match_mix(0.64 + d, 0.62 - d, 3, "tb7", sigma=sg)
        assert abs(float(r["p1_win"][0]) - 0.7) < 1e-6
        assert abs(r["games"].sum() - 1) < 1e-8 and abs(sum(float(v[0]) for v in r["sets"].values()) - 1) < 1e-10
        assert float(r["p_straight"][0]) > float(np.ravel(prev)[0])        # more lopsided, fewer games
        prev = r["p_straight"]
    assert float(mc.match_mix(0.65, 0.6, 3, "tb7", sigma=0.0)["p1_win"][0]) == pytest.approx(mc.match(0.65, 0.6)["p1_win"])


def test_chain_tables_free_memory_without_gc():
    """Recursive closures over numpy arrays once leaked (reference cycles); tables must free on refcount alone."""
    import gc
    import tracemalloc
    rng = np.random.default_rng(0)
    pa, pb = rng.uniform(0.55, 0.75, 3000), rng.uniform(0.55, 0.75, 3000)
    gc.disable()
    try:
        tracemalloc.start()
        mc.match_win_prob(pa, pb, 5, "tb10")
        base = tracemalloc.get_traced_memory()[0]
        for _ in range(20):
            mc.match_win_prob(pa, pb, 5, "tb10")
            float(mc.tiebreak_win(pa, pb, 10, 0)[0])
        grown = tracemalloc.get_traced_memory()[0] - base
        tracemalloc.stop()
    finally:
        gc.enable()
    assert grown < 5e6, grown



def test_season_drops_window_and_year_end_basis():
    """Last season's events drop when they end after snapshot - 364 days; year-end = Race + new + Finals."""
    def ev(tid, year, start, end, level="250", draw=None):
        return {"tid": tid, "year": year, "start": start, "end": end, "level": level, "draw_size": 4, "status": "done",
                "surface": "hard", "best_of": 3, "draw": draw}

    def ko(eid, w, l_, sf):
        return [{"id": f"{eid}-SF1", "event": eid, "round": "SF", "p1": w, "p2": sf[0], "winner": w, "status": "done", "date": None},
                {"id": f"{eid}-SF2", "event": eid, "round": "SF", "p1": l_, "p2": sf[1], "winner": l_, "status": "done", "date": None},
                {"id": f"{eid}-F", "event": eid, "round": "F", "p1": w, "p2": l_, "winner": w, "status": "done", "date": None}]
    prev = {"events": {"early-2025": ev("early", 2025, "2025-08-01", "2025-08-07"),        # ends before snapshot - 364: stays
                       "late-2025": ev("late", 2025, "2025-10-20", "2025-10-26", "500"),    # inside the window: drops
                       "finals-2025": ev("finals", 2025, "2025-11-09", "2025-11-16", "finals")},
            "matches": {}}
    for m in ko("early-2025", "a", "b", ("c", "d")) + ko("late-2025", "b", "a", ("c", "d")):
        prev["matches"][m["id"]] = m
    for i, (w, l_) in enumerate((("a", "b"), ("a", "c"), ("a", "d"), ("b", "c"), ("b", "d"), ("c", "d"))):
        prev["matches"][f"rr{i}"] = {"id": f"rr{i}", "event": "finals-2025", "round": "RR", "p1": w, "p2": l_, "winner": w,
                                     "status": "done", "date": None}
    cur = {"events": {"spring-2026": ev("spring", 2026, "2026-03-01", "2026-03-07", "500")}, "matches": {},
           "rankings": {"date": "2026-09-24", "rows": [[1, "a", 5000], [2, "b", 4000], [3, "c", 1000], [4, "d", 900]]}}
    for m in ko("spring-2026", "c", "a", ("b", "d")):
        cur["matches"][m["id"]] = m
    names = ["a", "b", "c", "d"]

    def prob(pids, surface, bo):
        return np.full((len(pids), len(pids)), 0.5)
    st = SS.build_state("atp", "2026-10-01", stores={2026: cur, 2025: prev}, prob=prob, n=200)
    t5 = SS._points.table("atp", "500", 4)
    # late-2025 (500: b won, a final) and the 2025 Finals (a 3 RR wins, b 2) drop; early-2025 does not
    assert st["drops"]["b"] == t5["W"] + 2 * 200 and st["drops"]["a"] == t5["F"] + 3 * 200
    assert {e[0] for e in st["drop_events"]["a"]} == {"late-2025", "finals-2025"}
    assert st["race_pts"]["c"] == t5["W"] and st["race_pts"]["a"] == t5["F"]
    r = SS.simulate_season(dict(st, events=[], finals=None), n=200)
    assert r["points"]["c"]["mean"] == t5["W"] and r["year_end_no1"] == {"c": 1.0}
    assert r["points"]["a"]["via_snapshot_mean"] == 5000 - (t5["F"] + 600)


def test_season_absent_player_returns_with_probability():
    pids = ["p0", "p1", "p2", "p3"]
    s = np.array([300.0, 200.0, 100.0, 0.0])
    st = {"tour": "wta", "players": pids, "rank_pts": {}, "race_pts": {p: 0 for p in pids}, "drops": {}, "use_snapshot": False,
          "events": [{"id": "x-2026", "level": "250", "draw_size": 4, "accept": 1.0, "surface": "hard", "best_of": 3,
                      "start": "2026-10-20", "entry": {p: 1.0 for p in pids}, "points": {"W": 250, "F": 163, "SF": 98}}],
          "logit": lambda a, b: SS._field_logit(s[:, None] - s[None, :], 0, 4), "slam_winners": [], "finals": None,
          "absent": {"p0": {"last_match": "2026-07-12", "missed_big": 3}}, "as_of": "2026-10-01"}
    r = SS.simulate_season(st, n=20000, seed=3)
    assert r["points"]["p0"]["added_mean"] == pytest.approx(0.5 * 250, rel=0.05)      # wins it whenever he returns
    assert r["year_end_no1"]["p0"] == pytest.approx(0.5, abs=0.02)


def test_year_end_no1_follows_the_race_not_the_official_ranking():
    """21 Oct 2026 (reported as a bug, it is not one): Sinner led the official ranking on 10,950 points against
    Zverev's 10,070, but 3,000 of Sinner's were last season's Vienna, Paris and Finals, which drop before the
    year-end ranking; the 2026 Race had Zverev ahead, 9,110 to 7,950. With Paris (1000) and the Finals left and
    Sinner out since Wimbledon, Zverev is the clear favourite (Kalshi 98.5%, Polymarket 99%), and Sinner, the
    ranking leader, is projected second. The site's 17% for Sinner is the absence rule's 50% chance he returns."""
    pids = ["zverev", "sinner"] + [f"x{i}" for i in range(6)]
    s = np.array([0.6, 1.0] + [0.0] * 6)
    st = {"tour": "atp", "players": pids, "rank_pts": {"sinner": 10950, "zverev": 10070},
          "race_pts": {"zverev": 9110, "sinner": 7950, **{f"x{i}": 3000 - 100 * i for i in range(6)}},
          "drops": {"sinner": 3000, "zverev": 960}, "earned_since_snapshot": {}, "use_snapshot": True,
          "events": [{"id": "paris-2026", "level": "m1000", "draw_size": 8, "accept": 1.0, "surface": "hard",
                      "best_of": 3, "start": "2026-10-26", "entry": {p: 1.0 for p in pids},
                      "points": {"W": 1000, "F": 650, "QF": 200}}],
          "logit": lambda a, b: SS._field_logit(s[:, None] - s[None, :], 0, 8), "slam_winners": [],
          "finals": {"points": {"RR_win": 200, "SF_win": 400, "F_win": 500}},
          "absent": {"sinner": {"last_match": "2026-07-12", "missed_big": 4}}, "as_of": "2026-10-21"}
    r = SS.simulate_season(st, n=6000, seed=1)
    no1 = r["year_end_no1"]
    assert no1["zverev"] > 0.7 > no1.get("sinner", 0.0)
    assert r["rank_dist"]["sinner"][1] > r["rank_dist"]["sinner"][0]           # projected second
    # the official-ranking route agrees once last season's points drop: 10,950 - 3,000 = the Race's 7,950
    assert r["points"]["sinner"]["via_snapshot_mean"] == pytest.approx(r["points"]["sinner"]["mean"], abs=1e-6)
    # without the absence rule he still needs to outscore Zverev by 1,160 in Paris and the Finals
    r2 = SS.simulate_season(dict(st, absent={}), n=6000, seed=1)
    assert no1["sinner"] < r2["year_end_no1"]["sinner"] < 0.5
