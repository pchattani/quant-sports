"""
Sofascore as a rugby source for The Quant Scrum (approved by the user on 2 Nov 2026; unclear terms, so it is credited in
the disclaimers and DATA_LICENSES and switched off with SOURCE_SOFASCORE_RUGBY_ENABLED=0, which also drops it from the
merge). It fills two gaps in ESPN's feed: team and player statistics for the 2026 Nations Championship (and other recent
tests ESPN carries without them), and the smaller nations' tests ESPN does not carry.

    /sport/rugby/scheduled-events/<YYYY-MM-DD>   every rugby event that day (one call a day): the discovery walk
    /event/<id>/statistics                       team statistics of a finished match
    /event/<id>/lineups                          the two matchday squads with each player's statistics

Rules (docs/RUNBOOK.md 5 and 5a; the football fetchers share the IP, and about 1,100 calls in an hour caused the 2 Nov
block):
  - its own small budget: at most HOURLY_MAX (30) calls in any rolling hour, counted across runs in the state file;
  - one call at a time, INTERVAL (5 s) apart: never a burst;
  - one host only (no fail-over to the mirror: a second host after a 403 would be a second call into the block);
  - the first 403 stops the run and is recorded (`blocked_at`), and no call is made for BACKOFF_HOURS (6) after any
    403: ours, the football season tables' (data/football/season_tables_state.json), or a failed football fetch in the
    hourly task's log (scripts/refresh_sofascore.log);
  - the Sofascore lock (data/deploy/locks/sofascore.lock, the football fetchers' lock): a run that finds it held skips;
  - PC only: Sofascore refuses datacenter addresses, so CI never calls it (the side store reaches CI in the stores
    snapshot, scripts/push_stores.py).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ...common import polite

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
FLAG = "SOURCE_SOFASCORE_RUGBY_ENABLED"
HOST = "api.sofascore.com"
HOURLY_MAX = 30
INTERVAL = 5.0
BACKOFF_HOURS = 6.0
CREDIT = "Sofascore (sofascore.com)"
LOCK_MAX_AGE_S = 3 * 3600

# a failed football fetch in the hourly log: the football fetchers stop at a 403 and log these lines
_LOG_FAIL = re.compile(r"^\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)[^\]]*([+-]\d\d:\d\d|Z)\]\s+(.*(fetch failed|HTTP 403|challeng).*)$")


def enabled() -> bool:
    return polite.flag_on(FLAG)


def state_path() -> Path:
    return Path(os.environ.get("RUGBY_SOFA_STATE") or (ROOT / "data" / "rugby" / "sofascore_state.json"))


def football_state_path() -> Path:
    return ROOT / "data" / "football" / "season_tables_state.json"


def hourly_log_path() -> Path:
    return ROOT / "scripts" / "refresh_sofascore.log"


def lock_path() -> Path:
    return ROOT / "data" / "deploy" / "locks" / "sofascore.lock"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def stamp(t: datetime | None = None) -> str:
    return (t or now_utc()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def load_state() -> dict:
    p = state_path()
    try:
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        st = {}
    st.setdefault("calls", [])
    st.setdefault("runs", [])
    return st


def save_state(st: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cut = stamp(now_utc() - timedelta(hours=2))
    st["calls"] = [c for c in st.get("calls") or [] if c >= cut]
    st["runs"] = (st.get("runs") or [])[-200:]
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ── the 403 back-off, read from every Sofascore fetcher on this PC ─────────────────────────────────────────────

def last_403s(st: dict | None = None, log_tail: int = 400) -> dict:
    """{source: the latest 403 (UTC datetime)} from our state, the football season tables' state and the hourly log."""
    out: dict[str, datetime] = {}
    st = st if st is not None else load_state()
    t = parse_ts(st.get("blocked_at"))
    if t:
        out["rugby"] = t
    try:
        fs = json.loads(football_state_path().read_text(encoding="utf-8"))
        t = parse_ts(fs.get("blocked_at"))
        if t:
            out["football season tables"] = t
    except (OSError, ValueError):
        pass
    try:
        lines = hourly_log_path().read_text(encoding="utf-8", errors="replace").splitlines()[-log_tail:]
    except OSError:
        lines = []
    for ln in lines:
        m = _LOG_FAIL.match(ln.strip())
        if not m:
            continue
        tz = m.group(2)
        t = parse_ts(m.group(1) + ("+00:00" if tz == "Z" else tz))
        if t and (out.get("football hourly log") is None or t > out["football hourly log"]):
            out["football hourly log"] = t
    return out


def backoff_left(st: dict | None = None, now: datetime | None = None) -> tuple[float, str | None]:
    """(hours left of the six-hour wait after the latest 403 anywhere, which source) — (0, None) when clear."""
    now = now or now_utc()
    best, who = 0.0, None
    for src, t in last_403s(st).items():
        left = BACKOFF_HOURS - (now - t).total_seconds() / 3600.0
        if left > best:
            best, who = left, src
    return best, who


def calls_last_hour(st: dict, now: datetime | None = None) -> int:
    cut = stamp((now or now_utc()) - timedelta(hours=1))
    return sum(1 for c in st.get("calls") or [] if c >= cut)


# ── the Sofascore lock (shared with the football fetchers) ─────────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    try:
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from local_sites import pid_alive          # the football fetchers' own liveness check
        return bool(pid_alive(int(pid)))
    except Exception:                               # noqa: BLE001 - unknown: treat as alive, the age rule breaks it
        return True


def take_lock(pid: int) -> bool:
    p = lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                info = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            started = parse_ts(info.get("started"))
            stale = (started is not None and (now_utc() - started).total_seconds() > LOCK_MAX_AGE_S) or \
                (info.get("pid") and not _pid_alive(int(info["pid"])))
            if not stale:
                return False
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": int(pid), "started": stamp(), "cmd": "scrum sofascore fetch"}, fh)
        return True
    return False


def release_lock(pid: int) -> None:
    p = lock_path()
    try:
        info = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if int(info.get("pid") or 0) == int(pid):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# ── the client ───────────────────────────────────────────────────────────────────────────────────────────────

class Blocked(RuntimeError):
    """Sofascore answered 403 (its IP-wide challenge): the run stops."""


class OutOfBudget(RuntimeError):
    pass


class Client:
    """One host, one call at a time INTERVAL seconds apart, at most `budget` calls this run and HOURLY_MAX in any
    rolling hour (across runs). A 403 records `blocked_at` and raises Blocked; every other failure returns None."""

    def __init__(self, budget: int = HOURLY_MAX, interval: float = INTERVAL, state: dict | None = None, get=None):
        self.state = state if state is not None else load_state()
        self.budget = max(0, min(int(budget), HOURLY_MAX - calls_last_hour(self.state)))
        self.interval = float(interval)
        self.used = self.fail = 0
        self.last_status: int | None = None
        self._last = 0.0
        self._get = get

    def _http(self, url: str):
        if self._get is not None:
            return self._get(url)
        from curl_cffi import requests as curl_requests          # ships with datafc (the football source)
        r = curl_requests.get(url, impersonate="chrome", timeout=20)
        return int(r.status_code), (r.json() if r.status_code == 200 else None)

    def get(self, path: str) -> dict | None:
        if polite.on_ci() or not enabled():
            raise OutOfBudget("Sofascore is not called on CI or with the source switched off")
        if self.used >= self.budget:
            raise OutOfBudget(f"budget of {self.budget} calls used")
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.used += 1
        self.state.setdefault("calls", []).append(stamp())
        try:
            status, payload = self._http(f"https://{HOST}/api/v1{path}")
        except Exception as exc:                                  # noqa: BLE001 - a transport error is a miss
            self._last = time.monotonic()
            self.fail += 1
            self.last_status = None
            log.warning("sofascore %s failed: %s", path, exc)
            return None
        self._last = time.monotonic()
        self.last_status = status
        if status == 403:
            self.state["blocked_at"] = stamp()
            self.state["blocked_path"] = path
            log.error("sofascore answered 403 on %s: stopping; no call for %.0f hours", path, BACKOFF_HOURS)
            raise Blocked(path)
        if status != 200:
            self.fail += 1
            log.info("sofascore %s -> HTTP %s", path, status)
            return None
        return payload


# ── parsing ──────────────────────────────────────────────────────────────────────────────────────────────────

# tournaments that are not 15-a-side senior rugby union tests (Sofascore files rugby league and sevens under the same
# sport); an event is kept only when neither its tournament nor its category matches
NOT_UNION = re.compile(r"rugby league|\bnrl\b|state of origin|super league|\bsevens\b|\b7s\b|\bsvns\b|\bu\s?-?\s?(16|17|18|19|20|21|23)\b|"
                       r"under[- ]?(18|19|20|21)|junior|youth|school|universit|student|academy|emerging|barbarian|"
                       r"\bxv\b|invitational|club friendl|beach|\btens\b|\b10s\b", re.I)
A_SIDE = re.compile(r"\s(A|B)$")          # 'England A' (case-sensitive: an A side, not a test)


def _name(x: Any) -> str:
    return str((x or {}).get("name") or "").strip()


def parse_event(e: dict) -> dict | None:
    """A Sofascore event -> our compact row; None for anything that is not a rugby event with two teams."""
    ht, at = e.get("homeTeam") or {}, e.get("awayTeam") or {}
    if not ht.get("id") or not at.get("id") or not e.get("id"):
        return None
    tour = e.get("tournament") or {}
    ut = tour.get("uniqueTournament") or {}
    cat = tour.get("category") or ut.get("category") or {}
    st = (e.get("status") or {}).get("type") or ""
    ts = e.get("startTimestamp")
    if not isinstance(ts, (int, float)):
        return None
    hs, as_ = (e.get("homeScore") or {}), (e.get("awayScore") or {})

    def score(s, k="current"):
        v = s.get(k)
        return int(v) if isinstance(v, (int, float)) else None

    def team(t):
        g = str(t.get("gender") or "").upper()[:1]
        col = (t.get("teamColors") or {}).get("primary")
        return {"id": int(t["id"]), "name": _name(t), "short": str(t.get("shortName") or ""), "code": str(t.get("nameCode") or ""),
                "g": g or None, "nat": bool(t.get("national")) if "national" in t else None, "col": col}
    return {"id": int(e["id"]), "ts": int(ts), "date": datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "st": st, "ut": ut.get("id"), "utn": _name(ut) or _name(tour), "tn": _name(tour), "cat": _name(cat),
            "season": _name(e.get("season")), "h": team(ht), "a": team(at), "hs": score(hs), "as": score(as_),
            "hh": [score(hs, "period1"), score(hs, "period2")], "ah": [score(as_, "period1"), score(as_, "period2")],
            "pstats": bool(e.get("hasEventPlayerStatistics"))}


def is_union_test(ev: dict) -> bool:
    """A senior 15-a-side union international between two national sides (by name; the merge adds the team-id check)."""
    from .. import nations
    txt = " ".join([ev.get("utn") or "", ev.get("tn") or "", ev.get("cat") or ""])
    if NOT_UNION.search(txt):
        return False
    for side in ("h", "a"):
        t = ev.get(side) or {}
        if t.get("nat") is False:
            return False
        if NOT_UNION.search(t.get("name") or "") or A_SIDE.search(t.get("name") or ""):
            return False
        if not nations.is_side(t.get("name") or ""):
            return False
    return True


def scope_of(ev: dict) -> str:
    g = {(ev.get("h") or {}).get("g"), (ev.get("a") or {}).get("g")}
    if "F" in g or re.search(r"\bwomen", (ev.get("utn") or "") + " " + (ev.get("h") or {}).get("name", ""), re.I):
        return "women"
    return "men"


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v or ""))
    return float(m.group(0)) if m else None


def parse_statistics(payload: dict | None) -> dict:
    """/event/<id>/statistics -> {item key or name: [home, away, home_total, away_total]} for the whole match. Values
    stay as Sofascore gives them (numbers; 'a/b (c%)' kept as a, with the total b); the merge maps them to ours."""
    out: dict[str, list] = {}
    for per in (payload or {}).get("statistics") or []:
        if str(per.get("period") or "ALL").upper() != "ALL":
            continue
        for g in per.get("groups") or []:
            for it in g.get("statisticsItems") or []:
                k = str(it.get("key") or it.get("name") or "").strip()
                if not k:
                    continue
                hv = it.get("homeValue") if isinstance(it.get("homeValue"), (int, float)) else _num(it.get("home"))
                av = it.get("awayValue") if isinstance(it.get("awayValue"), (int, float)) else _num(it.get("away"))
                ht_ = it.get("homeTotal") if isinstance(it.get("homeTotal"), (int, float)) else _total(it.get("home"))
                at_ = it.get("awayTotal") if isinstance(it.get("awayTotal"), (int, float)) else _total(it.get("away"))
                row = [hv, av]
                if ht_ is not None or at_ is not None:
                    row += [ht_, at_]
                out[k] = row
                nm = str(it.get("name") or "").strip()
                if nm and nm != k and nm not in out:
                    out["name:" + nm] = row
    return out


def _total(v: Any) -> float | None:
    m = re.match(r"\s*\d+(?:\.\d+)?\s*/\s*(\d+(?:\.\d+)?)", str(v or ""))
    return float(m.group(1)) if m else None


def parse_lineups(payload: dict | None) -> dict:
    """/event/<id>/lineups -> {"h": [[sofa_id, name, shirt, pos, sub, captain, {stat: v}]], "a": [...]}; {} when
    Sofascore has no line-ups for the match."""
    out = {}
    for side, key in (("h", "home"), ("a", "away")):
        rows = []
        for p in ((payload or {}).get(key) or {}).get("players") or []:
            pl = p.get("player") or {}
            if not pl.get("id"):
                continue
            shirt = p.get("shirtNumber", p.get("jerseyNumber", pl.get("jerseyNumber")))
            try:
                shirt = int(shirt)
            except (TypeError, ValueError):
                shirt = None
            stats = {k: v for k, v in (p.get("statistics") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
            rows.append([int(pl["id"]), _name(pl), shirt, str(p.get("position") or pl.get("position") or ""),
                         1 if p.get("substitute") else 0, 1 if p.get("captain") else 0, stats])
        if rows:
            out[side] = rows
    return out
