"""
Matchup probability analyzer for WC 2026.

Given SimulationResults, computes per-team opponent distributions at each
knockout stage and surfaces the top-N most likely opponents.
"""
from __future__ import annotations

from dataclasses import dataclass

from oddsmarkets.sports.world_cup.trading.simulator import SimulationResults

# Stage keys used in SimulationResults.matchup_probs and p_reach_* fields.
STAGE_REACH_KEY: dict[str, str] = {
    "r32":   "p_reach_r32",
    "r16":   "p_reach_r16",
    "qf":    "p_reach_qf",
    "sf":    "p_reach_sf",
    "final": "p_reach_final",
}

STAGE_LABELS: dict[str, str] = {
    "r32":   "R32",
    "r16":   "R16",
    "qf":    "QF",
    "sf":    "SF",
    "final": "Final",
}


@dataclass
class OpponentEntry:
    opponent: str
    prob_unconditional: float   # P(team faces opp at stage)
    prob_conditional: float     # P(team faces opp at stage | team reaches stage)


@dataclass
class TeamMatchupRow:
    team: str
    group: str
    # Keyed by stage ("r32", "r16", "qf", "sf", "final")
    top_opponents: dict[str, list[OpponentEntry]]
    reach_probs: dict[str, float]   # p_reach_* for all stages
    win_tournament: float


class MatchupAnalyzer:
    """
    Processes SimulationResults into per-team matchup tables.
    """

    def __init__(self, results: SimulationResults) -> None:
        self.results = results
        self._team_group: dict[str, str] = {
            team: grp
            for grp, teams in results.groups.items()
            for team in teams
        }

    def top_opponents(
        self,
        team: str,
        stage: str,
        n: int = 4,
    ) -> list[OpponentEntry]:
        """
        Return the top-n most likely opponents for *team* at *stage*.
        Probabilities are conditional on the team reaching that stage.
        """
        stage_probs = self.results.matchup_probs.get(stage, {})
        opp_probs = stage_probs.get(team, {})

        reach_key = STAGE_REACH_KEY.get(stage)
        p_reach = getattr(self.results, reach_key, {}).get(team, 0.0) if reach_key else 0.0

        entries: list[OpponentEntry] = []
        for opp, p_unconditional in sorted(opp_probs.items(), key=lambda x: -x[1]):
            p_cond = (p_unconditional / p_reach) if p_reach > 1e-9 else 0.0
            entries.append(OpponentEntry(
                opponent=opp,
                prob_unconditional=p_unconditional,
                prob_conditional=min(p_cond, 1.0),
            ))

        return entries[:n]

    def team_row(self, team: str, stages: list[str] | None = None) -> TeamMatchupRow:
        stages = stages or ["r32", "r16", "qf"]
        top_opps = {s: self.top_opponents(team, s) for s in stages}
        reach_probs = {
            s: getattr(self.results, STAGE_REACH_KEY[s], {}).get(team, 0.0)
            for s in STAGE_REACH_KEY
        }
        return TeamMatchupRow(
            team=team,
            group=self._team_group.get(team, "?"),
            top_opponents=top_opps,
            reach_probs=reach_probs,
            win_tournament=self.results.p_win_tournament.get(team, 0.0),
        )

    def all_teams_table(
        self,
        stages: list[str] | None = None,
        sort_by: str = "p_reach_qf",
    ) -> list[TeamMatchupRow]:
        """
        Build a matchup row for every team, sorted by the given probability key.
        """
        teams = list(self.results.p_win_tournament.keys())
        rows = [self.team_row(t, stages) for t in teams]
        rows.sort(
            key=lambda r: getattr(self.results, sort_by, {}).get(r.team, 0.0),
            reverse=True,
        )
        return rows
