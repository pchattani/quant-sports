"""
Synthetic edge files where the truth is known, for tests and for developing the report before real data lands.

kind="binary"   one selection per event (a yes/no prop). Market fair m ~ U(0.25, 0.70); price = 1/(m(1+vig)).
                With `edge` > 0 the true win probability is (1+edge)/price, so EVERY bet has true expected return
                exactly `edge`; the model knows it (model_p = truth, optionally noised). The close is efficient
                (fair close = truth) when close_eff = 1.  With edge = None the truth is the market (p = m) and the
                model is the market plus noise: no edge.
kind="two_way"  home/away events. Truth logit L ~ N(0, 1). Market logit = L + N(0, s_market); model logit =
                L + N(0, s_model) if informative else market logit + N(0, s_model); close logit = L + N(0, s_close).
kind="1x2"      three-way events (home/draw/away) from a draw-inflated logistic; same noise structure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _expit(x):
    return 1.0 / (1.0 + np.exp(-x))


def _times(n_events: int, per_slate: int, start: str, rng, lead_h: float):
    day = np.arange(n_events) // per_slate
    st = pd.Timestamp(start, tz="UTC") + pd.to_timedelta(day, unit="D") + pd.to_timedelta(
        rng.uniform(12, 22, n_events), unit="h")
    dec = st.normalize() - pd.Timedelta(hours=lead_h) + pd.Timedelta(hours=12)
    return st, dec, day


def make_synthetic(kind: str = "binary", n_events: int = 6000, edge: float | None = 0.03, sport: str = "synth",
                   vig: float = 0.04, seed: int = 0, start: str = "2020-01-01", per_slate: int = 20,
                   close_eff: float = 1.0, model_noise: float = 0.0, informative: bool = True,
                   s_market: float = 0.25, s_model: float = 0.15, s_close: float = 0.10, push_rate: float = 0.0,
                   lead_h: float = 24.0, leagues: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    st, dec, day = _times(n_events, per_slate, start, rng, lead_h)
    league = np.array([f"{sport}_L{i}" for i in rng.integers(0, leagues, n_events)])
    ev = np.array([f"{sport}_{i}" for i in range(n_events)])
    base = {"sport": sport, "season": st.year.astype(str)}

    if kind == "binary":
        m = rng.uniform(0.25, 0.70, n_events)
        price = 1.0 / (m * (1.0 + vig))
        if edge is None:
            p = m
            model = _expit(np.log(m / (1 - m)) + rng.normal(0, max(model_noise, 0.2), n_events))
        else:
            p = np.clip((1.0 + edge) / price, 1e-4, 1 - 1e-4)
            model = _expit(np.log(p / (1 - p)) + rng.normal(0, model_noise, n_events)) if model_noise else p
        fc = close_eff * p + (1 - close_eff) * m
        if s_close:
            fc = _expit(np.log(fc / (1 - fc)) + rng.normal(0, s_close, n_events))
        y = (rng.random(n_events) < p).astype(float)
        if push_rate:
            y[rng.random(n_events) < push_rate] = 0.5
        return pd.DataFrame({
            "event_id": ev, **base, "league": league, "start_time": st, "market": "prop_yes", "selection": "yes",
            "line": np.nan, "decision_time": dec, "model_p": model, "price_dec": price, "price_src": "synth_open",
            "fair_p_decision": m, "price_close": 1.0 / (fc * (1.0 + vig)), "fair_p_close": fc, "outcome": y,
            "slate": [f"{sport}:{d}" for d in day], "corr_group": ev, "max_stake_hint": np.nan})

    if kind in ("two_way", "1x2"):
        L = rng.normal(0, 1.0, n_events)
        Lm = L + rng.normal(0, s_market, n_events)
        Lmod = (L if informative else Lm) + rng.normal(0, s_model, n_events)
        Lc = L + rng.normal(0, s_close, n_events)
        if kind == "two_way":
            def probs(x):
                ph = _expit(x)
                return np.column_stack([ph, 1 - ph])
            sels = ["home", "away"]
            market = "moneyline"
        else:
            def probs(x):
                k = 0.9  # draw-inflated logistic: 3 categories
                ph = _expit(x - k / 2 + 0.2)
                pa = _expit(-x - k / 2)
                pd_ = np.clip(1 - ph - pa, 0.05, None)
                P = np.column_stack([ph, pd_, pa])
                return P / P.sum(axis=1, keepdims=True)
            sels = ["home", "draw", "away"]
            market = "1x2"
        Pt, Pm, Pmod, Pc = probs(L), probs(Lm), probs(Lmod), probs(Lc)
        if edge is None and not informative:
            Pt = Pm  # truth is the market
        cum = Pt.cumsum(axis=1)
        u = rng.random(n_events)
        win = (u[:, None] < cum).argmax(axis=1)
        price = 1.0 / (Pm * (1.0 + vig))
        close = 1.0 / (Pc * (1.0 + vig))
        k = len(sels)
        rows = {
            "event_id": np.repeat(ev, k), "sport": sport, "season": np.repeat(st.year.astype(str), k),
            "league": np.repeat(league, k), "start_time": np.repeat(st, k), "market": market,
            "selection": np.tile(sels, n_events), "line": np.nan, "decision_time": np.repeat(dec, k),
            "model_p": Pmod.ravel(), "price_dec": price.ravel(), "price_src": "synth_open",
            "fair_p_decision": Pm.ravel(), "price_close": close.ravel(), "fair_p_close": Pc.ravel(),
            "outcome": (np.arange(k)[None, :] == win[:, None]).astype(float).ravel(),
            "slate": np.repeat([f"{sport}:{d}" for d in day], k), "corr_group": np.repeat(ev, k),
            "max_stake_hint": np.nan,
        }
        return pd.DataFrame(rows)
    raise ValueError(kind)
