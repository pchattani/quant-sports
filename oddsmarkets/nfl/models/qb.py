"""
QB composite: EPA per dropback, CPOE (ours), sack avoidance and turnover-worthy plays, stabilisation-aware
and with priors, combined into a forecast of next season's EPA per dropback.

Components per QB-season (dropbacks include sacks and scrambles):
* epa_db: nflverse EPA per dropback;
* cpoe: our CPOE per aimed pass (completion.py);
* sack_rate: sacks per dropback (lower is better);
* twp_rate: FTN interception-worthy throws per attempt (2022->); before 2022 the interception rate,
  which is much noisier (stabilise.py: k for int_rate is about twice that for twp_rate).

Each component is regressed to a prior with its stabilisation constant k (stabilise.shrink_k): posterior =
(n x + k prior) / (n + k). The prior is the QB's own history (previous seasons, weight PRIOR_DECAY^lag x
volume), itself shrunk to the league mean with k, so a veteran's slow start moves him less than a
rookie's.

Composite: the regression of next season's EPA per dropback (QBs with >= MIN_DB dropbacks both seasons)
on this season's z-scored posteriors (weights `w`, fitted on every season pair available, weighted by
the smaller of the two volumes; DEFAULT_W when there are too few pairs). Composite = predicted next-season
EPA/dropback; `pct` = its percentile among the season's qualified QBs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io, completion, stabilise

MODEL_VERSION = "qb-1"
COMPONENTS = ["epa_db", "cpoe", "sack_rate", "twp_rate"]
K_METRIC = {"epa_db": "qb_epa_db", "cpoe": "cpoe", "sack_rate": "sack_rate", "twp_rate": "twp_rate"}
UNIT = {"epa_db": "db", "cpoe": "att", "sack_rate": "db", "twp_rate": "att"}
DEFAULT_W = {"epa_db": 0.09, "cpoe": 0.03, "sack_rate": -0.015, "twp_rate": -0.02}
PRIOR_DECAY = 0.6
MIN_DB = 200
MIN_PAIRS = 25


def season_components(season: int, d: pd.DataFrame | None = None) -> pd.DataFrame:
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return pd.DataFrame()
    db = (pd.to_numeric(d["qb_dropback"], errors="coerce").fillna(0) == 1) & d["passer_player_id"].notna()
    tp = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) == 1 if "two_point_attempt" in d else False
    x = d[db & ~tp]
    g = x.groupby("passer_player_id").agg(
        name=("passer_player_name", "last") if "passer_player_name" in x else ("posteam", "last"),
        team=("posteam", "last"), db=("qb_dropback", "size"),
        epa_sum=("epa", lambda s: float(pd.to_numeric(s, errors="coerce").sum())),
        sacks=("sack", lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0).sum()))).reset_index()
    g = g.rename(columns={"passer_player_id": "qb"})
    pa = x[(pd.to_numeric(x["pass_attempt"], errors="coerce").fillna(0) == 1) & (pd.to_numeric(x["sack"], errors="coerce").fillna(0) == 0)]
    att = pa.groupby("passer_player_id").agg(att=("pass_attempt", "size"),
                                             ints=("interception", lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
                                             twp=("f_int_worthy", lambda s: float(pd.to_numeric(s, errors="coerce").sum()) if pd.to_numeric(s, errors="coerce").notna().any() else np.nan),
                                             twp_n=("f_int_worthy", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())))
    g = g.merge(att.reset_index().rename(columns={"passer_player_id": "qb"}), on="qb", how="left")
    c = completion.season_rows(season, d)
    if len(c) and c["cp_ours"].notna().any():
        cc = c.assign(r=c["y"] - c["cp_ours"]).groupby("passer").agg(cp_att=("r", "size"), cpoe_sum=("r", "sum")).reset_index()
        g = g.merge(cc.rename(columns={"passer": "qb"}), on="qb", how="left")
    else:
        g["cp_att"], g["cpoe_sum"] = np.nan, np.nan
    g["season"] = int(season)
    g["epa_db"] = g["epa_sum"] / g["db"]
    g["sack_rate"] = g["sacks"] / g["db"]
    g["cpoe"] = g["cpoe_sum"] / g["cp_att"]
    use_twp = (g["twp_n"].fillna(0) >= 0.8 * g["att"].fillna(0)) & (g["twp_n"].fillna(0) > 0)
    g["twp_rate"] = np.where(use_twp, g["twp"] / g["twp_n"].clip(lower=1), g["ints"] / g["att"].clip(lower=1))
    g["twp_source"] = np.where(use_twp, "ftn", "int")
    g["n_db"] = g["db"].astype(float)
    g["n_att"] = g["att"].fillna(0).astype(float)
    g["n_cp"] = g["cp_att"].fillna(0).astype(float)
    return g


def _n(row_or_df, comp):
    return {"epa_db": "n_db", "sack_rate": "n_db", "cpoe": "n_cp", "twp_rate": "n_att"}[comp]


def posteriors(history: pd.DataFrame, season: int) -> pd.DataFrame:
    """Posterior components for `season` from a history of season_components rows (seasons <= season)."""
    h = history[history["season"] <= season]
    cur = h[h["season"] == season].copy()
    if not len(cur):
        return cur
    prev = h[h["season"] < season]
    for comp in COMPONENTS:
        ncol = _n(None, comp)
        k = stabilise.shrink_k(K_METRIC[comp])
        lg_n = cur[ncol].sum()
        league = float(np.nansum(cur[comp] * cur[ncol]) / lg_n) if lg_n > 0 else 0.0
        if len(prev):
            w = PRIOR_DECAY ** (season - prev["season"]) * prev[ncol]
            pv = prev.assign(_w=w, _wx=w * prev[comp]).groupby("qb").agg(_w=("_w", "sum"), _wx=("_wx", "sum"))
            prior = (pv["_wx"].fillna(0) + k * league) / (pv["_w"].fillna(0) + k)
            cur["prior_" + comp] = cur["qb"].map(prior).fillna(league)
        else:
            cur["prior_" + comp] = league
        x = cur[comp].fillna(league)
        n = cur[ncol].fillna(0)
        cur["post_" + comp] = (n * x + k * cur["prior_" + comp]) / (n + k)
        cur["league_" + comp] = league
    return cur


def fit_weights(history: pd.DataFrame) -> dict:
    """Weights of z-scored posteriors in a regression for next season's EPA/dropback."""
    rows = []
    for s in sorted(history["season"].unique()):
        nx = history[(history["season"] == s + 1) & (history["n_db"] >= MIN_DB)]
        if not len(nx):
            continue
        p = posteriors(history, s)
        p = p[p["n_db"] >= MIN_DB]
        j = p.merge(nx[["qb", "epa_db", "n_db"]].rename(columns={"epa_db": "next", "n_db": "n_next"}), on="qb")
        if len(j):
            for c in COMPONENTS:
                j["z_" + c] = _io.zscore(j["post_" + c])
            rows.append(j)
    if not rows:
        return {"w": DEFAULT_W, "pairs": 0, "fitted": False}
    J = pd.concat(rows, ignore_index=True)
    if len(J) < MIN_PAIRS:
        return {"w": DEFAULT_W, "pairs": int(len(J)), "fitted": False}
    X = np.column_stack([np.ones(len(J))] + [J["z_" + c].to_numpy(float) for c in COMPONENTS])
    w = np.minimum(J["n_db"], J["n_next"]).to_numpy(float)
    W = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * W[:, None], J["next"].to_numpy(float) * W, rcond=None)
    pred = X @ beta
    r = _io.pearson(pred, J["next"])
    r_raw = _io.pearson(J["epa_db"], J["next"])
    return {"w": {c: float(b) for c, b in zip(COMPONENTS, beta[1:])}, "intercept": float(beta[0]), "pairs": int(len(J)),
            "fitted": True, "r_composite_next": r, "r_raw_epa_next": r_raw}


def composite(history: pd.DataFrame, season: int, weights: dict) -> pd.DataFrame:
    p = posteriors(history, season)
    if not len(p):
        return p
    q = p["n_db"] >= MIN_DB
    w = weights.get("w") or DEFAULT_W
    score = np.full(len(p), weights.get("intercept", 0.0))
    for c in COMPONENTS:
        mu = p.loc[q, "post_" + c].mean() if q.any() else p["post_" + c].mean()
        sd = p.loc[q, "post_" + c].std() if q.sum() > 2 else p["post_" + c].std()
        p["z_" + c] = _io.zscore(p["post_" + c], mu, sd)
        score = score + w.get(c, 0.0) * p["z_" + c].to_numpy(float)
    p["composite"] = score
    ref = np.sort(p.loc[q, "composite"].to_numpy(float)) if q.any() else np.sort(score)
    p["pct"] = 100.0 * np.searchsorted(ref, p["composite"].to_numpy(float), side="right") / max(len(ref), 1)
    p["qualified"] = q
    return p.sort_values("composite", ascending=False).reset_index(drop=True)


def history(seasons) -> pd.DataFrame:
    parts = []
    for s in seasons:
        r = _io.cached("qb_comp", str(int(s)), _io.file_key(*_io.source_files(s), MODEL_VERSION, (completion.current_fit() or {}).get("key")),
                       lambda s=s: season_components(s).to_dict("records"))
        if r:
            parts.append(pd.DataFrame(r))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def fit(seasons=None, use_cache: bool = True) -> dict:
    seasons = _io.season_range(seasons)
    h = history(seasons)
    w = fit_weights(h) if len(h) else {"w": DEFAULT_W, "pairs": 0, "fitted": False}
    out = {"ok": True, "version": MODEL_VERSION, "seasons": seasons, **w}
    _io.store_fit("qb", out)
    return out


def current_fit() -> dict:
    return _io.get_fit("qb", MODEL_VERSION) or {"w": DEFAULT_W, "fitted": False}


def for_season(season: int) -> list[dict]:
    seasons = [s for s in _io.season_range() if s <= season][-6:]
    h = history(seasons)
    if not len(h):
        return []
    c = composite(h, season, current_fit())
    keep = ["qb", "name", "team", "season", "n_db", "n_att", "epa_db", "cpoe", "sack_rate", "twp_rate", "twp_source",
            *[f"post_{x}" for x in COMPONENTS], *[f"z_{x}" for x in COMPONENTS], "composite", "pct", "qualified"]
    return _io.clean(c[[k for k in keep if k in c]].to_dict("records"))


def export_fits(seasons=None) -> dict:
    f = fit(seasons)
    _io.write_fit("qb", f)
    return f
