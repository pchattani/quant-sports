"""Builder D: the analytics layer on synthetic seasons (no network): payload keys, direction-aware percentiles with
sample floors and stabilisation shrinkage, isolated model failures."""
from __future__ import annotations

import pytest

from oddsmarkets.nfl import analytics as an

SEASON = 2024


@pytest.fixture
def synth(gridiron_roots):
    from oddsmarkets.nfl.analytics import people
    from oddsmarkets.nfl.models import synthetic_b
    pbp, truth = synthetic_b.write_season(gridiron_roots["raw"], season=SEASON, seed=1, n_teams=8, rounds=2)
    people.reset()
    an._STORES.clear()
    yield {"roots": gridiron_roots, "pbp": pbp, "truth": truth}
    people.reset()


def _ctx(season=SEASON, full=True, models=False):
    from oddsmarkets.nfl.analytics.context import SeasonContext
    return SeasonContext(season, full=full, current=True, use_models=models)


# ---------------------------------------------------------------------------------------------- percentiles

def test_percentiles_direction_aware():
    v = {"a": 1.0, "b": 2.0, "c": 3.0, "d": None}
    hi = an.percentiles(v)
    lo = an.percentiles(v, lower=True)
    assert hi == {"a": 0, "b": 50, "c": 100}
    assert lo == {"a": 100, "b": 50, "c": 0}
    assert an.percentiles({"x": 5.0}) == {"x": 50}
    ties = an.percentiles({"a": 1.0, "b": 1.0, "c": 2.0})
    assert ties["a"] == ties["b"] == 25 and ties["c"] == 100


def test_add_percentiles_floors_shrinkage_and_direction():
    good = an.metric("m", "M", "G", "3", den="att", k=100.0)
    bad = an.metric("s", "S", "G", "pct", lower=True, den="att", k=100.0)
    rows = {f"p{i}": {"values": {"m": 0.1 * i, "s": 0.01 * i}, "n": {"att": 400}} for i in range(10)}
    # a tiny-sample player with an extreme value: shrunk toward the mean, not placed at the top
    rows["hot"] = {"values": {"m": 5.0, "s": 0.0}, "n": {"att": 30}}
    # under the floor: no percentile at all
    rows["tiny"] = {"values": {"m": 9.0, "s": 0.0}, "n": {"att": 5}}
    an.add_percentiles(rows, [good, bad], [f"p{i}" for i in range(10)], floors={"att": 20})
    assert rows["p9"]["pct"]["m"] > rows["p0"]["pct"]["m"]
    assert rows["p0"]["pct"]["s"] > rows["p9"]["pct"]["s"]           # lower is better: the smallest rate ranks highest
    assert "m" not in rows["tiny"]["pct"]
    # shrunk value: (30 * 5 + 100 * 0.45) / 130 = 1.5 -> above the pool but by much less than raw 5.0 would suggest
    assert rows["hot"]["pct"]["m"] == 100
    sv = an.shrunk(5.0, 30, 100.0, 0.45)
    assert 1.4 < sv < 1.6


def test_stabilises_at_on_public_metric():
    m = an.metric("x", "X", "G", "3", den="att", k=30.0)
    pm = an.public_metric(m)
    assert pm["stabilises_at"] == 70.0 and pm["unit"] == "att"
    assert not any(k.startswith("_") for k in pm)


# ---------------------------------------------------------------------------------------------- catalogues

def test_players_catalogue_keys(synth):
    from oddsmarkets.nfl.analytics import players as PL
    ctx = _ctx()
    cat = PL.build(ctx)
    assert cat["ok"] and cat["season"] == SEASON
    for m in cat["metrics"]:
        assert {"key", "label", "group", "fmt", "lower", "scope", "desc", "stabilises_at"} <= set(m)
    groups = {r["group"] for r in cat["players"].values()}
    assert {"QB", "RB", "WR", "K", "P"} <= groups
    for pid, r in cat["players"].items():
        assert {"name", "team", "pos", "group", "age", "games", "qualified", "values", "pct", "pct_pos"} <= set(r), pid
        assert "n" not in r
        for k, v in r["pct"].items():
            assert 0 <= v <= 100
    qbs = {p: r for p, r in cat["players"].items() if r["group"] == "QB" and r["qualified"]}
    assert len(qbs) >= 6
    # direction: the QB with the highest EPA / dropback has the highest percentile on it (no sample differences here)
    best = max(qbs, key=lambda p: qbs[p]["values"]["epa_db"])
    assert qbs[best]["pct"]["epa_db"] == max(r["pct"].get("epa_db", -1) for r in qbs.values())
    # sack rate is lower-is-better
    lo = min(qbs, key=lambda p: qbs[p]["values"]["sack_rate"])
    hi = max(qbs, key=lambda p: qbs[p]["values"]["sack_rate"])
    if qbs[lo]["values"]["sack_rate"] < qbs[hi]["values"]["sack_rate"]:
        assert qbs[lo]["pct"]["sack_rate"] > qbs[hi]["pct"]["sack_rate"]
    assert cat["composite_source"] == "fallback"
    assert any(r["values"].get("composite") is not None for r in qbs.values())


def test_planted_qb_skill_ranks(synth):
    """The planted QB skill (completion logit) shows in CPOE: the best planted passer beats the worst."""
    from oddsmarkets.nfl.analytics import players as PL
    cat = PL.build(_ctx())
    T = synth["truth"]["teams"]
    skill = {v["qb"]: v["qb_skill"] for v in T.values()}
    cp = {p: cat["players"][p]["values"].get("cpoe") for p in skill if p in cat["players"]}
    best, worst = max(skill, key=skill.get), min(skill, key=skill.get)
    assert cp[best] is not None and cp[worst] is not None
    assert cp[best] > cp[worst]


def test_teams_fourth_leaders_lab_glossary(synth):
    from oddsmarkets.nfl.analytics import fourth as FD
    from oddsmarkets.nfl.analytics import leaders as LD
    from oddsmarkets.nfl.analytics import players as PL
    from oddsmarkets.nfl.analytics import season as SN
    from oddsmarkets.nfl.analytics import teams as TM
    ctx = _ctx()
    cat = PL.build(ctx)
    sched = SN.schedule(ctx, {}, {}, None)
    cards = sched["games"]
    assert cards and {"game_id", "week", "gtype", "kickoff", "home", "away", "hs", "as", "status", "qtr", "clock", "possession",
                      "down", "dist", "yl100", "model", "market", "line", "wp_home", "qbs", "weather"} <= set(cards[0])
    tms = TM.build(ctx, cat, None, cards)
    assert tms["ok"] and len(tms["teams"]) == 8
    t = next(iter(tms["teams"].values()))
    assert {"values", "rank", "record", "units", "history", "qbs", "schedule", "name", "colour", "division"} <= set(t)
    assert {"off_epa", "def_epa", "proe", "proe_neutral", "go_rate", "sec_per_play", "rating"} <= set(t["values"])
    # planted aggressiveness: the most aggressive coach goes for it more than the least (GOE over a league model)
    fd = FD.build(ctx)
    assert fd["ok"] and fd["cols"][0] == "game_id" and fd["rows"]
    T = synth["truth"]["teams"]
    goe = {r["team"]: r["go_rate"] for r in fd["coaches"]}
    hi = max(T, key=lambda k: T[k]["aggr"])
    lo = min(T, key=lambda k: T[k]["aggr"])
    assert goe[hi] > goe[lo]
    spl = SN.build(ctx, tms, None, cards)
    assert spl["ok"] and spl["standings"] and spl["draft"] and spl["sim"]["ok"] is False
    wk = SN.weeks(ctx, cards, tms)
    assert wk and all(v["games"] for v in wk.values())
    ld = LD.build(SEASON, cat, tms)
    assert ld["ok"] and "QB" in ld["players"] and ld["teams"]
    lab = LD.lab(SEASON, cat, tms)
    assert lab["groups"]["QB"]["cols"][:3] == ["pid", "name", "team"]
    gl = LD.glossary()
    assert gl["ok"] and all("stabilises_at" in e for g in gl["groups"] for e in g["entries"])
    aw = LD.awards(ctx, cat, None)
    assert aw["ok"] and aw["source"] == "ranking" and aw["awards"]["mvp"]["candidates"]


def test_game_page_blocks(synth):
    from oddsmarkets.nfl.analytics import games as GM
    ctx = _ctx()
    P = ctx.plays()
    gid = sorted(ctx.games)[0]
    g = ctx.games[gid]
    page = GM.build_page(ctx, g, P[P["game_id"] == gid], GM.card(ctx, g), None, None, {}, {}, None)
    assert page["ok"] and page["plays"]["cols"][:15] == GM.PLAY_COLS
    assert page["plays"]["rows"] and len(page["plays"]["rows"][0]) == len(page["plays"]["cols"])
    assert page["drives"]["rows"] and page["wp"]["rows"]
    assert sum(page["score"]["home"]) == g["hs"] and sum(page["score"]["away"]) == g["as"]
    assert {"home", "away"} <= set(page["box"]) and page["box"]["home"]["passing"]
    # a page is never downgraded: no plays on this machine -> the old page's play blocks are kept
    again = GM.build_page(ctx, g, None, GM.card(ctx, g), None, page, {}, {}, None)
    assert again["plays"] == page["plays"] and again["drives"] == page["drives"]


def test_model_failure_is_isolated(synth, monkeypatch):
    """Play- and player-level models that raise are recorded in model_errors; the catalogue still builds."""
    import sys
    import types
    from oddsmarkets.nfl.analytics import players as PL

    def boom(*a, **k):
        raise RuntimeError("planted failure")
    for name in ("ep", "player_value"):
        fake = types.ModuleType(f"oddsmarkets.nfl.models.{name}")
        fake.MODEL_VERSION = "planted"
        fake.for_season = boom
        monkeypatch.setitem(sys.modules, f"oddsmarkets.nfl.models.{name}", fake)
    ctx = _ctx(models=True)
    cat = PL.build(ctx)
    assert cat["ok"] and cat["players"]
    assert "planted failure" in ctx.model_errors.get("ep", "")
    assert "planted failure" in ctx.model_errors.get("player_value", "")


def test_careers_and_history(synth):
    from oddsmarkets.nfl.analytics import careers as CR
    from oddsmarkets.nfl.analytics import history as HS
    from oddsmarkets.nfl.analytics import players as PL
    ctx = _ctx()
    cat = PL.build(ctx)
    rows = CR.reduce_cat(cat, SEASON)
    blocks = CR.current_blocks(ctx, cat)
    written = {}
    idx = CR.write_careers(lambda rel, p: written.__setitem__(rel, p), {SEASON: rows}, blocks, None, SEASON)
    assert idx and written
    pid, entry = next(iter(idx.items()))
    assert len(entry) == 5 and entry[3] == entry[4] == SEASON
    f = written[f"players/{pid}.json"]
    assert {"id", "name", "pos", "college", "draft", "seasons", "current", "similar"} <= set(f)
    qb = next(p for p, r in cat["players"].items() if r["group"] == "QB" and r["qualified"])
    assert written[f"players/{qb}.json"]["current"]["log"]
    assert written[f"players/{qb}.json"]["current"]["charts"].get("qb_grid") is not None
    h = HS.build({SEASON: rows}, {SEASON: HS.league_summary(ctx)})
    assert h["ok"] and h["season_leaders"] and h["career_leaders"] and h["league"]


def test_careers_skip_placeholder_ids(gridiron_roots):
    """Play-by-play's placeholder id "0" (no player recorded) pools unknown players: no career file, no index entry."""
    from oddsmarkets.nfl.analytics import careers as CR
    from oddsmarkets.nfl.analytics import people
    people.reset()
    row = {"season": 1999, "team": "PHI", "group": "DEF", "pos": "DEF", "games": 8, "values": {"tackles": 30}}
    rows = {1999: {"0": dict(row, name="0"), "00-0000000": dict(row), "00-0012345": dict(row, name="A Defender")}}
    written = {}
    idx = CR.write_careers(lambda rel, p: written.__setitem__(rel, p), rows, {}, None, 1999)
    assert set(idx) == {"00-0012345"}
    assert set(written) == {"players/00-0012345.json"}
    assert not CR.real_pid("0") and not CR.real_pid(None) and not CR.real_pid("nan") and CR.real_pid("00-0036355")
    people.reset()
