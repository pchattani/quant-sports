"""
ESPN's public tennis JSON (no key, CORS *): scoreboards and rankings for the ATP and WTA.

  https://site.api.espn.com/apis/site/v2/sports/tennis/{atp,wta}/scoreboard?dates=YYYYMMDD
      every tournament in progress on that day with ALL its matches (finished, live and scheduled,
      qualifying included; future rounds appear with "TBD" competitors, ids -3/-4), grouped by draw
      ("mens-singles", "womens-singles", doubles ...). Combined events (Beijing, Indian Wells ...)
      appear in both feeds, so each tour keeps only its own singles grouping.
  ...scoreboard?dates=YYYY
      the whole season in one answer (about 20 MB); the ATP 2025 answer holds 61 tournaments and
      3,941 men's singles matches.
  https://site.api.espn.com/apis/site/v2/sports/tennis/{atp,wta}/rankings
      the latest official ranking, top 150, with athlete ids, first/last names and citizenship.

Linescores are games per set; a set that went to a tiebreak carries "tiebreak" with that player's
tiebreak points (7-6 sets show 7/9 v 6/7 games, tiebreak 7 v 5 points, say). A live set at 6-6
carries the running tiebreak score. No match stats, no point-by-point, no server.

Shapes verified on 1 Oct 2026 (ATP Tokyo 5-2026, Beijing 959-2026; WTA Jingshan, Adana).
Every call goes through the paced `Client` (sources/_client.py), which never raises on a bad
answer; `BudgetExhausted` stops a backfill cleanly.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from .. import canon
from ._client import BudgetExhausted, Client  # noqa: F401 - re-exported for scripts

logger = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports/tennis"
SINGLES = {"atp": "mens-singles", "wta": "womens-singles"}
STATUS = {"STATUS_FINAL": "done", "STATUS_RETIRED": "ret", "STATUS_WALKOVER": "wo", "STATUS_DEFAULT": "def",
          "STATUS_DEFAULTED": "def", "STATUS_DISQUALIFIED": "def", "STATUS_IN_PROGRESS": "live",
          "STATUS_SUSPENDED": "live", "STATUS_DELAYED": "live", "STATUS_RAIN_DELAY": "live",
          "STATUS_END_PERIOD": "live", "STATUS_SCHEDULED": "upcoming", "STATUS_POSTPONED": "upcoming",
          "STATUS_CANCELED": None, "STATUS_CANCELLED": None, "STATUS_ABANDONED": None, "STATUS_BYE": None}


def client(budget: int = 2000, interval: float = 0.5) -> Client:
    return Client(budget=budget, interval=interval, name="espn")


# ── fetchers ────────────────────────────────────────────────────────────────

def scoreboard(c: Client, tour: str, dates: str | int) -> dict | None:
    """Raw scoreboard for one day ("YYYYMMDD") or one season ("YYYY")."""
    return c.get(f"{SITE}/{canon.tour_key(tour)}/scoreboard", {"dates": str(dates)})


def rankings_raw(c: Client, tour: str) -> dict | None:
    return c.get(f"{SITE}/{canon.tour_key(tour)}/rankings")


CORE = "https://sports.core.api.espn.com/v2/sports/tennis/leagues"


def athlete_raw(c: Client, tour: str, espn_id: str | int) -> dict | None:
    """ESPN's core athlete record (date of birth, hand, height): one call per player (scripts/tn_bio.py)."""
    return c.get(f"{CORE}/{canon.tour_key(tour)}/athletes/{espn_id}")


def parse_athlete(raw: dict | None) -> dict | None:
    """{"dob": "YYYY-MM-DD" | None, "name"} from a core athlete record; None for an empty answer. The core API gives
    "dateOfBirth" as an ISO timestamp ("2001-08-16T07:00Z"); the date part is the date of birth."""
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    dob = str(raw.get("dateOfBirth") or "")[:10]
    ok = bool(re.match(r"^(19|20)\d\d-\d\d-\d\d$", dob))
    return {"dob": dob if ok else None, "name": raw.get("displayName") or raw.get("fullName")}


# ── parsing ─────────────────────────────────────────────────────────────────

def _country(athlete: dict) -> str | None:
    flag = athlete.get("flag")
    href = flag.get("href") if isinstance(flag, dict) else flag
    m = re.search(r"/countries/\d+/([a-z]{3})\.png", str(href or ""))
    if m:
        return m.group(1).upper()
    return athlete.get("citizenshipCountry")


def player_side(cp: dict) -> dict | None:
    """A competitor -> {"name","first","last","espn","country"} (None for TBD slots)."""
    pid = str(cp.get("id") or "")
    a = cp.get("athlete") or {}
    full = a.get("displayName") or a.get("fullName")
    if not pid or pid.startswith("-") or not full or full.upper() == "TBD":
        return None
    short = str(a.get("shortName") or a.get("shortname") or "")
    last = None
    m = re.match(r"^[^\s.]{1,3}\.\s+(.+)$", short)                 # "C. Ugo Carabelli" -> "Ugo Carabelli"
    if m and full.endswith(m.group(1)):
        last = m.group(1)
    first = full[: len(full) - len(last)].strip() if last else None
    if a.get("lastName"):
        first, last = a.get("firstName"), a.get("lastName")
    return {"name": full, "first": first, "last": last, "espn": pid, "country": _country(a)}


def _sets(cps: list[dict]) -> tuple[list[list], list | None]:
    """[[ga, gb, tba, tbb]] for completed sets and the live set's [ga, gb, tba, tbb] (or None)."""
    la = (cps[0].get("linescores") or []) if cps else []
    lb = (cps[1].get("linescores") or []) if len(cps) > 1 else []
    out = []
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else {}
        y = lb[i] if i < len(lb) else {}
        ga, gb = _int(x.get("value")), _int(y.get("value"))
        if ga is None and gb is None:
            continue
        ta, tb = _int(x.get("tiebreak")), _int(y.get("tiebreak"))
        out.append([ga or 0, gb or 0, ta, tb, ("winner" in x) or ("winner" in y)])
    return [s[:4] for s in out], out


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _set_done(ga: int, gb: int) -> bool:
    hi, lo = max(ga, gb), min(ga, gb)
    return (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo == 6) or hi >= 7 and hi - lo >= 2


def event_meta(ev: dict, tour: str, comps: list[dict]) -> dict:
    venue = ev.get("venue") or {}
    place = venue.get("displayName") or (venue.get("address") or {}).get("summary") or ""
    if not place and comps:
        place = (comps[0].get("venue") or {}).get("fullName") or ""
    city, _, country = str(place).partition(",")
    if not country.strip() and canon.clean_city(city) is None and canon.fold(city) in canon.COUNTRY_NAMES:
        country = city
    city = canon.clean_city(city) or ""
    labels = canon.espn_round_labels([(c.get("round") or {}).get("displayName") or "" for c in comps])
    main = [labels.get((c.get("round") or {}).get("displayName") or "") for c in comps]
    bracket = canon.bracket_size([m for m in main if m and not canon.is_qual(m)])
    r1 = sum(1 for m in main if m and bracket and m == f"R{bracket}")
    start = str(ev.get("date") or "")[:10] or None
    end = None
    if ev.get("endDate"):
        try:     # ESPN's end is 03:59Z the next morning (US Eastern midnight)
            end = (datetime.fromisoformat(str(ev["endDate"]).replace("Z", "+00:00")) - timedelta(hours=6)).date().isoformat()
        except ValueError:
            end = str(ev["endDate"])[:10]
    name = ev.get("name") or ev.get("shortName")
    return {"name": name, "city": city.strip() or None, "country": country.strip() or None, "start": start, "end": end,
            "level": None, "series": None, "surface": None, "indoor": None,
            "draw_size": canon.snap_draw(canon.entrants(bracket, r1)) if bracket else None,
            "td": None, "espn": str(ev.get("id") or "") or None, "wta": None, "major": bool(ev.get("major")),
            "tid_hint": canon.tid_for(tour, name, city, "slam" if ev.get("major") else None),
            "labels": labels}


def parse_scoreboard(raw: dict | None, tour: str, year: int | None = None) -> list[dict]:
    """Source match records (canon.SMR_DOC) for one tour's singles in a scoreboard answer.
    TBD pairings are skipped; `year` (when given) keeps only events starting that year."""
    tour = canon.tour_key(tour)
    out: list[dict] = []
    for ev in (raw or {}).get("events") or []:
        comps = []
        for g in ev.get("groupings") or []:
            if ((g.get("grouping") or {}).get("slug")) == SINGLES[tour]:
                comps.extend(g.get("competitions") or [])
        if not comps:
            continue
        meta = event_meta(ev, tour, comps)
        if meta["tid_hint"] in ("skip", "next-gen-finals"):
            continue
        season = (ev.get("season") or {}).get("year")
        ev_year = int(season) if season else (int(meta["start"][:4]) if meta["start"] else year)
        for c in comps:
            rec = parse_competition(c, tour, meta)
            if rec is None:
                continue
            rec["year"] = ev_year or (int(year) if year else None)
            out.append(rec)
    return out


def parse_competition(c: dict, tour: str, meta: dict) -> dict | None:
    st = ((c.get("status") or {}).get("type") or {})
    status = STATUS.get(st.get("name"), "done" if st.get("completed") else "upcoming")
    if status is None:
        return None
    cps = sorted(c.get("competitors") or [], key=lambda x: int(x.get("order") or 0))
    if len(cps) != 2:
        return None
    a, b = player_side(cps[0]), player_side(cps[1])
    if not a or not b:
        return None
    rnd_raw = (c.get("round") or {}).get("displayName") or ""
    rnd = meta["labels"].get(rnd_raw)
    if rnd is None and meta.get("tid_hint") in ("atp-finals", "wta-finals", "wta-elite-trophy"):
        rnd = "RR"           # older Finals scoreboards leave the round-robin rounds unnamed
    if rnd is None:          # other unnamed rounds in older seasons are duplicate rows under second athlete ids
        return None
    sets, full = _sets(cps)
    winner = "a" if cps[0].get("winner") else "b" if cps[1].get("winner") else None
    live = None
    if status == "live" and full:
        last = full[-1]
        ga, gb, ta, tb, _ = last
        if _set_done(ga, gb) and not (ta is not None and ga == gb):
            live = {"set": len(full) + 1, "games": [0, 0], "points": None, "server": None}
        else:
            sets = sets[:-1]
            live = {"set": len(full), "games": [ga, gb], "points": [ta, tb] if ta is not None and ga == gb == 6 else None,
                    "server": None}
    while status != "live" and sets and sets[-1][0] == 0 and sets[-1][1] == 0:
        sets.pop()
    if status == "upcoming":
        sets = []
    if status == "wo":
        sets = []
    for s in sets:                      # tiebreak points only on 7-6 / 6-7 style sets
        if not (abs(s[0] - s[1]) == 1 and max(s[0], s[1]) >= 7):
            s[2] = s[3] = None
    best_of = canon.best_of(tour, "slam" if meta.get("major") else None, rnd)
    when = str(c.get("date") or c.get("startDate") or "")[:16] or None
    if when and meta.get("start") and (not when[:4].isdigit() or abs(int(when[:4]) - int(str(meta["start"])[:4])) > 1):
        when = None                     # ESPN dates some old matches 1900-01-0x: not a date at all
    if when and c.get("timeValid") is False:
        when = when[:10]                # no start time yet: ESPN's "T04:00Z" is a stand-in midnight (US Eastern)
    return {"src": "espn", "tour": tour, "year": None, "event": meta, "round": rnd, "round_raw": rnd_raw,
            "date": when, "best_of": best_of,
            "a": a, "b": b, "winner": winner if status != "live" else None, "status": status, "sets": sets,
            "odds": None, "stats": None, "live": live, "duration_min": None, "src_id": str(c.get("id") or "")}


def parse_rankings(raw: dict | None) -> dict | None:
    """{"date": iso, "rows": [[rank, side_dict, points]]} from the rankings answer."""
    for r in (raw or {}).get("rankings") or []:
        rows = []
        for x in r.get("ranks") or []:
            a = x.get("athlete") or {}
            if not a.get("id"):
                continue
            side = {"name": a.get("displayName"), "first": a.get("firstName"), "last": a.get("lastName"),
                    "espn": str(a["id"]), "country": a.get("citizenshipCountry") or _country(a)}
            rows.append([_int(x.get("current")), side, x.get("points")])
        if rows:
            return {"date": str(r.get("update") or "")[:10] or None, "rows": rows, "source": "espn"}
    return None
