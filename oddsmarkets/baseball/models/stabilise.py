"""
Stabilisation: the sample at which each metric becomes signal (split-half reliability 0.7).

For a metric measured on events of a unit (PA, ball in play, pitch, swing, called pitch, ...), for each
sample size n in GRID: split every player's season by game parity (his 1st, 3rd, 5th ... games against his 2nd,
4th ... games, in date order), take players with at least n events in each half, and correlate the means of the
first n events of each half across players (r_n, needs MIN_PLAYERS). Splitting by game rather than by event keeps
the shared pitcher, park, umpire and weather of one game out of both halves: the event-parity split (stab-3)
inflated r_n, so its k were 1.3-2x too small (docs/METRICS_SPEC.md, baseball stabilisation). Event tables without a
game id fall back to the event-parity split. Under the Spearman-Brown / beta-binomial model the reliability of an n-event mean is

    r(n) = n / (n + k)        so k = n (1 - r) / r,   and   n_0.7 = k * 0.7 / 0.3.

k is fitted by least squares on (n, r_n) over the grid (weighted by the number of players), per season,
then averaged over seasons weighted the same way; one season of pitches is in memory at a time. k is
also the shrinkage constant the other models use: a regressed rate = (sum + k * league) / (n + k)
(`shrink_k`); n_0.7 is shown on the glossary (`point`).
"""
from __future__ import annotations



import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _c

MODEL_VERSION = "stab-4"
GRID = [10, 20, 30, 50, 75, 100, 150, 200, 250, 300, 400, 500, 650, 800, 1000, 1300, 1600, 2000]
MIN_PLAYERS = 25
TARGET = 0.7
SWING = _c.SWINGS
WHIFF = {"swinging_strike", "swinging_strike_blocked", "foul_tip", "missed_bunt"}
DEFAULT_K = {"xwoba": 220.0, "woba": 330.0, "k_rate": 25.0, "bb_rate": 50.0}

# metric -> (unit, entity, description)
METRICS: dict[str, tuple[str, str, str]] = {
    "k_rate": ("pa", "batter", "Strikeout rate (per PA)"),
    "bb_rate": ("pa", "batter", "Walk rate (per PA)"),
    "hbp_rate": ("pa", "batter", "Hit-by-pitch rate"),
    "woba": ("pa", "batter", "wOBA"),
    "xwoba": ("pa", "batter", "xwOBA+ (ours)"),
    "savant_xwoba": ("pa", "batter", "Savant xwOBA"),
    "ev": ("bip", "batter", "Average exit velocity"),
    "la": ("bip", "batter", "Average launch angle"),
    "hard_hit": ("bip", "batter", "Hard-hit rate (EV >= 95)"),
    "barrel": ("bip", "batter", "Barrel rate"),
    "gb_rate": ("bip", "batter", "Ground-ball rate"),
    "fb_rate": ("bip", "batter", "Fly-ball rate"),
    "pull_rate": ("bip", "batter", "Pull rate (pull angle > 15 deg)"),
    "xwobacon": ("bip", "batter", "xwOBA+ on contact"),
    "savant_xwobacon": ("bip", "batter", "Savant xwOBA on contact"),
    "babip": ("bip", "batter", "Hit rate on balls in play (non-HR)"),
    "swing_rate": ("pitch", "batter", "Swing rate"),
    "chase_rate": ("pitch_out", "batter", "Chase rate (swings at pitches outside the zone)"),
    "zswing_rate": ("pitch_in", "batter", "Zone-swing rate"),
    "whiff_rate": ("swing", "batter", "Whiff rate (per swing)"),
    "bat_speed": ("swing", "batter", "Bat speed"),
    "p_k_rate": ("pa", "pitcher", "Strikeout rate (pitcher)"),
    "p_bb_rate": ("pa", "pitcher", "Walk rate (pitcher)"),
    "p_xwoba": ("pa", "pitcher", "xwOBA+ allowed"),
    "p_woba": ("pa", "pitcher", "wOBA allowed"),
    "p_gb_rate": ("bip", "pitcher", "Ground-ball rate (pitcher)"),
    "p_ev": ("bip", "pitcher", "Exit velocity allowed"),
    "p_whiff_rate": ("swing", "pitcher", "Whiff rate (pitcher, per swing)"),
    "p_csw": ("pitch", "pitcher", "Called strikes plus whiffs per pitch"),
    "p_zone_rate": ("pitch", "pitcher", "Zone rate"),
    "p_velo": ("pitch_ff", "pitcher", "Four-seam velocity"),
    "c_frame": ("called", "catcher", "Called strikes above a location-only expectation (catcher)"),
}


# ============================================================================ event tables

def event_tables(pitches: pd.DataFrame, bip_x: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Per-unit event frames with columns entity ids (batter, pitcher, catcher), t (order) and metric values."""
    p = pitches.reset_index(drop=True)
    p["t"] = np.arange(len(p))
    p["g"] = p["game_pk"].to_numpy() if "game_pk" in p else np.nan
    out: dict[str, pd.DataFrame] = {}
    ev = p["events"].astype(object).fillna("").astype(str)
    den = pd.to_numeric(p.get("woba_denom"), errors="coerce").fillna(0.0)
    last = p[(ev != "") & (den > 0)].copy()
    lev = last["events"].astype(str)
    pa = pd.DataFrame({"batter": last["batter"].map(_sid), "pitcher": last["pitcher"].map(_sid), "t": last["t"], "g": last["g"]})
    pa["k_rate"] = lev.isin(_c.K_EVENTS).astype(float).to_numpy()
    pa["bb_rate"] = lev.isin(_c.BB_EVENTS).astype(float).to_numpy()
    pa["hbp_rate"] = lev.isin(_c.HBP_EVENTS).astype(float).to_numpy()
    pa["woba"] = last["woba_value"].astype(float).fillna(0.0).to_numpy()
    sv = last.get("estimated_woba_using_speedangle")
    is_bip = lev.isin(_c.BIP_EVENTS).to_numpy()
    pa["savant_xwoba"] = np.where(is_bip, pd.to_numeric(sv, errors="coerce").fillna(last["woba_value"]).to_numpy() if sv is not None else np.nan,
                                  pa["woba"])
    if bip_x is not None and len(bip_x):
        m = bip_x.drop_duplicates(["game_pk", "at_bat_number"]).set_index(["game_pk", "at_bat_number"])["xwoba"]
        x = m.reindex(pd.MultiIndex.from_frame(last[["game_pk", "at_bat_number"]])).to_numpy()
        pa["xwoba"] = np.where(is_bip, x, pa["woba"])
    else:
        pa["xwoba"] = np.nan
    for c in ("k_rate", "bb_rate", "woba", "xwoba"):
        pa[f"p_{c}"] = pa[c]
    out["pa"] = pa
    b = last[is_bip & last["launch_speed"].notna().to_numpy()].copy()
    bb = pd.DataFrame({"batter": b["batter"].map(_sid), "pitcher": b["pitcher"].map(_sid), "t": b["t"], "g": b["g"]})
    ls = b["launch_speed"].astype(float).to_numpy(); la = b["launch_angle"].astype(float).to_numpy()
    bb["ev"] = ls; bb["p_ev"] = ls
    bb["la"] = la
    bb["hard_hit"] = (ls >= 95).astype(float)
    lsa = pd.to_numeric(b.get("launch_speed_angle"), errors="coerce") if "launch_speed_angle" in b else None
    bb["barrel"] = (lsa.to_numpy() == 6).astype(float) if lsa is not None and lsa.notna().any() else _barrel(ls, la)
    bt = b["bb_type"].astype(str).to_numpy()
    bb["gb_rate"] = (bt == "ground_ball").astype(float); bb["p_gb_rate"] = bb["gb_rate"]
    bb["fb_rate"] = (bt == "fly_ball").astype(float)
    pull = _c.pull_angle(_c.spray_angle(b["hc_x"], b["hc_y"]), b["stand"])
    bb["pull_rate"] = np.where(np.isfinite(pull), (pull > 15).astype(float), np.nan)
    e = b["events"].astype(str)
    nonhr = e != "home_run"
    bb["babip"] = np.where(nonhr, e.isin(["single", "double", "triple"]).astype(float), np.nan)
    bb["savant_xwobacon"] = pd.to_numeric(b.get("estimated_woba_using_speedangle"), errors="coerce").to_numpy() \
        if "estimated_woba_using_speedangle" in b else np.nan
    if bip_x is not None and len(bip_x):
        m = bip_x.drop_duplicates(["game_pk", "at_bat_number"]).set_index(["game_pk", "at_bat_number"])["xwoba"]
        bb["xwobacon"] = m.reindex(pd.MultiIndex.from_frame(b[["game_pk", "at_bat_number"]])).to_numpy()
    else:
        bb["xwobacon"] = np.nan
    out["bip"] = bb
    d = p["description"].astype(str)
    sw = d.isin(SWING).to_numpy()
    zone = pd.to_numeric(p.get("zone"), errors="coerce").to_numpy() if "zone" in p else np.full(len(p), np.nan)
    if np.isnan(zone).all() and "plate_x" in p:
        inz = (p["plate_x"].abs() <= 0.83) & (p["plate_z"] >= p["sz_bot"].fillna(1.55) - 0.12) & (p["plate_z"] <= p["sz_top"].fillna(3.4) + 0.12)
        inz = inz.to_numpy()
    else:
        inz = (zone >= 1) & (zone <= 9)
    pt = pd.DataFrame({"batter": p["batter"].map(_sid), "pitcher": p["pitcher"].map(_sid), "t": p["t"], "g": p["g"]})
    pt["swing_rate"] = sw.astype(float)
    pt["p_csw"] = (d.isin(WHIFF) | (d == "called_strike")).astype(float).to_numpy()
    pt["p_zone_rate"] = inz.astype(float)
    out["pitch"] = pt
    out["pitch_out"] = pt[~inz].assign(chase_rate=lambda x: x["swing_rate"])
    out["pitch_in"] = pt[inz].assign(zswing_rate=lambda x: x["swing_rate"])
    s = p[sw]
    swg = pd.DataFrame({"batter": s["batter"].map(_sid), "pitcher": s["pitcher"].map(_sid), "t": s["t"], "g": s["g"]})
    swg["whiff_rate"] = s["description"].astype(str).isin(WHIFF).astype(float).to_numpy()
    swg["p_whiff_rate"] = swg["whiff_rate"]
    swg["bat_speed"] = pd.to_numeric(s.get("bat_speed"), errors="coerce").to_numpy() if "bat_speed" in s else np.nan
    out["swing"] = swg
    if "pitch_type" in p and "release_speed" in p:
        f = p[p["pitch_type"].astype(str) == "FF"]
        out["pitch_ff"] = pd.DataFrame({"pitcher": f["pitcher"].map(_sid), "t": f["t"], "g": f["g"],
                                        "p_velo": f["release_speed"].astype(float).to_numpy()})
    if "fielder_2" in p and "plate_x" in p:
        c = p[d.isin(_c.CALLED) & p["plate_x"].notna() & p["plate_z"].notna()].copy()
        zt = (c["plate_z"] - c["sz_bot"].fillna(1.55)) / (c["sz_top"].fillna(3.4) - c["sz_bot"].fillna(1.55)).clip(lower=0.8)
        cell = (np.clip(((c["plate_x"] + 2) / 0.1).astype(int), 0, 40) * 100 + np.clip(((zt + 1) / 0.08).astype(int), 0, 50)
                + 10000 * c["stand"].astype(str).str.startswith("L").astype(int))
        y = (c["description"].astype(str) == "called_strike").astype(float)
        rate = y.groupby(cell).transform("mean")
        out["called"] = pd.DataFrame({"catcher": c["fielder_2"].map(_sid), "t": c["t"], "g": c["g"], "c_frame": (y - rate).to_numpy()})
    return out


def _sid(x):
    try:
        return str(int(x))
    except (TypeError, ValueError):
        return None


def _barrel(ls, la) -> np.ndarray:
    """Savant's barrel definition: EV >= 98 with a launch-angle window that widens with EV."""
    ls = np.asarray(ls, float); la = np.asarray(la, float)
    lo = np.clip(26 - (ls - 98) * np.where(ls < 100, 1.0, 1.2), 8, 26)
    hi = np.clip(30 + (ls - 98) * np.where(ls < 100, 1.0, 1.2), 30, 50)
    return ((ls >= 98) & (la >= lo) & (la <= hi)).astype(float)


# ============================================================================ split-half

def split_half_curve(ev: pd.DataFrame, entity: str, metric: str, grid: list[int] = GRID,
                     min_players: int = MIN_PLAYERS, by: str = "game") -> list[list[float]]:
    """[[n, r_n, players], ...]: the mean of the first n events in a player's odd games against the first n in his
    even games (`by="game"`, the default, when the frame has a game id `g`), else odd against even events of his
    first 2n (`by="event"`, the stab-3 split)."""
    use_game = by == "game" and "g" in ev and ev["g"].notna().any()
    cols = [entity, "t", metric] + (["g"] if use_game else [])
    d = ev[cols].dropna()
    d = d[d[entity].notna()]
    if not len(d):
        return []
    d = d.sort_values([entity, "t"], kind="mergesort")
    if use_game:
        first = d.groupby([entity, "g"], sort=False)["t"].transform("min")
        d["half"] = d.assign(_f=first).groupby(entity)["_f"].rank(method="dense").astype(int).sub(1) % 2
        d["rank"] = d.groupby([entity, "half"]).cumcount()
        cnt = d.groupby([entity, "half"]).size().unstack(fill_value=0)
        cnt = cnt.min(axis=1) if cnt.shape[1] == 2 else pd.Series(0, index=cnt.index)
    else:
        d["half"] = d.groupby(entity).cumcount() % 2
        d["rank"] = d.groupby(entity).cumcount() // 2
        cnt = d.groupby(entity).size() // 2
    out = []
    for n in grid:
        ok = cnt[cnt >= n].index
        if len(ok) < min_players:
            break
        s = d[d[entity].isin(ok) & (d["rank"] < n)]
        h = s.groupby([entity, "half"])[metric].mean().unstack()
        r = _c.pearson(h[0], h[1])
        if r is not None:
            out.append([float(n), float(r), int(len(ok))])
    return out


def fit_k(curve: list[list[float]]) -> float | None:
    """Least-squares k in r = n / (n + k) over the curve (weighted by players)."""
    pts = [(n, r, w) for n, r, w in curve if 0.02 < r < 0.995]
    if not pts:
        return None
    ks = np.logspace(-1, 4.5, 600)
    best, bk = np.inf, None
    for k in ks:
        err = sum(w * (r - n / (n + k)) ** 2 for n, r, w in pts)
        if err < best:
            best, bk = err, k
    return float(bk)


def season_stability(pitches: pd.DataFrame, bip_x: pd.DataFrame | None = None, metrics: list[str] | None = None) -> dict:
    tabs = event_tables(pitches, bip_x)
    out = {}
    for m in (metrics or list(METRICS)):
        unit, ent, _ = METRICS[m]
        ev = tabs.get(unit)
        if ev is None or m not in ev or ent not in ev or ev[m].isna().all():
            continue
        curve = split_half_curve(ev, ent, m)
        k = fit_k(curve)
        out[m] = {"curve": curve, "k": k, "players": int(max([c[2] for c in curve], default=0))}
    return out


def combine(seasons: dict[str, dict]) -> dict:
    res = {}
    for m, (unit, ent, desc) in METRICS.items():
        ks, ws = [], []
        for s, r in seasons.items():
            x = r.get(m)
            if x and x.get("k"):
                ks.append(x["k"]); ws.append(max(x.get("players", 1), 1))
        if not ks:
            continue
        k = float(np.exp(np.average(np.log(ks), weights=ws)))
        res[m] = {"k": round(k, 1), "n70": round(k * TARGET / (1 - TARGET), 1), "unit": unit, "entity": ent,
                  "label": desc, "seasons": len(ks)}
    return res


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    path = _c.pitch_path(level, season)
    if not path.exists():
        return {}

    def build():
        from oddsmarkets.baseball.models import xwoba
        cols = ["game_pk", "batter", "pitcher", "stand", "events", "description", "woba_value", "woba_denom",
                "estimated_woba_using_speedangle", "launch_speed", "launch_angle", "launch_speed_angle", "bb_type",
                "hc_x", "hc_y", "zone", "plate_x", "plate_z", "sz_top", "sz_bot", "bat_speed", "pitch_type",
                "release_speed", "fielder_2"]
        p = _c.load_pitches(level, season, cols)
        if p is None or not len(p):
            return {}
        bip = None
        try:
            bp = xwoba.bip_cache_path(level, season)
            bip = pd.read_parquet(bp) if bp.exists() else None
        except Exception:
            bip = None
        return season_stability(p, bip)
    return _c.cached("stabilise", f"{level}_{season}", _c.file_key(path, MODEL_VERSION), build, use_cache)


def table(level: str = "mlb", seasons: list[int] | None = None) -> dict:
    seasons = seasons or _c.pitch_seasons(level)
    per = {str(s): for_season(level, s) for s in seasons}
    return combine({k: v for k, v in per.items() if v})


def _fitted(level: str, kind: str = "game") -> dict:
    """The committed fit's metrics: "game" (game-parity split, stab-4: the display shrinkage) or "event" (the
    event-parity stab-3 values, kept frozen in `metrics_event` for the models validated with them: the projection
    regression constants and WAR's xwOBA blend, until a promotion backtest moves them)."""
    f = _c.read_fit(f"stabilise_{level}") or {}
    if kind == "event":
        return f.get("metrics_event") or f.get("metrics") or {}
    return f.get("metrics") or {}


def shrink_k(metric: str, level: str = "mlb", kind: str = "game") -> float:
    m = _fitted(level, kind).get(metric)
    return float(m["k"]) if m and m.get("k") else DEFAULT_K.get(metric, 200.0)


def point(metric: str, level: str = "mlb") -> float:
    """n at which split-half reliability reaches 0.7 (from the committed fit; default from DEFAULT_K)."""
    m = _fitted(level).get(metric)
    if m and m.get("n70"):
        return float(m["n70"])
    return DEFAULT_K.get(metric, 200.0) * TARGET / (1 - TARGET)


def export_fits(level: str = "mlb", seasons: list[int] | None = None) -> dict:
    t = table(level, seasons)
    old = _c.read_fit(f"stabilise_{level}") or {}
    # the event-parity values the projections and WAR were validated with: carried over unchanged
    event = old.get("metrics_event") or (old.get("metrics") if old.get("version") == "stab-3" else None) or {}
    out = {"version": MODEL_VERSION, "target": TARGET, "split": "game", "metrics": t, "metrics_event": event}
    _c.write_fit(f"stabilise_{level}", out)
    return out
