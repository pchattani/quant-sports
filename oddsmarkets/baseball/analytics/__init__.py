"""
The Quant Bullpen analytics layer: season catalogues (hitters, pitchers, fielders and catchers, teams),
game centre pages, umpires, parks, the season page (standings, simulation, bracket), leaders, history,
prospects, awards, markets, the lab, the glossary and the player career files, all read from the season
stores (`oddsmarkets.baseball.store`), one season's Statcast pitch table at a time and builders B's, C's
and D's models, and written by `scripts/build_bullpen.py` as the payloads in
`oddsmarkets/baseball/PAYLOADS.md`.

Roots
-----
One data root for stores in and payloads out: `docs/bullpen/data` unless BULLPEN_DATA points elsewhere
(tests build into a temporary folder); raw data under BULLPEN_RAW (default data/baseball) and caches under
BULLPEN_CACHE (default data/baseball/cache); this layer's own caches live in <cache>/analytics/.
`set_data_root` / `set_raw_root` / `set_cache_root` set those variables, so every model module (which reads
them on each call) follows.

Conventions
-----------
* Levels "mlb" / "aaa"; seasons are calendar years; ids are MLBAM ids as strings (Retrosheet-only players
  "r:<retroid>"), teams MLBAM team ids, games gamePk strings.
* Numbers are rounded at the payload boundary: probabilities 4 dp, rates 3 dp, "plus" scores integers;
  percentages (fmt "pct") are stored as fractions (0.273 = 27.3 %).
* Nothing here raises on missing data: a metric that cannot be computed is None, a model that is not
  ready yields {"ok": false} and the metrics that depend on it are None.
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
LEVELS = ("mlb", "aaa")
# OAA shrinkage k in chances (fielding percentiles): our year-to-year M50 is about 480 chances and the odd/even-game
# M50 355 (outfield) to 501 (infield) (docs/METRICS_SPEC.md, baseball stabilisation); 60 was 6-8x too light
OAA_K = 400.0
LEVEL_NAMES = {"mlb": "MLB", "aaa": "Triple-A"}
RETRO_NOTICE = ('The information used here was obtained free of charge from and is copyrighted by Retrosheet. '
                'Interested parties may contact Retrosheet at "www.retrosheet.org".')
CHADWICK_ATTRIBUTION = "Player identifiers from the Chadwick Baseball Bureau register (ODC-BY 1.0)."
LAHMAN_ATTRIBUTION = "Lahman Baseball Database (CC BY-SA 3.0)."
_STORES: dict[tuple, dict] = {}


# ---------------------------------------------------------------------------------------------- roots

def set_data_root(path: str | Path | None) -> Path:
    if path:
        os.environ["BULLPEN_DATA"] = str(Path(path))
    else:
        os.environ.pop("BULLPEN_DATA", None)
    _STORES.clear()
    return data_root()


def set_raw_root(path: str | Path | None) -> None:
    if path:
        os.environ["BULLPEN_RAW"] = str(Path(path))


def set_cache_root(path: str | Path | None) -> None:
    if path:
        os.environ["BULLPEN_CACHE"] = str(Path(path))


def data_root() -> Path:
    return Path(os.environ.get("BULLPEN_DATA") or (ROOT / "docs" / "bullpen" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("BULLPEN_RAW") or (ROOT / "data" / "baseball"))


def cache_root() -> Path:
    return Path(os.environ.get("BULLPEN_CACHE") or (raw_root() / "cache"))


def an_cache() -> Path:
    return cache_root() / "analytics"


def pitch_path(level: str, season: int) -> Path:
    return raw_root() / "statcast" / str(level) / f"{int(season)}.parquet"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seasons_on_disk(level: str) -> list[int]:
    """Seasons with a store under the data root, oldest first."""
    d = data_root() / str(level)
    try:
        return sorted(int(p.name) for p in d.iterdir() if p.is_dir() and p.name.isdigit() and (p / "store.json").exists())
    except OSError:
        return []


def pitch_seasons(level: str) -> list[int]:
    d = raw_root() / "statcast" / str(level)
    try:
        return sorted(int(p.stem) for p in d.glob("*.parquet") if p.stem.isdigit())
    except OSError:
        return []


def load_store(level: str, season: int) -> dict:
    """The season store (memoised on its size and mtime); {} when missing."""
    p = data_root() / str(level) / str(int(season)) / "store.json"
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


def load_people() -> dict:
    return read_json(data_root() / "people.json") or {}


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


def median(xs: Iterable[Any]) -> float | None:
    v = sorted(x for x in (fnum(x) for x in xs) if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


def fmt_value(v: Any, fmt: str) -> Any:
    """Round a metric value for its display format: int; 1/2/3 decimals; pct (fraction, 3 dp); prob (4 dp);
    plus (integer, 100 = average); rv (runs, 1 dp); mph/ft/in/deg (1 dp); rpm (int)."""
    x = fnum(v)
    if x is None:
        return None
    if fmt in ("int", "plus", "rpm"):
        return int(round(x))
    nd = {"1": 1, "2": 2, "3": 3, "pct": 3, "prob": 4, "rv": 1, "mph": 1, "ft": 1, "in": 1, "deg": 1, "war": 1,
          "pm": 2}.get(fmt, 3)
    return round(x, nd)


def age_on(dob: Any, season: int) -> float | None:
    """Age on 30 June of the season (the baseball age convention), one decimal."""
    try:
        s = str(dob)[:10]
        d = date.fromisoformat(s) if len(s) == 10 else date(int(s[:4]), 7, 1)
    except (TypeError, ValueError):
        return None
    ref = date(int(season), 6, 30)
    return round((ref - d).days / 365.25, 1)


# ---------------------------------------------------------------------------------------------- catalogue

def metric(key: str, label: str, group: str, fmt: str, lower: bool = False, scope: str = "all", desc: str = "",
           den: str | None = None, stab: str | None = None, k: float | None = None) -> dict:
    """METRIC = {"key","label","group","fmt","lower","scope","desc","stabilises_at"} (PAYLOADS.md), plus the
    private "_den" (the sample the metric is measured on: pa, bip, pitches, swings, bf, ...) and "_stab" (the
    stabilise.py metric whose k shrinks it, or "_k" a fixed k) used for shrinkage; they are dropped from
    payloads by `public_metric`."""
    return {"key": key, "label": label, "group": group, "fmt": fmt, "lower": bool(lower), "scope": scope, "desc": desc,
            "stabilises_at": None, "_den": den, "_stab": stab, "_k": k}


def stab_k(m: dict, level: str = "mlb") -> float | None:
    """The shrinkage constant of a metric: stabilise.py's fitted k for its "_stab" metric (default table when
    the fit is not committed), else its fixed "_k"."""
    if m.get("_stab"):
        try:
            from oddsmarkets.baseball.models import stabilise
            return float(stabilise.shrink_k(m["_stab"], "mlb"))
        except Exception:                                        # noqa: BLE001
            return None
    return fnum(m.get("_k"))


def stab_point(m: dict) -> float | None:
    """The sample at which the metric's split-half reliability reaches 0.7 (stabilise.point), or 0.7/0.3 k."""
    if m.get("_stab"):
        try:
            from oddsmarkets.baseball.models import stabilise
            return round(float(stabilise.point(m["_stab"], "mlb")), 0)
        except Exception:                                        # noqa: BLE001
            return None
    k = fnum(m.get("_k"))
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
    """Field percentile of each value, 100 = best, direction-aware: pct_i = 100 (W_i + T_i / 2) / (n - 1) with
    W_i the entries strictly worse than i and T_i the ties; a lone entry gets 50."""
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


def add_percentiles(rows: dict[str, dict], metrics: list[dict], reference: Iterable[str], role_of: dict[str, str] | None = None,
                    floors: dict[str, float] | None = None, level: str = "mlb", min_role: int = 5) -> dict:
    """Write "pct" (v the reference pool) and "pct_role" (v the same position / role) onto each row in place.

    * Reference distribution: the rows in `reference` (the sample floor that defines a regular, e.g. 2.1 PA
      per team game); every row with enough sample is placed against it, so a part-timer gets a percentile
      but cannot move anyone else's.
    * Sample floor: a row gets a percentile on a metric only when its denominator for that metric
      (rows[pid]["n"][den]) reaches floors[den] (e.g. 25 PA, 15 balls in play).
    * Shrinkage: the value placed is shrunk toward the reference mean with the metric's stabilisation k
      (stab_k): v_s = (n v + k m) / (n + k), so a 60-PA hot streak is pulled toward average by as much as
      its reliability says. The reference rows are shrunk the same way. Displayed values are never shrunk.
    * Direction from the metric's `lower` (100 = best).
    Returns {key: reference mean} (the shrinkage targets)."""
    ref = set(reference)
    floors = floors or {}
    roles: dict[str, list[str]] = {}
    for pid in ref:
        if pid in rows:
            roles.setdefault((role_of or {}).get(pid) or "-", []).append(pid)
    for r in rows.values():
        r.setdefault("pct", {})
        r.setdefault("pct_role", {})
    means = {}
    for m in metrics:
        key, lower, den = m["key"], bool(m.get("lower")), m.get("_den")
        if m.get("fmt") == "int" and not m.get("_pct_int"):
            continue
        k = stab_k(m, level) if den else None
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
            return shrunk(v, n, k, mu) if den else v
        sv = {pid: sval(pid) for pid in rows}
        refv = sorted(v for p, v in sv.items() if p in ref and v is not None)
        if len(refv) < 2:
            continue
        refr = {rl: sorted(v for v in (sv.get(p) for p in mem) if v is not None) for rl, mem in roles.items()}
        for pid, v in sv.items():
            if v is None:
                continue
            rows[pid]["pct"][key] = _place(refv, v, lower)
            pv = refr.get((role_of or {}).get(pid) or "-") or []
            if len(pv) >= min_role:
                rows[pid]["pct_role"][key] = _place(pv, v, lower)
    return means


def ranks(values: dict[str, Any], lower: bool = False) -> dict[str, int]:
    vals = {k: fnum(v) for k, v in values.items()}
    vals = {k: v for k, v in vals.items() if v is not None}
    items = sorted(vals.values())
    return {k: 1 + (bisect_left(items, v) if lower else len(items) - bisect_right(items, v)) for k, v in vals.items()}


# ---------------------------------------------------------------------------------------------- store helpers

def team_info(store: dict, tid: Any) -> dict:
    from oddsmarkets.baseball import canon
    t = (store.get("teams") or {}).get(str(tid)) or {}
    # alt: the second kit colour (canon.ALT, MLB only) for the Broadcast hero's clash rule
    return {"id": str(tid), "name": t.get("name") or str(tid), "abbr": t.get("abbr"), "short": t.get("short") or t.get("name"),
            "league": t.get("league"), "division": t.get("division"), "colour": t.get("colour"),
            "alt": t.get("alt") or canon.team_alt(tid), "venue": t.get("venue")}


def abbr_to_tid(store: dict) -> dict[str, str]:
    """Team abbreviation (store and Savant spellings) -> team id."""
    out: dict[str, str] = {}
    for tid, t in (store.get("teams") or {}).items():
        if (t or {}).get("abbr"):
            out[str(t["abbr"]).upper()] = str(tid)
    try:
        from oddsmarkets.baseball import canon
        for ab in list(out) + ["AZ", "ARI", "ATH", "OAK", "CWS", "CHW", "KC", "KCR", "SD", "SDP", "SF", "SFG", "TB", "TBR",
                              "WSH", "WSN", "LAA", "ANA", "MIA", "FLA"]:
            if ab not in out:
                t = canon.tid_from_abbr(ab)
                if t and str(t) in (store.get("teams") or {}):
                    out[ab] = str(t)
    except Exception:                                            # noqa: BLE001
        pass
    return out


def real_teams(store: dict) -> list[str]:
    return sorted(t for t, v in (store.get("teams") or {}).items() if not (v or {}).get("placeholder") and (v or {}).get("league"))


def player_name(store: dict, pid: Any, people: dict | None = None) -> str:
    p = (store.get("players") or {}).get(str(pid)) or {}
    if p.get("name"):
        return p["name"]
    q = (people or {}).get(str(pid)) or {}
    return q.get("name") or str(pid)
