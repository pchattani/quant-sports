#!/usr/bin/env python
"""
CI hydrate for The Quant Campus (CONTRACT.md 1.3): make sure the season stores are on disk before a build.

The stores are not in git. On CI they come back from the Actions cache (content key) or the `seed-campus` branch
(the lead's pipeline restores those before this runs). This script then checks, per level, that every season's
store is present and loads, reports what is missing or unreadable, and, when `--seed-base` is given (a URL prefix
under which `stores/<L>/<S>.json.gz` and `cfb/plays/<S>.json.gz` are served, e.g. a raw seed-branch URL),
downloads only the missing files. Nothing to do when the cache restored everything.

    python scripts/cc_hydrate.py                                  # report only
    python scripts/cc_hydrate.py --levels cfb --require 2014-2025 # exit 1 if any of those seasons is missing
    python scripts/cc_hydrate.py --seed-base https://raw.githubusercontent.com/<owner>/<repo>/seed-campus/data/college
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

from oddsmarkets.college import canon  # noqa: E402
from oddsmarkets.college import store as st  # noqa: E402

logger = logging.getLogger("cc_hydrate")


def fetch(url: str, timeout: float = 120.0) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "oddsmarkets-campus-ci"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            logger.warning("%s: HTTP %s", url, exc.code)
        return None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        logger.warning("%s: %s", url, exc)
        return None


def _valid_gz_json(b: bytes) -> bool:
    try:
        json.loads(gzip.decompress(b).decode("utf-8"))
        return True
    except (OSError, ValueError, EOFError):
        return False


def _put(path: Path, b: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(b)
    tmp.replace(path)


def check(level: str, seasons: list[int], seed_base: str | None = None) -> dict:
    """{"present": [S], "missing": [S], "unreadable": [S], "downloaded": [S], "games": {S: n}}."""
    out = {"present": [], "missing": [], "unreadable": [], "downloaded": [], "games": {}}
    for y in seasons:
        p = st.store_path(level, y)
        if p.exists():
            s = st.read_gz(p)
            if isinstance(s, dict) and s.get("games") is not None:
                out["present"].append(y)
                out["games"][y] = len(s["games"])
                continue
            out["unreadable"].append(y)
        else:
            out["missing"].append(y)
        if seed_base:
            b = fetch(f"{seed_base.rstrip('/')}/stores/{level}/{y}.json.gz")
            if b and _valid_gz_json(b):
                _put(p, b)
                out["downloaded"].append(y)
                if canon.is_football(level):
                    pb = fetch(f"{seed_base.rstrip('/')}/cfb/plays/{y}.json.gz")
                    if pb and _valid_gz_json(pb):
                        _put(st.plays_path(y), pb)
    return out


def _seasons(spec: str | None, level: str) -> list[int]:
    cur = canon.current_season(level)
    if not spec:
        return list(range(canon.FIRST_SEASON[level], cur + 1))
    if "-" in spec:
        a, b = (int(x) for x in spec.split("-"))
        return list(range(min(a, b), max(a, b) + 1))
    return [int(x) for x in spec.split(",") if x]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", default=",".join(canon.LEVELS))
    ap.add_argument("--seasons", default=None, help="range 2001-2026 or comma list (default: every season)")
    ap.add_argument("--require", default=None, help="seasons that must be present (range or list); exit 1 if not")
    ap.add_argument("--seed-base", default=None, help="URL prefix to download missing stores from")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    bad = False
    for lv in [x for x in args.levels.split(",") if x]:
        lv = canon.level_of(lv)
        r = check(lv, _seasons(args.seasons, lv), args.seed_base)
        logger.info("%s: %d present, %d missing %s, %d unreadable %s, %d downloaded", lv, len(r["present"]), len(r["missing"]),
                    r["missing"], len(r["unreadable"]), r["unreadable"], len(r["downloaded"]))
        if args.require:
            need = set(_seasons(args.require, lv))
            have = set(r["present"]) | set(r["downloaded"])
            if need - have:
                logger.error("%s: required seasons missing: %s", lv, sorted(need - have))
                bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
