"""
Loading and validating `data/edge/<sport>.parquet` (EDGE_PROTOCOL.md section 3), with leakage checks.

Contract enforced here:
  * required columns present and typed; times coerced to UTC;
  * decision_time strictly before start_time (a bet placed after the start is leakage, not a pre-match bet);
  * a decision-time price exists (price_dec finite and > 1) and model_p is a probability in (0, 1);
  * outcome in [0, 1] (fractions encode pushes / half results, see `settle_profit`); NaN = unsettled, excluded;
  * no duplicate decisions;
  * "no future columns": the portfolio layer only ever reads DECISION_COLS when deciding and sizing
    (see `decision_view`), POST_COLS only when settling and reporting. Extra columns in a file are listed and
    the ones whose names look post-event are flagged. Two statistical tripwires look for leaked information:
    a model that beats the closing line by an implausible margin, and a model that tracks the closing price
    more closely than the decision price it is supposed to have used.

Rows failing a hard check are dropped and counted. A file where more than `quarantine_share` of rows fail the
timing check is quarantined (excluded entirely): a systematic timing bug poisons every row, not just the
ones caught. `strict=True` raises instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED = ["event_id", "sport", "market", "selection", "start_time", "decision_time", "model_p", "price_dec", "outcome"]
OPTIONAL = ["league", "season", "line", "price_src", "fair_p_decision", "price_close", "fair_p_close", "slate",
            "corr_group", "max_stake_hint", "settle_time"]
# Recognised extras (not in the protocol table, honoured when present):
#   fee         per-contract fee in payout units (Kalshi convention: a $1 contract bought at ask a costs a + fee);
#               folded into the price: price_net = 1 / (1/price_dec + fee)
#   split       'dev' / 'train' / 'tune' rows are the sport agent's tuning period: used to fit the shrinkage
#               (they are the past) but never bet or scored; every other value is out of sample
#   quality_ok  False rows are never bet or scored (the sport agent flagged their data)
#   line_close  the closing line; where it differs from `line` the closing price is for another line and the
#               row gets no CLV
KNOWN_EXTRAS = ["fee", "split", "quality_ok", "line_close"]
PROTOCOL_COLS = REQUIRED + OPTIONAL
# What the decision/sizing step may see. Everything here is known at decision_time.
DECISION_COLS = ["event_id", "sport", "league", "season", "market", "selection", "line", "start_time",
                 "decision_time", "model_p", "price_dec", "price_src", "fair_p_decision", "slate", "corr_group",
                 "max_stake_hint", "fee"]
# Known only after the decision: used for settlement and evaluation, never for deciding.
POST_COLS = ["outcome", "price_close", "fair_p_close", "settle_time"]
_SUSPECT = re.compile(r"(close|closing|result|score|final|winner|outcome|settle|post|after|actual|label|target|y_?true)",
                      re.I)


class SchemaError(ValueError):
    pass


class LeakageError(ValueError):
    pass


@dataclass
class Validation:
    source: str
    rows_in: int = 0
    rows_out: int = 0
    dropped: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    quarantined: bool = False
    extra_cols: list = field(default_factory=list)

    def drop(self, why: str, n: int) -> None:
        if n:
            self.dropped[why] = self.dropped.get(why, 0) + int(n)

    def summary(self) -> str:
        d = ", ".join(f"{k}: {v}" for k, v in self.dropped.items()) or "none"
        s = f"{self.source}: {self.rows_in} rows in, {self.rows_out} kept; dropped {d}"
        if self.quarantined:
            s += "; QUARANTINED"
        return s


def _to_utc(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        # epoch seconds or milliseconds
        v = pd.to_numeric(s, errors="coerce")
        unit = "ms" if v.dropna().abs().median() > 1e11 else "s"
        return pd.to_datetime(v, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(s, utc=True, errors="coerce", format="mixed")


def settle_profit(outcome, price) -> np.ndarray:
    """
    Profit per unit staked. outcome is the fraction of the selection that won, on a quarter grid:
        1 win -> price-1;  0.75 half-win -> (price-1)/2;  0.5 push/void -> 0;  0.25 half-loss -> -1/2;  0 loss -> -1.
    Linear between those points: o >= 0.5 -> 2(o-0.5)(price-1);  o < 0.5 -> -(1-2o).
    """
    o = np.asarray(outcome, dtype=float)
    p = np.asarray(price, dtype=float)
    return np.where(o >= 0.5, 2.0 * (o - 0.5) * (p - 1.0), -(1.0 - 2.0 * o))


def validate(df: pd.DataFrame, source: str = "frame", strict: bool = False, quarantine_share: float = 0.05,
             allow_close_at_start: bool = True) -> tuple[pd.DataFrame, Validation]:
    v = Validation(source=source, rows_in=len(df))
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise SchemaError(f"{source}: missing required columns {missing}")
    v.extra_cols = [c for c in df.columns if c not in PROTOCOL_COLS + KNOWN_EXTRAS]
    suspect = [c for c in v.extra_cols if _SUSPECT.search(str(c))]
    if suspect:
        v.warnings.append(f"extra columns with post-event-looking names (never read by the portfolio layer): {suspect}")
    d = df.copy()
    for c in OPTIONAL:
        if c not in d.columns:
            d[c] = np.nan
    d["price_src"] = d["price_src"].astype(object).where(d["price_src"].notna(), "unknown").astype(str)
    d["start_time"] = _to_utc(d["start_time"])
    d["decision_time"] = _to_utc(d["decision_time"])
    d["settle_time"] = _to_utc(d["settle_time"]) if d["settle_time"].notna().any() else pd.NaT
    for c in ("model_p", "price_dec", "fair_p_decision", "price_close", "fair_p_close", "outcome", "line",
              "max_stake_hint") + (("line_close",) if "line_close" in d else ()):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    for c in ("event_id", "sport", "market", "selection"):
        d[c] = d[c].astype(str)
    lg = d["league"].astype(object)
    d["league"] = lg.where(lg.notna() & (lg.astype(str) != ""), d["sport"]).astype(str)
    yr = d["start_time"].dt.year.astype("Int64").astype(object)
    d["season"] = d["season"].astype(object).where(d["season"].notna(), yr).astype(str)

    bad_time = d["start_time"].isna() | d["decision_time"].isna()
    v.drop("missing start/decision time", bad_time.sum())
    d = d[~bad_time]

    at_off = d["decision_time"] == d["start_time"]
    close_src = d["price_src"].str.lower().str.contains("close")
    allowed_off = at_off & close_src & (allow_close_at_start and not strict)
    is_future = d["market"].astype(str).str.lower().str.startswith("future")
    fut_off = at_off & is_future & ~allowed_off & (not strict)
    if fut_off.any():
        v.warnings.append(f"{int(fut_off.sum())} futures rows have decision_time == start_time (start_time used as "
                          f"the quote time): kept; a future is judged against its settlement, not a start")
    allowed_off = allowed_off | fut_off
    if (allowed_off & ~is_future).any():
        v.warnings.append(f"{int((allowed_off & ~is_future).sum())} rows decide AT start_time with a closing price "
                          f"(price_src contains 'close'): kept as close-time decisions, which can never show CLV; "
                          f"the start_time is presumably a scheduled/date proxy. Strictly the protocol wants "
                          f"decision_time < start_time.")
    late = (d["decision_time"] >= d["start_time"]) & ~allowed_off
    n_late = int(late.sum())
    if n_late:
        msg = f"{n_late} rows ({n_late / max(len(d), 1):.1%}) have decision_time >= start_time (leakage)"
        if strict:
            raise LeakageError(f"{source}: {msg}")
        v.errors.append(msg)
        if n_late / max(len(d), 1) > quarantine_share:
            v.quarantined = True
            v.errors.append(f"over {quarantine_share:.0%} of rows fail the timing check: file quarantined")
    v.drop("decision_time >= start_time", n_late)
    d = d[~late]

    if d["settle_time"].notna().any():
        early_settle = d["settle_time"].notna() & (d["settle_time"] < d["start_time"])
        v.drop("settle_time before start_time", early_settle.sum())
        d = d[~early_settle]

    no_price = ~(np.isfinite(d["price_dec"]) & (d["price_dec"] > 1.0))
    if no_price.any() and strict:
        raise LeakageError(f"{source}: {int(no_price.sum())} rows have no valid decision-time price")
    v.drop("no valid decision-time price", no_price.sum())
    d = d[~no_price]

    edge_p = d["model_p"].isin([0.0, 1.0])
    if edge_p.any():
        v.warnings.append(f"{int(edge_p.sum())} rows with model_p exactly 0 or 1 clipped to [1e-4, 1-1e-4] (kept so "
                          f"multi-runner markets stay complete)")
        d["model_p"] = d["model_p"].clip(1e-4, 1 - 1e-4)
    bad_p = ~((d["model_p"] > 0.0) & (d["model_p"] < 1.0))
    v.drop("model_p not in (0,1)", bad_p.sum())
    d = d[~bad_p]

    bad_o = d["outcome"].notna() & ~d["outcome"].between(0.0, 1.0)
    v.drop("outcome outside [0,1]", bad_o.sum())
    d = d[~bad_o]
    uns = d["outcome"].isna()
    v.drop("unsettled (outcome NaN)", uns.sum())
    d = d[~uns]

    for c in ("price_close",):
        bad = d[c].notna() & ~(d[c] > 1.0)
        if bad.any():
            v.warnings.append(f"{int(bad.sum())} rows with {c} <= 1 set to NaN")
            d.loc[bad, c] = np.nan
    for c in ("fair_p_decision", "fair_p_close"):
        bad = d[c].notna() & ~d[c].between(0.0, 1.0, inclusive="neither")
        if bad.any():
            v.warnings.append(f"{int(bad.sum())} rows with {c} outside (0,1) set to NaN")
            d.loc[bad, c] = np.nan

    key = ["event_id", "market", "selection", "line", "decision_time", "price_src"]
    dup = d.duplicated(subset=key, keep="first")
    v.drop("duplicate decision rows", dup.sum())
    d = d[~dup]

    if d["slate"].isna().any():
        auto = d["sport"] + ":" + d["decision_time"].dt.strftime("%Y-%m-%d")
        d["slate"] = d["slate"].where(d["slate"].notna(), auto)
    d["slate"] = d["slate"].astype(str)
    d["corr_group"] = d["corr_group"].where(d["corr_group"].notna(), d["sport"] + ":" + d["event_id"]).astype(str)

    _tripwires(d, v)
    v.rows_out = 0 if v.quarantined else len(d)
    return (d.iloc[0:0] if v.quarantined else d.reset_index(drop=True)), v


def _ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _tripwires(d: pd.DataFrame, v: Validation, min_rows: int = 300) -> None:
    """Statistical leakage tripwires (warnings, not drops)."""
    b = d[d["outcome"].isin([0.0, 1.0])]
    has = b["fair_p_close"].notna() & b["fair_p_decision"].notna()
    bb = b[has]
    if len(bb) >= min_rows:
        y = bb["outcome"].to_numpy()
        ll_model = _ll(bb["model_p"].to_numpy(), y).mean()
        ll_close = _ll(bb["fair_p_close"].to_numpy(), y).mean()
        if ll_close - ll_model > 0.02:
            v.warnings.append(f"LEAKAGE? model log-loss {ll_model:.4f} beats the de-vigged close {ll_close:.4f} by "
                              f"{ll_close - ll_model:.4f} nats/bet, an implausible margin for a pre-event model")
        moved = (bb["fair_p_close"] - bb["fair_p_decision"]).abs() > 0.01
        if moved.sum() >= min_rows // 2:
            m = bb[moved]
            dc = (m["model_p"] - m["fair_p_close"]).abs().mean()
            dd = (m["model_p"] - m["fair_p_decision"]).abs().mean()
            if dc < 0.5 * dd:
                v.warnings.append(f"LEAKAGE? where the line moved, model_p sits closer to the CLOSE (mean |diff| "
                                  f"{dc:.4f}) than to the decision price ({dd:.4f}); check the model does not use "
                                  f"the closing line")
    hd = b[b["fair_p_decision"].notna()]
    if len(hd) >= min_rows:
        y = hd["outcome"].to_numpy()
        ll_m = _ll(hd["model_p"].to_numpy(), y).mean()
        ll_d = _ll(hd["fair_p_decision"].to_numpy(), y).mean()
        if ll_d - ll_m > 0.03:
            v.warnings.append(f"LEAKAGE? model log-loss {ll_m:.4f} beats the decision-time market {ll_d:.4f} by "
                              f"{ll_d - ll_m:.4f} nats/bet, far beyond any published pre-event edge")


def decision_view(df: pd.DataFrame, extra: tuple = ()) -> pd.DataFrame:
    """The columns a decision may use. Sizing functions receive only this."""
    cols = [c for c in DECISION_COLS if c in df.columns] + [c for c in extra if c in df.columns]
    leaked = [c for c in cols if c in POST_COLS]
    if leaked:
        raise LeakageError(f"post-decision columns requested in a decision view: {leaked}")
    return df[cols]


def load_edge_files(paths, strict: bool = False) -> tuple[pd.DataFrame, list[Validation]]:
    frames, reports = [], []
    for p in paths:
        p = Path(p)
        try:
            raw = pd.read_parquet(p)
        except Exception as e:  # noqa: BLE001  unreadable or half-written file
            v = Validation(source=p.name)
            v.errors.append(f"unreadable: {e!r}")
            v.quarantined = True
            reports.append(v)
            continue
        try:
            d, v = validate(raw, source=p.name, strict=strict)
        except SchemaError as e:
            v = Validation(source=p.name, rows_in=len(raw))
            v.errors.append(str(e))
            v.quarantined = True
            reports.append(v)
            continue
        d["source_file"] = p.name
        frames.append(d)
        reports.append(v)
    frames = [f for f in frames if len(f)]
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PROTOCOL_COLS + ["source_file"])
    return df, reports
