"""Builder C: team strength, goal model, live WP, season simulation and tiebreakers, bracket and lottery, awards,
backtest and the market parsers. Synthetic data with planted truth and recorded fixtures only (no network)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.nhl.models import _cdata as D
from oddsmarkets.nhl.models import award_winners as AW
from oddsmarkets.nhl.models import awards as AWD
from oddsmarkets.nhl.models import backtest as BT
from oddsmarkets.nhl.models import game as GM
from oddsmarkets.nhl.models import live as LV
from oddsmarkets.nhl.models import season_sim as SS
from oddsmarkets.nhl.models import synthetic_c as SC
from oddsmarkets.nhl.models import team_strength as TS
from oddsmarkets.nhl.sources import markets as M

FIX = Path(__file__).with_name("fixtures") / "markets_c.json"
S1, S2, S3 = 20242025, 20252026, 20262027
GP = {"theta": 0.08, "tie_k": 0.85, "k_pull": 2.2, "r_en": 0.22, "pull1": 2.0, "pull2": 3.0,
      "k_ot": {"3v3": 1.85, "4v4": 1.2}, "so_home": 0.5, "b0": 0.0, "b_xg": 1.0, "b_g": 0.0, "home": 0.045,
      "s": {"b2b": -0.06, "rest": 0.0, "travel": 0.0, "tz": 0.0}}


@pytest.fixture(autouse=True)
def _iso(rink_roots):
    GM.set_params(None)
    yield
    GM.set_params(None)


@pytest.fixture(scope="module")
def lg():
    return SC.league((S1, S2, S3), seed=21)


@pytest.fixture(scope="module")
def lg_mid():
    return SC.league((S2, S3), seed=5, played_through="2026-12-20")


# ── team strength ────────────────────────────────────────────────────────────

def test_planted_strengths_recovered(lg):
    r = TS.fit(lg["tg"][S3], S3, None, None).as_dict()
    T = lg["truth"][S3]["teams"]
    teams = sorted(T)
    for u, floor in (("ev_off", 0.8), ("ev_def", 0.8), ("pp", 0.85), ("pk", 0.85), ("draw", 0.7)):
        a = np.array([T[t][u] for t in teams])
        b = np.array([r["teams"][t][u] for t in teams])
        assert np.corrcoef(a, b)[0, 1] > floor, u
    assert r["mode"] == "xg"
    # goaltending: a season's goals-v-xG signal is weak at the NHL's spread (sd 0.05); planted at sd 0.12 it shows
    lgg = SC.league((S3,), seed=4, sd_goalie=0.12)
    rg = TS.fit(lgg["tg"][S3], S3, None, None).as_dict()
    gt = lgg["truth"][S3]["goalies"]
    qs = [q for q, v in rg["goalies"].items() if q in gt and v["n"] >= 25]
    assert len(qs) >= 25
    assert np.corrcoef([gt[q] for q in qs], [rg["goalies"][q]["val"] for q in qs])[0, 1] > 0.5
    # the net rating orders teams like the truth's expected goal difference
    true_rd = SC.truth_rd(lg["truth"][S3])
    tn = [TS.side_goals(true_rd, t)[0] - TS.side_goals(true_rd, t)[1] for t in teams]
    assert np.corrcoef(tn, [r["teams"][t]["net"] for t in teams])[0, 1] > 0.75


def test_goalie_is_an_input(lg):
    rd = TS.fit(lg["tg"][S3], S3, None, None).as_dict()
    gl = sorted(rd["goalies"].items(), key=lambda kv: kv[1]["val"])
    good, bad = gl[0][0], gl[-1][0]
    h, a = "BOS", "TOR"
    gh_good, _ = TS.expected_goals(rd, h, a, None, good)
    gh_bad, _ = TS.expected_goals(rd, h, a, None, bad)
    assert gh_good < gh_bad                     # a better opposing goalie lowers the home side's goals
    p_good = GM.predict(h, a, S3, rd, {"goalie_a": good}, GM.params(GP))["p_home"]
    p_bad = GM.predict(h, a, S3, rd, {"goalie_a": bad}, GM.params(GP))["p_home"]
    assert p_good < p_bad


def test_time_decay_and_prior(lg):
    tgo = SC.tg_getter(lg)
    ch = TS.season_chain([S1, S2], tg_of=tgo)
    pr = TS.preseason_prior(ch["ends"][S2], S3, TS.params(), {})
    t = "BOS"
    assert pr["teams"][t]["ev_off"] == pytest.approx(TS.params()["carry"]["ev_off"] * ch["ends"][S2].teams[t]["ev_off"])
    # with no games the fit returns the prior
    r0 = TS.fit(pd.DataFrame(columns=D.TG_COLS), S3, None, pr, teams=sorted(pr["teams"]))
    assert r0.teams[t]["ev_off"] == pytest.approx(pr["teams"][t]["ev_off"])
    assert r0.mode == "xg"
    # decay: a half-life of 1 day makes the fit follow the latest games only
    tg = lg["tg"][S3]
    w_long = TS.fit(tg, S3, "2027-04-20", None, TS.params({"half_life_days": 1e6}))
    w_short = TS.fit(tg, S3, "2027-04-20", None, TS.params({"half_life_days": 3.0}))
    assert w_short.teams[t]["ev_off"] != pytest.approx(w_long.teams[t]["ev_off"])


def test_goals_mode_without_xg(lg):
    tg = lg["tg"][S3].copy()
    for c in ("ev_xgf", "ev_xga", "pp_xgf", "pk_xga", "xga_all", "ev_toi", "pp_toi", "pk_toi"):
        tg[c] = np.nan
    r = TS.fit(tg, S3, None, None).as_dict()
    assert r["mode"] == "goals"
    gh, ga = TS.expected_goals(r, "BOS", "TOR")
    assert 1.5 < gh < 4.5 and 1.5 < ga < 4.5


def test_schedule_context():
    g = pd.DataFrame([
        {"game_id": "1", "season": S3, "date": pd.Timestamp("2026-10-10"), "home": "BOS", "away": "VAN", "gtype": "REG", "played": True},
        {"game_id": "2", "season": S3, "date": pd.Timestamp("2026-10-11"), "home": "MTL", "away": "VAN", "gtype": "REG", "played": True},
        {"game_id": "3", "season": S3, "date": pd.Timestamp("2026-10-14"), "home": "BOS", "away": "MTL", "gtype": "REG", "played": True}])
    c = D.add_context(g)
    assert c.loc[1, "b2b_a"] == 1.0 and c.loc[1, "rest_a"] == 0.0
    assert 400 < c.loc[1, "km_a"] < 450                   # Boston -> Montreal
    assert c.loc[0, "rest_h"] == 7.0 and c.loc[0, "km_h"] == 0.0
    assert c.loc[2, "rest_a"] == 2.0                      # MTL: 11th -> 14th


def test_store_line_parsing():
    lines = {"src": "DraftKings", "ml": [-130, 110], "puck_line": {"home": -1.5, "price": [190, -230]},
             "total": {"line": 6.5, "over": 105, "under": -125},
             "open": {"ml": [-120, 100]}, "close": {"ml": [-135, 115], "puck_line": {"home": -1.5, "price": [185, -225]},
                                                   "total": {"line": 6.0, "over": -110, "under": -110}}}
    lf = D.line_fields(lines)
    assert (lf["ml_home"], lf["ml_away"], lf["pl_home"], lf["pl_price_home"], lf["total_line"]) == (-135, 115, -1.5, 185, 6.0)
    assert (lf["ml_home_open"], lf["ml_away_open"]) == (-120, 100)
    assert D._gid({"starter": 8483548, "used": [8483548]}) == "8483548"


# ── goal model ───────────────────────────────────────────────────────────────

def test_goal_model_probabilities_sum():
    p = GM.params(GP)
    mh, ma = np.array([3.2, 2.5, 3.0, 4.0]), np.array([2.7, 3.1, 3.0, 2.0])
    for po in (False, True):
        o = GM.outcome_probs(mh, ma, p, po, S3, full=True)
        assert np.allclose(o["p_reg_home"] + o["p_reg_away"] + o["p_ot"], 1.0, atol=1e-9)
        assert np.allclose(o["reg"].sum((1, 2)), 1.0, atol=1e-9)
        assert np.allclose(o["total_pmf"].sum(1), 1.0, atol=1e-9)
        assert np.all(o["pl_home"] <= o["p_reg_home"] + 1e-12) and np.all(o["pl_away"] <= o["p_reg_away"] + 1e-12)
        assert np.all((o["p_home"] > o["p_reg_home"]) & (o["p_home"] < o["p_reg_home"] + o["p_ot"]))
        if po:
            assert np.allclose(o["p_so"], 0.0)
    # symmetric teams: one half each when the shootout is a coin flip
    o = GM.outcome_probs([3.0], [3.0], p, False, S3)
    assert o["p_home"][0] == pytest.approx(0.5, abs=1e-9)
    # stronger home side: monotone
    a = GM.outcome_probs([3.0, 3.3, 3.6], [3.0, 3.0, 3.0], p, False, S3)["p_home"]
    assert a[0] < a[1] < a[2]


def test_ot_and_shootout_logic():
    p = GM.params(GP)
    mh, ma = 3.4, 2.6
    reg = GM.outcome_probs([mh], [ma], p, False, S3)
    po = GM.outcome_probs([mh], [ma], p, True, S3)
    share = mh / (mh + ma)
    assert po["p_ot_home"][0] == pytest.approx(po["p_ot"][0] * share, rel=1e-9)
    k = p["k_ot"]["3v3"]
    p_dec = 1 - math.exp(-5 * k * (mh + ma) / 60)
    assert reg["p_ot_home"][0] == pytest.approx(reg["p_ot"][0] * (p_dec * share + (1 - p_dec) * 0.5), rel=1e-9)
    assert reg["p_so"][0] == pytest.approx(reg["p_ot"][0] * (1 - p_dec), rel=1e-9)
    # 4-on-4 era: fewer overtimes decided before a shootout
    old = GM.outcome_probs([mh], [ma], p, False, 20102011)
    assert old["p_so"][0] > reg["p_so"][0]
    # an overtime game never covers -1.5
    R = GM.outcome_probs([mh], [ma], p, False, S3, full=True)["reg"][0]
    d = np.subtract.outer(np.arange(GM.NMAX + 1), np.arange(GM.NMAX + 1))
    assert R[d >= 2].sum() == pytest.approx(GM.outcome_probs([mh], [ma], p, False, S3)["pl_home"][0])


def test_correlation_and_empty_net_effects():
    p = GM.params(GP)
    ties = [GM.outcome_probs([3.0], [3.0], dict(p, theta=t), False, S3)["p_ot"][0] for t in (0.0, 0.2)]
    assert ties[1] > ties[0]
    # empty-net goals widen margins: P(margin >= 2) rises with r_en
    lo = GM.outcome_probs([3.3], [2.8], dict(p, r_en=0.05), False, S3)["pl_home"][0]
    hi = GM.outcome_probs([3.3], [2.8], dict(p, r_en=0.4), False, S3)["pl_home"][0]
    assert hi > lo


def test_simulation_matches_analytic():
    p = GM.params(GP)
    rng = np.random.default_rng(1)
    n = 200_000
    s = GM.simulate_scores(np.full(n, 3.3), np.full(n, 2.9), rng, p, False, S3)
    o = GM.outcome_probs([3.3], [2.9], p, False, S3)
    assert s["home_win"].mean() == pytest.approx(o["p_home"][0], abs=0.006)
    assert s["ot"].mean() == pytest.approx(o["p_ot"][0], abs=0.006)
    assert ((s["hs"] - s["as_"]) >= 2).mean() == pytest.approx(o["pl_home"][0], abs=0.008)
    assert (s["hs"] + s["as_"]).mean() == pytest.approx(o["exp_total"][0], abs=0.03)


def test_fit_recovers_home_and_back_to_back(lg):
    wf = GM.walk_forward([S2, S3], games=lg["games"], tg_of=SC.tg_getter(lg))
    assert len(wf) == 2 * 1344 and wf["n_rated"].iloc[-1] > 0
    p = GM.fit_means(wf, GM.params(GP))
    assert p["home"] > 0.0 and p["s"]["b2b"] < -0.01
    assert 0.6 < p["b_xg"] + p["b_g"] < 1.4
    p = GM.fit_ot(wf, p)
    assert 1.0 < p["k_ot"]["3v3"] < 3.0
    mh, ma = GM.means(wf, p)
    o = GM.outcome_probs(mh, ma, p, False, S3)
    pl = wf["played"].to_numpy()
    y = (wf["margin"] > 0).to_numpy(float)[pl]
    ll = -np.mean(y * np.log(o["p_home"][pl]) + (1 - y) * np.log(1 - o["p_home"][pl]))
    assert ll < math.log(2) - 0.005
    assert o["p_ot"][pl].mean() == pytest.approx(wf["ot"][pl].mean(), abs=0.03)


def test_market_helpers():
    assert GM.ml_to_p(-150, 130) == pytest.approx((150 / 250) / (150 / 250 + 100 / 230))
    assert GM.american_to_p(50) is None
    pmf = np.zeros(20)
    pmf[5], pmf[6], pmf[7] = 0.3, 0.4, 0.3
    assert GM.total_over(pmf, 5.5) == pytest.approx(0.7)
    assert GM.total_push(pmf, 6.0) == pytest.approx(0.4)
    assert GM.fair_total(pmf[None])[0] in (5.5, 6.5)


# ── live ─────────────────────────────────────────────────────────────────────

def test_live_win_probability():
    p = GM.params(GP)
    pre = {"mu_h": 3.3, "mu_a": 2.8}
    pg = GM.outcome_probs([3.3], [2.8], p, False, S3)["p_home"][0]
    start = LV.live_wp({"period": 1, "clock": "20:00", "hs": 0, "as": 0, "season": S3}, pre, p)
    assert start["wp_home"] == pytest.approx(pg, abs=0.03)
    up2 = LV.live_wp({"period": 3, "clock": "1:00", "hs": 3, "as": 1, "season": S3}, pre, p)["wp_home"]
    down1 = LV.live_wp({"period": 3, "clock": "1:00", "hs": 1, "as": 2, "season": S3}, pre, p)["wp_home"]
    assert up2 > 0.97 and 0.02 < down1 < 0.25
    tie_end = LV.live_wp({"period": 3, "clock": "0:00", "hs": 2, "as": 2, "season": S3}, pre, p)
    assert tie_end["p_ot"] == pytest.approx(1.0) and 0.5 < tie_end["wp_home"] < 0.6
    pp = LV.live_wp({"period": 2, "clock": "10:00", "hs": 1, "as": 1, "home_skaters": 5, "away_skaters": 4, "pp_left": 120,
                     "season": S3}, pre, p)["wp_home"]
    ev = LV.live_wp({"period": 2, "clock": "10:00", "hs": 1, "as": 1, "season": S3}, pre, p)["wp_home"]
    assert pp > ev
    assert LV.live_wp({"status": "final", "hs": 2, "as": 3}, pre, p)["wp_home"] == 0.0
    # overtime: playoffs sudden death at the rate share
    assert LV.live_wp({"period": 4, "clock": "12:00", "hs": 2, "as": 2, "playoff": True}, pre, p)["wp_home"] == pytest.approx(3.3 / 6.1)
    h, a = LV.means_from_p(0.62, prm=p, season=S3)
    assert GM.outcome_probs([h], [a], p, False, S3)["p_home"][0] == pytest.approx(0.62, abs=1e-3)
    ser = LV.wp_series([{"period": 1, "clock": "20:00", "hs": 0, "as": 0}, {"period": 3, "clock": "0:30", "hs": 4, "as": 1}], pre, p)
    assert ser[0][0] == 0.0 and ser[1][1] > 0.99


def test_live_overtime_elapsed_time():
    """Regular-season overtime is 5 minutes: elapsed time runs 3600 -> 3900 (not +900 s), a goal's row carries the
    score after it, and playoff overtime periods are 20 minutes each."""
    p = GM.params(GP)
    pre = {"mu_h": 3.3, "mu_a": 2.8}
    # clock-based states: 2:00 left in RS overtime = 3780 s elapsed; playoff OT with 5:00 left = 3600 + 900, 2OT with 15:00 left = 4800 + 300
    ser = LV.wp_series([{"period": 4, "clock": "2:00", "hs": 2, "as": 2},
                        {"period": 4, "clock": "5:00", "hs": 2, "as": 2, "playoff": True},
                        {"period": 5, "clock": "15:00", "hs": 2, "as": 2, "playoff": True}], pre, p)
    assert [r[0] for r in ser] == [3780.0, 4500.0, 5100.0]
    assert LV.elapsed(5, 0.0, False) == 3900.0
    # events frame: RS game decided in overtime at 3725 s, scores before the event
    ev = pd.DataFrame({"game_id": ["2015020001"] * 4, "period": [1, 3, 4, 4], "sec": [0.0, 3000.0, 3600.0, 3725.0],
                       "type": ["FAC", "GOAL", "FAC", "GOAL"], "is_home": [1, 0, 1, 1],
                       "score_home": [0, 2, 2, 2], "score_away": [0, 1, 2, 2]})
    out = LV.from_events(ev, pre, p)
    assert [r[0] for r in out] == [0.0, 3000.0, 3600.0, 3725.0]
    assert 0.4 < out[2][1] < 0.7 and out[3][1] == 1.0
    # the third-period equaliser leaves the game tied
    tied = LV.live_wp({"period": 3, "sec_left": 600.0, "hs": 2, "as": 2}, pre, p)["wp_home"]
    assert out[1][1] == pytest.approx(round(tied, 4))
    # playoff game id: overtime is 20-minute sudden death, elapsed carried as is
    po = ev.assign(game_id="2015030111", sec=[0.0, 3000.0, 3600.0, 4500.0])
    out = LV.from_events(po, pre, p)
    assert out[3][0] == 4500.0 and out[2][1] == pytest.approx(3.3 / 6.1, abs=1e-4)


# ── tiebreakers ──────────────────────────────────────────────────────────────

def _ranker_from(records: dict, games: list[dict], season: int, order: list[str]):
    """Simulator ranker for one 'simulation' built from canon-style records and games."""
    idx = {t: i for i, t in enumerate(order)}
    T = len(order)
    kind, steps = SS.tiebreak_steps(season)
    arr = {k: np.array([[records[t][k] for t in order]]) for k in ("pts", "gp", "rw", "row", "w", "gf", "ga")}
    K = SS.sort_key(arr["pts"], arr["gp"], arr["rw"], arr["row"], arr["w"], kind)
    HP = np.zeros((1, T, T), np.int16)
    NG = np.zeros((T, T), np.int64)
    for g in games:
        h, a = idx[g["home"]], idx[g["away"]]
        hp, ap = (2, 1 if g.get("ot") else 0) if g["hs"] > g["as"] else (1 if g.get("ot") else 0, 2)
        HP[0, h, a] += hp
        HP[0, a, h] += ap
        NG[h, a] += 1
        NG[a, h] += 1
    return SS.Ranker(K, HP, NG, arr["gf"] - arr["ga"], arr["gf"], steps, np.random.default_rng(0)), idx


def test_tiebreak_regulation_wins_first():
    rec = {"AAA": {"pts": 10, "gp": 8, "rw": 3, "row": 5, "w": 5, "gf": 20, "ga": 20},
           "BBB": {"pts": 10, "gp": 8, "rw": 4, "row": 4, "w": 5, "gf": 18, "ga": 25},
           "CCC": {"pts": 10, "gp": 7, "rw": 2, "row": 2, "w": 4, "gf": 10, "ga": 30}}
    rk, idx = _ranker_from(rec, [], S3, list(rec))
    o = [list(rec)[i] for i in rk.rank(np.arange(3))[0]]
    assert o == ["CCC", "BBB", "AAA"]                  # fewer games played, then regulation wins
    from oddsmarkets.nhl import canon
    assert canon.rank(list(rec), rec, [], S3) == o
    # 2010-11 .. 2018-19: ROW, not RW
    rk2, _ = _ranker_from({k: dict(v, gp=8) for k, v in rec.items()}, [], 20152016, list(rec))
    o2 = [list(rec)[i] for i in rk2.rank(np.arange(3))[0]]
    assert o2[0] == "AAA"


def test_three_club_tie_head_to_head_then_goal_difference():
    # A, B, C equal on points, RW, ROW, W. Among themselves: A 8/8 points; B and C 3/8 each (B won its two-club
    # series 3-2 on points). The three-club step separates A only; B and C carry on to goal differential (C better):
    # A, C, B. A restart at the two-club head-to-head would have put B ahead of C.
    g = [{"home": "AAA", "away": "BBB", "hs": 3, "as": 1}, {"home": "BBB", "away": "AAA", "hs": 1, "as": 2},
         {"home": "AAA", "away": "CCC", "hs": 4, "as": 2}, {"home": "CCC", "away": "AAA", "hs": 2, "as": 3, "ot": True},
         {"home": "BBB", "away": "CCC", "hs": 3, "as": 2}, {"home": "CCC", "away": "BBB", "hs": 3, "as": 2, "ot": True}]
    base = {"pts": 20, "gp": 16, "rw": 8, "row": 9, "w": 9}
    rec = {"AAA": dict(base, gf=40, ga=40), "BBB": dict(base, gf=40, ga=45), "CCC": dict(base, gf=41, ga=42)}
    games = [dict(x, status="final", type=2, so=False, ot=x.get("ot", False), start=f"2026-10-{i + 10:02d}")
             for i, x in enumerate(g)]
    from oddsmarkets.nhl import canon
    expect = canon.rank(list(rec), rec, games, S3)
    assert expect == ["AAA", "CCC", "BBB"]
    rk, idx = _ranker_from(rec, games, S3, list(rec))
    assert [list(rec)[i] for i in rk.rank(np.arange(3))[0]] == expect


def test_odd_game_excluded_from_head_to_head():
    games = {}
    rows = [("2026020001", "2026-10-10", "XXX", "YYY", 3, 2), ("2026020002", "2026-11-10", "YYY", "XXX", 1, 4),
            ("2026020003", "2026-12-10", "XXX", "YYY", 1, 5)]
    for gid, d, h, a, hs, as_ in rows:
        games[gid] = {"game_id": gid, "date": d, "type": 2, "home": h, "away": a, "hs": hs, "as": as_, "status": "final",
                      "ot": False, "so": False}
    st = {"games": games}
    info = {"XXX": {"division": "D1", "conference": "C1"}, "YYY": {"division": "D1", "conference": "C1"}}
    S0 = SS.build_state(S3, st, teams_info=info)
    i, j = S0["idx"]["XXX"], S0["idx"]["YYY"]
    # XXX hosted two of three: its first home game (the 3-2 win) is excluded
    assert S0["NG"][i, j] == 2
    assert S0["HP0"][i, j] == 2 and S0["HP0"][j, i] == 2
    assert S0["P"][i] == 4 and S0["GF"][i] == 3 + 4 + 1


# ── season simulation ───────────────────────────────────────────────────────

def test_season_sim_sums_and_seeding(lg_mid):
    rd = SC.truth_rd(lg_mid["truth"][S3])
    for t in rd["teams"]:
        rd["teams"][t]["se_net"] = 0.15
        rd["teams"][t]["net"] = 0.0
    res = SS.simulate(S3, n=1500, seed=3, state={"store": lg_mid["stores"][S3], "ratings": rd, "params": GP,
                                                "through": "2026-12-21"})
    assert res["ok"] and res["format"] == "wildcard"
    T = res["teams"]
    tot = lambda k: sum(v[k] for v in T.values())  # noqa: E731
    assert tot("p_playoffs") == pytest.approx(16.0)
    assert tot("p_div") == pytest.approx(4.0) and tot("p_top3") == pytest.approx(12.0) and tot("p_wildcard") == pytest.approx(4.0)
    assert tot("p_cup") == pytest.approx(1.0) and tot("p_conf") == pytest.approx(2.0) and tot("p_pres") == pytest.approx(1.0)
    for r, k in (("r1", 16), ("r2", 8), ("conf_final", 4), ("final", 2)):
        assert sum(v["p_reach"][r] for v in T.values()) == pytest.approx(k)
    assert sum(v["lottery"]["p_first"] for v in T.values()) == pytest.approx(1.0)
    for t, v in T.items():
        assert v["p_cup"] <= v["p_conf"] <= v["p_playoffs"] + 1e-9
        assert sum(v["points_dist"].values()) == pytest.approx(1.0, abs=1e-3)
        assert v["p_points_ge"][50] >= v["p_points_ge"][100]
        assert v["lottery"]["p_first"] <= 1 - v["p_playoffs"] + 1e-9
        assert v["exp_pts"] >= v["current"]["pts"]
        nx = v["next"]
        if nx:
            assert 0 < nx["p_win"] < 1
            assert nx["if_win"]["p_playoffs"] >= nx["if_loss"]["p_playoffs"] - 0.03
    # each team's expected points: current + 2 x expected wins left, about one point per game left on average
    gp_left = sum(v["current"]["remaining"] for v in T.values())
    gained = sum(v["exp_pts"] - v["current"]["pts"] for v in T.values())
    assert 1.05 * gp_left < gained < 1.2 * gp_left       # 2 points a game plus about 0.23 for overtime


def test_completed_season_seeds_match_canon(lg):
    st = lg["stores"][S2]
    rd = SC.truth_rd(lg["truth"][S2])
    res = SS.simulate(S2, n=200, seed=1, state={"store": st, "ratings": rd, "params": GP})
    made = {t for t, v in res["teams"].items() if v["p_playoffs"] > 0.5}
    assert all(v["p_playoffs"] in (0.0, 1.0) for v in res["teams"].values())
    from oddsmarkets.nhl import canon
    S0 = SS.build_state(S2, st)
    rec = {t: {"gp": int(S0["GP"][i]), "w": int(S0["W"][i]), "l": int(S0["L"][i]), "otl": int(S0["OTL"][i]),
               "pts": int(S0["P"][i]), "rw": int(S0["RW"][i]), "row": int(S0["ROW"][i]), "gf": int(S0["GF"][i]),
               "ga": int(S0["GA"][i])} for i, t in enumerate(S0["teams"])}
    games = [dict(g, home=g["home"], away=g["away"]) for g in st["games"].values()]
    seeds = canon.playoff_seeds(S2, rec, games)
    want = {t for c in seeds.values() for d in c["divisions"].values() for t in d} | {t for c in seeds.values() for t in c["wild_cards"]}
    assert made == want
    divw = {t for t, v in res["teams"].items() if v["p_div"] > 0.5}
    assert divw == {d[0] for c in seeds.values() for d in c["divisions"].values()}
    # the Presidents' Trophy goes to canon's league leader
    lead = canon.rank(list(rec), rec, games, S2)[0]
    assert res["teams"][lead]["p_pres"] == 1.0
    # standings helper agrees with canon
    rows = SS.standings(S2, st)
    assert rows[0]["team"] == lead


def test_bracket_pairs_and_home_ice(lg):
    st = lg["stores"][S2]
    rd = SC.truth_rd(lg["truth"][S2])
    res = SS.simulate(S2, n=300, seed=2, state={"store": st, "ratings": rd, "params": GP})
    S0 = SS.build_state(S2, st)
    lpos = {t: r for t, r in SS._current_order(S0, *SS.tiebreak_steps(S2), 0)["league"].items()}
    for m in res["bracket"]["matchups"]["r1"]:
        assert lpos[m["home_ice"]] < lpos[m["other"]]           # better record holds home ice
    r1 = res["bracket"]["matchups"]["r1"]
    assert len(r1) == 8 and all(m["p"] == pytest.approx(1.0) for m in r1)


def test_lottery_matrix_matches_published_odds():
    Mx = SS.lottery_matrix()
    assert np.allclose(Mx.sum(0), 1.0) and np.allclose(Mx.sum(1), 1.0)
    first = Mx[:, 0] * 100
    assert first[0] == pytest.approx(18.5 + 2.5 + 2.0 + 1.5 + 0.5 + 0.5)      # 25.5: slots 12-16 cannot jump to 1
    assert np.allclose(first[1:11], SS.LOTTERY_ODDS[1:11])
    assert np.allclose(first[11:], 0.0)
    assert Mx[0, 1] * 100 == pytest.approx(18.8, abs=0.1)
    for slot in range(16):
        best = min(k for k in range(16) if Mx[slot, k] > 0)
        assert slot - best <= 10                                 # never more than ten places up
        worst = max(k for k in range(16) if Mx[slot, k] > 0)
        assert worst <= slot + 2                                 # two draws: at most two places down
    # the worst club can fall at most to third
    assert Mx[0, 3:].sum() == pytest.approx(0.0)


def test_magic_numbers_hand_worked():
    # one division of four in a conference of eight: P = points, R = games left
    P = np.array([100, 90, 80, 60, 95, 85, 70, 50])
    R = np.array([2, 2, 2, 2, 2, 2, 2, 2])
    div = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    conf = np.zeros(8, int)
    mg = SS.magic_numbers(P, R, div, conf)
    # team 0: division magic = max over rivals (P_j + 2R_j - P_i + 1) = 90 + 4 - 100 + 1 = -5 -> clinched
    assert mg[0]["clinched"]["division"] and mg[0]["magic"]["division"] == 0
    # team 3 (60 + 4 = 64 at most): three division rivals already above -> top three lost; eight-rival test cannot
    # be met in a conference of eight, so playoffs are not marked eliminated by the sufficient condition
    assert mg[3]["eliminated"]["division"] and mg[3]["tragic"]["playoffs"] >= 0
    # team 1: 3rd-largest of rivals' reach in its division: (100+4, 80+4, 60+4) - 90 + 1 -> 64 - 89 < 0 -> top 3 clinched
    assert mg[1]["clinched"]["playoffs"]


# ── awards ───────────────────────────────────────────────────────────────────

def test_winners_table_integrity():
    for a in ("hart", "vezina", "norris", "calder", "ross", "richard", "selke"):
        seasons = sorted(AW.WINNERS[a])
        assert seasons[0] == 20092010 and seasons[-1] == 20252026 and len(seasons) == 17
    assert len(AW.WINNERS["richard"][20092010]) == 2 and len(AW.WINNERS["richard"][20192020]) == 2
    assert AW.WINNERS["ross"][20222023][0] == ("Connor McDavid", "EDM", 153)
    assert AW.VERIFIED == "2026-10-01" and len(AW.SOURCES) == 7


def _synthetic_ps(seed: int, winner_pts: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 120
    pos = np.array(["C", "L", "R", "D"] * 30)
    pts = rng.normal(55, 18, n).clip(5, None)
    pts[pos == "D"] *= 0.6
    df = pd.DataFrame({"player": [f"p{seed}_{i}" for i in range(n)], "name": [f"Player {seed} {i}" for i in range(n)],
                       "team": rng.choice(["BOS", "TOR", "EDM", "COL"], n), "pos": pos, "gp": 82, "g": pts * 0.4,
                       "a": pts * 0.6, "pts": pts, "pm": rng.normal(0, 10, n), "toi_pg": 18.0, "rookie": rng.random(n) < 0.1,
                       "age": 25, "gp_g": np.nan, "xga": np.nan, "ga": np.nan, "gsax": np.nan, "sv": np.nan,
                       "team_pct": 0.55, "team_gp": 82, "value": pts / 10 + rng.normal(0, 1, n), "value_def": rng.normal(0, 1, n)})
    g = pd.DataFrame({"player": [f"g{seed}_{i}" for i in range(12)], "name": [f"Goalie {seed} {i}" for i in range(12)],
                      "team": "BOS", "pos": "G", "gp_g": 55, "gsax": rng.normal(5, 10, 12), "sv": 0.91, "team_pct": 0.55,
                      "team_gp": 82, "rookie": False})
    return pd.concat([df, g], ignore_index=True)


def test_award_logit_and_leader_sim(monkeypatch):
    tables = {}
    for k, s in enumerate(range(2010, 2026)):
        sid = s * 10000 + s + 1
        ps = _synthetic_ps(k)
        tables[sid] = ps
        top = ps[ps["pos"] != "G"].sort_values("pts").iloc[-1]["name"]
        topd = ps[ps["pos"] == "D"].sort_values("pts").iloc[-1]["name"]
        monkeypatch.setitem(AW.WINNERS["hart"], sid, [(top, "BOS")])
        monkeypatch.setitem(AW.WINNERS["norris"], sid, [(topd, "BOS")])
    fit = AWD.fit(sorted(tables), ps_of=lambda s: tables[s])
    assert fit["awards"]["hart"]["ok"] and fit["awards"]["hart"]["top1"] >= 12
    assert fit["awards"]["norris"]["ok"]
    ps = _synthetic_ps(99)
    pred = AWD.predict(S3, ps, fit, games_left={"BOS": 0, "TOR": 0, "EDM": 0, "COL": 0}, n=2000)
    hart = pred["hart"]["probs"]
    assert sum(hart.values()) == pytest.approx(1.0)
    best = ps[ps["pos"] != "G"].sort_values("pts").iloc[-1]["player"]
    assert max(hart, key=hart.get) == best
    # Ross at season end is deterministic: the points leader
    ross = pred["ross"]["probs"]
    assert ross[best] == pytest.approx(1.0)
    # mid-season the leader is uncertain but the favourite
    ps2 = ps.assign(gp=40, g=ps["g"] * 40 / 82, a=ps["a"] * 40 / 82, pts=ps["pts"] * 40 / 82, team_gp=40)
    r2 = AWD.leader_sim(ps2, {"BOS": 42, "TOR": 42, "EDM": 42, "COL": 42}, "pts", n=4000)
    assert 0.2 < r2[best] < 1.0 and sum(r2.values()) == pytest.approx(1.0)
    cm = AWD.compare_markets(pred, {"awards": {"hart": {"available": True, "probs": {f"name:{ps.set_index('player').loc[best, 'name']}": 0.4},
                                                        "mid": {}}}})
    assert cm["hart"]["rows"][0]["player"] == best and cm["hart"]["rows"][0]["market"] == 0.4


# ── backtest ─────────────────────────────────────────────────────────────────

def test_backtest_on_synthetic(lg, rink_roots):
    wf = GM.walk_forward([S2, S3], games=lg["games"], tg_of=SC.tg_getter(lg))
    out = BT.backtest(seasons=[S2, S3], wf=wf, season_sims=0, games=lg["games"], write=True)
    m = out["metrics"]
    for k in ("model", "elo", "xg_baseline", "market"):
        assert m[k]["n"] == 2 * 1344
    assert m["model"]["logloss"] < math.log(2)
    assert m["market"]["logloss"] <= m["elo"]["logloss"] + 0.01          # the planted-truth market is sharp
    assert out["ot"]["n"] > 0 and out["puck_line_home"]["n"] > 0 and out["totals_model"]["n"] > 0
    assert len(out["metrics"]["model"]["reliability"]) >= 5
    cal = json.loads((rink_roots["data"] / "calibration.json").read_text())
    assert cal["game_model"]["metrics"]["model"]["n"] == 2 * 1344
    rows = BT.summary_table(out)
    assert {r["model"] for r in rows} >= {"model", "elo", "xg_baseline", "market"}


def test_write_calibration_keeps_season_odds_on_games_only_refresh(rink_roots):
    path = rink_roots["data"] / "calibration.json"
    BT.write_calibration({"generated_at": "t1", "metrics": {}, "season_sim": {"n_sims": 7}})
    BT.write_calibration({"generated_at": "t2", "metrics": {"model": {"n": 1}}})
    cal = json.loads(path.read_text())
    assert cal["season_sim"] == {"n_sims": 7} and cal["game_model"]["generated_at"] == "t2"


def test_elo_basics():
    g = pd.DataFrame([{"game_id": str(i), "season": S3, "date": pd.Timestamp("2026-10-01") + pd.Timedelta(days=i), "gtype": "REG",
                       "home": "BOS", "away": "TOR", "played": True, "margin": 2.0, "so": False, "neutral": False} for i in range(10)])
    e = BT.elo_history(g)
    assert e.iloc[0] == pytest.approx(1 / (1 + 10 ** (-50 / 400)))
    assert e.iloc[-1] > e.iloc[0]


# ── markets ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def fx():
    return json.loads(FIX.read_text(encoding="utf-8"))


def test_map_team():
    teams = M.teams_info(S3)
    assert M.map_team(None, teams, "LA") == "LAK" and M.map_team(None, teams, "SJ") == "SJS"
    assert M.map_team(None, teams, "NJ") == "NJD" and M.map_team(None, teams, "TB") == "TBL"
    assert M.map_team("Montréal Canadiens", teams) == "MTL" and M.map_team("Montreal Canadiens", teams) == "MTL"
    assert M.map_team("Utah", teams) == "UTA" and M.map_team("Blue Jackets", teams) == "CBJ"
    assert M.map_team("LA Kings (2026-27)", teams) == "LAK" and M.map_team("Golden Knights", teams) == "VGK"
    assert M.map_team(None, teams, "LAS") == "VGK" and M.map_team(None, teams, "MON") == "MTL"
    assert M._codes_pair("FLALA", teams) == ("FLA", "LAK") and M._codes_pair("LASJ", teams) == ("LAK", "SJS")


def test_futures_parsing(fx):
    f = M.futures(S3, kalshi=fx["kalshi"], poly=fx["poly_futures"])
    ch = f["champion"]
    assert ch["available"] and ch["field"] == 32 and set(ch["sources"]) == {"kalshi", "polymarket"}
    assert sum(ch["probs"].values()) == pytest.approx(1.0, abs=1e-3) and not ch["unmatched"]
    for c in ("Eastern", "Western"):
        v = f["conference"][c]
        assert v["available"] and v["field"] == 16 and sum(v["probs"].values()) == pytest.approx(1.0, abs=1e-3)
    for d in M.DIVISIONS:
        assert f["division"][d]["available"] and f["division"][d]["field"] == 8
    assert f["presidents"]["available"]
    pl = f["playoffs"]
    assert pl["available"] and len(pl["probs"]) >= 28 and all(0 < p < 1 for p in pl["probs"].values())
    pts = f["points"]
    assert len(pts) == 32
    lad = pts["ANA"]["kalshi"]["ladder"]
    ks = sorted(lad)
    assert all(lad[a] >= lad[b] for a, b in zip(ks, ks[1:])) and pts["ANA"]["kalshi"]["ticker"] == "KXNHLSEASONPTS-27ANA"
    assert "polymarket" in pts["ANA"] and 80 in pts["ANA"]["polymarket"]["ladder"]
    # preseason award fields are too thin to de-vig: reported, not published
    hart = f["awards"]["hart"]
    assert hart["available"] is False and "implied total" in hart["reason"] and hart["mid"]
    assert set(f["advance"]) >= {"r2_east", "r2_west", "cf_east", "cf_west"}


def test_game_prices_parsing(fx):
    teams = M.teams_info(S3)
    gl = []
    for i, g in enumerate(fx["store_games"]):
        a, h = M._codes_pair(g["code"][7:], teams)
        gl.append({"game_id": str(i), "home": h, "away": a, "date": g["date"], "lines": None})
    gp = M.game_prices(S3, games=gl, kalshi=fx["kalshi"], poly=fx["poly_games"])
    assert len(gp) == 6
    r = gp["0"]                                   # BUF / CBJ, Oct 1
    assert {s["source"] for s in r["sources"]} == {"kalshi", "polymarket"} and r["basis"] == "prediction_markets"
    assert 0.4 < r["p_home"] < 0.6
    assert set(r["spread"]["kalshi"]) == {"home", "away"} and 1.5 in r["spread"]["kalshi"]["home"]
    tot = r["total"]["kalshi"]
    ks = sorted(tot)
    assert all(tot[a] >= tot[b] for a, b in zip(ks, ks[1:])) and 5.5 in r["total"]["polymarket"]
    assert 0.1 < r["ot"]["kalshi"] < 0.4
    # the two sources agree within a few points on every game
    for v in gp.values():
        ps = [s["p_home"] for s in v["sources"]]
        assert max(ps) - min(ps) < 0.06


def test_compare_titles():
    rows = M.compare_titles({"BOS": 0.1, "TOR": 0.05}, {"available": True, "probs": {"BOS": 0.08, "EDM": 0.2}})
    d = {r["id"]: r for r in rows}
    assert d["BOS"]["edge"] == pytest.approx(0.25) and d["EDM"]["model"] is None


def test_season_conventions_agree():
    """One season-id convention (a 4-digit year is the START year) and one turnover date (1 July) everywhere."""
    from datetime import date

    from oddsmarkets.nhl import analytics as AN
    from oddsmarkets.nhl import canon
    from oddsmarkets.nhl.models import _io
    for v in (2025, "2025", "2025-26", 20252026, "20252026"):
        assert _io.sid(v) == canon.norm_season(v) == 20252026
    assert D.sid(2025) == 20252026
    for d, want in ((date(2026, 6, 30), 20252026), (date(2026, 7, 1), 20262027), (date(2026, 8, 15), 20262027),
                    (date(2027, 1, 10), 20262027)):
        assert canon.current_season(d) == D.season_of_date(d) == M.season_for(d) == AN.current_season(d) == want
