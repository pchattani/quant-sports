"""
National-team competitions, national cups and super cups: the registry is
coherent, Sofascore's round and stage labels parse, search resolves an id
offline, the international fit's frame is marked, and the site-wide indexes
(every player's line across competitions; every club's matches across
competitions) come out of build entries.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.cup import store as cup_store  # noqa: E402
from oddsmarkets.football.competitions.cup.config import (  # noqa: E402
    CUP_FAMILIES, CUPS, INTERNATIONALS, ROUND_LABELS, CupConfig,
)
from oddsmarkets.football.competitions.league.config import LEAGUES  # noqa: E402
from oddsmarkets.football.sources import sofascore  # noqa: E402
from scripts.make_league_sample_store import build_cup  # noqa: E402

KINDS = {"swiss", "groups", "regional_swiss", "knockout", "fixed", "international"}


# ── the registry ─────────────────────────────────────────────────────────────

def test_cup_registry_is_coherent() -> None:
    assert len(CUPS) >= 50
    assert not set(CUPS) & set(LEAGUES)
    for slug, cfg in CUPS.items():
        assert isinstance(cfg, CupConfig) and cfg.slug == slug
        assert cfg.kind in KINDS, slug
        assert cfg.family in CUP_FAMILIES, slug
        assert cfg.sofascore_id or cfg.search, f"{slug} has neither an id nor a search name"
        assert cfg.registry is not None, slug
        for sofa_slug, code in cfg.round_slugs:
            assert code in ROUND_LABELS, f"{slug}: round {sofa_slug!r} maps to unlabelled code {code!r}"
    assert set(INTERNATIONALS) == {s for s, c in CUPS.items() if c.family == "international"}
    assert all(INTERNATIONALS[s] is CUPS[s] for s in INTERNATIONALS)
    for cfg in (CUPS[s] for s in INTERNATIONALS):
        assert cfg.kind == "international" and not cfg.simulated
    assert {c.family for c in CUPS.values()} == {"cup", "domestic", "super", "international"}
    for c in CUPS.values():
        if c.family in ("domestic", "super"):
            assert c.country_hint and c.detail_scope == "followed", c.slug
    ids = [c.sofascore_id for c in CUPS.values() if c.sofascore_id]
    assert len(ids) == len(set(ids)), "two cups share a Sofascore id"
    assert CUPS["club-world-cup"].kind == "groups" and CUPS["club-world-cup"].family == "cup"
    assert CUPS["world-cup"].neutral_venues and CUPS["friendlies"].friendly


# ── parsing Sofascore's labels ───────────────────────────────────────────────

def test_playoff_round_uses_the_competition_slugs() -> None:
    fa = dict(CUPS["fa-cup"].round_slugs)
    assert sofascore.playoff_round("4th-round", None, fa) == "r4"
    assert sofascore.playoff_round("round-of-32", None, fa) == "r32"
    assert sofascore.playoff_round("round-of-32") == "po"    # the Champions League convention: its play-off round is a round of 32
    assert sofascore.playoff_round("final", None, fa) == "final"


def _event(label: str, **extra) -> dict:
    return {
        "id": 77, "homeTeam": {"name": "Spain", "id": 1}, "awayTeam": {"name": "France", "id": 2},
        "status": {"type": "notstarted"}, "homeScore": {}, "awayScore": {},
        "tournament": {"name": label}, "startTimestamp": 1788548400, **extra,
    }


def test_event_record_reads_international_groups_and_stages() -> None:
    ident = lambda n: n  # noqa: E731
    _, r = sofascore.event_record(_event("UEFA Nations League, League A, Group 2", roundInfo={"round": 3}), ident, 5, international=True)
    assert (r["group"], r["stage"]) == ("A2", "league")
    _, r = sofascore.event_record(_event("European Championship Qualification, Group C", roundInfo={"round": 1}), ident, 5, international=True)
    assert (r["group"], r["stage"]) == ("C", "league")
    _, r2 = sofascore.event_record(_event("European Championship Qualification, Group C", roundInfo={"round": 1}), ident, 5)
    assert r2["stage"] == "qualifying"          # the club-cup reading of the same label
    _, r = sofascore.event_record(_event("World Cup, Knockout stage", roundInfo={"round": 28, "slug": "semifinals", "name": "Semifinals"}), ident, 5, international=True)
    assert (r["stage"], r["round"]) == ("playoff", "sf")
    _, r = sofascore.event_record(_event("International Friendly Games"), ident, 5, international=True)
    assert r["stage"] == "league" and r["group"] is None


def test_search_tournament_prefers_the_hinted_country_and_skips_youth(monkeypatch) -> None:
    payload = {"results": [
        {"type": "uniqueTournament", "entity": {"id": 1, "name": "Coppa Italia Women", "category": {"name": "Italy"}}},
        {"type": "uniqueTournament", "entity": {"id": 2, "name": "Coppa Italia Serie C", "category": {"name": "Italy"}}},
        {"type": "uniqueTournament", "entity": {"id": 3, "name": "Coppa Italia", "category": {"name": "Italy"}}},
        {"type": "uniqueTournament", "entity": {"id": 4, "name": "Coppa Italia", "category": {"name": "San Marino"}}},
        {"type": "team", "entity": {"id": 5, "name": "Coppa Italia FC"}},
    ]}
    calls = []
    monkeypatch.setattr(sofascore, "get_json", lambda path, **kw: calls.append(path) or payload)
    hit = sofascore.search_tournament("Coppa Italia", "Italy")
    assert hit == {"id": 3, "name": "Coppa Italia", "category": "Italy"}
    assert calls and "search/all?q=Coppa%20Italia" in calls[0]
    assert sofascore.search_tournament("Coppa Italia", "San Marino")["id"] == 4
    assert sofascore.search_tournament("Copa Argentina", "Argentina") is None
    monkeypatch.setattr(sofascore, "get_json", lambda path, **kw: {"results": [
        {"type": "uniqueTournament", "entity": {"id": 9, "name": "U21 Euro", "category": {"name": "Europe"}}}]})
    assert sofascore.search_tournament("Euro", "Europe") is None     # youth only: nothing acceptable


def test_confederation_table_covers_the_world_cup_field() -> None:
    from oddsmarkets.football.analytics.confederations import CONFEDERATION, confederation_of

    assert len(CONFEDERATION) >= 200
    assert confederation_of("Spain") == "UEFA" and confederation_of("Brazil") == "CONMEBOL"
    assert confederation_of("USA") == "CONCACAF" and confederation_of("United States") == "CONCACAF"
    assert confederation_of("Türkiye") == "UEFA" and confederation_of("Korea Republic") == "AFC"
    assert confederation_of("Ivory Coast") == "CAF" and confederation_of("Côte d'Ivoire") == "CAF"
    assert confederation_of("New Zealand") == "OFC" and confederation_of("Spain U21") == "UEFA"
    assert confederation_of("Arsenal") is None and confederation_of(None) is None
    groups = ROOT / "docs" / "wc" / "data" / "groups.json"
    if groups.exists():
        field = [r["team"] for b in json.loads(groups.read_text(encoding="utf-8"))["groups"].values() for r in b["standings"]]
        assert field and all(confederation_of(t) for t in field)


# ── the international fit's frame ────────────────────────────────────────────

def test_international_training_frame_marks_neutral_and_weight() -> None:
    store = build_cup(CUPS["world-cup"], played_rounds=2)
    finished = sum(1 for m in store["matches"].values() if m["status"] == "finished")
    assert finished >= 30
    df = cup_store.international_training_frame(store, neutral=True, weight=0.5)
    assert len(df) == finished
    assert df["neutral"].all() and (df["weight"] == 0.5).all()
    df2 = cup_store.international_training_frame(store)
    assert not df2["neutral"].any() and (df2["weight"] == 1.0).all()
    groups = cup_store.groups_out(store) if hasattr(cup_store, "groups_out") else None
    assert groups is None or len(groups) == 8


# ── the site-wide indexes ────────────────────────────────────────────────────

def _entries() -> list[dict]:
    player = {"player_id": 10, "name": "A Striker", "team": "Arsenal", "position": "F", "matches": 5, "minutes": 450,
              "goals": 3, "assists": 1, "xg": 2.4, "xa": 0.8, "rating": 7.3, "shots": 12, "key_passes": 6, "yellow": 1, "red": 0}
    fx = lambda i, comp_home, comp_away, status="finished": {  # noqa: E731
        "id": i, "date": f"2026-09-{10 + i:02d}T19:00:00Z", "round": "r3", "stage": "playoff", "status": status,
        "home": comp_home, "away": comp_away, "hs": 2 if status == "finished" else None, "as": 0 if status == "finished" else None,
        "detail": True, "model": {"h": 0.5, "d": 0.25, "a": 0.25, "fair": [2.0, 4.0, 4.0]},
    }
    return [
        {"slug": "premier-league", "name": "Premier League", "short_name": "EPL", "kind": "league", "ok": True,
         "_teams": {"Arsenal": {}, "Chelsea": {}}, "_players": [player],
         "_fixtures": [fx(1, "Arsenal", "Chelsea")]},
        {"slug": "fa-cup", "name": "FA Cup", "kind": "cup", "family": "domestic", "ok": True, "_teams": {},
         "_players": [{**player, "minutes": 90, "matches": 1, "goals": 1, "assists": 0, "xg": 0.9, "xa": 0.1, "rating": 7.9}],
         "_fixtures": [fx(2, "Arsenal", "Wrexham"), fx(3, "Chelsea", "Arsenal", "scheduled")]},
        {"slug": "euro", "name": "Euro", "kind": "cup", "family": "international", "ok": True, "_teams": {},
         "_players": [{**player, "team": "England", "minutes": 180, "matches": 2, "goals": 0}],
         "_fixtures": [fx(4, "England", "Arsenal")]},          # a national team, never a club's league match
        {"slug": "broken", "name": "Broken", "kind": "cup", "ok": False, "_players": [player], "_fixtures": [fx(5, "Arsenal", "X")]},
        {"slug": "bench", "name": "Bench", "kind": "cup", "family": "cup", "ok": True, "_teams": {},
         "_players": [{**player, "minutes": 0, "matches": 0}], "_fixtures": []},
    ]


def test_season_index_lists_every_competition_a_player_appeared_in(tmp_path) -> None:
    from scripts.build_site_all import build_season_index

    n = build_season_index(tmp_path, _entries())
    payload = json.loads((tmp_path / "season_index.json").read_text(encoding="utf-8"))
    assert n == 1 and set(payload["players"]) == {"10"}
    rows = payload["players"]["10"]["rows"]
    assert [(r["comp"], r["fam"], r["t"]) for r in rows] == [("premier-league", "league", "Arsenal"), ("fa-cup", "domestic", "Arsenal"), ("euro", "international", "England")]
    assert sum(r["min"] for r in rows) == 720 and sum(r["g"] for r in rows) == 4
    assert rows[0]["cn"] == "EPL" and rows[1]["rt"] == 7.9


def test_club_matches_gather_a_clubs_season_across_competitions(tmp_path) -> None:
    from scripts.build_site_all import build_club_matches

    build_club_matches(tmp_path, _entries())
    payload = json.loads((tmp_path / "premier-league" / "club_matches.json").read_text(encoding="utf-8"))
    arsenal = payload["clubs"]["Arsenal"]
    assert [(m["comp"], m["id"]) for m in arsenal] == [("premier-league", 1), ("fa-cup", 2), ("fa-cup", 3)]
    assert arsenal[0]["cn"] == "EPL" and arsenal[1]["cn"] == "FA Cup"
    assert arsenal[2]["status"] == "scheduled" and arsenal[2]["model"] == {"h": 0.5, "d": 0.25, "a": 0.25}
    assert all(m["comp"] != "euro" for m in arsenal)            # national-team matches stay out
    assert "Wrexham" not in payload["clubs"]                    # only clubs of a followed league
    assert [m["id"] for m in payload["clubs"]["Chelsea"]] == [1, 3]
