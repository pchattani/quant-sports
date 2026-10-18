"""Rink value: season value and best by position, the aging curve, rest-of-season projections, the position-aware depth
chart, grades, trade targets and the sensitivity curves (analytics/value.py, season_sim.sensitivity). Synthetic
inputs only; no network."""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.nhl.analytics import value as V
from oddsmarkets.nhl.models import game as GM
from oddsmarkets.nhl.models import season_sim as SS
from oddsmarkets.nhl.models import synthetic_c as SC

PRM = V.params_for({"F": 180.0, "D": 120.0})
S2, S3 = 20252026, 20262027
GP = {"theta": 0.08, "tie_k": 0.85, "k_pull": 2.2, "r_en": 0.22, "pull1": 2.0, "pull2": 3.0,
      "k_ot": {"3v3": 1.85, "4v4": 1.2}, "so_home": 0.5, "b0": 0.0, "b_xg": 1.0, "b_g": 0.0, "home": 0.045,
      "s": {"b2b": -0.06, "rest": 0.0, "travel": 0.0, "tz": 0.0}}


def P(pid, team, pos, mpg, rate, comps=None, age=27.0, basis="b"):
    c = {k: 0.0 for k in V.COMPONENTS}
    c["ev_off"] = rate / 2
    c["ev_def"] = rate / 2
    c.update(comps or {})
    return {"id": pid, "name": pid.upper(), "team": team, "pos": pos, "group": V.GROUP[pos], "mpg": mpg, "rate": rate,
            "next": rate, "comps": c, "age": age, "basis": basis}


def roster(team="A", base=0.0):
    """12 forwards (4 C, 4 L, 4 R) using the 180 forward minutes, 6 defence using 120, two goalies using 60."""
    out = []
    for i, (m, r) in enumerate(((19, 0.4), (16, 0.2), (14, 0.05), (11, -0.05))):
        out += [P(f"{team}c{i}", team, "C", m, base + r), P(f"{team}l{i}", team, "L", m, base + r - 0.02),
                P(f"{team}r{i}", team, "R", m, base + r - 0.04)]
    for i, (m, r) in enumerate(((23, 0.3), (21, 0.15), (20, 0.05), (20, 0.0), (18, -0.05), (18, -0.1))):
        out.append(P(f"{team}d{i}", team, "D", m, base + r))
    out += [P(f"{team}g0", team, "G", 45, base + 0.2), P(f"{team}g1", team, "G", 15, base - 0.1)]
    out += [P(f"{team}x{i}", team, "C", 8, base - 0.2) for i in range(2)]          # extras outside the rotation
    return out


# ---------------------------------------------------------------------------------------------- season value

def _cat(rows, kind="S", team_games=82):
    players = {}
    for pid, pos, toi, q, gar, war, comps in rows:
        vals = {"gar": gar, "war": war}
        if kind == "S":
            vals.update({f"gar_{c}": v for c, v in (comps or {}).items()})
        else:
            vals.update({"gsax": gar - 5.0, "sv_pct": 0.91})
        players[pid] = {"name": pid, "team": "T", "pos": pos, "group": "G" if kind == "G" else ("D" if pos == "D" else "F"),
                        "age": 27.0, "gp": 60, "toi": toi, "qualified": q, "values": vals}
    return {"players": players, "team_games": team_games}


def test_season_value_rates_percentiles_best_by_position():
    rows = [(f"s{i}", "CLRD"[i % 4], 1000 + 20 * i, i < 20, i * 0.5, i * 0.5 / 6.0, {"ev_off": i * 0.3, "pp": i * 0.2})
            for i in range(24)]
    sk = _cat(rows)
    gk = _cat([(f"g{i}", "G", 2000 + 100 * i, True, 10.0 * i, 10.0 * i / 6.0, None) for i in range(5)], kind="G")
    prev = _cat([("s8", "C", 1500, True, 1.5, 0.25, {})])
    v = V.season_value(S2, sk, gk, prev)
    R = {r[0]: dict(zip(v["cols"], r)) for r in v["rows"]}
    assert R["s8"]["rate"] == pytest.approx(4.0 / 1160 * 60, abs=1e-3)
    assert R["s8"]["d_rate"] == pytest.approx(4.0 / 1160 * 60 - 1.5 / 1500 * 60, abs=1e-3)
    assert R["s8"]["prev_war"] == pytest.approx(0.25)
    assert R["s8"]["ev_off"] == pytest.approx(2.4) and R["s8"]["why"][0][0] == "EV offence"
    assert R["g4"]["kind"] == "G" and R["g4"]["pct"] == 90             # goalies against goalies only (mid-rank of 5)
    assert R["s19"]["pct"] == 98 and R["s23"]["q"] == 0 and R["s23"]["pct"] == 100
    for k, ids in v["best"].items():
        assert all(R[i]["q"] == 1 and R[i]["pos"] == k for i in ids)
        assert [R[i]["war"] for i in ids] == sorted([R[i]["war"] for i in ids], reverse=True)
    assert v["best"]["G"][0] == "g4" and "s23" not in sum(v["best"].values(), [])
    assert v["currency"]["goals_per_win"] == pytest.approx(6.0, abs=0.01)


def test_season_value_percentiles_need_the_minutes_floor():
    """Early in a season (skaters.VALUE_PCT_MIN_TOI): no percentile under 200 minutes (600 for goalies), and those
    players are not in the pool; the floor scales with a short schedule (48 games in 2012-13), not with games played."""
    rows = [(f"s{i}", "CLRD"[i % 4], 250.0 + 10 * i, True, 0.01 * i, 0.01 * i / 6.0, {}) for i in range(10)]
    rows += [(f"e{i}", "C", 60.0 + i, True, 0.5, 0.5 / 6.0, {}) for i in range(10)]          # near-ties at a few games
    sk = _cat(rows, team_games=10)
    gk = _cat([(f"g{i}", "G", 400.0 + 100 * i, True, 1.0 * i, i / 6.0, None) for i in range(5)], kind="G", team_games=10)
    v = V.season_value(S3, sk, gk)
    R = {r[0]: dict(zip(v["cols"], r)) for r in v["rows"]}
    assert all(R[f"e{i}"]["pct"] is None and R[f"e{i}"]["pct_pos"] is None for i in range(10))
    assert R["s9"]["pct"] == 95 and R["s0"]["pct"] == 5            # placed among the ten past the floor only
    assert R["g0"]["pct"] is None and R["g1"]["pct"] is None and R["g4"]["pct"] == 83
    assert v["min_toi_pct"] == {"S": 200, "G": 600}
    from oddsmarkets.nhl.analytics.skaters import value_min_toi
    assert value_min_toi(20122013)["S"] == pytest.approx(200 * 48 / 82) and value_min_toi(20262027)["S"] == 200


def test_goals_per_win_needs_a_sample():
    assert V.goals_per_win([{"gar": 6.0, "war": 1.0}] * 19) is None
    assert V.goals_per_win([{"gar": 6.0, "war": 1.0}] * 20 + [{"gar": 0.1, "war": 0.01}]) == pytest.approx(6.0)


def test_aging_curve_recovers_a_planted_decline():
    rng = np.random.default_rng(0)
    seasons = [20152016 + 10001 * k for k in range(6)]
    rows = {s: [] for s in seasons}
    for i in range(600):
        age0 = 20 + i % 16
        talent = rng.normal(0.1, 0.1)
        for k, s in enumerate(seasons):
            age = age0 + k
            drift = 0.02 if age < 25 else (-0.03 if age >= 31 else 0.0)        # planted: up young, down old
            talent += drift
            rows[s].append({"id": str(i), "kind": "S", "age": float(age), "toi": 1200.0, "rate": talent + rng.normal(0, 0.01)})
    curve = dict((a, d) for a, d in V.aging_curve(rows, "S"))
    assert curve[22] > curve[28] > curve[34]
    assert curve[22] > 0 > curve[34]
    assert V.aging_delta(V.aging_curve(rows, "S"), 22.5) == pytest.approx((curve[22] + curve[23]) / 2, abs=1e-6)
    assert V.aging_delta(None, 30) == 0.0


# ---------------------------------------------------------------------------------------------- projection

def test_projection_pools_seasons_and_shrinks_to_replacement():
    cur = {"toi": 300.0, "gp": 20, "values": {"gar": 3.0, "gar_ev_off": 2.0}}
    prev = {"toi": 1500.0, "gp": 80, "values": {"gar": 10.0, "gar_ev_off": 6.0}}
    pr = V.player_projection(cur, prev, "S")
    den = 300 + 0.7 * 1500 + V.SHRINK_MIN["S"]
    assert pr["rate"] == pytest.approx((3.0 + 0.7 * 10.0) / den * 60)
    assert pr["comps"]["ev_off"] == pytest.approx((2.0 + 0.7 * 6.0) / den * 60)
    assert pr["mpg"] == pytest.approx((300 + 10 * 1500 / 80) / 30)
    assert pr["basis"] == "b"
    callup = V.player_projection({"toi": 30.0, "gp": 3, "values": {"gar": 3.0}}, None, "S")
    assert callup["rate"] == pytest.approx(3.0 / (30 + V.SHRINK_MIN["S"]) * 60) and callup["rate"] < 0.6
    nobody = V.player_projection(None, None, "S")
    assert nobody["rate"] == 0.0 and nobody["basis"] == "r" and nobody["mpg"] == 0.0
    g = V.player_projection({"toi": 600.0, "gp": 10, "values": {"gar": 2.0}}, {"toi": 3000.0, "gp": 55, "values": {"gar": 20.0}}, "G",
                            team_gp_cur=20, team_gp_prev=82)
    share = (600 / 1200 * 20 + 3000 / (82 * 60) * 10) / 30
    assert g["mpg"] == pytest.approx(share * 60)


# ---------------------------------------------------------------------------------------------- depth chart

def test_baseline_respects_group_budgets_and_caps():
    team = roster()
    m = V.baseline_minutes(team, PRM)
    by = {p["id"]: p for p in team}
    for g in ("F", "D", "G"):
        assert sum(v for k, v in m.items() if by[k]["group"] == g) == pytest.approx(PRM["budget"][g])
    assert m["Ax0"] == 0.0 and m["Ax1"] == 0.0
    assert max(v for k, v in m.items() if by[k]["group"] == "F") <= PRM["cap"]["F"]


def test_centre_swap_and_displacement_by_position():
    team = roster()
    star = P("Zc", "Z", "C", 21, 0.6)
    res = V.apply_moves(team, ["Ac0"], [star], PRM)
    # 19 open centre minutes, the star wants 21: two more from the lowest-rated centre
    assert dict(res["displaced"]) == {"Ac3": pytest.approx(2.0)}
    assert res["delta"] == pytest.approx((0.6 * 21 - 0.4 * 19 - (-0.05) * 2) / 60)
    tot = {g: sum(v for k, v in res["minutes"].items() if (k == "Zc" and g == "F") or
                  (k != "Zc" and next(p for p in team if p["id"] == k)["group"] == g)) for g in ("F", "D", "G")}
    for g in ("F", "D", "G"):
        assert tot[g] + res["fill_after"][g] == pytest.approx(PRM["budget"][g])


def test_defence_never_displaces_forwards_and_wingers_cover_centres():
    team = roster()
    d = P("Zd", "Z", "D", 22, 0.5)
    res = V.apply_moves(team, [], [d], PRM)
    assert all(k.startswith("Ad") for k in dict(res["displaced"]))
    w = P("Zl", "Z", "L", 18, 0.5)
    team2 = [p for p in team if p["pos"] != "L"] + [P("Al0", "A", "L", 5, -0.3)]
    res2 = V.apply_moves(team2, [], [w], PRM)
    # his own position first (the worse left wing, then replacement minutes, which a short forward group has)
    assert dict(res2["displaced"]) == {"Al0": pytest.approx(5.0)}
    assert res2["fill_after"]["F"] == pytest.approx(res2["fill_before"]["F"] - 13.0)
    # no left wings and no spare minutes: the neighbours (right wings first, then centres), lowest-rated first
    team3 = [p for p in team if p["pos"] != "L"] + [P("Ay", "A", "C", 22, -0.4), P("Az", "A", "R", 22, -0.45)]
    res3 = V.apply_moves(team3, [], [w], PRM)
    assert res3["fill_before"]["F"] == pytest.approx(0.0)
    assert dict(res3["displaced"]) == {"Az": pytest.approx(18.0)}


def test_a_better_goalie_takes_the_starts():
    team = roster()
    backup_star = P("Zg", "Z", "G", 20, 0.5)
    res = V.apply_moves(team, [], [backup_star], PRM)
    assert res["minutes"]["Zg"] == pytest.approx(60.0)
    assert dict(res["displaced"]) == {"Ag0": pytest.approx(45.0), "Ag1": pytest.approx(15.0)}
    assert res["delta"] == pytest.approx((0.5 * 60 - 0.2 * 45 - (-0.1) * 15) / 60)
    worse = P("Zh", "Z", "G", 20, 0.0)
    res2 = V.apply_moves(team, [], [worse], PRM)
    assert dict(res2["displaced"]) == {"Ag1": pytest.approx(15.0)}      # only the backup he outrates


def test_outgoing_minutes_go_to_the_next_best_then_replacement():
    team = roster()
    res = V.apply_moves(team, ["Ad0"], [], PRM)
    ab = dict(res["absorbed"])
    assert ab["Ad1"] == pytest.approx(PRM["cap"]["D"] - 21)
    assert all(v <= PRM["extra"]["D"] + 1e-9 for v in ab.values())               # spread: at most 5 more each
    assert ab["Ad2"] == pytest.approx(5.0) and ab["Ad5"] == pytest.approx(3.0)
    assert sum(ab.values()) == pytest.approx(23.0)
    lone = [P("Bd0", "B", "D", 20, 0.1), P("Bd1", "B", "D", 20, 0.0)]
    res2 = V.apply_moves(lone, ["Bd0"], [], PRM)
    assert res2["fill_after"]["D"] == pytest.approx(PRM["budget"]["D"] - 20 - PRM["extra"]["D"])


# ---------------------------------------------------------------------------------------------- grades and targets

def test_grades_and_targets():
    lists = {"A": roster("A", -0.1), "B": roster("B", 0.0), "C": roster("C", 0.1)}
    lists["C"].append(P("Cstar", "C", "C", 21, 0.9, age=35.0))
    lists["C"][-1]["next"] = 0.85
    g = V.grade_teams(lists, PRM, 82)
    for k in ("L", "R", "D", "G", "ev_off"):
        assert g["C"][k]["rank"] == 1 and g["A"][k]["rank"] == 3
    out = V.candidates("A", "C", lists, PRM, {"A": 60}, None, {"B": {"p_playoffs": 0.05}, "C": {"p_playoffs": 0.9}})
    assert out[0]["id"] == "Cstar" and all(c["pos"] == "C" and c["team"] != "A" for c in out)
    assert [c["gain"] for c in out[:V.N_CANDIDATES]] == sorted([c["gain"] for c in out[:V.N_CANDIDATES]], reverse=True)
    assert out[0]["gain_season"] == pytest.approx(out[0]["gain_net"] * 60, abs=0.1)
    assert any("age 35" in h for h in out[0]["hints"]) and not out[0]["attainable"]
    bc = [c for c in out if c["team"] == "B"]
    assert bc and all(any("out of contention" in h for h in c["hints"]) for c in bc)
    unit = V.candidates("A", "pp", lists, PRM, {"A": 60}, None, {})
    assert all(c["pos"] != "G" for c in unit)
    nd = V.needs_payloads(S3, {p["id"]: p for ps in lists.values() for p in ps}, PRM, 82, {t: 60 for t in lists}, None, {})
    assert len(nd["A"]["strengths"]) == 3 and len(nd["A"]["weaknesses"]) == 3
    assert "Cap not checked" in nd["A"]["note"]


# ---------------------------------------------------------------------------------------------- sensitivity

def test_interp_monotone_and_curve_delta():
    xs = [-0.75, -0.4, -0.15, 0.0, 0.15, 0.4, 0.75]
    ys = [0.1, 0.2, 0.3, 0.35, 0.33, 0.5, 0.6]
    sm = V.monotone(xs, ys)
    assert sm[4] == 0.35 and sm == sorted(sm)
    assert V.monotone(xs, [0.3, 0.2, 0.25, 0.1, 0.05, 0.0, 0.01], decreasing=True)[-1] == 0.0
    c = {"shifts": xs, "teams": {"T": {"exp_pts": [80, 85, 88, 90, 92, 95, 100]}}}
    assert V.curve_delta(c, "T", "exp_pts", 0.075) == pytest.approx(1.0)
    assert V.curve_delta(c, "T", "exp_pts", 2.0) == pytest.approx(10.0)       # the edge value beyond the grid


def test_season_sim_sensitivity_on_a_synthetic_league(rink_roots):
    GM.set_params(None)
    lg = SC.league((S2, S3), seed=5, played_through="2026-12-20")
    rd = SC.truth_rd(lg["truth"][S3])
    for t in rd["teams"]:
        rd["teams"][t]["se_net"] = 0.15
    st = {"store": lg["stores"][S3], "ratings": rd, "params": GP, "through": "2026-12-21"}
    t = sorted(rd["teams"])[0]
    base = SS.simulate(S3, n=600, seed=3, state=st)
    up = SS.simulate(S3, n=600, seed=3, state={**st, "shift": {t: 0.5}})
    assert up["teams"][t]["exp_pts"] > base["teams"][t]["exp_pts"] + 5
    sens = SS.sensitivity(S3, n=400, seed=3, state=st, teams=[t])
    assert sens["ok"] and sens["shifts"] == list(SS.SENS_SHIFTS)
    c = sens["teams"][t]
    assert np.all(np.diff(c["exp_pts"]) > 0)
    i0 = sens["shifts"].index(0.0)
    same = SS.simulate(S3, n=400, seed=3, state=st)
    assert c["exp_pts"][i0] == pytest.approx(same["teams"][t]["exp_pts"], abs=1e-3)
    assert c["p_playoffs"][0] <= c["p_playoffs"][-1]
    GM.set_params(None)
