"""
Feature engineering for the World Cup 2026 odds model.
Builds rolling xG, goals, and form statistics per team as of a given date.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

GLOBAL_XG_MEAN = 1.15   # FIFA WC historical average xG per team per match
GLOBAL_XG_STD = 0.65
SHRINKAGE_PRIOR_N = 5   # Bayesian shrinkage: blend toward mean for < this many games

# Match-type weights: qualifier/major tournament = 1.0, friendly = 0.5
MATCH_TYPE_WEIGHTS: dict[str, float] = {
    "world_cup":   1.0,
    "qualifier":   1.0,
    "copa_america": 1.0,
    "euro":        1.0,
    "afcon":       1.0,
    "asian_cup":   1.0,
    "friendly":    0.5,
    "other":       0.75,
}


@dataclass
class TeamFeatureRow:
    team: str
    as_of_date: date
    elo_rating: Optional[float]
    xg_for_10: float
    xg_against_10: float
    goals_for_10: float
    goals_against_10: float
    form_5: float   # points per game (0-1 normalized): wins*3+draws / games*3
    matches_played: int


class FeatureBuilder:
    """
    Computes rolling per-team features from a flat match history DataFrame.

    Expected match DataFrame columns:
        home_team, away_team, home_goals, away_goals, match_date,
        home_xg (optional), away_xg (optional), match_type (optional)
    """

    def build_team_features(
        self,
        matches: pd.DataFrame,
        team: str,
        as_of_date: date,
        window: int = 10,
        form_window: int = 5,
    ) -> TeamFeatureRow:
        """Compute rolling features for a single team as of as_of_date."""
        df = self._get_team_matches(matches, team, as_of_date)

        n = len(df)
        if n == 0:
            return TeamFeatureRow(
                team=team,
                as_of_date=as_of_date,
                elo_rating=None,
                xg_for_10=GLOBAL_XG_MEAN,
                xg_against_10=GLOBAL_XG_MEAN,
                goals_for_10=GLOBAL_XG_MEAN,
                goals_against_10=GLOBAL_XG_MEAN,
                form_5=0.33,  # mean draw rate
                matches_played=0,
            )

        recent = df.tail(window)
        mtype_w = recent.get("match_type", pd.Series(["other"] * len(recent))).map(
            lambda x: MATCH_TYPE_WEIGHTS.get(x, 0.75)
        )

        xg_for = self._weighted_mean(recent, "xg_for", mtype_w, fallback_col="goals_for")
        xg_against = self._weighted_mean(recent, "xg_against", mtype_w, fallback_col="goals_against")
        goals_for = self._weighted_mean(recent, "goals_for", mtype_w)
        goals_against = self._weighted_mean(recent, "goals_against", mtype_w)

        # Bayesian shrinkage toward global mean for sparse data
        n_r = len(recent)
        xg_for = (n_r * xg_for + SHRINKAGE_PRIOR_N * GLOBAL_XG_MEAN) / (n_r + SHRINKAGE_PRIOR_N)
        xg_against = (n_r * xg_against + SHRINKAGE_PRIOR_N * GLOBAL_XG_MEAN) / (n_r + SHRINKAGE_PRIOR_N)

        # Form: points per game over last form_window matches (0..1 normalized)
        form_df = df.tail(form_window)
        if len(form_df) > 0:
            pts = form_df["result"].map({"win": 3, "draw": 1, "loss": 0}).sum()
            form_5 = pts / (len(form_df) * 3)
        else:
            form_5 = 0.33

        return TeamFeatureRow(
            team=team,
            as_of_date=as_of_date,
            elo_rating=None,  # filled in by pipeline after EloRatings
            xg_for_10=round(xg_for, 4),
            xg_against_10=round(xg_against, 4),
            goals_for_10=round(goals_for, 4),
            goals_against_10=round(goals_against, 4),
            form_5=round(form_5, 4),
            matches_played=n,
        )

    def build_all_teams(
        self,
        matches: pd.DataFrame,
        teams: list[str],
        as_of_date: date,
    ) -> pd.DataFrame:
        """Build features for all teams; returns a DataFrame matching team_features schema."""
        rows = []
        for team in teams:
            row = self.build_team_features(matches, team, as_of_date)
            rows.append(row.__dict__)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_team_matches(
        self, matches: pd.DataFrame, team: str, as_of_date: date
    ) -> pd.DataFrame:
        """Return matches involving team before as_of_date, with perspective columns."""
        cutoff = pd.Timestamp(as_of_date, tz="UTC")
        if matches["match_date"].dt.tz is None:
            dates = matches["match_date"].dt.tz_localize("UTC")
        else:
            dates = matches["match_date"]

        is_home = matches["home_team"] == team
        is_away = matches["away_team"] == team
        mask = (is_home | is_away) & (dates < cutoff)
        df = matches[mask].copy()

        if df.empty:
            return df

        df["goals_for"] = df.apply(
            lambda r: r["home_goals"] if r["home_team"] == team else r["away_goals"], axis=1
        )
        df["goals_against"] = df.apply(
            lambda r: r["away_goals"] if r["home_team"] == team else r["home_goals"], axis=1
        )
        df["xg_for"] = df.apply(
            lambda r: r.get("home_xg") if r["home_team"] == team else r.get("away_xg"), axis=1
        )
        df["xg_against"] = df.apply(
            lambda r: r.get("away_xg") if r["home_team"] == team else r.get("home_xg"), axis=1
        )
        df["result"] = df.apply(
            lambda r: (
                "win" if r["goals_for"] > r["goals_against"]
                else ("draw" if r["goals_for"] == r["goals_against"] else "loss")
            ),
            axis=1,
        )
        return df.sort_values("match_date")

    @staticmethod
    def _weighted_mean(
        df: pd.DataFrame, col: str, weights: pd.Series, fallback_col: Optional[str] = None
    ) -> float:
        series = df.get(col)
        if series is None or series.isna().all():
            if fallback_col:
                series = df.get(fallback_col)
            if series is None or series.isna().all():
                return GLOBAL_XG_MEAN
        valid = series.notna()
        if valid.sum() == 0:
            return GLOBAL_XG_MEAN
        w = weights[valid].values
        v = series[valid].values
        total_w = w.sum()
        return float((v * w).sum() / total_w) if total_w > 0 else float(v.mean())
