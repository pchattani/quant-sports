"""
Live match data for WC 2026 from football-data.org and API-Football.
Degrades gracefully to empty data when no API keys are configured.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

FD_COMPETITION = "WC"
FD_SEASON = "2026"
AF_LEAGUE = 1
AF_SEASON = 2026

_CACHE_TTL = 270  # seconds (just under the 5-minute dashboard refresh)

# API name → simulator canonical name
_TEAM_ALIASES: dict[str, str] = {
    "United States": "USA",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "IR Iran": "Iran",
    "Korea Republic": "South Korea",
    "Republic of Korea": "South Korea",
    "New-Zealand": "New Zealand",
    "Türkiye": "Turkey",
    "Curaçao": "Curacao",
    "Cabo Verde": "Cape Verde",
    "Cape Verde Islands": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "Czechia": "Czech Republic",
    "Czech Rep.": "Czech Republic",
    "Congo DR": "DR Congo",
    "Democratic Republic of Congo": "DR Congo",
}

_STAGE_MAP_FD: dict[str, str] = {
    "GROUP_STAGE": "group",
    "LAST_32": "r32",
    "LAST_16": "r16",
    "QUARTER_FINALS": "qf",
    "SEMI_FINALS": "sf",
    "FINAL": "final",
}

_STATUS_MAP_FD: dict[str, str] = {
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
    "IN_PLAY": "live",
    "PAUSED": "live",
    "FINISHED": "finished",
}

_STAGE_MAP_AF: dict[str, str] = {
    "Round of 32": "r32",
    "Round of 16": "r16",
    "Quarter-finals": "qf",
    "Semi-finals": "sf",
    "Final": "final",
}

_STATUS_LIVE_AF = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT", "LIVE"}
_STATUS_FINISHED_AF = {"FT", "AET", "PEN"}


@dataclass
class GroupStanding:
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    gf: int
    ga: int
    gd: int
    points: int


@dataclass
class MatchResult:
    match_id: str
    home_team: str
    away_team: str
    home_goals: Optional[int]
    away_goals: Optional[int]
    match_date: Optional[datetime]
    status: str    # "scheduled" | "live" | "finished"
    stage: str     # "group" | "r32" | "r16" | "qf" | "sf" | "final"
    group: Optional[str]  # "A".."L" for group stage

    def is_finished(self) -> bool:
        return self.status == "finished"


@dataclass
class PlayerStats:
    player: str
    team: str
    goals: int
    assists: int
    appearances: int
    penalties: int = 0
    xg: Optional[float] = None


class LiveDataManager:
    def __init__(
        self,
        football_data_key: str = "",
        api_football_key: str = "",
    ) -> None:
        self._fd_key = football_data_key or ""
        self._af_key = api_football_key or ""
        self._matches_cache: list[MatchResult] = []
        self._matches_ts: float = 0.0
        self._standings_cache: dict[str, list[GroupStanding]] = {}
        self._standings_ts: float = 0.0
        self._players_cache: list[PlayerStats] = []
        self._players_ts: float = 0.0
        # Rate-limit state for football-data.org (free tier: 10 req/min)
        self._fd_requests_remaining: int = 10
        self._fd_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_matches(self, force: bool = False) -> list[MatchResult]:
        if not force and time.time() - self._matches_ts < _CACHE_TTL:
            return self._matches_cache
        result = self._fetch_matches()
        if result is not None:
            self._matches_cache = result
            self._matches_ts = time.time()
        return self._matches_cache

    def get_standings(self, force: bool = False) -> dict[str, list[GroupStanding]]:
        if not force and time.time() - self._standings_ts < _CACHE_TTL:
            return self._standings_cache
        # Compute from already-fetched matches first (saves an API request)
        matches = self.get_matches(force=force)
        result = _standings_from_matches(matches) if matches else None
        if not result:
            result = self._fetch_standings()
        if result is not None:
            self._standings_cache = result
            self._standings_ts = time.time()
        return self._standings_cache

    def get_players(self) -> list[PlayerStats]:
        if time.time() - self._players_ts < _CACHE_TTL:
            return self._players_cache
        result = self._fetch_players()
        if result is not None:
            self._players_cache = result
            self._players_ts = time.time()
        return self._players_cache

    # ------------------------------------------------------------------
    # football-data.org
    # ------------------------------------------------------------------

    def _fd_get(self, path: str) -> Optional[dict]:
        if not self._fd_key:
            return None
        with self._fd_lock:
            # Back off if we've burned through the minute's quota
            if self._fd_requests_remaining <= 0:
                logger.warning("football-data.org rate limit reached — skipping request to %s", path)
                return None
        try:
            r = requests.get(
                f"https://api.football-data.org/v4{path}",
                headers={"X-Auth-Token": self._fd_key},
                timeout=10,
            )
            # Inspect rate-limit headers on every response (as Daniel advised)
            with self._fd_lock:
                available = r.headers.get("X-Requests-Available-Minute")
                reset_secs = r.headers.get("X-RequestCounter-Reset")
                if available is not None:
                    self._fd_requests_remaining = int(available)
                if self._fd_requests_remaining <= 2:
                    logger.warning(
                        "football-data.org: only %s requests left this minute (resets in %ss)",
                        available, reset_secs,
                    )

            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After", "60")
                logger.warning("football-data.org rate-limited. Retry-After: %ss", retry_after)
                with self._fd_lock:
                    self._fd_requests_remaining = 0
                return None
            logger.warning("football-data.org %s → HTTP %d: %s", path, r.status_code, r.text[:200])
        except Exception as exc:
            logger.warning("football-data.org request failed: %s", exc)
        return None

    def _fetch_matches_fd(self) -> Optional[list[MatchResult]]:
        data = self._fd_get(f"/competitions/{FD_COMPETITION}/matches?season={FD_SEASON}")
        if not data:
            return None
        results: list[MatchResult] = []
        for m in data.get("matches", []):
            home = _normalize(m["homeTeam"]["name"])
            away = _normalize(m["awayTeam"]["name"])
            ft = m.get("score", {}).get("fullTime", {})
            stage = _STAGE_MAP_FD.get(m.get("stage", "GROUP_STAGE"), "group")
            grp_raw = m.get("group")
            grp = grp_raw.replace("GROUP_", "") if grp_raw else None
            status = _STATUS_MAP_FD.get(m.get("status", "SCHEDULED"), "scheduled")
            match_date = _parse_iso(m.get("utcDate"))
            results.append(MatchResult(
                match_id=str(m["id"]),
                home_team=home,
                away_team=away,
                home_goals=ft.get("home"),
                away_goals=ft.get("away"),
                match_date=match_date,
                status=status,
                stage=stage,
                group=grp,
            ))
        logger.info("football-data.org: %d matches fetched", len(results))
        return results or None

    def _fetch_standings_fd(self) -> Optional[dict[str, list[GroupStanding]]]:
        data = self._fd_get(f"/competitions/{FD_COMPETITION}/standings?season={FD_SEASON}")
        if not data:
            return None
        result: dict[str, list[GroupStanding]] = {}
        for block in data.get("standings", []):
            if block.get("stage") != "GROUP_STAGE":
                continue
            grp = (block.get("group") or "").replace("GROUP_", "")
            if not grp:
                continue
            rows = [
                GroupStanding(
                    team=_normalize(e["team"]["name"]),
                    played=e.get("playedGames", 0),
                    won=e.get("won", 0),
                    drawn=e.get("draw", 0),
                    lost=e.get("lost", 0),
                    gf=e.get("goalsFor", 0),
                    ga=e.get("goalsAgainst", 0),
                    gd=e.get("goalDifference", 0),
                    points=e.get("points", 0),
                )
                for e in block.get("table", [])
            ]
            if rows:
                result[grp] = rows
        logger.info("football-data.org: standings for %d groups", len(result))
        return result or None

    def _fetch_players_fd(self) -> Optional[list[PlayerStats]]:
        data = self._fd_get(
            f"/competitions/{FD_COMPETITION}/scorers?season={FD_SEASON}&limit=25"
        )
        if not data:
            return None
        results = [
            PlayerStats(
                player=s["player"]["name"],
                team=_normalize(s["team"]["name"]),
                goals=s.get("goals") or 0,
                assists=s.get("assists") or 0,
                appearances=s.get("playedMatches") or 0,
                penalties=s.get("penalties") or 0,
            )
            for s in data.get("scorers", [])
        ]
        return results or None

    # ------------------------------------------------------------------
    # API-Football via RapidAPI
    # ------------------------------------------------------------------

    def _af_get(self, path: str, params: dict) -> Optional[dict]:
        if not self._af_key:
            return None
        try:
            r = requests.get(
                f"https://v3.football.api-sports.io{path}",
                headers={
                    "x-rapidapi-key": self._af_key,
                    "x-rapidapi-host": "v3.football.api-sports.io",
                },
                params=params,
                timeout=10,
            )
            if r.status_code == 200:
                return r.json()
            logger.warning("API-Football %s → HTTP %d", path, r.status_code)
        except Exception as exc:
            logger.warning("API-Football request failed: %s", exc)
        return None

    def _fetch_matches_af(self) -> Optional[list[MatchResult]]:
        data = self._af_get("/fixtures", {"league": AF_LEAGUE, "season": AF_SEASON})
        if not data:
            return None
        results: list[MatchResult] = []
        for fix in data.get("response", []):
            fixture = fix.get("fixture", {})
            teams = fix.get("teams", {})
            goals = fix.get("goals", {})
            league_info = fix.get("league", {})
            home = _normalize(teams.get("home", {}).get("name", ""))
            away = _normalize(teams.get("away", {}).get("name", ""))
            if not home or not away:
                continue
            short = fixture.get("status", {}).get("short", "NS")
            if short in _STATUS_LIVE_AF:
                status = "live"
            elif short in _STATUS_FINISHED_AF:
                status = "finished"
            else:
                status = "scheduled"
            round_str = league_info.get("round", "")
            stage = "group" if "Group Stage" in round_str else _STAGE_MAP_AF.get(round_str, "group")
            results.append(MatchResult(
                match_id=str(fixture.get("id", f"{home}-{away}")),
                home_team=home,
                away_team=away,
                home_goals=goals.get("home") if status != "scheduled" else None,
                away_goals=goals.get("away") if status != "scheduled" else None,
                match_date=_parse_iso(fixture.get("date")),
                status=status,
                stage=stage,
                group=None,
            ))
        logger.info("API-Football: %d fixtures fetched", len(results))
        return results or None

    def _fetch_standings_af(self) -> Optional[dict[str, list[GroupStanding]]]:
        data = self._af_get("/standings", {"league": AF_LEAGUE, "season": AF_SEASON})
        if not data:
            return None
        result: dict[str, list[GroupStanding]] = {}
        response = data.get("response", [])
        if not response:
            return None
        for group_list in response[0].get("league", {}).get("standings", []):
            if not group_list:
                continue
            grp_name = group_list[0].get("group", "")
            grp = grp_name.replace("Group ", "").strip()[:1].upper()
            if not grp.isalpha():
                continue
            rows = []
            for e in group_list:
                all_s = e.get("all", {})
                g = all_s.get("goals", {})
                rows.append(GroupStanding(
                    team=_normalize(e.get("team", {}).get("name", "")),
                    played=all_s.get("played") or 0,
                    won=all_s.get("win") or 0,
                    drawn=all_s.get("draw") or 0,
                    lost=all_s.get("lose") or 0,
                    gf=g.get("for") or 0,
                    ga=g.get("against") or 0,
                    gd=e.get("goalsDiff") or 0,
                    points=e.get("points") or 0,
                ))
            if rows:
                result[grp] = rows
        logger.info("API-Football: standings for %d groups", len(result))
        return result or None

    def _fetch_players_af(self) -> Optional[list[PlayerStats]]:
        data = self._af_get(
            "/players/topscorers", {"league": AF_LEAGUE, "season": AF_SEASON}
        )
        if not data:
            return None
        results = []
        for entry in data.get("response", []):
            p = entry.get("player", {})
            stats = (entry.get("statistics") or [{}])[0]
            team = _normalize(stats.get("team", {}).get("name", ""))
            g_info = stats.get("goals", {})
            games = stats.get("games", {})
            results.append(PlayerStats(
                player=p.get("name", ""),
                team=team,
                goals=g_info.get("total") or 0,
                assists=g_info.get("assists") or 0,
                appearances=games.get("appearences") or 0,  # API typo: appearences
            ))
        return results or None

    # ------------------------------------------------------------------
    # Dispatch: football-data.org first, fall back to API-Football
    # ------------------------------------------------------------------

    def _fetch_matches(self) -> Optional[list[MatchResult]]:
        return self._fetch_matches_fd() or self._fetch_matches_af()

    def _fetch_standings(self) -> Optional[dict[str, list[GroupStanding]]]:
        return self._fetch_standings_fd() or self._fetch_standings_af()

    def _fetch_players(self) -> Optional[list[PlayerStats]]:
        return self._fetch_players_fd() or self._fetch_players_af()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalize(name: str) -> str:
    return _TEAM_ALIASES.get(name, name)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _standings_from_matches(matches: list[MatchResult]) -> dict[str, list[GroupStanding]]:
    """
    Derive per-group standings by replaying finished group-stage matches.
    Avoids a separate standings API call (and its rate-limit cost).
    """
    from collections import defaultdict

    # {group: {team: {played, won, drawn, lost, gf, ga, points}}}
    records: dict[str, dict[str, dict]] = defaultdict(dict)

    for m in matches:
        if m.stage != "group" or not m.group:
            continue
        grp = m.group
        for team in (m.home_team, m.away_team):
            if team not in records[grp]:
                records[grp][team] = {"played": 0, "won": 0, "drawn": 0, "lost": 0,
                                      "gf": 0, "ga": 0, "points": 0}

        if not m.is_finished() or m.home_goals is None or m.away_goals is None:
            continue

        hg, ag = int(m.home_goals), int(m.away_goals)
        ht, at = m.home_team, m.away_team
        records[grp][ht]["played"] += 1
        records[grp][at]["played"] += 1
        records[grp][ht]["gf"] += hg
        records[grp][ht]["ga"] += ag
        records[grp][at]["gf"] += ag
        records[grp][at]["ga"] += hg

        if hg > ag:
            records[grp][ht]["won"] += 1;   records[grp][ht]["points"] += 3
            records[grp][at]["lost"] += 1
        elif hg == ag:
            records[grp][ht]["drawn"] += 1; records[grp][ht]["points"] += 1
            records[grp][at]["drawn"] += 1; records[grp][at]["points"] += 1
        else:
            records[grp][at]["won"] += 1;   records[grp][at]["points"] += 3
            records[grp][ht]["lost"] += 1

    result: dict[str, list[GroupStanding]] = {}
    for grp, teams in records.items():
        rows = [
            GroupStanding(
                team=team,
                played=s["played"],
                won=s["won"],
                drawn=s["drawn"],
                lost=s["lost"],
                gf=s["gf"],
                ga=s["ga"],
                gd=s["gf"] - s["ga"],
                points=s["points"],
            )
            for team, s in teams.items()
        ]
        rows.sort(key=lambda x: (x.points, x.gd, x.gf), reverse=True)
        result[grp] = rows

    return result
