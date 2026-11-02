"""
Rugby nations: a code, a home location (the main test city: latitude, longitude, UTC offset in hours) and a
tier for priors. The location drives the travel feature (great-circle distance and time zones crossed between the
team's home and the venue); the tier sets a new team's starting rating. ESPN names map here through `lookup`
(women's sides carry " Women" and use the same nation row).

Tier 1 = the twelve Nations Championship sides minus Fiji and Japan (Six Nations and Rugby Championship);
tier 2 = the other regular Rugby World Cup sides; tier 3 = everyone else.
"""
from __future__ import annotations

import math
import re

# name: (code, lat, lon, utc_offset, tier)
NATIONS = {
    "England": ("ENG", 51.46, -0.34, 0, 1), "France": ("FRA", 48.92, 2.36, 1, 1), "Ireland": ("IRE", 53.34, -6.23, 0, 1),
    "Italy": ("ITA", 41.93, 12.45, 1, 1), "Scotland": ("SCO", 55.94, -3.24, 0, 1), "Wales": ("WAL", 51.48, -3.18, 0, 1),
    "Argentina": ("ARG", -34.60, -58.38, -3, 1), "Australia": ("AUS", -33.85, 151.06, 10, 1),
    "New Zealand": ("NZL", -36.87, 174.74, 12, 1), "South Africa": ("RSA", -26.20, 28.04, 2, 1),
    "Fiji": ("FIJ", -18.14, 178.44, 12, 2), "Japan": ("JPN", 35.68, 139.71, 9, 2), "Georgia": ("GEO", 41.72, 44.78, 4, 2),
    "Samoa": ("SAM", -13.83, -171.76, 13, 2), "Tonga": ("TGA", -21.14, -175.20, 13, 2),
    "United States": ("USA", 39.74, -104.99, -6, 2), "USA": ("USA", 39.74, -104.99, -6, 2),
    "Canada": ("CAN", 49.28, -123.12, -7, 2), "Romania": ("ROU", 44.43, 26.10, 2, 2), "Uruguay": ("URU", -34.90, -56.16, -3, 2),
    "Spain": ("ESP", 40.42, -3.70, 1, 2), "Portugal": ("POR", 38.72, -9.14, 0, 2), "Chile": ("CHI", -33.45, -70.66, -4, 2),
    "Namibia": ("NAM", -22.56, 17.08, 2, 2), "Russia": ("RUS", 55.75, 37.62, 3, 2), "Hong Kong": ("HKG", 22.32, 114.17, 8, 2),
    "Hong Kong China": ("HKG", 22.32, 114.17, 8, 2), "Zimbabwe": ("ZIM", -17.83, 31.05, 2, 3),
    "Belgium": ("BEL", 50.85, 4.35, 1, 3), "Netherlands": ("NED", 52.37, 4.90, 1, 3), "Germany": ("GER", 52.52, 13.40, 1, 3),
    "Switzerland": ("SUI", 46.95, 7.45, 1, 3), "Poland": ("POL", 52.23, 21.01, 1, 3), "Czech Republic": ("CZE", 50.08, 14.44, 1, 3),
    "Czechia": ("CZE", 50.08, 14.44, 1, 3), "Brazil": ("BRA", -23.55, -46.63, -3, 3), "Paraguay": ("PAR", -25.26, -57.58, -3, 3),
    "Colombia": ("COL", 4.71, -74.07, -5, 3), "Mexico": ("MEX", 19.43, -99.13, -6, 3), "Kenya": ("KEN", -1.29, 36.82, 3, 3),
    "Uganda": ("UGA", 0.35, 32.58, 3, 3), "Tunisia": ("TUN", 36.81, 10.18, 1, 3), "Morocco": ("MAR", 33.57, -7.59, 1, 3),
    "Ivory Coast": ("CIV", 5.36, -4.01, 0, 3), "Senegal": ("SEN", 14.69, -17.44, 0, 3), "Algeria": ("ALG", 36.75, 3.06, 1, 3),
    "Korea": ("KOR", 37.57, 126.98, 9, 3), "South Korea": ("KOR", 37.57, 126.98, 9, 3), "Sri Lanka": ("SRI", 6.93, 79.85, 5.5, 3),
    "Malaysia": ("MAS", 3.14, 101.69, 8, 3), "Singapore": ("SGP", 1.35, 103.82, 8, 3), "Philippines": ("PHI", 14.60, 120.98, 8, 3),
    "China": ("CHN", 39.90, 116.40, 8, 3), "Kazakhstan": ("KAZ", 43.24, 76.89, 6, 3), "United Arab Emirates": ("UAE", 25.20, 55.27, 4, 3),
    "Arabian Gulf": ("AGU", 25.20, 55.27, 4, 3), "Papua New Guinea": ("PNG", -9.44, 147.18, 10, 3),
    "Cook Islands": ("COK", -21.21, -159.78, -10, 3), "Ukraine": ("UKR", 50.45, 30.52, 2, 3), "Lithuania": ("LTU", 54.69, 25.28, 2, 3),
    "Latvia": ("LAT", 56.95, 24.11, 2, 3), "Croatia": ("CRO", 45.81, 15.98, 1, 3), "Sweden": ("SWE", 59.33, 18.07, 1, 3),
    "Denmark": ("DEN", 55.68, 12.57, 1, 3), "Norway": ("NOR", 59.91, 10.75, 1, 3), "Finland": ("FIN", 60.17, 24.94, 2, 3),
    "Austria": ("AUT", 48.21, 16.37, 1, 3), "Hungary": ("HUN", 47.50, 19.04, 1, 3), "Moldova": ("MDA", 47.01, 28.86, 2, 3),
    "Malta": ("MLT", 35.90, 14.51, 1, 3), "Israel": ("ISR", 32.09, 34.78, 2, 3), "Luxembourg": ("LUX", 49.61, 6.13, 1, 3),
    "Slovenia": ("SLO", 46.06, 14.51, 1, 3), "Serbia": ("SRB", 44.79, 20.45, 1, 3), "Bulgaria": ("BUL", 42.70, 23.32, 2, 3),
    "Andorra": ("AND", 42.51, 1.52, 1, 3), "Cyprus": ("CYP", 35.17, 33.36, 2, 3), "Bosnia and Herzegovina": ("BIH", 43.86, 18.41, 1, 3),
    "Madagascar": ("MAD", -18.88, 47.51, 3, 3), "Zambia": ("ZAM", -15.42, 28.28, 2, 3), "Botswana": ("BOT", -24.63, 25.92, 2, 3),
    "Nigeria": ("NGR", 6.52, 3.38, 1, 3), "Ghana": ("GHA", 5.60, -0.19, 0, 3), "Cameroon": ("CMR", 3.85, 11.50, 1, 3),
    "Peru": ("PER", -12.05, -77.04, -5, 3), "Venezuela": ("VEN", 10.48, -66.90, -4, 3), "Guyana": ("GUY", 6.80, -58.16, -4, 3),
    "Trinidad and Tobago": ("TTO", 10.65, -61.50, -4, 3), "Jamaica": ("JAM", 18.02, -76.80, -5, 3), "Bermuda": ("BER", 32.30, -64.78, -4, 3),
    "Cayman Islands": ("CAY", 19.29, -81.37, -5, 3), "Barbados": ("BRB", 13.10, -59.61, -4, 3), "Taiwan": ("TPE", 25.03, 121.57, 8, 3),
    "Chinese Taipei": ("TPE", 25.03, 121.57, 8, 3), "Thailand": ("THA", 13.76, 100.50, 7, 3), "India": ("IND", 19.08, 72.88, 5.5, 3),
    "Niue": ("NIU", -19.05, -169.92, -11, 3), "Tahiti": ("TAH", -17.53, -149.57, -10, 3), "Solomon Islands": ("SOL", -9.43, 159.95, 11, 3),
    "Vanuatu": ("VAN", -17.73, 168.32, 11, 3), "American Samoa": ("ASA", -14.28, -170.70, -11, 3),
    "Pacific Islanders": ("PIS", -18.14, 178.44, 12, 2), "British and Irish Lions": ("BIL", 51.50, -0.12, 0, 1),
    "British & Irish Lions": ("BIL", 51.50, -0.12, 0, 1),
    "Barbarians": ("BAR", 51.50, -0.12, 0, 1), "World XV": ("WXV", 51.50, -0.12, 0, 1),
    "Emerging Ireland": ("EIR", 53.34, -6.23, 0, 2), "Argentina XV": ("ARX", -34.60, -58.38, -3, 2),
    "Maori All Blacks": ("NZM", -36.87, 174.74, 12, 2), "Māori All Blacks": ("NZM", -36.87, 174.74, 12, 2),
    "England Saxons": ("ENS", 51.46, -0.34, 0, 2), "Ireland A": ("IRA", 53.34, -6.23, 0, 2), "Scotland A": ("SCA", 55.94, -3.24, 0, 2),
    "Tonga XV": ("TGX", -21.14, -175.20, 13, 3), "Fiji Warriors": ("FIW", -18.14, 178.44, 12, 3),
    "New Zealand Maori": ("NZM", -36.87, 174.74, 12, 2), "AUNZ XV": ("ANZ", -33.85, 151.06, 10, 2),
    "Emerging Springboks": ("ESA", -26.20, 28.04, 2, 2), "First Nations & Pasifika XV": ("FNP", -33.85, 151.06, 10, 2),
    "Provincial Union XV": ("PUX", -36.87, 174.74, 12, 2),
    "Bahamas": ("BAH", 25.05, -77.35, -5, 3), "Costa Rica": ("CRC", 9.93, -84.08, -6, 3), "Estonia": ("EST", 59.44, 24.75, 2, 3),
    "Eswatini": ("SWZ", -26.31, 31.14, 2, 3), "Qatar": ("QAT", 25.29, 51.53, 3, 3), "Kosovo": ("KOS", 42.66, 21.17, 1, 3),
    "Montenegro": ("MNE", 42.44, 19.26, 1, 3), "Burkina Faso": ("BFA", 12.37, -1.52, 0, 3), "Saint Lucia": ("LCA", 14.01, -60.99, -4, 3),
    "St. Vincent and the Grenadines": ("VIN", 13.16, -61.22, -4, 3), "Slovakia": ("SVK", 48.15, 17.11, 1, 3),
    "Turkey": ("TUR", 41.01, 28.98, 3, 3), "Korea Republic": ("KOR", 37.57, 126.98, 9, 3), "Cote d'Ivoire": ("CIV", 5.36, -4.01, 0, 3),
    "Bosnia-Herzegovina": ("BIH", 43.86, 18.41, 1, 3),
}
# the feed's names for sides in NATIONS under another name: shown under the name on the right
ALIAS = {"United States of America": "United States", "USA": "United States", "Hong Kong China": "Hong Kong",
         "Czech Republic": "Czechia", "South Korea": "Korea Republic", "Korea": "Korea Republic", "Ivory Coast": "Cote d'Ivoire",
         "Maori All Blacks": "New Zealand Maori", "Māori All Blacks": "New Zealand Maori", "British & Irish Lions": "British and Irish Lions"}
# venue cities for neutral-site matches whose country the feed does not give (World Cup hosts and common neutral venues)
CITIES = {
    "Twickenham": (51.46, -0.34, 0), "London": (51.50, -0.12, 0), "Cardiff": (51.48, -3.18, 0), "Edinburgh": (55.94, -3.24, 0),
    "Dublin": (53.34, -6.23, 0), "Paris": (48.86, 2.35, 1), "Saint-Denis": (48.92, 2.36, 1), "Marseille": (43.27, 5.40, 1),
    "Lyon": (45.76, 4.84, 1), "Nantes": (47.22, -1.55, 1), "Bordeaux": (44.84, -0.58, 1), "Toulouse": (43.60, 1.44, 1),
    "Lille": (50.63, 3.07, 1), "Nice": (43.70, 7.27, 1), "Saint-Etienne": (45.44, 4.39, 1), "Montpellier": (43.61, 3.88, 1),
    "Tokyo": (35.68, 139.71, 9), "Yokohama": (35.44, 139.64, 9), "Osaka": (34.69, 135.50, 9), "Fukuoka": (33.59, 130.40, 9),
    "Sapporo": (43.06, 141.35, 9), "Kobe": (34.69, 135.20, 9), "Kumamoto": (32.80, 130.71, 9), "Oita": (33.24, 131.61, 9),
    "Shizuoka": (34.98, 138.38, 9), "Toyota": (35.08, 137.16, 9), "Kamaishi": (39.28, 141.89, 9), "Kumagaya": (36.15, 139.39, 9),
    "Higashiosaka": (34.68, 135.60, 9), "Chofu": (35.66, 139.54, 9),
    "Sydney": (-33.85, 151.06, 10), "Brisbane": (-27.46, 153.02, 10), "Perth": (-31.95, 115.86, 8), "Melbourne": (-37.82, 144.95, 10),
    "Adelaide": (-34.93, 138.60, 9.5), "Newcastle": (-32.93, 151.78, 10), "Townsville": (-19.26, 146.82, 10),
    "Auckland": (-36.87, 174.74, 12), "Wellington": (-41.29, 174.78, 12), "Christchurch": (-43.53, 172.64, 12),
    "Dunedin": (-45.87, 170.50, 12), "Hamilton": (-37.79, 175.28, 12),
    "Johannesburg": (-26.20, 28.04, 2), "Cape Town": (-33.92, 18.42, 2), "Durban": (-29.86, 31.02, 2), "Pretoria": (-25.75, 28.19, 2),
    "Hong Kong": (22.32, 114.17, 8), "Singapore": (1.35, 103.82, 8), "Dubai": (25.20, 55.27, 4), "Las Vegas": (36.17, -115.14, -8),
    "Chicago": (41.88, -87.63, -6), "Washington": (38.90, -77.04, -5), "Denver": (39.74, -104.99, -7), "Montevideo": (-34.90, -56.16, -3),
    "Buenos Aires": (-34.60, -58.38, -3), "La Plata": (-34.92, -57.95, -3), "Madrid": (40.42, -3.70, 1), "Lisbon": (38.72, -9.14, 0),
    "Rome": (41.93, 12.45, 1), "Genoa": (44.41, 8.93, 1), "Turin": (45.07, 7.69, 1), "Udine": (46.06, 13.24, 1),
    "Liverpool": (53.41, -2.98, 0), "Gloucester": (51.86, -2.24, 0), "Leicester": (52.64, -1.13, 0), "Exeter": (50.72, -3.53, 0),
    "Brighton": (50.82, -0.14, 0), "Newcastle upon Tyne": (54.98, -1.61, 0), "Milton Keynes": (52.04, -0.76, 0),
    "Manchester": (53.48, -2.24, 0), "Leeds": (53.80, -1.55, 0), "Bucharest": (44.43, 26.10, 2), "Tbilisi": (41.72, 44.78, 4),
    "Suva": (-18.14, 178.44, 12), "Lautoka": (-17.62, 177.45, 12), "Apia": (-13.83, -171.76, 13), "Nuku'alofa": (-21.14, -175.20, 13),
}
# venues the feed names without a usable city, and city names shared by two test grounds (resolved to the one nearer
# the home side's home)
VENUES = {"Hill Dickinson": (53.43, -3.00, 0), "Everton Stadium": (53.43, -3.00, 0), "Goodison": (53.44, -2.97, 0),
          "St James": (54.98, -1.62, 0), "McDonald Jones": (-32.92, 151.73, 10), "Twickenham": (51.46, -0.34, 0),
          "Allianz Stadium": (-33.89, 151.22, 10), "Stade de France": (48.92, 2.36, 1)}
AMBIGUOUS = {"Newcastle": [(-32.93, 151.78, 10), (54.98, -1.61, 0)], "Hamilton": [(-37.79, 175.28, 12), (43.26, -79.87, -5)],
             "Perth": [(-31.95, 115.86, 8), (56.40, -3.44, 0)], "Wellington": [(-41.29, 174.78, 12), (-33.65, 18.99, 2)]}
_FOLD = re.compile(r"[^a-z]")
_NAME_FOLD = {_FOLD.sub("", k.lower()): k for k in NATIONS}


def canonical(name: str) -> str:
    """The name the site shows for a national side ('United States of America' -> 'United States'); unknown names
    (club and provincial sides on a tour) come back unchanged."""
    n = str(name or "").strip()
    if n in ALIAS:
        return ALIAS[n]
    r = lookup(n)
    if not r:
        return n
    k = r["name"]
    return ALIAS.get(k, k) if not n.lower().endswith(("women", "women's")) else n


def is_side(name: str) -> bool:
    """A national (or invitational representative) side; a club or provincial side on a tour is not."""
    return lookup(name) is not None


def base_name(name: str) -> str:
    """'England Women' -> 'England'; "Ireland Women's" -> 'Ireland'."""
    n = re.sub(r"\s+(women'?s?|w|xv|7s|sevens)$", "", str(name or "").strip(), flags=re.I)
    return n.strip()


def lookup(name: str) -> dict | None:
    n = base_name(name)
    n = ALIAS.get(n, n)
    k = n if n in NATIONS else _NAME_FOLD.get(_FOLD.sub("", n.lower()))
    if not k:
        return None
    code, lat, lon, tz, tier = NATIONS[k]
    return {"name": k, "code": code, "lat": lat, "lon": lon, "tz": tz, "tier": tier}


# invitational and representative sides: not World Rugby members, so never in the rankings (a Lions test does not
# move either side's points) and never on the power boards
INVITATIONAL = {"BIL", "BAR", "WXV", "NZM", "PIS", "EIR", "ARX", "ENS", "IRA", "SCA", "TGX", "FIW", "ANZ", "ESA", "FNP", "PUX"}


def invitational(name: str) -> bool:
    r = lookup(name)
    return bool(r) and r["code"] in INVITATIONAL


def tier(name: str) -> int:
    r = lookup(name)
    return r["tier"] if r else 3


def km(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def venue_point(match: dict) -> tuple | None:
    """Where a match was played: the venue city when we know it (CITIES), else the home side's home for a home match
    and the venue country for a neutral one."""
    v = match.get("venue") or {}
    name = str(v.get("name") or "")
    for key, loc in VENUES.items():
        if key in name:
            return loc
    city = str(v.get("city") or "").split(",")[0].strip()
    if city in AMBIGUOUS:
        h = lookup((match.get("home") or {}).get("name"))
        if h:
            return min(AMBIGUOUS[city], key=lambda c: km((h["lat"], h["lon"]), c[:2]))
    if city in CITIES:
        return CITIES[city]
    if not match.get("neutral"):
        h = lookup((match.get("home") or {}).get("name"))
        return (h["lat"], h["lon"], h["tz"]) if h else None
    c = lookup(((match.get("venue") or {}).get("country")) or "")
    return (c["lat"], c["lon"], c["tz"]) if c else None


def travel(team_name: str, where: tuple | None) -> tuple[float, float]:
    """(km, time zones crossed) from the team's home to the venue; (0, 0) when unknown."""
    t = lookup(team_name)
    if not t or not where:
        return 0.0, 0.0
    d = km((t["lat"], t["lon"]), where[:2])
    dz = abs(t["tz"] - where[2])
    dz = min(dz, 24 - dz)
    return d, dz
