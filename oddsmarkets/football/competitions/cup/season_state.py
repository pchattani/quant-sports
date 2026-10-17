"""
State of a cup season: the league or group phase, and what the bracket already knows.

Duck-compatible with `LeagueState` for the shared strength, players and build
code: `teams`, `finished`, `remaining`, `records()`, `zones` (the groups, or one
table), `standings(zone)`, `zone_of()`, `live_torneo()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from oddsmarkets.football.competitions.cup.config import CupConfig
from oddsmarkets.football.competitions.league.season_state import LeagueMatch, TABLE
from oddsmarkets.football.competitions.liga.season_state import TeamRecord


@dataclass
class CupState:
    cfg: CupConfig
    teams: list[str]
    finished: list[LeagueMatch] = field(default_factory=list)      # league/group phase
    remaining: list[LeagueMatch] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)      # group letter -> clubs
    # Knockout ties already decided: frozenset(pair) -> winner.
    playoff_results: dict[frozenset, str] = field(default_factory=dict)
    # Knockout ties known from the store, per round in kickoff order, as
    # (team hosting leg one, team hosting leg two). For a single-leg tie the
    # second is the away side.
    known_pairs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # Everything a knockout match tells us about who is still in the bracket.
    playoff_matches: list[LeagueMatch] = field(default_factory=list)
    team_ids: dict[str, int] = field(default_factory=dict)
    # Club -> league slug it plays in (for the pooled model), where known.
    team_league: dict[str, str] = field(default_factory=dict)
    previous_rank: dict[str, int] = field(default_factory=dict)
    season_name: str | None = None
    key: str = "cup"

    def __post_init__(self) -> None:
        self.teams = sorted(dict.fromkeys(self.teams))

    # ── duck-typing ──────────────────────────────────────────────────────────

    def live_torneo(self) -> "CupState":
        return self

    @property
    def conferences(self) -> dict[str, list[str]]:
        return self.groups

    @property
    def zones(self) -> dict[str, list[str]]:
        return self.groups if self.groups else {TABLE: list(self.teams)}

    def zone_of(self, team: str) -> str | None:
        for g, members in self.groups.items():
            if team in members:
                return g
        return None

    conference_of = zone_of

    # ── the table(s) ─────────────────────────────────────────────────────────

    def records(self) -> dict[str, TeamRecord]:
        table = {team: TeamRecord() for team in self.teams}
        for m in self.finished:
            if m.is_playoff or not m.is_finished:
                continue
            if m.home_team in table:
                table[m.home_team].add_result(m.home_goals, m.away_goals, self.cfg)
            if m.away_team in table:
                table[m.away_team].add_result(m.away_goals, m.home_goals, self.cfg)
        return table

    def standings(self, zone: str | None = None) -> list[tuple[str, TeamRecord]]:
        table = self.records()
        members = self.teams if zone in (None, TABLE) else self.groups.get(zone, [])
        return sorted(
            ((t, table[t]) for t in members if t in table),
            key=lambda kv: (-kv[1].points, -kv[1].gd, -kv[1].gf, kv[0]),
        )

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
        n = len(self.teams)
        return (2 * self.total_league_games // n) if n else 0

    def summary(self) -> str:
        return (
            f"{self.cfg.name} {self.season_name or ''}: phase {self.games_played}/"
            f"{self.total_league_games}, {len(self.playoff_results)} ties decided"
        )
