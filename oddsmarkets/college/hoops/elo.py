"""
Game Elo for college basketball (a comparison baseline for the efficiency model; FiveThirtyEight's recipe).

    E_home = 1 / (1 + 10 ** (-(R_h - R_a + HCA [not neutral]) / 400))
    R_h <- R_h + K M (S - E),  M = (|MOV| + 3) ** 0.8 / (7.5 + 0.006 D)   (D = Elo gap from the winner's side)
    between seasons R <- CARRY R + (1 - CARRY) 1500; a new D-I member starts at NEW; non-D-I opponents are one pooled
    team rated like any other.
"""
from __future__ import annotations

import numpy as np

from oddsmarkets.college.hoops import data as D

K = 32.0
HCA = 85.0
CARRY = 0.7
NEW = 1350.0
ND1_START = 1000.0
PTS_PER_ELO = 1.0 / 25.0


def run(tabs: dict[int, dict]) -> dict:
    """{season: {"p_home": array over the season table's finished games (pregame), "end": {tid: elo}}}."""
    R: dict[str, float] = {}
    out = {}
    first = True
    for s in sorted(tabs):
        tab = tabs[s]
        for t in list(R):
            R[t] = CARRY * R[t] + (1 - CARRY) * 1500.0 if t != D.ND1 else R[t]
        teams = tab["teams"]
        for t in teams:
            if t not in R:
                R[t] = ND1_START if t == D.ND1 else (1500.0 if first else NEW)
        first = False
        G = tab["g"]
        n = len(G["day"])
        ph = np.zeros(n)
        for k in range(n):
            th, ta = teams[G["h"][k]], teams[G["a"][k]]
            rh, ra = R[th], R[ta]
            dlt = rh - ra + (0.0 if G["neutral"][k] else HCA)
            e = 1.0 / (1.0 + 10.0 ** (-dlt / 400.0))
            ph[k] = e
            mov = G["hs"][k] - G["as"][k]
            sh = 1.0 if mov > 0 else 0.0
            dw = dlt if mov > 0 else -dlt
            mm = (abs(mov) + 3.0) ** 0.8 / max(2.0, 7.5 + 0.006 * dw)
            ch = K * mm * (sh - e)
            R[th] = rh + ch
            R[ta] = ra - ch
        out[s] = {"p_home": ph, "end": {t: round(R[t], 1) for t in teams}}
    return out
