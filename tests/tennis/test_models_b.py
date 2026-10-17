"""Builder B models (tennis): exact game/tiebreak/set maths, the score likelihood, the serve/return fit on
point-by-point simulated matches, Elo and Bradley-Terry. Synthetic data only; no network."""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np
import pytest

from oddsmarkets.tennis.models import bt, elo
from oddsmarkets.tennis.models import serve_return as SR
from oddsmarkets.tennis.models import synthetic as SY


# ------------------------------------------------------------------ game / tiebreak / set maths

def test_hold_formula_known_values():
    assert SR.game_hold(0.6) == pytest.approx(0.735729, abs=1e-6)
    assert SR.game_hold(0.65) == pytest.approx(0.829645, abs=1e-6)
    assert SR.game_hold(0.5) == pytest.approx(0.5, abs=1e-15)
    for p in (0.3, 0.55, 0.7, 0.9):
        assert SR.game_hold(1 - p) == pytest.approx(1 - SR.game_hold(p), abs=1e-14)


def test_hold_formula_against_brute_force():
    # enumerate point sequences of one game up to 40 points
    def brute(p):
        tot = 0.0
        states = {(0, 0): 1.0}
        for _ in range(400):
            nxt = {}
            for (a, b), v in states.items():
                for (x, y), q in (((a + 1, b), p), ((a, b + 1), 1 - p)):
                    if x >= 4 and x - y >= 2:
                        tot += v * q
                    elif y >= 4 and y - x >= 2:
                        pass
                    else:
                        if x >= 4 and y >= 4:          # collapse deuce states
                            x, y = x - 1, y - 1
                        nxt[(x, y)] = nxt.get((x, y), 0.0) + v * q
            states = nxt
        return tot

    for p in (0.45, 0.6, 0.72):
        assert SR.game_hold(p) == pytest.approx(brute(p), abs=1e-12)


def test_hold_derivative():
    for p in (0.2, 0.5, 0.63, 0.85):
        num = (SR.game_hold(p + 1e-6) - SR.game_hold(p - 1e-6)) / 2e-6
        assert SR.game_hold_dp(p) == pytest.approx(num, rel=1e-6)


def test_point_prob_from_hold_inverts_exactly():
    ps = np.linspace(0.02, 0.98, 97)
    back = SR.point_prob_from_hold(SR.game_hold(ps))
    assert np.max(np.abs(back - ps)) < 1e-12
    hs = np.linspace(0.01, 0.99, 99)
    assert np.max(np.abs(SR.game_hold(SR.point_prob_from_hold(hs)) - hs)) < 1e-12
    assert isinstance(SR.point_prob_from_hold(0.8), float)
    assert SR.point_prob_from_hold(SR.game_hold(0.6)) == pytest.approx(0.6, abs=1e-13)


@pytest.mark.parametrize("to", [7, 10])
def test_tiebreak_sums_and_symmetry(to):
    for pa, pb in ((0.65, 0.6), (0.5, 0.5), (0.8, 0.55)):
        d = SR.tiebreak_score_probs(pa, pb, True, to, cap=200)
        assert sum(d.values()) == pytest.approx(1.0, abs=1e-12)
        win = sum(v for (a, b), v in d.items() if a > b)
        assert SR.tiebreak_win(pa, pb, True, to) == pytest.approx(win, abs=1e-12)
        # who serves first does not change the tiebreak winner's odds (iid points)
        assert SR.tiebreak_win(pa, pb, True, to) == pytest.approx(SR.tiebreak_win(pa, pb, False, to), abs=1e-12)
        # relabelling the players
        assert SR.tiebreak_win(pa, pb, True, to) == pytest.approx(1 - SR.tiebreak_win(pb, pa, False, to), abs=1e-12)
    assert SR.tiebreak_win(0.6, 0.6, True, to) == pytest.approx(0.5, abs=1e-12)


@pytest.mark.parametrize("rule", ["tb7", "tb10", "tb7@12", "adv"])
def test_set_score_probs_sum_to_one(rule):
    for h1, h2 in ((0.8, 0.7), (0.62, 0.66), (0.9, 0.88)):
        for fs in (1, 2, None):
            d, tail = SR.set_score_probs(h1, h2, fs, rule, with_tail=True)
            assert sum(d.values()) + tail == pytest.approx(1.0, abs=1e-12)
            assert all(v >= 0 for v in d.values())
            if rule != "adv":
                assert tail == 0.0
            else:
                assert 0 < tail < 0.05 and max(max(k) for k in d) == 20


def test_set_score_probs_symmetry():
    for rule in ("tb7", "tb10", "adv"):
        a = SR.set_score_probs(0.83, 0.71, 1, rule)
        b = SR.set_score_probs(0.71, 0.83, 2, rule)
        for (g1, g2), v in a.items():
            assert b[(g2, g1)] == pytest.approx(v, abs=1e-14)
        e = SR.set_score_probs(0.75, 0.75, None, rule)
        for (g1, g2), v in e.items():
            assert e[(g2, g1)] == pytest.approx(v, abs=1e-14)
    # the set winner's odds do not depend on who serves first (Newton-Keller), the scores do
    a1, a2 = SR.set_score_probs(0.85, 0.7, 1), SR.set_score_probs(0.85, 0.7, 2)
    assert sum(v for k, v in a1.items() if k[0] > k[1]) == pytest.approx(sum(v for k, v in a2.items() if k[0] > k[1]),
                                                                        abs=1e-12)
    assert abs(a1[(6, 4)] - a2[(6, 4)]) > 1e-4
    # with breaks impossible every set reaches 6-6
    d = SR.set_score_probs(1 - 1e-12, 1 - 1e-12, 1, "tb7")
    assert d[(7, 6)] + d[(6, 7)] == pytest.approx(1.0, abs=1e-9)


def test_set_score_probs_match_simulation():
    rng = np.random.default_rng(3)
    h1, h2 = 0.8, 0.68
    pa, pb = SR.point_prob_from_hold(h1), SR.point_prob_from_hold(h2)
    n = 20000
    cnt: dict = {}
    for _ in range(n):
        r = SY.simulate_match(pa, pb, best_of=1, final_set_rule="tb7", rng=rng, a_first=True)
        k = tuple(r["sets"][0][:2])
        cnt[k] = cnt.get(k, 0) + 1
    d = SR.set_score_probs(h1, h2, 1, "tb7")
    for k, v in d.items():
        se = math.sqrt(v * (1 - v) / n)
        assert abs(cnt.get(k, 0) / n - v) < 4.5 * se + 1e-4, k


# ------------------------------------------------------------------ score likelihood

SCORES = [([[6, 4], [7, 6, 7, 5], [6, 7, None, None]], "tb7"),
          ([[7, 6, 12, 10], [3, 6], [13, 12]], "tb7"),
          ([[6, 7, 8, 10], [7, 5], [8, 6]], "adv"),
          ([[7, 5], [6, 2]], "tb7"),
          ([[6, 7, 3, 7], [7, 6, None, None], [7, 6, 10, 8]], "tb10")]


def test_match_loglik_equals_chained_set_probabilities():
    def direct(sets, h1, h2, rule):
        tot = 0.0
        for fs in (1, 2):
            p, f = 1.0, fs
            for k, s in enumerate(sets):
                r = rule if k == 2 else "tb7"
                if max(s[:2]) == 13:
                    r = "tb7@12"
                d = SR.set_score_probs(h1, h2, f, r)
                g = (s[0], s[1])
                if len(s) > 2 and s[2] is not None and g in ((7, 6), (6, 7)):
                    pa, pb = SR.point_prob_from_hold(h1), SR.point_prob_from_hold(h2)
                    N = 10 if r == "tb10" else 7
                    tw = SR.tiebreak_win(pa, pb, f == 1, N)
                    p *= d[g] / (tw if g == (7, 6) else 1 - tw) * SR.tiebreak_score_probs(pa, pb, f == 1, N)[(s[2], s[3])]
                else:
                    p *= d[g]
                if (s[0] + s[1]) % 2:
                    f = 3 - f
            tot += 0.5 * p
        return math.log(tot)

    for (sets, rule), h1, h2 in zip(SCORES, (0.8, 0.75, 0.7, 0.6, 0.85), (0.7, 0.72, 0.66, 0.65, 0.8)):
        assert SR.match_loglik(sets, h1, h2, 3, rule) == pytest.approx(direct(sets, h1, h2, rule), abs=1e-10)


def test_match_loglik_gradient():
    S = SR._prep_sets([SR.parse_sets(s, 3, r) for s, r in SCORES])
    hA = np.array([0.8, 0.75, 0.7, 0.6, 0.85])
    hB = np.array([0.7, 0.72, 0.66, 0.65, 0.8])
    ll, gA, gB = SR.match_loglik_vec(hA, hB, S)
    for i in range(len(hA)):
        e = np.zeros(len(hA)); e[i] = 1e-6
        na = (SR.match_loglik_vec(hA + e, hB, S)[0] - SR.match_loglik_vec(hA - e, hB, S)[0])[i] / 2e-6
        nb = (SR.match_loglik_vec(hA, hB + e, S)[0] - SR.match_loglik_vec(hA, hB - e, S)[0])[i] / 2e-6
        assert gA[i] == pytest.approx(na, rel=1e-5, abs=1e-6)
        assert gB[i] == pytest.approx(nb, rel=1e-5, abs=1e-6)


def test_mirror_symmetry_of_score_likelihood():
    # without tiebreak points a scoreline cannot tell holds (hA, hB) from (1 - hB, 1 - hA)
    for sets, rule in SCORES:
        bare = [x[:2] for x in sets]
        assert SR.match_loglik(bare, 0.8, 0.7, 3, rule) == pytest.approx(SR.match_loglik(bare, 0.3, 0.2, 3, rule), abs=1e-10)


def test_fit_lands_in_the_physical_mode(synth):
    ms, truth = synth
    m = SR.fit(ms[:1500], half_life_days=1e6, ridge=1.0)
    assert m["base"]["mu"] > 0.5
    holds = [v["all"]["hold"] for v in m["players"].values()]
    assert np.mean(holds) > 0.6


def test_parse_sets_rules():
    # retirement: the unfinished set and anything after are dropped
    assert len(SR.parse_sets([[6, 3], [4, 2]], 3, "tb7")) == 1
    assert SR.parse_sets([[3, 1]], 3, "tb7") == []
    # 13-12 only as a deciding set; 8-6 only as a deciding set
    assert SR.parse_sets([[6, 4], [3, 6], [13, 12]], 3, "tb7")[-1][3] == 12
    assert len(SR.parse_sets([[8, 6], [6, 4]], 3, "tb7")) == 0
    # tb10 deciding set; missing winner points implied by the loser's
    c = SR.parse_sets([[6, 4], [3, 6], [7, 6, None, 8]], 3, "tb10")[-1]
    assert (c[4], c[5], c[6]) == (10, 10, 8)
    c = SR.parse_sets([[7, 6, None, 4]], 3, "tb7")[0]
    assert (c[4], c[5], c[6]) == (7, 7, 4)
    # inconsistent tiebreak points are ignored
    assert SR.parse_sets([[7, 6, 7, 6]], 3, "tb7")[0][5] == -1


# ------------------------------------------------------------------ the serve/return fit

@pytest.fixture(scope="module")
def synth():
    return SY.make_tour(n_players=40, n_matches=4000, seed=11, days=700)


@pytest.fixture(scope="module")
def fit_scores(synth):
    ms, _ = synth
    return SR.fit(ms, half_life_days=1e6, ridge=1.0)


def _arr(model, truth, key, surf="all"):
    pids = truth["pids"]
    return (np.array([model["players"][p][surf][key] for p in pids]),
            np.array([truth[key][p] for p in pids]))


def test_fit_recovers_planted_strengths_from_scores(fit_scores, synth):
    _, truth = synth
    m = fit_scores
    assert m["converged"] and m["version"] == SR.VERSION
    s, ts = _arr(m, truth, "s")
    r, tr = _arr(m, truth, "r")
    assert np.corrcoef(s, ts)[0, 1] > 0.9
    assert np.corrcoef(r, tr)[0, 1] > 0.9
    assert m["base"]["mu"] + np.mean(s) - np.mean(r) == pytest.approx(truth["mu"], abs=0.1)
    json.dumps(m)                                         # JSON-safe


def test_fit_on_scores_gets_hold_close(fit_scores, synth):
    _, truth = synth
    pids = truth["pids"]
    m = fit_scores
    planted_r = np.mean([truth["r"][p] for p in pids])
    planted = np.array([1 / (1 + math.exp(-(truth["mu"] + truth["s"][p] - planted_r))) for p in pids])
    # hold v an average returner: re-centre the model's returner at the planted mean
    est = np.array([1 / (1 + math.exp(-(m["base"]["mu"] + m["players"][p]["hard"]["s"]
                                        - np.mean([m["players"][q]["hard"]["r"] for q in pids])))) for p in pids])
    assert np.mean(np.abs(est - planted)) < 0.03
    assert np.corrcoef(est, planted)[0, 1] > 0.9


def test_standard_errors_roughly_calibrated(fit_scores, synth):
    _, truth = synth
    s, ts = _arr(fit_scores, truth, "s")
    se = np.array([fit_scores["players"][p]["all"]["se_s"] for p in truth["pids"]])
    z = (s - np.mean(s)) - (ts - np.mean(ts))
    cover = np.mean(np.abs(z) < 1.96 * se)
    assert 0.75 <= cover <= 1.0


def test_stats_layer_sharpens(synth, fit_scores):
    ms, truth = synth
    m = SR.fit(ms, half_life_days=1e6, ridge=1.0, stats=True)
    s, ts = _arr(m, truth, "s")
    s0, _ = _arr(fit_scores, truth, "s")
    assert np.corrcoef(s, ts)[0, 1] > max(0.97, np.corrcoef(s0, ts)[0, 1])
    assert m["n_stats"] > 0 and m["constants"]["stats"]
    se1 = np.mean([m["players"][p]["all"]["se_s"] for p in truth["pids"]])
    se0 = np.mean([fit_scores["players"][p]["all"]["se_s"] for p in truth["pids"]])
    assert se1 < se0


def test_stats_link_offsets_vanish_on_iid_data(synth):
    ms, _ = synth
    m = SR.fit(ms, half_life_days=1e6, ridge=1.0, stats=True)
    assert abs(m["base"]["k_hold"]) < 0.1 and abs(m["base"]["k_spw"]) < 0.05
    rec = m["players"][ms[0]["p1"]]["hard"]
    assert rec["hold"] == pytest.approx(rec["hold_chain"], abs=0.03)


def test_objective_gradient_with_stats():
    ms, _ = SY.make_tour(n_players=8, n_matches=60, seed=21)
    ms[3]["stats"]["p1"]["bp_saved"] = None                 # one side without the games part
    rows = SR._prepare(ms, None, None, True)
    d = SR._Design(rows, max(r[1] for r in rows), 200.0)
    pen = SR._penalty(d, 1.0, 2.0, 1.0)
    rng = np.random.default_rng(0)
    th = rng.normal(0, 0.3, d.n_par)
    th[0] = 0.8
    f, g = SR._objective(th, d, pen, 0.7)
    for i in [0, 3, SR.K_HOLD, SR.K_SPW, SR.NB + 1, SR.NB + d.P + 2, SR.NB + 2 * d.P + 4, d.n_par - 1]:
        e = np.zeros(d.n_par); e[i] = 1e-6
        num = (SR._objective(th + e, d, pen, 0.7)[0] - SR._objective(th - e, d, pen, 0.7)[0]) / 2e-6
        assert g[i] == pytest.approx(num, rel=1e-5, abs=1e-5), i


def test_validate_stats_on_iid_data():
    ms, _ = SY.make_tour(n_players=30, n_matches=3000, seed=8, start=date(2018, 1, 1), days=540)
    v = SR.validate_stats(ms, years=[2018], half_life_days=1e6, ridge=1.0)
    ins = v["in_sample"]["player_season"]
    assert ins["n"] >= 20
    assert ins["spw_raw"]["corr"] > 0.8 and abs(ins["spw_raw"]["bias"]) < 0.01
    assert abs(ins["hold_cal"]["bias"]) < 0.02
    assert "out_of_sample" in v and abs(v["offsets"][2018]["k_hold"]) < 0.15


def test_surface_deltas_recovered():
    ms, truth = SY.make_tour(n_players=30, n_matches=4000, seed=5, sd_delta=0.5, sd_s=0.3, sd_r=0.3,
                             surface_p=(0.4, 0.4, 0.2))
    m = SR.fit(ms, half_life_days=1e6, ridge={"s": 1.0, "delta": 1.0}, stats=True)
    pids = truth["pids"]
    est = np.array([m["players"][p]["clay"]["s"] - m["players"][p]["hard"]["s"] for p in pids])
    tru = np.array([truth["ds"][p][1] - truth["ds"][p][0] for p in pids])
    assert np.corrcoef(est, tru)[0, 1] > 0.8


def test_warm_start_and_time_decay(synth, fit_scores):
    ms, _ = synth
    last = max(m["date"] for m in ms)
    m2 = SR.fit(ms, through=last, half_life_days=1e6, ridge=1.0, prior=fit_scores)
    assert m2["iterations"] < fit_scores["iterations"]
    a = np.array([fit_scores["players"][p]["all"]["s"] for p in fit_scores["players"]])
    b = np.array([m2["players"][p]["all"]["s"] for p in fit_scores["players"]])
    assert np.max(np.abs(a - b)) < 0.02
    mid = (date.fromisoformat(last) - timedelta(days=200)).isoformat()
    m3 = SR.fit(ms, through=mid, half_life_days=120, ridge=1.0)
    assert m3["through"] == mid and m3["n_matches"] < len(ms)


def test_hold_prob_api(fit_scores, synth):
    _, truth = synth
    a, b = truth["pids"][:2]
    h = SR.hold_prob(fit_scores, a, b, "clay", "250", 3)
    assert 0 < h < 1
    assert SR.hold_prob(fit_scores, "x:nobody", "x:else", "grass") == pytest.approx(
        1 / (1 + math.exp(-(SR.base_logit(fit_scores, "grass") + fit_scores["base"]["new_s"] - fit_scores["base"]["new_r"]))))
    p1, p2 = SR.serve_point_probs(fit_scores, a, b, "hard")
    assert SR.game_hold(p1) == pytest.approx(SR.hold_prob(fit_scores, a, b, "hard"), abs=1e-12)
    rec = fit_scores["players"][a]["hard"]
    assert {"s", "r", "se_s", "se_r", "n", "hold", "break", "spw", "rpw"} <= set(rec)


def test_fit_excludes_walkovers_and_handles_empty():
    m = SR.fit([], through="2020-01-01")
    assert m["players"] == {} and m["n_matches"] == 0
    wo = {"id": "w", "date": "2020-01-01", "p1": "a", "p2": "b", "status": "wo", "sets": [], "best_of": 3,
          "surface": "hard", "level": "250"}
    ret = dict(wo, id="r", status="ret", sets=[[6, 4], [2, 1]])
    m = SR.fit([wo, ret])
    assert m["n_matches"] == 1 and m["n_sets"] == 1


def test_out_of_sample_score_loglik(synth, fit_scores):
    ms, _ = synth
    ll, n, ns = SR.score_loglik(fit_scores, ms[:200])
    assert n == 200 and ns > 400 and ll < 0
    null = SR.fit([], through="2020-01-01")
    ll0, _, _ = SR.score_loglik(null, ms[:200])
    assert ll > ll0


# ------------------------------------------------------------------ Elo and Bradley-Terry

def _elo_matches(n_players=50, n=8000, seed=4):
    rng = np.random.default_rng(seed)
    true = rng.normal(1500, 150, n_players)
    pids = [f"x:e{i}" for i in range(n_players)]
    out = []
    d0 = date(2010, 1, 1)
    for k in range(n):
        i, j = rng.choice(n_players, 2, replace=False)
        p = 1 / (1 + 10 ** (-(true[i] - true[j]) / 400))
        w, l = (i, j) if rng.random() < p else (j, i)
        surf = ("hard", "clay", "grass")[k % 3]
        out.append({"id": f"e{k}", "date": (d0 + timedelta(days=k // 10)).isoformat(), "p1": pids[w], "p2": pids[l],
                    "status": "done", "surface": surf, "best_of": 3, "level": "250", "rank1": None, "rank2": None})
    return out, dict(zip(pids, true))


def test_elo_recovers_planted_strengths():
    ms, true = _elo_matches()
    h = elo.history("atp", matches=ms, prm={"rho": 1.0})
    cur = h["current"]
    pids = list(true)
    est = np.array([cur[p]["all"] for p in pids])
    assert np.corrcoef(est, [true[p] for p in pids])[0, 1] > 0.9
    r = elo.ratings_at(h, "2100-01-01", decay=False)
    assert r[pids[0]]["all"] == pytest.approx(cur[pids[0]]["all"])
    mid = elo.ratings_at(h, ms[4000]["date"])
    assert max(v["n"] for v in mid.values()) < max(v["n"] for v in r.values())
    assert set(r[pids[0]]) >= {"all", "hard", "clay", "grass", "n"}


def test_elo_p_win_and_params():
    p = dict(elo.DEFAULT_PARAMS)
    a, b = {"all": 1700, "clay": 1800}, {"all": 1600, "clay": 1500}
    assert elo.p_win(a, b, "clay", 3, p) + elo.p_win(b, a, "clay", 3, p) == pytest.approx(1.0)
    assert elo.p_win(a, b, "clay", 5, p) > elo.p_win(a, b, "clay", 3, p) > elo.p_win(a, b, "hard", 3, p) > 0.5
    ms, _ = _elo_matches(n=1500)
    for m in ms:
        m["date"] = "2006" + m["date"][4:]
    l, n = elo.loss(ms, p)
    assert n == len(ms) and 0.4 < l / n < 0.75
    # inactivity pulls toward the mean
    h = elo.compute(ms[:200], dict(p, rho=0.5))
    r0 = elo.ratings_at(h, ms[199]["date"])
    r1 = elo.ratings_at(h, "2009-01-01")
    top = max(r0, key=lambda k: r0[k]["all"])
    assert abs(r1[top]["all"] - elo.MEAN) < abs(r0[top]["all"] - elo.MEAN)


def test_elo_fit_params_improves_loss():
    ms, _ = _elo_matches(n_players=40, n=3000, seed=9)
    for m in ms:
        m["date"] = str(2005 + int(m["date"][:4]) - 2010) + m["date"][4:]
    res = elo.fit_params(ms, maxfev=120)
    assert res["logloss"] <= res["default_logloss"] + 1e-12
    assert set(elo.FIT_KEYS) <= set(res["params"])


def test_bt_sane():
    ms, true = _elo_matches(n_players=30, n=3000, seed=2)
    m = bt.fit(ms, half_life_days=1e6, ridge=0.1)
    pids = list(true)
    th = np.array([m["players"][p]["theta"] for p in pids])
    assert np.corrcoef(th, [true[p] for p in pids])[0, 1] > 0.9
    a, b = pids[:2]
    assert bt.p_win(m, a, b) + bt.p_win(m, b, a) == pytest.approx(1.0)
    assert bt.p_win(m, "x:unknown", "x:unknown2") == pytest.approx(0.5)
    json.dumps(m)


def test_for_tour_without_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("ACE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ACE_CACHE", str(tmp_path / "cache"))
    m = SR.for_tour("wta")
    assert isinstance(m, dict) and "players" in m
    h = elo.history("atp")
    assert h["rows"] == []
    assert bt.for_tour("atp")["players"] == {}


def test_for_tour_reads_stores_and_caches(tmp_path, monkeypatch, synth):
    ms, _ = synth
    monkeypatch.setenv("ACE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ACE_CACHE", str(tmp_path / "cache"))
    d = tmp_path / "data" / "atp" / "2018"
    d.mkdir(parents=True)
    sub = [dict(m, stats=None) for m in ms[:600]]
    (d / "store.json").write_text(json.dumps({"tour": "atp", "year": 2018, "players": {}, "events": {},
                                              "matches": {m["id"]: m for m in sub}}), encoding="utf-8")
    m1 = SR.for_tour("atp")
    assert m1["n_matches"] == 600
    assert list((tmp_path / "cache" / "serve_return").glob("*.json"))
    h = elo.history("atp")
    assert len(h["rows"]) == 600
    assert (tmp_path / "cache" / "elo" / "atp.json").exists()
