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


def _g(gid, gtype, home, away, hs, as_):
    return {"game_id": gid, "gtype": gtype, "home": home, "away": away, "hs": hs, "as": as_, "status": "final"}


def test_champions_from_the_stores():
    teams = {"OAK": {"franchise": "LV", "conf": "AFC"}, "NE": {"franchise": "NE", "conf": "AFC"}, "TB": {"franchise": "TB", "conf": "NFC"},
             "PHI": {"franchise": "PHI", "conf": "NFC"}}
    games = [_g("1", "REG", "OAK", "NE", 30, 10), _g("2", "REG", "TB", "PHI", 20, 17), _g("3", "REG", "NE", "TB", 21, 24),
             _g("4", "CON", "OAK", "NE", 41, 24), _g("5", "CON", "TB", "PHI", 27, 10), _g("6", "SB", "OAK", "TB", 21, 48)]
    out = HS.champions({2002: {"teams": teams, "games": {g["game_id"]: g for g in games}}})
    row = out["seasons"][0]
    assert row["sb"] == ["TB", "LV", 48, 21]          # the franchise's current abbreviation (Oakland -> Las Vegas)
    assert row["afc"] == "LV" and row["nfc"] == "TB"
    lv = out["teams"]["LV"][0]
    assert lv[0] == 2002 and lv[6] == 4 and lv[-1] == "OAK"   # lost the Super Bowl; the season's own abbreviation kept
    assert out["teams"]["TB"][0][6] == 5
    assert out["teams"]["NE"][0][6] == 3


def test_injury_board_values_the_lists():
    from oddsmarkets.nfl.analytics import injury_board as IB
    log = {"teams": {"KC": [["2026-10-20T00:00Z", [["1", "Questionable", "x", "Knee", "Leg", None, "WR"]]],
                            ["2026-10-24T00:00Z", [["1", "Out", "x", "Knee", "Leg", "2026-11-01", "WR"], ["2", "Questionable", "x", "Ankle", "Leg", None, "CB"],
                                                   ["3", "Active", "x", None, None, None, "QB"], ["4", "Doubtful", "x", "Hand", "Arm", None, "OT"]]]]}}
    value = {"cols": ["pid", "name", "gvar_pg"], "rows": [["00-1", "Wide Out", 2.0], ["00-2", "Corner Back", 1.0], ["00-3", "Quarter Back", 6.0]]}
    out = IB.build(2026, log, value, {"1": "00-1", "2": "00-2", "3": "00-3", "4": "00-4"}, {"00-4": {"name": "Tackle"}})
    kc = out["teams"]["KC"]
    assert kc["at"] == "2026-10-24T00:00Z"              # the latest snapshot only
    assert [p[0] for p in kc["players"]] == ["00-1", "00-2", "00-4"]   # the active quarterback is not on the board
    assert kc["out_pg"] == round(2.0 * 1.0 + 1.0 * 0.15, 2)            # an unvalued lineman counts 0
    assert kc["n_out"] == 2 and kc["n_q"] == 1
