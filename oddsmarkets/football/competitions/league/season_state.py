"""
Season state for a plain league: observed results, remaining fixtures, the table.

Deliberately duck-compatible with the Argentine `TorneoState` for the handful of
attributes the shared strength module reads — `finished`, `remaining`, `records()`,
`zones`, `standings(zone)`, `live_torneo()` — so power rankings, form, schedule
strength, luck and Elo trajectories are computed by the same code for every
competition. Conferences play the role of zones; a plain league has one zone
holding everyone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from oddsmarkets.football.competitions.league.config import LeagueConfig
from oddsmarkets.football.competitions.liga.season_state import TeamRecord

# The single "zone" of a league without conferences.
TABLE = "table"


@dataclass(frozen=True)
class LeagueMatch:
    """A league or playoff match, finished or scheduled."""

    game_id: str
    home_team: str
    away_team: str
    home_goals: int | None = None
    away_goals: int | None = None
    date: datetime | None = None
    round_name: str | None = None
    stage: str = "league"              # league | playoff
    status: str = "scheduled"          # scheduled | live | finished
    winner: str | None = None          # a drawn playoff tie settled on penalties
    # Sofascore keeps a postponed fixture's original event alongside the one it
    # is rescheduled as, so a pair can appear twice. The reader drops the
    # postponed copy when another entry for the same pair exists.
    postponed: bool = False

    @property
    def is_finished(self) -> bool:
        return (
            self.status == "finished"
            and self.home_goals is not None
            and self.away_goals is not None
            and self.home_goals >= 0
            and self.away_goals >= 0
        )

    @property
    def is_playoff(self) -> bool:
        return self.stage == "playoff"


@dataclass
class LeagueState:
    """One league season: results so far, fixtures to come, and who plays in it."""

    cfg: LeagueConfig
    teams: list[str]
    finished: list[LeagueMatch] = field(default_factory=list)
    remaining: list[LeagueMatch] = field(default_factory=list)
    conferences: dict[str, list[str]] = field(default_factory=dict)
    previous_rank: dict[str, int] = field(default_factory=dict)
    season_name: str | None = None
    key: str = "league"
    # Sofascore team ids, for crests.
    team_ids: dict[str, int] = field(default_factory=dict)
    # Decided playoff ties this season: frozenset({a, b}) -> winner. Keyed by the
    # pair because in a playoff two clubs meet in at most one round (a best-of-
    # three is one tie), and the simulator only consults this inside the playoff
    # phase — so the league-phase collision the Argentine code guards against by
    # keying on (round, slot) cannot happen here.
    playoff_results: dict[frozenset, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.teams = sorted(dict.fromkeys(self.teams))

    # ── duck-typing for the shared strength module ───────────────────────────

    def live_torneo(self) -> "LeagueState":
        return self

    @property
    def zones(self) -> dict[str, list[str]]:
        if self.conferences:
            return self.conferences
        return {TABLE: list(self.teams)}

    def zone_of(self, team: str) -> str | None:
        for conf, members in self.conferences.items():
            if team in members:
                return conf
        return None

    conference_of = zone_of

    # ── the table ────────────────────────────────────────────────────────────

    def records(self) -> dict[str, TeamRecord]:
        """Current league-stage table from finished matches."""
        table = {team: TeamRecord() for team in self.teams}
        for m in self.finished:
            if m.is_playoff or not m.is_finished:
                continue
            if m.home_team in table:
                table[m.home_team].add_result(m.home_goals, m.away_goals, self.cfg)
            if m.away_team in table:
                table[m.away_team].add_result(m.away_goals, m.home_goals, self.cfg)
        return table

    def _sort_key(self, team: str, rec: TeamRecord):
        parts = []
        for key in self.cfg.tiebreak:
            if key == "pts":
                parts.append(-rec.points)
            elif key == "gd":
                parts.append(-rec.gd)
            elif key == "gf":
                parts.append(-rec.gf)
            elif key == "w":
                parts.append(-rec.won)
        parts.append(team)
        return tuple(parts)

    def standings(self, zone: str | None = None) -> list[tuple[str, TeamRecord]]:
        """
        The table, or one conference's, ordered by the league's tiebreak keys with
        alphabetical order as the stable display fallback.
        """
        table = self.records()
        if zone is None or zone == TABLE:
            members = self.teams
        else:
            members = self.conferences.get(zone, [])
        return sorted(
            ((t, table[t]) for t in members if t in table),
            key=lambda kv: self._sort_key(kv[0], kv[1]),
        )

    # ── progress ─────────────────────────────────────────────────────────────

    @property
    def league_complete(self) -> bool:
        return not any(not m.is_playoff for m in self.remaining)

    @property
    def games_played(self) -> int:
        return sum(1 for m in self.finished if m.is_finished and not m.is_playoff)

    @property
    def total_league_games(self) -> int:
        return self.games_played + sum(1 for m in self.remaining if not m.is_playoff)

    @property
    def matches_per_team(self) -> int:
        """Season length, from the fixture list rather than assumed from the format."""
        n = len(self.teams)
        return (2 * self.total_league_games // n) if n else 0

    def summary(self) -> str:
        return (
            f"{self.cfg.name} {self.season_name or ''}: league {self.games_played}/"
            f"{self.total_league_games} teams={len(self.teams)}"
        )
