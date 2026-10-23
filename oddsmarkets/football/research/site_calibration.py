"""The Footballer's calibration.json (the kit's "How sure are we?": QK.calib.find reads metrics.model) from the
walk-forward 1X2 backtest of the promoted match model (docs/research/football_edge.md, "Model-improvement programme,
Oct 2026": data/football/edge_runs/oct26/full__chosen.parquet).

No look-ahead: every forecast in the run is the walk-forward pre-match one (refitted at each decision time on matches
settled 2.5 h before it), and only the test seasons (2019/20 on) of the site's leagues are scored, so the model choice
made on 2014-2018 is out of sample. The block is the home side's chance (the chart's subject), with its Brier score and
log-loss; "outcomes_1x2" adds the three-way scores and the draw and away blocks.

The run lives on the PC (data/ is not deployed), so the result is committed at oddsmarkets/football/competitions/league/
data/calibration.json and the site build copies it to data/calibration.json (scripts/build_site_all.py).

    python -m oddsmarkets.football.research.site_calibration [--run PATH]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from oddsmarkets.common import calibration as CB
from oddsmarkets.football.research.walkforward import TUNE_LAST_SEASON, season_year
from oddsmarkets.football.sources.football_data import SITE_LEAGUES

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "data" / "football" / "edge_runs" / "oct26" / "full__chosen.parquet"
OUT = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "calibration.json"


def season_label(y: int) -> str:
    return f"{y}/{str(y + 1)[2:]}"


def build(R: pd.DataFrame, leagues: set[str] | None = None, first_test: int = TUNE_LAST_SEASON + 1) -> dict:
    """The payload from a walk-forward run (columns league, season, p_h, p_d, p_a, result: 0 home, 1 draw, 2 away)."""
    lg = set(leagues or SITE_LEAGUES)
    sy = R["season"].map(season_year)
    d = R[R["league"].isin(lg) & (sy >= first_test) & R["result"].isin([0, 1, 2])].copy()
    P = d[["p_h", "p_d", "p_a"]].to_numpy(float)
    ok = np.isfinite(P).all(axis=1)
    d, P = d[ok], P[ok] / P[ok].sum(axis=1, keepdims=True)
    res = d["result"].to_numpy(int)
    Y = np.eye(3)[res]
    q = np.clip(P[np.arange(len(res)), res], 1e-12, 1.0)
    cum_p, cum_y = np.cumsum(P, axis=1)[:, :2], np.cumsum(Y, axis=1)[:, :2]
    y0 = int(sy[d.index].min()) if len(d) else first_test
    y1 = int(sy[d.index].max()) if len(d) else first_test
    by_league = {}
    for slug, g in d.groupby("league"):
        i = d.index.get_indexer(g.index)
        by_league[slug] = {"n": int(len(i)), "logloss_1x2": round(float(-np.log(q[i]).mean()), 5),
                           "brier_home": round(float(np.mean((P[i, 0] - Y[i, 0]) ** 2)), 5)}
    return {
        "ok": True, "league": "Football", "span": f"{season_label(y0)} to {season_label(y1)}", "subject": "the home side",
        "unit": "matches", "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "walk-forward 1X2 backtest of the promoted match model on football-data.co.uk results, the site's "
                  f"{len(lg)} leagues, test seasons only ({season_label(first_test)} on; settings chosen on 2014-2018)",
        "leagues": sorted(lg & set(d["league"])),
        "metrics": {"model": CB.block(P[:, 0], Y[:, 0])},
        "outcomes_1x2": {"n": int(len(res)), "logloss": round(float(-np.log(q).mean()), 5),
                         "brier": round(float(np.mean(np.sum((P - Y) ** 2, axis=1))), 5),
                         "rps": round(float(np.mean(np.sum((cum_p - cum_y) ** 2, axis=1) / 2)), 5),
                         "draw": CB.block(P[:, 1], Y[:, 1]), "away": CB.block(P[:, 2], Y[:, 2])},
        "by_league": by_league,
        "notes": ["Every forecast is the model's pre-match one, refitted at each decision time on matches settled at "
                  "least 2.5 hours before it; closing prices only judge.",
                  "The chart shows the home side's chance; the three-way log-loss, Brier score and ranked probability "
                  "score are in outcomes_1x2.",
                  "Cups and international matches are not in the backtest (football-data.co.uk covers leagues)."],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default=str(RUN), help="walk-forward run parquet (default: the promoted spec, Oct 2026)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    R = pd.read_parquet(a.run, columns=["league", "season", "p_h", "p_d", "p_a", "result"])
    out = build(R)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    m = out["metrics"]["model"]
    print(f"{a.out}: n {m['n']}, home Brier {m['brier']}, 1X2 log-loss {out['outcomes_1x2']['logloss']}, {out['span']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
