"""
Shared betting-portfolio and backtest layer (docs/research/EDGE_PROTOCOL.md section 4).

    schema      load + validate data/edge/<sport>.parquet, leakage checks, settlement convention
    devig       multiplicative / additive / power / Shin de-vigging (default: power), vectorised by market group
    calibrate   fair probabilities, derived columns, walk-forward shrinkage of the model toward the market
    kelly       Kelly (binary, exclusive, simultaneous), flat, proportional-to-edge, caps, drawdown throttle
    backtest    event-ordered bankroll simulation by slate
    stats       unit-stake edge tests (CLV, ROI, bootstrap CIs, market-null and permutation p-values),
                portfolio metrics (log growth, drawdown, Sharpe, turnover, risk of ruin)
    synthetic   synthetic edge files with known truth
    report      the EDGE_RESULTS.md writer used by scripts/edge_backtest.py
"""
from .backtest import SimResult, simulate  # noqa: F401
from .calibrate import prepare, walk_forward_shrink  # noqa: F401
from .devig import DEFAULT_METHOD  # noqa: F401  (the devig module stays reachable as .devig)
from .kelly import SizingConfig, kelly_binary, kelly_exclusive, simultaneous_kelly  # noqa: F401
from .schema import LeakageError, SchemaError, load_edge_files, settle_profit, validate  # noqa: F401
