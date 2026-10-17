"""
Which confederation a national team belongs to, by the name Sofascore gives it.

The nations page groups and filters by confederation; a competition's region
tells the build the confederation of every team in it for the continental
competitions, but the World Cup, the Club World Cup's hosts and friendlies mix
them, so the fallback is this table. A name not listed here is simply shown
without a confederation.
"""
from __future__ import annotations

import re
import unicodedata

_UEFA = """Albania Andorra Armenia Austria Azerbaijan Belarus Belgium Bosnia-Herzegovina Bulgaria Croatia Cyprus
Czech Republic Denmark England Estonia Faroe Islands Finland France Georgia Germany Gibraltar Greece Hungary Iceland
Israel Italy Kazakhstan Kosovo Latvia Liechtenstein Lithuania Luxembourg Malta Moldova Montenegro Netherlands
North Macedonia Northern Ireland Norway Poland Portugal Republic of Ireland Romania Russia San Marino Scotland Serbia
Slovakia Slovenia Spain Sweden Switzerland Turkey Ukraine Wales"""
_CONMEBOL = "Argentina Bolivia Brazil Chile Colombia Ecuador Paraguay Peru Uruguay Venezuela"
_CONCACAF = """Anguilla Antigua and Barbuda Aruba Bahamas Barbados Belize Bermuda Bonaire British Virgin Islands Canada
Cayman Islands Costa Rica Cuba Curaçao Dominica Dominican Republic El Salvador French Guiana Grenada Guadeloupe Guatemala
Guyana Haiti Honduras Jamaica Martinique Mexico Montserrat Nicaragua Panama Puerto Rico Saint Kitts and Nevis Saint Lucia
Saint Martin Saint Vincent and the Grenadines Sint Maarten Suriname Trinidad and Tobago Turks and Caicos Islands
United States US Virgin Islands"""
_CAF = """Algeria Angola Benin Botswana Burkina Faso Burundi Cameroon Cape Verde Central African Republic Chad Comoros
Congo DR Congo Djibouti Egypt Equatorial Guinea Eritrea Eswatini Ethiopia Gabon Gambia Ghana Guinea Guinea-Bissau
Ivory Coast Kenya Lesotho Liberia Libya Madagascar Malawi Mali Mauritania Mauritius Morocco Mozambique Namibia Niger
Nigeria Rwanda São Tomé and Príncipe Senegal Seychelles Sierra Leone Somalia South Africa South Sudan Sudan Tanzania
Togo Tunisia Uganda Zambia Zimbabwe"""
_AFC = """Afghanistan Australia Bahrain Bangladesh Bhutan Brunei Cambodia China Chinese Taipei Guam Hong Kong India
Indonesia Iran Iraq Japan Jordan Kuwait Kyrgyzstan Laos Lebanon Macau Malaysia Maldives Mongolia Myanmar Nepal
North Korea Northern Mariana Islands Oman Pakistan Palestine Philippines Qatar Saudi Arabia Singapore South Korea
Sri Lanka Syria Tajikistan Thailand Timor-Leste Turkmenistan United Arab Emirates Uzbekistan Vietnam Yemen"""
_OFC = "American Samoa Cook Islands Fiji New Caledonia New Zealand Papua New Guinea Samoa Solomon Islands Tahiti Tonga Vanuatu"

# Multi-word names are listed here so the whitespace-split lists above stay readable.
_MULTI = {
    "UEFA": ["Bosnia-Herzegovina", "Czech Republic", "Faroe Islands", "North Macedonia", "Northern Ireland",
             "Republic of Ireland", "San Marino"],
    "CONCACAF": ["Antigua and Barbuda", "British Virgin Islands", "Cayman Islands", "Costa Rica", "Dominican Republic",
                 "El Salvador", "French Guiana", "Puerto Rico", "Saint Kitts and Nevis", "Saint Lucia", "Saint Martin",
                 "Saint Vincent and the Grenadines", "Sint Maarten", "Trinidad and Tobago", "Turks and Caicos Islands",
                 "United States", "US Virgin Islands"],
    "CAF": ["Burkina Faso", "Cape Verde", "Central African Republic", "DR Congo", "Equatorial Guinea", "Ivory Coast",
            "São Tomé and Príncipe", "Sierra Leone", "South Africa", "South Sudan"],
    "AFC": ["Chinese Taipei", "Hong Kong", "North Korea", "Northern Mariana Islands", "Saudi Arabia", "South Korea",
            "Sri Lanka", "United Arab Emirates"],
    "OFC": ["American Samoa", "Cook Islands", "New Caledonia", "New Zealand", "Papua New Guinea", "Solomon Islands"],
}
_SINGLE = {"UEFA": _UEFA, "CONMEBOL": _CONMEBOL, "CONCACAF": _CONCACAF, "CAF": _CAF, "AFC": _AFC, "OFC": _OFC}

# Spellings Sofascore (or an older store) uses for a listed nation.
ALIASES = {
    "usa": "United States", "united states of america": "United States", "türkiye": "Turkey", "turkiye": "Turkey",
    "ireland": "Republic of Ireland", "czechia": "Czech Republic", "bosnia and herzegovina": "Bosnia-Herzegovina",
    "bosnia & herzegovina": "Bosnia-Herzegovina", "macedonia": "North Macedonia", "korea republic": "South Korea",
    "korea dpr": "North Korea", "dpr korea": "North Korea", "cote d'ivoire": "Ivory Coast", "côte d'ivoire": "Ivory Coast",
    "cape verde islands": "Cape Verde", "cabo verde": "Cape Verde", "congo dr": "DR Congo", "dr congo": "DR Congo",
    "democratic republic of congo": "DR Congo", "congo republic": "Congo", "swaziland": "Eswatini",
    "ir iran": "Iran", "iran ir": "Iran", "china pr": "China", "uae": "United Arab Emirates", "east timor": "Timor-Leste",
    "trinidad & tobago": "Trinidad and Tobago", "curacao": "Curaçao", "sao tome and principe": "São Tomé and Príncipe",
    "st. kitts and nevis": "Saint Kitts and Nevis", "st. lucia": "Saint Lucia", "st. vincent and the grenadines": "Saint Vincent and the Grenadines",
    "guinea bissau": "Guinea-Bissau", "vietnam": "Vietnam", "viet nam": "Vietnam", "laos": "Laos", "lao": "Laos",
    "myanmar": "Myanmar", "burma": "Myanmar", "hong kong, china": "Hong Kong", "macao": "Macau", "brunei darussalam": "Brunei",
}


def _fold(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _build() -> dict[str, str]:
    table: dict[str, str] = {}
    for conf, names in _MULTI.items():
        for n in names:
            table[_fold(n)] = conf
    for conf, blob in _SINGLE.items():
        remaining = blob
        for n in _MULTI.get(conf, []):
            remaining = remaining.replace(n, " ")
        for n in remaining.split():
            table[_fold(n)] = conf
    return table


CONFEDERATION: dict[str, str] = _build()


def confederation_of(name: str | None) -> str | None:
    """'UEFA', 'CONMEBOL', 'CONCACAF', 'CAF', 'AFC' or 'OFC' for a national team's name; None when unknown."""
    if not name:
        return None
    key = _fold(name)
    key = _fold(ALIASES.get(key, key))
    if key in CONFEDERATION:
        return CONFEDERATION[key]
    # "Spain U21", "Mexico W", "Brazil Olympic": the senior side's confederation.
    base = re.sub(r"\s+(u\d{2}|w|women|olympic|olympics|b|amateur)$", "", key)
    return CONFEDERATION.get(_fold(ALIASES.get(base, base)))
