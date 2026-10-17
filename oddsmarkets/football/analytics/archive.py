"""
The archive store: past seasons of every competition and the careers of
profiled players, fetched by scripts/fetch_sofascore_history.py.

Shape (docs/site/data/archive/store.json):

    seasons[slug][season_id] = {name, year, tournament_id, standings: [...], top_players: {...}}
    players[pid] = {details: {...}, seasons: [{tid, tname, sid, sname, year, team, stats}], ...}
    season_lists[tournament_id] = [{season_id, name, year}]

The readers here turn that into career pages and season tables, tolerant of
partial fills: a player with a details record but no seasons yet is a career
with nothing in it, not an error.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EMPTY_ARCHIVE: dict[str, Any] = {"seasons": {}, "players": {}, "season_lists": {}, "meta": {}}

# Season-stat keys kept from Sofascore's per-player season statistics and the
# short names a career table shows them under.
SEASON_STAT_KEYS = {
    "appearances": "apps", "matchesStarted": "starts", "minutesPlayed": "minutes", "rating": "rating",
    "goals": "goals", "assists": "assists", "expectedGoals": "xg", "expectedAssists": "xa",
    "expectedGoalsOnTarget": "xgot", "penaltyGoals": "pens", "totalShots": "shots", "shotsOnTarget": "sot",
    "keyPasses": "key_passes", "bigChancesCreated": "big_chances", "accuratePasses": "passes_acc",
    "totalPasses": "passes", "accuratePassesPercentage": "pass_pct", "successfulDribbles": "dribbles",
    "totalDuelsWon": "duels_won", "aerialDuelsWon": "aerials_won", "tackles": "tackles",
    "interceptions": "interceptions", "clearances": "clearances", "ballRecovery": "recoveries",
    "saves": "saves", "goalsConcededInsideTheBox": "conceded_box", "goalsConceded": "conceded",
    "cleanSheet": "clean_sheets", "yellowCards": "yellow", "redCards": "red", "goalsPrevented": "goals_prevented",
    "touches": "touches", "possessionLost": "poss_lost", "wasFouled": "fouled", "fouls": "fouls",
}
PER90 = ("goals", "assists", "xg", "xa", "shots", "key_passes", "big_chances", "tackles", "interceptions", "saves")


def load_archive(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in EMPTY_ARCHIVE.items()}
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error("archive at %s is unreadable (%s) — starting empty", path, exc)
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in EMPTY_ARCHIVE.items()}
    for key, default in EMPTY_ARCHIVE.items():
        store.setdefault(key, dict(default) if isinstance(default, dict) else default)
    return store


def save_archive(store: dict[str, Any], path: Path) -> None:
    store["meta"] = dict(store.get("meta") or {})
    store["meta"]["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def season_row(entry: dict) -> dict:
    """One (tournament, season) line of a career with derived per-90s."""
    stats = entry.get("stats") or {}
    row: dict[str, Any] = {
        "tid": entry.get("tid"), "tournament": entry.get("tname"), "sid": entry.get("sid"),
        "season": entry.get("sname"), "year": entry.get("year"), "team": entry.get("team"),
    }
    for src, dst in SEASON_STAT_KEYS.items():
        v = _f(stats.get(src))
        if v is not None:
            row[dst] = round(v, 3) if dst in ("rating", "xg", "xa", "xgot", "goals_prevented", "pass_pct") else int(v) if v == int(v) else round(v, 2)
    mins = _f(stats.get("minutesPlayed")) or 0.0
    if mins > 0:
        p90 = mins / 90.0
        for k in PER90:
            if k in row:
                row[k + "_90"] = round(float(row[k]) / p90, 3)
        g, a = row.get("goals", 0) or 0, row.get("assists", 0) or 0
        row["ga_90"] = round((g + a) / p90, 3)
    return row


def sort_key(row: dict) -> tuple:
    """Chronological order from a Sofascore season 'year' ('25/26' or '2026')."""
    y = str(row.get("year") or row.get("season") or "")
    if "/" in y:
        first = y.split("/")[0]
        n = int(first) if first.isdigit() else 0
        return (2000 + n if n < 100 else n, 1)
    digits = "".join(ch for ch in y if ch.isdigit())[:4]
    return (int(digits) if digits else 0, 0)


def career(archive: dict[str, Any], pid: str) -> dict | None:
    rec = (archive.get("players") or {}).get(str(pid))
    if not rec:
        return None
    seasons = sorted((season_row(e) for e in rec.get("seasons") or []), key=sort_key)
    totals: dict[str, float] = {}
    for row in seasons:
        for k in ("apps", "minutes", "goals", "assists", "xg", "xa", "shots", "key_passes", "yellow", "red"):
            if row.get(k) is not None:
                totals[k] = totals.get(k, 0.0) + float(row[k])
    mins = totals.get("minutes", 0.0)
    if mins > 0:
        totals["ga_90"] = round((totals.get("goals", 0) + totals.get("assists", 0)) / (mins / 90.0), 3)
    # Rating over the career, minutes-weighted.
    w = sum(float(r["minutes"]) for r in seasons if r.get("rating") and r.get("minutes"))
    if w > 0:
        totals["rating"] = round(sum(float(r["rating"]) * float(r["minutes"]) for r in seasons if r.get("rating") and r.get("minutes")) / w, 2)
    details = rec.get("details") or {}
    return {
        "id": str(pid), "details": details, "seasons": seasons,
        "totals": {k: (round(v, 2) if isinstance(v, float) and k not in ("apps", "minutes", "goals", "assists", "yellow", "red") else int(v) if isinstance(v, float) else v) for k, v in totals.items()},
        "fetched_at": rec.get("fetched_at"), "complete": bool(rec.get("complete")),
    }


def season_tables(archive: dict[str, Any], slug: str) -> list[dict]:
    """Past seasons of one competition, newest first: standings and the season's leaders."""
    out = []
    for sid, s in ((archive.get("seasons") or {}).get(slug) or {}).items():
        leaders = {}
        for cat, rows in (s.get("top_players") or {}).items():
            leaders[cat] = [{"id": str(r.get("id")), "name": r.get("name"), "team": r.get("team"), "value": r.get("value")} for r in rows[:10]]
        out.append({"season_id": int(sid), "name": s.get("name"), "year": s.get("year"),
                    "standings": s.get("standings") or [], "leaders": leaders})
    out.sort(key=lambda r: sort_key({"year": r["year"]}), reverse=True)
    return out
