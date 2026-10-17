"""
Transactions, injuries, the draft and player birth dates for The Quant Rink's valuation, trade ratings and fantasy
pages (oddsmarkets/nhl/analytics/moves.py, valuation.py, fantasy.py). Raw caches under <RINK_RAW>/moves/ (default
data/nhl/moves/, not committed).

Endpoints (verified 16 Oct 2026):
  ESPN  https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/transactions?season=<calendar year>&limit=200&page=<n>
        {"count","pageCount","pageIndex","transactions":[{"date","description","team":{"id","abbreviation",...}}]}:
        free text, one row per club per day (each side of a trade is its own row), newest first. NHL api-web has no
        transactions endpoint (/v1/transactions answers 404).
  ESPN  https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries
        {"injuries":[{"displayName" (club), "injuries":[{"status","date","athlete":{"displayName",...},"details"?,
        "shortComment","longComment"}]}]}: only the status, its date and the injury type are kept (the comments are
        a news provider's text and are not stored or shown).
  NHL   https://records.nhl.com/site/api/draft?cayenneExp=draftYear=<Y>
        every pick: playerId, overallPickNumber, roundNumber, pickInRound, triCode, birthDate, position.
  NHL   https://api-web.nhle.com/v1/player/<id>/landing     birthDate, position, draftDetails (missing birth dates).
Not used (terms): CapFriendly / PuckPedia / Spotrac (contracts, cap), fantasy platforms' ownership, ADP or rankings.

Pacing: ESPN 0.5 s between calls, records.nhl.com 0.5 s, api-web 0.25 s. Completed drafts and player landings are
cached permanently; the transaction pages of a past calendar year are fetched once; the current year's first pages are
refreshed by the hourly build (`refresh`, a handful of calls; silently skipped offline).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ._client import BudgetExhausted, Client

logger = logging.getLogger(__name__)

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
DRAFT = "https://records.nhl.com/site/api/draft"
WEB = "https://api-web.nhle.com/v1"
INTERVALS = {"espn.com": 0.5, "records.nhl.com": 0.5, "nhle.com": 0.25}
PAGE = 200
INJURY_TTL_H = 1.0


def moves_dir() -> Path:
    root = os.environ.get("RINK_RAW") or str(Path(__file__).resolve().parents[3] / "data" / "nhl")
    return Path(root) / "moves"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def client(budget: int = 60) -> Client:
    return Client(budget=budget, interval=0.5, intervals=INTERVALS, name="rink-moves", retries=2)


# ---------------------------------------------------------------------------------------------- transactions

def compact_tx(t: dict) -> list | None:
    """[date (YYYY-MM-DD), ESPN team id, ESPN abbreviation, description]."""
    if not isinstance(t, dict):
        return None
    d = str(t.get("date") or "")[:10]
    tm = t.get("team") or {}
    desc = str(t.get("description") or "").strip()
    if not d or not desc:
        return None
    return [d, str(tm.get("id") or ""), str(tm.get("abbreviation") or ""), desc]


def tx_path(year: int) -> Path:
    return moves_dir() / f"espn_tx_{int(year)}.json"


def load_tx(year: int) -> dict:
    return _read(tx_path(year)) or {"year": int(year), "rows": [], "pages": {}, "complete": False}


def _merge(rows: list[list], new: list[list]) -> list[list]:
    seen = {tuple(r) for r in rows}
    out = list(rows)
    for r in new:
        if tuple(r) not in seen:
            seen.add(tuple(r))
            out.append(r)
    out.sort(key=lambda r: (r[0], r[2], r[3]), reverse=True)
    return out


def fetch_tx_year(year: int, c: Client | None = None, max_pages: int | None = None, force: bool = False) -> dict:
    """Fetch the calendar year's transaction pages (all of them, or the first `max_pages`) and merge them into the
    cache. A past year whose pages were all fetched once is not fetched again unless `force`."""
    year = int(year)
    cur = load_tx(year)
    if cur.get("complete") and not force and max_pages is None:
        return cur
    c = c or client()
    rows = list(cur.get("rows") or [])
    page, n_pages, got = 1, None, 0
    while True:
        if max_pages is not None and page > max_pages:
            break
        d = c.get(f"{ESPN_SITE}/transactions", {"season": year, "limit": PAGE, "page": page})
        if not isinstance(d, dict):
            break
        n_pages = int(d.get("pageCount") or 0)
        new = [x for x in (compact_tx(t) for t in d.get("transactions") or []) if x]
        rows = _merge(rows, new)
        got += 1
        if page >= n_pages or not new:
            break
        page += 1
    if got:
        complete = bool(cur.get("complete")) or (max_pages is None and n_pages is not None and page >= n_pages)
        if year < datetime.now(timezone.utc).year and max_pages is None and n_pages is not None and page >= n_pages:
            complete = True
        cur = {"year": year, "rows": rows, "complete": complete, "page_count": n_pages, "fetched_at": _now(),
               "source": "ESPN public site API (transactions)"}
        _write(tx_path(year), cur)
    return cur


def refresh(today: date | None = None, pages: int = 2, c: Client | None = None, months: int = 13) -> dict:
    """Hourly: the current calendar year's first `pages` pages (newest first); the previous year's full set once
    (the 12-month window reaches back into it). Offline or failing: returns what is on disk."""
    today = today or datetime.now(timezone.utc).date()
    c = c or client()
    out = {"calls": 0, "years": {}}
    try:
        cur = load_tx(today.year)
        if not cur.get("rows"):
            fetch_tx_year(today.year, c)
        else:
            fetch_tx_year(today.year, c, max_pages=pages)
        if months >= today.month:
            prev = load_tx(today.year - 1)
            if not prev.get("complete"):
                fetch_tx_year(today.year - 1, c)
    except BudgetExhausted:
        pass
    except Exception as exc:                                     # noqa: BLE001 - offline / API change: keep the cache
        logger.warning("transactions refresh failed: %s", exc)
    out["calls"] = c.used
    for y in (today.year - 1, today.year):
        out["years"][y] = len(load_tx(y).get("rows") or [])
    return out


def tx_rows(years: list[int]) -> list[list]:
    rows: list[list] = []
    for y in years:
        rows += load_tx(y).get("rows") or []
    return rows


# ---------------------------------------------------------------------------------------------- injuries

def injuries_path() -> Path:
    return moves_dir() / "espn_injuries.json"


def compact_injuries(d: dict) -> list[list]:
    """[[ESPN club name, player name, status, date, type]]: status and type only (no comments)."""
    out = []
    for team in (d or {}).get("injuries") or []:
        tname = team.get("displayName") or ""
        tid = str(team.get("id") or "")
        for inj in team.get("injuries") or []:
            a = inj.get("athlete") or {}
            det = inj.get("details") or {}
            typ = det.get("type") if isinstance(det, dict) else None
            ret = det.get("returnDate") if isinstance(det, dict) else None
            out.append([tid, tname, a.get("displayName") or " ".join(x for x in (a.get("firstName"), a.get("lastName")) if x),
                        inj.get("status") or "", str(inj.get("date") or "")[:10], typ, str(ret)[:10] if ret else None])
    return out


def injuries(refresh_now: bool = True, c: Client | None = None) -> dict:
    """{"fetched_at","rows":[[espn team id, club, name, status, date, type, return date]]}; refreshed at most hourly."""
    p = injuries_path()
    cur = _read(p) or {}
    fresh = False
    try:
        at = datetime.strptime(str(cur.get("fetched_at")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        fresh = (datetime.now(timezone.utc) - at).total_seconds() < INJURY_TTL_H * 3600
    except ValueError:
        fresh = False
    if refresh_now and not fresh:
        try:
            c = c or client(5)
            d = c.get(f"{ESPN_SITE}/injuries")
            if isinstance(d, dict) and d.get("injuries") is not None:
                cur = {"fetched_at": _now(), "rows": compact_injuries(d), "source": "ESPN public site API (injuries)"}
                _write(p, cur)
        except Exception as exc:                                 # noqa: BLE001
            logger.warning("injuries refresh failed: %s", exc)
    return cur or {"rows": []}


# ---------------------------------------------------------------------------------------------- draft

DRAFT_COLS = ["year", "overall", "round", "in_round", "pid", "name", "team", "dob", "pos"]


def draft_path(year: int) -> Path:
    return moves_dir() / "draft" / f"draft_{int(year)}.json"


def fetch_draft(year: int, c: Client | None = None, today: date | None = None) -> dict | None:
    """Every pick of a draft (cached permanently once the draft has happened)."""
    year = int(year)
    p = draft_path(year)
    cur = _read(p)
    today = today or datetime.now(timezone.utc).date()
    if cur and cur.get("rows") and (cur.get("final") or year < today.year or (year == today.year and today.month >= 8)):
        return cur
    c = c or client()
    d = c.get(DRAFT, {"cayenneExp": f"draftYear={year}"})
    if not isinstance(d, dict) or not d.get("data"):
        return cur
    rows = []
    for r in d["data"]:
        rows.append([year, r.get("overallPickNumber"), r.get("roundNumber"), r.get("pickInRound"),
                     str(r["playerId"]) if r.get("playerId") else None, r.get("playerName"), r.get("triCode"),
                     r.get("birthDate"), r.get("position")])
    rows.sort(key=lambda r: (r[1] or 9999))
    out = {"year": year, "cols": DRAFT_COLS, "rows": rows, "fetched_at": _now(),
           "final": year < today.year or (year == today.year and today.month >= 8), "source": "records.nhl.com draft"}
    _write(p, out)
    return out


def drafts(years: list[int], fetch: bool = True, c: Client | None = None) -> dict[int, dict]:
    out = {}
    for y in years:
        d = _read(draft_path(y))
        if (not d or not d.get("rows")) and fetch:
            try:
                d = fetch_draft(y, c)
            except BudgetExhausted:
                break
            except Exception as exc:                             # noqa: BLE001
                logger.warning("draft %s failed: %s", y, exc)
        if d and d.get("rows"):
            out[int(y)] = d
    return out


# ---------------------------------------------------------------------------------------------- player landings

def landing_path() -> Path:
    return moves_dir() / "landings.json"


def landings(pids: list[str], fetch: bool = True, c: Client | None = None, max_calls: int = 40) -> dict[str, dict]:
    """{pid: {"dob","pos","name","draft":[year, round, overall, team]}} from api-web player landings, cached."""
    p = landing_path()
    cache = _read(p) or {}
    todo = [str(x) for x in pids if str(x) not in cache]
    if fetch and todo:
        c = c or client(max_calls + 5)
        n = 0
        try:
            for pid in todo[:max_calls]:
                d = c.get(f"{WEB}/player/{pid}/landing")
                n += 1
                if not isinstance(d, dict):
                    cache[pid] = {"missing": True}
                    continue
                dd = d.get("draftDetails") or {}
                nm = " ".join(x for x in ((d.get("firstName") or {}).get("default"), (d.get("lastName") or {}).get("default")) if x)
                cache[pid] = {"dob": d.get("birthDate"), "pos": d.get("position"), "name": nm or None,
                              "draft": [dd.get("year"), dd.get("round"), dd.get("overallPick"), dd.get("teamAbbrev")] if dd else None}
        except BudgetExhausted:
            pass
        except Exception as exc:                                 # noqa: BLE001
            logger.warning("player landings failed: %s", exc)
        if n:
            _write(p, cache)
        time.sleep(0)
    return {k: v for k, v in cache.items() if k in set(map(str, pids))}


# ---------------------------------------------------------------------------------------------- NHL player search

SEARCH = "https://search.d3.nhle.com/api/v1/search/player"
SEARCH_RETRY_DAYS = 7


def search_path() -> Path:
    return moves_dir() / "search.json"


def search(names: list[str], fetch: bool = True, c: Client | None = None, max_calls: int = 20) -> dict[str, list[dict]]:
    """{name: [{"pid","name","pos","team","last"}]} from the NHL's public player search (nhl.com's own search API), for
    names the stores, players index and draft records do not know (prospects in trades). Cached; a name with no answer
    is asked again after SEARCH_RETRY_DAYS days."""
    p = search_path()
    cache = _read(p) or {}
    now = datetime.now(timezone.utc)
    todo = []
    for n in dict.fromkeys(names):
        e = cache.get(n)
        if e is None:
            todo.append(n)
        elif not e.get("rows"):
            try:
                at = datetime.strptime(str(e.get("at")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if (now - at).days >= SEARCH_RETRY_DAYS:
                    todo.append(n)
            except ValueError:
                todo.append(n)
    if fetch and todo:
        c = c or client(max_calls + 2)
        done = 0
        try:
            for n in todo[:max_calls]:
                d = c.get(SEARCH, {"culture": "en-us", "limit": 10, "q": n})
                done += 1
                if not isinstance(d, list):
                    continue
                cache[n] = {"at": _now(), "rows": [{"pid": str(r.get("playerId")), "name": r.get("name"), "pos": r.get("positionCode"),
                                                    "team": r.get("lastTeamAbbrev") or r.get("teamAbbrev"), "last": r.get("lastSeasonId")}
                                                   for r in d if isinstance(r, dict) and r.get("playerId")]}
        except BudgetExhausted:
            pass
        except Exception as exc:                                 # noqa: BLE001
            logger.warning("player search failed: %s", exc)
        if done:
            _write(p, cache)
    return {n: (cache.get(n) or {}).get("rows") or [] for n in names}
