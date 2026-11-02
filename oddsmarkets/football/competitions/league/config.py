"""
Competition formats for plain leagues, expressed as data.

Every league here is a round-robin table where what matters — title, continental
qualification, relegation — is a function of finishing position alone. That is what
lets one simulator serve all of them: the position distribution is computed once and
every band probability is a sum over a range of it. The Argentine format is not in
this family (its berths depend on who wins a playoff), which is why it keeps its own
package.

Bands were checked against the rules Sofascore publishes on each league's current
standings (Sept 2026), which is also what the discovery script records. They change
at the margins season to season — Champions League coefficient places, whether a
league's fifth place is UCL or UEL — so re-verify at each rollover rather than
trusting these values across a season boundary.
"""
from __future__ import annotations

from dataclasses import dataclass

# Tiebreak keys the simulator can rank on, in the order they apply. Head-to-head
# clustering (La Liga, Serie A) cannot be vectorised and is approximated by goal
# difference; the effect on season-level probabilities is small and it is noted on
# the methodology tab rather than hidden.
TIEBREAK_GD = ("pts", "gd", "gf")
TIEBREAK_WINS = ("pts", "w", "gd", "gf")     # MLS

# Playoff round keys for MLS, outermost first. "wc" is the single-match wildcard.
MLS_ROUNDS = ("wc", "r1", "csf", "cf", "final")
MLS_ROUND_LABELS = {
    "wc": "Wild Card", "r1": "Round One", "csf": "Conf. Semifinal",
    "cf": "Conf. Final", "final": "MLS Cup",
}
# Liga MX Liguilla rounds, outermost first.
LIGUILLA_ROUNDS = ("play_in", "qf", "sf", "final")
LIGUILLA_ROUND_LABELS = {"play_in": "Play-in", "qf": "Quarter-final", "sf": "Semi-final", "final": "Final"}


@dataclass(frozen=True)
class Band:
    """A range of finishing positions that means something: a berth, a playoff, a drop."""

    key: str
    label: str
    first: int
    last: int
    # "up" bands are good news (continental berths, playoffs); "down" bands are
    # relegation or a relegation playoff. The front-end colours by this.
    kind: str = "up"

    def __post_init__(self) -> None:
        if self.first < 1 or self.last < self.first:
            raise ValueError(f"band {self.key}: invalid range {self.first}-{self.last}")

    def contains(self, pos: int) -> bool:
        return self.first <= pos <= self.last


@dataclass(frozen=True)
class SplitConfig:
    """
    The Belgian split: after the regular season the table divides into a
    championship group, a European group and a relegation group, each playing
    a double round-robin among themselves with the regular-season points halved
    (rounded up) carried in. The champion is first in the championship group.
    """

    top: int = 6
    europe: int = 6
    relegation: int = 4
    halve_points: bool = True


@dataclass(frozen=True)
class PlayoffConfig:
    """
    A post-season playoff. `kind` is "mls" or "liguilla".

    MLS Cup playoffs, as played from 2023.

    Per conference: seeds 1-7 qualify directly, 8 and 9 play a single wildcard match
    (hosted by 8) for the last place. Round One is a best-of-three with the higher
    seed hosting games one and three; the winners are re-seeded so the highest
    remaining seed meets the lowest. Conference semi-finals, finals and MLS Cup are
    single matches hosted by the higher seed — MLS Cup by the side with more
    regular-season points. There are no draws: Round One goes straight to a
    shootout, the later rounds to extra time and then a shootout.

    Liga MX Liguilla: one table; seeds 1-6 qualify directly, 7-10 play a play-in
    (7 hosts 8, 9 hosts 10; the 7v8 winner takes seed 7, the loser hosts the 9v10
    winner for seed 8). Quarter-finals, semi-finals and the final are two-legged
    with the higher seed at home in the second leg, re-seeded after each round;
    a level aggregate favours the higher seed (no extra time) except in the final.
    """

    kind: str = "mls"
    direct_per_conference: int = 7
    wildcard_seeds: tuple[int, int] = (8, 9)
    round_one_best_of: int = 3
    # liguilla
    direct: int = 6
    play_in: tuple[int, int, int, int] = (7, 8, 9, 10)

    @property
    def qualifiers_per_conference(self) -> int:
        return self.wildcard_seeds[1]

    @property
    def qualifiers(self) -> int:
        return self.play_in[-1] if self.kind == "liguilla" else self.qualifiers_per_conference


@dataclass(frozen=True)
class StageFormat:
    """
    One tournament inside a calendar-year season (an Apertura, a Clausura / Finalización, Uruguay's Intermedio).

    `final_phase` says how the stage's champion is decided once its round robin is over:
      "table"      first in the table (Peru, Uruguay's Apertura and Clausura);
      "knockout8"  the top 8 in a two-legged quarter-final, semi-final and final, the 1st and 2nd seeded into
                   opposite halves and the other six drawn (Colombia's Apertura 2026);
      "groups8"    the top 8 in two groups of four (1st and 2nd head them, 3rd-8th drawn), a double round robin,
                   then the two group winners in a two-legged final (Colombia's Finalización 2026);
      "group_final" two groups seeded from an earlier stage's table, a single round robin each, and the two
                   group winners in a one-match final (Uruguay's Intermedio).
    """

    key: str
    label: str
    final_phase: str = "table"
    # group_final: the earlier stage whose table seeds the groups, and which positions go to group A.
    seed_from: str | None = None
    group_a: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.final_phase not in ("table", "knockout8", "groups8", "group_final"):
            raise ValueError(f"stage {self.key}: unknown final phase {self.final_phase}")


@dataclass(frozen=True)
class TorneoFormat:
    """
    A calendar-year season played as several tournaments plus an aggregate table: Colombia, Uruguay, Peru.

    `champion` names how the season's own champion is decided:
      "stages"   every stage crowns its own champion and there is no single season champion (Colombia);
      "uruguay"  the Apertura and Clausura winners meet in a semi-final and its winner plays the aggregate
                 leader in a two-legged final; a club that wins both, or that leads the aggregate and wins the
                 semi-final, is champion outright;
      "peru"     the Apertura and Clausura winners (when in the aggregate top 8) and the aggregate 1st and 2nd
                 play two-legged semi-finals and a final (Reglamento Liga1 2026, 7.3); a club that wins both
                 stages is champion outright.
    `berths` names the continental allocation rule ("colombia", "uruguay", "peru"); the counts are the places.
    Relegation is either by promedio (points per match over `promedio_years` seasons, regular phases only, a
    club promoted later averaging over its own seasons) or by the aggregate table (`relegation_by`).
    """

    stages: tuple[StageFormat, ...]
    aggregate_label: str
    champion: str = "stages"
    berths: str = "colombia"
    libertadores: int = 4
    sudamericana: int = 4
    # Which matches the aggregate table counts: "regular" (each stage's round robin, Uruguay's Intermedio
    # groups included) or "all" (every match, playoffs too: Colombia's reclasificación).
    aggregate_matches: str = "regular"
    relegation_places: int = 2
    relegation_by: str = "promedio"
    promedio_years: int = 0
    # Which matches the promedio counts: "round_robin" (each stage's round robin only: Colombia) or "aggregate"
    # (every match of the aggregate table: Uruguay's Tabla Anual).
    promedio_matches: str = "round_robin"
    # Seasons a club promoted into the window averages over, when it is fewer than promedio_years: computed from
    # the seasons it actually played in the top flight (the store), so nothing is listed here.

    def __post_init__(self) -> None:
        if self.champion not in ("stages", "uruguay", "peru"):
            raise ValueError(f"unknown champion rule {self.champion}")
        if self.berths not in ("colombia", "uruguay", "peru"):
            raise ValueError(f"unknown berth rule {self.berths}")
        if self.relegation_by not in ("promedio", "aggregate"):
            raise ValueError(f"unknown relegation rule {self.relegation_by}")
        if self.relegation_by == "promedio" and self.promedio_years < 1:
            raise ValueError("relegation by promedio needs promedio_years")

    def stage(self, key: str) -> StageFormat | None:
        return next((s for s in self.stages if s.key == key), None)


@dataclass(frozen=True)
class LeagueConfig:
    """Everything about a league that a future season might change."""

    slug: str
    name: str
    short_name: str
    country: str
    sofascore_id: int
    n_teams: int
    bands: tuple[Band, ...]
    # Season label style: "split" is Aug-May ("26/27"), "calendar" is one year.
    season_style: str = "split"
    tiebreak: tuple[str, ...] = TIEBREAK_GD
    # Two conferences and a playoff, or None for a plain table.
    conferences: tuple[str, ...] | None = None
    playoff: PlayoffConfig | None = None
    # The Belgian split, or None.
    split: SplitConfig | None = None
    # A second Sofascore unique-tournament whose seasons also train the model
    # (Liga MX's Clausura beside its Apertura).
    alt_sofascore_id: int | None = None
    # Team-name registry in sources/teams.py.
    registry: str = ""
    # The Odds API sport key, when one exists.
    odds_api_sport: str | None = None
    # Whether the tiebreak is really head-to-head, so the methodology tab can say so.
    h2h_tiebreak: bool = False
    # Relegation places decided directly by position (the "down" bands of kind
    # "rel"); a relegation playoff is a separate band.
    points_win: int = 3
    points_draw: int = 1
    # A season played as several tournaments and an aggregate table (Colombia, Uruguay, Peru), or None.
    torneo: TorneoFormat | None = None
    # Points the competition took off (or added to) a club this season, by stage key ("" for a single table) and
    # club: ((stage, club, points), ...). Sofascore's results carry no sanctions, so they are listed here with the
    # source, checked against Sofascore's own standings at each discovery.
    point_adjustments: tuple[tuple[str, str, int], ...] = ()
    # Results the competition counts that Sofascore's match list lacks (a match awarded after it was called off, a
    # match missing from the list): ((stage, home, away, home goals, away goals), ...). Found by comparing the
    # tables with Sofascore's own standings at discovery; an awarded match is 3-0, an unlisted one is entered as
    # 1-0 or 0-0 from the points it gave (the real score is not in the data).
    unlisted_results: tuple[tuple[str, str, str, int, int], ...] = ()
    # Libertadores places decided outside the table this season (Chile's Copa de la Liga champion, Peru's or
    # Colombia's cups): a note for the methodology tab.
    berth_note: str = ""

    # ── simulation ────────────────────────────────────────────────────────────
    n_sims: int = 100_000
    sim_chunk: int = 25_000
    random_seed: int = 42
    max_goals: int = 8
    extra_time_weight: float = 0.5

    def __post_init__(self) -> None:
        if not self.registry:
            object.__setattr__(self, "registry", self.slug.replace("-", "_"))
        seen: set[str] = set()
        for band in self.bands:
            if band.key in seen:
                raise ValueError(f"{self.slug}: duplicate band key {band.key}")
            seen.add(band.key)
            if band.last > self.n_teams:
                raise ValueError(
                    f"{self.slug}: band {band.key} ends at {band.last} but the league has "
                    f"{self.n_teams} teams"
                )
        if self.playoff is not None and self.playoff.kind == "mls" and self.conferences is None:
            raise ValueError(f"{self.slug}: an MLS-style playoff needs conferences")
        if self.conferences is not None and (self.playoff is None or self.playoff.kind != "mls"):
            raise ValueError(f"{self.slug}: conferences need an MLS-style playoff")
        if self.split is not None and self.split.top + self.split.europe + self.split.relegation != self.n_teams:
            raise ValueError(f"{self.slug}: split groups do not add up to n_teams")
        if self.conferences is not None and self.n_teams % len(self.conferences):
            raise ValueError(f"{self.slug}: teams do not split evenly across conferences")

    @property
    def teams_per_conference(self) -> int:
        return self.n_teams // len(self.conferences) if self.conferences else self.n_teams

    @property
    def relegation_bands(self) -> tuple[Band, ...]:
        return tuple(b for b in self.bands if b.kind == "down")

    @property
    def direct_relegation_places(self) -> int:
        return sum(b.last - b.first + 1 for b in self.bands if b.kind == "down" and "playoff" not in b.key)

    def band(self, key: str) -> Band | None:
        return next((b for b in self.bands if b.key == key), None)


# ── European continental bands ───────────────────────────────────────────────

def _europe(ucl: int, uel: tuple[int, int] | None, uecl: int | None, rel_po: int | None,
            rel: tuple[int, int], ucl_q: int | None = None) -> tuple[Band, ...]:
    out = [Band("ucl", "Champions League", 1, ucl)]
    if ucl_q:
        out.append(Band("ucl_q", "Champions League qualifying", ucl_q, ucl_q))
    if uel:
        out.append(Band("uel", "Europa League", uel[0], uel[1]))
    if uecl:
        out.append(Band("uecl", "Conference League", uecl, uecl))
    if rel_po:
        out.append(Band("rel_playoff", "Relegation playoff", rel_po, rel_po, kind="down"))
    out.append(Band("rel", "Relegation", rel[0], rel[1], kind="down"))
    return tuple(out)


PREMIER_LEAGUE = LeagueConfig(
    slug="premier-league", name="Premier League", short_name="EPL", country="England",
    sofascore_id=17, n_teams=20,
    bands=_europe(ucl=4, uel=(5, 5), uecl=None, rel_po=None, rel=(18, 20)),
    odds_api_sport="soccer_epl",
)

LA_LIGA = LeagueConfig(
    slug="la-liga", name="LaLiga", short_name="LaLiga", country="Spain",
    sofascore_id=8, n_teams=20,
    bands=_europe(ucl=4, uel=(5, 5), uecl=6, rel_po=None, rel=(18, 20)),
    odds_api_sport="soccer_spain_la_liga", h2h_tiebreak=True,
)

SERIE_A = LeagueConfig(
    slug="serie-a", name="Serie A", short_name="Serie A", country="Italy",
    sofascore_id=23, n_teams=20,
    bands=_europe(ucl=4, uel=(5, 5), uecl=6, rel_po=None, rel=(18, 20)),
    odds_api_sport="soccer_italy_serie_a", h2h_tiebreak=True,
)

BUNDESLIGA = LeagueConfig(
    slug="bundesliga", name="Bundesliga", short_name="Bundesliga", country="Germany",
    sofascore_id=35, n_teams=18,
    bands=_europe(ucl=4, uel=(5, 5), uecl=6, rel_po=16, rel=(17, 18)),
    odds_api_sport="soccer_germany_bundesliga",
)

LIGUE_1 = LeagueConfig(
    slug="ligue-1", name="Ligue 1", short_name="Ligue 1", country="France",
    sofascore_id=34, n_teams=18,
    bands=_europe(ucl=3, ucl_q=4, uel=(5, 5), uecl=6, rel_po=16, rel=(17, 18)),
    odds_api_sport="soccer_france_ligue_one",
)

EREDIVISIE = LeagueConfig(
    slug="eredivisie", name="Eredivisie", short_name="Eredivisie", country="Netherlands",
    sofascore_id=37, n_teams=18,
    bands=(
        Band("ucl", "Champions League", 1, 1),
        Band("ucl_q", "Champions League qualifying", 2, 2),
        Band("uel_q", "Europa League qualifying", 3, 3),
        Band("euro_playoff", "European playoff", 4, 7),
        Band("rel_playoff", "Relegation playoff", 16, 16, kind="down"),
        Band("rel", "Relegation", 17, 18, kind="down"),
    ),
    odds_api_sport="soccer_netherlands_eredivisie",
)

PRIMEIRA_LIGA = LeagueConfig(
    slug="primeira-liga", name="Liga Portugal", short_name="Liga Portugal", country="Portugal",
    sofascore_id=238, n_teams=18,
    bands=(
        Band("ucl", "Champions League", 1, 2),
        Band("ucl_q", "Champions League qualifying", 3, 3),
        Band("uel_q", "Europa League qualifying", 4, 4),
        Band("uecl", "Conference League qualifying", 5, 5),
        Band("rel_playoff", "Relegation playoff", 16, 16, kind="down"),
        Band("rel", "Relegation", 17, 18, kind="down"),
    ),
    odds_api_sport="soccer_portugal_primeira_liga",
)

BRASILEIRAO = LeagueConfig(
    slug="brasileirao", name="Brasileirão Série A", short_name="Brasileirão", country="Brazil",
    sofascore_id=325, n_teams=20, season_style="calendar",
    # The CBF breaks ties on wins before goal difference.
    tiebreak=TIEBREAK_WINS,
    bands=(
        Band("lib", "Copa Libertadores", 1, 4),
        Band("lib_q", "Libertadores qualifying", 5, 5),
        Band("sud", "Copa Sudamericana", 6, 11),
        Band("rel", "Relegation", 17, 20, kind="down"),
    ),
    odds_api_sport="soccer_brazil_campeonato",
)

SAUDI_PRO_LEAGUE = LeagueConfig(
    slug="saudi-pro-league", name="Saudi Pro League", short_name="Saudi Pro League",
    country="Saudi Arabia", sofascore_id=955, n_teams=18,
    bands=(
        Band("acl_elite", "AFC Champions League Elite", 1, 5),
        Band("acl_two", "AFC Champions League Two", 6, 6),
        Band("rel", "Relegation", 16, 18, kind="down"),
    ),
)

MLS = LeagueConfig(
    slug="mls", name="Major League Soccer", short_name="MLS", country="USA / Canada",
    sofascore_id=242, n_teams=30, season_style="calendar",
    tiebreak=TIEBREAK_WINS,
    conferences=("Eastern", "Western"),
    playoff=PlayoffConfig(),
    # Bands are per conference for MLS.
    bands=(
        Band("playoffs", "Playoffs", 1, 7),
        Band("wildcard", "Wild Card", 8, 9),
    ),
    odds_api_sport="soccer_usa_mls",
)

LIGA_MX = LeagueConfig(
    slug="liga-mx", name="Liga MX", short_name="Liga MX", country="Mexico",
    sofascore_id=11621, alt_sofascore_id=11620, n_teams=18, season_style="calendar",
    playoff=PlayoffConfig(kind="liguilla"),
    # Relegation is suspended in Liga MX through the 2025-26 cycle.
    bands=(
        Band("liguilla", "Liguilla", 1, 6),
        Band("play_in", "Play-in", 7, 10),
    ),
    odds_api_sport="soccer_mexico_ligamx",
)

BELGIAN_PRO_LEAGUE = LeagueConfig(
    slug="belgian-pro-league", name="Belgian Pro League", short_name="Pro League", country="Belgium",
    # 18 clubs from 2026-27 (16 before). The split keeps a six-club championship
    # group and a six-club European group; the remaining six play the relegation
    # group. VERIFY the relegation rules of the 18-club format at the next
    # rollover — the bottom two below assume one direct drop and one playoff.
    sofascore_id=38, n_teams=18,
    split=SplitConfig(top=6, europe=6, relegation=6),
    # Bands read the post-split order: championship group 1-6, European group
    # 7-12, relegation group 13-18.
    bands=(
        Band("ucl", "Champions League", 1, 1),
        Band("ucl_q", "Champions League qualifying", 2, 2),
        Band("uel", "Europa League", 3, 3),
        Band("uecl_q", "Conference League qualifying", 4, 4),
        Band("euro_group", "European play-offs", 7, 12),
        Band("rel_playoff", "Relegation playoff", 17, 17, kind="down"),
        Band("rel", "Relegation", 18, 18, kind="down"),
    ),
    odds_api_sport="soccer_belgium_first_div",
)

# ── South America beyond Brazil and Argentina (added 2 Nov 2026) ─────────────
# Formats checked against each competition's 2026 regulations (research notes, 2 Nov 2026):
#   Colombia: DIMAYOR, Reglamento Liga BetPlay DIMAYOR I y II 2026 (V12, Jan 2026),
#             https://dimayor.com.co/wp-content/uploads/2026/01/REGLAMENTO-LIGA-2026-V12.pdf
#   Chile:    ANFP, Bases Campeonato Nacional de Primera División 2026, https://www.anfp.cl/bases/
#   Peru:     Reglamento Liga1 Te Apuesto 2026 (v6),
#             https://liga1.pe/wp-content/uploads/2026/03/Reglamento-Liga1-Te-Apuesto-2026.pdf
#   Uruguay:  no AUF reglamento for 2026 was found online. The format is taken from the 2026 season articles
#             (https://en.wikipedia.org/wiki/2026_Liga_AUF_Uruguaya and the Spanish one), RSSSF
#             (https://rsssf.org/tablesu/uru2026.html) and ESPN; the unconfirmed points are marked below.

# Chile breaks level points on goal difference, then wins, then goals scored (Bases 2026, Art. 82).
TIEBREAK_CHILE = ("pts", "gd", "w", "gf")

LIGA_DE_PRIMERA = LeagueConfig(
    slug="liga-de-primera", name="Liga de Primera", short_name="Liga de Primera", country="Chile",
    # 16 clubs, a double round robin of 30 rounds (Art. 78). A tie on points for first is settled by a single
    # play-off match (Art. 83), which the simulation approximates with the table order.
    sofascore_id=11653, n_teams=16, season_style="calendar", tiebreak=TIEBREAK_CHILE,
    bands=(
        # Art. 85: Chile 1 and 2 are first and second; Chile 3 is the Copa de la Liga champion; Chile 4 is the
        # winner of one match between third place and the Copa Chile champion, whose loser takes Sudamericana
        # Chile 4. Art. 86: Sudamericana Chile 1-3 are 4th to 6th. Art. 88: the bottom two go down, no promedio.
        Band("lib", "Copa Libertadores", 1, 2),
        Band("lib_po", "Libertadores play-off", 3, 3),
        Band("sud", "Copa Sudamericana", 4, 6),
        Band("rel", "Relegation", 15, 16, kind="down"),
    ),
    # Sofascore's standings on 2 Nov 2026 against the results: two Unión La Calera matches awarded to their opponents
    # (an extra foreign player), the draws with Everton and Cobresal becoming losses.
    point_adjustments=(("", "Everton de Viña del Mar", 2), ("", "Cobresal", 2), ("", "Unión La Calera", -2)),
    berth_note=("Chile 3 in the Libertadores goes to the Copa de la Liga champion and Chile 4 to the winner of a "
                "match between third place and the Copa Chile champion (Bases 2026, Art. 85); when a cup winner "
                "already holds a league place the berth passes down (Art. 87), which these bands do not follow."),
)

PRIMERA_A_COLOMBIA = LeagueConfig(
    slug="primera-a-colombia", name="Liga BetPlay DIMAYOR", short_name="Primera A", country="Colombia",
    # Sofascore files 2026 under the Apertura's tournament (11539, "Liga DIMAYOR 2026", both halves in one season);
    # until 2025 the Finalización was its own tournament (11536).
    sofascore_id=11539, alt_sofascore_id=11536, n_teams=20, season_style="calendar",
    # Arts. 9 and 20: points, goal difference, goals scored, away goals, fewest conceded (away goals and the
    # conceded criteria are not simulated).
    bands=(Band("playoffs", "Playoffs (top 8)", 1, 8),),
    torneo=TorneoFormat(
        stages=(
            # Liga I 2026: 19 rounds, then the top 8 in two-legged quarter-finals (1st and 2nd seeded apart),
            # semi-finals and final, ties on points then aggregate goal difference then penalties (Arts. 7-15).
            StageFormat("apertura", "Apertura", final_phase="knockout8"),
            # Liga II 2026: 19 rounds with home and away reversed, then two groups of four headed by 1st and 2nd
            # (3rd-8th drawn), a double round robin, and the group winners in a two-legged final (Arts. 18-24);
            # a group tie on points goes to the 1st or 2nd club that heads it (Art. 22).
            StageFormat("clausura", "Finalización", final_phase="groups8"),
        ),
        aggregate_label="Reclasificación",
        # Arts. 27-28: every 2026 match, the playoffs included.
        aggregate_matches="all",
        champion="stages",
        # Art. 30: Col 1 and 2 are the two champions, Col 3 and 4 the best two others in the reclasificación;
        # a double champion's place passes down the reclasificación. Art. 31: Sudamericana Col 1 is the Copa
        # BetPlay champion, Col 2-4 the best unqualified clubs in the reclasificación.
        berths="colombia", libertadores=4, sudamericana=4,
        # Arts. 32-34: the bottom two of the promedio, points per match over the round robins of 2024-I to 2026-II
        # (a club promoted since averages over its own tournaments).
        relegation_places=2, relegation_by="promedio", promedio_years=3, promedio_matches="round_robin",
    ),
    # Three Apertura 2026 results Sofascore's standings count and its match list lacks (2 Nov 2026).
    unlisted_results=(
        ("apertura", "Alianza Valledupar FC", "Internacional de Bogotá", 0, 1),
        ("apertura", "Once Caldas", "Alianza Valledupar FC", 0, 0),
        ("apertura", "Boyacá Chicó FC", "Atlético Bucaramanga", 0, 1),
    ),
    berth_note=("Sudamericana Colombia 1 is the Copa BetPlay champion (Art. 31); the simulation draws it from "
                "the Copa Colombia's own simulation when there is one, and passes it down the reclasificación "
                "when the winner already holds a place (press reports; the article does not say)."),
)

PRIMERA_DIVISION_URUGUAY = LeagueConfig(
    slug="primera-division-uruguay", name="Liga AUF Uruguaya", short_name="Primera División", country="Uruguay",
    sofascore_id=278, n_teams=16, season_style="calendar",
    bands=(),
    torneo=TorneoFormat(
        stages=(
            StageFormat("apertura", "Apertura"),
            # Two groups of eight seeded by the Apertura (A: 1, 4, 5, 8, 9, 12, 13, 16), a single round robin each,
            # the winners in a one-match final (RSSSF, Wikipedia).
            StageFormat("intermedio", "Intermedio", final_phase="group_final", seed_from="apertura",
                        group_a=(1, 4, 5, 8, 9, 12, 13, 16)),
            StageFormat("clausura", "Clausura"),
        ),
        aggregate_label="Tabla Anual",
        aggregate_matches="regular",
        # The Apertura and Clausura winners meet in a semi-final (one match per RSSSF; unconfirmed), its winner
        # plays the Tabla Anual leader over two legs; a club that wins both stages, or that leads the Anual and
        # wins the semi-final, is champion outright.
        champion="uruguay",
        # Uy1 champion, Uy2 runner-up, Uy3 the best Anual club not yet in, Uy4 the Copa AUF Uruguay champion
        # (outside the model: Sofascore does not carry that cup, so the place goes down the Anual here).
        # Sudamericana: the next four of the Anual (the 2025 practice; the Intermedio winner's place reported by
        # Wikipedia is unconfirmed).
        berths="uruguay", libertadores=4, sudamericana=4,
        # The bottom three of the promedio over 2025 and 2026 (clubs promoted for 2026 average over 2026);
        # the Wikipedia table marks two, its text and the Segunda's three promotions say three.
        relegation_places=3, relegation_by="promedio", promedio_years=2, promedio_matches="aggregate",
    ),
    # Sofascore's standings on 2 Nov 2026 against its match list: four results it counts and does not list, the
    # Intermedio match Peñarol v Liverpool called off and awarded to Liverpool, and one point off Peñarol in the
    # Clausura.
    unlisted_results=(
        ("apertura", "Albion FC", "Juventud de Las Piedras", 1, 0),
        ("apertura", "Central Español", "Danubio", 0, 0),
        ("apertura", "Deportivo Maldonado", "Nacional", 1, 0),
        ("intermedio", "Club Atlético Peñarol", "Liverpool UY", 0, 3),
        ("clausura", "Progreso", "CA Cerro", 0, 1),
        ("clausura", "Cerro Largo", "Central Español", 0, 0),
    ),
    point_adjustments=(("clausura", "Club Atlético Peñarol", -1),),
    berth_note=("Uruguay 4 in the Libertadores is the Copa AUF Uruguay champion, a cup Sofascore does not carry; "
                "the simulation gives that place to the next club in the Tabla Anual, and the Sudamericana "
                "places follow the Anual (the 2025 practice). No AUF reglamento for 2026 was found."),
)

LIGA_1_PERU = LeagueConfig(
    slug="liga-1-peru", name="Liga 1", short_name="Liga 1", country="Peru",
    sofascore_id=406, n_teams=18, season_style="calendar",
    # 14.1: points, goal difference, goals scored, fair play (not simulated).
    bands=(),
    torneo=TorneoFormat(
        stages=(StageFormat("apertura", "Apertura"), StageFormat("clausura", "Clausura")),
        aggregate_label="Tabla Acumulada",
        aggregate_matches="regular",
        champion="peru",
        # Art. 9: Libertadores Peru 1-4 are the final places 1-4 (champion, runner-up, the better and the worse
        # losing semi-finalist by the Acumulada); Sudamericana Peru 1-4 are places 5-8.
        berths="peru", libertadores=4, sudamericana=4,
        # 10.2: the bottom two of the Acumulada go down; no promedio.
        relegation_places=2, relegation_by="aggregate",
    ),
    # Sanctions in Sofascore's standings on 2 Nov 2026 (and the press): Universidad Técnica de Cajamarca five points in
    # each stage, Sport Boys four, Asociación Deportiva Tarma one and FC Cajamarca two on the Acumulada only.
    point_adjustments=(
        ("apertura", "Universidad Técnica de Cajamarca", -5), ("clausura", "Universidad Técnica de Cajamarca", -5),
        ("", "Sport Boys", -4), ("", "Asociación Deportiva Tarma", -1), ("", "FC Cajamarca", -2),
    ),
    # Cienciano v Deportivo Garcilaso in the Clausura: counted as a draw in Sofascore's standings, not in its list.
    unlisted_results=(("clausura", "Cienciano", "Deportivo Garcilaso", 0, 0),),
)

LEAGUES: dict[str, LeagueConfig] = {
    cfg.slug: cfg for cfg in (
        PREMIER_LEAGUE, LA_LIGA, SERIE_A, BUNDESLIGA, LIGUE_1,
        EREDIVISIE, PRIMEIRA_LIGA, BRASILEIRAO, MLS, SAUDI_PRO_LEAGUE,
        LIGA_MX, BELGIAN_PRO_LEAGUE,
        PRIMERA_A_COLOMBIA, PRIMERA_DIVISION_URUGUAY, LIGA_DE_PRIMERA, LIGA_1_PERU,
    )
}
# The four South American leagues added on 2 Nov 2026, in the order the site lists them.
CONMEBOL_LEAGUES = ("primera-a-colombia", "primera-division-uruguay", "liga-de-primera", "liga-1-peru")

# Slug of the Argentine competition in the combined site. It is built by its own
# package and script, but the site index needs a stable key for it.
LIGA_ARGENTINA_SLUG = "liga-argentina"


def get_league(slug: str) -> LeagueConfig:
    try:
        return LEAGUES[slug]
    except KeyError:
        raise KeyError(f"unknown league {slug!r}; known: {sorted(LEAGUES)}") from None


def with_sims(cfg: LeagueConfig, n_sims: int) -> LeagueConfig:
    """A copy with a different simulation count, chunked sensibly."""
    from dataclasses import replace
    return replace(cfg, n_sims=n_sims, sim_chunk=min(n_sims, cfg.sim_chunk))
