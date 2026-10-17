"""
Historical match dataset builder for Dixon-Coles training.

Looks for data/historical_matches.csv in the project root.
Falls back to live WC matches only if no historical file is present.
The model degrades gracefully to Elo-only when both sources are empty.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from oddsmarkets.sports.world_cup.data.live_data import MatchResult

logger = logging.getLogger(__name__)

# Project root: oddsmarkets/sports/world_cup/data/ → up 5 levels
_DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "data"
_HIST_CSV = _DATA_DIR / "historical_matches.csv"
_XG_CSV   = Path(__file__).parent / "match_xg.csv"


def _load_xg_lookup() -> pd.DataFrame | None:
    """Load match_xg.csv and return a lookup keyed on (home_team, away_team, date_str)."""
    if not _XG_CSV.exists():
        return None
    try:
        xg = pd.read_csv(_XG_CSV, parse_dates=["match_date"])
        xg["_date_str"] = xg["match_date"].dt.strftime("%Y-%m-%d")

        # StatsBomb xG systematically overestimates actual goals (ratio ~0.84).
        # Scale xG to goals-scale so mixed observations are on a consistent axis.
        total_goals = (
            xg["home_xg"].sum() + xg["away_xg"].sum()
        )  # placeholder — actual calibration below
        # Load calibration from the CSV's goals columns if available
        if "home_goals" in xg.columns and "away_goals" in xg.columns:
            g_total = xg["home_goals"].sum() + xg["away_goals"].sum()
            x_total = xg["home_xg"].sum() + xg["away_xg"].sum()
            calib = g_total / x_total if x_total > 0 else 1.0
        else:
            calib = 0.839   # measured from 262 StatsBomb matches
        logger.info(
            "Loaded %d xG records (calibration factor=%.3f applied)", len(xg), calib
        )
        xg["home_xg"] = xg["home_xg"] * calib
        xg["away_xg"] = xg["away_xg"] * calib
        return xg
    except Exception as exc:
        logger.warning("Failed to load xG CSV: %s", exc)
        return None


def _merge_xg(df: pd.DataFrame, xg: pd.DataFrame) -> pd.DataFrame:
    """Merge xG data into training DataFrame by (home_team, away_team, date).

    Adds home_xg / away_xg columns; NaN for matches without xG data.
    """
    df = df.copy()
    df["_date_str"] = df["match_date"].dt.strftime("%Y-%m-%d")

    xg_lookup = xg.set_index(["home_team", "away_team", "_date_str"])[
        ["home_xg", "away_xg"]
    ]

    keys = list(zip(df["home_team"], df["away_team"], df["_date_str"]))
    home_xg_vals = []
    away_xg_vals = []
    for k in keys:
        if k in xg_lookup.index:
            row = xg_lookup.loc[k]
            home_xg_vals.append(float(row["home_xg"]))
            away_xg_vals.append(float(row["away_xg"]))
        else:
            home_xg_vals.append(np.nan)
            away_xg_vals.append(np.nan)

    df["home_xg"] = home_xg_vals
    df["away_xg"] = away_xg_vals
    df.drop(columns=["_date_str"], inplace=True)

    n_matched = int(np.isfinite(df["home_xg"]).sum())
    logger.info("xG merged: %d/%d matches have xG data", n_matched, len(df))
    return df


def build_training_dataset(
    live_finished: "list[MatchResult] | None" = None,
    live_xg: dict | None = None,
) -> pd.DataFrame:
    """
    Build a DataFrame for Dixon-Coles fitting.

    Columns: home_team, away_team, home_goals, away_goals, match_date, weight
             home_xg, away_xg  (float, NaN when unavailable)

    If data/historical_matches.csv exists, it is loaded first.
    live_finished WC matches are always appended on top.
    live_xg (optional): {frozenset({home, away}): {team: calibrated_xg}} — per-match
    team xG for THIS tournament (e.g. from Sofascore), already scaled to goal units.
    Where present it fills the live rows' xG so the DC fit uses the xG likelihood
    for current-tournament matches too (teams meet at most once in a WC, so the
    unordered pair is a safe key).
    Returns an empty DataFrame (with correct columns) when no data is available.
    """
    xg_lookup = _load_xg_lookup()
    dfs: list[pd.DataFrame] = []

    if _HIST_CSV.exists():
        try:
            df = pd.read_csv(_HIST_CSV, parse_dates=["match_date"])
            if df["match_date"].dt.tz is None:
                df["match_date"] = df["match_date"].dt.tz_localize("UTC")
            dfs.append(df)
            logger.info("Loaded %d historical matches from %s", len(df), _HIST_CSV)
        except Exception as exc:
            logger.warning("Failed to load historical CSV: %s", exc)
    else:
        # This path is the norm in CI, not an edge case: `_HIST_CSV` lives in the
        # repo-root `data/` directory, which .gitignore excludes, so the file produced
        # by scripts/build_historical_data.py never leaves a local checkout. The fit
        # then runs on live tournament matches alone. That is a large, silent
        # reduction in training data, so say so loudly rather than logging nothing.
        logger.warning(
            "No historical match file at %s — fitting on live matches only. "
            "This file is gitignored, so it is absent in CI unless it is moved "
            "inside a package data directory.",
            _HIST_CSV,
        )

    if live_finished:
        rows = [
            {
                "home_team": m.home_team,
                "away_team": m.away_team,
                "home_goals": int(m.home_goals),
                "away_goals": int(m.away_goals),
                "match_date": m.match_date or datetime.now(timezone.utc),
                "weight": 1.0,
                "_is_live": True,
            }
            for m in live_finished
            if m.home_goals is not None and m.away_goals is not None
        ]
        if rows:
            live_df = pd.DataFrame(rows)
            if live_df["match_date"].dt.tz is None:
                live_df["match_date"] = live_df["match_date"].dt.tz_localize("UTC")
            dfs.append(live_df)
            logger.info("Appended %d live WC matches to training data.", len(rows))

    if not dfs:
        return pd.DataFrame(
            columns=[
                "home_team", "away_team", "home_goals", "away_goals",
                "match_date", "weight", "home_xg", "away_xg",
            ]
        )

    result = pd.concat(dfs, ignore_index=True)
    result["home_goals"] = result["home_goals"].astype(int)
    result["away_goals"] = result["away_goals"].astype(int)

    # Merge xG where available
    if xg_lookup is not None:
        result = _merge_xg(result, xg_lookup)
    else:
        result["home_xg"] = np.nan
        result["away_xg"] = np.nan

    # Fill live-tournament xG (calibrated by the caller) — ONLY into rows that
    # are actually this tournament's matches (_is_live), never into historical
    # meetings of the same team pair.
    if live_xg and "_is_live" in result.columns:
        filled = 0
        for i, row in result.iterrows():
            # NB: historical rows have NaN here (column absent pre-concat) and
            # NaN is truthy — compare to True explicitly.
            if row.get("_is_live") is not True or np.isfinite(row["home_xg"]):
                continue
            entry = live_xg.get(frozenset((row["home_team"], row["away_team"])))
            if entry and row["home_team"] in entry and row["away_team"] in entry:
                result.at[i, "home_xg"] = float(entry[row["home_team"]])
                result.at[i, "away_xg"] = float(entry[row["away_team"]])
                filled += 1
        if filled:
            logger.info("Live xG filled for %d current-tournament matches.", filled)
    if "_is_live" in result.columns:
        result = result.drop(columns=["_is_live"])

    return result
