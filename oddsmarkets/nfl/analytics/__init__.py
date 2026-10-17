"""
The Quant Gridiron analytics layer: season catalogues by position group (QB, RB, WR, TE, K, P, DEF), teams (unit
ratings, tendencies, pace, fourth-down aggressiveness), game centre pages, weeks, the season page (standings,
simulation odds, draft order, bracket), fourth downs, coaches, referees, leaders, the lab, history (1999 onward,
era-adjusted), awards, markets, the glossary and the player career files. Everything is read from the season stores
(builder A's `oddsmarkets.nfl.store`, or the nflverse schedule when a store is missing), one season of nflverse
play-by-play at a time, and builders B's and C's models; `scripts/build_gridiron.py` writes the payloads described in
`oddsmarkets/nfl/PAYLOADS.md`.

Roots
-----
GRIDIRON_DATA (default docs/gridiron/data) for stores in and payloads out; GRIDIRON_RAW (default data/nfl) for the
nflverse mirror (<raw>/raw/<release>/<file>.parquet) and derived tables; GRIDIRON_CACHE (default data/nfl/cache) for
caches; this layer's own caches live in <cache>/analytics/.

Conventions
-----------
* Seasons are the year the season starts; ids are nflverse game_id, gsis_id player ids and team abbreviations.
* Numbers are rounded at the payload boundary: probabilities 4 dp, EPA 3 dp, fractions 0-1 (fmt "pct", 3 dp).
* Nothing here raises on missing data: a metric that cannot be computed is None; a model that is not ready gives
  {"ok": false} and the metrics that depend on it are None.
"""
from __future__ import annotations

import json
import math
import os
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
FIRST_SEASON = 1999
NFLVERSE_CREDIT = "Data from nflverse (nflfastR, nflreadr, nflverse-data), CC-BY 4.0."
FTN_CREDIT = "FTN Data via nflverse (CC-BY-SA 4.0); derived charting data are shared alike."
NGS_CREDIT = "NFL Next Gen Stats via nflverse, for informational, non-commercial use."
_STORES: dict[tuple, dict] = {}


# ---------------------------------------------------------------------------------------------- roots

def set_data_root(path: str | Path | None) -> Path:
    if path:
        os.environ["GRIDIRON_DATA"] = str(Path(path))
    else:
        os.environ.pop("GRIDIRON_DATA", None)
    _STORES.clear()
    return data_root()


def set_raw_root(path: str | Path | None) -> None:
    if path:
        os.environ["GRIDIRON_RAW"] = str(Path(path))


def set_cache_root(path: str | Path | None) -> None:
    if path:
        os.environ["GRIDIRON_CACHE"] = str(Path(path))


def data_root() -> Path:
    return Path(os.environ.get("GRIDIRON_DATA") or (ROOT / "docs" / "gridiron" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("GRIDIRON_RAW") or (ROOT / "data" / "nfl"))


def cache_root() -> Path:
    return Path(os.environ.get("GRIDIRON_CACHE") or (raw_root() / "cache"))


def an_cache() -> Path:
    return cache_root() / "analytics"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_season(today: date | None = None) -> int:
    """The NFL season in progress (or most recently finished): seasons start in September; Jan-Feb belong to the
    previous season; March-August are the offseason of the season just finished."""
    try:
        from oddsmarkets.nfl import canon
        f = getattr(canon, "current_season", None)
        if f:
            return int(f(today))
    except Exception:                                            # noqa: BLE001
        pass
    d = today or datetime.now(timezone.utc).date()
    return d.year if d.month >= 9 else d.year - 1


def store_path(season: int) -> Path:
    return data_root() / str(int(season)) / "store.json"


def seasons_on_disk() -> list[int]:
    """Seasons with a store under the data root or a play-by-play file under the raw root, oldest first."""
    out: set[int] = set()
    d = data_root()
    try:
        out |= {int(p.name) for p in d.iterdir() if p.is_dir() and p.name.isdigit() and (p / "store.json").exists()}
    except OSError:
        pass
    out |= set(pbp_seasons())
    return sorted(out)


def pbp_seasons() -> list[int]:
    out = set()
    for d in (raw_root() / "raw" / "pbp", raw_root() / "derived"):
        try:
            for p in d.iterdir():
                name = p.stem if p.is_file() else p.name
                digits = "".join(ch for ch in name if ch.isdigit())
                if p.is_file() and p.suffix == ".parquet" and len(digits) == 4:
                    out.add(int(digits))
                elif p.is_dir() and p.name.isdigit() and (p / "plays.parquet").exists():
                    out.add(int(p.name))
        except OSError:
            continue
    return sorted(out)


def load_store(season: int) -> dict:
    """The season store (memoised on size and mtime); {} when missing."""
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
        _STORES[key] = s
    return s


def write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
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
        except Exception:                                        # noqa: BLE001
            return None
    if hasattr(o, "tolist"):
        return clean(o.tolist())
    if hasattr(o, "isoformat"):
        return o.isoformat()
    try:                                                         # pandas NA / NaT
        import pandas as pd
        if pd.isna(o):
            return None
    except Exception:                                            # noqa: BLE001
        pass
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


def rnd(v: Any, nd: int = 3) -> float | None:
    x = fnum(v)
    return None if x is None else round(x, nd)


def div(num: Any, den: Any) -> float | None:
    n, d = fnum(num), fnum(den)
    if n is None or not d:
        return None
    return n / d


def mean(xs: Iterable[Any]) -> float | None:
    v = [x for x in (fnum(x) for x in xs) if x is not None]
    return sum(v) / len(v) if v else None


def sid(x: Any) -> str | None:
    if x is None:
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return None
    s = str(x)
    return s if s and s not in ("nan", "None", "<NA>") else None


FMT_DP = {"1": 1, "2": 2, "3": 3, "pct": 3, "prob": 4, "epa": 3, "yds": 1, "sec": 2, "plus": 0, "int": 0}


def fmt_value(v: Any, fmt: str) -> Any:
    """Round a metric value for its display format: int / plus (integers); 1/2/3 decimals; pct (fraction, 3 dp);
    prob (4 dp); epa (3 dp); yds (1 dp); sec (2 dp)."""
    x = fnum(v)
    if x is None:
        return None
    nd = FMT_DP.get(fmt, 3)
    return int(round(x)) if nd == 0 else round(x, nd)


def age_on(dob: Any, season: int) -> float | None:
    """Age on 1 September of the season, one decimal."""
    try:
        s = str(dob)[:10]
        d = date.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return round((date(int(season), 9, 1) - d).days / 365.25, 1)


# ---------------------------------------------------------------------------------------------- catalogue

# Shrinkage constants k (in the metric's unit) where builder B's stabilise.py has no fit: split-half reliability
# r(n) = n / (n + k) reaches 0.7 at n = 0.7 k / 0.3. Values from published NFL stabilisation work (EPA per dropback
# ~ 400-600 dropbacks for r = 0.5, CPOE ~ 250-300 attempts, rushing efficiency very slow) rounded.
DEFAULT_K = {
    "epa_per_db": 350.0, "epa_per_play": 350.0, "cpoe": 250.0, "success": 300.0, "sack_rate": 120.0, "int_rate": 900.0,
    "adot": 60.0, "ttt": 40.0, "pressure_rate": 150.0, "scramble_rate": 150.0, "pa_rate": 80.0, "twp_rate": 400.0,
    "ryoe": 300.0, "rush_epa": 400.0, "rush_success": 350.0, "explosive": 250.0, "target_share": 25.0, "yprr": 150.0,
    "catch_rate": 150.0, "racr": 100.0, "drop_rate": 200.0, "contested": 60.0, "separation": 50.0, "yacoe": 120.0,
    "rec_epa": 200.0, "fg_oe": 60.0, "punt_net": 60.0, "def_tackles": 300.0, "def_pressure": 300.0,
}


def metric(key: str, label: str, group: str, fmt: str, lower: bool = False, scope: str = "all", desc: str = "",
           den: str | None = None, stab: str | None = None, k: float | None = None) -> dict:
    """METRIC = {key,label,group,fmt,lower,scope,desc,stabilises_at} (PAYLOADS.md) plus private "_den" (the sample
    unit the metric is measured on: plays, dropbacks, attempts, carries, targets, routes, fga, punts) and "_stab"
    (stabilise.py's metric name) / "_k" (a fixed k) for shrinkage; `public_metric` drops the private keys."""
    return {"key": key, "label": label, "group": group, "fmt": fmt, "lower": bool(lower), "scope": scope, "desc": desc,
            "stabilises_at": None, "_den": den, "_stab": stab, "_k": k}


# our "_stab" names -> builder B's stabilise.py metric names (B fits k for these; ours are used otherwise)
B_STAB = {"epa_per_db": "qb_epa_db", "cpoe": "cpoe", "sack_rate": "sack_rate", "int_rate": "int_rate", "twp_rate": "twp_rate",
          "ryoe": "ryoe_att", "rush_success": "rush_success", "catch_rate": "croe", "yacoe": "yacoe", "rec_epa": "epa_target",
          "fg_oe": "fgoe"}


def stab_k(m: dict) -> float | None:
    """The shrinkage constant: builder B's fitted k (stabilise.shrink_k) for metrics B covers, else the default table,
    else the metric's fixed "_k"."""
    name = m.get("_stab")
    if name:
        if name in B_STAB:
            try:
                from oddsmarkets.nfl.models import stabilise
                v = fnum(stabilise.shrink_k(B_STAB[name]))
                if v:
                    return v
            except Exception:                                    # noqa: BLE001
                pass
        if name in DEFAULT_K:
            return DEFAULT_K[name]
    return fnum(m.get("_k"))


def stab_point(m: dict) -> float | None:
    """The sample at which split-half reliability reaches 0.7: n = 0.7 k / 0.3 (stabilise.point's formula)."""
    k = stab_k(m)
    return round(k * 0.7 / 0.3, 0) if k else None


def public_metric(m: dict) -> dict:
    out = {k: v for k, v in m.items() if not k.startswith("_")}
    if out.get("stabilises_at") is None:
        out["stabilises_at"] = stab_point(m)
    if m.get("_den"):
        out["unit"] = m["_den"]
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
    """Field percentile of each value, 100 = best, direction-aware: 100 (W + T/2) / (n - 1), W the entries strictly
    worse, T the other entries tied; a lone entry gets 50."""
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
    """Stabilisation shrinkage toward the reference mean: (n v + k m) / (n + k)."""
    if v is None:
        return None
    if not k or m is None or n is None:
        return v
    return (n * v + k * m) / (n + k)


def add_percentiles(rows: dict[str, dict], metrics: list[dict], reference: Iterable[str], pos_of: dict[str, str] | None = None,
                    floors: dict[str, float] | None = None, min_pos: int = 5) -> dict:
    """Write "pct" (v the group's reference pool) and "pct_pos" (v the same listed position) on each row in place.

    * Reference: the qualified rows; every row with enough sample is placed against them (a part-timer gets a
      percentile but cannot move anyone else's).
    * Sample floor: a metric is placed only when the row's denominator rows[pid]["n"][den] reaches floors[den].
    * Shrinkage: the value placed is (n v + k m) / (n + k) with the metric's stabilisation k (stab_k); displayed
      values are never shrunk.
    * Direction: the metric's `lower` (100 = best).
    Returns {key: reference mean}."""
    ref = set(reference)
    floors = floors or {}
    poss: dict[str, list[str]] = {}
    for pid in ref:
        if pid in rows:
            poss.setdefault((pos_of or {}).get(pid) or "-", []).append(pid)
    for r in rows.values():
        r.setdefault("pct", {})
        r.setdefault("pct_pos", {})
    means = {}
    for m in metrics:
        key, lower, den = m["key"], bool(m.get("lower")), m.get("_den")
        if m.get("fmt") == "int" and not m.get("_pct_int"):
            continue
        k = stab_k(m) if den else None
        rv = [fnum(rows[p]["values"].get(key)) for p in ref if p in rows]
        rv = [v for v in rv if v is not None]
        if len(rv) < 2:
            continue
        mu = sum(rv) / len(rv)
        means[key] = mu

        def sval(pid: str) -> float | None:
            v = fnum(rows[pid]["values"].get(key))
            if v is None:
                return None
            n = fnum((rows[pid].get("n") or {}).get(den)) if den else None
            if den and floors.get(den) is not None and (n or 0) < floors[den]:
                return None
            return shrunk(v, n, k, mu) if den else v
        sv = {pid: sval(pid) for pid in rows}
        refv = sorted(v for p, v in sv.items() if p in ref and v is not None)
        if len(refv) < 2:
            continue
        refp = {ps: sorted(v for v in (sv.get(p) for p in mem) if v is not None) for ps, mem in poss.items()}
        for pid, v in sv.items():
            if v is None:
                continue
            rows[pid]["pct"][key] = _place(refv, v, lower)
            pv = refp.get((pos_of or {}).get(pid) or "-") or []
            if len(pv) >= min_pos:
                rows[pid]["pct_pos"][key] = _place(pv, v, lower)
    return means


def finish(rows: dict[str, dict], metrics: list[dict], reference: list[str], pos_of: dict[str, str],
           floors: dict[str, float]) -> dict:
    """Percentiles (shrunk for placement) then rounding; drops the private "n" block; returns the targets."""
    means = add_percentiles(rows, metrics, reference, pos_of, floors)
    for r in rows.values():
        r["values"] = round_values(r["values"], metrics)
        r["pct"] = {k: v for k, v in r["pct"].items() if r["values"].get(k) is not None}
        r["pct_pos"] = {k: v for k, v in r["pct_pos"].items() if r["values"].get(k) is not None}
    return means


def ranks(values: dict[str, Any], lower: bool = False) -> dict[str, int]:
    vals = {k: fnum(v) for k, v in values.items()}
    vals = {k: v for k, v in vals.items() if v is not None}
    items = sorted(vals.values())
    return {k: 1 + (bisect_left(items, v) if lower else len(items) - bisect_right(items, v)) for k, v in vals.items()}


def cols_rows(records: list[dict], cols: list[str]) -> dict:
    return {"cols": cols, "rows": [[r.get(c) for c in cols] for r in records]}
