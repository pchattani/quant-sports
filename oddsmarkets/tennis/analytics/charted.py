"""
Per-match statistics from the Match Charting Project (CC BY-NC-SA 4.0; sources/charting.py) for match pages.

The ATP publishes no per-match statistics we may use (docs/research/data_sources.md), and the WTA API has none for
the Slams. A charted match has every point: `build(td, years)` maps each charted match of those years to its store
match (both players resolved by full name through the registry, never creating one; the same pair within a window
around the charting date; the round when it agrees) and derives

  stats     the WTA-API shape (STATS per side, and per set): aces, double faults, serve points, first serves in and
            won, second serves won, service games, break points saved / faced, return points won, break points
            converted / chances
  charting  the match page's "Charting deep dive": first-serve direction, points won by rally length, winners /
            unforced / forced errors / aces, net points [played, won], and the number of charted points

{store match id: {"stats": {...}, "charting": {...}, "charted_id": str}}, cached under ACE_CACHE/ace_charted keyed on
the charting files and the matches searched. Break points are read from the point score before each point (server
first: "30-40", "40-AD"), never in a tiebreak; a service game is a distinct (set, game score) a player served in.
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from oddsmarkets.tennis import canon
from oddsmarkets.tennis.sources import charting as CH

logger = logging.getLogger(__name__)
VERSION = 2
KEYS = ("aces", "dfs", "sv_pts", "fs_in", "fs_won", "ss_won", "sv_gms", "bp_saved", "bp_faced", "rt_pts_won",
        "bp_conv", "bp_opps")
ROUNDS = {"R128", "R64", "R32", "R16", "QF", "SF", "F", "RR", "Q1", "Q2", "Q3", "BR"}
RALLY = (("1-3", 1, 3), ("4-6", 4, 6), ("7-9", 7, 9), ("10+", 10, 999))


def _bp(pts: str) -> bool:
    p = str(pts or "").upper().replace(" ", "")
    if "-" not in p:
        return False
    a, b = p.split("-", 1)
    return b in ("AD", "A") or (b == "40" and a in ("0", "15", "30"))


class _Acc:
    def __init__(self) -> None:
        self.c = {k: 0 for k in KEYS}
        self.games: set = set()

    def out(self) -> dict:
        d = dict(self.c)
        d["sv_gms"] = len(self.games)
        return d


def _points_files(tour: str) -> list[Path]:
    d = CH.cache_dir()
    g = CH.GENDER[canon.tour_key(tour)]
    return [d / f"charting-{g}-points-{s}.csv" for s in ("2020s", "2010s") if (d / f"charting-{g}-points-{s}.csv").exists()]


def _sig(paths: list[Path]) -> list:
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append([p.name, st.st_size, st.st_mtime_ns])
        except OSError:
            pass
    return out


def _link(td, cm: dict, by_pair: dict) -> str | None:
    reg = td.registry
    if reg is None:
        return None
    a = reg.find("charting", cm["p1"])
    b = reg.find("charting", cm["p2"])
    if not a or not b or a == b:
        return None
    d0 = canon_day(cm.get("date"))
    if d0 is None:
        return None
    cands = []
    for m in by_pair.get(frozenset((reg.canonical(a), reg.canonical(b))), []):
        d = canon_day(m.get("date"))
        if d is None or not (d0 - timedelta(days=3) <= d <= d0 + timedelta(days=16)):
            continue
        cands.append(m)
    if len(cands) > 1 and cm.get("round") in ROUNDS:
        cands = [m for m in cands if m.get("round") == cm["round"]] or cands
    return cands[0]["id"] if len(cands) == 1 else None


def canon_day(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def build(td, years: list[int]) -> dict[str, dict]:
    """{store match id: {"stats", "charting", "charted_id"}} for the charted matches of `years` (module docstring)."""
    from oddsmarkets.tennis.models import _io
    tour = canon.tour_key(td.tour)
    g = CH.GENDER[tour]
    mpath = CH.cache_dir() / f"charting-{g}-matches.csv"
    files = _points_files(tour)
    if not mpath.exists() or not files:
        return {}
    ms = [m for y in years for m in td.matches(y).values()
          if m.get("status") in ("done", "ret") and m.get("p1") and m.get("p2")]
    key = _io.file_key(VERSION, _sig([mpath] + files), sorted(years), len(ms),
                       hashlib.sha1("".join(sorted(m["id"] for m in ms)).encode()).hexdigest())
    return _io.cached("ace_charted", tour, key, lambda: _build(td, ms, years, mpath, files))


def _build(td, ms: list[dict], years: list[int], mpath: Path, files: list[Path]) -> dict:
    by_pair: dict = defaultdict(list)
    for m in ms:
        by_pair[frozenset((str(m["p1"]), str(m["p2"])))].append(m)
    charted = CH.read_matches(mpath)
    lo = f"{min(years) - 1}-12-01"
    want: dict[str, tuple[str, dict]] = {}
    for cid, cm in charted.items():
        if not cm.get("date") or cm["date"] < lo:
            continue
        mid = _link(td, cm, by_pair)
        if mid:
            want[cid] = (mid, cm)
    if not want:
        return {}
    store = {m["id"]: m for m in ms}
    acc: dict[str, dict] = {}
    for path in files:
        for row in CH.iter_points(path):
            cid = row["match_id"]
            if cid not in want:
                continue
            mid, cm = want[cid]
            m = store[mid]
            # charting Player 1 -> store p1 or p2
            pa = td.registry.canonical(td.registry.find("charting", cm["p1"]))
            flip = str(pa) != str(m["p1"])
            try:
                svr = int(row["svr"])
                win = int(row["winner"]) if row["winner"] else None
            except ValueError:
                continue
            tb = None
            try:
                g1, g2 = int(row["gm1"] or 0), int(row["gm2"] or 0)
                tb = (g1 == 6 and g2 == 6) or (g1 == 12 and g2 == 12)
            except ValueError:
                g1 = g2 = 0
            rec = CH.parse_point(row["first"], row["second"], svr, win, row["pts"], tb)
            if rec.get("special") == "unparsed" or rec.get("winner") not in (1, 2):
                continue
            a = acc.setdefault(mid, {"n": 0, "set": defaultdict(lambda: {1: _Acc(), 2: _Acc()}), "all": {1: _Acc(), 2: _Acc()},
                                     "dir": {1: defaultdict(int), 2: defaultdict(int)},
                                     "rally": {1: defaultdict(lambda: [0, 0]), 2: defaultdict(lambda: [0, 0])},
                                     "out": {1: defaultdict(int), 2: defaultdict(int)}, "net": {1: [0, 0], 2: [0, 0]},
                                     "flip": flip})
            a["n"] += 1
            sn = _set_no(row)
            ret = 3 - svr
            for tgt in (a["all"], a["set"][sn]):
                S, R = tgt[svr], tgt[ret]
                S.c["sv_pts"] += 1
                if rec.get("first_in") is not False and rec.get("serve_no") == 1:
                    S.c["fs_in"] += 1
                    if rec["winner"] == svr:
                        S.c["fs_won"] += 1
                elif rec["winner"] == svr:
                    S.c["ss_won"] += 1
                if rec.get("ace"):
                    S.c["aces"] += 1
                if rec.get("df"):
                    S.c["dfs"] += 1
                if rec["winner"] == ret:
                    R.c["rt_pts_won"] += 1
                if not tb and _bp(row["pts"]):
                    S.c["bp_faced"] += 1
                    R.c["bp_opps"] += 1
                    if rec["winner"] == svr:
                        S.c["bp_saved"] += 1
                    else:
                        R.c["bp_conv"] += 1
                if not tb:                                  # a tiebreak is not a service game
                    S.games.add((sn, g1, g2))
            if rec.get("serve_no") == 1 and rec.get("first_dir"):
                a["dir"][svr][rec["first_dir"]] += 1
            rl = rec.get("rally_len")
            if isinstance(rl, int) and rl >= 1:
                lab = next(k for k, lo_, hi_ in RALLY if lo_ <= rl <= hi_)
                for p in (1, 2):
                    a["rally"][p][lab][0] += 1
                    a["rally"][p][lab][1] += int(rec["winner"] == p)
            oc, en = rec.get("outcome"), rec.get("ender")
            if oc == "winner" and en in (1, 2):
                a["out"][en]["winners"] += 1
            elif oc == "unforced" and en in (1, 2):
                a["out"][en]["ufe"] += 1
            elif oc == "forced" and en in (1, 2):
                a["out"][en]["fe"] += 1
            elif oc == "ace":
                a["out"][svr]["aces"] += 1
            for p in (1, 2):
                if (rec.get("net") or {}).get(p):
                    a["net"][p][0] += 1
                    a["net"][p][1] += int(rec["winner"] == p)
    out = {}
    for mid, a in acc.items():
        if a["n"] < 30:
            continue
        o = (2, 1) if a["flip"] else (1, 2)          # store p1, p2 in charting numbering
        stats = {"p1": a["all"][o[0]].out(), "p2": a["all"][o[1]].out(),
                 "by_set": [{"set": s, "p1": v[o[0]].out(), "p2": v[o[1]].out()} for s, v in sorted(a["set"].items())]}

        def share(d: dict) -> dict:
            n = sum(d.values())
            return {k: round(d.get(k, 0) / n, 3) for k in ("wide", "body", "t")} if n else {}

        charting = {"points": a["n"],
                    "serve_dir": {"p1": share(a["dir"][o[0]]), "p2": share(a["dir"][o[1]])},
                    "rally": {"p1": {k: (round(v[1] / v[0], 3) if v[0] else None) for k, v in
                                     ((lab, a["rally"][o[0]][lab]) for lab, _, _ in RALLY)},
                              "p2": {k: (round(v[1] / v[0], 3) if v[0] else None) for k, v in
                                     ((lab, a["rally"][o[1]][lab]) for lab, _, _ in RALLY)}},
                    "outcomes": {"p1": {k: a["out"][o[0]].get(k, 0) for k in ("winners", "ufe", "fe", "aces")},
                                 "p2": {k: a["out"][o[1]].get(k, 0) for k in ("winners", "ufe", "fe", "aces")}},
                    "net": {"p1": a["net"][o[0]], "p2": a["net"][o[1]]}}
        out[mid] = {"stats": stats, "charting": charting}
    logger.info("%s charting: %d charted matches in %s linked, %d with points", td.tour, len(want), years, len(out))
    return out


def _set_no(row: dict) -> int:
    try:
        return int(row.get("set1") or 0) + int(row.get("set2") or 0) + 1
    except ValueError:
        return 1
