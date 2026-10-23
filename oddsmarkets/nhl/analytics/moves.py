"""
Transactions, deals, the pick-value curve and trade ratings for The Quant Rink (`data/<S>/transactions.json`,
`data/<S>/deals.json`, route #/moves, the team page's "Ledger"). Shared spec: docs/VALUE_SECTIONS.md section 4.

Source: ESPN's NHL transactions (free text, one row per club per day; sources/moves.py). NHL api-web has no
transactions endpoint. Values are on-field model value (WAR), never contracts or the salary cap (no salary source).

1. Parsing (`parse_row`): a row is split into clauses (sentences; "St.", "N.Y.", "No.", initials and "Jr." are not
   sentence ends). Each clause gets a type: trade, signing, waiver claim, waivers, release, recall/assignment, injured
   reserve, other. A trade clause is "Acquired <A> from <club> (in exchange) for <B>", "Traded <A> to <club> for <B>"
   or "Sent <A> to <NHL club> in exchange for <B>" (an AHL club makes it an assignment). Assets: players (position
   prefixes C, LW, RW, W, F, D, LD, RD, G and their plurals and combinations "C/RW"), draft picks ("a 2027
   second-round pick", "a 2028 first and second-round pick", "two 2026 third-round picks (No. 73 and 76)", "a
   third-round pick in the 2027 NHL Draft", "second and fourth-round picks in the 2027 and 2029 drafts" (paired in
   order), typos "20227" -> 2027, "thrid" -> third, "2nd round"; a pick with no year is the next draft), conditional
   picks (valued at face, flagged), future considerations and cash (value 0), "the rights to" a player.
2. Names (`NameIndex`): every player in players_index.json, the season stores and the draft records, keyed by a
   normalised name (accents, punctuation, "Jr." and case removed). One candidate: matched. Several: the one whose club
   (store, game logs, draft team) or position fits the clause. None: the same surname at one of the clubs involved,
   else a close spelling (difflib >= 0.88) at those clubs; otherwise the name is recorded as unmatched (never guessed).
3. Deals (`group_deals`): trade clauses at most DEAL_DAYS = 1 day apart are linked when the two clubs name each other
   or a player crosses between them (union-find; three-club trades become one deal with three sides); a group in
   which one club would appear on two different days is never merged (deadline chains stay separate deals). Both clubs' rows of the same trade are merged:
   assets to club A = what A's row says it acquired plus what B's row says it sent to A; picks are counted once
   (the larger count of the two descriptions).
4. Values (WAR, discounted 0.9 a season to the trade's season):
   at the time  players: valuation.AsOf (rates from seasons completed before the date, minutes and availability from
                games before it, survival, ageing; rest of that season + three more); picks: the pick-value curve at
                the known slot ("No. 23"), else the round's average, x 0.9^(draft year - the trade season's start
                year); a prospect with no NHL games: the curve at his draft slot; future considerations / cash 0.
   realised     sum over regular-season games for the new club after the date of the player's GAR per 60 that season
                (value.json) x his minutes / 60 / goals per win, each season discounted like the projection.
   now          realised + the valuation v2 projection still inside the original window (rest of this season and
                the seasons up to the trade season + 3), only while he is still with that club; picks unchanged.
   Each asset counts at max(0, value) (a club can always replace a below-replacement player: free disposal).
5. Grades: a side's share of the value the deal moved, rescaled to two sides (share x n / 2): A >= 0.65, B >= 0.55,
   C 0.45-0.55, D >= 0.35, F below; deals moving under MINOR_WAR in total are "minor". Winner: the largest share
   unless the deal is graded C/C or minor. League table: net value (received - sent) by club over the 12 months.

Pick-value curve (`pick_curve`): every pick of the 2010-2019 drafts (records.nhl.com), its discounted WAR over its
first seven seasons (season k after the draft weighted 0.9^k, WAR floored at 0 a season and scaled to an 82-game
season; picks who never played count 0), averaged by overall pick, made non-increasing (pool adjacent violators) and
fitted with v(p) = a (p + b)^-c (weighted least squares on the slot means). Cached on the drafts and value payloads.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import numpy as np

from oddsmarkets.nhl import analytics as an

logger = logging.getLogger(__name__)

VERSION = 1
WINDOW_DAYS = 365
DEAL_DAYS = 1
MINOR_WAR = 0.25
GRADES = ((0.65, "A"), (0.55, "B"), (0.45, "C"), (0.35, "D"), (-1.0, "F"))
PICK_DRAFTS = tuple(range(2010, 2020))
PICK_SEASONS = 7
DISCOUNT = 0.9
TYPES = {"trade": "Trade", "signing": "Signing", "claim": "Waiver claim", "waivers": "Waivers", "release": "Release",
         "recall": "Recall / assignment", "ir": "Injured reserve", "other": "Other"}
ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
       "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7}
NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "1": 1, "2": 2, "3": 3, "4": 4}

# ---------------------------------------------------------------------------------------------- clubs

CLUBS = {
    "ANA": ["Anaheim Ducks", "Anaheim", "Ducks"], "BOS": ["Boston Bruins", "Boston", "Bruins"], "BUF": ["Buffalo Sabres", "Buffalo", "Sabres"],
    "CGY": ["Calgary Flames", "Calgary", "Flames"], "CAR": ["Carolina Hurricanes", "Carolina", "Hurricanes"],
    "CHI": ["Chicago Blackhawks", "Chicago", "Blackhawks"], "COL": ["Colorado Avalanche", "Colorado", "Avalanche"],
    "CBJ": ["Columbus Blue Jackets", "Columbus", "Blue Jackets"], "DAL": ["Dallas Stars", "Dallas", "Stars"],
    "DET": ["Detroit Red Wings", "Detroit", "Red Wings"], "EDM": ["Edmonton Oilers", "Edmonton", "Oilers"],
    "FLA": ["Florida Panthers", "Florida", "Panthers"], "LAK": ["Los Angeles Kings", "Los Angeles", "LA Kings", "L.A. Kings", "Kings"],
    "MIN": ["Minnesota Wild", "Minnesota", "Wild"], "MTL": ["Montreal Canadiens", "Montreal", "Montréal Canadiens", "Montréal", "Canadiens"],
    "NSH": ["Nashville Predators", "Nashville", "Predators"], "NJD": ["New Jersey Devils", "New Jersey", "Devils"],
    "NYI": ["New York Islanders", "NY Islanders", "N.Y. Islanders", "Islanders"], "NYR": ["New York Rangers", "NY Rangers", "N.Y. Rangers", "Rangers"],
    "OTT": ["Ottawa Senators", "Ottawa", "Senators"], "PHI": ["Philadelphia Flyers", "Philadelphia", "Flyers"],
    "PIT": ["Pittsburgh Penguins", "Pittsburgh", "Penguins"], "SJS": ["San Jose Sharks", "San Jose", "Sharks"],
    "SEA": ["Seattle Kraken", "Seattle", "Kraken"], "STL": ["St. Louis Blues", "St Louis Blues", "St. Louis", "St Louis", "Blues"],
    "TBL": ["Tampa Bay Lightning", "Tampa Bay", "Tampa", "Lightning"], "TOR": ["Toronto Maple Leafs", "Toronto", "Maple Leafs"],
    "UTA": ["Utah Mammoth", "Utah Hockey Club", "Utah", "Mammoth"], "VAN": ["Vancouver Canucks", "Vancouver", "Canucks"],
    "VGK": ["Vegas Golden Knights", "Vegas", "Golden Knights"], "WSH": ["Washington Capitals", "Washington", "Capitals"],
    "WPG": ["Winnipeg Jets", "Winnipeg", "Jets"], "ARI": ["Arizona Coyotes", "Arizona", "Coyotes"],
}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.replace("�", "")


def _club_key(s: str) -> str:
    return re.sub(r"[^a-z ]", "", _fold(s).lower().replace(".", "")).strip()


_CLUB_ALIASES: dict[str, str] = {}
for _code, _names in CLUBS.items():
    for _n in _names:
        _CLUB_ALIASES[_club_key(_n)] = _code


def club_of(text: str) -> str | None:
    """An NHL club code from free text ("the Philadelphia Flyers", "N.Y. Rangers", "Ottowa Senators"); None for an
    AHL or unknown club."""
    t = str(text or "")
    if re.search(r"\((?:AHL|ECHL|KHL|SHL|CHL|OHL|WHL|QMJHL|NCAA|USHL|Liiga|NL)\)", t, re.I):
        return None
    k = _club_key(re.sub(r"^\s*the\s+", "", t, flags=re.I))
    k = re.sub(r"^the ", "", k).strip()
    if not k:
        return None
    if k in _CLUB_ALIASES:
        return _CLUB_ALIASES[k]
    # longest alias that the text starts or ends with ("Pittsburgh Penguins organization")
    for alias in sorted(_CLUB_ALIASES, key=len, reverse=True):
        if len(alias) >= 4 and (k.startswith(alias + " ") or k.endswith(" " + alias) or k == alias):
            return _CLUB_ALIASES[alias]
    m = difflib.get_close_matches(k, list(_CLUB_ALIASES), n=1, cutoff=0.82)
    return _CLUB_ALIASES[m[0]] if m else None


def club_exact(text: str) -> str | None:
    """An NHL club only when the text is exactly one of its names (no fuzzy matching)."""
    k = re.sub(r"^the ", "", _club_key(text)).strip()
    return _CLUB_ALIASES.get(k)


def _strip_club_suffix(a: str) -> tuple[str, str | None]:
    words = a.split()
    for n in (3, 2, 1):
        if len(words) > n:
            c = club_exact(" ".join(words[-n:]))
            if c:
                return " ".join(words[:-n]), c
    return a, None


# ---------------------------------------------------------------------------------------------- names

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv)\b")


def norm_name(s: str) -> str:
    """Lower case, accents, dots, apostrophes, hyphens and Jr./Sr. removed, single spaces."""
    s = _fold(s).lower()
    s = s.replace("’", "").replace("'", "").replace(".", " ").replace("-", " ")
    s = re.sub(r"[^a-z ]", " ", s)
    s = _SUFFIX.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # "j j peterka" -> "jj peterka" (initials written with dots)
    parts = s.split(" ")
    out, buf = [], ""
    for p in parts:
        if len(p) == 1:
            buf += p
        else:
            if buf:
                out.append(buf)
                buf = ""
            out.append(p)
    if buf:
        out.append(buf)
    return " ".join(out)


class NameIndex:
    """Normalised name -> candidates [{"pid","name","teams" (set), "pos", "last" (last season), "dob"}]."""

    def __init__(self):
        self.by: dict[str, dict[str, dict]] = {}
        self.surname: dict[str, set[str]] = {}
        self.info: dict[str, dict] = {}

    def add(self, pid: Any, name: str | None, team: str | None = None, pos: str | None = None, last: int | None = None,
            dob: str | None = None) -> None:
        pid = an.sid(pid)
        if not pid or not name:
            return
        k = norm_name(name)
        if not k:
            return
        rec = self.info.setdefault(pid, {"pid": pid, "name": name, "teams": set(), "pos": pos, "last": last, "dob": dob})
        if team:
            rec["teams"].add(team)
        if pos and not rec.get("pos"):
            rec["pos"] = pos
        if last and (rec.get("last") or 0) < last:
            rec["last"] = last
        if dob and not rec.get("dob"):
            rec["dob"] = dob
        self.by.setdefault(k, {})[pid] = rec
        sur = k.split(" ")[-1]
        self.surname.setdefault(sur, set()).add(pid)

    def match(self, name: str, teams: Iterable[str] = (), pos: str | None = None) -> tuple[str | None, str]:
        """(pid, how): how in "exact", "exact+club", "surname+club", "spelling+club", "ambiguous", "none"."""
        k = norm_name(name)
        teams = {t for t in teams if t}
        cands = list((self.by.get(k) or {}).values())
        g = _pos_group(pos)
        if len(cands) == 1:
            return cands[0]["pid"], "exact"
        if len(cands) > 1:
            pick = [c for c in cands if c["teams"] & teams] or cands
            if g:
                pick2 = [c for c in pick if _pos_group(c.get("pos")) == g]
                pick = pick2 or pick
            if len(pick) > 1:
                pick = sorted(pick, key=lambda c: -(c.get("last") or 0))
                if (pick[0].get("last") or 0) > (pick[1].get("last") or 0):
                    pick = pick[:1]
            if len(pick) == 1:
                return pick[0]["pid"], "exact+club"
            return None, "ambiguous"
        if not teams or not k:
            return None, "none"
        sur = k.split(" ")[-1]
        first = k.split(" ")[0]
        at = [self.info[p] for p in self.surname.get(sur, set()) if self.info[p]["teams"] & teams]
        at = [c for c in at if norm_name(c["name"]).split(" ")[0][:1] == first[:1]]
        if len(at) == 1:
            return at[0]["pid"], "surname+club"
        pool = {norm_name(c["name"]): c for p, c in self.info.items() if c["teams"] & teams}
        m = difflib.get_close_matches(k, list(pool), n=2, cutoff=0.88)
        if len(m) == 1 or (len(m) == 2 and difflib.SequenceMatcher(None, k, m[0]).ratio() > difflib.SequenceMatcher(None, k, m[1]).ratio() + 0.04):
            return pool[m[0]]["pid"], "spelling+club"
        return None, "none"


def _pos_group(pos: Any) -> str | None:
    p = str(pos or "").upper()
    if not p:
        return None
    if p.startswith("G"):
        return "G"
    if p.startswith("D") or p in ("LD", "RD"):
        return "D"
    return "F"


def build_index(stores: dict[int, dict], players_index: dict | None, drafts: dict[int, dict], sk_logs=None) -> NameIndex:
    ix = NameIndex()
    for pid, v in (players_index or {}).items():
        if isinstance(v, list) and v:
            ix.add(pid, v[0], v[1] if len(v) > 1 else None, v[2] if len(v) > 2 else None, v[4] if len(v) > 4 else None)
    for s, st in sorted(stores.items()):
        for pid, p in ((st or {}).get("players") or {}).items():
            if isinstance(p, dict):
                nm = p.get("name") or " ".join(x for x in (p.get("first"), p.get("last")) if x)
                ix.add(pid, nm, p.get("team"), p.get("pos"), s, p.get("dob"))
    for y, d in sorted(drafts.items()):
        for r in d.get("rows") or []:
            rec = dict(zip(d.get("cols") or [], r))
            if rec.get("pid"):
                ix.add(rec["pid"], rec.get("name"), rec.get("team"), rec.get("pos"), None, rec.get("dob"))
    if sk_logs is not None and len(sk_logs):
        tm = sk_logs.groupby("pid")["team"].agg(lambda s: set(s))
        for pid, ts in tm.items():
            rec = ix.info.get(str(pid))
            if rec:
                rec["teams"] |= ts
    return ix


# ---------------------------------------------------------------------------------------------- clauses

_VERBS = ("acquired", "acquire", "traded", "sent", "signed", "re-signed", "resigned", "agreed", "extended", "claimed",
          "waived", "placed", "released", "terminated", "bought", "recalled", "recaled", "assigned", "reassigned",
          "re-assigned", "loaned", "returned", "called", "elevated", "promoted", "activated", "reinstated", "transferred",
          "moved", "removed", "designated", "fired", "hired", "named", "announced", "suspended", "made", "will", "mutually")


def _protect(s: str) -> str:
    s = s.replace("’", "'")
    s = re.sub(r"\bN\.\s?Y\.", "NY", s)
    s = re.sub(r"\bL\.\s?A\.", "LA", s)
    s = re.sub(r"\b(St|Jr|Sr|No|Mt|Ft|vs|Dr|Mr)\.", r"\1", s)
    s = re.sub(r"\b((?:[A-Z]\.\s?){2,})", lambda m: m.group(1).replace(".", "").replace(" ", "") + " ", s)   # initials A.J. / J. J.
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\b([A-Z])\.\s(?=[A-Z][a-z])", r"\1 ", s)            # "T. J. Oshie", "A. Greer"
    return s


def split_clauses(desc: str) -> list[str]:
    s = _protect(str(desc or "").strip())
    parts = re.split(r"\s*\.\s*(?=[A-Z(])|\s*\.\s*$", s)
    out = [p.strip(" .") for p in parts if p and p.strip(" .")]
    return out


def clause_type(c: str) -> str:
    low = c.lower()
    v = low.split(" ")[0] if low else ""
    if v in ("acquired", "acquire", "traded") or (v == "sent" and ("exchange" in low or re.search(r"\bfor\b", low)) and "(ahl)" not in low):
        return "trade"
    if v == "claimed":
        return "claim" if "waiver" in low else "other"
    if "unconditional waivers" in low or "terminat" in low or v in ("released", "bought") or "buy out" in low or "bought out" in low:
        return "release"
    if v in ("waived", "designated") or ("on waivers" in low and v == "placed") or (v == "placed" and "waivers" in low):
        return "waivers"
    if "injured reserve" in low or "injured list" in low or "non-roster" in low:
        return "ir"
    if v in ("signed", "re-signed", "resigned", "agreed", "extended") or low.startswith("agreed to terms"):
        return "signing"
    if v in ("recalled", "recaled", "assigned", "reassigned", "re-assigned", "loaned", "returned", "called", "elevated", "promoted", "sent"):
        return "recall"
    return "other"


# ---------------------------------------------------------------------------------------------- assets

_ORDW = r"(?:first|second|third|thrid|fourth|fifth|sixth|seventh|1st|2nd|3rd|4th|5th|6th|7th)"
_ROUNDS = rf"(?P<rounds>{_ORDW}(?:\s*(?:,|and|&)\s*{_ORDW})*)"
_COUNT = r"(?:(?P<count>a|an|one|two|three|four|2|3|4)\s+)?"
_COND = r"(?P<cond>conditional\s+)?"
_PICK_A = re.compile(
    rf"{_COUNT}{_COND}(?P<year>20\d{{2,3}})\s+(?P<cond2>conditional\s+)?{_ROUNDS}[\s-]*round(?:\s+draft)?\s+(?:draft\s+)?picks?"
    rf"(?:\s+in\s+the\s+(?P<y2>20\d{{2}})(?:\s+nhl)?\s+draft)?(?:\s*\((?P<paren>[^)]*)\))?", re.I)
_PICK_B = re.compile(
    rf"{_COUNT}{_COND}{_ROUNDS}[\s-]*round(?:\s+draft)?\s+(?:draft\s+)?picks?(?:\s+in\s+the\s+(?P<years>20\d{{2,3}}(?:\s*(?:,|and)\s*20\d{{2,3}})*)(?:\s+nhl)?\s+drafts?)?"
    rf"(?:\s*\((?P<paren>[^)]*)\))?", re.I)
_FC = re.compile(r"future\s+considerations?", re.I)
_CASH = re.compile(r"\bcash(?:\s+considerations?)?\b", re.I)
_POS = r"(?:C|LW|RW|W|F|D|G|LD|RD)(?:/(?:C|LW|RW|W|F|D|G|LD|RD))*s?"
_POS_RE = re.compile(rf"^(?P<pos>{_POS})\s+(?=[A-ZÀ-ſ])")


def _year(s: str, ref_year: int) -> int | None:
    s = re.sub(r"\D", "", s or "")
    if len(s) == 4:
        return int(s)
    if len(s) == 5 and s.startswith("20"):
        cands = {int(s[:i] + s[i + 1:]) for i in range(len(s))}
        cands = [c for c in cands if 2000 <= c <= 2045]
        if cands:
            return min(cands, key=lambda c: (abs(c - ref_year), c))
    return None


def _rounds(txt: str) -> list[int]:
    return [ORD["third" if w.lower() == "thrid" else w.lower()] for w in re.findall(_ORDW, txt, re.I)]


def next_draft_year(d: date) -> int:
    return d.year if (d.month, d.day) < (6, 28) else d.year + 1


def parse_picks(text: str, d: date) -> tuple[list[dict], str]:
    """(picks, text with the pick phrases removed)."""
    picks: list[dict] = []
    t = re.sub(r"\b(\d)(?:st|nd|rd|th)\s+round\b", lambda m: {"1": "first", "2": "second", "3": "third", "4": "fourth", "5": "fifth", "6": "sixth", "7": "seventh"}[m.group(1)] + "-round", text)
    t = re.sub(r"\bthrid\b", "third", t, flags=re.I)

    def emit(years: list[int | None], rounds: list[int], count: int, cond: bool, paren: str | None, inferred: bool):
        overall = [int(x) for x in re.findall(r"\b(\d{1,3})\b", paren or "") if 0 < int(x) <= 260] if paren and re.search(r"No", paren, re.I) else []
        orig = None
        if paren and not overall:
            c = club_of(paren) or (paren.strip().upper() if re.fullmatch(r"[A-Za-z]{2,3}", paren.strip()) else None)
            orig = c
        items = []
        if len(years) > 1 and len(years) == len(rounds):
            items = list(zip(years, rounds))
        else:
            for y in years:
                for r in rounds:
                    items.append((y, r))
        n = max(count, len(overall)) if overall else count
        out = []
        for y, r in items:
            for i in range(max(1, n if len(items) == 1 else 1)):
                out.append({"kind": "pick", "year": y, "round": r, "cond": cond, "inferred_year": inferred,
                            "overall": overall[i] if i < len(overall) else None, "orig": orig})
        picks.extend(out)

    def sub_a(m):
        y = _year(m.group("year"), d.year) or _year(m.group("y2") or "", d.year)
        emit([y], _rounds(m.group("rounds")), NUM.get((m.group("count") or "a").lower(), 1), bool(m.group("cond") or m.group("cond2")),
             m.group("paren"), y is None)
        return " "

    t = _PICK_A.sub(sub_a, t)

    def sub_b(m):
        ys = [_year(y, d.year) for y in re.findall(r"20\d{2,3}", m.group("years") or "")]
        inferred = not ys
        if not ys:
            ys = [next_draft_year(d)]
        emit(ys, _rounds(m.group("rounds")), NUM.get((m.group("count") or "a").lower(), 1), bool(m.group("cond")), m.group("paren"), inferred)
        return " "

    t = _PICK_B.sub(sub_b, t)
    return picks, t


def parse_assets(text: str, d: date) -> list[dict]:
    """Assets in a free-text list: picks, future considerations, cash and players [{"kind": "player", "name", "pos",
    "rights"}]."""
    out: list[dict] = []
    t = str(text or "")
    t = re.sub(r"\b(?:and\s+)?(?:\$[\d.,]+\s*(?:million|M|K)?\s+)?(?:in\s+)?retained\s+salary\b.*$", "", t, flags=re.I)
    picks, t = parse_picks(t, d)
    out += picks
    if _FC.search(t):
        out.append({"kind": "fc"})
        t = _FC.sub(" ", t)
    if _CASH.search(t):
        out.append({"kind": "cash"})
        t = _CASH.sub(" ", t)
    t = re.sub(r"\b(?:the\s+)?(?:playing\s+)?rights\s+to\s+(?:unsigned\s+)?(?:draft\s+pick\s+)?", " RIGHTS:", t, flags=re.I)
    t = re.sub(r"\bunsigned draft pick\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" ,.;")
    chunks = [c.strip(" ,.;") for c in re.split(r",|\band\b|&|;", t)]
    cur_pos = None
    for c in chunks:
        if not c:
            continue
        rights = "RIGHTS:" in c
        c = c.replace("RIGHTS:", "").strip()
        c = re.sub(r"^(?:a|an|the)\s+", "", c, flags=re.I)
        m = _POS_RE.match(c)
        if m:
            cur_pos = m.group("pos").rstrip("s").split("/")[0]
            c = c[m.end():].strip()
        c = re.sub(r"\s*\(.*?\)\s*", " ", c).strip()
        c = re.sub(r"\s+(?:from|to)\s+.*$", "", c).strip()
        toks = c.split()
        if len(toks) < 2 or len(toks) > 5 or not all(tok[:1].isupper() or tok[:1] in "'’" or not tok[:1].isalpha() for tok in toks[:2]):
            continue
        if any(w.lower() in ("pick", "picks", "round", "draft", "considerations", "contract", "waivers") for w in toks):
            continue
        out.append({"kind": "player", "name": c, "pos": cur_pos, "rights": rights})
    return out


_TRADE_A = re.compile(r"^(?P<verb>acquired?|sent|traded)\s+(?P<a>.+?)\s+(?P<dir>from|to)\s+(?P<team>.+?)"
                      r"(?:\s+(?:in exchange for|in exchange|for)\s+(?P<b>.+))?$", re.I)


def parse_trade(clause: str, row_team: str, d: date) -> dict | None:
    """{"team" (the row's club), "cp" (counterpart), "in": [assets], "out": [assets]} or None."""
    c = re.sub(r"\bthe rights to\b", "rightsto", clause, flags=re.I)
    c = c.replace("rightsto", "the rights of")
    m = _TRADE_A.match(c)
    a = b = team = None
    direction = "from"
    if m:
        a, team, b, direction = m.group("a"), m.group("team"), m.group("b"), m.group("dir").lower()
        cp = club_of(team)
        if cp is None:
            # "Acquired F Zac Funk Washington for F Tyler Kopff": the club at the end of the asset text
            mm = re.match(r"^(?P<verb>acquired?|traded|sent)\s+(?P<a>.+?)\s+(?:in exchange for|for)\s+(?P<b>.+)$", clause, re.I)
            if mm:
                a, b = mm.group("a"), mm.group("b")
                a, cp = _strip_club_suffix(a)
    else:
        mm = re.match(r"^(?P<verb>acquired?|traded|sent)\s+(?P<a>.+?)\s+(?:in exchange for|for)\s+(?P<b>.+)$", clause, re.I)
        if not mm:
            return None
        a, b = mm.group("a"), mm.group("b")
        a, cp = _strip_club_suffix(a)
    if cp is None or cp == row_team:
        return None
    a = (a or "").replace("the rights of", "the rights to")
    b = (b or "").replace("the rights of", "the rights to")
    A, B = parse_assets(a, d), parse_assets(b or "", d)
    verb = clause.split(" ")[0].lower()
    if verb in ("acquired", "acquire") and direction == "from":
        return {"team": row_team, "cp": cp, "in": A, "out": B}
    if verb in ("traded", "sent") or direction == "to":
        return {"team": row_team, "cp": cp, "in": B, "out": A}
    return {"team": row_team, "cp": cp, "in": A, "out": B}


def clause_players(clause: str, typ: str, d: date) -> list[dict]:
    """Players named in a non-trade clause (the object of its verb)."""
    c = re.sub(r"^\S+\s+(?:up\s+)?", "", clause)                     # drop the verb
    if typ == "signing" and clause.lower().startswith("agreed"):
        c = re.sub(r"^to terms with\s+", "", c, flags=re.I)
    if typ == "other" and re.match(rf"^{_POS}\s+[A-Z]", clause):
        c = clause
    c = re.split(r"\s+(?:to|from|off|on|for|in|with|after|as|who)\s+(?=[a-z0-9$])|\s+(?:to|from|on)\s+(?=the\b|[A-Z][a-z]+\s*\()", c)[0]
    c = re.split(r"\s+(?:announced|served|agreed|scored|is|was|has|will|after)\b", c)[0]
    return [x for x in parse_assets(c, d) if x["kind"] == "player"]


def parse_row(row: list, season_of_team=None) -> list[dict]:
    """One ESPN row [date, ESPN team id, ESPN abbreviation, description] -> clauses [{"date","team","type","text",
    "trade" (for trades), "players" (asset dicts)}]."""
    from oddsmarkets.nhl import canon
    try:
        d = date.fromisoformat(str(row[0])[:10])
    except ValueError:
        return []
    team = canon.abbr_from_espn(row[1] or None, row[2] or None)
    out = []
    for c in split_clauses(row[3]):
        typ = clause_type(c)
        rec = {"date": d.isoformat(), "team": team, "type": typ, "text": c}
        if typ == "trade":
            tr = parse_trade(c, team, d)
            if tr is None:
                rec["type"] = "other" if not c.lower().startswith("sent") else "recall"
                rec["players"] = clause_players(c, rec["type"], d)
            else:
                rec["trade"] = tr
                rec["players"] = [x for x in tr["in"] + tr["out"] if x["kind"] == "player"]
        else:
            rec["players"] = clause_players(c, typ, d)
        out.append(rec)
    return out


# ---------------------------------------------------------------------------------------------- deals

def _asset_key(a: dict) -> tuple:
    if a["kind"] == "player":
        return ("p", a.get("pid") or norm_name(a.get("name") or ""))
    if a["kind"] == "pick":
        return ("k", a.get("year"), a.get("round"), a.get("overall"))
    return (a["kind"],)


def group_deals(clauses: list[dict]) -> list[dict]:
    """Union-find over trade clauses (DEAL_DAYS apart at most, sharing a pair of clubs or a player)."""
    tr = [c for c in clauses if c.get("trade")]
    n = len(tr)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    members = {i: [i] for i in range(n)}

    def union(i, j):
        a, b = find(i), find(j)
        if a == b:
            return
        # never merge a group in which one club would appear on two different days (deadline chains)
        days: dict[str, str] = {}
        for k in members[a] + members[b]:
            c = tr[k]
            for t in (c["trade"]["team"], c["trade"]["cp"]):
                if days.setdefault(t, c["date"]) != c["date"]:
                    return
        parent[b] = a
        members[a] += members.pop(b)

    dts = [date.fromisoformat(c["date"]) for c in tr]
    pairs = [frozenset((c["trade"]["team"], c["trade"]["cp"])) for c in tr]
    pkeys = [{_asset_key(a) for a in c["trade"]["in"] + c["trade"]["out"] if a["kind"] == "player"} for c in tr]
    for i in range(n):
        for j in range(i + 1, n):
            if abs((dts[i] - dts[j]).days) > DEAL_DAYS:
                continue
            if pairs[i] == pairs[j] or (pkeys[i] & pkeys[j] and pairs[i] & pairs[j]):
                union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    deals = []
    for idx in groups.values():
        cl = [tr[i] for i in sorted(idx, key=lambda i: (tr[i]["date"], tr[i]["team"]))]
        # moves: (asset, from, to) with each description contributing; dedupe players by key, picks by max count
        flows: dict[tuple, dict] = {}
        pick_counts: dict[tuple, dict[str, int]] = {}
        for c in cl:
            t = c["trade"]
            for direction, assets in (("in", t["in"]), ("out", t["out"])):
                fr, to = (t["cp"], t["team"]) if direction == "in" else (t["team"], t["cp"])
                local: dict[tuple, int] = {}
                for a in assets:
                    key = _asset_key(a)
                    if a["kind"] == "pick":
                        kk = (fr, to) + key
                        local[kk] = local.get(kk, 0) + 1
                        flows.setdefault(kk + (local[kk],), {**a, "from": fr, "to": to})
                    elif a["kind"] == "player":
                        kk = (key,)
                        if kk not in flows:
                            flows[kk] = {**a, "from": fr, "to": to}
                    else:
                        kk = (fr, to) + key
                        flows.setdefault(kk, {**a, "from": fr, "to": to})
                for kk, nn in local.items():
                    pick_counts.setdefault(kk, {})[c["team"]] = max(pick_counts.get(kk, {}).get(c["team"], 0), nn)
        teams = sorted({c["trade"]["team"] for c in cl} | {c["trade"]["cp"] for c in cl})
        d0 = min(c["date"] for c in cl)
        assets = list(flows.values())
        deals.append({"id": f"{d0}-{'-'.join(teams)}", "date": d0, "teams": teams, "assets": assets,
                      "text": [[c["team"], c["text"]] for c in cl], "rows": len(cl)})
    deals.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
    seen: dict[str, int] = {}
    for dl in deals:
        k = dl["id"]
        if k in seen:
            seen[k] += 1
            dl["id"] = f"{k}-{seen[k]}"
        else:
            seen[k] = 1
    return deals


# ---------------------------------------------------------------------------------------------- the pick-value curve

def _pava_decreasing(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Weighted pool-adjacent-violators, non-increasing."""
    vals, wts, cnt = [], [], []
    for yi, wi in zip(y.tolist(), w.tolist()):
        vals.append(yi)
        wts.append(wi)
        cnt.append(1)
        while len(vals) > 1 and vals[-2] < vals[-1]:
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / (wts[-2] + wts[-1])
            ww = wts[-2] + wts[-1]
            c = cnt[-2] + cnt[-1]
            vals[-2:], wts[-2:], cnt[-2:] = [v], [ww], [c]
    out = []
    for v, c in zip(vals, cnt):
        out += [v] * c
    return np.asarray(out)


def pick_values(drafts: dict[int, dict], vr: dict[int, dict]) -> list[tuple[int, int, int, float]]:
    """[(draft year, overall, round, discounted WAR over the first PICK_SEASONS seasons)] for the PICK_DRAFTS drafts with a
    complete window in the value payloads."""
    war: dict[tuple[int, str], float] = {}
    for s, x in vr.items():
        tg = max(int(x.get("team_games") or 82), 1)
        for r in x["rows"]:
            w = an.fnum(r.get("war"))
            if w is not None:
                war[(s, str(r["id"]))] = max(0.0, w) * 82.0 / tg
    last = max(vr) if vr else 0
    out = []
    for y in PICK_DRAFTS:
        d = drafts.get(y)
        if not d:
            continue
        if an.season_id(y + PICK_SEASONS - 1) > last or an.season_id(y + PICK_SEASONS - 1) not in vr:
            continue
        cols = d.get("cols") or []
        for r in d.get("rows") or []:
            rec = dict(zip(cols, r))
            ov = an.inum(rec.get("overall"))
            if not ov:
                continue
            pid = str(rec.get("pid") or "")
            v = sum(DISCOUNT ** k * war.get((an.season_id(y + k), pid), 0.0) for k in range(PICK_SEASONS)) if pid else 0.0
            out.append((y, ov, int(rec.get("round") or 0), v))
    return out


def pick_curve(drafts: dict[int, dict], vr: dict[int, dict]) -> dict:
    """{"a","b","c","points": [[overall, fitted]], "raw": [[overall, mean, n]], "round_avg": {round: value},
    "r2_slots", "r2_bins", "n_picks", "drafts"}; cached on its inputs."""
    pv = pick_values(drafts, vr)
    key = hashlib.sha1(json.dumps([VERSION, len(pv), round(sum(v for *_, v in pv), 4), sorted({y for y, *_ in pv})]).encode()).hexdigest()[:16]
    p = an.an_cache() / "moves" / "pick_curve.json"
    c = an.read_json(p) if p.exists() else None
    if isinstance(c, dict) and c.get("key") == key:
        return c["curve"]
    if len(pv) < 200:
        return {"ok": False, "reason": f"only {len(pv)} picks with a complete window"}
    from scipy.optimize import curve_fit
    maxp = 224
    S = np.zeros(maxp + 1)
    N = np.zeros(maxp + 1)
    for _, ov, _, v in pv:
        if ov <= maxp:
            S[ov] += v
            N[ov] += 1
    xs = np.arange(1, maxp + 1)
    m = N[1:] > 0
    mean = np.where(m, S[1:] / np.maximum(N[1:], 1), np.nan)
    xs_m, y_m, w_m = xs[m], mean[m], N[1:][m]
    iso = _pava_decreasing(y_m, w_m)

    def f(x, a, b, cc):
        return a * np.power(x + b, -cc)

    try:
        popt, _ = curve_fit(f, xs_m.astype(float), iso, p0=(10.0, 1.0, 0.8), sigma=1.0 / np.sqrt(w_m), bounds=([0, 0, 0.05], [1e4, 100, 5]),
                            maxfev=20000)
    except Exception:                                            # noqa: BLE001
        popt = (float(iso[0]), 0.0, 0.5)
    a, b, cc = (float(v) for v in popt)
    fit = f(xs.astype(float), a, b, cc)
    ss_res = float(np.sum(w_m * (y_m - f(xs_m.astype(float), a, b, cc)) ** 2))
    ss_tot = float(np.sum(w_m * (y_m - np.average(y_m, weights=w_m)) ** 2))
    bins = []
    for lo in range(1, maxp + 1, 16):
        mm = (xs_m >= lo) & (xs_m < lo + 16)
        if mm.any():
            bins.append((float(np.average(y_m[mm], weights=w_m[mm])), float(np.average(f(xs_m[mm].astype(float), a, b, cc), weights=w_m[mm])), float(w_m[mm].sum())))
    bb = np.asarray(bins)
    r2b = 1 - float(np.sum(bb[:, 2] * (bb[:, 0] - bb[:, 1]) ** 2)) / max(float(np.sum(bb[:, 2] * (bb[:, 0] - np.average(bb[:, 0], weights=bb[:, 2])) ** 2)), 1e-12)
    round_avg = {str(r): round(float(fit[32 * (r - 1):32 * r].mean()), 3) for r in range(1, 8)}
    emp_round = {}
    for r in range(1, 8):
        vals = [v for _, ov, rr, v in pv if 32 * (r - 1) < ov <= 32 * r]
        emp_round[str(r)] = [round(float(np.mean(vals)), 3) if vals else None, len(vals),
                             round(float(np.mean([v > 0 for v in vals])), 3) if vals else None]
    curve = {"ok": True, "a": round(a, 4), "b": round(b, 4), "c": round(cc, 4), "max_overall": maxp,
             "points": [[int(x), round(float(v), 3)] for x, v in zip(xs, fit)],
             "raw": [[int(x), round(float(v), 3), int(n)] for x, v, n in zip(xs_m, y_m, w_m)],
             "round_avg": round_avg, "round_empirical": emp_round, "r2_slots": round(1 - ss_res / max(ss_tot, 1e-12), 3),
             "r2_bins": round(r2b, 3), "n_picks": len(pv), "drafts": sorted({y for y, *_ in pv}),
             "seasons": PICK_SEASONS, "discount": DISCOUNT}
    try:
        an.write_json(p, {"key": key, "curve": curve})
    except OSError:
        pass
    return curve


def curve_value(curve: dict | None, overall: int | None = None, rnd: int | None = None) -> float:
    if not curve or not curve.get("ok"):
        return 0.0
    if overall:
        return float(curve["a"] * (int(overall) + curve["b"]) ** (-curve["c"]))
    if rnd:
        return float((curve.get("round_avg") or {}).get(str(int(rnd))) or 0.0)
    return 0.0


def pick_value(curve: dict | None, a: dict, trade_season: int) -> float:
    y = a.get("year")
    y0 = an.start_year(trade_season)
    v = curve_value(curve, a.get("overall"), a.get("round"))
    if y is None:
        return v
    return v * DISCOUNT ** max(0, int(y) - y0)


def grade(rel_share: float | None) -> str | None:
    if rel_share is None:
        return None
    for cut, g in GRADES:
        if rel_share >= cut:
            return g
    return "F"


# ---------------------------------------------------------------------------------------------- ratings

def realised(sk, gk, vr: dict[int, dict], pid: str, team: str, d: date, kind: str, trade_season: int, end_season: int) -> dict:
    """GAR-rate x minutes for the new club after the date, by season (WAR, undiscounted and discounted)."""
    out = {"war": 0.0, "disc": 0.0, "gp": 0, "toi": 0.0}
    log = sk if kind == "S" else gk
    if log is None or not len(log):
        return out
    ds = d.isoformat()
    g = log[(log["pid"] == int(pid)) & (log["team"] == team) & (log["date"] >= ds) & (log["gt"] == "R")]
    if not len(g):
        return out
    for s, x in g.groupby("season"):
        s = int(s)
        if s > end_season:
            continue
        row = next((r for r in (vr.get(s) or {}).get("rows") or [] if str(r["id"]) == str(pid)), None)
        rate = an.fnum((row or {}).get("rate")) or 0.0
        gpw = (vr.get(s) or {}).get("gpw") or 6.0
        toi = float(x["toi"].sum())
        w = rate * toi / 60.0 / gpw
        k = an.start_year(s) - an.start_year(trade_season)
        out["war"] += w
        out["disc"] += DISCOUNT ** max(k, 0) * w
        out["gp"] += int(len(x))
        out["toi"] += toi
    return out


def rate_deals(deals: list[dict], ix: NameIndex, asof, val_now: dict[str, dict], roster_now: dict[str, str], curve: dict | None,
               vr: dict[int, dict], logs: dict, f: dict, today: date, drafts: dict[int, dict]) -> list[dict]:
    """Values, shares and grades for every deal (in place, also returned)."""
    from oddsmarkets.nhl.analytics import valuation as V
    sk, gk = logs.get("sk"), logs.get("gk")
    draft_slot = {}
    for y, d in drafts.items():
        for r in d.get("rows") or []:
            rec = dict(zip(d.get("cols") or [], r))
            if rec.get("pid"):
                draft_slot[str(rec["pid"])] = (y, an.inum(rec.get("overall")))
    s_now = V.season_of(today)
    for dl in deals:
        d = date.fromisoformat(dl["date"])
        s0 = V.season_of(d)
        end = an.season_id(an.start_year(s0) + V.HORIZON)
        inputs, owners = [], []
        for a in dl["assets"]:
            a["at"] = a["realised"] = a["now"] = 0.0
            if a["kind"] == "player":
                if not a.get("pid"):
                    pid, how = ix.match(a.get("name") or "", (a["from"], a["to"]), a.get("pos"))
                    a["pid"], a["match"] = pid, how
                if not a.get("pid"):
                    a["note"] = "unmatched name: valued at 0"
                    continue
                rec = ix.info.get(a["pid"]) or {}
                a["name"] = rec.get("name") or a.get("name")
                if rec.get("pos"):
                    a["pos"] = rec["pos"]
                p = asof.player(a["pid"], a["to"], d, a.get("pos") or rec.get("pos"), rec.get("dob"))
                if p is None:
                    slot = draft_slot.get(a["pid"])
                    if slot and slot[1]:
                        a["at"] = curve_value(curve, slot[1]) * DISCOUNT ** max(0, slot[0] - an.start_year(s0))
                        a["now"] = a["at"]
                        a["note"] = f"prospect with no NHL games: valued at the draft slot (No. {slot[1]}, {slot[0]})"
                    else:
                        a["note"] = "no NHL games: replacement level"
                    continue
                if p["kind"] == "G":
                    p["avail"] = 1.0
                a["kind2"] = p["kind"]
                a["pos"] = a.get("pos") or p["pos"]
                inputs.append(p)
                owners.append(a)
            elif a["kind"] == "pick":
                a["at"] = pick_value(curve, a, s0)
                a["now"] = a["at"]
        res = V.project(inputs, f) if inputs else []
        for a, r in zip(owners, res):
            a["at"] = r["total"]
            a["age"] = r.get("age")
            rz = realised(sk, gk, vr, a["pid"], a["to"], d, a.get("kind2") or "S", s0, end)
            a["realised"] = rz["disc"]
            a["gp_since"] = rz["gp"]
            vn = val_now.get(a["pid"])
            remain = 0.0
            if vn and roster_now.get(a["pid"]) == a["to"]:
                j = an.start_year(s_now) - an.start_year(s0)
                for k, ev in enumerate(vn.get("ev") or []):
                    kk = j + k
                    if 0 <= kk <= V.HORIZON:
                        remain += DISCOUNT ** kk * ev
            elif vn is None and roster_now.get(a["pid"]) == a["to"]:
                remain = max(0.0, r["total"] - rz["disc"])
            a["still"] = roster_now.get(a["pid"]) == a["to"]
            a["now"] = rz["disc"] + remain
        teams = dl["teams"]
        nside = max(len(teams), 2)
        vals = {}
        for t in teams:
            got = [a for a in dl["assets"] if a["to"] == t]
            sent = [a for a in dl["assets"] if a["from"] == t]
            vals[t] = {"at": sum(max(0.0, a["at"]) for a in got), "now": sum(max(0.0, a["now"]) for a in got),
                       "realised": sum(max(0.0, a["realised"]) for a in got),
                       "sent_at": sum(max(0.0, a["at"]) for a in sent), "sent_now": sum(max(0.0, a["now"]) for a in sent)}
        tot_at = sum(v["at"] for v in vals.values())
        tot_now = sum(v["now"] for v in vals.values())
        for t, v in vals.items():
            v["share_at"] = v["at"] / tot_at if tot_at > 0 else None
            v["share_now"] = v["now"] / tot_now if tot_now > 0 else None
            v["grade_at"] = grade(v["share_at"] * nside / 2) if v["share_at"] is not None else None
            v["grade_now"] = grade(v["share_now"] * nside / 2) if v["share_now"] is not None else None
            v["net_at"] = v["at"] - v["sent_at"]
            v["net_now"] = v["now"] - v["sent_now"]
        dl["values"] = vals
        dl["total_at"], dl["total_now"] = tot_at, tot_now
        dl["minor"] = tot_at < MINOR_WAR and tot_now < MINOR_WAR
        for key in ("at", "now"):
            best = max(teams, key=lambda t: vals[t][f"share_{key}"] or 0)
            g = vals[best][f"grade_{key}"]
            dl[f"winner_{key}"] = None if dl["minor"] or g in (None, "C") else best
        dl["season"] = s0
    return deals


# ---------------------------------------------------------------------------------------------- payloads

def _r(v, nd=2):
    v = an.fnum(v)
    return None if v is None or not math.isfinite(v) else round(v, nd)


def asset_out(a: dict) -> dict:
    o = {"k": a["kind"], "from": a["from"], "to": a["to"]}
    if a["kind"] == "player":
        o.update({"pid": a.get("pid"), "name": a.get("name"), "pos": a.get("pos"), "at": _r(a.get("at")), "real": _r(a.get("realised")),
                  "now": _r(a.get("now")), "gp": a.get("gp_since")})
        if a.get("rights"):
            o["rights"] = 1
        if a.get("note"):
            o["note"] = a["note"]
        if a.get("still") is False and a.get("pid"):
            o["gone"] = 1
        if a.get("match") and a["match"] not in ("exact",):
            o["match"] = a["match"]
    elif a["kind"] == "pick":
        o.update({"year": a.get("year"), "round": a.get("round"), "overall": a.get("overall"), "cond": 1 if a.get("cond") else 0,
                  "at": _r(a.get("at")), "now": _r(a.get("now"))})
        if a.get("inferred_year"):
            o["yr_inferred"] = 1
    return o


def build(season: int, rows: list[list], ix: NameIndex, asof, val_now: dict[str, dict], roster_now: dict[str, str], curve: dict | None,
          vr: dict[int, dict], logs: dict, f: dict, today: date, drafts: dict[int, dict], phase: str | None = None,
          resolver=None) -> dict:
    """{"transactions": payload, "deals": payload, "n": counts}. `resolver(names) -> {name: [{"pid","name","pos","team",
    "last"}]}` looks up names in trades that the index does not know (sources/moves.search)."""
    lo = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    clauses = []
    for r in rows:
        if str(r[0])[:10] < lo:
            continue
        clauses += parse_row(r)
    # name matching for every clause
    unmatched = []
    n_names = n_match = 0
    for c in clauses:
        teams = {c["team"]}
        if c.get("trade"):
            teams.add(c["trade"]["cp"])
        for p in c.get("players") or []:
            if p.get("pid"):
                continue
            pid, how = ix.match(p["name"], teams, p.get("pos"))
            p["pid"], p["match"] = pid, how
            n_names += 1
            if pid:
                n_match += 1
            else:
                unmatched.append([p["name"], c["team"], c["date"], c["type"], how])
    if resolver is not None:
        # names in trades that no local list knows: the NHL's player search (exact normalised name; the club breaks ties)
        want = sorted({p["name"] for c in clauses if c.get("trade") for p in c.get("players") or [] if not p.get("pid")})
        found = resolver(want) if want else {}
        for nm, res in (found or {}).items():
            for r in res:
                if norm_name(r.get("name") or "") == norm_name(nm):
                    ix.add(r["pid"], r["name"], r.get("team"), r.get("pos"), an.inum(r.get("last")))
        if found:
            unmatched = []
            for c in clauses:
                teams = {c["team"]} | ({c["trade"]["cp"]} if c.get("trade") else set())
                for p in c.get("players") or []:
                    if not p.get("pid"):
                        pid, how = ix.match(p["name"], teams, p.get("pos"))
                        p["pid"], p["match"] = pid, how
                        if pid:
                            n_match += 1
                        else:
                            unmatched.append([p["name"], c["team"], c["date"], c["type"], how])
    deals = group_deals(clauses)
    rate_deals(deals, ix, asof, val_now, roster_now, curve, vr, logs, f, today, drafts)
    deal_of = {}
    for dl in deals:
        for t, txt in dl["text"]:
            deal_of[(t, txt)] = dl["id"]
    tx_rows = []
    for c in sorted(clauses, key=lambda c: (c["date"], c["team"] or ""), reverse=True):
        ps = [[p.get("pid"), (ix.info.get(p.get("pid")) or {}).get("name") or p["name"]] for p in c.get("players") or []]
        tx_rows.append([c["date"], c["team"], c["type"], c["text"], ps, deal_of.get((c["team"], c["text"]))])
    counts: dict[str, int] = {}
    for c in clauses:
        counts[c["type"]] = counts.get(c["type"], 0) + 1
    # league table
    table: dict[str, dict] = {}
    for dl in deals:
        for t, v in dl["values"].items():
            x = table.setdefault(t, {"deals": 0, "in_at": 0.0, "out_at": 0.0, "in_now": 0.0, "out_now": 0.0, "won": 0, "lost": 0})
            x["deals"] += 1
            x["in_at"] += v["at"]
            x["out_at"] += v["sent_at"]
            x["in_now"] += v["now"]
            x["out_now"] += v["sent_now"]
            if dl.get("winner_now") == t:
                x["won"] += 1
            elif dl.get("winner_now") and t in dl["teams"]:
                x["lost"] += 1
    for t, x in table.items():
        x["net_at"] = x["in_at"] - x["out_at"]
        x["net_now"] = x["in_now"] - x["out_now"]
    ranked = sorted([d for d in deals if not d["minor"]], key=lambda d: -max((v["net_now"] for v in d["values"].values()), default=0))
    deal_rows = []
    for dl in deals:
        deal_rows.append({"id": dl["id"], "date": dl["date"], "teams": dl["teams"], "minor": dl["minor"],
                          "winner_at": dl.get("winner_at"), "winner_now": dl.get("winner_now"),
                          "total_at": _r(dl["total_at"]), "total_now": _r(dl["total_now"]),
                          "sides": {t: {"at": _r(v["at"]), "real": _r(v["realised"]), "now": _r(v["now"]), "sent_at": _r(v["sent_at"]),
                                        "sent_now": _r(v["sent_now"]), "share_at": _r(v["share_at"], 3), "share_now": _r(v["share_now"], 3),
                                        "grade_at": v["grade_at"], "grade_now": v["grade_now"], "net_at": _r(v["net_at"]), "net_now": _r(v["net_now"])}
                                    for t, v in dl["values"].items()},
                          "assets": [asset_out(a) for a in dl["assets"]], "text": dl["text"]})
    n_assets = sum(1 for d in deals for a in d["assets"] if a["kind"] == "player")
    n_assets_m = sum(1 for d in deals for a in d["assets"] if a["kind"] == "player" and a.get("pid"))
    meta = {"source": "ESPN public site API (NHL transactions); values from our models", "window": {"from": lo, "to": today.isoformat()},
            "note": "Values are on-field model value (WAR), not contracts or the salary cap: there is no free, legitimate salary source we use."}
    tx = {"ok": True, "season": int(season), "updated_at": an.now(), "phase": phase, "version": VERSION, **meta,
          "types": TYPES, "cols": ["date", "team", "type", "text", "players", "deal"], "rows": tx_rows, "counts": counts,
          "names": {"named": n_names, "matched": n_match}, "unmatched": unmatched[:400], "n_unmatched": len(unmatched)}
    dp = {"ok": True, "season": int(season), "updated_at": an.now(), "phase": phase, "version": VERSION, **meta,
          "constants": {"discount": DISCOUNT, "minor_war": MINOR_WAR, "grades": [[c, g] for c, g in GRADES], "deal_days": DEAL_DAYS,
                        "horizon": 3},
          "deals": deal_rows, "teams": {t: {k: (_r(v) if isinstance(v, float) else v) for k, v in x.items()} for t, x in sorted(table.items())},
          "best": [d["id"] for d in ranked[:10]],
          "pick_curve": {k: v for k, v in (curve or {}).items() if k != "raw"} if curve else None,
          "pick_raw": (curve or {}).get("raw"),
          "n": {"deals": len(deals), "graded": sum(1 for d in deals if not d["minor"]), "players": n_assets, "players_matched": n_assets_m,
                "picks": sum(1 for d in deals for a in d["assets"] if a["kind"] == "pick")}}
    return {"transactions": tx, "deals": dp, "n": {"clauses": len(clauses), "trades": sum(1 for c in clauses if c.get("trade")),
                                                   "deals": len(deals), "unmatched": len(unmatched), "names": n_names}}
