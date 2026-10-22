"""
Reading a cup's Sofascore store.

Same store shape as the leagues. Two things are cup-specific: the group a match
belongs to (from the tournament label), and the knockout ties — which are read
both as decided results to force, and as known pairings that fix the bracket
once the draw has been made.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from oddsmarkets.football.competitions.cup.config import COUNTRY_LEAGUE, CupConfig
from oddsmarkets.football.competitions.cup.season_state import CupState
from oddsmarkets.football.competitions.league.season_state import LeagueMatch
from oddsmarkets.football.competitions.league.store import _POSTPONED, _status_of, current_season_id
from oddsmarkets.football.competitions.liga import store as _liga

logger = logging.getLogger(__name__)

# Cup team names are canonicalised at fetch time (through the club's own league
# registry), so the shared readers get a pass-through registry.
NO_REGISTRY: dict[str, str] = {}


def iter_matches(store: dict[str, Any], season_id: int | None = None) -> Iterable[tuple[LeagueMatch, dict]]:
    for gid, raw in (store.get("matches") or {}).items():
        if season_id is not None and raw.get("season_id") != season_id:
            continue
        if raw.get("superseded_by"):                  # the old copy of a re-listed fixture (liga.store.mark_superseded)
            continue
        home, away = str(raw.get("home", "")), str(raw.get("away", ""))
        if not home or not away or raw.get("stage") in ("qualifying", "other"):
            continue
        hs, as_ = raw.get("hs"), raw.get("as")
        yield LeagueMatch(
            game_id=str(gid), home_team=home, away_team=away,
            home_goals=int(hs) if hs is not None else None,
            away_goals=int(as_) if as_ is not None else None,
            date=_liga._parse_date(raw.get("date")),
            round_name=str(raw["round"]) if raw.get("round") is not None else None,
            stage="playoff" if raw.get("stage") == "playoff" else "league",
            status=_status_of(raw.get("status")),
            winner=raw.get("winner") or None,
            postponed=str(raw.get("status") or "").strip().lower() in _POSTPONED,
        ), raw


# Ties in a fully drawn named round.
FULL_TIES = {"r64": 32, "r32": 16, "r16": 8, "qf": 4, "sf": 2, "final": 1}


def _tie_winners(legs: list[dict]) -> set[str]:
    """The winners of the decided ties among these matches (legs of one tie share the pair of clubs)."""
    ties: dict[frozenset, list[dict]] = {}
    for raw in legs:
        ties.setdefault(frozenset((str(raw.get("home")), str(raw.get("away")))), []).append(raw)
    out: set[str] = set()
    for pair, ms in ties.items():
        if len(pair) != 2 or any(_status_of(m.get("status")) != "finished" or m.get("hs") is None or m.get("as") is None for m in ms):
            continue
        goals: dict[str, int] = {}
        for m in ms:
            goals[str(m["home"])] = goals.get(str(m["home"]), 0) + int(m["hs"])
            goals[str(m["away"])] = goals.get(str(m["away"]), 0) + int(m["as"])
        a, b = sorted(pair)
        if goals.get(a, 0) != goals.get(b, 0):
            out.add(a if goals.get(a, 0) > goals.get(b, 0) else b)
            continue
        ms.sort(key=lambda m: str(m.get("date") or ""))
        win = next((m.get("agg_winner") or m.get("winner") for m in reversed(ms) if m.get("agg_winner") or m.get("winner")), None)
        if win:
            out.add(str(win))
    return out


def normalize_knockout_rounds(store: dict[str, Any], cfg: CupConfig) -> int:
    """
    Put a national cup's rounds on its bracket, in place; returns the number of matches relabelled.

    Sofascore names a national cup's rounds "Round 1", "Round 2", ...: only "round-1" reaches a knockout key (the MLS
    table's), and a bare number outside the bracket became "qualifying", which the simulator skips. So until 22 Oct 2026
    the EFL Cup simulated from its first round alone (West Ham, out in the third round, 21% to win), the DFB-Pokal
    ignored its second-round draw, and the FA Cup and KNVB Beker filed their qualifying first rounds under the first
    round proper (a club in two first-round ties: "reach" 2.0). Per season:

    1. a bare round number N becomes "rN" when the bracket has an "rN";
    2. a club in two different ties of one round marks the earlier ties as an earlier stage: every match of that round
       before the first club's latest tie is qualifying (same opponents, a replay or second leg, is one tie);
    3. a round cannot start before the previous bracket round: its matches dated earlier are qualifying;
    4. a bracket that skips one of the cup's real rounds keeps only the rounds after the gap (see below).
    """
    if getattr(cfg, "kind", "") != "knockout":
        return 0
    order = [code for code, _legs in (cfg.rounds or ())]
    bracket = set(order)
    seasons: dict[Any, list[tuple[dict, datetime | None]]] = {}
    for raw in (store.get("matches") or {}).values():
        if not isinstance(raw, dict) or raw.get("superseded_by") or raw.get("stage") not in ("league", "qualifying", "playoff"):
            continue
        seasons.setdefault(raw.get("season_id"), []).append((raw, _liga._parse_date(raw.get("date"))))
    changed = 0
    for rows in seasons.values():
        key: dict[int, str | None] = {}
        for raw, _d in rows:
            r = raw.get("round")
            s = str(r).strip() if r is not None else ""
            if s.isdigit() and f"r{int(s)}" in bracket:
                key[id(raw)] = f"r{int(s)}"
            elif raw.get("stage") == "playoff" and s in bracket:
                key[id(raw)] = s
            else:
                key[id(raw)] = None                   # outside the bracket: left as it is
        for code in order:
            ms = [(raw, d) for raw, d in rows if key[id(raw)] == code and d is not None]
            ties: dict[str, dict[frozenset, datetime]] = {}
            for raw, d in ms:
                pair = frozenset((str(raw.get("home")), str(raw.get("away"))))
                for t in pair:
                    first = ties.setdefault(t, {}).get(pair)
                    ties[t][pair] = d if first is None or d < first else first
            late = [max(by_pair.values()) for by_pair in ties.values() if len(by_pair) > 1]
            if late:
                cutoff = min(late) - timedelta(days=1)
                for raw, d in ms:
                    if d < cutoff:
                        key[id(raw)] = "q"
        prev_start: datetime | None = None
        for code in order:
            ms = [(raw, d) for raw, d in rows if key[id(raw)] == code and d is not None]
            if prev_start is not None:
                for raw, d in ms:
                    if d < prev_start:
                        key[id(raw)] = "q"
            kept = [d for raw, d in ms if key[id(raw)] == code]
            if kept:
                prev_start = min(kept)
        # 4. consecutive rounds: when a later named round is fully drawn (8 ties for "r16", ...), every winner of the
        # bracket round before it must be in it; if one is missing, the configured bracket skips a round the cup really
        # has (the Copa do Brasil's fourth and fifth, the Belgian Cup's seventh) and that round and every earlier one
        # are left out, as before this function existed.
        present = [c for c in order if any(key[id(raw)] == c for raw, _d in rows)]
        for i in range(len(present) - 1, 0, -1):
            nxt, cur = present[i], present[i - 1]
            full = FULL_TIES.get(nxt)
            nxt_pairs = {frozenset((str(r.get("home")), str(r.get("away")))) for r, _d in rows if key[id(r)] == nxt}
            if full is None or len(nxt_pairs) != full:
                continue
            in_next = {t for p in nxt_pairs for t in p}
            winners = _tie_winners([r for r, _d in rows if key[id(r)] == cur])
            if winners and not winners <= in_next:
                for raw, _d in rows:
                    if key[id(raw)] in present[:i]:
                        key[id(raw)] = "q"
                break
        for raw, _d in rows:
            k = key[id(raw)]
            if k is None:
                continue
            want = ("qualifying", raw.get("round")) if k == "q" else ("playoff", k)
            if (raw.get("stage"), raw.get("round")) != want:
                raw["stage"], raw["round"] = want
                changed += 1
    return changed


def tie_results(matches: list[tuple[LeagueMatch, dict]]) -> tuple[dict[frozenset, str], dict[str, list[tuple[str, str]]]]:
    """
    Decided ties and known pairings from the knockout matches.

    Legs of one tie share a round key and a pair of clubs. A tie is decided when
    every leg is finished: on aggregate, or by Sofascore's aggregate winner when
    level (which covers a shootout). A single-leg round decides on its own
    result or recorded winner.
    """
    by_tie: dict[tuple[str, frozenset], list[tuple[LeagueMatch, dict]]] = {}
    for m, raw in matches:
        by_tie.setdefault((m.round_name or "", frozenset((m.home_team, m.away_team))), []).append((m, raw))

    results: dict[frozenset, str] = {}
    pairs: dict[str, list[tuple[str, str]]] = {}
    for (rnd, pair), legs in by_tie.items():
        # A postponed copy of a fixture played under another id with the same home side is not a leg: counted as one,
        # the tie never closed (Everton 1-0 Wolves, EFL Cup third round 2026, was simulated again) and its "pair" read
        # Everton v Everton. A two-legged tie's legs have different home sides, so a postponed second leg stays.
        # A cancelled match is no leg at all (Forge FC v Sporting San Miguelito, CONCACAF 2026: the club then played LA
        # Galaxy, and its "reach" read 2.0).
        legs = [(m, raw) for m, raw in legs if str(raw.get("status") or "").strip().lower() not in ("canceled", "cancelled")]
        if not legs:
            continue
        played_homes = {m.home_team for m, _ in legs if not m.postponed}
        legs = [(m, raw) for m, raw in legs if not (m.postponed and m.home_team in played_homes)]
        legs.sort(key=lambda mr: (mr[0].date or datetime.max.replace(tzinfo=timezone.utc), mr[0].game_id))
        first, last = legs[0][0], legs[-1][0]
        # Leg-one host first, leg-two host second; a single match lists home then away.
        ordered = (first.home_team, last.home_team) if len(legs) > 1 else (first.home_team, first.away_team)
        pairs.setdefault(rnd, []).append(ordered)
        if not all(m.is_finished for m, _ in legs):
            continue
        goals: dict[str, int] = {}
        for m, _ in legs:
            goals[m.home_team] = goals.get(m.home_team, 0) + int(m.home_goals)
            goals[m.away_team] = goals.get(m.away_team, 0) + int(m.away_goals)
        a, b = sorted(pair)
        if goals.get(a, 0) != goals.get(b, 0):
            results[pair] = a if goals.get(a, 0) > goals.get(b, 0) else b
            continue
        agg = next((raw.get("agg_winner") for _, raw in reversed(legs) if raw.get("agg_winner")), None)
        win = agg or next((m.winner for m, _ in reversed(legs) if m.winner), None)
        if win:
            results[pair] = win
    return results, pairs


def cup_state_from_store(store: dict[str, Any], cfg: CupConfig, groups: dict[str, list[str]] | None = None) -> CupState:
    season_id = current_season_id(store)
    finished: list[LeagueMatch] = []
    remaining: list[LeagueMatch] = []
    playoff: list[tuple[LeagueMatch, dict]] = []
    seen: dict[str, None] = {}
    grp: dict[str, list[str]] = {}
    ids: dict[str, int] = {}
    league_of: dict[str, str] = {}

    from dataclasses import replace as _replace

    for m, raw in iter_matches(store, season_id):
        # A fixed bracket has no league phase: every match is a tie, however
        # Sofascore labels the round ("Round 2" carries no knockout marker).
        if cfg.kind == "fixed" and not m.is_playoff:
            m = _replace(m, stage="playoff")
        for side, id_key, c_key in (("home", "home_id", "home_country"), ("away", "away_id", "away_country")):
            name = getattr(m, f"{side}_team")
            if raw.get(id_key):
                ids.setdefault(name, int(raw[id_key]))
            slug = COUNTRY_LEAGUE.get(str(raw.get(c_key) or ""))
            if slug:
                league_of.setdefault(name, slug)
        if m.is_playoff:
            playoff.append((m, raw))
            seen.setdefault(m.home_team)
            seen.setdefault(m.away_team)
            continue
        seen.setdefault(m.home_team)
        seen.setdefault(m.away_team)
        g = raw.get("group")
        if g:
            for t in (m.home_team, m.away_team):
                if t not in grp.setdefault(g, []):
                    grp[g].append(t)
        (finished if m.is_finished else remaining).append(m)

    # A club whose only matches this season sit in rounds Sofascore files under
    # "qualification" (a national cup's early rounds: the EFL Cup's second to fourth,
    # where the Premier League enters) still has a league to be priced from; without
    # this every such tie got the pool's average line on both sides.
    for raw in (store.get("matches") or {}).values():
        if not isinstance(raw, dict) or (season_id is not None and raw.get("season_id") != season_id):
            continue
        for side, id_key, c_key in (("home", "home_id", "home_country"), ("away", "away_id", "away_country")):
            name = str(raw.get(side) or "")
            if not name:
                continue
            if raw.get(id_key):
                ids.setdefault(name, int(raw[id_key]))
            slug = COUNTRY_LEAGUE.get(str(raw.get(c_key) or ""))
            if slug:
                league_of.setdefault(name, slug)

    if cfg.kind in ("groups", "regional_swiss", "international"):
        groups_out = grp or (groups or {})
    else:
        groups_out = {}
    # A fixed bracket's participants are the configured names plus anyone who has
    # played; the league phase is empty.
    teams = list(seen)
    if cfg.kind == "fixed":
        for tie in cfg.ties:
            for slot in (tie.home, tie.away):
                if ":" not in slot.source and slot.source not in teams:
                    teams.append(slot.source)
    results, pairs = tie_results(playoff)
    return CupState(
        cfg=cfg, teams=teams, finished=finished, remaining=remaining, groups=groups_out,
        playoff_results=results, known_pairs=pairs, playoff_matches=[m for m, _ in playoff],
        team_ids=ids, team_league=league_of,
        season_name=(store.get("meta") or {}).get("season_name"),
    )


def international_training_frame(store: dict[str, Any], neutral: bool = False, weight: float = 1.0, include_xg: bool = True):
    """Every finished national-team match in the store, for the international fit."""
    df = training_frame(store, include_xg=include_xg)
    if len(df):
        df["neutral"] = bool(neutral)
        df["weight"] = float(weight)
    return df


def training_frame(store: dict[str, Any], include_xg: bool = True):
    """Every finished match in the store (all stages, all seasons), for the pooled fit."""
    import pandas as pd

    xg = _liga.team_xg_map(store, registry=NO_REGISTRY) if include_xg else {}
    rows = []
    for m, raw in iter_matches(store):
        if not m.is_finished or m.date is None:
            continue
        row = {
            "game_id": m.game_id, "home_team": m.home_team, "away_team": m.away_team,
            "home_goals": int(m.home_goals), "away_goals": int(m.away_goals),
            "match_date": m.date, "weight": 1.0,
            "home_country": raw.get("home_country"), "away_country": raw.get("away_country"),
            "neutral": bool(raw.get("neutral")),
        }
        if m.game_id in xg:
            row["home_xg"], row["away_xg"] = xg[m.game_id]
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["game_id", "home_team", "away_team", "home_goals", "away_goals", "match_date", "weight"])
    df = pd.DataFrame(rows)
    df["match_date"] = pd.to_datetime(df["match_date"], utc=True)
    return df.sort_values("match_date").reset_index(drop=True)


def team_xg_map(store):
    return _liga.team_xg_map(store, registry=NO_REGISTRY)


def aggregate_players(store):
    return _liga.aggregate_players(store, registry=NO_REGISTRY)


def shots_by_player(store):
    return _liga.shots_by_player(store, registry=NO_REGISTRY)


def match_details(store, limit_ratings: int = 30):
    return _liga.match_details(store, limit_ratings=limit_ratings, registry=NO_REGISTRY)


def player_match_logs(store):
    return _liga.player_match_logs(store, registry=NO_REGISTRY)


def team_match_stats(store):
    return _liga.team_match_stats(store, registry=NO_REGISTRY)
