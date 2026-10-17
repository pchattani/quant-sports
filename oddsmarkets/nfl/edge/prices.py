"""
Prices at decision times for the NFL edge research.

Sources (what exists on disk; surveyed 2 Oct 2026)
    nflverse schedules  closing spread (1999 ->), closing moneyline and spread / total prices (2006 ->), one line per
                        game ("the close"; nflverse does not say which book). `spread_line` is "home favoured by".
    ESPN core odds      per-book lines from the season stores (GAME.lines, parsed by sources/espn.compact_lines):
                        closes by book from 2017; OPENING lines only where ESPN kept an open block: 2023 (totals on
                        128 games, spreads on 13), 2024 (ESPN BET, 284 games), 2025 (ESPN BET 180 / DraftKings 105)
                        and 2026 (DraftKings). Earlier seasons have no opener on ESPN (the movement history endpoint
                        answers empty), so CLV at the open is testable on 2023 -> only.
    Kalshi              hourly candles (sources/kalshi_history.py; data/nfl/cache/edge/kalshi_*.parquet).

Conventions: spread_home is the home handicap (negative = home favoured); prices are American in the stores and
decimal here; de-vig is multiplicative over the two sides (`devig2`).
"""
from __future__ import annotations

import math
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.common.edge import devig as _dv

ET = ZoneInfo("America/New_York")


def am_to_dec(a) -> float:
    try:
        x = float(a)
    except (TypeError, ValueError):
        return np.nan
    if not math.isfinite(x) or -100 < x < 100:
        return np.nan
    return 1.0 + (x / 100.0 if x > 0 else 100.0 / -x)


def devig2(d1, d2):
    """Multiplicative de-vig of two decimal prices -> (p1, p2); NaN when either is missing."""
    return _dv.multiplicative_pair(np.asarray(d1, float), np.asarray(d2, float))          # common/edge/devig.py


def kickoff_utc(gameday, gametime) -> pd.Timestamp:
    try:
        t = pd.Timestamp(f"{gameday} {gametime or '13:00'}").tz_localize(ET)
        return t.tz_convert("UTC")
    except Exception:  # noqa: BLE001
        return pd.NaT


def _blk(b: dict | None, pre: str) -> dict:
    b = b or {}
    sp = b.get("spread_price") or [None, None]
    tp = b.get("total_price") or [None, None]
    return {f"{pre}_spread_home": b.get("spread_home"), f"{pre}_sp_h": am_to_dec(sp[0]), f"{pre}_sp_a": am_to_dec(sp[1]),
            f"{pre}_total": b.get("total"), f"{pre}_ov": am_to_dec(tp[0]), f"{pre}_un": am_to_dec(tp[1]),
            f"{pre}_ml_h": am_to_dec(b.get("ml_home")), f"{pre}_ml_a": am_to_dec(b.get("ml_away"))}


def game_prices(seasons=None) -> pd.DataFrame:
    """One row per game: kickoff (UTC), the nflverse close (`nfv_*`), ESPN's main-book open (`eo_*`, with `eo_src`)
    and close (`ec_*`). Spread prices sp_h / sp_a are for home / away at `*_spread_home`."""
    sch = pd.read_parquet(D.schedules_path())
    if seasons is not None:
        sch = sch[sch["season"].isin(list(seasons))]
    rows = []
    stores: dict[int, dict] = {}
    for r in sch.itertuples(index=False):
        s = int(r.season)
        rec = {"game_id": r.game_id, "season": s, "week": int(r.week), "gtype": r.game_type,
               "kickoff": kickoff_utc(r.gameday, r.gametime), "home": r.home_team, "away": r.away_team}
        sl = r.spread_line
        rec.update({"nfv_spread_home": -float(sl) if pd.notna(sl) else np.nan,
                    "nfv_sp_h": am_to_dec(r.home_spread_odds), "nfv_sp_a": am_to_dec(r.away_spread_odds),
                    "nfv_total": float(r.total_line) if pd.notna(r.total_line) else np.nan,
                    "nfv_ov": am_to_dec(r.over_odds), "nfv_un": am_to_dec(r.under_odds),
                    "nfv_ml_h": am_to_dec(r.home_moneyline), "nfv_ml_a": am_to_dec(r.away_moneyline)})
        if s >= 2017:
            if s not in stores:
                stores[s] = D.load_store(s).get("games") or {}
            g = stores[s].get(r.game_id) or {}
            L = g.get("lines") or {}
            op, cl = L.get("open"), L.get("close")
            rec.update(_blk(op, "eo"))
            rec.update(_blk(cl, "ec"))
            rec["eo_src"] = (op or {}).get("src")
            rec["ec_src"] = (cl or {}).get("src")
            if g.get("kickoff"):
                try:
                    rec["kickoff"] = pd.Timestamp(g["kickoff"]).tz_convert("UTC")
                except Exception:  # noqa: BLE001
                    pass
            if s == 2026 and not np.isfinite(rec["nfv_spread_home"]) and L.get("spread_home") is not None:
                rec.update(_blk(L, "nfv"))
        rows.append(rec)
    df = pd.DataFrame(rows)
    for c in df.columns:
        if c.endswith(("_spread_home", "_total")):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
