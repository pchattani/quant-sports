"""
Cup formats as data.

Verified against each competition's 2026 regulations at the time of writing:

  Champions / Europa League — 36 clubs, 8 league-phase matches each (4 home, 4
  away against drawn opponents). Top 8 go straight to the Round of 16; 9-24 play
  a two-legged knockout play-off in February, the better-placed side at home in
  the second leg; 25-36 are out. From the Round of 16 the bracket is fixed and
  two-legged, with the higher league-phase finisher hosting the return leg; the
  final is a single match at a neutral venue. No away-goals rule.
  Conference League — the same with 6 league-phase matches each.

  Libertadores / Sudamericana — 8 groups of 4, home and away. Libertadores: the
  top two of each group reach a two-legged Round of 16 (group winners seeded, at
  home in the second leg), third place drops into the Sudamericana knockout
  round. Sudamericana: group winners go straight to the Round of 16; runners-up
  first face a Libertadores third-placed side over two legs. Quarter- and
  semi-finals are two-legged; the final is a single match at a neutral venue.

  AFC Champions League Elite — from 2026-27, 32 clubs in two regional leagues of
  16 (West, East), 8 matches each. The top eight of each region reach a
  two-legged Round of 16 played within the region (1 v 8, 2 v 7 ...); the
  quarter-finals, semi-finals and final are single matches at a centralised
  venue (Saudi Arabia until 2029), the quarter-finals pairing West against East.

  CAF Champions League — two qualifying rounds, then 16 clubs in four groups of
  four, home and away. The top two of each group reach two-legged quarter-finals
  (group winners against runners-up of other groups, drawn); the semi-finals and
  the final are also two-legged.

  CONCACAF Champions Cup — 27 clubs in a straight knockout: a two-legged Round
  One for 22 of them (five byes), then two-legged Round of 16, quarter-finals and
  semi-finals and a single-match final. The bracket is fixed by the draw, which
  the store carries once it is made.

  Intercontinental Cup — six continental champions in a fixed ladder: the AFC and
  OFC champions meet, the winner plays the CAF champion; the CONMEBOL and
  CONCACAF champions meet (the Derby of the Americas); the two survivors play
  for the right to face the UEFA champion in the final. All single matches.

Bracket draws (the UEFA play-off pairings, the CONMEBOL Round of 16 draw) are
random within constraints; the simulator draws them itself until the real draw
is in the store, after which the drawn pairs are used.
"""
from __future__ import annotations

from dataclasses import dataclass

from oddsmarkets.football.competitions.league.config import Band

# Knockout round keys, outermost first, and how many legs each is played over.
SWISS_ROUNDS: tuple[tuple[str, int], ...] = (("po", 2), ("r16", 2), ("qf", 2), ("sf", 2), ("final", 1))
GROUP_ROUNDS: tuple[tuple[str, int], ...] = (("r16", 2), ("qf", 2), ("sf", 2), ("final", 1))
ROUND_LABELS = {
    "po": "Knockout play-off", "r16": "Round of 16", "qf": "Quarter-final",
    "sf": "Semi-final", "final": "Final",
    "r1": "Round 1", "r2": "Round 2", "derby": "Derby of the Americas", "playoff": "Play-off",
}


@dataclass(frozen=True)
class FixedSlot:
    """
    A participant in a fixed bracket.

    `source` is one of: a literal club name; "winner:<round>" for a winner from
    an earlier round of this bracket; "champion:<competition-slug>" for the
    simulated winner of another competition on the site, drawn per simulation
    from that competition's title probabilities.
    """

    source: str


@dataclass(frozen=True)
class FixedTie:
    key: str
    label: str
    home: FixedSlot
    away: FixedSlot
    neutral: bool = False


@dataclass(frozen=True)
class CupConfig:
    slug: str
    name: str
    short_name: str
    region: str
    sofascore_id: int
    kind: str                                   # swiss | groups | regional_swiss | knockout | fixed
    n_teams: int
    rounds: tuple[tuple[str, int], ...] = ()
    # swiss
    direct_qualifiers: int = 8                  # straight to the Round of 16
    playoff_last: int = 24                      # 9..playoff_last enter the play-off
    # groups
    n_groups: int = 8
    group_size: int = 4
    group_advance: int = 2
    # Sudamericana: runners-up face an outside opponent before the Round of 16.
    runners_up_playoff: bool = False
    # Bands drawn on the league-phase or group tables.
    bands: tuple[Band, ...] = ()
    # fixed brackets
    ties: tuple[FixedTie, ...] = ()
    final_at_neutral_venue: bool = True
    # Rounds played as single matches at a centralised venue (no home side).
    neutral_rounds: tuple[str, ...] = ()
    # What the competition is: cup (continental / world), domestic (a national
    # cup), super (a one- or two-match super cup), international (national teams).
    family: str = "cup"
    # When the Sofascore id is not known, discovery searches this name and keeps
    # the unique tournament whose category matches `country_hint`.
    search: str | None = None
    country_hint: str | None = None
    # "followed": per-match detail only for matches with a club from a league the
    # site follows (a national cup's early rounds are mostly lower-league clubs).
    detail_scope: str = "all"
    # Every match at a neutral venue (a finals tournament), for the model.
    neutral_venues: bool = False
    # Friendlies count for half in the international fit.
    friendly: bool = False
    # Round slugs Sofascore uses in this competition that differ from the shared map.
    round_slugs: tuple[tuple[str, str], ...] = ()
    tiebreak: tuple[str, ...] = ("pts", "gd", "gf")
    odds_api_sport: str | None = None
    points_win: int = 3
    points_draw: int = 1
    n_sims: int = 100_000
    sim_chunk: int = 25_000
    random_seed: int = 42
    max_goals: int = 8
    extra_time_weight: float = 0.5

    def __post_init__(self) -> None:
        if self.kind not in ("swiss", "groups", "regional_swiss", "knockout", "fixed", "international"):
            raise ValueError(f"{self.slug}: unknown kind {self.kind}")
        if self.family not in ("cup", "domestic", "super", "international"):
            raise ValueError(f"{self.slug}: unknown family {self.family}")
        if self.kind in ("groups", "regional_swiss") and self.n_groups * self.group_size != self.n_teams:
            raise ValueError(f"{self.slug}: groups do not add up to n_teams")
        if self.kind == "fixed" and not self.ties:
            raise ValueError(f"{self.slug}: a fixed bracket needs ties")

    @property
    def conferences(self):          # duck-typing with LeagueConfig for shared readers
        return None

    @property
    def playoff(self):
        return None

    @property
    def round_keys(self) -> tuple[str, ...]:
        if self.kind == "fixed":
            return tuple(t.key for t in self.ties)
        return tuple(r for r, _ in self.rounds)

    @property
    def registry(self) -> str:                      # national teams canonicalise through the international registry
        return "international" if self.family == "international" else ""

    @property
    def simulated(self) -> bool:
        return self.kind != "international"

    @property
    def teams_per_conference(self) -> int:
        return self.group_size if self.kind in ("groups", "regional_swiss") else self.n_teams


def _uefa(slug: str, name: str, short: str, sofascore_id: int, matches: int, odds: str | None) -> CupConfig:
    return CupConfig(
        slug=slug, name=name, short_name=short, region="Europe", sofascore_id=sofascore_id,
        kind="swiss", n_teams=36, rounds=SWISS_ROUNDS, direct_qualifiers=8, playoff_last=24,
        bands=(
            Band("r16", "Round of 16", 1, 8),
            Band("po", "Knockout play-off", 9, 24),
            Band("out", "Eliminated", 25, 36, kind="down"),
        ),
        odds_api_sport=odds,
    )


CHAMPIONS_LEAGUE = _uefa("champions-league", "UEFA Champions League", "Champions League", 7, 8, "soccer_uefa_champs_league")
EUROPA_LEAGUE = _uefa("europa-league", "UEFA Europa League", "Europa League", 679, 8, "soccer_uefa_europa_league")
CONFERENCE_LEAGUE = _uefa("conference-league", "UEFA Conference League", "Conference League", 17015, 6, None)

LIBERTADORES = CupConfig(
    slug="libertadores", name="CONMEBOL Libertadores", short_name="Libertadores", region="South America",
    sofascore_id=384, kind="groups", n_teams=32, rounds=GROUP_ROUNDS,
    bands=(
        Band("r16", "Round of 16", 1, 2),
        Band("sud", "Sudamericana", 3, 3),
        Band("out", "Eliminated", 4, 4, kind="down"),
    ),
    odds_api_sport="soccer_conmebol_copa_libertadores",
)

SUDAMERICANA = CupConfig(
    slug="sudamericana", name="CONMEBOL Sudamericana", short_name="Sudamericana", region="South America",
    sofascore_id=480, kind="groups", n_teams=32, rounds=(("po", 2),) + GROUP_ROUNDS,
    runners_up_playoff=True,
    bands=(
        Band("r16", "Round of 16", 1, 1),
        Band("po", "Knockout play-off", 2, 2),
        Band("out", "Eliminated", 3, 4, kind="down"),
    ),
)

AFC_CHAMPIONS_LEAGUE = CupConfig(
    slug="afc-champions-league", name="AFC Champions League Elite", short_name="ACL Elite", region="Asia",
    sofascore_id=463, kind="regional_swiss", n_teams=32, n_groups=2, group_size=16, direct_qualifiers=8,
    rounds=(("r16", 2), ("qf", 1), ("sf", 1), ("final", 1)), neutral_rounds=("qf", "sf", "final"),
    bands=(
        Band("r16", "Round of 16", 1, 8),
        Band("out", "Eliminated", 9, 16, kind="down"),
    ),
)

CAF_CHAMPIONS_LEAGUE = CupConfig(
    slug="caf-champions-league", name="CAF Champions League", short_name="CAF Champions League", region="Africa",
    sofascore_id=1054, kind="groups", n_teams=16, n_groups=4, group_size=4,
    rounds=(("qf", 2), ("sf", 2), ("final", 2)), final_at_neutral_venue=False,
    bands=(
        Band("qf", "Quarter-finals", 1, 2),
        Band("out", "Eliminated", 3, 4, kind="down"),
    ),
)

CONCACAF_CHAMPIONS_CUP = CupConfig(
    slug="concacaf-champions-cup", name="CONCACAF Champions Cup", short_name="Champions Cup", region="CONCACAF",
    sofascore_id=498, kind="knockout", n_teams=27,
    rounds=(("r1", 2), ("r16", 2), ("qf", 2), ("sf", 2), ("final", 1)), final_at_neutral_venue=False,
)

# The 2026 edition. Rounds already played are read from the store and forced. The
# CONCACAF champion (Toluca, June 2026) and the UEFA champion (PSG, May 2026) are
# known and named; the Libertadores winner is drawn from that competition's own
# simulation. Replace the names at each edition.
INTERCONTINENTAL_CUP = CupConfig(
    slug="intercontinental-cup", name="FIFA Intercontinental Cup", short_name="Intercontinental Cup",
    region="World", sofascore_id=23674, kind="fixed", n_teams=6,
    ties=(
        FixedTie("r1", "Round 1 (AFC v OFC)", FixedSlot("Al-Ahli"), FixedSlot("Auckland FC")),
        FixedTie("r2", "Round 2 (CAF v winner)", FixedSlot("Mamelodi Sundowns"), FixedSlot("winner:r1")),
        FixedTie("derby", "Derby of the Americas", FixedSlot("champion:libertadores"), FixedSlot("Toluca")),
        FixedTie("playoff", "Play-off", FixedSlot("winner:derby"), FixedSlot("winner:r2")),
        FixedTie("final", "Final", FixedSlot("PSG"), FixedSlot("winner:playoff"), neutral=True),
    ),
)


# The FIFA Club World Cup (every four years; 2025 in the United States): eight
# groups of four, then single-match knockout rounds. Its matches are also the
# largest bridge between the continental blocks in the pooled fit.
CLUB_WORLD_CUP = CupConfig(
    slug="club-world-cup", name="FIFA Club World Cup", short_name="Club World Cup", region="World",
    sofascore_id=357, kind="groups", n_teams=32, n_groups=8, group_size=4,
    rounds=(("r16", 1), ("qf", 1), ("sf", 1), ("final", 1)), final_at_neutral_venue=True, neutral_venues=True,
    bands=(Band("r16", "Round of 16", 1, 2), Band("out", "Eliminated", 3, 4, kind="down")),
)

# ── national cups and super cups ─────────────────────────────────────────────
# Round keys are outermost first; a national cup's early rounds are mostly clubs
# the site does not follow, so per-match detail is fetched only for matches with
# a followed club (`detail_scope="followed"`). Most ties are single matches; the
# two-legged rounds are marked. Sofascore ids are resolved by discovery from
# `search` + `country_hint` and kept in seasons.json.

_R = {"r64": "Round of 64", "r32": "Round of 32", "r16": "Round of 16", "r1": "1st round", "r2": "2nd round",
      "r3": "3rd round", "r4": "4th round", "r5": "5th round", "r6": "6th round", "3rd": "Third-place match"}
for _k, _v in _R.items():
    ROUND_LABELS.setdefault(_k, _v)      # the front-end and the fetcher label these rounds too
# Domestic-cup round slugs Sofascore uses that the shared map reads differently
# (the shared map sends "round-of-32" to the UEFA play-off).
_DOMESTIC_SLUGS = (
    ("round-of-64", "r64"), ("1-32", "r64"), ("round-of-32", "r32"), ("1-16", "r32"),
    ("1st-round", "r1"), ("first-round", "r1"), ("2nd-round", "r2"), ("second-round", "r2"),
    ("3rd-round", "r3"), ("third-round", "r3"), ("4th-round", "r4"), ("fourth-round", "r4"),
    ("5th-round", "r5"), ("fifth-round", "r5"), ("6th-round", "r6"), ("sixth-round", "r6"),
)


def _domestic(slug: str, name: str, short: str, country: str, search: str, hint: str,
              rounds: tuple[tuple[str, int], ...], sofascore_id: int = 0, family: str = "domestic",
              neutral_final: bool = True) -> CupConfig:
    return CupConfig(
        slug=slug, name=name, short_name=short, region=country, sofascore_id=sofascore_id,
        kind="knockout", n_teams=64, rounds=rounds, final_at_neutral_venue=neutral_final,
        family=family, search=search, country_hint=hint, detail_scope="followed", round_slugs=_DOMESTIC_SLUGS,
    )


_ONE = (("final", 1),)
_FOUR = (("sf", 1), ("final", 1))

FA_CUP = _domestic("fa-cup", "FA Cup", "FA Cup", "England", "FA Cup", "England",
                   (("r1", 1), ("r2", 1), ("r3", 1), ("r4", 1), ("r5", 1), ("qf", 1), ("sf", 1), ("final", 1)))
EFL_CUP = _domestic("efl-cup", "EFL Cup", "EFL Cup", "England", "EFL Cup", "England",
                    (("r1", 1), ("r2", 1), ("r3", 1), ("r4", 1), ("qf", 1), ("sf", 2), ("final", 1)))
COMMUNITY_SHIELD = _domestic("community-shield", "FA Community Shield", "Community Shield", "England", "Community Shield", "England", _ONE, family="super")
COPA_DEL_REY = _domestic("copa-del-rey", "Copa del Rey", "Copa del Rey", "Spain", "Copa del Rey", "Spain",
                         (("r1", 1), ("r2", 1), ("r32", 1), ("r16", 1), ("qf", 1), ("sf", 2), ("final", 1)))
SUPERCOPA_ESPANA = _domestic("supercopa-espana", "Supercopa de España", "Supercopa", "Spain", "Supercopa", "Spain", _FOUR, family="super")
COPPA_ITALIA = _domestic("coppa-italia", "Coppa Italia", "Coppa Italia", "Italy", "Coppa Italia", "Italy",
                         (("r1", 1), ("r32", 1), ("r16", 1), ("qf", 1), ("sf", 2), ("final", 1)))
SUPERCOPPA_ITALIANA = _domestic("supercoppa-italiana", "Supercoppa Italiana", "Supercoppa", "Italy", "Supercoppa Italiana", "Italy", _FOUR, family="super")
DFB_POKAL = _domestic("dfb-pokal", "DFB-Pokal", "DFB-Pokal", "Germany", "DFB Pokal", "Germany",
                      (("r1", 1), ("r2", 1), ("r16", 1), ("qf", 1), ("sf", 1), ("final", 1)))
DFL_SUPERCUP = _domestic("dfl-supercup", "DFL-Supercup", "DFL-Supercup", "Germany", "Franz Beckenbauer Supercup", "Germany", _ONE, sofascore_id=799, family="super")
COUPE_DE_FRANCE = _domestic("coupe-de-france", "Coupe de France", "Coupe de France", "France", "Coupe de France", "France",
                            (("r64", 1), ("r32", 1), ("r16", 1), ("qf", 1), ("sf", 1), ("final", 1)))
TROPHEE_DES_CHAMPIONS = _domestic("trophee-des-champions", "Trophée des Champions", "Trophée des Champions", "France", "Trophee des Champions", "France", _ONE, family="super")
KNVB_BEKER = _domestic("knvb-beker", "KNVB Beker", "KNVB Beker", "Netherlands", "KNVB Beker", "Netherlands",
                       (("r1", 1), ("r2", 1), ("r16", 1), ("qf", 1), ("sf", 1), ("final", 1)))
JOHAN_CRUIJFF_SCHAAL = _domestic("johan-cruijff-schaal", "Johan Cruijff Schaal", "Cruijff Schaal", "Netherlands", "Johan Cruijff Schaal", "Netherlands", _ONE, family="super")
TACA_DE_PORTUGAL = _domestic("taca-de-portugal", "Taça de Portugal", "Taça de Portugal", "Portugal", "Taca de Portugal", "Portugal",
                             (("r3", 1), ("r4", 1), ("r5", 1), ("qf", 1), ("sf", 2), ("final", 1)))
TACA_DA_LIGA = _domestic("taca-da-liga", "Taça da Liga", "Taça da Liga", "Portugal", "Taca da Liga", "Portugal",
                         (("r3", 1), ("qf", 1), ("sf", 1), ("final", 1)))
SUPERTACA = _domestic("supertaca-portugal", "Supertaça Cândido de Oliveira", "Supertaça", "Portugal", "Supertaca", "Portugal", _ONE, family="super")
BELGIAN_CUP = _domestic("belgian-cup", "Belgian Cup", "Belgian Cup", "Belgium", "Belgian Cup", "Belgium",
                        (("r5", 1), ("r6", 1), ("r16", 1), ("qf", 1), ("sf", 2), ("final", 1)))
BELGIAN_SUPER_CUP = _domestic("belgian-super-cup", "Belgian Super Cup", "Belgian Super Cup", "Belgium", "Belgian Super Cup", "Belgium", _ONE, family="super")
COPA_DO_BRASIL = _domestic("copa-do-brasil", "Copa do Brasil", "Copa do Brasil", "Brazil", "Copa do Brasil", "Brazil",
                           (("r1", 1), ("r2", 1), ("r3", 2), ("r16", 2), ("qf", 2), ("sf", 2), ("final", 2)), sofascore_id=373, neutral_final=False)
SUPERCOPA_DO_BRASIL = _domestic("supercopa-do-brasil", "Supercopa do Brasil", "Supercopa do Brasil", "Brazil", "Supercopa do Brasil", "Brazil", _ONE, family="super")
COPA_ARGENTINA = _domestic("copa-argentina", "Copa Argentina", "Copa Argentina", "Argentina", "Copa Argentina", "Argentina",
                           (("r64", 1), ("r32", 1), ("r16", 1), ("qf", 1), ("sf", 1), ("final", 1)))
SUPERCOPA_ARGENTINA = _domestic("supercopa-argentina", "Supercopa Argentina", "Supercopa Argentina", "Argentina", "Supercopa Argentina", "Argentina", _ONE, family="super")
KINGS_CUP = _domestic("kings-cup", "Saudi King's Cup", "King's Cup", "Saudi Arabia", "King Cup", "Saudi Arabia",
                      (("r32", 1), ("r16", 1), ("qf", 1), ("sf", 1), ("final", 1)), sofascore_id=2058)
SAUDI_SUPER_CUP = _domestic("saudi-super-cup", "Saudi Super Cup", "Saudi Super Cup", "Saudi Arabia", "Saudi Super Cup", "Saudi Arabia", _FOUR, family="super")
US_OPEN_CUP = _domestic("us-open-cup", "U.S. Open Cup", "US Open Cup", "USA", "US Open Cup", "USA",
                        (("r3", 1), ("r4", 1), ("r32", 1), ("r16", 1), ("qf", 1), ("sf", 1), ("final", 1)), neutral_final=False)
LEAGUES_CUP = _domestic("leagues-cup", "Leagues Cup", "Leagues Cup", "USA / Mexico", "Leagues Cup", "USA",
                        (("qf", 1), ("sf", 1), ("final", 1)), family="cup", neutral_final=False)
CAMPEONES_CUP = _domestic("campeones-cup", "Campeones Cup", "Campeones Cup", "USA / Mexico", "Campeones Cup", "USA", _ONE, family="super", neutral_final=False)
CAMPEON_DE_CAMPEONES = _domestic("campeon-de-campeones", "Campeón de Campeones", "Campeón de Campeones", "Mexico", "Campeon de Campeones", "Mexico", _ONE, family="super")
UEFA_SUPER_CUP = _domestic("uefa-super-cup", "UEFA Super Cup", "UEFA Super Cup", "Europe", "UEFA Super Cup", "Europe", _ONE, sofascore_id=465, family="super")
RECOPA = _domestic("recopa-sudamericana", "CONMEBOL Recopa", "Recopa", "South America", "CONMEBOL Recopa", "South America",
                   (("final", 2),), sofascore_id=490, family="super", neutral_final=False)

# ── national teams ───────────────────────────────────────────────────────────
# Not simulated: fixtures, results, tables where there are groups, the knockout
# ladder as drawn, players, and the model's line on each match from the
# international fit (`neutral_venues` says whether the tournament is played at
# neutral grounds). Team names canonicalise through the international registry.

_INTL_SLUGS = (("round-of-32", "r32"), ("round-of-64", "r64"), ("third-place", "3rd"), ("3rd-place", "3rd"),
               ("third-place-playoff", "3rd"), ("match-for-3rd-place", "3rd"))


def _intl(slug: str, name: str, short: str, search: str, hint: str, rounds: tuple[tuple[str, int], ...] = (),
          sofascore_id: int = 0, neutral: bool = False, friendly: bool = False) -> CupConfig:
    return CupConfig(
        slug=slug, name=name, short_name=short, region="International", sofascore_id=sofascore_id,
        kind="international", n_teams=32, rounds=rounds, family="international", search=search, country_hint=hint,
        neutral_venues=neutral, friendly=friendly, round_slugs=_INTL_SLUGS, final_at_neutral_venue=True,
    )


# Sofascore ids verified 2 October 2026. Search had resolved every "World Cup
# Qualification" to the Conifa qualifiers (28716) and the Asian Cup was pinned to
# 247, a Bulgarian league; the confederations' qualifiers are 11 (UEFA),
# 295 (CONMEBOL), 14 (CONCACAF), 13 (CAF), 308 (AFC) and the Asian Cup is 246.
_WC_ROUNDS = (("r32", 1), ("r16", 1), ("qf", 1), ("sf", 1), ("final", 1))
_TOURNAMENT_ROUNDS = (("r16", 1), ("qf", 1), ("sf", 1), ("final", 1))

WORLD_CUP = _intl("world-cup", "FIFA World Cup", "World Cup", "World Cup", "World", _WC_ROUNDS, sofascore_id=16, neutral=True)
EURO = _intl("euro", "UEFA European Championship", "Euro", "European Championship", "Europe", _TOURNAMENT_ROUNDS, sofascore_id=1, neutral=True)
COPA_AMERICA = _intl("copa-america", "CONMEBOL Copa América", "Copa América", "Copa America", "South America", (("qf", 1), ("sf", 1), ("final", 1)), sofascore_id=133, neutral=True)
NATIONS_LEAGUE = _intl("nations-league", "UEFA Nations League", "Nations League", "UEFA Nations League", "Europe", (("qf", 2), ("sf", 1), ("final", 1)))
EURO_QUALIFIERS = _intl("euro-qualifiers", "European Championship Qualification", "Euro qualifiers", "EURO, Qualification", "Europe", (("po", 1),), sofascore_id=27)
WC_QUAL_UEFA = _intl("wc-qual-uefa", "World Cup Qualification, UEFA", "WC qualifiers (UEFA)", "World Cup Qualification", "Europe", (("po", 1),), sofascore_id=11)
WC_QUAL_CONMEBOL = _intl("wc-qual-conmebol", "World Cup Qualification, CONMEBOL", "WC qualifiers (CONMEBOL)", "World Cup Qualification", "South America", sofascore_id=295)
WC_QUAL_CONCACAF = _intl("wc-qual-concacaf", "World Cup Qualification, CONCACAF", "WC qualifiers (CONCACAF)", "World Cup Qualification", "North & Central America", sofascore_id=14)
WC_QUAL_CAF = _intl("wc-qual-caf", "World Cup Qualification, CAF", "WC qualifiers (CAF)", "World Cup Qualification", "Africa", sofascore_id=13)
WC_QUAL_AFC = _intl("wc-qual-afc", "World Cup Qualification, AFC", "WC qualifiers (AFC)", "World Cup Qualification", "Asia", sofascore_id=308)
AFCON = _intl("afcon", "Africa Cup of Nations", "AFCON", "Africa Cup of Nations", "Africa", _TOURNAMENT_ROUNDS, sofascore_id=270, neutral=True)
AFCON_QUALIFIERS = _intl("afcon-qualifiers", "Africa Cup of Nations Qualification", "AFCON qualifiers", "Africa Cup of Nations Qual.", "Africa", sofascore_id=1848)
ASIAN_CUP = _intl("asian-cup", "AFC Asian Cup", "Asian Cup", "Asian Cup", "Asia", _TOURNAMENT_ROUNDS, sofascore_id=246, neutral=True)
GOLD_CUP = _intl("gold-cup", "CONCACAF Gold Cup", "Gold Cup", "Gold Cup", "North & Central America", (("qf", 1), ("sf", 1), ("final", 1)), sofascore_id=140, neutral=True)
CONCACAF_NATIONS_LEAGUE = _intl("concacaf-nations-league", "CONCACAF Nations League", "CONCACAF NL", "CONCACAF Nations League", "North & Central America", (("qf", 2), ("sf", 1), ("final", 1)))
FRIENDLIES = _intl("friendlies", "International Friendlies", "Friendlies", "International Friendly Games", "World", sofascore_id=851, friendly=True)

CUPS: dict[str, CupConfig] = {
    c.slug: c for c in (
        CHAMPIONS_LEAGUE, EUROPA_LEAGUE, CONFERENCE_LEAGUE, UEFA_SUPER_CUP,
        LIBERTADORES, SUDAMERICANA, RECOPA,
        AFC_CHAMPIONS_LEAGUE, CAF_CHAMPIONS_LEAGUE, CONCACAF_CHAMPIONS_CUP, LEAGUES_CUP, CAMPEONES_CUP,
        CLUB_WORLD_CUP, INTERCONTINENTAL_CUP,
        FA_CUP, EFL_CUP, COMMUNITY_SHIELD, COPA_DEL_REY, SUPERCOPA_ESPANA, COPPA_ITALIA, SUPERCOPPA_ITALIANA,
        DFB_POKAL, DFL_SUPERCUP, COUPE_DE_FRANCE, TROPHEE_DES_CHAMPIONS, KNVB_BEKER, JOHAN_CRUIJFF_SCHAAL,
        TACA_DE_PORTUGAL, TACA_DA_LIGA, SUPERTACA, BELGIAN_CUP, BELGIAN_SUPER_CUP,
        COPA_DO_BRASIL, SUPERCOPA_DO_BRASIL, COPA_ARGENTINA, SUPERCOPA_ARGENTINA,
        KINGS_CUP, SAUDI_SUPER_CUP, US_OPEN_CUP, CAMPEON_DE_CAMPEONES,
        WORLD_CUP, EURO, COPA_AMERICA, NATIONS_LEAGUE, EURO_QUALIFIERS,
        WC_QUAL_UEFA, WC_QUAL_CONMEBOL, WC_QUAL_CONCACAF, WC_QUAL_CAF, WC_QUAL_AFC,
        AFCON, AFCON_QUALIFIERS, ASIAN_CUP, GOLD_CUP, CONCACAF_NATIONS_LEAGUE, FRIENDLIES,
    )
}
CUP_FAMILIES = {"cup": "Continental & world", "domestic": "National cups", "super": "Super cups", "international": "National teams"}
INTERNATIONALS: dict[str, CupConfig] = {k: v for k, v in CUPS.items() if v.family == "international"}

# Country (alpha-3) -> league slug, for mapping a cup entrant onto the league it
# plays in. Clubs from countries not listed keep the cup's own prefix in the
# pooled fit and start at the pool's average.
COUNTRY_LEAGUE: dict[str, str] = {
    # Sofascore uses ISO alpha-3 (DEU, PRT, NLD); the FIFA codes are kept as aliases.
    "ENG": "premier-league", "ESP": "la-liga", "ITA": "serie-a", "GER": "bundesliga", "DEU": "bundesliga",
    "FRA": "ligue-1", "NED": "eredivisie", "NLD": "eredivisie", "POR": "primeira-liga", "PRT": "primeira-liga",
    "BRA": "brasileirao", "USA": "mls", "CAN": "mls", "SAU": "saudi-pro-league", "KSA": "saudi-pro-league",
    "ARG": "liga-argentina", "MEX": "liga-mx", "BEL": "belgian-pro-league",
}
