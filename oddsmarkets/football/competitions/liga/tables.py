"""
The Argentine tables that span more than one tournament: the Tabla Anual and the promedios, with the
official versions Sofascore publishes beside them.

    official_table(store, "anual" | "promedios")   Sofascore's own table for the season (store["standings"],
                                                   one standings call the fetcher makes a few times a day from
                                                   its own budget), keyed by our club names
    promedio_prior(store, past, year)               each club's (points, matches) over the seasons before this
                                                   one in the promedio window, and where they came from
    compare(ours, official)                        how our table differs from the official one

Everything is computed from match results; the official tables are a check (and the promedio prior when they
exist: the 2024 Copa de la Liga that the 2026 promedios still count is not in our stores). Validated on 2025:
our Tabla Anual from the Apertura and Clausura 2025 results equals Sofascore's "Anual 2025" table for all 30
clubs, positions, points and matches (tiebreaks: points, goal difference, goals for).
"""
from __future__ import annotations

import re
from typing import Any

from oddsmarkets.football.sources.teams import normalize_team_name

REGISTRY = "liga_argentina"
FINISHED = {"finished", "ended", "afterpenalties", "afterextratime", "ap", "aet"}

# How the 2026 promedio window is made up (AFA): the current season and the two before it, zone-phase points only.
# 2024 also had the Copa de la Liga (14 matches a club), a separate Sofascore tournament our stores do not hold.
MISSING_PRIOR_NOTE = ("Promedio history from our results: the 2024 Liga Profesional and both 2025 tournaments. "
                      "The 2024 Copa de la Liga (14 matches a club) is not in our data, so the promedios are "
                      "approximate until Sofascore's own promedios table arrives with the next refresh.")


def team_names_by_id(store: dict[str, Any]) -> dict[int, str]:
    """Sofascore team id -> our club name, from the store's fixtures (the ids never change; names are spelled
    differently in standings blocks, e.g. "CA Lanús" against "Lanús")."""
    out: dict[int, str] = {}
    for raw in (store.get("matches") or {}).values():
        for side, key in (("home", "home_id"), ("away", "away_id")):
            if raw.get(key) and raw.get(side):
                out.setdefault(int(raw[key]), normalize_team_name(str(raw[side]), REGISTRY))
    return out


def _block(store: dict[str, Any], kind: str) -> dict | None:
    blocks = ((store.get("standings") or {}).get("blocks")) or []
    pat = re.compile(r"^\s*(anual|annual)" if kind == "anual" else r"^\s*promedio", re.I)
    for b in blocks:
        if isinstance(b, dict) and pat.search(str(b.get("name") or "")):
            return b
    return None


def official_table(store: dict[str, Any], kind: str) -> dict[str, dict] | None:
    """Sofascore's "Anual <year>" or "Promedios <year>" table as {club: {position, points, matches}}, or None
    when the store holds no such block. Clubs are matched by Sofascore id, then by name."""
    block = _block(store, kind)
    if not block:
        return None
    by_id = team_names_by_id(store)
    out: dict[str, dict] = {}
    for r in block.get("rows") or []:
        tid = r.get("team_id")
        name = by_id.get(int(tid)) if tid is not None and int(tid) in by_id else normalize_team_name(str(r.get("team") or ""), REGISTRY)
        if not name:
            continue
        out[name] = {"position": r.get("position"), "points": r.get("points"), "matches": r.get("matches")}
    return out or None


def official_meta(store: dict[str, Any]) -> dict:
    s = store.get("standings") or {}
    return {"at": s.get("at"), "season_id": s.get("season_id"),
            "blocks": [b.get("name") for b in s.get("blocks") or [] if isinstance(b, dict)]}


def results_prior(past: dict[str, Any] | None, store: dict[str, Any], year: int, n_seasons: int = 3) -> dict[str, tuple[int, int]]:
    """(points, matches) per club over the league seasons of the `n_seasons - 1` years before `year`, zone or
    league phase only, from the past-results store (docs/site/data/past/store.json, "liga-argentina")."""
    by_id = team_names_by_id(store)
    years = {str(y) for y in range(year - n_seasons + 1, year)}
    acc: dict[str, list[int]] = {}
    for season in (past or {}).values():
        if not isinstance(season, dict) or str(season.get("year")) not in years:
            continue
        for m in (season.get("matches") or {}).values():
            if m.get("stage", "league") != "league" or str(m.get("status") or "").lower() not in FINISHED:
                continue
            if m.get("hs") is None or m.get("as") is None or m.get("superseded_by"):
                continue
            hs, as_ = int(m["hs"]), int(m["as"])
            if hs < 0 or as_ < 0:
                continue
            for side, key, gf, ga in (("home", "home_id", hs, as_), ("away", "away_id", as_, hs)):
                tid = m.get(key)
                name = by_id.get(int(tid)) if tid is not None and int(tid) in by_id else normalize_team_name(str(m.get(side) or ""), REGISTRY)
                a = acc.setdefault(name, [0, 0])
                a[0] += 3 if gf > ga else 1 if gf == ga else 0
                a[1] += 1
    return {t: (v[0], v[1]) for t, v in acc.items()}


def previous_rank(past: dict[str, Any] | None, store: dict[str, Any], teams: list[str], year: int) -> dict[str, int]:
    """Last year's Tabla Anual order from its results ({club: rank}, 1 = top), the clubs not in it (promoted)
    after it in name order: the Elo seed, as the leagues seed from last season's table. Empty without data."""
    by_id = team_names_by_id(store)
    acc: dict[str, list[int]] = {}
    for season in (past or {}).values():
        if not isinstance(season, dict) or str(season.get("year")) != str(year - 1):
            continue
        for m in (season.get("matches") or {}).values():
            if m.get("stage", "league") != "league" or str(m.get("status") or "").lower() not in FINISHED:
                continue
            if m.get("hs") is None or m.get("as") is None or int(m["hs"]) < 0 or int(m["as"]) < 0:
                continue
            hs, as_ = int(m["hs"]), int(m["as"])
            for side, key, gf, ga in (("home", "home_id", hs, as_), ("away", "away_id", as_, hs)):
                tid = m.get(key)
                name = by_id.get(int(tid)) if tid is not None and int(tid) in by_id else normalize_team_name(str(m.get(side) or ""), REGISTRY)
                a = acc.setdefault(name, [0, 0, 0])
                a[0] += 3 if gf > ga else 1 if gf == ga else 0
                a[1] += gf - ga
                a[2] += gf
    if not acc:
        return {}
    order = sorted(acc, key=lambda t: (-acc[t][0], -acc[t][1], -acc[t][2], t))
    order = [t for t in order if t in set(teams)] + sorted(t for t in teams if t not in acc)
    return {t: i for i, t in enumerate(order, start=1)}


def promedio_prior(store: dict[str, Any], past: dict[str, Any] | None, year: int,
                   n_seasons: int = 3) -> tuple[dict[str, tuple[int, int]], dict]:
    """
    Each club's promedio points and matches before this season: ({club: (points, matches)}, info).

    With Sofascore's promedios and Tabla Anual tables in the store the prior is the one minus the other, which is
    exact (it carries the 2024 Copa de la Liga); otherwise it is the past seasons' results, short of that cup
    (info["source"] says which).
    """
    official = official_table(store, "promedios")
    anual = official_table(store, "anual")
    if official and anual:
        # Both tables come from the same answer, so promedios minus the Tabla Anual is the history before
        # this season exactly, whenever the call was made; this season is then ours, up to the minute.
        prior: dict[str, tuple[int, int]] = {}
        bad = []
        for team, row in official.items():
            a = anual.get(team)
            if a is None:
                bad.append(team)
                continue
            pts = int(row.get("points") or 0) - int(a.get("points") or 0)
            mp = int(row.get("matches") or 0) - int(a.get("matches") or 0)
            if pts < 0 or mp < 0:
                bad.append(team)
                continue
            prior[team] = (pts, mp)
        if not bad:
            return prior, {"source": "sofascore", "note": "Promedio history from Sofascore's promedios table "
                           "(its Tabla Anual taken out); this season is our own results.", **official_meta(store)}
    prior = results_prior(past, store, year, n_seasons)
    return prior, {"source": "results", "note": MISSING_PRIOR_NOTE,
                   "seasons": sorted({str(s.get("year")) for s in (past or {}).values() if isinstance(s, dict)
                                      and str(s.get("year")) in {str(y) for y in range(year - n_seasons + 1, year)}})}


def compare(ours: list[tuple[str, Any]], official: dict[str, dict] | None) -> dict | None:
    """Our ordered table against the official one: {"clubs", "same_position", "same_points", "same_matches",
    "diffs": [...]}; None without an official table."""
    if not official:
        return None
    diffs = []
    same_pos = same_pts = same_mp = 0
    for i, (team, rec) in enumerate(ours, start=1):
        o = official.get(team)
        if not o:
            diffs.append({"team": team, "ours": [i, rec.points, rec.played], "official": None})
            continue
        sp, spt, smp = o.get("position") == i, o.get("points") == rec.points, o.get("matches") == rec.played
        same_pos += sp
        same_pts += spt
        same_mp += smp
        if not (sp and spt and smp):
            diffs.append({"team": team, "ours": [i, rec.points, rec.played],
                          "official": [o.get("position"), o.get("points"), o.get("matches")]})
    return {"clubs": len(ours), "same_position": same_pos, "same_points": same_pts, "same_matches": same_mp,
            "diffs": diffs[:30]}
