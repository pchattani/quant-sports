"""
Build data/historical_matches.csv from the raw international results dataset.

Source: martj42/international_results (downloaded to data/raw_intl_results.csv)
Run once (or re-run to refresh):
    uv run python scripts/build_historical_data.py

Output columns: home_team, away_team, home_goals, away_goals, match_date, weight
  - weight reflects match importance BEFORE time-decay (DC fit applies xi=0.0018/day on top)
  - Only keeps matches from 2022-01-01 onwards so time-decay stays meaningful
  - Only keeps matches where at least one team is a WC 2026 qualifier
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

RAW_CSV = ROOT / "data" / "raw_intl_results.csv"
OUT_CSV = ROOT / "data" / "historical_matches.csv"

# Canonical WC 2026 team names (from simulator)
from oddsmarkets.sports.world_cup.trading.simulator import WC2026_GROUPS
WC_TEAMS: set[str] = {t for teams in WC2026_GROUPS.values() for t in teams}

# Raw dataset name → our canonical name
ALIASES: dict[str, str] = {
    "United States":        "USA",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    # Entries that are already canonical need no mapping
}

# Tournament type → match importance weight (before time-decay)
# Higher = more weight in the DC likelihood
TOURNAMENT_WEIGHTS: dict[str, float] = {
    "FIFA World Cup":                           1.00,
    "UEFA Euro":                                0.88,
    "Copa América":                             0.88,
    "Copa América":                        0.88,   # accent variant in dataset
    "African Cup of Nations":                   0.85,
    "AFC Asian Cup":                            0.85,
    "Gold Cup":                                 0.80,
    "CONCACAF Nations League":                  0.72,
    "UEFA Nations League":                      0.72,
    "FIFA World Cup qualification":             0.62,
    "UEFA Euro qualification":                  0.60,
    "African Cup of Nations qualification":     0.58,
    "AFC Asian Cup qualification":              0.58,
    "Gold Cup qualification":                   0.55,
    "FIFA Series":                              0.65,
    "Friendly":                                 0.30,
}
DEFAULT_WEIGHT = 0.45   # anything else (regional cups, etc.)

MIN_DATE = "2022-01-01"


def normalize(name: str) -> str:
    return ALIASES.get(name, name)


def main() -> None:
    if not RAW_CSV.exists():
        print(f"ERROR: {RAW_CSV} not found. Download it first:")
        print("  Invoke-WebRequest -Uri https://raw.githubusercontent.com/martj42/international_results/master/results.csv -OutFile data/raw_intl_results.csv")
        sys.exit(1)

    df = pd.read_csv(RAW_CSV, parse_dates=["date"])
    total_raw = len(df)

    # Filter to recent matches only
    df = df[df["date"] >= MIN_DATE].copy()
    print(f"Raw rows: {total_raw:,}  ->  since {MIN_DATE}: {len(df):,}")

    # Normalize team names
    df["home_team"] = df["home_team"].map(normalize)
    df["away_team"] = df["away_team"].map(normalize)

    # Keep only matches where at least one team is in WC 2026
    mask = df["home_team"].isin(WC_TEAMS) | df["away_team"].isin(WC_TEAMS)
    df = df[mask].copy()
    print(f"After WC-team filter: {len(df):,} matches")

    # Drop rows with missing scores (scheduled/future matches in the dataset)
    df = df.dropna(subset=["home_score", "away_score"]).copy()
    print(f"After dropping missing scores: {len(df):,} matches")

    # Assign importance weight by tournament type
    df["weight"] = df["tournament"].map(TOURNAMENT_WEIGHTS).fillna(DEFAULT_WEIGHT)

    # Rename / reformat columns
    out = pd.DataFrame({
        "home_team":  df["home_team"],
        "away_team":  df["away_team"],
        "home_goals": df["home_score"].astype(int),
        "away_goals": df["away_score"].astype(int),
        "match_date": df["date"].dt.strftime("%Y-%m-%d"),
        "weight":     df["weight"].round(4),
        "tournament": df["tournament"],
    })
    out = out.reset_index(drop=True)

    # Sanity check: which WC teams have the most matches?
    all_teams = pd.concat([out["home_team"], out["away_team"]])
    team_counts = all_teams.value_counts()
    print("\nMatches per WC team (top 10 / bottom 10):")
    wc_counts = team_counts[team_counts.index.isin(WC_TEAMS)]
    print(wc_counts.head(10).to_string())
    print("...")
    print(wc_counts.tail(10).to_string())

    # Check teams with very few matches
    sparse = wc_counts[wc_counts < 5]
    if not sparse.empty:
        print(f"\nWarning: {len(sparse)} WC teams with < 5 historical matches:")
        print(sparse.to_string())

    # Count by tournament type
    print("\nMatches by tournament (top 10):")
    print(out["tournament"].value_counts().head(10).to_string())

    out.to_csv(OUT_CSV, index=False)
    print(f"\nSaved {len(out):,} matches to {OUT_CSV}")


if __name__ == "__main__":
    main()
