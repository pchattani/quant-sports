"""
Tunneling: how alike two consecutive pitches of a plate appearance look at the batter's decision point
(DECISION_S = 167 ms before the plate) against how far apart they finish.

For each pair (previous pitch -> this pitch, same plate appearance; prep.py):
    dp_dist     distance (in) between the two trajectories at the decision point
    plate_dist  distance (in) between them at the front of the plate
    tunnel      E[dp_dist | plate_dist] - dp_dist, the league's expected decision-point gap for that plate
                gap (binned means, interpolated) minus the actual: positive = the pair stayed together longer
                than pairs that split as much usually do
    ratio       plate_dist / dp_dist

Per pitcher and pair type (e.g. FF->SL): pairs, mean distances, mean tunnel and a tunnel index scaled to
100 + 10 z over pitcher-pairs with >= MIN_PAIRS. `whiff_effect` shows the relationship with whiffs on the
second pitch: whiff rate by tunnel decile, and a logistic regression of whiff | swing on standardised
tunnel, controlling for the second pitch's stuff whiff probability (when given), zone and pitch family.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io, prep

MODEL_VERSION = "tunnel-2"
MIN_PAIRS = 30
BINS = np.array([0, 3, 6, 9, 12, 15, 18, 21, 24, 28, 32, 38, 46, 60, 200], float)


def pairs(df: pd.DataFrame) -> pd.DataFrame:
    """Rows of an enriched season that have a previous pitch in the PA, with the pair fields."""
    m = (df["has_prev"] == 1) & df["dp_dist"].notna() & df["plate_dist"].notna() & (df["prev_pt"] >= 0) & (df["pt"] >= 0)
    keep = [c for c in ("game_pk", "game_date", "pitcher", "batter", "pitch_type", "family", "fam", "pt", "prev_pt",
                        "dp_dist", "plate_dist", "swing", "whiff", "in_zone", "p_whiff", "rv_dn") if c in df]
    p = df.loc[m, keep].copy()
    p["pair"] = [f"{_io.PITCH_TYPES[a]}>{_io.PITCH_TYPES[b]}" for a, b in zip(p["prev_pt"].astype(int), p["pt"].astype(int))]
    return p


def curve(p: pd.DataFrame) -> dict:
    """League E[dp_dist | plate_dist] as bin means (at bin mean plate_dist)."""
    b = np.digitize(p["plate_dist"].to_numpy(float), BINS) - 1
    g = pd.DataFrame({"b": b, "x": p["plate_dist"].to_numpy(float), "y": p["dp_dist"].to_numpy(float)}).groupby("b").agg(
        x=("x", "mean"), y=("y", "mean"), n=("y", "size"))
    g = g[g["n"] >= 20]
    return {"x": g["x"].round(3).tolist(), "y": g["y"].round(3).tolist()}


def add_tunnel(p: pd.DataFrame, cv: dict) -> pd.DataFrame:
    exp = np.interp(p["plate_dist"].to_numpy(float), cv["x"], cv["y"]) if cv["x"] else p["dp_dist"].mean()
    p["tunnel"] = (exp - p["dp_dist"].to_numpy(float)).astype(np.float32)
    p["ratio"] = (p["plate_dist"] / p["dp_dist"].clip(lower=0.5)).astype(np.float32)
    return p


def pitcher_pairs(p: pd.DataFrame, min_pairs: int = MIN_PAIRS) -> pd.DataFrame:
    g = p.groupby(["pitcher", "pair"]).agg(n=("tunnel", "size"), dp=("dp_dist", "mean"), plate=("plate_dist", "mean"),
                                           tunnel=("tunnel", "mean"), ratio=("ratio", "mean"),
                                           swings=("swing", "sum"), whiffs=("whiff", "sum")).reset_index()
    g["whiff"] = g["whiffs"] / g["swings"].replace(0, np.nan)
    q = g[g["n"] >= min_pairs]
    mu, sd = (q["tunnel"].mean(), q["tunnel"].std()) if len(q) > 5 else (g["tunnel"].mean(), g["tunnel"].std() or 1.0)
    g["index"] = 100 + 10 * (g["tunnel"] - mu) / (sd or 1.0)
    return g


def pitcher_index(p: pd.DataFrame, pp: pd.DataFrame, min_pairs: int = MIN_PAIRS) -> pd.DataFrame:
    """Per pitcher: pair-weighted tunnel, its index, and the best pair."""
    q = pp[pp["n"] >= min_pairs]
    g = q.groupby("pitcher").apply(lambda x: pd.Series({"pairs": x["n"].sum(), "tunnel": np.average(x["tunnel"], weights=x["n"]),
                                                        "index": np.average(x["index"], weights=x["n"]),
                                                        "best_pair": x.sort_values("index").iloc[-1]["pair"]}),
                                   include_groups=False) if len(q) else pd.DataFrame()
    return g


def whiff_effect(p: pd.DataFrame) -> dict:
    s = p[p["swing"].astype(bool)].copy()
    if "p_whiff" in s and s["p_whiff"].notna().mean() >= 0.9:
        s = s[s["p_whiff"].notna()]
    if len(s) < 200:
        return {"n": int(len(s))}
    s["dec"] = pd.qcut(s["tunnel"], 10, labels=False, duplicates="drop")
    tab = s.groupby("dec").agg(tunnel=("tunnel", "mean"), whiff=("whiff", "mean"), n=("whiff", "size"))
    z = ((s["tunnel"] - s["tunnel"].mean()) / s["tunnel"].std()).to_numpy(float)
    cols = [np.ones(len(s)), z, s["in_zone"].to_numpy(float)]
    names = ["const", "tunnel_z", "in_zone"]
    for f in (1, 2):
        cols.append((s["fam"].to_numpy() == f).astype(float))
        names.append(f"fam{f}")
    if "p_whiff" in s and s["p_whiff"].notna().all():
        pw = np.clip(s["p_whiff"].to_numpy(float), 1e-4, 1 - 1e-4)
        cols.append(np.log(pw / (1 - pw)))
        names.append("logit_stuff_whiff")
    r = _io.logit_fit(np.column_stack(cols), s["whiff"].to_numpy(float))
    return {"n": int(len(s)), "deciles": tab.reset_index(drop=True).round(4).to_dict("list"),
            "logit": {n: {"b": float(b), "se": float(e)} for n, b, e in zip(names, r["beta"], r["se"])},
            "tunnel_sd_in": float(s["tunnel"].std())}


def analyse(df: pd.DataFrame, min_pairs: int = MIN_PAIRS) -> dict[str, Any]:
    p = pairs(df)
    cv = curve(p)
    p = add_tunnel(p, cv)
    pp = pitcher_pairs(p, min_pairs)
    return {"pairs": p, "curve": cv, "pitcher_pairs": pp, "pitchers": pitcher_index(p, pp, min_pairs),
            "whiff": whiff_effect(p)}


def for_season(level: str, season: int, use_cache: bool = True, with_stuff: bool = True) -> dict:
    """{"ok","level","season","curve","whiff": {...}, "pitchers": {pid: {pairs, tunnel, index, best_pair,
    by_pair: {pair: {n, dp, plate, tunnel, index, whiff}}}}, "league_pairs": {pair: {...}}}."""
    try:
        src = _io.pitch_path(level, season)
        if not src.exists():
            return {"ok": False, "reason": "no pitch table"}
        key = _io.file_key(MODEL_VERSION, src, with_stuff)

        def build():
            df = prep.prepared(level, season)
            if with_stuff:
                from oddsmarkets.baseball.models import stuff
                sm = stuff.model_for(level, season, use_cache)
                if sm.get("ok"):
                    u = stuff.usable(df)
                    df = df[u].copy()
                    df["p_whiff"] = stuff.predict_components(df, sm)["whiff"]
            a = analyse(df)
            del df
            pp = a["pitcher_pairs"]
            by: dict[str, dict] = {}
            for r in pp[pp["n"] >= MIN_PAIRS].itertuples():
                by.setdefault(str(r.pitcher), {})[r.pair] = {"n": int(r.n), "dp": r.dp, "plate": r.plate, "tunnel": r.tunnel,
                                                             "index": r.index, "whiff": r.whiff}
            pit = {str(pid): {**{k: v for k, v in row.items()}, "by_pair": by.get(str(pid), {})}
                   for pid, row in a["pitchers"].to_dict("index").items()} if len(a["pitchers"]) else {}
            lg = a["pairs"].groupby("pair").agg(n=("tunnel", "size"), dp=("dp_dist", "mean"), plate=("plate_dist", "mean"),
                                                whiff=("whiff", "mean"))
            lg = lg[lg["n"] >= 500]
            return _io.clean({"ok": True, "level": level, "season": season, "version": MODEL_VERSION, "curve": a["curve"],
                              "whiff": a["whiff"], "pitchers": pit, "league_pairs": lg.to_dict("index")}, 4)

        return _io.cached("tunneling", f"season_{level}_{season}", key, build, use_cache)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
