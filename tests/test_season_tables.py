"""The season-table fetcher (scripts/fetch_sofascore_season_tables.py): queue order, the empty stop, live refreshes,
paging, the 403 stop, the shard format and the Sofascore lock. No network: sofascore.get_json is replaced."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_sofascore_season_tables as F  # noqa: E402
from oddsmarkets.football.sources import sofascore  # noqa: E402

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def comps():
    return [
        {"slug": "premier-league", "tids": [17], "current": {300}, "tier": 0, "order": 0},
        {"slug": "la-liga", "tids": [8], "current": {800}, "tier": 0, "order": 1},
        {"slug": "champions-league", "tids": [7], "current": {700}, "tier": 1, "order": 13},
        {"slug": "euro", "tids": [1], "current": {10}, "tier": 3, "order": 50},
    ]


def lists():
    return {
        17: [{"season_id": 300, "year": "26/27"}, {"season_id": 299, "year": "25/26"}, {"season_id": 298, "year": "24/25"},
             {"season_id": 297, "year": "23/24"}, {"season_id": 296, "year": "22/23"}],
        8: [{"season_id": 800, "year": "26/27"}, {"season_id": 799, "year": "25/26"}],
        7: [{"season_id": 701, "year": "27/28"}, {"season_id": 700, "year": "26/27"}, {"season_id": 699, "year": "25/26"}],
        1: [{"season_id": 10, "year": "2024"}, {"season_id": 9, "year": "2020"}],
    }


def test_queue_depth_major_tiers_and_live():
    fin, live = F.queue(comps(), lists(), today=NOW, shards={})
    assert [(q["slug"], q["sid"]) for q in fin[:5]] == [
        ("premier-league", 299), ("la-liga", 799), ("champions-league", 699), ("euro", 10), ("premier-league", 298)]
    # the Euro's current edition is 2024: finished, not live; the Champions League lists a newer edition: live too
    assert {(q["slug"], q["sid"]) for q in live} == {("premier-league", 300), ("la-liga", 800), ("champions-league", 701),
                                                    ("champions-league", 700)}
    assert all(q["depth"] == 0 for q in fin[:4])


def test_queue_skips_complete_and_stops_after_empty_seasons():
    shards = {("premier-league", 299): {"complete": True, "n": 500},
              ("premier-league", 298): {"complete": True, "n": 0},
              ("premier-league", 297): {"complete": True, "n": 0}}
    fin, _ = F.queue(comps(), lists(), today=NOW, shards=shards)
    pl = [q["sid"] for q in fin if q["slug"] == "premier-league"]
    assert pl == []                    # 298 and 297 empty: 296 is never asked for
    shards[("premier-league", 297)] = {"complete": False, "n": 0, "next_page": 0}
    fin, _ = F.queue(comps(), lists(), today=NOW, shards=shards)
    assert [q["sid"] for q in fin if q["slug"] == "premier-league"] == [297, 296]


def test_live_refresh_interval():
    fresh = (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = (NOW - timedelta(days=F.LIVE_REFRESH_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    shards = {("premier-league", 300): {"complete": True, "n": 400, "fetched_at": fresh},
              ("la-liga", 800): {"complete": True, "n": 400, "fetched_at": stale}}
    _, live = F.queue(comps(), lists(), today=NOW, shards=shards)
    slugs = {(q["slug"], q["sid"]) for q in live}
    assert ("premier-league", 300) not in slugs and ("la-liga", 800) in slugs


def test_end_year():
    assert F.end_year("25/26") == 2026 and F.end_year("2026") == 2026 and F.end_year("23-25") == 2025
    assert F.end_year("") == 0


def test_tiers():
    assert F.tier_of("premier-league") == 0 and F.tier_of("liga-argentina") == 0
    assert F.tier_of("champions-league") == 1 and F.tier_of("fa-cup") == 2 and F.tier_of("community-shield") == 2
    assert F.tier_of("world-cup") == 3


def _res(pid, team, mins, **kw):
    return {"player": {"id": pid, "name": f"P{pid}"}, "team": {"id": team, "name": f"T{team}"}, "minutesPlayed": mins,
            "goals": kw.get("goals"), "expectedGoals": kw.get("xg"), "rating": kw.get("rt")}


def test_merge_and_pack_drop_empty_columns():
    sh = {"slug": "x", "sid": 1}
    F.merge_page(sh, [_res(1, 10, 900, goals=3), _res(2, 10, 1800, goals=0, rt=6.9)])
    F.merge_page(sh, [_res(1, 10, 950, goals=4)])                  # a later answer replaces the earlier row
    out = F.pack_shard(sh)
    assert out["fields"] == ["id", "team", "name", "minutesPlayed", "goals", "rating"]    # no xG: dropped
    assert out["rows"][0] == [2, 10, "P2", 1800, 0, 6.9] and out["rows"][1] == [1, 10, "P1", 950, 4, None]
    assert out["n"] == 2 and out["teams"] == {"10": "T10"} and "_rows" not in out


class FakeAPI:
    """sofascore.get_json stand-in: pages of a season table, or a status."""

    def __init__(self, pages: list[list[dict]] | None = None, status: int = 200, page_field=None):
        self.pages = pages or []
        self.status = status
        self.page_field = page_field
        self.paths: list[str] = []

    def __call__(self, path, timeout=20, quiet=False):
        self.paths.append(path)
        sofascore.LAST_STATUS = self.status
        if self.status != 200:
            return None
        off = int(path.split("offset=")[1].split("&")[0])
        i = off // F.PAGE
        if i >= len(self.pages):
            sofascore.LAST_STATUS = 404
            return None
        return {"results": self.pages[i], "page": self.page_field or i + 1, "pages": len(self.pages)}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "TABLES_DIR", tmp_path / "tables")
    monkeypatch.setattr(F, "PAUSE_S", 0)
    monkeypatch.setattr(sofascore, "LAST_STATUS", None)
    return tmp_path


def test_fetch_item_pages_resumes_and_completes(sandbox, monkeypatch):
    api = FakeAPI([[_res(i, 10, 1000 - i) for i in range(100)], [_res(i, 11, 50) for i in range(100, 130)]])
    monkeypatch.setattr(sofascore, "get_json", api)
    item = {"slug": "premier-league", "tid": 17, "sid": 299, "year": "25/26"}
    run = F.Run(1)
    assert F.fetch_item(item, run) is False and run.stop == "budget"
    sh = json.loads(F.shard_path("premier-league", 299).read_text(encoding="utf-8"))
    assert sh["next_page"] == 1 and sh["n"] == 100 and not sh["complete"] and sh["pages"] == 2
    run = F.Run(5)
    assert F.fetch_item(item, run) is True and run.budget.used == 1
    sh = json.loads(F.shard_path("premier-league", 299).read_text(encoding="utf-8"))
    assert sh["complete"] and sh["n"] == 130 and "offset=100" in api.paths[-1] and "limit=100" in api.paths[-1]


def test_fetch_item_404_is_an_empty_season(sandbox, monkeypatch):
    monkeypatch.setattr(sofascore, "get_json", FakeAPI(status=404))
    run = F.Run(5)
    assert F.fetch_item({"slug": "euro", "tid": 1, "sid": 9, "year": "2020"}, run) is True
    sh = json.loads(F.shard_path("euro", 9).read_text(encoding="utf-8"))
    assert sh["complete"] and sh["n"] == 0


def test_fetch_item_stops_at_403(sandbox, monkeypatch):
    api = FakeAPI(status=403)
    monkeypatch.setattr(sofascore, "get_json", api)
    run = F.Run(50)
    assert F.fetch_item({"slug": "euro", "tid": 1, "sid": 9}, run) is False
    assert run.stop == "403" and len(api.paths) == 1 and not run.can_call()


def test_fetch_item_refuses_wrong_page(sandbox, monkeypatch):
    api = FakeAPI([[_res(1, 1, 90)], [_res(2, 1, 90)]], page_field=1)        # offset ignored: always page 1
    monkeypatch.setattr(sofascore, "get_json", api)
    run = F.Run(5)
    F.fetch_item({"slug": "x", "tid": 1, "sid": 1}, run)
    assert run.stop == "paging" and len(api.paths) == 2


def test_live_refresh_starts_again(sandbox, monkeypatch):
    item = {"slug": "x", "tid": 1, "sid": 5, "live": True}
    F.write_json(F.shard_path("x", 5), {"fields": ["id", "team", "name", "minutesPlayed"], "rows": [[1, 2, "A", 90]],
                                        "complete": True, "next_page": 1, "pages": 1, "teams": {"2": "T"}})
    sh = F.open_shard(item)
    assert sh["complete"] is False and sh["next_page"] == 0 and "1:2" in sh["_rows"]


def test_backoff_hours():
    st = {"blocked_at": (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert F.backoff_left(st, NOW) == pytest.approx(F.BACKOFF_HOURS - 2)
    assert F.backoff_left({}, NOW) == 0.0


def test_lock_take_release(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "LOCK_DIR", tmp_path)
    monkeypatch.setattr(F, "LOCK_PATH", tmp_path / "sofascore.lock")
    me = os.getpid()
    assert F.take_lock(me) is True
    assert F.take_lock(me, wait_s=0) is False            # held by a live process
    assert F.release_lock(me + 1) is False and F.LOCK_PATH.exists()
    assert F.release_lock(me) is True and not F.LOCK_PATH.exists()
    F.LOCK_PATH.write_text(json.dumps({"pid": 999999991, "started": "x"}), encoding="utf-8")    # a dead owner
    assert F.take_lock(me) is True
    F.release_lock(me)


# ── the merge into people (oddsmarkets/football/analytics/unified.py, progression.py) ────────────────────────────

def _table(root: Path, slug: str, sid: int, name: str, year: str, rows: list[list], fields=None, teams=None):
    fields = fields or ["id", "team", "name", "minutesPlayed", "appearances", "matchesStarted", "goals", "assists",
                        "expectedGoals", "rating", "totalShots", "keyPasses"]
    F.write_json(root / "seasontables" / slug / str(sid) / "store.json",
                 {"v": 1, "slug": slug, "tid": 17, "sid": sid, "name": name, "year": year, "fields": fields, "rows": rows,
                  "teams": teams or {}, "complete": True, "n": len(rows)})


def _merge_world(tmp_path, with_tables=True, archive_row=False):
    from tests.test_unified import TODAY, _lineup, _m, _store
    from oddsmarkets.football.analytics import unified as U
    league = _store(
        [_m("1", "Home", "Away", 1, 2, 1, 0, "2025-09-01T15:00:00Z", 10),
         _m("2", "Away", "Home", 2, 1, 0, 0, "2026-03-01T15:00:00Z", 10),
         _m("3", "Home", "Away", 1, 2, 2, 2, "2026-09-01T15:00:00Z", 20)],
        {"2": _lineup("Home", "7", "Seven"), "3": _lineup("Home", "7", "Seven", goals=1)}, current=20,
        players={"7": {"n": "Seven", "pos": "F", "dob": 900000000}})
    league["detail_missing"] = {}
    seasons = {"premier-league": {"tournament_id": 17, "seasons": [{"season_id": 20, "name": "PL 26/27", "year": "26/27"},
                                                                 {"season_id": 10, "name": "PL 25/26", "year": "25/26"}]}}
    archive = {"seasons": {}, "season_lists": {}, "players": {}}
    if archive_row:
        archive["players"]["7"] = {"seasons": [{"tid": 17, "tname": "Premier League", "sid": 5, "sname": "Premier League 24/25",
                                                "year": "24/25", "team": "Home", "stats": {"appearances": 30, "minutesPlayed": 2000}}]}
    if with_tables:
        # the store's partial 2025/26 (one match of two with line-ups): the table's totals take over
        _table(tmp_path, "premier-league", 10, "Premier League 25/26", "25/26",
               [[7, 1, "Seven", 170, 2, 2, 3, 1, 0.9, 7.1, 6, 2], [999, 2, "Other", 900, 10, 10, 0, 0, None, 6.5, 1, 1]])
        # an edition no store holds: one row per team from the table
        _table(tmp_path, "premier-league", 5, "Premier League 24/25", "24/25",
               [[7, 1, "Seven", 2000, 30, 20, 9, 4, 7.5, 7.0, 50, 20]], teams={"1": "Home FC"})
        # before xG and shots: the row carries what the table has, nothing more
        _table(tmp_path, "premier-league", 4, "Premier League 15/16", "15/16",
               [[7, 2, "Seven", 1500, 20, 15, 4, 1]], fields=["id", "team", "name", "minutesPlayed", "appearances",
                                                               "matchesStarted", "goals", "assists"], teams={"2": "Away"})
        # a zero-minute row is not a season
        _table(tmp_path, "premier-league", 3, "Premier League 14/15", "14/15", [[7, 2, "Seven", 0, 0, 0, 0, 0]],
               fields=["id", "team", "name", "minutesPlayed", "appearances", "matchesStarted", "goals", "assists"])
    squads = {"teams": {"1": {"name": "Home", "fetched_at": "2026-10-01T00:00:00Z", "players": [{"id": "7", "n": "Seven", "pos": "F"}]}}}
    u = U.Unified(tmp_path, seasons, archive=archive, squads=squads, today=TODAY)
    u.add_store("premier-league", league)
    u.finish()
    return json.loads((tmp_path / "people" / "7.json").read_text(encoding="utf-8")), u


def test_tables_fill_the_seasons_before_the_stores(tmp_path):
    p, u = _merge_world(tmp_path)
    last = next(s for s in p["seasons"] if s["sid"] == 10)
    assert last["coverage"] == "totals" and last["src"] == "table" and last["min"] == 170 and last["g"] == 3
    assert last["lineups"] == {"apps": 1, "min": 90} and last["sh"] == 6 and last["xg"] == 0.9
    from oddsmarkets.football.analytics.unified import HIST_FIELDS, unpack_hist
    assert "archive" not in p and p["hist"]["f"] == HIST_FIELDS
    assert p["hist"]["r"][-1] == ["premier-league", 4, "15/16", "2015/16", 2, 20, 15, 1500, 4, 1]   # trailing nulls dropped
    assert p["teams"]["2"]["name"] == "Away"                     # the table's clubs once, in `teams`
    arch = {r["sid"]: r for r in unpack_hist(p)}
    assert set(arch) == {5, 4}                                   # 14/15 had no minutes; 25/26 is the store's row
    r = arch[5]
    assert r["era"] == "2024/25" and r["season"] == "24/25" and r["comp"] == "premier-league" and r["kind"] == "league"
    assert r["tid"] == 1 and r["team"] == "Home" and r["src"] == "table" and r["coverage"] == "totals"
    assert (r["min"], r["apps"], r["starts"], r["g"], r["a"], r["xg"], r["rt"], r["sh"], r["kp"]) == (2000, 30, 20, 9, 4, 7.5, 7.0, 50, 20)
    old = arch[4]
    assert old["era"] == "2015/16" and old["team"] == "Away" and "xg" not in old and "rt" not in old and "sh" not in old
    years = {y["era"]: y for y in p["years"]}
    assert set(years) == {"2026/27", "2025/26", "2024/25", "2015/16"} and years["2024/25"]["min"] == 2000
    assert "999" not in {str(k) for k in u.table_rows}           # only the people the build writes


def test_tables_replace_the_archive_row_of_the_same_edition(tmp_path):
    p, _ = _merge_world(tmp_path, archive_row=True)
    from oddsmarkets.football.analytics.unified import unpack_hist
    assert "archive" not in p
    rows = [r for r in unpack_hist(p) if r.get("sid") == 5]
    assert len(rows) == 1 and rows[0]["src"] == "table" and rows[0]["min"] == 2000


def test_without_tables_nothing_changes(tmp_path):
    p, _ = _merge_world(tmp_path, with_tables=False)
    assert "archive" not in p and "hist" not in p and next(s for s in p["seasons"] if s["sid"] == 10)["coverage"] == "partial"


def test_progression_marks_the_season_totals(tmp_path):
    from oddsmarkets.football.analytics import progression as PR
    p, _ = _merge_world(tmp_path)
    rows = {r["era"]: r for r in PR.person_rows(p, {}, {})}
    assert rows["2024/25"]["st"] == 1.0 and rows["2015/16"]["st"] == 1.0 and "st" not in rows["2026/27"]
    v = rows["2024/25"]["_v"]
    assert v["xg_90"] == pytest.approx(90 * 7.5 / 2000) and v["shots_90"] == pytest.approx(90 * 50 / 2000)
    old = rows["2015/16"]["_v"]
    assert "xg_90" not in old and "shots_90" not in old and "rating" not in old and old["goals_90"] == pytest.approx(90 * 4 / 1500)
    assert rows["2024/25"]["_kind"] == "box"                     # no Lab line: box numbers only
