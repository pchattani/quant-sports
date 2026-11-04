"""
Tours, their ESPN slugs and the seasons ESPN carries, and the player statuses.

Coverage measured on 4 Nov 2026 (one leaderboard per tour and year):
  pga   2001 on: round scores for the whole field; hole-by-hole in the season scoreboard
  eur   round scores from about 2019 (an empty 2018 leaderboard); no hole-by-hole in the scoreboard
  liv   2022 on: three rounds, 54 players
  lpga  patchy: 2015 and 2019 leaderboards carry no rounds
"""
from __future__ import annotations

TOURS: dict[str, dict] = {
    "pga": {"name": "PGA Tour", "short": "PGA", "from": 2001, "holes": True},
    "eur": {"name": "DP World Tour", "short": "DPWT", "from": 2019, "holes": False},
    "liv": {"name": "LIV Golf", "short": "LIV", "from": 2022, "holes": False},
    "lpga": {"name": "LPGA Tour", "short": "LPGA", "from": 2021, "holes": False},
}

# a player's finish at an event (leaderboard competitor status)
STATUS = {"STATUS_FINISH": "finish", "STATUS_CUT": "cut", "STATUS_WD": "wd", "STATUS_WITHDRAWN": "wd",
          "STATUS_DQ": "dq", "STATUS_DISQUALIFIED": "dq", "STATUS_MDF": "mdf", "STATUS_PLAY_COMPLETE": "finish",
          "STATUS_IN_PROGRESS": "live", "STATUS_SCHEDULED": "upcoming", "STATUS_PRE": "upcoming",
          "STATUS_DNS": "dns", "STATUS_DID_NOT_START": "dns"}

# an event's state (scoreboard event status)
EVENT_STATUS = {"STATUS_FINAL": "final", "STATUS_PLAY_COMPLETE": "live", "STATUS_IN_PROGRESS": "live",
                "STATUS_SUSPENDED": "live", "STATUS_DELAYED": "live", "STATUS_SCHEDULED": "upcoming",
                "STATUS_CANCELED": "canceled", "STATUS_CANCELLED": "canceled", "STATUS_POSTPONED": "upcoming"}


def tour_key(tour: str) -> str:
    t = str(tour).lower()
    if t not in TOURS:
        raise ValueError(f"unknown tour {tour!r}; expected one of {sorted(TOURS)}")
    return t
