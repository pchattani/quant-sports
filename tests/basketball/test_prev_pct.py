"""Kit v3 rail rings: last season's role percentiles ride on the current block of players/<pid>.json."""
from __future__ import annotations

from oddsmarkets.basketball.analytics import players as PL


def _row(role, pts, qual=True, pct=None):
    return {"role": role, "gp": 70, "qualified": qual, "values": {"pts100": pts}, "pct_role": pct if pct is not None else {}}


def test_prev_role_pct_same_role_and_role_change():
    prev = {"a": _row("G", 30.0, pct={"pts100": 88}), "b": _row("W", 20.0), "c": _row("W", 25.0), "d": _row("W", 15.0),
            "e": _row("G", 10.0), "f": _row("G", 12.0)}
    cats = {2026: {"players": prev}, 2027: {"players": {}}}
    blocks = {"a": {"season": 2027}, "b": {"season": 2027}, "z": {"season": 2027}, "e": None}
    n = PL.prev_role_pct(cats, blocks, {"a": "G", "b": "G", "z": "W"}, keys=["pts100"])
    assert n == 2
    # unchanged role: the stored pct_role
    assert blocks["a"]["prev_pct_pos"] == {"pts100": 88}
    assert blocks["a"]["prev_peer"]["season"] == 2026 and blocks["a"]["prev_peer"]["role"] == "G"
    # W last season, G now: placed among last season's qualified guards (30, 10, 12): 20 sits second of four
    pb = blocks["b"]["prev_pct_pos"]["pts100"]
    assert 50 <= pb <= 75
    assert blocks["b"]["prev_peer"]["role"] == "G"
    assert "prev_pct_pos" not in blocks["z"]           # no row last season
