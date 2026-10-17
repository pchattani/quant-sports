"""Player value, position grades, trade targets, the depth chart and the sensitivity curves (analytics/value.py,
season_sim.sensitivity). Synthetic inputs only; no network."""
from __future__ import annotations

import math

import numpy as np
import pytest

from oddsmarkets.basketball.analytics import value as V
from oddsmarkets.basketball.models import ratings as R
from oddsmarkets.basketball.models import season_sim as SS
from oddsmarkets.basketball.models.synthetic import make_store

PRM = V.params_for("nba", pace=100.0, ppw=31.0)


def P(pid, team, role, mpg, rate, o=None, d=None, age=27.0, basis="p"):
    o = rate / 2 if o is None else o
    d = rate - o if d is None else d
    return {"id": pid, "name": pid.upper(), "team": team, "role": role, "mpg": mpg, "rate": rate, "o": o, "d": d,
            "next": rate, "age": age, "basis": basis}


def roster(team="A", base=0.0):
    """Ten players: two starting guards, two wings, one big starter, then the bench. The first nine use exactly
    the 240 team minutes, so the tenth (b3) is out of the rotation."""
    return [P(f"{team}g1", team, "G", 36, base + 3.0), P(f"{team}g2", team, "G", 32, base + 1.0),
            P(f"{team}w1", team, "W", 34, base + 2.0), P(f"{team}w2", team, "W", 30, base + 0.0),
            P(f"{team}b1", team, "B", 33, base + 1.5), P(f"{team}g3", team, "G", 22, base - 1.0),
            P(f"{team}w3", team, "W", 20, base - 1.5), P(f"{team}b2", team, "B", 18, base - 0.5),
            P(f"{team}g4", team, "G", 15, base - 2.5), P(f"{team}b3", team, "B", 10, base - 3.0)]


# ---------------------------------------------------------------------------------------------- currency and positions

def test_points_per_win_is_sigma_root_two_pi():
    assert V.points_per_win("nba", sigma=12.0) == pytest.approx(12.0 * math.sqrt(2 * math.pi))
    # one point of margin per game over 82 games moves wins by 82 / ppw: the game model's slope at an even game
    assert 82 / V.points_per_win("nba", sigma=12.4) == pytest.approx(82 * 0.398942 / 12.4, rel=1e-5)


def _cat(rows, min_floor=200):
    players = {}
    for pid, pool, mins, q, vals in rows:
        players[pid] = {"name": pid, "team": "T", "pos": pool, "pool": pool, "age": 25.0, "gp": 60, "min": mins, "qualified": q,
                        "values": vals, "pct": {}}
    return {"players": players, "min_floor": min_floor}


def _box(reb, blk, rim, tpar, ast):
    return {"oreb100": reb / 3, "dreb100": 2 * reb / 3, "blk100": blk, "rim_freq": rim, "tpar": tpar, "ast100": ast}


def test_roles_split_forwards_by_box_profile():
    rows = []
    for i in range(12):
        rows.append((f"g{i}", "G", 1500, True, _box(7 + i * 0.1, 0.5, 0.25, 0.45, 9)))
        rows.append((f"c{i}", "C", 1500, True, _box(18 + i * 0.1, 3.0, 0.6, 0.05, 3)))
    rows += [("fbig", "F", 1200, True, _box(16, 2.5, 0.55, 0.1, 3)), ("fwing", "F", 1200, True, _box(8, 0.6, 0.3, 0.42, 6)),
             ("fnew", "F", 100, False, _box(17, 3.0, 0.6, 0.05, 2))]
    roles, info = V.classify_roles(_cat(rows))
    assert roles["g0"] == "G" and roles["c0"] == "B"
    assert roles["fbig"] == "B" and roles["fwing"] == "W"
    assert roles["fnew"] == "W"                       # under ROLE_MIN minutes: a wing by default
    assert info["threshold"] is not None and set(info["features"]) >= {"reb100", "blk100", "tpar"}


def test_season_value_war_percentiles_and_best():
    rows = [(f"p{i}", "G" if i % 3 == 0 else "C" if i % 3 == 1 else "F", 1000 + 50 * i, i < 9,
             {"hpm": float(i) - 3.0, "hpm_o": float(i) / 2, "hpm_d": float(i) / 2 - 3.0, "hpm_se": 1.5, **_box(10, 1, 0.3, 0.3, 5)})
            for i in range(12)]
    cat = _cat(rows)
    prev = _cat([("p5", "C", 2000, True, {"hpm": 0.0})])
    v = V.season_value("nba", 2026, cat, prev, pace=100.0, ppw=31.0)
    rows_ = [dict(zip(v["cols"], r)) for r in v["rows"]]
    by = {r["id"]: r for r in rows_}
    # WAR = (HPM + 2) x minutes x pace / 48 / 100 / ppw
    r = by["p5"]
    assert r["war"] == pytest.approx((2.0 + 2.0) * 1250 * 100 / 48 / 100 / 31, abs=0.01)
    assert r["prev_war"] == pytest.approx(2.0 * 2000 * 100 / 48 / 100 / 31, abs=0.01)
    assert r["d_hpm"] == pytest.approx(2.0)
    assert [x["war"] for x in rows_] == sorted([x["war"] for x in rows_], reverse=True)
    # best lists hold qualified players only, best first
    for k, ids in v["best"].items():
        assert all(by[i]["q"] == 1 for i in ids)
        assert [by[i]["war"] for i in ids] == sorted([by[i]["war"] for i in ids], reverse=True)
    # the floor: unqualified players are placed against the qualified ones but are never in the best lists
    assert by["p11"]["q"] == 0 and by["p11"]["pct"] == 100
    assert "p11" not in sum(v["best"].values(), [])
    assert v["currency"]["points_per_win"] == 31.0 and v["currency"]["replacement"] == -2.0


def test_projection_blends_this_season_with_the_prior():
    cur = {"min": 1000, "gp": 30, "values": {"hpm": 4.0, "hpm_o": 3.0, "hpm_d": 1.0}}
    prev = {"values": {"hpm": 2.0, "hpm_o": 1.5, "hpm_d": 0.5}}
    pr = V.player_projection(cur, [1.0, 30.0], prev, 32.0, None)
    w = 1000 / (1000 + V.PRIOR_MIN)
    assert pr["rate"] == pytest.approx(w * 4.0 + (1 - w) * 1.0)
    assert pr["o"] + pr["d"] == pytest.approx(pr["rate"])
    assert pr["basis"] == "b" and pr["mpg"] == 32.0
    only_prior = V.player_projection(None, [1.0, 30.0], prev, None, 26.0)
    assert only_prior["rate"] == 1.0 and only_prior["basis"] == "p" and only_prior["mpg"] == 30.0
    new = V.player_projection(cur, None, None, 30.0, 22.0)
    w2 = 1000 / (1000 + V.PRIOR_MIN_NEW)
    assert new["basis"] == "c" and new["rate"] == pytest.approx(w2 * 4.0 + (1 - w2) * V.REPLACEMENT)
    rookie = V.player_projection(None, None, None, None, 20.0)
    assert rookie["rate"] == V.REPLACEMENT and rookie["basis"] == "r" and rookie["mpg"] == 0.0
    assert rookie["next"] > rookie["rate"]                       # a 20-year-old improves on the aging curve


# ---------------------------------------------------------------------------------------------- depth chart

def test_baseline_minutes_fill_five_players_and_cap_each():
    team = roster()
    m = V.baseline_minutes(team, PRM)
    assert sum(m.values()) == pytest.approx(PRM["cap"])
    assert max(m.values()) <= PRM["max_min"] + 1e-9
    assert m["Ab3"] == 0.0                                       # the 240 minutes are gone before the 10th man
    short = team[:4]
    v = V.team_value(short, V.baseline_minutes(short, PRM), PRM)
    assert v["fill"] == pytest.approx(PRM["cap"] - 132)
    assert v["net"] == pytest.approx((36 * 3 + 32 * 1 + 34 * 2 + 30 * 0) / 48 + V.REPLACEMENT * v["fill"] / 48)


def test_like_for_like_swap_moves_rating_by_the_rate_gap():
    team = roster()
    new = P("Xg", "X", "G", 36, 5.0)
    res = V.apply_moves(team, ["Ag1"], [new], PRM)
    assert res["delta"] == pytest.approx((5.0 - 3.0) * 36 / 48)
    assert res["displaced"] == [] and res["absorbed"] == []
    assert sum(res["minutes"].values()) + res["fill_after"] == pytest.approx(PRM["cap"])


def test_incoming_player_displaces_the_lowest_rated_at_his_position():
    team = roster()
    new = P("Xb", "X", "B", 30, 4.0)
    res = V.apply_moves(team, [], [new], PRM)
    disp = dict(res["displaced"])
    # bigs in the rotation: b1 (+1.5, 33), b2 (-0.5, 18); b3 has no minutes. Worst first: b2 then b1.
    assert disp["Ab2"] == pytest.approx(18.0)
    assert disp["Ab1"] == pytest.approx(12.0)
    assert "Ab3" not in disp
    assert res["delta"] == pytest.approx((4.0 * 30 - (-0.5) * 18 - 1.5 * 12) / 48)
    # a worse newcomer takes nothing from better players at his position; he moves on to worse wings, then guards
    weak = P("Xw", "X", "B", 30, -1.0)
    res2 = V.apply_moves(team, [], [weak], PRM)
    d2 = dict(res2["displaced"])
    assert "Ab1" not in d2 and "Ab2" not in d2
    assert d2["Aw3"] == pytest.approx(20.0) and d2["Ag4"] == pytest.approx(10.0)


def test_outgoing_minutes_go_to_the_next_best_up_to_the_cap_then_replacement():
    team = roster()
    res = V.apply_moves(team, ["Ag1"], [], PRM)
    absorbed = dict(res["absorbed"])
    # best remaining guards first, each at most 12 more (EXTRA_SHARE) and up to the cap: g2 (+1.0, 32) to the cap,
    # g3 and g4 +12 each; the last 5.6 minutes go to the neighbouring wings, best first (w1 to the cap, then w2)
    assert absorbed["Ag2"] == pytest.approx(PRM["max_min"] - 32)
    assert absorbed["Ag3"] == pytest.approx(PRM["extra"]) and absorbed["Ag4"] == pytest.approx(PRM["extra"])
    assert absorbed["Aw1"] == pytest.approx(PRM["max_min"] - 34)
    assert absorbed["Aw2"] == pytest.approx(36 - (PRM["max_min"] - 32) - 2 * PRM["extra"] - (PRM["max_min"] - 34))
    assert res["delta"] < 0
    lone = [P("Lg", "L", "G", 30, 2.0), P("Lb", "L", "B", 30, 0.0)]
    res3 = V.apply_moves(lone, ["Lg"], [], PRM)
    # the big takes what he can (up to the cap), the rest goes to replacement
    assert dict(res3["absorbed"])["Lb"] == pytest.approx(PRM["max_min"] - 30)
    assert res3["fill_after"] == pytest.approx(PRM["cap"] - PRM["max_min"])


def test_trade_is_zero_sum_in_minutes_and_symmetric_for_identical_players():
    a, b = roster("A"), roster("B")
    ra = V.apply_moves(a, ["Aw1"], [b[2]], PRM)
    rb = V.apply_moves(b, ["Bw1"], [a[2]], PRM)
    assert ra["delta"] == pytest.approx(0.0, abs=1e-12) and rb["delta"] == pytest.approx(0.0, abs=1e-12)
    for r in (ra, rb):
        assert sum(r["minutes"].values()) + r["fill_after"] == pytest.approx(PRM["cap"])


# ---------------------------------------------------------------------------------------------- grades and targets

def test_grades_rank_teams_by_position_value():
    lists = {"A": roster("A", base=2.0), "B": roster("B", base=0.0), "C": roster("C", base=-2.0)}
    g = V.grade_teams(lists, PRM, 82)
    for k in ("G", "W", "B", "off", "def", "start", "bench"):
        assert g["A"][k]["rank"] == 1 and g["C"][k]["rank"] == 3
        assert g["A"][k]["pct"] > g["B"][k]["pct"] > g["C"][k]["pct"]
    assert g["A"]["G"]["grade"] == "A" and g["C"]["G"]["grade"] == "F"
    assert V.grade(80) == "A" and V.grade(60) == "B" and V.grade(40) == "C" and V.grade(20) == "D" and V.grade(19) == "F"


def test_candidates_rank_by_gain_at_the_weak_spot_with_data_hints():
    weak_bigs = roster("A")
    for p in weak_bigs:
        if p["role"] == "B":
            p["rate"] -= 3.0
            p["o"] -= 1.5
            p["d"] -= 1.5
    lists = {"A": weak_bigs, "B": roster("B"), "C": roster("C", base=1.0)}
    lists["C"].append(P("Cstar", "C", "B", 33, 7.0, age=33.0))
    sim = {"B": {"p_playoffs": 0.05}, "C": {"p_playoffs": 0.9}}
    out = V.candidates("A", "B", lists, PRM, {"A": 82, "B": 82, "C": 82}, None, sim, {"Cb1": "Out (knee)"})
    assert out and all(c["team"] != "A" and c["role"] == "B" for c in out)
    gains = [c["gain"] for c in out[:V.N_CANDIDATES]]
    assert gains == sorted(gains, reverse=True)
    assert out[0]["id"] == "Cstar"
    star = out[0]
    assert any("age 33" in h for h in star["hints"]) and any("two most valuable" in h for h in star["hints"])
    assert not star["attainable"]
    bb1 = next(c for c in out if c["id"] == "Bb1")
    assert any("out of contention" in h for h in bb1["hints"])
    cb1 = next((c for c in out if c["id"] == "Cb1"), None)
    if cb1:
        assert any("injury report" in h for h in cb1["hints"])
    # wins without curves: the game model's conversion
    assert star["wins"] == pytest.approx(star["gain_net"] * 100 / 100 * 82 / 31.0, abs=0.02)
    # every target really adds value at that spot
    for c in out:
        res = V.apply_moves(lists["A"], [], [next(p for p in lists[c["team"]] if p["id"] == c["id"])], PRM)
        assert res["delta"] == pytest.approx(c["gain"], abs=0.01)


def test_candidates_skip_low_minutes_and_replacement_players():
    lists = {"A": roster("A"), "B": [P("Bx", "B", "G", 5, 9.0), P("By", "B", "G", 30, 9.0, basis="r")]}
    assert V.candidates("A", "G", lists, PRM, {"A": 82}, None, {}, {}) == []


def test_needs_payload_has_three_strengths_and_three_weaknesses():
    lists = {t: roster(t, base=b) for t, b in (("A", 1.0), ("B", 0.0), ("C", -1.0), ("D", 0.5))}
    proj = {p["id"]: p for ps in lists.values() for p in ps}
    out = V.needs_payloads("nba", 2027, proj, PRM, {t: 82 for t in lists}, None, {}, {})
    nd = out["B"]
    assert len(nd["strengths"]) == 3 and len(nd["weaknesses"]) == 3
    assert not {s["key"] for s in nd["strengths"]} & {w["key"] for w in nd["weaknesses"]}
    assert min(s["pct"] for s in nd["strengths"]) >= max(w["pct"] for w in nd["weaknesses"])
    assert "salary cap" in nd["note"] and nd["free_agents"]
    assert len(nd["grades"]) == 7 and all(g["grade"] in "ABCDF" for g in nd["grades"])


# ---------------------------------------------------------------------------------------------- sensitivity curves

def test_interpolation_and_edges():
    xs, ys = [-6, -3, 0, 3, 6], [0.1, 0.2, 0.4, 0.7, 0.9]
    assert V.interp(xs, ys, 1.5) == pytest.approx(0.55)
    assert V.interp(xs, ys, -9) == 0.1 and V.interp(xs, ys, 9) == 0.9
    assert V.interp(xs, [None, 0.2, 0.4, None, 0.9], 4.5) == pytest.approx(0.4 + 0.5 * 4.5 / 6)
    curves = {"shifts": xs, "teams": {"T": {"p_playoffs": ys}}}
    assert V.curve_delta(curves, "T", "p_playoffs", 3.0) == pytest.approx(0.3)
    assert V.curve_delta(curves, "T", "p_playoffs", 0.0) == 0.0
    assert V.curve_delta(curves, "U", "p_playoffs", 1.0) is None


def test_monotone_smoothing_from_zero_outward():
    xs = [-6, -3, -1.5, 0.0, 1.5, 3, 6]
    assert V.monotone(xs, [0.1, 0.3, 0.25, 0.4, 0.38, 0.5, 0.6]) == [0.1, 0.25, 0.25, 0.4, 0.4, 0.5, 0.6]
    assert V.monotone(xs, [0.5, 0.3, 0.35, 0.2, 0.22, 0.1, 0.0], decreasing=True) == [0.5, 0.35, 0.35, 0.2, 0.2, 0.1, 0.0]


def test_season_sim_shift_and_sensitivity_curves():
    st, truth = make_store("nba", 2027, seed=4, played_frac=0.4)
    rt = R.fit_ratings(st["games"], league="nba")
    t = sorted(rt["teams"])[0]
    base = SS.simulate("nba", 2027, n=1500, seed=3, state={"store": st, "ratings": rt})
    up = SS.simulate("nba", 2027, n=1500, seed=3, state={"store": st, "ratings": rt, "shift": {t: 3.0}})
    assert up["teams"][t]["exp_w"] > base["teams"][t]["exp_w"] + 1.0
    others = [x for x in base["teams"] if x != t]
    assert sum(up["teams"][x]["exp_w"] for x in others) < sum(base["teams"][x]["exp_w"] for x in others)
    sens = SS.sensitivity("nba", 2027, n=800, seed=3, state={"store": st, "ratings": rt}, teams=[t])
    assert sens["ok"] and sens["shifts"] == list(SS.SENS_SHIFTS)
    c = sens["teams"][t]
    i0 = sens["shifts"].index(0.0)
    ew = c["exp_w"]
    assert ew[0] < ew[i0] < ew[-1]
    assert np.all(np.diff(ew) > 0)                               # common random numbers: smooth in the shift
    assert c["p_top4"][0] >= c["p_top4"][-1]
    # the zero point is the base run with the same seed and size
    same = SS.simulate("nba", 2027, n=800, seed=3, state={"store": st, "ratings": rt})
    assert ew[i0] == pytest.approx(same["teams"][t]["exp_w"], abs=1e-4)
