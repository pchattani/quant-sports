#!/usr/bin/env python
"""
Walk-forward backtest of The Quant Hardwood's fantasy projections (oddsmarkets/basketball/research/fantasy_backtest.py)
into docs/hardwood/data/<league>/fantasy_backtest.json, which the build embeds in fantasy.json. Run it when a season
completes (it is not part of the hourly build).

    python scripts/bb_fantasy_backtest.py --league nba --seasons 2022 2023 2024 2025 2026
    python scripts/bb_fantasy_backtest.py --league wnba
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(k, "2")

from oddsmarkets.basketball import analytics as an  # noqa: E402
from oddsmarkets.basketball.research import fantasy_backtest as FB  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", choices=list(an.LEAGUES), required=True)
    ap.add_argument("--seasons", type=int, nargs="*", help="completed seasons (default: the last five)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from oddsmarkets.basketball import canon
    cur = canon.current_season(args.league)
    seasons = args.seasons or [s for s in an.seasons_on_disk(args.league) if s < cur][-5:]
    t0 = time.perf_counter()
    res = FB.run(args.league, seasons)
    res["seconds"] = round(time.perf_counter() - t0, 1)
    an.write_json(an.data_root() / args.league / "fantasy_backtest.json", res)
    for hz, d in res["summary"].items():
        logging.info("%s %s: %s", args.league, hz, d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
