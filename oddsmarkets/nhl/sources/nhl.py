"""
NHL api-web (https://api-web.nhle.com/v1): schedule, play-by-play, boxscore, standings, rosters, players and the
DraftKings partner odds. No key; no CORS (fetched in CI or locally only); 3-5 requests a second are tolerated.

Endpoints (verified 1 Oct 2026):
  /schedule/{YYYY-MM-DD}                   gameWeek: 7 days from the date (games with id, gameType, startTimeUTC,
                                           venue, neutralSite, gameState, gameScheduleState, home/away abbrev, score,
                                           periodDescriptor, gameOutcome.lastPeriodType); nextStartDate
  /gamecenter/{id}/play-by-play            plays (eventId, sortOrder, periodDescriptor, timeInPeriod, situationCode,
                                           homeTeamDefendingSide (absent before ~2019-20), typeDescKey, details with
                                           xCoord / yCoord / zoneCode / shotType / player ids / eventOwnerTeamId),
                                           rosterSpots (teamId, playerId, names, sweaterNumber, positionCode)
  /gamecenter/{id}/boxscore                playerByGameStats per team: forwards, defense, goalies (starter flag, toi)
  /standings/{YYYY-MM-DD}                  one row per club (conference / division / wildcard sequences, GP, W, L, OTL,
                                           points, regulationWins, regulationPlusOtWins, goalFor, goalAgainst)
  /roster/{team}/{season}                  forwards / defensemen / goalies (birthDate, height, weight, shootsCatches)
  /player/{id}/landing                     bio + season totals
  /partner-game/US/now                     DraftKings moneyline (2- and 3-way), puck line and total for today's games
                                           (the one "now" URL used: it has no dated form)
Other "now" / "current" forms answer 307 to a dated form; only dated forms are called.

Game states: FUT / PRE -> scheduled, LIVE / CRIT -> live, FINAL / OFF -> final; gameScheduleState PPD -> postponed,
CNCL -> cancelled.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .. import canon
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

WEB = "https://api-web.nhle.com/v1"
INTERVAL = 0.25


def _name(node: Any) -> str | None:
    if isinstance(node, dict):
        return node.get("default")
    return node


# ── fetchers ────────────────────────────────────────────────────────────────

def schedule_week(c: Client, day: date | str) -> dict | None:
    return c.get(f"{WEB}/schedule/{str(day)[:10]}")


def pbp(c: Client, game_id: int | str) -> dict | None:
    return c.get(f"{WEB}/gamecenter/{game_id}/play-by-play")


def boxscore(c: Client, game_id: int | str) -> dict | None:
    return c.get(f"{WEB}/gamecenter/{game_id}/boxscore")


def landing(c: Client, game_id: int | str) -> dict | None:
    return c.get(f"{WEB}/gamecenter/{game_id}/landing")


def standings(c: Client, day: date | str) -> dict | None:
    return c.get(f"{WEB}/standings/{str(day)[:10]}")


def roster(c: Client, team: str, season: int) -> dict | None:
    return c.get(f"{WEB}/roster/{team}/{int(season)}")


def player_landing(c: Client, pid: int | str) -> dict | None:
    return c.get(f"{WEB}/player/{pid}/landing")


def partner_odds(c: Client, country: str = "US") -> dict | None:
    return c.get(f"{WEB}/partner-game/{country}/now")


# ── schedule ────────────────────────────────────────────────────────────────

def status_of(g: dict) -> str:
    sched = (g.get("gameScheduleState") or "OK").upper()
    if sched == "PPD":
        return "postponed"
    if sched == "CNCL":
        return "cancelled"
    st = (g.get("gameState") or "").upper()
    if st in ("FINAL", "OFF"):
        return "final"
    if st in ("LIVE", "CRIT"):
        return "live"
    return "scheduled"


def compact_game(g: dict, day: str | None = None) -> dict:
    """A GAME record (CONTRACT.md) from a schedule (or play-by-play header) game."""
    gid = int(g["id"])
    season = int(g.get("season") or canon.season_of_game(gid))
    h, a = g.get("homeTeam") or {}, g.get("awayTeam") or {}
    status = status_of(g)
    pd = g.get("periodDescriptor") or {}
    last = ((g.get("gameOutcome") or {}).get("lastPeriodType") or "").upper()
    start = g.get("startTimeUTC")
    if not day:
        day = g.get("gameDate")
    if not day and start:
        try:
            off = g.get("venueUTCOffset") or g.get("easternUTCOffset") or "-05:00"
            sign = -1 if off.startswith("-") else 1
            hh, mm = off.lstrip("+-").split(":")
            loc = datetime.fromisoformat(start.replace("Z", "+00:00")) + sign * timedelta(hours=int(hh), minutes=int(mm))
            day = loc.date().isoformat()
        except (ValueError, AttributeError):
            day = start[:10]
    home = h.get("abbrev") or canon.abbr_from_id(h.get("id"), season)
    away = a.get("abbrev") or canon.abbr_from_id(a.get("id"), season)
    rec = {"game_id": gid, "season": season, "date": day, "start": start, "type": int(g.get("gameType") or 2),
           "home": home, "away": away,
           "hs": h.get("score") if status in ("final", "live") else None,
           "as": a.get("score") if status in ("final", "live") else None,
           "status": status, "period": pd.get("number") if status in ("final", "live") else None,
           "ot": last == "OT" if status == "final" else None, "so": last == "SO" if status == "final" else None,
           "venue": _name(g.get("venue")), "neutral": bool(g.get("neutralSite")),
           "venue_tz": g.get("venueTimezone"), "lines": None, "goalies": None, "attendance": None}
    if rec["type"] == 3:
        rec["series"] = series_of(gid)
    return rec


def series_of(game_id: int | str) -> dict:
    """Playoff game id ...03RSG: round R, series S, game G."""
    s = str(game_id)
    return {"round": int(s[7]), "series": int(s[8]), "game": int(s[9])}


def week_games(raw: dict | None) -> list[dict]:
    out = []
    for d in (raw or {}).get("gameWeek") or []:
        for g in d.get("games") or []:
            if int(g.get("gameType") or 0) in canon.KEEP_TYPES:
                out.append(compact_game(g, d.get("date")))
    return out


def weeks(lo: date, hi: date):
    """Week windows [a, a + 6] covering lo .. hi."""
    a = lo
    while a <= hi:
        yield a, min(a + timedelta(days=6), hi)
        a += timedelta(days=7)


# ── standings ───────────────────────────────────────────────────────────────

def compact_standings(raw: dict | None, season: int | None = None) -> dict | None:
    rows = (raw or {}).get("standings") or []
    if not rows:
        return None
    out = []
    for r in rows:
        ab = _name(r.get("teamAbbrev"))
        out.append({"team": ab, "conference": r.get("conferenceName"), "division": r.get("divisionName"),
                    "gp": r.get("gamesPlayed"), "w": r.get("wins"), "l": r.get("losses"), "otl": r.get("otLosses"),
                    "pts": r.get("points"), "pct": r.get("pointPctg"), "rw": r.get("regulationWins"),
                    "row": r.get("regulationPlusOtWins"), "gf": r.get("goalFor"), "ga": r.get("goalAgainst"),
                    "sow": r.get("shootoutWins"), "sol": r.get("shootoutLosses"), "ties": r.get("ties"),
                    "streak": f"{r.get('streakCode') or ''}{r.get('streakCount') or ''}" or None,
                    "l10": [r.get("l10Wins"), r.get("l10Losses"), r.get("l10OtLosses")],
                    "seq": {"league": r.get("leagueSequence"), "conference": r.get("conferenceSequence"),
                            "division": r.get("divisionSequence"), "wildcard": r.get("wildcardSequence")},
                    "clinch": r.get("clinchIndicator")})
    out.sort(key=lambda x: x["seq"]["league"] or 99)
    day = rows[0].get("date")
    return {"date": day, "at": raw.get("standingsDateTimeUtc"), "season": season or rows[0].get("seasonId"),
            "rows": out}


# ── players ─────────────────────────────────────────────────────────────────

def player_from_roster(p: dict, team: str | None = None) -> dict:
    first, last = _name(p.get("firstName")), _name(p.get("lastName"))
    return {"name": f"{first} {last}".strip(), "first": first, "last": last, "pos": p.get("positionCode"),
            "shoots": p.get("shootsCatches"), "dob": p.get("birthDate"), "height": p.get("heightInInches"),
            "weight": p.get("weightInPounds"), "number": p.get("sweaterNumber"), "team": team,
            "country": p.get("birthCountry")}


def players_from_roster(raw: dict | None, team: str) -> dict[str, dict]:
    out = {}
    for grp in ("forwards", "defensemen", "goalies"):
        for p in (raw or {}).get(grp) or []:
            out[str(p["id"])] = player_from_roster(p, team)
    return out


def players_from_pbp(raw: dict | None, season: int) -> dict[str, dict]:
    out = {}
    tid = canon.team_ids(season)
    for p in (raw or {}).get("rosterSpots") or []:
        first, last = _name(p.get("firstName")), _name(p.get("lastName"))
        out[str(p["playerId"])] = {"name": f"{first} {last}".strip(), "first": first, "last": last,
                                   "pos": p.get("positionCode"), "number": p.get("sweaterNumber"),
                                   "team": tid.get(p.get("teamId")) or canon.abbr_from_id(p.get("teamId"))}
    return out


def player_from_landing(raw: dict | None) -> dict | None:
    if not raw:
        return None
    rec = player_from_roster({**raw, "positionCode": raw.get("position")}, raw.get("currentTeamAbbrev"))
    rec["active"] = raw.get("isActive")
    return rec


# ── boxscore ────────────────────────────────────────────────────────────────

def _toi(s: str | None) -> int:
    try:
        m, sec = str(s).split(":")
        return int(m) * 60 + int(sec)
    except (ValueError, AttributeError):
        return 0


def goalies_from_box(raw: dict | None) -> dict | None:
    """{"home": {"starter", "decision"?, "used": [pid...]}, "away": ...} from a boxscore."""
    pb = (raw or {}).get("playerByGameStats") or {}
    out = {}
    for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
        gs = (pb.get(key) or {}).get("goalies") or []
        used = [g for g in gs if _toi(g.get("toi")) > 0]
        starter = next((g["playerId"] for g in gs if g.get("starter")), None)
        if starter is None and used:
            starter = max(used, key=lambda g: _toi(g.get("toi")))["playerId"]
        out[side] = {"starter": starter, "used": [g["playerId"] for g in used],
                     # goalie of record: W / L, or O (an overtime / shootout loss)
                     "decision": next((g["playerId"] for g in gs if g.get("decision") in ("W", "L", "O")), None)}
    return out if any(v["starter"] for v in out.values()) else None


def goalies_from_pbp(raw: dict | None, season: int) -> dict | None:
    """Starters from the first goalieInNetId seen against each side."""
    home_id = ((raw or {}).get("homeTeam") or {}).get("id")
    out: dict[str, Any] = {"home": None, "away": None}
    for p in (raw or {}).get("plays") or []:
        d = p.get("details") or {}
        g = d.get("goalieInNetId")
        if not g or not d.get("eventOwnerTeamId"):
            continue
        if (p.get("periodDescriptor") or {}).get("periodType") == "SO":
            continue
        typ = p.get("typeDescKey")
        if typ == "blocked-shot":
            continue
        side = "away" if d["eventOwnerTeamId"] == home_id else "home"
        if out[side] is None:
            out[side] = g
        if out["home"] and out["away"]:
            break
    if not out["home"] and not out["away"]:
        return None
    return {k: {"starter": v, "used": [v] if v else [], "decision": None} for k, v in out.items()}


# ── partner odds (DraftKings via NHL) ───────────────────────────────────────

def partner_lines(raw: dict | None) -> dict[int, dict]:
    """gameId -> lines record {"src", "ml": [home, away], "puck_line": {"home", "price": [h, a]},
    "total": {"line", "over", "under"}} from a partner-game answer."""
    out: dict[int, dict] = {}
    partner = ((raw or {}).get("bettingPartner") or {}).get("name")
    for g in (raw or {}).get("games") or []:
        rec: dict[str, Any] = {"src": f"NHL partner ({partner})" if partner else "NHL partner", "ml": [None, None],
                               "puck_line": None, "total": None}
        pl: dict[str, Any] = {"home": None, "price": [None, None]}
        tot: dict[str, Any] = {"line": None, "over": None, "under": None}
        for k, side in enumerate(("home", "away")):
            for o in ((g.get(f"{side}Team") or {}).get("odds") or []):
                desc = str(o.get("description") or "").upper()
                q = str(o.get("qualifier") or "")
                try:
                    v = int(round(float(str(o.get("value")).replace("+", ""))))
                except (TypeError, ValueError):
                    continue
                if desc == "MONEY_LINE_2_WAY":
                    rec["ml"][k] = v
                elif desc == "PUCK_LINE":
                    pl["price"][k] = v
                    try:
                        line = float(q)
                        if side == "home":
                            pl["home"] = line
                        elif pl["home"] is None:
                            pl["home"] = -line
                    except ValueError:
                        pass
                elif desc == "OVER_UNDER" and q[:1].upper() in ("O", "U"):
                    try:
                        tot["line"] = float(q[1:])
                    except ValueError:
                        pass
                    tot["over" if q[:1].upper() == "O" else "under"] = v
        if pl["home"] is not None:
            rec["puck_line"] = pl
        if tot["line"] is not None:
            rec["total"] = tot
        if any(x is not None for x in rec["ml"]):
            out[int(g["gameId"])] = rec
    return out
