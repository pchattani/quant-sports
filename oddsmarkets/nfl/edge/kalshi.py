"""
Kalshi NFL decisions for the edge table (prices from sources/kalshi_history.py's parquet files).

Games (KXNFLGAME, one YES market per team): at a decision time t (kickoff - 24 h, kickoff - 1 h) the last hourly candle
at or before t gives each team's yes bid / ask. Buying team X costs min(ask_X, 1 - bid_other) (YES on X, or NO on the
other side); the taker fee 0.07 x P x (1 - P) per contract is added, so price_dec = 1 / (P + fee). fair_p_decision =
the two mid-points normalised; fair_p_close = the same from the last candle before kickoff (the Kalshi close).
A quote is used only when both sides are two-sided (0 < bid <= ask < 1) and each spread is <= 0.12.

Totals (KXNFLTOTAL "Over X") and spreads (KXNFLSPREAD "<TEAM> wins by over X"): per game and decision, the strike whose
mid is nearest 0.5 AT THE DECISION (never chosen with a later price); YES and NO are the two selections.

model_p: the game model's probabilities. Since 21 Oct 2026 each decision gets its own information set (`P_by_hour`):
t - 1 h the close-mode rows (listed starters, known from the inactives 90 minutes before kickoff, and the game-day
weather), t - 24 h the openA rows (ratings through the previous week, the QB who started the team's latest game, no
weather), so the day-before decision has no look-ahead. Before, both used the close-mode rows (a look-ahead at
t - 24 h noted in docs/research/nfl_edge.md). `book` decisions price Kalshi's last pre-kickoff quote with the de-vigged book
close (nflverse) as model_p, i.e. "is Kalshi behind the books at kickoff?", judged on outcomes only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.common.fees import KALSHI_TAKER_RATE, kalshi_cost
from oddsmarkets.nfl.edge import market as MK
from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import game as GM

FEE = KALSHI_TAKER_RATE      # common/fees.py
MAX_SPREAD = 0.12


def load():
    root = D.cache_root() / "edge"
    m = pd.read_parquet(root / "kalshi_markets.parquet")
    c = pd.read_parquet(root / "kalshi_candles.parquet", columns=["ticker", "ts", "yes_bid_close", "yes_ask_close", "volume"])
    c = c.sort_values(["ticker", "ts"])
    return m, c


def quote_at(c: pd.DataFrame, tickers, t) -> pd.DataFrame:
    """Last candle at or before t for each ticker: bid, ask (dollars), with a validity flag."""
    sub = c[c["ticker"].isin(list(tickers)) & (c["ts"] <= t)]
    q = sub.groupby("ticker").tail(1).set_index("ticker")
    q = q.assign(ok=(q["yes_bid_close"] > 0) & (q["yes_bid_close"] <= q["yes_ask_close"]) & (q["yes_ask_close"] < 1)
                 & ((q["yes_ask_close"] - q["yes_bid_close"]) <= MAX_SPREAD))
    return q


def _cost(p):
    return kalshi_cost(p)


def game_rows(m: pd.DataFrame, c: pd.DataFrame, P: pd.DataFrame, hours=(24.0, 1.0), book: bool = True,
              P_by_hour: dict | None = None) -> pd.DataFrame:
    """Per game, team and decision. P: the close-mode predictions (game_id, p_home, nfv_ml_h, nfv_ml_a, margin);
    P_by_hour {hours: predictions} overrides P's p_home for that decision (e.g. {24.0: openA rows})."""
    ph_by = {h: X.drop_duplicates("game_id").set_index("game_id")["p_home"] for h, X in (P_by_hour or {}).items()}
    g = m[(m["kind"] == "game") & m["game_id"].notna()]
    if "primary" in g:
        g = g[g["primary"].fillna(True).astype(bool)]     # Kalshi lists zero-volume duplicates on a wrong date
    Pi = P.set_index("game_id")
    rows = []
    for gid, gg in g.groupby("game_id"):
        if gid not in Pi.index or len(gg) != 2:
            continue
        r = Pi.loc[gid]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        ko = pd.Timestamp(gg["kickoff_utc"].iloc[0])
        tk = dict(zip(gg["team"], gg["ticker"]))
        home, away = gg["home_team"].iloc[0], gg["away_team"].iloc[0]
        if home not in tk or away not in tk:
            continue
        qc = quote_at(c, tk.values(), ko - pd.Timedelta(minutes=1))
        if len(qc) < 2 or not qc["ok"].all():
            continue
        mid = (qc["yes_bid_close"] + qc["yes_ask_close"]) / 2
        fc_h = mid[tk[home]] / (mid[tk[home]] + mid[tk[away]])
        y_h = np.nan if not np.isfinite(r["margin"]) else (1.0 if r["margin"] > 0 else (0.0 if r["margin"] < 0 else 0.5))
        dec = [(f"kalshi_t-{int(h)}h", ko - pd.Timedelta(hours=h), float(ph_by[h].get(gid, np.nan)) if h in ph_by
                else float(r["p_home"])) for h in hours]
        if book:
            from oddsmarkets.nfl.edge.prices import devig2
            ph, _ = devig2(r["nfv_ml_h"], r["nfv_ml_a"])
            if np.isfinite(ph):
                dec.append(("kalshi_kickoff_v_book", ko - pd.Timedelta(minutes=1), float(ph)))
        for name, t, p_home in dec:
            q = quote_at(c, tk.values(), t)
            if len(q) < 2 or not q["ok"].all():
                continue
            b = q["yes_bid_close"]
            a = q["yes_ask_close"]
            md = (b + a) / 2
            f_h = md[tk[home]] / (md[tk[home]] + md[tk[away]])
            for sel, me, other, mp, fd, fc, y in (("home", home, away, p_home, f_h, fc_h, y_h),
                                                   ("away", away, home, 1 - p_home, 1 - f_h, 1 - fc_h, 1 - y_h)):
                px = min(a[tk[me]], 1 - b[tk[other]])
                rows.append({"event_id": gid, "season": int(r["season"]), "week": int(r["week"]), "start_time": ko,
                             "market": "moneyline", "selection": sel, "line": np.nan, "decision_time": t,
                             "model_p": mp, "price_dec": 1.0 / _cost(px), "price_src": name, "fair_p_decision": fd,
                             "price_close": np.nan, "fair_p_close": fc, "outcome": y, "p_push": 0.0,
                             "max_stake_hint": float(q["volume"].sum()) if "volume" in q else np.nan, "decision": name})
    return pd.DataFrame(rows)


def ladder_rows(m: pd.DataFrame, c: pd.DataFrame, P: pd.DataFrame, kind: str, kk_by: dict, tk_by: dict,
                hours=(24.0, 1.0), P_by_hour: dict | None = None, cal=None) -> pd.DataFrame:
    """Totals ('total') or spreads ('spread'): the strike nearest 0.5 at each decision. P_by_hour as in game_rows
    (mu, sigma, mu_t, sigma_t taken from that decision's rows); cal: {season: (a, b)} market-line Platt maps applied
    to P(yes | no push) (game.market_cover / market_over), None = raw."""
    g = m[(m["kind"] == kind) & m["game_id"].notna() & m["floor_strike"].notna()]
    Pi = P.drop_duplicates("game_id").set_index("game_id")
    Pi_by = {h: X.drop_duplicates("game_id").set_index("game_id") for h, X in (P_by_hour or {}).items()}
    rows = []
    for gid, gg in g.groupby("game_id"):
        if gid not in Pi.index:
            continue
        r = Pi.loc[gid]
        ko = pd.Timestamp(gg["kickoff_utc"].iloc[0])
        qclose = quote_at(c, gg["ticker"], ko - pd.Timedelta(minutes=1))
        r_close = r
        for h in hours:
            r = Pi_by[h].loc[gid] if h in Pi_by and gid in Pi_by[h].index else r_close
            t = ko - pd.Timedelta(hours=h)
            q = quote_at(c, gg["ticker"], t)
            q = q[q["ok"]]
            if q.empty:
                continue
            md = (q["yes_bid_close"] + q["yes_ask_close"]) / 2
            tick = (md - 0.5).abs().idxmin()
            mk = gg.set_index("ticker").loc[tick]
            X = float(mk["floor_strike"])
            s = int(r["season"])
            if kind == "total":
                Pm = MK.total_pmf(np.array([r["mu_t"]]), float(r["sigma_t"]), tk_by.get(s))
                p_yes, push = MK.over_prob(Pm, np.array([X]))
                y = 1.0 if r["total"] > X else (0.0 if r["total"] < X else 0.5)
                line = X
            else:
                team = mk["team"]
                sign = 1.0 if team == r["home"] else -1.0
                Pm = GM.margin_pmf(np.array([sign * r["mu"]]), float(r["sigma"]), kk_by.get(s))
                p_yes, push = MK.cover_home(Pm, np.array([-X]))          # team margin > X
                y = 1.0 if sign * r["margin"] > X else (0.0 if sign * r["margin"] < X else 0.5)
                line = X
            if cal and cal.get(s):                       # the map is for P(home covers) / P(over)
                home_side = kind == "total" or sign > 0
                pq = float(p_yes[0]) if home_side else 1.0 - float(p_yes[0])
                pq = GM.platt(pq, cal[s])
                p_yes = np.array([pq if home_side else 1.0 - pq])
            b, a = float(q.loc[tick, "yes_bid_close"]), float(q.loc[tick, "yes_ask_close"])
            fd = (a + b) / 2
            fc = np.nan
            if tick in qclose.index and bool(qclose.loc[tick, "ok"]):
                fc = float((qclose.loc[tick, "yes_bid_close"] + qclose.loc[tick, "yes_ask_close"]) / 2)
            name = f"kalshi_t-{int(h)}h"
            for sel, mp, px, f1, f2, yy in (("yes", p_yes[0], a, fd, fc, y), ("no", 1 - p_yes[0], 1 - b, 1 - fd, 1 - fc, 1 - y)):
                rows.append({"event_id": gid, "season": s, "week": int(r["week"]), "start_time": ko,
                             "market": kind, "selection": f"{sel}:{mk.get('team') if kind == 'spread' else 'over'}>{X}",
                             "line": line, "decision_time": t, "model_p": float(mp), "price_dec": 1.0 / _cost(px),
                             "price_src": name, "fair_p_decision": f1, "price_close": np.nan, "fair_p_close": f2,
                             "outcome": yy if np.isfinite(r["margin"]) else np.nan, "p_push": float(push[0]), "decision": name})
    return pd.DataFrame(rows)
