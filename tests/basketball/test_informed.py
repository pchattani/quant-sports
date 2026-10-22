"""The market-informed game model (models/informed.py): market ratings, availability, fallbacks, predict (synthetic
data, no network)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pytest
from scipy.stats import norm

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import game as GM
from oddsmarkets.basketball.models import informed as INF
from oddsmarkets.basketball.models import ratings as R
from oddsmarkets.basketball.models.synthetic import make_store

FIT = {"version": INF.VERSION,
       "spread": {"const": 0.4, "mk_mu": 0.65, "rating": 0.4, "x_av": 0.9, "b2b": -1.4, "rest": 0.1,
                  "travel_1000km": 0.0, "tz": 0.0, "altitude": 0.4, "hca": 0.25},
       "cal_c0": -0.25, "cal_sd": 11.5,
       "total": {"const": 40.0, "mk_tot": 0.46, "base_total": 0.6, "x_tot_av": 0.9, "x_b2b_sum": -0.3,
                 "x_rest_sum": 0.15, "x_early": -0.9, "x_post": -6.4, "x_alt_tot": 0.3, "lg_pace": -0.2,
                 "lg_ortg": -0.3}}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDWOOD_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("HARDWOOD_DATA", str(tmp_path / "data"))
    GM.set_params("nba", None)
    yield
    GM.set_params("nba", None)
    INF.set_fitted("nba", None)
    INF.set_fitted("wnba", None)


def test_committed_fit_is_nba_only():
    assert INF.INFORMED_LEAGUES == ("nba",)
    f = INF.fitted("nba")
    assert f and f["version"] == INF.VERSION and f["cal_sd"] > 5
    assert set(f["spread"]) == {"const", *INF.SPREAD_FEATS}
    assert set(f["total"]) == {"const", *INF.TOTAL_FEATS}
    assert INF.enabled("nba") and not INF.enabled("wnba")
    # the walk-forward path never uses the season it scores: one entry per season, each fitted on fewer games
    wf = f["wf"]
    ns = [wf[s]["n_spread"] for s in sorted(wf)]
    assert ns == sorted(ns) and ns[-1] < f["n_spread"]


def test_market_ratings_recover_the_lines_and_never_see_the_day_itself():
    st, truth = make_store("nba", 2027, seed=3, played_frac=0.6, odds_noise=0.5)
    rows = G.finished(st["games"], "nba")
    days = sorted({r["day"] for r in rows})
    mk = INF.market_path("nba", 2027, st, days=days)
    late = days[-1]
    m = mk[late]
    true_net = {t: v["net"] for t, v in truth["teams"].items()}
    a = np.array([m["r"][t] for t in sorted(true_net)])
    b = np.array([true_net[t] for t in sorted(true_net)]) * 0.99
    assert np.corrcoef(a, b)[0, 1] > 0.95
    assert m["h"] == pytest.approx(3.0 * 0.99, abs=0.8)
    # lines of day D itself are not used for day D
    d = days[len(days) // 2]
    used = sum(1 for r in rows if r["day"] < d)
    assert mk[d]["n"] == used and mk[d]["n_games"] == used
    # a wild line on day d changes nothing on day d, only after it
    g = next(g for g in st["games"].values() if G.local_day(g) == d and g["status"] == "post")
    g["odds"]["spread_home"] = -29.0
    mk2 = INF.market_path("nba", 2027, st, days=[d, d + timedelta(days=1)])
    assert mk2[d]["r"] == pytest.approx(mk[d]["r"])
    nxt = min(x for x in days if x > d)
    mk3 = INF.market_path("nba", 2027, st, days=[nxt])
    assert mk3[nxt]["r"][g["home"]] != pytest.approx(mk[nxt]["r"][g["home"]])


def _game(gid, d, home, away, hp, ap, dnp_h=(), dnp_a=()):
    return {"id": gid, "date": f"{d.isoformat()}T23:30Z", "status": "post", "stype": "reg", "neutral": False,
            "home": home, "away": away, "hs": 100, "as": 95, "periods": 4,
            "odds": {"spread_home": -3.0, "total": 200.0},
            "box": {home: {"players": [[p, 1, 1440] for p in hp], "dnp": [[p, "Injury"] for p in dnp_h],
                           "team": {"fga": 85, "oreb": 10, "tov": 13, "fta": 20}},
                    away: {"players": [[p, 1, 1440] for p in ap], "dnp": [[p, "Injury"] for p in dnp_a],
                           "team": {"fga": 85, "oreb": 10, "tov": 13, "fta": 20}}}}


def test_availability_falls_when_a_good_player_misses_games_and_outs_apply_only_to_upcoming():
    d0 = date(2026, 11, 1)
    A = ["a1", "a2", "a3", "a4", "a5"]
    B = ["b1", "b2", "b3", "b4", "b5"]
    vals = {**{p: [6.0, 3.0, -3.0, 2000] for p in A}, **{p: [0.0, 0.0, 0.0, 2000] for p in B}, "a6": [-2.0, -1.0, -1.0, 500]}
    games = {"1": _game("1", d0, "1", "2", A, B)}
    games["2"] = _game("2", d0 + timedelta(days=2), "2", "1", B, ["a2", "a3", "a4", "a5", "a6"], dnp_a=["a1"])
    games["3"] = {**_game("3", d0 + timedelta(days=4), "1", "2", A, B), "status": "pre", "hs": None, "as": None, "box": {}}
    store = {"games": games, "teams": {"1": {"abbr": "AAA"}, "2": {"abbr": "BBB"}}}
    si = INF.season_inputs("nba", 2027, store=store, prior={}, vals=vals)
    day2, day3 = (d0 + timedelta(days=2)).isoformat(), (d0 + timedelta(days=4)).isoformat()
    av2, av3 = si["days"][day2]["av"]["1"][0], si["days"][day3]["av"]["1"][0]
    assert av3 < av2                       # a1 missed the last game: P(plays) 0.62 instead of 0.94
    inp = INF.inputs_for_game(si, d0 + timedelta(days=4), "1", "2")
    out = INF.inputs_for_game(si, d0 + timedelta(days=4), "1", "2", out={"1": {"a1"}}, upcoming=True)
    assert out["av_h"] < inp["av_h"]
    same = INF.inputs_for_game(si, d0 + timedelta(days=4), "1", "2", out={"1": {"a1"}}, upcoming=False)
    assert same["av_h"] == pytest.approx(inp["av_h"])
    # a P(plays) override (pre-game market listing) moves the expected rotation; Out still wins over it
    rot = si["live"]
    base_s = rot.expected("1")[0]
    assert rot.expected("1", p_over={"a1": 0.97})[0] > base_s                  # listed: back to near-certain
    assert rot.expected("1", p_over={"a1": 0.0})[0] < base_s
    assert rot.expected("1", out={"a1"}, p_over={"a1": 0.97})[0] == pytest.approx(rot.expected("1", out={"a1"})[0])


def test_fallbacks_no_lines_and_thin_lines():
    st, _ = make_store("nba", 2027, seed=4, played_frac=0.5)
    for g in st["games"].values():
        g["odds"] = None
    si = INF.season_inputs("nba", 2027, store=st, prior={}, vals={})
    rows = G.finished(st["games"], "nba")
    r = rows[-1]
    assert INF.inputs_for_game(si, r["day"], r["home"], r["away"]) is None          # no line, no prior
    si2 = INF.season_inputs("nba", 2027, store=st, prior={"r": {r["home"]: 2.0}}, vals={})
    early = rows[0]
    assert INF.inputs_for_game(si2, early["day"], early["home"], early["away"]) is not None   # prior only, early
    assert INF.inputs_for_game(si2, r["day"], r["home"], r["away"]) is None         # 50+ games, no lines


def test_predict_uses_the_informed_terms_and_the_parts_sum_to_the_margin():
    rt = {"teams": {"1": {"off": 118, "def": 112, "net": 6, "pace": 100, "games": 30},
                    "2": {"off": 114, "def": 116, "net": -2, "pace": 98, "games": 30}}, "league_ortg": 115, "league_pace": 99}
    INF.set_fitted("nba", FIT)
    inp = {"mk_h": 2.4, "mk_r_h": 3.0, "mk_r_a": -1.0, "mk_tot": 228.0, "av_h": -1.5, "av_a": 0.5, "tav_h": -1.0,
           "tav_a": 0.0, "n_lines": 300, "n_games": 300}
    base = GM.predict("1", "2", "2026-01-10", {"league": "nba", "ratings": rt})
    r = GM.predict("1", "2", "2026-01-10", {"league": "nba", "ratings": rt, "informed": inp})
    assert base["model"] == "base" and r["model"] == "informed"
    k = 99 / 100.0
    mu = (FIT["spread"]["const"] + FIT["spread"]["mk_mu"] * (2.4 + 3.0 + 1.0) + FIT["spread"]["rating"] * 8 * k
          + FIT["spread"]["x_av"] * (-2.0) * k + FIT["spread"]["hca"] + FIT["cal_c0"])
    assert r["margin"] == pytest.approx(mu, abs=1e-6)
    assert r["p_home"] == pytest.approx(norm.cdf(mu / 11.5))
    parts = ("rating", "hca", "rest", "b2b", "travel", "tz", "altitude", "injury")
    assert sum(r["detail"][p] for p in parts) == pytest.approx(r["margin"], abs=1e-9)
    assert r["pts_home"] + r["pts_away"] == pytest.approx(r["total"])
    assert r["base"]["p_home"] == pytest.approx(base["p_home"])
    # the availability term split by team (points of home margin) sums to the term
    assert r["detail"]["injury_home"] + r["detail"]["injury_away"] == pytest.approx(r["detail"]["injury"], abs=1e-9)
    assert r["detail"]["injury_home"] == pytest.approx(FIT["spread"]["x_av"] * -1.5 * k)
    # WNBA: not enabled, the informed inputs are ignored
    w = GM.predict("1", "2", "2026-06-10", {"league": "wnba", "ratings": rt, "informed": inp})
    assert w["model"] == "base"
