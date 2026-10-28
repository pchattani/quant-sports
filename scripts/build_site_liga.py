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
from oddsmarkets.football.competitions.liga import tables as liga_tables  # noqa: E402
from oddsmarkets.football.analytics import race as _race  # noqa: E402
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
# Argentina's store, with every other competition's (liga/store.py store_path; the old docs/liga copy before).
from oddsmarkets.football.competitions.liga.store import store_path as _store_path  # noqa: E402
STORE_PATH = _store_path()
HISTORY_STORE = DATA_DIR / "history_store.json"
PKG_DATA = ROOT / "oddsmarkets" / "football" / "competitions" / "liga" / "data"
# Past league seasons (the archive fetcher's results store): the promedio history before this season.
PAST_STORE = ROOT / "docs" / "site" / "data" / "past" / "store.json"
# The Copa Argentina's simulated winners ({club: p}), set by build_site_all from this run's cup build (the cups
# are built before Argentina). None: the cup's last bracket.json, else the berth is left to the table.
COPA_DIST: dict | None = None
COPA_BRACKET = ROOT / "docs" / "site" / "data" / "copa-argentina" / "bracket.json"

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

    from oddsmarkets.football.competitions.league import fitting
    dc = fitting.new_dc(DC_XI, DC_RIDGE)
    if train_df is not None and len(train_df) >= 50:
        try:
            # Market-implied rates of past matches (oddsmarkets/football/sources/market_rates.py):
            # extra Dixon-Coles rows only; a no-op without the football-data files. The same
            # frame and fit as the tuner (league/fitting.py).
            fit_df = fitting.dc_frame(train_df, "liga-argentina", DC_XI, market=not os.environ.get("NO_MARKET_RATES"))
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
        "matches_per_team": cfg.matches_per_team_per_torneo,
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


def table_places(cfg: LigaConfig) -> tuple[int, int]:
    """The Tabla Anual places that guarantee a berth whatever the champions do: (Libertadores through the table,
    last place that guarantees at least the Sudamericana). Six Libertadores places less the three automatic
    ones (Apertura and Clausura champions, Copa Argentina winner) leave at least three to the table; a champion
    already in them passes its place down, never up. Twelve continental places less at most three automatic ones
    leave at least nine."""
    lib = max(cfg.libertadores_berths - 3, 0)
    return lib, lib + cfg.sudamericana_berths


BERTH_LABELS = {
    "lib_auto": "Libertadores: a champion",
    "lib": "Libertadores",
    "lib_open": "Libertadores if an open title goes to a club already in, else Sudamericana",
    "sud": "Sudamericana",
    "sud_open": "Sudamericana if an open title goes to a club already in",
    "down_anual": "Relegated: last in the Tabla Anual",
    "down_promedio": "Relegated: the worst promedio",
}


def berths_now(state, cfg: LigaConfig, order: list[str], copa_winner: str | None) -> tuple[dict[str, str], dict]:
    """
    Where each club stands if the season ended today, with the actual berth counts: six Libertadores places, the
    Apertura and Clausura champions and the Copa Argentina winner first (a title still to be decided holds a place
    open), the rest down the Tabla Anual, then six Sudamericana places for the next clubs not already in; and the
    two relegations, the worst promedio and the last club in the Tabla Anual (the next-worst promedio when they are
    the same club). Returns ({club: status}, summary). Statuses: BERTH_LABELS.
    """
    teams = set(order)
    autos: list[tuple[str, str]] = []
    for team, why in ((state.apertura.champion, "Apertura champion"), (state.clausura.champion, "Clausura champion"),
                      (copa_winner, "Copa Argentina winner")):
        if team and team not in [a for a, _ in autos]:
            autos.append((team, why))
    open_titles = (0 if state.clausura.champion else 1) + (0 if copa_winner else 1)
    lib_left = max(cfg.libertadores_berths - len(autos) - open_titles, 0)
    sud_sure = max(cfg.sudamericana_berths - open_titles, 0)
    status: dict[str, str] = {t: "lib_auto" for t, _ in autos if t in teams}
    rest = [t for t in order if t not in status]
    plan = ["lib"] * lib_left + ["lib_open"] * open_titles + ["sud"] * sud_sure + ["sud_open"] * open_titles
    for team, st in zip(rest, plan):
        status[team] = st
    prom = state.promedio_now()
    worst = sorted(prom, key=lambda t: (prom[t], t))
    last = order[-1] if order else None
    if worst:
        down_p = worst[0] if worst[0] != last else (worst[1] if len(worst) > 1 else None)
        if last:
            status[last] = "down_anual"
        if down_p:
            status[down_p] = "down_promedio"
    summary = {"autos": [{"team": t, "why": w} for t, w in autos], "open_titles": open_titles,
               "table_libertadores": lib_left, "labels": BERTH_LABELS}
    return status, summary


def build_anual_json(state, results: LigaResults, cfg: LigaConfig, store: dict | None = None,
                     copa: dict | None = None) -> dict:
    """
    The Tabla Anual as it stands (the finished Apertura plus the Clausura so far, zone phases only), in the
    AFA's order, with where our simulations finish each club. Until October 2026 the table showed only the
    tournaments the simulator held as finished, and eight dead Apertura fixtures kept that empty: every club
    on 0 points.
    """
    now = state.anual_standings()
    by_torneo = {key: state.torneo(key).records() for key in (APERTURA, CLAUSURA)}
    proj = sorted(state.teams, key=lambda t: -results.expected_anual_points.get(t, 0.0))
    proj_pos = {t: i for i, t in enumerate(proj, start=1)}
    torneo = state.live_torneo() or state.clausura
    rows = []
    for pos, (team, rec) in enumerate(now, start=1):
        rows.append({
            "pos": pos, "team": team, "zone": torneo.zone_of(team),
            "played": rec.played, "w": rec.won, "d": rec.drawn, "l": rec.lost,
            "gf": rec.gf, "ga": rec.ga, "gd": rec.gd, "pts": rec.points,
            "pts_now": rec.points,
            "apertura_pts": by_torneo[APERTURA].get(team).points if by_torneo[APERTURA].get(team) else 0,
            "clausura_pts": by_torneo[CLAUSURA].get(team).points if by_torneo[CLAUSURA].get(team) else 0,
            "exp_pts": round(results.expected_anual_points.get(team, 0.0), 2),
            "proj_pos": proj_pos.get(team),
            "p_champion": round(results.p_anual_champion.get(team, 0.0), 5),
            "p_libertadores": round(results.p_libertadores.get(team, 0.0), 5),
            "p_sudamericana": round(results.p_sudamericana.get(team, 0.0), 5),
            "p_last": round(results.p_anual_position.get(team, [0.0])[-1], 5),
            # Full finishing distribution, for the position heatmap.
            "p_pos": [round(p, 5) for p in results.p_anual_position.get(team, [])],
        })
    lib_table, sud_last = table_places(cfg)
    copa_winner = cfg.copa_argentina_winner or (copa or {}).get("winner")
    status, now_summary = berths_now(state, cfg, [t for t, _ in now], copa_winner)
    for r in rows:
        r["berth_now"] = status.get(r["team"])
    official = liga_tables.official_table(store or {}, "anual")
    check = liga_tables.compare(now, official)
    if check is not None:
        check.update({k: v for k, v in liga_tables.official_meta(store or {}).items() if k != "blocks"})
    return {
        "rows": rows,
        "matches_per_team": cfg.matches_per_team_per_torneo * 2,
        "games_played": sum(r.played for _, r in now) // 2,
        "total_games": cfg.matches_per_torneo * 2,
        "tiebreak": ["pts", "gd", "gf"],
        "berths": {
            "libertadores": cfg.libertadores_berths,
            "sudamericana": cfg.sudamericana_berths,
            "table_libertadores": lib_table,
            "table_sudamericana_last": sud_last,
            "apertura_champion": state.apertura.champion,
            "clausura_champion": state.clausura.champion,
            "copa_argentina_winner": cfg.copa_argentina_winner or (copa or {}).get("winner"),
            "copa_argentina": copa or None,
            "now": now_summary,
            "note": (
                "Los campeones del Apertura, del Clausura y de la Copa Argentina "
                "clasifican directo a la Libertadores; los cupos restantes salen de "
                "esta tabla, y los seis siguientes van a la Sudamericana. Mientras la "
                "Copa Argentina se juega, su campeón sale de nuestras simulaciones de la copa."
            ),
            "note_en": (
                "The Apertura, Clausura and Copa Argentina champions qualify directly for the Libertadores; "
                "the remaining places go down this table, and the next six clubs not already in go to the "
                "Sudamericana. A champion already high in the table passes its place down, so the top "
                + str(lib_table) + " are always in the Libertadores and the top " + str(sud_last) + " always "
                "in one of the two. While the Copa Argentina is being played, its winner is drawn in every "
                "simulated season from our simulations of the cup."
            ),
        },
        "official": check,
        "updated_at": _now(),
    }


def build_relegation_json(state, results: LigaResults, cfg: LigaConfig, prior_info: dict | None = None,
                          store: dict | None = None) -> dict:
    promedios = state.promedio_now()
    now = state.anual_now()
    rows = []
    for team in state.teams:
        prior_pts, prior_mp = state.promedios_prior.get(team, (0, 0))
        q = results.promedio_quantiles.get(team, (0.0, 0.0, 0.0))
        rec = now.get(team)
        rows.append({
            "team": team,
            "promedio_now": round(promedios.get(team, 0.0), 4),
            "points": prior_pts + (rec.points if rec else 0),
            "matches": prior_mp + (rec.played if rec else 0),
            "season_points": rec.points if rec else 0,
            "season_matches": rec.played if rec else 0,
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
    # Sofascore's promedios table beside ours (same order: worst first), when the store holds it.
    official = liga_tables.official_table(store or {}, "promedios")
    check = None
    if official:
        diffs = []
        for r in rows:
            o = official.get(r["team"])
            if not o or o.get("points") != r["points"] or o.get("matches") != r["matches"]:
                diffs.append({"team": r["team"], "ours": [r["points"], r["matches"]],
                              "official": [o.get("points"), o.get("matches")] if o else None})
        check = {"clubs": len(rows), "same": len(rows) - len(diffs), "diffs": diffs[:30],
                 **{k: v for k, v in liga_tables.official_meta(store or {}).items() if k != "blocks"}}
    return {
        "rows": rows,
        "prior": prior_info or {},
        "official": check,
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


RACE_SEASON = "2026-anual"     # the daily race log's key; a new key starts it afresh (October 2026 fix)


def race_bands(cfg: LigaConfig) -> list[dict]:
    """The Race tab's bands on the Tabla Anual (docs/site/assets/app/race.js): the places that guarantee a
    Libertadores or at least a Sudamericana berth, and last place, which goes down. The probabilities behind
    them are the berths and relegation by every route (the champions, the cup, the promedio)."""
    lib, sud_last = table_places(cfg)
    n = cfg.n_teams
    return [
        {"key": "libertadores", "label": "Libertadores", "first": 1, "last": lib, "kind": "up",
         "phrase": "reach the Libertadores"},
        {"key": "continental", "label": "Libertadores or Sudamericana", "first": 1, "last": sud_last, "kind": "up",
         "phrase": "reach the Libertadores or the Sudamericana"},
        {"key": "relegation", "label": "Relegation", "first": n, "last": n, "kind": "down", "phrase": "go down"},
    ]


def _band_probs(results: LigaResults, team: str) -> dict:
    return {
        "libertadores": round(results.p_libertadores.get(team, 0.0), 5),
        "sudamericana": round(results.p_sudamericana.get(team, 0.0), 5),
        "continental": round(results.p_libertadores.get(team, 0.0) + results.p_sudamericana.get(team, 0.0), 5),
        "relegation": round(results.p_relegation_any.get(team, 0.0), 5),
        "top8": round(results.p_top8.get(team, 0.0), 5),
    }


def build_stakes(results: LigaResults) -> list[dict]:
    """probs.json "stakes" in the leagues' shape (analytics/race.py stakes_payload), the title being the top of
    the Tabla Anual and "top8" a place in this tournament's playoffs."""
    from types import SimpleNamespace

    bands = [SimpleNamespace(key="libertadores", label="Libertadores", kind="up"),
             SimpleNamespace(key="sudamericana", label="Sudamericana", kind="up"),
             SimpleNamespace(key="relegation", label="Relegation", kind="down"),
             SimpleNamespace(key="top8", label="Playoff place", kind="up")]
    out = _race.stakes_payload(results, SimpleNamespace(bands=bands))
    for s in out:
        for m in s.get("m") or []:
            if m.get("key") == "title":
                m["label"] = "Top of the Tabla Anual"
    return out


def build_table_json(state, results: LigaResults, cfg: LigaConfig, anual: dict) -> dict:
    """table.json in the leagues' shape, on the Tabla Anual, for the shared Race tab: the standings with the
    berth and relegation chances as bands, the points arithmetic over the 32 zone matches a club plays a year,
    and the title as the top of the Tabla Anual (`title_key`). The zone tables stay in zones.json."""
    rows = []
    for r in anual["rows"]:
        rows.append({
            "pos": r["pos"], "team": r["team"], "zone": r.get("zone"),
            "played": r["played"], "w": r["w"], "d": r["d"], "l": r["l"],
            "gf": r["gf"], "ga": r["ga"], "gd": r["gd"], "pts": r["pts"],
            "exp_pts": r["exp_pts"], "p_title": r["p_champion"], "p_pos": r["p_pos"],
            "bands": _band_probs(results, r["team"]),
        })
    return {
        "season": f"{cfg.season_year}",
        "view": "anual",
        "label": "Tabla Anual",
        "title_key": "p_anual",
        "title_label": "Top of the Tabla Anual",
        "title_short": "Top",
        "title_phrase": "top the Tabla Anual",
        "title_kpi": "Favourite to top it",
        "title_tier": "Tabla Anual contenders",
        "safety_label": "Clear of last place",
        "hist_keys": {"title": "anual", "band": "libertadores", "relegation": "relegation"},
        "exp_key": "exp_anual_pts",
        "down_places": cfg.relegation_places,
        "bands": race_bands(cfg),
        "tiebreak": ["pts", "gd", "gf"],
        "h2h_tiebreak": False,
        "games_played": anual["games_played"],
        "total_games": anual["total_games"],
        "matches_per_team": anual["matches_per_team"],
        "standings": rows,
        "updated_at": _now(),
    }


def build_probs_json(state, results: LigaResults, cfg: LigaConfig | None = None) -> dict:
    cfg = cfg or DEFAULT_CONFIG
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
            "exp_anual_pts": round(results.expected_anual_points.get(team, 0.0), 2),
            "bands": _band_probs(results, team),
        })
    teams.sort(key=lambda t: -t["p_title"])
    out = {"teams": teams, "bands": race_bands(cfg), "has_playoff": True, "updated_at": _now()}
    stakes = build_stakes(results)
    if stakes:
        out["stakes"] = stakes
    return out


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


def build_strength_json(model, state, results: LigaResults, store, cfg: LigaConfig,
                        prev_rank: dict[str, int] | None = None) -> dict:
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
        # Seeded like the model's Elo: last year's Tabla Anual (the team list's alphabetical order before
        # October 2026, which put Aldosivi top of every trajectory's starting line).
        elo.seed_from_ranking(
            prev_rank or {t: i + 1 for i, t in enumerate(state.teams)}, n_teams=len(state.teams)
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
    # Runs before the October 2026 fix computed the Tabla Anual without the Apertura: their anual and
    # relegation series are dropped (the Clausura title line is kept).
    for snap in snapshots:
        if isinstance(snap, dict) and not snap.get("v"):
            snap.pop("anual", None)
            snap.pop("relegation", None)
    stamp = _now()
    top = sorted(results.p_title.items(), key=lambda kv: -kv[1])[:16]
    snapshot = {
        "ts": stamp,
        "v": 2,
        "libertadores": {
            t: round(p, 5)
            for t, p in sorted(results.p_libertadores.items(), key=lambda kv: -kv[1])[:16]
        },
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
    # The Race tab's daily log (analytics/race.py roll_daily), on the Tabla Anual: its top, the Libertadores
    # and relegation by either route, one entry a day for the season.
    race_snaps = [
        {"ts": x.get("ts"), "title": x.get("anual"), "band": x.get("libertadores"), "band_key": "libertadores",
         "relegation": x.get("relegation")}
        for x in snapshots if isinstance(x, dict) and x.get("v")
    ]
    daily = _race.roll_daily(store.get("daily"), race_snaps, RACE_SEASON, results.teams)
    HISTORY_STORE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_STORE.write_text(
        json.dumps({"snapshots": snapshots, "daily": daily}, ensure_ascii=False), encoding="utf-8"
    )
    return {"snapshots": snapshots[-keep_out:], "daily": daily["days"], "updated_at": stamp}


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

    # The promedio history before this season: a committed promedios_history.json when there is one (the old
    # backfill job's output; never produced), else Sofascore's promedios table in the store, else our past
    # results (liga/tables.py says which, and the relegation payload carries it).
    meta_extra = _read_json(PKG_DATA / "season_meta.json", {})
    promedios = _read_json(PKG_DATA / "promedios_history.json", {})
    if promedios:
        prior = {t: (int(v.get("points", 0)), int(v.get("matches", 0))) for t, v in promedios.items()}
        prior_info = {"source": "file", "note": "Promedio history from promedios_history.json."}
    else:
        past = ((_read_json(PAST_STORE, {}) or {}).get("seasons") or {}).get("liga-argentina") or {}
        prior, prior_info = liga_tables.promedio_prior(store, past, cfg.season_year, cfg.promedio_seasons)
    logger.info("promedio history: %s, %d clubs", prior_info.get("source"), len(prior))

    # Champions: a played final in the store names them (liga/store.py champion_from_final); the meta file
    # only fills a gap.
    state = season_state_from_store(
        store, cfg,
        promedios_prior=prior,
        apertura_champion=meta_extra.get("apertura_champion"),
        clausura_champion=meta_extra.get("clausura_champion"),
    )
    logger.info(state.summary())

    # The Copa Argentina winner: this run's cup simulation, else the cup's last published bracket.
    copa_dist = COPA_DIST
    if copa_dist is None:
        copa_dist = ((_read_json(COPA_BRACKET, {}) or {}).get("p_cup")) or None
    copa_info = None
    if copa_dist:
        known = [t for t, p in copa_dist.items() if p >= 0.9999]
        unmatched = [t for t in copa_dist if t not in state.teams and copa_dist[t] > 0.001]
        copa_info = {"winner": known[0] if known else None, "source": "copa-argentina simulation",
                     "outside_league": round(sum(copa_dist[t] for t in unmatched), 4)}
        logger.info("Copa Argentina winner: %s; outside the league %.3f (%s)",
                    known[0] if known else "drawn per simulation", copa_info["outside_league"], unmatched[:6])

    train_df = training_frame(store)
    logger.info("training frame: %d matches", len(train_df))
    # The Elo seed: last year's Tabla Anual, from the past results when the meta file has none. With every club
    # in the Dixon-Coles fit the ensemble's Elo weight is 0, so the seed moves only the Elo shown on the Power tab.
    prev_rank = meta_extra.get("previous_anual_rank")
    if not prev_rank:
        past_all = ((_read_json(PAST_STORE, {}) or {}).get("seasons") or {}).get("liga-argentina") or {}
        prev_rank = liga_tables.previous_rank(past_all, store, state.teams, cfg.season_year) or None
    model, cal = build_model(train_df, state.teams, prev_rank)

    if state.live_torneo() is None:
        logger.error("Season is complete — nothing to simulate")
        return 1

    candidates = build_boot_candidates(store, None)
    boot = GoldenBootModel(candidates, seed=cfg.random_seed) if candidates else None
    if boot is None:
        logger.warning("No scorer candidates in the store — skipping the top-scorer race")

    results = LigaSimulator(
        model, state, cfg=cfg, seed=args.seed, boot_model=boot, copa_dist=copa_dist
    ).run()
    if copa_info is not None and results.copa_winner_share:
        copa_info["drawn"] = {t: round(p, 4) for t, p in sorted(results.copa_winner_share.items(), key=lambda kv: -kv[1])[:8]}
    boot_probs = boot.probabilities(results.n_sims) if boot else {}

    _write("teams.json", build_teams_json(state, results, store))
    _write("zones.json", build_zones_json(state, results, cfg))
    _write("bracket.json", build_bracket_json(state, results, cfg))
    anual = build_anual_json(state, results, cfg, store, copa_info)
    _write("anual.json", anual)
    _write("table.json", build_table_json(state, results, cfg, anual))
    _write("relegation.json", build_relegation_json(state, results, cfg, prior_info, store))
    _write("probs.json", build_probs_json(state, results, cfg))
    _write("history.json", build_history_json(results))
    _write("strength.json", build_strength_json(model, state, results, store, cfg, prev_rank))

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
        "clausura_champion": state.clausura.champion,
        "anual_games_played": anual["games_played"],
        "anual_games_total": anual["total_games"],
        "promedio_history": prior_info.get("source"),
        "official_check": {
            "anual": (anual.get("official") or {}).get("same_position"),
            "clubs": len(state.teams),
            "at": (store.get("standings") or {}).get("at"),
        } if anual.get("official") else None,
        "copa_argentina": copa_info,
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
