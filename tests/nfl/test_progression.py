"""Progression (common.progression): dv / dp / pg on the career rows, the prog block and progression_ref.json."""
from __future__ import annotations

from oddsmarkets.nfl.analytics import careers as CR


def _cat(season):
    P = {}
    for i in range(10):
        P[f"q{i}"] = {"group": "QB", "pos": "QB", "name": f"Q{i}", "team": "AAA", "games": 17, "qualified": True, "age": 24 + i,
                      "values": {"att": 400 + i, "epa_db": 0.01 * i, "cpoe": float(i), "sack_rate": 0.05 + 0.01 * i, "composite": 90 + i},
                      "pct_pos": {"epa_db": 10 * i}}
        P[f"d{i}"] = {"group": "DEF", "pos": "OLB", "name": f"D{i}", "team": "BBB", "games": 10, "qualified": True, "age": 26,
                      "values": {"tackles": 30 + i, "sacks": float(i), "qb_hits": i, "tfl": i, "pd": 1, "ints": 0, "ff": 0,
                                 "pressures_pg": 0.1 * i, "splash_pg": 0.2 * i, "def_value": float(i)}}
    P["x"] = {"group": "QB", "pos": "QB", "name": "X", "team": "AAA", "games": 2, "qualified": False, "age": 22,
              "values": {"att": 30, "epa_db": 0.5}}
    return {"players": P}


def _value(season):
    rows = [[f"q{i}", "Q", "AAA", "QB", 24, 17, 0, 0, 0, 1.0 + i, 50, 0, 1, []] for i in range(10)]
    rows += [[f"d{i}", "D", "BBB", "EDGE", 26, 10, 0, 0, 0, 0.5 * i, 50, 0, 1, []] for i in range(10)]
    return {"cols": ["pid", "name", "team", "pos", "age", "games", "opp", "gv", "gvar", "gvar_pg", "pct", "trend", "q", "why"], "rows": rows}


def test_progression_rows_ref_and_files():
    rows_by = {s: CR.reduce_cat(_cat(s), s) for s in (2024, 2025)}
    ref, prog = CR.progression(rows_by, _value)
    qk, dk = prog["keys"]["QB"], prog["keys"]["DEF"]
    assert qk[0] == "composite" and "gvar_pg" in qk and "tackles_pg" in dk
    q7, x, d5 = rows_by[2025]["q7"]["_h"], rows_by[2025]["x"]["_h"], rows_by[2025]["d5"]["_h"]
    assert q7["pg"] == "qb" and q7["dv"][qk.index("gvar_pg")] == 8.0
    assert q7["dp"][qk.index("epa_db")] == 70                         # the catalogue's own pct_pos
    assert q7["dp"][qk.index("sack_rate")] < 50                       # lower is better, placed among peers
    assert x["pg"] == "qb" and "dp" not in x                          # unqualified: values only
    assert d5["pg"] == "edge" and d5["dv"][dk.index("tackles_pg")] == 3.5
    assert ref["groups"]["qb"]["keys"] == qk and ref["seasons"]["2025"]["edge"]["n"] == 10
    written = {}
    CR.write_careers(lambda rel, p: written.__setitem__(rel, p), rows_by, {}, None, 2025, prog)
    f = written["players/q7.json"]
    assert f["prog"]["keys"]["QB"] == qk and f["seasons"][1]["pg"] == "qb" and len(f["seasons"][1]["dv"]) == len(qk)
