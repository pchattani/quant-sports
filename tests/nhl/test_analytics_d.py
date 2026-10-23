"""Builder D (The Quant Rink analytics layer): synthetic seasons, no network, no builder B / C models."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from rink_synth import make_season  # noqa: E402

from oddsmarkets.nhl import analytics as an  # noqa: E402


@pytest.fixture
def rink(tmp_path, monkeypatch):
    data, raw, cache = tmp_path / "data", tmp_path / "raw", tmp_path / "raw" / "cache"
    monkeypatch.setenv("RINK_DATA", str(data))
    monkeypatch.setenv("RINK_RAW", str(raw))
    monkeypatch.setenv("RINK_CACHE", str(cache))
    an._STORES.clear()
    make_season(data, raw, 20252026, seed=3)
    return {"data": data, "raw": raw, "cache": cache}


def ctx_for(season=20252026, **kw):
    from oddsmarkets.nhl.analytics.context import SeasonContext
    return SeasonContext(season, use_models=False, today=date(2026, 10, 1), **kw)


# ---------------------------------------------------------------------------------------------- percentiles

def test_percentiles_direction_aware():
    v = {"a": 1.0, "b": 2.0, "c": 3.0, "d": None}
    hi = an.percentiles(v)
    lo = an.percentiles(v, lower=True)
    assert hi == {"a": 0, "b": 50, "c": 100}
    assert lo == {"a": 100, "b": 50, "c": 0}
    assert an.percentiles({"x": 5}) == {"x": 50}
    t = an.percentiles({"a": 1, "b": 1, "c": 2})
    assert t["a"] == t["b"] == 25 and t["c"] == 100


def test_add_percentiles_floor_shrink_and_direction():
    mets = [an.metric("ga60", "GA/60", "g", "p60", lower=True, den="toi5", k=600.0),
            an.metric("gf60", "GF/60", "g", "p60", den="toi5", k=600.0)]
    rows = {}
    for i in range(10):
        rows[str(i)] = {"values": {"ga60": 2.0 + 0.1 * i, "gf60": 2.0 + 0.1 * i}, "n": {"toi5": 60000.0}}
    rows["hot"] = {"values": {"ga60": 0.5, "gf60": 5.0}, "n": {"toi5": 100.0}}          # tiny sample: shrunk hard
    rows["tiny"] = {"values": {"ga60": 0.1, "gf60": 9.0}, "n": {"toi5": 10.0}}          # under the floor
    ref = [str(i) for i in range(10)]
    an.add_percentiles(rows, mets, ref, {p: "F" for p in rows}, {"toi5": 50.0})
    assert rows["0"]["pct"]["ga60"] > rows["9"]["pct"]["ga60"]                          # lower is better
    assert rows["9"]["pct"]["gf60"] > rows["0"]["pct"]["gf60"]
    assert "ga60" not in rows["tiny"]["pct"]
    # 100 s of a 5.0 rate shrunk toward the mean with k = 600 s: not top of the pool
    assert rows["hot"]["pct"]["gf60"] < 100
    assert all(0 <= x <= 100 for r in rows.values() for x in r["pct"].values())
    assert rows["5"]["pct_pos"]                                                          # position comparison present


def test_count_metrics_need_the_games_floor():
    """Counting stats and value (no denominator) are not ranked off one game: they need floors["gp"] games, and the
    pool they are placed against is the players past that floor."""
    mets = [an.metric("g", "Goals", "s", "int"), an.metric("gar", "Rink value", "v", "1"),
            an.metric("g60", "G/60", "s", "p60", den="toi", k=600.0)]
    rows = {str(i): {"values": {"g": i, "gar": 0.5 * i, "g60": 1.0 + 0.1 * i}, "n": {"gp": 10.0, "toi": 60000.0}} for i in range(10)}
    rows["one"] = {"values": {"g": 2, "gar": 0.1, "g60": 6.8}, "n": {"gp": 1.0, "toi": 1062.0}}
    rows["early"] = {"values": {"g": 0, "gar": 0.0, "g60": 0.0}, "n": {"gp": 1.0, "toi": 900.0}}
    ref = list(rows)                                   # an early-season qualified pool takes nearly everyone
    an.add_percentiles(rows, mets, ref, {p: "F" for p in rows}, {"gp": 5.0, "toi": 6000.0}, default_den="gp")
    assert "g" not in rows["one"]["pct"] and "gar" not in rows["one"]["pct"]     # below the games floor
    assert "g60" not in rows["one"]["pct"]                                         # below the minutes floor
    assert rows["9"]["pct"]["g"] == 95 and rows["0"]["pct"]["g"] == 5            # (below + half ties) / 10
    # the one-game rows do not sit in the pool: 9 is the best of the ten past the floor
    assert rows["5"]["pct"]["gar"] > 50
    # without default_den (the old behaviour) one game's goals were ranked
    rows2 = {k: {"values": dict(v["values"]), "n": dict(v["n"])} for k, v in rows.items()}
    an.add_percentiles(rows2, mets, ref, {p: "F" for p in rows2}, {"gp": 5.0, "toi": 6000.0})
    assert "g" in rows2["one"]["pct"]


def test_metric_min_floor_is_fixed_and_leaves_the_pool():
    """A metric's "_min" (skaters' Value group: VALUE_PCT_MIN_TOI minutes) holds rows below it out of the
    percentile and out of the pool, whatever the prorated floors say."""
    mets = [dict(an.metric("gar", "Rink value", "Value", "1"), _min=("toi", 12000.0)), an.metric("g", "Goals", "s", "int")]
    rows = {str(i): {"values": {"gar": 0.1 * i, "g": i}, "n": {"gp": 10.0, "toi": 15000.0}} for i in range(5)}
    rows.update({f"x{i}": {"values": {"gar": 0.05 * i, "g": i}, "n": {"gp": 10.0, "toi": 9000.0}} for i in range(5)})
    an.add_percentiles(rows, mets, list(rows), {p: "F" for p in rows}, {"gp": 5.0}, default_den="gp")
    assert all("gar" not in rows[f"x{i}"]["pct"] and "g" in rows[f"x{i}"]["pct"] for i in range(5))
    assert rows["4"]["pct"]["gar"] == 90 and rows["0"]["pct"]["gar"] == 10    # (below + half ties) / 5
    assert "_min" not in an.public_metric(mets[0])


def test_finish_applies_the_games_floor_by_default():
    mets = [an.metric("p", "Points", "s", "int")]
    rows = {str(i): {"values": {"p": i}, "n": {"gp": 6.0}} for i in range(6)}
    rows["x"] = {"values": {"p": 3}, "n": {"gp": 1.0}}
    an.finish(rows, mets, list(rows), {p: "F" for p in rows}, {"gp": 5.0})
    assert "p" not in rows["x"]["pct"] and rows["5"]["pct"]["p"] == 92                 # 5.5 / 6 of the six past the floor
    assert "n" not in rows["x"]


def test_log_result_from_each_side():
    from oddsmarkets.nhl.analytics.careers import log_result
    g = {"status": "final", "home": "CAR", "away": "FLA", "hs": 0, "as": 1, "ot": True, "so": False}
    assert log_result(g, "FLA") == "W 1-0 (OT)"
    assert log_result(g, "CAR") == "OTL 0-1 (OT)"
    assert log_result({"status": "final", "home": "BOS", "away": "NYR", "hs": 3, "as": 0}, "NYR") == "L 0-3"
    assert log_result({"status": "final", "home": "BOS", "away": "NYR", "hs": 4, "as": 3, "so": True}, "BOS") == "W 4-3 (SO)"
    assert log_result({"status": "scheduled", "home": "BOS", "away": "NYR"}, "BOS") is None


# ---------------------------------------------------------------------------------------------- normalisation

def test_normalise_events_builder_a_columns():
    from oddsmarkets.nhl.analytics.context import normalise_events
    raw = pd.DataFrame([
        {"game_id": 2025020001, "event_id": 5, "period": 1, "sec": 10.0, "type": "faceoff", "team": "BOS", "x": 0.0, "y": 0.0,
         "zone": "N", "player1": 11, "player2": 21, "sit": "1551", "home_s1": 11, "home_s2": 12, "home_s3": 13, "home_s4": 14,
         "home_s5": 15, "home_g": 1, "away_s1": 21, "away_s2": 22, "away_s3": 23, "away_s4": 24, "away_s5": 25, "away_g": 2,
         "shooter": None, "score_home": 0, "score_away": 0},
        {"game_id": 2025020001, "event_id": 6, "period": 1, "sec": 30.0, "type": "blocked-shot", "team": "BOS", "x": 60.0, "y": 5.0,
         "zone": "O", "shooter": 12, "player1": 12, "player2": 24, "sit": "1451", "home_s1": 11, "home_s2": 12, "home_s3": 13,
         "home_s4": 14, "home_s5": 15, "home_g": 1, "away_s1": 21, "away_s2": 22, "away_s3": 23, "away_s4": 24, "away_g": 2,
         "score_home": 0, "score_away": 0}])
    for c in [f"away_s{i}" for i in range(5, 7)] + ["home_s6", "away_s6"]:
        raw[c] = raw.get(c)
    ev = normalise_events(raw, {"2025020001": {"home": "BOS", "away": "TOR"}})
    f, b = ev.iloc[0], ev.iloc[1]
    assert f["type"] == "FAC" and f["p1"] == 11 and f["p2"] == 21 and f["state"] == "5v5"
    assert b["type"] == "BLOCK" and b["p1"] == 12 and b["p2"] == 24 and b["st"] == "PP" and b["state"] == "5v4"
    assert ev["idx"].tolist() == [0.0, 1.0] and ev["game_id"].iloc[0] == "2025020001"
    assert b["dist"] == pytest.approx(np.hypot(29, 5))


def test_tables_consistency(rink):
    from oddsmarkets.nhl.analytics import tables
    c = ctx_for()
    T = tables.tables(c)
    pg, tg, st = T["pg"], T["tg"], T["st"]
    assert len(pg) and len(tg) and len(st)
    # on-ice: every 5v5 attempt is "for" for five skaters and "against" for five
    assert pg["cf_5v5"].sum() == pytest.approx(pg["ca_5v5"].sum())
    assert pg["cf_5v5"].sum() == pytest.approx(5 * tg["cf_5v5"].sum())
    # skater TOI = stint duration x skaters on ice
    n = st["n_h"].to_numpy() + st["n_v"].to_numpy()
    assert pg["toi"].sum() == pytest.approx(float((st["dur"].to_numpy() * n).sum()))
    # goals: individual = team
    assert pg["g"].sum() == pytest.approx(tg["gf_all"].sum())
    # every skater-game row sits with the team he skated for (never the opponent through a hit taken or a block)
    team_of = {float(p): v["team"] for p, v in c.players.items()}
    assert (pg["pid"].map(team_of) == pg["team"]).all()


def test_teammate_block_not_a_block():
    from oddsmarkets.nhl.analytics import box
    from oddsmarkets.nhl.analytics.context import normalise_events
    base = {"game_id": 2025020001, "period": 1, "type": "blocked-shot", "team": "BOS", "x": 60.0, "y": 0.0, "sit": "1551",
            "home_g": 1, "away_g": 2}
    for i in range(5):
        base[f"home_s{i + 1}"] = 11 + i
        base[f"away_s{i + 1}"] = 21 + i
    raw = pd.DataFrame([{**base, "event_id": 1, "sec": 5.0, "player1": 11, "player2": 21, "reason": None},
                        {**base, "event_id": 2, "sec": 9.0, "player1": 12, "player2": 13, "reason": "teammate-blocked"}])
    ev = normalise_events(raw, {"2025020001": {"home": "BOS", "away": "TOR"}})
    ind = box.individual(ev).set_index("pid")
    assert ind.loc[21.0, "blocks"] == 1 and ind.loc[21.0, "team"] == "TOR"
    assert 13.0 not in ind.index or ind.loc[13.0, "blocks"] == 0


# ---------------------------------------------------------------------------------------------- catalogues

def test_skater_catalogue(rink):
    from oddsmarkets.nhl.analytics import skaters
    cat = skaters.build(ctx_for())
    assert cat["ok"] and cat["kind"] == "skater"
    assert len(cat["metrics"]) >= 110
    for m in cat["metrics"]:
        assert set(("key", "label", "group", "fmt", "lower", "scope", "desc", "stabilises_at")) <= set(m)
    P = cat["players"]
    assert len(P) == 6 * 18
    r = next(iter(P.values()))
    assert set(("name", "team", "pos", "age", "gp", "toi", "qualified", "values", "pct", "pct_pos")) <= set(r)
    assert "n" not in r
    assert set(r["values"]) == {m["key"] for m in cat["metrics"]}
    # direction: the lowest CA/60 among the qualified has the best CA/60 percentile
    q = {p: v for p, v in P.items() if v["qualified"] and v["values"]["ca60"] is not None and "ca60" in v["pct"]}
    best = min(q, key=lambda p: q[p]["values"]["ca60"])
    worst = max(q, key=lambda p: q[p]["values"]["ca60"])
    assert q[best]["pct"]["ca60"] > q[worst]["pct"]["ca60"]
    # xG present (fallback) and summing to goals over the season's unblocked attempts
    assert cat["xg_source"] == "fallback"
    assert sum(v["values"]["ixg"] or 0 for v in P.values()) == pytest.approx(sum(v["values"]["g"] for v in P.values()), rel=0.05)
    # stabilisation point in minutes for a time metric: 0.7 k / 0.3 with k in seconds (the fitted k when the
    # stabilisation fit is committed, else this layer's 500 minutes)
    xgf = next(m for m in cat["metrics"] if m["key"] == "xgf_pct")
    priv = next(m for m in skaters.METRICS if m["key"] == "xgf_pct")
    k = an.stab_k(priv)
    assert xgf["stabilises_at"] == pytest.approx(round(k * 0.7 / 0.3 / 60), abs=1) and xgf["unit"] == "5v5 minutes"
    assert 100 <= xgf["stabilises_at"] <= 3000


def test_goalie_catalogue_identities(rink):
    from oddsmarkets.nhl.analytics import goalies
    cat = goalies.build(ctx_for())
    assert cat["ok"]
    for p, r in cat["players"].items():
        v = r["values"]
        if v["gsax"] is None:
            continue
        parts = [v[k] for k in ("gsax_low", "gsax_med", "gsax_high") if v[k] is not None]
        assert sum(parts) == pytest.approx(v["gsax"], abs=0.05)
        assert v["w"] + v["l"] + v["otl"] <= v["gp"]
        assert v["fa"] >= v["sa"]                         # unblocked attempts faced: shots on goal plus misses
    m = {x["key"]: x for x in cat["metrics"]}
    assert m["gaa"]["lower"] and not m["sv_pct"]["lower"]


def test_teams_and_season(rink):
    from oddsmarkets.nhl.analytics import season, skaters, teams
    c = ctx_for()
    sk = skaters.build(c)
    tp = teams.build(c, sk, None, None, [])
    assert tp["ok"] and set(tp["teams"]) == {"BOS", "TOR", "MTL", "NYR", "EDM", "VAN"}
    t = tp["teams"]["BOS"]
    g = tp["grid"]
    assert len(t["shot_map"]["for"]["att"]) == g["nx"] * g["ny"]
    assert t["lines"]["forwards"] and len(t["lines"]["forwards"][0]["ids"]) == 3
    assert t["lines"]["pairs"] and len(t["lines"]["pairs"][0]["ids"]) == 2
    assert t["units"]["source"] == "counts" and "pct" in t["units"]
    u = t["units"]
    assert u["gd_g"] == pytest.approx(u["gf_g"] - u["ga_g"], abs=0.002) and "gd_g" in u["pct"]
    sp = season.build(c, tp, None)
    rows = sp["standings"]["rows"]
    assert len(rows) == 6 and all(r["pts"] == 2 * r["w"] + r["otl"] for r in rows)
    assert sum(r["w"] for r in rows) == sum(r["gp"] for r in rows) // 2
    assert rows[0]["pts"] >= rows[-1]["pts"]
    assert sp["sim"]["ok"] is False


def test_game_page_and_card(rink):
    from oddsmarkets.nhl.analytics import games, tables
    c = ctx_for()
    T = tables.tables(c)
    gid = sorted(c.games)[0]
    g = c.games[gid]
    card = games.card(g, {"p_home": 0.55, "p_reg_home": 0.45, "p_ot": 0.22, "total": 6.1, "puck_line_home": 0.3}, None, {"home": 2.1, "away": 1.9})
    for k in ("game_id", "date", "start", "status", "period", "clock", "home", "away", "hs", "as", "goalies", "model", "market", "line",
              "wp_home", "xg"):
        assert k in card
    assert card["market"]["sources"] == ["line"] and 0 < card["market"]["p_home"] < 1
    ev = T["ev"]
    sel = lambda df: df[df["game_id"] == gid]  # noqa: E731
    page = games.build_page(c, g, sel(ev), sel(T["st"]), sel(T["pg"]), sel(T["gg"]), card, {"model": {"p_home": 0.55, "total": 6.0}}, None, T["pos"])
    assert page["ok"]
    assert page["shots"]["cols"] == ["period", "sec", "team", "player", "x", "y", "type", "shot_type", "xg", "goal", "strength"]
    assert page["xg_race"]["rows"][0] == [0, 0.0, 0.0, None]
    assert page["wp"]["source"] == "poisson" and page["wp"]["series"][-1][1] in (0.0, 1.0)
    assert set(page["box"]["skaters"]) == {g["home"], g["away"]}
    assert len(page["awards"]["stars"]) == 3
    goals = sum(r[3] for t in page["box"]["skaters"].values() for r in t)
    assert goals == g["hs"] + g["as"] - (1 if g.get("ot") else 0) or goals == g["hs"] + g["as"]
    # never downgrade: without events the old page's event blocks are kept
    kept = games.build_page(c, g, None, None, None, None, card, None, page, T["pos"])
    assert kept["shots"] == page["shots"] and kept["kept_from"] == page["updated_at"]


def test_wp_poisson_monotone():
    from oddsmarkets.nhl.analytics.games import wp_poisson
    assert wp_poisson(1, 600, 3, 3) > wp_poisson(0, 600, 3, 3) > wp_poisson(-1, 600, 3, 3)
    assert wp_poisson(0, 3600, 3, 3) == pytest.approx(0.5, abs=1e-6)
    assert wp_poisson(1, 0, 3, 3) == 1.0


def test_glossary_history_careers(rink):
    from oddsmarkets.nhl.analytics import careers, glossary, goalies, history, skaters
    gl = glossary.build()
    ents = [e for g in gl["groups"] for e in g["entries"]]
    assert all("stabilises_at" in e for e in ents)
    assert any(e["stabilises_at"] for e in ents)
    h = history.build({20252026: {"champion": "BOS", "finalist": "EDM", "leaders": {"p": {"id": "1", "value": 100}}}},
                      {"BOS": "Boston Bruins", "EDM": "Edmonton Oilers"})
    ch = {r["season"]: r for r in h["champions"]}
    assert ch[19171918]["champion"] == "Toronto Arenas" and ch[19181919]["champion"] is None
    assert ch[20242025]["champion"] == "Florida Panthers"
    assert ch[20252026]["champion"] == "Boston Bruins" and ch[20252026]["source"] == "store"
    c = ctx_for()
    sk, gk = skaters.build(c), goalies.build(c)
    rows = {**careers.reduce_cat(gk, 20252026, "goalie"), **careers.reduce_cat(sk, 20252026, "skater")}
    blocks = careers.current_blocks(c, sk, gk)
    written = {}
    idx = careers.write_careers(lambda rel, d: written.__setitem__(rel, d), {20252026: rows}, blocks, lambda p: None, 20252026, c.players)
    assert len(idx) == len(rows) == 6 * 20
    doc = written[f"players/{next(p for p in sk['players'])}.json"]
    for k in ("id", "name", "pos", "shoots", "dob", "height", "weight", "seasons", "current", "similar"):
        assert k in doc
    for k in ("log", "shots", "onice", "rapm", "linemates", "deployment", "projection"):
        assert k in doc["current"], k
    assert doc["similar"] and len(doc["similar"][0]) == 4
    # unchanged content is not rewritten
    written2 = {}
    careers.write_careers(lambda rel, d: written2.__setitem__(rel, d), {20252026: rows}, blocks,
                          lambda p: written.get(f"players/{p}.json"), 20252026, c.players)
    assert not written2


def test_xg_fallback_probabilities(rink):
    c = ctx_for()
    ev = c.events()
    f = ev["type"].isin(["GOAL", "SHOT", "MISS"])
    x = ev.loc[f, "xg"]
    assert x.notna().all() and (x > 0).all() and (x < 1).all()
    assert x.sum() == pytest.approx((ev["type"] == "GOAL").sum(), rel=0.02)
    assert ev.loc[~f, "xg"].isna().all()


def test_markets_payload_shapes(rink):
    """Builder C's futures shapes (TITLE / BINARY / per-conference dicts / points ladders) against a simulation."""
    from oddsmarkets.nhl.analytics import season
    c = ctx_for()
    sim = {"ok": True, "teams": {t: {"p_cup": 0.1, "p_conf": 0.2, "p_div": 0.3, "p_pres": 0.05, "p_playoffs": 0.6,
                                     "p_points_ge": {90: 0.4}, "points_dist": {85: 0.5, 95: 0.5}} for t in c.teams}}
    mk = {"futures": {"champion": {"available": True, "probs": {"BOS": 0.15}, "by_source": {"kalshi": {}}},
                      "conference": {"Eastern": {"available": True, "probs": {"BOS": 0.3}}, "Western": {"available": True, "probs": {"EDM": 0.4}}},
                      "playoffs": {"available": True, "probs": {"BOS": 0.7}},
                      "points": {"BOS": {"kalshi": {"ladder": {90: 0.5}}}}}}
    p = season.markets_payload(c, sim, None, [], mk)
    cup = {r["team"]: r for r in p["futures"]["cup"]}
    assert cup["BOS"]["market"] == 0.15 and cup["BOS"]["edge"] == pytest.approx(-0.05)
    conf = {r["team"]: r for r in p["futures"]["conference"]}
    assert conf["EDM"]["market"] == 0.4
    pts = p["points"][0]
    assert pts["points"] == 90 and pts["model"] == 0.4 and pts["edge"] == pytest.approx(-0.1)


def test_player_name_falls_back_to_stats_reports(rink):
    """A player the store's roster pass missed (a call-up) takes his name from the stats reports, not his id."""
    import gzip
    d = rink["raw"] / "stats" / "20252026"
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / "skater_summary_2.json.gz", "wt", encoding="utf-8") as fh:
        json.dump([{"playerId": 8499999, "skaterFullName": "Called Up"}], fh)
    c = ctx_for()
    c.players.pop("8499999", None)
    assert c.player_name("8499999") == "Called Up"
    assert c.player_name("8400000") is None
    assert c.player_name(None) is None


def test_careers_name_prefers_a_real_name_over_the_id():
    from oddsmarkets.nhl.analytics import careers
    rows = {20242025: {"8499999": {"season": 20242025, "kind": "skater", "team": "NJD", "name": "Called Up", "pos": "D", "values": {}}},
            20252026: {"8499999": {"season": 20252026, "kind": "skater", "team": "NJD", "name": "8499999", "pos": "D", "values": {}}}}
    written = {}
    idx = careers.write_careers(lambda rel, d: written.__setitem__(rel, d), rows, {}, lambda p: None, 20252026, {})
    assert idx["8499999"][0] == "Called Up"


def test_box_rebound_rush_flags_from_the_sequence():
    """reb60 / rush60 were 0 for everyone: the events table has no rebound / rush columns (only the xG model built
    them). box derives them with the model's rule, reading the feed's order within a second (`sort`)."""
    from oddsmarkets.nhl.analytics import box
    from oddsmarkets.nhl.analytics.context import normalise_events
    base = {"game_id": 2025020001, "period": 1, "sit": "1551", "home_g": 1, "away_g": 2, "y": 0.0}
    for i in range(5):
        base[f"home_s{i + 1}"] = 11 + i
        base[f"away_s{i + 1}"] = 21 + i
    rows = [
        # faceoff won in the neutral zone, shot 2 s later: a rush attempt
        {"event_id": 1, "sort": 1, "sec": 10.0, "type": "faceoff", "team": "BOS", "zone": "N", "x": 0.0, "player1": 11, "player2": 21},
        {"event_id": 2, "sort": 2, "sec": 12.0, "type": "shot-on-goal", "team": "BOS", "zone": "O", "x": 60.0, "player1": 12},
        # a second BOS attempt 2 s after the first: a rebound (not a rush: the previous event is in the offensive zone)
        {"event_id": 3, "sort": 3, "sec": 14.0, "type": "missed-shot", "team": "BOS", "zone": "O", "x": 70.0, "player1": 13},
        # TOR attempt 1 s after a BOS one: not a rebound (the other team's attempt), but a rush: BOS's offensive zone
        # is TOR's defensive zone
        {"event_id": 4, "sort": 4, "sec": 15.0, "type": "shot-on-goal", "team": "TOR", "zone": "O", "x": 60.0, "player1": 22},
        # feed order within a second: event_id 6 comes first in the feed (sort 5), so the shot (event_id 5, sort 6)
        # follows BOS's blocked attempt and is a rebound
        {"event_id": 6, "sort": 5, "sec": 40.0, "type": "blocked-shot", "team": "BOS", "zone": "O", "x": 50.0, "player1": 14, "player2": 23},
        {"event_id": 5, "sort": 6, "sec": 40.0, "type": "shot-on-goal", "team": "BOS", "zone": "O", "x": 65.0, "player1": 15},
    ]
    raw = pd.DataFrame([{**base, **r} for r in rows])
    ev = normalise_events(raw, {"2025020001": {"home": "BOS", "away": "TOR"}})
    reb, rush = box.rebound_rush(ev)
    by = dict(zip(ev["event_id"].astype(int), zip(reb, rush)))
    assert by[2] == (0.0, 1.0)
    assert by[3] == (1.0, 0.0)
    assert by[4] == (0.0, 1.0)
    assert by[5] == (1.0, 0.0)
    ind = box.individual(ev).set_index("pid")
    assert ind.loc[12.0, "rush_att"] == 1 and ind.loc[13.0, "reb_att"] == 1 and ind.loc[15.0, "reb_att"] == 1
    # a table that carries its own flags keeps them
    r2, u2 = box.rebound_rush(ev.assign(rebound=0.0, rush=0.0))
    assert r2.sum() == 0 and u2.sum() == 0


def test_box_rebound_rush_match_the_xg_features(rink):
    """On a whole synthetic season the box flags equal the xG model's own rebound / rush features shot for shot."""
    from oddsmarkets.nhl.analytics import box, context
    from oddsmarkets.nhl.models import _io, xg
    s = 20252026
    raw = context.read_parquet(an.events_path(s), exclude=context.EV_SKIP)
    ev = box.playable(context.normalise_events(raw, None))
    reb, rush = box.rebound_rush(ev)
    att, _ = xg.attempts(_io.events(s), s)
    k = pd.DataFrame({"game_id": ev["game_id"].astype("int64").to_numpy(), "idx": ev["idx"].to_numpy(), "reb_box": reb,
                      "rush_box": rush})
    m = att[["game_id", "idx", "rebound", "rush"]].merge(k, on=["game_id", "idx"], how="inner")
    assert len(m) == len(att) > 500
    assert m["rebound"].sum() > 0 and m["rush"].sum() > 0
    assert (m["reb_box"] == m["rebound"]).all() and (m["rush_box"] == m["rush"]).all()


def test_similar_spec_recipe_weighted_within_group():
    """METRICS_SPEC: hockey.json group features, z within group, weights = yoy r floored at 0.2, k = 6, qualified only."""
    from oddsmarkets.common import similar as SIM
    from oddsmarkets.nhl.analytics import careers
    feats = SIM.group_config("hockey", "forwards")["features"]
    rows = {}
    for i in range(10):
        rows[f"f{i}"] = {"name": f"F{i}", "team": "BOS", "group": "F", "qualified": True, "sim": {k: float(i) for k in feats}}
        rows[f"d{i}"] = {"name": f"D{i}", "team": "TOR", "group": "D", "qualified": True, "sim": {"gar_60": float(i)}}
    rows["x"] = {"name": "X", "team": "BOS", "group": "F", "qualified": False, "sim": {k: 4.0 for k in feats}}
    sim = careers.similar(rows, "skater")
    nb = sim["f4"]
    assert len(nb) == 6 and all(p.startswith("f") for p, *_ in nb) and "x" not in [p for p, *_ in nb]
    assert {nb[0][0], nb[1][0]} == {"f3", "f5"} and nb[0][3] <= nb[-1][3]
    assert all(p.startswith("d") for p, *_ in sim["d0"])
    assert set(careers.sim_keys("skater")) >= set(feats)
