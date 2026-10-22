"""
Market-rate rows from Kalshi's closing prices, for competitions without a football-data.co.uk file:
the Saudi Pro League (a pooled league) and the UEFA club cups (Champions, Europa, Conference League).

Same idea as `market_rates` (docs/MODELS.md 2.5): each finished match with a closing price becomes one
extra continuous-Poisson row carrying the goal rates that reproduce that price, at weight `W_MKT` with
the own decay `XI_MKT`. The "close" is Kalshi's last two-sided quote (bid > 0, ask < 1) at or before
kick-off - 1 minute and at most 6 hours old, on all three markets; the mids are de-vigged proportionally
and turned into rates with `walkforward.implied_rates` (no total: the draw pins it).

**Off** unless `model_params.json` `kalshi_market_rows.on` is true (or FOOTBALL_KALSHI_ROWS=1 for a check).
Tested walk-forward 1 Dec 2025 - 20 Oct 2026: log-loss -0.030 for Saudi and for the UEFA cups, but the
pre-registered calibration clause failed, so a forward test runs from 23 Oct 2026 (football_edge.md 3.3b,
3.6). `refresh` keeps the cache (data/football/odds/kalshi, `kalshi_history`) current where the build runs:
the listings incrementally (common/kalshi_listing.refresh), then the candles of newly settled games, newest
first, paced by the fetcher and capped per run, so a cold cache (CI) fills over a few runs.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from functools import cache

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

LEAGUE_SLUGS = ("saudi-pro-league",)
CUP_SLUGS = ("champions-league", "europa-league", "conference-league")
SLUGS = LEAGUE_SLUGS + CUP_SLUGS
REFRESH_EVERY_H = 6.0
MAX_CALLS = 150                 # candle calls per refresh (three per game)
RECENT_DAYS = 400               # games older than this are never fetched (beyond the fits' useful memory)
STALE_H = 6.0                   # a quote older than this at kick-off is not a price


@cache
def on() -> bool:
    if os.environ.get("FOOTBALL_KALSHI_ROWS") in ("1", "true", "yes"):
        return True
    from oddsmarkets.football.competitions.league.fitting import PARAMS_PATH
    try:
        return bool((json.loads(PARAMS_PATH.read_text(encoding="utf-8")).get("kalshi_market_rows") or {}).get("on"))
    except Exception:  # noqa: BLE001
        return False


def refresh(slugs: tuple[str, ...] = SLUGS, max_calls: int = MAX_CALLS, every_h: float = REFRESH_EVERY_H) -> dict:
    """Bring the cache up to date (at most every `every_h` hours); never raises. Returns what it did."""
    from oddsmarkets.football.sources import kalshi_history as kh

    stamp = kh.CACHE / "refresh_rates.json"
    out = {"listings": 0, "games": 0, "calls": 0, "skipped": False}
    try:
        last = json.loads(stamp.read_text(encoding="utf-8")).get("at") if stamp.exists() else None
        if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < every_h * 3600:
            out["skipped"] = True
            return out
        series = kh.game_series()
        todo = []
        for slug in slugs:
            s = series.get(slug)
            if not s:
                continue
            ms = kh.settled_markets(s)                    # incremental listing refresh (kalshi_listing.refresh)
            out["listings"] += 1
            by_ev: dict[str, list[dict]] = {}
            for m in ms:
                by_ev.setdefault(m["event_ticker"], []).append(m)
            for ev, mlist in by_ev.items():
                if (kh.CACHE / "candles" / f"{ev}.json").exists():
                    continue
                exp = mlist[0].get("expected_expiration_time") or mlist[0].get("close_time")
                if not exp:
                    continue
                t = pd.Timestamp(exp)
                if (pd.Timestamp.now(tz="UTC") - t).days > RECENT_DAYS:
                    continue
                todo.append((t, s, ev, mlist))
        todo.sort(key=lambda x: x[0], reverse=True)      # newest first: the fit's weight is on recent games
        for _t, s, ev, mlist in todo:
            if out["calls"] + len(mlist) > max_calls:
                break
            kh.event_candles(s, ev, mlist)
            out["calls"] += len(mlist)
            out["games"] += 1
        out["left"] = max(len(todo) - out["games"], 0)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **out}), encoding="utf-8")
        logger.info("kalshi rates refresh: %s", out)
    except Exception as exc:  # noqa: BLE001 - a failed refresh leaves the cache as it was; the rows use what is there
        logger.warning("kalshi rates refresh failed: %s", exc)
        out["error"] = str(exc)
    return out


def closing_rates(slug: str, frame: pd.DataFrame) -> pd.DataFrame:
    """
    game_id, p_h/p_d/p_a and the implied rates mkt_h/mkt_a for every cached, settled Kalshi game of `slug`
    matched to a finished match of `frame` (columns game_id, home_team, away_team, match_date; plain club
    names): the same day +-1 and both names (pm_prices._same).
    """
    from oddsmarkets.football.research import pm_prices as pmp
    from oddsmarkets.football.research.walkforward import implied_rates
    from oddsmarkets.football.sources import kalshi_history as kh

    empty = pd.DataFrame(columns=["game_id", "p_h", "p_d", "p_a", "mkt_h", "mkt_a"])
    series = kh.game_series().get(slug)
    if not series or frame is None or not len(frame):
        return empty
    q = pmp.kalshi_quotes(kh.CACHE / "candles", kh.CACHE / "markets", {slug: series})
    if not len(q):
        return empty
    evs = q.groupby("event").agg(home=("home", "first"), away=("away", "first"), exp=("expected_expiration", "first")).reset_index()
    evs["day"] = (evs["exp"] - pd.Timedelta(hours=3)).dt.floor("D")
    fr = frame.assign(day=pd.to_datetime(frame.match_date, utc=True).dt.floor("D"))
    by_day = {d: g for d, g in fr.groupby("day")}
    hit = {}
    for r in evs.itertuples():
        for dd in (r.day, r.day - pd.Timedelta(days=1), r.day + pd.Timedelta(days=1)):
            g = by_day.get(dd)
            if g is None:
                continue
            ok = [(gid, ko) for gid, h, a, ko in zip(g.game_id, g.home_team, g.away_team, g.match_date)
                  if pmp._same(r.home, h) and pmp._same(r.away, a)]
            if len(ok) == 1:
                hit[r.event] = ok[0]
                break
    if not hit:
        return empty
    kick = pd.Series({e: pd.Timestamp(ko) for e, (_g, ko) in hit.items()})
    kick = kick.dt.tz_localize("UTC") if kick.dt.tz is None else kick.dt.tz_convert("UTC")
    at = pmp.quote_at(q[q.event.isin(hit)], kick - pd.Timedelta(minutes=1)).copy()
    at["mid"] = (at.bid + at.ask) / 2
    at = at[at.groupby("event")["mid"].transform("size") == 3]
    if not len(at):
        return empty
    piv = at.pivot_table(index="event", columns="selection", values="mid")
    piv = piv.div(piv.sum(1), axis=0)
    out = pd.DataFrame({"game_id": [str(hit[e][0]) for e in piv.index], "p_h": piv["home"].to_numpy(),
                        "p_d": piv["draw"].to_numpy(), "p_a": piv["away"].to_numpy()})
    out["mkt_h"], out["mkt_a"] = implied_rates(out[["p_h", "p_d", "p_a"]].to_numpy(float), np.full(len(out), np.nan))
    logger.info("%s: %d Kalshi games, %d matched to the store, %d with a closing quote", slug, len(evs), len(hit), len(out))
    return out.dropna(subset=["mkt_h", "mkt_a"])


def rows(train_df: pd.DataFrame, slug: str, weight: float | None = None, xi_fit: float | None = None,
         xi_mkt: float | None = None, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """The Kalshi market rows of `train_df` (plain names), in its columns, as `market_rates.market_rows` makes them."""
    from oddsmarkets.football.sources import market_rates as mr

    if train_df is None or not len(train_df) or "game_id" not in train_df or slug not in SLUGS:
        return train_df.iloc[0:0] if train_df is not None else pd.DataFrame()
    try:
        k = closing_rates(slug, train_df)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: Kalshi rates unavailable (%s)", slug, exc)
        return train_df.iloc[0:0]
    if not len(k):
        return train_df.iloc[0:0]
    r = k.drop_duplicates("game_id").set_index("game_id")
    gid = train_df["game_id"].astype(str)
    hit = gid.isin(r.index).to_numpy()
    extra = train_df[hit].copy()
    rr = r.loc[gid[hit]]
    extra["home_xg"] = rr["mkt_h"].to_numpy()
    extra["away_xg"] = rr["mkt_a"].to_numpy()
    weight = mr.W_MKT if weight is None else weight
    xi_mkt = mr.XI_MKT if xi_mkt is None else xi_mkt
    w0 = extra["weight"].fillna(1.0) if "weight" in extra else 1.0
    extra["weight"] = w0 * weight * mr.decay_factor(extra["match_date"], xi_fit, xi_mkt, now)
    extra["game_id"] = extra["game_id"].astype(str) + ":kmkt"
    return extra
