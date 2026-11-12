#!/usr/bin/env python
"""
The live-score feed: one small file (live.json) with the score, period, clock and status of every game on today's
boards, keyed by the ids the sites already use. It is separate from the site builds on purpose: a site build takes
up to an hour, this takes seconds, so the home page and every sport page read the SAME fresh numbers (QK.live in
docs/_design/quant.js) and can never disagree about a score.

Standard library only and one file, so the live workflow (the-quant-live repo) runs it with a bare Python and no
install step. One tick:

    python scripts/live_feed.py --out site/live.json --state state.json

reads the boards that are due (a board with a game on is read every 30 s; one with a start inside 15 minutes every
60 s; inside three hours every 10 minutes; otherwise every 30 minutes), merges them into the state, writes live.json
and prints one JSON line: {"changed": bool, "live": n, "next": seconds, ...}. The caller loops and deploys the file
when it changed.

Sources (all already used by the site builds; read here with the program's User-Agent, never in bursts):
  ESPN site API scoreboards   NBA, WNBA, NFL, college football / basketball / hockey, rugby union tests
  NHL web API  /v1/score/now  NHL (the Rink's game ids are the NHL's)
  MLB Stats API  /schedule    MLB and the minor leagues (the Bullpen's ids are gamePk)
  ESPN all-soccer scoreboard  football: the Footballer's fixtures (its hub.json, Sofascore ids) matched to ESPN's
                              events by kickoff time and team names; a fixture with no clear match is left out
  ESPN tennis scoreboards     ATP and WTA singles: the Ace's match cards (its index.json) matched to ESPN's
                              matches by the pair of players; entries carry the sets as well
Golf and F1 are not in the feed: their pages keep reading the hourly build.

live.json:
  {"v": 1, "at": <epoch s, this tick>, "sports": {"<sport>": {"t": <epoch s, last good read>, "g": {"<id>":
     {"s": "pre"|"live"|"final"|"off", "hs": int|null, "as": int|null, "p": period|null, "c": clock|null,
      "d": short status text|null, "st": start ISO|null}}}}}
"s": "off" is a game postponed, cancelled or suspended: readers leave their own row alone.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = "TheQuantSports/1.0 (non-commercial; +https://pchattani.github.io/the-quant-sports)"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
NHL = "https://api-web.nhle.com/v1/score/now"
MLB = "https://statsapi.mlb.com/api/v1/schedule"
KEEP_H = 18            # a game stays in the feed this long after a board last carried it
TIMEOUT = 20

# nflverse abbreviations for ESPN's (oddsmarkets/nfl/canon.py ESPN_ABBR)
NFL_ABBR = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX"}
# the rugby competitions the Scrum carries (oddsmarkets/rugby/config.py COMPS; fifteens only)
RUGBY = ("180659", "244293", "17567", "164205", "289234", "268565", "289237")

# board key -> (sport, kind, url path or league, query)
BOARDS: dict[str, tuple[str, str, str, dict]] = {
    "nba": ("basketball", "espn", "basketball/nba", {"limit": 200}),
    "wnba": ("basketball", "espn", "basketball/wnba", {"limit": 200}),
    "nfl": ("nfl", "espn_nfl", "football/nfl", {}),
    "cfb": ("college", "espn", "football/college-football", {"groups": 80, "limit": 500}),
    "mbb": ("college", "espn", "basketball/mens-college-basketball", {"groups": 50, "limit": 500}),
    "wbb": ("college", "espn", "basketball/womens-college-basketball", {"groups": 50, "limit": 500}),
    "mch": ("college", "espn", "hockey/mens-college-hockey", {"limit": 300}),
    "wch": ("college", "espn", "hockey/womens-college-hockey", {"limit": 300}),
    "nhl": ("hockey", "nhl", NHL, {}),
    "mlb": ("baseball", "mlb", MLB, {"sportId": "1,11,12,13,14", "hydrate": "linescore"}),
}
BOARDS["soccer"] = ("football", "soccer", "", {})
BOARDS["tennis-atp"] = ("tennis", "tennis", "atp", {})
BOARDS["tennis-wta"] = ("tennis", "tennis", "wta", {})
# a board is never read more often than this, whatever its games say (the tennis board is every match of the week)
MIN_CADENCE = {"tennis": 60}
for _slug in RUGBY:
    # no `dates`: ESPN answers the current match day (a date range answers 400 for rugby)
    BOARDS["rugby-" + _slug] = ("rugby", "espn", "rugby/" + _slug, {"limit": 200})


def now_s() -> int:
    return int(time.time())


def get_json(url: str, params: dict | None = None):
    """One GET; None on any failure (the caller keeps what it had and tries again at the next tick)."""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, ValueError, OSError, TimeoutError):
        return None


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# ───────────────────────────────────────────── parsers: source answer -> {id: entry}

def _espn_state(st: dict) -> str:
    t = st.get("type") or {}
    name, state = str(t.get("name") or ""), str(t.get("state") or "")
    if any(k in name for k in ("POSTPONED", "CANCEL", "SUSPENDED", "FORFEIT", "ABANDONED")):
        return "off"
    if state == "in":
        return "live"
    if state == "post":
        return "final"
    return "pre"


def parse_espn(d: dict | None) -> dict[str, dict]:
    """ESPN scoreboard events keyed by ESPN's event id (the Hardwood, Campus and Scrum ids)."""
    out: dict[str, dict] = {}
    for ev in (d or {}).get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        st = comp.get("status") or ev.get("status") or {}
        s = _espn_state(st)
        sc = {}
        for c in comp.get("competitors") or []:
            sc[c.get("homeAway")] = (_int(c.get("score")), (c.get("team") or {}).get("abbreviation"))
        if "home" not in sc or "away" not in sc or not ev.get("id"):
            continue
        shown = s in ("live", "final")
        out[str(ev["id"])] = {
            "s": s, "hs": sc["home"][0] if shown else None, "as": sc["away"][0] if shown else None,
            "p": _int(st.get("period")) if s == "live" else None,
            "c": (st.get("displayClock") or None) if s == "live" else None,
            "d": ((st.get("type") or {}).get("shortDetail") or None) if s != "pre" else None,
            "st": ev.get("date") or comp.get("date"), "_h": sc["home"][1], "_a": sc["away"][1],
            "_season": (ev.get("season") or {}).get("year"), "_stype": (ev.get("season") or {}).get("type"),
            "_week": (ev.get("week") or {}).get("number"),
        }
    return out


def nfl_game_id(e: dict) -> str | None:
    """nflverse's game id (2026_10_WAS_NYG: season, week, away, home) from an ESPN event."""
    season, stype, week = _int(e.get("_season")), _int(e.get("_stype")), _int(e.get("_week"))
    if not season or not week or stype not in (2, 3) or not e.get("_h") or not e.get("_a"):
        return None
    if stype == 3:                       # wild card 19, divisional 20, conference 21, Super Bowl 22 (ESPN: 1, 2, 3, 5)
        week = 18 + (week if week <= 3 else 4)
    h, a = NFL_ABBR.get(e["_h"], e["_h"]), NFL_ABBR.get(e["_a"], e["_a"])
    return f"{season}_{week:02d}_{a}_{h}"


def parse_espn_nfl(d: dict | None) -> dict[str, dict]:
    out = {}
    for eid, e in parse_espn(d).items():
        gid = nfl_game_id(e)
        if gid:
            e["eid"] = eid               # ESPN's event id: kept in the state for the live model, not published
            out[gid] = e
    return out


def parse_nhl(d: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for g in (d or {}).get("games") or []:
        state = str(g.get("gameState") or "")
        sched = str(g.get("gameScheduleState") or "OK")
        s = "off" if sched not in ("OK", "") else "live" if state in ("LIVE", "CRIT") else "final" if state in ("FINAL", "OFF") else "pre"
        h, a = g.get("homeTeam") or {}, g.get("awayTeam") or {}
        pd, clock = g.get("periodDescriptor") or {}, g.get("clock") or {}
        ptype = str(pd.get("periodType") or "")
        d_txt = None
        if s == "live" and clock.get("inIntermission"):
            d_txt = "Intermission"
        elif s == "final":
            d_txt = "Final/SO" if ptype == "SO" else "Final/OT" if ptype == "OT" else "Final"
        shown = s in ("live", "final")
        if not g.get("id"):
            continue
        out[str(g["id"])] = {
            "s": s, "hs": _int(h.get("score")) if shown else None, "as": _int(a.get("score")) if shown else None,
            "p": _int(pd.get("number")) if s == "live" else None,
            "c": (clock.get("timeRemaining") or None) if s == "live" else None, "d": d_txt, "st": g.get("startTimeUTC"),
        }
    return out


def parse_mlb(d: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for day in (d or {}).get("dates") or []:
        for g in day.get("games") or []:
            st = g.get("status") or {}
            ab, detail = str(st.get("abstractGameState") or ""), str(st.get("detailedState") or "")
            if any(k in detail for k in ("Postponed", "Cancelled", "Suspended")):
                s = "off"
            else:
                s = "live" if ab == "Live" and detail not in ("Warmup", "Pre-Game", "Delayed Start") else "final" if ab == "Final" else "pre"
            ls, tm = g.get("linescore") or {}, g.get("teams") or {}
            shown = s in ("live", "final")
            inning = _int(ls.get("currentInning"))
            if not g.get("gamePk"):
                continue
            out[str(g["gamePk"])] = {
                "s": s, "hs": _int((tm.get("home") or {}).get("score")) if shown else None,
                "as": _int((tm.get("away") or {}).get("score")) if shown else None,
                "p": inning if s == "live" else None,
                "c": (str(ls.get("inningState") or "")[:3] or None) if s == "live" else None,
                "d": detail if s != "pre" else None, "st": g.get("gameDate"),
            }
    return out


def read_board(key: str) -> dict[str, dict] | None:
    """One board, parsed; None when the source did not answer."""
    sport, kind, where, q = BOARDS[key]
    if kind == "soccer":
        return read_soccer()
    if kind == "tennis":
        return read_tennis(where)
    q = dict(q)
    url = where if kind in ("nhl", "mlb") else f"{ESPN}/{where}/scoreboard"
    d = get_json(url, q)
    if not isinstance(d, dict):
        return None
    if kind == "nhl":
        return parse_nhl(d)
    if kind == "mlb":
        return parse_mlb(d)
    if kind == "espn_nfl":
        return parse_espn_nfl(d)
    return parse_espn(d)


# ───────────────────────────────────────────── football: the Footballer's fixtures matched to ESPN's soccer board
# The Footballer's ids are Sofascore's, and Sofascore is read from the PC only, on a budget. ESPN's all-soccer board
# carries most of the same matches under its own ids and names, so a fixture is matched to an ESPN event by kickoff
# time (within 15 minutes) and by both team names, and only when the match is clear: both names alike, and well
# ahead of the next best candidate. A fixture with no clear match is simply not in the feed (its page keeps the
# hourly build). Tested on 8 to 10 Nov 2026: 84 of 94 fixtures matched, none wrongly.

HUB_URL = "https://pchattani.github.io/the-quant-footballer/data/hub.json"
SOCCER_BOARD = f"{ESPN}/soccer/all/scoreboard"
_SOCCER: dict = {}         # kept in the state between ticks: {"hub_t", "fx": [[id, start, home, away]], "map": {id: espn id}}
_STOP = {"fc", "cf", "sc", "ac", "afc", "club", "de", "the", "cd", "fk", "sk", "if", "bk", "as", "ss", "us", "sv", "ca", "cs",
         "ud", "sd", "rc", "rcd", "real", "atletico", "athletic", "deportivo", "sporting", "united", "city", "town", "1",
         "04", "05", "1899", "1909"}


def _base(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def _toks(s: str) -> set[str]:
    w = _base(s).split()
    return set([x for x in w if x not in _STOP] or w)


def name_sim(site: str, names: list) -> float:
    """0..1: how alike the Footballer's team name is to any of ESPN's names for a team."""
    best, a, at = 0.0, _base(site), _toks(site)
    for n in names:
        if not n:
            continue
        b, bt = _base(n), _toks(n)
        if a == b:
            return 1.0
        r = difflib.SequenceMatcher(None, a, b).ratio()
        if (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 4:
            r = max(r, 0.9)
        j = len(at & bt) / max(1, min(len(at), len(bt))) if at & bt else 0.0
        best = max(best, j, r)
    return best


def parse_soccer_events(d: dict | None) -> list[dict]:
    out = []
    for gid, e in parse_espn(d).items():
        e["_id"] = gid
        out.append(e)
    # parse_espn keeps abbreviations only: the names are read again here
    names = {}
    for ev in (d or {}).get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        for c in comp.get("competitors") or []:
            t = c.get("team") or {}
            names[(str(ev.get("id")), c.get("homeAway"))] = [t.get("displayName"), t.get("shortDisplayName"), t.get("name"), t.get("location")]
    for e in out:
        e["_hn"], e["_an"] = names.get((e["_id"], "home")) or [], names.get((e["_id"], "away")) or []
    return out


def match_fixture(fx: list, events: list[dict]) -> dict | None:
    """The ESPN event that is this fixture, or None when no candidate is clearly it."""
    _id, start, home, away = fx
    cands = []
    for e in events:
        st = _start_s(e)
        if st is None or abs(st - start) > 900:
            continue
        cands.append((name_sim(home, e["_hn"]), name_sim(away, e["_an"]), e))
    good = sorted(((h + a, e) for h, a, e in cands if min(h, a) >= 0.6 or (max(h, a) >= 0.85 and min(h, a) >= 0.3)),
                  key=lambda x: -x[0])
    if not good or (len(good) > 1 and good[0][0] - good[1][0] <= 0.3):
        return None
    return good[0][1]


def read_soccer(now: int | None = None, getter=None) -> dict[str, dict] | None:
    now = now or now_s()
    getter = getter or get_json
    S = _SOCCER
    if "fx" not in S or now - S.get("hub_t", 0) > 900:
        hub = getter(HUB_URL, {"t": now // 600})
        if isinstance(hub, dict) and isinstance(hub.get("days"), dict):
            fx = []
            for day in hub["days"].values():
                for m in day or []:
                    st = _start_s({"st": m.get("date")})
                    if st and m.get("id") and now - 6 * 3600 <= st <= now + 30 * 3600 and m.get("status") not in ("postponed", "cancelled"):
                        fx.append([str(m["id"]), st, m.get("home") or "", m.get("away") or ""])
            S["fx"], S["hub_t"] = fx, now
        elif "fx" not in S:
            return None
    iso = lambda s: datetime.fromtimestamp(s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {f[0]: {"s": "pre", "hs": None, "as": None, "p": None, "c": None, "d": None, "st": iso(f[1])}
           for f in S["fx"] if f[1] > now - 6 * 3600}
    active = [f for f in S["fx"] if now - int(3.5 * 3600) <= f[1] <= now + 1200]
    if not active:
        return out
    # ESPN files a match under its US (Eastern) date: four or five hours behind UTC
    days = sorted({datetime.fromtimestamp(f[1] - h * 3600, timezone.utc).strftime("%Y%m%d") for f in active for h in (4, 5)})
    events: list[dict] = []
    for day in days:
        d = getter(SOCCER_BOARD, {"dates": day, "limit": 1000})
        if not isinstance(d, dict):
            return None
        events += parse_soccer_events(d)
    by_id = {e["_id"]: e for e in events}
    mp = S.setdefault("map", {})
    for f in active:
        e = by_id.get(mp.get(f[0])) or match_fixture(f, events)
        if e is None:
            if f[1] <= now:
                out[f[0]]["st"] = None       # started and not on ESPN's board: left to the hourly build, not polled for
            continue
        mp[f[0]] = e["_id"]
        out[f[0]] = dict(public(e), st=iso(f[1]))
    for k in [k for k in mp if k not in out]:
        del mp[k]
    return out


# ───────────────────────────────────────────── tennis: the Ace's match cards matched to ESPN's tennis scoreboard
# The Ace's match ids are its own (event, round, the two player ids), and its player ids are ESPN's athlete ids for
# nearly every player, so a card is matched to an ESPN match by the pair of players (two meetings of the same pair in
# one event, a round robin and a final, are told apart by date). Sets are written the Ace's way: [games p1, games
# p2, tiebreak p1, tiebreak p2] per completed set, and "live" for the set in play (oddsmarkets/tennis/sources/espn.py
# parse_competition, the same rules). "hs" / "as" are sets won by p1 / p2; "w" is the winner's id.

ACE_URL = "https://pchattani.github.io/the-quant-ace/data/index.json"
TENNIS_SINGLES = {"atp": "mens-singles", "wta": "womens-singles"}
TENNIS_DONE = {"STATUS_FINAL": "done", "STATUS_RETIRED": "ret", "STATUS_WALKOVER": "wo", "STATUS_DEFAULT": "def",
               "STATUS_DEFAULTED": "def", "STATUS_DISQUALIFIED": "def"}
TENNIS_LIVE = {"STATUS_IN_PROGRESS", "STATUS_SUSPENDED", "STATUS_DELAYED", "STATUS_RAIN_DELAY", "STATUS_END_PERIOD"}
_TENNIS: dict = {}         # kept in the state between ticks: {"t": epoch, "m": {tour: [[id, p1, p2, date]]}}


def _set_done(ga: int, gb: int) -> bool:
    hi, lo = max(ga, gb), min(ga, gb)
    return (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo == 6) or hi >= 7 and hi - lo >= 2


def _fnum(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def tennis_entry(c: dict, p1: str) -> dict | None:
    """One ESPN tennis match as a feed entry, written from p1's side."""
    name = str(((c.get("status") or {}).get("type") or {}).get("name") or "")
    done = TENNIS_DONE.get(name) or ("done" if ((c.get("status") or {}).get("type") or {}).get("completed") else None)
    s = "live" if name in TENNIS_LIVE else "final" if done else "pre"
    if any(k in name for k in ("POSTPONED", "CANCEL")):
        s = "off"
    cps = sorted(c.get("competitors") or [], key=lambda x: _fnum(x.get("order")) or 0)
    if len(cps) != 2:
        return None
    if str(cps[0].get("id")) != str(p1):
        cps = cps[::-1]
    la, lb = cps[0].get("linescores") or [], cps[1].get("linescores") or []
    full = []
    for i in range(max(len(la), len(lb))):
        x, y = (la[i] if i < len(la) else {}), (lb[i] if i < len(lb) else {})
        ga, gb = _fnum(x.get("value")), _fnum(y.get("value"))
        if ga is None and gb is None:
            continue
        full.append([ga or 0, gb or 0, _fnum(x.get("tiebreak")), _fnum(y.get("tiebreak"))])
    sets, live = [list(x) for x in full], None
    if s == "live" and full:
        ga, gb, ta, tb = full[-1]
        if _set_done(ga, gb) and not (ta is not None and ga == gb):
            live = {"set": len(full) + 1, "games": [0, 0], "points": None, "server": None}
        else:
            sets = sets[:-1]
            live = {"set": len(full), "games": [ga, gb], "points": [ta, tb] if ta is not None and ga == gb == 6 else None,
                    "server": None}
    while s != "live" and sets and sets[-1][0] == 0 and sets[-1][1] == 0:
        sets.pop()
    if s == "pre" or done == "wo":
        sets = []
    for x in sets:                       # tiebreak points only on 7-6 / 6-7 style sets
        if not (abs(x[0] - x[1]) == 1 and max(x[0], x[1]) >= 7):
            x[2] = x[3] = None
    w = str(cps[0].get("id")) if cps[0].get("winner") else str(cps[1].get("id")) if cps[1].get("winner") else None
    shown = s in ("live", "final")
    return {"s": s, "hs": sum(1 for x in sets if x[0] > x[1]) if shown else None,
            "as": sum(1 for x in sets if x[1] > x[0]) if shown else None,
            "p": live["set"] if live else None, "c": f"{live['games'][0]}-{live['games'][1]}" if live else None,
            "d": done if s == "final" else None, "st": None, "sets": sets if shown else [], "live": live,
            "w": w if s == "final" else None}


def read_tennis(tour: str, now: int | None = None, getter=None) -> dict[str, dict] | None:
    now = now or now_s()
    getter = getter or get_json
    S = _TENNIS
    if "m" not in S or now - S.get("t", 0) > 900:
        idx = getter(ACE_URL, {"t": now // 600})
        if isinstance(idx, dict) and isinstance(idx.get("tours"), dict):
            S["m"] = {T: [[str(m["id"]), str(m.get("p1")), str(m.get("p2")), str(m.get("date") or "")]
                          for k in ("live", "today", "upcoming") for m in (t.get(k) or [])
                          if m.get("id") and m.get("status") in ("live", "upcoming")]
                      for T, t in idx["tours"].items() if isinstance(t, dict)}
            S["t"] = now
        elif "m" not in S:
            return None
    mine = S["m"].get(tour) or []
    out: dict[str, dict] = {}
    for mid, _p1, _p2, date in mine:
        st = _start_s({"st": date + "Z" if len(date) == 16 else None}) if len(date) == 16 else None
        out[mid] = {"s": "pre", "hs": None, "as": None, "p": None, "c": None, "d": None,
                    "st": date + ":00Z" if st else None, "sets": [], "live": None, "w": None}
    # the board is read only on a day with a card: one dated within a day of now, or one without a time yet
    near = [m for m in mine if len(m[3]) < 16 or abs((_start_s({"st": m[3] + "Z"}) or 0) - now) < 30 * 3600]
    if not near:
        return out
    d = getter(f"{ESPN}/tennis/{tour}/scoreboard", {})
    if not isinstance(d, dict):
        return None
    pairs: dict[frozenset, list] = {}
    for ev in d.get("events") or []:
        for g in ev.get("groupings") or []:
            if ((g.get("grouping") or {}).get("slug")) != TENNIS_SINGLES.get(tour):
                continue
            for c in g.get("competitions") or []:
                ids = frozenset(str(x.get("id")) for x in c.get("competitors") or [])
                if len(ids) == 2:
                    pairs.setdefault(ids, []).append(c)
    for mid, p1, p2, date in near:
        cs = pairs.get(frozenset((p1, p2)))
        if not cs:
            continue
        if len(cs) > 1:                   # the same pair twice in one event: the meeting nearest the card's date
            cs = sorted(cs, key=lambda c: abs((_start_s({"st": c.get("date") or c.get("startDate")}) or 0)
                                                - (_start_s({"st": date + "Z"}) if len(date) == 16 else now)))
        e = tennis_entry(cs[0], p1)
        if e is None or e["s"] == "pre":
            continue
        e["st"] = out[mid]["st"]
        out[mid] = e
    return out


# ───────────────────────────────────────────── the tick

def _start_s(e: dict) -> int | None:
    try:
        return int(datetime.fromisoformat(str(e.get("st")).replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return None


def cadence(games: dict[str, dict], now: int) -> int:
    """Seconds until a board is read again, from the games it carries."""
    if any(e["s"] == "live" for e in games.values()):
        return 30
    soon = None
    for e in games.values():
        if e["s"] != "pre":
            continue
        st = _start_s(e)
        if st is None:
            continue
        dt = st - now
        if dt < -6 * 3600:               # a start long past and still "pre": a stale row, not a game about to begin
            continue
        soon = dt if soon is None else min(soon, dt)
    if soon is None:
        return 1800
    if soon <= 900:
        return 60
    if soon <= 3 * 3600:
        return min(600, max(60, soon - 900))
    return 1800


def public(e: dict) -> dict:
    return {k: v for k, v in e.items() if not k.startswith("_")}


def tick(state: dict, now: int | None = None, reader=read_board) -> dict:
    """Read the boards that are due into `state` (kept between ticks) and return the feed document."""
    global _SOCCER, _TENNIS
    now = now or now_s()
    _SOCCER = state.setdefault("soccer", {})
    _TENNIS = state.setdefault("tennis", {})
    boards = state.setdefault("boards", {})          # key -> {"next": epoch, "ok": epoch, "g": {id: entry + "seen"}}
    for key, (sport, kind, _w, _q) in BOARDS.items():
        b = boards.setdefault(key, {"next": 0, "ok": 0, "g": {}})
        if now < b.get("next", 0):
            continue
        got = reader(key)
        if got is None:
            b["fails"] = b.get("fails", 0) + 1
            b["next"] = now + min(300, 30 * b["fails"])      # a source that does not answer is left alone for a while
            continue
        b["fails"] = 0
        b["ok"] = now
        for gid, e in got.items():
            e = public(e)
            e["seen"] = now
            b["g"][gid] = e
        # a game the board no longer carries: kept (as last seen) for KEEP_H hours, but never left "live"
        for gid, e in list(b["g"].items()):
            if e["seen"] == now:
                continue
            if now - e["seen"] > KEEP_H * 3600:
                del b["g"][gid]
            elif e["s"] == "live" and now - e["seen"] > 900:
                del b["g"][gid]
        b["next"] = now + max(MIN_CADENCE.get(kind, 0), cadence({k: v for k, v in b["g"].items() if v["seen"] == now}, now))
    sports: dict[str, dict] = {}
    for key, (sport, _kind, _w, _q) in BOARDS.items():
        b = boards.get(key) or {}
        s = sports.setdefault(sport, {"t": 0, "g": {}})
        # a sport is as fresh as its stalest board that has a game on
        on = any(e["s"] == "live" for e in (b.get("g") or {}).values())
        if b.get("ok"):
            s["t"] = b["ok"] if not s["t"] else (min(s["t"], b["ok"]) if on or s.get("_on") else max(s["t"], b["ok"]))
            if on and not s.get("_on"):
                s["t"], s["_on"] = b["ok"], True
        for gid, e in (b.get("g") or {}).items():
            s["g"][gid] = {k: v for k, v in e.items() if k not in ("seen", "eid")}
    for s in sports.values():
        s.pop("_on", None)
    return {"v": 1, "at": now, "sports": sports}


def fingerprint(doc: dict) -> str:
    """The feed without its clocks: two documents with the same fingerprint show the same thing."""
    return json.dumps({k: v["g"] for k, v in doc["sports"].items()}, sort_keys=True, separators=(",", ":"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="live.json")
    ap.add_argument("--state", default="live_state.json")
    ap.add_argument("--summary", action="store_true", help="print the games per sport and status")
    a = ap.parse_args()
    sp = Path(a.state)
    try:
        state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    except ValueError:
        state = {}
    now = now_s()
    doc = tick(state, now)
    fp = fingerprint(doc)
    changed = fp != state.get("fp")
    state["fp"] = fp
    sp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    live = sum(1 for s in doc["sports"].values() for e in s["g"].values() if e["s"] == "live")
    nxt = max(15, min(b["next"] for b in state["boards"].values()) - now_s())
    print(json.dumps({"changed": changed, "live": live, "next": nxt, "games": sum(len(s["g"]) for s in doc["sports"].values()),
                      "failing": sorted(k for k, b in state["boards"].items() if b.get("fails"))}))
    if a.summary:
        for k, s in doc["sports"].items():
            c: dict[str, int] = {}
            for e in s["g"].values():
                c[e["s"]] = c.get(e["s"], 0) + 1
            print(f"  {k:11s} read {now - s['t'] if s['t'] else -1:>4d}s ago  {c}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
