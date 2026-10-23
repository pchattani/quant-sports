"""Kit v3 rail rings (Paddock): last season's peer percentiles on the driver career file's current block."""
from __future__ import annotations

from oddsmarkets.f1.analytics import drivers as drv

MET = [{"key": "races"}, {"key": "race_pace", "lower": True}, {"key": "points_per_race"}]


def test_prev_peer_pct_reads_pct_peer_when_the_catalogue_has_it():
    cat = {"year": 2025, "peer_floor": 8, "metrics": MET, "drivers": {
        "a": {"races": 24, "qualified": True, "pct_peer": {"race_pace": 90}},
        "b": {"races": 2, "qualified": False, "pct_peer": {}}}}
    assert drv.prev_peer_pct(cat, "a") == {"prev_pct_pos": {"race_pace": 90},
                                           "prev_peer": {"year": 2025, "races": 24, "floor": 8, "qualified": True}}
    assert drv.prev_peer_pct(cat, "b") == {} and drv.prev_peer_pct(cat, "zz") == {} and drv.prev_peer_pct(None, "a") == {}


def test_prev_peer_pct_ranks_an_older_catalogue_among_the_qualifying_drivers():
    rows = {d: {"races": 20, "values": {"race_pace": p, "points_per_race": q}} for d, p, q in
            (("a", 0.1, 10.0), ("b", 0.3, 5.0), ("c", 0.5, 1.0))}
    rows["stand_in"] = {"races": 1, "values": {"race_pace": 0.0, "points_per_race": 25.0}}     # under the floor: not a peer
    cat = {"year": 2025, "peer_floor": 8, "metrics": MET, "drivers": rows}
    got = drv.prev_peer_pct(cat, "a")["prev_pct_pos"]
    assert got == {"race_pace": 100, "points_per_race": 100}          # lower pace is better; the stand-in does not count
    assert drv.prev_peer_pct(cat, "c")["prev_pct_pos"] == {"race_pace": 0, "points_per_race": 0}
    assert drv.prev_peer_pct(cat, "stand_in") == {}
