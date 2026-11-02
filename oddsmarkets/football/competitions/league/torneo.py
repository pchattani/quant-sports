"""
Seasons played as several tournaments a year: Colombia, Uruguay and Peru.

The calendar-year leagues of the Andes and the River Plate split a season into an Apertura and a Clausura
(Colombia's Finalización), Uruguay adds an Intermedio between them, and each keeps an aggregate table over the
year (the reclasificación, the Tabla Anual, the Tabla Acumulada) that decides the continental places and, in
Peru, relegation. Colombia and Uruguay relegate on a promedio: points per match over two or three seasons.

The formats are data (`config.TorneoFormat` and `config.StageFormat`); this module reads a store into a season
state and simulates the rest of the season, vectorised over simulations like the plain-league simulator
(`simulator.py`): one (n_sims, n_teams) array per table, every fixture still to play sampled once per simulation.
Playoff legs whose clubs depend on the simulated tables (the cuadrangulares, a knockout, the season playoffs) are
sampled per simulation from the same score distributions (`core.simulation.PairSampler`); a leg already played is
taken as played, matched by its round and its two clubs.

What the simulation does not follow, and the methodology tab says so:
  - a tie on points for first place settled by a play-off match (Uruguay, Chile) is ranked on goal difference;
  - fair play and the away-goals and fewest-conceded criteria are not simulated (the table order uses points, goal
    difference, goals scored, and wins where the competition ranks on them);
  - when the regulation leaves a host or a draw open (Colombia's quarter-final draw, Uruguay's semi-final venue)
    the simulation draws it or plays it at the better-placed club's ground.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

import numpy as np

from oddsmarkets.football.competitions.league.config import LeagueConfig, StageFormat, TorneoFormat
from oddsmarkets.football.competitions.liga import store as _liga
from oddsmarkets.football.competitions.liga.season_state import TeamRecord
from oddsmarkets.football.core.simulation import PairSampler, ScoreSampler, count_positions, rank_table
from oddsmarkets.football.sources.teams import normalize_team_name

logger = logging.getLogger(__name__)

SEASON = "season"           # the season playoffs (Uruguay's semi-final and final, Peru's playoffs)
_FINISHED = {"finished"} | _liga.FINISHED_STATUSES
_LIVE = {"inprogress"} | _liga.LIVE_STATUSES
_POSTPONED = {"postponed", "delayed", "interrupted", "suspended"}
_DEAD = {"canceled", "cancelled", "abandoned", "removed"}
# Round keys a knockout tie can carry; anything else is matched on the pair of clubs alone.
_ROUNDS = ("qf", "sf", "final")


# ── matches ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TorneoMatch:
    game_id: str
    home: str
    away: str
    hg: int | None
    ag: int | None
    date: datetime | None
    round: str | None
    stage: str                      # "league" (a round robin or the Intermedio groups) or "playoff"
    status: str                     # finished | live | scheduled | postponed | dead
    torneo: str | None              # the stage key, None for the season playoffs
    group: str | None
    season_id: int | None
    winner: str | None = None       # a level knockout match decided on penalties
    agg_winner: str | None = None   # a two-legged tie's winner, on its second leg

    @property
    def done(self) -> bool:
        return self.status == "finished" and self.hg is not None and self.ag is not None

    @property
    def is_playoff(self) -> bool:
        return self.stage == "playoff"


def _status(raw: object) -> str:
    low = str(raw or "").strip().lower().replace(" ", "")
    if low in _FINISHED:
        return "finished"
    if low in _LIVE:
        return "live"
    if low in _POSTPONED:
        return "postponed"
    if low in _DEAD:
        return "dead"
    return "scheduled"


def read_matches(store: dict[str, Any], cfg: LeagueConfig, season_id: int | None = None) -> list[TorneoMatch]:
    """Every match of the store (or of one season), normalised; an old copy superseded by a re-listing is skipped."""
    out = []
    for gid, raw in (store.get("matches") or {}).items():
        if not isinstance(raw, dict) or raw.get("superseded_by"):
            continue
        if season_id is not None and raw.get("season_id") != season_id:
            continue
        home = normalize_team_name(str(raw.get("home") or ""), cfg.registry)
        away = normalize_team_name(str(raw.get("away") or ""), cfg.registry)
        if not home or not away:
            continue
        hs, as_ = raw.get("hs"), raw.get("as")
        winner = raw.get("winner")
        pens = raw.get("pens")
        if not winner and isinstance(pens, list) and len(pens) == 2 and pens[0] != pens[1] and hs is not None and hs == as_:
            winner = raw.get("home") if pens[0] > pens[1] else raw.get("away")
        torneo = raw.get("torneo")
        group = raw.get("group")
        stage = "playoff" if raw.get("stage") == "playoff" else "league"
        # Colombia's cuadrangulares in stores written before the fetcher filed them as playoffs.
        if stage == "league" and group and torneo and torneo != "intermedio":
            stage = "playoff"
        out.append(TorneoMatch(
            game_id=str(gid), home=home, away=away,
            hg=int(hs) if hs is not None else None, ag=int(as_) if as_ is not None else None,
            date=_liga._parse_date(raw.get("date")), round=str(raw["round"]) if raw.get("round") is not None else None,
            stage=stage, status=_status(raw.get("status")), torneo=torneo, group=group,
            season_id=raw.get("season_id"),
            winner=normalize_team_name(str(winner), cfg.registry) if winner else None,
            agg_winner=normalize_team_name(str(raw["agg_winner"]), cfg.registry) if raw.get("agg_winner") else None,
        ))
    return out


def _dedupe(matches: list[TorneoMatch]) -> list[TorneoMatch]:
    """Drop dead fixtures and the postponed copy of a fixture listed again (same stage, phase and clubs)."""
    def key(m):
        return (m.torneo, m.stage, m.round if m.is_playoff else None, m.home, m.away)
    live = [m for m in matches if m.status != "dead"]
    count: dict[tuple, int] = {}
    for m in live:
        count[key(m)] = count.get(key(m), 0) + 1
    return [m for m in live if not (m.status == "postponed" and count[key(m)] > 1)]


# ── season state ─────────────────────────────────────────────────────────────

@dataclass
class StageState:
    fmt: StageFormat
    regular_done: list[TorneoMatch] = field(default_factory=list)
    regular_left: list[TorneoMatch] = field(default_factory=list)
    playoff_done: list[TorneoMatch] = field(default_factory=list)
    playoff_left: list[TorneoMatch] = field(default_factory=list)
    champion: str | None = None
    # Round-robin pairings Sofascore has not listed yet (it publishes the last rounds late): (home, away), the venue
    # the reverse of the pair's meeting in an earlier stage. Simulated with the fixtures still to play.
    regular_missing: list[tuple[str, str]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.fmt.key

    @property
    def started(self) -> bool:
        return bool(self.regular_done or self.playoff_done)

    @property
    def scheduled(self) -> bool:
        return bool(self.regular_done or self.regular_left or self.playoff_done or self.playoff_left)

    @property
    def regular_complete(self) -> bool:
        return self.scheduled and not self.regular_left and not self.regular_missing

    @property
    def closed(self) -> bool:
        return self.champion is not None

    def groups(self) -> dict[str, list[str]]:
        """Playoff groups as drawn (Colombia's cuadrangulares), from the group matches in the store."""
        out: dict[str, list[str]] = {}
        for m in self.playoff_done + self.playoff_left:
            if m.group:
                g = out.setdefault(m.group, [])
                for t in (m.home, m.away):
                    if t not in g:
                        g.append(t)
        return out


@dataclass
class TorneoState:
    cfg: LeagueConfig
    teams: list[str]
    stages: list[StageState]
    season_done: list[TorneoMatch] = field(default_factory=list)
    season_left: list[TorneoMatch] = field(default_factory=list)
    season_name: str | None = None
    season_id: int | None = None
    # Promedio history before this season: club -> (points, matches) over the earlier seasons of the window.
    promedio_prior: dict[str, tuple[int, int]] = field(default_factory=dict)
    prior_seasons: list[str] = field(default_factory=list)
    adjustments: dict[str, dict[str, int]] = field(default_factory=dict)   # stage -> club -> points
    team_ids: dict[str, int] = field(default_factory=dict)
    champion: str | None = None          # the season champion when decided (Uruguay, Peru)

    @property
    def fmt(self) -> TorneoFormat:
        return self.cfg.torneo

    def stage(self, key: str) -> StageState | None:
        return next((s for s in self.stages if s.key == key), None)

    @property
    def current(self) -> StageState:
        """The stage being played: the first without a champion that has started, else the first not started, else
        the last."""
        for s in self.stages:
            if not s.closed and s.started:
                return s
        for s in self.stages:
            if not s.closed:
                return s
        return self.stages[-1]

    @property
    def complete(self) -> bool:
        if not all(s.closed for s in self.stages):
            return False
        if self.fmt.champion == "stages":
            return True
        return self.champion is not None and not self.season_left

    # ── tables as they stand ─────────────────────────────────────────────────

    def records(self, stage: str | None = None, aggregate: bool = False) -> dict[str, TeamRecord]:
        """A stage's round-robin table, or the aggregate table, from the results so far (sanctions not applied)."""
        table = {t: TeamRecord() for t in self.teams}
        for s in self.stages:
            if not aggregate and s.key != stage:
                continue
            ms = list(s.regular_done)
            if aggregate and self.fmt.aggregate_matches == "all":
                ms += s.playoff_done
            for m in ms:
                for team, gf, ga in ((m.home, m.hg, m.ag), (m.away, m.ag, m.hg)):
                    if team in table:
                        table[team].add_result(gf, ga, self.cfg)
        if aggregate and self.fmt.aggregate_matches == "all":
            for m in self.season_done:
                for team, gf, ga in ((m.home, m.hg, m.ag), (m.away, m.ag, m.hg)):
                    if team in table:
                        table[team].add_result(gf, ga, self.cfg)
        return table

    def adjustment(self, team: str, stage: str | None = None, aggregate: bool = False) -> int:
        if aggregate:
            return sum(self.adjustments.get(k, {}).get(team, 0) for k in self.adjustments)
        return self.adjustments.get(stage or "", {}).get(team, 0)

    def standings(self, stage: str | None = None, aggregate: bool = False) -> list[tuple[str, TeamRecord, int]]:
        """(club, record, points with sanctions) in table order."""
        recs = self.records(stage, aggregate)
        rows = [(t, r, r.points + self.adjustment(t, stage, aggregate)) for t, r in recs.items()]

        def key(row):
            t, r, pts = row
            parts = []
            for k in self.cfg.tiebreak:
                parts.append(-pts if k == "pts" else -r.gd if k == "gd" else -r.gf if k == "gf" else -r.won)
            return tuple(parts) + (t,)
        return sorted(rows, key=key)

    def promedio_now(self) -> dict[str, float]:
        """Each club's promedio as it stands: points per match over the window, this season's results included."""
        out = {}
        for t in self.teams:
            pts, mp = self.promedio_prior.get(t, (0, 0))
            for s in self.stages:
                for m in s.regular_done:
                    if t in (m.home, m.away):
                        gf, ga = (m.hg, m.ag) if t == m.home else (m.ag, m.hg)
                        pts += 3 if gf > ga else 1 if gf == ga else 0
                        mp += 1
            pts += sum(self.adjustments.get(k, {}).get(t, 0) for k in self.adjustments)
            out[t] = pts / mp if mp else 0.0
        return out

    # ── progress, for the shared readers ─────────────────────────────────────

    @property
    def games_played(self) -> int:
        return sum(len(s.regular_done) + len(s.playoff_done) for s in self.stages) + len(self.season_done)

    @property
    def games_total(self) -> int:
        return self.games_played + sum(len(s.regular_left) + len(s.playoff_left) for s in self.stages) + len(self.season_left)

    def summary(self) -> str:
        cur = self.current
        return (f"{self.cfg.name} {self.season_name or ''}: stage {cur.fmt.label} "
                f"{len(cur.regular_done)}/{len(cur.regular_done) + len(cur.regular_left)} regular, "
                f"{len(cur.playoff_done)} playoff played; teams={len(self.teams)}; "
                f"stages closed: {[s.key for s in self.stages if s.closed]}")


def _tie_winner(legs: list[TorneoMatch], two_legs: bool) -> str | None:
    """The winner of a decided tie: points over the legs, then aggregate goal difference, then the shoot-out."""
    done = [m for m in legs if m.done]
    if not done or (two_legs and len(done) < 2):
        return None
    a, b = done[0].home, done[0].away
    pts = {a: 0, b: 0}
    gd = {a: 0, b: 0}
    for m in done:
        for t, gf, ga in ((m.home, m.hg, m.ag), (m.away, m.ag, m.hg)):
            if t in pts:
                pts[t] += 3 if gf > ga else 1 if gf == ga else 0
                gd[t] += gf - ga
    if pts[a] != pts[b]:
        return a if pts[a] > pts[b] else b
    if gd[a] != gd[b]:
        return a if gd[a] > gd[b] else b
    last = done[-1]
    for w in (last.agg_winner, last.winner):
        if w in (a, b):
            return w
    return None


def _final_winner(ms: list[TorneoMatch], two_legs: bool) -> str | None:
    finals = [m for m in ms if m.round == "final"]
    if not finals:
        return None
    pairs: dict[frozenset, list[TorneoMatch]] = {}
    for m in finals:
        pairs.setdefault(frozenset((m.home, m.away)), []).append(m)
    for legs in pairs.values():
        legs.sort(key=lambda m: m.date or datetime.min)
        w = _tie_winner(legs, two_legs)
        if w:
            return w
    return None


def _season_year(entry_season: dict) -> int:
    import re
    for raw in (entry_season.get("year"), entry_season.get("name")):
        m = re.findall(r"\d{2,4}", str(raw or ""))
        if m:
            y = int(m[-1])
            return y + 2000 if y < 100 else y
    return 0


def torneo_state_from_store(store: dict[str, Any], cfg: LeagueConfig, entry: dict | None = None) -> TorneoState:
    """
    The current season of a torneo league: each stage's round robin and playoffs, the season playoffs, and the
    promedio history from the earlier seasons the store keeps (seasons.json lists them with their years).
    """
    from oddsmarkets.football.competitions.league.store import current_season_id, team_ids_from_store

    fmt = cfg.torneo
    entry = entry or {}
    sid = current_season_id(store)
    matches = _dedupe(read_matches(store, cfg, sid))
    teams: list[str] = []
    for m in matches:
        if m.torneo and not m.is_playoff:
            for t in (m.home, m.away):
                if t not in teams:
                    teams.append(t)
    if not teams:
        teams = [normalize_team_name(t, cfg.registry) for t in entry.get("teams") or []]
    teams = sorted(teams)

    stages = [StageState(fmt=sf) for sf in fmt.stages]
    by_key = {s.key: s for s in stages}
    season_done, season_left = [], []
    for m in sorted(matches, key=_when):
        st = by_key.get(m.torneo or "")
        if st is None:
            if m.is_playoff:
                (season_done if m.done else season_left).append(m)
            continue
        if m.is_playoff:
            (st.playoff_done if m.done else st.playoff_left).append(m)
        else:
            (st.regular_done if m.done else st.regular_left).append(m)

    # Results the competition counts that Sofascore does not list (config.unlisted_results), unless it lists them now.
    for stage_key, home, away, hg, ag in cfg.unlisted_results:
        st_ = by_key.get(stage_key)
        home, away = normalize_team_name(home, cfg.registry), normalize_team_name(away, cfg.registry)
        if st_ is None or home not in teams or away not in teams:
            logger.warning("%s: unlisted result %s v %s (%s) does not match the season; skipped", cfg.slug, home, away, stage_key)
            continue
        listed = {frozenset((m.home, m.away)) for m in st_.regular_done + st_.regular_left}
        if frozenset((home, away)) in listed:
            continue
        st_.regular_done.append(TorneoMatch(
            game_id=f"unlisted-{stage_key}-{home}-{away}", home=home, away=away, hg=int(hg), ag=int(ag), date=None,
            round=None, stage="league", status="finished", torneo=stage_key, group=None, season_id=sid))

    # A stage's round robin is over once its playoffs or a later stage have begun: what is left of it then is a
    # postponed fixture that was never played (Colombia's Apertura 2026 left three).
    for i, s in enumerate(stages):
        later = any(t.started for t in stages[i + 1:]) or (s.playoff_done and s.fmt.final_phase != "table")
        if later and s.regular_left:
            logger.info("%s: %s: %d unplayed round-robin fixtures dropped (the stage has moved on)",
                        cfg.slug, s.key, len(s.regular_left))
            s.regular_left = []
        if not later and s.started and s.fmt.final_phase != "group_final":
            s.regular_missing = _missing_pairs(s, stages[:i], teams)
            if s.regular_missing:
                logger.info("%s: %s: %d round-robin pairings not listed yet, simulated", cfg.slug, s.key,
                            len(s.regular_missing))
        # A stage decided on its table: its playoff matches (a play-off for first place) decide it when played.
        if s.fmt.final_phase == "table":
            if s.playoff_done and not s.playoff_left:
                s.champion = s.playoff_done[-1].winner or _tie_winner(s.playoff_done[-1:], False)
            if s.champion is None and s.regular_complete and not s.playoff_left and later:
                s.champion = _top_of(s, cfg)
            elif s.champion is None and s.regular_complete and not s.playoff_left:
                top = _top_two(s, cfg)
                # A clear first place is the champion; a tie on points waits for its play-off match.
                if top and (len(top) == 1 or top[0][1] != top[1][1]):
                    s.champion = top[0][0]
        elif s.fmt.final_phase in ("knockout8", "groups8"):
            s.champion = _final_winner(s.playoff_done, two_legs=True)
        elif s.fmt.final_phase == "group_final":
            s.champion = _final_winner(s.playoff_done, two_legs=False)

    state = TorneoState(
        cfg=cfg, teams=teams, stages=stages, season_done=season_done, season_left=season_left,
        season_name=(store.get("meta") or {}).get("season_name"), season_id=sid,
        team_ids=team_ids_from_store(store, cfg),
    )
    adj: dict[str, dict[str, int]] = {}
    for stage_key, club, pts in cfg.point_adjustments:
        adj.setdefault(stage_key, {})[normalize_team_name(club, cfg.registry)] = adj.get(stage_key, {}).get(club, 0) + int(pts)
    state.adjustments = adj
    if fmt.champion != "stages":
        state.champion = _season_champion(state)

    if fmt.relegation_by == "promedio":
        state.promedio_prior, state.prior_seasons = promedio_prior(store, cfg, entry, sid)
    return state


def _missing_pairs(s: StageState, earlier: list[StageState], teams: list[str]) -> list[tuple[str, str]]:
    """Every pair meets once in a single round robin; the pairs not in the stage's fixture list, each at the ground
    of the club that was away in the pair's earlier meeting this season."""
    listed = {frozenset((m.home, m.away)) for m in s.regular_done + s.regular_left}
    before: dict[frozenset, tuple[str, str]] = {}
    for e in earlier:
        for m in e.regular_done + e.regular_left:
            before[frozenset((m.home, m.away))] = (m.home, m.away)
    out = []
    for i, a in enumerate(teams):
        for j in range(i + 1, len(teams)):
            b = teams[j]
            pair = frozenset((a, b))
            if pair in listed:
                continue
            prev = before.get(pair)
            out.append((prev[1], prev[0]) if prev else ((a, b) if (i + j) % 2 else (b, a)))
    return out


def _when(m: TorneoMatch) -> tuple:
    """Kick-off order, undated fixtures last."""
    return (m.date is None, m.date.timestamp() if m.date else 0.0, m.game_id)


def _top_two(s: StageState, cfg: LeagueConfig) -> list[tuple[str, int]]:
    table: dict[str, TeamRecord] = {}
    for m in s.regular_done:
        for t, gf, ga in ((m.home, m.hg, m.ag), (m.away, m.ag, m.hg)):
            table.setdefault(t, TeamRecord()).add_result(gf, ga, cfg)
    rows = sorted(table.items(), key=lambda kv: (-kv[1].points, -kv[1].gd, -kv[1].gf, kv[0]))
    return [(t, r.points) for t, r in rows[:2]]


def _top_of(s: StageState, cfg: LeagueConfig) -> str | None:
    top = _top_two(s, cfg)
    return top[0][0] if top else None


def _season_champion(state: TorneoState) -> str | None:
    """
    The season champion once decided: the winner of the final (two legs in Uruguay and Peru), or a club that won
    both the Apertura and the Clausura, or (Uruguay) the Tabla Anual leader that won the semi-final.
    """
    w = _final_winner(state.season_done, two_legs=True)
    if w:
        return w
    a, c = state.stage("apertura"), state.stage("clausura")
    if a and c and a.champion and a.champion == c.champion:
        return a.champion
    if state.fmt.champion == "uruguay" and all(s.closed for s in state.stages):
        semis = [m for m in state.season_done if m.round == "sf"]
        if semis:
            sw = _tie_winner(semis[-1:], two_legs=False)
            table = state.standings(aggregate=True)
            if sw and table and table[0][0] == sw:
                return sw
    return None


def promedio_prior(store: dict[str, Any], cfg: LeagueConfig, entry: dict, current_sid: int | None
                   ) -> tuple[dict[str, tuple[int, int]], list[str]]:
    """
    Points and matches per club over the earlier seasons of the promedio window, from the store: the round robins
    (Colombia) or every Tabla Anual match (Uruguay: the Apertura, the Intermedio groups and the Clausura). A club
    that was not in the top flight in a season simply has no matches in it, so it averages over its own seasons,
    as both regulations require. Sanctions in earlier seasons are not in Sofascore's results and are not applied.
    """
    fmt = cfg.torneo
    seasons = [s for s in entry.get("seasons") or [] if int(s.get("season_id") or 0) != int(current_sid or 0)]
    cur_year = max((_season_year(s) for s in entry.get("seasons") or [] if int(s.get("season_id") or 0) == int(current_sid or 0)), default=0)
    if not cur_year:
        cur_year = max((_season_year(s) for s in entry.get("seasons") or []), default=0)
    window = {int(s["season_id"]): s for s in seasons
              if cur_year - fmt.promedio_years < _season_year(s) < cur_year}
    # Season by season, newest first: a club counts a season only while it has been in the top flight every season
    # since (Colombia's Jaguares, relegated after 2024 and promoted for 2026, average over 2026 alone).
    by_year: dict[int, dict[str, list[int]]] = {}
    used = []
    for sid, s in sorted(window.items()):
        ms = _dedupe(read_matches(store, cfg, sid))
        tally = by_year.setdefault(_season_year(s), {})
        n = 0
        for m in ms:
            if not m.done or m.is_playoff or not m.torneo:
                continue
            for t, gf, ga in ((m.home, m.hg, m.ag), (m.away, m.ag, m.hg)):
                rec = tally.setdefault(t, [0, 0])
                rec[0] += 3 if gf > ga else 1 if gf == ga else 0
                rec[1] += 1
            n += 1
        used.append(f"{s.get('name') or sid} ({n} matches)")
    out: dict[str, list[int]] = {}
    gone: set[str] = set()
    current_clubs = {t for m in read_matches(store, cfg, current_sid) for t in (m.home, m.away)}
    for year in sorted(by_year, reverse=True):
        tally = by_year[year]
        for t in current_clubs:
            if t in gone:
                continue
            if t not in tally:
                gone.add(t)
                continue
            rec = out.setdefault(t, [0, 0])
            rec[0] += tally[t][0]
            rec[1] += tally[t][1]
    return {t: (v[0], v[1]) for t, v in out.items()}, used


# ── results ──────────────────────────────────────────────────────────────────

@dataclass
class TorneoResults:
    n_sims: int
    runtime_s: float
    teams: list[str]
    stage_key: str
    # the current stage
    p_position: dict[str, list[float]] = field(default_factory=dict)
    expected_points: dict[str, float] = field(default_factory=dict)
    points_quantiles: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    p_stage: dict[str, dict[str, float]] = field(default_factory=dict)        # stage -> club -> champion chance
    p_playoffs: dict[str, float] = field(default_factory=dict)                 # current stage: reaches its playoffs
    p_reach: dict[str, dict[str, float]] = field(default_factory=dict)        # club -> round -> chance (current stage or season)
    reach_rounds: tuple[str, ...] = ()
    # the season
    p_title: dict[str, float] = field(default_factory=dict)                    # season champion (Colombia: the current stage's)
    p_runner_up: dict[str, float] = field(default_factory=dict)
    p_agg_position: dict[str, list[float]] = field(default_factory=dict)
    agg_expected_points: dict[str, float] = field(default_factory=dict)
    agg_points_quantiles: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    p_libertadores: dict[str, float] = field(default_factory=dict)
    p_sudamericana: dict[str, float] = field(default_factory=dict)
    p_relegation: dict[str, float] = field(default_factory=dict)
    promedio_quantiles: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    team_goals_mean: dict[str, float] = field(default_factory=dict)
    stakes: list[dict] = field(default_factory=list)
    # duck-typing with LeagueResults for the shared readers (history snapshots, the boot model)
    p_band: dict[str, dict[str, float]] = field(default_factory=dict)
    p_cup: dict[str, float] = field(default_factory=dict)
    p_conf_position: dict[str, list[float]] = field(default_factory=dict)
    p_final_position: dict[str, list[float]] = field(default_factory=dict)

    def p_in_band(self, key: str, team: str) -> float:
        return self.p_band.get(key, {}).get(team, 0.0)


# ── simulator ────────────────────────────────────────────────────────────────

class TorneoSimulator:
    """
    Simulates the rest of a torneo season. `model` is any match model with `.predict(home, away, neutral=...,
    max_goals=...)` returning a score matrix (the league's ensemble). `cup_dist` is a distribution over the national
    cup's winner when one feeds a berth (Colombia's Copa BetPlay -> Sudamericana Colombia 1).
    """

    def __init__(self, model, state: TorneoState, cfg: LeagueConfig | None = None, n_sims: int | None = None,
                 seed: int | None = None, chunk: int | None = None, boot_model=None,
                 cup_dist: dict[str, float] | None = None) -> None:
        self.model = model
        self.state = state
        self.cfg = cfg or state.cfg
        self.fmt: TorneoFormat = self.cfg.torneo
        self.n_sims = n_sims if n_sims is not None else self.cfg.n_sims
        self.seed = seed if seed is not None else self.cfg.random_seed
        self.chunk = chunk if chunk is not None else self.cfg.sim_chunk
        self.boot_model = boot_model
        self.cup_dist = cup_dist or {}
        self.teams = list(state.teams)
        self.T = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}
        self.sampler = ScoreSampler(model, self.teams, max_goals=self.cfg.max_goals)
        self.pairs = PairSampler(self.sampler)
        self._share: np.ndarray | None = None
        # known[(scope, round)] -> (hg, ag) matrices of legs already played, -1 where unknown; scope is a stage key
        # or SEASON. tie_w[(scope, round)][a, b] is the winner of a decided level tie (penalties), else -1.
        self.known: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
        self.tie_w: dict[tuple[str, str], np.ndarray] = {}
        for s in state.stages:
            self._learn(s.key, s.playoff_done)
        self._learn(SEASON, state.season_done)

    # ── played legs ─────────────────────────────────────────────────────────

    def _learn(self, scope: str, done: list[TorneoMatch]) -> None:
        for m in done:
            h, a = self.idx.get(m.home), self.idx.get(m.away)
            if h is None or a is None:
                continue
            rk = m.round if m.round in _ROUNDS else ("group" if m.group else "any")
            for key in {(scope, rk), (scope, "any")}:
                if key not in self.known:
                    self.known[key] = (np.full((self.T, self.T), -1, dtype=np.int32), np.full((self.T, self.T), -1, dtype=np.int32))
                    self.tie_w[key] = np.full((self.T, self.T), -1, dtype=np.intp)
                kh, ka = self.known[key]
                kh[h, a], ka[h, a] = m.hg, m.ag
                w = m.agg_winner or m.winner
                if w in (m.home, m.away):
                    wi = self.idx[w]
                    self.tie_w[key][h, a] = wi
                    self.tie_w[key][a, h] = wi

    def _leg(self, scope: str, rnd: str, home: np.ndarray, away: np.ndarray, rng) -> tuple[np.ndarray, np.ndarray]:
        """One leg per simulation (home and away vary per simulation); a leg already played is forced."""
        hg, ag = self.pairs.sample(home, away, rng)
        for key in ((scope, rnd), (scope, "any")):
            if key in self.known:
                kh, ka = self.known[key]
                fh, fa = kh[home, away], ka[home, away]
                hit = fh >= 0
                if hit.any():
                    hg = np.where(hit, fh, hg)
                    ag = np.where(hit, fa, ag)
                break
        same = home == away
        if same.any():
            hg = np.where(same, 0, hg)
            ag = np.where(same, 0, ag)
        return hg.astype(np.int32), ag.astype(np.int32)

    def share(self) -> np.ndarray:
        """P(home wins | the match is decided) per ordered pair: extra time's tilt towards the stronger side."""
        if self._share is None:
            k = self.sampler.k
            out = np.full((self.T, self.T), 0.5)
            iu = np.tril_indices(k, -1)
            for h in range(self.T):
                for a in range(self.T):
                    if h == a:
                        continue
                    cdf = self.sampler.cdf(h, a)
                    pmf = np.diff(np.concatenate([[0.0], cdf])).reshape(k, k)
                    hw, aw = pmf[iu].sum(), pmf.T[iu].sum()
                    out[h, a] = hw / (hw + aw) if hw + aw > 0 else 0.5
            self._share = out
        return self._share

    def _tie(self, scope: str, rnd: str, first_home: np.ndarray, second_home: np.ndarray, rng, two_legs: bool,
             extra_time: float, acc: dict | None = None) -> np.ndarray:
        """
        The winner of a tie per simulation. Two legs: `second_home` hosts the return; points over the legs, then
        aggregate goal difference, then (`extra_time` > 0) extra time tilted to the stronger side, else a shoot-out
        taken as even. One match: `first_home` hosts. Goals and points are added to `acc` (the aggregate table).
        """
        a, b = first_home, second_home
        rows = np.arange(a.shape[0])
        pa = np.zeros(a.shape[0], dtype=np.int32)
        pb = np.zeros(a.shape[0], dtype=np.int32)
        ga = np.zeros(a.shape[0], dtype=np.int32)
        gb = np.zeros(a.shape[0], dtype=np.int32)
        legs = [(a, b)] + ([(b, a)] if two_legs else [])
        for h, aw in legs:
            hg, ag = self._leg(scope, rnd, h, aw, rng)
            is_a = h is a
            sa, sb = (hg, ag) if is_a else (ag, hg)
            pa += 3 * (sa > sb) + (sa == sb)
            pb += 3 * (sb > sa) + (sa == sb)
            ga += sa
            gb += sb
            if acc is not None:
                _add(acc, rows, h, aw, hg, ag)
        win = np.where(pa > pb, a, np.where(pb > pa, b, np.where(ga > gb, a, np.where(gb > ga, b, -1))))
        level = win < 0
        if level.any():
            # A decided level tie is forced to its real winner (penalties).
            forced = np.full(a.shape[0], -1, dtype=np.intp)
            for key in ((scope, rnd), (scope, "any")):
                if key in self.tie_w:
                    forced = self.tie_w[key][a, b]
                    break
            if extra_time > 0:
                sh = self.share()[b if two_legs else a, a if two_legs else b]   # the host's share
                host = b if two_legs else a
                other = a if two_legs else b
                p_host = extra_time * sh + (1.0 - extra_time) * 0.5
                coin = np.where(rng.random(a.shape[0]) < p_host, host, other)
            else:
                coin = np.where(rng.random(a.shape[0]) < 0.5, a, b)
            win = np.where(level, np.where(forced >= 0, forced, coin), win)
        return win.astype(np.intp)

    # ── stage tables ────────────────────────────────────────────────────────

    def _seed(self, stage: StageState, S: int) -> dict[str, np.ndarray]:
        pts = np.zeros(self.T, dtype=np.int32)
        gf = np.zeros(self.T, dtype=np.int32)
        ga = np.zeros(self.T, dtype=np.int32)
        w = np.zeros(self.T, dtype=np.int32)
        mp = np.zeros(self.T, dtype=np.int32)
        for m in stage.regular_done:
            h, a = self.idx.get(m.home), self.idx.get(m.away)
            if h is None or a is None:
                continue
            pts[h] += 3 * (m.hg > m.ag) + (m.hg == m.ag)
            pts[a] += 3 * (m.ag > m.hg) + (m.hg == m.ag)
            w[h] += m.hg > m.ag
            w[a] += m.ag > m.hg
            gf[h] += m.hg
            ga[h] += m.ag
            gf[a] += m.ag
            ga[a] += m.hg
            mp[h] += 1
            mp[a] += 1
        for t, p in self.state.adjustments.get(stage.key, {}).items():
            if t in self.idx:
                pts[self.idx[t]] += p
        return {k: np.tile(v, (S, 1)) for k, v in (("pts", pts), ("gf", gf), ("ga", ga), ("w", w), ("mp", mp))}

    def _rank(self, tab: dict[str, np.ndarray], rng, cols: np.ndarray | None = None) -> np.ndarray:
        by = {"pts": tab["pts"], "gd": tab["gf"] - tab["ga"], "gf": tab["gf"], "w": tab["w"]}
        keys = [by[k] for k in self.cfg.tiebreak]
        if cols is not None:
            keys = [k[:, cols] for k in keys]
        order, _ = rank_table(keys, rng)
        return order if cols is None else cols[order]

    def _synthetic_fixtures(self, stage: StageState) -> list[tuple[int, int]]:
        """A stage with no fixtures published yet: the first stage's fixtures reversed (Colombia, Peru and the
        Uruguayan Clausura mirror the Apertura), or every pair once when no stage has fixtures."""
        first = self.state.stages[0]
        src = first.regular_done + first.regular_left
        if src and first is not stage:
            return [(self.idx[m.away], self.idx[m.home]) for m in src if m.home in self.idx and m.away in self.idx]
        return [(i, j) if (i + j) % 2 else (j, i) for i in range(self.T) for j in range(i + 1, self.T)]

    # ── main loop ───────────────────────────────────────────────────────────

    def run(self) -> TorneoResults:
        start = time.perf_counter()
        st, fmt, T, n = self.state, self.fmt, self.T, self.n_sims
        if T == 0:
            raise ValueError("no teams")
        rng = np.random.default_rng(self.seed)
        cur = st.current
        cur_i = st.stages.index(cur)
        stage_rounds = {"knockout8": ("playoffs", "qf", "sf", "final"), "groups8": ("playoffs", "groups", "final"),
                        "group_final": ("final",), "table": ()}
        if fmt.champion == "peru":
            season_rounds = ("playoffs", "sf", "final")
        elif fmt.champion == "uruguay":
            season_rounds = ("sf", "final")
        else:
            season_rounds = ()
        reach_rounds = stage_rounds[cur.fmt.final_phase] if fmt.champion == "stages" else season_rounds
        cnt = {
            "pos": np.zeros((T, T), dtype=np.int64), "agg_pos": np.zeros((T, T), dtype=np.int64),
            "title": np.zeros(T, dtype=np.int64), "runner": np.zeros(T, dtype=np.int64),
            "lib": np.zeros(T, dtype=np.int64), "sud": np.zeros(T, dtype=np.int64), "rel": np.zeros(T, dtype=np.int64),
            "reach": {r: np.zeros(T, dtype=np.int64) for r in reach_rounds},
            "stage": {s.key: np.zeros(T, dtype=np.int64) for s in st.stages},
        }
        sums = {"pts": np.zeros(T), "agg": np.zeros(T), "goals": np.zeros(T)}
        samples = {"pts": [], "agg": [], "prom": []}
        cup_p = np.array([self.cup_dist.get(t, 0.0) for t in self.teams], dtype=np.float64)
        cup_total = float(sum(self.cup_dist.values()))
        logger.info("Simulating %s: stage %s, %d sims", self.cfg.slug, cur.key, n)

        done = 0
        while done < n:
            S = min(self.chunk, n - done)
            rows = np.arange(S)
            agg = {k: np.zeros((S, T), dtype=np.int32) for k in ("pts", "gf", "ga", "w", "mp")}
            rr = {k: np.zeros((S, T), dtype=np.int32) for k in ("pts", "mp")}     # round robins only (promedio)
            goals = np.zeros((S, T), dtype=np.int32)
            champs: dict[str, np.ndarray] = {}
            orders: dict[str, np.ndarray] = {}
            stage_tabs: dict[str, dict[str, np.ndarray]] = {}
            for si, s in enumerate(st.stages):
                tab = self._seed(s, S)
                fixtures = [(self.idx[m.home], self.idx[m.away]) for m in s.regular_left
                            if m.home in self.idx and m.away in self.idx]
                fixtures += [(self.idx[h], self.idx[a]) for h, a in s.regular_missing if h in self.idx and a in self.idx]
                synthetic_groups = None
                if not s.scheduled:
                    if s.fmt.final_phase == "group_final":
                        synthetic_groups = self._intermedio_groups(s, orders, rng, S)
                    else:
                        fixtures = self._synthetic_fixtures(s)
                for h, a in fixtures:
                    hg, ag = self.sampler.sample(h, a, rng, S)
                    _add(tab, rows, np.full(S, h), np.full(S, a), hg, ag)
                    goals[:, h] += hg
                    goals[:, a] += ag
                if synthetic_groups is not None:
                    for members in synthetic_groups:
                        k = members.shape[1]
                        for i in range(k):
                            for j in range(i + 1, k):
                                h, a = (members[:, i], members[:, j]) if (i + j) % 2 else (members[:, j], members[:, i])
                                hg, ag = self.pairs.sample(h, a, rng)
                                _add(tab, rows, h, a, hg, ag)
                                np.add.at(goals, (rows, h), hg)
                                np.add.at(goals, (rows, a), ag)
                for k in ("pts", "gf", "ga", "w", "mp"):
                    agg[k] += tab[k]
                rr["pts"] += tab["pts"]
                rr["mp"] += tab["mp"]
                stage_tabs[s.key] = tab
                order = self._rank(tab, rng)
                orders[s.key] = order
                acc = agg if fmt.aggregate_matches == "all" else None
                if s.closed:
                    champ = np.full(S, self.idx.get(s.champion, -1), dtype=np.intp)
                    if acc is not None:
                        _add_known(acc, s.playoff_done, self.idx)
                else:
                    # an open stage's played legs are added as the simulation replays them (forced)
                    reach = cnt["reach"] if (s is cur and fmt.champion == "stages") else None
                    champ = self._stage_champion(s, order, tab, rng, S, reach, acc)
                champs[s.key] = champ
                ok = champ >= 0
                np.add.at(cnt["stage"][s.key], champ[ok], 1)
                if s is cur:
                    cnt["pos"] += count_positions(order, T)
                    sums["pts"] += tab["pts"].sum(axis=0)
                    if len(samples["pts"]) * self.chunk < 5000:
                        samples["pts"].append(tab["pts"][: min(S, 2000)].copy())
            # sanctions on the aggregate itself (Peru lists them per stage, so they are already in)
            for t, p in st.adjustments.get("", {}).items():
                if t in self.idx:
                    agg["pts"][:, self.idx[t]] += p
            if fmt.aggregate_matches == "all":
                _add_known(agg, st.season_done, self.idx)
            agg_order = self._rank(agg, rng)
            cnt["agg_pos"] += count_positions(agg_order, T)
            sums["agg"] += agg["pts"].sum(axis=0)
            if len(samples["agg"]) * self.chunk < 5000:
                samples["agg"].append(agg["pts"][: min(S, 2000)].copy())

            # relegation
            rel = np.zeros((S, T), dtype=bool)
            if fmt.relegation_by == "promedio":
                # this season's round robins (Colombia) or Tabla Anual matches (Uruguay: the Intermedio groups are a
                # round robin here too), sanctions included, over the earlier seasons of the window
                prior_p = np.array([st.promedio_prior.get(t, (0, 0))[0] for t in self.teams], dtype=np.float64)
                prior_m = np.array([st.promedio_prior.get(t, (0, 0))[1] for t in self.teams], dtype=np.float64)
                pts_s, mp_s = rr["pts"], rr["mp"]
                prom = (prior_p[None, :] + pts_s) / np.maximum(prior_m[None, :] + mp_s, 1)
                worst, _ = rank_table([-prom, -pts_s.astype(np.float64)], rng)
                down = worst[:, : fmt.relegation_places]
                rel[rows[:, None], down] = True
                if len(samples["prom"]) * self.chunk < 5000:
                    samples["prom"].append(prom[: min(S, 2000)].copy())
            else:
                down = agg_order[:, T - fmt.relegation_places:]
                rel[rows[:, None], down] = True
            np.add.at(cnt["rel"], rel.nonzero()[1], 1)

            # the season's champion and places
            places = None
            runner = None
            if fmt.champion == "stages":
                title = champs[cur.key]
            elif fmt.champion == "uruguay":
                title, runner = self._uruguay(champs, agg_order, rng, S, cnt["reach"])
            else:
                title, runner, places = self._peru(champs, agg_order, rng, S, cnt["reach"])
            ok = title >= 0
            np.add.at(cnt["title"], title[ok], 1)
            if runner is not None:
                okr = runner >= 0
                np.add.at(cnt["runner"], runner[okr], 1)

            # continental places
            lib, sud = self._berths(champs, title, runner, places, agg_order, rel, rng, S, cup_p, cup_total)
            np.add.at(cnt["lib"], lib.nonzero()[1], 1)
            np.add.at(cnt["sud"], sud.nonzero()[1], 1)

            if self.boot_model is not None:
                self.boot_model.accumulate_batch(goals, self.teams)
            sums["goals"] += goals.sum(axis=0)
            done += S

        runtime = time.perf_counter() - start
        logger.info("Simulated %d %s seasons in %.1fs", n, self.cfg.slug, runtime)
        return self._assemble(n, runtime, cur, cnt, sums, samples, reach_rounds)

    # ── stage champions ─────────────────────────────────────────────────────

    def _stage_champion(self, s: StageState, order, tab, rng, S, reach, acc) -> np.ndarray:
        ph = s.fmt.final_phase
        if ph == "table":
            return order[:, 0].copy()
        if ph == "group_final":
            return self._group_final(s, tab, order, rng, S, reach)
        top8 = order[:, :8]
        if reach is not None and "playoffs" in reach:
            np.add.at(reach["playoffs"], top8.ravel(), 1)
        if ph == "groups8":
            return self._groups8(s, order, tab, rng, S, reach, acc)
        return self._knockout8(s, order, tab, rng, S, reach, acc)

    def _groups8(self, s, order, tab, rng, S, reach, acc) -> np.ndarray:
        """Two groups of four headed by 1st and 2nd (3rd-8th drawn), a double round robin, then a two-legged final
        hosted (second leg) by the finalist with more points over the round robin and the groups."""
        rows = np.arange(S)
        drawn = s.groups()
        if len(drawn) == 2 and all(len(v) == 4 for v in drawn.values()):
            members = [np.tile(np.array([self.idx[t] for t in drawn[g]]), (S, 1)) for g in sorted(drawn)]
        else:
            rest = order[:, 2:8]
            perm = np.argsort(rng.random(rest.shape), axis=1)
            rest = np.take_along_axis(rest, perm, axis=1)
            members = [np.column_stack([order[:, 0], rest[:, :3]]), np.column_stack([order[:, 1], rest[:, 3:]])]
        pos = np.empty_like(order)
        np.put_along_axis(pos, order, np.broadcast_to(np.arange(self.T), order.shape), axis=1)
        winners = []
        for mem in members:
            if reach is not None and "groups" in reach:
                np.add.at(reach["groups"], mem.ravel(), 1)
            g = {k: np.zeros((S, 4), dtype=np.int32) for k in ("pts", "gf", "ga")}
            for i in range(4):
                for j in range(4):
                    if i == j:
                        continue
                    h, a = mem[:, i], mem[:, j]
                    hg, ag = self._leg(s.key, "group", h, a, rng)
                    g["pts"][:, i] += 3 * (hg > ag) + (hg == ag)
                    g["pts"][:, j] += 3 * (ag > hg) + (hg == ag)
                    g["gf"][:, i] += hg
                    g["ga"][:, i] += ag
                    g["gf"][:, j] += ag
                    g["ga"][:, j] += hg
                    if acc is not None:
                        _add(acc, rows, h, a, hg, ag)
            mpos = np.take_along_axis(pos, mem, axis=1)                  # round-robin position (0 = 1st)
            head = (mpos <= 1).astype(np.int32)                          # Art. 22: level on points, the head goes through
            o, _ = rank_table([g["pts"], head, g["gf"] - g["ga"], g["gf"], -mpos], rng)
            winners.append((mem[rows, o[:, 0]], g["pts"][rows, o[:, 0]]))
        (wa, pa), (wb, pb) = winners
        if reach is not None and "final" in reach:
            np.add.at(reach["final"], np.concatenate([wa, wb]), 1)
        tot_a = tab["pts"][rows, wa] + pa
        tot_b = tab["pts"][rows, wb] + pb
        a_hosts = (tot_a > tot_b) | ((tot_a == tot_b) & (np.take_along_axis(pos, wa[:, None], 1)[:, 0] < np.take_along_axis(pos, wb[:, None], 1)[:, 0]))
        second = np.where(a_hosts, wa, wb)
        first = np.where(a_hosts, wb, wa)
        return self._tie(s.key, "final", first, second, rng, two_legs=True, extra_time=0.0, acc=acc)

    def _knockout8(self, s, order, tab, rng, S, reach, acc) -> np.ndarray:
        """Two-legged quarter-finals (1st in bracket A, 2nd in bracket D, the other six drawn), semi-finals A v B and
        C v D, and the final; the better-placed club hosts the return (Arts. 10-15)."""
        rows = np.arange(S)
        pos = np.empty_like(order)
        np.put_along_axis(pos, order, np.broadcast_to(np.arange(self.T), order.shape), axis=1)
        qf_known = [m for m in s.playoff_done + s.playoff_left if m.round == "qf"]
        pairs = []
        seen = set()
        for m in qf_known:
            key = frozenset((m.home, m.away))
            if key not in seen and m.home in self.idx and m.away in self.idx:
                seen.add(key)
                pairs.append((self.idx[m.home], self.idx[m.away]))
        if len(pairs) == 4:
            first, second = order[:, 0], order[:, 1]
            ties = [np.tile(np.array(p), (S, 1)) for p in pairs]
            # bracket A holds 1st and D holds 2nd; B and C keep the store's order (the draw is not in the data)
            ia = next((i for i, p in enumerate(pairs) if int(first[0]) in p), 0)
            idd = next((i for i, p in enumerate(pairs) if int(second[0]) in p and i != ia), 3)
            mid = [i for i in range(4) if i not in (ia, idd)]
            ties = [ties[ia], ties[mid[0]], ties[mid[1]], ties[idd]]
        else:
            rest = order[:, 2:8]
            perm = np.argsort(rng.random(rest.shape), axis=1)
            rest = np.take_along_axis(rest, perm, axis=1)
            ties = [np.column_stack([order[:, 0], rest[:, 0]]), np.column_stack([rest[:, 1], rest[:, 2]]),
                    np.column_stack([rest[:, 3], rest[:, 4]]), np.column_stack([order[:, 1], rest[:, 5]])]
        played_pts = tab["pts"].copy()

        def better(x, y):
            px, py = played_pts[rows, x], played_pts[rows, y]
            ox, oy = pos[rows, x], pos[rows, y]
            top = (ox <= 1) | (oy <= 1)
            by_pos = ox < oy
            return np.where(top, by_pos, (px > py) | ((px == py) & by_pos))

        winners = []
        for t in ties:
            x, y = t[:, 0], t[:, 1]
            if reach is not None and "qf" in reach:
                np.add.at(reach["qf"], np.concatenate([x, y]), 1)
            hx = better(x, y)
            winners.append(self._tie(s.key, "qf", np.where(hx, y, x), np.where(hx, x, y), rng, True, 0.0, acc))
        for rnd in ("sf", "final"):
            nxt = []
            for i in range(0, len(winners), 2):
                x, y = winners[i], winners[i + 1]
                if reach is not None and rnd in reach:
                    np.add.at(reach[rnd], np.concatenate([x, y]), 1)
                hx = better(x, y)
                nxt.append(self._tie(s.key, rnd, np.where(hx, y, x), np.where(hx, x, y), rng, True, 0.0, acc))
            winners = nxt
        return winners[0]

    def _intermedio_groups(self, s, orders, rng, S) -> list[np.ndarray]:
        seed = orders.get(s.fmt.seed_from or "")
        if seed is None:
            seed = np.tile(np.arange(self.T), (S, 1))
        a_pos = [p - 1 for p in s.fmt.group_a if p - 1 < self.T]
        b_pos = [p for p in range(self.T) if p not in a_pos]
        return [seed[:, a_pos], seed[:, b_pos]]

    def _group_final(self, s, tab, order, rng, S, reach) -> np.ndarray:
        """Uruguay's Intermedio: two groups seeded from the Apertura table, each won on its own table, and a one-match
        final at a neutral ground (penalties after extra time)."""
        rows = np.arange(S)
        seed_stage = self.state.stage(s.fmt.seed_from or "")
        if seed_stage is not None and seed_stage.regular_complete:
            seed_order = np.array([self.idx[t] for t, _r, _p in self.state.standings(seed_stage.key) if t in self.idx])
            seed = np.tile(seed_order, (S, 1))
        else:
            seed = np.tile(np.arange(self.T), (S, 1))
        a_pos = [p - 1 for p in s.fmt.group_a if p - 1 < self.T]
        b_pos = [p for p in range(self.T) if p not in a_pos]
        ws = []
        for cols in (a_pos, b_pos):
            mem = seed[:, cols]
            by = {"pts": tab["pts"], "gd": tab["gf"] - tab["ga"], "gf": tab["gf"], "w": tab["w"]}
            keys = [np.take_along_axis(by[k], mem, axis=1) for k in self.cfg.tiebreak]
            o, _ = rank_table(keys, rng)
            ws.append(mem[rows, o[:, 0]])
        if reach is not None and "final" in reach:
            np.add.at(reach["final"], np.concatenate(ws), 1)
        return self._tie(s.key, "final", ws[0], ws[1], rng, two_legs=False, extra_time=0.5)

    # ── season champions ────────────────────────────────────────────────────

    def _uruguay(self, champs, agg_order, rng, S, reach):
        """
        The Apertura and Clausura winners in a semi-final (one match at the better Anual club's ground; the venue is
        not in the sources), its winner against the Tabla Anual leader over two legs (the leader at home in the
        second). A club that won both stages, or that leads the Anual and wins the semi-final, is champion outright.
        Runner-up: the final's loser, or with no final the best other club of the Anual.
        """
        a, c = champs.get("apertura"), champs.get("clausura")
        leader = agg_order[:, 0]
        rows = np.arange(S)
        apos = np.empty_like(agg_order)
        np.put_along_axis(apos, agg_order, np.broadcast_to(np.arange(self.T), agg_order.shape), axis=1)
        if self.state.champion is not None:
            champ = np.full(S, self.idx.get(self.state.champion, -1), dtype=np.intp)
            runner = self._best_other(agg_order, champ)
            return champ, runner
        both = a == c
        a_home = apos[rows, a] <= apos[rows, c]
        if "sf" in reach:
            np.add.at(reach["sf"], np.concatenate([a[~both], c[~both]]), 1)
        sw = self._tie(SEASON, "sf", np.where(a_home, a, c), np.where(a_home, c, a), rng, two_legs=False, extra_time=0.5)
        champ = np.where(both, a, -1)
        direct = (~both) & (sw == leader)
        champ = np.where(direct, sw, champ)
        runner = np.full(S, -1, dtype=np.intp)
        need_final = (~both) & (~direct)
        if "final" in reach:
            np.add.at(reach["final"], np.concatenate([sw[need_final], leader[need_final]]), 1)
            np.add.at(reach["final"], np.concatenate([a[both], sw[direct]]), 1)
        fw = self._tie(SEASON, "final", sw, leader, rng, two_legs=True, extra_time=0.5)
        champ = np.where(need_final, fw, champ)
        runner = np.where(need_final, np.where(fw == sw, leader, sw), runner)
        other = self._best_other(agg_order, champ)
        runner = np.where(runner >= 0, runner, other)
        return champ.astype(np.intp), runner.astype(np.intp)

    def _best_other(self, agg_order, champ):
        first, second = agg_order[:, 0], agg_order[:, 1]
        return np.where(first == champ, second, first)

    def _peru(self, champs, agg_order, rng, S, reach):
        """
        Reglamento Liga1 2026, 7.3 and 8: the Apertura and Clausura winners (each only when in the Acumulada top 8)
        and the Acumulada 1st and 2nd. Four clubs: semi-finals best v worst and 2nd v 3rd of the four by the
        Acumulada. A stage winner that is also Acumulada top-2 goes straight to the final and the other two meet in
        one semi-final; with a stage winner outside the top 8, the best of the other three goes straight to the
        final; both winners 1st and 2nd: a direct final. Every tie is two legs, the better Acumulada club hosting
        the return; points, aggregate goal difference, penalties. One club winning both stages is champion and
        3rd v 4th then the winner v 2nd decide the runner-up. Places 3 and 4 go to the losing semi-finalists by the
        Acumulada, the rest follow the Acumulada.
        """
        T = self.T
        rows = np.arange(S)
        apos = np.empty_like(agg_order)
        np.put_along_axis(apos, agg_order, np.broadcast_to(np.arange(T), agg_order.shape), axis=1)
        a, c = champs.get("apertura"), champs.get("clausura")
        first, second = agg_order[:, 0], agg_order[:, 1]
        champ = np.full(S, -1, dtype=np.intp)
        runner = np.full(S, -1, dtype=np.intp)
        third = np.full(S, -1, dtype=np.intp)
        fourth = np.full(S, -1, dtype=np.intp)

        def tie(x, y, rnd):
            x_better = apos[rows, x] < apos[rows, y]
            return self._tie(SEASON, rnd, np.where(x_better, y, x), np.where(x_better, x, y), rng, True, 0.0)

        def by_agg(x, y):
            return np.where(apos[rows, x] < apos[rows, y], x, y)

        both = a == c
        # one club won both: champion; 3rd v 4th, then its winner v 2nd for runner-up (the champion's places skipped)
        if both.any():
            # the Acumulada without the champion: one club removed from every row
            rest_teams = agg_order[agg_order != a[:, None]].reshape(S, T - 1)
            p2, p3, p4 = rest_teams[:, 0], rest_teams[:, 1], rest_teams[:, 2]
            w1 = tie(p3, p4, "any")
            l1 = np.where(w1 == p3, p4, p3)
            w2 = tie(w1, p2, "any")
            l2 = np.where(w2 == p2, w1, p2)
            champ = np.where(both, a, champ)
            runner = np.where(both, w2, runner)
            third = np.where(both, l2, third)
            fourth = np.where(both, l1, fourth)
            if "playoffs" in reach:
                for arr in (p2, p3, p4):
                    np.add.at(reach["playoffs"], arr[both], 1)
        a_in = apos[rows, a] < 8
        c_in = apos[rows, c] < 8
        top2 = lambda x: (x == first) | (x == second)  # noqa: E731
        # participants (up to four, distinct), each simulation
        part = np.full((S, 4), -1, dtype=np.intp)
        n_part = np.zeros(S, dtype=np.int32)
        for cand, use in ((first, np.ones(S, bool)), (second, np.ones(S, bool)), (a, a_in), (c, c_in)):
            new = use & ~(part == cand[:, None]).any(axis=1)
            part[rows[new], n_part[new]] = cand[new]
            n_part = n_part + new
        live = ~both
        if "playoffs" in reach:
            for k in range(4):
                sel = live & (part[:, k] >= 0)
                np.add.at(reach["playoffs"], part[sel, k], 1)
        # order the participants by the Acumulada
        key = np.where(part >= 0, apos[rows[:, None], np.maximum(part, 0)], T + 1)
        o = np.argsort(key, axis=1)
        part = np.take_along_axis(part, o, axis=1)
        n4 = live & (n_part == 4)
        n3 = live & (n_part == 3)
        n2 = live & (n_part == 2)
        # three clubs: a stage winner in the top two goes straight through (7.3.1.7); otherwise the best of the three
        # (7.3.1.6, a winner outside the top 8)
        stage_top = np.where(top2(a) & a_in & ~top2(c) & c_in, a, np.where(top2(c) & c_in & ~top2(a) & a_in, c, -1))
        bye = np.where(stage_top >= 0, stage_top, part[:, 0])
        others = np.where(part == bye[:, None], -1, part)
        ok = np.sort(np.where(others >= 0, apos[rows[:, None], np.maximum(others, 0)], T + 1), axis=1)
        x3 = np.take_along_axis(agg_order, np.minimum(ok[:, :1], T - 1), axis=1)[:, 0]
        y3 = np.take_along_axis(agg_order, np.minimum(ok[:, 1:2], T - 1), axis=1)[:, 0]
        # semi-finals
        s1 = tie(part[:, 0], np.where(n4, part[:, 3], part[:, 1]), "sf")
        s2 = tie(part[:, 1], part[:, 2], "sf")
        s3 = tie(x3, y3, "sf")
        f_x = np.where(n4, s1, np.where(n3, bye, part[:, 0]))
        f_y = np.where(n4, s2, np.where(n3, s3, part[:, 1]))
        if "sf" in reach:
            for arr, sel in ((part[:, 0], n4), (part[:, 3], n4), (part[:, 1], n4), (part[:, 2], n4), (x3, n3), (y3, n3)):
                np.add.at(reach["sf"], arr[sel], 1)
        if "final" in reach:
            for arr in (f_x, f_y):
                np.add.at(reach["final"], arr[live], 1)
        fw = tie(f_x, f_y, "final")
        fl = np.where(fw == f_x, f_y, f_x)
        champ = np.where(live, fw, champ)
        runner = np.where(live, fl, runner)
        l_s1 = np.where(s1 == part[:, 0], part[:, 3], part[:, 0])
        l_s2 = np.where(s2 == part[:, 1], part[:, 2], part[:, 1])
        l_s3 = np.where(s3 == x3, y3, x3)
        b4 = by_agg(l_s1, l_s2)
        w4 = np.where(b4 == l_s1, l_s2, l_s1)
        third = np.where(n4, b4, np.where(n3, l_s3, third))
        fourth = np.where(n4, w4, fourth)
        if self.state.champion is not None:
            champ = np.full(S, self.idx.get(self.state.champion, -1), dtype=np.intp)
        # final places: the four, then the Acumulada
        places = np.full((S, T), -1, dtype=np.intp)
        head = np.column_stack([champ, runner, third, fourth])
        for r in range(S):
            seen = [int(x) for x in head[r] if x >= 0]
            seen = list(dict.fromkeys(seen))
            rest = [int(x) for x in agg_order[r] if int(x) not in seen]
            places[r] = np.array((seen + rest)[:T])
        return champ, runner, places

    # ── berths ──────────────────────────────────────────────────────────────

    def _berths(self, champs, title, runner, places, agg_order, rel, rng, S, cup_p, cup_total):
        fmt = self.fmt
        T = self.T
        rows = np.arange(S)
        lib = np.zeros((S, T), dtype=bool)
        sud = np.zeros((S, T), dtype=bool)

        def fill(mask, n_target, other):
            count = mask.sum(axis=1)
            for p in range(T):
                cand = agg_order[:, p]
                take = (count < n_target) & ~mask[rows, cand] & ~other[rows, cand] & ~rel[rows, cand]
                mask[rows[take], cand[take]] = True
                count = count + take
            return mask

        if fmt.berths == "peru":
            lib[rows[:, None], places[:, :fmt.libertadores]] = True
            sud[rows[:, None], places[:, fmt.libertadores:fmt.libertadores + fmt.sudamericana]] = True
            return lib, sud
        if fmt.berths == "colombia":
            for key in ("apertura", "clausura"):
                ch = champs.get(key)
                if ch is not None:
                    ok = ch >= 0
                    lib[rows[ok], ch[ok]] = True
            lib = fill(lib, fmt.libertadores, np.zeros_like(lib))
            if cup_total > 0:
                # the Copa BetPlay champion, drawn from the cup's own simulation (a club outside this league wins
                # with the remaining probability, and then the place goes down the table: Art. 31, Par. 1)
                probs = np.append(cup_p, max(0.0, 1.0 - cup_p.sum()))
                probs = probs / probs.sum()
                draw = rng.choice(T + 1, size=S, p=probs)
                okc = (draw < T)
                okc[okc] &= ~lib[rows[okc], draw[okc]] & ~rel[rows[okc], draw[okc]]
                sud[rows[okc], draw[okc]] = True
            sud = fill(sud, fmt.sudamericana, lib)
            return lib, sud
        # uruguay
        for arr in (title, runner):
            if arr is not None:
                ok = arr >= 0
                lib[rows[ok], arr[ok]] = True
        lib = fill(lib, fmt.libertadores, np.zeros_like(lib))
        sud = fill(sud, fmt.sudamericana, lib)
        return lib, sud

    # ── assembly ────────────────────────────────────────────────────────────

    def _assemble(self, n, runtime, cur, cnt, sums, samples, reach_rounds) -> TorneoResults:
        res = TorneoResults(n_sims=n, runtime_s=runtime, teams=list(self.teams), stage_key=cur.key,
                            reach_rounds=tuple(r for r in reach_rounds if r != "playoffs"))
        pts = np.concatenate(samples["pts"], axis=0) if samples["pts"] else None
        agg = np.concatenate(samples["agg"], axis=0) if samples["agg"] else None
        prom = np.concatenate(samples["prom"], axis=0) if samples["prom"] else None
        for t, i in self.idx.items():
            res.p_position[t] = (cnt["pos"][i] / n).tolist()
            res.p_agg_position[t] = (cnt["agg_pos"][i] / n).tolist()
            res.expected_points[t] = float(sums["pts"][i] / n)
            res.agg_expected_points[t] = float(sums["agg"][i] / n)
            res.team_goals_mean[t] = float(sums["goals"][i] / n)
            if pts is not None:
                q = np.quantile(pts[:, i], [0.05, 0.5, 0.95])
                res.points_quantiles[t] = (float(q[0]), float(q[1]), float(q[2]))
            if agg is not None:
                q = np.quantile(agg[:, i], [0.05, 0.5, 0.95])
                res.agg_points_quantiles[t] = (float(q[0]), float(q[1]), float(q[2]))
            if prom is not None:
                q = np.quantile(prom[:, i], [0.05, 0.5, 0.95])
                res.promedio_quantiles[t] = (float(q[0]), float(q[1]), float(q[2]))
            res.p_title[t] = float(cnt["title"][i] / n)
            res.p_runner_up[t] = float(cnt["runner"][i] / n)
            res.p_libertadores[t] = float(cnt["lib"][i] / n)
            res.p_sudamericana[t] = float(cnt["sud"][i] / n)
            res.p_relegation[t] = float(cnt["rel"][i] / n)
            if "playoffs" in cnt["reach"]:
                res.p_playoffs[t] = float(cnt["reach"]["playoffs"][i] / n)
            res.p_reach[t] = {r: float(cnt["reach"][r][i] / n) for r in cnt["reach"] if r != "playoffs"}
        for key, c in cnt["stage"].items():
            res.p_stage[key] = {t: float(c[i] / n) for t, i in self.idx.items()}
        res.p_cup = dict(res.p_title)
        for b in self.cfg.bands:
            res.p_band[b.key] = {t: float(sum(d[b.first - 1: b.last])) for t, d in res.p_position.items()}
        return res


def _add(tab: dict[str, np.ndarray], rows: np.ndarray, h: np.ndarray, a: np.ndarray, hg: np.ndarray, ag: np.ndarray) -> None:
    """Add one simulated match per row to a (S, T) table (points, goals, wins, matches)."""
    np.add.at(tab["pts"], (rows, h), 3 * (hg > ag) + (hg == ag))
    np.add.at(tab["pts"], (rows, a), 3 * (ag > hg) + (hg == ag))
    np.add.at(tab["gf"], (rows, h), hg)
    np.add.at(tab["ga"], (rows, h), ag)
    np.add.at(tab["gf"], (rows, a), ag)
    np.add.at(tab["ga"], (rows, a), hg)
    np.add.at(tab["w"], (rows, h), (hg > ag).astype(np.int32))
    np.add.at(tab["w"], (rows, a), (ag > hg).astype(np.int32))
    np.add.at(tab["mp"], (rows, h), 1)
    np.add.at(tab["mp"], (rows, a), 1)


def _add_known(tab: dict[str, np.ndarray], played: Iterable[TorneoMatch], idx: dict[str, int]) -> None:
    """Add played matches to every row of a table: a closed stage's playoffs (an open stage's played legs are added
    as the simulation replays them, forced, so they are never added twice)."""
    for m in played:
        h, a = idx.get(m.home), idx.get(m.away)
        if h is None or a is None or not m.done:
            continue
        tab["pts"][:, h] += 3 * (m.hg > m.ag) + (m.hg == m.ag)
        tab["pts"][:, a] += 3 * (m.ag > m.hg) + (m.hg == m.ag)
        tab["gf"][:, h] += m.hg
        tab["ga"][:, h] += m.ag
        tab["gf"][:, a] += m.ag
        tab["ga"][:, a] += m.hg
        tab["w"][:, h] += int(m.hg > m.ag)
        tab["w"][:, a] += int(m.ag > m.hg)
        tab["mp"][:, h] += 1
        tab["mp"][:, a] += 1
