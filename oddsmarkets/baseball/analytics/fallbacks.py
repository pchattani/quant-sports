"""
Cold-cache fallbacks for CI, installed by scripts/build_bullpen.py without changing the model modules.

CI holds only the current season's pitch table. Builder D's projections weight three seasons of per-player count
aggregates; without the earlier seasons' Parquet they would project from the current season alone. scripts/mlb_fit.py
exports those aggregates (a few hundred KB) to models/fitted/proj_agg_{h,p}_<level>_<season>.parquet, and
`install()` wraps projections.season_aggregates so a season whose pitch table is absent reads the exported table.
A season with its pitch table on disk is untouched (the wrapper returns the model's own result).
"""
from __future__ import annotations

import functools
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
FITTED = Path(__file__).resolve().parents[1] / "models" / "fitted"
_INSTALLED = {"proj": False}


def agg_paths(level: str, season: int) -> tuple[Path, Path]:
    return FITTED / f"proj_agg_h_{level}_{int(season)}.parquet", FITTED / f"proj_agg_p_{level}_{int(season)}.parquet"


def fitted_aggregates(level: str, season: int) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    ph, pp = agg_paths(level, season)
    if not (ph.exists() and pp.exists()):
        return None
    try:
        return pd.read_parquet(ph), pd.read_parquet(pp)
    except Exception:                                            # noqa: BLE001
        return None


def install() -> bool:
    """Wrap projections.season_aggregates with the committed-aggregate fallback (idempotent)."""
    if _INSTALLED["proj"]:
        return True
    try:
        from oddsmarkets.baseball.models import _dio
        from oddsmarkets.baseball.models import projections as PJ
    except Exception:                                            # noqa: BLE001
        return False
    orig = PJ.season_aggregates

    @functools.wraps(orig)
    def season_aggregates(level: str, season: int, use_cache: bool = True):
        if not _dio.pitch_path(level, season).exists():
            f = fitted_aggregates(level, season)
            if f is not None:
                return f
        return orig(level, season, use_cache)
    season_aggregates.__wrapped_fallback__ = True             # type: ignore[attr-defined]
    PJ.season_aggregates = season_aggregates
    _INSTALLED["proj"] = True
    return True


def export_aggregates(level: str, seasons: list[int]) -> list[str]:
    """Write models/fitted/proj_agg_{h,p}_<level>_<season>.parquet from the local pitch tables (scripts/mlb_fit.py)."""
    from oddsmarkets.baseball.models import projections as PJ
    out = []
    FITTED.mkdir(parents=True, exist_ok=True)
    for s in seasons:
        h, p = PJ.season_aggregates(level, s)
        if not len(h) and not len(p):
            continue
        ph, pp = agg_paths(level, s)
        h.to_parquet(ph)
        p.to_parquet(pp)
        out += [str(ph), str(pp)]
    return out
