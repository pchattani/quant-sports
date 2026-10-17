"""
Build data/match_xg.csv from StatsBomb Open Data (free, no API key needed).

Source: https://github.com/statsbomb/open-data
Covers: WC 2022, EURO 2024, Copa América 2024  (highest-weighted training matches)

Usage:
    uv run python scripts/build_xg_data.py

Output columns: home_team, away_team, match_date, home_xg, away_xg, competition, source
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).parent.parent
OUT_CSV = ROOT / "data" / "match_xg.csv"

SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# Competitions to fetch: (label, competition_id, season_id)
COMPETITIONS = [
    ("WC 2022",       43,   106),
    ("EURO 2024",     55,   282),
    ("Copa Am 2024", 223,   282),
    ("AFCON 2023",  1267,   107),  # Africa Cup of Nations — covers Morocco, Ivory Coast, Senegal, etc.
    ("EURO 2020",     55,    43),  # lower weight (~3.5%) but adds European coverage
    ("WC 2018",       43,     3),  # ~0.5% decay weight but harmless
]

# StatsBomb name → our canonical name
SB_ALIASES: dict[str, str] = {
    "United States":           "USA",
    "Bosnia and Herzegovina":  "Bosnia-Herzegovina",
    "Côte d'Ivoire":           "Ivory Coast",
    "Côte d'Ivoire":      "Ivory Coast",   # encoded variant
    "Cote d'Ivoire":           "Ivory Coast",
    "Cape Verde Islands":      "Cape Verde",
    "Congo DR":                "DR Congo",
    "Republic of Ireland":     "Ireland",
    "Korea Republic":          "South Korea",
    "China PR":                "China",
}


def canon(name: str) -> str:
    return SB_ALIASES.get(name, name)


def fetch_json(url: str, retries: int = 3) -> list | dict | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(1)
    return None


def xg_from_events(match_id: int, sb_home: str, sb_away: str) -> tuple[float, float] | None:
    """Return (home_xg, away_xg) by summing statsbomb_xg from shot events.

    sb_home / sb_away are the raw StatsBomb team names (before alias mapping),
    used to split shots by team correctly.
    """
    url = f"{SB_BASE}/events/{match_id}.json"
    events = fetch_json(url)
    if not events:
        return None

    hxg = 0.0
    axg = 0.0

    for e in events:
        if e.get("type", {}).get("name") != "Shot":
            continue
        shot = e.get("shot", {})
        xg = shot.get("statsbomb_xg")
        if xg is None:
            continue
        # Own goals don't count toward the shooting team's xG
        if shot.get("outcome", {}).get("name") == "Own Goal":
            continue

        team = e.get("team", {}).get("name", "")
        if team == sb_home:
            hxg += xg
        elif team == sb_away:
            axg += xg
        # else: unknown team (shouldn't happen in clean data)

    return hxg, axg


def process_match(m: dict, label: str) -> dict | None:
    """Fetch events for one match and return an xG row."""
    match_id = m["match_id"]
    sb_home = m["home_team"]["home_team_name"]
    sb_away = m["away_team"]["away_team_name"]
    home = canon(sb_home)
    away = canon(sb_away)
    date = m["match_date"]

    hxg, axg = xg_from_events(match_id, sb_home, sb_away)
    return {
        "home_team": home,
        "away_team": away,
        "match_date": date,
        "home_xg": round(hxg, 4),
        "away_xg": round(axg, 4),
        "home_goals": m.get("home_score"),
        "away_goals": m.get("away_score"),
        "competition": label,
        "source": "statsbomb",
    }


def main() -> None:
    rows: list[dict] = []
    total_matches = 0

    for label, cid, sid in COMPETITIONS:
        print(f"\nFetching {label} (comp={cid}, season={sid})...")
        matches = fetch_json(f"{SB_BASE}/matches/{cid}/{sid}.json")
        if not matches:
            print(f"  ERROR: could not fetch match list")
            continue
        print(f"  {len(matches)} matches — downloading events in parallel...")
        total_matches += len(matches)

        done = 0
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(process_match, m, label): m for m in matches}
            for fut in as_completed(futures):
                result = fut.result()
                if result:
                    rows.append(result)
                done += 1
                if done % 20 == 0 or done == len(matches):
                    print(f"  {done}/{len(matches)} processed ({len(rows)} rows so far)")

    if not rows:
        print("No rows collected — check network access.")
        sys.exit(1)

    df = pd.DataFrame(rows).sort_values(["match_date", "home_team"])

    # Sanity check: xG vs goals correlation
    df_check = df.dropna(subset=["home_goals", "away_goals"])
    total_goals = df_check["home_goals"].sum() + df_check["away_goals"].sum()
    total_xg = df_check["home_xg"].sum() + df_check["away_xg"].sum()
    print(f"\nSanity: total goals={total_goals}, total xG={total_xg:.0f}, ratio={total_goals/total_xg:.3f}")

    # Drop goals columns (only needed for sanity check)
    out = df[["home_team", "away_team", "match_date", "home_xg", "away_xg", "competition", "source"]]
    out.to_csv(OUT_CSV, index=False)
    print(f"Saved {len(out)} xG records to {OUT_CSV}")
    print(f"\nCoverage: {len(out)}/{total_matches} matches ({100*len(out)/total_matches:.0f}%)")

    # Per-competition breakdown
    print("\nBreakdown:")
    for comp, grp in out.groupby("competition"):
        print(f"  {comp:20s}: {len(grp)} matches")


if __name__ == "__main__":
    main()
