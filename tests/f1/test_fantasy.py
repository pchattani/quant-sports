"""The fantasy layer (docs/VALUE_SECTIONS.md section 5; analytics/fantasy.py): the scoring table, projection arithmetic on
toy simulated weekends, value-pick ranking, the backtest metrics and the payload shape, plus the projection and backtest on
the synthetic season (no network)."""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.f1.analytics import fantasy as FT

from .conftest import YEAR


def test_scoring_table_primitives():
    assert [FT.quali_points(p) for p in (1, 2, 10, 11, None)] == [10, 9, 1, 0, 0]
    assert [FT.finish_points(p) for p in (1, 2, 3, 10, 11)] == [25, 18, 15, 1, 0]
    assert [FT.finish_points(p, sprint=True) for p in (1, 8, 9)] == [8, 1, 0]
    assert (FT.q2_cut(20), FT.q2_cut(22), FT.q2_cut(24), FT.q2_cut(10)) == (15, 16, 17, 10)
    assert [FT.q_bonus(*x) for x in ((2, 2), (2, 1), (2, 0), (1, 0), (0, 0))] == [10, 5, 3, 1, -1]
    assert [FT.pit_points(s) for s in (1.9, 2.0, 2.19, 2.3, 2.6, 3.0, None)] == [20, 10, 10, 5, 2, 0, 0]


def test_actual_rows_gain_dnf_dsq_and_pit_lane():
    rows = [{"driver": "a", "grid": 3, "position": 1, "position_text": "1", "status": "Finished", "fastest_rank": 1},
            {"driver": "b", "grid": 0, "position": 2, "position_text": "2", "status": "+1 Lap"},           # pit-lane start = last slot (4)
            {"driver": "c", "grid": 1, "position": 3, "position_text": "R", "status": "Engine"},
            {"driver": "d", "grid": 2, "position": 4, "position_text": "D", "status": "Disqualified", "fastest_rank": 1}]
    r = FT._session_rows(rows, sprint=False)
    assert r["a"]["c"] == {"race_pos": 25, "race_gain": 2, "race_fl": 10, "race_dnf": 0}
    assert r["b"]["c"]["race_gain"] == 2 and r["b"]["c"]["race_pos"] == 18
    assert r["c"]["c"] == {"race_pos": 0, "race_gain": 0, "race_fl": 0, "race_dnf": -20}
    assert r["d"]["c"]["race_dnf"] == -20 and r["d"]["c"]["race_fl"] == 0          # disqualified: nothing else
    s = FT._session_rows(rows, sprint=True)
    assert s["a"]["c"]["sprint_pos"] == 8 and s["a"]["c"]["sprint_fl"] == 5 and s["c"]["c"]["sprint_dnf"] == -10
    q = FT._quali_rows({"qualifying": [{"driver": "a", "position": 1, "q1": 1, "q2": 1, "q3": 1},
                                       {"driver": "b", "position": 12, "q1": 1, "q2": 1, "q3": None},
                                       {"driver": "c", "position": 20, "q1": None, "q2": None, "q3": None}]})
    assert (q["a"]["pts"], q["a"]["q3"], q["b"]["q2"], q["b"]["q3"], q["c"]["pts"]) == (10, True, True, False, FT.Q_NC)


def test_expected_points_from_a_toy_distribution():
    assert FT.expected_from_dist([0.5, 0.3, 0.2]) == pytest.approx(0.5 * 25 + 0.3 * 18 + 0.2 * 15)
    # two simulated races, three cars: positions, grid slots, classification and the fastest-lap car
    slot = np.array([[1, 2, 3], [2, 1, 3]])
    pos = np.array([[1, 3, 2], [3, 1, 2]])
    cls = np.array([[True, True, True], [False, True, True]])
    fl = np.array([0, 1])
    sc = FT.score_session(slot, pos, cls, fl)
    assert sc["pos"].tolist() == [[25, 15, 18], [0, 25, 18]]
    assert sc["gain"].tolist() == [[0, -1, 1], [0, 0, 1]]
    assert sc["fl"].tolist() == [[10, 0, 0], [0, 10, 0]] and sc["dnf"].tolist() == [[0, 0, 0], [-20, 0, 0]]
    s = {"drivers": ["a", "b", "c"], "slot": slot, "pos": pos, "cls": cls, "fl": fl}
    wp = FT.weekend_points(s, None, ["a", "b", "c"], ["T1", "T2"], {"a": "T1", "b": "T1", "c": "T2"}, n=2)
    # driver a: quali 10 + 25 + 10 (sim 1); quali 9 - 20 (sim 2)
    assert wp["total"][:, 0].tolist() == [45, -11]
    sm = FT.summarise(wp, ["a", "b", "c"], ["T1", "T2"])
    assert sm["drivers"]["a"]["mean"] == pytest.approx(17.0) and sm["drivers"]["a"]["p_dnf"] == pytest.approx(0.5)
    assert sm["drivers"]["a"]["p_front"] == 1.0
    # constructors: both drivers plus qualifying progression (field of 3: Q2 = top 3, Q3 = top 10, both in Q3 = +10)
    assert wp["team"][:, 0].tolist() == pytest.approx((wp["total"][:, 0] + wp["total"][:, 1] + 10).tolist())
    # an actual qualifying result replaces the simulated one
    wk = FT.weekend_points(s, None, ["a", "b", "c"], ["T1", "T2"], {"a": "T1", "b": "T1", "c": "T2"},
                           known={"quali": {"a": {"pos": 3, "pts": 8, "q2": True, "q3": True}}}, n=2)
    assert wk["comp"]["quali"][:, 0].tolist() == [8, 8] and wk["comp"]["quali"][:, 1].tolist() == [0, 0]


def test_overtake_and_pit_models():
    rows = [(f"2025_{r}", "c1" if r % 2 else "c2", d, g, 0, 1, ov) for r in range(1, 7) for d, g, ov in (("a", 3, 6), ("b", 0, 2), ("c", 1, 4))]
    m = FT.OvertakeModel.fit(rows)
    assert m is not None and m.races == 6 and m.coef[1] > 0                       # places gained bring passes
    lam = m.lam(["a", "b"], "c1", np.array([[5, 1]]), np.array([[1, 1]]), np.array([[True, True]]))
    assert lam[0, 0] > lam[0, 1] > 0
    assert FT.OvertakeModel.fit(rows[:6]) is None                                  # fewer than three races
    aw = {"year": 2026, "round": 1, "has_pit": True, "teams": {"T1": {"best_stop_s": 1.9, "fastest": True}, "T2": {"best_stop_s": 2.6, "fastest": False}}}
    pm = FT.PitModel.fit([aw, dict(aw, round=2)], 2026)
    assert pm.expected("T1") > pm.expected("T2") and pm.expected("new") == pytest.approx(pm.expected("__field__"))
    assert FT.PitModel.fit([dict(aw, has_pit=False)], 2026) is None


def test_metrics_spearman_mae_and_coverage():
    assert FT.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert FT.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert FT.spearman([1, 1, 1], [1, 2, 3]) is None
    assert FT.top_overlap({"a": 3, "b": 2, "c": 1}, {"a": 1, "b": 3, "c": 2}, k=2) == pytest.approx(0.5)
    m = FT.score_method([({"a": 10, "b": 0, "c": 5}, {"a": 12, "b": 1, "c": 3})], k=2)
    assert m["mae"] == pytest.approx(5 / 3, abs=1e-3) and m["bias"] == pytest.approx(-1 / 3, abs=1e-3)
    assert m["spearman"] == pytest.approx(1.0) and m["top_pick"] == 12
    assert FT.coverage([(0, 10, 5), (0, 10, 11)]) == 0.5


def test_tiers_form_line_and_picks():
    t = FT.tiers({"a": 30, "b": 29, "c": 20, "d": 19, "e": 5}, k=3)
    assert t == {"a": 1, "b": 1, "c": 2, "d": 2, "e": 3}
    assert FT.form_line([10, 20], 30) == pytest.approx((2 * 15 + 3 * 30) / 5)
    assert FT.form_line([], 7.0) == 7.0 and FT.form_line([4.0], None) == 4.0
    rows = {}
    for i, (nx, price, ros) in enumerate([(30, 32, 29), (25, 20, 26), (20, 21, 20), (18, 10, 19), (12, 15, 11), (8, 9, 8), (3, -6, 4), (2, 1, 2)]):
        d = f"d{i}"
        rows[d] = {"id": d, "team": "T", "next": nx, "price": price, "value": nx - price, "ros_per": ros, "value_ros": ros - price, "p10": nx - 15,
                   "p90": nx + 15, "car_trend": 0.0, "luck": 0}
    for i, price in enumerate((25, 24, 23, 22)):                     # four expensive midfielders: the price top five
        rows[f"e{i}"] = {"id": f"e{i}", "team": "U", "next": 10, "price": price, "value": 10 - price, "ros_per": 10, "value_ros": 10 - price,
                         "p10": -5, "p90": 25, "car_trend": 0.0, "luck": 0}
    ranks = FT.rank_of({d: r["next"] for d, r in rows.items()})
    pranks = FT.rank_of({d: r["price"] for d, r in rows.items()})
    for d, r in rows.items():
        r.update(rank_next=ranks[d], price_rank=pranks[d], form_rank=pranks[d], pace_rank=ranks[d])
    p = FT.suggest(rows, {}, {})
    assert [x["id"] for x in p["top"]] == ["d0", "d1", "d2", "d3", "d4"] and p["boost"]["id"] == "d0"
    # value: projection over the form line among drivers who score (d6's +9 against a -6 form line is a backmarker reverting)
    assert p["value"][0]["id"] == "d3" and "d6" not in [x["id"] for x in p["value"]]
    assert p["value"][0]["why"] and "form line" in p["value"][0]["why"][0]
    assert all(x["id"] != "d6" for x in p["risers"])
    assert p["fades"] and p["fades"][0]["id"] == "e0"                     # form line far above the projection


def test_payload_shape_on_a_toy_projection():
    proj = {"ok": True, "n": 10, "next": {"round": 4, "name": "Test GP", "sprint": False}, "rounds": [[4, "Test GP", False], [5, "Next GP", True]],
            "lineup": {"a": "T1", "b": "T1"},
            "drivers": {d: {"team": "T1", "next": {"mean": m, "p10": m - 10, "p90": m + 10, "p_q3": 0.5, "p_front": 0.2, "p_dnf": 0.1, "p_fl": 0.05,
                                                  "exp_qpos": 5, "comp": {k: 1.0 for k in FT.DCOMP}},
                            "ros": 2 * m, "ros_p10": m, "ros_p90": 3 * m, "rounds_left": 2, "schedule": [m, m]} for d, m in (("a", 20.0), ("b", 10.0))},
            "teams": {"T1": {"next": {"mean": 40.0, "p10": 20, "p90": 60, "drivers": 30, "q_bonus": 5, "pit": 5}, "ros": 80, "ros_p10": 50, "ros_p90": 110,
                             "rounds_left": 2, "schedule": [40, 40]}},
            "models": {"overtakes": None, "pit": {"races": 3}}}
    aw = {"has_race": True, "drivers": {"a": {"team": "T1", "c": {"quali": 10, "race_pos": 25}, "started": True}, "b": {"team": "T1", "c": {"quali": 9}, "started": True}},
          "teams": {"T1": {"drivers": ["a", "b"], "q_bonus": 10, "pit": None}}}
    pay = FT.fantasy_payload(YEAR, proj, {1: aw}, {}, None, None)
    assert pay["ok"] and pay["projection_ok"] and pay["driver_cols"] == FT.DRIVER_COLS and pay["team_cols"] == FT.TEAM_COLS
    rows = {r[0]: dict(zip(pay["driver_cols"], r)) for r in pay["drivers"]}
    assert rows["a"]["next"] == 20.0 and rows["a"]["form"] == 35.0 and rows["a"]["price"] == 35.0 and rows["a"]["value"] == -15.0
    assert rows["a"]["ros_per"] == 20.0 and rows["a"]["tier"] == 1
    assert pay["history"]["drivers"]["a"] == [35.0] and pay["history"]["teams"]["T1"] == [54.0]
    assert pay["schedule"]["rounds"][1] == [5, "Next GP", True] and pay["schedule"]["drivers"]["a"] == [20.0, 20.0]
    assert set(pay["picks"]) >= {"top", "boost", "value", "differentials", "risers", "fades", "constructors"}
    assert len(pay["comp"]["a"]) == len(FT.DCOMP) and pay["scoring"] and pay["excluded"]
    assert "not used" in pay["label"].lower() or "not the official" in pay["label"].lower()
    off = FT.fantasy_payload(YEAR, {"ok": False, "reason": "no rounds left"}, {1: aw}, {}, None, None)
    assert off["ok"] and not off["projection_ok"] and off["reason"] == "no rounds left" and off["picks"] == {}


def test_projection_and_backtest_on_the_synthetic_season(paddock_data):
    aw = FT.actual_weekend(YEAR, 1)
    assert aw["has_race"] and aw["drivers"]["drv0"]["c"]["quali"] == 10
    assert set(aw["teams"]) == {f"team{j}" for j in range(5)}
    pr = FT.season_projection(YEAR, n=200)
    assert pr["ok"], pr.get("reason")
    assert pr["next"]["round"] == 4 and [r[0] for r in pr["rounds"]] == [4, 5]
    d0 = pr["drivers"]["drv0"]
    assert d0["rounds_left"] == 2 and d0["next"]["p10"] <= d0["next"]["mean"] <= d0["next"]["p90"]
    assert d0["ros"] == pytest.approx(sum(d0["schedule"]), rel=1e-6, abs=1e-3)
    assert pr["drivers"]["drv0"]["next"]["mean"] > pr["drivers"]["drv9"]["next"]["mean"]     # the fastest car scores more
    bt = FT.backtest([YEAR - 1, YEAR], n=60)
    assert bt["ok"] and bt["races"] >= 6 and bt["metrics"]["drivers_core"]["model"]["n"] > 0
    assert set(bt["metrics"]["drivers_core"]) == {"model", "std", "prev", "last", "blend"}
    again = FT.backtest([YEAR - 1, YEAR], n=60)
    assert again["new"] == 0 and again["metrics"]["drivers_core"]["model"]["mae"] == bt["metrics"]["drivers_core"]["model"]["mae"]
    pay = FT.backtest_payload(bt)
    assert pay["ok"] and pay["per_race_cols"][0] == "year" and pay["baselines"]["std"]
