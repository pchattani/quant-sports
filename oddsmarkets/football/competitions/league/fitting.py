"""
The club Dixon-Coles fit, made in one place.

The site build (`scripts/build_site_all.py`: each league's own fit and the pooled fit;
`scripts/build_site_liga.py`: Argentina) and the tuner (`scripts/tune_league_models.py`)
all build their Dixon-Coles models and training frames through these functions, so the
tuner scores exactly the model the build publishes: the same market-rate rows (weight
`market_rates.W_MKT`, own decay `market_rates.XI_MKT`, the extra decay measured against the
fit's own xi), the same optimiser and the same rho. `tests/test_tuner_production.py` pins
that contract.

Until 21 October 2026 the tuner fitted plain goals/xG frames while the build added the
market rows, so a re-run of the tuner would have put back the parameters that lose once
the rows are in (docs/MODELS.md 5.1).
"""
from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from pathlib import Path

import pandas as pd

from oddsmarkets.football.core import DixonColesModel
from oddsmarkets.football.sources import market_rates

# The Dixon-Coles rho of every club fit, estimated separately from the team ratings: the
# maximum-likelihood rho of the low-score correction over every match of every football-data
# league in the seasons before the current one, given the walk-forward model's goal rates
# (`scripts/football_models_oct.py rhofit`; the rule was chosen on 2014-2018 and tested on
# 2019/20 on, docs/research/football_edge.md "Round 2"). Stored in model_params.json under
# `dixon_coles_rho`. A league's own frame cannot identify rho: almost every match in a store
# carries Sofascore xG, and xG and market-rate rows are fitted on their rates with no tau, so
# rho sat at the optimiser's start (-0.1), or two or three matches without xG pushed it to a
# bound (docs/MODELS.md 2.4).
PARAMS_PATH = Path(__file__).parent / "data" / "model_params.json"
RHO_FALLBACK = -0.05   # only when model_params.json has no `dixon_coles_rho`


@cache
def club_rho() -> float:
    """The rho every club Dixon-Coles fit holds (model_params.json `dixon_coles_rho.rho`)."""
    try:
        block = json.loads(PARAMS_PATH.read_text(encoding="utf-8")).get("dixon_coles_rho") or {}
        return float(block["rho"])
    except Exception:  # noqa: BLE001
        return RHO_FALLBACK


def new_dc(xi: float, ridge: float, prior_group=None) -> DixonColesModel:
    """An unfitted club Dixon-Coles model with the build's settings (`prior_group`: see `pooled_tier`)."""
    return DixonColesModel(xi=float(xi), ridge=float(ridge), analytic_grad=True, fixed_rho=club_rho(),
                           prior_group=prior_group)


def pooled_tier(team: str) -> str | None:
    """
    The prior tier of a club in the pooled fit (docs/research/football_edge.md 3.5): a club under a national
    cup's or super cup's prefix (outside the followed leagues: lower divisions, mostly) is "domestic"; under a
    continental cup's prefix (a foreign club) "continental"; a league club None (shrunk toward 0 as before).
    """
    from oddsmarkets.football.competitions.cup.config import CUPS
    from oddsmarkets.football.competitions.league.config import LEAGUES
    prefix = team.split(":", 1)[0] if ":" in team else None
    if not prefix or prefix in LEAGUES:
        return None
    cfg = CUPS.get(prefix)
    if cfg is None:
        return None
    return {"domestic": "domestic", "super": "domestic", "cup": "continental"}.get(cfg.family)


@cache
def tier_prior_on() -> bool:
    """Whether the pooled fit uses the tier prior (model_params.json `pooled_tier_prior.on`)."""
    try:
        return bool((json.loads(PARAMS_PATH.read_text(encoding="utf-8")).get("pooled_tier_prior") or {}).get("on"))
    except Exception:  # noqa: BLE001
        return False


def dc_frame(train_df: pd.DataFrame, slug: str, xi: float, *, market: bool = True,
             now: pd.Timestamp | datetime | None = None) -> pd.DataFrame:
    """
    The Dixon-Coles training frame of one league: its matches plus their market-rate rows.

    `xi` is the decay of the fit the frame goes into (the rows' extra decay is measured
    against it); `now` is the time the decay is measured from, which must equal the fit's
    `as_of` in a backtest (default: the clock, as in the build).
    """
    if not market or train_df is None or not len(train_df):
        return train_df
    if now is not None:
        now = pd.Timestamp(now)
        now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    return market_rates.with_market_rows(train_df, slug, xi_fit=float(xi), now=now)


def pooled_part(train_df: pd.DataFrame, slug: str, xi: float, *, market: bool = True,
                now: pd.Timestamp | datetime | None = None) -> pd.DataFrame:
    """One league's share of a pooled fit: `dc_frame`, with team names prefixed by the league slug."""
    fit_df = dc_frame(train_df, slug, xi, market=market, now=now)
    return fit_df.assign(home_team=slug + ":" + fit_df["home_team"], away_team=slug + ":" + fit_df["away_team"])


def fit_dc(fit_df: pd.DataFrame, xi: float, ridge: float, *, as_of: datetime | None = None,
           prior_group=None) -> DixonColesModel:
    """Fit `new_dc(xi, ridge)` on a frame from `dc_frame` / `pooled_part` (raises as `DixonColesModel.fit`)."""
    dc = new_dc(xi, ridge, prior_group=prior_group)
    dc.fit(fit_df, as_of=as_of)
    return dc
