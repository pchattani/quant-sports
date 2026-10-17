"""
Shared plumbing for builder C's models (shots, impact, winprob, awards): data and cache
roots (env `HARDWOOD_DATA`, `HARDWOOD_CACHE`), the period clock, table normalisation for the
contract's {"cols", "rows"} files, a small cached-JSON helper, and a penalised logistic
regression (Newton/IRLS on a sparse or dense design) used by the shot and win-probability models.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import scipy.sparse as sp
import scipy.linalg

ROOT = Path(__file__).resolve().parents[3]

PERIOD_S = {"nba": 720, "wnba": 600}
OT_S = 300
REG_PERIODS = 4

SHOT_COLS = ["game_id", "t", "period", "team", "shooter", "x_ft", "y_ft", "dist_ft", "angle_deg", "zone", "shot_type",
             "value", "made", "assisted", "assister", "blocked", "putback", "transition", "margin_before", "clutch"]
STINT_COLS = ["game_id", "t0", "t1", "h1", "h2", "h3", "h4", "h5", "a1", "a2", "a3", "a4", "a5",
              "poss_h", "poss_a", "pts_h", "pts_a"]
# GAME box player row (contract BOX_COLS order)
BOX_COLS = ["player_id", "starter", "sec", "pts", "fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl",
            "blk", "tov", "pf", "pm"]


def data_root() -> Path:
    return Path(os.environ.get("HARDWOOD_DATA") or (ROOT / "docs" / "hardwood" / "data"))


def cache_root() -> Path:
    return Path(os.environ.get("HARDWOOD_CACHE") or (ROOT / "data" / "basketball" / "cache"))


def pbp_root() -> Path:
    return Path(os.environ.get("HARDWOOD_PBP") or (ROOT / "data" / "basketball" / "pbp"))


def period_len(league: str, period: int) -> int:
    return PERIOD_S.get(str(league).lower(), 720) if int(period) <= REG_PERIODS else OT_S


def period_start(league: str, period: int) -> int:
    p = int(period)
    L = PERIOD_S.get(str(league).lower(), 720)
    if p <= REG_PERIODS:
        return (p - 1) * L
    return REG_PERIODS * L + (p - REG_PERIODS - 1) * OT_S


def regulation_s(league: str) -> int:
    return REG_PERIODS * PERIOD_S.get(str(league).lower(), 720)


def game_minutes(league: str) -> float:
    return regulation_s(league) / 60.0


def as_frame(obj: Any, cols: list[str] | None = None) -> pd.DataFrame:
    """A DataFrame from a DataFrame, a contract {"cols", "rows"} dict, a list of row lists
    (in `cols` order) or a list of dicts."""
    if obj is None:
        return pd.DataFrame(columns=cols or [])
    if isinstance(obj, pd.DataFrame):
        return obj
    if isinstance(obj, dict) and "rows" in obj:
        c = obj.get("cols") or cols
        rows = obj.get("rows") or []
        if rows and c and len(rows[0]) != len(c) and cols and len(rows[0]) == len(cols):
            c = cols
        return pd.DataFrame(rows, columns=c)
    obj = list(obj)
    if not obj:
        return pd.DataFrame(columns=cols or [])
    if isinstance(obj[0], dict):
        return pd.DataFrame(obj)
    return pd.DataFrame(obj, columns=cols[: len(obj[0])] if cols else None)


def resolve(path: Path) -> Path:
    """The file to read for `path`: `<path>.gz` when it exists and is not older than the plain file
    (completed seasons commit only the gzipped shots/stints), else `path` itself."""
    p = Path(path)
    gz = p.with_name(p.name + ".gz")
    try:
        gst = gz.stat()
    except OSError:
        return p
    try:
        pst = p.stat()
    except OSError:
        return gz
    return gz if gst.st_mtime_ns >= pst.st_mtime_ns else p


def exists(path: Path) -> bool:
    """`path` or its `.gz` sibling exists."""
    p = Path(path)
    return p.exists() or p.with_name(p.name + ".gz").exists()


def read_json(path: Path) -> Any:
    """JSON from `path`, or from `<path>.gz` (see `resolve`); None when missing or unreadable."""
    p = resolve(path)
    try:
        if p.name.endswith(".gz"):
            import gzip
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
        return None


def season_file(league: str, season: int, name: str) -> Any:
    return read_json(data_root() / str(league) / str(season) / name)


def file_key(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, Path):
            p = resolve(p)
            try:
                st = p.stat()
                h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode())
            except OSError:
                h.update(f"{p}|missing".encode())
        else:
            h.update(json.dumps(p, sort_keys=True, default=str).encode())
        h.update(b"|")
    return h.hexdigest()


def cached(kind: str, name: str, key: str, build: Callable[[], Any], use_cache: bool = True) -> Any:
    """JSON cache under cache_root()/kind/name.json, invalidated by `key`. Never raises on IO."""
    path = cache_root() / kind / f"{name}.json"
    if use_cache and path.exists():
        c = read_json(path)
        if isinstance(c, dict) and c.get("key") == key:
            return c.get("result")
    out = build()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "result": out}, separators=(",", ":"), default=_json_default), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass
    return out


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def clean(x: Any, nd: int = 4) -> Any:
    """Round floats, map non-finite to None, recurse into dicts/lists (for payloads)."""
    if isinstance(x, dict):
        return {k: clean(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v, nd) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return round(v, nd) if math.isfinite(v) else None
    return x


def hat_basis(x: np.ndarray, knots: Iterable[float]) -> sp.csr_matrix:
    """Piecewise-linear B-spline ("hat") basis: each x is a convex combination of its two
    neighbouring knots; values outside the knot range are clamped to the end knots."""
    k = np.asarray(list(knots), float)
    x = np.clip(np.asarray(x, float), k[0], k[-1])
    j = np.clip(np.searchsorted(k, x, side="right") - 1, 0, len(k) - 2)
    w = (x - k[j]) / (k[j + 1] - k[j])
    n = len(x)
    rows = np.concatenate([np.arange(n), np.arange(n)])
    cols = np.concatenate([j, j + 1])
    vals = np.concatenate([1 - w, w])
    return sp.csr_matrix((vals, (rows, cols)), shape=(n, len(k)))


def diff_penalty(m: int, order: int = 2) -> np.ndarray:
    D = np.diff(np.eye(m), n=order, axis=0)
    return D.T @ D


def logistic_fit(X, y: np.ndarray, P: np.ndarray, w: np.ndarray | None = None, beta0: np.ndarray | None = None,
                 prior_mean: np.ndarray | None = None, max_iter: int = 50, tol: float = 1e-8) -> dict:
    """
    Penalised logistic regression by Newton-Raphson (IRLS) with step halving:
        maximise  sum_i w_i [y_i eta_i - log(1 + e^eta_i)] - 1/2 (b - m)' P (b - m)
    X may be dense or scipy.sparse. Returns {"beta", "cov" (inverse penalised Hessian), "iters", "loglik"}.
    """
    n, p = X.shape
    w = np.ones(n) if w is None else np.asarray(w, float)
    y = np.asarray(y, float)
    m = np.zeros(p) if prior_mean is None else np.asarray(prior_mean, float)
    b = np.zeros(p) if beta0 is None else np.asarray(beta0, float).copy()
    issp = sp.issparse(X)

    def obj(beta):
        eta = X @ beta
        ll = float(np.sum(w * (y * eta - np.logaddexp(0.0, eta))))
        d = beta - m
        return ll - 0.5 * float(d @ P @ d), eta

    f, eta = obj(b)
    it = 0
    H = None
    for it in range(1, max_iter + 1):
        mu = 1.0 / (1.0 + np.exp(-eta))
        g = X.T @ (w * (y - mu)) - P @ (b - m)
        v = w * mu * (1 - mu)
        if issp:
            H = (X.T @ X.multiply(v[:, None]).tocsr()).toarray() + P
        else:
            H = X.T @ (X * v[:, None]) + P
        H = 0.5 * (H + H.T)
        try:
            step = scipy.linalg.solve(H + 1e-10 * np.eye(p), np.asarray(g).ravel(), assume_a="pos")
        except (np.linalg.LinAlgError, ValueError):
            step = np.linalg.lstsq(H, np.asarray(g).ravel(), rcond=None)[0]
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
    mu = 1.0 / (1.0 + np.exp(-eta))
    v = w * mu * (1 - mu)
    if issp:
        H = (X.T @ X.multiply(v[:, None]).tocsr()).toarray() + P
    else:
        H = X.T @ (X * v[:, None]) + P
    try:
        cov = np.linalg.inv(0.5 * (H + H.T) + 1e-10 * np.eye(p))
    except np.linalg.LinAlgError:
        cov = np.linalg.pinv(H)
    return {"beta": b, "cov": cov, "iters": it, "loglik": f}


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(x, float)))


def fold_name(s: str) -> str:
    """Accent-, case- and punctuation-insensitive name key ("Nikola Jokić" -> "nikolajokic")."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    for suf in (" jr.", " jr", " sr.", " sr", " iii", " ii", " iv"):
        if t.endswith(suf):
            t = t[: -len(suf)]
    return "".join(c for c in t if c.isalnum())


def box_frame(games: dict | Iterable[dict], stypes: Iterable[str] = ("reg",)) -> pd.DataFrame:
    """One row per player-game from GAME box scores: BOX_COLS + game_id, date, team, opp, home(0/1),
    team possessions (FGA - OREB + TOV + 0.44 FTA, averaged over the sides with a real estimate), game seconds,
    team/opp points. A side with no player-seconds (a missing box score) contributes no rows."""
    gl = games.values() if isinstance(games, dict) else games
    stypes = set(stypes) if stypes is not None else None
    rows = []
    for g in gl:
        if not g or g.get("status") != "post" or (stypes is not None and g.get("stype") not in stypes):
            continue
        box = g.get("box") or {}
        h, a = g.get("home"), g.get("away")
        if h not in box or a not in box:
            continue
        # A side whose players all have 0 seconds is a missing box score, not a game played with no stats
        # (ESPN: NBA 2013-2018, about 330 team-games a season, mostly CHI and NO; a refetch returns the same
        # zeros): its player rows are left out and the game's possessions come from the other side.
        empty = {tid for tid in (h, a) if not sum(float(r[2] or 0) for r in (box[tid].get("players") or []))}
        poss = []
        for tid in (h, a):
            if tid in empty:
                continue
            t = box[tid].get("team") or {}
            if t.get("fga") is None:
                tp = box[tid].get("players") or []
                fga = sum(r[5] or 0 for r in tp); oreb = sum(r[10] or 0 for r in tp)
                tov = sum(r[15] or 0 for r in tp); fta = sum(r[9] or 0 for r in tp)
            else:
                fga, oreb, fta, tov = t.get("fga") or 0, t.get("oreb") or 0, t.get("fta") or 0, t.get("tov") or 0
            poss.append(fga - oreb + tov + 0.44 * fta)
        poss = [p for p in poss if p > 20]
        gposs = float(np.mean(poss)) if poss else 0.0
        periods = int(g.get("periods") or 4)
        pts = {h: g.get("hs"), a: g.get("as")}
        for tid, opp in ((h, a), (a, h)):
            if tid in empty:
                continue
            for r in box[tid].get("players") or []:
                rec = dict(zip(BOX_COLS, list(r) + [None] * (len(BOX_COLS) - len(r))))
                rec.update({"game_id": g.get("id"), "date": str(g.get("date") or "")[:10], "team": tid, "opp": opp,
                            "home": int(tid == h), "team_poss": gposs, "periods": periods,
                            "team_pts": pts.get(tid), "opp_pts": pts.get(opp)})
                rows.append(rec)
    df = pd.DataFrame(rows)
    if not df.empty:
        for c in BOX_COLS[1:]:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        df["player_id"] = df["player_id"].astype(str)
    return df
