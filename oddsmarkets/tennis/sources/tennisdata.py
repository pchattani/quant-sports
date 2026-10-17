"""
tennis-data.co.uk: every ATP (2000->) and WTA (2007->) tour-level main-draw singles match with
round, surface, court, best-of, games per set, entry ranks and points, and closing odds
(Pinnacle, Bet365, Max and Avg from Oddsportal, Betfair Exchange; older years carry other books).

The yearly workbooks live under a hidden path prefix that the site rotates; the links with the
prefix are on data.php (alldata.php lists the same files without it). So every run reads the link
page first (1 call), then downloads only what changed: completed years once, the current year
when its Last-Modified moves (a conditional GET answers 304 otherwise). Files are cached under
data/tennis/td/<tour>/<year>.<ext> (git-ignored) with a small .meta.json beside each.

Formats: 2013-> are .xlsx (openpyxl); 2000-2012 are BIFF .xls, which needs `xlrd` (an optional
dependency: without it those years are skipped and reported).

Verified on 1 Oct 2026: ATP columns ATP, Location, Tournament, Date, Series, Court, Surface, Round,
Best of, Winner, Loser, WRank, LRank, WPts, LPts, W1..L5, Wsets, Lsets, Comment, B365W/L, PSW/L,
MaxW/L, AvgW/L, BFEW/L; WTA has WTA and Tier in place of ATP and Series and only W1..L3. Names are
"Surname I." ("Sinner J.", "Fernandez L.A.", "Ugo Carabelli C."). No tiebreak points, no seeds.
Before 2003 `Date` is the tournament's start date for every match.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .. import canon
from ._client import Client

logger = logging.getLogger(__name__)

BASE = "https://www.tennis-data.co.uk"
LINK_PAGES = ("data.php", "alldata.php")
FIRST_YEAR = {"atp": 2000, "wta": 2007}
_LINK = re.compile(r'href="?((?:[A-Za-z0-9_\-]+/)?(\d{4})(w?)/\d{4}\.(xlsx?|zip))', re.I)

# bookmaker column prefix -> MATCH.odds key (the others are kept in odds["other"])
BOOKS = {"PS": "ps", "B365": "b365", "Avg": "avg", "Max": "max", "BFE": "bfe"}
OTHER_BOOKS = ("CB", "EX", "IW", "LB", "SB", "SJ", "UB", "GB", "B&W", "BFD", "PSC")


def cache_root() -> Path:
    import os
    return Path(os.environ.get("ACE_RAW") or (canon.ROOT / "data" / "tennis")) / "td"


# -- links and downloads --------------------------------------------------------------------------

def parse_links(html: str) -> dict[tuple[str, int], str]:
    """{(tour, year): absolute url} from a link page; prefixed links win over bare ones."""
    out: dict[tuple[str, int], str] = {}
    for m in _LINK.finditer(html or ""):
        path, year, w, _ = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        key = ("wta" if w else "atp", year)
        prefixed = path.count("/") >= 2
        if key not in out or prefixed:
            out[key] = f"{BASE}/{path}"
    return out


def links(c: Client) -> dict[tuple[str, int], str]:
    """The current download links (prefix included). Tries data.php, then alldata.php."""
    best: dict[tuple[str, int], str] = {}
    for page in LINK_PAGES:
        html = c.get_text(f"{BASE}/{page}")
        got = parse_links(html or "")
        if any(u.count("/") >= 5 for u in got.values()):        # https://host/prefix/2026/2026.xlsx
            return got
        best = best or got
    if not best:
        logger.warning("tennis-data: no download links found on %s", ", ".join(LINK_PAGES))
    return best


def _meta_path(p: Path) -> Path:
    return p.with_name(p.name + ".meta.json")


def cached_file(tour: str, year: int) -> Path | None:
    d = cache_root() / tour
    for ext in ("xlsx", "xls"):
        p = d / f"{int(year)}.{ext}"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def fetch(c: Client, tour: str, year: int, url: str, refresh: bool = False) -> tuple[Path | None, bool]:
    """(local path, changed). A cached completed year is never re-read; with `refresh` the file is
    re-requested conditionally (If-Modified-Since), so an unchanged current year costs one 304."""
    ext = url.rsplit(".", 1)[-1].lower()
    p = cache_root() / tour / f"{int(year)}.{ext}"
    meta = {}
    if p.exists():
        try:
            meta = json.loads(_meta_path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        if not refresh:
            return p, False
    body, hdr = c.get_bytes(url, if_modified_since=meta.get("last_modified") if p.exists() else None)
    if hdr.get("status") == 304:
        return p, False
    if body is None:
        return (p if p.exists() else None), False
    if body[:4] not in (b"PK\x03\x04", b"\xd0\xcf\x11\xe0"):
        logger.warning("tennis-data %s answered something that is not a workbook (%d bytes)", url, len(body))
        return (p if p.exists() else None), False
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(p)
    _meta_path(p).write_text(json.dumps({"url": url, "last_modified": hdr.get("last-modified"), "etag": hdr.get("etag"),
                                         "bytes": len(body), "fetched": canon.now()}), encoding="utf-8")
    return p, True


def last_modified(tour: str, year: int) -> str | None:
    p = cached_file(tour, year)
    if not p:
        return None
    try:
        return json.loads(_meta_path(p).read_text(encoding="utf-8")).get("last_modified")
    except (OSError, ValueError):
        return None


# -- reading --------------------------------------------------------------------------------------

def read_rows(path: Path) -> list[dict]:
    """Rows of the workbook's first non-empty sheet as dicts ([] when unreadable)."""
    import pandas as pd
    path = Path(path)
    if path.suffix.lower() == ".csv":                  # recorded slices (tests) and hand-made files
        df = pd.read_csv(path, parse_dates=["Date"])
        df = df.dropna(subset=["Winner", "Loser"])
        return [{k: _cell(v) for k, v in r.items()} for r in df.to_dict("records")]
    engine = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"
    if engine == "xlrd":
        try:
            import xlrd  # noqa: F401
        except ImportError:
            logger.warning("tennis-data %s is .xls and xlrd is not installed: skipped", path.name)
            return []
    try:
        sheets = pd.read_excel(path, sheet_name=None, engine=engine)
    except Exception as exc:                       # noqa: BLE001 - a bad workbook must not stop a backfill
        logger.warning("tennis-data %s unreadable: %s", path, exc)
        return []
    for df in sheets.values():
        if df.shape[0] and "Winner" in df.columns:
            df = df.dropna(subset=["Winner", "Loser"])
            return [{k: _cell(v) for k, v in r.items()} for r in df.to_dict("records")]
    return []


def _cell(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "to_pydatetime"):
        return v.to_pydatetime()
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(str(v).replace(",", "").strip())
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _int(v: Any) -> int | None:
    x = _num(v)
    return None if x is None else int(round(x))


def _date(v: Any) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:        # an Excel serial that escaped parsing
        from datetime import timedelta
        return (date(1899, 12, 30) + timedelta(days=int(v))).isoformat()
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


STATUS = {"completed": "done", "retired": "ret", "walkover": "wo", "w/o": "wo", "disqualified": "def",
          "def": "def", "default": "def", "defaulted": "def", "awarded": "wo", "sched": "upcoming"}


def _odds(r: dict) -> dict | None:
    out: dict[str, Any] = {}
    for col, key in BOOKS.items():
        w, l_ = _num(r.get(col + "W")), _num(r.get(col + "L"))
        if w and l_ and w > 1 and l_ > 1:
            out[key] = [w, l_]
    other = {}
    for col in OTHER_BOOKS:
        w, l_ = _num(r.get(col + "W")), _num(r.get(col + "L"))
        if w and l_ and w > 1 and l_ > 1:
            other[col.lower()] = [w, l_]
    if other:
        out["other"] = other
    return out or None


def group_events(rows: list[dict], num_col: str) -> list[list[dict]]:
    """Rows grouped into events. The file's tournament number is the first key, but the files
    sometimes split one event across two numbers (WTA Charleston 2018, ATP Montpellier 2020): groups
    with the same tournament name and location merge when they start within 3 days of each other
    or hold no round in common."""
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for r in rows:
        key = (r.get(num_col), str(r.get("Tournament") or "").strip(), str(r.get("Location") or "").strip())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)
    merged: list[tuple[tuple, list[dict]]] = []
    for key in order:
        g = groups[key]
        start = min((d for d in (_date(r.get("Date")) for r in g) if d), default=None)
        rounds = {str(r.get("Round") or "") for r in g}
        for k2, g2 in merged:
            if k2[1:] != key[1:]:
                continue
            start2 = min((d for d in (_date(r.get("Date")) for r in g2) if d), default=None)
            rounds2 = {str(r.get("Round") or "") for r in g2}
            if canon._days_apart(start, start2) <= 3 or not (rounds & rounds2):
                g2.extend(g)
                break
        else:
            merged.append((key, list(g)))
    return [g for _, g in merged]


def parse(rows: list[dict], tour: str, year: int) -> list[dict]:
    """Source match records (see canon.SMR_DOC), winner as side "a", in file order, with each
    event's round labels inferred from the rounds it holds."""
    tour = canon.tour_key(tour)
    num_col = "ATP" if tour == "atp" else "WTA"
    series_col = "Series" if tour == "atp" else "Tier"
    out: list[dict] = []
    for grp in group_events(rows, num_col):
        dates = sorted(d for d in (_date(r.get("Date")) for r in grp) if d)
        raw_rounds = [str(r.get("Round") or "") for r in grp]
        first = grp[0]
        series = first.get(series_col)
        level = canon.level_from_series(tour, series, first.get("Tournament"))
        tid_hint = canon.tid_for(tour, first.get("Tournament"), first.get("Location"), level)
        level = canon.fix_level(tour, year, tid_hint, level, series)
        r1 = sum(1 for x in raw_rounds if canon.td_round_number(x) == 1)
        labels = canon.td_round_labels(raw_rounds, level=level, tid=tid_hint, tour=tour, year=year)
        bracket = canon.bracket_size(labels)
        ev = {"name": first.get("Tournament"), "city": str(first.get("Location") or "").strip() or None, "country": None,
              "start": dates[0] if dates else None, "end": dates[-1] if dates else None,
              "level": level, "series": series, "surface": canon.surface_key(first.get("Surface")),
              "indoor": str(first.get("Court") or "").lower().startswith("indoor"),
              "draw_size": canon.snap_draw(canon.entrants(bracket, r1)) if bracket else None,
              "td": f"{_int(first.get(num_col))}|{first.get('Tournament')}|{first.get('Location')}",
              "espn": None, "wta": None, "tid_hint": tid_hint}
        for r, rd_raw in zip(grp, raw_rounds):
            best_of = _int(r.get("Best of")) or canon.best_of(tour, level, labels.get(rd_raw), year)
            sets = []
            for i in range(1, 6):
                w, l_ = _int(r.get(f"W{i}")), _int(r.get(f"L{i}"))
                if w is None and l_ is None:
                    continue
                sets.append([w or 0, l_ or 0, None, None])
            while sets and sets[-1][0] == 0 and sets[-1][1] == 0:      # a retirement before the set began
                sets.pop()
            comment = str(r.get("Comment") or "Completed").strip().lower()
            if comment.startswith("cancel"):
                continue
            status = STATUS.get(comment.split(" ")[0])
            if status is None:                       # typos seen in the files: "Rrtired", "Walkoer"
                status = "ret" if "tir" in comment else "wo" if comment.startswith("walk") else "done"
            out.append({
                "src": "td", "tour": tour, "year": int(year), "event": ev,
                "round": labels.get(rd_raw), "round_raw": rd_raw, "date": _date(r.get("Date")),
                "best_of": best_of,
                "a": {"name": r.get("Winner"), "rank": _int(r.get("WRank")), "pts": _int(r.get("WPts"))},
                "b": {"name": r.get("Loser"), "rank": _int(r.get("LRank")), "pts": _int(r.get("LPts"))},
                "winner": "a", "status": status, "sets": sets, "odds": _odds(r), "stats": None, "live": None,
                "duration_min": None, "src_id": f"{ev['td']}:{len(out)}",
                "sets_won": [_int(r.get("Wsets")), _int(r.get("Lsets"))],
            })
    return out


def load_year(c: Client | None, tour: str, year: int, link: str | None, refresh: bool = False) -> tuple[list[dict], dict]:
    """(records, info) for one tour-year: downloads when needed (c may be None to read the cache only)."""
    tour = canon.tour_key(tour)
    info: dict[str, Any] = {"year": int(year), "changed": False, "file": None, "last_modified": None}
    p = cached_file(tour, year)
    if c is not None and link:
        p2, changed = fetch(c, tour, year, link, refresh=refresh)
        p = p2 or p
        info["changed"] = changed
    if not p:
        info["error"] = "no file"
        return [], info
    info["file"] = p.name
    info["last_modified"] = last_modified(tour, year)
    rows = read_rows(p)
    if not rows:
        info["error"] = "unreadable (.xls needs xlrd)" if p.suffix == ".xls" else "unreadable"
        return [], info
    recs = parse(rows, tour, year)
    info["rows"] = len(rows)
    return recs, info
