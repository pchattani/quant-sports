"""
Venue fees: the single source of truth for prediction-market venue fee schedules.

Every fee in the code base (the sport sites' market pages and edge studies, and any other caller) comes from here. Prices are
probabilities in [0, 1] (Kalshi cents / 100); fees are dollars. Verified against the venues' published schedules on
2026-10-02 (sources below); re-verify when a venue announces a change and add a dated entry rather than editing one.

Kalshi (CFTC DCM; Fee Schedule "July 2026 - 7.7.26 Update", https://kalshi.com/docs/kalshi-fee-schedule.pdf, and
the fee-rounding page https://docs.kalshi.com/getting_started/fee_rounding):
  taker fee = round_up( M x 0.07   x C x P x (1 - P) )
  maker fee = round_up( M_maker x 0.0175 x C x P x (1 - P) )
  * C contracts at price P in dollars; M the series multiplier (1 on the general schedule).
  * S&P 500 and Nasdaq-100 series (INX*, NASDAQ100*) trade at half the coefficient (0.035; Kalshi "We're halving
    the fees for our S&P and Nasdaq markets"); some series are fee-free (M = 0) and some sports series carry a
    reduced multiplier, reported per series by the API (`fee_type`, `fee_multiplier`). `kalshi_series_multiplier`
    covers the documented index cases; pass the API's multiplier when you have it.
  * Maker fees apply only on series flagged `quadratic_with_maker_fees` (most series: resting orders free). We
    default to charging them when maker=True (conservative); pass maker_multiplier=0 for a fee-free-maker series.
  * Rounding: the model fee of each fill is rounded up to $0.000001; a per-ORDER accumulator then rounds the
    member's balance change to its target precision -- $0.01 for non-direct (retail/FCM) members, $0.0001 for direct
    members -- rebating earlier over-rounding on later fills. Net effect for an order: ceil(sum of fill fees) to
    the precision. One 50c contract: 0.0175 -> $0.02. 100 contracts at 50c: $1.75 exactly.

Polymarket (two venues; Polymarket International is unavailable to US persons, Polymarket US is CFTC-regulated):
  International CLOB (https://docs.polymarket.com/trading/fees, read 2026-10-02):
    fee = C x rate x p x (1 - p), taker only; makers pay nothing (and receive rebates out of taker fees).
    rate by category: crypto 0.07; sports, economics, culture, weather, other 0.05; finance, politics, mentions,
    tech 0.04; geopolitics 0. Fees are rounded to 5 decimals (min 0.00001 USDC). Fee-free before 2026; a
    secondary source (rivermarkets) lists sports at 0.03 under "Fee Structure V2" (2026-03-30) -- the venue's docs
    say 0.05 today and win; historical sports trades between 2026-03-30 and the change may have paid 0.03.
  US (https://docs.polymarket.us/fees): fee = theta x C x p x (1 - p) for takers, maker REBATE 0.0125 x C x p x (1-p);
    theta = 0.0695 from 2026-10-01 14:00 UTC (10 AM ET), 0.06 from 2026-07-01; before that the legacy 10 bp of
    notional (screener/costs.py's old model; not re-verified). Fees and rebates are rounded to the cent with
    banker's rounding (half to even). Combo trades: C x p x [0.0695 (1 - p) + 0.06 (1 - p)^4].

Betfair Exchange: commission on NET market winnings (default 5%, the UK/IE base rate; some markets and
discount schemes differ -- pass `rate`). Losses pay nothing.

Conventions used by the sport studies (kept numerically identical when they were consolidated here):
  * `kalshi_fee_per_contract(p)` = 0.07 p (1 - p), unrounded: the per-contract fee of a large ("bulk") order, where
    the order-level round-up is under a cent spread over many contracts.
  * `kalshi_fee_single(p)` = the exact fee of a ONE-contract order (rounded up to the cent): the most conservative.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence

import numpy as np

# --------------------------------------------------------------------------------------------------------- Kalshi
KALSHI_TAKER_RATE = 0.07
KALSHI_MAKER_RATE = 0.0175
KALSHI_RETAIL_PRECISION = 0.01       # non-direct members: balance in whole cents
KALSHI_DIRECT_PRECISION = 0.0001     # direct members
# Series whose coefficient differs from the general schedule (multiplier on 0.07 / 0.0175). Prefix match on the
# series ticker with any leading "KX" removed.
KALSHI_SERIES_MULTIPLIERS: dict[str, float] = {"INX": 0.5, "NASDAQ100": 0.5}


def _dec(x: float) -> Decimal:
    # float -> Decimal through repr, then trimmed to 12 dp so binary noise (0.1 + 0.2) never tips a ceiling
    return Decimal(repr(float(x))).quantize(Decimal("1e-12"), rounding=ROUND_HALF_UP)


def _ceil_to(x: Decimal, step: float) -> Decimal:
    q = Decimal(repr(step))
    return (x / q).to_integral_value(rounding=ROUND_CEILING) * q


def kalshi_series_multiplier(series_ticker: str | None) -> float:
    """Documented fee multiplier for a Kalshi series ticker (1.0 unless listed in KALSHI_SERIES_MULTIPLIERS)."""
    if not series_ticker:
        return 1.0
    s = str(series_ticker).upper()
    s = s[2:] if s.startswith("KX") else s
    for pre, m in KALSHI_SERIES_MULTIPLIERS.items():
        if s.startswith(pre):
            return m
    return 1.0


def kalshi_fee_per_contract(price, maker: bool = False, multiplier: float = 1.0):
    """Unrounded fee per contract, rate x M x P x (1 - P); vectorised over numpy arrays. This is the bulk-order
    convention the sport edge studies use (the order-level round-up is spread over many contracts)."""
    rate = KALSHI_MAKER_RATE if maker else KALSHI_TAKER_RATE
    if np.ndim(price):
        p = np.asarray(price, float)
        return rate * multiplier * p * (1 - p)
    p = float(price)
    return rate * multiplier * p * (1 - p)


def _kalshi_model_fee(price: float, contracts: float, maker: bool, multiplier: float) -> Decimal:
    rate = KALSHI_MAKER_RATE if maker else KALSHI_TAKER_RATE
    p = _dec(price)
    raw = _dec(rate) * _dec(multiplier) * _dec(contracts) * p * (Decimal(1) - p)
    return _ceil_to(raw, 1e-6)                         # trade fee: ceil to $0.000001


def kalshi_fee(price: float, contracts: float = 1, maker: bool = False, multiplier: float = 1.0,
               precision: float = KALSHI_RETAIL_PRECISION) -> float:
    """Exact fee in dollars of ONE Kalshi order of `contracts` at `price`, rounded up to `precision` (the cent for
    retail members). Use `kalshi_order_fee` for an order filled at several prices."""
    if contracts <= 0:
        return 0.0
    if not (0.0 <= price <= 1.0):
        raise ValueError(f"price {price} outside [0, 1]")
    return float(_ceil_to(_kalshi_model_fee(price, contracts, maker, multiplier), precision))


def kalshi_order_fee(fills: Iterable[tuple[float, float]], maker: bool = False, multiplier: float = 1.0,
                     precision: float = KALSHI_RETAIL_PRECISION) -> float:
    """Fee of one order filled as [(price, contracts), ...]: each fill's fee is ceil'd to $0.000001, the order's
    accumulator rounds the total up to `precision` (Kalshi fee-rounding rules)."""
    tot = sum((_kalshi_model_fee(p, c, maker, multiplier) for p, c in fills if c > 0), Decimal(0))
    return float(_ceil_to(tot, precision)) if tot > 0 else 0.0


def kalshi_fee_single(price: float, maker: bool = False, multiplier: float = 1.0) -> float:
    """Fee of a one-contract order (rounded up to the cent): 0.02 at 50c, 0.01 at 3c."""
    return kalshi_fee(price, 1, maker=maker, multiplier=multiplier)


def kalshi_cost(price, maker: bool = False, multiplier: float = 1.0):
    """All-in cost per contract, price + bulk fee (vectorised)."""
    return price + kalshi_fee_per_contract(price, maker=maker, multiplier=multiplier)


def kalshi_decimal(ask: float | None, maker: bool = False, multiplier: float = 1.0) -> float | None:
    """Decimal odds of buying a Kalshi contract at `ask`, bulk fee included: 1 / (ask + fee); None if not 0 < ask < 1."""
    if ask is None:
        return None
    try:
        a = float(ask)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(a) or not (0 < a < 1):
        return None
    return 1.0 / kalshi_cost(a, maker=maker, multiplier=multiplier)


# ----------------------------------------------------------------------------------------------------- Polymarket
POLY_INTL_RATES: dict[str, float] = {
    "crypto": 0.07,
    "sports": 0.05, "economics": 0.05, "culture": 0.05, "weather": 0.05, "other": 0.05,
    "finance": 0.04, "politics": 0.04, "mentions": 0.04, "tech": 0.04,
    "geopolitics": 0.0,
}
POLY_INTL_FEES_START = datetime(2026, 1, 1, tzinfo=timezone.utc)     # fee-free before (approximate; see docstring)
# Polymarket US taker theta by effective time (UTC), newest last
POLY_US_THETA: list[tuple[datetime, float]] = [
    (datetime(2026, 7, 1, 4, 0, tzinfo=timezone.utc), 0.06),
    (datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc), 0.0695),
]
POLY_US_LEGACY_NOTIONAL_RATE = 0.001     # 10 bp of notional before 2026-07-01 (legacy, not re-verified)
POLY_US_MAKER_REBATE = 0.0125
POLY_US_COMBO_EXTRA = 0.06


def _asof(asof) -> datetime | None:
    if asof is None:
        return None
    if isinstance(asof, datetime):
        return asof if asof.tzinfo else asof.replace(tzinfo=timezone.utc)
    import pandas as pd
    t = pd.Timestamp(asof)
    return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).to_pydatetime()


def polymarket_us_theta(asof=None) -> float | None:
    """Taker theta in force at `asof` (latest if None); None before the quadratic schedule (legacy notional fee)."""
    t = _asof(asof)
    if t is None:
        return POLY_US_THETA[-1][1]
    th = None
    for start, v in POLY_US_THETA:
        if t >= start:
            th = v
    return th


def polymarket_fee_per_contract(price, venue: str = "international", category: str = "other",
                                maker: bool = False, asof=None):
    """Unrounded signed fee per contract (negative = rebate); vectorised."""
    p = np.asarray(price, float) if np.ndim(price) else float(price)
    if venue in ("international", "intl", "global"):
        if maker:
            return 0.0 * p
        t = _asof(asof)
        if t is not None and t < POLY_INTL_FEES_START:
            return 0.0 * p
        rate = POLY_INTL_RATES.get((category or "other").lower(), POLY_INTL_RATES["other"])
        return rate * p * (1 - p)
    if venue == "us":
        th = polymarket_us_theta(asof)
        if th is None:
            return 0.0 * p if maker else POLY_US_LEGACY_NOTIONAL_RATE * p
        if maker:
            return -POLY_US_MAKER_REBATE * p * (1 - p)
        return th * p * (1 - p)
    raise ValueError(f"unknown Polymarket venue {venue!r}")


def polymarket_fee(price: float, contracts: float = 1, venue: str = "international", category: str = "other",
                   maker: bool = False, asof=None, combo: bool = False) -> float:
    """Fee in dollars of one Polymarket trade (signed: negative = maker rebate on Polymarket US).
    International: rounded to 5 dp. US: rounded to the cent, banker's rounding."""
    if contracts <= 0:
        return 0.0
    if not (0.0 <= price <= 1.0):
        raise ValueError(f"price {price} outside [0, 1]")
    if venue == "us" and combo and not maker and polymarket_us_theta(asof) is not None:
        p = _dec(price)
        raw = _dec(contracts) * p * (_dec(polymarket_us_theta(asof)) * (1 - p) + _dec(POLY_US_COMBO_EXTRA) * (1 - p) ** 4)
    else:
        raw = _dec(contracts) * _dec(polymarket_fee_per_contract(price, venue, category, maker, asof))
    if venue == "us":
        return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))
    return float(raw.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP))


# -------------------------------------------------------------------------------------------------------- Betfair
BETFAIR_DEFAULT_RATE = 0.05


def betfair_commission(net_winnings: float, rate: float = BETFAIR_DEFAULT_RATE) -> float:
    """Commission on a market's net winnings (nothing on a net loss)."""
    return max(0.0, float(net_winnings)) * rate


def betfair_cost_per_unit(price: float, rate: float = BETFAIR_DEFAULT_RATE) -> float:
    """Expected commission per $1 of payout for a back bet at implied probability `price`, in probability units
    (screener convention): rate x (D - 1) / D with D = 1 / price. This is the cost if the bet wins, i.e.
    rate x (1 - price)."""
    d = 1.0 / max(price, 0.001)
    return rate * (d - 1.0) / d


# --------------------------------------------------------------------------------------------------- generic fee
def fee(venue: str, price: float, contracts: float = 1, maker: bool = False, **kw) -> float:
    """Dispatch: venue in kalshi | polymarket | polymarket_us | betfair (betfair: commission if the bet wins)."""
    v = venue.lower()
    if v == "kalshi":
        return kalshi_fee(price, contracts, maker=maker, **kw)
    if v in ("polymarket", "polymarket_intl", "poly"):
        return polymarket_fee(price, contracts, venue="international", maker=maker, **kw)
    if v == "polymarket_us":
        return polymarket_fee(price, contracts, venue="us", maker=maker, **kw)
    if v == "betfair":
        return betfair_commission(contracts * (1 - price), **kw)
    raise ValueError(f"unknown venue {venue!r}")


# ------------------------------------------------------------------------------------------------- book walking
@dataclass
class Fill:
    filled: float               # contracts filled
    requested: float
    notional: float             # sum price x size (dollars)
    fee: float                  # dollars, signed (negative = rebate)
    avg_price: float            # notional / filled (nan if nothing filled)
    all_in_price: float         # per contract incl. fees: buy (notional + fee) / filled, sell (notional - fee) / filled
    best_price: float           # touch price (nan if the side is empty)
    slippage: float             # avg_price - best (buy) or best - avg_price (sell), >= 0
    levels: list[tuple[float, float]] = field(default_factory=list)   # (price, size) taken at each level

    @property
    def unfilled(self) -> float:
        return self.requested - self.filled

    @property
    def complete(self) -> bool:
        return self.filled >= self.requested - 1e-9


def _levels(book, side: str) -> list[tuple[float, float]]:
    """Normalise a book to the levels a `side` order takes: buy lifts asks (ascending), sell hits bids (descending).
    `book`: dict with 'asks'/'bids' (lists of (price, size) or dicts), a DataFrame [side, price, size] or
    [price, size] already for the right side, or a plain list of (price, size) levels for the right side."""
    key = "asks" if side == "buy" else "bids"
    lv = book
    if isinstance(book, dict):
        lv = book.get(key) or book.get("ask" if side == "buy" else "bid") or []
    elif hasattr(book, "columns"):
        df = book
        if "side" in df.columns:
            names = {"ask", "asks", "sell", "yes_ask"} if side == "buy" else {"bid", "bids", "buy", "yes_bid"}
            df = df[df["side"].astype(str).str.lower().isin(names)]
        lv = list(zip(df["price"].astype(float), df["size"].astype(float)))
    out = []
    for x in lv:
        if isinstance(x, dict):
            p, s = float(x["price"]), float(x.get("size", x.get("quantity", 0)))
        else:
            p, s = float(x[0]), float(x[1])
        if s > 0:
            out.append((p, s))
    out.sort(key=lambda t: t[0], reverse=(side == "sell"))
    return out


def fill_cost(book, side: str, size: float, venue: str = "kalshi", maker: bool = False,
              limit: float | None = None, **fee_kw) -> Fill:
    """Walk `book` for an order of `size` contracts. side: 'buy' (YES, lifts asks) or 'sell' (hits bids).
    `limit` caps the worst price taken. The fee is the venue's: Kalshi rounds the whole order (accumulator), a
    Polymarket trade is charged per fill (each level a separate match), Betfair commission is not a trade fee (0)."""
    side = side.lower()
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    lv = _levels(book, side)
    best = lv[0][0] if lv else float("nan")
    left, taken = float(size), []
    for p, s in lv:
        if left <= 1e-12:
            break
        if limit is not None and ((side == "buy" and p > limit + 1e-12) or (side == "sell" and p < limit - 1e-12)):
            break
        q = min(s, left)
        taken.append((p, q))
        left -= q
    filled = sum(q for _, q in taken)
    notional = sum(p * q for p, q in taken)
    v = venue.lower()
    if v == "kalshi":
        f = kalshi_order_fee(taken, maker=maker, **fee_kw)
    elif v in ("polymarket", "poly", "polymarket_intl"):
        f = sum(polymarket_fee(p, q, venue="international", maker=maker, **fee_kw) for p, q in taken)
    elif v == "polymarket_us":
        f = sum(polymarket_fee(p, q, venue="us", maker=maker, **fee_kw) for p, q in taken)
    elif v in ("betfair", "none"):
        f = 0.0
    else:
        raise ValueError(f"unknown venue {venue!r}")
    f = round(f, 10)
    if filled > 0:
        avg = notional / filled
        all_in = (notional + f) / filled if side == "buy" else (notional - f) / filled
        slip = (avg - best) if side == "buy" else (best - avg)
    else:
        avg = all_in = slip = float("nan")
    return Fill(filled=filled, requested=float(size), notional=round(notional, 10), fee=f, avg_price=avg,
                all_in_price=all_in, best_price=best, slippage=slip, levels=taken)


def kalshi_book_sides(yes_bids: Sequence, no_bids: Sequence) -> dict:
    """Kalshi's order book lists YES bids and NO bids only; a NO bid at q is a YES ask at 1 - q. Returns the YES
    book {'bids': [(p, size)...], 'asks': [(1 - q, size)...]} (prices in dollars; cents are converted if > 1)."""
    def _p(x):
        x = float(x)
        return x / 100.0 if x > 1.0 else x
    bids = [(_p(p), float(s)) for p, s in yes_bids]
    asks = [(round(1.0 - _p(q), 6), float(s)) for q, s in no_bids]
    return {"bids": sorted(bids, key=lambda t: -t[0]), "asks": sorted(asks, key=lambda t: t[0])}


__all__ = [
    "KALSHI_TAKER_RATE", "KALSHI_MAKER_RATE", "KALSHI_SERIES_MULTIPLIERS", "kalshi_series_multiplier",
    "kalshi_fee", "kalshi_order_fee", "kalshi_fee_per_contract", "kalshi_fee_single", "kalshi_cost", "kalshi_decimal",
    "POLY_INTL_RATES", "POLY_US_THETA", "polymarket_us_theta", "polymarket_fee", "polymarket_fee_per_contract",
    "betfair_commission", "betfair_cost_per_unit", "fee", "Fill", "fill_cost", "kalshi_book_sides",
]
