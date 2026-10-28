"""Campus progression (oddsmarkets/college/progression.py on common.progression)."""
from __future__ import annotations

from oddsmarkets.college import progression as PROG


def _recs(n=10):
    out = []
    for i in range(n):
        out.append({"pid": f"q{i}", "kind": "QB", "q": True, "values": {"value_pg": float(i), "epa_play": 0.01 * i, "int_rate": 0.01 * i,
                                                                    "sack_rate": 0.05}})
    out.append({"pid": "x", "kind": "QB", "q": False, "values": {"value_pg": 9.0}})
    out.append({"pid": "ol", "kind": "OL", "q": True, "values": {"value": 1.0}})          # no spec group: left out
    return out


def test_cfb_rows_ref_and_merge():
    rows, ref, prog = PROG.build("cfb", {2024: _recs(), 2025: _recs()})
    keys = prog["keys"]["QB"]
    assert keys[0] == "value_pg" and "OL" not in prog["keys"] and "ol" not in rows
    r = rows["q9"][2025]
    assert r["pg"] == "cfb_qb" and r["dv"][0] == 9 and r["dp"][keys.index("int_rate")] < r["dp"][0]   # int rate: lower is better
    assert "dp" not in rows["x"][2025] and ref["seasons"]["2025"]["cfb_qb"]["n"] == 10
    page, srows = {}, [{"season": 2025}, {"season": 2023}]
    PROG.merge(page, srows, rows["q9"], prog)
    assert srows[0]["pg"] == "cfb_qb" and "dv" not in srows[1] and page["prog"] == prog


def test_hoops_roles_and_catalogue_pct():
    recs = [{"pid": f"g{i}", "kind": "G", "q": True, "values": {"r": float(i), "pts100": 20.0 + i}, "pct": {"r": 3.0 * i}}
            for i in range(10)]
    rows, ref, prog = PROG.build("mbb", {2026: recs})
    keys = prog["keys"]["G"]
    assert rows["g5"][2026]["pg"] == "mbb_guards" and rows["g5"][2026]["dp"][keys.index("r")] == 15
    assert "mbb_guards" in ref["groups"]
