#!/usr/bin/env python
"""
Hydrate the current season's inputs from the deployed public site before an hourly CI build.

CI never commits the current season's inputs, so a fresh checkout may lack them (or hold an older
committed copy). This fetches, per league, from

    https://pchattani.github.io/the-quant-hardwood/data/<L>/<S>/{store.json, recon.json, shots.json.gz, stints.json.gz}

and keeps whichever store is newer (by its "updated_at"); the derived files follow the store they
were derived with. A 404 (the first deploy, or a league with no season yet) is not an error.

    python scripts/bb_hydrate.py                       # both leagues, their current seasons
    python scripts/bb_hydrate.py --leagues wnba --base https://example.org/data
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.basketball import canon  # noqa: E402
from oddsmarkets.basketball import store as st  # noqa: E402

logger = logging.getLogger("bb_hydrate")
BASE = "https://pchattani.github.io/the-quant-hardwood/data"
DERIVED = ("recon.json", "shots.json.gz", "stints.json.gz", "injury_log.json.gz")


def fetch(url: str, timeout: float = 60.0) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oddsmarkets-hardwood-ci"}), timeout=timeout) as r:
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


def hydrate(league: str, season: int, base: str = BASE) -> dict:
    d = st.season_dir(league, season)
    url = f"{base}/{league}/{season}"
    remote = fetch(f"{url}/store.json")
    if remote is None:
        logger.info("%s %d: no deployed store (first run?)", league, season)
        return {"store": "missing"}
    local_p = d / "store.json"
    local = local_p.read_bytes() if local_p.exists() else None
    if local is not None and _updated(local) >= _updated(remote):
        logger.info("%s %d: checkout store is current (%s)", league, season, _updated(local))
        return {"store": "local"}
    d.mkdir(parents=True, exist_ok=True)
    try:
        json.loads(remote.decode("utf-8"))
    except ValueError:
        logger.warning("%s %d: deployed store is not JSON; kept the checkout", league, season)
        return {"store": "bad"}
    local_p.write_bytes(remote)
    got = {"store": "remote"}
    for name in DERIVED:
        b = fetch(f"{url}/{name}")
        if b is None:
            continue
        if name.endswith(".gz"):
            try:
                gzip.decompress(b)
            except OSError:
                continue
        (d / name).write_bytes(b)
        got[name] = len(b)
        plain = d / name[:-3] if name.endswith(".gz") else None
        if plain is not None and plain.exists():
            plain.unlink()                                  # the hydrated .gz is the newer copy
    logger.info("%s %d: hydrated from the site (%s)", league, season, got)
    return got


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leagues", nargs="*", choices=list(canon.LEAGUES), default=list(canon.LEAGUES))
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for league in args.leagues:
        hydrate(league, canon.current_season(league), args.base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
