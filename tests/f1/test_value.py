"""Driver value, constructors' strengths and needs and the driver-swap simulator (docs/VALUE_SECTIONS.md): the seat
swap of the race inputs, sign conventions and sample floors of the value page, grading and swap ranking, and the swap
table on the synthetic season (no network)."""
from __future__ import annotations

import math

import pytest

from oddsmarkets.f1.analytics import value as VL
from oddsmarkets.f1.models.race_sim import RaceInputs

from .conftest import YEAR


def _inp(session="race"):
    drivers = ["a", "b", "c", "d"]
    return RaceInputs(year=2030, round=5, drivers=drivers, team={"a": "T1", "b": "T1", "c": "T2", "d": "T2"},
                      pace_mu={"a": -1.0, "b": -0.8, "c": 0.5, "d": 0.7}, pace_sd={d: 0.2 for d in drivers}, grid=None,
                      dnf_hazard={d: 0.001 for d in drivers}, circuit={"laps": 50, "sprint_laps": 17}, session=session,
                      grid_strength={"a": -1.2, "b": -1.0, "c": 0.4, "d": 0.6},
                      grid_dist={"a": [0.6, 0.3, 0.1, 0.0], "b": [0.3, 0.5, 0.2, 0.0], "c": [0.1, 0.1, 0.5, 0.3], "d": [0.0, 0.1, 0.2, 0.7]},
                      ref_lap_s=90.0, meta={"dnf_split": {"a": {"mech": 0.02, "incident": 0.01}, "b": {"mech": 0.02, "incident": 0.05},
                                                          "c": {"mech": 0.10, "incident": 0.03}, "d": {"mech": 0.10, "incident": 0.02}}})


def test_swap_events_moves_the_seat_and_keeps_the_driver():
    eff = {"a": -0.10, "c": 0.05}                     # a is 0.15% of a lap faster than c relative to their team-mates
    (rnd, kind, new), = VL.swap_events([(5, "race", _inp())], "a", "c", eff)
    k = 0.9                                           # 90 s / 100
    assert new.team["a"] == "T2" and new.team["c"] == "T1" and new.team["b"] == "T1"
    assert new.pace_mu["a"] == pytest.approx(0.5 + (-0.10 - 0.05) * k)      # c's seat, plus the driver difference
    assert new.pace_mu["c"] == pytest.approx(-1.0 + (0.05 + 0.10) * k)
    assert new.pace_mu["b"] == -0.8 and new.pace_mu["d"] == 0.7
    assert new.grid_dist["a"] == [0.1, 0.1, 0.5, 0.3] and new.grid_strength["c"] == -1.2
    # retirement: the seat's mechanical share with the driver's own incident share
    assert new.dnf_hazard["a"] == pytest.approx(-math.log(1 - (0.10 + 0.01)) / 50)
    assert new.dnf_hazard["c"] == pytest.approx(-math.log(1 - (0.02 + 0.03)) / 50)
    assert new.dnf_hazard["b"] == 0.001
    # team-mates are not swapped; a sprint uses the sprint distance
    (_, _, same), = VL.swap_events([(5, "race", _inp())], "a", "b", eff)
    assert same.pace_mu == _inp().pace_mu
    (_, _, spr), = VL.swap_events([(5, "sprint", _inp("sprint"))], "a", "c", eff)
    assert spr.dnf_hazard["a"] == pytest.approx(-math.log(1 - 0.11) / 17)


def _effects():
    car = {"T1": [{"round": 1, "effect": -0.5, "se": 0.2, "observed": True}, {"round": 6, "effect": -0.7, "se": 0.2, "observed": True}],
           "T2": [{"round": 1, "effect": 0.3, "se": 0.2, "observed": True}, {"round": 6, "effect": 0.2, "se": 0.2, "observed": True}]}
    return {"car": car, "quali_car": car,
            "driver": {"a": {"effect": -0.1, "se": 0.15, "races": 6}, "b": {"effect": 0.1, "se": 0.15, "races": 6},
                       "c": {"effect": 0.02, "se": 0.15, "races": 6}, "d": {"effect": -0.02, "se": 0.3, "races": 2}},
            "quali_driver": {"a": {"effect": -0.05, "se": 0.1, "races": 6}}, "params": {}}


def test_value_payload_signs_floors_and_ranking():
    dcat = {"drivers": {d: {"name": d.upper(), "team": t, "values": {"points": 10.0, "elo_teammate": 1500}} for d, t in
                        (("a", "T1"), ("b", "T1"), ("c", "T2"), ("d", "T2"))}}
    prev = {"driver": {"a": {"effect": 0.0, "races": 10}}}
    v = VL.value_payload(2030, _effects(), prev, dcat, {"teams": {"T1": {"name": "Team 1"}}}, None, True)
    rows = {r[0]: dict(zip(v["driver_cols"], r)) for r in v["drivers"]}
    assert rows["a"]["pace_tm"] == pytest.approx(0.1) and rows["a"]["quali_tm"] == pytest.approx(0.05)    # positive = faster
    assert rows["a"]["pace_field"] == pytest.approx(0.7 + 0.1)              # the car's LATEST state plus the driver
    assert rows["a"]["trend"] == pytest.approx(0.1)
    assert rows["d"]["pct"] is None and rows["a"]["pct"] == 100            # under five races: no percentile
    assert v["best"]["pace_tm"][0] == "a" and "d" not in v["best"]["pace_tm"]
    teams = [dict(zip(v["team_cols"], r)) for r in v["teams"]]
    assert [t["id"] for t in teams] == ["T1", "T2"] and teams[0]["car"] == pytest.approx(0.7) and teams[0]["rank"] == 1
    assert teams[0]["trend"] == pytest.approx(0.2)                         # T1 got 0.2% of a lap faster
    assert teams[0]["car_mean"] == pytest.approx(0.6)


def test_needs_grades_and_swap_ranking():
    table = {"ok": True, "n": 100, "lineup": {"a": "T1", "b": "T1", "c": "T2", "d": "T2"},
             "pairs": {"a|c": [5, 0, 0, -5, 0, 0, -8.0, -0.1, 8.0, 0.1], "a|d": [1, 0, 0, -1, 0, 0, -2.0, 0, 2.5, 0.0],
                       "b|c": [0, 0, 0, 0, 0, 0, 1.0, 0, -1.0, 0], "b|d": [0, 0, 0, 0, 0, 0, 0.5, 0, -0.5, 0]}}
    sw = VL.team_swaps("T2", table, {})
    assert [(s["in"], s["out"]) for s in sw] == [("a", "c"), ("a", "d"), ("b", "d"), ("b", "c")]
    assert sw[0]["gain_pts"] == 8.0 and sw[0]["other_change"] == -8.0 and sw[0]["from"] == "T1"
    tcat = {"teams": {"T1": {"name": "One", "values": {"car_race_pace": -0.7, "dnf_mech": 0, "pit_stop_ms": 2400},
                             "pct": {"car_race_pace": 100, "dnf_mech": 85, "pit_stop_ms": 10}},
                      "T2": {"name": "Two", "values": {"car_race_pace": 0.2, "dnf_mech": 3, "pit_stop_ms": 2300},
                             "pct": {"car_race_pace": 0, "dnf_mech": 15, "pit_stop_ms": 90}}}}
    dcat = {"drivers": {"a": {"team": "T1", "values": {"elo_teammate": 1600}}, "b": {"team": "T1", "values": {"elo_teammate": 1560}},
                        "c": {"team": "T2", "values": {"elo_teammate": 1450}}, "d": {"team": "T2", "values": {"elo_teammate": 1470}}}}
    n = VL.needs_payload(2030, tcat, dcat, table, {})
    t2 = n["teams"]["T2"]
    assert [a["key"] for a in t2["weaknesses"]] == ["race_pace", "drivers", "reliability"]
    assert {a["key"]: a["grade"] for a in t2["areas"]} == {"race_pace": "F", "reliability": "F", "pit": "A", "drivers": "F"}
    imp = {w["key"]: w for w in t2["improve"]}
    assert imp["drivers"]["swaps"][0]["in"] == "a" and imp["race_pace"]["swaps"] == [] and "no market" in imp["race_pace"]["note"]
    assert "contracts" in n["label"]


def test_needs_reliability_falls_back_to_every_retirement_when_causes_are_unpublished():
    """Round 9: since 2023 the feed says only "Retired", so dnf_mech is 0 for every team and graded every team 50.
    With no mechanical cause anywhere but retirements in the field, Reliability reads dnf_rate and says so."""
    tcat = {"teams": {"T1": {"name": "One", "values": {"dnf_mech": 0, "dnf_rate": 0.05, "dnfs": 2}, "pct": {"dnf_mech": 50, "dnf_rate": 100}},
                      "T2": {"name": "Two", "values": {"dnf_mech": 0, "dnf_rate": 0.4, "dnfs": 12}, "pct": {"dnf_mech": 50, "dnf_rate": 0}}}}
    n = VL.needs_payload(2030, tcat, {"drivers": {}}, {"ok": False}, {})
    rel = {t: [a for a in n["teams"][t]["areas"] if a["key"] == "reliability"][0] for t in ("T1", "T2")}
    assert rel["T1"]["metric"] == "dnf_rate" and rel["T1"]["pct"] == 100 and rel["T2"]["pct"] == 0
    assert "any cause" in rel["T1"]["stat"]
    tcat["teams"]["T2"]["values"]["dnf_mech"] = 3                        # a published cause: the mechanical count again
    tcat["teams"]["T2"]["pct"]["dnf_mech"] = 0
    n = VL.needs_payload(2030, tcat, {"drivers": {}}, {"ok": False}, {})
    assert [a for a in n["teams"]["T2"]["areas"] if a["key"] == "reliability"][0]["metric"] == "dnf_mech"


def test_swap_table_on_the_synthetic_season(paddock_data):
    from oddsmarkets.f1.models.decomposition import season_effects
    eff = season_effects(YEAR)
    cache = paddock_data[1] / "swaps"
    t = VL.swap_table(YEAR, eff, n=120, cache_dir=cache)
    assert t["ok"] and t["cols"] == VL.SWAP_COLS
    lineup = t["lineup"]
    assert len(lineup) == 10 and len(t["pairs"]) == 45 - 5                 # every pair on different teams
    # the fastest driver (drv0, team0) into the slowest car (team4, drv9's seat): the drivers' points follow the car,
    # while each team keeps most of its own (the seat carries the pace; only the small driver difference moves)
    v = dict(zip(t["cols"], t["pairs"]["drv0|drv9"]))
    assert v["a_pts"] < 0 < v["b_pts"]
    assert abs(v["ta_pts"]) < 0.5 * abs(v["a_pts"]) and abs(v["tb_pts"]) < 0.5 * abs(v["b_pts"])
    again = VL.swap_table(YEAR, eff, n=120, cache_dir=cache)
    assert again.get("cached") and again["pairs"] == t["pairs"]
    pay = VL.swap_payload(YEAR, t, None, {"drv0": "Driver Zero"})
    assert pay["ok"] and pay["names"]["drv0"] == "Driver Zero" and pay["pairs"]
