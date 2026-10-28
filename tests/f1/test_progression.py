"""Paddock progression (common.progression): dv / dp / pg on the driver files and progression_ref.json."""
from __future__ import annotations

from oddsmarkets.f1.analytics import drivers as drv


def _cat(year, n=10):
    D = {f"d{i}": {"races": 20, "team": "t", "values": {"driver_effect": -0.01 * i, "race_h2h": 0.4 + 0.02 * i,
                                                        "elo_teammate": 1500 + i, "points_per_race": float(i)}}
         for i in range(n)}
    D["stand_in"] = {"races": 1, "values": {"driver_effect": 0.5}}
    return {"year": year, "peer_floor": 8, "drivers": D}


def test_progression_rows_ref_and_merge():
    rows, ref, prog = drv.progression({2024: _cat(2024), 2025: _cat(2025)})
    keys = prog["keys"]["drivers"]
    assert keys[0] == "driver_effect"
    r = rows["d9"][2025]
    assert r["pg"] == "drivers" and r["dp"][0] > rows["d0"][2025]["dp"][0]        # lower effect = better
    assert "dp" not in rows["stand_in"][2025]
    assert ref["seasons"]["2025"]["drivers"]["n"] == 10
    c = {"seasons": [{"year": 2025, "team": "t"}]}
    drv.merge_progression(c, rows["d9"], prog)
    assert c["seasons"][0]["dv"][keys.index("race_h2h")] == 0.58 and c["prog"] == prog
