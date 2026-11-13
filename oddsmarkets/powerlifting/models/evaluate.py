"""Fit, choose and score the meet forecast (models/forecast.py) on the sealed windows (models/backtest.py).

    evaluate(walked, entries, p, m0) -> (report dict for model.json, the live Model, the entrant frame)

Variants of expected DOTS, fitted on TRAIN: "last" (the last meet), "buckets" (+ meets so far, age, time away),
"full" (+ distance of the last meet from the rating and from the best). The variant is chosen on VALID; TEST is
scored once. The chosen variant goes live only if it beats the last meet on TEST (promotion rule); otherwise the
last meet is the forecast. The live model is refitted on everything through TEST_END, so meets from 2026 on are
still forecast out of sample.

Podium: the simulation (normal totals around the forecast, the bomb-out chance), blended with the rank table (the
training share of podiums by our forecast rank and flight size), against two simpler rules: the rank table alone and
an even share (3 / flight size).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import backtest as BT
from . import forecast as F

logger = logging.getLogger(__name__)
VARIANTS = ("last", "buckets", "full")


def entrant_frame(entries: pd.DataFrame, since: str = "2016-01-01", keep_dd: bool = False) -> pd.DataFrame:
    """Full-power entries from `since` with a stream, one row per lifter per meet, bomb-outs included.

    keep_dd: keep doping disqualifications (place DD). The sealed evaluation leaves them out; a meet page keeps them,
    because they lifted in the flight and the disqualification came after the meet (no look-ahead)."""
    e = entries[(entries["event"] == "SBD") & (entries["date"] >= since) & entries["sex"].isin(("M", "F")) &
                entries["eq"].isin(("raw", "wraps", "equipped"))].copy()
    e["stream"] = np.where(e["sex"] == "M", "men_", "women_") + e["eq"].map({"raw": "raw", "wraps": "wraps", "equipped": "eq"})
    e["date"] = pd.to_datetime(e["date"])
    e["dq"] = e["place"].astype(str).eq("DQ") | e["total"].isna()
    e = e[~e["place"].astype(str).isin(("G", "NS") if keep_dd else ("G", "NS", "DD"))]
    e = e.sort_values("total", ascending=False).drop_duplicates(["meet_id", "pid", "stream", "division"], keep="first")
    return e.reset_index(drop=True)


def _rank_table(df: pd.DataFrame) -> dict:
    """P(podium) by (flight size capped at 12, our forecast rank capped at 12), from training flights."""
    t = df.groupby(["size_c", "rank_c"])["pod"].agg(["mean", "size"])
    return {(int(a), int(b)): float(v["mean"]) for (a, b), v in t.iterrows() if v["size"] >= 30}


def podium_frame(ent: pd.DataFrame, model: F.Model, sims: int = 300, sd_scale: float = 1.0) -> pd.DataFrame:
    """Flights of 4+ with every entrant: forecast in kg, simulated podium and win chances, the even share and our rank."""
    fc = model.forecast(ent)
    bw = ent["bw"]
    mu_kg = F.to_kg(ent["sex"], bw, fc["mu"].to_numpy())
    sd_kg = F.to_kg(ent["sex"], bw, fc["sd"].to_numpy()) * sd_scale
    g = F.flights(ent)
    d = ent.assign(flight=g, mu=fc["mu"].to_numpy(), sd=fc["sd"].to_numpy(), p_bomb=fc["p_bomb"].to_numpy(), mu_kg=mu_kg, sd_kg=sd_kg,
                   new=fc["new"].to_numpy())
    d = d[np.isfinite(d["mu_kg"])]
    size = d.groupby("flight")["pid"].transform("size")
    d = d[size >= 4].copy()
    d["size"] = d.groupby("flight")["pid"].transform("size")
    d["rank"] = d.groupby("flight")["mu_kg"].rank(ascending=False, method="first")
    d["size_c"] = d["size"].clip(upper=12)
    d["rank_c"] = d["rank"].clip(upper=12)
    pl = pd.to_numeric(d["place"], errors="coerce")
    d["pod"] = (pl <= 3).astype(float)
    d["won"] = (pl == 1).astype(float)
    d["p_even"] = np.minimum(1.0, 3.0 / d["size"])
    if not sims:
        return d
    codes = pd.factorize(d["flight"])[0]
    p_pod, p_win = F.simulate_podium(codes, d["mu_kg"].to_numpy(float), d["sd_kg"].to_numpy(float), d["p_bomb"].to_numpy(float), sims=sims)
    d["p_pod"], d["p_win"] = p_pod, p_win
    d["p_even"] = np.minimum(1.0, 3.0 / d["size"])
    return d


def evaluate(walked: pd.DataFrame, entries: pd.DataFrame, p, m0: dict, podium: bool = True) -> tuple[dict, F.Model, pd.DataFrame, dict]:
    rows = walked[(walked["n"] > 0) & walked["last_dots"].notna()]
    first = walked[(walked["n"] == 0) & (walked["date"] <= BT.TRAIN_END) & walked["scored"]]
    train = BT.window(rows, "train")
    ent = entrant_frame(entries, since="2010-01-01")
    ent = F.pre_state(ent, walked, p, m0)
    ent["new"] = ent["n"] == 0
    ent_train = BT.window(ent, "train")
    models = {v: F.Model(variant=v).fit(train, first, ent_train) for v in VARIANTS}
    rep = {"variants": {}, "baselines": {}}
    for name in ("train", "valid", "test"):
        d = BT.window(rows, name)
        rep["baselines"][name] = {"rating": BT.errors(d["dots"], d["pre"])}
        for v, m in models.items():
            rep["variants"].setdefault(v, {})[name] = BT.errors(d["dots"], m.mu(d))
    chosen = min(("buckets", "full"), key=lambda v: rep["variants"][v]["valid"]["rmse"] or 1e9)
    test = BT.window(rows, "test")
    e_last = test["dots"] - models["last"].mu(test)
    e_new = test["dots"] - models[chosen].mu(test)
    e_rt = test["dots"] - test["pre"]
    rep["paired"] = {
        "vs_last": BT.paired(e_last ** 2, e_new ** 2, test["meet_id"]),
        "vs_rating": BT.paired(e_rt ** 2, e_new ** 2, test["meet_id"]),
        "last_vs_rating": BT.paired(e_rt ** 2, e_last ** 2, test["meet_id"]),
    }
    # calibration of the spread: share of test results inside the 80% band
    sd = models[chosen].spread(test)
    z = np.abs(e_new.to_numpy() / sd)
    rep["band80"] = round(float(np.mean(z <= 1.2816)), 4)
    live_variant = chosen if rep["paired"]["vs_last"]["better"] else "last"
    rep["chosen"], rep["live"] = chosen, live_variant
    # bins of expected v actual on the test years (the chosen variant)
    mu_t = models[chosen].mu(test)
    qs = np.unique(np.quantile(mu_t, np.linspace(0, 1, 11)))
    cal = []
    for lo, hi in zip(qs[:-1], qs[1:]):
        m = (mu_t >= lo) & (mu_t <= hi)
        if m.sum() >= 100:
            cal.append({"lo": round(float(lo), 1), "hi": round(float(hi), 1), "n": int(m.sum()),
                        "pred": round(float(mu_t[m].mean()), 1), "actual": round(float(test["dots"].to_numpy()[m].mean()), 1)})
    rep["calibration"] = cal
    # by meets so far: where the forecast is hard
    B = F.buckets(test)
    rep["by_n"] = [{"nb": lab, "n": int((B["nb"] == lab).sum()),
                    "rmse": round(float(np.sqrt(np.mean(e_new[B["nb"] == lab] ** 2))), 1),
                    "rmse_last": round(float(np.sqrt(np.mean(e_last[B["nb"] == lab] ** 2))), 1)}
                   for lab in F.N_LABS if (B["nb"] == lab).sum() >= 100]
    rep["coef"] = models[chosen].to_json()
    # the live model: refitted through the test years
    allrows = rows[rows["date"] <= BT.TEST_END]
    first_all = walked[(walked["n"] == 0) & (walked["date"] <= BT.TEST_END) & walked["scored"]]
    live = F.Model(variant=live_variant).fit(allrows, first_all, ent[ent["date"] <= BT.TEST_END])
    if podium:
        rep["podium"] = podium_report(ent, models[chosen] if live_variant == chosen else models["last"])
    return rep, live, ent, models


def podium_report(ent: pd.DataFrame, model: F.Model) -> dict:
    """The simulation alone is too sure in the tails (a flight rarely goes exactly to form: the lowest bin said 1.6%
    and 5.9% made the podium), so the live chance blends it with the rank table. The spread scale and the blend weight
    are chosen on the validation years by log loss; the test years are scored once, against the rank table (fitted on
    the training flights) and the even share."""
    span = ent[(ent["date"] > "2015-12-31") & (ent["date"] <= BT.TEST_END)]
    tr = podium_frame(BT.window(span, "train"), model, sims=0)
    table = _rank_table(tr)
    wtab = _rank_table(tr.assign(pod=tr["won"]))

    def ranked(x):
        x["p_rank"] = [table.get((int(a), int(b)), np.nan) for a, b in zip(x["size_c"], x["rank_c"])]
        x["p_rank"] = x["p_rank"].fillna(x["p_even"])
        x["p_rankw"] = [wtab.get((int(a), int(b)), np.nan) for a, b in zip(x["size_c"], x["rank_c"])]
        x["p_rankw"] = x["p_rankw"].fillna(1.0 / x["size"])
        return x

    best = None
    for sc in (1.0, 1.3, 1.6):
        dv = ranked(podium_frame(BT.window(span, "valid"), model, sims=200, sd_scale=sc))
        if dv.empty:
            break
        for e in (0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5):
            ll = BT.brier_logloss((1 - e) * dv["p_pod"] + e * dv["p_rank"], dv["pod"])[1].mean()
            if best is None or ll < best[0]:
                best = (ll, sc, e)
    _, scale, eps = best if best is not None else (None, 1.0, 0.0)
    out = {"flights_min": 4, "eps": eps, "sd_scale": scale,
           "rank_table": [[a, b, round(v, 4), round(wtab.get((a, b), float("nan")), 4)] for (a, b), v in sorted(table.items())]}
    for name in ("valid", "test"):
        x = podium_frame(BT.window(span, name), model, sims=200, sd_scale=scale)
        if x.empty:
            continue
        x = ranked(x)
        x["p_sim"] = x["p_pod"]
        x["p_pod"] = (1 - eps) * x["p_sim"] + eps * x["p_rank"]
        x["p_win"] = (1 - eps) * x["p_win"] + eps * x["p_rankw"]
        rec = {"n": int(len(x)), "flights": int(x["flight"].nunique()), "base_rate": round(float(x["pod"].mean()), 4)}
        losses = {}
        for k in ("p_pod", "p_sim", "p_rank", "p_even"):
            b, ll = BT.brier_logloss(x[k], x["pod"])
            losses[k] = (b, ll)
            rec[k] = {"brier": round(float(b.mean()), 4), "logloss": round(float(ll.mean()), 4)}
        rec["sim_vs_rank"] = BT.paired(losses["p_rank"][1], losses["p_pod"][1], x["flight"])
        rec["sim_vs_rank_brier"] = BT.paired(losses["p_rank"][0], losses["p_pod"][0], x["flight"])
        rec["sim_vs_even"] = BT.paired(losses["p_even"][1], losses["p_pod"][1], x["flight"])
        rec["reliability"] = BT.reliability(x["p_pod"], x["pod"])
        rec["reliability_rank"] = BT.reliability(x["p_rank"], x["pod"])
        bw, llw = BT.brier_logloss(x["p_win"], x["won"])
        bw2, llw2 = BT.brier_logloss(x["p_rankw"], x["won"])
        rec["win"] = {"brier": round(float(bw.mean()), 4), "logloss": round(float(llw.mean()), 4), "base_rate": round(float(x["won"].mean()), 4),
                      "rank_brier": round(float(bw2.mean()), 4), "rank_logloss": round(float(llw2.mean()), 4)}
        out[name] = rec
    t = out.get("test") or {}
    out["promoted"] = bool((t.get("sim_vs_rank") or {}).get("better"))
    return out
