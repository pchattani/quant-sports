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
SIMILAR_H = ["k_pct", "bb_pct", "iso", "xwoba_savant", "barrel_pct", "chase_pct", "whiff_pct", "ev", "pull_air_pct", "gb_pct", "sprint_speed"]
SIMILAR_P = ["k_pct", "bb_pct", "gb_pct", "fb_velo", "fb_ivb", "whiff_pct", "chase_pct", "csw_pct", "fb_usage", "br_usage", "hard_pct"]


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
            blk["pitch_zones"] = zp.get(pid)
            blk["movement"] = move.get(pid)
            blk["release"] = (phys.get(pid) or {}).get("release")
            t = tun.get(pid) or {}
            blk["tunnels"] = [{"pair": k, **v} for k, v in (t.get("by_pair") or {}).items()] or None
            f = fat.get(pid) or {}
            blk["fatigue"] = {k: v for k, v in f.items()} if f else None
            blk["pitching_rolling"] = prl.get(pid)
        blk["splits"] = splits.get(pid)
        pj = None
        for kind in ("hitters", "pitchers"):
            if (proj.get(kind) or {}).get(pid):
                pj = {"kind": kind[:-1], "season": ctx.season + 1, **proj[kind][pid]}
        blk["projection"] = pj
        out[pid] = blk
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


def similar_index(cats: dict[tuple, dict], kind: str, keys: list[str], min_n: int = 200):
    pts, ids = [], []
    for (lvl, s), c in cats.items():
        if lvl != "mlb" or not c:
            continue
        for pid, r in (c.get("players") or {}).items():
            if (r.get("pa" if kind == "hitter" else "bf") or 0) < min_n:
                continue
            v = [an.fnum((r.get("values") or {}).get(k)) for k in keys]
            if sum(x is None for x in v) > 2:
                continue
            pts.append(v)
            ids.append((pid, s))
    if len(pts) < 10:
        return None
    X = np.array([[np.nan if x is None else x for x in p] for p in pts], float)
    mu, sd = np.nanmean(X, 0), np.nanstd(X, 0)
    sd[sd == 0] = 1
    Z = np.nan_to_num((X - mu) / sd)
    return {"Z": Z, "ids": ids, "mu": mu, "sd": sd, "pos": {k: i for i, k in enumerate(ids)}}


def similar(pid: str, season: int, idx, names: dict, k: int = 6) -> list:
    if idx is None or (pid, season) not in idx["pos"]:
        return []
    i = idx["pos"][(pid, season)]
    d = np.sqrt(((idx["Z"] - idx["Z"][i]) ** 2).sum(1))
    out = []
    for j in np.argsort(d):
        q, s = idx["ids"][j]
        if q == pid:
            continue
        out.append({"pid": q, "season": s, "name": names.get(q), "distance": round(float(d[j]), 3)})
        if len(out) >= k:
            break
    return out


def write_careers(write, cats: dict[tuple, dict], blocks: dict[str, dict], history_rows: dict[str, dict] | None,
                  history_extra: set[str] | None, old_reader) -> dict:
    """Write data/players/<pid>.json for every player in the catalogues (all levels and seasons on disk) and every
    Retrosheet-era player on the all-time leaderboards; returns players_index rows."""
    people = an.load_people()
    rows: dict[str, list] = {}
    latest: dict[str, tuple] = {}
    names: dict[str, str] = {}
    for (lvl, s), c in sorted(cats.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        for kind, cat in (("hitter", c.get("hitters")), ("pitcher", c.get("pitchers"))):
            for pid, r in ((cat or {}).get("players") or {}).items():
                rows.setdefault(pid, []).append(season_row(lvl, s, kind, r))
                names[pid] = r.get("name") or names.get(pid)
                latest[pid] = (lvl, s, kind, r)
    hcats = {k: c.get("hitters") for k, c in cats.items()}
    pcats = {k: c.get("pitchers") for k, c in cats.items()}
    hidx = similar_index(hcats, "hitter", SIMILAR_H)
    pidx = similar_index(pcats, "pitcher", SIMILAR_P)
    stores: dict[str, dict] = {}
    for (lvl, s) in sorted(cats, key=lambda x: -x[1]):
        for pid, info in (an.load_store(lvl, s).get("players") or {}).items():
            stores.setdefault(pid, info)
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
        if lv and lv[0] == "mlb":
            sim = similar(pid, lv[1], hidx if lv[2] == "hitter" else pidx, names)
        name = names.get(pid) or info.get("name") or pe.get("name") or pid
        payload = {"id": pid, "name": name, "bats": info.get("bats"), "throws": info.get("throws"), "pos": info.get("pos") or (lv[3].get("pos") if lv else None),
                   "dob": info.get("dob") or pe.get("birth"), "debut": info.get("debut") or pe.get("debut"),
                   "ids": {"retro": info.get("retro") or pe.get("retro"), "bbref": info.get("bbref") or pe.get("bbref"),
                           "fg": info.get("fg") or pe.get("fg")},
                   "seasons": rows.get(pid, []), "history": ({**h, "cols": {"batting": _hist_cols("batting"), "pitching": _hist_cols("pitching")}}
                                                           if h else None),
                   "current": cur, "similar": sim, "updated_at": an.now()}
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
