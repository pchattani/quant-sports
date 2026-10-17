"""
Competition format for the Argentine Liga Profesional de Fútbol.

The format is expressed as data rather than scattered constants, because it changes
often — the AFA has restructured the top flight repeatedly, and the number of teams,
zones, playoff berths and relegation places have all moved within the last few seasons.
Anything a future season could change should live here.

2026 format (verified against reporting on the AFA reglamento, Aug 2026):
  - 30 teams, split into Zona A and Zona B of 15.
  - Two tournaments a year, each crowning a champion: Apertura (Jan-May) and
    Clausura (Jul-Dec).
  - 16 matches per team per tournament: a single round-robin inside your zone (14)
    plus 2 interzone matches — the designated classic rival, and one drawn by lot.
  - Top 8 of each zone reach a single-leg Round of 16 -> QF -> SF -> Final.
    Cross-zone: 1st of one zone meets 8th of the other, 2nd meets 7th, and so on.
    The bracket is a FIXED tree — teams are not re-seeded between rounds. The
    better-placed side hosts through the semi-finals; the final is at a neutral venue.
  - Tabla Anual combines both tournaments' points; its leader is Campeon de Liga.
    Only Primera Fase de Zonas points count — playoff results do not enter it.
  - Six Libertadores berths: Apertura champion, Clausura champion, Copa Argentina
    winner, then the best three of the Tabla Anual excluding those. Six Sudamericana
    berths follow, again excluding clubs already qualified.
  - Two relegations: worst three-season promedio (2024+2025+2026), and last in the
    Tabla Anual.

Every constant below was checked rather than inferred; the ones that most affect
output — the cross-zone pairing, the fixed bracket, the neutral-venue final, the
berth counts, and the fact that promedios and the Tabla Anual exclude playoff
points — are all confirmed. Re-verify at each season rollover: the AFA has
restructured the top flight repeatedly in recent years.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Sofascore unique-tournament id for Liga Profesional de Futbol.
SOFASCORE_TOURNAMENT_ID = 155
# Copa de la Liga Profesional, a separate competition, kept here so it is not
# confused with the league itself.
SOFASCORE_COPA_LIGA_TOURNAMENT_ID = 13475

# The Odds API sport key.
ODDS_API_SPORT = "soccer_argentina_primera_division"

ZONE_A = "A"
ZONE_B = "B"
ZONES = (ZONE_A, ZONE_B)

APERTURA = "apertura"
CLAUSURA = "clausura"
TORNEOS = (APERTURA, CLAUSURA)

# Playoff rounds, outermost first. All single-leg.
PLAYOFF_ROUNDS = ("r16", "qf", "sf", "final")
ROUND_LABELS = {
    "r16": "Octavos",
    "qf": "Cuartos",
    "sf": "Semifinal",
    "final": "Final",
}

# Round of 16 pairings by zone seed. Ordered so that adjacent pairs feed one
# quarter-final, which lets the simulator resolve the bracket by repeatedly
# folding the slot array in half.
#
# VERIFIED: the cross-zone pattern (1st of a zone vs 8th of the other, 2nd vs 7th,
# and so on) and the fixed-tree structure are both confirmed — there is no
# re-seeding between rounds, so a bracket rather than a re-draw is correct.
#
# Still isolated here as a single editable constant because the AFA has changed the
# format repeatedly; a future restructure should be a config edit, not a code change.
PLAYOFF_PAIRINGS: tuple[tuple[str, str], ...] = (
    ("A1", "B8"), ("A4", "B5"),
    ("A2", "B7"), ("A3", "B6"),
    ("B1", "A8"), ("B4", "A5"),
    ("B2", "A7"), ("B3", "A6"),
)


@dataclass(frozen=True)
class LigaConfig:
    """
    Everything about the competition that a future season might change.

    Defaults describe the 2026 season.
    """

    season_year: int = 2026

    n_teams: int = 30
    teams_per_zone: int = 15
    qualifiers_per_zone: int = 8

    # Matches per team per tournament: 14 intra-zone + 2 interzone.
    intra_zone_matches: int = 14
    interzone_matches: int = 2

    # ── Continental qualification (verified) ─────────────────────────────────
    # Six Libertadores berths: Apertura champion (ARG 1), Clausura champion (ARG 2),
    # Copa Argentina winner (ARG 3), then the best three of the Tabla Anual excluding
    # those (ARG 4-6). Six Sudamericana berths follow off the same table, again
    # excluding clubs already qualified. The simulator fills them in exactly that
    # order, which is why berths must be resolved inside the simulation: they depend
    # on who wins the tournament and cannot be recovered from marginals afterwards.
    libertadores_berths: int = 6
    sudamericana_berths: int = 6

    # The Copa Argentina is outside this model. Its winner takes a Libertadores
    # berth, and if they already qualified through the league a Tabla Anual place
    # cascades down — so berth probabilities are biased high for everyone unless
    # this is supplied once known. None means "not yet decided".
    copa_argentina_winner: str | None = None

    # ── Relegation ───────────────────────────────────────────────────────────
    # Two clubs go down: the worst three-season promedio (points per match across
    # the current and two preceding seasons) and whoever finishes last in the
    # Tabla Anual.
    relegation_places: int = 2
    promedio_seasons: int = 3
    # VERIFIED: the Tabla Anual is built from Primera Fase de Zonas points only, so
    # playoff results enter neither it nor the promedios derived alongside it.
    promedio_includes_playoffs: bool = False
    # When the worst promedio and the Tabla Anual's last place are the same club,
    # the second descent passes to the next-worst promedio.
    relegation_collision: str = "next_worst_promedio"

    # ── Match model ──────────────────────────────────────────────────────────
    # Probability the home side advances from a drawn single-leg tie. Extra time
    # favours the stronger side, so this is not a flat coin flip: the drawn mass is
    # split between an extra-time phase weighted by relative strength and a
    # shootout treated as even.
    extra_time_weight: float = 0.5
    # VERIFIED: the better-placed side hosts in octavos, cuartos and semifinales;
    # the final is played at a neutral stadium.
    final_at_neutral_venue: bool = True

    # ── Simulation ───────────────────────────────────────────────────────────
    n_sims: int = 100_000
    sim_chunk: int = 25_000
    random_seed: int = 42
    max_goals: int = 8

    # ── Points ───────────────────────────────────────────────────────────────
    points_win: int = 3
    points_draw: int = 1

    def zone_of_seed(self, seed_label: str) -> str:
        """'A3' -> 'A'."""
        return seed_label[0]

    def rank_of_seed(self, seed_label: str) -> int:
        """'A3' -> 3 (1-indexed)."""
        return int(seed_label[1:])

    @property
    def matches_per_team_per_torneo(self) -> int:
        return self.intra_zone_matches + self.interzone_matches

    @property
    def matches_per_torneo(self) -> int:
        """Total league-phase matches across both zones in one tournament."""
        return self.n_teams * self.matches_per_team_per_torneo // 2

    @property
    def playoff_teams(self) -> int:
        return self.qualifiers_per_zone * len(ZONES)

    def __post_init__(self) -> None:
        if self.n_teams != self.teams_per_zone * len(ZONES):
            raise ValueError(
                f"n_teams ({self.n_teams}) must equal teams_per_zone "
                f"({self.teams_per_zone}) x {len(ZONES)} zones"
            )
        if len(PLAYOFF_PAIRINGS) * 2 != self.playoff_teams:
            raise ValueError(
                f"PLAYOFF_PAIRINGS describes {len(PLAYOFF_PAIRINGS) * 2} teams but "
                f"qualifiers_per_zone implies {self.playoff_teams}"
            )
        if self.qualifiers_per_zone & (self.qualifiers_per_zone - 1):
            raise ValueError(
                "qualifiers_per_zone must be a power of two for a clean single-leg bracket"
            )


DEFAULT_CONFIG = LigaConfig()


# ── Zone membership fallback ─────────────────────────────────────────────────
# Zone membership is read from the Sofascore store at runtime, because it is drawn
# afresh each season. This fallback exists only so the simulator and site can be
# exercised offline, and is deliberately marked as such rather than being treated
# as authoritative.
FALLBACK_ZONES_2026: dict[str, list[str]] = {
    ZONE_A: [
        "Argentinos Juniors", "Atlético Tucumán", "Barracas Central", "Belgrano",
        "Boca Juniors", "Central Córdoba", "Estudiantes", "Independiente Rivadavia",
        "Lanús", "Newell's Old Boys", "Platense", "Rosario Central",
        "San Lorenzo", "Talleres", "Unión",
    ],
    ZONE_B: [
        "Aldosivi", "Banfield", "Defensa y Justicia", "Deportivo Riestra",
        "Gimnasia LP", "Godoy Cruz", "Huracán", "Independiente",
        "Instituto", "Racing Club", "River Plate", "San Martín SJ",
        "Sarmiento", "Tigre", "Vélez Sarsfield",
    ],
}


@dataclass(frozen=True)
class SeasonIds:
    """
    Sofascore season ids for one calendar year.

    These cannot be discovered from CI — Sofascore blocks datacenter IPs — so they
    are committed static configuration, produced by scripts/discover_sofascore_liga.py
    run from a residential connection at each season rollover.
    """

    year: int
    apertura: int | None = None
    clausura: int | None = None

    def for_torneo(self, torneo: str) -> int | None:
        return {APERTURA: self.apertura, CLAUSURA: self.clausura}.get(torneo)


@dataclass
class LigaSeasons:
    """Registry of known Sofascore season ids, loaded from data/seasons.json."""

    tournament_id: int = SOFASCORE_TOURNAMENT_ID
    seasons: dict[int, SeasonIds] = field(default_factory=dict)

    def get(self, year: int) -> SeasonIds | None:
        return self.seasons.get(year)

    def promedio_years(self, cfg: LigaConfig | None = None) -> list[int]:
        """The calendar years contributing to the current promedio window."""
        cfg = cfg or DEFAULT_CONFIG
        return [cfg.season_year - offset for offset in range(cfg.promedio_seasons)][::-1]
