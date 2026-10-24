"""
Fixed tables for The Quant Bullpen: levels, game types, positions and the 30 MLB franchises across
sources and seasons (MLBAM id, Stats API / Savant abbreviation, ESPN id, Retrosheet and Baseball-Reference
codes, names by season, league and division by season).

Teams are keyed by MLBAM team id (string in stores). Relocations and renames are kept per season, e.g.
Indians -> Guardians (2022), Oakland Athletics -> Athletics (Sacramento, 2025), Florida -> Miami Marlins
(2012), Expos -> Nationals (2005), Devil Rays -> Rays (2008); Houston moved NL -> AL in 2013 and Milwaukee
AL -> NL in 1998. Triple-A teams (sportId 11) are read per season from the Stats API, not hard-coded.

Verified on 1 Oct 2026 against /api/v1/teams?sportId=1&season=2015 and 2026, ESPN's MLB team list and the
2025 Retrosheet event files.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

LEVELS = ("mlb", "aaa")
SPORT_ID = {"mlb": 1, "aaa": 11}
STATCAST_FROM = {"mlb": 2015, "aaa": 2023}

GAME_TYPES = {
    "R": "Regular season", "F": "Wild Card Series", "D": "Division Series", "L": "League Championship Series",
    "W": "World Series", "S": "Spring training", "E": "Exhibition", "A": "All-Star Game",
    "C": "Championship",
}
# "C": the Stats API's championship game; in Triple-A (sportId 11) the one-game Triple-A National Championship
# between the International and Pacific Coast League champions (2023 on), after the league finals (typed "W")
POSTSEASON = ("F", "D", "L", "W", "C")
SEASON_TYPES = ("R",) + POSTSEASON
SAVANT_GT = "R|F|D|L|W|C|"          # regular season and every postseason round in one search

POSITIONS = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF", 10: "DH",
             11: "PH", 12: "PR"}
POSITION_CODE = {v: k for k, v in POSITIONS.items()}
POSITION_CODE.update({"TWP": 1, "OF": 8, "IF": 6, "Y": 10})

LEAGUES = {"103": "AL", "104": "NL", "117": "IL", "112": "PCL"}
DIVISIONS = {"200": "AL West", "201": "AL East", "202": "AL Central", "203": "NL West", "204": "NL East",
             "205": "NL Central"}

RETROSHEET_FIRST = 1901            # game logs; play-by-play event files exist from 1908
RETRO_ABS_RUNNER_FROM = 2020       # extra innings start with a runner on second (regular season)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_season(today: date | None = None) -> int:
    """Seasons are calendar years; January to mid-March still belongs to the coming season's year."""
    return (today or datetime.now(timezone.utc).date()).year


def season_window(season: int) -> tuple[date, date]:
    """Outer bounds of a season's games (openers abroad in mid-March; a World Series can reach early November)."""
    return date(season, 3, 10), date(season, 11, 10)


# ── franchises ──────────────────────────────────────────────────────────────
# names: [(first season, full name, short name, city)], newest last.
# retro / bbref: [(first season, code)], newest last.
TEAMS: dict[str, dict] = {
    "108": {"abbr": [(1901, "LAA")], "espn": "3", "colour": "#ba0021",
            "names": [(1961, "Los Angeles Angels", "Angels", "Los Angeles"), (1965, "California Angels", "Angels", "Anaheim"),
                      (1997, "Anaheim Angels", "Angels", "Anaheim"),
                      (2005, "Los Angeles Angels of Anaheim", "Angels", "Anaheim"), (2016, "Los Angeles Angels", "Angels", "Anaheim")],
            "retro": [(1961, "LAA"), (1965, "CAL"), (1997, "ANA")], "bbref": [(1961, "LAA"), (1965, "CAL"), (1997, "ANA"), (2005, "LAA")]},
    "109": {"abbr": [(1998, "AZ")], "espn": "29", "colour": "#aa182c",
            "names": [(1998, "Arizona Diamondbacks", "D-backs", "Phoenix")], "retro": [(1998, "ARI")], "bbref": [(1998, "ARI")]},
    "110": {"abbr": [(1901, "BAL")], "espn": "1", "colour": "#df4601",
            "names": [(1901, "Milwaukee Brewers", "Brewers", "Milwaukee"), (1902, "St. Louis Browns", "Browns", "St. Louis"),
                      (1954, "Baltimore Orioles", "Orioles", "Baltimore")],
            "retro": [(1901, "MLA"), (1902, "SLA"), (1954, "BAL")], "bbref": [(1901, "MLA"), (1902, "SLB"), (1954, "BAL")]},
    "111": {"abbr": [(1901, "BOS")], "espn": "2", "colour": "#0d2b56",
            "names": [(1901, "Boston Americans", "Americans", "Boston"), (1908, "Boston Red Sox", "Red Sox", "Boston")],
            "retro": [(1901, "BOS")], "bbref": [(1901, "BOS")]},
    "112": {"abbr": [(1901, "CHC")], "espn": "16", "colour": "#0e3386",
            "names": [(1901, "Chicago Cubs", "Cubs", "Chicago")], "retro": [(1901, "CHN")], "bbref": [(1901, "CHC")]},
    "113": {"abbr": [(1901, "CIN")], "espn": "17", "colour": "#c6011f",
            "names": [(1901, "Cincinnati Reds", "Reds", "Cincinnati")], "retro": [(1901, "CIN")], "bbref": [(1901, "CIN")]},
    "114": {"abbr": [(1901, "CLE")], "espn": "5", "colour": "#002b5c",
            "names": [(1901, "Cleveland Blues", "Blues", "Cleveland"), (1903, "Cleveland Naps", "Naps", "Cleveland"),
                      (1915, "Cleveland Indians", "Indians", "Cleveland"), (2022, "Cleveland Guardians", "Guardians", "Cleveland")],
            "retro": [(1901, "CLE")], "bbref": [(1901, "CLE")]},
    "115": {"abbr": [(1993, "COL")], "espn": "27", "colour": "#33006f",
            "names": [(1993, "Colorado Rockies", "Rockies", "Denver")], "retro": [(1993, "COL")], "bbref": [(1993, "COL")]},
    "116": {"abbr": [(1901, "DET")], "espn": "6", "colour": "#0a2240",
            "names": [(1901, "Detroit Tigers", "Tigers", "Detroit")], "retro": [(1901, "DET")], "bbref": [(1901, "DET")]},
    "117": {"abbr": [(1962, "HOU")], "espn": "18", "colour": "#002d62",
            "names": [(1962, "Houston Colt .45s", "Colt .45s", "Houston"), (1965, "Houston Astros", "Astros", "Houston")],
            "retro": [(1962, "HOU")], "bbref": [(1962, "HOU")]},
    "118": {"abbr": [(1969, "KC")], "espn": "7", "colour": "#004687",
            "names": [(1969, "Kansas City Royals", "Royals", "Kansas City")], "retro": [(1969, "KCA")], "bbref": [(1969, "KCR")]},
    "119": {"abbr": [(1901, "LAD")], "espn": "19", "colour": "#005a9c",
            "names": [(1901, "Brooklyn Dodgers", "Dodgers", "Brooklyn"), (1958, "Los Angeles Dodgers", "Dodgers", "Los Angeles")],
            "retro": [(1901, "BRO"), (1958, "LAN")], "bbref": [(1901, "BRO"), (1958, "LAD")]},
    "120": {"abbr": [(1969, "MON"), (2005, "WSH")], "espn": "20", "colour": "#ab0003",
            "names": [(1969, "Montreal Expos", "Expos", "Montreal"), (2005, "Washington Nationals", "Nationals", "Washington")],
            "retro": [(1969, "MON"), (2005, "WAS")], "bbref": [(1969, "MON"), (2005, "WSN")]},
    "121": {"abbr": [(1962, "NYM")], "espn": "21", "colour": "#002d72",
            "names": [(1962, "New York Mets", "Mets", "Flushing")], "retro": [(1962, "NYN")], "bbref": [(1962, "NYM")]},
    "133": {"abbr": [(1901, "PHA"), (1955, "KCA"), (1968, "OAK"), (2025, "ATH")], "espn": "11", "colour": "#003831",
            "names": [(1901, "Philadelphia Athletics", "Athletics", "Philadelphia"), (1955, "Kansas City Athletics", "Athletics", "Kansas City"),
                      (1968, "Oakland Athletics", "Athletics", "Oakland"), (2025, "Athletics", "Athletics", "Sacramento")],
            "retro": [(1901, "PHA"), (1955, "KC1"), (1968, "OAK"), (2025, "ATH")],
            "bbref": [(1901, "PHA"), (1955, "KCA"), (1968, "OAK"), (2025, "ATH")]},
    "134": {"abbr": [(1901, "PIT")], "espn": "23", "colour": "#27251f",
            "names": [(1901, "Pittsburgh Pirates", "Pirates", "Pittsburgh")], "retro": [(1901, "PIT")], "bbref": [(1901, "PIT")]},
    "135": {"abbr": [(1969, "SD")], "espn": "25", "colour": "#2f241d",
            "names": [(1969, "San Diego Padres", "Padres", "San Diego")], "retro": [(1969, "SDN")], "bbref": [(1969, "SDP")]},
    "136": {"abbr": [(1977, "SEA")], "espn": "12", "colour": "#005c5c",
            "names": [(1977, "Seattle Mariners", "Mariners", "Seattle")], "retro": [(1977, "SEA")], "bbref": [(1977, "SEA")]},
    "137": {"abbr": [(1901, "SF")], "espn": "26", "colour": "#fd5a1e",
            "names": [(1901, "New York Giants", "Giants", "New York"), (1958, "San Francisco Giants", "Giants", "San Francisco")],
            "retro": [(1901, "NY1"), (1958, "SFN")], "bbref": [(1901, "NYG"), (1958, "SFG")]},
    "138": {"abbr": [(1901, "STL")], "espn": "24", "colour": "#be0a14",
            "names": [(1901, "St. Louis Cardinals", "Cardinals", "St. Louis")], "retro": [(1901, "SLN")], "bbref": [(1901, "STL")]},
    "139": {"abbr": [(1998, "TB")], "espn": "30", "colour": "#092c5c",
            "names": [(1998, "Tampa Bay Devil Rays", "Devil Rays", "St. Petersburg"), (2008, "Tampa Bay Rays", "Rays", "St. Petersburg")],
            "retro": [(1998, "TBA")], "bbref": [(1998, "TBD"), (2008, "TBR")]},
    "140": {"abbr": [(1961, "WSA"), (1972, "TEX")], "espn": "13", "colour": "#003278",
            "names": [(1961, "Washington Senators", "Senators", "Washington"), (1972, "Texas Rangers", "Rangers", "Arlington")],
            "retro": [(1961, "WS2"), (1972, "TEX")], "bbref": [(1961, "WSA"), (1972, "TEX")]},
    "141": {"abbr": [(1977, "TOR")], "espn": "14", "colour": "#134a8e",
            "names": [(1977, "Toronto Blue Jays", "Blue Jays", "Toronto")], "retro": [(1977, "TOR")], "bbref": [(1977, "TOR")]},
    "142": {"abbr": [(1901, "WSH"), (1961, "MIN")], "espn": "9", "colour": "#031f40",
            "names": [(1901, "Washington Senators", "Senators", "Washington"), (1961, "Minnesota Twins", "Twins", "Minneapolis")],
            "retro": [(1901, "WS1"), (1961, "MIN")], "bbref": [(1901, "WSH"), (1961, "MIN")]},
    "143": {"abbr": [(1901, "PHI")], "espn": "22", "colour": "#e81828",
            "names": [(1901, "Philadelphia Phillies", "Phillies", "Philadelphia")], "retro": [(1901, "PHI")], "bbref": [(1901, "PHI")]},
    "144": {"abbr": [(1901, "BSN"), (1953, "MLN"), (1966, "ATL")], "espn": "15", "colour": "#0c2340",
            "names": [(1901, "Boston Braves", "Braves", "Boston"), (1953, "Milwaukee Braves", "Braves", "Milwaukee"),
                      (1966, "Atlanta Braves", "Braves", "Atlanta")],
            "retro": [(1901, "BSN"), (1953, "MLN"), (1966, "ATL")], "bbref": [(1901, "BSN"), (1953, "MLN"), (1966, "ATL")]},
    "145": {"abbr": [(1901, "CWS")], "espn": "4", "colour": "#27251f",
            "names": [(1901, "Chicago White Sox", "White Sox", "Chicago")], "retro": [(1901, "CHA")], "bbref": [(1901, "CHW")]},
    "146": {"abbr": [(1993, "FLA"), (2012, "MIA")], "espn": "28", "colour": "#00a3e0",
            "names": [(1993, "Florida Marlins", "Marlins", "Miami"), (2012, "Miami Marlins", "Marlins", "Miami")],
            "retro": [(1993, "FLO"), (2012, "MIA")], "bbref": [(1993, "FLA"), (2012, "MIA")]},
    "147": {"abbr": [(1901, "NYY")], "espn": "10", "colour": "#132448",
            "names": [(1901, "Baltimore Orioles", "Orioles", "Baltimore"), (1903, "New York Highlanders", "Highlanders", "New York"),
                      (1913, "New York Yankees", "Yankees", "Bronx")],
            "retro": [(1901, "BLA"), (1903, "NYA")], "bbref": [(1901, "BLA"), (1903, "NYH"), (1913, "NYY")]},
    "158": {"abbr": [(1969, "SEP"), (1970, "MIL")], "espn": "8", "colour": "#13294b",
            "names": [(1969, "Seattle Pilots", "Pilots", "Seattle"), (1970, "Milwaukee Brewers", "Brewers", "Milwaukee")],
            "retro": [(1969, "SE1"), (1970, "MIL")], "bbref": [(1969, "SEP"), (1970, "MIL")]},
}

# Second kit colour per franchise (the Broadcast hero's colour when the two teams' main colours clash,
# docs/_design/MIGRATION_V4.md). The stores keep no ESPN team objects for MLB (the ESPN fetch reads lines and win
# probability only), so these are the clubs' published secondary colours, like `colour` above: a fixed table.
ALT: dict[str, str] = {
    "108": "#003263", "109": "#e3d4ad", "110": "#000000", "111": "#bd3039", "112": "#cc3433", "113": "#000000",
    "114": "#e50022", "115": "#c4ced4", "116": "#fa4616", "117": "#eb6e1f", "118": "#bd9b60", "119": "#ef3e42",
    "120": "#14225a", "121": "#ff5910", "133": "#efb21e", "134": "#fdb827", "135": "#ffc425", "136": "#0c2c56",
    "137": "#27251f", "138": "#0c2340", "139": "#8fbce6", "140": "#c0111f", "141": "#e8291c", "142": "#d31145",
    "143": "#002d72", "144": "#ce1141", "145": "#c4ced4", "146": "#ef3340", "147": "#c4ced4", "158": "#ffc52f",
}


def team_alt(tid) -> str | None:
    """A franchise's second kit colour ("#rrggbb"), or None (a minor-league or unknown id)."""
    return ALT.get(str(tid))


# league by season: (first season, "AL"|"NL"); division from 1994 (three-division era), by season.
_LEAGUE_MOVES = {"158": [(1969, "AL"), (1998, "NL")], "117": [(1962, "NL"), (2013, "AL")]}
_NL = {"109", "112", "113", "115", "119", "120", "121", "134", "135", "137", "138", "143", "144", "146"}
_DIVISION = {  # since 2013 (HOU to the AL West); 1994-2012 handled in division()
    "108": "AL West", "117": "AL West", "133": "AL West", "136": "AL West", "140": "AL West",
    "110": "AL East", "111": "AL East", "139": "AL East", "141": "AL East", "147": "AL East",
    "114": "AL Central", "116": "AL Central", "118": "AL Central", "142": "AL Central", "145": "AL Central",
    "109": "NL West", "115": "NL West", "119": "NL West", "135": "NL West", "137": "NL West",
    "120": "NL East", "121": "NL East", "143": "NL East", "144": "NL East", "146": "NL East",
    "112": "NL Central", "113": "NL Central", "134": "NL Central", "138": "NL Central", "158": "NL Central",
}


def _at(rows: list[tuple], season: int, idx: int = 1):
    best = None
    for r in rows:
        if r[0] <= season:
            best = r
    best = best or rows[0]
    return best[idx] if idx < len(best) else None


def team_ids() -> list[str]:
    return list(TEAMS)


def team_name(tid: str, season: int) -> str | None:
    t = TEAMS.get(str(tid))
    return _at(t["names"], season, 1) if t else None


def team_short(tid: str, season: int) -> str | None:
    t = TEAMS.get(str(tid))
    return _at(t["names"], season, 2) if t else None


def team_abbr(tid: str, season: int) -> str | None:
    """Stats API / Savant abbreviation in that season (AZ for Arizona; OAK to 2024, ATH from 2025)."""
    t = TEAMS.get(str(tid))
    return _at(t["abbr"], season, 1) if t else None


def team_league(tid: str, season: int) -> str | None:
    tid = str(tid)
    if tid not in TEAMS:
        return None
    if tid in _LEAGUE_MOVES:
        return _at(_LEAGUE_MOVES[tid], season, 1)
    return "NL" if tid in _NL else "AL"


def team_division(tid: str, season: int) -> str | None:
    tid = str(tid)
    if tid not in TEAMS or season < 1994:
        return None
    if season < 2013:
        if tid == "117":
            return "NL Central"
        if tid == "158" and season < 1998:
            return "AL Central"
        if tid == "158":
            return "NL Central"
        if tid == "139" and season < 1998:
            return None
        if tid == "109" and season < 1998:
            return None
        if tid == "120":
            return "NL East"
        if tid == "116" and season < 1998:
            return "AL East"
    return _DIVISION.get(tid)


def team_record(tid: str, season: int) -> dict:
    """The store's team record for an MLB franchise (contract section 1)."""
    t = TEAMS[str(tid)]
    return {"name": team_name(tid, season), "abbr": team_abbr(tid, season), "short": team_short(tid, season),
            "league": team_league(tid, season), "division": team_division(tid, season), "venue": None,
            "colour": t["colour"]}


# source code -> MLBAM id
def _index(field: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tid, t in TEAMS.items():
        for row in t[field]:
            out.setdefault(row[1], tid)
    return out


ABBR_TO_TID = _index("abbr")
ABBR_TO_TID.update({"ARI": "109", "OAK": "133", "WAS": "120", "CHW": "145", "SDP": "135", "SFG": "137", "TBR": "139",
                    "KCR": "118", "FLA": "146", "ANA": "108", "LA": "119", "AZ": "109"})
ESPN_TO_TID = {t["espn"]: tid for tid, t in TEAMS.items()}
RETRO_TO_TID = _index("retro")
BBREF_TO_TID = _index("bbref")


def tid_from_abbr(abbr: str | None) -> str | None:
    return ABBR_TO_TID.get(str(abbr or "").upper()) if abbr else None


def tid_from_espn(espn_id) -> str | None:
    return ESPN_TO_TID.get(str(espn_id)) if espn_id is not None else None


def tid_from_retro(code: str | None) -> str | None:
    """MLBAM franchise id for a Retrosheet team code (None for defunct non-MLBAM clubs, e.g. Federal League)."""
    return RETRO_TO_TID.get(str(code or "").upper()) if code else None


def retro_code(tid: str, season: int) -> str | None:
    t = TEAMS.get(str(tid))
    return _at(t["retro"], season, 1) if t else None


def bbref_code(tid: str, season: int) -> str | None:
    t = TEAMS.get(str(tid))
    return _at(t["bbref"], season, 1) if t else None


def game_status(abstract: str | None, detailed: str | None, coded: str | None = None) -> str:
    """Stats API status -> "pre" | "live" | "final" | "postponed" | "cancelled" | "suspended"."""
    d = str(detailed or "").lower()
    if "postponed" in d:
        return "postponed"
    if "cancel" in d:
        return "cancelled"
    if "suspended" in d:
        return "suspended"
    a = str(abstract or "").lower()
    if a == "final" or d.startswith("final") or d.startswith("game over") or d == "completed early":
        return "final"
    if a == "live":
        return "live"
    return "pre"
