"""
Team profiles and player tables for The Quant Scrum (build.py writes them into payloads).

Team profile: per-match averages over the last two years of the TEAM_METRICS, opponent-adjusted (a team's average
minus how far its opponents' average conceded differs from the field's), with percentiles among the teams with six
or more matches in the window. Strengths and weaknesses are the best and worst three percentiles (style metrics,
which say how a side plays rather than how well, are left out of those).

Player tables: every appearance with its minutes (players.py), positions, per-80 rates shrunk toward the position,
Scrum value per 80 (the value model's weights, above the position's replacement level), and percentiles within the
position group for each calendar year and for the current window (the last two years).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from . import players as PL

# (id, label, direction, group, how): how = ("for", stat) the team's own, ("against", stat) the opponent's,
# ("ratio", a, b) a / (a + b), ("share", a, b) a / b, ("sum", a, b) a + b
TEAM_METRICS = [
    ("pf", "Points scored", "higher", "Attack", ("for", "pts")),
    ("tf", "Tries scored", "higher", "Attack", ("for", "tries")),
    ("metres", "Metres carried", "higher", "Attack", ("for", "metres")),
    ("gainline", "Carries over the gain line", "higher", "Attack", ("ratio", "gainline", "no_gainline")),
    ("breaks", "Clean breaks", "higher", "Attack", ("for", "breaks")),
    ("beaten", "Defenders beaten", "higher", "Attack", ("for", "beaten")),
    ("offloads", "Offloads", "higher", "Attack", ("for", "offloads")),
    ("pa", "Points conceded", "lower", "Defence", ("against", "pts")),
    ("ta", "Tries conceded", "lower", "Defence", ("against", "tries")),
    ("tackle_pct", "Tackle success", "higher", "Defence", ("ratio", "tackles", "missed")),
    ("metres_a", "Metres conceded", "lower", "Defence", ("against", "metres")),
    ("to_won", "Turnovers won", "higher", "Breakdown", ("for", "to_won")),
    ("ruck_pct", "Ruck retention", "higher", "Breakdown", ("share", "rucks_won", "rucks")),
    ("pens_ruck", "Breakdown penalties", "lower", "Breakdown", ("for", "pens_ruck")),
    ("scrum_pct", "Scrums won", "higher", "Set piece", ("share", "scrums_won", "scrums")),
    ("lineout_pct", "Lineouts won", "higher", "Set piece", ("share", "lineouts_won", "lineouts")),
    ("steals", "Lineout steals", "higher", "Set piece", ("for", "lineout_steals")),
    ("maul_m", "Maul metres", "higher", "Set piece", ("for", "maul_m")),
    ("scrum_pens", "Scrum penalties won", "higher", "Set piece", ("for", "scrum_pens_won")),
    ("pens", "Penalties conceded", "lower", "Discipline", ("for", "pens")),
    ("cards", "Cards", "lower", "Discipline", ("sum", "yc", "rc")),
    ("to_conc", "Turnovers conceded", "lower", "Discipline", ("for", "to_conc")),
    ("pens_offside", "Offside penalties", "lower", "Discipline", ("for", "pens_offside")),
    ("kick_m", "Kicking metres", "higher", "Kicking", ("for", "kick_m")),
    ("kick_pct", "Goal-kicking success", "higher", "Kicking", ("for", "kick_pct")),
    ("kick_ret", "Kicks regathered", "higher", "Kicking", ("share", "kick_retained", "kicks")),
    ("pts_terr", "Points per 10% of territory", "higher", "Conversion", ("per", "pts", "terr")),
    ("pts_poss", "Points per 10% of possession", "higher", "Conversion", ("per", "pts", "poss")),
    ("terr", "Territory", "higher", "Kicking", ("for", "terr")),
    ("poss", "Possession", "higher", "Kicking", ("for", "poss")),
]
TEAM_UNITS = {"gainline": "%", "tackle_pct": "%", "scrum_pct": "%", "lineout_pct": "%", "kick_pct": "%", "terr": "%", "poss": "%",
              "ruck_pct": "%", "kick_ret": "%", "pts_terr": "points", "pts_poss": "points"}
TEAM_SHORT = {"pf": "Pts for", "tf": "Tries for", "metres": "Metres", "gainline": "Gain line", "breaks": "Breaks", "beaten": "Beaten",
              "offloads": "Offloads", "pa": "Pts against", "ta": "Tries agst", "tackle_pct": "Tackle %", "metres_a": "Metres agst",
              "to_won": "TO won", "scrum_pct": "Scrum %", "lineout_pct": "Lineout %", "steals": "Steals", "maul_m": "Maul m",
              "pens": "Pens", "cards": "Cards", "to_conc": "TO conc", "kick_m": "Kick m", "kick_pct": "Goal %", "terr": "Territory",
              "poss": "Possession", "ruck_pct": "Ruck %", "pens_ruck": "Ruck pens", "scrum_pens": "Scrum pens",
              "pens_offside": "Offside", "kick_ret": "Regathered", "pts_terr": "Pts/terr", "pts_poss": "Pts/poss"}
STYLE = {"poss", "terr", "kick_m", "offloads"}
NO_ADJUST = {"poss", "terr"}


def _team_value(how, us: dict, them: dict, pf: int, pa: int):
    kind = how[0]
    if kind == "for":
        return pf if how[1] == "pts" else us.get(how[1])
    if kind == "per":                     # points per 10 percentage points of territory or possession
        d = us.get(how[2])
        return pf / (10.0 * d) if isinstance(d, (int, float)) and d > 0.05 else None
    if kind == "against":
        return pa if how[1] == "pts" else them.get(how[1])
    a, b = us.get(how[1]), us.get(how[2])
    if a is None or b is None:
        return None
    if kind == "ratio":
        return a / (a + b) if (a + b) > 0 else None
    if kind == "share":
        return a / b if b else None
    if kind == "sum":
        return a + b
    return None


def match_values(m: dict, side: str) -> dict:
    us = m["hstat"] if side == "home" else m["astat"]
    them = m["astat"] if side == "home" else m["hstat"]
    pf = m["hs"] if side == "home" else m["as"]
    pa = m["as"] if side == "home" else m["hs"]
    return {k: _team_value(how, us or {}, them or {}, pf, pa) for k, _l, _d, _g, how in TEAM_METRICS}


def team_profiles(finals: list[dict], now_day: str, days: int = 730, min_n: int = 6) -> dict:
    since = (date.fromisoformat(now_day) - timedelta(days=days)).isoformat()
    rows = defaultdict(list)
    allowed = defaultdict(lambda: defaultdict(list))
    for m in finals:
        if m["date"][:10] < since or not m.get("hstat") or not m.get("astat"):
            continue
        for side, other in (("home", "away"), ("away", "home")):
            vals = match_values(m, side)
            rows[m[side]["id"]].append((m[other]["id"], vals))
            for k, v in vals.items():
                if v is not None:
                    allowed[m[other]["id"]][k].append(v)
    field = {}
    for k, *_ in TEAM_METRICS:
        vs = [x[k] for t in rows for _o, x in rows[t] if x.get(k) is not None]
        field[k] = sum(vs) / len(vs) if vs else None
    avg_allowed = {t: {k: sum(v) / len(v) for k, v in d.items() if v} for t, d in allowed.items()}
    prof = {}
    for t, lst in rows.items():
        if len(lst) < min_n:
            continue
        out = {}
        for k, *_ in TEAM_METRICS:
            vs, adj = [], []
            for opp, x in lst:
                v = x.get(k)
                if v is None:
                    continue
                vs.append(v)
                oa = (avg_allowed.get(opp) or {}).get(k)
                shift = (oa - field[k]) if (oa is not None and field[k] is not None and k not in NO_ADJUST) else 0.0
                adj.append(v - shift)
            if vs:
                out[k] = {"raw": sum(vs) / len(vs), "adj": sum(adj) / len(adj), "n": len(vs)}
        prof[t] = {"n": len(lst), "m": out}
    for k, _l, d, _g, _h in TEAM_METRICS:
        vals = sorted(p["m"][k]["adj"] for p in prof.values() if k in p["m"])
        for p in prof.values():
            if k in p["m"]:
                p["m"][k]["pct"] = PL.pct_of(vals, p["m"][k]["adj"], lower_better=(d == "lower"))
    return {"since": since, "teams": prof, "field": field}


def strengths(prof: dict, k: int = 3) -> dict:
    items = [(mid, lab, (prof["m"].get(mid) or {}).get("pct")) for mid, lab, _d, _g, _h in TEAM_METRICS if mid not in STYLE]
    items = [x for x in items if x[2] is not None]
    items.sort(key=lambda x: -x[2])
    return {"best": [{"id": i, "label": lab, "pct": p} for i, lab, p in items[:k]],
            "worst": [{"id": i, "label": lab, "pct": p} for i, lab, p in items[-k:][::-1]]}


# ── players ────────────────────────────────────────────────────────────────────────────────────────────────

# (id, label, short, direction, family)
PLAYER_METRICS = [
    ("val80", "Scrum value per 80", "Value", "higher", "value"),
    ("pts", "Points per 80", "Points", "higher", "scoring"), ("tries", "Tries per 80", "Tries", "higher", "scoring"),
    ("ta", "Try assists per 80", "Try ast", "higher", "creating"), ("m", "Metres per 80", "Metres", "higher", "carrying"),
    ("car", "Carries per 80", "Carries", "higher", "carrying"), ("mpc", "Metres per carry", "m/carry", "higher", "carrying"),
    ("cb", "Clean breaks per 80", "Breaks", "higher", "carrying"), ("db", "Defenders beaten per 80", "Beaten", "higher", "carrying"),
    ("off", "Offloads per 80", "Offloads", "higher", "creating"), ("pas", "Passes per 80", "Passes", "higher", "creating"),
    ("tk", "Tackles per 80", "Tackles", "higher", "defence"), ("tkpct", "Tackle success", "Tackle %", "higher", "defence"),
    ("mt", "Missed tackles per 80", "Missed", "lower", "defence"),
    ("rk", "Rucks won per 80", "Rucks", "higher", "breakdown"), ("toc", "Turnovers conceded per 80", "TO conc", "lower", "discipline"),
    ("pc", "Penalties conceded per 80", "Pens", "lower", "discipline"), ("kfh", "Kicks from hand per 80", "Kicks", "higher", "kicking"),
    ("kpct", "Goal-kicking success", "Goal %", "higher", "kicking"),
    ("lopct", "Lineout throws won", "Throw %", "higher", "set piece"), ("ml", "Mauls won per 80", "Mauls", "higher", "set piece"),
    ("ko", "Knock-ons per 80", "Knock-ons", "lower", "discipline"), ("cards", "Cards per 80", "Cards", "lower", "discipline"),
    ("gkp", "Goal-kicking points per 80", "Kick pts", "higher", "kicking"), ("inv", "Involvements per 80", "Involve", "higher", "breakdown"),
]
PM_IDS = [x[0] for x in PLAYER_METRICS]
KICK_AVG = 0.72


def _pct_tables(lst: list) -> dict:
    t = {}
    for mid, _l, _s, d, _f in PLAYER_METRICS:
        t[mid] = (sorted(r[mid] for _a, r in lst if r.get(mid) is not None), d)
    return t


def player_tables(finals: list[dict], athletes: dict, now_day: str, weights: dict | None) -> dict:
    games = PL.player_games(finals)
    pos = PL.assign_positions(finals, athletes)
    for g in games:
        g["pos"] = pos.get(g["aid"])
        g["grp"] = PL.POS_GROUP.get(g["pos"]) if g["pos"] else None
    agg_grp = defaultdict(lambda: {"min": 0.0, "sums": defaultdict(float)})
    for g in games:
        if not g["grp"] or not g["stats"]:
            continue
        a = agg_grp[g["grp"]]
        a["min"] += g["min"]
        for k in PL.RATE_KEYS:
            v = g["stats"].get(k)
            if isinstance(v, (int, float)):
                a["sums"][k] += v
    prior = {gname: {k: 80.0 * a["sums"].get(k, 0.0) / a["min"] for k in PL.RATE_KEYS} for gname, a in agg_grp.items() if a["min"]}
    by_aid = defaultdict(list)
    for g in games:
        by_aid[g["aid"]].append(g)
    cur_from = (date.fromisoformat(now_day) - timedelta(days=730)).isoformat()
    w = weights or {}
    out = {"players": {}, "prior": prior, "games": by_aid, "pos": pos, "cur_from": cur_from}
    rows_cur = defaultdict(list)
    seasons = defaultdict(lambda: defaultdict(list))

    def window(gs):
        sel = [g for g in gs if g["stats"]]
        if not sel:
            return None
        return next(iter(PL.aggregate(sel).values()))
    for aid, gs in by_aid.items():
        gs.sort(key=lambda g: g["date"])
        grp = PL.POS_GROUP.get(pos.get(aid) or "")
        rec = {"aid": aid, "pos": pos.get(aid), "grp": grp, "career": PL.aggregate(gs)[aid], "seasons": {}}
        for y in sorted({g["season"] for g in gs}):
            a = window([g for g in gs if g["season"] == y])
            if a:
                rt = PL.rates(a, prior.get(grp))
                rt["val_raw"] = PL.value_per80(rt, w, {})
                rec["seasons"][y] = {"agg": a, "rates": rt}
                if grp and a["min"] >= PL.QUAL_MIN["season"]:
                    seasons[y][grp].append((aid, rt))
        a = window([g for g in gs if g["date"] >= cur_from])
        if a:
            rt = PL.rates(a, prior.get(grp))
            rt["val_raw"] = PL.value_per80(rt, w, {})
            rec["cur"] = {"agg": a, "rates": rt}
            if grp and a["min"] >= PL.QUAL_MIN["season"]:
                rows_cur[grp].append((aid, rt))
        out["players"][aid] = rec
    # replacement level: the 20th percentile of the raw value among qualified players of the group, per window
    def repl_of(lst):
        vs = sorted(r["val_raw"] for _a, r in lst)
        return vs[int(0.2 * (len(vs) - 1))] if vs else 0.0
    repl_cur = {g: repl_of(lst) for g, lst in rows_cur.items()}
    repl_season = {y: {g: repl_of(lst) for g, lst in d.items()} for y, d in seasons.items()}
    out["repl"] = repl_cur

    def finish(rt, grp, a, repl):
        rt["val80"] = rt["val_raw"] - repl.get(grp, 0.0)
        if a and a.get("kick_att", 0) >= 3:
            # goal kicking above an average kicker, per 80 (about 2.5 points a kick)
            rt["val80"] += 80.0 * 2.5 * (a["kick_made"] - KICK_AVG * a["kick_att"]) / max(a["min"], 160.0)
        return rt
    for aid, rec in out["players"].items():
        grp = rec["grp"]
        if "cur" in rec:
            finish(rec["cur"]["rates"], grp, rec["cur"]["agg"], repl_cur)
        for y, s in rec["seasons"].items():
            finish(s["rates"], grp, s["agg"], repl_season.get(y) or repl_cur)
    cur_tabs = {g: _pct_tables(lst) for g, lst in rows_cur.items()}
    season_tabs = {y: {g: _pct_tables(lst) for g, lst in d.items()} for y, d in seasons.items()}
    for aid, rec in out["players"].items():
        g = rec["grp"]
        if "cur" in rec and g in cur_tabs:
            rt = rec["cur"]["rates"]
            rec["cur"]["pct"] = {mid: PL.pct_of(v, rt.get(mid), d == "lower") for mid, (v, d) in cur_tabs[g].items()}
            rec["cur"]["qual"] = rec["cur"]["agg"]["min"] >= PL.QUAL_MIN["season"]
        for y, s in rec["seasons"].items():
            tabs = (season_tabs.get(y) or {}).get(g)
            if not tabs:
                continue
            s["pct"] = {mid: PL.pct_of(v, s["rates"].get(mid), d == "lower") for mid, (v, d) in tabs.items()}
            s["qual"] = s["agg"]["min"] >= PL.QUAL_MIN["season"]
    out["n_cur"] = {g: len(v) for g, v in rows_cur.items()}
    return out


def age_on(dob: str | None, day: str) -> float | None:
    try:
        b = date.fromisoformat(str(dob)[:10])
        d = date.fromisoformat(day[:10])
    except (TypeError, ValueError):
        return None
    a = (d - b).days / 365.25
    return round(a, 1) if 15 < a < 50 else None
