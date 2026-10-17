"""
Team-name normalisation shared across data sources.

Every provider spells teams differently — "Türkiye" vs "Turkey", "CA Boca Juniors"
vs "Boca Juniors" — and joining a market feed to a model feed fails silently when the
names disagree: the team is simply dropped, and the dashboard shows a gap rather than
an error. This module holds one registry per competition family so that mapping lives
in a single place.

Registries are deliberately separate. National-team and club aliases must not share a
namespace: "Racing" is a club in Argentina and part of several European club names,
while "Argentina" as a national side has nothing to do with Argentine clubs.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# ── International / national teams ───────────────────────────────────────────
# Sourced from the World Cup live-data client, which resolved these against
# football-data.org and API-Football spellings.
INTERNATIONAL_ALIASES: dict[str, str] = {
    "United States": "USA",
    "United States of America": "USA",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "IR Iran": "Iran",
    "Korea Republic": "South Korea",
    "Republic of Korea": "South Korea",
    "New-Zealand": "New Zealand",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "Curaçao": "Curacao",
    "Cabo Verde": "Cape Verde",
    "Cape Verde Islands": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "Czechia": "Czech Republic",
    "Czech Rep.": "Czech Republic",
    "Congo DR": "DR Congo",
    "DR Congo": "DR Congo",
    "Democratic Republic of Congo": "DR Congo",
}

# ── Argentine Liga Profesional ───────────────────────────────────────────────
# Canonical form is the short name Argentine media uses, which is also what betting
# markets tend to carry. Sofascore is the primary feed, so its spellings are covered
# first; bookmaker variants (via The Odds API) are added alongside.
#
# Deliberately kept flat rather than clever: club naming in Argentina is full of
# collisions ("Independiente" vs "Independiente Rivadavia", three clubs called
# "Estudiantes", "Central Córdoba" existing in two cities) which a fuzzy matcher
# gets wrong far more confidently than a lookup table does.
LIGA_ARGENTINA_ALIASES: dict[str, str] = {
    "CA Boca Juniors": "Boca Juniors",
    "Boca Jrs": "Boca Juniors",
    "CA River Plate": "River Plate",
    "CA Racing Club": "Racing Club",
    "Racing Club de Avellaneda": "Racing Club",
    "CA Independiente": "Independiente",
    "Independiente de Avellaneda": "Independiente",
    "CA San Lorenzo": "San Lorenzo",
    "San Lorenzo de Almagro": "San Lorenzo",
    "CA Vélez Sarsfield": "Vélez Sarsfield",
    "Velez Sarsfield": "Vélez Sarsfield",
    "Vélez": "Vélez Sarsfield",
    "CA Huracán": "Huracán",
    "Huracan": "Huracán",
    "Club Atlético Belgrano": "Belgrano",
    "Belgrano de Córdoba": "Belgrano",
    "Belgrano Cordoba": "Belgrano",
    "CA Talleres": "Talleres",
    "Talleres de Córdoba": "Talleres",
    "Talleres Cordoba": "Talleres",
    "CA Newell's Old Boys": "Newell's Old Boys",
    "Newells Old Boys": "Newell's Old Boys",
    "Newell's": "Newell's Old Boys",
    "CA Rosario Central": "Rosario Central",
    "CA Estudiantes de La Plata": "Estudiantes",
    "Estudiantes de La Plata": "Estudiantes",
    "Estudiantes L.P.": "Estudiantes",
    "CA Gimnasia y Esgrima La Plata": "Gimnasia LP",
    "Gimnasia y Esgrima La Plata": "Gimnasia LP",
    "Gimnasia La Plata": "Gimnasia LP",
    # Sofascore spells the La Plata club without a city and qualifies only the
    # Mendoza one, so the bare form has to resolve to La Plata.
    "Gimnasia y Esgrima": "Gimnasia LP",
    "Gimnasia y Esgrima Mendoza": "Gimnasia Mendoza",
    "Gimnasia y Esgrima de Mendoza": "Gimnasia Mendoza",
    "CA Lanús": "Lanús",
    "Lanus": "Lanús",
    "CA Banfield": "Banfield",
    "CA Tigre": "Tigre",
    "CA Platense": "Platense",
    "Club Atlético Platense": "Platense",
    "CA Argentinos Juniors": "Argentinos Juniors",
    "Argentinos Jrs": "Argentinos Juniors",
    "CA Defensa y Justicia": "Defensa y Justicia",
    "Defensa": "Defensa y Justicia",
    "CA Barracas Central": "Barracas Central",
    "CA Sarmiento": "Sarmiento",
    "Sarmiento de Junín": "Sarmiento",
    "Sarmiento Junin": "Sarmiento",
    "CA Independiente Rivadavia": "Independiente Rivadavia",
    "Independiente Rivadavia de Mendoza": "Independiente Rivadavia",
    "CA Central Córdoba": "Central Córdoba",
    "Central Córdoba de Santiago del Estero": "Central Córdoba",
    "Central Cordoba SdE": "Central Córdoba",
    "CA Instituto": "Instituto",
    "Instituto de Córdoba": "Instituto",
    "CA Godoy Cruz": "Godoy Cruz",
    "Godoy Cruz Antonio Tomba": "Godoy Cruz",
    "CA Unión": "Unión",
    "Union de Santa Fe": "Unión",
    "Unión de Santa Fe": "Unión",
    "Club Atlético Unión de Santa Fe": "Unión",
    "CA Colón": "Colón",
    "Colon de Santa Fe": "Colón",
    "CA Atlético Tucumán": "Atlético Tucumán",
    "Atletico Tucuman": "Atlético Tucumán",
    "CA Riestra": "Deportivo Riestra",
    "Riestra": "Deportivo Riestra",
    "CA Aldosivi": "Aldosivi",
    "CA San Martín de San Juan": "San Martín SJ",
    "San Martin San Juan": "San Martín SJ",
    "CD Estudiantes de Río Cuarto": "Estudiantes Río Cuarto",
    "Deportivo Estudiantes Río Cuarto": "Estudiantes Río Cuarto",
    "Estudiantes de Río Cuarto": "Estudiantes Río Cuarto",
}

# ── Plain leagues ─────────────────────────────────────────────────────────────
# One registry per league, keyed by the league slug with dashes as underscores.
# Canonical form is the short name the club is generally known by in English
# coverage and on the main odds feeds. Sofascore's full names are the primary
# spellings; The Odds API's variants are added where they differ. Clubs relegated
# at the end of last season are included so the previous-season table still joins
# when it seeds Elo.
PREMIER_LEAGUE_ALIASES: dict[str, str] = {
    "Liverpool FC": "Liverpool",
    "Manchester City FC": "Manchester City", "Man City": "Manchester City",
    "Manchester United FC": "Manchester United", "Man Utd": "Manchester United",
    "Man United": "Manchester United",
    "Tottenham Hotspur": "Tottenham", "Spurs": "Tottenham",
    "Brighton & Hove Albion": "Brighton", "Brighton and Hove Albion": "Brighton",
    "Newcastle United": "Newcastle",
    "West Ham United": "West Ham",
    "Wolverhampton": "Wolves", "Wolverhampton Wanderers": "Wolves",
    "Nottingham Forest FC": "Nottingham Forest", "Nottm Forest": "Nottingham Forest",
    "AFC Bournemouth": "Bournemouth",
    "Leeds United": "Leeds",
    "Ipswich Town": "Ipswich",
    "Hull City": "Hull",
    "Coventry City": "Coventry",
    "Sunderland AFC": "Sunderland",
    "Burnley FC": "Burnley",
    "Everton FC": "Everton",
    "Chelsea FC": "Chelsea",
    "Arsenal FC": "Arsenal",
    "Fulham FC": "Fulham",
    "Brentford FC": "Brentford",
    "Crystal Palace FC": "Crystal Palace",
    "Aston Villa FC": "Aston Villa",
}

LA_LIGA_ALIASES: dict[str, str] = {
    "FC Barcelona": "Barcelona",
    "Real Madrid CF": "Real Madrid",
    "Atlético de Madrid": "Atlético Madrid", "Atletico Madrid": "Atlético Madrid",
    "Athletic Bilbao": "Athletic Club", "Athletic Club Bilbao": "Athletic Club",
    "Real Betis Balompié": "Real Betis", "Betis": "Real Betis",
    "Sevilla FC": "Sevilla",
    "Villarreal CF": "Villarreal",
    "Real Sociedad de Fútbol": "Real Sociedad",
    "RC Celta de Vigo": "Celta Vigo", "Celta de Vigo": "Celta Vigo", "RC Celta": "Celta Vigo",
    "Rayo Vallecano de Madrid": "Rayo Vallecano",
    "CA Osasuna": "Osasuna",
    "Getafe CF": "Getafe",
    "RCD Espanyol": "Espanyol", "Espanyol Barcelona": "Espanyol",
    "Valencia CF": "Valencia",
    "Deportivo Alavés": "Alavés", "Alaves": "Alavés",
    "Levante UD": "Levante",
    "Elche CF": "Elche",
    "Girona FC": "Girona",
    "RCD Mallorca": "Mallorca",
    "Real Oviedo": "Oviedo",
    "Málaga CF": "Málaga", "Malaga": "Málaga",
    "Deportivo de A Coruña": "Deportivo La Coruña", "Deportivo La Coruna": "Deportivo La Coruña",
    "Deportivo": "Deportivo La Coruña",
    "Real Racing Club": "Racing Santander", "Racing de Santander": "Racing Santander",
}

SERIE_A_ALIASES: dict[str, str] = {
    "FC Internazionale": "Inter", "Inter Milan": "Inter", "Internazionale": "Inter",
    "AC Milan": "Milan",
    "SSC Napoli": "Napoli",
    "Juventus FC": "Juventus",
    "AS Roma": "Roma",
    "SS Lazio": "Lazio",
    "Atalanta BC": "Atalanta",
    "ACF Fiorentina": "Fiorentina",
    "Bologna FC": "Bologna", "Bologna FC 1909": "Bologna",
    "Torino FC": "Torino",
    "Udinese Calcio": "Udinese",
    "Genoa CFC": "Genoa",
    "Cagliari Calcio": "Cagliari",
    "US Lecce": "Lecce",
    "Parma Calcio 1913": "Parma", "Parma Calcio": "Parma",
    "Como 1907": "Como",
    "US Sassuolo": "Sassuolo", "Sassuolo Calcio": "Sassuolo",
    "AC Monza": "Monza",
    "Venezia FC": "Venezia",
    "Frosinone Calcio": "Frosinone",
    "Hellas Verona FC": "Hellas Verona", "Verona": "Hellas Verona",
    "Pisa SC": "Pisa",
    "US Cremonese": "Cremonese",
}

BUNDESLIGA_ALIASES: dict[str, str] = {
    "FC Bayern München": "Bayern München", "Bayern Munich": "Bayern München",
    "FC Bayern Munich": "Bayern München", "Bayern": "Bayern München",
    "Borussia Dortmund": "Dortmund", "BVB": "Dortmund",
    "Bayer 04 Leverkusen": "Leverkusen", "Bayer Leverkusen": "Leverkusen",
    "RasenBallsport Leipzig": "RB Leipzig",
    "VfB Stuttgart": "Stuttgart",
    "SC Freiburg": "Freiburg",
    "1. FSV Mainz 05": "Mainz", "FSV Mainz 05": "Mainz", "Mainz 05": "Mainz",
    "TSG Hoffenheim": "Hoffenheim", "TSG 1899 Hoffenheim": "Hoffenheim",
    "VfL Wolfsburg": "Wolfsburg",
    "Borussia M'gladbach": "Mönchengladbach", "Borussia Mönchengladbach": "Mönchengladbach",
    "Borussia Monchengladbach": "Mönchengladbach", "Gladbach": "Mönchengladbach",
    "FC Augsburg": "Augsburg",
    "1. FC Union Berlin": "Union Berlin", "FC Union Berlin": "Union Berlin",
    "SV Werder Bremen": "Werder Bremen", "Werder": "Werder Bremen",
    "1. FC Heidenheim": "Heidenheim", "1. FC Heidenheim 1846": "Heidenheim",
    "FC St. Pauli": "St. Pauli", "St Pauli": "St. Pauli",
    "Hamburger SV": "Hamburg", "HSV": "Hamburg",
    "1. FC Köln": "Köln", "FC Cologne": "Köln", "1. FC Koln": "Köln", "FC Köln": "Köln",
    "FC Schalke 04": "Schalke", "Schalke 04": "Schalke",
    "SC Paderborn 07": "Paderborn", "SC Paderborn": "Paderborn",
    "SV 07 Elversberg": "Elversberg", "SV Elversberg": "Elversberg",
}

LIGUE_1_ALIASES: dict[str, str] = {
    "Paris Saint-Germain": "PSG", "Paris Saint Germain": "PSG", "Paris SG": "PSG",
    "Olympique de Marseille": "Marseille", "Olympique Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon", "Olympique Lyon": "Lyon",
    "AS Monaco": "Monaco",
    "LOSC Lille": "Lille", "Lille OSC": "Lille",
    "OGC Nice": "Nice",
    "Stade Rennais": "Rennes", "Stade Rennais FC": "Rennes",
    "RC Strasbourg": "Strasbourg", "RC Strasbourg Alsace": "Strasbourg",
    "RC Lens": "Lens",
    "Stade Brestois": "Brest", "Stade Brestois 29": "Brest",
    "Toulouse FC": "Toulouse",
    "FC Nantes": "Nantes",
    "AJ Auxerre": "Auxerre",
    "Angers SCO": "Angers",
    "Le Havre AC": "Le Havre",
    "FC Lorient": "Lorient",
    "FC Metz": "Metz",
    "Le Mans FC": "Le Mans",
    "ESTAC Troyes": "Troyes", "Troyes AC": "Troyes",
}

EREDIVISIE_ALIASES: dict[str, str] = {
    "AFC Ajax": "Ajax", "Ajax Amsterdam": "Ajax",
    "PSV Eindhoven": "PSV",
    "Feyenoord Rotterdam": "Feyenoord",
    "AZ Alkmaar": "AZ",
    "FC Twente": "Twente",
    "FC Utrecht": "Utrecht",
    "FC Groningen": "Groningen",
    "SC Heerenveen": "Heerenveen",
    "NEC Nijmegen": "NEC",
    "SC Telstar": "Telstar",
    "SC Cambuur": "Cambuur",
    "Excelsior Rotterdam": "Excelsior",
    "Willem II Tilburg": "Willem II",
    "Heracles Almelo": "Heracles",
    "FC Volendam": "Volendam",
}

PRIMEIRA_LIGA_ALIASES: dict[str, str] = {
    "SL Benfica": "Benfica",
    "FC Porto": "Porto",
    "Sporting CP": "Sporting", "Sporting Lisbon": "Sporting",
    "Sporting Braga": "Braga", "SC Braga": "Braga",
    "Vitória SC": "Vitória Guimarães", "Vitoria Guimaraes": "Vitória Guimarães",
    "Vitória de Guimarães": "Vitória Guimarães",
    "FC Arouca": "Arouca",
    "Moreirense FC": "Moreirense",
    "Gil Vicente FC": "Gil Vicente",
    "FC Famalicão": "Famalicão", "Famalicao": "Famalicão",
    "CD Nacional": "Nacional",
    "Rio Ave FC": "Rio Ave",
    "GD Estoril Praia": "Estoril", "Estoril Praia": "Estoril",
    "Casa Pia AC": "Casa Pia",
    "CF Estrela Amadora": "Estrela Amadora", "Estrela da Amadora": "Estrela Amadora",
    "FC Alverca": "Alverca",
    "Académico Viseu FC": "Académico Viseu", "Academico Viseu": "Académico Viseu",
    "CS Marítimo": "Marítimo", "Maritimo": "Marítimo",
    "CD Tondela": "Tondela",
    "AVS - Futebol SAD": "AVS", "AVS Futebol SAD": "AVS",
}

BRASILEIRAO_ALIASES: dict[str, str] = {
    "CR Flamengo": "Flamengo",
    "SE Palmeiras": "Palmeiras",
    "São Paulo FC": "São Paulo", "Sao Paulo": "São Paulo",
    "SC Corinthians": "Corinthians", "Corinthians Paulista": "Corinthians",
    "Santos FC": "Santos",
    "Fluminense FC": "Fluminense",
    "Botafogo FR": "Botafogo",
    "CR Vasco da Gama": "Vasco da Gama", "Vasco": "Vasco da Gama",
    "Grêmio FBPA": "Grêmio", "Gremio": "Grêmio",
    "SC Internacional": "Internacional",
    "Cruzeiro EC": "Cruzeiro",
    "Atletico Mineiro": "Atlético Mineiro",
    "Atlético-MG": "Atlético Mineiro",
    "Athletico": "Athletico Paranaense", "Athletico-PR": "Athletico Paranaense",
    "Club Athletico Paranaense": "Athletico Paranaense",
    "EC Bahia": "Bahia",
    "Red Bull Bragantino": "Bragantino", "RB Bragantino": "Bragantino",
    "EC Vitória": "Vitória", "Vitoria": "Vitória",
    "Mirassol FC": "Mirassol",
    "Coritiba FC": "Coritiba",
    "Clube do Remo": "Remo",
    "Chapecoense AF": "Chapecoense",
    "Fortaleza EC": "Fortaleza",
    "Ceará SC": "Ceará", "Ceara": "Ceará",
    "EC Juventude": "Juventude",
    "Sport Club do Recife": "Sport Recife",
}

MLS_ALIASES: dict[str, str] = {
    "Inter Miami CF": "Inter Miami",
    "Los Angeles FC": "LAFC",
    "Los Angeles Galaxy": "LA Galaxy",
    "Seattle Sounders FC": "Seattle Sounders",
    "Orlando City SC": "Orlando City",
    "New York City FC": "NYCFC", "New York City": "NYCFC",
    "New York Red Bulls": "NY Red Bulls",
    "Vancouver Whitecaps FC": "Vancouver Whitecaps",
    "St.Louis City": "St. Louis City", "St. Louis City SC": "St. Louis City",
    "St Louis City": "St. Louis City",
    "CF Montreal": "CF Montréal", "Montreal Impact": "CF Montréal",
    "Sporting Kansas City": "Sporting KC",
    "Columbus Crew SC": "Columbus Crew",
    "Chicago Fire FC": "Chicago Fire",
    "Houston Dynamo FC": "Houston Dynamo",
    "Minnesota United FC": "Minnesota United",
    "Atlanta United FC": "Atlanta United",
    "Nashville SC": "Nashville",
    "Charlotte FC": "Charlotte",
    "Austin FC": "Austin",
    "San Diego FC": "San Diego",
    "D.C. United": "DC United",
    "Toronto FC": "Toronto",
    "New England Revolution": "New England",
    "San Jose Earthquakes": "San Jose",
}

SAUDI_PRO_LEAGUE_ALIASES: dict[str, str] = {
    "Al Hilal": "Al-Hilal", "Al-Hilal SFC": "Al-Hilal",
    "Al Nassr": "Al-Nassr", "Al-Nassr FC": "Al-Nassr",
    "Al Ittihad": "Al-Ittihad", "Al-Ittihad Club": "Al-Ittihad",
    "Al Ahli": "Al-Ahli", "Al-Ahli Saudi": "Al-Ahli",
    "Al Qadsiah": "Al-Qadsiah",
    "Al Ettifaq": "Al-Ettifaq",
    "Al Shabab": "Al-Shabab",
    "Al Taawoun": "Al-Taawoun",
    "Al Fateh": "Al-Fateh",
    "Al Fayha": "Al-Fayha", "Al Feiha": "Al-Fayha",
    "Al Khaleej": "Al-Khaleej",
    "Al Riyadh": "Al-Riyadh",
    "Al Hazem": "Al-Hazem", "Al Hazm": "Al-Hazem",
    "Al Kholood": "Al-Kholood",
    "Al Faisaly": "Al-Faisaly",
    "Neom SC": "Neom",
    "Abha Club": "Abha",
    "Diriyah Club": "Diriyah",
    "Al-Najma SC": "Al-Najma", "Al Najma": "Al-Najma",
    "Al Okhdood": "Al-Okhdood",
    "Damac FC": "Damac",
}

LIGA_MX_ALIASES: dict[str, str] = {
    "Club América": "América", "Club America": "América", "CF América": "América",
    "CD Guadalajara": "Guadalajara", "Chivas Guadalajara": "Guadalajara", "Chivas": "Guadalajara",
    "Cruz Azul FC": "Cruz Azul",
    "UNAM Pumas": "Pumas UNAM", "Pumas": "Pumas UNAM", "Club Universidad Nacional": "Pumas UNAM",
    "Tigres UANL": "Tigres", "Tigres de la UANL": "Tigres",
    "CF Monterrey": "Monterrey", "Rayados de Monterrey": "Monterrey",
    "Santos Laguna FC": "Santos Laguna",
    "CD Toluca": "Toluca", "Deportivo Toluca": "Toluca",
    "Club León": "León", "Club Leon": "León",
    "CF Pachuca": "Pachuca", "Club Pachuca": "Pachuca",
    "Atlas FC": "Atlas",
    "Club Tijuana": "Tijuana", "Club Tijuana Xoloitzcuintles": "Tijuana", "Xolos": "Tijuana",
    "Club Necaxa": "Necaxa",
    "Club Puebla": "Puebla",
    "Querétaro FC": "Querétaro", "Queretaro": "Querétaro",
    "FC Juárez": "Juárez", "Bravos de Juárez": "Juárez", "Juarez": "Juárez",
    "Mazatlán FC": "Mazatlán", "Mazatlan": "Mazatlán",
    "Atletico San Luis": "Atlético San Luis",
    "Atlante FC": "Atlante", "CF Atlante": "Atlante",
}

BELGIAN_PRO_LEAGUE_ALIASES: dict[str, str] = {
    "Club Brugge KV": "Club Brugge",
    "RSC Anderlecht": "Anderlecht",
    "KRC Genk": "Genk", "Racing Genk": "Genk",
    "Royal Antwerp FC": "Antwerp", "Antwerp FC": "Antwerp",
    "Union Saint-Gilloise": "Union SG", "Royale Union Saint-Gilloise": "Union SG", "Union St.Gilloise": "Union SG",
    "KAA Gent": "Gent", "AA Gent": "Gent",
    "Standard Liege": "Standard Liège", "R. Standard de Liège": "Standard Liège",
    "Cercle Brugge KSV": "Cercle Brugge",
    "KV Mechelen": "Mechelen",
    "Sint-Truidense VV": "Sint-Truiden", "STVV": "Sint-Truiden",
    "Oud-Heverlee Leuven": "OH Leuven",
    "KVC Westerlo": "Westerlo",
    "Sporting Charleroi": "Charleroi", "R. Charleroi SC": "Charleroi", "RC Sporting Charleroi": "Charleroi",
    "FCV Dender EH": "Dender", "FCV Dender": "Dender",
    "SV Zulte Waregem": "Zulte Waregem",
    "RAAL La Louvière": "La Louvière", "La Louviere": "La Louvière",
    "KV Kortrijk": "Kortrijk",
    "Beerschot VA": "Beerschot", "K. Beerschot V.A.": "Beerschot",
    "Lommel SK": "Lommel",
    "SK Beveren": "Beveren", "Waasland-Beveren": "Beveren",
}

REGISTRIES: dict[str, dict[str, str]] = {
    "international": INTERNATIONAL_ALIASES,
    "liga_argentina": LIGA_ARGENTINA_ALIASES,
    "premier_league": PREMIER_LEAGUE_ALIASES,
    "la_liga": LA_LIGA_ALIASES,
    "serie_a": SERIE_A_ALIASES,
    "bundesliga": BUNDESLIGA_ALIASES,
    "ligue_1": LIGUE_1_ALIASES,
    "eredivisie": EREDIVISIE_ALIASES,
    "primeira_liga": PRIMEIRA_LIGA_ALIASES,
    "brasileirao": BRASILEIRAO_ALIASES,
    "mls": MLS_ALIASES,
    "saudi_pro_league": SAUDI_PRO_LEAGUE_ALIASES,
    "liga_mx": LIGA_MX_ALIASES,
    "belgian_pro_league": BELGIAN_PRO_LEAGUE_ALIASES,
}

# Country (alpha-3) -> registry, for cup entrants: a club is canonicalised through
# the registry of the league it plays in, so "Liverpool FC" in the Champions
# League is the same "Liverpool" as in the Premier League store. Clubs from other
# countries keep Sofascore's spelling.
COUNTRY_REGISTRY: dict[str, str] = {
    # Sofascore uses ISO alpha-3 (DEU, PRT, NLD); the FIFA codes are kept as aliases.
    "ENG": "premier_league", "ESP": "la_liga", "ITA": "serie_a", "GER": "bundesliga", "DEU": "bundesliga",
    "FRA": "ligue_1", "NED": "eredivisie", "NLD": "eredivisie", "POR": "primeira_liga", "PRT": "primeira_liga",
    "BRA": "brasileirao", "USA": "mls", "CAN": "mls", "SAU": "saudi_pro_league", "KSA": "saudi_pro_league",
    "ARG": "liga_argentina", "MEX": "liga_mx", "BEL": "belgian_pro_league",
}


def normalize_cup_name(name: str, country_alpha3: str | None) -> str:
    """A cup entrant's canonical name: through its country's league registry when there is one."""
    registry = COUNTRY_REGISTRY.get(str(country_alpha3 or "").upper())
    return normalize_team_name(name, registry) if registry else (name or "").strip()


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def _fold(name: str) -> str:
    """Accent-insensitive, punctuation-insensitive, case-insensitive key."""
    folded = _strip_accents(name).lower()
    folded = folded.replace("&", " and ")
    folded = re.sub(r"[^a-z0-9]+", " ", folded)
    return folded.strip()


def normalize_team_name(name: str, registry: str | dict[str, str] = "international") -> str:
    """
    Map a provider's spelling of a team onto its canonical form.

    `registry` is either a key in REGISTRIES or an explicit alias mapping. Unknown
    names are returned unchanged rather than raising — a provider adding a team we
    have not seen should degrade to a missing join, not a crashed build.

    Matching is tried exactly first, then on an accent- and punctuation-folded key,
    so "Velez Sarsfield", "Vélez Sarsfield" and "CA Vélez Sarsfield" all resolve
    without needing an entry for every permutation.
    """
    if not name:
        return name

    aliases = REGISTRIES.get(registry, {}) if isinstance(registry, str) else registry

    cleaned = name.strip()
    if cleaned in aliases:
        return aliases[cleaned]

    folded = _fold(cleaned)
    table = _fold_table(registry) if isinstance(registry, str) else _build_fold_table(aliases)
    return table.get(folded, cleaned)


def _build_fold_table(aliases: dict[str, str]) -> dict[str, str]:
    """Folded-key lookup for one alias mapping."""
    table: dict[str, str] = {}
    for alias, canonical in aliases.items():
        table.setdefault(_fold(alias), canonical)
    # Canonical names must also resolve to themselves.
    for canonical in set(aliases.values()):
        table.setdefault(_fold(canonical), canonical)
    return table


@lru_cache(maxsize=None)
def _fold_table(registry_name: str) -> dict[str, str]:
    """
    Cached fold table for a named registry.

    Keyed by the registry *name*, never by the mapping's identity. An earlier version
    cached on `id(aliases)`, which is unsafe here because the public signature accepts
    an ad-hoc dict: a temporary can be garbage-collected and CPython can hand its
    address to the next one, silently serving a different registry's table. Ad-hoc
    mappings are therefore built fresh rather than cached — they are small, and a
    wrong join is far worse than a rebuild.
    """
    return _build_fold_table(REGISTRIES.get(registry_name, {}))


def canonical_teams(registry: str | dict[str, str] = "international") -> set[str]:
    """The set of canonical names a registry can produce."""
    aliases = REGISTRIES.get(registry, {}) if isinstance(registry, str) else registry
    return set(aliases.values())
