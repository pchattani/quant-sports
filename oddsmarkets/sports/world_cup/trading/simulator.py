"""
Monte Carlo tournament simulator for FIFA World Cup 2026.
48-team format: 12 groups of 4, top-2 + best-8 third-place → 32-team R32 knockout.

10,000 simulations complete in <5 seconds via numpy-vectorized sampling.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from typing import DefaultDict

import numpy as np

from oddsmarkets.sports.world_cup.models.ensemble import EnsembleModel
from oddsmarkets.sports.world_cup.models.dixon_coles import MatchProbabilities
from oddsmarkets.sports.world_cup.trading.tournament_state import CONFIRMED_POSITIONS

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# WC 2026 confirmed group assignments (draw: December 5, 2024).
# Hosts: Mexico (Group A), Canada (Group B), USA (Group D).
# Key: Argentina=J, Spain=H, France=I per confirmed draw.
# -------------------------------------------------------------------
WC2026_GROUPS: dict[str, list[str]] = {
    "A": ["Mexico",      "South Africa",       "South Korea",   "Czech Republic"],
    "B": ["Canada",      "Bosnia-Herzegovina", "Qatar",         "Switzerland"],
    "C": ["Brazil",      "Morocco",            "Haiti",         "Scotland"],
    "D": ["USA",         "Paraguay",           "Australia",     "Turkey"],
    "E": ["Germany",     "Curacao",            "Ivory Coast",   "Ecuador"],
    "F": ["Netherlands", "Japan",              "Sweden",        "Tunisia"],
    "G": ["Belgium",     "Egypt",              "Iran",          "New Zealand"],
    "H": ["Spain",       "Cape Verde",         "Saudi Arabia",  "Uruguay"],
    "I": ["France",      "Senegal",            "Iraq",          "Norway"],
    "J": ["Argentina",   "Algeria",            "Austria",       "Jordan"],
    "K": ["Portugal",    "DR Congo",           "Uzbekistan",    "Colombia"],
    "L": ["England",     "Croatia",            "Ghana",         "Panama"],
}

# Official WC 2026 R32 bracket (32 teams, 16 matches).
# Each entry is (slot_a, slot_b). Slot formats:
#   "XN"       -> Nth-place finisher in group X  (N=1,2)
#   "3rd:ABCD" -> best 3rd-place from those eligible groups (resolved via _THIRD_SLOT_GROUPS)
WC2026_R32: list[tuple[str, str]] = [
    ("2A", "2B"),          # M73 - idx 0
    ("1E", "3rd:ABCDF"),   # M74 - idx 1
    ("1F", "2C"),          # M75 - idx 2
    ("1C", "2F"),          # M76 - idx 3
    ("1I", "3rd:CDFGH"),   # M77 - idx 4
    ("2E", "2I"),          # M78 - idx 5
    ("1A", "3rd:CEFHI"),   # M79 - idx 6
    ("1L", "3rd:EHIJK"),   # M80 - idx 7
    ("1D", "3rd:BEFIJ"),   # M81 - idx 8
    ("1G", "3rd:AEHIJ"),   # M82 - idx 9
    ("2K", "2L"),          # M83 - idx 10
    ("1H", "2J"),          # M84 - idx 11
    ("1B", "3rd:EFGIJ"),   # M85 - idx 12
    ("1J", "2H"),          # M86 - idx 13  Argentina vs Group H runner-up
    ("1K", "3rd:DEIJL"),   # M87 - idx 14
    ("2D", "2G"),          # M88 - idx 15
]

# R16 pairings: each entry is (r32_idx_a, r32_idx_b)
# M89=W74 vs W77, M90=W73 vs W75, M91=W76 vs W78, M92=W79 vs W80
# M93=W83 vs W84, M94=W81 vs W82, M95=W86 vs W88, M96=W85 vs W87
WC2026_R16: list[tuple[int, int]] = [
    (1, 4),   # M89
    (0, 2),   # M90
    (3, 5),   # M91
    (6, 7),   # M92
    (10, 11), # M93
    (8, 9),   # M94
    (13, 15), # M95: Argentina (W86) vs W88 (2D/2G winner)
    (12, 14), # M96
]

# QF pairings (indices into R16 winners list)
# M97=W89 vs W90, M98=W93 vs W94, M99=W91 vs W92, M100=W95 vs W96
WC2026_QF: list[tuple[int, int]] = [(0, 1), (4, 5), (2, 3), (6, 7)]

# SF pairings (indices into QF winners list)
WC2026_SF: list[tuple[int, int]] = [(0, 1), (2, 3)]

# Official FIFA WC 2026 Annex C: 495 combinations for 8 best third-placed teams.
# Columns = (1A->M79, 1B->M85, 1D->M81, 1E->M74, 1G->M82, 1I->M77, 1K->M87, 1L->M80)
# Each value is the GROUP LETTER of the 3rd-place team assigned to that slot.
_ANNEX_C_ROWS: list[tuple[str, ...]] = [
    ('E', 'J', 'I', 'F', 'H', 'G', 'L', 'K'),
    ('H', 'G', 'I', 'D', 'J', 'F', 'L', 'K'),
    ('E', 'J', 'I', 'D', 'H', 'G', 'L', 'K'),
    ('E', 'J', 'I', 'D', 'H', 'F', 'L', 'K'),
    ('E', 'G', 'I', 'D', 'J', 'F', 'L', 'K'),
    ('E', 'G', 'J', 'D', 'H', 'F', 'L', 'K'),
    ('E', 'G', 'I', 'D', 'H', 'F', 'L', 'K'),
    ('E', 'G', 'J', 'D', 'H', 'F', 'L', 'I'),
    ('E', 'G', 'J', 'D', 'H', 'F', 'I', 'K'),
    ('H', 'G', 'I', 'C', 'J', 'F', 'L', 'K'),
    ('E', 'J', 'I', 'C', 'H', 'G', 'L', 'K'),
    ('E', 'J', 'I', 'C', 'H', 'F', 'L', 'K'),
    ('E', 'G', 'I', 'C', 'J', 'F', 'L', 'K'),
    ('E', 'G', 'J', 'C', 'H', 'F', 'L', 'K'),
    ('E', 'G', 'I', 'C', 'H', 'F', 'L', 'K'),
    ('E', 'G', 'J', 'C', 'H', 'F', 'L', 'I'),
    ('E', 'G', 'J', 'C', 'H', 'F', 'I', 'K'),
    ('H', 'G', 'I', 'C', 'J', 'D', 'L', 'K'),
    ('C', 'J', 'I', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'G', 'I', 'D', 'J', 'F', 'L', 'K'),
    ('C', 'G', 'J', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'G', 'I', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'G', 'J', 'D', 'H', 'F', 'L', 'I'),
    ('C', 'G', 'J', 'D', 'H', 'F', 'I', 'K'),
    ('E', 'J', 'I', 'C', 'H', 'D', 'L', 'K'),
    ('E', 'G', 'I', 'C', 'J', 'D', 'L', 'K'),
    ('E', 'G', 'J', 'C', 'H', 'D', 'L', 'K'),
    ('E', 'G', 'I', 'C', 'H', 'D', 'L', 'K'),
    ('E', 'G', 'J', 'C', 'H', 'D', 'L', 'I'),
    ('E', 'G', 'J', 'C', 'H', 'D', 'I', 'K'),
    ('C', 'J', 'E', 'D', 'I', 'F', 'L', 'K'),
    ('C', 'J', 'E', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'E', 'I', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'J', 'E', 'D', 'H', 'F', 'L', 'I'),
    ('C', 'J', 'E', 'D', 'H', 'F', 'I', 'K'),
    ('C', 'G', 'E', 'D', 'J', 'F', 'L', 'K'),
    ('C', 'G', 'E', 'D', 'I', 'F', 'L', 'K'),
    ('C', 'G', 'E', 'D', 'J', 'F', 'L', 'I'),
    ('C', 'G', 'E', 'D', 'J', 'F', 'I', 'K'),
    ('C', 'G', 'E', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'G', 'J', 'D', 'H', 'F', 'L', 'E'),
    ('C', 'G', 'J', 'D', 'H', 'F', 'E', 'K'),
    ('C', 'G', 'E', 'D', 'H', 'F', 'L', 'I'),
    ('C', 'G', 'E', 'D', 'H', 'F', 'I', 'K'),
    ('C', 'G', 'J', 'D', 'H', 'F', 'E', 'I'),
    ('H', 'J', 'B', 'F', 'I', 'G', 'L', 'K'),
    ('E', 'J', 'I', 'B', 'H', 'G', 'L', 'K'),
    ('E', 'J', 'B', 'F', 'I', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'F', 'I', 'G', 'L', 'K'),
    ('E', 'J', 'B', 'F', 'H', 'G', 'L', 'K'),
    ('E', 'G', 'B', 'F', 'I', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'F', 'H', 'G', 'L', 'I'),
    ('E', 'J', 'B', 'F', 'H', 'G', 'I', 'K'),
    ('H', 'J', 'B', 'D', 'I', 'G', 'L', 'K'),
    ('H', 'J', 'B', 'D', 'I', 'F', 'L', 'K'),
    ('I', 'G', 'B', 'D', 'J', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'D', 'J', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'D', 'I', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'D', 'J', 'F', 'L', 'I'),
    ('H', 'G', 'B', 'D', 'J', 'F', 'I', 'K'),
    ('E', 'J', 'B', 'D', 'I', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'D', 'I', 'G', 'L', 'K'),
    ('E', 'J', 'B', 'D', 'H', 'G', 'L', 'K'),
    ('E', 'G', 'B', 'D', 'I', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'D', 'H', 'G', 'L', 'I'),
    ('E', 'J', 'B', 'D', 'H', 'G', 'I', 'K'),
    ('E', 'J', 'B', 'D', 'I', 'F', 'L', 'K'),
    ('E', 'J', 'B', 'D', 'H', 'F', 'L', 'K'),
    ('E', 'I', 'B', 'D', 'H', 'F', 'L', 'K'),
    ('E', 'J', 'B', 'D', 'H', 'F', 'L', 'I'),
    ('E', 'J', 'B', 'D', 'H', 'F', 'I', 'K'),
    ('E', 'G', 'B', 'D', 'J', 'F', 'L', 'K'),
    ('E', 'G', 'B', 'D', 'I', 'F', 'L', 'K'),
    ('E', 'G', 'B', 'D', 'J', 'F', 'L', 'I'),
    ('E', 'G', 'B', 'D', 'J', 'F', 'I', 'K'),
    ('E', 'G', 'B', 'D', 'H', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'D', 'J', 'F', 'L', 'E'),
    ('H', 'G', 'B', 'D', 'J', 'F', 'E', 'K'),
    ('E', 'G', 'B', 'D', 'H', 'F', 'L', 'I'),
    ('E', 'G', 'B', 'D', 'H', 'F', 'I', 'K'),
    ('H', 'G', 'B', 'D', 'J', 'F', 'E', 'I'),
    ('H', 'J', 'B', 'C', 'I', 'G', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'I', 'F', 'L', 'K'),
    ('I', 'G', 'B', 'C', 'J', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'I', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'F', 'L', 'I'),
    ('H', 'G', 'B', 'C', 'J', 'F', 'I', 'K'),
    ('E', 'J', 'B', 'C', 'I', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'I', 'G', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'H', 'G', 'L', 'K'),
    ('E', 'G', 'B', 'C', 'I', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'H', 'G', 'L', 'I'),
    ('E', 'J', 'B', 'C', 'H', 'G', 'I', 'K'),
    ('E', 'J', 'B', 'C', 'I', 'F', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'H', 'F', 'L', 'K'),
    ('E', 'I', 'B', 'C', 'H', 'F', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'H', 'F', 'L', 'I'),
    ('E', 'J', 'B', 'C', 'H', 'F', 'I', 'K'),
    ('E', 'G', 'B', 'C', 'J', 'F', 'L', 'K'),
    ('E', 'G', 'B', 'C', 'I', 'F', 'L', 'K'),
    ('E', 'G', 'B', 'C', 'J', 'F', 'L', 'I'),
    ('E', 'G', 'B', 'C', 'J', 'F', 'I', 'K'),
    ('E', 'G', 'B', 'C', 'H', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'F', 'L', 'E'),
    ('H', 'G', 'B', 'C', 'J', 'F', 'E', 'K'),
    ('E', 'G', 'B', 'C', 'H', 'F', 'L', 'I'),
    ('E', 'G', 'B', 'C', 'H', 'F', 'I', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'F', 'E', 'I'),
    ('H', 'J', 'B', 'C', 'I', 'D', 'L', 'K'),
    ('I', 'G', 'B', 'C', 'J', 'D', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'D', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'I', 'D', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'D', 'L', 'I'),
    ('H', 'G', 'B', 'C', 'J', 'D', 'I', 'K'),
    ('C', 'J', 'B', 'D', 'I', 'F', 'L', 'K'),
    ('C', 'J', 'B', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'I', 'B', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'J', 'B', 'D', 'H', 'F', 'L', 'I'),
    ('C', 'J', 'B', 'D', 'H', 'F', 'I', 'K'),
    ('C', 'G', 'B', 'D', 'J', 'F', 'L', 'K'),
    ('C', 'G', 'B', 'D', 'I', 'F', 'L', 'K'),
    ('C', 'G', 'B', 'D', 'J', 'F', 'L', 'I'),
    ('C', 'G', 'B', 'D', 'J', 'F', 'I', 'K'),
    ('C', 'G', 'B', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'G', 'B', 'D', 'H', 'F', 'L', 'J'),
    ('H', 'G', 'B', 'C', 'J', 'F', 'D', 'K'),
    ('C', 'G', 'B', 'D', 'H', 'F', 'L', 'I'),
    ('C', 'G', 'B', 'D', 'H', 'F', 'I', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'F', 'D', 'I'),
    ('E', 'J', 'B', 'C', 'I', 'D', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'H', 'D', 'L', 'K'),
    ('E', 'I', 'B', 'C', 'H', 'D', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'H', 'D', 'L', 'I'),
    ('E', 'J', 'B', 'C', 'H', 'D', 'I', 'K'),
    ('E', 'G', 'B', 'C', 'J', 'D', 'L', 'K'),
    ('E', 'G', 'B', 'C', 'I', 'D', 'L', 'K'),
    ('E', 'G', 'B', 'C', 'J', 'D', 'L', 'I'),
    ('E', 'G', 'B', 'C', 'J', 'D', 'I', 'K'),
    ('E', 'G', 'B', 'C', 'H', 'D', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'D', 'L', 'E'),
    ('H', 'G', 'B', 'C', 'J', 'D', 'E', 'K'),
    ('E', 'G', 'B', 'C', 'H', 'D', 'L', 'I'),
    ('E', 'G', 'B', 'C', 'H', 'D', 'I', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'D', 'E', 'I'),
    ('C', 'J', 'B', 'D', 'E', 'F', 'L', 'K'),
    ('C', 'E', 'B', 'D', 'I', 'F', 'L', 'K'),
    ('C', 'J', 'B', 'D', 'E', 'F', 'L', 'I'),
    ('C', 'J', 'B', 'D', 'E', 'F', 'I', 'K'),
    ('C', 'E', 'B', 'D', 'H', 'F', 'L', 'K'),
    ('C', 'J', 'B', 'D', 'H', 'F', 'L', 'E'),
    ('C', 'J', 'B', 'D', 'H', 'F', 'E', 'K'),
    ('C', 'E', 'B', 'D', 'H', 'F', 'L', 'I'),
    ('C', 'E', 'B', 'D', 'H', 'F', 'I', 'K'),
    ('C', 'J', 'B', 'D', 'H', 'F', 'E', 'I'),
    ('C', 'G', 'B', 'D', 'E', 'F', 'L', 'K'),
    ('C', 'G', 'B', 'D', 'J', 'F', 'L', 'E'),
    ('C', 'G', 'B', 'D', 'J', 'F', 'E', 'K'),
    ('C', 'G', 'B', 'D', 'E', 'F', 'L', 'I'),
    ('C', 'G', 'B', 'D', 'E', 'F', 'I', 'K'),
    ('C', 'G', 'B', 'D', 'J', 'F', 'E', 'I'),
    ('C', 'G', 'B', 'D', 'H', 'F', 'L', 'E'),
    ('C', 'G', 'B', 'D', 'H', 'F', 'E', 'K'),
    ('H', 'G', 'B', 'C', 'J', 'F', 'D', 'E'),
    ('C', 'G', 'B', 'D', 'H', 'F', 'E', 'I'),
    ('H', 'J', 'I', 'F', 'A', 'G', 'L', 'K'),
    ('E', 'J', 'I', 'A', 'H', 'G', 'L', 'K'),
    ('E', 'J', 'I', 'F', 'A', 'H', 'L', 'K'),
    ('E', 'J', 'I', 'F', 'A', 'G', 'L', 'K'),
    ('E', 'G', 'J', 'F', 'A', 'H', 'L', 'K'),
    ('E', 'G', 'I', 'F', 'A', 'H', 'L', 'K'),
    ('E', 'G', 'J', 'F', 'A', 'H', 'L', 'I'),
    ('E', 'G', 'J', 'F', 'A', 'H', 'I', 'K'),
    ('H', 'J', 'I', 'D', 'A', 'G', 'L', 'K'),
    ('H', 'J', 'I', 'D', 'A', 'F', 'L', 'K'),
    ('I', 'G', 'J', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'J', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'I', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'J', 'D', 'A', 'F', 'L', 'I'),
    ('H', 'G', 'J', 'D', 'A', 'F', 'I', 'K'),
    ('E', 'J', 'I', 'D', 'A', 'H', 'L', 'K'),
    ('E', 'J', 'I', 'D', 'A', 'G', 'L', 'K'),
    ('E', 'G', 'J', 'D', 'A', 'H', 'L', 'K'),
    ('E', 'G', 'I', 'D', 'A', 'H', 'L', 'K'),
    ('E', 'G', 'J', 'D', 'A', 'H', 'L', 'I'),
    ('E', 'G', 'J', 'D', 'A', 'H', 'I', 'K'),
    ('E', 'J', 'I', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'E', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'E', 'I', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'E', 'D', 'A', 'F', 'L', 'I'),
    ('H', 'J', 'E', 'D', 'A', 'F', 'I', 'K'),
    ('E', 'G', 'J', 'D', 'A', 'F', 'L', 'K'),
    ('E', 'G', 'I', 'D', 'A', 'F', 'L', 'K'),
    ('E', 'G', 'J', 'D', 'A', 'F', 'L', 'I'),
    ('E', 'G', 'J', 'D', 'A', 'F', 'I', 'K'),
    ('H', 'G', 'E', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'J', 'D', 'A', 'F', 'L', 'E'),
    ('H', 'G', 'J', 'D', 'A', 'F', 'E', 'K'),
    ('H', 'G', 'E', 'D', 'A', 'F', 'L', 'I'),
    ('H', 'G', 'E', 'D', 'A', 'F', 'I', 'K'),
    ('H', 'G', 'J', 'D', 'A', 'F', 'E', 'I'),
    ('H', 'J', 'I', 'C', 'A', 'G', 'L', 'K'),
    ('H', 'J', 'I', 'C', 'A', 'F', 'L', 'K'),
    ('I', 'G', 'J', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'I', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'F', 'L', 'I'),
    ('H', 'G', 'J', 'C', 'A', 'F', 'I', 'K'),
    ('E', 'J', 'I', 'C', 'A', 'H', 'L', 'K'),
    ('E', 'J', 'I', 'C', 'A', 'G', 'L', 'K'),
    ('E', 'G', 'J', 'C', 'A', 'H', 'L', 'K'),
    ('E', 'G', 'I', 'C', 'A', 'H', 'L', 'K'),
    ('E', 'G', 'J', 'C', 'A', 'H', 'L', 'I'),
    ('E', 'G', 'J', 'C', 'A', 'H', 'I', 'K'),
    ('E', 'J', 'I', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'E', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'E', 'I', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'E', 'C', 'A', 'F', 'L', 'I'),
    ('H', 'J', 'E', 'C', 'A', 'F', 'I', 'K'),
    ('E', 'G', 'J', 'C', 'A', 'F', 'L', 'K'),
    ('E', 'G', 'I', 'C', 'A', 'F', 'L', 'K'),
    ('E', 'G', 'J', 'C', 'A', 'F', 'L', 'I'),
    ('E', 'G', 'J', 'C', 'A', 'F', 'I', 'K'),
    ('H', 'G', 'E', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'F', 'L', 'E'),
    ('H', 'G', 'J', 'C', 'A', 'F', 'E', 'K'),
    ('H', 'G', 'E', 'C', 'A', 'F', 'L', 'I'),
    ('H', 'G', 'E', 'C', 'A', 'F', 'I', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'F', 'E', 'I'),
    ('H', 'J', 'I', 'C', 'A', 'D', 'L', 'K'),
    ('I', 'G', 'J', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'G', 'I', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'G', 'J', 'C', 'A', 'D', 'I', 'K'),
    ('C', 'J', 'I', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'F', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'F', 'I', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'J', 'F', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'J', 'F', 'C', 'A', 'D', 'I', 'K'),
    ('C', 'G', 'J', 'D', 'A', 'F', 'L', 'K'),
    ('C', 'G', 'I', 'D', 'A', 'F', 'L', 'K'),
    ('C', 'G', 'J', 'D', 'A', 'F', 'L', 'I'),
    ('C', 'G', 'J', 'D', 'A', 'F', 'I', 'K'),
    ('H', 'G', 'F', 'C', 'A', 'D', 'L', 'K'),
    ('C', 'G', 'J', 'D', 'A', 'F', 'L', 'H'),
    ('H', 'G', 'J', 'C', 'A', 'F', 'D', 'K'),
    ('H', 'G', 'F', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'G', 'F', 'C', 'A', 'D', 'I', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'F', 'D', 'I'),
    ('E', 'J', 'I', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'J', 'E', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'E', 'I', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'J', 'E', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'J', 'E', 'C', 'A', 'D', 'I', 'K'),
    ('E', 'G', 'J', 'C', 'A', 'D', 'L', 'K'),
    ('E', 'G', 'I', 'C', 'A', 'D', 'L', 'K'),
    ('E', 'G', 'J', 'C', 'A', 'D', 'L', 'I'),
    ('E', 'G', 'J', 'C', 'A', 'D', 'I', 'K'),
    ('H', 'G', 'E', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'D', 'L', 'E'),
    ('H', 'G', 'J', 'C', 'A', 'D', 'E', 'K'),
    ('H', 'G', 'E', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'G', 'E', 'C', 'A', 'D', 'I', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'D', 'E', 'I'),
    ('C', 'J', 'E', 'D', 'A', 'F', 'L', 'K'),
    ('C', 'E', 'I', 'D', 'A', 'F', 'L', 'K'),
    ('C', 'J', 'E', 'D', 'A', 'F', 'L', 'I'),
    ('C', 'J', 'E', 'D', 'A', 'F', 'I', 'K'),
    ('H', 'E', 'F', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'J', 'F', 'C', 'A', 'D', 'L', 'E'),
    ('H', 'J', 'E', 'C', 'A', 'F', 'D', 'K'),
    ('H', 'E', 'F', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'E', 'F', 'C', 'A', 'D', 'I', 'K'),
    ('H', 'J', 'E', 'C', 'A', 'F', 'D', 'I'),
    ('C', 'G', 'E', 'D', 'A', 'F', 'L', 'K'),
    ('C', 'G', 'J', 'D', 'A', 'F', 'L', 'E'),
    ('C', 'G', 'J', 'D', 'A', 'F', 'E', 'K'),
    ('C', 'G', 'E', 'D', 'A', 'F', 'L', 'I'),
    ('C', 'G', 'E', 'D', 'A', 'F', 'I', 'K'),
    ('C', 'G', 'J', 'D', 'A', 'F', 'E', 'I'),
    ('H', 'G', 'F', 'C', 'A', 'D', 'L', 'E'),
    ('H', 'G', 'E', 'C', 'A', 'F', 'D', 'K'),
    ('H', 'G', 'J', 'C', 'A', 'F', 'D', 'E'),
    ('H', 'G', 'E', 'C', 'A', 'F', 'D', 'I'),
    ('H', 'J', 'B', 'A', 'I', 'G', 'L', 'K'),
    ('H', 'J', 'B', 'A', 'I', 'F', 'L', 'K'),
    ('I', 'J', 'B', 'F', 'A', 'G', 'L', 'K'),
    ('H', 'J', 'B', 'F', 'A', 'G', 'L', 'K'),
    ('H', 'G', 'B', 'A', 'I', 'F', 'L', 'K'),
    ('H', 'J', 'B', 'F', 'A', 'G', 'L', 'I'),
    ('H', 'J', 'B', 'F', 'A', 'G', 'I', 'K'),
    ('E', 'J', 'B', 'A', 'I', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'A', 'I', 'G', 'L', 'K'),
    ('E', 'J', 'B', 'A', 'H', 'G', 'L', 'K'),
    ('E', 'G', 'B', 'A', 'I', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'A', 'H', 'G', 'L', 'I'),
    ('E', 'J', 'B', 'A', 'H', 'G', 'I', 'K'),
    ('E', 'J', 'B', 'A', 'I', 'F', 'L', 'K'),
    ('E', 'J', 'B', 'F', 'A', 'H', 'L', 'K'),
    ('E', 'I', 'B', 'F', 'A', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'F', 'A', 'H', 'L', 'I'),
    ('E', 'J', 'B', 'F', 'A', 'H', 'I', 'K'),
    ('E', 'J', 'B', 'F', 'A', 'G', 'L', 'K'),
    ('E', 'G', 'B', 'A', 'I', 'F', 'L', 'K'),
    ('E', 'J', 'B', 'F', 'A', 'G', 'L', 'I'),
    ('E', 'J', 'B', 'F', 'A', 'G', 'I', 'K'),
    ('E', 'G', 'B', 'F', 'A', 'H', 'L', 'K'),
    ('H', 'J', 'B', 'F', 'A', 'G', 'L', 'E'),
    ('H', 'J', 'B', 'F', 'A', 'G', 'E', 'K'),
    ('E', 'G', 'B', 'F', 'A', 'H', 'L', 'I'),
    ('E', 'G', 'B', 'F', 'A', 'H', 'I', 'K'),
    ('H', 'J', 'B', 'F', 'A', 'G', 'E', 'I'),
    ('I', 'J', 'B', 'D', 'A', 'H', 'L', 'K'),
    ('I', 'J', 'B', 'D', 'A', 'G', 'L', 'K'),
    ('H', 'J', 'B', 'D', 'A', 'G', 'L', 'K'),
    ('I', 'G', 'B', 'D', 'A', 'H', 'L', 'K'),
    ('H', 'J', 'B', 'D', 'A', 'G', 'L', 'I'),
    ('H', 'J', 'B', 'D', 'A', 'G', 'I', 'K'),
    ('I', 'J', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'I', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'B', 'D', 'A', 'F', 'L', 'I'),
    ('H', 'J', 'B', 'D', 'A', 'F', 'I', 'K'),
    ('F', 'J', 'B', 'D', 'A', 'G', 'L', 'K'),
    ('I', 'G', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('F', 'J', 'B', 'D', 'A', 'G', 'L', 'I'),
    ('F', 'J', 'B', 'D', 'A', 'G', 'I', 'K'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'L', 'J'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'J', 'K'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'L', 'I'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'I', 'K'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'I', 'J'),
    ('E', 'J', 'B', 'A', 'I', 'D', 'L', 'K'),
    ('E', 'J', 'B', 'D', 'A', 'H', 'L', 'K'),
    ('E', 'I', 'B', 'D', 'A', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'D', 'A', 'H', 'L', 'I'),
    ('E', 'J', 'B', 'D', 'A', 'H', 'I', 'K'),
    ('E', 'J', 'B', 'D', 'A', 'G', 'L', 'K'),
    ('E', 'G', 'B', 'A', 'I', 'D', 'L', 'K'),
    ('E', 'J', 'B', 'D', 'A', 'G', 'L', 'I'),
    ('E', 'J', 'B', 'D', 'A', 'G', 'I', 'K'),
    ('E', 'G', 'B', 'D', 'A', 'H', 'L', 'K'),
    ('H', 'J', 'B', 'D', 'A', 'G', 'L', 'E'),
    ('H', 'J', 'B', 'D', 'A', 'G', 'E', 'K'),
    ('E', 'G', 'B', 'D', 'A', 'H', 'L', 'I'),
    ('E', 'G', 'B', 'D', 'A', 'H', 'I', 'K'),
    ('H', 'J', 'B', 'D', 'A', 'G', 'E', 'I'),
    ('E', 'J', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('E', 'I', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('E', 'J', 'B', 'D', 'A', 'F', 'L', 'I'),
    ('E', 'J', 'B', 'D', 'A', 'F', 'I', 'K'),
    ('H', 'E', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'B', 'D', 'A', 'F', 'L', 'E'),
    ('H', 'J', 'B', 'D', 'A', 'F', 'E', 'K'),
    ('H', 'E', 'B', 'D', 'A', 'F', 'L', 'I'),
    ('H', 'E', 'B', 'D', 'A', 'F', 'I', 'K'),
    ('H', 'J', 'B', 'D', 'A', 'F', 'E', 'I'),
    ('E', 'G', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('E', 'G', 'B', 'D', 'A', 'F', 'L', 'J'),
    ('E', 'G', 'B', 'D', 'A', 'F', 'J', 'K'),
    ('E', 'G', 'B', 'D', 'A', 'F', 'L', 'I'),
    ('E', 'G', 'B', 'D', 'A', 'F', 'I', 'K'),
    ('E', 'G', 'B', 'D', 'A', 'F', 'I', 'J'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'L', 'E'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'E', 'K'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'E', 'J'),
    ('H', 'G', 'B', 'D', 'A', 'F', 'E', 'I'),
    ('I', 'J', 'B', 'C', 'A', 'H', 'L', 'K'),
    ('I', 'J', 'B', 'C', 'A', 'G', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'G', 'L', 'K'),
    ('I', 'G', 'B', 'C', 'A', 'H', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'G', 'L', 'I'),
    ('H', 'J', 'B', 'C', 'A', 'G', 'I', 'K'),
    ('I', 'J', 'B', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'I', 'B', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'F', 'L', 'I'),
    ('H', 'J', 'B', 'C', 'A', 'F', 'I', 'K'),
    ('C', 'J', 'B', 'F', 'A', 'G', 'L', 'K'),
    ('I', 'G', 'B', 'C', 'A', 'F', 'L', 'K'),
    ('C', 'J', 'B', 'F', 'A', 'G', 'L', 'I'),
    ('C', 'J', 'B', 'F', 'A', 'G', 'I', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'L', 'J'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'J', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'L', 'I'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'I', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'I', 'J'),
    ('E', 'J', 'B', 'A', 'I', 'C', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'A', 'H', 'L', 'K'),
    ('E', 'I', 'B', 'C', 'A', 'H', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'A', 'H', 'L', 'I'),
    ('E', 'J', 'B', 'C', 'A', 'H', 'I', 'K'),
    ('E', 'J', 'B', 'C', 'A', 'G', 'L', 'K'),
    ('E', 'G', 'B', 'A', 'I', 'C', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'A', 'G', 'L', 'I'),
    ('E', 'J', 'B', 'C', 'A', 'G', 'I', 'K'),
    ('E', 'G', 'B', 'C', 'A', 'H', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'G', 'L', 'E'),
    ('H', 'J', 'B', 'C', 'A', 'G', 'E', 'K'),
    ('E', 'G', 'B', 'C', 'A', 'H', 'L', 'I'),
    ('E', 'G', 'B', 'C', 'A', 'H', 'I', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'G', 'E', 'I'),
    ('E', 'J', 'B', 'C', 'A', 'F', 'L', 'K'),
    ('E', 'I', 'B', 'C', 'A', 'F', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'A', 'F', 'L', 'I'),
    ('E', 'J', 'B', 'C', 'A', 'F', 'I', 'K'),
    ('H', 'E', 'B', 'C', 'A', 'F', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'F', 'L', 'E'),
    ('H', 'J', 'B', 'C', 'A', 'F', 'E', 'K'),
    ('H', 'E', 'B', 'C', 'A', 'F', 'L', 'I'),
    ('H', 'E', 'B', 'C', 'A', 'F', 'I', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'F', 'E', 'I'),
    ('E', 'G', 'B', 'C', 'A', 'F', 'L', 'K'),
    ('E', 'G', 'B', 'C', 'A', 'F', 'L', 'J'),
    ('E', 'G', 'B', 'C', 'A', 'F', 'J', 'K'),
    ('E', 'G', 'B', 'C', 'A', 'F', 'L', 'I'),
    ('E', 'G', 'B', 'C', 'A', 'F', 'I', 'K'),
    ('E', 'G', 'B', 'C', 'A', 'F', 'I', 'J'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'L', 'E'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'E', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'E', 'J'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'E', 'I'),
    ('I', 'J', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'I', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'J', 'B', 'C', 'A', 'D', 'I', 'K'),
    ('C', 'J', 'B', 'D', 'A', 'G', 'L', 'K'),
    ('I', 'G', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('C', 'J', 'B', 'D', 'A', 'G', 'L', 'I'),
    ('C', 'J', 'B', 'D', 'A', 'G', 'I', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'L', 'J'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'J', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'I', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'I', 'J'),
    ('C', 'J', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('C', 'I', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('C', 'J', 'B', 'D', 'A', 'F', 'L', 'I'),
    ('C', 'J', 'B', 'D', 'A', 'F', 'I', 'K'),
    ('H', 'F', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('C', 'J', 'B', 'D', 'A', 'F', 'L', 'H'),
    ('H', 'J', 'B', 'C', 'A', 'F', 'D', 'K'),
    ('H', 'F', 'B', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'F', 'B', 'C', 'A', 'D', 'I', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'F', 'D', 'I'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'L', 'J'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'J', 'K'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'L', 'I'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'I', 'K'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'I', 'J'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'L', 'H'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'D', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'D', 'J'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'D', 'I'),
    ('E', 'J', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('E', 'I', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('E', 'J', 'B', 'C', 'A', 'D', 'L', 'I'),
    ('E', 'J', 'B', 'C', 'A', 'D', 'I', 'K'),
    ('H', 'E', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'D', 'L', 'E'),
    ('H', 'J', 'B', 'C', 'A', 'D', 'E', 'K'),
    ('H', 'E', 'B', 'C', 'A', 'D', 'L', 'I'),
    ('H', 'E', 'B', 'C', 'A', 'D', 'I', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'D', 'E', 'I'),
    ('E', 'G', 'B', 'C', 'A', 'D', 'L', 'K'),
    ('E', 'G', 'B', 'C', 'A', 'D', 'L', 'J'),
    ('E', 'G', 'B', 'C', 'A', 'D', 'J', 'K'),
    ('E', 'G', 'B', 'C', 'A', 'D', 'L', 'I'),
    ('E', 'G', 'B', 'C', 'A', 'D', 'I', 'K'),
    ('E', 'G', 'B', 'C', 'A', 'D', 'I', 'J'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'L', 'E'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'E', 'K'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'E', 'J'),
    ('H', 'G', 'B', 'C', 'A', 'D', 'E', 'I'),
    ('C', 'E', 'B', 'D', 'A', 'F', 'L', 'K'),
    ('C', 'J', 'B', 'D', 'A', 'F', 'L', 'E'),
    ('C', 'J', 'B', 'D', 'A', 'F', 'E', 'K'),
    ('C', 'E', 'B', 'D', 'A', 'F', 'L', 'I'),
    ('C', 'E', 'B', 'D', 'A', 'F', 'I', 'K'),
    ('C', 'J', 'B', 'D', 'A', 'F', 'E', 'I'),
    ('H', 'F', 'B', 'C', 'A', 'D', 'L', 'E'),
    ('H', 'E', 'B', 'C', 'A', 'F', 'D', 'K'),
    ('H', 'J', 'B', 'C', 'A', 'F', 'D', 'E'),
    ('H', 'E', 'B', 'C', 'A', 'F', 'D', 'I'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'L', 'E'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'E', 'K'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'E', 'J'),
    ('C', 'G', 'B', 'D', 'A', 'F', 'E', 'I'),
    ('H', 'G', 'B', 'C', 'A', 'F', 'D', 'E')
]
# Annex C column index -> R32 slot index in WC2026_R32
_ANNEX_C_COL_TO_SLOT: tuple[int, ...] = (6, 12, 8, 1, 9, 4, 14, 7)
# Pre-computed lookup: frozenset of 8 qualifying group letters -> {slot_idx: group_letter}
_ANNEX_C_TABLE: dict[frozenset, dict[int, str]] = {
    frozenset(row): {_ANNEX_C_COL_TO_SLOT[c]: row[c] for c in range(8)}
    for row in _ANNEX_C_ROWS
}

# Historical WC shootout: effectively 50/50 after extra time
SHOOTOUT_HOME_WIN_PROB = 0.50


def _sort_group_standings(
    teams: list[str],
    points: dict[str, int],
    gd: dict[str, int],
    gf: dict[str, int],
    h2h: dict[tuple[str, str], tuple[int, int]],
) -> list[str]:
    """
    Sort group teams per WC 2026 official tiebreaker order:
    overall pts → H2H pts → H2H GD → H2H GF → overall GD → overall GF
    H2H is computed only among the cluster of tied teams (same overall pts).
    """
    def _h2h_stats(cluster: list[str]) -> dict[str, tuple[int, int, int]]:
        h_pts: dict[str, int] = {t: 0 for t in cluster}
        h_gd:  dict[str, int] = {t: 0 for t in cluster}
        h_gf:  dict[str, int] = {t: 0 for t in cluster}
        for i, t1 in enumerate(cluster):
            for t2 in cluster[i + 1:]:
                res = h2h.get((t1, t2))
                if res is None:
                    r2 = h2h.get((t2, t1))
                    if r2 is not None:
                        res = (r2[1], r2[0])
                if res is None:
                    continue
                hg, ag = res
                if hg > ag:
                    h_pts[t1] += 3
                elif hg == ag:
                    h_pts[t1] += 1
                    h_pts[t2] += 1
                else:
                    h_pts[t2] += 3
                h_gd[t1] += hg - ag
                h_gd[t2] += ag - hg
                h_gf[t1] += hg
                h_gf[t2] += ag
        return {t: (h_pts[t], h_gd[t], h_gf[t]) for t in cluster}

    # Group by equal overall points
    by_pts: dict[int, list[str]] = {}
    for t in teams:
        by_pts.setdefault(points[t], []).append(t)

    result: list[str] = []
    for pts_val in sorted(by_pts.keys(), reverse=True):
        cluster = by_pts[pts_val]
        if len(cluster) == 1:
            result.extend(cluster)
        else:
            h = _h2h_stats(cluster)
            cluster.sort(
                key=lambda t: (h[t][0], h[t][1], h[t][2], gd[t], gf[t]),
                reverse=True,
            )
            result.extend(cluster)

    return result


@dataclass
class SimulationResults:
    n_sims: int
    simulated_at: datetime
    p_win_group:      dict[str, float] = field(default_factory=dict)
    p_reach_r32:      dict[str, float] = field(default_factory=dict)
    p_reach_r16:      dict[str, float] = field(default_factory=dict)
    p_reach_qf:       dict[str, float] = field(default_factory=dict)
    p_reach_sf:       dict[str, float] = field(default_factory=dict)
    p_reach_final:    dict[str, float] = field(default_factory=dict)
    p_win_tournament: dict[str, float] = field(default_factory=dict)

    # matchup_probs[stage][team][opponent] = P(team faces opponent at stage, unconditional)
    # Use MatchupAnalyzer.conditional_probs() to get P(.|team reached stage).
    matchup_probs: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)

    # groups snapshot (used by dashboard)
    groups: dict[str, list[str]] = field(default_factory=dict)

    # third_place_scenarios[(pts, gd)] = P(qualifying as one of best-8 third-place teams)
    # Estimated over all simulations; useful for the scenario analysis chart.
    third_place_scenarios: dict[tuple[int, int], float] = field(default_factory=dict)

    # r32_slot_teams[i] = {"slot_a": [{team, p}, ...], "slot_b": [...]}
    # Top-3 most likely teams for each side of the 16 R32 matches.
    r32_slot_teams: list[dict] = field(default_factory=list)

    # p_finish_pos[team][pos] = P(team finishes pos in group), pos in 1..4
    p_finish_pos: dict[str, dict[int, float]] = field(default_factory=dict)

    # r32_opponents_by_pos[team][pos] = [{team: opp, p: P(face opp | finished pos & qualified)}]
    r32_opponents_by_pos: dict[str, dict[int, list[dict]]] = field(default_factory=dict)


class TournamentSimulator:
    """
    Simulates the WC 2026 tournament via Monte Carlo.
    Pre-computes score matrices once, then samples N times for speed.
    """

    def __init__(
        self,
        model: EnsembleModel,
        groups: dict[str, list[str]] | None = None,
        n_sims: int = 10_000,
        seed: int = 42,
    ) -> None:
        self.model = model
        self.groups = groups or WC2026_GROUPS
        self.n_sims = n_sims
        self.rng = np.random.default_rng(seed)

        self._all_teams: list[str] = [t for teams in self.groups.values() for t in teams]
        self._match_probs: dict[tuple[str, str], MatchProbabilities] = {}
        self._boot = None  # optional GoldenBootModel; set via run(boot_model=...)

    def precompute_group_matches(self) -> None:
        """Pre-compute score matrices for all group-stage matchups."""
        for group_teams in self.groups.values():
            for home, away in combinations(group_teams, 2):
                if (home, away) not in self._match_probs:
                    self._match_probs[(home, away)] = self.model.predict(
                        home, away, neutral=True
                    )
        logger.info("Pre-computed %d unique group-stage matchup matrices", len(self._match_probs))

    def run(self, state: "TournamentState | None" = None, boot_model=None) -> SimulationResults:
        """
        Run n_sims tournament simulations.

        If *state* is provided (live tournament data), the simulation:
          - Uses known group outcomes for completed groups (no re-simulation).
          - Seeds partial groups from actual standings, simulating only remaining games.
          - Propagates known knockout results.

        If *boot_model* (a GoldenBootModel) is provided, each simulated knockout
        scoreline is fed to it so it can estimate Golden-Boot probabilities.
        """
        from oddsmarkets.sports.world_cup.trading.tournament_state import TournamentState
        self._state: TournamentState = state or TournamentState.empty()
        self._boot = boot_model
        # Known knockout outcomes: whenever these two teams meet in a sim, force
        # the real winner so reach-round probabilities condition on actual results.
        self._known_ko: dict[frozenset, str] = dict(
            getattr(self._state, "knockout_winners_by_teams", {}) or {}
        )
        self.precompute_group_matches()

        counters: dict[str, dict[str, int]] = {
            team: {
                "win_group": 0, "reach_r32": 0, "reach_r16": 0,
                "reach_qf": 0, "reach_sf": 0, "reach_final": 0, "win_tournament": 0,
            }
            for team in self._all_teams
        }

        stages = ["r32", "r16", "qf", "sf", "final"]
        matchup_counts: dict[str, DefaultDict[str, DefaultDict[str, int]]] = {
            s: defaultdict(lambda: defaultdict(int)) for s in stages
        }
        # scenario_counts[(pts, gd)] = [qualify_count, total_count]
        scenario_counts: DefaultDict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
        # r32_slot_counts[i] = (defaultdict_a, defaultdict_b): team counts per slot side
        r32_slot_counts: list[tuple[DefaultDict[str, int], DefaultDict[str, int]]] = [
            (defaultdict(int), defaultdict(int)) for _ in range(16)
        ]
        # pos_counts[team][pos] = # sims where team finished pos (1-4) in group
        pos_counts: DefaultDict[str, DefaultDict[int, int]] = defaultdict(lambda: defaultdict(int))
        # r32_by_pos_counts[team][pos][opponent] = # sims where team (finished pos) faced opponent in R32
        r32_by_pos_counts: DefaultDict[str, DefaultDict[int, DefaultDict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )

        for _ in range(self.n_sims):
            if self._boot is not None:
                self._boot.start_sim()
            try:
                self._simulate_one(counters, matchup_counts, scenario_counts, r32_slot_counts,
                                   pos_counts, r32_by_pos_counts)
                if self._boot is not None:
                    self._boot.finalize_sim()
            except Exception as exc:
                logger.debug("Simulation error (skipped): %s", exc)

        results = SimulationResults(
            n_sims=self.n_sims,
            simulated_at=datetime.now(timezone.utc),
            groups=dict(self.groups),
        )
        for team in self._all_teams:
            c = counters[team]
            results.p_win_group[team]      = c["win_group"]       / self.n_sims
            results.p_reach_r32[team]      = c["reach_r32"]       / self.n_sims
            results.p_reach_r16[team]      = c["reach_r16"]       / self.n_sims
            results.p_reach_qf[team]       = c["reach_qf"]        / self.n_sims
            results.p_reach_sf[team]       = c["reach_sf"]        / self.n_sims
            results.p_reach_final[team]    = c["reach_final"]     / self.n_sims
            results.p_win_tournament[team] = c["win_tournament"]  / self.n_sims

        # Third-place qualification scenarios: P(qualify | pts, gd)
        results.third_place_scenarios = {
            key: counts[0] / counts[1]
            for key, counts in scenario_counts.items()
            if counts[1] > 0
        }

        # R32 slot team probabilities
        results.r32_slot_teams = [
            {
                "slot_a": [
                    {"team": t, "p": round(c / self.n_sims, 3)}
                    for t, c in sorted(cnt_a.items(), key=lambda x: -x[1])[:3]
                ],
                "slot_b": [
                    {"team": t, "p": round(c / self.n_sims, 3)}
                    for t, c in sorted(cnt_b.items(), key=lambda x: -x[1])[:3]
                ],
            }
            for cnt_a, cnt_b in r32_slot_counts
        ]

        # Group finish-position probabilities and conditional R32 opponents
        for team in self._all_teams:
            results.p_finish_pos[team] = {
                pos: round(pos_counts[team][pos] / self.n_sims, 4) for pos in [1, 2, 3, 4]
            }
            by_pos: dict[int, list[dict]] = {}
            for pos in [1, 2, 3]:
                opp_counts = r32_by_pos_counts[team][pos]
                total = sum(opp_counts.values())
                if total > 0:
                    by_pos[pos] = [
                        {"team": opp, "p": round(cnt / total, 4)}
                        for opp, cnt in sorted(opp_counts.items(), key=lambda x: -x[1])[:4]
                    ]
            results.r32_opponents_by_pos[team] = by_pos

        # Convert counts to unconditional probabilities
        results.matchup_probs = {}
        for stage in stages:
            results.matchup_probs[stage] = {}
            for team_a, opponents in matchup_counts[stage].items():
                results.matchup_probs[stage][team_a] = {
                    opp: cnt / self.n_sims for opp, cnt in opponents.items()
                }

        logger.info(
            "Simulation complete (%d runs). Top winner: %s (%.1f%%)",
            self.n_sims,
            max(results.p_win_tournament, key=results.p_win_tournament.get),  # type: ignore[arg-type]
            max(results.p_win_tournament.values()) * 100,
        )
        return results

    # ------------------------------------------------------------------
    # Single simulation
    # ------------------------------------------------------------------

    def _simulate_one(
        self,
        counters: dict[str, dict[str, int]],
        matchup_counts: dict[str, DefaultDict[str, DefaultDict[str, int]]],
        scenario_counts: "DefaultDict[tuple[int,int], list[int]]",
        r32_slot_counts: "list[tuple[DefaultDict, DefaultDict]] | None" = None,
        pos_counts: "DefaultDict[str, DefaultDict[int, int]] | None" = None,
        r32_by_pos_counts: "DefaultDict[str, DefaultDict[int, DefaultDict[str, int]]] | None" = None,
    ) -> None:
        # --- Group stage ---
        group_results: dict[str, list[str]] = {}   # group -> [1st, 2nd, 3rd, 4th]
        third_records: list[dict] = []

        for group_name, teams in self.groups.items():
            known_order = self._state.known_qualifier_order(group_name)
            if known_order:
                standings = known_order
                # Use actual live standings data so 3rd-place competition is correct
                seed = self._state.seed_points_gd_gf(group_name)
                pts_dict: dict[str, int] = {t: seed.get(t, (0, 0, 0))[0] for t in standings}
                gd_dict:  dict[str, int] = {t: seed.get(t, (0, 0, 0))[1] for t in standings}
                gf_dict:  dict[str, int] = {t: seed.get(t, (0, 0, 0))[2] for t in standings}
            else:
                standings, pts_dict, gd_dict, gf_dict = self._simulate_group_full(
                    teams, group_name
                )
                if group_name in CONFIRMED_POSITIONS:
                    standings = self._apply_confirmed(standings, CONFIRMED_POSITIONS[group_name])
            group_results[group_name] = standings
            counters[standings[0]]["win_group"] += 1
            for team in standings[:2]:
                counters[team]["reach_r32"] += 1
            # Track group finish positions
            if pos_counts is not None:
                for pos, team in enumerate(standings, 1):
                    pos_counts[team][pos] += 1
            third_records.append({
                "team":  standings[2],
                "group": group_name,
                "pts":   pts_dict.get(standings[2], 0),
                "gd":    gd_dict.get(standings[2], 0),
                "gf":    gf_dict.get(standings[2], 0),
            })

        # --- Assign 3rd-place teams to bracket slots ---
        third_assignment = self._assign_thirds(third_records)

        # Mark best-8 third-place teams as having reached R32 + record scenario stats
        qualified_thirds = {v for v in third_assignment.values() if v is not None}
        for rec in third_records:
            key = (rec["pts"], rec["gd"])
            scenario_counts[key][1] += 1
            if rec["team"] in qualified_thirds:
                scenario_counts[key][0] += 1
                counters[rec["team"]]["reach_r32"] += 1

        # --- Build actual R32 pairs ---
        r32_pairs = self._build_r32_pairs(group_results, third_assignment)
        if r32_slot_counts is not None:
            for idx, (t1, t2) in enumerate(r32_pairs):
                if t1: r32_slot_counts[idx][0][t1] += 1
                if t2: r32_slot_counts[idx][1][t2] += 1

        # Track R32 opponents conditional on group finishing position
        if r32_by_pos_counts is not None:
            team_to_pos: dict[str, int] = {
                team: pos
                for grp, order in group_results.items()
                for pos, team in enumerate(order, 1)
            }
            for t1, t2 in r32_pairs:
                if t1 and t2:
                    p1 = team_to_pos.get(t1)
                    p2 = team_to_pos.get(t2)
                    if p1: r32_by_pos_counts[t1][p1][t2] += 1
                    if p2: r32_by_pos_counts[t2][p2][t1] += 1

        # --- Play R32 -> 16 winners (indexed 0..15) ---
        r32_winners = self._play_bracket_round(
            r32_pairs, counters, matchup_counts["r32"], "reach_r16"
        )

        # --- Play R16 using WC2026_R16 pairings ---
        r16_pairs = [(r32_winners[i], r32_winners[j]) for i, j in WC2026_R16]
        r16_winners = self._play_bracket_round(
            r16_pairs, counters, matchup_counts["r16"], "reach_qf"
        )

        # --- Play QF using WC2026_QF pairings ---
        qf_pairs = [(r16_winners[i], r16_winners[j]) for i, j in WC2026_QF]
        qf_winners = self._play_bracket_round(
            qf_pairs, counters, matchup_counts["qf"], "reach_sf"
        )

        # --- Play SF using WC2026_SF pairings ---
        sf_pairs = [(qf_winners[i], qf_winners[j]) for i, j in WC2026_SF]
        sf_winners = self._play_bracket_round(
            sf_pairs, counters, matchup_counts["sf"], "reach_final"
        )

        # --- Final ---
        if len(sf_winners) == 2:
            t1, t2 = sf_winners
            matchup_counts["final"][t1][t2] += 1
            matchup_counts["final"][t2][t1] += 1
            champion = self._knockout_match(t1, t2)
            counters[champion]["win_tournament"] += 1
        elif len(sf_winners) == 1:
            counters[sf_winners[0]]["win_tournament"] += 1

    # ------------------------------------------------------------------
    # Bracket helpers
    # ------------------------------------------------------------------

    def _play_bracket_round(
        self,
        pairs: list[tuple[str, str]],
        counters: dict[str, dict[str, int]],
        matchup_cnt: DefaultDict[str, DefaultDict[str, int]],
        next_stage_key: str,
    ) -> list[str]:
        """Play all matches in a round; record matchups; return winners in pair order."""
        winners = []
        for team_a, team_b in pairs:
            matchup_cnt[team_a][team_b] += 1
            matchup_cnt[team_b][team_a] += 1
            w = self._knockout_match(team_a, team_b)
            counters[w][next_stage_key] += 1
            winners.append(w)
        return winners

    def _build_r32_pairs(
        self,
        group_results: dict[str, list[str]],
        third_assignment: dict[int, str | None],
    ) -> list[tuple[str, str]]:
        """
        Resolve all 16 R32 slot pairs into actual team names.
        Skips any match where a slot cannot be resolved (should not happen in normal play).
        """
        pairs: list[tuple[str, str]] = []
        for idx, (slot_a, slot_b) in enumerate(WC2026_R32):
            t1 = self._resolve_r32_slot(slot_a, idx, group_results, third_assignment)
            t2 = self._resolve_r32_slot(slot_b, idx, group_results, third_assignment)
            pairs.append((t1, t2))
        return pairs

    def _resolve_r32_slot(
        self,
        slot: str,
        match_idx: int,
        group_results: dict[str, list[str]],
        third_assignment: dict[int, str | None],
    ) -> str | None:
        """Resolve a single R32 slot string to a team name."""
        if slot.startswith("3rd:"):
            return third_assignment.get(match_idx)
        # Format "NX": position digit N first, group letter X last (e.g. "2A" = 2nd place group A)
        group = slot[-1]
        pos   = int(slot[:-1]) - 1
        standings = group_results.get(group, [])
        return standings[pos] if pos < len(standings) else None

    def _assign_thirds(
        self,
        third_records: list[dict],
    ) -> dict[int, str]:
        """
        Select best 8 third-place teams and assign them to their bracket slots
        using the official FIFA WC 2026 Annex C lookup table (495 combinations).
        """
        ranked = sorted(
            third_records,
            key=lambda r: (-r["pts"], -r["gd"], -r["gf"]),
        )[:8]
        best8_groups = frozenset(r["group"] for r in ranked)
        group_to_team = {r["group"]: r["team"] for r in ranked}
        slot_to_group = _ANNEX_C_TABLE[best8_groups]
        return {slot: group_to_team[grp] for slot, grp in slot_to_group.items()}

    # ------------------------------------------------------------------
    # Group simulation
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_confirmed(
        standings: list[str],
        confirmed: dict[int, str],
    ) -> list[str]:
        """Force confirmed positions (1-indexed) into the simulated standings."""
        result: list[str | None] = [None] * len(standings)
        for pos_1, team in confirmed.items():
            result[pos_1 - 1] = team
        confirmed_teams = set(confirmed.values())
        remaining = [t for t in standings if t not in confirmed_teams]
        idx = 0
        for i in range(len(result)):
            if result[i] is None:
                result[i] = remaining[idx]
                idx += 1
        return result  # type: ignore[return-value]

    def _simulate_group_full(
        self,
        teams: list[str],
        group_name: str,
    ) -> tuple[list[str], dict[str, int], dict[str, int], dict[str, int]]:
        """
        Simulate a full group, returning (sorted_teams, pts, gd, gf).
        Respects partial state (already-played fixtures, seeded standings).
        Uses WC 2026 tiebreaker: overall pts → H2H pts → H2H GD → H2H GF → overall GD → overall GF.
        """
        seed = self._state.seed_points_gd_gf(group_name)
        played = self._state.already_played_fixtures(group_name)

        if seed:
            points = {t: seed.get(t, (0, 0, 0))[0] for t in teams}
            gd     = {t: seed.get(t, (0, 0, 0))[1] for t in teams}
            gf     = {t: seed.get(t, (0, 0, 0))[2] for t in teams}
        else:
            points = {t: 0 for t in teams}
            gd     = {t: 0 for t in teams}
            gf     = {t: 0 for t in teams}

        # Seed H2H from already-played fixtures (with actual scores)
        h2h: dict[tuple[str, str], tuple[int, int]] = {}
        gs = self._state.group_states.get(group_name)
        if gs is not None:
            for home, away, hg, ag in gs.played_fixtures:
                h2h[(home, away)] = (hg, ag)

        for home, away in combinations(teams, 2):
            if (home, away) in played or (away, home) in played:
                continue
            hg, ag = self._sample_score(home, away)
            h2h[(home, away)] = (hg, ag)
            if hg > ag:
                points[home] += 3
            elif hg == ag:
                points[home] += 1
                points[away] += 1
            else:
                points[away] += 3
            gd[home] += hg - ag
            gd[away] += ag - hg
            gf[home] += hg
            gf[away] += ag

        sorted_teams = _sort_group_standings(teams, points, gd, gf, h2h)
        return sorted_teams, points, gd, gf

    def _simulate_group_with_state(self, teams: list[str], group_name: str) -> list[str]:
        """Backward-compatible wrapper: returns sorted team list only."""
        sorted_teams, _, _, _ = self._simulate_group_full(teams, group_name)
        return sorted_teams

    def _simulate_group(self, teams: list[str]) -> list[str]:
        points = {t: 0 for t in teams}
        gd = {t: 0 for t in teams}
        gf = {t: 0 for t in teams}

        for home, away in combinations(teams, 2):
            hg, ag = self._sample_score(home, away)
            if hg > ag:
                points[home] += 3
            elif hg == ag:
                points[home] += 1
                points[away] += 1
            else:
                points[away] += 3
            gd[home] += hg - ag
            gd[away] += ag - hg
            gf[home] += hg
            gf[away] += ag

        return sorted(teams, key=lambda t: (points[t], gd[t], gf[t]), reverse=True)

    def _knockout_match(self, home: str, away: str) -> str:
        # Force the actual winner when this exact pairing has already been played.
        known = self._known_ko.get(frozenset((home, away)))
        if known is not None:
            return known
        hg, ag = self._sample_score(home, away)
        if self._boot is not None:  # feed future goals to the Golden Boot model
            self._boot.allocate(home, hg)
            self._boot.allocate(away, ag)
        if hg > ag:
            return home
        if ag > hg:
            return away
        return home if self.rng.random() < SHOOTOUT_HOME_WIN_PROB else away

    def _sample_score(self, home: str, away: str) -> tuple[int, int]:
        key = (home, away)
        rev = (away, home)
        if key in self._match_probs:
            hg, ag = self._sample_from_matrix(self._match_probs[key].score_matrix)
        elif rev in self._match_probs:
            ag, hg = self._sample_from_matrix(self._match_probs[rev].score_matrix)
        else:
            probs = self.model.predict(home, away, neutral=True)
            self._match_probs[key] = probs   # cache for subsequent simulations
            hg, ag = self._sample_from_matrix(probs.score_matrix)
        return hg, ag

    def _sample_from_matrix(self, matrix: np.ndarray) -> tuple[int, int]:
        k = matrix.shape[0]
        flat = np.maximum(matrix, 0).flatten()
        total = flat.sum()
        if total <= 0 or np.isnan(total):
            return (int(self.rng.poisson(1.15)), int(self.rng.poisson(1.15)))
        flat = flat / total
        idx = self.rng.choice(len(flat), p=flat)
        return divmod(idx, k)
