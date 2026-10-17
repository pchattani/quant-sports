#!/usr/bin/env python
"""
Hydrate the current season's store from the deployed public site before an hourly CI build.

CI never commits the current season's store, so a fresh checkout may lack it (or hold an older committed copy). This
fetches

    https://pchattani.github.io/the-quant-rink/data/<S>/store.json

and keeps whichever store is newer (by its "updated_at"). A 404 (the first deploy, or a season not yet published) is
not an error. Play-by-play, shifts and the derived tables are not hydrated: CI restores data/nhl (current season) from
the Actions cache and nhl_fetch.py --refresh-current tops it up.

    python scripts/nhl_hydrate.py                         # the current season
    python scripts/nhl_hydrate.py --season 20262027 --base https://example.org/data
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

from oddsmarkets.nhl import analytics as an  # noqa: E402

logger = logging.getLogger("nhl_hydrate")
BASE = "https://pchattani.github.io/the-quant-rink/data"


def fetch(url: str, timeout: float = 60.0) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oddsmarkets-rink-ci"}), timeout=timeout) as r:
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=None, help="season id, e.g. 20262027 (default: the current one)")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--data", default=None, help="data root (default RINK_DATA or docs/rink/data)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.data:
        an.set_data_root(args.data)
    hydrate(args.season or an.current_season(), args.base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
