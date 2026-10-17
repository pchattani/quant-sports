"""
Pitching model: stuff, location, count and sequence together in one expected run value per pitch.

    pitch_xrv = E[rv_dn | stuff_xrv, loc_rel, the stuff model's physical features, location (x_away, z_rel,
                          plate_z), count, family, batter side,
                          sequence: has_prev, prev_same, d_velo_prev, d_ivb_prev, d_hb_prev, dp_dist, plate_dist]

(LightGBM regression; stuff_xrv from stuff.py, loc_rel from location.py, sequence features from the previous
pitch of the plate appearance, prep.py). The physical features enter directly as well as through stuff_xrv so
the model can learn stuff x location interactions (a riding fastball up in the zone). No validation figure for
the combined model is recorded in a committed file (an earlier note quoted a pitcher-level correlation of 0.39 with
run value per pitch; it is not reproducible from the repository and is not published). The score is count-neutral, pitch_rel = pitch_xrv - base[count],
scaled like the others: 100 + 10 (mu - pitch_rel) / sd_pt (100 = the league's average pitch, 10 = one SD of
pitcher-pitch-type means).

`for_season` reports stuff, location and pitching per pitcher, per pitch type and overall, plus a game-by-
game series with a rolling ROLL_N-pitch pitching score.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io, location, physics, prep, stuff

MODEL_VERSION = "pitching-2"

SEQ = ["has_prev", "prev_same", "d_velo_prev", "d_ivb_prev", "d_hb_prev", "dp_dist", "plate_dist"]
LOC = ["x_away", "z_rel", "plate_z", "balls", "strikes", "fam", "stand_l"]
FEATURES = ["stuff_xrv", "loc_rel"] + stuff.FEATURES + LOC + SEQ
N_TRAIN_SEASONS = 4
SAMPLE_PER_SEASON = 400_000
LGB_PARAMS = {"num_leaves": 31, "learning_rate": 0.06, "min_data_in_leaf": 1000, "lambda_l2": 20.0}
ROUNDS = 500
SCALE_MIN = 100
ROLL_N = 500


def usable(df: pd.DataFrame) -> pd.Series:
    return stuff.usable(df) & location.usable(df)


def add_components(df: pd.DataFrame, stuff_model: dict, loc_model: dict) -> pd.DataFrame:
    """The enriched frame plus stuff_xrv / stuff and loc_rel / location columns."""
    out = df.copy()
    out["vaa_adj"] = physics.vaa_adjusted(df, stuff_model["vaa_slopes"]).astype(np.float32)
    s = stuff.score(df, stuff_model, scaled=bool(stuff_model.get("scale")))
    out["stuff_xrv"] = s["stuff_xrv"].to_numpy()
    if "stuff" in s:
        out["stuff"] = s["stuff"].to_numpy()
    for c in ("p_whiff", "p_swing", "p_called"):
        out[c] = s[c].to_numpy()
    lsc = location.score(df, loc_model, scaled=bool(loc_model.get("scale")))
    out["loc_rel"] = lsc["loc_rel"].to_numpy()
    if "location" in lsc:
        out["location"] = lsc["location"].to_numpy()
    return out


def features(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for c in FEATURES:
        X[c] = pd.to_numeric(df[c], errors="coerce").astype(np.float32)
    return X


def fit(level: str, seasons: list[int], stuff_model: dict, loc_model: dict, frames: dict | None = None,
        n_per_season: int = SAMPLE_PER_SEASON, log=None) -> dict:
    t0 = time.time()
    parts = []
    for i, s in enumerate(seasons):
        df = prep.sample_seasons(level, [s], n_per_season, filt=usable, frames=frames)
        if df.empty:
            continue
        parts.append(add_components(df, stuff_model, loc_model)[FEATURES + ["rv_dn", "cnt"]])
        del df
    tr = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if len(tr) < 500:
        return {"ok": False, "reason": f"only {len(tr)} training pitches"}
    X = features(tr)
    y = tr["rv_dn"].to_numpy(float)
    vm = np.random.default_rng(13).random(len(tr)) < 0.1
    bst, info = _io.lgb_train(X[~vm], y[~vm], "regression", LGB_PARAMS, X[vm], y[vm], rounds=ROUNDS, early=40)
    ms = _io.booster_dump(bst)
    base = tr.groupby("cnt")["rv_dn"].mean()
    model = {"ok": True, "version": MODEL_VERSION, "level": level, "seasons": list(seasons), "features": FEATURES,
             "model": ms, **info, "base": {str(int(k)): float(v) for k, v in base.items()},
             "importance": _io.importances(ms, FEATURES), "n_train": int(len(tr)),
             "components": {"stuff": stuff_model.get("seasons"), "location": loc_model.get("seasons")}}
    if log:
        log(f"pitching: n={len(tr)} iters={info['best_iter']} {info.get('val_metric')}")
    del tr, X
    last = seasons[-1]
    df = frames[last] if frames is not None and last in frames else prep.prepared(level, last)
    sc = score(add_components(df[usable(df)], stuff_model, loc_model), model, scaled=False)
    model["scale"] = location.scaling(sc, "pitch_rel")
    model["fit_secs"] = round(time.time() - t0, 1)
    return model


def score(dfc: pd.DataFrame, model: dict, scaled: bool = True) -> pd.DataFrame:
    """dfc: a frame from add_components. Adds pitch_xrv, pitch_rel and (scaled) pitching."""
    out = dfc.copy()
    out["pitch_xrv"] = _io.lgb_predict(model["model"], features(dfc)).astype(np.float32)
    out["pitch_rel"] = (out["pitch_xrv"] - location.base_of(model, dfc["cnt"].to_numpy())).astype(np.float32)
    if scaled and model.get("scale"):
        s = model["scale"]
        out["pitching"] = _io.scale_100(out["pitch_rel"], s["mu"], s["sd_pt"]).astype(np.float32)
    return out


def train_seasons(level: str, season: int, n: int = N_TRAIN_SEASONS) -> list[int]:
    return [s for s in _io.seasons_on_disk(level) if s < season][-n:]


def model_for(level: str, season: int, use_cache: bool = True, log=None) -> dict:
    seasons = train_seasons(level, season)
    if not seasons:
        m = _io.load_fitted(f"pitching_{level}", MODEL_VERSION)
        if m:
            return m
        seasons = [season] if _io.pitch_path(level, season).exists() else []
    if not seasons:
        return {"ok": False, "reason": "no pitch data and no committed fit"}
    sm = stuff.model_for(level, season, use_cache, log)
    lm = location.model_for(level, season, use_cache, log)
    if not sm.get("ok") or not lm.get("ok"):
        return {"ok": False, "reason": "component model missing"}
    key = _io.file_key(MODEL_VERSION, *[_io.pitch_path(level, s) for s in seasons], sm.get("scale"), lm.get("scale"))
    return _io.cached("pitching", f"model_{level}_{'-'.join(map(str, seasons))}", key,
                      lambda: fit(level, seasons, sm, lm, log=log), use_cache, gz=True)


def rolling(sc: pd.DataFrame, n: int = ROLL_N, col: str = "pitching") -> dict:
    """Per pitcher, per game: [date, pitches, game stuff, game location, game pitching, rolling-n pitching]."""
    d = sc.sort_values(["pitcher", "game_date", "game_pk", "at_bat_number", "pitch_number"], kind="mergesort")
    out: dict[str, list] = {}
    for pid, g in d.groupby("pitcher", sort=False):
        v = g[col].to_numpy(float)
        cs = np.concatenate([[0.0], np.cumsum(v)])
        idx = np.arange(1, len(v) + 1)
        lo = np.maximum(idx - n, 0)
        roll = (cs[idx] - cs[lo]) / (idx - lo)
        gg = g.assign(_roll=roll).groupby(["game_date", "game_pk"], sort=False)
        rows = gg.agg(n=(col, "size"), stuff=("stuff", "mean"), location=("location", "mean"), pitching=(col, "mean"),
                      roll=("_roll", "last")).reset_index()
        out[str(pid)] = [[r.game_date, int(r.n), round(float(r.stuff), 1), round(float(r.location), 1),
                          round(float(r.pitching), 1), round(float(r.roll), 1)] for r in rows.itertuples()]
    return out


def aggregate(sc: pd.DataFrame) -> dict:
    cols = dict(n=("pitching", "size"), stuff=("stuff", "mean"), location=("location", "mean"), pitching=("pitching", "mean"),
                xrv100=("pitch_rel", "mean"), velo=("release_speed", "mean"), ivb=("ivb", "mean"), hb=("hb_arm", "mean"),
                spin=("release_spin_rate", "mean"), vaa=("vaa", "mean"), ext=("release_extension", "mean"),
                rv=("rv", "mean"))
    g = sc.groupby(["pitcher", "pitch_type"], observed=True).agg(**cols).reset_index()
    tot = sc.groupby("pitcher").size()
    g["usage"] = g["n"] / g["pitcher"].map(tot)
    for c in ("xrv100", "rv"):
        g[c] *= 100
    per = sc.groupby("pitcher").agg(n=("pitching", "size"), stuff=("stuff", "mean"), location=("location", "mean"),
                                    pitching=("pitching", "mean"), xrv100=("pitch_rel", "mean"), rv=("rv", "mean"))
    per["xrv100"] *= 100
    per["rv"] *= 100
    types: dict[str, dict] = {}
    keys = ("n", "usage", "stuff", "location", "pitching", "xrv100", "rv", "velo", "ivb", "hb", "spin", "vaa", "ext")
    for r in g.itertuples():
        types.setdefault(str(r.pitcher), {})[r.pitch_type] = {k: getattr(r, k) for k in keys}
    return {str(pid): {"n": int(r.n), "stuff": r.stuff, "location": r.location, "pitching": r.pitching,
                       "xrv100": r.xrv100, "rv100": r.rv, "types": types.get(str(pid), {})} for pid, r in per.iterrows()}


def season_scores(level: str, season: int, use_cache: bool = True, df: pd.DataFrame | None = None,
                  models: tuple[dict, dict, dict] | None = None) -> pd.DataFrame:
    """Per-pitch stuff, location and pitching scores for an enriched season."""
    if models is None:
        sm, lm, pm = stuff.model_for(level, season, use_cache), location.model_for(level, season, use_cache), \
            model_for(level, season, use_cache)
    else:
        sm, lm, pm = models
    if df is None:
        df = prep.prepared(level, season)
    dfc = add_components(df[usable(df)], sm, lm)
    return score(dfc, pm)


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    """{"ok","level","season","model": {...}, "pitchers": {pid: {n, stuff, location, pitching, xrv100, rv100,
    types: {pt: {...}}}}, "rolling": {pid: [[date, n, stuff, location, pitching, roll], ...]},
    "leaders": {pt: [...]}}."""
    try:
        src = _io.pitch_path(level, season)
        if not src.exists():
            return {"ok": False, "reason": "no pitch table"}
        pm = model_for(level, season, use_cache)
        if not pm.get("ok"):
            return {"ok": False, "reason": pm.get("reason", "no model")}
        key = _io.file_key(MODEL_VERSION, pm.get("seasons"), pm.get("scale"), src)

        def build():
            sc = season_scores(level, season, use_cache)
            lead = {}
            g = sc.groupby(["pitcher", "pitch_type"], observed=True).agg(
                n=("pitching", "size"), stuff=("stuff", "mean"), location=("location", "mean"),
                pitching=("pitching", "mean")).reset_index()
            for pt, grp in g[g["n"] >= 200].groupby("pitch_type", observed=True):
                lead[pt] = grp.sort_values("pitching", ascending=False).head(10).to_dict("records")
            return _io.clean({"ok": True, "level": level, "season": season, "version": MODEL_VERSION,
                              "model": {k: pm.get(k) for k in ("seasons", "scale", "importance", "base")},
                              "pitchers": aggregate(sc), "rolling": rolling(sc), "leaders": lead}, 3)

        return _io.cached("pitching", f"season_{level}_{season}", key, build, use_cache, gz=True)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}


def export_fits(level: str = "mlb", season: int | None = None, log=None, with_swing: bool = True) -> dict:
    """Write builder B's committed fits for CI, fitted on the latest N_TRAIN_SEASONS seasons on disk
    (through `season`): models/fitted/{stuff,location,pitching,swing}_<level>.json.gz."""
    from oddsmarkets.baseball.models import swing
    on = [s for s in _io.seasons_on_disk(level) if season is None or s <= season]
    seasons = on[-N_TRAIN_SEASONS:]
    if not seasons:
        return {"ok": False, "reason": "no seasons on disk"}
    sm = stuff.fit(level, seasons, log=log, baseline=False)
    lm = location.fit(level, seasons, log=log)
    pm = fit(level, seasons, sm, lm, log=log)
    out = {"stuff": str(_io.write_json(_io.FITTED / f"stuff_{level}.json", sm, gz=True)),
           "location": str(_io.write_json(_io.FITTED / f"location_{level}.json", lm, gz=True)),
           "pitching": str(_io.write_json(_io.FITTED / f"pitching_{level}.json", pm, gz=True))}
    if with_swing:
        out["swing"] = str(_io.write_json(_io.FITTED / f"swing_{level}.json", swing.fit(level, seasons, log=log), gz=True))
    return out
