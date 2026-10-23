"""oddsmarkets/common/calibration.py: the block QK.calib.find reads (metrics.model)."""
from __future__ import annotations

import numpy as np

from oddsmarkets.common import calibration as CB


def test_block_scores_and_buckets():
    p = np.array([0.05, 0.15, 0.55, 0.65, 0.95, 1.0])
    y = np.array([0, 0, 1, 0, 1, 1])
    b = CB.block(p, y)
    assert b["n"] == 6 and abs(b["brier"] - float(np.mean((p - y) ** 2))) < 1e-5
    assert b["base_rate"] == 0.5 and [r["lo"] for r in b["reliability"]] == [0.0, 0.1, 0.5, 0.6, 0.9]
    top = b["reliability"][-1]
    assert top["n"] == 2 and top["freq"] == 1.0 and top["mean_p"] == 0.975     # 1.0 lands in the last bucket
    assert set(b) >= {"n", "brier", "logloss", "base_rate", "mean_p", "reliability"}


def test_from_table_reads_a_p_mean_y_mean_table():
    rows = [{"lo": 0.0, "hi": 0.5, "n": 30, "p_mean": 0.3, "y_mean": 0.2}, {"lo": 0.5, "hi": 1.0, "n": 10, "p_mean": 0.8, "y_mean": 0.9},
            {"lo": 0.9, "hi": 1.0, "n": 0, "p_mean": None, "y_mean": None}]
    b = CB.from_table(rows, n=40, brier=0.2, logloss=0.6)
    assert b["n"] == 40 and b["brier"] == 0.2 and len(b["reliability"]) == 2
    assert b["reliability"][1] == {"lo": 0.5, "hi": 1.0, "n": 10, "mean_p": 0.8, "freq": 0.9}
    assert b["base_rate"] == round((0.2 * 30 + 0.9 * 10) / 40, 4)
    assert CB.from_table([]) is None
