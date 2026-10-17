"""
Canonical identities and rules for The Quant Ace (ATP and WTA singles).

Contents
  * constants: tours, levels, surfaces, round labels;
  * tournaments: canonical ids (`tid`, a slug: "wimbledon", "indian-wells", ...), level from the
    sources' series/tier labels, surface keys, best-of and final-set rules by event and year,
    ranking-points tables per level and round (hand-entered, VERIFY flags below);
  * rounds: tennis-data / ESPN / WTA round names -> "R128|R64|R32|R16|QF|SF|F|RR|Q1|Q2|Q3|BR";
  * players: name folding and parsing ("Sinner J.", "Fernandez L.A.", "Ugo Carabelli C.",
    "Wang Xin."), and `Registry`, the tour-wide identity table that links tennis-data names,
    ESPN athletes, WTA ids and charting names to one `pid`.

Player ids (CONTRACT section 1): the ESPN athlete id when known, else "x:<slug>". A player first
seen without an ESPN id and later linked to one is renamed and the old id kept in `redirects`;
store.load applies the redirects, so stores written earlier stay consistent.

The registry lives at docs/ace/data/<tour>/registry.json (committed: CI resolves the current
year's names against it). Hard cases go in oddsmarkets/tennis/overrides.json.

Resolution order inside tn_fetch, per year: ESPN (ids, full names), WTA (ids, full names, dates
of birth), then tennis-data ("Surname I.") resolved against the event's field first, then the
whole tour; charting names (full) last. A name that matches no full-name player becomes
"x:<slug>" and is reported as unresolved when the event had a full-name field to match against.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
TOURS = ("atp", "wta")
LEVELS = ("slam", "finals", "m1000", "500", "250", "other", "ch", "q")
TOUR_LEVELS = ("slam", "finals", "m1000", "500", "250", "other")
SURFACES = ("hard", "clay", "grass", "carpet")
ROUNDS = ("Q1", "Q2", "Q3", "R128", "R64", "R32", "R16", "RR", "QF", "SF", "BR", "F")
MAIN_ROUNDS = ("R128", "R64", "R32", "R16", "RR", "QF", "SF", "BR", "F")
FINAL_SET_RULES = ("adv", "tb7", "tb10")
QUAL_ROUNDS = ("Q1", "Q2", "Q3")


def is_qual(rnd: Any) -> bool:
    return str(rnd or "") in QUAL_ROUNDS


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tour_key(tour: Any) -> str:
    t = str(tour or "").strip().lower()
    if t not in TOURS:
        raise ValueError(f"tour must be atp or wta, not {tour!r}")
    return t


def data_root() -> Path:
    return Path(os.environ.get("ACE_DATA") or (ROOT / "docs" / "ace" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("ACE_RAW") or (ROOT / "data" / "tennis"))


def current_year(today: date | None = None) -> int:
    return (today or datetime.now(timezone.utc).date()).year


# ── text folding ──────────────────────────────────────────────────────────────

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_TRANS = str.maketrans({"ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L", "ß": "ss", "æ": "ae",
                        "Æ": "AE", "œ": "oe", "Œ": "OE", "ı": "i", "þ": "th", "ð": "d", "�": ""})


def fold(s: Any) -> str:
    """Lower-case ASCII with accents removed, hyphens/apostrophes/dots as spaces, single-spaced."""
    s = str(s or "").translate(_TRANS)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).encode("ascii", "ignore").decode()
    s = s.lower().replace("'", "").replace("`", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def slug(s: Any) -> str:
    return fold(s).replace(" ", "-")


def name_tokens(s: Any) -> list[str]:
    return [t for t in fold(s).split() if t not in _SUFFIXES]


# ── surfaces and levels ───────────────────────────────────────────────────────

def surface_key(s: Any) -> str | None:
    f = fold(s)
    if not f:
        return None
    if "clay" in f:
        return "clay"
    if "grass" in f:
        return "grass"
    if "carpet" in f:
        return "carpet"
    return "hard"                       # Hard, Greenset, Acrylic, indoor hard ...


def level_from_series(tour: str, series: Any, name: Any = None) -> str:
    """tennis-data `Series` (ATP) / `Tier` (WTA) -> level."""
    s = fold(series)
    n = fold(name)
    if "elite trophy" in n:
        return "other"
    if s in ("grand slam",):
        return "slam"
    if s in ("masters cup", "tour championships", "atp finals", "wta finals"):
        return "finals"
    if s in ("masters 1000", "masters", "wta1000", "wta 1000", "tier 1", "tier i", "premier mandatory",
             "premier 5"):
        return "m1000"
    if s in ("atp500", "atp 500", "international gold", "wta500", "wta 500", "premier", "tier 2", "tier ii"):
        return "500"
    if s in ("atp250", "atp 250", "international", "wta250", "wta 250", "tier 3", "tier iii", "tier 4", "tier iv",
             "tier 5", "tier v") or re.fullmatch(r"wta ?2\d\d", s or ""):
        return "250"                    # "WTA251".."WTA276" are spreadsheet auto-fill typos for WTA250
    if s in ("wta 125", "wta125", "125k", "challenger", "atp challenger"):
        return "ch"
    if "olymp" in s or "olymp" in n:
        return "other"
    return "250"


def level_from_wta(level: Any, group_level: Any = None, title: Any = None) -> str | None:
    """WTA API `level` (falls back to tournamentGroup.level); None for ITF events."""
    for raw in (level, group_level):
        s = fold(raw)
        if not s:
            continue
        if s == "itf":
            return None
        if "grand slam" in s:
            return "slam"
        if "final" in s or "championship" in s:
            return "finals"
        if "elite" in s:
            return "other"
        if "1000" in s or "mandatory" in s or "premier 5" in s:
            return "m1000"
        if "500" in s or s == "premier":
            return "500"
        if "250" in s or "international" in s:
            return "250"
        if "125" in s:
            return "ch"
    t = fold(title)
    if "finals" in t:
        return "finals"
    return None


# ── tournaments ───────────────────────────────────────────────────────────────

SLAMS = {"australian-open": "Australian Open", "roland-garros": "Roland Garros", "wimbledon": "Wimbledon",
         "us-open": "US Open"}

# Name patterns (folded) -> tid, tried before the city rule. Order matters.
NAME_TIDS = [
    (r"\baustralian open\b", "australian-open"),
    (r"\b(french open|roland garros)\b", "roland-garros"),
    (r"\bwimbledon\b|\bthe championships wimbledon\b", "wimbledon"),
    (r"^(the )?u ?s open\b|\bus open\b(?! series)", "us-open"),
    (r"\belite trophy\b", "wta-elite-trophy"),
    (r"\bnext ?gen\b", "next-gen-finals"),
    (r"\bmasters cup\b|\batp (tour )?finals\b|\bnitto atp\b|\bbarclays atp\b", "atp-finals"),
    (r"\bwta (tour )?finals\b|\bwta championships\b|\bsony ericsson championships\b|\bwta tour championships\b",
     "wta-finals"),
    (r"\bwestern southern\b|\bcincinnati\b", "cincinnati"),
    (r"\bqueen s\b|\bqueens club\b|\bhsbc championships\b|\bcinch championships\b|\bfever tree championships\b"
     r"|\baegon championships\b|\bstella artois\b|\bartois championships\b", "queens"),
    (r"\brogers cup\b|\bnational bank open\b|\bcanadian open\b|\bomnium banque nationale\b", "canada"),
    (r"\bolympic|^(rio|tokyo|paris|london|beijing|athens|sydney) 20\d\d$", "olympics"),
    (r"\blaver cup\b|\bunited cup\b|\bhopman\b|\bdavis cup\b|\bbillie jean king\b|\bfed cup\b|\bsix kings\b"
     r"|\bexhibition\b|\bworld tennis league\b|\bultimate tennis\b", "skip"),
]

# Folded city spellings -> canonical city slug.
CITY_ALIASES = {
    "ho chi min city": "ho-chi-minh-city", "monreal": "montreal", "nrnberg": "nurnberg", "nuremberg": "nurnberg",
    "nurnberg": "nurnberg", "queens club": "queens", "marrakesh": "marrakech", "s hertogenbosch": "s-hertogenbosch",
    "hertogenbosch": "s-hertogenbosch", "rosmalen": "s-hertogenbosch", "den bosch": "s-hertogenbosch",
    "mason": "cincinnati", "key biscayne": "miami", "miami gardens": "miami", "monte carlo": "monte-carlo",
    "monaco": "monte-carlo", "roquebrune cap martin": "monte-carlo", "nur sultan": "astana", "astana": "astana",
    "st petersburg": "st-petersburg", "saint petersburg": "st-petersburg", "st polten": "st-polten",
    "vina del mar": "vina-del-mar", "santa ponsa": "mallorca", "palma": "mallorca", "cabo san lucas": "los-cabos",
    "washington d c": "washington", "washington dc": "washington", "flushing meadows": "new-york",
    "rogers cup": "canada", "costa do sauipe": "costa-do-sauipe", "mexico city": "mexico-city",
    "bangkok": "bangkok", "ponte vedra beach": "ponte-vedra-beach", "cluj napoca": "cluj-napoca",
}

# Canonical tids of the current calendar with a default level, used when an event appears in ESPN
# or the WTA API before tennis-data has it (tennis-data's Series/Tier wins otherwise).
# VERIFY: hand-entered from the 2025-26 ATP and WTA calendars (atptour.com / wtatennis.com
# tournament pages), 1 Oct 2026.
KNOWN_LEVELS = {
    "atp": {"australian-open": "slam", "roland-garros": "slam", "wimbledon": "slam", "us-open": "slam",
            "atp-finals": "finals", "indian-wells": "m1000", "miami": "m1000", "monte-carlo": "m1000",
            "madrid": "m1000", "rome": "m1000", "canada": "m1000", "cincinnati": "m1000", "shanghai": "m1000",
            "paris": "m1000", "rotterdam": "500", "rio-de-janeiro": "500", "dubai": "500", "acapulco": "500",
            "doha": "500", "barcelona": "500", "munich": "500", "halle": "500", "queens": "500",
            "hamburg": "500", "washington": "500", "beijing": "500", "tokyo": "500", "vienna": "500",
            "basel": "500", "next-gen-finals": "other", "olympics": "other"},
    "wta": {"australian-open": "slam", "roland-garros": "slam", "wimbledon": "slam", "us-open": "slam",
            "wta-finals": "finals", "doha": "m1000", "dubai": "m1000", "indian-wells": "m1000", "miami": "m1000",
            "madrid": "m1000", "rome": "m1000", "canada": "m1000", "cincinnati": "m1000", "beijing": "m1000",
            "wuhan": "m1000", "brisbane": "500", "adelaide": "500", "abu-dhabi": "500", "charleston": "500",
            "stuttgart": "500", "berlin": "500", "queens": "500", "bad-homburg": "500", "eastbourne": "250",
            "washington": "500", "san-diego": "500", "monterrey": "500", "seoul": "500", "tokyo": "500",
            "ningbo": "500", "singapore": "500", "linz": "500", "wta-elite-trophy": "other", "olympics": "other"},
}

# Masters/1000 events with a 96-player draw (128-slot bracket) by year range; the rest are 56 (64).
# VERIFY: from the ATP/WTA calendars (Madrid and Rome 96 from 2023 (ATP) / 2023 (WTA),
# Shanghai 96 from 2023, Canada and Cincinnati 96 from 2025 (ATP) / 2025 (WTA)).
DRAW96 = {
    "atp": {"indian-wells": (2009, 9999), "miami": (2000, 9999), "madrid": (2023, 9999), "rome": (2023, 9999),
            "shanghai": (2023, 9999), "canada": (2025, 9999), "cincinnati": (2025, 9999)},
    "wta": {"indian-wells": (2009, 9999), "miami": (2000, 9999), "madrid": (2023, 9999), "rome": (2023, 9999),
            "beijing": (2009, 9999), "canada": (2025, 9999), "cincinnati": (2025, 9999), "wuhan": (2026, 9999)},
}


# tennis-data labels every WTA Premier event of 2009-2020 "Premier"; the Premier Mandatory and
# Premier 5 events (today's WTA 1000s) are picked out here. VERIFY: hand-entered from the WTA
# calendars of those years (Dubai and Doha alternated as the Premier 5 from 2012).
WTA_PREMIER_1000 = {
    "indian-wells": (2009, 2020), "miami": (2009, 2020), "madrid": (2009, 2020), "beijing": (2009, 2020),
    "rome": (2009, 2020), "canada": (2009, 2020), "cincinnati": (2009, 2020), "tokyo": (2009, 2013),
    "wuhan": (2014, 2019),
}
WTA_PREMIER_1000_YEARS = {"dubai": {2009, 2010, 2011, 2015, 2017, 2019}, "doha": {2012, 2013, 2014, 2016, 2018, 2020}}
# Single events whose tennis-data label is wrong. VERIFY.
LEVEL_FIX = {("wta", 2021, "dubai"): "m1000", ("wta", 2021, "doha"): "500"}


def fix_level(tour: str, year: int, tid: str, level: str, series: Any = None) -> str:
    """tennis-data's level corrected for WTA Premier-era 1000s and known mislabels."""
    key = (tour, int(year), tid)
    if key in LEVEL_FIX:
        return LEVEL_FIX[key]
    if tour == "wta" and fold(series) == "premier":
        y = int(year)
        if tid in WTA_PREMIER_1000 and WTA_PREMIER_1000[tid][0] <= y <= WTA_PREMIER_1000[tid][1]:
            return "m1000"
        if y in WTA_PREMIER_1000_YEARS.get(tid, ()):
            return "m1000"
    return level


STANDARD_DRAWS = (8, 12, 16, 28, 32, 48, 56, 64, 96, 128)


def snap_draw(n: int | None) -> int | None:
    if not n:
        return n
    for s in STANDARD_DRAWS:
        if n <= s:
            return s
    return n


def tid_for(tour: str, name: Any = None, city: Any = None, level: str | None = None) -> str:
    """Canonical tournament id from an event's name and city (no year suffix; duplicates within a
    year are suffixed by `unique_tid`). Returns "skip" for team events and exhibitions."""
    n = fold(name)
    for pat, tid in NAME_TIDS:
        if re.search(pat, n):
            if tid == "us-open" and level not in (None, "slam"):
                break                                  # "US Open Series" events, "U.S. Men's Clay Court" ...
            if tid in ("atp-finals", "wta-finals") and level not in (None, "finals"):
                break
            return tid
    if level == "slam":
        for k, v in SLAMS.items():
            if fold(v) in n:
                return k
    if level == "finals":
        return "atp-finals" if tour == "atp" else "wta-finals"
    c = fold(str(city or "").split(",")[0])
    if c in CITY_ALIASES:
        c2 = CITY_ALIASES[c]
    else:
        c2 = slug(c)
    if c2 in ("montreal", "toronto") and level == "m1000":
        return "canada"
    if c2 == "london" and "queen" in n:
        return "queens"
    if not c2:
        return slug(name) or "unknown"
    return c2


COUNTRY_NAMES = {fold(x) for x in (
    "Australia", "France", "Germany", "Spain", "Italy", "USA", "United States", "U.S.A.", "China", "China PR",
    "Great Britain", "United Kingdom", "England", "Netherlands", "Switzerland", "Austria", "Sweden", "Russia", "Brazil",
    "Argentina", "Chile", "Mexico", "Ecuador", "Colombia", "India", "Qatar", "UAE", "United Arab Emirates", "Morocco",
    "Turkey", "Turkiye", "Türkiye", "Hungary", "Bulgaria", "Croatia", "Serbia", "Portugal", "Belgium", "Japan", "Korea",
    "South Korea", "Republic of Korea", "Kazakhstan", "Poland", "Romania", "Czech Republic", "Czechia", "Monaco", "Canada",
    "New Zealand", "Israel", "Greece", "Thailand", "Malaysia", "Uzbekistan", "Slovakia", "Slovenia", "Denmark", "Finland",
    "Norway", "Ireland", "Scotland", "Wales", "Latvia", "Estonia", "Lithuania", "Ukraine", "Belarus", "Georgia",
    "Saudi Arabia", "Singapore", "Hong Kong", "Chinese Taipei", "Taiwan", "Indonesia", "Philippines", "Vietnam",
    "South Africa", "Egypt", "Tunisia", "Peru", "Uruguay", "Paraguay", "Bolivia", "Venezuela", "Puerto Rico",
    "Bosnia and Herzegovina", "Montenegro", "North Macedonia", "Luxembourg", "Cyprus", "Malta", "Iceland")} - {"singapore", "hong kong", "monaco", "luxembourg"}
# ESPN's older scoreboards put a court or arena where the city belongs
NOT_CITIES = {"grandstand", "centre court", "center court", "stadium", "court 1", "court 2", "main court", "inalpi arena",
              "pala alpitour", "o2 arena", "the o2"}


def clean_city(place: Any) -> str | None:
    """The city part of a venue string, or None when it is a country, a court or an arena."""
    c = str(place or "").split(",")[0].strip()
    f = fold(c)
    if not f or f in COUNTRY_NAMES or f in NOT_CITIES or "arena" in f or "stadium" in f or "court" in f:
        return None
    return c


def city_key(city: Any) -> str:
    c = fold(str(city or "").split(",")[0])
    return CITY_ALIASES.get(c, slug(c))


def unique_tid(tid: str, start: str | None, taken: dict[str, str | None]) -> str:
    """`tid` or `tid-2`, `tid-3`... when another event of the same year already holds the id
    (`taken`: {tid: start}). Events starting within 3 days of the holder are the same event."""
    if tid not in taken:
        return tid
    k = 2
    cand = tid
    while cand in taken:
        if _days_apart(taken[cand], start) <= 3:
            return cand
        cand = f"{tid}-{k}"
        k += 1
    return cand


def _days_apart(a: str | None, b: str | None) -> int:
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    except (TypeError, ValueError):
        return 999


def event_id(tid: str, year: int) -> str:
    return f"{tid}-{int(year)}"


def default_level(tour: str, tid: str) -> str:
    return KNOWN_LEVELS.get(tour, {}).get(tid, "250")


def best_of(tour: str, level: str | None, rnd: str | None, year: int | None = None) -> int:
    """Best-of for a match when the source does not say. Men's Slam main draws are best of five;
    everything else here is best of three (historic five-set Masters/Finals finals come from
    tennis-data's own `Best of` column)."""
    if tour == "atp" and level == "slam" and rnd and not is_qual(rnd):
        return 5
    return 3


def final_set_rule(tour: str, tid: str | None, year: int, level: str | None = None) -> tuple[str, int]:
    """(rule, games at which the deciding-set tiebreak starts) for a deciding set.
    Rules: "adv" (advantage set), "tb7" (standard tiebreak), "tb10" (first to 10).
    VERIFY (hand-entered; sources: the four Slams' rule announcements and the 2022 joint Grand Slam
    Board statement on a 10-point tiebreak at 6-6 in the final set):
      Australian Open: advantage to 2018, tb10 at 6-6 from 2019;
      Roland Garros:   advantage to 2021, tb10 at 6-6 from 2022;
      Wimbledon:       advantage to 2018, tb7 at 12-12 2019-2021, tb10 at 6-6 from 2022;
      US Open:         tb7 at 6-6 to 2021, tb10 at 6-6 from 2022;
      Olympics:        advantage final sets to 2012, tb7 from 2016;
      tour events, Finals: tb7 at 6-6."""
    y = int(year)
    if tid == "australian-open":
        return ("adv", 0) if y <= 2018 else ("tb10", 6)
    if tid == "roland-garros":
        return ("adv", 0) if y <= 2021 else ("tb10", 6)
    if tid == "wimbledon":
        if y <= 2018:
            return ("adv", 0)
        return ("tb7", 12) if y <= 2021 else ("tb10", 6)
    if tid == "us-open":
        return ("tb7", 6) if y <= 2021 else ("tb10", 6)
    if tid == "olympics":
        return ("adv", 0) if y <= 2012 else ("tb7", 6)
    return ("tb7", 6)


# ── ranking points ────────────────────────────────────────────────────────────
# Points for reaching a round and losing there ("W" = title). VERIFY: hand-entered, not scraped.
# ATP: ATP Official Rulebook 2025, section 9 (Rankings), "ATP Ranking Points" table.
# WTA: WTA Official Rulebook 2025, section XVI (Rankings), points tables (2024 points revamp).
# 0 = the round exists but earns nothing for a loss there; None = not part of that draw.
POINTS_VERIFY = True
POINTS = {
    "atp": {
        "slam":  {"W": 2000, "F": 1300, "SF": 800, "QF": 400, "R16": 200, "R32": 100, "R64": 50, "R128": 10},
        "m1000": {"W": 1000, "F": 650, "SF": 400, "QF": 200, "R16": 100, "R32": 50, "R64": 30, "R128": 10},
        "m1000_56": {"W": 1000, "F": 650, "SF": 400, "QF": 200, "R16": 100, "R32": 50, "R64": 10},
        "500":   {"W": 500, "F": 330, "SF": 200, "QF": 100, "R16": 50, "R32": 0},
        "500_48": {"W": 500, "F": 330, "SF": 200, "QF": 100, "R16": 50, "R32": 25, "R64": 0},
        "250":   {"W": 250, "F": 165, "SF": 100, "QF": 50, "R16": 25, "R32": 0},
        "250_48": {"W": 250, "F": 165, "SF": 100, "QF": 50, "R16": 25, "R32": 13, "R64": 0},
        # ATP Finals: 200 per round-robin win, +400 for the semi-final win, +500 for the final win.
        "finals": {"RR_WIN": 200, "SF_WIN": 400, "F_WIN": 500, "MAX": 1500},
    },
    "wta": {
        "slam":  {"W": 2000, "F": 1300, "SF": 780, "QF": 430, "R16": 240, "R32": 130, "R64": 70, "R128": 10},
        "m1000": {"W": 1000, "F": 650, "SF": 390, "QF": 215, "R16": 120, "R32": 65, "R64": 35, "R128": 10},
        "m1000_56": {"W": 1000, "F": 650, "SF": 390, "QF": 215, "R16": 120, "R32": 65, "R64": 10},
        "500":   {"W": 500, "F": 325, "SF": 195, "QF": 108, "R16": 60, "R32": 1},
        "500_48": {"W": 500, "F": 325, "SF": 195, "QF": 108, "R16": 60, "R32": 32, "R64": 1},
        "250":   {"W": 250, "F": 163, "SF": 98, "QF": 54, "R16": 30, "R32": 1},
        "ch":    {"W": 125, "F": 81, "SF": 49, "QF": 27, "R16": 15, "R32": 1},
        "finals": {"RR_WIN": 200, "SF_WIN": 400, "F_WIN": 500, "MAX": 1500},
    },
}
POINTS_SOURCES = {
    "atp": "ATP Official Rulebook 2025, section 9 (ATP Rankings) - hand-entered, VERIFY",
    "wta": "WTA Official Rulebook 2025, section XVI (WTA Rankings), tables after the 2024 revamp - hand-entered, VERIFY",
}


def points_table(tour: str, level: str, draw_size: int | None = None) -> dict:
    t = POINTS.get(tour_key(tour), {})
    if level == "m1000" and draw_size and draw_size <= 64:
        return t.get("m1000_56", {})
    if level in ("500", "250") and draw_size and draw_size > 32:
        return t.get(f"{level}_48", t.get(level, {}))
    return t.get(level, {})


def points(tour: str, level: str, reached: str, draw_size: int | None = None) -> int | None:
    """Ranking points for a player whose event ended at `reached` ("W" for the title)."""
    return points_table(tour, level, draw_size).get(reached)


# ── rounds ────────────────────────────────────────────────────────────────────

_NUM_WORDS = {"1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3, "4th": 4, "fourth": 4,
              "5th": 5, "fifth": 5}


def td_round_number(raw: str) -> int | None:
    m = re.match(r"\s*(\d)(?:st|nd|rd|th)\s+round", str(raw or ""), re.I)
    return int(m.group(1)) if m else None


def _fixed_round(raw: str) -> str | None:
    f = fold(raw)
    if not f:
        return None
    if "robin" in f or "group" in f:
        return "RR"
    if "third place" in f or "3rd place" in f or "bronze" in f:
        return "BR"
    if "gold medal" in f:
        return "F"
    if f.startswith("qualif") or f.startswith("q "):
        return None
    if f in ("the final", "final", "finals", "f", "championship"):
        return "F"
    if f.startswith("semi") or f == "sf" or f == "s":
        return "SF"
    if f.startswith("quarter") or f == "qf" or f == "q":
        return "QF"
    if f in ("round of 16", "r16", "4th round of 16"):
        return "R16"
    if f in ("round of 32", "r32"):
        return "R32"
    if f in ("round of 64", "r64"):
        return "R64"
    if f in ("round of 128", "r128"):
        return "R128"
    return None


def label_for(number: int, n_rounds: int) -> str:
    """Round `number` of an event whose last numbered round is `n_rounds` (the one before the QF)."""
    size = 8 * 2 ** (n_rounds - number + 1)
    return f"R{size}" if size >= 16 else "QF"


def bracket_from_level(level: str | None, tid: str | None, tour: str | None, year: int | None, r1: int) -> int:
    if level == "slam":
        return 128
    if level == "m1000":
        if tid and tour and year and tid in DRAW96.get(tour, {}):
            lo, hi = DRAW96[tour][tid]
            if lo <= int(year) <= hi:
                return 128
        return 128 if r1 > 24 else 64
    for size in (16, 32, 64, 128):
        if r1 <= size // 2:
            return size
    return 128


def td_round_labels(raw_rounds: Iterable[str], level: str | None = None, tid: str | None = None,
                    tour: str | None = None, year: int | None = None) -> dict[str, str | None]:
    """{raw round name: label} for one tennis-data event. When the event has reached its
    quarter-finals every numbered round has been played and "1st Round" of an event with four
    numbered rounds is R128 (and so on); for an event still in its early rounds the bracket
    comes from the level and the size of the first round."""
    raws = list(raw_rounds)
    nums = [td_round_number(r) for r in raws]
    present = sorted({n for n in nums if n})
    fixed = {r: _fixed_round(r) for r in set(raws)}
    reached_qf = any(v in ("QF", "SF", "F") for v in fixed.values())
    out: dict[str, str | None] = {}
    if present and not reached_qf:
        r1 = sum(1 for n in nums if n == 1)
        bracket = bracket_from_level(level, tid, tour, year, r1)
        n_rounds = max(1, bracket.bit_length() - 4)            # 128 -> 4 numbered rounds before the QF
    else:
        n_rounds = max(present) if present else 0
    for r in set(raws):
        n = td_round_number(r)
        out[r] = label_for(n, n_rounds) if n else fixed.get(r)
    return out


def bracket_size(labels: dict | Iterable[str]) -> int | None:
    vals = labels.values() if isinstance(labels, dict) else labels
    sizes = [int(v[1:]) for v in vals if v and re.fullmatch(r"R\d+", v)]
    if sizes:
        return max(sizes)
    if any(v == "QF" for v in vals):
        return 8
    return None


def entrants(bracket: int | None, r1_matches: int | None) -> int | None:
    """Players in the main draw: first-round matches plus byes (= bracket/2 - r1 matches)."""
    if not bracket:
        return None
    if not r1_matches or r1_matches > bracket // 2:
        return bracket
    return r1_matches + bracket // 2


def espn_round_labels(raw_rounds: Iterable[str]) -> dict[str, str | None]:
    """ESPN round names ("Round 1", "Round 2", ..., "Quarterfinal", "Semifinal", "Final",
    "Qualifying 1st Round", "Qualifying Final", "Round Robin") -> labels, from one event's rounds
    (ESPN lists every round of the draw, scheduled ones included, so the count is reliable)."""
    raws = set(raw_rounds)
    main_nums, qual_nums, has_qfinal = [], [], False
    for r in raws:
        f = fold(r)
        m = re.fullmatch(r"round (\d)", f) or re.fullmatch(r"(\d)(?:st|nd|rd|th) round", f)
        if m:
            main_nums.append(int(m.group(1)))
            continue
        if f.startswith("qualifying"):
            mq = re.search(r"(\d)(?:st|nd|rd|th)? round|round (\d)", f)
            if mq:
                qual_nums.append(int(mq.group(1) or mq.group(2)))
            elif "final" in f:
                has_qfinal = True
    n_main = max(main_nums) if main_nums else 0
    q_last = (max(qual_nums) if qual_nums else 0) + 1
    out: dict[str, str | None] = {}
    for r in raws:
        f = fold(r)
        m = re.fullmatch(r"round (\d)", f) or re.fullmatch(r"(\d)(?:st|nd|rd|th) round", f)
        if m:
            out[r] = label_for(int(m.group(1)), n_main)
        elif f.startswith("qualifying"):
            mq = re.search(r"(\d)(?:st|nd|rd|th)? round|round (\d)", f)
            if mq:
                out[r] = f"Q{min(3, int(mq.group(1) or mq.group(2)))}"
            else:
                out[r] = f"Q{min(3, q_last)}" if has_qfinal else "Q1"
        elif ("group" in f or "robin" in f) and main_nums and qual_nums and 1 not in qual_nums:
            out[r] = "Q1"          # ESPN labels the 2024 Australian Open's first qualifying round "Group Stage"
        else:
            out[r] = _fixed_round(r)
    return out


def wta_round_label(round_id: Any, draw_level: Any, draw_size: int | None) -> str | None:
    """WTA API RoundID ("1".."7", "Q", "S", "F", "R" round robin) for main draw (DrawLevelType "M")
    or qualifying ("Q") -> label. Main-draw numbered rounds use the bracket implied by the singles
    draw size (28 -> 32, 56 -> 64, 96 -> 128)."""
    rid = str(round_id or "").strip().upper()
    lvl = str(draw_level or "").strip().upper()
    if lvl == "Q":
        return f"Q{min(3, int(rid))}" if rid.isdigit() else None
    if rid == "Q":
        return "QF"
    if rid == "S":
        return "SF"
    if rid == "F":
        return "F"
    if rid in ("R", "RR"):
        return "RR"
    if rid.isdigit():
        size = 1
        while size < int(draw_size or 32):
            size *= 2
        lab = size // (2 ** (int(rid) - 1))
        return f"R{lab}" if lab >= 16 else ("QF" if lab == 8 else ("SF" if lab == 4 else "F"))
    return None


# ── player names ──────────────────────────────────────────────────────────────

def parse_abbrev(name: Any) -> tuple[list[str], list[str]] | None:
    """tennis-data "Surname I." -> (surname tokens, first-name prefixes). "Fernandez L.A." ->
    (["fernandez"], ["l", "a"]); "Wang Xin." -> (["wang"], ["xin"]); "Ugo Carabelli C." ->
    (["ugo", "carabelli"], ["c"]). None when the name has no initials part."""
    s = str(name or "").strip().translate(_TRANS)
    if not s:
        return None
    parts = s.split()
    if len(parts) < 2:
        return None
    tail = parts[-1]
    if "." in tail or (len(fold(tail)) == 1 and len(parts) >= 2):
        sur = name_tokens(" ".join(parts[:-1]))
        inits = [fold(x) for x in re.split(r"[.\-]", tail) if fold(x)]
        # "Del Potro J.M." / "Auger-Aliassime F." / "Zhang Shu." / "Kim K."
        if not sur or not inits:
            return None
        return sur, [i.replace(" ", "") for i in inits]
    return None


def split_full(first: Any, last: Any = None, full: Any = None) -> tuple[list[str], list[str]]:
    """(first tokens, last tokens) from separate fields or a "First Last" string."""
    if last:
        return name_tokens(first), name_tokens(last)
    toks = name_tokens(full or first)
    if len(toks) <= 1:
        return [], toks
    return toks[:1], toks[1:]


def short_name(first: Any, last: Any) -> str:
    f = str(first or "").strip()
    return f"{f[:1]}. {str(last or '').strip()}".strip(". ") if f else str(last or "").strip()


def abbrev_matches(sur: list[str], inits: list[str], first: list[str], last: list[str]) -> float:
    """Score (0 = no match) of a "Surname I." against a full name. 3 = surname and every initial;
    2 = surname and the first initial; works for hyphenated/compound surnames, middle names in the
    surname ("Ugo Carabelli") and Chinese order ("Wang Xin." against "Xinyu Wang" or "Wang Xinyu")."""
    if not sur or not inits:
        return 0
    allt = first + last
    sj = "".join(sur)

    def init_score(given: list[str]) -> int:
        if not given:
            return 0
        g0 = given[0]
        if len(inits) == 1:
            i0 = inits[0]
            if len(i0) > 1:                    # "Xin." - a prefix of the given name
                return 3 if "".join(given).startswith(i0) else 0
            return 3 if g0.startswith(i0) else 0
        # several initials: "L.A." against "Leylah Annie"
        if all(k < len(given) and given[k].startswith(i) for k, i in enumerate(inits)):
            return 3
        if "".join(given).startswith("".join(inits)):
            return 3
        return 2 if g0.startswith(inits[0]) else 0

    best = 0
    # surname = the last tokens of the name
    for k in range(1, len(allt)):
        if "".join(allt[k:]) == sj:
            best = max(best, init_score(allt[:k]))
    # the given surname tokens equal `last` exactly (separate fields)
    if last and "".join(last) == sj and first:
        best = max(best, init_score(first))
    # Chinese order: surname first ("Wang Xinyu" stored as first="Wang", last="Xinyu" or full order);
    # scored below the usual order, so "Maria T." is Tatjana Maria before Maria Timofeeva
    if not best:
        for k in range(1, len(allt)):
            if "".join(allt[:k]) == sj:
                best = max(best, init_score(allt[k:]) - 1.5 if init_score(allt[k:]) else 0)
    # a surname that drops a second family name ("Bautista R." for "Roberto Bautista Agut")
    if not best and len(last) >= 2 and last[0] == sur[0] and len(sur) == 1 and first:
        best = max(best, min(2, init_score(first)) - 1 if init_score(first) else 0)
    return best


def full_key(first: list[str], last: list[str]) -> str:
    return " ".join(first + last)


# ── registry ──────────────────────────────────────────────────────────────────

def overrides() -> dict:
    p = Path(__file__).resolve().parent / "overrides.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Registry:
    """Tour-wide player identity table (docs/ace/data/<tour>/registry.json).

    players[pid] = {"name", "first", "last", "short", "country", "hand", "dob", "height",
                    "espn", "wta", "aliases": [...]}   (aliases: every raw name seen, any source)
    redirects   = {old pid: new pid}                  (x:<slug> ids later linked to an ESPN id)
    """

    def __init__(self, tour: str, data: dict | None = None):
        self.tour = tour_key(tour)
        data = data or {}
        self.players: dict[str, dict] = data.get("players") or {}
        self.redirects: dict[str, str] = data.get("redirects") or {}
        ov = overrides().get(self.tour) or {}
        self.ov_names: dict[str, str] = {k: str(v) for k, v in (ov.get("names") or {}).items()}
        self.ov_same: dict[str, str] = {str(k): str(v) for k, v in (ov.get("same") or {}).items()}
        self.ov_espn_names: dict[str, str] = {str(k): str(v) for k, v in (ov.get("espn_names") or {}).items()}
        self.stats: dict[str, dict[str, int]] = {}
        self.unresolved: dict[str, dict[str, int]] = {}
        self.dirty = False
        self._reindex()

    # persistence
    @staticmethod
    def path(tour: str) -> Path:
        return data_root() / tour_key(tour) / "registry.json"

    @classmethod
    def load(cls, tour: str) -> "Registry":
        try:
            data = json.loads(cls.path(tour).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        return cls(tour, data)

    def save(self) -> Path:
        p = self.path(self.tour)
        p.parent.mkdir(parents=True, exist_ok=True)
        out = {"tour": self.tour, "updated_at": now(), "n_players": len(self.players),
               "players": dict(sorted(self.players.items())), "redirects": dict(sorted(self.redirects.items()))}
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(p)
        self.dirty = False
        return p

    # indexes
    def _reindex(self) -> None:
        self.by_espn: dict[str, str] = {}
        self.by_wta: dict[str, str] = {}
        self.by_alias: dict[str, set[str]] = {}
        self.by_surname: dict[str, set[str]] = {}
        for pid, p in self.players.items():
            self._index(pid, p)

    def _index(self, pid: str, p: dict) -> None:
        if p.get("espn"):
            self.by_espn[str(p["espn"])] = pid
        if p.get("wta"):
            self.by_wta[str(p["wta"])] = pid
        for v in p.get("espn_alt") or []:
            self.by_espn[str(v)] = pid
        for v in p.get("wta_alt") or []:
            self.by_wta[str(v)] = pid
        for a in [p.get("name")] + list(p.get("aliases") or []):
            for k in {fold(a), " ".join(name_tokens(a))}:          # with and without "Jr"
                if k:
                    self.by_alias.setdefault(k, set()).add(pid)
        toks = name_tokens(p.get("name"))
        for k in range(len(toks)):                       # every suffix and prefix of the full name
            self.by_surname.setdefault("".join(toks[k:]), set()).add(pid)
            self.by_surname.setdefault("".join(toks[: k + 1]), set()).add(pid)
        for t in name_tokens(p.get("last")):
            self.by_surname.setdefault(t, set()).add(pid)
        if p.get("last"):
            self.by_surname.setdefault("".join(name_tokens(p.get("last"))), set()).add(pid)

    def canonical(self, pid: str | None) -> str | None:
        seen = set()
        while pid in self.redirects and pid not in seen:
            seen.add(pid)
            pid = self.redirects[pid]
        return pid

    def _count(self, src: str, key: str, n: int = 1) -> None:
        d = self.stats.setdefault(src, {})
        d[key] = d.get(key, 0) + n

    def _miss(self, src: str, name: str) -> None:
        d = self.unresolved.setdefault(src, {})
        d[name] = d.get(name, 0) + 1

    # mutation
    def _new_pid(self, espn: Any, base: str) -> str:
        if espn:
            return str(espn)
        pid = "x:" + (slug(base) or "unknown")
        k = 2
        root = pid
        while pid in self.players:
            pid = f"{root}-{k}"
            k += 1
        return pid

    def _add_alias(self, pid: str, alias: Any) -> None:
        if not alias:
            return
        p = self.players[pid]
        al = p.setdefault("aliases", [])
        if alias != p.get("name") and alias not in al:
            al.append(alias)
            self.by_alias.setdefault(fold(alias), set()).add(pid)
            self.dirty = True

    def _fill(self, pid: str, **kw: Any) -> None:
        p = self.players[pid]
        for k, v in kw.items():
            if v in (None, "", 0) or k == "aliases":
                continue
            if k in ("espn", "wta"):
                v = str(v)
            if p.get(k) in (None, ""):
                p[k] = v
                self.dirty = True
                if k == "espn":
                    self.by_espn[v] = pid
                elif k == "wta":
                    self.by_wta[v] = pid

    def _promote(self, pid: str, espn: str) -> str:
        """Rename an x: player to its ESPN id (records a redirect)."""
        espn = str(espn)
        if pid == espn:
            return pid
        if espn in self.players:                        # both exist: merge pid into espn
            target = self.players[espn]
            src = self.players.pop(pid)
            for a in [src.get("name")] + list(src.get("aliases") or []):
                if a and a != target.get("name") and a not in target.setdefault("aliases", []):
                    target["aliases"].append(a)
            for k, v in src.items():
                if k != "aliases" and target.get(k) in (None, "") and v not in (None, ""):
                    target[k] = v
        else:
            self.players[espn] = self.players.pop(pid)
            self.players[espn]["espn"] = espn
        self.redirects[pid] = espn
        for k, v in list(self.redirects.items()):
            if v == pid:
                self.redirects[k] = espn
        self.dirty = True
        self._reindex()
        return espn

    def add(self, src: str, *, first: Any = None, last: Any = None, full: Any = None, espn: Any = None,
            wta: Any = None, country: Any = None, dob: Any = None, hand: Any = None, height: Any = None,
            raw: Any = None, field: Iterable[str] | None = None) -> str:
        """Resolve (or create) a player known by a full name and, optionally, source ids."""
        espn = str(espn) if espn not in (None, "", 0, "0") else None
        wta = str(wta) if wta not in (None, "", 0, "0") else None
        if espn and espn in self.ov_espn_names:            # ESPN profiles carrying another player's name
            full, first, last = self.ov_espn_names[espn], None, None
            raw = full
        fn, ln = split_full(first, last, full)
        disp = " ".join(x for x in (str(first or "").strip(), str(last or "").strip()) if x) if last else str(full or first or "").strip()
        raw = raw or disp
        self._count(src, "names")
        pid = None
        if espn and espn in self.by_espn:
            pid = self.by_espn[espn]
        elif wta and wta in self.by_wta:
            pid = self.by_wta[wta]
        if pid is None:
            pid = self._match_full(fn, ln, country, dob, field)
        if pid is None and fn and ln:
            # a player first known only from tennis-data ("Safin M.") or charting
            pid = self._match_abbrev_full(fn, ln, field)
        if pid is not None:
            p = self.players[pid]
            # the same name with a second id: ESPN and the WTA API both keep duplicate profiles
            # (Venus Williams has WTA ids 18251 and 230220); a namesake only when dates of birth differ
            if dob and p.get("dob") and str(p["dob"])[:10] != str(dob)[:10]:
                pid = None
            else:
                for k, v in (("espn", espn), ("wta", wta)):
                    if v and p.get(k) and str(p[k]) != v:
                        alts = p.setdefault(f"{k}_alt", [])
                        if v not in alts:
                            alts.append(v)
                            self.dirty = True
                        (self.by_espn if k == "espn" else self.by_wta)[v] = pid
        if pid is None:
            pid = self._new_pid(espn, disp or raw)
            self.players[pid] = {"name": disp or raw, "first": str(first or "").strip() or (" ".join(fn).title() if fn else None),
                                 "last": str(last or "").strip() or (" ".join(ln).title() if ln else None),
                                 "short": None, "country": None, "hand": None, "dob": None, "height": None,
                                 "espn": espn, "wta": wta, "aliases": []}
            self.players[pid]["short"] = short_name(self.players[pid]["first"], self.players[pid]["last"])
            self._index(pid, self.players[pid])
            self.dirty = True
            self._count(src, "created")
        else:
            self._count(src, "linked")
            p = self.players[pid]
            if p.get("name", "").startswith(("x:",)) or (disp and len(name_tokens(disp)) > len(name_tokens(p.get("name"))) and not p.get("espn")):
                p["name"] = disp
            if disp and (not p.get("first") or not p.get("last") or p.get("_abbrev")) and last:
                p["first"], p["last"] = str(first).strip(), str(last).strip()
                p["short"] = short_name(p["first"], p["last"])
                p.pop("_abbrev", None)
                if disp:
                    p["name"] = disp
                self._reindex()
        self._fill(pid, espn=espn, wta=wta, country=country, dob=dob, hand=hand, height=height)
        self._add_alias(pid, raw)
        if espn and not pid == espn and pid.startswith("x:"):
            pid = self._promote(pid, espn)
        return pid

    def find(self, src: str, full: Any, hand: Any = None) -> str | None:
        """Resolve a full name without creating a player (charting, market names). A match records
        the name as an alias and fills the hand when the registry has none."""
        raw = str(full or "").strip()
        if not raw:
            return None
        self._count(src, "names")
        if raw in self.ov_names:
            pid = self.canonical(self.ov_names[raw])
            if pid in self.players:
                self._count(src, "override")
                return pid
        fn, ln = split_full(raw)
        pid = self._match_full(fn, ln, None, None, None)
        if pid is None and fn and ln:
            pid = self._match_abbrev_full(fn, ln, None)
        if pid is None and len(fn + ln) >= 3:
            # "Felix Auger Aliassime", "Alex De Minaur": try every first/last split of the tokens
            toks = fn + ln
            for k in range(1, len(toks)):
                pid = self._match_full(toks[:k], toks[k:], None, None, None)
                if pid:
                    break
        if pid is None and fn and ln:
            # a shortened compound surname: "Albert Ramos" for "Albert Ramos-Vinolas"
            hits = set()
            for c in self.by_surname.get(ln[0], set()):
                c = self.canonical(c)
                q = self.players.get(c) or {}
                if q.get("_abbrev"):
                    continue
                qf, ql = split_full(q.get("first"), q.get("last"), q.get("name"))
                if qf[:1] == fn[:1] and len(ql) > len(ln) and ql[: len(ln)] == ln:
                    hits.add(c)
            if len(hits) == 1:
                pid = hits.pop()
        if pid is None:
            self._count(src, "unresolved")
            self._miss(src, raw)
            return None
        self._count(src, "linked")
        self._add_alias(pid, raw)
        h = str(hand or "").strip().upper()[:1]
        if h in ("R", "L"):
            self._fill(pid, hand=h)
        return pid

    def _match_full(self, fn: list[str], ln: list[str], country: Any, dob: Any, field: Iterable[str] | None) -> str | None:
        key = full_key(fn, ln)
        cands = set(self.by_alias.get(key, set()))
        if fn and ln:
            cands |= self.by_alias.get(full_key(ln, fn), set())       # reversed order (Chinese names)
        cands = {self.canonical(c) for c in cands if self.canonical(c) in self.players}
        if not cands:
            return None
        if field:
            fs = set(field)
            inf = [c for c in cands if c in fs]
            if len(inf) == 1:
                return inf[0]
        if len(cands) == 1:
            c = next(iter(cands))
            p = self.players[c]
            if dob and p.get("dob") and str(p["dob"])[:10] != str(dob)[:10]:
                return None
            return c
        if country:
            cc = [c for c in cands if (self.players[c].get("country") or "").upper() == str(country).upper()]
            if len(cc) == 1:
                return cc[0]
        if dob:
            dd = [c for c in cands if str(self.players[c].get("dob") or "")[:10] == str(dob)[:10]]
            if len(dd) == 1:
                return dd[0]
        return None

    def _match_abbrev_full(self, fn: list[str], ln: list[str], field: Iterable[str] | None) -> str | None:
        """A full name against players known only by an abbreviated (tennis-data) name."""
        sj = "".join(ln)
        cands = [c for c in self.by_surname.get(sj, set()) if self.players.get(c, {}).get("_abbrev")]
        hits = []
        for c in cands:
            p = self.players[c]
            parsed = parse_abbrev(p.get("name"))
            if parsed and abbrev_matches(parsed[0], parsed[1], fn, ln) >= 2:
                hits.append(c)
        if field:
            fs = set(field)
            inf = [h for h in hits if h in fs]
            if len(inf) == 1:
                return inf[0]
        return hits[0] if len(hits) == 1 else None

    def resolve_abbrev(self, src: str, name: Any, field: Iterable[str] | None = None, create: bool = True,
                       has_field: bool = False) -> str | None:
        """A tennis-data "Surname I." name -> pid: the event's field first, then the whole tour,
        then an earlier alias; otherwise a new x:<slug> player (counted as unresolved when the
        event had a full-name field: `has_field`)."""
        raw = str(name or "").strip()
        if not raw:
            return None
        self._count(src, "names")
        if raw in self.ov_names:
            pid = self.canonical(self.ov_names[raw])
            if pid in self.players:
                self._count(src, "override")
                self._add_alias(pid, raw)
                return pid
        parsed = parse_abbrev(raw)
        fieldset = {self.canonical(f) for f in field} if field else set()
        if parsed:
            sur, inits = parsed
            pid = self._best_abbrev(sur, inits, fieldset) if fieldset else None
            if pid:
                self._count(src, "field")
                self._add_alias(pid, raw)
                return pid
            # earlier alias (same raw string), unique
            al = {self.canonical(c) for c in self.by_alias.get(fold(raw), set())}
            al = {c for c in al if c in self.players}
            if len(al) == 1:
                pid = next(iter(al))
                if not fieldset or pid in fieldset or not self.players[pid].get("espn") or not has_field:
                    self._count(src, "alias")
                    return pid
            pid = self._best_abbrev(sur, inits, None)
            if pid:
                self._count(src, "tour")
                self._add_alias(pid, raw)
                return pid
            # the event's only player with that surname, when no player anywhere fits the initials
            # ("Dolgopolov O." for "Alexandr Dolgopolov": the sources romanise the given name differently)
            if fieldset:
                sj = "".join(sur)
                only = []
                for c in fieldset:
                    pl = self.players.get(c)
                    if not pl or pl.get("_abbrev"):
                        continue
                    toks = name_tokens(pl.get("name"))
                    if sj == "".join(name_tokens(pl.get("last"))) or any("".join(toks[k:]) == sj for k in range(1, len(toks))):
                        only.append(c)
                if len(only) == 1:
                    self._count(src, "field_surname")
                    self._add_alias(only[0], raw)
                    return only[0]
        else:
            fn, ln = split_full(raw)
            pid = self._match_full(fn, ln, None, None, fieldset or None)
            if pid:
                self._count(src, "full")
                self._add_alias(pid, raw)
                return pid
        if not create:
            return None
        if has_field:
            self._miss(src, raw)
            self._count(src, "unresolved")
        else:
            self._count(src, "td_only")
        same = sorted(c for c in self.by_alias.get(fold(raw), set()) if (self.players.get(c) or {}).get("_abbrev"))
        if same:
            return same[0]
        pid = self._new_pid(None, raw)
        sur, inits = parsed if parsed else (name_tokens(raw), [])
        self.players[pid] = {"name": raw, "first": None, "last": " ".join(sur).title() if sur else raw,
                             "short": raw, "country": None, "hand": None, "dob": None, "height": None,
                             "espn": None, "wta": None, "aliases": [], "_abbrev": True}
        self._index(pid, self.players[pid])
        self.dirty = True
        return pid

    def _best_abbrev(self, sur: list[str], inits: list[str], fieldset: set[str] | None) -> str | None:
        sj = "".join(sur)
        pool = set()
        for key in (sj, sur[-1], sur[0]):
            pool |= self.by_surname.get(key, set())
        pool = {self.canonical(c) for c in pool}
        if fieldset is not None:
            pool &= fieldset
        scored = []
        for c in pool:
            p = self.players.get(c)
            if not p or p.get("_abbrev"):
                continue
            fn, ln = split_full(p.get("first"), p.get("last"), p.get("name"))
            s = abbrev_matches(sur, inits, fn, ln)
            if s:
                scored.append((s, c))
        if not scored and fieldset:
            # lenient, inside the event's field only: a surname token among the player's names and
            # the first initial on another of them ("Vallejo D." for "Adolfo Daniel Vallejo",
            # "Merida Aguilar D." for "Daniel Merida", "Barrios M." for "Marcelo Tomas Barrios Vera")
            for c in fieldset:
                p = self.players.get(c)
                if not p or p.get("_abbrev"):
                    continue
                toks = name_tokens(p.get("name"))
                hit = [k for k, t in enumerate(toks) if t in sur]
                if hit and any(t.startswith(inits[0][:1]) for k, t in enumerate(toks) if k not in hit):
                    scored.append((1, c))
        if not scored:
            return None
        top = max(s for s, _ in scored)
        best = [c for s, c in scored if s == top]
        if len(best) == 1:
            return best[0]
        return None

    def merge(self, keep: str, drop: str) -> str:
        """One player known under two pids (an ESPN profile and a WTA profile with different first
        names, "Catherine" / "Caty McNally"): `drop` folds into `keep` (ESPN ids win) and redirects."""
        keep, drop = self.canonical(keep), self.canonical(drop)
        if keep == drop or keep not in self.players or drop not in self.players:
            return keep
        if self.players[drop].get("espn") and not self.players[keep].get("espn"):
            keep, drop = drop, keep
        t, src = self.players[keep], self.players.pop(drop)
        for a in [src.get("name")] + list(src.get("aliases") or []):
            if a and a != t.get("name") and a not in t.setdefault("aliases", []):
                t["aliases"].append(a)
        for k in ("espn", "wta"):
            if src.get(k) and t.get(k) and str(src[k]) != str(t[k]):
                t.setdefault(f"{k}_alt", [])
                if str(src[k]) not in t[f"{k}_alt"]:
                    t[f"{k}_alt"].append(str(src[k]))
            for v in src.get(f"{k}_alt") or []:
                if v not in t.setdefault(f"{k}_alt", []):
                    t[f"{k}_alt"].append(v)
        for k, v in src.items():
            if k not in ("aliases", "espn_alt", "wta_alt", "_abbrev") and t.get(k) in (None, "") and v not in (None, ""):
                t[k] = v
        self.redirects[drop] = keep
        for k, v in list(self.redirects.items()):
            if v == drop:
                self.redirects[k] = keep
        self.dirty = True
        self._reindex()
        return keep

    def link_abbrev_players(self) -> int:
        """Merge x: players known only by a tennis-data name into a unique full-name player that
        matches it (run after a year's ESPN/WTA names are in). Returns the number merged."""
        n = 0
        for pid in [p for p, v in self.players.items() if v.get("_abbrev")]:
            if pid not in self.players:
                continue
            parsed = parse_abbrev(self.players[pid].get("name"))
            if not parsed:
                continue
            target = self._best_abbrev(parsed[0], parsed[1], None)
            if target and target != pid:
                src = self.players.pop(pid)
                t = self.players[target]
                for a in [src.get("name")] + list(src.get("aliases") or []):
                    if a and a not in t.setdefault("aliases", []) and a != t.get("name"):
                        t["aliases"].append(a)
                self.redirects[pid] = target
                for k, v in list(self.redirects.items()):
                    if v == pid:
                        self.redirects[k] = target
                n += 1
        if n:
            self.dirty = True
            self._reindex()
        return n

    def record(self, pid: str) -> dict:
        """The store's player record (CONTRACT section 1)."""
        p = self.players.get(self.canonical(pid)) or {}
        return {"name": p.get("name"), "short": p.get("short"), "country": p.get("country"), "hand": p.get("hand"),
                "dob": p.get("dob"), "height": p.get("height"), "espn": p.get("espn"), "wta": p.get("wta"),
                "aliases": list(p.get("aliases") or [])}

    def report(self) -> dict:
        out = {}
        for src, d in self.stats.items():
            names = d.get("names", 0)
            unres = d.get("unresolved", 0)
            out[src] = {**d, "rate": round(1 - unres / names, 4) if names else None,
                        "unresolved_examples": sorted(self.unresolved.get(src, {}).items(), key=lambda kv: -kv[1])[:25]}
        return out


# ── documentation of the source match record handed from sources/ to tn_fetch ─

SMR_DOC = """
Source match record (one per singles match per source; side "a"/"b" in the source's order,
"a" = winner for finished tennis-data rows):
  {"src": "td"|"espn"|"wta", "tour", "year",
   "event": {"name","city","country","start","end","level","series","surface","indoor","draw_size",
             "td","espn","wta"},
   "round", "round_raw", "date", "best_of",
   "a": {"name" | "first","last", "espn","wta","country","seed","entry","rank","pts"}, "b": {...},
   "winner": "a"|"b"|None, "status": "upcoming|live|done|ret|wo|def",
   "sets": [[ga, gb, tba, tbb]], "odds": {...}|None, "stats": {"a","b","by_set"}|None,
   "live": {"set","games":[ga,gb],"points":[pa,pb]|None,"server":"a"|"b"|None}|None,
   "duration_min", "src_id"}
"""
