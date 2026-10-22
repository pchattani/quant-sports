"""
Player value, club strengths and needs, and the transfer simulator's inputs
(oddsmarkets/football/analytics/value.py, value_payloads.py, sensitivity.py).

Offline: synthetic line-ups with a planted signal for the model, the sample-store
generator for the payloads, a small simulated league for the sensitivity curves.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from oddsmarkets.football.analytics import value as V
from oddsmarkets.football.analytics import value_payloads as VP
from oddsmarkets.football.analytics.sensitivity import CachedModel, TiltedModel, gd_per_delta, league_sensitivity, tilt_matrix

ROOT = Path(__file__).parent.parent


# ── roles from formations ────────────────────────────────────────────────────

@pytest.mark.parametrize("formation, roles", [
    ("4-2-3-1", ["FB", "CB", "CB", "FB", "DM", "DM", "W", "AM", "W", "ST"]),
    ("4-3-3", ["FB", "CB", "CB", "FB", "CM", "CM", "CM", "W", "ST", "W"]),
    ("3-4-2-1", ["CB", "CB", "CB", "FB", "CM", "CM", "FB", "AM", "AM", "ST"]),
    ("3-5-2", ["CB", "CB", "CB", "FB", "CM", "CM", "CM", "FB", "ST", "ST"]),
    ("5-3-2", ["FB", "CB", "CB", "CB", "FB", "CM", "CM", "CM", "ST", "ST"]),
    ("4-4-2", ["FB", "CB", "CB", "FB", "W", "CM", "CM", "W", "ST", "ST"]),
    ("4-1-4-1", ["FB", "CB", "CB", "FB", "DM", "W", "CM", "CM", "W", "ST"]),
    ("3-1-4-2", ["CB", "CB", "CB", "DM", "FB", "CM", "CM", "FB", "ST", "ST"]),
    ("4-1-2-1-2", ["FB", "CB", "CB", "FB", "DM", "CM", "CM", "AM", "ST", "ST"]),
    ("5-4-1", ["FB", "CB", "CB", "CB", "FB", "W", "CM", "CM", "W", "ST"]),
])
def test_formation_roles_follow_sofascores_line_order(formation, roles) -> None:
    assert V.formation_roles([int(x) for x in formation.split("-")]) == roles


def test_assign_roles_needs_eleven_starters_one_keeper_and_ten_outfielders() -> None:
    letters = ["G", "D", "D", "D", "D", "M", "M", "M", "F", "F", "F"]
    out = V.assign_roles("4-3-3", letters)
    assert out[0] == "GK" and out[1:] == V.formation_roles([4, 3, 3])
    # The keeper is placed wherever the source lists him.
    moved = V.assign_roles("4-3-3", letters[1:5] + ["G"] + letters[5:])
    assert moved[4] == "GK" and moved.count("GK") == 1
    assert V.assign_roles("4-4-3", letters) is None            # eleven outfielders
    assert V.assign_roles("4-3-3", letters[:10]) is None       # ten starters
    assert V.assign_roles("4-3-3", ["D"] + letters[1:]) is None  # no keeper
    assert V.assign_roles(None, letters) is None and V.assign_roles("diamond", letters) is None


# ── collecting line-ups ──────────────────────────────────────────────────────

def _store_with(players: dict, formation=("4-3-3", "4-3-3"), possession=(60, 40), pens=()) -> dict:
    return {
        "matches": {"1": {"home": "A", "away": "B", "hs": 2, "as": 1, "date": "2026-09-01T18:00:00Z", "season_id": 7,
                          "home_id": 10, "away_id": 20, "status": "finished"}},
        "lineups": {"1": players},
        "team_stats": {"1": {"home": {"ballPossession": possession[0]}, "away": {"ballPossession": possession[1]}}},
        "lineup_extras": {"1": {"formation": {"home": formation[0], "away": formation[1]}}},
        "incidents": {"1": [{"incident_type": "goal", "incident_class": "penalty", "player_id": int(p)} for p in pens]},
        "meta": {"season_id": 7},
    }


def _xi(team: str, base: int, stats=None) -> dict:
    letters = ["G", "D", "D", "D", "D", "M", "M", "M", "F", "F", "F"]
    return {str(base + i): {"n": f"{team}{i}", "t": team, "p": l, "s": {"minutesPlayed": 90, "rating": 7.0, **(stats or {})}}
            for i, l in enumerate(letters)}


def test_collector_reads_npxg_possession_adjustment_roles_and_the_match() -> None:
    home = _xi("A", 100, {"expectedGoals": 0.5, "wonTackle": 2, "possessionLostCtrl": 4})
    away = _xi("B", 200, {"expectedGoals": 0.1, "wonTackle": 2})
    home["108"]["s"]["expectedGoals"] = 1.29        # took and scored a penalty
    store = _store_with({**home, **away}, pens=[108])
    col = V.ValueCollector()
    assert col.add_store("premier-league", store) == 1
    assert col.add_store("premier-league", store) == 0   # a match is read once
    R = col.finish()
    assert len(R) == 22 and R.m_day.size == 1
    k = V.FKEYS.index
    pen_row = int(np.flatnonzero(R.pid == 108)[0])
    assert R.X[pen_row, k("npxg")] == pytest.approx(1.29 - V.PEN_XG)
    # The home side had 60% of the ball: its tackles count 50 / 40; the away side's 50 / 60.
    h0, a0 = int(np.flatnonzero(R.pid == 101)[0]), int(np.flatnonzero(R.pid == 201)[0])
    assert R.X[h0, k("tkw")] == pytest.approx(2 * 50 / 40) and R.X[a0, k("tkw")] == pytest.approx(2 * 50 / 60)
    assert R.X[h0, k("lost")] == -4                      # signed so that every weight is non-negative
    assert R.m_npxg[0, 0] == pytest.approx(10 * 0.5 + 1.29 - V.PEN_XG, rel=1e-5) and R.m_npxg[0, 1] == pytest.approx(11 * 0.1, rel=1e-5)
    assert [V.ROLES[r] for r in R.role[R.side == 0]] == ["GK"] + V.formation_roles([4, 3, 3])
    assert R.current["premier-league"] == "7" and R.comp_scope == ["club"]


# ── fitting and validation on a planted signal ───────────────────────────────

def _synthetic_rows(n_players: int = 220, n_matches: int = 1400, seed: int = 3) -> V.Rows:
    """Players with a true quality that drives their actions and their teams' xG difference."""
    rng = np.random.default_rng(seed)
    quality = rng.normal(0, 1, n_players)
    teams = [list(range(i, n_players, 20)) for i in range(20)]          # 20 squads of 11
    col = {k: [] for k in ("pid", "match", "side", "day", "comp", "sid", "tid", "start", "mins", "letter", "role", "rating")}
    X, m_day, m_tid, m_npxg, m_goals = [], [], [], [], []
    start = date(2025, 8, 1).toordinal()
    for mi in range(n_matches):
        h, a = rng.choice(20, size=2, replace=False)
        sides = (teams[h], teams[a])
        q = [quality[s].sum() for s in sides]
        xgd = 0.08 * (q[0] - q[1]) + 0.25 + rng.normal(0, 1.0)
        npxg = (max(1.3 + xgd / 2, 0.05), max(1.3 - xgd / 2, 0.05))
        day = start + mi // 10
        for s, squad in enumerate(sides):
            for pid in squad:
                col["pid"].append(pid); col["match"].append(mi); col["side"].append(s); col["day"].append(day)
                col["comp"].append(0); col["sid"].append(0); col["tid"].append(1000 + (h if s == 0 else a)); col["start"].append(1)
                col["mins"].append(90.0); col["letter"].append(2); col["role"].append(4)
                col["rating"].append(6.8 + 0.2 * quality[pid] + rng.normal(0, 0.6))
                x = np.zeros(V.NF)
                x[V.FKEYS.index("xa")] = max(0.0, 0.1 + 0.05 * quality[pid] + rng.normal(0, 0.05))
                x[V.FKEYS.index("tkw")] = max(0.0, 2 + 0.6 * quality[pid] + rng.normal(0, 1.0))
                x[V.FKEYS.index("lost")] = -max(0.0, 8 - 0.5 * quality[pid] + rng.normal(0, 2.0))
                X.append(x)
        m_day.append(day); m_tid.append((1000 + h, 1000 + a)); m_npxg.append(npxg); m_goals.append((rng.poisson(npxg[0]), rng.poisson(npxg[1])))
    arr = {k: np.array(v) for k, v in col.items()}
    return V.Rows(pid=arr["pid"], match=arr["match"], side=arr["side"], day=arr["day"], comp=arr["comp"], sid=arr["sid"], tid=arr["tid"],
                  start=arr["start"], mins=arr["mins"].astype(float), letter=arr["letter"], role=arr["role"], rating=arr["rating"].astype(float),
                  X=np.array(X), comps=["premier-league"], comp_scope=["club"], sids=["1"], current={"premier-league": "1"},
                  m_day=np.array(m_day), m_comp=np.zeros(n_matches, dtype=int), m_tid=np.array(m_tid), m_npxg=np.array(m_npxg),
                  m_goals=np.array(m_goals), m_gid=np.arange(n_matches))


def test_fit_weights_are_never_negative() -> None:
    rng = np.random.default_rng(0)
    Z = rng.normal(size=(400, 3))
    y = 1.5 * Z[:, 0] - 2.0 * Z[:, 1] + rng.normal(0, 0.1, 400)
    beta, h = V.fit_weights(Z, y, lam=1.0)
    assert beta[1] == 0.0 and beta[2] >= 0.0
    # With the negative column pinned at zero, the rest is (nearly) least squares on the others.
    ols = np.linalg.lstsq(np.column_stack([np.ones(400), Z[:, 0], Z[:, 2]]), y, rcond=None)[0]
    assert beta[0] == pytest.approx(ols[1], abs=0.01)


def test_prior_rates_use_only_earlier_days() -> None:
    R = _synthetic_rows(n_matches=60)
    club = V._club_rows(R)
    prior, prior_r = V.prior_rates(R, club)
    first_day = R.day.min()
    # On the first day nobody has a history: zero rates and a 6.7 rating for everyone.
    sel = R.day == first_day
    assert np.allclose(prior[sel], 0.0) and np.allclose(prior_r[sel], 6.7)
    # Changing a later match's stats never moves an earlier prior (nor the position means behind it).
    X2 = R.X.copy()
    X2[R.day == R.day.max()] += 50.0
    prior2, _ = V.prior_rates(V.Rows(**{**R.__dict__, "X": X2}), club)
    earlier = R.day < R.day.max()
    assert np.allclose(prior[earlier], prior2[earlier])


def test_walk_forward_validation_finds_the_planted_signal_and_the_model_beats_noise() -> None:
    R = _synthetic_rows()
    vm = V.fit_model(R)
    val = vm.validation
    assert val["ok"] and val["n_test"] > 300
    assert val["r2"]["xgd"]["value"] > 0.02 and val["r2"]["xgd"]["box"] > 0.0
    w = {x["key"]: x["weight"] for x in vm.weights()}
    assert w["tkw"] > 0 and w["xa"] >= 0 and w["lost"] <= 0      # signs as declared
    assert vm.fitted and vm.scale >= 0 and vm.rating_w >= 0
    # Centring: the competition's minutes-weighted mean value is its strength over eleven (here 0).
    vals = V.row_values(R, vm).sum(axis=1)
    assert vals.sum() / (R.mins.sum() / 90.0) == pytest.approx(0.0, abs=1e-9)
    assert vm.reliability.get("value_r", 0) > 0.3


def test_too_few_matches_fall_back_to_the_default_weights() -> None:
    vm = V.fit_model(_synthetic_rows(n_matches=40))
    assert not vm.fitted and np.allclose(vm.beta, V.default_beta()) and not vm.validation["ok"]


# ── the small pieces ─────────────────────────────────────────────────────────

def test_points_per_goal_is_the_poisson_slope() -> None:
    s = V.xpts_slope(1.35)
    assert 0.6 < s < 0.75
    # A goal of goal difference is worth more where fewer goals are scored.
    assert V.xpts_slope(1.1) > V.xpts_slope(1.6)


def test_continuation_is_one_for_the_young_and_never_rises_with_age() -> None:
    ages = [a for a in range(18, 41) for _ in range(max(1, 60 - max(0, a - 27) * 6))]
    c = V.continuation_curve(ages)
    assert all(c[a] == 1.0 for a in range(17, 27))
    vals = [c[a] for a in range(17, 41)]
    assert all(b <= a + 1e-9 for a, b in zip(vals, vals[1:])) and c[36] < 0.9


def test_ageing_curve_falls_back_without_data_and_fits_a_quadratic_with_it() -> None:
    assert V.ageing_curve([])[20] > 0 > V.ageing_curve([])[34]
    pairs = [(a + 0.5, 0.1 - 0.01 * (a - 20), 1.0) for a in range(18, 36) for _ in range(10)]
    c = V.ageing_curve(pairs)
    assert c[20] > c[27] > c[33]


def test_window_status_open_closed_and_across_new_year() -> None:
    assert V.window_status("premier-league", date(2026, 8, 10))["open"] is True
    closed = V.window_status("premier-league", date(2026, 10, 15))
    assert closed["open"] is False and closed["next"] == "1 Jan 2027"
    assert V.window_status("liga-mx", date(2027, 1, 15))["open"] is True     # 1 Dec - 1 Feb
    assert V.window_status("not-a-league", date(2026, 10, 15)) is None


def test_grades_are_league_quintiles() -> None:
    assert VP.grade_of(85) == "A" and VP.grade_of(50) == "C" and VP.grade_of(5) == "E"


def test_targets_rank_by_gain_respect_strength_age_club_and_per_club_caps() -> None:
    info = {}

    def add(pid, proj, tid, age=25, mins=2000, role="CB", league="la-liga"):
        info[pid] = {"proj": proj, "tid": tid, "age": age, "min": mins, "role": role, "league": league, "name": f"P{pid}", "club": f"C{tid}"}

    add(1, 0.30, 99)                 # the buyer's own player: never a target
    add(2, 0.28, 50)                 # a stronger club: out
    add(3, 0.25, 51); add(4, 0.24, 51); add(5, 0.23, 51)     # third from one club: out
    add(6, 0.20, 52, league="premier-league")                # a league far stronger than the buyer's: out
    add(7, 0.15, 53)
    add(8, 0.06, 54)                 # barely better than the weakest regular
    pool = {50: {"strength": 2.4}, 51: {"strength": 1.6}, 52: {"strength": 1.5}, 53: {"strength": 1.7}, 54: {"strength": 1.2}}
    g = {"slots": 2.0, "depth": [{"id": "x", "proj": 0.10, "min": 600}, {"id": "y", "proj": 0.05, "min": 500}]}
    cands = sorted(info, key=lambda p: -info[p]["proj"])
    out = VP.find_targets(99, "CB", g, 1.8, info, cands, pool, {}, {}, {}, {}, 0.68, 20, date(2026, 10, 15),
                          offsets={"la-liga": 0.3, "premier-league": 0.7}, buyer_league="la-liga")
    assert [t["id"] for t in out] == ["3", "4", "7", "8"]
    assert out[0]["gain90"] == pytest.approx(0.25 - 0.05)
    assert out[0]["gain_pts_rest"] == pytest.approx(0.20 * VP.REGULAR_SHARE * 0.68 * 20, abs=0.01)
    assert all(a["gain90"] >= b["gain90"] for a, b in zip(out, out[1:]))
    # Hints only where the data supports them.
    ctx = {"depth": {(51, "CB"): 4}, "settled": {53}}
    out = VP.find_targets(99, "CB", g, 1.8, info, cands, pool, {}, {"3": "2027-05"}, {}, {}, 0.68, 20, date(2026, 10, 15),
                          offsets={"la-liga": 0.3, "premier-league": 0.7}, buyer_league="la-liga", hints_ctx=ctx)
    hints = {t["id"]: " | ".join(t["hints"]) for t in out}
    assert "4 regulars" in hints["3"] and "contract ends May 2027" in hints["3"]
    assert "little left to play for" in hints["7"] and hints["8"] == ""


# ── sensitivity curves ───────────────────────────────────────────────────────

def test_tilting_a_poisson_matrix_is_a_poisson_with_the_scaled_rate() -> None:
    k = np.arange(9)
    pois = lambda lam: np.exp(-lam) * lam ** k / np.array([math.factorial(int(i)) for i in k])  # noqa: E731
    m = np.outer(pois(1.4), pois(1.1))
    t = tilt_matrix(m, math.exp(0.1), math.exp(-0.1))
    ref = np.outer(pois(1.4 * math.exp(0.1)), pois(1.1 * math.exp(-0.1)))
    assert np.allclose(t, ref / ref.sum(), atol=1e-4)


def _small_league():
    import scripts.make_league_sample_store as sample
    import scripts.build_site_all as b

    cfg = b.LEAGUES["premier-league"]
    store = sample.build(cfg, played_rounds=10)
    state = b.league_state_from_store(store, cfg)
    params, _ = b.model_params_for(cfg.slug)
    model, _ = b.build_model(b.training_frame(store, cfg), state.teams, state.previous_rank, cfg, params)
    return model, state, cfg


def test_league_sensitivity_curves_move_the_right_way_and_leave_other_pairings_alone() -> None:
    model, state, cfg = _small_league()
    base = CachedModel(model)
    team, other = state.teams[0], state.teams[1:3]
    p0 = base.predict(other[0], other[1])
    p1 = TiltedModel(base, team, 0.3).predict(other[0], other[1])
    assert p1 is p0
    up = TiltedModel(base, team, 0.3).predict(team, other[0])
    assert up.home_win > base.predict(team, other[0]).home_win
    assert gd_per_delta(base, team, [(m.home_team, m.away_team, False) for m in state.remaining]) > 0.5
    sens = league_sensitivity(model, state, cfg, n_sims=600, budget_s=None)
    assert sens["shifts"] == [-0.3, -0.15, 0.0, 0.15, 0.3] and len(sens["teams"]) == len(state.teams)
    c = sens["teams"][team]
    assert all(b2 > a for a, b2 in zip(c["exp_pts"], c["exp_pts"][1:]))
    assert c["band:rel"][0] >= c["band:rel"][-1] and c["p_title"][-1] >= c["p_title"][0]
    assert {"exp_pts", "p_title", "band:ucl", "band:rel"} <= set(sens["metrics"])


# ── the payloads, end to end on the sample store ─────────────────────────────

@pytest.fixture(scope="module")
def built_value(tmp_path_factory):
    import scripts.make_league_sample_store as sample
    import scripts.build_site_all as b
    from oddsmarkets.football.analytics.unified import competitions

    data = tmp_path_factory.mktemp("value-data")
    cfg = b.LEAGUES["premier-league"]
    store = sample.build(cfg, played_rounds=14)
    col = V.ValueCollector()
    col.add_store("premier-league", store, current_key=900002)
    R = col.finish()
    teams = {}
    for m in store["matches"].values():
        teams[m["home"]] = {"team_id": m["home_id"], "slug": m["home"].lower()}
    people, club_of, clubs = {}, {}, {}
    pid_team = {}
    for lu in store["lineups"].values():
        for pid, p in lu.items():
            pid_team[pid] = p["t"]
    for pid, pm in store["players"].items():
        people[pid] = {"name": pm["n"], "pos": pm["pos"], "dob": datetime.fromtimestamp(pm["dob"], tz=timezone.utc).date().isoformat()}
        club_of[pid] = {"tid": teams[pid_team[pid]]["team_id"]} if pid in pid_team else None
    for name, t in teams.items():
        clubs[str(t["team_id"])] = {"name": name, "names": {"premier-league": name}}
    pool = {"leagues": {"premier-league": {}}, "clubs": [
        {"team": n, "comp": "premier-league", "in_league": True, "team_id": t["team_id"], "xg_for": 1.4 + 0.05 * i, "xg_against": 1.3,
         "strength": 1.3 + 0.05 * i, "rank": i + 1} for i, (n, t) in enumerate(teams.items())]}
    entry = {"slug": "premier-league", "ok": True, "season": "sample", "games_total": 380, "_teams": teams, "_floor": 270}
    (data / "premier-league").mkdir()
    (data / "premier-league" / "meta.json").write_text(json.dumps({"calibration": {"mean_goals": 1.4}}), encoding="utf-8")
    ctx = VP.ValueContext(data_dir=data, comps=competitions(), pool=pool, people=people, club_of=club_of, clubs=clubs,
                          squads={}, archive={}, entries=[entry], today=datetime(2026, 12, 1, tzinfo=timezone.utc))
    summary = VP.build_value(ctx, R)
    return data, summary


def _rows(doc):
    return [dict(zip(doc["fields"], r)) for r in doc["rows"]]


def test_value_payloads_have_the_contracted_shapes(built_value) -> None:
    data, summary = built_value
    meta = json.loads((data / "value" / "meta.json").read_text(encoding="utf-8"))
    assert meta["components"][-2:] == ["Rating", "League"] and len(meta["model"]["weights"]) == V.NF + 1
    assert set(meta["replacement"]) >= set(V.ROLES) and meta["comps"]["premier-league"]["ppg"] > 0.5
    assert meta["windows"]["premier-league"]["open"] is False
    players = _rows(json.loads((data / "value" / "players.json").read_text(encoding="utf-8")))
    lines = _rows(json.loads((data / "value" / "lines.json").read_text(encoding="utf-8")))
    assert players and lines and summary["players"] == len(players)
    p = next(r for r in players if r["min"] >= 900)
    assert p["role"] in V.ROLES + ("DF", "MF", "FW") and len(p["c"]) == len(V.COMPONENTS_OUT)
    # GAR/90 is the rate above the role's replacement level; projections shrink toward it.
    assert abs(p["proj"]) <= abs(p["gar90"]) + 1e-9
    assert p["gar"] == pytest.approx(p["gar90"] * p["min"] / 90, abs=0.02)
    assert {l["comp"] for l in lines} == {"premier-league"}


def test_sample_floors_are_honoured(built_value) -> None:
    data, _ = built_value
    players = _rows(json.loads((data / "value" / "players.json").read_text(encoding="utf-8")))
    lines = _rows(json.loads((data / "value" / "lines.json").read_text(encoding="utf-8")))
    assert all(r["pct"] is None for r in players if r["min"] < V.REGULAR_MINUTES)
    assert all(r["pct"] is None for r in lines if r["min"] < 270)
    assert all(r["min"] >= 90 for r in lines)
    assert all(r["pct"] is None or 0 <= r["pct"] <= 100 for r in players + lines)


def test_club_files_grade_every_unit_against_the_league(built_value) -> None:
    data, summary = built_value
    files = sorted((data / "value" / "club").glob("*.json"))
    assert len(files) == summary["clubs"] == 20
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    for d in docs:
        assert [u["unit"] for u in d["units"]] == [u for u, _, _ in V.UNITS]
        assert len(d["strengths"]) == 3 and len(d["weaknesses"]) == 3 and set(d["targets"]) == set(d["weaknesses"])
        assert all(u["grade"] == VP.grade_of(u["pct"]) and 1 <= u["rank"] <= u["n"] == 20 for u in d["units"])
        assert d["window"]["open"] is False and d["league"] == "premier-league"
        for unit, ts in d["targets"].items():
            assert all(t["tid"] != d["tid"] for t in ts)
            assert all(a["gain90"] >= b["gain90"] for a, b in zip(ts, ts[1:]))
            assert all(t["age"] is not None and t["age"] <= VP.TARGET_MAX_AGE for t in ts)
    # Within a unit, the ranks are a permutation-with-ties of 1..20 and the best club gets the top grade.
    gk = sorted((u for d in docs for u in d["units"] if u["unit"] == "GK"), key=lambda u: u["rank"])
    assert gk[0]["rank"] == 1 and gk[0]["pct"] >= gk[-1]["pct"]


def test_moves_payload_is_written_even_without_transfer_history(built_value) -> None:
    from oddsmarkets.football.analytics import moves as MV
    data, _ = built_value
    doc = json.loads((data / "value" / "moves.json").read_text(encoding="utf-8"))
    assert doc["fields"] == MV.P_FIELDS and "meta" in doc
    meta = json.loads((data / "value" / "meta.json").read_text(encoding="utf-8"))
    assert "moves" in meta
    club = json.loads(next((data / "value" / "club").glob("*.json")).read_text(encoding="utf-8"))
    assert "movement" in club and "targets" in club


# ── the people payload is slimmer ────────────────────────────────────────────

def test_person_files_carry_no_season_line_and_no_crest_paths(tmp_path) -> None:
    import scripts.make_league_sample_store as sample
    import scripts.build_site_all as b
    from oddsmarkets.football.analytics.unified import Unified

    cfg = b.LEAGUES["premier-league"]
    store = sample.build(cfg, played_rounds=4)
    from oddsmarkets.football.analytics.players import add_percentiles, aggregate_players
    players = aggregate_players(store, cfg.registry)
    add_percentiles(players)
    entry = {"slug": "premier-league", "ok": True, "_players": players, "_fixtures": []}
    u = Unified(tmp_path, {}, entries=[entry])
    u.add_store("premier-league", store)
    u.finish()
    files = list((tmp_path / "people").glob("*.json"))
    assert files
    for f in files[:40]:
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert all("line" not in s for s in doc["seasons"])
        assert all("crest" not in t and t.get("national", True) is not False for t in doc["teams"].values())
