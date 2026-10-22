"""Builder E's analytics layer on synthetic data: catalogue payload keys (PAYLOADS.md), direction-aware percentiles
with sample floors and shrinkage, model isolation, model values mapped into the catalogues, game pages, the glossary,
and the Retrosheet notice in history payloads. No network."""
from __future__ import annotations

import pandas as pd
import pytest

from oddsmarkets.baseball import analytics as an

METRIC_KEYS = {"key", "label", "group", "fmt", "lower", "scope", "desc", "stabilises_at"}


def test_percentiles_are_direction_aware():
    assert an.percentiles({"a": 1, "b": 2, "c": 3}) == {"a": 0, "b": 50, "c": 100}
    assert an.percentiles({"a": 1, "b": 2, "c": 3}, lower=True) == {"a": 100, "b": 50, "c": 0}
    assert an.percentiles({"a": 5}) == {"a": 50}
    assert an.percentiles({"a": None, "b": 1}) == {"b": 50}


def test_add_percentiles_floors_shrinkage_and_roles():
    m_hi = an.metric("woba", "wOBA", "T", "3", den="pa", k=300)
    m_lo = an.metric("k_pct", "K%", "T", "pct", lower=True, den="pa", k=60)
    rows = {}
    for i in range(20):
        rows[f"r{i}"] = {"values": {"woba": 0.300 + 0.005 * i, "k_pct": 0.30 - 0.005 * i}, "n": {"pa": 500}}
    rows["hot"] = {"values": {"woba": 0.450, "k_pct": 0.05}, "n": {"pa": 60}}       # small-sample outlier
    rows["tiny"] = {"values": {"woba": 0.900, "k_pct": 0.0}, "n": {"pa": 10}}       # under the floor
    ref = [f"r{i}" for i in range(20)]
    role = {p: ("C" if i % 2 else "SS") for i, p in enumerate(ref)} | {"hot": "C", "tiny": "C"}
    an.add_percentiles(rows, [m_hi, m_lo], ref, role, floors={"pa": 50}, min_role=5)
    # best raw values: the top regular gets the top percentile; lower-is-better metric flips
    assert rows["r19"]["pct"]["woba"] > rows["r0"]["pct"]["woba"]
    assert rows["r19"]["pct"]["k_pct"] > rows["r0"]["pct"]["k_pct"]
    # under the sample floor: no percentile
    assert "woba" not in rows["tiny"]["pct"]
    # shrinkage: 60 PA of .450 (above every regular's raw value) is placed as (60 x .450 + 300 m) / 360 against the
    # regulars' own shrunk values (500 PA each), so it does not top the pool
    mean = sum(0.300 + 0.005 * i for i in range(20)) / 20
    hot = (60 * 0.45 + 300 * mean) / 360
    best = (500 * 0.395 + 300 * mean) / 800
    assert hot < best
    assert rows["hot"]["pct"]["woba"] < 100
    assert set(rows["r1"]["pct_role"]) == {"woba", "k_pct"}


def test_metric_public_shape_and_stabilisation():
    from oddsmarkets.baseball.analytics import fielders, hitters, pitchers, teams, umpires
    for mets in (hitters.METRICS, pitchers.METRICS, fielders.METRICS, teams.METRICS, umpires.METRICS):
        keys = [m["key"] for m in mets]
        assert len(keys) == len(set(keys))
        for m in mets:
            pm = an.public_metric(m)
            assert METRIC_KEYS <= set(pm)
            assert not any(k.startswith("_") for k in pm)
    assert len(hitters.METRICS) >= 150
    assert len(pitchers.METRICS) >= 140
    # a metric shrunk with stabilise.py's k carries its 0.7-reliability point
    k_pct = next(m for m in hitters.METRICS if m["key"] == "k_pct")
    assert an.public_metric(k_pct)["stabilises_at"] > 0


@pytest.fixture
def ctx(synthetic_world):
    from oddsmarkets.baseball.analytics.context import SeasonContext
    return SeasonContext("mlb", 2025, full=False, use_models=False)


def test_hitters_and_pitchers_catalogues(ctx):
    from oddsmarkets.baseball.analytics import hitters, pitchers
    h = hitters.build(ctx)
    p = pitchers.build(ctx)
    for cat, nkey in ((h, "pa"), (p, "bf")):
        assert cat["ok"] is True
        assert all(METRIC_KEYS <= set(m) for m in cat["metrics"])
        assert cat["players"]
        r = next(iter(cat["players"].values()))
        assert {"name", "team", "pos", "age", nkey, "qualified", "values", "pct", "pct_role"} <= set(r)
        assert set(r["values"]) == {m["key"] for m in cat["metrics"]}
    assert "arsenal" in p and p["arsenal"]
    some = next(a for a in p["arsenal"].values() if a)
    assert {"n", "usage", "velo", "whiff"} <= set(next(iter(some.values())))
    # model metrics are None (models disabled), traditional ones are filled
    any_h = max(h["players"].values(), key=lambda r: r["pa"])
    assert any_h["values"]["pa"] > 0 and any_h["values"]["woba"] is not None
    assert any_h["values"]["war"] is None
    assert ctx.model_errors.get("war")


def test_failing_model_is_isolated(synthetic_world, monkeypatch):
    from oddsmarkets.baseball.analytics import hitters
    from oddsmarkets.baseball.analytics.context import SeasonContext
    from oddsmarkets.baseball.models import war

    def boom(*a, **k):
        raise RuntimeError("planted failure")
    monkeypatch.setattr(war, "for_season", boom)
    c = SeasonContext("mlb", 2025, full=False, use_models=True)
    r = c.model("war")
    assert r["ok"] is False and "planted failure" in r["reason"]
    # the catalogue still builds; the other models are stubbed out to keep the test fast
    for name in ("xwoba", "swing", "battrack", "catchprob", "framing"):
        c._models[name] = {"ok": False, "reason": "stub"}
    c._wpa = pd.DataFrame()
    cat = hitters.build(c)
    assert cat["ok"] and "war" in cat["model_errors"]


def test_model_values_are_mapped(ctx):
    from oddsmarkets.baseball.analytics import hitters, pitchers
    h0 = hitters.build(ctx)
    pid = max(h0["players"], key=lambda p: h0["players"][p]["pa"])
    ctx._models["war"] = {"ok": True, "constants": {"rpw": 10.0},
                          "batters": {"cols": ["pid", "pos", "war", "batting", "bat_results", "baserunning", "rar", "pos_runs", "replacement"],
                                      "rows": [[pid, 6, 3.0, 10.0, 20.0, 1.5, 30.0, 7.5, 20.0]]},
                          "pitchers": {"cols": ["pid", "war_ra9", "war_x"], "rows": []}}
    ctx._models["xwoba"] = {"ok": True, "hitters": {"cols": ["pid", "pa", "xwoba", "xwoba_n", "savant_xwoba"], "rows": [[pid, 400, 0.355, 0.350, 0.340]]}}
    h = hitters.build(ctx)
    v = h["players"][pid]["values"]
    assert v["war"] == 3.0 and v["war_results"] == 4.0        # + (20 - 10) / 10
    assert v["xwoba_plus"] == 0.355 and v["batting_runs"] == 10.0
    assert h["players"][pid]["pos"] == "SS"


def test_game_page_shape(ctx):
    from oddsmarkets.baseball.analytics import games as GM
    gpk = next(iter(ctx.games))
    g = ctx.games[gpk]
    gp = GM.game_pitches(ctx, [gpk])
    page = GM.build_page(ctx, g, gp, GM.card(ctx, g), None, None)
    for k in ("gpk", "date", "status", "home", "away", "hs", "as", "model", "market", "line", "pitches", "wp", "umpire", "box", "arsenal"):
        assert k in page
    assert page["pitches"]["cols"] == GM.PITCH_COLS
    assert len(page["pitches"]["rows"]) == len(gp)
    assert all(len(r) == len(GM.PITCH_COLS) for r in page["pitches"]["rows"])
    assert page["box"]["batting"]["home"] and page["box"]["pitching"]["away"]
    assert page["wp"]["ours_kind"] in ("league", "model", None)
    if page["wp"]["ours"]:
        assert all(0.0 <= x[3] <= 1.0 for x in page["wp"]["ours"])
    card = GM.card(ctx, g)
    assert {"gpk", "date", "start", "status", "gtype", "series", "home", "away", "hs", "as", "inning", "probables", "model", "market",
            "line", "wp_home"} <= set(card)


def test_history_payload_carries_the_retrosheet_notice():
    from oddsmarkets.baseball.analytics import history as HS
    from oddsmarkets.baseball.sources import retrosheet
    b = pd.DataFrame({"pa": [600.0, 500.0], "ab": [550.0, 450.0], "h": [180.0, 120.0], "b2": [30.0, 20.0], "b3": [5.0, 1.0], "hr": [40.0, 10.0],
                      "bb": [40.0, 30.0], "ibb": [0.0, 0.0], "hbp": [2.0, 1.0], "k": [80.0, 90.0], "sf": [3.0, 2.0], "sh": [0.0, 0.0],
                      "wnum": [250.0, 150.0], "den": [590.0, 490.0], "wraa": [40.0, -5.0], "war": [7.0, 1.0], "season": [1927, 1927],
                      "lg_rpa": [0.12, 0.12]}, index=["r:ruthb101", "r:smitj101"])
    p = pd.DataFrame({"outs": [700.0], "runs": [80.0], "games": [35.0], "bf": [950.0], "k": [150.0], "bb": [60.0], "hr": [12.0], "h": [200.0],
                      "war": [5.0], "season": [1927], "lg_ra9": [4.8]}, index=["r:grovl101"])
    out = HS.build("mlb", (b, p))
    assert out["ok"] is True
    assert out["meta"]["retrosheet_notice"] == retrosheet.NOTICE
    assert "Retrosheet" in out["meta"]["retrosheet_notice"] and "www.retrosheet.org" in out["meta"]["retrosheet_notice"]
    assert out["leaders"]
    ph = HS.player_history((b, p))
    assert ph["r:ruthb101"]["batting"][0][0] == 1927
    assert ph["r:grovl101"]["pitching"][0][0] == 1927
    assert HS.notice_meta()["retrosheet_notice"] == retrosheet.NOTICE


def test_glossary():
    from oddsmarkets.baseball.analytics import glossary
    g = glossary.build()
    assert g["ok"] and g["groups"]
    for grp in g["groups"]:
        for e in grp["entries"]:
            assert METRIC_KEYS <= set(e)
    keys = {m["key"] for m in g["model"]}
    assert {"percentile", "stabilisation", "xwoba_plus", "war", "game_model"} <= keys
    assert g["notices"]["retrosheet"] == an.RETRO_NOTICE


def test_last_team_follows_dates_not_game_pks():
    """A traded player's team is the one of his latest game by date. The pitch frame is sorted by game_pk, and a
    gamePk is not date order (Luis Arraez, Tarik Skubal, Adley Rutschman showed their pre-trade clubs in 2026)."""
    from oddsmarkets.baseball.analytics import pitchagg as PG
    df = pd.DataFrame({
        "game_pk": [900, 100, 500], "game_date": pd.to_datetime(["2026-04-01", "2026-08-01", "2026-06-01"]),
        "at_bat_number": [1, 1, 1], "batter": [7, 7, 7], "pitcher": [9, 9, 8],
        "inning_topbot": ["Top", "Top", "Bot"], "home_team": ["DET", "LAD", "SF"], "away_team": ["SF", "PHI", "PHI"],
    }).sort_values("game_pk")
    assert PG.last_team(df, "batter", "bat")["7"] == "PHI"       # 1 Aug, away at LAD (pk 100, the lowest)
    assert PG.last_team(df, "pitcher", "fld")["9"] == "LAD"      # fielding side of his latest game


def test_steals_come_from_the_official_line(ctx, monkeypatch):
    """SB / CS show MLB's official line when the Stats API cache has one (the pitch-data estimate over-counted by
    2.6 a hitter in 2026: wild pitches and indifference), the estimate otherwise; unintentional walks say so."""
    from oddsmarkets.baseball.analytics import hitters, mlbapi
    h0 = hitters.build(ctx)
    pid = max(h0["players"], key=lambda p: h0["players"][p]["pa"])
    other = next(p for p in h0["players"] if p != pid)
    monkeypatch.setattr(mlbapi, "season_lines", lambda level, season, group, *a, **k:
                        {pid: {"sb": 7, "cs": 2}} if (level, season, group) == ("mlb", 2025, "hitting") else None)
    h = hitters.build(ctx)
    assert h["players"][pid]["values"]["sb"] == 7 and h["players"][pid]["values"]["cs"] == 2
    assert h["players"][other]["values"]["sb"] == h0["players"][other]["values"]["sb"]
    labels = {m["key"]: m["label"] for m in h["metrics"]}
    assert labels["bb"] == "uBB" and labels["sb"] == "SB"
