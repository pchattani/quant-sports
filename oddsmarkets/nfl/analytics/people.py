"""
The player crosswalk (nflverse `players` release): gsis_id -> name, position, position group, birth date, college,
draft, rookie and last season. Loaded once per process (a slim frame), with the season rosters as a fallback for
players the crosswalk lacks.

Draft fields are kept only from the 2008 draft (`DRAFT_API_FROM`): nflverse takes those from the NFL's draft API;
earlier drafts in the release are scraped from Pro Football Reference, whose terms forbid building a website on its
data, so a pre-2008 draft (or one without a year) is published as `None`.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from oddsmarkets.nfl import analytics as an

logger = logging.getLogger(__name__)
_PEOPLE: dict[str, dict] | None = None
DRAFT_API_FROM = 2008          # nflverse players: NFL draft API from 2008; earlier years scraped from PFR (not used)

POS_GROUP = {
    "QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "TE", "K": "K", "PK": "K", "P": "P",
    "DE": "DEF", "DT": "DEF", "NT": "DEF", "DL": "DEF", "LB": "DEF", "ILB": "DEF", "OLB": "DEF", "MLB": "DEF", "CB": "DEF",
    "S": "DEF", "FS": "DEF", "SS": "DEF", "DB": "DEF", "SAF": "DEF", "EDGE": "DEF",
}
DEF_POS = {"DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "EDGE": "DL", "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB",
           "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "DB": "DB", "SAF": "DB"}


def _col(df: pd.DataFrame, *names: str) -> str | None:
    return next((n for n in names if n in df.columns), None)


def people() -> dict[str, dict]:
    """{gsis_id: {name, pos, group, dob, college, draft: {year, round, pick, team}, rookie, last, height, weight}}."""
    global _PEOPLE
    if _PEOPLE is not None:
        return _PEOPLE
    from oddsmarkets.nfl.analytics.context import load_release
    out: dict[str, dict] = {}
    df = None
    try:
        df = load_release("players", None)
    except Exception as exc:                                     # noqa: BLE001
        logger.info("players crosswalk: %s", exc)
    if df is not None and len(df):
        idc = _col(df, "gsis_id", "player_id")
        if idc:
            nm = _col(df, "display_name", "full_name", "football_name", "player_name")
            pc = _col(df, "position", "pos")
            gc_ = _col(df, "position_group")
            dob = _col(df, "birth_date", "birthdate")
            col = _col(df, "college_name", "college")
            dy, dr, dp, dt = (_col(df, "draft_year", "entry_year"), _col(df, "draft_round"), _col(df, "draft_pick", "draft_number"),
                              _col(df, "draft_team", "draft_club"))
            rk, ls = _col(df, "rookie_season", "rookie_year"), _col(df, "last_season")
            ht, wt = _col(df, "height"), _col(df, "weight")
            jn = _col(df, "jersey_number")
            for r in df.to_dict("records"):
                pid = an.sid(r.get(idc))
                if not pid or not pid.startswith("00-"):
                    continue
                pos = an.sid(r.get(pc)) if pc else None
                out[pid] = {"name": an.sid(r.get(nm)) if nm else pid, "pos": pos,
                            "group": POS_GROUP.get(str(pos or "").upper()) or (an.sid(r.get(gc_)) if gc_ else None),
                            "dob": str(r.get(dob))[:10] if dob and an.sid(r.get(dob)) else None,
                            "college": an.sid(r.get(col)) if col else None,
                            "draft": _draft(r, dy, dr, dp, dt),
                            "rookie": an.inum(r.get(rk)) if rk else None, "last": an.inum(r.get(ls)) if ls else None,
                            "height": an.fnum(r.get(ht)) if ht else None, "weight": an.fnum(r.get(wt)) if wt else None,
                            "number": jersey(r.get(jn)) if jn else None}
    _PEOPLE = out
    return out


_ESPN: dict[str, str] | None = None


def espn_xwalk() -> dict[str, str]:
    """{espn athlete id: gsis_id} from the nflverse players release (ESPN box scores on game pages before nflverse
    publishes the week)."""
    global _ESPN
    if _ESPN is not None:
        return _ESPN
    out: dict[str, str] = {}
    try:
        from oddsmarkets.nfl.analytics.context import load_release
        df = load_release("players", None)
    except Exception as exc:                                     # noqa: BLE001
        logger.info("players crosswalk (espn): %s", exc)
        df = None
    if df is not None and len(df):
        idc, ec = _col(df, "gsis_id", "player_id"), _col(df, "espn_id")
        if idc and ec:
            for g, e in zip(df[idc], df[ec]):
                g, e = an.sid(g), an.sid(e)
                if g and e and g.startswith("00-"):
                    out[e[:-2] if e.endswith(".0") else e] = g
    _ESPN = out
    return out


def _draft(r: dict, dy: str | None, dr: str | None, dp: str | None, dt: str | None) -> dict | None:
    """{year, round, pick, team} for drafts from DRAFT_API_FROM (the NFL draft API's); None otherwise."""
    year = an.inum(r.get(dy)) if dy else None
    if year is None or year < DRAFT_API_FROM:
        return None
    return {"year": year, "round": an.inum(r.get(dr)) if dr else None, "pick": an.inum(r.get(dp)) if dp else None,
            "team": an.sid(r.get(dt)) if dt else None}


def reset() -> None:
    global _PEOPLE, _ESPN
    _PEOPLE = None
    _ESPN = None


def jersey(v: Any) -> int | None:
    """A jersey number from an nflverse column (12, 12.0, "12"); None when missing or out of the 0-99 range."""
    n = an.inum(v)
    return n if n is not None and 0 <= n <= 99 else None


def season_numbers(season: int | None) -> dict[str, int]:
    """{gsis_id: jersey number} from the season's nflverse weekly rosters (the release the fantasy and availability
    models already read), each player's latest week; {} when the release is not on disk."""
    if season is None:
        return {}
    from oddsmarkets.nfl.analytics.context import load_release
    try:
        df = load_release("weekly_rosters", int(season), ["gsis_id", "week", "jersey_number"])
    except Exception as exc:                                     # noqa: BLE001
        logger.info("weekly rosters %s: %s", season, exc)
        return {}
    if df is None or not len(df) or "jersey_number" not in df.columns or "gsis_id" not in df.columns:
        return {}
    out: dict[str, int] = {}
    wk = df["week"] if "week" in df.columns else None
    rows = df.assign(_w=wk).sort_values("_w", na_position="first") if wk is not None else df
    for pid, j in zip(rows["gsis_id"], rows["jersey_number"]):
        pid, n = an.sid(pid), jersey(j)
        if pid and n is not None:
            out[pid] = n                                         # later weeks overwrite earlier ones
    return out


def season_roster(ctx) -> dict[str, dict]:
    """{gsis_id: {name, pos, team}} from the season's roster release (weekly rosters as a fallback)."""
    for rel in ("rosters", "weekly_rosters"):
        df = ctx.release(rel)
        if df is None or not len(df):
            continue
        idc = _col(df, "gsis_id", "player_id")
        if not idc:
            continue
        nm = _col(df, "full_name", "player_name", "display_name")
        pc = _col(df, "position", "depth_chart_position")
        tc = _col(df, "team", "recent_team")
        out = {}
        for r in df.to_dict("records"):
            pid = an.sid(r.get(idc))
            if pid:
                out[pid] = {"name": an.sid(r.get(nm)) if nm else None, "pos": an.sid(r.get(pc)) if pc else None,
                            "team": an.sid(r.get(tc)) if tc else None, "dob": str(r.get("birth_date"))[:10] if r.get("birth_date") else None}
        return out
    return {}


def info(pid: str, roster: dict | None = None, fallback_name: Any = None) -> dict:
    p = people().get(pid) or {}
    r = (roster or {}).get(pid) or {}
    pos = p.get("pos") or r.get("pos")
    return {"name": p.get("name") or r.get("name") or an.sid(fallback_name) or pid, "pos": pos,
            "group": POS_GROUP.get(str(pos or "").upper()) or p.get("group"), "dob": p.get("dob") or r.get("dob")}
