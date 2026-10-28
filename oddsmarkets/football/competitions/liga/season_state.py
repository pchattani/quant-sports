"""
Season state: the bridge between observed results and the simulator.

Three things differ fundamentally from the World Cup's TournamentState:

1. Remaining fixtures are *read*, not enumerated. With a single round-robin plus two
   interzone matches you cannot reconstruct the schedule from combinations(teams, 2),
   and home/away matters now that the model has a home-advantage term.
2. Partial seasons are the normal case rather than an edge case. A league dashboard
   spends its whole life mid-season.
3. Completed tournaments are constants. The Apertura is finished, so it contributes
   fixed points to the Tabla Anual rather than simulated variance — both more correct
   and much cheaper.

Known playoff results are keyed by (round, slot), never by team pair. The World Cup
code keyed them by frozenset({home, away}), which force-returns a known winner whenever
those two clubs meet in any round — harmless in a tournament where teams meet once,
wrong in a league where they meet in the league phase and again in the playoffs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from oddsmarkets.football.competitions.liga.config import (
    APERTURA,
    CLAUSURA,
    DEFAULT_CONFIG,
    LigaConfig,
    PLAYOFF_ROUNDS,
    ZONES,
)


@dataclass(frozen=True)
class LigaMatch:
    """A league-phase or playoff match, finished or scheduled."""

    game_id: str
    home_team: str
    away_team: str
    home_goals: int | None = None
    away_goals: int | None = None
    date: datetime | None = None
    round_name: str | None = None      # "12" for league rounds, "r16"/"qf"/... for playoffs
    torneo: str | None = None
    zone: str | None = None            # None for interzone fixtures
    status: str = "scheduled"          # scheduled | live | finished

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
        return self.round_name in PLAYOFF_ROUNDS


@dataclass
class TeamRecord:
    """A club's running league-phase record within one tournament."""

    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0
    points: int = 0

    @property
    def gd(self) -> int:
        return self.gf - self.ga

    def add_result(self, scored: int, conceded: int, cfg: LigaConfig) -> None:
        self.played += 1
        self.gf += scored
        self.ga += conceded
        if scored > conceded:
            self.won += 1
            self.points += cfg.points_win
        elif scored == conceded:
            self.drawn += 1
            self.points += cfg.points_draw
        else:
            self.lost += 1


@dataclass
class TorneoState:
    """State of a single tournament (Apertura or Clausura)."""

    key: str
    zones: dict[str, list[str]]
    finished: list[LigaMatch] = field(default_factory=list)
    remaining: list[LigaMatch] = field(default_factory=list)
    playoff_results: dict[str, str] = field(default_factory=dict)   # "r16:3" -> winner
    champion: str | None = None
    cfg: LigaConfig = field(default=DEFAULT_CONFIG)

    @property
    def teams(self) -> list[str]:
        return [t for zone in ZONES for t in self.zones.get(zone, [])]

    def zone_of(self, team: str) -> str | None:
        for zone, members in self.zones.items():
            if team in members:
                return zone
        return None

    def records(self) -> dict[str, TeamRecord]:
        """Current league-phase table, derived from finished matches."""
        table = {team: TeamRecord() for team in self.teams}
        for m in self.finished:
            if m.is_playoff or not m.is_finished:
                continue
            if m.home_team in table:
                table[m.home_team].add_result(m.home_goals, m.away_goals, self.cfg)
            if m.away_team in table:
                table[m.away_team].add_result(m.away_goals, m.home_goals, self.cfg)
        return table

    def standings(self, zone: str) -> list[tuple[str, TeamRecord]]:
        """
        Zone table sorted by the Argentine criteria: points, then goal difference,
        then goals for. Remaining ties are drawn by lot, which the simulator models
        with random jitter; here they fall back to alphabetical for a stable display.
        """
        table = self.records()
        members = self.zones.get(zone, [])
        return sorted(
            ((t, table[t]) for t in members if t in table),
            key=lambda kv: (-kv[1].points, -kv[1].gd, -kv[1].gf, kv[0]),
        )

    @property
    def league_complete(self) -> bool:
        return not self.remaining

    @property
    def playoffs_complete(self) -> bool:
        return self.champion is not None

    @property
    def is_complete(self) -> bool:
        return self.league_complete and self.playoffs_complete

    @property
    def games_played(self) -> int:
        return sum(1 for m in self.finished if m.is_finished and not m.is_playoff)

    @property
    def total_league_games(self) -> int:
        return self.games_played + sum(1 for m in self.remaining if not m.is_playoff)


@dataclass
class SeasonState:
    """A full calendar season: two tournaments plus the promedio history behind them."""

    year: int
    apertura: TorneoState
    clausura: TorneoState
    # team -> (points, matches_played) accumulated over the preceding promedio seasons
    promedios_prior: dict[str, tuple[int, int]] = field(default_factory=dict)
    cfg: LigaConfig = field(default=DEFAULT_CONFIG)

    @property
    def teams(self) -> list[str]:
        """Canonical team ordering, used as the model's index order."""
        seen: list[str] = []
        for torneo in (self.clausura, self.apertura):
            for team in torneo.teams:
                if team not in seen:
                    seen.append(team)
        return sorted(seen)

    def torneo(self, key: str) -> TorneoState:
        return {APERTURA: self.apertura, CLAUSURA: self.clausura}[key]

    def anual_base(self) -> dict[str, TeamRecord]:
        """
        Tabla Anual contribution from completed tournaments only.

        The Apertura is finished, so it is a constant. Anything still in progress is
        excluded here and supplied by the simulation instead.
        """
        base = {team: TeamRecord() for team in self.teams}
        for torneo in (self.apertura, self.clausura):
            if not torneo.league_complete:
                continue
            for team, rec in torneo.records().items():
                if team not in base:
                    base[team] = TeamRecord()
                acc = base[team]
                acc.played += rec.played
                acc.won += rec.won
                acc.drawn += rec.drawn
                acc.lost += rec.lost
                acc.gf += rec.gf
                acc.ga += rec.ga
                acc.points += rec.points
        return base

    def anual_now(self) -> dict[str, TeamRecord]:
        """
        The Tabla Anual as it stands: both tournaments' zone-phase results played so far (the finished
        Apertura plus the Clausura to date), as the AFA publishes it. Playoff matches never count.
        `anual_base` is the constant part the simulation starts from; this is what the table shows.
        """
        base = {team: TeamRecord() for team in self.teams}
        for torneo in (self.apertura, self.clausura):
            for team, rec in torneo.records().items():
                acc = base.setdefault(team, TeamRecord())
                acc.played += rec.played
                acc.won += rec.won
                acc.drawn += rec.drawn
                acc.lost += rec.lost
                acc.gf += rec.gf
                acc.ga += rec.ga
                acc.points += rec.points
        return base

    def anual_standings(self) -> list[tuple[str, TeamRecord]]:
        """The current Tabla Anual in order: points, goal difference, goals for (the AFA's order; it matched
        Sofascore's "Anual 2025" table club for club), then name for a stable display."""
        table = self.anual_now()
        return sorted(table.items(), key=lambda kv: (-kv[1].points, -kv[1].gd, -kv[1].gf, kv[0]))

    def live_torneo(self) -> TorneoState | None:
        """The tournament currently being simulated, if any."""
        for torneo in (self.clausura, self.apertura):
            if not torneo.league_complete or not torneo.playoffs_complete:
                return torneo
        return None

    def promedio_now(self) -> dict[str, float]:
        """
        Current promedio per club: total points divided by total matches across the
        promedio window. Clubs promoted this season have no prior history and are
        scored on the current season alone — which is exactly why the metric is
        points per match rather than points per season. The current season counts what has been played so
        far (the Tabla Anual as it stands), as the published promedios do.
        """
        current = self.anual_now()
        out: dict[str, float] = {}
        for team in self.teams:
            prior_pts, prior_mp = self.promedios_prior.get(team, (0, 0))
            rec = current.get(team, TeamRecord())
            pts = prior_pts + rec.points
            mp = prior_mp + rec.played
            out[team] = (pts / mp) if mp else 0.0
        return out

    def summary(self) -> str:
        live = self.live_torneo()
        phase = live.key if live else "complete"
        played = live.games_played if live else 0
        total = live.total_league_games if live else 0
        return (
            f"Liga {self.year}: phase={phase} league {played}/{total} "
            f"teams={len(self.teams)} apertura_champion={self.apertura.champion}"
        )
