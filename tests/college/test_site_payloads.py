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
    assert res["levels"] == {"cfb": True, "mbb": True, "wbb": False}
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
