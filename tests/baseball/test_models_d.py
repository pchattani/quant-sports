"""Builder D: prediction models (game simulation, live win probability, season / postseason simulation,
projections, awards, backtest) and the Kalshi / Polymarket parser, on synthetic data and the recorded
market fixture (markets_d.json, probed 2026-10-01). No network."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.baseball.models import awards as AW
from oddsmarkets.baseball.models import backtest as BT
from oddsmarkets.baseball.models import game_sim as G
from oddsmarkets.baseball.models import live as LV
from oddsmarkets.baseball.models import projections as PJ
from oddsmarkets.baseball.models import season_sim as SS
from oddsmarkets.baseball.models import synthetic_d as SD
from oddsmarkets.baseball.models._dio import E, NE

FIX = Path(__file__).parent / "fixtures" / "markets_d.json"


def _neutral(auto=True, hfa=None):
    L = G.league_split()
    spec = {"home": G.neutral_side(L), "away": G.neutral_side(L), "league": L, "auto_runner": auto}
    if hfa is not None:
        spec["hfa"] = hfa
    return spec


# ── series odds ──────────────────────────────────────────────────────────────

def _brute(p_home, p_away, best_of, pattern, wa=0, wb=0):
    need = best_of // 2 + 1
    tot = 0.0
    for outcome in itertools.product([1, 0], repeat=best_of - wa - wb):
        # every remaining game is "played" (games after the decision only spread probability), so each full
        # sequence is counted once; the winner is whoever reaches `need` first
        a, b, pr, winner = wa, wb, 1.0, None
        for k, w in enumerate(outcome):
            p = p_home if pattern[wa + wb + k] == "H" else p_away
            pr *= p if w else 1 - p
            a, b = a + w, b + (1 - w)
            if winner is None and (a >= need or b >= need):
                winner = "A" if a >= need else "B"
        if winner == "A":
            tot += pr
    return tot


@pytest.mark.parametrize("best_of,pattern", [(3, "HHH"), (5, "HHAAH"), (7, "HHAAAHH")])
def test_series_closed_form(best_of, pattern):
    for ph, pa in ((0.6, 0.52), (0.5, 0.5), (0.45, 0.38)):
        for wa, wb in ((0, 0), (1, 0), (0, 1), (1, 1)):
            if max(wa, wb) >= best_of // 2 + 1:
                continue
            assert SS.series_prob(ph, pa, best_of, pattern, wa, wb) == pytest.approx(_brute(ph, pa, best_of, pattern, wa, wb), abs=1e-12)
    assert SS.series_prob(0.6, 0.6, 3, "HHH") == pytest.approx(0.6 ** 2 + 2 * 0.6 ** 2 * 0.4)
    assert SS.series_prob(0.5, 0.5, 7, pattern="HHAAAHH") == pytest.approx(0.5)
    lens = SS.series_length(0.55, 0.5, best_of, pattern)
    assert sum(lens["A"].values()) == pytest.approx(SS.series_prob(0.55, 0.5, best_of, pattern))
    assert sum(lens["A"].values()) + sum(lens["B"].values()) == pytest.approx(1.0)


def test_series_simulation_matches_closed_form():
    T = 2
    P = np.array([[0.5, 0.58], [0.47, 0.5]])          # P[i, j]: i at home beats j
    L = SS._logit(P)
    rng = np.random.default_rng(0)
    S = 200000
    A, B = np.zeros(S, int), np.ones(S, int)
    w, _ = SS._series(A, B, "CS", L, np.zeros((S, T)), rng, {})
    exact = SS.series_prob(0.58, 1 - 0.47, 7, "HHAAAHH")
    assert (w == 0).mean() == pytest.approx(exact, abs=0.004)
    # a series in progress continues from its score
    w, _ = SS._series(A, B, "DS", L, np.zeros((S, T)), rng, {("DS", 0, 1): (2, 0)})
    assert (w == 0).mean() == pytest.approx(SS.series_prob(0.58, 0.53, 5, "HHAAH", 2, 0), abs=0.004)


# ── bracket and season ───────────────────────────────────────────────────────

def test_phase_triple_a_postseason_completes():
    # Triple-A's finals are best of three and typed "W": nobody reaches four wins, so the season is over when
    # nothing is left to play (an MLB store in the same state is still in its postseason)
    g = lambda gpk, gt, st, hs=3, as_=2: {"gpk": gpk, "date": "2025-09-23", "gtype": gt, "home": "1", "away": "2",  # noqa: E731
                                          "hs": hs, "as": as_, "status": st}
    games = {"a": g("a", "R", "final"), "b": g("b", "R", "postponed"), "c": g("c", "W", "final"), "d": g("d", "W", "final")}
    assert SS.phase({"level": "aaa", "games": games}) == "complete"
    assert SS.phase({"level": "mlb", "games": games}) == "postseason"
    games["e"] = g("e", "W", "scheduled", None, None)
    assert SS.phase({"level": "aaa", "games": games}) == "postseason"


def test_postseason_probabilities_sum_and_observed_series():
    st, r = SD.quick_store(seed=4, played_frac=1.0)
    S = SS.standings(st)
    al = S["seeds"]["AL"]
    assert len(al) == 6 and len(S["seeds"]["NL"]) == 6
    # seeds 1-3 are division winners, ordered by record
    assert all(S["teams"][t]["div_winner"] for t in al[:3])
    assert S["teams"][al[0]]["pct"] >= S["teams"][al[1]]["pct"] >= S["teams"][al[2]]["pct"]
    st["games"]["x1"] = {"gpk": "x1", "date": "2027-10-01", "gtype": "F", "home": al[2], "away": al[5], "hs": 4, "as": 2,
                         "status": "final"}
    st["games"]["x2"] = {"gpk": "x2", "date": "2027-10-02", "gtype": "F", "home": al[2], "away": al[5], "hs": 5, "as": 1,
                         "status": "final"}
    assert SS.phase(st) == "postseason"
    ps = SS.postseason(st, n=20000, seed=1)
    tot = {k: sum(v[k] for v in ps["teams"].values()) for k in ("p_ds", "p_lcs", "p_pennant", "p_ws")}
    assert tot == pytest.approx({"p_ds": 8, "p_lcs": 4, "p_pennant": 2, "p_ws": 1}, abs=1e-3)
    assert ps["teams"][al[2]]["p_ds"] == 1.0 and ps["teams"][al[5]]["p_ds"] == 0.0     # 2-0: series won
    assert ps["teams"][al[0]]["p_ds"] == 1.0                                              # bye
    for s in ps["series"]:
        if not s["done"]:
            assert s["p_home_field_sim"] == pytest.approx(s["p_home_field_closed_form"], abs=0.03)


def test_regular_season_sums_magic_and_conditional():
    st, r = SD.quick_store(seed=3, played_frac=0.7)
    res = SS.regular_season(st, n=6000, seed=2)
    T = res["teams"]
    assert sum(v["p_division"] for v in T.values()) == pytest.approx(6, abs=1e-3)       # 5-decimal rounding
    assert sum(v["p_wildcard"] for v in T.values()) == pytest.approx(6, abs=1e-3)
    assert sum(v["p_bye"] for v in T.values()) == pytest.approx(4, abs=1e-3)
    assert sum(v["p_ws"] for v in T.values()) == pytest.approx(1, abs=1e-3)
    for v in T.values():
        assert sum(v["seed_dist"]) == pytest.approx(1, abs=1e-4)
        if "next" in v:
            assert v["next"]["if_win"]["p_postseason"] >= v["next"]["if_loss"]["p_postseason"] - 0.02
    best, worst = max(r, key=r.get), min(r, key=r.get)
    assert T[best]["p_postseason"] > T[worst]["p_postseason"]
    # magic numbers: hand-worked on a finished division
    st2, _ = SD.quick_store(seed=3, played_frac=1.0)
    res2 = SS.regular_season(st2, n=500, seed=0)
    for t, v in res2["teams"].items():
        assert v["magic"]["clinched_division"] == (v["p_division"] == 1.0) or v["magic"]["division_magic"] == 0


def test_tiebreak_head_to_head():
    # two teams level on wins: the head-to-head winner ranks first
    W = np.array([[10.0, 10.0, 5.0]])
    G_ = np.array([[20.0, 20.0, 20.0]])
    H = np.zeros((1, 3, 3))
    H[0, 1, 0] = 3
    H[0, 0, 1] = 1
    same = np.ones((3, 3), bool)
    key = SS.rank_keys(W, G_, H, np.zeros((1, 3)), np.zeros((1, 3)), np.zeros((1, 3)), np.zeros((1, 3)), same,
                       np.random.default_rng(0))
    assert key[0, 1] > key[0, 0] > key[0, 2]


# ── the game simulation ──────────────────────────────────────────────────────

def test_extra_innings_rule():
    assert not G.auto_runner_rule(2019, "R")
    assert G.auto_runner_rule(2020, "R") and G.auto_runner_rule(2026, "R")
    assert not G.auto_runner_rule(2026, "D") and not G.auto_runner_rule(2024, "W")
    a = G.simulate(_neutral(auto=True), n=20000, seed=1, keep=True)
    b = G.simulate(_neutral(auto=False), n=20000, seed=1, keep=True)
    xa = a["_innings"][a["_innings"] > 9]
    xb = b["_innings"][b["_innings"] > 9]
    # with the runner on second, extra-inning games end sooner
    assert xa.mean() < xb.mean()
    assert (xa >= 12).mean() < (xb >= 12).mean()
    # no game ends tied, and a home team leading after 8.5 never bats in the 9th (scores are never equal)
    assert (a["_score"][:, 0] != a["_score"][:, 1]).all()


def test_pa_sim_reproduces_planted_run_environment():
    spec = _neutral(auto=False)
    res = G.simulate(spec, n=20000, seed=3)
    assert res["seconds"] < 4.0                     # target < 2 s for 20k games (slack for a loaded CI box)
    # Markov chain expectation of runs per half inning from the same tables and PA vector (no pitching change)
    F = LV.half_inning(G.LEAGUE_DEFAULT)
    per_half = float((F[0, 0] * np.arange(LV.R)).sum())
    assert res["runs"]["total"] / 2 == pytest.approx(per_half * 8.8, rel=0.06)
    # a planted run environment: doubling the HR rate raises scoring
    hot = dict(spec)
    m = np.ones(NE)
    m[E["HR"]] = 2.0
    hot["env"] = m
    assert G.simulate(hot, n=20000, seed=3)["runs"]["total"] > res["runs"]["total"] + 1.0
    # no home advantage and identical teams: a fair game (the last at-bat is worth little)
    flat = G.simulate(_neutral(auto=False, hfa=np.ones(NE)), n=40000, seed=5)
    assert flat["p_home"] == pytest.approx(0.5, abs=0.015)


def test_pa_sim_matches_independent_games():
    """game_sim's win rate and scoring against games played PA by PA by synthetic_d's independent loop."""
    w = SD.make_world(seed=7, talent_sd=1.5)
    tids = list(w["teams"])
    strong = max(tids, key=lambda t: -np.mean([w["players"][h]["true"][E["HR"]] for h in w["teams"][t]["hitters"][:9]]) * 0
                 + np.mean([w["players"][h]["true"][E["HR"]] + w["players"][h]["true"][E["BB"]] for h in w["teams"][t]["hitters"][:9]]))
    weak = min(tids, key=lambda t: np.mean([w["players"][h]["true"][E["HR"]] + w["players"][h]["true"][E["BB"]] for h in w["teams"][t]["hitters"][:9]]))
    starters = {strong: w["teams"][strong]["starters"][0], weak: w["teams"][weak]["starters"][0]}
    rng = np.random.default_rng(11)
    trans = G.default_transitions()
    league = G.league_split()
    wins, runs = 0, []
    n = 500
    for k in range(n):
        _, g = SD.play_game(w, strong, weak, rng, k, "2026-05-01", league, trans, starters)
        wins += g["hs"] > g["as"]
        runs.append(g["hs"] + g["as"])
    spec = {"home": SD.true_side(w, strong, starters[strong]), "away": SD.true_side(w, weak, starters[weak]),
            "league": league, "auto_runner": True}
    res = G.simulate(spec, n=20000, seed=2, trans=trans)      # the same (default) tables as the PA-by-PA loop
    se = np.sqrt(res["p_home"] * (1 - res["p_home"]) / n)
    assert abs(wins / n - res["p_home"]) < 3.5 * se + 0.02
    assert np.mean(runs) == pytest.approx(res["runs"]["total"], abs=3.5 * np.std(runs) / np.sqrt(n) + 0.3)


def test_outputs_consistent():
    res = G.simulate(_neutral(), n=20000, seed=4)
    assert res["p_home"] + res["p_away"] == pytest.approx(1.0)
    assert sum(res["total_dist"]) == pytest.approx(1.0, abs=1e-6)
    assert res["f5"]["home"] + res["f5"]["away"] + res["f5"]["tie"] == pytest.approx(1.0)
    assert res["runline"]["home_-1.5"] + res["runline"]["away_+1.5"] == pytest.approx(1.0)
    assert G.p_over(res, 8.5) == pytest.approx(res["over"]["8.5"], abs=1e-4)


def test_live_markov_matches_simulation():
    spec = _neutral()
    m = LV.LiveModel(spec)
    pre = m.win_prob({"inning": 1, "top": True, "outs": 0, "bases": 0, "score": [0, 0]})
    assert pre == pytest.approx(G.simulate(spec, n=40000, seed=9)["p_home"], abs=0.012)
    st = {"inning": 8, "top": False, "outs": 1, "bases": 3, "score": [4, 3]}
    sim = LV.live_sim(spec, st | {"sp_in": [False, False]}, n=40000, seed=1)["p_home"]
    assert m.win_prob(st) == pytest.approx(sim, abs=0.015)
    # walk-off logic and monotonicity in the count
    base = {"inning": 9, "top": False, "outs": 2, "bases": 7, "score": [5, 4]}
    assert m.win_prob(base | {"count": [3, 0]}) > m.win_prob(base) > m.win_prob(base | {"count": [0, 2]})
    assert m.win_prob({"inning": 9, "top": True, "outs": 3, "bases": 0, "score": [2, 3]}) == 1.0


# ── projections ──────────────────────────────────────────────────────────────

def _tot(rows):
    df = pd.DataFrame(rows).set_index("pid")
    for c in PJ.COUNT_COLS:
        if c not in df.columns:
            df[c] = 0.0
    return df


def test_projection_regression_direction():
    lg = {"K": 0.22, "BB": 0.08, "HBP": 0.01, "GB": 0.43, "XWCON": 0.37, "HRBIP": 0.045, "HITS": 0.30, "XBH": 0.07, "TRIP": 0.07}
    rows = []
    for pid, pa in (("small", 50), ("big", 600)):
        rows.append({"pid": pid, "PA": pa, "K": 0.40 * pa, "BB": 0.04 * pa, "HBP": 0, "BIP": 0.5 * pa, "GBALL": 0.2 * pa,
                     "HR": 0.05 * pa, "NHBIP": 0.45 * pa, "NHHITS": 0.15 * pa, "XBH": 0.03 * pa, "3B": 0.0,
                     "XW_SUM": 0.5 * pa * 0.5, "XW_N": 0.5 * pa})
    out = PJ.project_from_totals(_tot(rows), "hitter", lg, n_proj=600)
    k_small, k_big = out.loc["small", "K"], out.loc["big", "K"]
    # both regress toward the league rate from the observed 0.40, the smaller sample much further
    assert lg["K"] < k_small < k_big < 0.40
    assert lg["BB"] > out.loc["big", "BB"] > 0.04 and out.loc["small", "BB"] > out.loc["big", "BB"]
    # slow skills regress more than fast ones at the same sample (K stabilises at 60 PA, hits at 820 BIP)
    frac_k = (0.40 - k_big) / (0.40 - lg["K"])
    hits_obs = 0.15 / 0.45
    frac_h = (hits_obs - out.loc["big", "HITS"]) / (hits_obs - lg["HITS"])
    assert frac_h > frac_k
    # ranges contain the projection and narrow with sample
    assert out.loc["big", "K_p10"] < k_big < out.loc["big", "K_p90"]
    assert (out.loc["small", "K_p90"] - out.loc["small", "K_p10"]) > (out.loc["big", "K_p90"] - out.loc["big", "K_p10"])
    r = PJ.event_rates(out.loc["big"])
    assert r.sum() == pytest.approx(1.0) and r[E["K"]] == pytest.approx(k_big, rel=1e-6)


def test_aging_and_translation_defaults_and_platoon():
    ag = {"K": {"coef": (0.02, 0.006, 0.0)}}
    assert PJ.aging_delta(ag, "K", 33) > PJ.aging_delta(ag, "K", 25)
    assert PJ.aging_delta(ag, "K", None) == 0.0
    rates = G.LEAGUE_DEFAULT.copy()
    row = pd.Series({**{e: rates[i] * 500 for i, e in enumerate(E)}, "PA": 500, "SELF_L": 500,
                     **{f"{e}_L": rates[i] * 150 for i, e in enumerate(E)}, **{f"{e}_R": rates[i] * 350 for i, e in enumerate(E)},
                     "PA_L": 150, "PA_R": 350})
    pr = PJ.platoon_rates(rates, row, None, "hitter")
    # a left-handed hitter with no observed split keeps the league's platoon disadvantage against lefties
    assert pr["L"][E["K"]] > pr["R"][E["K"]]


# ── projections on synthetic seasons (pitch-table shaped), plus a backtest ───

@pytest.fixture(scope="module")
def synth_env(tmp_path_factory):
    root = tmp_path_factory.mktemp("bullpen")
    mp = pytest.MonkeyPatch()
    mp.setenv("BULLPEN_RAW", str(root / "raw"))
    mp.setenv("BULLPEN_CACHE", str(root / "cache"))
    mp.setenv("BULLPEN_DATA", str(root / "data"))
    # keep the synthetic runs hermetic and fast: builders B / C's models (stuff, parks, stabilisation) would
    # train on the synthetic pitch tables; our own fallbacks are what these tests exercise
    from oddsmarkets.baseball.models import _dio
    mp.setattr(_dio, "sibling", lambda name: None)
    # and the documented default base-out tables, not the committed fit (which moves with every refit and, at 300
    # simulations a game, moved this module's 40-game correlation check across its threshold)
    mp.setitem(G._TRANS, "mlb", G.default_transitions())
    w = SD.make_world(seed=2, per_div=2)
    SD.write_season(root / "raw", w, 2024, n_days=25, lines=False)
    _, st = SD.write_season(root / "raw", w, 2025, n_days=12, lines=True)
    yield w, st
    mp.undo()


def test_projection_without_bat_tracking_keeps_hr_prior():
    # before bat tracking (2023) bat speed is all NaN; it must drop out of the HR/BIP prior, not blank it
    rng = np.random.default_rng(0)
    n = 300
    bip = rng.integers(150, 450, n).astype(float)
    tot = pd.DataFrame({"HR": rng.binomial(bip.astype(int), 0.045).astype(float), "BIP": bip,
                        "XW_SUM": bip * rng.normal(0.37, 0.04, n), "XW_N": bip,
                        "GBALL": rng.binomial(bip.astype(int), 0.43).astype(float),
                        "BS_SUM": np.zeros(n), "BS_N": np.zeros(n), "PA": bip * 1.45}, index=[str(i) for i in range(n)])
    k = {"GB": 70.0, "XWCON": 50.0, "BATSPD": 50.0, "HRBIP": 800.0}
    pr = PJ.project_from_totals(tot, "hitter", {"GB": 0.43, "XWCON": 0.37, "BATSPD": float("nan"), "HRBIP": 0.045}, k=k)
    assert pr["BATSPD"].isna().all()
    assert np.isfinite(pr["HRBIP"]).all() and abs(float(pr["HRBIP"].mean()) - 0.045) < 0.01


def test_projection_tracks_truth_on_synthetic(synth_env):
    w, _ = synth_env
    pr = PJ.project("mlb", 2026, "next", role="hitter", n_proj=600, use_aging=False)
    assert len(pr) > 50
    tk = np.array([w["players"][p]["true"][E["K"]] for p in pr.index])
    assert np.corrcoef(tk, pr["K"])[0, 1] > 0.6
    raw = PJ.season_aggregates("mlb", 2025)[0]
    obs = (raw["K"] / raw["PA"]).reindex(pr.index)
    lgk = raw["K"].sum() / raw["PA"].sum()
    # projections are pulled toward the league: less spread than observed rates
    assert pr["K"].std() < obs.std()
    assert abs(pr["K"].mean() - lgk) < 0.02


def test_backtest_on_synthetic(synth_env):
    w, st = synth_env
    res = BT.backtest_season("mlb", 2025, n_sims=300, store=st, max_games=40)
    g = res["games"]
    assert len(g) == 40
    sm = BT._summ(g)
    for m in ("model", "ratings", "starter_record"):
        assert 0.5 < sm[m]["logloss"] < 0.8
    assert sm["vs_market"]["market"]["n"] == 40
    # the model sees the planted talent: it correlates with the true probabilities
    tp = [st["games"][r["gpk"]]["_true_p"] for r in g]
    assert np.corrcoef([r["model"] for r in g], tp)[0, 1] > 0.2      # 300 sims, one short season of history
    sc = BT.score([(0.9, 1), (0.1, 0), (0.6, 0)])
    assert sc["n"] == 3 and sc["brier"] == pytest.approx((0.01 + 0.01 + 0.36) / 3, abs=1e-5)


# ── awards ───────────────────────────────────────────────────────────────────

def test_award_winners_table_and_model():
    for award, by in AW.WINNERS.items():
        assert sorted(by) == list(range(2015, 2026))
        assert all(len(v) == 2 and all(v) for v in by.values())
    assert AW.VERIFIED and "baseball-reference" in AW.SOURCE
    assert AW.WINNERS["mvp"][2025] == ("Aaron Judge", "Shohei Ohtani")
    assert AW.WINNERS["cy"][2025] == ("Tarik Skubal", "Paul Skenes")
    assert AW.WINNERS["roy"][2025] == ("Nick Kurtz", "Drake Baldwin")
    rng = np.random.default_rng(0)
    rows = []
    for k in range(12):
        c = pd.DataFrame({"pid": [str(i) for i in range(20)], "value": rng.normal(3, 2, 20), "hr": rng.normal(25, 8, 20),
                          "team": rng.uniform(.4, .6, 20), "woba": rng.normal(.34, .03, 20)})
        for f in AW.FEATURES["mvp"]:
            c["z_" + f] = (c[f] - c[f].mean()) / c[f].std()
        rows.append((2015 + k, "AL", c, int(np.argmax(c["value"]))))
    f = AW.fit(rows, "mvp")
    assert f["source"] == "fitted" and f["beta"][0] > 1.0
    p = AW.softmax_probs(rows[0][2], "mvp", f["beta"])
    assert p.sum() == pytest.approx(1.0) and np.argmax(p) == rows[0][3]


# ── markets on the recorded fixture ─────────────────────────────────────────

@pytest.fixture(scope="module")
def fx():
    return json.loads(FIX.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mstore():
    from oddsmarkets.baseball import canon
    teams = {t: {"name": canon.team_name(t, 2026), "abbr": canon.team_abbr(t, 2026), "short": canon.team_short(t, 2026),
                 "league": canon.team_league(t, 2026)} for t in canon.team_ids()}
    ab = {v["abbr"]: k for k, v in teams.items()}
    games = {"1": {"gpk": "1", "date": "2026-10-01", "home": ab["ATL"], "away": ab["PHI"],
                   "lines": {"ml": [-125, 105], "close": {"ml": [-120, 100], "total": {"line": 7.5, "over": -110, "under": -110},
                                                          "rl": {"home": -1.5, "price": [150, -170]}}}},
             "2": {"gpk": "2", "date": "2026-10-03", "home": ab["MIL"], "away": ab["SD"]}}
    return {"teams": teams, "players": {}, "games": games}, ab


def test_markets_team_mapping(mstore):
    from oddsmarkets.baseball.sources import markets as M
    st, ab = mstore
    T = st["teams"]
    for code in ("NYY", "CWS", "AZ", "ATH", "WSH", "TB", "SD", "SF", "KC", "LAD"):
        assert M.map_team(None, T, code) == ab[code]
    assert M.map_team(None, T, "ARI") == ab["AZ"] and M.map_team(None, T, "OAK") == ab["ATH"]
    assert M.map_team("Chicago WS", T) == ab["CWS"] and M.map_team("Chicago C", T) == ab["CHC"]
    assert M.map_team("New York Y", T) == ab["NYY"] and M.map_team("Los Angeles D", T) == ab["LAD"]
    assert M.map_team("A's", T) == ab["ATH"] and M.map_team("Braves", T) == ab["ATL"]
    assert M.map_team("Boston Red Sox", T) == ab["BOS"]


def test_markets_futures_on_fixture(fx, mstore):
    from oddsmarkets.baseball.sources import markets as M
    st, ab = mstore
    fut = M.futures(2026, st, fx["poly"], fx["kalshi"])
    ws = fut["champion"]
    assert ws["available"] and sum(ws["probs"].values()) == pytest.approx(1.0, abs=1e-3)
    assert set(ws["sources"]) == {"kalshi", "polymarket"}
    alive = {t for t, p in ws["probs"].items() if p > 0}
    assert {ab[c] for c in ("LAD", "NYY", "MIL", "SD", "TB", "CLE", "CWS", "PHI", "ATL")} == alive
    assert max(ws["probs"], key=ws["probs"].get) == ab["LAD"]
    for lg in ("AL", "NL"):
        t = fut["pennant"][lg]
        assert t["available"] and all(st["teams"][k]["league"] == lg for k, v in t["probs"].items() if v > 0)
    mvp = fut["awards"]["al_mvp"]
    # Kalshi's "Yordan Álvarez" and Polymarket's "Yordan Alvarez" pool into one runner
    assert mvp["available"] and max(mvp["probs"], key=mvp["probs"].get) == "name:yordan alvarez"
    assert not any("player" in k or "tie" in k for k in fut["awards"]["al_roy"]["probs"])
    ser = {frozenset(s["teams"]): s for s in fut["series"]}
    wc = ser[frozenset((ab["PHI"], ab["ATL"]))]
    assert wc["round"] == "WC" and {x["source"] for x in wc["sources"]} == {"kalshi", "polymarket"}
    assert sum(wc["probs"].values()) == pytest.approx(1.0)
    assert ser[frozenset((ab["SD"], ab["MIL"]))]["probs"][ab["MIL"]] == pytest.approx(0.6071, abs=2e-3)
    assert fut["advance"]["NLDS"]["probs"][ab["SD"]] == 1.0


def test_markets_game_prices_on_fixture(fx, mstore):
    from oddsmarkets.baseball.sources import markets as M
    st, ab = mstore
    gp = M.game_prices("2026-10-01", st, fx["poly"], fx["kalshi"])
    g = gp["1"]
    assert {x["source"] for x in g["sources"]} == {"kalshi", "polymarket", "draftkings_ml"}
    assert g["basis"] == "prediction_markets" and 0.45 < g["p_home"] < 0.55
    dk = next(x for x in g["sources"] if x["source"] == "draftkings_ml")
    assert dk["p_home"] == pytest.approx((120 / 220) / (120 / 220 + 0.5), abs=1e-4)
    lad = g["total"]["kalshi"]
    assert list(lad) == sorted(lad) and lad[1.5] > lad[7.5] > lad[11.5]
    assert g["total"]["draftkings"]["line"] == 7.5
    assert g["runline"]["draftkings"]["home_line"] == -1.5
    f5 = g["f5"]
    assert f5["home"] + f5["away"] + f5["tie"] == pytest.approx(1.0, abs=1e-3) and f5["away"] > f5["home"]
    gp3 = M.game_prices("2026-10-03", st, fx["poly"], fx["kalshi"])
    assert gp3["2"]["p_home"] == pytest.approx(0.6129, abs=0.01)           # Brewers at home in NLDS game 1
    assert "home" in gp3["2"]["runline"]["kalshi"] and "away" in gp3["2"]["runline"]["kalshi"]
    assert M.devig_ml(-150, 130) == pytest.approx((150 / 250) / (150 / 250 + 100 / 230))
    assert M.edge(0.55, 0.5) == pytest.approx(0.1)
