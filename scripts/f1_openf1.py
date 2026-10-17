#!/usr/bin/env python
"""
Fill the per-session OpenF1 records (and, with --telemetry, the raw car data and
location for every driver), 2023 onward, resumably.

A session is fetched once it has ended (plus a 30-minute settling margin) and
re-fetched while it is younger than `--refresh-hours`, so late corrections land.
Telemetry is fetched only for sessions whose record exists, driver by driver,
skipping files already on disk.

    python scripts/f1_openf1.py --from 2023 --to 2026                  # session records
    python scripts/f1_openf1.py --from 2023 --to 2026 --telemetry      # plus all telemetry
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.f1.sources import openf1 as of  # noqa: E402

logger = logging.getLogger("f1_openf1")


def _ended(sess: dict, margin_s: float = 1800) -> bool:
    end = of._ts(sess.get("date_end"))
    return end is not None and datetime.now(timezone.utc).timestamp() - end > margin_s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", type=int, default=2023)
    ap.add_argument("--to", dest="end", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--telemetry", action="store_true")
    ap.add_argument("--budget", type=int, default=100000)
    ap.add_argument("--refresh-hours", type=float, default=48)
    ap.add_argument("--types", default="", help="comma-separated session_type filter, e.g. Race,Qualifying")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = of.Client(budget=args.budget)
    types = {t for t in args.types.split(",") if t}
    now = datetime.now(timezone.utc).timestamp()
    try:
        for year in range(args.end, args.start - 1, -1):
            for sess in sorted(of.sessions(c, year), key=lambda s: s.get("date_start") or "", reverse=True):
                if not _ended(sess) or (types and sess.get("session_type") not in types):
                    continue
                key = sess["session_key"]
                p = of.session_path(year, key)
                young = (now - (of._ts(sess.get("date_end")) or now)) < args.refresh_hours * 3600
                if not p.exists() or young:
                    rec = of.fetch_session(c, sess)
                    of.save_session(year, rec)
                    logger.info("%d %s %s: %d drivers, %d laps (%d calls)", year, sess.get("circuit_short_name"), sess.get("session_name"),
                                len(rec["drivers"]), sum(len(v) for v in rec["laps"].values()), c.used)
                if args.telemetry:
                    import json
                    rec = json.loads(p.read_text(encoding="utf-8"))
                    for dn in rec["drivers"]:
                        if of.telemetry_path(year, key, int(dn)).exists() and not young:
                            continue
                        try:
                            of.fetch_telemetry(c, year, sess, int(dn))
                        except MemoryError:     # one oversized response (seen 2024 Hungaroring) must not end the pass
                            import gc
                            gc.collect()
                            logger.warning("%d %s %s driver %s: telemetry skipped (MemoryError)", year,
                                           sess.get("circuit_short_name"), sess.get("session_name"), dn)
                    logger.info("%d %s %s: telemetry done (%d calls)", year, sess.get("circuit_short_name"), sess.get("session_name"), c.used)
    except RuntimeError as exc:
        logger.info("%s", exc)
    logger.info("calls used: %d", c.used)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
