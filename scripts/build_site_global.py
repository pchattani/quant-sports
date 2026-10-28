"""
The site-wide payloads that sit above the competitions: the cross-competition
pool of clubs and players, and the archive's career and past-season pages.

Called by build_site_all.py once every competition has been built, with the
competitions' in-memory results (each entry carries its `_players`, `_teams`,
`_strength`, `_probs` and `_bracket` for this purpose). Everything degrades:
without a pooled fit there is no pool, without Polymarket there is no market
without the archive there are no careers — each payload says so.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.football.analytics.archive import career, season_tables
from oddsmarkets.football.analytics.unified import current_era, edition_era, frame_of
from oddsmarkets.football.analytics.pool import build_pool
from oddsmarkets.football.competitions.cup.config import CUPS
from oddsmarkets.football.competitions.league.config import LEAGUES, LIGA_ARGENTINA_SLUG

logger = logging.getLogger("build-global")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(out_dir: Path, name: str, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _read(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read %s: %s", path, exc)
        return default


# ── the pool ─────────────────────────────────────────────────────────────────

INTL_RECENT_DAYS = 60


def in_current_window(c: dict, now: datetime | None = None) -> bool:
    """
    Whether a competition's built edition is the one of the season under way: a club
    competition's edition in its frame's current season (from its fixtures' dates); an
    international competition, which has no season, while it has played in the last
    INTL_RECENT_DAYS. A competition without fixtures is kept (nothing to judge by).
    """
    now = now or datetime.now(timezone.utc)
    dates = [str(f.get("date") or "")[:10] for f in c.get("_fixtures") or [] if f.get("date")]
    if not dates:
        return True
    frame = frame_of(c.get("slug"))
    if frame == "international":
        played = [str(f.get("date") or "")[:10] for f in c.get("_fixtures") or [] if f.get("status") == "finished" and f.get("date")]
        return bool(played) and max(played) >= (now - timedelta(days=INTL_RECENT_DAYS)).strftime("%Y-%m-%d")
    return edition_era(c.get("slug"), "", dates) == current_era(frame, now)

def build_global(data_dir: Path, entries: list[dict], pooled, connections: dict[str, int] | None,
                 bridges: dict[str, int] | None = None) -> dict | None:
    """
    pool.json; returns the pool. The cross-competition player payloads (the lab, the
    leaders, compare) are one row per person and are written by the unified step
    (analytics/people_lines.py, data/lab/): players_global.json and players_lab*.json,
    one row per player per competition, are retired.
    """
    league_names = {slug: cfg.name for slug, cfg in LEAGUES.items()}
    cup_names = {slug: cfg.name for slug, cfg in CUPS.items()}
    ok = [c for c in entries if c.get("ok")]
    strength_rows = {c["slug"]: {r["team"]: r for r in c.get("_strength") or []} for c in ok}
    teams_info = {c["slug"]: c.get("_teams") or {} for c in ok}
    pool = None
    if pooled is not None and pooled.params_:
        try:
            pool = build_pool(pooled, league_names, cup_names, strength_rows, teams_info, connections, bridges)
        except Exception as exc:  # noqa: BLE001
            logger.error("pool failed: %s", exc)
    if pool is not None:
        _write(data_dir, "pool.json", {**pool, "updated_at": _now()})
        return pool
    # No pooled fit this run: never publish an empty pool over the last good one (the clubs scale, the overview's
    # surprises and the Lab's pooled chances read it). The previous file stays; only a first build writes the stub.
    prev = _read(data_dir / "pool.json", None)
    if isinstance(prev, dict) and prev.get("model") and prev.get("clubs"):
        logger.warning("pool: no pooled fit this run; keeping the previous pool.json (%s)", prev.get("updated_at"))
        return None
    _write(data_dir, "pool.json", {"model": None, "leagues": {}, "clubs": [], "note": "No pooled fit this run.", "updated_at": _now()})
    return pool


# ── the archive ──────────────────────────────────────────────────────────────

def build_archive_pages(data_dir: Path, archive: dict) -> dict:
    careers_dir = data_dir / "careers"
    careers_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for pid in list((archive.get("players") or {})):
        c = career(archive, pid)
        if not c:
            continue
        _write(careers_dir, f"{pid}.json", c)
        d = c["details"]
        last = c["seasons"][-1] if c["seasons"] else {}
        index.append({"id": pid, "name": d.get("name"), "team": d.get("team") or last.get("team"), "position": d.get("position"),
                      "country": d.get("country"), "seasons": len(c["seasons"]), "complete": c["complete"],
                      "goals": c["totals"].get("goals"), "assists": c["totals"].get("assists")})
    index.sort(key=lambda r: -(r.get("goals") or 0))
    _write(careers_dir, "index.json", {"players": index, "updated_at": _now()})
    hist_dir = data_dir / "history"
    n_seasons = 0
    for slug in list(LEAGUES) + [LIGA_ARGENTINA_SLUG] + list(CUPS):
        tables = season_tables(archive, slug)
        if tables:
            _write(hist_dir, f"{slug}.json", {"seasons": tables, "updated_at": _now()})
            n_seasons += len(tables)
    write_champions(data_dir)
    return {"careers": len(index), "seasons": n_seasons}


CHAMPIONS_REF = Path(__file__).resolve().parents[1] / "oddsmarkets" / "football" / "analytics" / "data" / "champions_wikidata.json"


def write_champions(data_dir: Path) -> int:
    """
    data/champions.json for the History tabs: every champion of each competition since it began, from Wikidata (CC0;
    scripts/football_champions_wikidata.py writes the committed reference file). Rows are [season, year, winner],
    oldest first. Returns the number of competitions written (0 when the reference file is missing).
    """
    ref = _read(CHAMPIONS_REF, None)
    if not isinstance(ref, dict) or not ref.get("competitions"):
        return 0
    comps = {slug: {"label": c.get("label"), "editions": [[e.get("season"), e.get("year"), e.get("winner")] for e in c.get("editions") or []]}
             for slug, c in ref["competitions"].items() if c.get("editions")}
    _write(data_dir, "champions.json", {"source": ref.get("source"), "licence": ref.get("licence"), "fetched_at": ref.get("fetched_at"),
                                        "competitions": comps, "updated_at": _now()})
    return len(comps)
