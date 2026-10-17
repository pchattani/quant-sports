"""
The Quant Paddock analytics layer: season catalogues for drivers and teams, the race
centre, per-race awards, circuit pages and the glossary, all read from the season
stores (`oddsmarkets.f1.store`), the OpenF1 session records and the pace/simulation
models, and written by `scripts/build_paddock.py` as the payloads in PAYLOADS.md.

Data root
---------
Everything (season stores, OpenF1 session records, processed telemetry, and the
payloads the build writes) lives under one directory, `docs/paddock/data` by default.
`set_data_root(path)` (or the environment variable PADDOCK_DATA, read by
`data_root()` on first use) points every reader at another directory, so tests can
build into a temporary folder without touching the committed data. Model caches
(`data/f1/cache`) can be redirected the same way with `set_cache_root(path)` or
PADDOCK_CACHE.

Conventions
-----------
* Drivers are keyed by Jolpica driverId, teams by constructorId, circuits by circuitId.
* Numbers are rounded at the payload boundary: probabilities 4 dp, seconds 3 dp, ms integers.
* Nothing here raises on missing data: a metric that cannot be computed is None.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Iterable

from oddsmarkets.f1 import canon
from oddsmarkets.f1 import store as _store
from oddsmarkets.f1.sources import openf1 as _openf1

_DEFAULT_DATA = _store.DATA
_ROOT_SET = False


def _clear_caches() -> None:
    """Forget every in-memory cache keyed by year (stores, session indexes, circuit records)."""
    for name in ("_STORES", "_SESS_INDEX", "_SESS_RECS", "_HEADERS"):
        c = getattr(canon, name, None)
        if isinstance(c, dict):
            c.clear()
    try:
        from oddsmarkets.f1.models import circuits as _circ
        _circ._load_cached.cache_clear()
        _circ._RECORDS_MEM = None
        _circ._PROFILE_CACHE.clear()
    except Exception:                                            # pragma: no cover - defensive
        pass
    try:
        from oddsmarkets.f1.models import race_sim as _rs
        _rs._A_MEMO.clear()
    except Exception:                                            # pragma: no cover - defensive
        pass
    try:
        from oddsmarkets.f1.analytics import context as _ctx
        from oddsmarkets.f1.analytics import forecasts as _fc
        _ctx.reset()
        _fc._DIGESTS.clear()
    except Exception:                                            # pragma: no cover - defensive
        pass


def set_data_root(path: str | Path | None) -> Path:
    """Point the season stores, OpenF1 records, telemetry and payload output at `path`
    (None restores docs/paddock/data). Clears the in-memory caches."""
    global _ROOT_SET
    p = Path(path) if path else _DEFAULT_DATA
    _store.DATA = p
    _openf1.SITE_DATA = p
    _ROOT_SET = True
    _clear_caches()
    return p


def set_cache_root(path: str | Path | None) -> None:
    """Redirect the model caches (pace fits, circuit records, Elo, backtest, forecasts)."""
    if not path:
        return
    base = Path(path)
    from oddsmarkets.f1.models import backtest as _bt
    from oddsmarkets.f1.models import circuits as _circ
    from oddsmarkets.f1.models import elo as _elo
    from oddsmarkets.f1.models import laptime as _lt
    _circ.CACHE = base
    _circ.RECORDS_PATH = base / "circuit_records.json"
    _lt.CACHE = base / "pace"
    _elo.CACHE = base / "elo.json"
    _bt.OUT = base / "backtest.json"
    from oddsmarkets.f1.analytics import forecasts as _fc
    _fc.CACHE = base / "forecasts"
    _clear_caches()


def data_root() -> Path:
    """The active data directory (PADDOCK_DATA on first use, else docs/paddock/data)."""
    if not _ROOT_SET and os.environ.get("PADDOCK_DATA"):
        set_data_root(os.environ["PADDOCK_DATA"])
        if os.environ.get("PADDOCK_CACHE"):
            set_cache_root(os.environ["PADDOCK_CACHE"])
    return _store.DATA


def seasons_on_disk() -> list[int]:
    """Years with a season store under the data root, newest first."""
    root = data_root()
    try:
        return sorted((int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit() and (p / "store.json").exists()),
                      reverse=True)
    except OSError:
        return []


# ---------------------------------------------------------------------------------------------- numbers

def fnum(v: Any) -> float | None:
    """float(v) when finite, else None."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def inum(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


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


def share(num: float, den: float) -> float | None:
    return None if not den else num / den


def percentiles(values: dict[str, Any], lower: bool = False) -> dict[str, int]:
    """Field percentile of each value, 100 = best, direction-aware.

        pct_i = 100 * (W_i + 0.5 * T_i) / (n - 1)

    where W_i counts the other entries strictly worse than i (smaller when higher is
    better; larger when `lower` is True), T_i the other entries tied with i, and n the
    number of entries with a value. A lone entry gets 50. None values are skipped.
    """
    vals = {k: fnum(v) for k, v in values.items()}
    vals = {k: v for k, v in vals.items() if v is not None}
    n = len(vals)
    if n == 0:
        return {}
    if n == 1:
        return {k: 50 for k in vals}
    out = {}
    items = list(vals.values())
    for k, v in vals.items():
        worse = sum(1 for x in items if (x > v if lower else x < v))
        tie = sum(1 for x in items if x == v) - 1
        out[k] = int(round(100.0 * (worse + 0.5 * tie) / (n - 1)))
    return out


# ---------------------------------------------------------------------------------------------- results rows

def status_kind(row: dict) -> str:
    """'finished' | 'dnf_mech' | 'dnf_incident' | 'dnf_unknown' | 'dsq' | 'dns' (models.circuits.status_kind)."""
    from oddsmarkets.f1.models.circuits import status_kind as _sk
    try:
        return _sk(row)
    except Exception:                                            # pragma: no cover - defensive
        return "dnf_unknown"


def started(row: dict) -> bool:
    return status_kind(row) != "dns"


def classified(row: dict) -> bool:
    return status_kind(row) == "finished"


def driver_name(store: dict, d: str) -> str:
    info = (store.get("drivers") or {}).get(d) or {}
    n = f"{info.get('given') or ''} {info.get('family') or ''}".strip()
    return n or d


def team_name(store: dict, t: str | None) -> str | None:
    if not t:
        return None
    return ((store.get("constructors") or {}).get(t) or {}).get("name") or t
