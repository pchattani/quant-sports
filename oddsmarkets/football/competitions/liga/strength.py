"""
Team strength, form and luck.

The build already fits Elo ratings and Dixon-Coles attack/defence parameters every
run, uses them to simulate, and then discards them. This module exposes them, plus
the two derived views that most often disagree with the league table.

Why this matters more in a league than in a tournament: over 16 matches the table is
a noisy estimate of strength. A club can sit fourth on the back of a soft schedule and
a run of one-goal wins, and the table cannot tell you that. Three things separate
signal from noise here:

  - **Neutral strength** — expected points per game against a league-average opponent
    at a neutral venue. Schedule-independent by construction, so it is directly
    comparable across clubs in a way the table is not.
  - **Schedule strength** — the average quality of opponents already faced against
    those still to come. This is what makes an early-season table misleading.
  - **Luck** — points actually taken against points the underlying xG deserved.
    Sustained overperformance is usually finishing variance rather than a skill.

None of these are predictions; they are descriptions of what has happened and of what
the fitted model believes. The forecast lives in the simulator.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logging.getLogger(__name__)
logger = logging.getLogger(__name__)

# Trailing window for form. Six matches is a little over a third of a 16-game
# tournament — long enough to mean something, short enough to still be "recent".
FORM_WINDOW = 6

# Goal ceiling when converting xG into an expected-points distribution.
_MAX_GOALS = 8


@dataclass
class TeamStrength:
    """Everything the power-rankings view shows for one club."""

    team: str
    elo: float = 0.0
    attack: float = 0.0
    defence: float = 0.0
    strength_ppg: float = 0.0          # expected points/game vs an average opponent
    strength_rank: int = 0
    table_rank: int = 0
    rank_delta: int = 0                # table position minus strength rank

    played: int = 0
    points: int = 0
    ppg: float = 0.0

    form_points: int = 0               # points in the trailing window
    form_ppg: float = 0.0
    form_gf: int = 0
    form_ga: int = 0
    form_results: list[str] = field(default_factory=list)   # "W"/"D"/"L", oldest first

    xg_for: float = 0.0
    xg_against: float = 0.0
    xg_diff: float = 0.0
    expected_points: float = 0.0       # points the xG deserved
    luck: float = 0.0                  # actual minus expected

    sos_played: float = 0.0            # mean opponent strength faced
    sos_remaining: float = 0.0         # mean opponent strength still to come
    sos_delta: float = 0.0             # remaining minus played: positive = harder run-in

    elo_history: list[dict] = field(default_factory=list)


def _poisson_pmf(lam: float, k: int) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def expected_points_from_xg(home_xg: float, away_xg: float) -> tuple[float, float]:
    """
    Points each side "deserved" from a match, given the xG both created.

    Goals are treated as independent Poisson draws with means equal to the xG. This
    is the standard xPoints construction: it deliberately ignores the actual result,
    so comparing it to real points isolates finishing and goalkeeping variance from
    chance creation.
    """
    p_home = p_draw = p_away = 0.0
    for h in range(_MAX_GOALS + 1):
        ph = _poisson_pmf(home_xg, h)
        for a in range(_MAX_GOALS + 1):
            p = ph * _poisson_pmf(away_xg, a)
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    if total <= 0:
        return 1.0, 1.0
    p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total
    return 3 * p_home + p_draw, 3 * p_away + p_draw


def neutral_strength(model, teams: list[str]) -> dict[str, float]:
    """
    Expected points per game for each club against a league-average opponent, on
    neutral ground.

    Averaging over every possible opponent is what removes schedule effects — unlike
    points per game, two clubs' values are directly comparable even if neither has
    played the other.
    """
    out: dict[str, float] = {}
    for team in teams:
        total = 0.0
        count = 0
        for opp in teams:
            if opp == team:
                continue
            try:
                p = model.predict(team, opp, neutral=True)
            except Exception as exc:  # noqa: BLE001
                logger.debug("strength prediction failed for %s vs %s: %s", team, opp, exc)
                continue
            total += 3 * p.home_win + p.draw
            count += 1
        out[team] = round(total / count, 4) if count else 0.0
    return out


def build_team_strength(
    model,
    state,
    teams: list[str],
    xg_by_match: dict[str, tuple[float, float]] | None = None,
    form_window: int = FORM_WINDOW,
) -> list[TeamStrength]:
    """
    Assemble the full power-rankings view.

    `state` is a SeasonState; only its live tournament is described, so the numbers
    line up with the zone tables the rest of the site shows.
    """
    xg_by_match = xg_by_match or {}
    torneo = state.live_torneo() or state.clausura
    records = torneo.records()

    strength = neutral_strength(model, teams)
    out: dict[str, TeamStrength] = {}

    for team in teams:
        rec = records.get(team)
        ts = TeamStrength(team=team, strength_ppg=strength.get(team, 0.0))
        if rec:
            ts.played = rec.played
            ts.points = rec.points
            ts.ppg = round(rec.points / rec.played, 3) if rec.played else 0.0
        try:
            ts.elo = round(float(model.elo.get_rating(team)), 1)
        except Exception:  # noqa: BLE001
            ts.elo = 0.0
        params = getattr(getattr(model, "dc", None), "params_", {}) or {}
        ts.attack = round(float(params.get(f"attack_{team}", 0.0)), 4)
        ts.defence = round(float(params.get(f"defense_{team}", 0.0)), 4)
        out[team] = ts

    # Walk finished league matches in order, accumulating form, xG and expected points.
    finished = sorted(
        [m for m in torneo.finished if m.is_finished and not m.is_playoff],
        key=lambda m: (m.date is None, m.date),
    )
    per_team_results: dict[str, list[dict]] = {t: [] for t in teams}

    for m in finished:
        home, away = m.home_team, m.away_team
        if home not in out or away not in out:
            continue
        hg, ag = int(m.home_goals), int(m.away_goals)
        hxg, axg = xg_by_match.get(m.game_id, (None, None))

        for team, gf, ga, opp, own_xg, opp_xg in (
            (home, hg, ag, away, hxg, axg),
            (away, ag, hg, home, axg, hxg),
        ):
            result = "W" if gf > ga else "D" if gf == ga else "L"
            per_team_results[team].append({
                "result": result, "gf": gf, "ga": ga, "opponent": opp,
                "date": m.date.strftime("%Y-%m-%d") if m.date else None,
            })
            ts = out[team]
            if own_xg is not None and opp_xg is not None:
                ts.xg_for += float(own_xg)
                ts.xg_against += float(opp_xg)

        if hxg is not None and axg is not None:
            xp_home, xp_away = expected_points_from_xg(float(hxg), float(axg))
            out[home].expected_points += xp_home
            out[away].expected_points += xp_away

    # Form over the trailing window, and strength of schedule.
    remaining_by_team: dict[str, list[str]] = {t: [] for t in teams}
    for m in torneo.remaining:
        if m.is_playoff:
            continue
        if m.home_team in remaining_by_team:
            remaining_by_team[m.home_team].append(m.away_team)
        if m.away_team in remaining_by_team:
            remaining_by_team[m.away_team].append(m.home_team)

    for team, ts in out.items():
        results = per_team_results.get(team, [])
        window = results[-form_window:]
        ts.form_results = [r["result"] for r in window]
        ts.form_points = sum(3 if r["result"] == "W" else 1 if r["result"] == "D" else 0
                             for r in window)
        ts.form_ppg = round(ts.form_points / len(window), 3) if window else 0.0
        ts.form_gf = sum(r["gf"] for r in window)
        ts.form_ga = sum(r["ga"] for r in window)

        played_opps = [r["opponent"] for r in results]
        ts.sos_played = round(
            sum(strength.get(o, 0.0) for o in played_opps) / len(played_opps), 4
        ) if played_opps else 0.0
        upcoming = remaining_by_team.get(team, [])
        ts.sos_remaining = round(
            sum(strength.get(o, 0.0) for o in upcoming) / len(upcoming), 4
        ) if upcoming else 0.0
        ts.sos_delta = round(ts.sos_remaining - ts.sos_played, 4)

        ts.xg_for = round(ts.xg_for, 2)
        ts.xg_against = round(ts.xg_against, 2)
        ts.xg_diff = round(ts.xg_for - ts.xg_against, 2)
        ts.expected_points = round(ts.expected_points, 2)
        # Only meaningful where xG actually covered the matches played.
        ts.luck = round(ts.points - ts.expected_points, 2) if ts.expected_points else 0.0

    # Ranks: model strength against where the club actually sits in its zone.
    ordered = sorted(out.values(), key=lambda t: -t.strength_ppg)
    for i, ts in enumerate(ordered, start=1):
        ts.strength_rank = i

    for zone in torneo.zones:
        for pos, (team, _rec) in enumerate(torneo.standings(zone), start=1):
            if team in out:
                out[team].table_rank = pos

    # Compare like with like: a club's strength rank restricted to its own zone, so
    # the delta against its zone position is meaningful rather than comparing a
    # 30-club ranking to a 15-club table.
    for zone, members in torneo.zones.items():
        in_zone = sorted(
            [out[t] for t in members if t in out], key=lambda t: -t.strength_ppg
        )
        for pos, ts in enumerate(in_zone, start=1):
            ts.rank_delta = ts.table_rank - pos

    return sorted(out.values(), key=lambda t: -t.strength_ppg)


def elo_trajectories(model_factory, state, teams: list[str]) -> dict[str, list[dict]]:
    """
    Elo rating after each finished match, per club.

    Takes a factory rather than a fitted model because the trajectory has to be
    rebuilt by replaying results from the seed — reading the final ratings would give
    a flat line at today's value.
    """
    elo = model_factory()
    torneo = state.live_torneo() or state.clausura
    history: dict[str, list[dict]] = {t: [] for t in teams}

    finished = sorted(
        [m for m in torneo.finished if m.is_finished and not m.is_playoff],
        key=lambda m: (m.date is None, m.date),
    )
    for m in finished:
        if m.home_team not in history or m.away_team not in history:
            continue
        elo.update(
            m.home_team, m.away_team,
            int(m.home_goals), int(m.away_goals),
            tournament_type="league", neutral=False,
        )
        stamp = m.date.strftime("%Y-%m-%d") if m.date else None
        for team in (m.home_team, m.away_team):
            history[team].append({"date": stamp, "elo": round(elo.get_rating(team), 1)})

    return history
