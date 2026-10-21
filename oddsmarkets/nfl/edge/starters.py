"""
Starters out for the edge experiments: the production module models/availability.py (moved there on 21 Oct 2026 when
the feature was promoted), with the research cache data/nfl/cache/edge/starters_out.parquet.
"""
from __future__ import annotations

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models.availability import (GROUPS, MISSING_STATUS, P_MISS, POS2GRP, attach,  # noqa: F401
                                                 depth_starters, starters_out, team_alias)
from oddsmarkets.nfl.models import availability as _AV


def load(seasons, refresh: bool = False):
    return _AV.load(seasons, refresh=refresh, path=D.cache_root() / "edge" / "starters_out.parquet")
