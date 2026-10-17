#!/usr/bin/env python
"""
Fill the archive: past seasons of every competition, and the careers of the
players the site profiles.

Two queues, spent from one call budget per run, cheapest first:

  1. Past seasons. For each competition, the seasons Sofascore lists before the
     current one (up to SEASONS_BACK): the final standings and the season's
     leaders per category — two calls a season.
  2. Player careers. The profiled players — each competition's best by
     rating — get their details, the
     list of seasons Sofascore has statistics for, and one call per (tournament,
     season) for the tournaments the site follows plus the international ones,
     newest first, up to SEASONS_PER_PLAYER.

  3. Past results (newest first): every match of the seasons older than the two
     each store keeps (up to PAST_SEASONS_BACK), results only, into
     docs/site/data/past/store.json. One call a page of thirty matches, at most
     --past-budget calls a run, resumable page by page across runs.

  4. Transfers (added 16 October 2026), with whatever the first three leave (they were
     all but finished by then, so about 55 of the 60 calls a run): into
     docs/site/data/transfers/store.json,
       a. each club's recent transfers in and out (`/team/{id}/transfers`, one call a
          club, about the last nine months with fees, loans, frees and loan returns):
          the followed leagues and Argentina first, never fetched before stale, a club
          refreshed every TEAM_REFRESH_DAYS (7; TEAM_WINDOW_REFRESH_DAYS, 2, inside a
          transfer window), the cup clubs every CUP_TEAM_REFRESH_DAYS (30);
       b. then players' whole transfer histories (`/player/{id}/transfer-history`, one
          call a player) for the earlier windows the club lists no longer show: the
          players the value layer rates with PLAYER_MIN_MINUTES (450) club minutes in 12
          months, most minutes first, each once and again after PLAYER_REFRESH_DAYS (180),
          keeping CUP_RESERVE (5) calls a run for the cup clubs' lists.
     A full first pass: the ~270 followed clubs in about five runs; the ~6,900 rated players
     at ~50 a run in about six days; the ~360 cup clubs at 5 a run over about three days.

Each run does what the budget allows and stops; the next run carries on. Like
the other fetchers it runs only from a residential connection and stops after
the first 403 challenge.

    python scripts/fetch_sofascore_history.py                # default budget
    python scripts/fetch_sofascore_history.py --budget 300
    python scripts/fetch_sofascore_history.py --players-only
    python scripts/fetch_sofascore_history.py --transfers-budget 0     # skip phase 4
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.analytics.archive import load_archive, save_archive  # noqa: E402
from oddsmarkets.football.competitions.cup.config import CUPS  # noqa: E402
from oddsmarkets.football.competitions.league.config import LEAGUES  # noqa: E402
from oddsmarkets.football.sources import sofascore  # noqa: E402
from oddsmarkets.football.sources.teams import normalize_cup_name, normalize_team_name  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fetch-history")

SITE_DATA = ROOT / "docs" / "site" / "data"
ARCHIVE_PATH = SITE_DATA / "archive" / "store.json"
PAST_PATH = SITE_DATA / "past" / "store.json"
LIGA_SEASONS_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "liga" / "data" / "seasons.json"
SEASONS_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "seasons.json"

DEFAULT_BUDGET = 60
SEASONS_BACK = 8
SEASONS_PER_PLAYER = 12
PROFILED_PER_COMPETITION = 25
PAUSE_S = 1.0
MAX_CONSECUTIVE_FAILURES = 3
PAST_SEASONS_BACK = 6          # past seasons of results beyond the two each store keeps
DEFAULT_PAST_BUDGET = 20       # of the run's budget, for past results
TRANSFERS_PATH = SITE_DATA / "transfers" / "store.json"
VALUE_PLAYERS_PATH = SITE_DATA / "value" / "players.json"   # the build's rated players (phase 4b's queue)
TEAM_REFRESH_DAYS = 7
TEAM_WINDOW_REFRESH_DAYS = 2
CUP_TEAM_REFRESH_DAYS = 30
PLAYER_REFRESH_DAYS = 180
PLAYER_MIN_MINUTES = 450       # phase 4b: players with this many club minutes in 12 months
FAILED_RETRY_DAYS = 14
CUP_RESERVE = 5                # phase 4: calls a run kept for the cup clubs once the followed clubs are current
# Record keys a past result keeps (event_record has more; these are what a
# results list and a computed table need).
PAST_KEYS = ("home", "away", "home_id", "away_id", "hs", "as", "date", "round", "stage", "group", "winner",
             "agg_winner", "status", "split_group", "pens")

# Tournaments a career keeps: everything the site follows plus the national
# team tournaments that decide awards. Sofascore ids.
INTERNATIONAL_TIDS = {16: "World Cup", 1: "European Championship", 133: "Copa América", 357: "Club World Cup"}
LIGA_ARGENTINA_TID = 155


def allowed_tournaments() -> set[int]:
    tids = {cfg.sofascore_id for cfg in list(LEAGUES.values()) + list(CUPS.values())}
    tids |= {getattr(cfg, "alt_sofascore_id", None) for cfg in LEAGUES.values()} - {None}
    tids |= set(INTERNATIONAL_TIDS) | {LIGA_ARGENTINA_TID}
    return tids


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def profiled_players() -> list[dict]:
    """Each competition's best by rating, de-duplicated by id."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(pid, name, reason):
        pid = str(pid) if pid else None
        if not pid or pid in seen:
            return
        seen.add(pid)
        out.append({"id": pid, "name": name, "why": reason})

    for path in sorted(SITE_DATA.glob("*/players_live.json")):
        try:
            live = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        players = [p for p in live.get("players") or [] if p.get("qualified") and p.get("rating")]
        players.sort(key=lambda p: (-float(p["rating"]), -p.get("minutes", 0)))
        for p in players[:PROFILED_PER_COMPETITION]:
            add(p["player_id"], p["name"], f"top rating {path.parent.name}")
    return out


def with_liga(seasons_cfg: dict) -> dict:
    """seasons.json plus the Argentine league (its own seasons file), so its past seasons are archived too."""
    out = dict(seasons_cfg)
    try:
        liga = json.loads(LIGA_SEASONS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    ids = []
    # Only the current year: the Argentine store holds that alone, so earlier
    # years are past seasons to archive like any other competition's.
    for s in (liga.get("seasons") or [])[:1]:
        for key in ("clausura", "apertura"):
            if s.get(key) and s[key] not in ids:
                ids.append(s[key])
    if liga.get("tournament_id") and ids:
        out["liga-argentina"] = {"tournament_id": liga["tournament_id"], "seasons": [{"season_id": i} for i in ids]}
    return out


def load_past(path: Path = PAST_PATH) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        doc = {}
    doc.setdefault("seasons", {})
    doc.setdefault("meta", {})
    return doc


def save_past(doc: dict, path: Path = PAST_PATH) -> None:
    doc["meta"]["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def past_queue(archive: dict, past: dict, seasons_cfg: dict) -> list[tuple[str, int, dict]]:
    """
    (slug, tournament_id, season) for past seasons whose results are not complete,
    newest first across competitions (every competition's last season before its
    store's, then the one before, ...), leagues before cups at each depth.
    """
    order = {slug: i for i, slug in enumerate(list(LEAGUES) + ["liga-argentina"] + list(CUPS))}
    queue = []
    for slug, entry in seasons_cfg.items():
        tid = int(entry.get("tournament_id") or 0)
        listed = archive["season_lists"].get(str(tid))
        if not tid or not listed:
            continue
        in_store = {int(s["season_id"]) for s in entry.get("seasons") or []}
        # A competition re-resolved to another tournament drops what it had.
        valid = {int(s["season_id"]) for s in listed}
        have = past["seasons"].setdefault(slug, {})
        for sid in [k for k in have if int(k) not in valid]:
            del have[sid]
        older = [s for s in listed if int(s["season_id"]) not in in_store
                 and "club friendly" not in str(s.get("name") or "").lower()]
        if in_store:
            newest_store = max(_year_key(s.get("year")) for s in listed if int(s["season_id"]) in in_store) if any(
                int(s["season_id"]) in in_store for s in listed) else 9999
            older = [s for s in older if _year_key(s.get("year")) <= newest_store]
        for depth, s in enumerate(older[:PAST_SEASONS_BACK]):
            rec = have.get(str(s["season_id"]))
            if rec and rec.get("complete"):
                continue
            queue.append((depth, order.get(slug, 999), slug, tid, s))
    queue.sort(key=lambda q: (q[0], q[1]))
    return [(slug, tid, s) for _, _, slug, tid, s in queue]


def _canon_for(slug: str):
    """(canon, canon2, international, round_slugs) as the live fetcher uses them for this competition."""
    if slug == "liga-argentina":
        return (lambda n: normalize_team_name(n, "liga_argentina")), None, False, {}
    cfg = LEAGUES.get(slug) or CUPS.get(slug)
    international = getattr(cfg, "family", "") == "international"
    canon2 = normalize_cup_name if (slug in CUPS and not international) else None
    return (lambda n: normalize_team_name(n, cfg.registry)), canon2, international, dict(getattr(cfg, "round_slugs", ()) or ())


def fetch_past_season(past: dict, slug: str, tid: int, season: dict, budget) -> bool:
    """Fetch (or resume) one past season's results. True when anything arrived."""
    sid = int(season["season_id"])
    rec = past["seasons"].setdefault(slug, {}).setdefault(str(sid), {
        "name": season.get("name"), "year": season.get("year"), "tournament_id": tid,
        "matches": {}, "complete": False, "next_page": 0})
    events, complete, next_page = sofascore.past_season_events(tid, sid, budget, start_page=int(rec.get("next_page") or 0))
    canon, canon2, international, round_slugs = _canon_for(slug)
    for ev in events:
        out = sofascore.event_record(ev, canon, sid, canon2=canon2, round_slugs=round_slugs, international=international)
        if out is None:
            continue
        gid, r = out
        rec["matches"][gid] = {k: r[k] for k in PAST_KEYS if r.get(k) is not None}
    rec["next_page"] = next_page
    rec["complete"] = bool(complete)
    rec["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info("past %s %s (%s): %d matches%s", slug, sid, season.get("name"), len(rec["matches"]),
                "" if complete else f", resumes at page {next_page}")
    return bool(events) or complete


def season_queue(archive: dict, seasons_cfg: dict) -> list[tuple[str, int, int, dict]]:
    """(slug, tournament_id, season_id, season) for past seasons still to fetch."""
    queue = []
    for slug, entry in seasons_cfg.items():
        current = (entry.get("seasons") or [{}])[0]
        tid = int(entry.get("tournament_id") or 0)
        if not tid:
            continue
        listed = archive["season_lists"].get(str(tid))
        if listed is None:
            queue.append((slug, tid, 0, {"_list": True}))
            continue
        have = archive["seasons"].setdefault(slug, {})
        past = [s for s in listed if s.get("season_id") != current.get("season_id")][:SEASONS_BACK]
        for s in past:
            if str(s["season_id"]) not in have:
                queue.append((slug, tid, int(s["season_id"]), s))
    return queue


def fetch_season(archive: dict, slug: str, tid: int, sid: int, season: dict, budget) -> bool:
    blocks = sofascore.standings_blocks(tid, sid) if budget.take() else None
    time.sleep(PAUSE_S)
    if blocks is None:
        return False
    standings = []
    for b in blocks:
        for r in b.get("rows") or []:
            standings.append({"group": b.get("name"), "team": r.get("team"), "team_id": r.get("team_id"), "position": r.get("position"),
                              "points": r.get("points"), "matches": r.get("matches"), "promotion": r.get("promotion")})
    top = sofascore.top_players(tid, sid, budget=budget)
    archive["seasons"].setdefault(slug, {})[str(sid)] = {
        "name": season.get("name"), "year": season.get("year"), "tournament_id": tid,
        "standings": standings, "top_players": top or {},
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return True


def fetch_player(archive: dict, player: dict, budget, allowed: set[int]) -> bool:
    """Details, the season list, and per-season stats up to the cap; resumable across runs."""
    pid = player.get("id")
    if not pid:
        hit = sofascore.search_player(player["name"] + (" " + player["club"] if player.get("club") else ""), budget=budget)
        if not hit:
            hit = sofascore.search_player(player["name"], budget=budget)
        if not hit:
            logger.warning("no Sofascore player found for %s", player["name"])
            return False
        pid = player["id"] = hit["id"]
    rec = archive["players"].setdefault(str(pid), {"seasons": [], "why": player.get("why")})
    if not rec.get("details"):
        details = sofascore.player_details(pid, budget=budget)
        if details is None:
            return False
        rec["details"] = details
    if rec.get("season_list") is None:
        listed = sofascore.player_seasons(pid, budget=budget)
        if listed is None:
            return False
        keep = [s for s in listed if int(s.get("tid") or 0) in allowed]
        keep.sort(key=lambda s: _year_key(s.get("year")), reverse=True)
        rec["season_list"] = keep[:SEASONS_PER_PLAYER]
    have = {(int(s["tid"]), int(s["sid"])) for s in rec["seasons"]}
    for s in rec["season_list"]:
        key = (int(s["tid"]), int(s["sid"]))
        if key in have:
            continue
        if budget.left < 1:
            return True
        stats = sofascore.player_season_stats(pid, key[0], key[1], budget=budget)
        if stats is None:
            # No statistics for that season (a squad member who never played): remember it so
            # the next run does not ask again.
            rec["seasons"].append({**s, "stats": {}, "team": None, "empty": True})
            continue
        rec["seasons"].append({**s, "stats": stats["stats"], "team": stats["team"]})
    rec["complete"] = len(rec["seasons"]) >= len(rec["season_list"])
    rec["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return True


def _year_key(year) -> int:
    y = str(year or "")
    if "/" in y:
        first = y.split("/")[0]
        return 2000 + int(first) if first.isdigit() else 0
    digits = "".join(ch for ch in y if ch.isdigit())[:4]
    return int(digits) if digits else 0


# ── phase 4: transfers ───────────────────────────────────────────────────────

def _now_s() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load_transfers(path: Path = TRANSFERS_PATH) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        doc = {}
    for k in ("transfers", "teams", "players", "failed", "meta"):
        doc.setdefault(k, {})
    return doc


def save_transfers(doc: dict, path: Path = TRANSFERS_PATH) -> None:
    doc["meta"]["updated_at"] = _now_s()
    doc["meta"]["n_transfers"] = len(doc["transfers"])
    doc["meta"]["source"] = ("Sofascore: /team/{id}/transfers and /player/{id}/transfer-history; "
                             "fees as Sofascore publishes them (EUR unless `cur`)")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def add_transfers(doc: dict, recs: list[dict]) -> int:
    """Merge transfer records into the store (keyed by Sofascore's id); returns how many were new."""
    new = 0
    for r in recs:
        key = sofascore.transfer_key(r)
        if key not in doc["transfers"]:
            new += 1
        doc["transfers"][key] = r
    return new


def transfer_team_queue(clubs: dict[str, dict], doc: dict, today: datetime | None = None) -> list[str]:
    """
    Clubs whose transfer list is due: the followed leagues and Argentina (priority 0)
    before the cup clubs, never fetched before stale, oldest first. Priority 0 refreshes
    every TEAM_REFRESH_DAYS (TEAM_WINDOW_REFRESH_DAYS inside a transfer window), the
    rest every CUP_TEAM_REFRESH_DAYS. A club without a transfers page waits FAILED_RETRY_DAYS.
    """
    from fetch_sofascore_squads import in_transfer_window

    today = today or datetime.now(timezone.utc)
    window = in_transfer_window(today.date())
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    out = []
    for tid, info in clubs.items():
        bad = _parse_ts(((doc.get("failed") or {}).get("t" + tid) or {}).get("at"))
        if bad is not None and (today - bad).days < FAILED_RETRY_DAYS:
            continue
        prio = int(info.get("priority", 1))
        days = (TEAM_WINDOW_REFRESH_DAYS if window else TEAM_REFRESH_DAYS) if prio == 0 else CUP_TEAM_REFRESH_DAYS
        fetched = _parse_ts((doc["teams"].get(tid) or {}).get("fetched_at"))
        if fetched is None:
            out.append((prio, 0, epoch, tid))
        elif (today - fetched).total_seconds() >= days * 86400:
            out.append((prio, 1, fetched, tid))
    out.sort()
    return [q[3] for q in out]


def transfer_player_queue(doc: dict, value_players: Path = VALUE_PLAYERS_PATH, today: datetime | None = None) -> list[str]:
    """Players whose transfer history is due: the rated players with PLAYER_MIN_MINUTES+, most minutes first."""
    today = today or datetime.now(timezone.utc)
    try:
        vp = json.loads(value_players.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    fields = vp.get("fields") or []
    if "id" not in fields or "min" not in fields:
        return []
    i_id, i_min = fields.index("id"), fields.index("min")
    rows = sorted(((str(r[i_id]), r[i_min] or 0) for r in vp.get("rows") or [] if (r[i_min] or 0) >= PLAYER_MIN_MINUTES),
                  key=lambda x: -x[1])
    out = []
    for pid, _ in rows:
        bad = _parse_ts(((doc.get("failed") or {}).get("p" + pid) or {}).get("at"))
        if bad is not None and (today - bad).days < FAILED_RETRY_DAYS:
            continue
        fetched = _parse_ts((doc["players"].get(pid) or {}).get("fetched_at"))
        if fetched is None or (today - fetched).days >= PLAYER_REFRESH_DAYS:
            out.append(pid)
    return out


def fetch_transfers(budget, clubs: dict[str, dict] | None = None, path: Path = TRANSFERS_PATH,
                    value_players: Path = VALUE_PLAYERS_PATH) -> dict:
    """Phase 4: club transfer lists first, then player histories, inside `budget`. Saves the store."""
    doc = load_transfers(path)
    if clubs is None:
        from fetch_sofascore_squads import candidate_clubs
        clubs, _ = candidate_clubs()
    team_q = transfer_team_queue(clubs, doc)
    player_q = transfer_player_queue(doc, value_players)
    logger.info("transfers: %d clubs and %d players due, %d transfers stored; budget %d",
                len(team_q), len(player_q), len(doc["transfers"]), budget.limit)
    stats = {"teams": 0, "players": 0, "new": 0, "failed": 0}
    state = {"misses": 0, "changed": False}

    def handle(key: str, recs) -> bool:
        """False when the run should stop. A missing page (404 and the like) is noted and skipped."""
        if recs is None:
            if sofascore.LAST_STATUS in (404, 410, 422, 200):
                doc["failed"][key] = {"at": _now_s(), "status": sofascore.LAST_STATUS}
                stats["failed"] += 1
                state["changed"] = True
                return True
            state["misses"] += 1
            if sofascore.is_blocked() or state["misses"] >= MAX_CONSECUTIVE_FAILURES:
                logger.warning("transfers: Sofascore not answering (status %s) — stopping", sofascore.LAST_STATUS)
                return False
            return True
        state["misses"] = 0
        doc["failed"].pop(key, None)
        stats["new"] += add_transfers(doc, recs)
        state["changed"] = True
        return True

    def teams(queue: list[str], keep: int = 0) -> bool:
        """Fetch clubs' transfer lists until `keep` calls are left. False when the run should stop."""
        for tid in queue:
            if budget.left <= keep or sofascore.is_blocked():
                return True
            try:
                recs = sofascore.team_transfers(tid, budget=budget)
            except sofascore.BudgetExhausted:
                return False
            time.sleep(PAUSE_S)
            if not handle("t" + tid, recs):
                return False
            if recs is not None:
                doc["teams"][tid] = {"fetched_at": _now_s(), "n": len(recs), "name": (clubs.get(tid) or {}).get("name")}
                stats["teams"] += 1
        return True

    # The followed leagues' clubs first; then player histories, keeping CUP_RESERVE calls a
    # run for the cup clubs (their transfers mostly involve clubs the site does not follow).
    followed = [t for t in team_q if int((clubs.get(t) or {}).get("priority", 1)) == 0]
    cups = [t for t in team_q if int((clubs.get(t) or {}).get("priority", 1)) != 0]
    go = teams(followed)
    reserve = min(CUP_RESERVE, len(cups), budget.left // 5)     # a fifth at most, so a small budget still reaches players
    for pid in (player_q if go else []):
        if budget.left <= reserve or sofascore.is_blocked():
            break
        try:
            recs = sofascore.player_transfer_history(pid, budget=budget)
        except sofascore.BudgetExhausted:
            go = False
            break
        time.sleep(PAUSE_S)
        if not handle("p" + pid, recs):
            go = False
            break
        if recs is not None:
            doc["players"][pid] = {"fetched_at": _now_s(), "n": len(recs)}
            stats["players"] += 1
    if go:
        teams(cups)
    if state["changed"]:
        save_transfers(doc, path)
    logger.info("transfers: %d clubs, %d players, %d new transfers (%d stored), %d without a page",
                stats["teams"], stats["players"], stats["new"], len(doc["transfers"]), stats["failed"])
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="calls this run may make")
    parser.add_argument("--players-only", action="store_true")
    parser.add_argument("--seasons-only", action="store_true")
    parser.add_argument("--past-budget", type=int, default=DEFAULT_PAST_BUDGET,
                        help="of the budget, calls for past seasons' results (0 to skip)")
    parser.add_argument("--transfers-budget", type=int, default=None,
                        help="of the budget, calls for transfers (default: whatever the other phases leave; 0 to skip)")
    args = parser.parse_args()

    seasons_cfg = json.loads(SEASONS_PATH.read_text(encoding="utf-8")).get("leagues", {}) if SEASONS_PATH.exists() else {}
    if not seasons_cfg:
        logger.error("no seasons.json")
        return 1
    seasons_cfg = with_liga(seasons_cfg)
    first = next(iter(seasons_cfg.values()))
    if not sofascore.probe(int(first["tournament_id"]), int(first["seasons"][0]["season_id"])):
        if sofascore.is_blocked():
            logger.error("Sofascore is challenging this IP (HTTP 403) — nothing fetched this run")
            return 1
    budget = sofascore.CallBudget(args.budget)
    archive = load_archive(ARCHIVE_PATH)
    allowed = allowed_tournaments()
    misses = 0
    changed = False

    if not args.players_only:
        for slug, tid, sid, season in season_queue(archive, seasons_cfg):
            if budget.left < 2 or sofascore.is_blocked():
                break
            if season.get("_list"):
                budget.take()
                listed = sofascore.list_seasons(tid)
                time.sleep(PAUSE_S)
                if listed:
                    archive["season_lists"][str(tid)] = listed
                    changed = True
                    for s2 in [s for s in listed[1:]][:SEASONS_BACK]:
                        if budget.left < 2:
                            break
                        ok = fetch_season(archive, slug, tid, int(s2["season_id"]), s2, budget)
                        changed = changed or ok
                continue
            ok = fetch_season(archive, slug, tid, sid, season, budget)
            changed = changed or ok
            misses = 0 if ok else misses + 1
            if misses >= MAX_CONSECUTIVE_FAILURES:
                logger.warning("seasons: Sofascore not answering — stopping")
                break

    past = load_past()
    past_changed = False
    if args.past_budget > 0 and not args.players_only and not sofascore.is_blocked():
        past_budget = sofascore.CallBudget(min(args.past_budget, budget.left))
        misses = 0
        for slug, tid, season in past_queue(archive, past, seasons_cfg):
            if past_budget.left < 1 or sofascore.is_blocked():
                break
            ok = fetch_past_season(past, slug, tid, season, past_budget)
            past_changed = True
            misses = 0 if ok else misses + 1
            if misses >= MAX_CONSECUTIVE_FAILURES:
                logger.warning("past results: Sofascore not answering — stopping")
                break
        budget.used += past_budget.used
        logger.info("past results: %d calls", past_budget.used)

    if not args.seasons_only and budget.left >= 3 and not sofascore.is_blocked():
        misses = 0
        for player in profiled_players():
            if budget.left < 3 or sofascore.is_blocked():
                break
            rec = archive["players"].get(str(player.get("id") or ""))
            if rec and rec.get("complete"):
                continue
            try:
                ok = fetch_player(archive, player, budget, allowed)
            except sofascore.BudgetExhausted:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: %s", player["name"], exc)
                ok = False
            changed = changed or ok
            misses = 0 if ok else misses + 1
            if misses >= MAX_CONSECUTIVE_FAILURES:
                logger.warning("players: Sofascore not answering — stopping")
                break
            time.sleep(PAUSE_S)

    if args.transfers_budget != 0 and not args.players_only and not args.seasons_only and not sofascore.is_blocked() and budget.left > 0:
        cap = budget.left if args.transfers_budget is None else min(args.transfers_budget, budget.left)
        t_budget = sofascore.CallBudget(cap)
        try:
            fetch_transfers(t_budget)
        except Exception as exc:  # noqa: BLE001
            logger.warning("transfers: %s", exc)
        budget.used += t_budget.used
        logger.info("transfers: %d calls", t_budget.used)

    logger.info("calls used: %d of %d", budget.used, budget.limit)
    if changed:
        save_archive(archive, ARCHIVE_PATH)
    if past_changed:
        save_past(past)
    n_seasons = sum(len(v) for v in archive["seasons"].values())
    n_players = len(archive["players"])
    complete = sum(1 for r in archive["players"].values() if r.get("complete"))
    logger.info("archive: %d past seasons over %d competitions, %d players (%d complete)",
                n_seasons, len(archive["seasons"]), n_players, complete)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
