"""
Rink value: goals and wins above replacement for skaters (RAPM + box prior) and goalies (GSAx).

Skaters
-------
1. Box prior. A TOI-weighted ridge regression, pooled over every season on disk, of 5v5 xG RAPM offence and
   defence (rapm.py, xGF/60 and xGA/60 prevented) on standardised individual rates: 5v5 individual xG, attempts
   and primary / secondary assists per 60, minor penalties drawn and taken per 60, net faceoff wins per 60, hits and
   blocks per 60 (all situations) and a defenceman flag, each rate regressed to its position group's mean with
   100 pseudo-minutes. Its residual variance tau^2 (weighted residual variance
   minus the mean RAPM se^2, floored) is the prior's variance.
2. Combination (Bayesian): the season's 5v5 xG RAPM is refitted with each skater's ridge centre at his box
   prediction instead of zero (lambda again by cross-validation), so a player sits on his box profile until his
   5v5 minutes move him; O and D are that fit's posterior means and se. (The multi-season RAPM page keeps its
   previous-season prior; Rink value is a single-season measure.)
3. Components (goals above average over the season):
       ev_off = O x 5v5 TOI / 60,  ev_def = D x 5v5 TOI / 60
       pp = share x (on-ice PP xGF/60 - league) x PP TOI / 60 / 5, pk = share x (league - on-ice PK xGA/60) x PK TOI / 60 / 4
            (share = TOI / (TOI + 150 min): small samples regressed to average)
       shooting = goals above xG, shrunk (shooting.py; RAPM is in xG so finishing is additive)
       pen = (minors drawn - minors taken) x goals per minor (league net PP goals per 60 x 2 / 60)
   GAA = sum. Faceoffs enter only through the box prior (their value is already in the xG RAPM).
4. Replacement: per position group (F, D), the TOI-weighted GAA per 60 of players outside each team's top 13
   forwards / 7 defence by TOI (the bottom 10% when there are none); GAR = GAA - replacement rate x TOI / 60.
5. Wins: GAR / goals per win, goals per win = 4 g / x (the derivative of the Pythagorean expectation at g goals
   per team-game; x fitted on every team-season on disk, 2.0 without enough of them).

Goalies
-------
GAR = GSAx - replacement GSAx per attempt x attempts faced, replacement = goalies outside the top 2 x teams by
attempts faced (the bottom quarter otherwise); WAR = GAR / goals per win.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _io, _stints
from oddsmarkets.nhl.models.shooting import frame_rows

MODEL_VERSION = "nhlvalue-1"
BOX_FEATURES = ["ixg60", "icf60", "a1_60", "a2_60", "pen_drawn60", "pen_taken60", "fo_net60", "hits60", "blocks60", "is_d"]
BOX_RIDGE = 5.0
RATE_PSEUDO_MIN = 100.0       # box rates regressed to the position group's mean with 100 pseudo-minutes
BOX_MIN_TOI5 = 150.0          # minutes
BOX_WEIGHT_CAP = 1200.0       # minutes
TAU2_FLOOR = 0.0025
SPECIAL_K_MIN = 150.0
TEAM_F, TEAM_D = 13, 7
GOALIE_TEAM = 2
PYTHAG_DEFAULT = 2.0


def box_rates(pg: pd.DataFrame, pos: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-player season rates from the player-game table (index player id)."""
    g = pg.groupby("player")
    t = g.sum(numeric_only=True)
    out = pd.DataFrame(index=t.index)
    out["gp"] = g.size()
    tm = pg.groupby(["player", "team"])["toi"].sum().reset_index().sort_values("toi").drop_duplicates("player", keep="last")
    out["team"] = tm.set_index("player")["team"].reindex(out.index)
    out["toi"] = t["toi"] / 60.0
    out["toi5"] = t["toi5"] / 60.0
    out["toipp"] = t["toipp"] / 60.0
    out["toipk"] = t["toipk"] / 60.0
    m5 = (t["toi5"] / 3600.0).where(t["toi5"] > 0)
    ma = (t["toi"] / 3600.0).where(t["toi"] > 0)
    out["ixg60"] = t["ixg5"] / m5
    out["icf60"] = t["icf5"] / m5
    out["a1_60"] = t["a1_5"] / m5
    out["a2_60"] = t["a2_5"] / m5
    out["pen_drawn60"] = t["pen_drawn"] / ma
    out["pen_taken60"] = t["pen_taken"] / ma
    out["fo_net60"] = (t["fo_won"] - t["fo_lost"]) / ma
    out["hits60"] = t["hits"] / ma
    out["blocks60"] = t["blocks"] / ma
    for c in ("g", "a1", "a2", "pen_drawn", "pen_taken", "fo_won", "fo_lost", "ixg", "gpp", "a1pp", "a2pp"):
        out[c] = t[c]
    grp = pos["group"] if pos is not None and "group" in pos else pd.Series(dtype=object)
    out["group"] = grp.reindex([int(p) for p in out.index]).fillna("F").to_numpy()
    out["is_d"] = (out["group"] == "D").astype(float)
    # small samples: regress each rate to the TOI-weighted mean of the player's position group
    for c in BOX_FEATURES:
        if c == "is_d":
            continue
        tcol = "toi5" if c in ("ixg60", "icf60", "a1_60", "a2_60") else "toi"
        w = out[tcol].to_numpy(float)
        v = out[c].to_numpy(float)
        sh = v.copy()
        for g in pd.unique(out["group"]):
            m = (out["group"] == g).to_numpy() & np.isfinite(v) & (w > 0)
            if not m.any():
                continue
            mu = float(np.average(v[m], weights=w[m]))
            mm = (out["group"] == g).to_numpy()
            sh[mm] = (np.nan_to_num(v[mm]) * w[mm] + RATE_PSEUDO_MIN * mu) / (w[mm] + RATE_PSEUDO_MIN)
        out[c] = sh
    return out


def box_fit(rates: list[pd.DataFrame], rapms: list[dict], lam: float = BOX_RIDGE) -> dict:
    """Pooled ridge of RAPM O and D on standardised box rates; tau^2 per side."""
    frames = []
    for k, (r, rp) in enumerate(zip(rates, rapms)):
        pl = rp or {}
        f = r[(r["toi5"] >= BOX_MIN_TOI5) & (r["group"] != "G")].copy()
        f = f[[str(int(p)) in pl for p in f.index]]
        for side in ("o", "d"):
            f[f"y_{side}"] = [pl[str(int(p))][side] for p in f.index]
            f[f"se_{side}"] = [pl[str(int(p))][f"se_{side}"] for p in f.index]
        frames.append(f)
    df = pd.concat(frames) if frames else pd.DataFrame()
    df = df[df[BOX_FEATURES].notna().all(axis=1)] if len(df) else df
    if len(df) < len(BOX_FEATURES) + 10:
        return {"ok": False, "reason": f"only {len(df)} player-seasons with RAPM and box rates", "version": MODEL_VERSION}
    Z = df[BOX_FEATURES].to_numpy(float)
    w = np.minimum(df["toi5"].to_numpy(float), BOX_WEIGHT_CAP)
    mu = np.average(Z, axis=0, weights=w)
    sd = np.sqrt(np.average((Z - mu) ** 2, axis=0, weights=w))
    sd[sd < 1e-9] = 1.0
    Zs = (Z - mu) / sd
    lam_eff = lam * w.sum() / 1000.0
    out = {"ok": True, "version": MODEL_VERSION, "features": BOX_FEATURES, "mu": mu.tolist(), "sd": sd.tolist(),
           "n": int(len(df))}
    for side in ("o", "d"):
        y = df[f"y_{side}"].to_numpy(float)
        coef = _io.wridge(Zs, y, w, lam_eff)
        pred = coef[0] + Zs @ coef[1:]
        r = y - pred
        se2 = df[f"se_{side}"].to_numpy(float) ** 2
        out[f"coef_{side}"] = coef.tolist()
        out[f"tau2_{side}"] = max(float(np.average(r ** 2, weights=w) - np.average(se2, weights=w)), TAU2_FLOOR)
        out[f"r2_{side}"] = float(1 - np.average(r ** 2, weights=w) / max(np.average((y - np.average(y, weights=w)) ** 2, weights=w), 1e-12))
    return out


def box_predict(rates: pd.DataFrame, model: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=rates.index, columns=["box_o", "box_d"], dtype=float)
    if not model.get("ok"):
        return out
    ok = rates[BOX_FEATURES].notna().all(axis=1)
    Z = (rates.loc[ok, BOX_FEATURES].to_numpy(float) - np.array(model["mu"])) / np.array(model["sd"])
    for side in ("o", "d"):
        c = np.array(model[f"coef_{side}"])
        out.loc[ok, f"box_{side}"] = c[0] + Z @ c[1:]
    return out


def combine(box: float | None, tau2: float, rapm: float | None, se: float | None) -> tuple[float, float, float]:
    """(value, se, weight on RAPM)."""
    pb = 1.0 / tau2 if box is not None and np.isfinite(box) else 0.0
    pr = 1.0 / se ** 2 if rapm is not None and se and np.isfinite(rapm) else 0.0
    if pb + pr == 0:
        return 0.0, float(np.sqrt(tau2)), 0.0
    v = ((box or 0.0) * pb + (rapm or 0.0) * pr) / (pb + pr)
    return float(v), float(1.0 / np.sqrt(pb + pr)), float(pr / (pb + pr))


# ============================================================================ scoring environment

def game_results(ev: pd.DataFrame) -> pd.DataFrame:
    """Per game: home, away, gh, ga (regulation + OT goals), shootout winner credited, home_win."""
    e = ev[ev["type"] == "goal"]
    reg = e[e["shootout"] == 0]
    g = ev.drop_duplicates("game_id")[["game_id", "home_team", "away_team"]].set_index("game_id")
    g["gh"] = reg[reg["is_home"] == 1].groupby("game_id").size().reindex(g.index).fillna(0)
    g["ga"] = reg[reg["is_home"] == 0].groupby("game_id").size().reindex(g.index).fillna(0)
    so = e[e["shootout"] == 1]
    soh = so[so["is_home"] == 1].groupby("game_id").size().reindex(g.index).fillna(0)
    soa = so[so["is_home"] == 0].groupby("game_id").size().reindex(g.index).fillna(0)
    g["home_win"] = np.where(g["gh"] != g["ga"], (g["gh"] > g["ga"]).astype(float), (soh > soa).astype(float))
    g.loc[(g["gh"] == g["ga"]) & (soh == soa), "home_win"] = np.nan
    return g.reset_index()


def team_records(res: pd.DataFrame) -> pd.DataFrame:
    a = pd.DataFrame({"team": res["home_team"], "gf": res["gh"], "ga": res["ga"], "w": res["home_win"]})
    b = pd.DataFrame({"team": res["away_team"], "gf": res["ga"], "ga": res["gh"], "w": 1 - res["home_win"]})
    t = pd.concat([a, b]).dropna(subset=["w"])
    return t.groupby("team").agg(gp=("w", "size"), w=("w", "sum"), gf=("gf", "sum"), ga=("ga", "sum"))


def pythag_x(records: list[pd.DataFrame]) -> float:
    t = pd.concat(records) if records else pd.DataFrame()
    t = t[t["gp"] >= 20] if len(t) else t
    if len(t) < 60:
        return PYTHAG_DEFAULT
    wp = (t["w"] / t["gp"]).to_numpy(float)
    r = (t["gf"] / t["ga"]).to_numpy(float)
    xs = np.linspace(1.4, 2.8, 141)
    err = [np.sum((wp - r ** x / (r ** x + 1)) ** 2) for x in xs]
    return float(xs[int(np.argmin(err))])


def goals_per_win(goals_per_team_game: float, x: float) -> float:
    return 4.0 * goals_per_team_game / x


# ============================================================================ the season table

def _season_inputs(season: int, use_cache: bool = True) -> dict:
    from oddsmarkets.nhl.models import goalies, onice, rapm, shooting
    ev = _io.events(season)
    pos = _io.players(season, ev)
    pg = _stints.player_games_cached(season, use_cache)
    rp = rapm.chain(season, use_cache)
    return {"ev": ev, "pos": pos, "pg": pg, "rapm": rp, "shoot": shooting.for_season(season, use_cache),
            "goalies": goalies.for_season(season, use_cache), "onice": onice.for_season(season, use_cache)}


def _rows(obj: dict | None, key: str) -> pd.DataFrame:
    t = (obj or {}).get(key) or {}
    return pd.DataFrame(t.get("rows") or [], columns=t.get("cols") or [])


def box_model(use_cache: bool = True) -> dict:
    """The box prior fitted on every completed season on disk with stints (cached; the committed fit when no
    completed season is on disk, as in CI)."""
    from oddsmarkets.nhl.models import rapm, xg
    seasons = _io.completed_seasons(need_stints=True)
    if not seasons:
        f = _io.load_fitted("value", MODEL_VERSION)
        return f or {"box": {"ok": False, "reason": "no seasons and no committed fit"}, "pythag_x": PYTHAG_DEFAULT}
    f = xg.current_fit() or {}
    key = _io.file_key(MODEL_VERSION, rapm.MODEL_VERSION, f.get("key"), *[p for s in seasons for p in _io.source_files(s)])

    def build():
        rates, rps, recs = [], [], []
        for s in seasons:
            rp = rapm.chain(s, use_cache)
            if not rp.get("ok"):
                continue
            ev = _io.events(s)
            pg = _stints.player_games_cached(s, use_cache)
            rates.append(box_rates(pg, _io.players(s, ev)))
            rps.append((rp.get("xg") or {}).get("players") or {})
            res = game_results(ev[ev["game_type"] == 2])
            recs.append(team_records(res))
            del ev, pg
        out = box_fit(rates, rps) if rates else {"ok": False, "reason": "no RAPM fits"}
        return _io.clean({"box": out, "pythag_x": pythag_x(recs), "seasons": seasons}, 8)

    return _io.cached("value", "box_model", key, build, use_cache)


def season_table(season: int, use_cache: bool = True) -> dict:
    season = _io.sid(season)
    inp = _season_inputs(season, use_cache)
    ev, pg, rp = inp["ev"], inp["pg"], inp["rapm"]
    if not len(pg):
        return {"ok": False, "reason": "no player-game table (stints missing)"}
    bm = box_model(use_cache)
    box = bm.get("box") or {}
    x = float(bm.get("pythag_x") or PYTHAG_DEFAULT)
    res = game_results(ev)
    gpg = float((res["gh"].sum() + res["ga"].sum()) / max(2 * len(res), 1))
    gpw = goals_per_win(gpg, x)
    rates = box_rates(pg, inp["pos"])
    rates = rates[rates["group"] != "G"]
    bp = box_predict(rates, box)
    rx = ((rp or {}).get("xg") or {}).get("players") or {}
    prior = {str(int(p)): {"o": float(bp.at[p, "box_o"]), "d": float(bp.at[p, "box_d"])} for p in bp.index
             if np.isfinite(bp.at[p, "box_o"]) and np.isfinite(bp.at[p, "box_d"])}
    from oddsmarkets.nhl.models import rapm as rapm_mod
    post = rapm_mod.fit(_stints.for_season(season, use_cache), "xg", prior=prior if box.get("ok") else None)
    px = post.get("players") or {}
    teams = _rows(inp["onice"], "teams")
    oi = _rows(inp["onice"], "players").set_index("player_id") if (inp["onice"] or {}).get("ok") else pd.DataFrame()
    sh = _rows(inp["shoot"], "players").set_index("player_id") if (inp["shoot"] or {}).get("ok") else pd.DataFrame()
    lg = {}
    if len(teams):
        for role, col in (("pp", "xgf60"), ("pk", "xga60")):
            t = teams[teams["role"] == role]
            lg[role] = float(np.average(t[col], weights=t["toi"])) if len(t) and t["toi"].sum() > 0 else np.nan
        tp = teams[teams["role"] == "pp"]
        pp_net60 = float(np.average(tp["gf60"] - tp["ga60"], weights=tp["toi"])) if len(tp) and tp["toi"].sum() > 0 else 6.0
    else:
        pp_net60 = 6.0
    goals_per_minor = pp_net60 * 120.0 / 3600.0
    rows = []
    tau_o, tau_d = float(box.get("tau2_o", 0.04)), float(box.get("tau2_d", 0.04))
    for p, r in rates.iterrows():
        pid = int(p)
        rr = rx.get(str(pid)) or {}
        q = px.get(str(pid))
        if q is not None:
            o, se_o, d, se_d = q["o"], q["se_o"], q["d"], q["se_d"]
        else:                                   # no 5v5 stints: the box prior alone
            o, se_o, _ = combine(bp.at[p, "box_o"], tau_o, None, None)
            d, se_d, _ = combine(bp.at[p, "box_d"], tau_d, None, None)
        ev_off = o * r["toi5"] / 60.0
        ev_def = d * r["toi5"] / 60.0
        pp = pk = 0.0
        if pid in oi.index:
            q = oi.loc[pid]
            if np.isfinite(q.get("pp_xgf60", np.nan)) and np.isfinite(lg.get("pp", np.nan)):
                ptoi = float(q.get("pp_toi") or 0.0)
                pp = ptoi / (ptoi + SPECIAL_K_MIN) * (float(q["pp_xgf60"]) - lg["pp"]) * ptoi / 60.0 / 5.0
            if np.isfinite(q.get("pk_xga60", np.nan)) and np.isfinite(lg.get("pk", np.nan)):
                ktoi = float(q.get("pk_toi") or 0.0)
                pk = ktoi / (ktoi + SPECIAL_K_MIN) * (lg["pk"] - float(q["pk_xga60"])) * ktoi / 60.0 / 4.0
        shoot = float(sh.at[pid, "gax_shrunk"]) if pid in sh.index and np.isfinite(sh.at[pid, "gax_shrunk"]) else 0.0
        pen = (float(r["pen_drawn"]) - float(r["pen_taken"])) * goals_per_minor
        gaa = ev_off + ev_def + pp + pk + shoot + pen
        rows.append({"player_id": pid, "team": r["team"], "group": r["group"], "gp": int(r["gp"]), "toi": float(r["toi"]),
                     "toi5": float(r["toi5"]), "off": o, "def": d, "off_se": se_o, "def_se": se_d, "box_off": bp.at[p, "box_o"], "box_def": bp.at[p, "box_d"],
                     "rapm_off": rr.get("o"), "rapm_def": rr.get("d"), "ev_off": ev_off, "ev_def": ev_def, "pp": pp, "pk": pk,
                     "shooting": shoot, "pen": pen, "gaa": gaa})
    t = pd.DataFrame(rows)
    if not len(t):
        return {"ok": False, "reason": "no skaters"}
    n_teams = max(int(pd.Series(pd.concat([res["home_team"], res["away_team"]])).nunique()), 1)
    rep = {}
    for grp, per in (("F", TEAM_F), ("D", TEAM_D)):
        m = t["group"] == grp
        s = t[m].sort_values("toi", ascending=False)
        pool = s.iloc[per * n_teams:]
        pool = pool[pool["toi"] >= 20]
        if len(pool) < 5:
            pool = s[s["toi"] >= 20].tail(max(int(0.1 * len(s)), 3))
        rep[grp] = float(pool["gaa"].sum() / max(pool["toi"].sum(), 1e-9) * 60.0) if len(pool) else 0.0
    t["rep60"] = t["group"].map(rep).fillna(0.0)
    t["gar"] = t["gaa"] - t["rep60"] * t["toi"] / 60.0
    t["war"] = t["gar"] / gpw
    t["gar60"] = 60.0 * t["gar"] / t["toi"].where(t["toi"] > 0)
    t = t.sort_values("gar", ascending=False).reset_index(drop=True)
    # goalies
    gt = _rows(inp["goalies"], "goalies")
    if len(gt):
        s = gt.sort_values("fa", ascending=False)
        pool = s.iloc[GOALIE_TEAM * n_teams:]
        pool = pool[pool["fa"] >= 100]
        if len(pool) < 3:
            pool = s[s["fa"] >= 100].tail(max(int(0.25 * len(s)), 2))
        rep_g = float(pool["gsax"].sum() / max(pool["fa"].sum(), 1e-9)) if len(pool) else 0.0
        g = pd.DataFrame({"player_id": gt["player_id"], "team": gt["team"], "fa": gt["fa"], "gsax": gt["gsax"],
                          "gsax_shrunk": gt["gsax_shrunk"]})
        g["gar"] = g["gsax"] - rep_g * g["fa"]
        g["war"] = g["gar"] / gpw
        g = g.sort_values("gar", ascending=False).reset_index(drop=True)
    else:
        g, rep_g = pd.DataFrame(), None
    env = {"goals_per_team_game": gpg, "pythag_x": x, "goals_per_win": gpw, "goals_per_minor": goals_per_minor,
           "replacement_gaa60": rep, "replacement_gsax_per_attempt": rep_g, "teams": n_teams,
           "league_pp_xgf60": lg.get("pp"), "league_pk_xga60": lg.get("pk")}
    env["posterior_ridge"] = post.get("ridge")
    return {"ok": True, "season": season, "environment": env,
            "box_model": {k: box.get(k) for k in ("ok", "n", "r2_o", "r2_d", "tau2_o", "tau2_d", "features", "coef_o", "coef_d")},
            "skaters": frame_rows(t), "goalies": frame_rows(g) if len(g) else {"cols": [], "rows": []}}


def for_season(season: int, use_cache: bool = True) -> dict:
    from oddsmarkets.nhl.models import rapm, xg
    season = _io.sid(season)
    if not _io.stints_path(season).exists():
        return {"ok": False, "reason": "no stints for this season"}
    f = xg.current_fit() or {}
    seasons = _io.completed_seasons(need_stints=True)
    key = _io.file_key(MODEL_VERSION, rapm.MODEL_VERSION, f.get("key"), *[p for s in seasons for p in _io.source_files(s)])
    return _io.cached("value", str(season), key, lambda: season_table(season, use_cache), use_cache)


def export_fits() -> dict:
    bm = box_model()
    out = {"version": MODEL_VERSION, "ok": bool((bm.get("box") or {}).get("ok")), "box": bm.get("box"),
           "pythag_x": bm.get("pythag_x"), "seasons": bm.get("seasons")}
    _io.write_fit("value", out)
    return out
