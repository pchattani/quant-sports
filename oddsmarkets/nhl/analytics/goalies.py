"""
goalies.json: the goalie catalogue for one season's regular season.

Goals saved above expected (GSAx = xG of the unblocked attempts faced minus goals allowed) overall, by danger band
(xG < 0.08 low, 0.08-0.20 medium, 0.20+ high), by shot type and by strength; save percentages; workload (shots and
expected goals faced per 60, average shot quality, high-danger share, starts, back-to-back starts); quality starts;
rebound control; builder B's shrunk GSAx and Rink value; EDGE save percentages by distance (2021-22 onward).
Percentiles as in the skater catalogue (qualified pool: a quarter of the team's minutes; floor 100 unblocked
attempts faced; metrics with no denominator, GSAx totals and Rink value among them, need FLOORS["gp"] games),
shrinkage on the unblocked attempts faced.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics import adapters, edge, tables
from oddsmarkets.nhl.analytics.context import SeasonContext

M = an.metric
FLOORS = {"fa": 100.0, "gp": 3.0}
METRICS = [
    M("gp", "Games", "Workload", "int", pct=False, desc="Games played."),
    M("gs", "Starts", "Workload", "int", pct=False, desc="Games started (in net for the first event)."),
    M("toi", "TOI (min)", "Workload", "toi_min", pct=False, desc="Minutes played."),
    M("w", "Wins", "Results", "int", desc="Decisions credited to the goalie with the most time in the game."),
    M("l", "Losses", "Results", "int", pct=False, desc="Regulation losses."),
    M("otl", "OT / SO losses", "Results", "int", pct=False, desc="Overtime and shootout losses."),
    M("sa", "Shots against", "Workload", "int", pct=False, desc="Shots on goal faced."),
    M("fa", "Unblocked attempts faced", "Workload", "int", pct=False,
      desc="Unblocked shot attempts faced (shots on goal plus misses; empty-net attempts excluded): the sample behind GSAx / 100."),
    M("ga", "Goals against", "Results", "int", pct=False, desc="Goals allowed (empty-net goals excluded)."),
    M("sv_pct", "Save %", "Results", "3", den="fa", k=2000, stab="g_sv_pct", desc="Saves per shot on goal."),
    M("gaa", "GAA", "Results", "2", lower=True, den="fa", k=2000, desc="Goals against per 60."),
    M("gsax", "GSAx", "Expected goals", "goals", desc="xG of the unblocked attempts faced minus goals allowed (positive = better)."),
    M("gsax60", "GSAx / 60", "Expected goals", "3", den="fa", k=1200, stab="gsax60", desc="GSAx per 60 minutes."),
    M("gsax100", "GSAx / 100 attempts", "Expected goals", "3", den="fa", k=1200, stab="gsax100", desc="GSAx per 100 unblocked attempts faced."),
    M("dfsv_pct", "dFSv%", "Expected goals", "pct", den="fa", k=1200, desc="Unblocked save % minus expected unblocked save %."),
    M("xfsv_pct", "Expected FSv%", "Expected goals", "pct", pct=False, desc="1 minus mean xG per unblocked attempt faced (shot difficulty)."),
    M("gsax_low", "GSAx low danger", "By danger", "goals", desc="GSAx on attempts with xG under 0.08."),
    M("gsax_med", "GSAx medium danger", "By danger", "goals", desc="GSAx on attempts with xG 0.08-0.20."),
    M("gsax_high", "GSAx high danger", "By danger", "goals", desc="GSAx on attempts with xG 0.20 or more."),
    M("sv_pct_low", "Low-danger sv%", "By danger", "pct", den="fa", k=3000, desc="Save % on low-danger shots on goal."),
    M("sv_pct_med", "Medium-danger sv%", "By danger", "pct", den="fa", k=2000, desc="Save % on medium-danger shots on goal."),
    M("sv_pct_high", "High-danger sv%", "By danger", "pct", den="fa", k=1500, stab="g_hd_sv_pct", desc="Save % on high-danger shots on goal."),
    M("gsax_wrist", "GSAx wrist / snap", "By shot type", "goals", desc="GSAx on wrist and snap shots."),
    M("gsax_slap", "GSAx slap", "By shot type", "goals", desc="GSAx on slap shots."),
    M("gsax_tip", "GSAx tips", "By shot type", "goals", desc="GSAx on tips and deflections."),
    M("gsax_back", "GSAx backhand", "By shot type", "goals", desc="GSAx on backhands."),
    M("gsax_5v5", "GSAx 5v5", "By strength", "goals", desc="GSAx at 5v5."),
    M("gsax_sh", "GSAx short-handed", "By strength", "goals", desc="GSAx with the goalie's team short-handed."),
    M("sv_pct_5v5", "5v5 sv%", "By strength", "pct", den="fa", k=2000, desc="Save % at 5v5."),
    M("sv_pct_sh", "PK sv%", "By strength", "pct", den="fa", k=1500, desc="Save % short-handed."),
    M("sa60", "Shots against / 60", "Workload", "2", pct=False, desc="Shots on goal faced per 60."),
    M("xga60", "xGA / 60", "Workload", "2", pct=False, desc="Expected goals faced per 60 (difficulty of the workload)."),
    M("xg_per_shot", "xG per attempt", "Workload", "3", pct=False, desc="Mean xG of the unblocked attempts faced."),
    M("hd_share", "High-danger share", "Workload", "pct", pct=False, desc="Share of unblocked attempts faced that were high danger."),
    M("start_share", "Start share", "Workload", "pct", pct=False, desc="Share of the team's games started."),
    M("b2b_starts", "Back-to-back starts", "Workload", "int", pct=False, desc="Starts on the second night of a back-to-back."),
    M("qs_pct", "Quality start %", "Results", "pct", den="gp", k=30, desc="Starts with sv% above the league average (or .885 on 20 "
      "shots or fewer)."),
    M("rbs", "Really bad starts", "Results", "int", lower=True, pct=False, desc="Starts with sv% under .850."),
    M("reb_rate", "Rebound rate", "Rebound control", "pct", lower=True, den="fa", k=1500, desc="Saves followed within 3 s by another "
      "attempt by the shooting team, per save."),
    M("gsax_shrunk", "GSAx (shrunk)", "Model", "goals", desc="GSAx regressed toward zero by its stabilisation constant."),
    M("gsax_m", "GSAx (model)", "Model", "goals", desc="GSAx from the expected-goals model's own table (empty nets out)."),
    M("gar", "Rink value (GAR)", "Model", "1", desc="Goals above a replacement-level goalie."),
    M("war", "Rink value (WAR)", "Model", "2", desc="GAR in wins."),
    M("edge_hd_sv_pct", "EDGE high-danger sv%", "EDGE tracking", "pct", desc="NHL EDGE save % from high-danger areas."),
    M("edge_md_sv_pct", "EDGE mid-range sv%", "EDGE tracking", "pct", desc="NHL EDGE save % from mid-range."),
    M("edge_ld_sv_pct", "EDGE long-range sv%", "EDGE tracking", "pct", desc="NHL EDGE save % from long range."),
]
KEYS = [m["key"] for m in METRICS]


def decisions(ctx, gg: pd.DataFrame) -> dict[tuple, str]:
    """{(game_id, goalie pid): "w" | "l" | "otl"}: the goalie of record from the boxscore (the store's
    games[gid].goalies[side].decision: the goalie in net for the deciding goal), else the one with the most time.

    The NHL credits the decision to the goalie in net when the winning goal is scored, not to the one who played
    longer: a starter pulled after the deciding goal keeps the loss and his reliever gets no decision."""
    out = {}
    if not len(gg):
        return out
    pick = []
    for (gid, team), grp in gg.groupby(["game_id", "team"], sort=False):
        g = ctx.games.get(gid) or {}
        side = "home" if team == g.get("home") else "away" if team == g.get("away") else None
        off = an.inum((((g.get("goalies") or {}).get(side) or {}).get("decision")) if side else None)
        hit = grp[[an.inum(p) == off for p in grp["pid"]]] if off is not None else grp.iloc[0:0]
        pick.append(hit.iloc[0] if len(hit) else grp.sort_values("toi", ascending=False).iloc[0])
    top = pd.DataFrame(pick) if pick else gg.iloc[0:0]
    for r in top.itertuples(index=False):
        g = ctx.games.get(r.game_id) or {}
        hs, as_ = an.inum(g.get("hs")), an.inum(g.get("as"))
        if hs is None or as_ is None or hs == as_ or g.get("status") != "final":
            continue
        home = r.team == g.get("home")
        won = (hs > as_) == home
        extra = bool(g.get("ot") or g.get("so")) or (str(g.get("period") or "") not in ("", "3") and an.inum(g.get("period")) not in (None, 3))
        out[(r.game_id, r.pid)] = "w" if won else ("otl" if extra else "l")
    return out


def starters(T: dict) -> dict[str, dict[str, float]]:
    """{game_id: {team: goalie pid}}: the goalie in net for the team's first stint (or first shot faced)."""
    out: dict[str, dict[str, float]] = {}
    st = T["st"]
    if len(st) and "hg" in st:
        first = st.sort_values(["game_id", "start"] if "start" in st else ["game_id"]).drop_duplicates("game_id")
        for r in first.itertuples(index=False):
            d = out.setdefault(r.game_id, {})
            if r.hg == r.hg:
                d[r.home_team] = r.hg
            if r.vg == r.vg:
                d[r.away_team] = r.vg
    ev = T["ev"]
    if len(ev):
        for side, gcol, tcol in (("h", "hg", "home_team"), ("v", "vg", "away_team")):
            f = ev[ev[gcol].notna()].drop_duplicates("game_id")
            for r in f[["game_id", gcol, tcol]].itertuples(index=False):
                out.setdefault(r[0], {}).setdefault(r[2], r[1])
    return out


def build(ctx: SeasonContext) -> dict | None:
    T = tables.tables(ctx)
    gg = T["gg"]
    if not len(gg):
        return None
    G = gg[gg["gt"] == "REG"]
    if not len(G):
        return None
    dec = decisions(ctx, G)
    stt = starters(T)
    start_set = {(g, p) for g, d in stt.items() for p in d.values()}
    num = [c for c in G.columns if c not in ("game_id", "pid", "team", "gt")]
    agg = G.groupby("pid")[num].sum()
    agg["gp"] = G.groupby("pid")["game_id"].nunique()
    agg["team"] = G.sort_values("game_id").groupby("pid").tail(1).set_index("pid")["team"]
    # league average sv% (quality starts) and b2b
    lg_sv = 1 - G["ga"].sum() / G["sa"].sum() if G["sa"].sum() else 0.9
    b2b = _b2b(ctx)
    team_games = {}
    for gid, g in ctx.games.items():
        if g.get("gtype") == "REG" and g.get("status") == "final":
            for t in (g.get("home"), g.get("away")):
                team_games[t] = team_games.get(t, 0) + 1
    per_game = G.set_index(["game_id", "pid"])
    models = adapters.player_tables(ctx)
    gv = adapters.goalie_value(ctx)
    ed = edge.goalies(ctx)
    tg_n = ctx.team_games() or 1
    rows, ref = {}, []
    for pid, r in agg.iterrows():
        p = an.sid(pid)
        rd = r.to_dict()
        f = lambda k: an.fnum(rd.get(k)) or 0.0  # noqa: E731
        toi = f("toi")
        v = {"gp": f("gp"), "toi": toi / 60.0 if toi else None, "sa": f("sa"), "ga": f("ga")}
        mine = [(g, pid) for g in G.loc[G["pid"] == pid, "game_id"]]
        starts = [k for k in mine if k in start_set]
        v["gs"] = len(starts)
        for k in ("w", "l", "otl"):
            v[k] = sum(1 for kk in mine if dec.get(kk) == k)
        v["sv_pct"] = 1 - f("ga") / f("sa") if f("sa") else None
        v["gaa"] = an.per60(f("ga"), toi)
        v["gsax"] = f("xga") - f("ga") if f("fa") else None
        v["gsax60"] = an.per60(v["gsax"], toi) if v["gsax"] is not None else None
        v["gsax100"] = 100 * v["gsax"] / f("fa") if f("fa") else None
        v["xfsv_pct"] = 1 - f("xga") / f("fa") if f("fa") else None
        v["dfsv_pct"] = ((1 - f("ga") / f("fa")) - v["xfsv_pct"]) if f("fa") else None
        for b in ("low", "med", "high"):
            v[f"gsax_{b}"] = f(f"xga_{b}") - f(f"ga_{b}") if f(f"fa_{b}") else None
            v[f"sv_pct_{b}"] = 1 - f(f"ga_{b}") / f(f"sa_{b}") if f(f"sa_{b}") else None
        for t in ("wrist", "slap", "tip", "back"):
            v[f"gsax_{t}"] = f(f"xga_{t}") - f(f"ga_{t}") if f(f"fa_{t}") else None
        v["gsax_5v5"] = f("xga_5v5") - f("ga_5v5") if f("fa_5v5") else None
        v["gsax_sh"] = f("xga_SH") - f("ga_SH") if f("fa_SH") else None
        v["sv_pct_5v5"] = 1 - f("ga_5v5") / f("sa_5v5") if f("sa_5v5") else None
        v["sv_pct_sh"] = 1 - f("ga_SH") / f("sa_SH") if f("sa_SH") else None
        v["sa60"], v["xga60"] = an.per60(f("sa"), toi), an.per60(f("xga"), toi)
        v["xg_per_shot"] = an.div(f("xga"), f("fa"))
        v["hd_share"] = an.div(f("fa_high"), f("fa"))
        v["start_share"] = an.div(len(starts), team_games.get(rd.get("team")))
        v["b2b_starts"] = sum(1 for g, _ in starts if (g, rd.get("team")) in b2b)
        qs = rbs = 0
        for g, _ in starts:
            try:
                row = per_game.loc[(g, pid)]
            except KeyError:
                continue
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            sa_, ga_ = float(row["sa"]), float(row["ga"])
            if not sa_:
                continue
            sv = 1 - ga_ / sa_
            qs += int(sv >= lg_sv or (sa_ <= 20 and sv >= 0.885))
            rbs += int(sv < 0.85)
        v["qs_pct"] = qs / len(starts) if starts else None
        v["rbs"] = rbs
        saves = f("sa") - f("ga")
        v["reb_rate"] = f("reb") / saves if saves else None
        v["fa"] = f("fa")
        for k, d in models.items():
            if k in ("gsax_m", "gsax_shrunk") and p in d:
                v[k] = d[p]
        for k, d in gv.items():
            if p in d:
                v[k] = d[p]
        for k, x in (ed.get(p) or {}).items():
            v[k] = x
        info = ctx.players.get(p) or {}
        qualified = toi >= 0.25 * tg_n * 3600.0
        rows[p] = {"name": ctx.player_name(p) or p, "team": rd.get("team"), "pos": "G", "group": "G",
                   "age": an.age_on(info.get("dob"), ctx.season), "gp": int(v["gp"]), "toi": an.rnd(toi / 60.0, 1), "qualified": qualified,
                   "catches": info.get("shoots") or info.get("catches"), "values": v, "n": {"fa": f("fa"), "gp": f("gp")}}
        if qualified:
            ref.append(p)
    an.finish(rows, METRICS, ref, {p: "G" for p in rows}, FLOORS)
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "phase": ctx.phase, "team_games": tg_n, "kind": "goalie",
            "metrics": [an.public_metric(m) for m in METRICS], "players": rows,
            "reference": {"n": len(ref), "min_toi": round(0.25 * tg_n * 60), "floors": FLOORS, "league_sv_pct": an.rnd(lg_sv, 4)},
            "danger_bands": {"low": [0, 0.08], "med": [0.08, 0.20], "high": [0.20, 1]}, "xg_source": ctx.xg_source,
            "model_errors": dict(ctx.model_errors)}


def _b2b(ctx) -> set[tuple]:
    """{(game_id, team)} for the second game of a back-to-back."""
    by_team: dict[str, list] = {}
    for gid, g in ctx.games.items():
        if g.get("gtype") not in ("REG", "PO") or not g.get("date"):
            continue
        try:
            d = date.fromisoformat(str(g["date"])[:10])
        except ValueError:
            continue
        for t in (g.get("home"), g.get("away")):
            by_team.setdefault(t, []).append((d, gid))
    out = set()
    for t, xs in by_team.items():
        xs.sort()
        for (d0, _), (d1, g1) in zip(xs, xs[1:]):
            if (d1 - d0).days == 1:
                out.add((g1, t))
    return out
