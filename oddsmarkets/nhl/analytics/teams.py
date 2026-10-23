"""
teams.json: per team unit ratings (5v5 offence and defence, power play, penalty kill, goaltending) with history,
shot maps for and against (5v5 unblocked attempts on a 5 ft grid of the offensive half, per 60 and against the
league), line combinations (forward lines and defence pairs with 5v5 TOI and on-ice xGF%), deployment (each
skater's minutes by strength and zone starts), and the schedule against the model.

Ratings come from builder C's team_strength when it answers ("source": "team_strength"); otherwise from the
season's own counts ("source": "counts": 5v5 xG rates, PP xGF/60, PK xGA/60, goalie GSAx/60).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics import adapters, tables
from oddsmarkets.nhl.analytics.context import FENWICK, GOAL, SeasonContext

GRID = {"x0": 25.0, "dx": 5.0, "nx": 14, "y0": -42.5, "dy": 5.0, "ny": 17}     # x 25..95 ft (offensive zone), y full width
ZONES = (("crease", lambda x, y: (x >= 80) & (np.abs(y) <= 6)),
         ("slot", lambda x, y: (x >= 69) & (x < 89) & (np.abs(y) <= 9) & ~((x >= 80) & (np.abs(y) <= 6))),
         ("high_slot", lambda x, y: (x >= 54) & (x < 69) & (np.abs(y) <= 9)),
         ("circles", lambda x, y: (x >= 54) & (x < 89) & (np.abs(y) > 9) & (np.abs(y) <= 22)),
         ("point", lambda x, y: (x >= 25) & (x < 54)),
         ("perimeter", lambda x, y: (x >= 54) & (np.abs(y) > 22)),
         ("behind_net", lambda x, y: x >= 89))


def grid_counts(x: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
    ix = np.floor((x - GRID["x0"]) / GRID["dx"]).astype(int)
    iy = np.floor((y - GRID["y0"]) / GRID["dy"]).astype(int)
    ok = (ix >= 0) & (ix < GRID["nx"]) & (iy >= 0) & (iy < GRID["ny"]) & np.isfinite(x) & np.isfinite(y)
    out = np.zeros(GRID["nx"] * GRID["ny"])
    np.add.at(out, iy[ok] * GRID["nx"] + ix[ok], 1.0 if w is None else w[ok])
    return out


def zone_counts(x: np.ndarray, y: np.ndarray, xg: np.ndarray, g: np.ndarray) -> dict:
    out = {}
    for nm, f in ZONES:
        m = f(x, y) & np.isfinite(x)
        out[nm] = {"att": int(m.sum()), "xg": round(float(np.nansum(xg[m])), 2), "g": int(g[m].sum())}
    return out


def shot_maps(ev: pd.DataFrame, tg: pd.DataFrame) -> dict:
    """{team: {"for": {...}, "against": {...}}, "league": {...}} at 5v5: per-60 grids of attempts and xG, the team's
    per-60 minus the league's, and zone counts."""
    E = ev[ev["type"].isin(FENWICK).to_numpy() & (ev["state"] == "5v5").to_numpy() & (ev["game_id"].astype(str).str[4:6] == "02").to_numpy()]
    if not len(E):
        return {}
    toi = tg[tg["gt"] == "REG"].groupby("team")["toi_5v5"].sum() if len(tg) and "toi_5v5" in tg else pd.Series(dtype=float)
    x, y = E["x"].to_numpy(float), E["y"].to_numpy(float)
    xg = np.nan_to_num(E["xg"].to_numpy(float))
    gl = (E["type"] == GOAL).to_numpy(float)
    lg_t = float(toi.sum()) / 2 if len(toi) else 0.0           # each 5v5 second counts for both teams
    league = {"att60": _r(grid_counts(x, y) * 3600 / lg_t / 2 if lg_t else None),
              "xg60": _r(grid_counts(x, y, xg) * 3600 / lg_t / 2 if lg_t else None)}
    lg_att = grid_counts(x, y) * 3600 / lg_t / 2 if lg_t else None
    lg_xg = grid_counts(x, y, xg) * 3600 / lg_t / 2 if lg_t else None
    out = {"_league": league}
    teams = E["team"].to_numpy(object)
    opps = E["opp"].to_numpy(object)
    for t in sorted(set(teams) | set(opps)):
        if t is None:
            continue
        sec = float(toi.get(t, 0.0))
        e = {}
        for side, m in (("for", teams == t), ("against", opps == t)):
            att = grid_counts(x[m], y[m])
            xgg = grid_counts(x[m], y[m], xg[m])
            blk = {"att": _r(att, 0), "xg": _r(xgg, 3), "g": _r(grid_counts(x[m], y[m], gl[m]), 0),
                   "zones": zone_counts(x[m], y[m], xg[m], gl[m])}
            if sec and lg_att is not None:
                a60, x60 = att * 3600 / sec, xgg * 3600 / sec
                blk["att60"], blk["xg60"] = _r(a60), _r(x60, 3)
                blk["att60_rel"], blk["xg60_rel"] = _r(a60 - lg_att), _r(x60 - lg_xg, 3)
            e[side] = blk
        e["toi5"] = an.rnd(sec / 60.0, 1)
        out[t] = e
    return out


def _r(a, nd: int = 2):
    if a is None:
        return None
    return [round(float(v), nd) if nd else int(round(float(v))) for v in a]


def unit_ratings(ctx: SeasonContext, T: dict, cat_g: dict | None) -> dict:
    """{team: {"off5","def5","pp","pk","goalie","rating","source"}} from team_strength or the season's counts."""
    tr = adapters.team_ratings(ctx)
    tg = T["tg"]
    counts: dict[str, dict] = {}
    if len(tg):
        R = tg[tg["gt"] == "REG"].groupby("team").sum(numeric_only=True)
        gp = tg[tg["gt"] == "REG"].groupby("team")["game_id"].nunique()
        for t, r in R.iterrows():
            f = lambda k: float(r.get(k, 0.0) or 0.0)  # noqa: E731
            off5, def5 = an.per60(f("xgf_5v5"), f("toi_5v5")), an.per60(f("xga_5v5"), f("toi_5v5"))
            counts[t] = {"off5": off5, "def5": def5, "pp": an.per60(f("xgf_PP"), f("toi_PP")), "pk": an.per60(f("xga_SH"), f("toi_SH")),
                         "gf_g": an.div(f("gf_all"), gp.get(t)), "ga_g": an.div(f("ga_all"), gp.get(t)),
                         "gd_g": an.div(f("gf_all") - f("ga_all"), gp.get(t)),
                         "xgf_g": an.div(f("xgf_all"), gp.get(t)), "xga_g": an.div(f("xga_all"), gp.get(t)),
                         "xgf_pct5": (f("xgf_5v5") / (f("xgf_5v5") + f("xga_5v5"))) if f("xgf_5v5") + f("xga_5v5") else None,
                         "cf_pct5": (f("cf_5v5") / (f("cf_5v5") + f("ca_5v5"))) if f("cf_5v5") + f("ca_5v5") else None,
                         "gp": int(gp.get(t, 0)), "pp_toi_g": an.div(f("toi_PP") / 60, gp.get(t)), "pk_toi_g": an.div(f("toi_SH") / 60, gp.get(t)),
                         "pp_gf": f("gf_PP"), "pk_ga": f("ga_SH")}
    # special-teams percentages
    st_pct = special_teams_pct(ctx, T)
    for t, v in st_pct.items():
        counts.setdefault(t, {}).update(v)
    # goaltending: team GSAx per 60
    gg = T["gg"]
    if len(gg):
        G = gg[gg["gt"] == "REG"].groupby("team")[["xga", "ga", "toi"]].sum()
        for t, r in G.iterrows():
            counts.setdefault(t, {})["goalie"] = an.per60(r["xga"] - r["ga"], r["toi"])
            counts[t]["gsax"] = float(r["xga"] - r["ga"])
    out = {}
    for t in ctx.teams:
        c = counts.get(t, {})
        e = {k: an.rnd(v, 3) if isinstance(v, float) else v for k, v in c.items()}
        if tr and t in tr["teams"]:
            m = tr["teams"][t]
            e["model"] = {k: an.rnd(v, 3) for k, v in m.items() if isinstance(v, (int, float)) or v is None}
            e["rating"] = an.rnd(m.get("rating"), 3)
            e["source"] = "team_strength"
        else:
            xd = (c.get("xgf_g") or 0) - (c.get("xga_g") or 0) if c.get("xgf_g") is not None else None
            e["rating"] = an.rnd(xd, 3)
            e["source"] = "counts"
        out[t] = e
    # league percentiles of the units (100 = best)
    for k, lower in (("off5", False), ("def5", True), ("pp", False), ("pk", True), ("goalie", False), ("rating", False), ("gd_g", False)):
        pc = an.percentiles({t: v.get(k) for t, v in out.items()}, lower)
        for t, p in pc.items():
            out[t].setdefault("pct", {})[k] = p
    return {"teams": out, "history": (tr or {}).get("history") or {}, "units": (tr or {}).get("units") or "xG per 60 (counts)",
            "source": "team_strength" if tr else "counts", "version": (tr or {}).get("version")}


def team_summary_rows(season: int) -> list[dict]:
    import gzip
    import json
    p = an.raw_root() / "stats" / str(season) / "team_summary_2.json.gz"
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, list) else []
    except (OSError, ValueError, EOFError):
        return []


def special_teams_pct(ctx: SeasonContext, T: dict) -> dict[str, dict]:
    """{team: {"pp_pct", "pk_pct", "pp_source"}}: the NHL's own percentages from the stats REST team summary when on
    disk, else power-play goals per minor penalty drawn and 1 - short-handed goals against per minor taken."""
    out: dict[str, dict] = {}
    rows = team_summary_rows(ctx.season)
    if rows:
        by_name = {(v.get("name") or "").lower(): t for t, v in ctx.teams.items()}
        try:
            from oddsmarkets.nhl import canon
            ids = canon.team_ids(ctx.season)
        except Exception:                                        # noqa: BLE001
            ids = {}
        for r in rows:
            t = ids.get(r.get("teamId")) or by_name.get(str(r.get("teamFullName") or "").lower())
            if t:
                out[t] = {"pp_pct": an.fnum(r.get("powerPlayPct")), "pk_pct": an.fnum(r.get("penaltyKillPct")), "pp_source": "nhl"}
    tg = T["tg"]
    if len(tg):
        R = tg[tg["gt"] == "REG"].groupby("team").sum(numeric_only=True)
        for t, r in R.iterrows():
            if t in out:
                continue
            d, k = float(r.get("pen_drawn", 0.0)), float(r.get("pen_taken", 0.0))
            out[t] = {"pp_pct": float(r.get("gf_PP", 0.0)) / d if d else None, "pk_pct": 1 - float(r.get("ga_SH", 0.0)) / k if k else None,
                      "pp_source": "events"}
    return out


def rolling_history(ctx: SeasonContext, T: dict, window: int = 10) -> dict:
    """{team: [[game_no, date, xgf_pct5 rolling, gf_pct rolling, cf_pct5 rolling], ...]} over the regular season."""
    tg = T["tg"]
    if not len(tg):
        return {}
    R = tg[tg["gt"] == "REG"].copy()
    R["date"] = R["game_id"].map(lambda g: (ctx.games.get(g) or {}).get("date"))
    out = {}
    for t, D in R.sort_values("game_id").groupby("team"):
        roll = D[["xgf_5v5", "xga_5v5", "gf_all", "ga_all", "cf_5v5", "ca_5v5"]].rolling(window, min_periods=1).sum()
        rows = []
        for i, (idx, r) in enumerate(roll.iterrows()):
            a = r["xgf_5v5"] + r["xga_5v5"]
            b = r["gf_all"] + r["ga_all"]
            c = r["cf_5v5"] + r["ca_5v5"]
            rows.append([i + 1, D.loc[idx, "date"], an.rnd(r["xgf_5v5"] / a, 3) if a else None, an.rnd(r["gf_all"] / b, 3) if b else None,
                         an.rnd(r["cf_5v5"] / c, 3) if c else None])
        out[t] = rows
    return out


def lines_for_team(combos: pd.DataFrame, team: str, names: dict, n_f: int = 8, n_d: int = 6) -> dict:
    out = {"forwards": [], "pairs": []}
    if combos is None or not len(combos):
        return out
    C = combos[combos["team"] == team]
    for kind, key, n in (("F", "forwards", n_f), ("D", "pairs", n_d)):
        K = C[C["kind"] == kind].sort_values("toi", ascending=False).head(n)
        for r in K.itertuples(index=False):
            ids = r.key.split("-")
            out[key].append(line_row(ids, r, names))
    return out


def line_row(ids: list[str], r, names: dict) -> dict:
    xf, xa = float(r.xgf), float(r.xga)
    cf, ca = float(r.cf), float(r.ca)
    return {"ids": ids, "names": [names.get(i) or i for i in ids], "toi": round(float(r.toi) / 60, 1), "games": int(r.games),
            "xgf": round(xf, 2), "xga": round(xa, 2), "xgf_pct": round(xf / (xf + xa), 3) if xf + xa else None,
            "cf_pct": round(cf / (cf + ca), 3) if cf + ca else None, "gf": int(r.gf), "ga": int(r.ga),
            "xgf60": round(3600 * xf / float(r.toi), 2) if r.toi else None, "xga60": round(3600 * xa / float(r.toi), 2) if r.toi else None}


def build(ctx: SeasonContext, skaters: dict | None, goalies: dict | None, sim: dict | None, cards: list[dict] | None,
          standings: dict | None = None) -> dict | None:
    T = tables.tables(ctx)
    if not ctx.teams:
        return None
    units = unit_ratings(ctx, T, goalies)
    maps = shot_maps(T["ev"], T["tg"]) if T["has_events"] else {}
    hist = rolling_history(ctx, T)
    cmb = tables.combos(ctx)
    names = {p: r.get("name") for p, r in ((skaters or {}).get("players") or {}).items()}
    sk = (skaters or {}).get("players") or {}
    gk = (goalies or {}).get("players") or {}
    sim_t = (sim or {}).get("teams") or {} if (sim or {}).get("ok") else {}
    rec = {r["team"]: r for r in ((standings or {}).get("rows") or [])}
    if not rec:
        from oddsmarkets.nhl.analytics import season as SN
        rec = {t: {"team": t, **r} for t, r in SN.records(ctx).items()}
    teams = {}
    for t, info in ctx.teams.items():
        dep = []
        for p, r in sk.items():
            if r.get("team") != t:
                continue
            v = r.get("values") or {}
            dep.append({"id": p, "name": r.get("name"), "pos": r.get("pos"), "gp": r.get("gp"), "toi_gp": v.get("toi_gp"),
                        "toi5_gp": v.get("toi5_gp"), "toi_pp_gp": v.get("toi_pp_gp"), "toi_sh_gp": v.get("toi_sh_gp"),
                        "ozs_pct": v.get("ozs_pct"), "qoc_toi": v.get("qoc_toi"), "xgf_pct": v.get("xgf_pct"), "p": v.get("p"),
                        "gar": v.get("gar"), "rapm_net": v.get("rapm_net")})
        dep.sort(key=lambda x: -(x.get("toi_gp") or 0))
        gl = [{"id": p, "name": r.get("name"), "gp": r.get("gp"), "gsax": (r.get("values") or {}).get("gsax"),
               "sv_pct": (r.get("values") or {}).get("sv_pct"), "gs": (r.get("values") or {}).get("gs")}
              for p, r in gk.items() if r.get("team") == t]
        gl.sort(key=lambda x: -(x.get("gp") or 0))
        sched = [c for c in (cards or []) if t in (c.get("home"), c.get("away"))]
        sched_rows = []
        for c in sched:
            home = c.get("home") == t
            pm = (c.get("model") or {}).get("p_home")
            pmk = (c.get("market") or {}).get("p_home") if c.get("market") else None
            res = None
            if c.get("status") == "final" and c.get("hs") is not None:
                gf, ga = (c["hs"], c["as"]) if home else (c["as"], c["hs"])
                res = "W" if gf > ga else ("OTL" if c.get("ot") or c.get("so") else "L")
            sched_rows.append({"game_id": c.get("game_id"), "date": c.get("date"), "opp": c.get("away") if home else c.get("home"),
                               "home": home, "status": c.get("status"), "gf": c.get("hs") if home else c.get("as"),
                               "ga": c.get("as") if home else c.get("hs"), "result": res,
                               "p_win": an.rnd(pm if home else (1 - pm), 4) if pm is not None else None,
                               "p_market": an.rnd(pmk if home else (1 - pmk), 4) if pmk is not None else None,
                               "xgf": ((c.get("xg") or {}).get("home") if home else (c.get("xg") or {}).get("away")),
                               "xga": ((c.get("xg") or {}).get("away") if home else (c.get("xg") or {}).get("home"))})
        u = units["teams"].get(t, {})
        teams[t] = {"abbr": t, "name": info.get("name"), "division": info.get("division"), "conference": info.get("conference"),
                    "colour": info.get("colour"), "alt": info.get("alt"), "record": rec.get(t),
                    "units": u, "history": units["history"].get(t) or [], "rolling": hist.get(t) or [],
                    "shot_map": maps.get(t), "lines": lines_for_team(cmb, t, names), "deployment": dep, "goalies": gl,
                    "sim": sim_t.get(t), "schedule": sched_rows}
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "phase": ctx.phase, "teams": teams,
            "grid": GRID, "zones": [z for z, _ in ZONES], "league_map": maps.get("_league"), "ratings_source": units["source"],
            "ratings_units": units["units"], "ratings_version": units["version"], "rolling_window": 10, "xg_source": ctx.xg_source,
            "model_errors": dict(ctx.model_errors)}
