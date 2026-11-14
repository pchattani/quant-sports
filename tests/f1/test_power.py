"""The Paddock's power rankings adapter (oddsmarkets/f1/analytics/power_build.py) on a small synthetic data tree."""
import json
from pathlib import Path

import pytest

from oddsmarkets.f1.analytics import power_build as PB

Y = 2031
# field Elo after rounds 1..3 (the career files) and now (season.json, = round 3)
ELO = {"a": [1600.0, 1590.0, 1580.0], "b": [1500.0, 1560.0, 1620.0], "c": [1550.0, 1550.0, 1540.0], "d": [1450.0, 1460.0, 1470.0]}
TEAM = {"a": "t0", "b": "t0", "c": "t1", "d": "t1"}


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _tree(root: Path, finished: bool = False, clinched: bool = False):
    ids = list(ELO) + ["x"]                                       # x: a one-race stand-in, below the peer floor
    _w(root / "index.json", {"current_season": Y, "seasons": [Y],
                             "drivers": {d: {"name": f"Driver {d.upper()}", "code": d.upper() * 3, "team": TEAM.get(d, "t1")} for d in ids},
                             "teams": {"t0": {"name": "Team Zero", "colour": "#ff0000"}, "t1": {"name": "Team One F1 Team", "colour": "#0000ff"}}})
    cal = [{"round": r, "name": f"Grand Prix {r}", "date": f"{Y}-03-0{r}", "status": "done", "winner": "b" if r == 3 else "a",
            "winner_team": "t0"} for r in (1, 2, 3)]
    cal += [{"round": r, "name": f"Grand Prix {r}", "date": f"{Y}-03-0{r}", "status": "upcoming"} for r in (4, 5)]
    if finished:
        cal = cal[:3]
    stand_d = [{"pos": i + 1, "driver": d, "team": TEAM.get(d, "t1"), "points": 50 - 10 * i, "wins": 1 if d in ("a", "b") else 0}
               for i, d in enumerate(["b", "a", "c", "d", "x"])]
    stand_t = [{"pos": 1, "team": "t0", "points": 90, "wins": 3}, {"pos": 2, "team": "t1", "points": 30, "wins": 0}]
    champ = {"drivers": {d: {"p_title": 0.6 if d == "b" else 0.4 if d == "a" else 0.0, "clinched": False, "eliminated": d not in ("a", "b")} for d in ids},
             "constructors": {"t0": {"p_title": 1.0, "clinched": clinched}, "t1": {"p_title": 0.0, "eliminated": True}}}
    _w(root / str(Y) / "season.json", {
        "ok": True, "year": Y, "updated_at": f"{Y}-03-04T00:00:00Z", "rounds_done": 3, "rounds_total": 3 if finished else 5,
        "finished": finished, "calendar": cal, "standings": {"drivers": stand_d, "constructors": stand_t},
        "championship": None if finished else champ, "names": {d: f"Driver {d.upper()}" for d in ids},
        "teams": {"t0": {"name": "Team Zero", "colour": "#ff0000", "drivers": ["a", "b"]}, "t1": {"name": "Team One F1 Team", "colour": "#0000ff", "drivers": ["c", "d", "x"]}},
        "elo": {**{d: {"elo": v[-1], "elo_teammate": 1500 + i, "elo_quali": 1700 - 10 * i} for i, (d, v) in enumerate(ELO.items())},
                "x": {"elo": 1400.0, "elo_teammate": 1500.0, "elo_quali": 1400.0}}})
    drivers = {}
    for i, d in enumerate(ELO):
        drivers[d] = {"name": f"Driver {d.upper()}", "code": d.upper() * 3, "team": TEAM[d], "races": 3, "qualified": True,
                      "values": {"driver_effect": -0.1 * (i - 1.5), "avg_quali": 2 + i, "poles": 3 - i, "q3_rate": 1.0, "quali_h2h": 0.5,
                                 "avg_finish": 2 + i, "points": 50 - 10 * i, "pos_gained": 0.5, "net_overtakes": 1.0,
                                 "race_h2h": 0.5, "team_points_share": 0.5},
                      "log": [{"round": r, "pos": (1 if (d == "a" and r < 3) or (d == "b" and r == 3) else 2 + i), "status": "Finished",
                               "points": 10, "team": TEAM[d]} for r in (1, 2, 3) if not (d == "d" and r == 2)]}
    drivers["x"] = {"name": "Driver X", "team": "t1", "races": 1, "qualified": False, "values": {}, "log": [{"round": 2, "pos": 15, "status": "Retired", "points": 0, "team": "t1"}]}
    _w(root / str(Y) / "drivers.json", {"ok": True, "peer_floor": 2, "drivers": drivers})
    _w(root / str(Y) / "teams.json", {"ok": True, "teams": {
        "t0": {"name": "Team Zero", "values": {"car_pace_latest": -0.5}, "log": [{"round": r, "drivers": ["a", "b"]} for r in (1, 2, 3)]},
        "t1": {"name": "Team One", "values": {"car_pace_latest": 0.5},
               "log": [{"round": r, "drivers": ["c", "x" if r == 2 else "d"]} for r in (1, 2, 3)]}}})
    for d, v in ELO.items():
        _w(root / "drivers" / f"{d}.json", {"elo": [[Y - 1, 20, 1500.0, 1500.0]] + [[Y, r + 1, e, 1500.0] for r, e in enumerate(v)]})
    _w(root / "drivers" / "x.json", {"elo": [[Y, 2, 1400.0, 1500.0]]})


def test_paddock_drivers_and_constructors(tmp_path):
    _tree(tmp_path)
    res = PB.build(tmp_path)
    assert res["leagues"] == ["drivers", "constructors"]
    idx = json.loads((tmp_path / "power.json").read_text(encoding="utf-8"))
    assert idx["default"] == "drivers"
    d = json.loads((tmp_path / "power" / "drivers.json").read_text(encoding="utf-8"))
    assert d["kind"] == "players" and d["noun"] == "drivers" and d["step"] == "race" and d["phase"] == "season"
    assert [s["label"] for s in d["snapshots"]] == ["R1", "R2", "Now"]
    ids = [t["id"] for t in d["teams"]]
    assert ids == ["b", "a", "c", "d"]                            # x (below the peer floor) is not ranked
    b = d["teams"][0]
    assert b["path"] == [3, 2, 1] and b["prev"] == 2 and b["move"] == 1
    # no look-ahead: each snapshot is the Elo after that round, shown against the grid average then
    avg1 = sum(v[0] for v in ELO.values()) / 4
    assert b["rpath"][0] == pytest.approx(ELO["b"][0] - avg1, abs=0.06)
    assert sum(t["rating"] for t in d["teams"]) == pytest.approx(0, abs=0.3)
    assert b["chance"]["label"] == "Title" and b["chance"]["p"] == 0.6
    assert {"label": "Elo", "text": "1,620"} in b["stats"] and b["href"] == "#/driver/b"
    assert b["note"].startswith("New No. 1") and "won the Grand Prix 3" in b["note"]
    g = {x["key"]: x for x in d["players"]["groups"]}
    assert list(g) == ["quali", "race", "teammate"]
    assert g["race"]["metric"]["key"] == "pace_tm" and g["race"]["top"][0]["id"] == "d"   # the most negative driver effect
    assert g["race"]["top"][0]["value"] == pytest.approx(0.15) and g["quali"]["min"] == "2+ Grand Prix starts"
    assert g["quali"]["top"][0]["id"] == "a" and g["quali"]["top"][0]["team"] == "T0" and g["quali"]["n"] == 4
    c = json.loads((tmp_path / "power" / "constructors.json").read_text(encoding="utf-8"))
    assert c["kind"] == "teams" and [t["id"] for t in c["teams"]] == ["t0", "t1"]
    t1 = c["teams"][1]
    # round 2: c and the stand-in x raced for t1 (d sat it out): the team is who raced, on their Elo after the round
    avg2 = sum(v[1] for v in ELO.values()) / 4
    assert t1["rpath"][1] == pytest.approx((ELO["c"][1] + 1400.0) / 2 - avg2, abs=0.06)
    assert t1["name"] == "Team One" and t1["group"] == "C & D"
    assert {"label": "Car pace", "text": "−0.50%"} in t1["stats"]


def test_paddock_clinched_and_offseason(tmp_path):
    _tree(tmp_path, clinched=True)
    PB.build(tmp_path)
    c = json.loads((tmp_path / "power" / "constructors.json").read_text(encoding="utf-8"))
    t0 = c["teams"][0]
    assert t0["note"].startswith(f"Clinched the {Y} constructors’ title") and "chance" not in t0
    assert t0["stats"][0] == {"label": "Title", "text": "Champions"}
    _tree(tmp_path, finished=True)
    PB.build(tmp_path)
    d = json.loads((tmp_path / "power" / "drivers.json").read_text(encoding="utf-8"))
    assert d["phase"] == "offseason" and d["snapshots"][-1]["label"] == "Final"
    assert all("chance" not in t for t in d["teams"])
    assert d["teams"][0]["note"].startswith(f"{Y} drivers’ champion")
