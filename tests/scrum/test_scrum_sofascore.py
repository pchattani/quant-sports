"""The Quant Scrum's Sofascore source (approved 2 Nov 2026): the call rules (hourly cap, the six-hour back-off after any
403 on this PC, stop at the first 403, the shared lock, never on CI), the parsing, and the merge (statistics into the
tests ESPN carries without them; Sofascore-only tests added only between proven union sides; the switch)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from oddsmarkets.rugby import sofa, store
from oddsmarkets.rugby.sources import sofascore as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
NOW = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """Every file the source touches under tmp_path; CI markers cleared so the client may 'call' (a fake getter)."""
    monkeypatch.setenv("RUGBY_STORES", str(tmp_path / "stores"))
    monkeypatch.setenv("RUGBY_SOFA_STATE", str(tmp_path / "state.json"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("SOURCE_SOFASCORE_RUGBY_ENABLED", raising=False)
    monkeypatch.setattr(sf, "football_state_path", lambda: tmp_path / "football_state.json")
    monkeypatch.setattr(sf, "hourly_log_path", lambda: tmp_path / "refresh.log")
    monkeypatch.setattr(sf, "lock_path", lambda: tmp_path / "locks" / "sofascore.lock")
    sofa._LOADED.clear()
    return tmp_path


def _ev(eid, day, home, away, hs, as_, ut="International Friendly", hid=None, aid=None, st="finished", gender="M"):
    ts = int(datetime.fromisoformat(day + "T15:00:00+00:00").timestamp())
    return {"id": eid, "startTimestamp": ts, "status": {"type": st},
            "tournament": {"name": ut, "category": {"name": "International"}, "uniqueTournament": {"id": 900, "name": ut}},
            "season": {"name": ut + " 2026"},
            "homeTeam": {"id": hid or abs(hash(home)) % 10000, "name": home, "nameCode": home[:3].upper(), "national": True, "gender": gender},
            "awayTeam": {"id": aid or abs(hash(away)) % 10000, "name": away, "nameCode": away[:3].upper(), "national": True, "gender": gender},
            "homeScore": {"current": hs, "period1": hs // 2}, "awayScore": {"current": as_, "period1": as_ // 2}}


# ── the rules ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_backoff_reads_our_state_the_football_state_and_the_hourly_log(iso):
    assert sf.backoff_left({}, NOW) == (0.0, None)
    st = {"blocked_at": (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    left, who = sf.backoff_left(st, NOW)
    assert who == "rugby" and abs(left - 4.0) < 1e-6
    (iso / "football_state.json").write_text(json.dumps({"blocked_at": (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}))
    left, who = sf.backoff_left({}, NOW)
    assert who == "football season tables" and abs(left - 5.0) < 1e-6
    # the hourly task's log: local time with an offset; a fractional second containing "403" is not a 403
    (iso / "refresh.log").write_text("[2026-11-10T09:30:00.1234403-05:00] stores updated and pushed to main (abc)\n"
                                     "[2026-11-10T09:59:21.5594408-05:00] League fetch failed (continuing)\n", encoding="utf-8")
    left, who = sf.backoff_left({}, NOW)          # 09:59 EST = 14:59 UTC, one minute before NOW
    assert who == "football hourly log" and left > 5.9
    assert sf.backoff_left({}, NOW + timedelta(hours=7)) == (0.0, None)


def test_client_caps_the_hour_stops_at_the_first_403_and_never_runs_on_ci(iso, monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        return (403, None) if "boom" in url else (200, {"ok": 1})
    recent = [(datetime.now(timezone.utc) - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ") for m in range(28)]
    cl = sf.Client(budget=30, interval=0, state={"calls": recent}, get=fake)
    assert cl.budget == 2                           # 28 calls in the last hour: two left of the 30
    assert cl.get("/a") == {"ok": 1}
    with pytest.raises(sf.Blocked):
        cl.get("/boom")
    assert cl.state["blocked_at"] and len(calls) == 2 and calls[0] == "https://api.sofascore.com/api/v1/a"
    with pytest.raises(sf.OutOfBudget):
        cl.get("/c")
    monkeypatch.setenv("CI", "true")
    with pytest.raises(sf.OutOfBudget):
        sf.Client(budget=5, interval=0, state={}, get=fake).get("/a")
    monkeypatch.delenv("CI")
    monkeypatch.setenv("SOURCE_SOFASCORE_RUGBY_ENABLED", "0")
    with pytest.raises(sf.OutOfBudget):
        sf.Client(budget=5, interval=0, state={}, get=fake).get("/a")


def test_lock_is_shared_and_only_its_owner_releases_it(iso):
    import os
    me = os.getpid()
    assert sf.take_lock(me)
    assert not sf.take_lock(222)                    # held by a live process
    sf.release_lock(222)
    assert sf.lock_path().exists()
    sf.release_lock(me)
    assert not sf.lock_path().exists()
    sf.lock_path().write_text(json.dumps({"pid": 99999991, "started": "2026-11-10T00:00:00Z"}))
    assert sf.take_lock(me)                         # a dead owner's lock is broken
    sf.release_lock(me)


def test_run_skips_inside_the_backoff_and_records_a_403(iso, monkeypatch):
    job = pytest.importorskip("scrum_sofascore")      # a PC-only script: not in the public build repo
    monkeypatch.setattr(job, "espn_index", lambda: {})
    st = {"blocked_at": (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "calls": [], "runs": []}
    (iso / "state.json").write_text(json.dumps(st))
    rep = job.run(30, 0, "2026-11-01")
    assert rep["calls"] == 0 and rep["stop"].startswith("backoff")
    (iso / "state.json").write_text(json.dumps({"calls": [], "runs": []}))
    n = {"c": 0}

    def fake(url):
        n["c"] += 1
        return (403, None) if n["c"] == 3 else (200, {"events": []})
    cl = sf.Client(budget=30, interval=0, state=sf.load_state(), get=fake)
    rep = job.run(30, 0, "2026-11-01", client=cl)
    assert rep["stop"] == "403" and rep["calls"] == 3      # stopped at the first 403, nothing after it
    saved = json.loads((iso / "state.json").read_text())
    assert saved["blocked_at"] and not sf.lock_path().exists()


def test_run_walks_days_then_details_within_the_budget(iso, monkeypatch):
    job = pytest.importorskip("scrum_sofascore")      # a PC-only script: not in the public build repo
    monkeypatch.setattr(job, "espn_index", lambda: {})
    days = {"2026-11-07": [_ev(1, "2026-11-07", "Portugal", "Georgia", 20, 25), _ev(2, "2026-11-07", "England", "Samoa", 30, 10,
                                                                                  ut="Rugby League International")]}

    def fake(url):
        if "/scheduled-events/" in url:
            return 200, {"events": days.get(url.rsplit("/", 1)[1], [])}
        if url.endswith("/statistics"):
            return 200, {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [{"name": "Tries", "home": "2", "away": "3"}]}]}]}
        return 404, None
    cl = sf.Client(budget=12, interval=0, state=sf.load_state(), get=fake)
    rep = job.run(12, 0, "2026-11-01", today=datetime(2026, 11, 10).date(), client=cl)
    s = job.load_store()
    assert list(s["events"]) == ["1"]                      # the rugby league test is not kept
    assert rep["calls"] <= 12 and s["detail"]["1"]["done"] == 1
    assert s["detail"]["1"]["stats"]["Tries"][:2] == [2.0, 3.0]


# ── parsing and merging ─────────────────────────────────────────────────────────────────────────────────────────

def test_union_filter_keeps_tests_and_drops_league_sevens_age_grade_and_a_sides():
    keep = sf.parse_event(_ev(1, "2026-11-07", "Spain", "Romania", 30, 12, ut="Rugby Europe Championship"))
    assert sf.is_union_test(keep) and sf.scope_of(keep) == "men"
    assert sf.is_union_test(sf.parse_event(_ev(9, "2026-07-04", "New Zealand", "France", 34, 32, ut="Nations Championship")))
    for ut in ("Rugby League World Cup", "World Rugby Sevens Series", "U20 Championship", "Pacific Challenge"):
        e = sf.parse_event(_ev(2, "2026-11-07", "Fiji", "Tonga", 20, 10, ut=ut))
        assert sf.is_union_test(e) == (ut == "Pacific Challenge"), ut
    assert not sf.is_union_test(sf.parse_event(_ev(3, "2026-11-07", "England A", "Ireland A", 20, 10)))
    assert not sf.is_union_test(sf.parse_event(_ev(4, "2026-11-07", "Leinster", "Munster", 20, 10)))
    w = sf.parse_event(_ev(5, "2026-04-04", "England", "France", 40, 10, ut="Women's Six Nations", gender="F"))
    assert sf.scope_of(w) == "women"


def test_statistics_and_lineups_parse():
    st = sf.parse_statistics({"statistics": [
        {"period": "1ST", "groups": [{"statisticsItems": [{"name": "Tries", "home": "1", "away": "0"}]}]},
        {"period": "ALL", "groups": [{"statisticsItems": [
            {"name": "Possession", "home": "55%", "away": "45%", "homeValue": 55, "awayValue": 45, "key": "possession"},
            {"name": "Scrums won", "home": "5/6 (83%)", "away": "7/7 (100%)"},
            {"name": "Tackles", "home": "120", "away": "150"}, {"name": "Missed tackles", "home": "20", "away": "10"}]}]}]})
    assert st["possession"] == [55, 45] and st["Scrums won"] == [5.0, 7.0, 6.0, 7.0]
    h, a = sofa.team_stats(st)
    assert h["poss"] == 0.55 and a["scrums_won"] == 7 and h["scrums"] == 6 and h["tackle_pct"] == round(120 / 140, 3)
    lu = sf.parse_lineups({"home": {"players": [{"player": {"id": 7, "name": "Antoine Dupont"}, "shirtNumber": 9, "position": "B",
                                                 "substitute": False, "statistics": {"tries": 1, "tackles": 5, "rating": 8.1}}]}})
    assert lu["h"][0][:5] == [7, "Antoine Dupont", 9, "B", 0]
    assert sofa.player_stats(lu["h"][0][6]) == {"tries": 1, "tk": 5}


def _row(mid, day, home, away, hs, as_, hid, aid, lh=None, la=None, hstat=None, source=None):
    m = {"id": mid, "comp": "nc", "date": day + "T15:00Z", "status": "final", "home": {"id": hid, "name": home},
         "away": {"id": aid, "name": away}, "hs": hs, "as": as_, "lh": lh or [], "la": la or []}
    if hstat:
        m["hstat"], m["astat"] = hstat, dict(hstat)
    if source:
        m["source"] = source
    return m


def _side_store(iso, events, detail):
    store.write_gz(iso / "stores" / "side" / "sofascore.json.gz", {"v": 1, "events": events, "detail": detail, "days": {}})
    sofa._LOADED.clear()


def test_merge_fills_statistics_adds_proven_tests_and_respects_the_switch(iso, monkeypatch):
    def ev(eid, day, h, a, hs, as_, hid, aid):
        e = sf.parse_event(_ev(eid, day, h, a, hs, as_, hid=hid, aid=aid))
        e["scope"] = "men"
        return e
    events = {"1": ev(1, "2026-07-04", "France", "New Zealand", 32, 34, 10, 11),         # ESPN has it, home and away swapped
              "2": ev(2, "2026-03-01", "Portugal", "Georgia", 20, 25, 20, 21),           # Wikipedia has it: proves both sides
              "3": ev(3, "2026-11-07", "Portugal", "Georgia", 13, 9, 20, 21),            # only Sofascore: added
              "4": ev(4, "2026-11-07", "Tonga", "Samoa", 30, 10, 30, 31),                # only Sofascore, unproven sides: left out
              "5": ev(5, "2026-02-07", "Ireland", "Wales", 9, 9, 40, 41)}                # score conflict with ESPN: ignored
    stats = {"Tries": [3, 4], "Possession": [40, 60], "Carries": [100, 130]}
    detail = {"1": {"done": 1, "stats": stats, "lu": {"h": [[1, "Antoine Dupont", 9, "B", 0, 0, {"tries": 1, "carries": 6}]],
                                                     "a": [[2, "Cam Roigard", 9, "B", 0, 0, {"carries": 4}]]}},
              "3": {"done": 1, "stats": stats}}
    _side_store(iso, events, detail)
    espn = [_row("603975", "2026-07-04", "New Zealand", "France", 34, 32, "8", "9", lh=[["228027", 9, "SH", 1, 0, {}]],
                 la=[["300000", 9, "SH", 1, 0, {}]]),
            _row("w1", "2026-03-01", "Portugal", "Georgia", 20, 25, "wPOR", "wGEO", source="wikipedia"),
            _row("700", "2026-02-07", "Ireland", "Wales", 20, 9, "3", "4")]
    ath = {"228027": {"name": "Cam Roigard"}, "300000": {"name": "Antoine Dupont"}}
    out, rep = sofa.merge("men", [json.loads(json.dumps(m)) for m in espn], ath)
    assert rep["matched"] == 2 and rep["conflicts"] == 1 and rep["added"] == 1 and rep["unproven"] == 1
    nz = next(m for m in out if m["id"] == "603975")
    assert nz["hstat"]["tries"] == 4 and nz["astat"]["tries"] == 3 and nz["hstat"]["poss"] == 0.6   # oriented to ESPN's home
    assert nz["lh"][0][5] == {"car": 4} and nz["la"][0][5] == {"tries": 1, "car": 6} and nz["stat_src"] == "sofascore"
    new = next(m for m in out if m["id"] == "s3")
    assert new["source"] == "sofascore" and new["home"]["id"] == "wPOR" and (new["hs"], new["as"]) == (13, 9) and new["hstat"]["carries"] == 100
    assert not any(m["id"] == "s4" for m in out)
    # the surname check: a shirt number that belongs to someone else is not filled
    ath2 = {"228027": {"name": "Someone Else"}, "300000": {"name": "Antoine Dupont"}}
    out2, _ = sofa.merge("men", [json.loads(json.dumps(m)) for m in espn], ath2)
    assert next(m for m in out2 if m["id"] == "603975")["lh"][0][5] == {}
    monkeypatch.setenv("SOURCE_SOFASCORE_RUGBY_ENABLED", "0")
    out3, rep3 = sofa.merge("men", [dict(m) for m in espn], ath)
    assert rep3 == {"enabled": False} and len(out3) == 3


# ── the progression payloads (10 Nov 2026) ──────────────────────────────────────────────────────────────────────

def test_form_years_counts_results_and_our_pre_match_expectation():
    from types import SimpleNamespace
    from oddsmarkets.rugby import pages
    ms = [{"id": "1", "date": "2025-02-01T15:00Z", "home": {"id": "A"}, "away": {"id": "B"}, "hs": 20, "as": 10},
          {"id": "2", "date": "2025-03-01T15:00Z", "home": {"id": "B"}, "away": {"id": "A"}, "hs": 15, "as": 15},
          {"id": "3", "date": "2026-07-01T15:00Z", "home": {"id": "C"}, "away": {"id": "A"}, "hs": 30, "as": 3}]
    S = SimpleNamespace(finals=ms)
    w = {"fc": {"1": {"p_home": 0.6, "p_draw": 0.0, "p_away": 0.4, "margin": 4.0},
                "2": {"p_home": 0.5, "p_draw": 0.1, "p_away": 0.4, "margin": 2.0}}}
    rows = pages.form_years(S, w, "A")
    assert rows[0][:7] == [2025, 2, 1, 1, 0, 35, 25]
    assert rows[0][7] == round(0.6 + 0.4 + 0.05, 2) and rows[0][8] == 2 and rows[0][9] == round(((10 - 4) + (0 + 2)) / 2, 1)
    assert rows[1][:5] == [2026, 1, 0, 0, 1] and rows[1][8] == 0 and rows[1][9] is None


def test_progression_ref_quantiles_per_year_and_group():
    from oddsmarkets.rugby import pages
    ana = {"players": {str(i): {"grp": "lock", "seasons": {2025: {"qual": 1, "rates": {"tk": float(i)}}}} for i in range(11)}}
    ana["players"]["x"] = {"grp": "lock", "seasons": {2025: {"qual": 0, "rates": {"tk": 999.0}}}}
    ref = pages.progression_ref(None, ana)
    g = ref["seasons"]["2025"]["lock"]
    assert g["n"] == 11 and g["m"]["tk"] == [1.0, 2.5, 5.0, 7.5, 9.0]
