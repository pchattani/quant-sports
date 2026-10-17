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

LEAGUES: dict[str, LeagueConfig] = {
    cfg.slug: cfg for cfg in (
        PREMIER_LEAGUE, LA_LIGA, SERIE_A, BUNDESLIGA, LIGUE_1,
        EREDIVISIE, PRIMEIRA_LIGA, BRASILEIRAO, MLS, SAUDI_PRO_LEAGUE,
        LIGA_MX, BELGIAN_PRO_LEAGUE,
    )
}

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
