"""
Career files (data/players/<pid>.json) and players_index.json.

Seasons: each season's catalogues reduced to compact career rows (`reduce_cat`: counting stats and the headline rates,
with an era-adjusted "plus" = 100 + 10 z within the season's qualified pool at the position group) for the seasons
built from play-by-play (2009-10 onward); builder A's stats REST season reports fill the totals of any season on
disk without a catalogue (`stats_rows`). The full season adds a "current" block per player (`current_blocks`): the
game log, the shot chart (5 ft grid + points with xG), on-ice 5v5 rates, RAPM, EDGE, linemates (shared 5v5 time),
deployment, the projection; and similar players (nearest neighbours on standardised headline metrics within the
position group). A player's file is rewritten only when its content changed.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
from typing import Callable

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics import edge, tables
from oddsmarkets.nhl.analytics.context import FENWICK, GOAL

logger = logging.getLogger(__name__)
SEASON_KEYS_S = ["gp", "toi_gp", "g", "a", "p", "p60", "sog", "ixg", "ixg60", "gax", "sh_pct", "cf_pct", "xgf_pct", "xgf_pct_rel",
                 "rapm_off", "rapm_def", "rapm_net", "gar", "war", "hits", "blocks", "fo_pct", "pim", "ozs_pct", "toi_pp_gp", "toi_sh_gp"]
SEASON_KEYS_G = ["gp", "gs", "w", "l", "otl", "sv_pct", "gaa", "gsax", "gsax60", "gsax_high", "sv_pct_high", "qs_pct", "gar", "war", "toi"]
PLUS_S = ["p60", "ixg60", "xgf_pct", "xgf_pct_rel", "rapm_net", "gar"]
PLUS_G = ["sv_pct", "gsax60", "gsax_high"]
SIMILAR_S = ["p60", "ixg60", "icf60", "xgf60", "xga60", "cf_pct", "hits60", "blocks60", "toi_gp", "ozs_pct", "pen_drawn60", "shot_dist"]
SIMILAR_G = ["sv_pct", "gsax60", "sv_pct_high", "sv_pct_low", "xg_per_shot", "reb_rate", "start_share"]
# catalogue group -> docs/_design/metrics/hockey.json group (the METRICS_SPEC similar-players features and weights)
SPEC_GROUP = {"F": "forwards", "D": "defence", "G": "goalies"}


def sim_keys(kind: str) -> list[str]:
    """Every feature a season row keeps for the similarity: the spec groups' features (fallback: the old lists)."""
    from oddsmarkets.common import similar as SIM
    groups = ("forwards", "defence") if kind == "skater" else ("goalies",)
    keys: list[str] = []
    for g in groups:
        cfg = SIM.group_config("hockey", g)
        keys += cfg["features"] if cfg else []
    return list(dict.fromkeys(keys)) or (SIMILAR_S if kind == "skater" else SIMILAR_G)
LOWER = {"gaa", "xga60"}


def reduce_cat(cat: dict | None, season: int, kind: str) -> dict[str, dict] | None:
    if not cat or not cat.get("players"):
        return None
    P = cat["players"]
    keys = SEASON_KEYS_S if kind == "skater" else SEASON_KEYS_G
    plus_keys = PLUS_S if kind == "skater" else PLUS_G
    skeys = sim_keys(kind)
    # the plus needs the catalogue's games floor too (one game's GAR is not a season): the pool and the rows placed
    gp_floor = an.fnum(((cat.get("reference") or {}).get("floors") or {}).get("gp")) or 0.0

    def placed(r: dict) -> bool:
        return bool(r.get("qualified")) and (an.fnum(r.get("gp")) or 0.0) >= gp_floor
    stats: dict[tuple, tuple] = {}
    for grp in ({r.get("group") for r in P.values()}):
        mem = [r for r in P.values() if r.get("group") == grp and placed(r)]
        for k in plus_keys:
            v = [an.fnum((r.get("values") or {}).get(k)) for r in mem]
            v = [x for x in v if x is not None]
            if len(v) >= 8:
                stats[(grp, k)] = (float(np.mean(v)), float(np.std(v)) or 1.0)
    out = {}
    for pid, r in P.items():
        vals = {k: (r.get("values") or {}).get(k) for k in keys}
        sim = {k: (r.get("values") or {}).get(k) for k in skeys}
        pl = {}
        if placed(r):
            for k in plus_keys:
                st = stats.get((r.get("group"), k))
                x = an.fnum(vals.get(k))
                if st and x is not None:
                    pl[k] = int(round(100 + 10 * ((st[0] - x) if k in LOWER else (x - st[0])) / st[1]))
        out[pid] = {"season": int(season), "kind": kind, "team": r.get("team"), "teams": r.get("teams"), "group": r.get("group"),
                    "pos": r.get("pos"), "name": r.get("name"), "age": r.get("age"), "qualified": r.get("qualified"), "values": vals,
                    "plus": pl, "sim": sim}
    return out


def stats_rows(season: int) -> dict[str, dict]:
    """{pid: compact season row} from builder A's stats REST skater / goalie summary reports (regular season)."""
    out: dict[str, dict] = {}
    for rep, kind in (("skater_summary_2", "skater"), ("goalie_summary_2", "goalie")):
        p = an.raw_root() / "stats" / str(season) / f"{rep}.json.gz"
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError, EOFError):
            continue
        for r in rows or []:
            pid = an.sid(r.get("playerId"))
            if not pid:
                continue
            team = (str(r.get("teamAbbrevs") or "").split(",")[-1].strip() or None)
            if kind == "skater":
                gp = an.fnum(r.get("gamesPlayed"))
                vals = {"gp": gp, "g": an.fnum(r.get("goals")), "a": an.fnum(r.get("assists")), "p": an.fnum(r.get("points")),
                        "sog": an.fnum(r.get("shots")), "pim": an.fnum(r.get("penaltyMinutes")),
                        "toi_gp": an.rnd((an.fnum(r.get("timeOnIcePerGame")) or 0) / 60.0, 1) if r.get("timeOnIcePerGame") else None,
                        "sh_pct": an.fnum(r.get("shootingPct")), "plus_minus": an.fnum(r.get("plusMinus")),
                        "ppp": an.fnum(r.get("ppPoints")), "fo_pct": an.fnum(r.get("faceoffWinPct"))}
                name, pos = r.get("skaterFullName"), r.get("positionCode")
            else:
                vals = {"gp": an.fnum(r.get("gamesPlayed")), "gs": an.fnum(r.get("gamesStarted")), "w": an.fnum(r.get("wins")),
                        "l": an.fnum(r.get("losses")), "otl": an.fnum(r.get("otLosses")), "sv_pct": an.fnum(r.get("savePct")),
                        "gaa": an.fnum(r.get("goalsAgainstAverage")), "so": an.fnum(r.get("shutouts"))}
                name, pos = r.get("goalieFullName"), "G"
            out[pid] = {"season": int(season), "kind": kind, "team": team, "name": name, "pos": pos, "values": vals, "plus": {},
                        "source": "stats"}
    return out


# ---------------------------------------------------------------------------------------------- current blocks

def log_result(g: dict | None, team: str | None) -> str | None:
    """A final game from one team's side: "W 3-2", "OTL 2-3 (OT)", "L 1-4", "W 4-3 (SO)"; None before it is final."""
    if not g or g.get("status") != "final" or g.get("hs") is None or g.get("as") is None or not team:
        return None
    home = team == g.get("home")
    gf, ga = (int(g["hs"]), int(g["as"])) if home else (int(g["as"]), int(g["hs"]))
    extra = " (SO)" if g.get("so") else (" (OT)" if g.get("ot") else "")
    tag = "W" if gf > ga else ("OTL" if extra else "L")
    return f"{tag} {gf}-{ga}{extra}"


def current_blocks(ctx, sk: dict | None, gk: dict | None) -> dict[str, dict]:
    T = tables.tables(ctx)
    pg = T["pg"]
    out: dict[str, dict] = {}
    if not len(pg) and not len(T["gg"]):
        return out
    meta = {gid: (g.get("date"), g.get("home"), g.get("away")) for gid, g in ctx.games.items()}
    from oddsmarkets.nhl.analytics.games import game_score_skater
    # game logs
    for pid, D in pg.sort_values("game_id").groupby("pid"):
        p = an.sid(pid)
        log = []
        for r in D.to_dict("records"):
            d, h, a = meta.get(r["game_id"], (None, None, None))
            home = r["team"] == h
            log.append([r["game_id"], d, a if home else h, home, int(r.get("g", 0)), int(r.get("a1", 0) + r.get("a2", 0)),
                        int(r.get("sog", 0)), round(r.get("ixg", 0.0), 2), round(r.get("toi", 0) / 60, 1), round(r.get("toi_5v5", 0) / 60, 1),
                        round(r.get("xgf_5v5", 0.0), 2), round(r.get("xga_5v5", 0.0), 2), round(game_score_skater(r), 2),
                        log_result(ctx.games.get(r["game_id"]), r["team"])])
        out[p] = {"season": ctx.season, "kind": "skater", "log": {"cols": ["game_id", "date", "opp", "home", "g", "a", "sog", "ixg", "toi",
                                                                           "toi5", "xgf", "xga", "gs", "result"], "rows": log}}
    gg = T["gg"]
    if len(gg):
        for pid, D in gg.sort_values("game_id").groupby("pid"):
            p = an.sid(pid)
            log = []
            for r in D.to_dict("records"):
                d, h, a = meta.get(r["game_id"], (None, None, None))
                home = r["team"] == h
                log.append([r["game_id"], d, a if home else h, home, int(r.get("sa", 0)), int(r.get("ga", 0)), round(r.get("xga", 0.0), 2),
                            round(r.get("xga", 0.0) - r.get("ga", 0.0), 2), round(r.get("toi", 0) / 60, 1),
                            log_result(ctx.games.get(r["game_id"]), r["team"])])
            out[p] = {"season": ctx.season, "kind": "goalie", "log": {"cols": ["game_id", "date", "opp", "home", "sa", "ga", "xga", "gsax", "toi",
                                                                               "result"], "rows": log}}
    # shot charts
    ev = T["ev"]
    if len(ev):
        from oddsmarkets.nhl.analytics.teams import GRID, grid_counts
        F = ev[ev["type"].isin(FENWICK).to_numpy() & (ev["game_id"].astype(str).str[4:6] == "02").to_numpy()]
        for pid, D in F.groupby("p1"):
            p = an.sid(pid)
            if p not in out:
                continue
            x, y = D["x"].to_numpy(float), D["y"].to_numpy(float)
            xg = np.nan_to_num(D["xg"].to_numpy(float))
            gl = (D["type"] == GOAL).to_numpy()
            pts = [[an.rnd(a, 1), an.rnd(b, 1), an.rnd(c, 3), int(d)] for a, b, c, d in zip(x, y, xg, gl)][-400:]
            out[p]["shots"] = {"grid": GRID, "att": [int(v) for v in grid_counts(x, y)], "xg": [round(float(v), 3) for v in grid_counts(x, y, xg)],
                               "g": [int(v) for v in grid_counts(x, y, gl.astype(float))], "points": pts,
                               "point_cols": ["x", "y", "xg", "goal"]}
        # goalies: shots faced
        G = F.assign(_g=np.where(F["goalie"].notna(), F["goalie"], np.where(F["is_home"] == 1, F["vg"], F["hg"])))
        for pid, D in G[G["_g"].notna()].groupby("_g"):
            p = an.sid(pid)
            if p not in out:
                continue
            x, y = D["x"].to_numpy(float), D["y"].to_numpy(float)
            xg = np.nan_to_num(D["xg"].to_numpy(float))
            gl = (D["type"] == GOAL).to_numpy().astype(float)
            out[p]["shots"] = {"grid": GRID, "faced": True, "att": [int(v) for v in grid_counts(x, y)],
                               "xg": [round(float(v), 3) for v in grid_counts(x, y, xg)], "g": [int(v) for v in grid_counts(x, y, gl)]}
    # catalogue-derived blocks
    from oddsmarkets.nhl.analytics import skaters as SK
    SP = (sk or {}).get("players") or {}
    by_str = onice_by_strength(pg)
    keys_on = ["toi5", "cf60", "ca60", "cf_pct", "xgf60", "xga60", "xgf_pct", "gf60", "ga60", "gf_pct", "on_sh_pct", "on_sv_pct", "pdo",
               "xgf_pct_rel", "cf_pct_rel", "adj_xgf60", "adj_xga60", "adj_xgf_pct"]
    keys_rapm = [k for k in SK.KEYS if k.startswith("rapm_")]
    keys_dep = ["ozs_pct", "dzs_share", "qoc_toi", "qot_toi", "qoc_xgf", "qot_xgf", "toi_share", "toi_gp", "toi5_gp", "toi_pp_gp", "toi_sh_gp",
                "shift_len", "shifts_gp"]
    keys_proj = ["proj_pts", "proj_g", "proj_xgf_pct", "pts_pace"]
    from oddsmarkets.nhl.analytics import adapters
    proj_m = adapters.projections(ctx)
    gm_w: dict = {}
    if ctx.use_models:
        try:                        # the game model's player term (models/players.py): rating and lineup weight now
            from oddsmarkets.nhl.models import players as PL
            gm_w = PL.player_table(ctx.season)
        except Exception as exc:    # noqa: BLE001
            ctx.model_errors["players"] = f"{type(exc).__name__}: {exc}"
    peers = peer_blocks(sk, gk)
    for p, r in SP.items():
        b = out.setdefault(p, {"season": ctx.season, "kind": "skater"})
        v = r.get("values") or {}
        pc = r.get("pct") or {}
        b["onice"] = {k: v.get(k) for k in keys_on} | {"pct": {k: pc.get(k) for k in keys_on if pc.get(k) is not None}}
        if p in by_str:
            b["onice"]["by_strength"] = by_str[p]
        b["rapm"] = {k: v.get(k) for k in keys_rapm} | {"pct": {k: pc.get(k) for k in keys_rapm if pc.get(k) is not None}}
        b["deployment"] = {k: v.get(k) for k in keys_dep}
        w = gm_w.get(int(p)) if str(p).isdigit() else None
        if w:
            b["game_model"] = w
        b["projection"] = {k: v.get(k) for k in keys_proj} | ({"model": proj_m.get(p)} if proj_m.get(p) else {})
        e = edge.player_block(ctx.season, p)
        if e:
            b["edge"] = e
        b["pct"] = pc
        b.update(peers.get(p) or {})
    for p, r in ((gk or {}).get("players") or {}).items():
        b = out.setdefault(p, {"season": ctx.season, "kind": "goalie"})
        b["goalie"] = r.get("values")
        b["pct"] = r.get("pct")
        b.update(peers.get(p) or {})
        e = edge.player_block(ctx.season, p)
        if e:
            b["edge"] = e
    # linemates from the 5v5 combos
    C = tables.combos(ctx)
    if C is not None and len(C):
        names = {p: r.get("name") for p, r in SP.items()}
        share: dict[str, dict[str, float]] = {}
        for r in C.itertuples(index=False):
            ids = r.key.split("-")
            for a in ids:
                for b2 in ids:
                    if a != b2:
                        share.setdefault(a, {})
                        share[a][b2] = share[a].get(b2, 0.0) + float(r.toi)
        for p, d in share.items():
            if p in out:
                top = sorted(d.items(), key=lambda x: -x[1])[:8]
                out[p]["linemates"] = [[q, names.get(q) or ctx.player_name(q) or q, round(t / 60, 1)] for q, t in top]
    return out


def peer_blocks(sk: dict | None, gk: dict | None) -> dict[str, dict]:
    """{pid: {"pct_pos", "peer"}} for the current season's player files (accuracy audit, 22 Oct 2026): the percentiles
    against the same position group (F / D / G) and who that group is (its qualified size and the qualification floor),
    so a player page can show "v N forwards" without loading the 2.7 MB catalogue. "pct" stays the whole-pool rank."""
    out: dict[str, dict] = {}
    for cat, kind in ((sk, "skater"), (gk, "goalie")):
        P = (cat or {}).get("players") or {}
        ref = (cat or {}).get("reference") or {}
        n: dict = {}
        for r in P.values():
            if r.get("qualified"):
                g = r.get("group") if kind == "skater" else "G"
                n[g] = n.get(g, 0) + 1
        floor = {"min_toi5": ref.get("min_toi5")} if kind == "skater" else {"min_toi": ref.get("min_toi")}
        floor["min_gp"] = (ref.get("floors") or {}).get("gp")
        for pid, r in P.items():
            g = r.get("group") if kind == "skater" else "G"
            out[pid] = {"pct_pos": r.get("pct_pos") or (r.get("pct") if kind == "goalie" else None) or {},
                        "peer": {"group": g, "n": n.get(g, 0), "qualified": bool(r.get("qualified")), **floor}}
    return out


def prev_season(season: int) -> int:
    """20252026 -> 20242025."""
    return int(season) - 10001


def add_prev_pct(blocks: dict[str, dict], load: Callable[[int, str], dict | None]) -> int:
    """Last season's position-group percentiles on each "current" block (kit v3 rail rings, 23 Oct 2026), so the player
    page need not load last season's 4 MB catalogue: "prev_pct_pos" (the same shape as "pct_pos") and "prev_peer"
    {"season", "group", "gp", "qualified"}. Skaters only when last season's group (F / D) is this season's; goalies
    against goalies. `load(season, "skaters.json" | "goalies.json")` reads a season's catalogue. Returns the count."""
    cache: dict = {}

    def cat(season: int, fn: str) -> dict:
        if (season, fn) not in cache:
            cache[(season, fn)] = ((load(season, fn) or {}).get("players") or {})
        return cache[(season, fn)]

    n = 0
    for pid, b in blocks.items():
        if not b or not b.get("season"):
            continue
        goalie = b.get("kind") == "goalie"
        pr = cat(prev_season(b["season"]), "goalies.json" if goalie else "skaters.json").get(pid)
        if not pr:
            continue
        grp = "G" if goalie else pr.get("group")
        cur = "G" if goalie else (b.get("peer") or {}).get("group")
        pc = (pr.get("pct_pos") or pr.get("pct")) if goalie else (pr.get("pct_pos") if grp == cur else None)
        if not pc:
            continue
        b["prev_pct_pos"] = pc
        b["prev_peer"] = {"season": prev_season(b["season"]), "group": grp, "gp": pr.get("gp"), "qualified": bool(pr.get("qualified"))}
        n += 1
    return n


def onice_by_strength(pg: pd.DataFrame) -> dict[str, dict]:
    """{pid: {"5v5" | "pp" | "pk": {toi (min), cf60, ca60, ff60, fa60, sf60, sa60, gf60, ga60, xgf60, xga60, cf_pct, xgf_pct, gf_pct}}}
    over the regular season (pp / pk = the player's team with more / fewer skaters)."""
    if not len(pg):
        return {}
    P = pg[pg["gt"] == "REG"]
    if not len(P):
        return {}
    cols = [c for c in P.columns if c.endswith(("_5v5", "_PP", "_SH")) and c.split("_")[0] in
            ("toi", "cf", "ca", "ff", "fa", "sf", "sa", "gf", "ga", "xgf", "xga")]
    agg = P.groupby("pid")[cols].sum()
    out: dict[str, dict] = {}
    for pid, r in agg.iterrows():
        d = {}
        for s, lab in (("5v5", "5v5"), ("PP", "pp"), ("SH", "pk")):
            t = float(r.get(f"toi_{s}", 0.0) or 0.0)
            if t <= 0:
                continue
            e = {"toi": round(t / 60.0, 1)}
            for k in ("cf", "ca", "ff", "fa", "sf", "sa", "gf", "ga", "xgf", "xga"):
                e[f"{k}60"] = an.rnd(an.per60(r.get(f"{k}_{s}", 0.0), t), 2)
            for f_, a_ in (("cf", "ca"), ("xgf", "xga"), ("gf", "ga")):
                x, y = float(r.get(f"{f_}_{s}", 0.0)), float(r.get(f"{a_}_{s}", 0.0))
                e[f"{f_}_pct"] = round(x / (x + y), 3) if x + y else None
            d[lab] = e
        out[an.sid(pid)] = d
    return out


def similar(rows: dict[str, dict], kind: str, n: int | None = None) -> dict[str, list]:
    """Nearest neighbours by the METRICS_SPEC recipe (oddsmarkets/common/similar.py) within the position group (F, D, G),
    qualified rows of the season only: the group's features from docs/_design/metrics/hockey.json, z-scored within the
    group, a missing feature at the group mean (z 0), weights = year-to-year r floored at 0.2, weighted Euclidean,
    k from the spec (6). Rows [pid, name, team, distance] (weighted RMS z gap, smaller = closer)."""
    from oddsmarkets.common import similar as SIM
    out = {}
    by_grp: dict[str, list[str]] = {}
    for p, r in rows.items():
        if r.get("qualified"):
            by_grp.setdefault(r.get("group") or "-", []).append(p)
    for grp, ids in by_grp.items():
        fb = {"features": SIMILAR_S if kind == "skater" else SIMILAR_G, "k": 6}
        cfg = SIM.group_config("hockey", SPEC_GROUP.get(grp, ""), fallback=fb)
        k = n or cfg["k"]
        if len(ids) < k + 2:
            continue
        X = SIM.matrix([rows[p] for p in ids], cfg["features"], lambda r, f: (r.get("sim") or {}).get(f))
        Z = SIM.zscore(X)
        Z = np.where(np.isnan(Z), 0.0, Z)
        w = np.array([cfg["weights"][f] for f in cfg["features"]])
        for i, p in enumerate(ids):
            out[p] = [[ids[j], rows[ids[j]].get("name"), rows[ids[j]].get("team"), round(d, 2)] for j, d in SIM.nearest(Z, i, w, k)]
    return out


# ---------------------------------------------------------------------------------------------- writing

def write_careers(write: Callable[[str, dict], None], rows_by: dict[int, dict[str, dict]], blocks: dict[str, dict],
                  old_reader: Callable[[str], dict | None], current: int, people: dict[str, dict]) -> dict[str, list]:
    """Write players/<pid>.json for every player with a season row; returns players_index entries
    {pid: [name, team, pos, first_season, last_season]}."""
    by_pid: dict[str, list] = {}
    for s in sorted(rows_by):
        for pid, r in (rows_by[s] or {}).items():
            by_pid.setdefault(pid, []).append(r)
    sims = {}
    cur = rows_by.get(current) or {}
    for kind in ("skater", "goalie"):
        sims.update(similar({p: r for p, r in cur.items() if r.get("kind") == kind}, kind))
    idx = {}
    n_written = 0
    for pid, seasons in by_pid.items():
        seasons.sort(key=lambda r: r["season"])
        last = seasons[-1]
        info = people.get(pid) or {}
        # the latest season row with a real name (a row named by its id came from a season whose store missed the player)
        named = next((r.get("name") for r in reversed(seasons) if r.get("name") and str(r.get("name")) != pid), None)
        nm = info.get("name") or named or last.get("name")
        doc = {"id": pid, "name": nm, "pos": info.get("pos") or last.get("pos"),
               "shoots": info.get("shoots"), "dob": info.get("dob"), "height": info.get("height"), "weight": info.get("weight"),
               "number": info.get("number"), "kind": last.get("kind"),
               "seasons": [{k: r.get(k) for k in ("season", "team", "teams", "pos", "age", "qualified", "values", "plus", "source")} for r in seasons],
               "current": blocks.get(pid), "similar": sims.get(pid)}
        idx[pid] = [doc["name"], last.get("team"), doc["pos"], seasons[0]["season"], last["season"]]
        old = old_reader(pid)
        if old is not None and _sig(old) == _sig(doc):
            continue
        doc["updated_at"] = an.now()
        write(f"players/{pid}.json", doc)
        n_written += 1
    logger.info("careers: %d files written, %d unchanged", n_written, len(by_pid) - n_written)
    return idx


def _sig(doc: dict) -> str:
    d = {k: v for k, v in doc.items() if k != "updated_at"}
    return hashlib.sha1(json.dumps(an.clean(d), sort_keys=True, default=str).encode()).hexdigest()
