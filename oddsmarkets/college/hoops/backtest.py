"""
Walk-forward backtest of the game model against results and closing lines (calibration.json).

Every finished game is predicted from ratings fitted on games of earlier days only (model.level_state); the
game-model parameters for season S come from seasons < S. Scored on games between two Division I members:

  model     Brier, log loss, accuracy of p_home; MAE / RMSE of the predicted margin
  elo       the Elo baseline (elo.py) on the same games
  close     the closing line (ESPN core odds: `spread_home`, see CONTRACT 1.1) as a margin forecast (-spread), and the
            de-vigged closing moneyline as a probability where present
  vs_close  on games with a closing spread: MAE model v MAE close; ATS hit rate of the model's side against the
            close (pushes and zero-edge games dropped; se = sqrt(p(1-p)/n)); totals MAE v the closing total
  espn      ESPN's matchup predictor where stored
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

EPS = 1e-4
SPREAD_BUCKETS = [(0, 3), (3, 6), (6, 10), (10, 15), (15, 25), (25, 80)]


def prob_scores(p: np.ndarray, y: np.ndarray) -> dict:
    if not len(p):
        return {"n": 0, "brier": None, "logloss": None, "acc": None}
    pc = np.clip(p, EPS, 1 - EPS)
    return {"n": int(len(p)), "brier": round(float(np.mean((pc - y) ** 2)), 5),
            "logloss": round(float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))), 5),
            "acc": round(float(np.mean((pc > 0.5) == (y > 0.5))), 4)}


def margin_scores(pred: np.ndarray, actual: np.ndarray) -> dict:
    if not len(pred):
        return {"mae": None, "rmse": None}
    e = pred - actual
    return {"mae": round(float(np.mean(np.abs(e))), 3), "rmse": round(float(np.sqrt(np.mean(e ** 2))), 3)}


def ats(mu: np.ndarray, spread: np.ndarray, margin: np.ndarray) -> dict:
    edge = mu + spread                    # model margin minus the market's (-spread)
    res = margin + spread                 # home cover margin
    m = (np.abs(edge) > 1e-9) & (np.abs(res) > 1e-9)
    if not m.any():
        return {"ats_hit": None, "ats_n": 0, "ats_se": None}
    hit = np.sign(edge[m]) == np.sign(res[m])
    p = float(hit.mean())
    n = int(m.sum())
    return {"ats_hit": round(p, 4), "ats_n": n, "ats_se": round(math.sqrt(p * (1 - p) / n), 4)}


def calibration_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    out = []
    edges = np.linspace(0, 1, bins + 1)
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= 1))
        if m.any():
            out.append({"lo": round(edges[i], 2), "hi": round(edges[i + 1], 2), "n": int(m.sum()),
                        "p_mean": round(float(p[m].mean()), 4), "y_mean": round(float(y[m].mean()), 4)})
    return out


def rows(state: dict, seasons: list[int] | None = None) -> dict:
    """Concatenated per-game arrays over the seasons (D-I v D-I games only)."""
    ss = seasons or state["seasons"]
    acc: dict[str, list] = {k: [] for k in ("season", "mu", "p", "total_pred", "margin", "total", "spread", "ctotal",
                                             "p_ml", "pred", "elo", "stype", "nprior", "gid", "day", "cblock")}
    for s in ss:
        tab, pr, F = state["tabs"][s], state["preds"][s], state["feats"][s]
        G = tab["g"]
        m = F["both"] & np.isfinite(pr["mu"])
        acc["season"].append(np.full(m.sum(), s))
        acc["mu"].append(pr["mu"][m])
        acc["p"].append(pr["p"][m])
        acc["total_pred"].append(pr["total"][m])
        acc["margin"].append(F["margin"][m])
        acc["total"].append(F["total"][m])
        acc["spread"].append(G["spread"][m])
        acc["ctotal"].append(G["total"][m])
        acc["p_ml"].append(G["p_ml"][m])
        acc["pred"].append(G["pred"][m])
        acc["elo"].append(state["elo"][s]["p_home"][m])
        acc["stype"].append(G["stype"][m])
        acc["nprior"].append(np.minimum(state["walks"][s]["nprior_h"][m], state["walks"][s]["nprior_a"][m]))
        acc["gid"].append(G["gid"][m])
        acc["day"].append(G["day"][m])
        acc["cblock"].append(G["cblock"][m] if "cblock" in G else np.zeros(int(m.sum()), bool))
    return {k: np.concatenate(v) if v else np.zeros(0) for k, v in acc.items()}


def summarize(state: dict, seasons: list[int] | None = None) -> dict:
    """The calibration.json body (without ok/level/updated_at)."""
    r = rows(state, seasons)
    y = (r["margin"] > 0).astype(float)
    model = {**prob_scores(r["p"], y), **margin_scores(r["mu"], r["margin"])}
    elo = prob_scores(r["elo"], y)
    hc = np.isfinite(r["spread"])
    close = {**prob_scores(np.where(np.isfinite(r["p_ml"]), r["p_ml"], np.nan)[hc & np.isfinite(r["p_ml"])],
                           y[hc & np.isfinite(r["p_ml"])]),
             **margin_scores(-r["spread"][hc], r["margin"][hc])}
    ml = np.isfinite(r["p_ml"])
    model_on_ml = prob_scores(r["p"][ml], y[ml])
    tm = hc & np.isfinite(r["ctotal"])
    vs = {"n": int(hc.sum()), "mae_model": margin_scores(r["mu"][hc], r["margin"][hc])["mae"],
          "mae_close": close["mae"], **ats(r["mu"][hc], r["spread"][hc], r["margin"][hc]),
          "total_mae_model": margin_scores(r["total_pred"][tm], r["total"][tm])["mae"],
          "total_mae_close": margin_scores(r["ctotal"][tm], r["total"][tm])["mae"], "total_n": int(tm.sum()),
          "ml_n": int(ml.sum()), "model_on_ml": model_on_ml,
          "rmse_model": margin_scores(r["mu"][hc], r["margin"][hc])["rmse"],
          "rmse_close": margin_scores(-r["spread"][hc], r["margin"][hc])["rmse"]}
    if tm.any():
        e = r["total_pred"][tm] - r["ctotal"][tm]
        res = r["total"][tm] - r["ctotal"][tm]
        mm = (np.abs(e) > 1e-9) & (np.abs(res) > 1e-9)
        if mm.any():
            hit = np.sign(e[mm]) == np.sign(res[mm])
            pp = float(hit.mean())
            vs.update({"ou_hit": round(pp, 4), "ou_n": int(mm.sum()), "ou_se": round(math.sqrt(pp * (1 - pp) / mm.sum()), 4)})
    pm = np.isfinite(r["pred"])
    espn = None
    if pm.sum() >= 30:
        espn = {"espn": prob_scores(r["pred"][pm], y[pm]), "model": prob_scores(r["p"][pm], y[pm])}
    per = []
    for s in sorted(set(r["season"].tolist())):
        m = r["season"] == s
        h = m & hc
        row = {"season": int(s), "n": int(m.sum()), "n_close": int(h.sum()),
               "model": {**prob_scores(r["p"][m], y[m]), **margin_scores(r["mu"][m], r["margin"][m])},
               "elo": prob_scores(r["elo"][m], y[m]),
               "close": margin_scores(-r["spread"][h], r["margin"][h]) if h.any() else None,
               "model_on_close": margin_scores(r["mu"][h], r["margin"][h]) if h.any() else None}
        row.update(ats(r["mu"][h], r["spread"][h], r["margin"][h]) if h.any() else {"ats_hit": None, "ats_n": 0, "ats_se": None})
        t2 = h & np.isfinite(r["ctotal"])
        row["total_mae_model"] = margin_scores(r["total_pred"][t2], r["total"][t2])["mae"] if t2.any() else None
        row["total_mae_close"] = margin_scores(r["ctotal"][t2], r["total"][t2])["mae"] if t2.any() else None
        mlm = m & ml
        row["ml"] = {"n": int(mlm.sum()), "model": prob_scores(r["p"][mlm], y[mlm]),
                     "close": prob_scores(r["p_ml"][mlm], y[mlm])} if mlm.sum() >= 20 else None
        per.append(row)
    by_spread = []
    for lo, hi in SPREAD_BUCKETS:
        m = hc & (np.abs(r["spread"]) >= lo) & (np.abs(r["spread"]) < hi)
        if m.sum() >= 20:
            by_spread.append({"lo": lo, "hi": hi, "n": int(m.sum()),
                              "mae_model": margin_scores(r["mu"][m], r["margin"][m])["mae"],
                              "mae_close": margin_scores(-r["spread"][m], r["margin"][m])["mae"],
                              "ats_hit": ats(r["mu"][m], r["spread"][m], r["margin"][m])["ats_hit"]})
    by_stage = []
    for lo, hi, lab in ((0, 5, "0-4 games played"), (5, 10, "5-9"), (10, 20, "10-19"), (20, 99, "20+")):
        m = (r["nprior"] >= lo) & (r["nprior"] < hi)
        if m.any():
            by_stage.append({"label": lab, "n": int(m.sum()), **prob_scores(r["p"][m], y[m]),
                             **margin_scores(r["mu"][m], r["margin"][m]),
                             "n_close": int((m & hc).sum()),
                             "mae_close": margin_scores(-r["spread"][m & hc], r["margin"][m & hc])["mae"] if (m & hc).any() else None,
                             "mae_model_on_close": margin_scores(r["mu"][m & hc], r["margin"][m & hc])["mae"] if (m & hc).any() else None})
    by_line = []
    for flag, lab in ((True, "explicit closing line (book's close block: ESPN BET 2023-2025, DraftKings 2026)"),
                      (False, "last listed line or median of books (consensus 2013, offshore 2014-2016, US books later)")):
        m = hc & (r["cblock"].astype(bool) == flag)
        if m.sum() >= 20:
            tm2 = m & np.isfinite(r["ctotal"])
            by_line.append({"kind": "close" if flag else "last_or_median", "label": lab, "n": int(m.sum()),
                            "mae_model": margin_scores(r["mu"][m], r["margin"][m])["mae"],
                            "mae_close": margin_scores(-r["spread"][m], r["margin"][m])["mae"],
                            **ats(r["mu"][m], r["spread"][m], r["margin"][m]),
                            "total_mae_model": margin_scores(r["total_pred"][tm2], r["total"][tm2])["mae"] if tm2.any() else None,
                            "total_mae_close": margin_scores(r["ctotal"][tm2], r["total"][tm2])["mae"] if tm2.any() else None})
    by_type = []
    for st_ in ("reg", "conf", "ncaa", "nit", "wbit", "post"):
        m = r["stype"] == st_
        if m.sum() >= 20:
            by_type.append({"stype": st_, "n": int(m.sum()), **prob_scores(r["p"][m], y[m]), **margin_scores(r["mu"][m], r["margin"][m])})
    return {"seasons": sorted(int(s) for s in set(r["season"].tolist())), "n_games": int(len(y)),
            "summary": {"model": model, "elo": elo, "close": close, "vs_close": vs, "espn_predictor": espn},
            "per_season": per, "calibration": calibration_table(r["p"], y), "by_spread": by_spread,
            "by_stage": by_stage, "by_type": by_type, "by_line": by_line}
