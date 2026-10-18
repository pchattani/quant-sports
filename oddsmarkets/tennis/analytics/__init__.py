"""
The Quant Ace analytics layer (builder D): player catalogues and careers, tournament pages, the match
centre, rankings and the race, the lab, markets, history, the index and the glossary, all read from the
season stores (`oddsmarkets.tennis.store`), the registry and style tables (builder A) and the models
(builders B and C), and written by `scripts/build_ace.py` as the payloads in `oddsmarkets/tennis/PAYLOADS.md`.

Roots
-----
Stores in and payloads out live under one data root, `docs/ace/data` unless ACE_DATA points elsewhere
(tests build into a temporary folder); model caches under ACE_CACHE (default data/tennis/cache).
`set_data_root` / `set_cache_root` set the variables, so every model module (which reads them on each
call) follows.

Conventions
-----------
* Tours "atp" / "wta"; player ids and event ids per CONTRACT.md.
* Numbers are rounded at the payload boundary: probabilities 4 dp, ratings 1 dp, rates 3 dp; fractions
  (fmt "pct", "prob") are 0-1.
* Nothing here raises on missing data: a metric that cannot be computed is None.

`TourData` is the shared, memoised view of one tour the build passes around: stores per year (with the
registry's id redirects applied), player info, the Elo history and its per-match index, serve/return fits
per season end and per month (cached under ACE_CACHE, keyed on the matches they saw, so a new result in
the current season does not refit past seasons), and prediction contexts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from oddsmarkets.common.edge import devig as _dv

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
TOURS = ("atp", "wta")
TOUR_NAMES = {"atp": "ATP Tour", "wta": "WTA Tour"}
TOUR_LEVELS = ("slam", "finals", "m1000", "500", "250", "other")
POINT_LEVELS = ("slam", "finals", "m1000", "500", "250")
SURFACES = ("hard", "clay", "grass")
FINISHED = ("done", "ret", "wo", "def")
PLAYED = ("done", "ret", "def")                # walkovers are not played
MAIN_ROUNDS = ("R128", "R64", "R32", "R16", "RR", "QF", "SF", "BR", "F")
ROUND_ORDER = {"Q1": 0, "Q2": 1, "Q3": 2, "R128": 3, "R64": 4, "R32": 5, "R16": 6, "RR": 7, "QF": 8, "SF": 9, "BR": 10, "F": 11}
FIRST_YEAR = {"atp": 2000, "wta": 2007}


# ---------------------------------------------------------------------------------------------- roots

def set_data_root(path: str | Path | None) -> Path:
    if path:
        os.environ["ACE_DATA"] = str(Path(path))
    else:
        os.environ.pop("ACE_DATA", None)
    _clear()
    return data_root()


def set_cache_root(path: str | Path | None) -> None:
    if path:
        os.environ["ACE_CACHE"] = str(Path(path))
    _clear()


def _clear() -> None:
    try:
        from oddsmarkets.tennis.models import predict as _pr
        _pr._CTX.clear()
    except Exception:                                            # pragma: no cover - defensive
        pass


def data_root() -> Path:
    return Path(os.environ.get("ACE_DATA") or (ROOT / "docs" / "ace" / "data"))


def cache_root() -> Path:
    return Path(os.environ.get("ACE_CACHE") or (ROOT / "data" / "tennis" / "cache"))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def years_on_disk(tour: str) -> list[int]:
    d = data_root() / tour
    try:
        return sorted(int(p.name) for p in d.iterdir() if p.is_dir() and p.name.isdigit() and (p / "store.json").exists())
    except OSError:
        return []


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def fname(id_: Any) -> str:
    """File-safe form of a player or match id for players/<id>.json and matches/<id>.json: ':' -> '_' (pids
    "x:<slug>" would otherwise name an NTFS alternate data stream on Windows; slugs never contain '_')."""
    return str(id_).replace(":", "_")


def digest(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, default=str, separators=(",", ":")).encode())
        h.update(b"|")
    return h.hexdigest()[:20]


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


def prob(v: Any) -> float | None:
    return rnd(v, 4)


def div(num: Any, den: Any) -> float | None:
    n, d = fnum(num), fnum(den)
    if n is None or not d:
        return None
    return n / d


def mean(xs: Iterable[Any]) -> float | None:
    v = [x for x in (fnum(x) for x in xs) if x is not None]
    return sum(v) / len(v) if v else None


def day(d: Any) -> date | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


# Plausible dates of birth. ESPN's core athlete API reuses old ids: some early-2000s players get the date of birth
# of a different, younger person (Andrei Pavel "born 2004", ages of -3 in his own seasons), and some current players
# share their id with an early-2000s namesake's matches (Casper Ruud's id carries matches from 2000). So a date is
# kept when it is a real date from DOB_MIN_YEAR on, not in the future, and puts the player between TYPICAL_MIN and
# TYPICAL_MAX at the median date of their latest run of matches on disk (no gap over CAREER_GAP days, so a reused
# id's older namesake does not count; TourData.spans) and at least START_MIN at that run's first match; otherwise
# it is treated as missing (scripts/tn_bio.py stores null, TourData.players drops it). An age at a date more than
# 180 days before that latest run, or outside AGE_MIN..AGE_MAX, is shown as unknown (age_at, TourData.dob_from).
DOB_MIN_YEAR = 1940
AGE_MIN, AGE_MAX = 12.0, 60.0
TYPICAL_MIN, TYPICAL_MAX = 15.0, 50.0
START_MIN = 13.0
CAREER_GAP = 730


def years_between(a: date, b: date) -> float:
    return (b - a).days / 365.25


def age_at(dob: Any, when: Any, since: Any = None) -> float | None:
    """Age in years at `when`, None when unknown, outside AGE_MIN..AGE_MAX or before `since` (TourData.dob_from)."""
    d, w = day(dob), day(when)
    if d is None or w is None:
        return None
    s = day(since)
    if s is not None and w < s - timedelta(days=180):
        return None
    a = years_between(d, w)
    return a if AGE_MIN <= a <= AGE_MAX else None


def plausible_dob(dob: Any, typical: Any = None, today: date | None = None, start: Any = None) -> str | None:
    """The ISO date of birth when plausible (see DOB_MIN_YEAR), else None. typical / start: the median and first
    date of the player's latest run of matches (TourData.spans; None: not checked)."""
    d = day(dob) if dob not in (None, "") else None
    if d is None or d.year < DOB_MIN_YEAR or d > (today or today_utc()):
        return None
    t = day(typical)
    if t is not None and not (TYPICAL_MIN <= years_between(d, t) <= TYPICAL_MAX):
        return None
    s = day(start)
    if s is not None and years_between(d, s) < START_MIN:
        return None
    return d.isoformat()


def fmt_value(v: Any, fmt: str) -> Any:
    """Round a metric value for its format (int, 1, 2, 3, pct = fraction 3 dp, prob 4 dp, signed 2 dp)."""
    x = fnum(v)
    if x is None:
        return None
    if fmt == "int":
        return int(round(x))
    nd = {"1": 1, "2": 2, "3": 3, "pct": 3, "prob": 4, "signed": 2}.get(fmt, 3)
    return round(x, nd)


def devig2(odds: Any) -> float | None:
    """P(first) from a two-way decimal price pair, de-vigged multiplicatively."""
    try:
        a, b = float(odds[0]), float(odds[1])
    except (TypeError, ValueError, IndexError):
        return None
    if a <= 1.0 or b <= 1.0:
        return None
    return _dv.multiplicative_pair(a, b)[0]          # common/edge/devig.py


# ---------------------------------------------------------------------------------------------- percentiles

def percentiles(values: dict[str, Any], lower: bool = False) -> dict[str, int]:
    """Field percentile of each value, 100 = best, direction-aware:
        pct_i = 100 * (W_i + 0.5 * T_i) / (n - 1)
    W_i = other entries strictly worse than i (smaller when higher is better, larger when `lower`),
    T_i = other entries tied with i. A lone entry gets 50; None values are skipped."""
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


def place(sorted_vals: list[float], v: float, lower: bool) -> int:
    """Percentile (0-100, 100 = best) of v against a sorted reference distribution."""
    n = len(sorted_vals)
    lo, hi = bisect_left(sorted_vals, v), bisect_right(sorted_vals, v)
    below, above, ties = lo, n - hi, hi - lo
    r = (below + 0.5 * ties) / n if not lower else (above + 0.5 * ties) / n
    return int(round(100 * r))


def rank_in(sorted_vals: list[float], v: float, lower: bool) -> int:
    """Competition rank (1 = best) of v in a sorted reference distribution."""
    return 1 + (bisect_left(sorted_vals, v) if lower else len(sorted_vals) - bisect_right(sorted_vals, v))


def shrink(v: float | None, n: float | None, prior: float | None, k: float) -> float | None:
    """(v n + prior k) / (n + k): a rate pulled towards the pool mean by k pseudo-observations."""
    if v is None or prior is None or not k:
        return v
    n = float(n or 0)
    return (v * n + prior * k) / (n + k)


def metric(key: str, label: str, group: str, fmt: str, lower: bool = False, scope: str = "all", desc: str = "") -> dict:
    """METRIC = {"key","label","group","fmt","lower","scope","desc"} (PAYLOADS.md)."""
    return {"key": key, "label": label, "group": group, "fmt": fmt, "lower": bool(lower), "scope": scope, "desc": desc}


# ---------------------------------------------------------------------------------------------- match helpers

def is_tour_level(m: dict) -> bool:
    return str(m.get("level")) in TOUR_LEVELS and str(m.get("round") or "") not in ("Q1", "Q2", "Q3")


def chain_rule(m: dict) -> str:
    """The deciding-set rule in match_chain's vocabulary ("tb12" for a tiebreak at 12-12)."""
    r = str(m.get("final_set_rule") or "tb7")
    if r == "tb7" and int(m.get("final_set_tb_at") or 6) == 12:
        return "tb12"
    return r if r in ("tb7", "tb10", "adv", "tb12") else "tb7"


def set_pairs(m: dict) -> list[tuple[int, int]]:
    out = []
    for s in m.get("sets") or []:
        try:
            out.append((int(s[0]), int(s[1])))
        except (TypeError, ValueError, IndexError):
            break
    return out


def score_text(m: dict, flip: bool = False) -> str:
    """'6-4 7-6(5)' from p1's view (from p2's when flip); 'ret.' / 'w/o' appended."""
    if m.get("status") == "wo":
        return "w/o"
    parts = []
    for s in m.get("sets") or []:
        try:
            a, b = int(s[0]), int(s[1])
        except (TypeError, ValueError, IndexError):
            continue
        ta = s[2] if len(s) > 2 else None
        tb = s[3] if len(s) > 3 else None
        if flip:
            a, b, ta, tb = b, a, tb, ta
        t = f"{a}-{b}"
        if ta is not None and tb is not None and max(a, b) >= 7 and min(a, b) >= 6:
            t += f"({min(int(ta), int(tb))})"
        parts.append(t)
    txt = " ".join(parts)
    if m.get("status") == "ret":
        txt += " ret."
    elif m.get("status") == "def":
        txt += " def."
    return txt


def winner_side(m: dict) -> int | None:
    w = m.get("winner")
    if w is None:
        return None
    return 0 if str(w) == str(m.get("p1")) else 1


def complete_draw(draw: dict | None, matches: Iterable[dict]) -> int:
    """Fill null first-round slots of a DRAW from the event's later-round matches, in place; returns the
    number of slots filled. The WTA draw endpoint leaves seeded players with a first-round bye (and some
    others) as null slots; a player who first appears in round r beside a known player at slot i belongs in
    the sibling block of i at that round (slots ((i >> r) ^ 1) << r ... + 2^r, 0-based, r = 0 for the first
    round). Within that block she goes to the null slot carrying a seed when there is one, else the first
    null slot; a block that already holds a known player is left alone (no guessing)."""
    if not draw or not draw.get("slots"):
        return 0
    from oddsmarkets.tennis.models import _points
    slots = sorted(draw["slots"], key=lambda x: int(x[0]))
    n = len(slots)
    size = 1
    while size < max(n, int(draw.get("size") or 0), 2):
        size *= 2
    if n != size:
        return 0
    rounds = _points.round_names(size)
    pos = {x[1]: i for i, x in enumerate(slots) if x[1]}
    filled = 0
    ms = [m for m in matches if m.get("round") in rounds and m.get("p1") and m.get("p2")]
    for ri, rnd in enumerate(rounds):
        for m in ms:
            if m.get("round") != rnd:
                continue
            a, b = m["p1"], m["p2"]
            for known, miss in ((a, b), (b, a)):
                if known not in pos or miss in pos:
                    continue
                lo = ((pos[known] >> ri) ^ 1) << ri
                block = range(lo, min(lo + (1 << ri), n))
                if any(slots[j][1] for j in block):
                    continue
                cand = [j for j in block if len(slots[j]) > 2 and slots[j][2]] or list(block)
                if not cand:
                    continue
                slots[cand[0]][1] = miss
                pos[miss] = cand[0]
                filled += 1
    if filled:
        draw["slots"] = slots
        draw["filled_from_results"] = filled
    return filled


# ---------------------------------------------------------------------------------------------- tour data

# Serve/return refit budget for past checkpoints (seconds, env ACE_SR_FIT_BUDGET; unset = no limit). A cold
# model cache in CI would otherwise refit every monthly and season-end checkpoint (about 50 ATP fits of ~20 s
# and 40 WTA fits of ~50 s: well past the build's timeout, so the cache could never warm up). Fits within
# CURRENT_DAYS of today are never budgeted. Shared by both tours of one process.
CURRENT_DAYS = 45
_SR_BUDGET = {"spent": 0.0}


def sr_fit_budget() -> float | None:
    v = os.environ.get("ACE_SR_FIT_BUDGET")
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


class TourData:
    """Memoised view of one tour's stores and model state (see the module docstring)."""

    def __init__(self, tour: str, today: date | None = None):
        from oddsmarkets.tennis import canon
        self.tour = canon.tour_key(tour)
        self.today = today or today_utc()
        self.years = years_on_disk(self.tour)
        try:
            self.registry = canon.Registry.load(self.tour)
        except Exception:                                        # pragma: no cover - defensive
            self.registry = None
        self._stores: dict[int, dict] = {}
        self._players: dict[str, dict] | None = None
        self._spans: dict[str, tuple[str, str, str, str]] | None = None
        self._elo = None
        self._elo_idx: dict[str, tuple] | None = None
        self._elo_at: dict[str, dict] = {}
        self._sr: dict[str, dict] = {}
        self.sr_skipped: set[str] = set()       # past checkpoints left unfitted by the refit budget (cold cache)
        self._ctx: dict[str, Any] = {}
        self._rated: list[dict] | None = None
        self._style = None
        self.current = self.today.year if self.today.year in self.years else (max(self.years) if self.years else self.today.year)

    # stores
    def store(self, year: int) -> dict:
        year = int(year)
        s = self._stores.get(year)
        if s is None:
            from oddsmarkets.tennis import store as st
            try:
                s = st.load(self.tour, year, self.registry)
            except Exception as exc:                             # pragma: no cover - defensive
                logger.warning("%s %s: store unreadable (%s)", self.tour, year, exc)
                s = st.new_store(self.tour, year)
            for eid, ev in (s.get("events") or {}).items():
                ev.setdefault("id", eid)
            by_ev: dict[str, list] = {}
            for mid, m in (s.get("matches") or {}).items():
                m.setdefault("id", mid)
                by_ev.setdefault(m.get("event"), []).append(m)
            for eid, ev in (s.get("events") or {}).items():
                if ev.get("draw") and by_ev.get(eid):
                    try:
                        complete_draw(ev["draw"], by_ev[eid])
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("draw completion %s failed: %s", eid, exc)
            self._stores[year] = s
        return s

    def events(self, year: int) -> dict[str, dict]:
        return self.store(year).get("events") or {}

    def matches(self, year: int) -> dict[str, dict]:
        return self.store(year).get("matches") or {}

    def match_date(self, m: dict, year: int | None = None) -> date | None:
        d = day(m.get("date"))
        if d is None:
            ev = self.events(year or self.current).get(m.get("event")) if year else None
            d = day((ev or {}).get("start"))
        return d

    # players
    @property
    def players(self) -> dict[str, dict]:
        if self._players is None:
            out: dict[str, dict] = {}
            if self.registry is not None:
                for pid, p in (self.registry.players or {}).items():
                    out[pid] = dict(p)
            for y in self.years:
                for pid, p in (self.store(y).get("players") or {}).items():
                    cur = out.setdefault(pid, {})
                    for k, v in p.items():
                        if v not in (None, "", []):
                            cur[k] = v
            # dates of birth from ESPN's athlete API (scripts/tn_bio.py) where neither the registry nor a store has
            # one; every date (whatever its source) must be plausible for the player's match span (plausible_dob)
            spans = self.spans
            for pid, cur in out.items():
                if cur.get("dob"):
                    sp = spans.get(pid) or (None,) * 4
                    cur["dob"] = plausible_dob(cur["dob"], sp[1], self.today, sp[3])
            bio = read_json(data_root() / self.tour / "bio.json") or {}
            redirect = self.registry.canonical if (self.registry is not None and self.registry.redirects) else None
            for pid, rec in bio.items():
                if str(pid).startswith("_") or not isinstance(rec, dict) or not rec.get("dob"):
                    continue
                p = (redirect(pid) or pid) if redirect else pid
                if p in out and not out[p].get("dob"):
                    sp = spans.get(p) or (None,) * 4
                    out[p]["dob"] = plausible_dob(rec["dob"], sp[1], self.today, sp[3])
            self._players = out
        return self._players

    @property
    def spans(self) -> dict[str, tuple[str, str, str, str]]:
        """pid -> (first, typical, last, run start) ISO date of the player's matches on disk (a match without a date takes its
        event's start, so does one dated outside the store's year +-1); typical is the median date of the latest run of matches, which starts at run start. For plausible_dob and age."""
        if self._spans is None:
            out: dict[str, list[str]] = {}
            for y in self.years:
                evs = self.events(y)
                ok = (str(y - 1), str(y), str(y + 1))
                for m in self.matches(y).values():
                    d = str(m.get("date") or "")[:10]
                    if d[:4] not in ok:                 # missing, or a stray date (2007's store has some in 2050)
                        d = str((evs.get(m.get("event")) or {}).get("start") or "")[:10]
                    if len(d) != 10 or d[:4] not in ok:
                        continue
                    for side in ("p1", "p2"):
                        if m.get(side):
                            out.setdefault(str(m[side]), []).append(d)
            spans = {}
            for k, v in out.items():
                v.sort()
                # the latest unbroken run of matches (no gap over CAREER_GAP days): a reused id's older namesake
                # stays out of the median
                i = len(v) - 1
                while i > 0 and (date.fromisoformat(v[i]) - date.fromisoformat(v[i - 1])).days <= CAREER_GAP:
                    i -= 1
                run = v[i:]
                spans[k] = (v[0], run[len(run) // 2], v[-1], run[0])
            self._spans = spans
        return self._spans

    def name(self, pid: Any) -> str:
        p = self.players.get(str(pid)) or {}
        return str(p.get("name") or pid)

    def short(self, pid: Any) -> str:
        p = self.players.get(str(pid)) or {}
        return str(p.get("short") or p.get("name") or pid)

    def age(self, pid: str, when: date) -> float | None:
        a = age_at((self.players.get(pid) or {}).get("dob"), when, self.dob_from(pid))
        return round(a, 1) if a is not None else None

    def dob_from(self, pid: str) -> str | None:
        """The first date the player's date of birth applies to: the start of their latest run of matches (an
        older namesake under a reused id gets no age)."""
        sp = self.spans.get(str(pid))
        return sp[3] if sp else None

    # style (charting)
    @property
    def style(self) -> dict:
        if self._style is None:
            s = read_json(data_root() / self.tour / "style.json") or {}
            self._style = {k: v for k, v in s.items() if not str(k).startswith("_")}
            if self.registry is not None and self.registry.redirects:
                self._style = {self.registry.canonical(k) or k: v for k, v in self._style.items()}
        return self._style

    # Elo
    @property
    def elo(self) -> dict:
        """B's Elo over the redirected stores (elo.history(tour) reads the raw stores, where a player
        later linked to an ESPN id can still carry an x:<slug> id). Cached under ACE_CACHE/ace_elo."""
        if self._elo is None:
            from oddsmarkets.tennis.models import _io
            from oddsmarkets.tennis.models import elo as E
            rated = self.rated_matches()
            prm = E.params(self.tour)
            key = digest(E.VERSION, prm, len(rated), hashlib.sha1("".join(
                f"{m['id']}{m.get('p1')}{m.get('p2')}{m.get('status')}{m.get('date')}" for m in rated).encode()).hexdigest())
            self._elo = _io.cached("ace_elo", self.tour, key, lambda: E.history(self.tour, matches=rated))
        return self._elo

    def elo_row(self, mid: str) -> tuple | None:
        """The Elo history row of a rated match (cols per elo.COLS) or None."""
        if self._elo_idx is None:
            self._elo_idx = {str(g[0]): g for g in self.elo.get("rows") or []}
        return self._elo_idx.get(str(mid))

    def elo_pre(self, m: dict) -> float | None:
        """Elo P(m.p1 wins) before the match, None when it was not rated (walkovers)."""
        g = self.elo_row(m.get("id"))
        if g is None:
            return None
        p = fnum(g[12])
        if p is None:
            return None
        return p if str(g[2]) == str(m.get("p1")) else 1.0 - p

    def elo_at(self, when: date) -> dict:
        k = when.isoformat()
        r = self._elo_at.get(k)
        if r is None:
            from oddsmarkets.tennis.models import elo as E
            r = E.ratings_at(self.elo, when)
            self._elo_at[k] = r
        return r

    def elo_params(self) -> dict:
        from oddsmarkets.tennis.models import elo as E
        return self.elo.get("params") or E.params(self.tour)

    # game-share Elo (the blend's third term, models/gelo.py), over the redirected stores like Elo
    @property
    def gelo(self) -> dict:
        if getattr(self, "_gelo", None) is None:
            from oddsmarkets.tennis.models import _io
            from oddsmarkets.tennis.models import gelo as G
            rated = self.rated_matches()
            prm = G.params(self.tour)
            key = digest(G.VERSION, prm, len(rated), hashlib.sha1("".join(
                f"{m['id']}{m.get('p1')}{m.get('p2')}{m.get('status')}{m.get('date')}{m.get('sets')}"
                for m in rated).encode()).hexdigest())
            self._gelo = _io.cached("ace_gelo", self.tour, key, lambda: G.history(self.tour, matches=rated))
        return self._gelo

    def gelo_at(self, when: date) -> dict:
        memo = self.__dict__.setdefault("_gelo_at", {})
        k = when.isoformat()
        if k not in memo:
            from oddsmarkets.tennis.models import gelo as G
            memo[k] = G.ratings_at(self.gelo, when)
        return memo[k]

    # serve/return fits keyed on the matches they saw
    def rated_matches(self) -> list[dict]:
        """Every rated MATCH row (done / ret / def) of the redirected stores, dated (a missing or garbled
        date takes the event's start), sorted as the models sort them."""
        if self._rated is None:
            from oddsmarkets.tennis.models import _io
            out = []
            for y in self.years:
                evs = self.events(y)
                for m in self.matches(y).values():
                    if m.get("status") not in _io.RATED_STATUS or not m.get("p1") or not m.get("p2"):
                        continue
                    d = day(m.get("date"))
                    if d is None or abs(d.year - y) > 1:
                        d = day((evs.get(m.get("event")) or {}).get("start"))
                        if d is None or abs(d.year - y) > 1:
                            continue
                    m2 = m if str(m.get("date") or "")[:10] == d.isoformat() and len(str(m.get("date"))) == 10 \
                        else dict(m, date=d.isoformat())
                    out.append(m2)
            out.sort(key=_io.match_key)
            self._rated = out
        return self._rated

    def sr_fit(self, through: date) -> dict | None:
        """B's serve/return model fitted on matches dated <= `through` (window and constants per tour),
        cached under ACE_CACHE/ace_sr keyed on those matches only.

        Cold cache: a fit within CURRENT_DAYS of today is always made (and, when it fails or nothing can be
        fitted, the committed fit models/fitted/serve_return_<tour>.json stands in). A past checkpoint is
        refitted only while the refit budget (ACE_SR_FIT_BUDGET) lasts; beyond it the checkpoint gets no
        serve/return model this run (never the committed fit, which saw later matches), is listed in
        `sr_skipped`, and the build leaves the pages that used it unsigned so a later, warmer run rebuilds them.
        Every fit made is cached, so a cold cache warms over a few runs."""
        k = through.isoformat()
        if k in self._sr:
            return self._sr[k]
        if k in self.sr_skipped:
            return None
        current = (self.today - through).days <= CURRENT_DAYS
        mdl = None
        try:
            from oddsmarkets.tennis.models import _io
            from oddsmarkets.tennis.models import serve_return as SR
            c = SR.constants(self.tour)
            wd = float(c.get("window_days") or 1460)
            lo = (through - timedelta(days=int(max(wd, 4 * float(c.get("half_life_days") or 365))) + 1)).isoformat()
            hi = through.isoformat()
            ms = [m for m in self.rated_matches() if lo <= str(m.get("date"))[:10] <= hi]
            if not ms:
                mdl = None
            else:
                stats = self.tour == "wta"
                key = digest(SR.VERSION, c, stats, hi, len(ms),
                             hashlib.sha1("".join(f"{m['id']}{m.get('sets')}{m.get('status')}{bool(m.get('stats'))}"
                                                  for m in ms).encode()).hexdigest())

                def build():
                    return SR.fit(ms, through, c["half_life_days"],
                                  {"s": c["ridge"], "delta": c["ridge_delta"], "base": c["ridge_base"]},
                                  stats=stats, window_days=c["window_days"], stats_weight=c["stats_weight"])
                name = f"{self.tour}_{hi}"
                budget = sr_fit_budget()
                over = not current and budget is not None and _SR_BUDGET["spent"] >= budget
                if over:
                    hit = read_json(_io.cache_root() / "ace_sr" / f"{name}.json")
                    over = not (isinstance(hit, dict) and hit.get("key") == key)
                if over:
                    logger.info("%s serve/return fit through %s skipped: refit budget (%.0f s) spent", self.tour, hi, budget)
                    self.sr_skipped.add(k)
                    return None
                t0 = time.perf_counter()
                mdl = _io.cached("ace_sr", name, key, build)
                _SR_BUDGET["spent"] += time.perf_counter() - t0
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s serve/return fit through %s failed: %s", self.tour, through, exc)
            mdl = None
        if mdl is None and current:
            mdl = self._fitted_sr()           # the committed fit stands in only for a current one (CI, cold cache)
        if mdl is not None:
            self._sr[k] = mdl                 # a failed fit is retried on the next call, never memoised
        return mdl

    def _fitted_sr(self) -> dict | None:
        """The committed fit (models/fitted/serve_return_<tour>.json) when nothing can be fitted here."""
        from oddsmarkets.tennis.models import _io
        f = read_json(_io.FITTED / f"serve_return_{self.tour}.json")
        return (f or {}).get("model") if isinstance(f, dict) else None

    def season_end(self, year: int) -> date:
        return min(date(int(year), 12, 31), self.today)

    def season_sr(self, year: int) -> dict | None:
        return self.sr_fit(self.season_end(year))

    # prediction contexts
    def context(self, when: date, exact_elo: dict | None = None, exact_gelo: dict | None = None):
        """predict.Context at `when`: Elo ratings at that day (or exact pre-match Elo P by (p1, p2) when
        given), the serve/return fit through the day before, the committed blend. The game-share Elo term uses the
        exact pre-match differences by (p1, p2) when given (finished matches, as the backtest scored them), else the
        ratings at `when` for a current context (today or yesterday); a past context without exact values prices
        the term at 0 (ratings snapshots for every month would cost a pass over the history each)."""
        from oddsmarkets.tennis.models import elo as E
        from oddsmarkets.tennis.models import predict as P
        from oddsmarkets.tennis.models import serve_return as SR
        key = when.isoformat()
        base = self._ctx.get(key)
        if base is None:
            sr = self.sr_fit(when - timedelta(days=1))
            gr, gp = None, None
            if P.blend_params(self.tour).get("w_gelo") and when >= self.today - timedelta(days=1):
                try:
                    gr, gp = self.gelo_at(when), self.gelo.get("params")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s game-share Elo at %s failed: %s", self.tour, when, exc)
            base = P.Context(self.tour, when, elo_ratings=self.elo_at(when), elo_params=self.elo_params(), elo_mod=E,
                             sr_model=sr, sr_mod=SR if sr else None, gelo_ratings=gr, gelo_params=gp)
            self._ctx[key] = base
        if not exact_elo and not exact_gelo:
            return base
        elo_fn = None
        if exact_elo:
            def elo_fn(p1, p2, surface, best_of):
                v = exact_elo.get((p1, p2))
                if v is not None:
                    return v
                r1, r2 = base.elo_ratings.get(p1), base.elo_ratings.get(p2)
                return float(E.p_win(r1 or {}, r2 or {}, surface, int(best_of), base.elo_params))
        gelo_fn = None
        if exact_gelo:
            def gelo_fn(p1, p2, surface):
                v = exact_gelo.get((p1, p2))
                if v is not None:
                    return v
                if base.gelo_ratings is None:
                    return 0.0
                from oddsmarkets.tennis.models import gelo as G
                return G.diff(base.gelo_ratings.get(p1), base.gelo_ratings.get(p2), surface, base.gelo_params)
        return P.Context(self.tour, when, elo_ratings=base.elo_ratings, elo_params=base.elo_params, elo_mod=E,
                         sr_model=base.sr_model, sr_mod=base.sr_mod, elo_fn=elo_fn, gelo_fn=gelo_fn,
                         gelo_ratings=base.gelo_ratings, gelo_params=base.gelo_params)

    def gelo_pre(self, m: dict) -> float | None:
        """Game-share Elo difference for m.p1 before the match (gelo history), None when it has no row."""
        idx = self.__dict__.get("_gelo_idx")
        if idx is None:
            idx = self.__dict__["_gelo_idx"] = {str(g[0]): (str(g[2]), g[5]) for g in self.gelo.get("rows") or []}
        hit = idx.get(str(m.get("id")))
        if hit is None:
            return None
        return float(hit[1]) if hit[0] == str(m.get("p1")) else -float(hit[1])

    def today_context(self):
        return self.context(self.today)

    # pairs across years (head to head)
    def pair_index(self) -> dict[frozenset, list[dict]]:
        if getattr(self, "_pairs", None) is None:
            out: dict[frozenset, list[dict]] = {}
            for y in self.years:
                for m in self.matches(y).values():
                    if m.get("status") not in FINISHED or not m.get("winner") or m.get("status") == "wo":
                        continue
                    if str(m.get("round") or "") in ("Q1", "Q2", "Q3"):
                        continue
                    out.setdefault(frozenset((str(m["p1"]), str(m["p2"]))), []).append(m)
            for v in out.values():
                v.sort(key=lambda m: (str(m.get("date") or ""), ROUND_ORDER.get(m.get("round"), 5)))
            self._pairs = out
        return self._pairs


def h2h(td: TourData, a: str, b: str, before: str | None = None, last: int = 5) -> dict:
    """{"w","l","last":[[date, event, round, winner, score]]} from a's view, matches before `before` (iso)."""
    ms = td.pair_index().get(frozenset((str(a), str(b)))) or []
    if before:
        ms = [m for m in ms if str(m.get("date") or "")[:10] < before[:10]]
    w = sum(1 for m in ms if str(m["winner"]) == str(a))
    rows = [[str(m.get("date") or "")[:10], m.get("event"), m.get("round"), m.get("winner"),
             score_text(m, flip=str(m.get("p1")) != str(a))] for m in ms[-last:]][::-1]
    return {"w": w, "l": len(ms) - w, "last": rows}
