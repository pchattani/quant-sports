#!/usr/bin/env python
"""
Download and parse Retrosheet for The Quant Bullpen, newest season first, resumably.

For each season: the game log (gl<YYYY>.zip, 1901->) to data/baseball/retro/games/<YYYY>.parquet and, from
1908, the regular-season and postseason event files (<YYYY>eve.zip, <YYYY>post.zip) replayed by our own
parser to data/baseball/retro/pa/<YYYY>.parquet (one row per event: plate appearances and running events
with the base-out state before and after). Each season is validated against its game log (runs and hits
per team, game by game) and, with --lahman, against the Lahman team totals; results accumulate in
data/baseball/retro/validation.json. Seasons already parsed are skipped unless --refresh.

    python scripts/mlb_retro.py --from 1901 --to 2025 --log logs/mlb_backfill_retro.log
    python scripts/mlb_retro.py --from 2025 --to 2025 --refresh --lahman

Notice (required wherever the data is shown): oddsmarkets.baseball.sources.retrosheet.NOTICE
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from oddsmarkets.baseball import store as st  # noqa: E402
from oddsmarkets.baseball.sources import lahman, retrosheet  # noqa: E402
from oddsmarkets.baseball.sources._client import BudgetExhausted, Client  # noqa: E402

logger = logging.getLogger("mlb_retro")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", type=int, default=1901)
    ap.add_argument("--to", dest="end", type=int, default=2025)
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--interval", type=float, default=retrosheet.INTERVAL)
    ap.add_argument("--refresh", action="store_true", help="re-parse seasons already on disk")
    ap.add_argument("--redownload", action="store_true", help="download the zips again")
    ap.add_argument("--lahman", action="store_true", help="cross-check team runs and hits against Lahman")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()
    handlers = [logging.StreamHandler()]
    if args.log:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=handlers)
    c = Client(budget=args.budget, interval=args.interval, name="retro",
               intervals={"sabr.box.com": 1.0, "retrosheet.org": args.interval})
    vpath = st.raw_root() / "retro" / "validation.json"
    val = st.read_json(vpath, {}) or {}
    if args.lahman:
        got = lahman.download(c)
        logger.info("lahman: %s", sorted(got))
    t0 = time.monotonic()
    try:
        for year in range(args.end, args.start - 1, -1):
            done = st.retro_games_path(year).exists() and (year < retrosheet.EVENTS_FROM or st.retro_pa_path(year).exists())
            if done and not args.refresh and str(year) in val:
                continue
            if args.redownload:
                for kind in ("gamelog", "eve", "post"):
                    retrosheet.download(c, year, kind, refresh=True)
            t1 = time.monotonic()
            r = retrosheet.parse_season(c, year)
            if args.lahman and st.retro_pa_path(year).exists():
                pa = pd.read_parquet(st.retro_pa_path(year), columns=["gtype", "bat_team", "hit", "runs_on_play"])
                r["lahman"] = lahman.check_retro(year, pa)
                del pa
            r["at"] = st.now()
            val[str(year)] = r
            st.write_json(vpath, dict(sorted(val.items())), indent=1)
            v = r.get("validation") or {}
            logger.info("%d: %s game-log games, %s events (%s PA) in %s games, %s unparsed; runs match %s, hits match %s "
                        "(%.1f s)%s", year, r.get("gamelog_games"), r.get("events"), r.get("pa"), r.get("event_games"),
                        r.get("unparsed"), v.get("runs_match"), v.get("hits_match"), time.monotonic() - t1,
                        f"; lahman {r['lahman']}" if r.get("lahman") else "")
    except BudgetExhausted as exc:
        logger.info("%s", exc)
    logger.info("calls: %s; %.0f s elapsed", c.report(), time.monotonic() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
