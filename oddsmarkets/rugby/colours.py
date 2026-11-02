"""Kit colours for the rugby nations (primary, alternate): the hero's diagonal edge, chart lines and team marks.
ESPN's own team colour wins when the feed has one; these fill the gaps and supply the alternate for clashes.
Pale kits (England's white) are handled by the kit's pale-kit rule (QK.color.block)."""
from __future__ import annotations

from . import nations

KITS = {
    "ENG": ("#ffffff", "#c8102e"), "FRA": ("#1d3a8f", "#ffffff"), "IRE": ("#169b62", "#ffffff"), "ITA": ("#1f5fbf", "#ffffff"),
    "SCO": ("#0b2d6b", "#a2aaad"), "WAL": ("#d21034", "#ffffff"), "ARG": ("#75aadb", "#ffffff"), "AUS": ("#ffcd00", "#00843d"),
    "NZL": ("#000000", "#ffffff"), "RSA": ("#007a4d", "#ffb81c"), "FIJ": ("#ffffff", "#62b5e5"), "JPN": ("#c8102e", "#ffffff"),
    "GEO": ("#a6192e", "#ffffff"), "SAM": ("#0033a0", "#ffffff"), "TGA": ("#c10000", "#ffffff"), "USA": ("#0a3161", "#b31942"),
    "CAN": ("#d80621", "#000000"), "ROU": ("#fcd116", "#002b7f"), "URU": ("#5cbfeb", "#ffffff"), "ESP": ("#c60b1e", "#ffc400"),
    "POR": ("#c8102e", "#046a38"), "CHI": ("#d52b1e", "#0039a6"), "NAM": ("#003580", "#d21034"), "RUS": ("#ffffff", "#d52b1e"),
    "HKG": ("#de2910", "#ffffff"), "ZIM": ("#006400", "#ffd200"), "BEL": ("#000000", "#fdda24"), "NED": ("#f36c21", "#ffffff"),
    "GER": ("#ffffff", "#000000"), "SUI": ("#d52b1e", "#ffffff"), "POL": ("#dc143c", "#ffffff"), "CZE": ("#11457e", "#d7141a"),
    "BRA": ("#ffdf00", "#009c3b"), "PAR": ("#d52b1e", "#ffffff"), "COL": ("#fcd116", "#003893"), "MEX": ("#006847", "#ce1126"),
    "KEN": ("#bb0000", "#006600"), "UGA": ("#fcdc04", "#000000"), "KOR": ("#cd2e3a", "#0047a0"), "BIL": ("#c8102e", "#ffffff"),
    "PIS": ("#00205b", "#ffffff"), "NZM": ("#000000", "#ffffff"), "BAR": ("#000000", "#ffffff"),
    # the rest of the test sides in the feed (national colours; 2 Nov 2026), so no side falls back to the kit default
    "ALG": ("#006233", "#ffffff"), "AND": ("#10069f", "#fedf00"), "AUT": ("#c8102e", "#ffffff"), "BAH": ("#00778b", "#ffc72c"),
    "BER": ("#c8102e", "#00205b"), "BFA": ("#ef2b2d", "#009e49"), "BIH": ("#002395", "#fecb00"), "BOT": ("#6da9d2", "#000000"),
    "BUL": ("#00966e", "#d62612"), "CAY": ("#c8102e", "#012169"), "CIV": ("#f77f00", "#009e60"), "CRC": ("#002b7f", "#ce1126"),
    "CRO": ("#d6001c", "#ffffff"), "CYP": ("#0f5aa8", "#d57800"), "DEN": ("#c60c30", "#ffffff"), "ESA": ("#007a4d", "#ffb81c"),
    "EST": ("#0072ce", "#000000"), "FIN": ("#002f6c", "#ffffff"), "GUY": ("#009e49", "#fcd116"), "HUN": ("#ce2939", "#477050"),
    "IND": ("#ff9933", "#138808"), "ISR": ("#0038b8", "#ffffff"), "JAM": ("#009b3a", "#fed100"), "KOS": ("#244aa5", "#d0a650"),
    "LAT": ("#9e3039", "#ffffff"), "LCA": ("#66ccff", "#fcd116"), "LTU": ("#006a44", "#fdb913"), "LUX": ("#00a1de", "#ef3340"),
    "MAS": ("#010066", "#cc0001"), "MDA": ("#0046ae", "#ffd200"), "MLT": ("#cf142b", "#ffffff"), "MNE": ("#c40308", "#d4af3a"),
    "NOR": ("#ba0c2f", "#00205b"), "PER": ("#d91023", "#ffffff"), "QAT": ("#8a1538", "#ffffff"), "SEN": ("#00853f", "#fdef42"),
    "SGP": ("#ef3340", "#ffffff"), "SLO": ("#005da4", "#ed1c24"), "SRB": ("#c6363c", "#0c4076"), "SRI": ("#8d153a", "#ffbe29"),
    "SVK": ("#0b4ea2", "#ee1c25"), "SWE": ("#006aa7", "#fecc00"), "SWZ": ("#3e5eb9", "#ffd900"), "THA": ("#2d2a4a", "#a51931"),
    "TPE": ("#000095", "#fe0000"), "TTO": ("#da1a35", "#000000"), "TUN": ("#e70013", "#ffffff"), "TUR": ("#e30a17", "#ffffff"),
    "UAE": ("#00732f", "#ff0000"), "UKR": ("#0057b7", "#ffd700"), "VEN": ("#cf142b", "#00247d"), "VIN": ("#009e60", "#fcd116"),
    "ZAM": ("#198a00", "#ef7d00"), "BRB": ("#00267f", "#ffc726"),
}


def kit(name: str, espn: str | None = None, espn_alt: str | None = None) -> tuple[str | None, str | None]:
    n = nations.lookup(name)
    k = KITS.get(n["code"]) if n else None
    prim = espn if espn and espn.lower() not in ("#000000", "#ffffff") and not k else (k[0] if k else espn)
    alt = (k[1] if k else None) or espn_alt
    return prim, alt
