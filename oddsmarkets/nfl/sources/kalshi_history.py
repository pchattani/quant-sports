"""
Kalshi NFL market history (market metadata + hourly candlesticks), fetched politely and cached on disk, for the NFL
betting-edge backtest. CLI: scripts/nfl_edge_kalshi.py.

Endpoints (public, no credentials; base https://api.elections.kalshi.com/trade-api/v2; surveyed 2026-10-02)

    GET /historical/cutoff
        {"market_settled_ts": "2026-08-03T00:00:00Z", ...}. Markets settled before the cutoff are served ONLY by
        the /historical/* endpoints; markets settled after it (and open ones) only by the live endpoints.
    GET /historical/markets?series_ticker=S&limit=1000&cursor=C          (also event_ticker=E)
        {"markets": [...], "cursor": "..."}; cursor "" (or absent) on the last page. limit 1000 works.
    GET /historical/markets/{ticker}/candlesticks?start_ts=&end_ts=&period_interval=60
        Historical candle schema: {"end_period_ts", "price": {"open","high","low","close","mean","previous"},
        "yes_bid": {...}, "yes_ask": {...}, "volume", "open_interest"} (plain keys, string dollars).
    GET /events?series_ticker=S&status=settled|open|closed&with_nested_markets=true&limit=200&cursor=C
        Lists ALL events of the series, including pre-cutoff ones, but pre-cutoff events come back with no nested
        markets (fetch those with /historical/markets). Markets inside an open event can be individually
        finalized (e.g. a "1+ wins" rung).
    GET /series/{series}/markets/{ticker}/candlesticks?start_ts=&end_ts=&period_interval=60
        Live candle schema: same structure with "_dollars" suffixes ("close_dollars", ...) and "volume_fp",
        "open_interest_fp". `parse_candle` reads both.
    Limits: period_interval is 1, 60 or 1440; a request may span at most 5000 candles (400 "requested time range
    with candlesticks: N, max candlesticks: 5000" otherwise). Ranges are chunked on a fixed epoch grid of
    CHUNK_HOURS so an open market's chunk keys are stable across runs (a closed market is fetched in the fewest
    requests from its open_time). GET /markets/candlesticks (batch, <=100 tickers, <=10000
    candles) exists but answered 429 to every unauthenticated call, so it is not used. Unauthenticated reads get
    sporadic 429s even at ~3 req/s (the IP is shared with the site refreshers), hence retry with back-off.
    The User-Agent is football/sources/prediction_markets.py HEADERS.

What exists (NFL)
    KXNFLGAME    game winner, event KXNFLGAME-25NOV03ARIDAL (US-Eastern date, away code then home code), one
                 market per team (ticker suffix = team code). First listed for the 2025 preseason (Hall of Fame
                 game 2025-07-31, opened 2025-05-20); no 2024-season game markets exist (no older NFL game series
                 either: the full /series list has no non-KX NFL series). The Super Bowl has no KXNFLGAME event:
                 its winner market is the season-long KXSB event (KXSB-25 = 2024 season, KXSB-26 = 2025, KXSB-27 =
                 2026), kept here as kind "champion" (game_id set for the two finalists' markets).
                 Likewise the 2025-season conference championship games (2026-01-25) have only a zero-volume
                 KXNFLGAME placeholder (KXNFLGAME-26JAN25LASEA; the AFC game has none): the traded winner markets
                 are KXNFLAFCCHAMP / KXNFLNFCCHAMP (events -25 = 2025 season, -27 = 2026; kind "conference",
                 game_id set for the two CON teams' markets).
                 KXNFLGAME also has zero-volume duplicate events on a wrong date (KXNFLGAME-26JAN17SFSEA beside
                 the traded -26JAN18SFSEA); both map to the same game_id, and `primary` marks the most-traded event
                 per (series, game_id).
    KXNFLSPREAD  "<Team> wins by over X points" ladder per team, floor_strike X (strike_type greater).
    KXNFLTOTAL   "Over X points scored" ladder, floor_strike X. Both first listed 2025-08-19 (no preseason).
    KXNFLWINS    2026 season: series KXNFLWINS, event KXNFLWINS-27<TEAM>, "N+ wins" (floor_strike N).
                 2025 season: one series per team KXNFLWINS-<TEAM>, events KXNFLWINS-<TEAM>-25 and -25B,
                 "Over N.5 wins" (ticker -T<N>).
    KXNFLPLAYOFF event -26 = 2025 season, -27 = 2026 season; per-team yes/no.
    KXNFL{AFC,NFC}{EAST,NORTH,SOUTH,WEST}  division winners; event -25 = 2025 season (!), -27 = 2026 season.
    Season is therefore never read from the suffix: games use the kickoff date, futures the expected expiration
    (NFL season = year if month >= 3 else year - 1).
    Kalshi team codes: nflverse's except JAC (JAX) and LAR (LA); early-2026 tickers used LA.

Kickoff: nflverse gameday + gametime (US Eastern) when the event maps to a schedule row; otherwise the market's
expected_expiration_time - 3 h (Kalshi sets expected expiration = kickoff + 3 h; occurrence_datetime, when present,
equals the expected expiration, not kickoff).

Cache: data/nfl/cache/edge/kalshi/<group>/<key>.json.gz, one file per request. Every request is served from the
cache when present, so a rerun makes zero requests; `refresh_live=True` refetches live listings and candle chunks
that were incomplete when fetched (market still open).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import requests as _rq

logger = logging.getLogger(__name__)

BASE = "https://api.elections.kalshi.com/trade-api/v2"
HEADERS = {"User-Agent": "Mozilla/5.0 (The Quant Footballer; +https://pchattani.github.io/the-quant-footballer/)"}
ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "nfl" / "cache" / "edge" / "kalshi"
GAMES_PARQUET = ROOT / "data" / "nfl" / "raw" / "schedules" / "games.parquet"

MIN_GAP = 0.3            # seconds between requests (>= 0.25 required)
MAX_GAP = 4.0            # adaptive gap ceiling under 429s
PERIOD = 60              # hourly candles
CHUNK_HOURS = 4800       # < 5000-candle cap per request
KICKOFF_FROM_EXPIRY = timedelta(hours=3)

GAME_SERIES = {"KXNFLGAME": "game", "KXNFLSPREAD": "spread", "KXNFLTOTAL": "total"}
DIVISION_SERIES = [f"KXNFL{c}{d}" for c in ("AFC", "NFC") for d in ("EAST", "NORTH", "SOUTH", "WEST")]
KALSHI_CODES = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAC",
                "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN",
                "WAS"]
FUTURE_SERIES = (["KXNFLWINS"] + [f"KXNFLWINS-{c}" for c in KALSHI_CODES] + ["KXNFLPLAYOFF"] + DIVISION_SERIES
                 + ["KXNFLAFCCHAMP", "KXNFLNFCCHAMP", "KXSB"])
NFLVERSE = {"ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX",
            "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN",
            "WAS"}
CODE_ALIASES = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}
MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                          "DEC"))}


def series_kind(series: str) -> str | None:
    if series in GAME_SERIES:
        return GAME_SERIES[series]
    if series == "KXNFLWINS" or series.startswith("KXNFLWINS-"):
        return "wins"
    if series == "KXNFLPLAYOFF":
        return "playoff"
    if series in DIVISION_SERIES:
        return "division"
    if series == "KXSB":
        return "champion"
    if series in ("KXNFLAFCCHAMP", "KXNFLNFCCHAMP"):
        return "conference"
    return None


def nfl_code(code: str | None) -> str | None:
    if not code:
        return None
    c = CODE_ALIASES.get(code.upper(), code.upper())
    return c if c in NFLVERSE else None


def nfl_season(d: datetime | None) -> int | None:
    if d is None:
        return None
    return d.year if d.month >= 3 else d.year - 1


def ts(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def num(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


# ── HTTP + cache ─────────────────────────────────────────────────────────────

class Offline(RuntimeError):
    """A request was needed but the fetcher is offline and the cache misses it."""


@dataclass
class Fetcher:
    cache: Path = CACHE
    offline: bool = False
    refresh_live: bool = False
    min_gap: float = MIN_GAP
    max_tries: int = 15
    gap: float = MIN_GAP
    requests: int = 0
    hits: int = 0
    retries: int = 0
    failures: int = 0
    _last: float = 0.0
    session: _rq.Session = field(default_factory=_rq.Session)

    def key_path(self, group: str, path: str, params: dict) -> Path:
        raw = path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        name = re.sub(r"[^A-Za-z0-9_.=-]+", "_", raw.strip("/"))
        if len(name) > 150:
            name = name[:110] + "_" + hashlib.sha1(raw.encode()).hexdigest()[:16]
        return self.cache / group / f"{name}.json.gz"

    @staticmethod
    def read(p: Path) -> dict | None:
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def get(self, group: str, path: str, params: dict, *, live: bool = False,
            stale: callable = None) -> dict | None:
        """Cached GET. `live` listings refetch under refresh_live; `stale(cached)` -> True forces a refetch."""
        p = self.key_path(group, path, params)
        if p.exists():
            env = self.read(p)
            if env is not None:
                refetch = (not self.offline and self.refresh_live
                           and (live or (stale is not None and stale(env))))
                if not refetch:
                    self.hits += 1
                    return env.get("body")
        if self.offline:
            raise Offline(f"cache miss offline: {p.name}")
        body, status = self._http(path, params)
        if body is None:
            return None
        env = {"url": BASE + path, "params": params, "status": status,
               "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "body": body}
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(env, f, separators=(",", ":"))
        tmp.replace(p)
        return body

    def _http(self, path: str, params: dict) -> tuple[dict | None, int]:
        """One logical GET: serial, >= min_gap apart. On 429/5xx the gap widens (x1.5, cap MAX_GAP) and the
        call sleeps with exponential back-off (2 s doubling, cap 30 s, or Retry-After); each success narrows
        the gap back towards min_gap. The Kalshi IP budget is shared with the other site fetchers."""
        delay = 2.0
        for attempt in range(self.max_tries):
            wait = self._last + max(self.min_gap, self.gap) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                r = self.session.get(BASE + path, params=params, headers=HEADERS, timeout=60)
            except _rq.RequestException as exc:
                logger.info("kalshi %s: %s (attempt %d)", path, exc, attempt + 1)
                r = None
            if r is not None and r.status_code == 200:
                self.gap = max(self.min_gap, self.gap * 0.97)
                try:
                    return r.json(), 200
                except ValueError:
                    logger.warning("kalshi %s: non-JSON 200", path)
                    self.failures += 1
                    return None, 200
            if r is not None and r.status_code != 429 and r.status_code < 500:
                logger.warning("kalshi %s %s -> %s %s", path, params, r.status_code, r.text[:200])
                self.failures += 1
                return None, r.status_code
            self.retries += 1
            self.gap = min(MAX_GAP, max(self.min_gap, self.gap) * 1.5)
            ra = num(r.headers.get("Retry-After")) if r is not None else None
            time.sleep(min(30.0, ra if ra else delay))
            delay = min(30.0, delay * 2)
        logger.warning("kalshi %s %s: gave up after %d tries", path, params, self.max_tries)
        self.failures += 1
        return None, 0

    def pages(self, group: str, path: str, params: dict, key: str, *, live: bool = False) -> Iterator[dict]:
        cursor = None
        for _ in range(500):
            q = dict(params)
            if cursor:
                q["cursor"] = cursor
            body = self.get(group, path, q, live=live)
            if not body:
                return
            items = body.get(key) or []
            yield from items
            cursor = body.get("cursor")
            if not cursor or not items:
                return


# ── listings ─────────────────────────────────────────────────────────────────

def historical_markets(f: Fetcher, series: str) -> list[dict]:
    return list(f.pages("lists", "/historical/markets", {"series_ticker": series, "limit": 1000}, "markets"))


def live_markets(f: Fetcher, series: str, statuses: tuple[str, ...]) -> list[dict]:
    out = []
    for st in statuses:
        params = {"series_ticker": series, "status": st, "with_nested_markets": "true", "limit": 200}
        for ev in f.pages("lists", "/events", params, "events", live=(st != "settled")):
            for m in ev.get("markets") or []:
                m = dict(m)
                m.setdefault("event_ticker", ev.get("event_ticker"))
                m["_event_title"] = ev.get("title")
                m["_event_sub_title"] = ev.get("sub_title")
                out.append(m)
    return out


def list_series(f: Fetcher, series: str, statuses: tuple[str, ...]) -> list[dict]:
    """All markets of a series: historical (pre-cutoff) plus live (post-cutoff), deduped by ticker (live wins)."""
    by: dict[str, dict] = {}
    for m in historical_markets(f, series):
        m = dict(m)
        m["_source"] = "historical"
        by[m["ticker"]] = m
    for m in live_markets(f, series, statuses):
        m["_source"] = "live"
        by[m["ticker"]] = m
    for m in by.values():
        m["_series"] = series
    return list(by.values())


# ── candles ──────────────────────────────────────────────────────────────────

def candle_path(m: dict) -> str:
    t = m["ticker"]
    if m.get("_source") == "historical":
        return f"/historical/markets/{t}/candlesticks"
    series = m.get("_series") or m["event_ticker"].split("-")[0]
    return f"/series/{series}/markets/{t}/candlesticks"


def chunks(start: datetime, end: datetime, period: int = PERIOD, cell_hours: int = CHUNK_HOURS) -> list[tuple[int, int, int]]:
    """[(cell, start_ts, end_ts)] covering [start, end] on a fixed epoch grid (stable cache keys)."""
    step = period * 60
    cell = cell_hours * 3600
    s = int(start.timestamp()) // step * step
    e = -(-int(end.timestamp()) // step) * step
    out = []
    for c in range(s // cell, e // cell + 1):
        a, b = max(s, c * cell), min(e, (c + 1) * cell - step)
        if a <= b:
            out.append((c, a, b))
    return out


def compact_chunks(start: datetime, end: datetime, period: int = PERIOD,
                   max_candles: int = CHUNK_HOURS) -> list[tuple[int, int]]:
    """[(start_ts, end_ts)] covering a closed range in as few <= max_candles requests as possible."""
    step = period * 60
    s = int(start.timestamp()) // step * step
    e = -(-int(end.timestamp()) // step) * step
    out = []
    while s <= e:
        b = min(e, s + (max_candles - 1) * step)
        out.append((s, b))
        s = b + step
    return out


class FetchFailed(RuntimeError):
    """The API refused or kept rate-limiting a candle request; nothing was cached, a rerun retries it."""


def fetch_candles(f: Fetcher, m: dict, now: datetime | None = None) -> list[dict]:
    """Raw candle dicts over the market's life (open_time .. close_time + 1 h, capped at now).

    A closed market's range is fixed, so it is fetched in the fewest <= CHUNK_HOURS requests from open_time (keys
    are the exact params). An open market is chunked on the epoch grid (`chunks`) and its last, still-growing chunk
    is keyed by grid cell, refetched only under refresh_live."""
    now = now or datetime.now(timezone.utc)
    o, c = ts(m.get("open_time")), ts(m.get("close_time"))
    if o is None or c is None:
        return []
    end = min(c + timedelta(hours=1), now)
    if end <= o:
        return []
    path = candle_path(m)
    now_ts = int(now.timestamp())
    closed = c + timedelta(hours=2) <= now
    grid = chunks(o, end)
    out: list[dict] = []
    if closed:
        legacy = [f.key_path("candles", path, {"start_ts": a, "end_ts": b, "period_interval": PERIOD})
                  for _, a, b in grid]
        if all(p.exists() for p in legacy):
            spans = [(a, b) for _, a, b in grid]
        else:
            spans = compact_chunks(o, end)
        for a, b in spans:
            body = f.get("candles", path, {"start_ts": a, "end_ts": b, "period_interval": PERIOD})
            if body is None:
                raise FetchFailed(f"{m['ticker']} {a}-{b}")
            out.extend(body.get("candlesticks") or [])
        return out
    for cell, a, b in grid:
        complete = b < now_ts - 3600
        params = {"start_ts": a, "end_ts": b, "period_interval": PERIOD}
        if complete:
            body = f.get("candles", path, params)
        else:
            p = f.key_path("candles", path, {"cell": cell, "period_interval": PERIOD, "open": 1})
            env = f.read(p) if p.exists() else None
            if env is not None and not (f.refresh_live and not f.offline):
                f.hits += 1
                body = env.get("body")
            else:
                if f.offline:
                    raise Offline(f"cache miss offline: {p.name}")
                body, status = f._http(path, params)
                if body is not None:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with gzip.open(p, "wt", encoding="utf-8") as fh:
                        json.dump({"url": BASE + path, "params": params, "status": status,
                                   "fetched_at": now.isoformat(timespec="seconds"), "body": body}, fh,
                                  separators=(",", ":"))
        if body is None:
            raise FetchFailed(f"{m['ticker']} {a}-{b}")
        out.extend(body.get("candlesticks") or [])
    return out


def _px(d: dict | None, k: str) -> float | None:
    if not d:
        return None
    return num(d.get(f"{k}_dollars", d.get(k)))


CANDLE_COLUMNS = ["ticker", "ts", "yes_bid_open", "yes_bid_high", "yes_bid_low", "yes_bid_close", "yes_ask_open",
                  "yes_ask_high", "yes_ask_low", "yes_ask_close", "price_open", "price_high", "price_low",
                  "price_close", "price_mean", "price_previous", "volume", "open_interest"]


def parse_candle(ticker: str, c: dict) -> dict:
    """One candle (live `_dollars`/`_fp` schema or historical plain schema) -> flat row; prices in dollars (0-1)."""
    row: dict[str, Any] = {"ticker": ticker,
                           "ts": datetime.fromtimestamp(int(c["end_period_ts"]), tz=timezone.utc)}
    for side in ("yes_bid", "yes_ask"):
        for k in ("open", "high", "low", "close"):
            row[f"{side}_{k}"] = _px(c.get(side), k)
    for k in ("open", "high", "low", "close", "mean", "previous"):
        row[f"price_{k}"] = _px(c.get("price"), k)
    row["volume"] = num(c.get("volume_fp", c.get("volume")))
    row["open_interest"] = num(c.get("open_interest_fp", c.get("open_interest")))
    return row


def parse_candles(ticker: str, candles: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in candles:
        t = c.get("end_period_ts")
        if t is None or t in seen:
            continue
        seen.add(t)
        out.append(parse_candle(ticker, c))
    out.sort(key=lambda r: r["ts"])
    return out


# ── market rows ──────────────────────────────────────────────────────────────

EVENT_RE = re.compile(r"^(KXNFLGAME|KXNFLSPREAD|KXNFLTOTAL)-(\d\d)([A-Z]{3})(\d\d)([A-Z]+)$")


def parse_game_event(event_ticker: str) -> tuple[datetime, list[tuple[str, str]]] | None:
    """KXNFLGAME-25NOV03ARIDAL -> (date 2025-11-03, [(away, home) nflverse code splits that are valid])."""
    m = EVENT_RE.match(event_ticker or "")
    if not m or m.group(3) not in MONTHS:
        return None
    d = datetime(2000 + int(m.group(2)), MONTHS[m.group(3)], int(m.group(4)), tzinfo=timezone.utc)
    codes = m.group(5)
    splits = []
    for i in range(2, len(codes) - 1):
        a, h = nfl_code(codes[:i]), nfl_code(codes[i:])
        if a and h and a != h:
            splits.append((a, h))
    return d, splits


def yes_team(m: dict, kind: str) -> str | None:
    t, ev = m["ticker"], m.get("event_ticker") or ""
    suffix = t[len(ev) + 1:] if t.startswith(ev + "-") else t.rsplit("-", 1)[-1]
    if kind == "game":
        return nfl_code(suffix)
    if kind == "spread":
        return nfl_code(re.sub(r"\d+$", "", suffix))
    if kind in ("playoff", "division", "champion", "conference"):
        return nfl_code(suffix)
    if kind == "wins":
        s = m.get("_series", "")
        if s.startswith("KXNFLWINS-"):
            return nfl_code(s.split("-", 1)[1])
        mm = re.match(r"KXNFLWINS-\d\d([A-Z]+)$", ev)
        return nfl_code(mm.group(1)) if mm else None
    return None


def line_and_note(m: dict, kind: str, team: str | None) -> tuple[float | None, str]:
    """`line` such that YES iff stat > line (stat: margin, total points, wins), plus a readable note."""
    fs = num(m.get("floor_strike"))
    sub = str(m.get("yes_sub_title") or "")
    if kind == "game":
        return None, f"YES iff {team} wins (tie settles 0.50)"
    if kind == "spread":
        return fs, f"YES iff {team} wins by more than {fs} points (margin = {team} score - opponent score)"
    if kind == "total":
        return fs, f"YES iff combined points > {fs}"
    if kind == "wins":
        mo = re.search(r"Over (\d+(?:\.\d+)?) wins", sub, re.I)
        mp = re.search(r"(\d+)\+ wins", sub)
        if mo:
            line = float(mo.group(1))
        elif mp:
            line = int(mp.group(1)) - 0.5
        else:
            line = fs
        return line, f"YES iff {team} regular-season wins > {line} (sub-title '{sub}')"
    if kind == "playoff":
        return None, f"YES iff {team} makes the playoffs"
    if kind == "division":
        return None, f"YES iff {team} wins the division"
    if kind == "conference":
        return None, f"YES iff {team} wins the conference (the conference championship game)"
    if kind == "champion":
        return None, f"YES iff {team} wins the Super Bowl"
    return fs, ""


def load_schedule(path: Path = GAMES_PARQUET):
    import pandas as pd
    g = pd.read_parquet(path, columns=["game_id", "season", "game_type", "week", "gameday", "gametime",
                                       "away_team", "home_team"])
    g = g[g.season >= 2024].copy()
    ko = pd.to_datetime(g.gameday + " " + g.gametime.fillna("13:00"), errors="coerce")
    g["kickoff_utc"] = ko.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    return g


class GameIndex:
    def __init__(self, sched):
        self.by: dict[tuple, dict] = {}
        self.sb: dict[int, dict] = {}
        self.con: dict[tuple[int, str], dict] = {}
        for r in sched.to_dict("records"):
            rec = {k: r[k] for k in ("game_id", "season", "game_type", "week", "away_team", "home_team")}
            rec["kickoff_utc"] = r["kickoff_utc"].to_pydatetime() if r["kickoff_utc"] is not None and str(r["kickoff_utc"]) != "NaT" else None
            self.by[(r["gameday"], r["away_team"], r["home_team"])] = rec
            if r["game_type"] == "SB":
                self.sb[int(r["season"])] = rec
            if r["game_type"] == "CON":
                self.con[(int(r["season"]), r["away_team"])] = rec
                self.con[(int(r["season"]), r["home_team"])] = rec

    def match(self, d: datetime, splits: list[tuple[str, str]]) -> tuple[dict | None, str]:
        for delta, how in ((0, "exact"), (-1, "date-1"), (1, "date+1")):
            day = (d + timedelta(days=delta)).strftime("%Y-%m-%d")
            for a, h in splits:
                if (day, a, h) in self.by:
                    return self.by[(day, a, h)], how
            for a, h in splits:
                if (day, h, a) in self.by:
                    return self.by[(day, h, a)], how + ",swapped"
        return None, ""


MARKET_COLUMNS = ["series", "event_ticker", "ticker", "kind", "season", "game_id", "game_type", "week", "away_team",
                  "home_team", "team", "floor_strike", "strike_type", "line", "strike_note", "open_time", "close_time",
                  "kickoff_utc", "kickoff_source", "expected_expiration_time", "settlement_ts", "status", "result",
                  "settlement_value", "volume", "open_interest", "last_price", "title", "yes_sub_title",
                  "event_title", "source", "map_note"]


def market_row(m: dict, gi: GameIndex | None) -> dict:
    series = m.get("_series") or m["event_ticker"].split("-")[0]
    kind = series_kind(series) or ""
    team = yes_team(m, kind)
    line, note = line_and_note(m, kind, team)
    exp = ts(m.get("expected_expiration_time"))
    row: dict[str, Any] = {
        "series": series, "event_ticker": m.get("event_ticker"), "ticker": m["ticker"], "kind": kind,
        "season": None, "game_id": None, "game_type": None, "week": None, "away_team": None, "home_team": None,
        "team": team, "floor_strike": num(m.get("floor_strike")), "strike_type": m.get("strike_type"),
        "line": line, "strike_note": note, "open_time": ts(m.get("open_time")), "close_time": ts(m.get("close_time")),
        "kickoff_utc": None, "kickoff_source": None, "expected_expiration_time": exp,
        "settlement_ts": ts(m.get("settlement_ts")), "status": m.get("status"), "result": m.get("result") or None,
        "settlement_value": num(m.get("settlement_value_dollars", m.get("settlement_value"))),
        "volume": num(m.get("volume_fp", m.get("volume"))), "open_interest": num(m.get("open_interest_fp", m.get("open_interest"))),
        "last_price": num(m.get("last_price_dollars", m.get("last_price"))), "title": m.get("title"),
        "yes_sub_title": m.get("yes_sub_title"), "event_title": m.get("_event_title"), "source": m.get("_source"),
        "map_note": None,
    }
    if row["settlement_value"] is None and row["result"] in ("yes", "no"):
        row["settlement_value"] = 1.0 if row["result"] == "yes" else 0.0
    if kind in ("game", "spread", "total"):
        ko_fallback = exp - KICKOFF_FROM_EXPIRY if exp else None
        pe = parse_game_event(m.get("event_ticker") or "")
        g, how = (gi.match(pe[0], pe[1]) if (gi and pe) else (None, ""))
        if g:
            row.update(game_id=g["game_id"], season=int(g["season"]), game_type=g["game_type"], week=int(g["week"]),
                       away_team=g["away_team"], home_team=g["home_team"], map_note=how)
            row["kickoff_utc"], row["kickoff_source"] = (g["kickoff_utc"], "nflverse") if g["kickoff_utc"] else (ko_fallback, "kalshi_expiry-3h")
        else:
            if pe and pe[1]:
                row["away_team"], row["home_team"] = pe[1][0]
            ref = ko_fallback or (pe[0] if pe else None)
            row["season"] = nfl_season(ref)
            row["kickoff_utc"], row["kickoff_source"] = ko_fallback, "kalshi_expiry-3h"
            pre = ref is not None and ref.month in (7, 8)
            row["map_note"] = "unmapped:preseason" if pre else "unmapped"
            row["game_type"] = "PRE" if pre else None
    else:
        row["season"] = nfl_season(exp or row["close_time"])
        g = None
        if gi is not None and team and row["season"] is not None:
            if kind == "champion":
                g = gi.sb.get(row["season"])
            elif kind == "conference":
                g = gi.con.get((row["season"], team))
        if g and team in (g["away_team"], g["home_team"]):
            row.update(game_id=g["game_id"], game_type=g["game_type"], week=int(g["week"]), away_team=g["away_team"],
                       home_team=g["home_team"], kickoff_utc=g["kickoff_utc"], kickoff_source="nflverse",
                       map_note=f"{g['game_type']} finalist")
    return row
