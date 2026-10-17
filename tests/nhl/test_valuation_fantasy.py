"""Valuation v2 (analytics/valuation.py) and the fantasy layer (analytics/fantasy.py) on synthetic inputs; no network."""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.nhl.analytics import fantasy as FA
from oddsmarkets.nhl.analytics import valuation as VV

F0 = {"reliability": {"S": {"sigma2": 0.07, "tau2": 0.02, "delta2": 0.02}, "G": {"sigma2": 2.0, "tau2": 0.008, "delta2": 0.1}},
      "aging": {"S": [[a, (0.03 if a < 26 else -0.02)] for a in range(18, 43)], "G": [[a, 0.0] for a in range(18, 43)]},
      "survival": {"S": {"base": 0.8}, "G": {"base": 0.8}}, "minutes": {"S": {"cv": 0.3}, "G": {"cv": 0.4}}, "avail": {"S": 0.8, "G": 0.45}}


def P(**kw):
    p = {"id": "x", "kind": "S", "pos": "C", "age": 27.0, "rate": 0.3, "mpg": 18.0, "avail": 0.9, "t_eff": 2000.0,
         "games": [40, 84, 84, 84], "gpw": 6.0, "frac0": 0.5}
    p.update(kw)
    return p


# ---------------------------------------------------------------------------------------------- valuation

def test_discounting_ageing_and_survival():
    r = VV.project([P(age=None)], F0)[0]
    one = 0.3 * 18 * 0.9 / 60 / 6.0                     # WAR a game
    assert r["ev"][0] == pytest.approx(one * 40)
    assert r["ev"][1] == pytest.approx(0.8 * one * 84)
    assert r["ev"][3] == pytest.approx(0.8 ** 3 * one * 84)
    assert r["total"] == pytest.approx(sum(0.9 ** k * e for k, e in enumerate(r["ev"])))
    young = VV.project([P(age=22.0)], F0)[0]
    old = VV.project([P(age=33.0)], F0)[0]
    assert young["rates"][3] == pytest.approx(0.3 + 3 * 0.03)        # ageing applied a season at a time
    assert old["rates"][3] == pytest.approx(0.3 - 3 * 0.02)
    assert young["total"] > old["total"]


def test_band_ordering_and_width():
    rs = VV.project([P(id="a", t_eff=3000.0), P(id="b", t_eff=50.0), P(id="c", rate=-0.1)], F0)
    for r in rs:
        assert r["p10"] <= r["p50"] <= r["p90"]
    a, b = rs[0], rs[1]
    assert b["se"] > a["se"]                                           # fewer minutes, wider rate uncertainty
    assert (b["p90"] - b["p10"]) > (a["p90"] - a["p10"])


def test_injury_and_positional_replacement():
    base = VV.project([P()], F0)[0]
    hurt = VV.project([P(inj_games0=20)], F0)[0]
    assert hurt["ev"][0] == pytest.approx(base["ev"][0] * 20 / 40)
    assert hurt["ev"][1] == pytest.approx(base["ev"][1])
    v = VV.project([P(repl=0.1, age=None)], F0)[0]
    assert v["vorp"] == pytest.approx(v["total"] * (0.3 - 0.1) / 0.3, rel=1e-6)
    assert VV.injury_games("Injured Reserve", "2026-11-01", ["2026-10-20", "2026-10-25", "2026-11-02"], date(2026, 10, 16)) == 2
    assert VV.injury_games("Day-To-Day", None, ["2026-10-20"], date(2026, 10, 16)) == 1
    assert VV.injury_games("Active", None, ["2026-10-20"], date(2026, 10, 16)) == 0


def test_availability_regression():
    a = VV.availability([(82, 82), (82, 82)], 0.8)
    b = VV.availability([(41, 82), (41, 82)], 0.8)
    assert 0.9 < a <= 1.0 and 0.5 < b < 0.6
    assert VV.availability([], 0.8) == pytest.approx(0.8)


def _vr_synth(n=300, seasons=(20212022, 20222023, 20232024, 20242025, 20252026), seed=3):
    rng = np.random.default_rng(seed)
    talent = rng.normal(0.05, 0.12, n)
    out = {}
    for j, s in enumerate(seasons):
        rows = []
        for i in range(n):
            age = 20 + (i % 18) + j
            if age > 37 and rng.random() < 0.6:
                continue
            toi = float(rng.uniform(200, 1600))
            rate = talent[i] + rng.normal(0, math.sqrt(0.07 * 60 / toi))
            pos = "CLRD"[i % 4]
            rows.append({"id": str(i), "kind": "S", "pos": pos, "team": f"T{i % 32}", "age": float(age), "toi": toi, "gp": int(toi / 15),
                         "gar": rate * toi / 60, "rate": rate, "war": rate * toi / 60 / 6})
        out[s] = {"rows": rows, "team_games": 82, "gpw": 6.0, "n_teams": 32}
    return out


def test_fits_on_synthetic_seasons():
    vr = _vr_synth()
    comp = sorted(vr)
    rel = VV.reliability(vr, comp, None)["S"]
    assert 0.03 < rel["sigma2"] < 0.15                  # planted noise 0.07 per 60 minutes
    assert rel["tau2"] == pytest.approx(0.0144, abs=0.008)
    sv = VV.survival_fit(vr, comp)["S"]
    assert sv["coef"] is not None and sv["n"] > 500
    assert VV.survival_p(sv, 38.0, 0.0, 15.0, "S") < VV.survival_p(sv, 26.0, 0.0, 15.0, "S")
    pos = VV.positional(vr, comp)["positions"]
    assert set(pos) == {"C", "L", "R", "D", "G"}
    assert pos["C"]["starter"] >= pos["C"]["repl"]


# ---------------------------------------------------------------------------------------------- fantasy

def _season_logs(season=20252026, n_games=40, seed=7):
    """Two clubs playing each other n_games times; club A's skater 1 shoots twice as much as everyone."""
    rng = np.random.default_rng(seed)
    y = season // 10000
    d0 = date(y, 10, 8)
    sk, gk, tg = [], [], []
    for g in range(n_games):
        gid = int(f"{y}02{g + 1:04d}")
        d = (d0 + timedelta(days=2 * g)).isoformat()
        for team, opp, home in (("AAA", "BBB", 1), ("BBB", "AAA", 0)):
            for k in range(6):
                pid = (1 if team == "AAA" else 101) + k
                strong = pid == 1
                toi = 20.0 if strong else 15.0
                ixg = (0.6 if strong else 0.2) * rng.uniform(0.8, 1.2)
                sk.append({"season": season, "game_id": gid, "date": d, "gt": "R", "team": team, "opp": opp, "home": home, "pid": pid,
                           "pos": "D" if k >= 4 else "C", "toi": toi, "toipp": 3.0 if strong else 1.0, "toipk": 1.0, "g": int(rng.random() < ixg),
                           "a": int(rng.random() < 0.3), "pm": int(rng.integers(-1, 2)), "pim": 0, "hits": int(rng.integers(0, 3)), "blk": int(rng.integers(0, 2)),
                           "sog": int(rng.integers(1, 5)), "ppg": 0, "ppp": int(rng.random() < (0.3 if strong else 0.05)), "app": 0, "gpp": 0, "g5": 0,
                           "a5": int(rng.random() < 0.2), "ixg": ixg, "iff": 3, "xgf5": 0.8, "xga5": 0.7, "gf5": int(rng.random() < 0.5),
                           "ga5": 0, "toi5": toi - 4, "ixg_pp": ixg * 0.3, "ixg_es": ixg * 0.7})
            starter = (1001 if team == "AAA" else 2001) + (1 if g % 4 == 3 else 0)
            ga = int(rng.integers(0, 5))
            gk.append({"season": season, "game_id": gid, "date": d, "gt": "R", "team": team, "opp": opp, "home": home, "pid": starter, "toi": 60.0,
                       "sa": 30, "sv": 30 - ga, "ga": ga, "dec": "W" if (g + home) % 2 else "L", "start": 1, "xga": 2.8, "ga_x": float(ga)})
            tg.append({"season": season, "game_id": gid, "date": d, "gt": "R", "team": team, "opp": opp, "home": home, "gf": 3, "ga": 2, "win": home,
                       "ot": 0, "p_win": 0.55 if home else 0.45, "xgf": 3.0, "xga": 2.8, "sf": 30.0, "sa": 30.0})
    return {"sk": pd.DataFrame(sk), "gk": pd.DataFrame(gk), "tg": pd.DataFrame(tg)}


def _logs2():
    a, b = _season_logs(20242025, seed=1), _season_logs(20252026, seed=2)
    return {k: pd.concat([a[k], b[k]], ignore_index=True) for k in a}


def test_skater_projection_categories_and_weights():
    L = _logs2()
    P_ = FA.project_at(L, "2026-01-01", 20252026)
    sr = P_["sr"]
    assert sr.loc[1, "toi_w"] > sr.loc[2, "toi_w"]
    cats = {k: v for k, v in FA.skater_cats(sr.loc[[1, 2]]).items()}
    assert set(cats) == set(FA.CATS_S)
    assert cats["g"][0] > cats["g"][1] and cats["ppp"][0] > cats["ppp"][1]
    assert sr.loc[1, "pp_unit"] == 1
    # an opponent that concedes more raises the scoring categories, not hits
    harder = FA.skater_cats(sr.loc[[1]], 1.2, 1.1, 1.0)
    assert harder["g"][0] == pytest.approx(cats["g"][0] * 1.2) and harder["hit"][0] == pytest.approx(cats["hit"][0])
    pts = FA.points({"g": 1.0, "a": 1.0, "sog": 2.0})
    assert pts == pytest.approx(FA.DEFAULT_POINTS["g"] + FA.DEFAULT_POINTS["a"] + 2 * FA.DEFAULT_POINTS["sog"])
    assert FA.points({"g": 1.0}, {"g": 5.0}) == 5.0


def test_goalie_starts_and_back_to_backs():
    sh = FA.start_probs([(1, 0.75), (2, 0.25)], False, 0.5)
    assert sum(sh.values()) == pytest.approx(1.0) and sh[1] == pytest.approx(0.75)
    b2b = FA.start_probs([(1, 0.75), (2, 0.25)], True, 0.5)
    assert b2b[1] == pytest.approx(0.375) and b2b[2] == pytest.approx(0.625)
    out = FA.start_probs([(1, 0.75), (2, 0.25)], False, 0.5, {1})
    assert out == {2: pytest.approx(1.0)}
    L = _logs2()
    gr = FA.goalie_rates(L["gk"], L["tg"], 20252026)
    assert gr.loc[1001, "share"] > gr.loc[1002, "share"]
    g = FA.goalie_game({"talent": 0.05}, {"xga_pg": 3.0, "sa_pg": 30.0}, {"off_x": 1.0, "off_s": 1.0}, 0.6, 1.0)
    assert g["w"] == pytest.approx(0.6 * FA.DECISION) and g["ga"] == pytest.approx(2.85) and g["so"] == pytest.approx(math.exp(-2.85))


def test_tiers_replacement_and_z():
    vals = [100, 99.9, 99.8, 80, 79.9, 79.8, 79.7, 50, 49.9, 49.8] + [10 - 0.01 * i for i in range(30)]
    t = FA.tiers(vals, pool=40)
    assert t[0] == t[2] and t[3] > t[2] and t[3] == t[6] and t[7] > t[6] and t[10] > t[9]
    assert all(a <= b for a, b in zip(t, t[1:]))
    players = [{"id": str(i), "pos": "CLRDG"[i % 5], "ros": 300 - i} for i in range(300)]
    rep = FA.replacement(players)
    assert set(rep) == {"C", "L", "R", "D", "G"}
    drafted = sum(FA.ROSTER.values()) * FA.N_TEAMS
    assert drafted == 204
    assert all(0 < v < 300 for v in rep.values())
    z = FA.zscores([{"id": "a", "ros": 10, "g": 2, "ga": 1}, {"id": "b", "ros": 5, "g": 1, "ga": 3}], ["g", "ga"], 10)
    assert z["a"] > z["b"]                                    # fewer goals against is better


def test_backtest_metrics_and_checkpoint():
    assert FA.wmae(np.array([1.0, 2.0]), np.array([2.0, 2.0]), np.array([1.0, 3.0])) == pytest.approx(0.25)
    assert FA.spearman(np.arange(6), np.arange(6) ** 2) == pytest.approx(1.0)
    assert FA.spearman(np.arange(3), np.arange(3)) is None
    L = _logs2()
    r = FA._checkpoint(L, 20252026, "2025-12-01", "2026-03-01")
    for key in (("S", "week"), ("S", "ros")):
        assert key in r
        for cat in ("pts", "g", "sog"):
            m = r[key][cat]
            assert m["model"][0] is not None and m["std"][0] is not None and m["last"][0] is not None
    bt = FA.backtest(L, [20252026], step_days=14)
    assert bt["ok"] and bt["checkpoints"] > 0
    assert {row[3] for row in bt["rows"]} == {"model", "std", "last"}
    s = FA.backtest_summary(bt)
    assert "S_ros" in s["pts"]
