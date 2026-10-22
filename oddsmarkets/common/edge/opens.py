"""
Kalshi opening quotes for the edge files (docs/research/EDGE_PROTOCOL.md section 3; docs/research/OPENING_PRICES.md).

Every sport's honest test is the model at a decision time against the price available then. Sportsbook openers in
our data (ESPN core odds, football-data's early columns) carry no timestamp; Kalshi's hourly candles do. This module
reads the sports' Kalshi candle caches into one shape and finds, per game:

* the **listing quote**: the first hourly candle at which every selection of the game has a liquid two-sided quote
  (0 < bid <= ask < 1, ask - bid <= MAX_SPREAD), quotes carried forward at most STALE_S;
* the **first usable quote** at or after a time t: the same test from t on. A model row is only valid from its own
  information cutoff, so the open decision of a sport is the first liquid quote at or after max(listing, cutoff);
* the **close**: the last liquid quote at or before the start (minus a minute).

Prices follow the sports' Kalshi conventions: a two-way game buys selection X at min(ask_X, 1 - bid_other) (YES on X
or NO on the other side), a single-market game (one YES contract) buys the home side at the ask and the away side at
1 - bid, a three-way football game buys YES at the ask; the taker fee (common/fees.kalshi_cost) is added, so
price_dec = 1 / (p + fee). fair = mid-points normalised over the game's selections.

Nothing here reads a model: the sport adapters in scripts/edge_opens.py join each sport's own model_p, taken from the
sport's edge rows whose information cutoff is at or before the decision.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from oddsmarkets.common.fees import kalshi_cost

MAX_SPREAD = 0.10          # a liquid quote: at most 10 cents wide on every selection
STALE_S = 6 * 3600         # a candle's quote is carried forward at most 6 hours
PRICE_SRC = "kalshi_open"  # the price_src of the rows this layer adds (removed and rebuilt on every run)


def _f(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return np.nan
    return v if np.isfinite(v) else np.nan


def _side(d: dict | None) -> float:
    d = d or {}
    return _f(d.get("close_dollars", d.get("close")))


def parse_candles(rows: list, ticker: str) -> list[tuple]:
    """Raw API candles (both the `close` and the `close_dollars` field formats) or the football cache's compacted
    candles -> [(ticker, end_ts, bid, ask, volume)]."""
    out = []
    for c in rows or []:
        ts = c.get("end_period_ts")
        if not ts:
            continue
        vol = _f(c.get("volume_fp", c.get("volume")))
        out.append((ticker, int(ts), _side(c.get("yes_bid")), _side(c.get("yes_ask")), 0.0 if np.isnan(vol) else vol))
    return out


def candles_from_dir(cdir: Path, tickers: Iterable[str] | None = None) -> pd.DataFrame:
    """A directory of <TICKER>.json files (raw API lists) or <EVENT>.json files ({ticker: [candles]})."""
    want = set(tickers) if tickers is not None else None
    rows: list[tuple] = []
    files = sorted(Path(cdir).glob("*.json")) if want is None else [Path(cdir) / f"{t}.json" for t in sorted(want)]
    for p in files:
        try:
            d = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            for tk, cs in d.items():
                if want is None or tk in want:
                    rows += parse_candles(cs, tk)
        elif want is None or p.stem in want:
            rows += parse_candles(d, p.stem)
    return pd.DataFrame(rows, columns=["ticker", "ts", "bid", "ask", "vol"])


def markets_from_json(paths: Iterable[Path]) -> pd.DataFrame:
    """Kalshi market listings (lists of market dicts) -> ticker, event, open/close/expected-expiration times, result,
    yes_sub_title."""
    rows = []
    for p in paths:
        try:
            ms = json.loads(Path(p).read_text("utf-8"))
        except (OSError, ValueError):
            continue
        for m in ms if isinstance(ms, list) else []:
            rows.append({"ticker": m.get("ticker"), "event": m.get("event_ticker"), "open_time": m.get("open_time"),
                         "close_time": m.get("close_time"), "exp_time": m.get("expected_expiration_time"),
                         "occurrence": m.get("occurrence_datetime"), "result": m.get("result"),
                         "yes_sub_title": m.get("yes_sub_title"), "title": m.get("title")})
    d = pd.DataFrame(rows).dropna(subset=["ticker"]).drop_duplicates("ticker")
    for c in ("open_time", "close_time", "exp_time", "occurrence"):
        d[c] = pd.to_datetime(d[c], utc=True, errors="coerce", format="mixed")
    return d


def _valid(bid: float, ask: float, max_spread: float) -> bool:
    return (np.isfinite(bid) and np.isfinite(ask) and 0 < bid <= ask < 1 and ask - bid <= max_spread + 1e-9)


class EventQuotes:
    """The hourly quotes of one game's markets (one, two or three YES contracts)."""

    def __init__(self, c: pd.DataFrame, tickers: list[str]):
        self.tickers = list(tickers)
        c = c[c["ticker"].isin(self.tickers)].sort_values("ts")
        self.ts = np.unique(c["ts"].to_numpy())
        self.by = {t: g[["ts", "bid", "ask", "vol"]].to_numpy(float) for t, g in c.groupby("ticker")}
        self.first_ts = int(c["ts"].min()) if len(c) else None

    def _state(self, t: int, max_spread: float, stale: int):
        """Each ticker's last candle at or before t (if not stale and liquid): {ticker: (bid, ask)} or None."""
        out = {}
        for tk in self.tickers:
            a = self.by.get(tk)
            if a is None or not len(a):
                return None
            i = np.searchsorted(a[:, 0], t, side="right") - 1
            if i < 0 or t - a[i, 0] > stale or not _valid(a[i, 1], a[i, 2], max_spread):
                return None
            out[tk] = (float(a[i, 1]), float(a[i, 2]))
        return out

    def first_at_or_after(self, t0: float, t_max: float, max_spread: float = MAX_SPREAD,
                          stale: int = STALE_S) -> tuple[int, dict] | None:
        """The first candle time in [t0, t_max] at which every ticker has a liquid quote."""
        for t in self.ts[(self.ts >= t0) & (self.ts <= t_max)]:
            q = self._state(int(t), max_spread, stale)
            if q is not None:
                return int(t), q
        return None

    def last_at_or_before(self, t_max: float, t_min: float | None = None, max_spread: float = MAX_SPREAD,
                          stale: int = STALE_S) -> tuple[int, dict] | None:
        sel = self.ts[self.ts <= t_max]
        if t_min is not None:
            sel = sel[sel >= t_min]
        for t in sel[::-1]:
            q = self._state(int(t), max_spread, stale)
            if q is not None:
                return int(t), q
        return None

    def volume_between(self, t0: float, t1: float) -> float:
        return float(sum(a[(a[:, 0] > t0) & (a[:, 0] <= t1), 3].sum() for a in self.by.values()))


def two_way(q: dict, home_tk: str, away_tk: str | None, home_is_yes: bool = True) -> dict:
    """Prices of home / away from one or two YES markets. With one market (away_tk None), the YES contract is the
    home side when home_is_yes, else the away side. Returns {sel: (cost, fair)}."""
    if away_tk is not None:
        (bh, ah), (ba, aa) = q[home_tk], q[away_tk]
        mh, ma = (bh + ah) / 2, (ba + aa) / 2
        fh = mh / (mh + ma)
        return {"home": (min(ah, 1 - ba), fh), "away": (min(aa, 1 - bh), 1 - fh)}
    b, a = q[home_tk]
    if not home_is_yes:
        b, a = 1 - a, 1 - b
    m = (b + a) / 2
    return {"home": (a, m), "away": (1 - b, 1 - m)}


def three_way(q: dict, tk: dict) -> dict:
    """{sel: ticker} for home / draw / away -> {sel: (cost at the ask, normalised mid)}."""
    mids = {s: (q[t][0] + q[t][1]) / 2 for s, t in tk.items()}
    tot = sum(mids.values())
    return {s: (q[t][1], mids[s] / tot) for s, t in tk.items()}


def dec(cost: float) -> float:
    """Decimal price of buying at `cost` dollars with the taker fee (NaN outside (0, 1))."""
    if not (np.isfinite(cost) and 0 < cost < 1):
        return np.nan
    c = float(kalshi_cost(cost))
    return 1.0 / c if 0 < c < 1 else np.nan


def merge_into(path: Path, rows: pd.DataFrame, src: str = PRICE_SRC) -> tuple[int, int]:
    """Replace this layer's rows (price_src == src) in an edge file with `rows`; other rows untouched. The write is
    atomic (temporary file, then replace). Returns (rows removed, rows added)."""
    path = Path(path)
    sig = (path.stat().st_mtime_ns, path.stat().st_size)
    base = pd.read_parquet(path)
    keep = base[base["price_src"].astype(str) != src]
    removed = len(base) - len(keep)
    if len(rows):
        rows = rows.copy()
        for c in keep.columns:
            if c not in rows.columns:
                rows[c] = np.nan
        extra = [c for c in rows.columns if c not in keep.columns]
        for c in extra:
            keep = keep.assign(**{c: np.nan})
        rows = rows[list(keep.columns)]
        for c in keep.columns:   # keep the file's dtypes where the new rows allow it
            if keep[c].dtype == object or rows[c].dtype == object:
                continue
            try:
                rows[c] = rows[c].astype(keep[c].dtype)
            except (TypeError, ValueError):
                pass
        out = pd.concat([keep, rows], ignore_index=True)
    else:
        out = keep
    tmp = path.with_suffix(path.suffix + ".opens.tmp")
    out.to_parquet(tmp, index=False)
    if (path.stat().st_mtime_ns, path.stat().st_size) != sig:     # the sport's builder rewrote it meanwhile
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{path.name} changed while the open rows were merged; nothing written, run again")
    tmp.replace(path)
    return removed, len(rows)


# ── forward capture (oddsmarkets/fund/capture): timestamped first sightings ──────────────────────────────────────

def _fund_root() -> Path:
    import os
    return Path(os.environ.get("FUND_DATA") or Path(__file__).resolve().parents[3] / "data" / "fund")


def capture_espn_opens(leagues: Iterable[str] | None = None, root: Path | None = None) -> pd.DataFrame:
    """
    The capture's ESPN scoreboard lines (DraftKings; `reference/venue=espn`, source espn:draftkings, polled about
    hourly from 2 Oct 2026) reduced to one row per game: first_seen (the first capture time: the opener `ml_open`
    was posted at or before it, so it is an honest upper bound on the opener's time), the opener and the current line
    at first sight, and the last pre-game sighting. Columns: league, espn_id, home, away, start, first_seen,
    ml_open_home/away/draw, ml_first_home/away/draw, p_fair_first_home, spread_first, total_first, last_seen,
    ml_last_home/away/draw, p_fair_last_home, n_seen. American odds as numbers.
    """
    import duckdb
    root = Path(root or _fund_root())
    src = (root / "reference" / "venue=espn" / "date=*" / "*.parquet").as_posix()
    con = duckdb.connect()
    con.execute("SET threads=2")
    d = con.execute(f"""SELECT underlying_id, epoch(ts) AS t, "values" AS v FROM read_parquet('{src}',
        hive_partitioning=true, union_by_name=true) WHERE source = 'espn:draftkings'""").fetchdf()
    if not len(d):
        return pd.DataFrame()
    parts = d["underlying_id"].str.split(":", expand=True)
    d["league"], d["espn_id"] = parts[2], parts[3]
    if leagues is not None:
        d = d[d["league"].isin(set(leagues))]
    vals = [json.loads(v) if isinstance(v, str) else {} for v in d["v"]]

    def am(x):
        try:
            return float(str(x).replace("+", "")) if x not in (None, "", "EVEN") else (100.0 if x == "EVEN" else np.nan)
        except ValueError:
            return np.nan
    flat = pd.DataFrame({
        "home": [v.get("home") for v in vals], "away": [v.get("away") for v in vals],
        "start": pd.to_datetime([v.get("start") for v in vals], utc=True, errors="coerce"),
        "state": [v.get("state") for v in vals],
        **{f"ml_{k}_{s}": [am(((v.get(k2) or {}) or {}).get(s)) for v in vals]
           for k, k2 in (("now", "ml"), ("open", "ml_open")) for s in ("home", "away", "draw")},
        "p_fair_home": [((v.get("p_fair") or {}) or {}).get("home") for v in vals],
        "spread": [v.get("spread") for v in vals], "total": [v.get("total") for v in vals],
    }, index=d.index)
    d = pd.concat([d[["league", "espn_id", "t"]], flat], axis=1)
    d["t"] = pd.to_datetime(d["t"], unit="s", utc=True)
    pre = d[(d["state"] == "pre") & (d["t"] < d["start"])].sort_values("t")
    if not len(pre):
        return pd.DataFrame()
    g = pre.groupby(["league", "espn_id"])
    first, last = g.head(1).set_index(["league", "espn_id"]), g.tail(1).set_index(["league", "espn_id"])
    out = pd.DataFrame({
        "home": first["home"], "away": first["away"], "start": last["start"], "first_seen": first["t"],
        **{f"ml_open_{s}": first[f"ml_open_{s}"] for s in ("home", "away", "draw")},
        **{f"ml_first_{s}": first[f"ml_now_{s}"] for s in ("home", "away", "draw")},
        "p_fair_first_home": first["p_fair_home"], "spread_first": first["spread"], "total_first": first["total"],
        "last_seen": last["t"], **{f"ml_last_{s}": last[f"ml_now_{s}"] for s in ("home", "away", "draw")},
        "p_fair_last_home": last["p_fair_home"], "n_seen": g.size(),
    }).reset_index()
    out["lead_first_seen_h"] = (out["start"] - out["first_seen"]).dt.total_seconds() / 3600
    return out


def capture_kalshi_first(pattern: str = r"^kalshi:KX[A-Z0-9]*(GAME|MATCH)-", root: Path | None = None) -> pd.DataFrame:
    """
    The capture's Kalshi books (`books/venue=kalshi`, from 2 Oct 2026; every listed contract at least hourly at
    level 1, tier 1/2 contracts every 1-15 minutes in depth) reduced to each matching contract's first two-sided
    snapshot: contract_id, ticker, event, first_ts, bid, ask, last_ts, n_snapshots. A game's listing quote then is
    the first time all its contracts are two-sided (as `EventQuotes` does on candles).
    """
    import duckdb
    root = Path(root or _fund_root())
    src = (root / "books" / "venue=kalshi" / "date=*" / "*.parquet").as_posix()
    con = duckdb.connect()
    con.execute("SET threads=2")
    d = con.execute(f"""
        WITH b AS (SELECT contract_id, epoch(ts) t,
                          max(CASE WHEN side = 'bid' AND level = 1 THEN price END) bid,
                          max(CASE WHEN side = 'ask' AND level = 1 THEN price END) ask
                   FROM read_parquet('{src}', hive_partitioning=true)
                   WHERE regexp_matches(contract_id, '{pattern}')
                   GROUP BY contract_id, ts),
             f AS (SELECT contract_id, min(t) FILTER (WHERE bid > 0 AND ask < 1 AND bid <= ask) first_t,
                          max(t) last_t, count(*) n FROM b GROUP BY contract_id)
        SELECT f.contract_id, f.first_t, b.bid, b.ask, f.last_t, f.n FROM f
        LEFT JOIN b ON b.contract_id = f.contract_id AND b.t = f.first_t""").fetchdf()
    if not len(d):
        return d
    d["ticker"] = d["contract_id"].str.replace("kalshi:", "", regex=False)
    d["event"] = d["ticker"].str.rsplit("-", n=1).str[0]
    for c in ("first_t", "last_t"):
        d[c.replace("_t", "_ts")] = pd.to_datetime(d[c], unit="s", utc=True)
    return d.drop(columns=["first_t", "last_t"]).rename(columns={"n": "n_snapshots"})
