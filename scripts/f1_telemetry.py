#!/usr/bin/env python
"""
Summarise raw telemetry into the site's per-session telemetry files
(oddsmarkets/f1/telemetry.py), for every session with telemetry on disk.

A session is (re)processed when its output is missing or older than its newest
raw telemetry file. Prints a coverage line per season.

    python scripts/f1_telemetry.py --from 2023 --to 2026
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.f1 import telemetry as tm  # noqa: E402
from oddsmarkets.f1.sources import openf1 as of  # noqa: E402

logger = logging.getLogger("f1_telemetry")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", type=int, default=2023)
    ap.add_argument("--to", dest="end", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for year in range(args.end, args.start - 1, -1):
        raw = of.TELEMETRY / str(year)
        done = skipped = 0
        if not raw.exists():
            logger.info("%d: no raw telemetry", year)
            continue
        for sdir in sorted(raw.iterdir()):
            if not sdir.is_dir():
                continue
            key = int(sdir.name)
            newest = max((f.stat().st_mtime for f in sdir.glob("*.json.gz")), default=0)
            out = tm.out_path(year, key)
            if not args.force and out.exists() and out.stat().st_mtime >= newest:
                skipped += 1
                continue
            try:
                p = tm.write_session(year, key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%d session %d failed: %s", year, key, exc)
                continue
            done += p is not None
        logger.info("%d: %d sessions processed, %d up to date", year, done, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
