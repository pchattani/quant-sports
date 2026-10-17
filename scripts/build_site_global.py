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
from oddsmarkets.football.analytics.players import FLOOR_MIN, FLOOR_SHARE, METRICS, POSITION_LABELS, add_percentiles
from oddsmarkets.football.analytics.unified import current_era, edition_era, frame_of
from oddsmarkets.football.analytics.pool import ADJUSTED_KEYS, adjust_players, build_pool
from oddsmarkets.football.competitions.cup.config import CUPS
from oddsmarkets.football.competitions.league.config import LEAGUES, LIGA_ARGENTINA_SLUG

logger = logging.getLogger("build-global")

# What a global player row carries: identity, playing time, the headline totals,
# the rates the leaderboards and compare tools use, and their adjusted twins.
GLOBAL_KEYS = (
    "player_id", "name", "team", "position", "is_gk", "age", "country", "matches", "starts", "minutes", "rating",
    "goals", "assists", "xg", "xa", "npg", "npxg", "shots", "key_passes",
    "goals_90", "npg_90", "assists_90", "xg_90", "npxg_90", "xa_90", "xgot_90", "shots_90", "key_passes_90",
    "big_chances_90", "sot_pct", "pass_pct", "passes_90", "dribbles_90", "dribble_pct", "prog_carries_90",
    "touches_90", "tackles_90", "tackle_pct", "interceptions_90", "clearances_90", "blocks_90", "recoveries_90",
    "aerial_pct", "duel_pct", "duels_won_90", "aerials_won_90", "fouls_90", "fouled_90", "km_90", "sprints_90",
    "top_speed", "saves_90", "save_pct", "goals_prevented_90", "conceded_90", "yellow", "red", "qualified",
)


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
                 bridges: dict[str, int] | None = None) -> tuple[list[dict], dict | None]:
    """pool.json and players_global.json; returns (global players, pool)."""
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
    short = {c["slug"]: c.get("short_name") or c["name"] for c in entries}
    rows: list[dict] = []
    left_out: list[str] = []
    for c in ok:
        # One window for every row: the competition's edition of the season under way in its frame
        # (2026/27 in Europe, 2026 in Brazil); an edition long over (the Euro 2024 qualifiers, last
        # season's Coupe de France) is not "this season" and stays on its own pages.
        if not in_current_window(c):
            left_out.append(c["slug"])
            continue
        info = c.get("_teams") or {}
        for p in c.get("_players") or []:
            # Each competition's own floor: a share of the minutes its season has offered so far.
            if not p.get("qualified"):
                continue
            row = {k: p.get(k) for k in GLOBAL_KEYS if p.get(k) is not None}
            row["comp"] = c["slug"]
            row["comp_name"] = short[c["slug"]]
            row["season"] = c.get("season")
            row["kind"] = c.get("kind")
            row["team_slug"] = (info.get(p.get("team")) or {}).get("slug")
            row["crest"] = (info.get(p.get("team")) or {}).get("crest")
            row["pct_comp"] = p.get("pct")
            rows.append(row)
    factors = {slug: L["factor_att"] for slug, L in (pool or {}).get("leagues", {}).items()}
    adjust_players(rows, factors)
    # Percentiles against the whole pool's position groups. Every row is over its own
    # competition's floor (FLOOR_SHARE of the minutes its season has offered), so the pool
    # takes them all rather than one fixed number of minutes that is a tenth of a Brazilian
    # season and a third of a European one; the adjusted rates rank alongside the raw ones.
    floor = add_percentiles(rows, floor=FLOOR_MIN)
    for r in rows:
        r["pct_global"] = r.pop("pct", None)
        r["pool_global"] = r.pop("pool", None)
    _write_adjusted_percentiles(rows)
    rows.sort(key=lambda r: -(r.get("rating") or 0))
    build_lab(data_dir, ok, short, factors)
    try:
        build_lab_windows(data_dir, ok, short, factors)
    except Exception as exc:  # noqa: BLE001
        logger.error("calendar windows failed: %s", exc)
    if pool is not None:
        _write(data_dir, "pool.json", {**pool, "updated_at": _now()})
    else:
        _write(data_dir, "pool.json", {"model": None, "leagues": {}, "clubs": [], "note": "No pooled fit this run.", "updated_at": _now()})
    _write(data_dir, "players_global.json", {
        "players": rows, "metrics": METRICS, "positions": POSITION_LABELS, "minutes_floor": floor,
        "floor_share": FLOOR_SHARE, "left_out": sorted(left_out),
        "floor_rule": (f"Each player is over his competition's floor: {int(FLOOR_SHARE * 100)}% of the minutes its season has "
                       "offered so far. One window: each competition's edition of the season under way."),
        "leagues": (pool or {}).get("leagues", {}), "adjusted_keys": list(ADJUSTED_KEYS),
        "note": ("Rates marked adjusted are multiplied by the league's scoring factor from the pooled model — how much "
                 "easier it is to score against that league's defences than against the pool average — so attacking "
                 "output from different competitions sits on one footing. Percentiles are against the pool's position "
                 "group. Argentina's clubs are fitted separately and carry no factor."),
        "updated_at": _now(),
    })
    return rows, pool


def _write_adjusted_percentiles(rows: list[dict]) -> None:
    """Percentiles of the adjusted attacking rates within the global position pools."""
    pools: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("qualified") and (r.get("pool_global") or {}).get("key"):
            pools.setdefault(r["pool_global"]["key"], []).append(r)
    for members in pools.values():
        for key in ADJUSTED_KEYS:
            adj = key + "_adj"
            vals = sorted(float(m[adj]) for m in members if m.get(adj) is not None)
            if len(vals) < 3:
                continue
            for m in members:
                v = m.get(adj)
                if v is None:
                    continue
                below = sum(1 for x in vals if x < v)
                ties = sum(1 for x in vals if x == v)
                m.setdefault("pct_global", {})[adj] = int(round(100 * (below + 0.5 * ties) / len(vals)))


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
    return {"careers": len(index), "seasons": n_seasons}


# The Player lab: every player with at least LAB_MIN_MINUTES in any competition,
# column-oriented and rounded so the whole world loads in one small file.
LAB_MIN_MINUTES = 90
LAB_ID = ("player_id", "name", "team", "position", "age", "minutes", "matches")
LIGA_STORE_PATH = Path(__file__).resolve().parents[1] / "docs" / "liga" / "data" / "liga_store.json"


def _lab_keys() -> list[str]:
    keys = [m["key"] for m in METRICS
            if m["key"].endswith("_90") or m.get("pct") or m["group"] == "Advanced" or m["key"] in ("rating", "xg_per_shot")]
    return list(dict.fromkeys(k for k in keys if k not in LAB_ID))


def build_lab(data_dir: Path, entries: list[dict], short: dict[str, str], factors: dict[str, float]) -> int:
    """players_lab.json: the scatter page's data, per player per competition."""
    keys = _lab_keys()
    comps: dict[str, dict] = {}
    rows: list[list] = []
    for c in entries:
        players = [p for p in c.get("_players") or [] if (p.get("minutes") or 0) >= LAB_MIN_MINUTES]
        if not players:
            continue
        info = c.get("_teams") or {}
        comps[c["slug"]] = {"name": short.get(c["slug"], c["name"]), "kind": c.get("kind"), "family": c.get("family"),
                            "factor": round(float(factors.get(c["slug"], 1.0)), 4)}
        for p in players:
            row = [p.get("player_id"), p.get("name"), p.get("team"), p.get("position") or ("G" if p.get("is_gk") else None),
                   p.get("age"), int(p.get("minutes") or 0), int(p.get("matches") or 0), c["slug"],
                   (info.get(p.get("team")) or {}).get("slug")]
            for k in keys:
                v = p.get(k)
                row.append(None if v is None else round(float(v), 3))
            rows.append(row)
    metrics = [{k2: m[k2] for k2 in ("key", "label", "group", "fmt", "scope", "lower") if k2 in m}
               for m in METRICS if m["key"] in keys]
    _write(data_dir, "players_lab.json", {
        "fields": list(LAB_ID) + ["comp", "team_slug"] + keys, "metrics": metrics, "comps": comps,
        "adjusted_keys": list(ADJUSTED_KEYS), "min_minutes": LAB_MIN_MINUTES, "rows": rows, "updated_at": _now(),
    })
    logger.info("players_lab.json: %d player-competition rows, %d metrics", len(rows), len(keys))
    return len(rows)


def _window_store(stores: dict[str, dict], start: str, end: str) -> tuple[dict, dict[str, dict[str, float]], dict[str, tuple[str, str]], dict[str, str]]:
    """
    One store holding every match inside [start, end] from every competition,
    plus each player's minutes by competition, each player's latest club (never a
    national team) and each competition's first date with detail.
    """
    merged = {"matches": {}, "lineups": {}, "team_stats": {}, "incidents": {}, "players": {}, "shots": {}}
    minutes: dict[str, dict[str, float]] = {}
    club: dict[str, tuple[str, str]] = {}
    first: dict[str, str] = {}
    for slug, (st, international) in stores.items():
        ms = st.get("matches") or {}
        dates = [(ms.get(g) or {}).get("date") or "" for g in (st.get("lineups") or {})]
        dates = [d[:10] for d in dates if d]
        if dates:
            first[slug] = min(dates)
        for pid, meta in (st.get("players") or {}).items():
            merged["players"].setdefault(pid, meta)
        for gid, lineup in (st.get("lineups") or {}).items():
            m = ms.get(gid) or {}
            d = (m.get("date") or "")[:10]
            if not d or d < start or d > end or not isinstance(lineup, dict):
                continue
            merged["matches"][gid] = m
            merged["lineups"][gid] = lineup
            for key in ("team_stats", "incidents"):
                if gid in (st.get(key) or {}):
                    merged[key][gid] = st[key][gid]
            for pid, p in lineup.items():
                if not isinstance(p, dict):
                    continue
                mins = float(((p.get("s") or {}).get("minutesPlayed")) or 0)
                if mins <= 0:
                    continue
                minutes.setdefault(str(pid), {})
                minutes[str(pid)][slug] = minutes[str(pid)].get(slug, 0.0) + mins
                if not international and d >= club.get(str(pid), ("", ""))[0]:
                    club[str(pid)] = (d, str(p.get("t") or ""))
    return merged, minutes, club, first


def build_lab_windows(data_dir: Path, entries: list[dict], short: dict[str, str], factors: dict[str, float],
                      now: datetime | None = None) -> dict[str, int]:
    """
    players_lab_365.json (the last twelve months) and players_lab_ytd.json (the
    calendar year so far): one line per player across every competition played
    in that window, club and national team, so a player in a league three matches
    old is compared on the same stretch of calendar as one twenty matches in.
    Rates come from the same aggregation as the season lines. The club shown is
    the latest club; the competition is the one with the most minutes; the
    scoring factor is the minutes-weighted mean of the competitions played in.
    """
    from oddsmarkets.football.analytics.players import aggregate_players

    now = now or datetime.now(timezone.utc)
    end = now.strftime("%Y-%m-%d")
    windows = {"365": ((now - timedelta(days=365)).strftime("%Y-%m-%d"), "Last 12 months"),
               "ytd": (f"{now.year}-01-01", f"Calendar {now.year}")}
    stores: dict[str, tuple[dict, bool]] = {}
    for c in entries:
        path = LIGA_STORE_PATH if c.get("kind") == "liga" else data_dir / c["slug"] / "store.json"
        if not path.exists():
            continue
        try:
            stores[c["slug"]] = (json.loads(path.read_text(encoding="utf-8")), c.get("family") == "international")
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: store unreadable for the calendar views: %s", c["slug"], exc)
    info = {c["slug"]: c.get("_teams") or {} for c in entries}
    keys = _lab_keys()
    out: dict[str, int] = {}
    for tag, (start, label) in windows.items():
        merged, minutes, club, first = _window_store(stores, start, end)
        players = aggregate_players(merged, registry={}) if merged["lineups"] else []
        rows = []
        for p in players:
            pid = str(p.get("player_id"))
            if (p.get("minutes") or 0) < LAB_MIN_MINUTES:
                continue
            by = minutes.get(pid) or {}
            total = sum(by.values()) or 1.0
            clubs = {k: v for k, v in by.items() if not stores.get(k, ({}, False))[1]}
            main = max(clubs or by, key=(clubs or by).get) if by else None      # the club competition with most minutes
            factor = sum(float(factors.get(s, 1.0)) * m for s, m in by.items()) / total
            team = (club.get(pid) or ("", ""))[1] or p.get("team")
            mix = " · ".join(f"{short.get(s, s)} {int(m)}'" for s, m in sorted(by.items(), key=lambda kv: -kv[1]))
            row = [p.get("player_id"), p.get("name"), team, p.get("position") or ("G" if p.get("is_gk") else None),
                   p.get("age"), int(p.get("minutes") or 0), int(p.get("matches") or 0), mix, round(factor, 4), main,
                   (info.get(main, {}).get(team) or {}).get("slug")]
            for k in keys:
                v = p.get(k)
                row.append(None if v is None else round(float(v), 3))
            rows.append(row)
        metrics = [{k2: m[k2] for k2 in ("key", "label", "group", "fmt", "scope", "lower") if k2 in m}
                   for m in METRICS if m["key"] in keys]
        comps = {s: {"name": short.get(s, s), "factor": round(float(factors.get(s, 1.0)), 4), "first_detail": first.get(s)}
                 for s in stores}
        _write(data_dir, f"players_lab_{tag}.json", {
            "fields": list(LAB_ID) + ["mix", "factor", "comp", "team_slug"] + keys, "metrics": metrics, "comps": comps,
            "adjusted_keys": list(ADJUSTED_KEYS), "min_minutes": LAB_MIN_MINUTES, "rows": rows,
            "window": {"tag": tag, "label": label, "start": start, "end": end}, "updated_at": _now(),
        })
        logger.info("players_lab_%s.json: %d players, %d matches in %s..%s", tag, len(rows), len(merged["lineups"]), start, end)
        out[tag] = len(rows)
    return out
