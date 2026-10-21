"""
Player layer for college basketball: box-score value above replacement, positions, inferred transfers, team
strengths and needs, and fantasy projections with a walk-forward check. Built only from ESPN box scores in our
stores (games with a summary); seasons without box scores get no player payloads.

Value (team-constrained box value, documented and public):
  game score  GmSc = PTS + 0.4 FGM - 0.7 FGA - 0.4 (FTA - FTM) + 0.7 OREB + 0.3 DREB + STL + 0.7 AST + 0.7 BLK
                     - 0.4 PF - TOV                                                              (Hollinger)
  rate        g_p = 40 * sum(GmSc) / sum(minutes), shrunk to the league mean with K_MIN pseudo-minutes
  scale       a = slope of team rating (adjusted efficiency margin per 100) on the team's minutes-weighted g,
              fitted over every team of the season
  rating      r_p = (a (g_p - g_league) + resid_t) / 5, resid_t = rating_t - a (g_team - g_league), so that the
              five-man sum on the floor, sum_p r_p * minutes_p / (team minutes / 5), equals the team's rating (the
              box plus-minus scale: points per 100 possessions above an average D-I player)
  value       VAR_p = (r_p - repl) * possessions_p / 100, possessions_p = minutes_p / 40 * team tempo;
              repl = the minutes-weighted mean r of players outside their team's top eight in minutes (the
              season's replacement level); value_pg = VAR / games
Usage, true shooting and a simple offensive rating (points per 100 possessions used = 100 PTS / (FGA + 0.475 FTA
+ TOV)) are reported alongside. Positions: ESPN's roster position pooled to G/F/C (canon.pool), else inferred
(assist share -> G, block or rebound share -> C, else F).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from oddsmarkets.college import canon
from oddsmarkets.college.hoops import data as D

K_MIN = 150.0
STATS = ["sec", "pts", "fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf"]
COL = {c: i for i, c in enumerate(["player_id", "starter", "sec", "pts", "fgm", "fga", "tpm", "tpa", "ftm", "fta",
                                    "oreb", "dreb", "ast", "stl", "blk", "tov", "pf"])}
FANTASY_W = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}
CATS9 = ["pts", "reb", "ast", "stl", "blk", "tpm", "fg", "ft", "tov"]


def gmsc(r: np.ndarray) -> np.ndarray:
    """Game score from stacked stat columns (order STATS)."""
    s = {k: r[:, i] for i, k in enumerate(STATS)}
    return (s["pts"] + 0.4 * s["fgm"] - 0.7 * s["fga"] - 0.4 * (s["fta"] - s["ftm"]) + 0.7 * s["oreb"] + 0.3 * s["dreb"]
            + s["stl"] + 0.7 * s["ast"] + 0.7 * s["blk"] - 0.4 * s["pf"] - s["tov"])


def box_rows(level: str, season: int, st: dict | None = None) -> dict:
    """Player-game rows of a season's box scores: {"pid","tid","gid","day","opp","home": arrays, "X": (n, len(STATS)),
    "starter", "team_tot": {(gid, tid): {fga, fta, tov, min}}}."""
    st = st if st is not None else D.load(level, season)
    pid, tid, gid, day, opp, home, starter, X = [], [], [], [], [], [], [], []
    tt = {}
    for g in (st.get("games") or {}).values():
        b = g.get("box") or {}
        if g.get("status") != "post" or len(b) != 2 or not D.box_ok(g, rel=0.1):
            continue
        d = D.local_day(g.get("date"))
        if d is None:
            continue
        h, a = str(g["home"]), str(g["away"])
        for t, v in b.items():
            o = a if t == h else h
            tm = (v or {}).get("team") or {}
            tsec = 0
            for row in (v or {}).get("players") or []:
                try:
                    sec = float(row[COL["sec"]] or 0)
                except (TypeError, ValueError, IndexError):
                    continue
                if sec <= 0:
                    continue
                vals = [float(row[COL[k]] or 0) if k != "sec" else sec for k in STATS]
                pid.append(str(row[0]))
                tid.append(t)
                gid.append(str(g["id"]))
                day.append(d.toordinal())
                opp.append(o)
                home.append(t == h)
                starter.append(bool(row[1]))
                X.append(vals)
                tsec += sec
            tt[(str(g["id"]), t)] = {"fga": float(tm.get("fga") or 0), "fta": float(tm.get("fta") or 0),
                                     "tov": float(tm.get("tov") or 0), "sec": tsec}
    n = len(pid)
    return {"pid": np.array(pid, dtype=object), "tid": np.array(tid, dtype=object), "gid": np.array(gid, dtype=object),
            "day": np.array(day, dtype=np.int64), "opp": np.array(opp, dtype=object), "home": np.array(home, bool),
            "starter": np.array(starter, bool), "X": np.array(X, float).reshape(n, len(STATS)), "team_tot": tt}


def position(level: str, pinfo: dict | None, per40: dict | None = None) -> str:
    p = canon.pool(level, (pinfo or {}).get("pos")) or (pinfo or {}).get("pool")
    if p in ("G", "F", "C"):
        return p
    if per40:
        if per40.get("ast", 0) >= 4.0:
            return "G"
        if per40.get("blk", 0) >= 2.0 or per40.get("reb", 0) >= 11.0:
            return "C"
    return "F"


def season_players(level: str, season: int, ratings: dict[str, dict], br: dict | None = None,
                   st: dict | None = None) -> dict:
    """Per player-season rows (primary team = most minutes) with value (module docstring).
    `ratings`: {tid: {"rating","tempo"}} season-end team ratings. Returns {"rows": {pid: ROW}, "params": {...}}."""
    st = st if st is not None else D.load(level, season)
    br = br if br is not None else box_rows(level, season, st)
    if len(br["pid"]):
        # Division I players only: rows of non-member opponents (D-II, NAIA ... on a D-I schedule) are dropped
        keep = np.array([t in ratings for t in br["tid"]], bool)
        if not keep.all():
            br = {k: (v[keep] if isinstance(v, np.ndarray) else v) for k, v in br.items()}
    if not len(br["pid"]):
        return {"rows": {}, "params": None}
    keys = defaultdict(list)
    for k, (p, t) in enumerate(zip(br["pid"], br["tid"])):
        keys[(p, t)].append(k)
    gs = gmsc(br["X"])
    tot_min = sum(br["X"][:, 0]) / 60.0
    lg_g = 40.0 * gs.sum() / max(tot_min, 1)
    stints = {}
    for (p, t), ks in keys.items():
        ks = np.array(ks)
        Xs = br["X"][ks].sum(0)
        mins = Xs[0] / 60.0
        gsum = gs[ks].sum()
        stints[(p, t)] = {"gp": len(ks), "min": mins, "X": Xs, "gsum": gsum, "gs_starts": int(br["starter"][ks].sum()),
                          "games": ks}
    # team minutes-weighted g
    team_g = defaultdict(lambda: [0.0, 0.0])
    for (p, t), s in stints.items():
        team_g[t][0] += s["gsum"]
        team_g[t][1] += s["min"]
    tg = {t: 40.0 * v[0] / max(v[1], 1) for t, v in team_g.items() if v[1] > 200}
    xs = [(tg[t] - lg_g, ratings[t]["rating"]) for t in tg if t in ratings]
    if len(xs) >= 30:
        A = np.array(xs)
        a = float(np.polyfit(A[:, 0], A[:, 1], 1)[0])
    else:
        a = 1.5
    for (p, t), s in stints.items():
        g_raw = 40.0 * s["gsum"] / max(s["min"], 1e-6)
        s["g"] = (s["min"] * g_raw + K_MIN * lg_g) / (s["min"] + K_MIN)
    adj = {}
    for t in tg:
        r_t = (ratings.get(t) or {}).get("rating")
        if r_t is None:
            continue
        mins = [(s["min"], s["g"]) for (p, tt_), s in stints.items() if tt_ == t]
        mw = sum(m for m, _ in mins)
        gbar = sum(m * g for m, g in mins) / max(mw, 1)
        adj[t] = (r_t - a * (gbar - lg_g)) / 5.0
    for (p, t), s in stints.items():
        s["r"] = a / 5.0 * (s["g"] - lg_g) + adj.get(t, -3.0)
    # replacement: minutes-weighted r of players outside each team's top 8 in minutes
    bench = []
    by_team = defaultdict(list)
    for (p, t), s in stints.items():
        by_team[t].append(s)
    for t, ss in by_team.items():
        ss.sort(key=lambda s: -s["min"])
        bench += ss[8:]
    bw = sum(s["min"] for s in bench)
    repl = sum(s["min"] * s["r"] for s in bench) / bw if bw > 0 else -5.0
    # per-player primary rows (all stints summed; value summed over stints at each team's tempo)
    players = st.get("players") or {}
    rows = {}
    per_p = defaultdict(list)
    for (p, t), s in stints.items():
        per_p[p].append((t, s))
    tot = {}
    for (gidv, t), v in br["team_tot"].items():
        tot.setdefault(t, [0.0, 0.0, 0.0, 0.0])
        tot[t][0] += v["fga"]
        tot[t][1] += v["fta"]
        tot[t][2] += v["tov"]
        tot[t][3] += v["sec"]
    for p, lst in per_p.items():
        lst.sort(key=lambda x: -x[1]["min"])
        t0 = lst[0][0]
        X = sum(s["X"] for _, s in lst)
        mins = X[0] / 60.0
        gp = sum(s["gp"] for _, s in lst)
        var = 0.0
        for t, s in lst:
            tempo = (ratings.get(t) or {}).get("tempo") or D.DEFAULT_PACE[level]
            var += (s["r"] - repl) * s["min"] / 40.0 * tempo / 100.0
        r_p = sum(s["r"] * s["min"] for _, s in lst) / max(mins, 1e-6)
        sx = {k: X[i] for i, k in enumerate(STATS)}
        tt_ = tot.get(t0, [1, 1, 1, 1])
        used = sx["fga"] + 0.475 * sx["fta"] + sx["tov"]
        tm_used = tt_[0] + 0.475 * tt_[1] + tt_[2]
        usg = 100.0 * used * (tt_[3] / 60.0 / 5.0) / max(mins * tm_used, 1e-6) if mins > 0 else None
        per40 = {k: 40.0 * sx[k] / max(mins, 1e-6) for k in ("ast", "blk")}
        per40["reb"] = 40.0 * (sx["oreb"] + sx["dreb"]) / max(mins, 1e-6)
        pi = players.get(p) or {}
        rows[p] = {"id": p, "name": pi.get("name") or p, "team": t0, "teams": [t for t, _ in lst],
                   "pos": position(level, pi, per40), "class": pi.get("class"), "gp": gp, "gs": sum(s["gs_starts"] for _, s in lst),
                   "min": mins, "tot": sx, "r": r_p, "value": var, "value_pg": var / max(gp, 1),
                   "usg": usg, "ts": sx["pts"] / (2 * (sx["fga"] + 0.475 * sx["fta"])) if (sx["fga"] + sx["fta"]) > 0 else None,
                   "ortg": 100.0 * sx["pts"] / used if used > 0 else None}
    vals = sorted(r["value"] for r in rows.values())
    for r in rows.values():
        r["pctl"] = round(100.0 * np.searchsorted(vals, r["value"], side="right") / len(vals), 1)
    return {"rows": rows, "params": {"a": round(a, 4), "league_g": round(lg_g, 3), "repl": round(repl, 3), "k_min": K_MIN,
                                     "n_players": len(rows)}}


def per_game_line(r: dict) -> dict:
    gp = max(r["gp"], 1)
    t = r["tot"]
    return {"min": round(r["min"] / gp, 1), "pts": round(t["pts"] / gp, 1), "reb": round((t["oreb"] + t["dreb"]) / gp, 1),
            "ast": round(t["ast"] / gp, 1), "stl": round(t["stl"] / gp, 1), "blk": round(t["blk"] / gp, 1),
            "tov": round(t["tov"] / gp, 1),
            "fg_pct": round(t["fgm"] / t["fga"], 3) if t["fga"] else None,
            "tp_pct": round(t["tpm"] / t["tpa"], 3) if t["tpa"] else None,
            "ft_pct": round(t["ftm"] / t["fta"], 3) if t["fta"] else None,
            "ts": round(r["ts"], 3) if r.get("ts") is not None else None,
            "usg": round(r["usg"], 1) if r.get("usg") is not None else None,
            "ortg": round(r["ortg"], 1) if r.get("ortg") is not None else None}


def why(r: dict, params: dict) -> str:
    pg = per_game_line(r)
    bits = [f"{pg['pts']} pts, {pg['reb']} reb, {pg['ast']} ast in {pg['min']} min"]
    if pg.get("ts") is not None:
        bits.append(f"TS {pg['ts']:.3f}")
    bits.append(f"{r['r']:+.1f} per 100 v average (replacement {params['repl']:+.1f})")
    return "; ".join(bits)


# ── transfers (inferred) ────────────────────────────────────────────────────

def inferred_moves(prev_rows: dict, cur_team: dict[str, str], cur_rows: dict | None, players_info: dict) -> list[dict]:
    """Players whose primary team last season differs from this season's team (box scores, or this season's
    rosters before games). value_before = last season's value; value_after = this season's (None before games)."""
    out = []
    for p, t in cur_team.items():
        r0 = prev_rows.get(p)
        if not r0 or r0["team"] == t:
            continue
        r1 = (cur_rows or {}).get(p)
        pi = players_info.get(p) or {}
        out.append({"player": p, "name": r0["name"] or pi.get("name"), "pos": r0["pos"], "from": r0["team"], "to": t,
                    "value_before": round(r0["value"], 2), "value_after": round(r1["value"], 2) if r1 else None,
                    "class": pi.get("class") or r0.get("class"), "grade": grade(r0["pctl"])})
    out.sort(key=lambda m: -(m["value_before"] or 0))
    return out


def grade(p: float | None) -> str | None:
    if p is None:
        return None
    for cut, g in ((97, "A+"), (90, "A"), (80, "B+"), (70, "B"), (55, "C+"), (40, "C"), (25, "D")):
        if p >= cut:
            return g
    return "F"


def current_team_map(st: dict, rows: dict | None) -> dict[str, str]:
    """{pid: tid} for this season: box-score primary team where the player has played, else the roster."""
    out = {}
    for t, pids in (st.get("rosters") or {}).items():
        for p in pids or []:
            out[str(p)] = str(t)
    for p, r in (rows or {}).items():
        out[p] = r["team"]
    return out


def returning_value(prev_rows: dict, cur_team: dict[str, str], members: list[str]) -> dict[str, dict]:
    """{tid: {"ret": value of last season's players now on the team (any team last season) = "ret_same" (its own
    players returning) + "ret_in" (incoming D-I transfers, "n_in" of them), "lost": value of the team's last-season
    players now elsewhere or gone, "prev": the team's last-season total}}: the roster-turnover features."""
    out = {t: {"ret": 0.0, "ret_same": 0.0, "ret_in": 0.0, "n_in": 0, "lost": 0.0, "prev": 0.0, "ret_min": 0.0,
               "prev_min": 0.0} for t in members}
    for p, r in prev_rows.items():
        t0 = r["team"]
        v = max(r["value"], -5.0)
        if t0 in out:
            out[t0]["prev"] += v
            out[t0]["prev_min"] += r["min"]
        t1 = cur_team.get(p)
        if t1 in out:
            out[t1]["ret"] += v
            if t1 == t0:
                out[t1]["ret_min"] += r["min"]
                out[t1]["ret_same"] += v
            else:
                out[t1]["ret_in"] += v
                out[t1]["n_in"] += 1
        if t0 in out and t1 != t0:
            out[t0]["lost"] += v
    return out


# ── strengths and needs ─────────────────────────────────────────────────────

def units(level: str, rows: dict, team_stats: dict[str, dict]) -> dict[str, list[dict]]:
    """{tid: [UNIT]} graded against every team: G / F / C value (sum of player VAR at the position) plus
    offense / defense / tempo-free facets (team_stats: {tid: {"off","def","efg","tov_rate","orb_rate","ftr",
    "opp_efg"}} where present)."""
    pos_val = defaultdict(lambda: {"G": 0.0, "F": 0.0, "C": 0.0})
    top = defaultdict(lambda: {"G": [], "F": [], "C": []})
    for r in rows.values():
        pos_val[r["team"]][r["pos"]] += r["value"]
        top[r["team"]][r["pos"]].append(r)
    teams = sorted(set(pos_val) | set(team_stats))
    facets = [("G", "Guards", False), ("F", "Forwards", False), ("C", "Centers", False),
              ("off", "Offense (adj. pts/100)", False), ("def", "Defense (adj. pts/100 allowed)", True),
              ("efg", "Shooting (eFG%)", False), ("tov_rate", "Ball security (TO rate)", True),
              ("orb_rate", "Offensive rebounding", False), ("ftr", "Getting to the line (FTA/FGA)", False),
              ("opp_efg", "Shot defense (opp. eFG%)", True)]
    vals = {}
    for key, _, low in facets:
        v = {}
        for t in teams:
            x = pos_val[t][key] if key in ("G", "F", "C") else (team_stats.get(t) or {}).get(key)
            if x is not None:
                v[t] = float(x)
        vals[key] = v
    out = {}
    for t in teams:
        us = []
        for key, label, low in facets:
            v = vals[key]
            if t not in v or len(v) < 20:
                continue
            arr = np.array(sorted(v.values()))
            pct = 100.0 * np.searchsorted(arr, v[t], side="right") / len(arr)
            if low:
                pct = 100.0 - pct + 100.0 / len(arr)
            pct = float(np.clip(pct, 0, 100))
            if key in ("G", "F", "C"):
                best = sorted(top[t][key], key=lambda r: -r["value"])[:2]
                ev = ", ".join(f"{r['name']} {r['value']:+.1f}" for r in best) or "no minutes at the position"
                ev = f"{v[t]:+.1f} pts above replacement ({ev})"
            elif key in ("efg", "opp_efg", "tov_rate", "orb_rate", "ftr"):
                ev = f"{v[t]:.3f}"
            else:
                ev = f"{v[t]:.1f}"
            us.append({"unit": label, "key": key, "grade": grade(pct), "pctl": round(pct, 1),
                       "value": round(v[t], 3), "evidence": ev})
        out[t] = us
    return out


def suggestions(tid: str, needs: list[dict], rows: dict, team_rows: list[dict], k: int = 5) -> list[dict]:
    """For each positional need (G/F/C): the best players at that position on other teams, with the gain over the
    team's weakest rotation player at the position (value per game x the team's games). Model suggestions only."""
    out = []
    for nd in needs:
        key = nd.get("key")
        if key not in ("G", "F", "C"):
            continue
        mine = sorted([r for r in team_rows if r["pos"] == key], key=lambda r: -r["min"])[:3]
        floor = min((r["value_pg"] for r in mine), default=0.0)
        cands = sorted((r for r in rows.values() if r["pos"] == key and r["team"] != tid and r["gp"] >= 10),
                       key=lambda r: -r["value_pg"])[:k]
        out.append({"need": nd["unit"], "candidates": [{"id": r["id"], "name": r["name"], "team": r["team"],
                                                        "value": round(r["value"], 2),
                                                        "gain": round((r["value_pg"] - floor) * 30, 2)} for r in cands]})
    return out


# ── fantasy ─────────────────────────────────────────────────────────────────

def fp_of(X: np.ndarray) -> np.ndarray:
    s = {k: X[:, i] for i, k in enumerate(STATS)}
    return (FANTASY_W["pts"] * s["pts"] + FANTASY_W["reb"] * (s["oreb"] + s["dreb"]) + FANTASY_W["ast"] * s["ast"]
            + FANTASY_W["stl"] * s["stl"] + FANTASY_W["blk"] * s["blk"] + FANTASY_W["tov"] * s["tov"])


def fantasy_backtest(br: dict, half_life: float = 8.0, min_games: int = 3) -> dict:
    """Walk-forward check of the per-game projection (exponentially weighted per-minute fantasy rate x weighted
    minutes, half-life `half_life` games, from games on earlier days only) against the naive season-to-date
    average fantasy points per game. Player-games after the player's `min_games`-th game; rank correlation per
    day (Spearman) over players with a projection."""
    if not len(br["pid"]):
        return {"n": 0}
    fp = fp_of(br["X"])
    mins = br["X"][:, 0] / 60.0
    order = np.lexsort((br["day"], br["pid"]))
    lam = 0.5 ** (1.0 / half_life)
    proj, naive, act, days = [], [], [], []
    prev_p = None
    for k in order:
        p = br["pid"][k]
        if p != prev_p:
            n = 0
            s_fp = s_min = w_fp = w_min = w_n = 0.0
            prev_p = p
        if n >= min_games:
            rate = w_fp / max(w_min, 1e-6)
            m_hat = w_min / max(w_n, 1e-6)
            proj.append(rate * m_hat)
            naive.append(s_fp / n)
            act.append(fp[k])
            days.append(br["day"][k])
        n += 1
        s_fp += fp[k]
        s_min += mins[k]
        w_fp = lam * w_fp + fp[k]
        w_min = lam * w_min + mins[k]
        w_n = lam * w_n + 1.0
    proj, naive, act, days = map(np.array, (proj, naive, act, days))
    if not len(act):
        return {"n": 0}

    def spearman_by_day(pred):
        cs = []
        for d in np.unique(days):
            m = days == d
            if m.sum() >= 20:
                a = np.argsort(np.argsort(pred[m]))
                b = np.argsort(np.argsort(act[m]))
                cs.append(np.corrcoef(a, b)[0, 1])
        return float(np.nanmean(cs)) if cs else None
    return {"n": int(len(act)), "mae": round(float(np.mean(np.abs(proj - act))), 3),
            "mae_naive": round(float(np.mean(np.abs(naive - act))), 3),
            "rank_corr": round(spearman_by_day(proj) or 0, 4), "rank_corr_naive": round(spearman_by_day(naive) or 0, 4),
            "half_life": half_life, "scoring": FANTASY_W}


def nine_cat(lines: dict[str, dict], pool_n: int = 200) -> dict[str, dict]:
    """Per-game z-scores over the top `pool_n` players by fantasy points; percentages weighted by attempts."""
    ids = sorted(lines, key=lambda p: -lines[p]["fp"])[:pool_n]
    if len(ids) < 20:
        return {}
    def arr(k):
        return np.array([lines[p][k] for p in ids], float)
    z = {}
    for c in ("pts", "reb", "ast", "stl", "blk", "tpm"):
        a = arr(c)
        z[c] = (a.mean(), a.std() + 1e-9)
    fgm, fga, ftm, fta = arr("fgm"), arr("fga"), arr("ftm"), arr("fta")
    lg_fg, lg_ft = fgm.sum() / max(fga.sum(), 1), ftm.sum() / max(fta.sum(), 1)
    fgi, fti = (fgm - lg_fg * fga), (ftm - lg_ft * fta)
    tv = arr("tov")
    out = {}
    for p, L in lines.items():
        s = sum((L[c] - z[c][0]) / z[c][1] for c in z)
        s += (L["fgm"] - lg_fg * L["fga"] - fgi.mean()) / (fgi.std() + 1e-9)
        s += (L["ftm"] - lg_ft * L["fta"] - fti.mean()) / (fti.std() + 1e-9)
        s -= (L["tov"] - tv.mean()) / (tv.std() + 1e-9)
        out[p] = s
    ranks = sorted(out, key=lambda p: -out[p])
    return {p: {"z": round(out[p], 3), "rank": i + 1} for i, p in enumerate(ranks)}
