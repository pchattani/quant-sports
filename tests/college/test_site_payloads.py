"""Site-wide payloads of The Quant Campus (oddsmarkets/college/site.py) from small fixture payloads. No network."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from oddsmarkets.college import site

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("cc_site_fixture", HERE / "fixtures" / "site" / "fixture_data.py")
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)

NOW = datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc)


@pytest.fixture()
def data(tmp_path):
    return fixture.make(tmp_path / "data")


def test_seasons_built_ignores_folders_without_season(data):
    assert site.seasons_built(data, "cfb") == [2026, 2025]
    assert site.seasons_built(data, "wbb") == []


def test_index_level_block(data):
    idx = site.build_index(data, NOW)
    cfb = idx["levels"]["cfb"]
    assert idx["ok"] and cfb["ok"]
    assert cfb["current_season"] == 2026 and cfb["seasons"] == [2026, 2025]
    assert cfb["phase"] == "regular" and cfb["week"] == 8
    assert cfb["headline"].startswith("Week 8")
    # today: the live game and anything on today's UTC day; next: the next 3 days; last: the last 2 days
    assert [g["id"] for g in cfb["today"]] == ["103"]
    assert [g["id"] for g in cfb["next_games"]] == ["104", "105"]
    assert [g["id"] for g in cfb["last_games"]] == ["102", "101"]
    assert cfb["top25"][0] == {"rank": 1, "team": "3", "prev": 2, "record": "7-0"}
    assert [r["team"] for r in cfb["model_top"]] == ["3", "1", "2"]
    # title odds: model, with the market from markets.json, zero-probability teams dropped
    assert cfb["title_odds"] == [{"team": "3", "p": 0.3, "market": 0.35}, {"team": "1", "p": 0.1, "market": 0.08}]
    assert cfb["champions"] == [[2025, "3"]]
    assert set(cfb["conferences"]) == {"8", "5"}
    # non-member teams are kept only when a listed game uses them
    assert "9" in cfb["teams"] and cfb["teams"]["9"]["member"] is False


def test_index_missing_level_is_not_ok(data):
    idx = site.build_index(data, NOW)
    assert idx["levels"]["wbb"]["ok"] is False and "reason" in idx["levels"]["wbb"]


def test_preseason_falls_back_to_the_coming_weeks(data):
    mbb = site.build_index(data, NOW)["levels"]["mbb"]
    assert mbb["current_season"] == 2027 and mbb["phase"] == "preseason"
    assert mbb["today"] == [] and [g["id"] for g in mbb["next_games"]] == ["901"]
    assert mbb["headline"].startswith("Tip-off")


def test_pick_games_orders_ranked_and_close_first_within_cap():
    now = NOW
    cards = [fixture.card(str(i), f"2026-10-20T{10 + i % 10:02d}:00:00Z", "pre", "1", "2", p=0.5 + i / 100) for i in range(60)]
    cards[59]["hr"] = 3
    today, nxt, last = site.pick_games(cards, now)
    assert len(nxt) == 40
    assert "59" in [c["id"] for c in nxt]          # ranked game kept although it is the least close
    assert [c["date"] for c in nxt] == sorted(c["date"] for c in nxt)


def test_glossary_has_site_terms_and_payload_metrics(data):
    g = site.build_glossary(data)
    names = [x["name"] for x in g["groups"]]
    assert names[:4] == ["Ratings", "Games", "Season", "Players"]
    keys = {e["key"] for x in g["groups"] for e in x["entries"]}
    assert {"rating", "p_home", "p_cfp", "transfer"} <= keys
    # "rating" already exists in the site terms, so the payload metric is namespaced; "epa" too
    assert "cfb:rating" in keys and "cfb:epa" in keys


def test_search_teams_and_players_with_career_files(data):
    idx = site.build_index(data, NOW)
    rows = site.build_search(data, idx)
    hrefs = {r["href"] for r in rows}
    assert "#/cfb/team/1" in hrefs and "#/cfb/team/9" not in hrefs       # members only
    assert "#/cfb/player/p1" in hrefs                                     # catalogue + career file
    assert "#/cfb/player/p2" not in hrefs                                 # no career file
    assert "#/cfb/player/p3" in hrefs                                     # career file only (read for its name)
    assert all(r["sport"] == "college" for r in rows)
    p1 = [r for r in rows if r["href"] == "#/cfb/player/p1"][0]
    assert p1["t"] == "Ann Arbor" and "CFB" in p1["s"] and p1["w"] == 40.0
    alpha = [r for r in rows if r["href"] == "#/cfb/team/1"][0]
    assert alpha["s"] == "CFB team · SEC"


def test_build_all_writes_three_files(data):
    res = site.build_all(data, NOW)
    assert res["levels"] == {"cfb": True, "mbb": True, "wbb": False, "mch": False, "wch": False}
    for f in ("index.json", "glossary.json", "search.json"):
        assert json.loads((data / f).read_text(encoding="utf-8"))
    assert isinstance(json.loads((data / "search.json").read_text(encoding="utf-8")), list)


def test_broken_payload_does_not_raise(tmp_path):
    d = tmp_path / "data"
    (d / "cfb" / "2026").mkdir(parents=True)
    (d / "cfb" / "2026" / "season.json").write_text('{"ok": true, "phase": "regular"}', encoding="utf-8")
    (d / "cfb" / "2026" / "schedule.json").write_text("{not json", encoding="utf-8")
    idx = site.build_index(d, NOW)
    assert idx["levels"]["cfb"]["ok"] and idx["levels"]["cfb"]["today"] == []


def test_pick_games_today_is_the_us_sports_day():
    """A Wednesday 8 pm Eastern game (00:00Z Thursday) is Wednesday's result, not Thursday's; a 10:30 pm Pacific
    kick-off (05:30Z) stays on its evening."""
    now = datetime(2026, 10, 22, 19, 17, tzinfo=timezone.utc)            # Thursday afternoon Eastern
    cards = [fixture.card("wed_late", "2026-10-22T00:00:00Z", "post", "1", "2", p=0.5),
             fixture.card("thu", "2026-10-22T23:00:00Z", "pre", "1", "2", p=0.5),
             fixture.card("thu_pac", "2026-10-23T05:30:00Z", "pre", "1", "2", p=0.5),
             fixture.card("fri", "2026-10-23T23:00:00Z", "pre", "1", "2", p=0.5)]
    today, nxt, last = site.pick_games(cards, now)
    assert [c["id"] for c in today] == ["thu", "thu_pac"]
    assert [c["id"] for c in last] == ["wed_late"]
    assert [c["id"] for c in nxt] == ["fri"]


# ── this week (the overview's digest) ─────────────────────────────────────
def test_index_digest_this_week(data):
    """levels.<L>.digest: the stage from the schedule, featured from the shared significance rule, and the chance
    log next to the level's payloads (the front end never reads it)."""
    dig = site.build_index(data, NOW)["levels"]["cfb"]["digest"]
    assert dig["asof"].startswith("2026-10-19T18:00")
    assert set(dig["featured"]) == {"today", "next", "week"}
    st = dig.get("stage")
    if st:
        assert st["week"] == 8 and 0 <= st["played"] <= st["total"]
    assert (data / "cfb" / "chance_log.json").exists() or not site.load(data / "cfb" / "2026" / "season.json").get("sim")


def _card(i, t, h, a, hs=None, as_=None, p=0.5, status="post", stype="reg", hr=None, ar=None, rnd=None):
    return {"id": str(i), "date": t, "status": status, "stype": stype, "home": h, "away": a, "hs": hs, "as": as_, "hr": hr, "ar": ar,
            "round": rnd, "model": {"p_home": p}}


def test_level_digest_week_from_frozen_chances(tmp_path):
    cards = [_card(1, "2026-10-17T19:30:00Z", "1", "2", 31, 10, 0.80, hr=3), _card(2, "2026-10-17T23:00:00Z", "4", "3", 38, 31, 0.12, ar=5),
             _card(3, "2026-10-18T00:00:00Z", "5", "6", 20, 24, 0.40), _card(4, "2026-10-01T23:00:00Z", "6", "5", 3, 50, 0.95),
             _card(5, "2026-10-24T16:00:00Z", "1", "3", status="pre", p=0.55, hr=3, ar=5)]
    season = {"phase": "regular", "week": 8, "sim": {"teams": {"1": {"p_cfp": 0.9, "p_title": 0.3}, "3": {"p_cfp": 0.6, "p_title": 0.1},
                                                              "4": {"p_cfp": 0.01, "p_title": 0.0}}}}
    dig = site.level_digest(tmp_path, "cfb", 2026, cards, season, NOW)
    r = dig["record"]
    assert (r["n"], r["won"], r["upsets"]) == (3, 2, 1) and "by" not in r     # the weeks-old game is left out
    u = dig["upset"]
    assert u["winner"] == "4" and u["loser"] == "3" and u["p"] == 0.12 and u["ranks"] == [None, 5]
    assert [x["id"] for x in dig["featured"]["next"] + dig["featured"]["today"]][:1] == ["5"]
    log = site.load(tmp_path / "cfb" / "chance_log.json")
    snap = log["2026"]["p_cfp"]
    assert list(snap) == ["2026-10-19"] and "4" in snap["2026-10-19"] and "2" not in snap["2026-10-19"]   # half a percent floor


def test_featured_prefers_the_big_game_over_the_closest(tmp_path):
    """The shared significance rule on college cards: No. 3 v No. 5 with playoff places and title chances riding on
    it leads; a dead coin flip between two unranked teams with nothing at stake does not, however close."""
    now = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)
    cards = [_card(10, "2026-10-24T16:00:00Z", "7", "8", status="pre", p=0.50), _card(11, "2026-10-24T19:30:00Z", "1", "3", status="pre", p=0.62, hr=3, ar=5)]
    season = {"phase": "regular", "sim": {"teams": {"1": {"p_cfp": 0.7, "p_title": 0.2}, "3": {"p_cfp": 0.5, "p_title": 0.1},
                                                    "7": {"p_cfp": 0.0, "p_title": 0.0}, "8": {"p_cfp": 0.0, "p_title": 0.0}}}}
    f = site.level_digest(tmp_path, "cfb", 2026, cards, season, now)["featured"]
    ids = [x["id"] for x in f["today"]]
    assert ids[0] == "11" and (ids.index("10") > 0 if "10" in ids else True)
    assert "#3 v #5" in f["today"][0]["why"] and "two title contenders" in f["today"][0]["why"]


def test_pick_games_reaches_the_next_slate():
    """A Sunday in football: one Tuesday game in the next 3 days, the Saturday slate four days later. "What to
    watch" must still get Saturday (round 9: it was empty Sunday to Wednesday)."""
    now = datetime(2026, 10, 25, 16, 0, tzinfo=timezone.utc)            # Sunday noon Eastern
    cards = [fixture.card("tue", "2026-10-27T23:30:00Z", "pre", "1", "2", p=0.5)]
    cards += [fixture.card(f"sat{i}", f"2026-10-31T{16 + i % 8:02d}:00:00Z", "pre", "1", "2", p=0.5) for i in range(12)]
    cards += [fixture.card("next_sat", "2026-11-07T16:00:00Z", "pre", "1", "2", p=0.5)]
    today, nxt, last = site.pick_games(cards, now)
    ids = [c["id"] for c in nxt]
    assert "tue" in ids and sum(1 for i in ids if i.startswith("sat")) == 12 and "next_sat" not in ids


def test_next_games_carry_the_featured_games():
    cards = [fixture.card("a", "2026-10-20T16:00:00Z", "pre", "1", "2", p=0.5), fixture.card("b", "2026-10-24T16:00:00Z", "pre", "1", "2", p=0.5)]
    out = site.with_featured(cards, [], [cards[0]], {"today": [], "next": [{"id": "b"}], "week": None})
    assert [c["id"] for c in out] == ["a", "b"]
