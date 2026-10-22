"""
Sofascore access shared by every competition's fetcher.

Two routes into the same API live here, deliberately side by side:

  - Direct JSON calls through curl_cffi, for the endpoints datafc does not wrap —
    the season list, a season's paginated event list, and standings blocks. The
    event list is what makes one fetcher serve every league: MLS has no round
    numbers and no `/rounds` endpoint at all, while the round-by-round path the
    Argentine fetcher uses costs one call per round. `events/last` and `events/next`
    page through a whole season in a handful of calls regardless of format.
  - Per-match detail (lineups with player metadata, team statistics, the shot map,
    the momentum graph, incidents), also direct, so that every call can be counted
    against one budget per run. `call` wraps datafc for the older fetchers.

Both fail over between Sofascore's hosts. Everything degrades to "no data" rather
than raising into a build: the callers write whatever arrived and the site marks
the rest stale.

RUN FROM A RESIDENTIAL CONNECTION. Sofascore blocks datacenter IPs, so none of this
works from CI; stores are fetched locally, committed, and hydrated by the build.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

logger = logging.getLogger(__name__)

HOSTS = ["api.sofascore.com", "api.sofavpn.com"]

# datafc source keys, tried in order; the first that answers is kept for the process.
_SOURCES = ["sofascore", "sofavpn"]
_active_source: str | None = None

# Pause between direct page requests. datafc rate-limits its own calls at 2/s; the
# direct route has to be polite by hand.
PAGE_PAUSE_S = 0.5

# Per-player stats kept from the ~70 Sofascore exposes per match. Everything a
# leaderboard, a percentile or a match log can use is kept; what is dropped is
# Sofascore's own composite "value" indices and bookkeeping. Every competition
# uses the same selection so the readers and the front-end share one shape.
KEEP_STATS = [
    # minutes, scoring, creation
    "minutesPlayed", "goals", "goalAssist", "expectedGoals", "expectedAssists",
    "expectedGoalsOnTarget", "totalShots", "onTargetScoringAttempt", "shotOffTarget",
    "blockedScoringAttempt", "hitWoodwork", "bigChanceCreated", "bigChanceMissed",
    "keyPass", "penaltyWon", "penaltyConceded", "penaltyMiss", "totalOffside",
    # passing and carrying
    "accuratePass", "totalPass", "accurateOwnHalfPasses", "totalOwnHalfPasses",
    "accurateOppositionHalfPasses", "totalOppositionHalfPasses",
    "accurateLongBalls", "totalLongBalls", "accurateCross", "totalCross",
    "totalContest", "wonContest", "ballCarriesCount", "progressiveBallCarriesCount",
    "totalBallCarriesDistance", "totalProgressiveBallCarriesDistance", "bestBallCarryProgression",
    "totalProgression", "touches", "unsuccessfulTouch", "dispossessed", "possessionLostCtrl",
    # defending and duels
    "duelWon", "duelLost", "aerialWon", "aerialLost", "challengeLost",
    "totalTackle", "wonTackle", "interceptionWon", "totalClearance", "clearanceOffLine",
    "outfielderBlock", "ballRecovery", "fouls", "wasFouled", "errorLeadToAShot",
    "errorLeadToAGoal", "ownGoals",
    # goalkeeping
    "saves", "savedShotsFromInsideTheBox", "goalsPrevented", "keeperSaveValue",
    "totalKeeperSweeper", "accurateKeeperSweeper", "goodHighClaim", "punches",
    # physical
    "kilometersCovered", "metersCoveredRunningKm", "metersCoveredHighSpeedRunningKm",
    "metersCoveredSprintingKm", "numberOfSprints", "topSpeed",
    # rating
    "rating",
]

# Calls one match's detail costs: lineups, team statistics, shot map, momentum graph,
# incidents. A run's call budget is spent in these units.
DETAIL_CALLS = 5
DETAIL_PAUSE_S = 0.25


class BudgetExhausted(RuntimeError):
    """Raised inside a detail fetch when the run's call budget runs out."""


class CallBudget:
    """
    A cap on detail calls for one process, shared by every competition.

    Sofascore answers an IP-wide 403 "challenge" for many hours after a burst of a
    few thousand calls. The hourly task used to be able to reach that on a busy
    match day by itself (nineteen competitions, forty matches each, four calls a
    match), which is what kept re-triggering the block. One budget per run, spent
    round-robin across competitions, keeps every run well under it.
    """

    def __init__(self, limit: int) -> None:
        self.limit = int(limit)
        self.used = 0

    @property
    def left(self) -> int:
        return max(self.limit - self.used, 0)

    def take(self, n: int = 1) -> bool:
        if self.used + n > self.limit:
            return False
        self.used += n
        return True

SHOT_COLS = [
    "player_name", "is_home", "player_coordinates_x", "player_coordinates_y",
    "xg", "xgot", "shot_type", "body_part", "situation", "time",
]
MOMENTUM_COLS = ["minute", "value"]

# Sofascore `status.type` values. Anything else (postponed, cancelled, interrupted)
# is treated as still to be played, which is right for a postponement and wrong
# only for the rare abandoned fixture.
STATUS_FINISHED = "finished"
STATUS_LIVE = "inprogress"


# ── direct JSON route ────────────────────────────────────────────────────────

def get_json(path: str, timeout: int = 20, quiet: bool = False) -> dict | None:
    """GET an API path, trying each host. None on total failure — never raises."""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        logger.error("curl_cffi is required (it ships with datafc). Run: uv sync")
        return None

    global LAST_STATUS
    for host in HOSTS:
        url = f"https://{host}/api/v1{path}"
        try:
            resp = curl_requests.get(url, impersonate="chrome", timeout=timeout)
            LAST_STATUS = int(resp.status_code)
            if resp.status_code == 200:
                return resp.json()
            logger.debug("%s -> HTTP %s", url, resp.status_code)
        except Exception as exc:  # noqa: BLE001
            LAST_STATUS = None
            logger.debug("%s failed: %s", url, exc)
    (logger.debug if quiet else logger.warning)("All hosts failed for %s", path)
    return None


# The HTTP status of the most recent direct call (None for a transport failure).
# A 403 is Sofascore's IP-wide "challenge": once it appears, every further call
# in the run is wasted and may prolong the block, so the fetchers stop.
LAST_STATUS: int | None = None


def is_blocked() -> bool:
    return LAST_STATUS == 403


def list_seasons(tournament_id: int) -> list[dict]:
    """Every season Sofascore knows for a unique-tournament, newest first."""
    payload = get_json(f"/unique-tournament/{tournament_id}/seasons")
    if not payload:
        return []
    return [
        {"season_id": s.get("id"), "name": str(s.get("name", "")), "year": s.get("year")}
        for s in payload.get("seasons", [])
    ]


def season_events(tournament_id: int, season_id: int) -> list[dict]:
    """
    Every event of a season — played and scheduled — via the paginated
    `events/last` and `events/next` endpoints.

    Pagination stops on `hasNextPage`, or on the first page that fails, in which
    case whatever arrived is returned: a partial season is still useful for the
    matches it covers, and the caller keeps previously stored fixtures anyway.
    """
    out: list[dict] = []
    for direction in ("last", "next"):
        page = 0
        while True:
            # A finished season has no upcoming events and `next/0` is a 404, which
            # is the normal case for last season rather than a failure.
            payload = get_json(
                f"/unique-tournament/{tournament_id}/season/{season_id}/events/{direction}/{page}",
                quiet=(direction == "next" and page == 0),
            )
            if not payload:
                break
            out.extend(payload.get("events") or [])
            if not payload.get("hasNextPage"):
                break
            page += 1
            time.sleep(PAGE_PAUSE_S)
        time.sleep(PAGE_PAUSE_S)
    # A match can appear on both the last page of `last` and the first of `next`
    # while it is live.
    seen: set = set()
    unique = []
    for ev in out:
        gid = ev.get("id")
        if gid in seen:
            continue
        seen.add(gid)
        unique.append(ev)
    return unique


def past_season_events(tournament_id: int, season_id: int, budget, start_page: int = 0) -> tuple[list[dict], bool, int]:
    """
    The events of a finished season from page `start_page` on, each page charged
    to `budget`: the `events/last` pages only (a finished season has no `next`).
    Returns (events, complete, next_page): complete is False when the budget ran
    out or a page failed part-way, and next_page is where to resume next run.
    """
    out: list[dict] = []
    page = start_page
    while True:
        if not budget.take():
            return out, False, page
        payload = get_json(f"/unique-tournament/{tournament_id}/season/{season_id}/events/last/{page}", quiet=True)
        time.sleep(PAGE_PAUSE_S)
        if not payload:
            # A 404 on the first page is a season with no events at all.
            done = LAST_STATUS == 404 and page == 0
            return out, done, page
        out.extend(payload.get("events") or [])
        if not payload.get("hasNextPage"):
            return out, True, page + 1
        page += 1


def standings_blocks(tournament_id: int, season_id: int) -> list[dict]:
    """
    Standings tables for a season, one block per table Sofascore publishes.

    A plain league has one block; MLS has three (overall plus one per conference);
    the Argentine league has one per zone per tournament plus the aggregates. Each
    block is returned as {name, rows: [{team, position, points, matches, promotion}]}
    with raw Sofascore team names — callers normalise.
    """
    payload = get_json(f"/unique-tournament/{tournament_id}/season/{season_id}/standings/total")
    if not payload:
        return []
    blocks = []
    for block in payload.get("standings", []):
        rows = []
        for row in block.get("rows", []):
            rows.append({
                "team": str((row.get("team") or {}).get("name", "")),
                "team_id": (row.get("team") or {}).get("id"),
                "position": row.get("position"),
                "points": row.get("points"),
                "matches": row.get("matches"),
                "promotion": (row.get("promotion") or {}).get("text"),
            })
        blocks.append({"name": str(block.get("name", "")).strip(), "rows": rows})
    return blocks


# ── event → store record ─────────────────────────────────────────────────────

# Knockout-round slugs across competitions, normalised to short keys. League
# rounds carry only a number and never reach this table.
PLAYOFF_SLUGS: dict[str, str] = {
    # Argentine playoffs / generic cups
    "round-of-16": "r16", "1-8": "r16", "octavos": "r16", "eighth-finals": "r16",
    "quarterfinals": "qf", "quarter-finals": "qf", "1-4": "qf", "cuartos": "qf",
    "semifinals": "sf", "semi-finals": "sf", "1-2": "sf", "semifinal": "sf",
    # UEFA knockout play-off (February); the qualifying "Playoff Round" in August
    # is filtered out by its tournament label before this is consulted.
    "playoff-round": "po", "knockout-round-play-offs": "po", "round-of-32": "po",
    # MLS Cup playoffs
    "wild-card": "wc", "wildcard": "wc", "round-1": "r1", "round-one": "r1",
    "conference-semifinals": "csf", "conference-semi-finals": "csf",
    "conference-finals": "cf", "conference-final": "cf",
    "final": "final",
}


def _score(v) -> int | None:
    """A displayed score as goals, or None: Sofascore marks an awarded or voided match with a negative number."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def playoff_round(slug: object, name: object = None, extra: dict[str, str] | None = None) -> str | None:
    """Map a Sofascore round slug or name onto a short round key, else None. `extra` overrides per competition."""
    table = {**PLAYOFF_SLUGS, **(extra or {})}
    for raw in (slug, name):
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        key = re.sub(r"[\s_/]+", "-", str(raw).strip().lower())
        if key in table:
            return table[key]
        # Longest needle first, so "conference-semifinals" is not caught by
        # "semifinals" and "conference-final" is not caught by "final". Needles
        # match whole hyphen-separated tokens only: "round-12" is a league round,
        # not "round-1" followed by a stray digit.
        for needle in sorted(table, key=len, reverse=True):
            if re.search(rf"(^|-){re.escape(needle)}(-|$)", key):
                return table[needle]
    return None


def search_tournament(query: str, country_hint: str | None = None, budget=None) -> dict | None:
    """
    The unique tournament Sofascore's search returns for a name, preferring the
    one whose category (a country or region) matches the hint. None when nothing
    matches the name closely enough.
    """
    import urllib.parse

    payload = _budgeted(f"/search/all?q={urllib.parse.quote(query)}&page=0", budget) if budget is not None \
        else get_json(f"/search/all?q={urllib.parse.quote(query)}&page=0", quiet=True)
    hits = []
    q = _fold(query)
    for r in (payload or {}).get("results") or []:
        if r.get("type") != "uniqueTournament":
            continue
        e = r.get("entity") or {}
        sport = str(((e.get("category") or {}).get("sport") or {}).get("slug") or "").lower()
        if sport and sport != "football":
            continue                                  # the Billie Jean King Cup is tennis; Copa do Brasil exists in volleyball too
        name = _fold(e.get("name"))
        category = _fold((e.get("category") or {}).get("name"))
        # Word sets, not substrings: a sponsor inside the name ("Copa Betano do
        # Brasil") must still match "Copa do Brasil".
        qt, nt = set(q.split()), set(name.split())
        if not (qt <= nt or nt <= qt):
            continue
        score = 0
        if country_hint and _fold(country_hint) in category:
            score += 2
        if name == q:
            score += 1
        if any(w in name for w in ("women", "feminino", "femenin", "frauen", "u17", "u19", "u20", "u21", "u23", "amateur", "reserve",
                                     "conifa", "futsal", "beach", "youth", "olympic")):
            score -= 5
        hits.append((score, {"id": e.get("id"), "name": e.get("name"), "category": (e.get("category") or {}).get("name")}))
    if not hits:
        return None
    hits.sort(key=lambda h: -h[0])
    return hits[0][1] if hits[0][0] >= 0 else None


def _fold(text) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _iso(ts: object) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OSError, OverflowError, TypeError):
        return None


def event_record(event: dict, canon: Callable[[str], str], season_id: int,
                 canon2: Callable[[str, str | None], str] | None = None,
                 round_slugs: dict[str, str] | None = None, international: bool = False) -> tuple[str, dict] | None:
    """
    One raw Sofascore event as a store record.

    The record shape is shared with the Argentine store (`home`, `away`, `round`,
    `status`, `hs`, `as`, `date`) with two additions: `stage` says whether the match
    is league play or a playoff, and `winner` names the side that went through
    when a playoff tie was drawn and settled on penalties — the scoreline alone
    cannot say.
    """
    gid = event.get("id")
    if canon2 is not None:
        # Cups: a club is canonicalised through the registry of its own country's
        # league, so it joins the league store's spelling.
        home = canon2(str((event.get("homeTeam") or {}).get("name", "")),
                      ((event.get("homeTeam") or {}).get("country") or {}).get("alpha3"))
        away = canon2(str((event.get("awayTeam") or {}).get("name", "")),
                      ((event.get("awayTeam") or {}).get("country") or {}).get("alpha3"))
    else:
        home = canon(str((event.get("homeTeam") or {}).get("name", "")))
        away = canon(str((event.get("awayTeam") or {}).get("name", "")))
    if gid is None or not home or not away:
        return None

    status = str((event.get("status") or {}).get("type", "") or "").lower()
    round_info = event.get("roundInfo") or {}
    ko = playoff_round(round_info.get("slug"), round_info.get("name"), round_slugs)
    # MLS playoff matches carry no roundInfo at all; the only marker is the
    # tournament label ("MLS, Playoffs"). Miss it and every playoff result lands in
    # the conference table. Cups add three more shapes on the same label: the
    # qualifying rounds before a competition proper, group-stage groups, and the
    # split-season rounds of the Belgian league.
    label = str((event.get("tournament") or {}).get("name", "") or "").lower()
    group = None
    # "Group A", "Group 1", the Nations League's "Group A1" / "League A, Group 2".
    m_group = re.search(r"\bgroup ([a-z]?\d{1,2}|[a-z])\b", label)
    if m_group:
        group = m_group.group(1).upper()
        m_league = re.search(r"\bleague ([a-d])\b", label)
        if m_league and not group.startswith(m_league.group(1).upper()):
            group = m_league.group(1).upper() + group
    else:
        # The AFC's league stage is two regional leagues; a region is a group.
        m_region = re.search(r"\b(east|west|north|south|central) region\b", label)
        if m_region:
            group = m_region.group(1).capitalize()
    # A national-team qualification competition is nothing but "qualifying"
    # matches, which are its league phase, not a stage before it.
    if international and ko:
        stage = "playoff"
    elif international:
        stage = "league"
    elif "qualif" in label and "knockout" not in label or ("playoff round" in label and "knockout" not in label and "mls" not in label):
        stage = "qualifying"
    elif "championship round" in label or "conference league playoffs" in label or "relegation round" in label:
        stage = "split"
    elif "relegation/promotion" in label or "europa playoffs" in label:
        stage = "other"
    elif ko or round_info.get("cupRoundType") or "playoff" in label or "play in" in label or "play-in" in label or "knockout" in label:
        stage = "playoff"
    else:
        stage = "league"
    round_key: object = ko if ko else round_info.get("round")
    if round_key is None and round_info.get("name"):
        round_key = str(round_info["name"])
    split_group = None
    if stage == "split":
        split_group = "top" if "championship" in label else "europe" if "conference" in label else "relegation"

    hs = _score((event.get("homeScore") or {}).get("display"))
    as_ = _score((event.get("awayScore") or {}).get("display"))
    # `display` is the score after extra time; a shoot-out is reported apart.
    ph = _score((event.get("homeScore") or {}).get("penalties"))
    pa = _score((event.get("awayScore") or {}).get("penalties"))
    winner = None
    code = event.get("winnerCode")
    if stage == "playoff" and hs is not None and hs == as_ and code in (1, 2):
        winner = home if code == 1 else away
    # A two-legged tie's winner on aggregate, when Sofascore knows it: the second
    # leg carries aggregatedWinnerCode.
    agg = event.get("aggregatedWinnerCode")
    agg_winner = (home if agg == 1 else away) if agg in (1, 2) else None
    home_country = str(((event.get("homeTeam") or {}).get("country") or {}).get("alpha3", "") or "")
    away_country = str(((event.get("awayTeam") or {}).get("country") or {}).get("alpha3", "") or "")

    return str(gid), {
        "home": home,
        "away": away,
        "round": round_key,
        "status": status,
        "hs": int(hs) if hs is not None else None,
        "as": int(as_) if as_ is not None else None,
        "date": _iso(event.get("startTimestamp")),
        "stage": stage,
        "winner": winner,
        "season_id": int(season_id),
        # Team ids drive crests; countries let cup teams find their league.
        "home_id": (event.get("homeTeam") or {}).get("id"),
        "away_id": (event.get("awayTeam") or {}).get("id"),
        "home_country": home_country or None,
        "away_country": away_country or None,
        "group": group,
        "split_group": split_group,
        "agg_winner": agg_winner,
        "leg": round_info.get("cupRoundType") and None,
        **({"pens": [int(ph), int(pa)]} if ph is not None and pa is not None else {}),
    }


# ── datafc route ─────────────────────────────────────────────────────────────

def call(fn, **kwargs):
    """Call a datafc function against whichever source works, remembering it."""
    global _active_source
    order = [_active_source] if _active_source else _SOURCES
    last_exc: Exception | None = None
    for src in order:
        try:
            out = fn(data_source=src, **kwargs)
            if _active_source != src:
                logger.info("Sofascore data source: %s", src)
                _active_source = src
            return out
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if _active_source == src:
                _active_source = None
    raise last_exc if last_exc else RuntimeError("no data source available")


def _num(value):
    """A stat value as a JSON number, or None; ints stay ints so the store stays small."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value) if value == int(value) else round(value, 4)
    return None


def _player_meta(pl: dict) -> dict:
    """What a player page needs about the person, kept once per store rather than per match."""
    country = pl.get("country") or {}
    meta = {"n": pl.get("name"), "sn": pl.get("shortName"), "pos": pl.get("position"), "slug": pl.get("slug")}
    if pl.get("dateOfBirthTimestamp") is not None:
        meta["dob"] = int(pl["dateOfBirthTimestamp"])
    if pl.get("height"):
        meta["h"] = int(pl["height"])
    if country.get("alpha3"):
        meta["c"] = str(country["alpha3"])
    if pl.get("jerseyNumber"):
        meta["no"] = str(pl["jerseyNumber"])
    return {k: v for k, v in meta.items() if v is not None}


def parse_lineups(payload: dict, side_map: dict[str, str]) -> tuple[dict, dict, dict]:
    """
    (players, player_meta, extras) from `/event/{id}/lineups`.

    `players` is the per-match lineup entry keyed by player id — name, club, the
    kept stats, position, shirt number and whether they started — which is the
    shape the readers aggregate. An unused substitute has no stats and is left
    out, as before. `extras` carries formations and the missing-players list.
    """
    players: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    extras: dict[str, dict] = {"formation": {}, "missing": {}}
    for side in ("home", "away"):
        block = payload.get(side) or {}
        if block.get("formation"):
            extras["formation"][side] = str(block["formation"])
        for entry in block.get("players") or []:
            pl = entry.get("player") or {}
            pid = pl.get("id")
            if pid is None:
                continue
            stats: dict[str, object] = {}
            for key, value in (entry.get("statistics") or {}).items():
                if key in KEEP_STATS:
                    n = _num(value)
                    if n is not None:
                        stats[key] = n
            meta[str(pid)] = _player_meta(pl)
            if not stats:
                continue
            rec: dict[str, object] = {"n": str(pl.get("name", "")), "t": side_map[side], "s": stats}
            pos = entry.get("position") or pl.get("position")
            if pos:
                rec["p"] = str(pos)
            if entry.get("substitute"):
                rec["sub"] = True
            shirt = entry.get("shirtNumber") or entry.get("jerseyNumber")
            if shirt is not None:
                rec["no"] = str(shirt)
            if entry.get("captain"):
                rec["cap"] = True
            players[str(pid)] = rec
        missing = []
        for m in block.get("missingPlayers") or []:
            pl = m.get("player") or {}
            if pl.get("name"):
                missing.append({"n": pl["name"], "id": pl.get("id"), "type": m.get("type"), "reason": m.get("reason")})
        if missing:
            extras["missing"][side] = missing
    return players, meta, extras


def parse_statistics(payload: dict) -> dict | None:
    """Whole-match team statistics as {home: {key: value}, away: {...}}; ratio stats keep their denominators under `<key>_total`."""
    out: dict[str, dict] = {"home": {}, "away": {}}
    for period in payload.get("statistics") or []:
        if str(period.get("period", "ALL")).upper() != "ALL":
            continue
        for group in period.get("groups") or []:
            for item in group.get("statisticsItems") or []:
                key = item.get("key")
                if not key:
                    continue
                for side in ("home", "away"):
                    value = _num(item.get(side + "Value"))
                    if value is not None:
                        out[side][key] = value
                    total = _num(item.get(side + "Total"))
                    if total is not None:
                        out[side][key + "_total"] = total
    return out if out["home"] or out["away"] else None


def parse_shotmap(payload: dict, side_map: dict[str, str]) -> list[dict]:
    """
    Shots with the store's field names. Coordinates are Sofascore's: `x` is the
    distance from the goal line being attacked (0 at the line), `y` runs across
    the pitch, both in percent of the pitch.
    """
    shots = []
    for s in payload.get("shotmap") or []:
        pl = s.get("player") or {}
        pc = s.get("playerCoordinates") or {}
        gm = s.get("goalMouthCoordinates") or {}
        is_home = bool(s.get("isHome"))
        rec = {
            "player_id": pl.get("id"), "player_name": pl.get("name"),
            "team": side_map["home" if is_home else "away"], "is_home": is_home,
            "x": _num(pc.get("x")), "y": _num(pc.get("y")),
            "xg": _num(s.get("xg")), "xgot": _num(s.get("xgot")),
            "shot_type": s.get("shotType"), "body_part": s.get("bodyPart"),
            "situation": s.get("situation"), "time": s.get("time"),
        }
        if s.get("addedTime") is not None:
            rec["added_time"] = s.get("addedTime")
        if s.get("goalMouthLocation"):
            rec["goal_mouth"] = s["goalMouthLocation"]
        if gm.get("y") is not None:
            rec["gm_y"], rec["gm_z"] = _num(gm.get("y")), _num(gm.get("z"))
        gk = s.get("goalkeeper") or {}
        if gk.get("name"):
            rec["goalkeeper"] = gk["name"]
        shots.append(rec)
    return shots


def parse_graph(payload: dict) -> list[dict]:
    return [
        {"minute": _num(p.get("minute")), "value": _num(p.get("value"))}
        for p in payload.get("graphPoints") or []
        if p.get("minute") is not None
    ]


def parse_incidents(payload: dict, side_map: dict[str, str]) -> list[dict]:
    """Goals, cards, substitutions and VAR decisions, flattened to the store's field names."""
    out = []
    for inc in payload.get("incidents") or []:
        kind = inc.get("incidentType")
        if kind in (None, "period", "injuryTime"):
            continue
        is_home = bool(inc.get("isHome"))
        rec: dict[str, object] = {
            "incident_type": kind, "incident_class": inc.get("incidentClass"),
            "time": inc.get("time"), "added_time": inc.get("addedTime"),
            "is_home": is_home, "team": side_map["home" if is_home else "away"],
        }
        player = inc.get("player") or inc.get("playerIn") or {}
        if player.get("name"):
            rec["player_name"] = player["name"]
            rec["player_id"] = player.get("id")
        if kind == "substitution":
            rec["player_in"] = (inc.get("playerIn") or {}).get("name")
            rec["player_out"] = (inc.get("playerOut") or {}).get("name")
            if inc.get("injury"):
                rec["injury"] = True
        elif kind == "goal":
            rec["home_score"], rec["away_score"] = inc.get("homeScore"), inc.get("awayScore")
            assist = inc.get("assist1") or {}
            if assist.get("name"):
                rec["assist"] = assist["name"]
        elif kind == "card":
            if inc.get("reason"):
                rec["reason"] = inc["reason"]
        elif kind == "varDecision":
            rec["confirmed"] = bool(inc.get("confirmed"))
        out.append(rec)
    return out


LITE_DETAIL_CALLS = 3
# Why the last fetch_match_detail returned False: "no-lineups" (Sofascore answered, no line-ups page),
# "no-stats" (line-ups without player statistics), "transport" (no answer, a 403 or a server error).
LAST_DETAIL_MISS: str | None = None


def fetch_match_detail(
    store: dict, gid: str, meta: dict, canon: Callable[[str], str],
    budget: CallBudget | None = None, lite: bool = False,
) -> bool:
    """
    Lineups, team statistics, shots, momentum and incidents for one match, written
    into the store. Five direct calls, each taken from `budget` when one is given;
    BudgetExhausted is raised when it runs out mid-match, leaving what arrived.
    `lite` (a past season's backfill) asks for the line-ups, the team statistics and
    the incidents only, three calls: everything the season totals, xG and cards
    need, without the shot map and the momentum graph that only a match page draws.

    Returns whether the lineups arrived. They carry the per-player stats every
    other payload builds on, so a match without them is a failure rather than a
    success with empty detail — which is how a completely broken detail fetch once
    reported hundreds of successes and stored nothing. On a failure LAST_DETAIL_MISS
    says whether Sofascore answered without the data or did not answer.
    """
    global LAST_DETAIL_MISS
    LAST_DETAIL_MISS = None
    side_map = {"home": meta.get("home", "home"), "away": meta.get("away", "away")}

    def get(path: str) -> dict | None:
        if budget is not None and not budget.take():
            raise BudgetExhausted(path)
        out = get_json(path, quiet=True)
        time.sleep(DETAIL_PAUSE_S)
        return out

    lineups = get(f"/event/{gid}/lineups")
    if not lineups:
        LAST_DETAIL_MISS = "no-lineups" if LAST_STATUS in (404, 410) else "transport"
        logger.warning("lineups fetch failed for %s (HTTP %s)", gid, LAST_STATUS)
        return False
    players, pmeta, extras = parse_lineups(lineups, side_map)
    if not players:
        LAST_DETAIL_MISS = "no-stats"
        logger.debug("no usable lineup stats for %s", gid)
        return False
    store.setdefault("lineups", {})[gid] = players
    store.setdefault("players", {}).update(pmeta)
    if extras.get("formation") or extras.get("missing"):
        store.setdefault("lineup_extras", {})[gid] = extras

    stats = get(f"/event/{gid}/statistics")
    parsed = parse_statistics(stats) if stats else None
    if parsed:
        store.setdefault("team_stats", {})[gid] = parsed
    if not lite:
        shots = get(f"/event/{gid}/shotmap")
        if shots:
            store.setdefault("shots", {})[gid] = parse_shotmap(shots, side_map)
        graph = get(f"/event/{gid}/graph")
        if graph:
            store.setdefault("momentum", {})[gid] = parse_graph(graph)
    incidents = get(f"/event/{gid}/incidents")
    if incidents:
        store.setdefault("incidents", {})[gid] = parse_incidents(incidents, side_map)
    return True


def parse_prematch(payload: dict, side_map: dict[str, str]) -> dict | None:
    """
    A pre-match `/event/{id}/lineups` answer, compact: whether Sofascore marks it
    confirmed (the clubs' announced XIs, about an hour before kick-off; before that
    it may serve predicted line-ups), and per side the formation, the eleven
    starters [player id, name, G/D/M/F, shirt] in Sofascore's order, and the
    missing players. None when a side has no eleven starters.
    """
    out: dict[str, Any] = {"confirmed": bool(payload.get("confirmed"))}
    for side in ("home", "away"):
        block = payload.get(side) or {}
        xi = []
        for entry in block.get("players") or []:
            pl = entry.get("player") or {}
            if pl.get("id") is None or entry.get("substitute"):
                continue
            shirt = entry.get("shirtNumber") or entry.get("jerseyNumber")
            xi.append([int(pl["id"]), str(pl.get("name") or ""), str(entry.get("position") or pl.get("position") or ""),
                       str(shirt) if shirt is not None else ""])
        if len(xi) != 11:
            return None
        rec: dict[str, Any] = {"team": side_map.get(side, side), "xi": xi}
        if block.get("formation"):
            rec["f"] = str(block["formation"])
        missing = [[m.get("player", {}).get("id"), m["player"]["name"], m.get("type"), m.get("reason")]
                   for m in block.get("missingPlayers") or [] if (m.get("player") or {}).get("name")]
        if missing:
            rec["missing"] = missing
        out[side] = rec
    return out


# Pre-match line-ups (docs/MODELS.md 2.6): asked for league matches kicking off within this many minutes, until
# Sofascore marks them confirmed, at most PREMATCH_MAX a run, from the run's one call budget.
PREMATCH_LEAD_MIN = 100
PREMATCH_MAX = 12


def prematch_queue(store: dict, now: datetime | None = None, lead_min: int = PREMATCH_LEAD_MIN) -> list[tuple[str, dict]]:
    """Matches not yet started whose kick-off is within `lead_min` minutes and whose line-ups are not stored as
    confirmed, soonest first."""
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    have = store.get("prematch") or {}
    out = []
    for gid, m in (store.get("matches") or {}).items():
        if not isinstance(m, dict) or m.get("status") in (STATUS_FINISHED, STATUS_LIVE) or m.get("superseded_by"):
            continue
        try:
            ko = datetime.fromisoformat(str(m.get("date") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if ko.tzinfo is None:
            ko = ko.replace(tzinfo=timezone.utc)
        if not (now - timedelta(minutes=5) <= ko <= now + timedelta(minutes=lead_min)):
            continue
        if (have.get(str(gid)) or {}).get("confirmed"):
            continue
        out.append((str(gid), m))
    out.sort(key=lambda kv: str(kv[1].get("date") or ""))
    return out


def fetch_prematch(store: dict, gid: str, meta: dict, budget: CallBudget | None = None,
                   now: datetime | None = None) -> bool:
    """
    One call: the line-ups of a match about to start, into store["prematch"][gid]
    with the time they were fetched (`at`), so the build can apply the line-up term
    and a later study knows what was known when. Returns whether eleven starters a
    side came back (confirmed or not).
    """
    if budget is not None and not budget.take():
        raise BudgetExhausted(f"/event/{gid}/lineups")
    payload = get_json(f"/event/{gid}/lineups", quiet=True)
    time.sleep(DETAIL_PAUSE_S)
    if not payload:
        return False
    rec = parse_prematch(payload, {"home": meta.get("home", "home"), "away": meta.get("away", "away")})
    if rec is None:
        return False
    rec["at"] = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.setdefault("prematch", {})[str(gid)] = rec
    return True


def _budgeted(path: str, budget=None, quiet: bool = True):
    """A direct call charged to a budget; BudgetExhausted when there is none left."""
    if budget is not None and not budget.take():
        raise BudgetExhausted(path)
    out = get_json(path, quiet=quiet)
    time.sleep(DETAIL_PAUSE_S)
    return out


def player_details(pid: int | str, budget=None) -> dict | None:
    """The person: position, birth date, height, country, current club, foot, market value."""
    payload = _budgeted(f"/player/{pid}", budget)
    pl = (payload or {}).get("player") if payload else None
    if not pl:
        return None
    team = pl.get("team") or {}
    country = pl.get("country") or {}
    out = {
        "id": str(pl.get("id") or pid), "name": pl.get("name"), "short_name": pl.get("shortName"),
        "slug": pl.get("slug"), "position": pl.get("position"), "height": pl.get("height"),
        "dob": pl.get("dateOfBirthTimestamp"), "country": country.get("alpha3") or country.get("name"),
        "team": team.get("name"), "team_id": team.get("id"), "foot": pl.get("preferredFoot"),
        "shirt": pl.get("jerseyNumber") or pl.get("shirtNumber"),
        "contract_until": pl.get("contractUntilTimestamp"),
    }
    mv = pl.get("proposedMarketValueRaw") or {}
    if mv.get("value"):
        out["market_value"] = mv.get("value")
        out["market_value_currency"] = mv.get("currency")
    return {k: v for k, v in out.items() if v is not None}


def player_seasons(pid: int | str, budget=None) -> list[dict] | None:
    """Every (tournament, season) Sofascore has statistics for, newest first per tournament."""
    payload = _budgeted(f"/player/{pid}/statistics/seasons", budget)
    if not payload:
        return None
    out = []
    for block in payload.get("uniqueTournamentSeasons") or []:
        ut = block.get("uniqueTournament") or {}
        for season in block.get("seasons") or []:
            out.append({
                "tid": ut.get("id"), "tname": ut.get("name"),
                "sid": season.get("id"), "sname": season.get("name"), "year": season.get("year"),
            })
    return out


def player_season_stats(pid: int | str, tid: int, sid: int, budget=None) -> dict | None:
    """One player's season statistics in one tournament, plus the club they were with."""
    payload = _budgeted(f"/player/{pid}/unique-tournament/{tid}/season/{sid}/statistics/overall", budget)
    if not payload or not payload.get("statistics"):
        return None
    stats = {k: v for k, v in payload["statistics"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    team = (payload.get("team") or {}).get("name")
    return {"stats": stats, "team": team}


def top_players(tid: int, sid: int, budget=None) -> dict | None:
    """A season's leaders per category: {category: [{id, name, team, position, value}]}."""
    payload = _budgeted(f"/unique-tournament/{tid}/season/{sid}/top-players/overall", budget)
    if not payload:
        return None
    out: dict[str, list[dict]] = {}
    for cat, rows in (payload.get("topPlayers") or {}).items():
        if not isinstance(rows, list):
            continue
        items = []
        for r in rows:
            pl = r.get("player") or {}
            st = r.get("statistics") or {}
            value = st.get(cat) if cat in st else next((v for k, v in st.items() if isinstance(v, (int, float)) and k not in ("id", "type", "appearances")), None)
            items.append({
                "id": pl.get("id"), "name": pl.get("name"), "position": pl.get("position"),
                "team": (r.get("team") or {}).get("name"), "value": value,
                "appearances": st.get("appearances"),
            })
        out[cat] = items
    return out


def search_player(name: str, budget=None) -> dict | None:
    """The first player Sofascore's search returns for a name."""
    import urllib.parse

    payload = _budgeted(f"/search/all?q={urllib.parse.quote(name)}&page=0", budget)
    for r in (payload or {}).get("results") or []:
        if r.get("type") == "player":
            e = r.get("entity") or {}
            return {"id": str(e.get("id")), "name": e.get("name"), "team": (e.get("team") or {}).get("name")}
    return None


def team_players(team_id: int | str, budget=None) -> list[dict] | None:
    """
    A club's current squad (`/team/{id}/players`): one compact row per player,
    in the PlayerMeta shape of the stores plus the contract end. None when the
    call failed (as opposed to an empty squad, which is []).
    """
    payload = _budgeted(f"/team/{team_id}/players", budget)
    if payload is None or not isinstance(payload, dict) or "players" not in payload:
        return None
    rows = []
    seen: set[str] = set()
    for item in payload.get("players") or []:
        pl = (item or {}).get("player") or {}
        pid = pl.get("id")
        if pid is None or str(pid) in seen:
            continue
        seen.add(str(pid))
        country = pl.get("country") or {}
        mv = pl.get("proposedMarketValueRaw") or {}
        row = {
            "id": str(pid), "n": pl.get("name"), "sn": pl.get("shortName"), "pos": pl.get("position"),
            "no": str(pl.get("jerseyNumber") or pl.get("shirtNumber") or "") or None,
            "dob": pl.get("dateOfBirthTimestamp"), "c": country.get("alpha3"), "h": pl.get("height"),
            "until": pl.get("contractUntilTimestamp"),
            # Sofascore's proposed market value, as the squad lists it (EUR unless `mvc` says otherwise).
            "mv": mv.get("value") if isinstance(mv, dict) and mv.get("value") else None,
            "mvc": mv.get("currency") if isinstance(mv, dict) and mv.get("value") and mv.get("currency") not in (None, "EUR") else None,
        }
        rows.append({k: v for k, v in row.items() if v is not None})
    return rows


# Sofascore's transfer `type`: 1 a loan, 2 the end of a loan (the player returns), 3 a
# permanent move (with a fee, "Free", or "-" when no fee is published: a youth promotion,
# an undisclosed fee). Checked against /team/42/transfers on 15 October 2026.
TRANSFER_KINDS = {1: "loan", 2: "loan_end", 3: "transfer"}


def parse_transfer(item: dict, pid: int | str | None = None) -> dict | None:
    """
    One transfer in the compact store shape: `i` Sofascore's transfer id, `p` the player
    id, `n` his name, `ps` his position letter, `f`/`fn` and `t`/`tn` the clubs' ids and
    names, `k` the type (1 loan, 2 loan return, 3 transfer), `fee` the fee as published
    (`cur` its currency when not EUR; None when Sofascore has no figure), `d` Sofascore's
    fee text ("59.6M €", "Free", "-"), `ts` the date (unix seconds).
    """
    if not isinstance(item, dict):
        return None
    pl = item.get("player") or {}
    pid = pl.get("id") or pid
    ts = item.get("transferDateTimestamp")
    if pid is None or not ts:
        return None
    fr, to = item.get("transferFrom") or {}, item.get("transferTo") or {}
    raw = item.get("transferFeeRaw")
    fee = raw.get("value") if isinstance(raw, dict) else None
    if fee is None and isinstance(item.get("transferFee"), (int, float)):
        fee = item.get("transferFee")
    cur = raw.get("currency") if isinstance(raw, dict) else None
    rec = {
        "i": item.get("id"), "p": str(pid), "n": pl.get("name"), "ps": pl.get("position"),
        "f": fr.get("id"), "fn": item.get("fromTeamName") or fr.get("name"),
        "t": to.get("id"), "tn": item.get("toTeamName") or to.get("name"),
        "k": item.get("type"), "fee": fee, "cur": cur if cur not in (None, "EUR") else None,
        "d": item.get("transferFeeDescription"), "ts": int(ts),
    }
    return {k: v for k, v in rec.items() if v is not None}


def transfer_key(rec: dict) -> str:
    """The store key: Sofascore's transfer id, else player, date and clubs."""
    if rec.get("i") is not None:
        return str(rec["i"])
    return f"{rec.get('p')}:{rec.get('ts')}:{rec.get('f')}:{rec.get('t')}"


def team_transfers(team_id: int | str, budget=None) -> list[dict] | None:
    """A club's recent transfers in and out (`/team/{id}/transfers`, about the last nine months). None when the call failed."""
    payload = _budgeted(f"/team/{team_id}/transfers", budget)
    if payload is None or not isinstance(payload, dict) or not ({"transfersIn", "transfersOut"} & set(payload)):
        return None
    out = []
    for key in ("transfersIn", "transfersOut"):
        for item in payload.get(key) or []:
            rec = parse_transfer(item)
            if rec:
                out.append(rec)
    return out


def player_transfer_history(pid: int | str, budget=None) -> list[dict] | None:
    """A player's whole transfer history (`/player/{id}/transfer-history`). None when the call failed."""
    payload = _budgeted(f"/player/{pid}/transfer-history", budget)
    if payload is None or not isinstance(payload, dict) or "transferHistory" not in payload:
        return None
    out = []
    for item in payload.get("transferHistory") or []:
        rec = parse_transfer(item, pid=pid)
        if rec:
            out.append(rec)
    return out


def probe(tournament_id: int, season_id: int) -> bool:
    """Connectivity check: can this machine see one page of one season?"""
    payload = get_json(f"/unique-tournament/{tournament_id}/season/{season_id}/events/last/0")
    ok = bool(payload and payload.get("events") is not None)
    logger.info("Sofascore %s", "reachable" if ok else "unreachable")
    return ok


def new_store() -> dict[str, Any]:
    return {
        "matches": {}, "lineups": {}, "shots": {}, "momentum": {},
        "incidents": {}, "players": {}, "team_stats": {}, "lineup_extras": {}, "meta": {},
    }
