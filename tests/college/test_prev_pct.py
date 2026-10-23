"""Kit v3 rail rings (Campus): last season's position (CFB) / role (MBB, WBB) percentiles on the current block."""
from __future__ import annotations

from oddsmarkets.college import packing as PK
from oddsmarkets.college.football import build as FB
from oddsmarkets.college.hoops import build as HB


def test_cfb_prev_ring_same_position_and_qualified():
    prev = {"ok": True, "players": {"1": {"pos": "QB", "gp": 12, "qualified": True, "pct_pos": {"epa_play": 88.0}},
                                    "2": {"pos": "WR", "gp": 3, "qualified": False, "pct_pos": {"rec_yds": 40.0}},
                                    "3": {"pos": "RB", "gp": 10, "qualified": True, "pct_pos": {"rush_yds": 70.0}}}}
    assert FB.prev_ring(prev, "1", "QB", 2025) == {"prev_pct_pos": {"epa_play": 88.0},
                                                   "prev_peer": {"season": 2025, "pos": "QB", "gp": 12, "qualified": True}}
    assert FB.prev_ring(prev, "2", "WR", 2025) == {}       # not qualified last season
    assert FB.prev_ring(prev, "3", "WR", 2025) == {}       # RB then, WR now
    assert FB.prev_ring(None, "1", "QB", 2025) == {}
    packed = {"ok": True, "players": PK.pack_keyed(prev["players"])}
    assert FB.prev_ring(packed, "1", "QB", 2025)["prev_pct_pos"] == {"epa_play": 88.0}


def test_hoops_prev_ring_same_role():
    def sp(roles, qual, pcts_role):
        return {"rows": {p: {"pos": "F", "gp": 30} for p in roles}, "role_of": roles, "qual": set(qual), "pcts_role": pcts_role}
    prev = sp({"1": "W", "2": "G", "3": "W"}, ["1", "2"], {"1": {"ts": 81.0}, "2": {"ts": 50.0}, "3": {"ts": 10.0}})
    cur = sp({"1": "W", "2": "W", "3": "W"}, ["1", "2", "3"], {})
    got = HB.prev_ring(cur, prev, "1", 2026)
    assert got["prev_pct_pos"] == {"ts": 81.0}
    assert got["prev_peer"] == {"season": 2026, "role": "W", "pos": "F", "gp": 30, "qualified": True}
    assert HB.prev_ring(cur, prev, "2", 2026) == {}       # a guard then, a wing now
    assert HB.prev_ring(cur, prev, "3", 2026) == {}       # not qualified last season
    assert HB.prev_ring(cur, None, "1", 2026) == {}
