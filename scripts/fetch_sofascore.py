"""
Live WC 2026 player/match data from Sofascore via datafc (curl_cffi under the hood).

Architecture (mirrors the market-odds resilience contract):
  - Incremental store at docs/wc/data/players_live_store.json — per finished match we
    keep lineups (player stats), shots, momentum and incidents, keyed by Sofascore
    game_id. Each run only fetches matches not yet in the store (a handful of
    requests per hour, not the whole tournament).
  - The store is rsynced to the public site repo with the rest of docs/wc; CI
    re-hydrates the latest store from the public repo before each run (same
    pattern as history_store.json), so the pipeline works whether the fetch
    happens in CI or locally (Plan B: run this script locally, commit the store).
  - EVERY network call is wrapped: on failure we keep last-good data and mark the
    aggregate payload ok:false. The build never breaks because Sofascore does.

Sources: Sofascore is an undocumented API — the site credits it and requests are
rate-limited by datafc. StatsBomb historical data remains the permanent fallback.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
STORE_PATH = ROOT / "docs" / "wc" / "data" / "players_live_store.json"

TOURNAMENT_ID = 16      # FIFA World Cup (Sofascore unique-tournament id)
SEASON_ID = 58210       # 2026 season (verified via /unique-tournament/16/seasons)

# Data-source fallback: api.sofascore.com blocks datacenter IPs (GitHub Actions),
# so we try the primary host first and fall back to datafc's 'sofavpn' mirror.
# Once a source succeeds/fails we remember it for the rest of the run.
_SOURCES = ["sofascore", "sofavpn"]
_active_source: str | None = None


def _call(fn, **kwargs):
    """Call a datafc function trying each data source; sticks with the first
    one that works for the remainder of the process."""
    global _active_source
    order = [_active_source] if _active_source else _SOURCES
    last_exc: Exception | None = None
    for src in order:
        try:
            out = fn(data_source=src, **kwargs)
            if _active_source != src:
                logger.info("Sofascore data source: %s", src)
                _active_source = src
            return out
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if _active_source == src:
                _active_source = None   # sticky source went bad — re-probe both next call
    raise last_exc if last_exc else RuntimeError("no data source")

# Sofascore team name → our canonical WC 2026 name
TEAM_ALIASES = {
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "Czechia": "Czech Republic",
    "South Korea": "South Korea",
    "Korea Republic": "South Korea",
    "USA": "USA",
    "United States": "USA",
    "Cabo Verde": "Cape Verde",
    "DR Congo": "DR Congo",
    "Congo DR": "DR Congo",
    "Türkiye": "Turkey",
    "Ivory Coast": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    "Curaçao": "Curacao",
}

# Sofascore lineup stat keys we persist (of the ~74 available)
KEEP_STATS = [
    "minutesPlayed", "goals", "goalAssist", "expectedGoals", "expectedAssists",
    "expectedGoalsOnTarget", "totalShots", "onTargetScoringAttempt", "keyPass",
    "bigChanceCreated", "accuratePass", "totalPass", "duelWon", "duelLost",
    "wonTackle", "interceptionWon", "ballRecovery", "touches", "rating",
    "saves", "goalsPrevented", "keeperSaveValue", "savedShotsFromInsideTheBox",
    "kilometersCovered", "numberOfSprints", "topSpeed",
]


def canon_team(name: str) -> str:
    return TEAM_ALIASES.get((name or "").strip(), (name or "").strip())


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def load_store() -> dict:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("players_live_store unreadable (%s) — starting fresh", e)
    return {"matches": {}, "lineups": {}, "shots": {}, "momentum": {}, "incidents": {}}


def save_store(store: dict) -> None:
    from datetime import datetime, timezone
    store["meta"] = {"updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(store, separators=(",", ":")), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fetch (all datafc calls individually guarded)
# ---------------------------------------------------------------------------

def probe() -> bool:
    """P0 CI probe: can this environment reach Sofascore at all?"""
    try:
        from datafc import match_data
        df = _call(match_data, tournament_id=TOURNAMENT_ID, season_id=SEASON_ID, week_number=1)
        ok = df is not None and len(df) > 0
        logger.info("Sofascore probe: %s (%d matches via %s)",
                    "PASS" if ok else "EMPTY", 0 if df is None else len(df), _active_source)
        return ok
    except Exception as e:  # noqa: BLE001
        logger.warning("Sofascore probe FAILED: %s", e)
        return False


def fetch_all_matches() -> pd.DataFrame | None:
    """All WC 2026 matches across every round (groups + named knockout stages).

    Knockout rounds live behind slugged endpoints (…/round/6/slug/round-of-32),
    which datafc exposes via tournament_type='world_cup' + tournament_stage.
    We derive (round_number, stage) pairs from season_rounds_data slugs.
    """
    try:
        from datafc import match_data, season_rounds_data
        rounds = _call(season_rounds_data, tournament_id=TOURNAMENT_ID, season_id=SEASON_ID)
    except Exception as e:  # noqa: BLE001
        logger.warning("Sofascore rounds fetch failed: %s", e)
        return None
    frames = []
    n_rounds = 0
    for _, r in rounds.iterrows():
        rn = r.get("round_number")
        if pd.isna(rn):
            continue
        rn = int(rn)
        slug = r.get("slug")
        n_rounds += 1
        try:
            if isinstance(slug, str) and slug:
                df = _call(match_data, tournament_id=TOURNAMENT_ID, season_id=SEASON_ID,
                           week_number=rn, tournament_type="world_cup",
                           tournament_stage=slug.replace("-", "_"))
            else:
                df = _call(match_data, tournament_id=TOURNAMENT_ID, season_id=SEASON_ID, week_number=rn)
            if df is not None and len(df):
                frames.append(df)
        except Exception as e:  # noqa: BLE001
            logger.debug("round %s (%s) match fetch failed: %s", rn, slug, e)
    if not frames:
        return None
    allm = pd.concat(frames, ignore_index=True).drop_duplicates(subset="game_id")
    logger.info("Sofascore: %d matches across %d rounds", len(allm), n_rounds)
    return allm


def _match_row_df(matches: pd.DataFrame, gid) -> pd.DataFrame:
    return matches[matches["game_id"] == gid]


def update_store(store: dict, max_new: int = 40) -> dict:
    """Fetch data for finished matches missing from the store. Returns status dict."""
    status = {"ok": False, "matches_seen": 0, "new_fetched": 0, "failures": 0}
    matches = fetch_all_matches()
    if matches is None:
        return status
    status["ok"] = True

    finished = matches[matches["status"].astype(str).str.lower().isin(["ended", "afterpenalties", "afterextratime", "ap", "aet"])]
    status["matches_seen"] = len(finished)

    # refresh match metadata for every match (cheap, already fetched)
    score_cols = [c for c in ("home_score_display", "home_score", "home_score_current") if c in matches.columns]
    away_cols = [c for c in ("away_score_display", "away_score", "away_score_current") if c in matches.columns]
    for _, m in matches.iterrows():
        gid = str(m["game_id"])
        hs = next((m[c] for c in score_cols if pd.notna(m.get(c))), None)
        as_ = next((m[c] for c in away_cols if pd.notna(m.get(c))), None)
        store["matches"][gid] = {
            "home": canon_team(str(m.get("home_team", ""))),
            "away": canon_team(str(m.get("away_team", ""))),
            "round": int(m["week"]) if pd.notna(m.get("week")) else None,
            "status": str(m.get("status", "")),
            "hs": int(hs) if hs is not None and pd.notna(hs) else None,
            "as": int(as_) if as_ is not None and pd.notna(as_) else None,
        }

    new = [gid for gid in (str(g) for g in finished["game_id"]) if gid not in store["lineups"]]
    if not new:
        logger.info("Sofascore: store up to date (%d finished matches)", len(finished))
        return status

    from datafc import lineups_data, shots_data, momentum_data, incidents_data
    for gid in new[:max_new]:
        mdf = _match_row_df(matches, type(matches["game_id"].iloc[0])(gid))
        # lineups (player stats) — required; skip match entirely on failure
        meta = store["matches"].get(gid, {})
        side_map = {"home": meta.get("home", "home"), "away": meta.get("away", "away")}
        try:
            lu = _call(lineups_data, match_df=mdf)
            players: dict = {}
            for (pid, pname, pteam), grp in lu.groupby(["player_id", "player_name", "team"]):
                stats = {r["stat_name"]: r["stat_value"] for _, r in grp.iterrows()
                         if r["stat_name"] in KEEP_STATS and pd.notna(r["stat_value"])}
                if stats:
                    # lineups' team column is the side ("home"/"away") — resolve to team name
                    tname = side_map.get(str(pteam).lower(), canon_team(str(pteam)))
                    players[str(int(pid))] = {"n": pname, "t": tname, "s": stats}
            store["lineups"][gid] = players
            status["new_fetched"] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("lineups fetch failed for %s: %s", gid, e)
            status["failures"] += 1
            continue
        # shots / momentum / incidents — best-effort extras
        for key, fn, cols in (
            ("shots", shots_data, ["player_name", "is_home", "player_coordinates_x",
                                   "player_coordinates_y", "xg", "xgot", "shot_type",
                                   "body_part", "situation", "time"]),
            ("momentum", momentum_data, ["minute", "value"]),
            ("incidents", incidents_data, None),
        ):
            try:
                df = _call(fn, match_df=mdf)
                if df is not None and len(df):
                    if cols:
                        keep = [c for c in cols if c in df.columns]
                        recs = df[keep].to_dict("records") if keep else df.to_dict("records")
                    else:
                        keep = [c for c in df.columns if df[c].dtype.kind in "ifObU"][:12]
                        recs = df[keep].to_dict("records")
                    for r in recs:  # resolve side labels to team names
                        if "is_home" in r:
                            r["team"] = side_map["home"] if r.pop("is_home") else side_map["away"]
                        elif str(r.get("team", "")).lower() in side_map:
                            r["team"] = side_map[str(r["team"]).lower()]
                        # compact coordinate keys for the store/frontend
                        if "player_coordinates_x" in r:
                            r["x"] = r.pop("player_coordinates_x")
                            r["y"] = r.pop("player_coordinates_y")
                    store[key][gid] = json.loads(pd.DataFrame(recs).to_json(orient="records"))
            except Exception as e:  # noqa: BLE001
                logger.debug("%s fetch failed for %s: %s", key, gid, e)
        time.sleep(0.4)  # gentle pacing on top of datafc's own limits

    logger.info("Sofascore: fetched %d new matches (%d failures)", status["new_fetched"], status["failures"])
    return status


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

_SUM_KEYS = [k for k in KEEP_STATS if k not in ("rating", "topSpeed")]


def aggregate_players(store: dict) -> list[dict]:
    """Per-player tournament totals + per-90 from the per-match store."""
    acc: dict[str, dict] = {}
    for gid, players in store.get("lineups", {}).items():
        for pid, p in players.items():
            s = p.get("s", {})
            mins = float(s.get("minutesPlayed", 0) or 0)
            a = acc.setdefault(pid, {"player_id": pid, "name": p["n"], "team": p["t"],
                                     "matches": 0, "_rat_w": 0.0, "_rat_min": 0.0, "top_speed": 0.0,
                                     **{k: 0.0 for k in _SUM_KEYS}})
            a["name"], a["team"] = p["n"], p["t"]  # latest naming wins
            if mins > 0:
                a["matches"] += 1
            for k in _SUM_KEYS:
                a[k] += float(s.get(k, 0) or 0)
            if s.get("rating") is not None and mins > 0:
                a["_rat_w"] += float(s["rating"]) * mins
                a["_rat_min"] += mins
            if s.get("topSpeed"):
                a["top_speed"] = max(a["top_speed"], float(s["topSpeed"]))

    out = []
    for a in acc.values():
        mins = a["minutesPlayed"]
        p90 = max(mins, 1) / 90.0
        rec = {
            "player_id": a["player_id"], "name": a["name"], "team": a["team"],
            "matches": a["matches"], "minutes": int(mins),
            "goals": int(a["goals"]), "assists": int(a["goalAssist"]),
            "xg": round(a["expectedGoals"], 2), "xa": round(a["expectedAssists"], 2),
            "xgot": round(a["expectedGoalsOnTarget"], 2),
            "shots": int(a["totalShots"]), "sot": int(a["onTargetScoringAttempt"]),
            "key_passes": int(a["keyPass"]), "big_chances": int(a["bigChanceCreated"]),
            "passes": int(a["totalPass"]), "pass_pct": round(100 * a["accuratePass"] / max(a["totalPass"], 1), 1),
            "duels_won": int(a["duelWon"]), "tackles_won": int(a["wonTackle"]),
            "interceptions": int(a["interceptionWon"]), "recoveries": int(a["ballRecovery"]),
            "touches": int(a["touches"]),
            "saves": int(a["saves"]), "goals_prevented": round(a["goalsPrevented"], 2),
            "km": round(a["kilometersCovered"], 1), "sprints": int(a["numberOfSprints"]),
            "top_speed": round(a["top_speed"], 1),
            "rating": round(a["_rat_w"] / a["_rat_min"], 2) if a["_rat_min"] > 0 else None,
            "is_gk": bool(a["saves"] > 0 or a["keeperSaveValue"] > 0 or a["savedShotsFromInsideTheBox"] > 0),
        }
        for m in ("goals", "xg", "xa", "xgot", "shots", "key_passes", "assists"):
            rec[f"{m}_90"] = round(rec[m] / p90, 3)
        out.append(rec)
    out.sort(key=lambda r: (-r["goals"], -r["xg"]))
    return out


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="CI probe only")
    ap.add_argument("--backfill", action="store_true", help="fetch everything missing (no cap)")
    args = ap.parse_args()
    if args.probe:
        raise SystemExit(0 if probe() else 1)
    store = load_store()
    st = update_store(store, max_new=1000 if args.backfill else 40)
    save_store(store)
    agg = aggregate_players(store)
    print(f"status={st}  players={len(agg)}  store_matches={len(store['lineups'])}")
    for r in agg[:8]:
        print(f"  {r['name']:24s} {r['team']:12s} {r['minutes']:4d}min G={r['goals']} xG={r['xg']:.2f} "
              f"xA={r['xa']:.2f} KP={r['key_passes']} rat={r['rating']}".encode("ascii", "replace").decode())
