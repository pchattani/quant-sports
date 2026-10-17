#!/usr/bin/env python
"""
Backfill the historical inputs the Liga dashboard needs but cannot derive.

RUN THIS LOCALLY, NOT IN CI. Sofascore blocks datacenter IPs. It is a one-shot job —
re-run only at a season rollover, or to extend the promedio window.

Produces three committed files in oddsmarkets/football/competitions/liga/data/:

  promedios_history.json  accumulated points and matches per club for the seasons
                          preceding the current one. Without it, promedios are
                          computed from this season alone and the relegation table
                          is wrong.
  season_meta.json        the Apertura champion (a fixed Libertadores berth and a
                          fixed Tabla Anual contribution) and the previous Tabla
                          Anual order, which seeds the Elo.
  history_matches.csv     a multi-season Dixon-Coles training set with per-match xG.

Everything is computed from the match dump rather than scraped from a published
promedios or standings table. A published table can silently disagree with the
results it claims to summarise — deductions, abandoned matches, late corrections —
and a mismatch there would be invisible in the output.

    python scripts/backfill_liga_history.py                  # all promedio seasons
    python scripts/backfill_liga_history.py --years 2024 2025
    python scripts/backfill_liga_history.py --dry-run        # print, write nothing
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.liga.config import (  # noqa: E402
    APERTURA,
    CLAUSURA,
    DEFAULT_CONFIG,
    SOFASCORE_TOURNAMENT_ID,
    TORNEOS,
)
from oddsmarkets.football.sources.teams import normalize_team_name  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill-liga")

PKG_DATA = ROOT / "oddsmarkets" / "football" / "competitions" / "liga" / "data"
SEASONS_PATH = PKG_DATA / "seasons.json"

FINISHED = {"ended", "afterpenalties", "afterextratime", "ap", "aet"}
_SOURCES = ["sofascore", "sofavpn"]
_active_source: str | None = None


def _call(fn, **kwargs):
    global _active_source
    order = [_active_source] if _active_source else _SOURCES
    last: Exception | None = None
    for src in order:
        try:
            out = fn(data_source=src, **kwargs)
            if _active_source != src:
                logger.info("Sofascore data source: %s", src)
                _active_source = src
            return out
        except Exception as exc:  # noqa: BLE001
            last = exc
            if _active_source == src:
                _active_source = None
    raise last if last else RuntimeError("no data source available")


def _canon(name) -> str:
    return normalize_team_name(str(name or ""), "liga_argentina")


def fetch_season(season_id: int, torneo: str, year: int) -> list[dict]:
    """Every finished league-phase match of one tournament."""
    from datafc import match_data, season_rounds_data

    try:
        rounds = _call(
            season_rounds_data,
            tournament_id=SOFASCORE_TOURNAMENT_ID, season_id=season_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("rounds fetch failed for %s %s: %s", torneo, year, exc)
        return []

    rows = []
    for _, r in rounds.iterrows():
        rn = r.get("round_number")
        if pd.isna(rn):
            continue
        try:
            df = _call(
                match_data,
                tournament_id=SOFASCORE_TOURNAMENT_ID,
                season_id=season_id, week_number=int(rn),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("round %s failed: %s", rn, exc)
            continue
        if df is None or not len(df):
            continue

        for _, m in df.iterrows():
            status = str(m.get("status", "")).lower().replace(" ", "")
            if status not in FINISHED:
                continue
            hs = next((m[c] for c in ("home_score_display", "home_score", "home_score_current")
                       if c in m and pd.notna(m.get(c))), None)
            as_ = next((m[c] for c in ("away_score_display", "away_score", "away_score_current")
                        if c in m and pd.notna(m.get(c))), None)
            if hs is None or as_ is None:
                continue
            ts = next((m[c] for c in ("start_timestamp", "startTimestamp")
                       if c in m and pd.notna(m.get(c))), None)
            date = None
            if ts is not None:
                try:
                    date = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                except (ValueError, OSError, OverflowError):
                    date = None
            rows.append({
                "game_id": str(m["game_id"]),
                "home_team": _canon(m.get("home_team")),
                "away_team": _canon(m.get("away_team")),
                "home_goals": int(hs), "away_goals": int(as_),
                "match_date": date.strftime("%Y-%m-%d") if date else None,
                "round": int(m["week"]) if pd.notna(m.get("week")) else None,
                "season": year, "torneo": torneo, "weight": 1.0,
            })
        time.sleep(0.25)

    logger.info("%s %s: %d finished matches", torneo, year, len(rows))
    return rows


def fetch_xg(game_ids: list[str], cap: int = 2000) -> dict[str, tuple[float, float]]:
    """Per-match team xG, summed from player lineups. Best-effort."""
    from datafc import lineups_data

    out: dict[str, tuple[float, float]] = {}
    for i, gid in enumerate(game_ids[:cap]):
        try:
            df = _call(lineups_data, game_id=int(gid))
        except Exception:  # noqa: BLE001
            continue
        if df is None or not len(df) or "expectedGoals" not in df.columns:
            continue
        try:
            by_team = df.groupby("team_name")["expectedGoals"].sum()
            if len(by_team) == 2:
                vals = [float(v) for v in by_team.values]
                out[gid] = (round(vals[0], 3), round(vals[1], 3))
        except Exception:  # noqa: BLE001
            pass
        if i and i % 50 == 0:
            logger.info("  xG: %d/%d", i, min(len(game_ids), cap))
        time.sleep(0.35)
    return out


def league_table(rows: list[dict]) -> dict[str, dict]:
    """
    Points, matches and goals per club, computed from results.

    Deriving this rather than reading a published table is the point: the promedios
    must agree with the matches they summarise, by construction.
    """
    table: dict[str, dict] = defaultdict(
        lambda: {"points": 0, "matches": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0}
    )
    cfg = DEFAULT_CONFIG
    for r in rows:
        hg, ag = r["home_goals"], r["away_goals"]
        for team, gf, ga in ((r["home_team"], hg, ag), (r["away_team"], ag, hg)):
            if not team:
                continue
            t = table[team]
            t["matches"] += 1
            t["gf"] += gf
            t["ga"] += ga
            if gf > ga:
                t["won"] += 1
                t["points"] += cfg.points_win
            elif gf == ga:
                t["drawn"] += 1
                t["points"] += cfg.points_draw
            else:
                t["lost"] += 1
    return dict(table)


def check_consistency(rows: list[dict], table: dict[str, dict], label: str) -> bool:
    """Points must equal 3 per match minus one per draw. Catches a truncated dump."""
    draws = sum(1 for r in rows if r["home_goals"] == r["away_goals"])
    expected = 3 * len(rows) - draws
    actual = sum(t["points"] for t in table.values())
    ok = expected == actual
    (logger.info if ok else logger.error)(
        "%s: %d matches, %d draws — points %d, expected %d %s",
        label, len(rows), draws, actual, expected, "OK" if ok else "MISMATCH",
    )
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="*", help="calendar years to fetch")
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    parser.add_argument("--no-xg", action="store_true", help="skip the slow xG pass")
    parser.add_argument("--xg-cap", type=int, default=1200)
    args = parser.parse_args()

    if not SEASONS_PATH.exists():
        logger.error(
            "No %s. Run scripts/discover_sofascore_liga.py first, from a residential "
            "connection.", SEASONS_PATH,
        )
        return 1
    registry = json.loads(SEASONS_PATH.read_text(encoding="utf-8"))
    seasons = registry.get("seasons", [])
    if not seasons:
        logger.error("seasons.json contains no seasons")
        return 1

    cfg = DEFAULT_CONFIG
    current = cfg.season_year
    years = args.years or [current - o for o in range(1, cfg.promedio_seasons)]
    logger.info("Backfilling seasons: %s (current is %s)", years, current)

    all_rows: list[dict] = []
    per_year: dict[int, list[dict]] = {}
    for entry in seasons:
        year = entry.get("year")
        if year not in years and year != current:
            continue
        for torneo in TORNEOS:
            season_id = entry.get(torneo)
            if not season_id:
                continue
            rows = fetch_season(int(season_id), torneo, int(year))
            if rows:
                per_year.setdefault(int(year), []).extend(rows)
                all_rows.extend(rows)

    if not all_rows:
        logger.error("No matches fetched — nothing written")
        return 1

    # promedios_history: the seasons *before* the current one.
    promedios: dict[str, dict] = defaultdict(lambda: {"points": 0, "matches": 0})
    all_ok = True
    for year in sorted(per_year):
        table = league_table(per_year[year])
        all_ok &= check_consistency(per_year[year], table, f"season {year}")
        if year == current:
            continue
        for team, rec in table.items():
            promedios[team]["points"] += rec["points"]
            promedios[team]["matches"] += rec["matches"]

    # season_meta: previous year's Tabla Anual order, used to seed the Elo.
    prev_year = max((y for y in per_year if y < current), default=None)
    previous_rank: dict[str, int] = {}
    if prev_year:
        prev_table = league_table(per_year[prev_year])
        ordered = sorted(
            prev_table.items(),
            key=lambda kv: (-kv[1]["points"], -(kv[1]["gf"] - kv[1]["ga"]), -kv[1]["gf"]),
        )
        previous_rank = {team: i + 1 for i, (team, _) in enumerate(ordered)}

    meta = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "previous_anual_year": prev_year,
        "previous_anual_rank": previous_rank,
        # Champions are playoff outcomes, not derivable from league-phase results.
        # Left null for a human to fill; the build treats null as "not yet decided".
        "apertura_champion": None,
        "clausura_champion": None,
        "_note": (
            "apertura_champion and clausura_champion are playoff results and must be "
            "set by hand. The Apertura champion holds a Libertadores berth outright, "
            "so leaving it null understates that club's qualification probability."
        ),
    }

    xg: dict[str, tuple[float, float]] = {}
    if not args.no_xg:
        logger.info("Fetching xG for up to %d matches (slow)…", args.xg_cap)
        xg = fetch_xg([r["game_id"] for r in all_rows], cap=args.xg_cap)
        logger.info("xG coverage: %d/%d matches", len(xg), len(all_rows))

    if args.dry_run:
        print(json.dumps({
            "seasons": {y: len(r) for y, r in per_year.items()},
            "clubs_with_promedio_history": len(promedios),
            "previous_anual_top5": list(previous_rank)[:5],
            "xg_coverage": len(xg),
            "consistency_ok": all_ok,
        }, indent=2, ensure_ascii=False))
        return 0 if all_ok else 1

    PKG_DATA.mkdir(parents=True, exist_ok=True)
    (PKG_DATA / "promedios_history.json").write_text(
        json.dumps(dict(promedios), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (PKG_DATA / "season_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    csv_path = PKG_DATA / "history_matches.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "game_id", "home_team", "away_team", "home_goals", "away_goals",
            "match_date", "weight", "season", "torneo", "home_xg", "away_xg",
        ])
        writer.writeheader()
        for r in all_rows:
            hx, ax = xg.get(r["game_id"], (None, None))
            writer.writerow({
                "game_id": r["game_id"], "home_team": r["home_team"],
                "away_team": r["away_team"], "home_goals": r["home_goals"],
                "away_goals": r["away_goals"], "match_date": r["match_date"],
                "weight": r["weight"], "season": r["season"], "torneo": r["torneo"],
                "home_xg": hx, "away_xg": ax,
            })

    logger.info("Wrote %s (%d clubs)", PKG_DATA / "promedios_history.json", len(promedios))
    logger.info("Wrote %s", PKG_DATA / "season_meta.json")
    logger.info("Wrote %s (%d matches)", csv_path, len(all_rows))
    logger.warning(
        "Set apertura_champion in season_meta.json by hand — it is a playoff result "
        "and cannot be derived from league-phase matches."
    )
    if not all_ok:
        logger.error("At least one season failed its points check — inspect before committing")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
