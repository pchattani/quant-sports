"""
Transactions as facts (docs/VALUE_SECTIONS.md section 4): the MLB Stats API transactions (cached by analytics/mlbapi.py)
parsed into the kind of move, the player, the clubs and its particulars; injured-list stints and days per season (the
availability inputs of analytics/valuation.py); trades grouped from their pieces.

Parsing. The Stats API types (`typeCode`) give the kind; the description gives the particulars, read by patterns and
never shown: the injured list's length (10, 15 or 60 days; "disabled list" before 2019; the 7-day list of 2020-21 for
concussions), the date a placement is retroactive to, the body part (a category from keywords: elbow, shoulder,
hamstring, ...), whether a free-agent contract is a minor-league one, and a trade's extras (cash, a player to be named
later, international bonus pool money, a draft pick, future considerations). A trade's pieces share one id: each
player moved is a record (from his old club to his new one); the cash and the player to be named are records without a
person.

Injured-list stints: a placement opens a stint (on its retroactive date when there is one), a transfer to the 60-day list
continues it, an activation from the list (or a release, an outright or a trade, which end the club's stint) closes it;
a stint still open at the end of the regular season is closed there. Days are counted inside each season's regular-season
dates (the store's first and last regular-season game).
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Iterable

KIND = {"TR": "trade", "SFA": "signing", "SGN": "signing", "CU": "recall", "SE": "selected", "OPT": "option", "OUT": "outright",
        "DES": "dfa", "REL": "release", "CLW": "claim", "DFA": "free_agency", "RET": "retired", "SU": "suspension",
        "CP": "purchase", "PUR": "purchase", "OBT": "purchase", "ACQ": "purchase", "RTN": "returned", "ASG": "assigned",
        "R5": "rule5", "R5M": "rule5", "DR": "draft", "LON": "loan"}
LABEL = {"trade": "Trade", "signing": "Signing", "signing_minor": "Minor-league signing", "recall": "Recalled", "selected": "Contract selected",
         "option": "Optioned", "outright": "Outrighted", "dfa": "Designated for assignment", "release": "Released",
         "claim": "Waiver claim", "free_agency": "Elected free agency", "retired": "Retired", "suspension": "Suspended",
         "purchase": "Purchased", "returned": "Returned", "assigned": "Assigned", "rehab": "Rehab assignment", "rule5": "Rule 5",
         "draft": "Drafted", "loan": "Loaned", "il_place": "Placed on the injured list", "il_transfer": "Moved to the 60-day injured list",
         "il_activate": "Activated from the injured list", "activated": "Activated", "list_place": "Placed on a list",
         "list_activate": "Activated from a list", "status": "Roster status changed", "reassigned": "Reassigned to the minors"}
# the moves the public feed lists (minor-league signings, assignments and number changes are left out)
FEED_KINDS = ("trade", "signing", "recall", "selected", "option", "outright", "dfa", "release", "claim", "free_agency", "retired",
              "suspension", "purchase", "rule5", "il_place", "il_transfer", "il_activate", "rehab")

_IL = re.compile(r"(placed|activated|transferred|reinstated)\b.*?\b(?:from|on|to) the (\d+)[- ]day (?:injured|disabled) list"
                 r"(?:.*?to the (\d+)[- ]day (?:injured|disabled) list)?", re.I)
_RETRO = re.compile(r"retroactive to ([A-Za-z]+ \d{1,2}, \d{4})", re.I)
_LIST = re.compile(r"\b(placed|activated)\b.*\b(paternity|bereavement|restricted|reserve|family medical emergency|suspended) list", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september",
                                          "october", "november", "december"))}
PARTS = (("elbow", ("elbow", "tommy john", "ucl", "ulnar", "flexor", "forearm", "pronator")), ("shoulder", ("shoulder", "rotator", "labrum", "capsule")),
         ("lat", (" lat ", " lat.", "latissimus", "teres")), ("hamstring", ("hamstring",)), ("oblique", ("oblique", "intercostal", "abdominal", "side ")),
         ("back", ("back", "lumbar", "spine", "disc", "neck", "cervical", "thoracic")), ("knee", ("knee", "acl", "meniscus", "patell")),
         ("ankle", ("ankle", "achilles")), ("foot", ("foot", "toe", "plantar", "heel")), ("hand", ("hand", "wrist", "finger", "thumb", "hamate", "blister", "nail")),
         ("hip", ("hip", "groin", "adductor", "glute", "pelvi")), ("calf", ("calf", "shin", "fibula", "tibia")), ("quad", ("quad",)),
         ("head", ("concussion", "head", "face", "jaw", "eye", "orbital", "nose")), ("ribs", ("rib", "chest", "pectoral", "sternum")),
         ("arm", ("biceps", "triceps", "arm", "humer")), ("illness", ("illness", "covid", "virus", "infection", "flu", "appendic")))
EXTRAS = (("cash", ("cash",)), ("ptbnl", ("player to be named",)), ("intl", ("international", "bonus pool", "pool money")),
          ("pick", ("draft pick", "competitive balance")), ("future", ("future considerations",)))


def _d(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _long_date(s: str) -> date | None:
    try:
        m, rest = s.split(" ", 1)
        d, y = rest.replace(",", "").split()
        return date(int(y), MONTHS[m.lower()], int(d))
    except (ValueError, KeyError):
        return None


def body_part(text: str | None) -> str | None:
    t = " " + (text or "").lower() + " "
    if not t.strip():
        return None
    for part, keys in PARTS:
        if any(k in t for k in keys):
            return part
    return "other"


def parse(r: dict) -> dict:
    """One cached transaction (statsapi.compact_tx) as facts: {id, date, kind, pid, name, from, to} plus, by kind,
    il (list length), il_to (after a transfer), start (a placement's retroactive date), part (body part), minor (a
    minor-league contract), extras (a trade's cash, player to be named, ...)."""
    code = r.get("c")
    x = r.get("x") or ""
    xl = x.lower()
    kind = KIND.get(code, "other")
    out = {"id": r.get("id"), "date": r.get("d"), "kind": kind, "pid": r.get("p"), "name": r.get("pn"), "from": r.get("f"), "to": r.get("t")}
    if code == "SC":
        m = _IL.search(x)
        if m:
            verb = m.group(1).lower()
            out["il"] = int(m.group(2))
            if verb == "placed":
                out["kind"] = "il_place"
                rm = _RETRO.search(x)
                st = _long_date(rm.group(1)) if rm else None
                out["start"] = st.isoformat() if st else r.get("d")
                tail = re.split(r"list(?: retroactive to [A-Za-z]+ \d{1,2}, \d{4})?\.\s*", x, maxsplit=1)
                out["part"] = body_part(tail[1] if len(tail) > 1 else None)
            elif verb == "transferred":
                out["kind"] = "il_transfer"
                out["il_to"] = int(m.group(3)) if m.group(3) else 60
            else:
                out["kind"] = "il_activate"
            out["club"] = r.get("t") or r.get("f")
        elif _LIST.search(x):
            out["kind"] = "list_place" if _LIST.search(x).group(1).lower() == "placed" else "list_activate"
        elif "reassigned" in xl:
            out["kind"] = "reassigned"
        elif " activated " in f" {xl} ":
            out["kind"] = "activated"
        else:
            out["kind"] = "status"
    elif code == "ASG" and "rehab assignment" in xl:
        out["kind"] = "rehab"
    elif kind == "signing":
        out["minor"] = "minor league contract" in xl or "minor-league contract" in xl
        if out["minor"]:
            out["kind"] = "signing_minor"
    elif kind == "trade" and r.get("p"):
        out["oneway"] = " for " not in xl
    elif kind == "trade" and not r.get("p"):
        # "A traded X [and cash] to B for Y [and a player to be named later]": what precedes " for " goes to B, what
        # follows it to A; a record without a person is the extra its receiving club got
        first, _, second = xl.partition(" for ")
        subj_is_to = bool(r.get("tn")) and x.startswith(str(r.get("tn")))
        part = second if subj_is_to else first
        ex = [k for k, keys in EXTRAS if any(w in part for w in keys)]
        out["extras"] = ex or ["cash"]
    return out


def parse_all(rows: Iterable[dict]) -> list[dict]:
    return [parse(r) for r in rows]


# ── injured-list stints ─────────────────────────────────────────────────────

def season_bounds(stores: dict[int, dict]) -> dict[int, tuple[date, date]]:
    """{season: (first, last regular-season game date)} from the stores; defaults when a store has no games."""
    out = {}
    for s, st in stores.items():
        ds = sorted(str(g.get("date"))[:10] for g in ((st or {}).get("games") or {}).values() if g.get("gtype") == "R" and g.get("date"))
        out[s] = (_d(ds[0]), _d(ds[-1])) if ds else (date(s, 3, 28), date(s, 9, 30))
    return out


ENDERS = ("release", "outright", "free_agency", "retired", "il_activate", "activated")


def il_stints(parsed: list[dict], today: date | None = None) -> dict[str, list[dict]]:
    """{pid: [{start, end (None while open), il (the list's days), part, club}]}, oldest first."""
    by: dict[str, list[dict]] = defaultdict(list)
    for t in sorted(parsed, key=lambda t: (t.get("date") or "", t.get("id") or 0)):
        if t.get("pid"):
            by[t["pid"]].append(t)
    out: dict[str, list[dict]] = {}
    for pid, ts in by.items():
        st: list[dict] = []
        cur = None
        for t in ts:
            k = t["kind"]
            if k == "il_place":
                if cur is not None and abs(((_d(t["date"]) or date.min) - (_d(cur.get("placed") or cur["start"]) or date.min)).days) <= 3:
                    cur["il"] = t.get("il") or cur["il"]          # the same placement recorded twice (or corrected)
                    cur["part"] = cur.get("part") or t.get("part")
                    continue
                if cur is not None:                       # a placement while one is open (a missed activation): close it
                    cur["end"] = min(t.get("start") or t["date"], t["date"])
                    st.append(cur)
                cur = {"start": t.get("start") or t["date"], "end": None, "il": t.get("il"), "part": t.get("part"), "club": t.get("club") or t.get("to"),
                       "placed": t["date"]}
            elif k == "il_transfer" and cur is not None:
                cur["il"] = t.get("il_to") or cur["il"]
            elif cur is not None and (k in ENDERS or k == "trade"):
                cur["end"] = t["date"]
                st.append(cur)
                cur = None
        if cur is not None:
            st.append(cur)
        if st:
            out[pid] = st
    return out


def il_days(stints: dict[str, list[dict]], bounds: dict[int, tuple[date, date]], today: date | None = None) -> dict[str, dict[int, dict]]:
    """{pid: {season: {"days", "stints", "parts": [..]}}}: days on the injured list inside each season's regular season
    (an open stint runs to the season's end, or to `today` for the season under way)."""
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    for pid, sts in stints.items():
        for x in sts:
            a = _d(x["start"])
            b = _d(x["end"]) if x.get("end") else None
            if a is None:
                continue
            for s, (lo, hi) in bounds.items():
                end_cap = min(hi, today) if today and lo <= today <= hi else hi
                bb = b if b is not None else end_cap
                lo2, hi2 = max(a, lo), min(bb, end_cap)
                if hi2 < lo2:
                    continue
                cell = out[pid].setdefault(s, {"days": 0, "stints": 0, "parts": []})
                cell["days"] += (hi2 - lo2).days + 1
                cell["stints"] += 1
                if x.get("part") and x["part"] not in cell["parts"]:
                    cell["parts"].append(x["part"])
    return out


STALE_DAYS = 400   # an open stint older than this lost its activation (a death, a retirement, an unrecorded release)


def on_il(stints: dict[str, list[dict]], when: date) -> dict[str, dict]:
    """Players on the injured list on `when`: {pid: stint}. A placement never followed by an activation, release or trade
    is open for at most STALE_DAYS (no stint outlives a season and its winter: the 60-day list empties after the World
    Series), so a 2015 placement with no recorded end is not "on the list" in 2026 (round 9)."""
    out = {}
    for pid, sts in stints.items():
        for x in sts:
            a, b = _d(x["start"]), _d(x["end"]) if x.get("end") else None
            if a and b is None and (when - a).days > STALE_DAYS:
                continue
            if a and a <= when and (b is None or b >= when):
                out[pid] = x
    return out


# ── trades ──────────────────────────────────────────────────────────────────

def trades(parsed: list[dict]) -> list[dict]:
    """Trades grouped by id: {id, date, teams [club ids], pieces [{pid, name, from, to}], extras {receiving club: [..]}}.
    Records whose clubs are not both known are dropped; a trade whose every piece is cash or a player to be named still
    lists its clubs."""
    by: dict[Any, list[dict]] = defaultdict(list)
    for t in parsed:
        if t["kind"] == "trade" and t.get("id") is not None:
            by[t["id"]].append(t)
    out = []
    for tid, recs in by.items():
        teams: list[str] = []
        pieces, extras = [], defaultdict(list)
        for r in recs:
            for c in (r.get("from"), r.get("to")):
                if c and c not in teams:
                    teams.append(c)
            if r.get("pid") and r.get("from") and r.get("to"):
                if not any(p["pid"] == r["pid"] for p in pieces):
                    pieces.append({"pid": r["pid"], "name": r.get("name"), "from": r["from"], "to": r["to"]})
            elif r.get("to"):
                for e in r.get("extras") or ["cash"]:
                    if e not in extras[r["to"]]:
                        extras[r["to"]].append(e)
        if len(teams) < 2:
            continue
        out.append({"id": tid, "date": min(r["date"] for r in recs if r.get("date")), "teams": teams, "pieces": pieces,
                    "extras": {k: v for k, v in extras.items()}, "oneway": all(r.get("oneway") for r in recs if r.get("pid")) and not extras})
    out.sort(key=lambda t: (t["date"], t["id"]))
    return merge_oneway(out)


def merge_oneway(trades: list[dict], gap: int = 6) -> list[dict]:
    """A deal among three clubs is sometimes recorded as one-way trades on the same date with neighbouring ids (A to B, B
    to C, C to A), and a two-club deal now and then as two one-way trades: merge one-way trades of a date whose ids are
    within `gap` of each other when, together, every club both sends and receives."""
    out, used = [], set()
    by_date: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(trades):
        if t.get("oneway"):
            by_date[t["date"]].append(i)
    groups: dict[int, list[int]] = {}
    for d, idx in by_date.items():
        idx.sort(key=lambda i: trades[i]["id"])
        cluster: list[int] = []
        clusters = []
        for i in idx:
            if cluster and int(trades[i]["id"]) - int(trades[cluster[-1]]["id"]) > gap:
                clusters.append(cluster)
                cluster = []
            cluster.append(i)
        if cluster:
            clusters.append(cluster)
        for cl in clusters:
            if len(cl) < 2:
                continue
            send, recv = set(), set()
            for i in cl:
                for pc in trades[i]["pieces"]:
                    send.add(pc["from"])
                    recv.add(pc["to"])
            if send == recv and len(send) >= 2:
                groups[cl[0]] = cl
                used.update(cl)
    for i, t in enumerate(trades):
        if i in groups:
            cl = groups[i]
            teams: list[str] = []
            pieces = []
            for j in cl:
                for c in trades[j]["teams"]:
                    if c not in teams:
                        teams.append(c)
                pieces.extend(trades[j]["pieces"])
            out.append({"id": t["id"], "date": t["date"], "teams": teams, "pieces": pieces, "extras": {}, "oneway": False,
                        "merged": [trades[j]["id"] for j in cl]})
        elif i not in used:
            out.append(t)
    return out


# ── the feed ────────────────────────────────────────────────────────────────

def feed_rows(parsed: list[dict], lo: str, hi: str, mlb_teams: set[str]) -> list[list]:
    """[[date, kind, pid, name, from, to, detail]] for the public feed: the moves in FEED_KINDS between lo and hi that
    involve an MLB club; detail is our own short text (the list's length, the body part, a minor-league contract)."""
    out = []
    for t in parsed:
        d = t.get("date") or ""
        k = t["kind"]
        if not (lo <= d <= hi) or k not in FEED_KINDS:
            continue
        if not ((t.get("from") in mlb_teams) or (t.get("to") in mlb_teams)):
            continue
        if k == "trade" and not t.get("pid"):
            continue                                     # trades are listed per player; the trades table has the rest
        det = ""
        if k == "il_place":
            det = f"{t.get('il')}-day" + (f" · {t['part']}" if t.get("part") and t["part"] != "other" else "") + \
                  (f" · from {t['start']}" if t.get("start") and t["start"] != d else "")
        elif k == "il_transfer":
            det = f"to the {t.get('il_to') or 60}-day"
        elif k == "il_activate":
            det = f"from the {t.get('il')}-day"
        out.append([d, k, t.get("pid"), t.get("name"), t.get("from"), t.get("to"), det])
    out.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return out


def ledger_counts(rows: list[list], mlb_teams: Iterable[str]) -> dict[str, dict]:
    """{tid: {kind: count}} from feed rows (a move counts for the club it involves: both clubs for a trade)."""
    out: dict[str, dict] = {t: defaultdict(int) for t in mlb_teams}
    for d, k, pid, name, f, to, det in rows:
        for c in {f, to}:
            if c in out:
                kk = k
                if k == "trade":
                    kk = "trade_in" if c == to else "trade_out"
                out[c][kk] += 1
    return {t: dict(v) for t, v in out.items()}
