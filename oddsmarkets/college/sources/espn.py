"""
ESPN's public JSON for The Quant Campus: NCAA FBS football (cfb), Division I men's (mbb) and women's (wbb)
basketball. Scoreboards, summaries (box, plays, win probability, pickcenter, predictor), core odds, rankings
(AP, Coaches, CFP and CFP seedings, weekly history), conferences and per-season membership, rosters, injuries.

No key and no stated rate limit; every call goes through one `Client` (copied from the Hardwood client, with
the Campus User-Agent): paced GETs (`interval` seconds between calls, shared by every thread that uses the
client), retries with back-off on 429 / 403 / 5xx (403 is ESPN's throttling answer and gets a long pause),
a `budget` that raises `BudgetExhausted`, and None (never an exception) on a bad game.

Endpoints (sport/league from canon.ESPN; probed 19 Oct 2026)
  site  https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/
          scoreboard?dates=YYYYMMDD&groups=50&limit=500          basketball, one US day (D-I games)
          scoreboard?dates=YYYY&seasontype=2|3&week=N&groups=80&limit=500    football, one week (FBS games);
                       leagues[0].calendar = [{value: "2"|"3", entries: [{value: week, startDate, endDate}]}]
                       (postseason weeks: "1" = Bowls (every postseason game), "999" = CFP)
          summary?event=ID      boxscore, plays (basketball), drives.previous[].plays (football), winprobability,
                                pickcenter (DraftKings with open/close blocks in recent seasons; numberfire /
                                consensus in the mid-2010s), predictor, injuries, header (competitor `rank` =
                                tournament seed in NCAA tournament games), header.gameNote
          teams?groups=..&limit=1000, teams/ID/roster (today's roster only: ?season=Y answers an empty roster),
          injuries (football: a stale feed with 2020 items; kept only when dated within 60 days)
  v2    https://site.api.espn.com/apis/v2/sports/{sport}/{league}/standings?season=Y&group=80|50
          conferences (children, with divisions as grandchildren) and their member teams for any season:
          the per-season membership (realignment) and the FBS / D-I member flag
  core  https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/
          events/{id}/competitions/{id}/odds    books; DraftKings (id 100) with open/close/current blocks since about
                                                2023; several books with one line each (spread relative to the home
                                                team) around 2013-2016; "Opening" (id 23) = the opener; numberfire,
                                                teamrankings, consensus (1002-1004) are not books; anything "Live" is
                                                in-game and ignored
          seasons/Y/rankings                    ranking types of a season (1 AP, 2 Coaches, 21 CFP, 22 CFP seedings,
                                                4 ESPN power), each listing its weekly rankings
          seasons/Y/types/T/weeks/W/rankings/R  one poll: ranks[{current, points, firstPlaceVotes, team.$ref}]
          seasons/Y/teams/T/athletes?limit=1000 the season's roster as athlete ids (history)
          seasons/Y/athletes/ID                 one athlete in a season: experience (class year), height, weight,
                                                birthPlace, position

Shapes the parsers rely on: basketball scoreboard competitors carry `statistics` (rebounds, assists, fgm/fga,
ftm/fta, 3pm/3pa, points; no turnovers or offensive rebounds), `curatedRank.current` (AP rank; 99 = unranked; in
NCAA tournament games it is the SEED, in football postseason games the CFP ranking), team `conferenceId` (often
today's conference, not the season's: the standings decide membership). Football scoreboard statistics are
empty. Basketball box keys: minutes, points, FG, 3PT, FT, rebounds, assists, turnovers, steals, blocks, OREB,
DREB, fouls (no plus-minus). Games before about 2010 have box scores but no plays.
"""
from __future__ import annotations

import logging
import re
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from oddsmarkets.basketball.sources import espn as hw
from .. import canon

logger = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports"
SITE_V2 = "https://site.api.espn.com/apis/v2/sports"
CORE = "https://sports.core.api.espn.com/v2/sports"
HEADERS = {"User-Agent": "The Quant Campus (pchattani.github.io/the-quant-campus)"}
TIMEOUT = 30

NOT_BOOKS = {"1001", "1002", "1003", "1004"}        # accuscore / teamrankings / numberfire / consensus
OPENING = "23"
PREFERRED = ["100", "58", "38", "45", "36", "2", "41", "25", "20", "19", "18", "15", "21"]   # DK, ESPN BET, Caesars ...
RANK_KEYS = {"ap": "ap", "usa": "coaches", "cfp": "cfp"}


class BudgetExhausted(RuntimeError):
    pass


class Client:
    """Paced GET with retries and back-off; `budget` caps calls per run; `used`, `seconds`, `failures`,
    `throttled` are counters. Thread-safe: worker threads share the pacer, so `interval` is the gap between
    any two calls of this client."""

    def __init__(self, budget: int = 2000, interval: float = 0.5, retries: int = 4):
        self.budget, self.interval, self.retries = budget, interval, retries
        self.used, self.failures, self.seconds, self.throttled = 0, 0, 0.0, 0
        self._next = 0.0
        self._lock = threading.Lock()
        self._pause_until = 0.0
        self.session = requests.Session()

    def _slot(self) -> None:
        with self._lock:
            if self.used >= self.budget:
                raise BudgetExhausted(f"ESPN budget of {self.budget} calls spent")
            now = time.monotonic()
            start = max(now, self._next, self._pause_until)
            self._next = start + self.interval
            self.used += 1
        wait = start - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _pause(self, seconds: float) -> None:
        with self._lock:
            self._pause_until = max(self._pause_until, time.monotonic() + seconds)

    def get(self, url: str, params: dict | None = None) -> dict | None:
        for attempt in range(self.retries):
            self._slot()
            t0 = time.monotonic()
            try:
                r = self.session.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException as exc:
                self.seconds += time.monotonic() - t0
                logger.warning("espn %s %s: %s (attempt %d)", url, params, exc, attempt + 1)
                self._pause(3 * (attempt + 1))
                continue
            self.seconds += time.monotonic() - t0
            if r.status_code in (429, 403) or r.status_code >= 500:
                if r.status_code in (429, 403):
                    self.throttled += 1
                    back = int(r.headers.get("Retry-After") or 0) or 60 * (attempt + 1)
                else:
                    back = 10 * (attempt + 1)
                logger.warning("espn %s %s answered %s; pausing %ds (throttled %d so far)", url, params,
                               r.status_code, back, self.throttled)
                self._pause(back)
                continue
            if r.status_code != 200:
                logger.info("espn %s %s answered %s", url, params, r.status_code)
                self.failures += 1
                return None
            try:
                d = r.json()
            except ValueError:
                logger.warning("espn %s %s answered non-JSON", url, params)
                self.failures += 1
                return None
            return d if isinstance(d, dict) else None
        self.failures += 1
        return None


def _site(level: str) -> str:
    sp, lg = canon.ESPN[level]
    return f"{SITE}/{sp}/{lg}"


def _core(level: str) -> str:
    sp, lg = canon.ESPN[level]
    return f"{CORE}/{sp}/leagues/{lg}"


# ── fetchers ────────────────────────────────────────────────────────────────

def scoreboard_day(c: Client, level: str, yyyymmdd: str) -> dict | None:
    """One US day of games (basketball; works for football too) as ESPN's raw answer."""
    return c.get(f"{_site(level)}/scoreboard", {"dates": str(yyyymmdd), "groups": canon.GROUP[level], "limit": 500})


def scoreboard_week(c: Client, season: int, seasontype: int, week: int) -> dict | None:
    """One football week (FBS games; postseason week 1 holds every bowl and CFP game, week 999 the CFP)."""
    return c.get(f"{_site('cfb')}/scoreboard", {"dates": int(season), "seasontype": int(seasontype), "week": int(week),
                                               "groups": canon.GROUP["cfb"], "limit": 500})


def _probe_day(level: str, season: int) -> str:
    return f"{int(season)}1001" if canon.is_football(level) else f"{int(season)}0115"


def calendar(c: Client, level: str, season: int) -> list:
    """Basketball: the season's YYYYMMDD game days (ESPN's whitelist; falls back to every day of
    canon.season_window). Football: [[seasontype, week, label, start, end]] for regular and postseason weeks."""
    if canon.is_football(level):
        raw = c.get(f"{_site(level)}/scoreboard", {"dates": int(season), "seasontype": 2, "week": 1,
                                                  "groups": canon.GROUP[level], "limit": 1})
        return football_calendar(raw)
    raw = c.get(f"{_site(level)}/scoreboard", {"dates": _probe_day(level, season), "groups": canon.GROUP[level], "limit": 1})
    days = hw.calendar(raw)
    lo, hi = canon.season_window(level, season)
    days = [d for d in days if lo.strftime("%Y%m%d") <= d <= hi.strftime("%Y%m%d")]
    if not days:
        days = [(lo + timedelta(days=i)).strftime("%Y%m%d") for i in range((hi - lo).days + 1)]
    return days


def football_calendar(raw: dict | None) -> list[list]:
    out = []
    for lg in (raw or {}).get("leagues") or []:
        for sec in lg.get("calendar") or []:
            if not isinstance(sec, dict):
                continue
            st = _int(sec.get("value"))
            if st not in (2, 3):
                continue
            for e in sec.get("entries") or []:
                out.append([st, _int(e.get("value")), e.get("label"), str(e.get("startDate") or "")[:10],
                            str(e.get("endDate") or "")[:10]])
    return out


def summary(c: Client, level: str, gid: str) -> dict | None:
    d = c.get(f"{_site(level)}/summary", {"event": str(gid)})
    if d is not None and not d.get("header"):
        logger.info("espn summary %s/%s has no header", level, gid)
        return None
    return d


def core_odds(c: Client, level: str, gid: str) -> dict | None:
    return c.get(f"{_core(level)}/events/{gid}/competitions/{gid}/odds", {"limit": 50})


def _ref_id(ref: Any, kind: str) -> str | None:
    m = re.search(rf"/{kind}/(\d+)", str(ref or ""))
    return m.group(1) if m else None


def rankings(c: Client, level: str, season: int) -> dict[str, dict[str, list]]:
    """{"ap": {week: [[rank, tid, points, first_votes]]}, "coaches": {...}, "cfp": {...}, "cfp_seeds": {...}} for every
    week ESPN lists. Week labels: regular-season weeks as ESPN numbers them ("1".."16"), "pre" for a preseason
    poll, "final" for the last postseason poll, "post<N>" for other postseason polls."""
    out: dict[str, dict[str, list]] = {}
    idx = c.get(f"{_core(level)}/seasons/{int(season)}/rankings", {"limit": 50}) or {}
    for it in idx.get("items") or []:
        kind_rec = c.get(str(it.get("$ref") or "").replace("http://", "https://")) or {}
        rtype = str(kind_rec.get("type") or "")
        key = RANK_KEYS.get(rtype)
        if rtype == "tournament" and canon.is_football(level):
            key = "cfp_seeds"
        if not key:
            continue
        refs = [str(r.get("$ref") or "") for r in kind_rec.get("rankings") or []]
        post = [r for r in refs if "/types/3/" in r]
        for ref in refs:
            raw = c.get(ref.replace("http://", "https://"))
            if not raw:
                continue
            label = week_label(ref, raw, last_post=bool(post) and ref == post[-1])
            out.setdefault(key, {})[label] = parse_ranking(raw)
    return out


def week_label(ref: str, raw: dict, last_post: bool = False) -> str:
    m = re.search(r"/types/(\d+)/weeks/(\d+)/", ref)
    st, wk = (int(m.group(1)), int(m.group(2))) if m else (2, _int((raw.get("occurrence") or {}).get("number")) or 0)
    if st == 1:
        return "pre"
    if st == 3:
        occ = raw.get("occurrence") or {}
        if last_post or occ.get("last") or "final" in str(occ.get("displayValue") or "").lower():
            return "final"
        return f"post{wk}"
    return str(wk)


def parse_ranking(raw: dict) -> list[list]:
    rows = []
    for r in raw.get("ranks") or []:
        t = r.get("team") or {}
        tid = str(t.get("id") or "") or _ref_id(t.get("$ref"), "teams")
        if tid:
            rows.append([_int(r.get("current")), tid, _float(r.get("points")), _int(r.get("firstPlaceVotes"))])
    return sorted(rows, key=lambda x: (x[0] or 999))


def teams(c: Client, level: str, season: int | None = None) -> dict[str, dict]:
    """{tid: team record} of ESPN's current FBS / D-I team list (`season` is ignored by ESPN's site endpoint)."""
    d = c.get(f"{_site(level)}/teams", {"groups": canon.GROUP[level], "limit": 1000}) or {}
    out = {}
    for sp in d.get("sports") or []:
        for lg in sp.get("leagues") or []:
            for t in lg.get("teams") or []:
                t = t.get("team") or t
                if t.get("id"):
                    out[str(t["id"])] = team_rec(t)
    return out


def conferences(c: Client, level: str, season: int) -> tuple[dict[str, dict], dict[str, dict]]:
    """({cid: {"name","short","abbr","fbs"|"d1": True, "divisions": {did: name}}}, {tid: {"conference": cid,
    "division": did|None}}) for one season from ESPN's standings (the season's own membership)."""
    sp, lg = canon.ESPN[level]
    d = c.get(f"{SITE_V2}/{sp}/{lg}/standings", {"season": int(season), "group": canon.GROUP[level]})
    return parse_standings(level, d)


def parse_standings(level: str, d: dict | None) -> tuple[dict[str, dict], dict[str, dict]]:
    flag = "fbs" if canon.is_football(level) else "d1"
    confs: dict[str, dict] = {}
    members: dict[str, dict] = {}

    def entries(node):
        return [str((e.get("team") or {}).get("id") or "") for e in (node.get("standings") or {}).get("entries") or []]

    for ch in (d or {}).get("children") or []:
        cid = str(ch.get("id") or "")
        if not cid:
            continue
        confs[cid] = {"name": ch.get("name"), "short": ch.get("shortName"), "abbr": ch.get("abbreviation"), flag: True,
                      "divisions": {}}
        for t in entries(ch):
            if t:
                members[t] = {"conference": cid, "division": None}
        for div in ch.get("children") or []:
            did = str(div.get("id") or "")
            confs[cid]["divisions"][did] = div.get("shortName") or div.get("name")
            for t in entries(div):
                if t:
                    members[t] = {"conference": cid, "division": did}
    return confs, members


def roster(c: Client, level: str, tid: str, season: int | None = None) -> list[dict]:
    """Today's roster (season None): player records with class year, height, weight, hometown, position.
    A past season (`season` given): ESPN's site endpoint answers an empty roster, so this reads the core
    season roster, which lists athlete ids only ([{"id"}]); `athlete_season` gives one athlete's details."""
    if season is None:
        d = c.get(f"{_site(level)}/teams/{tid}/roster", {"limit": 500}) or {}     # without a limit ESPN stops at 100
        out = []
        for a in d.get("athletes") or []:
            if isinstance(a, dict) and "items" in a:
                out.extend(player_rec(level, x, tid) for x in a.get("items") or [])
            elif isinstance(a, dict):
                out.append(player_rec(level, a, tid))
        return [p for p in out if p.get("id")]
    d = c.get(f"{_core(level)}/seasons/{int(season)}/teams/{tid}/athletes", {"limit": 1000}) or {}
    return [{"id": i} for i in (_ref_id(x.get("$ref"), "athletes") for x in d.get("items") or []) if i]


def athlete_season(c: Client, level: str, season: int, pid: str) -> dict | None:
    """One athlete as of a season (core): class year, height, weight, hometown, position; None on failure."""
    d = c.get(f"{_core(level)}/seasons/{int(season)}/athletes/{pid}")
    if not d or not d.get("id"):
        return None
    pos = d.get("position") or {}
    rec = player_rec(level, {**d, "position": {"abbreviation": pos.get("abbreviation")}}, None)
    tid = _ref_id((d.get("team") or {}).get("$ref"), "teams")
    rec["teams"] = [tid] if tid else []
    return rec


def injuries(c: Client, level: str, max_age_days: int = 60) -> dict[str, list[list]]:
    """{tid: [[pid, status, detail, date]]} as of now (items older than `max_age_days` dropped: ESPN's college
    football feed still carries 2020 items)."""
    d = c.get(f"{_site(level)}/injuries") or {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    out: dict[str, list[list]] = {}
    for t in d.get("injuries") or []:
        tid = str(t.get("id") or "")
        for x in t.get("injuries") or []:
            when = str(x.get("date") or "")[:10]
            if when and when < cutoff:
                continue
            pid = hw._athlete_id(x.get("athlete") or {})
            if tid and pid:
                out.setdefault(tid, []).append([pid, x.get("status"), hw._injury_detail(x), when or None])
    return out


# ── small parsers ───────────────────────────────────────────────────────────

def _int(v: Any) -> int | None:
    return hw._int(v)


def _float(v: Any) -> float | None:
    try:
        if v is None or v == "" or v == "--":
            return None
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


def _am(v: Any) -> int | None:
    """American odds from '+150', '-110', 'EVEN', 150 or {"american": ...}."""
    if isinstance(v, dict):
        v = v.get("american") if v.get("american") is not None else v.get("odds")
    s = str(v or "").strip().upper()
    if s in ("EVEN", "EV", "PK"):
        return 100
    x = _float(s)
    return int(x) if x is not None and abs(x) >= 100 else None


def _line(v: Any) -> float | None:
    """'-3.5', '+2', 'o55.5', 'u147.5', 'PK' -> float."""
    s = str(v or "").strip().lower().lstrip("ou")
    if s in ("pk", "even", "ev"):
        return 0.0
    return _float(s)


def _clock(v: Any) -> int | None:
    s = str(v or "").strip()
    m = re.match(r"^(\d+):(\d{1,2})(?:\.\d+)?$", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    x = _float(s)
    return int(x) if x is not None else None


def _iso(s: Any) -> str | None:
    return hw._iso(s)


def team_rec(t: dict) -> dict:
    """A STORE team record from an ESPN team node (conference = the node's conferenceId, a weak hint)."""
    loc, nick = t.get("location"), t.get("name")
    return {"name": t.get("displayName") or " ".join(x for x in (loc, nick) if x) or None,
            "short": t.get("shortDisplayName") or loc, "abbr": t.get("abbreviation"), "location": loc,
            "nickname": t.get("nickname") if t.get("nickname") and t.get("nickname") != loc else nick,
            "colour": hw._colour(t.get("color")), "alt_colour": hw._colour(t.get("alternateColor")),
            "conference": str(t["conferenceId"]) if t.get("conferenceId") else None}


def _hometown(a: dict) -> str | None:
    bp = a.get("birthPlace") or {}
    if bp.get("displayText"):
        return bp["displayText"]
    parts = [bp.get("city"), bp.get("state") or (bp.get("country") if bp.get("country") != "USA" else None)]
    s = ", ".join(p for p in parts if p)
    return s or None


def player_rec(level: str, a: dict, tid: str | None = None) -> dict:
    pos = (a.get("position") or {}).get("abbreviation")
    h, w = _float(a.get("height")), _float(a.get("weight"))
    return {"id": hw._athlete_id(a), "name": a.get("displayName") or a.get("fullName"), "short": a.get("shortName"),
            "pos": pos, "pool": canon.pool(level, pos), "jersey": a.get("jersey"),
            "class": canon.class_year(a.get("experience")), "height_in": int(h) if h else None,
            "weight_lb": int(w) if w else None, "hometown": _hometown(a), "teams": [str(tid)] if tid else []}


def _headline(comp: dict, header: dict | None = None) -> str | None:
    for n in comp.get("notes") or []:
        if n.get("headline"):
            return n["headline"]
    return (header or {}).get("gameNote") or None


def _rank(c: dict) -> int | None:
    v = (c.get("curatedRank") or {}).get("current")
    if v is None:
        v = c.get("rank")
    v = _int(v)
    return v if v is not None and 1 <= v <= 50 else None


_BB_SB_STATS = {"fieldGoalsMade": "fgm", "fieldGoalsAttempted": "fga", "threePointFieldGoalsMade": "tpm",
                "threePointFieldGoalsAttempted": "tpa", "freeThrowsMade": "ftm", "freeThrowsAttempted": "fta",
                "rebounds": "reb", "assists": "ast", "points": "pts"}


def _sb_team_stats(c: dict) -> dict:
    out = {}
    for s in c.get("statistics") or []:
        k = _BB_SB_STATS.get(s.get("name"))
        if k:
            out[k] = _int(s.get("displayValue"))
    return out


def compact_event(level: str, ev: dict, header: dict | None = None) -> dict:
    """A GAME skeleton (CONTRACT.md 1.2) from a scoreboard event (or a summary header wrapped as one)."""
    comp = (ev.get("competitions") or [{}])[0]
    cs = {c.get("homeAway"): c for c in comp.get("competitors") or []}
    h, a = cs.get("home") or {}, cs.get("away") or {}
    status = hw._status(comp.get("status") or ev.get("status") or {})
    scored = status in ("in", "post")
    lh = [_int(x.get("value") if x.get("value") is not None else x.get("displayValue")) or 0 for x in h.get("linescores") or []]
    la = [_int(x.get("value") if x.get("value") is not None else x.get("displayValue")) or 0 for x in a.get("linescores") or []]
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    season = ev.get("season") or {}
    note = _headline(comp, header)
    conf_flag = comp.get("conferenceCompetition")
    stype, rnd, region = canon.classify(level, season.get("type"), note, conf_flag, comp.get("tournamentId"))
    home = str((h.get("team") or {}).get("id") or h.get("id") or "")
    away = str((a.get("team") or {}).get("id") or a.get("id") or "")
    rh, ra = _rank(h), _rank(a)
    ranks, seeds = {"home": rh, "away": ra}, None
    if stype == "ncaa":
        seeds = {"home": rh if rh and rh <= 16 else None, "away": ra if ra and ra <= 16 else None}
        ranks = {"home": None, "away": None}
    elif stype == "cfp" and (rh or ra):
        seeds = {"home": rh if rh and rh <= 12 else None, "away": ra if ra and ra <= 12 else None}
    team_stats = {}
    if not canon.is_football(level):
        for side, c in (("home", h), ("away", a)):
            ts = _sb_team_stats(c)
            if ts and any(v is not None for v in ts.values()) and scored:
                team_stats[home if side == "home" else away] = ts
    wk = ev.get("week") or {}
    return {
        "id": str(ev.get("id") or comp.get("id")), "date": _iso(comp.get("date") or ev.get("date")), "status": status,
        "stype": stype, "round": rnd, "region": region, "note": note,
        "week": _int(wk.get("number")) if canon.is_football(level) and isinstance(wk, dict) else None,
        "neutral": bool(comp.get("neutralSite")), "conf_game": bool(conf_flag),
        "home": home, "away": away,
        "hs": _int(h.get("score")) if scored else None, "as": _int(a.get("score")) if scored else None,
        "periods": max(len(lh), len(la)) or (_int((comp.get("status") or {}).get("period")) if scored else 0) or 0,
        "line": {"home": lh, "away": la}, "ranks": ranks, "seeds": seeds, "team_stats": team_stats, "box": {},
        "odds": _odds_scoreboard(comp, h, a),
        "predictor": None,
        "venue": {"name": venue.get("fullName"), "city": addr.get("city"), "state": addr.get("state")} if venue.get("fullName") else None,
        "attendance": _int(comp.get("attendance")) or None, "has_pbp": False, "summary": False,
        # ESPN's timeValid: false = start time not set (the date then carries a midnight-Eastern placeholder);
        # left out when ESPN does not say, so a summary header never clears a scoreboard's flag (store.merge_game)
        **({"tba": comp.get("timeValid") is False} if comp.get("timeValid") is not None else {}),
    }


def _odds_scoreboard(comp: dict, h: dict, a: dict) -> dict | None:
    """The scoreboard's current line (pregame scoreboards carry DraftKings' line): a weak, non-closing source."""
    for o in comp.get("odds") or []:
        prov = o.get("provider") or {}
        if str(prov.get("id")) in NOT_BOOKS or "live" in str(prov.get("name") or "").lower():
            continue
        ho, ao = o.get("homeTeamOdds") or {}, o.get("awayTeamOdds") or {}
        sp = _signed_spread(_float(o.get("spread")), ho, ao, _int(ho.get("moneyLine")), _int(ao.get("moneyLine")))
        return {"provider": prov.get("name"), "spread_home": sp, "total": _float(o.get("overUnder")) or None,
                "ml_home": _int(ho.get("moneyLine")), "ml_away": _int(ao.get("moneyLine")), "open_spread_home": None,
                "open_total": None, "n_books": 1, "source": "scoreboard"}
    return None


def teams_from_event(ev: dict) -> dict[str, dict]:
    out = {}
    for c in ((ev.get("competitions") or [{}])[0]).get("competitors") or []:
        t = c.get("team") or {}
        if t.get("id"):
            out[str(t["id"])] = team_rec(t)
    return out


# ── odds ────────────────────────────────────────────────────────────────────

def _signed_spread(sp: float | None, ho: dict, ao: dict, ml_h: int | None = None, ml_a: int | None = None) -> float | None:
    """The home team's line: ESPN's single `spread` is home-relative, checked against the favourite flags
    (and the moneyline when the flags are missing)."""
    if sp is None:
        return None
    if sp == 0:
        return 0.0
    hf, af = ho.get("favorite"), ao.get("favorite")
    if hf is True and sp > 0 or af is True and sp < 0:
        return -sp
    if hf is None and af is None and ml_h is not None and ml_a is not None and ml_h != ml_a:
        if (ml_h < ml_a) != (sp < 0) and abs(sp) >= 2.5:
            return -sp
    return sp


def _block(item: dict, when: str) -> dict | None:
    """Open/close/current numbers of a core odds item: {spread_home, total, ml_home, ml_away}."""
    h = (item.get("homeTeamOdds") or {}).get(when) or {}
    a = (item.get("awayTeamOdds") or {}).get(when) or {}
    tot = item.get(when) or {}
    if not h and not a and not tot:
        return None
    sp = _line((h.get("pointSpread") or {}).get("american"))
    if sp is None:
        asp = _line((a.get("pointSpread") or {}).get("american"))
        sp = -asp if asp is not None else None
    total = _line((tot.get("total") or {}).get("american") or (tot.get("total") or {}).get("alternateDisplayValue"))
    if total is None:
        total = _line((tot.get("over") or {}).get("line"))
    rec = {"spread_home": sp, "total": total or None, "ml_home": _am(h.get("moneyLine")), "ml_away": _am(a.get("moneyLine"))}
    return rec if any(v is not None for v in rec.values()) else None


def _book(item: dict) -> dict | None:
    prov = item.get("provider") or {}
    pid, name = str(prov.get("id") or ""), str(prov.get("name") or "")
    if pid in NOT_BOOKS or pid == OPENING or "live" in name.lower() or name.lower() in ("numberfire", "teamrankings", "consensus"):
        return None
    ho, ao = item.get("homeTeamOdds") or {}, item.get("awayTeamOdds") or {}
    ml_h, ml_a = _int(ho.get("moneyLine")), _int(ao.get("moneyLine"))
    b = {"id": pid, "name": name, "spread_home": _signed_spread(_float(item.get("spread")), ho, ao, ml_h, ml_a),
         "total": _float(item.get("overUnder")) or None, "ml_home": ml_h, "ml_away": ml_a,
         "open": _block(item, "open"), "close": _block(item, "close")}
    if b["open"] is None and (item.get("initialSpread") is not None or item.get("initialOverUnder") is not None):
        b["open"] = {"spread_home": _signed_spread(_float(item.get("initialSpread")), ho, ao, ml_h, ml_a),
                     "total": _float(item.get("initialOverUnder")) or None, "ml_home": None, "ml_away": None}
    if b["close"]:
        for k in ("spread_home", "total", "ml_home", "ml_away"):
            if b["close"].get(k) is not None:
                b[k] = b["close"][k]
    if all(b[k] is None for k in ("spread_home", "total", "ml_home", "ml_away")):
        return None
    return b


def _median(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def parse_odds(raw_core: dict | None) -> dict | None:
    """The GAME `odds` record from a core odds answer: the preferred book's closing numbers (DraftKings, then
    ESPN BET, Caesars ...; its `close` block when present, else its single line), or the median of the books
    when no preferred book is listed; the opener from that book's `open` block, else the "Opening" item.
    spread_home is the home team's line (negative = home favoured)."""
    items = (raw_core or {}).get("items") or []
    books = [b for b in (_book(i) for i in items) if b]
    opening = next((i for i in items if str((i.get("provider") or {}).get("id")) == OPENING), None)
    if not books:
        # 2012-2013: ESPN lists only "consensus" (with numberfire / teamrankings): its spread is the market consensus
        cons = next((i for i in items if str((i.get("provider") or {}).get("id")) == "1004"), None)
        if cons is None:
            return None
        ho, ao = cons.get("homeTeamOdds") or {}, cons.get("awayTeamOdds") or {}
        sp = _signed_spread(_float(cons.get("spread")), ho, ao)
        if sp is None and not _float(cons.get("overUnder")):
            return None
        return {"provider": "consensus", "spread_home": sp, "total": _float(cons.get("overUnder")) or None,
                "ml_home": None, "ml_away": None,
                "open_spread_home": _signed_spread(_float(cons.get("initialSpread")), ho, ao),
                "open_total": _float(cons.get("initialOverUnder")) or None, "n_books": 0, "source": "core",
                "has_close_block": False}
    rank = {p: k for k, p in enumerate(PREFERRED)}
    with_spread = [b for b in books if b["spread_home"] is not None]
    pool = with_spread or books
    if len(pool) >= 3:
        msp = statistics.median([b["spread_home"] for b in pool if b["spread_home"] is not None] or [0])
        pool = [b for b in pool if b["spread_home"] is None or abs(b["spread_home"] - msp) <= 3.5] or pool
    main = sorted(pool, key=lambda b: (rank.get(b["id"], 99), b["id"]))[0]
    if main["id"] in rank and (main.get("close") or len(pool) < 3):
        rec = {k: main.get(k) for k in ("spread_home", "total", "ml_home", "ml_away")}
        provider = main["name"]
    else:
        rec = {"spread_home": _median([b["spread_home"] for b in pool]), "total": _median([b["total"] for b in pool]),
               "ml_home": main.get("ml_home"), "ml_away": main.get("ml_away")}
        provider = "median" if len(pool) > 1 else main["name"]
    op = main.get("open")
    if op is None and opening is not None:
        ho, ao = opening.get("homeTeamOdds") or {}, opening.get("awayTeamOdds") or {}
        op = {"spread_home": _signed_spread(_float(opening.get("spread")), ho, ao), "total": _float(opening.get("overUnder")) or None}
    return {"provider": provider, **rec, "open_spread_home": (op or {}).get("spread_home"),
            "open_total": (op or {}).get("total"), "n_books": len(books), "source": "core",
            "has_close_block": bool(main.get("close"))}


def odds_from_pickcenter(raw_summary: dict | None) -> dict | None:
    """The GAME `odds` record from a summary's pickcenter when it holds a real book (DraftKings carries open and
    close blocks); None when it holds only numberfire / teamrankings / consensus or nothing."""
    picks = [p for p in (raw_summary or {}).get("pickcenter") or []
             if str((p.get("provider") or {}).get("id")) not in NOT_BOOKS and str((p.get("provider") or {}).get("id")) != OPENING
             and "live" not in str((p.get("provider") or {}).get("name") or "").lower()]
    if not picks:
        return None
    rank = {p: k for k, p in enumerate(PREFERRED)}
    p = sorted(picks, key=lambda x: rank.get(str((x.get("provider") or {}).get("id")), 99))[0]
    ho, ao = p.get("homeTeamOdds") or {}, p.get("awayTeamOdds") or {}
    ml_h, ml_a = _int(ho.get("moneyLine")), _int(ao.get("moneyLine"))
    rec = {"provider": (p.get("provider") or {}).get("name"),
           "spread_home": _signed_spread(_float(p.get("spread")), ho, ao, ml_h, ml_a),
           "total": _float(p.get("overUnder")) or None, "ml_home": ml_h, "ml_away": ml_a,
           "open_spread_home": None, "open_total": None, "n_books": 1, "source": "pickcenter"}
    ps, tot, ml = p.get("pointSpread") or {}, p.get("total") or {}, p.get("moneyline") or {}
    close = {"spread_home": _line(((ps.get("home") or {}).get("close") or {}).get("line")),
             "total": _line(((tot.get("over") or {}).get("close") or {}).get("line")),
             "ml_home": _am(((ml.get("home") or {}).get("close") or {}).get("odds")),
             "ml_away": _am(((ml.get("away") or {}).get("close") or {}).get("odds"))}
    for k, v in close.items():
        if v is not None:
            rec[k] = v
    rec["open_spread_home"] = _line(((ps.get("home") or {}).get("open") or {}).get("line"))
    rec["open_total"] = _line(((tot.get("over") or {}).get("open") or {}).get("line"))
    rec["has_close_block"] = close["spread_home"] is not None
    if all(rec[k] is None for k in ("spread_home", "total", "ml_home", "ml_away")):
        return None
    return rec


# ── summaries ───────────────────────────────────────────────────────────────

def _snake(s: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.strip("_").lower()


_FB_SPLIT = {"completions/passingAttempts": ("cmp", "att"), "fieldGoalsMade/fieldGoalAttempts": ("fgm", "fga"),
             "extraPointsMade/extraPointAttempts": ("xpm", "xpa")}


def _num(v: Any) -> float | int | None:
    x = _float(v)
    if x is None:
        return None
    return int(x) if x == int(x) else x


def _split(v: Any, sep: str = "/") -> tuple:
    m = re.match(rf"^\s*(-?\d+)\s*[{re.escape(sep)}]\s*(-?\d+)\s*$", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _fb_team_box(stats: list[dict]) -> dict:
    raw = {s.get("name"): s.get("displayValue") for s in stats or []}
    t: dict[str, Any] = {}
    t["first_downs"] = _int(raw.get("firstDowns"))
    t["total_yards"] = _int(raw.get("totalYards"))
    t["pass_yards"] = _int(raw.get("netPassingYards"))
    t["rush_yards"] = _int(raw.get("rushingYards"))
    t["rush_att"] = _int(raw.get("rushingAttempts"))
    t["pass_cmp"], t["pass_att"] = _split(raw.get("completionAttempts"), "/-")
    t["turnovers"] = _int(raw.get("turnovers"))
    t["fumbles_lost"] = _int(raw.get("fumblesLost"))
    t["ints_thrown"] = _int(raw.get("interceptions"))
    t["penalties"], t["penalty_yards"] = _split(raw.get("totalPenaltiesYards"), "-/")
    t["third_conv"], t["third_att"] = _split(raw.get("thirdDownEff"), "-/")
    t["fourth_conv"], t["fourth_att"] = _split(raw.get("fourthDownEff"), "-/")
    t["possession_s"] = _clock(raw.get("possessionTime"))
    return t


def _fb_players(cats: list[dict]) -> dict:
    out = {}
    for cat in cats or []:
        name = cat.get("name")
        keys = cat.get("keys") or []
        cols: list[str] = []
        for k in keys:
            cols.extend(_FB_SPLIT.get(k) or [_snake(k)])
        rows = []
        for a in cat.get("athletes") or []:
            pid = hw._athlete_id(a.get("athlete") or {})
            if not pid:
                continue
            row: list = [pid]
            for k, v in zip(keys, a.get("stats") or []):
                if k in _FB_SPLIT:
                    row.extend(_split(v, "/-"))
                else:
                    row.append(_num(v))
            rows.append(row)
        if name:
            out[name] = {"cols": cols, "rows": rows}
    return out


def compact_game(level: str, raw: dict) -> dict:
    """The GAME record (CONTRACT.md 1.2) from a raw summary, box included, `summary` True."""
    header = raw.get("header") or {}
    comp = (header.get("competitions") or [{}])[0]
    ev = {"id": header.get("id") or comp.get("id"), "season": header.get("season") or {}, "competitions": [comp],
          "week": header.get("week") if isinstance(header.get("week"), dict) else ({"number": header.get("week")} if header.get("week") else {})}
    g = compact_event(level, ev, header)
    gi = raw.get("gameInfo") or {}
    venue = gi.get("venue") or {}
    if venue.get("fullName"):
        addr = venue.get("address") or {}
        g["venue"] = {"name": venue.get("fullName"), "city": addr.get("city"), "state": addr.get("state")}
    if gi.get("attendance"):
        g["attendance"] = _int(gi.get("attendance")) or None
    g["odds"] = odds_from_pickcenter(raw)
    g["predictor"] = hw._predictor(raw, g.get("home"))
    box: dict[str, dict] = {}
    bx = raw.get("boxscore") or {}
    stats_by_team = {str((t.get("team") or {}).get("id")): t.get("statistics") or [] for t in bx.get("teams") or []}
    if canon.is_football(level):
        for tid, st in stats_by_team.items():
            box[tid] = {"team": _fb_team_box(st), "players": {}}
        for tp in bx.get("players") or []:
            tid = str((tp.get("team") or {}).get("id"))
            box.setdefault(tid, {"team": _fb_team_box([]), "players": {}})["players"] = _fb_players(tp.get("statistics"))
        drives = (raw.get("drives") or {}).get("previous") or []
        g["has_pbp"] = sum(len(d.get("plays") or []) for d in drives) >= 20
    else:
        for tp in bx.get("players") or []:
            tid = str((tp.get("team") or {}).get("id"))
            rows, dnp = [], []
            for st in (tp.get("statistics") or [])[:1]:
                keys = st.get("keys") or []
                for a in st.get("athletes") or []:
                    pid = hw._athlete_id(a.get("athlete") or {})
                    if not pid:
                        continue
                    row = None if a.get("didNotPlay") else hw._player_row(a, keys)
                    if row is None or (row[2] in (None, 0) and not any(row[3:17])):
                        if a.get("didNotPlay") or not a.get("stats"):
                            dnp.append([pid, a.get("reason")])
                            continue
                    rows.append(row[:17])
            team = hw._team_box(stats_by_team.get(tid, []), rows)
            team.pop("lead_changes", None)
            box[tid] = {"players": rows, "dnp": dnp, "team": team}
        plays = raw.get("plays") or []
        g["has_pbp"] = sum(1 for p in plays if str((p.get("type") or {}).get("id")) not in ("411", "412", "402")) >= hw.MIN_PBP_PLAYS
    g["box"] = box
    if g["status"] != "post":
        inj: dict[str, list[list]] = {}
        for t in raw.get("injuries") or []:
            tid = str((t.get("team") or {}).get("id") or "")
            for x in t.get("injuries") or []:
                pid = hw._athlete_id(x.get("athlete") or {})
                if tid and pid:
                    inj.setdefault(tid, []).append([pid, x.get("status"), hw._injury_detail(x)])
        g["injuries"] = inj
    if g["status"] == "post" and (g["hs"] is None or g["as"] is None) and not canon.is_football(level):
        h, a = box.get(g["home"]), box.get(g["away"])
        if h and a:
            g["hs"] = sum(r[3] or 0 for r in h["players"]) if g["hs"] is None else g["hs"]
            g["as"] = sum(r[3] or 0 for r in a["players"]) if g["as"] is None else g["as"]
    g["summary"] = True
    return g


def teams_from_summary(raw: dict) -> dict[str, dict]:
    out = {}
    comp = ((raw.get("header") or {}).get("competitions") or [{}])[0]
    for c in comp.get("competitors") or []:
        t = c.get("team") or {}
        if t.get("id"):
            out[str(t["id"])] = team_rec(t)
    return out


def players_from_summary(level: str, raw: dict) -> dict[str, dict]:
    """{pid: player record} for everyone in the box score (positions and jerseys; class comes from rosters)."""
    out: dict[str, dict] = {}
    for tp in (raw.get("boxscore") or {}).get("players") or []:
        tid = str((tp.get("team") or {}).get("id"))
        cats = tp.get("statistics") or []
        for st in (cats if canon.is_football(level) else cats[:1]):
            for a in st.get("athletes") or []:
                ath = a.get("athlete") or {}
                pid = hw._athlete_id(ath)
                if not pid or pid in out:
                    continue
                p = player_rec(level, ath, tid)
                p["class"] = p["height_in"] = p["weight_lb"] = p["hometown"] = None
                out[pid] = p
    return out


# ── play-by-play ────────────────────────────────────────────────────────────

def compact_pbp_bb(raw: dict) -> dict | None:
    """Basketball play-by-play in Hardwood's compact row format (store.PBP_COLS), or None without real plays."""
    return hw.compact_pbp(raw)


def _offense_defense(p: dict, drive_team: str | None) -> tuple[str | None, str | None]:
    off = dfn = None
    for tp in p.get("teamParticipants") or []:
        if tp.get("type") == "offense":
            off = str(tp.get("id") or "") or _ref_id((tp.get("team") or {}).get("$ref"), "teams")
        elif tp.get("type") == "defense":
            dfn = str(tp.get("id") or "") or _ref_id((tp.get("team") or {}).get("$ref"), "teams")
    if off is None:
        off = str(((p.get("start") or {}).get("team") or {}).get("id") or "") or drive_team
    return off or None, dfn or None


def compact_plays_cfb(raw: dict) -> dict | None:
    """{"drives": [DRIVE row], "plays": [PLAY row], "types": {type_id: text}} for one football game
    (store.PLAY_COLS / DRIVE_COLS), or None when the summary has no drives. Kickoffs, punts, penalties,
    timeouts and period ends are kept; `wp_home` is ESPN's home win probability after the play where given."""
    drives = (raw.get("drives") or {}).get("previous") or []
    if not drives:
        return None
    comp = ((raw.get("header") or {}).get("competitions") or [{}])[0]
    teams = [str((c.get("team") or {}).get("id")) for c in comp.get("competitors") or []]
    wp = {str(w.get("playId")): w.get("homeWinPercentage") for w in raw.get("winprobability") or []}
    types: dict[str, str] = {}
    drows, prows = [], []
    for di, d in enumerate(drives):
        dteam = str((d.get("team") or {}).get("id") or "") or None
        plays = d.get("plays") or []
        st = d.get("start") or {}
        start_yte = None
        for p in plays:
            ps = p.get("start") or {}
            if str(((ps.get("team") or {}).get("id")) or "") == (dteam or "") and ps.get("yardsToEndzone") is not None \
                    and str((p.get("type") or {}).get("id")) not in ("53", "12", "32"):
                start_yte = _int(ps.get("yardsToEndzone"))
                break
        if start_yte is None:
            start_yte = _int(st.get("yardLine"))
        drows.append([di, dteam, _int((st.get("period") or {}).get("number")), _clock((st.get("clock") or {}).get("displayValue")),
                      start_yte, _int(d.get("offensivePlays")), _int(d.get("yards")), d.get("displayResult") or d.get("result"),
                      1 if d.get("isScore") else 0])
        for p in plays:
            ty = p.get("type") or {}
            tid = _int(ty.get("id"))
            if tid is not None and ty.get("text"):
                types[str(tid)] = ty["text"]
            off, dfn = _offense_defense(p, dteam)
            if dfn is None and off in teams and len(teams) == 2:
                dfn = teams[1] if off == teams[0] else teams[0]
            s, e = p.get("start") or {}, p.get("end") or {}
            w = wp.get(str(p.get("id")))
            prows.append([_int(p.get("sequenceNumber")), di, _int((p.get("period") or {}).get("number")),
                          _clock((p.get("clock") or {}).get("displayValue")), off, dfn, tid,
                          _int(s.get("down")), _int(s.get("distance")), _int(s.get("yardsToEndzone")), _int(p.get("statYardage")),
                          _int(e.get("down")), _int(e.get("distance")), _int(e.get("yardsToEndzone")),
                          1 if p.get("scoringPlay") else 0, _int(p.get("homeScore")), _int(p.get("awayScore")),
                          1 if p.get("isTurnover") else 0, 1 if p.get("isPenalty") else 0,
                          round(float(w), 4) if w is not None else None, str(p.get("text") or "").replace("\n", " ").strip()])
    return {"drives": drows, "plays": prows, "types": types}


def season_of(raw: dict) -> int | None:
    return _int(((raw.get("header") or {}).get("season") or {}).get("year"))
