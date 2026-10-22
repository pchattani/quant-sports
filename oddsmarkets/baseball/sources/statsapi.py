"""
MLB Stats API (statsapi.mlb.com, no key, CORS *): schedules, live feeds, teams, venues, people, standings,
rosters, injured lists and transactions for MLB (sportId 1) and Triple-A (sportId 11).

Endpoints verified on 1 Oct 2026:
  /api/v1/schedule?sportId=&startDate=&endDate=&hydrate=probablePitcher,linescore,team,weather,officials,venue,
                   lineups,decisions                one week ~ 1 MB; lineups (starting nine), officials (home plate
                                                    umpire), weather {"condition","temp","wind"}, series fields
  /api/v1.1/game/{pk}/feed/live[?fields=...]        ~ 830 KB in full; `fields` trims it to ~ 10 KB.
                                                    gameData.absChallenges {"hasChallenges", "home"/"away":
                                                    {"usedSuccessful","usedFailed","remaining"}} and moundVisits (2026)
  /api/v1/teams?sportId=&season=&hydrate=venue      names, abbreviations, league, division, venue by season
  /api/v1/venues?venueIds=&hydrate=location,fieldInfo   lat/lon, elevation (ft), azimuth, roof, turf, distances
  /api/v1/people?personIds=a,b,...                  name, bats, throws, position, birth date, debut
  /api/v1/standings?leagueId=103,104&season=        records, division and wild-card ranks
  /api/v1/teams/{id}/roster?rosterType=40Man|injured&season=
  /api/v1/transactions?startDate=&endDate=&sportId=

Raw feeds are never re-hosted (MLBAM terms); only compact GAME records go into the stores.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Iterable

from .. import canon
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

API = "https://statsapi.mlb.com/api"
HYDRATE = "probablePitcher,linescore,team,weather,officials,venue,lineups,decisions"
FEED_FIELDS = ("gameData,absChallenges,hasChallenges,away,home,usedSuccessful,usedFailed,remaining,moundVisits,used,"
               "liveData,boxscore,teams,battingOrder,team,id,linescore,innings,num,runs")
STATUS_RANK = {"final": 5, "live": 4, "suspended": 3, "pre": 2, "postponed": 1, "cancelled": 1}


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pid(x: Any) -> str | None:
    if isinstance(x, dict):
        x = x.get("id")
    return str(x) if x not in (None, "") else None


# ── schedule ────────────────────────────────────────────────────────────────

def schedule(c: Client, level: str, start: date | str, end: date | str, game_types: str | None = None) -> list[dict] | None:
    """Raw schedule games from start to end (inclusive), or None on failure."""
    p = {"sportId": canon.SPORT_ID[level], "startDate": str(start), "endDate": str(end), "hydrate": HYDRATE}
    if game_types:
        p["gameType"] = game_types
    d = c.get(f"{API}/v1/schedule", p)
    if d is None:
        return None
    return [g for day in (d.get("dates") or []) for g in (day.get("games") or [])]


def _weather(w: dict | None) -> dict | None:
    if not w or not any(w.get(k) for k in ("temp", "wind", "condition")):
        return None
    return {"temp": _int(w.get("temp")), "wind": w.get("wind"), "cond": w.get("condition")}


def _umpire_hp(officials: list | None) -> str | None:
    for o in officials or []:
        if str(o.get("officialType") or "").lower() == "home plate":
            return _pid(o.get("official"))
    return None


def _innings(ls: dict | None) -> list[list[int | None]] | None:
    inn = (ls or {}).get("innings") or []
    if not inn:
        return None
    return [[_int((x.get("away") or {}).get("runs")), _int((x.get("home") or {}).get("runs"))] for x in inn]


def compact_game(g: dict) -> dict:
    """A GAME record (CONTRACT.md section 1) from a hydrated schedule game."""
    teams = g.get("teams") or {}
    home, away = teams.get("home") or {}, teams.get("away") or {}
    htid, atid = _pid(home.get("team")), _pid(away.get("team"))
    st_ = g.get("status") or {}
    status = canon.game_status(st_.get("abstractGameState"), st_.get("detailedState"), st_.get("codedGameState"))
    gtype = g.get("gameType")
    series = None
    if gtype in canon.POSTSEASON:
        series = {"desc": g.get("seriesDescription"), "game": _int(g.get("seriesGameNumber")),
                  "of": _int(g.get("gamesInSeries"))}
    lu = g.get("lineups") or {}
    lineups = None
    if lu.get("homePlayers") or lu.get("awayPlayers"):
        lineups = {}
        if htid and lu.get("homePlayers"):
            lineups[htid] = [_pid(p) for p in lu["homePlayers"]]
        if atid and lu.get("awayPlayers"):
            lineups[atid] = [_pid(p) for p in lu["awayPlayers"]]
    dec = g.get("decisions") or {}
    decisions = {k[0]: _pid(dec.get(k)) for k in ("winner", "loser", "save") if dec.get(k)} or None
    ls = g.get("linescore") or {}
    return {
        "gpk": str(g.get("gamePk")),
        "date": g.get("officialDate") or str(g.get("gameDate") or "")[:10],
        "start": g.get("gameDate"),
        "gtype": gtype,
        "gnum": _int(g.get("gameNumber")),
        "series": series,
        "home": htid, "away": atid,
        "hs": _int(home.get("score")), "as": _int(away.get("score")),
        "status": status,
        "venue": _pid(g.get("venue")),
        "weather": _weather(g.get("weather")),
        "umpire_hp": _umpire_hp(g.get("officials")),
        "probables": {"home": _pid(home.get("probablePitcher")), "away": _pid(away.get("probablePitcher"))},
        "lineups": lineups,
        "innings": _innings(ls),
        "scheduled_innings": _int(g.get("scheduledInnings")),
        "decisions": decisions,
        "lines": None,
        "abs": None,
        "has_statcast": False,
    }


def take_game(store: dict, g: dict, merge) -> bool:
    """Merge a schedule game into a store, resolving rescheduled games (one gamePk listed on its original
    date as postponed and again on the make-up date): a record from another date only replaces one of
    lower or equal status rank. Returns True when the store changed."""
    rec = compact_game(g)
    if not rec["home"] or not rec["away"] or rec["gtype"] not in canon.SEASON_TYPES:
        return False
    old = store["games"].get(rec["gpk"])
    if old and old.get("date") != rec["date"]:
        if STATUS_RANK.get(rec["status"], 0) < STATUS_RANK.get(old.get("status"), 0):
            return False
    merge(store, rec)
    return True


def team_refs(g: dict) -> dict[str, dict]:
    """Team records carried by a hydrated schedule game (team hydrate)."""
    out = {}
    for side in ("home", "away"):
        t = ((g.get("teams") or {}).get(side) or {}).get("team") or {}
        if t.get("id"):
            out[str(t["id"])] = t
    return out


# ── teams and venues ────────────────────────────────────────────────────────

def teams(c: Client, level: str, season: int) -> list[dict]:
    d = c.get(f"{API}/v1/teams", {"sportId": canon.SPORT_ID[level], "season": season, "hydrate": "venue"})
    return list((d or {}).get("teams") or [])


def team_record(t: dict, level: str, season: int) -> dict:
    """The store's team record from a Stats API team (MLB colours and fixed fields from canon)."""
    tid = str(t.get("id"))
    league = canon.LEAGUES.get(str((t.get("league") or {}).get("id")), (t.get("league") or {}).get("name"))
    div = canon.DIVISIONS.get(str((t.get("division") or {}).get("id")), (t.get("division") or {}).get("name"))
    rec = {"name": t.get("name"), "abbr": t.get("abbreviation"), "short": t.get("teamName") or t.get("clubName"),
           "league": league, "division": div, "venue": _pid(t.get("venue")),
           "colour": (canon.TEAMS.get(tid) or {}).get("colour")}
    if level == "aaa":
        rec["parent"] = _pid(t.get("parentOrgId"))
        rec["city"] = t.get("locationName")
    return rec


def venues(c: Client, ids: Iterable[str], season: int | None = None) -> dict[str, dict]:
    ids = sorted({str(i) for i in ids if i})
    out: dict[str, dict] = {}
    for k in range(0, len(ids), 50):
        p = {"venueIds": ",".join(ids[k:k + 50]), "hydrate": "location,fieldInfo"}
        if season:
            p["season"] = season
        d = c.get(f"{API}/v1/venues", p)
        for v in (d or {}).get("venues") or []:
            out[str(v["id"])] = venue_record(v)
    return out


def venue_record(v: dict) -> dict:
    loc = v.get("location") or {}
    co = loc.get("defaultCoordinates") or {}
    fi = v.get("fieldInfo") or {}
    dims = {"lf": _int(fi.get("leftLine")), "lcf": _int(fi.get("leftCenter")), "cf": _int(fi.get("center")),
            "rcf": _int(fi.get("rightCenter")), "rf": _int(fi.get("rightLine"))}
    return {"name": v.get("name"), "city": loc.get("city"), "state": loc.get("stateAbbrev"),
            "lat": _float(co.get("latitude")), "lon": _float(co.get("longitude")), "elev_ft": _int(loc.get("elevation")),
            "azimuth": _float(loc.get("azimuthAngle")), "roof": fi.get("roofType"), "turf": fi.get("turfType"),
            "capacity": _int(fi.get("capacity")), "dims": dims if any(dims.values()) else None, "walls": None}


# ── live feed ───────────────────────────────────────────────────────────────

def feed(c: Client, gpk: str, full: bool = False) -> dict | None:
    """The game's live feed: trimmed to the ABS / mound-visit / batting-order fields unless `full`."""
    return c.get(f"{API}/v1.1/game/{gpk}/feed/live", None if full else {"fields": FEED_FIELDS})


def feed_extras(f: dict) -> dict:
    """GAME fields a feed adds to the schedule record: ABS challenges (2026), mound visits and the full
    batting order (starters in order) when the schedule had no lineups."""
    gd = f.get("gameData") or {}
    teams = gd.get("teams") or {}
    htid, atid = _pid(teams.get("home")), _pid(teams.get("away"))
    out: dict[str, Any] = {}
    ab = gd.get("absChallenges") or {}
    if ab.get("hasChallenges"):
        out["abs"] = {side: {"won": _int((ab.get(side) or {}).get("usedSuccessful")),
                             "lost": _int((ab.get(side) or {}).get("usedFailed")),
                             "left": _int((ab.get(side) or {}).get("remaining"))} for side in ("home", "away")}
    mv = gd.get("moundVisits") or {}
    if mv:
        out["mound_visits"] = {side: _int((mv.get(side) or {}).get("used")) for side in ("home", "away")}
    box = ((f.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
    lu = {}
    for side, tid in (("home", htid), ("away", atid)):
        order = (box.get(side) or {}).get("battingOrder") or []
        if tid and order:
            lu[tid] = [str(x) for x in order]
    if lu:
        out["lineups"] = lu
    return out


# ── pre-game snapshots (timecoded feed) ─────────────────────────────────────
#
# /api/v1.1/game/{pk}/feed/live/timestamps lists the times (UTC, YYYYMMDD_HHMMSS) the feed changed;
# /feed/live?timecode=T returns the feed as it stood at the latest change at or before T, and the first change when
# T is earlier than all of them. The first change is the switch to "Pre-Game" (measured 22 Oct 2026: about 1 h
# before first pitch in 2017-2024 (samples), about 3 h in 2025-2026; the 2016 feeds sampled start at first pitch). Asking for a time
# well before first pitch therefore returns the earliest state the archive holds, stamped (metaData.timeStamp)
# with the time it was published: the batting orders and probable pitchers known then.

SNAP_FIELDS = ("metaData,timeStamp,gameData,status,detailedState,abstractGameState,probablePitchers,away,home,id,datetime,"
               "dateTime,liveData,boxscore,teams,battingOrder,team")


def pregame_snapshot(c: Client, gpk: str, start: str, lead_hours: float = 6.0) -> dict | None:
    """The game's earliest archived feed state (see above), compacted (`compact_snapshot`); None on failure."""
    from datetime import datetime, timezone
    try:
        t0 = datetime.fromisoformat(str(start).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
    tc = (t0 - timedelta(hours=lead_hours)).strftime("%Y%m%d_%H%M%S")
    f = c.get(f"{API}/v1.1/game/{gpk}/feed/live", {"timecode": tc, "fields": SNAP_FIELDS})
    if f is None:
        return None
    return compact_snapshot(f, start)


def compact_snapshot(f: dict, start: str | None = None) -> dict:
    """{"ts": ISO UTC of the snapshot, "lead_min": minutes before the scheduled first pitch (positive = before),
    "state": detailed status, "lineups": {"home": [...], "away": [...]} (empty lists when not posted),
    "probables": {"home", "away"}}."""
    from datetime import datetime, timezone
    md = f.get("metaData") or {}
    gd = f.get("gameData") or {}
    ts = md.get("timeStamp")
    iso, lead = None, None
    if ts:
        try:
            t = datetime.strptime(str(ts), "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
            iso = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            s0 = start or ((gd.get("datetime") or {}).get("dateTime"))
            if s0:
                t0 = datetime.fromisoformat(str(s0).replace("Z", "+00:00")).astimezone(timezone.utc)
                lead = round((t0 - t).total_seconds() / 60, 1)
        except ValueError:
            pass
    box = ((f.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
    pp = gd.get("probablePitchers") or {}
    return {"ts": iso, "lead_min": lead, "state": (gd.get("status") or {}).get("detailedState"),
            "lineups": {s: [str(x) for x in ((box.get(s) or {}).get("battingOrder") or [])] for s in ("home", "away")},
            "probables": {s: _pid(pp.get(s)) for s in ("home", "away")}}


# ── people, standings, rosters, transactions ────────────────────────────────

def people(c: Client, ids: Iterable[str]) -> dict[str, dict]:
    """Player records (store schema) for MLBAM ids, 150 per call."""
    ids = sorted({str(i) for i in ids if i and str(i).isdigit()})
    out: dict[str, dict] = {}
    for k in range(0, len(ids), 150):
        d = c.get(f"{API}/v1/people", {"personIds": ",".join(ids[k:k + 150])})
        for p in (d or {}).get("people") or []:
            out[str(p["id"])] = person_record(p)
    return out


def person_record(p: dict) -> dict:
    first = p.get("useName") or p.get("firstName") or ""
    last = p.get("useLastName") or p.get("lastName") or ""
    short = f"{first[:1]}. {last}".strip() if first and last else (p.get("fullName") or "")
    return {"name": p.get("fullName"), "short": short, "bats": (p.get("batSide") or {}).get("code"),
            "throws": (p.get("pitchHand") or {}).get("code"), "pos": (p.get("primaryPosition") or {}).get("abbreviation"),
            "dob": p.get("birthDate"), "debut": p.get("mlbDebutDate"), "retro": None, "bbref": None, "fg": None}


def standings(c: Client, season: int, level: str = "mlb") -> dict[str, dict]:
    leagues = "103,104" if level == "mlb" else "117,112"
    d = c.get(f"{API}/v1/standings", {"leagueId": leagues, "season": season, "standingsTypes": "regularSeason"})
    out: dict[str, dict] = {}
    for rec in (d or {}).get("records") or []:
        for t in rec.get("teamRecords") or []:
            tid = _pid(t.get("team"))
            if not tid:
                continue
            out[tid] = {"w": _int(t.get("wins")), "l": _int(t.get("losses")), "div_rank": _int(t.get("divisionRank")),
                        "lg_rank": _int(t.get("leagueRank")), "wc_rank": _int(t.get("wildCardRank")),
                        "gb": t.get("gamesBack"), "wc_gb": t.get("wildCardGamesBack"),
                        "rs": _int(t.get("runsScored")), "ra": _int(t.get("runsAllowed")),
                        "clinched": t.get("clinchIndicator")}
    return out


def roster(c: Client, tid: str, kind: str = "40Man", season: int | None = None) -> list[dict]:
    p = {"rosterType": kind}
    if season:
        p["season"] = season
    d = c.get(f"{API}/v1/teams/{tid}/roster", p)
    out = []
    for r in (d or {}).get("roster") or []:
        out.append({"pid": _pid(r.get("person")), "name": (r.get("person") or {}).get("fullName"),
                    "pos": (r.get("position") or {}).get("abbreviation"),
                    "status": (r.get("status") or {}).get("description"), "note": r.get("note")})
    return out


def transactions(c: Client, start: date | str, end: date | str, level: str = "mlb") -> list[dict]:
    d = c.get(f"{API}/v1/transactions", {"startDate": str(start), "endDate": str(end), "sportId": canon.SPORT_ID[level]})
    out = []
    for t in (d or {}).get("transactions") or []:
        out.append({"id": t.get("id"), "date": t.get("date") or t.get("effectiveDate"), "pid": _pid(t.get("person")),
                    "team": _pid(t.get("toTeam")) or _pid(t.get("fromTeam")), "from": _pid(t.get("fromTeam")),
                    "to": _pid(t.get("toTeam")), "code": t.get("typeCode"), "desc": t.get("description")})
    return out


def compact_tx(t: dict) -> dict:
    """One transaction as the cache keeps it (never deployed): id (a trade's pieces share it), dates, type code, the
    person (id and name), the clubs and the description (parsed by analytics/moves.py; the site shows only the parsed
    facts)."""
    p = t.get("person") or {}
    return {"id": _int(t.get("id")), "d": str(t.get("date") or "")[:10] or None, "e": str(t.get("effectiveDate") or "")[:10] or None,
            "r": str(t.get("resolutionDate") or "")[:10] or None, "c": t.get("typeCode"), "p": _pid(p), "pn": p.get("fullName"),
            "f": _pid(t.get("fromTeam")), "fn": (t.get("fromTeam") or {}).get("name"), "t": _pid(t.get("toTeam")),
            "tn": (t.get("toTeam") or {}).get("name"), "x": t.get("description")}


def transactions_raw(c: Client, start: date | str, end: date | str, level: str = "mlb") -> list[dict] | None:
    """Every transaction from start to end (compact_tx records, duplicates dropped), or None when the call failed.
    sportId 1 lists the moves of every MLB organisation, minor-league ones included."""
    d = c.get(f"{API}/v1/transactions", {"startDate": str(start), "endDate": str(end), "sportId": canon.SPORT_ID[level]})
    if d is None:
        return None
    out, seen = [], set()
    for t in d.get("transactions") or []:
        rec = compact_tx(t)
        key = (rec["id"], rec["p"], rec["f"], rec["t"], rec["c"])
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


# MLB and the minor-league levels the prospect model reads (sportId; High-A and Single-A were "Advanced A" and "Class A"
# before 2021)
SPORT_IDS = {"mlb": 1, "aaa": 11, "aa": 12, "hia": 13, "a": 14}

# Stats API stat names -> the short keys of a stat line (fantasy actuals and the transaction ledgers)
LINE_KEYS = {
    "hitting": {"g": "gamesPlayed", "pa": "plateAppearances", "ab": "atBats", "r": "runs", "h": "hits", "d": "doubles", "t": "triples",
                "hr": "homeRuns", "rbi": "rbi", "sb": "stolenBases", "cs": "caughtStealing", "bb": "baseOnBalls", "ibb": "intentionalWalks",
                "so": "strikeOuts", "hbp": "hitByPitch", "sf": "sacFlies", "sh": "sacBunts", "gidp": "groundIntoDoublePlay"},
    "pitching": {"g": "gamesPitched", "gs": "gamesStarted", "outs": "outs", "bf": "battersFaced", "w": "wins", "l": "losses", "sv": "saves",
                 "svo": "saveOpportunities", "hld": "holds", "bs": "blownSaves", "gf": "gamesFinished", "h": "hits", "r": "runs",
                 "er": "earnedRuns", "hr": "homeRuns", "bb": "baseOnBalls", "ibb": "intentionalWalks", "hbp": "hitBatsmen", "so": "strikeOuts",
                 "cg": "completeGames", "sho": "shutouts"},
}


def stat_lines(c: Client, group: str, level: str = "mlb", season: int | None = None, start: date | str | None = None,
               end: date | str | None = None, page: int = 3000) -> dict[str, dict] | None:
    """Every player's counting stats for a season (`season`) or a date range (`start`..`end`), {pid: {key: n, "team":
    club id or None for more than one, "teams": n, "age"}}; None when a call failed. Rows of one player (a traded
    player's clubs, when the API splits them) are summed."""
    keys = LINE_KEYS[group]
    p = {"group": group, "sportId": SPORT_IDS.get(level) or canon.SPORT_ID[level], "playerPool": "ALL", "limit": page, "offset": 0}
    if start is not None:
        p.update(stats="byDateRange", startDate=str(start), endDate=str(end or start))
        if season:
            p["season"] = season
    else:
        p.update(stats="season", season=season)
    out: dict[str, dict] = {}
    while True:
        d = c.get(f"{API}/v1/stats", dict(p))
        if d is None:
            return None
        blocks = d.get("stats") or []
        splits = (blocks[0].get("splits") if blocks else None) or []
        total = _int(blocks[0].get("totalSplits")) if blocks else 0
        for sp in splits:
            pid = _pid(sp.get("player"))
            if not pid:
                continue
            st_ = sp.get("stat") or {}
            row = {k: _int(st_.get(v)) or 0 for k, v in keys.items()}
            tid = _pid(sp.get("team"))
            nt = _int(sp.get("numTeams")) or 1
            old = out.get(pid)
            if old is None:
                row.update(team=tid if nt == 1 else None, teams=nt, age=_int(st_.get("age")))
                out[pid] = row
            elif nt > 1 and old.get("teams", 1) == 1:      # the combined row of a traded player replaces his club rows
                row.update(team=None, teams=nt, age=_int(st_.get("age")) or old.get("age"))
                out[pid] = row
            elif old.get("teams", 1) == 1 and nt == 1 and tid != old.get("team"):
                for k in keys:
                    old[k] = (old.get(k) or 0) + row[k]
                old.update(team=None, teams=old.get("teams", 1) + 1)
        p["offset"] += len(splits)
        if not splits or not total or p["offset"] >= total:
            break
    return out


def weeks(lo: date, hi: date, days: int = 7) -> list[tuple[date, date]]:
    """[lo, hi] cut into windows of `days`, newest first."""
    out = []
    d = hi
    while d >= lo:
        a = max(lo, d - timedelta(days=days - 1))
        out.append((a, d))
        d = a - timedelta(days=1)
    return out
