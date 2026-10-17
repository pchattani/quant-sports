#!/usr/bin/env python
"""
Hydrate the current season's stores from the deployed public site before an hourly CI build.

CI never commits the current season's store, so a fresh checkout may lack it (or hold an older committed copy).
This fetches, per level,

    https://pchattani.github.io/the-quant-bullpen/data/<L>/<S>/store.json

and keeps whichever store is newer (by its "updated_at"). A 404 (the first deploy, or a level with no season yet)
is not an error. The pitch tables are not hydrated: CI restores the current season's Parquet from the Actions
cache and mlb_fetch.py --refresh-current tops it up.

    python scripts/mlb_hydrate.py                         # both levels, their current season
    python scripts/mlb_hydrate.py --levels mlb --base https://example.org/data
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.baseball import canon  # noqa: E402
from oddsmarkets.baseball import store as st  # noqa: E402

logger = logging.getLogger("mlb_hydrate")
BASE = "https://pchattani.github.io/the-quant-bullpen/data"


def fetch(url: str, timeout: float = 60.0) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oddsmarkets-bullpen-ci"}), timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            logger.warning("%s: HTTP %s", url, exc.code)
        return None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        logger.warning("%s: %s", url, exc)
        return None


def _updated(b: bytes | None) -> str:
    if not b:
        return ""
    try:
        return str(json.loads(b.decode("utf-8")).get("updated_at") or "")
    except ValueError:
        return ""


def hydrate(level: str, season: int, base: str = BASE, fetcher=fetch) -> dict:
    p = st.season_path(level, season)
    remote = fetcher(f"{base}/{level}/{season}/store.json")
    if remote is None:
        logger.info("%s %d: no deployed store (first run?)", level, season)
        return {"store": "missing"}
    local = p.read_bytes() if p.exists() else None
    if local is not None and _updated(local) >= _updated(remote):
        logger.info("%s %d: checkout store is current (%s)", level, season, _updated(local))
        return {"store": "local"}
    try:
        json.loads(remote.decode("utf-8"))
    except ValueError:
        logger.warning("%s %d: deployed store is not JSON; kept the checkout", level, season)
        return {"store": "bad"}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(remote)
    logger.info("%s %d: hydrated from the site (%d bytes, updated %s)", level, season, len(remote), _updated(remote))
    return {"store": "remote", "bytes": len(remote)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", nargs="*", choices=list(canon.LEVELS), default=list(canon.LEVELS))
    ap.add_argument("--season", type=int, default=None, help="season (default: the current one)")
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    season = args.season or canon.current_season(datetime.now(timezone.utc).date())
    for level in args.levels:
        hydrate(level, season, args.base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
