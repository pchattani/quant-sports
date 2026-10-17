"""
data/edge/nfl.parquet (docs/research/EDGE_PROTOCOL.md section 3): one row per selection per decision.

Decisions written
    nflverse_close   2006 -> : the close (kickoff). model_p = the promoted close model (raw, not shrunk: the portfolio
                     layer estimates its own haircut walk-forward). fair_p_close = fair_p_decision (the same price).
    espn_open        2023 -> : ESPN's opener (ESPN BET / DraftKings). model_p = the move model (blend.py) on the
                     conservative open rows (ratings through the week BEFORE the previous one, QB as of then), so it
                     is valid even for look-ahead openers. fair_p_close at the opener's line through market.LineMap.
    kalshi_*         prediction-market decisions (edge/kalshi.py), when the Kalshi history is on disk.
    future_wins      Kalshi win-total ladders priced by the preseason season simulation (edge/futures.py).
                     start_time = the season's last regular-season kickoff, settle_time = that + 24 h (futures.py);
                     settle_time is NaN on every other row (the portfolio layer's default applies).

decision_time: the close = kickoff; the opener = the information cutoff (00:00 UTC of the first game day of the
week before the game's week; ESPN does not timestamp openers). Probabilities of spreads / totals are conditional on no
push (p_push given); outcome 0.5 = push. devig = multiplicative. slate = season-week-decision; corr_group = game id
(every market of one game is correlated).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.edge import blend as BL
from oddsmarkets.nfl.edge import evaluate as EV
from oddsmarkets.nfl.edge import market as MK
from oddsmarkets.nfl.edge import prices as PR

COLS = ["event_id", "sport", "league", "season", "start_time", "market", "selection", "line", "decision_time", "model_p",
        "price_dec", "price_src", "fair_p_decision", "price_close", "fair_p_close", "outcome", "slate", "corr_group",
        "max_stake_hint", "p_push", "devig", "decision", "week", "line_close", "settle_time", "quality_ok",
        "quality_note"]


def _finish(S: pd.DataFrame, decision_time, slate_tag: str) -> pd.DataFrame:
    S = S.copy()
    S["sport"], S["league"] = "nfl", "NFL"
    S["decision_time"] = decision_time
    S["slate"] = S["season"].astype(str) + "-w" + S["week"].astype(int).astype(str).str.zfill(2) + "-" + slate_tag
    S["corr_group"] = S["corr_group"].fillna(S["event_id"]) if "corr_group" in S else S["event_id"]
    if "max_stake_hint" not in S:
        S["max_stake_hint"] = np.nan
    S["devig"] = "multiplicative"
    for c in COLS:
        if c not in S:
            S[c] = np.nan
    return S[COLS]


def _close_prices(S: pd.DataFrame, P: pd.DataFrame, pre: str) -> pd.DataFrame:
    """price_close / line_close of the same selection at the close (`pre` prefix columns of P)."""
    g = P.set_index("game_id")
    idx = S["event_id"]
    pc = np.full(len(S), np.nan)
    lc = np.full(len(S), np.nan)
    for mk, sel, col, lcol, sign in (("moneyline", "home", "ml_h", None, 1), ("moneyline", "away", "ml_a", None, 1),
                                     ("spread", "home", "sp_h", "spread_home", 1), ("spread", "away", "sp_a", "spread_home", -1),
                                     ("total", "over", "ov", "total", 1), ("total", "under", "un", "total", 1)):
        m = ((S["market"] == mk) & (S["selection"] == sel)).to_numpy()
        pc[m] = g[f"{pre}_{col}"].reindex(idx[m]).to_numpy(float)
        if lcol:
            lc[m] = sign * g[f"{pre}_{lcol}"].reindex(idx[m]).to_numpy(float)
    S = S.copy()
    S["price_close"], S["line_close"] = pc, lc
    return S


def close_rows(P: pd.DataFrame, lm: MK.LineMap) -> pd.DataFrame:
    P = P[P["season"] >= 2006]
    S = EV.selections(P, "nfv", "nfv", lm, "nflverse_close", "close")
    S = _close_prices(S, P, "nfv")
    S["fair_p_close"] = S["fair_p_decision"]
    return _finish(S, pd.to_datetime(S["start_time"], utc=True), "close")


def open_rows(P: pd.DataFrame, lm: MK.LineMap, betas: dict, kk: np.ndarray, tk, sigma_m: float = 13.2,
              sigma_t: float = 13.5) -> pd.DataFrame:
    """Move-model probabilities at the ESPN opener. betas: {season: (b_spread, b_total)} learnt on earlier seasons."""
    o = P[P["eo_spread_home"].notna() | P["eo_total"].notna() | P["eo_ml_h"].notna()].copy()
    o.attrs = P.attrs
    b = o["season"].map(lambda s: betas[int(s)][0]).to_numpy(float)
    bt = o["season"].map(lambda s: betas[int(s)][1]).to_numpy(float)
    open_line = -o["eo_spread_home"].to_numpy(float)
    chat = open_line + b * (o["mu"].to_numpy(float) - open_line)
    chat_t = o["eo_total"].to_numpy(float) + bt * (o["mu_t"].to_numpy(float) - o["eo_total"].to_numpy(float))
    ph1, pc1, _ = BL.probs_from_line(chat, sigma_m, kk, o["eo_spread_home"].to_numpy(float))
    ph0, pc0, _ = BL.probs_from_line(open_line, sigma_m, kk, o["eo_spread_home"].to_numpy(float))
    po1, _ = BL.over_from_total(chat_t, sigma_t, tk, o["eo_total"].to_numpy(float))
    po0, _ = BL.over_from_total(o["eo_total"].to_numpy(float), sigma_t, tk, o["eo_total"].to_numpy(float))
    fml, _ = PR.devig2(o["eo_ml_h"], o["eo_ml_a"])
    fsp, _ = PR.devig2(o["eo_sp_h"], o["eo_sp_a"])
    fov, _ = PR.devig2(o["eo_ov"], o["eo_un"])
    o["p_home"] = np.clip(fml + (ph1 - ph0), 0.01, 0.99)
    S = EV.selections(o, "eo", "ec", lm, "espn_open", "open")
    sp_new = pd.Series(np.clip(fsp + (pc1 - pc0), 0.01, 0.99), index=o["game_id"].to_numpy())
    to_new = pd.Series(np.clip(fov + (po1 - po0), 0.01, 0.99), index=o["game_id"].to_numpy())
    m = S["market"] == "spread"
    v = sp_new.reindex(S.loc[m, "event_id"]).to_numpy()
    S.loc[m, "model_p"] = np.where(S.loc[m, "selection"] == "home", v, 1 - v)
    m = S["market"] == "total"
    v = to_new.reindex(S.loc[m, "event_id"]).to_numpy()
    S.loc[m, "model_p"] = np.where(S.loc[m, "selection"] == "over", v, 1 - v)
    S = S[np.isfinite(S["model_p"])]
    S = _close_prices(S, o, "ec")
    # information cutoff: first game day of the previous week (00:00 UTC)
    wk = P.groupby(["season", "week"])["date"].min()
    cut = []
    for s, w in zip(S["season"], S["week"]):
        prev = wk.loc[s][wk.loc[s].index < w]
        cut.append(pd.Timestamp(prev.iloc[-1] if len(prev) else wk.loc[(s, w)] - pd.Timedelta(days=7)).tz_localize("UTC"))
    return _finish(S, pd.DatetimeIndex(cut), "open")


# ── assembly ────────────────────────────────────────────────────────────────

def move_betas(P: pd.DataFrame, mr: pd.DataFrame, mode: str, seasons, qb_s: float = 0.77) -> dict:
    """{season: (b_spread, b_total)} from 2006 to the season before, with the pseudo-open (market ratings)."""
    Q = P.drop(columns=[c for c in P.columns if c.startswith("mr_")]).merge(mr, on="game_id", how="left")
    qadd = qb_s * Q["np_lg"] * (Q["qbv_h"] - Q["qbv_a"])
    pseudo = np.where(mode == "openB", Q["mr_line_b"], Q["mr_line"]) + qadd
    pseudo_t = np.where(mode == "openB", Q["mr_total_b"], Q["mr_total"])
    sea = Q["season"].to_numpy()
    return {int(s): (BL.move_beta(Q["mu"].to_numpy(float), np.asarray(pseudo, float), -Q["nfv_spread_home"].to_numpy(float), sea, s),
                     BL.move_beta(Q["mu_t"].to_numpy(float), np.asarray(pseudo_t, float), Q["nfv_total"].to_numpy(float), sea, s))
            for s in seasons}


def write(exp: str = "mr", out_path=None, extra: list[pd.DataFrame] | None = None) -> pd.DataFrame:
    """Close and open decisions from the saved predictions of experiment `exp` (scripts/nfl_edge.py --save-preds),
    plus any extra decision frames (Kalshi, futures); writes data/edge/nfl.parquet."""
    import pickle
    from pathlib import Path
    from oddsmarkets.nfl.models import _cdata as D
    cache = D.cache_root() / "edge"
    with open(cache / f"preds_{exp}.pkl", "rb") as f:
        d = pickle.load(f)
    preds = {}
    for m, (P, at) in d.items():
        P = pd.DataFrame(P)
        P.attrs = at
        preds[m] = P
    Pc, Pb = preds["close"], preds["openB"]
    s_last = max(Pc.attrs["keys"])
    lm = MK.LineMap(13.2, Pc.attrs["keys"][s_last], 13.5, Pc.attrs["tkeys"].get(s_last))
    mr = pd.read_parquet(cache / "mr_base.parquet")
    betas = move_betas(Pb, mr, "openB", range(2023, 2027))
    parts = [close_rows(Pc, lm), open_rows(Pb, lm, betas, Pb.attrs["keys"][s_last], Pb.attrs["tkeys"].get(s_last))]
    parts += [x for x in (extra or []) if x is not None and len(x)]
    T = pd.concat(parts, ignore_index=True)
    out_path = Path(out_path) if out_path else D.REPO / "data" / "edge" / "nfl.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    T.to_parquet(out_path, index=False)
    return T
