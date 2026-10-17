#!/usr/bin/env python
"""
Fit the models CI cannot fit itself and write them to oddsmarkets/baseball/models/fitted/ (committed by hand).

CI holds only the current season's pitch table, so every model that trains on earlier seasons falls back to these
files when its cache is cold:

  builder B   stuff_<L>.json.gz, location_<L>.json.gz, pitching_<L>.json.gz, swing_<L>.json.gz
              (pitching.export_fits: fitted on the latest four seasons on disk, through --season)
  builder C   re24_<L>.json, re24_retro.json, xwoba_<L>.txt.gz + .json, catchprob_<L>.txt.gz + .json,
              framing_<L>.json, parks_<L>.json, stabilise_<L>.json, war_constants.json (fit_c.export_fits)
  builder D   transitions_<L>.json (game_sim.fit_and_save: base-out running tables, pitches per outcome),
              weather_<L>.json (game_inputs.save_weather: within-park weather effects of the last three seasons),
              league_days_<L>.json (projections.export_league_days: league event counts by day of the last two
              seasons, for the season environment's calendar comparison)
  this layer  proj_agg_{h,p}_<L>_<S>.parquet: the projection count aggregates of the last --proj-seasons seasons
              (read by analytics.fallbacks when the season's pitch table is absent)

Every step is isolated; a failing one is reported and the rest run. Each fit holds one season of pitches at a
time inside the model code. Run locally after a backfill, at the start of a season, or when a model version moves.

    python scripts/mlb_fit.py                         # everything, MLB
    python scripts/mlb_fit.py --only b c --season 2025
    python scripts/mlb_fit.py --levels mlb aaa --only d proj
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oddsmarkets.baseball import analytics as an  # noqa: E402

logger = logging.getLogger("mlb_fit")
GROUPS = ("b", "c", "d", "proj")


def _run(name: str, fn) -> dict:
    t = time.time()
    try:
        r = fn()
        logger.info("%s: done in %.0f s", name, time.time() - t)
        return {"ok": True, "s": round(time.time() - t, 1), "result": r}
    except Exception as exc:  # noqa: BLE001 - isolated steps
        logger.error("%s failed: %s\n%s", name, exc, traceback.format_exc())
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "s": round(time.time() - t, 1)}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", nargs="+", choices=list(an.LEVELS), default=["mlb"])
    ap.add_argument("--only", nargs="+", choices=GROUPS, default=list(GROUPS))
    ap.add_argument("--season", type=int, default=None, help="fit through this season (default: the latest on disk)")
    ap.add_argument("--proj-seasons", type=int, default=3, help="export projection aggregates for the last N seasons (default 3)")
    ap.add_argument("--no-retro", action="store_true", help="skip the Retrosheet RE / linear-weight fits")
    args = ap.parse_args(argv)
    report: dict = {}
    for level in args.levels:
        on = [s for s in an.pitch_seasons(level) if args.season is None or s <= args.season]
        if not on:
            logger.warning("%s: no pitch tables on this machine", level)
            continue
        season = args.season or on[-1]
        rep = report.setdefault(level, {})
        if "b" in args.only:
            from oddsmarkets.baseball.models import pitching
            rep["b"] = _run(f"{level} builder B", lambda: pitching.export_fits(level, season, with_swing=True))
        if "c" in args.only:
            from oddsmarkets.baseball.models import fit_c
            rep["c"] = _run(f"{level} builder C", lambda: fit_c.export_fits(level, season, retro=(not args.no_retro and level == "mlb")))
        if "d" in args.only:
            from oddsmarkets.baseball.models import game_sim
            rep["d"] = _run(f"{level} builder D transitions", lambda: game_sim.fit_and_save(level, on[-3:]))
            from oddsmarkets.baseball.models import game_inputs, projections
            rep["d_weather"] = _run(f"{level} builder D weather", lambda: game_inputs.save_weather(level, on[-3:]))
            rep["d_days"] = _run(f"{level} builder D league days", lambda: projections.export_league_days(level, on[-2:]))
        if "proj" in args.only:
            from oddsmarkets.baseball.analytics import fallbacks
            rep["proj"] = _run(f"{level} projection aggregates", lambda: fallbacks.export_aggregates(level, on[-args.proj_seasons:]))
    print(json.dumps(an.clean(report), indent=1, default=str))
    return 0 if all(v.get("ok") for r in report.values() for v in r.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
