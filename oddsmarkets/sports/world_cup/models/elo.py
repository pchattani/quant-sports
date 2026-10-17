"""
Elo rating system for international football teams.
Used as a prior/ensemble component for teams with sparse WC xG data.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Initial Elo for teams with no prior data
DEFAULT_ELO = 1500.0

# K-factors per match type
K_WORLD_CUP = 60
K_QUALIFIER = 40
K_FRIENDLY = 20
# Domestic league play. Club sides meet often over a season, so each result carries
# less information than a rare international fixture and K is correspondingly lower.
K_LEAGUE = 20

# Home-advantage bonus, in Elo points, added to the home side's rating when a match
# is not played at a neutral venue. Defaults to 0.0 so neutral-venue tournaments
# (the World Cup) are unaffected; domestic competitions pass a fitted value.
DEFAULT_HOME_ADVANTAGE = 0.0

# FIFA World Ranking approximation for WC 2026 qualified teams only (48 teams).
# Based on FIFA ranking at tournament start, June 2026.
FIFA_RANKING_2026: dict[str, int] = {
    # Rank 1-16: elite / likely contenders
    "Argentina": 1,  "France": 2,    "Spain": 3,      "England": 4,
    "Brazil": 5,     "Portugal": 6,  "Germany": 7,    "Netherlands": 8,
    "Colombia": 9,   "Belgium": 10,  "Uruguay": 11,   "Japan": 12,
    "USA": 13,       "Morocco": 14,  "Croatia": 15,   "Mexico": 16,
    # Rank 17-32: solid qualifiers
    "Ecuador": 17,          "Switzerland": 18,     "South Korea": 19,  "Turkey": 20,
    "Senegal": 21,          "Canada": 22,          "Norway": 23,       "Austria": 24,
    "Australia": 25,        "Sweden": 26,          "Algeria": 27,      "Scotland": 28,
    "Bosnia-Herzegovina": 29, "Czech Republic": 30, "South Africa": 31, "Egypt": 32,
    # Rank 33-48: lower-ranked qualifiers
    "Ivory Coast": 33,  "Iran": 34,      "Tunisia": 35,   "Saudi Arabia": 36,
    "Ghana": 37,        "Paraguay": 38,  "Panama": 39,    "New Zealand": 40,
    "Iraq": 41,         "Jordan": 42,    "Cape Verde": 43, "DR Congo": 44,
    "Qatar": 45,        "Uzbekistan": 46, "Curacao": 47,  "Haiti": 48,
}


def _rank_to_elo(rank: int, n_teams: int = 48, base: float = 1500.0, scale: float = 15.0) -> float:
    """Linear mapping: rank 1 → base + (n-1)*scale, rank n → base."""
    return base + (n_teams - rank) * scale


class EloRatings:
    """
    Team-level Elo ratings with match-type K-factor weighting.
    K-factors: 60 (WC), 40 (qualifier/major tournament), 20 (friendly), 20 (league).

    `home_advantage` is expressed in Elo points and applied to the home side whenever
    a match is played with `neutral=False`. It defaults to 0.0, which reproduces
    neutral-venue behaviour exactly.
    """

    def __init__(
        self,
        k_world_cup: int = K_WORLD_CUP,
        k_qualifier: int = K_QUALIFIER,
        k_friendly: int = K_FRIENDLY,
        base: float = DEFAULT_ELO,
        k_league: int = K_LEAGUE,
        home_advantage: float = DEFAULT_HOME_ADVANTAGE,
    ) -> None:
        self.k_world_cup = k_world_cup
        self.k_qualifier = k_qualifier
        self.k_friendly = k_friendly
        self.base = base
        self.k_league = k_league
        self.home_advantage = home_advantage
        self._ratings: dict[str, float] = {}

    def _rating_diff(self, home: str, away: str, neutral: bool) -> float:
        """Rating gap seen by the logistic, including home advantage where it applies."""
        dr = self.get_rating(home) - self.get_rating(away)
        if not neutral:
            dr += self.home_advantage
        return dr

    def seed_from_ranking(
        self,
        ranking: Optional[dict[str, int]] = None,
        n_teams: int = 48,
    ) -> None:
        """
        Initialise ratings from a rank dict {team: rank}.
        Defaults to FIFA_RANKING_2026 if not provided.
        """
        ranking = ranking or FIFA_RANKING_2026
        for team, rank in ranking.items():
            self._ratings[team] = _rank_to_elo(rank, n_teams=n_teams, base=self.base)
        logger.info("Elo seeded for %d teams from FIFA ranking.", len(ranking))

    def get_rating(self, team: str) -> float:
        return self._ratings.get(team, self.base)

    def update(
        self,
        home: str,
        away: str,
        home_score: int,
        away_score: int,
        tournament_type: str = "qualifier",
        neutral: bool = True,
    ) -> tuple[float, float]:
        """
        Update Elo after a match result. Returns (new_home_elo, new_away_elo).
        tournament_type: "world_cup" | "qualifier" | "friendly"
        """
        k = {
            "world_cup": self.k_world_cup,
            "qualifier": self.k_qualifier,
            "friendly": self.k_friendly,
            "league": self.k_league,
        }.get(tournament_type, self.k_qualifier)

        r_h = self.get_rating(home)
        r_a = self.get_rating(away)

        # Expected score for home team, including home advantage when not at a
        # neutral venue. Rating updates must use the same expectation the model
        # would have predicted, or home wins are systematically over-rewarded.
        dr = self._rating_diff(home, away, neutral)
        e_h = 1.0 / (1.0 + 10 ** (-dr / 400.0))
        e_a = 1.0 - e_h

        # Actual score
        if home_score > away_score:
            s_h, s_a = 1.0, 0.0
        elif home_score == away_score:
            s_h, s_a = 0.5, 0.5
        else:
            s_h, s_a = 0.0, 1.0

        new_r_h = r_h + k * (s_h - e_h)
        new_r_a = r_a + k * (s_a - e_a)
        self._ratings[home] = new_r_h
        self._ratings[away] = new_r_a
        return new_r_h, new_r_a

    def expected_outcome(self, home: str, away: str, neutral: bool = True) -> tuple[float, float]:
        """
        Return (P_home_wins, P_away_or_draw) using the Elo formula.
        Note: Elo does not model draws; use this as a directional prior only.
        """
        dr = self._rating_diff(home, away, neutral)
        p_home = 1.0 / (1.0 + 10 ** (-dr / 400.0))
        return p_home, 1.0 - p_home

    def to_dataframe(self) -> pd.DataFrame:
        rows = [{"team": t, "elo_rating": r} for t, r in sorted(
            self._ratings.items(), key=lambda x: -x[1]
        )]
        return pd.DataFrame(rows)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._ratings, indent=2))

    @classmethod
    def load(cls, path: Path) -> "EloRatings":
        obj = cls()
        obj._ratings = json.loads(path.read_text())
        return obj
