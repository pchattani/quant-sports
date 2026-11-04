"""Walk-forward DOTS ratings (no look-ahead).

Each stream (sex × equipment group) is its own scale. For a meet, every lifter's pre-meet rating is
the decayed mean of their past SBD DOTS, shrunk to the stream mean:

    r = (k0 * m0 + sum w * dots) / (k0 + sum w),  w = 0.5 ** (age_days / half_life)

m0 is the mean DOTS of the stream in the training window (so a newcomer is an average lifter, not
zero). Residual = actual dots − pre; the sealed test scores those residuals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import canon, store


@dataclass(frozen=True)
class Params:
    half_life: float = 365.0
    k0: float = 4.0
    m0: float = 400.0          # overwritten per stream by the training mean
    min_field: int = 8         # meets smaller than this are not used as updates (the residual is noise)


# chosen on SBD raw 2012-2019 by RMSE of pre-meet DOTS (models/backtest.py); the grid in tuning.csv
CHOSEN = Params(half_life=365.0, k0=4.0)


def load_scored(entries: pd.DataFrame | None = None) -> pd.DataFrame:
    """SBD rows with a total and DOTS, a bodyweight, and a stream we rate."""
    df = entries if entries is not None else store.load_entries()
    if df.empty:
        return df
    df = df[(df["event"] == "SBD") & df["total"].notna() & df["dots"].notna() & df["bw"].notna()].copy()
    df = df[df["sex"].isin(("M", "F")) & df["eq"].isin(("raw", "wraps", "equipped"))]
    df["stream"] = np.where(df["sex"] == "M", "men_", "women_") + df["eq"].map(
        {"raw": "raw", "wraps": "wraps", "equipped": "eq"})
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["date", "meet_id"]).reset_index(drop=True)


class _Book:
    def __init__(self, p: Params):
        self.p = p
        self.s: dict[str, float] = {}
        self.w: dict[str, float] = {}
        self.n: dict[str, int] = {}
        self.t: dict[str, pd.Timestamp] = {}

    def _decay(self, pid: str, t: pd.Timestamp) -> float:
        dt = (t - self.t[pid]).days
        return 0.5 ** (dt / self.p.half_life) if dt > 0 else 1.0

    def rating(self, pid: str, t: pd.Timestamp) -> float:
        if pid not in self.t:
            return self.p.m0
        f = self._decay(pid, t)
        return (self.p.k0 * self.p.m0 + self.s[pid] * f) / (self.p.k0 + self.w[pid] * f)

    def weight(self, pid: str, t: pd.Timestamp) -> float:
        return self.w[pid] * self._decay(pid, t) if pid in self.t else 0.0

    def add(self, pid: str, t: pd.Timestamp, dots: float) -> None:
        if pid in self.t:
            f = self._decay(pid, t)
            self.s[pid] = self.s[pid] * f + dots
            self.w[pid] = self.w[pid] * f + 1.0
            self.n[pid] += 1
        else:
            self.s[pid], self.w[pid], self.n[pid] = dots, 1.0, 1
        self.t[pid] = t


def walk(rows: pd.DataFrame, p: Params = CHOSEN) -> tuple[pd.DataFrame, dict[str, _Book]]:
    """Per-start rows with pre-meet rating, plus the finished book per stream.

    Output columns: stream, meet_id, pid, date, dots, total, bw, sex, eq, tested, pre, weight, n, resid.
    """
    books: dict[str, _Book] = {}
    out = []
    for (start, meet, stream), g in rows.groupby(["date", "meet_id", "stream"], sort=False):
        book = books.setdefault(stream, _Book(p))
        scored = len(g) >= p.min_field
        for pid, dots, total, bw, sex, eq, tested in zip(
                g["pid"], g["dots"], g["total"], g["bw"], g["sex"], g["eq"], g["tested"]):
            pre = book.rating(pid, start)
            wt = book.weight(pid, start)
            n = book.n.get(pid, 0)
            out.append((stream, meet, pid, start, float(dots), float(total), float(bw), sex, eq,
                        bool(tested), pre, wt, n, float(dots) - pre))
            if scored:
                book.add(pid, start, float(dots))
    scored_df = pd.DataFrame(out, columns=["stream", "meet_id", "pid", "date", "dots", "total", "bw",
                                           "sex", "eq", "tested", "pre", "weight", "n", "resid"])
    return scored_df, books


def current(book: _Book, at: date | None = None, min_meets: int = 5, active_days: int = 400) -> pd.DataFrame:
    t = pd.Timestamp(at or date.today())
    rows = [(pid, book.rating(pid, t), book.weight(pid, t), book.n[pid], book.t[pid]) for pid in book.t
            if book.n[pid] >= min_meets and (t - book.t[pid]) <= timedelta(days=active_days)]
    df = pd.DataFrame(rows, columns=["pid", "rating", "weight", "meets", "last"])
    return df.sort_values("rating", ascending=False).reset_index(drop=True)
