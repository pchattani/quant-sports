"""The Quant Iron's analytics: weight classes, attempts, age curves, class moves, federations, formulas, lift ratios,
records and the per-lifter profile behind the Scouting Room. Pure functions of the stores (no network).

Everything descriptive here is computed on what had happened by the build date; nothing feeds back into the
forecast except through models/forecast.py, which fits only on the training years.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import canon

# IPF classes (2019 onwards): the upper limit of each class in kg; above the last is "+"
IPF = {"M": [59, 66, 74, 83, 93, 105, 120], "F": [47, 52, 57, 63, 69, 76, 84]}
LIFTS = (("squat", "Squat", "s"), ("bench", "Bench", "b"), ("dead", "Deadlift", "d"))
MODERN = "2012-01-01"          # attempts, ages and the raw era: the Lab's analyses start here


def ipf_class(sex, bw) -> str | None:
    if bw is None or not np.isfinite(bw):
        return None
    lims = IPF["F" if sex == "F" else "M"]
    for x in lims:
        if bw <= x:
            return str(x)
    return f"{lims[-1]}+"


def ipf_class_vec(sex: pd.Series, bw: pd.Series) -> pd.Series:
    out = pd.Series(pd.NA, index=bw.index, dtype="object")
    for sx in ("M", "F"):
        lims = np.array(IPF[sx], dtype=float)
        m = (sex == sx) & bw.notna()
        if not m.any():
            continue
        i = np.searchsorted(lims, bw[m].to_numpy(dtype=float), side="left")
        labels = np.array([str(x) for x in IPF[sx]] + [f"{IPF[sx][-1]}+"], dtype=object)
        out.loc[m] = labels[i]
    return out


def class_order(sex: str) -> list[str]:
    lims = IPF["F" if sex == "F" else "M"]
    return [str(x) for x in lims] + [f"{lims[-1]}+"]


def _r(x, k=1):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, k) if np.isfinite(v) else None


# ── attempts ──────────────────────────────────────────────────────────────────────────────────────────────────
JUMP_BINS = [0.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 1000.0]
JUMP_LABELS = ["0-2.5%", "2.5-5%", "5-7.5%", "7.5-10%", "10-12.5%", "12.5-15%", "15%+"]


def attempts(entries: pd.DataFrame, since: str = MODERN) -> dict:
    """Make rates by lift and attempt, by the size of the jump, and the third-attempt strategy."""
    cols = ["s1", "s2", "s3", "b1", "b2", "b3", "d1", "d2", "d3"]
    if not set(cols) <= set(entries.columns):
        return {}
    e = entries[(entries["event"] == "SBD") & (entries["date"] >= since)]
    e = e[e[cols].notna().sum(axis=1) >= 6]
    out = {"n_lifters": int(len(e)), "since": since[:4], "lifts": {}, "jumps": {}, "third": {}, "by_stream": {}}
    for lift, label, k in LIFTS:
        a = [e[f"{k}{i}"].to_numpy(dtype=float) for i in (1, 2, 3)]
        rows = []
        for i in range(3):
            v = a[i]
            ok = np.isfinite(v) & (v != 0)
            rows.append({"att": i + 1, "n": int(ok.sum()), "made": _r(100 * np.mean(v[ok] > 0), 1) if ok.any() else None})
        out["lifts"][lift] = {"label": label, "attempts": rows}
        # the jump from the last made attempt to the next one, and how often it goes
        js = []
        for i in (1, 2):
            prev, nxt = a[i - 1], a[i]
            ok = np.isfinite(prev) & np.isfinite(nxt) & (prev > 0) & (nxt != 0)
            jump = (np.abs(nxt[ok]) - prev[ok]) / prev[ok] * 100
            made = nxt[ok] > 0
            good = jump >= 0
            b = np.digitize(jump[good], JUMP_BINS) - 1
            for j, lab in enumerate(JUMP_LABELS):
                m = b == j
                if m.sum() >= 200:
                    js.append({"att": i + 1, "bin": lab, "n": int(m.sum()), "made": _r(100 * made[good][m].mean(), 1),
                               "gain": _r(np.mean(np.where(made[good][m], jump[good][m], 0.0)), 2)})
        out["jumps"][lift] = js
        # third attempts after a made second: the jump, the make rate and the kilos it adds on average
        p2, p3 = a[1], a[2]
        ok = np.isfinite(p2) & np.isfinite(p3) & (p2 > 0) & (p3 != 0)
        kg = np.abs(p3[ok]) - p2[ok]
        made3 = p3[ok] > 0
        tb = [0, 2.5, 5, 7.5, 10, 12.5, 15, 20, 1000]
        tl = ["0-2.5", "2.5-5", "5-7.5", "7.5-10", "10-12.5", "12.5-15", "15-20", "20+"]
        idx = np.digitize(kg, tb) - 1
        th = []
        for j, lab in enumerate(tl):
            m = (idx == j) & (kg >= 0)
            if m.sum() >= 200:
                th.append({"kg": lab, "n": int(m.sum()), "made": _r(100 * made3[m].mean(), 1),
                           "exp": _r(np.mean(np.where(made3[m], kg[m], 0.0)), 2)})
        miss2 = np.isfinite(p2) & np.isfinite(p3) & (p2 < 0) & (p3 != 0)
        same = miss2 & (np.abs(np.abs(p3) - np.abs(p2)) < 0.01)
        out["third"][lift] = {"after_make": th,
                              "after_miss_same": {"n": int(same.sum()), "made": _r(100 * np.mean(p3[same] > 0), 1) if same.any() else None},
                              "after_miss_up": {"n": int((miss2 & ~same).sum()),
                                                "made": _r(100 * np.mean(p3[miss2 & ~same] > 0), 1) if (miss2 & ~same).any() else None}}
    # the whole day: made attempts out of nine, by stream and tested
    made = (e[cols] > 0).sum(axis=1)
    tried = (e[cols].notna() & (e[cols] != 0)).sum(axis=1)
    rate = made / tried.replace(0, np.nan)
    for key in canon.STREAMS:
        sx = "M" if key.startswith("men") else "F"
        eq = canon.STREAMS[key]["eq"]
        m = (e["sex"] == sx) & (e["eq"] == eq)
        if m.sum() < 500:
            continue
        out["by_stream"][key] = {
            "n": int(m.sum()), "made": _r(100 * rate[m].mean(), 1),
            "nine": _r(100 * np.mean(made[m] == 9), 1),
            "tested": _r(100 * rate[m & e["tested"]].mean(), 1) if (m & e["tested"]).sum() > 200 else None,
            "untested": _r(100 * rate[m & ~e["tested"]].mean(), 1) if (m & ~e["tested"]).sum() > 200 else None,
        }
    return out


def bombouts(entries: pd.DataFrame, since: str = MODERN) -> dict:
    """Share of full-power entries with no total (a bomb-out or a withdrawal: OpenPowerlifting's DQ), by lift missed."""
    e = entries[(entries["event"] == "SBD") & (entries["date"] >= since)]
    dq = e["place"].astype(str).eq("DQ")
    out = {"n": int(len(e)), "rate": _r(100 * dq.mean(), 2), "by_stream": {}}
    cols = ["s1", "s2", "s3", "b1", "b2", "b3", "d1", "d2", "d3"]
    if set(cols) <= set(e.columns):
        d = e[dq & (e[cols].notna().sum(axis=1) >= 6)]
        lost = {}
        for _lift, label, k in LIFTS:
            v = d[[f"{k}1", f"{k}2", f"{k}3"]].to_numpy(dtype=float)
            allmiss = np.all(~(v > 0), axis=1) & np.all(np.isfinite(v), axis=1)
            lost[label] = int(allmiss.sum())
        tot = sum(lost.values()) or 1
        out["lift_lost"] = [{"lift": k, "n": v, "share": _r(100 * v / tot, 1)} for k, v in lost.items()]
    for key, meta in canon.STREAMS.items():
        sx = "M" if key.startswith("men") else "F"
        m = (e["sex"] == sx) & (e["eq"] == meta["eq"])
        if m.sum() >= 500:
            out["by_stream"][key] = _r(100 * dq[m].mean(), 2)
    return out


# ── age curves, peak ages ─────────────────────────────────────────────────────────────────────────────────────
def age_curves(walked: pd.DataFrame, entries: pd.DataFrame, since: str = "2005-01-01") -> dict:
    """Within-lifter change per year by age (pairs of a lifter's consecutive scored meets 60-730 days apart), summed
    into a curve from age 16; the peak is where the curve tops out. Cross-sectional means are shown for reference
    (they are biased: the lifters who stay in the sport are the good ones)."""
    w = walked[(walked["date"] >= since) & walked["scored"] & walked["age"].notna()][
        ["stream", "pid", "date", "dots", "age", "meet_id", "bw", "sex"]].copy()
    lifts = entries[["meet_id", "pid", "squat", "bench", "dead"]].drop_duplicates(["meet_id", "pid"])
    w = w.merge(lifts, on=["meet_id", "pid"], how="left")
    k = np.array([canon.dots_coeff(s, b) for s, b in zip(w["sex"], w["bw"])])
    for c in ("squat", "bench", "dead"):
        w[c + "_pts"] = w[c].to_numpy(dtype=float) * k
    w = w.sort_values(["stream", "pid", "date"])
    g = w.groupby(["stream", "pid"])
    prev = g.shift(1)
    days = (w["date"] - prev["date"]).dt.days
    ok = (days >= 60) & (days <= 730) & prev["age"].notna()
    yrs = days[ok] / 365.25
    mid = ((w["age"] + prev["age"]) / 2)[ok].round()
    out = {}
    for key in canon.STREAMS:
        m = (w.loc[ok, "stream"] == key)
        if m.sum() < 2000:
            continue
        rec = {"ages": [], "total": [], "cross": [], "n": []}
        curves = {}
        for col in ("dots", "squat_pts", "bench_pts", "dead_pts"):
            rate = ((w[col] - prev[col])[ok] / yrs)[m]
            df = pd.DataFrame({"a": mid[m], "r": rate}).dropna()
            df = df[(df["a"] >= 14) & (df["a"] <= 75)]
            # trimmed mean per age: a few huge jumps (a first meet in a new suit) should not steer a curve
            agg = df.groupby("a")["r"].agg(lambda s: s.clip(s.quantile(0.05), s.quantile(0.95)).mean() if len(s) >= 80 else np.nan)
            curves[col] = agg
        ages = [a for a in range(16, 71) if a in curves["dots"].index and np.isfinite(curves["dots"].get(a, np.nan))]
        if len(ages) < 10:
            continue
        base = w[(w["stream"] == key)]
        cross = base.assign(a=base["age"].round()).groupby("a")["dots"].mean()
        cnt = base.assign(a=base["age"].round()).groupby("a").size()
        for col in curves:
            run, cum = 0.0, []
            for a in ages:
                v = curves[col].get(a, np.nan)
                run += v if np.isfinite(v) else 0.0
                cum.append(round(run, 1))
            curves[col] = cum
        peaks = {}
        for col, lab in (("dots", "total"), ("squat_pts", "squat"), ("bench_pts", "bench"), ("dead_pts", "dead")):
            arr = np.array(curves[col])
            peaks[lab] = int(ages[int(np.argmax(arr))])
        rec = {"ages": ages, "total": curves["dots"], "squat": curves["squat_pts"], "bench": curves["bench_pts"],
               "dead": curves["dead_pts"], "cross": [_r(cross.get(a), 1) for a in ages],
               "n": [int(cnt.get(a, 0)) for a in ages], "peak": peaks}
        out[key] = rec
    return out


# ── weight-class moves ────────────────────────────────────────────────────────────────────────────────────────
def class_moves(walked: pd.DataFrame, entries: pd.DataFrame, since: str = MODERN) -> dict:
    """Consecutive scored meets 60-400 days apart: lifters who moved up a class, down a class, or stayed, and what
    happened to their total (kg) and to their DOTS."""
    w = walked[(walked["date"] >= since) & walked["scored"]][["stream", "pid", "date", "dots", "total", "bw", "sex"]].copy()
    w["cls"] = ipf_class_vec(w["sex"], w["bw"])
    w = w.sort_values(["stream", "pid", "date"])
    prev = w.groupby(["stream", "pid"]).shift(1)
    days = (w["date"] - prev["date"]).dt.days
    ok = (days >= 60) & (days <= 400) & prev["cls"].notna() & w["cls"].notna()
    out = {}
    for sx, key in (("M", "men_raw"), ("F", "women_raw"), ("M", "men_eq"), ("F", "women_eq")):
        order = class_order(sx)
        pos = {c: i for i, c in enumerate(order)}
        m = ok & (w["stream"] == key)
        if m.sum() < 2000:
            continue
        a = prev.loc[m, "cls"].map(pos)
        b = w.loc[m, "cls"].map(pos)
        step = (b - a)
        rows = []
        for lab, sel in (("Moved down a class", step == -1), ("Stayed in the class", step == 0), ("Moved up a class", step == 1)):
            idx = sel[sel].index
            if len(idx) < 100:
                continue
            dkg = (w.loc[idx, "total"] - prev.loc[idx, "total"])
            dpt = (w.loc[idx, "dots"] - prev.loc[idx, "dots"])
            dbw = (w.loc[idx, "bw"] - prev.loc[idx, "bw"])
            rows.append({"move": lab, "n": int(len(idx)), "bw": _r(dbw.mean(), 1), "kg": _r(dkg.mean(), 1),
                         "dots": _r(dpt.mean(), 1), "better": _r(100 * (dpt > 0).mean(), 1)})
        out[key] = rows
    return out


# ── federations ───────────────────────────────────────────────────────────────────────────────────────────────
def federations(walked: pd.DataFrame, entries: pd.DataFrame, since: str = "2015-01-01", min_starts: int = 400) -> dict:
    """Federation strength, two ways: the field (how strong its lifters are) and a within-lifter effect (how much the
    same lifter totals there, in DOTS, against the all-federation average: a lifter fixed effect taken out by
    alternating means). Raw full power only, so equipment does not decide it."""
    meta = entries[["meet_id", "fed", "parent"]].drop_duplicates("meet_id")
    out = {}
    for key in ("men_raw", "women_raw"):
        w = walked[(walked["stream"] == key) & (walked["date"] >= since) & walked["scored"]][["pid", "meet_id", "dots", "tested"]]
        w = w.merge(meta, on="meet_id", how="left")
        cnt = w["fed"].value_counts()
        feds = cnt[cnt >= min_starts].index
        w = w[w["fed"].isin(feds)].copy()
        if w.empty:
            continue
        # alternating means: dots = lifter + fed (+ noise); 12 sweeps settle it
        fe = pd.Series(0.0, index=feds)
        for _ in range(12):
            li = (w["dots"] - w["fed"].map(fe)).groupby(w["pid"]).mean()
            res = w["dots"] - w["pid"].map(li)
            multi = w["pid"].map(w.groupby("pid")["fed"].nunique()) > 1
            fe_new = res[multi].groupby(w.loc[multi, "fed"]).mean()
            fe = fe_new.reindex(feds).fillna(0.0)
            fe = fe - np.average(fe, weights=cnt.reindex(feds))
        multi_n = w[w["pid"].map(w.groupby("pid")["fed"].nunique()) > 1].groupby("fed")["pid"].nunique()
        rows = []
        for f in feds:
            d = w[w["fed"] == f]
            top = d.groupby("pid")["dots"].max().sort_values(ascending=False)
            rows.append({"fed": f, "parent": str(d["parent"].dropna().iloc[0]) if d["parent"].notna().any() else "",
                         "starts": int(len(d)), "lifters": int(d["pid"].nunique()),
                         "median": _r(d["dots"].median(), 1), "top50": _r(top.head(50).mean(), 1),
                         "tested": _r(100 * d["tested"].mean(), 0), "effect": _r(fe.get(f), 1),
                         "shared": int(multi_n.get(f, 0))})
        rows.sort(key=lambda r: -(r["top50"] or 0))
        out[key] = rows[:40]
    return out


def tested_split(walked: pd.DataFrame, since: str = "2015-01-01") -> dict:
    """Tested against untested: the median and the top-100 mean of each lifter's best DOTS since `since`."""
    out = {}
    w = walked[(walked["date"] >= since) & walked["scored"]]
    for key in canon.STREAMS:
        d = w[w["stream"] == key]
        if len(d) < 1000:
            continue
        rec = {}
        for lab, m in (("tested", d["tested"]), ("untested", ~d["tested"])):
            best = d[m].groupby("pid")["dots"].max().sort_values(ascending=False)
            if len(best) < 100:
                continue
            rec[lab] = {"lifters": int(len(best)), "median": _r(best.median(), 1), "top100": _r(best.head(100).mean(), 1)}
        out[key] = rec
    return out


# ── the points formulas across bodyweight ─────────────────────────────────────────────────────────────────────
def formulas(entries: pd.DataFrame, since: str = "2018-01-01", top: int = 20) -> dict:
    """The mean points of each class's top 20 raw lifters (each lifter's best), under DOTS, Wilks and IPF GL. A fair
    formula gives flat lines: the best of every class score the same."""
    e = entries[(entries["event"] == "SBD") & (entries["eq"] == "raw") & (entries["date"] >= since) & entries["total"].notna()]
    e = e.assign(cls=ipf_class_vec(e["sex"], e["bw"]))
    out = {}
    for sx in ("M", "F"):
        rows = []
        for c in class_order(sx):
            d = e[(e["sex"] == sx) & (e["cls"] == c)]
            if d.empty:
                continue
            rec = {"cls": c}
            for col in ("dots", "wilks", "gl"):
                if col not in d.columns:
                    continue
                best = d.groupby("pid")[col].max().sort_values(ascending=False).head(top)
                rec[col] = _r(best.mean(), 1)
            rows.append(rec)
        out["men" if sx == "M" else "women"] = rows
    return out


# ── lift ratios ───────────────────────────────────────────────────────────────────────────────────────────────
def ratios(walked: pd.DataFrame, entries: pd.DataFrame, since: str = "2018-01-01") -> dict:
    """Squat, bench and deadlift as shares of the total, by class (raw): the median and the middle half."""
    lifts = entries[["meet_id", "pid", "squat", "bench", "dead"]].drop_duplicates(["meet_id", "pid"])
    out = {}
    for key, sx in (("men_raw", "M"), ("women_raw", "F")):
        w = walked[(walked["stream"] == key) & (walked["date"] >= since) & walked["scored"]][["pid", "meet_id", "total", "bw", "sex"]]
        w = w.merge(lifts, on=["meet_id", "pid"], how="left")
        w = w[(w["squat"] > 0) & (w["bench"] > 0) & (w["dead"] > 0)]
        w = w.assign(cls=ipf_class_vec(w["sex"], w["bw"]))
        rows = []
        for c in class_order(sx):
            d = w[w["cls"] == c]
            if len(d) < 300:
                continue
            rec = {"cls": c, "n": int(len(d))}
            for col in ("squat", "bench", "dead"):
                sh = 100 * d[col] / d["total"]
                rec[col] = [_r(sh.quantile(0.25), 1), _r(sh.median(), 1), _r(sh.quantile(0.75), 1)]
                rec[col + "_bw"] = _r((d[col] / d["bw"]).median(), 2)
            rows.append(rec)
        out[key] = rows
    return out


# ── records ───────────────────────────────────────────────────────────────────────────────────────────────────
REC_EQ = {"Raw": "Raw", "Wraps": "Wraps", "Single-ply": "Single-ply", "Multi-ply": "Multi-ply"}


def records(entries: pd.DataFrame, names: dict, max_steps: int = 30) -> dict:
    """All-time bests per sex, equipment (Raw, Wraps, Single-ply, Multi-ply) and IPF class (by the bodyweight on the
    day), for squat, bench, deadlift (from full-power meets) and total, with every time the record moved."""
    e = entries[(entries["event"] == "SBD") & entries["total"].notna() & entries["bw"].notna() &
                entries["equipment"].isin(REC_EQ)][["pid", "name", "sex", "equipment", "bw", "squat", "bench", "dead",
                                                    "total", "date", "meet_id", "fed", "tested", "dots"]]
    e = e[e["sex"].isin(("M", "F"))].rename(columns={"name": "lname"}).assign(cls=lambda d: ipf_class_vec(d["sex"], d["bw"]))
    out = {}
    for (sx, eq), d in e.groupby(["sex", "equipment"]):
        key = ("men" if sx == "M" else "women") + "_" + eq.lower().replace("-", "")
        classes = []
        for c in class_order(sx):
            dc = d[d["cls"] == c].sort_values("date")
            if len(dc) < 50:
                continue
            rec = {"cls": c, "lifts": {}}
            for col in ("squat", "bench", "dead", "total"):
                v = dc[col].to_numpy(dtype=float)
                ok = np.isfinite(v) & (v > 0)
                if not ok.any():
                    continue
                sub = dc[ok]
                vv = v[ok]
                runmax = np.maximum.accumulate(vv)
                prevmax = np.concatenate([[-1.0], runmax[:-1]])
                brk = vv > prevmax
                steps = sub[brk]
                hist = [{"date": str(r.date)[:10], "kg": _r(r_v, 1), "pid": r.pid, "name": str(r.lname), "fed": str(r.fed)}
                        for r, r_v in zip(steps.itertuples(index=False), vv[brk])]
                best = hist[-1]
                rec["lifts"][col] = {"kg": best["kg"], "pid": best["pid"], "name": best["name"], "date": best["date"],
                                     "fed": best["fed"], "steps": hist[-max_steps:], "n_steps": len(hist)}
            classes.append(rec)
        out[key] = {"label": ("Men" if sx == "M" else "Women") + " · " + eq, "classes": classes}
    return out


def all_time(walked: pd.DataFrame, names: dict, meet_name: dict, n: int = 50) -> dict:
    """The best DOTS ever per stream (each lifter's best performance) and the best of each decade."""
    out = {}
    w = walked[walked["scored"]]
    for key in canon.STREAMS:
        d = w[w["stream"] == key]
        if d.empty:
            continue
        i = d.groupby("pid")["dots"].idxmax()
        best = d.loc[i].sort_values("dots", ascending=False)
        rows = [{"pid": r.pid, "name": (names.get(r.pid) or {}).get("name", r.pid), "cc": (names.get(r.pid) or {}).get("country", ""),
                 "dots": _r(r.dots, 1), "total": _r(r.total, 1), "bw": _r(r.bw, 1), "date": str(r.date)[:10],
                 "meet": r.meet_id, "meet_name": str(meet_name.get(r.meet_id, ""))} for r in best.head(n).itertuples(index=False)]
        dec = {}
        dd = d.assign(dec=(d["date"].dt.year // 10 * 10))
        for decade, g in dd.groupby("dec"):
            if decade < 1970:
                continue
            j = g.groupby("pid")["dots"].idxmax()
            top = g.loc[j].sort_values("dots", ascending=False).head(10)
            dec[str(int(decade))] = [{"pid": r.pid, "name": (names.get(r.pid) or {}).get("name", r.pid),
                                      "dots": _r(r.dots, 1), "date": str(r.date)[:10]} for r in top.itertuples(index=False)]
        out[key] = {"top": rows, "decades": dec}
    return out


# ── the lifter profile (the Scouting Room, the lifter page's percentiles) ─────────────────────────────────────
# id, label, short, family, dir ('higher' | 'lower' | 'style'), unit, tip
METRICS = [
    ("rt", "Our rating", "Rating", "rating", "higher", "DOTS", "The DOTS we expect at the lifter's next meet (our forecast, as of today)."),
    ("dots", "Best DOTS", "DOTS", "points", "higher", "DOTS", "The best DOTS score in the window: total adjusted for bodyweight (Konertz 2019)."),
    ("gl", "Best IPF GL", "GL", "points", "higher", "GL", "The best IPF GL (Goodlift) points in the window, the IPF's own bodyweight formula."),
    ("wilks", "Best Wilks", "Wilks", "points", "higher", "Wilks", "The best Wilks score in the window (the older bodyweight formula, still used by some federations)."),
    ("total", "Best total", "Total", "lifts", "higher", "kg", "The heaviest full-power total in the window."),
    ("squat", "Best squat", "Squat", "lifts", "higher", "kg", "The heaviest squat in a full-power meet in the window."),
    ("bench", "Best bench", "Bench", "lifts", "higher", "kg", "The heaviest bench press in a full-power meet in the window."),
    ("dead", "Best deadlift", "Dead", "lifts", "higher", "kg", "The heaviest deadlift in a full-power meet in the window."),
    ("rel", "Total per kg of bodyweight", "Total/BW", "relative", "higher", "x BW", "Best total divided by bodyweight on the day."),
    ("rel_s", "Squat per kg of bodyweight", "Squat/BW", "relative", "higher", "x BW", "Squat at the best-total meet divided by bodyweight."),
    ("rel_b", "Bench per kg of bodyweight", "Bench/BW", "relative", "higher", "x BW", "Bench at the best-total meet divided by bodyweight."),
    ("rel_d", "Deadlift per kg of bodyweight", "Dead/BW", "relative", "higher", "x BW", "Deadlift at the best-total meet divided by bodyweight."),
    ("sh_s", "Squat share of total", "Squat %", "shape", "style", "%", "The squat as a share of the best total: a style, not better or worse."),
    ("sh_b", "Bench share of total", "Bench %", "shape", "style", "%", "The bench as a share of the best total: a style."),
    ("sh_d", "Deadlift share of total", "Dead %", "shape", "style", "%", "The deadlift as a share of the best total: a style."),
    ("make", "Attempts made", "Made", "attempts", "higher", "%", "Share of attempts made, all three lifts, shrunk toward the stream average (as if nine more attempts at the average)."),
    ("make_s", "Squats made", "Sq made", "attempts", "higher", "%", "Share of squat attempts made (shrunk)."),
    ("make_b", "Benches made", "Bp made", "attempts", "higher", "%", "Share of bench attempts made (shrunk)."),
    ("make_d", "Deadlifts made", "Dl made", "attempts", "higher", "%", "Share of deadlift attempts made (shrunk)."),
    ("third", "Third attempts made", "3rd made", "attempts", "higher", "%", "Share of third attempts made (shrunk toward the average with six attempts)."),
    ("jump3", "Third-attempt jump", "3rd jump", "attempts", "style", "%", "The average jump from a made second attempt to the third, as a share of the second: bold or careful, a style."),
    ("beat", "Beat our forecast", "Beat", "meet day", "higher", "%", "Share of meets above our pre-meet expectation (shrunk toward half with four meets)."),
    ("value", "Meet value", "Value", "meet day", "higher", "DOTS", "Average DOTS above our pre-meet expectation per meet (shrunk toward zero with three meets)."),
    ("cons", "Meet-to-meet spread", "Spread", "meet day", "lower", "DOTS", "How far each meet lands from the lifter's own trend line, in DOTS (shrunk). Lower is steadier."),
    ("bomb", "Bomb-out rate", "Bombs", "meet day", "lower", "%", "Share of full-power meets without a total (shrunk toward the stream rate with five meets)."),
    ("prog", "Progress per year", "Progress", "progress", "higher", "DOTS/yr", "The trend in DOTS per year over the window (shrunk toward zero for a short span)."),
    ("meets", "Meets", "Meets", "progress", "higher", "", "Scored full-power meets in the window."),
]
METRIC_IDS = [m[0] for m in METRICS]


def _shrink(num, den, prior, k):
    return (num + prior * k) / (den + k)


def profile(walked: pd.DataFrame, entries: pd.DataFrame, start, end, min_meets: int = 2) -> pd.DataFrame:
    """Per (stream, pid) metrics over meets dated in (start, end]: best lifts and points, ratios, attempts, meet day
    against our forecast (walked must carry `exp`), steadiness, bomb-outs and progress. Lifters with fewer than
    `min_meets` scored meets in the window are left out. Percentiles come from percentiles()."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    w = walked[(walked["date"] > start) & (walked["date"] <= end)]
    cnt = w.groupby(["stream", "pid"])["dots"].transform("size")
    w = w[cnt >= min_meets]
    if w.empty:
        return pd.DataFrame()
    dts = pd.to_datetime(entries["date"])
    e = entries[(entries["event"] == "SBD") & (dts > start) & (dts <= end)]
    att_cols = ["s1", "s2", "s3", "b1", "b2", "b3", "d1", "d2", "d3"]
    x = w.merge(e[["meet_id", "pid", "squat", "bench", "dead", "gl", "wilks"] + [c for c in att_cols if c in e.columns]]
                .drop_duplicates(["meet_id", "pid"]), on=["meet_id", "pid"], how="left").reset_index(drop=True)
    g = x.groupby(["stream", "pid"])
    out = pd.DataFrame({
        "dots": g["dots"].max(), "total": g["total"].max(), "squat": g["squat"].max(), "bench": g["bench"].max(),
        "dead": g["dead"].max(), "gl": g["gl"].max(), "wilks": g["wilks"].max(), "meets": g.size(),
        "bw": g["bw"].last(), "sex": g["sex"].last(), "tested": g["tested"].mean(), "age": g["age"].last(),
        "last": g["date"].max(), "first": g["date"].min(),
    })
    bi = x.loc[g["total"].idxmax()].set_index(["stream", "pid"])
    for c, k in (("rel", "total"), ("rel_s", "squat"), ("rel_b", "bench"), ("rel_d", "dead")):
        out[c] = (bi[k] / bi["bw"]).reindex(out.index)
    ok = (bi["squat"] > 0) & (bi["bench"] > 0) & (bi["dead"] > 0)
    for c, k in (("sh_s", "squat"), ("sh_b", "bench"), ("sh_d", "dead")):
        out[c] = (100 * bi[k] / bi["total"]).where(ok).reindex(out.index)
    if set(att_cols) <= set(x.columns):
        A = x[att_cols].to_numpy(dtype=float)
        tried = np.isfinite(A) & (A != 0)
        made = A > 0
        per = {}
        for nm, sl in (("make", slice(0, 9)), ("make_s", slice(0, 3)), ("make_b", slice(3, 6)), ("make_d", slice(6, 9))):
            per[nm + "_m"] = made[:, sl].sum(axis=1)
            per[nm + "_t"] = tried[:, sl].sum(axis=1)
        th = np.zeros(len(x)); tt = np.zeros(len(x)); jsum = np.zeros(len(x)); jn = np.zeros(len(x))
        for i in (2, 5, 8):
            t3 = tried[:, i]
            th += made[:, i] & t3
            tt += t3
            ok2 = (A[:, i - 1] > 0) & t3
            den = np.where(ok2, A[:, i - 1], 1.0)
            j = np.where(ok2, (np.abs(np.nan_to_num(A[:, i])) - np.nan_to_num(A[:, i - 1])) / den * 100, 0.0)
            jsum += j; jn += ok2
        per.update({"third_m": th, "third_t": tt, "jump_s": jsum, "jump_n": jn})
        P = pd.DataFrame(per)
        P["stream"], P["pid"] = x["stream"].to_numpy(), x["pid"].to_numpy()
        S = P.groupby(["stream", "pid"]).sum()
        for nm in ("make", "make_s", "make_b", "make_d", "third"):
            m_all, t_all = S[nm + "_m"], S[nm + "_t"]
            prior = m_all.groupby(level=0).sum() / t_all.groupby(level=0).sum().replace(0, np.nan)
            pr = prior.reindex(S.index.get_level_values(0)).to_numpy()
            k = 6.0 if nm == "third" else 9.0
            v = 100 * _shrink(m_all.to_numpy(), t_all.to_numpy(), pr, k)
            out[nm] = pd.Series(np.where(t_all.to_numpy() > 0, v, np.nan), index=S.index).reindex(out.index)
        out["jump3"] = (S["jump_s"] / S["jump_n"].replace(0, np.nan)).reindex(out.index)
    if "exp" in x.columns:
        has = x["exp"].notna()
        r = (x["dots"] - x["exp"]).where(has)
        R = pd.DataFrame({"r": r.fillna(0.0), "b": ((r > 0) & has).astype(float), "h": has.astype(float),
                          "stream": x["stream"], "pid": x["pid"]})
        G = R.groupby(["stream", "pid"])
        nh = G["h"].sum()
        out["beat"] = (100 * _shrink(G["b"].sum(), nh, 0.5, 4.0)).where(nh > 0).reindex(out.index)
        out["value"] = (G["r"].sum() / (nh + 3.0)).where(nh > 0).reindex(out.index)
    t = (x["date"] - start).dt.days / 365.25
    keys = [x["stream"], x["pid"]]
    mt = t.groupby(keys).transform("mean")
    md = x["dots"].groupby(keys).transform("mean")
    cov = ((t - mt) * (x["dots"] - md)).groupby(keys).sum()
    var = ((t - mt) ** 2).groupby(keys).sum()
    slope = cov / var.replace(0, np.nan)
    n = x.groupby(keys).size()
    out["prog"] = (slope * var / (var + 1.0)).reindex(out.index)
    sl_row = slope.reindex(pd.MultiIndex.from_arrays(keys)).fillna(0.0).to_numpy()
    res2 = ((x["dots"] - (md + sl_row * (t - mt))) ** 2).groupby(keys).sum()
    out["cons"] = np.sqrt((res2 + 3 * 15.0 ** 2) / ((n - 1).clip(lower=0) + 3)).reindex(out.index)
    ee = e[e["sex"].isin(("M", "F")) & e["eq"].isin(("raw", "wraps", "equipped"))]
    ee = ee.assign(dq=ee["place"].astype(str).eq("DQ") | ee["total"].isna(),
                   stream=np.where(ee["sex"] == "M", "men_", "women_") + ee["eq"].map({"raw": "raw", "wraps": "wraps", "equipped": "eq"}))
    ee = ee.drop_duplicates(["meet_id", "pid", "stream"])
    B = ee.groupby(["stream", "pid"])["dq"].agg(["sum", "size"])
    prior = ee.groupby("stream")["dq"].mean()
    pr = prior.reindex(B.index.get_level_values(0)).to_numpy()
    out["bomb"] = pd.Series(100 * _shrink(B["sum"].to_numpy(), B["size"].to_numpy(), pr, 5.0), index=B.index).reindex(out.index)
    out["cls"] = ipf_class_vec(out["sex"], out["bw"])
    return out.reset_index()


def percentiles(df: pd.DataFrame, ids=None, by=("stream", "cls")) -> pd.DataFrame:
    """Percentile (0-100) of each metric within the peer group `by` (10 or more with a value); lower-is-better
    metrics turned so higher is better; style metrics are plain positions in the class, not grades."""
    ids = ids or METRIC_IDS
    dirs = {m[0]: m[4] for m in METRICS}
    out = pd.DataFrame(index=df.index)
    grp = df.groupby(list(by))
    for k in ids:
        if k not in df.columns:
            continue
        p = grp[k].rank(pct=True, method="average") * 100
        n = grp[k].transform("count")
        p = p.where(n >= 10)
        out[k] = (100 - p + 100 / n) if dirs.get(k) == "lower" else p
    return out.clip(0, 100)


def reliability(walked: pd.DataFrame, entries: pd.DataFrame, years=(2022, 2023, 2024)) -> dict:
    """How much each profile metric is a trait and how much it predicts: for consecutive calendar years (t, t+1), the
    same lifters (two or more meets in each, same stream), the year-to-year correlation of the metric (yoy_r: a
    trait repeats) and its correlation with the next year's best DOTS (pred_r), pooled over the year pairs."""
    acc: dict = {}
    for y in years:
        a = profile(walked, entries, pd.Timestamp(f"{y - 1}-12-31"), pd.Timestamp(f"{y}-12-31"))
        b = profile(walked, entries, pd.Timestamp(f"{y}-12-31"), pd.Timestamp(f"{y + 1}-12-31"))
        if a.empty or b.empty:
            continue
        m = a.merge(b, on=["stream", "pid"], suffixes=("", "_n"))
        for k in METRIC_IDS:
            if k not in m.columns or k == "rt":
                continue
            d = pd.DataFrame({"a": m[k], "b": m[k + "_n"], "t": m["dots_n"]}).dropna()
            acc.setdefault(k, []).append(d)
    out = {}
    for k, parts in acc.items():
        d = pd.concat(parts)
        if len(d) < 200:
            continue
        out[k] = {"n": int(len(d)), "yoy_r": round(float(d["a"].corr(d["b"], method="spearman")), 3),
                  "pred_r": round(float(d["a"].corr(d["t"], method="spearman")), 3)}
    return out
