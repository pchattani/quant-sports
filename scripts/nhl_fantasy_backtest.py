#!/usr/bin/env python
"""
The Quant Rink's fantasy backtest (analytics/fantasy.py `backtest`): walk-forward over the last five completed seasons at
weekly checkpoints, our per-game projection against two naive baselines (season to date; last season), MAE per
player-game (games-weighted) and Spearman per checkpoint, next week and rest of season.

The result is cached on the completed seasons' game logs (<cache>/analytics/fantasy/backtest.json) and copied to
docs/rink/data/fantasy_backtest.json; the hourly build only reads the cache (it recomputes it only when the completed
seasons' inputs or the model version change). Run this after a refit or a model change:

    python scripts/nhl_fantasy_backtest.py              # the last five completed seasons
    python scripts/nhl_fantasy_backtest.py --seasons 20232024 20242025
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(v, "2")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.nhl import analytics as an  # noqa: E402
from oddsmarkets.nhl.analytics import fantasy as FA  # noqa: E402


def default_seasons() -> list[int]:
    cur = an.current_season()
    return [an.season_id(an.start_year(cur) - k) for k in range(FA.BT_SEASONS, 0, -1)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="*", help="completed seasons (NHL ids); default the last five")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    t0 = time.perf_counter()
    seasons = args.seasons or default_seasons()
    res = FA.backtest_cached(seasons)
    an.write_json(an.data_root() / "fantasy_backtest.json", res)
    logging.info("fantasy backtest %s: %d checkpoints in %.0f s", seasons, res.get("checkpoints") or 0, time.perf_counter() - t0)
    for row in res.get("rows") or []:
        if row[2] == "pts":
            logging.info("  %s %-4s %-5s mae %s spearman %s", row[0], row[1], row[3], row[4], row[5])
    return 0


if __name__ == "__main__":
    sys.exit(main())
