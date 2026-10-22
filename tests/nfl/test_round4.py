"""Round 4 (22 Oct 2026): ESPN injury snapshots, kept final summaries, forecast-at-decision columns in the walk-forward
fit, and the no-look-ahead of the referee and Kalman features."""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from oddsmarkets.nfl import store as st
from oddsmarkets.nfl.edge import fit as FT
from oddsmarkets.nfl.edge import round4 as R4
from oddsmarkets.nfl.sources import espn


def _entry(aid, status, date, typ="Knee"):
    return {"status": status, "date": date, "details": {"type": typ, "location": typ, "returnDate": None},
            "athlete": {"displayName": "X", "position": {"abbreviation": "WR"},
                        "links": [{"href": f"https://www.espn.com/nfl/player/_/id/{aid}/x"}]},
            "shortComment": "comment text is not kept"}


def test_league_injury_rows_ids_from_links_and_team_abbr():
    raw = {"injuries": [{"id": "22", "injuries": [_entry("3127287", "Questionable", "2026-10-22T02:06Z")]},
                        {"id": "99999", "injuries": [_entry("1", "Out", "2026-10-22T02:06Z")]}]}
    rows = espn.league_injury_rows(raw, 2026)
    assert list(rows) == ["ARI"]                                          # an unknown team id is dropped
    assert rows["ARI"] == [["3127287", "Questionable", "2026-10-22T02:06Z", "Knee", "Knee", None, "WR"]]
    assert "comment" not in json.dumps(rows)


def test_injury_log_appends_only_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("GRIDIRON_DATA", str(tmp_path))
    log = st.load_injury_log(2026)
    a = [["1", "Questionable", "2026-10-22T02:06Z", "Knee", "Knee", None, "WR"]]
    assert st.append_injury_log(log, "ARI", "2026-10-22T10:00:00Z", a)
    assert not st.append_injury_log(log, "ARI", "2026-10-22T11:00:00Z", list(reversed(a)))   # same list: no snapshot
    b = [["1", "Out", "2026-10-23T20:00Z", "Knee", "Knee", None, "WR"]]
    assert st.append_injury_log(log, "ARI", "2026-10-23T21:00:00Z", b)
    st.save_injury_log(2026, log)
    back = st.load_injury_log(2026)
    assert [s[0] for s in back["teams"]["ARI"]] == ["2026-10-22T10:00:00Z", "2026-10-23T21:00:00Z"]
    assert back["teams"]["ARI"][1][1][0][1] == "Out" and back["updated_at"]
    with gzip.open(st.injury_log_path(2026), "rt", encoding="utf-8") as fh:
        assert json.load(fh)["teams"]


def test_kept_summary_is_the_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("GRIDIRON_RAW", str(tmp_path))
    monkeypatch.setenv("GRIDIRON_CACHE", str(tmp_path / "cache"))
    assert st.read_espn_summary(2026, "2026_07_A_B") is None
    st.write_json_gz(st.espn_summary_keep_path(2026, "2026_07_A_B"), {"status": "final", "box": {}})
    assert st.read_espn_summary(2026, "2026_07_A_B")["status"] == "final"
    st.write_json(st.espn_summary_path(2026, "2026_07_A_B"), {"status": "live"})
    assert st.read_espn_summary(2026, "2026_07_A_B")["status"] == "live"   # the day's cache first


def _rows(seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for s in (2004, 2005, 2006):
        for w in range(1, 9):
            for g in range(8):
                x = rng.normal()
                out.append({"game_id": f"{s}_{w}_{g}", "season": s, "week": w, "date": pd.Timestamp(f"{s}-09-01") + pd.Timedelta(days=7 * w),
                            "gtype": "REG", "played": True, "n_games_rated": 1, "f_net": x, "f_hfa": 1.0, "t_off": 0.0,
                            "t_x": rng.normal(), "base": 44.0})
    R = pd.DataFrame(out)
    R["margin"] = np.round(3 * R["f_net"] + rng.normal(0, 3, len(R)))
    R["total"] = np.round(44 + 4 * R["t_x"] + rng.normal(0, 3, len(R)))
    return R


def test_pred_columns_feed_only_the_predicted_week():
    R = _rows()
    kw = dict(start=2006, margin_keys=False, total_keys=False)
    a = FT.wf_predict(R.copy(), ("f_net",), ("t_x",), **kw)
    b = FT.wf_predict(R.assign(t_x__pred=R["t_x"]), ("f_net",), ("t_x",), **kw)
    assert np.allclose(a["mu_t"], b["mu_t"])                               # identical forecast = no change
    c = FT.wf_predict(R.assign(t_x__pred=R["t_x"] + 1.0), ("f_net",), ("t_x",), **kw)
    d = (c["mu_t"] - a["mu_t"]).to_numpy()
    assert np.all(d > 3.0) and np.all(d < 5.0)                             # +1 forecast x coefficient ~4, fit unchanged
    assert np.allclose(c["sigma_t"], a["sigma_t"])                         # training used the realised column


def _games():
    rows = []
    for s in (2010, 2011):
        for w in range(1, 7):
            rows.append({"game_id": f"{s}_{w}_A_B", "season": s, "week": w, "date": pd.Timestamp(f"{s}-09-01") + pd.Timedelta(days=7 * w),
                         "home": "BUF" if w % 2 else "MIA", "away": "MIA" if w % 2 else "BUF", "neutral": False,
                         "line": 3.0 if w % 2 else -3.0, "total_line": 44.0, "margin": 3.0, "total": 44.0, "played": True})
    return pd.DataFrame(rows)


def test_kalman_uses_only_earlier_weeks():
    prm = {"q": 0.3, "rho": 0.8, "q0": 9.0, "sl": 2.0, "res": True, "qt": 0.3, "rhot": 0.8, "q0t": 4.0, "st": 2.0}
    G = _games()
    a = R4.kalman(G, prm)
    G2 = G.copy()
    G2.loc[G2["game_id"] == "2011_5_A_B", ["line", "margin", "total_line", "total"]] = [30.0, 40.0, 70.0, 90.0]
    b = R4.kalman(G2, prm)
    same = a["game_id"].str.startswith("2010") | a["game_id"].isin(["2011_1_A_B", "2011_2_A_B", "2011_3_A_B",
                                                                       "2011_4_A_B", "2011_5_A_B"])
    assert np.allclose(a.loc[same, "kf_line"], b.loc[same, "kf_line"])      # week 5's own line never enters week 5
    assert np.allclose(a.loc[same, "kf_total"], b.loc[same, "kf_total"])
    assert not np.isclose(a.loc[a["game_id"] == "2011_6_A_B", "kf_line"].iloc[0],
                          b.loc[b["game_id"] == "2011_6_A_B", "kf_line"].iloc[0])
    # openB values are one week staler: week 6's _b does not see week 5
    assert np.isclose(a.loc[a["game_id"] == "2011_6_A_B", "kf_line_b"].iloc[0],
                      b.loc[b["game_id"] == "2011_6_A_B", "kf_line_b"].iloc[0])


def test_referee_effect_ignores_the_game_and_later_games(tmp_path, monkeypatch):
    G = _games().assign(mode="close")
    sch = pd.DataFrame({"game_id": G["game_id"], "referee": "Ref One"})
    sp = tmp_path / "games.parquet"
    sch.to_parquet(sp)
    monkeypatch.setattr(R4.D, "schedules_path", lambda: sp)
    monkeypatch.setattr(R4, "penalties", lambda seasons: pd.DataFrame({"game_id": G["game_id"], "pen": 12.0, "season": G["season"]}))
    a = R4.referee(G, k=5.0).set_index("game_id")
    G2 = G.copy()
    G2.loc[G2["game_id"] == "2011_4_A_B", "total"] = 80.0
    b = R4.referee(G2, k=5.0).set_index("game_id")
    assert a.loc["2010_1_A_B", "t_ref"] == 0.0                              # no earlier games
    for gid in ("2010_3_A_B", "2011_3_A_B", "2011_4_A_B"):
        assert a.loc[gid, "t_ref"] == b.loc[gid, "t_ref"]                   # the changed game and earlier ones: same
    assert b.loc["2011_5_A_B", "t_ref"] > a.loc["2011_5_A_B", "t_ref"]      # later games see it


def test_injury_changes_week_window_and_baseline(tmp_path, monkeypatch):
    from oddsmarkets.nfl.analytics import games as G
    from oddsmarkets.nfl.analytics import people as PP
    monkeypatch.setenv("GRIDIRON_DATA", str(tmp_path))
    monkeypatch.setattr(PP, "espn_xwalk", lambda: {"1": "00-0000001"})
    G._INJ_LOGS.clear()
    log = st.load_injury_log(2026)
    q = lambda s: [["1", s, "d", "Knee", "Knee", None, "WR"]]      # noqa: E731
    st.append_injury_log(log, "GB", "2026-10-22T16:00:00Z", q("Active"))         # the log's first snapshot: baseline
    st.append_injury_log(log, "GB", "2026-10-23T16:00:00Z", q("Questionable"))
    st.append_injury_log(log, "GB", "2026-10-25T18:00:00Z", q("Out"))             # after kickoff: ignored
    st.save_injury_log(2026, log)
    ch = G.injury_changes(2026, {"home": "DET", "away": "GB", "kickoff": "2026-10-25T17:00:00Z"})
    assert ch["away"] == [{"at": "2026-10-23T16:00:00Z", "espn": "1", "pid": "00-0000001", "from": "Active", "to": "Questionable"}]
    assert ch["home"] == [] and ch["as_of"] == "2026-10-23T16:00:00Z"
    G._INJ_LOGS.clear()
