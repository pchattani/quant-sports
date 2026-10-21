"""Preview payloads for The Quant Campus front end (builder D's development fixture; not a model).

Writes every payload of oddsmarkets/college/PAYLOADS.md for a few levels and seasons from the real stores,
with PLACEHOLDER model numbers (a least-squares margin rating, a normal game model, a crude Monte Carlo season),
so the front end can be built and checked before the real football (B) and basketball (C) payloads exist.

Never write this into docs/campus/data: the output folder is explicit, and the local preview server maps it
under /_preview/ (the page reads it with ?data=/_preview/ in local preview only).

    uv run --frozen python tests/college/fixtures/site/make_preview.py OUT_DIR [--levels cfb,mbb,wbb]

The small JSON fixtures the site tests read (tests/college/fixtures/site/data) are trimmed from this output by
`--fixture`, which keeps only a handful of teams and games.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from oddsmarkets.college import store as cstore  # noqa: E402

NOW = datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc)
NOW_S = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
SD = {"cfb": 15.5, "mbb": 11.0, "wbb": 11.5}
HFA = {"cfb": 2.5, "mbb": 3.2, "wbb": 3.0}
CAP = {"cfb": 28, "mbb": 30, "wbb": 30}
SEASONS = {"cfb": [2025, 2026], "mbb": [2026, 2027], "wbb": [2026, 2027]}
CURRENT = {"cfb": 2026, "mbb": 2027, "wbb": 2027}
RNG = random.Random(7)


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def r4(x):
    return None if x is None else round(float(x), 4)


def r2(x):
    return None if x is None else round(float(x), 2)


def dump(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))


def member_ids(st):
    return {t for t, v in st["teams"].items() if v.get("member")}


def fit_ratings(L, games, members, until=None):
    """Least-squares margin rating (placeholder for B/C's models)."""
    ids = sorted(members)
    ix = {t: i for i, t in enumerate(ids)}
    rows, ys = [], []
    for g in games:
        if g["status"] != "post" or g.get("hs") is None:
            continue
        if until and g["date"] >= until:
            continue
        h, a = g["home"], g["away"]
        if h not in ix and a not in ix:
            continue
        r = np.zeros(len(ids) + 2)
        if h in ix:
            r[ix[h]] = 1
        else:
            r[-1] -= 1
        if a in ix:
            r[ix[a]] = -1
        else:
            r[-1] += 1
        r[-2] = 0 if g.get("neutral") else 1
        rows.append(r)
        m = g["hs"] - g["as"]
        ys.append(max(-CAP[L], min(CAP[L], m)))
    if not rows:
        return {}
    X = np.array(rows)
    y = np.array(ys, dtype=float)
    lam = 2.0
    A = X.T @ X + lam * np.eye(X.shape[1])
    A[-2, -2] -= lam
    b = np.linalg.solve(A, X.T @ y)
    mean = b[: len(ids)].mean()
    out = {t: float(b[ix[t]] - mean) for t in ids}
    return out


def card(L, S, g, R, members):
    rh, ra = R.get(g["home"], -12 if g["home"] not in members else 0), R.get(g["away"], -12 if g["away"] not in members else 0)
    margin = rh - ra + (0 if g.get("neutral") else HFA[L])
    p = phi(margin / SD[L])
    tot = (52 if L == "cfb" else 142) + RNG.uniform(-6, 6)
    o = g.get("odds") or {}
    market = None
    if o.get("spread_home") is not None:
        market = {"p_home": r4(phi(-o["spread_home"] / SD[L])), "spread_home": o["spread_home"], "total": o.get("total"),
                  "source": "espn_close" if g["status"] == "post" else "espn"}
    res = None
    if g["status"] == "post" and g.get("hs") is not None:
        cover = None
        if market:
            v = g["hs"] - g["as"] + market["spread_home"]
            cover = "push" if v == 0 else ("home" if v > 0 else "away")
        res = {"cover": cover, "model_correct": (p > 0.5) == (g["hs"] > g["as"])}
    return {"id": g["id"], "season": S, "date": g["date"], "status": g["status"], "stype": g["stype"], "round": g.get("round"),
            "region": g.get("region"), "note": g.get("note"), "week": g.get("week"), "home": g["home"], "away": g["away"],
            "hs": g.get("hs"), "as": g.get("as"), "hr": (g.get("ranks") or {}).get("home"), "ar": (g.get("ranks") or {}).get("away"),
            "hseed": (g.get("seeds") or {}).get("home"), "aseed": (g.get("seeds") or {}).get("away"),
            "neutral": g.get("neutral"), "conf_game": g.get("conf_game"), "period": None, "clock": None,
            "model": {"p_home": r4(p), "margin": r2(margin), "total": r2(tot)}, "market": market, "result": res}


def team_obj(t):
    return {"name": t["name"], "short": t.get("short"), "abbr": t.get("abbr"), "colour": t.get("colour"),
            "alt_colour": t.get("alt_colour"), "conference": t.get("conference"), "member": bool(t.get("member"))}


def latest_poll(st, kind):
    p = (st.get("rankings") or {}).get(kind) or {}
    if not p:
        return [], None
    def key(w):
        return (2, 0) if w == "final" else ((0, 0) if w == "pre" else ((1, int(w)) if w.isdigit() else (1.5, 0)))
    ws = sorted(p.keys(), key=key)
    cur = p[ws[-1]]
    prev = {r[1]: r[0] for r in p[ws[-2]]} if len(ws) > 1 else {}
    return [{"rank": r[0], "team": r[1], "points": r[2], "first": r[3], "prev": prev.get(r[1])} for r in cur], ws[-1]


# ───────────────────────────────────────────────────────────── players
def fb_player_stats(st, members):
    P = defaultdict(lambda: defaultdict(float))
    games_of = defaultdict(set)
    logs = defaultdict(list)
    for g in st["games"].values():
        if not g.get("box"):
            continue
        for tid, b in g["box"].items():
            for cat, blk in (b.get("players") or {}).items():
                cols = blk["cols"]
                for row in blk["rows"]:
                    pid = row[0]
                    d = dict(zip(cols, row[1:]))
                    games_of[pid].add(g["id"])
                    P[pid]["team"] = tid
                    if cat == "passing":
                        P[pid]["cmp"] += d.get("cmp") or 0; P[pid]["att"] += d.get("att") or 0
                        P[pid]["pass_yds"] += d.get("passing_yards") or 0; P[pid]["pass_td"] += d.get("passing_touchdowns") or 0
                        P[pid]["int"] += d.get("interceptions") or 0
                    elif cat == "rushing":
                        P[pid]["car"] += d.get("rushing_attempts") or 0; P[pid]["rush_yds"] += d.get("rushing_yards") or 0
                        P[pid]["rush_td"] += d.get("rushing_touchdowns") or 0
                    elif cat == "receiving":
                        P[pid]["rec"] += d.get("receptions") or 0; P[pid]["rec_yds"] += d.get("receiving_yards") or 0
                        P[pid]["rec_td"] += d.get("receiving_touchdowns") or 0
                    elif cat == "defensive":
                        P[pid]["tkl"] += d.get("total_tackles") or d.get("tackles") or 0
                        P[pid]["sacks"] += d.get("sacks") or 0; P[pid]["tfl"] += d.get("tackles_for_loss") or 0
                        P[pid]["pd"] += d.get("passes_defended") or 0
                    elif cat == "interceptions":
                        P[pid]["def_int"] += d.get("interceptions") or 0
                    elif cat == "kicking":
                        P[pid]["fgm"] += d.get("fgm") or 0
    out = {}
    for pid, s in P.items():
        gp = len(games_of[pid])
        v = (s["pass_yds"] * 0.04 + s["pass_td"] * 4 - s["int"] * 4 + s["rush_yds"] * 0.1 + s["rush_td"] * 6 + s["rec_yds"] * 0.1
             + s["rec_td"] * 6 + s["tkl"] * 0.8 + s["sacks"] * 4 + s["tfl"] * 1.5 + s["def_int"] * 5 + s["pd"] * 1.5 + s["fgm"] * 2.5)
        epa = v * 0.35 - gp * 2.5
        out[pid] = dict(s)
        out[pid].update({"gp": gp, "value": round(epa, 1), "epa": round(epa, 1), "epa_play": round(epa / max(1, s["att"] + s["car"] + s["rec"] * 1.6 + s["tkl"]), 3)})
    return out


def bb_player_stats(st, members):
    P = defaultdict(lambda: defaultdict(float))
    for g in st["games"].values():
        for tid, b in (g.get("box") or {}).items():
            for row in b.get("players") or []:
                pid = row[0]
                s = P[pid]
                s["team"] = tid
                s["gp"] += 1
                for k, v in zip(cstore.BOX_COLS[2:], row[2:]):
                    s[k] += v or 0
    out = {}
    for pid, s in P.items():
        gp = s["gp"]
        if not gp:
            continue
        reb = s["oreb"] + s["dreb"]
        val = (s["pts"] + reb * 1.1 + s["ast"] * 1.5 + s["stl"] * 2 + s["blk"] * 1.5 - s["tov"] * 1.5 - (s["fga"] - s["fgm"]) * 0.8
               - (s["fta"] - s["ftm"]) * 0.4) / 10 - gp * 0.25
        tsa = s["fga"] + 0.44 * s["fta"]
        out[pid] = {"team": s["team"], "gp": int(gp), "min": round(s["sec"] / 60 / gp, 1), "pts": round(s["pts"] / gp, 1), "reb": round(reb / gp, 1),
                    "ast": round(s["ast"] / gp, 1), "stl": round(s["stl"] / gp, 1), "blk": round(s["blk"] / gp, 1), "tov": round(s["tov"] / gp, 1),
                    "fg_pct": round(s["fgm"] / s["fga"], 3) if s["fga"] else None, "tp_pct": round(s["tpm"] / s["tpa"], 3) if s["tpa"] else None,
                    "ft_pct": round(s["ftm"] / s["fta"], 3) if s["fta"] else None, "ts": round(s["pts"] / (2 * tsa), 3) if tsa else None,
                    "usg": round(min(40, 8 + (s["fga"] + 0.44 * s["fta"] + s["tov"]) / gp * 1.1), 1), "ortg": round(90 + val / gp * 6, 1),
                    "value": round(val, 2), "value_pg": round(val / gp, 3)}
    return out


def fb_pos(st, pid, s):
    p = (st["players"].get(pid) or {}).get("pos")
    if p:
        return p
    if s.get("att", 0) > 20:
        return "QB"
    if s.get("car", 0) > s.get("rec", 0) and s.get("car", 0) > 5:
        return "RB"
    if s.get("rec", 0) > 3:
        return "WR"
    if s.get("tkl", 0) > 3:
        return "LB"
    return "ATH"


def bb_pos(st, pid):
    p = ((st["players"].get(pid) or {}).get("pos") or "G")[:1].upper()
    return p if p in "GFC" else "G"


# ───────────────────────────────────────────────────────────── main per level/season
def build_season(L, S, out: Path, prevR=None):
    st = cstore.load(L, S)
    members = member_ids(st)
    games = sorted(st["games"].values(), key=lambda g: g["date"])
    fb = L == "cfb"
    R = fit_ratings(L, games, members)
    if not R or len([g for g in games if g["status"] == "post"]) < 50:
        R = {t: (prevR or {}).get(t, 0.0) * 0.65 + RNG.gauss(0, 1.5) for t in members}
    teams = {t: team_obj(v) for t, v in st["teams"].items()}
    confs = {}
    for t in members:
        c = st["teams"][t].get("conference")
        if c and c in st["conferences"]:
            confs.setdefault(c, {"name": st["conferences"][c]["name"], "short": st["conferences"][c].get("short"), "teams": []})["teams"].append(t)
    cards = [card(L, S, g, R, members) for g in games if g["home"] in members or g["away"] in members]
    played = [g for g in games if g["status"] == "post" and g.get("hs") is not None]
    # ratings
    order = sorted(members, key=lambda t: -R.get(t, 0))
    rank = {t: i + 1 for i, t in enumerate(order)}
    ratings = {}
    gp = defaultdict(int)
    for g in played:
        gp[g["home"]] += 1; gp[g["away"]] += 1
    sos = {}
    for t in members:
        opp = [R.get(g["away"] if g["home"] == t else g["home"], -12) for g in games if t in (g["home"], g["away"])]
        sos[t] = float(np.mean(opp)) if opp else 0.0
    sos_rank = {t: i + 1 for i, t in enumerate(sorted(members, key=lambda t: -sos[t]))}
    for t in members:
        r = R.get(t, 0.0)
        if fb:
            ratings[t] = {"rating": r2(r), "off": r2(28 + r * 0.55), "def": r2(28 - r * 0.45), "se": r2(2.0 + 6 / (1 + gp[t])), "rank": rank[t],
                          "games": gp[t], "epa_off": r4(0.02 * r / 3), "epa_def": r4(-0.015 * r / 3), "sr_off": r4(0.42 + r / 300), "sr_def": r4(0.42 - r / 320),
                          "pts_rating": r2(r + RNG.gauss(0, 1.2)), "sos": r2(sos[t]), "sos_rank": sos_rank[t]}
        else:
            ratings[t] = {"rating": r2(r), "off": r2(108 + r * 0.55), "def": r2(108 - r * 0.45), "tempo": r2(68 + RNG.gauss(0, 2.5)), "se": r2(1.5 + 5 / (1 + gp[t])),
                          "rank": rank[t], "games": gp[t], "sos": r2(sos[t]), "sos_rank": sos_rank[t], "luck": r4(RNG.gauss(0, 0.03))}
    # rating paths
    paths = defaultdict(list)
    if played:
        d0, d1 = played[0]["date"][:10], played[-1]["date"][:10]
        dates = sorted({g["date"][:10] for g in played})
        step = 7
        cps = dates[::step] + [dates[-1]] if dates else []
        for d in cps[1:]:
            Rd = fit_ratings(L, games, members, until=d + "T23:59:59Z")
            for t in members:
                if t in Rd:
                    paths[t].append([d, r2(0.5 * Rd[t] + 0.5 * (prevR or {}).get(t, Rd[t]) if d < dates[len(dates) // 4] else Rd[t])])
    else:
        for t in members:
            paths[t] = [[f"{S - (0 if fb else 1)}-10-15", r2(R.get(t, 0))]]
    # standings
    rec = {t: {"team": t, "w": 0, "l": 0, "conf_w": 0, "conf_l": 0, "home": [0, 0], "away": [0, 0], "neutral": [0, 0], "streak": "", "pf": 0, "pa": 0} for t in members}
    streak = defaultdict(list)
    for g in played:
        for side, t, pf, pa in (("home", g["home"], g["hs"], g["as"]), ("away", g["away"], g["as"], g["hs"])):
            if t not in rec:
                continue
            w = pf > pa
            r = rec[t]
            r["w" if w else "l"] += 1
            if g.get("conf_game"):
                r["conf_w" if w else "conf_l"] += 1
            k = "neutral" if g.get("neutral") else side
            r[k][0 if w else 1] += 1
            r["pf"] += pf; r["pa"] += pa
            streak[t].append("W" if w else "L")
    ap, apw = latest_poll(st, "ap")
    aprank = {x["team"]: x["rank"] for x in ap}
    standings = {}
    for c, info in confs.items():
        rows = []
        for t in info["teams"]:
            r = dict(rec[t])
            s = streak[t]
            if s:
                n = 1
                while n < len(s) and s[-n - 1] == s[-1]:
                    n += 1
                r["streak"] = s[-1] + str(n)
            r["rank"] = aprank.get(t)
            r["rating_rank"] = rank[t]
            rows.append(r)
        rows.sort(key=lambda r: (-(r["conf_w"] - r["conf_l"]), -(r["w"] - r["l"]), r["rating_rank"]))
        for i, r in enumerate(rows):
            r["conf_rank"] = i + 1
        standings[c] = rows
    # sims
    sim, cfp, bracket = simulate(L, S, st, games, members, R, confs, rec, rank)
    polls = {"ap": ap, "coaches": latest_poll(st, "coaches")[0]}
    if fb:
        polls["cfp"] = latest_poll(st, "cfp")[0]
    power = [{"rank": rank[t], "team": t, "rating": r2(R.get(t, 0)), "prev_rank": max(1, rank[t] + RNG.randint(-3, 3))} for t in order]
    # players
    ps = fb_player_stats(st, members) if fb else bb_player_stats(st, members)
    for pid, s in ps.items():
        s["pos"] = fb_pos(st, pid, s) if fb else bb_pos(st, pid)
    leaders = {}
    keys = ["pass_yds", "rush_yds", "rec_yds", "sacks", "tkl", "epa"] if fb else ["pts", "reb", "ast", "stl", "blk", "value"]
    for k in keys:
        rr = sorted([(pid, s) for pid, s in ps.items() if s.get("gp", 0) >= (2 if fb else 5)], key=lambda x: -(x[1].get(k) or 0))[:10]
        leaders[k] = [[pid, s["team"], round(s.get(k) or 0, 1)] for pid, s in rr]
    phase = ("regular" if S == CURRENT[L] else "offseason") if fb else ("preseason" if S == CURRENT[L] else "offseason")
    week = 8 if fb and S == CURRENT[L] else None
    fmt = {"cfp": {"teams": 12, "auto_bids": 5, "byes": 0 if S >= 2025 else 4, "rule": "2025 rules assumed" if S >= 2026 else ("straight seeding" if S == 2025 else "byes to top four conference champions"), "verified": S <= 2025}} if fb else \
        {"ncaa": {"field": 68, "at_large": 37 if L == "mbb" else 37, "first_four": True, "verified": S <= 2026}}
    D = out / L / str(S)
    season = {"ok": True, "level": L, "season": S, "updated_at": NOW_S, "phase": phase, "week": week, "format": fmt,
              "conferences": confs, "teams": teams, "standings": standings, "ratings": ratings, "rating_paths": dict(paths),
              "polls": polls, "power": power, "sim": {"n_sims": 2000, "teams": sim, "notes": ["Preview fixture: placeholder numbers, not the model."]},
              "leaders": leaders}
    dump(D / "season.json", season)
    dump(D / "schedule.json", {"ok": True, "level": L, "season": S, "updated_at": NOW_S, "games": cards})
    if fb:
        dump(D / "cfp.json", cfp)
    else:
        dump(D / "bracket.json", bracket)
    players_payloads(L, S, D, st, ps, teams, members, rank, ratings, sim, cards, prevR)
    game_pages(L, S, D, st, games, cards, teams, ps)
    return R, season, ps, cards


def simulate(L, S, st, games, members, R, confs, rec, rank, n=600):
    fb = L == "cfb"
    rem = [g for g in games if g["status"] == "pre" and g["home"] in members and g["away"] in members and g["stype"] in ("reg", None)]
    ids = sorted(members)
    ix = {t: i for i, t in enumerate(ids)}
    base_w = np.array([rec[t]["w"] for t in ids], float)
    base_l = np.array([rec[t]["l"] for t in ids], float)
    W = np.tile(base_w, (n, 1))
    for g in rem:
        m = R.get(g["home"], 0) - R.get(g["away"], 0) + (0 if g.get("neutral") else HFA[L])
        p = phi(m / SD[L])
        u = np.random.default_rng(int(g["id"]) % 99991).random(n) < p
        W[:, ix[g["home"]]] += u
        W[:, ix[g["away"]]] += ~u
    tot_games = base_w + base_l + np.array([sum(1 for g in rem if t in (g["home"], g["away"])) for t in ids])
    r_arr = np.array([R.get(t, 0) for t in ids])
    sim = {}
    rng = np.random.default_rng(S)
    if fb:
        score = r_arr[None, :] * 0.6 + W * 3.0 + rng.normal(0, 2, (n, len(ids)))
        p_conf = np.zeros(len(ids)); p_cfp = np.zeros(len(ids)); p_bye = np.zeros(len(ids)); rounds = np.zeros((len(ids), 4)); seedc = np.zeros((len(ids), 13))
        for k in range(n):
            champs = []
            for c, info in confs.items():
                js = [ix[t] for t in info["teams"]]
                if not js:
                    continue
                j = max(js, key=lambda j: score[k, j] + rng.normal(0, 3))
                champs.append(j); p_conf[j] += 1
            order = list(np.argsort(-score[k]))
            auto = sorted(champs, key=lambda j: -score[k, j])[:5]
            field = auto + [j for j in order if j not in auto][: 12 - len(auto)]
            field = sorted(field, key=lambda j: -score[k, j])
            for s_, j in enumerate(field):
                p_cfp[j] += 1; seedc[j, s_ + 1] += 1
                if s_ < 4:
                    p_bye[j] += 1
            def play(a, b):
                return a if rng.random() < phi((r_arr[a] - r_arr[b]) / SD[L]) else b
            seeds = field
            qf = [seeds[0], seeds[1], seeds[2], seeds[3]]
            fr = [play(seeds[4], seeds[11]), play(seeds[5], seeds[10]), play(seeds[6], seeds[9]), play(seeds[7], seeds[8])]
            for j in qf + fr:
                rounds[j, 0] += 1
            q = [play(qf[0], fr[3]), play(qf[1], fr[2]), play(qf[2], fr[1]), play(qf[3], fr[0])]
            for j in q:
                rounds[j, 1] += 1
            f = [play(q[0], q[3]), play(q[1], q[2])]
            for j in f:
                rounds[j, 2] += 1
            rounds[play(f[0], f[1]), 3] += 1
        for t in ids:
            j = ix[t]
            wd = np.bincount(W[:, j].astype(int), minlength=int(tot_games[j]) + 1) / n
            sim[t] = {"exp_w": r2(W[:, j].mean()), "exp_l": r2(tot_games[j] - W[:, j].mean()), "w_dist": [r4(x) for x in wd],
                      "p_bowl": r4((W[:, j] >= 6).mean()), "p_conf_game": r4(min(1, p_conf[j] / n * 1.7)), "p_conf": r4(p_conf[j] / n),
                      "p_cfp": r4(p_cfp[j] / n), "p_bye": r4(p_bye[j] / n),
                      "p_round": {"qf": r4(rounds[j, 0] / n), "sf": r4(rounds[j, 1] / n), "final": r4(rounds[j, 2] / n), "title": r4(rounds[j, 3] / n)},
                      "seed_dist": {str(s): r4(seedc[j, s] / n) for s in range(1, 13) if seedc[j, s]}, "p_title": r4(rounds[j, 3] / n), "next": None}
        nxt = {}
        for g in sorted(rem, key=lambda g: g["date"]):
            for t, o, h in ((g["home"], g["away"], True), (g["away"], g["home"], False)):
                if t not in nxt:
                    m = R.get(g["home"], 0) - R.get(g["away"], 0) + (0 if g.get("neutral") else HFA[L])
                    p = phi(m / SD[L])
                    nxt[t] = {"game": g["id"], "opp": o, "p_win": r4(p if h else 1 - p)}
        for t in sim:
            sim[t]["next"] = nxt.get(t)
        cfp = cfp_payload(L, S, st, games, ids, sim, R, rank, confs, rec)
        return sim, cfp, None
    # basketball
    score = r_arr[None, :] + rng.normal(0, 2.5, (n, len(ids)))
    p_ncaa = np.zeros(len(ids)); p_auto = np.zeros(len(ids)); p_conf_t = np.zeros(len(ids)); seedc = np.zeros((len(ids), 17)); rounds = np.zeros((len(ids), 7))
    for k in range(n):
        autos = []
        for c, info in confs.items():
            js = [ix[t] for t in info["teams"]]
            if not js:
                continue
            j = max(js, key=lambda j: score[k, j] + rng.normal(0, 4))
            autos.append(j); p_conf_t[j] += 1; p_auto[j] += 1
        order = [j for j in np.argsort(-score[k])]
        field = list(dict.fromkeys(autos + [j for j in order if j not in autos][: 68 - len(autos)]))[:68]
        field = sorted(field, key=lambda j: -score[k, j])
        for s_, j in enumerate(field[:64]):
            p_ncaa[j] += 1; seedc[j, s_ // 4 + 1] += 1
        regions = [[] for _ in range(4)]
        for s_, j in enumerate(field[:64]):
            regions[(s_ % 4) if (s_ // 4) % 2 == 0 else 3 - (s_ % 4)].append(j)
        def play(a, b):
            return a if rng.random() < phi((r_arr[a] - r_arr[b]) / 11) else b
        winners = []
        for reg in regions:
            pairs = [(0, 15), (7, 8), (4, 11), (3, 12), (5, 10), (2, 13), (6, 9), (1, 14)]
            cur = [play(reg[a], reg[b]) for a, b in pairs]
            for j in reg:
                rounds[j, 0] += 1
            lvl = 1
            while len(cur) > 1:
                for j in cur:
                    rounds[j, lvl] += 1
                cur = [play(cur[i], cur[i + 1]) for i in range(0, len(cur), 2)]
                lvl += 1
            winners.append(cur[0])
        for j in winners:
            rounds[j, 4] += 1
        f = [play(winners[0], winners[1]), play(winners[2], winners[3])]
        for j in f:
            rounds[j, 5] += 1
        rounds[play(f[0], f[1]), 6] += 1
    for t in ids:
        j = ix[t]
        sd_ = {str(s): r4(seedc[j, s] / n) for s in range(1, 17) if seedc[j, s]}
        mean_seed = sum(int(s) * p for s, p in sd_.items()) / max(1e-9, sum(sd_.values())) if sd_ else None
        sim[t] = {"exp_w": r2(W[:, j].mean()), "exp_l": r2(tot_games[j] - W[:, j].mean()), "exp_conf_w": r2(W[:, j].mean() * 0.55), "exp_conf_l": r2((tot_games[j] - W[:, j].mean()) * 0.6),
                  "p_conf_reg": r4(p_conf_t[j] / n * 0.9), "p_conf_tourney": r4(p_conf_t[j] / n), "p_ncaa": r4(p_ncaa[j] / n), "p_auto": r4(p_auto[j] / n),
                  "p_at_large": r4(max(0, p_ncaa[j] - p_auto[j]) / n), "seed_mean": r2(mean_seed), "seed_dist": sd_,
                  "p_round": {"r32": r4(rounds[j, 1] / n), "s16": r4(rounds[j, 2] / n), "e8": r4(rounds[j, 3] / n), "f4": r4(rounds[j, 4] / n), "final": r4(rounds[j, 5] / n), "title": r4(rounds[j, 6] / n)},
                  "p_title": r4(rounds[j, 6] / n)}
    br = bracket_payload(L, S, st, games, ids, sim, R, rank, confs, rec)
    return sim, None, br


def cfp_payload(L, S, st, games, ids, sim, R, rank, confs, rec):
    teams = st["teams"]
    cfpg = [g for g in games if g["stype"] == "cfp"]
    actual = None
    if cfpg:
        seeds = {}
        for g in cfpg:
            for side in ("home", "away"):
                sd = (g.get("seeds") or {}).get(side)
                if sd:
                    seeds[g[side]] = sd
        RN = {"First Round": "First Round", "Quarterfinal": "Quarterfinal", "Semifinal": "Semifinal", "National Championship": "National Championship"}
        gl = []
        for i, g in enumerate(sorted(cfpg, key=lambda g: g["date"])):
            w = None
            if g["status"] == "post":
                w = g["home"] if g["hs"] > g["as"] else g["away"]
            m = R.get(g["home"], 0) - R.get(g["away"], 0)
            gl.append({"round": RN.get(g["round"], g["round"]), "slot": i, "home": g["home"], "away": g["away"], "p_home": r4(phi(m / SD[L])), "winner": w, "gid": g["id"]})
        actual = {"rankings": latest_poll(st, "cfp")[0][:25], "bracket": {"seeds": [{"seed": s, "team": t, "auto": False} for t, s in sorted(seeds.items(), key=lambda x: x[1])], "games": gl}}
    top = sorted(ids, key=lambda t: -(sim[t]["p_cfp"] or 0))
    proxy = []
    for i, t in enumerate(sorted(ids, key=lambda t: -(R.get(t, 0) + rec[t]["w"] * 2))[:30]):
        proxy.append({"rank": i + 1, "team": t, "score": r2(R.get(t, 0) + rec[t]["w"] * 2), "p_top12": r4(sim[t]["p_cfp"]), "p_in": r4(sim[t]["p_cfp"]),
                      "p_bye": r4(sim[t]["p_bye"]), "record": f"{rec[t]['w']}-{rec[t]['l']}", "sos_rank": rank[t], "conf_champ_p": r4(sim[t]["p_conf"])})
    field = top[:12]
    field = sorted(field, key=lambda t: -(R.get(t, 0) + rec[t]["w"] * 2))
    seeds = [{"seed": i + 1, "team": t, "auto": i < 5} for i, t in enumerate(field)]
    def pg(a, b):
        return r4(phi((R.get(a, 0) - R.get(b, 0)) / SD[L]))
    pgames = [{"round": "First Round", "slot": k, "home": field[h], "away": field[a], "p_home": pg(field[h], field[a]), "winner": None, "gid": None}
              for k, (h, a) in enumerate([(4, 11), (5, 10), (6, 9), (7, 8)])]
    pgames += [{"round": "Quarterfinal", "slot": k, "home": field[k], "away": None, "p_home": None, "winner": None, "gid": None} for k in range(4)]
    pgames += [{"round": "Semifinal", "slot": k, "home": None, "away": None, "p_home": None, "winner": None, "gid": None} for k in range(2)]
    pgames += [{"round": "National Championship", "slot": 0, "home": None, "away": None, "p_home": None, "winner": None, "gid": None}]
    odds = {t: {"p_in": sim[t]["p_cfp"], "p_bye": sim[t]["p_bye"], "p_qf": sim[t]["p_round"]["qf"], "p_sf": sim[t]["p_round"]["sf"], "p_final": sim[t]["p_round"]["final"],
                "p_title": sim[t]["p_title"], "seed_dist": sim[t]["seed_dist"]} for t in ids if sim[t]["p_cfp"]}
    ctg = {}
    for c, info in confs.items():
        rows = sorted(info["teams"], key=lambda t: -(sim[t]["p_conf_game"] or 0))[:6]
        ctg[c] = [{"team": t, "p_appear": sim[t]["p_conf_game"], "p_win": sim[t]["p_conf"]} for t in rows]
    bowls = [g for g in games if g["stype"] == "bowl"]
    return {"ok": True, "season": S, "updated_at": NOW_S, "format": {"teams": 12, "auto_bids": 5, "byes": 0, "rule": "2025 rules assumed", "verified": S <= 2025},
            "actual": actual, "committee_proxy": proxy, "projected_bracket": {"seeds": seeds, "games": pgames}, "odds": odds, "conf_title_games": ctg,
            "bowls": {"eligible": {t: sim[t]["p_bowl"] for t in ids}, "games": [card(L, S, g, R, set(ids)) for g in bowls]},
            "proxy_fit": {"n_seasons": 11, "spearman": 0.91, "top12_overlap": 10.6, "features": ["wins", "losses", "sos", "rating", "wins_v_ranked", "conf_champ"], "weights": [1.0, -1.6, 0.4, 0.8, 0.5, 1.2]}}


REG_ORDER = {"mbb": None, "wbb": None}


def bracket_payload(L, S, st, games, ids, sim, R, rank, confs, rec):
    ng = [g for g in games if g["stype"] == "ncaa"]
    actual = None
    rounds = ["R64", "R32", "S16", "E8", "F4", "Final", "Champion"]
    if ng:
        regions = defaultdict(dict)
        ff = []
        for g in ng:
            if not g.get("region"):
                continue
            for side in ("home", "away"):
                sd = (g.get("seeds") or {}).get(side)
                if sd:
                    regions[g["region"]][g[side]] = sd
            if g["round"] == "First Four":
                ff.append({"region": g["region"], "seed": (g.get("seeds") or {}).get("home"), "teams": [g["home"], g["away"]], "gid": g["id"]})
        actual = {"regions": {r: [{"seed": s, "team": t} for t, s in sorted(v.items(), key=lambda x: x[1])] for r, v in regions.items()},
                  "games": [card(L, S, g, R, set(ids)) for g in ng], "first_four": ff}
    br = sorted(ids, key=lambda t: -(sim[t]["p_ncaa"] or 0))[:80]
    bracketology = [{"team": t, "seed_mean": sim[t]["seed_mean"], "seed_mode": int(max(sim[t]["seed_dist"].items(), key=lambda x: x[1])[0]) if sim[t]["seed_dist"] else None,
                     "p_ncaa": sim[t]["p_ncaa"], "p_auto": sim[t]["p_auto"], "p_at_large": sim[t]["p_at_large"], "conf": st["teams"][t].get("conference"),
                     "record": f"{rec[t]['w']}-{rec[t]['l']}", "rating_rank": rank[t]} for t in br]
    proj = sorted(br[:68], key=lambda t: (sim[t]["seed_mean"] or 99))
    names = ["East", "West", "South", "Midwest"] if L == "mbb" else ["Regional 1", "Regional 2", "Regional 3", "Regional 4"]
    pregions = {n: [] for n in names}
    for i, t in enumerate(proj[:64]):
        s = i // 4 + 1
        k = (i % 4) if (s % 2 == 1) else 3 - (i % 4)
        pregions[names[k]].append({"seed": s, "team": t, "p": sim[t]["p_ncaa"]})
    odds = {}
    if actual:
        seed_of, reg_of = {}, {}
        for r, rows in actual["regions"].items():
            for x in rows:
                seed_of[x["team"]] = x["seed"]; reg_of[x["team"]] = r
        # pre-tournament odds by seed strength (placeholder)
        for t in seed_of:
            s = seed_of[t]
            base = max(0.02, 1 - s / 17)
            pr = {}
            p = 1.0
            for k, rd in enumerate(rounds):
                if k == 0:
                    pr[rd] = 1.0
                    continue
                p *= base ** (0.6 + 0.12 * k) * (0.9 + 0.2 * (R.get(t, 0) > 10))
                pr[rd] = r4(min(1.0, p))
            odds[t] = {"p_round": pr, "seed": s, "region": reg_of[t]}
    else:
        for t in br[:68]:
            pr = sim[t]["p_round"]
            odds[t] = {"p_round": {"R64": sim[t]["p_ncaa"], "R32": pr["r32"], "S16": pr["s16"], "E8": pr["e8"], "F4": pr["f4"], "Final": pr["final"], "Champion": pr["title"]},
                       "seed": int(round(sim[t]["seed_mean"])) if sim[t]["seed_mean"] else None, "region": None}
    upsets = []
    pairs = [(1, 16), (8, 9), (5, 12), (4, 13), (6, 11), (3, 14), (7, 10), (2, 15)]
    regs = actual["regions"] if actual else {n: [{"seed": x["seed"], "team": x["team"]} for x in v] for n, v in pregions.items()}
    for rname, rows in regs.items():
        bys = defaultdict(list)
        for x in rows:
            bys[x["seed"]].append(x["team"])
        for a, b in pairs:
            if bys.get(a) and bys.get(b):
                fav, dog = bys[a][0], bys[b][0]
                m = R.get(fav, 0) - R.get(dog, 0)
                upsets.append({"round": "R64", "region": rname, "fav": fav, "dog": dog, "seed_fav": a, "seed_dog": b, "p_upset": r4(1 - phi(m / 11)), "market_p": None})
    ct = {}
    for c, info in confs.items():
        rows = sorted(info["teams"], key=lambda t: -R.get(t, 0))
        tot = sum(math.exp(R.get(t, 0) / 5) for t in rows) or 1
        ct[c] = {"teams": [{"team": t, "seed": i + 1, "p_win": r4(math.exp(R.get(t, 0) / 5) / tot)} for i, t in enumerate(rows)], "approximate": True,
                 "games": [card(L, S, g, R, set(ids)) for g in games if g["stype"] == "conf" and st["teams"].get(g["home"], {}).get("conference") == c]}
    return {"ok": True, "season": S, "updated_at": NOW_S, "field": 68, "format": {"field": 68, "at_large": 37, "first_four": True, "verified": S <= 2026},
            "actual": actual, "bracketology": bracketology,
            "projected": {"regions": pregions, "first_four": [[proj[64], proj[65]], [proj[66], proj[67]]] if len(proj) >= 68 else [], "last_in": proj[60:64], "first_out": [t for t in br[68:72]]},
            "rounds": rounds, "odds": odds, "upsets": upsets, "conf_tourneys": ct,
            "selection_fit": {"n_seasons": 22, "at_large_acc": 0.94, "seed_mae": 0.71, "features": ["rating", "sos", "wins_q1", "record", "conf_rank"]}}


# ───────────────────────────────────────────────────────────── players and teams
FB_METRICS = [("rating", "Rating", "Overall", "signed1", False, "Expected margin v an average FBS team, neutral field"),
              ("off", "Offense", "Overall", "1", False, "Points per game component"),
              ("def", "Defense", "Overall", "1", True, "Points allowed component (lower is better)"),
              ("epa_off", "EPA/play off", "Efficiency", "3", False, "Opponent-adjusted offensive EPA per play"),
              ("epa_def", "EPA/play def", "Efficiency", "3", True, "Opponent-adjusted defensive EPA per play allowed"),
              ("sr_off", "Success rate off", "Efficiency", "pct", False, "Share of plays that gain enough"),
              ("sos", "Schedule strength", "Schedule", "signed1", False, "Mean rating of opponents")]
BB_METRICS = [("rating", "Adj. margin", "Overall", "signed1", False, "Adjusted efficiency margin per 100 possessions"),
              ("off", "Adj. offense", "Overall", "1", False, "Adjusted points scored per 100"),
              ("def", "Adj. defense", "Overall", "1", True, "Adjusted points allowed per 100 (lower is better)"),
              ("tempo", "Tempo", "Style", "1", False, "Possessions per 40 minutes"),
              ("sos", "Schedule strength", "Schedule", "signed1", False, "Mean rating of opponents"),
              ("luck", "Luck", "Overall", "3", False, "Win% above expectation from margins")]


def metric(k, lab, grp, f, low, desc):
    return {"key": k, "label": lab, "group": grp, "fmt": f, "lower": low, "desc": desc}


def pct_rank(vals: dict, lower=False):
    ks = [k for k, v in vals.items() if v is not None]
    arr = sorted(vals[k] for k in ks)
    out = {}
    n = len(arr)
    for k in ks:
        i = np.searchsorted(arr, vals[k], side="right")
        p = 100 * i / n
        out[k] = round(100 - p if lower else p, 0)
    return out


def players_payloads(L, S, D, st, ps, teams, members, rank, ratings, sim, cards, prevR):
    fb = L == "cfb"
    # teams catalogue
    mets = FB_METRICS if fb else BB_METRICS
    tv = {t: {m[0]: ratings[t].get(m[0]) for m in mets} for t in members}
    pcts = {m[0]: pct_rank({t: tv[t][m[0]] for t in members}, m[4]) for m in mets}
    recs = defaultdict(lambda: [0, 0])
    for c in cards:
        if c["status"] == "post" and c["hs"] is not None:
            w = c["home"] if c["hs"] > c["as"] else c["away"]
            for t in (c["home"], c["away"]):
                recs[t][0 if t == w else 1] += 1
    dump(D / "teams.json", {"ok": True, "metrics": [metric(*m) for m in mets], "teams": {
        t: {"name": teams[t]["name"], "conference": teams[t]["conference"], "w": recs[t][0], "l": recs[t][1], "rating_rank": rank[t],
            "values": tv[t], "pct": {k: pcts[k].get(t) for k in pcts}} for t in members}})
    # players catalogue
    q = {pid: s for pid, s in ps.items() if s["team"] in members}
    if fb:
        pm = [("epa", "EPA", "Value", "1", False, "Expected points added (total)"), ("pass_yds", "Pass yds", "Passing", "int", False, ""),
              ("pass_td", "Pass TD", "Passing", "int", False, ""), ("rush_yds", "Rush yds", "Rushing", "int", False, ""),
              ("rec_yds", "Rec yds", "Receiving", "int", False, ""), ("tkl", "Tackles", "Defense", "int", False, ""), ("sacks", "Sacks", "Defense", "1", False, "")]
    else:
        pm = [("value", "Value", "Value", "2", False, "Value above replacement (season)"), ("pts", "PTS", "Scoring", "1", False, "Points per game"),
              ("reb", "REB", "Rebounding", "1", False, ""), ("ast", "AST", "Playmaking", "1", False, ""), ("ts", "TS%", "Scoring", "pct", False, "True shooting"),
              ("usg", "USG%", "Usage", "1", False, ""), ("stl", "STL", "Defense", "1", False, ""), ("blk", "BLK", "Defense", "1", False, "")]
    ppc = {m[0]: pct_rank({p: q[p].get(m[0]) for p in q}, m[4]) for m in pm}
    pos_n = defaultdict(int)
    for p in q:
        pos_n[q[p]["pos"]] += 1
    players = {}
    for p, s in q.items():
        info = st["players"].get(p) or {}
        players[p] = {"name": info.get("name") or p, "team": s["team"], "pos": s["pos"], "class": info.get("class"), "gp": s["gp"],
                      "qualified": s["gp"] >= (3 if fb else 8), "values": {m[0]: (round(s.get(m[0]), 3) if s.get(m[0]) is not None else None) for m in pm},
                      "pct": {m[0]: ppc[m[0]].get(p) for m in pm}, "pct_pos": {m[0]: ppc[m[0]].get(p) for m in pm}}
    POS_L = {"QB": "Quarterbacks", "RB": "Running backs", "WR": "Wide receivers", "TE": "Tight ends", "OL": "Offensive line", "DL": "Defensive line",
             "LB": "Linebackers", "DB": "Defensive backs", "CB": "Cornerbacks", "S": "Safeties", "K": "Kickers", "P": "Punters", "G": "Guards", "F": "Forwards", "C": "Centers"}
    dump(D / "players.json", {"ok": True, "metrics": [metric(*m) for m in pm], "positions": {k: {"label": POS_L.get(k, k), "n": v} for k, v in pos_n.items()},
                              "min_floor": {"gp": 3 if fb else 8}, "players": players})
    # value
    rows = sorted(q.items(), key=lambda x: -(x[1]["value"] or 0))
    vp = pct_rank({p: s["value"] for p, s in q.items()})

    def vrow(p, s):
        info = st["players"].get(p) or {}
        why = (f"{int(s.get('pass_yds', 0))} pass yds, {int(s.get('rush_yds', 0))} rush yds" if fb and s["pos"] == "QB" else
               (f"{int(s.get('rec_yds', 0) + s.get('rush_yds', 0))} scrimmage yds" if fb else f"{s['pts']} pts, {s['reb']} reb, {s['ast']} ast a game"))
        return {"id": p, "name": info.get("name") or p, "team": s["team"], "pos": s["pos"], "class": info.get("class"), "gp": s["gp"],
                "value": s["value"], "value_pg": round(s["value"] / max(1, s["gp"]), 3), "pctl": vp.get(p), "why": why}
    byp = defaultdict(list)
    for p, s in rows:
        if len(byp[s["pos"]]) < 10:
            byp[s["pos"]].append(vrow(p, s))
    dump(D / "value.json", {"ok": True, "currency": {"key": "value", "label": "EPA above replacement" if fb else "Value above replacement",
                                                     "desc": "Preview placeholder currency"}, "leaders": [vrow(p, s) for p, s in rows[:200]], "by_position": dict(byp)})
    # moves (inferred): compare with previous season's store
    try:
        prev = cstore.load(L, S - 1)
    except Exception:
        prev = {"players": {}}
    prev_team = {}
    for p, info in (prev.get("players") or {}).items():
        if info.get("teams"):
            prev_team[p] = info["teams"][-1]
    moves = []
    for p, s in q.items():
        pt = prev_team.get(p)
        if pt and pt != s["team"]:
            moves.append({"player": p, "name": (st["players"].get(p) or {}).get("name") or p, "pos": s["pos"], "from": pt, "to": s["team"],
                          "value_before": round(s["value"] * RNG.uniform(0.3, 1.2), 2), "value_after": s["value"], "class": (st["players"].get(p) or {}).get("class"),
                          "grade": RNG.choice(["A", "B", "B", "C", "C", "D"])})
    moves.sort(key=lambda m: -(m["value_after"] or 0))
    byt = defaultdict(lambda: {"in": [], "out": [], "net_value": 0.0})
    for m in moves:
        byt[m["to"]]["in"].append(m["player"]); byt[m["to"]]["net_value"] += m["value_after"] or 0
        byt[m["from"]]["out"].append(m["player"]); byt[m["from"]]["net_value"] -= m["value_before"] or 0
    dump(D / "moves.json", {"ok": True, "season": S, "note": "Inferred from box scores and rosters (same ESPN athlete id on a new team); not the official transfer portal.",
                            "moves": moves[:600], "by_team": {k: {"in": v["in"], "out": v["out"], "net_value": round(v["net_value"], 2)} for k, v in byt.items()},
                            "best": moves[:25], "summary": {"n": len(moves), "teams": len(byt)}})
    # fantasy
    if fb:
        fp = []
        for p, s in rows[:400]:
            if s["pos"] not in ("QB", "RB", "WR", "TE", "K"):
                continue
            pr = (s.get("pass_yds", 0) * 0.04 + s.get("pass_td", 0) * 4 + s.get("rush_yds", 0) * 0.1 + s.get("rush_td", 0) * 6 + s.get("rec", 0) + s.get("rec_yds", 0) * 0.1 + s.get("rec_td", 0) * 6) / max(1, s["gp"])
            fp.append({"id": p, "name": (st["players"].get(p) or {}).get("name") or p, "team": s["team"], "pos": s["pos"], "opp": None, "proj": round(pr, 1),
                       "proj_lo": round(pr * 0.6, 1), "proj_hi": round(pr * 1.4, 1)})
        fp.sort(key=lambda x: -x["proj"])
        for i, x in enumerate(fp):
            x["tier"] = 1 + i // 12
        rk = {f: sorted(fp, key=lambda x: -x["proj"])[:100] for f in ("ppr", "half", "standard")}
        fant = {"ok": True, "season": S, "scoring": {"ppr": {"rec": 1}, "half": {"rec": 0.5}, "standard": {"rec": 0}}, "period": "Week 9", "projections": fp,
                "rankings": rk, "start_sit": fp[10:20], "sleepers": fp[40:50], "backtest": {"n": 5210, "mae": 5.9, "mae_naive": 6.6, "rank_corr": 0.58, "rank_corr_naive": 0.52}}
    else:
        fp = [{"id": p, "name": (st["players"].get(p) or {}).get("name") or p, "team": s["team"], "pos": s["pos"], "opp": None,
               "proj": round(s["pts"] + 1.2 * s["reb"] + 1.5 * s["ast"] + 3 * (s["stl"] + s["blk"]) - s["tov"], 1)} for p, s in rows[:300]]
        for i, x in enumerate(fp):
            x["proj_lo"] = round(x["proj"] * 0.7, 1); x["proj_hi"] = round(x["proj"] * 1.3, 1); x["tier"] = 1 + i // 15
        fant = {"ok": True, "season": S, "scoring": {"points": {"pts": 1, "reb": 1.2, "ast": 1.5, "stl": 3, "blk": 3, "tov": -1}}, "period": "next 7 days", "projections": fp,
                "rankings": {"points": fp[:100], "9cat": fp[:100]}, "start_sit": fp[10:20], "sleepers": fp[50:60], "backtest": {"n": 9800, "mae": 6.1, "mae_naive": 6.9, "rank_corr": 0.61, "rank_corr_naive": 0.55}}
    dump(D / "fantasy.json", fant)
    # lab
    lf = ["id", "name", "team", "conference", "w", "l"] + [m[0] for m in mets]
    dump(D / "lab_teams.json", {"ok": True, "kind": "team", "fields": lf, "metrics": [metric(*m) for m in mets],
                                "rows": [[t, teams[t]["name"], t, teams[t]["conference"], recs[t][0], recs[t][1]] + [tv[t][m[0]] for m in mets] for t in members]})
    pf = ["id", "name", "team", "pos", "gp"] + [m[0] for m in pm]
    dump(D / "lab_players.json", {"ok": True, "kind": "player", "fields": pf, "metrics": [metric(*m) for m in pm],
                                  "rows": [[p, players[p]["name"], s["team"], s["pos"], s["gp"]] + [players[p]["values"][m[0]] for m in pm] for p, s in q.items() if s["gp"] >= 2]})
    # team pages
    bypos = defaultdict(lambda: defaultdict(float))
    for p, s in q.items():
        bypos[s["team"]][s["pos"]] += s["value"] or 0
    units_list = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB"] if fb else ["G", "F", "C"]
    unit_vals = {u: pct_rank({t: bypos[t].get(u, 0) for t in members}) for u in units_list}
    for t in members:
        roster = []
        for p in (st["rosters"].get(t) or [])[:120]:
            s = q.get(p)
            info = st["players"].get(p) or {}
            row = {"id": p, "name": info.get("name") or p, "pos": (s or {}).get("pos") or info.get("pos"), "class": info.get("class"),
                   "gp": (s or {}).get("gp", 0), "value": (s or {}).get("value"), "value_pg": round((s or {}).get("value", 0) / max(1, (s or {}).get("gp", 1)), 3) if s else None}
            if s and not fb:
                row.update({"pts": s["pts"], "reb": s["reb"], "ast": s["ast"], "min": s["min"]})
            if s and fb:
                row.update({"pass_yds": s.get("pass_yds"), "rush_yds": s.get("rush_yds"), "rec_yds": s.get("rec_yds"), "tkl": s.get("tkl")})
            roster.append(row)
        if not roster:
            roster = [{"id": p, "name": (st["players"].get(p) or {}).get("name") or p, "pos": s["pos"], "class": None, "gp": s["gp"], "value": s["value"], "value_pg": None}
                      for p, s in q.items() if s["team"] == t]
        roster.sort(key=lambda r: -(r.get("value") or -99))
        units = []
        for u in units_list:
            pc = unit_vals[u].get(t, 50)
            g = "A" if pc >= 85 else "B" if pc >= 65 else "C" if pc >= 35 else "D" if pc >= 15 else "F"
            units.append({"unit": u, "grade": g, "pctl": pc, "value": round(bypos[t].get(u, 0), 2), "evidence": f"{u} value {bypos[t].get(u, 0):.1f} ({int(pc)}th percentile)"})
        us = sorted(units, key=lambda x: -x["pctl"])
        my_cards = [c for c in cards if t in (c["home"], c["away"])]
        tm_moves = byt.get(t, {"in": [], "out": []})
        mv = {m["player"]: m for m in moves}
        sugg = []
        for u in us[-2:]:
            cands = [(p, s) for p, s in rows if s["pos"] == u["unit"] and s["team"] != t][:5]
            sugg.append({"need": u["unit"], "candidates": [{"id": p, "name": (st["players"].get(p) or {}).get("name") or p, "team": s["team"], "value": s["value"],
                                                            "gain": round((s["value"] or 0) - (bypos[t].get(u["unit"], 0) / 3), 2)} for p, s in cands]})
        stats = {m[0]: {"v": tv[t][m[0]], "pct": pcts[m[0]].get(t), "rank": None} for m in mets}
        rh = [[w, None, rank[t] + RNG.randint(-4, 4)] for w in range(1, 9)]
        dump(D / "teams" / f"{t}.json", {"ok": True, "id": t, "level": L, "season": S, "team": teams[t], "record": {"w": recs[t][0], "l": recs[t][1]},
                                          "rating": ratings[t], "rating_path": None, "rank_history": rh, "schedule": my_cards, "stats": stats, "roster": roster,
                                          "units": units, "strengths": us[:3], "needs": us[-3:][::-1],
                                          "moves": {"in": [mv[p] for p in tm_moves["in"] if p in mv], "out": [mv[p] for p in tm_moves["out"] if p in mv]},
                                          "odds": sim.get(t), "suggestions": sugg})
    # careers (top players only in the preview)
    for p, s in rows[:400]:
        info = st["players"].get(p) or {}
        seasons = [dict({"season": S, "team": s["team"], "gp": s["gp"], "pos": s["pos"], "value": s["value"], "value_pg": round(s["value"] / max(1, s["gp"]), 3), "pctl": vp.get(p)},
                        **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items() if k not in ("team", "gp", "value", "pos")})]
        log = []
        for c in cards:
            if c["status"] != "post" or s["team"] not in (c["home"], c["away"]):
                continue
            home = c["home"] == s["team"]
            my, op = (c["hs"], c["as"]) if home else (c["as"], c["hs"])
            log.append({"game": c["id"], "date": c["date"], "opp": c["away"] if home else c["home"], "home": home, "res": ("W " if my > op else "L ") + f"{my}-{op}",
                        "value": round((s["value"] or 0) / max(1, s["gp"]) + RNG.gauss(0, 1.5), 2)})
        car = {"ok": True, "id": p, "name": info.get("name") or p, "pos": s["pos"], "level": L, "updated_at": NOW_S, "class": info.get("class"),
               "height_in": info.get("height_in"), "weight_lb": info.get("weight_lb"), "hometown": info.get("hometown"), "seasons": seasons,
               "current": {"season": S, "team": s["team"], "log": log[-14:], "value": vrow(p, s), "fantasy": None},
               "moves": [m for m in moves if m["player"] == p], "similar": [{"id": x, "name": (st["players"].get(x) or {}).get("name") or x, "season": S, "distance": round(RNG.random(), 2)} for x, _ in rows[:400:57] if x != p][:5]}
        prevf = D.parent / "players" / f"{p}.json"
        if prevf.exists():
            old = json.loads(prevf.read_text(encoding="utf-8"))
            car["seasons"] = [x for x in old.get("seasons", []) if x["season"] != S] + car["seasons"]
        dump(prevf, car)


def game_pages(L, S, D, st, games, cards, teams, ps):
    fb = L == "cfb"
    cmap = {c["id"]: c for c in cards}
    pick = [g for g in games if g["status"] == "post" and g["id"] in cmap and g.get("box")]
    post = [g for g in pick if g["stype"] not in ("reg", "conf")]
    reg = [g for g in pick if g["stype"] in ("reg", "conf")]
    chosen = post + reg[-60:]
    plays = None
    if fb:
        try:
            plays = cstore.load_plays(S)
        except Exception:
            plays = None
    for g in chosen:
        c = cmap[g["id"]]
        page = dict(c)
        page.update({"ok": True, "level": L, "teams": {t: teams.get(t) or {"name": t} for t in (g["home"], g["away"])}, "venue": g.get("venue"), "attendance": g.get("attendance"),
                     "pregame": {"model": {"p_home": c["model"]["p_home"], "margin": c["model"]["margin"], "sd": SD[L], "total": c["model"]["total"],
                                           "spread_fair": r2(-c["model"]["margin"]), "detail": {}}, "market": c["market"],
                                 "espn_predictor": (g.get("predictor") or {}).get("home"), "elo_p_home": r4(min(0.98, max(0.02, c["model"]["p_home"] + RNG.gauss(0, 0.04))))},
                     "team_stats": g.get("team_stats") or {}, "flow": None, "wp": None, "drives": None, "epa": None, "plays": None, "leaders": {}})
        names = lambda pid: (st["players"].get(pid) or {}).get("name") or pid
        if fb:
            box = {}
            for tid, b in g["box"].items():
                cats = {}
                for cat, blk in (b.get("players") or {}).items():
                    cats[cat] = {"cols": blk["cols"], "rows": [[r[0], names(r[0])] + r[1:] for r in blk["rows"]]}
                box[tid] = {"team": b.get("team"), "players": cats}
            page["box"] = box
            pg = (plays or {}).get("games", {}).get(g["id"]) if plays else None
            if pg:
                PC = cstore.PLAY_COLS
                ix = {k: i for i, k in enumerate(PC)}
                wp = []
                lev = []
                last = None
                for r in pg["plays"]:
                    t = (r[ix["period"]] - 1) * 900 + (900 - (r[ix["clock_s"]] or 0))
                    t = min(t, 3600 + 300 * max(0, r[ix["period"]] - 4))
                    w = r[ix["wp_home"]]
                    if w is not None:
                        wp.append([round(t / 60, 2), w])
                        if last is not None:
                            lev.append((abs(w - last), round(t / 60, 2), r))
                        last = w
                page["wp"] = {"model": wp[::2], "espn": wp}
                page["flow"] = [[round(((r[ix["period"]] - 1) * 900 + 900 - (r[ix["clock_s"]] or 0)) / 60, 2), (r[ix["home_score"]] or 0) - (r[ix["away_score"]] or 0)] for r in pg["plays"]]
                page["drives"] = [{"team": d[1], "period": d[2], "start": d[4], "plays": d[5], "yards": d[6], "result": d[7], "epa": round(RNG.gauss(0.3 if d[8] else -0.6, 0.8), 2)} for d in pg["drives"]]
                lev.sort(key=lambda x: -x[0])
                page["plays"] = [{"t": x[1], "period": x[2][ix["period"]], "clock": f"{int((x[2][ix['clock_s']] or 0) // 60)}:{int((x[2][ix['clock_s']] or 0) % 60):02d}",
                                  "team": x[2][ix["offense"]], "text": x[2][ix["text"]], "wpa": round(x[0] * (1 if True else -1), 3)} for x in lev[:8]]
                page["epa"] = {t: {"epa_play": round(RNG.gauss(0.05, 0.15), 3), "sr": round(RNG.uniform(0.35, 0.52), 3), "pass_epa": round(RNG.gauss(0.08, 0.2), 3),
                                   "rush_epa": round(RNG.gauss(0, 0.15), 3), "explosive": round(RNG.uniform(0.06, 0.14), 3)} for t in (g["home"], g["away"])}
            for tid, b in box.items():
                ld = []
                for cat, lab in (("passing", "pass"), ("rushing", "rush"), ("receiving", "rec")):
                    blk = b["players"].get(cat)
                    if blk and blk["rows"]:
                        r = blk["rows"][0]
                        ld.append({"id": r[0], "name": r[1], "line": f"{lab} " + " · ".join(f"{c}: {v}" for c, v in list(zip(blk['cols'], r[2:]))[:3])})
                page["leaders"][tid] = ld
        else:
            box = {}
            for tid, b in g["box"].items():
                rows = []
                for r in b.get("players") or []:
                    d = dict(zip(cstore.BOX_COLS, r))
                    d["id"] = d.pop("player_id"); d["name"] = names(d["id"]); d["min"] = round(d.pop("sec") / 60, 0); d["reb"] = d["oreb"] + d["dreb"]
                    rows.append(d)
                box[tid] = {"players": rows, "dnp": [[x[0], names(x[0]), x[1]] for x in b.get("dnp") or []], "team": b.get("team")}
                page["leaders"][tid] = [{"id": x["id"], "name": x["name"], "line": f"{x['pts']} pts · {x['reb']} reb · {x['ast']} ast"} for x in sorted(rows, key=lambda x: -x["pts"])[:3]]
            page["box"] = box
            pb = cstore.load_pbp(L, S, g["id"])
            if pb:
                PI = {k: i for i, k in enumerate(cstore.PBP_COLS)}
                flow, wp = [], []
                hl = 20 * 60 if L == "mbb" else 10 * 60
                for r in pb["plays"]:
                    per = r[PI["period"]]
                    reg_p = 2 if L == "mbb" else 4
                    base = (per - 1) * hl if per <= reg_p else reg_p * hl + (per - reg_p - 1) * 300
                    plen = hl if per <= reg_p else 300
                    t = round((base + plen - (r[PI["clock_s"]] or 0)) / 60, 2)
                    flow.append([t, (r[PI["home_score"]] or 0) - (r[PI["away_score"]] or 0)])
                    w = (pb.get("wp") or {}).get(str(r[PI["seq"]]))
                    if w is not None:
                        wp.append([t, w])
                page["flow"] = flow
                page["wp"] = {"model": wp[::3], "espn": wp} if wp else None
        dump(D / "games" / f"{g['id']}.json", page)


def level_files(L, out: Path, seasons_built):
    D = out / L
    rng = random.Random(3)
    per = []
    for s in range(2014 if L == "cfb" else 2015, (2026 if L == "cfb" else 2027)):
        n = 700 if L == "cfb" else 5200
        per.append({"season": s, "n": n, "n_close": int(n * 0.9), "model": {"brier": round(rng.uniform(0.165, 0.185), 4), "logloss": round(rng.uniform(0.49, 0.53), 4), "acc": round(rng.uniform(0.72, 0.77), 3),
                    "mae": round(rng.uniform(12, 13.5) if L == "cfb" else rng.uniform(8.5, 9.5), 2)}, "close": {"brier": round(rng.uniform(0.16, 0.18), 4), "logloss": round(rng.uniform(0.48, 0.52), 4),
                    "acc": round(rng.uniform(0.73, 0.78), 3), "mae": round(rng.uniform(11.8, 13.2) if L == "cfb" else rng.uniform(8.3, 9.3), 2)}, "ats_hit": round(rng.uniform(0.48, 0.53), 3)})
    cal = [{"lo": i / 10, "hi": (i + 1) / 10, "n": 400 + rng.randint(0, 200), "p_mean": round(i / 10 + 0.05, 3), "y_mean": round(min(1, max(0, i / 10 + 0.05 + rng.gauss(0, 0.02))), 3)} for i in range(10)]
    by = [{"lo": a, "hi": b, "n": rng.randint(200, 900), "mae_model": round(rng.uniform(10, 14), 2), "mae_close": round(rng.uniform(10, 14), 2), "ats_hit": round(rng.uniform(0.47, 0.54), 3)}
          for a, b in ((0, 3), (3, 7), (7, 14), (14, 21), (21, 60))]
    dump(D / "calibration.json", {"ok": True, "level": L, "updated_at": NOW_S, "seasons": [p["season"] for p in per], "n_games": sum(p["n"] for p in per),
                                  "summary": {"model": {"brier": 0.176, "logloss": 0.512, "acc": 0.745, "mae": 12.8 if L == "cfb" else 8.9, "rmse": 16.2 if L == "cfb" else 11.4, "n": 8200},
                                              "elo": {"brier": 0.182, "logloss": 0.528, "acc": 0.735, "mae": 13.3, "rmse": 16.9, "n": 8200},
                                              "close": {"brier": 0.171, "logloss": 0.499, "acc": 0.752, "mae": 12.5 if L == "cfb" else 8.7, "rmse": 15.8, "n": 7400},
                                              "vs_close": {"n": 7400, "mae_model": 12.8, "mae_close": 12.5, "ats_hit": 0.507, "ats_n": 7100, "ats_se": 0.006, "total_mae_model": 11.1, "total_mae_close": 10.7, "total_n": 7000},
                                              "espn_predictor": {"brier": 0.179, "logloss": 0.521, "acc": 0.74, "n": 3100}},
                                  "per_season": per, "calibration": cal, "by_spread": by, "sim": {"cfp_field_hit": 0.86} if L == "cfb" else {"seed_mae": 0.8, "title_brier": 0.012},
                                  "notes": ["Preview fixture: placeholder numbers, not the backtest."]})
    champs = []
    for S in range(2014, 2026):
        champs.append({"season": S if L == "cfb" else S + 1, "team": rng.choice(list(seasons_built[max(seasons_built)]["teams"].keys())[:30]), "runner_up": None, "score": "35-28"})
    last = seasons_built[max(seasons_built)]
    dump(D / "history.json", {"ok": True, "level": L, "champions": champs, "conference_champions": {}, "first_season": 2001 if L == "cfb" else 2002,
                              "best_teams": [{"season": 2019, "team": t, "rating": r2(30 - i), "record": "13-1"} for i, t in enumerate(list(last["ratings"].keys())[:25])]})
    cur = max(seasons_built)
    s = seasons_built[cur]
    sim = s["sim"]["teams"]
    top = sorted(sim, key=lambda t: -(sim[t].get("p_title") or 0))[:16]
    fut = {"champion": {"probs": {t: r4(min(0.99, (sim[t]["p_title"] or 0) * rng.uniform(0.7, 1.3))) for t in top}, "sources": ["kalshi", "polymarket"], "by_source": {}, "available": True, "implied_total": 1.04}}
    games = {}
    sched = json.loads((out / L / str(cur) / "schedule.json").read_text(encoding="utf-8"))["games"]
    for c in sched:
        if c["status"] == "pre" and c["market"]:
            games[c["id"]] = {"home": c["home"], "away": c["away"], "date": c["date"], "model": c["model"], "market": c["market"], "edge": r4(c["model"]["p_home"] - c["market"]["p_home"])}
    dump(D / "markets.json", {"ok": True, "level": L, "season": cur, "updated_at": NOW_S, "fetched": True, "futures": fut,
                              "model": {"champion": {t: sim[t]["p_title"] for t in top}, "conference": {}, ("playoff" if L == "cfb" else "ncaa"): {t: sim[t].get("p_cfp", sim[t].get("p_ncaa")) for t in top}},
                              "games": games})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--levels", default="cfb,mbb,wbb")
    a = ap.parse_args(argv)
    out = Path(a.out)
    for L in a.levels.split(","):
        built = {}
        prevR = None
        for S in SEASONS[L]:
            print(L, S, flush=True)
            R, season, ps, cards = build_season(L, S, out, prevR)
            prevR = R
            built[S] = season
        level_files(L, out, built)


if __name__ == "__main__":
    main()
