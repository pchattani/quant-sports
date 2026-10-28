"""Footballer progression (oddsmarkets/football/analytics/progression.py on common.progression)."""
from __future__ import annotations

import json

from oddsmarkets.football.analytics import progression as FP

ERAS = {"season": {"split": "2026/27", "calendar": "2026"}, "last": {"split": "2025/26", "calendar": "2025"}}


def _person(i, role="ST", mins=1800):
    return {"id": str(i), "frame": "split", "role": role, "pos": "F",
            "seasons": [{"comp": "premier-league", "sid": 1, "scope": "club", "era": "2025/26", "tid": 10, "team": "A",
                         "apps": 20, "min": mins, "g": i, "a": 1, "xg": 0.5 * i, "xa": 1.0, "sh": 20, "kp": 10, "rt": 7.0},
                        {"comp": "champions-league", "sid": 2, "scope": "club", "era": "2025/26", "tid": 10, "team": "A",
                         "apps": 2, "min": 180, "g": 0, "a": 0, "xg": None, "xa": None, "sh": 1, "kp": 0, "rt": 6.0}],
            "archive": [{"comp": "premier-league", "sid": 0, "scope": "club", "era": "2024/25", "tid": 11, "team": "B",
                         "apps": 30, "min": 2700, "g": i, "a": 2, "xg": float(i), "xa": 1.0, "rt": 7.1}]}


def test_rows_box_and_lab_kinds():
    people = {str(i): _person(i) for i in range(10)}
    lab = {(str(i), "club", "last"): {"player_id": str(i), "minutes": 1980, "role": "ST", "gar90": 0.01 * i, "npxg_xa_90": 0.1 * i,
                                      "xg_90": 0.2, "xa_90": 0.05} for i in range(10)}
    rows, ref, prog = FP.build(people, lab, ERAS)
    r = {x["key"]: x for x in rows["9"]}
    new, old = r["club:2025/26"], r["club:2024/25"]
    assert new["kd"] == "out" and old["kd"] == "box" and new["min"] == 1980 and new["teams"] == [10]
    ko = prog["keys"]["out"]
    assert ko[0] == "npxg_xa_90" and new["dv"][ko.index("gar90")] == 0.09 and new["pg"] == "st"
    kb = prog["keys"]["box"]
    assert old["dv"][kb.index("goals_90")] == 0.3 and "dp" in old
    # xG rates only over competitions with xG holding half the minutes: 1800 of 1980
    assert abs(new["dv"][ko.index("xg_xa_90")] - 0.25) < 1e-9          # the Lab's own xG + xA where merged
    assert "club:2025/26" in ref["seasons"] and ref["seasons"]["club:2025/26"]["st"]["n"] == 10


def test_lab_line_for_another_span_is_not_merged():
    people = {"1": _person(1)}
    lab = {("1", "club", "last"): {"player_id": "1", "minutes": 400, "role": "CB", "gar90": 0.2}}
    rows, _ref, _prog = FP.build(people, lab, ERAS)
    assert {x["key"]: x for x in rows["1"]}["club:2025/26"]["kd"] == "box"


def test_apply_and_carry(tmp_path):
    (tmp_path / "people").mkdir()
    (tmp_path / "lab").mkdir()
    (tmp_path / "lab" / "index.json").write_text(json.dumps({"windows": [{"key": k, "eras": e} for k, e in ERAS.items()]}))
    for i in range(9):
        (tmp_path / "people" / f"{i}.json").write_text(json.dumps(_person(i)), encoding="utf-8")
    assert FP.apply(tmp_path) == 9 and FP.apply(tmp_path) == 0
    p = json.loads((tmp_path / "people" / "3.json").read_text(encoding="utf-8"))
    ref = json.loads((tmp_path / "progression_ref.json").read_text(encoding="utf-8"))
    assert p["prog"]["keys_in"] == "progression_ref.json" and ref["prog"]["keys"]["box"] and p["progression"][0]["key"] == "club:2024/25"
    fresh = FP.carry(tmp_path / "people" / "3.json", {"id": "3"})
    assert fresh["progression"] == p["progression"] and (tmp_path / "progression_ref.json").exists()


def test_international_rows_carry_their_own_gar():
    """value_fields scores each Lab line over its own matches (28 Oct 2026), so the international row takes the intl
    line's GAR/90, which differs from the club line's."""
    p = _person(1)
    p["seasons"].append({"comp": "world-cup", "sid": 3, "scope": "international", "era": "2025/26", "tid": 4705,
                         "team": "Norway", "apps": 5, "min": 450, "g": 3, "a": 0, "xg": 2.0, "xa": 0.2, "sh": 12, "kp": 3, "rt": 7.4})
    lab = {("1", "intl", "last"): {"player_id": "1", "minutes": 450, "role": "ST", "gar90": 0.31, "gar": 1.55, "npxg_xa_90": 0.5},
           ("1", "club", "last"): {"player_id": "1", "minutes": 1980, "role": "ST", "gar90": 0.12, "gar": 2.64, "npxg_xa_90": 0.4}}
    rows, _ref, prog = FP.build({"1": p}, lab, ERAS)
    r = {x["key"]: x for x in rows["1"]}
    ko = prog["keys"]["out"]
    nat, club = r["intl:2025/26"], r["club:2025/26"]
    assert nat["kd"] == "out" and nat["dv"][ko.index("gar90")] == 0.31 and nat["dv"][ko.index("npxg_xa_90")] == 0.5
    assert club["dv"][ko.index("gar90")] == 0.12
