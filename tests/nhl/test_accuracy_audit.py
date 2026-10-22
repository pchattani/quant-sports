"""Accuracy audit (Oct 2026): goalie of record, bench minors, and late re-reads of final games."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from oddsmarkets.nhl import derive
from oddsmarkets.nhl.analytics import goalies
from oddsmarkets.nhl.sources import nhl


def _fetch_module():
    p = Path(__file__).resolve().parents[2] / "scripts" / "nhl_fetch.py"
    spec = importlib.util.spec_from_file_location("nhl_fetch_audit_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_decision_goes_to_goalie_of_record_not_most_time():
    # LAK 1-4 on 13 Oct 2026: Kuemper started, was pulled after the deciding goal, Forsberg finished with more time.
    games = {"2026020104": {"home": "LAK", "away": "XYZ", "hs": 1, "as": 4, "status": "final", "ot": False, "so": False,
                            "period": 3, "goalies": {"home": {"starter": 8475311, "used": [8476341, 8475311],
                                                              "decision": 8475311},
                                                     "away": {"starter": 1, "used": [1], "decision": 1}}},
             # an overtime loss whose boxscore decision ("O") was not stored: the goalie with the most time
             "2026020141": {"home": "MTL", "away": "SJS", "hs": 3, "as": 4, "status": "final", "ot": True, "so": False,
                            "period": 4, "goalies": {"home": {"starter": 8482487, "used": [8482487], "decision": None},
                                                     "away": {"starter": 8477968, "used": [8477968],
                                                              "decision": 8477968}}}}
    gg = pd.DataFrame([
        {"game_id": "2026020104", "pid": 8475311.0, "team": "LAK", "toi": 1500.0},
        {"game_id": "2026020104", "pid": 8476341.0, "team": "LAK", "toi": 2100.0},
        {"game_id": "2026020104", "pid": 1.0, "team": "XYZ", "toi": 3600.0},
        {"game_id": "2026020141", "pid": 8482487.0, "team": "MTL", "toi": 3722.0},
        {"game_id": "2026020141", "pid": 8477968.0, "team": "SJS", "toi": 3733.0},
    ])
    dec = goalies.decisions(SimpleNamespace(games=games), gg)
    assert dec[("2026020104", 8475311.0)] == "l"
    assert ("2026020104", 8476341.0) not in dec                 # the reliever gets no decision
    assert dec[("2026020104", 1.0)] == "w"
    assert dec[("2026020141", 8482487.0)] == "otl"
    assert dec[("2026020141", 8477968.0)] == "w"


def test_box_keeps_overtime_loss_decision():
    raw = {"playerByGameStats": {
        "homeTeam": {"goalies": [{"playerId": 8484170, "toi": "00:00", "starter": False},
                                 {"playerId": 8482487, "toi": "62:02", "starter": True, "decision": "O"}]},
        "awayTeam": {"goalies": [{"playerId": 8477968, "toi": "62:13", "starter": True, "decision": "W"}]}}}
    gl = nhl.goalies_from_box(raw)
    assert gl["home"]["decision"] == 8482487 and gl["away"]["decision"] == 8477968
    assert gl["home"]["used"] == [8482487]


def test_bench_minor_not_charged_to_server():
    ben = {"typeCode": "BEN", "descKey": "too-many-men-on-the-ice", "duration": 2, "servedByPlayerId": 8471214,
           "drawnByPlayerId": None, "eventOwnerTeamId": 15}
    assert derive._actors("penalty", ben)[4] is None
    mn = {"typeCode": "MIN", "duration": 2, "committedByPlayerId": 8474151, "servedByPlayerId": 8470000,
          "drawnByPlayerId": 8471214}
    assert derive._actors("penalty", mn)[4:] == (8474151, 8471214)


def test_late_read_checkpoints():
    nf = _fetch_module()
    today = date(2026, 10, 22)
    # game of 18 Oct read on 19 Oct 13:00 (settled): due again from 21 Oct (day + 3)
    assert nf.late_read_due("2026-10-18", "2026-10-19T13:00:00Z", today)
    assert not nf.late_read_due("2026-10-18", "2026-10-21T00:30:00Z", today)          # read at the checkpoint
    assert not nf.late_read_due("2026-10-20", "2026-10-21T13:00:00Z", today)          # day + 3 not reached
    assert nf.late_read_due("2026-10-15", "2026-10-21T00:30:00Z", today)              # day + 7 (22 Oct) passed
    assert not nf.late_read_due("2026-10-15", "2026-10-22T00:05:00Z", today)
    assert not nf.late_read_due("2026-10-15", None, today)


def test_todo_rereads_recent_finals_once_per_checkpoint(monkeypatch, tmp_path):
    nf = _fetch_module()
    today = date(2026, 10, 22)
    games = {gid: {"game_id": gid, "date": d, "status": "final", "type": 2}
             for gid, d in (("1", "2026-10-18"), ("2", "2026-10-10"), ("3", "2026-10-20"))}
    for g in games.values():
        (tmp_path / f"{g['game_id']}.gz").write_text("x")
    at = {"1": "2026-10-19T13:00:00Z", "2": "2026-10-11T13:00:00Z", "3": "2026-10-21T13:00:00Z"}
    s = {"season": 20262027, "games": games, "meta": {"pbp": dict(at), "shifts": dict(at)}}
    path = lambda season, gid: tmp_path / f"{gid}.gz"  # noqa: E731
    monkeypatch.setattr(nf, "final_games", lambda s, newest_first=True: list(s["games"].values()))
    assert [g["game_id"] for g in nf._todo(s, "pbp", path, True, today, None)] == ["1"]   # 2 is past the window
    assert nf._todo(s, "shifts", path, True, today, None) == []                         # shifts are not re-read
    assert nf._todo(s, "pbp", path, False, today, None) == []                           # only with --refresh-current


def test_award_fit_survives_a_missing_feature_and_degenerate_fits_are_not_shown():
    import numpy as np
    from oddsmarkets.nhl.models import awards as A
    X = np.array([[1.0, np.nan], [2.0, np.nan], [3.0, np.nan]])
    Z = A._z(X)
    assert np.isfinite(Z).all() and (Z[:, 1] == 0).all()
    # the committed Hart / Norris / Selke fits (all-zero coefficients, NaN log-likelihood) are not usable
    assert not A.usable_fit({"ok": True, "beta": [0.0, 0.0, 0.0], "loglik": None})
    assert A.usable_fit({"ok": True, "beta": [0.1, 2.0], "loglik": -10.2})
    groups = [(A._z(np.array([[5.0, np.nan], [1.0, np.nan], [2.0, np.nan]])), 0) for _ in range(8)]
    b = A.fit_clogit(groups)
    assert np.isfinite(b).all() and b[0] > 0 and abs(b[1]) < 1e-9
    import pandas as pd
    ps = pd.DataFrame({"player": ["1", "2"], "name": ["A", "B"], "team": ["T", "U"], "pos": ["C", "D"], "gp": [5, 5],
                       "g": [3, 1], "a": [2, 1], "pts": [5, 2], "pm": [1, 0], "toi_pg": [20, 18], "rookie": [False, False],
                       "age": [25, 26], "gp_g": [np.nan, np.nan], "xga": [np.nan] * 2, "ga": [np.nan] * 2,
                       "gsax": [np.nan] * 2, "sv": [np.nan] * 2, "team_pct": [0.6, 0.5], "team_gp": [5, 5],
                       "value": [1.0, 0.5], "value_def": [0.2, 0.1]})
    fitd = {"awards": {"hart": {"ok": True, "beta": [0.0] * 5, "loglik": None}}}
    out = A.predict(20262027, ps=ps, fitd=fitd, games_left={"T": 77, "U": 77})
    assert out["hart"]["ok"] is False and "degenerate" in out["hart"]["reason"]


def test_scoring_races_use_last_season_rates_from_disk(monkeypatch):
    import numpy as np
    import pandas as pd
    from oddsmarkets.nhl.models import awards as A
    prev = pd.DataFrame({"player": ["1", "2"], "name": ["A", "B"], "team": ["T", "U"], "pos": ["C", "C"],
                         "gp": [82.0, 82.0], "g": [50.0, 20.0], "pts": [130.0, 60.0]})
    seen = []
    monkeypatch.setattr(A, "_from_stats_files", lambda s: seen.append(s) or prev)
    cur = pd.DataFrame({"player": ["1", "2"], "name": ["A", "B"], "team": ["T", "U"], "pos": ["C", "C"], "gp": [5, 5],
                        "g": [3, 3], "a": [3, 3], "pts": [6, 6], "team_gp": [5, 5]})
    for c in A.PS_COLS:
        if c not in cur:
            cur[c] = np.nan
    out = A.predict(20262027, ps=cur, fitd={"awards": {}}, games_left={"T": 77, "U": 77}, n=2000)
    assert seen == [20252026]
    assert out["ross"]["ok"] and out["ross"]["probs"]["1"] > 0.9
    assert out["richard"]["ok"]


def test_game_page_rebuilds_when_the_shift_charts_fill_in():
    from oddsmarkets.nhl.analytics import games
    g = {"status": "final", "hs": 3, "as": 4, "period": 4, "ot": True}
    s0 = games.page_sig(g, 300, {"v": 1})
    assert games.page_sig(g, 300, {"v": 1}, None) == s0                 # past seasons keep their signatures
    assert games.page_sig(g, 300, {"v": 1}, 2964) != games.page_sig(g, 300, {"v": 1}, 3733)
