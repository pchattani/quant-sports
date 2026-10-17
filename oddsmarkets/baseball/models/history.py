"""
Careers and all-time leaderboards, 1908 onward (Retrosheet event files start in 1908; its 1901-1907 box-score
files are not read, so there are no player seasons before 1908; history.json `first` = 1908).

Seasons with Retrosheet event files come from builder A's PA tables (one season in memory at a time);
seasons after the last Retrosheet year (2026 until Retrosheet publishes it) come from the Statcast PA
table. Per player-season: counting stats (PA, AB, H, 2B, 3B, HR, BB, IBB, HBP, K, SF, SH), wOBA with the
season's own weights (re24), batting runs, era-adjusted wRC+-style index

    wRC+ = 100 * (wRAA / PA + lgR/PA) / (lgR/PA)        (league = that season; not park-adjusted)

and Bullpen WAR (war.historical_season; fielding is a proxy before Statcast, flagged). Pitchers: BF,
outs, runs, K, BB, HR, RA9 and the era index RA9- = 100 * RA9 / lgRA9 (lower is better), WAR.

Careers sum the seasons (wRC+ and RA9- recomputed from summed components so they are PA/IP
weighted). Ids: MLBAM pid when the Chadwick crosswalk knows the Retrosheet id, else "r:<retroid>".

Lahman cross-check (`lahman_check`): per season, the share of player-seasons whose Retrosheet H and HR
equal Lahman's (stints summed), with the largest disagreements listed.
"""
from __future__ import annotations


import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _c

MODEL_VERSION = "hist-2"
MIN_PA_RATE = 3000
MIN_OUTS_RATE = 4500        # 1,500 innings
COUNT_COLS = ["pa", "ab", "h", "b2", "b3", "hr", "bb", "ibb", "hbp", "k", "sf", "sh"]


def _crosswalk(people: dict) -> tuple[dict, dict]:
    r2m = {v.get("retro"): k for k, v in people.items() if isinstance(v, dict) and v.get("retro") and not str(k).startswith("r:")}
    names = {k: v.get("name") for k, v in people.items() if isinstance(v, dict)}
    return r2m, names


def retro_lines(season: int, df: pd.DataFrame | None = None, people: dict | None = None) -> dict | None:
    """Batter and pitcher season lines from one Retrosheet season."""
    from oddsmarkets.baseball.models import re24, war
    df = _c.load_pa(season) if df is None else df
    if df is None or not len(df):
        return None
    for c in df.columns:
        if isinstance(df[c].dtype, pd.CategoricalDtype):
            df[c] = df[c].astype(object)
    r2m = _c.retro_maps(people)["r2m"]
    res = re24.retro_season(season, df, with_wpa=False)
    pa = res["pa"]
    lw = res["lw"]
    bat = _count_lines(pa, "batter", lw)
    lg_rpa = float(lw["runs_per_pa"])
    pit = _pitch_lines(df, pa)
    hw = war.historical_season(season, df, people)
    if hw is not None:
        wb = pd.Series(hw["batters"]["war"].to_numpy(), index=hw["batters"]["retro"].to_numpy())
        wp = pd.Series(hw["pitchers"]["war_ra9"].to_numpy(), index=hw["pitchers"]["retro"].to_numpy())
        bat["war"] = wb.reindex(bat.index).fillna(0.0)
        pit["war"] = wp.reindex(pit.index).fillna(0.0)
    bat["season"] = season
    pit["season"] = season
    bat["lg_rpa"] = lg_rpa
    pit["lg_ra9"] = float(lw["runs_per_inning"]) * 9
    bat["retro"] = bat.index
    pit["retro"] = pit.index
    bat.index = [r2m.get(r, f"r:{r}") for r in bat.index]
    pit.index = [r2m.get(r, f"r:{r}") for r in pit.index]
    return {"batters": bat, "pitchers": pit, "lw": lw}


def _count_lines(pa: pd.DataFrame, by: str, lw: dict) -> pd.DataFrame:
    c = pa["cls"]
    sf = pa["sf"].astype(bool) if "sf" in pa else pa.get("events", pd.Series("", index=pa.index)).astype(str).eq("sac_fly")
    sh = pa["sh"].astype(bool) if "sh" in pa else pa.get("events", pd.Series("", index=pa.index)).astype(str).eq("sac_bunt")
    d = pd.DataFrame({"who": pa[by].astype(str).to_numpy(),
                      "pa": 1.0, "h": c.isin(["1B", "2B", "3B", "HR"]).astype(float).to_numpy(),
                      "b2": (c == "2B").astype(float).to_numpy(), "b3": (c == "3B").astype(float).to_numpy(),
                      "hr": (c == "HR").astype(float).to_numpy(), "bb": (c == "BB").astype(float).to_numpy(),
                      "ibb": (c == "IBB").astype(float).to_numpy(), "hbp": (c == "HBP").astype(float).to_numpy(),
                      "k": (c == "K").astype(float).to_numpy(), "sf": sf.astype(float).to_numpy(),
                      "sh": sh.astype(float).to_numpy(), "ci": (c == "CI").astype(float).to_numpy()})
    w = lw["woba_w"]
    d["wnum"] = (w.get("BB", 0.69) * d["bb"] + w.get("HBP", 0.72) * d["hbp"] + w.get("1B", 0.88) * (d["h"] - d["b2"] - d["b3"] - d["hr"])
                 + w.get("2B", 1.25) * d["b2"] + w.get("3B", 1.58) * d["b3"] + w.get("HR", 2.03) * d["hr"])
    d["den"] = d["pa"] - d["ibb"] - d["sh"] - d["ci"]
    g = d.groupby("who").sum(numeric_only=True)
    g["ab"] = g["pa"] - g["bb"] - g["ibb"] - g["hbp"] - g["sf"] - g["sh"] - g["ci"]
    lg = float(g["wnum"].sum() / max(g["den"].sum(), 1))
    scale = float(lw.get("woba_scale") or 1.2)
    g["woba"] = g["wnum"] / g["den"].replace(0, np.nan)
    g["wraa"] = (g["woba"].fillna(lg) - lg) / scale * g["den"]
    return g.drop(columns=["ci"])


def _pitch_lines(df: pd.DataFrame, pa: pd.DataFrame) -> pd.DataFrame:
    rows = df[df["gtype"].astype(str) == "R"] if "gtype" in df else df
    g = rows.groupby(rows["pitcher"].astype(str))
    t = pd.DataFrame({"outs": g["outs_on_play"].sum(), "runs": g["runs_on_play"].sum(), "games": g["game_id"].nunique()})
    c = pa["cls"]
    pg = pd.DataFrame({"who": pa["pitcher"].astype(str).to_numpy(), "bf": 1.0, "k": (c == "K").astype(float).to_numpy(),
                       "bb": c.isin(["BB", "IBB"]).astype(float).to_numpy(), "hr": (c == "HR").astype(float).to_numpy(),
                       "h": c.isin(["1B", "2B", "3B", "HR"]).astype(float).to_numpy()}).groupby("who").sum()
    t = t.join(pg, how="left").fillna(0.0)
    return t


def statcast_lines(level: str, season: int) -> dict | None:
    """Season lines for a Statcast season without Retrosheet (2026): counts from the pitch table, WAR from war.py."""
    from oddsmarkets.baseball.models import re24, war
    rs = re24.statcast_season(level, season, with_wpa=False, count=False)
    if rs is None:
        return None
    pa = rs["pa"]
    lw = rs["lw"]
    bat = _count_lines(pa.assign(batter=pa["batter"].map(war._sid)), "batter", lw)
    pa2 = pa.assign(pid=pa["pitcher"].map(war._sid))
    pa2["outs_rec"] = (np.minimum(pa2["end_outs"], 3) - pa2["outs_when_up"]).clip(lower=0)
    c = pa2["cls"]
    pg = pd.DataFrame({"who": pa2["pid"], "bf": 1.0, "outs": pa2["outs_rec"], "runs": pa2["runs_pa"],
                       "k": (c == "K").astype(float), "bb": c.isin(["BB", "IBB"]).astype(float),
                       "hr": (c == "HR").astype(float), "h": c.isin(["1B", "2B", "3B", "HR"]).astype(float)}).groupby("who").sum()
    pg["games"] = pa2.groupby("pid")["game_pk"].nunique()
    w = war.for_season(level, season)
    if w.get("ok"):
        wb = pd.DataFrame(w["batters"]["rows"], columns=w["batters"]["cols"]).set_index("pid")["war"]
        wp = pd.DataFrame(w["pitchers"]["rows"], columns=w["pitchers"]["cols"]).set_index("pid")["war_ra9"]
        bat["war"] = wb.reindex(bat.index).astype(float).fillna(0.0)
        pg["war"] = wp.reindex(pg.index).astype(float).fillna(0.0)
    bat["season"] = season; pg["season"] = season
    bat["lg_rpa"] = float(lw["runs_per_pa"]); pg["lg_ra9"] = float(lw["runs_per_inning"]) * 9
    return {"batters": bat, "pitchers": pg, "lw": lw}


# ============================================================================ careers

def season_rows(level: str = "mlb", seasons: list[int] | None = None, people: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Player-season rows over all seasons (Retrosheet first, Statcast for later seasons), one at a time."""
    retro = _c.retro_seasons()
    stat = _c.pitch_seasons(level)
    last_retro = max(retro) if retro else 0
    plan = [("retro", s) for s in retro] + [("statcast", s) for s in stat if s > last_retro]
    if seasons:
        plan = [x for x in plan if x[1] in set(seasons)]
    people = people if people is not None else _c.load_people()
    bats, pits = [], []
    for kind, s in plan:
        r = _cached_lines(kind, s, level, people)
        if r is None:
            continue
        bats.append(r[0]); pits.append(r[1])
    b = pd.concat(bats) if bats else pd.DataFrame()
    p = pd.concat(pits) if pits else pd.DataFrame()
    return b, p


def _cached_lines(kind: str, season: int, level: str, people: dict):
    path = _c.pa_path(season) if kind == "retro" else _c.pitch_path(level, season)
    cp = _c.cache_root() / "history" / f"{kind}_{season}.parquet"
    kp = cp.with_suffix(".key")
    from oddsmarkets.baseball.models import war as _war
    key = _c.file_key(path, MODEL_VERSION, _war.MODEL_VERSION)
    try:
        if cp.exists() and kp.exists() and kp.read_text() == key:
            d = pd.read_parquet(cp)
            return d[d["role"] == "bat"].drop(columns="role").set_index("pid"), d[d["role"] == "pit"].drop(columns="role").set_index("pid")
    except Exception:
        pass
    r = retro_lines(season, people=people) if kind == "retro" else statcast_lines(level, season)
    if r is None:
        return None
    b = r["batters"].assign(role="bat"); p = r["pitchers"].assign(role="pit")
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        allr = pd.concat([b, p]).rename_axis("pid").reset_index()
        for c in allr.columns:
            if allr[c].dtype == object:
                allr[c] = allr[c].astype(str)
        allr.to_parquet(cp, index=False)
        kp.write_text(key)
    except Exception:
        pass
    return r["batters"], r["pitchers"]


def careers(b: pd.DataFrame, p: pd.DataFrame, names: dict | None = None) -> dict[str, pd.DataFrame]:
    out = {}
    if len(b):
        bb = b.copy()
        bb["lgr"] = bb["lg_rpa"] * bb["pa"]
        cols = [c for c in COUNT_COLS + ["wraa", "war", "lgr", "wnum", "den"] if c in bb]
        g = bb.groupby(level=0)
        cb = g[cols].sum()
        cb["first"] = g["season"].min(); cb["last"] = g["season"].max(); cb["seasons"] = g["season"].nunique()
        cb["wrc_plus"] = 100 * (cb["wraa"] + cb["lgr"]) / cb["lgr"].replace(0, np.nan)
        cb["woba"] = cb["wnum"] / cb["den"].replace(0, np.nan) if "wnum" in cb else np.nan
        out["batters"] = cb
    if len(p):
        pp = p.copy()
        pp["lgruns"] = pp["lg_ra9"] * pp["outs"] / 27.0
        cols = [c for c in ("bf", "outs", "runs", "k", "bb", "hr", "h", "war", "lgruns", "games") if c in pp]
        g = pp.groupby(level=0)
        cp = g[cols].sum()
        cp["first"] = g["season"].min(); cp["last"] = g["season"].max()
        cp["ip"] = cp["outs"] / 3
        cp["ra9"] = 27 * cp["runs"] / cp["outs"].replace(0, np.nan)
        cp["ra9_minus"] = 100 * cp["runs"] / cp["lgruns"].replace(0, np.nan)
        out["pitchers"] = cp
    if "batters" in out or "pitchers" in out:
        wb = out["batters"]["war"] if "batters" in out and "war" in out["batters"] else pd.Series(dtype=float)
        wp = out["pitchers"]["war"] if "pitchers" in out and "war" in out["pitchers"] else pd.Series(dtype=float)
        idx = wb.index.union(wp.index)
        tot = pd.DataFrame({"war_bat": wb.reindex(idx).fillna(0.0), "war_pit": wp.reindex(idx).fillna(0.0)})
        tot["war"] = tot["war_bat"] + tot["war_pit"]
        out["total"] = tot
    if names:
        for k in out:
            out[k]["name"] = [names.get(i) for i in out[k].index]
    return out


def leaderboards(car: dict[str, pd.DataFrame], n: int = 50) -> dict:
    out = {}
    b = car.get("batters")
    if b is not None and len(b):
        for key, asc, filt in (("war", False, None), ("wraa", False, None), ("hr", False, None), ("h", False, None),
                               ("wrc_plus", False, MIN_PA_RATE)):
            d = b if filt is None else b[b["pa"] >= filt]
            out[f"bat_{key}"] = _c.frame_rows(d.sort_values(key, ascending=asc).head(n).reset_index().rename(columns={"index": "pid"}))
    p = car.get("pitchers")
    if p is not None and len(p):
        for key, asc, filt in (("war", False, None), ("k", False, None), ("ra9_minus", True, MIN_OUTS_RATE)):
            d = p if filt is None else p[p["outs"] >= filt]
            out[f"pit_{key}"] = _c.frame_rows(d.sort_values(key, ascending=asc).head(n).reset_index().rename(columns={"index": "pid"}))
    t = car.get("total")
    if t is not None and len(t):
        out["all_war"] = _c.frame_rows(t.sort_values("war", ascending=False).head(n).reset_index().rename(columns={"index": "pid"}))
    return out


def build(level: str = "mlb", n: int = 50) -> dict:
    """Careers and leaderboards over every season on disk (cached per season)."""
    people = _c.load_people()
    b, p = season_rows(level, people=people)
    maps = _c.retro_maps(people)
    names = dict(maps["name"])
    car = careers(b, p, names)
    return {"ok": bool(len(b) or len(p)), "version": MODEL_VERSION,
            "seasons": sorted(set(b["season"].astype(int))) if len(b) else [], "leaders": leaderboards(car, n),
            "n_batters": int(len(car.get("batters", []))), "n_pitchers": int(len(car.get("pitchers", [])))}


def player_career(pid: str, b: pd.DataFrame, p: pd.DataFrame) -> dict:
    """Season-by-season rows for one player (for the player page's career table)."""
    out = {}
    if len(b) and pid in b.index:
        out["batting"] = _c.frame_rows(b.loc[[pid]].reset_index(drop=True))
    if len(p) and pid in p.index:
        out["pitching"] = _c.frame_rows(p.loc[[pid]].reset_index(drop=True))
    return out


# ============================================================================ Lahman cross-check

def lahman_check(season: int, b: pd.DataFrame | None = None, people: dict | None = None) -> dict:
    try:
        from oddsmarkets.baseball.sources import lahman
        lb = lahman.load("Batting.csv")
    except Exception:
        lb = None
    if lb is None:
        return {"ok": False, "reason": "Lahman Batting.csv not cached"}
    if b is None:
        r = retro_lines(season, people=people)
        if r is None:
            return {"ok": False, "reason": "no Retrosheet season"}
        b = r["batters"]
    retro2bb = _c.retro_maps(people)["r2b"]
    l = lb[lb["yearID"] == int(season)].groupby("playerID")[["H", "HR", "BB", "SO"]].sum()
    x = b.copy()
    x["bbref"] = x["retro"].map(retro2bb)
    m = x.dropna(subset=["bbref"]).set_index("bbref").join(l, how="inner")
    if not len(m):
        return {"ok": False, "reason": "no id matches"}
    out = {"ok": True, "season": season, "players": int(len(m)),
           "h_exact": float((m["h"] == m["H"]).mean()), "hr_exact": float((m["hr"] == m["HR"]).mean()),
           "bb_exact": float((m["bb"] + m["ibb"] == m["BB"]).mean()), "so_exact": float((m["k"] == m["SO"]).mean()),
           "h_total": [float(m["h"].sum()), float(m["H"].sum())], "hr_total": [float(m["hr"].sum()), float(m["HR"].sum())]}
    m["dh"] = (m["h"] - m["H"]).abs()
    out["worst"] = m.sort_values("dh", ascending=False).head(5)[["h", "H", "hr", "HR"]].reset_index().values.tolist()
    return out


def export_fits(level: str = "mlb") -> dict:
    """History is an output table, not a fit; nothing is committed beyond the RE/linear-weight fits."""
    return {"ok": True}
