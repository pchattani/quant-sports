"""
The College Football Data API (CFBD, https://api.collegefootballdata.com), key-gated and OFF.

CFBD needs a free API key (Bearer token). None is configured and none may be added (the user's standing rule:
no credentials anywhere; CONTRACT.md rules). Without `CFBD_API_KEY` in the environment every function here
returns None and logs once; nothing in the build depends on it. With a key, `get(path, params)` is a paced GET.

What each endpoint would add, where the models would plug it in, and what to check before use
(CFBD's own terms: free tier rate limits, attribution "Data provided by CollegeFootballData.com" requested;
much of its content is aggregated from third parties whose terms travel with the data):

  /lines?year=Y[&week=W]            historical lines from several books (consensus, Bovada, DraftKings, ESPN Bet,
                                    William Hill ...) with spread OPEN and close, totals and moneylines, back to
                                    about 2013. Would deepen the walk-forward backtest v the close (ESPN core odds
                                    have one line per book 2013-2016 and DraftKings open/close since about 2023;
                                    2017-2022 is thin) -> football/backtest. Terms: sportsbook lines are factual
                                    numbers, but check CFBD's redistribution clause before publishing them.
  /recruiting/players, /recruiting/teams, /talent
                                    recruit star ratings and team talent composites. The SOURCE is 247Sports
                                    (composite rankings): 247Sports' terms forbid reuse of its rankings, so under
                                    the data-terms rule these stay off the site even with a key unless 247's
                                    licence is confirmed; at most an internal, unpublished prior.
                                    -> preseason prior (football/team_strength) and transfer "grade".
  /player/returning                 returning production (share of last season's usage / PPA returning). We compute
                                    our own from ESPN box scores (allowed, labelled); CFBD's would be a cross-check.
  /player/portal?year=Y             transfer portal entries (origin, destination, eligibility, rating). The site
                                    infers moves from ESPN athlete ids instead ("inferred, not the official portal").
                                    Ratings inside are 247Sports' -> same restriction as recruiting.
  /ppa/*, /metrics/wp, /stats/game/advanced, /stats/season/advanced
                                    CFBD's own EPA-style predicted points added, havoc, success rates. Our EP/EPA is
                                    fitted on ESPN plays; CFBD's would validate it (calibration page cross-check).
  /plays, /drives, /games/players    play-by-play and box scores (overlap with ESPN; useful where ESPN's 2001-2005
                                    drives are sparse).
  /games/weather                    kickoff weather (temperature, wind, precipitation; a small totals feature).
  /venues, /teams/fbs?year=Y, /conferences
                                    venue coordinates (travel distance in the game model) and FBS membership by year
                                    (we take membership from ESPN standings per season).
  /rankings?year=Y                  AP / Coaches / CFP weekly polls (ESPN core has the same; cross-check only).
  /draft/picks                      NFL draft picks of college players (player value validation).

Turning it on (only if the user decides to): set CFBD_API_KEY in the environment of the build; nothing else.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE = "https://api.collegefootballdata.com"
HEADERS = {"User-Agent": "The Quant Campus (pchattani.github.io/the-quant-campus)"}
_warned = False
_lock = threading.Lock()
_last = 0.0
INTERVAL = 1.0


def api_key() -> str | None:
    k = os.environ.get("CFBD_API_KEY") or ""
    return k.strip() or None


def enabled() -> bool:
    return api_key() is not None


def _off() -> None:
    global _warned
    if not _warned:
        logger.info("CFBD is off: no CFBD_API_KEY configured (by design; see oddsmarkets/college/sources/cfbd.py)")
        _warned = True


def get(path: str, params: dict | None = None) -> Any:
    """GET a CFBD endpoint; None without a key or on any failure (never raises)."""
    global _last
    key = api_key()
    if not key:
        _off()
        return None
    with _lock:
        wait = _last + INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
    try:
        r = requests.get(f"{BASE}/{path.lstrip('/')}", params=params,
                         headers={**HEADERS, "Authorization": f"Bearer {key}"}, timeout=30)
        if r.status_code != 200:
            logger.info("cfbd %s answered %s", path, r.status_code)
            return None
        return r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.info("cfbd %s failed: %s", path, exc)
        return None


def lines(year: int, week: int | None = None, season_type: str = "regular") -> list | None:
    """Historical lines (several books, open and close) for a season; None without a key."""
    p: dict[str, Any] = {"year": int(year), "seasonType": season_type}
    if week is not None:
        p["week"] = int(week)
    return get("/lines", p)


def returning_production(year: int) -> list | None:
    return get("/player/returning", {"year": int(year)})


def portal(year: int) -> list | None:
    """Transfer portal entries (ratings inside come from 247Sports: not for publication; see the docstring)."""
    return get("/player/portal", {"year": int(year)})


def team_talent(year: int) -> list | None:
    """247Sports team talent composite (not for publication; see the docstring)."""
    return get("/talent", {"year": int(year)})


def weather(year: int, week: int | None = None) -> list | None:
    p: dict[str, Any] = {"year": int(year)}
    if week is not None:
        p["week"] = int(week)
    return get("/games/weather", p)


def venues() -> list | None:
    return get("/venues")
