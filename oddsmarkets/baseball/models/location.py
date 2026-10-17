"""
Location model: the run value of where a pitch is thrown, given the count, pitch family and platoon.

    loc_xrv = E[rv_dn | x_away, z_rel, plate_z, balls, strikes, family, platoon, pitcher hand, batter side]

fitted by LightGBM regression (a smooth surface: large leaves, strong L2) on rv_dn, the pitch's
delta_run_exp with in-play luck removed (prep.py). x_away is plate_x signed away from the batter, z_rel the
height as a share of the batter's zone.

The location *score* is count-neutral: loc_rel = loc_xrv - base[count], where base is the training mean
run value in that count, so a 3-0 pitch is not penalised for the count it was thrown in. Scaled as the
stuff score: 100 + 10 (mu - loc_rel) / sd_pt, so the league's pitches average 100 and 10 is one SD of
pitcher-pitch-type mean location value.

`grid` evaluates the surface on a 13 x 13 batter-relative grid for any family / platoon / count (the
heatmaps the pitcher and hitter pages draw).
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io, prep

MODEL_VERSION = "location-1"

FEATURES = ["x_away", "z_rel", "plate_z", "balls", "strikes", "fam", "platoon", "throws_l", "stand_l"]
N_TRAIN_SEASONS = 4
SAMPLE_PER_SEASON = 400_000
LGB_PARAMS = {"num_leaves": 31, "learning_rate": 0.06, "min_data_in_leaf": 1000, "lambda_l2": 20.0,
              "feature_fraction": 1.0}
ROUNDS = 500
SCALE_MIN = 100
GRID_X = np.round(np.linspace(-1.5, 1.5, 13), 3)
GRID_Z = np.round(np.linspace(-0.5, 1.5, 13), 3)


def usable(df: pd.DataFrame) -> pd.Series:
    return (df["competitive"] & ~df["bunt"] & df["family"].notna() & df["x_away"].notna() & df["z_rel"].notna()
            & df["rv_dn"].notna())


def features(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for c in FEATURES:
        X[c] = pd.to_numeric(df[c], errors="coerce").astype(np.float32)
    return X


def fit(level: str, seasons: list[int], frames: dict | None = None, n_per_season: int = SAMPLE_PER_SEASON,
        log=None) -> dict:
    t0 = time.time()
    tr = prep.sample_seasons(level, seasons, n_per_season, filt=usable, frames=frames,
                             columns=FEATURES + ["cnt", "rv_dn", "pitcher", "pitch_type"])
    if len(tr) < 500:
        return {"ok": False, "reason": f"only {len(tr)} training pitches"}
    X = features(tr)
    y = tr["rv_dn"].to_numpy(float)
    vm = np.random.default_rng(3).random(len(tr)) < 0.1
    bst, info = _io.lgb_train(X[~vm], y[~vm], "regression", LGB_PARAMS, X[vm], y[vm], rounds=ROUNDS, early=40)
    ms = _io.booster_dump(bst)
    base = tr.groupby("cnt")["rv_dn"].mean()
    model = {"ok": True, "version": MODEL_VERSION, "level": level, "seasons": list(seasons), "features": FEATURES,
             "model": ms, **info, "base": {str(int(k)): float(v) for k, v in base.items()},
             "importance": _io.importances(ms, FEATURES), "n_train": int(len(tr))}
    if log:
        log(f"location: n={len(tr)} iters={info['best_iter']} {info.get('val_metric')}")
    del tr, X
    last = seasons[-1]
    df = frames[last] if frames is not None and last in frames else prep.prepared(level, last)
    sc = score(df[usable(df)], model, scaled=False)
    model["scale"] = scaling(sc)
    model["fit_secs"] = round(time.time() - t0, 1)
    return model


def scaling(sc: pd.DataFrame, col: str = "loc_rel", min_n: int = SCALE_MIN) -> dict:
    x = sc[col].astype(float)
    g = sc.groupby(["pitcher", "pitch_type"], observed=True)[col].agg(["mean", "size"])
    g = g[g["size"] >= min_n]
    return {"mu": float(x.mean()), "sd_pitch": float(x.std()),
            "sd_pt": float(g["mean"].std()) if len(g) > 5 else float(x.std()), "n_groups": int(len(g))}


def base_of(model: dict, cnt: np.ndarray) -> np.ndarray:
    tab = np.array([model["base"].get(str(i), 0.0) for i in range(12)])
    return tab[np.clip(np.asarray(cnt, int), 0, 11)]


def predict(df: pd.DataFrame, model: dict) -> np.ndarray:
    return _io.lgb_predict(model["model"], features(df))


def score(df: pd.DataFrame, model: dict, scaled: bool = True) -> pd.DataFrame:
    keep = [c for c in ("game_pk", "game_date", "at_bat_number", "pitch_number", "pitcher", "batter", "pitch_type",
                        "family", "cnt", "rv_dn") if c in df]
    out = df[keep].copy()
    out["loc_xrv"] = predict(df, model).astype(np.float32)
    out["loc_rel"] = (out["loc_xrv"] - base_of(model, df["cnt"].to_numpy())).astype(np.float32)
    if scaled and model.get("scale"):
        s = model["scale"]
        out["location"] = _io.scale_100(out["loc_rel"], s["mu"], s["sd_pt"]).astype(np.float32)
    return out


def grid(model: dict, fam: str = "fastball", platoon: int = 1, balls: int = 0, strikes: int = 0,
         throws_l: int = 0) -> dict:
    """The run-value surface (runs per pitch from the batting side, count-relative) on GRID_X x GRID_Z."""
    xx, zz = np.meshgrid(GRID_X, GRID_Z)
    n = xx.size
    stand_l = throws_l if platoon else 1 - throws_l
    df = pd.DataFrame({"x_away": xx.ravel(), "z_rel": zz.ravel(), "plate_z": 1.6 + zz.ravel() * 1.8,
                       "balls": np.full(n, balls), "strikes": np.full(n, strikes),
                       "fam": np.full(n, _io.FAMILY_CODE[fam]), "platoon": np.full(n, platoon),
                       "throws_l": np.full(n, throws_l), "stand_l": np.full(n, stand_l)})
    v = predict(df, model) - base_of(model, np.full(n, balls * 3 + strikes))
    return {"x": GRID_X.tolist(), "z": GRID_Z.tolist(), "rv": np.round(v.reshape(xx.shape), 4).tolist()}


def train_seasons(level: str, season: int, n: int = N_TRAIN_SEASONS) -> list[int]:
    return [s for s in _io.seasons_on_disk(level) if s < season][-n:]


def model_for(level: str, season: int, use_cache: bool = True, log=None) -> dict:
    seasons = train_seasons(level, season)
    if not seasons:
        m = _io.load_fitted(f"location_{level}", MODEL_VERSION)
        if m:
            return m
        seasons = [season] if _io.pitch_path(level, season).exists() else []
    if not seasons:
        return {"ok": False, "reason": "no pitch data and no committed fit"}
    key = _io.file_key(MODEL_VERSION, *[_io.pitch_path(level, s) for s in seasons])
    return _io.cached("location", f"model_{level}_{'-'.join(map(str, seasons))}", key,
                      lambda: fit(level, seasons, log=log), use_cache, gz=True)


def aggregate(sc: pd.DataFrame) -> dict:
    g = sc.groupby(["pitcher", "pitch_type"], observed=True).agg(n=("location", "size"), location=("location", "mean"),
                                                                 loc_rv100=("loc_rel", "mean")).reset_index()
    g["loc_rv100"] *= 100
    per = sc.groupby("pitcher").agg(n=("location", "size"), location=("location", "mean"), loc_rv100=("loc_rel", "mean"))
    per["loc_rv100"] *= 100
    types: dict[str, dict] = {}
    for r in g.itertuples():
        types.setdefault(str(r.pitcher), {})[r.pitch_type] = {"n": int(r.n), "location": float(r.location),
                                                              "loc_rv100": float(r.loc_rv100)}
    return {"pitchers": {str(pid): {"n": int(r.n), "location": float(r.location), "loc_rv100": float(r.loc_rv100),
                                    "types": types.get(str(pid), {})} for pid, r in per.iterrows()}}


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    """{"ok","level","season","model": {seasons, scale, importance, base}, "pitchers": {pid: {...}},
    "grids": {"<fam>|<platoon>|<b>-<s>": grid}}."""
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
                   "model": {k: model.get(k) for k in ("seasons", "scale", "importance", "base")}}
            out.update(aggregate(sc))
            grids = {}
            for fam in _io.FAMILIES:
                for pl in (0, 1):
                    for b, s in ((0, 0), (0, 2), (2, 0), (3, 2), (1, 1)):
                        grids[f"{fam}|{pl}|{b}-{s}"] = grid(model, fam, pl, b, s)
            out["grids"] = grids
            return _io.clean(out, 4)

        return _io.cached("location", f"season_{level}_{season}", key, build, use_cache)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}


def export_fits(level: str = "mlb", season: int | None = None, log=None) -> str:
    on = [s for s in _io.seasons_on_disk(level) if season is None or s <= season]
    m = fit(level, on[-N_TRAIN_SEASONS:], log=log)
    return str(_io.write_json(_io.FITTED / f"location_{level}.json", m, gz=True))
