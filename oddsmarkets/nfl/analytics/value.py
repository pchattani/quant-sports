"""
Player value, best at each position, team strengths and needs, and the trade simulator's payload
(docs/VALUE_SECTIONS.md; payloads in PAYLOADS.md "As built": value.json, needs/<abbr>.json, trade.json).

The currency: points (EPA) above a replacement-level player at the same position
----------------------------------------------------------------------------------
* QB, RB, WR, TE: Gridiron Value (models/player_value.py: the per-season ridge of play EPA on passer, receiver and
  rusher indicators and the defence; coefficient = EPA per play above an average player in the role, already shrunk)
  minus a replacement level per position and role: GVAR = sum over roles of (rate - repl[pos, role]) x plays. The
  replacement rate is the 20th percentile (REPL_Q) of the role rates of the position's players with a minimum sample
  (ROLE_FLOOR), so it is "what a freely available player does in that role". Receivers' raw ridge rates are not
  centred (targeted passes are better than sacks and throwaways, which sit in the intercept), so the replacement
  level is what makes a receiver's value comparable with a passer's.
* K: points over expected (models/kicking.py: 3 x field goals over expected + extra points over the league rate),
  shrunk per attempt with the stabilisation k (60 FGA), minus the 20th percentile kicker's rate, times attempts.
* P: EPA per punt over the league's mean punt, shrunk with k (60 punts), minus the 20th percentile, times punts.
* Defenders (EDGE, DL, LB, CB, S): Splash EPA (the catalogue's def_value: minus the EPA of plays the player made a
  sack, interception, forced fumble, pass defensed or tackle for loss on, shared among the credited players) per
  game, shrunk with k = 6 games toward the position mean, minus the 20th percentile, times games. It is only what
  the box score credits: no coverage, no pressure without a hit, no run fits. At team level splash EPA per game does
  track opponent-adjusted defensive EPA per game (2006-2025, 640 team-seasons: slope 1.29, r 0.71), but individual
  values are used at face value, never scaled up.
* OL: not modelled individually. Public data have no blocking assignments; the only individual measure, on-field
  RAPM, is collinear across the five linemen (MODELS.md 8.2). The team's pass protection (pressure allowed) is graded
  as a unit and labelled as the line, backs and QB together.

Teams: position value = the starters model
------------------------------------------
Each position has STARTERS (SLOTS: QB 1, RB 2, WR 3, TE 2, EDGE 2, DL 2, LB 2, CB 3, S 2, K 1, P 1). Position value =
the sum of the best per-game values above replacement (GVAR per game, each floored at 0: a team can always field a
replacement player) among the players on the current roster (latest nflverse weekly roster: ACT or INA; injured
reserve and the practice squad are out), points per game. An incoming player displaces the weakest starter if he
is better; a departing starter is replaced by the team's own next man up (or a replacement player). Players are
valued at the volume they have shown: a part-timer's per-play rate is never extrapolated to a starter's workload
(an early version did, and a backup with a few big plays came out as a 2.7-point-a-game upgrade). The QB is the
exception: the team-strength model's QB term (EPA per dropback, models/team_strength.py) of the starter, times the
league's dropbacks per game, so a QB change moves the rating exactly as the season simulation's starting-QB
override does.

A trade's effect on a team = k_resp x the change in its position values (points per game), with k_resp = s + b_mr
x 0.77 (game model: the margin's response to a rating change once the market ratings carry it, as for a starting
QB; 0.85 with the committed fit). The season simulation's per-team sensitivity curves (season_sim.sensitivity)
turn it into wins, playoff, division, bye, conference and Super Bowl odds and the mean draft slot.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from oddsmarkets.nfl import analytics as an

logger = logging.getLogger(__name__)

VERSION = "value-1"
POSITIONS = ("QB", "RB", "WR", "TE", "EDGE", "DL", "LB", "CB", "S", "K", "P")
OFFENCE = ("QB", "RB", "WR", "TE")
DEFENCE = ("EDGE", "DL", "LB", "CB", "S")
POS_LABEL = {"QB": "Quarterback", "RB": "Running back", "WR": "Wide receiver", "TE": "Tight end", "EDGE": "Edge rusher",
             "DL": "Interior line", "LB": "Linebacker", "CB": "Cornerback", "S": "Safety", "K": "Kicker", "P": "Punter",
             "OL": "Offensive line"}
SLOTS = {"QB": 1, "RB": 2, "WR": 3, "TE": 2, "EDGE": 2, "DL": 2, "LB": 2, "CB": 3, "S": 2, "K": 1, "P": 1}
REPL_Q = 0.2
ROLE_FLOOR = {"passer": (30.0, 10.0), "receiver": (10.0, 2.0), "rusher": (15.0, 3.0), "all": (20.0, 3.0)}   # (min, per team game)
DEF_K_GAMES = 6.0
K_K, P_K = 60.0, 60.0
FALLBACK_K = 100.0           # without the player_value model: raw EPA credit per opportunity shrunk with 100
GRADE_CUTS = ((80, "A"), (60, "B"), (40, "C"), (20, "D"), (0, "F"))
WHY = {"QB": ["pass", "rush", "epa_db", "cpoe", "composite"], "RB": ["rush", "rec", "ryoe", "ypc"],
       "WR": ["rec", "yacoe", "croe", "target_share"], "TE": ["rec", "yacoe", "croe", "target_share"],
       "K": ["fg_oe", "fg_50", "fg_pct"], "P": ["net", "inside20", "net_oe"],
       "EDGE": ["sacks", "qb_hits", "tfl", "ff"], "DL": ["sacks", "qb_hits", "tfl", "ff"], "LB": ["tfl", "sacks", "pd", "ints"],
       "CB": ["pd", "ints", "ff", "tfl"], "S": ["pd", "ints", "ff", "tfl"]}
UNITS = [  # key, label, teams.json value key, lower is better, the positions behind it
    ("qb", "Quarterback (model QB term)", None, False, ["QB"]),
    ("pass_off", "Pass offence", "off_pass_epa", False, ["QB", "WR", "TE"]),
    ("rush_off", "Rush offence", "off_rush_epa", False, ["RB"]),
    ("protection", "Pass protection (line, backs and QB)", "pressure_allowed", True, []),
    ("pass_def", "Pass defence", "def_pass_epa", True, ["CB", "S", "EDGE"]),
    ("rush_def", "Rush defence", "def_rush_epa", True, ["DL", "LB"]),
    ("pass_rush", "Pass rush", "pressure_rate_def", False, ["EDGE", "DL"]),
    ("st", "Special teams", "st_epa_g", False, ["K", "P"]),
]
LABEL = ("Model suggestions based on on-field value only: they do not consider salary cap, contracts, scheme fit, "
         "medicals or whether a club would trade, unless shown.")
AVAILABLE = ("ACT", "INA")
ON_ROSTER = ("ACT", "INA", "RES", "DEV", "PUP", "SUS", "NWT", "EXE", "RSN", "RSR")


def grade(p: Any) -> str | None:
    p = an.fnum(p)
    if p is None:
        return None
    for cut, g in GRADE_CUTS:
        if p >= cut:
            return g
    return "F"


# ---------------------------------------------------------------------------------------------- reference data

_XW: dict[str, dict] | None = None


def crosswalk() -> dict[str, dict]:
    """{gsis_id: {"pff", "ngs", "status", "team", "pos"}} from the nflverse players release (cached per process)."""
    global _XW
    if _XW is not None:
        return _XW
    out: dict[str, dict] = {}
    try:
        from oddsmarkets.nfl.analytics.context import load_release
        df = load_release("players", None, ["gsis_id", "pff_position", "ngs_position", "status", "latest_team", "position"])
    except Exception as exc:                                     # noqa: BLE001
        logger.info("players crosswalk: %s", exc)
        df = None
    if df is not None and len(df):
        for r in df.to_dict("records"):
            pid = an.sid(r.get("gsis_id"))
            if pid:
                out[pid] = {"pff": an.sid(r.get("pff_position")), "ngs": an.sid(r.get("ngs_position")), "status": an.sid(r.get("status")),
                            "team": an.sid(r.get("latest_team")), "pos": an.sid(r.get("position"))}
    _XW = out
    return out


def reset() -> None:
    global _XW
    _XW = None


def current_roster(ctx) -> dict[str, dict]:
    """{gsis_id: {team, status, pos, dcp, ngs, week}} from the season's latest weekly roster (the current season only)."""
    df = ctx.release("weekly_rosters")
    if df is None or not len(df) or "gsis_id" not in df or "week" not in df:
        return {}
    import pandas as pd
    wk = pd.to_numeric(df["week"], errors="coerce")
    last = df[wk == wk.max()]
    out = {}
    for r in last.to_dict("records"):
        pid = an.sid(r.get("gsis_id"))
        if not pid:
            continue
        from oddsmarkets.nfl.analytics import teamsref
        out[pid] = {"team": teamsref.canon_abbr(an.sid(r.get("team")), ctx.season) if an.sid(r.get("team")) else None,
                    "status": an.sid(r.get("status")), "pos": an.sid(r.get("position")), "dcp": an.sid(r.get("depth_chart_position")),
                    "ngs": an.sid(r.get("ngs_position")), "week": an.inum(r.get("week"))}
    return out


DC_43 = {"LDE": "EDGE", "RDE": "EDGE", "LDT": "DL", "RDT": "DL", "NT": "DL", "WLB": "LB", "MLB": "LB", "SLB": "LB",
         "LILB": "LB", "RILB": "LB"}
DC_34 = {"LDE": "DL", "RDE": "DL", "LDT": "DL", "RDT": "DL", "NT": "DL", "WLB": "EDGE", "SLB": "EDGE", "LOLB": "EDGE",
         "ROLB": "EDGE", "MLB": "LB", "LILB": "LB", "RILB": "LB"}
DC_OTHER = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "LT": "OL", "LG": "OL", "C": "OL", "RG": "OL", "RT": "OL",
            "LCB": "CB", "RCB": "CB", "NB": "CB", "CB": "CB", "FS": "S", "SS": "S", "S": "S", "PK": "K", "K": "K", "P": "P"}


def depth_charts(ctx) -> dict[str, dict[str, list[str]]]:
    """{team: {our position: [gsis ids in depth order]}} from the latest nflverse (ESPN) depth chart snapshot."""
    df = ctx.release("depth_charts")
    if df is None or not len(df) or "gsis_id" not in df:
        return {}
    if "dt" in df:
        df = df[df["dt"] == df["dt"].max()]
    out: dict[str, dict[str, list]] = {}
    from oddsmarkets.nfl.analytics import teamsref
    rows = sorted(df.to_dict("records"), key=lambda r: (str(r.get("team")), an.inum(r.get("pos_rank")) or 9, an.inum(r.get("pos_slot")) or 99))
    for r in rows:
        pid, ab = an.sid(r.get("gsis_id")), an.sid(r.get("pos_abb"))
        t = teamsref.canon_abbr(an.sid(r.get("team")), ctx.season) if an.sid(r.get("team")) else None
        if not pid or not ab or not t:
            continue
        grp = str(r.get("pos_grp") or "")
        pos = (DC_34 if "3-4" in grp else DC_43).get(ab) or DC_OTHER.get(ab)
        if not pos:
            continue
        lst = out.setdefault(t, {}).setdefault(pos, [])
        if pid not in lst:
            lst.append(pid)
    return out


NGS_DEF = {"EDGE": "EDGE", "INTERIOR_LINE": "DL", "MLB": "LB", "OLB": "LB", "ILB": "LB", "CB": "CB", "SLOT_CB": "CB",
           "SAFETY": "S", "HIGH_SAFETY": "S"}
PFF_DEF = {"ED": "EDGE", "DI": "DL", "LB": "LB", "CB": "CB", "S": "S"}
ROSTER_DEF = {"DE": "EDGE", "EDGE": "EDGE", "OLB": "LB", "DT": "DL", "NT": "DL", "DL": "DL", "ILB": "LB", "MLB": "LB", "LB": "LB",
              "CB": "CB", "FS": "S", "SS": "S", "S": "S", "SAF": "S", "DB": "CB"}


def def_position(pid: str, cat_pos: Any, roster: dict | None, xw: dict | None, dc_pos: str | None = None) -> str:
    """EDGE / DL / LB / CB / S: the weekly roster's NGS position, else PFF's (crosswalk), else the crosswalk's NGS
    position, else the depth chart, else the listed position (DE -> EDGE, DT / NT -> DL, OLB -> LB, DB -> CB)."""
    r, x = roster or {}, xw or {}
    for src, mp in ((r.get("ngs"), NGS_DEF), (x.get("pff"), PFF_DEF), (x.get("ngs"), NGS_DEF)):
        if src and mp.get(str(src).upper()):
            return mp[str(src).upper()]
    if dc_pos in DEFENCE:
        return dc_pos
    for src in (r.get("dcp"), cat_pos, x.get("pos"), r.get("pos")):
        if src and ROSTER_DEF.get(str(src).upper()):
            return ROSTER_DEF[str(src).upper()]
    return "LB"


# ---------------------------------------------------------------------------------------------- players

def pv_roles(pv: Any) -> dict[str, dict[str, tuple[float, float]]]:
    """{pid: {role: (adjusted EPA per play, plays)}} from player_value.for_season's "players" rows."""
    out: dict[str, dict] = {}
    rows = (pv or {}).get("players") if isinstance(pv, dict) else None
    if not rows or (isinstance(pv, dict) and pv.get("ok") is False):
        return out
    for r in rows:
        pid, role = an.sid(r.get("player")), an.sid(r.get("role"))
        rate, n = an.fnum(r.get("adj_per_play")), an.fnum(r.get("adj_plays"))
        if pid and role and rate is not None and n:
            out.setdefault(pid, {})[role] = (rate, n)
    return out


def _q(xs: list[float], q: float = REPL_Q) -> float | None:
    return float(np.quantile(np.asarray(xs, float), q)) if len(xs) >= 5 else None


def _opp_fallback(grp: str, v: dict) -> float:
    if grp == "QB":
        return float(v.get("att") or 0) + float(v.get("carries") or 0)
    return float(v.get("carries") or 0) + float(v.get("targets") or 0)


def player_records(season: int, cat: dict | None, pv: Any = None, roster: dict | None = None, xw: dict | None = None,
                   dc: dict | None = None, qbs: dict | None = None) -> tuple[dict[str, dict], dict]:
    """Per player of the season's catalogue: position, team (current roster team when `roster` is given), status,
    games, opportunities, Gridiron Value (gv), value above replacement (gvar), its rate per opportunity (per game for
    defenders) and the "why" components. Returns (records, replacement levels)."""
    players = (cat or {}).get("players") or {}
    tg = max(int((cat or {}).get("team_games") or 0), 1)
    roles = pv_roles(pv)
    xw = xw if xw is not None else {}
    dc_pos: dict[str, str] = {}
    for t, by in (dc or {}).items():
        for pos, ids in by.items():
            for p in ids:
                dc_pos.setdefault(p, pos)
    recs: dict[str, dict] = {}
    for pid, r in players.items():
        grp = r.get("group")
        v = r.get("values") or {}
        if grp in OFFENCE:
            pos = grp
        elif grp in ("K", "P"):
            pos = grp
        elif grp == "DEF":
            pos = def_position(pid, r.get("pos"), (roster or {}).get(pid), xw.get(pid), dc_pos.get(pid))
        else:
            continue
        ro = (roster or {}).get(pid) or {}
        team = (ro.get("team") if ro.get("status") in ON_ROSTER else None) if roster else r.get("team")
        recs[pid] = {"pid": pid, "name": r.get("name"), "team": team, "team_played": r.get("team"), "pos": pos, "group": grp,
                     "age": an.fnum(r.get("age")), "games": int(r.get("games") or 0), "q": bool(r.get("qualified")),
                     "status": ro.get("status") if roster else None, "v": v}
    repl: dict[str, Any] = {}
    # offence: role rates
    pr_roles: dict[tuple, list] = {}
    for pid, rc in recs.items():
        if rc["pos"] not in OFFENCE:
            continue
        rl = roles.get(pid)
        if not rl:
            opp = _opp_fallback(rc["group"], rc["v"])
            gv = an.fnum(rc["v"].get("value"))
            rl = {"all": (gv / (opp + FALLBACK_K), opp)} if gv is not None and opp > 0 else {}
        rc["roles"] = rl
        for role, (rate, n) in rl.items():
            lo, per = ROLE_FLOOR.get(role, ROLE_FLOOR["all"])
            if n >= max(lo, per * tg):
                pr_roles.setdefault((rc["pos"], role), []).append(rate)
                pr_roles.setdefault(("*", role), []).append(rate)
    for (pos, role), xs in pr_roles.items():
        if pos != "*":
            q = _q(xs)
            if q is not None:
                repl.setdefault(pos, {})[role] = round(q, 4)
    for (pos, role), xs in pr_roles.items():
        if pos == "*":
            repl.setdefault("_league", {})[role] = round(_q(xs) or float(np.min(xs)), 4)
    for pid, rc in recs.items():
        if rc["pos"] not in OFFENCE:
            continue
        gvar, opp, parts = 0.0, 0.0, {}
        for role, (rate, n) in (rc.get("roles") or {}).items():
            rp = (repl.get(rc["pos"]) or {}).get(role)
            if rp is None:
                rp = (repl.get("_league") or {}).get(role, 0.0)
            parts[role] = (rate - rp) * n
            gvar += parts[role]
            opp += n
        v = rc["v"]
        rc.update(gv=an.fnum(v.get("value")), gvar=gvar if opp else None, opp=opp, rate=gvar / opp if opp else None)
        if rc["pos"] == "QB":
            rc["why"] = [parts.get("passer"), parts.get("rusher"), v.get("epa_db"), v.get("cpoe"), v.get("composite")]
            q = (qbs or {}).get(pid)
            rc["qbv"] = q
        elif rc["pos"] == "RB":
            rc["why"] = [parts.get("rusher", parts.get("all")), parts.get("receiver"), v.get("ryoe"), v.get("ypc")]
        else:
            rc["why"] = [parts.get("receiver", parts.get("all")), v.get("yacoe"), v.get("croe"), v.get("target_share")]
    # kickers and punters
    for pos, gv_of, n_of, kk in (("K", lambda v: an.fnum(v.get("pts_oe")), lambda v: an.fnum(v.get("fga")), K_K),
                                 ("P", None, lambda v: an.fnum(v.get("punts")), P_K)):
        mem = {p: rc for p, rc in recs.items() if rc["pos"] == pos}
        if pos == "P":
            tot = [(an.fnum(rc["v"].get("epa_punt")), an.fnum(rc["v"].get("punts")) or 0) for rc in mem.values()]
            tot = [(e, n) for e, n in tot if e is not None and n]
            lg = sum(e * n for e, n in tot) / sum(n for _, n in tot) if tot else 0.0
            repl.setdefault("P", {})["league_epa_punt"] = round(lg, 4)
            gv_of = (lambda v, lg=lg: (an.fnum(v.get("epa_punt")) - lg) * (an.fnum(v.get("punts")) or 0)
                     if an.fnum(v.get("epa_punt")) is not None else None)
        sh = {}
        for p, rc in mem.items():
            g, n = gv_of(rc["v"]), n_of(rc["v"]) or 0
            rc.update(gv=g, opp=n)
            sh[p] = g / (n + kk) if g is not None and n > 0 else None
        rp = _q([x for p, x in sh.items() if x is not None and mem[p]["q"]])
        rp = rp if rp is not None else 0.0
        repl.setdefault(pos, {})["per_" + ("fga" if pos == "K" else "punt")] = round(rp, 4)
        for p, rc in mem.items():
            x = sh.get(p)
            rc["rate"] = (x - rp) if x is not None else None
            rc["gvar"] = rc["rate"] * rc["opp"] if x is not None else None
            v = rc["v"]
            rc["why"] = [v.get("fg_oe"), v.get("fg_50"), v.get("fg_pct")] if pos == "K" else [v.get("net"), v.get("inside20"), v.get("net_oe")]
    # defenders
    for pos in DEFENCE:
        mem = {p: rc for p, rc in recs.items() if rc["pos"] == pos}
        pg = {p: (an.fnum(rc["v"].get("def_value")) or 0.0) / rc["games"] for p, rc in mem.items() if rc["games"] > 0}
        ref = [x for p, x in pg.items() if mem[p]["q"]]
        m = float(np.mean(ref)) if ref else (float(np.mean(list(pg.values()))) if pg else 0.0)
        sh = {p: ((an.fnum(mem[p]["v"].get("def_value")) or 0.0) + DEF_K_GAMES * m) / (mem[p]["games"] + DEF_K_GAMES) for p in pg}
        rp = _q([sh[p] for p in sh if mem[p]["q"]])
        rp = rp if rp is not None else (min(sh.values()) if sh else 0.0)
        repl.setdefault(pos, {})["per_game"] = round(rp, 4)
        for p, rc in mem.items():
            v = rc["v"]
            rc["gv"] = an.fnum(v.get("def_value"))
            rc["opp"] = float(rc["games"])
            rc["rate"] = (sh[p] - rp) if p in sh else None
            rc["gvar"] = rc["rate"] * rc["games"] if p in sh else None
            rc["why"] = {"EDGE": [v.get("sacks"), v.get("qb_hits"), v.get("tfl"), v.get("ff")],
                         "DL": [v.get("sacks"), v.get("qb_hits"), v.get("tfl"), v.get("ff")],
                         "LB": [v.get("tfl"), v.get("sacks"), v.get("pd"), v.get("ints")]}.get(pos, [v.get("pd"), v.get("ints"), v.get("ff"), v.get("tfl")])
    for rc in recs.values():
        g = rc["games"]
        rc["opp_pg"] = (rc.get("opp") or 0.0) / g if g else 0.0
        rc["gvar_pg"] = rc["gvar"] / g if rc.get("gvar") is not None and g else None
        if rc["pos"] in DEFENCE:
            rc["opp_pg"] = 1.0
    return recs, repl


def prev_gv_pg(cat: dict | None) -> dict[str, float]:
    """Last season's Gridiron Value per game from its catalogue (the trend column): QB/RB/WR/TE value, K points
    over expected, P punting EPA over the league's mean punt, defenders' splash EPA."""
    players = (cat or {}).get("players") or {}
    tot = [(an.fnum(r["values"].get("epa_punt")), an.fnum(r["values"].get("punts")) or 0) for r in players.values() if r.get("group") == "P"]
    tot = [(e, n) for e, n in tot if e is not None and n]
    lg = sum(e * n for e, n in tot) / sum(n for _, n in tot) if tot else 0.0
    out = {}
    for pid, r in players.items():
        v, g, grp = r.get("values") or {}, int(r.get("games") or 0), r.get("group")
        if not g:
            continue
        x = {"K": an.fnum(v.get("pts_oe")), "DEF": an.fnum(v.get("def_value"))}.get(grp, an.fnum(v.get("value")))
        if grp == "P":
            e = an.fnum(v.get("epa_punt"))
            x = (e - lg) * (an.fnum(v.get("punts")) or 0) if e is not None else None
        if x is not None:
            out[pid] = x / g
    return out


def gv_pg(rc: dict) -> float | None:
    return rc["gv"] / rc["games"] if rc.get("gv") is not None and rc.get("games") else None


# ---------------------------------------------------------------------------------------------- the value page

COLS = ["pid", "name", "team", "pos", "age", "games", "opp", "gv", "gvar", "gvar_pg", "pct", "trend", "q", "why"]


def value_payload(season: int, recs: dict[str, dict], repl: dict, prev: dict[str, float] | None, phase: str | None,
                  tg: int, current: bool, basis_season: int | None = None) -> dict:
    """value.json: the leaderboard rows (column-oriented), the best ten at each position and the notes."""
    rows, by_pos = [], {}
    pct: dict[str, int] = {}
    for pos in POSITIONS:
        mem = {p: rc for p, rc in recs.items() if rc["pos"] == pos and rc.get("gvar_pg") is not None}
        pct.update(an.percentiles({p: rc["gvar_pg"] for p, rc in mem.items() if rc["q"]}))
    keep = [rc for rc in recs.values() if rc.get("gvar") is not None and (rc["games"] >= 1) and
            ((rc["pos"] in DEFENCE and rc["games"] >= 2) or (rc["pos"] not in DEFENCE and (rc.get("opp") or 0) >= 5))]
    keep.sort(key=lambda rc: -(rc["gvar"] or 0))
    for rc in keep:
        tr = None
        g_now = gv_pg(rc)
        if prev and rc["pid"] in prev and g_now is not None:
            tr = g_now - prev[rc["pid"]]
        rows.append([rc["pid"], rc["name"], rc.get("team") or rc.get("team_played"), rc["pos"], an.rnd(rc.get("age"), 1), rc["games"],
                     an.rnd(rc.get("opp"), 0), an.rnd(rc.get("gv"), 1), an.rnd(rc["gvar"], 1), an.rnd(rc.get("gvar_pg"), 2),
                     pct.get(rc["pid"]), an.rnd(tr, 2), 1 if rc["q"] else 0, [an.rnd(x, 3) for x in (rc.get("why") or [])]])
    for pos in POSITIONS:
        cand = [rc for rc in keep if rc["pos"] == pos and rc["q"]]
        cand.sort(key=lambda rc: -(rc["gvar"] or 0))
        by_pos[pos] = [rc["pid"] for rc in cand[:10]]
    return {"ok": True, "season": season, "updated_at": an.now(), "version": VERSION, "phase": phase, "team_games": tg, "current": current,
            "basis_season": basis_season or season, "positions": list(POSITIONS), "labels": POS_LABEL, "cols": COLS, "rows": rows,
            "best": by_pos, "why": WHY, "replacement": repl, "repl_q": REPL_Q,
            "notes": {"currency": "Points (EPA) above a replacement-level player at the same position: the 20th-percentile rate among "
                                  "the position's regulars, times the player's volume.",
                      "ol": "Offensive linemen are not valued individually: public data have no blocking assignments, and on-field "
                            "plus-minus cannot separate five linemen who play every snap together. Teams are graded on pass "
                            "protection as a unit.",
                      "defence": "Defenders are valued on Splash EPA: the plays the box score credits them with (sacks, "
                                 "interceptions, forced fumbles, passes defensed, tackles for loss). Coverage, pressure without a "
                                 "hit and run fits are invisible, so defensive values are a floor on what a player is worth.",
                      "trend": "Trend: this season's Gridiron Value per game minus last season's."},
            "credits": [an.NFLVERSE_CREDIT] + ([an.FTN_CREDIT] if season >= 2022 else [])}


# ---------------------------------------------------------------------------------------------- teams: the starters model

def available(rc: dict, current: bool) -> bool:
    return (not current) or rc.get("status") in AVAILABLE or rc.get("status") is None


def pos_value(vals: list[float | None], n: int) -> float:
    """Starters model: the n best per-game values above replacement on the roster (each floored at 0: a team can
    always field a replacement player), summed."""
    vs = sorted((max(0.0, v) for v in vals if v is not None), reverse=True)
    return float(sum(vs[:n]))


def team_members(recs: dict[str, dict], current: bool) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for p, rc in recs.items():
        t = rc.get("team")
        if t and rc["pos"] in SLOTS and available(rc, current):
            out.setdefault(t, {}).setdefault(rc["pos"], []).append(p)
    return out


def team_pos_values(recs: dict[str, dict], teams: list[str], members: dict, qb_val: dict[str, float], np_lg: float) -> dict[str, dict[str, float]]:
    """{team: {pos: points per game above replacement}} (QB: the team-strength QB term x dropbacks per game, so the
    QB value is relative to an average QB, not replacement)."""
    out = {}
    for t in teams:
        out[t] = {}
        for pos, n in SLOTS.items():
            if pos == "QB":
                q = qb_val.get(t)
                out[t][pos] = np_lg * q if q is not None else None
                continue
            ids = (members.get(t) or {}).get(pos, [])
            out[t][pos] = pos_value([recs[p].get("gvar_pg") for p in ids], n)
    return out


def gain_for(team: str, rc: dict, recs: dict, members: dict, qb_val: dict, qbs: dict, np_lg: float) -> float:
    """Points per game (before k_resp) team gains by adding rc at his position: he displaces the weakest starter if
    he is better (QB: if his model QB value beats the starter's)."""
    pos = rc["pos"]
    if pos == "QB":
        q, cur = (qbs or {}).get(rc["pid"]), qb_val.get(team)
        if q is None or cur is None:
            return 0.0
        return max(0.0, np_lg * (q - cur))
    ids = (members.get(team) or {}).get(pos, [])
    vals = [recs[p].get("gvar_pg") for p in ids if p != rc["pid"]]
    return pos_value(vals + [rc.get("gvar_pg")], SLOTS[pos]) - pos_value(vals, SLOTS[pos])


def loss_for(team: str, rc: dict, recs: dict, members: dict, qb_val: dict, qbs: dict, np_lg: float,
             qb_next: dict[str, float] | None = None, qb_start: dict[str, str] | None = None) -> float:
    """Points per game (before k_resp) team loses without rc: the next man up on its own roster takes his place (a
    QB only matters when he is the starter; the next QB on the depth chart takes over)."""
    pos = rc["pos"]
    if pos == "QB":
        cur = qb_val.get(team)
        if cur is None or (qb_start or {}).get(team) != rc["pid"]:
            return 0.0
        nxt = (qb_next or {}).get(team)
        return np_lg * (cur - nxt) if nxt is not None else 0.0
    ids = (members.get(team) or {}).get(pos, [])
    vals = [recs[p].get("gvar_pg") for p in ids]
    return pos_value(vals, SLOTS[pos]) - pos_value([recs[p].get("gvar_pg") for p in ids if p != rc["pid"]], SLOTS[pos])


def interp(curve: list[float], grid: list[float], x: float) -> float | None:
    if not curve or not grid:
        return None
    x = max(grid[0], min(grid[-1], x))
    return float(np.interp(x, grid, curve))


def curve_delta(sens: dict | None, team: str, key: str, dx: float) -> float | None:
    """Change in a sensitivity-curve quantity for a strength shift dx (points per game)."""
    c = ((sens or {}).get("teams") or {}).get(team) or {}
    g = (sens or {}).get("grid") or []
    if key not in c or not g:
        return None
    a, b = interp(c[key], g, dx), interp(c[key], g, 0.0)
    return None if a is None or b is None else a - b


# ---------------------------------------------------------------------------------------------- needs and trade

def team_sack_rates(ctx) -> dict[str, dict]:
    """{team: {"allowed", "generated"}}: sacks per dropback on offence and defence in the regular season's plays (the
    pass-protection and pass-rush fallback when the pressure model has no participation data, i.e. in-season)."""
    from oddsmarkets.nfl.analytics.context import flag
    from oddsmarkets.nfl.analytics.players import reg_plays, scrimmage
    try:
        S = scrimmage(reg_plays(ctx))
    except Exception:                                            # noqa: BLE001
        return {}
    if not len(S) or "qb_dropback" not in S:
        return {}
    D = S[flag(S, "qb_dropback").fillna(0) == 1]
    sk = flag(D, "sack").fillna(0)
    a, g = sk.groupby(D["posteam"]).mean(), sk.groupby(D["defteam"]).mean()
    return {t: {"allowed": an.fnum(a.get(t)), "generated": an.fnum(g.get(t))} for t in set(a.index) | set(g.index)}


def unit_rows(tm: dict, qb_pct: dict[str, int], qb_val: dict[str, float], np_lg: float, team: str,
              sacks: dict[str, dict] | None = None, sack_pct: dict[str, dict] | None = None) -> list[dict]:
    out = []
    vals, pc = tm.get("values") or {}, tm.get("pct") or {}
    for key, label, vk, lower, pos in UNITS:
        if key in ("protection", "pass_rush") and vals.get(vk) is None and (sacks or {}).get(team):
            sub = "allowed" if key == "protection" else "generated"
            v = sacks[team].get(sub)
            p = ((sack_pct or {}).get(sub) or {}).get(team)
            if v is not None:
                out.append({"key": key, "label": label, "value": an.rnd(v, 4), "fmt": "pct", "pct": p, "grade": grade(p),
                            "stat": ("sacks per dropback " + ("allowed" if sub == "allowed" else "by the defence") +
                                     " (pressure data arrive only after the season)"), "positions": pos, "lower": key == "protection"})
            continue
        if key == "qb":
            v = qb_val.get(team)
            out.append({"key": key, "label": label, "value": an.rnd(v, 3), "fmt": "epa", "pct": qb_pct.get(team), "grade": grade(qb_pct.get(team)),
                        "stat": "the starter's EPA per dropback above an average QB in the team-strength model"
                        + (f" ({np_lg * v:+.1f} points a game)" if v is not None else ""), "positions": pos})
            continue
        v = vals.get(vk)
        p = pc.get(vk)
        if v is None:
            continue
        fmt = "pct" if vk in ("pressure_allowed", "pressure_rate_def") else ("2" if vk == "st_epa_g" else "epa")
        stat = {"off_pass_epa": "opponent-adjusted EPA per dropback", "off_rush_epa": "opponent-adjusted EPA per designed run",
                "def_pass_epa": "opponent-adjusted EPA per dropback allowed", "def_rush_epa": "opponent-adjusted EPA per run allowed",
                "pressure_allowed": "share of dropbacks under pressure", "pressure_rate_def": "share of opponent dropbacks pressured",
                "st_epa_g": "special-teams EPA per game, net of the opponent's"}.get(vk, vk)
        out.append({"key": key, "label": label, "value": an.rnd(v, 4), "fmt": fmt, "pct": p, "grade": grade(p), "stat": stat, "positions": pos,
                    "lower": lower})
    return out


def build(ctx, cat: dict | None, tms: dict | None, sim: dict | None = None, sens: dict | None = None, prev_cat: dict | None = None,
          prev_pv: Any = None, contracts_tab: dict | None = None, contracts_on: bool = False) -> dict:
    """Every value payload of a season: {"value": value.json, "needs": {abbr: needs payload} (current season),
    "trade": trade.json (current season)}. Light seasons get value.json only."""
    season = ctx.season
    current = bool(ctx.current)
    xw = crosswalk()
    roster = current_roster(ctx) if current else {}
    dc = depth_charts(ctx) if current else {}
    pv = ctx.model("player_value") if ctx.use_models else None
    rt = ctx.model("team_strength") if ctx.use_models else None
    rt = rt if isinstance(rt, dict) and rt.get("teams") else None
    qbs = {q: an.fnum(v.get("val")) for q, v in ((rt or {}).get("qbs") or {}).items()} if rt else {}
    for q, v in ((rt or {}).get("qb_prior") or {}).items():
        qbs.setdefault(q, an.fnum(v))
    tg = max(int((cat or {}).get("team_games") or 0), 1)
    recs, repl = player_records(season, cat, pv, roster or None, xw, dc, qbs)
    basis = season
    if current and len([r for r in recs.values() if r.get("gvar") is not None]) < 100 and prev_cat:
        # before the season's first games: last season's values on this season's rosters
        recs, repl = player_records(season - 1, prev_cat, prev_pv, roster or None, xw, dc, qbs)
        basis = season - 1
    prev = prev_gv_pg(prev_cat) if basis == season else None
    out: dict[str, Any] = {"value": value_payload(season, recs, repl, prev, getattr(ctx, "phase", None), tg, current, basis)}
    if not current:
        return out
    teams = sorted(ctx.teams)
    np_lg = float(((rt or {}).get("league") or {}).get("np") or 35.0)
    qb_val = {t: an.fnum(v.get("qb_val")) for t, v in ((rt or {}).get("teams") or {}).items()}
    qb_start = {t: v.get("qb") for t, v in ((rt or {}).get("teams") or {}).items()}
    for rc in recs.values():
        if rc["pos"] == "QB":
            rc["qbv"] = qbs.get(rc["pid"])
    # QB depth: the depth chart's order (current roster, available), else by the model's QB value
    qb_depth: dict[str, list[str]] = {}
    for t in teams:
        ids = [p for p in ((dc.get(t) or {}).get("QB") or []) if (roster.get(p) or {}).get("status") in AVAILABLE or not roster]
        extra = sorted([p for p, ro in roster.items() if ro.get("team") == t and ro.get("status") in AVAILABLE and
                        (str(ro.get("pos") or "").upper() == "QB") and p not in ids], key=lambda p: -(qbs.get(p) if qbs.get(p) is not None else -9))
        qb_depth[t] = ids + extra
    qb_next = {}
    from oddsmarkets.nfl.models import team_strength as TS
    qb_new = float(TS.params().get("qb_new", -0.02))
    for t in teams:
        nxt = [p for p in qb_depth.get(t, []) if p != qb_start.get(t)]
        qb_next[t] = (qbs.get(nxt[0]) if qbs.get(nxt[0]) is not None else qb_new) if nxt else qb_new
    members = team_members(recs, True)
    tpv = team_pos_values(recs, teams, members, qb_val, np_lg)
    sacks = team_sack_rates(ctx)
    sack_pct = {"allowed": an.percentiles({t: (sacks.get(t) or {}).get("allowed") for t in teams}, lower=True),
                "generated": an.percentiles({t: (sacks.get(t) or {}).get("generated") for t in teams})}
    pos_pct = {pos: an.percentiles({t: tpv[t].get(pos) for t in teams}) for pos in SLOTS}
    qb_pct = an.percentiles({t: qb_val.get(t) for t in teams})
    try:
        from oddsmarkets.nfl.models import game as GMm
        from oddsmarkets.nfl.models import market_ratings as MRm
        p = GMm.params()
        k_resp = float(p.get("s", 0.0)) + float(p.get("mr", 0.0)) * float(MRm.QB_S)
    except Exception:                                            # noqa: BLE001
        k_resp = 0.85
    sim_t = (sim or {}).get("teams") or {} if (sim or {}).get("ok") else {}
    remaining = {t: int(((sim_t.get(t) or {}).get("current") or {}).get("remaining") or 0) for t in teams}
    if not any(remaining.values()):
        # no simulation this run: count each club's regular-season games not yet final
        for g in (getattr(ctx, "games", None) or {}).values():
            if g.get("status") != "final" and str(g.get("gtype") or g.get("game_type") or "REG") == "REG":
                for t in (g.get("home"), g.get("away")):
                    if t in remaining:
                        remaining[t] += 1
    out["needs"] = {}
    tm_all = (tms or {}).get("teams") or {}
    prev_recs = player_records(season - 1, prev_cat, prev_pv, None, xw)[0] if prev_cat else {}
    unsigned = unsigned_candidates(recs, roster, xw, prev_cat, prev_pv, season, prev_recs)
    for t in teams:
        out["needs"][t] = needs_payload(season, t, recs, tm_all.get(t) or {}, tpv, pos_pct, qb_pct, qb_val, qbs, qb_next, qb_start, np_lg,
                                        members, sens, sim_t, remaining, k_resp, dc, xw, unsigned, contracts_tab, contracts_on, basis,
                                        sacks, sack_pct)
    out["trade"] = trade_payload(season, recs, teams, qb_val, qb_start, qb_depth, qbs, qb_new, np_lg, k_resp, sens, sim_t,
                                 remaining, roster, contracts_tab, contracts_on, basis, getattr(ctx, "phase", None))
    # inputs for valuation v2 and the transactions pages (not written: build_gridiron.value_pages uses them)
    out["_ctx"] = {"recs": recs, "prev_recs": prev_recs if basis == season else {}, "unsigned": unsigned, "roster": roster, "k_resp": k_resp,
                   "teams": teams, "qbs": qbs, "np": np_lg, "qb_new": qb_new, "remaining": remaining, "basis": basis,
                   "tg": tg}
    return out


def unsigned_candidates(recs: dict, roster: dict, xw: dict, prev_cat: dict | None, prev_pv: Any, season: int,
                        prev_recs: dict | None = None) -> list[dict]:
    """Players with value this season or last who are on no current roster (the latest weekly roster lists them as
    released, or not at all while the players release says released) and not retired: their latest rates (last
    season's when they have none this season)."""
    if not roster:
        return []
    cut = set()
    for p, x in xw.items():
        ro = roster.get(p)
        if x.get("status") == "RET" or (ro and ro.get("status") in ON_ROSTER):
            continue
        if (ro and ro.get("status") == "CUT") or (not ro and x.get("status") in ("CUT", "RLS", "UFA")):
            cut.add(p)
    if not cut:
        return []
    out = []
    if prev_recs is None:
        prev_recs, _ = player_records(season - 1, prev_cat, prev_pv, None, xw) if prev_cat else ({}, {})
    for p in cut:
        rc = recs.get(p)
        src = season
        if rc is None or rc.get("gvar_pg") is None:
            rc, src = prev_recs.get(p), season - 1
        if rc is None or rc.get("gvar_pg") is None or rc["gvar_pg"] <= 0 or not rc.get("q"):
            continue
        out.append({**rc, "src": src, "team": None})
    return out


def needs_payload(season, t, recs, tm, tpv, pos_pct, qb_pct, qb_val, qbs, qb_next, qb_start, np_lg, members, sens, sim_t, remaining,
                  k_resp, dc, xw, unsigned, contracts_tab, contracts_on, basis, sacks=None, sack_pct=None) -> dict:
    units = unit_rows(tm, qb_pct, qb_val, np_lg, t, sacks, sack_pct)
    positions = []
    for pos in POSITIONS:
        if pos == "QB":
            ids = sorted((members.get(t) or {}).get(pos, []), key=lambda p: -(qbs.get(p) if qbs.get(p) is not None else -9))
        else:
            ids = sorted((members.get(t) or {}).get(pos, []), key=lambda p: -(recs[p].get("gvar_pg") if recs[p].get("gvar_pg") is not None else -99))
        pl = [[p, recs[p]["name"], an.rnd(recs[p].get("gvar_pg"), 2), an.rnd(qbs.get(p), 3) if pos == "QB" else None]
              for p in ids[:max(SLOTS[pos] + 1, 3)]]
        inj = [[p, rc["name"]] for p, rc in recs.items() if rc.get("team") == t and rc["pos"] == pos and rc.get("status") == "RES"
               and (rc.get("gvar") or 0) > 0]
        positions.append({"pos": pos, "label": POS_LABEL[pos], "value": an.rnd(tpv[t].get(pos), 2), "pct": pos_pct[pos].get(t),
                          "grade": grade(pos_pct[pos].get(t)), "players": pl, "ir": inj[:3],
                          "basis": "QB term x dropbacks per game, v an average QB" if pos == "QB" else "points per game above replacement"})
    items = [{"kind": "unit", "key": u["key"], "label": u["label"], "pct": u["pct"], "grade": u["grade"],
              "evidence": u["stat"], "value": u["value"], "fmt": u["fmt"], "positions": u.get("positions") or []} for u in units if u.get("pct") is not None]
    items += [{"kind": "pos", "key": x["pos"], "label": x["label"], "pct": x["pct"], "grade": x["grade"], "value": x["value"], "fmt": "2",
               "evidence": ("starters: " + ", ".join(f"{pl[1]} {pl[2]:+.2f}" if pl[2] is not None else pl[1] for pl in x["players"][:SLOTS[x['pos']]])
                            if x["players"] else "no player on the roster with a sample"), "positions": [x["pos"]]}
              for x in positions if x["pos"] != "QB" and x.get("pct") is not None]
    items.sort(key=lambda z: -(z["pct"] or 0))
    strengths = [z for z in items if (z["pct"] or 0) >= 60][:3]
    weak = [z for z in sorted(items, key=lambda z: (z["pct"] if z["pct"] is not None else 50)) if (z["pct"] if z["pct"] is not None else 50) <= 40][:3]
    seller = {s: (sim_t.get(s) or {}).get("p_playoffs") for s in sim_t}
    improve = []
    for w in weak:
        pos_list = [p for p in (w.get("positions") or []) if p in SLOTS]
        if not pos_list:
            improve.append({"key": w["key"], "label": w["label"], "candidates": [], "unsigned": [],
                            "note": "Not tradeable as individuals in our models: pass protection is the line, backs and QB together, "
                                    "and linemen are not valued one by one."})
            continue
        cands, fa = [], []
        for pos in pos_list:
            for rc in recs.values():
                if rc["pos"] != pos or rc.get("team") in (None, t) or not available(rc, True) or rc.get("gvar_pg") is None:
                    continue
                g = gain_for(t, rc, recs, members, qb_val, qbs, np_lg)
                if g <= 0.05:
                    continue
                cands.append((g, rc, pos))
            for rc in unsigned:
                if rc["pos"] != pos:
                    continue
                g = gain_for(t, rc, recs, members, qb_val, qbs, np_lg)
                if g > 0.05:
                    fa.append((g, rc, pos))
        cands.sort(key=lambda z: -z[0])
        fa.sort(key=lambda z: -z[0])

        def row(g, rc, pos, free=False):
            dx = k_resp * g
            s = rc.get("team")
            cost = None if free else loss_for(s, rc, recs, members, qb_val, qbs, np_lg, qb_next, qb_start)
            hints = []
            ps = seller.get(s)
            if not free and ps is not None and ps < 0.10:
                hints.append(f"{s} are {100 * ps:.0f}% to make the playoffs")
            if not free and pos == "QB" and qb_start.get(s) != rc["pid"]:
                hints.append(f"not {s}'s starting QB at present")
            elif not free and cost is not None and cost < 0.5 * g:
                hints.append(f"costs {s} only {k_resp * cost:.2f} points a game (depth behind him)")
            ct = (contracts_tab or {}).get(rc["pid"]) if contracts_on else None
            if ct and ct.get("contract_year"):
                hints.append("in the last year of his contract")
            if rc.get("age") is not None and rc["age"] >= 31:
                hints.append(f"age {rc['age']:.0f}")
            r = {"pid": rc["pid"], "name": rc["name"], "team": s, "pos": pos, "age": an.rnd(rc.get("age"), 1),
                 "gain_pg": an.rnd(dx, 2), "gain_rest": an.rnd(dx * remaining.get(t, 0), 1) if remaining.get(t) else None,
                 "d_wins": an.rnd(curve_delta(sens, t, "mean_wins", dx), 2), "d_playoffs": an.rnd(curve_delta(sens, t, "p_playoffs", dx), 4),
                 "seller_cost_pg": an.rnd(k_resp * cost, 2) if cost is not None else None, "gvar_pg": an.rnd(rc.get("gvar_pg"), 2),
                 "hints": hints}
            if free:
                r["last_season"] = rc.get("src")
            if ct:
                r.update(cap_hit=ct.get("cap_hit"), years_left=ct.get("years_left"))
            return r
        improve.append({"key": w["key"], "label": w["label"], "positions": pos_list,
                        "candidates": [row(g, rc, pos) for g, rc, pos in cands[:5]],
                        "unsigned": [row(g, rc, pos, True) for g, rc, pos in fa[:3]]})
    ol = [[p, (xw.get(p) or {}).get("pos") or "OL"] for p in ((dc.get(t) or {}).get("OL") or [])[:5]]
    return {"ok": True, "season": season, "team": t, "updated_at": an.now(), "basis_season": basis, "label": LABEL,
            "units": units, "positions": positions, "strengths": strengths, "weaknesses": weak, "improve": improve,
            "ol": {"starters": ol, "note": "Linemen are not valued individually (no blocking assignments in public data); the unit is "
                                           "graded through pass protection."},
            "k_resp": round(k_resp, 3), "remaining": remaining.get(t),
            "contracts": {"enabled": bool(contracts_on), "note": None if contracts_on else __import__(
                "oddsmarkets.nfl.analytics.contracts", fromlist=["NOT_PUBLISHED"]).NOT_PUBLISHED},
            "grades": [list(x) for x in GRADE_CUTS]}


TRADE_COLS = ["pid", "name", "team", "pos", "age", "games", "gvar", "gvar_pg", "qbv", "status", "cap_hit", "years_left"]


def trade_payload(season, recs, teams, qb_val, qb_start, qb_depth, qbs, qb_new, np_lg, k_resp, sens, sim_t, remaining,
                  roster, contracts_tab, contracts_on, basis, phase) -> dict:
    """trade.json: everything the client-side simulator needs (players on current rosters at the modelled positions,
    each team's QB depth, the sensitivity curves and the published odds)."""
    from oddsmarkets.nfl.analytics import contracts as CT
    rows = []
    seen = set()
    for p, rc in recs.items():
        if rc.get("team") not in teams or rc["pos"] not in SLOTS:
            continue
        if rc.get("status") not in ("ACT", "INA", "RES", None):
            continue
        ct = (contracts_tab or {}).get(p) if contracts_on else None
        rows.append([p, rc["name"], rc["team"], rc["pos"], an.rnd(rc.get("age"), 1), rc["games"], an.rnd(rc.get("gvar"), 1),
                     an.rnd(rc.get("gvar_pg"), 3), an.rnd(qbs.get(p), 4) if rc["pos"] == "QB" else None, rc.get("status"),
                     ct.get("cap_hit") if ct else None, ct.get("years_left") if ct else None])
        seen.add(p)
    # quarterbacks on the depth chart without a sample this season (backups, rookies): their model QB value
    for t, ids in qb_depth.items():
        for p in ids:
            if p in seen:
                continue
            ro = roster.get(p) or {}
            from oddsmarkets.nfl.analytics import people
            nm = (people.people().get(p) or {}).get("name") or p
            ct = (contracts_tab or {}).get(p) if contracts_on else None
            rows.append([p, nm, t, "QB", None, 0, None, None, an.rnd(qbs.get(p, qb_new), 4), ro.get("status"),
                         ct.get("cap_hit") if ct else None, ct.get("years_left") if ct else None])
            seen.add(p)
    rows.sort(key=lambda r: (r[2], POSITIONS.index(r[3]), -(r[7] if r[7] is not None else -999)))
    cap = None
    if contracts_on and contracts_tab:
        rteam = {p: ro.get("team") for p, ro in roster.items() if ro.get("status") in ("ACT", "INA", "RES")}
        tot = CT.team_totals({p: v for p, v in contracts_tab.items() if p in rteam}, rteam)
        cap = {"season_cap": CT.season_cap(contracts_tab), "teams": tot, "credit": CT.CREDIT,
               "note": "Sum of the listed cap numbers of players on the current roster (active, inactive and injured reserve) "
                       "against the season cap; dead money, carry-over and the offseason top-51 rule are not modelled."}
    base = {}
    for t in teams:
        s = sim_t.get(t) or {}
        base[t] = {k: an.rnd(s.get(k), 4) for k in ("p_playoffs", "p_div", "p_bye", "p_conf", "p_sb")}
        base[t].update(mean_wins=an.rnd(s.get("mean_wins"), 2), mean_pick=an.rnd(s.get("mean_pick"), 2), rating=an.rnd(s.get("rating"), 2),
                       remaining=remaining.get(t), record=[((s.get("current") or {}).get(k)) for k in ("w", "l", "t")])
    return {"ok": True, "season": season, "updated_at": an.now(), "version": VERSION, "phase": phase, "basis_season": basis,
            "cols": TRADE_COLS, "players": rows, "slots": SLOTS, "positions": list(POSITIONS), "labels": POS_LABEL,
            "qb": {t: {"starter": qb_start.get(t), "val": an.rnd(qb_val.get(t), 4), "depth": qb_depth.get(t, [])}
                                                      for t in teams},
            "qb_new": qb_new, "np": round(np_lg, 2), "k_resp": round(k_resp, 4),
            "sens": {"ok": bool((sens or {}).get("ok")), "grid": (sens or {}).get("grid"), "keys": (sens or {}).get("keys"),
                     "teams": (sens or {}).get("teams") or {}, "n": (sens or {}).get("n"), "reason": (sens or {}).get("reason")},
            "baseline": base, "cap": cap,
            "contracts": {"enabled": bool(contracts_on), "note": None if contracts_on else CT.NOT_PUBLISHED},
            "label": LABEL}
