"""
Player value, best by position, team strengths and needs, and the trade simulator's inputs for The Quant
Hardwood (the shared spec is docs/VALUE_SECTIONS.md; payloads in PAYLOADS.md "Value, needs and trade").

Currency: wins above replacement from HPM (models/impact.py)
-------------------------------------------------------------
    possessions = minutes x league pace / G                        (G = 48 NBA, 40 WNBA; pace per G minutes)
    PAR = (HPM - REPLACEMENT) x possessions / 100                  points above a replacement player (-2.0 per 100,
                                                                   impact.REPLACEMENT_HPM, the injury and roster
                                                                   models' replacement level)
    WAR = PAR / points per win,  points per win = sigma x sqrt(2 pi)
The game model's margin is Normal(mu, sigma) (models/game.py), so one point of expected margin moves an even
game's win probability by phi(0) / sigma = 1 / (sigma sqrt(2 pi)); points per win is its inverse (NBA sigma
12.41: 31.1 points; WNBA 12.02: 30.1). Rates: HPM (per 100 possessions, above average) and PAR per game.

Positions
---------
ESPN lists only G, F and C, so PG / SG / SF / PF cannot be told apart. Players are grouped as guards (G),
wings and bigs: C is a big; an F is a big when his box profile is closer to the centres' than to the guards':
    score = z(oreb100 + dreb100) + z(blk100) + z(rim_freq) - z(tpar) - z(ast100)   (z over qualified players)
and F with score above the midpoint of the guards' and centres' mean scores is a big (150+ minutes; fewer: a wing).

Rest-of-season projection (team needs and the trade simulator)
-------------------------------------------------------------
    rate = (HPM_this x min_this + prior x K) / (min_this + K)
prior = last season's HPM plus the aging step (impact.projections "hpm_next", the roster prior's value in
models/ratings.py; the season before for a player who missed last season), K = PRIOR_MIN (1,000 minutes); a player
with no earlier season is pulled towards replacement (-2.0) with K = PRIOR_MIN_NEW (250, the projections' pseudo-
minutes). Offence and defence likewise. Minutes per game are impact.projections "min" (recent games weighted 0.5^(k/12)).

Depth chart (position-aware)
---------------------------
A team's rotation hands its players' projected minutes (each capped at MAX_SHARE x G) out to the players with
the most minutes first until five players' worth (5G) is used; any shortfall is played at replacement level.
    team value = sum(rate x minutes) / G + REPLACEMENT x fill / G       (net points per 100, impact.roster_impact)
A trade (`apply_moves`): the outgoing players' minutes open up in their position; each incoming player takes his
projected minutes, first from open minutes at his position, then from his new team's lowest-rated minutes at his
position (replacement fill first when it is lower), then at the neighbouring positions; open minutes left over go
to the team's best remaining players at that position, each at most EXTRA_SHARE x G (12 NBA, 10 WNBA) more and up to
the cap ("next man up"), then the neighbouring positions, then replacement. The change in team value is the change in net rating for the rest of the season.

Wins and odds: per-team sensitivity curves from the season simulation (season_sim.sensitivity: the whole season
re-run with that team shifted by -6 .. +6 net points per 100); between grid points linear interpolation; beyond
the grid the edge value. Without a simulation (offseason) wins come from the conversion above.
"""
from __future__ import annotations

import logging
import math
import statistics
from bisect import bisect_left, bisect_right
from typing import Any, Iterable

from oddsmarkets.basketball import analytics as an

logger = logging.getLogger(__name__)

VERSION = 1
REPLACEMENT = -2.0                    # impact.REPLACEMENT_HPM
PRIOR_MIN = 1000.0                    # minutes of last season's projection in the rest-of-season rate
PRIOR_MIN_NEW = 250.0                 # ... of replacement level for a player with no earlier season (impact.PRIOR_MINUTES)
MAX_SHARE = 0.8                       # a player's minutes cap per game: 38.4 (NBA), 32 (WNBA)
EXTRA_SHARE = 0.25                    # a "next man up" takes at most this share of a game more: 12 (NBA), 10 (WNBA)
ROLE_MIN = 150.0                      # minutes before a forward's box profile decides wing or big
ROLES = ("G", "W", "B")
ROLE_LABELS = {"G": "Guards", "W": "Wings", "B": "Bigs"}
ROLE_ONE = {"G": "guard", "W": "wing", "B": "big"}
ADJACENT = {"G": ("W", "B"), "W": ("G", "B"), "B": ("W", "G")}
ROLE_FEATURES = (("reb100", 1.0), ("blk100", 1.0), ("rim_freq", 1.0), ("tpar", -1.0), ("ast100", -1.0))
UNITS = (("off", "Offence"), ("def", "Defence"), ("start", "Starting five"), ("bench", "Bench"))
GRADE_CUTS = ((80, "A"), (60, "B"), (40, "C"), (20, "D"), (-1, "F"))
N_CANDIDATES = 5
EXTRA_ATTAINABLE = 3                  # beyond the top five, up to three more that the data marks attainable
MIN_CAND_MPG = 10.0
STARTER_MPG = 28.0
BENCH_MPG = 24.0
OUT_OF_CONTENTION = 0.15              # seller's playoff probability below this: "out of contention"
BEST_N = 10
RECENT_DAYS = 30                      # a player on no ESPN roster counts on his last team only if he played this recently
WHY_METRICS = (("ts_add", "scoring efficiency"), ("pts100", "scoring volume"), ("ast100", "playmaking"),
               ("tov100", "ball security"), ("oreb100", "offensive rebounding"), ("dreb100", "defensive rebounding"),
               ("stl100", "steals"), ("blk100", "rim protection"), ("pox100", "shot-making"), ("tpar", "three-point volume"))
NOTE = ("Model suggestions based on on-field value (HPM); not considering the salary cap, contracts, fit or availability "
        "unless shown. Cap not checked: there is no free, legitimate salary source we use for the NBA or WNBA.")


# ---------------------------------------------------------------------------------------------- basics

def game_minutes(league: str) -> float:
    return 40.0 if str(league).lower() == "wnba" else 48.0


def points_per_win(league: str, sigma: float | None = None) -> float:
    """sigma x sqrt(2 pi), sigma the game model's fitted margin sd (models/game.params)."""
    if sigma is None:
        try:
            from oddsmarkets.basketball.models import game as GM
            sigma = float(GM.params(league).get("sigma") or 12.0)
        except Exception:                          # noqa: BLE001
            sigma = 12.0
    return float(sigma) * math.sqrt(2.0 * math.pi)


def season_games(league: str, season: int) -> int:
    try:
        from oddsmarkets.basketball.models.config import fmt
        return int(fmt(league, season).games)
    except Exception:                              # noqa: BLE001
        return 44 if str(league).lower() == "wnba" else 82


def _f(v: Any) -> float | None:
    return an.fnum(v)


def _r(v: Any, nd: int = 2) -> float | None:
    v = _f(v)
    return None if v is None else round(v, nd)


def place(sorted_vals: list[float], v: float, lower: bool = False) -> int:
    """Mid-rank percentile of v against a sorted reference (100 = best), the catalogues' convention."""
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


def war_of(rate: float, minutes: float, pace: float, league: str, ppw: float) -> float:
    """WAR of `minutes` played at HPM `rate`."""
    poss = minutes * pace / game_minutes(league)
    return (rate - REPLACEMENT) * poss / 100.0 / ppw


# ---------------------------------------------------------------------------------------------- positions

def _feature(vals: dict, key: str) -> float | None:
    if key == "reb100":
        a, b = _f(vals.get("oreb100")), _f(vals.get("dreb100"))
        return None if a is None or b is None else a + b
    return _f(vals.get(key))


def classify_roles(cat: dict | None) -> tuple[dict[str, str], dict]:
    """({pid: "G"|"W"|"B"}, {"threshold", "features"}) for a season catalogue (players.json)."""
    P = ((cat or {}).get("players")) or {}
    q = [r for r in P.values() if r.get("qualified")]
    stats = {}
    for k, _s in ROLE_FEATURES:
        xs = [x for x in (_feature(r.get("values") or {}, k) for r in q) if x is not None]
        if len(xs) >= 10:
            sd = statistics.pstdev(xs)
            stats[k] = (statistics.fmean(xs), sd if sd > 0 else 1.0)

    def score(r):
        v = r.get("values") or {}
        s, n = 0.0, 0
        for k, sign in ROLE_FEATURES:
            x = _feature(v, k)
            if k in stats and x is not None:
                s += sign * (x - stats[k][0]) / stats[k][1]
                n += 1
        return s if n else None

    gs = [x for x in (score(r) for r in q if r.get("pool") == "G") if x is not None]
    cs = [x for x in (score(r) for r in q if r.get("pool") == "C") if x is not None]
    thr = (statistics.fmean(gs) + statistics.fmean(cs)) / 2.0 if gs and cs else None
    out = {}
    for pid, r in P.items():
        pool = str(r.get("pool") or r.get("pos") or "F")[:1].upper()
        if pool == "G":
            out[pid] = "G"
        elif pool == "C":
            out[pid] = "B"
        else:
            s = score(r) if thr is not None and (_f(r.get("min")) or 0) >= ROLE_MIN else None
            out[pid] = "B" if s is not None and s > thr else "W"
    return out, {"threshold": None if thr is None else round(thr, 3), "features": [k for k, _ in ROLE_FEATURES if k in stats]}


def role_from_pos(pos: Any) -> str:
    p = str(pos or "F").upper()
    return "G" if p.startswith(("G", "PG", "SG")) else "B" if p.startswith("C") else "W"


# ---------------------------------------------------------------------------------------------- season value

def _why(r: dict) -> list:
    """The player's box strengths: up to three of WHY_METRICS at the 80th league percentile or better."""
    pct = r.get("pct") or {}
    hits = sorted(((pct.get(k), lab) for k, lab in WHY_METRICS if pct.get(k) is not None and pct.get(k) >= 80), reverse=True)
    return [[lab, int(p)] for p, lab in hits[:3]]


def season_value(league: str, season: int, cat: dict | None, prev_cat: dict | None = None, pace: float | None = None,
                 phase: str | None = None, ppw: float | None = None, updated_at: str | None = None) -> dict:
    """value.json: every player of the season catalogue with HPM, his WAR, PAR per game, percentiles, the change
    from last season and his position group; `best` lists the top BEST_N qualified players per position."""
    league = str(league).lower()
    ppw = ppw or points_per_win(league)
    G = game_minutes(league)
    if pace is None:
        from oddsmarkets.basketball.models.config import GAME_DEFAULTS
        pace = float(GAME_DEFAULTS[league]["pace"])
    roles, rinfo = classify_roles(cat)
    P = ((cat or {}).get("players")) or {}
    PP = ((prev_cat or {}).get("players")) or {}
    rows: dict[str, dict] = {}
    for pid, r in P.items():
        v = r.get("values") or {}
        h, mins = _f(v.get("hpm")), _f(r.get("min")) or 0.0
        if h is None or mins <= 0:
            continue
        poss = mins * pace / G
        par = (h - REPLACEMENT) * poss / 100.0
        gp = int(r.get("gp") or 0)
        pv = (PP.get(pid) or {})
        pvv = pv.get("values") or {}
        ph, pmin = _f(pvv.get("hpm")), _f(pv.get("min")) or 0.0
        prev_war = (ph - REPLACEMENT) * pmin * pace / G / 100.0 / ppw if ph is not None and pmin > 0 else None
        rows[pid] = {"id": pid, "name": r.get("name"), "team": r.get("team"), "pos": r.get("pos"), "role": roles.get(pid, "W"),
                     "age": _r(r.get("age"), 1), "gp": gp, "min": int(round(mins)), "hpm": h, "o": _f(v.get("hpm_o")),
                     "d": _f(v.get("hpm_d")), "se": _f(v.get("hpm_se")), "par": par, "war": par / ppw,
                     "par_g": par / gp if gp else None, "q": bool(r.get("qualified")), "prev_war": prev_war,
                     "d_hpm": (h - ph) if ph is not None and pmin > 0 else None, "why": _why(r)}
    ref = sorted(x["war"] for x in rows.values() if x["q"])
    refr = {k: sorted(x["war"] for x in rows.values() if x["q"] and x["role"] == k) for k in ROLES}
    for x in rows.values():
        x["pct"] = place(ref, x["war"]) if len(ref) >= 2 else None
        rr = refr.get(x["role"]) or []
        x["pct_role"] = place(rr, x["war"]) if len(rr) >= 3 else None
    best = {}
    for k in ROLES:
        cand = sorted((x for x in rows.values() if x["q"] and x["role"] == k), key=lambda x: -x["war"])[:BEST_N]
        best[k] = [x["id"] for x in cand]
    cols = ["id", "name", "team", "pos", "role", "age", "gp", "min", "hpm", "o", "d", "se", "par", "war", "par_g", "pct",
            "pct_role", "q", "prev_war", "d_hpm", "why"]
    nd = {"hpm": 2, "o": 2, "d": 2, "se": 2, "par": 1, "war": 2, "par_g": 2, "prev_war": 2, "d_hpm": 2}
    out_rows = []
    for x in sorted(rows.values(), key=lambda x: -x["war"]):
        out_rows.append([(_r(x[c], nd[c]) if c in nd else (1 if x[c] else 0) if c == "q" else x[c]) for c in cols])
    return {"ok": True, "league": league, "season": int(season), "updated_at": updated_at or an.now(), "phase": phase,
            "version": VERSION, "currency": {"unit": "WAR", "points_per_win": round(ppw, 2), "replacement": REPLACEMENT,
                                             "pace": round(float(pace), 2), "game_minutes": G, "games": season_games(league, season)},
            "roles": dict(ROLE_LABELS), "role_rule": rinfo, "cols": cols, "rows": out_rows, "best": best,
            "n_qualified": len(ref), "min_floor": (cat or {}).get("min_floor"),
            "note": "WAR = (HPM + 2.0) x possessions / 100 / points per win; percentiles against qualified players."}


# ---------------------------------------------------------------------------------------------- projection

def player_projection(cur: dict | None, prior: list | tuple | None, prev_row: dict | None, proj_min: float | None,
                      age: float | None) -> dict:
    """Rest-of-season rate and minutes for one player. `cur`: this season's catalogue row (or None); `prior`:
    [hpm_next, minutes] from last season's impact model (ratings._last_season_values); `prev_row`: last season's
    catalogue row (offence / defence split); `proj_min`: impact.projections minutes per game."""
    from oddsmarkets.basketball.models.impact import aging_delta
    cv = (cur or {}).get("values") or {}
    ch, cmin = _f(cv.get("hpm")), _f((cur or {}).get("min")) or 0.0
    co, cd = _f(cv.get("hpm_o")), _f(cv.get("hpm_d"))
    if prior and prior[0] is not None:
        pr = float(prior[0])
        pv = (prev_row or {}).get("values") or {}
        po, pd_, pt = _f(pv.get("hpm_o")), _f(pv.get("hpm_d")), _f(pv.get("hpm"))
        if po is not None and pd_ is not None and pt is not None:
            adj = (pr - pt) / 2.0
            pro, prd = po + adj, pd_ + adj
        else:
            pro, prd = pr / 2.0, pr / 2.0
        basis = "b" if ch is not None and cmin > 0 else "p"
    else:
        pr, pro, prd = REPLACEMENT, REPLACEMENT / 2.0, REPLACEMENT / 2.0
        basis = "c" if ch is not None and cmin > 0 else "r"
    if ch is not None and cmin > 0:
        w = cmin / (cmin + (PRIOR_MIN if basis == "b" else PRIOR_MIN_NEW))
        rate = w * ch + (1 - w) * pr
        o = w * (co if co is not None else ch / 2.0) + (1 - w) * pro
        d = w * (cd if cd is not None else ch / 2.0) + (1 - w) * prd
    else:
        rate, o, d = pr, pro, prd
    mpg = proj_min
    if mpg is None:
        mpg = (_f((cur or {}).get("min")) or 0.0) / max(1, int((cur or {}).get("gp") or 0)) if cur and cur.get("gp") else \
            (float(prior[1]) if prior and len(prior) > 1 and prior[1] is not None else 0.0)
    nxt = rate + aging_delta(age)
    return {"rate": rate, "o": o, "d": d, "mpg": max(0.0, float(mpg or 0.0)), "next": nxt, "basis": basis}


def current_rosters(store: dict, box_last: dict[str, tuple[str, str]] | None = None, since: str | None = None) -> dict[str, str]:
    """{pid: team} today: the store's `meta.rosters` (ESPN team rosters, refreshed by bb_fetch.py), plus anyone on
    no roster who played this season (on or after `since`, when given) at his latest game's team."""
    out: dict[str, str] = {}
    for tid, pids in (((store or {}).get("meta") or {}).get("rosters") or {}).items():
        for p in pids or []:
            out[str(p)] = str(tid)
    for pid, (team, d) in (box_last or {}).items():
        if since is None or str(d) >= since:
            out.setdefault(str(pid), str(team))
    return out


def projections(ctx, cat: dict | None, prev_cat: dict | None, roles_cur: dict | None = None,
                roles_prev: dict | None = None) -> dict[str, dict]:
    """{pid: {"id","name","team","pos","role","age","mpg","rate","o","d","next","basis"}} for every player on a
    current roster (the trade simulator's and the team page's inputs)."""
    from oddsmarkets.basketball.models import ratings as RT
    league, season = ctx.league, ctx.season
    prior: dict[str, list] = {}
    try:
        prior = dict(RT._last_season_values(league, season - 1) or {})
        if an.load_store(league, season - 2).get("games"):
            older = RT._last_season_values(league, season - 2) or {}
            prior = {**older, **prior}
    except Exception as exc:                       # noqa: BLE001
        logger.warning("%s %s value prior failed: %s", league, season, exc)
    box_last: dict[str, tuple[str, str]] = {}
    bx = ctx.box
    if bx is not None and not bx.empty and "sec" in bx:
        played = bx[bx["sec"] > 0].sort_values("date")
        for pid, team, d in zip(played["player_id"], played["team"], played["date"]):
            box_last[str(pid)] = (str(team), str(d))
    teams = set(ctx.teams)
    from datetime import timedelta
    since = str(ctx.today - timedelta(days=RECENT_DAYS)) if (((ctx.store or {}).get("meta") or {}).get("rosters")) else None
    roster = {p: t for p, t in current_rosters(ctx.store, box_last, since).items() if t in teams}
    P = ((cat or {}).get("players")) or {}
    PP = ((prev_cat or {}).get("players")) or {}
    imp = ((ctx.impact or {}).get("players")) or {}
    players = ctx.players or {}
    roles_cur = roles_cur if roles_cur is not None else classify_roles(cat)[0]
    roles_prev = roles_prev if roles_prev is not None else classify_roles(prev_cat)[0]
    out = {}
    for pid, team in roster.items():
        info = players.get(pid) or {}
        cur = P.get(pid)
        pj = (imp.get(pid) or {}).get("proj") or {}
        age = None
        if info.get("dob"):
            from oddsmarkets.basketball.models.impact import _age
            age = _age(info.get("dob"), str(ctx.today))
        elif cur and cur.get("age") is not None:
            age = _f(cur.get("age"))
        pr = player_projection(cur, prior.get(pid), PP.get(pid), _f(pj.get("min")), age)
        if cur and (_f(cur.get("min")) or 0) >= ROLE_MIN:
            role = roles_cur.get(pid)
        elif pid in roles_prev and (_f((PP.get(pid) or {}).get("min")) or 0) >= ROLE_MIN:
            role = roles_prev.get(pid)
        else:
            role = None
        role = role or roles_cur.get(pid) or role_from_pos(info.get("pos") or (cur or {}).get("pos"))
        out[pid] = {"id": pid, "name": info.get("name") or (cur or {}).get("name") or pid, "team": team,
                    "pos": info.get("pos") or (cur or {}).get("pos"), "role": role, "age": age, **pr}
    return out


# ---------------------------------------------------------------------------------------------- depth chart

def params_for(league: str, pace: float, ppw: float | None = None) -> dict:
    G = game_minutes(league)
    return {"league": str(league).lower(), "G": G, "cap": 5.0 * G, "max_min": MAX_SHARE * G, "extra": EXTRA_SHARE * G, "repl": REPLACEMENT,
            "pace": float(pace), "ppw": float(ppw or points_per_win(league))}


def baseline_minutes(team: list[dict], prm: dict) -> dict[str, float]:
    """{pid: minutes per game} for a roster: projected minutes capped at max_min, handed out most minutes first
    until cap (five players' worth) is used (ratings._allocate_minutes)."""
    left = prm["cap"]
    out = {}
    for p in sorted(team, key=lambda p: (-min(float(p.get("mpg") or 0.0), prm["max_min"]), str(p["id"]))):
        take = max(0.0, min(min(float(p.get("mpg") or 0.0), prm["max_min"]), left))
        out[p["id"]] = take
        left -= take
    return out


def team_value(team: list[dict], minutes: dict[str, float], prm: dict) -> dict:
    """Net, offence and defence per 100 of a rotation (impact.roster_impact with replacement fill)."""
    G = prm["G"]
    by = {p["id"]: p for p in team}
    used = sum(minutes.values())
    fill = max(0.0, prm["cap"] - used)
    net = sum(by[k]["rate"] * m for k, m in minutes.items() if k in by) / G + prm["repl"] * fill / G
    off = sum(by[k]["o"] * m for k, m in minutes.items() if k in by) / G + prm["repl"] / 2.0 * fill / G
    dfn = sum(by[k]["d"] * m for k, m in minutes.items() if k in by) / G + prm["repl"] / 2.0 * fill / G
    return {"net": net, "off": off, "def": dfn, "fill": fill}


def apply_moves(team: list[dict], out_ids: Iterable[str], incoming: Iterable[dict], prm: dict) -> dict:
    """The team after `out_ids` leave and `incoming` (player dicts with id, role, mpg, rate, o, d) arrive.
    Returns {"before", "after", "delta" (net), "delta_off", "delta_def", "minutes" (after), "displaced":
    [[pid, minutes]], "absorbed": [[pid, minutes]], "fill_before", "fill_after"}. The same rules as the trade page
    (docs/hardwood/assets/js/trade.js `applyMoves`)."""
    out_ids = {str(x) for x in out_ids}
    incoming = [p for p in incoming if str(p["id"]) not in {str(t["id"]) for t in team}]
    base = baseline_minutes(team, prm)
    before = team_value(team, base, prm)
    roster = [p for p in team if str(p["id"]) not in out_ids] + list(incoming)
    by = {p["id"]: p for p in roster}
    m = {p["id"]: base.get(p["id"], 0.0) for p in roster if p not in incoming}
    open_ = {k: 0.0 for k in ROLES}
    for p in team:
        if str(p["id"]) in out_ids:
            open_[p.get("role") or "W"] += base.get(p["id"], 0.0)
    fill = max(0.0, prm["cap"] - sum(base.values()))
    displaced: dict[str, float] = {}
    absorbed: dict[str, float] = {}
    for p in sorted(incoming, key=lambda p: (-float(p["rate"]), str(p["id"]))):
        need = min(float(p.get("mpg") or 0.0), prm["max_min"])
        role = p.get("role") or "W"
        take = min(need, open_[role])
        open_[role] -= take
        got = take
        need -= take
        for rr in (role,) + ADJACENT[role]:
            if need <= 1e-9:
                break
            # the lowest-rated minutes at this position, replacement fill among them (at the team's own position only)
            pool = sorted([(float(by[k]["rate"]), str(k)) for k in m if k in by and by[k] is not p and (by[k].get("role") or "W") == rr
                           and m[k] > 1e-9 and by[k] not in incoming], key=lambda x: (x[0], x[1]))
            if rr == role and fill > 1e-9:
                pool = sorted(pool + [(prm["repl"], "")], key=lambda x: (x[0], x[1]))
            for rate, k in pool:
                if need <= 1e-9:
                    break
                if rate >= float(p["rate"]) and k:
                    break                          # nobody worse left to displace at this position
                if k == "":
                    t = min(need, fill)
                    fill -= t
                else:
                    t = min(need, m[k])
                    m[k] -= t
                    displaced[k] = displaced.get(k, 0.0) + t
                need -= t
                got += t
        m[p["id"]] = got
    for role in ROLES:
        left = open_[role]
        for rr in (role,) + ADJACENT[role]:
            if left <= 1e-9:
                break
            for k in sorted([k for k in m if (by[k].get("role") or "W") == rr], key=lambda k: (-float(by[k]["rate"]), str(k))):
                if left <= 1e-9:
                    break
                spare = min(prm["max_min"] - m[k], prm["extra"] - absorbed.get(k, 0.0))
                if spare <= 1e-9:
                    continue
                t = min(spare, left)
                m[k] += t
                absorbed[k] = absorbed.get(k, 0.0) + t
                left -= t
        fill += max(0.0, left)
    after = team_value(roster, m, prm)
    return {"before": before["net"], "after": after["net"], "delta": after["net"] - before["net"],
            "delta_off": after["off"] - before["off"], "delta_def": after["def"] - before["def"],
            "minutes": m, "displaced": sorted([[k, v] for k, v in displaced.items() if v > 0.05], key=lambda x: -x[1]),
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


DECREASING = ("p_top4",)


def monotone(shifts: list[float], ys: list[float | None], decreasing: bool = False) -> list[float | None]:
    """Make a curve monotone outward from the zero shift (simulation noise can wiggle a probability)."""
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
    """Change in `key` for team `tid` at a rating shift, read off its sensitivity curve (value at the shift minus
    value at zero)."""
    c = ((curves or {}).get("teams") or {}).get(tid) or {}
    ys = c.get(key)
    xs = (curves or {}).get("shifts") or []
    if not ys or not xs:
        return None
    a, b = interp(xs, ys, shift), interp(xs, ys, 0.0)
    return None if a is None or b is None else a - b


SENS_TTL_HOURS = 6.0                  # a cached run is reused this long while only results and ratings move


def sensitivity_curves(ctx, n: int | None = None) -> dict | None:
    """season_sim.sensitivity for the context's season, monotone-smoothed. Cached on the simulation's inputs
    (ratings, standings, games left); a run on the same teams, grid and stage (games left or not) is reused for up to
    SENS_TTL_HOURS when only results or ratings have moved, so a day of games costs at most a few re-runs (the page
    adds the curves' differences to the fresh baseline, and a day's results barely move a curve's shape)."""
    import hashlib
    import json
    import time as _time
    from oddsmarkets.basketball.models import _io
    from oddsmarkets.basketball.models import season_sim as SS
    sim = ctx.sim
    if not sim or not sim.get("teams"):
        return None
    n = int(n or SS.SENS_SIMS)
    key_src = [VERSION, ctx.league, ctx.season, n, list(SS.SENS_SHIFTS),
               sorted((t, round(float(r.get("rating") or 0), 3), round(float(r.get("rating_se") or 0), 3),
                       (r.get("current") or {}).get("w"), (r.get("current") or {}).get("l"),
                       (r.get("current") or {}).get("remaining")) for t, r in sim["teams"].items()),
               sim.get("remaining_games")]
    key = hashlib.sha1(json.dumps(key_src, default=str).encode()).hexdigest()
    coarse = hashlib.sha1(json.dumps([VERSION, ctx.league, ctx.season, n, list(SS.SENS_SHIFTS), sorted(sim["teams"]),
                                      bool(sim.get("remaining_games"))]).encode()).hexdigest()
    path = an.cache_root() / "value" / f"sensitivity_{ctx.league}_{ctx.season}.json"
    c = an.read_json(path) if path.exists() else None
    fresh = isinstance(c, dict) and (c.get("key") == key or (c.get("coarse") == coarse and
                                                            _time.time() - float(c.get("at") or 0) < SENS_TTL_HOURS * 3600))
    if fresh:
        res = c.get("result")
    else:
        res = SS.sensitivity(ctx.league, ctx.season, n=n, seed=ctx.season + 1,
                             state={"store": ctx.member_store, "ratings": ctx.ratings})
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"key": key, "coarse": coarse, "at": _time.time(), "result": _io.clean(res, 6)},
                                       separators=(",", ":")), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass
    if not res or not res.get("ok"):
        return res
    shifts = res["shifts"]
    for t, c in res["teams"].items():
        for k in list(c):
            c[k] = monotone(shifts, c[k], decreasing=k in DECREASING)
    return res


# ---------------------------------------------------------------------------------------------- team grades and needs

def team_lists(proj: dict[str, dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in proj.values():
        out.setdefault(p["team"], []).append(p)
    return out


def unit_values(team: list[dict], prm: dict, games: int) -> dict[str, float]:
    """Projected WAR over `games` games by position group and unit for a rotation."""
    m = baseline_minutes(team, prm)
    G, pace, ppw = prm["G"], prm["pace"], prm["ppw"]
    conv = pace / 100.0 * games / ppw / G      # (rate - repl) x minutes -> WAR over the games
    by = {p["id"]: p for p in team}
    out = {k: 0.0 for k in ROLES}
    out.update({"off": 0.0, "def": 0.0, "start": 0.0, "bench": 0.0})
    order = sorted(m, key=lambda k: (-m[k], k))
    starters = set(order[:5])
    for k, mins in m.items():
        p = by[k]
        v = (p["rate"] - prm["repl"]) * mins * conv
        out[p.get("role") or "W"] += v
        out["off"] += (p["o"] - prm["repl"] / 2.0) * mins * conv
        out["def"] += (p["d"] - prm["repl"] / 2.0) * mins * conv
        out["start" if k in starters else "bench"] += v
    return out


def grade_teams(lists: dict[str, list[dict]], prm: dict, games: int) -> dict[str, dict]:
    """{tid: {key: {"value","pct","grade","rank","n"}}} for the positions and units, against the league's teams."""
    vals = {t: unit_values(ps, prm, games) for t, ps in lists.items()}
    keys = list(ROLES) + [k for k, _ in UNITS]
    out = {t: {} for t in vals}
    for k in keys:
        ref = sorted(v[k] for v in vals.values())
        for t, v in vals.items():
            pct = place(ref, v[k])
            rank = 1 + len(ref) - bisect_right(ref, v[k])
            out[t][k] = {"value": v[k], "pct": pct, "grade": grade(pct), "rank": rank, "n": len(ref)}
    return out


def _label(k: str) -> str:
    return ROLE_LABELS.get(k) or dict(UNITS).get(k) or k


def _evidence(k: str, g: dict, team: list[dict], prm: dict, weak: bool) -> str:
    m = baseline_minutes(team, prm)
    rot = [p for p in team if m.get(p["id"], 0) >= 1.0]
    if k in ROLES:
        grp = [p for p in rot if (p.get("role") or "W") == k]
    elif k == "start":
        grp = sorted(rot, key=lambda p: -m[p["id"]])[:5]
    elif k == "bench":
        grp = sorted(rot, key=lambda p: -m[p["id"]])[5:]
    else:
        grp = rot
    comp = "o" if k == "off" else "d" if k == "def" else "rate"
    head = f"{g['value']:.1f} projected WAR over a full season, {an_ordinal(g['rank'])} of {g['n']}"
    if not grp:
        return head + "; no rotation minutes here (played at replacement level)"
    grp = sorted(grp, key=lambda p: (p[comp], -m[p["id"]])) if weak else sorted(grp, key=lambda p: (-p[comp], -m[p["id"]]))
    p = grp[0]
    what = "offence" if comp == "o" else "defence" if comp == "d" else "HPM"
    lead = "weakest" if weak else "led by"
    return f"{head}; {lead} {p['name']} ({p[comp]:+.1f} {what} per 100, {m[p['id']]:.0f} min)"


def an_ordinal(n: int) -> str:
    n = int(n)
    t = n % 100
    return f"{n}{'th' if 11 <= t <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def candidates(tid: str, key: str, lists: dict[str, list[dict]], prm: dict, games_left: dict[str, int], curves: dict | None,
               sim_teams: dict | None, injuries: dict[str, dict] | None = None, n: int = N_CANDIDATES) -> list[dict]:
    """Ranked trade targets for team `tid`'s weakness `key`: players on other teams who would add the most at that
    position (or unit), each added to `tid`'s depth chart with nobody going back. Feasibility hints come from the data
    only: the seller's playoff odds, what losing him costs the seller (depth), age, the injury report."""
    from oddsmarkets.basketball.models.impact import aging_delta
    team = lists.get(tid) or []
    comp = "delta_off" if key == "off" else "delta_def" if key == "def" else "delta"
    pool = []
    for t, ps in lists.items():
        if t == tid:
            continue
        for p in ps:
            if float(p.get("mpg") or 0) < MIN_CAND_MPG or p.get("basis") == "r":
                continue
            if key in ROLES and (p.get("role") or "W") != key:
                continue
            if key == "start" and float(p["mpg"]) < STARTER_MPG:
                continue
            if key == "bench" and float(p["mpg"]) >= BENCH_MPG:
                continue
            pool.append(p)
    scored = []
    for p in pool:
        res = apply_moves(team, [], [p], prm)
        if res[comp] <= 0.05:
            continue
        scored.append((res[comp], res["delta"], p, res))
    scored.sort(key=lambda x: (-x[0], -x[1], str(x[2]["id"])))
    top_two = {}
    for t, ps in lists.items():
        mm = baseline_minutes(ps, prm)
        top_two[t] = {q["id"] for q in sorted(ps, key=lambda q: (-(q["rate"] - prm["repl"]) * mm.get(q["id"], 0.0), q["id"]))[:2]}
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
            hints.append(f"seller has depth at the position: losing the player moves them {cost:+.1f} per 100 (adds {tot:+.1f} here)")
        franchise = p["id"] in top_two.get(seller, set())
        if franchise:
            hints.append("one of the seller's two most valuable players")
        if p.get("age") and p["age"] >= 31:
            hints.append(f"age {p['age']:.0f}: projected {aging_delta(p['age']):+.1f} per 100 next season")
        inj = (injuries or {}).get(p["id"])
        if inj:
            hints.append(f"injury report: {inj}")
        attainable = (out_of or depth) and not franchise
        if len(out) >= n:
            if not attainable:
                continue
            n_extra += 1
        wins = curve_delta(curves, tid, "exp_w", tot) if curves else None
        if wins is None:
            wins = tot * prm["pace"] / 100.0 * games_left.get(tid, 0) / prm["ppw"]
        disp = [[k, round(v, 1)] for k, v in res["displaced"][:3]]
        out.append({"id": p["id"], "name": p["name"], "team": seller, "role": p.get("role"), "age": _r(p.get("age"), 1),
                    "mpg": _r(p["mpg"], 1), "rate": _r(p["rate"], 2), "gain": _r(gain, 2), "gain_net": _r(tot, 2),
                    "wins": _r(wins, 2), "d_playoffs": _r(curve_delta(curves, tid, "p_playoffs", tot), 4) if curves else None,
                    "d_title": _r(curve_delta(curves, tid, "p_title", tot), 4) if curves else None,
                    "seller_cost": _r(cost, 2), "displaces": disp, "hints": hints, "attainable": bool(attainable),
                    "war_rest": _r(war_of(p["rate"], min(p["mpg"], prm["max_min"]) * games_left.get(tid, 0), prm["pace"],
                                          prm["league"], prm["ppw"]), 2)})
    return out


def needs_payloads(league: str, season: int, proj: dict[str, dict], prm: dict, games_left: dict[str, int],
                   curves: dict | None, sim_teams: dict | None, injuries: dict[str, dict] | None,
                   phase: str | None = None, updated_at: str | None = None) -> dict[str, dict]:
    """{tid: needs/<tid>.json}: grades, top three strengths and weaknesses with evidence, and trade targets."""
    lists = team_lists(proj)
    games = season_games(league, season)
    grades = grade_teams(lists, prm, games)
    out = {}
    for tid, team in lists.items():
        g = grades[tid]
        keys = list(ROLES) + [k for k, _ in UNITS]
        order = sorted(keys, key=lambda k: (-g[k]["pct"], keys.index(k)))
        strengths = order[:3]
        weaknesses = [k for k in sorted(keys, key=lambda k: (g[k]["pct"], keys.index(k))) if k not in strengths][:3]
        m = baseline_minutes(team, prm)
        depth = sorted(team, key=lambda p: (-m.get(p["id"], 0), p["id"]))
        out[tid] = {
            "ok": True, "league": league, "season": int(season), "team": tid, "updated_at": updated_at or an.now(),
            "phase": phase, "basis": "projection",
            "grades": [{"key": k, "label": _label(k), "value": _r(g[k]["value"], 2), "pct": g[k]["pct"], "grade": g[k]["grade"],
                        "rank": g[k]["rank"], "n": g[k]["n"]} for k in keys],
            "strengths": [{"key": k, "label": _label(k), "grade": g[k]["grade"], "pct": g[k]["pct"], "relative": g[k]["pct"] < 50,
                           "evidence": _evidence(k, g[k], team, prm, False)} for k in strengths],
            "weaknesses": [{"key": k, "label": _label(k), "grade": g[k]["grade"], "pct": g[k]["pct"], "relative": g[k]["pct"] >= 50,
                            "evidence": _evidence(k, g[k], team, prm, True),
                            "targets": candidates(tid, k, lists, prm, games_left, curves, sim_teams, injuries)} for k in weaknesses],
            "depth": [{"id": p["id"], "name": p["name"], "role": p.get("role"), "pos": p.get("pos"), "age": _r(p.get("age"), 1),
                       "mpg": _r(m.get(p["id"], 0.0), 1), "rate": _r(p["rate"], 2), "o": _r(p["o"], 2), "d": _r(p["d"], 2),
                       "basis": p.get("basis")} for p in depth],
            "fill": _r(team_value(team, m, prm)["fill"], 1),
            "games": games, "games_left": games_left.get(tid),
            "free_agents": "Not identified: ESPN's rosters list signed players only.",
            "note": NOTE}
    return out


def trade_payload(league: str, season: int, proj: dict[str, dict], prm: dict, sim: dict | None, curves: dict | None,
                  ratings: dict | None, injuries: dict[str, dict] | None, phase: str | None = None,
                  updated_at: str | None = None) -> dict:
    """trade.json: the players (rest-of-season rate, minutes, position, age, next season's rate), each team's
    baseline odds and sensitivity curves, and the constants the page's depth chart needs."""
    cols = ["id", "name", "team", "pos", "role", "age", "mpg", "rate", "o", "d", "next", "basis", "inj"]
    rows = []
    for p in sorted(proj.values(), key=lambda p: (p["team"], -float(p.get("mpg") or 0), p["id"])):
        rows.append([p["id"], p["name"], p["team"], p.get("pos"), p.get("role"), _r(p.get("age"), 1), _r(p.get("mpg"), 1),
                     _r(p["rate"], 2), _r(p["o"], 2), _r(p["d"], 2), _r(p["next"], 2), p.get("basis"),
                     (injuries or {}).get(p["id"])])
    st = (sim or {}).get("teams") or {}
    rt = ((ratings or {}).get("teams")) or {}
    teams = {}
    games = season_games(league, season)
    for t in sorted({p["team"] for p in proj.values()} | set(st)):
        s = st.get(t) or {}
        cur = s.get("current") or {}
        lot = s.get("p_lottery_pick")
        teams[t] = {"rating": _r((rt.get(t) or {}).get("net"), 2), "se": _r((rt.get(t) or {}).get("se_net"), 2),
                    "w": cur.get("w"), "l": cur.get("l"), "left": cur.get("remaining"),
                    "exp_w": _r(s.get("exp_w"), 2), "p_playoffs": _r(s.get("p_playoffs"), 4), "p_top6": _r(s.get("p_top6"), 4),
                    "p_conf": _r(s.get("p_conf"), 4), "p_title": _r(s.get("p_title"), 4),
                    "p_top4": _r(sum(lot[:4]), 4) if lot else None, "conference": s.get("conference")}
    return {"ok": True, "league": league, "season": int(season), "updated_at": updated_at or an.now(), "phase": phase,
            "version": VERSION, "params": {k: (_r(v, 3) if isinstance(v, (int, float)) else v) for k, v in prm.items()}, "games": games,
            "roles": dict(ROLE_LABELS), "adjacent": {k: list(v) for k, v in ADJACENT.items()},
            "players": {"cols": cols, "rows": rows}, "teams": teams,
            "curves": ({"shifts": curves["shifts"], "keys": curves["keys"], "n_sims": curves.get("n_sims"),
                        "teams": curves["teams"]} if curves and curves.get("ok") else None),
            "sim": {"n_sims": (sim or {}).get("n_sims"), "remaining_games": (sim or {}).get("remaining_games")} if sim else None,
            "note": NOTE}


def injury_map(teams_payload: dict | None) -> dict[str, str]:
    """{pid: "Out (detail)"} from teams.json injuries."""
    out = {}
    for t in (((teams_payload or {}).get("teams")) or {}).values():
        for r in t.get("injuries") or []:
            pid = str(r.get("player") or "")
            if pid and r.get("status"):
                out[pid] = str(r["status"]) + (f" ({r['detail']})" if r.get("detail") else "")
    return out


def build_current(ctx, cat: dict | None, prev_cat: dict | None, teams_payload: dict | None, season_payload: dict | None,
                  curves_sims: int | None = None) -> dict:
    """{"needs": {tid: payload}, "trade": payload, "curves": ...} for the current season."""
    league, season = ctx.league, ctx.season
    pace = _f((season_payload or {}).get("league_pace")) or _f((ctx.ratings or {}).get("league_pace"))
    if pace is None:
        from oddsmarkets.basketball.models.config import GAME_DEFAULTS
        pace = float(GAME_DEFAULTS[league]["pace"])
    prm = params_for(league, pace)
    proj = projections(ctx, cat, prev_cat)
    sim = ctx.sim
    curves = None
    if sim and sim.get("teams"):
        try:
            curves = sensitivity_curves(ctx, curves_sims)
        except Exception as exc:                   # noqa: BLE001
            logger.warning("%s %s sensitivity failed: %s", league, season, exc, exc_info=True)
    games = season_games(league, season)
    st = (sim or {}).get("teams") or {}
    tids = {p["team"] for p in proj.values()}
    if st:
        games_left = {t: int(((st.get(t) or {}).get("current") or {}).get("remaining") or 0) for t in tids}
    else:
        games_left = {t: games for t in tids}          # no simulation (offseason): a full season
    inj = injury_map(teams_payload)
    now = an.now()
    needs = needs_payloads(league, season, proj, prm, games_left, curves if curves and curves.get("ok") else None, st, inj,
                           phase=ctx.phase, updated_at=now)
    trade = trade_payload(league, season, proj, prm, sim, curves, ctx.ratings, inj, phase=ctx.phase, updated_at=now)
    return {"needs": needs, "trade": trade, "n_players": len(proj), "proj": proj, "prm": prm, "games_left": games_left,
            "injuries": injury_pairs(teams_payload)}


def injury_pairs(teams_payload: dict | None) -> dict[str, list]:
    """{pid: [status, detail]} from teams.json injuries (valuation v2 and the fantasy layer)."""
    out = {}
    for t in (((teams_payload or {}).get("teams")) or {}).values():
        for r in t.get("injuries") or []:
            pid = str(r.get("player") or "")
            if pid and r.get("status"):
                out[pid] = [str(r["status"]), r.get("detail")]
    return out
