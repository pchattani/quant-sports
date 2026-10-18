"""
People, clubs and seasons across every competition: the unified payloads
(docs/site/UNIFIED_PAYLOADS.md).

Every store is one competition, and a player or a club used to exist once per
competition: Erling Haaland in the Premier League, again in the Champions League,
again for Norway. Here every person is one record keyed by Sofascore player id
and every club or national team one record keyed by Sofascore team id, each
carrying every appearance or match from every store tagged with its competition,
the competition's kind (league, domestic cup, super cup, continental club
competition, international) and its season, so the front end can filter All /
Club / International / one competition / one season.

Who plays where is decided by the squads store (docs/site/data/squads/store.json,
scripts/fetch_sofascore_squads.py) where it has the club: lineups only say where a
player last appeared in a competition the site follows, which keeps a player who
has left listed at his old club until he plays somewhere followed.

Seasons: each competition lists its editions newest first, the live one (the
existing payloads), the past ones its store holds (results, a table, player and
club lines where there is match detail), and older ones from the archive
(official standings and season leaders) and the past-results store.

Inputs are plain dicts (stores, seasons.json, the archive, the squads and past
stores, the competitions as built), so everything here is testable offline.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from oddsmarkets.football.analytics.archive import season_row, sort_key
from oddsmarkets.football.analytics.players import METRICS, add_percentiles, aggregate_players, player_incidents
from oddsmarkets.football.competitions.cup.config import CUPS
from oddsmarkets.football.competitions.league.config import LEAGUES, LIGA_ARGENTINA_SLUG
from oddsmarkets.football.competitions.liga.store import overdue as _overdue

logger = logging.getLogger(__name__)

KIND_BY_FAMILY = {"cup": "continental_club", "domestic": "domestic_cup", "super": "super_cup", "international": "international"}
FINISHED = {"finished", "ended", "afterpenalties", "afterextratime", "ap", "aet"}
APPS_FIELDS = ["date", "gid", "comp", "sid", "tid", "opp_tid", "opp", "home", "res", "start",
               "min", "g", "a", "xg", "xa", "rt", "sh", "kp", "yc", "rc"]
# How a national team's squad is read without a roster: who played for it within
# this many days of its latest match.
NATIONAL_SQUAD_DAYS = 400
# A person's season row used to carry the competition's full season line (every
# metric and its percentile) above LINE_MIN_MINUTES. No page read it and it was more
# than half of data/people/ (76 of 142 MB on 15 October 2026), so it is off: the person
# page's competition dossier reads the competition's players_live.json, and a past
# season's lines are in s/<sid>/season.json. PERSON_LINES = True restores it.
PERSON_LINES = False
LINE_MIN_MINUTES = 90
LINE_DROP = {"player_id", "name", "short_name", "team", "country", "height", "shirt", "age", "is_gk", "position", "pool"}
# Knockout depth, for "how far a club went" in a cup.
ROUND_DEPTH = {"qualifying": 0, "prelim": 0, "po": 1, "league": 2, "group": 2, "r64": 3, "r32": 4, "r16": 5, "qf": 6, "sf": 7,
               "3rd": 7, "final": 8, "winner": 9}


# ── competitions ─────────────────────────────────────────────────────────────

def competitions() -> dict[str, dict]:
    """slug -> {name, short, kind, scope, tid, registry} for every competition in the registry."""
    out: dict[str, dict] = {}
    for slug, cfg in LEAGUES.items():
        out[slug] = {"name": cfg.name, "short": cfg.short_name, "kind": "league", "scope": "club",
                     "tid": cfg.sofascore_id, "registry": cfg.registry}
    out[LIGA_ARGENTINA_SLUG] = {"name": "Liga Profesional de Fútbol", "short": "Liga Argentina", "kind": "league",
                                "scope": "club", "tid": 155, "registry": "liga_argentina"}
    for slug, cfg in CUPS.items():
        kind = KIND_BY_FAMILY.get(cfg.family, "continental_club")
        out[slug] = {"name": cfg.name, "short": cfg.short_name, "kind": kind,
                     "scope": "international" if kind == "international" else "club",
                     "tid": cfg.sofascore_id, "registry": cfg.registry}
    return out


# ── the season model (docs/football_data_audit.md) ──────────────────────────
#
# Every competition runs on one of two frames. A split season runs July to June and
# is labelled "2026/27" (the European leagues and cups, their super cups, Saudi Arabia,
# the AFC and CAF club competitions, the Nations League); a calendar season is the
# year, "2026" (Brazil, MLS, Liga MX's two halves, Argentina, the South and North
# American club cups, the world club cups). An edition's season key (`era`) comes from
# its matches' dates in its competition's frame, so a super cup played on 2 August 2026
# opens 2026/27 whatever Sofascore's `year` says. International football has no season
# of its own: a player's international appearances fall in his own frame (that of his
# club football) by date, the split year turning on 1 August so a June or July
# tournament closes the season it ends. National teams' own pages read the calendar year.

CALENDAR_COMPETITIONS = frozenset({
    "brasileirao", "mls", "liga-mx", LIGA_ARGENTINA_SLUG,
    "libertadores", "sudamericana", "recopa-sudamericana", "concacaf-champions-cup", "leagues-cup", "campeones-cup",
    "club-world-cup", "intercontinental-cup", "copa-do-brasil", "supercopa-do-brasil", "copa-argentina",
    "supercopa-argentina", "us-open-cup", "campeon-de-campeones",
})
# World club competitions bring both frames together (the Club World Cup in June and July, the
# Intercontinental Cup from September to December): like international football, an appearance
# there counts in the player's (and a club's) own frame by date.
NEUTRAL_COMPETITIONS = frozenset({"club-world-cup", "intercontinental-cup"})
# Matches with line-ups get a page of their own only in the live edition or the last year
# (scripts/build_site_all.py has_match_page): older detail feeds the totals, not a page each.
MATCH_PAGE_DAYS = 365
SPLIT_START_MONTH = 7          # a club edition's matches from July on belong to the season that starts that year
INTL_SPLIT_START_MONTH = 8     # an international appearance in a split frame: June and July close the season


def frame_of(slug: str | None) -> str:
    """"split", "calendar" or "international" for a competition slug (unknown: split)."""
    if not slug:
        return "split"
    if slug in CALENDAR_COMPETITIONS:
        return "calendar"
    cfg = CUPS.get(slug)
    if cfg is not None and cfg.family == "international":
        return "international"
    return "split"


def frame_era(frame: str, date: str | None, start_month: int = SPLIT_START_MONTH) -> str | None:
    """The season key of a date in a frame: "2026/27" (split) or "2026" (calendar, international)."""
    d = str(date or "")
    if len(d) < 7 or not d[:4].isdigit() or not d[5:7].isdigit():
        return None
    y, m = int(d[:4]), int(d[5:7])
    if frame == "split":
        s = y if m >= start_month else y - 1
        return f"{s}/{(s + 1) % 100:02d}"
    return str(y)


def _median_date(dates: Iterable[str]) -> str | None:
    ds = sorted(str(d)[:10] for d in dates if d)
    return ds[len(ds) // 2] if ds else None


def edition_era(slug: str, label_era: str, dates: Iterable[str] = (), shift: int | None = None) -> str:
    """
    One edition's season key: from the median date of its matches in the
    competition's frame (calendar for an international competition); without
    dates (an archive-only edition) from Sofascore's label, a four-digit year in a
    split competition moved by `shift` (learned from the editions with dates: the
    Supercopa de Espana named "2027" is played in January 2027, 2026/27) or, by
    default, opening the season that starts that year (a summer super cup).
    """
    frame = frame_of(slug)
    med = _median_date(dates)
    if med:
        out = frame_era("calendar" if frame == "international" else frame, med)
        if out:
            return out
    e = str(label_era or "")
    if frame == "split" and re.fullmatch(r"(19|20)\d{2}", e):
        s = int(e) + (shift or 0)
        return f"{s}/{(s + 1) % 100:02d}"
    if frame != "split":
        m = re.match(r"^((?:19|20)\d{2})/\d{2}$", e)
        if m:
            return m.group(1)
    return e


def person_frame(club_slugs_newest_first: list[str], archive_years: list[str] | None = None) -> str:
    """A player's frame: that of his latest club league (else latest club competition, else his archive career's latest season)."""
    leagues = [s for s in club_slugs_newest_first if s in LEAGUES or s == LIGA_ARGENTINA_SLUG]
    for s in leagues or club_slugs_newest_first:
        f = frame_of(s)
        if f != "international":
            return f
    for y in archive_years or []:
        if _SPLIT_RE.match(str(y or "")):
            return "split"
        if re.fullmatch(r"(19|20)\d{2}", str(y or "")):
            return "calendar"
    return "calendar"


_SPLIT_RE = re.compile(r"^\d{2}/\d{2}$")


def current_era(frame: str, today: datetime) -> str:
    """The season a frame is in today (a split season from July, when its club editions start)."""
    return frame_era(frame, today.strftime("%Y-%m-%d")) or str(today.year)


def tournament_slugs() -> dict[int, str]:
    """Sofascore tournament id -> slug, for mapping archive careers onto competitions."""
    out: dict[int, str] = {}
    for slug, c in competitions().items():
        if c["tid"]:
            out.setdefault(int(c["tid"]), slug)
    for slug, cfg in LEAGUES.items():
        alt = getattr(cfg, "alt_sofascore_id", None)
        if alt:
            out.setdefault(int(alt), slug)
    return out


# ── seasons ──────────────────────────────────────────────────────────────────

_SPLIT = re.compile(r"^(\d{2})/(\d{2})$")
_YEAR4 = re.compile(r"(19|20)\d{2}")


_NAME_SPLIT = re.compile(r"\b(?:19|20)?(\d{2})/(?:19|20)?(\d{2})\b")


def _split_era(a: str, b: str) -> str:
    ai = int(a)
    return f"{2000 + ai if ai < 70 else 1900 + ai}/{b}"


def _name_season(name: str) -> str | None:
    """The season a competition's name states ("Super Cup 22/23" -> "22/23", "UEFA Super Cup 2026" -> "2026"), if any."""
    m = _NAME_SPLIT.search(name)
    if m and int(m.group(2)) == (int(m.group(1)) + 1) % 100:
        return f"{m.group(1)}/{m.group(2)}"
    found = re.findall(r"(?:19|20)\d{2}", name)
    return found[-1] if found else None


def fan_label(slug: str | None, season: str) -> str:
    """
    World Cup qualifying is named for the World Cup it leads to: Sofascore's "World Cup
    Qualification, AFC 2025" is 2026 World Cup qualifying.
    """
    if slug and slug.startswith("wc-qual") and re.fullmatch(r"(19|20)\d{2}", str(season or "")):
        y = int(season)
        while y % 4 != 2:
            y += 1
        return str(y)
    return season


def year_label(year: str | None) -> tuple[str, str] | None:
    """(season, era) from Sofascore's season year alone ("26/27", "2026"), or None."""
    y = str(year or "").strip()
    m = _SPLIT.match(y)
    if m and int(m.group(2)) == (int(m.group(1)) + 1) % 100:
        return y, _split_era(m.group(1), m.group(2))
    if len(y) == 4 and y.isdigit():
        return y, y
    return None


def season_label(name: str | None, year: str | None) -> tuple[str, str]:
    """
    (season, era) from Sofascore's season name and year. The label is the season
    the name states, as a fan reads it ("UEFA Super Cup 2026", not "26/27"; "Euro
    2020", not 2021); the era, the cross-competition grouping key, comes from the
    year ("26/27" -> "2026/27", "2026" -> "2026"). A qualifying competition is
    labelled by the tournament it qualifies for (the later of the two years). The
    halves of a split-season league ("Apertura 2026") keep their name and fall in
    their calendar year.
    """
    name = str(name or "")
    y = str(year or "").strip()
    half = re.search(r"\b(apertura|clausura)\b", name, re.I)
    if half:
        m = re.search(r"(?:19|20)\d{2}", name)
        yy = m.group(0) if m else (y if len(y) == 4 and y.isdigit() else "")
        return f"{half.group(1).capitalize()} {yy}".strip(), yy or y
    by_year = year_label(y)
    from_name = _name_season(name)
    if by_year:
        label, era = by_year
        if from_name:
            label = from_name
            if "qualif" in name.lower() and len(from_name) == 4 and len(y) == 4 and y.isdigit():
                label = max(from_name, y)
        return label, era
    if from_name:
        m = _SPLIT.match(from_name)
        return from_name, (_split_era(m.group(1), m.group(2)) if m else from_name)
    return y or name, y or name


def era_key(era: str) -> tuple[int, int]:
    """Sort key: "2026/27" after "2026" (a split season ends in the later year)."""
    m = re.match(r"^((?:19|20)\d{2})(?:/(\d{2}))?", str(era or ""))
    if not m:
        return (0, 0)
    return (int(m.group(1)), 1 if m.group(2) else 0)


def _season_sort(row: dict) -> tuple:
    half = 1 if str(row.get("season", "")).startswith("Clausura") else 0
    return (*era_key(row.get("era", "")), half, str(row.get("sid")))


def liga_season_key(m: dict) -> str | None:
    """The Argentine store holds a calendar year; its seasons are the year's halves."""
    d = str(m.get("date") or "")[:4]
    t = m.get("torneo")
    return f"{d}-{t}" if d and t else None


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _finished(m: dict) -> bool:
    return str(m.get("status") or "").lower() in FINISHED and m.get("hs") is not None and m.get("as") is not None


# ── standings, champions ─────────────────────────────────────────────────────

def compute_standings(matches: Iterable[dict], stages: tuple[str, ...] = ("league",)) -> list[dict]:
    """A table (per group when matches carry one) from finished league-phase results: 3/1/0, then GD, GF."""
    rows: dict[tuple, dict] = {}
    for m in matches:
        if (m.get("stage") or "league") not in stages or not _finished(m):
            continue
        g = m.get("group")
        for side, tid, gf, ga in (("home", m.get("home_id"), m["hs"], m["as"]), ("away", m.get("away_id"), m["as"], m["hs"])):
            r = rows.setdefault((g, m[side]), {"team": m[side], "tid": tid, "group": g, "played": 0, "w": 0, "d": 0, "l": 0,
                                               "gf": 0, "ga": 0, "pts": 0})
            r["played"] += 1
            r["gf"] += int(gf)
            r["ga"] += int(ga)
            if gf > ga:
                r["w"] += 1
                r["pts"] += 3
            elif gf == ga:
                r["d"] += 1
                r["pts"] += 1
            else:
                r["l"] += 1
    out: list[dict] = []
    groups = sorted({k[0] for k in rows}, key=lambda g: (g is None, str(g)))
    for g in groups:
        members = [r for k, r in rows.items() if k[0] == g]
        for r in members:
            r["gd"] = r["gf"] - r["ga"]
        members.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["team"]))
        for i, r in enumerate(members, start=1):
            r["pos"] = i
            if r["group"] is None:
                del r["group"]
        out.extend(members)
    return out


def official_standings(archive_season: dict, name_to_tid: Callable[[str], Any]) -> list[dict]:
    """The archive's standings rows in the season.json row shape."""
    out = []
    rows = archive_season.get("standings") or []
    blocks = {r.get("group") for r in rows}
    for r in rows:
        tid = r.get("team_id") or name_to_tid(r.get("team"))
        row = {"pos": r.get("position"), "team": r.get("team"), "tid": tid, "played": r.get("matches"), "pts": r.get("points")}
        if len(blocks) > 1 and r.get("group"):
            row["group"] = r.get("group")
        if r.get("promotion"):
            row["note"] = r.get("promotion")
        out.append({k: v for k, v in row.items() if v is not None})
    return out


def merge_records(official: list[dict], computed: list[dict]) -> list[dict]:
    """
    The official table with each club's record (W, D, L, goals) from the results,
    when the results account for every club's games exactly; otherwise as it is
    (an archive table spans phases the results do not, or the results are partial).
    """
    if not official or not computed:
        return official
    tids = [r.get("tid") for r in official]
    if None in tids or len(set(tids)) != len(tids):
        return official
    by: dict = {}
    for r in computed:
        if r.get("tid") in by:
            return official
        by[r.get("tid")] = r
    if any(t not in by or by[t]["played"] != r.get("played") for t, r in zip(tids, official)):
        return official
    out = []
    for r in official:
        row = dict(r)
        for k in ("w", "d", "l", "gf", "ga", "gd"):
            row[k] = by[r["tid"]][k]
        out.append(row)
    return out


def _drop_stale(ms: dict) -> dict:
    """A finished season without its stale copies: a postponed or cancelled entry whose fixture was played under another id."""
    played = {(m.get("home"), m.get("away")) for m in ms.values() if isinstance(m, dict) and _finished(m)}
    return {g: m for g, m in ms.items() if isinstance(m, dict) and not (
        str(m.get("status") or "").lower() in ("postponed", "canceled", "cancelled") and (m.get("home"), m.get("away")) in played)}


def tie_winner(m: dict) -> str | None:
    """The side that won one match (penalties and aggregates included)."""
    if m.get("agg_winner"):
        return m["agg_winner"]
    if m.get("winner"):
        return m["winner"]
    if not _finished(m):
        return None
    if m["hs"] > m["as"]:
        return m["home"]
    if m["as"] > m["hs"]:
        return m["away"]
    return None


def champion_of(matches: list[dict], standings: list[dict], kind: str, title_by_playoff: bool = False) -> dict | None:
    """
    The final's winner, else (a league) the top of a single table. A league's
    "final" is a relegation or promotion play-off (Paderborn v Wolfsburg) unless
    the league crowns its champion in a play-off (Liga MX's Liguilla, MLS Cup, the
    Argentine torneos), so a league reads its table unless `title_by_playoff`. A
    final in a qualifying stage (the Club World Cup's play-in) crowns no one.
    """
    finals = [m for m in matches if m.get("round") == "final" and _finished(m)
              and str(m.get("stage") or "") not in ("qualifying", "other", "split")]
    if kind == "league" and not title_by_playoff:
        finals = []
    # Several finals between different pairs (the Euro qualifiers' play-off paths)
    # crown no one.
    if len({frozenset((m.get("home"), m.get("away"))) for m in finals}) > 1:
        return None
    if finals:
        finals.sort(key=lambda m: str(m.get("date") or ""))
        m = finals[-1]
        w = tie_winner(m)
        if w:
            return {"team": w, "tid": m.get("home_id") if w == m.get("home") else m.get("away_id")}
    if kind == "league" and standings:
        groups = {r.get("group") for r in standings if r.get("group")}
        if not groups:
            top = next((r for r in standings if r.get("pos") == 1), None)
        else:
            # A split league (Belgium) is won at the top of its championship round.
            champ = [g for g in groups if re.search(r"champion", str(g), re.I)]
            top = next((r for r in standings if r.get("pos") == 1 and r.get("group") == champ[0]), None) if len(champ) == 1 else None
        if top:
            return {k: top.get(k) for k in ("team", "tid") if top.get(k) is not None}
    return None


def _new_cs() -> dict:
    """A club's accumulator for one competition-season."""
    return {"played": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "depth": -1, "won_final": False, "lost_final": False,
            "po_played": 0, "lg": {"played": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0},
            "det_n": 0, "na_n": 0, "bf_n": 0}     # finished matches: with line-ups, none on Sofascore, queued for backfill


def _round_key(m: dict, kind: str | None = None) -> tuple[str | None, float]:
    """
    How far a match is into a competition: (round key, depth). Knockout keys as
    stored ("r16", "qf", ...); a numbered round of a national cup is that round
    ("r3": Sofascore files a national cup's early rounds under "qualification",
    but the EFL Cup's third round is the third round, not a qualifier); a numbered
    round in a continental qualifying stage is a qualifying round ("q2"); Sofascore's
    round 300 is the preliminary round.
    """
    r = m.get("round")
    stage = str(m.get("stage") or "league")
    if isinstance(r, str) and r in ROUND_DEPTH:
        return r, ROUND_DEPTH[r]
    n = None
    if isinstance(r, int) or (isinstance(r, str) and r.isdigit()):
        n = int(r)
    elif isinstance(r, str) and re.fullmatch(r"r\d", r):
        n = int(r[1:])
        return r, 2 + n / 10
    if n is not None and stage != "league":
        if n == 300:
            return "prelim", 0
        if kind == "domestic_cup" and 0 < n < 10:
            return f"r{n}", 2 + n / 10
        if stage == "qualifying" and 0 < n < 10:
            return f"q{n}", n / 10
    if stage == "qualifying":
        return "qualifying", 0
    return (stage if stage in ROUND_DEPTH else None), ROUND_DEPTH.get(stage, 2)


def _round_depth(m: dict, kind: str | None = None) -> float:
    return _round_key(m, kind)[1]


_NOISE = {"fc", "afc", "cf", "sc", "ac", "as", "ss", "fk", "sk", "cd", "ud", "sd", "ca", "club", "de", "the", "1", "calcio",
          "sv", "vfb", "vfl", "tsg", "rcd", "ogc", "sco", "stade", "cr", "ec", "se", "fbc", "bk", "if"}


def _tokens(name: str) -> tuple[str, ...]:
    f = _fold(str(name or "").replace("&", " and "))
    return tuple(w for w in f.split() if w not in _NOISE) or tuple(f.split())


class NameIndex:
    """
    A club's spelling in the archive ("Liverpool FC", "Brighton & Hove Albion")
    against the stores' ("Liverpool", "Brighton"): exact fold, then without club
    affixes, then the one candidate whose words contain (or are contained in) the
    name's. Competition-local names first, then every club seen.
    """

    def __init__(self) -> None:
        self.local: dict[tuple, Any] = {}
        self.fallback: dict[tuple, Any] = {}
        self.registry = None

    def add(self, name, tid) -> None:
        if name and tid is not None:
            self.local.setdefault(_tokens(name), tid)

    def add_fallback(self, name, tid) -> None:
        if name and tid is not None:
            self.fallback.setdefault(_tokens(name), tid)

    @staticmethod
    def _match(toks: tuple, table: dict, loose: bool = True) -> Any:
        if toks in table:
            return table[toks]
        if not loose:
            return None
        s = set(toks)
        if not s:
            return None
        hits = {tid for k, tid in table.items() if k and (s <= set(k) or set(k) <= s)}
        return next(iter(hits)) if len(hits) == 1 else None

    def __call__(self, name) -> Any:
        if not name:
            return None
        names = [name]
        if self.registry:
            try:
                from oddsmarkets.football.sources.teams import normalize_team_name
                names.append(normalize_team_name(name, self.registry))
            except Exception:  # noqa: BLE001
                pass
        # Every exact spelling (the name, the registry's canonical form) before any loose match:
        # "Paris Saint-Germain" is PSG by the registry, not Paris FC by a shared word.
        for table, loose in ((self.local, False), (self.local, True), (self.fallback, False)):
            for nm in names:
                hit = self._match(_tokens(nm), table, loose)
                if hit is not None:
                    return int(hit)
        return None


# ── the build ────────────────────────────────────────────────────────────────

def _iso_date(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def _age(dob: str | None, today: datetime) -> int | None:
    if not dob:
        return None
    try:
        y, m, d = (int(x) for x in dob.split("-"))
    except ValueError:
        return None
    return today.year - y - ((today.month, today.day) < (m, d))


def _r(v, n=2):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, n)


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _write(path: Path, payload: Any) -> None:
    """Write JSON compactly, leaving an unchanged file untouched (deploy diffs stay small)."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _prune(dir_path: Path, keep: set[str]) -> int:
    n = 0
    if dir_path.exists():
        for f in dir_path.glob("*.json"):
            if f.stem not in keep:
                try:
                    f.unlink()
                    n += 1
                except OSError:
                    pass
    return n


class Unified:
    """
    Accumulates every store, one at a time (`add_store`), then writes the
    registries (`finish`). Memory is bounded by the compact appearance rows
    (about 130,000) rather than by the stores.
    """

    def __init__(self, data_dir: Path, seasons_cfg: dict, archive: dict | None = None, past: dict | None = None,
                 squads: dict | None = None, entries: list[dict] | None = None, pool: dict | None = None,
                 today: datetime | None = None) -> None:
        self.data_dir = data_dir
        self.seasons_cfg = seasons_cfg or {}
        self.archive = archive or {}
        self.past = past or {}
        self.squads = squads or {}
        self.entries = {e["slug"]: e for e in entries or [] if e.get("slug")}
        self.pool = pool or {}
        self.today = today or datetime.now(timezone.utc)
        self.comps = competitions()
        self.people: dict[str, dict] = {}            # pid -> identity
        self.apps: dict[str, list[list]] = {}        # pid -> appearance rows
        self.lines: dict[tuple, dict] = {}           # (pid, comp, sid) -> a full season line
        self.clubs: dict[str, dict] = {}             # tid -> identity and accumulators
        self.club_matches: dict[str, list[dict]] = {}
        self.club_seasons: dict[tuple, dict] = {}    # (tid, comp, sid) -> season row
        self.season_meta: dict[tuple, dict] = {}     # (comp, sid) -> {season, era, name}
        self.manifests: dict[str, dict] = {}         # slug -> seasons.json payload
        self.current: dict[str, Any] = {}            # slug -> current season key
        self.era_shift: dict[str, int] = {}          # slug -> label year to season start (split competitions named by a year)
        self.unavailable: dict[str, set[str]] = {}   # slug -> match ids Sofascore has no line-ups for
        self.followed: set[str] = set()              # clubs of the followed leagues' current seasons (the fetch's scope)
        # The model's home/draw/away line per fixture still to play (fixtures.json's, from the fixture's home side).
        self.models: dict[str, dict] = {}
        for e in self.entries.values():
            for f in e.get("_fixtures") or []:
                if f.get("model"):
                    self.models[str(f["id"])] = {k: f["model"][k] for k in ("h", "d", "a") if k in f["model"]}

    # -- one competition --------------------------------------------------------

    def _season_names(self, slug: str) -> dict[str, dict]:
        """sid -> {name, year} from seasons.json, the archive's season lists and the past store."""
        names: dict[str, dict] = {}
        entry = self.seasons_cfg.get(slug) or {}
        tid = entry.get("tournament_id") or self.comps.get(slug, {}).get("tid")
        for s in (self.archive.get("season_lists") or {}).get(str(tid), []) or []:
            names[str(s.get("season_id"))] = {"name": s.get("name"), "year": s.get("year")}
        for sid, s in ((self.archive.get("seasons") or {}).get(slug) or {}).items():
            names.setdefault(str(sid), {"name": s.get("name"), "year": s.get("year")})
        for sid, s in ((self.past.get("seasons") or {}).get(slug) or {}).items():
            names.setdefault(str(sid), {"name": s.get("name"), "year": s.get("year")})
        for s in entry.get("seasons") or []:
            names[str(s.get("season_id"))] = {"name": s.get("name"), "year": s.get("year")}
        return names

    def add_store(self, slug: str, store: dict, current_key: Any = None, torneo: str | None = None) -> None:
        """
        One competition's store. `current_key` is the live season (meta.season_id
        unless given); for Argentina it is "<year>-<torneo>" and the store's
        matches are split into the year's halves.
        """
        comp = self.comps.get(slug)
        if comp is None or not store or not store.get("matches"):
            return
        is_liga = slug == LIGA_ARGENTINA_SLUG
        matches = store.get("matches") or {}
        meta = store.get("meta") or {}
        if current_key is None:
            current_key = meta.get("season_id")
        key_of = (lambda m: liga_season_key(m)) if is_liga else (lambda m: m.get("season_id"))
        names = self._season_names(slug)

        by_season: dict[Any, dict[str, dict]] = {}
        for gid, m in matches.items():
            if not isinstance(m, dict) or m.get("superseded_by"):     # the old copy of a re-listed fixture
                continue
            k = key_of(m)
            if k is None:
                continue
            by_season.setdefault(k, {})[str(gid)] = m
        if current_key is None and by_season:
            current_key = max(by_season, key=lambda k: max(str(m.get("date") or "") for m in by_season[k].values()))
        self.current[slug] = current_key
        if slug in LEAGUES:
            for m in (by_season.get(current_key) or {}).values():
                self.followed.update(n for n in (m.get("home"), m.get("away")) if n)

        def meta_for(k) -> dict:
            if is_liga:
                year, half = str(k).split("-", 1)
                label = f"{half.capitalize()} {year}"
                return {"name": f"Liga Profesional {label}", "season": label, "era": year}
            n = names.get(str(k)) or {}
            season, era = season_label(n.get("name"), n.get("year"))
            if not n.get("name") and str(k) == str(meta.get("season_id")):
                season, era = season_label(meta.get("season_name"), None)
                n = {"name": meta.get("season_name")}
            return {"name": n.get("name") or season, "season": fan_label(slug, season), "era": era, "year": n.get("year")}

        shifts: dict[int, int] = {}
        for k, ms in by_season.items():
            sm = meta_for(k)
            label_era = sm["era"]
            sm["mid"] = _median_date(m.get("date") for m in ms.values())
            sm["era"] = edition_era(slug, label_era, [sm["mid"]] if sm["mid"] else ())
            if re.fullmatch(r"(19|20)\d{2}", str(label_era or "")) and re.fullmatch(r"\d{4}/\d{2}", str(sm["era"])):
                d = int(str(sm["era"])[:4]) - int(label_era)
                shifts[d] = shifts.get(d, 0) + 1
            self.season_meta[(slug, str(k))] = sm
        if shifts:
            self.era_shift[slug] = max(shifts, key=shifts.get)
        # Matches Sofascore has no line-ups for (the fetcher stopped asking): "unavailable", not "to backfill".
        self.unavailable[slug] = {str(g) for g, r in (store.get("detail_missing") or {}).items() if isinstance(r, dict) and r.get("final")}

        # Player identity from the store's metadata (first seen wins; rosters override later).
        for pid, pm in (store.get("players") or {}).items():
            if not isinstance(pm, dict):
                continue
            ident = self.people.setdefault(str(pid), {})
            for src, dst in (("n", "name"), ("sn", "short_name"), ("slug", "slug"), ("pos", "pos"), ("c", "nat"),
                             ("h", "height"), ("no", "shirt")):
                if dst == "shirt" and comp["scope"] == "international":
                    continue
                if pm.get(src) and not ident.get(dst):
                    ident[dst] = pm[src]
            if pm.get("dob") and not ident.get("dob"):
                ident["dob"] = _iso_date(pm["dob"])

        cards = self._cards(store)
        lineups = store.get("lineups") or {}
        self._xg = {}
        for gid, ts in (store.get("team_stats") or {}).items():
            try:
                h, a = (ts or {}).get("home", {}).get("expectedGoals"), (ts or {}).get("away", {}).get("expectedGoals")
                if h is not None and a is not None:
                    self._xg[str(gid)] = (round(float(h), 2), round(float(a), 2))
            except (AttributeError, TypeError, ValueError):
                continue
        for k, ms in by_season.items():
            sid = str(k)
            for gid, m in ms.items():
                self._club_match(slug, comp, sid, gid, m, gid in lineups)
                lineup = lineups.get(gid)
                if isinstance(lineup, dict):
                    self._appearances(slug, sid, gid, m, lineup, cards)

        # Season lines from match detail, for every season but the live one (the
        # live one's lines come from the competition's players_live payload).
        reg = comp["registry"]
        for k, ms in by_season.items():
            if k == current_key:
                continue
            keep = set(ms)
            with_detail = [g for g in keep if g in lineups]
            if not with_detail:
                continue
            view = {key: ({g: v for g, v in store[key].items() if g in keep} if isinstance(store.get(key), dict) else store.get(key))
                    for key in store}
            try:
                players = aggregate_players(view, registry=reg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s %s: season lines failed: %s", slug, k, exc)
                players = []
            if players:
                add_percentiles(players)
                for p in players:
                    self.lines[(str(p["player_id"]), slug, str(k))] = p
        entry = self.entries.get(slug) or {}
        for p in entry.get("_players") or []:
            self.lines[(str(p["player_id"]), slug, str(current_key))] = p

        self._write_seasons(slug, comp, by_season, current_key, lineups)

    def _paged(self, slug: str, sid: str, m: dict) -> bool:
        """Whether a match with line-ups has a match page (build_site_all.has_match_page): the live edition, or the last MATCH_PAGE_DAYS."""
        if str(self.current.get(slug)) == str(sid):
            return True
        return str(m.get("date") or "")[:10] >= (self.today - timedelta(days=MATCH_PAGE_DAYS)).strftime("%Y-%m-%d")

    def _in_fetch_scope(self, slug: str, m: dict) -> bool:
        """
        Whether the hourly fetch asks for this finished match's detail
        (scripts/fetch_sofascore_leagues.py `wants_detail`): a national cup's ties and
        any qualifying round only with a followed club in them. Argentina has its own fetch, which asks for every match.
        """
        if slug == LIGA_ARGENTINA_SLUG:
            return True
        involved = m.get("home") in self.followed or m.get("away") in self.followed
        if str(m.get("stage") or "") in ("qualifying", "other"):
            return involved
        cfg = CUPS.get(slug)
        return involved or cfg is None or getattr(cfg, "detail_scope", "all") != "followed"

    def _cards(self, store: dict) -> dict[tuple[str, str], tuple[int, int]]:
        out: dict[tuple[str, str], list[int]] = {}
        for gid, incs in (store.get("incidents") or {}).items():
            if not isinstance(incs, list):
                continue
            for inc in incs:
                if not isinstance(inc, dict) or str(inc.get("incident_type") or "").lower() != "card" or not inc.get("player_id"):
                    continue
                c = out.setdefault((str(gid), str(inc["player_id"])), [0, 0])
                c[1 if "red" in str(inc.get("incident_class") or "").lower() else 0] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}

    def _club_match(self, slug: str, comp: dict, sid: str, gid: str, m: dict, detail: bool) -> None:
        for side, other in (("home", "away"), ("away", "home")):
            tid = m.get(f"{side}_id")
            if tid is None:
                continue
            t = str(tid)
            club = self.clubs.setdefault(t, {"id": int(tid), "names": {}, "countries": {}, "national": False, "last": ""})
            name = m.get(side)
            d = str(m.get("date") or "")
            club["names"].setdefault(slug, name)
            if d >= club["last"]:
                club["last"] = d
                club["name"] = name
            if _finished(m) and d > club.get("last_played", ""):
                club["last_played"] = d
            ctry = m.get(f"{side}_country")
            if ctry:
                club["countries"][ctry] = club["countries"].get(ctry, 0) + 1
            if comp["scope"] == "international":
                club["national"] = True
            row = {"id": str(gid), "comp": slug, "sid": sid, "date": m.get("date"), "home": 1 if side == "home" else 0,
                   "opp_tid": m.get(f"{other}_id"), "opp": m.get(other), "status": _status(m),
                   "round": m.get("round"), "stage": m.get("stage")}
            if _finished(m):
                gf, ga = (m["hs"], m["as"]) if side == "home" else (m["as"], m["hs"])
                row.update({"gf": gf, "ga": ga, "res": result_string(m, side == "home")})
                if m.get("pens"):
                    row["pens"] = m["pens"] if side == "home" else m["pens"][::-1]
                w = tie_winner(m)
                if w and m.get("stage") == "playoff":
                    row["through"] = 1 if w == name else 0
                xg = (getattr(self, "_xg", None) or {}).get(str(gid))
                if xg:
                    row["xg"] = [xg[0], xg[1]] if side == "home" else [xg[1], xg[0]]
            if detail and self._paged(slug, sid, m):
                row["detail"] = True
            model = self.models.get(str(gid))
            if model and not _finished(m):
                row["model"] = model
            self.club_matches.setdefault(t, []).append({k: v for k, v in row.items() if v is not None})
            cs = self.club_seasons.setdefault((t, slug, sid), _new_cs())
            if _finished(m):
                gf, ga = row["gf"], row["ga"]
                res = "w" if gf > ga else "d" if gf == ga else "l"
                cs["played"] += 1
                if detail:
                    cs["det_n"] += 1
                elif str(gid) in self.unavailable.get(slug, ()):
                    cs["na_n"] += 1
                elif self._in_fetch_scope(slug, m):
                    cs["bf_n"] += 1
                cs["gf"] += gf
                cs["ga"] += ga
                cs[res] += 1
                # A league's table counts its league phase (and a split league's rounds), not its play-offs.
                if str(m.get("stage") or "league") in ("league", "split"):
                    lg = cs["lg"]
                    lg["played"] += 1
                    lg["gf"] += gf
                    lg["ga"] += ga
                    lg[res] += 1
                elif m.get("stage") == "playoff":
                    cs["po_played"] += 1
            key, depth = _round_key(m, comp["kind"])
            if depth > cs["depth"]:
                cs["depth"] = depth
                cs["stage"] = key
            if m.get("round") == "final" and _finished(m) and str(m.get("stage") or "") not in ("qualifying", "other", "split"):
                if tie_winner(m) == name:
                    cs["won_final"] = True
                elif tie_winner(m):
                    cs["lost_final"] = True

    def _appearances(self, slug: str, sid: str, gid: str, m: dict, lineup: dict, cards: dict) -> None:
        date = str(m.get("date") or "")[:10]
        for pid, p in lineup.items():
            if not isinstance(p, dict):
                continue
            s = p.get("s") or {}
            mins = _num(s.get("minutesPlayed"))
            if mins <= 0:
                continue
            team = p.get("t")
            if team == m.get("home"):
                home, tid, opp_tid, opp = 1, m.get("home_id"), m.get("away_id"), m.get("away")
            elif team == m.get("away"):
                home, tid, opp_tid, opp = 0, m.get("away_id"), m.get("home_id"), m.get("home")
            else:
                continue
            res = result_string(m, home)
            yc, rc = cards.get((gid, str(pid)), (0, 0))
            row = [date, gid, slug, sid, tid, opp_tid, opp, home, res, 0 if p.get("sub") else 1,
                   int(mins), int(_num(s.get("goals"))), int(_num(s.get("goalAssist"))),
                   _r(s.get("expectedGoals"), 3), _r(s.get("expectedAssists"), 3), _r(s.get("rating"), 1),
                   int(_num(s.get("totalShots"))), int(_num(s.get("keyPass"))), yc, rc]
            self.apps.setdefault(str(pid), []).append(row)
            ident = self.people.setdefault(str(pid), {})
            if p.get("n") and not ident.get("name"):
                ident["name"] = p["n"]
            if p.get("p") and not ident.get("pos"):
                ident["pos"] = p["p"]

    # -- seasons of one competition ----------------------------------------------

    def _name_to_tid(self, slug: str, by_season: dict) -> "NameIndex":
        """Club name -> team id within one competition: its store, its past results, then every club seen so far."""
        idx = NameIndex()
        for ms in by_season.values():
            for m in ms.values():
                for side in ("home", "away"):
                    idx.add(m.get(side), m.get(f"{side}_id"))
        for pr in ((self.past.get("seasons") or {}).get(slug) or {}).values():
            for m in (pr.get("matches") or {}).values():
                for side in ("home", "away"):
                    idx.add(m.get(side), m.get(f"{side}_id"))
        for tid, rec in (self.squads.get("teams") or {}).items():
            idx.add_fallback((rec or {}).get("name"), tid)
        for tid, c in self.clubs.items():
            for nm in (c.get("names") or {}).values():
                idx.add_fallback(nm, tid)
        idx.registry = self.comps[slug]["registry"]
        return idx

    def _write_seasons(self, slug: str, comp: dict, by_season: dict, current_key: Any, lineups: dict) -> None:
        out_dir = self.data_dir / slug
        rows: list[dict] = []
        name_to_tid = self._name_to_tid(slug, by_season)
        # Qualifying competitions crown no one: their "finals" are play-off ties for a place.
        tbp = self._title_by_playoff(slug)
        crown = (lambda *_a: None) if "qual" in slug else (lambda ms, st, kind: champion_of(ms, st, kind, tbp))
        arch = (self.archive.get("seasons") or {}).get(slug) or {}
        past = (self.past.get("seasons") or {}).get(slug) or {}
        keep_dirs: set[str] = set()

        # Which editions get a row: every store season; an archive season or a past-results
        # season only when it holds something to show (a table, results or leaders).
        present = {str(k) for k in by_season}
        arch_sids = [sid for sid, a in arch.items() if sid not in present and "club friendly" not in str(a.get("name") or "").lower()
                     and (a.get("standings") or a.get("top_players") or ((past.get(sid) or {}).get("matches")))]
        past_sids = [sid for sid, pr in past.items() if sid not in present and sid not in arch and pr.get("matches")]
        shift = self.era_shift.get(slug)
        for sid in arch_sids:
            a = arch[sid]
            season, era = season_label(a.get("name"), a.get("year"))
            mid = _median_date(m.get("date") for m in ((past.get(sid) or {}).get("matches") or {}).values())
            era = edition_era(slug, era, [mid] if mid else (), shift)
            self.season_meta[(slug, sid)] = {"name": a.get("name"), "season": fan_label(slug, season), "era": era, "year": a.get("year"),
                                             "mid": mid}
        for sid in past_sids:
            pr = past[sid]
            season, era = season_label(pr.get("name"), pr.get("year"))
            mid = _median_date(m.get("date") for m in (pr.get("matches") or {}).values())
            era = edition_era(slug, era, [mid] if mid else (), shift)
            self.season_meta[(slug, sid)] = {"name": pr.get("name"), "season": fan_label(slug, season), "era": era, "year": pr.get("year"),
                                             "mid": mid}
        self._settle_labels(slug, sorted(present) + arch_sids + past_sids)

        for k, ms in by_season.items():
            sid = str(k)
            sm = self.season_meta[(slug, sid)]
            if k != current_key:
                ms = _drop_stale(ms)
            mlist = list(ms.values())
            finished = sum(1 for m in mlist if _finished(m))
            detail = sum(1 for g in ms if g in lineups)
            row = {"sid": k, "season": sm["season"], "era": sm["era"], "name": sm["name"],
                   "source": "live" if k == current_key else "store",
                   "path": "" if k == current_key else f"s/{sid}/",
                   "matches": len(mlist), "finished": finished, "detail": detail}
            row.update(_coverage_fields(ms, lineups, self.unavailable.get(slug, set())))
            official = arch.get(sid)
            standings = official_standings(official, name_to_tid) if official and official.get("standings") else []
            computed = compute_standings(mlist, ("league",)) if not standings else []
            if standings and k != current_key:
                standings = merge_records(standings, compute_standings(mlist, ("league",)))
            champ = crown(mlist, standings or computed, comp["kind"]) if finished and (finished == len(mlist) or k != current_key) else None
            if champ and k != current_key:
                row["champion"] = champ
            if k != current_key:
                keep_dirs.add(sid)
                self._write_past_season(out_dir / "s" / sid, slug, comp, sid, sm, mlist, ms, lineups, standings, computed, official,
                                        name_to_tid=name_to_tid)
            self._apply_positions(slug, sid, standings or computed)
            rows.append(row)

        for sid in arch_sids:
            a = arch[sid]
            sm = self.season_meta[(slug, sid)]
            pr = past.get(sid) or {}
            pms = _drop_stale(pr.get("matches") or {})
            mlist = list(pms.values())
            for gid, m in pms.items():
                self._club_match(slug, comp, sid, gid, m, False)
            standings = official_standings(a, name_to_tid) if a.get("standings") else []
            computed = compute_standings(mlist) if not standings and mlist else []
            if standings and mlist:
                standings = merge_records(standings, compute_standings(mlist))
            row = {"sid": int(sid), "season": sm["season"], "era": sm["era"], "name": a.get("name"), "source": "archive",
                   "path": f"s/{sid}/", "matches": len(mlist), "finished": sum(1 for m in mlist if _finished(m)), "detail": 0}
            champ = crown(mlist, standings or computed, comp["kind"])
            if champ:
                row["champion"] = champ
            keep_dirs.add(sid)
            self._write_past_season(out_dir / "s" / sid, slug, comp, sid, sm, mlist, {}, {}, standings, computed, a,
                                    source="archive", name_to_tid=name_to_tid, pms=pms)
            self._apply_positions(slug, sid, standings or computed)
            rows.append(row)
        # Past results without an archive season (the archive list fills first, so rare).
        for sid in past_sids:
            pr = past[sid]
            sm = self.season_meta[(slug, sid)]
            pms = _drop_stale(pr.get("matches") or {})
            mlist = list(pms.values())
            for gid, m in pms.items():
                self._club_match(slug, comp, sid, gid, m, False)
            computed = compute_standings(mlist)
            row = {"sid": int(sid), "season": sm["season"], "era": sm["era"], "name": pr.get("name"), "source": "archive",
                   "path": f"s/{sid}/", "matches": len(mlist), "finished": sum(1 for m in mlist if _finished(m)), "detail": 0}
            champ = crown(mlist, computed, comp["kind"])
            if champ:
                row["champion"] = champ
            keep_dirs.add(sid)
            self._write_past_season(out_dir / "s" / sid, slug, comp, sid, sm, mlist, {}, {}, [], computed, None, source="archive",
                                    name_to_tid=name_to_tid, pms=pms)
            self._apply_positions(slug, sid, computed)
            rows.append(row)

        rows.sort(key=_season_sort, reverse=True)
        # The live season first even when an older edition sorts later (it never should).
        rows.sort(key=lambda r: r["source"] != "live")
        live_ms = list((by_season.get(current_key) or {}).values())
        status = self._status(by_season.get(current_key) or {}, slug)
        winner = crown(live_ms, [], comp["kind"]) if status == "last_edition" else None
        if winner is None and status == "last_edition" and comp["kind"] == "league":
            live_rows = [r for r in rows if r["source"] == "live"]
            winner = crown(live_ms, compute_standings(live_ms), "league") if live_rows else None
        manifest = {"slug": slug, "current": current_key, "status": status, "seasons": rows,
                    "updated_at": self.today.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if winner:
            manifest["winner"] = winner
            for r in rows:
                if r["source"] == "live":
                    r["champion"] = winner
        self.manifests[slug] = manifest
        _write(out_dir / "seasons.json", manifest)
        s_dir = out_dir / "s"
        if s_dir.exists():
            for d in s_dir.iterdir():
                if d.is_dir() and d.name not in keep_dirs:
                    for f in d.glob("*"):
                        f.unlink()
                    d.rmdir()

    def _settle_labels(self, slug: str, sids: list[str]) -> None:
        """Two editions labelled alike (Sofascore names two Trophees des Champions "2026"): label those by their year."""
        by_label: dict[str, list[str]] = {}
        for sid in sids:
            sm = self.season_meta.get((slug, sid)) or {}
            by_label.setdefault(str(sm.get("season")), []).append(sid)
        for label, group in by_label.items():
            if len(group) < 2:
                continue
            for sid in group:
                sm = self.season_meta[(slug, sid)]
                yl = year_label(sm.get("year"))
                if yl and yl[0] != label:
                    sm["season"] = yl[0]
        # Still alike (two Saudi Super Cups both "Super Cup 2024", both year 24/25): the older edition says so.
        again: dict[str, list[str]] = {}
        for sid in sids:
            again.setdefault(str((self.season_meta.get((slug, sid)) or {}).get("season")), []).append(sid)
        for label, group in again.items():
            if len(group) < 2:
                continue
            group.sort(key=lambda x: int(x) if str(x).isdigit() else 0)
            for sid in group[:-1]:
                self.season_meta[(slug, sid)]["season"] = f"{label} (earlier)"

    def _status(self, ms: dict, slug: str | None = None) -> str:
        """
        current, or last_edition: nothing left to play and the edition decided (its
        final played, a super cup's one tie done) or, for a league or a competition
        without a final, its last match long past. A cup between rounds whose next
        ties are not yet scheduled (Copa Argentina, the Intercontinental Cup before
        its December final) stays current.
        """
        if not ms:
            return "current"
        open_ = [m for m in ms.values() if str(m.get("status") or "").lower() in ("notstarted", "inprogress", "live", "scheduled")
                 and str(m.get("date") or "") >= self.today.strftime("%Y-%m-%d")]
        if open_:
            return "current"
        last = max((str(m.get("date") or "") for m in ms.values()), default="")
        if not last:
            return "current"
        try:
            days = (self.today - datetime.strptime(last[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)).days
        except ValueError:
            return "current"
        kind = (self.comps.get(slug or "") or {}).get("kind")
        if slug and "qual" not in slug:
            finals = [m for m in ms.values() if m.get("round") == "final" and _finished(m)
                      and str(m.get("stage") or "") not in ("qualifying", "other", "split")]
            if finals and kind != "league":
                return "last_edition"
            if kind == "super_cup" and all(_finished(m) or _status(m) in ("postponed", "cancelled") for m in ms.values()):
                return "last_edition"
        if kind in ("continental_club", "domestic_cup") or (kind == "international" and slug and "qual" not in slug
                                                            and slug != "friendlies"):
            # A knockout competition without its final in the store: between rounds for months, not over.
            return "last_edition" if days > 120 else "current"
        return "last_edition" if days > 30 else "current"

    def _apply_positions(self, slug: str, sid: str, standings: list[dict]) -> None:
        if slug == "friendlies":
            return
        # A club in several blocks of an official table (Argentina's zone, its annual table and its
        # relegation averages) finished where its own zone or table says, not in an aggregate.
        agg = re.compile(r"promedio|average|anual|annual|relegation", re.I)
        real = {r.get("tid") for r in standings if r.get("tid") is not None and not agg.search(str(r.get("group") or ""))}
        seen: set = set()
        for r in standings:
            tid = r.get("tid")
            if tid is None:
                continue
            if (tid in real and agg.search(str(r.get("group") or ""))) or tid in seen:
                continue
            seen.add(tid)
            cs = self.club_seasons.setdefault((str(tid), slug, sid), _new_cs())
            cs["pos"] = r.get("pos")
            if r.get("played") is not None:
                cs["tbl_played"] = r.get("played")
            if r.get("pts") is not None:
                cs["pts"] = r.get("pts")
            if r.get("group"):
                cs["group"] = r.get("group")
            club = self.clubs.setdefault(str(tid), {"id": int(tid), "names": {}, "countries": {}, "national": False, "last": ""})
            club["names"].setdefault(slug, r.get("team"))
            club.setdefault("name", r.get("team"))

    def _write_past_season(self, d: Path, slug: str, comp: dict, sid: str, sm: dict, mlist: list[dict], ms: dict,
                           lineups: dict, standings: list[dict], computed: list[dict], archive_season: dict | None,
                           source: str = "store", name_to_tid: Callable[[str], Any] = lambda n: None,
                           pms: dict | None = None) -> None:
        fixtures = [_fixture_row(gid, m, gid in lineups and self._paged(slug, sid, m)) for gid, m in ms.items()]
        if not ms and pms:
            fixtures = [_fixture_row(gid, m, False) for gid, m in pms.items()]
        fixtures.sort(key=lambda r: (str(r.get("date") or "9999"), r["id"]))
        bracket = [{k: f.get(k) for k in ("id", "round", "home", "away", "home_id", "away_id", "hs", "as", "winner", "agg_winner", "date")
                    if f.get(k) is not None}
                   for f in fixtures if f.get("stage") == "playoff" and isinstance(f.get("round"), str)]
        payload: dict[str, Any] = {
            "slug": slug, "sid": int(sid) if str(sid).isdigit() else sid, "season": sm["season"], "era": sm["era"],
            "name": sm["name"], "source": source,
            "standings": standings or computed, "standings_source": "official" if standings else "computed",
        }
        groups = sorted({r["group"] for r in (standings or computed) if r.get("group")})
        if groups:
            payload["groups"] = groups
        if fixtures:
            payload["fixtures"] = fixtures
        fin = [f for f in fixtures if f.get("status") == "finished"]
        with_lineups = sum(1 for f in fin if f["id"] in lineups)
        # Player lines cover the finished matches with line-ups: "partial" tells the page to say so.
        payload["coverage"] = coverage_flag(with_lineups, len(fin)) if fin else COVERAGE_NONE
        if bracket:
            payload["bracket"] = bracket
        players = [p for (pid, c, s), p in self.lines.items() if c == slug and s == sid]
        if players:
            payload["players"] = [{k: v for k, v in p.items() if v is not None} for p in sorted(players, key=lambda p: -(p.get("minutes") or 0))]
            payload["metrics"] = METRICS
            payload["detail_matches"] = with_lineups
            payload["leaders"] = _leaders_from_players(players, name_to_tid)
        if archive_season and archive_season.get("top_players"):
            payload["leaders"] = {**payload.get("leaders", {}), **_leaders_from_archive(archive_season["top_players"], name_to_tid)}
        _write(d / "season.json", payload)

    # -- the registries ---------------------------------------------------------

    def _roster_index(self) -> tuple[dict[str, tuple[str, str]], set[str]]:
        """pid -> (tid, fetched_at) of the most recently fetched squad that lists him; the set of tids with a squad."""
        out: dict[str, tuple[str, str]] = {}
        teams = (self.squads.get("teams") or {})
        for tid, rec in teams.items():
            stamp = str(rec.get("fetched_at") or "")
            for p in rec.get("players") or []:
                pid = str(p.get("id"))
                if pid not in out or stamp > out[pid][1]:
                    out[pid] = (str(tid), stamp)
        return out, set(teams)

    def _roster_rows(self, roster: dict) -> dict[str, dict]:
        """pid -> his row in the squad that counts for him (the one `_roster_index` picked): market value, contract."""
        teams = self.squads.get("teams") or {}
        out: dict[str, dict] = {}
        for pid, (tid, _stamp) in roster.items():
            for p in (teams.get(tid) or {}).get("players") or []:
                if str(p.get("id")) == pid:
                    out[pid] = p
                    break
        return out

    def current_club(self, pid: str, apps: list[list], roster: dict, rostered: set[str]) -> dict | None:
        """The rules in UNIFIED_PAYLOADS.md section 2.3."""
        club_apps = [a for a in apps if self.comps.get(a[2], {}).get("scope") == "club" and a[4] is not None]
        last = max(club_apps, key=lambda a: a[0]) if club_apps else None
        last_date, last_tid = (last[0], str(last[4])) if last else ("", None)
        hit = roster.get(pid)
        if hit:
            tid, stamp = hit
            # A roster fetched before a later appearance for another club is out of date for him.
            if not (last_tid and last_tid != tid and last_date > stamp[:10]):
                return {"tid": int(tid), "source": "roster", "as_of": stamp[:10]}
        prof = (self.squads.get("people") or {}).get(pid)
        arch = ((self.archive.get("players") or {}).get(pid) or {})
        for p, stamp in ((prof, (prof or {}).get("fetched_at")), (arch.get("details"), arch.get("fetched_at"))):
            if not p or str(stamp or "")[:10] < last_date:
                continue
            # Sofascore's placeholder club for a free agent or a retired player.
            if not p.get("team_id") or str(p.get("team") or "").strip().lower() == "no team":
                return None
            return {"tid": int(p["team_id"]), "name": p.get("team"), "source": "profile", "as_of": str(stamp)[:10]}
        if last_tid and last_tid not in rostered:
            return {"tid": int(last_tid), "source": "appearances", "as_of": last_date}
        return None

    def finish(self) -> dict[str, int]:
        roster, rostered = self._roster_index()
        squads_teams = self.squads.get("teams") or {}
        # Roster identity: the freshest source of name, position, date of birth.
        for tid, rec in squads_teams.items():
            for p in rec.get("players") or []:
                ident = self.people.setdefault(str(p.get("id")), {})
                for src, dst in (("n", "name"), ("sn", "short_name"), ("pos", "pos"), ("c", "nat"), ("h", "height"), ("no", "shirt")):
                    if p.get(src):
                        ident[dst] = p[src]
                if p.get("dob"):
                    ident["dob"] = _iso_date(p["dob"])
        tslug = tournament_slugs()
        today = self.today
        people_dir = self.data_dir / "people"
        clubs_dir = self.data_dir / "clubs"
        index_rows: list[list] = []
        club_of: dict[str, dict | None] = {}
        nt_of: dict[str, tuple[str, str]] = {}
        written: set[str] = set()
        archive_players = self.archive.get("players") or {}
        listed = {str(p.get("player_id")) for e in self.entries.values() for p in (e.get("_players") or []) if p.get("player_id")}
        for e in self.entries.values():
            intl = (self.comps.get(e.get("slug") or "") or {}).get("scope") == "international"
            for p in e.get("_players") or []:
                ident = self.people.setdefault(str(p.get("player_id")), {})
                for src, dst in (("name", "name"), ("short_name", "short_name"), ("position", "pos"), ("country", "nat"),
                                 ("height", "height"), ("shirt", "shirt")):
                    if dst == "shirt" and intl:
                        continue
                    if p.get(src) and not ident.get(dst):
                        ident[dst] = p[src]
                # A goalkeeper whose line-ups carry no position still makes saves.
                if not ident.get("pos") and (p.get("is_gk") or (p.get("saves") or 0) >= 3):
                    ident["pos"] = "G"
        all_pids = set(self.apps) | {p for p in archive_players if (archive_players[p] or {}).get("details")} | set(roster) | listed
        roster_row = self._roster_rows(roster)
        self.frame_of_person: dict[str, str] = {}

        for pid in all_pids:
            apps = sorted(self.apps.get(pid, []), key=lambda a: (a[0], a[1]), reverse=True)
            ident = dict(self.people.get(pid) or {})
            det = (archive_players.get(pid) or {}).get("details") or {}
            for src, dst in (("name", "name"), ("short_name", "short_name"), ("slug", "slug"), ("position", "pos"),
                             ("country", "nat"), ("height", "height"), ("shirt", "shirt")):
                if det.get(src) and not ident.get(dst):
                    ident[dst] = det[src]
            if det.get("dob") and not ident.get("dob"):
                ident["dob"] = _iso_date(det["dob"])
            if not ident.get("name"):
                continue
            cc = self.current_club(pid, apps, roster, rostered)
            if cc:
                cc["name"] = (self.clubs.get(str(cc["tid"])) or {}).get("name") or cc.get("name") or \
                    (squads_teams.get(str(cc["tid"])) or {}).get("name")
            club_of[pid] = cc
            intl = [a for a in apps if self.comps.get(a[2], {}).get("scope") == "international" and a[4] is not None]
            nt = None
            if intl:
                nt_tid = str(intl[0][4])
                nt = {"tid": int(nt_tid), "name": (self.clubs.get(nt_tid) or {}).get("name")}
                nt_of[pid] = (nt_tid, intl[0][0])
            arch_seasons = sorted((archive_players.get(pid) or {}).get("seasons") or [], key=lambda e: sort_key({"year": e.get("year")}),
                                  reverse=True)
            frame = person_frame([a[2] for a in apps if self.comps.get(a[2], {}).get("scope") == "club"],
                                 [e.get("year") for e in arch_seasons])
            self.frame_of_person[pid] = frame
            seasons = self._person_seasons(pid, apps, frame)
            for s in seasons:
                if s["scope"] == "club":
                    s["current"] = bool(cc and str(cc["tid"]) == str(s["tid"]))
                else:
                    s["current"] = bool(nt and str(nt["tid"]) == str(s["tid"]))
            arch_rows = self._person_archive(pid, seasons, tslug, frame)
            years = season_totals(seasons + arch_rows)
            # A career list the old cap cut short: the season it stopped in, and every older one, may miss
            # competitions (the backfill lists it again); those years say so instead of reading "full".
            cut = self.career_cut(pid, tslug, frame)
            if cut:
                for y in years:
                    if era_key(y["era"]) <= era_key(cut):
                        y["coverage"], y["gap"] = COVERAGE_PARTIAL, "career"
            comps_used = {a[2] for a in apps} | {r["comp"] for r in arch_rows if r.get("comp")}
            teams = {}
            for a in apps:
                for t, nm in ((a[4], None), (a[5], a[6])):
                    if t is None or str(t) in teams:
                        continue
                    c = self.clubs.get(str(t)) or {}
                    # The crest path is derived from the id on the page (assets/crests/<tid>.png), and
                    # "national" is written only when true: both were repeated in every file.
                    teams[str(t)] = {"name": c.get("name") or nm}
                    if c.get("national"):
                        teams[str(t)]["national"] = True
            payload = {
                "id": pid, **{k: ident[k] for k in ("name", "short_name", "slug", "pos", "nat", "dob", "height", "shirt") if ident.get(k)},
            }
            age = _age(ident.get("dob"), today)
            if age is not None:
                payload["age"] = age
            if cc:
                payload["current_club"] = cc
            if nt:
                payload["national_team"] = nt
            payload.update(_market_fields(roster_row.get(pid), det))
            payload["frame"] = frame
            payload["comps"] = {s: {"name": self.comps[s]["short"], "kind": self.comps[s]["kind"], "scope": self.comps[s]["scope"]}
                                for s in sorted(comps_used) if s in self.comps}
            payload["teams"] = teams
            payload["apps_fields"] = APPS_FIELDS
            payload["apps"] = apps
            payload["seasons"] = seasons
            if arch_rows:
                payload["archive"] = arch_rows
            if cut:
                payload["career_gap"] = {"through": cut}
            payload["years"] = years
            _write(people_dir / f"{pid}.json", payload)
            written.add(pid)
            # "min" is the minutes of his current season in his own frame, every competition: the same
            # number as his page's row for that season (a European's 2026/27, a Brazilian's 2026).
            season_now = current_era(frame, today)
            now_row = next((y for y in years if y["era"] == season_now), None)
            index_rows.append([pid, ident.get("name"), ident.get("pos"), ident.get("nat"), ident.get("dob"),
                               cc["tid"] if cc else None, cc.get("name") if cc else None,
                               nt["tid"] if nt else None, nt["name"] if nt else None,
                               sorted(comps_used, key=lambda s: -sum(a[10] for a in apps if a[2] == s)),
                               now_row["min"] if now_row else 0, apps[0][0] if apps else None, season_now,
                               payload.get("mv")])
        pruned = _prune(people_dir, written)
        index_rows.sort(key=lambda r: (-(r[10] or 0), r[1] or ""))
        _write(self.data_dir / "people_index.json", {
            "fields": ["id", "name", "pos", "nat", "dob", "club_tid", "club", "nt_tid", "nt", "comps", "min", "last", "season", "mv"],
            "rows": index_rows, "updated_at": today.strftime("%Y-%m-%dT%H:%M:%SZ")})
        n_clubs = self._write_clubs(clubs_dir, club_of, nt_of, roster, rostered)
        self.club_of = club_of
        logger.info("unified: %d people (%d pruned), %d clubs", len(written), pruned, n_clubs)
        return {"people": len(written), "clubs": n_clubs}

    def app_era(self, a: list, frame: str) -> str | None:
        """
        The season an appearance counts in: its edition's for club football; for
        international football the date in the player's own frame (a European's
        September qualifier is 2026/27, a Brazilian's is 2026).
        """
        if self.comps.get(a[2], {}).get("scope") == "international" or a[2] in NEUTRAL_COMPETITIONS:
            return frame_era(frame, a[0], INTL_SPLIT_START_MONTH)
        return (self.season_meta.get((a[2], a[3])) or {}).get("era")

    def _person_seasons(self, pid: str, apps: list[list], frame: str = "split") -> list[dict]:
        """One row per (competition, edition, team, season): the season x competition table."""
        acc: dict[tuple, dict] = {}
        for a in apps:
            key = (a[2], a[3], a[4], self.app_era(a, frame))
            r = acc.setdefault(key, {"apps": 0, "starts": 0, "min": 0, "g": 0, "a": 0, "xg": 0.0, "xa": 0.0, "_rw": 0.0, "_rm": 0.0,
                                     "sh": 0, "kp": 0, "yc": 0, "rc": 0})
            r["apps"] += 1
            r["starts"] += a[9]
            r["min"] += a[10]
            r["g"] += a[11]
            r["a"] += a[12]
            r["xg"] += a[13] or 0.0
            r["xa"] += a[14] or 0.0
            if a[15] is not None:
                r["_rw"] += a[15] * a[10]
                r["_rm"] += a[10]
            r["sh"] += a[16]
            r["kp"] += a[17]
            r["yc"] += a[18]
            r["rc"] += a[19]
        out = []
        for (comp, sid, tid, era), r in acc.items():
            c = self.comps.get(comp, {})
            sm = self.season_meta.get((comp, sid)) or {}
            row = {"comp": comp, "kind": c.get("kind"), "scope": c.get("scope"), "sid": int(sid) if str(sid).isdigit() else sid,
                   "season": sm.get("season"), "era": era or sm.get("era"), "tid": tid,
                   "team": (self.clubs.get(str(tid)) or {}).get("names", {}).get(comp) or (self.clubs.get(str(tid)) or {}).get("name"),
                   "source": self._row_source(comp, str(sid)),
                   "apps": r["apps"], "starts": r["starts"], "min": r["min"], "g": r["g"], "a": r["a"],
                   "xg": round(r["xg"], 2), "xa": round(r["xa"], 2), "sh": r["sh"], "kp": r["kp"], "yc": r["yc"], "rc": r["rc"]}
            if r["_rm"] > 0:
                row["rt"] = round(r["_rw"] / r["_rm"], 2)
            # Coverage: how many of the team's finished matches in this edition have line-ups. A player's
            # minutes can only be counted where they do, so "partial" means the row is a lower bound.
            cs = self.club_seasons.get((str(tid), comp, str(sid))) or {}
            fin, det = int(cs.get("played") or 0), int(cs.get("det_n") or 0)
            row["coverage"] = coverage_flag(det, fin)
            if row["coverage"] != COVERAGE_FULL:
                row["cov"] = [det, fin]
                row["gap"] = _gap(cs)
            line = self.lines.get((pid, comp, str(sid))) if PERSON_LINES else None
            if line and r["min"] >= LINE_MIN_MINUTES and abs(_num(line.get("minutes")) - r["min"]) <= max(10, 0.05 * r["min"]) and (
                    line.get("team") in (None, row["team"]) or len([1 for k in acc if k[0] == comp and k[1] == sid]) == 1):
                row["line"] = {k: v for k, v in line.items() if v is not None and k not in LINE_DROP}
            out.append(row)
        out.sort(key=lambda r: (era_key(r.get("era") or ""), r["min"]), reverse=True)
        return out

    ARCHIVE_KEYS = (("apps", "apps"), ("starts", "starts"), ("minutes", "min"), ("goals", "g"), ("assists", "a"),
                    ("xg", "xg"), ("xa", "xa"), ("rating", "rt"))

    def _person_archive(self, pid: str, seasons: list[dict], tslug: dict[int, str], frame: str = "split") -> list[dict]:
        """
        The archive's season totals (Sofascore's per-player season statistics) for the
        editions no store holds; and, for an edition a store holds only in part (a
        partial line-up record), the season totals in place of the store row's sums
        when they are larger, the row then saying `coverage: "totals"`. Matched on
        the edition's id, so a row is never counted twice.
        """
        rec = (self.archive.get("players") or {}).get(pid) or {}
        by_sid: dict[tuple, list[dict]] = {}
        for r in seasons:
            by_sid.setdefault((r["comp"], str(r.get("sid"))), []).append(r)
        have = {(r["comp"], r.get("season")) for r in seasons}
        out = []
        for e in rec.get("seasons") or []:
            if e.get("empty"):
                continue
            row = season_row(e)
            slug = tslug.get(int(e.get("tid") or 0))
            sid = str(e.get("sid")) if e.get("sid") is not None else None
            season, era = season_label(e.get("sname"), e.get("year"))
            season = fan_label(slug, season)
            if slug and sid and (slug, sid) in by_sid:
                same = by_sid[(slug, sid)]
                mins = _num(row.get("minutes"))
                if len(same) == 1 and same[0].get("coverage") not in (None, COVERAGE_FULL) and mins > same[0]["min"]:
                    r0 = same[0]
                    r0["lineups"] = {"apps": r0["apps"], "min": r0["min"]}
                    for src, dst in self.ARCHIVE_KEYS:
                        if row.get(src) is not None:
                            r0[dst] = row[src]
                    r0["coverage"] = COVERAGE_TOTALS
                    r0.pop("gap", None)
                continue
            if slug and not sid and (slug, season) in have:
                continue
            kind = self._archive_kind(e, slug)
            era = self._archive_era(e, slug, sid, season, era, kind, frame)
            # The archive spells a club its own way ("Inter Miami CF", "Paris Saint-Germain"): the club's id and name when one club matches.
            team, team_tid = e.get("team"), None
            t = self._archive_club(team, slug, kind == "international")
            if t is not None:
                team_tid, team = int(t), (self.clubs.get(t) or {}).get("name") or team
            out.append({"comp": slug, "tournament": e.get("tname"), "kind": kind,
                        "scope": "international" if kind == "international" else "club",
                        "season": season, "era": era, "team": team, **({"tid": team_tid} if team_tid is not None else {}),
                        **({"sid": int(sid) if sid.isdigit() else sid} if sid else {}),
                        **{dst: row[src] for src, dst in self.ARCHIVE_KEYS if row.get(src) is not None},
                        "coverage": COVERAGE_TOTALS, "source": "archive"})
        out.sort(key=lambda r: era_key(r.get("era") or ""), reverse=True)
        return out

    def _archive_kind(self, e: dict, slug: str | None) -> str:
        c = self.comps.get(slug or "", {})
        return c.get("kind") or ("international" if int(e.get("tid") or 0) in (16, 1, 133, 270, 246, 140) else "league")

    def _archive_era(self, e: dict, slug: str | None, sid: str | None, season: str | None, era: str | None, kind: str,
                     frame: str) -> str | None:
        """The season an archive entry counts in, in the player's frame."""
        sm = self.season_meta.get((slug, sid)) if slug and sid else None
        if kind == "international":
            mid = (sm or {}).get("mid")
            # No dates for an edition no store holds: a tournament named for a year closes the
            # split season ending that year (June and July), or is that calendar year.
            y = re.search(r"(?:19|20)\d{2}", str(season or e.get("year") or ""))
            return frame_era(frame, mid, INTL_SPLIT_START_MONTH) if mid else (
                (f"{int(y.group(0)) - 1}/{int(y.group(0)) % 100:02d}" if frame == "split" else y.group(0)) if y else era)
        if sm and sm.get("era"):
            return sm["era"]
        if slug:
            return edition_era(slug, era, (), self.era_shift.get(slug))
        return era

    # The fetcher's old rule cut a career's season list at this many rows, newest first, so it could end
    # mid-season (Mbappe's list stopped at the Champions League 2023/24, without Ligue 1 or anything
    # older). A list it chose and filled to the cap is read as cut; the fetcher lists it again
    # (scripts/fetch_sofascore_history.py: needs_relist) and stamps the new rule.
    LEGACY_LIST_CAP = 12
    LIST_RULE = 2

    def career_cut(self, pid: str, tslug: dict[int, str], frame: str = "split") -> str | None:
        """The oldest season of a career list the old cap cut short (that season and older may miss competitions), else None."""
        rec = (self.archive.get("players") or {}).get(pid) or {}
        listed = rec.get("season_list") or []
        if rec.get("list_rule") == self.LIST_RULE or len(listed) < self.LEGACY_LIST_CAP:
            return None
        eras = []
        for e in listed:
            slug = tslug.get(int(e.get("tid") or 0))
            sid = str(e.get("sid")) if e.get("sid") is not None else None
            season, era = season_label(e.get("sname"), e.get("year"))
            era = self._archive_era(e, slug, sid, fan_label(slug, season), era, self._archive_kind(e, slug), frame)
            if era:
                eras.append(era)
        return min(eras, key=era_key) if eras else None

    def _archive_club(self, team: str | None, slug: str | None, international: bool) -> str | None:
        """
        The one club (or national team) an archive spelling names: its folded words, else the
        competitions' registries' canonical form ("Paris Saint-Germain" -> "PSG"), narrowed to the
        clubs of that competition when several match. None when it stays ambiguous.
        """
        if not team:
            return None
        tok = self._club_tokens()
        kind_ok = lambda t: bool((self.clubs.get(t) or {}).get("national")) == international  # noqa: E731
        cands = {t for t in tok.get(_tokens(team), set()) if kind_ok(t)}
        if len(cands) != 1:
            from oddsmarkets.football.sources.teams import normalize_team_name

            regs = [(self.comps.get(slug or "") or {}).get("registry")] + [c.get("registry") for c in self.comps.values()]
            more: set = set()
            for reg in dict.fromkeys(r for r in regs if r):
                try:
                    nm = normalize_team_name(team, reg)
                except Exception:  # noqa: BLE001
                    continue
                if nm and nm != team:
                    more |= {t for t in tok.get(_tokens(nm), set()) if kind_ok(t)}
            if more:
                cands = more
        if len(cands) > 1 and slug:
            inside = {t for t in cands if slug in ((self.clubs.get(t) or {}).get("names") or {})}
            if inside:
                cands = inside
        return next(iter(cands)) if len(cands) == 1 else None

    def _club_tokens(self) -> dict[tuple, set]:
        """Every club's and national team's spellings (folded, without club affixes) -> ids."""
        if not hasattr(self, "_ctok"):
            self._ctok: dict[tuple, set] = {}
            for tid, c in self.clubs.items():
                for nm in set(list((c.get("names") or {}).values()) + [c.get("name")]):
                    if nm:
                        self._ctok.setdefault(_tokens(nm), set()).add(tid)
        return self._ctok

    def _write_clubs(self, clubs_dir: Path, club_of: dict, nt_of: dict, roster: dict, rostered: set[str]) -> int:
        squads_teams = self.squads.get("teams") or {}
        pool_by_tid = {str(c.get("team_id")): c for c in (self.pool.get("clubs") or []) if c.get("team_id")}
        strength: dict[tuple[str, str], dict] = {}
        team_ids: dict[tuple[str, str], Any] = {}
        for slug, e in self.entries.items():
            for t, info in (e.get("_teams") or {}).items():
                team_ids[(slug, t)] = (info or {}).get("team_id")
            for r in e.get("_strength") or []:
                tid = team_ids.get((slug, r.get("team")))
                if tid:
                    strength[(str(tid), slug)] = r
        home_league: dict[str, str] = {}
        for (tid, slug, sid), _cs in self.club_seasons.items():
            if self.comps.get(slug, {}).get("kind") == "league" and str(self.current.get(slug)) == sid:
                home_league[tid] = slug
        for (tid, slug, sid), _cs in self.club_seasons.items():
            if tid not in home_league and self.comps.get(slug, {}).get("kind") == "league":
                home_league[tid] = slug
        # Squads without a roster: the players whose current club this is.
        by_club: dict[str, list[str]] = {}
        for pid, cc in club_of.items():
            if cc:
                by_club.setdefault(str(cc["tid"]), []).append(pid)
        last_nt_match = {t: c.get("last_played") or c.get("last", "") for t, c in self.clubs.items() if c.get("national")}
        by_nt: dict[str, list[str]] = {}
        for pid, (tid, d) in nt_of.items():
            lm = last_nt_match.get(tid, "")[:10]
            try:
                gap = (datetime.strptime(lm, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days if lm and d else 9999
            except ValueError:
                gap = 9999
            if gap <= NATIONAL_SQUAD_DAYS:
                by_nt.setdefault(tid, []).append(pid)

        index_rows = []
        written: set[str] = set()
        for tid, club in self.clubs.items():
            if not club.get("name"):
                continue
            national = bool(club.get("national"))
            country = max(club["countries"], key=club["countries"].get) if club["countries"] else None
            seasons = []
            for (t, slug, sid), cs in self.club_seasons.items():
                if t != tid:
                    continue
                c = self.comps.get(slug, {})
                sm = self.season_meta.get((slug, sid)) or {}
                era = sm.get("era")
                if slug in NEUTRAL_COMPETITIONS and not national and sm.get("mid"):
                    era = frame_era(frame_of(home_league.get(tid)), sm["mid"], INTL_SPLIT_START_MONTH) or era
                row = {"comp": slug, "kind": c.get("kind"), "scope": c.get("scope"), "sid": int(sid) if str(sid).isdigit() else sid,
                       "season": sm.get("season"), "era": era,
                       "source": self._row_source(slug, sid)}
                kind = c.get("kind")
                # A league row is its table: the league phase (play-offs and relegation ties apart).
                rec = cs["lg"] if kind == "league" and cs["lg"]["played"] else cs
                if kind == "league" and cs.get("tbl_played") and rec["played"] and rec["played"] != cs["tbl_played"]:
                    # Part of a season's results beside its full official table: the table's games, no partial record.
                    rec = {"played": 0}
                if rec["played"]:
                    for k in ("played", "w", "d", "l", "gf", "ga"):
                        row[k] = rec[k]
                elif cs.get("tbl_played"):
                    # An archive season: the table's games, no record (the archive has none).
                    row["played"] = cs["tbl_played"]
                for k in ("pos", "group", "pts"):
                    if cs.get(k) is not None:
                        row[k] = cs[k]
                if kind != "league" or (self._title_by_playoff(slug) and cs["po_played"]):
                    if "qual" in slug:
                        # A qualifying competition's "final" is a play-off for a place: won, the team qualified.
                        stage = "qualified" if cs.get("won_final") else "po-final" if cs.get("lost_final") else cs.get("stage")
                    else:
                        stage = "winner" if cs.get("won_final") else "runner-up" if cs.get("lost_final") else cs.get("stage")
                    if stage:
                        row["stage"] = stage
                if row["source"] == "live":
                    st = strength.get((tid, slug))
                    if st:
                        row["rating"] = {k: st.get(k) for k in ("attack", "defence", "elo", "strength_ppg") if st.get(k) is not None}
                if row["source"] in ("live", "store") and cs["played"]:
                    # Player data for the club's matches in this edition: "partial" when some lack line-ups.
                    row["coverage"] = coverage_flag(cs["det_n"], cs["played"])
                    if row["coverage"] != COVERAGE_FULL:
                        row["cov"] = [cs["det_n"], cs["played"]]
                        row["gap"] = _gap(cs)
                seasons.append(row)
            seasons.sort(key=lambda r: (era_key(r.get("era") or ""), r["comp"]), reverse=True)
            club_eras = [r["era"] for r in seasons if r.get("source") in ("live", "store") and r.get("era")]
            era_now = max(club_eras, key=era_key) if club_eras else None
            if tid in squads_teams and not national:
                rec = squads_teams[tid]
                members = [(str(p["id"]), p) for p in rec.get("players") or []]
                source, as_of = "roster", str(rec.get("fetched_at") or "")[:10]
            else:
                ids = by_nt.get(tid, []) if national else by_club.get(tid, [])
                members = [(pid, {}) for pid in ids]
                source, as_of = "appearances", (club.get("last_played") or club.get("last") or "")[:10]
            players = []
            for pid, rp in members:
                ident = self.people.get(pid) or {}
                apps = [a for a in self.apps.get(pid, []) if str(a[4]) == tid and
                        (self.season_meta.get((a[2], a[3])) or {}).get("era") == era_now]
                row = {"id": pid, "name": rp.get("n") or ident.get("name"), "pos": rp.get("pos") or ident.get("pos"),
                       "shirt": rp.get("no") or ident.get("shirt"), "nat": rp.get("c") or ident.get("nat"),
                       "dob": _iso_date(rp["dob"]) if rp.get("dob") else ident.get("dob"), "height": rp.get("h") or ident.get("height")}
                age = _age(row["dob"], self.today)
                if age is not None:
                    row["age"] = age
                for k, v in _market_fields(rp, None).items():
                    if k != "foot":
                        row[k] = v
                if apps:
                    mins = sum(a[10] for a in apps)
                    rw = sum((a[15] or 0) * a[10] for a in apps if a[15] is not None)
                    rm = sum(a[10] for a in apps if a[15] is not None)
                    row.update({"apps": len(apps), "min": mins, "g": sum(a[11] for a in apps), "a": sum(a[12] for a in apps)})
                    if rm:
                        row["rt"] = round(rw / rm, 2)
                players.append({k: v for k, v in row.items() if v is not None})
            pos_order = {"G": 0, "D": 1, "M": 2, "F": 3}
            players.sort(key=lambda r: (pos_order.get(r.get("pos"), 4), -(r.get("min") or 0), r.get("name") or ""))
            matches = sorted(self.club_matches.get(tid, []), key=lambda r: (str(r.get("date") or ""), r["id"]), reverse=True)
            # Seen twice (a club in two stores' copies of one match, e.g. a seeded store): keep one.
            seen: set[str] = set()
            matches = [m for m in matches if not (m["id"] in seen or seen.add(m["id"]))]
            payload = {"id": int(tid), "name": club["name"], "slug": _slugify(club["name"]), "country": country,
                       "national": national, "names": club["names"]}
            # Only a crest that is on disk (the public build ships none: docs/HOSTING_MIGRATION.md, D6).
            if not national and (self.data_dir.parent / "assets" / "crests" / f"{tid}.png").exists():
                payload["crest"] = f"assets/crests/{tid}.png"
            if tid in home_league:
                payload["home"] = home_league[tid]
            payload["squad"] = {"source": source, "as_of": as_of, "era": era_now, "players": players}
            payload["seasons"] = seasons
            payload["years"] = club_season_totals(seasons)
            payload["matches"] = matches
            pc = pool_by_tid.get(tid)
            if pc and not national:
                payload["pool"] = {"strength": pc.get("strength"), "rank": pc.get("rank"), "comp": pc.get("comp")}
            _write(clubs_dir / f"{tid}.json", payload)
            written.add(tid)
            comps_used = sorted({r["comp"] for r in seasons if r.get("source") in ("live", "store")},
                                key=lambda s: (self.comps.get(s, {}).get("kind") != "league", s))
            index_rows.append([int(tid), club["name"], _slugify(club["name"]), country, 1 if national else 0,
                               payload.get("crest"), home_league.get(tid), comps_used])
        _prune(clubs_dir, written)
        index_rows.sort(key=lambda r: (r[4], r[6] is None, r[1] or ""))
        _write(self.data_dir / "clubs_index.json", {
            "fields": ["id", "name", "slug", "country", "national", "crest", "home", "comps"], "rows": index_rows,
            "updated_at": self.today.strftime("%Y-%m-%dT%H:%M:%SZ")})
        return len(written)

    def _title_by_playoff(self, slug: str) -> bool:
        """A league that crowns its champion in a play-off (Liga MX, MLS, the Argentine torneos)."""
        if slug == LIGA_ARGENTINA_SLUG:
            return True
        cfg = LEAGUES.get(slug)
        return bool(cfg is not None and getattr(cfg, "playoff", None) is not None)

    def _row_source(self, comp: str, sid: str) -> str:
        """live (the edition in progress), store (a finished edition the stores hold) or archive."""
        if str(self.current.get(comp)) == sid:
            return "live" if (self.manifests.get(comp) or {}).get("status", "current") == "current" else "store"
        return "store" if (comp, sid) in self._store_seasons() else "archive"

    def _store_seasons(self) -> set[tuple[str, str]]:
        if not hasattr(self, "_ss"):
            self._ss = {(slug, str(r["sid"])) for slug, man in self.manifests.items() for r in man["seasons"]
                        if r["source"] in ("live", "store")}
        return self._ss

    def mark_departed(self) -> int:
        """
        players_live.json of every club competition: `current` on each row, true
        when the player's current club is the club the row is for. A player who
        has left keeps his line (his minutes there are real) and is marked.
        """
        changed = 0
        club_of = getattr(self, "club_of", {})
        for slug, e in self.entries.items():
            if self.comps.get(slug, {}).get("scope") != "club":
                continue
            path = self.data_dir / slug / "players_live.json"
            if not path.exists():
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            tids = {t: (info or {}).get("team_id") for t, info in (e.get("_teams") or {}).items()}
            for p in doc.get("players") or []:
                cc = club_of.get(str(p.get("player_id")))
                tid = tids.get(p.get("team"))
                p["current"] = bool(cc and tid is not None and str(cc["tid"]) == str(tid))
            _write(path, doc)
            changed += 1
        return changed

    def competition_fields(self) -> dict[str, dict]:
        """Per competition, the keys competitions.json carries (UNIFIED_PAYLOADS.md 1.1)."""
        out = {}
        for slug, c in self.comps.items():
            man = self.manifests.get(slug)
            fields = {"kind_u": c["kind"], "scope": c["scope"]}
            if man:
                live = next((r for r in man["seasons"] if r["source"] == "live"), None)
                if live:
                    fields["current_season"] = {"sid": live["sid"], "season": live["season"], "era": live["era"],
                                                "status": man["status"]}
                if man.get("winner"):
                    fields["winner"] = man["winner"]
                fields["seasons"] = [{k: r[k] for k in ("sid", "season", "era", "source")} for r in man["seasons"]]
            out[slug] = fields
        return out


def season_totals(rows: list[dict]) -> list[dict]:
    """
    Year by year: one row per season key (`era`) summing every season x competition
    row in it (store rows and archive rows alike), with the international part
    (`intl`; the club part is the rest) and the club teams by minutes. Built from the
    rows themselves, so the competitions always add up to the season. `coverage` is
    "partial" when any row in it is a lower bound. Zero xG, xA and starts are left out.
    """
    by: dict[str, dict] = {}
    for r in rows:
        era = r.get("era")
        if not era:
            continue
        y = by.setdefault(era, {"era": era, "rows": 0, "apps": 0, "starts": 0, "min": 0, "g": 0, "a": 0, "xg": 0.0, "xa": 0.0,
                                "_rw": 0.0, "_rm": 0, "intl": {"apps": 0, "min": 0, "g": 0, "a": 0}, "_teams": {},
                                "coverage": COVERAGE_FULL})
        y["rows"] += 1
        for k in ("apps", "min", "g", "a"):
            v = int(_num(r.get(k)))
            y[k] += v
            if r.get("scope") == "international":
                y["intl"][k] += v
        y["starts"] += int(_num(r.get("starts")))
        y["xg"] += _num(r.get("xg"))
        y["xa"] += _num(r.get("xa"))
        if r.get("rt") and r.get("min"):
            y["_rw"] += float(r["rt"]) * float(r["min"])
            y["_rm"] += float(r["min"])
        if r.get("scope") != "international" and r.get("tid") is not None:
            y["_teams"][r["tid"]] = y["_teams"].get(r["tid"], 0) + int(_num(r.get("min")))
        if r.get("coverage") in (COVERAGE_PARTIAL, COVERAGE_NONE):
            y["coverage"] = COVERAGE_PARTIAL
    out = []
    for y in by.values():
        if y["_rm"]:
            y["rt"] = round(y["_rw"] / y["_rm"], 2)
        y["xg"], y["xa"] = round(y["xg"], 2), round(y["xa"], 2)
        y["teams"] = [t for t, _m in sorted(y["_teams"].items(), key=lambda kv: -kv[1])]
        if not y["intl"]["apps"]:
            del y["intl"]
        if not y["teams"]:
            del y["teams"]
        for k in ("xg", "xa", "starts"):
            if not y[k]:
                del y[k]
        for k in ("_rw", "_rm", "_teams"):
            del y[k]
        out.append(y)
    out.sort(key=lambda y: era_key(y["era"]), reverse=True)
    return out


def club_season_totals(rows: list[dict]) -> list[dict]:
    """A club's year by year: each season key's competition rows summed (a row without a record leaves it "partial")."""
    by: dict[str, dict] = {}
    for r in rows:
        era = r.get("era")
        if not era:
            continue
        y = by.setdefault(era, {"era": era, "comps": 0, "played": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "record": COVERAGE_FULL})
        y["comps"] += 1
        if r.get("w") is None:
            if r.get("played"):
                y["record"] = COVERAGE_PARTIAL
            continue
        for k in ("played", "w", "d", "l", "gf", "ga"):
            y[k] += int(_num(r.get(k)))
        if r.get("stage") == "winner":
            y.setdefault("won", []).append(r["comp"])
    return sorted(by.values(), key=lambda y: era_key(y["era"]), reverse=True)


def _market_fields(squad_row: dict | None, details: dict | None) -> dict:
    """Market value (EUR unless `mvc`), contract end and foot: the squad list first, then the archive's profile."""
    out: dict[str, Any] = {}
    sr, det = squad_row or {}, details or {}
    if sr.get("mv"):
        out["mv"] = int(sr["mv"])
        if sr.get("mvc"):
            out["mvc"] = sr["mvc"]
    elif det.get("market_value"):
        out["mv"] = int(det["market_value"])
        if det.get("market_value_currency") and det["market_value_currency"] != "EUR":
            out["mvc"] = det["market_value_currency"]
    until = sr.get("until") or det.get("contract_until")
    if until:
        d = _iso_date(until)
        if d:
            out["until"] = d
    if det.get("foot"):
        out["foot"] = det["foot"]
    return out


COVERAGE_FULL = "full"
COVERAGE_PARTIAL = "partial"
COVERAGE_NONE = "none"
COVERAGE_TOTALS = "totals"


def _gap(cs: dict) -> str:
    """
    Why a partial row is partial: "backfill" (the hourly fetch has the missing matches
    queued), "unavailable" (Sofascore has no line-ups for them) or "outside" (ties the
    fetch never asks for: a national cup's or a qualifying round's without a followed club).
    """
    if cs.get("bf_n"):
        return "backfill"
    return "unavailable" if cs.get("na_n") else "outside"


def coverage_flag(with_detail: int, finished: int) -> str:
    """"full" when every finished match has line-ups (or none is finished yet), "none" when none has, else "partial"."""
    if finished <= 0 or with_detail >= finished:
        return COVERAGE_FULL
    return COVERAGE_NONE if with_detail <= 0 else COVERAGE_PARTIAL


def _coverage_fields(ms: dict, lineups: dict, unavailable: set[str]) -> dict:
    """A season's player-data coverage: the flag, and how many finished matches Sofascore has no line-ups for."""
    fin = [g for g, m in ms.items() if _finished(m)]
    det = sum(1 for g in fin if g in lineups)
    out: dict[str, Any] = {"coverage": coverage_flag(det, len(fin))}
    na = sum(1 for g in fin if g not in lineups and str(g) in unavailable)
    if na:
        out["unavailable"] = na
    return out


def result_string(m: dict, home: bool) -> str | None:
    """"W 2-1", or for a shoot-out "D 1-1, won 4-3 pens" / "D 1-1, lost on pens", from one side."""
    if not _finished(m):
        return None
    gf, ga = (m["hs"], m["as"]) if home else (m["as"], m["hs"])
    out = f"{'W' if gf > ga else 'D' if gf == ga else 'L'} {gf}-{ga}"
    if gf == ga and m.get("winner"):
        won = m["winner"] == (m.get("home") if home else m.get("away"))
        pens = m.get("pens")
        if pens:
            pf, pa = (pens[0], pens[1]) if home else (pens[1], pens[0])
            out += f", {'won' if won else 'lost'} {pf}-{pa} pens"
        else:
            out += f", {'won' if won else 'lost'} on pens"
    return out


def _status(m: dict) -> str:
    raw = str(m.get("status") or "").lower()
    if raw in FINISHED:
        return "finished"
    if raw in ("inprogress", "live"):
        return "live"
    if raw in ("postponed",):
        return "postponed"
    if raw in ("canceled", "cancelled"):
        return "cancelled"
    if _overdue(m):              # "not started" hours after kick-off: never closed by the source, not to come
        return "postponed"
    return "scheduled"


def _fixture_row(gid: str, m: dict, detail: bool) -> dict:
    row = {"id": str(gid), "date": m.get("date"), "round": m.get("round"), "stage": m.get("stage") or "league",
           "status": _status(m), "home": m.get("home"), "away": m.get("away"), "home_id": m.get("home_id"),
           "away_id": m.get("away_id"), "hs": m.get("hs"), "as": m.get("as")}
    for k in ("group", "winner", "agg_winner", "torneo", "zone", "split_group", "pens"):
        if m.get(k):
            row[k] = m[k]
    if row["status"] == "postponed" and _overdue(m):
        row["result_missing"] = True
    if detail:
        row["detail"] = True
    return {k: v for k, v in row.items() if v is not None}


def _leaders_from_players(players: list[dict], name_to_tid: Callable[[str], Any] = lambda n: None,
                          n: int = 10) -> dict[str, list[dict]]:
    out = {}
    for key, cat in (("goals", "goals"), ("assists", "assists"), ("xg", "expectedGoals"), ("rating", "rating")):
        pool = [p for p in players if p.get(key)]
        if key == "rating":
            pool = [p for p in pool if p.get("qualified")]
        pool.sort(key=lambda p: -float(p[key]))
        out[cat] = [_leader(str(p["player_id"]), p.get("name"), p.get("team"), p[key], name_to_tid) for p in pool[:n]]
    return {k: v for k, v in out.items() if v}


def _leaders_from_archive(top: dict, name_to_tid: Callable[[str], Any] = lambda n: None, n: int = 10) -> dict[str, list[dict]]:
    return {cat: [_leader(str(r.get("id")), r.get("name"), r.get("team"), r.get("value"), name_to_tid) for r in (rows or [])[:n]]
            for cat, rows in (top or {}).items()}


def _leader(pid, name, team, value, name_to_tid) -> dict:
    row = {"id": pid, "name": name, "team": team, "tid": name_to_tid(team), "value": value}
    return {k: v for k, v in row.items() if v is not None}


def _slugify(name: str) -> str:
    """The same club slug the competition payloads use (build_site_all._slug), so links agree."""
    return "".join(ch if ch.isalnum() else "-" for ch in str(name or "").lower()).strip("-")
