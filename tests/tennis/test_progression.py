"""Ace progression (common.progression): dv / dp / pg on the career rows and progression_ref.json."""
from __future__ import annotations

from oddsmarkets.tennis.analytics import players as PL


def _cat(n=10):
    P = {}
    for i in range(n):
        P[str(i)] = {"matches": 20 + i, "qualified": True, "rank": 10 - i,
                     "values": {"elo": 1600 + 20 * i, "hold": 0.7 + 0.01 * i, "brk": 0.2 + 0.01 * i, "games_won_pct": 0.5,
                                "elo_clay": 1500, "elo_grass": 1500, "win_v_top50": 0.4},
                     "pct": {"hold": 5 * i}}
    P["low"] = {"matches": 3, "qualified": False, "rank": 300, "values": {"elo": 1400, "hold": 0.5}}
    return {"players": P}


def test_progression_rows_ref_and_merge():
    rows, ref, prog = PL.progression({2024: _cat(), 2025: _cat()}, "atp")
    keys = prog["keys"]["atp"]
    assert keys[0] == "elo" and "dominance" not in keys               # no ATP values: left out of the deep set
    r9 = rows["9"][2025]
    assert r9["pg"] == "atp_all" and r9["dv"][0] == 1780 and r9["dp"][keys.index("hold")] == 45    # the catalogue's pct
    assert r9["dp"][0] > rows["0"][2025]["dp"][0] and "dp" not in rows["low"][2025]
    assert ref["seasons"]["2025"]["atp_all"]["n"] == 10
    page = {"seasons": [{"year": 2025, "w": 1}, {"year": 2023, "w": 2}]}
    PL.merge_progression(page, rows["9"], prog)
    assert page["seasons"][0]["pg"] == "atp_all" and "dv" not in page["seasons"][1] and page["prog"] == prog
