"""Home page builder: stale inputs never show as live, and CI fetches the season-dependent files it reads."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_home", ROOT / "scripts" / "build_home.py")
bh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bh)

NOW = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)


def _g(status, hours_from_now):
    return bh.game("football", "X", "1", bh.iso(NOW + timedelta(hours=hours_from_now)), status,
                   bh.team("A"), bh.team("B"))


def test_stale_live_and_overdue_pre_games_are_dropped():
    ctx = bh.Ctx("public", NOW)
    assert bh.in_window(ctx, _g("live", -1.5))            # a game in progress
    assert not bh.in_window(ctx, _g("live", -5 * 24))     # "live" since 17 Oct: a stale input
    assert not bh.in_window(ctx, _g("live", -10))         # longer than any game lasts
    assert bh.in_window(ctx, _g("pre", 2))
    assert bh.in_window(ctx, _g("pre", -1))               # just started, status not updated yet
    assert not bh.in_window(ctx, _g("pre", -30))          # never started per the input: stale
    assert bh.in_window(ctx, _g("final", -30))
    assert not bh.in_window(ctx, _g("final", -50))
    picked = bh.pick_games(ctx, [_g("live", -100), _g("live", -1), _g("pre", -30), _g("pre", 5)])
    assert [g["status"] for g in picked] == ["live", "pre"]


def test_season_files_follow_each_sites_index(tmp_path):
    def put(rel, obj):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")

    put("paddock/data/index.json", {"current_season": 2026})
    put("hardwood/data/index.json", {"leagues": {"nba": {"current_season": 2027}, "wnba": {"current_season": 2026}}})
    put("gridiron/data/index.json", {"season": 2026})
    put("rink/data/index.json", {"season": "20262027"})
    rows = bh.season_files(tmp_path)
    assert ("paddock", "the-quant-paddock", "2026/season.json") in rows
    assert ("hardwood", "the-quant-hardwood", "nba/2027/season.json") in rows
    assert ("hardwood", "the-quant-hardwood", "wnba/2026/season.json") in rows
    assert ("gridiron", "the-quant-gridiron", "2026/season.json") in rows
    assert ("rink", "the-quant-rink", "20262027/season.json") in rows
    assert ("site", "the-quant-footballer", "premier-league/probs.json") in rows
    assert ("site", "the-quant-footballer", "premier-league/market_odds.json") not in rows   # no market on the home page
    # a missing tree gives no rows for that site rather than an error
    assert all(r[0] == "site" for r in bh.season_files(tmp_path / "nothing"))


def test_home_workflow_fetches_the_season_files():
    gen = (ROOT / "scripts" / "gen_ci_workflows.py").read_text(encoding="utf-8")
    assert "build_home.py --season-files" in gen


def test_team_nicknames_and_broadcast_fields():
    # the Broadcast hero prints the nickname large and the city under it; two-word nicknames stay whole
    assert bh.nickname("Vegas Golden Knights") == "Golden Knights"
    assert bh.nickname("Toronto Maple Leafs") == "Maple Leafs"
    assert bh.nickname("Colorado Avalanche") == "Avalanche"
    t = bh.team("Jets", "WPG", "#041E42", full="Winnipeg Jets", alt="#004C97")
    assert t["full"] == "Winnipeg Jets" and t["alt"] == "#004C97"
    assert "full" not in bh.team("Arsenal", full="Arsenal")          # no city to print: not written


def _keys(x):
    """Every dict key anywhere in a JSON-like value."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


def test_no_market_field_reaches_home_json(tmp_path, monkeypatch):
    """STYLE_GUIDE §3: the market never shows on the home page, so home.json carries none (games, title rows, F1 field)."""
    def put(rel, obj):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")

    start = bh.iso(NOW + timedelta(hours=3))
    put("paddock/data/index.json", {"current_season": 2026, "teams": {"mclaren": {"colour": "#FF8000"}},
                                    "drivers": {"norris": {"name": "Lando Norris", "code": "NOR", "team": "mclaren"}},
                                    "next": {"name": "Mexico City GP", "round": 20, "year": 2026, "date": start[:10],
                                             "sessions": {"race": start}, "circuit": {"name": "Hermanos Rodríguez"}}})
    put("paddock/data/markets.json", {"next_race": {"model": {"norris": 0.31}, "prices": {"norris": 0.4, "piastri": 0.2}},
                                      "drivers_title": {"prices": {"norris": 0.5}}})
    put("paddock/data/2026/season.json", {"championship": {"drivers": {"norris": {"p_title": 0.6}}}})
    put("hardwood/data/index.json", {"leagues": {"nba": {"teams": {"1": {"name": "Boston Celtics", "abbr": "BOS"},
                                                                    "2": {"name": "New York Knicks", "abbr": "NYK"}},
                                                          "today": [{"id": 9, "date": start, "status": "pre", "home": 1, "away": 2,
                                                                     "model": {"p_home": 0.6, "total": 221.5},
                                                                     "market": {"p_home": 0.55, "spread_home": -3.5}}]}}})
    monkeypatch.setattr(bh, "DOCS", tmp_path)
    ctx = bh.Ctx("local", NOW)
    out = {"games": [], "charts": {}, "futures": {}, "sports": [], "search": [], "pool": [], "series": []}
    for fn in (bh.build_f1, bh.build_basketball):
        try:
            fn(ctx, "../x/", out)
        except (KeyError, TypeError, AttributeError):
            pass   # a later block wants more fixture than this test gives; the fields below are already written
    assert out["games"] and out["charts"].get("f1_next_race") and out["futures"].get("f1")
    assert [r["name"] for r in out["charts"]["f1_next_race"]["field"]] == ["Lando Norris"]   # model only
    bad = {k for k in _keys(out) if k.startswith("market") or k == "spread"}
    assert not bad, bad
    src = (ROOT / "scripts" / "build_home.py").read_text(encoding="utf-8")
    assert "market_home=" not in src and '"market":' not in src and "market_odds.json" not in src


def test_featured_game_is_the_significant_one_not_a_3am_coin_flip():
    """The screenshot bug: a 50/50 WTA 250 at 03:00 (New York) led the page as "Our pick tonight". The significance
    rule (oddsmarkets/common/featured.py) must put an NFL or EPL game the same day first."""
    now = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)          # Fri 22:00 in New York

    def at(h):
        return bh.iso(now.replace(hour=h))
    wta = bh.game("tennis", "WTA · Ningbo", "wta1", at(7), "pre", bh.team("M. Bouzkova"), bh.team("L. Fernandez"),
                  p_home=0.5, players=True)
    wta["sig"] = {"comp": "250", "round": "R16"}
    nfl = bh.game("nfl", "NFL", "nfl1", at(17), "pre", bh.team("Chiefs", "KC"), bh.team("Bills", "BUF"), p_home=0.58)
    nfl["sig"] = {"title": [0.2, 0.15], "playoff": [0.8, 0.7]}
    epl = bh.game("football", "EPL", "epl1", at(14), "pre", bh.team("Arsenal"), bh.team("Chelsea"),
                  p_home=0.5, p_draw=0.26, p_away=0.24)
    epl["sig"] = {"comp": "premier-league", "title": [0.45, 0.02]}
    for pool in ([wta, nfl], [wta, epl], [wta, nfl, epl]):
        games = [dict(g) for g in pool]
        sports = []
        top = bh.top_of_page(now, games, games, [], sports)
        today = top["featured"]["today"]
        assert today and today[0]["key"] != "tennis:wta1", today
        assert all(r["key"] != "tennis:wta1" for r in today)             # under the bar: never the game of the day
        w = {bh.FT.game_key(g): g.get("weight") for g in games}
        assert w["tennis:wta1"] < min(v for k, v in w.items() if k != "tennis:wta1")
    src = (ROOT / "docs" / "home" / "assets" / "home.js").read_text(encoding="utf-8")
    assert "'Our pick" not in src                                        # the label rule: never "Our pick"


def test_digest_counts_only_pre_game_chances_and_leaves_football_out():
    now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)

    def fin(sport, gid, ph, hs, as_, days_ago, **kw):
        return bh.game(sport, sport.upper(), gid, bh.iso(now - timedelta(days=days_ago)), "final", bh.team("H"),
                       bh.team("A"), hs, as_, p_home=ph, **kw)
    pool = [fin("nfl", "a", 0.7, 24, 10, 1), fin("hockey", "b", 0.6, 1, 3, 2), fin("baseball", "c", 0.2, 5, 1, 3),
            fin("nfl", "old", 0.9, 0, 30, 16),                                 # outside even the widened 14 days
            fin("football", "d", 0.6, 0, 2, 1, p_draw=0.2)]                     # football: never counted
    top = bh.top_of_page(now, [], pool, [], [])
    rec = top["digest"]["record"]
    assert rec["n"] == 3 and rec["won"] == 1 and rec["days"] == 7         # 14 days adds nothing here: the week stays
    assert "football" not in top["digest"]["record_sports"] and top["digest"]["left_out"] == ["football"]
    assert top["digest"]["upset"]["p"] == 0.2 and top["digest"]["upset"]["sport"] == "baseball"


def test_record_widens_to_14_days_when_the_week_is_thin():
    now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    pool = [bh.game("nfl", "NFL", f"g{i}", bh.iso(now - timedelta(days=1 if i < 5 else 10)), "final", bh.team("H"),
                    bh.team("A"), 20, 10, p_home=0.6) for i in range(25)]
    rec = bh.record_with_floor(pool, now)
    assert rec["days"] == 14 and rec["n"] == 25                        # 5 this week: too few, so the last 14 days
    rec = bh.record_with_floor(pool[:5], now)
    assert rec["days"] == 7 and rec["n"] == 5                          # nothing more to widen to: the week, flagged small
