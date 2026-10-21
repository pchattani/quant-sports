"""
data/edge/basketball.parquet (docs/research/EDGE_PROTOCOL.md section 3): one row per selection per decision.

Decisions
  * ESPN open (price_src espn_espnbet_open / espn_dk_open): the opening moneyline, spread and total of the book
    ESPN carries with open and close blocks (ESPN BET 2024-2025, DraftKings 2026), every test-season game with an
    open price (NBA and WNBA 2024-2026). decision_time = 08:00 US Eastern on the game day (ESPN does not stamp
    the open; the model uses games through the previous US day).
  * Kalshi (price_src kalshi_ask): the game-winner market at the same decision time, buying at the ask plus the
    taker fee; fair_p_close = the mid of the last hourly candle before tip-off. max_stake_hint = open interest
    (contracts) at the decision candle.

model_p (since the October 2026 model-improvement program) is the market-informed model as the site publishes it
(research/improve.py, models/informed.py: margin from the close predictor C with its probit calibration, total from
the close-total predictor CT; it never uses the game's own prices); model_p_raw is the production base model (M0
margin, production-structure total). `write(model="c2")` reproduces the 2 October rows (C2 = C shrunk towards the
open; model_p_raw M1/T2). fair_p_* are multiplicative de-vigs (`devig` column); for spreads
and totals fair_p_close is the closing market's win probability AT THE DECISION LINE, conditional on no push
(close_push gives the push probability), so a line move counts as closing-line value.
line_close is the closing line of the selection (spread: the closing home line, negated for the away side; total:
the closing total; NaN for moneylines and Kalshi). The portfolio layer gives no CLV where it differs from `line`
(price_close is the price AT the closing line), so the shared report no longer reads line moves as CLV.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.research import experiments as X
from oddsmarkets.basketball.research import kalshi as K
from oddsmarkets.basketball.research import markets as M

logger = logging.getLogger(__name__)

COLS = ["event_id", "sport", "league", "season", "start_time", "market", "selection", "line", "decision_time",
        "model_p", "price_dec", "price_src", "fair_p_decision", "price_close", "fair_p_close", "outcome", "slate",
        "corr_group", "max_stake_hint", "devig", "model_p_raw", "model_push", "close_push", "model_ev", "clv", "stype",
        "line_close"]


def _abbr(league: str, seasons) -> dict[int, dict[str, str]]:
    out = {}
    for s in seasons:
        st = G.load_store(league, int(s)) or {}
        out[int(s)] = {t: (v or {}).get("abbr") for t, v in (st.get("teams") or {}).items()}
    return out


def _finish(out: pd.DataFrame) -> pd.DataFrame:
    out["sport"] = "basketball"
    out["slate"] = out["league"] + "_" + out["day"].astype(str)
    out["corr_group"] = out["league"] + "_" + out["event_id"].astype(str)
    out["devig"] = np.where(out["price_src"] == "kalshi_ask", "mid", "multiplicative")
    out["start_time"] = pd.to_datetime(out["start_time"], utc=True)
    out["decision_time"] = pd.to_datetime(out["decision_time"], utc=True)
    for c in COLS:
        if c not in out:
            out[c] = np.nan
    extra = [c for c in ("day", "gp", "price_clv", "model_p_c2") if c in out]
    return out[COLS + extra]


def league_rows(league: str, lag: int = 1, model: str = "informed") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Protocol rows for one league. model="informed" (October 2026): model_p is the market-informed model as the
    site publishes it (research/improve.py: close predictor C with the probit calibration for margins, the close-total
    predictor CT for totals; no use of the game's own prices), model_p_raw the production base model (M0 margin,
    production-structure totals). model="c2": the 2 October rows (C2 = C shrunk towards the open)."""
    if model == "c2":
        return _league_rows_c2(league, lag)
    from oddsmarkets.basketball.research import improve as I
    p = I.add_probs(I.candidates(league), league)
    test = p[p.season.isin(X.TEST)].copy()
    test = test[test.open_sp_h.notna() | test.open_ml_h.notna() | test.open_tot.notna()]
    sig_m, sig_t = float(test.sig_m.iloc[0]), float(test.sig_t.iloc[0])
    for c in ("inf_mu", "inf_sd", "inf_tot", "inf_tsd"):
        if c not in test:
            raise RuntimeError(f"missing {c}")
    test["inf_mu"] = test["inf_mu"].fillna(test["mu1"])
    test["inf_sd"] = test["inf_sd"].fillna(test["sd1"])
    test["inf_tot"] = test["inf_tot"].fillna(test["tp_mu"])
    test["inf_tsd"] = test["inf_tsd"].fillna(test["tp_sd"])
    s2 = M.selections(test, "inf_mu", "inf_sd", "inf_tot", "inf_tsd", sig_m, sig_t)
    raw = M.selections(test, "m0_mu", "m0_sd", "tp_mu", "tp_sd", sig_m, sig_t)
    key = ["event_id", "market", "selection"]
    s2 = s2.merge(raw[key + ["model_p"]].rename(columns={"model_p": "model_p_raw"}), on=key, how="left")
    s2["price_src"] = s2["price_src_book"].map({"espn_espnbet": "espn_espnbet_open", "espn_dk": "espn_dk_open"})
    s2["max_stake_hint"] = np.nan
    from scipy.stats import norm
    t = test.copy()
    t["p_inf"] = norm.cdf(t["inf_mu"] / t["inf_sd"])
    t["p_raw"] = norm.cdf(t["m0_mu"] / t["m0_sd"])
    t["day"] = pd.to_datetime(t["day"]).dt.date
    k = K.load(league, t, _abbr(league, t.season.unique()))
    ks = K.selections(k, t, "p_inf") if not k.empty else pd.DataFrame()
    if not ks.empty:
        kr = K.selections(k, t, "p_raw")
        ks = ks.merge(kr[["event_id", "selection", "model_p"]].rename(columns={"model_p": "model_p_raw"}),
                      on=["event_id", "selection"], how="left")
    return _finish(pd.concat([s2, ks], ignore_index=True, sort=False)), k


def _league_rows_c2(league: str, lag: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = X.run_league(league, lag)
    test = r["test"].copy()
    sig_m, sig_t = r["result"]["sig_m"], r["result"]["sig_t"]
    test["sig_m"], test["sig_t"] = sig_m, sig_t
    s2 = M.selections(test, "c2_mu", "sig_m", "c2_tot", "sig_t", sig_m, sig_t)
    raw = M.selections(test, "mu1", "sd1", "mut", "sdt", sig_m, sig_t)
    key = ["event_id", "market", "selection"]
    s2 = s2.merge(raw[key + ["model_p"]].rename(columns={"model_p": "model_p_raw"}), on=key, how="left")
    s2["price_src"] = s2["price_src_book"].map({"espn_espnbet": "espn_espnbet_open", "espn_dk": "espn_dk_open"})
    s2["max_stake_hint"] = np.nan
    from scipy.stats import norm
    t = test.copy()
    t["p_c2"] = norm.cdf(t["c2_mu"] / sig_m)
    t["p_raw"] = norm.cdf(t["mu1"] / t["sd1"])
    k = K.load(league, t, _abbr(league, t.season.unique()))
    ks = K.selections(k, t, "p_c2") if not k.empty else pd.DataFrame()
    if not ks.empty:
        kr = K.selections(k, t, "p_raw")
        ks = ks.merge(kr[["event_id", "selection", "model_p"]].rename(columns={"model_p": "model_p_raw"}),
                      on=["event_id", "selection"], how="left")
    return _finish(pd.concat([s2, ks], ignore_index=True, sort=False)), k


def write(leagues=("nba", "wnba"), model: str = "informed") -> Path:
    frames = []
    for lg in leagues:
        rows, k = league_rows(lg, model=model)
        frames.append(rows)
        logger.info("%s: %d selections (%d Kalshi games)", lg, len(rows), len(k))
    df = pd.concat(frames, ignore_index=True)
    df["line"] = df["line"].astype(float)
    df["line_close"] = pd.to_numeric(df["line_close"], errors="coerce")
    df["max_stake_hint"] = df["max_stake_hint"].astype(float)
    p = X.OUT / "basketball.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.drop(columns=[c for c in ("day",) if c in df]).to_parquet(p, index=False)
    print(f"wrote {p}: {len(df)} rows", flush=True)
    return p
