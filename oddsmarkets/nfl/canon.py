"""
Canonical NFL reference data for The Quant Gridiron (CONTRACT.md section 1).

Teams are nflverse abbreviations as published for that season (the Rams are "LA", Washington "WAS"),
with the three relocations of the data window mapped to a franchise:

    STL -> LA   from 2016 (St. Louis Rams -> Los Angeles Rams)
    SD  -> LAC  from 2017 (San Diego Chargers -> Los Angeles Chargers)
    OAK -> LV   from 2020 (Oakland Raiders -> Las Vegas Raiders)

ESPN uses its own abbreviations (LAR, WSH) and numeric team ids; `abbr_from_espn` maps both.

Divisions: the 1999-2001 six-division alignment (31 teams; Houston joined in 2002) and the eight-division
alignment from 2002. Formats by season: 16 games and 17 weeks to 2020, 17 games and 18 weeks from 2021;
6 playoff clubs a conference to 2019 (two byes), 7 from 2020 (one bye). nflverse numbers playoff weeks on
from the regular season (WC = last regular week + 1, ... SB = + 4), verified against games.parquet.

Stadiums: nflverse `stadium_id` -> name, city, country, lat/lon (decimal degrees), altitude (metres above
sea level), roof type (outdoors / dome / retractable) and IANA time zone. Hand-entered, then checked
against the schedules (every id used 1999-2026 is present; every regular home ground lies within 80 km of
its club's city; roof types agree with nflverse's per-game roof). Surface is per game, from the schedules.

The tiebreaking procedure is encoded as ordered steps (`DIVISION_TWO`, `DIVISION_THREE`, `WILDCARD_TWO`,
`WILDCARD_THREE`, `TIEBREAK_NOTES`), quoted from the NFL's published procedure; `oddsmarkets.nfl.tiebreak`
applies them.
"""
from __future__ import annotations

import math
from datetime import date

# ── seasons and coverage ────────────────────────────────────────────────────

FIRST_SEASON = 1999
NGS_FROM = 2016
FTN_FROM = 2022
PARTICIPATION = (2016, 2025)        # published after each season, never in-season
ESPN_ODDS_FROM = 2017
MONEYLINE_FROM = 2006               # nflverse schedules carry moneylines from 2006 (spread and total from 1999)
GTYPES = ("REG", "WC", "DIV", "CON", "SB")
POST_GTYPES = ("WC", "DIV", "CON", "SB")


def current_season(today: date | None = None) -> int:
    """The season a date belongs to: September-February is one season; March-August looks ahead."""
    today = today or date.today()
    return today.year if today.month >= 3 else today.year - 1


def season_window(season: int) -> tuple[date, date]:
    return date(int(season), 8, 1), date(int(season) + 1, 2, 28)


# ── formats ─────────────────────────────────────────────────────────────────

def formats(season: int) -> dict:
    """Schedule and playoff format of a season."""
    s = int(season)
    reg_weeks = 18 if s >= 2021 else 17
    if s <= 2001:
        n_teams, div_per_conf, wc, byes = 31, 3, 3, 2
    elif s <= 2019:
        n_teams, div_per_conf, wc, byes = 32, 4, 2, 2
    else:
        n_teams, div_per_conf, wc, byes = 32, 4, 3, 1
    per_conf = div_per_conf + wc
    return {"season": s, "teams": n_teams, "games": 17 if s >= 2021 else 16, "reg_weeks": reg_weeks,
            "byes_per_team": 1, "divisions_per_conf": div_per_conf, "wild_cards_per_conf": wc,
            "playoff_teams_per_conf": per_conf, "playoff_teams": 2 * per_conf, "byes_per_conf": byes,
            "reseed": True,
            "post_weeks": {"WC": reg_weeks + 1, "DIV": reg_weeks + 2, "CON": reg_weeks + 3, "SB": reg_weeks + 4}}


def gtype_of_week(season: int, week: int) -> str:
    pw = {v: k for k, v in formats(season)["post_weeks"].items()}
    return pw.get(int(week), "REG")


# ── teams ───────────────────────────────────────────────────────────────────

# franchise (current abbreviation) -> list of (first season, abbreviation, full name), oldest first
FRANCHISES: dict[str, list[tuple[int, str, str]]] = {
    "ARI": [(1994, "ARI", "Arizona Cardinals")],
    "ATL": [(1966, "ATL", "Atlanta Falcons")],
    "BAL": [(1996, "BAL", "Baltimore Ravens")],
    "BUF": [(1960, "BUF", "Buffalo Bills")],
    "CAR": [(1995, "CAR", "Carolina Panthers")],
    "CHI": [(1922, "CHI", "Chicago Bears")],
    "CIN": [(1968, "CIN", "Cincinnati Bengals")],
    "CLE": [(1999, "CLE", "Cleveland Browns")],
    "DAL": [(1960, "DAL", "Dallas Cowboys")],
    "DEN": [(1960, "DEN", "Denver Broncos")],
    "DET": [(1934, "DET", "Detroit Lions")],
    "GB": [(1921, "GB", "Green Bay Packers")],
    "HOU": [(2002, "HOU", "Houston Texans")],
    "IND": [(1984, "IND", "Indianapolis Colts")],
    "JAX": [(1995, "JAX", "Jacksonville Jaguars")],
    "KC": [(1963, "KC", "Kansas City Chiefs")],
    "LA": [(1995, "STL", "St. Louis Rams"), (2016, "LA", "Los Angeles Rams")],
    "LAC": [(1961, "SD", "San Diego Chargers"), (2017, "LAC", "Los Angeles Chargers")],
    "LV": [(1995, "OAK", "Oakland Raiders"), (2020, "LV", "Las Vegas Raiders")],
    "MIA": [(1966, "MIA", "Miami Dolphins")],
    "MIN": [(1961, "MIN", "Minnesota Vikings")],
    "NE": [(1971, "NE", "New England Patriots")],
    "NO": [(1967, "NO", "New Orleans Saints")],
    "NYG": [(1925, "NYG", "New York Giants")],
    "NYJ": [(1963, "NYJ", "New York Jets")],
    "PHI": [(1933, "PHI", "Philadelphia Eagles")],
    "PIT": [(1933, "PIT", "Pittsburgh Steelers")],
    "SEA": [(1976, "SEA", "Seattle Seahawks")],
    "SF": [(1946, "SF", "San Francisco 49ers")],
    "TB": [(1976, "TB", "Tampa Bay Buccaneers")],
    "TEN": [(1999, "TEN", "Tennessee Titans")],
    "WAS": [(1937, "WAS", "Washington Redskins"), (2020, "WAS", "Washington Football Team"),
            (2022, "WAS", "Washington Commanders")],
}

RELOCATIONS = {"STL": ("LA", 2016), "SD": ("LAC", 2017), "OAK": ("LV", 2020)}   # old abbr -> (new abbr, first season)

# Home city reference points (lat, lon) per abbreviation, used to check stadium coordinates and for travel.
CITY: dict[str, tuple[str, float, float]] = {
    "ARI": ("Glendale, AZ", 33.53, -112.26), "ATL": ("Atlanta, GA", 33.75, -84.39), "BAL": ("Baltimore, MD", 39.29, -76.61),
    "BUF": ("Orchard Park, NY", 42.77, -78.79), "CAR": ("Charlotte, NC", 35.23, -80.84), "CHI": ("Chicago, IL", 41.88, -87.63),
    "CIN": ("Cincinnati, OH", 39.10, -84.51), "CLE": ("Cleveland, OH", 41.50, -81.69), "DAL": ("Arlington, TX", 32.74, -97.11),
    "DEN": ("Denver, CO", 39.74, -104.99), "DET": ("Detroit, MI", 42.33, -83.05), "GB": ("Green Bay, WI", 44.51, -88.02),
    "HOU": ("Houston, TX", 29.76, -95.37), "IND": ("Indianapolis, IN", 39.77, -86.16), "JAX": ("Jacksonville, FL", 30.33, -81.66),
    "KC": ("Kansas City, MO", 39.10, -94.58), "LA": ("Inglewood, CA", 33.96, -118.35), "STL": ("St. Louis, MO", 38.63, -90.20),
    "LAC": ("Inglewood, CA", 33.96, -118.35), "SD": ("San Diego, CA", 32.72, -117.16), "LV": ("Las Vegas, NV", 36.17, -115.14),
    "OAK": ("Oakland, CA", 37.80, -122.27), "MIA": ("Miami Gardens, FL", 25.96, -80.24), "MIN": ("Minneapolis, MN", 44.98, -93.27),
    "NE": ("Foxborough, MA", 42.07, -71.25), "NO": ("New Orleans, LA", 29.95, -90.07), "NYG": ("East Rutherford, NJ", 40.81, -74.07),
    "NYJ": ("East Rutherford, NJ", 40.81, -74.07), "PHI": ("Philadelphia, PA", 39.95, -75.17), "PIT": ("Pittsburgh, PA", 40.44, -80.00),
    "SEA": ("Seattle, WA", 47.61, -122.33), "SF": ("San Francisco Bay Area, CA", 37.56, -122.18), "TB": ("Tampa, FL", 27.95, -82.46),
    "TEN": ("Nashville, TN", 36.16, -86.78), "WAS": ("Landover, MD", 38.91, -76.86),
}

# ESPN team id -> franchise (verified on the 2026 week-4 scoreboard: all 32 ids)
ESPN_TEAM_ID = {"22": "ARI", "1": "ATL", "33": "BAL", "2": "BUF", "29": "CAR", "3": "CHI", "4": "CIN", "5": "CLE",
                "6": "DAL", "7": "DEN", "8": "DET", "9": "GB", "34": "HOU", "11": "IND", "30": "JAX", "12": "KC",
                "14": "LA", "24": "LAC", "13": "LV", "15": "MIA", "16": "MIN", "17": "NE", "18": "NO", "19": "NYG",
                "20": "NYJ", "21": "PHI", "23": "PIT", "25": "SF", "26": "SEA", "27": "TB", "10": "TEN", "28": "WAS"}
ESPN_ID_OF = {v: k for k, v in ESPN_TEAM_ID.items()}
ESPN_ABBR = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "LA": "LA", "STL": "LA", "SD": "LAC", "OAK": "LV"}

# Division alignment: franchise -> (conference, division)
_ALIGN_2002 = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"], "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"], "AFC West": ["DEN", "KC", "LAC", "LV"],
    "NFC East": ["DAL", "NYG", "PHI", "WAS"], "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"], "NFC West": ["ARI", "LA", "SEA", "SF"],
}
_ALIGN_1999 = {
    "AFC East": ["BUF", "IND", "MIA", "NE", "NYJ"], "AFC Central": ["BAL", "CIN", "CLE", "JAX", "PIT", "TEN"],
    "AFC West": ["DEN", "KC", "LAC", "LV", "SEA"],
    "NFC East": ["ARI", "DAL", "NYG", "PHI", "WAS"], "NFC Central": ["CHI", "DET", "GB", "MIN", "TB"],
    "NFC West": ["ATL", "CAR", "LA", "NO", "SF"],
}


def alignment(season: int) -> dict[str, list[str]]:
    """Division name -> team abbreviations (as of that season)."""
    al = _ALIGN_1999 if int(season) <= 2001 else _ALIGN_2002
    return {d: sorted(abbr(f, season) for f in fs) for d, fs in al.items()}


def franchise(team: str) -> str:
    """Franchise key (the current abbreviation) of any abbreviation (nflverse or ESPN)."""
    t = str(team).upper()
    if t in FRANCHISES:
        return t
    if t in RELOCATIONS:
        return RELOCATIONS[t][0]
    return ESPN_ABBR.get(t, t)


def abbr(team: str, season: int) -> str:
    """The nflverse abbreviation a franchise used in a season (franchise("STL") in 2015 -> "STL")."""
    f = franchise(team)
    out = f
    for first, ab, _name in FRANCHISES.get(f, []):
        if int(season) >= first:
            out = ab
    return out


def team_name(team: str, season: int) -> str:
    f = franchise(team)
    out = f
    for first, _ab, name in FRANCHISES.get(f, []):
        if int(season) >= first:
            out = name
    return out


def teams(season: int) -> dict[str, dict]:
    """abbr -> {abbr, franchise, name, conf, div, espn_id, city, lat, lon} for the clubs of a season."""
    out = {}
    for div, members in alignment(season).items():
        for ab in members:
            f = franchise(ab)
            city = CITY.get(ab) or CITY.get(f)
            out[ab] = {"abbr": ab, "franchise": f, "name": team_name(f, season), "conf": div.split()[0], "div": div,
                       "espn_id": ESPN_ID_OF.get(f), "city": city[0], "lat": city[1], "lon": city[2]}
    return dict(sorted(out.items()))


def abbr_from_espn(espn_id_or_abbr: str, season: int) -> str | None:
    """nflverse abbreviation for an ESPN team id ("14") or ESPN abbreviation ("LAR")."""
    k = str(espn_id_or_abbr)
    f = ESPN_TEAM_ID.get(k) or (franchise(k) if k.upper() in FRANCHISES or k.upper() in ESPN_ABBR or k.upper() in RELOCATIONS else None)
    return abbr(f, season) if f else None


def division_of(team: str, season: int) -> str | None:
    t = abbr(team, season)
    for d, ms in alignment(season).items():
        if t in ms:
            return d
    return None


def conference_of(team: str, season: int) -> str | None:
    d = division_of(team, season)
    return d.split()[0] if d else None


# ── stadiums ────────────────────────────────────────────────────────────────

# stadium_id -> (name, city, country, lat, lon, altitude_m, roof, tz)
# roof: "outdoors" | "dome" | "retractable" (nflverse per-game roof: outdoors / dome / open / closed)
STADIUMS: dict[str, tuple] = {
    "ATL00": ("Georgia Dome", "Atlanta, GA", "USA", 33.7577, -84.4008, 320, "dome", "America/New_York"),
    "ATL97": ("Mercedes-Benz Stadium", "Atlanta, GA", "USA", 33.7554, -84.4010, 320, "retractable", "America/New_York"),
    "BAL00": ("M&T Bank Stadium", "Baltimore, MD", "USA", 39.2780, -76.6227, 10, "outdoors", "America/New_York"),
    "BOS00": ("Gillette Stadium", "Foxborough, MA", "USA", 42.0909, -71.2643, 85, "outdoors", "America/New_York"),
    "BOS99": ("Foxboro Stadium", "Foxborough, MA", "USA", 42.0915, -71.2635, 85, "outdoors", "America/New_York"),
    "BRG00": ("Tiger Stadium (LSU)", "Baton Rouge, LA", "USA", 30.4120, -91.1838, 15, "outdoors", "America/Chicago"),
    "BUF00": ("Highmark Stadium", "Orchard Park, NY", "USA", 42.7738, -78.7870, 190, "outdoors", "America/New_York"),
    "BUF01": ("Rogers Centre", "Toronto, ON", "Canada", 43.6414, -79.3894, 80, "retractable", "America/Toronto"),
    "CAR00": ("Bank of America Stadium", "Charlotte, NC", "USA", 35.2258, -80.8528, 230, "outdoors", "America/New_York"),
    "CHI98": ("Soldier Field", "Chicago, IL", "USA", 41.8623, -87.6167, 180, "outdoors", "America/Chicago"),
    "CHI99": ("Memorial Stadium (Champaign)", "Champaign, IL", "USA", 40.0992, -88.2360, 225, "outdoors", "America/Chicago"),
    "CIN00": ("Paycor Stadium", "Cincinnati, OH", "USA", 39.0954, -84.5160, 150, "outdoors", "America/New_York"),
    "CIN99": ("Cinergy Field", "Cincinnati, OH", "USA", 39.0974, -84.5072, 150, "outdoors", "America/New_York"),
    "CLE00": ("Huntington Bank Field", "Cleveland, OH", "USA", 41.5061, -81.6995, 180, "outdoors", "America/New_York"),
    "DAL00": ("AT&T Stadium", "Arlington, TX", "USA", 32.7473, -97.0945, 180, "retractable", "America/Chicago"),
    "DAL99": ("Texas Stadium", "Irving, TX", "USA", 32.8400, -96.9110, 150, "outdoors", "America/Chicago"),
    "DEN00": ("Empower Field at Mile High", "Denver, CO", "USA", 39.7439, -105.0201, 1609, "outdoors", "America/Denver"),
    "DEN99": ("Mile High Stadium", "Denver, CO", "USA", 39.7461, -105.0217, 1609, "outdoors", "America/Denver"),
    "DET00": ("Ford Field", "Detroit, MI", "USA", 42.3400, -83.0456, 180, "dome", "America/Detroit"),
    "DET99": ("Pontiac Silverdome", "Pontiac, MI", "USA", 42.6458, -83.2550, 290, "dome", "America/Detroit"),
    "FRA00": ("Deutsche Bank Park", "Frankfurt", "Germany", 50.0686, 8.6455, 110, "outdoors", "Europe/Berlin"),
    "GER00": ("Allianz Arena", "Munich", "Germany", 48.2188, 11.6247, 520, "outdoors", "Europe/Berlin"),
    "GNB00": ("Lambeau Field", "Green Bay, WI", "USA", 44.5013, -88.0622, 195, "outdoors", "America/Chicago"),
    "HOU00": ("NRG Stadium", "Houston, TX", "USA", 29.6847, -95.4107, 15, "retractable", "America/Chicago"),
    "IND00": ("Lucas Oil Stadium", "Indianapolis, IN", "USA", 39.7601, -86.1639, 218, "retractable", "America/Indiana/Indianapolis"),
    "IND99": ("RCA Dome", "Indianapolis, IN", "USA", 39.7639, -86.1628, 218, "dome", "America/Indiana/Indianapolis"),
    "JAX00": ("EverBank Stadium", "Jacksonville, FL", "USA", 30.3239, -81.6373, 5, "outdoors", "America/New_York"),
    "KAN00": ("GEHA Field at Arrowhead Stadium", "Kansas City, MO", "USA", 39.0489, -94.4839, 260, "outdoors", "America/Chicago"),
    "LAX01": ("SoFi Stadium", "Inglewood, CA", "USA", 33.9535, -118.3392, 30, "dome", "America/Los_Angeles"),
    "LAX97": ("StubHub Center", "Carson, CA", "USA", 33.8644, -118.2611, 15, "outdoors", "America/Los_Angeles"),
    "LAX99": ("Los Angeles Memorial Coliseum", "Los Angeles, CA", "USA", 34.0141, -118.2879, 50, "outdoors", "America/Los_Angeles"),
    "LON00": ("Wembley Stadium", "London", "UK", 51.5560, -0.2796, 40, "outdoors", "Europe/London"),
    "LON01": ("Twickenham Stadium", "London", "UK", 51.4559, -0.3415, 10, "outdoors", "Europe/London"),
    "LON02": ("Tottenham Hotspur Stadium", "London", "UK", 51.6043, -0.0664, 30, "outdoors", "Europe/London"),
    "MAD01": ("Santiago Bernabeu", "Madrid", "Spain", 40.4531, -3.6883, 660, "retractable", "Europe/Madrid"),
    "MEL00": ("Melbourne Cricket Ground", "Melbourne", "Australia", -37.8200, 144.9834, 30, "outdoors", "Australia/Melbourne"),
    "MEX00": ("Estadio Azteca", "Mexico City", "Mexico", 19.3029, -99.1505, 2240, "outdoors", "America/Mexico_City"),
    "MIA00": ("Hard Rock Stadium", "Miami Gardens, FL", "USA", 25.9580, -80.2389, 3, "outdoors", "America/New_York"),
    "MIN00": ("Hubert H. Humphrey Metrodome", "Minneapolis, MN", "USA", 44.9739, -93.2581, 255, "dome", "America/Chicago"),
    "MIN01": ("U.S. Bank Stadium", "Minneapolis, MN", "USA", 44.9738, -93.2575, 255, "dome", "America/Chicago"),
    "MIN98": ("TCF Bank Stadium", "Minneapolis, MN", "USA", 44.9765, -93.2246, 255, "outdoors", "America/Chicago"),
    "MUN01": ("FC Bayern Munich Stadium (Allianz Arena)", "Munich", "Germany", 48.2188, 11.6247, 520, "outdoors", "Europe/Berlin"),
    "NAS00": ("Nissan Stadium", "Nashville, TN", "USA", 36.1665, -86.7713, 130, "outdoors", "America/Chicago"),
    "NOR00": ("Caesars Superdome", "New Orleans, LA", "USA", 29.9511, -90.0812, 3, "dome", "America/Chicago"),
    "NYC00": ("Giants Stadium", "East Rutherford, NJ", "USA", 40.8122, -74.0742, 3, "outdoors", "America/New_York"),
    "NYC01": ("MetLife Stadium", "East Rutherford, NJ", "USA", 40.8135, -74.0745, 3, "outdoors", "America/New_York"),
    "OAK00": ("Oakland-Alameda County Coliseum", "Oakland, CA", "USA", 37.7516, -122.2005, 5, "outdoors", "America/Los_Angeles"),
    "PAR00": ("Stade de France", "Saint-Denis", "France", 48.9245, 2.3602, 35, "outdoors", "Europe/Paris"),
    "PHI00": ("Lincoln Financial Field", "Philadelphia, PA", "USA", 39.9008, -75.1675, 10, "outdoors", "America/New_York"),
    "PHI99": ("Veterans Stadium", "Philadelphia, PA", "USA", 39.9067, -75.1714, 10, "outdoors", "America/New_York"),
    "PHO00": ("State Farm Stadium", "Glendale, AZ", "USA", 33.5276, -112.2626, 330, "retractable", "America/Phoenix"),
    "PHO99": ("Sun Devil Stadium", "Tempe, AZ", "USA", 33.4264, -111.9325, 360, "outdoors", "America/Phoenix"),
    "PIT00": ("Acrisure Stadium", "Pittsburgh, PA", "USA", 40.4468, -80.0158, 220, "outdoors", "America/New_York"),
    "PIT99": ("Three Rivers Stadium", "Pittsburgh, PA", "USA", 40.4470, -80.0130, 220, "outdoors", "America/New_York"),
    "RIO00": ("Maracana Stadium", "Rio de Janeiro", "Brazil", -22.9122, -43.2302, 10, "outdoors", "America/Sao_Paulo"),
    "SAN00": ("Alamodome", "San Antonio, TX", "USA", 29.4169, -98.4789, 200, "dome", "America/Chicago"),
    "SAO00": ("Arena Corinthians", "Sao Paulo", "Brazil", -23.5453, -46.4742, 760, "outdoors", "America/Sao_Paulo"),
    "SDG00": ("Qualcomm Stadium", "San Diego, CA", "USA", 32.7831, -117.1196, 20, "outdoors", "America/Los_Angeles"),
    "SEA00": ("Lumen Field", "Seattle, WA", "USA", 47.5952, -122.3316, 5, "outdoors", "America/Los_Angeles"),
    "SEA98": ("Kingdome", "Seattle, WA", "USA", 47.5953, -122.3316, 5, "dome", "America/Los_Angeles"),
    "SEA99": ("Husky Stadium", "Seattle, WA", "USA", 47.6503, -122.3016, 15, "outdoors", "America/Los_Angeles"),
    "SFO00": ("Candlestick Park", "San Francisco, CA", "USA", 37.7136, -122.3863, 5, "outdoors", "America/Los_Angeles"),
    "SFO01": ("Levi's Stadium", "Santa Clara, CA", "USA", 37.4030, -121.9700, 5, "outdoors", "America/Los_Angeles"),
    "STL00": ("Edward Jones Dome", "St. Louis, MO", "USA", 38.6328, -90.1885, 140, "dome", "America/Chicago"),
    "TAM00": ("Raymond James Stadium", "Tampa, FL", "USA", 27.9759, -82.5033, 10, "outdoors", "America/New_York"),
    "VEG00": ("Allegiant Stadium", "Paradise, NV", "USA", 36.0909, -115.1833, 620, "dome", "America/Los_Angeles"),
    "WAS00": ("Northwest Stadium", "Landover, MD", "USA", 38.9078, -76.8645, 60, "outdoors", "America/New_York"),
}
STADIUM_FIELDS = ("name", "city", "country", "lat", "lon", "altitude_m", "roof", "tz")


def stadium(stadium_id: str | None) -> dict | None:
    rec = STADIUMS.get(str(stadium_id or ""))
    if not rec:
        return None
    return {"id": stadium_id, **dict(zip(STADIUM_FIELDS, rec))}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def roof_consistent(stadium_roof: str, game_roof: str | None) -> bool:
    """Does nflverse's per-game roof agree with the stadium's roof type?"""
    g = (game_roof or "").strip().lower()
    if not g:
        return True
    if stadium_roof == "outdoors":
        return g == "outdoors"
    if stadium_roof == "dome":
        return g in ("dome", "closed")
    return g in ("open", "closed", "dome", "outdoors")


# ── NFL tiebreaking procedure ───────────────────────────────────────────────
#
# Source: NFL, "Tiebreaking Procedures", https://www.nfl.com/standings/tie-breaking-procedures
# (the operations.nfl.com page now answers 404; nfl.com hosts the same procedure). Read 1 Oct 2026.
# Each step is (key, the NFL's wording). `oddsmarkets.nfl.tiebreak` implements every key.

TIEBREAK_SOURCE = "https://www.nfl.com/standings/tie-breaking-procedures"
TIEBREAK_READ = "2026-10-01"

DIVISION_TWO = [
    ("h2h", "Head-to-head (best won-lost-tied percentage in games between the clubs)."),
    ("div_pct", "Best won-lost-tied percentage in games played within the division."),
    ("common_pct", "Best won-lost-tied percentage in common games."),
    ("conf_pct", "Best won-lost-tied percentage in games played within the conference."),
    ("sov", "Strength of victory in all games."),
    ("sos", "Strength of schedule in all games."),
    ("conf_rank", "Best combined ranking among conference teams in points scored and points allowed in all games."),
    ("all_rank", "Best combined ranking among all teams in points scored and points allowed in all games."),
    ("common_net", "Best net points in common games."),
    ("all_net", "Best net points in all games."),
    ("net_td", "Best net touchdowns in all games."),
    ("coin", "Coin toss."),
]

DIVISION_THREE = [
    ("h2h", "Head-to-head (best won-lost-tied percentage in games among the clubs)."),
    *DIVISION_TWO[1:],
]

WILDCARD_TWO = [
    ("h2h_if", "Head-to-head, if applicable."),
    ("conf_pct", "Best won-lost-tied percentage in games played within the conference."),
    ("common_pct4", "Best won-lost-tied percentage in common games, minimum of four."),
    ("sov", "Strength of victory in all games."),
    ("sos", "Strength of schedule in all games."),
    ("conf_rank", "Best combined ranking among conference teams in points scored and points allowed in all games."),
    ("all_rank", "Best combined ranking among all teams in points scored and points allowed in all games."),
    ("conf_net", "Best net points in conference games."),
    ("all_net", "Best net points in all games."),
    ("net_td", "Best net touchdowns in all games."),
    ("coin", "Coin toss."),
]

WILDCARD_THREE = [
    ("div_reduce", "Apply division tiebreaker to eliminate all but the highest ranked club in each division prior to "
                   "proceeding to step 2. The original seeding within a division upon application of the division "
                   "tiebreaker remains the same for all subsequent applications of the procedure that are necessary "
                   "to identify the Wild Card participants."),
    ("h2h_sweep", "Head-to-head sweep. (Applicable only if one club has defeated each of the others or if one club "
                  "has lost to each of the others.)"),
    *WILDCARD_TWO[1:],
]

TIEBREAK_NOTES = [
    "Tie games count as one-half win and one-half loss for both clubs.",
    "Only one club advances in any tie-breaking step. Remaining tied clubs revert to the first step of the "
    "applicable division or Wild Card tie-breakers.",
    "Division, three or more clubs (Note): If two clubs remain tied after one-or-more clubs are eliminated during any "
    "step, tiebreaker restarts at Step 1 of two-club format. If three clubs remain tied after a fourth club is "
    "eliminated during any step, tiebreaker restarts at Step 1 of three-club format.",
    "Wild Card, three or more clubs (Note): If two clubs remain tied after one-or-more clubs are eliminated during any "
    "step, tiebreaker restarts at Step 1 of two-club format. If three clubs remain tied after a fourth club is "
    "eliminated during any step, tiebreaker restarts at Step 2 of three-club format.",
    "When the first Wild Card team has been identified, the procedure is repeated to name the second and third Wild "
    "Card (i.e., eliminate all but the highest-ranked club in each division prior to proceeding to Step 2).",
    "In comparing records against common opponents among tied teams, the best won-lost-tied percentage is the "
    "deciding factor, since teams may have played an unequal number of games.",
    "To determine home-field priority among division winners, apply Wild Card tiebreakers.",
    "To determine home-field priority for Wild Card qualifiers, apply division tiebreakers (if teams are from the "
    "same division) or Wild Card tiebreakers (if teams are from different divisions).",
    "To determine the best combined ranking among conference teams in points scored and points allowed, add a "
    "team's position in the two categories, and the lowest score wins.",
]

# Interpretations where the published text is silent (stated on the methodology page):
TIEBREAK_INTERPRETATION = [
    "The published notes speak of three clubs remaining after a fourth is eliminated; the same restart applies "
    "whenever three or more clubs remain after any are eliminated (division: Step 1 of the three-club format; Wild "
    "Card: Step 2, the division reduction having been made).",
    "Strength of victory and strength of schedule count each game (an opponent beaten twice counts twice).",
    "Points rankings share places on equal points (competition ranking: 1, 2, 2, 4).",
    "A club with no games in a category has a percentage of 0.5 for that category (it cannot be compared).",
    "Net touchdowns need touchdown counts (from play-by-play); without them the step passes to the coin toss.",
    "The coin toss is a seeded random draw so that the same inputs give the same order.",
]
