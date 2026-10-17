"""
The Quant Hardwood analytics layer: season catalogues for players and teams, lineups, the game
centre, the season page, awards, markets, the lab, history and the glossary, all read from the
season stores (`oddsmarkets.basketball.store`), the derived inputs (shots / stints, plain or
gzipped) and builder B's and C's models, and written by `scripts/build_hardwood.py` as the
payloads in `oddsmarkets/basketball/PAYLOADS.md`.

Roots
-----
Everything is read from and written under one data root, `docs/hardwood/data` unless the
environment variable HARDWOOD_DATA points elsewhere (tests build into a temporary folder); model
caches live under HARDWOOD_CACHE (default data/basketball/cache) and raw play-by-play under
HARDWOOD_PBP (default data/basketball/pbp). `set_data_root` / `set_cache_root` set those variables,
so every model module (which reads them on each call) follows.

Conventions
-----------
* Leagues "nba" / "wnba"; seasons are the ESPN year (NBA 2026-27 = 2027); ids are ESPN ids (str).
* Numbers are rounded at the payload boundary: probabilities 4 dp, ratings 2 dp, rates 3 dp;
  percentages (fmt "pct") are stored as fractions (0.573 = 57.3 %).
* Nothing here raises on missing data: a metric that cannot be computed is None.
"""
from __future__ import annotations

import json
import math
import os
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from oddsmarkets.basketball import canon
from oddsmarkets.basketball.models import _io

LEAGUES = canon.LEAGUES
LEAGUE_NAMES = canon.LEAGUE_NAMES
POOLS = ("G", "F", "C")
POOL_LABELS = {"G": "Guards", "F": "Forwards", "C": "Centres"}
PLACEHOLDER_ABBR = {"TBD", "TBA"}
_STORES: dict[tuple, dict] = {}


# ---------------------------------------------------------------------------------------------- roots

def set_data_root(path: str | Path | None) -> Path:
    """Point every reader and writer at `path` (None restores docs/hardwood/data)."""
    if path:
        os.environ["HARDWOOD_DATA"] = str(Path(path))
    else:
        os.environ.pop("HARDWOOD_DATA", None)
    _clear()
    return data_root()


def set_cache_root(path: str | Path | None) -> None:
    if path:
        os.environ["HARDWOOD_CACHE"] = str(Path(path))
    _clear()


def set_pbp_root(path: str | Path | None) -> None:
    if path:
        os.environ["HARDWOOD_PBP"] = str(Path(path))


def _clear() -> None:
    _STORES.clear()
    try:
        from oddsmarkets.basketball.models import game as _gm
        _gm._PARAMS.clear()
    except Exception:                                            # pragma: no cover - defensive
        pass


def data_root() -> Path:
    return _io.data_root()


def cache_root() -> Path:
    return _io.cache_root()


def pbp_root() -> Path:
    return _io.pbp_root()


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seasons_on_disk(league: str) -> list[int]:
    """Seasons with a store under the data root, oldest first."""
    d = data_root() / str(league)
    try:
        return sorted(int(p.name) for p in d.iterdir() if p.is_dir() and p.name.isdigit() and (p / "store.json").exists())
    except OSError:
        return []


def load_store(league: str, season: int) -> dict:
    """The season store (memoised on its size and mtime); an empty store when missing."""
    from oddsmarkets.basketball import store as _st
    p = _st.season_path(league, season)
    try:
        st = p.stat()
        key = (str(p), st.st_size, st.st_mtime_ns)
    except OSError:
        return _st.new_store(league, season)
    s = _STORES.get(key)
    if s is None:
        for k in [k for k in _STORES if k[0] == str(p)]:
            _STORES.pop(k, None)
        s = _st.load(league, season)
        _STORES[key] = s
    return s


def load_table(league: str, season: int, name: str) -> Any:
    from oddsmarkets.basketball import store as _st
    return _st.load_table(league, season, name)


def has_pbp_dir(league: str, season: int) -> bool:
    d = pbp_root() / str(league) / str(season)
    try:
        return d.exists() and any(d.glob("*.json.gz"))
    except OSError:
        return False


# ---------------------------------------------------------------------------------------------- numbers

def fnum(v: Any) -> float | None:
    """float(v) when finite, else None."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def inum(v: Any) -> int | None:
    x = fnum(v)
    return None if x is None else int(round(x))


def rnd(v: Any, nd: int = 3) -> float | None:
    x = fnum(v)
    return None if x is None else round(x, nd)


def mean(xs: Iterable[Any]) -> float | None:
    v = [x for x in (fnum(x) for x in xs) if x is not None]
    return sum(v) / len(v) if v else None


def median(xs: Iterable[Any]) -> float | None:
    v = sorted(x for x in (fnum(x) for x in xs) if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


def sd(xs: Iterable[Any]) -> float | None:
    v = [x for x in (fnum(x) for x in xs) if x is not None]
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def div(num: Any, den: Any) -> float | None:
    n, d = fnum(num), fnum(den)
    if n is None or not d:
        return None
    return n / d


def per100(x: Any, poss: Any) -> float | None:
    v = div(x, poss)
    return None if v is None else 100.0 * v


def fmt_value(v: Any, fmt: str) -> Any:
    """Round a metric value for its display format (int, 1, 2, 3, pct = fraction 3 dp, pm 2 dp, sec 1 dp, prob 4 dp)."""
    x = fnum(v)
    if x is None:
        return None
    if fmt == "int":
        return int(round(x))
    nd = {"1": 1, "2": 2, "3": 3, "pct": 3, "pm": 2, "sec": 1, "prob": 4}.get(fmt, 3)
    return round(x, nd)


# ---------------------------------------------------------------------------------------------- percentiles

def percentiles(values: dict[str, Any], lower: bool = False) -> dict[str, int]:
    """Field percentile of each value, 100 = best, direction-aware (the F1 helper):

        pct_i = 100 * (W_i + 0.5 * T_i) / (n - 1)

    W_i counts the other entries strictly worse than i (smaller when higher is better; larger
    when `lower`), T_i the other entries tied with i, n the entries with a value. A lone entry
    gets 50; None values are skipped."""
    vals = {k: fnum(v) for k, v in values.items()}
    vals = {k: v for k, v in vals.items() if v is not None}
    n = len(vals)
    if n == 0:
        return {}
    if n == 1:
        return {k: 50 for k in vals}
    items = sorted(vals.values())
    out = {}
    for k, v in vals.items():
        lo, hi = bisect_left(items, v), bisect_right(items, v)
        below, above, tie = lo, n - hi, hi - lo - 1
        worse = above if lower else below
        out[k] = int(round(100.0 * (worse + 0.5 * tie) / (n - 1)))
    return out


def ranks(values: dict[str, Any], lower: bool = False) -> dict[str, int]:
    """Competition rank (1 = best; ties share the better rank)."""
    vals = {k: fnum(v) for k, v in values.items()}
    vals = {k: v for k, v in vals.items() if v is not None}
    items = sorted(vals.values())
    return {k: _rank(items, v, lower) for k, v in vals.items()}


def _rank(sorted_vals: list[float], v: float, lower: bool) -> int:
    return 1 + (bisect_left(sorted_vals, v) if lower else len(sorted_vals) - bisect_right(sorted_vals, v))


def add_percentiles(rows: dict[str, dict], metrics: list[dict], qualified: Iterable[str], pool_of: dict[str, str] | None = None,
                    min_pool: int = 3) -> None:
    """Write "pct" (field), "pct_pool" (position pool) and "rank" onto each row in place.

    Reference distributions are the *qualified* rows (over the minutes floor); every row is placed
    against them, so a part-timer still gets a percentile but cannot move anyone else's. Direction
    comes from each metric's `lower`. A pool with fewer than `min_pool` qualified members gives no
    pool percentile."""
    qual = set(qualified)
    pools: dict[str, list[str]] = {}
    for pid in qual:
        pools.setdefault((pool_of or {}).get(pid) or "-", []).append(pid)
    for r in rows.values():
        r.setdefault("pct", {})
        r.setdefault("pct_pool", {})
        r.setdefault("rank", {})
    for m in metrics:
        k, lower = m["key"], bool(m.get("lower"))
        ref = sorted(v for v in (fnum(rows[p]["values"].get(k)) for p in qual if p in rows) if v is not None)
        refp = {pl: sorted(v for v in (fnum(rows[p]["values"].get(k)) for p in mem if p in rows) if v is not None)
                for pl, mem in pools.items()}
        for pid, r in rows.items():
            v = fnum(r["values"].get(k))
            if v is None:
                continue
            if len(ref) >= 2:
                r["pct"][k] = _place(ref, v, lower)
            pl = (pool_of or {}).get(pid) or "-"
            pv = refp.get(pl) or []
            if len(pv) >= min_pool:
                r["pct_pool"][k] = _place(pv, v, lower)
            if pid in qual and ref:
                r["rank"][k] = _rank(ref, v, lower)


def _place(sorted_vals: list[float], v: float, lower: bool) -> int:
    n = len(sorted_vals)
    lo, hi = bisect_left(sorted_vals, v), bisect_right(sorted_vals, v)
    below, above, ties = lo, n - hi, hi - lo
    rank = (below + 0.5 * ties) / n if not lower else (above + 0.5 * ties) / n
    return int(round(100 * rank))


# ---------------------------------------------------------------------------------------------- catalogue

def metric(key: str, label: str, group: str, fmt: str, lower: bool = False, scope: str = "all", desc: str = "") -> dict:
    """METRIC = {"key","label","group","fmt","lower","scope","desc"} (PAYLOADS.md)."""
    return {"key": key, "label": label, "group": group, "fmt": fmt, "lower": bool(lower), "scope": scope, "desc": desc}


def round_values(values: dict[str, Any], metrics: list[dict]) -> dict[str, Any]:
    fm = {m["key"]: m["fmt"] for m in metrics}
    return {k: fmt_value(values.get(k), fm[k]) for k in fm}


# ---------------------------------------------------------------------------------------------- teams and games

def placeholder_teams(store: dict) -> set[str]:
    """Team ids that are not league members: "TBD" bracket slots, exhibition opponents (national
    teams) that play only preseason games."""
    tdict = store.get("teams") or {}
    out = {t for t, v in tdict.items() if str((v or {}).get("abbr") or "").upper() in PLACEHOLDER_ABBR
           or "tbd" in str((v or {}).get("name") or "").lower()}
    n: dict[str, int] = {}
    for g in (store.get("games") or {}).values():
        if (g or {}).get("stype") in ("reg", "playin", "post", "cup"):
            for t in (str(g.get("home")), str(g.get("away"))):
                n[t] = n.get(t, 0) + 1
    # an All-Star or exhibition side mislabelled as a regular-season game plays once or twice
    med = median(n.values()) or 0
    played = {t for t, k in n.items() if med < 8 or k >= 0.25 * med}
    members = played - out
    if not members:                       # preseason: league members carry a conference, exhibition guests do not
        members = {t for t, v in tdict.items() if (v or {}).get("conference")} - out
    if members:
        out |= {t for t in tdict if t not in members}
    return out


def member_teams(store: dict) -> list[str]:
    bad = placeholder_teams(store)
    return sorted(t for t in (store.get("teams") or {}) if t not in bad)


def superseded(store: dict) -> set[str]:
    """Postponed / cancelled games replayed under another id (same two teams, a later date)."""
    games = store.get("games") or {}
    out = set()
    by_pair: dict[frozenset, list[dict]] = {}
    for g in games.values():
        by_pair.setdefault(frozenset((str(g.get("home")), str(g.get("away")))), []).append(g)
    for g in games.values():
        if g.get("status") not in ("postponed", "canceled"):
            continue
        d = str(g.get("date") or "")
        pair = by_pair.get(frozenset((str(g.get("home")), str(g.get("away"))))) or []
        if any(o is not g and o.get("status") not in ("postponed", "canceled") and str(o.get("date") or "") > d and o.get("stype") == g.get("stype")
               for o in pair):
            out.add(str(g.get("id")))
        elif g.get("status") == "canceled":
            out.add(str(g.get("id")))
    return out


def real_games(store: dict, stypes: Iterable[str] | None = None) -> dict[str, dict]:
    """Games between league members (no TBD slots, no exhibition opponents, no superseded
    postponements, no All-Star games), optionally of the given stypes."""
    bad = placeholder_teams(store)
    sup = superseded(store)
    st = set(stypes) if stypes is not None else None
    out = {}
    for gid, g in (store.get("games") or {}).items():
        if not g or gid in sup or g.get("stype") == "allstar":
            continue
        if str(g.get("home")) in bad or str(g.get("away")) in bad:
            continue
        if st is not None and g.get("stype") not in st:
            continue
        out[gid] = g
    return out


def team_info(store: dict, tid: str) -> dict:
    t = (store.get("teams") or {}).get(str(tid)) or {}
    name = t.get("name") or str(tid)
    loc = t.get("location") or ""
    short = name[len(loc):].strip() if loc and name.startswith(loc) else name.split(" ")[-1]
    return {"name": name, "abbr": t.get("abbr"), "short": short or name, "colour": t.get("colour"), "alt_colour": t.get("alt_colour"),
            "conference": t.get("conference"), "division": t.get("division")}


def player_name(store: dict, pid: str) -> str:
    return str(((store.get("players") or {}).get(str(pid)) or {}).get("name") or pid)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
