"""Kit v3 rail rings: last season's position-group percentiles ride on the current block of players/<pid>.json."""
from __future__ import annotations

from oddsmarkets.nhl.analytics import careers


def test_prev_pct_pos_from_last_seasons_catalogue_same_group_only():
    cats = {(20242025, "skaters.json"): {"players": {
                "1": {"group": "F", "gp": 80, "qualified": True, "pct_pos": {"p": 90}},
                "2": {"group": "F", "gp": 12, "qualified": False, "pct_pos": {"p": 30}}}},
            (20242025, "goalies.json"): {"players": {"30": {"group": "G", "gp": 50, "qualified": True, "pct": {"sv_pct": 70}}}}}
    blocks = {"1": {"season": 20252026, "kind": "skater", "peer": {"group": "F"}},
              "2": {"season": 20252026, "kind": "skater", "peer": {"group": "D"}},   # moved F -> D: no ring
              "3": {"season": 20252026, "kind": "skater", "peer": {"group": "F"}},   # a rookie: no ring
              "30": {"season": 20252026, "kind": "goalie"}}
    n = careers.add_prev_pct(blocks, lambda s, fn: cats.get((s, fn)))
    assert n == 2
    assert blocks["1"]["prev_pct_pos"] == {"p": 90}
    assert blocks["1"]["prev_peer"] == {"season": 20242025, "group": "F", "gp": 80, "qualified": True}
    assert "prev_pct_pos" not in blocks["2"] and "prev_pct_pos" not in blocks["3"]
    assert blocks["30"]["prev_pct_pos"] == {"sv_pct": 70} and blocks["30"]["prev_peer"]["group"] == "G"
