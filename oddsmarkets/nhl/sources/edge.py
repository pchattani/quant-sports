"""
NHL EDGE puck and player tracking (https://api-web.nhle.com/v1/edge), 2021-22 ->.

Endpoints (verified 1 Oct 2026; season S, game type T = 2 regular / 3 playoffs):
  skater-detail/{pid}/{S}/{T}      topShotSpeed, skatingSpeed (speedMax, burstsOver20), totalDistanceSkated,
                                   distanceMaxGame, sogSummary / sogDetails (shots by area), zoneTimeDetails
                                   (O / N / D zone share, all and even strength) with percentiles and league averages
  goalie-detail/{pid}/{S}/{T}      stats (GAA, games above .900, goal differential per 60, ...), shotLocationSummary /
                                   shotLocationDetails (saves and goals by area)
  team-detail/{team_id}/{S}/{T}    shotSpeed, skatingSpeed, distanceSkated, sogSummary, zoneTimeDetails (with ranks)
  2020-21 and earlier answer 404 (no page). A player with no tracked games answers 404 too.
"""
from __future__ import annotations

import logging
from typing import Any

from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

EDGE = "https://api-web.nhle.com/v1/edge"
KINDS = {"skater": "skater-detail", "goalie": "goalie-detail", "team": "team-detail"}


def detail(c: Client, kind: str, ident: int | str, season: int, game_type: int = 2) -> dict | None:
    return c.get(f"{EDGE}/{KINDS[kind]}/{ident}/{int(season)}/{int(game_type)}")


def _v(node: Any, *path, unit: str = "imperial"):
    for p in path:
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    if isinstance(node, dict):
        return node.get(unit, node.get("value"))
    return node


def summary(kind: str, raw: dict | None) -> dict | None:
    """A compact per-player (team) EDGE record for the site and models."""
    if not raw:
        return None
    if kind == "skater":
        z = raw.get("zoneTimeDetails") or {}
        return {"top_shot_mph": _v(raw, "topShotSpeed"), "top_shot_pct": _v(raw, "topShotSpeed", "percentile"),
                "max_speed_mph": _v(raw, "skatingSpeed", "speedMax"),
                "max_speed_pct": _v(raw, "skatingSpeed", "speedMax", "percentile"),
                "bursts_20": _v(raw, "skatingSpeed", "burstsOver20", unit="value"),
                "distance_mi": _v(raw, "totalDistanceSkated"),
                "distance_max_game_mi": _v(raw, "distanceMaxGame"),
                "oz_pct": z.get("offensiveZonePctg"), "nz_pct": z.get("neutralZonePctg"),
                "dz_pct": z.get("defensiveZonePctg"), "oz_ev_pct": z.get("offensiveZoneEvPctg")}
    if kind == "goalie":
        return {k: v for k, v in (raw.get("stats") or {}).items() if not isinstance(v, dict)} | {
            "shot_locations": len(raw.get("shotLocationDetails") or [])}
    z = raw.get("zoneTimeDetails") or {}
    return {"max_speed_mph": _v(raw, "skatingSpeed", "speedMax"), "top_shot_mph": _v(raw, "shotSpeed", "topShotSpeed"),
            "oz_pct": z.get("offensiveZonePctg"), "dz_pct": z.get("defensiveZonePctg")}
