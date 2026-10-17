"""
Player value, best by position, team strengths and needs, and the trade simulator's inputs for The Quant Rink
(the shared spec is docs/VALUE_SECTIONS.md; payloads in PAYLOADS.md "As built": value.json, needs/<abbr>.json,
trade.json).

Currency: Rink value (models/value.py)
--------------------------------------
Skaters: GAR = EV offence + EV defence + power play + penalty kill + shooting + penalties, in goals above a
replacement player (the position group's players outside each team's top 13 forwards / 7 defence by TOI);
goalies: GSAx above replacement goalies. WAR = GAR / goals per win (the Pythagorean derivative). Rates: GAR per 60.
Goalies are ranked separately. The leaderboard and best-by-position read the season catalogues (skaters.json,
goalies.json); "qualified" is the catalogue's own sample floor (skaters 250 5v5 minutes per 82 team games,
prorated; goalies a quarter of the team's minutes).

Rest-of-season projection (team needs and the trade simulator)
-------------------------------------------------------------
    rate = (GAR_this + 0.7 x GAR_last) / (TOI_this + 0.7 x TOI_last + K) x 60      GAR per 60 (components likewise)
(last season's minutes at the RAPM prior's carry, 0.7; K = 300 minutes for skaters, 1,500 for goalies, of
replacement-level play, so a call-up with a handful of games sits near replacement). Skater minutes a game = (TOI_this + 10 x last season's
TOI per game) / (games_this + 10); a goalie's = his share of his team's goalie minutes, blended the same way, x 60.
Next season = rate + an aging step: the delta-method change in GAR per 60 between consecutive seasons by age
(skaters with 400+ minutes in both, goalies 1,000+; harmonic-mean minute weights), centred on the all-ages mean
change, shrunk towards zero and smoothed over neighbouring ages (`aging_curve`).

Depth chart (position-aware)
---------------------------
Per game a team has a forward budget (the league's forward minutes per team game last season, ~181), a defence
budget (~117) and 60 goalie minutes; each player is capped (forwards 22, defence 26, goalies 60). Projected
minutes are handed out most first within each group; a shortfall is played at replacement level (GAR 0). Team
value = sum(rate x minutes) / 60, goals a game above replacement. A trade (`apply_moves`): outgoing minutes open
up at the player's position; an incoming player takes his minutes from open minutes at his position, then from his
new team's lowest-rated minutes at that position (replacement fill first when lower), then at the neighbouring
positions (centre and both wings are neighbours; defence and goal have none); a goalie who is better than a team's
goalie takes that goalie's starts. Open minutes left over go to the best remaining players at the position (each at
most 4 more minutes for forwards, 5 for defence, all of them for a goalie) up to the cap, then the neighbours, then
replacement. The change in team value is the change in its net rating (goals a
game) for the rest of the season.

Odds: per-team sensitivity curves from the season simulation (season_sim.sensitivity, the whole season re-run
with that club shifted by -0.75 .. +0.75 goals a game); linear between grid points, the edge value beyond.
"""
from __future__ import annotations

import logging
import math
from bisect import bisect_left, bisect_right
from typing import Any, Iterable

from oddsmarkets.nhl import analytics as an

logger = logging.getLogger(__name__)

VERSION = 1
PREV_WEIGHT = 0.7
TOI_PRIOR_GAMES = 10.0
SHRINK_MIN = {"S": 300.0, "G": 1500.0}   # minutes of replacement-level play added to the rest-of-season rate
ROLES = ("C", "L", "R", "D", "G")
ROLE_LABELS = {"C": "Centres", "L": "Left wings", "R": "Right wings", "D": "Defence", "G": "Goalies"}
ROLE_ONE = {"C": "C", "L": "LW", "R": "RW", "D": "D", "G": "G"}
GROUP = {"C": "F", "L": "F", "R": "F", "D": "D", "G": "G"}
ADJACENT = {"C": ("L", "R"), "L": ("R", "C"), "R": ("L", "C"), "D": (), "G": ()}
CAP = {"F": 22.0, "D": 26.0, "G": 60.0}
EXTRA = {"F": 4.0, "D": 5.0, "G": 60.0}   # a "next player up" takes at most this many more minutes (a backup goalie all)
BUDGET = {"F": 181.0, "D": 117.0, "G": 60.0}
COMPONENTS = ("ev_off", "ev_def", "pp", "pk", "shooting", "pen")
COMP_LABELS = {"ev_off": "EV offence", "ev_def": "EV defence", "pp": "power play", "pk": "penalty kill", "shooting": "shooting",
               "pen": "penalties"}
UNITS = (("ev_off", "5v5 offence"), ("ev_def", "5v5 defence"), ("pp", "Power play"), ("pk", "Penalty kill"))
GRADE_CUTS = ((80, "A"), (60, "B"), (40, "C"), (20, "D"), (-1, "F"))
N_CANDIDATES = 5
EXTRA_ATTAINABLE = 3
MIN_CAND_MIN = {"F": 8.0, "D": 10.0, "G": 10.0}
OUT_OF_CONTENTION = 0.15
BEST_N = 10
AGING_MIN = {"S": 400.0, "G": 1000.0}
AGING_SHRINK = {"S": 20000.0, "G": 300000.0}   # pseudo-weight (harmonic-mean minutes) pulling each age's change to zero
NOTE = ("Model suggestions based on on-field value (Rink value, GAR); not considering the salary cap, contracts, fit or "
        "availability unless shown. Cap not checked: there is no free, legitimate salary source we use for the NHL.")


def _f(v: Any) -> float | None:
    return an.fnum(v)


def _r(v: Any, nd: int = 2) -> float | None:
    v = _f(v)
    return None if v is None else round(v, nd)


def place(sorted_vals: list[float], v: float, lower: bool = False) -> int:
    n = len(sorted_vals)
    if not n:
        return 50
    lo, hi = bisect_left(sorted_vals, v), bisect_right(sorted_vals, v)
    below, above, ties = lo, n - hi, hi - lo
    rank = (below + 0.5 * ties) / n if not lower else (above + 0.5 * ties) / n
    return int(round(100 * rank))


def grade(pct: float | None) -> str | None:
    if pct is None:
        return None
    for cut, g in GRADE_CUTS:
        if pct >= cut:
            return g
    return "F"


def an_ordinal(n: int) -> str:
    n = int(n)
    t = n % 100
    return f"{n}{'th' if 11 <= t <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def role_of(pos: Any) -> str:
    p = str(pos or "").upper()
    if p.startswith("G"):
        return "G"
    if p.startswith("D"):
        return "D"
    if p in ("L", "LW"):
        return "L"
    if p in ("R", "RW"):
        return "R"
    return "C"


# ---------------------------------------------------------------------------------------------- season value

def _comps(vals: dict) -> dict:
    return {c: _f(vals.get(f"gar_{c}")) for c in COMPONENTS}


def _why_skater(comps: dict) -> list:
    parts = sorted(((v, c) for c, v in comps.items() if v is not None and abs(v) >= 0.05), key=lambda x: -abs(x[0]))[:2]
    return [[COMP_LABELS[c], round(v, 1)] for v, c in parts]


def season_value(season: int, sk: dict | None, gk: dict | None, prev_sk: dict | None = None, prev_gk: dict | None = None,
                 phase: str | None = None, updated_at: str | None = None) -> dict:
    """value.json: every skater and goalie with GAR in the season's catalogues: GAR, WAR, GAR per 60, the components,
    percentiles (skaters against qualified skaters and their position; goalies against qualified goalies), the change
    from last season; `best` lists the top BEST_N qualified players at C, LW, RW, D and G."""
    rows: dict[str, dict] = {}
    for kind, cat, prev in (("S", sk, prev_sk), ("G", gk, prev_gk)):
        PP = ((prev or {}).get("players")) or {}
        for pid, r in (((cat or {}).get("players")) or {}).items():
            v = r.get("values") or {}
            gar, war, toi = _f(v.get("gar")), _f(v.get("war")), _f(r.get("toi")) or 0.0
            if gar is None or toi <= 0:
                continue
            role = "G" if kind == "G" else role_of(r.get("pos"))
            pv = (PP.get(pid) or {})
            pvv = pv.get("values") or {}
            ptoi = _f(pv.get("toi")) or 0.0
            pgar = _f(pvv.get("gar"))
            rate = gar / toi * 60.0
            comps = _comps(v) if kind == "S" else {}
            why = _why_skater(comps) if kind == "S" else \
                [x for x in ([["GSAx", round(_f(v.get("gsax")), 1)]] if _f(v.get("gsax")) is not None else []) +
                 ([["save %", round(_f(v.get("sv_pct")), 3)]] if _f(v.get("sv_pct")) is not None else [])]
            rows[pid] = {"id": pid, "name": r.get("name"), "team": r.get("team"), "pos": role, "kind": kind, "age": _r(r.get("age"), 1),
                         "gp": int(r.get("gp") or 0), "toi": toi, "toi_gp": toi / max(1, int(r.get("gp") or 0)), "gar": gar,
                         "war": war, "rate": rate, "q": bool(r.get("qualified")),
                         "prev_war": _f(pvv.get("war")) if pgar is not None and ptoi > 0 else None,
                         "d_rate": rate - pgar / ptoi * 60.0 if pgar is not None and ptoi > 0 else None,
                         "gsax": _f(v.get("gsax")) if kind == "G" else None, "why": why, **{c: comps.get(c) for c in COMPONENTS}}
    for kind in ("S", "G"):
        ref = sorted(x["war"] for x in rows.values() if x["kind"] == kind and x["q"] and x["war"] is not None)
        refr = {k: sorted(x["war"] for x in rows.values() if x["kind"] == kind and x["q"] and x["pos"] == k and x["war"] is not None)
                for k in ROLES}
        for x in rows.values():
            if x["kind"] != kind or x["war"] is None:
                continue
            x["pct"] = place(ref, x["war"]) if len(ref) >= 2 else None
            rr = refr.get(x["pos"]) or []
            x["pct_pos"] = place(rr, x["war"]) if len(rr) >= 3 else None
    best = {k: [x["id"] for x in sorted((x for x in rows.values() if x["q"] and x["pos"] == k and x["war"] is not None),
                                         key=lambda x: -x["war"])[:BEST_N]] for k in ROLES}
    gpw = goals_per_win(rows.values())
    if gpw is None and (prev_sk or prev_gk):
        gpw = goals_per_win([{"gar": _f(r.get("values", {}).get("gar")), "war": _f(r.get("values", {}).get("war"))}
                             for c in (prev_sk, prev_gk) for r in (((c or {}).get("players")) or {}).values()])
    cols = ["id", "name", "team", "pos", "kind", "age", "gp", "toi", "toi_gp", "gar", "war", "rate", "pct", "pct_pos", "q",
            "prev_war", "d_rate"] + list(COMPONENTS) + ["gsax", "why"]
    nd = {"toi": 0, "toi_gp": 1, "gar": 1, "war": 2, "rate": 3, "prev_war": 2, "d_rate": 3, "gsax": 1,
          **{c: 1 for c in COMPONENTS}}
    out_rows = []
    for x in sorted(rows.values(), key=lambda x: -(x["war"] if x["war"] is not None else -99)):
        out_rows.append([(_r(x.get(c), nd[c]) if c in nd else (1 if x.get(c) else 0) if c == "q" else x.get(c)) for c in cols])
    return {"ok": True, "season": int(season), "updated_at": updated_at or an.now(), "phase": phase, "version": VERSION,
            "currency": {"unit": "WAR", "goals_per_win": _r(gpw, 2), "replacement": 0.0},
            "team_games": (sk or {}).get("team_games"),
            "roles": dict(ROLE_LABELS), "cols": cols, "rows": out_rows, "best": best,
            "n_qualified": {"S": sum(1 for x in rows.values() if x["kind"] == "S" and x["q"]),
                            "G": sum(1 for x in rows.values() if x["kind"] == "G" and x["q"])},
            "note": "GAR: goals above replacement (Rink value); WAR = GAR / goals per win. Percentiles against qualified players."}


def goals_per_win(rows: Iterable[dict]) -> float | None:
    """GAR / WAR read back from the catalogues (the value model's 4g / x) on players with |WAR| >= 0.5, so the
    payloads' rounding does not distort it; None with fewer than 20 such players (early in a season)."""
    xs = [(x["gar"], x["war"]) for x in rows if x.get("gar") is not None and x.get("war") is not None and abs(x["war"]) >= 0.5]
    if len(xs) < 20:
        return None
    return sum(abs(g) for g, _ in xs) / sum(abs(w) for _, w in xs)


# ---------------------------------------------------------------------------------------------- aging

def aging_curve(rows_by_season: dict[int, list[dict]], kind: str) -> list[list[float]]:
    """[[age, change in GAR per 60 over the next season]] for ages 18..42, by the delta method on consecutive
    seasons (players with AGING_MIN minutes in both), centred on the all-ages mean change, shrunk and smoothed."""
    S: dict[int, float] = {}
    W: dict[int, float] = {}
    seasons = sorted(rows_by_season)
    min_toi = AGING_MIN[kind]
    for s in seasons:
        nxt = an.season_id(an.start_year(s) + 1)
        b = {x["id"]: x for x in rows_by_season.get(nxt) or [] if x.get("kind") == kind}
        if not b:
            continue
        for x in rows_by_season[s]:
            y = b.get(x["id"])
            if x.get("kind") != kind or not y or x.get("age") is None or x.get("rate") is None or y.get("rate") is None:
                continue
            if (x.get("toi") or 0) < min_toi or (y.get("toi") or 0) < min_toi:
                continue
            w = 2.0 / (1.0 / x["toi"] + 1.0 / y["toi"])
            a = int(round(x["age"]))
            S[a] = S.get(a, 0.0) + w * (y["rate"] - x["rate"])
            W[a] = W.get(a, 0.0) + w
    if not W:
        return [[a, 0.0] for a in range(18, 43)]
    mean = sum(S.values()) / sum(W.values())
    raw = {a: (S[a] / W[a] - mean) * W[a] / (W[a] + AGING_SHRINK[kind]) for a in W}
    out = []
    for a in range(18, 43):
        num = den = 0.0
        for d, k in ((-1, 0.5), (0, 1.0), (1, 0.5)):
            if a + d in raw:
                num += k * W[a + d] * raw[a + d]
                den += k * W[a + d]
        out.append([a, round(num / den, 4) if den else 0.0])
    return out


def aging_delta(curve: list | None, age: float | None) -> float:
    if not curve or age is None or not math.isfinite(age):
        return 0.0
    xs = [c[0] for c in curve]
    ys = [c[1] for c in curve]
    return float(interp(xs, ys, float(age)) or 0.0)


# ---------------------------------------------------------------------------------------------- projection

def player_projection(cur: dict | None, prev: dict | None, kind: str, team_gp_cur: float = 0.0, team_gp_prev: float = 82.0,
                      age: float | None = None, curve: list | None = None) -> dict:
    """Rest-of-season GAR per 60 (and components), minutes a game and next season's rate for one player.
    `cur` / `prev`: catalogue rows (skaters.json / goalies.json) this and last season."""
    cv, pv = (cur or {}).get("values") or {}, (prev or {}).get("values") or {}
    ct, pt = _f((cur or {}).get("toi")) or 0.0, _f((prev or {}).get("toi")) or 0.0
    cg, pg = _f(cv.get("gar")), _f(pv.get("gar"))
    num = den = 0.0
    if cg is not None and ct > 0:
        num += cg
        den += ct
    if pg is not None and pt > 0:
        num += PREV_WEIGHT * pg
        den += PREV_WEIGHT * pt
    rate = num / (den + SHRINK_MIN[kind]) * 60.0 if den > 0 else 0.0
    comps = {}
    if kind == "S":
        for c in COMPONENTS:
            n_ = d_ = 0.0
            a, b = _f(cv.get(f"gar_{c}")), _f(pv.get(f"gar_{c}"))
            if a is not None and ct > 0:
                n_ += a
                d_ += ct
            if b is not None and pt > 0:
                n_ += PREV_WEIGHT * b
                d_ += PREV_WEIGHT * pt
            comps[c] = n_ / (d_ + SHRINK_MIN[kind]) * 60.0 if d_ > 0 else 0.0
    basis = "b" if (cg is not None and ct > 0) and (pg is not None and pt > 0) else "c" if cg is not None and ct > 0 else \
        "p" if pg is not None and pt > 0 else "r"
    cgp, pgp = int((cur or {}).get("gp") or 0), int((prev or {}).get("gp") or 0)
    if kind == "G":
        cs = ct / (team_gp_cur * 60.0) if team_gp_cur > 0 else None
        ps = pt / (team_gp_prev * 60.0) if team_gp_prev > 0 and pt > 0 else None
        if cs is not None and ps is not None:
            share = (cs * team_gp_cur + ps * TOI_PRIOR_GAMES) / (team_gp_cur + TOI_PRIOR_GAMES)
        else:
            share = cs if cs is not None else ps if ps is not None else 0.0
        mpg = min(1.0, share) * 60.0
    else:
        if pgp > 0 and pt > 0:
            mpg = (ct + TOI_PRIOR_GAMES * pt / pgp) / (cgp + TOI_PRIOR_GAMES)
        elif cgp > 0:
            mpg = ct / cgp
        else:
            mpg = 0.0
    return {"rate": rate, "comps": comps, "mpg": mpg, "basis": basis, "next": rate + aging_delta(curve, age)}


def team_games_played(store: dict) -> dict[str, int]:
    n: dict[str, int] = {}
    games = (store or {}).get("games") or {}
    for g in (games.values() if isinstance(games, dict) else games):
        if not isinstance(g, dict):
            continue
        gid = str(g.get("game_id") or "")
        st = str(g.get("status") or "").lower()
        if gid[4:6] != "02" or st not in ("final", "off", "official"):
            continue
        for t in (g.get("home"), g.get("away")):
            if t:
                n[t] = n.get(t, 0) + 1
    return n


def projections(season: int, store: dict, teams: Iterable[str], sk: dict | None, gk: dict | None, prev_sk: dict | None,
                prev_gk: dict | None, curves: dict | None = None) -> dict[str, dict]:
    """{pid: {"id","name","team","pos","group","age","mpg","rate","comps","next","basis"}} for every player on a
    current roster (the store's players carry today's team)."""
    teams = set(teams)
    gp_now = team_games_played(store)
    cur = {**(((sk or {}).get("players")) or {}), **(((gk or {}).get("players")) or {})}
    prv = {**(((prev_sk or {}).get("players")) or {}), **(((prev_gk or {}).get("players")) or {})}
    prev_team_gp = max([int(_f((prev_gk or {}).get("team_games")) or 0), int(_f((prev_sk or {}).get("team_games")) or 0)] or [0]) or 82
    players = (store or {}).get("players") or {}
    out = {}
    for pid0, p in (players.items() if isinstance(players, dict) else ((x.get("id"), x) for x in players)):
        pid = an.sid(pid0)
        if not pid or not isinstance(p, dict) or p.get("team") not in teams:
            continue
        role = role_of(p.get("pos") or (cur.get(pid) or {}).get("pos") or (prv.get(pid) or {}).get("pos"))
        kind = "G" if role == "G" else "S"
        age = an.age_on(p.get("dob"), season) if p.get("dob") else _f((cur.get(pid) or {}).get("age"))
        curve = (curves or {}).get(kind)
        pr = player_projection(cur.get(pid), prv.get(pid), kind, float(gp_now.get(p["team"], 0)), float(prev_team_gp), age, curve)
        name = p.get("name") or " ".join(x for x in (p.get("first"), p.get("last")) if x) or (cur.get(pid) or prv.get(pid) or {}).get("name") or pid
        out[pid] = {"id": pid, "name": name, "team": p["team"], "pos": role, "group": GROUP[role], "age": age, **pr}
    return out


# ---------------------------------------------------------------------------------------------- depth chart

def params_for(budget: dict | None = None) -> dict:
    b = dict(BUDGET)
    b.update({k: float(v) for k, v in (budget or {}).items() if v})
    return {"budget": b, "cap": dict(CAP), "extra": dict(EXTRA), "repl": 0.0}


def league_budget(sk: dict | None, gk: dict | None) -> dict:
    """The league's forward and defence minutes per team game in a completed season's catalogue."""
    P = ((sk or {}).get("players")) or {}
    tg = _f((sk or {}).get("team_games")) or 82.0
    teams = {r.get("team") for r in P.values() if r.get("team")}
    if not P or not teams:
        return dict(BUDGET)
    f = sum(_f(r.get("toi")) or 0.0 for r in P.values() if r.get("group") == "F")
    d = sum(_f(r.get("toi")) or 0.0 for r in P.values() if r.get("group") == "D")
    n = len(teams) * tg
    out = dict(BUDGET)
    if n > 0 and f > 0 and d > 0:
        out.update({"F": round(f / n, 1), "D": round(d / n, 1)})
    return out


def baseline_minutes(team: list[dict], prm: dict) -> dict[str, float]:
    out = {}
    for grp in ("F", "D", "G"):
        left = prm["budget"][grp]
        cap = prm["cap"][grp]
        for p in sorted([p for p in team if GROUP[p["pos"]] == grp], key=lambda p: (-min(float(p.get("mpg") or 0.0), cap), str(p["id"]))):
            take = max(0.0, min(min(float(p.get("mpg") or 0.0), cap), left))
            out[p["id"]] = take
            left -= take
    return out


def team_value(team: list[dict], minutes: dict[str, float], prm: dict) -> dict:
    """Goals a game above replacement for the rotation; components for skaters; fill per group."""
    by = {p["id"]: p for p in team}
    out = {"net": 0.0, **{c: 0.0 for c in COMPONENTS}, "gk": 0.0}
    used = {"F": 0.0, "D": 0.0, "G": 0.0}
    for k, m in minutes.items():
        p = by.get(k)
        if p is None:
            continue
        used[GROUP[p["pos"]]] += m
        out["net"] += p["rate"] * m / 60.0
        if p["pos"] == "G":
            out["gk"] += p["rate"] * m / 60.0
        for c in COMPONENTS:
            out[c] += float((p.get("comps") or {}).get(c) or 0.0) * m / 60.0
    out["fill"] = {g: max(0.0, prm["budget"][g] - used[g]) for g in used}
    return out


def apply_moves(team: list[dict], out_ids: Iterable[str], incoming: Iterable[dict], prm: dict) -> dict:
    """The team after `out_ids` leave and `incoming` arrive (the same rules as docs/rink/assets/js/trade.js
    `applyMoves`). Returns {"before","after","delta" (goals a game), "delta_comp": {component: change},
    "minutes", "base", "displaced", "absorbed", "fill_before", "fill_after"}."""
    out_ids = {str(x) for x in out_ids}
    own = {str(t["id"]) for t in team}
    incoming = [p for p in incoming if str(p["id"]) not in own]
    in_ids = {p["id"] for p in incoming}
    base = baseline_minutes(team, prm)
    before = team_value(team, base, prm)
    roster = [p for p in team if str(p["id"]) not in out_ids] + incoming
    by = {p["id"]: p for p in roster}
    m = {p["id"]: base.get(p["id"], 0.0) for p in roster if p["id"] not in in_ids}
    open_ = {k: 0.0 for k in ROLES}
    for p in team:
        if str(p["id"]) in out_ids:
            open_[p["pos"]] += base.get(p["id"], 0.0)
    fill = dict(before["fill"])
    displaced: dict[str, float] = {}
    absorbed: dict[str, float] = {}
    for p in sorted(incoming, key=lambda p: (-float(p["rate"]), str(p["id"]))):
        role, grp = p["pos"], GROUP[p["pos"]]
        cap = prm["cap"][grp]
        need = min(float(p.get("mpg") or 0.0), cap)
        if role == "G":
            worse = sum(m[k] for k in m if by[k]["pos"] == "G" and k not in in_ids and float(by[k]["rate"]) < float(p["rate"]))
            need = min(cap, max(need, open_["G"] + worse + fill["G"]))
        take = min(need, open_[role])
        open_[role] -= take
        got = take
        need -= take
        for rr in (role,) + ADJACENT[role]:
            if need <= 1e-9:
                break
            pool = sorted([(float(by[k]["rate"]), str(k)) for k in m if by[k]["pos"] == rr and m[k] > 1e-9 and k not in in_ids],
                          key=lambda x: (x[0], x[1]))
            if rr == role and fill[grp] > 1e-9:
                pool = sorted(pool + [(prm["repl"], "")], key=lambda x: (x[0], x[1]))
            for rate, k in pool:
                if need <= 1e-9:
                    break
                if rate >= float(p["rate"]) and k:
                    break
                if k == "":
                    t = min(need, fill[grp])
                    fill[grp] -= t
                else:
                    t = min(need, m[k])
                    m[k] -= t
                    displaced[k] = displaced.get(k, 0.0) + t
                need -= t
                got += t
        m[p["id"]] = got
    for role in ROLES:
        left = open_[role]
        grp = GROUP[role]
        cap = prm["cap"][grp]
        for rr in (role,) + ADJACENT[role]:
            if left <= 1e-9:
                break
            for k in sorted([k for k in m if by[k]["pos"] == rr], key=lambda k: (-float(by[k]["rate"]), str(k))):
                if left <= 1e-9:
                    break
                spare = min(cap - m[k], prm["extra"][grp] - absorbed.get(k, 0.0))
                if spare <= 1e-9:
                    continue
                t = min(spare, left)
                m[k] += t
                absorbed[k] = absorbed.get(k, 0.0) + t
                left -= t
        fill[grp] += max(0.0, left)
    after = team_value(roster, m, prm)
    return {"before": before["net"], "after": after["net"], "delta": after["net"] - before["net"],
            "delta_comp": {c: after[c] - before[c] for c in COMPONENTS + ("gk",)}, "minutes": m, "base": base,
            "displaced": sorted([[k, v] for k, v in displaced.items() if v > 0.05], key=lambda x: -x[1]),
            "absorbed": sorted([[k, v] for k, v in absorbed.items() if v > 0.05], key=lambda x: -x[1]),
            "fill_before": before["fill"], "fill_after": fill}


# ---------------------------------------------------------------------------------------------- sensitivity curves

def interp(xs: list[float], ys: list[float | None], x: float) -> float | None:
    """Linear interpolation on a grid, the edge value beyond it (trade.js `interp`)."""
    pts = [(float(a), float(b)) for a, b in zip(xs, ys) if b is not None]
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0
    return pts[-1][1]


DECREASING = ("p_first", "p_top2")


def monotone(shifts: list[float], ys: list[float | None], decreasing: bool = False) -> list[float | None]:
    ys = list(ys)
    if 0.0 not in shifts:
        return ys
    i0 = shifts.index(0.0)
    sign = -1.0 if decreasing else 1.0
    for i in range(i0 + 1, len(ys)):
        if ys[i] is not None and ys[i - 1] is not None and sign * ys[i] < sign * ys[i - 1]:
            ys[i] = ys[i - 1]
    for i in range(i0 - 1, -1, -1):
        if ys[i] is not None and ys[i + 1] is not None and sign * ys[i] > sign * ys[i + 1]:
            ys[i] = ys[i + 1]
    return ys


def curve_delta(curves: dict | None, tid: str, key: str, shift: float) -> float | None:
    c = ((curves or {}).get("teams") or {}).get(tid) or {}
    ys = c.get(key)
    xs = (curves or {}).get("shifts") or []
    if not ys or not xs:
        return None
    a, b = interp(xs, ys, shift), interp(xs, ys, 0.0)
    return None if a is None or b is None else a - b


SENS_TTL_HOURS = 6.0                   # a cached run is reused this long while only results and ratings move


def sensitivity_curves(season: int, sim: dict | None, n: int | None = None) -> dict | None:
    """season_sim.sensitivity for the season, monotone-smoothed. Cached on the simulation's inputs (ratings,
    standings, games left); a run on the same clubs, grid and stage is reused for up to SENS_TTL_HOURS when only
    results or ratings have moved (the page adds the curves' differences to the fresh baseline)."""
    import hashlib
    import json
    import time as _time
    from oddsmarkets.nhl.models import season_sim as SS
    from oddsmarkets.nhl.models import team_strength as TS
    if not sim or not sim.get("ok") or not sim.get("teams"):
        return None
    n = int(n or SS.SENS_SIMS)
    key_src = [VERSION, season, n, list(SS.SENS_SHIFTS),
               sorted((t, round(float(r.get("rating") or 0), 4), round(float(r.get("rating_se") or 0), 4),
                       (r.get("current") or {}).get("pts"), (r.get("current") or {}).get("gp"), (r.get("current") or {}).get("remaining"))
                      for t, r in sim["teams"].items())]
    key = hashlib.sha1(json.dumps(key_src, default=str).encode()).hexdigest()
    coarse = hashlib.sha1(json.dumps([VERSION, season, n, list(SS.SENS_SHIFTS), sorted(sim["teams"]),
                                      bool(sim.get("remaining_games"))]).encode()).hexdigest()
    path = an.an_cache() / "value" / f"sensitivity_{season}.json"
    c = an.read_json(path) if path.exists() else None
    if isinstance(c, dict) and (c.get("key") == key or (c.get("coarse") == coarse and
                                                        _time.time() - float(c.get("at") or 0) < SENS_TTL_HOURS * 3600)):
        res = c.get("result")
    else:
        res = SS.sensitivity(season, n=n, seed=int(season) % 100000 + 1, state={"ratings": TS.for_season(season)})
        try:
            an.write_json(path, {"key": key, "coarse": coarse, "at": _time.time(), "result": res})
        except Exception:                          # noqa: BLE001
            pass
    if not res or not res.get("ok"):
        return res
    for t, cc in res["teams"].items():
        for k in list(cc):
            cc[k] = monotone(res["shifts"], cc[k], decreasing=k in DECREASING)
    return res


# ---------------------------------------------------------------------------------------------- grades and needs

def team_lists(proj: dict[str, dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in proj.values():
        out.setdefault(p["team"], []).append(p)
    return out


def unit_values(team: list[dict], prm: dict, games: int) -> dict[str, float]:
    """Projected GAR over `games` games by position and unit."""
    m = baseline_minutes(team, prm)
    by = {p["id"]: p for p in team}
    out = {k: 0.0 for k in ROLES}
    out.update({k: 0.0 for k, _ in UNITS})
    for k, mins in m.items():
        p = by[k]
        out[p["pos"]] += p["rate"] * mins / 60.0 * games
        for u, _ in UNITS:
            out[u] += float((p.get("comps") or {}).get(u) or 0.0) * mins / 60.0 * games
    return out


def grade_teams(lists: dict[str, list[dict]], prm: dict, games: int) -> dict[str, dict]:
    vals = {t: unit_values(ps, prm, games) for t, ps in lists.items()}
    keys = list(ROLES) + [k for k, _ in UNITS]
    out = {t: {} for t in vals}
    for k in keys:
        ref = sorted(v[k] for v in vals.values())
        for t, v in vals.items():
            pct = place(ref, v[k])
            out[t][k] = {"value": v[k], "pct": pct, "grade": grade(pct), "rank": 1 + len(ref) - bisect_right(ref, v[k]), "n": len(ref)}
    return out


def _label(k: str) -> str:
    return ROLE_LABELS.get(k) or dict(UNITS).get(k) or k


def _evidence(k: str, g: dict, team: list[dict], prm: dict, weak: bool) -> str:
    m = baseline_minutes(team, prm)
    rot = [p for p in team if m.get(p["id"], 0) >= 1.0]
    grp = [p for p in rot if p["pos"] == k] if k in ROLES else [p for p in rot if p["pos"] != "G"]
    val = (lambda p: p["rate"]) if k in ROLES else (lambda p: float((p.get("comps") or {}).get(k) or 0.0))
    head = f"{g['value']:.1f} projected GAR over a full season, {an_ordinal(g['rank'])} of {g['n']}"
    if not grp:
        return head + "; no regular here (played at replacement level)"
    grp = sorted(grp, key=lambda p: (val(p), -m[p["id"]])) if weak else sorted(grp, key=lambda p: (-val(p), -m[p["id"]]))
    p = grp[0]
    what = "GAR per 60" if k in ROLES else COMP_LABELS.get(k, k) + " GAR per 60"
    return f"{head}; {'weakest' if weak else 'led by'} {p['name']} ({val(p):+.2f} {what}, {m[p['id']]:.1f} min)"


def candidates(tid: str, key: str, lists: dict[str, list[dict]], prm: dict, games_left: dict[str, int], curves: dict | None,
               sim_teams: dict | None, n: int = N_CANDIDATES) -> list[dict]:
    """Ranked trade targets for team `tid`'s weakness `key` (a position, or a unit ranked by that component),
    each added to `tid`'s depth chart with nobody going back; feasibility hints from the data only."""
    team = lists.get(tid) or []
    pool = []
    for t, ps in lists.items():
        if t == tid:
            continue
        for p in ps:
            if p.get("basis") == "r" or float(p.get("mpg") or 0) < MIN_CAND_MIN[GROUP[p["pos"]]]:
                continue
            if key in ROLES and p["pos"] != key:
                continue
            if key not in ROLES and p["pos"] == "G":
                continue
            pool.append(p)
    scored = []
    for p in pool:
        res = apply_moves(team, [], [p], prm)
        gain = res["delta"] if key in ROLES else res["delta_comp"][key]
        if gain <= 0.002:
            continue
        scored.append((gain, res["delta"], p, res))
    scored.sort(key=lambda x: (-x[0], -x[1], str(x[2]["id"])))
    top_two = {}
    for t, ps in lists.items():
        mm = baseline_minutes(ps, prm)
        top_two[t] = {q["id"] for q in sorted(ps, key=lambda q: (-q["rate"] * mm.get(q["id"], 0.0), q["id"]))[:2]}
    out = []
    n_extra = 0
    for gain, tot, p, res in scored:
        if len(out) >= n + EXTRA_ATTAINABLE or (len(out) >= n and n_extra >= EXTRA_ATTAINABLE):
            break
        seller = p["team"]
        cost = apply_moves(lists.get(seller) or [], [p["id"]], [], prm)["delta"]
        hints = []
        sp = ((sim_teams or {}).get(seller) or {}).get("p_playoffs")
        out_of = sp is not None and sp < OUT_OF_CONTENTION
        if out_of:
            hints.append(f"seller out of contention ({100 * sp:.0f}% to make the playoffs)")
        depth = cost > -0.5 * tot
        if depth:
            hints.append(f"seller has depth at the position: losing the player moves them {cost:+.3f} goals a game (adds {tot:+.3f} here)")
        franchise = p["id"] in top_two.get(seller, set())
        if franchise:
            hints.append("one of the seller's two most valuable players")
        if p.get("age") and p["age"] >= 32 and abs(p["next"] - p["rate"]) >= 0.005:
            hints.append(f"age {p['age']:.0f}: projected {p['next'] - p['rate']:+.3f} GAR per 60 next season")
        attainable = (out_of or depth) and not franchise
        if len(out) >= n:
            if not attainable:
                continue
            n_extra += 1
        left = games_left.get(tid, 0)
        pts = curve_delta(curves, tid, "exp_pts", tot) if curves else None
        disp = [[k, round(v, 1)] for k, v in res["displaced"][:3]]
        out.append({"id": p["id"], "name": p["name"], "team": seller, "pos": p["pos"], "age": _r(p.get("age"), 1),
                    "mpg": _r(p["mpg"], 1), "rate": _r(p["rate"], 3), "gain": _r(gain, 3), "gain_net": _r(tot, 3),
                    "gain_season": _r(tot * left, 1), "pts": _r(pts, 1) if pts is not None else None,
                    "d_playoffs": _r(curve_delta(curves, tid, "p_playoffs", tot), 4) if curves else None,
                    "d_cup": _r(curve_delta(curves, tid, "p_cup", tot), 4) if curves else None,
                    "seller_cost": _r(cost, 3), "displaces": disp, "hints": hints, "attainable": bool(attainable)})
    return out


def needs_payloads(season: int, proj: dict[str, dict], prm: dict, games: int, games_left: dict[str, int], curves: dict | None,
                   sim_teams: dict | None, phase: str | None = None, updated_at: str | None = None) -> dict[str, dict]:
    lists = team_lists(proj)
    grades = grade_teams(lists, prm, games)
    keys = list(ROLES) + [k for k, _ in UNITS]
    out = {}
    for tid, team in lists.items():
        g = grades[tid]
        strengths = sorted(keys, key=lambda k: (-g[k]["pct"], keys.index(k)))[:3]
        weaknesses = [k for k in sorted(keys, key=lambda k: (g[k]["pct"], keys.index(k))) if k not in strengths][:3]
        m = baseline_minutes(team, prm)
        depth = sorted(team, key=lambda p: (["F", "D", "G"].index(p["group"]), -m.get(p["id"], 0), p["id"]))
        out[tid] = {
            "ok": True, "season": int(season), "team": tid, "updated_at": updated_at or an.now(), "phase": phase, "basis": "projection",
            "grades": [{"key": k, "label": _label(k), "value": _r(g[k]["value"], 1), "pct": g[k]["pct"], "grade": g[k]["grade"],
                        "rank": g[k]["rank"], "n": g[k]["n"]} for k in keys],
            "strengths": [{"key": k, "label": _label(k), "grade": g[k]["grade"], "pct": g[k]["pct"], "relative": g[k]["pct"] < 50,
                           "evidence": _evidence(k, g[k], team, prm, False)} for k in strengths],
            "weaknesses": [{"key": k, "label": _label(k), "grade": g[k]["grade"], "pct": g[k]["pct"], "relative": g[k]["pct"] >= 50,
                            "evidence": _evidence(k, g[k], team, prm, True),
                            "targets": candidates(tid, k, lists, prm, games_left, curves, sim_teams)} for k in weaknesses],
            "depth": [{"id": p["id"], "name": p["name"], "pos": p["pos"], "age": _r(p.get("age"), 1), "mpg": _r(m.get(p["id"], 0.0), 1),
                       "rate": _r(p["rate"], 3), "basis": p.get("basis")} for p in depth if m.get(p["id"], 0.0) > 0.05],
            "games": games, "games_left": games_left.get(tid),
            "free_agents": "Not identified: the NHL rosters we read list signed players only.",
            "note": NOTE}
    return out


def trade_payload(season: int, proj: dict[str, dict], prm: dict, games: int, sim: dict | None, curves: dict | None,
                  phase: str | None = None, updated_at: str | None = None) -> dict:
    cols = ["id", "name", "team", "pos", "age", "mpg", "rate", "next", "basis"] + list(COMPONENTS)
    rows = []
    for p in sorted(proj.values(), key=lambda p: (p["team"], ["F", "D", "G"].index(p["group"]), -float(p.get("mpg") or 0), p["id"])):
        rows.append([p["id"], p["name"], p["team"], p["pos"], _r(p.get("age"), 1), _r(p.get("mpg"), 1), _r(p["rate"], 4),
                     _r(p["next"], 4), p.get("basis")] + [_r((p.get("comps") or {}).get(c), 4) for c in COMPONENTS])
    st = (sim or {}).get("teams") or {}
    teams = {}
    for t in sorted({p["team"] for p in proj.values()} | set(st)):
        s = st.get(t) or {}
        cur = s.get("current") or {}
        lot = s.get("lottery") or {}
        teams[t] = {"rating": _r(s.get("rating"), 3), "se": _r(s.get("rating_se"), 3), "gp": cur.get("gp"), "pts": cur.get("pts"),
                    "left": cur.get("remaining"), "exp_pts": _r(s.get("exp_pts"), 2), "p_playoffs": _r(s.get("p_playoffs"), 4),
                    "p_div": _r(s.get("p_div"), 4), "p_conf": _r(s.get("p_conf"), 4), "p_cup": _r(s.get("p_cup"), 4),
                    "p_first": _r(lot.get("p_first"), 4), "p_top2": _r(lot.get("p_top2"), 4), "conference": s.get("conference")}
    return {"ok": True, "season": int(season), "updated_at": updated_at or an.now(), "phase": phase, "version": VERSION,
            "params": prm, "games": games, "roles": dict(ROLE_LABELS), "group": dict(GROUP),
            "adjacent": {k: list(v) for k, v in ADJACENT.items()}, "components": list(COMPONENTS),
            "players": {"cols": cols, "rows": rows}, "teams": teams,
            "curves": ({"shifts": curves["shifts"], "keys": curves["keys"], "n_sims": curves.get("n_sims"), "teams": curves["teams"]}
                       if curves and curves.get("ok") else None),
            "sim": {"n_sims": (sim or {}).get("n_sims") or (sim or {}).get("n"), "remaining_games": (sim or {}).get("remaining_games")}
            if sim and sim.get("ok") else None,
            "note": NOTE}


def build_current(season: int, store: dict, teams: Iterable[str], sk: dict | None, gk: dict | None, prev_sk: dict | None,
                  prev_gk: dict | None, sim: dict | None, curves_aging: dict | None, phase: str | None = None,
                  games: int = 82, curve_sims: int | None = None) -> dict:
    """{"needs": {abbr: payload}, "trade": payload, "n_players"} for the current season."""
    prm = params_for(league_budget(prev_sk, prev_gk))
    proj = projections(season, store, teams, sk, gk, prev_sk, prev_gk, curves_aging)
    curves = None
    if sim and sim.get("ok") and sim.get("teams"):
        try:
            curves = sensitivity_curves(season, sim, curve_sims)
        except Exception as exc:                   # noqa: BLE001
            logger.warning("%s sensitivity failed: %s", season, exc, exc_info=True)
    st = (sim or {}).get("teams") or {} if (sim or {}).get("ok") else {}
    tids = {p["team"] for p in proj.values()}
    if st:
        games_left = {t: int(((st.get(t) or {}).get("current") or {}).get("remaining") or 0) for t in tids}
    else:
        games_left = {t: games for t in tids}
    now = an.now()
    ok_curves = curves if curves and curves.get("ok") else None
    needs = needs_payloads(season, proj, prm, games, games_left, ok_curves, st, phase=phase, updated_at=now)
    trade = trade_payload(season, proj, prm, games, sim if (sim or {}).get("ok") else None, ok_curves, phase=phase, updated_at=now)
    trade["aging"] = curves_aging
    return {"needs": needs, "trade": trade, "n_players": len(proj)}
