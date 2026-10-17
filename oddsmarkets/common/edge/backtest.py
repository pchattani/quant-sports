"""
Event-ordered bankroll simulation.

Timeline: each slate is decided at its first decision_time; each bet settles at its `settle_at`. Events are
processed in time order, settlements before decisions at the same instant. At a slate:

    equity  = cash + stakes outstanding (marked at cost)          peak = running max of equity
    dd      = 1 - equity / peak  ->  drawdown multiplier           (throttle, SizingConfig.dd_*)
    f       = size_slate(decision view, cfg) * multiplier          bankroll fractions
    stake   = f * equity, then min(stake, max_stake_hint) (liquidity), then scaled so sum <= cash

Within a slate, duplicate decisions on the same selection (several price sources or decision times) collapse to
the best price, so the bankroll never doubles up on one selection. Sizing sees only `decision_view` columns;
outcome, close and settlement columns are read only when a bet settles.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .calibrate import to_seconds
from .kelly import SizingConfig, candidates, drawdown_multiplier, full_kelly, size_slate
from .schema import decision_view

_VIEW_EXTRA = ("q", "excl_key", "edge", "edge_raw")


@dataclass
class SimResult:
    cfg: SizingConfig
    ledger: pd.DataFrame          # one row per bet placed
    equity: pd.DataFrame          # time, equity (marked at cost), cash
    slates: pd.DataFrame          # per slate: time, equity before, staked, profit (when settled), log return
    initial: float

    @property
    def final(self) -> float:
        return float(self.equity["equity"].iloc[-1]) if len(self.equity) else self.initial


def dedupe_best_price(c: pd.DataFrame) -> pd.DataFrame:
    """One row per (slate, event, market, line, selection): the best decision-time price (ties: earliest)."""
    if not len(c):
        return c
    key = ["slate", "event_id", "market", "line", "selection"]
    c = c.assign(_l=c["line"].fillna(-9999.0))
    c = c.sort_values(["price_dec", "decision_time"], ascending=[False, True])
    c = c.drop_duplicates(subset=["slate", "event_id", "market", "_l", "selection"], keep="first")
    return c.drop(columns="_l").sort_index()


def simulate(d: pd.DataFrame, cfg: SizingConfig, initial: float = 10_000.0, cache: dict | None = None) -> SimResult:
    """
    `d` is the prepared + shrunk frame (calibrate.prepare -> walk_forward_shrink). `cache` (any dict) memoises
    the bankroll-independent full-Kelly vector per slate across runs that share the same filters.
    """
    view_all = decision_view(d, extra=_VIEW_EXTRA)
    cand_mask = candidates(view_all, cfg) & ~d.get("warmup", pd.Series(False, index=d.index)).astype(bool)
    c = d[cand_mask]
    c = dedupe_best_price(c)
    if not len(c):
        eq = pd.DataFrame({"time": [pd.Timestamp(0, tz="UTC")], "equity": [initial], "cash": [initial]})
        return SimResult(cfg, pd.DataFrame(), eq, pd.DataFrame(), initial)
    c = c.assign(_dec_s=to_seconds(c["decision_time"]), _set_s=to_seconds(c["settle_at"]))
    slate_t = c.groupby("slate")["_dec_s"].min().sort_values(kind="stable")
    by_slate = {k: g for k, g in c.groupby("slate")}

    cash = initial
    outstanding = 0.0
    peak = initial
    pending: list = []  # heap of (settle_s, seq, ledger index)
    seq = 0
    rows = []
    eq_t, eq_v, eq_c = [], [], []
    slate_rows = []
    slate_profit: dict = {}

    def settle_until(t):
        nonlocal cash, outstanding, peak
        last = None
        while pending and pending[0][0] <= t:
            ts, _, li = heapq.heappop(pending)
            r = rows[li]
            payout = r["stake"] * (1.0 + r["profit_unit"])
            cash += payout
            outstanding -= r["stake"]
            r["profit"] = r["stake"] * r["profit_unit"]
            slate_profit[r["slate"]] = slate_profit.get(r["slate"], 0.0) + r["profit"]
            last = ts
            if not pending or pending[0][0] > ts:
                eq = cash + outstanding
                peak = max(peak, eq)
                eq_t.append(ts)
                eq_v.append(eq)
                eq_c.append(cash)
        return last

    for slate, t in slate_t.items():
        settle_until(t)
        equity = cash + outstanding
        if equity <= 1e-9:
            break
        dd = 1.0 - equity / peak
        mult = drawdown_multiplier(dd, cfg) if cfg.use_caps else 1.0
        g = by_slate[slate]
        view = decision_view(g, extra=_VIEW_EXTRA)
        full = None
        if cfg.method == "kelly":
            ck = (slate, cfg.simultaneous, cfg.use_shrunk, cfg.min_edge, cfg.min_prob, cfg.max_price)
            if cache is not None and ck in cache:
                full = cache[ck]
            else:
                full = full_kelly(view, cfg)
                if cache is not None:
                    cache[ck] = full
        f = size_slate(view, cfg, bankroll_frac_flat=initial / equity, full=full) * mult
        stake = f * equity
        hint = g["max_stake_hint"].to_numpy(float)
        stake = np.where(np.isfinite(hint) & (hint >= 0), np.minimum(stake, hint), stake)
        tot = stake.sum()
        if tot > cash and tot > 0:
            stake *= cash / tot
        placed = stake > 0
        if not placed.any():
            slate_rows.append({"slate": slate, "t": t, "equity": equity, "staked": 0.0, "n": 0, "dd": dd,
                               "mult": mult})
            continue
        cash -= stake[placed].sum()
        outstanding += stake[placed].sum()
        gp = g[placed]
        for (ix, r), s, fr in zip(gp.iterrows(), stake[placed], f[placed]):
            rows.append({"idx": ix, "slate": slate, "sport": r["sport"], "league": r["league"], "market": r["market"],
                         "price_src": r["price_src"], "event_id": r["event_id"], "selection": r["selection"],
                         "decision_time": r["decision_time"], "start_time": r["start_time"],
                         "price_dec": r["price_dec"], "q": r["q"], "model_p": r["model_p"], "edge": r["edge"],
                         "edge_raw": r["edge_raw"], "frac": fr, "stake": s, "equity_at_bet": equity,
                         "outcome": r["outcome"], "profit_unit": r["profit_unit"], "clv": r["clv"],
                         "beat_close": r["beat_close"], "lead_h": r["lead_h"], "profit": np.nan})
            heapq.heappush(pending, (r["_set_s"], seq, len(rows) - 1))
            seq += 1
        slate_rows.append({"slate": slate, "t": t, "equity": equity, "staked": float(stake[placed].sum()),
                           "n": int(placed.sum()), "dd": dd, "mult": mult})
    settle_until(np.inf)

    ledger = pd.DataFrame(rows)
    eq = pd.DataFrame({"time": pd.to_datetime(np.asarray(eq_t, float), unit="s", utc=True), "equity": eq_v,
                       "cash": eq_c})
    eq = pd.concat([pd.DataFrame({"time": [pd.to_datetime(slate_t.iloc[0], unit="s", utc=True)],
                                  "equity": [initial], "cash": [initial]}), eq], ignore_index=True)
    sl = pd.DataFrame(slate_rows)
    if len(sl):
        sl["profit"] = sl["slate"].map(slate_profit).fillna(0.0)
        sl["ret"] = np.where(sl["equity"] > 0, sl["profit"] / sl["equity"], 0.0)
        sl["logret"] = np.log1p(sl["ret"].clip(lower=-0.999999))
        sl["time"] = pd.to_datetime(sl["t"], unit="s", utc=True)
    return SimResult(cfg, ledger, eq, sl, initial)
