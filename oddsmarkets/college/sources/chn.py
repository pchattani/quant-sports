"""
College Hockey News (collegehockeynews.com) for The Quant Campus college hockey (`mch` men, `wch` women).

EVERYTHING that comes from CHN goes through this one module, behind one switch:

    CHN_ENABLED=0   (environment)  -> `enabled()` is False: no fetch, no parse, and the hockey builder drops every
                                      CHN-derived payload (player stats, box scores, shot metrics, rosters), so the
                                      site falls back to ESPN scores and our own models on results only.

The user approved CHN as the primary college hockey source on 30 Oct 2026 ("use the richest and most granular data
and acknowledge them in the disclaimer; if we have to take it down later that's ok"), credited on every hockey
page and in DATA_LICENSES.md. Nothing raw is re-hosted: raw pages stay in the private cache below, the site gets
derived facts and our model output only.

Politeness (required by the brief, enforced here, never by callers):
- robots.txt is obeyed for `User-agent: *` (wildcards and `$` anchors, longest match wins). It disallows box scores
  dated 2024 and earlier (`/box/final/19|200|201|2020..2024`), so historic seasons come from the team season pages
  (overall, advanced, game-by-game, roster) and the per-game shot-metrics page, which robots allows.
- a real User-Agent naming the project and a contact;
- one request at a time across every process on this PC (a lock directory) and at least `INTERVAL` seconds
  between requests (a shared timestamp file);
- back-off on 429 / 403 / 5xx (Retry-After honoured), and `Blocked` after repeated refusals so a job stops;
- every raw page cached (gzip) so nothing is fetched twice; current-season pages take a `max_age`.
- local fetch only (this PC), never CI: `fetch_allowed()` is False when `CI` is set.

URL map (probed 30 Oct 2026; men unless noted, women add the `/women` prefix to stats / roster / schedules pages,
and a trailing `w` to box URLs):
  /schedules/?date=YYYYMMDD                       men's day scoreboard: games, `metrics.php?gd=` ids, box links
  /stats/team/<Slug>/<id>/overall,<YYYYyyyy>      season: skater scoring (GP G A Pts Sh +/- PIM GWG PPG SHG, pos,
                                                  class) and goaltending; the nav lists that season's teams by
                                                  conference (the per-season D-I membership)
  /stats/team/<Slug>/<id>/advanced,<..>           season shot attempts by strength (men from 2013-14)
  /stats/team/<Slug>/<id>/gamebygame,<..>         every game: goals / shots by period, PP, PIM, scorers,
                                                  attendance, box and metrics links (gd ids)
  /reports/roster/<Slug>/<id>/<YYYYyyyy>          roster: number, class, position, height, weight, DOB, hometown,
                                                  last team, NHL draft (women: /women/roster/...)
  /box/final/<YYYYMMDD>/<away>/<home>/[w]         box: periods, shots, team PIM/PPG/FO/xG, scoring with assists,
                                                  times and PP/SH/EN, penalties, goalies, skater G A +/- Sh TOI
                                                  PIM FO (TOI and xG on men's recent boxes), line chart
  /box/metrics.php?gd=<n>                         per-player shot attempts (blocked / missed / saved / goal) by
                                                  total, even strength, power play and close; goalie saves by
                                                  strength. Men only.
CHN does not publish shot coordinates in its box or metrics pages (checked 30 Oct 2026, current and past games).
"""
from __future__ import annotations

import gzip
import hashlib
import html as _html
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)

BASE = "https://www.collegehockeynews.com"
USER_AGENT = "TheQuantCampus/1.0 (college hockey analytics; +https://pchattani.github.io/the-quant-campus)"
INTERVAL = 3.0          # seconds between requests, shared by every process
TIMEOUT = 40
ROOT = Path(__file__).resolve().parents[3]
LEVELS = ("mch", "wch")
CREDIT = "College Hockey News (collegehockeynews.com)"


def enabled() -> bool:
    """The one switch. Off -> no CHN fetch, parse or payload anywhere."""
    return os.environ.get("CHN_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")


def fetch_allowed() -> bool:
    """Network fetches only from the PC (never CI) and only while enabled."""
    return enabled() and not os.environ.get("CI") and not os.environ.get("GITHUB_ACTIONS")


def raw_root() -> Path:
    return Path(os.environ.get("CHN_RAW") or (ROOT / "data" / "college" / "chn"))


class Blocked(RuntimeError):
    """The site refused us repeatedly (403/429/5xx): stop the job."""


class Disallowed(RuntimeError):
    """robots.txt disallows this path."""


# ── robots ─────────────────────────────────────────────────────────────────────────────────────────────────

def parse_robots(text: str, agent: str = "*") -> list[tuple[str, bool]]:
    """Rules of the group that applies to `agent` (here always '*'): [(pattern, allow)]."""
    groups: list[tuple[list[str], list[tuple[str, bool]]]] = []
    cur_agents: list[str] = []
    cur_rules: list[tuple[str, bool]] = []
    last_was_agent = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            if not last_was_agent and (cur_agents or cur_rules):
                groups.append((cur_agents, cur_rules))
                cur_agents, cur_rules = [], []
            cur_agents.append(v.lower())
            last_was_agent = True
        elif k in ("allow", "disallow"):
            last_was_agent = False
            if v:
                cur_rules.append((v, k == "allow"))
        else:
            last_was_agent = False
    if cur_agents or cur_rules:
        groups.append((cur_agents, cur_rules))
    rules: list[tuple[str, bool]] = []
    for agents, rs in groups:
        if agent.lower() in agents:
            rules.extend(rs)
    if not rules and agent != "*":
        return parse_robots(text, "*")
    return rules


def _pat_re(p: str) -> re.Pattern:
    anchored = p.endswith("$")
    body = p[:-1] if anchored else p
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile("^" + rx + ("$" if anchored else ""))


def robots_allows(rules: list[tuple[str, bool]], path: str) -> bool:
    """Longest matching rule wins; ties go to Allow (Google semantics). No match -> allowed."""
    best_len, best_allow = -1, True
    for pat, allow in rules:
        if _pat_re(pat).match(path):
            ln = len(pat)
            if ln > best_len or (ln == best_len and allow):
                best_len, best_allow = ln, allow
    return best_allow


# ── cache ──────────────────────────────────────────────────────────────────────────────────────────────────

def cache_path(path: str) -> Path:
    p = path.strip("/")
    safe = re.sub(r"[^A-Za-z0-9.,=-]+", "_", p)[:150] or "index"
    h = hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]
    head = p.split("/", 1)[0].split("?", 1)[0] or "root"
    if head == "women" and "/" in p:
        head = "women_" + p.split("/")[1].split("?", 1)[0]
    return raw_root() / "raw" / re.sub(r"[^A-Za-z0-9_.-]", "_", head) / f"{safe}.{h}.json.gz"


def read_cached(path: str) -> dict | None:
    cp = cache_path(path)
    if not cp.exists():
        return None
    try:
        with gzip.open(cp, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, EOFError):
        return None


def _write_cached(path: str, rec: dict) -> None:
    cp = cache_path(path)
    cp.parent.mkdir(parents=True, exist_ok=True)
    tmp = cp.with_name(cp.name + f".{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
        json.dump(rec, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, cp)


def _age_s(rec: dict) -> float:
    try:
        t = datetime.strptime(rec["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except (KeyError, ValueError):
        return 1e12


# ── client ─────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Client:
    interval: float = INTERVAL
    budget: int | None = None              # max network requests this run (None = unlimited)
    offline: bool = False                  # cache only
    used: int = 0
    failures: int = 0
    _rules: list | None = field(default=None, repr=False)
    _session: Any = field(default=None, repr=False)

    def __post_init__(self):
        if not fetch_allowed():
            self.offline = True

    # robots.txt itself is cached for a day
    def rules(self) -> list[tuple[str, bool]]:
        if self._rules is None:
            rec = read_cached("/robots.txt")
            if (rec is None or _age_s(rec) > 86400) and not self.offline:
                rec = self._fetch("/robots.txt", check_robots=False) or rec
            text = (rec or {}).get("html") or ""
            if not text:
                raise Blocked("robots.txt unavailable; refusing to crawl blind")
            self._rules = parse_robots(text)
        return self._rules

    def allowed(self, path: str) -> bool:
        return robots_allows(self.rules(), path)

    def get(self, path: str, max_age: float | None = None, refetch_missing: bool = False) -> str | None:
        """HTML of `path` (site-relative). Cached pages are returned without a request unless older than `max_age`
        seconds. Returns None for a 404 / disallowed / offline miss. Raises Blocked when the site keeps refusing."""
        if not enabled():
            return None
        rec = read_cached(path)
        if rec is not None:
            fresh = max_age is None or _age_s(rec) <= max_age
            if fresh and (rec.get("status") == 200 or not refetch_missing):
                return rec.get("html") if rec.get("status") == 200 else None
        if self.offline:
            return rec.get("html") if rec and rec.get("status") == 200 else None
        if not self.allowed(path):
            raise Disallowed(path)
        new = self._fetch(path)
        if new is None:
            return rec.get("html") if rec and rec.get("status") == 200 else None
        return new.get("html") if new.get("status") == 200 else None

    def cached_or_none(self, path: str) -> str | None:
        rec = read_cached(path)
        return rec.get("html") if rec and rec.get("status") == 200 else None

    # one paced request across every process on the PC
    def _fetch(self, path: str, check_robots: bool = True) -> dict | None:
        if self.budget is not None and self.used >= self.budget:
            raise BudgetExhausted(f"CHN budget {self.budget} used")
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8",
                                          "Accept-Language": "en-US,en;q=0.8"})
        url = BASE + path
        delay = 60.0
        for attempt in range(4):
            with _GlobalPace(self.interval):
                self.used += 1
                try:
                    r = self._session.get(url, timeout=TIMEOUT, allow_redirects=True)
                    status, text = r.status_code, r.text
                    retry_after = r.headers.get("Retry-After")
                except requests.RequestException as e:
                    status, text, retry_after = -1, "", None
                    logger.warning("CHN %s: %s", path, e)
            if status == 200:
                self.failures = 0
                rec = {"path": path, "status": 200, "fetched_at": _now(), "html": text}
                _write_cached(path, rec)
                return rec
            if status in (404, 410):
                self.failures = 0
                rec = {"path": path, "status": status, "fetched_at": _now(), "html": ""}
                _write_cached(path, rec)
                return rec
            # 403 / 429 / 5xx / network: back off
            self.failures += 1
            if self.failures >= 6:
                raise Blocked(f"CHN refused {self.failures} times in a row (last {status} on {path})")
            wait = delay
            if retry_after and str(retry_after).isdigit():
                wait = max(wait, float(retry_after))
            if status == 403:
                wait = max(wait, 300.0)
            logger.warning("CHN %s -> %s; backing off %.0f s", path, status, wait)
            time.sleep(wait)
            delay *= 2
        return None


class BudgetExhausted(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _GlobalPace:
    """mkdir lock + last-request timestamp, so the backfill and the hourly refresh never overlap or speed up."""

    def __init__(self, interval: float):
        self.interval = interval
        self.dir = raw_root()
        self.lock = self.dir / ".fetch_lock"
        self.stamp = self.dir / ".last_fetch"

    def _last(self) -> float:
        try:
            return float(self.stamp.read_text().strip())
        except (OSError, ValueError):
            return 0.0

    def __enter__(self):
        """Wait for the gap WITHOUT the lock, then take the lock only for the request itself, so two processes
        (the backfill and the hourly refresh) share the slot fairly instead of one starving the other."""
        self.dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        while True:
            wait = self._last() + self.interval - time.time()
            if wait > 0:
                time.sleep(wait + random.uniform(0, 0.6))
                continue
            try:
                self.lock.mkdir()
            except FileExistsError:
                try:
                    if time.time() - self.lock.stat().st_mtime > 300:      # a crashed holder
                        self.lock.rmdir()
                        continue
                except OSError:
                    pass
                if time.time() - t0 > 1800:
                    raise Blocked("CHN fetch lock held for 30 minutes")
                time.sleep(random.uniform(0.2, 0.8))
                continue
            if self._last() + self.interval > time.time():      # someone fetched while we waited
                self.lock.rmdir()
                continue
            return self

    def __exit__(self, *exc):
        try:
            self.stamp.write_text(f"{time.time():.3f}")
        finally:
            try:
                self.lock.rmdir()
            except OSError:
                pass
        return False


# ── URLs ───────────────────────────────────────────────────────────────────────────────────────────────────

def season_code(season: int) -> str:
    """Campus season (the year it ends, 2027 = 2026-27) -> CHN '20262027'."""
    return f"{int(season) - 1}{int(season)}"


def code_season(code: str) -> int:
    return int(str(code)[4:8])


def _pfx(level: str) -> str:
    return "/women" if level == "wch" else ""


def team_stats_url(level: str, slug: str, tid: str | int, kind: str, season: int) -> str:
    return f"{_pfx(level)}/stats/team/{slug}/{tid}/{kind},{season_code(season)}"


def roster_url(level: str, slug: str, tid: str | int, season: int) -> str:
    base = "/women/roster" if level == "wch" else "/reports/roster"
    return f"{base}/{slug}/{tid}/{season_code(season)}"


def schedule_day_url(level: str, ymd: str) -> str:
    return f"{_pfx(level)}/schedules/?date={ymd}"


def metrics_url(gd: str | int) -> str:
    return f"/box/metrics.php?gd={gd}"


# ── generic HTML table reader (no bs4 in the project) ──────────────────────────────────────────────────────

class _Tables(HTMLParser):
    """Every <table> as rows of cells; a cell is {"t": text, "a": [hrefs], "cls": class}. Also collects all
    anchors and headings in document order (`self.seq`) so callers can find what precedes a table."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self.stack: list[dict] = []
        self.cell: dict | None = None
        self.row: list | None = None
        self.seq: list[tuple[str, Any]] = []      # ("h", text) | ("table", idx) | ("a", (href, text))
        self._htext: list[str] | None = None
        self._a: list | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag == "table":
            t = {"rows": [], "cls": a.get("class") or "", "id": a.get("id") or ""}
            self.stack.append(t)
            self.tables.append(t)
            self.seq.append(("table", len(self.tables) - 1))
        elif tag == "tr" and self.stack:
            self.row = []
            self.stack[-1]["rows"].append(self.row)
        elif tag in ("td", "th") and self.stack:
            if self.row is None:
                self.row = []
                self.stack[-1]["rows"].append(self.row)
            self.cell = {"t": "", "a": [], "cls": a.get("class") or "", "th": tag == "th",
                         "span": int(a.get("colspan") or 1) if str(a.get("colspan") or "1").isdigit() else 1}
            self.row.append(self.cell)
        elif tag == "a":
            href = a.get("href") or ""
            if self.cell is not None:
                self.cell["a"].append(href)
            self._a = [href, ""]
        elif tag in ("h1", "h2", "h3", "h4", "caption"):
            self._htext = []
        elif tag == "br" and self.cell is not None:
            self.cell["t"] += " "

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if tag == "table" and self.stack:
            self.stack.pop()
            self.row, self.cell = None, None
        elif tag in ("td", "th"):
            self.cell = None
        elif tag == "tr":
            self.row = None
        elif tag == "a" and self._a is not None:
            self.seq.append(("a", (self._a[0], self._a[1].strip())))
            self._a = None
        elif tag in ("h1", "h2", "h3", "h4", "caption") and self._htext is not None:
            self.seq.append(("h", " ".join("".join(self._htext).split())))
            self._htext = None

    def handle_data(self, data):
        if self._skip:
            return
        if self.cell is not None:
            self.cell["t"] += data
        if self._htext is not None:
            self._htext.append(data)
        if self._a is not None:
            self._a[1] += data


def _norm(s: str) -> str:
    s = s.replace("‑", "-").replace("–", "-").replace("−", "-").replace("\xa0", " ")
    return " ".join(s.split())


def read_tables(html_text: str) -> _Tables:
    p = _Tables()
    p.feed(html_text or "")
    p.close()
    for t in p.tables:
        for row in t["rows"]:
            for c in row:
                c["t"] = _norm(c["t"])
    return p


def _int(s: Any) -> int | None:
    s = _norm(str(s or "")).replace(",", "")
    if s in ("", "-", "--"):
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def _float(s: Any) -> float | None:
    s = _norm(str(s or "")).replace(",", "")
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pair(s: str) -> tuple[int | None, int | None]:
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", _norm(s or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _mmss(s: str) -> int | None:
    m = re.match(r"^\s*(\d+):(\d\d)\s*$", _norm(s or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _strip_tags(s: str) -> str:
    return _norm(_html.unescape(re.sub(r"<[^>]+>", " ", s)))


# ── team links / season membership ─────────────────────────────────────────────────────────────────────────

_TEAM_LINK = re.compile(r'<a href="(?:/women)?/stats/team/([A-Za-z0-9-]+)/(\d+)/overall,(\d{8})">\s*([^<]+?)\s*</a>')


def parse_season_teams(html_text: str) -> list[dict]:
    """The season's teams by conference from a team season page's 'Other Teams' menu:
    [{slug, chn_id, name, conf}] (conference as CHN names it that season)."""
    i = (html_text or "").find("Other Teams")
    if i < 0:
        return []
    seg = html_text[i:]
    end = seg.find("</nav>")
    if end > 0:
        seg = seg[:end]
    out, conf = [], None
    for m in re.finditer(r'<p>([^<]+)</p>|' + _TEAM_LINK.pattern, seg):
        if m.group(1):
            conf = _norm(_html.unescape(m.group(1)))
            continue
        out.append({"slug": m.group(2), "chn_id": m.group(3), "name": _norm(_html.unescape(m.group(5))),
                    "conf": conf})
    seen, uniq = set(), []
    for t in out:
        if t["chn_id"] not in seen:
            seen.add(t["chn_id"])
            uniq.append(t)
    return uniq


def parse_nav_teams(html_text: str, level: str) -> list[dict]:
    """Today's Division I teams from the site menu every page carries ([{slug, chn_id, name, conf: None}]): a program
    new this season (Maryville, 2026-27) can be missing from a team page's season menu."""
    pat = (r'<a href="/women/team/([A-Za-z0-9-]+)/(\d+)"[^>]*>\s*([^<]+?)\s*</a>' if level == "wch" else
           r'<a href="/reports/team/([A-Za-z0-9-]+)/(\d+)" class="team"[^>]*>\s*([^<]+?)\s*</a>')
    out, seen = [], set()
    for m in re.finditer(pat, html_text or ""):
        if m.group(2) in seen:
            continue
        seen.add(m.group(2))
        out.append({"slug": m.group(1), "chn_id": m.group(2), "name": _norm(_html.unescape(m.group(3))), "conf": None})
    return out


def season_teams(html_text: str, level: str, current: bool) -> list[dict]:
    """The season's team list; for the current season with any team in today's site menu added (as Independent)."""
    teams = parse_season_teams(html_text)
    if current and teams:
        have = {t["chn_id"] for t in teams}
        for t in parse_nav_teams(html_text, level):
            if t["chn_id"] not in have:
                teams.append({**t, "conf": "Independent"})
    return teams


def parse_season_list(html_text: str, level: str, slug: str, tid: str | int) -> list[int]:
    pf = "/women" if level == "wch" else ""
    codes = set(re.findall(re.escape(f"{pf}/stats/team/{slug}/{tid}/") + r"[a-z]+,(\d{8})", html_text or ""))
    return sorted({code_season(c) for c in codes})


# ── team season: overall (skaters + goalies) ───────────────────────────────────────────────────────────────

def _header_index(row: list[dict]) -> dict[str, int]:
    return {c["t"]: i for i, c in enumerate(row)}


def _player_link(cell: dict) -> str | None:
    for a in cell.get("a") or []:
        m = re.search(r"/players/(?:career/)?[^/]+/(\d+)", a) or re.search(r"/stats/player/[^/]*/?(\d+)", a)
        if m:
            return m.group(1)
    return None


def parse_overall(html_text: str) -> dict:
    """{"record", "skaters": [...], "goalies": [...]}. Skater: name, pos, cls, gp, g, a, pts, sh, pim, gwg, ppg,
    shg, pm, chn_pid. Goalie: name, cls, gp, w, l, t, ga, min, sv, so, chn_pid."""
    tb = read_tables(html_text)
    out: dict[str, Any] = {"skaters": [], "goalies": [], "record": None}
    m = re.search(r"Record</span>\s*<span>([^<]+)</span>", html_text or "") or \
        re.search(r"Record\s*</?[^>]*>\s*([0-9]+-[0-9]+-[0-9]+[^<]*)", html_text or "")
    if m:
        out["record"] = _norm(_strip_tags(m.group(1)))
    for t in tb.tables:
        rows = t["rows"]
        if not rows:
            continue
        hi = None
        for k, r in enumerate(rows[:3]):
            names = [c["t"] for c in r]
            if "Name, Yr" in names:
                hi = k
                break
        if hi is None:
            continue
        hdr = _header_index(rows[hi])
        is_goalie = "SV%" in hdr or "GAA" in hdr
        for r in rows[hi + 1:]:
            if len(r) < len(hdr) - 1:
                continue
            nm = r[hdr["Name, Yr"]]["t"]
            if not nm or nm.upper().startswith("TOTAL"):
                continue
            parts = [p.strip() for p in nm.split(",")]
            name = parts[0]
            g = lambda k: r[hdr[k]]["t"] if k in hdr and hdr[k] < len(r) else ""
            pid = _player_link(r[hdr["Name, Yr"]])
            if is_goalie:
                cls = parts[1] if len(parts) > 1 else None
                out["goalies"].append({"name": name, "cls": cls, "chn_pid": pid, "gp": _int(g("GP")),
                                       "w": _int(g("W")), "l": _int(g("L")), "t": _int(g("T")),
                                       "ga": _int(g("GA")), "min": _int(g("MIN")), "sv": _int(g("SV")),
                                       "so": _int(g("SH"))})
            else:
                pos = parts[1] if len(parts) > 2 else None
                cls = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else None)
                out["skaters"].append({"name": name, "pos": pos, "cls": cls, "chn_pid": pid, "gp": _int(g("GP")),
                                       "g": _int(g("G")), "a": _int(g("A")), "pts": _int(g("Pts.")),
                                       "sh": _int(g("Shots")), "pim": _int(g("PIM")), "gwg": _int(g("GWG")),
                                       "ppg": _int(g("PPG")), "shg": _int(g("SHG")), "pm": _int(g("+/-"))})
    return out


# ── team season: advanced (shot attempts by strength) ──────────────────────────────────────────────────────

SA_SPLITS = ("all", "ev", "pp", "close")
SA_KEYS = ("bl", "mi", "sv", "g", "tsa")


def metrics_has_data(html_text: str) -> bool:
    """A per-game metrics page with player rows (CHN only filled these for recent seasons)."""
    return any(t["kind"] == "skaters" and any(r["name"] != "TOTAL" for r in t["rows"])
               for t in parse_attempt_tables(html_text or ""))


def parse_attempt_tables(html_text: str) -> list[dict]:
    """Shot-attempt tables (team season 'advanced' page and the per-game metrics page). One dict per table:
    {"team": label, "kind": "skaters"|"goalies", "rows": [...]}. Skater rows: name, chn_pid, {split}_{key} for
    split in all/ev/pp/close and key in bl/mi/sv/g/tsa, blk, fow, fol. Goalie rows: name, chn_pid,
    {all,ev,sh|pp,close}_{sv,ga}."""
    tb = read_tables(html_text)
    out = []
    for t in tb.tables:
        rows = t["rows"]
        if len(rows) < 3:
            continue
        flat = [[c["t"] for c in r] for r in rows[:5]]
        sk = next((k for k, r in enumerate(flat) if "TOTAL" in r and any("EVEN STRENGTH" in x for x in r)), None)
        if sk is None:
            continue
        top = flat[sk]
        team = top[0] if top and top[0] not in ("TOTAL", "Player") else ""
        hdr_i = next((k for k in range(sk + 1, len(flat)) if "Player" in flat[k] or "SV%" in flat[k]), sk + 1)
        goalie = "SV%" in flat[hdr_i] if hdr_i < len(flat) else False
        splits = []
        for c in rows[sk]:
            lab = c["t"].upper()
            if lab in ("TOTAL", "EVEN STRENGTH", "POWER PLAY", "SHORTHANDED", "CLOSE"):
                splits.append({"TOTAL": "all", "EVEN STRENGTH": "ev", "POWER PLAY": "pp", "SHORTHANDED": "sh",
                               "CLOSE": "close"}[lab])
        recs = []
        cur_team = flat[hdr_i][0] if goalie and hdr_i < len(flat) and flat[hdr_i] else team
        if goalie:
            team = cur_team
        for r in rows[hdr_i + 1:]:
            cells = [c["t"] for c in r]
            if not cells or not cells[0] or cells[0].upper().startswith("KEY"):
                continue
            if len(cells) > 1 and cells[1] in ("SV", "Bl"):
                cur_team = cells[0]
                continue
            name = cells[0]
            if name.upper() == "TOTAL":
                name = "TOTAL"
            rec: dict[str, Any] = {"name": name, "chn_pid": _player_link(r[0]), "team": cur_team}
            vals = cells[1:]
            if goalie:
                for k, sp in enumerate(splits):
                    rec[f"{sp}_sv"] = _int(vals[3 * k]) if 3 * k < len(vals) else None
                    rec[f"{sp}_ga"] = _int(vals[3 * k + 1]) if 3 * k + 1 < len(vals) else None
            else:
                for k, sp in enumerate(splits):
                    for j, key in enumerate(SA_KEYS):
                        idx = 5 * k + j
                        rec[f"{sp}_{key}"] = _int(vals[idx]) if idx < len(vals) else None
                rest = vals[5 * len(splits):]
                rec["blk"] = _int(rest[0]) if rest else None
                fo = rest[1] if len(rest) > 1 else ""
                rec["fow"], rec["fol"] = _pair(fo)
            recs.append(rec)
        out.append({"team": team, "kind": "goalies" if goalie else "skaters", "rows": recs})
    return out


# ── team season: game by game ──────────────────────────────────────────────────────────────────────────────

def parse_gamebygame(html_text: str, season: int) -> list[dict]:
    """Every game of a team season: date (YYYY-MM-DD), site ('home'|'away'|'neutral'), opp name, opp chn_id (when
    linked), res W/L/T, gf / ga by period (p1 p2 p3 ot), sf / sa by period, pp (ppg, ppo), pk (ppga, times shorthanded),
    pim, scorers, att, box (path), gd (metrics id)."""
    tb = read_tables(html_text)
    games = []
    gd_by_box = {b: g for g, b in re.findall(r'metrics\.php\?gd=(\d+)"[^<]*</a></td>\s*-->\s*<td><a href="(/box/final/[^"]+)"',
                                             html_text or "")}
    for t in tb.tables:
        rows = t["rows"]
        flat = [[c["t"] for c in r] for r in rows[:3]]
        if not any("Opp." in r for r in flat) or not any("Scorers" in " ".join(r) for r in flat):
            continue
        hdr_k = next(k for k, r in enumerate(flat) if "Opp." in r)
        hcol = {}
        for i, name in enumerate(flat[hdr_k]):
            if name in ("PP", "OPP", "PIM", "xG", "xGopp", "Scorers", "Att.") and name not in hcol:
                hcol[name] = i
        for r in rows[hdr_k + 1:]:
            cells = [c["t"] for c in r]
            if len(cells) < 5:
                continue
            links = [a for c in r for a in c["a"]]
            box = next((a for a in links if a.startswith("/box/final/")), None)
            gd_live = next((re.search(r"gd=(\d+)", a).group(1) for a in links if "metrics.php?gd=" in a), None)
            gd = gd_live or (gd_by_box.get(box) if box else None)
            # columns: date, site, opp, res, g1 g2 g3 got gT, o1 o2 o3 oot oT, s1 s2 s3 sot sT, a1 a2 a3 aot aT, PP, OPP, PIM, scorers, att
            dt = _date_from(cells[0], season, box)
            site = {"vs.": "neutral", "at": "away", "": "home"}.get(cells[1].strip(), "home")
            opp_cell = r[2]
            opp_id = None
            for a in opp_cell["a"]:
                mm = re.search(r"/(?:stats/)?team/[^/]+/(\d+)", a) or re.search(r"/schedules/team/[^/]+/(\d+)", a)
                if mm:
                    opp_id = mm.group(1)
            if any("No data entered" in c for c in cells) or len(cells) < 25:
                games.append({"date": dt, "site": site, "opp": cells[2], "opp_chn": opp_id, "res": None,
                              "gf": None, "ga": None, "sf": None, "sa": None, "ppg": None, "ppo": None,
                              "opp_ppg": None, "opp_ppo": None, "pim": None, "scorers": "", "att": None,
                              "box": box, "gd": gd, "gd_live": bool(gd_live), "nodata": True})
                continue
            nums = cells[4:24]
            per = lambda xs: {"p1": _int(xs[0]), "p2": _int(xs[1]), "p3": _int(xs[2]), "ot": _int(xs[3]),
                              "t": _int(xs[4])}
            col = lambda name: (cells[hcol[name]] if name in hcol and hcol[name] < len(cells) else "")
            ppg, ppo = _pair(col("PP"))
            oppg, oppo = _pair(col("OPP"))
            rm = re.match(r"^([WLT])", cells[3] or "")
            games.append({"date": dt, "site": site, "opp": cells[2], "opp_chn": opp_id, "res": rm.group(1) if rm else None,
                          "res_label": cells[3] or None, "ot_flag": "OT" in (cells[3] or "").upper() or None,
                          "so_flag": "SO" in (cells[3] or "").upper() or None,
                          "gf": per(nums[0:5]), "ga": per(nums[5:10]), "sf": per(nums[10:15]), "sa": per(nums[15:20]),
                          "ppg": ppg, "ppo": ppo, "opp_ppg": oppg, "opp_ppo": oppo, "pim": _int(col("PIM")),
                          "xg": _float(col("xG")), "xga": _float(col("xGopp")), "scorers": col("Scorers"),
                          "att": _int(col("Att.")), "box": box, "gd": gd, "gd_live": bool(gd_live)})
        break
    return games


_MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                       "Dec"], 1)}


def _date_from(label: str, season: int, box: str | None) -> str | None:
    if box:
        m = re.match(r"/box/final/(\d{4})(\d\d)(\d\d)/", box)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2})", _norm(label))
    if not m or m.group(1) not in _MONTHS:
        return None
    mo = _MONTHS[m.group(1)]
    yr = int(season) - 1 if mo >= 8 else int(season)
    return f"{yr}-{mo:02d}-{int(m.group(2)):02d}"


# ── roster ─────────────────────────────────────────────────────────────────────────────────────────────────

def parse_roster(html_text: str) -> list[dict]:
    """[{num, name ('First Last'), cls, pos, ht_in, wt, dob (YYYY-MM-DD), hometown, last_team, draft, chn_pid}]"""
    tb = read_tables(html_text)
    out = []
    for t in tb.tables:
        rows = t["rows"]
        hi = next((k for k, r in enumerate(rows[:3]) if any(c["t"] == "Name" for c in r)
                   and any(c["t"].startswith("Pos") for c in r)), None)
        if hi is None:
            continue
        hdr = {c["t"].strip(): i for i, c in enumerate(rows[hi])}
        col = lambda name: next((i for k, i in hdr.items() if k.startswith(name)), None)
        ci = {k: col(k) for k in ("No.", "Name", "Yr", "Pos", "Ht", "Wt", "DOB", "Hometown", "Last Team", "NHL Draft")}
        for r in rows[hi + 1:]:
            if ci["Name"] is None or len(r) <= ci["Name"]:
                continue
            nm = r[ci["Name"]]["t"]
            if not nm or len(r) < 4:
                continue
            g = lambda k: r[ci[k]]["t"] if ci[k] is not None and ci[k] < len(r) else ""
            if "," in nm:
                last, first = nm.split(",", 1)
                name = f"{first.strip()} {last.strip()}"
            else:
                name = nm
            ht = None
            mh = re.match(r"(\d)-(\d{1,2})", g("Ht"))
            if mh:
                ht = int(mh.group(1)) * 12 + int(mh.group(2))
            dob = None
            md = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", g("DOB"))
            if md:
                dob = f"{md.group(3)}-{int(md.group(1)):02d}-{int(md.group(2)):02d}"
            out.append({"num": g("No.") or None, "name": name, "cls": g("Yr") or None, "pos": g("Pos") or None,
                        "ht_in": ht, "wt": _int(g("Wt")), "dob": dob, "hometown": g("Hometown") or None,
                        "last_team": g("Last Team") or None, "draft": g("NHL Draft") or None,
                        "chn_pid": _player_link(r[ci["Name"]])})
        if out:
            break
    return out


# ── box score ──────────────────────────────────────────────────────────────────────────────────────────────

def _segment(html_text: str, div_id: str) -> str:
    """The HTML of <div id="div_id"> up to the next top-level box section."""
    i = html_text.find(f'<div id="{div_id}"')
    if i < 0:
        return ""
    nxt = [html_text.find(f'<div id="{k}"', i + 10) for k in
           ("meta", "linescore", "goals", "shots", "pp", "scoring", "penalties", "goalies", "playersums", "linechart",
            "right", "bottom")]
    nxt = [n for n in nxt if n > i]
    return html_text[i:min(nxt) if nxt else len(html_text)]


def _rows_with_class(seg: str) -> list[tuple[str, list[dict]]]:
    """Rows of a segment's tables in order: (tr class, cells); section rows carry class 'stats-section'."""
    out = []
    for m in re.finditer(r"<tr([^>]*)>(.*?)</tr>", seg, re.S):
        cls = re.search(r'class="([^"]*)"', m.group(1))
        cells = []
        for c in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", m.group(2), re.S):
            inner = c.group(1)
            cells.append({"t": _strip_tags(inner), "a": re.findall(r'href="([^"]+)"', inner)})
        out.append((cls.group(1) if cls else "", cells))
    return out


def _period_of(label: str, cur: int) -> int:
    low = label.lower()
    if "1st" in low and "ot" not in low:
        return 1
    if "2nd" in low and "ot" not in low:
        return 2
    if "3rd" in low and "ot" not in low:
        return 3
    if "shootout" in low:
        return 99
    m = re.search(r"(\d+)(?:st|nd|rd|th)?\s*(?:ot|overtime)", low)
    if m:
        return 3 + int(m.group(1))
    if "ot" in low or "overtime" in low:
        return 4
    return cur


def _pid(links: list[str]) -> str | None:
    for a in links:
        m = re.search(r"/players/career/[^/]+/(\d+)", a)
        if m:
            return m.group(1)
    return None


def parse_box(html_text: str) -> dict | None:
    """A final box score; None when the page holds no box.
    {"away"/"home": {name, chn_slug, chn_id, abbr, score, record, periods[], shots[], pen, pim, ppg, ppo, fow, fol, xg},
     "date", "game_type" (CHN's label: 'Hockey East Game', 'Non-Conference Game', '... Tournament ...'), "venue", "att",
     "refs", "ot" (overtime periods), "so" (shootout), "goals": [{per, t (s into the period), team ('away'|'home'),
     scorer, scorer_pid, n (season goal no.), a1, a2, sit ('EV'|'PP'|'SH'|'EN'|'PP+EN'...)}], "pens": [{per, t, team,
     player, min, inf}], "goalies": [{team, name, sv, ga, sec, en}], "skaters": [{team, name, g, a, pm, sh, toi (s),
     pim, fow, fol}], "lines": {side: {F, D, G, X}}}"""
    if not html_text or '<div id="linescore"' not in html_text:
        return None
    res: dict[str, Any] = {"goals": [], "pens": [], "goalies": [], "skaters": []}
    meta = _segment(html_text, "meta")
    teams = re.findall(r'<div class="team">(.*?)</div>', meta, re.S)
    sides = []
    for blk in teams[:2]:
        m = re.search(r'href="(?:/women/team|/reports/team)/([^/"]+)/(\d+)"[^>]*>(.*?)</a>', blk, re.S)
        sc = re.search(r"<h2>\s*(\d+)\s*</h2>", blk)
        rec = re.findall(r"<h4>(.*?)</h4>", blk, re.S)
        sides.append({"name": _strip_tags(m.group(3)) if m else None, "chn_slug": m.group(1) if m else None,
                      "chn_id": m.group(2) if m else None, "score": int(sc.group(1)) if sc else None,
                      "record": _strip_tags(rec[-1]) if len(rec) > 1 else None})
    if len(sides) < 2:
        return None
    res["away"], res["home"] = sides[0], sides[1]
    dm = re.search(r"<h4>\s*[A-Z][a-z]+day,\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*</h4>", meta)
    try:
        res["date"] = datetime.strptime(dm.group(1), "%B %d, %Y").strftime("%Y-%m-%d") if dm else None
    except ValueError:
        res["date"] = None
    spans = [_strip_tags(s) for s in re.findall(r"<span>(.*?)</span>", meta, re.S)]
    res["game_type"], res["venue"], res["att"], res["refs"] = None, None, None, None
    for s in spans:
        if s.startswith("at "):
            res["venue"] = s[3:]
        elif s.startswith("Attendance"):
            res["att"] = _int(s.split(":", 1)[-1])
        elif s.startswith("Referees"):
            res["refs"] = s.split(":", 1)[-1].strip()
        elif not s.startswith("Asst.") and res["game_type"] is None and s:
            res["game_type"] = s
    # line scores
    for key in ("periods", "shots"):
        seg = _segment(html_text, "goals" if key == "periods" else "shots")
        rws = _rows_with_class(seg)
        hdr = [cells for cls, cells in rws if "stats-section" in cls]
        rows = [cells for cls, cells in rws if cells and "stats-section" not in cls]
        labels = [c["t"] for c in hdr[0][1:]] if hdr else []
        for side, cells in zip(("away", "home"), rows[:2]):
            vals = [_int(c["t"]) for c in cells[1:]]
            res[side]["abbr"] = res[side].get("abbr") or cells[0]["t"]
            if key == "periods":
                res[side]["periods"] = vals[:-1]
                if res[side]["score"] is None and vals:
                    res[side]["score"] = vals[-1]
            else:
                res[side]["shots"] = vals
        if key == "periods":
            res["period_labels"] = labels[:-1]
    labels = [str(x).upper() for x in (res.get("period_labels") or [])]
    res["so"] = any(l.startswith("SO") for l in labels)
    res["ot"] = sum(1 for l in labels if "OT" in l)
    rws = _rows_with_class(_segment(html_text, "pp"))
    hdr = next((c for cls, c in rws if c and c[0]["t"] == "Team"), None)
    if hdr:
        idx = {c["t"]: i for i, c in enumerate(hdr)}
        body = [c for cls, c in rws if c and c[0]["t"] != "Team" and "stats-section" not in cls]
        for side, r in zip(("away", "home"), body[:2]):
            g = lambda k: r[idx[k]]["t"] if k in idx and idx[k] < len(r) else ""
            res[side]["pen"], res[side]["pim"] = _pair(g("Pen-PIM"))
            res[side]["ppg"], res[side]["ppo"] = _pair(g("PPG-PPO"))
            res[side]["fow"], res[side]["fol"] = _pair(g("FOW-L"))
            res[side]["xg"] = _float(g("xG"))
    ab = {res["away"].get("abbr"): "away", res["home"].get("abbr"): "home"}
    # scoring
    per = 0
    for cls, cells in _rows_with_class(_segment(html_text, "scoring")):
        if "stats-section" in cls:
            if cells and cells[0]["t"] != "Scoring":
                per = _period_of(cells[0]["t"], per)
            continue
        if len(cells) < 5 or per == 99:
            continue
        team = ab.get(cells[0]["t"]) or ("away" if "vscore" in cls else "home" if "hscore" in cls else None)
        sit = cells[1]["t"].upper().replace(" ", "")
        k = next((j for j in range(2, len(cells)) if re.search(r"\(\d+\)\s*$", cells[j]["t"])), None)
        if k is None:
            k = next((j for j in range(2, len(cells)) if cells[j]["t"]), 2)
        sc_cell = cells[k]
        ms = re.match(r"^(.*?)\s*\((\d+)\)\s*$", sc_cell["t"])
        name, n = (ms.group(1), int(ms.group(2))) if ms else (sc_cell["t"], None)
        ast = cells[k + 1]["t"] if k + 1 < len(cells) else ""
        t_s = _mmss(cells[k + 2]["t"]) if k + 2 < len(cells) else None
        a = [x.strip() for x in ast.split(",") if x.strip() and x.strip().lower() not in ("unassisted",)]
        res["goals"].append({"per": per, "t": t_s, "team": team, "scorer": name,
                             "scorer_pid": _pid(sc_cell["a"]) or _pid([x for c in cells for x in c["a"]]),
                             "n": n, "a1": a[0] if a else None, "a2": a[1] if len(a) > 1 else None,
                             "sit": "+".join(x for x in re.split(r"[,/+]", sit) if x) if sit else "EV"})
    # penalties
    per = 0
    for cls, cells in _rows_with_class(_segment(html_text, "penalties")):
        if "stats-section" in cls:
            if cells and cells[0]["t"] != "Penalties":
                per = _period_of(cells[0]["t"], per)
            continue
        if len(cells) < 5:
            continue
        team = ab.get(cells[0]["t"]) or ("away" if "vscore" in cls else "home" if "hscore" in cls else None)
        res["pens"].append({"per": per, "t": _mmss(cells[4]["t"]), "team": team, "player": cells[1]["t"],
                            "min": _int(cells[2]["t"]), "inf": cells[3]["t"]})
    # goalies
    cur = None
    names = {res["away"]["name"]: "away", res["home"]["name"]: "home"}
    for cls, cells in _rows_with_class(_segment(html_text, "goalies")):
        if not cells:
            continue
        if "stats-header" in cls:
            cur = names.get(cells[0]["t"]) or ("away" if cur is None else "home")
            continue
        if "stats-section" in cls or len(cells) < 4:
            continue
        res["goalies"].append({"team": cur, "name": cells[0]["t"], "sv": _int(cells[1]["t"]), "ga": _int(cells[2]["t"]),
                               "sec": _mmss(cells[3]["t"]), "en": cells[0]["t"].upper() == "EMPTY NET"})
    # skaters
    seg = _segment(html_text, "playersums")
    for blk in re.findall(r'<div class="playersum">(.*?)</table>', seg, re.S):
        rws = _rows_with_class(blk)
        if not rws:
            continue
        hdr = rws[0][1]
        side = names.get(hdr[0]["t"]) if hdr else None
        idx = {c["t"]: i for i, c in enumerate(hdr)}
        for cls, r in rws[1:]:
            if len(r) < 4 or not r[0]["t"]:
                continue
            g = lambda k: r[idx[k]]["t"] if k in idx and idx[k] < len(r) else ""
            fw, fl = _pair(g("FOW-L"))
            res["skaters"].append({"team": side, "name": r[0]["t"], "g": _int(g("G")), "a": _int(g("A")),
                                   "pm": _int(g("+/-")), "sh": _int(g("Sh")), "toi": _mmss(g("TOI")),
                                   "pim": _int(g("PIM")), "fow": fw, "fol": fl})
    # line chart (forward lines / defence pairs / goalies), when present
    seg = _segment(html_text, "linechart")
    lines: dict[str, dict] = {}
    if seg:
        side, grp = None, None
        for tok in re.split(r"<[^>]+>", seg):
            x = _norm(_html.unescape(tok))
            if not x:
                continue
            if x in names:
                side = names[x]
                lines.setdefault(side, {"F": [], "D": [], "G": [], "X": []})
                continue
            low = x.lower()
            if low in ("forward", "forwards"):
                grp = "F"
                continue
            if low in ("defense", "defence", "defensemen"):
                grp = "D"
                continue
            if low in ("goalie", "goalies", "goaltenders", "goaltender"):
                grp = "G"
                continue
            if low == "extras":
                grp = "X"
                continue
            if side and grp and len(x) < 40 and re.match(r"^[A-Z][A-Za-z'.\- ]+( \([A-Z]\))?$", x):
                lines[side][grp].append(x)
    for v in lines.values():
        v["G"] = v["G"][:3]
    res["lines"] = {k: v for k, v in lines.items() if any(v.values())}
    return res


# ── day scoreboard ─────────────────────────────────────────────────────────────────────────────────────────

def parse_scoreboard(html_text: str) -> list[dict]:
    """Men's day scoreboard: [{gd, status, conf, away, home: {name, logo, score, record}, box}]."""
    out = []
    for m in re.finditer(r'<div id="game-(\d+)" class="game"[^>]*data-status="([^"]*)"(.*?)(?=<div id="game-\d+"|'
                         r'<div class="confGroup"|</main>|$)', html_text or "", re.S):
        gd, status, body = m.group(1), m.group(2), m.group(3)
        conf = None
        pre = html_text[:m.start()]
        mc = list(re.finditer(r"<h2>([^<]+)</h2>", pre))
        if mc:
            conf = _norm(_html.unescape(mc[-1].group(1)))
        teams = re.findall(r'<div class="game-team[^"]*">\s*<span>\s*<img src="/images/logos/([a-z_0-9]+)\.png"[^>]*>\s*'
                           r'<strong>([^<]+)</strong>\s*(?:<small>\(([^)]*)\)</small>)?(.*?)</div>', body, re.S)
        if len(teams) < 2:
            continue

        def tm(t):
            score = re.findall(r"<strong>(\d+)</strong>", t[3])
            return {"logo": t[0], "name": _norm(_html.unescape(t[1])), "record": t[2] or None,
                    "score": int(score[-1]) if score else None}
        box = re.search(r'href="(/box/final/[^"]+)"', body)
        out.append({"gd": gd, "status": status, "conf": conf, "away": tm(teams[0]), "home": tm(teams[1]),
                    "box": box.group(1) if box else None})
    return out


# ── team schedule (current season; future games too) ──────────────────────────────────────────────────────

def team_schedule_url(level: str, slug: str, tid: str | int) -> str:
    return f"{_pfx(level)}/schedules/team/{slug}/{tid}"
