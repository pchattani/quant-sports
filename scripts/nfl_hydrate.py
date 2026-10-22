#!/usr/bin/env python
"""
Hydrate the current season's store from the deployed public site before an hourly CI build.

CI never commits the current season's store, so a fresh checkout may lack it (or hold an older committed copy). This
fetches

    https://pchattani.github.io/the-quant-gridiron/data/<S>/store.json

and keeps whichever store is newer (by its "updated_at"); likewise the timestamped ESPN injury snapshots
(<S>/injury_log.json.gz). A 404 (the first deploy, or a season not yet published) is
not an error. Play-by-play is not hydrated: CI restores data/nfl/raw from the Actions cache and the timestamp-gated
nflverse fetch tops it up.

    python scripts/nfl_hydrate.py                    # the current season
    python scripts/nfl_hydrate.py --season 2026 --base https://example.org/data
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.nfl import analytics as an  # noqa: E402

logger = logging.getLogger("nfl_hydrate")
BASE = "https://pchattani.github.io/the-quant-gridiron/data"


def fetch(url: str, timeout: float = 60.0) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oddsmarkets-gridiron-ci"}), timeout=timeout) as r:
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


def hydrate(season: int, base: str = BASE, fetcher=fetch) -> dict:
    p = an.store_path(season)
    remote = fetcher(f"{base}/{season}/store.json")
    if remote is None:
        logger.info("%d: no deployed store (first run?)", season)
        return {"store": "missing"}
    try:
        json.loads(remote.decode("utf-8"))
    except ValueError:
        logger.warning("%d: deployed store is not JSON; kept the checkout", season)
        return {"store": "bad"}
    local = p.read_bytes() if p.exists() else None
    if local is not None and _updated(local) >= _updated(remote):
        logger.info("%d: checkout store is current (%s)", season, _updated(local))
        return {"store": "local"}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_bytes(remote)
    tmp.replace(p)
    logger.info("%d: hydrated from the site (%d bytes, updated %s)", season, len(remote), _updated(remote))
    return {"store": "remote", "bytes": len(remote)}


def hydrate_injury_log(season: int, base: str = BASE, fetcher=fetch) -> str:
    """The timestamped ESPN injury snapshots (injury_log.json.gz, scripts/nfl_fetch.py): ESPN keeps no history, so the
    deployed copy is the record. Kept when the checkout has none or an older one (by its updated_at)."""
    import gzip
    from oddsmarkets.nfl import store as st
    remote = fetcher(f"{base}/{season}/{st.INJURY_LOG}")
    if remote is None:
        return "missing"
    try:
        r = json.loads(gzip.decompress(remote).decode("utf-8"))
    except (OSError, ValueError):
        logger.warning("%d: deployed injury log unreadable; kept the checkout", season)
        return "bad"
    p = st.injury_log_path(season)
    local = st.load_injury_log(season) if p.exists() else None
    if local is not None and str(local.get("updated_at") or "") >= str(r.get("updated_at") or ""):
        return "local"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".hydrate.tmp")
    tmp.write_bytes(remote)
    tmp.replace(p)
    logger.info("%d: injury log hydrated from the site (%d teams)", season, len(r.get("teams") or {}))
    return "remote"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=None, help="season (default: the current one)")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--data", default=None, help="data root (default GRIDIRON_DATA or docs/gridiron/data)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.data:
        an.set_data_root(args.data)
    season = args.season or an.current_season()
    hydrate(season, args.base)
    hydrate_injury_log(season, args.base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
