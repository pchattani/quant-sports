"""
The football pipeline and its walk-forward backtest against closing lines.

`pipeline(current)` runs, over every season on disk up to `current`:
  1. the EP model (cross-fitted by season, ep.fit) and per-game team EPA / success (ep.team_game_stats);
  2. chained walk-forward ratings (ratings.run_seasons: every game day refits on games before that day);
  3. the Elo baseline;
  4. the blend (game.fit_blend), refitted before each season on the earlier seasons' walk-forward rows only.
The pregame prediction of every game is therefore out of sample: ratings from games before its day, weights
from earlier seasons, rating hyperparameters tuned once on 2002-2011 (seasons without closing lines).

`calibration(...)` turns the predictions into the calibration.json payload: model v result, v the close
(spread MAE, ATS of the model's side with its standard error, totals), Brier / log loss v the de-vigged moneyline
where the store has both prices, per season, calibration table, by spread bucket, v ESPN's predictor if stored.
"""
from __future__ import annotations

import hashlib
import logging
import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import data, ep, game, ratings

logger = logging.getLogger(__name__)
VERSION = "cfb-bt-5"
# Rating hyperparameters tuned on 2002-2011 margins (walk-forward MAE, coordinate search; no closing lines exist
# before 2012, so every season in the v-close backtest is out of sample for these).
# Re-checked 21 Oct 2026 (one-at-a-time sweeps on 2002-2011 walk-forward margin MAE, points model): non-FBS teams now
# carry their last seen deviation across seasons (rho_fcs 0.9 per season) and share an FCS-conference level (carried
# at 0.95), deviation precision 2 game-equivalents: MAE 12.93 -> 12.66 (games v FCS teams 14.98 -> 13.39); prior
# strength, carry-over, recency, margin cap, new-member prior and home prior stay at their optima (within 0.02).
TUNED = ratings.Params(lam=3.0, rho=0.8, half_life=2000.0, cap=40.0, new_mean=-8.0, lam_fcs=2.0, hfa=2.0,
                       rho_fcs=0.9, rho_fconf=0.95, lam_fconf=2.0, fcs_conf=True)


def team_stats(current: int, seasons: list[int] | None = None, wp_out: dict | None = None) -> tuple[dict, dict]:
    """({season: team_game_stats}, ep fit) for seasons with plays. `wp_out` (optional) is filled with
    {gid: ESPN's home win probability after the game's first play} (ESPN's pregame estimate as carried into its
    win-probability feed; 2016 on)."""
    ps = [s for s in data.plays_seasons() if s <= int(current)]
    all_ps = list(ps)
    if seasons is not None:
        ps = [s for s in ps if s in seasons]
    if not ps:
        return {}, {}
    fitd = ep.fit(current, all_ps)
    out = {}
    for s in ps:
        pl = ep.season_epa(s, fitd)
        if len(pl):
            out[s] = ep.team_game_stats(pl)
            if wp_out is not None and pl["wp_home"].notna().any():
                w = pl[pl["wp_home"].notna()].groupby("gid", sort=False)["wp_home"].first()
                wp_out.update({str(g): float(v) for g, v in w.items() if 0.0 <= v <= 1.0})
    return out, fitd


def pipeline(current: int, seasons: list[int] | None = None, p: ratings.Params = TUNED, use_cache: bool = True) -> dict:
    seasons = sorted(s for s in (seasons or data.seasons_available()) if s <= int(current))
    wp_open: dict = {}
    tstats, fitd = team_stats(current, seasons, wp_open)
    key = hashlib.md5(f"{VERSION}|{ratings.cache_key(seasons, p)}|{fitd.get('key')}|{sorted(tstats)}".encode()).hexdigest()[:16]
    if use_cache:
        c = data.cache_get("pipeline", key)
        if c is not None:
            return c
    runs = ratings.run_seasons(seasons, p, tstats, snapshots=True)
    frames, cmaps, feats = [], [], {}
    for s in seasons:
        if s not in runs:
            continue
        st = data.load_store(s)
        gf = data.games_frame(s, st)
        frames.append(gf)
        cmaps.append((data.conf_of(st), {t: bool(v.get("member")) for t, v in (st.get("teams") or {}).items()}))
        feats[s] = game.features(runs[s].pregame, gf)
    elo = game.elo_run(frames, cmaps)
    preds, blends = [], {}
    for s in sorted(feats):
        prior_rows = pd.concat([feats[x] for x in feats if x < s], ignore_index=True) if any(x < s for x in feats) else None
        b = game.fit_blend(prior_rows)
        blends[s] = b
        f = feats[s]
        if not len(f):
            continue
        pr = game.predict_frame(f, b)
        keep = f[["gid", "season", "date", "day", "week", "stype", "round", "status", "final", "neutral", "conf_game",
                  "home", "away", "hs", "as", "h_member", "a_member", "spread_home", "total", "ml_home", "ml_away",
                  "provider", "predictor", "is_home", "d_rest", "d_pts", "d_epa", "d_sr", "pts_total"]].copy()
        keep = keep.rename(columns={"total": "close_total"})
        preds.append(keep.merge(pr, on="gid", how="left"))
    P = pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()
    if len(P):
        P = P.merge(elo, on="gid", how="left")
        P["espn_wp_open"] = P["gid"].map(wp_open).astype(float)
    out = {"key": key, "seasons": seasons, "current": int(current), "preds": P, "blends": blends,
           "final": {s: r.final for s, r in runs.items()}, "snapshots": {s: r.snapshots for s, r in runs.items()},
           "teams": {s: r.teams for s, r in runs.items()},
           "ep": {k: v for k, v in fitd.items() if k not in ("W", "folds")} if fitd else {},
           "ep_W": fitd.get("W") if fitd else None, "params": p.__dict__}
    data.cache_put("pipeline", key, out)
    return out


# ── metrics ─────────────────────────────────────────────────────────────────

def _pm(y: np.ndarray, p: np.ndarray, margin_pred=None, margin=None) -> dict:
    p = np.clip(p.astype(float), 1e-4, 1 - 1e-4)
    out = {"n": len(y)}
    if not len(y):
        return out
    out["brier"] = round(float(np.mean((p - y) ** 2)), 4)
    out["logloss"] = round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4)
    out["acc"] = round(float(np.mean((p > 0.5) == (y > 0.5))), 4)
    if margin_pred is not None:
        e = margin - margin_pred
        out["mae"] = round(float(np.mean(np.abs(e))), 3)
        out["rmse"] = round(float(np.sqrt(np.mean(e ** 2))), 3)
    return out


def _ats(model_margin: np.ndarray, spread: np.ndarray, margin: np.ndarray) -> dict:
    side = np.sign(model_margin + spread)          # +1 = model takes the home side
    res = np.sign(margin + spread)                  # +1 = home covered
    ok = (side != 0) & (res != 0)
    n = int(ok.sum())
    hit = float(np.mean(side[ok] == res[ok])) if n else None
    se = math.sqrt(hit * (1 - hit) / n) if n else None
    return {"ats_hit": None if hit is None else round(hit, 4), "ats_n": n, "ats_se": None if se is None else round(se, 4),
            "pushes": int(((res == 0) & (side != 0)).sum())}


def close_prob(d: pd.DataFrame, sd: float = 15.5) -> np.ndarray:
    """Market home win probability: the de-vigged moneyline when both prices exist, else the spread through a
    normal with the model's mid-season sd."""
    ml = np.array([data.devig(a, b) if np.isfinite(a) and np.isfinite(b) else np.nan
                   for a, b in zip(d["ml_home"].to_numpy(float), d["ml_away"].to_numpy(float))])
    sp = norm.cdf(-d["spread_home"].to_numpy(float) / sd)
    return np.where(np.isfinite(ml), ml, sp)


def calibration(pipe: dict) -> dict:
    P = pipe["preds"]
    if P is None or not len(P):
        return {"ok": False, "reason": "no games"}
    d = P[P["final"] & (P["h_member"] | P["a_member"]) & np.isfinite(P["margin"])].copy()
    d.loc[d["season"].isin(list(data.UNRELIABLE_LINES)), ["spread_home", "close_total", "ml_home", "ml_away"]] = np.nan
    d["m"] = d["hs"] - d["as"]
    d = d[d["m"] != 0]
    y = (d["m"] > 0).to_numpy(float)
    summ = {"model": _pm(y, d["p_home"].to_numpy(), d["margin"].to_numpy(), d["m"].to_numpy()),
            "elo": _pm(y, d["elo_p_home"].to_numpy(), d["elo_margin"].to_numpy(), d["m"].to_numpy())}
    c = d[np.isfinite(d["spread_home"])].copy()
    cp = close_prob(c, (pipe["blends"].get(pipe["current"]) or {}).get("sd", {}).get("mid", 15.5))
    yc = (c["m"] > 0).to_numpy(float)
    summ["close"] = _pm(yc, cp, -c["spread_home"].to_numpy(), c["m"].to_numpy())
    vs = {"n": len(c),
          "mae_model": round(float(np.mean(np.abs(c["m"] - c["margin"]))), 3) if len(c) else None,
          "mae_close": round(float(np.mean(np.abs(c["m"] + c["spread_home"]))), 3) if len(c) else None,
          "rmse_model": round(float(np.sqrt(np.mean((c["m"] - c["margin"]) ** 2))), 3) if len(c) else None,
          "rmse_close": round(float(np.sqrt(np.mean((c["m"] + c["spread_home"]) ** 2))), 3) if len(c) else None,
          "mean_abs_diff_model_close": round(float(np.mean(np.abs(c["margin"] + c["spread_home"]))), 3) if len(c) else None}
    vs.update(_ats(c["margin"].to_numpy(), c["spread_home"].to_numpy(), c["m"].to_numpy()))
    t = c[np.isfinite(c["close_total"])]
    tot = (t["hs"] + t["as"]).to_numpy(float)
    vs["total_n"] = len(t)
    vs["total_mae_model"] = round(float(np.mean(np.abs(tot - t["total"]))), 3) if len(t) else None
    vs["total_mae_close"] = round(float(np.mean(np.abs(tot - t["close_total"]))), 3) if len(t) else None
    mlm = np.isfinite(c["ml_home"].to_numpy(float)) & np.isfinite(c["ml_away"].to_numpy(float))
    if mlm.any():
        cm = c[mlm]
        pm = np.array([data.devig(a, b) for a, b in zip(cm["ml_home"], cm["ml_away"])], float)
        ym = (cm["m"] > 0).to_numpy(float)
        vs["ml_n"] = int(mlm.sum())
        a, b = _pm(ym, cm["p_home"].to_numpy()), _pm(ym, pm)
        vs["brier_model"], vs["brier_market"] = a["brier"], b["brier"]
        vs["logloss_model"], vs["logloss_market"] = a["logloss"], b["logloss"]
    summ["vs_close"] = vs
    summ["espn_predictor"] = None
    espn = d["predictor"].to_numpy(float)
    src = np.where(np.isfinite(espn), "matchup predictor", "win-probability feed at the opening kickoff")
    if "espn_wp_open" in d:
        espn = np.where(np.isfinite(espn), espn, d["espn_wp_open"].to_numpy(float))
    okp = np.isfinite(espn)
    if okp.any():
        pr = d[okp]
        yp = (pr["m"] > 0).to_numpy(float)
        ep_ = espn[okp]
        block = {**_pm(yp, ep_), "espn": _pm(yp, ep_), "model": _pm(yp, pr["p_home"].to_numpy()),
                 "seasons": [int(pr["season"].min()), int(pr["season"].max())],
                 "source": sorted(set(src[okp].tolist())),
                 "per_season": []}
        mlp = np.array([data.devig(a, b) if np.isfinite(a) and np.isfinite(b) else np.nan
                        for a, b in zip(pr["ml_home"].to_numpy(float), pr["ml_away"].to_numpy(float))])
        mk = np.isfinite(mlp)
        if mk.sum() >= 30:
            block["on_moneyline_games"] = {"n": int(mk.sum()), "espn": _pm(yp[mk], ep_[mk]),
                                           "model": _pm(yp[mk], pr["p_home"].to_numpy()[mk]), "market": _pm(yp[mk], mlp[mk])}
        for s_, g in pr.groupby("season"):
            if len(g) < 30:
                continue
            m_ = okp[d["season"].to_numpy() == s_]
            e_ = espn[d["season"].to_numpy() == s_][m_]
            gy = (g["m"] > 0).to_numpy(float)
            block["per_season"].append({"season": int(s_), "n": len(g), "espn": _pm(gy, e_), "model": _pm(gy, g["p_home"].to_numpy())})
        summ["espn_predictor"] = block
    per = []
    for s, g in d.groupby("season"):
        gy = (g["m"] > 0).to_numpy(float)
        gc = g[np.isfinite(g["spread_home"])]
        row = {"season": int(s), "n": len(g), "n_close": len(gc),
               "model": _pm(gy, g["p_home"].to_numpy(), g["margin"].to_numpy(), g["m"].to_numpy()),
               "elo": _pm(gy, g["elo_p_home"].to_numpy(), g["elo_margin"].to_numpy(), g["m"].to_numpy()),
               "close": None, "model_on_close": None, "ats_hit": None,
               "blend": "full" if (pipe["blends"].get(int(s)) or {}).get("full") else "points"}
        if len(gc):
            gcy = (gc["m"] > 0).to_numpy(float)
            row["close"] = _pm(gcy, close_prob(gc), -gc["spread_home"].to_numpy(), gc["m"].to_numpy())
            row["model_on_close"] = _pm(gcy, gc["p_home"].to_numpy(), gc["margin"].to_numpy(), gc["m"].to_numpy())
            row.update(_ats(gc["margin"].to_numpy(), gc["spread_home"].to_numpy(), gc["m"].to_numpy()))
            ml = np.isfinite(gc["ml_home"].to_numpy(float)) & np.isfinite(gc["ml_away"].to_numpy(float))
            row["ml_n"] = int(ml.sum())
            if ml.sum() >= 30:
                gm = gc[ml]
                pm = np.array([data.devig(a, b) for a, b in zip(gm["ml_home"], gm["ml_away"])], float)
                ym = (gm["m"] > 0).to_numpy(float)
                row["ml_model"] = _pm(ym, gm["p_home"].to_numpy())
                row["ml_market"] = _pm(ym, pm)
        per.append(row)
    cal = []
    edges = np.linspace(0, 1, 11)
    p = d["p_home"].to_numpy()
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.sum():
            cal.append({"lo": round(lo, 2), "hi": round(hi, 2), "n": int(m.sum()), "p_mean": round(float(p[m].mean()), 4),
                        "y_mean": round(float(y[m].mean()), 4)})
    bys = []
    a = np.abs(c["spread_home"].to_numpy(float))
    for lo, hi in ((0, 3), (3, 7), (7, 10), (10, 14), (14, 21), (21, 99)):
        m = (a >= lo) & (a < hi)
        if m.sum():
            g = c[m]
            r = {"lo": lo, "hi": hi, "n": int(m.sum()),
                 "mae_model": round(float(np.mean(np.abs(g["m"] - g["margin"]))), 3),
                 "mae_close": round(float(np.mean(np.abs(g["m"] + g["spread_home"]))), 3)}
            r.update({k: v for k, v in _ats(g["margin"].to_numpy(), g["spread_home"].to_numpy(), g["m"].to_numpy()).items()
                      if k in ("ats_hit", "ats_n", "ats_se")})
            bys.append(r)
    # where the model loses ground to the close: by phase of the season and by opponent level
    wk = np.where(c["stype"].isin(["bowl", "cfp"]), 99, c["week"].fillna(99).to_numpy(float))
    fbs2 = (c["h_member"] & c["a_member"]).to_numpy(bool)
    groups = [("Weeks 1-2", wk <= 2), ("Weeks 3-4", (wk > 2) & (wk <= 4)), ("Weeks 5-8", (wk > 4) & (wk <= 8)),
              ("Week 9 on", (wk > 8) & (wk < 99)), ("Postseason", wk == 99), ("FBS v FBS", fbs2), ("FBS v non-FBS", ~fbs2)]
    by_phase = []
    for label, m in groups:
        if m.sum():
            g = c[m]
            r = {"group": label, "n": int(m.sum()), "mae_model": round(float(np.mean(np.abs(g["m"] - g["margin"]))), 3),
                 "mae_close": round(float(np.mean(np.abs(g["m"] + g["spread_home"]))), 3)}
            r.update({k: v for k, v in _ats(g["margin"].to_numpy(), g["spread_home"].to_numpy(), g["m"].to_numpy()).items()
                      if k in ("ats_hit", "ats_n", "ats_se")})
            by_phase.append(r)
    seasons_close = sorted(int(s) for s in c["season"].unique())
    notes = [
        "Walk-forward: every game is predicted from ratings fitted on games played before its day; blend weights, "
        "totals line and spread of outcomes are refitted before each season on earlier seasons only.",
        "Rating hyperparameters (prior strength, carry-over, recency, margin cap) were tuned once on 2002-2011, "
        "seasons with no closing lines, so the comparison with the close is out of sample.",
        "Closing lines are ESPN's: 'consensus' for 2013, the median of the books ESPN lists for 2014-2022, and "
        "the book's explicit close (ESPN BET, then DraftKings) from 2023; seasons covered here: "
        + (f"{seasons_close[0]}-{seasons_close[-1]}" if seasons_close else "none") + ".",
        "Market win probabilities are the de-vigged moneylines where both prices are stored; otherwise the spread "
        "through a normal (used only for the 'close' Brier score, flagged).",
        "Games involving at least one FBS team; ties and games without a final score excluded.",
        *[f"{k}: {v}." for k, v in sorted(data.UNRELIABLE_LINES.items())],
        "ESPN's matchup predictor is not stored for finished games; the ESPN comparison uses ESPN's home win "
        "probability after the opening kickoff in its win-probability feed (its pregame estimate carried into the "
        "feed), available from 2016.",
    ]
    return {"ok": True, "level": "cfb", "updated_at": data.now_iso(),
            "seasons": sorted(int(s) for s in d["season"].unique()), "n_games": len(d),
            "summary": summ, "per_season": per, "calibration": cal, "by_spread": bys, "by_phase": by_phase, "sim": None, "notes": notes,
            "ep": pipe.get("ep", {}).get("validation"), "blend": pipe["blends"].get(pipe["current"]),
            "params": pipe.get("params")}
