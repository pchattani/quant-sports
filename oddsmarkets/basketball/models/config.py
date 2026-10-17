"""
Per-league, per-season competition format for the season simulation and the game model.

`fmt(league, season)` returns a `SeasonFormat`. It never raises: any season from 1997 on
gets a format (older seasons get the nearest rule set), and an unknown league gets the
current NBA rules. Only the *current* format needs to be exactly right for the season
simulation; the historical rows exist so that loaders, the backtest and history pages
do not crash and so the season-sim calibration can replay recent seasons.

What was checked against data (ESPN standings, 1 Oct 2026)
    NBA 2025-26 (season 2026): 30 teams, 15 per conference, 82 games each.
    WNBA 2026: 15 teams (East 7: ATL CHI CON IND NY TOR WSH; West 8: DAL GS LV LA MIN PHX
    POR SEA), 44 games each; Kalshi KXWNBA-26 lists 15 runners and Polymarket's WNBA
    "advance to semifinals" market lists 8 playoff teams.

Taken from the published rules, not checked against data here
    NBA: tiebreak order, play-in shape, 2-2-1-1-1, the 2019 lottery table, NBA Cup
    (group games count in the standings, the knockout final does not).
    WNBA: 8 playoff teams seeded 1-8 regardless of conference; first round best-of-3
    (1-1-1, higher seed hosts games 1 and 3), semifinals best-of-5 (2-2-1), finals best-of-7
    (2-2-1-1-1) from 2025; WNBA tiebreaks (head-to-head, record vs .500+ teams, head-to-head
    point differential, overall point differential). Historical WNBA team counts and
    game counts are from memory and marked `verified=False`.

Tiebreak criteria names (see season_sim.CRITERIA): h2h, div_winner, div_record,
conf_record, vs_playoff_own, vs_playoff_other, vs_500, h2h_pd, pd.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

# ── series home patterns (H = higher seed at home) ───────────────────────────
PATTERNS = {1: "H", 3: "HAH", 5: "HHAAH", 7: "HHAAHAH"}
PATTERN_232 = "HHAAAHH"           # NBA Finals 1985-2013

# ── NBA draft lottery: combinations out of 1000 for the #1 pick ─────────────
LOTTERY_2019 = [140, 140, 140, 125, 105, 90, 75, 60, 45, 30, 20, 15, 10, 5]
LOTTERY_1995 = [250, 199, 156, 119, 88, 63, 43, 28, 17, 11, 8, 7, 6, 5]

NBA_TB_TWO = ("h2h", "div_winner", "div_record", "conf_record", "vs_playoff_own", "vs_playoff_other", "pd")
NBA_TB_MULTI = ("div_winner", "h2h", "div_record", "conf_record", "vs_playoff_own", "pd")
WNBA_TB_TWO = ("h2h", "vs_500", "h2h_pd", "pd")
WNBA_TB_MULTI = ("h2h", "vs_500", "h2h_pd", "pd")

# ── canonical alignments (ESPN abbreviations); the store's own team fields win ─
NBA_DIVISIONS = {
    "East": {"Atlantic": ["BOS", "BKN", "NY", "PHI", "TOR"],
             "Central": ["CHI", "CLE", "DET", "IND", "MIL"],
             "Southeast": ["ATL", "CHA", "MIA", "ORL", "WSH"]},
    "West": {"Northwest": ["DEN", "MIN", "OKC", "POR", "UTAH"],
             "Pacific": ["GS", "LAC", "LAL", "PHX", "SAC"],
             "Southwest": ["DAL", "HOU", "MEM", "NO", "SA"]},
}
WNBA_CONFERENCES = {
    "East": {"East": ["ATL", "CHI", "CON", "IND", "NY", "TOR", "WSH"]},
    "West": {"West": ["DAL", "GS", "LV", "LA", "MIN", "PHX", "POR", "SEA"]},
}

# ── arenas: (lat, lon, standard UTC offset, altitude m) by ESPN abbreviation ──
NBA_ARENAS = {
    "ATL": (33.757, -84.396, -5, 320), "BOS": (42.366, -71.062, -5, 5), "BKN": (40.683, -73.976, -5, 10),
    "CHA": (35.225, -80.839, -5, 230), "CHI": (41.881, -87.674, -6, 180), "CLE": (41.497, -81.688, -5, 200),
    "DAL": (32.790, -96.810, -6, 140), "DEN": (39.749, -105.008, -7, 1609), "DET": (42.341, -83.055, -5, 190),
    "GS": (37.768, -122.388, -8, 5), "HOU": (29.751, -95.362, -6, 15), "IND": (39.764, -86.156, -5, 220),
    "LAC": (33.945, -118.343, -8, 30), "LAL": (34.043, -118.267, -8, 90), "MEM": (35.138, -90.051, -6, 80),
    "MIA": (25.781, -80.188, -5, 2), "MIL": (43.045, -87.917, -6, 190), "MIN": (44.980, -93.276, -6, 260),
    "NO": (29.949, -90.082, -6, 2), "NY": (40.751, -73.993, -5, 10), "OKC": (35.463, -97.515, -6, 370),
    "ORL": (28.539, -81.384, -5, 30), "PHI": (39.901, -75.172, -5, 10), "PHX": (33.446, -112.071, -7, 330),
    "POR": (45.532, -122.667, -8, 15), "SAC": (38.580, -121.500, -8, 8), "SA": (29.427, -98.437, -6, 200),
    "TOR": (43.643, -79.379, -5, 80), "UTAH": (40.768, -111.901, -7, 1288), "UTA": (40.768, -111.901, -7, 1288),
    "WSH": (38.898, -77.021, -5, 20),
    # former franchises / abbreviations that may appear in older stores
    "SEA": (47.622, -122.354, -8, 30), "NJ": (40.812, -74.074, -5, 5), "VAN": (49.278, -123.109, -8, 10),
    "NOH": (29.949, -90.082, -6, 2), "NOK": (35.463, -97.515, -6, 370), "CHH": (35.225, -80.839, -5, 230),
}
WNBA_ARENAS = {
    "ATL": (33.650, -84.450, -5, 300), "CHI": (41.870, -87.620, -6, 180), "CON": (41.490, -72.090, -5, 60),
    "IND": (39.764, -86.156, -5, 220), "NY": (40.683, -73.976, -5, 10), "TOR": (43.640, -79.420, -5, 80),
    "WSH": (38.860, -76.990, -5, 20), "DAL": (32.730, -97.110, -6, 180), "GS": (37.768, -122.388, -8, 5),
    "LV": (36.090, -115.178, -8, 610), "LA": (34.043, -118.267, -8, 90), "MIN": (44.980, -93.276, -6, 260),
    "PHX": (33.446, -112.071, -7, 330), "POR": (45.532, -122.667, -8, 15), "SEA": (47.622, -122.354, -8, 30),
}
ALTITUDE_TEAMS = {"nba": ("DEN", "UTAH", "UTA"), "wnba": ()}


@dataclass(frozen=True)
class SeasonFormat:
    league: str
    season: int
    n_teams: int
    games: int
    seeding: str = "conference"              # "conference" (NBA) or "league" (WNBA since 2016)
    conferences: dict = field(default_factory=dict)   # conf -> division -> [abbr]
    direct: int = 6                          # direct playoff places per seeding group
    playin: bool = True                      # 7v8 / 9v10 / loser-v-winner
    playin_seeds: tuple = (7, 10)
    playoff_teams: int = 8                   # per seeding group (16 NBA, 8 WNBA)
    series: tuple = (7, 7, 7, 7)             # best-of per round, last = finals
    patterns: tuple = ("HHAAHAH",) * 4
    rounds: tuple = ("r1", "semis", "conf_finals", "finals")
    reseed: bool = False
    finals_home: str = "record"              # better regular-season record hosts
    tb_two: tuple = NBA_TB_TWO
    tb_multi: tuple = NBA_TB_MULTI
    eligible_n: int = 10                     # "playoff eligible" for the vs-playoff-teams tiebreaks
    lottery: tuple | None = tuple(LOTTERY_2019)
    lottery_draws: int = 4
    cup: dict | None = None                  # NBA Cup: group and knockout games are stype "reg"; the final is "cup" and does not count
    period_s: int = 720
    ot_s: int = 300
    verified: bool = True
    notes: tuple = ()

    @property
    def group_size(self) -> int:
        return self.n_teams if self.seeding == "league" else max(1, self.n_teams // max(1, len(self.conferences) or 2))

    def as_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["series"], d["patterns"], d["rounds"] = list(self.series), list(self.patterns), list(self.rounds)
        d["tb_two"], d["tb_multi"] = list(self.tb_two), list(self.tb_multi)
        d["lottery"] = list(self.lottery) if self.lottery else None
        d["playin_seeds"] = list(self.playin_seeds)
        d["notes"] = list(self.notes)
        return d


def _nba(season: int) -> SeasonFormat:
    s = int(season)
    n_teams = 29 if s <= 2004 else 30
    games = {1999: 50, 2012: 66, 2020: 72, 2021: 72}.get(s, 82)       # 2020: ~64-75 played (bubble)
    notes = []
    if s == 2020:
        notes.append("2019-20: season suspended; 22 teams resumed in the bubble with 8 seeding games and a 8v9 play-in")
    playin = s >= 2021
    series_r1 = 5 if s <= 2002 else 7
    finals_pat = PATTERN_232 if 1985 <= s <= 2013 else PATTERNS[7]
    pats = (PATTERNS[series_r1], PATTERNS[7], PATTERNS[7], finals_pat)
    if s <= 2004:
        conferences = {"East": {"Atlantic": [], "Central": []}, "West": {"Midwest": [], "Pacific": []}}
        notes.append("two divisions per conference before 2004-05; alignment taken from the store")
    else:
        conferences = NBA_DIVISIONS
    lottery = tuple(LOTTERY_2019) if s >= 2019 else tuple(LOTTERY_1995)
    draws = 4 if s >= 2019 else 3
    cup = {"group_games": 4, "final_counts": False, "knockout_counts": True} if s >= 2024 else None
    return SeasonFormat(
        league="nba", season=s, n_teams=n_teams, games=games, seeding="conference", conferences=conferences,
        direct=6 if playin else 8, playin=playin, playin_seeds=(7, 10), playoff_teams=8,
        series=(series_r1, 7, 7, 7), patterns=pats, rounds=("r1", "semis", "conf_finals", "finals"),
        tb_two=NBA_TB_TWO, tb_multi=NBA_TB_MULTI, eligible_n=10 if playin else 8,
        lottery=lottery, lottery_draws=draws, cup=cup, period_s=720,
        verified=s >= 2026, notes=tuple(notes))


# WNBA team counts and games per season (1997 on). 2026 checked against ESPN standings.
_WNBA_TEAMS = {1997: 8, 1998: 10, 1999: 12, 2000: 16, 2001: 16, 2002: 16, 2003: 14, 2004: 13, 2005: 13, 2006: 14,
               2007: 13, 2008: 14, 2009: 13, 2025: 13, 2026: 15}
_WNBA_GAMES = {1997: 28, 1998: 30, 1999: 32, 2000: 32, 2001: 32, 2002: 32, 2020: 22, 2021: 32, 2022: 36, 2023: 40,
               2024: 40, 2025: 44, 2026: 44}


def _wnba(season: int) -> SeasonFormat:
    s = int(season)
    n_teams = _WNBA_TEAMS.get(s, 12 if 2010 <= s <= 2024 else 15)
    games = _WNBA_GAMES.get(s, 34 if 2003 <= s <= 2019 else 44)
    if s >= 2025:
        series, pats = (3, 5, 7), (PATTERNS[3], PATTERNS[5], PATTERNS[7])
    elif s >= 2022:
        series, pats = (3, 5, 5), (PATTERNS[3], PATTERNS[5], PATTERNS[5])
    elif s >= 2016:
        series, pats = (1, 1, 5, 5), ("H", "H", PATTERNS[5], PATTERNS[5])
    else:
        series, pats = (3, 3, 5), (PATTERNS[3], PATTERNS[3], PATTERNS[5])
    if s >= 2016:
        seeding, playoff_teams = "league", 8
        rounds = ("r1", "semis", "finals") if len(series) == 3 else ("r1", "r2", "semis", "finals")
    else:
        seeding, playoff_teams = "conference", 4
        rounds = ("r1", "conf_finals", "finals")
    notes = ["2016-2021 first two rounds were single games with byes for seeds 1-2 (simplified here as a bracket)"] if 2016 <= s <= 2021 else []
    return SeasonFormat(
        league="wnba", season=s, n_teams=n_teams, games=games, seeding=seeding, conferences=WNBA_CONFERENCES,
        direct=playoff_teams, playin=False, playoff_teams=playoff_teams, series=series, patterns=pats, rounds=rounds,
        reseed=False, tb_two=WNBA_TB_TWO, tb_multi=WNBA_TB_MULTI, eligible_n=playoff_teams,
        lottery=None, lottery_draws=0, cup=None, period_s=600, verified=s == 2026, notes=tuple(notes))


def fmt(league: str, season: int) -> SeasonFormat:
    """The SeasonFormat for (league, season). Never raises."""
    try:
        s = int(season)
    except (TypeError, ValueError):
        s = 2027
    s = max(1997, s)
    return _wnba(s) if str(league).lower() == "wnba" else _nba(s)


def with_teams(f: SeasonFormat, n_teams: int, games: int | None = None) -> SeasonFormat:
    """The same format resized to the teams actually in a store (expansion, history)."""
    return replace(f, n_teams=int(n_teams), games=int(games or f.games))


def arenas(league: str) -> dict[str, tuple]:
    return WNBA_ARENAS if str(league).lower() == "wnba" else NBA_ARENAS


def canonical_alignment(league: str, abbr: str) -> tuple[str | None, str | None]:
    """(conference, division) for an ESPN abbreviation from the canonical tables, or (None, None)."""
    table = WNBA_CONFERENCES if str(league).lower() == "wnba" else NBA_DIVISIONS
    for conf, divs in table.items():
        for div, teams in divs.items():
            if abbr in teams:
                return conf, div
    return None, None


def norm_conf(name: Any) -> str | None:
    """'Eastern Conference' / 'East' / 'EAST' -> 'East'; None when blank."""
    t = str(name or "").strip().lower()
    if not t:
        return None
    if t.startswith("east"):
        return "East"
    if t.startswith("west"):
        return "West"
    return str(name).strip()


# Defaults for the game model (overridden by fitted values in the cache)
GAME_DEFAULTS = {
    "nba": {"sigma": 12.0, "hca": 2.4, "b2b": -1.6, "rest": 0.4, "travel_1000km": -0.25, "tz": -0.25,
            "altitude": 1.0, "pace": 99.0, "ortg": 114.0, "replacement": -2.0, "sigma_market": 12.0},
    "wnba": {"sigma": 12.5, "hca": 2.0, "b2b": -1.2, "rest": 0.3, "travel_1000km": -0.2, "tz": -0.2,
             "altitude": 0.5, "pace": 80.0, "ortg": 104.0, "replacement": -2.0, "sigma_market": 12.5},
}
ELO_DEFAULTS = {
    "nba": {"k": 20.0, "hca": 100.0, "carry": 0.75, "mean": 1505.0, "new_team": 1300.0, "pts_per_elo": 1 / 28.0},
    "wnba": {"k": 20.0, "hca": 90.0, "carry": 0.70, "mean": 1505.0, "new_team": 1350.0, "pts_per_elo": 1 / 30.0},
}
