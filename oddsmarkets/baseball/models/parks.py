"""
Park factors (our own), by batter hand and batted-ball outcome, multi-year and regressed, with
dimension and weather effects.

Contact factors come from xwOBA+ residuals: every ball in play has a park-neutral expectation
(xwoba.py's `xwoba_n` and class probabilities under league-standard fences, walls, elevation and an
open roof, from its exit velocity, launch angle, spray and the batter's speed). For park p, hand h
and outcome c in {1B, 2B, 3B, HR}:

    F_c(p, h) = (O + K_c) / (E + K_c),   O = observed count, E = sum of neutral probabilities

over the last YEARS seasons (one season's aggregates in memory at a time), with K_c pseudo-events
of regression (K table). F_woba is the same on wOBA-on-contact points: (sum woba + K) / (sum xwoba_n + K)
with K = K_WOBA * mean. Because the expectation already holds contact quality fixed, these factors
separate the park from the hitters who play there (no home/road split needed).

Runs, strikeouts and walks use the classic home/road method on team games:
F_runs = (runs per game in home games / runs per game in road games), regressed with G0 games,
and the same for K and BB rates per PA (K_PA pseudo-PAs). Factors are ratios (1.00 = neutral; the
index form x 100 is also returned).

Dimensions: across parks, the contact factors are regressed on mean fence distance, the
left/right-field fence and wall heights and elevation (least squares, reported as coefficients).
Weather: on air balls (launch angle 15-45, exit velocity >= 90) the carry residual
(hit_distance_sc minus the physics carry, scaled to the season mean) and the HR residual
(HR - neutral P(HR)) are regressed on temperature (F) and the outward wind component (mph;
"Out To CF" = 1, "Out To LF/RF" = 0.7, "In From ..." negative, cross winds 0), with park fixed
effects removed (residuals centred within park). Domes and closed roofs are excluded.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _c

MODEL_VERSION = "parks-3"
YEARS = 3
K = {"1B": 1000.0, "2B": 300.0, "3B": 60.0, "HR": 250.0}
K_WOBA = 1500.0          # pseudo balls in play for the wOBA-on-contact factor
G0 = 160.0               # pseudo games for the run factor
K_PA = 6000.0            # pseudo PAs for K and BB factors
OUTCOMES = ["1B", "2B", "3B", "HR"]
INDOOR = ("dome", "roof closed", "closed")


def parse_wind(w: Any) -> float:
    """Outward wind component (mph) from strings like '12 mph, Out To CF'."""
    if not w or not isinstance(w, str):
        return 0.0
    m = re.search(r"(\d+)\s*mph", w)
    sp = float(m.group(1)) if m else 0.0
    s = w.lower()
    if "out to" in s:
        return sp * (1.0 if "cf" in s else 0.7)
    if "in from" in s:
        return -sp * (1.0 if "cf" in s else 0.7)
    return 0.0


def _indoor(g: dict, venue: dict | None) -> bool:
    cond = str(((g or {}).get("weather") or {}).get("cond") or "").lower()
    roof = str((venue or {}).get("roof") or "").lower()
    return any(k in cond for k in INDOOR) or roof in ("dome", "fixed")


# ============================================================================ season aggregates

def season_aggregates(bip: pd.DataFrame, pa: pd.DataFrame | None, store: dict | None, games: pd.DataFrame | None = None) -> dict:
    """One season's sums: contact (by park x hand x outcome), home/road runs, K, BB and weather rows."""
    out: dict[str, Any] = {"contact": {}, "homeroad": {}, "weather": None}
    if bip is not None and len(bip):
        b = bip.copy()
        b["park"] = b["home_team"].astype(str)
        b["hand"] = b["stand"].astype(str).str[:1]
        ev = b["events"].astype(str)
        for c, e in zip(OUTCOMES, ("single", "double", "triple", "home_run")):
            b[f"o_{c}"] = (ev == e).astype(float)
        pn = {c: f"pn_{c}" for c in OUTCOMES}
        if not all(v in b for v in pn.values()):
            for c in OUTCOMES:
                b[pn[c]] = b.get(f"p_{c}", np.nan)
        g = b.groupby(["park", "hand"])
        agg = pd.DataFrame({"n": g.size(), "woba": g["woba_value"].sum(), "xwoba_n": g["xwoba_n"].sum()})
        for c in OUTCOMES:
            agg[f"o_{c}"] = g[f"o_{c}"].sum()
            agg[f"e_{c}"] = g[pn[c]].sum()
        out["contact"] = {f"{p}|{h}": r.to_dict() for (p, h), r in agg.iterrows()}
    if pa is not None and len(pa):
        p = pa.copy()
        home_bat = p["inning_topbot"].astype(str).str.lower().str.startswith("b")
        p["bat_team"] = np.where(home_bat, p["home_team"], p["away_team"])
        p["k"] = (p["cls"] == "K").astype(float)
        p["bb"] = p["cls"].isin(["BB"]).astype(float)
        p["runs"] = p["runs_pa"].astype(float) if "runs_pa" in p else (p["post_bat_score"].astype(float) - p["bat_score"].astype(float))
        hr = {}
        for team in sorted(set(p["home_team"].astype(str)) | set(p["away_team"].astype(str))):
            h = p[p["home_team"].astype(str) == team]
            r = p[(p["away_team"].astype(str) == team)]
            hr[team] = {"h_games": int(h["game_pk"].nunique()), "h_runs": float(h["runs"].sum()), "h_pa": int(len(h)),
                        "h_k": float(h["k"].sum()), "h_bb": float(h["bb"].sum()),
                        "r_games": int(r["game_pk"].nunique()), "r_runs": float(r["runs"].sum()), "r_pa": int(len(r)),
                        "r_k": float(r["k"].sum()), "r_bb": float(r["bb"].sum())}
        out["homeroad"] = hr
    out["weather"] = weather_rows(bip, store)
    return out


def weather_rows(bip: pd.DataFrame | None, store: dict | None) -> list | None:
    """Air-ball residual rows [park, temp, wind_out, carry_resid, hr_resid] for the weather regression."""
    if bip is None or not len(bip) or not store or "hit_distance_sc" not in bip:
        return None
    games = store.get("games") or {}
    venues = store.get("venues") or {}
    b = bip[(bip["launch_angle"].between(15, 45)) & (bip["launch_speed"] >= 90)].copy()
    if not len(b):
        return None
    meta = {}
    for k, g in games.items():
        w = (g or {}).get("weather") or {}
        v = venues.get(str((g or {}).get("venue")))
        try:
            t = float(w.get("temp"))
        except (TypeError, ValueError):
            t = np.nan
        meta[int(k)] = (t, parse_wind(w.get("wind")), _indoor(g, v))
    m = b["game_pk"].astype(np.int64).map(meta)
    ok = m.notna()
    b = b[ok]
    m = m[ok]
    if not len(b):
        return None
    b["temp"] = [x[0] for x in m]
    b["wind"] = [x[1] for x in m]
    b = b[~np.array([x[2] for x in m], bool) & b["temp"].notna()]
    fl = _c.flight(b["launch_speed"].to_numpy(float), b["launch_angle"].to_numpy(float))
    carry = fl["dist"]
    d = b["hit_distance_sc"].astype(float).to_numpy()
    scale = np.nanmean(d) / max(np.nanmean(carry), 1e-6)
    b["carry_resid"] = d - carry * scale
    phr = b["p_HR"] if "p_HR" in b else 0.0
    b["hr_resid"] = (b["events"].astype(str) == "home_run").astype(float) - phr
    b = b[np.isfinite(b["carry_resid"])]
    return b[["home_team", "temp", "wind", "carry_resid", "hr_resid"]].astype({"home_team": str}).values.tolist()


def season_for(level: str, season: int, use_cache: bool = True) -> dict:
    """Cached per-season aggregates (needs the xwOBA+ batted-ball cache, built on demand)."""
    path = _c.pitch_path(level, season)
    if not path.exists():
        return {}

    def build():
        from oddsmarkets.baseball.models import re24, xwoba
        bip = xwoba.load_bip(level, season)
        store = _c.load_store(level, season)
        p = _c.load_pitches(level, season, ["inning", "inning_topbot", "outs_when_up", "bat_score", "fld_score",
                                            "post_bat_score", "on_1b", "on_2b", "on_3b", "events", "home_team",
                                            "away_team", "batter", "pitcher", "stand", "p_throws", "game_date"])
        pa = re24.prepare_pa(_c.pa_table(p)) if p is not None and len(p) else None
        if bip is not None and "hit_distance_sc" not in bip:
            hd = _c.load_pitches(level, season, ["hit_distance_sc", "events"])
            if hd is not None:
                last = hd[hd["events"].astype(object).notna()].drop_duplicates(["game_pk", "at_bat_number"], keep="last")
                bip = bip.merge(last[["game_pk", "at_bat_number", "hit_distance_sc"]], on=["game_pk", "at_bat_number"], how="left")
        bip = _neutral_classes(bip)
        return season_aggregates(bip, pa, store)
    return _c.cached("parks", f"{level}_{season}", _c.file_key(path, MODEL_VERSION, "v2"), build, use_cache)


def _neutral_classes(bip: pd.DataFrame | None) -> pd.DataFrame | None:
    """Park-neutral class probabilities: the cached BIP table holds park-specific p_*; rescale them by
    xwoba_n / xwoba so expected counts are neutral (exact for the wOBA total, proportional per class)."""
    if bip is None or not len(bip):
        return bip
    if all(f"pn_{c}" in bip for c in OUTCOMES):
        return bip
    b = bip.copy()
    ratio = (b["xwoba_n"] / b["xwoba"].replace(0, np.nan)).fillna(1.0).clip(0.5, 2.0)
    for c in OUTCOMES:
        b[f"pn_{c}"] = b[f"p_{c}"] * ratio
    return b


# ============================================================================ multi-year factors

def combine(aggs: list[dict], store: dict | None = None) -> dict:
    """Regressed multi-year factors per park from season aggregates."""
    contact: dict[str, dict] = {}
    homeroad: dict[str, dict] = {}
    for a in aggs:
        for k, r in (a.get("contact") or {}).items():
            acc = contact.setdefault(k, {})
            for f, v in r.items():
                acc[f] = acc.get(f, 0.0) + float(v or 0.0)
        for t, r in (a.get("homeroad") or {}).items():
            acc = homeroad.setdefault(t, {})
            for f, v in r.items():
                acc[f] = acc.get(f, 0.0) + float(v or 0.0)
    parks: dict[str, dict] = {}
    by_park: dict[str, dict] = {}
    for k, r in contact.items():
        p, h = k.split("|")
        by_park.setdefault(p, {})[h] = r
    teams = {t.get("abbr"): (tid, t) for tid, t in ((store or {}).get("teams") or {}).items()}
    venues = (store or {}).get("venues") or {}
    for p in sorted(set(by_park) | set(homeroad)):
        hands = by_park.get(p, {})
        tot: dict[str, float] = {}
        for r in hands.values():
            for f, v in r.items():
                tot[f] = tot.get(f, 0.0) + v
        fac = _factors(tot)
        hr = homeroad.get(p)
        if hr and hr.get("h_games") and hr.get("r_games"):
            hg, rg = hr["h_games"], hr["r_games"]
            ratio = (hr["h_runs"] / hg) / max(hr["r_runs"] / rg, 1e-9)
            fac["runs"] = (hg * ratio + G0) / (hg + G0)
            for kk in ("k", "bb"):
                rh = hr[f"h_{kk}"] / max(hr["h_pa"], 1)
                rr = hr[f"r_{kk}"] / max(hr["r_pa"], 1)
                ratio = rh / max(rr, 1e-9)
                fac[kk.upper()] = (hr["h_pa"] * ratio + K_PA) / (hr["h_pa"] + K_PA)
        tid, t = teams.get(p, (None, {}))
        v = venues.get(str((t or {}).get("venue"))) if t else None
        parks[p] = {"abbr": p, "team": tid, "venue": (t or {}).get("venue"), "name": (v or {}).get("name"),
                    "dims": (v or {}).get("dims"), "walls": (v or {}).get("walls"), "elev_ft": (v or {}).get("elev_ft"),
                    "roof": (v or {}).get("roof"), "factors": fac,
                    "index": {k2: round(100 * v2, 1) for k2, v2 in fac.items() if v2 is not None},
                    "by_hand": {h: _factors(r) for h, r in hands.items()}, "n_bip": int(tot.get("n", 0))}
    return parks


def _factors(r: dict) -> dict:
    out = {}
    for c in OUTCOMES:
        o, e = r.get(f"o_{c}", 0.0), r.get(f"e_{c}", 0.0)
        out[c] = (o + K[c]) / (e + K[c]) if e > 0 else 1.0
    n = r.get("n", 0.0)
    if n:
        mean = r.get("xwoba_n", 0.0) / n
        kk = K_WOBA * mean
        out["woba_con"] = (r.get("woba", 0.0) + kk) / (r.get("xwoba_n", 0.0) + kk)
    return out


def dimension_effects(parks: dict) -> dict:
    """Least squares across parks of contact factors on fence distance, wall height and elevation."""
    rows = []
    for p, v in parks.items():
        d = v.get("dims") or {}
        try:
            mean_fence = float(np.mean([d[k] for k in ("lf", "lcf", "cf", "rcf", "rf")]))
        except (KeyError, TypeError):
            continue
        walls = v.get("walls") or {}
        wl = np.mean([float(walls.get(k, 8) if not isinstance(walls.get(k), dict) else 8) for k in ("lf", "cf", "rf")]) if walls else 8.0
        rows.append([mean_fence, wl, float(v.get("elev_ft") or 0), v["factors"].get("HR", 1.0), v["factors"].get("woba_con", 1.0),
                     v["factors"].get("2B", 1.0)])
    if len(rows) < 6:
        return {"n": len(rows)}
    a = np.array(rows)
    X = np.column_stack([np.ones(len(a)), (a[:, 0] - 375) / 10, (a[:, 1] - 8) / 10, a[:, 2] / 1000])
    out = {"n": len(rows), "terms": ["intercept", "per 10 ft of mean fence", "per 10 ft of wall", "per 1000 ft elevation"]}
    for j, name in ((3, "HR"), (4, "woba_con"), (5, "2B")):
        beta, *_ = np.linalg.lstsq(X, a[:, j], rcond=None)
        out[name] = beta.tolist()
    return out


def weather_effects(rows: list) -> dict:
    """Temperature and wind effects on carry (ft) and HR probability, park-centred."""
    if not rows:
        return {"n": 0}
    d = pd.DataFrame(rows, columns=["park", "temp", "wind", "carry", "hr"])
    d = d.dropna()
    if len(d) < 200:
        return {"n": int(len(d))}
    for c in ("temp", "wind", "carry", "hr"):
        d[c] = d[c] - d.groupby("park")[c].transform("mean")
    X = np.column_stack([d["temp"] / 10.0, d["wind"]])
    out = {"n": int(len(d))}
    for y, name in (("carry", "carry_ft"), ("hr", "hr_prob")):
        beta, res, *_ = np.linalg.lstsq(X, d[y].to_numpy(float), rcond=None)
        resid = d[y].to_numpy(float) - X @ beta
        cov = np.linalg.inv(X.T @ X) * resid.var()
        out[name] = {"per_10F": float(beta[0]), "per_mph_out": float(beta[1]),
                     "se": [float(np.sqrt(cov[0, 0])), float(np.sqrt(cov[1, 1]))]}
    return out


def park_factors(level: str, season: int, years: int = YEARS, use_cache: bool = True) -> dict:
    """{"ok","season","years","parks": {abbr: {...factors...}}, "dimensions", "weather"}."""
    seasons = [s for s in range(season - years + 1, season + 1) if _c.pitch_path(level, s).exists()]
    if not seasons:
        fit = _c.read_fit(f"parks_{level}")
        return fit if isinstance(fit, dict) else {"ok": False, "reason": "no seasons"}
    key = _c.file_key(*[_c.pitch_path(level, s) for s in seasons], MODEL_VERSION)

    def build():
        aggs = [season_for(level, s) for s in seasons]
        store = _c.load_store(level, season) or _c.load_store(level, seasons[-1])
        parks = combine(aggs, store)
        wrows = [r for a in aggs for r in (a.get("weather") or [])]
        return {"ok": True, "version": MODEL_VERSION, "season": season, "years": seasons, "parks": parks,
                "dimensions": dimension_effects(parks), "weather": weather_effects(wrows)}
    return _c.cached("parks", f"factors_{level}_{season}_{years}", key, build, use_cache)


def factors(level: str, season: int) -> dict:
    """Builder D's entry point: {"parks": {abbr: {"factors": {"1B","2B","3B","HR","runs","K","BB","woba_con"}}}}."""
    return park_factors(level, season)


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    return park_factors(level, season, use_cache=use_cache)


def leaders(res: dict, key: str = "runs", n: int = 5) -> dict:
    parks = (res or {}).get("parks") or {}
    vals = sorted(((v["factors"].get(key), p) for p, v in parks.items() if v["factors"].get(key) is not None), reverse=True)
    return {"top": vals[:n], "bottom": vals[-n:][::-1]}


def export_fits(level: str = "mlb", season: int | None = None) -> dict:
    seasons = _c.pitch_seasons(level)
    season = season or (seasons[-1] if seasons else None)
    if season is None:
        return {"ok": False, "reason": "no seasons"}
    r = park_factors(level, season)
    _c.write_fit(f"parks_{level}", r)
    return {"ok": bool(r.get("ok")), "season": season, "parks": len(r.get("parks") or {})}
