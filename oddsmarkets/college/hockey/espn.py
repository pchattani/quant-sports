"""
ESPN's public JSON for college hockey (men `mch`: hockey/mens-college-hockey, women `wch`: hockey/womens-college-hockey).

ESPN carries scores only for college hockey: per-day scoreboards (teams, start time, status, period line score,
venue, attendance, neutral flag, postseason notes, the USCHO poll rank), a team list, and the USCHO polls. Summaries
have no box score and no play-by-play (probed 30 Oct 2026). It is the fallback schedule and the cross-check of CHN
results, and the only source when CHN is switched off (`sources/chn.py` CHN_ENABLED=0).

Raw days are kept compact in data/college/hockey/espn/<L>/<S>.json.gz {"days": {YYYYMMDD: [EVENT]}, "teams": {...},
"polls": {...}, "fetched": {YYYYMMDD: iso}}. Uses the Campus ESPN `Client` (paced, budgeted, back-off).
"""
from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..sources import espn as cc_espn

logger = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports/hockey"
CORE = "https://sports.core.api.espn.com/v2/sports/hockey/leagues"
LEAGUE = {"mch": "mens-college-hockey", "wch": "womens-college-hockey"}
ROOT = Path(__file__).resolve().parents[3]


def raw_dir() -> Path:
    return Path(os.environ.get("CAMPUS_RAW") or (ROOT / "data" / "college")) / "hockey" / "espn"


def raw_path(level: str, season: int) -> Path:
    return raw_dir() / level / f"{int(season)}.json.gz"


def load_raw(level: str, season: int) -> dict:
    p = raw_path(level, season)
    if not p.exists():
        return {"days": {}, "fetched": {}, "polls": {}}
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def save_raw(level: str, season: int, d: dict) -> None:
    p = raw_path(level, season)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(d, fh, separators=(",", ":"))
    os.replace(tmp, p)


def season_window(season: int) -> tuple[date, date]:
    """1 Sep of season - 1 to 20 Apr of season (2020-21 ran late into April)."""
    return date(int(season) - 1, 9, 25), date(int(season), 4, 20)


def _int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def compact_event(e: dict) -> dict | None:
    try:
        c = e["competitions"][0]
    except (KeyError, IndexError):
        return None
    st = (c.get("status") or e.get("status") or {}).get("type") or {}
    state = st.get("state")
    status = {"pre": "pre", "in": "in", "post": "post"}.get(state, "pre")
    if st.get("name") in ("STATUS_POSTPONED",):
        status = "postponed"
    if st.get("name") in ("STATUS_CANCELED", "STATUS_CANCELLED"):
        status = "canceled"
    out = {"id": str(e.get("id")), "date": e.get("date"), "status": status, "detail": st.get("shortDetail"),
           "stype": (e.get("season") or {}).get("type"), "neutral": bool(c.get("neutralSite")),
           "conf": c.get("conferenceCompetition"), "venue": (c.get("venue") or {}).get("fullName"),
           "city": ((c.get("venue") or {}).get("address") or {}).get("city"),
           "state": ((c.get("venue") or {}).get("address") or {}).get("state"),
           "att": c.get("attendance") or None, "tv": c.get("timeValid", True),
           "notes": [n.get("headline") for n in (c.get("notes") or []) if n.get("headline")],
           "period": (c.get("status") or {}).get("period"), "clock": (c.get("status") or {}).get("displayClock")}
    for t in c.get("competitors") or []:
        side = "h" if t.get("homeAway") == "home" else "a"
        tm = t.get("team") or {}
        out[side] = {"id": str(tm.get("id")), "name": tm.get("displayName"), "loc": tm.get("location"),
                     "abbr": tm.get("abbreviation"), "short": tm.get("shortDisplayName"),
                     "score": _int(t.get("score")) if status in ("post", "in") else None,
                     "ls": [_int(x.get("value")) for x in (t.get("linescores") or [])],
                     "rank": ((t.get("curatedRank") or {}).get("current")),
                     "winner": t.get("winner")}
    if "h" not in out or "a" not in out:
        return None
    return out


def scoreboard(c: cc_espn.Client, level: str, ymd: str) -> list[dict] | None:
    d = c.get(f"{SITE}/{LEAGUE[level]}/scoreboard", {"dates": ymd, "limit": 500})
    if d is None:
        return None
    return [x for x in (compact_event(e) for e in d.get("events") or []) if x]


def teams(c: cc_espn.Client, level: str) -> list[dict]:
    d = c.get(f"{SITE}/{LEAGUE[level]}/teams", {"limit": 500}) or {}
    out = []
    for lg in (d.get("sports") or [{}])[0].get("leagues") or []:
        for t in lg.get("teams") or []:
            tm = t.get("team") or {}
            out.append({"id": str(tm.get("id")), "name": tm.get("displayName"), "loc": tm.get("location"),
                        "nick": tm.get("name"), "abbr": tm.get("abbreviation"), "short": tm.get("shortDisplayName"),
                        "color": tm.get("color"), "alt": tm.get("alternateColor"), "active": tm.get("isActive")})
    return out


def rankings_now(c: cc_espn.Client, level: str) -> list[dict]:
    d = c.get(f"{SITE}/{LEAGUE[level]}/rankings") or {}
    out = []
    for r in d.get("rankings") or []:
        out.append({"name": r.get("name"), "date": r.get("date"),
                    "ranks": [{"rank": x.get("current"), "prev": x.get("previous"), "team": str((x.get("team") or {}).get("id")),
                               "points": x.get("points"), "fpv": x.get("firstPlaceVotes"), "record": x.get("recordSummary")}
                              for x in r.get("ranks") or []]})
    return out


def fetch_season(c: cc_espn.Client, level: str, season: int, refresh_recent_days: int = 0,
                 today: date | None = None) -> dict:
    """Every day of a season window not yet fetched (plus the last `refresh_recent_days` and the next 10 days for the
    current season). Saves as it goes."""
    raw = load_raw(level, season)
    lo, hi = season_window(season)
    today = today or date.today()
    days = [(lo + timedelta(days=i)) for i in range((hi - lo).days + 1)]
    n = 0
    now = datetime.now(timezone.utc)
    for d in days:
        ymd = d.strftime("%Y%m%d")
        got = raw["fetched"].get(ymd)
        age_d = (now - datetime.strptime(got, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).days if got else None
        recent = refresh_recent_days and (today - timedelta(days=refresh_recent_days) <= d <= today + timedelta(days=10))
        future_stale = d > today and (age_d is None or age_d >= 3)
        past_settle = got and d <= today and got[:10] <= (d + timedelta(days=1)).isoformat()   # fetched before it settled
        if got and not recent and not future_stale and not past_settle:
            continue
        evs = scoreboard(c, level, ymd)
        if evs is None:
            continue
        if evs:
            raw["days"][ymd] = evs
        else:
            raw["days"].pop(ymd, None)
        raw["fetched"][ymd] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        n += 1
        if n % 20 == 0:
            save_raw(level, season, raw)
    save_raw(level, season, raw)
    return raw


def all_events(raw: dict) -> list[dict]:
    seen, out = set(), []
    for ymd in sorted(raw.get("days") or {}):
        for e in raw["days"][ymd]:
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            out.append(e)
    return out
