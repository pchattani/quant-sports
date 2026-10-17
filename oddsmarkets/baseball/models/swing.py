"""
Swing decisions: P(swing), the run value of swinging against taking, and each hitter's decision value.

League models (LightGBM, trained on competitive non-bunt pitches of the training seasons):

    p_sw(pitch, count)   = P(swing | x_away, z_rel, plate_z, balls, strikes, family, velocity, IVB, HB, hands)
    rv_sw(pitch, count)  = E[rv_dn | swing, same features]     (whiffs, fouls and balls in play, in-play luck removed)
    rv_tk(pitch, count)  = E[rv    | take,  same features]     (balls and called strikes)

All run values are from the batting side (positive = good for the hitter). The batter-specific swing
probability adds a ridge-shrunk logit offset per batter (`aggression`, prior sd TAU):
P(swing | pitch, count, batter) = sigmoid(logit p_sw + a_batter).

Decision value of pitch i (the batter chose c_i = swing or take):

    dv_i = rv_c(i) - [p_sw rv_sw + (1 - p_sw) rv_tk]

the runs the choice gained over the league-average decision on that pitch, valued at league-average
outcomes for each choice, so it isolates the decision from the contact that follows. A hitter's decision
value is sum_i dv_i (and per 100 pitches), split into the zone and chase parts (which add up to the total).
`dv_alt` = rv_c(i) - rv_other(i) measures the choice against the opposite one; "should have swung" is the
share of takes where rv_sw > rv_tk and "should have taken" the share of swings where rv_tk > rv_sw.
dv_c centres dv on the season's league (dv - n * mean dv per pitch), so league dv_c sums to zero; the
leaderboards use it.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io, prep

MODEL_VERSION = "swing-1"

FEATURES = ["x_away", "z_rel", "plate_z", "balls", "strikes", "fam", "release_speed", "ivb", "hb_arm", "platoon",
            "throws_l", "stand_l"]
N_TRAIN_SEASONS = 4
SAMPLE_PER_SEASON = 400_000
LGB_SWING = {"num_leaves": 63, "learning_rate": 0.08, "min_data_in_leaf": 300, "lambda_l2": 5.0}
LGB_RV = {"num_leaves": 31, "learning_rate": 0.06, "min_data_in_leaf": 1000, "lambda_l2": 20.0}
ROUNDS = 500
TAU = 0.5
GRID_X = np.round(np.linspace(-1.5, 1.5, 13), 3)
GRID_Z = np.round(np.linspace(-0.5, 1.5, 13), 3)


def usable(df: pd.DataFrame) -> pd.Series:
    return (df["competitive"] & ~df["bunt"] & df["family"].notna() & df["x_away"].notna() & df["z_rel"].notna()
            & df["rv"].notna())


def features(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for c in FEATURES:
        X[c] = pd.to_numeric(df[c], errors="coerce").astype(np.float32)
    return X


def fit(level: str, seasons: list[int], frames: dict | None = None, n_per_season: int = SAMPLE_PER_SEASON,
        log=None) -> dict:
    t0 = time.time()
    tr = prep.sample_seasons(level, seasons, n_per_season, filt=usable, frames=frames,
                             columns=FEATURES + ["swing", "take", "rv", "rv_dn"])
    if len(tr) < 500:
        return {"ok": False, "reason": f"only {len(tr)} training pitches"}
    X = features(tr)
    vm = np.random.default_rng(9).random(len(tr)) < 0.1
    out: dict[str, Any] = {"ok": True, "version": MODEL_VERSION, "level": level, "seasons": list(seasons),
                           "features": FEATURES, "n_train": int(len(tr))}
    sw = tr["swing"].to_numpy(bool)
    for name, mask, y, obj, params in (("swing", np.ones(len(tr), bool), sw.astype(float), "binary", LGB_SWING),
                                       ("rv_swing", sw, tr["rv_dn"].to_numpy(float), "regression", LGB_RV),
                                       ("rv_take", tr["take"].to_numpy(bool), tr["rv"].to_numpy(float), "regression", LGB_RV)):
        m = mask
        bst, info = _io.lgb_train(X[m & ~vm], y[m & ~vm], obj, params, X[m & vm], y[m & vm], rounds=ROUNDS, early=40)
        ms = _io.booster_dump(bst)
        out[name] = {"model": ms, **info, "n": int(m.sum()), "mean": float(np.mean(y[m]))}
        out.setdefault("importance", {})[name] = _io.importances(ms, FEATURES)
        if log:
            log(f"swing {name}: n={m.sum()} iters={info['best_iter']} {info.get('val_metric')}")
    out["fit_secs"] = round(time.time() - t0, 1)
    return out


def predict(df: pd.DataFrame, model: dict) -> dict[str, np.ndarray]:
    X = features(df)
    return {"p_sw": _io.lgb_predict(model["swing"]["model"], X),
            "rv_sw": _io.lgb_predict(model["rv_swing"]["model"], X),
            "rv_tk": _io.lgb_predict(model["rv_take"]["model"], X)}


def batter_offsets(batter: np.ndarray, y: np.ndarray, p: np.ndarray, tau: float = TAU, iters: int = 8) -> dict:
    """Ridge-shrunk logit offset per batter: argmax_o sum log L(y | sigmoid(logit p + o)) - o^2 / (2 tau^2)."""
    ids, inv = np.unique(batter, return_inverse=True)
    eta = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))
    o = np.zeros(len(ids))
    for _ in range(iters):
        mu = 1 / (1 + np.exp(-(eta + o[inv])))
        g = np.bincount(inv, y - mu, len(ids)) - o / tau ** 2
        h = np.bincount(inv, mu * (1 - mu), len(ids)) + 1 / tau ** 2
        o = o + g / h
    return dict(zip(ids.tolist(), o.tolist()))


def decisions(df: pd.DataFrame, model: dict) -> pd.DataFrame:
    """Per pitch: p_sw, rv_sw, rv_tk, the choice, dv and dv_alt (module docstring)."""
    keep = [c for c in ("game_pk", "game_date", "at_bat_number", "pitch_number", "batter", "pitcher", "stand",
                        "in_zone", "x_away", "z_rel", "balls", "strikes", "swing", "whiff", "contact", "rv", "rv_dn") if c in df]
    out = df[keep].copy()
    p = predict(df, model)
    for k, v in p.items():
        out[k] = v.astype(np.float32)
    sw = out["swing"].to_numpy(bool)
    chosen = np.where(sw, p["rv_sw"], p["rv_tk"])
    other = np.where(sw, p["rv_tk"], p["rv_sw"])
    exp = p["p_sw"] * p["rv_sw"] + (1 - p["p_sw"]) * p["rv_tk"]
    out["dv"] = (chosen - exp).astype(np.float32)
    out["dv_alt"] = (chosen - other).astype(np.float32)
    out["swing_adv"] = (p["rv_sw"] - p["rv_tk"]).astype(np.float32)
    return out


def hitters(dec: pd.DataFrame, offsets: dict | None = None, min_n: int = 1) -> pd.DataFrame:
    d = dec.copy()
    d["sw"] = d["swing"].astype(float)
    z = d["in_zone"].astype(bool)
    d["z_sw"] = np.where(z, d["sw"], np.nan)
    d["o_sw"] = np.where(~z, d["sw"], np.nan)
    d["dv_zone"] = np.where(z, d["dv"], 0.0)
    d["dv_chase"] = np.where(~z, d["dv"], 0.0)
    d["should_sw"] = np.where(~d["swing"], (d["swing_adv"] > 0).astype(float), np.nan)
    d["should_tk"] = np.where(d["swing"], (d["swing_adv"] < 0).astype(float), np.nan)
    d["contact_f"] = np.where(d["swing"], d["contact"].astype(float), np.nan)
    g = d.groupby("batter").agg(n=("dv", "size"), dv=("dv", "sum"), dv_zone=("dv_zone", "sum"), dv_chase=("dv_chase", "sum"),
                                dv_alt=("dv_alt", "sum"), swing=("sw", "mean"), x_swing=("p_sw", "mean"),
                                zone_swing=("z_sw", "mean"), chase=("o_sw", "mean"), zone=("in_zone", "mean"),
                                should_swing=("should_sw", "mean"), should_take=("should_tk", "mean"),
                                contact=("contact_f", "mean"))
    g["dv100"] = 100 * g["dv"] / g["n"]
    # centred on this season's league: the model's smoothing and league-wide drift from the training
    # seasons leave a small mean dv per pitch; dv_c sums to zero over the league
    mean_dv = float(d["dv"].mean()) if len(d) else 0.0
    g["dv_c"] = g["dv"] - mean_dv * g["n"]
    g["dv_c100"] = 100 * g["dv_c"] / g["n"]
    if offsets:
        g["aggression"] = g.index.map(offsets)
    return g[g["n"] >= min_n]


def value_grid(model: dict, balls: int, strikes: int, fam: str = "fastball", platoon: int = 0) -> dict:
    """Swing advantage rv_sw - rv_tk and P(swing) on a batter-relative grid for one count."""
    xx, zz = np.meshgrid(GRID_X, GRID_Z)
    n = xx.size
    velo = {"fastball": 94.0, "breaking": 84.0, "offspeed": 86.0}[fam]
    ivb = {"fastball": 15.0, "breaking": -2.0, "offspeed": 6.0}[fam]
    hb = {"fastball": 8.0, "breaking": -6.0, "offspeed": 13.0}[fam]
    df = pd.DataFrame({"x_away": xx.ravel(), "z_rel": zz.ravel(), "plate_z": 1.6 + zz.ravel() * 1.8,
                       "balls": np.full(n, balls), "strikes": np.full(n, strikes), "fam": np.full(n, _io.FAMILY_CODE[fam]),
                       "release_speed": np.full(n, velo), "ivb": np.full(n, ivb), "hb_arm": np.full(n, hb),
                       "platoon": np.full(n, platoon), "throws_l": np.zeros(n), "stand_l": np.full(n, 0 if platoon else 1)})
    p = predict(df, model)
    return {"x": GRID_X.tolist(), "z": GRID_Z.tolist(),
            "adv": np.round((p["rv_sw"] - p["rv_tk"]).reshape(xx.shape), 4).tolist(),
            "p_sw": np.round(p["p_sw"].reshape(xx.shape), 3).tolist()}


def train_seasons(level: str, season: int, n: int = N_TRAIN_SEASONS) -> list[int]:
    return [s for s in _io.seasons_on_disk(level) if s < season][-n:]


def model_for(level: str, season: int, use_cache: bool = True, log=None) -> dict:
    seasons = train_seasons(level, season)
    if not seasons:
        m = _io.load_fitted(f"swing_{level}", MODEL_VERSION)
        if m:
            return m
        seasons = [season] if _io.pitch_path(level, season).exists() else []
    if not seasons:
        return {"ok": False, "reason": "no pitch data and no committed fit"}
    key = _io.file_key(MODEL_VERSION, *[_io.pitch_path(level, s) for s in seasons])
    return _io.cached("swing", f"model_{level}_{'-'.join(map(str, seasons))}", key,
                      lambda: fit(level, seasons, log=log), use_cache, gz=True)


def season_table(df: pd.DataFrame, model: dict, min_n: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per-pitch decisions, per-hitter table) for an enriched season."""
    u = df[usable(df)]
    dec = decisions(u, model)
    offs = batter_offsets(dec["batter"].to_numpy(), dec["swing"].to_numpy(float), dec["p_sw"].to_numpy())
    return dec, hitters(dec, offs, min_n)


def for_season(level: str, season: int, use_cache: bool = True, min_n: int = 50) -> dict:
    """{"ok","level","season","model": {seasons, importance}, "hitters": {pid: {...}}, "league": {...},
    "grids": {"<b>-<s>|<fam>": value_grid}, "leaders": {"dv": [...], "dv100": [...]}}."""
    try:
        src = _io.pitch_path(level, season)
        if not src.exists():
            return {"ok": False, "reason": "no pitch table"}
        model = model_for(level, season, use_cache)
        if not model.get("ok"):
            return {"ok": False, "reason": model.get("reason", "no model")}
        key = _io.file_key(MODEL_VERSION, model.get("seasons"), src, min_n)

        def build():
            df = prep.prepared(level, season)
            dec, h = season_table(df, model, min_n=min_n)
            del df
            league = {"n": int(len(dec)), "swing": float(dec["swing"].mean()), "dv_total": float(dec["dv"].sum()),
                      "chase": float(dec.loc[dec["in_zone"] == 0, "swing"].mean()),
                      "zone_swing": float(dec.loc[dec["in_zone"] == 1, "swing"].mean())}
            grids = {f"{b}-{s}|{fam}": value_grid(model, b, s, fam) for b in range(4) for s in range(3)
                     for fam in ("fastball", "breaking")}
            q = h[h["n"] >= max(min_n, 1000)] if (h["n"] >= 1000).sum() >= 20 else h
            return _io.clean({"ok": True, "level": level, "season": season, "version": MODEL_VERSION,
                              "model": {"seasons": model["seasons"], "importance": model.get("importance")},
                              "hitters": {str(k): v for k, v in h.to_dict("index").items()}, "league": league,
                              "grids": grids,
                              "leaders": {"dv_c": q.sort_values("dv_c", ascending=False).head(15).reset_index().to_dict("records"),
                                          "dv_c100": q.sort_values("dv_c100", ascending=False).head(15).reset_index().to_dict("records")}}, 4)

        return _io.cached("swing", f"season_{level}_{season}", key, build, use_cache)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}


def export_fits(level: str = "mlb", season: int | None = None, log=None) -> str:
    on = [s for s in _io.seasons_on_disk(level) if season is None or s <= season]
    m = fit(level, on[-N_TRAIN_SEASONS:], log=log)
    return str(_io.write_json(_io.FITTED / f"swing_{level}.json", m, gz=True))
