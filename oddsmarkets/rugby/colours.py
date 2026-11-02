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
}


def kit(name: str, espn: str | None = None, espn_alt: str | None = None) -> tuple[str | None, str | None]:
    n = nations.lookup(name)
    k = KITS.get(n["code"]) if n else None
    prim = espn if espn and espn.lower() not in ("#000000", "#ffffff") and not k else (k[0] if k else espn)
    alt = (k[1] if k else None) or espn_alt
    return prim, alt
