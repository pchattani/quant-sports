"""
The site payloads of a torneo league (Colombia, Uruguay, Peru): the stage tables, the aggregate table, the
relegation table, the playoff picture and the chances, in the shapes the front-end already reads for the plain
leagues (table.json, probs.json, bracket.json) and for Argentina (anual.json, relegation.json).
"""
from __future__ import annotations

from datetime import datetime, timezone

from oddsmarkets.football.competitions.league.config import LeagueConfig
from oddsmarkets.football.competitions.league.torneo import SEASON, TorneoResults, TorneoState

BERTH_LABELS = {
    "lib_auto": "Libertadores: a champion",
    "lib": "Libertadores",
    "lib_open": "Libertadores if an open title goes to a club already in, else Sudamericana",
    "sud": "Sudamericana",
    "sud_open": "Sudamericana if an open title or cup goes to a club already in",
    "down_anual": "Relegated: in the bottom places of the table",
    "down_promedio": "Relegated: in the bottom places of the promedio",
}
PHASE_ROUNDS = {
    "knockout8": (("qf", "Quarter-final"), ("sf", "Semi-final"), ("final", "Final")),
    "groups8": (("groups", "Cuadrangulares"), ("final", "Final")),
    "group_final": (("final", "Final"),),
    "table": (),
}
SEASON_ROUNDS = {
    "uruguay": (("sf", "Semi-final"), ("final", "Final")),
    "peru": (("sf", "Semi-final"), ("final", "Final")),
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(state: TorneoState, stage: str | None = None, aggregate: bool = False) -> list[dict]:
    out = []
    for pos, (team, rec, pts) in enumerate(state.standings(stage, aggregate), start=1):
        out.append({"pos": pos, "team": team, "tid": state.team_ids.get(team), "played": rec.played, "w": rec.won,
                    "d": rec.drawn, "l": rec.lost, "gf": rec.gf, "ga": rec.ga, "gd": rec.gd, "pts": pts})
    return out


def _fixture_rows(matches) -> list[dict]:
    return [{"round": m.round, "home": m.home, "away": m.away, "hg": m.hg, "ag": m.ag,
             "date": m.date.strftime("%Y-%m-%d") if m.date else None, "done": m.done, "stage": m.stage, "id": m.game_id}
            for m in sorted(matches, key=lambda x: (x.date is None, x.date.timestamp() if x.date else 0.0, x.game_id))]


def stage_status(s) -> str:
    return "done" if s.closed else ("live" if s.started else "upcoming")


def format_lines(cfg: LeagueConfig) -> list[str]:
    """The format in a few plain sentences, for the methodology tab."""
    fmt = cfg.torneo
    out = []
    phase_text = {
        "table": "won by the first in the table",
        "knockout8": "a round robin, then the top 8 in two-legged quarter-finals, semi-finals and a final",
        "groups8": ("a round robin, then the top 8 in two groups of four (1st and 2nd head them) played home and "
                    "away, and the group winners in a two-legged final"),
        "group_final": "two groups seeded from the Apertura, each a single round robin, and a one-match final",
    }
    for s in fmt.stages:
        out.append(f"{s.label}: {phase_text[s.final_phase]}.")
    if fmt.champion == "uruguay":
        out.append("The Apertura and Clausura winners meet in a semi-final; its winner plays the Tabla Anual leader "
                   "over two legs. A club that wins both stages, or leads the Anual and wins the semi-final, is "
                   "champion outright.")
    elif fmt.champion == "peru":
        out.append("The Apertura and Clausura winners (when in the Acumulada top 8) and the Acumulada's top two "
                   "play two-legged semi-finals and a final; a club that wins both stages is champion.")
    else:
        out.append("Each stage crowns its own champion.")
    agg = "every match, the playoffs included" if fmt.aggregate_matches == "all" else "the stages' round robins"
    out.append(f"The {fmt.aggregate_label} adds up {agg}; it decides the continental places after the champions.")
    if fmt.relegation_by == "promedio":
        out.append(f"The bottom {fmt.relegation_places} of the promedio go down: points per match over "
                   f"{fmt.promedio_years} seasons, a club promoted since averaging over its own seasons.")
    else:
        out.append(f"The bottom {fmt.relegation_places} of the {fmt.aggregate_label} go down.")
    if cfg.berth_note:
        out.append(cfg.berth_note)
    return out


def build_table_json(state: TorneoState, res: TorneoResults, cfg: LeagueConfig) -> dict:
    """The current stage's table with our chances (the shape of a plain league's table.json), and every stage's
    table as it stands under `stages`."""
    cur = state.current
    stage_p = res.p_stage.get(cur.key, {})
    rows = []
    for r in _rows(state, cur.key):
        team = r["team"]
        q = res.points_quantiles.get(team, (0.0, 0.0, 0.0))
        rows.append({**r, "exp_pts": round(res.expected_points.get(team, 0.0), 2),
                     "p05": round(q[0], 1), "p50": round(q[1], 1), "p95": round(q[2], 1),
                     "p_title": round(stage_p.get(team, 0.0), 5),
                     "p_pos": [round(p, 5) for p in res.p_position.get(team, [])],
                     "bands": {b.key: round(res.p_in_band(b.key, team), 5) for b in cfg.bands}})
    stages = []
    for s in state.stages:
        entry = {
            "key": s.key, "label": s.fmt.label, "phase": s.fmt.final_phase, "status": stage_status(s),
            "champion": s.champion, "games_played": len(s.regular_done),
            "total_games": len(s.regular_done) + len(s.regular_left) + len(s.regular_missing),
            "p_champion": {t: round(p, 5) for t, p in sorted(res.p_stage.get(s.key, {}).items(), key=lambda kv: -kv[1])
                           if p > 0.0005},
        }
        if s.fmt.final_phase == "group_final":
            seed = state.stage(s.fmt.seed_from or "")
            order = [t for t, _r, _p in state.standings(seed.key)] if seed is not None else list(state.teams)
            a = {order[p - 1] for p in s.fmt.group_a if p - 1 < len(order)}
            table = _rows(state, s.key)
            groups = {"A": [r for r in table if r["team"] in a], "B": [r for r in table if r["team"] not in a]}
            for g in groups.values():
                for i, r in enumerate(g, start=1):
                    r["pos"] = i
            entry["groups"] = groups
        else:
            entry["standings"] = _rows(state, s.key) if s.scheduled else []
        stages.append(entry)
    left = cur.regular_left
    return {
        "season": state.season_name,
        "stage": {"key": cur.key, "label": cur.fmt.label, "phase": cur.fmt.final_phase, "status": stage_status(cur)},
        "stages": stages,
        "bands": [{"key": b.key, "label": b.label, "first": b.first, "last": b.last, "kind": b.kind} for b in cfg.bands],
        "tiebreak": list(cfg.tiebreak),
        "h2h_tiebreak": cfg.h2h_tiebreak,
        "standings": rows,
        "fixtures": _fixture_rows(cur.regular_done + left),
        "games_played": len(cur.regular_done),
        "total_games": len(cur.regular_done) + len(left) + len(cur.regular_missing),
        "unlisted_fixtures": len(cur.regular_missing),
        "matches_per_team": len(state.teams) - 1 if cur.fmt.final_phase != "group_final" else None,
        "torneo": {"aggregate_label": cfg.torneo.aggregate_label, "champion_rule": cfg.torneo.champion,
                   "relegation_by": cfg.torneo.relegation_by, "format": format_lines(cfg)},
        "adjustments": [{"stage": st, "team": t, "points": p} for st, t, p in cfg.point_adjustments],
        "unlisted_results": [{"stage": st, "home": h, "away": a, "score": [hg, ag]} for st, h, a, hg, ag in cfg.unlisted_results],
        "updated_at": _now(),
    }


def berths_now(state: TorneoState, cfg: LeagueConfig, order: list[str], promedio: dict[str, float],
               cup_winner: str | None = None) -> tuple[dict[str, str], dict]:
    """Where each club stands if the season ended today: {club: status} (BERTH_LABELS) and a summary."""
    fmt = cfg.torneo
    status: dict[str, str] = {}
    n = fmt.relegation_places
    if fmt.relegation_by == "promedio":
        worst = sorted(promedio, key=lambda t: (promedio[t], t))[:n]
        for t in worst:
            status[t] = "down_promedio"
    else:
        for t in order[-n:]:
            status[t] = "down_anual"
    autos: list[tuple[str, str]] = []
    open_titles = 0
    if fmt.berths == "colombia":
        for s in state.stages:
            if s.champion:
                if s.champion not in [a for a, _ in autos]:
                    autos.append((s.champion, f"{s.fmt.label} champion"))
            else:
                open_titles += 1
        cup_open = 0 if cup_winner else 1
    elif fmt.berths == "uruguay":
        if state.champion:
            autos.append((state.champion, "champion"))
        else:
            open_titles = 2          # the champion and the runner-up come from the playoffs
        cup_open = 1                 # the Copa AUF Uruguay's place (not in the data) goes down the table
    else:                            # peru: the playoff clubs take places 1-4
        if state.champion:
            autos.append((state.champion, "champion"))
        else:
            a, c = state.stage("apertura"), state.stage("clausura")
            top8 = order[:8]
            for s in (a, c):
                if s is not None and s.champion and s.champion in top8 and s.champion not in [x for x, _ in autos]:
                    autos.append((s.champion, f"{s.fmt.label} winner, in the playoffs"))
        cup_open = 0
    lib_left = max(fmt.libertadores - len(autos) - open_titles, 0)
    sud_sure = max(fmt.sudamericana - open_titles - (cup_open if fmt.berths == "colombia" else 0), 0)
    for t, _why in autos:
        if t not in status:
            status[t] = "lib_auto"
    rest = [t for t in order if t not in status]
    plan = ["lib"] * lib_left + ["lib_open"] * open_titles + ["sud"] * sud_sure + \
        ["sud_open"] * (open_titles + (cup_open if fmt.berths == "colombia" else 0))
    for team, st in zip(rest, plan):
        status[team] = st
    summary = {"autos": [{"team": t, "why": w} for t, w in autos], "open_titles": open_titles,
               "table_libertadores": lib_left, "labels": BERTH_LABELS}
    return status, summary


def build_anual_json(state: TorneoState, res: TorneoResults, cfg: LeagueConfig, cup_winner: str | None = None) -> dict:
    """The aggregate table as it stands (Argentina's anual.json shape), with our chances."""
    fmt = cfg.torneo
    now = _rows(state, aggregate=True)
    order = [r["team"] for r in now]
    status, summary = berths_now(state, cfg, order, state.promedio_now() if fmt.relegation_by == "promedio" else {}, cup_winner)
    by_stage = {s.key: state.records(s.key) for s in state.stages}
    rows = []
    for r in now:
        t = r["team"]
        q = res.agg_points_quantiles.get(t, (0.0, 0.0, 0.0))
        dist = res.p_agg_position.get(t, [])
        rows.append({**r, "pts_now": r["pts"], **{f"{k}_pts": rec[t].points for k, rec in by_stage.items() if t in rec},
                     "exp_pts": round(res.agg_expected_points.get(t, 0.0), 2), "p05": round(q[0], 1), "p95": round(q[2], 1),
                     "p_champion": round(dist[0] if dist else 0.0, 5),
                     "p_libertadores": round(res.p_libertadores.get(t, 0.0), 5),
                     "p_sudamericana": round(res.p_sudamericana.get(t, 0.0), 5),
                     "p_relegation": round(res.p_relegation.get(t, 0.0), 5),
                     "p_pos": [round(p, 5) for p in dist], "berth_now": status.get(t)})
    notes = {
        "colombia": ("Libertadores: the Apertura and Finalización champions, then the best two other clubs of the "
                     "reclasificación (a double champion's place passes down). Sudamericana: the Copa BetPlay "
                     "champion, then the best clubs not already in. A relegated club takes no place. Reglamento "
                     "Liga BetPlay DIMAYOR 2026, Arts. 30-31."),
        "uruguay": ("Libertadores: the champion and the runner-up, then the best club of the Tabla Anual not already "
                    "in, and the Copa AUF Uruguay champion (a cup not in our data: its place is given to the next "
                    "club of the Anual). Sudamericana: the next four of the Anual. No AUF reglamento for 2026 was "
                    "found; this follows the 2026 season articles and the 2025 practice."),
        "peru": ("Libertadores: the final places 1-4 (the champion, the runner-up and the two losing "
                 "semi-finalists by the Acumulada); Sudamericana: places 5-8 (Reglamento Liga1 2026, Art. 9)."),
    }
    return {
        "label": fmt.aggregate_label,
        "rows": rows,
        "games_played": sum(r["played"] for r in now) // 2,
        "tiebreak": list(cfg.tiebreak),
        "berths": {"libertadores": fmt.libertadores, "sudamericana": fmt.sudamericana,
                   "relegated": fmt.relegation_places, "relegation_by": fmt.relegation_by,
                   "now": summary, "note_en": notes[fmt.berths],
                   "stage_champions": {s.key: s.champion for s in state.stages}},
        "updated_at": _now(),
    }


def build_relegation_json(state: TorneoState, res: TorneoResults, cfg: LeagueConfig) -> dict:
    fmt = cfg.torneo
    rows = []
    if fmt.relegation_by == "promedio":
        prom = state.promedio_now()
        season = {t: [0, 0] for t in state.teams}
        for s in state.stages:
            for m in s.regular_done:
                for t, gf, ga in ((m.home, m.hg, m.ag), (m.away, m.ag, m.hg)):
                    if t in season:
                        season[t][0] += 3 if gf > ga else 1 if gf == ga else 0
                        season[t][1] += 1
        for t in state.teams:
            pp, pm = state.promedio_prior.get(t, (0, 0))
            q = res.promedio_quantiles.get(t, (0.0, 0.0, 0.0))
            rows.append({"team": t, "promedio_now": round(prom.get(t, 0.0), 4),
                         "points": pp + season[t][0], "matches": pm + season[t][1],
                         "season_points": season[t][0], "season_matches": season[t][1],
                         "prior_points": pp, "prior_matches": pm,
                         "p05": round(q[0], 4), "p50": round(q[1], 4), "p95": round(q[2], 4),
                         "p_promedio": round(res.p_relegation.get(t, 0.0), 5), "p_anual": 0.0,
                         "p_any": round(res.p_relegation.get(t, 0.0), 5)})
        rows.sort(key=lambda r: (r["promedio_now"], r["team"]))
        note = (f"The bottom {fmt.relegation_places} of the promedio go down: points per match over the "
                f"{fmt.promedio_years} seasons up to this one ({'the round robins only' if fmt.promedio_matches == 'round_robin' else 'every Tabla Anual match'}); "
                "a club promoted since averages over its own seasons.")
    else:
        now = _rows(state, aggregate=True)
        for r in now:
            t = r["team"]
            q = res.agg_points_quantiles.get(t, (0.0, 0.0, 0.0))
            rows.append({"team": t, "pts_now": r["pts"], "played": r["played"],
                         "exp_pts": round(res.agg_expected_points.get(t, 0.0), 2),
                         "p05": round(q[0], 1), "p50": round(q[1], 1), "p95": round(q[2], 1),
                         "p_promedio": 0.0, "p_anual": round(res.p_relegation.get(t, 0.0), 5),
                         "p_any": round(res.p_relegation.get(t, 0.0), 5)})
        rows.sort(key=lambda r: (r["pts_now"], r["team"]))
        note = f"The bottom {fmt.relegation_places} of the {fmt.aggregate_label} go down; there is no promedio."
    for i, r in enumerate(rows, start=1):
        r["pos"] = i
    return {
        "rows": rows,
        "prior": {"seasons": state.prior_seasons},
        "rules": {"places": fmt.relegation_places, "by": fmt.relegation_by, "promedio_seasons": fmt.promedio_years,
                  "label": fmt.aggregate_label, "note_en": note},
        "updated_at": _now(),
    }


def build_probs_json(state: TorneoState, res: TorneoResults, cfg: LeagueConfig) -> dict:
    cur = state.current
    teams = []
    for t in state.teams:
        teams.append({
            "team": t, "conference": None,
            "exp_pts": round(res.expected_points.get(t, 0.0), 2),
            "exp_anual": round(res.agg_expected_points.get(t, 0.0), 2),
            "p_title": round(res.p_title.get(t, 0.0), 5),
            "p_stage": round(res.p_stage.get(cur.key, {}).get(t, 0.0), 5),
            "p_playoffs": round(res.p_playoffs.get(t, 0.0), 5) if res.p_playoffs else None,
            "p_anual": round((res.p_agg_position.get(t) or [0.0])[0], 5),
            "p_libertadores": round(res.p_libertadores.get(t, 0.0), 5),
            "p_sudamericana": round(res.p_sudamericana.get(t, 0.0), 5),
            "p_relegation": round(res.p_relegation.get(t, 0.0), 5),
            "bands": {b.key: round(res.p_in_band(b.key, t), 5) for b in cfg.bands},
        })
    teams.sort(key=lambda r: (-r["p_title"], -r["exp_anual"]))
    return {"teams": teams, "bands": [{"key": b.key, "label": b.label, "first": b.first, "last": b.last, "kind": b.kind}
                                     for b in cfg.bands],
            "stage": {"key": cur.key, "label": cur.fmt.label}, "title_label": title_label(state, cfg),
            "has_playoff": True, "updated_at": _now()}


def title_label(state: TorneoState, cfg: LeagueConfig) -> str:
    if cfg.torneo.champion == "stages":
        return f"{state.current.fmt.label} champion"
    return "Champion"


def build_bracket_json(state: TorneoState, res: TorneoResults, cfg: LeagueConfig) -> dict:
    """The playoffs being played: Colombia's current stage (the cuadrangulares or the knockout), Uruguay's and Peru's
    season playoffs. Ties known from the store are listed by round with their decided winners."""
    fmt = cfg.torneo
    cur = state.current
    if fmt.champion == "stages":
        rounds = PHASE_ROUNDS[cur.fmt.final_phase]
        played = cur.playoff_done + cur.playoff_left
        scope = cur.key
    else:
        rounds = SEASON_ROUNDS[fmt.champion]
        played = state.season_done + state.season_left
        scope = SEASON
    known: dict[str, list[list[str]]] = {}
    forced: dict[str, str] = {}
    pairs: dict[tuple[str, frozenset], list] = {}
    groups: dict[str, list[str]] = {}
    for m in played:
        if m.group:
            g = groups.setdefault(m.group, [])
            for t in (m.home, m.away):
                if t not in g:
                    g.append(t)
            continue
        rk = m.round if m.round in ("qf", "sf", "final") else "final" if m.round is None else str(m.round)
        pairs.setdefault((rk, frozenset((m.home, m.away))), []).append(m)
    from oddsmarkets.football.competitions.league.torneo import _tie_winner
    for (rk, pair), legs in pairs.items():
        names = sorted(pair)
        known.setdefault(rk, []).append(names)
        single = (fmt.champion == "uruguay" and rk == "sf") or (scope != SEASON and cur.fmt.final_phase == "group_final")
        w = _tie_winner(sorted(legs, key=lambda m: (m.date is None, m.date.timestamp() if m.date else 0)), two_legs=not single)
        if w:
            forced[" v ".join(names)] = w
    group_tables = {}
    for g, members in sorted(groups.items()):
        rec = {t: {"team": t, "played": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0} for t in members}
        for m in played:
            if m.group != g or not m.done:
                continue
            for t, gf, ga in ((m.home, m.hg, m.ag), (m.away, m.ag, m.hg)):
                r = rec[t]
                r["played"] += 1
                r["gf"] += gf
                r["ga"] += ga
                r["w" if gf > ga else "d" if gf == ga else "l"] += 1
                r["pts"] += 3 if gf > ga else 1 if gf == ga else 0
        table = sorted(rec.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"], r["team"]))
        for i, r in enumerate(table, start=1):
            r["pos"] = i
            r["gd"] = r["gf"] - r["ga"]
            r["p_final"] = round(res.p_reach.get(r["team"], {}).get("final", 0.0), 5)
        group_tables[g] = table
    seeds = []
    if fmt.champion == "stages" and cur.fmt.final_phase in ("knockout8", "groups8"):
        table = state.standings(cur.key)
        seeds = [{"seed": i + 1, "team": t, "direct": True} for i, (t, _r, _p) in enumerate(table[:8])]
    notes = {
        "groups8": ("Liga II 2026 (Arts. 21-24): the top 8 of the round robin in two groups of four, 1st and 2nd at "
                    "the head of each and 3rd-8th drawn, played home and away; a group tie on points goes to the club "
                    "that heads it. The two group winners meet in a two-legged final, the one with more points over "
                    "the round robin and the groups at home in the second leg; level on points and goal difference "
                    "it goes to penalties. Until the groups are drawn the simulation draws them itself."),
        "knockout8": ("Liga I 2026 (Arts. 10-15): the top 8 in two-legged quarter-finals (1st and 2nd in opposite "
                      "halves, the other six drawn), semi-finals and a final; points, then aggregate goal "
                      "difference, then penalties. The better-placed club plays the second leg at home."),
        "uruguay": ("The Apertura and Clausura winners meet in a semi-final, its winner plays the Tabla Anual leader "
                    "over two legs; a club that won both stages, or that leads the Anual and wins the semi-final, "
                    "is champion with no final. Ties are settled by extra time and penalties in the simulation (the "
                    "AUF's rule is not in our sources)."),
        "peru": ("Reglamento Liga1 2026, 7.3: the Apertura and Clausura winners (if in the Acumulada top 8) and the "
                 "Acumulada's top two. Two-legged semi-finals and final, the better Acumulada club at home in the "
                 "second leg; points, aggregate goal difference, penalties. A stage winner in the top two goes "
                 "straight to the final; one club winning both stages is champion."),
    }
    note = notes.get(cur.fmt.final_phase if fmt.champion == "stages" else fmt.champion, "")
    playoff_rounds = [r for r, _ in rounds]
    return {
        "kind": "torneo",
        "scope": "stage" if fmt.champion == "stages" else "season",
        "stage": {"key": cur.key, "label": cur.fmt.label},
        "rounds": playoff_rounds,
        "round_labels": dict(rounds),
        "known": known,
        "forced": forced,
        "groups": group_tables,
        "seeds": {"Seeds": seeds} if seeds else {},
        "confirmed": cur.regular_complete,
        "reach": {t: {r: round(p, 5) for r, p in reach.items()} for t, reach in res.p_reach.items()},
        "p_playoffs": {t: round(p, 5) for t, p in res.p_playoffs.items()},
        "p_cup": {t: round(p, 5) for t, p in res.p_title.items()},
        "note": note,
        "updated_at": _now(),
    }
