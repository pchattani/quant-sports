"""
Ranking points by level and round for builder C's simulators (tournament_sim, season_sim).

canon.py (builder A) owns the only table: `table(tour, level, draw_size, year)` is
`canon.points_table(tour, level, draw_size)` (canon.POINTS, checked against the ATP 2025 and WTA 2024
official charts cited there) with the Finals keys renamed. There is no second, hand-entered copy here. Keys
are the round in which a player lost ("R128" ... "F") plus "W" for the champion; for the Finals: "RR_win"
(each round-robin win), "SF_win" and "F_win". A level canon has no table for (ATP Challengers, "other")
earns nothing.

Simplifications (marked): the first-round loser value applies to the draw's first round whatever its size;
a player with a first-round bye who loses his first match gets the first-round loser value (ATP and WTA rule);
qualifying points are not added.
"""
from __future__ import annotations

from typing import Any

ROUNDS = ["R128", "R64", "R32", "R16", "QF", "SF", "F"]


def round_names(size: int) -> list[str]:
    """Round labels for a knockout of `size` (power of two) slots: [first round, ..., "F"]."""
    out = []
    k = int(size)
    while k >= 2:
        out.append({2: "F", 4: "SF", 8: "QF"}.get(k, f"R{k}"))
        k //= 2
    return out


def _canon_table(tour: str, level: str, draw_size: int | None) -> dict:
    from oddsmarkets.tennis import canon
    t = canon.points_table(tour, level, draw_size) or {}
    return _norm({str(k): float(v) for k, v in t.items() if isinstance(v, (int, float))})


_KEYS = {"RR_WIN": "RR_win", "SF_WIN": "SF_win", "F_WIN": "F_win"}


def _norm(t: dict) -> dict:
    """canon's Finals keys (RR_WIN, SF_WIN, F_WIN) to ours."""
    return {_KEYS.get(k, k): v for k, v in t.items()}


def table(tour: str, level: str, draw_size: int | None = None, year: int | None = None) -> dict:
    """canon's points for (tour, level, draw size); {} when canon has none. `year` is accepted for callers
    and ignored (canon applies the current tables to every year: MODELS.md, Known limitations)."""
    t = "wta" if str(tour).lower() == "wta" else "atp"
    return _canon_table(t, str(level or "250"), draw_size)


def points_for_exit(tab: dict, exit_round: str, first_round: str, had_bye: bool = False, won_a_match: bool = True) -> float:
    """Points for a player who lost in `exit_round` ("W" for the champion)."""
    if had_bye and not won_a_match:
        return float(tab.get(first_round, 0.0))
    return float(tab.get(exit_round, 0.0))


def as_float(x: Any, d: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d
