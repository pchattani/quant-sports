#!/usr/bin/env python
"""
Fit the models CI cannot fit itself and commit them to oddsmarkets/basketball/models/fitted/:

  game_params_<league>.json   game.fit_params on every season with a store on this machine
                              (walk-forward coefficients and sigma; CI has no history to fit on)
  winprob_<league>.json       the live win-probability model fitted on the seasons before the current
                              one (CI holds only the current season's play-by-play, so it would
                              otherwise refit in-sample on a few weeks of games)

Run locally after a backfill or at the start of a season, then commit the files.

    python scripts/bb_fit.py                  # both leagues
    python scripts/bb_fit.py --leagues nba
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oddsmarkets.basketball import canon  # noqa: E402
from oddsmarkets.basketball.models import game, winprob  # noqa: E402
from oddsmarkets.basketball.models._io import clean  # noqa: E402

logger = logging.getLogger("bb_fit")
FITTED = Path(game.__file__).with_name("fitted")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leagues", nargs="+", default=list(canon.LEAGUES))
    args = ap.parse_args(argv)
    FITTED.mkdir(parents=True, exist_ok=True)
    for lg in args.leagues:
        res = game.fit_params(lg, use_cache=False)
        (FITTED / f"game_params_{lg}.json").write_text(json.dumps(clean({"result": res, "fitted_on": str(date.today())}), indent=1),
                                                       encoding="utf-8")
        logger.info("%s game params: %s", lg, {k: res.get(k) for k in ("sigma", "hca", "b2b", "travel", "altitude", "n_games") if k in res})
        cur = canon.current_season(lg, date.today())
        m = winprob.model_for(lg, cur, use_cache=False)
        if m.get("ok"):
            (FITTED / f"winprob_{lg}.json").write_text(json.dumps(clean(m)), encoding="utf-8")
            logger.info("%s win-probability model for %s: K %.1f", lg, cur, m.get("K", float("nan")))
        else:
            logger.warning("%s win-probability model not fitted: %s", lg, m.get("reason"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
