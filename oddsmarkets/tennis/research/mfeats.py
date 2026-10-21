"""
Market-rating features for the tennis edge research (docs/research/tennis_edge.md, "Model-improvement program,
Oct 2026"). The rating itself is the production module `models/mrating.py` (a Kalman filter on earlier matches'
de-vigged closing prices and results); this adds, per base-frame row and oriented to A, the pre-match difference
on the match's logit scale and four variants used as checks:

* mr      production: Pinnacle, else Betfair, else average, Bet365, Max closes (power de-vig), results
* mr_V    the pair's rating variance before the match (uncertainty)
* mr_nm   no prices at all (results only: how much of the gain is the market's)
* mr_avg  the market average's close only (what the site has in 2026, when tennis-data carries no Pinnacle)
* mr_ol3  every close known only three days after its match (a stale workbook)
* mr_seq  strictly sequential within a day (date, round, id): leaks through matches the stores hold twice on one day
          (the production rating prices a day from the states at the end of the day before)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.models import mrating as MR


def _col(df: pd.DataFrame, pre: dict, prm: dict) -> tuple[np.ndarray, np.ndarray]:
    d = df["id"].map(lambda i: (pre.get(i) or (np.nan, np.nan))[0]).to_numpy(float)
    V = df["id"].map(lambda i: (pre.get(i) or (np.nan, np.nan))[1]).to_numpy(float)
    d = np.where(df["flip"].to_numpy(), -d, d)
    s = np.where(df["bo"].to_numpy() == 5, float(prm["s5"]), 1.0)
    return np.nan_to_num(d * s), V


def add(df: pd.DataFrame, tour: str, variants: bool = True) -> pd.DataFrame:
    t = _io.tour_key(tour)
    prm = MR.params(t)
    ms = _io.load_matches(t, statuses=None)
    prep = MR.prepare(ms, max_margin=prm["max_margin"])
    df = df.copy()
    df["mr"], df["mr_V"] = _col(df, MR.run(prep, prm)["pre"], prm)
    if variants:
        df["mr_nm"], _ = _col(df, MR.run(MR.prepare(ms, books=()), prm)["pre"], prm)
        df["mr_avg"], _ = _col(df, MR.run(MR.prepare(ms, books=("avg",), max_margin=prm["max_margin"]), prm)["pre"], prm)
        df["mr_ol3"], _ = _col(df, MR.run(prep, dict(prm, obs_lag=3))["pre"], prm)
        df["mr_seq"], _ = _col(df, MR.run(prep, prm, day_lag=False)["pre"], prm)
    return df
