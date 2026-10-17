#!/usr/bin/env python
"""
Build the static JSON payloads for the Liga Profesional dashboard.

Like scripts/build_site_wc.py, this emits only JSON into docs/liga/data/; the HTML,
CSS and JS are hand-maintained files shipped verbatim by the deploy rsync, which
makes docs/liga/ the root of the published Pages repo.

Design rule inherited from the World Cup build and worth restating: every external
dependency degrades rather than fails. Sofascore is unreachable from CI by design, so
the build must produce a complete site from the committed store alone. If that is ever
not true, the hourly job breaks the site instead of merely leaving it stale.

    python scripts/build_site_liga.py
    python scripts/build_site_liga.py --sims 20000     # faster local iteration
    python scripts/build_site_liga.py --no-market      # skip the odds fetch
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.liga.config import (  # noqa: E402
    APERTURA,
    CLAUSURA,
    DEFAULT_CONFIG,
    PLAYOFF_PAIRINGS,
    PLAYOFF_ROUNDS,
    ROUND_LABELS,
    LigaConfig,
    ZONES,
)
from oddsmarkets.football.core.markets import (  # noqa: E402
    build_match_markets,
    build_outright_markets,
)
from oddsmarkets.football.competitions.liga.simulator import LigaResults, LigaSimulator  # noqa: E402
from oddsmarkets.football.competitions.liga.strength import (  # noqa: E402
    FORM_WINDOW,
    build_team_strength,
    elo_trajectories,
)
from oddsmarkets.football.competitions.liga.store import (  # noqa: E402
    aggregate_players,
    team_xg_map,
    empirical_calibration,
    load_store,
    match_details,
    season_state_from_store,
    shots_by_player,
    store_age_hours,
    training_frame,
)
from oddsmarkets.football.sources.teams import normalize_team_name  # noqa: E402
from oddsmarkets.football.core import (  # noqa: E402
    DixonColesModel,
    EloRatings,
    EnsembleModel,
    GoldenBootModel,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("build-liga")

SITE_DIR = ROOT / "docs" / "liga"
DATA_DIR = SITE_DIR / "data"
STORE_PATH = DATA_DIR / "liga_store.json"
HISTORY_STORE = DATA_DIR / "history_store.json"
PKG_DATA = ROOT / "oddsmarkets" / "football" / "competitions" / "liga" / "data"

# Fitted from walk-forward log-loss over the committed seasons by
# scripts/tune_liga_model.py. Until that has been run against real data these are
# reasoned starting points, not measurements, and are labelled as such on the site.
ELO_HOME_ADVANTAGE = 70.0
ELO_K_LEAGUE = 20
ELO_RANK_SCALE = 10.0
DC_WEIGHT = 0.80
DC_RIDGE = 0.5
DC_XI = 0.0035

# scripts/tune_league_models.py writes a walk-forward-tuned set for Argentina
# alongside the leagues'; when it exists it overrides the constants above.
MODEL_PARAMS_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "model_params.json"
MODEL_PARAMS_METHOD = "default"
try:
    _tuned = json.loads(MODEL_PARAMS_PATH.read_text(encoding="utf-8")).get("leagues", {}).get("liga-argentina")
except Exception:  # noqa: BLE001
    _tuned = None
if _tuned and _tuned.get("params"):
    _p = _tuned["params"]
    ELO_HOME_ADVANTAGE = float(_p.get("elo_home_advantage", ELO_HOME_ADVANTAGE))
    ELO_K_LEAGUE = int(_p.get("k_league", ELO_K_LEAGUE))
    DC_WEIGHT = float(_p.get("dc_weight", DC_WEIGHT))
    DC_RIDGE = float(_p.get("ridge", DC_RIDGE))
    DC_XI = float(_p.get("xi", DC_XI))
    MODEL_PARAMS_METHOD = _tuned.get("method", "tuned")

STALE_AFTER_HOURS = 24.0
SEASON_STALE_DAYS = 30


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(name: str, payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    logger.info("wrote %s", name)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read %s: %s", path, exc)
        return default


# ── model ────────────────────────────────────────────────────────────────────

def build_model(train_df, teams: list[str], prev_rank: dict[str, int] | None):
    """
    Fit the ensemble.

    Unlike the World Cup path, everything here is played at a real venue, so the Elo
    carries a home-advantage term and Dixon-Coles is asked for non-neutral predictions.
    The draw rate and lambda scale are measured from the training data rather than
    inherited from World Cup group play, which is both lower-scoring and less
    draw-heavy than Argentine league football.
    """
    cal = empirical_calibration(train_df)
    logger.info(
        "calibration: draw_rate=%.3f mean_goals=%.2f home_win_rate=%.3f",
        cal["draw_rate"], cal["mean_goals"], cal["home_win_rate"],
    )

    elo = EloRatings(
        k_league=ELO_K_LEAGUE,
        home_advantage=ELO_HOME_ADVANTAGE,
    )
    ranking = prev_rank or {t: i + 1 for i, t in enumerate(teams)}
    elo.seed_from_ranking(ranking, n_teams=len(teams))
    # Rebuild ratings by replaying the season chronologically.
    if train_df is not None and len(train_df):
        for row in train_df.itertuples():
            elo.update(
                row.home_team, row.away_team,
                int(row.home_goals), int(row.away_goals),
                tournament_type="league", neutral=False,
            )

    dc = DixonColesModel(xi=DC_XI, ridge=DC_RIDGE, analytic_grad=True)
    if train_df is not None and len(train_df) >= 50:
        try:
            # Market-implied rates of past matches (oddsmarkets/football/sources/market_rates.py):
            # extra Dixon-Coles rows only; a no-op without the football-data files.
            from oddsmarkets.football.sources import market_rates
            fit_df = train_df if os.environ.get("NO_MARKET_RATES") else market_rates.with_market_rows(train_df, "liga-argentina")
            dc.fit(fit_df)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Dixon-Coles fit failed (%s) — falling back to Elo only", exc)
    else:
        logger.warning(
            "Only %d training matches — skipping the Dixon-Coles fit and relying on Elo",
            0 if train_df is None else len(train_df),
        )

    return EnsembleModel(
        dc, elo,
        dc_weight=DC_WEIGHT if dc.is_fitted else 0.0,
        draw_rate=cal["draw_rate"],
        lam_scale=cal["lam_scale"],
        # The Elo term already carries home advantage; applying the legacy away
        # multiplier as well would count the same asymmetry twice.
        away_penalty=1.0,
    ), cal


# ── payload builders ─────────────────────────────────────────────────────────

def build_teams_json(state, results: LigaResults, store: dict | None = None) -> dict:
    torneo = state.live_torneo() or state.clausura
    ids: dict[str, int] = {}
    for raw in ((store or {}).get("matches") or {}).values():
        for side, key in (("home", "home_id"), ("away", "away_id")):
            if raw.get(key):
                ids.setdefault(normalize_team_name(str(raw.get(side, "")), "liga_argentina"), int(raw[key]))
    out = {}
    for team in state.teams:
        tid = ids.get(team)
        crest = f"assets/crests/{tid}.png" if tid else None
        out[team] = {
            "slug": team.lower().replace(" ", "-").replace("'", ""),
            "zone": torneo.zone_of(team),
            "team_id": tid,
            # Only claim a crest that is actually committed beside the site.
            "crest": crest if crest and (SITE_DIR.parent / "site" / crest).exists() else None,
        }
    return {"teams": out, "updated_at": _now()}


def build_zones_json(state, results: LigaResults, cfg: LigaConfig) -> dict:
    torneo = state.live_torneo() or state.clausura
    zones = {}
    for zone in ZONES:
        rows = []
        for pos, (team, rec) in enumerate(torneo.standings(zone), start=1):
            rows.append({
                "pos": pos, "team": team,
                "played": rec.played, "w": rec.won, "d": rec.drawn, "l": rec.lost,
                "gf": rec.gf, "ga": rec.ga, "gd": rec.gd, "pts": rec.points,
                "p_top8": round(results.p_top8.get(team, 0.0), 5),
                "p_zone_win": round(results.p_zone_win.get(team, 0.0), 5),
                "exp_pts": round(results.expected_points.get(team, 0.0), 2),
            })
        fixtures = [
            {
                "round": m.round_name, "home": m.home_team, "away": m.away_team,
                "hg": m.home_goals, "ag": m.away_goals,
                "date": m.date.strftime("%Y-%m-%d") if m.date else None,
                "done": m.is_finished,
            }
            for m in sorted(
                [x for x in torneo.finished + torneo.remaining if x.zone == zone],
                key=lambda x: (x.date or datetime.max.replace(tzinfo=timezone.utc)),
            )
        ]
        zones[zone] = {
            "standings": rows,
            "fixtures": fixtures,
            "games_played": sum(1 for f in fixtures if f["done"]),
            "total_games": len(fixtures),
        }
    return {
        "tournament": torneo.key,
        "qualifiers_per_zone": cfg.qualifiers_per_zone,
        "zones": zones,
        "updated_at": _now(),
    }


def build_bracket_json(state, results: LigaResults, cfg: LigaConfig) -> dict:
    torneo = state.live_torneo() or state.clausura
    seeds = []
    for pos, (left, right) in enumerate(PLAYOFF_PAIRINGS):
        for label in (left, right):
            zone = cfg.zone_of_seed(label)
            rank = cfg.rank_of_seed(label)
            standings = torneo.standings(zone)
            occupant = standings[rank - 1][0] if len(standings) >= rank else None
            seeds.append({
                "slot": len(seeds),
                "label": label,
                "pair": pos,
                "likely": occupant,
                "confirmed": torneo.league_complete,
            })
    return {
        "rounds": list(PLAYOFF_ROUNDS),
        "round_labels": ROUND_LABELS,
        "seeds": seeds,
        "results": torneo.playoff_results,
        "reach": {
            team: {r: round(p, 5) for r, p in reach.items()}
            for team, reach in results.p_reach.items()
        },
        "p_title": {t: round(p, 5) for t, p in results.p_title.items()},
        "updated_at": _now(),
    }


def build_anual_json(state, results: LigaResults, cfg: LigaConfig) -> dict:
    base = state.anual_base()
    rows = []
    for team in state.teams:
        rec = base.get(team)
        rows.append({
            "team": team,
            "pts_now": rec.points if rec else 0,
            "played": rec.played if rec else 0,
            "gd": rec.gd if rec else 0,
            "exp_pts": round(results.expected_anual_points.get(team, 0.0), 2),
            "p_champion": round(results.p_anual_champion.get(team, 0.0), 5),
            "p_libertadores": round(results.p_libertadores.get(team, 0.0), 5),
            "p_sudamericana": round(results.p_sudamericana.get(team, 0.0), 5),
            "p_last": round(results.p_anual_position.get(team, [0.0])[-1], 5),
            # Full finishing distribution, for the position heatmap.
            "p_pos": [round(p, 5) for p in results.p_anual_position.get(team, [])],
        })
    rows.sort(key=lambda r: (-r["exp_pts"], -r["pts_now"]))
    for i, row in enumerate(rows, start=1):
        row["pos"] = i
    return {
        "rows": rows,
        "berths": {
            "libertadores": cfg.libertadores_berths,
            "sudamericana": cfg.sudamericana_berths,
            "copa_argentina_winner": cfg.copa_argentina_winner,
            "note": (
                "Los campeones del Apertura, del Clausura y de la Copa Argentina "
                "clasifican directo a la Libertadores; los cupos restantes salen de "
                "esta tabla. La Copa Argentina queda fuera del modelo: si su campeón "
                "ya está definido se toma como dado, y si no, se asume que ese cupo "
                "se resuelve por la tabla."
            ),
            "note_en": (
                "The Apertura, Clausura and Copa Argentina champions qualify directly "
                "for the Libertadores; the remaining berths come from this table. The "
                "Copa Argentina is outside the model: if its winner is already decided "
                "it is taken as given, otherwise that berth is assumed to resolve through "
                "the table."
            ),
        },
        "updated_at": _now(),
    }


def build_relegation_json(state, results: LigaResults, cfg: LigaConfig) -> dict:
    promedios = state.promedio_now()
    rows = []
    for team in state.teams:
        prior_pts, prior_mp = state.promedios_prior.get(team, (0, 0))
        q = results.promedio_quantiles.get(team, (0.0, 0.0, 0.0))
        rows.append({
            "team": team,
            "promedio_now": round(promedios.get(team, 0.0), 4),
            "prior_points": prior_pts,
            "prior_matches": prior_mp,
            "p05": round(q[0], 4), "p50": round(q[1], 4), "p95": round(q[2], 4),
            "p_promedio": round(results.p_relegation_promedio.get(team, 0.0), 5),
            "p_anual": round(results.p_relegation_anual.get(team, 0.0), 5),
            "p_any": round(results.p_relegation_any.get(team, 0.0), 5),
        })
    rows.sort(key=lambda r: r["promedio_now"])
    for i, row in enumerate(rows, start=1):
        row["pos"] = i
    return {
        "rows": rows,
        "rules": {
            "places": cfg.relegation_places,
            "promedio_seasons": cfg.promedio_seasons,
            "collision": cfg.relegation_collision,
            "note": (
                "Descienden dos clubes: el peor promedio de tres temporadas (puntos "
                "por partido) y el último de la Tabla Anual. Cuando se trata del mismo "
                "club, el segundo descenso pasa al siguiente peor promedio — por eso la "
                "vía del promedio explica, en promedio, algo más de un descenso."
            ),
            "note_en": (
                "Two clubs go down: the worst three-season promedio (points per match) "
                "and the last-placed club in the Tabla Anual. When that is the same club, "
                "the second descent passes to the next-worst promedio — which is why the "
                "promedio route accounts, on average, for slightly more than one descent."
            ),
        },
        "updated_at": _now(),
    }


def build_probs_json(state, results: LigaResults) -> dict:
    torneo = state.live_torneo() or state.clausura
    teams = []
    for team in state.teams:
        teams.append({
            "team": team,
            "zone": torneo.zone_of(team),
            "p_top8": round(results.p_top8.get(team, 0.0), 5),
            "p_qf": round(results.p_reach.get(team, {}).get("qf", 0.0), 5),
            "p_sf": round(results.p_reach.get(team, {}).get("sf", 0.0), 5),
            "p_final": round(results.p_reach.get(team, {}).get("final", 0.0), 5),
            "p_title": round(results.p_title.get(team, 0.0), 5),
            "p_anual": round(results.p_anual_champion.get(team, 0.0), 5),
            "p_libertadores": round(results.p_libertadores.get(team, 0.0), 5),
            "p_sudamericana": round(results.p_sudamericana.get(team, 0.0), 5),
            "p_relegation": round(results.p_relegation_any.get(team, 0.0), 5),
            "exp_pts": round(results.expected_points.get(team, 0.0), 2),
        })
    teams.sort(key=lambda t: -t["p_title"])
    return {"teams": teams, "updated_at": _now()}


def build_players_json(
    store, results: LigaResults, boot_probs: dict, candidates: list[dict] | None = None
) -> tuple[dict, dict]:
    """
    players_live.json and player_leaders.json.

    Shapes are kept byte-compatible with the World Cup payloads, which is what lets
    the Players tab port across with no logic changes.

    The top-scorer probability is joined on (name, club) rather than name alone.
    GoldenBootModel keys its output by name, so joining on name would attach the same
    probability to every player sharing it — two namesakes at different clubs would
    each claim the full probability and the column would sum to more than 1.
    """
    players = aggregate_players(store)
    age = store_age_hours(store)
    fresh = age is not None and age < STALE_AFTER_HOURS

    # The club each probability actually belongs to, from the candidate list the model
    # was built from.
    prob_team = {c["name"]: c["team"] for c in (candidates or [])}

    leaders = []
    for p in players:
        prob = boot_probs.get(p["name"])
        if prob is not None and prob_team.get(p["name"]) not in (None, p["team"]):
            prob = None          # same name, different club — not this player's race
        leaders.append({
            "name": p["name"], "team": p["team"],
            "goals": p["goals"], "assists": p["assists"],
            "xg": p["xg"], "minutes": p["minutes"],
            "model": round(prob, 4) if prob is not None else None,
        })
    leaders.sort(key=lambda r: (-(r["model"] or 0), -r["goals"], -r["xg"]))

    live = {
        "ok": bool(players) or fresh,
        "updated_at": _now(),
        "checked_at": _now(),
        "matches_covered": len(store.get("lineups", {})),
        "players": players,
    }
    return live, {"top_scorer": leaders[:40], "live": leaders}


def build_boot_candidates(store, results: LigaResults, cap_per_team: int = 12) -> list[dict]:
    """
    Candidate scorers for the top-scorer race.

    Capped per club so squad depth does not swamp the field, and keyed on the club a
    player actually appeared for — mid-season transfers are common here, so a player's
    club is a property of their appearances rather than a fixed attribute.
    """
    players = aggregate_players(store)
    by_team: dict[str, list[dict]] = {}
    for p in players:
        if not p["team"] or p["is_gk"]:
            continue
        by_team.setdefault(p["team"], []).append(p)

    candidates = []
    for team, squad in by_team.items():
        squad.sort(key=lambda r: (-r["goals"], -r["xg"], -r["minutes"]))
        for p in squad[:cap_per_team]:
            per90 = p.get("goals_90", 0.0)
            candidates.append({
                "name": p["name"], "team": team,
                "cur_goals": p["goals"], "cur_assists": p["assists"],
                # No StatsBomb coverage for Argentina, so the historical rate comes
                # from this season's own per-90 rather than a prior tournament.
                "hist_goals_90": float(per90),
                "role": "FWD" if per90 >= 0.25 else "MID",
            })

    # GoldenBootModel returns probabilities keyed by player name, so two candidates
    # sharing a name would collide there and the same probability would then be joined
    # onto both rows — inflating the totals rather than splitting them. Merge duplicates
    # here instead, keeping the higher-scoring record.
    merged: dict[str, dict] = {}
    for c in candidates:
        prev = merged.get(c["name"])
        if prev is None or c["cur_goals"] > prev["cur_goals"]:
            merged[c["name"]] = c
    if len(merged) != len(candidates):
        logger.warning(
            "Merged %d duplicate player names among top-scorer candidates",
            len(candidates) - len(merged),
        )
    return list(merged.values())


def build_strength_json(model, state, results: LigaResults, store, cfg: LigaConfig) -> dict:
    """
    Power rankings: what the fitted model believes, next to what the table says.

    The Elo and Dixon-Coles parameters here are computed every build and were
    previously discarded after the simulation. The interesting column is rank_delta —
    where a club sits versus where its underlying performance says it should.
    """
    xg = team_xg_map(store)
    rows = build_team_strength(model, state, state.teams, xg_by_match=xg)

    def _elo_factory():
        elo = EloRatings(k_league=ELO_K_LEAGUE, home_advantage=ELO_HOME_ADVANTAGE)
        elo.seed_from_ranking(
            {t: i + 1 for i, t in enumerate(state.teams)}, n_teams=len(state.teams)
        )
        return elo

    trajectories = elo_trajectories(_elo_factory, state, state.teams)

    return {
        "form_window": FORM_WINDOW,
        "rows": [
            {
                "team": r.team, "zone": (state.live_torneo() or state.clausura).zone_of(r.team),
                "elo": r.elo, "attack": r.attack, "defence": r.defence,
                "strength_ppg": r.strength_ppg, "strength_rank": r.strength_rank,
                "table_rank": r.table_rank, "rank_delta": r.rank_delta,
                "played": r.played, "points": r.points, "ppg": r.ppg,
                "form_points": r.form_points, "form_ppg": r.form_ppg,
                "form_gf": r.form_gf, "form_ga": r.form_ga,
                "form_results": r.form_results,
                "xg_for": r.xg_for, "xg_against": r.xg_against, "xg_diff": r.xg_diff,
                "expected_points": r.expected_points, "luck": r.luck,
                "sos_played": r.sos_played, "sos_remaining": r.sos_remaining,
                "sos_delta": r.sos_delta,
            }
            for r in rows
        ],
        "elo_history": trajectories,
        "notes": {
            "strength_ppg": (
                "Puntos por partido esperados contra un rival promedio en cancha "
                "neutral. Al promediar sobre todos los rivales posibles, no depende "
                "del calendario — a diferencia de los puntos por partido reales."
            ),
            "rank_delta": (
                "Posición en la tabla menos posición por fuerza del modelo, dentro de "
                "la misma zona. Positivo significa que el club rinde por debajo de "
                "donde está ubicado."
            ),
            "luck": (
                "Puntos reales menos los que merecía el xG. Sostenido en el tiempo "
                "suele ser varianza de definición, no una habilidad."
            ),
            "sos_delta": (
                "Fuerza media de los rivales que faltan menos la de los ya jugados. "
                "Positivo significa que lo más difícil está por venir."
            ),
        },
        "notes_en": {
            "strength_ppg": (
                "Expected points per game against an average opponent at a neutral "
                "venue. Averaging over every possible opponent removes the schedule, "
                "which real points per game cannot."
            ),
            "rank_delta": (
                "Table position minus the model's strength rank, within the same zone. "
                "Positive means the club is performing below where it sits."
            ),
            "luck": (
                "Actual points minus the points the xG deserved. Sustained over time it "
                "is usually finishing variance, not a skill."
            ),
            "sos_delta": (
                "Mean strength of opponents still to play minus those already played. "
                "Positive means the hard part is still to come."
            ),
        },
        "updated_at": _now(),
    }


def build_history_json(results: LigaResults, keep_store: int = 400, keep_out: int = 60) -> dict:
    """
    Append a snapshot and return the recent tail.

    The World Cup build writes an equivalent file every hour and the front-end never
    reads it, so the chart was never built. Here it is actually consumed.
    """
    store = _read_json(HISTORY_STORE, {"snapshots": []})
    snapshots = store.get("snapshots", [])
    stamp = _now()
    top = sorted(results.p_title.items(), key=lambda kv: -kv[1])[:16]
    snapshot = {
        "ts": stamp,
        "title": {t: round(p, 5) for t, p in top},
        "anual": {
            t: round(p, 5)
            for t, p in sorted(results.p_anual_champion.items(), key=lambda kv: -kv[1])[:16]
        },
        "relegation": {
            t: round(p, 5)
            for t, p in sorted(results.p_relegation_any.items(), key=lambda kv: -kv[1])[:16]
        },
    }
    if not any(s.get("ts") == stamp for s in snapshots):
        snapshots.append(snapshot)
    snapshots = snapshots[-keep_store:]
    HISTORY_STORE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_STORE.write_text(
        json.dumps({"snapshots": snapshots}, ensure_ascii=False), encoding="utf-8"
    )
    return {"snapshots": snapshots[-keep_out:], "updated_at": stamp}


def write_market_odds(markets: dict | None) -> None:
    """
    Market odds, retaining the previous file when a fetch returns nothing.

    Same contract as the World Cup build: a failed fetch flips ok:false and refreshes
    checked_at, but never replaces good data with an empty payload.
    """
    path = DATA_DIR / "market_odds.json"
    if markets:
        _write("market_odds.json", {
            "ok": True, "updated_at": _now(), "checked_at": _now(), **markets,
        })
        return
    prev = _read_json(path, None)
    if prev:
        prev["ok"] = False
        prev["checked_at"] = _now()
        path.write_text(json.dumps(prev, ensure_ascii=False), encoding="utf-8")
        logger.warning("market odds unavailable — retained the previous file, ok=false")
    else:
        _write("market_odds.json", {
            "ok": False, "updated_at": None, "checked_at": _now(), "h2h": {},
        })


def build_market_payload(raw: dict | None, model, results: LigaResults) -> dict | None:
    """
    Turn raw odds into the model-vs-market comparison the tab renders.

    Outrights are optional by design: whether Argentine league futures are quoted at
    all is unverified, so an absent title market yields available:false rather than an
    error, and the tab hides that section instead of showing an empty panel.
    """
    if not raw:
        return None
    h2h = raw.get("h2h") or []
    outrights = raw.get("outrights") or {}

    payload = {}
    if h2h:
        payload["matches"] = build_match_markets(h2h, model)
    payload["outrights"] = build_outright_markets(outrights, results.p_title)
    return payload or None


def fetch_markets_safe(cfg: LigaConfig) -> dict | None:
    """Fetch match odds. Any failure returns None; the build never depends on this."""
    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        logger.info("ODDS_API_KEY not set — skipping market odds")
        return None
    try:
        import asyncio

        from oddsmarkets.sports.world_cup.trading.the_odds_api import TheOddsAPIFetcher
        from oddsmarkets.football.competitions.liga.config import ODDS_API_SPORT

        async def _go():
            async with TheOddsAPIFetcher(api_key) as fetcher:
                return await fetcher.fetch_match_odds(sport=ODDS_API_SPORT)

        rows = asyncio.run(_go())
        if not rows:
            return None
        return {"h2h": rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning("market odds fetch failed: %s", exc)
        return None


# ── main ─────────────────────────────────────────────────────────────────────

LAST_BUILD: dict | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, default=None, help="override simulation count")
    parser.add_argument("--no-market", action="store_true", help="skip the odds fetch")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    cfg = DEFAULT_CONFIG
    if args.sims:
        cfg = LigaConfig(n_sims=args.sims, sim_chunk=min(args.sims, cfg.sim_chunk))

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    store = load_store(STORE_PATH)
    age = store_age_hours(store)
    store_fresh = age is not None and age < STALE_AFTER_HOURS
    synthetic = bool((store.get("meta") or {}).get("synthetic"))
    if synthetic:
        logger.warning(
            "Store is SYNTHETIC (generated by make_liga_sample_store.py). The site will "
            "be labelled as sample data. Replace it with a real fetch before publishing."
        )
    logger.info(
        "store: %d matches, %d with detail, age=%s",
        len(store.get("matches", {})), len(store.get("lineups", {})),
        f"{age:.1f}h" if age is not None else "unknown",
    )
    if not store.get("matches"):
        logger.error(
            "Store is empty. Run scripts/fetch_sofascore_liga.py from a residential "
            "connection and commit docs/liga/data/liga_store.json."
        )
        return 1

    promedios = _read_json(PKG_DATA / "promedios_history.json", {})
    prior = {t: (int(v.get("points", 0)), int(v.get("matches", 0)))
             for t, v in promedios.items()}
    meta_extra = _read_json(PKG_DATA / "season_meta.json", {})

    state = season_state_from_store(
        store, cfg,
        promedios_prior=prior,
        apertura_champion=meta_extra.get("apertura_champion"),
        clausura_champion=meta_extra.get("clausura_champion"),
    )
    logger.info(state.summary())

    train_df = training_frame(store)
    logger.info("training frame: %d matches", len(train_df))
    model, cal = build_model(train_df, state.teams, meta_extra.get("previous_anual_rank"))

    if state.live_torneo() is None:
        logger.error("Season is complete — nothing to simulate")
        return 1

    candidates = build_boot_candidates(store, None)
    boot = GoldenBootModel(candidates, seed=cfg.random_seed) if candidates else None
    if boot is None:
        logger.warning("No scorer candidates in the store — skipping the top-scorer race")

    results = LigaSimulator(
        model, state, cfg=cfg, seed=args.seed, boot_model=boot
    ).run()
    boot_probs = boot.probabilities(results.n_sims) if boot else {}

    _write("teams.json", build_teams_json(state, results, store))
    _write("zones.json", build_zones_json(state, results, cfg))
    _write("bracket.json", build_bracket_json(state, results, cfg))
    _write("anual.json", build_anual_json(state, results, cfg))
    _write("relegation.json", build_relegation_json(state, results, cfg))
    _write("probs.json", build_probs_json(state, results))
    _write("history.json", build_history_json(results))
    _write("strength.json", build_strength_json(model, state, results, store, cfg))

    live_players, leaders = build_players_json(store, results, boot_probs, candidates)
    _write("players_live.json", live_players)
    _write("player_leaders.json", leaders)
    _write("shots.json", {"players": shots_by_player(store)})
    _write("match_detail.json", {"matches": match_details(store)})

    raw_markets = None if args.no_market else fetch_markets_safe(cfg)
    write_market_odds(build_market_payload(raw_markets, model, results))

    torneo = state.live_torneo()
    last_date = max(
        (m.date for m in torneo.finished if m.date), default=None
    )
    season_stale = bool(
        last_date and (datetime.now(timezone.utc) - last_date).days > SEASON_STALE_DAYS
    )
    if season_stale:
        logger.warning(
            "Most recent finished match is %s — the configured season id may be stale.",
            last_date.date(),
        )

    _write("meta.json", {
        "updated_at": _now(),
        "n_sims": results.n_sims,
        "runtime_s": round(results.runtime_s, 2),
        "phase": torneo.key,
        "games_played": torneo.games_played,
        "games_total": torneo.total_league_games,
        "league_complete": torneo.league_complete,
        "apertura_champion": state.apertura.champion,
        "store_fresh": store_fresh,
        "synthetic": synthetic,
        "store_age_hours": round(age, 1) if age is not None else None,
        "season_stale": season_stale,
        "training_matches": len(train_df),
        "calibration": cal,
        "model": {
            "elo_home_advantage": ELO_HOME_ADVANTAGE,
            "elo_k_league": ELO_K_LEAGUE,
            "dc_weight": DC_WEIGHT if model.dc.is_fitted else 0.0,
            "dc_xi": DC_XI,
            "dc_ridge": DC_RIDGE,
            "dc_fitted": model.dc.is_fitted,
            "params_method": MODEL_PARAMS_METHOD,
        },
        "source": "Sofascore",
    })

    # The combined site's build reuses the fitted model and the store for the
    # fixtures, player and team analytics payloads it adds on top of these.
    global LAST_BUILD
    LAST_BUILD = {"model": model, "state": state, "store": store, "cfg": cfg, "results": results}
    logger.info("Build complete in %.1fs of simulation", results.runtime_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
