"""
Published World Rugby ranking values our replica is checked against, all quoted from Wikipedia text (read
2 Nov 2026), never from World Rugby's own feeds:

  PUBLISHED_2026_09_28  "World Rugby Rankings", the men's top 30 "as of 28 September 2026" (points to two decimals)
  RANKS_2025_12_01      "2027 Rugby World Cup", Draw: the 24 qualified teams' world ranking positions "as of
                        1 December 2025" (positions only; 21st-ranked Belgium did not qualify)

The live rankings page anchors on PUBLISHED_2026_09_28 (every team's published points on that date) and rolls the
formula forward through the results played since, so it tracks the official table exactly as long as the feed has
every test. The check below runs the other way: our replica rebuilt from 1995 with tier priors (no published input
at all) is compared with both tables, which measures the formula and the feed's coverage together.
"""
from __future__ import annotations

import math

PUBLISHED_DATE = "2026-09-28"
PUBLISHED_2026_09_28 = [
    ("South Africa", 93.09), ("New Zealand", 91.15), ("Ireland", 88.08), ("France", 87.43), ("England", 85.68),
    ("Australia", 85.55), ("Scotland", 84.78), ("Argentina", 82.24), ("Japan", 77.28), ("Fiji", 76.81),
    ("Wales", 76.38), ("Italy", 76.30), ("Georgia", 73.94), ("Portugal", 69.39), ("United States", 67.58),
    ("Chile", 66.94), ("Spain", 66.83), ("Uruguay", 65.75), ("Tonga", 65.14), ("Samoa", 64.73), ("Romania", 62.45),
    ("Canada", 62.29), ("Belgium", 61.03), ("Hong Kong", 60.74), ("Zimbabwe", 57.68), ("Namibia", 56.96),
    ("Netherlands", 56.44), ("Switzerland", 55.47), ("Czech Republic", 54.78), ("Poland", 54.54),
]
RANKS_DATE = "2025-12-01"
RANKS_2025_12_01 = {
    "South Africa": 1, "New Zealand": 2, "England": 3, "Ireland": 4, "France": 5, "Argentina": 6, "Australia": 7,
    "Fiji": 8, "Scotland": 9, "Italy": 10, "Wales": 11, "Japan": 12, "Georgia": 13, "Uruguay": 14, "Spain": 15,
    "United States": 16, "Chile": 17, "Tonga": 18, "Samoa": 19, "Portugal": 20, "Romania": 22, "Hong Kong": 23,
    "Zimbabwe": 24, "Canada": 25,
}
ALIASES = {"United States": ("USA", "United States of America"), "Hong Kong": ("Hong Kong China",),
           "Czech Republic": ("Czechia",)}


def _ids_by_name(matches: list[dict]) -> dict:
    out = {}
    for m in matches:
        for s in ("home", "away"):
            t = m.get(s) or {}
            if t.get("name") and t.get("id"):
                out[t["name"]] = t["id"]
    for k, al in ALIASES.items():
        for a in al:
            if a in out and k not in out:
                out[k] = out[a]
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None

    def rk(x):
        o = sorted(range(n), key=lambda i: x[i])
        r = [0.0] * n
        for i, j in enumerate(o):
            r[j] = i + 1.0
        return r
    ra, rb = rk(a), rk(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return round(cov / (va * vb), 4) if va and vb else None


def points_at(ranker_history: list, upto: str) -> dict:
    """team id -> points after the last match on or before `upto` (from Ranker.history)."""
    out = {}
    for d, h, ph, a, pa, _x in ranker_history:
        if d > upto:
            break
        out[h], out[a] = ph, pa
    return out


def replica_check(rk, matches: list[dict]) -> dict:
    ids = _ids_by_name(matches)
    res = {}
    pts = points_at(rk.history, PUBLISHED_DATE)
    have = [(n, v, pts.get(ids.get(n))) for n, v in PUBLISHED_2026_09_28]
    got = [(n, v, o) for n, v, o in have if o is not None]
    if got:
        err = [o - v for _n, v, o in got]
        offset = sum(err) / len(err)
        res["sep2026"] = {
            "date": PUBLISHED_DATE, "n": len(got), "of": len(PUBLISHED_2026_09_28),
            "mae": round(sum(abs(e) for e in err) / len(err), 3),
            "mae_top10": round(sum(abs(o - v) for n, v, o in got[:10]) / max(1, min(10, len(got))), 3),
            "bias": round(offset, 3),
            "mae_after_level": round(sum(abs(e - offset) for e in err) / len(err), 3),
            "spearman": spearman([v for _n, v, _o in got], [o for _n, _v, o in got]),
            "rows": [{"team": n, "published": v, "ours": round(o, 2)} for n, v, o in got],
            "missing": [n for n, _v, o in have if o is None],
        }
        ours_rank = {n: i + 1 for i, (n, _v, _o) in enumerate(sorted(got, key=lambda r: -r[2]))}
        pub_rank = {n: i + 1 for i, (n, _v, _o) in enumerate(got)}
        res["sep2026"]["same_rank"] = sum(1 for n in ours_rank if ours_rank[n] == pub_rank[n])
        res["sep2026"]["within_one"] = sum(1 for n in ours_rank if abs(ours_rank[n] - pub_rank[n]) <= 1)
    pts = points_at(rk.history, RANKS_DATE)
    have = [(n, r, pts.get(ids.get(n))) for n, r in RANKS_2025_12_01.items()]
    got = [(n, r, o) for n, r, o in have if o is not None]
    if got:
        order = sorted(got, key=lambda x: -x[2])
        ours = {n: i + 1 for i, (n, _r, _o) in enumerate(order)}
        pub = {n: i + 1 for i, (n, _r, _o) in enumerate(sorted(got, key=lambda x: x[1]))}
        res["dec2025"] = {"date": RANKS_DATE, "n": len(got), "spearman": spearman([-r for _n, r, _o in got], [o for _n, _r, o in got]),
                          "same_rank": sum(1 for n in ours if ours[n] == pub[n]),
                          "within_one": sum(1 for n in ours if abs(ours[n] - pub[n]) <= 1),
                          "rows": [{"team": n, "published_rank": r, "our_rank": ours[n]} for n, r, _o in got]}
    return res


def anchor_seed(matches: list[dict]) -> dict:
    """team id -> published points on 28 Sep 2026 (the live table's anchor)."""
    ids = _ids_by_name(matches)
    return {ids[n]: v for n, v in PUBLISHED_2026_09_28 if n in ids}
