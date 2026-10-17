"""
Tournament state for the WC 2026 simulation.

Wraps live standings/results so the Monte Carlo simulator can:
  - Use *known* group outcomes (all 3 games played) directly.
  - Start from *current standings* when a group is partially played.
  - Propagate *known knockout results* without re-simulating them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oddsmarkets.sports.world_cup.data.live_data import GroupStanding, MatchResult
    from oddsmarkets.sports.world_cup.models.ensemble import EnsembleModel

logger = logging.getLogger(__name__)

# Each group plays 3 rounds (6 matches total for 4 teams)
GAMES_PER_GROUP = 6

# Positions confirmed by live results as of MD2 (locked regardless of remaining matches).
# A team is only confirmed at a position if H2H + points guarantee it even in worst-case MD3.
# Format: group → {1-indexed position → team name}
CONFIRMED_POSITIONS: dict[str, dict[int, str]] = {
    # Mexico 6pts, won H2H vs South Korea 1-0 → confirmed 1st even if SK also reaches 6pts
    "A": {1: "Mexico"},
    # Group B complete (all 6 played): Switzerland 7pts clear; Canada 2nd via overall GD (+5 vs -1) over Bosnia after H2H draw 1-1
    "B": {1: "Switzerland", 2: "Canada", 3: "Bosnia-Herzegovina", 4: "Qatar"},
    # USA 6pts, won H2H vs both Australia (2-0) and Paraguay (4-1) → confirmed 1st
    "D": {1: "USA"},
    # Germany 6pts, won H2H vs Ivory Coast (2-1) → confirmed 1st; no other team can reach 6pts
    "E": {1: "Germany"},
    # Argentina 6pts, won H2H vs both Algeria (3-0) and Austria (2-0) → confirmed 1st
    "J": {1: "Argentina"},
    # NOT Group I: France and Norway both 6pts but play each other in MD3 — order unconfirmed
    # NOT Group K: Colombia 6pts but plays Portugal (4pts) in MD3 — Portugal can win and take 1st
}


@dataclass
class GroupState:
    group: str
    standings: list["GroupStanding"]    # sorted by current position
    games_played: int                   # 0–6
    is_complete: bool                   # all 6 games done
    # Which group-stage matches have already been played
    # List of (home_team, away_team, home_goals, away_goals)
    played_fixtures: list[tuple[str, str, int, int]] = field(default_factory=list)


@dataclass
class TournamentState:
    """
    Snapshot of the live tournament.
    Passed to TournamentSimulator.run() to constrain the simulation
    to what's already known.
    """
    group_states: dict[str, GroupState]         # group letter → GroupState
    # Knockout bracket: live match_id → winning team name, or None if undecided
    knockout_results: dict[str, str | None] = field(default_factory=dict)
    # Knockout winners keyed by the (unordered) pair of teams that met. Lets the
    # simulator force the actual winner whenever those two teams meet in any sim,
    # so reach-round probabilities become conditional on real results.
    knockout_winners_by_teams: dict[frozenset, str] = field(default_factory=dict)

    @classmethod
    def from_live_data(
        cls,
        standings: dict[str, list["GroupStanding"]],
        matches: list["MatchResult"],
    ) -> "TournamentState":
        """
        Build TournamentState from live standings + match results.
        """
        group_states: dict[str, GroupState] = {}

        for grp, rows in standings.items():
            # Collect finished fixtures for this group
            played: list[tuple[str, str, int, int]] = []
            for m in matches:
                if (
                    m.stage == "group"
                    and m.group == grp
                    and m.is_finished()
                    and m.home_goals is not None
                    and m.away_goals is not None
                ):
                    played.append((
                        m.home_team, m.away_team,
                        int(m.home_goals), int(m.away_goals),
                    ))

            games_played = len(played)
            is_complete = games_played >= GAMES_PER_GROUP

            group_states[grp] = GroupState(
                group=grp,
                standings=rows,
                games_played=games_played,
                is_complete=is_complete,
                played_fixtures=played,
            )

        # Extract knockout results from matches
        knockout_results: dict[str, str | None] = {}
        knockout_winners_by_teams: dict[frozenset, str] = {}
        for m in matches:
            if m.stage in ("r32", "r16", "qf", "sf", "final") and m.is_finished():
                if m.home_goals is not None and m.away_goals is not None:
                    if m.home_goals > m.away_goals:
                        winner = m.home_team
                    elif m.away_goals > m.home_goals:
                        winner = m.away_team
                    else:
                        # Level on goals → decided on penalties, which we can't
                        # read from the score. Leave undecided (re-simulated).
                        winner = None
                    knockout_results[m.match_id] = winner
                    if winner is not None:
                        knockout_winners_by_teams[frozenset((m.home_team, m.away_team))] = winner

        return cls(
            group_states=group_states,
            knockout_results=knockout_results,
            knockout_winners_by_teams=knockout_winners_by_teams,
        )

    @classmethod
    def empty(cls) -> "TournamentState":
        return cls(group_states={}, knockout_results={})

    def is_empty(self) -> bool:
        return not self.group_states

    def group_is_complete(self, group: str) -> bool:
        gs = self.group_states.get(group)
        return gs.is_complete if gs else False

    def known_qualifier_order(self, group: str) -> list[str] | None:
        """
        If the group is complete, return [1st, 2nd, 3rd, 4th] team names.
        Returns None if the group is not yet complete.
        """
        gs = self.group_states.get(group)
        if gs is None or not gs.is_complete:
            return None
        return [s.team for s in gs.standings]

    def partial_standings(self, group: str) -> list["GroupStanding"] | None:
        """
        Return current standings for a partially-played group.
        Returns None if the group is not in the state (no data yet).
        """
        gs = self.group_states.get(group)
        if gs is None:
            return None
        return gs.standings

    def already_played_fixtures(self, group: str) -> set[tuple[str, str]]:
        """
        Return set of (home, away) pairs already played in the group.
        Used to skip re-simulating those fixtures.
        """
        gs = self.group_states.get(group)
        if gs is None:
            return set()
        return {(fix[0], fix[1]) for fix in gs.played_fixtures}

    def seed_points_gd_gf(
        self, group: str
    ) -> dict[str, tuple[int, int, int]]:
        """
        Return {team: (points, gd, gf)} from actual standings.
        Used to initialize partial group simulations.
        """
        gs = self.group_states.get(group)
        if gs is None:
            return {}
        return {
            s.team: (s.points, s.gd, s.gf)
            for s in gs.standings
        }

    def summary(self) -> str:
        lines = []
        for grp in sorted(self.group_states.keys()):
            gs = self.group_states[grp]
            status = "complete" if gs.is_complete else f"{gs.games_played}/6 played"
            lines.append(f"  Group {grp}: {status}")
        ko_known = sum(1 for v in self.knockout_results.values() if v)
        if ko_known:
            lines.append(f"  Knockout results known: {ko_known}")
        return "\n".join(lines) if lines else "  (no data)"
