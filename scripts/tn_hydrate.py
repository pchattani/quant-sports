#!/usr/bin/env python
"""
Hydrate the current year's inputs from the deployed public site before an hourly CI build.

CI never commits the current year's store, so a fresh checkout may lack it (or hold an older committed
copy). This fetches, per tour, from

    https://pchattani.github.io/the-quant-ace/data/<T>/<year>/store.json
    https://pchattani.github.io/the-quant-ace/data/<T>/{registry.json, style.json}

and keeps whichever copy is newer (by "updated_at"; style.json by "_meta.updated_at"). The registry
travels with the store: identities the hourly fetch resolved are in the deployed registry, not the
checkout's. A 404 (the first deploy, or a tour with no store for the year yet) is not an error.

    python scripts/tn_hydrate.py                       # both tours, the current year
    python scripts/tn_hydrate.py --tours wta --base https://example.org/data
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

from oddsmarkets.tennis import canon  # noqa: E402

logger = logging.getLogger("tn_hydrate")
BASE = "https://pchattani.github.io/the-quant-ace/data"


def fetch(url: str, timeout: float = 60.0) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oddsmarkets-ace-ci"}), timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            logger.warning("%s: HTTP %s", url, exc.code)
        return None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        logger.warning("%s: %s", url, exc)
        return None


def _stamp(b: bytes | None, style: bool = False) -> str:
    if not b:
        return ""
    try:
        d = json.loads(b.decode("utf-8"))
    except ValueError:
        return ""
    if not isinstance(d, dict):
        return ""
    if style:
        return str((d.get("_meta") or {}).get("updated_at") or "")
    return str(d.get("updated_at") or "")


def hydrate_file(url: str, local: Path, style: bool = False) -> str:
    """'remote' when the deployed copy replaced the local one, else 'local' / 'missing' / 'bad'."""
    remote = fetch(url)
    if remote is None:
        return "missing"
    try:
        json.loads(remote.decode("utf-8"))
    except ValueError:
        logger.warning("%s is not JSON; kept the checkout", url)
        return "bad"
    cur = local.read_bytes() if local.exists() else None
    if cur is not None and _stamp(cur, style) >= _stamp(remote, style):
        return "local"
    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(local.suffix + ".tmp")
    tmp.write_bytes(remote)
    tmp.replace(local)
    return "remote"


def hydrate(tour: str, year: int, base: str = BASE) -> dict:
    root = canon.data_root() / tour
    out = {"store": hydrate_file(f"{base}/{tour}/{year}/store.json", root / str(year) / "store.json"),
           "registry": hydrate_file(f"{base}/{tour}/registry.json", root / "registry.json"),
           "style": hydrate_file(f"{base}/{tour}/style.json", root / "style.json", style=True)}
    logger.info("%s %d: %s", tour, year, out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tours", nargs="*", choices=list(canon.TOURS), default=list(canon.TOURS))
    ap.add_argument("--year", type=int, default=None, help="default: the current year (UTC)")
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    year = args.year or datetime.now(timezone.utc).year
    for t in args.tours:
        hydrate(t, year, args.base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
