#!/usr/bin/env python
"""
Fit the tennis models' frozen constants on local history and commit them to oddsmarkets/tennis/models/fitted/:

  elo_params_<tour>.json     B's Elo constants (K decay, surface blend, best-of-five, layoff pull, entry
                             ratings), fitted on 2005-2019 walk-forward log-loss (elo.export_fits)
  serve_return_<tour>.json   B's tuned serve/return constants and the latest fit (players seen in the last
                             two years), the model CI and the build fall back to when nothing can be
                             fitted on the machine (serve_return.export_fits)
  predict_<tour>.json        C's blend weights (w_elo, w_sr) and dispersion sigma, from the walk-forward
                             backtest (backtest.backtest), which also refreshes docs/ace/data/<tour>/calibration.json

The loaders already read these files: elo.params(tour), serve_return.constants(tour) / for_tour (the committed
model when no stores are on disk), predict.blend_params(tour); the build's TourData.sr_fit falls back to the
committed model when a fit cannot be made.

Run locally after a backfill or at the start of a season, then commit the files. The backtest is slow (a
serve/return refit per month since 2008, cached under ACE_CACHE/backtest_sr), so it runs only with --backtest.

    python scripts/tn_fit.py                          # both tours: Elo constants and serve/return
    python scripts/tn_fit.py --tours wta --backtest   # also the blend (and calibration.json)
    python scripts/tn_fit.py --no-elo                 # serve/return only
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oddsmarkets.tennis import canon  # noqa: E402

logger = logging.getLogger("tn_fit")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tours", nargs="+", choices=list(canon.TOURS), default=list(canon.TOURS))
    ap.add_argument("--no-elo", action="store_true", help="keep the committed Elo constants")
    ap.add_argument("--no-sr", action="store_true", help="keep the committed serve/return fit")
    ap.add_argument("--backtest", action="store_true", help="run the walk-forward backtest and commit the blend weights")
    ap.add_argument("--elo-evals", type=int, default=800, help="Elo optimiser evaluations (default 800)")
    ap.add_argument("--through", default=None, help="serve/return fit date (default: the latest match)")
    args = ap.parse_args(argv)
    from oddsmarkets.tennis.models import elo as E
    from oddsmarkets.tennis.models import serve_return as SR
    for t in args.tours:
        t0 = time.time()
        if not args.no_elo:
            p = E.export_fits(t, maxfev=args.elo_evals)
            logger.info("%s Elo constants -> %s (%.0f s)", t, p, time.time() - t0)
        if not args.no_sr:
            t1 = time.time()
            r = SR.export_fits(t, through=args.through, refit_elo=False)
            logger.info("%s serve/return -> %s (%.0f s)", t, r.get("serve_return"), time.time() - t1)
        if args.backtest:
            from oddsmarkets.tennis.models import backtest as BT
            t1 = time.time()
            out = BT.backtest(t, log=lambda msg: logger.info("%s", msg))
            ba = out.get("blend_all_years") or {}
            logger.info("%s backtest: %d matches, blend w_elo %s w_sr %s (%.0f s)", t, out.get("n_matches", 0), ba.get("w_elo"),
                        ba.get("w_sr"), time.time() - t1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
