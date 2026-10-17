"""
Transactions feed, team ledgers and trade ratings (docs/VALUE_SECTIONS.md section 4; payloads transactions.json and
ledgers/<abbr>.json, PAYLOADS.md "As built").

Source: ESPN's public transactions list (sources/espn.transactions: site .../transactions?season=<calendar year>),
the same public site data the rest of the site uses for live scores, credited on the page. Each entry is a club's
free-text note ("Traded WR X and a 2027 sixth-round draft pick to Houston for 2027 second- and seventh-round draft
picks. Signed ..."), often one per club for the same trade, sometimes with typos. Left out on purpose:
  * nflverse `trades` (load_trades): Lee Sharpe's table built from Pro Football Reference, whose terms forbid this
    use (sports-reference.com/data_use: no websites or tools built on data taken from its sites);
  * nflverse `draft_picks`: "courtesy of PFR", same reason. Draft slots come from the players release, which takes
    them from the NFL's own draft API from 2008 (valuation.FIRST_DRAFT);
  * contracts and cap figures (OverTheCap's terms; analytics/contracts.py).

Parsing
-------
A note is split into clauses at each sentence that starts with a verb ESPN uses (Traded, Acquired, Received, Signed,
Released, Waived, Placed, Claimed, ...). Trade clauses:
  Traded <gives> to <club> [for | in exchange for <gets>]
  Acquired <gets> [from (the) <club> | from (a) trade with <club>] [for | in exchange (for) <gives>]
  Received <gets> [from <club> | from a trade with <club> | in a trade with <club>] [in exchange for <gives>]
Assets: players ("<POS> <Name>", plural positions carry over a list), picks (every round word followed by "pick",
"picks" or "selection", the nearest preceding year; "conditional" anywhere in the phrase; "the 172nd 2025 pick" as an
overall slot; no year = the next draft after the note's date) and draft considerations (nothing). Club names map to
abbreviations by nickname, then city; "Los Angeles" and "New York" stay ambiguous until the other club's note or the
players' previous clubs settle them. Players are matched to gsis ids by normalised name (suffixes and punctuation
dropped, a close spelling allowed within the position group), preferring a player on the giving club's weekly roster.
Notes of the same trade (each club's, and repeats on the next day) are merged when the club pair matches within four
days and the assets overlap, or the pair is unique in that window.

Ratings
-------
Each side's assets are valued in the value page's currency (points above replacement; analytics/valuation.py):
  * at the time: a player's projection from the seasons completed before the trade (the rest of that season and the
    next three, discounted 10% a season; in-season form before the trade is not re-modelled); a pick at the draft-pick
    value curve (its round's mean when the slot is unknown; conditional picks count half; discounted for the seasons
    until it is used);
  * realised: his GVAR per game in each season since, times the games he has played for his new club after the trade
    date (nflverse weekly player stats);
  * now: realised plus what is still projected for him (this season's valuation) while he is on that club's roster;
    picks stay at their curve value (our sources cannot say which player a traded pick became).
Net = value received minus value sent, in points and wins (x k_resp x wins per point). Grades on the net in wins:
A >= +1, B >= +0.3, C within 0.3 of even, D >= -1, F below. Offensive linemen and long snappers are not valued (we
cannot measure them) and are flagged; a side made only of them reads "not rated".
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from oddsmarkets.nfl import analytics as an

logger = logging.getLogger(__name__)

VERSION = "transactions-1"
WINDOW_DAYS = 365
TTL_HOURS = 6.0
GRADES = ((1.0, "A"), (0.3, "B"), (-0.3, "C"), (-1.0, "D"))
CREDIT = "Transactions: ESPN's public NFL transactions list (club notes as published), parsed by us."
LEFT_OUT = ("Not used, for their terms: nflverse's trades table and draft-pick table (both from Pro Football Reference, "
            "whose terms forbid building websites or tools on its data) and contract figures (OverTheCap's terms).")

TEAM_NAMES = {
    "ARI": ("Arizona", "Cardinals"), "ATL": ("Atlanta", "Falcons"), "BAL": ("Baltimore", "Ravens"), "BUF": ("Buffalo", "Bills"),
    "CAR": ("Carolina", "Panthers"), "CHI": ("Chicago", "Bears"), "CIN": ("Cincinnati", "Bengals"), "CLE": ("Cleveland", "Browns"),
    "DAL": ("Dallas", "Cowboys"), "DEN": ("Denver", "Broncos"), "DET": ("Detroit", "Lions"), "GB": ("Green Bay", "Packers"),
    "HOU": ("Houston", "Texans"), "IND": ("Indianapolis", "Colts"), "JAX": ("Jacksonville", "Jaguars"), "KC": ("Kansas City", "Chiefs"),
    "LA": ("Los Angeles", "Rams"), "LAC": ("Los Angeles", "Chargers"), "LV": ("Las Vegas", "Raiders"), "MIA": ("Miami", "Dolphins"),
    "MIN": ("Minnesota", "Vikings"), "NE": ("New England", "Patriots"), "NO": ("New Orleans", "Saints"), "NYG": ("New York", "Giants"),
    "NYJ": ("New York", "Jets"), "PHI": ("Philadelphia", "Eagles"), "PIT": ("Pittsburgh", "Steelers"), "SF": ("San Francisco", "49ers"),
    "SEA": ("Seattle", "Seahawks"), "TB": ("Tampa Bay", "Buccaneers"), "TEN": ("Tennessee", "Titans"), "WAS": ("Washington", "Commanders"),
}
ESPN_ABBR = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA"}
VERBS = ("Traded", "Trade", "Acquired", "Received", "Signed", "Singed", "SIgned", "Re-signed", "Resigned", "Released", "Release",
         "Waived", "Waived/injured", "Waived/Injured", "Waiving", "Placed", "PLaced", "Claimed", "Activated", "Reinstated", "Designated",
         "Elevated", "Elevate", "Elevating", "Elevation", "Reverted", "Promoted", "Agreed", "Hired", "Fired", "Named", "Restructured",
         "Announced", "Tendered", "Exercised", "Terminated", "Declined", "Returned", "Tried", "Transferred", "Extended", "Recalled",
         "Suspended", "Converted", "Removed", "Moved", "Reached", "Assigned")
_SPLIT = re.compile(r"(?:(?<=\.)|(?<=\.\")|(?<=;))\s+(?=(?:" + "|".join(sorted((re.escape(v) for v in VERBS), key=len, reverse=True)) + r")\b)")
ROUND_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
               "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7}
_ROUND = re.compile(r"\b(first|second|third|fourth|fifth|sixth|seventh|1st|2nd|3rd|4th|5th|6th|7th)\b(?=[\s,\-])", re.I)
_PICKWORD = re.compile(r"\b(?:picks?|selections?)\b", re.I)
_OVERALL = re.compile(r"\bthe\s+(\d{1,3})(?:st|nd|rd|th)\s+(?:overall\s+)?(?:pick\s+(?:in\s+the\s+)?)?(\d{4})(?:\s+(?:overall\s+)?(?:draft\s+)?pick)?", re.I)
POS_TOKENS = ("QB", "RB", "FB", "HB", "WR", "TE", "OT", "OG", "OL", "IOL", "LT", "RT", "LG", "RG", "T/G", "G/T", "C/G", "G/C", "OF", "T",
              "G", "C", "DE", "DT", "NT", "DL", "EDGE", "OLB", "ILB", "MLB", "LB", "CB", "FS", "SS", "S", "DB", "K", "PK", "P", "LS", "KR", "PR")
_POS_ALT = "|".join(re.escape(p) for p in sorted(POS_TOKENS, key=len, reverse=True))
_NAMEWORD = r"(?:[A-Z][\w'’.\-]*|de|van|von|da|di|la|le|del|dos|du|St\.)"
_SUFFIX = r"(?:Jr\.?|Sr\.?|II|III|IV|V)"
_PLAYER = re.compile(r"(?<![A-Za-z/])(" + _POS_ALT + r")(s)?\s+(" + _NAMEWORD + r"(?:\s+(?:" + _NAMEWORD + r"|" + _SUFFIX + r"))*)")
_LISTNAME = re.compile(r"^(?:,\s*(?:and\s+)?|\s+and\s+)(" + _NAMEWORD + r"(?:\s+(?:" + _NAMEWORD + r"|" + _SUFFIX + r"))+)")
POS_GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "TE", "K": "K", "PK": "K", "P": "P", "LS": "LS",
             "OT": "OL", "OG": "OL", "OL": "OL", "IOL": "OL", "LT": "OL", "RT": "OL", "LG": "OL", "RG": "OL", "T/G": "OL", "G/T": "OL",
             "C/G": "OL", "G/C": "OL", "OF": "OL", "T": "OL", "G": "OL", "C": "OL", "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL",
             "EDGE": "DL", "OLB": "LB", "ILB": "LB", "MLB": "LB", "LB": "LB", "CB": "DB", "FS": "DB", "SS": "DB", "S": "DB", "DB": "DB",
             "SAF": "DB", "KR": "WR", "PR": "WR"}
TYPES = ("trade", "signing", "extension", "release", "claim", "reserve", "activation", "practice", "other")


# ---------------------------------------------------------------------------------------------- text helpers

def norm_name(s: Any) -> str:
    """Lower case, accents and punctuation dropped, suffixes (Jr, Sr, II-V) removed: "D.K. Metcalf" -> "dk metcalf"."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[.'’`]", "", t.lower())
    t = re.sub(r"[-]", " ", t)
    words = [w for w in t.split() if w not in ("jr", "sr", "ii", "iii", "iv", "v")]
    return " ".join(words)


def clauses(text: Any) -> list[str]:
    """A note split into its sentences that start with a transaction verb (the rest stay attached)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return []
    return [c.strip() for c in _SPLIT.split(s) if c.strip()]


def espn_team(abbr: Any) -> str | None:
    s = str(abbr or "").upper()
    s = ESPN_ABBR.get(s, s)
    return s if s in TEAM_NAMES else None


def team_from_text(s: Any) -> list[str]:
    """Candidate abbreviations for a club as ESPN writes it ("the Los Angeles Rams", "Houston", "N.Y. Jets",
    "Los Angeles" -> ["LA", "LAC"])."""
    t = re.sub(r"\s+", " ", str(s or "")).strip().rstrip(".")
    t = re.sub(r"^(?:the|a)\s+", "", t, flags=re.I)
    t = t.replace("N.Y.", "New York").replace("L.A.", "Los Angeles")
    low = t.lower()
    nick = [a for a, (city, nk) in TEAM_NAMES.items() if re.search(r"\b" + re.escape(nk.lower()) + r"\b", low)]
    if len(nick) == 1:
        return nick
    city = [a for a, (cty, nk) in TEAM_NAMES.items() if low.startswith(cty.lower())]
    if city:
        return city
    if low in ("washington football team", "football team"):
        return ["WAS"]
    return []


def default_draft_year(d: date) -> int:
    """The next draft after a date: the draft is held in late April."""
    return d.year if (d.month, d.day) < (4, 30) else d.year + 1


def parse_picks(text: str, d: date) -> list[dict]:
    """Picks named in an asset phrase: [{"year", "round", "overall", "conditional"}]."""
    out = []
    used = []
    for m in _OVERALL.finditer(text):
        ov, yr = int(m.group(1)), int(m.group(2))
        if 1 <= ov <= 300 and 1990 < yr < 2100:
            out.append({"year": yr, "round": min(7, (ov - 1) // 32 + 1), "overall": ov, "conditional": "conditional" in text[max(0, m.start() - 15):m.end()].lower()})
            used.append((m.start(), m.end()))
    pick_ends = [m.end() for m in _PICKWORD.finditer(text)]
    for m in _ROUND.finditer(text):
        if any(a <= m.start() < b for a, b in used):
            continue
        after = text[m.end():]
        nxt_pick = _PICKWORD.search(after)
        nxt_player = _PLAYER.search(after)
        if not nxt_pick or nxt_pick.start() > 60 or (nxt_player and nxt_player.start() < nxt_pick.start()):
            continue
        prev_end = max([e for e in pick_ends if e <= m.start()] or [0])
        seg = text[prev_end:m.start()]
        yrs = re.findall(r"\b(19\d\d|20\d\d)\b", seg)
        seg_after = after[:nxt_pick.start()]
        yrs_after = re.findall(r"\b(19\d\d|20\d\d)\b", seg_after)
        yr = int(yrs[-1]) if yrs else (int(yrs_after[0]) if yrs_after else default_draft_year(d))
        cond = "conditional" in (seg + seg_after).lower()
        out.append({"year": yr, "round": ROUND_WORDS[m.group(1).lower()], "overall": None, "conditional": cond})
    return out


def parse_players(text: str) -> list[dict]:
    """[{"pos", "name"}] for every "<POS> <Name>" (a plural position carries over a following list of names)."""
    out = []
    for m in _PLAYER.finditer(text):
        pos, plural, name = m.group(1), m.group(2), m.group(3).strip().rstrip(".,")
        name = re.sub(r"\s+(?:and|to|from|for|in|on|as|with)$", "", name)
        if len(name) < 3 or name.lower() in ("the", "a", "an"):
            continue
        if re.match(r"^(?:The|A|An)\s", name):
            continue
        out.append({"pos": pos.upper(), "name": name})
        if plural:
            rest = text[m.end():]
            while True:
                mm = _LISTNAME.match(rest)
                if not mm:
                    break
                nm = mm.group(1).strip().rstrip(".,")
                if re.match(r"^(?:" + _POS_ALT + r")s?\s", nm):
                    break
                out.append({"pos": pos.upper(), "name": nm})
                rest = rest[mm.end():]
    return out


def parse_assets(text: str, d: date) -> dict:
    t = re.sub(r"\([^)]*\)", "", str(text or ""))
    return {"players": dedupe_players(parse_players(t)), "picks": parse_picks(t, d),
            "considerations": bool(re.search(r"considerations|future considerations|cash", t, re.I))}


_TRADED = re.compile(r"^Trade[ds]?\s+(?P<gives>.+?)\s+to\s+(?P<team>(?:the\s+)?[A-Z][\w.'’ ]+?)(?:\s+(?:in exchange for|in exchange|for)\s+(?P<gets>.+?))?\.?$")
_ACQ = re.compile(r"^(?:Acquired|Received)\s+(?P<gets>.+?)(?:\s+(?:from|in)\s+(?:a\s+)?(?:trade\s+with\s+)?(?P<team>(?:the\s+)?[A-Z][\w.'’ ]+?))?"
                  r"(?:\s+(?:in exchange for|in exchange|for)\s+(?P<gives>.+?))?\.?$")


def classify(clause: str) -> str:
    c = clause.strip()
    low = c.lower()
    if re.match(r"^(?:hired|fired|named|announced)\b", low):
        return "other"
    if re.match(r"^(?:traded?|trade)\b", low):
        return "trade"
    if re.match(r"^(?:acquired|received)\b", low):
        if "waivers" in low:
            return "claim"
        if "exemption" in low:
            return "other"
        return "trade"
    if re.match(r"^claimed\b", low):
        return "claim"
    if re.match(r"^(?:signed|singed|re-signed|resigned|agreed)\b", low):
        if "practice squad" in low and "from the practice squad" not in low:
            return "practice"
        if "extension" in low:
            return "extension"
        return "signing"
    if re.match(r"^(?:released|release|waived|waiving|terminated)\b", low):
        if "practice squad" in low:
            return "practice"
        return "release"
    if re.match(r"^(?:placed|reverted|designated|suspended)\b", low) or "injured reserve" in low:
        if re.match(r"^designated", low) and "return" in low:
            return "activation"
        return "reserve"
    if re.match(r"^(?:activated|reinstated|returned|recalled)\b", low):
        return "activation"
    if re.match(r"^(?:elevated|elevate|elevating|elevation|promoted)\b", low):
        return "practice"
    if re.match(r"^(?:restructured|extended|exercised|tendered|declined)\b", low):
        return "extension"
    return "other"


def parse_trade(team: str, d: date, clause: str) -> dict | None:
    """One club's trade clause -> {"date", "team", "counter" (candidates), "gets", "gives", "text"}; None when the
    clause is not a trade."""
    c = re.sub(r"\([^)]*\)", "", clause).strip()
    c = re.sub(r"\s+", " ", c)
    if classify(c) != "trade":
        return None
    m = _TRADED.match(c)
    if m:
        gives, gets, tm = m.group("gives"), m.group("gets") or "", m.group("team")
    else:
        m = _ACQ.match(c)
        if not m:
            return None
        gets, gives, tm = m.group("gets"), m.group("gives") or "", m.group("team") or ""
    counter = team_from_text(tm) if tm else []
    counter = [x for x in counter if x != team]
    return {"date": d.isoformat(), "team": team, "counter": counter, "gets": parse_assets(gets, d), "gives": parse_assets(gives, d),
            "text": clause.strip()}


def _date(s: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        try:
            return date.fromisoformat(str(s)[:10])
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------------------------- player matching

class Matcher:
    """Names to gsis ids: {normalised name: [ids]} from the people table, with each id's position group and
    seasons, and the weekly rosters' clubs ({pid: [(date-ish, team)]}) for disambiguation."""

    def __init__(self, people: dict[str, dict], rosters: dict[str, list[tuple]] | None = None):
        self.people = people or {}
        self.idx: dict[str, list[str]] = {}
        for pid, p in self.people.items():
            n = norm_name(p.get("name"))
            if n:
                self.idx.setdefault(n, []).append(pid)
        self.rosters = rosters or {}
        self.by_last: dict[str, list[str]] = {}
        for n, ids in self.idx.items():
            self.by_last.setdefault(n.split()[-1], []).extend(ids)

    def _group(self, pid: str) -> str | None:
        p = self.people.get(pid) or {}
        return POS_GROUP.get(str(p.get("pos") or "").upper()) or ("DL" if str(p.get("group")) == "DEF" else None)

    def _team_before(self, pid: str, d: date) -> str | None:
        best = None
        for when, t in self.rosters.get(pid, []):
            if when <= d and (best is None or when >= best[0]):
                best = (when, t)
        return best[1] if best else None

    def _team_after(self, pid: str, d: date) -> str | None:
        best = None
        for when, t in self.rosters.get(pid, []):
            if when >= d and (best is None or when <= best[0]):
                best = (when, t)
        return best[1] if best else None

    def match(self, pos: str, name: str, d: date, team_hint: str | list | None = None) -> str | None:
        n = norm_name(name)
        if not n:
            return None
        grp = POS_GROUP.get(str(pos).upper())
        cands = list(self.idx.get(n, []))
        if not cands:
            # a close spelling within the same surname or position group ("Tyron-Shoyinka" for "Tryon-Shoyinka")
            last = n.split()[-1]
            pool = set(self.by_last.get(last, []))
            if not pool:
                pool = {pid for nn, ids in self.idx.items() if nn[:1] == n[:1] and abs(len(nn) - len(n)) <= 3 for pid in ids}
            scored = []
            for pid in pool:
                r = SequenceMatcher(None, n, norm_name(self.people[pid].get("name"))).ratio()
                if r >= 0.86:
                    scored.append((r, pid))
            scored.sort(reverse=True)
            cands = [pid for r, pid in scored if r >= scored[0][0] - 0.02] if scored else []
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        hints = [team_hint] if isinstance(team_hint, str) else list(team_hint or [])

        def score(pid):
            p = self.people.get(pid) or {}
            s = 0.0
            last = an.inum(p.get("last"))
            if last is not None and last >= d.year - 2:
                s += 2.0
            if grp and self._group(pid) == grp:
                s += 1.0
            tb = self._team_before(pid, d)
            if tb and tb in hints:
                s += 3.0
            elif tb:
                s += 0.5
            return s
        cands.sort(key=lambda pid: -score(pid))
        return cands[0] if score(cands[0]) > score(cands[1]) else (cands[0] if score(cands[0]) >= 3 else None)


# ---------------------------------------------------------------------------------------------- merging

def _asset_keys(a: dict) -> set:
    ks = set()
    for p in a.get("players") or []:
        nm = norm_name(p.get("name")).split()
        ks.add(("p", p.get("pid") or " ".join(nm[:2])))
    for k in a.get("picks") or []:
        ks.add(("k", k.get("year"), k.get("round")))
    return ks


def _same_player(p: dict, q: dict) -> bool:
    if p.get("pid") and q.get("pid"):
        return p["pid"] == q["pid"]
    a, b = norm_name(p.get("name")).split(), norm_name(q.get("name")).split()
    if not a or not b:
        return False
    n = min(len(a), len(b))
    return a[:n] == b[:n]


def dedupe_players(ps: list[dict]) -> list[dict]:
    """Drop repeats and truncated repeats ("QB Dorian" beside "QB Dorian Thompson-Robinson"), keeping the fuller name."""
    out: list[dict] = []
    for p in sorted(ps, key=lambda x: (0 if x.get("pid") else 1, -len(str(x.get("name") or "")))):
        if not any(_same_player(p, q) for q in out):
            out.append(p)
    order = {id(p): i for i, p in enumerate(ps)}
    return sorted(out, key=lambda x: order.get(id(x), 0))


def _union(a: dict, b: dict) -> dict:
    out = {"players": list(a.get("players") or []), "picks": list(a.get("picks") or []),
           "considerations": bool(a.get("considerations") or b.get("considerations"))}
    for p in b.get("players") or []:
        if not any(_same_player(p, q) for q in out["players"]):
            out["players"].append(p)
    out["players"] = dedupe_players(out["players"])
    cnt: dict[tuple, int] = {}
    for k in out["picks"]:
        cnt[(k.get("year"), k.get("round"))] = cnt.get((k.get("year"), k.get("round")), 0) + 1
    seen: dict[tuple, int] = {}
    for k in b.get("picks") or []:
        key = (k.get("year"), k.get("round"))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > cnt.get(key, 0):
            out["picks"].append(k)
    return out


def _role(t: dict, team: str) -> str | None:
    """"a" or "b" when the club is already a party to the trade record, else None."""
    if t["a"] == team:
        return "a"
    if t["b"] == team:
        return "b"
    return None


def _fits(t: dict, s: dict, d: date) -> int | None:
    """Overlap of a club note with a trade record (None when they cannot be the same trade)."""
    gap = abs((date.fromisoformat(t["date"]) - d).days)
    if gap > 10:
        return None
    team, cands = s["team"], s.get("counter") or []
    r = _role(t, team)
    if r is None:
        if t["b"] is not None:
            return None
        if t["b_cands"] and team not in t["b_cands"]:
            return None
        if cands and t["a"] not in cands:
            return None
        r = "b"
    other = t["b"] if r == "a" else t["a"]
    if cands and other is not None and other not in cands:
        return None
    o = "b" if r == "a" else "a"
    ov = len(_asset_keys(s["gets"]) & _asset_keys(t["gets"][r])) + len(_asset_keys(s["gives"]) & _asset_keys(t["gets"][o]))
    if gap > 4 and ov < 2:
        return None
    return ov


def merge_sides(sides: list[dict]) -> list[dict]:
    """Club notes -> trades {"date", "teams": [A, B], "gets": {A: assets, B: assets}, "texts": [...]}: notes of the
    same trade (both clubs', repeats) are merged when the clubs fit within four days and the assets overlap, or when
    the other club has no note of its own on that trade yet and no other trade between the pair is in the window."""
    recs: list[dict] = []
    for s in sorted(sides, key=lambda x: x["date"]):
        d = date.fromisoformat(s["date"])
        best = None
        for t in recs:
            ov = _fits(t, s, d)
            if ov is None:
                continue
            if best is None or ov > best[0]:
                best = (ov, t)
        if best is not None and best[0] == 0:
            t = best[1]
            same_pair = [x for x in recs if _fits(x, s, d) is not None]
            already = any(n["team"] == s["team"] for n in t["texts"])
            if len(same_pair) != 1 or already:
                best = None
        if best is None:
            cands = [c for c in (s.get("counter") or []) if c != s["team"]]
            recs.append({"date": s["date"], "a": s["team"], "b": cands[0] if len(cands) == 1 else None, "b_cands": cands,
                         "gets": {"a": s["gets"], "b": s["gives"]}, "texts": [{"team": s["team"], "date": s["date"], "text": s["text"]}]})
            continue
        t = best[1]
        r = _role(t, s["team"])
        if r is None:
            t["b"], r = s["team"], "b"
        o = "b" if r == "a" else "a"
        t["gets"][r] = _union(t["gets"][r], s["gets"])
        t["gets"][o] = _union(t["gets"][o], s["gives"])
        if t["b"] is None and r == "a":
            cands = [c for c in (s.get("counter") or []) if c != s["team"]]
            if len(cands) == 1:
                t["b"] = cands[0]
            elif cands:
                t["b_cands"] = [c for c in t["b_cands"] if c in cands] or cands
        t["texts"].append({"team": s["team"], "date": s["date"], "text": s["text"]})
    out = []
    for t in recs:
        out.append({"date": t["date"], "teams": [t["a"], t["b"]], "cands": t["b_cands"], "texts": t["texts"],
                    "gets": {t["a"]: t["gets"]["a"], t["b"]: t["gets"]["b"]}})
    return out


def resolve_counters(trades: list[dict], matcher: "Matcher | None") -> None:
    """An unknown or ambiguous club: the previous club of the players this side received (weekly rosters), else the
    single candidate the note named."""
    for t in trades:
        a, o = t["teams"]
        if o is not None:
            continue
        cands = t.get("cands") or []
        prev = []
        for p in (t["gets"].get(a) or {}).get("players") or []:
            if p.get("pid") and matcher is not None:
                tb = matcher._team_before(p["pid"], date.fromisoformat(t["date"]) - timedelta(days=1))
                if tb and tb != a:
                    prev.append(tb)
        for p in (t["gets"].get(None) or {}).get("players") or []:
            if p.get("pid") and matcher is not None:
                ta = matcher._team_after(p["pid"], date.fromisoformat(t["date"]) + timedelta(days=1))
                if ta and ta != a:
                    prev.append(ta)
        pick = [x for x in prev if not cands or x in cands]
        if pick:
            o = max(set(pick), key=pick.count)
        elif len(cands) == 1:
            o = cands[0]
        if o is not None:
            t["teams"][1] = o
            t["gets"][o] = t["gets"].pop(None, {"players": [], "picks": []})


# ---------------------------------------------------------------------------------------------- the feed

def feed(raw: list[dict], since: date, until: date | None = None) -> list[dict]:
    """[{"date", "team", "type", "text", "players": [{"pos", "name"}]}] per clause, newest first."""
    out = []
    for r in raw:
        d = _date(r.get("date"))
        t = espn_team(r.get("team"))
        if d is None or t is None or d < since or (until and d > until):
            continue
        for c in clauses(r.get("text")):
            ty = classify(c)
            if ty == "other" and not _PLAYER.search(c):
                continue
            out.append({"date": d.isoformat(), "team": t, "type": ty, "text": c, "players": parse_players(re.sub(r"\([^)]*\)", "", c))})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def trade_sides(raw: list[dict], since: date) -> list[dict]:
    out = []
    for r in raw:
        d = _date(r.get("date"))
        t = espn_team(r.get("team"))
        if d is None or t is None or d < since:
            continue
        for c in clauses(r.get("text")):
            s = parse_trade(t, d, c)
            if s and (s["gets"]["players"] or s["gets"]["picks"] or s["gives"]["players"] or s["gives"]["picks"]):
                out.append(s)
    return out


# ---------------------------------------------------------------------------------------------- ratings

def grade(net_wins: float | None) -> str | None:
    if net_wins is None:
        return None
    for cut, g in GRADES:
        if net_wins >= cut:
            return g
    return "F"


def trade_season(d: date) -> tuple[int, bool]:
    """(the season a date belongs to for valuation, in-season?): September-February belong to the season under way;
    March-August to the coming season (offseason)."""
    if d.month >= 9:
        return d.year, True
    if d.month <= 2:
        return d.year - 1, True
    return d.year, False


class RateCtx:
    """What the ratings need: the value panel by (pid, season) (completed seasons), the fitted curves, the pick curve,
    the current season's records, this season's valuation rows, games by (pid, season) after a date for a club, team
    games remaining after a date, the current rosters, k_resp and wins per point."""

    def __init__(self, season: int, rows_by: dict, curves: dict, pick: dict | None, cur: dict[str, dict], val_now: dict[str, dict],
                 games_log: dict[str, list[tuple]], team_dates: dict[tuple, list[date]], roster_now: dict[str, str], k_resp: float,
                 wpp: float, people: dict | None = None, today: date | None = None):
        self.season, self.rows_by, self.curves, self.pick = season, rows_by, curves, pick
        self.cur, self.val_now, self.games_log, self.team_dates = cur, val_now, games_log, team_dates
        self.roster_now, self.k_resp, self.wpp = roster_now, k_resp, wpp
        self.people = people or {}
        self.today = today or datetime.now(timezone.utc).date()

    def wins(self, pts: float | None) -> float | None:
        return None if pts is None else pts * self.k_resp * self.wpp

    def rate_pg(self, pid: str, s: int) -> float | None:
        if s == self.season:
            return an.fnum((self.cur.get(pid) or {}).get("gvar_pg"))
        r = self.rows_by.get((pid, s))
        return r["x"] if r else None

    def games_after(self, pid: str, team: str, d: date) -> dict[int, int]:
        out: dict[int, int] = {}
        for s, gd, t in self.games_log.get(pid, []):
            if gd > d and t == team:
                out[s] = out.get(s, 0) + 1
        return out

    def remaining(self, team: str, s: int, d: date) -> int:
        ds = self.team_dates.get((team, s)) or []
        if not ds:
            return 17 if d.month in range(3, 9) else 0
        return sum(1 for x in ds if x > d)

    def played_since(self, team: str, s: int, d: date) -> int:
        ds = self.team_dates.get((team, s)) or []
        return sum(1 for x in ds if d < x <= self.today)


def value_player(rc: RateCtx, pid: str | None, pos: str, team: str, d: date) -> dict:
    """{"at", "real", "exp_so_far", "now", "valued"} for a player a club received on date d."""
    from oddsmarkets.nfl.analytics import valuation as VA
    grp = POS_GROUP.get(str(pos).upper())
    if grp in ("OL", "LS") or pid is None:
        return {"valued": False, "why": "offensive linemen are not valued" if grp == "OL" else ("long snappers are not valued" if grp == "LS" else "player not matched")}
    S, in_season = trade_season(d)
    rem = rc.remaining(team, S, d) if in_season else 17
    pj = VA.as_of(pid, None, S, rc.rows_by, rc.curves, float(rem))
    at = pj["total"] if pj else 0.0
    # realised: GVAR per game x games for the new club after the trade date
    real = 0.0
    ga = rc.games_after(pid, team, d)
    for s, n in ga.items():
        x = rc.rate_pg(pid, s)
        if x is not None:
            real += max(0.0, x) * n
    # expected so far from the projection: the share of each projected season that has been played
    exp = 0.0
    if pj:
        for k, (lv, g) in enumerate(zip(pj["levels"], pj["games"])):
            s = S + k
            if s > rc.season:
                break
            if k == 0:
                tot = max(rem, 1)
                frac = min(1.0, rc.played_since(team, s, d) / tot) if s == rc.season else 1.0
            else:
                frac = min(1.0, rc.played_since(team, s, date(s, 3, 1)) / 17.0) if s == rc.season else 1.0
            exp += max(0.0, lv) * g * frac
    # still to come: this season's valuation while he is on the club's roster now
    fut = 0.0
    if rc.roster_now.get(pid) == team:
        v = rc.val_now.get(pid)
        if v:
            for j, (lv, g) in enumerate(zip(v.get("proj") or [], v.get("games") or [])):
                s = rc.season + j
                if s > S + VA.H or lv is None or g is None:
                    break
                fut += VA.DISCOUNT ** j * max(0.0, lv) * g
    return {"valued": True, "at": at, "real": real, "exp_so_far": exp, "now": real + fut, "fut": fut, "games": sum(ga.values()),
            "proj_known": pj is not None}


def value_pick(rc: RateCtx, k: dict, d: date) -> dict:
    from oddsmarkets.nfl.analytics import valuation as VA
    S, _ = trade_season(d)
    at = VA.pick_value(rc.pick, k["year"], k.get("round"), k.get("overall"), S, bool(k.get("conditional")))
    now_s = max(rc.season, S)
    now = VA.pick_value(rc.pick, k["year"], k.get("round"), k.get("overall"), now_s, bool(k.get("conditional")))
    return {"valued": at is not None, "at": at or 0.0, "now": now or 0.0, "real": 0.0, "exp_so_far": 0.0}


def rate(t: dict, rc: RateCtx) -> dict:
    """A merged trade -> its public record: per side the assets with values, totals, nets, grades and the winner."""
    d = date.fromisoformat(t["date"])
    a, b = t["teams"]
    sides = {}
    for team in (a, b):
        if team is None:
            continue
        assets = t["gets"].get(team) or {}
        rows, tot = [], {"at": 0.0, "now": 0.0, "real": 0.0, "exp_so_far": 0.0}
        valued = 0
        for p in assets.get("players") or []:
            v = value_player(rc, p.get("pid"), p.get("pos"), team, d)
            if v.get("valued"):
                valued += 1
                for kk in tot:
                    tot[kk] += v.get(kk) or 0.0
            rows.append({"kind": "player", "pid": p.get("pid"), "name": p.get("name"), "pos": p.get("pos"),
                         "at": an.rnd(v.get("at"), 1), "now": an.rnd(v.get("now"), 1), "real": an.rnd(v.get("real"), 1),
                         "exp": an.rnd(v.get("exp_so_far"), 1), "games": v.get("games"), "valued": bool(v.get("valued")),
                         "why": v.get("why"), "on_roster": rc.roster_now.get(p.get("pid")) == team if p.get("pid") else None})
        for k in assets.get("picks") or []:
            v = value_pick(rc, k, d)
            if v.get("valued"):
                valued += 1
                tot["at"] += v["at"]
                tot["now"] += v["now"]
            rows.append({"kind": "pick", "year": k.get("year"), "round": k.get("round"), "overall": k.get("overall"),
                         "conditional": bool(k.get("conditional")), "at": an.rnd(v.get("at"), 1), "now": an.rnd(v.get("now"), 1),
                         "valued": bool(v.get("valued"))})
        if assets.get("considerations"):
            rows.append({"kind": "considerations", "at": 0.0, "now": 0.0, "valued": True})
        sides[team] = {"assets": rows, "tot": tot, "n_valued": valued, "n": len(rows)}
    out_sides = []
    for team in (a, b):
        if team is None:
            continue
        o = b if team == a else a
        mine, theirs = sides[team]["tot"], (sides.get(o) or {}).get("tot") or {"at": 0.0, "now": 0.0, "real": 0.0}
        net_at, net_now = mine["at"] - theirs["at"], mine["now"] - theirs["now"]
        rated = sides[team]["n_valued"] > 0 or ((sides.get(o) or {}).get("n_valued") or 0) > 0
        out_sides.append({"team": team, "gets": sides[team]["assets"], "in_at": an.rnd(mine["at"], 1), "in_now": an.rnd(mine["now"], 1),
                          "real": an.rnd(mine["real"], 1), "exp_so_far": an.rnd(mine["exp_so_far"], 1),
                          "net_at": an.rnd(net_at, 1) if rated else None, "net_now": an.rnd(net_now, 1) if rated else None,
                          "wins_at": an.rnd(rc.wins(net_at), 2) if rated else None, "wins_now": an.rnd(rc.wins(net_now), 2) if rated else None,
                          "grade_at": grade(rc.wins(net_at)) if rated else None, "grade_now": grade(rc.wins(net_now)) if rated else None})
    winner = None
    if len(out_sides) == 2 and out_sides[0]["wins_now"] is not None:
        w0 = out_sides[0]["wins_now"]
        winner = "even" if abs(w0) < 0.15 else (out_sides[0]["team"] if w0 > 0 else out_sides[1]["team"])
    return {"date": t["date"], "teams": [x for x in (a, b)], "sides": out_sides, "winner": winner,
            "notes": [x["text"] for x in t["texts"]][:3]}


# ---------------------------------------------------------------------------------------------- loading (cached)

def cache_path(year: int):
    return an.cache_root() / "espn" / "transactions" / f"{int(year)}.json"


def load_year(year: int, today: date, fetch: bool = True, client=None) -> list[dict]:
    """A calendar year's transactions: the cached copy when fresh (TTL_HOURS for the current year, a week for the
    previous, never refetched once the year is two years past), else ESPN (one call per 1,000 entries)."""
    p = cache_path(year)
    old = an.read_json(p) or {}
    rows = old.get("rows") or []
    got = old.get("fetched_at")
    age_h = None
    if got:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(got.replace("Z", "+00:00"))).total_seconds() / 3600
        except ValueError:
            age_h = None
    ttl = TTL_HOURS if year >= today.year else (24 * 7 if year == today.year - 1 else 1e9)
    if rows and age_h is not None and age_h < ttl:
        return rows
    if not fetch:
        return rows
    try:
        from oddsmarkets.nfl.sources import espn as E
        from oddsmarkets.nfl.sources._client import Client
        c = client or Client(budget=20, interval=1.0, name="gridiron-transactions")
        new = E.transactions(c, year)
    except Exception as exc:                                     # noqa: BLE001
        logger.info("transactions %s: %s", year, exc)
        new = None
    if new:
        an.write_json(p, {"year": year, "fetched_at": an.now(), "n": len(new), "rows": new})
        return new
    return rows


# ---------------------------------------------------------------------------------------------- the payloads

FEED_COLS = ["date", "team", "type", "text", "players"]


def build(season: int, today: date, raw: list[dict], matcher: Matcher, rc: RateCtx, teams: list[str]) -> dict:
    """{"transactions": transactions.json, "ledgers": {abbr: ledgers/<abbr>.json}} for the last WINDOW_DAYS."""
    since = today - timedelta(days=WINDOW_DAYS)
    items = feed(raw, since, today)
    val = rc.val_now
    for it in items:
        d = date.fromisoformat(it["date"])
        hint = it["team"]
        pl = []
        for p in it["players"]:
            pid = matcher.match(p["pos"], p["name"], d, hint)
            v = val.get(pid) if pid else None
            pl.append([pid, p["name"], p["pos"], v.get("value") if v else None])
        it["players"] = pl
    # trades
    sides = trade_sides(raw, since)
    for s in sides:
        d = date.fromisoformat(s["date"])
        for p in s["gets"]["players"]:
            p["pid"] = matcher.match(p["pos"], p["name"], d, s["counter"])
        for p in s["gives"]["players"]:
            p["pid"] = matcher.match(p["pos"], p["name"], d, s["team"])
    merged = merge_sides(sides)
    resolve_counters(merged, matcher)
    rated = []
    for t in merged:
        if t["teams"][1] is None and not ((t["gets"].get(t["teams"][0]) or {}).get("players") or (t["gets"].get(t["teams"][0]) or {}).get("picks")):
            continue
        try:
            rated.append(rate(t, rc))
        except Exception as exc:                                 # noqa: BLE001
            logger.info("rate %s: %s", t.get("texts"), exc)
    rated.sort(key=lambda r: r["date"], reverse=True)
    # winners and losers by club
    table: dict[str, dict] = {t: {"team": t, "trades": 0, "net_at": 0.0, "net_now": 0.0, "wins_at": 0.0, "wins_now": 0.0, "real": 0.0,
                                  "signed": 0.0, "lost": 0.0, "n_signed": 0, "n_lost": 0} for t in teams}
    for r in rated:
        for sd in r["sides"]:
            row = table.get(sd["team"])
            if row is None or sd["net_now"] is None:
                continue
            row["trades"] += 1
            row["net_at"] += sd["net_at"] or 0.0
            row["net_now"] += sd["net_now"] or 0.0
            row["wins_at"] += sd["wins_at"] or 0.0
            row["wins_now"] += sd["wins_now"] or 0.0
            row["real"] += sd["real"] or 0.0
    for it in items:
        row = table.get(it["team"])
        if row is None:
            continue
        for pid, nm, pos, v in it["players"]:
            if v is None or v <= 0:
                continue
            if it["type"] == "signing":
                row["signed"] += v
                row["n_signed"] += 1
            elif it["type"] == "release":
                row["lost"] += v
                row["n_lost"] += 1
    for row in table.values():
        for k in ("net_at", "net_now", "real", "signed", "lost"):
            row[k] = round(row[k], 1)
        for k in ("wins_at", "wins_now"):
            row[k] = round(row[k], 2)
    sides_all = [dict(sd, date=r["date"], other=[x for x in r["teams"] if x != sd["team"]][0] if len(r["teams"]) > 1 else None)
                 for r in rated for sd in r["sides"] if sd["wins_now"] is not None]
    best = sorted(sides_all, key=lambda s: -(s["wins_now"] or 0))[:10]
    worst = sorted(sides_all, key=lambda s: (s["wins_now"] or 0))[:10]
    counts = {}
    for it in items:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
    recent = [[it["date"], it["team"], it["type"], it["text"], it["players"]] for it in items
              if it["type"] in ("trade", "signing", "release", "claim", "extension")][:400]
    pub = {"ok": True, "season": season, "updated_at": an.now(), "version": VERSION, "window": [since.isoformat(), today.isoformat()],
           "k_resp": round(rc.k_resp, 4), "wins_per_point": round(rc.wpp, 5), "grades": [[c, g] for c, g in GRADES] + [[None, "F"]],
           "trades": rated, "table": sorted(table.values(), key=lambda r: -r["wins_now"]),
           "best": [[s["date"], s["team"], s["other"], s["wins_now"], s["grade_now"], s["wins_at"]] for s in best],
           "worst": [[s["date"], s["team"], s["other"], s["wins_now"], s["grade_now"], s["wins_at"]] for s in worst],
           "feed_cols": FEED_COLS, "feed": recent, "counts": counts, "n_feed": len(items),
           "pick_curve": {k: (rc.pick or {}).get(k) for k in ("ok", "rounds", "n", "drafts", "note")},
           "notes": {"source": CREDIT, "left_out": LEFT_OUT,
                     "method": "Value at the time: the player's projection from the seasons completed before the trade (rest of "
                               "that season and the next three, discounted 10% a season), picks from our draft-pick value curve. "
                               "Realised: his value above replacement per game times the games he has played for his new club "
                               "since. Now: realised plus what is still projected while he is on that roster. Picks keep their "
                               "curve value: our sources do not say which player a traded pick became.",
                     "parse": "Trades are parsed from the clubs' notes as ESPN publishes them; a note that names no player we "
                              "can match, or a club we cannot identify, is shown with what could be read."},
           "credits": [CREDIT, an.NFLVERSE_CREDIT]}
    ledgers = {}
    for tm in teams:
        mine = [[it["date"], it["type"], it["text"], it["players"]] for it in items if it["team"] == tm]
        tr = [r for r in rated if tm in r["teams"]]
        ledgers[tm] = {"ok": True, "season": season, "team": tm, "updated_at": an.now(), "window": pub["window"], "summary": table.get(tm),
                       "trades": tr, "feed_cols": ["date", "type", "text", "players"], "feed": mine, "credits": [CREDIT]}
    return {"transactions": pub, "ledgers": ledgers}


# ---------------------------------------------------------------------------------------------- inputs from disk

def week_dates(seasons: list[int]) -> tuple[dict[tuple, date], dict[tuple, list[date]], dict[str, date]]:
    """From the schedules: ({(season, week): first game date}, {(team, season): regular-season game dates},
    {game_id: date})."""
    from oddsmarkets.nfl.analytics.context import load_release
    df = load_release("schedules", None, ["game_id", "season", "week", "game_type", "gameday", "home_team", "away_team"])
    wk, td, gd = {}, {}, {}
    if df is None or not len(df):
        return wk, td, gd
    df = df[df["season"].isin(seasons)]
    for r in df.to_dict("records"):
        d = _date(r.get("gameday"))
        if d is None:
            continue
        s, w = an.inum(r.get("season")), an.inum(r.get("week"))
        gd[str(r.get("game_id"))] = d
        if (s, w) not in wk or d < wk[(s, w)]:
            wk[(s, w)] = d
        if r.get("game_type") == "REG":
            for t in (r.get("home_team"), r.get("away_team")):
                from oddsmarkets.nfl.analytics import teamsref
                td.setdefault((teamsref.canon_abbr(t, s), s), []).append(d)
    return wk, td, gd


def roster_history(seasons: list[int], wk: dict[tuple, date]) -> dict[str, list[tuple]]:
    """{pid: [(week date, team)]} from the weekly rosters (on-roster statuses only)."""
    from oddsmarkets.nfl.analytics import teamsref
    from oddsmarkets.nfl.analytics.context import load_release
    out: dict[str, list[tuple]] = {}
    for s in seasons:
        df = load_release("weekly_rosters", s, ["gsis_id", "team", "week", "status"])
        if df is None or not len(df):
            continue
        df = df[df["status"].isin(["ACT", "INA", "RES", "PUP", "DEV", "SUS", "EXE", "NON"])] if "status" in df else df
        for pid, t, w in zip(df["gsis_id"].astype(str), df["team"].astype(str), df["week"]):
            d = wk.get((s, an.inum(w)))
            if d is None or not pid or pid == "None":
                continue
            out.setdefault(pid, []).append((d, teamsref.canon_abbr(t, s)))
    return out


def games_log(seasons: list[int], gd: dict[str, date]) -> dict[str, list[tuple]]:
    """{pid: [(season, game date, team)]} from nflverse weekly player stats (a row = a game with a recorded stat)."""
    from oddsmarkets.nfl.analytics import teamsref
    from oddsmarkets.nfl.analytics.context import load_release
    out: dict[str, list[tuple]] = {}
    for s in seasons:
        df = load_release("stats_player", s, ["player_id", "team", "game_id", "season_type"])
        if df is None or not len(df):
            continue
        for pid, t, g in zip(df["player_id"].astype(str), df["team"].astype(str), df["game_id"].astype(str)):
            d = gd.get(g)
            if d is not None:
                out.setdefault(pid, []).append((s, d, teamsref.canon_abbr(t, s)))
    return out


def run(season: int, today: date, recs: dict[str, dict], valuation: dict | None, roster: dict[str, dict], k_resp: float,
        teams: list[str], fetch: bool = True, raw: list[dict] | None = None) -> dict:
    """Everything for the current season's transactions pages (see build)."""
    from oddsmarkets.nfl.analytics import people as PP
    from oddsmarkets.nfl.analytics import valuation as VA
    if raw is None:
        raw = []
        for y in (today.year - 1, today.year):
            raw += load_year(y, today, fetch=fetch)
    if not raw:
        return {"transactions": {"ok": False, "reason": "no transactions on disk and ESPN did not answer"}, "ledgers": {}}
    seasons = sorted({season - 1, season, trade_season(today - timedelta(days=WINDOW_DAYS))[0]})
    wk, td, gd = week_dates(seasons)
    ppl = PP.people()
    matcher = Matcher(ppl, roster_history(seasons, wk))
    rows = VA.panel_rows(season)
    rows_by = {(r["pid"], r["season"]): r for r in rows}
    curves = VA.fit_curves(rows)
    pick = (valuation or {}).get("pick_curve") or VA.pick_curve(rows, VA.draft_table(), season - 1)
    cols = (valuation or {}).get("cols") or []
    val_now = {}
    for r in (valuation or {}).get("rows") or []:
        o = dict(zip(cols, r))
        val_now[o["pid"]] = o
    cur = {p: {"gvar_pg": rc.get("gvar_pg"), "games": rc.get("games")} for p, rc in recs.items()}
    roster_now = {p: ro.get("team") for p, ro in (roster or {}).items() if ro.get("status") in ("ACT", "INA", "RES", "PUP", "SUS", "EXE")}
    rc = RateCtx(season, rows_by, curves, pick, cur, val_now, games_log(seasons, gd), td, roster_now, k_resp,
                 float((valuation or {}).get("wins_per_point") or VA.wins_per_point()), ppl, today)
    return build(season, today, raw, matcher, rc, teams)
