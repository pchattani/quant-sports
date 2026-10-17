"""
history.json: Stanley Cup champions since the NHL's first season (1917-18), season leaders, and the seasons list.

Champions: the playoff series in the season stores decide the seasons on disk (2009-10 onward: champion and
finalist from the final series); earlier seasons come from the `CUP` table below (the Stanley Cup winners as
engraved, NHL era; 1919 not awarded (influenza), 1925 won by the WCHL's Victoria Cougars, 2005 not awarded
(lockout)). Season leaders: from each season's catalogues on disk (points, goals, ixG, GSAx, Rink value), else
builder A's stats REST season reports (points, goals, assists, save %).
"""
from __future__ import annotations

import gzip
import json

from oddsmarkets.nhl import analytics as an

# end year -> (champion, finalist or None)
CUP: dict[int, tuple[str | None, str | None]] = {
    1918: ("Toronto Arenas", "Vancouver Millionaires"), 1919: (None, None), 1920: ("Ottawa Senators", "Seattle Metropolitans"),
    1921: ("Ottawa Senators", "Vancouver Millionaires"), 1922: ("Toronto St. Patricks", "Vancouver Millionaires"),
    1923: ("Ottawa Senators", "Edmonton Eskimos"), 1924: ("Montreal Canadiens", "Calgary Tigers"),
    1925: ("Victoria Cougars", "Montreal Canadiens"), 1926: ("Montreal Maroons", "Victoria Cougars"),
    1927: ("Ottawa Senators", "Boston Bruins"), 1928: ("New York Rangers", "Montreal Maroons"), 1929: ("Boston Bruins", "New York Rangers"),
    1930: ("Montreal Canadiens", "Boston Bruins"), 1931: ("Montreal Canadiens", "Chicago Black Hawks"),
    1932: ("Toronto Maple Leafs", "New York Rangers"), 1933: ("New York Rangers", "Toronto Maple Leafs"),
    1934: ("Chicago Black Hawks", "Detroit Red Wings"), 1935: ("Montreal Maroons", "Toronto Maple Leafs"),
    1936: ("Detroit Red Wings", "Toronto Maple Leafs"), 1937: ("Detroit Red Wings", "New York Rangers"),
    1938: ("Chicago Black Hawks", "Toronto Maple Leafs"), 1939: ("Boston Bruins", "Toronto Maple Leafs"),
    1940: ("New York Rangers", "Toronto Maple Leafs"), 1941: ("Boston Bruins", "Detroit Red Wings"),
    1942: ("Toronto Maple Leafs", "Detroit Red Wings"), 1943: ("Detroit Red Wings", "Boston Bruins"),
    1944: ("Montreal Canadiens", "Chicago Black Hawks"), 1945: ("Toronto Maple Leafs", "Detroit Red Wings"),
    1946: ("Montreal Canadiens", "Boston Bruins"), 1947: ("Toronto Maple Leafs", "Montreal Canadiens"),
    1948: ("Toronto Maple Leafs", "Detroit Red Wings"), 1949: ("Toronto Maple Leafs", "Detroit Red Wings"),
    1950: ("Detroit Red Wings", "New York Rangers"), 1951: ("Toronto Maple Leafs", "Montreal Canadiens"),
    1952: ("Detroit Red Wings", "Montreal Canadiens"), 1953: ("Montreal Canadiens", "Boston Bruins"),
    1954: ("Detroit Red Wings", "Montreal Canadiens"), 1955: ("Detroit Red Wings", "Montreal Canadiens"),
    1956: ("Montreal Canadiens", "Detroit Red Wings"), 1957: ("Montreal Canadiens", "Boston Bruins"),
    1958: ("Montreal Canadiens", "Boston Bruins"), 1959: ("Montreal Canadiens", "Toronto Maple Leafs"),
    1960: ("Montreal Canadiens", "Toronto Maple Leafs"), 1961: ("Chicago Black Hawks", "Detroit Red Wings"),
    1962: ("Toronto Maple Leafs", "Chicago Black Hawks"), 1963: ("Toronto Maple Leafs", "Detroit Red Wings"),
    1964: ("Toronto Maple Leafs", "Detroit Red Wings"), 1965: ("Montreal Canadiens", "Chicago Black Hawks"),
    1966: ("Montreal Canadiens", "Detroit Red Wings"), 1967: ("Toronto Maple Leafs", "Montreal Canadiens"),
    1968: ("Montreal Canadiens", "St. Louis Blues"), 1969: ("Montreal Canadiens", "St. Louis Blues"),
    1970: ("Boston Bruins", "St. Louis Blues"), 1971: ("Montreal Canadiens", "Chicago Black Hawks"),
    1972: ("Boston Bruins", "New York Rangers"), 1973: ("Montreal Canadiens", "Chicago Black Hawks"),
    1974: ("Philadelphia Flyers", "Boston Bruins"), 1975: ("Philadelphia Flyers", "Buffalo Sabres"),
    1976: ("Montreal Canadiens", "Philadelphia Flyers"), 1977: ("Montreal Canadiens", "Boston Bruins"),
    1978: ("Montreal Canadiens", "Boston Bruins"), 1979: ("Montreal Canadiens", "New York Rangers"),
    1980: ("New York Islanders", "Philadelphia Flyers"), 1981: ("New York Islanders", "Minnesota North Stars"),
    1982: ("New York Islanders", "Vancouver Canucks"), 1983: ("New York Islanders", "Edmonton Oilers"),
    1984: ("Edmonton Oilers", "New York Islanders"), 1985: ("Edmonton Oilers", "Philadelphia Flyers"),
    1986: ("Montreal Canadiens", "Calgary Flames"), 1987: ("Edmonton Oilers", "Philadelphia Flyers"),
    1988: ("Edmonton Oilers", "Boston Bruins"), 1989: ("Calgary Flames", "Montreal Canadiens"),
    1990: ("Edmonton Oilers", "Boston Bruins"), 1991: ("Pittsburgh Penguins", "Minnesota North Stars"),
    1992: ("Pittsburgh Penguins", "Chicago Blackhawks"), 1993: ("Montreal Canadiens", "Los Angeles Kings"),
    1994: ("New York Rangers", "Vancouver Canucks"), 1995: ("New Jersey Devils", "Detroit Red Wings"),
    1996: ("Colorado Avalanche", "Florida Panthers"), 1997: ("Detroit Red Wings", "Philadelphia Flyers"),
    1998: ("Detroit Red Wings", "Washington Capitals"), 1999: ("Dallas Stars", "Buffalo Sabres"),
    2000: ("New Jersey Devils", "Dallas Stars"), 2001: ("Colorado Avalanche", "New Jersey Devils"),
    2002: ("Detroit Red Wings", "Carolina Hurricanes"), 2003: ("New Jersey Devils", "Mighty Ducks of Anaheim"),
    2004: ("Tampa Bay Lightning", "Calgary Flames"), 2005: (None, None), 2006: ("Carolina Hurricanes", "Edmonton Oilers"),
    2007: ("Anaheim Ducks", "Ottawa Senators"), 2008: ("Detroit Red Wings", "Pittsburgh Penguins"),
    2009: ("Pittsburgh Penguins", "Detroit Red Wings"), 2010: ("Chicago Blackhawks", "Philadelphia Flyers"),
    2011: ("Boston Bruins", "Vancouver Canucks"), 2012: ("Los Angeles Kings", "New Jersey Devils"),
    2013: ("Chicago Blackhawks", "Boston Bruins"), 2014: ("Los Angeles Kings", "New York Rangers"),
    2015: ("Chicago Blackhawks", "Tampa Bay Lightning"), 2016: ("Pittsburgh Penguins", "San Jose Sharks"),
    2017: ("Pittsburgh Penguins", "Nashville Predators"), 2018: ("Washington Capitals", "Vegas Golden Knights"),
    2019: ("St. Louis Blues", "Boston Bruins"), 2020: ("Tampa Bay Lightning", "Dallas Stars"),
    2021: ("Tampa Bay Lightning", "Montreal Canadiens"), 2022: ("Colorado Avalanche", "Tampa Bay Lightning"),
    2023: ("Vegas Golden Knights", "Florida Panthers"), 2024: ("Florida Panthers", "Edmonton Oilers"),
    2025: ("Florida Panthers", "Edmonton Oilers"),
}
NOTES = {1919: "Not awarded: the final was abandoned during the influenza pandemic.",
         1925: "Won by the Victoria Cougars of the Western Canada Hockey League.",
         2005: "Not awarded: the 2004-05 season was cancelled by the lockout."}
LEADER_KEYS_S = (("p", "Points"), ("g", "Goals"), ("ixg", "ixG"), ("gar", "Rink value (GAR)"), ("xgf_pct", "5v5 xGF%"))
LEADER_KEYS_G = (("gsax", "GSAx"), ("sv_pct", "Save %"), ("w", "Wins"))


def _stats_rows(season: int, report: str) -> list[dict]:
    p = an.raw_root() / "stats" / str(season) / f"{report}.json.gz"
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, list) else []
    except (OSError, ValueError, EOFError):
        return []


def seasons_list() -> list[dict]:
    """Every NHL season from builder A's cached stats REST season list (start / end dates, games)."""
    d = an.read_json(an.cache_root() / "stats_seasons.json") or {}
    out = []
    for k, v in sorted((d.get("seasons") or {}).items()):
        out.append({"season": int(k), "label": an.season_label(int(k)), "start": v.get("start"), "end": v.get("end"),
                    "games": v.get("total_regular") or v.get("games")})
    return out


def season_leaders(season: int, cat_s: dict | None, cat_g: dict | None) -> dict:
    out = {}
    for src, keys in ((cat_s, LEADER_KEYS_S), (cat_g, LEADER_KEYS_G)):
        P = (src or {}).get("players") or {}
        mets = {m["key"]: m for m in (src or {}).get("metrics") or []}
        for k, label in keys:
            if k not in mets:
                continue
            qual_only = k in ("xgf_pct", "sv_pct")
            c = [(p, r["values"].get(k), r) for p, r in P.items() if r["values"].get(k) is not None and (r.get("qualified") or not qual_only)]
            if not c:
                continue
            c.sort(key=lambda x: x[1], reverse=not mets[k].get("lower"))
            p, v, r = c[0]
            out[k] = {"label": label, "id": p, "name": r.get("name"), "team": r.get("team"), "value": v}
    if out:
        return out
    # stats REST season reports
    rows = _stats_rows(season, "skater_summary_2")
    for k, col, label in (("p", "points", "Points"), ("g", "goals", "Goals"), ("a", "assists", "Assists")):
        c = [r for r in rows if an.fnum(r.get(col)) is not None]
        if c:
            r = max(c, key=lambda x: an.fnum(x.get(col)))
            out[k] = {"label": label, "id": an.sid(r.get("playerId")), "name": r.get("skaterFullName"),
                      "team": (str(r.get("teamAbbrevs") or "").split(",")[-1].strip() or None), "value": an.fnum(r.get(col))}
    g = [r for r in _stats_rows(season, "goalie_summary_2") if (an.fnum(r.get("gamesPlayed")) or 0) >= 25]
    if g:
        r = max(g, key=lambda x: an.fnum(x.get("savePct")) or 0)
        out["sv_pct"] = {"label": "Save %", "id": an.sid(r.get("playerId")), "name": r.get("goalieFullName"),
                         "team": (str(r.get("teamAbbrevs") or "").split(",")[-1].strip() or None), "value": an.fnum(r.get("savePct"))}
    return out


def league_summary(ctx, T: dict | None) -> dict:
    """The season's scoring environment: goals, shots and xG per team-game, save % (empty nets out), shooting %,
    power-play % and penalty-kill % (the stats REST team summary when on disk, else from the events), penalties per
    team-game; regular season."""
    games = [g for g in ctx.games.values() if g.get("gtype") == "REG" and g.get("status") == "final" and g.get("hs") is not None]
    out = {"season": ctx.season, "label": an.season_label(ctx.season), "games": len(games)}
    if games:
        goals = sum(int(g["hs"]) + int(g["as"]) - (1 if g.get("so") else 0) for g in games)
        out["goals_pg"] = round(goals / (2 * len(games)), 3)
        out["ot_share"] = round(sum(1 for g in games if g.get("ot") or g.get("so")) / len(games), 3)
        out["so_share"] = round(sum(1 for g in games if g.get("so")) / len(games), 3)
        out["home_win"] = round(sum(1 for g in games if g["hs"] > g["as"]) / len(games), 3)
    tg = (T or {}).get("tg")
    if tg is not None and len(tg):
        R = tg[tg["gt"] == "REG"]
        n = R["game_id"].nunique() * 2 or 1
        sf, gf = float(R["sf_all"].sum()), float(R["gf_all"].sum())
        en = float(R.get("gf_oth", 0).sum()) if "gf_oth" in R else 0.0
        out.update(shots_pg=round(sf / n, 2), xg_pg=round(float(R["xgf_all"].sum()) / n, 3), sh_pct=round(gf / sf, 4) if sf else None,
                   pen_pg=round(float(R["pen_taken"].sum()) / n, 2) if "pen_taken" in R else None)
        gg = (T or {}).get("gg")
        if gg is not None and len(gg):
            G = gg[gg["gt"] == "REG"]
            sa, ga = float(G["sa"].sum()), float(G["ga"].sum())
            out["sv_pct"] = round(1 - ga / sa, 4) if sa else None
            out["gsax_check"] = round(float(G["xga"].sum() - ga), 1)
        d, k = float(R.get("pen_drawn", 0).sum()), float(R.get("pen_taken", 0).sum())
        out["pp_pct"] = round(float(R["gf_PP"].sum()) / d, 4) if d else None
        out["pk_pct"] = round(1 - float(R["ga_SH"].sum()) / k, 4) if k else None
    rows = _stats_rows(ctx.season, "team_summary_2")
    if rows:
        w = [an.fnum(r.get("gamesPlayed")) or 0 for r in rows]
        tw = sum(w) or 1

        def avg(col):
            v = [(an.fnum(r.get(col)), x) for r, x in zip(rows, w) if an.fnum(r.get(col)) is not None]
            return round(sum(a * b for a, b in v) / sum(b for _, b in v), 4) if v and sum(b for _, b in v) else None
        out["pp_pct"] = avg("powerPlayPct") or out.get("pp_pct")
        out["pk_pct"] = avg("penaltyKillPct") or out.get("pk_pct")
        out.setdefault("shots_pg", avg("shotsForPerGame"))
        if out.get("goals_pg") is None:
            out["goals_pg"] = avg("goalsForPerGame")
        out["source"] = "nhl + events" if tg is not None and len(tg) else "nhl"
        del tw
    return out


def build(results: dict[int, dict], team_names: dict[str, str]) -> dict:
    """results: {season: {"champion": abbr | None, "finalist": abbr | None, "leaders": {...}}} for seasons on disk."""
    champs = []
    for y in sorted(CUP):
        c, f = CUP[y]
        champs.append({"season": an.season_id(y - 1), "label": an.season_label(an.season_id(y - 1)), "champion": c, "finalist": f,
                       "note": NOTES.get(y), "source": "table"})
    have = {r["season"]: r for r in champs}
    for s, r in sorted(results.items()):
        if not r.get("champion"):
            continue
        row = have.get(s) or {"season": s, "label": an.season_label(s), "note": None}
        row.update({"champion": team_names.get(r["champion"], r["champion"]), "champion_abbr": r["champion"],
                    "finalist": team_names.get(r.get("finalist"), r.get("finalist")) if r.get("finalist") else row.get("finalist"),
                    "finalist_abbr": r.get("finalist"), "series": r.get("series"), "source": "store"})
        if s not in have:
            champs.append(row)
    champs.sort(key=lambda r: r["season"])
    counts: dict[str, int] = {}
    for r in champs:
        if r.get("champion") and r["champion"] != "Victoria Cougars":
            counts[r["champion"]] = counts.get(r["champion"], 0) + 1
    leaders = {str(s): r.get("leaders") for s, r in sorted(results.items()) if r.get("leaders")}
    league = [r["league"] for s, r in sorted(results.items()) if r.get("league")]
    return {"ok": True, "updated_at": an.now(), "champions": champs, "titles": sorted(counts.items(), key=lambda x: -x[1]),
            "season_leaders": leaders, "league": league,
            "league_cols": ["season", "label", "games", "goals_pg", "shots_pg", "xg_pg", "sv_pct", "sh_pct", "pp_pct", "pk_pct", "pen_pg",
                            "ot_share", "so_share", "home_win"],
            "seasons": seasons_list(), "first_season": 19171918,
            "notes": "Champions before the seasons on disk from the engraved Stanley Cup record; from 2009-10 the final series in the "
                     "season stores."}
