"""Player progression (round 6, 28 Oct 2026): every season of a player on the position group's deep metric set, placed
against that season's qualified peers, and the peer reference per season. One recipe for every site; the front end is
the kit module docs/_design/progression.js (MIGRATION_V4.md, "Progression").

Payload contract
----------------
players/<pid>.json (added fields only):
    "prog": {"v": 1, "keys": {"<kind>": [metric ids]}}    the deep set per kind (skater / goalie, hitter / pitcher ...):
                                                          the spec groups' headline metrics, then the secondary ones,
                                                          spec order, only ids the data carries
    seasons[i].dv  [values aligned to prog.keys[kind]]    null where the season has no value
    seasons[i].dp  [percentiles 0-100 aligned]           only on rows placed in the pool (qualified); else absent
    seasons[i].pg  "<spec group id>"                     the peer group the row is placed in

<data>/progression_ref.json (one small file per sport or league):
    {"v": 1, "sport", "updated_at", "q": [10, 25, 50, 75, 90],
     "groups": {gid: {"label", "keys": [ids]}},
     "seasons": {"<season>": {"len": games in the season (optional), gid: {"n": qualified peers, "m": {id: [q10, q25,
                 q50, q75, q90]}}}}}

Percentiles: the site's own percentile for the key when the caller passes one (so the progression agrees with the
player card), else the mid-rank percentile among the season's qualified peers of the group (100 = best; lower-is-better
metrics flipped; style metrics placed high = more). A key needs MIN_POOL qualified values for percentiles and the
reference. Values are rounded to 4 significant figures.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, timezone
from typing import Any, Iterable

from oddsmarkets.common import similar as SIM

Q = (10, 25, 50, 75, 90)
MIN_POOL = 8
VERSION = 1


def fnum(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def rnd(v: Any) -> float | int | None:
    """4 significant figures (an integer stays an integer)."""
    x = fnum(v)
    if x is None:
        return None
    if x == int(x) and abs(x) < 1e7:
        return int(x)
    if x == 0:
        return 0
    d = max(0, 3 - int(math.floor(math.log10(abs(x)))))
    return round(x, d)


def group(sport: str, gid: str) -> dict | None:
    return next((g for g in SIM.spec(sport).get("groups") or [] if g.get("id") == gid), None)


def group_keys(sport: str, gid: str) -> list[str]:
    """The group's metric ids: headline (by order) then secondary (by order), as the spec lists them."""
    g = group(sport, gid) or {}
    ms = [m for m in g.get("metrics") or [] if m.get("id")]
    head = sorted((m for m in ms if m.get("set") == "headline"), key=lambda m: m.get("order") or 99)
    rest = [m for m in ms if m.get("set") != "headline"]
    return [m["id"] for m in head + rest]


def deep_keys(sport: str, gids: Iterable[str], have: Iterable[str] | None = None, extra: Iterable[str] = ()) -> list[str]:
    """The union of the groups' keys (first group's order first), then `extra`, kept only where `have` has them."""
    hv = set(have) if have is not None else None
    out: list[str] = []
    for gid in gids:
        for k in group_keys(sport, gid):
            if k not in out and (hv is None or k in hv):
                out.append(k)
    for k in extra:
        if k not in out and (hv is None or k in hv):
            out.append(k)
    return out


def directions(sport: str, groups: Iterable[str] | None = None) -> dict[str, str]:
    """{id: 'higher' | 'lower' | 'neutral'} over every group of the sport's spec (or only `groups`: a metric can point
    the other way for another position, e.g. K% for hitters and pitchers)."""
    out: dict[str, str] = {}
    gs = set(groups) if groups is not None else None
    for g in SIM.spec(sport).get("groups") or []:
        if gs is not None and g.get("id") not in gs:
            continue
        for m in g.get("metrics") or []:
            if m.get("id") and m["id"] not in out:
                out[m["id"]] = str(m.get("direction") or "higher")
    return out


def place(pool: list[float], v: float, lower: bool = False) -> int:
    """Mid-rank percentile of v in the sorted pool, 0-100 (100 = best; lower=True flips)."""
    n = len(pool)
    if not n:
        return 50
    lo = bisect.bisect_left(pool, v)
    hi = bisect.bisect_right(pool, v)
    p = 100.0 * (lo + 0.5 * (hi - lo)) / n
    return int(round(100 - p if lower else p))


def quantiles(vals: list[float]) -> list[float]:
    """Linear-interpolated quantiles Q of a sorted list."""
    n = len(vals)
    out = []
    for q in Q:
        pos = (n - 1) * q / 100.0
        i = int(math.floor(pos))
        f = pos - i
        x = vals[i] if i + 1 >= n else vals[i] * (1 - f) + vals[i + 1] * f
        out.append(rnd(x))
    return out


class Builder:
    """Collect rows, then fill dv / dp / pg and build the reference.

        pb = Builder("hockey", {"skater": [...], "goalie": [...]})
        h = pb.add(season, kind, gid, values, qualified, pct=None)    # h: the dict to merge into the season row
        pb.finish()                                                   # fills every handle
        ref = pb.reference(labels={gid: label}, lengths={season: games})
    """

    def __init__(self, sport: str, keys: dict[str, list[str]], dirs: dict[str, dict[str, str]] | None = None):
        self.sport = sport
        self.keys = {k: list(v) for k, v in keys.items()}
        self.dirs = directions(sport)
        self.kdirs = dirs or {}          # {kind: {id: direction}}: per-kind overrides (directions(sport, groups))
        self.rows: list[tuple] = []
        self.pools: dict[tuple, dict[str, list[float]]] = {}
        self.group_kind: dict[str, str] = {}

    def add(self, season: Any, kind: str, gid: str | None, values: dict, qualified: bool, pct: dict | None = None) -> dict:
        keys = self.keys.get(kind) or []
        h: dict = {}
        vals = [fnum((values or {}).get(k)) for k in keys]
        self.rows.append((str(season), kind, gid, vals, bool(qualified), pct or {}, h))
        if gid:
            self.group_kind.setdefault(gid, kind)
            if qualified:
                pool = self.pools.setdefault((str(season), gid), {})
                for k, v in zip(keys, vals):
                    if v is not None:
                        pool.setdefault(k, []).append(v)
        return h

    def finish(self) -> None:
        for P in self.pools.values():
            for k in P:
                P[k].sort()
        for season, kind, gid, vals, qual, pct, h in self.rows:
            keys = self.keys.get(kind) or []
            h["dv"] = [rnd(v) for v in vals]
            if gid:
                h["pg"] = gid
            if not (qual and gid):
                continue
            pool = self.pools.get((season, gid)) or {}
            dp: list = []
            for k, v in zip(keys, vals):
                p = fnum(pct.get(k))
                if p is not None:
                    dp.append(int(round(p)))
                elif v is not None and len(pool.get(k) or []) >= MIN_POOL:
                    dp.append(place(pool[k], v, (self.kdirs.get(kind) or {}).get(k, self.dirs.get(k)) == "lower"))
                else:
                    dp.append(None)
            if any(x is not None for x in dp):
                h["dp"] = dp

    def reference(self, labels: dict[str, str] | None = None, lengths: dict[Any, Any] | None = None) -> dict:
        seasons: dict[str, dict] = {}
        for (season, gid), P in sorted(self.pools.items()):
            m = {k: quantiles(v) for k, v in P.items() if len(v) >= MIN_POOL}
            if not m:
                continue
            n = max(len(v) for v in P.values())
            seasons.setdefault(season, {})[gid] = {"n": n, "m": m}
        for s, ln in (lengths or {}).items():
            if str(s) in seasons and ln:
                seasons[str(s)]["len"] = ln
        groups = {gid: {"label": (labels or {}).get(gid) or ((group(self.sport, gid) or {}).get("display") or gid),
                        "kind": kind, "keys": self.keys.get(kind) or []} for gid, kind in sorted(self.group_kind.items())}
        return {"v": VERSION, "sport": self.sport, "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "q": list(Q), "groups": groups, "seasons": seasons}

    def prog_block(self) -> dict:
        return {"v": VERSION, "keys": self.keys}
