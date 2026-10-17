"""
Championship futures against Kalshi (KXNBA, KXWNBA; scripts/bb_kalshi_history.py --futures).

At checkpoints (the 1st and 15th of each month from the market's first quote to the last regular-season day) the
season is simulated with ratings fitted on games through the day before (production `season_sim.simulate`,
preseason prior = last season carried over, as the site had it then) and P(title) is compared with Kalshi's
daily candle: bets buy YES at the ask (or NO at 1 - bid) plus the taker fee when the model's edge exceeds a
threshold; CLV is measured against the mid on the last day before the postseason ("close"). Few seasons and
one champion each: the CLV figures describe price moves, the P&L is not informative.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import _io
from oddsmarkets.basketball.models import ratings as R
from oddsmarkets.basketball.models import season_sim as SS
from oddsmarkets.basketball.research import kalshi as K
from oddsmarkets.basketball.sources.markets import CODE_ALIASES

SERIES = {"nba": "KXNBA", "wnba": "KXWNBA"}


def _quote(candles, d: date):
    ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
    return K._at(candles, ts)


def run(league: str, n_sims: int = 2000) -> pd.DataFrame:
    series = SERIES[league]
    root = _io.cache_root() / "kalshi" / series
    markets = json.loads((root / "markets.json").read_text("utf-8"))
    alias = CODE_ALIASES[league]
    rows = []
    for season_code in sorted({m["event_ticker"].split("-")[1] for m in markets}):
        season = 2000 + int(season_code)
        st = G.load_store(league, season)
        if not st:
            continue
        ab = {(v or {}).get("abbr"): t for t, v in (st.get("teams") or {}).items()}
        ms = [m for m in markets if m["event_ticker"].endswith(f"-{season_code}")]
        reg = sorted(r["day"] for r in G.finished(st.get("games") or {}, league, stypes=G.STANDINGS))
        post = sorted(r["day"] for r in G.finished(st.get("games") or {}, league, stypes=("post", "playin")))
        if not reg or not post:
            continue
        last_reg, first_post = reg[-1], post[0]
        candles = {}
        for m in ms:
            p = root / "candles" / f"{m['ticker']}.json"
            if p.exists():
                code = m["ticker"].rsplit("-", 1)[-1]
                tid = ab.get(alias.get(code, code))
                if tid:
                    candles[tid] = (json.loads(p.read_text("utf-8")), m["result"])
        if not candles:
            continue
        first_q = min(c[0]["end_period_ts"] for c, _ in candles.values() if c)
        start = max(reg[0] + timedelta(days=14), datetime.fromtimestamp(first_q, timezone.utc).date())
        cps = [d for d in pd.date_range(start, last_reg).date if d.day in (1, 15)]
        close_day = first_post - timedelta(days=0)
        ends = R.season_end_ratings(league, season - 1)
        prior = R.preseason_prior(league, season, last=ends if ends and ends["n_games"] >= 30 else None,
                                  teams=R.league_teams(st))
        for cp in cps:
            through = cp - timedelta(days=1)
            rt = R.fit_ratings(st.get("games") or {}, through=through, prior=prior, league=league, teams=R.league_teams(st))
            res = SS.simulate(league, season, n=n_sims, seed=season, state={"store": st, "through": through, "ratings": rt})
            for tid, (c, result) in candles.items():
                q, qc = _quote(c, cp), _quote(c, close_day)
                pm = ((res.get("teams") or {}).get(tid) or {}).get("p_title")
                if q is None or qc is None or pm is None:
                    continue
                rows.append({"league": league, "season": season, "checkpoint": cp, "team": tid, "model_p": pm,
                             "bid": q["bid"], "ask": q["ask"], "close_mid": (qc["bid"] + qc["ask"]) / 2,
                             "outcome": 1.0 if result == "yes" else 0.0, "oi": q["oi"]})
    return pd.DataFrame(rows)


def selections(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for _, r in df.iterrows():
        for side, cost, pm, fc, y in (("yes", r.ask, r.model_p, r.close_mid, r.outcome),
                                      ("no", 1 - r.bid, 1 - r.model_p, 1 - r.close_mid, 1 - r.outcome)):
            c = cost + K.fee(cost)
            if not 0 < c < 1:
                continue
            out.append({**r.to_dict(), "selection": side, "price_dec": 1 / c, "model_p_sel": pm, "fair_p_close": fc,
                        "model_ev": pm / c - 1, "clv": fc / c - 1, "profit": (1 / c - 1) if y == 1 else -1.0,
                        "mid": (r.bid + r.ask) / 2 if side == "yes" else 1 - (r.bid + r.ask) / 2})
    return pd.DataFrame(out)
