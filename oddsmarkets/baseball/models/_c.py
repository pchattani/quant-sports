"""
Shared plumbing for builder C's baseball models (xwoba, catchprob, framing, umpire, re24, parks,
war, history, stabilise).

* Roots from the contract: data `BULLPEN_DATA` (docs/bullpen/data), raw `BULLPEN_RAW` (data/baseball),
  cache `BULLPEN_CACHE` (data/baseball/cache); committed fits in `models/fitted/`. When builder B's
  `models/_io.py` exists its root functions are used, so both builders agree on paths.
* Loaders: one season of pitches at a time (`load_pitches`, column-selected, game-type filtered,
  sorted in game order), the per-season store, Retrosheet PA tables and Savant leaderboard CSVs.
* `pa_table`: one row per plate appearance from the pitch table (state at the first pitch, result
  at the last), the unit every value model here works on.
* Batted-ball geometry: spray angle from (hc_x, hc_y), handedness-adjusted pull angle, landing
  distance, and launch physics (drag + Magnus lift) for hang time.
* A penalised logistic regression (Newton/IRLS on a sparse design), hat bases and their tensor
  product, and the JSON cache helpers (same shape as Hardwood's `_io`).
Never raises on missing files: loaders return None or an empty frame.
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import scipy.linalg
import scipy.sparse as sp

try:  # builder B owns models/_io.py; use its roots when present
    from oddsmarkets.baseball.models import _io as _B  # type: ignore
except Exception:  # pragma: no cover - depends on build order
    _B = None

ROOT = Path(__file__).resolve().parents[3]
FITTED = Path(__file__).with_name("fitted")
LEVELS = ("mlb", "aaa")


# ============================================================================ roots

def _b(name: str):
    f = getattr(_B, name, None) if _B is not None else None
    return f if callable(f) else None


def data_root() -> Path:
    f = _b("data_root")
    return Path(f()) if f else Path(os.environ.get("BULLPEN_DATA") or (ROOT / "docs" / "bullpen" / "data"))


def raw_root() -> Path:
    f = _b("raw_root")
    return Path(f()) if f else Path(os.environ.get("BULLPEN_RAW") or (ROOT / "data" / "baseball"))


def cache_root() -> Path:
    f = _b("cache_root")
    return Path(f()) if f else Path(os.environ.get("BULLPEN_CACHE") or (ROOT / "data" / "baseball" / "cache"))


def pitch_path(level: str, season: int) -> Path:
    return raw_root() / "statcast" / str(level) / f"{int(season)}.parquet"


def pa_path(season: int) -> Path:
    return raw_root() / "retro" / "pa" / f"{int(season)}.parquet"


def store_path(level: str, season: int) -> Path:
    return data_root() / str(level) / str(int(season)) / "store.json"


def pitch_seasons(level: str = "mlb") -> list[int]:
    d = raw_root() / "statcast" / str(level)
    out = []
    for p in d.glob("*.parquet"):
        try:
            out.append(int(p.stem))
        except ValueError:
            pass
    return sorted(out)


def retro_seasons() -> list[int]:
    out = []
    for p in (raw_root() / "retro" / "pa").glob("*.parquet"):
        try:
            out.append(int(p.stem))
        except ValueError:
            pass
    return sorted(out)


# ============================================================================ loaders

PITCH_ORDER = ["game_pk", "at_bat_number", "pitch_number"]


def parquet_columns(path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq
        return list(pq.read_schema(path).names)
    except Exception:
        return []


def load_pitches(level: str, season: int, columns: Iterable[str] | None = None,
                 game_types: Iterable[str] | None = ("R",), path: Path | None = None) -> pd.DataFrame | None:
    """One season of pitches (only `columns` that exist; missing requested columns added as NaN),
    restricted to `game_types` (None = all), sorted in game order. None when the file is missing."""
    p = Path(path) if path is not None else pitch_path(level, season)
    if not p.exists():
        return None
    have = parquet_columns(p)
    cols = None
    if columns is not None:
        want = list(dict.fromkeys(list(columns) + PITCH_ORDER + ["game_type"]))
        cols = [c for c in want if c in have]
    try:
        df = pd.read_parquet(p, columns=cols)
    except Exception:
        return None
    return prepare_pitches(df, columns=columns, game_types=game_types)


def prepare_pitches(df: pd.DataFrame, columns: Iterable[str] | None = None,
                    game_types: Iterable[str] | None = ("R",)) -> pd.DataFrame:
    """Filter game types, add missing requested columns as NaN, decategorise the few string
    columns we compare against, and sort in game order (game_pk, at_bat_number, pitch_number)."""
    if game_types is not None and "game_type" in df:
        df = df[df["game_type"].astype(str).isin(set(game_types))]
    if columns is not None:
        for c in columns:
            if c not in df:
                df[c] = np.nan
    for c in ("events", "description", "bb_type", "stand", "p_throws", "inning_topbot", "home_team", "away_team",
              "pitch_type", "type", "if_fielding_alignment", "of_fielding_alignment", "game_type"):
        if c in df and isinstance(df[c].dtype, pd.CategoricalDtype):
            df[c] = df[c].astype(object)
    if all(c in df for c in PITCH_ORDER):
        df = df.sort_values(PITCH_ORDER, kind="mergesort")
    return df.reset_index(drop=True)


def read_json(path: Path) -> Any:
    p = Path(path)
    gz = p.with_name(p.name + ".gz")
    try:
        if not p.exists() and gz.exists():
            import gzip
            with gzip.open(gz, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
        return None


def load_store(level: str, season: int) -> dict | None:
    f = _b("load_store")
    if f:
        try:
            s = f(level, season)
            if isinstance(s, dict):
                return s
        except Exception:
            pass
    s = read_json(store_path(level, season))
    return s if isinstance(s, dict) else None


def load_pa(season: int) -> pd.DataFrame | None:
    """Retrosheet PA table for one season (contract columns), None when missing."""
    p = pa_path(season)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:
        return None
    for c in df.columns:
        if isinstance(df[c].dtype, pd.CategoricalDtype):
            df[c] = df[c].astype(object)
    return df


def load_people() -> dict:
    d = read_json(data_root() / "people.json")
    return d if isinstance(d, dict) else {}


def leaderboard(kind: str, season: int) -> pd.DataFrame | None:
    """A Savant leaderboard CSV builder A cached (sprint_speed, oaa / outs_above_average,
    catcher_framing, expected_statistics), searched under the raw root; None when absent."""
    f = _b("leaderboard") or _b("load_leaderboard")
    if f:
        try:
            df = f(kind, season)
            if isinstance(df, pd.DataFrame) and len(df):
                return df
        except Exception:
            pass
    names = {"oaa": "outs_above_average", "framing": "catcher-framing", "sprint_speed": "sprint_speed",
             "arm": "arm-strength"}.get(kind, kind)
    try:  # builder A's cache-only reader: <cache>/savant/leaderboards/<name>_<kind>_<season>.csv
        from oddsmarkets.baseball.sources import savant as _sv
        df = _sv.leaderboard(None, names, int(season))
        if isinstance(df, pd.DataFrame) and len(df):
            return df
    except Exception:
        pass
    for h in sorted(glob.glob(str(cache_root() / "savant" / "leaderboards" / f"{names}_*_{int(season)}.csv"))):
        try:
            return pd.read_csv(h, low_memory=False)
        except Exception:
            continue
    aliases = {"oaa": ["oaa", "outs_above_average", "outs-above-average"],
               "framing": ["catcher_framing", "framing", "catcher-framing"],
               "sprint_speed": ["sprint_speed", "sprint-speed"],
               "expected": ["expected_statistics", "expected-statistics", "expected"]}.get(kind, [kind])
    root = raw_root()
    for a in aliases:
        pats = [f"**/{a}_{season}.csv", f"**/{a}-{season}.csv", f"**/{season}/{a}.csv", f"**/{a}/{season}.csv",
                f"**/{a}_{season}.parquet", f"**/{season}/{a}.parquet", f"**/{a}/{season}.parquet"]
        for pat in pats:
            hits = glob.glob(str(root / pat), recursive=True)
            for h in hits:
                try:
                    return pd.read_parquet(h) if h.endswith(".parquet") else pd.read_csv(h)
                except Exception:
                    continue
    return None


# ============================================================================ event vocab

HIT_EVENTS = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
BB_EVENTS = {"walk"}
IBB_EVENTS = {"intent_walk"}
HBP_EVENTS = {"hit_by_pitch"}
K_EVENTS = {"strikeout", "strikeout_double_play"}
OUT_BIP_EVENTS = {"field_out", "force_out", "grounded_into_double_play", "double_play", "triple_play",
                  "fielders_choice_out", "fielders_choice", "sac_fly", "sac_fly_double_play", "sac_bunt",
                  "sac_bunt_double_play"}
ERROR_EVENTS = {"field_error"}
BIP_EVENTS = set(HIT_EVENTS) | OUT_BIP_EVENTS | ERROR_EVENTS
PA_EVENTS = BIP_EVENTS | BB_EVENTS | IBB_EVENTS | HBP_EVENTS | K_EVENTS | {"catcher_interf"}
OUT_MADE = {"field_out": 1, "force_out": 1, "grounded_into_double_play": 2, "double_play": 2, "triple_play": 3,
            "fielders_choice_out": 1, "sac_fly": 1, "sac_fly_double_play": 2, "sac_bunt": 1,
            "sac_bunt_double_play": 2, "strikeout": 1, "strikeout_double_play": 2}
CALLED = {"called_strike", "ball", "blocked_ball"}
SWINGS = {"swinging_strike", "swinging_strike_blocked", "foul", "foul_tip", "hit_into_play", "foul_bunt",
          "missed_bunt", "bunt_foul_tip", "hit_into_play_no_out", "hit_into_play_score"}


def event_class(events: pd.Series) -> np.ndarray:
    """PA outcome class: 'BB','IBB','HBP','1B','2B','3B','HR','K','ROE','OUT','CI', else '' (not a PA end)."""
    e = events.astype(object).fillna("").astype(str).to_numpy()
    m = {"walk": "BB", "intent_walk": "IBB", "hit_by_pitch": "HBP", "single": "1B", "double": "2B", "triple": "3B",
         "home_run": "HR", "strikeout": "K", "strikeout_double_play": "K", "field_error": "ROE", "catcher_interf": "CI"}
    for k in OUT_BIP_EVENTS:
        m[k] = "OUT"
    return np.array([m.get(x, "") for x in e], dtype=object)


# ============================================================================ PA table

def _bases(df: pd.DataFrame) -> np.ndarray:
    b = np.zeros(len(df), int)
    for bit, c in ((1, "on_1b"), (2, "on_2b"), (4, "on_3b")):
        if c in df:
            b |= df[c].notna().to_numpy() * bit
    return b


def pa_table(p: pd.DataFrame) -> pd.DataFrame:
    """One row per plate appearance (game_pk, at_bat_number) from a game-ordered pitch table:
    state at the first pitch (outs, bases bitmask, bat_score, runners), result at the last
    (events, class, post_bat_score, woba_value/denom, batted-ball columns, fielders), the half-inning
    key and the number of pitches. Rows whose last pitch carries no PA-ending event keep cls ''."""
    if p is None or not len(p):
        return pd.DataFrame()
    p = p.copy()
    p["_bases"] = _bases(p)
    g = p.groupby(["game_pk", "at_bat_number"], sort=False)
    first = g.head(1).set_index(["game_pk", "at_bat_number"])
    last = g.tail(1).set_index(["game_pk", "at_bat_number"])
    out = pd.DataFrame(index=first.index)
    for c in ("game_date", "game_type", "home_team", "away_team", "inning", "inning_topbot", "batter", "pitcher",
              "stand", "p_throws", "outs_when_up", "bat_score", "fld_score", "on_1b", "on_2b", "on_3b"):
        if c in first:
            out[c] = first[c]
    out["bases"] = first["_bases"]
    for c in ["events", "description", "bb_type", "launch_speed", "launch_angle", "hit_distance_sc", "hc_x", "hc_y",
              "woba_value", "woba_denom", "estimated_woba_using_speedangle", "estimated_ba_using_speedangle",
              "post_bat_score", "balls", "strikes", "if_fielding_alignment", "of_fielding_alignment",
              "delta_run_exp", "home_win_exp", "delta_home_win_exp", "hit_location", "umpire", "pitch_type",
              "release_speed", "plate_x", "plate_z"] + [f"fielder_{i}" for i in range(2, 10)]:
        if c in last:
            out[c if c not in ("balls", "strikes") else f"last_{c}"] = last[c]
    out["n_pitches"] = g.size()
    out = out.reset_index()
    out["cls"] = event_class(out["events"]) if "events" in out else ""
    out["half"] = np.where(out["inning_topbot"].astype(str).str.lower().str.startswith("t"), 0, 1)
    out["hkey"] = out["game_pk"].astype(np.int64) * 100 + out["inning"].astype(int) * 2 + out["half"]
    return out


# ============================================================================ batted-ball geometry

HC_X0, HC_Y0 = 125.42, 198.27
HC_FT = 2.495     # feet per hit-coordinate unit (Savant's 250x250 field image, home plate to 2B ≈ 127.3 ft)


def spray_angle(hc_x, hc_y) -> np.ndarray:
    """Spray angle in degrees: 0 = straight away centre, negative = left field (3B side), positive = right."""
    x = np.asarray(hc_x, float) - HC_X0
    y = HC_Y0 - np.asarray(hc_y, float)
    return np.degrees(np.arctan2(x, y))


def pull_angle(spray, stand) -> np.ndarray:
    """Handedness-adjusted spray: positive = pull side (left field for a right-handed batter), negative = opposite."""
    s = np.asarray(spray, float)
    lefty = np.asarray(pd.Series(stand).astype(str).str.upper().str.startswith("L"))
    return np.where(lefty, s, -s)


def hc_distance(hc_x, hc_y) -> np.ndarray:
    return HC_FT * np.hypot(np.asarray(hc_x, float) - HC_X0, HC_Y0 - np.asarray(hc_y, float))


def landing_xy(dist_ft, spray_deg) -> tuple[np.ndarray, np.ndarray]:
    """Field coordinates in feet: x toward right field (1B side), y toward centre field."""
    a = np.radians(np.asarray(spray_deg, float))
    d = np.asarray(dist_ft, float)
    return d * np.sin(a), d * np.cos(a)


# launch physics (drag + Magnus lift, still air at sea level): constants documented for the methodology
BALL_MASS = 0.145          # kg
BALL_RADIUS = 0.0366       # m
AIR_RHO = 1.20             # kg/m^3 (sea level, ~20 C)
CD = 0.33                  # drag coefficient
CL_MAX = 0.20              # lift coefficient of a well-backspun fly ball
CONTACT_HEIGHT_M = 0.9


def flight(launch_speed_mph, launch_angle_deg, dt: float = 0.01, t_max: float = 9.0) -> dict:
    """Vectorised 2-D trajectory under gravity, quadratic drag and Magnus lift. Backspin lift
    scales with launch angle (CL = CL_MAX * clip(sin 2LA, 0, 1)), a smooth stand-in for the spin a
    batter imparts. Returns {"hang": seconds to landing at ground level, "dist": carry in feet,
    "apex": feet}. Grounders (LA <= 0) get the time to the first bounce."""
    v = np.nan_to_num(np.asarray(launch_speed_mph, float), nan=85.0) * 0.44704
    la = np.radians(np.nan_to_num(np.asarray(launch_angle_deg, float), nan=10.0))
    n = v.shape[0]
    k = 0.5 * AIR_RHO * math.pi * BALL_RADIUS ** 2 / BALL_MASS
    cl = CL_MAX * np.clip(np.sin(2 * la), 0.0, 1.0)
    x = np.zeros(n); z = np.full(n, CONTACT_HEIGHT_M)
    vx = v * np.cos(la); vz = v * np.sin(la)
    hang = np.full(n, np.nan); dist = np.full(n, np.nan); apex = z.copy()
    alive = np.ones(n, bool)
    t = 0.0
    while t < t_max and alive.any():
        sp_ = np.hypot(vx, vz)
        ax = -k * sp_ * (CD * vx + cl * vz)
        az = -9.81 - k * sp_ * (CD * vz - cl * vx)
        nvx, nvz = vx + ax * dt, vz + az * dt
        nx, nz = x + 0.5 * (vx + nvx) * dt, z + 0.5 * (vz + nvz) * dt
        landed = alive & (nz <= 0) & (z > 0)
        if landed.any():
            f = z[landed] / np.maximum(z[landed] - nz[landed], 1e-9)
            hang[landed] = t + f * dt
            dist[landed] = x[landed] + f * (nx[landed] - x[landed])
            alive &= ~landed
        x, z, vx, vz = np.where(alive, nx, x), np.where(alive, nz, z), np.where(alive, nvx, vx), np.where(alive, nvz, vz)
        apex = np.maximum(apex, z)
        t += dt
    hang = np.where(np.isnan(hang), t_max, hang)
    dist = np.where(np.isnan(dist), x, dist)
    return {"hang": hang, "dist": dist * 3.28084, "apex": apex * 3.28084}


# ============================================================================ regression helpers

def hat_basis(x: np.ndarray, knots: Iterable[float]) -> sp.csr_matrix:
    k = np.asarray(list(knots), float)
    x = np.clip(np.nan_to_num(np.asarray(x, float), nan=float(np.median(k))), k[0], k[-1])
    j = np.clip(np.searchsorted(k, x, side="right") - 1, 0, len(k) - 2)
    w = (x - k[j]) / (k[j + 1] - k[j])
    n = len(x)
    rows = np.concatenate([np.arange(n), np.arange(n)])
    cols = np.concatenate([j, j + 1])
    vals = np.concatenate([1 - w, w])
    return sp.csr_matrix((vals, (rows, cols)), shape=(n, len(k)))


def tensor_hat(x, kx, z, kz) -> sp.csr_matrix:
    """Tensor-product hat basis (bilinear interpolation weights) on the grid kx × kz, column j*len(kz)+l."""
    A = hat_basis(x, kx).tocoo(); B = hat_basis(z, kz).tocoo()
    n = A.shape[0]
    a = A.tocsr(); b = B.tocsr()
    ai = a.indices.reshape(n, 2); av = a.data.reshape(n, 2)
    bi = b.indices.reshape(n, 2); bv = b.data.reshape(n, 2)
    cols = (ai[:, :, None] * len(kz) + bi[:, None, :]).reshape(n, 4)
    vals = (av[:, :, None] * bv[:, None, :]).reshape(n, 4)
    rows = np.repeat(np.arange(n), 4)
    return sp.csr_matrix((vals.ravel(), (rows, cols.ravel())), shape=(n, len(kx) * len(kz)))


def diff_penalty(m: int, order: int = 2) -> np.ndarray:
    D = np.diff(np.eye(m), n=order, axis=0)
    return D.T @ D


def tensor_penalty(mx: int, mz: int, order: int = 2) -> np.ndarray:
    Px, Pz = diff_penalty(mx, order), diff_penalty(mz, order)
    return np.kron(Px, np.eye(mz)) + np.kron(np.eye(mx), Pz)


def codes(values, levels: list) -> np.ndarray:
    m = {v: i for i, v in enumerate(levels)}
    return np.array([m.get(v, -1) for v in values], int)


def onehot(c: np.ndarray, k: int) -> sp.csr_matrix:
    n = len(c)
    ok = c >= 0
    return sp.csr_matrix((np.ones(int(ok.sum())), (np.arange(n)[ok], c[ok])), shape=(n, k))


def sigmoid(x) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(x, float)))


def logistic_fit(X, y: np.ndarray, P, w: np.ndarray | None = None, beta0: np.ndarray | None = None,
                 max_iter: int = 40, tol: float = 1e-9, want_cov: bool = False) -> dict:
    """Penalised logistic regression by Newton/IRLS with step halving:
        maximise  sum_i w_i [y_i eta_i - log(1 + e^eta_i)] - 1/2 b' P b
    X dense or scipy.sparse; P a dense (p, p) penalty (ridge on random-effect columns = 1/sigma^2)."""
    n, p = X.shape
    w = np.ones(n) if w is None else np.asarray(w, float)
    y = np.asarray(y, float)
    P = np.asarray(P, float)
    b = np.zeros(p) if beta0 is None else np.asarray(beta0, float).copy()
    issp = sp.issparse(X)
    if issp:
        X = X.tocsr()

    def obj(beta):
        eta = X @ beta
        return float(np.sum(w * (y * eta - np.logaddexp(0.0, eta)))) - 0.5 * float(beta @ P @ beta), eta

    def hess(eta):
        mu = sigmoid(eta)
        v = w * mu * (1 - mu)
        if issp:
            H = (X.T @ X.multiply(v[:, None]).tocsr()).toarray()
        else:
            H = X.T @ (X * v[:, None])
        return 0.5 * (H + H.T) + P, mu

    f, eta = obj(b)
    it = 0
    for it in range(1, max_iter + 1):
        H, mu = hess(eta)
        g = np.asarray(X.T @ (w * (y - mu))).ravel() - P @ b
        try:
            step = scipy.linalg.solve(H + 1e-9 * np.eye(p), g, assume_a="pos")
        except (np.linalg.LinAlgError, ValueError):
            step = np.linalg.lstsq(H, g, rcond=None)[0]
        s = 1.0
        while True:
            nb = b + s * step
            nf, neta = obj(nb)
            if nf >= f - 1e-12 or s < 1e-6:
                break
            s *= 0.5
        done = abs(nf - f) < tol * (1 + abs(f))
        b, f, eta = nb, nf, neta
        if done:
            break
    out = {"beta": b, "iters": it, "loglik": f}
    if want_cov:
        H, _ = hess(eta)
        try:
            out["cov"] = np.linalg.inv(H + 1e-9 * np.eye(p))
        except np.linalg.LinAlgError:
            out["cov"] = np.linalg.pinv(H)
    return out


def shrink(num, den, prior_mean, k) -> np.ndarray:
    """Beta-binomial style shrinkage of num/den toward prior_mean with k pseudo-observations."""
    num = np.asarray(num, float); den = np.asarray(den, float)
    return (num + k * prior_mean) / (den + k)


def pearson(a, b) -> float | None:
    a = np.asarray(a, float); b = np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3 or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
        return None
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


# ============================================================================ cache / payload helpers

def file_key(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, Path):
            try:
                st = p.stat()
                h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode())
            except OSError:
                h.update(f"{p}|missing".encode())
        else:
            h.update(json.dumps(p, sort_keys=True, default=str).encode())
        h.update(b"|")
    return h.hexdigest()


def _json_default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def clean(x: Any, nd: int = 4) -> Any:
    if isinstance(x, dict):
        return {str(k): clean(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v, nd) for v in x]
    if isinstance(x, np.ndarray):
        return [clean(v, nd) for v in x.tolist()]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return round(v, nd) if math.isfinite(v) else None
    return x


def frame_rows(df: pd.DataFrame, nd: int = 4) -> dict:
    """A DataFrame as the contract's compact {"cols", "rows"} with cleaned values."""
    return {"cols": list(map(str, df.columns)), "rows": clean(df.astype(object).where(df.notna(), None).values.tolist(), nd)}


def cached(kind: str, name: str, key: str, build: Callable[[], Any], use_cache: bool = True) -> Any:
    path = cache_root() / kind / f"{name}.json"
    if use_cache and path.exists():
        c = read_json(path)
        if isinstance(c, dict) and c.get("key") == key:
            return c.get("result")
    out = build()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "result": out}, separators=(",", ":"), default=_json_default),
                        encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass
    return out


def write_fit(name: str, obj: Any) -> Path:
    """Write a JSON fit to models/fitted/<name>.json (compact)."""
    FITTED.mkdir(parents=True, exist_ok=True)
    path = FITTED / f"{name}.json"
    path.write_text(json.dumps(clean(obj, 6), separators=(",", ":"), default=_json_default), encoding="utf-8")
    return path


def read_fit(name: str) -> Any:
    return read_json(FITTED / f"{name}.json")


_LAHMAN_PEOPLE: dict = {}


def lahman_people() -> pd.DataFrame | None:
    """Lahman People.csv (retroID, bbrefID, names) from builder A's cache, or None."""
    if "df" not in _LAHMAN_PEOPLE:
        df = None
        try:
            from oddsmarkets.baseball.sources import lahman
            df = lahman.load("People.csv")
        except Exception:
            df = None
        _LAHMAN_PEOPLE["df"] = df
    return _LAHMAN_PEOPLE["df"]


def retro_maps(people: dict | None = None) -> dict[str, dict]:
    """{"r2m": retro -> MLBAM pid, "r2b": retro -> bbref, "b2r": bbref -> retro, "name": retro or pid -> name}
    from the Chadwick crosswalk, completed from Lahman People.csv where the crosswalk is missing."""
    people = load_people() if people is None else people
    r2m, r2b, name = {}, {}, {}
    for k, v in (people or {}).items():
        if not isinstance(v, dict):
            continue
        r = v.get("retro")
        if r:
            if not str(k).startswith("r:"):
                r2m[r] = str(k)
            if v.get("bbref"):
                r2b[r] = v["bbref"]
            name[r] = v.get("name")
        name[str(k)] = v.get("name")
    lp = lahman_people()
    if lp is not None and "retroID" in lp:
        sub = lp.dropna(subset=["retroID"])
        for r, b, f, l in zip(sub["retroID"], sub.get("bbrefID", sub["playerID"]), sub.get("nameFirst", ""), sub.get("nameLast", "")):
            r2b.setdefault(r, b)
            nm = f"{f if isinstance(f, str) else ''} {l if isinstance(l, str) else ''}".strip()
            name.setdefault(r, nm)
            name.setdefault(f"r:{r}", nm)
    return {"r2m": r2m, "r2b": r2b, "b2r": {b: r for r, b in r2b.items()}, "name": name}
