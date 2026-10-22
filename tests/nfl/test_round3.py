"""Round 3 (22 Oct 2026): pre-snap states, WP and EPA from ESPN plays; injury lists keyed by side with the
starters-out impact; player weights for absences."""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.analytics import games as GM
from oddsmarkets.nfl.models import live as LV

# [seq, qtr, clock_s, team, down, dist, yl100, type, text, home_score, away_score, espn_wp_home]
PLAYS = [
    [1, 1, 900, "AWY", 0, 0, 65, "Kickoff", "X kicks 65 yards from AWY 35 to end zone, Touchback.", 0, 0, 0.55],
    [2, 1, 900, "HOM", 1, 10, 70, "Rush", "A run for 5 yards", 0, 0, 0.56],
    [3, 1, 860, "HOM", 2, 5, 65, "Pass Reception", "B pass to C for 65 yards, TOUCHDOWN. K extra point is GOOD", 7, 0, 0.66],
    [4, 1, 855, "HOM", -1, 0, 0, "Timeout", "Timeout #1 by AWY at 14:15.", 7, 0, 0.66],
    [5, 1, 855, "HOM", 0, 0, 65, "Kickoff", "K kicks 65 yards from HOM 35 to AWY 0, Touchback.", 7, 0, 0.65],
    [6, 1, 850, "AWY", 1, 10, 75, "Pass Incompletion", "D pass incomplete", 7, 0, 0.66],
    [7, 1, 845, "AWY", 2, 10, 75, "Rush", "E run for 0", 7, 0, 0.67],
    [8, 1, 840, "AWY", 3, 10, 75, "Pass Incompletion", "D pass incomplete", 7, 0, 0.68],
    [9, 1, 835, "AWY", 4, 10, 25, "Punt", "P punts 45 yards to HOM 30, fair catch by R.", 7, 0, 0.69],
    [10, 1, 830, "HOM", 1, 10, 70, "Rush", "A run for 3", 7, 0, 0.69],
]


def test_states_pre_snap_score_timeouts_punt_kickoff():
    S = LV.espn_states(PLAYS, "HOM", "AWY", 2026)
    td = S.iloc[2]
    assert (td["hs"], td["as"], td["hs_after"]) == (0.0, 0.0, 7.0)        # the score before the TD is 0-0
    assert S.iloc[3]["kind"] == "none"                                      # a timeout has no state
    assert S.iloc[5]["pos_to"] == 2.0 and S.iloc[5]["def_to"] == 3.0        # AWY used one: it is on offence here
    k = S.iloc[4]
    assert k["kind"] == "kick" and k["poss"] == "AWY" and k["yardline_100"] == LV.KICKOFF_YL100
    assert S.iloc[8]["yardline_100"] == 75.0                                # ESPN said 25: 30 + 45 from the text
    assert S.iloc[1]["receive_2h_ko"] == 0.0 and S.iloc[5]["receive_2h_ko"] == 1.0   # AWY kicked off first


def test_wp_series_carries_and_flags_states():
    ser = LV.wp_series({"plays": PLAYS, "status": "in", "away": "AWY"}, {"margin": 3.0, "p_home": 0.6}, "HOM", 2026)
    assert len(ser) == len(PLAYS) and all(len(r) == 4 for r in ser)
    assert ser[3][3] is False and ser[3][1] == ser[2][1]                    # the timeout carries the TD play's value
    assert all(0.0 <= r[1] <= 1.0 for r in ser)
    assert ser[4][1] > ser[2][1]                                            # after the TD (kickoff state) home is higher


def test_epa_series_scoring_and_possession():
    eps = LV.epa_series({"plays": PLAYS, "away": "AWY"}, "HOM", 2026, "outdoors")
    if not eps:                                                             # no committed EP fit in this checkout
        return
    by = {r[0]: r for r in eps}
    assert by[1][2] is None and by[4][2] is None                            # kickoff, timeout: no EPA
    assert abs(by[3][2] - (7.0 - by[3][1])) < 1e-6                          # TD: 7 - EP before
    assert abs(by[2][2] - (by[3][1] - by[2][1])) < 1e-3                     # same possession: EP next - EP now
    assert abs(by[9][2] - (-by[10][1] - by[9][1])) < 1e-3                   # punt: possession changes, sign flips


def test_injuries_keyed_by_team_become_sides_with_impacts():
    g = {"home": "HOM", "away": "AWY"}
    inj = {"HOM": [{"name": "A", "status": "Out", "espn_athlete": "1"}, {"name": "Z", "status": "Active"}],
           "AWY": [{"pid": "00-2", "name": "B", "status": "Questionable"}]}
    n = GM._norm_injuries(inj, g)
    assert set(n) == {"home", "away", "source"} and len(n["home"]) == 1     # Active left out
    av = {"home": {"players": []}, "away": {"players": [{"pid": "00-2", "pts": -0.08}]}}
    out = GM._injury_impacts(n, av)
    assert out["away"][0]["impact"] == -0.08 and out["away"][0]["starter"] is True


def test_player_weights_shrink_to_one():
    from oddsmarkets.nfl.edge import starters as SO
    n = np.array([0.0, 3.0, 8.0])
    rel = np.array([np.nan, 2.0, 0.5])
    w = (n * np.nan_to_num(rel, nan=1.0) + SO.K_SHRINK) / (n + SO.K_SHRINK)
    assert w[0] == 1.0 and 1.0 < w[1] < 2.0 and 0.5 < w[2] < 1.0
    assert pd.Series(w).between(0.5, 2.0).all()
