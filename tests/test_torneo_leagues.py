"""
Colombia, Uruguay, Chile and Peru (2 Nov 2026): the torneo simulator's formats, golden and invariant.

Golden: a degenerate model in which the stronger club (the lower number, T00 the strongest) always wins 1-0 makes
every stage, playoff, berth and relegation known in advance, so each format's rules are pinned exactly: Colombia's
cuadrangulares and two-legged final, its knockout, the reclasificación berths and the promedio; Uruguay's
semi-final and outright champion; Peru's playoff shapes (a double stage winner, a stage winner with a bye). Invariant:
under a fair model the places add up (four Libertadores, four Sudamericana, the relegation count, one champion).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from oddsmarkets.football.competitions.league import torneo as T
from oddsmarkets.football.competitions.league import torneo_payloads as P
from oddsmarkets.football.competitions.league.config import (
    LIGA_1_PERU,
    LIGA_DE_PRIMERA,
    PRIMERA_A_COLOMBIA,
    PRIMERA_DIVISION_URUGUAY,
    LeagueConfig,
)
from oddsmarkets.football.core import MatchProbabilities

T0 = datetime(2026, 1, 20, 20, 0, tzinfo=timezone.utc)


class StrongerWins:
    """The lower-numbered club always wins 1-0, home or away."""

    def predict(self, home, away, neutral=True, max_goals=8):
        k = max_goals + 1
        m = np.zeros((k, k))
        if int(home[1:]) < int(away[1:]):
            m[1, 0] = 1.0
            return MatchProbabilities(1.0, 0.0, 0.0, 1.0, 0.0, m)
        m[0, 1] = 1.0
        return MatchProbabilities(0.0, 0.0, 1.0, 0.0, 1.0, m)


class Fair:
    """Every club alike: Poisson 1.3 v 1.1."""

    def predict(self, home, away, neutral=True, max_goals=8):
        k = max_goals + 1
        ks = np.arange(k)
        f = np.array([float(math.factorial(i)) for i in range(k)])
        ph = np.exp(-1.3) * 1.3 ** ks / f
        pa = np.exp(-1.1) * 1.1 ** ks / f
        m = np.outer(ph, pa)
        m /= m.sum()
        return MatchProbabilities(float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum()), 1.3, 1.1, m)


def plain(cfg: LeagueConfig, **kw) -> LeagueConfig:
    """The config without the real season's sanctions and unlisted results (they name real clubs)."""
    from dataclasses import replace
    return replace(cfg, point_adjustments=kw.pop("point_adjustments", ()), unlisted_results=(), n_sims=kw.pop("n_sims", 400),
                   sim_chunk=200, **kw)


class Store:
    """A store in the fetcher's shape, built match by match."""

    def __init__(self, sid: int = 2026):
        self.matches: dict[str, dict] = {}
        self.sid = sid
        self.n = 0

    def add(self, home, away, hs=None, as_=None, torneo=None, stage="league", rnd=None, group=None, sid=None,
            status=None, day=0, **extra):
        self.n += 1
        self.matches[f"g{self.n}"] = {
            "home": home, "away": away, "hs": hs, "as": as_, "round": rnd, "stage": stage, "group": group,
            "status": status or ("finished" if hs is not None else "notstarted"), "torneo": torneo,
            "season_id": sid or self.sid, "date": (T0 + timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%SZ"), **extra,
        }

    def result(self, home, away, **kw):
        """A played match decided by the stronger-wins rule."""
        hw = int(home[1:]) < int(away[1:])
        self.add(home, away, 1 if hw else 0, 0 if hw else 1, **kw)

    def round_robin(self, teams, torneo, played: float, day0=0, reverse=False, sid=None):
        pairs = [(a, b) for i, a in enumerate(teams) for b in teams[i + 1:]]
        cut = int(len(pairs) * played)
        for k, (a, b) in enumerate(pairs):
            h, aw = ((b, a) if reverse else (a, b)) if (k % 2) else ((a, b) if reverse else (b, a))
            if k < cut:
                self.result(h, aw, torneo=torneo, day=day0 + k // 10, sid=sid)
            else:
                self.add(h, aw, torneo=torneo, day=day0 + 30 + k // 10, sid=sid)

    def doc(self) -> dict:
        return {"matches": self.matches, "meta": {"season_id": self.sid, "season_name": "Test 2026"}}


def teams(n):
    return [f"T{i:02d}" for i in range(n)]


def entry(seasons):
    return {"seasons": [{"season_id": sid, "year": str(y), "name": f"S{y}"} for sid, y in seasons]}


# ── Colombia ─────────────────────────────────────────────────────────────────

def colombia_store(apertura_champion="T03", clausura_played=0.5):
    s = Store()
    ts = teams(20)
    # the 2025 season (both halves complete) for the promedio
    s.round_robin(ts, "apertura", 1.0, day0=-400, sid=2025)
    s.round_robin(ts, "clausura", 1.0, day0=-250, reverse=True, sid=2025)
    s.round_robin(ts, "apertura", 1.0)
    # the Apertura's final as played: the champion beat T00 over two legs (a real upset the data forces)
    s.add(apertura_champion, "T00", 2, 0, torneo="apertura", stage="playoff", rnd="final", day=60)
    s.add("T00", apertura_champion, 0, 0, torneo="apertura", stage="playoff", rnd="final", day=64)
    s.round_robin(ts, "clausura", clausura_played, day0=120, reverse=True)
    return s


def test_colombia_groups_final_berths_and_promedio_are_exact():
    cfg = plain(PRIMERA_A_COLOMBIA)
    st = T.torneo_state_from_store(colombia_store().doc(), cfg, entry([(2026, 2026), (2025, 2025)]))
    assert st.stage("apertura").champion == "T03"
    assert st.current.key == "clausura" and not st.current.closed
    assert st.promedio_prior["T00"] == (38 * 3, 38)
    res = T.TorneoSimulator(StrongerWins(), st, n_sims=400, chunk=200).run()
    # the Finalización: T00 heads group A, T01 group B, they win them and T00 the final
    assert res.p_stage["clausura"]["T00"] == 1.0
    assert res.p_title["T00"] == 1.0
    assert res.p_reach["T00"]["final"] == 1.0 and res.p_reach["T01"]["final"] == 1.0
    assert all(res.p_playoffs[f"T{i:02d}"] == 1.0 for i in range(8))
    # Libertadores: the two champions, then the best two others of the reclasificación
    lib = {t for t, p in res.p_libertadores.items() if p == 1.0}
    assert lib == {"T03", "T00", "T01", "T02"}
    assert {t for t, p in res.p_sudamericana.items() if p == 1.0} == {"T04", "T05", "T06", "T07"}
    # the promedio's bottom two
    assert {t for t, p in res.p_relegation.items() if p == 1.0} == {"T18", "T19"}
    assert sum(res.p_relegation.values()) == pytest.approx(2.0)


def test_colombia_cup_winner_takes_sudamericana_one_unless_already_in():
    cfg = plain(PRIMERA_A_COLOMBIA)
    st = T.torneo_state_from_store(colombia_store().doc(), cfg, entry([(2026, 2026), (2025, 2025)]))
    res = T.TorneoSimulator(StrongerWins(), st, n_sims=400, chunk=200, cup_dist={"T12": 1.0}).run()
    assert res.p_sudamericana["T12"] == 1.0
    assert res.p_sudamericana["T07"] == 0.0           # the cup winner took the last table place
    res2 = T.TorneoSimulator(StrongerWins(), st, n_sims=400, chunk=200, cup_dist={"T00": 1.0}).run()
    assert res2.p_sudamericana["T00"] == 0.0 and res2.p_sudamericana["T07"] == 1.0   # already in: down the table


def test_colombia_knockout_stage():
    cfg = plain(PRIMERA_A_COLOMBIA)
    s = Store()
    s.round_robin(teams(20), "apertura", 0.6)
    st = T.torneo_state_from_store(s.doc(), cfg, entry([(2026, 2026)]))
    assert st.current.key == "apertura"
    res = T.TorneoSimulator(StrongerWins(), st, n_sims=200, chunk=100).run()
    assert res.reach_rounds == ("qf", "sf", "final")
    assert res.p_title["T00"] == 1.0
    assert all(res.p_reach[f"T{i:02d}"]["qf"] == 1.0 for i in range(8))
    assert res.p_reach["T00"]["final"] == 1.0 and res.p_reach["T01"]["final"] == 1.0   # 1st and 2nd in opposite halves


def test_colombia_known_groups_and_played_legs_are_forced():
    """Groups already drawn are used as drawn, and a group match already played counts as played."""
    cfg = plain(PRIMERA_A_COLOMBIA)
    s = colombia_store(clausura_played=1.0)
    groups = {"A": ["T00", "T07", "T02", "T05"], "B": ["T01", "T06", "T03", "T04"]}
    for g, mem in groups.items():
        for i, h in enumerate(mem):
            for j, a in enumerate(mem):
                if i != j:
                    s.add(h, a, torneo="clausura", stage="playoff", group=g, day=200)
    # T07 beat T00 in their first meeting: forced in every simulation
    first = next(k for k, m in s.matches.items() if m.get("group") == "A" and m["home"] == "T00" and m["away"] == "T07")
    s.matches[first].update({"hs": 0, "as": 3, "status": "finished"})
    st = T.torneo_state_from_store(s.doc(), cfg, entry([(2026, 2026), (2025, 2025)]))
    res = T.TorneoSimulator(StrongerWins(), st, n_sims=200, chunk=100).run()
    # T00 still wins group A on points (5 wins of 6) and the final against T01
    assert res.p_title["T00"] == 1.0
    assert res.p_reach["T03"]["final"] == 0.0 and res.p_reach["T01"]["final"] == 1.0


def test_promedio_newcomer_averages_over_its_own_seasons():
    cfg = plain(PRIMERA_A_COLOMBIA)
    s = Store()
    ts = teams(20)
    old = ts[:19] + ["T99"]                         # T19 was not in the top flight in 2025; T99 was
    s.round_robin(old, "apertura", 1.0, day0=-400, sid=2025)
    s.round_robin(ts, "apertura", 1.0)
    st = T.torneo_state_from_store(s.doc(), cfg, entry([(2026, 2026), (2025, 2025)]))
    assert "T19" not in st.promedio_prior and st.promedio_prior["T00"][1] == 19


# ── Uruguay ──────────────────────────────────────────────────────────────────

def uruguay_store(apertura_winner="T05", clausura_played=0.6):
    s = Store()
    ts = teams(16)
    s.round_robin(ts, "apertura", 1.0, sid=2025, day0=-400)
    s.round_robin(ts, "intermedio", 1.0, sid=2025, day0=-350)
    s.round_robin(ts, "clausura", 1.0, sid=2025, day0=-300)
    # this season's Apertura, its winner forced by one table-topping result set: every other match by the rule
    pairs = [(a, b) for i, a in enumerate(ts) for b in ts[i + 1:]]
    for k, (a, b) in enumerate(pairs):
        if apertura_winner in (a, b):
            other = b if a == apertura_winner else a
            s.add(apertura_winner, other, 3, 0, torneo="apertura", day=k // 8)
        else:
            s.result(a, b, torneo="apertura", day=k // 8)
    a_pos = [1, 4, 5, 8, 9, 12, 13, 16]
    order = [apertura_winner] + [t for t in ts if t != apertura_winner]
    ga = [order[p - 1] for p in a_pos]
    gb = [t for t in order if t not in ga]
    for g in (ga, gb):
        for i, a in enumerate(g):
            for b in g[i + 1:]:
                s.result(a, b, torneo="intermedio", day=40)
    s.result(min(ga), min(gb), torneo="intermedio", stage="playoff", rnd="final", day=50)
    s.round_robin(ts, "clausura", clausura_played, day0=80)
    return s


def test_uruguay_semi_final_and_the_anual_leader_champion_outright():
    cfg = plain(PRIMERA_DIVISION_URUGUAY)
    st = T.torneo_state_from_store(uruguay_store().doc(), cfg, entry([(2026, 2026), (2025, 2025)]))
    assert st.stage("apertura").champion == "T05"
    assert st.stage("intermedio").closed
    res = T.TorneoSimulator(StrongerWins(), st, n_sims=400, chunk=200).run()
    # T00 wins the Clausura, beats T05 in the semi-final and, leading the Anual, is champion with no final
    assert res.p_stage["clausura"]["T00"] == 1.0
    assert res.p_title["T00"] == 1.0
    assert res.p_reach["T00"]["sf"] == 1.0 and res.p_reach["T05"]["sf"] == 1.0
    assert sum(res.p_libertadores.values()) == pytest.approx(4.0)
    assert res.p_libertadores["T00"] == 1.0
    assert sum(res.p_relegation.values()) == pytest.approx(3.0)


def test_uruguay_double_stage_winner_is_champion():
    cfg = plain(PRIMERA_DIVISION_URUGUAY)
    st = T.torneo_state_from_store(uruguay_store(apertura_winner="T00").doc(), cfg, entry([(2026, 2026), (2025, 2025)]))
    res = T.TorneoSimulator(StrongerWins(), st, n_sims=200, chunk=100).run()
    assert res.p_title["T00"] == 1.0
    assert res.p_reach["T00"].get("sf", 0.0) == 0.0          # no semi-final is played


# ── Peru ─────────────────────────────────────────────────────────────────────

def peru_store(apertura_winner="T00"):
    s = Store()
    ts = teams(18)
    pairs = [(a, b) for i, a in enumerate(ts) for b in ts[i + 1:]]
    for k, (a, b) in enumerate(pairs):
        if apertura_winner in (a, b):
            other = b if a == apertura_winner else a
            s.add(apertura_winner, other, 2, 0, torneo="apertura", day=k // 9)
        else:
            s.result(a, b, torneo="apertura", day=k // 9)
    s.round_robin(ts, "clausura", 0.5, day0=60, reverse=True)
    return s


def test_peru_double_stage_winner_and_the_runner_up_playoff():
    cfg = plain(LIGA_1_PERU)
    st = T.torneo_state_from_store(peru_store().doc(), cfg, entry([(2026, 2026)]))
    assert st.stage("apertura").champion == "T00"
    res = T.TorneoSimulator(StrongerWins(), st, n_sims=400, chunk=200).run()
    assert res.p_title["T00"] == 1.0
    assert res.p_runner_up["T01"] == 1.0                   # 3rd v 4th, then the winner v 2nd
    assert {t for t, p in res.p_libertadores.items() if p == 1.0} == {"T00", "T01", "T02", "T03"}
    assert {t for t, p in res.p_sudamericana.items() if p == 1.0} == {"T04", "T05", "T06", "T07"}
    assert {t for t, p in res.p_relegation.items() if p == 1.0} == {"T16", "T17"}


def test_peru_stage_winner_in_the_top_two_goes_straight_to_the_final():
    cfg = plain(LIGA_1_PERU)
    st = T.torneo_state_from_store(peru_store(apertura_winner="T05").doc(), cfg, entry([(2026, 2026)]))
    assert st.stage("apertura").champion == "T05"
    res = T.TorneoSimulator(StrongerWins(), st, n_sims=400, chunk=200).run()
    # the Acumulada's top two are T00 (the Clausura winner) and T01; T05 won the Apertura and sits in the top 8.
    # Three clubs: the stage winner in the top two (T00) goes straight to the final, T01 and T05 meet in the semi.
    assert res.p_title["T00"] == 1.0
    assert res.p_reach["T00"]["final"] == 1.0
    assert res.p_reach["T00"].get("sf", 0.0) == 0.0
    assert res.p_reach["T01"]["sf"] == 1.0 and res.p_reach["T05"]["sf"] == 1.0
    assert res.p_runner_up["T01"] == 1.0
    assert sum(res.p_libertadores.values()) == pytest.approx(4.0)


# ── invariants under a fair model ───────────────────────────────────────────

@pytest.mark.parametrize("cfg,store,ent,n_rel", [
    (PRIMERA_A_COLOMBIA, colombia_store, [(2026, 2026), (2025, 2025)], 2),
    (PRIMERA_DIVISION_URUGUAY, uruguay_store, [(2026, 2026), (2025, 2025)], 3),
    (LIGA_1_PERU, peru_store, [(2026, 2026)], 2),
])
def test_places_add_up(cfg, store, ent, n_rel):
    st = T.torneo_state_from_store(store().doc(), plain(cfg), entry(ent))
    res = T.TorneoSimulator(Fair(), st, n_sims=600, chunk=300, seed=5).run()
    assert sum(res.p_title.values()) == pytest.approx(1.0)
    assert sum(res.p_libertadores.values()) == pytest.approx(4.0)
    assert sum(res.p_sudamericana.values()) == pytest.approx(4.0)
    assert sum(res.p_relegation.values()) == pytest.approx(n_rel)
    for t in st.teams:
        assert sum(res.p_position[t]) == pytest.approx(1.0)
        assert sum(res.p_agg_position[t]) == pytest.approx(1.0)
        assert res.p_libertadores[t] + res.p_sudamericana[t] <= 1.0 + 1e-9
    for key, dist in res.p_stage.items():
        assert sum(dist.values()) == pytest.approx(1.0), key


# ── state: what the store does not list, sanctions, dead fixtures ───────────

def test_unlisted_pairs_are_simulated_and_unlisted_results_counted_once():
    from dataclasses import replace
    s = Store()
    ts = teams(18)
    s.round_robin(ts, "apertura", 1.0)
    s.round_robin(ts, "clausura", 0.5, day0=60, reverse=True)
    # drop two Clausura fixtures from the list: one played (in the config), one still to play
    gone = [k for k, m in s.matches.items() if m["torneo"] == "clausura" and m["status"] == "notstarted"][:2]
    h0, a0 = s.matches[gone[0]]["home"], s.matches[gone[0]]["away"]
    for k in gone:
        del s.matches[k]
    cfg = replace(plain(LIGA_1_PERU), unlisted_results=(("clausura", h0, a0, 0, 0),),
                  point_adjustments=(("", "T17", -4), ("clausura", "T16", -1)))
    st = T.torneo_state_from_store(s.doc(), cfg, entry([(2026, 2026)]))
    cl = st.stage("clausura")
    assert len(cl.regular_missing) == 1
    assert any(m.game_id.startswith("unlisted-") for m in cl.regular_done)
    agg = {t: p for t, _r, p in st.standings(aggregate=True)}
    recs = st.records(aggregate=True)
    assert agg["T17"] == recs["T17"].points - 4 and agg["T16"] == recs["T16"].points - 1
    # listed again by Sofascore: the unlisted result is not added twice
    s.add(h0, a0, 1, 1, torneo="clausura", day=90)
    st2 = T.torneo_state_from_store(s.doc(), cfg, entry([(2026, 2026)]))
    assert not any(m.game_id.startswith("unlisted-") for m in st2.stage("clausura").regular_done)


def test_dead_fixtures_of_a_finished_stage_are_dropped():
    s = Store()
    ts = teams(18)
    s.round_robin(ts, "apertura", 1.0)
    s.add("T00", "T01", torneo="apertura", status="postponed")          # never played, the Clausura has begun
    s.add("T02", "T03", torneo="apertura", status="canceled")
    s.round_robin(ts, "clausura", 0.2, day0=60, reverse=True)
    st = T.torneo_state_from_store(s.doc(), plain(LIGA_1_PERU), entry([(2026, 2026)]))
    assert not st.stage("apertura").regular_left and st.stage("apertura").closed


# ── payloads ─────────────────────────────────────────────────────────────────

def test_payload_shapes():
    cfg = plain(PRIMERA_A_COLOMBIA)
    st = T.torneo_state_from_store(colombia_store().doc(), cfg, entry([(2026, 2026), (2025, 2025)]))
    res = T.TorneoSimulator(Fair(), st, n_sims=200, chunk=100).run()
    table = P.build_table_json(st, res, cfg)
    assert table["stage"]["key"] == "clausura" and len(table["standings"]) == 20
    assert {s["key"] for s in table["stages"]} == {"apertura", "clausura"}
    assert table["stages"][0]["champion"] == "T03" and table["stages"][0]["status"] == "done"
    anual = P.build_anual_json(st, res, cfg)
    assert anual["label"] == "Reclasificación" and len(anual["rows"]) == 20
    assert {r["berth_now"] for r in anual["rows"]} >= {"lib_auto", "down_promedio"}
    assert anual["berths"]["now"]["autos"][0] == {"team": "T03", "why": "Apertura champion"}
    rel = P.build_relegation_json(st, res, cfg)
    assert rel["rules"]["by"] == "promedio" and rel["rows"][0]["promedio_now"] <= rel["rows"][-1]["promedio_now"]
    probs = P.build_probs_json(st, res, cfg)
    assert {"p_title", "p_libertadores", "p_sudamericana", "p_relegation", "p_anual"} <= set(probs["teams"][0])
    br = P.build_bracket_json(st, res, cfg)
    assert br["rounds"] == ["groups", "final"] and br["scope"] == "stage"


# ── Chile: a plain league with sanctions ─────────────────────────────────────

def test_chile_sanctions_apply_to_the_table():
    from dataclasses import replace
    from oddsmarkets.football.competitions.league.season_state import LeagueMatch, LeagueState
    cfg = replace(LIGA_DE_PRIMERA, point_adjustments=(("", "A", -2), ("", "B", 2)))
    st = LeagueState(cfg=cfg, teams=["A", "B"], finished=[LeagueMatch("1", "A", "B", 1, 0, status="finished")])
    rec = st.records()
    assert rec["A"].points == 1 and rec["B"].points == 2
    assert LIGA_DE_PRIMERA.tiebreak == ("pts", "gd", "w", "gf")


def test_real_sanctions_name_clubs_of_the_season():
    """The configs' sanctions and unlisted results name clubs as Sofascore spells them (seasons.json's lists)."""
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "oddsmarkets/football/competitions/league/data/seasons.json"
    seasons = json.loads(path.read_text(encoding="utf-8"))["leagues"]
    for cfg in (PRIMERA_A_COLOMBIA, PRIMERA_DIVISION_URUGUAY, LIGA_DE_PRIMERA, LIGA_1_PERU):
        if cfg.slug not in seasons:
            continue
        clubs = set(seasons[cfg.slug].get("teams") or [])
        for _stage, club, _pts in cfg.point_adjustments:
            assert club in clubs, (cfg.slug, club)
        for _stage, h, a, _hg, _ag in cfg.unlisted_results:
            assert h in clubs and a in clubs, (cfg.slug, h, a)


# ── the fetcher: stage labels, finished past seasons, discovery years ──────────

def _event(label, round_info=None, group_label=None):
    return {"id": 1, "homeTeam": {"name": "A", "id": 10}, "awayTeam": {"name": "B", "id": 11},
            "tournament": {"name": label}, "roundInfo": round_info or {"round": 3},
            "status": {"type": "finished"}, "homeScore": {"display": 1}, "awayScore": {"display": 0}, "startTimestamp": 1767225600}


@pytest.mark.parametrize("label,torneo,stage,group", [
    ("Liga DIMAYOR, Finalizacion", "clausura", "league", None),
    ("Liga DIMAYOR, Apertura", "apertura", "league", None),
    ("Primera A, Clausura, Championship, Group B", "clausura", "playoff", "B"),
    ("Primera A, Apertura, Group A", "apertura", "playoff", "A"),
    ("Liga AUF Uruguaya, Torneo Intermedio", "intermedio", "league", None),
    ("Liga 1, Clausura", "clausura", "league", None),
])
def test_event_record_files_the_stage(label, torneo, stage, group):
    from oddsmarkets.football.sources.sofascore import event_record
    gid, rec = event_record(_event(label), lambda n: n, 99, torneo_labels=True)
    assert rec["torneo"] == torneo and rec["stage"] == stage and rec["group"] == group


def test_event_record_without_torneo_labels_is_unchanged():
    from oddsmarkets.football.sources.sofascore import event_record
    _gid, rec = event_record(_event("Liga MX, Apertura"), lambda n: n, 99)
    assert "torneo" not in rec


def test_complete_past_season_is_kept_for_a_week():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from fetch_sofascore_leagues import complete_past_season
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    store = {"matches": {"1": {"season_id": 5, "status": "finished"}, "2": {"season_id": 5, "status": "postponed"}}}
    assert complete_past_season(store, 5, "2026-10-30T00:00:00Z", now)
    assert not complete_past_season(store, 5, "2026-10-20T00:00:00Z", now)            # older than a week
    assert not complete_past_season(store, 5, None, now)
    store["matches"]["3"] = {"season_id": 5, "status": "notstarted"}
    assert not complete_past_season(store, 5, "2026-10-30T00:00:00Z", now)             # still something to play


def test_discovery_season_year():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from discover_sofascore_leagues import _season_year
    assert _season_year({"year": "2026"}) == 2026
    assert _season_year({"year": "25/26"}) == 2026
    assert _season_year({"name": "Primera A, Finalización 2024"}) == 2024
