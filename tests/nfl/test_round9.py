"""Round 9 (28 Oct 2026): the builder pieces behind the Gridiron fixes."""
from __future__ import annotations

from oddsmarkets.nfl.analytics import fantasy_model as FM
from oddsmarkets.nfl.analytics import history as HS


def _row(group, name, team, values, pv=None):
    return {"group": group, "name": name, "team": team, "qualified": True, "values": values, "plus": {}, "pv": pv or values}


def test_season_records_are_the_best_seasons_in_our_data():
    rows = {
        2001: {"a": _row("DEF", "Michael Strahan", "NYG", {"sacks": 22.5, "tackles": 50})},
        2021: {"b": _row("DEF", "T.J. Watt", "PIT", {"sacks": 22.5, "tackles": 60})},
        2025: {"c": _row("DEF", "Myles Garrett", "CLE", {"sacks": 23.0, "tackles": 45}),
               "d": _row("QB", "Some Quarterback", "CLE", {"pass_yds": 4100, "att": 600})},
    }
    out = HS.build(rows, {})
    rec = out["season_records"]
    assert out["record_cols"] == ["pid", "name", "season", "team", "value"]
    assert rec["sacks"]["rows"][0][:3] == ["c", "Myles Garrett", 2025]
    # the record before 2025 is the 22.5 shared by two seasons (earlier season first on a tie)
    before = [r for r in rec["sacks"]["rows"] if r[2] < 2025]
    assert [r[4] for r in before] == [22.5, 22.5] and before[0][2] == 2001
    assert rec["pass_yds"]["rows"][0][4] == 4100.0
    # a group-bound key never takes another group's rows
    assert all(r[0] != "d" for r in rec["sacks"]["rows"])


def test_counts_in_the_fantasy_reasons_agree_in_number():
    assert FM._n(1, "TD") == "1 TD"
    assert FM._n(3.0, "TD") == "3 TDs"
    assert FM._n(0, "TD") == "0 TDs"
