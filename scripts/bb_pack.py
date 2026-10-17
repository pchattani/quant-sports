#!/usr/bin/env python
"""
Gzip the derived model inputs of completed seasons for committing.

    docs/hardwood/data/<league>/<season>/shots.json   ->  shots.json.gz
    docs/hardwood/data/<league>/<season>/stints.json  ->  stints.json.gz

Storage rule: a completed season's store.json, recon.json, shots.json.gz and stints.json.gz are
committed (locally, by hand); the plain shots.json / stints.json are git-ignored. The current
season's inputs are never committed: CI rebuilds them every run from the play-by-play cache and the
deployed site. Every loader (models/_io.read_json, store.load_table) reads the .gz when the plain
file is missing or older, so a fresh checkout works from the .gz alone.

The current season of each league (canon.current_season) is skipped unless --include-current;
a season whose .gz is already newer than its plain file is left alone unless --force.

    python scripts/bb_pack.py                         # every completed season of both leagues
    python scripts/bb_pack.py --league nba --from 2017 --to 2026
    python scripts/bb_pack.py --league wnba --seasons 2025 --remove-plain
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.basketball import canon  # noqa: E402
from oddsmarkets.basketball import store as st  # noqa: E402

logger = logging.getLogger("bb_pack")
TABLES = ("shots.json", "stints.json")


def pack_season(league: str, season: int, force: bool = False, remove_plain: bool = False) -> list[Path]:
    """Write <table>.gz for each plain table of a season; returns the files written."""
    out = []
    d = st.season_dir(league, season)
    for name in TABLES:
        plain, gz = d / name, d / f"{name}.gz"
        if not plain.exists():
            continue
        if gz.exists() and gz.stat().st_mtime_ns >= plain.stat().st_mtime_ns and not force:
            if remove_plain:
                plain.unlink()
            continue
        try:
            obj = json.loads(plain.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("%s %d %s unreadable: %s", league, season, name, exc)
            continue
        p = st.save_table_gz(league, season, name, obj)
        with gzip.open(p, "rt", encoding="utf-8") as fh:            # verify before anything is removed
            if json.load(fh) != obj:
                raise RuntimeError(f"{p} does not round-trip")
        out.append(p)
        logger.info("%s %d %s: %.1f MB -> %.1f MB", league, season, name, plain.stat().st_size / 1e6, p.stat().st_size / 1e6)
        if remove_plain:
            plain.unlink()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", choices=canon.LEAGUES, nargs="*", default=list(canon.LEAGUES))
    ap.add_argument("--seasons", type=int, nargs="*", help="exact seasons (default: every season on disk)")
    ap.add_argument("--from", dest="start", type=int, default=None)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--include-current", action="store_true", help="also pack the current season")
    ap.add_argument("--force", action="store_true", help="rewrite the .gz even when it is up to date")
    ap.add_argument("--remove-plain", action="store_true", help="delete the plain file once its .gz is verified")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = 0
    for league in args.league:
        cur = canon.current_season(league)
        seasons = args.seasons or st.seasons_on_disk(league)
        for s in sorted(seasons):
            if (args.start and s < args.start) or (args.end and s > args.end):
                continue
            if s >= cur and not args.include_current:
                logger.info("%s %d: current season, skipped", league, s)
                continue
            n += len(pack_season(league, s, args.force, args.remove_plain))
    logger.info("%d files packed", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
