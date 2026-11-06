"""The meet forecast: expected DOTS (and so an expected total at the lifter's bodyweight), its spread, the bomb-out
chance, and podium chances from simulating each flight. Fitted on the training years only (TRAIN_END), choices made
on the validation years, scored once on the sealed test years (models/backtest.py).

Why not the rating alone: lifters improve, so a decayed mean of past meets lags (on the sealed test the decayed mean
misses by about 40 DOTS a meet, the last meet alone by about 32). The forecast starts from the last meet and adds what
the training years say about lifters at that stage: meets so far, age, and time since the last meet, plus how far
the last meet sits from the lifter's longer-run level and best.

    mu = last + a + b * (rating - last) + c * (best - last) + n_bucket + age_bucket + gap_bucket   (least squares)

Spread: the training residual's sd per meets-so-far and gap bucket. Bomb-outs: the training share of full-power
entries without a total per stream and newcomer flag. A newcomer (no scored meet) is the stream's mean first meet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import canon

N_BINS = [0, 1, 2, 3, 5, 9, 10_000]
N_LABS = ["1", "2", "3", "4-5", "6-9", "10+"]
AGE_BINS = [0, 18, 21, 24, 29, 34, 39, 49, 59, 200]
AGE_LABS = ["<18", "18-20", "21-23", "24-28", "29-33", "34-38", "39-48", "49-58", "59+"]
GAP_BINS = [-1, 60, 120, 240, 400, 800, 1e7]
GAP_LABS = ["<60", "60-119", "120-239", "240-399", "400-799", "800+"]
SIMS = 400


def buckets(df: pd.DataFrame) -> pd.DataFrame:
    nb = pd.cut(df["n"], N_BINS, labels=N_LABS).astype("object")
    ab = pd.cut(df["age"], AGE_BINS, labels=AGE_LABS).astype("object").where(df["age"].notna(), "unknown")
    gb = pd.cut(df["gap"], GAP_BINS, labels=GAP_LABS).astype("object")
    return pd.DataFrame({"nb": nb, "ab": ab, "gb": gb}, index=df.index)


@dataclass
class Model:
    variant: str = "full"                    # last | buckets | full
    coef: dict = field(default_factory=dict)  # name -> value
    sd: dict = field(default_factory=dict)    # "nb|gb" -> residual sd
    sd_all: float = 32.0
    new_mu: dict = field(default_factory=dict)  # stream -> mean first-meet DOTS
    new_sd: dict = field(default_factory=dict)
    bomb: dict = field(default_factory=dict)  # "stream|new" -> share without a total

    def design(self, df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
        cols, names = [np.ones(len(df))], ["a"]
        if self.variant == "full":
            cols += [(df["pre"] - df["last_dots"]).to_numpy(dtype=float), (df["best_dots"] - df["last_dots"]).to_numpy(dtype=float)]
            names += ["b", "c"]
        if self.variant in ("buckets", "full"):
            B = buckets(df)
            for col, labs in (("nb", N_LABS[1:]), ("ab", AGE_LABS + ["unknown"]), ("gb", GAP_LABS[1:])):
                for lab in labs:
                    if col == "ab" and lab == "24-28":
                        continue                     # the reference age band
                    cols.append((B[col] == lab).to_numpy(dtype=float))
                    names.append(f"{col}:{lab}")
        return np.column_stack(cols), names

    def fit(self, rows: pd.DataFrame, first: pd.DataFrame, entries_train: pd.DataFrame | None = None) -> "Model":
        d = rows[(rows["n"] > 0) & rows["last_dots"].notna()]
        y = (d["dots"] - d["last_dots"]).to_numpy(dtype=float)
        if self.variant == "last":
            self.coef = {}
            res = y
        else:
            X, names = self.design(d)
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            self.coef = {k: float(v) for k, v in zip(names, beta)}
            res = y - X @ beta
        B = buckets(d)
        key = B["nb"].astype(str) + "|" + B["gb"].astype(str)
        sd = pd.Series(res, index=d.index).groupby(key).agg(["std", "size"])
        self.sd = {k: float(v["std"]) for k, v in sd.iterrows() if v["size"] >= 200 and np.isfinite(v["std"])}
        self.sd_all = float(np.std(res)) if len(res) else 32.0
        for s, g in first.groupby("stream"):
            self.new_mu[s] = float(g["dots"].mean())
            self.new_sd[s] = float(g["dots"].std())
        if entries_train is not None and len(entries_train):
            et = entries_train
            for (s, new), g in et.groupby(["stream", "new"]):
                if len(g) >= 200:
                    self.bomb[f"{s}|{int(new)}"] = float(g["dq"].mean())
        return self

    def mu(self, df: pd.DataFrame) -> np.ndarray:
        """Expected DOTS for rows with history (n > 0); NaN elsewhere."""
        out = np.full(len(df), np.nan)
        m = ((df["n"] > 0) & df["last_dots"].notna()).to_numpy()
        if not m.any():
            return out
        d = df[m]
        if self.variant == "last" or not self.coef:
            out[m] = d["last_dots"].to_numpy(dtype=float)
            return out
        X, names = self.design(d)
        beta = np.array([self.coef.get(k, 0.0) for k in names])
        out[m] = d["last_dots"].to_numpy(dtype=float) + X @ beta
        return out

    def spread(self, df: pd.DataFrame) -> np.ndarray:
        B = buckets(df)
        key = (B["nb"].astype(str) + "|" + B["gb"].astype(str)).to_numpy()
        return np.array([self.sd.get(k, self.sd_all) for k in key])

    def forecast(self, df: pd.DataFrame) -> pd.DataFrame:
        """mu, sd (DOTS) and the bomb-out chance for every row (newcomers get the stream's first-meet numbers)."""
        mu = self.mu(df)
        sd = self.spread(df)
        new = ~np.isfinite(mu)
        st = df["stream"].to_numpy()
        mu[new] = [self.new_mu.get(s, 330.0) for s in st[new]]
        sd[new] = [self.new_sd.get(s, 70.0) for s in st[new]]
        bomb = np.array([self.bomb.get(f"{s}|{int(n)}", 0.06) for s, n in zip(st, new)])
        return pd.DataFrame({"mu": mu, "sd": sd, "p_bomb": bomb, "new": new}, index=df.index)

    def to_json(self) -> dict:
        return {"variant": self.variant, "coef": {k: round(v, 3) for k, v in self.coef.items()},
                "sd_all": round(self.sd_all, 2), "new_mu": {k: round(v, 1) for k, v in self.new_mu.items()},
                "bomb": {k: round(v, 4) for k, v in self.bomb.items()}}


def pre_state(entrants: pd.DataFrame, walked: pd.DataFrame, p, m0: dict | None) -> pd.DataFrame:
    """For entrant rows (stream, pid, date, ...), what the book knew the day before: n, last, best, rating, gap.

    Uses only walked rows dated strictly before the entrant's date (merge_asof, allow_exact_matches=False)."""
    w = walked[walked["scored"]][["stream", "pid", "date", "dots", "st_t", "st_s", "st_w"]].copy()
    w = w.sort_values(["stream", "pid", "date"])
    g = w.groupby(["stream", "pid"])
    w["n_after"] = g.cumcount() + 1
    w["best_after"] = g["dots"].cummax()
    first = g["date"].transform("min")
    w["first"] = first
    e = entrants.copy()
    e["date"] = pd.to_datetime(e["date"]).astype("datetime64[ns]")
    w["date"] = pd.to_datetime(w["date"]).astype("datetime64[ns]")
    w["st_t"] = pd.to_datetime(w["st_t"]).astype("datetime64[ns]")
    e["_i"] = np.arange(len(e))
    e = e.sort_values("date")
    w = w.sort_values("date")
    m = pd.merge_asof(e, w.rename(columns={"date": "prev_date", "dots": "last_dots"}), left_on="date", right_on="prev_date",
                      by=["stream", "pid"], allow_exact_matches=False, direction="backward")
    m = m.sort_values("_i")
    f = np.power(0.5, (m["date"] - m["st_t"]).dt.days.clip(lower=0) / p.half_life)
    m0v = m["stream"].map(lambda s: (m0 or {}).get(s, p.m0)).astype(float)
    m["pre"] = np.where(m["st_s"].notna(), (p.k0 * m0v + m["st_s"] * f) / (p.k0 + m["st_w"] * f), m0v)
    m["n"] = m["n_after"].fillna(0).astype(int)
    m["best_dots"] = m["best_after"]
    m["gap"] = (m["date"] - m["prev_date"]).dt.days.astype(float)
    m.index = entrants.index
    return m.drop(columns=["_i"])


def simulate_podium(groups: np.ndarray, mu_kg: np.ndarray, sd_kg: np.ndarray, p_bomb: np.ndarray,
                    sims: int = SIMS, seed: int = 7, top: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """P(top-`top` finish) and P(win) for each row, flights given by `groups` (integer codes). Totals ~ normal, a
    bomb-out with p_bomb scores nothing. Rows are processed flight by flight in blocks of equal size."""
    rng = np.random.default_rng(seed)
    n = len(groups)
    p_pod = np.zeros(n)
    p_win = np.zeros(n)
    if n == 0:
        return p_pod, p_win
    order = np.argsort(groups, kind="stable")
    g_sorted = groups[order]
    starts = np.flatnonzero(np.r_[True, g_sorted[1:] != g_sorted[:-1]])
    ends = np.r_[starts[1:], n]
    sizes = ends - starts
    for size in np.unique(sizes):
        sel = np.flatnonzero(sizes == size)
        if size > 60:
            continue
        idx = np.stack([order[starts[i]:ends[i]] for i in sel])              # (G, size)
        for c0 in range(0, len(idx), max(1, 200_000 // (size * sims) + 1)):
            I = idx[c0:c0 + max(1, 200_000 // (size * sims) + 1)]
            m, s, b = mu_kg[I][..., None], sd_kg[I][..., None], p_bomb[I][..., None]
            draw = m + s * rng.standard_normal((I.shape[0], size, sims))
            draw = np.where(rng.random((I.shape[0], size, sims)) < b, -np.inf, draw)
            # rank: how many in the flight beat this draw
            better = (draw[:, None, :, :] > draw[:, :, None, :]).sum(axis=2)  # (G, size, sims)
            ok = np.isfinite(draw)
            p_pod[I] = np.mean(ok & (better < top), axis=2)
            p_win[I] = np.mean(ok & (better == 0), axis=2)
    return p_pod, p_win


def flights(entrants: pd.DataFrame) -> np.ndarray:
    key = (entrants["meet_id"].astype(str) + "|" + entrants["sex"].astype(str) + "|" + entrants["equipment"].astype(str) + "|" +
           entrants["division"].astype(str) + "|" + entrants["wclass"].astype(str))
    return pd.factorize(key)[0]


def to_kg(sex: pd.Series, bw: pd.Series, dots: np.ndarray) -> np.ndarray:
    k = np.array([canon.dots_coeff(s, b) if b == b else np.nan for s, b in zip(sex, bw)])
    return dots / k
