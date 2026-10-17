"""
Season futures priced by the season simulation at a decision date, with every input fitted before that date
(the backtest's season_calibration recipe: team strength chained from three seasons earlier with the preseason prior,
fitted on games before `through`; game coefficients from walk-forward rows strictly before it).

    sim_at(season, through, n)  -> {team: {"win_dist": [...], "p_playoffs", "p_div", ...}}

Win-total ladders ("N+ wins", Kalshi KXNFLWINS) are priced as P(W >= N) from win_dist (a tie counts half a win in
the NFL's percentage but not in a win count: win_dist is the distribution of wins).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import game as GM
from oddsmarkets.nfl.models import season_sim as SS
from oddsmarkets.nfl.models import team_strength as TS


def sim_at(season: int, through, wf: pd.DataFrame, n: int = 10000, seed: int = 0, depth_qb: bool = False) -> dict:
    """depth_qb: teams without a game yet start their preseason depth-chart QB1 (valued from the QB book); without
    it a team's QB term is the league average before its first game. Off by default: on 2006-2025 week-1 checkpoints it
    made playoff log-loss worse by 0.016 (CI 0.008-0.024) and division by 0.014 (edge experiment futures_qb)."""
    through = pd.Timestamp(through)
    if through.tzinfo is not None:
        through = through.tz_convert(None)
    p_ts = TS.params()
    last, book = None, {}
    for s in range(season - 3, season):
        u = D.unit_rows(s)
        prior = TS.preseason_prior(last, s, p_ts, book, TS.continuity(s))
        end = TS.fit(u, s, None, prior, p_ts)
        TS.update_qb_book(book, end)
        last = end
    prior = TS.preseason_prior(last, season, p_ts, book, TS.continuity(season))
    G = D.games_frame([season - 1, season])
    gs = G[(G["season"] == season) & (G["gtype"] == "REG")]
    u = D.unit_rows(season) if season in D.pbp_seasons() else pd.DataFrame()
    r = TS.fit(u, season, through, prior, p_ts, teams=sorted(set(gs["home"]) | set(gs["away"])))
    rd = r.as_dict()
    rd["qb_prior"] = prior["qbs"]
    w = wf[wf["mode"] == "close"] if "mode" in wf else wf
    prm = GM.fit_from_rows(w[w["date"] < through])
    qb = {}
    if depth_qb:
        from oddsmarkets.nfl.edge.walk import depth_qb1
        st = rd.get("starters") or {}
        qb = {t: q for t, q in depth_qb1(season).items() if t not in st}
    res = SS.simulate(season, n=n, seed=seed, state={"games": G, "through": through, "ratings": rd, "params": prm, "qb": qb})
    return res["teams"]


def p_at_least(win_dist, k: float) -> float:
    d = np.asarray(win_dist, float)
    return float(d[int(np.ceil(k - 1e-9)):].sum())


# ── Kalshi futures decisions ────────────────────────────────────────────────

def season_last_kickoff(season: int) -> pd.Timestamp | None:
    """UTC kickoff of the season's last regular-season game (scheduled if not yet played)."""
    G = D.games_frame([season])
    reg = G[(G["season"] == season) & (G["gtype"] == "REG")]
    k = pd.to_datetime(reg["kickoff"], utc=True, errors="coerce").dropna()
    return k.max() if len(k) else None


def final_outcomes(season: int) -> dict:
    """{team: {"wins", "playoffs", "div"}} for a completed regular season (None when unfinished)."""
    from oddsmarkets.nfl.models import backtest as BT
    G = D.games_frame([season])
    reg = G[(G["season"] == season) & (G["gtype"] == "REG")]
    if reg.empty or not reg["played"].all():
        return {}
    wins: dict[str, float] = {}
    for r in reg.itertuples(index=False):
        wins.setdefault(r.home, 0.0)
        wins.setdefault(r.away, 0.0)
        if r.margin > 0:
            wins[r.home] += 1
        elif r.margin < 0:
            wins[r.away] += 1
    out = BT.season_outcomes(G, season) or {}
    return {t: {"wins": w, "playoffs": float(t in out.get("playoffs", set())) if out else np.nan,
                "div": float(t in out.get("div", set())) if out else np.nan} for t, w in wins.items()}


def kalshi_rows(season: int, checkpoints: list, wf: pd.DataFrame, m: pd.DataFrame, c: pd.DataFrame, n: int = 10000) -> pd.DataFrame:
    """Win-total ladders, make-the-playoffs and division markets at each checkpoint date: model = sim_at(checkpoint),
    price = Kalshi ask (+ taker fee) at the checkpoint, fair_p_decision = mid, fair_p_close = mid at the NEXT
    checkpoint (a later price; futures have no single close), outcome from the final standings when complete.

    Timing (EDGE_PROTOCOL section 5): decision_time = the checkpoint (00:00 UTC; the quote is the last hourly candle
    at or before it, the simulation uses games before it). A season future has no kickoff after which betting is
    in-play, so start_time = the kickoff of the season's last regular-season game (the earliest time every one of
    these propositions can be fully decided) and settle_time = that kickoff + 24 h (capital stays locked until the
    regular season ends; Kalshi may settle a clinched ladder rung earlier, which this ignores conservatively).
    Before 2 Oct 2026 start_time was the checkpoint itself (decision_time == start_time on every futures row).

    Tradeability (`quality_ok`, `quality_note`; False rows are kept for the record but never bet or scored):
      * relisted:   Kalshi listed the 2025 win totals twice (KXNFLWINS-<TEAM>-25-T<k> from May, then -25B- from
                    28 Aug). Every rung of the first listing settled NO, even DEN over 8.5 with 14 wins, so the
                    standings-based outcome is not what that contract paid. A listing whose finalized settlement
                    contradicts the standings anywhere is flagged in full, and where two listings quote the same
                    (team, kind, line) at a checkpoint only the one consistent with settlement is kept.
      * closed:     the market had closed (or settled) by the checkpoint, so its last candle is not a live quote.
      * stale:      the last candle at or before the checkpoint is more than STALE_H hours old.
    These rows were behind the poor calibration of the futures prices in the 2 Oct 2026 report (wins slope 0.81).
    The division slope (0.35 there, 0.09 on 2025 alone) comes from 8 divisions x 3 checkpoints of one season with
    six long-shot division winners (NE, CHI, CAR, JAX, DEN, SEA). The quotes are coherent (each division's mids sum
    to ~1.02) and Kalshi's settlements agree with the standings, so that slope is small-sample noise, not a data
    error."""
    from oddsmarkets.nfl.edge import kalshi as K
    fut = m[(m["season"] == season) & m["kind"].isin(["wins", "playoff", "division"]) & m["team"].notna()]
    if fut.empty:
        return pd.DataFrame()
    res = final_outcomes(season)
    bad_listing = _contradicted_listings(fut, res)
    season_end = season_last_kickoff(season)
    if season_end is None:
        return pd.DataFrame()
    settle = season_end + pd.Timedelta(hours=24)
    rows = []
    for k, cp in enumerate(checkpoints):
        t = pd.Timestamp(cp, tz="UTC")
        if t >= season_end:
            continue
        nxt = pd.Timestamp(checkpoints[k + 1], tz="UTC") if k + 1 < len(checkpoints) else None
        sim = sim_at(season, t, wf, n=n)
        q = K.quote_at(c, fut["ticker"], t)
        q = q[q["ok"]]
        qn = K.quote_at(c, fut["ticker"], nxt) if nxt is not None else None
        for mk in fut[fut["ticker"].isin(q.index)].itertuples(index=False):
            s = sim.get(mk.team)
            if not s:
                continue
            if mk.kind == "wins":
                ln = float(mk.line) if np.isfinite(getattr(mk, "line", np.nan)) else float(mk.floor_strike) - 0.5
                p = p_at_least(s["win_dist"], np.floor(ln) + 1)                 # YES iff wins > line
                y = (float(res[mk.team]["wins"] > ln) if mk.team in res else np.nan)
                market = "future_wins"
            elif mk.kind == "playoff":
                p, y, market = s["p_playoffs"], res.get(mk.team, {}).get("playoffs", np.nan), "future_playoffs"
            else:
                p, y, market = s["p_div"], res.get(mk.team, {}).get("div", np.nan), "future_division"
            b, a = float(q.loc[mk.ticker, "yes_bid_close"]), float(q.loc[mk.ticker, "yes_ask_close"])
            notes = []
            if _listing(mk.ticker) in bad_listing:
                notes.append("relisted")
            ct = pd.to_datetime(getattr(mk, "close_time", None), utc=True, errors="coerce")
            if pd.notna(ct) and ct <= t:
                notes.append("closed")
            qts = pd.to_datetime(q.loc[mk.ticker, "ts"], utc=True, errors="coerce") if "ts" in q else pd.NaT
            if pd.notna(qts) and (t - qts) > pd.Timedelta(hours=STALE_H):
                notes.append("stale")
            fd = (a + b) / 2
            fc = np.nan
            if qn is not None and mk.ticker in qn.index and bool(qn.loc[mk.ticker, "ok"]):
                fc = float((qn.loc[mk.ticker, "yes_bid_close"] + qn.loc[mk.ticker, "yes_ask_close"]) / 2)
            for sel, mp, px, f1, f2, yy in (("yes", p, a, fd, fc, y), ("no", 1 - p, 1 - b, 1 - fd, 1 - fc, 1 - y if np.isfinite(y) else np.nan)):
                rows.append({"event_id": mk.ticker, "season": season, "week": 0, "start_time": season_end,
                             "settle_time": settle, "market": market,
                             "selection": sel, "line": (float(mk.line) if np.isfinite(getattr(mk, "line", np.nan)) else float(mk.floor_strike) - 0.5) if mk.kind == "wins" else np.nan,
                             "decision_time": t, "model_p": float(mp), "price_dec": 1.0 / K._cost(px),
                             "price_src": "kalshi_future_ask", "fair_p_decision": f1, "price_close": np.nan,
                             "fair_p_close": f2, "outcome": yy, "p_push": 0.0, "decision": f"future_{k}",
                             "corr_group": f"{season}_{mk.team}", "quality_ok": not notes,
                             "quality_note": ",".join(notes), "_team": mk.team, "_kind": mk.kind})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    # two listings quoting one proposition at one checkpoint: keep a single tradeable row (the consistent listing)
    key = ["decision", "_team", "_kind", "line", "selection"]
    ok = out[out["quality_ok"]]
    dup = ok.duplicated(subset=key, keep=False)
    if dup.any():
        for _, g in ok[dup].groupby(key, dropna=False):
            drop = g.index[1:]                                   # all consistent: keep the first, flag the rest
            out.loc[drop, "quality_ok"] = False
            out.loc[drop, "quality_note"] = "duplicate_listing"
    return out.drop(columns=["_team", "_kind"])


STALE_H = 48.0


def _listing(ticker: str) -> str:
    """Listing key of a futures ticker: the series plus the season code (KXNFLWINS-DEN-25B-T8 -> KXNFLWINS-25B)."""
    parts = str(ticker).split("-")
    if parts[0] == "KXNFLWINS" and len(parts) >= 4:
        return f"{parts[0]}-{parts[2]}"
    return "-".join(parts[:2]) if len(parts) >= 2 else str(ticker)


def _contradicted_listings(fut: pd.DataFrame, res: dict) -> set:
    """Listings with at least one finalized market whose Kalshi result contradicts the final standings."""
    bad = set()
    if not res or "result" not in fut:
        return bad
    for mk in fut.itertuples(index=False):
        r = getattr(mk, "result", None)
        if r not in ("yes", "no") or mk.team not in res:
            continue
        if mk.kind == "wins":
            ln = float(mk.line) if np.isfinite(getattr(mk, "line", np.nan)) else float(mk.floor_strike) - 0.5
            y = float(res[mk.team]["wins"] > ln)
        elif mk.kind == "playoff":
            y = res[mk.team].get("playoffs", np.nan)
        else:
            y = res[mk.team].get("div", np.nan)
        if np.isfinite(y) and float(r == "yes") != y:
            bad.add(_listing(mk.ticker))
    return bad
