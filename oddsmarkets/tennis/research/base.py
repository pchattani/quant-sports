"""
Stage 1 of the tennis edge research: the walk-forward baseline frame and the full match timeline.

`base_frame(tour)` runs `backtest.predictions` (the production walk-forward: sequential Elo, serve/return
refitted monthly through the day before each month, cached under ACE_CACHE/backtest_sr) and returns one row per
scorable tour-level match (2008->, two warm-up years before 2010), oriented at random by the backtest's fixed
hash: player A is p1 unless `flip`, y = 1 when A won. The production blend for year Y is fitted on the years
before Y only (as backtest.evaluate does). Raw closing odds from tennis-data (Pinnacle, Bet365, Max, Avg,
Betfair exchange) are carried oriented to A, not de-vigged.

`timeline(tour)` returns every MATCH row on disk (all levels and statuses: qualifying, Challenger / WTA 125,
retirements, walkovers) in compact form, for the walk-forward feature builders in `features.py`.

Both are cached as parquet under data/edge/cache/ keyed on the stores' signature (git-ignored).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.models import backtest as BT
from oddsmarkets.tennis.models import predict as PR

CACHE = _io.ROOT / "data" / "edge" / "cache"
BOOK_KEYS = ("ps", "b365", "max", "avg", "bfe")


def _cache(name: str, key: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{name}_{key[:10]}.parquet"


def _odds_pair(m: dict, k: str):
    o = (m.get("odds") or {}).get(k)
    try:
        a, b = float(o[0]), float(o[1])
    except (TypeError, ValueError, IndexError):
        return (np.nan, np.nan)
    if not (a > 1.0 and b > 1.0 and math.isfinite(a) and math.isfinite(b)):
        return (np.nan, np.nan)
    return (a, b)


def _games(sets) -> tuple[int, int, int]:
    """(games p1, games p2, sets played) over the set scores present."""
    g1 = g2 = n = 0
    for s in sets or []:
        try:
            a, b = int(s[0]), int(s[1])
        except (TypeError, ValueError, IndexError):
            continue
        g1 += a
        g2 += b
        n += 1
    return g1, g2, n


def timeline(tour: str, use_cache: bool = True) -> pd.DataFrame:
    t = _io.tour_key(tour)
    key = _io.file_key("timeline-2", _io.signature(t))
    p = _cache(f"tn_timeline_{t}", key)
    if use_cache and p.exists():
        return pd.read_parquet(p)
    ev_country: dict = {}
    for y in _io.years_on_disk(t):
        st = _io.load_store(t, y) or {}
        for eid, e in (st.get("events") or {}).items():
            ev_country[eid] = (e.get("country"), e.get("city"), e.get("tid"))
    recs = []
    for m in _io.load_matches(t, statuses=None):
        if not (m.get("p1") and m.get("p2")):
            continue
        g1, g2, ns = _games(m.get("sets"))
        c = ev_country.get(m.get("event")) or (None, None, None)
        recs.append({
            "id": m["id"], "date": str(m["date"])[:10], "event": m.get("event"), "round": str(m.get("round") or ""),
            "level": str(m.get("level")), "surface": _io.fold_surface(m.get("surface")), "raw_surface": str(m.get("surface")),
            "indoor": bool(m.get("indoor")), "bo": 5 if int(m.get("best_of") or 3) == 5 else 3,
            "p1": str(m["p1"]), "p2": str(m["p2"]), "winner": str(m.get("winner") or ""), "status": str(m.get("status")),
            "g1": g1, "g2": g2, "nsets": ns, "dur": float(m["duration_min"]) if m.get("duration_min") else np.nan,
            "rank1": float(m["rank1"]) if m.get("rank1") else np.nan, "rank2": float(m["rank2"]) if m.get("rank2") else np.nan,
            "country": c[0], "city": c[1], "tid": c[2],
        })
    df = pd.DataFrame(recs)
    df.to_parquet(p)
    return df


def base_frame(tour: str, first_year: int = 2010, use_cache: bool = True, log=None) -> pd.DataFrame:
    t = _io.tour_key(tour)
    last = max(_io.years_on_disk(t))
    key = _io.file_key("base-1", _io.signature(t), _io.fits_signature(t), first_year)
    p = _cache(f"tn_base_{t}", key)
    if use_cache and p.exists():
        return pd.read_parquet(p)
    matches = _io.load_matches(t, statuses=None)
    by_id = {m["id"]: m for m in matches}
    rows, fits = BT.predictions(t, matches, range(first_year, last + 1), log=log)
    del fits
    recs = []
    for r in rows:
        m = by_id[r["id"]]
        fl = bool(r["flip"])
        a, b = (m["p2"], m["p1"]) if fl else (m["p1"], m["p2"])
        o = lambda p_: None if p_ is None else (1.0 - p_ if fl else p_)  # noqa: E731
        rec = {"id": r["id"], "date": r["date"], "year": r["year"], "level": r["level"], "event": r["event"],
               "round": str(m.get("round") or ""), "surface": _io.fold_surface(m.get("surface")),
               "indoor": bool(m.get("indoor")), "bo": r["bo"], "rule": r["rule"], "A": str(a), "B": str(b),
               "y": 0 if fl else 1, "flip": fl,
               "elo": o(r["elo"]), "sr": o(r["sr"]),
               "spw_A": (r["pb"] if fl else r["pa"]), "spw_B": (r["pa"] if fl else r["pb"]),
               "rank_A": m.get("rank2" if fl else "rank1"), "rank_B": m.get("rank1" if fl else "rank2"),
               "pts_A": m.get("pts2" if fl else "pts1"), "pts_B": m.get("pts1" if fl else "pts2")}
        for k in BOOK_KEYS:
            x1, x2 = _odds_pair(m, k)
            rec[f"{k}_A"], rec[f"{k}_B"] = (x2, x1) if fl else (x1, x2)
        recs.append(rec)
    del rows
    df = pd.DataFrame(recs)
    for c in ("elo", "sr", "spw_A", "spw_B", "rank_A", "rank_B", "pts_A", "pts_B"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # production blend, walk-forward by year (weights for Y fitted on years < Y), as backtest.evaluate
    own = PR.blend_params(t)
    df["model"] = np.nan
    for Y in sorted(df["year"].unique()):
        early = df[(df["year"] < Y) & df["elo"].notna() & df["sr"].notna()]
        if len(early):
            bf = PR.fit_blend(early["elo"].to_numpy(), early["sr"].to_numpy(), early["y"].to_numpy())
            w = (bf["w_elo"], bf["w_sr"])
        else:
            w = (float(own["w_elo"]), float(own["w_sr"]))
        m_ = (df["year"] == Y)
        both = m_ & df["elo"].notna() & df["sr"].notna()
        df.loc[both, "model"] = PR.blend(df.loc[both, "elo"].to_numpy(), df.loc[both, "sr"].to_numpy(), w[0], w[1])
        only = m_ & df["elo"].notna() & df["sr"].isna()
        df.loc[only, "model"] = df.loc[only, "elo"]
    df.to_parquet(p)
    return df
