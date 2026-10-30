"""
Level constants and identity rules for The Quant Campus (college sports).

Levels: "cfb" (NCAA FBS football), "mbb" (NCAA Division I men's basketball), "wbb" (Division I women's).
Seasons are labelled by ESPN's `season.year`:
  cfb  the year the season STARTS (the 2025 season's bowls and CFP final in January 2026 are season 2025);
  mbb, wbb  the year the season ENDS (2025-26 = 2026), the Hardwood convention.
Teams, players, games and conferences are keyed by ESPN ids as strings (ESPN keeps one id per school
across conference moves and renames; a player keeps one athlete id across transfers).

This module is owned by the data builder (oddsmarkets/college/CONTRACT.md section 1); the constants below
are the shared contract every builder imports.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

LEVELS = ("cfb", "mbb", "wbb")
LEVEL_NAMES = {"cfb": "College Football (FBS)", "mbb": "Men's College Basketball (Division I)",
               "wbb": "Women's College Basketball (Division I)"}
LEVEL_SHORT = {"cfb": "CFB", "mbb": "MBB", "wbb": "WBB"}
SPORT = {"cfb": "football", "mbb": "basketball", "wbb": "basketball"}
# College hockey (30 Oct 2026): men's and women's Division I, built by oddsmarkets/college/hockey (its own ESPN
# scoreboard reader and College Hockey News); not in LEVELS, which the basketball / football fetchers loop over.
HOCKEY_LEVELS = ("mch", "wch")
ALL_LEVELS = LEVELS + HOCKEY_LEVELS
LEVEL_NAMES.update({"mch": "Men's College Hockey (Division I)", "wch": "Women's College Hockey (Division I)"})
LEVEL_SHORT.update({"mch": "MCH", "wch": "WCH"})
SPORT.update({"mch": "hockey", "wch": "hockey"})
# ESPN (sport, league) path segments and the scoreboard `groups` filter (80 = FBS, 50 = Division I)
ESPN = {"cfb": ("football", "college-football"), "mbb": ("basketball", "mens-college-basketball"),
        "wbb": ("basketball", "womens-college-basketball")}
GROUP = {"cfb": 80, "mbb": 50, "wbb": 50}
# Earliest seasons ESPN serves scoreboards for (probed 19 Oct 2026: all three answer for 2001-02)
FIRST_SEASON = {"cfb": 2001, "mbb": 2002, "wbb": 2002}

# Game types (`stype`). Football: reg | conf (conference championship game) | bowl | cfp (any College Football
# Playoff or BCS/BCS-era national-title game) | other. Basketball: reg | conf (conference tournament) |
# ncaa (NCAA tournament incl. First Four) | nit | wbit | post (other postseason: CBI, CIT, Crown, ...).
STYPES = {"cfb": ("reg", "conf", "bowl", "cfp", "other"), "mbb": ("reg", "conf", "ncaa", "nit", "post"),
          "wbb": ("reg", "conf", "ncaa", "wbit", "nit", "post")}


def sport(level: str) -> str:
    return SPORT[str(level).lower()]


def is_football(level: str) -> bool:
    return SPORT[str(level).lower()] == "football"


def season_window(level: str, season: int) -> tuple[date, date]:
    """A generous [first, last] calendar window of a season (fallback when ESPN's calendar is unavailable).
    cfb: 20 Aug of `season` to 25 Jan of season + 1. mbb/wbb: 1 Nov of season - 1 to 15 Apr of season
    (2021: 25 Nov 2020 to 6 Apr 2021; 2020: no postseason, ends 15 Mar)."""
    y = int(season)
    if is_football(level):
        return date(y, 8, 20), date(y + 1, 1, 25)
    if y == 2021:
        return date(2020, 11, 20), date(2021, 4, 10)
    if y == 2020:
        return date(2019, 11, 1), date(2020, 3, 15)
    return date(y - 1, 11, 1), date(y, 4, 15)


def current_season(level: str, today: date | None = None) -> int:
    """The season a site shows by default: the one in progress, else the next one (from 1 Feb for cfb, from
    1 May for basketball, the site switches to the coming season's preseason view)."""
    d = today or date.today()
    if is_football(level):
        return d.year if d.month >= 2 else d.year - 1
    return d.year + 1 if d.month >= 5 else d.year


def time_tba(game: dict) -> bool:
    """A game not yet played whose start time is not set: ESPN's `timeValid: false` (stored as "tba") or its
    placeholder time, midnight US Eastern (05:00Z in winter, 04:00Z in summer). Real late games are not caught:
    ESPN writes a 7 pm Hawaii tip-off as 04:59Z, never on the placeholder."""
    if (game or {}).get("status") not in ("pre", None):
        return False
    if game.get("tba"):
        return True
    d = str(game.get("date") or "")
    if len(d) < 16:
        return False
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        t = datetime.fromisoformat(d.replace("Z", "+00:00"))
        if t.tzinfo is None:
            return False
        et = t.astimezone(ZoneInfo("America/New_York"))
    except (ValueError, KeyError, ImportError):
        return d[10:16] in ("T05:00", "T04:00")
    return et.hour == 0 and et.minute == 0 and et.second == 0


def in_season(level: str, today: date | None = None, pad_days: int = 14) -> bool:
    from datetime import timedelta
    d = today or date.today()
    a, b = season_window(level, current_season(level, d))
    return a - timedelta(days=pad_days) <= d <= b + timedelta(days=7)


def level_of(x: Any) -> str:
    s = str(x or "").lower()
    if s in LEVELS:
        return s
    raise ValueError(f"unknown level {x!r}")


# ── game classification (CONTRACT.md 1.2: stype, round, region) ─────────────

CFP_ROUNDS = ("First Round", "Quarterfinal", "Semifinal", "National Championship")
NCAA_ROUNDS = ("First Four", "Round of 64", "Round of 32", "Sweet 16", "Elite 8", "Final Four", "National Championship")
NCAA_TOURNAMENT_ID = 22

_OTHER_POST = (("wbit", r"\bwbit\b|women'?s basketball invitation"),
               ("nit", r"\bnit\b|national invitation"),
               ("post", r"\bcbi\b|\bcit\b|collegeinsider|college basketball invitational|\bcrown\b|\bwbi\b|"
                        r"vegas 16|basketball classic|postseason tournament|\btbc\b|invitational|classic"))


def _clean(h: str | None) -> str:
    return " ".join(str(h or "").replace("’", "'").split())


def _tail(h: str) -> str | None:
    """The part after the last ' - ' without a trailing ' AT CITY ST' ('Big Ten Tournament - 3rd Round' -> '3rd Round')."""
    if " - " not in h:
        return None
    t = h.rsplit(" - ", 1)[1]
    t = re.sub(r"\s+(at|in)\s+.*$", "", t, flags=re.I).strip()
    if t.isupper():
        t = re.sub(r"(\d)([A-Z])", lambda m: m.group(1) + m.group(2).lower(), t.title())
    return t or None


def _ncaa_round_from_text(h: str) -> str | None:
    s = h.lower()
    if "first four" in s or "opening round" in s or "play-in" in s:
        return "First Four"
    if "national championship" in s or "national final" in s or s.endswith("- championship"):
        return "National Championship"
    if "final four" in s or "national semifinal" in s:
        return "Final Four"
    if "elite 8" in s or "elite eight" in s or "regional final" in s:
        return "Elite 8"
    if "sweet 16" in s or "sweet sixteen" in s or "regional semifinal" in s:
        return "Sweet 16"
    if "2nd round" in s or "second round" in s:
        return "Round of 32"
    if "1st round" in s or "first round" in s:
        return "Round of 64"
    return None


def _region(h: str) -> str | None:
    """'South' from '... - South Region - 2nd Round'; 'Regional 4' from '... - Regional 4 in Spokane - 1st Round';
    'Syracuse' from 'SYRACUSE REGIONAL AT WORCESTER MA' (2005-era names)."""
    m = re.search(r"regional\s+(\d)\b", h, re.I)
    if m:
        return f"Regional {m.group(1)}"
    for part in h.split(" - "):
        m = re.match(r"^\s*([A-Za-z .'-]+?)\s+region(?:al)?\b", part.strip(), re.I)
        if m:
            name = m.group(1).strip()
            if re.search(r"championship|ncaa|basketball", name, re.I):
                continue
            return name.title()
    return None


def classify(level: str, season_type: Any, headline: str | None, conf_game: bool | None = None,
             tournament_id: Any = None) -> tuple[str, str | None, str | None]:
    """(stype, round, region) from ESPN's season type id (2 regular, 3 post), the event's note headline and,
    optionally, the competition's conferenceCompetition flag and tournamentId.

    Football: cfp = any College Football Playoff game (and a BCS-era national championship game when the
    headline says so); bowl = other postseason; conf = conference championship game (regular season type,
    headline "... Championship").
    Basketball: ncaa = NCAA tournament (tournamentId 22, or a headline naming the men's / women's
    championship or a region); nit / wbit / post (CBI, CIT, Crown, WBI ...) = other postseason; conf =
    conference tournament (regular season type, headline "... Tournament|Championship - <round>", not flagged
    as a non-conference game). The NCAA round from the headline is a first guess; `ncaa_rounds` fixes it from
    the bracket (ESPN called the Round of 64 the "2nd Round" in 2011-2015)."""
    lv = level_of(level)
    h = _clean(headline)
    s = h.lower()
    try:
        t = int(season_type)
    except (TypeError, ValueError):
        t = 2
    if is_football(lv):
        if t == 3 and "semifinal" in s and "playoff" not in s:
            return "cfp", "Semifinal", None              # 2014-2023: "Allstate Sugar Bowl - Semifinal", "CFP Semifinal at ..."
        if "playoff" in s or "national championship" in s or "bcs championship" in s:
            if "national championship" in s or "bcs championship" in s:
                rnd = "National Championship"
            elif "semifinal" in s:
                rnd = "Semifinal"
            elif "quarterfinal" in s:
                rnd = "Quarterfinal"
            elif "first round" in s:
                rnd = "First Round"
            else:
                rnd = None
            return "cfp", rnd, None
        if t == 3:
            return "bowl", h or None, None
        if "championship" in s and "fcs" not in s:
            return "conf", "Championship", None
        return ("reg", None, None) if t in (1, 2) else ("other", h or None, None)
    try:
        tid = int(tournament_id) if tournament_id is not None else None
    except (TypeError, ValueError):
        tid = None
    other = None
    for kind, pat in _OTHER_POST:
        if re.search(pat, s):
            other = kind
            break
    ncaa_text = other is None and bool(re.search(
        r"\bncaa\b|men'?s basketball championship|women'?s (basketball )?championship|\bregion(al)?\b|final four|"
        r"first four|opening round", s))
    if t == 3:
        if tid == NCAA_TOURNAMENT_ID or ncaa_text:
            return "ncaa", _ncaa_round_from_text(h), _region(h)
        if other == "wbit" and lv == "mbb":
            other = "post"
        return (other or "post"), _tail(h) or (h or None), None
    if h and conf_game is not False and re.search(r"tournament|championship", s) and not ncaa_text:
        return "conf", _tail(h), None
    return "reg", None, None


def ncaa_rounds(games: dict[str, dict]) -> dict[str, str]:
    """{gid: round} for a season's NCAA tournament games from the bracket itself: a game between equal seeds is
    the First Four (the men's opening round 2001-2010 too); otherwise the round is 1 + the bracket wins either
    team already has (Round of 64 = no wins yet). Uses `seeds` and finished results in date order."""
    rows = sorted((g for g in games.values() if g.get("stype") == "ncaa" and g.get("status") != "canceled"),
                  key=lambda g: (g.get("date") or "", str(g.get("id"))))
    wins: dict[str, int] = {}
    out: dict[str, str] = {}
    for g in rows:
        sd = g.get("seeds") or {}
        k = max(wins.get(str(g.get("home")), 0), wins.get(str(g.get("away")), 0))
        ff = k == 0 and sd.get("home") is not None and sd.get("home") == sd.get("away") and sd["home"] >= 10
        if ff:
            out[str(g["id"])] = "First Four"
        else:
            out[str(g["id"])] = NCAA_ROUNDS[min(1 + k, len(NCAA_ROUNDS) - 1)]
        if g.get("status") == "post" and g.get("hs") is not None and g.get("as") is not None and not ff:
            w = str(g["home"] if g["hs"] > g["as"] else g["away"])
            wins[w] = wins.get(w, 0) + 1
    return out


def ncaa_regions(games: dict[str, dict]) -> int:
    """Women's headlines before 2022 name the first-weekend host site ("Waco", "Iowa City") instead of the
    region: when a season shows more than four region names, each early-round game takes the region of the
    later game its teams played (walking back from the Sweet 16, whose four names are the real regions).
    Returns the number of games changed."""
    rows = sorted((g for g in games.values() if g.get("stype") == "ncaa"), key=lambda g: g.get("date") or "")
    late = {g.get("region") for g in rows if g.get("round") in ("Sweet 16", "Elite 8") and g.get("region")}
    allr = {g.get("region") for g in rows if g.get("region")}
    if len(allr) <= 4 or len(late) != 4:
        return 0
    team_region: dict[str, str] = {}
    n = 0
    for g in reversed(rows):
        if g.get("round") in ("Final Four", "National Championship"):
            continue
        r = g.get("region") if g.get("region") in late else None
        r = r or team_region.get(str(g.get("home"))) or team_region.get(str(g.get("away")))
        if r and r != g.get("region"):
            g["region"] = r
            n += 1
        if r:
            team_region.setdefault(str(g.get("home")), r)
            team_region.setdefault(str(g.get("away")), r)
    return n


# BCS-era title games whose headline does not say so (ESPN notes before 2006 name only the bowl, 2001 none):
# season -> the two finalists' ESPN team ids (2001 Rose: Miami-Nebraska; 2002 Fiesta: Ohio State-Miami;
# 2003 Sugar: LSU-Oklahoma; 2004 Orange: USC-Oklahoma; 2005 Rose: Texas-USC)
BCS_TITLE_GAMES = {2001: {"2390", "158"}, 2002: {"194", "2390"}, 2003: {"99", "201"}, 2004: {"30", "201"}, 2005: {"251", "30"}}


def fix_cfb_postseason(season: int, games: dict[str, dict], teams: dict[str, dict] | None = None) -> int:
    """Season-level football fixes the headlines cannot give (returns the number of games changed):
    the BCS title game 2001-2005 (BCS_TITLE_GAMES); the 4-team CFP semifinals 2014-2023 whose headline names
    only the bowl (the finalists' last postseason games before the title game), with seeds = their CFP ranks;
    conference championship games in seasons whose headlines are missing (a December, neutral-site game
    between two members of the same non-independent conference)."""
    n = 0
    y = int(season)
    post = [g for g in games.values() if g.get("stype") in ("bowl", "cfp")]
    if y in BCS_TITLE_GAMES:
        for g in post:
            if {str(g.get("home")), str(g.get("away"))} == BCS_TITLE_GAMES[y] and g.get("stype") != "cfp":
                g["stype"], g["round"] = "cfp", "National Championship"
                n += 1
    final = next((g for g in post if g.get("stype") == "cfp" and g.get("round") == "National Championship"), None)
    if final and 2014 <= y <= 2023:
        for t in (final.get("home"), final.get("away")):
            prev = sorted((g for g in post if g is not final and t in (g.get("home"), g.get("away"))
                           and (g.get("date") or "") < (final.get("date") or "")), key=lambda g: g.get("date") or "")
            if prev and prev[-1].get("stype") != "cfp":
                g = prev[-1]
                g["stype"], g["round"] = "cfp", "Semifinal"
                n += 1
        for g in post:
            if g.get("stype") == "cfp" and not any((g.get("seeds") or {}).values()):
                r = g.get("ranks") or {}
                if r.get("home") and r.get("away") and r["home"] <= 4 and r["away"] <= 4:
                    g["seeds"] = {"home": r["home"], "away": r["away"]}
    if teams and not any(g.get("stype") == "conf" for g in games.values()):
        for g in games.values():
            th, ta = teams.get(str(g.get("home"))) or {}, teams.get(str(g.get("away"))) or {}
            if g.get("stype") == "reg" and g.get("neutral") and str(g.get("date") or "")[5:7] == "12" \
                    and th.get("member") and ta.get("member") and th.get("conference") and th.get("conference") == ta.get("conference") \
                    and th.get("conference") != "18":
                g["stype"], g["round"] = "conf", "Championship"
                n += 1
    return n


# ── basketball clock (college halves; women's quarters from 2015-16) ────────
OT_S = 300
WBB_QUARTERS_FROM = 2016


def reg_periods(level: str, season: int | None = None) -> int:
    if level_of(level) == "wbb" and (season is None or int(season) >= WBB_QUARTERS_FROM):
        return 4
    return 2


def period_len(level: str, period: int, season: int | None = None) -> int:
    """Seconds in `period`: men two 20-minute halves; women four 10-minute quarters from 2016 (2015-16) and two
    20-minute halves before; every overtime 5 minutes."""
    n = reg_periods(level, season)
    if int(period) > n:
        return OT_S
    return 600 if n == 4 else 1200


def period_start(level: str, period: int, season: int | None = None) -> int:
    p, n = int(period), reg_periods(level, season)
    reg = period_len(level, 1, season)
    return (p - 1) * reg if p <= n else n * reg + (p - n - 1) * OT_S


def game_t(level: str, period: int, clock_s: float, season: int | None = None) -> float:
    """Elapsed game seconds at `clock_s` remaining in `period`."""
    return period_start(level, period, season) + period_len(level, period, season) - float(clock_s)


def regulation_s(level: str, season: int | None = None) -> int:
    return 2400


# ── positions and class years ───────────────────────────────────────────────
FB_POOLS = ("QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "K", "P", "ATH")
BB_POOLS = ("G", "F", "C")
_FB_POOL = {"QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "TB": "RB", "WR": "WR", "TE": "TE",
            "OL": "OL", "OT": "OL", "OG": "OL", "T": "OL", "G": "OL", "C": "OL", "IOL": "OL", "LS": "OL",
            "DL": "DL", "DE": "DL", "DT": "DL", "NT": "DL", "EDGE": "DL",
            "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB",
            "DB": "DB", "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "SAF": "DB",
            "K": "K", "PK": "K", "P": "P", "ATH": "ATH"}
_BB_POOL = {"G": "G", "PG": "G", "SG": "G", "F": "F", "SF": "F", "PF": "F", "G-F": "F", "F-G": "F", "GF": "F",
            "F-C": "F", "FC": "F", "C": "C", "C-F": "C", "CF": "C"}


def pool(level: str, pos: str | None) -> str | None:
    """Position pool: football QB/RB/WR/TE/OL/DL/LB/DB/K/P/ATH, basketball G/F/C (None when unknown)."""
    if not pos:
        return None
    p = str(pos).upper().replace(" ", "")
    if is_football(level):
        return _FB_POOL.get(p)
    if p in _BB_POOL:
        return _BB_POOL[p]
    return {"GUARD": "G", "FORWARD": "F", "CENTER": "C"}.get(p) or _BB_POOL.get(p[:1])


CLASSES = ("FR", "SO", "JR", "SR", "GR")


def class_year(exp: Any) -> str | None:
    """'FR|SO|JR|SR|GR' from ESPN's `experience` ({"years": 2, "abbreviation": "SO"}) or a string."""
    if isinstance(exp, dict):
        ab, yrs = str(exp.get("abbreviation") or ""), exp.get("years")
    else:
        ab, yrs = str(exp or ""), None
    ab = ab.upper().replace(".", "").replace("RS", "").replace("-", "").strip()
    if ab in CLASSES:
        return ab
    if ab in ("GRAD", "GS", "5TH", "6TH"):
        return "GR"
    try:
        y = int(yrs)
    except (TypeError, ValueError):
        return None
    return CLASSES[min(max(y, 1), 5) - 1] if y > 0 else None
