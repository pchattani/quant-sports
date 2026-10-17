"""
Experiment: does the WTA point layer (serve/return fitted with the real WTA match statistics, `stats=True`, as
production does) price matches better than the score-only fit the backtest uses? Walk-forward monthly refits
(through the day before each month) for 2021-2025, cached separately from the score-only fits.
Output: data/edge/cache/tn_wta_stats_sr.parquet {id, sr_stats}.
"""
from __future__ import annotations

import types

import pandas as pd

from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.models import backtest as BT
from oddsmarkets.tennis.models import serve_return as SR
from oddsmarkets.tennis.research import base as B


def _stats_module():
    m = types.SimpleNamespace()
    for k in dir(SR):
        if not k.startswith("__"):
            setattr(m, k, getattr(SR, k))
    m.fit = lambda *a, **kw: SR.fit(*a, **{**kw, "stats": True})
    m.constants = lambda t: {**SR.constants(t), "_stats_layer": True}
    return m


def run(years=range(2021, 2026), log=print) -> pd.DataFrame:
    out = B.CACHE / "tn_wta_stats_sr.parquet"
    matches = _io.load_matches("wta", statuses=None)
    rows, fits = BT.predictions("wta", matches, years, warmup_years=0, sr_mod=_stats_module(), log=log)
    del fits
    df = pd.DataFrame([{"id": r["id"], "sr_stats_p1": r["sr"]} for r in rows])
    df.to_parquet(out)
    return df


if __name__ == "__main__":
    d = run()
    print(len(d), d["sr_stats_p1"].notna().sum())
