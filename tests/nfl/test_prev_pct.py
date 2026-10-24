"""Kit v3 rail rings: last season's role and position percentiles ride on the current block of players/<pid>.json."""
from __future__ import annotations

from oddsmarkets.nfl.analytics import careers as CR


def test_prev_pct_role_and_position_pool():
    prev = {"players": {
        "1": {"group": "DEF", "pos": "OLB", "role": "EDGE", "games": 17, "qualified": True, "pct_role": {"d_sacks": 90}, "pct_pos": {"d_sacks": 80}},
        "2": {"group": "DEF", "pos": "CB", "role": "CB", "games": 16, "qualified": True, "pct_role": {"d_pd": 70}, "pct_pos": {"d_pd": 60}},
        "3": {"group": "WR", "pos": "WR", "role": "WR", "games": 9, "qualified": False, "pct_role": {}, "pct_pos": {"yprr": 55}}}}
    blocks = {"1": {"season": 2026, "group": "DEF", "pos": "LB", "role": "EDGE"},   # OLB -> LB: same pools
              "2": {"season": 2026, "group": "DEF", "pos": "S", "role": "S"},       # CB -> S: role differs, DB pool same
              "3": {"season": 2026, "group": "TE", "pos": "TE", "role": "TE"},      # WR -> TE: nothing
              "4": {"season": 2026, "group": "QB", "pos": "QB", "role": "QB"}}
    n = CR.add_prev_pct(blocks, lambda s: prev if s == 2025 else None)
    assert n == 2
    assert blocks["1"]["prev_pct_role"] == {"d_sacks": 90} and blocks["1"]["prev_pct_pos"] == {"d_sacks": 80}
    assert blocks["1"]["prev_peer"] == {"season": 2025, "role": "EDGE", "group": "DEF", "pos_pool": "LB", "games": 17, "qualified": True}
    assert "prev_pct_role" not in blocks["2"] and blocks["2"]["prev_pct_pos"] == {"d_pd": 60}
    assert "prev_peer" not in blocks["3"] and "prev_peer" not in blocks["4"]


def test_write_careers_carries_prev_fields():
    rows = {2026: {"1": {"season": 2026, "group": "DEF", "role": "EDGE", "values": {"games": 10}, "name": "A"}}}
    blk = {"season": 2026, "group": "DEF", "role": "EDGE", "prev_pct_role": {"d_sacks": 90}, "prev_peer": {"season": 2025}}
    written = {}
    CR.write_careers(lambda rel, p: written.__setitem__(rel, p), rows, {"1": blk}, None, 2026)
    cur = written["players/1.json"]["current"]
    assert cur["prev_pct_role"] == {"d_sacks": 90} and cur["prev_peer"] == {"season": 2025} and "prev_pct_pos" not in cur


def test_write_careers_carries_the_jersey_number(monkeypatch):
    """The player hero's outlined number: the season's weekly rosters first, the players release's latest second."""
    import pandas as pd
    from oddsmarkets.nfl.analytics import context, people
    monkeypatch.setattr(people, "people", lambda: {"00-1": {"name": "A", "number": 9}, "00-2": {"name": "B", "number": 33}})
    wk = pd.DataFrame({"gsis_id": ["00-1", "00-1", "00-3"], "week": [2, 1, 1], "jersey_number": [12.0, 4.0, None]})
    monkeypatch.setattr(context, "load_release", lambda name, season, cols=None, kind=None: wk if name == "weekly_rosters" else None)
    assert people.season_numbers(2026) == {"00-1": 12}               # the latest week wins; a missing number is skipped
    rows = {2026: {p: {"season": 2026, "group": "QB", "values": {"games": 10}, "name": p} for p in ("00-1", "00-2", "00-3")}}
    written = {}
    blocks = {p: {"season": 2026, "group": "QB"} for p in rows[2026]}   # current blocks: every file is written
    CR.write_careers(lambda rel, p: written.__setitem__(rel, p), rows, blocks, None, 2026)
    assert written["players/00-1.json"]["number"] == 12
    assert written["players/00-2.json"]["number"] == 33
    assert written["players/00-3.json"]["number"] is None
    assert people.jersey("07") == 7 and people.jersey(150) is None
