"""
The tennis edge pipeline (docs/research/EDGE_PROTOCOL.md; results in docs/research/tennis_edge.md).

    uv run python scripts/tn_edge.py            # experiments, betting tables, Kalshi test, data/edge/tennis.parquet

Decision times. tennis-data.co.uk carries closing prices only (Pinnacle, Bet365, Max and Avg from Oddsportal,
Betfair exchange from 2025); there is no opening price. So for those books the decision time is the close (the
start of the match) and:
* CLV of a bet at price P is fair_close * P - 1 with fair_close = Pinnacle's multiplicatively de-vigged close (the
  sharpest price in the file). A bet at Pinnacle's own close has CLV = minus half its margin by construction; a bet
  at the Max price (the best price across Oddsportal's books at the close) is the only tennis-data bet that can
  beat Pinnacle's close, which makes "Max-odds shopping against Pinnacle fair" the closing-time test.
* Kalshi (from June 2025) gives a genuinely earlier decision time ("open", "late": kalshi_edge.py), judged against
  tennis-data's later close.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.research import experiment as X
from oddsmarkets.tennis.research import kalshi_edge as KE

S = X.Spec
ALL = ["gelo", "form", "rank", "pts", "rest", "m7", "m30", "g3", "g7", "prev", "prev_sets", "b2b", "ret", "wo", "layoff",
       "layoff120", "since_layoff", "qual", "home", "h2h", "x_bo5", "x_tb", "x_indoor", "x_new", "x_early", "x_level250"]

FUNDAMENTAL = [
    S("E1 prod recalibrated", ["model"], note="production blend, one slope refitted"),
    S("E2 Elo + serve/return refit", ["elo", "sr"], note="blend weights refitted annually"),
    S("E3 + game-share Elo (MOV)", ["model", "gelo"]),
    S("E4 + recent form", ["model", "form"]),
    S("E5 + ranking", ["model", "rank"]),
    S("E6 + ranking points", ["model", "pts"]),
    S("E7 + rest / activity", ["model", "rest", "m7", "m30"]),
    S("E8 + fatigue (games, sets, minutes)", ["model", "g3", "g7", "prev", "prev_sets", "b2b"]),
    S("E9 + WTA minutes played", ["model", "min3"], note="WTA only (durations from 2020)"),
    S("E10 + retirement / layoff", ["model", "ret", "wo", "layoff", "layoff120", "since_layoff"]),
    S("E11 + qualifier", ["model", "qual"]),
    S("E12 + home country", ["model", "home"]),
    S("E13 + head-to-head (shrunk)", ["model", "h2h"]),
    S("E14 + interactions (bo5, pace, indoor, new, early round, 250)",
      ["model", "x_bo5", "x_tb", "x_indoor", "x_new", "x_early", "x_level250"]),
    S("E15 all features", ["model"] + ALL),
    S("E16 all features, ridge 20", ["model"] + ALL, ridge=20.0),
    S("E17 core (game Elo, rest, points, form, retirement, h2h)",
      ["model", "gelo", "rest", "m30", "pts", "form", "ret", "h2h"]),
]
MARKET = [
    S("M1 Pinnacle recalibrated", ["ps"], ridge=1.0),
    S("M2 Pinnacle power de-vig, recalibrated", ["ps_pow"], ridge=1.0),
    S("M3 Pinnacle + model", ["ps", "model"], ridge=1.0),
    S("M4 Pinnacle + model + game Elo", ["ps", "model", "gelo"], ridge=5.0),
    S("M5 Pinnacle + rest/fatigue", ["ps", "rest", "m7", "m30", "g3", "g7", "prev", "prev_sets", "b2b"], ridge=5.0),
    S("M6 Pinnacle + retirement/layoff", ["ps", "ret", "wo", "layoff", "layoff120", "since_layoff"], ridge=5.0),
    S("M7 Pinnacle + qualifier/home/h2h", ["ps", "qual", "home", "h2h"], ridge=5.0),
    S("M8 Pinnacle + model + all, ridge 20", ["ps", "model"] + ALL, ridge=20.0),
    S("M9 Pinnacle + model + all, ridge 100", ["ps", "model"] + ALL, ridge=100.0),
    S("M10 Pinnacle power + model + all, ridge 100", ["ps_pow", "model"] + ALL, ridge=100.0),
]
BEST_FUND = "E15 all features"
BEST_MKT = "M10 Pinnacle power + model + all, ridge 100"
FLB = "M2 Pinnacle power de-vig, recalibrated"


def quality(df: pd.DataFrame) -> pd.Series:
    """True where the closing odds look sane enough to bet against: Pinnacle margin in [0, 10] %, the Max prices not
    a cross-book arbitrage of 3 % or more and neither Max price more than 1.5 x Pinnacle's."""
    ps_ov = 1 / df["ps_A"] + 1 / df["ps_B"]
    mx_ov = 1 / df["max_A"] + 1 / df["max_B"]
    ratio = np.maximum(df["max_A"] / df["ps_A"], df["max_B"] / df["ps_B"])
    ok = ps_ov.between(1.0, 1.10) & (mx_ov >= 0.97) & (ratio <= 1.5)
    return ok.fillna(False)


def bets(df: pd.DataFrame, p: pd.Series, book: str, thr: float, years, mask=None) -> pd.DataFrame:
    m = df["year"].isin(years) & p.notna() & df[f"{book}_A"].notna() & df["ps_fair"].notna() & df["q_ok"]
    if mask is not None:
        m &= mask
    d, p = df[m], p[m]
    out = []
    for side in ("A", "B"):
        q = p if side == "A" else 1 - p
        o = d[f"{book}_{side}"]
        fair = d["ps_fair"] if side == "A" else 1 - d["ps_fair"]
        ev = q * o - 1
        win = d["y"] if side == "A" else 1 - d["y"]
        sel = ev > thr
        out.append(pd.DataFrame({"ev": ev[sel], "odds": o[sel], "clv": (fair * o - 1)[sel], "pnl": (win * o - 1)[sel],
                                 "event": d["event"][sel].astype(str), "year": d["year"][sel], "level": d["level"][sel],
                                 "round": d["round"][sel], "fair": fair[sel]}))
    return pd.concat(out)


def summarise(b: pd.DataFrame) -> dict:
    if len(b) == 0:
        return {"n": 0}
    lo, hi = X.boot_ci(b["pnl"].to_numpy(), b["event"].to_numpy())
    clo, chi = X.boot_ci(b["clv"].to_numpy(), b["event"].to_numpy(), seed=3)
    return {"n": int(len(b)), "mean_odds": round(float(b["odds"].mean()), 3), "ev": round(float(b["ev"].mean()), 4),
            "clv": round(float(b["clv"].mean()), 4), "clv_ci": [round(clo, 4), round(chi, 4)],
            "roi": round(float(b["pnl"].mean()), 4), "roi_ci": [round(lo, 4), round(hi, 4)]}


def tour_tables(tour: str, log=print) -> tuple[dict, pd.DataFrame]:
    df = X.load(tour)
    df["q_ok"] = quality(df)
    res: dict = {"tour": tour, "n_rows": int(len(df)), "n_ps": int(df["ps_fair"].notna().sum()),
                 "n_quality_dropped": int((df["ps_fair"].notna() & ~df["q_ok"]).sum()), "experiments": [], "bets": [],
                 "strata": []}
    preds: dict = {"prod": df["model"], "ps_fair": df["ps_fair"]}
    res["baseline"] = {"dev": X.score(df, df["model"], X.DEV), "test": X.score(df, df["model"], X.TEST)}
    for sp in FUNDAMENTAL + MARKET:
        if sp.feats == ["model", "min3"] and tour != "wta":
            continue
        r = X.run(df, sp)
        preds[sp.name] = r.pop("_pred")
        res["experiments"].append(r)
        log(f"{tour} {sp.name:55s} dev {r['dev']['ll']:.5f} (prod {r['dev']['ll_prod']:.5f}, ps {r['dev']['ll_ref']:.5f})"
            f" | test {r['test']['ll']:.5f} d_prod {r['test']['d_prod']:+.5f} {r['test']['d_prod_ci']}"
            f" d_ps {r['test']['d_ref']:+.5f} {r['test']['d_ref_ci']}")
    res["coefs_best_fund"] = X.coefs(df, next(s for s in FUNDAMENTAL if s.name == BEST_FUND))
    res["coefs_best_mkt"] = X.coefs(df, next(s for s in MARKET if s.name == BEST_MKT))
    # betting at closing prices, test years only
    strategies = [("model (production) @ Pinnacle", "prod", "ps"), ("model (production) @ Max", "prod", "max"),
                  ("model E15 @ Pinnacle", BEST_FUND, "ps"), ("model E15 @ Max", BEST_FUND, "max"),
                  ("model E15 @ Bet365", BEST_FUND, "b365"),
                  ("Pinnacle fair @ Max (line shopping)", "ps_fair", "max"),
                  ("FLB-corrected Pinnacle M2 @ Max", FLB, "max"), ("FLB-corrected Pinnacle M2 @ Pinnacle", FLB, "ps"),
                  ("market + model M10 @ Max", BEST_MKT, "max"), ("market + model M10 @ Pinnacle", BEST_MKT, "ps"),
                  ("market + model M10 @ Bet365", BEST_MKT, "b365")]
    for label, key, book in strategies:
        for thr in (0.0, 0.02, 0.05):
            for split, yrs in (("test", X.TEST), ("dev", X.DEV)):
                s = summarise(bets(df, preds[key], book, thr, yrs))
                res["bets"].append({"strategy": label, "book": book, "thr": thr, "split": split, **s})
                if split == "test":
                    log(f"{tour} BET {label:40s} thr {thr:.2f} {s}")
    # strata for the two closing-time strategies that can beat Pinnacle's close
    for label, key in (("FLB-corrected Pinnacle M2 @ Max", FLB), ("market + model M10 @ Max", BEST_MKT),
                       ("model E15 @ Max", BEST_FUND)):
        b = bets(df, preds[key], "max", 0.02, X.TEST)
        b["rank_max"] = np.nan
        groups = {"level": b["level"],
                  "round": np.where(b["round"].isin(["R128", "R64", "R32"]), "early (R128-R32)",
                                    np.where(b["round"].isin(["R16", "QF"]), "middle (R16-QF)", "late (SF-F, RR)")),
                  "odds": pd.cut(b["odds"], [1, 1.5, 2.0, 3.0, 5.0, 1000]).astype(str),
                  "year": b["year"]}
        for gname, g in groups.items():
            for val, bb in b.groupby(g):
                res["strata"].append({"strategy": label, "by": gname, "value": str(val), **summarise(bb)})
    df["_p_fund"] = preds[BEST_FUND]
    df["_p_mkt"] = preds[BEST_MKT]
    df["_p_flb"] = preds[FLB]
    return res, df


# ── Kalshi ───────────────────────────────────────────────────────────────────

def kalshi_tables(tour: str, df: pd.DataFrame, log=print) -> tuple[dict, pd.DataFrame]:
    k = KE.load(tour)
    out: dict = {"tour": tour, "n_events": 0}
    if k.empty:
        return out, k
    j = k.merge(df[["id", "A", "B", "y", "year", "event", "level", "round", "_p_fund", "model", "ps_fair", "bfe_fair",
                    "avg_fair", "ps_A", "ps_B", "bfe_A", "bfe_B", "avg_A", "avg_B", "max_A", "max_B"]], on="id", how="inner")
    if j.empty:
        return out, j
    xa = j["x_pid"] == j["A"]
    j["mid_A"] = np.where(xa, (j["bid"] + j["ask"]) / 2, 1 - (j["bid"] + j["ask"]) / 2)
    j["ask_A"] = np.where(xa, j["ask"], 1 - j["bid"])          # cost of a $1 contract on A
    j["ask_B"] = np.where(xa, 1 - j["bid"], j["ask"])
    ref = j["ps_fair"].fillna(j["bfe_fair"]).fillna(j["avg_fair"])
    j["close_fair"] = ref
    # a reference close on the other side of a day-ahead Kalshi quote by more than 0.30 is a tennis-data orientation
    # error (seen: a 2026 Wimbledon semi-final whose odds are swapped against the result, Kalshi and the model), so
    # those matches are dropped from the Kalshi test (both decisions); the count is reported
    op = j[j["decision"] == "open"].set_index("id")["mid_A"]
    bad = set(op.index[(op - j[j["decision"] == "open"].set_index("id")["close_fair"]).abs() > 0.30])
    out["dropped_bad_close"] = len(bad)
    j = j[~j["id"].isin(bad)].copy()
    j["close_src"] = np.where(j["ps_fair"].notna(), "pinnacle", np.where(j["bfe_fair"].notna(), "betfair", np.where(j["avg_fair"].notna(), "avg", None)))
    out["n_events"] = int(j["id"].nunique())
    out["by_decision"] = {}
    for dname, g in j.groupby("decision"):
        g = g[g["_p_fund"].notna()]
        y = g["y"].to_numpy(float)
        r = {"n": int(len(g))}
        for name, p in (("kalshi_mid", g["mid_A"]), ("model_E15", g["_p_fund"]), ("model_prod", g["model"]),
                        ("close_fair", g["close_fair"])):
            mm = p.notna()
            r[f"ll_{name}"] = round(float(X.ll_vec(p[mm], y[mm.to_numpy()]).mean()), 5) if mm.any() else None
        both = g["close_fair"].notna()
        if both.any():
            gg = g[both]
            yy = gg["y"].to_numpy(float)
            d = X.ll_vec(gg["mid_A"], yy) - X.ll_vec(gg["close_fair"], yy)
            lo, hi = X.boot_ci(d, gg["event"].astype(str).to_numpy())
            r["kalshi_minus_close"] = {"n": int(len(gg)), "d": round(float(d.mean()), 5), "ci": [round(lo, 5), round(hi, 5)]}
            d2 = X.ll_vec(gg["_p_fund"], yy) - X.ll_vec(gg["mid_A"], yy)
            lo, hi = X.boot_ci(d2, gg["event"].astype(str).to_numpy())
            r["model_minus_kalshi"] = {"d": round(float(d2.mean()), 5), "ci": [round(lo, 5), round(hi, 5)]}
        # bets: the model against Kalshi's ask (fee included in the edge test and P&L), CLV v the later close
        for thr in (0.0, 0.02, 0.05):
            rows = []
            for side in ("A", "B"):
                q = g["_p_fund"] if side == "A" else 1 - g["_p_fund"]
                cost = g[f"ask_{side}"] + KE.fee(g[f"ask_{side}"])
                ev = q / cost - 1
                win = g["y"] if side == "A" else 1 - g["y"]
                fair = g["close_fair"] if side == "A" else 1 - g["close_fair"]
                sel = (ev > thr) & fair.notna()
                rows.append(pd.DataFrame({"ev": ev[sel], "odds": (1 / cost)[sel], "clv": (fair / cost - 1)[sel],
                                          "pnl": (win / cost - 1)[sel], "event": g["event"][sel].astype(str)}))
            r[f"bets_model_thr{thr}"] = summarise(pd.concat(rows))
        # market blend at the decision: logit p = a logit(Kalshi mid) + b logit(model), fitted on earlier months of
        # Kalshi rows only (at least 300), judged against the ask at that time and the later close
        g = g.assign(month=pd.to_datetime(g["ts"], unit="s").dt.strftime("%Y-%m"))
        pb = pd.Series(np.nan, index=g.index)
        Xk = np.column_stack([X.logit(g["mid_A"]), X.logit(g["_p_fund"])])
        yk = g["y"].to_numpy(float)
        months = sorted(g["month"].unique())
        coef = None
        for mo in months:
            tr = (g["month"] < mo).to_numpy()
            te = (g["month"] == mo).to_numpy()
            if tr.sum() < 300:
                continue
            coef = X.fit_logit(Xk[tr], yk[tr], ridge=1.0)
            pb[te] = X.sig(Xk[te] @ coef)
        r["blend_coef_last"] = [round(float(c), 4) for c in coef] if coef is not None else None
        mb = pb.notna()
        if mb.any():
            yy = yk[mb.to_numpy()]
            a = X.ll_vec(pb[mb], yy)
            b = X.ll_vec(g.loc[mb, "mid_A"], yy)
            lo, hi = X.boot_ci(a - b, g.loc[mb, "event"].astype(str).to_numpy())
            r["blend_minus_kalshi"] = {"n": int(mb.sum()), "d": round(float((a - b).mean()), 5),
                                       "ci": [round(lo, 5), round(hi, 5)]}
            for thr in (0.0, 0.02, 0.05):
                rows = []
                gg = g[mb]
                for side in ("A", "B"):
                    q = pb[mb] if side == "A" else 1 - pb[mb]
                    cost = gg[f"ask_{side}"] + KE.fee(gg[f"ask_{side}"])
                    ev = q / cost - 1
                    win = gg["y"] if side == "A" else 1 - gg["y"]
                    fair = gg["close_fair"] if side == "A" else 1 - gg["close_fair"]
                    sel = (ev > thr) & fair.notna()
                    rows.append(pd.DataFrame({"ev": ev[sel], "odds": (1 / cost)[sel], "clv": (fair / cost - 1)[sel],
                                              "pnl": (win / cost - 1)[sel], "event": gg["event"][sel].astype(str)}))
                r[f"bets_blend_thr{thr}"] = summarise(pd.concat(rows))
        out["by_decision"][dname] = r
        log(f"{tour} KALSHI {dname} {r}")
    return out, j


# ── output file ──────────────────────────────────────────────────────────────

def _start_times(tour: str) -> dict:
    out = {}
    for m in _io.load_matches(tour, statuses=None):
        d = str(m.get("date") or "")
        if "T" in d:
            try:
                out[m["id"]] = datetime.fromisoformat(d[:16]).replace(tzinfo=timezone.utc)
                continue
            except ValueError:
                pass
        dd = _io.day(d)
        if dd:
            out[m["id"]] = datetime(dd.year, dd.month, dd.day, 12, tzinfo=timezone.utc)
    return out


def edge_rows(tour: str, df: pd.DataFrame, kal: pd.DataFrame) -> pd.DataFrame:
    """Protocol rows (one per selection per decision per price source) for every match with an out-of-sample
    prediction (2012 onward)."""
    st = _start_times(tour)
    d = df[df["_p_fund"].notna()].copy()
    d["start_time"] = d["id"].map(st)
    d["split"] = np.where(d["year"].isin(X.DEV), "dev", np.where(d["year"].isin(X.TEST), "test", "2026"))
    frames = []
    src = {"ps": "tdc_pinnacle_close", "max": "tdc_max_close", "b365": "tdc_b365_close", "avg": "tdc_avg_close",
           "bfe": "tdc_betfair_close"}
    close_fair = d["ps_fair"].fillna(d["bfe_fair"]).fillna(d["avg_fair"])
    close_src = np.where(d["ps_fair"].notna(), "ps", np.where(d["bfe_fair"].notna(), "bfe", "avg"))
    for side in ("A", "B"):
        sgn = side == "A"
        for book, name in src.items():
            pr = d[f"{book}_{side}"]
            ok = pr.notna()
            if not ok.any():
                continue
            g = d[ok]
            cf = close_fair[ok]
            fair_dec = (g[f"{book}_A"].rdiv(1) / (g[f"{book}_A"].rdiv(1) + g[f"{book}_B"].rdiv(1)))
            pc = np.where(close_src[ok.to_numpy()] == "ps", g[f"ps_{side}"],
                          np.where(close_src[ok.to_numpy()] == "bfe", g[f"bfe_{side}"], g[f"avg_{side}"]))
            frames.append(pd.DataFrame({
                "event_id": g["id"], "sport": "tennis", "league": tour, "season": g["year"], "start_time": g["start_time"],
                "market": "moneyline", "selection": np.where(sgn, g["A"], g["B"]), "line": np.nan,
                "decision_time": g["start_time"], "model_p": g["_p_fund"] if sgn else 1 - g["_p_fund"],
                "model_p_mkt": g["_p_mkt"] if sgn else 1 - g["_p_mkt"],
                "model_p_flb": g["_p_flb"] if sgn else 1 - g["_p_flb"],
                "price_dec": pr[ok], "price_src": name,
                "fair_p_decision": (cf if sgn else 1 - cf),
                "devig": "multiplicative (" + pd.Series(close_src[ok.to_numpy()], index=g.index) + " close)",
                "book_fair_p": fair_dec if sgn else 1 - fair_dec,
                "price_close": pc, "fair_p_close": (cf if sgn else 1 - cf),
                "outcome": g["y"] if sgn else 1 - g["y"], "slate": g["date"].astype(str) + f"|tennis-{tour}",
                "corr_group": g["id"], "max_stake_hint": np.nan, "level": g["level"], "round": g["round"],
                "split": g["split"], "quality_ok": g["q_ok"], "fee": 0.0}))
    if kal is not None and not kal.empty:
        k = kal[kal["_p_fund"].notna()].copy()
        k["start_time"] = k["id"].map(st)
        for side in ("A", "B"):
            sgn = side == "A"
            cost = k[f"ask_{side}"]
            close_price = np.where(k["close_src"] == "pinnacle", k[f"ps_{side}"],
                                   np.where(k["close_src"] == "betfair", k[f"bfe_{side}"], k[f"avg_{side}"]))
            frames.append(pd.DataFrame({
                "event_id": k["id"], "sport": "tennis", "league": tour, "season": k["year"], "start_time": k["start_time"],
                "market": "moneyline", "selection": np.where(sgn, k["A"], k["B"]), "line": np.nan,
                "decision_time": pd.to_datetime(k["ts"], unit="s", utc=True),
                "model_p": k["_p_fund"] if sgn else 1 - k["_p_fund"], "model_p_mkt": np.nan, "model_p_flb": np.nan,
                "price_dec": 1 / cost, "price_src": "kalshi_ask_" + k["decision"],
                "fair_p_decision": k["mid_A"] if sgn else 1 - k["mid_A"], "devig": "kalshi mid (bid+ask)/2",
                "book_fair_p": k["mid_A"] if sgn else 1 - k["mid_A"],
                "price_close": close_price, "fair_p_close": k["close_fair"] if sgn else 1 - k["close_fair"],
                "outcome": k["y"] if sgn else 1 - k["y"], "slate": k["date"].astype(str) + f"|tennis-{tour}",
                "corr_group": k["id"], "max_stake_hint": k["candle_volume"], "level": k["level"],
                "round": k["round"], "split": np.where(k["year"] >= 2026, "2026", "test"), "quality_ok": True,
                "fee": KE.fee(cost)}))
    out = pd.concat(frames, ignore_index=True)
    out["outcome"] = out["outcome"].astype(float)
    return out


def main(tours=("atp", "wta"), log=print) -> dict:
    allres: dict = {}
    rows = []
    for t in tours:
        res, df = tour_tables(t, log)
        kres, kal = kalshi_tables(t, df, log)
        res["kalshi"] = kres
        allres[t] = res
        rows.append(edge_rows(t, df, kal))
        del df, kal
    out = pd.concat(rows, ignore_index=True)
    p = _io.ROOT / "data" / "edge" / "tennis.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(p, index=False)
    allres["parquet"] = {"path": str(p), "rows": int(len(out)),
                         "by_src": {k: int(v) for k, v in out["price_src"].value_counts().items()}}
    (_io.ROOT / "data" / "edge" / "cache" / "tennis_results.json").write_text(json.dumps(_io.clean(allres), indent=1),
                                                                              encoding="utf-8")
    return allres
