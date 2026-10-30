"""
Season stores for college hockey (`mch` men, `wch` women): ESPN's results joined with College Hockey News.

    data/college/stores/<L>/<S>.json.gz      (private, like every Campus store; never published raw)

Shape (version 1):
    {"level", "season", "version", "built_at", "chn_used": bool,
     "teams": {tid: {"name", "short", "abbr", "espn_id", "chn_id", "chn_slug", "conf", "d1": bool}},
     "conferences": {cid: {"name", "short"}},
     "games": [GAME],                                   # every game with a Division I team, date order
     "polls": {...},                                    # ESPN's USCHO poll snapshots (current season)
     "chn": {"players": {pid: PLAYER}, "goalies": {pid: GOALIE}, "boxes": {gid: BOX}, "metrics": {gid: [...]},
             "rosters": {tid: [ROSTER_ROW]}, "coverage": {...}} | None}
GAME = {"id", "espn_id", "date" (UTC ISO; CHN-only games 23:00Z, "tba": true), "status" pre|in|post|postponed|canceled,
        "stype" reg|conf|ncaa|exh, "round", "region", "note", "home", "away", "neutral", "conf_game",
        "hs", "as", "ot" (overtime periods), "so" (shootout), "res" W|T|L (home, NCAA record: shootouts are ties),
        "venue", "att", "chn" {"box", "gd", "sh": [h, a], "pp": [[ppg, ppo] h, a], "pim": [h, a], "xg": [h, a],
        "per": [[h periods], [a periods]], "scorers": [h, a]} | absent}

Team ids are ESPN's school ids (the Campus convention; the same school id as its basketball team) wherever the
school is on ESPN, else "c<chn id>" (CHN-only teams), else "x:<name>" for non-Division-I opponents.

Everything from CHN sits under `chn` (and the per-game `chn` block). With CHN switched off (`sources/chn.py`
CHN_ENABLED=0) the store is built from ESPN alone: teams, results and the NCAA tournament still work; players,
box scores and shot data do not exist.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..sources import chn
from .. import store as cc_store
from . import espn as hk

logger = logging.getLogger(__name__)

VERSION = 1
LEVELS = ("mch", "wch")
FIRST = {"mch": 2006, "wch": 2006}
SEED = ("Boston-University", "10")

CONF_SHORT = {"Atlantic Hockey": "AHA", "Atlantic Hockey America": "AHA", "Big Ten": "B1G", "CCHA": "CCHA",
              "ECAC": "ECAC", "ECAC Hockey": "ECAC", "Hockey East": "HEA", "NCHC": "NCHC", "WCHA": "WCHA",
              "CHA": "CHA", "College Hockey America": "CHA", "Independent": "IND", "D-I Independent": "IND",
              "NEWHA": "NEWHA", "MAAC": "MAAC"}


def current_season(today: date | None = None) -> int:
    d = today or date.today()
    return d.year + 1 if d.month >= 8 else d.year


def store_path(level: str, season: int) -> Path:
    return cc_store.paths()["stores"] / level / f"{int(season)}.json.gz"


def load_store(level: str, season: int) -> dict | None:
    p = store_path(level, season)
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def save_store(level: str, season: int, st: dict) -> Path:
    return cc_store.write_gz(store_path(level, season), st)


def seasons_on_disk(level: str) -> list[int]:
    d = cc_store.paths()["stores"] / level
    if not d.exists():
        return []
    return sorted(int(p.name.split(".")[0]) for p in d.glob("*.json.gz") if p.name.split(".")[0].isdigit())


# ── names ──────────────────────────────────────────────────────────────────────────────────────────────────

ALIAS = {
    "mass lowell": "umass lowell", "massachusetts lowell": "umass lowell", "uml": "umass lowell",
    "connecticut": "uconn", "rensselaer": "rpi", "nebraska omaha": "omaha", "minnesota duluth": "minnesota duluth",
    "minn duluth": "minnesota duluth", "miami": "miami oh", "miami ohio": "miami oh", "lake superior": "lake superior state",
    "lk superior st": "lake superior state", "long island": "long island university", "liu": "long island university",
    "augustana": "augustana university sd", "augustana sd": "augustana university sd", "st thomas": "st thomas minnesota",
    "st thomas mn": "st thomas minnesota", "american intl": "american international", "aic": "american international",
    "alabama huntsville": "alabama huntsville", "uah": "alabama huntsville", "union": "union ny", "union college": "union ny",
    "assumption": "assumption college", "post": "post university", "saint anselm": "st anselm",
    "saint michaels": "saint michael s", "st michaels": "saint michael s", "st michael s": "saint michael s",
    "unh": "new hampshire", "bu": "boston university", "boston univ": "boston university", "bc": "boston college",
    "boston c": "boston college", "boston u": "boston university", "michigan st": "michigan state",
    "minnesota st": "minnesota state", "bemidji st": "bemidji state", "ferris st": "ferris state",
    "st cloud": "st cloud state", "st cloud st": "st cloud state", "northern mich": "northern michigan",
    "western mich": "western michigan", "colorado col": "colorado college", "arizona st": "arizona state",
    "penn st": "penn state", "ohio st": "ohio state", "wayne st": "wayne state", "alaska fairbanks": "alaska",
    "alaska anchorage": "alaska anchorage", "army west point": "army", "umass": "massachusetts",
    "franklin pierce": "franklin pierce", "st lawrence": "st lawrence", "saint lawrence": "st lawrence",
    "maryville mo": "maryville", "union ny": "union ny", "assumption college": "assumption college",
}


def norm_name(s: str | None) -> str:
    s = (s or "").lower().replace("&", "and").replace("'", " ")
    s = re.sub(r"\(([^)]*)\)", r" \1 ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\buniv\b|\buniversity of\b", " ", s) if not s.strip().startswith("long island") else s
    s = " ".join(s.split())
    return ALIAS.get(s, s)


def espn_keys(t: dict) -> set[str]:
    out = {norm_name(t.get("loc")), norm_name(t.get("short"))}
    nm, nick = t.get("name") or "", t.get("nick") or ""
    if nm and nick and nm.endswith(nick):
        out.add(norm_name(nm[: -len(nick)]))
    out.add(norm_name(nm))
    return {x for x in out if x}


# ── CHN season (cache only, parsed) ────────────────────────────────────────────────────────────────────────

def chn_season(level: str, season: int) -> dict | None:
    """Every cached CHN page of a season, parsed: {"teams": [...], "games": {chn_id: [...]}, "overall": {chn_id},
    "advanced": {chn_id}, "rosters": {chn_id}, "boxes": {path: box}, "metrics": {gd: tables}} or None (none cached /
    CHN off)."""
    if not chn.enabled():
        return None
    c = chn.Client(offline=True)
    seed = c.cached_or_none(chn.team_stats_url(level, SEED[0], SEED[1], "overall", season))
    teams = chn.season_teams(seed or "", level, season >= current_season())
    if not teams:
        return None
    out: dict[str, Any] = {"teams": teams, "games": {}, "overall": {}, "advanced": {}, "rosters": {}, "boxes": {},
                           "metrics": {}}
    for t in teams:
        tid, slug = t["chn_id"], t["slug"]
        h = c.cached_or_none(chn.team_stats_url(level, slug, tid, "gamebygame", season))
        if h:
            out["games"][tid] = chn.parse_gamebygame(h, season)
        h = c.cached_or_none(chn.team_stats_url(level, slug, tid, "overall", season))
        if h:
            out["overall"][tid] = chn.parse_overall(h)
        h = c.cached_or_none(chn.team_stats_url(level, slug, tid, "advanced", season))
        if h:
            out["advanced"][tid] = chn.parse_attempt_tables(h)
        h = c.cached_or_none(chn.roster_url(level, slug, tid, season))
        if h:
            out["rosters"][tid] = chn.parse_roster(h)
    for tid, gl in out["games"].items():
        for g in gl:
            if g.get("box") and g["box"] not in out["boxes"]:
                h = c.cached_or_none(g["box"])
                if h:
                    b = chn.parse_box(h)
                    if b:
                        out["boxes"][g["box"]] = b
            if level == "mch" and g.get("gd") and g["gd"] not in out["metrics"]:
                h = c.cached_or_none(chn.metrics_url(g["gd"]))
                if h and chn.metrics_has_data(h):
                    out["metrics"][g["gd"]] = chn.parse_attempt_tables(h)
    return out


# ── team identity ──────────────────────────────────────────────────────────────────────────────────────────

def _espn_team_index(level: str, season: int, events: list[dict]) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for e in events:
        for s in ("h", "a"):
            t = e[s]
            idx.setdefault(t["id"], {"id": t["id"], "name": t["name"], "loc": t["loc"], "abbr": t["abbr"],
                                     "short": t["short"], "nick": None})
    cur = hk.load_raw(level, current_season())
    for t in cur.get("teams") or []:
        if t["id"] in idx:
            idx[t["id"]].update({k: t.get(k) for k in ("nick", "color", "alt") if t.get(k)})
        else:
            idx[t["id"]] = dict(t)
    return idx


def map_chn_to_espn(cs: dict, events: list[dict], eidx: dict[str, dict]) -> dict[str, str]:
    """{chn_id: espn_id} by matching each CHN team's results (date, goals for, goals against) to ESPN's, then names."""
    sig_e: dict[str, set] = defaultdict(set)
    for e in events:
        if e["status"] != "post" or e["h"]["score"] is None:
            continue
        d = e["date"][:10]
        for s, o in (("h", "a"), ("a", "h")):
            for dd in (d, _shift(d, -1)):
                sig_e[e[s]["id"]].add((dd, e[s]["score"], e[o]["score"]))
    out: dict[str, str] = {}
    taken: set[str] = set()
    cands = []
    for t in cs["teams"]:
        gl = [g for g in cs["games"].get(t["chn_id"], []) if g.get("gf") and g["gf"].get("t") is not None]
        sig = {(g["date"], g["gf"]["t"], g["ga"]["t"]) for g in gl if g.get("date")}
        if not sig:
            continue
        best, bs = None, 0
        for eid, es in sig_e.items():
            n = len(sig & es)
            if n > bs:
                best, bs = eid, n
        if best and bs >= max(3, 0.4 * len(sig)):
            cands.append((bs, t["chn_id"], best))
    for bs, cid, eid in sorted(cands, reverse=True):
        if cid not in out and eid not in taken:
            out[cid] = eid
            taken.add(eid)
    # names for the rest
    by_key: dict[str, str] = {}
    for eid, t in eidx.items():
        for k in espn_keys(t):
            by_key.setdefault(k, eid)
    for t in cs["teams"]:
        if t["chn_id"] in out:
            continue
        eid = by_key.get(norm_name(t["name"])) or by_key.get(norm_name(t["slug"].replace("-", " ")))
        if eid and eid not in taken:
            out[t["chn_id"]] = eid
            taken.add(eid)
    return out


def _shift(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def conf_id(name: str | None) -> str:
    if not name:
        return "ind"
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ── games ──────────────────────────────────────────────────────────────────────────────────────────────────

_ROUND_RX = [(re.compile(r"Frozen Four", re.I), "Frozen Four"),
             (re.compile(r"National Championship|Championship Game|National Final", re.I), "Final"),
             (re.compile(r"Regional Semifinal", re.I), "Regional semifinal"),
             (re.compile(r"Regional Final", re.I), "Regional final"),
             (re.compile(r"Quarterfinal", re.I), "Quarterfinal"),
             (re.compile(r"Semifinal", re.I), "Semifinal"),
             (re.compile(r"1st Round|First Round|Opening Round", re.I), "First round"),
             (re.compile(r"Third Place|Consolation", re.I), "Third place"),
             (re.compile(r"Final|Championship", re.I), "Final")]


def classify(notes: list[str], stype_espn: Any, chn_type: str | None, level: str) -> tuple[str, str | None, str | None]:
    """(stype, round, region) from ESPN's notes and season type, else CHN's box label."""
    txt = " | ".join(notes or [])
    if "NCAA" in txt or stype_espn == 3 or (chn_type and "NCAA" in chn_type):
        src = txt or chn_type or ""
        rnd = next((r for rx, r in _ROUND_RX if rx.search(src)), None)
        if level == "mch" and rnd == "Semifinal":
            rnd = "Frozen Four"
        if level == "wch" and rnd == "Semifinal":
            rnd = "Frozen Four"
        m = re.search(r"-\s*([A-Za-z .']+?) Regional", src)
        return "ncaa", rnd, m.group(1).strip() if m else None
    conf_t = re.search(r"^(Atlantic Hockey|Big Ten|CCHA|ECAC|Hockey East|NCHC|WCHA|CHA|NEWHA|AHA|Atlantic Hockey America)"
                       r"(?: Tournament)?\s*-\s*(.+)$", notes[0]) if notes else None
    if conf_t:
        rnd = next((r for rx, r in _ROUND_RX if rx.search(conf_t.group(2))), conf_t.group(2))
        return "conf", rnd, None
    if chn_type and re.search(r"Tournament|Playoff|Championship", chn_type) and not re.search(
            r"Non-Conference|Classic|Cup|Invitational|Beanpot|Showcase|Holiday|Face-Off|Four\b", chn_type):
        rnd = next((r for rx, r in _ROUND_RX if rx.search(chn_type)), None)
        return "conf", rnd, None
    if chn_type and re.search(r"Exhibition", chn_type, re.I):
        return "exh", None, None
    return "reg", None, None


def _res(hs, as_, so: bool) -> str | None:
    if hs is None or as_ is None:
        return None
    if so or hs == as_:
        return "T"
    return "W" if hs > as_ else "L"


def assemble(level: str, season: int, chn_data: dict | None = None, use_chn: bool | None = None) -> dict:
    """Build (do not save) the season store."""
    use_chn = chn.enabled() if use_chn is None else use_chn
    raw = hk.load_raw(level, season)
    events = [e for e in hk.all_events(raw)]
    eidx = _espn_team_index(level, season, events)
    cs = (chn_data if chn_data is not None else chn_season(level, season)) if use_chn else None
    teams: dict[str, dict] = {}
    confs: dict[str, dict] = {}
    cmap: dict[str, str] = {}
    if cs:
        cmap = map_chn_to_espn(cs, events, eidx)
        for t in cs["teams"]:
            tid = cmap.get(t["chn_id"]) or f"c{t['chn_id']}"
            e = eidx.get(tid, {})
            cid = conf_id(t["conf"])
            confs.setdefault(cid, {"name": t["conf"] or "Independent", "short": CONF_SHORT.get(t["conf"] or "", t["conf"])})
            teams[tid] = {"name": e.get("loc") or t["name"], "short": t["name"], "abbr": e.get("abbr"),
                          "espn_id": e.get("id"), "chn_id": t["chn_id"], "chn_slug": t["slug"], "conf": cid,
                          "d1": True, "color": e.get("color"), "alt": e.get("alt")}
    # ESPN-only seasons / teams: conferences from ESPN standings are not fetched; mark D-I by appearances
    if not cs:
        cnt = Counter()
        for e in events:
            for s in ("h", "a"):
                cnt[e[s]["id"]] += 1
        for eid, n in cnt.items():
            if n >= 10:
                e = eidx.get(eid, {})
                teams[eid] = {"name": e.get("loc") or e.get("name"), "short": e.get("short") or e.get("loc"),
                              "abbr": e.get("abbr"), "espn_id": eid, "chn_id": None, "chn_slug": None, "conf": "ind",
                              "d1": True, "color": e.get("color"), "alt": e.get("alt")}
        confs.setdefault("ind", {"name": "Independent", "short": "IND"})
    # name -> team id for CHN opponents: CHN's season teams, then every ESPN team of the season (a program new to
    # Division I or missing from CHN's season menu, e.g. Maryville in 2026-27)
    by_chn_name: dict[str, str] = {}
    for eid, et in eidx.items():
        for k in espn_keys(et):
            by_chn_name.setdefault(k, eid)
    if cs:
        for t in cs["teams"]:
            by_chn_name[norm_name(t["name"])] = cmap.get(t["chn_id"]) or f"c{t['chn_id']}"

    games: dict[str, dict] = {}
    key_of: dict[tuple, str] = {}
    fuzzy: dict[tuple, str] = {}             # +-1 day (time zones): used only when the ESPN game's own day is free
    espn_day: dict[str, str] = {}

    def key(d: str, a: str, b: str) -> tuple:
        return (d, tuple(sorted((a, b))))

    # ESPN events
    for e in events:
        h, a = e["h"]["id"], e["a"]["id"]
        for tid in (h, a):
            if tid not in teams:
                et = eidx.get(tid, {})
                teams[tid] = {"name": et.get("loc") or et.get("name") or e["h" if tid == h else "a"]["name"],
                              "short": et.get("short"), "abbr": et.get("abbr"), "espn_id": tid, "chn_id": None,
                              "chn_slug": None, "conf": None, "d1": False}
        st, rnd, reg = classify(e.get("notes") or [], e.get("stype"), None, level)
        so = "SO" in str(e.get("detail") or "")
        ot = 0
        if e["status"] == "post":
            m = re.search(r"/(\d)?OT", str(e.get("detail") or ""))
            ot = (int(m.group(1)) if m and m.group(1) else 1) if m else max(0, len(e["h"]["ls"]) - 3)
        g = {"id": e["id"], "espn_id": e["id"], "date": e["date"], "status": e["status"], "stype": st, "round": rnd,
             "region": reg, "note": (e.get("notes") or [None])[0], "home": h, "away": a, "neutral": e["neutral"],
             "hs": e["h"]["score"], "as": e["a"]["score"], "ot": ot, "so": so,
             "res": _res(e["h"]["score"], e["a"]["score"], so) if e["status"] == "post" else None,
             "venue": e.get("venue"), "att": e.get("att"), "tba": e.get("tv") is False,
             "per": [e["h"]["ls"][:3], e["a"]["ls"][:3]] if e["h"]["ls"] else None,
             "hr": _rank(e["h"].get("rank")), "ar": _rank(e["a"].get("rank"))}
        games[g["id"]] = g
        d = _local_day(e["date"])
        key_of[key(d, h, a)] = g["id"]
        espn_day[g["id"]] = d
        fuzzy.setdefault(key(_shift(d, 1), h, a), g["id"])
        fuzzy.setdefault(key(_shift(d, -1), h, a), g["id"])

    # CHN team game lists
    chn_cov = Counter()
    chn_days: set = set()
    if cs:
        for t in cs["teams"]:
            me0 = cmap.get(t["chn_id"]) or f"c{t['chn_id']}"
            for row in cs["games"].get(t["chn_id"], []):
                opp0 = by_chn_name.get(norm_name(row["opp"]))
                if row.get("date") and opp0:
                    chn_days.add((row["date"], tuple(sorted((me0, opp0)))))
    if cs:
        seen_pairs: set = set()
        for t in cs["teams"]:
            me = cmap.get(t["chn_id"]) or f"c{t['chn_id']}"
            for row in cs["games"].get(t["chn_id"], []):
                if not row.get("date"):
                    continue
                opp = by_chn_name.get(norm_name(row["opp"]))
                if opp is None:
                    oid = "x:" + re.sub(r"[^a-z0-9]+", "-", row["opp"].lower()).strip("-")
                    opp = oid
                    teams.setdefault(oid, {"name": row["opp"], "short": row["opp"], "abbr": None, "espn_id": None,
                                           "chn_id": None, "chn_slug": None, "conf": None, "d1": False})
                site = row["site"]
                home, away = (me, opp) if site in ("home", "neutral") else (opp, me)
                k = key(row["date"], home, away)
                pair_key = (row["date"], tuple(sorted((home, away))), row.get("box"))
                gid = key_of.get(k)
                if gid is None and k in fuzzy:
                    cand = fuzzy[k]
                    # a Friday-Saturday series: the ESPN game of the next day is not this one when CHN also lists a
                    # game between the pair on that day
                    if (espn_day.get(cand), k[1]) not in chn_days:
                        gid = cand
                mine_is_home = home == me
                gf = (row.get("gf") or {}).get("t")
                ga = (row.get("ga") or {}).get("t")
                hs, as_ = (gf, ga) if mine_is_home else (ga, gf)
                bx = cs["boxes"].get(row.get("box")) if row.get("box") else None
                if gid is None:
                    if pair_key in seen_pairs:
                        continue
                    gid = f"h{row['date'].replace('-', '')}{home}{away}".replace(":", "")
                    if gid in games:
                        continue
                    so = bool(bx and bx.get("so"))
                    ot_n = 1 if (row.get("gf") or {}).get("ot") is not None or (row.get("ga") or {}).get("ot") is not None else 0
                    played = hs is not None or row.get("res") is not None
                    games[gid] = {"id": gid, "espn_id": None, "date": f"{row['date']}T23:00:00Z", "tba": True,
                                  "status": "post" if played else ("post" if row.get("nodata") else "pre"),
                                  "stype": "reg", "round": None, "region": None, "note": None, "home": home,
                                  "away": away, "neutral": site == "neutral", "hs": hs, "as": as_, "ot": ot_n,
                                  "so": so, "res": _res(hs, as_, so) if hs is not None else _flip_res(row.get("res"), mine_is_home),
                                  "venue": None, "att": row.get("att"), "per": None, "hr": None, "ar": None}
                    key_of[k] = gid
                    chn_cov["chn_only"] += 1
                seen_pairs.add(pair_key)
                g = games[gid]
                # orient CHN's numbers to the store's home/away
                flip = g["home"] != home
                cb = g.setdefault("chn", {})
                if row.get("box"):
                    cb["box"] = row["box"]
                if row.get("gd"):
                    cb["gd"] = row["gd"]
                if row.get("so_flag"):
                    g["so"] = True
                    g["res"] = "T"
                if row.get("ot_flag") or (row.get("gf") or {}).get("ot") is not None or (row.get("ga") or {}).get("ot") is not None:
                    g["ot"] = max(g.get("ot") or 0, 1)       # CHN's game-by-game line has an overtime column
                if row.get("sf") and row["sf"].get("t") is not None:
                    my_home = (g["home"] == me)
                    sf, sa = row["sf"]["t"], row["sa"]["t"]
                    cb["sh"] = [sf, sa] if my_home else [sa, sf]
                    per_f = [row["gf"].get(k2) for k2 in ("p1", "p2", "p3")]
                    per_a = [row["ga"].get(k2) for k2 in ("p1", "p2", "p3")]
                    cb["per"] = [per_f, per_a] if my_home else [per_a, per_f]
                    shp_f = [row["sf"].get(k2) for k2 in ("p1", "p2", "p3", "ot")]
                    shp_a = [row["sa"].get(k2) for k2 in ("p1", "p2", "p3", "ot")]
                    cb["shp"] = [shp_f, shp_a] if my_home else [shp_a, shp_f]
                    pp_f, pp_a = [row.get("ppg"), row.get("ppo")], [row.get("opp_ppg"), row.get("opp_ppo")]
                    cb["pp"] = [pp_f, pp_a] if my_home else [pp_a, pp_f]
                    if row.get("pim") is not None:
                        cb.setdefault("pim", [None, None])[0 if my_home else 1] = row["pim"]
                    if row.get("xg") is not None:
                        cb["xg"] = [row["xg"], row.get("xga")] if my_home else [row.get("xga"), row["xg"]]
                    if row.get("scorers"):
                        cb.setdefault("scorers", [None, None])[0 if my_home else 1] = row["scorers"]
                    if hs is not None:
                        new = (hs, as_) if not flip else (as_, hs)
                        if g.get("hs") is not None and (g["hs"], g["as"]) != new:
                            chn_cov["score_fix"] += 1          # ESPN and CHN disagree: CHN's line is kept
                        if g.get("hs") is None or (g["hs"], g["as"]) != new:
                            g["hs"], g["as"] = new
                            g["status"] = "post"
                            g["res"] = _res(new[0], new[1], bool(g.get("so")))
                    if g.get("att") is None and row.get("att"):
                        g["att"] = row["att"]
                    chn_cov["stats"] += 1
                if bx:
                    if bx.get("game_type"):
                        cb["type"] = bx["game_type"]
                    if bx.get("so"):
                        g["so"] = True
                        g["res"] = "T"
                    if g.get("venue") is None and bx.get("venue"):
                        g["venue"] = bx["venue"]
                    cb["has_box"] = True
                if row.get("res") and g.get("res") is None:
                    g["res"] = _flip_res(row["res"], g["home"] == me)
                    if g["status"] == "pre":
                        g["status"] = "post"
    # a team outside CHN's season list that plays a Division I schedule (8+ games against D-I teams) is Division I
    if cs:
        vs_d1 = Counter()
        for g in games.values():
            h_, a_ = teams.get(g["home"], {}), teams.get(g["away"], {})
            if h_.get("d1") and not a_.get("d1"):
                vs_d1[g["away"]] += 1
            elif a_.get("d1") and not h_.get("d1"):
                vs_d1[g["home"]] += 1
        for t, n in vs_d1.items():
            if n >= 8 and t in teams and not str(t).startswith("x:"):
                teams[t]["d1"] = True
                teams[t]["conf"] = teams[t].get("conf") or "ind"
                confs.setdefault("ind", {"name": "Independent", "short": "IND"})
    # game types: CHN's label refines ESPN's for conference tournaments, exhibitions and conference games
    for g in games.values():
        cb = g.get("chn") or {}
        if cb.get("type"):
            st, rnd, reg = classify([g["note"]] if g.get("note") else [], 3 if g["stype"] == "ncaa" else 2, cb["type"], level)
            if g["stype"] == "reg" and st in ("conf", "exh"):
                g["stype"], g["round"] = st, g["round"] or rnd
        th, ta = teams.get(g["home"], {}), teams.get(g["away"], {})
        lab = cb.get("type") or ""
        if g["stype"] == "reg":
            if lab:
                g["conf_game"] = bool(re.search(r"Game$", lab)) and "Non-Conference" not in lab and "Exhibition" not in lab
            else:
                g["conf_game"] = bool(th.get("conf") and th.get("conf") == ta.get("conf") and th.get("conf") != "ind")
        else:
            g["conf_game"] = False
        if not th.get("d1") and not ta.get("d1"):
            g["drop"] = True
    gl = sorted((g for g in games.values() if not g.get("drop")), key=lambda g: (g["date"], g["id"]))
    st = {"level": level, "season": season, "version": VERSION, "built_at": cc_store.now(), "chn_used": bool(cs),
          "teams": teams, "conferences": confs, "games": gl, "polls": raw.get("polls") or {},
          "espn_teams": {k: {kk: v.get(kk) for kk in ("color", "alt")} for k, v in eidx.items() if v.get("color")}}
    us = uscho_block(level, season, teams)
    if us:
        st["uscho"] = us
    if cs:
        st["chn"] = chn_block(level, season, cs, cmap, teams, games)
        st["chn"]["coverage"] = dict(chn_cov)
    return st


def uscho_block(level: str, season: int, teams: dict) -> dict | None:
    """USCHO polls of the season from the cache (sources/uscho.py; None when switched off or none cached):
    {date: [{"rank", "team", "points", "first", "record", "prev"}]} with team ids mapped by name."""
    from ..sources import uscho
    if not uscho.enabled():
        return None
    keys = {}
    for t, v in teams.items():
        if v.get("d1"):
            for nm in (v.get("short"), v.get("name"), (v.get("chn_slug") or "").replace("-", " ")):
                if nm:
                    keys.setdefault(norm_name(nm), t)
    out = {}
    try:
        dates = [d for d in uscho.poll_dates_cached(level) if d.get("season") == season]
    except Exception:  # noqa: BLE001
        return None
    for d in dates:
        p = uscho.parse_poll(uscho.cached(f"{uscho.PATH[level]}{d['date']}") or "")
        if not p or not p["rows"]:
            continue
        rows = []
        for r in p["rows"]:
            t = keys.get(norm_name(r["name"])) or keys.get(norm_name(re.sub(r"\bSt\.?$", "State", r["name"] or "")))
            if t:
                rows.append({"rank": r["rank"], "team": t, "points": r["points"], "first": r["first"],
                             "record": r["record"], "prev": r["prev"]})
        if rows:
            out[d["date"]] = rows
    return out or None


def _flip_res(res: str | None, mine_is_home: bool) -> str | None:
    if res not in ("W", "L", "T"):
        return None
    if mine_is_home or res == "T":
        return res
    return "L" if res == "W" else "W"


def _rank(x) -> int | None:
    try:
        x = int(x)
    except (TypeError, ValueError):
        return None
    return x if 0 < x <= 25 else None


def _local_day(iso: str) -> str:
    """US Eastern calendar date of a UTC start (late games stay on their evening)."""
    t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    return (t - timedelta(hours=9)).date().isoformat()


# ── CHN players, rosters, boxes ────────────────────────────────────────────────────────────────────────────

def _pkey(name: str) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


def chn_block(level: str, season: int, cs: dict, cmap: dict, teams: dict, games: dict) -> dict:
    players: dict[str, dict] = {}
    goalies: dict[str, dict] = {}
    rosters: dict[str, list] = {}
    name_ix: dict[tuple, str] = {}
    for t in cs["teams"]:
        tid = cmap.get(t["chn_id"]) or f"c{t['chn_id']}"
        ov = cs["overall"].get(t["chn_id"]) or {}
        ros = cs["rosters"].get(t["chn_id"]) or []
        rmap = {_pkey(r["name"]): r for r in ros}
        rosters[tid] = ros
        adv_rows = {}
        for tab in cs["advanced"].get(t["chn_id"]) or []:
            if tab["kind"] == "skaters":
                for r in tab["rows"]:
                    if r["name"] != "TOTAL":
                        adv_rows[_pkey(r["name"])] = r
        for sk in ov.get("skaters") or []:
            pid = sk.get("chn_pid") or f"n{tid}-{_pkey(sk['name'])}"
            ro = rmap.get(_pkey(sk["name"])) or {}
            rec = {"name": sk["name"], "team": tid, "pos": (sk.get("pos") or ro.get("pos") or "F")[:1].upper(),
                   "cls": sk.get("cls") or ro.get("cls"), "gp": sk.get("gp"), "g": sk.get("g"), "a": sk.get("a"),
                   "pts": sk.get("pts"), "sh": sk.get("sh"), "pim": sk.get("pim"), "gwg": sk.get("gwg"),
                   "ppg": sk.get("ppg"), "shg": sk.get("shg"), "pm": sk.get("pm"),
                   "bio": {k: ro.get(k) for k in ("num", "ht_in", "wt", "dob", "hometown", "last_team", "draft")} if ro else None}
            ad = adv_rows.get(_pkey(sk["name"]))
            if ad:
                rec["adv"] = {k: v for k, v in ad.items() if k not in ("name", "chn_pid", "team")}
            if pid in players:      # traded mid-season (rare in college): keep the bigger line
                if (players[pid].get("gp") or 0) >= (rec.get("gp") or 0):
                    continue
            players[pid] = rec
            name_ix[(tid, _pkey(sk["name"]))] = pid
        for gk in ov.get("goalies") or []:
            pid = gk.get("chn_pid") or f"n{tid}-{_pkey(gk['name'])}"
            ro = rmap.get(_pkey(gk["name"])) or {}
            goalies[pid] = {"name": gk["name"], "team": tid, "cls": gk.get("cls") or ro.get("cls"), "gp": gk.get("gp"),
                            "w": gk.get("w"), "l": gk.get("l"), "t": gk.get("t"), "ga": gk.get("ga"), "min": gk.get("min"),
                            "sv": gk.get("sv"), "so": gk.get("so"),
                            "bio": {k: ro.get(k) for k in ("num", "ht_in", "wt", "dob", "hometown", "last_team", "draft")} if ro else None}
            name_ix[(tid, _pkey(gk["name"]))] = pid
    # boxes keyed by our game id
    boxes: dict[str, dict] = {}
    metrics: dict[str, list] = {}
    by_box = {g["chn"]["box"]: g for g in games.values() if (g.get("chn") or {}).get("box")}
    by_gd = {g["chn"]["gd"]: g for g in games.values() if (g.get("chn") or {}).get("gd")}
    for path, b in cs["boxes"].items():
        g = by_box.get(path)
        if not g:
            continue
        side_tid = {"home": g["home"], "away": g["away"]}
        # CHN's away/home are the box's; ours may be flipped on neutral ice
        a_chn, h_chn = b["away"].get("chn_id"), b["home"].get("chn_id")
        flip = False
        if h_chn and (cmap.get(h_chn) or f"c{h_chn}") == g["away"]:
            flip = True
        tmap = {"away": side_tid["home"] if flip else side_tid["away"], "home": side_tid["away"] if flip else side_tid["home"]}
        sk = []
        for r in b["skaters"]:
            tid = tmap.get(r["team"])
            pid = name_ix.get((tid, _pkey(r["name"])))
            sk.append([pid, tid, r["name"], r.get("g"), r.get("a"), r.get("pm"), r.get("sh"), r.get("toi"), r.get("pim"),
                       r.get("fow"), r.get("fol")])
        gks = []
        for r in b["goalies"]:
            tid = tmap.get(r["team"])
            gks.append([name_ix.get((tid, _pkey(r["name"]))) if not r.get("en") else None, tid, r["name"], r.get("sv"),
                        r.get("ga"), r.get("sec"), 1 if r.get("en") else 0])
        goals = []
        for x in b["goals"]:
            tid = tmap.get(x["team"])
            goals.append([x["per"], x["t"], tid, x.get("scorer_pid") or name_ix.get((tid, _pkey(x["scorer"]))), x["scorer"],
                          name_ix.get((tid, _pkey(x.get("a1") or ""))), x.get("a1"),
                          name_ix.get((tid, _pkey(x.get("a2") or ""))), x.get("a2"), x["sit"], x.get("n")])
        pens = [[x["per"], x["t"], tmap.get(x["team"]), name_ix.get((tmap.get(x["team"]), _pkey(x["player"]))),
                 x["player"], x["min"], x["inf"]] for x in b["pens"]]
        teamstats = {}
        for side in ("away", "home"):
            s = b[side]
            teamstats[tmap[side]] = {k: s.get(k) for k in ("shots", "periods", "pen", "pim", "ppg", "ppo", "fow", "fol", "xg")}
        lines = {}
        for side, v in (b.get("lines") or {}).items():
            lines[tmap.get(side)] = v
        boxes[g["id"]] = {"type": b.get("game_type"), "venue": b.get("venue"), "att": b.get("att"), "refs": b.get("refs"),
                          "ot": b.get("ot"), "so": b.get("so"), "labels": b.get("period_labels"),
                          "team": teamstats, "skaters": sk, "goalies": gks, "goals": goals, "pens": pens,
                          "lines": lines}
    for gd, tabs in cs["metrics"].items():
        g = by_gd.get(gd)
        if not g:
            continue
        rows = []
        names_tid = {}
        for side in ("home", "away"):
            tt = teams.get(g[side]) or {}
            for nm in (tt.get("abbr"), tt.get("short"), tt.get("name")):
                if nm:
                    names_tid[nm] = g[side]
        for tab in tabs:
            for r in tab["rows"]:
                if r["name"] == "TOTAL":
                    continue
                tid = names_tid.get(r.get("team")) or names_tid.get(tab.get("team"))
                if tid is None:
                    for side in ("home", "away"):
                        if (g[side], _pkey(r["name"])) in name_ix:
                            tid = g[side]
                pid = name_ix.get((tid, _pkey(r["name"])))
                rows.append([tab["kind"][0], pid, tid, r["name"]] + [r.get(k) for k in METRIC_KEYS[tab["kind"]]])
        metrics[g["id"]] = rows
    return {"players": players, "goalies": goalies, "rosters": rosters, "boxes": boxes, "metrics": metrics,
            "metric_cols": {k: v for k, v in METRIC_KEYS.items()},
            "box_cols": {"skaters": ["pid", "team", "name", "g", "a", "pm", "sh", "toi", "pim", "fow", "fol"],
                         "goalies": ["pid", "team", "name", "sv", "ga", "sec", "en"],
                         "goals": ["per", "t", "team", "pid", "name", "a1_pid", "a1", "a2_pid", "a2", "sit", "n"],
                         "pens": ["per", "t", "team", "pid", "name", "min", "inf"]}}


METRIC_KEYS = {"skaters": [f"{sp}_{k}" for sp in ("all", "ev", "pp", "close") for k in ("bl", "mi", "sv", "g", "tsa")]
               + ["blk", "fow", "fol"],
               "goalies": [f"{sp}_{k}" for sp in ("all", "ev", "sh", "close") for k in ("sv", "ga")]}


def build_store(level: str, season: int, save: bool = True) -> dict:
    st = assemble(level, season)
    if save:
        save_store(level, season, st)
    return st
