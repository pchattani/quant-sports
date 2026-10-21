"""
College fantasy football: PPR / half-PPR / standard points from box scores, projections for the coming week,
and a walk-forward backtest against a naive season-average projection.

Scoring: passing 0.04/yd, 4/TD, -2/INT; rushing and receiving 0.1/yd, 6/TD; receptions 1 (PPR), 0.5 (half),
0 (standard); fumbles lost -2; kickers 3 per FG made, 1 per extra point (no distance bonus: the box has none).

Projection for a player's next game = usage x opponent x game script:
  base   = exponentially weighted mean of his fantasy points this season (half-life 6 games), shrunk toward
           the position mean of regular players with weight 1.5 games;
  opp    = (points the opponent has allowed to the position per game / league mean, shrunk with 10 games) ** 0.5;
  script = (team points implied by the game model / the team's season average points) ** 0.25 (clipped 0.7-1.35).
Naive = his season-to-date average. Range = projection -/+ 1 sd of his game-to-game points (shrunk).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

SCORING = {"ppr": {"rec": 1.0}, "half": {"rec": 0.5}, "std": {"rec": 0.0}}
SCORING_DOC = {"pass_yds": 0.04, "pass_td": 4, "pass_int": -2, "rush_yds": 0.1, "rush_td": 6, "rec_yds": 0.1, "rec_td": 6,
               "rec": {"ppr": 1, "half": 0.5, "std": 0}, "fum_lost": -2, "fgm": 3, "xpm": 1}
FPOS = ("QB", "RB", "WR", "TE", "K")
TUNE = {"hl": 6.0, "prior": 1.5, "k_opp": 10.0, "pow": 0.25, "opp_pow": 0.5}   # tuned on 2025 only (2026 out of sample)
TUNED_ON = (2025,)


def points(df: pd.DataFrame, fmt: str) -> pd.Series:
    rec = SCORING[fmt]["rec"]
    return (0.04 * df["pass_yds"] + 4 * df["pass_td"] - 2 * df["pass_int"] + 0.1 * df["rush_yds"] + 6 * df["rush_td"]
            + rec * df["rec"] + 0.1 * df["rec_yds"] + 6 * df["rec_td"] - 2 * df["fum_lost"] + 3 * df["fgm"] + df["xpm"])


def game_points(box: pd.DataFrame, pos: dict[str, str]) -> pd.DataFrame:
    """Per player-game fantasy points in each format for fantasy positions."""
    if not len(box):
        return pd.DataFrame()
    g = box.copy()
    g["pos"] = g["pid"].map(pos)
    g = g[g["pos"].isin(FPOS)]
    for f in SCORING:
        g[f"fp_{f}"] = points(g, f)
    g["day"] = g["date"].astype(str).str[:10]
    return g.sort_values(["date", "gid"]).reset_index(drop=True)


def _ewm(vals: np.ndarray, hl: float = 3.0) -> float:
    if not len(vals):
        return np.nan
    w = 0.5 ** (np.arange(len(vals))[::-1] / hl)
    return float(np.sum(w * vals) / np.sum(w))


def project_rows(hist: pd.DataFrame, targets: pd.DataFrame, fmt: str, implied: dict | None = None) -> pd.DataFrame:
    """Projections for `targets` (pid, team, opp, pos, gid) from `hist` (earlier player-games of the season).
    `implied`: {(gid, team): implied points} from the game model (optional)."""
    col = f"fp_{fmt}"
    if not len(targets):
        return targets.assign(proj=[], naive=[], sd=[])
    pos_mean = {}
    for p in FPOS:
        x = hist[hist["pos"] == p]
        r = x.groupby("pid")[col].agg(["mean", "size"])
        r = r[r["size"] >= 2]
        pos_mean[p] = float(r["mean"].quantile(0.6)) if len(r) else 5.0
    # opponent allowed per game to each position, v league mean
    allowed = hist.groupby(["opp", "pos", "gid"])[col].sum().reset_index().groupby(["opp", "pos"])[col].agg(["mean", "size"])
    lg = hist.groupby(["pos", "gid", "opp"])[col].sum().groupby("pos").mean().to_dict()
    tp = hist.assign(_pts=6 * (hist["pass_td"] + hist["rush_td"]) + hist["xpm"] + 3 * hist["fgm"])
    team_pts = tp.groupby(["team", "gid"])["_pts"].sum()
    team_avg = team_pts.groupby("team").mean().to_dict() if len(team_pts) else {}
    hist_by = {pid: g[col].to_numpy(float) for pid, g in hist.groupby("pid")}
    out = []
    for r in targets.itertuples(index=False):
        v = hist_by.get(r.pid, np.zeros(0))
        n = len(v)
        pm = pos_mean.get(r.pos, 5.0)
        base = (n * _ewm(v, TUNE["hl"]) + TUNE["prior"] * pm) / (n + TUNE["prior"]) if n else pm
        naive = float(np.mean(v)) if n else pm
        a = allowed.loc[(r.opp, r.pos)] if (r.opp, r.pos) in allowed.index else None
        lm = lg.get(r.pos) or 1.0
        if a is not None and lm > 0:
            k = TUNE["k_opp"]
            opp_f = ((a["size"] * a["mean"] + k * lm) / (a["size"] + k) / lm) ** TUNE["opp_pow"]
        else:
            opp_f = 1.0
        sc = 1.0
        if implied and (r.gid, r.team) in implied and team_avg.get(r.team):
            sc = float(np.clip((max(implied[(r.gid, r.team)], 3.0) / max(team_avg[r.team], 7.0)) ** TUNE["pow"], 0.7, 1.35))
        proj = base * opp_f * sc
        sd = float(np.sqrt((n * (np.var(v) if n > 1 else 0.0) + 3 * (0.6 * pm) ** 2) / (n + 3)))
        out.append({"pid": r.pid, "proj": proj, "naive": naive, "sd": sd, "opp_f": opp_f, "n": n})
    return targets.reset_index(drop=True).join(pd.DataFrame(out).drop(columns=["pid"]))


def backtest(gp_by_season: dict[int, pd.DataFrame], implied_by_season: dict[int, dict] | None = None,
             fmt: str = "ppr", min_prior: int = 2) -> dict:
    """Walk-forward by game day: each player-game (with min_prior earlier games) projected from earlier games."""
    errs, errs_n, rc, rc_n, n = [], [], [], [], 0
    per = []
    for s, gp in sorted(gp_by_season.items()):
        if not len(gp):
            continue
        days = sorted(gp["day"].unique())
        se, sn, cnt = [], [], 0
        for d in days:
            hist = gp[gp["day"] < d]
            tgt = gp[gp["day"] == d]
            if not len(hist):
                continue
            cntp = hist.groupby("pid").size()
            tgt = tgt[tgt["pid"].map(cntp).fillna(0) >= min_prior]
            if not len(tgt):
                continue
            pr = project_rows(hist, tgt[["pid", "team", "opp", "pos", "gid"]], fmt, (implied_by_season or {}).get(s))
            y = tgt[f"fp_{fmt}"].to_numpy(float)
            e = np.abs(y - pr["proj"].to_numpy())
            en = np.abs(y - pr["naive"].to_numpy())
            se.append(e)
            sn.append(en)
            cnt += len(y)
            for p in FPOS:
                m = (tgt["pos"].to_numpy() == p)
                if m.sum() >= 20:
                    rc.append(spearmanr(pr["proj"].to_numpy()[m], y[m]).correlation)
                    rc_n.append(spearmanr(pr["naive"].to_numpy()[m], y[m]).correlation)
        if cnt:
            e, en = np.concatenate(se), np.concatenate(sn)
            errs.append(e)
            errs_n.append(en)
            per.append({"season": int(s), "n": int(cnt), "mae": round(float(e.mean()), 3), "mae_naive": round(float(en.mean()), 3)})
            n += cnt
    if not n:
        return {"n": 0, "mae": None, "mae_naive": None, "rank_corr": None, "rank_corr_naive": None, "per_season": []}
    e, en = np.concatenate(errs), np.concatenate(errs_n)
    return {"n": int(n), "format": fmt, "mae": round(float(e.mean()), 3), "mae_naive": round(float(en.mean()), 3),
            "rank_corr": round(float(np.nanmean(rc)), 4) if rc else None,
            "rank_corr_naive": round(float(np.nanmean(rc_n)), 4) if rc_n else None, "per_season": per,
            "method": f"walk-forward by game day; players with at least {min_prior} earlier games this season; rank "
                      "correlation = mean Spearman within (day, position) groups of 20+ players"}


def tiers(df: pd.DataFrame, col: str = "proj") -> pd.Series:
    rk = df.groupby("pos")[col].rank(ascending=False, method="first")
    return np.ceil(rk / np.where(df["pos"] == "QB", 6, np.where(df["pos"] == "K", 6, 12))).clip(upper=6).astype(int)
