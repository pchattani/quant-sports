"""Draft-pick values (analytics/picks.py) and their use in the trade ratings (analytics/moves.py). Synthetic inputs only."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.basketball.analytics import bio as BIO
from oddsmarkets.basketball.analytics import moves as MV
from oddsmarkets.basketball.analytics import picks as PK
from oddsmarkets.basketball.analytics import value as V

PRM = V.params_for("nba", pace=100.0, ppw=31.0)
FIT = {"aging": [[a, 0.0] for a in range(19, 42)], "spread": {"s1": 1.5, "tau": 1.0}, "surv": [2.5, -0.1, -0.05, 0.3, 0.5],
       "avail": 0.8, "min_cv": 0.25}
TEAMS = MV.TeamIndex({"BOS": {"name": "Boston Celtics", "location": "Boston", "abbr": "BOS"},
                      "CHI": {"name": "Chicago Bulls", "location": "Chicago", "abbr": "CHI"},
                      "PHX": {"name": "Phoenix Suns", "location": "Phoenix", "abbr": "PHX"},
                      "DEN": {"name": "Denver Nuggets", "location": "Denver", "abbr": "DEN"},
                      "OKC": {"name": "Oklahoma City Thunder", "location": "Oklahoma City", "abbr": "OKC"}})


def _pts(n_drafts=20, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for y in range(2000, 2000 + n_drafts):
        for o in range(1, 61):
            mu = 14.0 / o ** 0.6
            out.append((y, o, 1 if o <= 30 else 2, float(max(0.0, mu * rng.lognormal(0, 0.6) - (0 if rng.random() > 0.2 else mu)))))
    return out


# ---------------------------------------------------------------------------------------------- curve

def test_kernel_curve_is_non_increasing_and_tracks_the_shape():
    c = PK.fit_curve(_pts(), "nba", boot=40)
    v = c["v"]
    assert c["ok"] and len(v) == 60 and all(a >= b - 1e-9 for a, b in zip(v, v[1:]))
    assert v[0] > 3 * v[29] > 0 and c["rounds"]["1"] > c["rounds"]["2"]
    assert all(lo <= x + 1e-9 and x <= hi + 1e-9 for lo, x, hi in zip(c["lo"], v, c["hi"]))
    assert all(a <= b <= d for a, b, d in zip(c["q10"], c["q50"], c["q90"]))


def test_validation_reports_dev_and_sealed_test_for_the_nba():
    val = PK.validate(_pts(27), "nba", boot=50)
    assert val["ok"] and "kernel" in val["dev_lodo"]["mse"]
    t = val["test"]
    assert t["drafts"][0] == 2011 and t["train_lag"] == 5
    assert t["metrics"]["kernel"]["mse"] < t["metrics"]["flat"]["mse"]
    assert len(t["mse_kernel_minus_round"]["ci95"]) == 2


def test_history_matches_list_entries_by_name_when_ids_differ(monkeypatch):
    # the old curve's bug: the draft list's athlete ids are not the league's; the name finds the player
    monkeypatch.setattr(BIO, "players", lambda lg: {"100": {"draft": [2010, 1, 1, "BOS"]}})
    monkeypatch.setattr(BIO, "drafts", lambda lg: {2010: [[1, 1, 1, "BOS", "x1", "First Pick", False],
                                                          [2, 1, 2, "CHI", "x2", "Second Pick", True],
                                                          [3, 1, 3, "PHX", "x3", "Never Played", False]]})
    war_by = {s: {"100": 5.0, "200": 2.0} for s in range(2011, 2016)}
    rows_by = {s: {"100": {"name": "First Pick"}, "200": {"name": "Second Pick"}} for s in range(2011, 2016)}
    h = PK.history("nba", war_by, rows_by)[2010]
    assert h["slots"] == {1: "100", 2: "200"} and h["traded"][2] and h["team"][3] == "PHX"
    pts = PK.outcomes("nba", {2010: h}, war_by, 2015)
    v = {o: x for _y, o, _r, x in pts}
    assert v[1] == pytest.approx(5.0 * (1 + 0.9 + 0.81 + 0.729)) and v[3] == 0.0


def test_persistence_recovers_the_regression():
    rng = np.random.default_rng(2)
    wp = {}
    x = {f"t{i}": rng.normal(0.5, 0.15) for i in range(30)}
    for s in range(1990, 2030):
        wp[s] = dict(x)
        x = {t: 0.5 + 0.6 * (v - 0.5) + rng.normal(0, 0.12) for t, v in x.items()}
    p = PK.persistence(wp, range(1990, 2030))
    assert p["beta"][0] == pytest.approx(0.6, abs=0.08) and p["beta"][1] == pytest.approx(0.36, abs=0.1)
    assert p["beta"][-1] == 0.0


# ---------------------------------------------------------------------------------------------- traded picks

def _model(sim=None, season=2027):
    curve = PK.fit_curve(_pts(), "nba", boot=20)
    teams = [f"t{i:02d}" for i in range(30)]
    wp = {2026: {t: 0.2 + 0.6 * i / 29 for i, t in enumerate(teams)}}       # t00 worst, t29 best
    pers = {"beta": [0.6, 0.35, 0.14, 0, 0, 0, 0], "sd": [0.12, 0.14, 0.15, 0.15, 0.15, 0.15, 0.15]}
    return PK.PickModel("nba", season, curve, pers, wp, {2026}, sim=sim, members=teams), teams


def test_finished_season_uses_the_lottery_and_the_standings():
    pm, teams = _model()
    d = pm.dists(2026, "now")
    worst, best = d["t00"][1], d["t29"][1]
    assert worst[:4].sum() > 0.5 and worst[0] == pytest.approx(0.14)             # 2019 lottery table: 14% at No. 1
    assert best[29] == pytest.approx(1.0) and d["t29"][2][29] == pytest.approx(1.0)
    v_bad = pm.value("t00", 2026, 1, 2026)["v"]
    v_good = pm.value("t29", 2026, 1, 2026)["v"]
    assert v_bad > 2 * v_good > 0


def test_future_picks_regress_towards_the_average_and_are_discounted():
    pm, teams = _model()
    near = pm.value("t00", 2027, 1, 2027)
    far = pm.value("t00", 2031, 1, 2027)
    avg = np.mean([PK.curve_at(pm.curve, o) for o in range(1, 31)])
    assert near["v_undiscounted"] > far["v_undiscounted"]
    assert far["v_undiscounted"] == pytest.approx(avg, rel=0.15)
    assert far["v"] == pytest.approx(far["v_undiscounted"] * 0.9 ** (2032 - 2027))
    assert near["slot"][0] <= near["med"] <= near["slot"][1]


def test_protection_lowers_value_and_rolls_over():
    pm, teams = _model()
    un = pm.value("t00", 2027, 1, 2027)["v"]
    pr = pm.value("t00", 2027, 1, 2027, protect=4)
    assert 0 < pr["v"] < un and 0 < pr["p_convey"] < 1 and "rolls" in pr["note"]
    assert pm.value("t00", 2027, 1, 2027, conditional=True)["v"] == pytest.approx(0.5 * un)


def test_swap_rights_are_worth_more_against_a_worse_team():
    pm, teams = _model()
    vs_bad = pm.value("t00", 2027, 1, 2027, swap_with="t29")["v"]
    vs_good = pm.value("t28", 2027, 1, 2027, swap_with="t29")["v"]
    assert vs_bad > vs_good >= 0


def test_live_simulation_slot_distribution_is_used():
    p1 = [0.0] * 30
    p1[2] = 1.0
    sim = {"remaining_games": 50, "teams": {f"t{i:02d}": {"exp_w": 41.0, "current": {"w": 10, "l": 10, "remaining": 62},
                                                          "p_draft_pick": p1 if i == 5 else [1 / 30] * 30, "p_record_rank": [1 / 30] * 30}
                                            for i in range(30)}}
    pm, _ = _model(sim)
    r = pm.value("t05", 2027, 1, 2027)
    assert r["slot"] == [3, 3] and r["v"] == pytest.approx(PK.curve_at(pm.curve, 3) * 0.9)
    # "at the time" ignores the simulation: the standings of the last finished season
    assert pm.value("t05", 2027, 1, 2027, basis="time")["slot"] != [3, 3]


# ---------------------------------------------------------------------------------------------- parsing and ratings

def test_parse_protections_conditions_swaps_and_slots():
    p = MV.picks_in("for G X, an unprotected 2031 first-round draft pick and a 2030 pick swap")
    assert (p[0]["year"], p[0]["round"], p[0]["protect"], p[0]["swap"]) == (2031, 1, 0, False)
    assert (p[1]["year"], p[1]["swap"], p[1].get("round_stated")) == (2030, True, False)
    q = MV.picks_in("Acquired a 2030 conditional second-round draft pick from Charlotte")
    assert q[0]["cond"] and q[0]["round"] == 2 and q[0]["year"] == 2030
    r = MV.picks_in("for a 2027 first-round pick (top-10 protected) and a 2028 lottery-protected first-round pick")
    assert r[0]["protect"] == 10 and r[1]["protect"] == "lottery"
    s = MV.picks_in("Acquired Chicago's 2026 first-round pick in exchange for the 2025 No. 11 pick.")
    assert (s[0]["year"], s[0]["round"]) == (2026, 1) and (s[1]["year"], s[1]["overall"]) == (2025, 11)
    assert MV.picks_in("a 2027 third-round pick")[0]["round"] == 3


def test_parse_row_reads_the_original_owner():
    names = MV.NameIndex({})
    r = MV.parse_row({"date": "2025-02-03", "team": "PHX", "text": "Acquired a 2029 second-round draft pick, originally belonging to the "
                      "Phoenix Suns, from the Oklahoma City Thunder in exchange for a 2030 conditional second-round draft pick originally "
                      "belonging to the Denver Nuggets."}, names, TEAMS)
    s = r["sents"][0]
    assert s["picks_in"][0]["origin"] == "PHX" and s["picks_out"][0]["origin"] == "DEN" and s["picks_out"][0]["cond"]
    r2 = MV.parse_row({"date": "2025-04-08", "team": "BOS", "text": "Acquired Chicago's 2026 first-round pick from Phoenix in exchange for a 2027 "
                       "second-round pick."}, names, TEAMS)
    assert r2["sents"][0]["picks_in"][0]["origin"] == "CHI"


def test_draft_rights_slot_is_the_player_not_a_second_asset(monkeypatch):
    monkeypatch.setattr(BIO, "draft_slot", lambda lg, pid: [2025, 1, 10, "BOS"] if pid == "9" else None)
    monkeypatch.setattr(BIO, "dob", lambda lg, pid: None)
    monkeypatch.setattr(BIO, "drafts", lambda lg: {})
    pm, _ = _model(season=2026)
    box = pd.DataFrame([{"player_id": "8", "date": "2025-01-10", "team": "CHI", "sec": 1800, "team_poss": 100.0, "season": 2025}])
    rows_by = {2025: {"8": {"hpm": 1.0, "min": 2000, "gp": 70}}}
    deal = {"id": "x", "date": "2025-07-06", "teams": ["BOS", "CHI"], "rows": [], "zero": [], "players": {"9": ["CHI", "BOS"], "8": ["BOS", "CHI"]},
            "picks": [{"from": "CHI", "to": "BOS", "year": 2025, "round": None, "overall": 10, "n": 1, "swap": False},
                      {"from": "CHI", "to": "BOS", "year": 2027, "round": 2, "overall": None, "n": 1, "swap": False}]}
    ctx = {"rows": rows_by, "box": box, "games_left": {}, "valuation": {}, "names": {}, "current": 2026, "roster": {}, "slot_seasons": [],
           "draft_hist": {}}
    out = MV.rate_deals("nba", [deal], ctx, FIT, PRM, pm, date(2025, 10, 1))
    bos = [s for s in out[0]["sides"] if s["team"] == "BOS"][0]
    kinds = [x["kind"] for x in bos["in"]]
    assert kinds.count("pick") == 1 and bos["in"][[x["kind"] for x in bos["in"]].index("pick")]["round"] == 2
    rookie = [x for x in bos["in"] if x["kind"] == "player"][0]
    # no NBA minutes yet: the slot's curve value, discounted to his first season
    assert rookie["v_time"] == pytest.approx(PK.curve_at(pm.curve, 10) * 0.9 ** 0) and rookie["draft_slot"] == 10


def test_selection_finds_the_holders_pick():
    hist = {2026: {"listed": True, "slots": {5: "p5", 40: "p40", 41: "p41"}, "team": {5: "BOS", 40: "BOS", 41: "BOS"},
                   "round_of": {5: 1, 40: 2, 41: 2}, "traded": {5: False, 40: True, 41: False}}}
    assert MV.selection("nba", hist, 2026, 1, "BOS") == (5, "p5")
    assert MV.selection("nba", hist, 2026, 2, "BOS") == (40, "p40")
    assert MV.selection("nba", hist, 2026, 1, "CHI") is None and MV.selection("nba", hist, 2027, 1, "BOS") is None
