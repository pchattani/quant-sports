"""
League constants and identity rules for The Quant Hardwood (NBA and WNBA).

Seasons are labelled by ESPN's `season.year`, the year the season ends in
(NBA 2025-26 = 2026, WNBA 2026 = 2026). Teams, players and games are keyed by
ESPN ids as strings.

Clock: `clock_s` is seconds remaining in the period; `t` is elapsed game seconds,
`period_start(...) + period_len(...) - clock_s`. NBA quarters are 12 minutes;
WNBA quarters are 10 minutes from 2006 (two 20-minute halves 1997-2005);
every overtime is 5 minutes.

Court (feet, from ESPN's shot coordinates, measured empirically in pbp.py):
the three-point arc is 23.75 ft (NBA) or 22.15 ft (WNBA from 2013; 20.5 ft
before), 22 ft in the corners, where the straight corner line runs 14 ft from
the baseline, i.e. 8.75 ft along the floor from the centre of the rim.

Team identity: ESPN keeps one id per franchise through relocations and renames
(Seattle SuperSonics -> Oklahoma City Thunder is id 25 throughout), and its
scoreboards and box scores carry the era's name and abbreviation, so each
season store records the name of its own time. `FRANCHISE_MOVES` documents the
moves for display and history pages; `team_label` picks the name for a season.
"""
from __future__ import annotations

from datetime import date
from typing import Any

LEAGUES = ("nba", "wnba")
LEAGUE_NAMES = {"nba": "NBA", "wnba": "WNBA"}
REG_PERIODS = 4
OT_S = 300

# Earliest seasons ESPN serves: box scores from 1997 (NBA 1996-97 / WNBA's first season);
# play-by-play with coordinates from about 2017 (NBA 2016-17 is patchy; 2018 is complete).
BOX_FROM = {"nba": 1997, "wnba": 1997}
PBP_FROM = {"nba": 2017, "wnba": 2017}


def period_len(league: str, period: int, season: int | None = None) -> int:
    """Length of a period in seconds."""
    lg = str(league).lower()
    p = int(period)
    if lg == "wnba" and season is not None and int(season) < 2006:
        return 1200 if p <= 2 else OT_S
    if p > REG_PERIODS:
        return OT_S
    return 600 if lg == "wnba" else 720


def reg_periods(league: str, season: int | None = None) -> int:
    if str(league).lower() == "wnba" and season is not None and int(season) < 2006:
        return 2
    return REG_PERIODS


def period_start(league: str, period: int, season: int | None = None) -> int:
    """Elapsed game seconds at the start of `period`."""
    p = int(period)
    n = reg_periods(league, season)
    reg = period_len(league, 1, season)
    if p <= n:
        return (p - 1) * reg
    return n * reg + (p - n - 1) * OT_S


def game_t(league: str, period: int, clock_s: float, season: int | None = None) -> float:
    return period_start(league, period, season) + period_len(league, period, season) - float(clock_s)


def regulation_s(league: str, season: int | None = None) -> int:
    return reg_periods(league, season) * period_len(league, 1, season)


def three_point_line(league: str, season: int | None = None) -> tuple[float, float]:
    """(arc radius ft, corner distance ft) of the three-point line."""
    if str(league).lower() == "wnba":
        if season is not None and int(season) < 2013:
            return 20.5, 20.5
        return 22.15, 22.0
    return 23.75, 22.0


CORNER_Y_FT = 8.75        # the straight corner segment, along the floor from the rim centre
LANE_HALF_W_FT = 8.0      # 16-ft lane
FT_LINE_Y_FT = 13.75      # free-throw line, 19 ft from the baseline = 13.75 ft from the rim centre

# ── positions ───────────────────────────────────────────────────────────────

POOL = {
    "G": "G", "PG": "G", "SG": "G",
    "F": "F", "SF": "F", "PF": "F", "G-F": "F", "F-G": "F", "GF": "F", "FG": "F", "F-C": "F", "FC": "F",
    "C": "C", "C-F": "C", "CF": "C",
}


def pool(pos: str | None) -> str | None:
    """Position pool G, F or C from ESPN's position abbreviation (wings and stretch bigs are F)."""
    if not pos:
        return None
    p = str(pos).upper().replace(" ", "")
    if p in POOL:
        return POOL[p]
    return {"GUARD": "G", "FORWARD": "F", "CENTER": "C"}.get(p) or POOL.get(p[:1])


# ── season types ────────────────────────────────────────────────────────────

SEASON_TYPES = {1: "pre", 2: "reg", 3: "post", 4: "off", 5: "playin"}


def stype(season_type: Any, headline: str | None = None) -> str:
    """Contract stype from ESPN's season type id and the event's note headline."""
    h = (headline or "").lower()
    if "all-star" in h or "all star" in h or "rising stars" in h or "celebrity" in h:
        return "allstar"
    if "cup" in h and ("championship" in h or " final" in h) and "semifinal" not in h:
        return "cup"
    if "in-season tournament" in h and "championship" in h:     # the 2023 NBA Cup final's note
        return "cup"
    if h.strip() == "wnba commissioner's cup":                  # the 2021 final's note (the only game so labelled)
        return "cup"
    try:
        t = int(season_type)
    except (TypeError, ValueError):
        return "reg"
    return {1: "pre", 2: "reg", 3: "post", 5: "playin"}.get(t, "reg")


# ── season windows (fallbacks when the core API is unreachable) ─────────────

def season_window(league: str, season: int) -> tuple[date, date]:
    """A generous [first, last] calendar window for a season, used only as a fallback.
    NBA: Sep 25 of the previous year to Jul 31 (the 2020 bubble ran to Oct 11; 2021 to Jul 22).
    WNBA: Apr 1 to Nov 1."""
    y = int(season)
    if str(league).lower() == "wnba":
        return date(y, 4, 1), date(y, 11, 1)
    if y == 2020:
        return date(2019, 9, 25), date(2020, 10, 15)
    if y == 2021:
        return date(2020, 12, 1), date(2021, 7, 25)
    if y == 1999:
        return date(1999, 1, 15), date(1999, 7, 1)
    if y == 2012:
        return date(2011, 12, 1), date(2012, 6, 30)
    return date(y - 1, 9, 25), date(y, 7, 31)


def current_season(league: str, today: date | None = None) -> int:
    """The season label in play (or most recently finished) on `today`."""
    d = today or date.today()
    if str(league).lower() == "wnba":
        return d.year if d.month >= 4 else d.year - 1
    return d.year + 1 if d.month >= 9 else d.year


# ── franchises ──────────────────────────────────────────────────────────────

# ESPN team id -> [(first season under this identity, name, abbreviation)], oldest first.
FRANCHISE_MOVES: dict[str, dict[str, list[tuple[int, str, str]]]] = {
    "nba": {
        "3": [(1997, "Charlotte Hornets", "CHA"), (2003, "New Orleans Hornets", "NO"),
              (2006, "New Orleans/Oklahoma City Hornets", "NOK"), (2008, "New Orleans Hornets", "NO"),
              (2014, "New Orleans Pelicans", "NO")],
        "17": [(1997, "New Jersey Nets", "NJ"), (2013, "Brooklyn Nets", "BKN")],
        "25": [(1997, "Seattle SuperSonics", "SEA"), (2009, "Oklahoma City Thunder", "OKC")],
        "29": [(1997, "Vancouver Grizzlies", "VAN"), (2002, "Memphis Grizzlies", "MEM")],
        "30": [(2005, "Charlotte Bobcats", "CHA"), (2015, "Charlotte Hornets", "CHA")],
        "12": [(1997, "Los Angeles Clippers", "LAC"), (2016, "LA Clippers", "LAC")],
        "27": [(1997, "Washington Bullets", "WSH"), (1998, "Washington Wizards", "WSH")],
    },
    "wnba": {
        "17": [(1997, "Utah Starzz", "UTA"), (2003, "San Antonio Silver Stars", "SA"), (2014, "San Antonio Stars", "SA"),
               (2018, "Las Vegas Aces", "LV")],
        "3": [(1998, "Detroit Shock", "DET"), (2010, "Tulsa Shock", "TUL"), (2016, "Dallas Wings", "DAL")],
        "18": [(1999, "Orlando Miracle", "ORL"), (2003, "Connecticut Sun", "CON")],
        "129689": [(2025, "Golden State Valkyries", "GS")],
        "131935": [(2026, "Toronto Tempo", "TOR")],
        "132052": [(2026, "Portland Fire", "POR")],
    },
}

FIRST_SEASON = {lg: {tid: moves[0][0] for tid, moves in d.items()} for lg, d in FRANCHISE_MOVES.items()}


def team_label(league: str, team_id: str, season: int, store_team: dict | None = None) -> tuple[str | None, str | None]:
    """(name, abbreviation) for a team in a season: the season store's own record when present
    (ESPN gives the era's name), else the franchise table, else (None, None)."""
    if store_team and store_team.get("name"):
        return store_team.get("name"), store_team.get("abbr")
    moves = FRANCHISE_MOVES.get(str(league).lower(), {}).get(str(team_id))
    if not moves:
        return None, None
    cur = None
    for first, name, abbr in moves:
        if int(season) >= first:
            cur = (name, abbr)
    return cur or (None, None)


def team_active(league: str, team_id: str, season: int) -> bool:
    """False only for a season before a known franchise's first season."""
    first = FIRST_SEASON.get(str(league).lower(), {}).get(str(team_id))
    return first is None or int(season) >= first
