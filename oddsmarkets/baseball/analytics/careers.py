"""
Player career files (data/players/<pid>.json, all levels) and players_index.json.

Career file (PAYLOADS): {"id","name","bats","throws","pos","dob","debut","ids":{"retro","bbref","fg"},
"seasons": [{level, season, kind, team, ...traditional..., xwoba_plus, xwoba_savant, war, ...}],
"history": {"batting": [[...]], "pitching": [[...]], "cols": {...}} (Retrosheet-era seasons, before 2015),
"current": {...the latest full season's blocks...}, "similar": [...], "meta": {"retrosheet_notice"} when history is present}.

Current blocks (the full season being built), for every player in its catalogues:
* hitting / pitching: the catalogue row (values, pct, pct_role, n);
* spray: the last 400 balls in play [hc_x, hc_y, xwOBA+ (else Savant xwOBA), EV, LA, result code];
* zones: 5 x 5 grids (rows low -> high, columns catcher's view left -> right; the inner 3 x 3 is the strike zone in
  thirds, the outer ring outside it) per pitch family: hitters [pitches, swing%, whiff%, xwOBA], pitchers per pitch type
  [pitches, whiff%];
* decisions: the hitter's mean decision value (runs per 100 pitches) and pitches per cell (builder B's swing model);
* battrack, arsenal, release, tunnels, fatigue from builder B; movement: up to 300 pitches [type, arm-side HB, IVB, velo];
* rolling: hitters [[date, rolling-100-PA xwOBA+, rolling wOBA]], pitchers builder B's [[date, pitches, stuff, location,
  pitching, rolling-500-pitch pitching]];
* splits: v LHP/RHP (v LHB/RHB), home/away and by month: PA (BF), wOBA, K%;
* projection: builder D's next-season projection.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import pitchagg as PG
from oddsmarkets.baseball.analytics.context import SeasonContext

X_EDGES = [-np.inf, -0.83, -0.277, 0.277, 0.83, np.inf]
Z_EDGES = [-np.inf, 0.0, 1 / 3, 2 / 3, 1.0, np.inf]
EV_CODE = {"single": 1, "double": 2, "triple": 3, "home_run": 4, "field_error": 5}
SEASON_KEYS_H = ["g", "pa", "ab", "h", "b2", "b3", "hr", "bb", "so", "sb", "avg", "obp", "slg", "ops", "woba", "xwoba_plus", "xwoba_savant",
                 "k_pct", "bb_pct", "barrel_pct", "hard_pct", "ev", "chase_pct", "whiff_pct", "bat_speed", "dv", "oaa", "framing_runs", "war", "war_results"]
SEASON_KEYS_P = ["g", "gs", "w", "l", "sv", "ip", "bf", "so", "bb", "hr", "ra9", "fip", "whip", "k_pct", "bb_pct", "k_bb_pct", "csw_pct",
                 "whiff_pct", "xwoba_plus", "xwoba_savant", "fb_velo", "stuff_plus", "location_plus", "pitching_plus", "war", "war_x"]
# similar players (docs/METRICS_SPEC.md): the peer group's features and year-to-year weights from
# docs/_design/metrics/baseball.json (oddsmarkets/common/similar.py); the lists below are the fallback when the spec
# file is absent, and SIMILAR_H / SIMILAR_P (every feature of every group) are the values the careers step keeps
HIT_GROUP = {"C": "hitters_C", "1B": "hitters_1B", "2B": "hitters_2B", "3B": "hitters_3B", "SS": "hitters_SS",
             "CF": "hitters_CF", "LF": "hitters_LFRF", "RF": "hitters_LFRF", "OF": "hitters_LFRF", "DH": "hitters_DH",
             "TWP": "hitters_DH"}
PIT_GROUP = {"SP": "sp", "RP": "rp"}
SIM_MIN = {"hitter": ("pa", 200.0), "sp": ("bf", 300.0), "rp": ("bf", 120.0)}   # full-season minimums, prorated by team games
SIM_FROM = 2015
_FALLBACK_H = ["xwoba_n", "barrel_pct", "hard_pct", "bat_speed", "k_pct", "bb_pct", "chase_pct", "sprint_speed", "gb_pct", "pull_air_pct"]
_FALLBACK_P = ["xwoba_n", "xfip", "k_pct", "bb_pct", "csw_pct", "stuff_plus", "pitching_plus", "fb_velo", "chase_pct", "gb_pct",
               "fb_usage", "br_usage"]


def _sim_cfg(gid: str, kind: str) -> dict:
    from oddsmarkets.common import similar as SIM
    return SIM.group_config("baseball", gid, fallback={"features": _FALLBACK_H if kind == "hitter" else _FALLBACK_P, "k": 5})


def _sim_features(kind: str) -> list[str]:
    gids = ["hitters_all"] + sorted(set(HIT_GROUP.values())) if kind == "hitter" else sorted(set(PIT_GROUP.values()))
    out: list[str] = []
    for g in gids:
        for f in _sim_cfg(g, kind)["features"]:
            if f not in out:
                out.append(f)
    return out


SIMILAR_H = _sim_features("hitter")
SIMILAR_P = _sim_features("pitcher")


# ---------------------------------------------------------------------------------------------- current blocks

def _cells(df: pd.DataFrame) -> np.ndarray:
    x = PG._f(df, "plate_x")
    z = PG._f(df, "plate_z")
    top, bot = PG._f(df, "sz_top"), PG._f(df, "sz_bot")
    ok = np.isfinite(top) & np.isfinite(bot) & (top - bot > 0.8)
    top, bot = np.where(ok, top, 3.4), np.where(ok, bot, 1.55)
    zn = (z - bot) / (top - bot)
    cx = np.digitize(x, X_EDGES[1:-1])
    cz = np.digitize(zn, Z_EDGES[1:-1])
    return np.where(np.isfinite(x) & np.isfinite(z), cz * 5 + cx, -1)


def _grid(sub: pd.DataFrame, cols: list[str], fn) -> list:
    g = [[None] * 5 for _ in range(5)]
    for cell, r in sub.iterrows():
        if cell < 0:
            continue
        g[int(cell) // 5][int(cell) % 5] = fn(r)
    return g


def current_blocks(ctx: SeasonContext, hcat: dict | None, pcat: dict | None) -> dict[str, dict]:
    df = ctx.frame()
    if not len(df):
        return {}
    hp = (hcat or {}).get("players") or {}
    pp = (pcat or {}).get("players") or {}
    out: dict[str, dict] = {}
    fl = None
    cell = _cells(df)
    desc = PG._s(df, "description")
    ev = PG._s(df, "events")
    fam = PG._s(df, "pitch_type").map(PG.FAMILY).fillna("")
    sw = desc.isin(PG.SWINGS).to_numpy()
    wh = desc.isin(PG.WHIFFS).to_numpy()
    pa_end = ev.isin(PG.PA_EVENTS).to_numpy()
    xw = PG._f(df, "estimated_woba_using_speedangle")
    wv = np.nan_to_num(PG._f(df, "woba_value"))
    wd = np.nan_to_num(PG._f(df, "woba_denom"))
    bipm = ev.isin(set(PG.HIT) | PG.OUT_BIP | {"field_error"}).to_numpy()
    xnum = np.where(pa_end, np.where(bipm & np.isfinite(xw), xw, wv), 0.0)
    base = pd.DataFrame({"batter": df["batter"].astype(str).to_numpy(), "pitcher": df["pitcher"].astype(str).to_numpy(), "cell": cell,
                         "fam": fam.to_numpy(), "pt": PG._s(df, "pitch_type").to_numpy(), "n": 1.0, "sw": sw.astype(float),
                         "wh": wh.astype(float), "xn": xnum, "wd": np.where(pa_end, wd, 0.0)})
    # hitters: zone grids by family
    zh: dict[str, dict] = {}
    for f in ("all", "fb", "br", "os"):
        b = base if f == "all" else base[base["fam"] == f]
        g = b.groupby(["batter", "cell"])[["n", "sw", "wh", "xn", "wd"]].sum()
        for (pid, c), r in g.iterrows():
            if pid not in hp:
                continue
            grid = zh.setdefault(pid, {}).setdefault(f, [[None] * 5 for _ in range(5)])
            if c < 0:
                continue
            grid[int(c) // 5][int(c) % 5] = [int(r["n"]), an.rnd(an.div(r["sw"], r["n"]), 3), an.rnd(an.div(r["wh"], r["sw"]), 3),
                                             an.rnd(an.div(r["xn"], r["wd"]), 3)]
    # pitchers: location by pitch type
    zp: dict[str, dict] = {}
    g = base.groupby(["pitcher", "pt", "cell"])[["n", "sw", "wh"]].sum()
    tot = base.groupby(["pitcher", "pt"])["n"].sum()
    for (pid, pt, c), r in g.iterrows():
        if pid not in pp or not pt or tot.get((pid, pt), 0) < 50 or c < 0:
            continue
        grid = zp.setdefault(pid, {}).setdefault(pt, [[None] * 5 for _ in range(5)])
        grid[int(c) // 5][int(c) % 5] = [int(r["n"]), an.rnd(an.div(r["wh"], r["sw"]), 3)]
    # decision grids
    dec: dict[str, list] = {}
    sc = ctx.scores()
    if sc is not None and "dv" in sc:
        k = df[["game_pk", "at_bat_number", "pitch_number"]].copy()
        k["batter"] = base["batter"].to_numpy()
        k["cell"] = cell
        j = k.merge(sc[["game_pk", "at_bat_number", "pitch_number", "dv"]], on=["game_pk", "at_bat_number", "pitch_number"], how="inner")
        j = j[j["dv"].notna()]
        gd = j.groupby(["batter", "cell"])["dv"].agg(["sum", "size"])
        for (pid, c), r in gd.iterrows():
            if pid not in hp or c < 0:
                continue
            grid = dec.setdefault(pid, [[None] * 5 for _ in range(5)])
            grid[int(c) // 5][int(c) % 5] = [an.rnd(100 * r["sum"] / r["size"], 2), int(r["size"])]
    # spray
    spray: dict[str, list] = {}
    bm = bipm & np.isfinite(PG._f(df, "hc_x"))
    if bm.any():
        s = df.loc[bm, ["game_pk", "at_bat_number", "batter", "hc_x", "hc_y", "launch_speed", "launch_angle", "estimated_woba_using_speedangle"]].copy()
        s["code"] = ev[bm].map(EV_CODE).fillna(0).astype(int).to_numpy()
        bx = ctx.bip()
        if bx is not None and "xwoba" in bx:
            s = s.merge(bx[["game_pk", "at_bat_number", "xwoba"]].drop_duplicates(["game_pk", "at_bat_number"]), on=["game_pk", "at_bat_number"], how="left")
        else:
            s["xwoba"] = np.nan
        s["xw"] = s["xwoba"].fillna(pd.to_numeric(s["estimated_woba_using_speedangle"], errors="coerce"))
        for pid, x in s.groupby(s["batter"].astype(str)):
            if pid not in hp:
                continue
            x = x.tail(400)
            spray[pid] = [[_r(a, 1), _r(b, 1), _r(c, 3), _r(d, 1), _r(e, 0), int(f)] for a, b, c, d, e, f in
                          zip(x["hc_x"], x["hc_y"], x["xw"], x["launch_speed"], x["launch_angle"], x["code"])]
    # movement samples
    move: dict[str, list] = {}
    arm = np.where(PG._s(df, "p_throws").to_numpy() == "L", 1.0, -1.0)
    mv = pd.DataFrame({"pitcher": base["pitcher"], "pt": base["pt"], "hb": PG._f(df, "pfx_x") * 12 * arm, "ivb": PG._f(df, "pfx_z") * 12,
                       "velo": PG._f(df, "release_speed")})
    mv = mv[(mv["pt"] != "") & mv["hb"].notna() & mv["ivb"].notna()]
    for pid, x in mv.groupby("pitcher"):
        if pid not in pp:
            continue
        if len(x) > 300:
            x = x.sample(300, random_state=0)
        move[pid] = [[t, _r(h, 1), _r(i, 1), _r(v, 1)] for t, h, i, v in zip(x["pt"], x["hb"], x["ivb"], x["velo"])]
    # rolling (hitters) and splits
    roll, splits = _rolling_splits(ctx, hp, pp)
    logs = game_logs(ctx, hp, pp)
    phys = ctx.model("physics").get("pitchers") or {}
    tun = ctx.model("tunneling").get("pitchers") or {}
    fat = ctx.model("fatigue").get("pitchers") or {}
    prl = ctx.model("pitching").get("rolling") or {}
    btk = ctx.model("battrack").get("hitters") or {}
    proj = ctx.model("proj_next")
    arsenal = (pcat or {}).get("arsenal") or {}
    for pid in set(hp) | set(pp):
        blk: dict[str, Any] = {"season": ctx.season, "level": ctx.level}
        if pid in hp:
            r = hp[pid]
            blk["hitting"] = {k: r.get(k) for k in ("values", "pct", "pct_role", "n", "qualified", "pa", "team", "pos", "age")}
            blk["spray"] = spray.get(pid)
            blk["zones"] = zh.get(pid)
            blk["decisions"] = dec.get(pid)
            blk["battrack"] = an.clean(btk.get(pid)) if btk.get(pid) else None
            blk["rolling"] = roll.get(pid)
        if pid in pp:
            r = pp[pid]
            blk["pitching"] = {k: r.get(k) for k in ("values", "pct", "pct_role", "n", "qualified", "bf", "team", "role", "primary", "age")}
            blk["arsenal"] = arsenal.get(pid)
            # the league average of each of his pitch types (the movement chart's grey marks; peers.own_types)
            from oddsmarkets.baseball.analytics.peers import own_types
            blk["league_types"] = own_types((pcat or {}).get("league_types"), arsenal.get(pid))
            blk["pitch_zones"] = zp.get(pid)
            blk["movement"] = move.get(pid)
            blk["release"] = (phys.get(pid) or {}).get("release")
            t = tun.get(pid) or {}
            blk["tunnels"] = [{"pair": k, **v} for k, v in (t.get("by_pair") or {}).items()] or None
            f = fat.get(pid) or {}
            blk["fatigue"] = {k: v for k, v in f.items()} if f else None
            blk["pitching_rolling"] = prl.get(pid)
        blk["splits"] = splits.get(pid)
        blk["log"] = logs.get(pid)
        pj = None
        for kind in ("hitters", "pitchers"):
            if (proj.get(kind) or {}).get(pid):
                pj = {"kind": kind[:-1], "season": ctx.season + 1, **proj[kind][pid]}
        blk["projection"] = pj
        out[pid] = blk
    return out


LOG_H = ["date", "gpk", "t", "opp", "home", "res", "pa", "ab", "h", "tb", "hr", "bb", "k", "xwoba"]
LOG_P = ["date", "gpk", "t", "opp", "home", "res", "gs", "outs", "bf", "h", "r", "bb", "k", "hr", "np"]


def game_logs(ctx: SeasonContext, hp: dict, pp: dict) -> dict[str, dict]:
    """{pid: {"hitting": {cols, rows, best}, "pitching": {cols, rows, best}}}: one row per game this season (date order)
    from the plate-appearance table, for the player page's "Every game this season". Hitting: PA, AB, H, total bases,
    HR, BB, K and the game's xwOBA; pitching: started, outs, batters faced, H, runs, BB, K, HR, pitches. `res` is the
    player's team's result ("W 5-3"), `t` the game type (R regular season, F/D/L/W postseason), `home` 1 at home.
    `best` is the row index of the best game (hitting: total bases + walks, then xwOBA; pitching: a game score,
    40 + 2 outs + K - 2 BB - 2 H - 3 R - 6 HR)."""
    pa = (ctx.agg() or {}).get("pa")
    out: dict[str, dict] = {}
    if pa is None or not len(pa):
        return out
    d = pa.copy()
    ev = d["events"].astype(str)
    d["h"] = ev.isin(PG.HIT).astype(int)
    d["tb"] = ev.map(PG.HIT).fillna(0).astype(int)
    d["hr"] = (ev == "home_run").astype(int)
    d["bb"] = ev.isin({"walk", "intent_walk"}).astype(int)
    d["k"] = ev.isin(PG.K_EV).astype(int)
    d["pa_n"] = d["is_pa"].astype(int)
    d["ab"] = (d["is_pa"] & ~ev.isin({"walk", "intent_walk", "hit_by_pitch", "catcher_interf", "sac_fly", "sac_bunt",
                                       "sac_fly_double_play", "sac_bunt_double_play"})).astype(int)
    d["w"] = pd.to_numeric(d["woba_value"], errors="coerce").fillna(0.0) * d["pa_n"]
    d["den"] = pd.to_numeric(d["woba_denom"], errors="coerce").fillna(0.0) * d["pa_n"]
    bx = ctx.bip()
    if bx is not None and "xwoba" in bx:
        d = d.merge(bx[["game_pk", "at_bat_number", "xwoba"]].drop_duplicates(["game_pk", "at_bat_number"]),
                    on=["game_pk", "at_bat_number"], how="left")
        d["xw"] = np.where(d["xwoba"].notna(), pd.to_numeric(d["xwoba"], errors="coerce"), d["w"]) * d["pa_n"]
    else:
        d["xw"] = d["w"]
    d["date"] = pd.to_datetime(d["game_date"]).dt.strftime("%Y-%m-%d")
    games = ctx.games or {}

    def meta(gpk, bat_side_home: bool, own_abbr: str, opp_abbr: str):
        g = games.get(str(int(gpk))) or {}
        own_home = bool(bat_side_home)
        res = None
        if g.get("status") == "final" and isinstance(g.get("hs"), (int, float)) and isinstance(g.get("as"), (int, float)):
            a, b = (g["hs"], g["as"]) if own_home else (g["as"], g["hs"])
            res = f"{'W' if a > b else 'L' if a < b else 'T'} {int(a)}-{int(b)}"
        return [g.get("gtype") or "R", opp_abbr, 1 if own_home else 0, res]

    # hitting: the batter's half (half 1 = bottom = home batting)
    hb = d[d["batter"].astype(str).isin(set(hp))]
    if len(hb):
        agg = hb.groupby([hb["batter"].astype(str), "game_pk"]).agg(
            date=("date", "first"), half=("half", "first"), bt=("bat_team", "first"), ft=("fld_team", "first"),
            pa=("pa_n", "sum"), ab=("ab", "sum"), h=("h", "sum"), tb=("tb", "sum"), hr=("hr", "sum"), bb=("bb", "sum"),
            k=("k", "sum"), xw=("xw", "sum"), den=("den", "sum")).reset_index()
        agg = agg[agg["pa"] > 0].sort_values(["batter", "date", "game_pk"])
        for pid, x in agg.groupby("batter"):
            rows = []
            for r in x.itertuples(index=False):
                t, opp, home, res = meta(r.game_pk, r.half == 1, r.bt, r.ft)
                rows.append([r.date, int(r.game_pk), t, opp, home, res, int(r.pa), int(r.ab), int(r.h), int(r.tb), int(r.hr),
                             int(r.bb), int(r.k), _r(an.div(r.xw, r.den), 3)])
            if rows:
                sc = [(rw[9] + rw[11], rw[13] if rw[13] is not None else -1) for rw in rows]
                out.setdefault(pid, {})["hitting"] = {"cols": LOG_H, "rows": rows, "best": max(range(len(rows)), key=lambda i: sc[i])}
    # pitching: the pitcher's team fields (half 0 = top = home pitching)
    pb = d[d["pitcher"].astype(str).isin(set(pp))]
    if len(pb):
        firsts = pa.sort_values(["game_pk", "half", "at_bat_number"]).drop_duplicates(["game_pk", "half"])
        starters = set(zip(firsts["pitcher"].astype(str), firsts["game_pk"]))
        agg = pb.groupby([pb["pitcher"].astype(str), "game_pk"]).agg(
            date=("date", "first"), half=("half", "first"), bt=("bat_team", "first"), ft=("fld_team", "first"),
            outs=("outs_rec", "sum"), bf=("pa_n", "sum"), h=("h", "sum"), r=("runs", "sum"), bb=("bb", "sum"),
            k=("k", "sum"), hr=("hr", "sum"), np_=("n_pitches", "sum")).reset_index()
        agg = agg.sort_values(["pitcher", "date", "game_pk"])
        for pid, x in agg.groupby("pitcher"):
            rows = []
            for r in x.itertuples(index=False):
                t, opp, home, res = meta(r.game_pk, r.half == 0, r.ft, r.bt)
                rows.append([r.date, int(r.game_pk), t, opp, home, res, 1 if (pid, r.game_pk) in starters else 0, int(r.outs),
                             int(r.bf), int(r.h), int(r.r), int(r.bb), int(r.k), int(r.hr), int(r.np_)])
            if rows:
                gsc = [40 + 2 * rw[7] + rw[12] - 2 * rw[11] - 2 * rw[9] - 3 * rw[10] - 6 * rw[13] for rw in rows]
                out.setdefault(pid, {})["pitching"] = {"cols": LOG_P, "rows": rows, "best": max(range(len(rows)), key=lambda i: gsc[i])}
    return out


def _r(x, nd):
    v = an.fnum(x)
    return None if v is None else (int(round(v)) if nd == 0 else round(v, nd))


def _rolling_splits(ctx: SeasonContext, hp: dict, pp: dict) -> tuple[dict, dict]:
    pa = (ctx.agg() or {}).get("pa")
    roll: dict[str, list] = {}
    splits: dict[str, dict] = {}
    if pa is None or not len(pa):
        return roll, splits
    d = pa[pa["is_pa"]].copy()
    d["w"] = pd.to_numeric(d["woba_value"], errors="coerce").fillna(0.0)
    d["den"] = pd.to_numeric(d["woba_denom"], errors="coerce").fillna(0.0)
    bx = ctx.bip()
    if bx is not None and "xwoba" in bx:
        d = d.merge(bx[["game_pk", "at_bat_number", "xwoba"]].drop_duplicates(["game_pk", "at_bat_number"]), on=["game_pk", "at_bat_number"], how="left")
        d["xw"] = d["xwoba"].where(d["xwoba"].notna(), d["w"])
    else:
        d["xw"] = d["w"]
    d["k"] = d["events"].isin(PG.K_EV).astype(float)
    d["date"] = pd.to_datetime(d["game_date"]).dt.strftime("%Y-%m-%d")
    d["month"] = d["date"].str[:7]
    d["home_bat"] = d["half"] == 1
    d = d.sort_values(["game_date", "game_pk", "at_bat_number"])
    for pid, x in d.groupby(d["batter"].astype(str)):
        if pid not in hp:
            continue
        n = 100
        cw, cx, cd = np.cumsum(x["w"].to_numpy()), np.cumsum(x["xw"].to_numpy()), np.cumsum(x["den"].to_numpy())
        idx = np.arange(len(x))
        lo = np.maximum(idx - n, -1)
        def win(c):
            return c - np.where(lo >= 0, c[np.clip(lo, 0, None)], 0.0)
        ww, wx, wd = win(cw), win(cx), win(cd)
        last = x["date"].ne(x["date"].shift(-1)).to_numpy()
        roll[pid] = [[dt, _r(a / b if b else None, 3), _r(c / b if b else None, 3)] for dt, a, c, b, m in
                     zip(x["date"], wx, ww, wd, last) if m]
    for who, side_home in (("batter", True), ("pitcher", False)):
        pool = hp if who == "batter" else pp
        for pid, x in d.groupby(d[who].astype(str)):
            if pid not in pool:
                continue
            sp: dict[str, Any] = {}
            home = x["home_bat"] if side_home else ~x["home_bat"]
            for nm, m in (("home", home), ("away", ~home)):
                y = x[m]
                sp[nm] = {"pa": int(len(y)), "woba": _r(an.div(y["w"].sum(), y["den"].sum()), 3), "k_pct": _r(an.div(y["k"].sum(), len(y)), 3)}
            hand = x["p_throws"].astype(str) if who == "batter" else x["stand"].astype(str)
            for h in ("L", "R"):
                y = x[hand == h]
                sp[f"v{h}"] = {"pa": int(len(y)), "woba": _r(an.div(y["w"].sum(), y["den"].sum()), 3), "k_pct": _r(an.div(y["k"].sum(), len(y)), 3)}
            sp["months"] = {mo: {"pa": int(len(y)), "woba": _r(an.div(y["w"].sum(), y["den"].sum()), 3),
                                 "k_pct": _r(an.div(y["k"].sum(), len(y)), 3)} for mo, y in x.groupby("month")}
            key = pid
            if key in splits:
                splits[key][who] = sp
            else:
                splits[key] = {who: sp}
    return roll, splits


# ---------------------------------------------------------------------------------------------- careers

def season_row(level: str, season: int, kind: str, r: dict) -> dict:
    keys = SEASON_KEYS_H if kind == "hitter" else SEASON_KEYS_P
    v = r.get("values") or {}
    return {"level": level, "season": season, "kind": kind, "team": r.get("team"), "pos": r.get("pos") if kind == "hitter" else r.get("role"),
            **{k: v.get(k) for k in keys}}


def prog_keys(kind: str, have: set[str] | None = None) -> list[str]:
    """The progression deep set (round 6, oddsmarkets/common/progression.py): every hitter group's (or the SP / RP
    groups') headline then secondary metrics, spec order, only ids the catalogues carry."""
    from oddsmarkets.common import progression as PR
    groups = list(dict.fromkeys(HIT_GROUP.values())) if kind == "hitter" else ["sp", "rp"]
    return PR.deep_keys("baseball", groups, have)


def prog_placed(r: dict, kind: str, team_games: Any) -> bool:
    """Placed in the season's peer pool: the spec minimum (200 PA, 300 BF for starters, 120 for relievers) prorated by
    the season's team games (60 in 2020)."""
    g = sim_group(r, kind) or ""
    stat, full = SIM_MIN["hitter"] if kind == "hitter" else SIM_MIN.get(g, SIM_MIN["rp"])
    tg = an.fnum(team_games)
    tg = tg if tg else 162.0
    n = r.get(stat)
    if n is None:
        n = (r.get("values") or {}).get(stat)
    try:
        return float(n or 0) >= full * min(1.0, tg / 162.0)
    except (TypeError, ValueError):
        return False


def sim_group(r: dict, kind: str) -> str | None:
    """The spec peer group of a catalogue row: hitters by position (hitters_all when it is unknown), pitchers by role."""
    if kind == "hitter":
        return HIT_GROUP.get(str(r.get("pos") or "").upper(), "hitters_all")
    return PIT_GROUP.get(str(r.get("role") or "").upper())


def similar_index(cats: dict[tuple, dict], kind: str, keys: list[str] | None = None, min_n: int | None = None):
    """Per spec group: the qualified MLB player-seasons from 2015 (the group's minimum, prorated by the season's team
    games), their features z-scored within group and season, and the year-to-year weights (floored at 0.2)."""
    from oddsmarkets.common import similar as SIM
    rows: dict[str, list] = {}
    for (lvl, s), c in cats.items():
        if lvl != "mlb" or not c or int(s) < SIM_FROM:
            continue
        scale = min(1.0, float(c.get("team_games") or 162) / 162.0)
        for pid, r in (c.get("players") or {}).items():
            gid = sim_group(r, kind)
            if gid is None:
                continue
            field, need = SIM_MIN["hitter" if kind == "hitter" else gid]
            if (an.fnum(r.get(field)) or 0) < (min_n if min_n is not None else need * scale):
                continue
            rows.setdefault(gid, []).append((str(pid), int(s), r))
    groups, of = {}, {}
    for gid, items in rows.items():
        if len(items) < 6:
            continue
        cfg = _sim_cfg(gid, kind)
        feats = cfg["features"]
        M = SIM.matrix([it[2] for it in items], feats)
        seasons = [it[1] for it in items]
        groups[gid] = {"Z": SIM.zscore(M, seasons), "w": np.array([cfg["weights"][f] for f in feats]), "k": cfg["k"],
                       "ids": [(it[0], it[1]) for it in items], "team": [it[2].get("team") for it in items],
                       "pids": np.array([it[0] for it in items], dtype=object)}
        for i, it in enumerate(items):
            of.setdefault(it[0], {})[it[1]] = (gid, i)
    if not groups:
        return None
    return {"groups": groups, "of": of}


def similar(pid: str, season: int, idx, names: dict, k: int | None = None) -> list:
    """The spec's nearest player-seasons for the player's season `season`, else his latest qualified MLB season:
    [{"pid","season","name","team","distance","for_season"}], nearest first, one season per person (his nearest),
    never the player himself."""
    from oddsmarkets.common import similar as SIM
    if idx is None:
        return []
    mine = idx["of"].get(str(pid)) or {}
    if not mine:
        return []
    s0 = season if season in mine else max(mine)
    gid, i = mine[s0]
    G = idx["groups"][gid]
    k = k or G["k"]
    out, seen = [], set()
    for j, d in SIM.nearest(G["Z"], i, G["w"], 12 * k, allowed=G["pids"] != str(pid)):
        q = G["ids"][j][0]
        if q in seen:                                   # one row per person: his nearest season
            continue
        seen.add(q)
        out.append({"pid": q, "season": G["ids"][j][1], "name": names.get(q), "team": G["team"][j], "distance": round(d, 3),
                    "for_season": s0})
        if len(out) >= k:
            break
    return out


MOVE_CONTEXT = ("season", "snapshot", "phase", "horizons", "published", "base_rates", "deadline_label", "type_labels", "updated_at")


def movement_rows(level: str = "mlb") -> dict[str, dict]:
    """{pid: the player's movement.json row} for players/<pid>.json `movement`: {"row": {field: value} (movement.json
    player_fields), plus the payload's season, snapshot, phase, horizons, published flags, base rates and labels} so the
    player page needs no movement.json. {} when the file is absent (written by the value step, before the careers)."""
    m = an.read_json(an.data_root() / level / "movement.json") or {}
    fields, rows = m.get("player_fields") or [], m.get("players") or []
    if not m.get("ok") or not fields or "pid" not in fields:
        return {}
    ctx = {k: m.get(k) for k in MOVE_CONTEXT if k in m}
    i = fields.index("pid")
    return {str(r[i]): {**ctx, "row": dict(zip(fields, r))} for r in rows if isinstance(r, list) and len(r) == len(fields)}


def add_prev_pct(blocks: dict[str, dict], load) -> int:
    """Last season's position / role percentiles on each current block (kit v3 rail rings, 23 Oct 2026), so the player
    page need not load last season's catalogue: current.hitting / current.pitching get "prev_pct_pos" (the same shape
    as their pct_role) and "prev_peer" {"level", "season", "group", "pa" | "bf", "qualified"}. Same level, and only when
    last season's peer group is this season's (hitters: the position group, C ... LF/RF, DH; pitchers: SP / RP).
    `load(level, season, "hitters" | "pitchers")` returns that season's catalogue. Returns the number of sub-blocks."""
    from oddsmarkets.baseball.analytics.catalog import POS_GROUP
    cache: dict = {}

    def cat(level, season, kind):
        if (level, season, kind) not in cache:
            cache[(level, season, kind)] = ((load(level, season, kind) or {}).get("players") or {})
        return cache[(level, season, kind)]

    def grp(r: dict, kind: str):
        return (r.get("role") or None) if kind == "pitchers" else POS_GROUP.get(r.get("pos") or "", "DH")

    n = 0
    for pid, b in blocks.items():
        if not b or not b.get("season"):
            continue
        lvl, ps = b.get("level") or "mlb", int(b["season"]) - 1
        for kind, key, den in (("hitters", "hitting", "pa"), ("pitchers", "pitching", "bf")):
            sub = b.get(key)
            if not sub:
                continue
            pr = cat(lvl, ps, kind).get(pid)
            if not pr or not pr.get("pct_role"):
                continue
            g = grp(pr, kind)
            if g is None or g != grp(sub, kind):
                continue
            sub["prev_pct_pos"] = pr["pct_role"]
            sub["prev_peer"] = {"level": lvl, "season": ps, "group": g, den: pr.get(den), "qualified": bool(pr.get("qualified"))}
            n += 1
    return n


def roster_numbers(store: dict) -> dict[str, str]:
    """{pid: jersey number} from a season store's 40-man and injured rosters (meta.rosters[tid].num, from the roster
    answers' jerseyNumber)."""
    out: dict[str, str] = {}
    for r in ((store.get("meta") or {}).get("rosters") or {}).values():
        for pid, n in ((r or {}).get("num") or {}).items():
            if n:
                out[str(pid)] = str(n)
    return out


def write_careers(write, cats: dict[tuple, dict], blocks: dict[str, dict], history_rows: dict[str, dict] | None,
                  history_extra: set[str] | None, old_reader) -> dict:
    """Write data/players/<pid>.json for every player in the catalogues (all levels and seasons on disk) and every
    Retrosheet-era player on the all-time leaderboards; returns players_index rows."""
    people = an.load_people()
    moves = movement_rows("mlb")
    rows: dict[str, list] = {}
    latest: dict[str, tuple] = {}
    names: dict[str, str] = {}
    # progression (round 6): the deep set on every MLB season row against that season's position group (hitters) or
    # role (SP / RP), and data/mlb/progression_ref.json (each season's peer median and middle half)
    from oddsmarkets.common import progression as PR
    have: dict[str, set] = {"hitter": set(), "pitcher": set()}
    for (lvl, s), c in cats.items():
        if lvl != "mlb":
            continue
        for kind, cat in (("hitter", c.get("hitters")), ("pitcher", c.get("pitchers"))):
            for r in ((cat or {}).get("players") or {}).values():
                have[kind].update((r.get("values") or {}).keys())
    pkeys = {kind: prog_keys(kind, have[kind]) for kind in ("hitter", "pitcher")}
    pb = PR.Builder("baseball", pkeys, dirs={"pitcher": PR.directions("baseball", ["sp", "rp"]),
                                            "hitter": PR.directions("baseball", list(dict.fromkeys(HIT_GROUP.values())))})
    lengths: dict[str, int] = {}
    pkinds: dict[str, set] = {}
    for (lvl, s), c in sorted(cats.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        for kind, cat in (("hitter", c.get("hitters")), ("pitcher", c.get("pitchers"))):
            tg = (cat or {}).get("team_games")
            if lvl == "mlb" and tg:
                lengths[str(s)] = max(lengths.get(str(s), 0), int(tg))
            for pid, r in ((cat or {}).get("players") or {}).items():
                row = season_row(lvl, s, kind, r)
                if lvl == "mlb":
                    # nested as "pr" ({dv, dp, pg}): the season rows already carry "dv" (decision value)
                    row["pr"] = pb.add(s, kind, sim_group(r, kind), r.get("values") or {}, prog_placed(r, kind, tg), pct=r.get("pct_role"))
                    pkinds.setdefault(pid, set()).add(kind)
                rows.setdefault(pid, []).append(row)
                names[pid] = r.get("name") or names.get(pid)
                latest[pid] = (lvl, s, kind, r)
    pb.finish()
    try:
        write("mlb/progression_ref.json", pb.reference(lengths=lengths))
    except Exception:            # noqa: BLE001 - the reference is an extra; the careers still write
        pass
    hcats = {k: c.get("hitters") for k, c in cats.items()}
    pcats = {k: c.get("pitchers") for k, c in cats.items()}
    hidx = similar_index(hcats, "hitter", SIMILAR_H)
    pidx = similar_index(pcats, "pitcher", SIMILAR_P)
    stores: dict[str, dict] = {}
    nums: dict[str, str] = {}
    for (lvl, s) in sorted(cats, key=lambda x: -x[1]):
        st = an.load_store(lvl, s)
        for pid, info in (st.get("players") or {}).items():
            stores.setdefault(pid, info)
        nums_now = roster_numbers(st)
        for pid, n in nums_now.items():
            nums.setdefault(pid, n)
    index: dict[str, list] = {}
    hist = history_rows or {}
    todo = set(rows) | (history_extra or set())
    for pid in todo:
        info = stores.get(pid) or {}
        pe = people.get(pid) or {}
        lv = latest.get(pid)
        cur = blocks.get(pid)
        h = hist.get(pid)
        if cur is None or (h is None and not hist):
            old = old_reader(pid) or {}
            if cur is None:
                cur = old.get("current")
            if h is None and not hist and old.get("history"):
                h = {k: v for k, v in old["history"].items() if k != "cols"}       # no Retrosheet tables here: keep
        sim = []
        if lv:
            sim = similar(pid, lv[1], hidx if lv[2] == "hitter" else pidx, names)
        name = names.get(pid) or info.get("name") or pe.get("name") or pid
        payload = {"id": pid, "name": name, "number": nums.get(pid) or info.get("num"), "bats": info.get("bats"), "throws": info.get("throws"), "pos": info.get("pos") or (lv[3].get("pos") if lv else None),
                   "dob": info.get("dob") or pe.get("birth"), "debut": info.get("debut") or pe.get("debut"),
                   "ids": {"retro": info.get("retro") or pe.get("retro"), "bbref": info.get("bbref") or pe.get("bbref"),
                           "fg": info.get("fg") or pe.get("fg")},
                   "seasons": rows.get(pid, []), "history": ({**h, "cols": {"batting": _hist_cols("batting"), "pitching": _hist_cols("pitching")}}
                                                           if h else None),
                   "current": cur, "similar": sim, "movement": moves.get(pid), "updated_at": an.now()}
        if pkinds.get(pid):
            payload["prog"] = {"v": PR.VERSION, "keys": {kd: pkeys[kd] for kd in sorted(pkinds[pid])}}
        if h:
            from oddsmarkets.baseball.analytics.history import notice_meta
            payload["meta"] = notice_meta()
        write(f"players/{pid}.json", payload)
        levels = sorted({r["level"] for r in rows.get(pid, [])})
        team = (lv[3].get("team") if lv else None)
        index[pid] = [name, team, payload["pos"], payload["bats"], payload["throws"], levels]
    return index


def _hist_cols(kind: str) -> list:
    from oddsmarkets.baseball.analytics.history import BAT_KEYS, PIT_KEYS
    return BAT_KEYS if kind == "batting" else PIT_KEYS
