"""oddsmarkets/common/follow.py: the follow card (My Teams), its size guard and the fact engine, on synthetic teams."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from oddsmarkets.common import follow as FL

NOW = datetime(2026, 8, 15, 18, 0, tzinfo=timezone.utc)


def day(n: int) -> str:
    """ISO start n days from NOW (negative: the past)."""
    return (NOW + timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def games(letters: str, start: int = -1, p: float | None = 0.5) -> list[dict]:
    """Results oldest first, the last one `start` days from NOW, one a day."""
    n = len(letters)
    return [{"start": day(start - (n - 1 - i)), "res": c, "p": p} for i, c in enumerate(letters)]


def kinds(fx):
    return [f["kind"] for f in fx]


def base(**kw):
    ctx = {"name": "Milwaukee Brewers", "short": "Brewers", "phase": "season", "league_name": "MLB"}
    ctx.update(kw)
    return ctx


# ───────────────────────────────────────────────────────────── helpers
def test_form_streak_and_change():
    rs = games("LWWWWWW")
    assert FL.form_letters(rs, NOW) == "WWWWW"
    assert FL.streak_of(rs, NOW) == ("W", 6)
    assert FL.streak_of(games("WWLO"), NOW) == ("L", 2)          # an overtime loss counts as a loss
    assert FL.longest_run(games("WWWLWW"), NOW) == 3
    s = {"2026-08-01": 0.40, "2026-08-08": 0.50, "2026-08-14": 0.70}
    assert FL.change_since(s, NOW, 7) == pytest.approx(0.20)
    assert FL.change_since({"2026-08-14": 0.7}, NOW, 7) is None   # no snapshot a week old
    assert FL.upset_flag(0.38, "W") and not FL.upset_flag(0.41, "W") and not FL.upset_flag(0.2, "L")
    assert FL.ordinal(1) == "1st" and FL.ordinal(12) == "12th" and FL.ordinal(23) == "23rd" and FL.ordinal(111) == "111th"
    assert FL.record_text(103, 59) == "103–59" and FL.record_text(10, 4, 2) == "10–4–2" and FL.record_text(None, 3) is None


def test_label_case_keeps_inner_capitals():
    assert FL.label_case("Strikeout rate") == "strikeout rate"
    assert FL.label_case("BaseRuns win%") == "BaseRuns win%"
    assert FL.label_case("Lineup wOBA") == "lineup wOBA"
    assert FL.label_case("xwOBA+") == "xwOBA+"


def test_swing_label_keeps_its_own_capitals():
    """The swing fact capitalises the first letter only: "Stanley Cup", not str.capitalize()'s "Stanley cup"."""
    series = {"2026-08-08": 0.10, "2026-08-15": 0.22}
    for lab, want in (("Stanley Cup", "Stanley Cup chance up 12 points"), ("playoff", "Playoff chance up 12 points"),
                      ("AFC title", "AFC title chance up 12 points")):
        sw = [f for f in FL.facts(base(chances=[{"label": lab, "series": series}]), NOW) if f["kind"] == "swing"][0]
        assert sw["text"].startswith(want), sw["text"]


# ───────────────────────────────────────────────────────────── no look-ahead
def test_no_look_ahead_results_after_asof_are_ignored():
    rs = games("WWWW", start=-1) + [{"start": day(1), "res": "L", "p": 0.5}, {"start": day(2), "res": "L", "p": 0.5}]
    assert FL.streak_of(rs, NOW) == ("W", 4)
    assert FL.form_letters(rs, NOW) == "WWWW"
    fx = FL.facts(base(results=rs), NOW)
    st = [f for f in fx if f["kind"] == "streak"][0]
    assert "won 4 in a row" in st["text"]
    # the same results read a few days later see the losses
    assert FL.streak_of(rs, NOW + timedelta(days=3)) == ("L", 2)


def test_no_look_ahead_chance_log_and_next_game():
    series = {"2026-08-07": 0.30, "2026-08-15": 0.55, "2026-08-20": 0.95}      # the 20th is after asof
    assert FL.change_since(series, NOW, 7) == pytest.approx(0.25)
    fx = FL.facts(base(chances=[{"label": "Playoff", "series": series}]), NOW)
    sw = [f for f in fx if f["kind"] == "swing"][0]
    assert "up 25 points to 55%" in sw["text"]
    # a "next" game that has already started is not next
    started = {"start": day(0) if False else (NOW - timedelta(hours=1)).isoformat(), "opp": {"short": "Cubs"}, "p": 0.5,
               "score": 70, "reasons": ["a top-of-the-table game"], "rivalry": "Brewers v Cubs"}
    assert not [f for f in FL.facts(base(next=started), NOW) if f["kind"] in ("big_game", "rivalry")]
    later = dict(started, start=day(1))
    assert {"big_game", "rivalry"} <= set(kinds(FL.facts(base(next=later), NOW)))


def test_no_look_ahead_rating_moves_and_player_runs():
    ranks = [["2026-07-10", 12], ["2026-08-14", 5], ["2026-08-20", 1]]
    fx = FL.facts(base(rating_ranks=ranks), NOW)
    rm = [f for f in fx if f["kind"] == "rating_move"][0]
    assert "up 7 places" in rm["text"] and "to 5th" in rm["text"]
    runs = [{"text": "Later news.", "asof": "2026-08-20"}]
    assert "player_run" not in kinds(FL.facts(base(player_runs=runs), NOW))
    runs = [{"text": "Devers is on a run.", "asof": "2026-08-14"}]
    assert "player_run" in kinds(FL.facts(base(player_runs=runs), NOW))


# ───────────────────────────────────────────────────────────── each fact kind
def test_every_kind_from_a_rich_synthetic_team():
    ctx = base(
        results=games("LWWWWWWWWW", p=0.45),
        streak_history=[{"season": 2019, "kind": "W", "n": 1}, {"season": 2011, "kind": "W", "n": 9}],
        rating_ranks=[["2026-07-01", 14], ["2026-08-14", 4]],
        vs_last={"now": [70, 50], "last": [60, 60], "season_last": 2025},
        split={"of": 30, "league": "MLB", "home": {"record": "40–18", "rank": 1}, "away": {"record": "30–32", "rank": 14}},
        best_start={"record": "70–50", "since": 1982},
        pctl=[{"label": "Barrel rate", "rank": 1, "of": 30, "text": "9.6%"}, {"label": "Framing", "rank": 30, "of": 30, "text": "−9"}],
        best_record={"record": "70–50", "scope": "group", "where": "NL Central"},
        sos={"rank": 1, "of": 30, "left": 42, "where": "MLB", "text": "+0.21"},
        luck={"d": 5.2, "basis": "BaseRuns says their play deserved"},
        chances=[{"label": "Postseason", "series": {"2026-08-07": 0.5, "2026-08-14": 0.74}}],
        clinch={"magic": 9, "what": "the NL Central"},
        next={"start": day(2), "opp": {"short": "Cubs"}, "p": 0.41, "score": 66, "reasons": ["a top-of-the-table game"], "rivalry": None},
        players=[{"name": "Jacob Misiorowski", "text": "6.5", "metric": "Bullpen WAR", "rank": 2, "of": 400, "pool": "MLB pitchers"}],
        player_runs=[{"text": "Turang is on a run.", "asof": "2026-08-14"}],
        rating={"rank": 4, "of": 30, "text": "+0.80", "unit": "runs a game"},
    )
    cands = FL.candidates(ctx, NOW)
    got = set(kinds(cands))
    want = {"streak", "form_xp", "rating_move", "vs_last", "split", "best_start", "pctl", "best_record", "sos", "luck",
            "swing", "clinch", "big_game", "player_rank", "player_run", "rating"}
    assert want <= got, want - got
    st = [c for c in cands if c["kind"] == "streak"][0]["text"]
    assert st == "The Brewers have won 9 in a row, their longest since 2011."
    fx = [c for c in cands if c["kind"] == "form_xp"][0]["text"]
    assert "won 9 of their last 10" in fx and "4.5" in fx
    top = FL.facts(ctx, NOW)
    assert 3 <= len(top) <= FL.MAX_FACTS
    assert len(set(kinds(top))) == len(top)
    assert [f["score"] for f in top] == sorted((f["score"] for f in top), reverse=True)


def test_champion_franchise_call_and_offseason_drops_live_kinds():
    ctx = base(phase="offseason", final=True, results=games("WWWWW"),
               champion={"event": "World Series", "season": 2026, "result": [4, 1], "opp": "Rays", "first_title": True,
                         "seasons": 58, "pre_p": 0.228, "pre_rank": 1, "pre_n": 12},
               chances=[{"label": "Title", "series": {"2026-08-01": 0.1, "2026-08-14": 0.9}}],
               player_runs=[{"text": "On a run.", "asof": "2026-08-14"}],
               franchise={"pct": 0.636, "record": "103–59", "best_pct": 0.62, "best_record": "100–62", "best_season": 2011, "final": True})
    fx = FL.facts(ctx, NOW)
    k = kinds(fx)
    assert k[0] == "champion" and fx[0]["text"] == "2026 World Series champions, 4–1 over the Rays."
    assert "franchise" in k and "call" in k
    assert [f for f in fx if f["kind"] == "franchise"][0]["text"].startswith("The first World Series title in franchise history, in their 58th")
    assert "23%" in [f for f in fx if f["kind"] == "call"][0]["text"] and "best of the 12" in [f for f in fx if f["kind"] == "call"][0]["text"]
    for live in FL.LIVE_KINDS:
        assert live not in k
    # with no first title, a franchise best record still counts as its own kind
    ctx2 = base(phase="offseason", final=True, franchise=ctx["franchise"])
    f2 = [f for f in FL.facts(ctx2, NOW) if f["kind"] == "franchise"][0]
    assert f2["text"] == "The best record in franchise history (103–59); the old best was 100–62 in 2011."


def test_losing_streak_extremes_and_worst_places():
    ctx = base(results=games("WLLLLL"), pctl=[{"label": "Lineup wOBA", "rank": 30, "of": 30, "text": ".311"}],
               split={"of": 30, "league": "MLB", "away": {"record": "26–55", "rank": 30}})
    fx = {f["kind"]: f["text"] for f in FL.facts(ctx, NOW)}
    assert fx["streak"] == "The Brewers have lost 5 in a row, their longest run this season."
    assert fx["pctl"] == "The worst lineup wOBA in MLB (.311)."
    assert fx["split"] == "The Brewers have the worst record on the road in MLB: 26–55."


def test_player_places_and_ties():
    ctx = base(final=True, players=[{"name": "Cam Schlittler", "text": "6.5", "metric": "Bullpen WAR", "rank": 1, "of": 300, "pool": "MLB pitchers", "tied": True}])
    t = [f for f in FL.facts(ctx, NOW) if f["kind"] == "player_rank"][0]["text"]
    assert t == "Cam Schlittler's 6.5 Bullpen WAR was joint-best among MLB pitchers."
    ctx["players"][0].update(rank=3, tied=False)
    assert "was 3rd among MLB pitchers" in [f for f in FL.facts(ctx, NOW) if f["kind"] == "player_rank"][0]["text"]
    ctx["players"][0].update(rank=40)
    assert "player_rank" not in kinds(FL.facts(ctx, NOW))


def test_vs_last_full_season_needs_equal_lengths():
    t = {f["kind"]: f["text"] for f in FL.facts(base(final=True, vs_last={"now": [103, 59], "last": [96, 66], "season_last": 2025, "full": True}), NOW)}
    assert t["vs_last"] == "The Brewers won 7 more games than in 2025 (96–66)."
    t = {f["kind"]: f["text"] for f in FL.facts(base(final=True, vs_last={"now": [73, 77], "last": [80, 67], "season_last": 2025, "full": True}), NOW)}
    assert t["vs_last"] == "The Brewers finished 73–77, against 80–67 in 2025."


# ───────────────────────────────────────────────────────────── de-duplication and ranking
def test_dedupe_one_per_kind_and_no_repeated_text():
    ctx = base(pctl=[{"label": "Barrel rate", "rank": 1, "of": 30, "text": "9.6%"}, {"label": "Offence", "rank": 2, "of": 30, "text": "+0.5"},
                     {"label": "Framing", "rank": 1, "of": 30, "text": "+14"}])
    fx = FL.facts(ctx, NOW)
    assert kinds(fx).count("pctl") == 1
    # two kinds that word the same sentence: the text is kept once
    out = [{"kind": "a", "text": "Same line.", "score": 50}, {"kind": "b", "text": "Same  line.", "score": 40}]
    orig = FL.candidates
    try:
        FL.candidates = lambda c, a: out          # noqa: E731
        got = FL.facts({}, NOW)
    finally:
        FL.candidates = orig
    assert [g["kind"] for g in got] == ["a"]


def test_facts_respect_limit_and_min_score():
    ctx = base(rating={"rank": 15, "of": 30, "text": "+0.01"})
    fx = FL.facts(ctx, NOW)
    assert kinds(fx) == ["rating"]
    assert FL.facts(ctx, NOW, min_score=99) == []
    rich = base(results=games("WWWWWW"), rating={"rank": 1, "of": 30, "text": "+1.6"},
                pctl=[{"label": "Barrel rate", "rank": 1, "of": 30}], luck={"d": 6}, best_record={"record": "1", "scope": "league", "where": "MLB"},
                vs_last={"now": [80, 40], "last": [60, 60], "season_last": 2025})
    assert len(FL.facts(rich, NOW, limit=3)) == 3


# ───────────────────────────────────────────────────────────── the card and the size guard
def card(**kw):
    a = dict(site="bullpen", sport="baseball", scope="mlb", ident="158",
             team={"name": "Milwaukee Brewers", "short": "Brewers", "abbr": "MIL", "colour": "#13294b", "href": "#/mlb/team/158"},
             asof=NOW, phase="season", season=2026)
    a.update(kw)
    return FL.make_card(**a)


def test_card_schema_and_cleaning():
    c = card(now={"record": "70–50", "form": "LLWWWWW", "streak": "W5", "standing": {"pos": 1, "of": 5, "group": "NL Central", "text": "1st"}, "rating": None},
             chances=[{"key": "p_ws", "label": "World Series", "p": 0.21, "d7": None}],
             next_games=[{"id": str(i), "start": day(i + 1), "home": True, "opp": {"name": "Cubs"}, "p": 0.5} for i in range(5)],
             facts=[{"kind": "streak", "text": "Won 5.", "score": 60}] * 7, players=[{"name": "A"}, {"name": "B"}, {"name": "C"}],
             profile={"strong": [{"id": i} for i in "abcd"], "weak": [{"id": i} for i in "xyz"]})
    assert c["v"] == FL.V and c["k"] == "bullpen:mlb:158" and c["asof"] == "2026-08-15T18:00Z" and c["phase"] == "season"
    assert c["now"]["form"] == "WWWWW" and "rating" not in c["now"]
    assert c["chances"] == [{"key": "p_ws", "label": "World Series", "p": 0.21}]       # None dropped
    assert len(c["next"]) == FL.MAX_NEXT and len(c["facts"]) == FL.MAX_FACTS and len(c["players"]) == FL.MAX_PLAYERS
    assert len(c["profile"]["strong"]) == 3 and len(c["profile"]["weak"]) == 2
    assert all(set(f) == {"kind", "text"} for f in c["facts"])                      # the score stays in the builder
    for bad in ({"phase": "summer"}, {"team": {}}, {"asof": None}):
        with pytest.raises(ValueError):
            card(**bad)


def test_size_guard_shrinks_and_refuses(tmp_path):
    big = "x" * 900
    c = card(facts=[{"kind": f"k{i}", "text": big} for i in range(5)],
             next_games=[{"id": str(i), "start": day(i + 1), "opp": {"name": "Cubs"}, "why": [big, big]} for i in range(3)],
             players=[{"name": big}, {"name": big}], profile={"strong": [{"label": big}] * 3, "weak": [{"label": big}] * 2})
    assert FL.card_bytes(c) > FL.MAX_BYTES
    s = FL.shrink(c)
    assert FL.card_bytes(s) <= FL.MAX_BYTES
    assert FL.card_bytes(c) > FL.MAX_BYTES                     # shrink works on a copy
    assert s["team"] == c["team"] and s["k"] == c["k"]         # identity and freshness are never trimmed
    out = FL.write_cards(tmp_path, "mlb", {"158": c, "147": card(ident="147")})
    assert out["n"] == 2 and out["max"] <= FL.MAX_BYTES and out["ids"] == ["147", "158"]
    assert json.loads((tmp_path / "mlb" / "158.json").read_text(encoding="utf-8"))["k"] == "bullpen:mlb:158"
    # prune: a club no longer in the league loses its card
    FL.write_cards(tmp_path, "mlb", {"147": card(ident="147")})
    assert not (tmp_path / "mlb" / "158.json").exists()
    huge = card(team={"name": "x" * (FL.MAX_BYTES + 10)})
    with pytest.raises(ValueError):
        FL.write_cards(tmp_path, "mlb", {"1": huge})


def test_rivalry_lookup():
    assert FL.rivalry("Yankees", "Red Sox") == "Yankees v Red Sox"
    assert FL.rivalry("Red Sox", "Yankees") == "Yankees v Red Sox"
    assert FL.rivalry("Brewers", "Rays") is None and FL.rivalry(None, "Rays") is None
