"""CFB game centre: highest-leverage plays (build.play_wpa / build.top_plays) on small synthetic frames. No network."""
import numpy as np
import pandas as pd

from oddsmarkets.college.football.build import play_wpa, top_plays

KEYS = {"t", "period", "clock", "team", "text", "wpa"}


def _frame(rows):
    x = pd.DataFrame(rows, columns=["period", "clock_s", "offense", "pts", "wp_home", "text"])
    x["t"] = [(p - 1) * 900 + (900 - c) for p, c in zip(x["period"], x["clock_s"])]
    return x


def _close_game():
    # home "H" leads 13-7 late; away "A" scores the go-ahead TD, H drives into range and the FG is blocked.
    # ESPN's wp_home is the home WP after each row; NaN on a timeout, a spiky penalty row, admin rows.
    return _frame([
        (1, 900, "H", 0, 0.62, "kickoff 65 yards, touchback"),
        (1, 860, "H", 0, 0.64, "rush for 4 yards"),
        (3, 556, "A", 0, 0.66, "pass incomplete"),
        (3, 556, "A", 0, 0.45, "PENALTY defensive pass interference, NO PLAY"),   # isolated ESPN spike
        (3, 556, "A", 0, 0.65, "pass incomplete deep"),
        (3, 545, "A", 0, np.nan, "Timeout H, clock 09:05"),                        # no WP on this row
        (3, 520, "A", 0, 0.64, "rush for 3 yards"),
        (3, 0, "A", 0, 0.64, "End of 3rd quarter."),
        (4, 60, "A", 0, 0.70, "pass incomplete"),
        (4, 42, "A", 7, 0.15, "pass complete for 12 yds, TOUCHDOWN"),             # go-ahead score: -0.55
        (4, 41, "H", 0, np.nan, "Timeout H, clock 00:41"),
        (4, 37, "H", 0, 0.08, "kickoff 65 yards, touchback"),
        (4, 30, "H", 0, 0.60, "pass complete deep middle for 42 yds"),            # +0.52
        (4, 3, "H", 0, 0.01, "45 yd field goal attempt NO GOOD blocked"),         # -0.59, not a scrimmage play
        (4, 0, "H", 0, 0.0, "End of 4th quarter."),
    ])


def test_top_plays_are_the_biggest_swings_largest_first():
    x = _close_game()
    wpa = play_wpa(x["wp_home"].to_numpy(float), x["pts"].to_numpy(float), np.full(len(x), 0.6), final=0.0)
    top = top_plays(x, wpa, 3)
    assert [r["wpa"] for r in top] == [-0.59, -0.55, 0.52]          # blocked FG, go-ahead TD, the deep completion
    assert "blocked" in top[0]["text"] and "TOUCHDOWN" in top[1]["text"]
    assert top[1]["team"] == "A" and top[1]["period"] == 4 and top[1]["clock"] == "0:42" and top[1]["t"] == 3558
    assert all(set(r) == KEYS for r in top)


def test_wpa_values_and_artefacts():
    x = _close_game()
    wpa = play_wpa(x["wp_home"].to_numpy(float), x["pts"].to_numpy(float), np.full(len(x), 0.6), final=0.0)
    assert wpa[0] == 0.0                                    # first row: ESPN's own value is the baseline
    assert abs(wpa[9] + 0.55) < 1e-9                        # the go-ahead TD
    assert abs(wpa[12] - 0.52) < 1e-9 and abs(wpa[13] + 0.59) < 1e-9
    assert abs(wpa[3]) < 1e-9 and abs(wpa[4] + 0.01) < 1e-9  # spike removed: no +/-0.2 on the penalty or next row
    assert abs(wpa[6] + 0.01) < 1e-9                        # after a NaN timeout: carried forward, not 0.5
    assert abs(wpa.sum() - (0.0 - 0.62)) < 1e-9             # telescopes from the first value to the end
    top = top_plays(x, wpa, 20)
    assert len(top) == len(x) - 4                           # admin rows (2 timeouts, 2 end of quarter) never listed
    assert not any(r["text"].lower().startswith(("timeout", "end of")) for r in top)
    aw = [abs(r["wpa"]) for r in top]
    assert aw == sorted(aw, reverse=True)
    assert len(top_plays(x, wpa, 10)) == 10


def test_model_path_uses_pre_play_states_and_the_result():
    x = _close_game()
    pre = np.linspace(0.6, 0.3, len(x))
    pre[10] = 0.9                                           # a big pre-play jump means row 9 moved it
    wpa = play_wpa(np.full(len(x), np.nan), x["pts"].to_numpy(float), pre, final=1.0)
    assert abs(wpa[9] - (0.9 - pre[9])) < 1e-9 and abs(wpa[10] - (pre[11] - 0.9)) < 1e-9
    assert abs(wpa[-1] - (1.0 - pre[-1])) < 1e-9
    assert abs(wpa.sum() - (1.0 - pre[0])) < 1e-9


def test_scoring_first_row_uses_the_pregame_baseline():
    x = _frame([(1, 900, "A", 7, 0.30, "kickoff return 100 yds TOUCHDOWN"), (1, 880, "H", 0, 0.31, "rush for 2")])
    wpa = play_wpa(x["wp_home"].to_numpy(float), x["pts"].to_numpy(float), np.array([0.6, 0.3]))
    assert abs(wpa[0] + 0.30) < 1e-9


def test_empty():
    assert len(play_wpa(np.zeros(0), np.zeros(0), np.zeros(0))) == 0
    assert top_plays(_frame([]), np.zeros(0)) == []
