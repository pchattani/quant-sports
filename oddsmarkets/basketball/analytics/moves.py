"""
Transactions, trade ratings and the pick-value curve for The Quant Hardwood (docs/VALUE_SECTIONS.md section 4;
payloads transactions.json and deals.json, PAYLOADS.md "Valuation, moves and fantasy").

Source: ESPN's transactions endpoint (sources/espn.py transactions_page), free text, one row per team per day, newest
first, paged by CALENDAR year. Cached under <cache>/transactions/<league>_<year>.json; a past year is fetched once
(re-fetched in January), the current year's first page is refreshed at most every TX_TTL_HOURS during the build.
No salary or contract source is used (Spotrac, HoopsHype and Basketball-Reference are left out: their terms forbid
reuse), so trades are rated on on-field value only.

Parsing
-------
A row's text is split into sentences; each sentence's leading verb gives its type (trade, signing, release, waiver
claim, contract, injury list, G League assignment, discipline, staff, other). In a trade sentence ("Acquired ...
from X in exchange for ...", "Traded ... to X for ...") the player mentions (a position tag such as G, F, C, G/F,
Gs, Fs followed by a name, or a further name after "and" / "," that matches a known player) before the exchange
marker are incoming, those after it outgoing; draft picks ("a 2027 second-round pick", "two second-round picks",
"the 22nd overall pick", "a 2028 first and second-round pick", "2nd round picks in 2027 and 2030", "a 2030 pick
swap") likewise, with protections ("top-10 protected", "lottery-protected", "unprotected"), "conditional" and the
pick's original owner ("originally belonging to the Phoenix Suns", "Chicago's 2026 first-round pick", "via X") where
the text states them; "draft considerations" and cash are noted and valued at zero. Names are matched to ESPN ids from
the stores (accents, apostrophes and suffixes normalised; a close match by edit similarity of at least NAME_CUTOFF
when the team context agrees); names that do not match are listed, never guessed.

Deals
-----
Trade sentences within DEAL_DAYS of each other are linked when they share a player or name each other's team; a
connected group is one deal (multi-team trades included). A player's source team is the team he last played for
before the date (box scores), else the team the text names; his destination is the team whose sentence lists him
as incoming. Picks are deduplicated across the two sides' sentences by (from, to, year, round).

Ratings (per side, in WAR; analytics/valuation.py)
--------------------------------------------------
value at the time  each incoming player's four-season value AS OF the trade date with no hindsight: his rate is
                   the last completed season's HPM before the trade plus the fitted ageing step, shrunk towards
                   replacement with PRIOR_SHRINK_MIN pseudo-minutes; minutes a game from his games before the date
                   (half-life 12 games); the receiving team's games left that season; availability and survival as in
                   valuation v2. A player with no completed season before the trade and a recent draft slot (a
                   rookie, draft rights) starts from his slot's curve value, blended with the model as he plays
                   (picks.ROOKIE_INFO_MIN minutes). Draft picks (analytics/picks.py): the curve over the owner's slot
                   distribution from the standings of the last season completed before the trade, protections,
                   swaps and conditions as stated, discounted 0.9 a season until the pick first plays. A known slot
                   that names a drafted player in the same side ("draft rights to X, the 10th overall pick") is the
                   player, not a second asset.
realised since     for each incoming player, the sum over his games for the new team after the date of
                   (that season's HPM - replacement) x his possessions / 100 / points per win, weighted 0.9^k by the
                   season (k seasons after the trade's season), so it is on the same footing.
current view       realised since + today's projection (valuation v2) of the seasons left in the trade's four-season
                   window while the player is still on that team. A pick not yet used: today's slot distribution
                   (the season simulation); a pick already used: the player it became for the team that holds it
                   (realised plus projection, with the slot prior until he has played), else the curve at its slot.
share and grade    share = value in / (value in + value out) on each basis (positive parts); A >= 0.65, B >= 0.55,
                   C 0.45-0.55, D >= 0.35, F below; a deal moving less than MINOR_WAR in total is "minor". The winner is
                   the side with the largest share; the league table sums each team's net (in - out).

Pick-value curve
----------------
analytics/picks.py: every reconstructable draft (NBA 1996-2022, WNBA 2018-2023), a pick's WAR over its first four
seasons (each floored at zero, discounted 0.9^j; never played = 0), a kernel smoother made non-increasing, with a
bootstrap band and a walk-forward validation on held-out drafts.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
import time
import unicodedata
from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import bio as BIO
from oddsmarkets.basketball.analytics import picks as PK
from oddsmarkets.basketball.analytics import valuation as VV
from oddsmarkets.basketball.analytics import value as VAL

logger = logging.getLogger(__name__)

VERSION = 2
TX_TTL_HOURS = 3.0
WINDOW_DAYS = 365
DEAL_DAYS = 3
NAME_CUTOFF = 0.84
PRIOR_SHRINK_MIN = 250.0
MINOR_WAR = 0.5
GRADE_CUTS = ((0.65, "A"), (0.55, "B"), (0.45, "C"), (0.35, "D"), (-1.0, "F"))

TYPES = {"trade": "Trade", "sign": "Signing", "release": "Waived / released", "claim": "Waiver claim", "contract": "Contract",
         "injury": "Injury list", "assign": "G League / assignment", "discipline": "Discipline", "staff": "Staff", "other": "Other"}
VERBS = (("acquired", "trade"), ("traded", "trade"), ("sent", "trade"), ("received", "trade"), ("signed", "sign"),
         ("re-signed", "sign"), ("resigned", "sign"), ("agreed", "sign"), ("matched", "sign"), ("waived", "release"),
         ("released", "release"), ("terminated", "release"), ("claimed", "claim"), ("converted", "contract"),
         ("exercised", "contract"), ("declined", "contract"), ("extended", "contract"), ("tendered", "contract"),
         ("placed", "injury"), ("activated", "injury"), ("reinstated", "injury"), ("recalled", "assign"), ("assigned", "assign"),
         ("suspended", "discipline"), ("fined", "discipline"), ("hired", "staff"), ("fired", "staff"), ("named", "staff"),
         ("promoted", "staff"), ("relieved", "staff"), ("announced", "other"), ("set", "other"), ("temporarily", "other"))
POS_TAG = r"(?:PG|SG|SF|PF|G/F|F/G|F/C|C/F|G-F|F-C|G|F|C)s?"
NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "both": 2}
ROUND_WORDS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}
STOP = {"from", "to", "for", "in", "and", "the", "a", "an", "draft", "cash", "considerations", "consideration", "with", "as", "of",
        "on", "off", "waivers", "exchange", "rights", "future", "two-way", "contract", "pick", "picks", "round", "second-round",
        "first-round", "who", "while", "both", "teams", "team", "three-team", "multi-team", "trade", "deal", "sent", "received",
        "acquired", "waived", "signed", "part", "seven-team", "four-team", "five-team"}
SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}


def _f(v: Any) -> float | None:
    return an.fnum(v)


def _r(v: Any, nd: int = 2) -> float | None:
    v = _f(v)
    return None if v is None else round(v, nd)


# ---------------------------------------------------------------------------------------------- source cache

def cache_path(league: str, year: int):
    return an.cache_root() / "transactions" / f"{league}_{int(year)}.json"


def fetch_year(league: str, year: int, client=None, full: bool = True, max_pages: int = 12) -> list[dict]:
    """Every row ESPN lists for a calendar year (full) or just the newest page."""
    from oddsmarkets.basketball.sources import espn
    c = client or espn.Client(budget=40, interval=0.5)
    out: list[dict] = []
    page = 1
    while page <= max_pages:
        raw = espn.transactions_page(c, league, year, page)
        if not raw:
            break
        out.extend(espn.parse_transactions(raw))
        if not full or page >= int(raw.get("pageCount") or 1):
            break
        page += 1
    return out


def _key(r: dict) -> tuple:
    return (r.get("date"), r.get("team"), r.get("text"))


def load_transactions(league: str, today: date, refresh: bool = True, client=None) -> tuple[list[dict], dict]:
    """Rows of this calendar year and last (cached; refreshed as the module docstring says). Never raises on the
    network: a failed refresh keeps the cache."""
    rows: list[dict] = []
    info = {"years": {}, "fetched": 0}
    for year in (today.year - 1, today.year):
        p = cache_path(league, year)
        c = an.read_json(p) if p.exists() else None
        cached = (c or {}).get("rows") or []
        at = float((c or {}).get("at") or 0)
        age_h = (time.time() - at) / 3600.0 if at else 1e9
        need_full = not c or (year < today.year and (c or {}).get("complete_year") != year and today.month == 1) or \
            (year < today.year and not (c or {}).get("complete_year") and today.month > 1)
        need_head = year == today.year and age_h > TX_TTL_HOURS
        if refresh and (need_full or need_head):
            try:
                got = fetch_year(league, year, client, full=need_full or age_h > 24.0)
                info["fetched"] += 1
                if got:
                    seen = {_key(r) for r in got}
                    merged = got + [r for r in cached if _key(r) not in seen]
                    cached = sorted(merged, key=lambda r: (r.get("date") or "", r.get("team") or ""), reverse=True)
                    payload = {"at": time.time(), "rows": cached}
                    if year < today.year:
                        payload["complete_year"] = year
                    an.write_json(p, payload)
            except Exception as exc:                     # noqa: BLE001  the network never breaks the build
                logger.warning("%s transactions %s refresh failed: %s", league, year, exc)
        info["years"][year] = len(cached)
        rows.extend(cached)
    seen = set()
    out = []
    for r in sorted(rows, key=lambda r: (r.get("date") or "", r.get("team") or "", r.get("text") or ""), reverse=True):
        k = _key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out, info


# ---------------------------------------------------------------------------------------------- names and teams

def norm(name: str) -> str:
    """Lower case, accents and punctuation stripped, suffixes (Jr., III) dropped."""
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = s.replace("’", "'").replace("`", "'").lower()
    s = re.sub(r"[^a-z0-9' \-]", " ", s)
    s = s.replace("'", "").replace("-", " ")
    toks = [t for t in s.split() if t]
    while toks and toks[-1] in SUFFIX:
        toks.pop()
    return " ".join(toks)


class NameIndex:
    """Player names -> ESPN ids, with each player's teams by date (box scores) for the team context."""

    def __init__(self, people: dict[str, str], stints: dict[str, list[tuple[str, str, str]]] | None = None,
                 rosters: dict[str, str] | None = None):
        self.names = {pid: n for pid, n in people.items() if n}
        self.by_norm: dict[str, list[str]] = {}
        for pid, n in self.names.items():
            self.by_norm.setdefault(norm(n), []).append(pid)
        self.stints = stints or {}                          # pid -> [(first date, last date, team)] in date order
        self.rosters = rosters or {}
        self._keys = list(self.by_norm)

    def team_before(self, pid: str, d: str) -> str | None:
        last = None
        for a, b, t in self.stints.get(pid) or []:
            if a < d:
                last = t
        return last

    def team_after(self, pid: str, d: str) -> str | None:
        for a, b, t in self.stints.get(pid) or []:
            if a >= d:
                return t
        return self.rosters.get(pid)

    def match(self, name: str, d: str | None = None, teams: Iterable[str] = ()) -> str | None:
        teams = {str(t) for t in teams if t}
        k = norm(name)
        if not k:
            return None
        cands = self.by_norm.get(k) or []
        if not cands:
            close = difflib.get_close_matches(k, self._keys, n=4, cutoff=NAME_CUTOFF)
            # a close match must share the last name's first letters (typos, not different people)
            close = [c for c in close if c.split()[-1][:3] == k.split()[-1][:3] or c.split()[0] == k.split()[0]]
            cands = [pid for c in close for pid in self.by_norm.get(c, [])]
            if not cands:
                return None
            if teams and d:
                ok = [p for p in cands if self._teams_near(p, d) & teams]
                if ok:
                    cands = ok
                elif len(close) > 1:
                    return None
        if len(cands) == 1:
            return cands[0]
        if d:
            ok = [p for p in cands if self._teams_near(p, d) & teams] if teams else []
            if len(ok) == 1:
                return ok[0]
            recent = sorted(cands, key=lambda p: max([b for a, b, t in self.stints.get(p) or []] or [""]), reverse=True)
            return recent[0]
        return cands[0]

    def _teams_near(self, pid: str, d: str) -> set[str]:
        s = {t for a, b, t in self.stints.get(pid) or []}
        if pid in self.rosters:
            s.add(self.rosters[pid])
        return s


class TeamIndex:
    """Team mentions in text -> team ids (full names, nicknames, locations when unique, abbreviations, common
    variants such as "L.A. Clippers")."""

    def __init__(self, teams: dict[str, dict]):
        self.alias: dict[str, str] = {}
        loc_count: dict[str, int] = {}
        for t in teams.values():
            loc = norm(t.get("location") or "")
            loc_count[loc] = loc_count.get(loc, 0) + 1
        for tid, t in teams.items():
            name = norm(t.get("name") or "")
            loc = norm(t.get("location") or "")
            nick = name[len(loc):].strip() if loc and name.startswith(loc) else name.split(" ")[-1] if name else ""
            for a in (name, nick, f"the {name}"):
                if a:
                    self.alias[a] = str(tid)
            if loc and loc_count.get(loc) == 1:
                self.alias[loc] = str(tid)
            if loc == "los angeles" and nick:
                for v in ("la", "l a"):
                    self.alias[f"{v} {nick}"] = str(tid)
            if t.get("abbr"):
                self.alias.setdefault(str(t["abbr"]).lower(), str(tid))
            if loc == "golden state":
                self.alias["golden state"] = str(tid)
        pats = sorted((a for a in self.alias if len(a) > 2), key=len, reverse=True)
        self._pat = re.compile(r"\b(" + "|".join(r"\s+".join(re.escape(w) for w in a.split(" ")) for a in pats) + r")\b") \
            if pats else None

    def find(self, text: str) -> list[tuple[int, str]]:
        """[(start, end, team id)] in order (positions are the original sentence's)."""
        if not self._pat:
            return []
        out = []
        for m in self._pat.finditer(flat_text(text)):
            key = " ".join(m.group(1).split())
            if key in self.alias:
                out.append((m.start(), m.end(), self.alias[key]))
        return out


def flat_text(text: str) -> str:
    """Lower case, accents dropped, every other non-alphanumeric character a space, one for one, so positions match
    the original sentence ("L.A. Clippers" reads "l a  clippers")."""
    out = []
    for c in str(text or ""):
        d = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode()[:1]
        out.append(d.lower() if d and d.isalnum() else " ")
    return "".join(out)


# ---------------------------------------------------------------------------------------------- parsing

def sentences(text: str) -> list[str]:
    """Split on sentence ends that are not abbreviations (Jr., Sr., L.A., initials)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = re.sub(r"\.(?=[A-Z][a-z])", ". ", t)                # "contract .Acquired" / "contract.Acquired"
    parts, buf = [], ""
    for tok in re.split(r"(?<=\.)\s+", t):
        buf = (buf + " " + tok).strip() if buf else tok
        last = buf.split(" ")[-1] if buf else ""
        if re.search(r"(?:\bJr|\bSr|\bSt|\bL\.A|\b[A-Z]|\bNo|\bvs)\.$", last) or re.search(r"\b[A-Z]\.[A-Z]\.$", last):
            continue
        parts.append(buf)
        buf = ""
    if buf:
        parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def sentence_type(s: str) -> str:
    w = s.strip().split(" ")[0].lower().rstrip(",") if s.strip() else ""
    for v, t in VERBS:
        if w == v:
            if t == "trade" and re.search(r"off waivers|waiver claim", s, re.I):
                return "claim"
            if t == "assign" or (t == "trade" and w == "sent" and re.search(r"g league|g-league|to the .* \(g", s, re.I)):
                return "assign"
            return t
    if re.search(r"\btrade\b|\bacquired\b", s, re.I):
        return "trade"
    return "other"


EXCHANGE = re.compile(r"\bin exchange for\b|\bin exchange\b|\bfor\b|\band sent\b|\bwhile sending\b|\bsending\b|\bsent\b", re.I)
UPPER = "A-ZÀ-ÖØ-ÞĀĂĄĆĈĊČĎĐĒĔĖĘĚĜĞĠĢĤĦĨĪĬĮİĴĶĹĻĽĿŁŃŅŇŌŎŐŒŔŖŘŚŜŞŠŢŤŦŨŪŬŮŰŲŴŶŸŹŻŽ"
NAME_TOK = (r"[" + UPPER + r"][\w'’\-\.]*(?:\s(?:[" + UPPER + r"][\w'’\-\.]*|de|da|del|van|der|la|le|di|du|von|St\.))*")


def mentions(s: str, idx: NameIndex | None = None) -> list[tuple[int, str]]:
    """[(position, name)] of player mentions in a sentence."""
    out = []
    for m in re.finditer(r"\b(" + POS_TAG + r")\s+(" + NAME_TOK + r")", s):
        tag, rest = m.group(1), m.group(2)
        names = [rest]
        # a plural tag or an "and"/"," continuation names further players
        pos = m.end()
        tail = s[pos:]
        while True:
            mm = re.match(r"\s*(?:,\s*(?:and\s+)?|\s+and\s+)(" + NAME_TOK + r")", tail)
            if not mm:
                break
            nxt = mm.group(1)
            first = nxt.split(" ")[0]
            if re.fullmatch(POS_TAG, first) or first.lower() in STOP or re.match(r"\d", first):
                break
            if not tag.endswith("s") and (idx is None or not idx.by_norm.get(norm(nxt))):
                break
            names.append(nxt)
            tail = tail[mm.end():]
            pos += mm.end()
        for n in names:
            n = _trim_name(n)
            if n:
                out.append((s.find(n, m.start()), n))
    return out


def _trim_name(n: str) -> str:
    toks = n.strip().rstrip(".,").split(" ")
    keep = []
    for t in toks:
        if t.lower().rstrip(".,") in STOP and keep:
            break
        keep.append(t)
    # "Jr" written without a period stays; a trailing period of "Jr." is restored by norm()
    return " ".join(keep).strip().rstrip(",")


MOD = r"(?:(?:future|unprotected|conditional|lottery[- ]protected|top[- ]\d{1,2}[- ]protected|protected)\s+)*"
RND = r"(first|second|third|1st|2nd|3rd)"
PICK_RE = [
    # "a 2027 second-round pick", "two second-round draft picks", "a 2028 first and second-round pick", "an unprotected
    # 2031 first-round draft pick", "a 2030 conditional second-round draft pick", "Chicago's 2026 first-round pick"
    re.compile(r"\b(?:(a|an|one|two|three|four|five|six|both|\d)\s+)?" + MOD + r"(?:(\d{4,5})\s+)?" + MOD + RND +
               r"(?:\s*(?:-|\s)?\s*(?:and|&)\s+" + RND + r")?[- ]round(?:\s+draft)?\s+picks?(?:\s+in\s+the\s+(\d{4,5})(?:\s+\w+)?\s+draft)?(\s+swap)?", re.I),
    # "2nd round picks in 2027 and 2030"
    re.compile(r"\b(first|second|third|1st|2nd|3rd)[- ]round\s+picks?\s+in\s+(\d{4})(?:\s*(?:,|and)\s*(\d{4}))?(?:\s*(?:,|and)\s*(\d{4}))?", re.I),
    # "the 22nd overall pick", "a No. 29 pick in the 2025 draft", "the 10th overall pick in the 2025 draft", "the 2025 No. 11 pick"
    re.compile(r"\b(?:the|a)\s+(?:(\d{4})\s+)?(?:No\.\s*)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:overall\s+)?(?:draft\s+)?pick(?:\s+in\s+the\s+(\d{4})\s+draft)?", re.I),
    # "a second-round pick swap", "first-round pick swap in the 2026 draft", "a 2030 pick swap"
    re.compile(r"\b(?:(\d{4})\s+)?(?:(first|second|1st|2nd)[- ]round\s+)?(?:draft\s+)?pick\s+swap(?:\s+in\s+the\s+(\d{4})\s+draft)?", re.I),
]
PROTECT_RE = re.compile(r"\b(?:top[- ](\d{1,2})[- ]protected|(lottery)[- ]protected|(unprotected))\b", re.I)
ORIGIN_RE = re.compile(r"^\W*(?:\(\s*)?(?:originally\s+(?:belonging\s+to|owned\s+by|from)|via|belonging\s+to|owned\s+by)\s+(?:the\s+)?", re.I)


def picks_in(s: str, default_year: int | None = None) -> list[dict]:
    """[{"pos", "end", "year", "round", "overall", "n", "swap", "protect", "cond"}] for the draft picks mentioned in a
    sentence. protect: N for "top-N protected" ("lottery-protected" -> "lottery"), 0 for "unprotected", None when the
    text says nothing; cond: "conditional" is in the phrase."""
    out = []
    used: list[tuple[int, int]] = []

    def free(a, b):
        return all(b <= x or a >= y for x, y in used)

    def extra(a, b):
        seg = s[a:min(len(s), b + 40)]
        nxt = re.search(r"\b(?:and|for|from|in exchange)\b", s[b:b + 40], re.I)
        if nxt:
            seg = s[a:b + nxt.start()]
        m = PROTECT_RE.search(seg)
        prot = None
        if m:
            prot = int(m.group(1)) if m.group(1) else ("lottery" if m.group(2) else 0)
        return prot, bool(re.search(r"\bconditional\b", seg, re.I))

    for m in PICK_RE[3].finditer(s):
        used.append((m.start(), m.end()))
        rd = ROUND_WORDS[m.group(2).lower()] if m.group(2) else 1
        prot, cond = extra(m.start(), m.end())
        out.append({"pos": m.start(), "end": m.end(), "year": _year(m.group(1) or m.group(3)), "round": rd, "overall": None, "n": 1,
                    "swap": True, "protect": prot, "cond": cond, "round_stated": bool(m.group(2))})
    for m in PICK_RE[1].finditer(s):
        if not free(m.start(), m.end()):
            continue
        used.append((m.start(), m.end()))
        rd = ROUND_WORDS[m.group(1).lower()]
        prot, cond = extra(m.start(), m.end())
        for g in (m.group(2), m.group(3), m.group(4)):
            if g:
                out.append({"pos": m.start(), "end": m.end(), "year": int(g), "round": rd, "overall": None, "n": 1, "swap": False,
                            "protect": prot, "cond": cond})
    for m in PICK_RE[0].finditer(s):
        if not free(m.start(), m.end()):
            continue
        used.append((m.start(), m.end()))
        c = m.group(1)
        n = NUM_WORDS.get(c.lower(), None) if c else 1
        if n is None:
            n = int(c) if c.isdigit() else 1
        year = _year(m.group(2) or m.group(5))
        swap = bool(m.group(6))
        prot, cond = extra(m.start(), m.end())
        rounds = [ROUND_WORDS[m.group(3).lower()]] + ([ROUND_WORDS[m.group(4).lower()]] if m.group(4) else [])
        for rd in rounds:
            out.append({"pos": m.start(), "end": m.end(), "year": year, "round": rd, "overall": None, "n": n, "swap": swap,
                        "protect": prot, "cond": cond})
    for m in PICK_RE[2].finditer(s):
        if not free(m.start(), m.end()):
            continue
        used.append((m.start(), m.end()))
        ov = int(m.group(2))
        out.append({"pos": m.start(), "end": m.end(), "year": _year(m.group(1) or m.group(3)), "round": None, "overall": ov, "n": 1,
                    "swap": False, "protect": None, "cond": False})
    return sorted(out, key=lambda p: p["pos"])


def pick_origin(s: str, pk: dict, teams: "TeamIndex", nxt: int | None = None) -> str | None:
    """The team whose pick it is when the text says so: "originally belonging to the Phoenix Suns", "(via Detroit)"
    after the pick, or a possessive just before it ("Chicago's 2026 first-round pick")."""
    tail_end = min(len(s), nxt if nxt is not None else len(s), pk["end"] + 70)
    tail = s[pk["end"]:tail_end]
    m = ORIGIN_RE.match(tail)
    if m:
        hits = teams.find(tail[m.end():m.end() + 40])
        if hits and hits[0][0] <= 2:
            return hits[0][2]
    head = s[max(0, pk["pos"] - 40):pk["pos"]]
    mm = re.search(r"([A-Za-z.\s]+?)['’]s\s*$", head)
    if mm:
        hits = teams.find(mm.group(1))
        if hits:
            return hits[-1][2]
    return None


def _year(s: str | None) -> int | None:
    if not s:
        return None
    s = str(s)
    if len(s) == 5 and s.startswith("20"):         # "20227" -> 2027 (a typo seen in ESPN's text)
        s = s[:2] + s[3:]
    try:
        y = int(s)
    except ValueError:
        return None
    return y if 1990 <= y <= 2100 else None


def parse_row(row: dict, names: NameIndex, teams: TeamIndex) -> dict:
    """{"date","team","text","types","sents": [{"type","in": [pid|name], "out", "picks_in", "picks_out", "teams",
    "unmatched", "zero": [notes]}], "players": [pids]}."""
    d = row.get("date") or ""
    team = str(row.get("team") or "")
    out = {"date": d, "team": team, "abbr": row.get("abbr"), "text": row.get("text"), "types": [], "sents": [], "players": []}
    for s in sentences(row.get("text") or ""):
        typ = sentence_type(s)
        if typ not in out["types"]:
            out["types"].append(typ)
        ms = mentions(s, names)
        tm = teams.find(s)
        info = {"type": typ, "text": s, "in": [], "out": [], "picks_in": [], "picks_out": [], "teams": [], "unmatched": [], "zero": [],
                "hint": {}}
        for _p, _e, t in tm:
            if t != team and t not in info["teams"]:
                info["teams"].append(t)
        ex = EXCHANGE.search(s) if typ == "trade" else None
        cut = ex.start() if ex else len(s) + 1
        verb = s.strip().split(" ")[0].lower()
        flip = verb == "traded"                        # "Traded X to Y for Z": X goes out, Z comes in
        for pos, nm in ms:
            pid = names.match(nm, d, [team] + info["teams"])
            if pid is None:
                info["unmatched"].append(nm)
                continue
            if pid not in out["players"]:
                out["players"].append(pid)
            if typ == "trade":
                incoming = (pos < cut) != flip
                info["in" if incoming else "out"].append(pid)
                # the team the text ties the player to: a team named just before his position tag ("Detroit G Jaden
                # Ivey"), else the first team named after him ("... from Chicago", "... to Cleveland")
                after = [t for p, _e, t in tm if p > pos]
                lead = [t for p, e, t in tm if e <= pos and re.fullmatch(r"\s+(?:" + POS_TAG + r")\s+", s[e:pos])]
                hint = lead[-1] if lead else (after[0] if after else None)
                if hint and hint != team:
                    info["hint"][pid] = hint
        if typ == "trade":
            pks = picks_in(s)
            for i_pk, pk in enumerate(pks):
                incoming = (pk["pos"] < cut) != flip
                nxt = pks[i_pk + 1]["pos"] if i_pk + 1 < len(pks) else None
                rec = {k: pk.get(k) for k in ("year", "round", "overall", "n", "swap", "protect", "cond")}
                rec["origin"] = pick_origin(s, pk, teams, nxt)
                info["picks_in" if incoming else "picks_out"].append(rec)
            for z in ("draft consideration", "cash consideration", "future consideration", "cash"):
                if z in s.lower() and z not in info["zero"]:
                    info["zero"].append(z)
        out["sents"].append(info)
    return out


# ---------------------------------------------------------------------------------------------- deals

def build_deals(parsed: list[dict], names: NameIndex) -> list[dict]:
    """Group trade sentences into deals. Returns [{"id","date","teams","rows": [texts], "players": {pid: [from, to]},
    "picks": [{"from","to","year","round","overall","n","swap"}], "zero": [notes]}]."""
    items = []                                           # (row index, sentence index, team, date, info)
    for i, r in enumerate(parsed):
        for j, s in enumerate(r["sents"]):
            if s["type"] == "trade" and (s["in"] or s["out"] or s["picks_in"] or s["picks_out"] or s["teams"]):
                items.append((i, j, r["team"], r["date"], s))
    parent = list(range(len(items)))
    days: dict[int, dict[str, str]] = {k: {items[k][2]: items[k][3]} for k in range(len(items))}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        """Merge two groups unless a team would appear in both on different days (the same two teams trading again
        a day or two later is a separate deal; chaining them would merge a deadline's trades)."""
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        da, db = days[ra], days[rb]
        if any(t in da and da[t] != d for t, d in db.items()):
            return
        parent[rb] = ra
        da.update(db)

    def near(d1, d2):
        try:
            return abs((date.fromisoformat(d1) - date.fromisoformat(d2)).days) <= DEAL_DAYS
        except ValueError:
            return False

    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            ia, ib = items[a], items[b]
            if ia[2] == ib[2] or not near(ia[3], ib[3]):
                continue
            sa, sb = ia[4], ib[4]
            # the two sides of one deal name each other; a player crossing between them (in for one, out for the
            # other) links them when only one side names the other. Sharing a player alone does not: players are
            # flipped on in later deals around a deadline, and chaining on them would merge separate trades.
            names_each = ib[2] in sa["teams"] and ia[2] in sb["teams"]
            crossing = bool((set(sa["in"]) & set(sb["out"])) | (set(sa["out"]) & set(sb["in"])))
            one_way = ib[2] in sa["teams"] or ia[2] in sb["teams"]
            if names_each or (crossing and one_way):
                union(a, b)
    groups: dict[int, list[int]] = {}
    for k in range(len(items)):
        groups.setdefault(find(k), []).append(k)
    deals = []
    moved: dict[str, tuple[str, str]] = {}               # pid -> (date, team) of his latest move, oldest deals first
    for g, members in sorted(groups.items(), key=lambda kv: min(items[k][3] for k in kv[1])):
        rows = [items[k] for k in members]
        teams = []
        for _i, _j, t, _d, s in rows:
            for x in [t] + s["teams"]:
                if x and x not in teams:
                    teams.append(x)
        d0 = min(r[3] for r in rows)
        players: dict[str, list] = {}
        # source: a side listing him outgoing > the team the text ties him to > his latest earlier move > the team he
        # last played for; destination: the side listing him incoming > the text > the only other side > his next team
        for _i, _j, t, d, s in rows:
            for pid in s["out"]:
                cur = players.setdefault(pid, [None, None])
                cur[0] = t
        for _i, _j, t, d, s in rows:
            for pid in s["in"]:
                cur = players.setdefault(pid, [None, None])
                cur[1] = t
        for _i, _j, t, d, s in rows:
            for pid in s["in"]:
                cur = players[pid]
                if cur[0] is None:
                    h = s["hint"].get(pid)
                    mv = moved.get(pid)
                    last = names.team_before(pid, d0)
                    last_d = max([b for a, b, tt in names.stints.get(pid) or [] if a < d0] or [""])
                    cur[0] = h or (mv[1] if mv and mv[0] >= last_d and mv[1] != t else None) or (last if last != t else None)
            for pid in s["out"]:
                cur = players[pid]
                if cur[1] is None:
                    h = s["hint"].get(pid)
                    others = [x for x in s["teams"] if x != t]
                    cur[1] = h or (others[0] if len(others) == 1 else None) or names.team_after(pid, d0)
        for pid, ft in players.items():
            if ft[0] == ft[1]:
                ft[0] = None
            if ft[1]:
                moved[pid] = (d0, ft[1])
            for x in ft:
                if x and x not in teams:
                    teams.append(x)
        # picks: (from, to, year, round, overall) -> count, the larger of the two sides' mentions
        pk: dict[tuple, dict] = {}
        for _i, _j, t, d, s in rows:
            others = [x for x in s["teams"] if x != t]
            cp = others[0] if len(others) == 1 else (([x for x in teams if x != t] + [None])[0] if len(teams) == 2 else None)
            for p in s["picks_in"]:
                key = (cp, t, p["year"], p["round"], p["overall"], p["swap"])
                if key not in pk or pk[key]["n"] < p["n"]:
                    pk[key] = {"from": cp, "to": t, **p}
            for p in s["picks_out"]:
                key = (t, cp, p["year"], p["round"], p["overall"], p["swap"])
                if key not in pk or pk[key]["n"] < p["n"]:
                    pk[key] = {"from": t, "to": cp, **p}
        # the same pick seen from both sides with one side's counterparty unknown
        merged: dict[tuple, dict] = {}
        for key, p in sorted(pk.items(), key=lambda kv: (kv[1]["from"] is None or kv[1]["to"] is None)):
            twin = None
            for k2, q in merged.items():
                if (q["year"], q["round"], q["overall"], q["swap"]) == (p["year"], p["round"], p["overall"], p["swap"]) and \
                        (p["from"] in (q["from"], None)) and (p["to"] in (q["to"], None)):
                    twin = k2
                    break
            if twin is None:
                merged[key] = p
            else:
                merged[twin]["n"] = max(merged[twin]["n"], p["n"])
        zero = sorted({z for r in rows for z in r[4]["zero"]})
        did = hashlib.sha1(json.dumps([d0, sorted(teams), sorted(players)], default=str).encode()).hexdigest()[:10]
        deals.append({"id": did, "date": d0, "teams": teams, "rows": [{"team": r[2], "date": r[3], "text": r[4]["text"]} for r in rows],
                      "players": players, "picks": list(merged.values()), "zero": zero})
    deals.sort(key=lambda x: x["date"], reverse=True)
    return deals


# ---------------------------------------------------------------------------------------------- picks

def draft_held_before(league: str, d: str) -> int:
    """The latest draft held on or before a date (NBA late June, WNBA mid April)."""
    dd = date.fromisoformat(d[:10])
    cut = (4, 15) if str(league).lower() == "wnba" else (6, 24)
    return dd.year if (dd.month, dd.day) >= cut else dd.year - 1


def _protect(league: str, v) -> int | None:
    if v == "lottery":
        return PK.LOTTERY_PROTECT[PK._lg(league)]
    return int(v) if v else None


def pick_label(p: dict) -> str:
    if p.get("overall"):
        return f"No. {p['overall']} pick" + (f" ({p['year']})" if p.get("year") else "")
    rd = PK.ordinal(p.get("round") or 1)
    yr = f"{p['year']} " if p.get("year") else "future "
    lab = f"{yr}{rd}"
    if p.get("swap"):
        lab += " swap" if p.get("round_stated", True) else " swap (round not stated: 1st assumed)"
    if p.get("protect") == 0:
        lab += ", unprotected"
    elif p.get("protect") == "lottery":
        lab += ", lottery-protected"
    elif p.get("protect"):
        lab += f", top-{p['protect']} protected"
    if p.get("cond"):
        lab += ", conditional"
    return lab


def selection(league: str, hist: dict, year: int, rnd: int | None, holder: str | None, overall: int | None = None) -> tuple[int, str | None] | None:
    """(overall, pid) of the player a used pick became: the slot when known, else the holder's one selection in that
    round (the traded one when he made several); None when the draft is not held or the holder is ambiguous."""
    h = (hist or {}).get(int(year)) if year else None
    if not h or not h.get("listed"):
        return None
    if overall:
        return int(overall), h["slots"].get(int(overall))
    cands = [ov for ov, t in h["team"].items() if t == str(holder) and (rnd is None or h["round_of"].get(ov) == int(rnd))]
    if len(cands) > 1:
        tr = [ov for ov in cands if h["traded"].get(ov)]
        cands = tr if len(tr) == 1 else cands
    if len(cands) != 1:
        return None
    return cands[0], h["slots"].get(cands[0])


def pick_item(league: str, p: dict, d: str, s_tr: int, pm: "PK.PickModel", ctx_data: dict, today: date,
              player_fn=None) -> dict:
    """One traded pick: value at the time (no hindsight) and today's view (see the module docstring)."""
    n = int(p.get("n") or 1)
    frm, to = p.get("from"), p.get("to")
    origin = p.get("origin") or frm
    prot = _protect(league, p.get("protect"))
    cond = bool(p.get("cond"))
    item = {"kind": "pick", "label": pick_label(p), "year": p.get("year"), "round": p.get("round"), "overall": p.get("overall"), "n": n,
            "swap": bool(p.get("swap")), "via": origin if origin and origin != frm else None, "protect": p.get("protect"), "cond": cond,
            "realised": 0.0}
    if p.get("overall"):
        year = p.get("year") or draft_held_before(league, d)
        fs = PK.first_season(league, year)
        v = PK.curve_at(pm.curve, int(p["overall"])) * (PK.DISCOUNT ** max(0, fs - s_tr)) * n
        item.update({"year": year, "v_time": v, "v_now": v, "slot": [int(p["overall"])] * 2, "slot_now": [int(p["overall"])] * 2,
                     "note": "known slot"})
        sel = selection(league, ctx_data.get("draft_hist") or {}, year, None, to, int(p["overall"]))
    else:
        swap_with = to if p.get("swap") else None
        org = frm if p.get("swap") else origin
        at = pm.value(org, p.get("year"), p.get("round"), s_tr, basis="time", protect=prot, conditional=cond, swap_with=swap_with, n=n)
        nw = pm.value(org, p.get("year"), p.get("round"), s_tr, basis="now", protect=prot, conditional=cond, swap_with=swap_with, n=n)
        item.update({"year": at["year"], "v_time": at["v"], "v_now": nw["v"], "slot": at["slot"], "slot_now": nw["slot"], "note": nw["note"],
                     "p_convey": nw.get("p_convey")})
        sel = None
        if not p.get("swap") and n == 1 and at["year"] <= max(BIO.drafts(league) or {0: 0}):
            sel = selection(league, ctx_data.get("draft_hist") or {}, at["year"], p.get("round"), to)
            if sel:
                fs = PK.first_season(league, at["year"])
                item["v_now"] = PK.curve_at(pm.curve, sel[0]) * (PK.DISCOUNT ** max(0, fs - s_tr))
                item["slot_now"] = [sel[0], sel[0]]
                item["note"] = "used: the curve at its slot"
    item["remaining"] = item["v_now"]
    if sel and sel[1] and player_fn is not None:
        # the pick has been used: today's view is the player it became, for the team that holds it
        dd = f"{int(item['year'])}-{'04-15' if str(league).lower() == 'wnba' else '06-26'}"
        it = player_fn(sel[1], dd, to)
        if it is not None:
            item.update({"v_now": it["v_now"], "realised": it["realised"], "remaining": it["remaining"], "player": sel[1],
                         "player_name": it.get("name"), "slot_now": [sel[0], sel[0]], "note": f"used: No. {sel[0]}"})
    return item


def _rookie_prior(league: str, pid: str, s_tr: int, curve: dict) -> tuple[float, int] | None:
    """(slot curve value discounted to the trade's season, overall) for a player drafted within the last two drafts."""
    ds = BIO.draft_slot(league, pid)
    if not ds or not ds[0] or not ds[2]:
        return None
    fs = PK.first_season(league, int(ds[0]))
    if fs < s_tr - 1:
        return None
    return PK.curve_at(curve, int(ds[2])) * (PK.DISCOUNT ** max(0, fs - s_tr)), int(ds[2])


# ---------------------------------------------------------------------------------------------- per-player history

def season_war_rows(league: str, seasons: Iterable[int]) -> tuple[dict[int, dict[str, float]], dict[int, dict[str, dict]]]:
    """({season: {pid: WAR}}, {season: {pid: value.json row}}) from each season's value.json."""
    war: dict[int, dict[str, float]] = {}
    rows: dict[int, dict[str, dict]] = {}
    for s in seasons:
        v = an.read_json(an.data_root() / league / str(s) / "value.json") or {}
        cols = v.get("cols") or []
        if not cols:
            continue
        rr = {}
        for r in v.get("rows") or []:
            x = dict(zip(cols, r))
            rr[str(x["id"])] = x
        rows[s] = rr
        war[s] = {k: (_f(x.get("war")) or 0.0) for k, x in rr.items()}
    return war, rows


def stints_from_box(frames: Iterable) -> dict[str, list[tuple[str, str, str]]]:
    """{pid: [(first date, last date, team)]} from box frames (consecutive games with the same team)."""
    out: dict[str, list[list]] = {}
    for bx in frames:
        if bx is None or bx.empty:
            continue
        b = bx[bx["sec"] > 0].sort_values("date")
        for pid, team, d in zip(b["player_id"], b["team"], b["date"]):
            st = out.setdefault(str(pid), [])
            if st and st[-1][2] == str(team):
                st[-1][1] = str(d)
            else:
                st.append([str(d), str(d), str(team)])
    return {k: [tuple(x) for x in sorted(v)] for k, v in out.items()}


def season_of_date(league: str, d: str) -> int:
    """The season a date belongs to; offseason dates belong to the coming season."""
    dd = date.fromisoformat(d[:10])
    if str(league).lower() == "wnba":
        return dd.year if dd.month <= 10 else dd.year + 1
    return dd.year + 1 if dd.month >= 7 else dd.year


# ---------------------------------------------------------------------------------------------- ratings

def grade(share: float | None, total: float) -> str | None:
    if share is None:
        return None
    if total < MINOR_WAR:
        return "minor"
    for cut, g in GRADE_CUTS:
        if share >= cut:
            return g
    return "F"


def rate_deals(league: str, deals: list[dict], ctx_data: dict, fit: dict, prm: dict, pm: "PK.PickModel", today: date) -> list[dict]:
    """Ratings for each deal (see the module docstring). ctx_data: {"rows": {season: {pid: value row}}, "box": DataFrame
    of player-games (seasons around the window, with team_poss / sec), "games_left": {season: {team: {date: left}}},
    "valuation": {pid: today's valuation row dict}, "names": {pid: name}, "current": season, "roster": {pid: team},
    "draft_hist": picks.history(...)}; pm: the pick model (analytics/picks.py)."""
    rows_by = ctx_data["rows"]
    box = ctx_data["box"]
    val_now = ctx_data.get("valuation") or {}
    names = ctx_data.get("names") or {}
    cur_season = ctx_data["current"]
    roster = ctx_data.get("roster") or {}
    out = []
    by_player = {pid: g for pid, g in box.groupby("player_id")} if box is not None and not box.empty else {}
    slot_seasons = ctx_data.get("slot_seasons") or []
    for dl in deals:
        d = dl["date"]
        s_tr = season_of_date(league, d)
        sides = {t: {"team": t, "in": [], "out": []} for t in dl["teams"]}
        slots_in: dict[str, set] = {}
        for pid, (frm, to) in dl["players"].items():
            item = _player_item(league, pid, d, s_tr, to, rows_by, by_player.get(pid), fit, prm, ctx_data, val_now, roster, slot_seasons, names,
                                pm.curve)
            if item.get("draft_slot"):
                slots_in.setdefault(to, set()).add(item["draft_slot"])
            if to in sides:
                sides[to]["in"].append(item)
            if frm in sides:
                sides[frm]["out"].append(item)

        def player_fn(pid, dd, team):
            return _player_item(league, pid, dd, s_tr, team, rows_by, by_player.get(pid), fit, prm, ctx_data, val_now, roster, slot_seasons,
                                names, pm.curve)
        for p in dl["picks"]:
            if p.get("overall") and int(p["overall"]) in (slots_in.get(p.get("to")) or set()):
                continue                                 # "draft rights to X, the 10th overall pick": X is the asset
            item = pick_item(league, p, d, s_tr, pm, ctx_data, today, player_fn)
            if p.get("to") in sides:
                sides[p["to"]]["in"].append(item)
            if p.get("from") in sides:
                sides[p["from"]]["out"].append(item)
        res_sides = []
        for t, sd in sides.items():
            if not sd["in"] and not sd["out"]:
                continue
            pos = lambda xs, k: sum(max(0.0, x.get(k) or 0.0) for x in xs)  # noqa: E731
            vin, vout = pos(sd["in"], "v_time"), pos(sd["out"], "v_time")
            nin, nout = pos(sd["in"], "v_now"), pos(sd["out"], "v_now")
            rin, rout = sum(x.get("realised") or 0.0 for x in sd["in"]), sum(x.get("realised") or 0.0 for x in sd["out"])
            st = vin / (vin + vout) if vin + vout > 1e-9 else None
            sn = nin / (nin + nout) if nin + nout > 1e-9 else None
            res_sides.append({"team": t, "in": sd["in"], "out": sd["out"], "v_in": vin, "v_out": vout, "share_time": st,
                              "grade_time": grade(st, vin + vout), "r_in": rin, "r_out": rout, "now_in": nin, "now_out": nout,
                              "share_now": sn, "grade_now": grade(sn, nin + nout)})
        if not res_sides:
            continue
        tot_t = sum(s["v_in"] for s in res_sides)
        tot_n = sum(s["now_in"] for s in res_sides)
        win_t = max(res_sides, key=lambda s: (s["share_time"] or 0.0))["team"] if tot_t >= MINOR_WAR else None
        win_n = max(res_sides, key=lambda s: (s["share_now"] or 0.0))["team"] if tot_n >= MINOR_WAR else None
        out.append({**{k: dl[k] for k in ("id", "date", "teams", "rows", "zero")}, "season": s_tr, "sides": res_sides,
                    "total_time": tot_t, "total_now": tot_n, "winner_time": win_t, "winner_now": win_n,
                    "days": (today - date.fromisoformat(d)).days})
    return out


def _player_item(league, pid, d, s_tr, to, rows_by, games, fit, prm, ctx_data, val_now, roster, slot_seasons, names, curve=None) -> dict:
    """One player's value at the trade (no hindsight), realised since and current view."""
    G = prm["G"]
    prev = None
    for s in range(s_tr - 1, s_tr - 3, -1):
        r = (rows_by.get(s) or {}).get(pid)
        if r and (_f(r.get("min")) or 0) > 0:
            prev = (s, r)
            break
    dob = BIO.dob(league, pid)
    age = BIO.age_at(dob, d) if dob else None
    if prev:
        ps, pr = prev
        h, m = _f(pr.get("hpm")) or VAL.REPLACEMENT, _f(pr.get("min")) or 0.0
        steps = sum(VV.aging_delta(fit.get("aging"), (age - (s_tr - ps) + j) if age is not None else None) for j in range(s_tr - ps))
        rate = ((h + steps) * m + VAL.REPLACEMENT * PRIOR_SHRINK_MIN) / (m + PRIOR_SHRINK_MIN)
        basis = "p"
        gp_prev, games_prev = int(pr.get("gp") or 0), VAL.season_games(league, ps)
    else:
        rate, basis, m, gp_prev, games_prev = VAL.REPLACEMENT, "r", 0.0, 0, 0
    before = games[games["date"] < d] if games is not None else None
    if before is not None and len(before):
        b = before[before["sec"] > 0].sort_values("date").tail(30)
        k = np.arange(len(b))[::-1]
        w = 0.5 ** (k / 12.0)
        mpg = float(np.sum(w * b["sec"].to_numpy() / 60.0) / np.sum(w)) if len(b) else 0.0
    else:
        mpg = (_f((prev[1] if prev else {}).get("min")) or 0.0) / max(1, gp_prev) if prev else 0.0
    mpg = min(mpg, VAL.MAX_SHARE * G)
    avail = VV.availability(gp_prev, games_prev, fit)
    lk = (ctx_data.get("games_left") or {}).get(s_tr)
    left = int(lk.get((to, d), VAL.season_games(league, s_tr)) if lk is not None else VAL.season_games(league, s_tr))
    full = VAL.season_games(league, s_tr)
    sd = VV.player_sd(fit, 0.0, m, basis)
    seed = int(hashlib.sha1(f"{league}{d}{pid}".encode()).hexdigest()[:8], 16)
    vt = VV.value_at(rate, sd, mpg, age, left, full, avail, fit, prm, seed=seed, n=120)
    prior = _rookie_prior(league, pid, s_tr, curve) if (prev is None and curve) else None
    w_time = 1.0
    if prior:
        m_before = float(before["sec"].sum()) / 60.0 if before is not None and len(before) else 0.0
        w_time = min(1.0, m_before / PK.ROOKIE_INFO_MIN)
        vt = {**vt, "v": w_time * vt["v"] + (1.0 - w_time) * prior[0],
              "p10": w_time * vt["p10"] + (1.0 - w_time) * prior[0] * 0.15, "p90": w_time * vt["p90"] + (1.0 - w_time) * prior[0] * 2.2}
    # realised since: games for the new team after the date
    realised = 0.0
    mins_after = 0.0
    gp_after = 0
    if games is not None and len(games):
        aft = games[(games["date"] >= d) & (games["team"] == to) & (games["sec"] > 0)]
        for s, sub in aft.groupby("season"):
            r = (rows_by.get(int(s)) or {}).get(pid)
            h = _f((r or {}).get("hpm"))
            if h is None:
                continue
            poss = float((sub["sec"] / 60.0 / G * sub["team_poss"]).sum())
            k = max(0, int(s) - s_tr)
            realised += (VV.DISCOUNT ** k) * (h - VAL.REPLACEMENT) * poss / 100.0 / prm["ppw"]
            mins_after += float(sub["sec"].sum()) / 60.0
            gp_after += int(len(sub))
    remaining = 0.0
    vn = val_now.get(pid)
    still = roster.get(pid) == to
    if vn and still:
        for i, s in enumerate(slot_seasons):
            k = int(s) - s_tr
            if 0 <= k < VV.SLOTS:
                w = vn.get(f"w{i}")
                if w is not None:
                    remaining += (VV.DISCOUNT ** k) * w
    v_now = realised + remaining
    if prior:
        # a rookie: the slot prior, less what he has produced, until he has played enough for the model alone
        m_all = float(games[games["sec"] > 0]["sec"].sum()) / 60.0 if games is not None and len(games) else 0.0
        w_now = min(1.0, m_all / PK.ROOKIE_INFO_MIN)
        prior_left = max(0.0, prior[0] - realised) if still else 0.0
        remaining = w_now * remaining + (1.0 - w_now) * prior_left
        v_now = realised + remaining
    return {"kind": "player", "id": pid, "name": names.get(pid) or pid, "age": _r(age, 1), "rate": rate, "mpg": mpg, "basis": basis,
            "v_time": vt["v"], "p10": vt["p10"], "p90": vt["p90"], "realised": realised, "gp_after": gp_after, "min_after": mins_after,
            "remaining": remaining, "v_now": v_now, "still": bool(still), "draft_slot": prior[1] if prior else None,
            "prior": round(prior[0], 3) if prior else None, "w_prior": round(1.0 - w_time, 3) if prior else None}


# ---------------------------------------------------------------------------------------------- payloads

def compact_item(x: dict) -> dict:
    if x["kind"] == "pick":
        out = {"k": "pick", "label": x["label"], "v": _r(x["v_time"], 2), "now": _r(x["v_now"], 2), "swap": x.get("swap") or None,
               "year": x.get("year"), "round": x.get("round"), "n": x.get("n") if (x.get("n") or 1) > 1 else None,
               "via": x.get("via"), "slot": x.get("slot"), "slot_now": x.get("slot_now"), "note": x.get("note") or None,
               "conv": _r(x.get("p_convey"), 3)}
        if x.get("player"):
            out.update({"pid": x["player"], "pname": x.get("player_name"), "real": _r(x.get("realised"), 2), "rem": _r(x.get("remaining"), 2)})
        return {k: v for k, v in out.items() if v is not None}
    return {"k": "p", "id": x["id"], "name": x["name"], "age": x.get("age"), "rate": _r(x["rate"], 2), "mpg": _r(x["mpg"], 1),
            "v": _r(x["v_time"], 2), "p10": _r(x.get("p10"), 2), "p90": _r(x.get("p90"), 2), "real": _r(x["realised"], 2),
            "gp": x.get("gp_after"), "rem": _r(x["remaining"], 2), "now": _r(x["v_now"], 2), "still": 1 if x.get("still") else 0,
            **({"slot": x["draft_slot"], "prior": x.get("prior"), "wp": x.get("w_prior")} if x.get("draft_slot") else {})}


def deals_payload(league: str, season: int, rated: list[dict], curve: dict, n_rows: int, unmatched: list[str],
                  updated_at: str | None = None, window: tuple[str, str] | None = None) -> dict:
    teams: dict[str, dict] = {}
    deals = []
    for dl in rated:
        sides = []
        for s in dl["sides"]:
            sides.append({"team": s["team"], "in": [compact_item(x) for x in s["in"]], "out": [compact_item(x) for x in s["out"]],
                          "v_in": _r(s["v_in"], 2), "v_out": _r(s["v_out"], 2), "share": _r(s["share_time"], 3), "grade": s["grade_time"],
                          "r_in": _r(s["r_in"], 2), "r_out": _r(s["r_out"], 2), "now_in": _r(s["now_in"], 2), "now_out": _r(s["now_out"], 2),
                          "share_now": _r(s["share_now"], 3), "grade_now": s["grade_now"]})
            t = teams.setdefault(s["team"], {"n": 0, "net_time": 0.0, "net_now": 0.0, "net_real": 0.0, "in_time": 0.0, "out_time": 0.0,
                                             "best": None, "worst": None})
            t["n"] += 1
            nt = s["v_in"] - s["v_out"]
            nn = s["now_in"] - s["now_out"]
            t["net_time"] += nt
            t["net_now"] += nn
            t["net_real"] += s["r_in"] - s["r_out"]
            t["in_time"] += s["v_in"]
            t["out_time"] += s["v_out"]
            if t["best"] is None or nn > t["best"][1]:
                t["best"] = [dl["id"], nn]
            if t["worst"] is None or nn < t["worst"][1]:
                t["worst"] = [dl["id"], nn]
        deals.append({"id": dl["id"], "date": dl["date"], "season": dl["season"], "teams": dl["teams"], "rows": dl["rows"], "zero": dl["zero"],
                      "sides": sides, "total": _r(dl["total_time"], 2), "total_now": _r(dl["total_now"], 2),
                      "winner": dl["winner_time"], "winner_now": dl["winner_now"]})
    for t in teams.values():
        for k in ("net_time", "net_now", "net_real", "in_time", "out_time"):
            t[k] = _r(t[k], 2)
        for k in ("best", "worst"):
            if t[k]:
                t[k] = [t[k][0], _r(t[k][1], 2)]
    return {"ok": True, "league": league, "season": int(season), "updated_at": updated_at or an.now(), "version": VERSION,
            "window": list(window) if window else None, "deals": deals, "teams": teams,
            "pick_curve": {**{k: curve.get(k) for k in ("v", "lo", "hi", "q10", "q50", "q90", "raw", "rounds", "n_drafts", "n_picks", "years",
                                                        "seasons", "per_round")},
                           "picks": [[i + 1, v] for i, v in enumerate(curve.get("v") or [])]},
            "n_rows": n_rows, "unmatched": unmatched[:200],
            "constants": {"discount": VV.DISCOUNT, "slots": VV.SLOTS, "grade_cuts": [[c, g] for c, g in GRADE_CUTS], "minor": MINOR_WAR,
                          "deal_days": DEAL_DAYS, "prior_shrink_min": PRIOR_SHRINK_MIN},
            "note": "On-field model value only (HPM wins above replacement). No salaries, cap or contracts: there is no free, "
                    "legitimate source we use (Spotrac, HoopsHype and Basketball-Reference terms forbid reuse)."}


def transactions_payload(league: str, season: int, parsed: list[dict], deal_of: dict[tuple, str], since: str, until: str,
                         unmatched: list[str], updated_at: str | None = None, people: dict[str, str] | None = None) -> dict:
    """The feed. `names` carries {pid: name} for every player a row links: most of them (waived, two-way, unsigned) are
    in no other payload the page loads, and without it they would show as their ESPN id."""
    rows, names = [], {}
    for r in parsed:
        if not (since <= r["date"] <= until):
            continue
        rows.append([r["date"], r["team"], r["types"], r["text"], r["players"], deal_of.get((r["date"], r["team"]))])
        for pid in r["players"] or []:
            nm = (people or {}).get(str(pid))
            if nm:
                names[str(pid)] = nm
    return {"ok": True, "league": league, "season": int(season), "updated_at": updated_at or an.now(), "since": since, "until": until,
            "types": TYPES, "cols": ["date", "team", "types", "text", "players", "deal"], "rows": rows, "names": names,
            "unmatched": sorted(set(unmatched))[:200], "source": "ESPN transactions (free text, parsed by the site)"}


# ---------------------------------------------------------------------------------------------- the build step

def build(ctx, valuation: dict | None, prm: dict, fit: dict, refresh: bool = True, rows: list[dict] | None = None) -> dict:
    """{"transactions": payload, "deals": payload, "info"} for the current season's context."""
    league, season, today = ctx.league, ctx.season, ctx.today
    if rows is None:
        rows, info = load_transactions(league, today, refresh=refresh)
    else:
        info = {"years": {}, "fetched": 0}
    since = str(today - timedelta(days=WINDOW_DAYS))
    until = str(today)
    window_rows = [r for r in rows if since <= (r.get("date") or "") <= until]
    # names and teams of this season and the two before
    people: dict[str, str] = {}
    teams_rec: dict[str, dict] = {}
    seasons = [s for s in an.seasons_on_disk(league) if season - 2 <= s <= season]
    frames = []
    from oddsmarkets.basketball.models import _io
    for s in seasons:
        st = an.load_store(league, s)
        for pid, p in (st.get("players") or {}).items():
            if p.get("name"):
                people[str(pid)] = p["name"]
        for tid, t in (st.get("teams") or {}).items():
            if t.get("name"):
                teams_rec[str(tid)] = t
        bx = ctx.box_all if s == season else _io.box_frame(an.real_games(st), ("reg", "post", "playin", "cup"))
        if bx is not None and not bx.empty:
            bx = bx.copy()
            bx["season"] = s
            frames.append(bx)
    import pandas as pd
    box = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    member = set(an.member_teams(ctx.store))
    teams_rec = {k: v for k, v in teams_rec.items() if k in member or not member}
    roster = VAL.current_rosters(ctx.store)
    names = NameIndex(people, stints_from_box(frames), roster)
    tix = TeamIndex(teams_rec)
    parsed = [parse_row(r, names, tix) for r in window_rows]
    unmatched = [n for r in parsed for s in r["sents"] for n in s["unmatched"] if s["type"] in ("trade", "claim", "sign", "release")]
    deals = build_deals(parsed, names)
    # games left for each team after each deal date, per season
    games_left: dict[int, dict] = {}
    for s in seasons:
        st = an.load_store(league, s)
        gl = sorted(((str(g.get("date") or "")[:10], g.get("home"), g.get("away")) for g in an.real_games(st).values()
                     if g.get("stype") == "reg"), key=lambda x: x[0])
        games_left[s] = _LeftLookup(gl)
    war_by, rows_by = season_war_rows(league, an.seasons_on_disk(league))
    pfit = PK.fits(league, season, war_by, rows_by)
    curve = pfit.get("curve") or {}
    pm = PK.model(league, season, ctx.sim, an.member_teams(ctx.store), fit=pfit, phase=ctx.phase)
    draft_hist = PK.history(league, war_by, rows_by)
    vrows = {}
    slot_seasons: list[int] = []
    if valuation and valuation.get("ok"):
        cols = valuation["cols"]
        vrows = {str(r[0]): dict(zip(cols, r)) for r in valuation["rows"]}
        for lab in valuation.get("slots") or []:
            m = re.search(r"(\d{4})", str(lab))
            slot_seasons.append(int(m.group(1)) if m else season)
    ctx_data = {"rows": rows_by, "box": box, "games_left": games_left, "valuation": vrows, "names": people, "current": season,
                "roster": roster, "slot_seasons": slot_seasons, "draft_hist": draft_hist}
    rated = rate_deals(league, deals, ctx_data, fit, prm, pm, today)
    deal_of = {}
    for dl in rated:
        for r in dl["rows"]:
            deal_of[(r["date"], r["team"])] = dl["id"]
    now = an.now()
    tx = transactions_payload(league, season, parsed, deal_of, since, until, unmatched, updated_at=now, people=people)
    dp = deals_payload(league, season, rated, curve, len(window_rows), sorted(set(unmatched)), updated_at=now, window=(since, until))
    teams_pk = sorted(an.member_teams(ctx.store)) or sorted(teams_rec)
    pk = PK.payload(league, season, pm, pfit, teams_pk, updated_at=now)
    return {"transactions": tx, "deals": dp, "picks": pk, "info": {**info, "rows": len(window_rows), "deals": len(rated),
                                                                   "unmatched": len(set(unmatched))}}


class _LeftLookup:
    """games_left[season][(team, date)] -> the team's regular-season games on or after the date."""

    def __init__(self, games: list[tuple[str, str, str]]):
        self.by_team: dict[str, list[str]] = {}
        for d, h, a in games:
            for t in (h, a):
                self.by_team.setdefault(str(t), []).append(d)

    def get(self, key, default=None):
        if isinstance(key, tuple) and len(key) == 2:
            t, d = key
            ds = self.by_team.get(str(t))
            if not ds:
                return default
            from bisect import bisect_left
            return len(ds) - bisect_left(ds, str(d))
        return default
