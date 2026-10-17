"""
One pass over a season's raw play-by-play: each final game with a local play-by-play file is
parsed once (`pbp.derive`: typed events, possessions, lineups, stints, shots) and scored with the
win-probability model (`winprob.wpa`), and the results feed three consumers:

* per-game event summaries for the player and team catalogues (and-ones, live-ball turnovers,
  offensive fouls, clutch scoring and on-floor clutch results, possession types for teams),
  kept per game in data/<league>/<season>/pbp_summary.json.gz keyed on the game's fetch stamp and
  the WP model, so an hourly build re-parses only new games, and a machine without a game's raw
  file (CI) keeps the summary an earlier build derived;
* the season WPA totals (sum of the per-game player WPA);
* the game-centre pages (`games.build_game`), through `on_game`, for the games whose page is due.

Definitions
-----------
clutch            the NBA's: last 5:00 of the 4th quarter or overtime with the margin within 5
                  points (both read before the event / at the start of the possession).
and-one           a made field goal followed, at the same clock, by a lone free throw ("1 of 1",
                  not technical or flagrant) by the same shooter.
live-ball turnover a turnover that ESPN credits with a steal.
ATO possession    a possession whose first action follows a timeout taken in the dead ball before it.
transition        a possession of start kind "tr" (after a defensive rebound or a live-ball turnover)
                  whose first shot comes within 6 s; the remainder are half-court.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
from typing import Any, Callable

from oddsmarkets.basketball import pbp as P
from oddsmarkets.basketball import store as bst
from oddsmarkets.basketball.analytics import data_root, fnum
from oddsmarkets.basketball.models import winprob as W

logger = logging.getLogger(__name__)
VERSION = 3
CLUTCH_S = 300
CLUTCH_MARGIN = 5
TRANSITION_S = 6.0


def _sig(*parts: Any) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def game_sig(store: dict, gid: str, wp_model: dict | None) -> str:
    g = (store.get("games") or {}).get(gid) or {}
    return _sig(VERSION, (store.get("meta") or {}).get("fetched", {}).get(gid), g.get("hs"), g.get("as"), g.get("status"),
                (wp_model or {}).get("beta"))


def _clutch(e: dict, league: str) -> bool:
    return int(e.get("period") or 0) >= 4 and float(e.get("clock") or 0) <= CLUTCH_S and \
        abs(int(e.get("hs_before") or 0) - int(e.get("as_before") or 0)) <= CLUTCH_MARGIN


def event_summary(ge: Any, game: dict, wres: dict | None, league: str) -> dict:
    """Per-player and per-team counts from one parsed game (module docstring)."""
    ev = ge.events
    home, away = ge.home, ge.away
    pl: dict[str, dict] = {}
    tm: dict[str, dict] = {home: {}, away: {}}

    def P_(pid):
        return pl.setdefault(str(pid), {})

    def add(d, k, v=1.0):
        d[k] = d.get(k, 0.0) + v

    for i, e in enumerate(ev):
        k = e["kind"]
        ps = [str(x) for x in (e.get("players") or []) if x]
        cl = _clutch(e, league)
        if k == "shot" and ps:
            p = P_(ps[0])
            if cl:
                add(p, "c_fga"); add(p, "c_pts", e.get("pts") or 0)
            if e.get("made"):
                for j in range(i + 1, min(i + 6, len(ev))):
                    f = ev[j]
                    if f["kind"] == "ft" and f.get("clock") == e.get("clock") and f.get("period") == e.get("period"):
                        if f.get("of") == 1 and not f.get("technical") and not f.get("flagrant") and (f.get("players") or [None])[0] == ps[0]:
                            add(p, "and1")
                        break
                    if f["kind"] in ("shot", "tov", "reb"):
                        break
        elif k == "ft" and ps and not e.get("technical"):
            if cl:
                p = P_(ps[0])
                add(p, "c_fta"); add(p, "c_pts", e.get("pts") or 0)
        elif k == "tov" and ps:
            p = P_(ps[0])
            add(p, "tov_pbp")
            if e.get("steal") or len(ps) > 1:
                add(p, "tov_live")
        elif k == "foul" and ps and e.get("offensive") and not e.get("technical"):
            add(P_(ps[0]), "off_foul")
    # possessions: clutch on-floor results, possession types
    poss = ge.possessions
    first_action: dict[int, int] = {}
    for q_i, q in enumerate(poss):
        s, e_ = int(q.get("start_i", 0)), int(q.get("end_i", 0))
        for j in range(s, min(e_ + 1, len(ev))):
            if ev[j]["kind"] in ("shot", "ft", "tov"):
                first_action[q_i] = j
                break
    timeouts = [e["i"] for e in ev if e["kind"] == "timeout"]
    prev_end = -1
    for q_i, q in enumerate(poss):
        team = q.get("team")
        if team not in tm:
            prev_end = int(q.get("end_i", prev_end))
            continue
        opp = away if team == home else home
        s = int(q.get("start_i", 0))
        fa = first_action.get(q_i, int(q.get("end_i", s)))
        e0 = ev[min(s, len(ev) - 1)] if ev else {}
        pts = float(q.get("pts") or 0)
        T = tm[team]
        add(T, "poss"); add(T, "pts", pts)
        kind = q.get("start_kind")
        first_t = ev[fa]["t"] if fa < len(ev) else q.get("end_t")
        fast = kind == "tr" and (fnum(first_t) or 0) - (fnum(q.get("start_t")) or 0) <= TRANSITION_S
        add(T, "poss_tr" if fast else "poss_hc"); add(T, "pts_tr" if fast else "pts_hc", pts)
        if kind != "tr" and any(prev_end < t < fa for t in timeouts):
            add(T, "poss_ato"); add(T, "pts_ato", pts)
        prev_end = int(q.get("end_i", prev_end))
        if e0 and _clutch(e0, league):
            add(T, "c_poss"); add(T, "c_pf", pts)
            add(tm[opp], "c_poss_d"); add(tm[opp], "c_pa", pts)
            dur = max(0.0, (fnum(q.get("end_t")) or 0) - (fnum(q.get("start_t")) or 0))
            for p in q.get("players_off") or []:
                d = P_(p); add(d, "c_poss_o"); add(d, "c_pf", pts); add(d, "c_sec", dur)
            for p in q.get("players_def") or []:
                d = P_(p); add(d, "c_poss_d"); add(d, "c_pa", pts); add(d, "c_sec", dur)
    out = {"players": pl, "teams": tm}
    if wres:
        team_of = W._team_of(game)
        wp = {}
        for pid, r in (wres.get("players") or {}).items():
            wp[pid] = {k: r.get(k) for k in ("team", "wpa", "pos", "neg", "clutch_wpa", "li_wpa")}
            wp[pid]["dwpa"] = 0.0
        for row in wres.get("plays") or []:
            for pid, c in (row.get("credit") or {}).items():
                if team_of.get(pid) and row.get("team") and team_of[pid] != str(row["team"]) and pid in wp:
                    wp[pid]["dwpa"] += c
        out["wpa"] = wp
        out["excitement"] = wres.get("excitement")
        out["comeback"] = wres.get("comeback")
        out["clutch_game"] = any(r.get("clutch") for r in wres.get("plays") or [])
    return out


def _cache_path(league: str, season: int):
    """data/<L>/<S>/pbp_summary.json.gz: build output deployed with the site, so a machine without the raw
    play-by-play (CI for every game it did not fetch itself) restores it with the previous deploy."""
    return data_root() / league / str(season) / "pbp_summary.json.gz"


def season_pass(league: str, season: int, store: dict, games: dict, wp_model: dict | None,
                on_game: Callable[[str, dict, dict], None] | None = None, want_page: Callable[[str], bool] | None = None,
                use_cache: bool = True) -> dict:
    """{"games": {gid: summary}, "n_parsed", "n_cached", "n_missing"} over the final games in `games` with
    play-by-play. `on_game(gid, game, parsed)` receives {"derive", "wpa"} for every game parsed this run;
    games whose summary is cached are parsed only when `want_page(gid)` asks for their page."""
    path = _cache_path(league, season)
    cache = {}
    if use_cache:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                c = json.load(fh)
            if c.get("version") == VERSION:
                cache = c.get("games") or {}
        except (OSError, ValueError, EOFError):
            cache = {}
    out, n_parsed, n_cached, n_missing = {}, 0, 0, 0
    model_ok = bool(wp_model and wp_model.get("ok"))
    for gid, g in games.items():
        if g.get("status") not in ("post", "in") or not g.get("has_pbp"):
            continue
        sig = game_sig(store, gid, wp_model if model_ok else None)
        cached = cache.get(gid)
        need_page = bool(want_page and want_page(gid))
        if cached and cached.get("sig") == sig and not need_page:
            out[gid] = cached
            n_cached += 1
            continue
        raw = bst.load_pbp(league, season, gid)
        if raw is None:
            if cached:
                out[gid] = cached                 # keep what an earlier run derived
            else:
                n_missing += 1
            continue
        try:
            d = P.derive(raw, g, league, season)
            wres = W.wpa(g, raw, wp_model, d["events"], league) if model_ok else None
            summ = event_summary(d["events"], g, wres, league) if g.get("status") == "post" else {}
        except Exception as exc:  # noqa: BLE001 - one bad game never stops the season
            logger.warning("%s %s game %s: pbp pass failed: %s", league, season, gid, exc)
            continue
        summ["sig"] = sig
        if g.get("status") == "post":
            out[gid] = summ
        n_parsed += 1
        if on_game:
            try:
                on_game(gid, g, {"derive": d, "wpa": wres, "raw": raw})
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s %s game %s: page callback failed: %s", league, season, gid, exc)
    if use_cache:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump({"version": VERSION, "games": _round(out)}, fh, separators=(",", ":"), default=str)
            tmp.replace(path)
        except OSError:
            pass
    return {"games": out, "n_parsed": n_parsed, "n_cached": n_cached, "n_missing": n_missing}


def _round(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _round(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_round(v) for v in o]
    if isinstance(o, float):
        return round(o, 5)
    return o


def season_totals(summaries: dict[str, dict]) -> dict:
    """Season sums: {"players": {pid: counts}, "teams": {tid: counts}, "wpa": {pid: {team,wpa,pos,neg,clutch_wpa,li_wpa,dwpa,games}}}."""
    pl: dict[str, dict] = {}
    tm: dict[str, dict] = {}
    wp: dict[str, dict] = {}
    for s in summaries.values():
        for pid, d in (s.get("players") or {}).items():
            o = pl.setdefault(pid, {})
            for k, v in d.items():
                o[k] = o.get(k, 0.0) + (v or 0.0)
        for tid, d in (s.get("teams") or {}).items():
            o = tm.setdefault(tid, {"games": 0, "clutch_games": 0})
            o["games"] += 1
            for k, v in d.items():
                o[k] = o.get(k, 0.0) + (v or 0.0)
        for pid, d in (s.get("wpa") or {}).items():
            o = wp.setdefault(pid, {"team": d.get("team"), "wpa": 0.0, "pos": 0.0, "neg": 0.0, "clutch_wpa": 0.0, "li_wpa": 0.0,
                                    "dwpa": 0.0, "games": 0})
            for k in ("wpa", "pos", "neg", "clutch_wpa", "li_wpa", "dwpa"):
                o[k] += float(d.get(k) or 0.0)
            o["games"] += 1
            o["team"] = d.get("team") or o["team"]
    return {"players": pl, "teams": tm, "wpa": wp}
