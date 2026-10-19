"""
Shared plumbing for the Bullpen pitch models (builder B: physics, stuff, location, pitching, tunneling,
swing, battrack, fatigue).

* Roots: `BULLPEN_DATA` (default docs/bullpen/data), `BULLPEN_RAW` (default data/baseball) and
  `BULLPEN_CACHE` (default data/baseball/cache); committed fits in models/fitted/ (`FITTED`).
* `load_pitches(level, season, columns)`: one season's Statcast pitch table (builder A's Parquet,
  `<raw>/statcast/<level>/<season>.parquet`) reading only the requested columns; columns absent from the
  file come back as nulls. Never more than one season is read by a call.
* Pitch outcome classes from Savant's `description` (`outcomes`), pitch families (`FAMILY`), the count,
  batter-relative location and arm-side normalisation helpers shared by every model.
* JSON cache (`cached`), JSON/gzip writers, `clean` for payloads, and LightGBM helpers that keep a fitted
  booster JSON-safe (its text dump) with an in-process cache of loaded boosters.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
FITTED = Path(__file__).resolve().with_name("fitted")

LEVELS = ("mlb", "aaa")

# physical constants (feet, seconds)
G_FT = 32.174                  # gravity, ft/s^2
Y0 = 50.0                      # the 9-parameter fit is defined at y = 50 ft from the point of home plate
Y_FRONT = 17.0 / 12.0          # front of home plate (where plate_x / plate_z are measured)
Y_PFX = 40.0                   # pfx movement is measured over y = 40 ft -> front of plate
DECISION_S = 0.167             # the batter's decision point: 167 ms before the ball reaches the plate
FTS_TO_MPH = 3600.0 / 5280.0

# pitch families
FAMILY = {"FF": "fastball", "FA": "fastball", "SI": "fastball", "FT": "fastball", "FC": "fastball",
          "SL": "breaking", "ST": "breaking", "CU": "breaking", "KC": "breaking", "SV": "breaking", "CS": "breaking",
          "CH": "offspeed", "FS": "offspeed", "FO": "offspeed", "SC": "offspeed", "KN": "offspeed"}
FAMILIES = ["fastball", "breaking", "offspeed"]
FAMILY_CODE = {f: i for i, f in enumerate(FAMILIES)}
PITCH_TYPES = ["FF", "SI", "FC", "SL", "ST", "CU", "KC", "SV", "CH", "FS", "FO", "SC", "KN"]
PT_CODE = {p: i for i, p in enumerate(PITCH_TYPES)}
PRIMARY_FB = ("FF", "SI", "FC")      # candidates for a pitcher's primary fastball, in tie-break order

# Savant `description` values
WHIFF = {"swinging_strike", "swinging_strike_blocked", "foul_tip", "missed_bunt"}
FOUL = {"foul", "foul_bunt", "bunt_foul_tip", "foul_pitchout"}
INPLAY = {"hit_into_play", "hit_into_play_no_out", "hit_into_play_score"}
CALLED = {"called_strike"}
BALL = {"ball", "blocked_ball", "hit_by_pitch", "automatic_ball"}
NON_COMPETITIVE = {"intent_ball", "pitchout", "automatic_strike", "automatic_ball", "swinging_pitchout"}
BUNT = {"missed_bunt", "foul_bunt", "bunt_foul_tip"}

# zone numbers: 1-9 inside the strike zone, 11-14 outside
IN_ZONE = set(range(1, 10))


# ----------------------------------------------------------------------------- roots

def data_root() -> Path:
    return Path(os.environ.get("BULLPEN_DATA") or (ROOT / "docs" / "bullpen" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("BULLPEN_RAW") or (ROOT / "data" / "baseball"))


def cache_root() -> Path:
    return Path(os.environ.get("BULLPEN_CACHE") or (raw_root() / "cache"))


def pitch_path(level: str, season: int) -> Path:
    return raw_root() / "statcast" / str(level) / f"{int(season)}.parquet"


def seasons_on_disk(level: str = "mlb") -> list[int]:
    d = raw_root() / "statcast" / str(level)
    if not d.exists():
        return []
    out = []
    for p in d.glob("*.parquet"):
        if p.stem.isdigit():
            out.append(int(p.stem))
    return sorted(out)


# ----------------------------------------------------------------------------- pitch tables

def parquet_columns(path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq
        return list(pq.read_schema(path).names)
    except Exception:  # noqa: BLE001 - unreadable / partial file
        return []


def load_pitches(level: str, season: int, columns: Iterable[str] | None = None,
                 path: Path | None = None) -> pd.DataFrame:
    """One season's pitch table with only `columns` (all when None). Columns the file does not have come
    back as all-null float columns, so callers can rely on them; categoricals are returned as strings
    (object) so models can compare them freely. Empty frame when the file is missing or unreadable."""
    p = Path(path) if path is not None else pitch_path(level, season)
    cols = list(dict.fromkeys(columns)) if columns is not None else None
    if not p.exists():
        return pd.DataFrame(columns=cols or [])
    have = parquet_columns(p)
    want = [c for c in cols if c in have] if cols is not None else None
    try:
        df = pd.read_parquet(p, columns=want)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=cols or [])
    for c in df.columns:
        if isinstance(df[c].dtype, pd.CategoricalDtype):
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    if cols is not None:
        for c in cols:
            if c not in df:
                df[c] = np.nan
        df = df[cols]
    return df


def outcomes(df: pd.DataFrame) -> pd.DataFrame:
    """Boolean outcome flags from `description` (added in place and returned):
    swing, whiff, foul, inplay, contact (= foul | inplay), take, called (called strike), ball, bunt,
    competitive (not intentional / pitchout / automatic)."""
    d = df["description"].astype(str).str.lower() if "description" in df else pd.Series("", index=df.index)
    df["whiff"] = d.isin(WHIFF)
    df["foul"] = d.isin(FOUL)
    df["inplay"] = d.isin(INPLAY) | d.str.startswith("hit_into_play")
    df["contact"] = df["foul"] | df["inplay"]
    df["swing"] = df["whiff"] | df["contact"]
    df["called"] = d.isin(CALLED)
    df["ball"] = d.isin(BALL)
    df["take"] = df["called"] | df["ball"]
    df["bunt"] = d.isin(BUNT)
    if "bb_type" in df:
        pass
    df["competitive"] = ~d.isin(NON_COMPETITIVE) & (df["swing"] | df["take"])
    return df


def family_of(pitch_type: pd.Series) -> pd.Series:
    return pitch_type.astype(object).map(FAMILY)


def arm_sign(p_throws: pd.Series) -> np.ndarray:
    """+1 for a left-hander, -1 for a right-hander: multiplying a catcher's-view x (positive toward first
    base) by it gives the arm-side direction as positive (a righty's arm side is the third-base side)."""
    return np.where(p_throws.astype(str).to_numpy() == "L", 1.0, -1.0)


def away_sign(stand: pd.Series) -> np.ndarray:
    """+1 for a right-handed batter, -1 for a left-hander: x * sign is positive away from the batter."""
    return np.where(stand.astype(str).to_numpy() == "L", -1.0, 1.0)


def count_code(balls: pd.Series, strikes: pd.Series) -> np.ndarray:
    b = pd.to_numeric(balls, errors="coerce").fillna(0).clip(0, 3).to_numpy(int)
    s = pd.to_numeric(strikes, errors="coerce").fillna(0).clip(0, 2).to_numpy(int)
    return b * 3 + s


COUNTS = [f"{b}-{s}" for b in range(4) for s in range(3)]


def pa_key(df: pd.DataFrame) -> pd.Series:
    return df["game_pk"].astype("int64") * 1000 + pd.to_numeric(df["at_bat_number"], errors="coerce").fillna(0).astype("int64")


def sort_pitches(df: pd.DataFrame) -> pd.DataFrame:
    keys = [c for c in ("game_date", "game_pk", "at_bat_number", "pitch_number") if c in df]
    return df.sort_values(keys, kind="mergesort").reset_index(drop=True) if keys else df


# ----------------------------------------------------------------------------- JSON / cache

def resolve(path: Path) -> Path:
    p = Path(path)
    gz = p.with_name(p.name + ".gz")
    if gz.exists() and (not p.exists() or gz.stat().st_mtime_ns >= p.stat().st_mtime_ns):
        return gz
    return p


def read_json(path: Path) -> Any:
    p = resolve(path)
    try:
        if p.name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
        return None


def _json_default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def write_json(path: Path, obj: Any, gz: bool = False, nd: int | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(clean(obj, nd) if nd else obj, separators=(",", ":"), default=_json_default)
    if gz or p.name.endswith(".gz"):
        p = p if p.name.endswith(".gz") else p.with_name(p.name + ".gz")
        with gzip.open(p, "wt", encoding="utf-8", compresslevel=9) as fh:
            fh.write(txt)
    else:
        p.write_text(txt, encoding="utf-8")
    return p


# Cache keys are path-independent: a file enters a key as its path relative to the root it lives under, its size and
# a digest of its content, never its absolute path or modification time. A cache fitted on one machine (the PC) is
# then reused on another (a CI runner, whose checkout has other paths and fresh mtimes for committed files). Digests
# are memoised per (relative path, size, mtime_ns) in <cache>/_digests.json, so a file is read once per change.
_DIGESTS: dict[str, dict] = {}          # memo file -> {tag: [size, mtime_ns, sha1]} (one per cache root)
_DIGESTS_DIRTY: dict[str, int] = {}


def rel_tag(path: Path) -> str:
    """`<root>:<path relative to it>` for a file under the cache, fitted, raw, data or repository root; else its name."""
    p = Path(path)
    try:
        ap = p.resolve()
    except OSError:
        ap = p.absolute()
    for tag, root in (("cache", cache_root()), ("fitted", FITTED), ("raw", raw_root()), ("data", data_root()), ("root", ROOT)):
        try:
            return f"{tag}:{ap.relative_to(Path(root).resolve()).as_posix()}"
        except (ValueError, OSError):
            continue
    return p.name


def _memo_path() -> Path:
    return cache_root() / "_digests.json"


def _memo() -> dict:
    mp = str(_memo_path())
    m = _DIGESTS.get(mp)
    if m is None:
        try:
            m = json.loads(Path(mp).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            m = None
        m = _DIGESTS[mp] = m if isinstance(m, dict) else {}
    return m


def flush_digests() -> None:
    """Write the digest memos (merged with what another process may have written meanwhile)."""
    for mp, n in list(_DIGESTS_DIRTY.items()):
        if not n or mp not in _DIGESTS:
            continue
        p = Path(mp)
        try:
            cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            if not isinstance(cur, dict):
                cur = {}
        except (OSError, ValueError):
            cur = {}
        cur.update(_DIGESTS[mp])
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(cur, separators=(",", ":"), sort_keys=True), encoding="utf-8")
            os.replace(tmp, p)
            _DIGESTS_DIRTY[mp] = 0
        except OSError:
            pass


def content_digest(path: Path) -> str | None:
    """sha1 of the file's bytes (memoised on relative path, size and mtime_ns); None when it is missing."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None
    if not p.is_file():
        return None
    tag = rel_tag(p)
    memo = _memo()
    hit = memo.get(tag)
    if isinstance(hit, list) and len(hit) == 3 and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
        return hit[2]
    h = hashlib.sha1()
    try:
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
    except OSError:
        return None
    d = h.hexdigest()
    memo[tag] = [st.st_size, st.st_mtime_ns, d]
    mp = str(_memo_path())
    _DIGESTS_DIRTY[mp] = _DIGESTS_DIRTY.get(mp, 0) + 1
    if _DIGESTS_DIRTY[mp] >= 25 or st.st_size > 20_000_000:
        flush_digests()
    return d


def path_sig(path: Path) -> str:
    """A file's part of a cache key: relative path, size and content digest (or 'missing')."""
    p = Path(path)
    d = content_digest(p)
    if d is None:
        return f"{rel_tag(p)}|missing"
    return f"{rel_tag(p)}|{p.stat().st_size}|{d}"


def stamp(path: Path) -> str:
    """A short content stamp of a file for cache file names ('0' when missing)."""
    d = content_digest(Path(path))
    return d[:12] if d else "0"


import atexit as _atexit  # noqa: E402

_atexit.register(flush_digests)


def file_key(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, Path):
            h.update(path_sig(p).encode())
        else:
            h.update(json.dumps(p, sort_keys=True, default=str).encode())
        h.update(b"|")
    return h.hexdigest()


def cached(kind: str, name: str, key: str, build: Callable[[], Any], use_cache: bool = True, gz: bool = False) -> Any:
    """JSON cache under cache_root()/kind/name.json[.gz], invalidated by `key`. Never raises on IO."""
    path = cache_root() / kind / (f"{name}.json.gz" if gz else f"{name}.json")
    if use_cache and path.exists():
        c = read_json(path)
        if isinstance(c, dict) and c.get("key") == key:
            return c.get("result")
    out = build()
    try:
        write_json(path, {"key": key, "result": out}, gz=gz)
    except (OSError, TypeError, ValueError):
        pass
    return out


def clean(x: Any, nd: int = 4) -> Any:
    """Round floats, map non-finite to None, recurse into dicts/lists (for payloads)."""
    if isinstance(x, dict):
        return {str(k): clean(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v, nd) for v in x]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return round(v, nd) if math.isfinite(v) else None
    return x


def load_fitted(name: str, version: str) -> dict | None:
    """models/fitted/<name>.json(.gz) when its version matches."""
    m = read_json(FITTED / f"{name}.json")
    if isinstance(m, dict) and m.get("version") == version and m.get("ok", True):
        return m
    return None


# ----------------------------------------------------------------------------- LightGBM

_BOOSTERS: dict[str, Any] = {}


def lgb_train(X: pd.DataFrame | np.ndarray, y: np.ndarray, objective: str, params: dict | None = None,
              X_val=None, y_val=None, rounds: int = 400, early: int = 30, weight: np.ndarray | None = None,
              categorical: list[str] | None = None) -> tuple[Any, dict]:
    """Train a LightGBM booster. Returns (booster, info {"best_iter", "val_metric"}). Deterministic."""
    import lightgbm as lgb
    p = {"objective": objective, "learning_rate": 0.08, "num_leaves": 31, "min_data_in_leaf": 200,
         "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1,
         "seed": 7, "deterministic": True, "force_col_wise": True,
         "num_threads": int(os.environ.get("BULLPEN_THREADS") or min(8, max(1, (os.cpu_count() or 4) - 2)))}
    if len(X) < 100_000 and not os.environ.get("BULLPEN_THREADS"):
        p["num_threads"] = 2          # small fits: thread start-up and oversubscription cost more than they save
    if params:
        p.update(params)
    cat = categorical or "auto"
    ds = lgb.Dataset(X, label=np.asarray(y, float), weight=weight, categorical_feature=cat, free_raw_data=True)
    valid, cbs = [], []
    if X_val is not None and len(X_val):
        valid = [lgb.Dataset(X_val, label=np.asarray(y_val, float), reference=ds, categorical_feature=cat)]
        cbs = [lgb.early_stopping(early, verbose=False)]
    bst = lgb.train(p, ds, num_boost_round=rounds, valid_sets=valid or None, callbacks=cbs or None)
    info = {"best_iter": int(bst.best_iteration or bst.current_iteration())}
    if valid:
        bs = bst.best_score.get("valid_0") or {}
        info["val_metric"] = {k: float(v) for k, v in bs.items()}
    return bst, info


def booster_dump(bst) -> str:
    return bst.model_to_string(num_iteration=bst.best_iteration or -1)


def booster(model_str: str):
    """A Booster from its text dump, cached in-process by hash."""
    import lightgbm as lgb
    h = hashlib.sha1(model_str.encode()).hexdigest()
    b = _BOOSTERS.get(h)
    if b is None:
        b = lgb.Booster(model_str=model_str)
        if len(_BOOSTERS) > 64:
            _BOOSTERS.clear()
        _BOOSTERS[h] = b
    return b


def lgb_predict(model_str: str, X: pd.DataFrame, chunk: int = 400_000) -> np.ndarray:
    b = booster(model_str)
    if len(X) == 0:
        return np.zeros(0)
    nt = int(os.environ.get("BULLPEN_THREADS") or (2 if len(X) < 100_000 else min(8, max(1, (os.cpu_count() or 4) - 2))))
    out = [b.predict(X.iloc[i:i + chunk], num_threads=nt) for i in range(0, len(X), chunk)]
    return np.concatenate(out).astype(float)


def importances(model_str: str, features: list[str]) -> dict:
    """Gain importance shares (sum to 1) by feature."""
    b = booster(model_str)
    g = b.feature_importance(importance_type="gain").astype(float)
    tot = g.sum() or 1.0
    names = b.feature_name() or features
    return {n: round(float(v / tot), 4) for n, v in sorted(zip(names, g), key=lambda t: -t[1])}


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if len(y) else float("nan")


def scale_100(x: np.ndarray, mu: float, sd: float, higher_is_better: bool = False) -> np.ndarray:
    """100 + 10 (x - mu) / sd, flipped when lower x is better (run values from the batter's side)."""
    z = (np.asarray(x, float) - mu) / (sd if sd and sd > 0 else 1.0)
    return 100.0 + 10.0 * (z if higher_is_better else -z)


def shrink(total: float, n: float, k: float, prior: float = 0.0) -> float:
    """(total + k * prior) / (n + k): a mean shrunk toward `prior` by k pseudo-observations."""
    return float((total + k * prior) / (n + k)) if (n + k) > 0 else float(prior)


def logit_fit(X: np.ndarray, y: np.ndarray, ridge: float = 1e-4, iters: int = 30) -> dict:
    """Small dense logistic regression by Newton-Raphson (intercept is the caller's column).
    Returns {"beta", "se"}."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    b = np.zeros(X.shape[1])
    H = np.eye(X.shape[1])
    for _ in range(iters):
        eta = np.clip(X @ b, -30, 30)
        mu = 1 / (1 + np.exp(-eta))
        g = X.T @ (y - mu) - ridge * b
        H = X.T @ (X * (mu * (1 - mu))[:, None]) + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-8:
            break
    cov = np.linalg.inv(H)
    return {"beta": b, "se": np.sqrt(np.diag(cov))}
