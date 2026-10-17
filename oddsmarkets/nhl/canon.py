"""
Canonical NHL reference data for The Quant Rink (CONTRACT.md section 1).

Seasons are NHL ids (20262027). The data window opens with 2009-10 (api-web play-by-play with coordinates);
shift charts start with 2010-11 (2009-10 answers empty), NHL EDGE with 2021-22.

Teams are the NHL tri-codes as published for that season, with NHL team ids (stats REST /team, verified
1 Oct 2026):

    ATL (11) -> WPG (52)   from 2011-12 (Atlanta Thrashers -> Winnipeg Jets)
    PHX (27) -> ARI (53)   from 2014-15 (Phoenix Coyotes renamed Arizona Coyotes; same franchise)
    ARI (53) -> UTA (59)   from 2024-25 (Utah Hockey Club; the NHL lists it as a new franchise (id 40) that took
                           over the Coyotes' hockey assets; its team id became 68 as the Utah Mammoth in 2025-26)
    VGK (54)               expansion 2017-18
    SEA (55)               expansion 2021-22

Divisions (verified against /v1/standings/<season end> for every season 2009-10 -> 2025-26, and 2026-27 against
/v1/standings/2026-10-02, by
scripts/nhl_fetch.py --check-canon):
    2009-10 .. 2012-13   six divisions: East Atlantic / Northeast / Southeast, West Central / Northwest / Pacific
    2013-14 .. 2019-20   four: East Atlantic / Metropolitan, West Central / Pacific (VGK in the Pacific from 2017-18)
    2020-21              four realigned COVID divisions, no conferences: North, East, Central, West
    2021-22 ->           four: SEA joins the Pacific, ARI moves to the Central (UTA from 2024-25)

Formats: 82 games (48 in the 2012-13 lockout season, 56 in 2020-21, 2019-20 paused at 68-71 games per team
with 82 scheduled, 84 from 2026-27). Points: win 2, overtime / shootout loss 1. Regular-season overtime is five
minutes (4-on-4 to 2014-15, 3-on-3 from 2015-16) then a shootout; playoff overtime is 20-minute 5-on-5 periods.

Playoffs (16 teams, best of seven):
    2009-10 .. 2012-13   8 per conference; division winners seeded 1-3, then by points; re-seeded every round
    2013-14 -> (not 20)  divisional: top 3 of each division + 2 wild cards per conference; fixed bracket; the
                         division winner with the better record meets the lower wild card
    2019-20              return to play: 24 teams; top 4 per conference round robin, 5-12 best-of-5 qualifiers;
                         16 re-seeded by conference
    2020-21              top 4 of each division; two rounds inside the division, then semifinals re-seeded by points

The tiebreaking procedure is encoded as ordered steps (`TIEBREAK_STEPS`, by era), quoted from NHL.com
("Tie-Breaking Procedure", https://www.nhl.com/info/standings-info/tie-breaking-procedure, read 1 Oct 2026);
the eras before 2019-20 follow the NHL's announcement of the regulation-wins change
(https://www.nhl.com/sharks/news/new-tiebreaker-system-for-standings/c-537490) and the record of earlier
procedures (wins before 2010-11; ROW 2010-11 .. 2018-19). `order_tied` applies them.

Arenas: name, city, latitude / longitude (decimal degrees), IANA time zone, first and last season used, and name
aliases (an arena's sponsor names over the window), for travel distances. `arena_for_game` resolves a game's
venue name (neutral sites included), falling back to the home club's arena of that season.
"""
from __future__ import annotations

import math
from datetime import date

# ── seasons and coverage ────────────────────────────────────────────────────

FIRST_SEASON = 20092010
SHIFTS_FROM = 20102011
EDGE_FROM = 20212022
ESPN_ODDS_FROM = 20192020
ESPN_OPEN_CLOSE_FROM = 20222023
MONEYPUCK_FROM = 20072008
GAME_TYPES = {1: "pre", 2: "regular", 3: "playoffs", 4: "allstar"}
KEEP_TYPES = (2, 3)


def season_id(start_year: int) -> int:
    return int(start_year) * 10000 + int(start_year) + 1


def start_year(season: int) -> int:
    s = int(season)
    return s // 10000 if s > 9999 else s


def season_label(season: int) -> str:
    y = start_year(season)
    return f"{y}-{str(y + 1)[-2:]}"


def norm_season(s: int | str) -> int:
    """20262027, 2026 (start year) or "2026-27" -> 20262027."""
    s = str(s).strip()
    if "-" in s:
        return season_id(int(s.split("-")[0]))
    v = int(s)
    return v if v > 9999 else season_id(v)


def seasons_between(a: int, b: int) -> list[int]:
    return [season_id(y) for y in range(start_year(a), start_year(b) + 1)]


def current_season(today: date | None = None) -> int:
    """July-December belongs to the season starting that year; January-June to the one that started the year before."""
    today = today or date.today()
    return season_id(today.year if today.month >= 7 else today.year - 1)


def season_of_game(game_id: int | str) -> int:
    return season_id(int(str(game_id)[:4]))


def game_type(game_id: int | str) -> int:
    return int(str(game_id)[4:6])


# ── formats ─────────────────────────────────────────────────────────────────

def games_per_team(season: int) -> int:
    y = start_year(season)
    if y == 2012:
        return 48
    if y == 2020:
        return 56
    return 84 if y >= 2026 else 82


def formats(season: int) -> dict:
    y = start_year(season)
    n_teams = 30 if y < 2017 else 31 if y < 2021 else 32
    if y <= 2012:
        playoff = {"kind": "conference", "teams": 16, "per_conference": 8, "division_winners_top": 3, "reseed": True}
    elif y == 2019:
        playoff = {"kind": "return_to_play", "teams": 24, "per_conference": 12, "round_robin": 4, "qualifiers": 8,
                   "qualifier_best_of": 5, "reseed": True}
    elif y == 2020:
        playoff = {"kind": "division_2021", "teams": 16, "per_division": 4, "reseed_semis": True}
    else:
        playoff = {"kind": "divisional_wildcard", "teams": 16, "per_division": 3, "wild_cards_per_conference": 2,
                   "reseed": False}
    return {"season": int(season_id(y)), "teams": n_teams, "games": games_per_team(season),
            "paused": y == 2019, "points": {"W": 2, "OTL": 1, "SOL": 1, "L": 0},
            "ot_minutes": 5, "ot_skaters": 4 if y <= 2014 else 3, "shootout": True,
            "playoff_ot": "20-minute 5-on-5 periods", "best_of": 7, "playoff": playoff,
            "conferences": y != 2020, "tiebreak": tiebreak_era(season)}


# ── teams ───────────────────────────────────────────────────────────────────

# abbr -> (name, NHL team id, first season, last season); seasons inclusive by start year.
TEAMS: dict[str, tuple[str, int, int, int]] = {
    "ANA": ("Anaheim Ducks", 24, 2009, 9999), "BOS": ("Boston Bruins", 6, 2009, 9999),
    "BUF": ("Buffalo Sabres", 7, 2009, 9999), "CGY": ("Calgary Flames", 20, 2009, 9999),
    "CAR": ("Carolina Hurricanes", 12, 2009, 9999), "CHI": ("Chicago Blackhawks", 16, 2009, 9999),
    "COL": ("Colorado Avalanche", 21, 2009, 9999), "CBJ": ("Columbus Blue Jackets", 29, 2009, 9999),
    "DAL": ("Dallas Stars", 25, 2009, 9999), "DET": ("Detroit Red Wings", 17, 2009, 9999),
    "EDM": ("Edmonton Oilers", 22, 2009, 9999), "FLA": ("Florida Panthers", 13, 2009, 9999),
    "LAK": ("Los Angeles Kings", 26, 2009, 9999), "MIN": ("Minnesota Wild", 30, 2009, 9999),
    "MTL": ("Montréal Canadiens", 8, 2009, 9999), "NSH": ("Nashville Predators", 18, 2009, 9999),
    "NJD": ("New Jersey Devils", 1, 2009, 9999), "NYI": ("New York Islanders", 2, 2009, 9999),
    "NYR": ("New York Rangers", 3, 2009, 9999), "OTT": ("Ottawa Senators", 9, 2009, 9999),
    "PHI": ("Philadelphia Flyers", 4, 2009, 9999), "PIT": ("Pittsburgh Penguins", 5, 2009, 9999),
    "SJS": ("San Jose Sharks", 28, 2009, 9999), "STL": ("St. Louis Blues", 19, 2009, 9999),
    "TBL": ("Tampa Bay Lightning", 14, 2009, 9999), "TOR": ("Toronto Maple Leafs", 10, 2009, 9999),
    "VAN": ("Vancouver Canucks", 23, 2009, 9999), "WSH": ("Washington Capitals", 15, 2009, 9999),
    "ATL": ("Atlanta Thrashers", 11, 2009, 2010), "WPG": ("Winnipeg Jets", 52, 2011, 9999),
    "PHX": ("Phoenix Coyotes", 27, 2009, 2013), "ARI": ("Arizona Coyotes", 53, 2014, 2023),
    "UTA": ("Utah Hockey Club", 59, 2024, 9999), "VGK": ("Vegas Golden Knights", 54, 2017, 9999),
    "SEA": ("Seattle Kraken", 55, 2021, 9999),
}
UTA_MAMMOTH_FROM = 2025          # Utah Mammoth, team id 68
FRANCHISE = {"ATL": "WPG", "PHX": "UTA", "ARI": "UTA"}   # relocation lineage to today's club (UTA: hockey assets)
OLD_CODES = {"WPG": ["ATL"], "UTA": ["ARI", "PHX"], "ARI": ["PHX"]}

COLOURS = {
    "ANA": ("#F47A38", "#B9975B"), "ARI": ("#8C2633", "#E2D6B5"), "PHX": ("#8C2633", "#E2D6B5"),
    "BOS": ("#FFB81C", "#000000"), "BUF": ("#003087", "#FFB81C"), "CGY": ("#C8102E", "#F1BE48"),
    "CAR": ("#CE1126", "#000000"), "CHI": ("#CF0A2C", "#000000"), "COL": ("#6F263D", "#236192"),
    "CBJ": ("#002654", "#CE1126"), "DAL": ("#006847", "#8F8F8C"), "DET": ("#CE1126", "#FFFFFF"),
    "EDM": ("#041E42", "#FF4C00"), "FLA": ("#041E42", "#C8102E"), "LAK": ("#111111", "#A2AAAD"),
    "MIN": ("#154734", "#A6192E"), "MTL": ("#AF1E2D", "#192168"), "NSH": ("#FFB81C", "#041E42"),
    "NJD": ("#CE1126", "#000000"), "NYI": ("#00539B", "#F47D30"), "NYR": ("#0038A8", "#CE1126"),
    "OTT": ("#C52032", "#C2912C"), "PHI": ("#F74902", "#000000"), "PIT": ("#FCB514", "#000000"),
    "SJS": ("#006D75", "#EA7200"), "SEA": ("#001628", "#99D9D9"), "STL": ("#002F87", "#FCB514"),
    "TBL": ("#002868", "#FFFFFF"), "TOR": ("#00205B", "#FFFFFF"), "UTA": ("#71AFE5", "#090909"),
    "VAN": ("#00205B", "#00843D"), "VGK": ("#B4975A", "#333F42"), "WSH": ("#C8102E", "#041E42"),
    "WPG": ("#041E42", "#004C97"), "ATL": ("#041E42", "#5C88DA"),
}

# Division membership by era (start years inclusive). Team codes are those of the season (resolved by `teams`).
_SIX = {
    ("Eastern", "Atlantic"): ["NJD", "NYI", "NYR", "PHI", "PIT"],
    ("Eastern", "Northeast"): ["BOS", "BUF", "MTL", "OTT", "TOR"],
    ("Eastern", "Southeast"): ["ATL", "CAR", "FLA", "TBL", "WSH"],          # WPG in place of ATL 2011-12, 2012-13
    ("Western", "Central"): ["CHI", "CBJ", "DET", "NSH", "STL"],
    ("Western", "Northwest"): ["CGY", "COL", "EDM", "MIN", "VAN"],
    ("Western", "Pacific"): ["ANA", "DAL", "LAK", "PHX", "SJS"],
}
_FOUR = {
    ("Eastern", "Atlantic"): ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
    ("Eastern", "Metropolitan"): ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
    ("Western", "Central"): ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "WPG"],
    ("Western", "Pacific"): ["ANA", "CGY", "EDM", "LAK", "ARI", "SJS", "VAN"],
}
_COVID = {
    (None, "North"): ["CGY", "EDM", "MTL", "OTT", "TOR", "VAN", "WPG"],
    (None, "East"): ["BOS", "BUF", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
    (None, "Central"): ["CAR", "CHI", "CBJ", "DAL", "DET", "FLA", "NSH", "TBL"],
    (None, "West"): ["ANA", "ARI", "COL", "LAK", "MIN", "SJS", "STL", "VGK"],
}
_NOW = {
    ("Eastern", "Atlantic"): ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
    ("Eastern", "Metropolitan"): ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
    ("Western", "Central"): ["ARI", "CHI", "COL", "DAL", "MIN", "NSH", "STL", "WPG"],
    ("Western", "Pacific"): ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"],
}
# The NHL's own division abbreviations in /v1/standings (used to check the tables above).
NHL_DIV_ABBR = {"Atlantic": ("ATL", "A"), "Northeast": ("NE",), "Southeast": ("SE",), "Central": ("CEN", "C"),
                "Northwest": ("NW",), "Pacific": ("PAC", "P"), "Metropolitan": ("M",), "North": ("NTH",),
                "East": ("EST",), "West": ("WST",)}


def code_in_season(abbr: str, season: int) -> str:
    """A club's code in a season (WPG in 2010-11 is ATL; UTA in 2015-16 is ARI; ARI in 2012-13 is PHX)."""
    y = start_year(season)
    a = str(abbr).upper()
    if a in ("WPG", "ATL"):
        return "ATL" if y <= 2010 else "WPG"
    if a in ("UTA", "ARI", "PHX"):
        return "PHX" if y <= 2013 else "ARI" if y <= 2023 else "UTA"
    return a


def _layout(season: int) -> dict:
    y = start_year(season)
    if y <= 2012:
        return _SIX
    if y == 2020:
        return _COVID
    if y <= 2019:
        return _FOUR
    return _NOW


def teams(season: int) -> dict[str, dict]:
    """abbr -> {name, id, conference, division, colour, alt, franchise} for the clubs of a season."""
    y = start_year(season)
    out: dict[str, dict] = {}
    for (conf, div), members in _layout(season).items():
        for m in members:
            a = code_in_season(m, season)
            if a == "VGK" and y < 2017:
                continue
            name, tid, lo, hi = TEAMS[a]
            if not lo <= y <= hi:
                continue
            if a == "UTA" and y >= UTA_MAMMOTH_FROM:
                name, tid = "Utah Mammoth", 68
            col = COLOURS.get(a, ("#555555", "#999999"))
            out[a] = {"abbr": a, "name": name, "id": tid, "conference": conf, "division": div,
                      "colour": col[0], "alt": col[1], "franchise": FRANCHISE.get(a, a)}
    if 2017 <= y <= 2019 and "VGK" not in out:
        name, tid, _, _ = TEAMS["VGK"]
        out["VGK"] = {"abbr": "VGK", "name": name, "id": tid, "conference": "Western", "division": "Pacific",
                      "colour": COLOURS["VGK"][0], "alt": COLOURS["VGK"][1], "franchise": "VGK"}
    return dict(sorted(out.items()))


def team_ids(season: int) -> dict[int, str]:
    """NHL team id -> abbr for a season (both Utah ids map to UTA)."""
    out = {t["id"]: a for a, t in teams(season).items()}
    if "UTA" in out.values():
        out[59] = out[68] = "UTA"
    return out


ALL_TEAM_IDS = {v[1]: k for k, v in TEAMS.items()} | {68: "UTA"}


def abbr_from_id(team_id: int, season: int | None = None) -> str | None:
    if season is not None:
        a = team_ids(season).get(int(team_id))
        if a:
            return a
    return ALL_TEAM_IDS.get(int(team_id))


def division_of(abbr: str, season: int) -> str | None:
    t = teams(season).get(code_in_season(abbr, season))
    return t["division"] if t else None


def conference_of(abbr: str, season: int) -> str | None:
    t = teams(season).get(code_in_season(abbr, season))
    return t["conference"] if t else None


# ESPN team ids / abbreviations -> NHL codes (ESPN uses LA, NJ, SJ, TB, UTAH; Arizona was id 24, Utah 129764).
ESPN_ABBR = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA", "UTA": "UTA", "WSH": "WSH",
             "PHX": "ARI", "ARI": "ARI", "MON": "MTL", "NAS": "NSH", "WAS": "WSH", "LV": "VGK", "CLB": "CBJ"}
ESPN_ID = {"25": "ANA", "1": "BOS", "2": "BUF", "3": "CGY", "7": "CAR", "4": "CHI", "17": "COL", "29": "CBJ",
           "9": "DAL", "5": "DET", "6": "EDM", "26": "FLA", "8": "LAK", "30": "MIN", "10": "MTL", "27": "NSH",
           "11": "NJD", "12": "NYI", "13": "NYR", "14": "OTT", "15": "PHI", "16": "PIT", "18": "SJS",
           "124292": "SEA", "19": "STL", "20": "TBL", "21": "TOR", "129764": "UTA", "22": "VAN", "37": "VGK",
           "23": "WSH", "28": "WPG", "24": "ARI"}


def abbr_from_espn(espn_id: str | int | None = None, espn_abbr: str | None = None,
                   season: int | None = None) -> str | None:
    a = ESPN_ID.get(str(espn_id)) if espn_id is not None else None
    if a is None and espn_abbr:
        a = ESPN_ABBR.get(str(espn_abbr).upper(), str(espn_abbr).upper())
    if a and season is not None:
        a = code_in_season(a, season)
    return a


# ── arenas ──────────────────────────────────────────────────────────────────

# key -> (name, city, lat, lon, tz, home club (franchise code) or None, first, last (start years), aliases)
ARENAS: dict[str, tuple] = {
    "honda": ("Honda Center", "Anaheim", 33.8078, -117.8765, "America/Los_Angeles", "ANA", 2009, 9999, ("Honda Center",)),
    "glendale": ("Gila River Arena", "Glendale", 33.5319, -112.2611, "America/Phoenix", "ARI", 2009, 2021,
                 ("Jobing.com Arena", "Gila River Arena", "Desert Diamond Arena")),
    "mullett": ("Mullett Arena", "Tempe", 33.4246, -111.9322, "America/Phoenix", "ARI", 2022, 2023, ("Mullett Arena",)),
    "philips": ("Philips Arena", "Atlanta", 33.7573, -84.3963, "America/New_York", "ATL", 2009, 2010,
                ("Philips Arena", "State Farm Arena")),
    "tdgarden": ("TD Garden", "Boston", 42.3662, -71.0621, "America/New_York", "BOS", 2009, 9999, ("TD Garden",)),
    "keybank": ("KeyBank Center", "Buffalo", 42.8750, -78.8764, "America/New_York", "BUF", 2009, 9999,
                ("HSBC Arena", "First Niagara Center", "KeyBank Center")),
    "saddledome": ("Scotiabank Saddledome", "Calgary", 51.0374, -114.0519, "America/Edmonton", "CGY", 2009, 9999,
                   ("Pengrowth Saddledome", "Scotiabank Saddledome", "Saddledome")),
    "raleigh": ("Lenovo Center", "Raleigh", 35.8033, -78.7219, "America/New_York", "CAR", 2009, 9999,
                ("RBC Center", "PNC Arena", "Lenovo Center")),
    "united": ("United Center", "Chicago", 41.8807, -87.6742, "America/Chicago", "CHI", 2009, 9999, ("United Center",)),
    "denver": ("Ball Arena", "Denver", 39.7487, -105.0077, "America/Denver", "COL", 2009, 9999, ("Pepsi Center", "Ball Arena")),
    "nationwide": ("Nationwide Arena", "Columbus", 39.9693, -83.0061, "America/New_York", "CBJ", 2009, 9999, ("Nationwide Arena",)),
    "aac": ("American Airlines Center", "Dallas", 32.7905, -96.8103, "America/Chicago", "DAL", 2009, 9999,
            ("American Airlines Center",)),
    "joelouis": ("Joe Louis Arena", "Detroit", 42.3254, -83.0516, "America/Detroit", "DET", 2009, 2016, ("Joe Louis Arena",)),
    "lca": ("Little Caesars Arena", "Detroit", 42.3411, -83.0553, "America/Detroit", "DET", 2017, 9999, ("Little Caesars Arena",)),
    "rexall": ("Rexall Place", "Edmonton", 53.5714, -113.4561, "America/Edmonton", "EDM", 2009, 2015, ("Rexall Place",)),
    "rogersplace": ("Rogers Place", "Edmonton", 53.5469, -113.4979, "America/Edmonton", "EDM", 2016, 9999, ("Rogers Place",)),
    "sunrise": ("Amerant Bank Arena", "Sunrise", 26.1584, -80.3256, "America/New_York", "FLA", 2009, 9999,
                ("BankAtlantic Center", "BB&T Center", "FLA Live Arena", "Amerant Bank Arena")),
    "cryptocom": ("Crypto.com Arena", "Los Angeles", 34.0430, -118.2673, "America/Los_Angeles", "LAK", 2009, 9999,
                  ("Staples Center", "STAPLES Center", "Crypto.com Arena")),
    "xcel": ("Grand Casino Arena", "Saint Paul", 44.9448, -93.1010, "America/Chicago", "MIN", 2009, 9999,
             ("Xcel Energy Center", "Grand Casino Arena")),
    "bell": ("Bell Centre", "Montréal", 45.4961, -73.5693, "America/Toronto", "MTL", 2009, 9999, ("Bell Centre", "Centre Bell")),
    "bridgestone": ("Bridgestone Arena", "Nashville", 36.1592, -86.7785, "America/Chicago", "NSH", 2009, 9999,
                    ("Sommet Center", "Bridgestone Arena")),
    "prudential": ("Prudential Center", "Newark", 40.7334, -74.1711, "America/New_York", "NJD", 2009, 9999, ("Prudential Center",)),
    "coliseum": ("Nassau Coliseum", "Uniondale", 40.7229, -73.5904, "America/New_York", "NYI", 2009, 2020,
                 ("Nassau Veterans Memorial Coliseum", "Nassau Coliseum", "NYCB Live", "Nassau Veterans")),
    "barclays": ("Barclays Center", "Brooklyn", 40.6826, -73.9754, "America/New_York", "NYI", 2015, 2019, ("Barclays Center",)),
    "ubs": ("UBS Arena", "Elmont", 40.7117, -73.7255, "America/New_York", "NYI", 2021, 9999, ("UBS Arena",)),
    "msg": ("Madison Square Garden", "New York", 40.7505, -73.9934, "America/New_York", "NYR", 2009, 9999, ("Madison Square Garden",)),
    "ctc": ("Canadian Tire Centre", "Ottawa", 45.2969, -75.9271, "America/Toronto", "OTT", 2009, 9999,
            ("Scotiabank Place", "Canadian Tire Centre")),
    "wellsfargo": ("Xfinity Mobile Arena", "Philadelphia", 39.9012, -75.1720, "America/New_York", "PHI", 2009, 9999,
                   ("Wachovia Center", "Wells Fargo Center", "Xfinity Mobile Arena")),
    "mellon": ("Mellon Arena", "Pittsburgh", 40.4414, -79.9890, "America/New_York", "PIT", 2009, 2009, ("Mellon Arena",)),
    "ppg": ("PPG Paints Arena", "Pittsburgh", 40.4394, -79.9892, "America/New_York", "PIT", 2010, 9999,
            ("CONSOL Energy Center", "Consol Energy Center", "PPG Paints Arena")),
    "sap": ("SAP Center", "San Jose", 37.3328, -121.9012, "America/Los_Angeles", "SJS", 2009, 9999,
            ("HP Pavilion", "SAP Center")),
    "climate": ("Climate Pledge Arena", "Seattle", 47.6221, -122.3540, "America/Los_Angeles", "SEA", 2021, 9999,
                ("Climate Pledge Arena",)),
    "enterprise": ("Enterprise Center", "St. Louis", 38.6268, -90.2026, "America/Chicago", "STL", 2009, 9999,
                   ("Scottrade Center", "Enterprise Center")),
    "amalie": ("Benchmark International Arena", "Tampa", 27.9427, -82.4518, "America/New_York", "TBL", 2009, 9999,
               ("St. Pete Times Forum", "Tampa Bay Times Forum", "Amalie Arena", "Benchmark International Arena")),
    "scotiabank": ("Scotiabank Arena", "Toronto", 43.6435, -79.3791, "America/Toronto", "TOR", 2009, 9999,
                   ("Air Canada Centre", "Scotiabank Arena")),
    "delta": ("Delta Center", "Salt Lake City", 40.7683, -111.9011, "America/Denver", "UTA", 2024, 9999, ("Delta Center",)),
    "rogers": ("Rogers Arena", "Vancouver", 49.2778, -123.1088, "America/Vancouver", "VAN", 2009, 9999,
               ("General Motors Place", "GM Place", "Rogers Arena")),
    "tmobile": ("T-Mobile Arena", "Paradise", 36.1029, -115.1785, "America/Los_Angeles", "VGK", 2017, 9999, ("T-Mobile Arena",)),
    "capitalone": ("Capital One Arena", "Washington", 38.8981, -77.0209, "America/New_York", "WSH", 2009, 9999,
                   ("Verizon Center", "Capital One Arena")),
    "winnipeg": ("Canada Life Centre", "Winnipeg", 49.8928, -97.1436, "America/Winnipeg", "WPG", 2011, 9999,
                 ("MTS Centre", "Bell MTS Place", "Canada Life Centre")),
    # neutral sites: Global Series / Premiere games, outdoor games and other one-offs
    "stockholm": ("Avicii Arena", "Stockholm", 59.2936, 18.0833, "Europe/Stockholm", None, 2009, 9999,
                  ("Ericsson Globe", "Globe Arena", "Avicii Arena")),
    "helsinki": ("Hartwall Arena", "Helsinki", 60.2052, 24.9290, "Europe/Helsinki", None, 2009, 9999,
                 ("Hartwall Arena", "Hartwall Areena", "Helsinki Halli")),
    "tampere": ("Nokia Arena", "Tampere", 61.4940, 23.7741, "Europe/Helsinki", None, 2022, 9999, ("Nokia Arena",)),
    "prague": ("O2 Arena", "Prague", 50.1047, 14.4936, "Europe/Prague", None, 2009, 9999, ("O2 Arena", "O2 arena")),
    "berlin": ("Uber Arena", "Berlin", 52.5053, 13.4436, "Europe/Berlin", None, 2009, 9999,
               ("O2 World", "Mercedes-Benz Arena", "Uber Arena")),
    "gothenburg": ("Scandinavium", "Gothenburg", 57.7003, 11.9878, "Europe/Stockholm", None, 2009, 9999, ("Scandinavium",)),
    "bern": ("PostFinance Arena", "Bern", 46.9583, 7.4683, "Europe/Zurich", None, 2009, 9999, ("PostFinance Arena",)),
    "cologne": ("Lanxess Arena", "Cologne", 50.9384, 6.9830, "Europe/Berlin", None, 2009, 9999, ("Lanxess Arena", "LANXESS arena")),
    "zurich": ("Swiss Life Arena", "Zürich", 47.4126, 8.4993, "Europe/Zurich", None, 2009, 9999, ("Swiss Life Arena", "Hallenstadion")),
    "mannheim": ("SAP Arena", "Mannheim", 49.4637, 8.5176, "Europe/Berlin", None, 2009, 9999, ("SAP Arena",)),
    "bratislava": ("Slovnaft Arena", "Bratislava", 48.1590, 17.1052, "Europe/Bratislava", None, 2009, 9999, ("Slovnaft Arena",)),
    "riga": ("Arena Riga", "Riga", 56.9673, 24.1210, "Europe/Riga", None, 2009, 9999, ("Arena Riga",)),
    "london": ("The O2", "London", 51.5030, 0.0032, "Europe/London", None, 2009, 9999, ("The O2",)),
    "malmo": ("Malmö Arena", "Malmö", 55.5654, 12.9763, "Europe/Stockholm", None, 2009, 9999, ("Malmö Arena", "Malmo Arena")),
    "quebec": ("Videotron Centre", "Québec City", 46.8317, -71.2492, "America/Toronto", None, 2009, 9999,
               ("Videotron Centre", "Centre Vidéotron")),
    "ottawa_outdoor": ("Lansdowne Park", "Ottawa", 45.3983, -75.6838, "America/Toronto", None, 2017, 2017,
                       ("Lansdowne Park", "TD Place Stadium")),
}
# Outdoor games and other stadiums (one-offs): matched by name only, never a home fallback.
STADIUMS: dict[str, tuple] = {
    "Fenway Park": ("Boston", 42.3467, -71.0972), "Heinz Field": ("Pittsburgh", 40.4468, -80.0158),
    "Acrisure Stadium": ("Pittsburgh", 40.4468, -80.0158), "Citizens Bank Park": ("Philadelphia", 39.9061, -75.1665),
    "Michigan Stadium": ("Ann Arbor", 42.2658, -83.7487), "Dodger Stadium": ("Los Angeles", 34.0739, -118.2400),
    "Yankee Stadium": ("New York", 40.8296, -73.9262), "Soldier Field": ("Chicago", 41.8623, -87.6167),
    "BC Place": ("Vancouver", 49.2768, -123.1120), "Nationals Park": ("Washington", 38.8730, -77.0074),
    "TCF Bank Stadium": ("Minneapolis", 44.9765, -93.2246), "Gillette Stadium": ("Foxborough", 42.0909, -71.2643),
    "Coors Field": ("Denver", 39.7559, -104.9942), "Busch Stadium": ("St. Louis", 38.6226, -90.1928),
    "Lincoln Financial Field": ("Philadelphia", 39.9008, -75.1675), "Notre Dame Stadium": ("Notre Dame", 41.6984, -86.2339),
    "Cotton Bowl": ("Dallas", 32.7797, -96.7593), "Mosaic Stadium": ("Regina", 50.4535, -104.6460),
    "Lambeau Field": ("Green Bay", 44.5013, -88.0622), "Commonwealth Stadium": ("Edmonton", 53.5595, -113.4766),
    "Investors Group Field": ("Winnipeg", 49.8078, -97.1430), "IG Field": ("Winnipeg", 49.8078, -97.1430),
    "McMahon Stadium": ("Calgary", 51.0703, -114.1215), "Target Field": ("Minneapolis", 44.9817, -93.2776),
    "T-Mobile Park": ("Seattle", 47.5914, -122.3325), "Wrigley Field": ("Chicago", 41.9484, -87.6553),
    "MetLife Stadium": ("East Rutherford", 40.8135, -74.0745), "Ohio Stadium": ("Columbus", 40.0017, -83.0197),
    "Tim Hortons Field": ("Hamilton", 43.2522, -79.8301), "Lake Tahoe": ("Stateline", 38.9637, -119.9400),
    "Edgewood Tahoe": ("Stateline", 38.9637, -119.9400), "Raymond James Stadium": ("Tampa", 27.9759, -82.5033),
    "Bank of America Stadium": ("Charlotte", 35.2258, -80.8528), "Ross-Ade Stadium": ("West Lafayette", 40.4344, -86.9183),
}


def _norm(s: str | None) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _arena_rec(key: str, season: int | None = None) -> dict:
    name, city, lat, lon, tz, club, lo, hi, aliases = ARENAS[key]
    return {"key": key, "name": name, "city": city, "lat": lat, "lon": lon, "tz": tz, "club": club}


def home_arena(abbr: str, season: int) -> dict | None:
    """The club's main arena in a season (the Islanders' 2018-19 / 2019-20 split home is Barclays)."""
    y = start_year(season)
    fr = {"PHX": "ARI", "ATL": "ATL"}.get(code_in_season(abbr, season), code_in_season(abbr, season))
    best = None
    for key, rec in ARENAS.items():
        if rec[5] == fr and rec[6] <= y <= rec[7]:
            if fr == "NYI" and 2015 <= y <= 2019 and key != "barclays":
                continue
            best = key
            break
    return _arena_rec(best) if best else None


def arena_for_game(venue: str | None, home: str | None = None, season: int | None = None) -> dict | None:
    """Arena (or outdoor stadium) of a game by venue name, else the home club's arena that season."""
    v = _norm(venue)
    if v:
        for key, rec in ARENAS.items():
            if any(_norm(a) and (_norm(a) in v or v in _norm(a)) for a in rec[8]):
                return _arena_rec(key)
        for name, (city, lat, lon) in STADIUMS.items():
            if _norm(name) in v:
                return {"key": _norm(name), "name": name, "city": city, "lat": lat, "lon": lon, "tz": None, "club": None,
                        "outdoor": True}
    if home and season:
        return home_arena(home, season)
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ── situation codes ─────────────────────────────────────────────────────────

def decode_situation(code: str | int | None) -> dict | None:
    """NHL situationCode (4 digits: away goalie in net, away skaters, home skaters, home goalie in net).
    "1551" = 5v5 with both goalies; "0651" = away net empty with 6 skaters; "1451" = home power play."""
    if code is None:
        return None
    s = str(code).strip()
    if len(s) == 3:
        s = "0" + s
    if len(s) != 4 or not s.isdigit():
        return None
    ag, ask, hsk, hg = (int(ch) for ch in s)
    return {"away_goalie": ag, "away_skaters": ask, "home_skaters": hsk, "home_goalie": hg}


def strength_label(team_skaters: int, opp_skaters: int) -> str:
    return f"{team_skaters}v{opp_skaters}"


def strength_state(team_skaters: int, opp_skaters: int, team_goalie: int = 1, opp_goalie: int = 1) -> str:
    """EV / PP / SH from the team's view, with EN (opponent's net empty) and PS (penalty shot / shootout 1v0)."""
    if (team_skaters, opp_skaters) in ((1, 0), (0, 1)):
        return "PS"
    if not opp_goalie:
        return "EN"
    ts, os_ = team_skaters - (0 if team_goalie else 1), opp_skaters - (0 if opp_goalie else 1)
    if ts > os_:
        return "PP"
    if ts < os_:
        return "SH"
    return "EV"


# ── tiebreaking ─────────────────────────────────────────────────────────────

TIEBREAK_SOURCE = ("NHL.com, 'Tie-Breaking Procedure' (https://www.nhl.com/info/standings-info/tie-breaking-procedure), "
                   "read 1 Oct 2026; earlier eras: NHL.com 'New Tiebreaker System for Standings' (2019) and the "
                   "procedures in force 2005-06 .. 2018-19 (wins, then ROW from 2010-11)")
TIEBREAK_INTRO = ("If two or more clubs are tied in points during the regular season, the standing of the clubs is "
                  "determined in the following order:")
# Each step: (key, quoted text). Keys are interpreted by `order_tied`.
_STEP_TEXT = {
    "gp": "The fewer number of games played (i.e., superior points percentage).",
    "rw": "The greater number of games won, excluding games won in Overtime or by Shootout (i.e., 'Regulation Wins'). "
          "This figure is reflected in the RW column.",
    "row": "The greater number of games won, excluding games won by Shootout. This figure is reflected in the ROW column.",
    "w": "The greater number of games won by the Club in any manner (i.e., 'Total Wins'). This figure is reflected in "
         "the W column.",
    "h2h": "The greater number of points earned in games against each other among two or more tied clubs. For the "
           "purpose of determining standing for two or more Clubs that have not played an even number of games with "
           "one or more of the other tied Clubs, the first game played in the city that has the extra game (the 'odd "
           "game') shall not be included. When more than two Clubs are tied, the percentage of available points earned "
           "in games among each other (and not including any 'odd games') shall be used to determine standing.",
    "diff": "The greater differential between goals for and against (including goals scored in Overtime or awarded for "
            "prevailing in Shootouts) for the entire regular season. This figure is reflected in the DIFF column.",
    "gf": "The greater number of goals scored (including goals scored in Overtime or awarded for prevailing in "
          "Shootouts) for the entire regular season. This figure is reflected in the GF column.",
}
TIEBREAK_STEPS = {
    "2019-": ["gp", "rw", "row", "w", "h2h", "diff", "gf"],     # current published procedure
    "2010-2018": ["gp", "row", "h2h", "diff"],                  # ROW first (2010-11 .. 2018-19)
    "-2009": ["gp", "w", "h2h", "diff"],                         # wins first (2005-06 .. 2009-10)
}
TIEBREAK_NOTES = [
    "A shootout win counts as one goal for (and the loss one against) in GF / GA / DIFF; NHL final scores of a "
    "shootout game already include that goal.",
    "Steps run in order on the tied group; a step that separates the clubs splits the group, and each still-tied "
    "subgroup carries on from the next step (the published procedure has no restart clause). The head-to-head step "
    "is computed among the clubs still tied at that point (two clubs: points; more: percentage of available points).",
    "The same procedure orders clubs within a division, a conference, the wild-card race and the league.",
    "If every step leaves clubs tied (e.g. a preseason or all-level table), the NHL breaks the tie by random draw; "
    "here the remaining clubs are ordered by abbreviation (deterministic) and the trace records 'unresolved'.",
]


def tiebreak_era(season: int) -> str:
    y = start_year(season)
    return "2019-" if y >= 2019 else "2010-2018" if y >= 2010 else "-2009"


def tiebreak_steps(season: int) -> list[tuple[str, str]]:
    return [(k, _STEP_TEXT[k]) for k in TIEBREAK_STEPS[tiebreak_era(season)]]


def game_points(g: dict) -> tuple[int, int]:
    """(home points, away points) of a final regular-season game: W 2, OT/SO loss 1."""
    hs, as_ = int(g["hs"]), int(g["as"])
    extra = bool(g.get("ot") or g.get("so"))
    if hs > as_:
        return 2, (1 if extra else 0)
    if as_ > hs:
        return (1 if extra else 0), 2
    return 1, 1          # tie (not possible from 2005-06; kept for safety)


def records_from_games(games: list[dict]) -> dict[str, dict]:
    """Standings records from final regular-season games: gp, w, l, otl, pts, rw, row, gf, ga."""
    rec: dict[str, dict] = {}
    for g in games:
        if g.get("status", "final") != "final" or int(g.get("type", 2)) != 2:
            continue
        hp, ap = game_points(g)
        for side, opp, pts, gf, ga in (("home", "away", hp, g["hs"], g["as"]), ("away", "home", ap, g["as"], g["hs"])):
            t = rec.setdefault(g[side], {"gp": 0, "w": 0, "l": 0, "otl": 0, "pts": 0, "rw": 0, "row": 0, "gf": 0, "ga": 0})
            t["gp"] += 1
            t["pts"] += pts
            t["gf"] += int(gf)
            t["ga"] += int(ga)
            if pts == 2:
                t["w"] += 1
                if not g.get("so"):
                    t["row"] += 1
                if not g.get("ot") and not g.get("so"):
                    t["rw"] += 1
            elif pts == 1:
                t["otl"] += 1
            else:
                t["l"] += 1
    return rec


def head_to_head(group: list[str], games: list[dict]) -> dict[str, tuple[int, int]]:
    """(points, available points) per club in games among `group`, the 'odd games' left out: for each pair that
    has not played an even number of games, the first game in the city that has the extra game is excluded."""
    gs = set(group)
    among = [g for g in games if g.get("home") in gs and g.get("away") in gs and g.get("status", "final") == "final"
             and int(g.get("type", 2)) == 2]
    among.sort(key=lambda g: (g.get("start") or g.get("date") or "", str(g.get("game_id", ""))))
    drop: set[int] = set()
    pairs: dict[frozenset, list[int]] = {}
    for i, g in enumerate(among):
        pairs.setdefault(frozenset((g["home"], g["away"])), []).append(i)
    for pair, idx in pairs.items():
        a, b = sorted(pair)
        at_a = [i for i in idx if among[i]["home"] == a]
        at_b = [i for i in idx if among[i]["home"] == b]
        if len(at_a) > len(at_b):
            drop.add(at_a[0])
        elif len(at_b) > len(at_a):
            drop.add(at_b[0])
    out = {t: [0, 0] for t in group}
    for i, g in enumerate(among):
        if i in drop:
            continue
        hp, ap = game_points(g)
        out[g["home"]][0] += hp
        out[g["away"]][0] += ap
        out[g["home"]][1] += 2
        out[g["away"]][1] += 2
    return {t: (v[0], v[1]) for t, v in out.items()}


def _step_value(step: str, team: str, rec: dict, h2h: dict | None, n_group: int):
    r = rec[team]
    if step == "gp":
        return -r["gp"]
    if step in ("rw", "row", "w"):
        return r[step]
    if step == "diff":
        return r["gf"] - r["ga"]
    if step == "gf":
        return r["gf"]
    if step == "h2h":
        pts, avail = h2h[team]
        if n_group == 2:
            return pts
        return pts / avail if avail else 0.0
    raise KeyError(step)


def order_tied(group: list[str], records: dict[str, dict], games: list[dict], season: int,
               steps: list[str] | None = None, trace: list | None = None) -> list[str]:
    """Order clubs tied on points by the NHL procedure of the season. `records` per club: gp, rw, row, w, gf, ga
    (and pts); `games`: final regular-season GAME records (home, away, hs, as, ot, so, start). `trace` (a list)
    collects (step, {club: value}) for every step applied."""
    steps = list(steps if steps is not None else TIEBREAK_STEPS[tiebreak_era(season)])
    group = sorted(group)
    if len(group) <= 1:
        return group
    if not steps:                       # every step exhausted: the NHL draws lots; we use abbreviation order
        if trace is not None:
            trace.append(("unresolved", {t: None for t in group}))
        return group
    step, rest = steps[0], steps[1:]
    h2h = head_to_head(group, games) if step == "h2h" else None
    vals = {t: _step_value(step, t, records, h2h, len(group)) for t in group}
    if trace is not None:
        trace.append((step, dict(vals)))
    out: list[str] = []
    for v in sorted(set(vals.values()), reverse=True):
        sub = [t for t in group if vals[t] == v]
        out.extend(order_tied(sub, records, games, season, rest, trace) if len(sub) > 1 else sub)
    return out


def rank(clubs: list[str], records: dict[str, dict], games: list[dict], season: int) -> list[str]:
    """Clubs ordered by points, ties broken by `order_tied` (in-season, step 1 'fewer games played' applies)."""
    out: list[str] = []
    by_pts: dict[int, list[str]] = {}
    for t in clubs:
        by_pts.setdefault(records[t]["pts"], []).append(t)
    for p in sorted(by_pts, reverse=True):
        out.extend(order_tied(by_pts[p], records, games, season))
    return out


def playoff_seeds(season: int, records: dict[str, dict], games: list[dict]) -> dict:
    """The playoff field of a season from records and games, for the two standard 16-team formats:
    divisional + wild card (2013-14 ->, not 2019-20 / 2020-21) -> {conf: {"divisions": {div: [3 clubs]},
    "wild_cards": [2 clubs]}}; conference (2009-10 .. 2012-13) -> {conf: [8 clubs in seed order]}."""
    ts = teams(season)
    kind = formats(season)["playoff"]["kind"]
    confs = sorted({t["conference"] for t in ts.values() if t["conference"]})
    out: dict = {}
    for conf in confs:
        members = [a for a, t in ts.items() if t["conference"] == conf and a in records]
        divs = sorted({ts[a]["division"] for a in members})
        div_order = {d: rank([a for a in members if ts[a]["division"] == d], records, games, season) for d in divs}
        if kind == "divisional_wildcard":
            tops = {d: o[:3] for d, o in div_order.items()}
            taken = {a for o in tops.values() for a in o}
            wc = rank([a for a in members if a not in taken], records, games, season)[:2]
            out[conf] = {"divisions": tops, "wild_cards": wc}
        elif kind == "conference":
            winners = rank([o[0] for o in div_order.values()], records, games, season)
            others = rank([a for a in members if a not in winners], records, games, season)
            out[conf] = (winners + others)[:8]
        else:
            out[conf] = rank(members, records, games, season)
    return out
