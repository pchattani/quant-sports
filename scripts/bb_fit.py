#!/usr/bin/env python
"""
Fit the models CI cannot fit itself and commit them to oddsmarkets/basketball/models/fitted/:

  game_params_<league>.json   game.fit_params on every season with a store on this machine
                              (walk-forward coefficients and sigma; CI has no history to fit on)
  winprob_<league>.json       the live win-probability model fitted on the seasons before the current
                              one (CI holds only the current season's play-by-play, so it would
                              otherwise refit in-sample on a few weeks of games)
  informed_<league>.json      the market-informed game model (models/informed.py; leagues in
                              informed.INFORMED_LEAGUES), fitted by research/improve.py final_fit on the
                              walk-forward edge table (needs `scripts/bb_edge.py build --lags 1 --roster` and the
                              ESPN line cache, scripts/bb_odds_history.py); --no-informed skips it
  informed_values_<league>.json  the player values (two finished seasons) the current season's availability term
                              starts from, so CI never refits a past season's impact model for them

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
from oddsmarkets.basketball.models import game, informed, winprob  # noqa: E402
from oddsmarkets.basketball.models._io import clean  # noqa: E402

logger = logging.getLogger("bb_fit")
FITTED = Path(game.__file__).with_name("fitted")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leagues", nargs="+", default=list(canon.LEAGUES))
    ap.add_argument("--no-informed", action="store_true", help="leave models/fitted/informed_<L>.json as it is")
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
        if not args.no_informed and lg in informed.INFORMED_LEAGUES:
            try:
                from oddsmarkets.basketball.research import improve
                f = improve.final_fit(lg)
            except Exception as exc:  # noqa: BLE001  (the edge table or line cache is missing)
                logger.warning("%s informed model not refitted (%s); the committed fit stays", lg, exc)
                f = None
            if f:
                (FITTED / f"informed_{lg}.json").write_text(json.dumps(clean(f, 6), indent=1), encoding="utf-8")
                logger.info("%s informed model through %s: %s", lg, f.get("through_season"), f.get("spread"))
        if lg in informed.INFORMED_LEAGUES:
            # the player values the current season's availability term starts from (two finished seasons)
            vals = {str(s): informed.season_player_values(lg, s, use_committed=False) for s in (cur - 1, cur - 2)}
            vals = {s: {p: [round(x, 4) for x in v] for p, v in d.items()} for s, d in vals.items() if d}
            (FITTED / f"informed_values_{lg}.json").write_text(json.dumps({"for_season": cur, "seasons": vals},
                                                                          separators=(",", ":")), encoding="utf-8")
            logger.info("%s informed player values for %s: %s", lg, cur, {s: len(d) for s, d in vals.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
