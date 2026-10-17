"""
Called-strike probability and catcher framing.

Model (one season of called pitches: called_strike, ball, blocked_ball; automatic calls, pitchouts
and HBP excluded), a penalised logistic regression fitted by Newton/IRLS on a sparse design:

    logit P(strike) = f_stand(x, z~)                 tensor-product hat surface per batter side
                    + count[b-s] + family[FB/BR/OS/OT] + hands[pitcher hand x batter side]
                    + c_catcher + u_umpire + p_pitcher + b_batter      random effects (ridge)

x = plate_x (ft, catcher's view), z~ = (plate_z - sz_bot) / (sz_top - sz_bot) (0 = bottom of this
batter's zone, 1 = top). The surface has knots every 0.15 ft (x in [-1.8, 1.8]) and 0.1 zone
heights (z~ in [-0.6, 1.6]) with a second-difference penalty LAMBDA_SURF; count, family and hands
carry a ridge LAMBDA_FIXED. Random effects are Gaussian with fixed prior sds (SD_CATCHER,
SD_UMPIRE, SD_PITCHER, SD_BATTER, logit scale): their ridge is 1 / sd^2, which is exactly the
mixed-model posterior mode given those variance components (documented constants; the synthetic
tests recover planted catcher effects with them).

The umpire is the store's home-plate umpire for the game (GAME.umpire_hp) or the pitch table's
`umpire` column when the store lacks it.

Framing: for each called pitch received by catcher c,
    strikes added = p(with c) - p(with c = 0),
    framing runs  = strikes added x strike value at that count (re24.count_values: the run value of
                    a strike over a ball for the fielding side),
summed per catcher; also per 7,000 called pitches (about a full season of catching).
"""
from __future__ import annotations


import numpy as np
import pandas as pd
import scipy.sparse as sp

from oddsmarkets.baseball.models import _c

MODEL_VERSION = "frame-1"
KX = list(np.round(np.arange(-1.8, 1.8001, 0.15), 3))
KZ = list(np.round(np.arange(-0.6, 1.6001, 0.1), 3))
COUNTS = [f"{b}-{s}" for b in range(4) for s in range(3)]
FAMILY = {"FF": "FB", "SI": "FB", "FC": "FB", "FA": "FB", "FT": "FB", "SL": "BR", "CU": "BR", "KC": "BR", "SV": "BR",
          "ST": "BR", "CS": "BR", "SC": "BR", "CH": "OS", "FS": "OS", "FO": "OS"}
FAMILIES = ["FB", "BR", "OS", "OT"]
HANDS = ["R-R", "R-L", "L-R", "L-L"]
LAMBDA_SURF = 1.0
LAMBDA_FIXED = 1.0
SD_CATCHER = 0.20
SD_UMPIRE = 0.15
SD_PITCHER = 0.12
SD_BATTER = 0.12
DEFAULT_SZ = (1.55, 3.40)
PER_SEASON = 7000
COLUMNS = ["game_pk", "game_date", "at_bat_number", "pitch_number", "pitcher", "batter", "stand", "p_throws", "home_team",
           "away_team", "inning", "inning_topbot", "outs_when_up", "balls", "strikes", "on_1b", "on_2b", "on_3b",
           "pitch_type", "plate_x", "plate_z", "sz_top", "sz_bot", "description", "events", "umpire", "fielder_2",
           "bat_score", "fld_score", "post_bat_score", "woba_value", "woba_denom"]


def called_pitches(pitches: pd.DataFrame, store: dict | None = None) -> pd.DataFrame:
    """Called pitches with y, normalised height, count, family, hands, catcher, umpire ids."""
    d = pitches[pitches["description"].astype(str).isin(_c.CALLED) & pitches["plate_x"].notna() & pitches["plate_z"].notna()].copy()
    d["y"] = (d["description"].astype(str) == "called_strike").astype(int)
    bot = d["sz_bot"].astype(float).fillna(DEFAULT_SZ[0]) if "sz_bot" in d else pd.Series(DEFAULT_SZ[0], index=d.index)
    top = d["sz_top"].astype(float).fillna(DEFAULT_SZ[1]) if "sz_top" in d else pd.Series(DEFAULT_SZ[1], index=d.index)
    bad = (top - bot) < 0.8
    bot = bot.where(~bad, DEFAULT_SZ[0]); top = top.where(~bad, DEFAULT_SZ[1])
    d["sz_bot_"], d["sz_top_"] = bot, top
    d["zt"] = (d["plate_z"].astype(float) - bot) / (top - bot)
    d["count"] = d["balls"].astype(int).clip(0, 3).astype(str) + "-" + d["strikes"].astype(int).clip(0, 2).astype(str)
    d["family"] = d["pitch_type"].astype(str).map(FAMILY).fillna("OT")
    d["hands"] = d["p_throws"].astype(str).str[:1] + "-" + d["stand"].astype(str).str[:1]
    d["catcher"] = _ids(d["fielder_2"])
    d["pitcher"] = _ids(d["pitcher"]).fillna("")
    d["batter"] = _ids(d["batter"]).fillna("")
    ump = None
    if store and store.get("games"):
        gm = {int(k): (g or {}).get("umpire_hp") for k, g in store["games"].items()}
        ump = d["game_pk"].astype(np.int64).map(gm)
    if ump is None or ump.isna().all():
        ump = d["umpire"] if "umpire" in d else pd.Series(None, index=d.index)
    elif "umpire" in d:
        ump = ump.fillna(d["umpire"])
    d["ump"] = ump.map(lambda x: None if pd.isna(x) else str(int(x)) if isinstance(x, (int, float, np.integer, np.floating)) else str(x))
    d["in_zone"] = ((d["plate_x"].astype(float).abs() <= 0.83) & (d["plate_z"].astype(float) >= bot - 0.12)
                    & (d["plate_z"].astype(float) <= top + 0.12)).astype(int)
    return d.reset_index(drop=True)


def _ids(s: pd.Series) -> pd.Series:
    """Ids as strings of integers ("660271"), None when missing."""
    num = pd.to_numeric(s, errors="coerce")
    out = num.map(lambda x: str(int(x)) if pd.notna(x) else None)
    return out.where(num.notna(), s.where(s.notna(), None).map(lambda v: None if v is None else str(v)))


def _levels(s: pd.Series, min_n: int = 1) -> list[str]:
    vc = s.dropna().astype(str).value_counts()
    return sorted(vc[vc >= min_n].index.tolist())


def design(d: pd.DataFrame, spec: dict, drop: tuple[str, ...] = ()) -> sp.csr_matrix:
    """Design matrix. `drop` zeroes random-effect groups ("catcher", "ump", "pitcher", "batter")."""
    n = len(d)
    blocks = []
    x = d["plate_x"].astype(float).to_numpy(); z = d["zt"].astype(float).to_numpy()
    T = _c.tensor_hat(x, spec["kx"], z, spec["kz"])
    left = d["stand"].astype(str).str.upper().str.startswith("L").to_numpy()
    blocks.append(sp.diags((~left).astype(float)) @ T)
    blocks.append(sp.diags(left.astype(float)) @ T)
    blocks.append(_c.onehot(_c.codes(d["count"], COUNTS), len(COUNTS)))
    blocks.append(_c.onehot(_c.codes(d["family"], FAMILIES), len(FAMILIES)))
    blocks.append(_c.onehot(_c.codes(d["hands"], HANDS), len(HANDS)))
    for grp, col in (("catcher", "catcher"), ("ump", "ump"), ("pitcher", "pitcher"), ("batter", "batter")):
        lv = spec["levels"][grp]
        if grp in drop:
            blocks.append(sp.csr_matrix((n, len(lv))))
        else:
            vals = d[col].map(lambda v: None if pd.isna(v) else str(int(v)) if isinstance(v, (float, np.floating)) else str(v))
            blocks.append(_c.onehot(_c.codes(vals, lv), len(lv)))
    return sp.hstack(blocks, format="csr")


def _penalty(spec: dict) -> np.ndarray:
    mx, mz = len(spec["kx"]), len(spec["kz"])
    ns = mx * mz
    sizes = [ns, ns, len(COUNTS), len(FAMILIES), len(HANDS)] + [len(spec["levels"][g]) for g in ("catcher", "ump", "pitcher", "batter")]
    p = sum(sizes)
    P = np.zeros((p, p))
    Ps = LAMBDA_SURF * _c.tensor_penalty(mx, mz) + 1e-4 * np.eye(ns)
    P[:ns, :ns] = Ps
    P[ns:2 * ns, ns:2 * ns] = Ps
    o = 2 * ns
    for k in sizes[2:5]:
        P[o:o + k, o:o + k] += LAMBDA_FIXED * np.eye(k)
        o += k
    for g, sd in (("catcher", SD_CATCHER), ("ump", SD_UMPIRE), ("pitcher", SD_PITCHER), ("batter", SD_BATTER)):
        k = len(spec["levels"][g])
        P[o:o + k, o:o + k] += np.eye(k) / sd ** 2
        o += k
    return P


def fit(d: pd.DataFrame, min_n: int = 1) -> dict:
    """Fit the called-strike model on called pitches `d` (from `called_pitches`)."""
    spec = {"kx": KX, "kz": KZ, "levels": {"catcher": _levels(d["catcher"], min_n), "ump": _levels(d["ump"], min_n),
                                           "pitcher": _levels(d["pitcher"].astype(str), min_n),
                                           "batter": _levels(d["batter"].astype(str), min_n)}}
    d = d.assign(pitcher=d["pitcher"].astype(str), batter=d["batter"].astype(str))
    X = design(d, spec)
    P = _penalty(spec)
    y = d["y"].to_numpy(float)
    b0 = np.zeros(X.shape[1])
    ns = len(KX) * len(KZ)
    b0[:2 * ns] = -2.0
    res = _c.logistic_fit(X, y, P, beta0=b0, max_iter=30)
    beta = res["beta"]
    o = 2 * ns + len(COUNTS) + len(FAMILIES) + len(HANDS)
    effects = {}
    for g in ("catcher", "ump", "pitcher", "batter"):
        k = len(spec["levels"][g])
        effects[g] = dict(zip(spec["levels"][g], beta[o:o + k].tolist()))
        o += k
    return {"version": MODEL_VERSION, "spec": spec, "beta": beta, "effects": effects, "iters": res["iters"],
            "n": int(len(d)), "strike_rate": float(y.mean())}


def predict(model: dict, d: pd.DataFrame, drop: tuple[str, ...] = ()) -> np.ndarray:
    d = d.assign(pitcher=d["pitcher"].astype(str), batter=d["batter"].astype(str))
    return _c.sigmoid(design(d, model["spec"], drop) @ model["beta"])


def strike_values(level: str, season: int, pitches: pd.DataFrame | None = None) -> dict:
    """Strike-over-ball run value by count: re24 cache/committed fit; else computed from `pitches`; else 0.125 flat."""
    from oddsmarkets.baseball.models import re24
    w = None
    if pitches is not None:
        r = re24.statcast_season(level, season, pitches=pitches, with_wpa=False)
        w = r["counts"] if r else None
    else:
        s = re24.weights(level, season)
        w = (s or {}).get("counts")
    if not w:
        return {c: 0.125 for c in COUNTS}
    return {c: float(w["strike_value"].get(c, 0.125)) for c in COUNTS}


def framing_table(d: pd.DataFrame, model: dict, sv: dict) -> pd.DataFrame:
    p_full = predict(model, d)
    p_noc = predict(model, d, drop=("catcher",))
    d = d.assign(p=p_full, p0=p_noc, sv=d["count"].map(sv).astype(float).fillna(0.125))
    d["added"] = d["p"] - d["p0"]
    d["runs"] = d["added"] * d["sv"]
    d["resid"] = d["y"] - d["p0"]
    g = d[d["catcher"].notna()].groupby("catcher")
    t = pd.DataFrame({"called": g.size(), "strikes_added": g["added"].sum(), "runs": g["runs"].sum(),
                      "raw_above_x": g["resid"].sum(), "shadow_called": g["in_zone"].size()})
    t["effect"] = t.index.map(model["effects"]["catcher"]).astype(float)
    t["runs_per_season"] = t["runs"] / t["called"] * PER_SEASON
    t["strike_rate_added"] = t["strikes_added"] / t["called"]
    return t.drop(columns=["shadow_called"]).reset_index().rename(columns={"catcher": "pid"}).sort_values("runs", ascending=False)


def validate_framing(table: pd.DataFrame, season: int, min_called: int = 1000) -> dict:
    lb = _c.leaderboard("framing", season)
    if lb is None or not len(lb):
        return {"ok": False, "reason": "no Savant catcher-framing leaderboard cached"}
    idc = next((c for c in ("player_id", "id", "catcher_id", "entity_id") if c in lb), None)
    vc = next((c for c in ("runs_extra_strikes", "framing_runs", "rv_tot", "catcher_framing_runs", "runs") if c in lb), None)
    rc = next((c for c in ("strike_rate", "pct_tot", "shadow_zone_strike_rate") if c in lb), None)
    if not idc or not vc:
        return {"ok": False, "reason": f"unrecognised columns {list(lb.columns)[:12]}"}
    s = lb.groupby(lb[idc].astype(str))[[vc] + ([rc] if rc else [])].sum()
    m = table.set_index("pid").join(s, how="inner")
    m = m[m["called"] >= min_called]
    out = {"ok": True, "n": int(len(m)), "r_runs": _c.pearson(m["runs"], m[vc]), "col": vc}
    if rc:
        out["r_rate"] = _c.pearson(m["strike_rate_added"], m[rc])
    return out


def season_fit(level: str, season: int, pitches: pd.DataFrame | None = None, store: dict | None = None) -> dict | None:
    """(called pitches, model, strike values, framing table) for one season."""
    own = pitches is None
    if own:
        pitches = _c.load_pitches(level, season, COLUMNS)
        if pitches is None or not len(pitches):
            return None
        store = store or _c.load_store(level, season)
    d = called_pitches(pitches, store)
    model = fit(d)
    sv = strike_values(level, season, None if own else pitches)
    return {"called": d, "model": model, "sv": sv, "table": framing_table(d, model, sv)}


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    path = _c.pitch_path(level, season)
    if not path.exists():
        return {"ok": False, "reason": f"no pitch table for {level} {season}"}

    def build():
        r = season_fit(level, season)
        if r is None:
            return {"ok": False, "reason": "empty"}
        t = r["table"]
        return {"ok": True, "version": MODEL_VERSION, "n": r["model"]["n"], "strike_rate": r["model"]["strike_rate"],
                "catchers": _c.frame_rows(t), "validation": validate_framing(t, season),
                "strike_values": r["sv"]}
    return _c.cached("framing", f"{level}_{season}", _c.file_key(path, MODEL_VERSION), build, use_cache)


def surface(model: dict, stand: str = "R", count: str = "0-0", family: str = "FB", hands: str | None = None,
            nx: int = 41, nz: int = 45) -> dict:
    """League called-strike probability grid for the site (no random effects)."""
    xs = np.linspace(-1.8, 1.8, nx); zs = np.linspace(-0.6, 1.6, nz)
    X, Z = np.meshgrid(xs, zs, indexing="ij")
    hands = hands or f"R-{stand}"
    d = pd.DataFrame({"plate_x": X.ravel(), "zt": Z.ravel(), "stand": stand, "count": count, "family": family,
                      "hands": hands, "catcher": None, "ump": None, "pitcher": "", "batter": ""})
    p = predict(model, d, drop=("catcher", "ump", "pitcher", "batter")).reshape(X.shape)
    return {"x": xs.round(3).tolist(), "zt": zs.round(3).tolist(), "p": np.round(p, 3).tolist()}


def export_fits(level: str = "mlb", season: int | None = None) -> dict:
    """models/fitted/framing_<level>.json: surface/count/family/hands coefficients and spec (random effects
    are season outputs, not part of the committed model)."""
    seasons = _c.pitch_seasons(level)
    season = season or (seasons[-1] if seasons else None)
    if season is None:
        return {"ok": False, "reason": "no seasons"}
    r = season_fit(level, season)
    if r is None:
        return {"ok": False, "reason": "empty"}
    m = r["model"]
    ns = 2 * len(KX) * len(KZ) + len(COUNTS) + len(FAMILIES) + len(HANDS)
    out = {"version": MODEL_VERSION, "season": season, "kx": KX, "kz": KZ, "counts": COUNTS, "families": FAMILIES,
           "hands": HANDS, "beta_fixed": np.round(m["beta"][:ns], 5).tolist(), "strike_values": r["sv"],
           "sd": {"catcher": SD_CATCHER, "ump": SD_UMPIRE, "pitcher": SD_PITCHER, "batter": SD_BATTER}}
    _c.write_fit(f"framing_{level}", out)
    return {"ok": True, "season": season}
