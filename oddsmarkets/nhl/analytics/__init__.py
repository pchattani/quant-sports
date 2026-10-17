"""
The Quant Rink analytics layer: season catalogues (skaters, goalies, teams, lines), game centre pages, the season
page (standings, simulation, lottery, bracket), leaders, the lab, awards, markets, history, the glossary and the
player career files, read from builder A's season stores and derived event / stint tables (one season at a time)
and builders B's and C's models, and written by `scripts/build_rink.py` as the payloads in
`oddsmarkets/nhl/PAYLOADS.md`.

Roots
-----
One data root for stores in and payloads out: `docs/rink/data` unless RINK_DATA points elsewhere (tests build into
a temporary folder); raw data under RINK_RAW (default data/nhl) and caches under RINK_CACHE (default
data/nhl/cache); this layer's own caches live in <cache>/analytics/. `set_data_root` / `set_raw_root` /
`set_cache_root` set those variables, so every model module (which reads them on each call) follows.

Conventions
-----------
* Seasons are NHL ids (20262027); games NHL gameIds as strings; players NHL playerIds as strings; teams tri-codes.
* Numbers are rounded at the payload boundary: probabilities 4 dp, rates per 60 2 dp, fractions 3 dp.
* Nothing here raises on missing data: a metric that cannot be computed is None, a model that is not ready yields
  {"ok": false} and the metrics that depend on it are None.
"""
from __future__ import annotations

import json
import math
import os
import re
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
FIRST_SEASON = 19171918
PBP_FIRST = 20092010          # play-by-play with coordinates (careers' "current"-style blocks from here)
SHIFTS_FIRST = 20102011
EDGE_FIRST = 20212022
MONEYPUCK_CREDIT = "xG benchmark data from MoneyPuck.com"
_STORES: dict[tuple, dict] = {}


# ---------------------------------------------------------------------------------------------- roots

def set_data_root(path: str | Path | None) -> Path:
    if path:
        os.environ["RINK_DATA"] = str(Path(path))
    else:
        os.environ.pop("RINK_DATA", None)
    _STORES.clear()
    return data_root()


def set_raw_root(path: str | Path | None) -> None:
    if path:
        os.environ["RINK_RAW"] = str(Path(path))


def set_cache_root(path: str | Path | None) -> None:
    if path:
        os.environ["RINK_CACHE"] = str(Path(path))


def data_root() -> Path:
    return Path(os.environ.get("RINK_DATA") or (ROOT / "docs" / "rink" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("RINK_RAW") or (ROOT / "data" / "nhl"))


def cache_root() -> Path:
    return Path(os.environ.get("RINK_CACHE") or (raw_root() / "cache"))


def an_cache() -> Path:
    return cache_root() / "analytics"


def derived_dir(season: int) -> Path:
    return raw_root() / "derived" / str(int(season))


def events_path(season: int) -> Path:
    return derived_dir(season) / "events.parquet"


def stints_path(season: int) -> Path:
    return derived_dir(season) / "stints.parquet"


def store_path(season: int) -> Path:
    return data_root() / str(int(season)) / "store.json"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------------------------- seasons

def season_id(start_year: int) -> int:
    return int(start_year) * 10000 + int(start_year) + 1


def start_year(season: int) -> int:
    s = int(season)
    return s // 10000 if s > 9999 else s


def end_year(season: int) -> int:
    s = int(season)
    return s % 10000 if s > 9999 else s + 1


def season_label(season: int) -> str:
    return f"{start_year(season)}-{str(end_year(season))[-2:]}"


def prev_season(season: int) -> int:
    return season_id(start_year(season) - 1)


def current_season(today: date | None = None) -> int:
    """The NHL season in progress or next to start: from 1 July the season starting that autumn (builder A's canon
    when it answers)."""
    try:
        from oddsmarkets.nhl import canon
        f = getattr(canon, "current_season", None)
        if f is not None:
            v = f(today) if today is not None else f()
            if v:
                return int(v)
    except Exception:                                            # noqa: BLE001
        pass
    d = today or datetime.now(timezone.utc).date()
    return season_id(d.year if d.month >= 7 else d.year - 1)


def seasons_on_disk() -> list[int]:
    """Seasons with a store under the data root or derived events under the raw root, oldest first."""
    out = set()
    try:
        for p in data_root().iterdir():
            if p.is_dir() and p.name.isdigit() and len(p.name) == 8 and (p / "store.json").exists():
                out.add(int(p.name))
    except OSError:
        pass
    try:
        for p in (raw_root() / "derived").iterdir():
            if p.is_dir() and p.name.isdigit() and len(p.name) == 8 and (p / "events.parquet").exists():
                out.add(int(p.name))
    except OSError:
        pass
    return sorted(out)


def load_store(season: int) -> dict:
    """The season store (memoised on its size and mtime); {} when missing."""
    p = store_path(season)
    try:
        st = p.stat()
        key = (str(p), st.st_size, st.st_mtime_ns)
    except OSError:
        return {}
    s = _STORES.get(key)
    if s is None:
        for k in [k for k in _STORES if k[0] == str(p)]:
            _STORES.pop(k, None)
        s = read_json(p) or {}
        _STORES.clear()                                          # one season's store in memory at a time
        _STORES[key] = s
    return s


# ---------------------------------------------------------------------------------------------- json

def write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    try:
        p = Path(path)
        if p.name.endswith(".gz"):
            import gzip
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
        return None


def clean(o: Any) -> Any:
    """JSON-safe copy: NaN/inf -> None, numpy scalars -> Python, tuples/sets -> lists, keys -> str."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [clean(v) for v in o]
    if isinstance(o, bool) or o is None or isinstance(o, (str, int)):
        return o
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            return clean(o.item())
        except Exception:                                        # pragma: no cover - defensive
            return None
    if hasattr(o, "tolist"):
        return clean(o.tolist())
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return o


# ---------------------------------------------------------------------------------------------- numbers

def fnum(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def inum(v: Any) -> int | None:
    x = fnum(v)
    return None if x is None else int(round(x))


def sid(v: Any) -> str | None:
    """An id as a string ("8478402"), None for empty / NaN; floats that are whole numbers lose their ".0"."""
    if v is None:
        return None
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        if v.is_integer():
            return str(int(v))
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "null", "<na>"):
        return None
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def rnd(v: Any, nd: int = 3) -> float | None:
    x = fnum(v)
    return None if x is None else round(x, nd)


def div(num: Any, den: Any) -> float | None:
    n, d = fnum(num), fnum(den)
    if n is None or not d:
        return None
    return n / d


def per60(num: Any, toi_sec: Any) -> float | None:
    n, t = fnum(num), fnum(toi_sec)
    if n is None or not t:
        return None
    return 3600.0 * n / t


def mean(xs: Iterable[Any]) -> float | None:
    v = [x for x in (fnum(x) for x in xs) if x is not None]
    return sum(v) / len(v) if v else None


def fmt_value(v: Any, fmt: str) -> Any:
    """Round a metric value for its display format: int; 1/2/3 decimals; pct (fraction 0-1, 3 dp); prob (4 dp);
    p60 (per 60, 2 dp); toi_min (minutes, 1 dp); toi (seconds, integer); goals (2 dp); plus (integer, 100 = average)."""
    x = fnum(v)
    if x is None:
        return None
    if fmt in ("int", "plus"):
        return int(round(x))
    nd = {"1": 1, "2": 2, "3": 3, "pct": 3, "prob": 4, "p60": 2, "toi": 0, "toi_min": 1, "goals": 2, "mph": 1, "kmh": 1, "ft": 1, "deg": 1,
          "sec": 1}.get(fmt, 3)
    return round(x, nd)


def age_on(dob: Any, season: int) -> float | None:
    """Age on 1 February of the season (mid-season), one decimal."""
    try:
        s = str(dob)[:10]
        d = date.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    ref = date(end_year(season), 2, 1)
    return round((ref - d).days / 365.25, 1)


# ---------------------------------------------------------------------------------------------- catalogue

def metric(key: str, label: str, group: str, fmt: str, lower: bool = False, scope: str = "all", desc: str = "",
           den: str | None = None, stab: str | None = None, k: float | None = None, pct: bool = True) -> dict:
    """METRIC = {"key","label","group","fmt","lower","scope","desc","stabilises_at"} (PAYLOADS.md), plus the private
    "_den" (the sample the metric is measured on: toi5 seconds, shots, faceoffs, ...), "_stab" (the stabilise.py
    metric whose k shrinks it) or "_k" (a fixed k in the den's unit) and "_pct" (False: no percentile, e.g. counts of
    games); the private keys are dropped from payloads by `public_metric`."""
    return {"key": key, "label": label, "group": group, "fmt": fmt, "lower": bool(lower), "scope": scope, "desc": desc,
            "stabilises_at": None, "_den": den, "_stab": stab, "_k": k, "_pct": pct}


DEN_UNIT = {"toi": "minutes", "toi5": "5v5 minutes", "toipp": "PP minutes", "toipk": "PK minutes", "shots": "shots", "fo": "faceoffs",
            "sa": "shots faced", "fa": "unblocked shots faced", "gp": "games", "att": "unblocked attempts", "pen": "minor penalties",
            "fen": "unblocked attempts faced"}
# k in seconds for the time-based denominators is converted to the unit shown (minutes) for stabilises_at
_TIME_DENS = {"toi", "toi5", "toipp", "toipk"}


def stab_k(m: dict) -> float | None:
    """The shrinkage constant of a metric in its denominator's unit: builder B's stabilise.py k for its "_stab"
    metric when fitted, else the fixed "_k"."""
    if m.get("_stab"):
        try:
            from oddsmarkets.nhl.analytics import adapters
            k = adapters.stab_k(m["_stab"])
            if k is not None:
                return float(k)
        except Exception:                                        # noqa: BLE001
            pass
    return fnum(m.get("_k"))


def stab_point(m: dict) -> float | None:
    """The sample at which split-half reliability reaches 0.7: n_0.7 = 0.7 k / 0.3 (builder B's stabilise.point when
    it answers); time denominators reported in minutes."""
    pt = None
    if m.get("_stab"):
        try:
            from oddsmarkets.nhl.analytics import adapters
            pt = adapters.stab_point(m["_stab"])
        except Exception:                                        # noqa: BLE001
            pt = None
    if pt is None:
        k = stab_k(m)
        pt = k * 0.7 / 0.3 if k else None
    if pt is None:
        return None
    if m.get("_den") in _TIME_DENS:
        pt = pt / 60.0
    return round(float(pt), 0)


def public_metric(m: dict) -> dict:
    out = {k: v for k, v in m.items() if not k.startswith("_")}
    if out.get("stabilises_at") is None:
        out["stabilises_at"] = stab_point(m)
    if m.get("_den"):
        out["unit"] = DEN_UNIT.get(m["_den"], m["_den"])
    return out


def round_values(values: dict[str, Any], metrics: list[dict]) -> dict[str, Any]:
    return {m["key"]: fmt_value(values.get(m["key"]), m["fmt"]) for m in metrics}


def _place(sorted_vals: list[float], v: float, lower: bool) -> int:
    n = len(sorted_vals)
    lo, hi = bisect_left(sorted_vals, v), bisect_right(sorted_vals, v)
    below, above, ties = lo, n - hi, hi - lo
    rank = (below + 0.5 * ties) / n if not lower else (above + 0.5 * ties) / n
    return max(0, min(100, int(round(100 * rank))))


def percentiles(values: dict[str, Any], lower: bool = False) -> dict[str, int]:
    """Field percentile of each value, 100 = best, direction-aware: pct_i = 100 (W_i + T_i / 2) / (n - 1) with W_i
    the entries strictly worse than i and T_i the other ties; a lone entry gets 50."""
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


def shrunk(v: float | None, n: float | None, k: float | None, m: float | None) -> float | None:
    """Stabilisation-based shrinkage toward the reference mean: (n v + k m) / (n + k)."""
    if v is None:
        return None
    if not k or m is None or n is None:
        return v
    return (n * v + k * m) / (n + k)


def add_percentiles(rows: dict[str, dict], metrics: list[dict], reference: Iterable[str], pos_of: dict[str, str] | None = None,
                    floors: dict[str, float] | None = None, min_pos: int = 5, default_den: str | None = None) -> dict:
    """Write "pct" (v the reference pool) and "pct_pos" (v the same position group) onto each row in place.

    * Reference distribution: the rows in `reference` (the qualified pool); every row with enough sample is placed
      against it, so a call-up gets a percentile but cannot move anyone else's.
    * Sample floor: a row gets a percentile on a metric only when its denominator (rows[pid]["n"][den]) reaches
      floors[den]. Metrics without a denominator (counting stats, GSAx, RAPM, Rink value) are held to the floor of
      `default_den` (games played in the catalogues), unshrunk: one game's goals or GAR ranks no one, and the pool
      they are placed against is the players at or above that floor.
    * Shrinkage: the value placed is shrunk toward the reference mean with the metric's stabilisation k:
      v_s = (n v + k m) / (n + k). Displayed values are never shrunk.
    * Direction from the metric's `lower` (100 = best).
    Returns {key: reference mean}."""
    ref = set(reference)
    floors = floors or {}
    groups: dict[str, list[str]] = {}
    for pid in ref:
        if pid in rows:
            groups.setdefault((pos_of or {}).get(pid) or "-", []).append(pid)
    for r in rows.values():
        r.setdefault("pct", {})
        r.setdefault("pct_pos", {})
    means = {}
    for m in metrics:
        key, lower, den = m["key"], bool(m.get("lower")), m.get("_den")
        if m.get("_pct") is False:
            continue
        k = stab_k(m) if den else None
        rv = [fnum(rows[p]["values"].get(key)) for p in ref if p in rows]
        rv = [v for v in rv if v is not None]
        if len(rv) < 2:
            continue
        mu = sum(rv) / len(rv)
        means[key] = mu

        def sval(pid):
            v = fnum(rows[pid]["values"].get(key))
            if v is None:
                return None
            n = fnum((rows[pid].get("n") or {}).get(den)) if den else None
            if den and floors.get(den) is not None and (n or 0) < floors[den]:
                return None
            if not den and default_den and floors.get(default_den) is not None:
                n0 = fnum((rows[pid].get("n") or {}).get(default_den))
                if (n0 or 0) < floors[default_den]:
                    return None
            return shrunk(v, n, k, mu) if den else v
        sv = {pid: sval(pid) for pid in rows}
        refv = sorted(v for p, v in sv.items() if p in ref and v is not None)
        if len(refv) < 2:
            continue
        refg = {g: sorted(v for v in (sv.get(p) for p in mem) if v is not None) for g, mem in groups.items()}
        for pid, v in sv.items():
            if v is None:
                continue
            rows[pid]["pct"][key] = _place(refv, v, lower)
            pv = refg.get((pos_of or {}).get(pid) or "-") or []
            if len(pv) >= min_pos:
                rows[pid]["pct_pos"][key] = _place(pv, v, lower)
    return means


def finish(rows: dict[str, dict], metrics: list[dict], reference: list[str], pos_of: dict[str, str], floors: dict[str, float],
           default_den: str | None = "gp") -> dict:
    """Percentiles (on raw values, shrunk for placement) then rounding; drops the private sample counts. Metrics with
    no denominator need floors[default_den] (games played) before they get a percentile."""
    means = add_percentiles(rows, metrics, reference, pos_of, floors, default_den=default_den)
    for r in rows.values():
        r["values"] = round_values(r["values"], metrics)
        r["pct"] = {k: v for k, v in r["pct"].items() if r["values"].get(k) is not None}
        r["pct_pos"] = {k: v for k, v in r["pct_pos"].items() if r["values"].get(k) is not None}
        r.pop("n", None)
    return means


def ranks(values: dict[str, Any], lower: bool = False) -> dict[str, int]:
    vals = {k: fnum(v) for k, v in values.items()}
    vals = {k: v for k, v in vals.items() if v is not None}
    items = sorted(vals.values())
    return {k: 1 + (bisect_left(items, v) if lower else len(items) - bisect_right(items, v)) for k, v in vals.items()}


_BUILDER = re.compile(r"\s*\(?\b[Bb]uilders? [A-F](?:'s)?(?: and [A-F](?:'s)?)?\)?:?\s*")


def scrub(x: Any) -> Any:
    """Published text without internal builder references ("builder B's xG" -> "xG")."""
    if isinstance(x, str):
        return _BUILDER.sub(" ", x).strip()
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items()}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    return x


def pos_group(pos: Any) -> str:
    """"F" (C, L, R, LW, RW, F), "D" or "G"."""
    p = str(pos or "").upper()
    if p.startswith("G"):
        return "G"
    if p.startswith("D"):
        return "D"
    return "F"
