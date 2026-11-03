"""
ESPN's public rugby JSON for The Quant Scrum (the only source; World Rugby's own feeds are out on their terms).

Endpoints (league slugs in config.COMPS; probed 2 Nov 2026)
  site  https://site.api.espn.com/apis/site/v2/sports/rugby/<slug>/scoreboard?dates=YYYY&limit=1000
          every event of a calendar year in the competition. competitors[].statistics carries about 200 team
          stats per match (possession and territory by half, carries over the gain line, rucks, mauls, scrums,
          lineouts with steals, penalties by offence, turnovers by kind, kicks, cards); competitions[0].details
          are the key moments (tries, conversions, penalty goals, drop goals, cards, substitutions) with the
          minute and the running score; neutralSite and venue
        https://site.api.espn.com/apis/site/v2/sports/rugby/<slug>/summary?event=ID
          rosters (the matchday 23: jersey, position, captain, 26 stats per player), boxscore.players (athlete
          date of birth, height, weight, birth country, position), header, gameInfo (venue, attendance)
  No odds are published for rugby (pickcenter is empty).

The client is paced (`interval` seconds between any two calls, 2 s by default), retries with back-off on 429,
403 and 5xx, caps calls with a budget (`BudgetExhausted`), and returns None, never an exception, on a bad answer.
Every answer is cached gzipped under data/rugby/raw (raw never reaches the public build).
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import requests

from .. import config

logger = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports/rugby"
CORE = "https://sports.core.api.espn.com/v2/sports/rugby"
HEADERS = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
TIMEOUT = 30

# Team stats kept per match (scoreboard names -> our keys). Shares are 0-1 in ESPN; kept as given.
TEAM_KEYS = {
    "possession": "poss", "pcPossessionFirst": "poss1", "pcPossessionSecond": "poss2",
    "territory": "terr", "pcTerritoryFirst": "terr1", "pcTerritorySecond": "terr2",
    "ballPossessionLast10Mins": "poss_l10", "territoryLast10Mins": "terr_l10",
    "metres": "metres", "runs": "carries", "carriesCrossedGainLine": "gainline", "carriesNotMadeGainLine": "no_gainline",
    "cleanBreaks": "breaks", "defendersBeaten": "beaten", "offload": "offloads", "passes": "passes",
    "tackles": "tackles", "missedTackles": "missed", "tackleSuccess": "tackle_pct",
    "rucksWon": "rucks_won", "rucksTotal": "rucks", "rucksLost": "rucks_lost",
    "maulsWon": "mauls_won", "maulsTotal": "mauls", "maulingMetres": "maul_m", "maulsWonTry": "maul_tries",
    "scrumsWon": "scrums_won", "scrumsTotal": "scrums", "scrumsWonPenalty": "scrum_pens_won",
    "scrumsLostPenalty": "scrum_pens_lost", "scrumsReset": "scrum_resets",
    "lineoutsWon": "lineouts_won", "totalLineouts": "lineouts", "lineoutWonSteal": "lineout_steals",
    "lineoutsLost": "lineouts_lost",
    "turnoverWon": "to_won", "turnoversConceded": "to_conc", "turnoverKnockOn": "knock_ons",
    "handlingError": "handling_err", "turnoverOwnHalf": "to_own_half",
    "penaltiesConceded": "pens", "totalFreeKicksConceded": "free_kicks", "penaltyConcededOwnHalf": "pens_own_half",
    "penaltyConcededOffside": "pens_offside", "penaltyConcededHighTackle": "pens_high",
    "penaltyConcededKillingRuck": "pens_ruck", "penaltyConcededScrumOffence": "pens_scrum",
    "yellowCards": "yc", "redCards": "rc",
    "tries": "tries", "tryAssists": "try_assists", "conversionGoals": "cons", "missedConversionGoals": "cons_missed",
    "penaltyGoals": "pen_goals", "missedPenaltyGoals": "pen_goals_missed", "dropGoalsConverted": "drops",
    "penaltyTries": "pen_tries", "kickPercentSuccess": "kick_pct",
    "kicksFromHand": "kicks", "kickFromHandMetres": "kick_m", "kickInTouch": "kick_touch",
    "kickPossessionRetained": "kick_retained", "collectionFromKick": "kick_collect",
    "restartsWon": "restarts_won", "restartOwnPlayer": "restart_own",
    "points": "pts", "tryBonusPoints": "try_bp", "losingBonusPoints": "losing_bp",
}
# Player stats (summary rosters; 26 per player). Our keys in PLAYER_KEYS order.
PLAYER_KEYS = {
    "points": "pts", "tries": "tries", "tryAssists": "ta", "conversionGoals": "con", "penaltyGoals": "pg",
    "dropGoalsConverted": "dg", "kickPercentSuccess": "kpct", "metres": "m", "runs": "car", "cleanBreaks": "cb",
    "defendersBeaten": "db", "offload": "off", "passes": "pas", "tackles": "tk", "missedTackles": "mt",
    "lineoutsWon": "lo", "totalLineouts": "lot", "rucksWon": "rk", "maulsWon": "ml", "turnoversConceded": "toc",
    "turnoverKnockOn": "ko", "penaltiesConceded": "pc", "totalFreeKicksConceded": "fk", "yellowCards": "yc",
    "redCards": "rc", "kicksFromHand": "kfh",
}
PLAYER_COLS = list(PLAYER_KEYS.values())
EVENT_TYPES = {"try": "try", "penalty try": "try", "conversion": "con", "penalty goal": "pg", "penalty": "pg",
               "drop goal": "dg", "yellow card": "yc", "red card": "rc", "substitute on": "on",
               "player substituted": "off"}


class BudgetExhausted(RuntimeError):
    pass


def raw_root() -> Path:
    return Path(os.environ.get("RUGBY_RAW") or (Path(__file__).resolve().parents[3] / "data" / "rugby" / "raw"))


class Client:
    """Paced GET with retries and back-off; `budget` caps network calls per run (cache hits are free)."""

    def __init__(self, budget: int = 2000, interval: float = 2.0, retries: int = 4):
        self.budget, self.interval, self.retries = budget, interval, retries
        self.used = self.failures = self.throttled = self.hits = 0
        self._next = 0.0
        self._pause_until = 0.0
        self._lock = threading.Lock()
        self.session = requests.Session()

    def _slot(self) -> None:
        with self._lock:
            if self.used >= self.budget:
                raise BudgetExhausted(f"ESPN budget of {self.budget} calls spent")
            now = time.monotonic()
            start = max(now, self._next, self._pause_until)
            self._next = start + self.interval
            self.used += 1
        wait = start - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _pause(self, s: float) -> None:
        with self._lock:
            self._pause_until = max(self._pause_until, time.monotonic() + s)

    def get(self, url: str, params: dict | None = None) -> dict | None:
        for attempt in range(self.retries):
            self._slot()
            try:
                r = self.session.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException as exc:
                logger.warning("espn %s %s: %s (attempt %d)", url, params, exc, attempt + 1)
                self._pause(5 * (attempt + 1))
                continue
            if r.status_code in (429, 403) or r.status_code >= 500:
                if r.status_code in (429, 403):
                    self.throttled += 1
                back = (int(r.headers.get("Retry-After") or 0) or 60 * (attempt + 1)) if r.status_code in (429, 403) \
                    else 10 * (attempt + 1)
                logger.warning("espn %s %s answered %s; pausing %ds", url, params, r.status_code, back)
                self._pause(back)
                continue
            if r.status_code != 200:
                self.failures += 1
                return None
            try:
                d = r.json()
            except ValueError:
                self.failures += 1
                return None
            return d if isinstance(d, dict) else None
        self.failures += 1
        return None

    # cached fetchers ---------------------------------------------------------------------------------------
    def cached(self, path: Path, url: str, params: dict | None, refresh: bool = False) -> dict | None:
        if path.exists() and not refresh:
            try:
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    self.hits += 1
                    return json.load(fh)
            except (OSError, ValueError):
                pass
        d = self.get(url, params)
        if d is not None:
            write_gz(path, d)
        return d


def write_gz(p: Path, obj: Any) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


def scoreboard(c: Client, slug: str, year: int, refresh: bool = False) -> dict | None:
    p = raw_root() / "sb" / str(slug) / f"{int(year)}.json.gz"
    return c.cached(p, f"{SITE}/{slug}/scoreboard", {"dates": int(year), "limit": 1000}, refresh)


def summary(c: Client, slug: str, event_id: str, refresh: bool = False) -> dict | None:
    p = raw_root() / "summary" / str(event_id)[-2:] / f"{event_id}.json.gz"
    return c.cached(p, f"{SITE}/{slug}/summary", {"event": str(event_id)}, refresh)


def athlete(c: Client, athlete_id: str, refresh: bool = False) -> dict | None:
    """The core API's athlete record (date of birth, height, weight, birthplace, position): the bio the summary's
    box score lacks for about 40% of the players (every Nations Championship 2026 player, most tier-two and three
    players). Cached under raw/athletes/<nn>/<id>.json.gz."""
    p = raw_root() / "athletes" / str(athlete_id)[-2:] / f"{athlete_id}.json.gz"
    return c.cached(p, f"{CORE}/athletes/{athlete_id}", None, refresh)


def athlete_cached(athlete_id: str) -> dict | None:
    p = raw_root() / "athletes" / str(athlete_id)[-2:] / f"{athlete_id}.json.gz"
    if not p.exists():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def parse_athlete(d: dict | None) -> dict:
    """Bio fields in the store's athlete shape: dob, ht_cm, wt_kg, pos, born, city (empty dict when nothing)."""
    if not isinstance(d, dict):
        return {}
    out = {}
    if d.get("dateOfBirth"):
        out["dob"] = str(d["dateOfBirth"])[:10]
    h, w = _num(d.get("height")), _num(d.get("weight"))
    if h and 50 <= h <= 90:                                   # inches
        out["ht_cm"] = round(h * 2.54)
    if w and 120 <= w <= 400:                                 # pounds
        out["wt_kg"] = round(w * 0.4536)
    pos = d.get("position") or {}
    if pos.get("abbreviation"):
        out["pos"] = pos["abbreviation"]
    bp = d.get("birthPlace") or {}
    if bp.get("country"):
        out["born"] = bp["country"]
    if bp.get("city"):
        out["city"] = bp["city"]
    return out


def summary_cached(event_id: str) -> bool:
    return (raw_root() / "summary" / str(event_id)[-2:] / f"{event_id}.json.gz").exists()


# ── parsers ─────────────────────────────────────────────────────────────────────────────────────────────────

def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def _int(x) -> int | None:
    v = _num(x)
    return None if v is None else int(round(v))


def _stat_map(stats, keys: dict) -> dict:
    out = {}
    for s in stats or []:
        k = keys.get(s.get("name"))
        if not k:
            continue
        v = _num(s.get("value") if s.get("value") is not None else s.get("displayValue"))
        if v is None:
            continue
        out[k] = round(v, 3) if abs(v - round(v)) > 1e-9 else int(round(v))
    return out


def _team(t: dict) -> dict:
    t = t or {}
    return {"id": str(t.get("id") or ""), "name": t.get("displayName") or t.get("name") or "",
            "abbr": t.get("abbreviation") or "", "colour": ("#" + t["color"]) if t.get("color") else None,
            "alt": ("#" + t["alternateColor"]) if t.get("alternateColor") else None}


def _minute(det: dict) -> int | None:
    clk = det.get("clock") or {}
    v = _num(clk.get("value"))
    if v is not None:
        return int(v // 60) + 1 if v > 0 else 0
    s = str(clk.get("displayValue") or "").replace("'", "").split("+")[0]
    return _int(s)


def parse_event(ev: dict, slug: str) -> dict | None:
    """One scoreboard event as a match row (fixtures and results). Team stats only for finished matches."""
    try:
        comp = (ev.get("competitions") or [{}])[0]
        cs = comp.get("competitors") or []
        home = next((x for x in cs if x.get("homeAway") == "home"), None)
        away = next((x for x in cs if x.get("homeAway") == "away"), None)
        if not home or not away:
            return None
    except (AttributeError, IndexError, TypeError):
        return None
    st = ((comp.get("status") or ev.get("status") or {}).get("type") or {})
    state = st.get("state") or "pre"
    status = {"pre": "pre", "in": "live", "post": "final"}.get(state, "pre")
    if status == "final" and not st.get("completed", True):
        status = "off"                                            # postponed / cancelled / abandoned
    if (st.get("name") or "") in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED"):
        status = "off"
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    row = {
        "id": str(ev.get("id")), "comp": config.comp(slug)["key"], "slug": str(slug),
        "season": ((ev.get("season") or {}).get("year")), "date": ev.get("date") or comp.get("date"),
        "status": status, "neutral": bool(comp.get("neutralSite")),
        "venue": {"name": venue.get("fullName") or "", "city": addr.get("city") or "", "country": addr.get("country") or ""},
        "home": _team(home.get("team")), "away": _team(away.get("team")),
        "note": " ".join(n.get("headline") or "" for n in comp.get("notes") or [] if n.get("headline")).strip(),
        "season_slug": (ev.get("season") or {}).get("slug") or "",
    }
    if status in ("final", "live"):
        row["hs"], row["as"] = _int(home.get("score")), _int(away.get("score"))
        def halves(x):
            ls = [l for l in x.get("linescores") or [] if (_int(l.get("period")) or 0) in (1, 2)]
            return [_int(l.get("value") if l.get("value") is not None else l.get("displayValue")) for l in ls]
        row["hh"], row["ah"] = halves(home), halves(away)
        if status == "final":
            row["hstat"] = _stat_map(home.get("statistics"), TEAM_KEYS)
            row["astat"] = _stat_map(away.get("statistics"), TEAM_KEYS)
            row["events"] = parse_details(comp.get("details"), row["home"]["id"])
    return row


PTS = {"try": 5, "con": 2, "pg": 3, "dg": 3}


def parse_details(details, home_id: str) -> list[list]:
    """Key moments: [[minute, type, side, athlete_id, name, home_score, away_score]]. The running score comes from
    the feed when it has one (summary header), else it is counted from the scoring events (a penalty try is 7)."""
    evs, hs, as_ = [], 0, 0
    for d in details or []:
        text = str(((d.get("type") or {}).get("text") or "")).lower()
        ty = EVENT_TYPES.get(text)
        if not ty:
            continue
        parts = d.get("participants") or []
        ath = ((parts[0] or {}).get("athlete") or {}) if parts else {}
        if not ath and d.get("athletesInvolved"):
            ath = d["athletesInvolved"][0] or {}
        side = "h" if str(((d.get("team") or {}).get("id")) or "") == str(home_id) else "a"
        pts = 7 if text == "penalty try" else PTS.get(ty, 0)
        if side == "h":
            hs += pts
        else:
            as_ += pts
        h2, a2 = _int(d.get("homeScore")), _int(d.get("awayScore"))
        if h2 is not None and a2 is not None:
            hs, as_ = h2, a2
        evs.append([_minute(d), ty, side, str(ath.get("id") or ""), ath.get("displayName") or "", hs, as_])
    return evs


def parse_scoreboard(d: dict | None, slug: str) -> list[dict]:
    out = []
    for ev in (d or {}).get("events") or []:
        r = parse_event(ev, slug)
        if r:
            out.append(r)
    return out


def parse_summary(d: dict | None) -> dict | None:
    """The matchday 23 per side and the athletes seen: {"lineups": {"h": [...], "a": [...]}, "athletes": {id: {...}},
    "venue", "attendance"}. A lineup row: [athlete_id, jersey, pos, starter, captain, stats{...}]. Starters are
    jerseys 1-15 (ESPN's `starter` flag is unreliable in rugby feeds)."""
    if not isinstance(d, dict):
        return None
    hdr = ((d.get("header") or {}).get("competitions") or [{}])[0]
    home_id = next((str((c.get("team") or {}).get("id")) for c in hdr.get("competitors") or [] if c.get("homeAway") == "home"), None)
    out = {"lineups": {"h": [], "a": []}, "athletes": {}}
    for side in d.get("rosters") or []:
        tid = str((side.get("team") or {}).get("id") or "")
        key = side.get("homeAway") or ("home" if tid == home_id else "away")
        rows = []
        for p in side.get("roster") or []:
            a = p.get("athlete") or {}
            aid = str(a.get("id") or "")
            if not aid:
                continue
            jersey = _int(p.get("jersey"))
            stats = _stat_map(p.get("stats"), PLAYER_KEYS)
            rows.append([aid, jersey, ((p.get("position") or {}).get("abbreviation") or ""),
                         1 if (jersey is not None and 1 <= jersey <= 15) else 0, 1 if p.get("captain") else 0, stats])
            out["athletes"].setdefault(aid, {"name": a.get("displayName") or a.get("fullName") or "",
                                             "short": a.get("shortName") or ""})
        out["lineups"]["h" if key == "home" else "a"] = rows
    for side in ((d.get("boxscore") or {}).get("players") or []):
        for g in side.get("statistics") or []:
            for at in g.get("athletes") or []:
                a = at.get("athlete") or {}
                aid = str(a.get("id") or "")
                if not aid:
                    continue
                rec = out["athletes"].setdefault(aid, {"name": a.get("displayName") or "", "short": a.get("shortName") or ""})
                if a.get("dateOfBirth"):
                    rec["dob"] = str(a["dateOfBirth"])[:10]
                if a.get("height"):
                    rec["ht_cm"] = round(float(a["height"]) * 2.54)
                if a.get("weight"):
                    rec["wt_kg"] = round(float(a["weight"]) * 0.4536)
                pos = (a.get("position") or {})
                if pos.get("abbreviation"):
                    rec["pos"] = pos.get("abbreviation")
                if (a.get("birthPlace") or {}).get("country"):
                    rec["born"] = a["birthPlace"]["country"]
    if hdr.get("details") and home_id:
        out["events"] = parse_details(hdr.get("details"), home_id)
    gi = d.get("gameInfo") or {}
    out["attendance"] = _int(gi.get("attendance")) or None
    v = gi.get("venue") or {}
    if v:
        out["venue"] = {"name": v.get("fullName") or "", "city": (v.get("address") or {}).get("city") or "",
                        "country": (v.get("address") or {}).get("country") or ""}
    return out
