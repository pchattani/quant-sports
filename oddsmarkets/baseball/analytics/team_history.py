"""
data/mlb/team_history.json: the clubs' history for Standings > History (round 9, 28 Oct 2026).

Seasons 1901 (the American League's first) to the Lahman Baseball Database's last year come from its Teams.csv (SABR,
CC BY-SA 3.0; American and National League rows only: the other leagues it now carries are not part of these tables);
later seasons from our own season stores (season.json standings and the postseason as played). Nothing is fetched here:
the file is cached under <cache>/lahman/ by sources/lahman.py, and its AL / NL rows from 1901 are committed beside this
module (lahman_teams_al_nl.csv.gz, 30 KB) so a machine without the cache builds the same file.

{"ok", "updated_at", "first", "last", "lahman_last", "sources",
 "franchises": {fid: {tid, name, abbr, first, last, seasons, w, l, pct, titles, pennants, postseason, last_title, best}},
 "champions": [{season, fid, tid, name, abbr (that season's), w, l, opp: {fid, tid, name, abbr, w, l}}]  (World Series winners from 1903; none in 1904
   or 1994),
 "pennants": {season: {AL: fid, NL: fid}},
 "best": [team-season], "worst": [team-season]  (win %, seasons of 100+ games), "best_rd": [team-season] (run differential
   a game), team-season = {season, fid, tid, name, lg, w, l, pct, rs, ra, rdg, champion, pennant},
 "droughts": [{fid, tid, name, last_title, years}] (the current 30 clubs, longest first),
 "records": [{key, label, value, fmt, season, fid, tid, name}]}
"""
from __future__ import annotations

import logging
from pathlib import Path

from oddsmarkets.baseball import analytics as an

logger = logging.getLogger(__name__)

FIRST = 1901
# Lahman franchID -> our MLB team id (the current 30 clubs)
FRANCH_TID = {"ARI": "109", "OAK": "133", "ATL": "144", "BAL": "110", "BOS": "111", "CHW": "145", "CHC": "112", "CIN": "113",
              "CLE": "114", "COL": "115", "DET": "116", "HOU": "117", "KCR": "118", "ANA": "108", "LAD": "119", "FLA": "146",
              "MIL": "158", "MIN": "142", "NYY": "147", "NYM": "121", "PHI": "143", "PIT": "134", "SDP": "135", "SEA": "136",
              "SFG": "137", "STL": "138", "TBD": "139", "TEX": "140", "TOR": "141", "WSN": "120"}
TID_FRANCH = {v: k for k, v in FRANCH_TID.items()}
# Baseball-Reference codes that MLB writes differently (the site uses MLB's)
BR_ABBR = {"CHW": "CWS", "KCR": "KC", "SDP": "SD", "SFG": "SF", "TBR": "TB", "TBD": "TB", "WSN": "WSH", "ARI": "AZ"}


COPY = Path(__file__).with_name("lahman_teams_al_nl.csv.gz")   # the AL / NL rows from 1901, committed (CC BY-SA 3.0)


def _rows_lahman() -> list[dict] | None:
    """Teams.csv from the Lahman cache when it is on this machine, else the committed AL / NL copy (so CI, which may not
    hold the cache, builds the same file); whichever reaches the later season."""
    import pandas as pd
    df = None
    try:
        from oddsmarkets.baseball.sources import lahman
        df = lahman.load("Teams.csv")
    except Exception as exc:                                     # noqa: BLE001
        logger.info("Lahman Teams.csv cache unavailable: %s", exc)
    try:
        cp = pd.read_csv(COPY) if COPY.exists() else None
    except Exception:                                            # noqa: BLE001
        cp = None
    if df is None or not len(df) or (cp is not None and int(cp["yearID"].max()) > int(df["yearID"].max())):
        df = cp
    if df is None or not len(df):
        return None
    df = df[(df["yearID"] >= FIRST) & (df["lgID"].isin(["AL", "NL"]))]
    out = []
    for r in df.to_dict("records"):
        fid = str(r.get("franchID"))
        out.append({"season": int(r["yearID"]), "fid": fid, "tid": FRANCH_TID.get(fid), "name": str(r.get("name") or fid),
                    "abbr": BR_ABBR.get(str(r.get("teamIDBR")), str(r.get("teamIDBR") or r.get("teamID") or fid)), "lg": str(r["lgID"]), "g": an.inum(r.get("G")) or 0,
                    "w": an.inum(r.get("W")) or 0, "l": an.inum(r.get("L")) or 0, "rs": an.inum(r.get("R")), "ra": an.inum(r.get("RA")),
                    "ws": str(r.get("WSWin") or "") == "Y", "pennant": str(r.get("LgWin") or "") == "Y",
                    "post": any(str(r.get(k) or "") == "Y" for k in ("DivWin", "WCWin", "LgWin"))})
    return out


def _rows_store(season: int) -> list[dict]:
    """A finished season after Lahman's last year, from our season.json (standings rows and the postseason as played)."""
    d = an.read_json(an.data_root() / "mlb" / str(season) / "season.json") if hasattr(an, "data_root") else None
    if not isinstance(d, dict) or not d.get("standings"):
        return []
    post = d.get("postseason") or {}
    pt = post.get("teams") or {}
    champ = post.get("champion") if post.get("complete") else None
    ws = next((s for s in (post.get("series") or []) if s.get("round") == "WS"), None)
    finalists = set(map(str, (ws or {}).get("teams") or [])) if ws and ws.get("done") else set()
    out = []
    for rows in d["standings"].values():
        for r in rows:
            t = str(r.get("tid"))
            fid = TID_FRANCH.get(t)
            if not fid:
                continue
            out.append({"season": season, "fid": fid, "tid": t, "name": r.get("name") or fid, "abbr": r.get("abbr") or fid,
                        "lg": r.get("league") or "", "g": (r.get("w") or 0) + (r.get("l") or 0), "w": r.get("w") or 0, "l": r.get("l") or 0,
                        "rs": r.get("rs"), "ra": r.get("ra"), "ws": t == champ, "pennant": t in finalists, "post": t in pt})
    return out


def _complete(season: int) -> bool:
    d = an.read_json(an.data_root() / "mlb" / str(season) / "season.json") if hasattr(an, "data_root") else None
    p = (d or {}).get("postseason") or {}
    if p.get("actual"):
        return bool(p.get("complete"))
    return str((d or {}).get("phase") or "") in ("offseason", "complete") and bool(p)


def build(extra_seasons: list[int] | None = None) -> dict | None:
    rows = _rows_lahman()
    if rows is None:
        return None
    lahman_last = max(r["season"] for r in rows)
    for s in sorted(extra_seasons or []):
        if s > lahman_last and _complete(s):
            rows += _rows_store(s)
    last = max(r["season"] for r in rows)
    for r in rows:
        g = r["w"] + r["l"]
        r["pct"] = round(r["w"] / g, 4) if g else None
        r["rdg"] = round((r["rs"] - r["ra"]) / g, 3) if g and r["rs"] is not None and r["ra"] is not None else None
    by_season: dict[int, list] = {}
    for r in rows:
        by_season.setdefault(r["season"], []).append(r)
    latest = {}
    for r in sorted(rows, key=lambda x: x["season"]):
        latest[r["fid"]] = r
    champions, pennants = [], {}
    for s in sorted(by_season):
        lst = by_season[s]
        pn = {r["lg"]: r for r in lst if r["pennant"]}
        if pn:
            pennants[str(s)] = {lg: r["fid"] for lg, r in pn.items()}
        w = next((r for r in lst if r["ws"]), None)
        if w:
            o = next((r for lg, r in pn.items() if r["fid"] != w["fid"]), None)
            champions.append({"season": s, "fid": w["fid"], "tid": w["tid"], "name": w["name"], "abbr": w["abbr"], "w": w["w"], "l": w["l"],
                              "opp": {"fid": o["fid"], "tid": o["tid"], "name": o["name"], "abbr": o["abbr"], "w": o["w"], "l": o["l"]} if o else None})
    fr: dict[str, dict] = {}
    for r in rows:
        f = fr.setdefault(r["fid"], {"tid": r["tid"], "first": r["season"], "last": r["season"], "seasons": 0, "w": 0, "l": 0,
                                     "titles": 0, "pennants": 0, "postseason": 0, "last_title": None, "best": None})
        f["first"], f["last"] = min(f["first"], r["season"]), max(f["last"], r["season"])
        f["seasons"] += 1
        f["w"] += r["w"]
        f["l"] += r["l"]
        f["titles"] += int(r["ws"])
        f["pennants"] += int(r["pennant"])
        f["postseason"] += int(r["post"] or r["ws"] or r["pennant"])
        if r["ws"]:
            f["last_title"] = max(f["last_title"] or 0, r["season"])
        if r["g"] >= 100 and (f["best"] is None or (r["pct"] or 0) > f["best"]["pct"]):
            f["best"] = {"season": r["season"], "w": r["w"], "l": r["l"], "pct": r["pct"]}
    for fid, f in fr.items():
        f["name"], f["abbr"] = latest[fid]["name"], latest[fid]["abbr"]
        f["pct"] = round(f["w"] / max(f["w"] + f["l"], 1), 4)

    def ts(r):
        return {k: r[k] for k in ("season", "fid", "tid", "name", "abbr", "lg", "w", "l", "pct", "rs", "ra", "rdg")} | {"champion": r["ws"], "pennant": r["pennant"]}
    full = [r for r in rows if r["g"] >= 100 and r["pct"] is not None]
    best = sorted(full, key=lambda r: (-r["pct"], -r["w"]))[:25]
    worst = sorted(full, key=lambda r: (r["pct"], r["w"]))[:15]
    best_rd = sorted((r for r in full if r["rdg"] is not None), key=lambda r: -r["rdg"])[:15]
    droughts = []
    for fid, tid in FRANCH_TID.items():
        f = fr.get(fid)
        if not f:
            continue
        lt = f["last_title"]
        droughts.append({"fid": fid, "tid": tid, "name": f["name"], "last_title": lt, "first": f["first"],
                         "years": last - (lt if lt else f["first"] - 1)})
    droughts.sort(key=lambda x: -x["years"])
    records = []

    def rec(key, label, r, value, fmt, tied=None):
        x = {"key": key, "label": label, "value": value, "fmt": fmt, "season": r["season"], "fid": r["fid"], "tid": r["tid"], "name": r["name"]}
        also = [{"season": t["season"], "fid": t["fid"], "tid": t["tid"], "name": t["name"]} for t in (tied or []) if t is not r]
        if also:
            x["also"] = also
        records.append(x)
    g162 = [r for r in full if r["g"] >= 154]
    if g162:
        r = max(g162, key=lambda r: (r["w"], r["pct"]))
        rec("most_w", "Most wins in a season", r, r["w"], "int", [x for x in g162 if x["w"] == r["w"]])
        r = max(full, key=lambda r: r["pct"])
        rec("best_pct", "Best winning percentage", r, r["pct"], "pct3")
        r = min(g162, key=lambda r: (r["w"], -r["l"]))
        rec("fewest_w", "Fewest wins in a full season", r, r["w"], "int")
        r = max((x for x in g162 if x["rs"] is not None), key=lambda r: r["rs"])
        rec("most_rs", "Most runs scored", r, r["rs"], "int")
        r = min((x for x in full if x["ra"] is not None and x["season"] >= 1920), key=lambda r: r["ra"] / max(r["g"], 1))
        rec("fewest_ra", "Fewest runs allowed a game (live-ball era)", r, round(r["ra"] / max(r["w"] + r["l"], 1), 2), "num2")
        r = max((x for x in full if x["rdg"] is not None), key=lambda r: r["rdg"])
        rec("best_rd", "Best run differential a game", r, r["rdg"], "signed2")
    top = max(fr.items(), key=lambda kv: (kv[1]["titles"], kv[1]["pennants"]))
    records.append({"key": "most_titles", "label": "Most World Series titles", "value": top[1]["titles"], "fmt": "int", "season": None,
                    "fid": top[0], "tid": top[1]["tid"], "name": top[1]["name"]})
    if droughts:
        d0 = droughts[0]
        records.append({"key": "drought", "label": "Longest title drought (active)", "value": d0["years"], "fmt": "int",
                        "season": d0["last_title"], "fid": d0["fid"], "tid": d0["tid"], "name": d0["name"]})
    return {"ok": True, "updated_at": an.now(), "first": FIRST, "last": last, "lahman_last": lahman_last,
            "sources": {"lahman": "Season totals " + str(FIRST) + "-" + str(lahman_last) + " from the Lahman Baseball Database (SABR), "
                        "licensed under Creative Commons Attribution-ShareAlike 3.0.",
                        "ours": "Later seasons from our own standings and the postseason as played (MLB Stats API)."},
            "franchises": fr, "champions": champions, "pennants": pennants,
            "best": [ts(r) for r in best], "worst": [ts(r) for r in worst], "best_rd": [ts(r) for r in best_rd],
            "droughts": droughts, "records": records}
