"""Player file fields for the v4 player page (23 Oct 2026): `number` (the jersey number from the Stats API answers the
fetcher already gets: roster jerseyNumber, else the person's primaryNumber) and `current.log` (one row per game this
season, hitting and pitching, with the best game marked)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from oddsmarkets.baseball.analytics import careers as CR
from oddsmarkets.baseball.sources import statsapi


def test_jersey_numbers_from_the_answers_already_fetched():
    assert statsapi.jersey("27") == "27" and statsapi.jersey("07") == "07" and statsapi.jersey(5) == "5"
    assert statsapi.jersey(None) is None and statsapi.jersey("") is None and statsapi.jersey("N/A") is None and statsapi.jersey("1234") is None
    rec = statsapi.person_record({"fullName": "Pete Crow-Armstrong", "firstName": "Pete", "lastName": "Crow-Armstrong", "primaryNumber": "4"})
    assert rec["num"] == "4"

    class C:
        def get(self, url, params=None):
            return {"roster": [{"person": {"id": 691718, "fullName": "Pete Crow-Armstrong"}, "jerseyNumber": "4", "position": {"abbreviation": "CF"},
                                "status": {"description": "Active"}},
                               {"person": {"id": 1, "fullName": "No Number"}, "position": {"abbreviation": "P"}, "status": {}}]}
    ros = statsapi.roster(C(), "112")
    assert ros[0]["num"] == "4" and ros[1]["num"] is None
    store = {"meta": {"rosters": {"112": {"40man": ["691718"], "num": {"691718": "4"}}, "113": {"40man": []}}}}
    assert CR.roster_numbers(store) == {"691718": "4"}
    assert CR.roster_numbers({}) == {}


def _pa(rows):
    cols = ["game_pk", "at_bat_number", "game_date", "batter", "pitcher", "events", "half", "bat_team", "fld_team", "is_pa",
            "woba_value", "woba_denom", "outs_rec", "runs", "n_pitches"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


def test_game_logs_one_row_per_game_with_the_best_marked():
    # game 1 (home team CHC bats in the bottom, half 1): batter 10 doubles and homers; pitcher 20 (STL) starts it
    # game 2 (CHC away, half 0): batter 10 walks and strikes out; pitcher 20 does not pitch
    rows = [
        [1, 1, "2026-04-01", 10, 20, "double", 1, "CHC", "STL", True, 1.25, 1, 0, 0, 4],
        [1, 2, "2026-04-01", 11, 20, "strikeout", 1, "CHC", "STL", True, 0.0, 1, 1, 0, 5],
        [1, 3, "2026-04-01", 10, 20, "home_run", 1, "CHC", "STL", True, 2.0, 1, 0, 2, 3],
        [1, 4, "2026-04-01", 30, 40, "field_out", 0, "STL", "CHC", True, 0.0, 1, 1, 0, 2],
        [2, 1, "2026-04-02", 10, 21, "walk", 0, "CHC", "MIL", True, 0.7, 1, 0, 0, 6],
        [2, 2, "2026-04-02", 10, 21, "strikeout", 0, "CHC", "MIL", True, 0.0, 1, 1, 0, 4],
    ]
    pa = _pa(rows)
    ctx = SimpleNamespace(agg=lambda: {"pa": pa}, bip=lambda: None,
                          games={"1": {"status": "final", "hs": 5, "as": 3, "gtype": "R"}, "2": {"status": "final", "hs": 2, "as": 1, "gtype": "R"}})
    L = CR.game_logs(ctx, {"10": 1}, {"20": 1})
    h = L["10"]["hitting"]
    assert h["cols"] == CR.LOG_H and len(h["rows"]) == 2
    r1 = dict(zip(h["cols"], h["rows"][0]))
    assert r1["date"] == "2026-04-01" and r1["opp"] == "STL" and r1["home"] == 1 and r1["res"] == "W 5-3"
    assert (r1["pa"], r1["ab"], r1["h"], r1["tb"], r1["hr"], r1["bb"], r1["k"]) == (2, 2, 2, 6, 1, 0, 0)
    r2 = dict(zip(h["cols"], h["rows"][1]))
    assert r2["opp"] == "MIL" and r2["home"] == 0 and r2["res"] == "L 1-2" and (r2["ab"], r2["bb"], r2["k"]) == (1, 1, 1)
    assert h["best"] == 0
    p = dict(zip(CR.LOG_P, L["20"]["pitching"]["rows"][0]))
    assert len(L["20"]["pitching"]["rows"]) == 1
    assert p["opp"] == "CHC" and p["home"] == 0 and p["res"] == "L 3-5" and p["gs"] == 1
    assert (p["outs"], p["bf"], p["h"], p["r"], p["k"], p["hr"], p["np"]) == (1, 3, 2, 2, 1, 1, 12)
    assert "11" not in L and "40" not in L                            # only the players asked for
    json.dumps(L, allow_nan=False)
    assert CR.game_logs(SimpleNamespace(agg=lambda: {}, bip=lambda: None, games={}), {"10": 1}, {}) == {}
