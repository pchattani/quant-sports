"""
Barttorvik (barttorvik.com, Bart Torvik's T-Rank) for The Quant Campus men's and women's college basketball: the
season team-results CSVs, a reference rating beside ours.

Terms: no terms page found (the site renders by script; checked 22 and 30 Oct 2026); approved under the user's
unclear-terms rule (30 Oct 2026), credited as *Barttorvik (barttorvik.com, T-Rank)* on the Campus Terms page and in
DATA_LICENSES.md. No lawsuit by the site over scraping or data reuse was found (web search, 30 Oct 2026).

robots.txt (obeyed by oddsmarkets/common/polite.py): `User-agent: *` disallows the game-level and time-machine pages
(`/db.php`, `/box.php`, `/trank-time-machine.php`, `/team-time-machine.php`, `/results.php`, `/conf-time-machine.php`,
`/playerstat.php`, `/teamcast.php`, `/*.json`, the same under `ncaaw/`) with `Crawl-Delay: 10`; the season CSVs
(`/<year>_team_results.csv`, `/ncaaw/<year>_team_results.csv`) are not disallowed. Only those are read, 10 s apart.

One switch:

    SOURCE_BARTTORVIK_ENABLED=0  -> no fetch, no parse; the derived table is ignored, so nothing of T-Rank shows.

No look-ahead: the CSVs are end-of-season (or current-to-date) ratings. They are shown for display and used as a
benchmark of our ratings; they are never a model input for the season they describe. The previous season's final
T-Rank is public before the next season starts, so it may serve as a pre-season benchmark.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from oddsmarkets.common.polite import ROOT, Source

SRC = Source(name="barttorvik", base="https://barttorvik.com", flag="SOURCE_BARTTORVIK_ENABLED",
             raw_dir=ROOT / "data" / "college" / "barttorvik", interval=10.0,
             credit="Barttorvik (barttorvik.com, T-Rank)")
CREDIT = SRC.credit
FIRST = {"mbb": 2008, "wbb": 2021}
DERIVED = Path(__file__).with_name("derived") / "barttorvik_teams.json"


def enabled() -> bool:
    return SRC.enabled()


def csv_path(level: str, season: int) -> str:
    return ("/ncaaw" if level == "wbb" else "") + f"/{int(season)}_team_results.csv"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_team_results(text: str | None) -> list[dict]:
    """Rows of a `<year>_team_results.csv`: rank, team, conf, record, adjoe, adjde, barthag, adjt, wab."""
    if not text or "<html" in text[:300].lower():
        return []
    rd = csv.reader(io.StringIO(text))
    head = next(rd, None)
    if not head:
        return []
    h = [c.strip().lower() for c in head]

    def col(*names):
        for n in names:
            if n in h:
                return h.index(n)
        return None
    i_rank, i_team, i_conf, i_rec = col("rank"), col("team"), col("conf"), col("record")
    i_oe, i_de, i_bh, i_t, i_wab = col("adjoe"), col("adjde"), col("barthag"), col("adjt"), col("wab")
    if i_team is None or i_oe is None or i_de is None:
        return []
    out = []
    for r in rd:
        if len(r) <= max(i_team, i_oe, i_de):
            continue
        oe, de = _f(r[i_oe]), _f(r[i_de])
        if oe is None or de is None:
            continue
        out.append({"rank": int(_f(r[i_rank]) or 0) if i_rank is not None else None, "team": r[i_team].strip(),
                    "conf": r[i_conf].strip() if i_conf is not None else None,
                    "record": r[i_rec].strip() if i_rec is not None else None,
                    "adjoe": round(oe, 2), "adjde": round(de, 2), "net": round(oe - de, 2),
                    "barthag": round(_f(r[i_bh]), 4) if i_bh is not None and _f(r[i_bh]) is not None else None,
                    "adjt": round(_f(r[i_t]), 1) if i_t is not None and _f(r[i_t]) is not None else None,
                    "wab": round(_f(r[i_wab]), 2) if i_wab is not None and _f(r[i_wab]) is not None else None})
    return out


def season_teams(level: str, season: int, fetch: bool = False, client=None) -> list[dict]:
    if not enabled():
        return []
    cl = client or SRC.client(offline=not fetch)
    cur = int(season) >= date.today().year
    return parse_team_results(cl.get(csv_path(level, season), max_age=86400 if (fetch and cur) else None))


# ── names ──────────────────────────────────────────────────────────────────────────────────────────────────

def norm(s: str | None) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    t = t.replace("&", " and ").replace("'", "")
    t = re.sub(r"\bst\b\.?", "state", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


# Barttorvik name -> ESPN-style display name, where the two differ beyond `norm` (checked against the Campus stores).
ALIAS = {
    "connecticut": "uconn", "mississippi": "ole miss", "miami fl": "miami", "miami oh": "miami oh",
    "louisiana lafayette": "louisiana", "louisiana monroe": "ul monroe", "nc state": "nc state",
    "north carolina state": "nc state", "saint marys": "saint marys", "state johns": "state johns",
    "southern miss": "southern miss", "texas a and m corpus chris": "texas a and m corpus christi",
    "cal state bakersfield": "cal state bakersfield", "umass lowell": "umass lowell", "massachusetts": "umass",
    "ut rio grande valley": "ut rio grande valley", "illinois chicago": "uic", "detroit": "detroit mercy",
    "loyola chicago": "loyola chicago", "fiu": "florida international", "liu": "long island university",
    "liu brooklyn": "long island university", "southeast missouri state": "southeast missouri state",
    "tennessee martin": "ut martin", "arkansas pine bluff": "arkansas pine bluff", "cal baptist": "california baptist",
    "nebraska omaha": "omaha", "pittsburgh": "pittsburgh", "penn": "pennsylvania", "the citadel": "citadel",
    "sam houston state": "sam houston", "grambling state": "grambling", "kansas city": "kansas city",
    "umkc": "kansas city", "usc upstate": "south carolina upstate", "southern": "southern",
    "seattle": "seattle u", "queens": "queens university", "saint francis": "saint francis",
    "st francis pa": "saint francis", "mount state marys": "mount state marys", "texas a and m commerce": "east texas a and m",
    "southeastern louisiana": "se louisiana", "mcneese state": "mcneese", "nicholls state": "nicholls",
    "central connecticut": "central connecticut", "fort wayne": "purdue fort wayne", "ipfw": "purdue fort wayne",
    "iupui": "iu indianapolis", "albany": "ualbany", "hawaii": "hawaii", "bethune cookman": "bethune cookman",
    "mississippi valley state": "mississippi valley state", "cal state northridge": "csun",
    "cal state fullerton": "cal state fullerton", "loyola md": "loyola maryland", "american": "american university",
    "byu": "byu", "uc santa barbara": "uc santa barbara", "app state": "app state", "appalachian state": "app state",
    "east tennessee state": "east tennessee state", "gardner webb": "gardner webb", "lsu": "lsu", "smu": "smu",
    "tcu": "tcu", "ucf": "ucf", "unlv": "unlv", "vcu": "vcu", "utep": "utep", "utsa": "utsa", "uab": "uab",
    "unc asheville": "unc asheville", "unc greensboro": "unc greensboro", "unc wilmington": "unc wilmington",
    "north carolina a and t": "north carolina a and t", "north carolina central": "north carolina central",
    "southern illinois edwardsville": "siu edwardsville", "siue": "siu edwardsville", "saint josephs": "saint josephs",
    "state bonaventure": "state bonaventure", "st thomas": "state thomas minnesota", "state thomas": "state thomas minnesota",
    "le moyne": "le moyne", "texas southern": "texas southern", "prairie view a and m": "prairie view a and m",
    "alabama a and m": "alabama a and m", "florida a and m": "florida a and m", "maryland eastern shore": "maryland eastern shore",
    "hawaii": "hawaii", "college of charleston": "charleston", "charleston": "charleston",
    "n c state": "nc state", "iu indy": "iu indianapolis", "new orleans": "lsu new orleans",
    "state francis ny": "state francis brooklyn",
}


def match_names(bt_names: list[str], ours: dict[str, str]) -> dict[str, str]:
    """{barttorvik name: our team id} by normalised name, then the alias table, then a unique prefix match."""
    by = {}
    for tid, nm in ours.items():
        by.setdefault(norm(nm), tid)
    out = {}
    for n in bt_names:
        k = norm(n)
        tid = by.get(k) or by.get(ALIAS.get(k, "\0"))
        if tid is not None and tid not in out.values():     # exact names and aliases only, one row per team
            out[n] = tid
    return out


# ── derived table (committed; read by the Campus build and the benchmark) ─────────────────────────────────

def build_derived(team_names: dict[str, dict[str, dict[str, str]]]) -> dict:
    """team_names: {level: {season: {our tid: name}}} -> {"levels": {level: {season: {tid: row}}}, "unmatched": ...}."""
    levels, unmatched = {}, {}
    for level, by_season in team_names.items():
        for s, ours in sorted(by_season.items()):
            rows = season_teams(level, int(s))
            if not rows:
                continue
            m = match_names([r["team"] for r in rows], ours)
            levels.setdefault(level, {})[str(s)] = {
                m[r["team"]]: {"rank": r["rank"], "adjoe": r["adjoe"], "adjde": r["adjde"], "net": r["net"],
                               "barthag": r["barthag"], "adjt": r["adjt"], "wab": r["wab"]}
                for r in rows if r["team"] in m}
            miss = sorted(r["team"] for r in rows if r["team"] not in m)
            if miss:
                unmatched.setdefault(level, {})[str(s)] = miss
    return {"source": "barttorvik", "credit": CREDIT, "url": "https://barttorvik.com",
            "note": "T-Rank team ratings from Barttorvik's season team-results CSVs (end of season, or to date for the "
                    "current season): adjusted offensive and defensive efficiency per 100 possessions, net = adjoe - "
                    "adjde, barthag, adjusted tempo, wins above bubble. A reference beside our ratings; never a model "
                    "input for the season it describes.",
            "levels": levels, "unmatched": unmatched}


def write_derived(team_names) -> Path | None:
    if not enabled():
        return None
    d = build_derived(team_names)
    if not d["levels"]:
        return None
    DERIVED.parent.mkdir(parents=True, exist_ok=True)
    DERIVED.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    return DERIVED


def load_derived() -> dict | None:
    if not enabled() or not DERIVED.exists():
        return None
    try:
        return json.loads(DERIVED.read_text(encoding="utf-8"))
    except ValueError:
        return None
