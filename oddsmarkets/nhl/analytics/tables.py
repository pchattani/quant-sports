"""
The season's aggregate tables, built once per SeasonContext and shared by the catalogues, team, line, game and
career builders (`tables(ctx)`):

  pg      per (game_id, pid, team): individual counts + on-ice counts + time on ice (box.individual / onice / toi)
  gg      per (game_id, pid, team) goalie: shots / goals / xG faced by strength, danger, shot type, and TOI
  tg      per (game_id, team): team counts for / against by strength and time by strength
  combos  5v5 forward lines and defence pairs
  pos     {pid(float): "F" | "D" | "G"}
Regular season and playoffs are both in pg / gg / tg (game type in column "gt": "REG" / "PO"); the catalogues use
the regular season.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics import box


def positions(ctx, ev: pd.DataFrame) -> dict[float, str]:
    out: dict[float, str] = {}
    for pid, p in ctx.players.items():
        f = an.fnum(pid)
        if f is not None:
            out[f] = an.pos_group(p.get("pos") or p.get("position"))
    if len(ev):
        for c in ("hg", "vg", "goalie"):
            if c in ev:
                for g in pd.unique(ev[c].dropna()):
                    out.setdefault(float(g), "G")
    return out


def tables(ctx) -> dict:
    key = "_tables"
    if key in ctx._models:
        return ctx._models[key]
    t0 = time.perf_counter()
    ev = box.playable(ctx.events())
    if len(ev):
        ev = box.fix_block_team(ev)
    st = box.playable_stints(ctx.stints())
    pos = positions(ctx, ev)
    ind = box.individual(ev) if len(ev) else pd.DataFrame(columns=["game_id", "pid", "team"])
    oi = box.onice(ev) if len(ev) else pd.DataFrame(columns=["game_id", "pid", "team"])
    tt = box.toi(st) if len(st) else pd.DataFrame(columns=["game_id", "pid", "team"])
    keys = ["game_id", "pid", "team"]
    pg = ind.merge(oi, on=keys, how="outer").merge(tt, on=keys, how="outer") if len(ind) or len(oi) or len(tt) else \
        pd.DataFrame(columns=keys)
    num = [c for c in pg.columns if c not in keys]
    pg[num] = pg[num].astype(float).fillna(0.0)
    if len(pg):
        # the team a player skated for in each game is the side of the ice he was on (an event credited through the
        # "opponent" of its owner, e.g. a team-mate's blocked shot, cannot move him to the other bench)
        sides = box.side_teams(ev, st)
        if len(sides):
            pg = pg.merge(sides, on=["game_id", "pid"], how="left")
            pg["team"] = pg["side_team"].where(pg["side_team"].notna(), pg["team"])
            pg = pg.drop(columns=["side_team"]).groupby(keys, sort=False)[num].sum().reset_index()
        pg["pos"] = pg["pid"].map(lambda p: pos.get(p, "F"))
        pg = pg[pg["pos"] != "G"].reset_index(drop=True)
        pg["gt"] = np.where(pg["game_id"].astype(str).str[4:6] == "03", "PO", "REG")
    gg = box.goalie_games(ev) if len(ev) else pd.DataFrame(columns=keys)
    gt_ = box.goalie_toi(st) if len(st) else pd.DataFrame(columns=keys + ["toi"])
    if len(gg) or len(gt_):
        gg = gg.merge(gt_, on=keys, how="outer")
        n2 = [c for c in gg.columns if c not in keys]
        gg[n2] = gg[n2].astype(float).fillna(0.0)
        gg["gt"] = np.where(gg["game_id"].astype(str).str[4:6] == "03", "PO", "REG")
    tg = box.team_games(ev, st) if (len(ev) or len(st)) else pd.DataFrame(columns=["game_id", "team"])
    if len(tg):
        tg["gt"] = np.where(tg["game_id"].astype(str).str[4:6] == "03", "PO", "REG")
    ctx._ev, ctx._st = ev, st          # keep one copy: the playable frames replace the loaded ones
    out = {"ev": ev, "st": st, "pg": pg, "gg": gg, "tg": tg, "pos": pos, "has_toi": bool(len(st)), "has_events": bool(len(ev))}
    ctx._models[key] = out
    ctx.timings["tables"] = time.perf_counter() - t0
    return out


def combos(ctx) -> pd.DataFrame:
    key = "_combos"
    if key in ctx._models:
        return ctx._models[key]
    T = tables(ctx)
    st = T["st"]
    st_reg = st[st["game_id"].astype(str).str[4:6] == "02"] if len(st) else st
    ev = T["ev"]
    ev_reg = ev[ev["game_id"].astype(str).str[4:6] == "02"] if len(ev) else ev
    df = box.combos(ev_reg, st_reg, T["pos"]) if len(st_reg) else pd.DataFrame()
    ctx._models[key] = df
    return df


def season_agg(pg: pd.DataFrame, gt: str = "REG") -> pd.DataFrame:
    """Per pid: sums over the season's games of type gt, gp, and team (the team of the latest game) and teams."""
    if not len(pg):
        return pd.DataFrame()
    P = pg[pg["gt"] == gt] if gt else pg
    if not len(P):
        return pd.DataFrame()
    num = [c for c in P.columns if c not in ("game_id", "pid", "team", "pos", "gt")]
    agg = P.groupby("pid")[num].sum()
    agg["gp"] = P.groupby("pid")["game_id"].nunique()
    last = P.sort_values("game_id").groupby("pid").tail(1).set_index("pid")["team"]
    agg["team"] = last
    teams = P.groupby("pid")["team"].agg(lambda s: list(dict.fromkeys(s)))
    agg["teams"] = teams
    return agg
