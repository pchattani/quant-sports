"""Kit v3 rail rings (Ace): last season's tour and surface percentiles on the career file's current block."""
from __future__ import annotations

from oddsmarkets.tennis.analytics import players as PL


def test_prev_pct_tour_and_surfaces_by_floor():
    cat = {"year": 2025, "surface_floor": {"hard": 10, "clay": 8, "grass": 5}, "players": {
        "a": {"qualified": True, "matches": 60, "pct": {"elo": 90, "not_in_spec": 5},
              "values_surface": {"hard": {"matches": 30}, "clay": {"matches": 4}},
              "pct_surface": {"hard": {"elo_surface": 80, "hold": 60}, "clay": {"elo_surface": 99}}},
        "b": {"qualified": False, "matches": 9, "pct": {"elo": 40}, "values_surface": {"grass": {"matches": 6}},
              "pct_surface": {"grass": {"hold": 70}}},
        "c": {"qualified": False, "matches": 3, "pct": {"elo": 10}}}}
    a = PL.prev_pct(cat, "a", "atp")
    assert a["prev_pct_pos"] == {"all": {"elo": 90}, "hard": {"elo_hard": 80, "hold": 60}}     # clay under its floor
    assert a["prev_peer"] == {"year": 2025, "matches": 60, "qualified": True, "surface_matches": {"hard": 30, "clay": 4, "grass": 0}}
    assert PL.prev_pct(cat, "b", "atp")["prev_pct_pos"] == {"grass": {"hold": 70}}      # not qualified on tour: surface only
    assert PL.prev_pct(cat, "c", "atp") == {} and PL.prev_pct(None, "a", "atp") == {}
