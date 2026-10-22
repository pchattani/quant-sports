"""
Market-implied goal rates of past matches, as extra Dixon-Coles training rows.

For every finished league match in a store that football-data.co.uk also lists with
closing prices (Pinnacle; after January 2026, when football-data's Pinnacle columns
stop, the Betfair exchange close, else the market average), the closing 1X2 (and over/under 2.5 where present) is turned
into the pair of goal rates (home, away) that reproduces it under a Dixon-Coles score
model (rho = -0.05). The build adds one extra row per such match, carrying those rates
in the xG columns (so `DixonColesModel` scores it with its continuous-Poisson path) and
weight `W_MKT`; the match's own goals (or xG) row is kept as it was.

Why: a closing line summarises everything the market knew about both teams on the
day (injuries, lineups, form), so it is a much less noisy measurement of team strength
than a single scoreline. In the walk-forward research (docs/research/football_edge.md,
2019/20-2026/27 test seasons, production parameters, the 12 site leagues) adding these
rows at weight 3 cut the 1X2 log-loss by 0.0079 (95% CI 0.0065-0.0092) and improved
every one of the 12 leagues. Since 21 October 2026 the rows weigh 96 and decay with
their own half-life of 23 days (`W_MKT`, `XI_MKT`): on the 2019/20-2026/27 test seasons that cut
the log-loss of the site's 12 leagues by a further 0.0075 (95% CI 0.0064-0.0087). It does not use any price of the match being predicted:
only closing prices of matches already played.

Only *past* closing prices enter the fit, and they are the prices of matches that are
finished, so nothing about a future fixture leaks into its own prediction.

The raw CSVs live under data/football/odds/raw (git-ignored). Without them (CI, or a
fresh clone) this module returns no rows and the model is exactly the goals/xG model.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import pandas as pd

from oddsmarkets.football.sources import football_data as fd

logger = logging.getLogger(__name__)

# Weight and own daily decay of the market rows (since 21 Oct 2026; 2 Oct: weight 3, the fit's decay).
# Each row weighs W_MKT * exp(-XI_MKT * days ago) against a goals row's exp(-xi * days ago): a
# half-life of 23 days, so the fit follows the last few weeks of closing lines. Tuned walk-forward
# on the 2014-2018 football-data seasons; docs/research/football_edge.md, "Model-improvement
# programme, Oct 2026".
W_MKT = 96.0
XI_MKT: float | None = 0.03
# football-data division / extra-league file for each site league with a closing line.
SITE_FILES: dict[str, tuple[str, str]] = {
    "premier-league": ("main", "E0"), "la-liga": ("main", "SP1"), "serie-a": ("main", "I1"),
    "bundesliga": ("main", "D1"), "ligue-1": ("main", "F1"), "eredivisie": ("main", "N1"),
    "primeira-liga": ("main", "P1"), "belgian-pro-league": ("main", "B1"),
    "brasileirao": ("extra", "BRA"), "mls": ("extra", "USA"), "liga-mx": ("extra", "MEX"),
    "liga-argentina": ("extra", "ARG"),
}


def refresh(max_age_hours: float = 24.0) -> None:
    """Fetch the current season's files for the site leagues when older than a day (polite, cached)."""
    cur = fd.season_codes()[-2:]  # the season in progress and the one before (both feed a two-season frame)
    divs = [code for kind, code in SITE_FILES.values() if kind == "main"]
    extras = [code for kind, code in SITE_FILES.values() if kind == "extra"]
    try:
        fd.download(divisions=divs, seasons=cur, extras=extras, refresh_current=True, max_age_hours=max_age_hours)
    except Exception as exc:  # noqa: BLE001 - the build must never fail on this
        logger.warning("football-data refresh failed: %s", exc)


def _first(*arrays: np.ndarray) -> np.ndarray:
    out = arrays[0].copy()
    for a in arrays[1:]:
        fill = ~np.isfinite(out).all(axis=-1) if out.ndim == 2 else ~np.isfinite(out)
        out[fill] = a[fill]
    return out


def closing_probs(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """
    De-vigged closing 1X2 and P(over 2.5): Pinnacle where football-data has it (to
    January 2026), else the Betfair exchange close, else the market-average close.
    """
    from oddsmarkets.football.research.walkforward import devig

    p1 = _first(devig(df[["psc_h", "psc_d", "psc_a"]].to_numpy(float)),
                devig(df[["bfec_h", "bfec_d", "bfec_a"]].to_numpy(float)),
                devig(df[["avgc_h", "avgc_d", "avgc_a"]].to_numpy(float)))
    po = _first(devig(df[["pc_o25", "pc_u25"]].to_numpy(float))[:, 0],
                devig(df[["bfec_o25", "bfec_u25"]].to_numpy(float))[:, 0],
                devig(df[["avgc_o25", "avgc_u25"]].to_numpy(float))[:, 0],
                devig(df[["maxc_o25", "maxc_u25"]].to_numpy(float))[:, 0])
    return p1, po


@lru_cache(maxsize=None)
def _league_prices(slug: str) -> pd.DataFrame:
    from oddsmarkets.football.research.walkforward import implied_rates

    kind, code = SITE_FILES[slug]
    frames = []
    if kind == "main":
        for s in fd.season_codes()[-3:]:
            p = fd.RAW_DIR / "mmz4281" / s / f"{code}.csv"
            if p.exists():
                frames.append(fd.parse_main(p, code, s))
    else:
        p = fd.RAW_DIR / "new" / f"{code}.csv"
        if p.exists():
            df = fd.parse_extra(p, code)
            frames.append(df[df.start_time >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1100)])
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True).dropna(subset=["hg", "ag"]).reset_index(drop=True)
    p1, po = closing_probs(df)
    df["mkt_h"], df["mkt_a"] = implied_rates(p1, po)
    _, ev = fd.map_to_sofascore(df, slug)
    df["game_id"] = ev.astype("string")
    return df.dropna(subset=["game_id", "mkt_h", "mkt_a"])


_PARAMS = fd.ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "model_params.json"


@lru_cache(maxsize=None)
def fit_xi(slug: str) -> float | None:
    """
    The time decay of the Dixon-Coles fit that `slug`'s rows go into, as the build sets it
    from model_params.json: the `pooled` block for leagues whose method is `pooled` (they are
    fitted in the pooled fit, or on their own with the same parameters when it is unavailable),
    else the league's own `xi`. None when the file or the league is missing.
    """
    import json
    try:
        mp = json.loads(_PARAMS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    entry = (mp.get("leagues") or {}).get(slug)
    if entry is None or entry.get("method") == "pooled":
        block = mp.get("pooled") or {}
    else:
        block = entry.get("params") or {}
    xi = block.get("xi")
    return float(xi) if xi is not None else None


def decay_factor(match_date: pd.Series, xi_fit: float | None, xi_mkt: float | None,
                 now: pd.Timestamp | None = None) -> np.ndarray:
    """
    Extra weight that gives the market rows their own time decay: the fit weights every
    row by exp(-xi_fit * days_ago), so multiplying a row by exp(-(xi_mkt - xi_fit) * days_ago)
    leaves it at exp(-xi_mkt * days_ago). 1.0 when either decay is unset.
    """
    if xi_fit is None or xi_mkt is None:
        return np.ones(len(match_date))
    d = pd.to_datetime(match_date)
    if d.dt.tz is None:
        d = d.dt.tz_localize("UTC")
    now = now or pd.Timestamp.now(tz="UTC")
    days = ((now - d).dt.total_seconds() / 86400).to_numpy(float)
    return np.exp(-(float(xi_mkt) - float(xi_fit)) * np.clip(days, 0, None))


def market_rows(train_df: pd.DataFrame, slug: str, weight: float | None = None, xi_fit: float | None = None,
                xi_mkt: float | None = None, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Extra training rows (same columns as `train_df`) for the matches with a closing line.

    `xi_fit` is the decay of the Dixon-Coles fit the rows go into and `xi_mkt` the decay the
    market rows should have (see `decay_factor`). Defaults: `W_MKT`, `XI_MKT` and the fit's decay
    from model_params.json (`fit_xi`). `now` is the time the decay is measured from (default: the
    clock), and must be the same as the fit's `as_of` in a backtest."""
    weight = W_MKT if weight is None else weight
    xi_mkt = XI_MKT if xi_mkt is None else xi_mkt
    xi_fit = fit_xi(slug) if xi_fit is None else xi_fit
    if slug not in SITE_FILES and train_df is not None and len(train_df) and "game_id" in train_df:
        # No football-data file: Kalshi's closing prices where switched on (kalshi_rates; off by default).
        from oddsmarkets.football.sources import kalshi_rates
        if kalshi_rates.on() and slug in kalshi_rates.LEAGUE_SLUGS:
            return kalshi_rates.rows(train_df, slug, weight, xi_fit, xi_mkt, now)
    if slug not in SITE_FILES or train_df is None or not len(train_df) or "game_id" not in train_df:
        return train_df.iloc[0:0] if train_df is not None else pd.DataFrame()
    try:
        prices = _league_prices(slug)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: market rates unavailable (%s)", slug, exc)
        return train_df.iloc[0:0]
    if not len(prices):
        return train_df.iloc[0:0]
    rates = prices.set_index("game_id")[["mkt_h", "mkt_a"]]
    rates = rates[~rates.index.duplicated()]
    gid = train_df["game_id"].astype(str)
    hit = gid.isin(rates.index).to_numpy()
    if not hit.any():
        return train_df.iloc[0:0]
    extra = train_df[hit].copy()
    r = rates.loc[gid[hit]]
    extra["home_xg"] = r["mkt_h"].to_numpy()
    extra["away_xg"] = r["mkt_a"].to_numpy()
    extra["weight"] = extra.get("weight", 1.0) * weight * decay_factor(extra["match_date"], xi_fit, xi_mkt, now)
    extra["game_id"] = extra["game_id"].astype(str) + ":mkt"
    return extra


def with_market_rows(train_df: pd.DataFrame, slug: str, weight: float | None = None, xi_fit: float | None = None,
                     xi_mkt: float | None = None, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """`train_df` plus its market rows (for the Dixon-Coles fit only, never for Elo or calibration).

    The build (`scripts/build_site_all.py`, `scripts/build_site_liga.py`) and the tuner
    (`scripts/tune_league_models.py`) both build their Dixon-Coles frames through this function
    (via `oddsmarkets.football.competitions.league.fitting`), so they cannot drift apart."""
    extra = market_rows(train_df, slug, weight, xi_fit, xi_mkt, now)
    if not len(extra):
        return train_df
    logger.info("%s: %d market-rate rows added to the Dixon-Coles fit (%d matches)", slug, len(extra), len(train_df))
    out = pd.concat([train_df, extra], ignore_index=True)
    return out.sort_values("match_date").reset_index(drop=True)
