"""
Team reference for the analytics layer: names, colours, divisions and conferences by season, keyed by the nflverse
abbreviation of that season (LA for the Rams from 2016, STL before; LAC from 2017, SD before; LV from 2020, OAK
before). Builder A's canon (oddsmarkets.nfl.canon) and the season store win where they answer; this table is the
fallback so the layer never stops on a missing canon. Colours are plain hex values (no logos).
"""
from __future__ import annotations

from typing import Any

# abbr: (name, short, division, primary colour, alternate colour)
TEAMS = {
    "ARI": ("Arizona Cardinals", "Cardinals", "NFC West", "#97233F", "#000000"),
    "ATL": ("Atlanta Falcons", "Falcons", "NFC South", "#A71930", "#000000"),
    "BAL": ("Baltimore Ravens", "Ravens", "AFC North", "#241773", "#9E7C0C"),
    "BUF": ("Buffalo Bills", "Bills", "AFC East", "#00338D", "#C60C30"),
    "CAR": ("Carolina Panthers", "Panthers", "NFC South", "#0085CA", "#101820"),
    "CHI": ("Chicago Bears", "Bears", "NFC North", "#0B162A", "#C83803"),
    "CIN": ("Cincinnati Bengals", "Bengals", "AFC North", "#FB4F14", "#000000"),
    "CLE": ("Cleveland Browns", "Browns", "AFC North", "#311D00", "#FF3C00"),
    "DAL": ("Dallas Cowboys", "Cowboys", "NFC East", "#003594", "#869397"),
    "DEN": ("Denver Broncos", "Broncos", "AFC West", "#FB4F14", "#002244"),
    "DET": ("Detroit Lions", "Lions", "NFC North", "#0076B6", "#B0B7BC"),
    "GB": ("Green Bay Packers", "Packers", "NFC North", "#203731", "#FFB612"),
    "HOU": ("Houston Texans", "Texans", "AFC South", "#03202F", "#A71930"),
    "IND": ("Indianapolis Colts", "Colts", "AFC South", "#002C5F", "#A2AAAD"),
    "JAX": ("Jacksonville Jaguars", "Jaguars", "AFC South", "#006778", "#D7A22A"),
    "KC": ("Kansas City Chiefs", "Chiefs", "AFC West", "#E31837", "#FFB81C"),
    "LA": ("Los Angeles Rams", "Rams", "NFC West", "#003594", "#FFA300"),
    "LAC": ("Los Angeles Chargers", "Chargers", "AFC West", "#0080C6", "#FFC20E"),
    "LV": ("Las Vegas Raiders", "Raiders", "AFC West", "#000000", "#A5ACAF"),
    "MIA": ("Miami Dolphins", "Dolphins", "AFC East", "#008E97", "#FC4C02"),
    "MIN": ("Minnesota Vikings", "Vikings", "NFC North", "#4F2683", "#FFC62F"),
    "NE": ("New England Patriots", "Patriots", "AFC East", "#002244", "#C60C30"),
    "NO": ("New Orleans Saints", "Saints", "NFC South", "#D3BC8D", "#101820"),
    "NYG": ("New York Giants", "Giants", "NFC East", "#0B2265", "#A71930"),
    "NYJ": ("New York Jets", "Jets", "AFC East", "#125740", "#000000"),
    "PHI": ("Philadelphia Eagles", "Eagles", "NFC East", "#004C54", "#A5ACAF"),
    "PIT": ("Pittsburgh Steelers", "Steelers", "AFC North", "#FFB612", "#101820"),
    "SEA": ("Seattle Seahawks", "Seahawks", "NFC West", "#002244", "#69BE28"),
    "SF": ("San Francisco 49ers", "49ers", "NFC West", "#AA0000", "#B3995D"),
    "TB": ("Tampa Bay Buccaneers", "Buccaneers", "NFC South", "#D50A0A", "#34302B"),
    "TEN": ("Tennessee Titans", "Titans", "AFC South", "#0C2340", "#4B92DB"),
    "WAS": ("Washington Commanders", "Commanders", "NFC East", "#5A1414", "#FFB612"),
}
FORMER = {"STL": ("LA", 2016, "St. Louis Rams"), "SD": ("LAC", 2017, "San Diego Chargers"), "OAK": ("LV", 2020, "Oakland Raiders")}
ALIASES = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "SL": "STL"}
# 1999-2001 had 31 then 32 teams in six divisions; the pre-2002 alignment
OLD_DIV = {
    "AFC East": ["BUF", "IND", "MIA", "NE", "NYJ"], "AFC Central": ["BAL", "CIN", "CLE", "JAX", "PIT", "TEN"],
    "AFC West": ["DEN", "KC", "OAK", "SD", "SEA"], "NFC East": ["ARI", "DAL", "NYG", "PHI", "WAS"],
    "NFC Central": ["CHI", "DET", "GB", "MIN", "TB"], "NFC West": ["ATL", "CAR", "NO", "SF", "STL"],
}
WASHINGTON = {2020: "Washington Football Team", 2021: "Washington Football Team"}


def franchise(abbr: Any) -> str | None:
    """The current abbreviation of a franchise (STL -> LA, SD -> LAC, OAK -> LV)."""
    if not isinstance(abbr, str) or not abbr:
        return None
    a = ALIASES.get(abbr.upper(), abbr.upper())
    return FORMER[a][0] if a in FORMER else a


def canon_abbr(abbr: Any, season: int) -> Any:
    """The abbreviation the franchise used in that season (nflverse spelling)."""
    if not isinstance(abbr, str) or not abbr:
        return abbr
    a = franchise(abbr)
    for old, (new, since, _) in FORMER.items():
        if a == new and int(season) < since:
            return old
    return a


def info(abbr: str, season: int) -> dict:
    a = franchise(abbr) or abbr
    name, short, divn, col, alt = TEAMS.get(a, (abbr, abbr, None, "#555555", "#999999"))
    if abbr in FORMER and int(season) < FORMER[abbr][1]:
        name = FORMER[abbr][2]
    if a == "WAS":
        name = WASHINGTON.get(int(season), "Washington Redskins" if int(season) < 2020 else name)
    if int(season) < 2002:
        divn = next((d for d, mem in OLD_DIV.items() if abbr in mem or a in mem), divn)
        if a == "HOU":
            divn = None
    conf = divn.split()[0] if divn else None
    return {"abbr": abbr, "name": name, "short": short, "division": divn, "conference": conf, "colour": col, "alt": alt,
            "franchise": a}


def season_teams(season: int, store_teams: dict | None = None) -> dict[str, dict]:
    """{abbr: {abbr,name,short,division,conference,colour,alt,franchise}} for the season: canon / store fields over
    this table."""
    s = int(season)
    out: dict[str, dict] = {}
    abbrs = [canon_abbr(a, s) for a in TEAMS]
    if s < 2002:
        abbrs = [a for a in abbrs if a != "HOU"]
    canon_t: dict = {}
    try:
        from oddsmarkets.nfl import canon
        for fn in ("teams_for_season", "teams", "season_teams"):
            f = getattr(canon, fn, None)
            if callable(f):
                try:
                    r = f(s)
                except TypeError:
                    continue
                if isinstance(r, dict) and r:
                    canon_t = r
                    break
    except Exception:                                            # noqa: BLE001
        canon_t = {}
    for a in set(abbrs) | set((store_teams or {}).keys()) | set(canon_t.keys()):
        base = info(a, s)
        for src in (canon_t.get(a), (store_teams or {}).get(a)):
            if isinstance(src, dict):
                alias = {"colour": "color", "alt": "alt_colour", "division": "div", "conference": "conf"}
                for k in ("name", "short", "division", "conference", "colour", "alt"):
                    v = src.get(k) or src.get(alias.get(k, k))
                    if v:
                        base[k] = v
        if base.get("division") and not base.get("conference"):
            base["conference"] = str(base["division"]).split()[0]
        out[a] = base
    return out
