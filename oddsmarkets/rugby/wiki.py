"""
Wikipedia rows for The Quant Scrum: test results ESPN does not carry (every test before 1987, the small nations'
tests before about 2015, the Rugby Europe, Pacific, Americas, Asia and Africa competitions, the women's Six Nations
and WXV), and the referee and attendance of the tests it does carry. Source pages and terms:
`sources/wikipedia.py`; crawl: `scripts/scrum_wiki.py`.

    build_store()   parse every cached page into data/rugby/stores/wiki/<scope>.json.gz (private, never published):
                    {"rows": [{wid, date, time_utc, home, away, hs, as, venue, attendance, referee, comp, event, page,
                    scope}], "squads": {...}, "most_caps": {...}, "report": {...}}
    merge(scope, espn_matches)  -> (matches, report): ESPN rows enriched with the referee and attendance, plus the
                    Wikipedia-only tests as match rows in the store's shape (id "w<hash>", source "wikipedia")

A Wikipedia row matches an ESPN row when the two sides agree and the dates are within a day (local against UTC);
the score must agree too, or the row is reported as a conflict and ESPN's is kept. Only full tests go in: the
{{ruA}} template (an "A" side), "XV" names, invitational and club sides are dropped. SOURCE_WIKIPEDIA_RUGBY_ENABLED=0
makes merge() return ESPN's rows untouched.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import nations, store
from .sources import wiki_html as H

log = logging.getLogger(__name__)

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
# flag-template codes Wikipedia uses that differ from ours, and historic sides
EXTRA_CODES = {"JAP": "Japan", "TON": "Tonga", "FJI": "Fiji", "WSM": "Samoa", "SAF": "South Africa", "SA": "South Africa",
               "NZ": "New Zealand", "LVA": "Latvia", "SVN": "Slovenia", "BAR": "Barbados", "BRB": "Barbados",
               "GBR": None, "URS": "Soviet Union", "TCH": "Czechoslovakia", "FRG": "Germany", "GDR": "East Germany",
               "YUG": "Yugoslavia", "RHO": "Zimbabwe", "ZAI": None, "NIR": None, "IRL": "Ireland", "ROM": "Romania",
               "SUD": None, "TAI": "Chinese Taipei", "ROC": "Chinese Taipei", "HK": "Hong Kong", "KSA": None,
               "SAM": "Samoa", "RSA": "South Africa", "ARA": "Arabian Gulf", "AGU": "Arabian Gulf", "SWI": "Switzerland",
               "DEN": "Denmark", "SCG": "Serbia", "MON": None, "GUA": None, "PAN": None, "ESA": None, "HON": None,
               "SRI": "Sri Lanka", "NGA": "Nigeria", "UGA": "Uganda", "IVO": "Cote d'Ivoire", "CIV": "Cote d'Ivoire"}
EXTRA_SIDES = {"Soviet Union": ("URS", 55.75, 37.62, 3, 3), "Czechoslovakia": ("TCH", 50.08, 14.44, 1, 3),
               "East Germany": ("GDR", 52.52, 13.40, 1, 3), "Yugoslavia": ("YUG", 44.79, 20.45, 1, 3)}
for _k, _v in EXTRA_SIDES.items():
    nations.NATIONS.setdefault(_k, _v)
    nations._NAME_FOLD.setdefault(nations._FOLD.sub("", _k.lower()), _k)
CODE_TO_NAME: dict[str, str] = {}
for _n, _r in nations.NATIONS.items():
    CODE_TO_NAME.setdefault(_r[0], nations.ALIAS.get(_n, _n))
RESULT_ONLY_BEFORE = "1891-01-01"
NOT_TEST = re.compile(r"(?i)\bXV\b|\bA\b|barbarian|select|invitation|president|development|emerging|students|"
                      r"universit|under[- ]?\d|u\d\d|\bclub\b|province|county|districts?\b|army|navy|services|"
                      r"\bB\b|colts|juniors?|academy|sevens|\b7s\b")


def enabled() -> bool:
    from .sources import wikipedia as W
    return W.enabled()


# ── page parsing ────────────────────────────────────────────────────────────────────────────────────────────

def side(raw: str, women: bool) -> str | None:
    """A rugbybox team cell (wiki text) -> the nation's canonical name, or None for an A side, an XV, a club or an
    invitational side the rankings ignore."""
    s = str(raw or "")
    if re.search(r"(?i)\{\{\s*ru\s*a\b|\{\{\s*rua", s):
        return None
    m = re.search(r"(?i)name\s*=\s*([^|}]+)", s)
    if m and NOT_TEST.search(m.group(1)):
        return None
    cand = []
    for t in re.finditer(r"\{\{\s*(?:ru|ru-rt|rut|rufu|flagicon|flagteam|ru-?w|ruw|ruw-rt)\s*\|\s*([^|}]+)", s, flags=re.I):
        cand.append(t.group(1).strip())
    txt = H.strip_wt(re.sub(r"\{\{[^{}]*\}\}", "", s)).replace("(1 BP)", "").replace("(2 BP)", "")
    txt = re.sub(r"\(\s*\d\s*BP\s*\)|\(BP\)", "", txt).strip(" |")
    if txt:
        if NOT_TEST.search(txt):
            return None
        # a name next to a flag decides: "{{flagicon|NZL}} [[Chiefs (rugby union)|Chiefs]]" is a club, not New Zealand
        cand = [txt]
    for c in cand:
        c = re.sub(r"(?i)\s+women'?s?$", "", c).strip()
        if c.upper() in EXTRA_CODES:
            n = EXTRA_CODES[c.upper()]
            if n is None:
                return None
            return n
        if c.upper() in CODE_TO_NAME and len(c) <= 3:
            return CODE_TO_NAME[c.upper()]
        r = nations.lookup(c)
        if r:
            return nations.canonical(r["name"])
        if c == txt:
            return None
    return None


def parse_date(s: str) -> str | None:
    s = H.norm(s or "")
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    m2 = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", s)
    if m:
        y, mo, d = map(int, m.groups())
    elif m2:
        d, mo, y = map(int, m2.groups())                      # the England lists write dd/mm/yyyy
    else:
        m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})", s)
        if m and m.group(2).lower()[:3] in {k[:3] for k in MONTHS}:
            d, mo, y = int(m.group(1)), next(v for k, v in MONTHS.items() if k[:3] == m.group(2).lower()[:3]), int(m.group(3))
        else:
            m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
            if not m or m.group(1).lower()[:3] not in {k[:3] for k in MONTHS}:
                return None
            mo, d, y = next(v for k, v in MONTHS.items() if k[:3] == m.group(1).lower()[:3]), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse_time_utc(day: str, s: str) -> str | None:
    """'21:00 CET (UTC+1)' on 2019-02-01 -> '2019-02-01T20:00'; None without both a clock time and a UTC offset."""
    s = H.norm(s or "")
    m = re.search(r"(\d{1,2})[:.](\d{2})", s)
    o = re.search(r"UTC\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", s)
    if not m or not o:
        return None
    try:
        t = datetime.fromisoformat(day) + timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
    except ValueError:
        return None
    off = (int(o.group(2)) + int(o.group(3) or 0) / 60) * (1 if o.group(1) == "+" else -1)
    return (t - timedelta(hours=off)).strftime("%Y-%m-%dT%H:%M")


def parse_score(s: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{1,3})\s*[-–:]\s*(\d{1,3})", H.norm(s or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_referee(s: str) -> dict | None:
    s = H.norm(s or "").split(" | ")[0]
    s = re.sub(r"(?i)^referee:?\s*", "", s).strip()
    if not s or len(s) < 4:
        return None
    m = re.match(r"(.+?)\s*\(([^)]+)\)", s)
    name, union = (m.group(1), m.group(2)) if m else (s, "")
    name = re.sub(r"\s+", " ", name).strip(" ,;")
    if not re.search(r"[A-Za-z]", name) or len(name) > 40:
        return None
    u = nations.lookup(union) if union else None
    union = (nations.canonical(u["name"]) if u else CODE_TO_NAME.get(union.upper(), union)) if union else ""
    return {"name": name, "union": union}


def classify(title: str) -> tuple[str, str]:
    """(comp key, scope) from the page title."""
    t = title.lower()
    women = "women" in t or "wxv" in t or "pacific four" in t
    if "six nations" in t or "five nations" in t or "home nations" in t:
        key = "w6n" if women else "six"
    elif "tri nations" in t or "rugby championship" in t and "americas" not in t and "asia" not in t:
        key = "trc"
    elif "rugby world cup" in t and "qualif" not in t and "warm-up" not in t:
        key = "wrwc" if women else "rwc"
    elif "wxv" in t:
        key = "wxv"
    else:
        key = "test"
    return key, ("women" if women else "men")


def event_name(title: str) -> str:
    t = re.sub(r"^\d{4}(?:[–-]\d{2,4})?\s+", "", title)
    t = re.sub(r"\s+\d{4}(?:[–-]\d{2,4})?$", "", t)
    return t.strip()


def rows_from_boxes(html: str, title: str) -> list[dict]:
    key, scope = classify(title)
    out = []
    for b in H.rugbyboxes(html):
        raw = b.get("_raw") or {}
        women = scope == "women"
        h = side(raw.get("home") or raw.get("team1") or "", women)
        a = side(raw.get("away") or raw.get("team2") or "", women)
        if not h or not a or h == a:
            continue
        d = parse_date(b.get("date") or "")
        sc = parse_score(b.get("score") or "") if b.get("score") else None
        if sc is None and b.get("homescore") and b.get("awayscore"):
            try:
                sc = (int(re.sub(r"\D", "", b["homescore"])), int(re.sub(r"\D", "", b["awayscore"])))
            except ValueError:
                sc = None
        if not d:
            continue
        if sc is None:
            ref = parse_referee(b.get("referee") or "")
            if ref and d >= (date.today() - timedelta(days=2)).isoformat():
                out.append({"date": d, "home": h, "away": a, "hs": None, "as": None, "venue": {}, "attendance": None,
                            "referee": ref, "comp": key, "event": event_name(title), "page": title, "scope": scope,
                            "kind": "box", "pre": 1})
            continue
        stad = H.norm(b.get("stadium") or "").split(" | ")[0]
        parts = [p.strip() for p in stad.split(",") if p.strip()]
        venue = {"name": parts[0] if len(parts) > 1 else "", "city": parts[1] if len(parts) > 1 else (parts[0] if parts else ""),
                 "country": parts[2] if len(parts) > 2 else ""}
        att = re.sub(r"[^\d]", "", (b.get("attendance") or b.get("Attendance") or "").split(" | ")[0].split("(")[0])
        row = {"date": d, "home": h, "away": a, "hs": sc[0], "as": sc[1], "venue": venue,
               "attendance": int(att) if att and 0 < int(att) < 200000 else None,
               "referee": parse_referee(b.get("referee") or ""), "comp": key, "event": event_name(title),
               "page": title, "scope": scope, "kind": "box"}
        tu = parse_time_utc(d, b.get("time") or "")
        if tu:
            row["time_utc"] = tu
        out.append(row)
    return out


# National results lists (tables): "List of New Zealand rugby union test matches" and the like. A table qualifies
# when its header row has a date, an opponent and a score (or points for and against).
LIST_SELF = {"List of England national rugby union team": "England", "List of Argentina": "Argentina",
             "List of Australia": "Australia", "List of Germany": "Germany", "List of Japan": "Japan",
             "List of New Zealand": "New Zealand", "List of South Africa": "South Africa"}
# lists whose single score column reads our side first (Germany's "result"); the others are used only with separate
# points-for and points-against columns (Canada's and Belgium's score columns have no fixed order, so they are not used)
ME_FIRST = {"Germany"}


def _hdr(g: list[list[dict]]) -> tuple[int, list[str]] | None:
    for i, row in enumerate(g[:3]):
        hs = [H.text(c).lower() for c in row]
        if any("date" in h for h in hs) and any(h in ("opponent", "opponents", "opposition", "versus", "vs", "team", "opponent team")
                                                 or "oppos" in h or "opponent" in h for h in hs):
            return i, hs
    return None


def rows_from_tables(html: str, title: str) -> list[dict]:
    me = next((v for k, v in LIST_SELF.items() if title.startswith(k)), None)
    if not me:
        return []
    out = []
    p = H.read(html)
    for t in p.tables:
        if "wikitable" not in t["cls"] or t["nested"]:
            continue
        g = H.grid(t)
        hh = _hdr(g)
        if not hh:
            continue
        hi, hs = hh
        col = lambda *names: next((j for j, h in enumerate(hs) if any(h == n or h.startswith(n) for n in names)), None)
        cd, co = col("date"), col("opponent", "opposition", "opposing", "versus", "vs", "team")
        cs = col("score", "result", "f-a", "scores")
        cf, ca = col("f", "pf", "for", "points for"), col("a", "pa", "against", "points against")
        cv = col("venue", "ground", "location", "stadium")
        cy = col("city")
        cha = col("h/a", "home/away", "home or away", "h / a")
        cc = col("competition", "tournament", "event", "match type", "type")
        if cf is not None and ca is not None:
            cs = None
        elif me not in ME_FIRST:
            continue
        if cd is None or co is None or (cs is None and (cf is None or ca is None)):
            continue
        for row in g[hi + 1:]:
            if len(row) <= max(x for x in (cd, co, cs, cf, ca) if x is not None):
                continue
            d = parse_date(H.text(row[cd]))
            if not d:
                continue
            opp_cell = row[co]
            opp = None
            for tl in H.wiki_titles(opp_cell):
                if "national" in tl.lower() or "rugby union team" in tl.lower():
                    if NOT_TEST.search(re.sub(r"(?i)national rugby union team|rugby union team", "", tl)):
                        opp = None
                        break
                    r = nations.lookup(re.sub(r"(?i)\s*national rugby union team.*$|\s*rugby union team.*$", "", tl))
                    if r:
                        opp = nations.canonical(r["name"])
                        break
            if opp is None:
                txt = H.text(opp_cell)
                if NOT_TEST.search(txt):
                    continue
                r = nations.lookup(txt.split(" | ")[0].strip())
                opp = nations.canonical(r["name"]) if r else None
            if not opp or opp == me or nations.invitational(opp):
                continue
            if cs is not None:
                sc = parse_score(H.text(row[cs]))
            else:
                try:
                    sc = (int(re.sub(r"\D", "", H.text(row[cf]))), int(re.sub(r"\D", "", H.text(row[ca]))))
                except ValueError:
                    sc = None
            if sc is None:
                continue
            venue_txt = H.text(row[cv]) if cv is not None and cv < len(row) else ""
            if cy is not None and cy < len(row) and H.text(row[cy]):
                venue_txt = (venue_txt + ", " + H.text(row[cy])).strip(", ")
            ha = H.text(row[cha]).strip().upper()[:1] if cha is not None and cha < len(row) else ""
            # the list's own side first in the score; home and away from an H/A column or the venue
            home_is_me = None
            if ha in ("H", "A", "N"):
                home_is_me = {"H": True, "A": False, "N": True}[ha]
            neutral = ha == "N"
            if home_is_me is None:
                home_is_me = _venue_side(venue_txt, me, opp)
                neutral = None if home_is_me is None else False
                home_is_me = True if home_is_me is None else home_is_me
            hs_, as_ = (sc[0], sc[1]) if home_is_me else (sc[1], sc[0])
            parts = [x.strip() for x in venue_txt.split(",") if x.strip()]
            out.append({"date": d, "home": me if home_is_me else opp, "away": opp if home_is_me else me, "hs": hs_, "as": as_,
                        "venue": {"name": parts[0] if len(parts) > 1 else "", "city": parts[1] if len(parts) > 1 else (parts[0] if parts else ""),
                                  "country": parts[2] if len(parts) > 2 else ""},
                        "neutral": neutral, "attendance": None, "referee": None,
                        "comp": _list_comp(H.text(row[cc]) if cc is not None and cc < len(row) else ""),
                        "event": H.text(row[cc]) if cc is not None and cc < len(row) else "", "page": title,
                        "scope": "men", "kind": "table"})
    return out


def _list_comp(s: str) -> str:
    t = (s or "").lower()
    if "world cup" in t and "qualif" not in t:
        return "rwc"
    if "six nations" in t or "five nations" in t or "home nations" in t:
        return "six"
    if "tri nations" in t or "rugby championship" in t:
        return "trc"
    return "test"


_CITY_NATION: dict[str, str] = {}


def _venue_side(venue: str, me: str, opp: str) -> bool | None:
    """True when the venue is in our side's country, False in the opponent's, None when unknown (taken as neutral)."""
    if not _CITY_NATION:
        for cty, (la, lo, tz) in nations.CITIES.items():
            best = min(((nations.km((r[1], r[2]), (la, lo)), n) for n, r in nations.NATIONS.items()
                        if r[0] not in nations.INVITATIONAL), default=(None, None))
            if best[0] is not None and best[0] < 1200:
                _CITY_NATION[cty.lower()] = nations.canonical(best[1])
    v = (venue or "").lower()
    for nm, flag in ((me, True), (opp, False)):
        if nm.lower() in v:
            return flag
    for cty, n in _CITY_NATION.items():
        if cty in v:
            if n == me:
                return True
            if n == opp:
                return False
    return None


def _vkeys(v: dict) -> list[str]:
    out = []
    for k in ("city", "name"):
        x = re.sub(r"\(.*?\)", "", str((v or {}).get(k) or "")).strip().lower()
        if x:
            out.append(x)
    return out


def fix_sides(rows: list[dict]) -> dict:
    """Home, away and neutral from the venue. Each ground and city is given the nation that is listed at home there
    in the home-and-away rugbyboxes (a majority of at least three in four, two or more matches), else the nearest
    nation to a city in our table. Then: a row played in its away side's country is turned round; a row played in a
    third country is neutral; a table row whose venue is unknown is neutral (the lists do not say who was at home)."""
    votes: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["kind"] != "box" or r["comp"] in ("rwc", "wrwc", "wxv") or re.search(r"(?i)qualif|repechage|tournament|cup", r.get("event") or ""):
            continue
        for k in _vkeys(r.get("venue")):
            votes[k][nations.base_name(r["home"])] += 1
    where: dict[str, str] = {}
    for k, c in votes.items():
        n, top = c.most_common(1)[0]
        if top >= 2 and top >= 0.75 * sum(c.values()):
            where[k] = n
    if not _CITY_NATION:
        _venue_side("", "", "")
    for k, n in _CITY_NATION.items():
        where.setdefault(k, nations.base_name(n))
    st = Counter()
    for r in rows:
        vn = next((where[k] for k in _vkeys(r.get("venue")) if k in where), None)
        h, a = nations.base_name(r["home"]), nations.base_name(r["away"])
        if vn == a and r.get("neutral") is not True:
            r["home"], r["away"], r["hs"], r["as"] = r["away"], r["home"], r["as"], r["hs"]
            r["neutral"] = False
            st["turned"] += 1
        elif vn == h:
            r["neutral"] = False
        elif vn:
            r["neutral"] = True
            st["neutral"] += 1
        elif r["kind"] == "table":
            r["neutral"] = True
            st["unknown_neutral"] += 1
        else:
            r["neutral"] = bool(r.get("neutral"))
    st["grounds"] = len(where)
    return dict(st)


# ── squads and caps (national-team articles) ─────────────────────────────────────────────────────────────────

def squad_tables(html: str) -> dict:
    """{"current": [{name, caps, dob, pos}], "most_caps": [{name, caps, years}]} from a national team's article:
    the current-squad table (a 'Caps' column) and the all-time 'most caps' table."""
    p = H.read(html)
    cur, most = [], []
    for t in p.tables:
        if t["nested"] and "wikitable" not in t["cls"]:
            continue
        g = H.grid(t)
        if len(g) < 2:
            continue
        hs = [H.text(c).lower() for c in g[0]]
        if "caps" not in " ".join(hs):
            continue
        ci = next((j for j, h in enumerate(hs) if h.startswith("caps")), None)
        ni = next((j for j, h in enumerate(hs) if h in ("player", "name", "players")), None)
        if ci is None or ni is None:
            continue
        head = " ".join(t["heads"]).lower() + " " + t["caption"].lower()
        di = next((j for j, h in enumerate(hs) if "date of birth" in h or h.startswith("dob") or "age" == h), None)
        pi = next((j for j, h in enumerate(hs) if h.startswith("pos")), None)
        yi = next((j for j, h in enumerate(hs) if "career" in h or "span" in h or "years" in h), None)
        rows = []
        for row in g[1:]:
            if len(row) <= max(ci, ni):
                continue
            name = H.text(row[ni]).split(" | ")[0]
            name = re.sub(r"\(.*?\)|\*|†|\bc\b$", "", name).strip(" *")
            caps = re.sub(r"[^\d]", "", H.text(row[ci]))
            if not name or not caps or len(name) > 40:
                continue
            r = {"name": name, "caps": int(caps)}
            if di is not None and di < len(row):
                d = parse_date(H.text(row[di]))
                if d:
                    r["dob"] = d
            if pi is not None and pi < len(row):
                r["pos"] = H.text(row[pi])
            if yi is not None and yi < len(row):
                r["years"] = H.text(row[yi])
            rows.append(r)
        if not rows:
            continue
        if "most" in head or "record" in head or "capped" in head:
            most += rows
        elif "squad" in head or "current" in head or "recent call" in head or di is not None:
            cur += rows
    return {"current": cur, "most_caps": most}


# ── the store ─────────────────────────────────────────────────────────────────────────────────────────────────

def _key(r: dict) -> tuple:
    return (r["date"], tuple(sorted((nations.base_name(r["home"]), nations.base_name(r["away"])))))


def wid(r: dict) -> str:
    h = hashlib.sha1(f"{r['scope']}|{r['date']}|{r['home']}|{r['away']}".encode("utf-8")).hexdigest()[:10]
    return "w" + h


def build_store() -> dict:
    from .sources import wikipedia as W
    if not W.enabled():
        return {"disabled": True}
    raw = W.raw_dir() / "raw"
    rows: list[dict] = []
    squads: dict = {}
    pages = 0
    for p in sorted(raw.glob("*.json.gz")):
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError, EOFError):
            continue
        if rec.get("status") != 200 or not str(rec.get("path") or "").startswith("/wiki/"):
            continue
        from urllib.parse import unquote
        title = unquote(rec["path"][6:]).replace("_", " ")
        if ":" in title:
            continue
        pages += 1
        html = rec.get("text") or ""
        try:
            rows += rows_from_boxes(html, title)
            rows += rows_from_tables(html, title)
        except Exception as e:                                           # one bad page never stops the build
            log.warning("wiki parse %s: %s", title, e)
        if title.endswith("national rugby union team"):
            try:
                sq = squad_tables(html)
            except Exception as e:
                log.warning("squad parse %s: %s", title, e)
                sq = None
            if sq and (sq["current"] or sq["most_caps"]):
                nm = title.replace(" women's national rugby union team", " Women").replace(" national rugby union team", "")
                squads[nm] = sq
    sides = fix_sides(rows)
    # dedupe: same scope, date and pair; a rugbybox wins over a table row, a row with a referee over one without
    best: dict[tuple, dict] = {}
    conflicts = 0
    for r in rows:
        k = (r["scope"],) + _key(r)
        cur = best.get(k)
        if cur is None:
            best[k] = r
            continue
        same = {(cur["home"], cur["hs"]), (cur["away"], cur["as"])} == {(r["home"], r["hs"]), (r["away"], r["as"])}
        if not same:
            conflicts += 1
        rank = lambda x: (x["kind"] == "box", bool(x.get("referee")), bool(x.get("attendance")), x["comp"] != "test")
        if rank(r) > rank(cur):
            for f in ("referee", "attendance", "time_utc"):
                if not r.get(f) and cur.get(f):
                    r[f] = cur[f]
            best[k] = r
        else:
            for f in ("referee", "attendance", "time_utc"):
                if not cur.get(f) and r.get(f):
                    cur[f] = r[f]
    by_scope = defaultdict(list)
    for r in best.values():
        r["wid"] = wid(r)
        by_scope[r["scope"]].append(r)
    for sc, rs in by_scope.items():
        rs.sort(key=lambda r: (r["date"], r["wid"]))
        store.write_gz(store.side_dir() / "wiki" / f"{sc}.json.gz",
                       {"v": 1, "built": store.now(), "credit": W.CREDIT, "rows": rs,
                        "squads": {k: v for k, v in squads.items() if (k.endswith(" Women")) == (sc == "women")}})
    _CACHE.clear()
    return {"pages": pages, "rows": len(rows), "unique": len(best), "conflicting_duplicates": conflicts, "sides": sides,
            "by_scope": {k: len(v) for k, v in by_scope.items()}, "squads": len(squads)}


_CACHE: dict = {}


def load(scope: str) -> dict:
    p = store.side_dir() / "wiki" / f"{scope}.json.gz"
    k = str(p)
    if k not in _CACHE:
        try:
            _CACHE[k] = store.read_gz(p) if p.exists() else {}
        except (OSError, ValueError):
            _CACHE[k] = {}
    return _CACHE[k] or {}


def _team_ids(espn: list[dict], scope: str) -> dict:
    ids: dict[str, dict] = {}
    for m in espn:
        for s in ("home", "away"):
            t = m.get(s) or {}
            b = nations.base_name(t.get("name") or "")
            if b and t.get("id") and b not in ids:
                ids[b] = {"id": t["id"], "abbr": t.get("abbr"), "colour": t.get("colour"), "alt": t.get("alt")}
    return ids


def merge(scope: str, espn: list[dict]) -> tuple[list[dict], dict]:
    """ESPN's rows with the Wikipedia referee and attendance attached, plus the Wikipedia-only tests."""
    if not enabled():
        return espn, {"enabled": False}
    W = load(scope)
    rows = W.get("rows") or []
    if not rows:
        return espn, {"rows": 0}
    idx: dict[tuple, list[dict]] = defaultdict(list)
    for m in espn:
        d = str(m.get("date") or "")[:10]
        if not d:
            continue
        pair = tuple(sorted((nations.base_name(nations.canonical((m.get("home") or {}).get("name") or "")),
                             nations.base_name(nations.canonical((m.get("away") or {}).get("name") or "")))))
        idx[(d, pair)].append(m)
    ids = _team_ids(espn, scope)
    sfx = " Women" if scope == "women" else ""
    added, matched, conflicts, refs, atts = [], 0, 0, 0, 0
    first_espn = min((str(m.get("date") or "9999")[:10] for m in espn if m.get("status") == "final"), default="9999")
    for r in rows:
        pair = tuple(sorted((nations.base_name(r["home"]), nations.base_name(r["away"]))))
        hit = None
        dd = date.fromisoformat(r["date"])
        for k in (0, 1, -1):
            c = idx.get(((dd + timedelta(days=k)).isoformat(), pair))
            if c:
                hit = c[0]
                break
        if hit is not None:
            matched += 1
            if hit.get("status") == "final" and hit.get("hs") is not None and r.get("hs") is not None:
                hn = nations.base_name(nations.canonical(hit["home"]["name"]))
                got = {(hn, hit["hs"]), (nations.base_name(nations.canonical(hit["away"]["name"])), hit["as"])}
                if got != {(nations.base_name(r["home"]), r["hs"]), (nations.base_name(r["away"]), r["as"])}:
                    conflicts += 1
                    continue
            if r.get("referee") and not hit.get("referee"):
                hit["referee"] = r["referee"]
                refs += 1
            if r.get("attendance") and not hit.get("attendance"):
                hit["attendance"] = r["attendance"]
                atts += 1
            continue
        if r["scope"] != scope or r.get("pre") or r.get("hs") is None:
            continue

        def team(n):
            b = nations.base_name(n)
            t = ids.get(b)
            rr = nations.lookup(b)
            code = rr["code"] if rr else b[:3].upper()
            if t:
                return {"id": t["id"], "name": b + sfx, "abbr": t.get("abbr") or code, "colour": t.get("colour"), "alt": t.get("alt")}
            return {"id": f"w{code}", "name": b + sfx, "abbr": code, "colour": None, "alt": None}
        t_utc = r.get("time_utc")
        hs_, as_ = r["hs"], r["as"]
        ro = r["date"] < RESULT_ONLY_BEFORE
        if ro:
            # before 1891 there was no common points system (goals and tries were counted, the scores in the lists do
            # not compare): the result only, as an eight-point win or a 3-3 draw for the models
            hs_, as_ = (8, 0) if hs_ > as_ else ((0, 8) if as_ > hs_ else (3, 3))
        m = {"id": r["wid"], "comp": r["comp"], "slug": "wiki", "season": int(r["date"][:4]),
             "date": (t_utc + "Z") if t_utc else r["date"] + "T12:00Z", "time_known": bool(t_utc),
             "status": "final", "neutral": bool(r.get("neutral")), "venue": dict(r.get("venue") or {}),
             "home": team(r["home"]), "away": team(r["away"]), "hs": hs_, "as": as_, "hh": [], "ah": [],
             "note": r.get("event") or "", "season_slug": "", "source": "wikipedia", "page": r.get("page")}
        if ro:
            m["ro"] = 1
        if r.get("referee"):
            m["referee"] = r["referee"]
        if r.get("attendance"):
            m["attendance"] = r["attendance"]
        added.append(m)
    out = espn + added
    out.sort(key=lambda m: (m.get("date") or "", m.get("id")))
    in_window = sum(1 for r in rows if r["scope"] == scope and r["date"] >= first_espn)
    return out, {"rows": len(rows), "matched_espn": matched, "score_conflicts": conflicts, "added": len(added),
                 "referees_attached": refs, "attendance_attached": atts, "rows_since_first_espn": in_window}
