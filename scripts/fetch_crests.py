#!/usr/bin/env python
"""
Download club crests for every team in every store into docs/site/assets/crests/.

Sofascore serves a PNG per team id, but only to a browser-shaped client: a plain
request gets a 403, so hot-linking from the published site is not an option and
the images are committed beside it instead. ~5 KB each, a few hundred clubs.

RUN LOCALLY (residential connection), after the stores have been fetched — team
ids come from the stores. Only missing crests are fetched, so re-running is cheap;
`--refresh` re-downloads everything.

    python scripts/fetch_crests.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.cup.config import CUPS  # noqa: E402
from oddsmarkets.football.competitions.league.config import LEAGUES  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fetch-crests")

CRESTS_DIR = ROOT / "docs" / "site" / "assets" / "crests"
STORES = [ROOT / "docs" / "site" / "data" / slug / "store.json" for slug in list(LEAGUES) + list(CUPS)]
STORES.append(ROOT / "docs" / "liga" / "data" / "liga_store.json")
PAUSE_S = 0.3


def team_ids(store_path: Path, current_only: bool = True) -> set[int]:
    """Ids of every club in the store's live season (relegated clubs need no crest)."""
    if not store_path.exists():
        return set()
    store = json.loads(store_path.read_text(encoding="utf-8"))
    season = (store.get("meta") or {}).get("season_id")
    ids: set[int] = set()
    for m in (store.get("matches") or {}).values():
        if current_only and season is not None and m.get("season_id") not in (season, None):
            continue
        for key in ("home_id", "away_id"):
            if m.get(key):
                ids.add(int(m[key]))
    return ids


def fetch_one(team_id: int, dest: Path) -> bool:
    from curl_cffi import requests as curl_requests

    for host in ("api.sofascore.app", "api.sofascore.com"):
        try:
            resp = curl_requests.get(
                f"https://{host}/api/v1/team/{team_id}/image", impersonate="chrome", timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: %s", team_id, exc)
            continue
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
            dest.write_bytes(resp.content)
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-download existing crests too")
    args = parser.parse_args()

    ids: set[int] = set()
    for path in STORES:
        found = team_ids(path)
        logger.info("%s: %d clubs", path.parent.name, len(found))
        ids |= found
    if not ids:
        logger.error("No team ids in any store — fetch the stores first (the fetchers record ids).")
        return 1

    CRESTS_DIR.mkdir(parents=True, exist_ok=True)
    done = failed = skipped = 0
    for team_id in sorted(ids):
        dest = CRESTS_DIR / f"{team_id}.png"
        if dest.exists() and not args.refresh:
            skipped += 1
            continue
        if fetch_one(team_id, dest):
            done += 1
        else:
            failed += 1
        time.sleep(PAUSE_S)
    logger.info("crests: %d fetched, %d already present, %d failed", done, skipped, failed)
    if done:
        # The kit colours the Broadcast heroes use come from the crests (the public build ships no crests, so the
        # derived table is what CI reads): re-derive it, then commit oddsmarkets/football/analytics/data/club_colours.json.
        from oddsmarkets.football.analytics import colours
        rows = colours.refresh(CRESTS_DIR)
        logger.info("club colours: %d clubs -> %s (commit it)", len(rows), colours.TABLE)
    return 0 if (done or skipped) else 1


if __name__ == "__main__":
    raise SystemExit(main())
