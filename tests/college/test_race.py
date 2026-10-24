"""The Campus race fields: what rides on the next game (football sim stakes), the season-long race log and its CI
restore."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from oddsmarkets.college import site
from oddsmarkets.college.football.sim import game_stakes

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_site as ci  # noqa: E402


def test_game_stakes_conditional_chances():
    rng = np.random.default_rng(1)
    n = 4000
    allt = ["A", "B", "C", "D"]
    hwin = rng.random(n) < 0.6                        # A (home) beats B in 60% of sims
    cfp = np.zeros((n, 4), bool)
    cfp[:, 0] = hwin                                  # A is in exactly when it wins
    cfp[:, 1] = ~hwin & (rng.random(n) < 0.5)         # B half the time it wins
    cfp[:, 2] = ~hwin                                 # C (a third party) gains when A loses
    other = np.zeros((n, 4), bool)
    rows = game_stakes({"g1": (0, 1, hwin, 0.6, "2026-10-31T16:00:00Z")}, {"cfp": cfp, "conf": other, "title": other},
                       allt, {"A", "B", "C", "D"})
    assert len(rows) == 1
    r = rows[0]
    assert r["home"] == "A" and r["away"] == "B" and r["p_home"] == 0.6
    assert r["cfp"]["home"] == [1.0, 0.0]             # A: in if it wins, out if it loses
    assert r["cfp"]["away"][1] == 0.0                 # B: out when it loses
    assert 0.4 < r["cfp"]["away"][0] < 0.6            # B: about half when it wins
    assert r["others"] and r["others"][0]["team"] == "C" and r["others"][0]["d"] == -1.0
    # expected places moved: p q (A 1.0 + B ~0.5 + C 1.0) with p = 0.6
    assert 0.55 < r["swing"] < 0.65


def test_game_stakes_skips_one_sided_and_non_members():
    n = 100
    always = np.ones(n, bool)
    arr = np.zeros((n, 3), bool)
    nw = {"g1": (0, 1, always, 0.99, "d"), "g2": (2, 1, np.arange(n) % 2 == 0, 0.5, "d"),
          "g3": (0, 1, np.arange(n) < 20, 0.2, "d")}
    rows = game_stakes(nw, {"cfp": arr}, ["A", "B", "X"], {"A"})
    assert rows == []          # g1 has no losing sims; g2 has no FBS member; g3's upset is in under 30 sims


def test_game_stakes_ignores_noise():
    rng = np.random.default_rng(3)
    n = 3000
    hwin = rng.random(n) < 0.5
    cfp = rng.random((n, 60)) < 0.3                  # nobody's chance depends on the game
    r = game_stakes({"g": (0, 1, hwin, 0.5, "d")}, {"cfp": cfp}, [str(i) for i in range(60)], {"0", "1"})[0]
    assert r["swing"] < 0.03 and len(r["others"]) <= 1


def test_race_log_season_long(tmp_path: Path):
    lv = tmp_path / "cfb"
    lv.mkdir()
    (lv / "chance_log.json").write_text(json.dumps({"2026": {"p_cfp": {"2026-10-24": {"1": 0.5, "2": 0.004}}}}))
    sim = {"1": {"p_cfp": 0.61, "p_title": 0.2, "p_conf": 0.4}, "2": {"p_cfp": 0.005, "p_title": 0.0, "p_conf": 0.0}}
    log = site.write_race_log(tmp_path, "cfb", 2026, sim, datetime(2026, 10, 25, 12, tzinfo=timezone.utc))
    assert sorted(log["p_cfp"]) == ["2026-10-24", "2026-10-25"]   # seeded from the chance log, then today
    assert log["p_cfp"]["2026-10-24"] == {"1": 0.5}                  # under the 1% floor dropped
    assert log["p_cfp"]["2026-10-25"] == {"1": 0.61}
    assert log["p_conf"]["2026-10-25"] == {"1": 0.4}
    on_disk = json.loads((lv / "race_log.json").read_text())
    assert set(on_disk) == {"2026"}
    # many days later the whole season is still there (no ten-day cap)
    for d in range(26, 31):
        site.write_race_log(tmp_path, "cfb", 2026, sim, datetime(2026, 10, d, 12, tzinfo=timezone.utc))
    for d in range(1, 30):
        log = site.write_race_log(tmp_path, "cfb", 2026, sim, datetime(2026, 11, d, 12, tzinfo=timezone.utc))
    assert len(log["p_cfp"]) == 2 + 5 + 29
    assert site.write_race_log(tmp_path, "cfb", 2026, {}, datetime(2026, 12, 1, tzinfo=timezone.utc)) is None


def test_ci_keeps_the_race_log_whole():
    assert ci.is_log("campus", "data/cfb/race_log.json")
    assert ci.RACE_LOG_KEEP == site.RACE_LOG_KEEP
    live = {"2026": {"p_cfp": {f"2026-10-{d:02d}": {"1": 0.5} for d in range(1, 31)}}}
    new = {"2026": {"p_cfp": {"2026-10-31": {"1": 0.6}}}}
    merged, lost = ci.merge_log("race_log.json", live, new, datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert lost == 30 and len(merged["2026"]["p_cfp"]) == 31
    merged, lost = ci.merge_log("chance_log.json", live, new, datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert len(merged["2026"]["p_cfp"]) == ci.CHANCE_LOG_KEEP
