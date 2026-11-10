"""Home's search index (scripts/build_home.py): national teams are only national teams, tennis lists exactly the
players with a follow card (follow_build.select: active and ranked 500 or better, plus this week's players), and each
row carries the follow picker's group order."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_home_search", ROOT / "scripts" / "build_home.py")
bh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bh)


def test_a_club_that_met_a_national_team_is_still_a_club():
    club_comps = {"serie-a", "coppa-italia", "la-liga"}
    # Fiorentina carries the national flag from a 2022 friendly against Qatar
    assert not bh.is_national_team({"name": "Fiorentina", "national": 1, "home": "serie-a", "comps": ["serie-a", "coppa-italia"]}, club_comps)
    assert not bh.is_national_team({"name": "Lazio", "national": 1, "home": None, "comps": ["coppa-italia"]}, club_comps)
    assert bh.is_national_team({"name": "England", "national": 1, "home": None, "comps": ["euro", "friendlies"]}, club_comps)
    assert not bh.is_national_team({"name": "Arsenal", "national": 0, "home": "premier-league"}, club_comps)


def test_football_search_labels(tmp_path, monkeypatch):
    d = tmp_path / "site" / "data"
    d.mkdir(parents=True)
    (d / "clubs_index.json").write_text(json.dumps({"fields": ["id", "name", "country", "national", "home", "comps"], "rows": [
        [2693, "Fiorentina", "ITA", 1, "serie-a", ["serie-a"]], [4713, "England", "ENG", 1, None, ["euro"]]]}), encoding="utf-8")
    (d / "competitions.json").write_text(json.dumps({"competitions": [
        {"slug": "serie-a", "name": "Serie A", "scope": "club"}, {"slug": "euro", "name": "Euro", "scope": "international"}]}), encoding="utf-8")
    monkeypatch.setattr(bh, "DOCS", tmp_path)
    out = {"search": []}
    bh.football_search("B/", out)
    sub = {r[1]: r[2] for r in out["search"]}
    assert sub["Fiorentina"] == "Club · ITA" and sub["England"] == "National team · ENG"


def test_tennis_search_is_the_follow_card_set(tmp_path):
    from datetime import datetime, timezone
    from oddsmarkets.tennis.analytics import follow_build as TFB
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    t = tmp_path / "atp"
    t.mkdir()
    # [name, short, country, rank, last tour-level match, official]
    (t / "players_index.json").write_text(json.dumps({"players": {
        "1": ["Jannik Sinner", "J. Sinner", "ITA", 1, "2026-10-30", 1], "2": ["Someone Else", "S. Else", "USA", 500, "2026-03-01", 0],
        "3": ["Far Down", "F. Down", "FRA", 501, "2026-10-01", 0], "4": ["No Rank", "N. Rank", "ESP", None, "2026-10-01", 0],
        "5": ["Week Player", "W. Player", "ARG", 900, "2026-10-01", 0], "7": ["Long Gone", "L. Gone", "SWE", 12, "2019-05-01", 0],
        "8": ["Injured Star", "I. Star", "SRB", 40, "2025-06-01", 1]}}), encoding="utf-8")
    (t / "rankings.json").write_text(json.dumps({"official": [[1, "1", 11000, 0], [40, "8", 900, 0]]}), encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps({"tours": {"atp": {"today": [{"p1": "5", "p2": "6"}]}}}), encoding="utf-8")
    rows = bh.tennis_search_players(tmp_path, "atp", {"5": "W. Player", "6": "Q. Only"}, now)
    # 7 was last seen in 2019 (its rank is only its last-known one): no card, so not in the search either; 8 has not
    # played a tour-level match for 17 months but holds a current official ranking
    assert rows == [("1", "Jannik Sinner"), ("8", "Injured Star"), ("2", "Someone Else"), ("6", "Q. Only"), ("5", "Week Player")]
    assert [pid for pid, _ in rows] and sorted(pid for pid, _ in rows) == TFB.select(tmp_path, "atp", now)[0]
    # no index on disk: this week's players alone
    (tmp_path / "index.json").write_text(json.dumps({"tours": {"wta": {"live": [{"p1": "9", "p2": "x:qual"}]}}}), encoding="utf-8")
    assert bh.tennis_search_players(tmp_path, "wta", {"9": "A. B"}, now) == [("9", "A. B")]


def test_season_files_fetch_the_tennis_index(tmp_path):
    (tmp_path / "ace" / "data").mkdir(parents=True)
    (tmp_path / "ace" / "data" / "index.json").write_text(json.dumps({"tours": {"atp": {"events_now": [{"event": "paris-2026"}]}}}),
                                                          encoding="utf-8")
    rows = bh.season_files(tmp_path)
    for T in ("atp", "wta"):
        assert ("ace", "the-quant-ace", f"{T}/players_index.json") in rows and ("ace", "the-quant-ace", f"{T}/rankings.json") in rows
    assert ("ace", "the-quant-ace", "atp/events/paris-2026.json") in rows


def test_search_rows_carry_the_picker_group_order():
    rows = bh.search_rows([["football", "Arsenal", "Club · ENG", "F/#/club/42"], ["football", "Ajax", "Club · NLD", "F/#/club/2953"],
                           ["football", "Premier League", "Competition · England", "F/#/premier-league"],
                           ["college", "Ohio State", "College football · Big Ten", "C/#/cfb/team/194"],
                           ["college", "Minnesota", "Women’s college hockey", "C/#/wch/team/135"],
                           ["basketball", "Valkyries", "WNBA team", "H/#/wnba/team/129689"], ["tennis", "Jannik Sinner", "ATP player", "A/#/atp/player/3623"],
                           ["f1", "Mercedes", "Constructor", "P/#/team/mercedes"], ["nfl", "", "NFL team", "x"]])
    assert [r[4] if len(r) > 4 else None for r in rows] == [0, 6, None, 0, 4, 1, 0, 1]
    # the South American leagues' clubs follow the big five, Colombia, Uruguay, Chile and Peru after Brazil and Argentina
    sa = bh.search_rows([["football", c, "Club · " + k, "F/#/club/1"] for c, k in
                         (("Flamengo", "BRA"), ("Boca Juniors", "ARG"), ("Atlético Nacional", "COL"), ("Nacional", "URY"),
                          ("Colo-Colo", "CHL"), ("Alianza Lima", "PER"))])
    assert [r[4] for r in sa] == [9, 10, 11, 12, 13, 14]
    tur = bh.search_rows([["football", "Galatasaray", "Club · TUR", "F/#/club/3061"], ["football", "Gent", "Club · BEL", "F/#/club/1"]])
    assert [r[4] for r in tur] == [8, 7]                 # Turkey with the European leagues, after Belgium
