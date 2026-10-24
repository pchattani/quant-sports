"""
The league race: the payload fields behind a league's Race tab (docs/site/assets/app/race.js).

    stakes_payload(results, cfg)        probs.json "stakes": what rides on each of the next fixtures, from the
                                        season simulation split by that fixture's result (LeagueSimulator.stakes)
    set_pieces(store, norm)             analytics.json "set_pieces": xG for and against per match from set pieces,
                                        open play and fast breaks, with percentiles against the league
    roll_daily(prev, snapshot, ...)     history_store.json / history.json "daily": one title / band / relegation
                                        snapshot per UTC day for the whole season (the hourly snapshots keep
                                        only the last 400 runs, about 17 days)

No look-ahead: the stakes and the daily snapshots are this build's own simulation, and the set-piece numbers
read only matches already played. Everything is plain dicts and stdlib so the builder can call it anywhere.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

# ── stakes ───────────────────────────────────────────────────────────────────

# How much each metric counts towards a fixture's overall swing: the title most, the drop next, then the first
# up band (Champions League places), then any other band.
STAKE_WEIGHTS = {"title": 1.0, "down": 0.8, "up1": 0.7, "up": 0.4}
STAKE_TEAMS = 4           # at most this many clubs per metric in the payload
STAKE_MIN_MOVE = 0.015    # a club is listed only when its chance moves at least this much between results
STAKE_MIN_N = 200         # a result produced in fewer simulations than this has no conditional chances
STAKE_SE = 3.0            # ... and the move must exceed this many standard errors of the difference


def _se(p1: float, n1: int, p2: float, n2: int) -> float:
    return math.sqrt(max(p1 * (1 - p1), 1e-9) / max(n1, 1) + max(p2 * (1 - p2), 1e-9) / max(n2, 1))


def _metric_rows(cond: list, n: list[int], teams: list[str]) -> tuple[float, dict[str, list[float | None]]]:
    """(swing, {team: [p|H, p|D, p|A]}) for one metric. The swing is half the summed absolute difference between
    the home-win and away-win worlds over the clubs whose difference is beyond noise: the share of that
    metric's places the result decides."""
    if not cond or cond[0] is None or cond[2] is None or n[0] < STAKE_MIN_N or n[2] < STAKE_MIN_N:
        return 0.0, {}
    swing = 0.0
    moved = []
    for i, t in enumerate(teams):
        ph, pa = cond[0][i], cond[2][i]
        pd = cond[1][i] if cond[1] is not None and n[1] >= STAKE_MIN_N else None
        vals = [v for v in (ph, pd, pa) if v is not None]
        rng = max(vals) - min(vals)
        noise = STAKE_SE * _se(ph, n[0], pa, n[2])
        if abs(ph - pa) > noise:
            swing += abs(ph - pa) / 2
        if rng >= STAKE_MIN_MOVE and rng > noise:
            moved.append((rng, t, [round(ph, 3), None if pd is None else round(pd, 3), round(pa, 3)]))
    moved.sort(key=lambda x: (-x[0], x[1]))
    return swing, {t: v for _, t, v in moved[:STAKE_TEAMS]}


def stakes_payload(results, cfg) -> list[dict]:
    """probs.json "stakes": [{"id", "home", "away", "date", "p": [H, D, A] (share of simulations), "swing",
    "m": [{"key", "label", "kind", "swing", "teams": {team: [p|H, p|D, p|A]}}]}], soonest first. A metric with
    no club moving beyond noise is left out; a fixture with nothing left in play has an empty "m"."""
    teams = list(results.teams)
    bands = list(cfg.bands)
    first_up = next((b.key for b in bands if b.kind == "up"), None)
    out = []
    for s in getattr(results, "stakes", None) or []:
        n = [int(x) for x in s.get("n") or [0, 0, 0]]
        tot = sum(n) or 1
        metrics = []
        total = 0.0
        sw, rows = _metric_rows(s.get("title") or [], n, teams)
        if rows:
            metrics.append({"key": "title", "label": "Title", "kind": "title", "swing": round(sw, 4), "teams": rows})
        total += STAKE_WEIGHTS["title"] * sw
        for b in bands:
            sw, rows = _metric_rows((s.get("bands") or {}).get(b.key) or [], n, teams)
            w = STAKE_WEIGHTS["down"] if b.kind == "down" else STAKE_WEIGHTS["up1"] if b.key == first_up else STAKE_WEIGHTS["up"]
            total += w * sw
            if rows:
                metrics.append({"key": b.key, "label": b.label, "kind": b.kind, "swing": round(sw, 4), "teams": rows})
        out.append({"id": s.get("id"), "home": s.get("home"), "away": s.get("away"), "date": s.get("date"),
                    "p": [round(x / tot, 3) for x in n], "swing": round(total, 4), "m": metrics})
    return out


# ── set pieces ───────────────────────────────────────────────────────────────

SET_PIECE = {"corner", "set-piece", "free-kick", "throw-in-set-piece"}
OPEN_PLAY = {"assisted", "regular", "fast-break"}
FAST_BREAK = {"fast-break"}
PENALTY = {"penalty"}
MIN_MATCHES = 3


def _pct(values: dict[str, float], lower: bool = False) -> dict[str, int]:
    """Rank-based 0-100, 100 always the best (the convention of analytics.json profiles)."""
    from oddsmarkets.football.analytics.insights import percentile_ranks
    return percentile_ranks(values, lower)


def set_pieces(store: dict, norm=None) -> dict:
    """analytics.json "set_pieces": {"teams": {team: {"matches", "sp_xg", "sp_xga", "op_xg", "op_xga", "fb_xg",
    "fb_xga", "pen_xg", "sp_share", "pct": {key: 0-100}}}, "keys": {...}} per match, over the season's matches
    with a shot map. The store passed is already the season view. Clubs under MIN_MATCHES matches are left
    out; {} when no match has a shot map."""
    norm = norm or (lambda x: x)
    matches = store.get("matches") or {}
    shots = store.get("shots") or {}
    acc: dict[str, dict[str, float]] = {}
    for gid, sh in shots.items():
        m = matches.get(str(gid)) or matches.get(gid)
        if not m or m.get("status") != "finished" or not isinstance(sh, list) or not sh:
            continue
        if (m.get("stage") or "league") != "league":
            continue
        home, away = norm(m.get("home")), norm(m.get("away"))
        if not home or not away:
            continue
        sums = {True: {"sp": 0.0, "op": 0.0, "fb": 0.0, "pen": 0.0}, False: {"sp": 0.0, "op": 0.0, "fb": 0.0, "pen": 0.0}}
        for s in sh:
            if not isinstance(s, dict):
                continue
            xg = s.get("xg")
            try:
                xg = float(xg)
            except (TypeError, ValueError):
                continue
            if math.isnan(xg):
                continue
            sit = s.get("situation")
            side = bool(s.get("is_home"))
            if sit in SET_PIECE:
                sums[side]["sp"] += xg
            elif sit in PENALTY:
                sums[side]["pen"] += xg
            elif sit in OPEN_PLAY:
                sums[side]["op"] += xg
                if sit in FAST_BREAK:
                    sums[side]["fb"] += xg
        for team, own, opp in ((home, sums[True], sums[False]), (away, sums[False], sums[True])):
            a = acc.setdefault(team, {"matches": 0, "sp_xg": 0.0, "sp_xga": 0.0, "op_xg": 0.0, "op_xga": 0.0,
                                      "fb_xg": 0.0, "fb_xga": 0.0, "pen_xg": 0.0})
            a["matches"] += 1
            a["sp_xg"] += own["sp"]
            a["sp_xga"] += opp["sp"]
            a["op_xg"] += own["op"]
            a["op_xga"] += opp["op"]
            a["fb_xg"] += own["fb"]
            a["fb_xga"] += opp["fb"]
            a["pen_xg"] += own["pen"]
    teams = {}
    for t, a in acc.items():
        n = a["matches"]
        if n < MIN_MATCHES:
            continue
        row = {"matches": n}
        for k in ("sp_xg", "sp_xga", "op_xg", "op_xga", "fb_xg", "fb_xga", "pen_xg"):
            row[k] = round(a[k] / n, 3)
        np_xg = a["sp_xg"] + a["op_xg"]
        row["sp_share"] = round(a["sp_xg"] / np_xg, 3) if np_xg > 0 else None
        teams[t] = row
    if len(teams) < 4:
        return {}
    lower = {"sp_xga": True, "op_xga": True, "fb_xga": True}
    pct: dict[str, dict[str, int]] = {t: {} for t in teams}
    for k in ("sp_xg", "sp_xga", "op_xg", "op_xga", "fb_xg", "fb_xga"):
        ranks = _pct({t: r[k] for t, r in teams.items()}, lower.get(k, False))
        for t, v in ranks.items():
            pct[t][k] = v
    for t in teams:
        teams[t]["pct"] = pct[t]
    return {"teams": teams, "min_matches": MIN_MATCHES,
            "keys": {"sp_xg": "Set-piece xG for", "sp_xga": "Set-piece xG against", "op_xg": "Open-play xG for",
                     "op_xga": "Open-play xG against", "fb_xg": "Fast-break xG for", "fb_xga": "Fast-break xG against",
                     "pen_xg": "Penalty xG", "sp_share": "Share of non-penalty xG from set pieces"}}


# ── the daily race history ───────────────────────────────────────────────────

DAILY_KEEP = 400          # days: a season and its pre-season
DAILY_MIN = 0.0005        # a club below this in a metric is left out of that day's snapshot


def _day(ts: str | None) -> str | None:
    if not ts:
        return None
    s = str(ts)
    return s[:10] if len(s) >= 10 and s[4] == "-" else None


def _slim(d: dict | None) -> dict:
    return {t: round(float(p), 4) for t, p in (d or {}).items() if p is not None and float(p) >= DAILY_MIN}


def daily_entry(snapshot: dict, metrics=("title", "band", "relegation", "shield")) -> dict:
    """One day's slimmed snapshot: {"d": day, "ts", metric: {team: p}, "band_key"}."""
    e = {"d": _day(snapshot.get("ts")), "ts": snapshot.get("ts")}
    for k in metrics:
        if isinstance(snapshot.get(k), dict):
            e[k] = _slim(snapshot[k])
    if snapshot.get("band_key"):
        e["band_key"] = snapshot["band_key"]
    return e


def roll_daily(prev: dict | None, snapshots: list[dict], season: str | None, teams) -> dict:
    """The daily race history: {"season", "days": [daily_entry, ...]} with one entry per UTC day (the day's latest
    run), oldest first, the last DAILY_KEEP days. A new season starts it afresh. The first call seeds it from
    the hourly snapshots still in the store, keeping only those whose clubs are all in this season's league
    (an hourly store spanning a season change keeps last season's runs too)."""
    team_set = set(teams or [])
    keep = prev if isinstance(prev, dict) and prev.get("season") == season else None
    days: dict[str, dict] = {}
    if keep:
        for e in keep.get("days") or []:
            if isinstance(e, dict) and e.get("d"):
                days[e["d"]] = e
    for s in snapshots or []:
        if not isinstance(s, dict) or not _day(s.get("ts")):
            continue
        clubs = set((s.get("title") or {}).keys()) | set((s.get("relegation") or {}).keys())
        if team_set and clubs and not clubs <= team_set:
            continue
        e = daily_entry(s)
        cur = days.get(e["d"])
        if cur is None or str(cur.get("ts") or "") <= str(e.get("ts") or ""):
            days[e["d"]] = e
    out = [days[d] for d in sorted(days)][-DAILY_KEEP:]
    return {"season": season, "days": out}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
