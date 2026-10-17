"""
Stuff model: the expected run value of a pitch from its physical characteristics alone (no location, no
count, no batter), per pitch family, scaled so 100 = the league-average pitch and 10 = one SD of
pitcher-pitch-type quality.

Components (one LightGBM model each, per family: fastball FF/SI/FC; breaking SL/ST/CU/KC/SV; offspeed
CH/FS/FO/SC/KN), trained on competitive, non-bunt pitches:

    p_sw  = P(swing)                   p_wh = P(whiff | swing)       p_fo = P(foul | contact)
    p_cs  = P(called strike | take)    xwc  = E[xwOBA | ball in play]   (Savant's estimated_woba_using_speedangle)

and their combination into expected run value (runs from the batting side; lower is better for the pitcher)

    xRV = p_sw [p_wh rv_wh + (1 - p_wh)(p_fo rv_fo + (1 - p_fo)(a + b xwc))] + (1 - p_sw)[p_cs rv_cs + (1 - p_cs) rv_b]

with rv_wh, rv_fo, rv_cs, rv_b the training seasons' mean delta_run_exp of whiffs, fouls, called strikes and
balls (a count-neutral average), and a + b xwc the least-squares line of in-play delta_run_exp on xwOBA.

Features (FEATURES): velocity, IVB, arm-side HB, spin rate, arm-side spin axis, extension, release height and
arm-side release side, arm angle, VAA adjusted for location height (vaa - slope_family (plate_z - z_ref)),
differentials to the pitcher's primary fastball (velocity, IVB, HB), the measured-v-movement spin-axis gap
(seam-shifted wake), and platoon (same hand) and the pitcher's hand.

Scaling: stuff = 100 + 10 (mu - xRV) / sd, mu the pitch-weighted league mean xRV and sd the SD of
pitcher-pitch-type mean xRV (>= SCALE_MIN pitches) in the last training season, so the league's pitches
average 100.

Training: the seasons before the target season on disk (up to N_TRAIN_SEASONS, e.g. 2021-2024 for 2025),
SAMPLE_PER_SEASON pitches drawn from each season while holding one season at a time. `validate` reports
pitch-level log-loss of each component on a later season against a velocity-only model, and `pitcher_validity`
the year-to-year correlation of pitcher stuff with next season's run value per pitch.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io, physics, prep

MODEL_VERSION = "stuff-1"

FEATURES = ["release_speed", "ivb", "hb_arm", "release_spin_rate", "spin_axis_arm", "release_extension",
            "release_pos_z", "release_side_arm", "arm_angle", "vaa_adj", "d_velo", "d_ivb", "d_hb", "axis_dev",
            "platoon", "throws_l"]
COMPONENTS = {"swing": "binary", "whiff": "binary", "foul": "binary", "called": "binary", "xwc": "regression"}
N_TRAIN_SEASONS = 4
SAMPLE_PER_SEASON = 350_000
SCALE_MIN = 100
LGB_PARAMS = {"num_leaves": 31, "learning_rate": 0.08, "min_data_in_leaf": 300, "lambda_l2": 10.0}
ROUNDS = 300


# ----------------------------------------------------------------------------- data

def usable(df: pd.DataFrame) -> pd.Series:
    return df["competitive"] & ~df["bunt"] & df["family"].notna() & df["release_speed"].notna() & df["ivb"].notna()


def features(df: pd.DataFrame, slopes: dict) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    d = df.copy()
    d["vaa_adj"] = physics.vaa_adjusted(df, slopes)
    for c in FEATURES:
        X[c] = pd.to_numeric(d[c], errors="coerce").astype(np.float32) if c in d else np.float32(np.nan)
    return X


COMP_COL = {"swing": "swing", "whiff": "whiff", "foul": "foul", "called": "called", "xwc": "xwoba_con"}


def _mask(df: pd.DataFrame, comp: str) -> np.ndarray:
    """Rows on which a component is defined (swing: all; whiff: swings; foul: contact; called: takes;
    xwc: balls in play with an xwOBA)."""
    if comp == "swing":
        return np.ones(len(df), bool)
    if comp == "whiff":
        return df["swing"].to_numpy(bool)
    if comp == "foul":
        return df["contact"].to_numpy(bool)
    if comp == "called":
        return df["take"].to_numpy(bool)
    return (df["inplay"] & df["xwoba_con"].notna()).to_numpy(bool)


def run_values(df: pd.DataFrame) -> dict:
    rv = df["rv"].astype(float)
    out = {}
    for k, col in (("whiff", "whiff"), ("foul", "foul"), ("called", "called"), ("ball", "ball")):
        m = df[col] & rv.notna()
        out[k] = float(rv[m].mean()) if m.any() else 0.0
    m = df["inplay"] & df["xwoba_con"].notna() & rv.notna()
    if m.sum() > 50:
        x, y = df.loc[m, "xwoba_con"].to_numpy(float), rv[m].to_numpy(float)
        xc = x - x.mean()
        b = float((xc * (y - y.mean())).sum() / max((xc ** 2).sum(), 1e-9))
        out["inplay_a"], out["inplay_b"] = float(y.mean() - b * x.mean()), b
    else:
        out["inplay_a"], out["inplay_b"] = -0.25, 0.8
    return out


def combine(p: dict[str, np.ndarray], rv: dict) -> np.ndarray:
    inplay = rv["inplay_a"] + rv["inplay_b"] * p["xwc"]
    contact = p["foul"] * rv["foul"] + (1 - p["foul"]) * inplay
    swing = p["whiff"] * rv["whiff"] + (1 - p["whiff"]) * contact
    take = p["called"] * rv["called"] + (1 - p["called"]) * rv["ball"]
    return p["swing"] * swing + (1 - p["swing"]) * take


# ----------------------------------------------------------------------------- fit / predict

def train_seasons(level: str, season: int, n: int = N_TRAIN_SEASONS) -> list[int]:
    on = [s for s in _io.seasons_on_disk(level) if s < season]
    return on[-n:]


def fit(level: str, seasons: list[int], frames: dict | None = None, n_per_season: int = SAMPLE_PER_SEASON,
        baseline: bool = True, log=None) -> dict:
    """Fit the stuff components on `seasons` (sampled, one season held at a time). `frames` maps season ->
    enriched frame (tests). Returns the JSON-safe model dict."""
    t0 = time.time()
    tr = prep.sample_seasons(level, seasons, n_per_season, filt=usable, frames=frames)
    if len(tr) < 500:
        return {"ok": False, "reason": f"only {len(tr)} training pitches"}
    slopes = physics.vaa_slope(tr)
    X = features(tr, slopes)
    rv = run_values(tr)
    rng = np.random.default_rng(5)
    is_val = rng.random(len(tr)) < 0.1
    fams: dict[str, Any] = {}
    imps: dict[str, Any] = {}
    for fam in _io.FAMILIES:
        fm = (tr["family"] == fam).to_numpy()
        fams[fam], imps[fam] = {}, {}
        for comp, kind in COMPONENTS.items():
            mm = fm & _mask(tr, comp)
            yy = tr.loc[mm, COMP_COL[comp]].to_numpy(float)
            if mm.sum() < 200:
                fams[fam][comp] = {"const": float(np.nanmean(yy)) if len(yy) else (0.3 if kind == "binary" else 0.37)}
                continue
            obj = "binary" if kind == "binary" else "regression"
            vm = is_val[mm]
            Xf = X[mm]
            bst, info = _io.lgb_train(Xf[~vm], yy[~vm], obj, LGB_PARAMS, Xf[vm], yy[vm], rounds=ROUNDS)
            ent = {"model": _io.booster_dump(bst), **info, "n": int(mm.sum()), "mean": float(np.mean(yy))}
            if baseline and kind == "binary":
                bb, binfo = _io.lgb_train(Xf.loc[~vm, ["release_speed"]], yy[~vm], obj,
                                          {"num_leaves": 7, "min_data_in_leaf": 500}, Xf.loc[vm, ["release_speed"]], yy[vm],
                                          rounds=150)
                ent["velo_only"] = _io.booster_dump(bb)
            fams[fam][comp] = ent
            imps[fam][comp] = _io.importances(ent["model"], FEATURES)
            if log:
                log(f"stuff {fam}/{comp}: n={mm.sum()} iters={info['best_iter']} {info.get('val_metric')}")
    model = {"ok": True, "version": MODEL_VERSION, "level": level, "seasons": list(seasons), "features": FEATURES,
             "vaa_slopes": slopes, "rv": rv, "families": fams, "importance": imps, "n_train": int(len(tr))}
    del tr, X
    # scaling on the last training season, scored in full
    last = seasons[-1]
    df = frames[last] if frames is not None and last in frames else prep.prepared(level, last)
    df = df[usable(df)]
    sc = score(df, model, scaled=False)
    model["scale"] = scaling(sc)
    model["fit_secs"] = round(time.time() - t0, 1)
    return model


def scaling(sc: pd.DataFrame, col: str = "stuff_xrv", min_n: int = SCALE_MIN) -> dict:
    x = sc[col].astype(float)
    mu = float(x.mean())
    g = sc.groupby(["pitcher", "pitch_type"], observed=True)[col].agg(["mean", "size"])
    g = g[g["size"] >= min_n]
    sd_pt = float(g["mean"].std()) if len(g) > 5 else float(x.std())
    return {"mu": mu, "sd_pitch": float(x.std()), "sd_pt": sd_pt, "n_groups": int(len(g))}


def predict_components(df: pd.DataFrame, model: dict, velo_only: bool = False) -> dict[str, np.ndarray]:
    X = features(df, model["vaa_slopes"])
    fam = df["family"].to_numpy()
    out = {c: np.full(len(df), np.nan) for c in COMPONENTS}
    for f, comps in model["families"].items():
        m = fam == f
        if not m.any():
            continue
        for comp, ent in comps.items():
            if "const" in ent:
                out[comp][m] = ent["const"]
            elif velo_only and ent.get("velo_only"):
                out[comp][m] = _io.lgb_predict(ent["velo_only"], X.loc[m, ["release_speed"]])
            elif velo_only:
                out[comp][m] = ent.get("mean", np.nan)
            else:
                out[comp][m] = _io.lgb_predict(ent["model"], X[m])
    return out


def score(df: pd.DataFrame, model: dict, scaled: bool = True) -> pd.DataFrame:
    """Per pitch: the components (p_swing, p_whiff, p_foul, p_called, xwc), stuff_xrv and the stuff score."""
    keep = [c for c in ("game_pk", "game_date", "at_bat_number", "pitch_number", "pitcher", "batter", "pitch_type",
                        "family", "p_throws", "stand", "release_speed", "ivb", "hb_arm", "release_spin_rate",
                        "release_extension", "vaa", "rv", "rv_dn", "swing", "whiff", "called", "take", "inplay",
                        "xwoba_con") if c in df]
    out = df[keep].copy()
    p = predict_components(df, model)
    for c, v in p.items():
        out[f"p_{c}"] = v.astype(np.float32)
    out["stuff_xrv"] = combine(p, model["rv"]).astype(np.float32)
    if scaled and model.get("scale"):
        s = model["scale"]
        out["stuff"] = _io.scale_100(out["stuff_xrv"], s["mu"], s["sd_pt"]).astype(np.float32)
    return out


def model_for(level: str, season: int, use_cache: bool = True, log=None) -> dict:
    """The stuff model for scoring `season`: fitted on the seasons before it on disk (cached); the committed
    fit when no earlier season is on disk (CI); an in-sample fit on `season` as the last resort."""
    seasons = train_seasons(level, season)
    if not seasons:
        m = _io.load_fitted(f"stuff_{level}", MODEL_VERSION)
        if m:
            return m
        seasons = [season] if _io.pitch_path(level, season).exists() else []
    if not seasons:
        return {"ok": False, "reason": "no pitch data and no committed fit"}
    key = _io.file_key(MODEL_VERSION, *[_io.pitch_path(level, s) for s in seasons])
    return _io.cached("stuff", f"model_{level}_{'-'.join(map(str, seasons))}", key,
                      lambda: fit(level, seasons, log=log), use_cache, gz=True)


# ----------------------------------------------------------------------------- validation

def validate(df: pd.DataFrame, model: dict) -> dict:
    """Pitch-level out-of-sample check on an enriched season: per family and component, log-loss (binary) or
    RMSE (xwOBAcon) of the model against the velocity-only baseline and the constant; plus the correlation of
    stuff_xrv with realized rv_dn."""
    df = df[usable(df)]
    p = predict_components(df, model)
    pv = predict_components(df, model, velo_only=True)
    out: dict[str, Any] = {"n": int(len(df)), "families": {}}
    for f in _io.FAMILIES:
        fm = (df["family"] == f).to_numpy()
        res = {}
        for comp, kind in COMPONENTS.items():
            mm = fm & _mask(df, comp)
            if mm.sum() < 50:
                continue
            y = df.loc[mm, COMP_COL[comp]].to_numpy(float)
            ent = model["families"].get(f, {}).get(comp, {})
            if kind == "binary":
                base = np.full(mm.sum(), ent.get("mean", y.mean()))
                res[comp] = {"n": int(mm.sum()), "logloss": _io.log_loss(y, p[comp][mm]),
                             "logloss_velo": _io.log_loss(y, pv[comp][mm]), "logloss_const": _io.log_loss(y, base)}
            else:
                res[comp] = {"n": int(mm.sum()), "rmse": float(np.sqrt(np.mean((y - p[comp][mm]) ** 2))),
                             "rmse_const": float(np.sqrt(np.mean((y - ent.get("mean", y.mean())) ** 2)))}
        out["families"][f] = res
    x = combine(p, model["rv"])
    out["corr_xrv_rv_dn"] = float(np.corrcoef(x, df["rv_dn"].astype(float).fillna(0))[0, 1])
    return out


def pitcher_validity(prev: pd.DataFrame, nxt: pd.DataFrame, min_pitches: int = 500) -> dict:
    """Year-to-year: pitcher-level correlation of prev-season stuff (scored frame with `stuff`, `rv`, `rv_dn`)
    with next season's run value per pitch (pitcher's side: -rv), against prev-season RV/pitch as predictor."""
    a = prev.groupby("pitcher").agg(n=("stuff", "size"), stuff=("stuff", "mean"), rv=("rv", "mean"), rv_dn=("rv_dn", "mean"))
    b = nxt.groupby("pitcher").agg(n2=("rv", "size"), rv2=("rv", "mean"), rv_dn2=("rv_dn", "mean"))
    j = a.join(b, how="inner")
    j = j[(j["n"] >= min_pitches) & (j["n2"] >= min_pitches)]
    if len(j) < 10:
        return {"n": int(len(j))}
    c = lambda x, y: float(np.corrcoef(x, y)[0, 1])  # noqa: E731
    return {"n": int(len(j)), "min_pitches": min_pitches,
            "stuff_v_next_rv": c(j["stuff"], -j["rv2"]), "stuff_v_next_rv_dn": c(j["stuff"], -j["rv_dn2"]),
            "rv_v_next_rv": c(-j["rv"], -j["rv2"]), "rv_dn_v_next_rv_dn": c(-j["rv_dn"], -j["rv_dn2"])}


# ----------------------------------------------------------------------------- season tables

def aggregate(sc: pd.DataFrame, min_n: int = 1) -> dict:
    """Per pitcher x pitch type and per pitcher: usage and shape, stuff, xRV per 100, component rates v actual."""
    sc = sc.copy()
    sc["pitcher"] = sc["pitcher"].astype("int64")
    agg = dict(n=("stuff", "size"), stuff=("stuff", "mean"), xrv100=("stuff_xrv", "mean"), velo=("release_speed", "mean"),
               ivb=("ivb", "mean"), hb=("hb_arm", "mean"), spin=("release_spin_rate", "mean"),
               ext=("release_extension", "mean"), vaa=("vaa", "mean"), p_whiff=("p_whiff", "mean"),
               p_swing=("p_swing", "mean"), rv=("rv", "mean"))
    g = sc.groupby(["pitcher", "pitch_type"], observed=True).agg(**agg).reset_index()
    sw = sc[sc["swing"]].groupby(["pitcher", "pitch_type"], observed=True)["whiff"].agg(["mean", "size"])
    g = g.join(sw.rename(columns={"mean": "whiff", "size": "swings"}), on=["pitcher", "pitch_type"])
    tot = sc.groupby("pitcher").size()
    g["usage"] = g["n"] / g["pitcher"].map(tot)
    g["xrv100"] *= 100
    g["rv100"] = g["rv"] * 100
    g = g[g["n"] >= min_n]
    per = sc.groupby("pitcher").agg(n=("stuff", "size"), stuff=("stuff", "mean"), xrv100=("stuff_xrv", "mean"))
    per["xrv100"] *= 100
    by_pt = {}
    for pid, grp in g.groupby("pitcher"):
        by_pt[str(pid)] = {r.pitch_type: {k: getattr(r, k) for k in ("n", "usage", "stuff", "xrv100", "velo", "ivb", "hb", "spin",
                                                                      "ext", "vaa", "p_whiff", "whiff", "p_swing", "rv100")}
                           for r in grp.itertuples()}
    pitchers = {str(pid): {"n": int(r.n), "stuff": float(r.stuff), "xrv100": float(r.xrv100), "types": by_pt.get(str(pid), {})}
                for pid, r in per.iterrows()}
    league = sc.groupby("pitch_type", observed=True).agg(n=("stuff", "size"), stuff=("stuff", "mean"),
                                                         velo=("release_speed", "mean")).reset_index()
    return {"pitchers": pitchers, "league": {r.pitch_type: {"n": int(r.n), "stuff": float(r.stuff), "velo": float(r.velo)}
                                             for r in league.itertuples()}}


def leaders(sc: pd.DataFrame, min_n: int = 200, top: int = 10) -> dict:
    g = sc.groupby(["pitcher", "pitch_type"], observed=True).agg(n=("stuff", "size"), stuff=("stuff", "mean"),
                                                                 velo=("release_speed", "mean"), ivb=("ivb", "mean"),
                                                                 hb=("hb_arm", "mean")).reset_index()
    g = g[g["n"] >= min_n]
    out = {}
    for pt, grp in g.groupby("pitch_type", observed=True):
        out[pt] = grp.sort_values("stuff", ascending=False).head(top).to_dict("records")
    return out


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    """Stuff scores for one season: {"ok","level","season","model": {seasons, scale, importance},
    "pitchers": {pid: {n, stuff, xrv100, types: {pt: {...}}}}, "league": {pt: {...}}, "leaders": {pt: [...]}}."""
    try:
        src = _io.pitch_path(level, season)
        if not src.exists():
            return {"ok": False, "reason": "no pitch table"}
        model = model_for(level, season, use_cache)
        if not model.get("ok"):
            return {"ok": False, "reason": model.get("reason", "no model")}
        key = _io.file_key(MODEL_VERSION, model.get("seasons"), model.get("scale"), src)

        def build():
            df = prep.prepared(level, season)
            sc = score(df[usable(df)], model)
            del df
            out = {"ok": True, "level": level, "season": season, "version": MODEL_VERSION,
                   "model": {"seasons": model["seasons"], "scale": model["scale"], "importance": model["importance"],
                             "rv": model["rv"]}}
            out.update(aggregate(sc))
            out["leaders"] = leaders(sc)
            return _io.clean(out, 4)

        return _io.cached("stuff", f"season_{level}_{season}", key, build, use_cache)
    except Exception as e:  # noqa: BLE001 - a failing model step returns a payload, not an exception
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}


def export_fits(level: str = "mlb", season: int | None = None, log=None) -> str:
    """Fit on the latest N_TRAIN_SEASONS seasons on disk (through `season` when given) and write
    models/fitted/stuff_<level>.json.gz for CI."""
    on = _io.seasons_on_disk(level)
    if season is not None:
        on = [s for s in on if s <= season]
    seasons = on[-N_TRAIN_SEASONS:]
    m = fit(level, seasons, log=log, baseline=False)
    return str(_io.write_json(_io.FITTED / f"stuff_{level}.json", m, gz=True))
