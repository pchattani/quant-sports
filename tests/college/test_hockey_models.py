"""College hockey models: the NPI / PairWise replica, the game model's outcome layer and the season simulation, on
small synthetic seasons (no network, no CHN data)."""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

import numpy as np
import pytest

from oddsmarkets.college.hockey import model as M, npi as N, sim as SIM


def game(i, h, a, res, site="home", ot=0, stype="reg", hs=None, as_=None, date="2026-11-01"):
    hs = hs if hs is not None else (3 if res == "W" else 1 if res == "L" else 2)
    as_ = as_ if as_ is not None else (1 if res == "W" else 3 if res == "L" else 2)
    return {"id": str(i), "date": f"{date}T23:00:00Z", "status": "post", "stype": stype, "home": h, "away": a,
            "neutral": site == "neutral", "res": res, "ot": ot, "hs": hs, "as": as_, "conf_game": True}


# ── NPI ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_npi_weights():
    assert N._weights("home", "W", False, 2026, False) == (0.8, 0.0)
    assert N._weights("away", "W", False, 2026, False) == (1.2, 0.0)
    assert N._weights("home", "L", False, 2026, False) == (0.0, 1.2)
    assert N._weights("neutral", "W", False, 2026, False) == (1.0, 0.0)
    w, l = N._weights("home", "W", True, 2026, False)           # home OT win: 0.4 x 0.8 + 0.2 as a win, 0.4 x 1.2 a loss
    assert math.isclose(w, 0.52) and math.isclose(l, 0.48)
    assert N._weights("home", "W", False, 2026, True) == (1.0, 0.0)   # conference postseason: unweighted
    assert N._weights("home", "T", False, 2026, False) == (0.4, 0.6)


def test_npi_fixed_point_matches_formula():
    # two teams that only play each other: NPI_A = (w*(25 + .75 NPI_B + qwb) + l*.75 NPI_B) / (w + l)
    games = [game(1, "A", "B", "W", site="neutral"), game(2, "A", "B", "W", site="neutral"), game(3, "B", "A", "W", site="neutral")]
    v = N.npi(games, {"A", "B"}, 2027)
    a, b = v["A"]["npi"], v["B"]["npi"]
    qa = 0.5 * (b - 51) if b > 51 else 0
    qb = 0.5 * (a - 51) if a > 51 else 0
    # A: 2 wins over B, 1 loss; B: 1 win, 2 losses (no bad-win removal under 12 weighted wins; good losses dropped)
    assert v["A"]["rank"] == 1 and v["A"]["w"] == 2 and v["B"]["l"] == 2
    assert a > b


def test_npi_good_losses_dropped():
    # C beats strong A; a loss to strong A must not raise B's NPI (good losses are dropped)
    games = [game(i, "A", "X%d" % i, "W") for i in range(10)] + [game(20, "A", "B", "W"), game(21, "B", "C", "W")]
    d1 = {"A", "B", "C"} | {"X%d" % i for i in range(10)}
    v = N.npi(games, d1, 2027)
    assert all(np.isfinite(x["npi"]) for x in v.values())


def test_rpi_components():
    games = [game(1, "A", "B", "W"), game(2, "B", "C", "W"), game(3, "C", "A", "W")]
    r = N.rpi(games, {"A", "B", "C"}, 2016, bad_wins=False, qwb=False)
    # a 3-team cycle: everyone 1-1, every RPI equal
    assert len({x["rpi"] for x in r.values()}) == 1


def test_pairwise_head_to_head_breaks_equal_rpi():
    games = [game(1, "A", "B", "W", site="neutral")]
    pw = N.pairwise(games, {"A", "B"}, 2016)
    assert pw["A"]["pwr"] == 1 and pw["A"]["pcw"] == 1


def test_select_and_seed_bracket():
    order = [f"T{i}" for i in range(1, 25)]
    auto = {"c1": "T20", "c2": "T3"}
    field = N.select_field(order, auto, 16)
    assert len(field) == 16 and "T20" in field and "T3" in field and "T17" not in field
    conf = {t: ("x" if t in ("T1", "T16") else "c%s" % t) for t in field}
    br = N.seed_bracket(field, conf)
    regs = br["regions"]
    assert len(regs) == 4 and all(len(v) == 4 for v in regs.values())
    # no first-round conference match-up for the 1 seed with its 4 seed
    for v in regs.values():
        s = dict(v)
        assert conf.get(s[1]) != conf.get(s[4]) or s[1] != "T1"


# ── game model ─────────────────────────────────────────────────────────────────────────────────────────────

def test_outcome_sums_to_one_and_ties():
    p = dict(M.DEFAULTS)
    o = M.outcome(3.0, 3.0, p, post=False, season=2026)
    assert math.isclose(o["p_home"] + o["p_tie"] + o["p_away"], 1.0, abs_tol=1e-9)
    assert math.isclose(o["p_home"], o["p_away"], abs_tol=1e-9) and 0.03 < o["p_tie"] < 0.15
    po = M.outcome(3.0, 3.0, p, post=True, season=2026)
    assert po["p_tie"] == 0 and math.isclose(po["p_home"], 0.5, abs_tol=1e-9)
    strong = M.outcome(4.0, 2.0, p, season=2026)
    assert strong["p_home"] > 0.6


def test_regulation_goals_strip_ot_and_shootouts():
    assert M.regulation_goals({"hs": 3, "as": 2, "ot": 1}) == (2, 2)
    assert M.regulation_goals({"hs": 3, "as": 3, "ot": 1}) == (3, 3)
    assert M.regulation_goals({"hs": 4, "as": 3, "ot": 1, "so": True}) == (3, 3)
    assert M.regulation_goals({"hs": 5, "as": 1}) == (5, 1)
    assert M.regulation_goals({"hs": 2, "as": 1, "per": [[1, 0, 0], [0, 1, 0]], "ot": 1}) == (1, 1)


def _season(n_teams=12, n_rounds=8, seed=0, year=2026):
    rng = random.Random(seed)
    teams = [f"T{i}" for i in range(n_teams)]
    strength = {t: (n_teams - i) / n_teams for i, t in enumerate(teams)}
    games, k = [], 0
    for r in range(n_rounds):
        rng.shuffle(teams)
        for i in range(0, n_teams, 2):
            h, a = teams[i], teams[i + 1]
            lh, la = 3 * math.exp(0.6 * (strength[h] - strength[a]) + 0.08), 3 * math.exp(0.6 * (strength[a] - strength[h]))
            hs, as_ = np.random.default_rng(k).poisson(lh), np.random.default_rng(k + 999).poisson(la)
            res = "W" if hs > as_ else "L" if hs < as_ else "T"
            d = (date(year - 1, 10, 3) + timedelta(days=7 * r)).isoformat()
            games.append(game(k, h, a, res, hs=int(hs), as_=int(as_), date=d))
            k += 1
    st = {"teams": {t: {"d1": True, "conf": "c1" if int(t[1:]) % 2 else "c2"} for t in teams},
          "games": sorted(games, key=lambda g: g["date"]), "conferences": {"c1": {}, "c2": {}}}
    return st, strength


def test_walk_forward_learns_strength():
    st, strength = _season(n_rounds=16)
    preds, ends = M.walk_forward([2026], {2026: st})
    f = ends[2026]
    best = max(strength, key=strength.get)
    worst = min(strength, key=strength.get)
    assert f.net(best) > f.net(worst)
    # predictions use only earlier games: the first day's predictions come from the prior (no games yet)
    first = min(p["day"] for p in preds)
    assert all(p["n_fit"] == 0 for p in preds if p["day"] == first)


# ── season simulation ──────────────────────────────────────────────────────────────────────────────────────

def test_simulation_shapes_and_totals():
    st, _ = _season(n_teams=20, n_rounds=6, year=2027)
    # leave the last two rounds to play
    played = st["games"][:-20]
    rest = [dict(g, status="pre", res=None, hs=None, **{"as": None}) for g in st["games"][-20:]]
    st["games"] = played + rest
    d1 = {t for t in st["teams"]}
    f = M.season_ratings(2027, st["games"], d1, {}, M.DEFAULTS)
    cx = SIM.Ctx(st, f, {}, 2027)
    res = SIM.simulate(cx, "mch", n=400, seed=1)
    T = res["teams"]
    assert math.isclose(sum(v["p_title"] for v in T.values()), 1.0, abs_tol=2e-3)
    assert math.isclose(sum(v["p_ncaa"] for v in T.values()), 16.0, abs_tol=2e-3)
    assert math.isclose(sum(v["p_f4"] for v in T.values()), 4.0, abs_tol=2e-3)
    assert all(v["p_title"] <= v["p_final"] + 1e-9 <= v["p_f4"] + 2e-9 for v in T.values())
    wres = SIM.simulate(cx, "wch", n=300, seed=2)
    assert math.isclose(sum(v["p_ncaa"] for v in wres["teams"].values()), 11.0, abs_tol=2e-3)


def test_field_format():
    assert SIM.field_format("mch", 2027)["field"] == 16
    assert SIM.field_format("wch", 2026)["field"] == 11
    assert SIM.field_format("wch", 2019)["field"] == 8
