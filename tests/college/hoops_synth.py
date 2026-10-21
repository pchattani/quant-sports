"""Synthetic college basketball stores for the hoops tests (no network): conferences, a regular season from known
team strengths, conference tournament finals, an NCAA tournament (68 or 64 teams, seeds, regions, First Four) and
box scores, in the store shape of oddsmarkets/college/CONTRACT.md 1.2."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from oddsmarkets.college import store as ST

REGIONS = ["East", "West", "South", "Midwest"]
SLOT = [1, 16, 8, 9, 5, 12, 4, 13, 6, 11, 3, 14, 7, 10, 2, 15]


def iso(d: date, hour: int = 23) -> str:
    return datetime(d.year, d.month, d.day, hour, 0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _score(rng, net_h, net_a, neutral, L=104.0, pace=68.0):
    poss = pace + rng.normal(0, 3)
    h = 0.0 if neutral else 3.5
    eh = L + (net_h - net_a) / 2 + h / 2
    ea = L - (net_h - net_a) / 2 - h / 2
    hs = int(round(poss * eh / 100 + rng.normal(0, 8)))
    as_ = int(round(poss * ea / 100 + rng.normal(0, 8)))
    if hs == as_:
        hs += 1 if rng.random() < 0.5 else -1
        if hs == as_:
            hs += 2
    return max(hs, 30), max(as_, 30), poss


def _stats(rng, pts, poss):
    fga = int(round(poss * 0.88))
    fta = int(round(poss * 0.3))
    ftm = int(round(fta * 0.7))
    tpa = int(round(fga * 0.38))
    rest = max(pts - ftm, 0)
    tpm = min(tpa, int(round(rest * 0.3 / 3)))
    fgm = min(fga, tpm + max(0, (rest - 3 * tpm) // 2))
    reb = int(round(36 + rng.normal(0, 3)))
    return {"fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa, "ftm": ftm, "fta": fta, "reb": reb, "ast": int(fgm * 0.55), "pts": pts}


def _box(rng, tid, pids, ts, poss):
    n = len(pids)
    mins = np.array([34, 32, 30, 28, 26, 20, 18, 12][:n], float)
    mins = mins / mins.sum() * 200
    share = rng.dirichlet(np.ones(n) * 3) * 0.3 + mins / mins.sum() * 0.7
    rows = []
    tot = {k: 0 for k in ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf")}
    pts_left = ts["pts"]
    for k, p in enumerate(pids):
        fga = int(round(ts["fga"] * share[k]))
        fgm = int(round(ts["fgm"] * share[k]))
        tpa = int(round(ts["tpa"] * share[k]))
        tpm = min(tpa, int(round(ts["tpm"] * share[k])))
        fta = int(round(ts["fta"] * share[k]))
        ftm = min(fta, int(round(ts["ftm"] * share[k])))
        pts = 2 * (fgm - tpm) + 3 * tpm + ftm
        oreb, dreb = int(rng.poisson(1.0 * share[k] * 8)), int(rng.poisson(3.0 * share[k] * 8))
        ast, stl, blk = int(rng.poisson(share[k] * 12)), int(rng.poisson(share[k] * 6)), int(rng.poisson(share[k] * 3))
        tov, pf = int(rng.poisson(share[k] * 11)), int(rng.poisson(2))
        row = [p, 1 if k < 5 else 0, int(mins[k] * 60), pts, fgm, fga, tpm, tpa, ftm, fta, oreb, dreb, ast, stl, blk, tov, pf]
        rows.append(row)
        for key, v in zip(("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf"),
                          (fgm, fga, tpm, tpa, ftm, fta, oreb, dreb, ast, stl, blk, tov, pf)):
            tot[key] += v
    # make the box add up to the score (data.box_ok): the first player's free throws / field goals take the rounding
    d = ts["pts"] - (2 * tot["fgm"] + tot["tpm"] + tot["ftm"])
    r0 = rows[0]
    if r0[8] + d >= 0:
        r0[8] += d
        r0[9] = max(r0[9], r0[8])
        tot["ftm"] += d
        tot["fta"] = sum(r[9] for r in rows)
    else:
        need = -(r0[8] + d)                          # points still to remove after zeroing the free throws
        tot["ftm"] -= r0[8]
        r0[8] = 0
        k2 = (need + 1) // 2
        r0[4] -= k2
        r0[5] = max(r0[5], r0[4])
        tot["fgm"] -= k2
        extra = 2 * k2 - need                        # removed one point too many: give it back as a free throw
        r0[8] += extra
        r0[9] = max(r0[9], r0[8])
        tot["ftm"] += extra
        tot["fga"] = sum(r[5] for r in rows)
        tot["fta"] = sum(r[9] for r in rows)
    r0[3] = 2 * (r0[4] - r0[6]) + 3 * r0[6] + r0[8]
    tot["tov"] = max(tot["tov"], 1)
    team = dict(tot)
    team.update({"team_tov": 0, "pts_paint": 0, "pts_fastbreak": 0, "pts_off_tov": 0, "largest_lead": 0})
    return {"players": rows, "dnp": [], "team": team}


def make_season(level: str, season: int, strengths: dict[str, float], conf_of: dict[str, str], seed: int = 0,
                tournament: bool = True, box: bool = True, field: int = 68, played: bool = True,
                rosters: dict[str, list[str]] | None = None) -> dict:
    rng = np.random.default_rng(seed + season)
    st = ST.new_store(level, season)
    confs = sorted(set(conf_of.values()))
    st["conferences"] = {c: {"name": f"Conf {c}", "short": f"C{c}", "abbr": f"c{c}", "d1": True, "divisions": {}} for c in confs}
    members = sorted(strengths)
    for t in members:
        st["teams"][t] = {"name": f"Team {t}", "short": f"T{t}", "abbr": f"T{t}", "location": f"Loc {t}", "nickname": "X",
                          "colour": "#123456", "alt_colour": "#654321", "conference": conf_of[t], "member": True, "division": None,
                          "venue": None}
    for t in ("9001", "9002"):
        st["teams"][t] = {"name": f"NonD1 {t}", "short": f"N{t}", "abbr": f"N{t}", "location": "", "nickname": "", "colour": None,
                          "alt_colour": None, "conference": None, "member": False, "division": None, "venue": None}
    roster = rosters or {t: [f"{t}{k:02d}" for k in range(8)] for t in members}
    for t, ps in roster.items():
        for k, p in enumerate(ps):
            st["players"][p] = {"name": f"Player {p}", "short": f"P{p}", "pos": ["PG", "SG", "SF", "PF", "C", "G", "F", "C"][k % 8],
                                "jersey": str(k), "class": "SO", "height_in": None, "weight_lb": None, "hometown": None, "teams": [t]}
    st["rosters"] = {t: list(ps) for t, ps in roster.items()}
    d0 = date(season - 1, 11, 8)
    gid = [season * 100000]

    def add(h, a, d, stype="reg", neutral=False, round_=None, region=None, seeds=None, status="post"):
        gid[0] += 1
        g = {"id": str(gid[0]), "date": iso(d), "status": status, "stype": stype, "round": round_, "region": region,
             "note": None, "week": None, "neutral": neutral, "conf_game": conf_of.get(h) is not None and conf_of.get(h) == conf_of.get(a) and stype == "reg",
             "home": h, "away": a, "hs": None, "as": None, "periods": 2, "line": {}, "ranks": {"home": None, "away": None},
             "seeds": seeds, "team_stats": {}, "box": {}, "odds": None, "injuries": {}, "predictor": None,
             "venue": {"name": "Neutral Arena" if neutral else f"Arena {h}", "city": "X", "state": "Y"}, "attendance": 1000,
             "has_pbp": False, "summary": bool(box)}
        if status == "post":
            sh = strengths.get(h, -25.0)
            sa = strengths.get(a, -25.0)
            hs, as_, poss = _score(rng, sh, sa, neutral)
            g["hs"], g["as"] = hs, as_
            tsh, tsa = _stats(rng, hs, poss), _stats(rng, as_, poss)
            g["team_stats"] = {h: tsh, a: tsa}
            if box and h in roster and a in roster:
                g["box"] = {h: _box(rng, h, roster[h], tsh, poss), a: _box(rng, a, roster[a], tsa, poss)}
            spread = -round(((sh - sa) * 0.68 + (0 if neutral else 3.5)) * 2) / 2
            g["odds"] = {"provider": "Test", "spread_home": spread, "total": 140.5, "ml_home": -150 if spread < 0 else 130,
                         "ml_away": 130 if spread < 0 else -150, "open_spread_home": spread, "open_total": 140.5, "n_books": 1,
                         "source": "core", "has_close_block": True}
        st["games"][g["id"]] = g
        return g

    status = "post" if played else "pre"
    # conference round robin + non-conference
    by_conf = {}
    for t in members:
        by_conf.setdefault(conf_of[t], []).append(t)
    day = 0
    for c, ts in by_conf.items():
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                h, a = (ts[i], ts[j]) if rng.random() < 0.5 else (ts[j], ts[i])
                add(h, a, d0 + timedelta(days=50 + int(rng.integers(0, 60))), status=status)
    for t in members:
        for k in range(10):
            o = members[int(rng.integers(0, len(members)))]
            if o == t or conf_of[o] == conf_of[t]:
                continue
            add(t, o, d0 + timedelta(days=int(rng.integers(0, 45))), neutral=k == 0, status=status)
        add(t, "9001", d0 + timedelta(days=int(rng.integers(0, 30))), status=status)
    if not played:
        return st
    # conference tournament finals (top two by strength, neutral)
    autos = {}
    for c, ts in by_conf.items():
        a, b = sorted(ts, key=lambda t: -strengths[t])[:2]
        g = add(a, b, date(season, 3, 8), stype="conf", neutral=True)
        autos[c] = a if g["hs"] > g["as"] else b
    if not tournament:
        return st
    # field: autos + best at-large, seeded by strength (S-curve), snake into regions
    at = [t for t in sorted(members, key=lambda t: -strengths[t]) if t not in autos.values()]
    n_at = field - len(autos)
    fld = list(autos.values()) + at[:n_at]
    ranked = sorted(fld, key=lambda t: -strengths[t])
    n_ff = field - 64
    ff_at = [t for t in at[:n_at]][-2 * (n_ff // 2):] if n_ff >= 2 else []
    ff_auto = sorted(autos.values(), key=lambda t: strengths[t])[:2 * (n_ff - n_ff // 2)] if n_ff else []
    pair = {}
    for grp in (ff_at, ff_auto):
        grp = sorted(grp, key=lambda t: -strengths[t])
        for k in range(0, len(grp), 2):
            pair[grp[k]] = grp[k:k + 2]
            pair[grp[k + 1]] = grp[k:k + 2]
    entries, used = [], set()
    for t in ranked:
        if t in used:
            continue
        e = pair.get(t, [t])
        entries.append(e)
        used.update(e)
    regions = [dict() for _ in range(4)]
    for k, e in enumerate(entries[:64]):
        line, j = divmod(k, 4)
        r = j if line % 2 == 0 else 3 - j
        regions[r][line + 1] = e
    order = [0, 3, 1, 2]
    ff_day = date(season, 3, 17)
    for r in order:
        for sd, e in regions[r].items():
            if len(e) == 2:
                g = add(e[0], e[1], ff_day, stype="ncaa", neutral=True, round_="First Four", region=REGIONS[r],
                        seeds={"home": sd, "away": sd})
                regions[r][sd] = [e[0] if g["hs"] > g["as"] else e[1]]
    cur = []
    for r in order:
        for sd in SLOT:
            cur.append((regions[r][sd][0], sd, REGIONS[r]))
    names = ["Round of 64", "Round of 32", "Sweet 16", "Elite 8", "Final Four", "National Championship"]
    for rd in range(6):
        nxt = []
        d = date(season, 3, 19) + timedelta(days=3 * rd)
        for k in range(0, len(cur), 2):
            (a, sa, ra), (b, sb, rb) = cur[k], cur[k + 1]
            g = add(a, b, d, stype="ncaa", neutral=True, round_=names[rd], region=ra if rd < 4 else None,
                    seeds={"home": sa, "away": sb})
            nxt.append(cur[k] if g["hs"] > g["as"] else cur[k + 1])
        cur = nxt
    return st


def make_level(level: str = "mbb", seasons=(2025, 2026), n_conf: int = 8, per_conf: int = 10, seed: int = 1,
               current: int | None = None) -> dict:
    """Writes stores for `seasons` (+ `current` as an unplayed schedule) under the CAMPUS_STORES root; returns
    {"strengths", "conf_of"}."""
    rng = np.random.default_rng(seed)
    conf_of, strengths = {}, {}
    for c in range(n_conf):
        base = rng.normal(0, 8)
        for k in range(per_conf):
            t = str(100 + c * per_conf + k)
            conf_of[t] = str(c + 1)
            strengths[t] = float(base + rng.normal(0, 8))
    for s in seasons:
        st = make_season(level, s, strengths, conf_of, seed=seed)
        ST.save(st)
        for t in strengths:
            strengths[t] = 0.7 * strengths[t] + rng.normal(0, 4)
    if current:
        st = make_season(level, current, strengths, conf_of, seed=seed, played=False)
        ST.save(st)
    return {"strengths": strengths, "conf_of": conf_of}
