"""The Quant Scrum: parsers on saved ESPN answers, the rating maths, the World Rugby replica against the published
formula and values, the competition rules (bonus points, tie-breakers, the 2027 World Cup draw), and the follow cards.

The ESPN fixtures (tests/scrum/fixtures) stay out of the public build (scripts/export_public.py, D5): the tests that
read them skip there."""
from __future__ import annotations

import gzip
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from oddsmarkets.rugby import comps, models, nations, rankings, validate
from oddsmarkets.rugby.ratings import Model, Params, wdl
from oddsmarkets.rugby.sources import espn

FIX = Path(__file__).parent / "fixtures"


def _fx(name):
    p = FIX / name
    if not p.exists():
        pytest.skip(f"fixture {name} not in this checkout")
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


# ── parsers ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_scoreboard_event_parses_score_halves_stats_and_moments():
    sb = _fx("scoreboard_six_2025.json.gz")
    rows = espn.parse_scoreboard(sb, "180659")
    assert len(rows) == 1
    r = rows[0]
    assert r["comp"] == "six" and r["status"] == "final" and r["home"]["name"] == "France" and r["away"]["name"] == "Wales"
    assert (r["hs"], r["as"]) == (43, 0) and r["hh"] == [28, 15] and r["ah"] == [0, 0]
    assert r["hstat"]["tries"] == 7 and r["hstat"]["metres"] == 431 and 0 < r["hstat"]["poss"] < 1
    assert r["astat"]["rc"] == 0 and r["hstat"]["rc"] == 1
    tries = [e for e in r["events"] if e[1] == "try"]
    assert len(tries) == 7 and all(e[2] == "h" for e in tries)
    assert r["events"][-1][5] == 43            # the running score counted from the events ends on the final score


def test_summary_gives_the_matchday_23_and_bios():
    sm = espn.parse_summary(_fx("summary_600250.json.gz"))
    h, a = sm["lineups"]["h"], sm["lineups"]["a"]
    assert len(h) == 23 and len(a) == 23
    assert sum(r[3] for r in h) == 15                                # starters are jerseys 1-15
    ramos = next(r for r in h if r[0] == "238367")
    assert ramos[1] == 15 and ramos[2] == "FB" and ramos[5]["con"] == 4 and ramos[5]["pts"] == 8
    assert sm["athletes"]["238367"]["dob"] == "1995-07-23"
    assert sm["events"][2][1] == "try" and sm["events"][2][5:] == [5, 0]   # the header's own running score


# ── rating maths (golden) ────────────────────────────────────────────────────────────────────────────────────

def _m(h, a, hs=None, as_=None, neutral=False, date="2025-02-01T15:00Z"):
    m = {"id": f"{h}-{a}-{date}", "home": {"id": h, "name": h}, "away": {"id": a, "name": a}, "date": date,
         "neutral": neutral, "venue": {}, "status": "final" if hs is not None else "pre"}
    if hs is not None:
        m["hs"], m["as"] = hs, as_
    return m


def test_wdl_is_symmetric_and_draws_are_rare():
    pw, pd, pl = wdl(0.0, Params(s0=12.0, s1=0.0))
    assert abs(pw - pl) < 1e-12 and abs(pw + pd + pl - 1) < 1e-12
    assert abs(pd - (math.erf(0.5 / (12 * math.sqrt(2))))) < 1e-9     # P(|N(0, 12)| < 0.5)
    pw2, _pd2, pl2 = wdl(10.0, Params(s0=12.0, s1=0.0))
    assert pw2 > 0.75 and pl2 < 0.25


def test_home_advantage_and_neutral_ground():
    p = Params(H=5.0, split=False, c_km=0, c_tz=0, c_rest=0)
    mdl = Model(p)
    e_home = mdl.expect(_m("England", "France"))
    e_neut = mdl.expect(_m("England", "France", neutral=True))
    assert abs(e_home["margin"] - e_neut["margin"] - 5.0) < 1e-9
    assert abs(e_neut["margin"]) < 1e-9                                 # same tier, same prior, neutral: level


def test_update_moves_by_the_learning_rate_and_caps_the_error():
    p = Params(H=0.0, k=0.1, k_new=0.1, cap=20.0, split=False, c_km=0, c_tz=0, c_rest=0, k_mu=0.0)
    mdl = Model(p)
    m = _m("England", "France", 30, 10, neutral=True)
    e = mdl.expect(m)
    mdl.update(m, e)
    assert abs(mdl.rating("England") - (8.0 + 0.1 * 20)) < 1e-9          # tier-1 prior 8, error 20 (exactly the cap)
    assert abs(mdl.rating("France") - (8.0 - 0.1 * 20)) < 1e-9
    mdl2 = Model(p)
    m2 = _m("England", "France", 80, 0, neutral=True)
    mdl2.update(m2)
    assert abs(mdl2.rating("England") - (8.0 + 0.1 * 20)) < 1e-9         # an 80-point win teaches no more than 20


def test_walk_forward_never_sees_the_match_it_forecasts():
    ms = [_m("England", "France", 30, 10, date="2025-02-01T15:00Z"), _m("England", "France", 30, 10, date="2025-03-01T15:00Z")]
    rows = models.walk(ms, Params(split=False), keep_from=2000)
    assert rows[0]["margin"] == pytest.approx(Params().H)                # before any result: priors equal, home advantage only
    assert rows[1]["margin"] > rows[0]["margin"]                         # the second forecast has learned from the first


def test_travel_counts_distance_and_time_zones():
    km, tz = nations.travel("New Zealand", (51.46, -0.34, 0))
    assert 18000 < km < 18500 and tz == 12
    assert nations.travel("England", (51.46, -0.34, 0)) == (0.0, 0)


# ── the World Rugby replica (the published formula) ─────────────────────────────────────────────────────────

def test_points_exchange_matches_the_published_formula():
    # home side A on 80 v B on 76 before July 2026: the gap with the 3-point allowance is 7
    assert rankings.exchange(80, 76, 5, "a", "2025-06-01") == pytest.approx(0.3)
    assert rankings.exchange(80, 76, 20, "a", "2025-06-01") == pytest.approx(0.45)                  # by 16+: x1.5
    assert rankings.exchange(80, 76, 20, "a", "2025-06-01", world_cup=True) == pytest.approx(0.9)    # World Cup: x2
    assert rankings.exchange(80, 76, -5, "a", "2025-06-01") == pytest.approx(-1.7)
    assert rankings.exchange(80, 76, 0, "a", "2025-06-01") == pytest.approx(-0.7)                   # a draw: the favourite pays
    # no home allowance from 1 July 2026
    assert rankings.exchange(80, 76, 5, "a", "2026-07-04") == pytest.approx(0.6)
    # a favourite beating an outsider 10+ below: no transfer; an outsider winning: the cap of 2
    assert rankings.exchange(90, 75, 5, None, "2026-08-01") == 0.0
    assert rankings.exchange(75, 90, 5, None, "2026-08-01") == pytest.approx(2.0)
    assert rankings.exchange(75, 90, 30, None, "2026-08-01", world_cup=True) == pytest.approx(6.0)  # the WC cap of 6


def test_exchange_is_zero_sum_in_the_ranker():
    rk = rankings.Ranker(seed={"a": 80.0, "b": 76.0})
    x = rk.update("a", "b", 5, 12, "2025-06-01")
    assert rk.points["a"] + rk.points["b"] == pytest.approx(156.0) and x == pytest.approx(-1.7)
    wi = rankings.what_if(80, 76, "a", "2025-06-01")
    assert [b["a"] for b in wi] == [0.45, 0.3, -0.7, -1.7, -2.55]


def test_published_values_are_ordered_and_the_anchor_rolls_forward():
    pts = [v for _n, v in validate.PUBLISHED_2026_09_28]
    assert len(pts) == 30 and pts == sorted(pts, reverse=True)
    assert validate.PUBLISHED_2026_09_28[0] == ("South Africa", 93.09)
    ranks = sorted(validate.RANKS_2025_12_01.values())
    assert len(ranks) == 24 and 21 not in ranks                                            # Belgium (21st) did not qualify
    # rolled forward from the anchor: a home Ireland win by 5 over Argentina after July 2026 (no allowance)
    rk = rankings.Ranker(seed={"IRE": 88.08, "ARG": 82.24})
    x = rk.update("IRE", "ARG", 25, 20, "2026-11-06")
    assert x == pytest.approx(1 - (88.08 - 82.24) / 10) and rk.points["IRE"] == pytest.approx(88.08 + x)


def test_replica_check_measures_against_the_published_table():
    ms = [_m("South Africa", "New Zealand", 30, 10, date="2026-09-01T15:00Z")]
    rk, _ = models.replica(ms)
    chk = validate.replica_check(rk, ms)
    assert chk["sep2026"]["n"] == 2 and chk["sep2026"]["mae"] >= 0


# ── competition rules ──────────────────────────────────────────────────────────────────────────────────────

def test_bonus_points_and_the_grand_slam():
    assert comps.match_points(30, 10, 4) == (5, 1, 0)        # a win with four tries
    assert comps.match_points(20, 27, 4) == (2, 1, 1)        # lost by seven with four tries: both bonus points
    assert comps.match_points(20, 28, 2) == (0, 0, 0)        # lost by eight: none
    assert comps.match_points(20, 20, 1) == (2, 0, 0)
    teams = ["A", "B", "C", "D", "E", "F"]
    res = [{"home": a, "away": b, "hs": 20, "as": 10, "ht": 2, "at": 1} for a, b in itertools.combinations(teams, 2)]
    t = comps.table(res, teams, grand_slam=True)
    assert t[0]["team"] == "A" and t[0]["w"] == 5 and t[0]["gs"] == 3 and t[0]["pts"] == 23
    assert t[-1]["team"] == "F" and t[-1]["pts"] == 0


def test_six_nations_tiebreak_points_difference_then_tries():
    res = [{"home": "A", "away": "B", "hs": 30, "as": 10, "ht": 3, "at": 1},
           {"home": "B", "away": "A", "hs": 25, "as": 20, "ht": 4, "at": 2}]
    t = comps.table(res, ["A", "B"])
    assert [x["team"] for x in t] == ["A", "B"] and t[0]["pts"] == t[1]["pts"] == 5   # level on points: A on difference
    res2 = [{"home": "A", "away": "B", "hs": 20, "as": 20, "ht": 3, "at": 2}]
    assert [x["team"] for x in comps.table(res2, ["A", "B"])] == ["A", "B"]           # level on difference: tries


def test_world_cup_pool_tiebreak_head_to_head_first():
    res = [{"home": "A", "away": "B", "hs": 10, "as": 12, "ht": 1, "at": 1},
           {"home": "A", "away": "C", "hs": 50, "as": 0, "ht": 8, "at": 0},
           {"home": "B", "away": "C", "hs": 22, "as": 24, "ht": 4, "at": 2}]
    t = comps.table(res, ["A", "B", "C"], tiebreak="rwc")
    a, b = next(x for x in t if x["team"] == "A"), next(x for x in t if x["team"] == "B")
    assert a["pts"] == b["pts"] == 6 and a["pd"] > b["pd"]
    assert [x["team"] for x in t][:2] == ["B", "A"]                                    # B beat A: head to head wins


def test_world_cup_2027_draw_and_bracket():
    allt = [t for ts in comps.RWC27_POOLS.values() for t in ts]
    assert len(allt) == 24 and len(set(allt)) == 24 and "Australia" in comps.RWC27_POOLS["A"]
    assert len(comps.RWC27_THIRDS) == 15
    for q, perm in comps.RWC27_THIRDS.items():
        assert sorted(perm) == sorted(q)                                               # the four thirds, each once
        for winner, third in zip("ABCD", perm):
            assert winner != third                                                     # never your own pool's third
    seats = sorted(x for pr in comps.RWC27_R16.values() for x in pr if not x.startswith("3:"))
    assert seats == sorted([f"1{p}" for p in "ABCDEF"] + [f"2{p}" for p in "ABCDEF"])


def test_simulators_run_and_sum_to_one():
    mdl = Model(Params(split=True))
    teams = comps.NC_NORTH
    ids = {t: t for t in teams}
    sim = comps.ScoreSim(12.0, 0.1)
    out = comps.simulate_league(mdl, sim, teams, ids, [], [(d, h, a) for d, h, a in comps.SIX27], n=400, grand_slam=True, triple_crown=True)
    assert abs(sum(r["title"] for r in out["teams"]) - 1) < 1e-9
    assert all(abs(sum(r["pos"]) - 1) < 1e-6 for r in out["teams"])
    ids = {t: t for ts in comps.RWC27_POOLS.values() for t in ts}
    rw = comps.simulate_rwc27(mdl, comps.ScoreSim(12.0, 0.1), ids, [], {}, n=200)
    assert abs(sum(r["champion"] for r in rw["teams"]) - 1) < 1e-9
    assert abs(sum(r["r16"] for r in rw["teams"]) - 16) < 1e-6


def test_score_sim_tries_follow_the_points():
    sim = comps.ScoreSim(12.0, 0.1, t0=0.0, t1=0.13)
    for _ in range(500):
        h, a, ht, at = sim.draw(28.0, 18.0)
        assert ht * 5 <= h and at * 5 <= a and h != 1 and a != 1


# ── follow cards ──────────────────────────────────────────────────────────────────────────────────────────

def test_follow_cards_one_per_team_under_8kb(tmp_path, monkeypatch):
    if not (FIX / "stores" / "men").exists():
        pytest.skip("fixture stores not in this checkout")
    import shutil
    shutil.copytree(FIX / "stores", tmp_path / "stores")                  # the build writes the forecast log there
    monkeypatch.setenv("RUGBY_STORES", str(tmp_path / "stores"))
    monkeypatch.setenv("SCRUM_NOW", "2026-11-02T12:00:00Z")
    from oddsmarkets.rugby import follow_build, pages
    res = pages.build_scope("men", tmp_path / "data", sims=200, game_pages=False)
    assert res["ok"]
    out = follow_build.build(res, tmp_path / "data")
    teams = {k: v for k, v in res["info"]["teams"].items() if v.get("active")}
    assert out["n"] == len(teams) and out["max"] <= 8192
    files = sorted(p.stem for p in (tmp_path / "data" / "follow" / "men").glob("*.json"))
    assert files == sorted(teams)
    card = json.loads((tmp_path / "data" / "follow" / "men" / f"{files[0]}.json").read_text(encoding="utf-8"))
    assert card["k"] == f"scrum:men:{files[0]}" and card["sport"] == "rugby" and card["team"]["href"].startswith("#/men/team/")
    fx = json.loads((tmp_path / "data" / "men" / "fixtures.json").read_text(encoding="utf-8"))
    assert all(c["date"] >= "2026-11-02" for c in fx["upcoming"])          # nothing past the clock is "upcoming"
