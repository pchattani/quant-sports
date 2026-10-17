#!/usr/bin/env python
"""
Fit The Quant Gridiron's fantasy model and run its walk-forward backtest (analytics/fantasy.py describes the model).

Tunes the recency half-life, opponent exponent and prior weight on the tuning seasons (fantasy.TUNE), fits the
regression constants and the floor/ceiling SD model there, then projects every week of 2019..--last from the games
before it only and writes oddsmarkets/nfl/models/fitted/fantasy.json (params, sd, grid, backtest). The hourly build
reads that file; rerun this after a season ends. About ten minutes on two cores.

    python scripts/nfl_fantasy_fit.py
    python scripts/nfl_fantasy_fit.py --last 2025
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--last", type=int, default=2025, help="last evaluation season (default 2025)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from oddsmarkets.nfl.analytics import fantasy_model as FM
    t0 = time.perf_counter()
    res = FM.fit_all(eval_last=args.last)
    b = (res.get("backtest") or {}).get("formats", {}).get("ppr", {})
    for pos, r in b.items():
        logging.info("%s n %s: model MAE %s rho %s | season-to-date %s / %s | last season %s / %s", pos, r["n"], r["model"]["mae"],
                     r["model"]["rho"], r["season_to_date"]["mae"], r["season_to_date"]["rho"], r["last_season"]["mae"], r["last_season"]["rho"])
    logging.info("params %s", json.dumps(res.get("params")))
    logging.info("done in %.0f s -> %s", time.perf_counter() - t0, FM.fitted_path())
    return 0


if __name__ == "__main__":
    sys.exit(main())
