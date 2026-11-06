"""
The Quant Green's player, course and lab analytics (6 Nov 2026), from the walked rounds (models/ratings.py), the
season stores (store.py) and ESPN's season statistics. Nothing here feeds the forecasts: these are descriptions,
and every rate is shrunk toward the peer average so a handful of rounds cannot top a list.

Per player, over a window (the last WINDOW_DAYS, or one calendar season):
  scoring     strokes gained per round against an average field (sg), in rounds 1-2 and at the weekend, on the
              front and back nine (each nine against the field's par for it), round-to-round spread, the share of
              great (+3 or better) and poor (-3 or worse) rounds, form (the last 8 events)
  holes       (tours with hole-by-hole scores: PGA Tour and Korn Ferry) strokes gained per hole on par 3s, 4s and 5s
              against the field on the same hole and round, birdie-or-better, bogey-or-worse and double-or-worse
              rates, the eagle rate on par 5s
  striking    (PGA Tour, 2017 on) driving distance and accuracy, greens in regulation, putts per green hit, sand
              saves; and the strokes-gained approximation by category (fit_categories)
  outcomes    win, top-10 and made-cut rates, shrunk toward the peer rate
Courses (single-course events): difficulty against par, length, what the course rewards (the correlation of the
field's strokes gained there with each striking stat) and the courses most like it.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from . import canon, store

WINDOW_DAYS = 730
Q_ROUNDS = 30              # rounds in the window before a player gets percentiles
K_ROUNDS = 12              # shrinkage, rounds of the peer average
K_HOLES = 72               # holes of the peer average
K_EVENTS = 10              # events of the peer rate
K_COURSE = 32              # rounds at a course (models: course history failed the promotion test; display only)
GREAT, POOR = 3.0, -3.0

# id: (label, short, family, dir, unit)
METRICS = {
    "rt": ("Our rating", "Rating", "value", "higher", "strokes per round v an average field"),
    "sg": ("Strokes gained per round", "SG/rd", "value", "higher", "strokes per round v an average field"),
    "form": ("Form: strokes gained, last 8 events", "Form", "value", "higher", "strokes per round"),
    "sg_e": ("Strokes gained, rounds 1 and 2", "R1-2", "scoring", "higher", "strokes per round"),
    "sg_w": ("Strokes gained at the weekend", "Wknd", "scoring", "higher", "strokes per round"),
    "sg_f": ("Strokes gained, front nine", "Front", "scoring", "higher", "strokes per nine"),
    "sg_b": ("Strokes gained, back nine", "Back", "scoring", "higher", "strokes per nine"),
    "sd": ("Round-to-round spread", "Spread", "scoring", "lower", "strokes (one standard deviation)"),
    "great": ("Great rounds (+3 or better)", "Great", "scoring", "higher", "share of rounds"),
    "poor": ("Poor rounds (-3 or worse)", "Poor", "scoring", "lower", "share of rounds"),
    "h3": ("Par 3s: strokes gained per hole", "Par 3", "holes", "higher", "strokes per hole"),
    "h4": ("Par 4s: strokes gained per hole", "Par 4", "holes", "higher", "strokes per hole"),
    "h5": ("Par 5s: strokes gained per hole", "Par 5", "holes", "higher", "strokes per hole"),
    "bird": ("Birdie-or-better rate", "Bird%", "holes", "higher", "share of holes"),
    "bog": ("Bogey-or-worse rate", "Bog%", "holes", "lower", "share of holes"),
    "dbl": ("Double-bogey-or-worse rate", "Dbl%", "holes", "lower", "share of holes"),
    "eag": ("Eagle rate on par 5s", "Eagle%", "holes", "higher", "share of par 5s"),
    "dist": ("Driving distance", "Dist", "striking", "higher", "yards"),
    "acc": ("Driving accuracy", "Acc%", "striking", "higher", "share of fairways"),
    "gir": ("Greens in regulation", "GIR%", "striking", "higher", "share of greens"),
    "ppg": ("Putts per green hit", "Putts/GIR", "striking", "lower", "putts"),
    "sand": ("Sand saves", "Sand%", "striking", "higher", "share of bunkers"),
    "c_ott": ("Off the tee (estimate)", "OTT", "categories", "higher", "strokes per round"),
    "c_app": ("Approach (estimate)", "APP", "categories", "higher", "strokes per round"),
    "c_arg": ("Around the green (estimate)", "ARG", "categories", "higher", "strokes per round"),
    "c_putt": ("Putting (estimate)", "PUTT", "categories", "higher", "strokes per round"),
    "win": ("Win rate", "Win%", "outcomes", "higher", "share of starts"),
    "t10": ("Top-10 rate", "Top10%", "outcomes", "higher", "share of starts"),
    "cut": ("Made-cut rate", "Cut%", "outcomes", "higher", "share of starts with a cut"),
}
PCT = {"great", "poor", "bird", "bog", "dbl", "eag", "acc", "gir", "sand", "win", "t10", "cut"}   # stored as 0-1
TIPS = {
    "rt": "Our rating: the decayed, shrunk average of a player's strokes gained, the number the forecasts use.",
    "sg": "Strokes gained per round against an average field over the window, shrunk toward the peer average.",
    "form": "Strokes gained per round over the player's last eight events: who is playing well now.",
    "sg_e": "Rounds 1 and 2: before the cut, in a full field.",
    "sg_w": "Rounds 3 and 4: after the cut, usually in contention or chasing.",
    "sg_f": "The front nine against the field's average front nine that day (strength-adjusted, like every number here).",
    "sg_b": "The back nine, the same way. Front plus back is the round.",
    "sd": "One standard deviation of the player's strokes gained from round to round, after their own average: lower is steadier.",
    "great": "Share of rounds three or more strokes better than an average field would have shot.",
    "poor": "Share of rounds three or more strokes worse.",
    "h3": "On par 3s, strokes better than the field on the same hole that day, per hole (hole-by-hole tours only).",
    "h4": "On par 4s, the same way.",
    "h5": "On par 5s, the same way: where length pays.",
    "bird": "Share of holes played in birdie or better.",
    "bog": "Share of holes played in bogey or worse: lower is better.",
    "dbl": "Share of holes played in double bogey or worse: the big numbers.",
    "eag": "Share of par 5s played in eagle or better.",
    "dist": "Average measured drive (ESPN season statistics, PGA Tour, 2017 on).",
    "acc": "Share of fairways hit from the tee.",
    "gir": "Share of greens reached in regulation (par minus two strokes).",
    "ppg": "Putts per green reached in regulation: lower is better.",
    "sand": "Share of greenside bunker shots followed by one putt or holed out.",
    "c_ott": "Our estimate from driving distance and accuracy, in strokes per round against the tour average. Not ShotLink strokes gained: a regression of our round-by-round strokes gained on season statistics.",
    "c_app": "Our estimate from greens in regulation, the same way.",
    "c_arg": "Our estimate from sand saves, the same way.",
    "c_putt": "Our estimate from putts per green hit, the same way.",
    "win": "Wins per start, shrunk toward the peer rate (ten starts of weight).",
    "t10": "Top-10 finishes (ties included) per start, shrunk the same way.",
    "cut": "Cuts made per start in events with a cut, shrunk the same way.",
}


def _r(x, k=3):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, k) if np.isfinite(v) else None


# ── loading ──────────────────────────────────────────────────────────────────

def event_meta(tours) -> pd.DataFrame:
    rows = []
    for t in tours:
        for s in store.seasons(t):
            for k, e in store.load_events(t, s).items():
                cs = e.get("courses") or []
                host = next((c for c in cs if c.get("host")), cs[0] if cs else None) or {}
                par, yards = host.get("par"), host.get("yards")
                rows.append({"event": k, "tour": t, "season": s, "name": e.get("name"), "start": e.get("start"),
                             "status": e.get("status"), "major": bool(e.get("major")), "team": bool(e.get("team")),
                             "cut_round": e.get("cut_round") or 0, "single": len(cs) == 1,
                             "course": str(host.get("id") or "") or None, "course_name": host.get("name"),
                             # older leaderboards carry par 0 and yards 0: unknown, not zero
                             "par": par if (par or 0) >= 60 else None, "yards": yards if (yards or 0) >= 4000 else None,
                             "tid": e.get("tournament_id"),
                             "holes_n": len(host.get("holes") or [])})
    df = pd.DataFrame(rows)
    if len(df):
        df["start"] = pd.to_datetime(df["start"])
    return df


def round_extras(tours) -> pd.DataFrame:
    parts = []
    for t in tours:
        for s in store.seasons(t):
            r = store.load_table(t, s, "rounds")
            if len(r):
                parts.append(r[[c for c in ("event", "pid", "round", "out", "in", "tee_time", "holes") if c in r.columns]])
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["event", "pid", "round", "out", "in", "tee_time", "holes"])


def results_frame(tours, meta: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for t in tours:
        for s in store.seasons(t):
            r = store.load_table(t, s, "results")
            if len(r):
                parts.append(r[["event", "pid", "pos", "status"]])
    if not parts:
        return pd.DataFrame(columns=["event", "pid", "pos", "status", "start", "cut_round", "major", "tour"])
    df = pd.concat(parts, ignore_index=True)
    df = df[df["status"].isin(["finish", "cut", "wd", "dq", "mdf"])]
    m = meta[(meta["status"] == "final") & ~meta["team"]][["event", "start", "cut_round", "major", "tour", "season"]]
    return df.merge(m, on="event", how="inner")


def holes_frame(tours, meta: pd.DataFrame, since: pd.Timestamp | None = None) -> pd.DataFrame:
    """Every hole of single-course final events with the field's average on that hole and round: d = field - strokes."""
    ok = meta[meta["single"] & (meta["status"] == "final") & ~meta["team"]]
    if since is not None:
        ok = ok[ok["start"] >= since]
    keep = set(ok["event"])
    parts = []
    for t in tours:
        if not canon.TOURS[t].get("holes"):
            continue
        for s in store.seasons(t):
            if since is not None and s < since.year:
                continue
            h = store.load_table(t, s, "holes")
            if not len(h):
                continue
            h = h[h["event"].isin(keep) & h["par"].notna()]
            parts.append(h[["event", "pid", "round", "hole", "strokes", "par"]])
    if not parts:
        return pd.DataFrame(columns=["event", "pid", "round", "hole", "strokes", "par", "d", "rel", "start"])
    h = pd.concat(parts, ignore_index=True)
    h["strokes"] = h["strokes"].astype(float)
    h["par"] = h["par"].astype(int)
    fm = h.groupby(["event", "round", "hole"])["strokes"].transform("mean")
    cnt = h.groupby(["event", "round", "hole"])["strokes"].transform("size")
    h = h[cnt >= 20].copy()
    h["d"] = (fm[cnt >= 20] - h["strokes"]).astype("float32")
    h["rel"] = (h["strokes"] - h["par"]).astype("int8")
    h = h.merge(ok[["event", "start"]], on="event")
    return h


def stats_frame(tours=canon.STATS_TOURS) -> pd.DataFrame:
    rows = []
    for t in tours:
        for s in range(canon.STATS_FROM, date.today().year + 1):
            for pid, x in store.load_stats(t, s).items():
                if not x or not x.get("rounds"):
                    continue
                ppg = x.get("pp_gir")
                if not ppg and x.get("gir_hit"):
                    ppg = x.get("gir_putts", 0) / x["gir_hit"] if x.get("gir_putts") else None
                rows.append({"pid": str(pid), "season": s, "tour": t, "n": x.get("rounds"), "dist": x.get("dist"), "acc": x.get("acc"),
                             "gir": x.get("gir"), "ppg": ppg, "sand": x.get("sand")})
    df = pd.DataFrame(rows)
    for c in ("acc", "gir", "sand"):
        if c in df.columns:
            df[c] = df[c] / 100.0
    return df


# ── the round frame ──────────────────────────────────────────────────────────

def round_frame(sg: pd.DataFrame, extras: pd.DataFrame) -> pd.DataFrame:
    """The walked rounds with the nines against the field's par for each nine and the tee-time wave (rounds 1-2)."""
    df = sg.merge(extras, on=["event", "pid", "round"], how="left")
    ok = df["out"].notna() & df["in"].notna() & ((df["out"] + df["in"]) == df["strokes"])
    po = (df["out"] + df["pre"] / 2).where(ok)
    pi = (df["in"] + df["pre"] / 2).where(ok)
    g = [df["event"], df["round"]]
    df["sg_f"] = po.groupby(g).transform("mean") - df["out"].where(ok)
    df["sg_b"] = pi.groupby(g).transform("mean") - df["in"].where(ok)
    tt = pd.to_datetime(df["tee_time"], errors="coerce", utc=True)
    df["tt"] = tt
    early = df["round"] <= 2
    med = tt.where(early).groupby(g).transform("median")
    df["wave"] = np.where(early & tt.notna(), np.where(tt <= med, "am", "pm"), "")
    df["res"] = df["sg"] - df["pre"]
    return df


# ── per-player metrics ──────────────────────────────────────────────────────

def _shrink(mean: pd.Series, n: pd.Series, k: float, prior: float | None = None) -> pd.Series:
    if prior is None:
        w = n.fillna(0)
        prior = float((mean.fillna(0) * w).sum() / w.sum()) if w.sum() else 0.0
    return (mean * n + k * prior) / (n + k)


def player_metrics(rf: pd.DataFrame, hf: pd.DataFrame, res: pd.DataFrame, st: pd.DataFrame, cats: dict | None,
                   by: list[str] = ["pid"]) -> pd.DataFrame:
    """One row per `by` group (pid, or pid and year) with every metric shrunk, plus rounds, events and holes."""
    g = rf.groupby(by)
    out = pd.DataFrame({"rounds": g.size(), "events": g["event"].nunique()})
    out["sg_raw"] = g["sg"].mean()
    out["sg"] = _shrink(out["sg_raw"], out["rounds"], K_ROUNDS)
    for key, mask in (("sg_e", rf["round"] <= 2), ("sg_w", rf["round"] >= 3)):
        gg = rf[mask].groupby(by)["sg"]
        out[key] = _shrink(gg.mean(), gg.size(), K_ROUNDS).reindex(out.index)
    for key in ("sg_f", "sg_b"):
        gg = rf[rf[key].notna()].groupby(by)[key]
        out[key] = _shrink(gg.mean(), gg.size(), K_ROUNDS).reindex(out.index)
    resid = rf["sg"] - rf.groupby(by)["sg"].transform("mean")
    sd = resid.groupby([rf[b] for b in by]).std()
    out["sd"] = _shrink(sd, out["rounds"], K_ROUNDS)
    # great and poor are judged against the player's own field, so rounds in weak fields do not inflate them
    rel = rf["sg"] - rf.groupby(["event", "round"])["sg"].transform("mean")
    for key, m in (("great", rel >= GREAT), ("poor", rel <= POOR)):
        gg = m.astype(float).groupby([rf[b] for b in by])
        out[key] = _shrink(gg.mean(), gg.size(), K_ROUNDS)
    # form: the last eight events (window only; by pid)
    if by == ["pid"]:
        ev = rf.groupby(["pid", "event"]).agg(sg=("sg", "mean"), n=("sg", "size"), d=("date", "max")).reset_index()
        ev = ev.sort_values("d").groupby("pid").tail(8)
        fs = ev.groupby("pid").apply(lambda x: float((x["sg"] * x["n"]).sum() / x["n"].sum()))
        fn = ev.groupby("pid")["n"].sum()
        out["form"] = _shrink(fs, fn, K_ROUNDS).reindex(out.index)
    # holes
    if len(hf):
        hg = hf.groupby(by)
        out["holes"] = hg.size()
        for p in (3, 4, 5):
            s = hf[hf["par"] == p].groupby(by)["d"]
            out[f"h{p}"] = _shrink(s.mean(), s.size(), K_HOLES / 3).reindex(out.index)
        for key, m, sub in (("bird", hf["rel"] <= -1, None), ("bog", hf["rel"] >= 1, None), ("dbl", hf["rel"] >= 2, None),
                            ("eag", hf["rel"] <= -2, hf["par"] == 5)):
            x = m.astype(float)
            if sub is not None:
                x = x[sub]
                keys = [hf.loc[sub, b] for b in by]
            else:
                keys = [hf[b] for b in by]
            gg = x.groupby(keys)
            out[key] = _shrink(gg.mean(), gg.size(), K_HOLES if sub is None else K_HOLES / 4).reindex(out.index)
    # outcomes
    if len(res):
        rr = res.copy()
        rr["win"] = ((rr["pos"] == 1) & (rr["status"] == "finish")).astype(float)
        rr["t10"] = ((rr["pos"] <= 10) & (rr["status"] == "finish")).astype(float)
        rg = rr.groupby(by)
        out["starts"] = rg.size().reindex(out.index)
        for key in ("win", "t10"):
            out[key] = _shrink(rg[key].mean(), rg.size(), K_EVENTS).reindex(out.index)
        rc = rr[rr["cut_round"] > 0]
        cg = (rc["status"] == "finish").astype(float).groupby([rc[b] for b in by])
        out["cut"] = _shrink(cg.mean(), cg.size(), K_EVENTS).reindex(out.index)
        out["wins"] = rg["win"].sum().reindex(out.index)
        out["top10"] = rg["t10"].sum().reindex(out.index)
    # striking (season stats, weighted by rounds)
    if len(st):
        s = st.copy()
        keyc = by if "year" not in by else ["pid", "season"]
        if "year" in by:
            s = s.rename(columns={"season": "year"})
            keyc = by
        for c in ("dist", "acc", "gir", "ppg", "sand"):
            v = s[c].notna()
            num = (s[c].where(v) * s["n"]).groupby([s[b] for b in keyc]).sum(min_count=1)
            den = s["n"].where(v).groupby([s[b] for b in keyc]).sum()
            out[c] = (num / den).reindex(out.index)
        if cats:
            z = category_scores(st, cats)
            for c in ("c_ott", "c_app", "c_arg", "c_putt"):
                num = (z[c] * s["n"]).groupby([s[b] for b in keyc]).sum(min_count=1)
                den = s["n"].where(z[c].notna()).groupby([s[b] for b in keyc]).sum()
                out[c] = (num / den).reindex(out.index)
    return out


# ── strokes-gained categories from season statistics ────────────────────────

FEAT = ("dist", "acc", "gir", "ppg", "sand")


def _z(s: pd.DataFrame, mom: dict | None = None, min_rounds: int = 30) -> pd.DataFrame:
    """Each statistic z-scored within its season against that season's regulars (min_rounds), so the tour's drift
    (drives are about ten yards longer than in 2017) does not read as skill."""
    z = pd.DataFrame(index=s.index)
    reg = s["n"] >= min_rounds if "n" in s.columns else pd.Series(True, index=s.index)
    for c in FEAT:
        g = s[c].where(reg).groupby(s["season"])
        m, sd = g.transform("mean"), g.transform("std")
        z[c] = (s[c] - m) / sd
    return z


def fit_categories(stats: pd.DataFrame, rf: pd.DataFrame, train=range(2017, 2023), test=range(2023, 2026),
                   min_rounds: int = 30) -> dict | None:
    """OLS of a player-season's mean strokes gained (PGA Tour rounds, centred on the season's player mean) on the
    season's z-scored statistics. Fit on `train` seasons, scored once on `test` (R2 out of sample)."""
    if not len(stats):
        return None
    pga = rf[rf["tour"] == "pga"]
    ys = pga.groupby(["pid", pga["date"].dt.year])["sg"].agg(["mean", "size"]).reset_index()
    ys.columns = ["pid", "season", "y", "nr"]
    d = stats.merge(ys, on=["pid", "season"])
    d = d[(d["nr"] >= min_rounds)].dropna(subset=list(FEAT))
    if len(d) < 200:
        return None
    d["y"] = d["y"] - d.groupby("season")["y"].transform("mean")
    mom = {c: (float(d[c].mean()), float(d[c].std())) for c in FEAT}
    z = _z(d, min_rounds=0)
    X = np.column_stack([np.ones(len(d))] + [z[c].to_numpy() for c in FEAT])
    tr = d["season"].isin(list(train)).to_numpy()
    te = d["season"].isin(list(test)).to_numpy()
    if tr.sum() < 200 or te.sum() < 100:
        return None
    b, *_ = np.linalg.lstsq(X[tr], d["y"].to_numpy()[tr], rcond=None)

    def r2(mask):
        y = d["y"].to_numpy()[mask]
        p = X[mask] @ b
        return float(1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum())
    return {"coef": {c: float(b[i + 1]) for i, c in enumerate(FEAT)}, "intercept": float(b[0]), "mom": mom,
            "r2_train": r2(tr), "r2_test": r2(te), "n_train": int(tr.sum()), "n_test": int(te.sum()),
            "train": [train.start, train.stop - 1], "test": [test.start, test.stop - 1]}


def category_scores(s: pd.DataFrame, cats: dict) -> pd.DataFrame:
    z = _z(s)
    b = cats["coef"]
    return pd.DataFrame({"c_ott": b["dist"] * z["dist"] + b["acc"] * z["acc"], "c_app": b["gir"] * z["gir"],
                         "c_arg": b["sand"] * z["sand"], "c_putt": b["ppg"] * z["ppg"]}, index=s.index)


# ── percentiles ─────────────────────────────────────────────────────────────

def percentiles(df: pd.DataFrame, pool: pd.Series, ids=METRICS) -> pd.DataFrame:
    """Each metric's percentile (0-100) against the rows in `pool` (a boolean mask); lower-is-better flipped."""
    out = pd.DataFrame(index=df.index)
    for m in ids:
        if m not in df.columns:
            continue
        ref = np.sort(df.loc[pool, m].dropna().to_numpy())
        if len(ref) < 10:
            continue
        v = df[m].to_numpy(dtype=float)
        lo = np.searchsorted(ref, v, side="left")
        hi = np.searchsorted(ref, v, side="right")
        p = 100.0 * (lo + hi) / 2.0 / len(ref)
        if METRICS[m][3] == "lower":
            p = 100.0 - p
        out[m] = np.where(np.isfinite(v), np.round(p, 0), np.nan)
    return out


def similar(pc: pd.DataFrame, ids: list[str], pool: pd.Index, n: int = 5, values: pd.DataFrame | None = None) -> dict:
    """For each row, the n nearest pool rows: ranked on the z-scored values when given (percentiles saturate at the top,
    so the best players would all look alike), reported as the mean percentile gap over shared metrics."""
    cols = [c for c in ids if c in pc.columns]
    P = pc.loc[pool, cols].to_numpy(dtype=float)
    Z = None
    if values is not None:
        zv = values[cols].astype(float)
        zv = (zv - zv.loc[pool].mean()) / zv.loc[pool].std()
        Z, ZP = zv, zv.loc[pool].to_numpy(dtype=float)
    out = {}
    for pid in pc.index:
        v = pc.loc[pid, cols].to_numpy(dtype=float)
        ok = np.isfinite(P) & np.isfinite(v)[None, :]
        cnt = ok.sum(axis=1)
        pgap = np.where(ok, np.abs(P - v[None, :]), 0).sum(axis=1) / np.maximum(cnt, 1)
        if Z is not None:
            zr = Z.loc[pid].to_numpy(dtype=float)
            okz = np.isfinite(ZP) & np.isfinite(zr)[None, :]
            gap = np.sqrt(np.where(okz, (ZP - zr[None, :]) ** 2, 0).sum(axis=1) / np.maximum(okz.sum(axis=1), 1))
        else:
            gap = pgap.copy()
        gap[(cnt < max(3, len(cols) // 2))] = np.inf
        if pid in pool:
            gap[pool.get_loc(pid)] = np.inf
        order = np.argsort(gap)[:n]
        out[pid] = [(pool[i], float(pgap[i])) for i in order if np.isfinite(gap[i])]
    return out


# ── courses ─────────────────────────────────────────────────────────────────

def course_table(meta: pd.DataFrame, rf: pd.DataFrame, stats: pd.DataFrame, cats: dict | None, off=None) -> pd.DataFrame:
    """One row per course with events on file: editions, rounds, scoring against par, yards, what it rewards."""
    m = meta[meta["single"] & meta["course"].notna() & ~meta["team"] & (meta["status"] == "final")]
    d = rf.drop(columns=[c for c in ("course", "par") if c in rf.columns]).merge(m[["event", "course", "par"]], on="event")
    d = d[d["par"].notna()]
    d["tp"] = d["strokes"] - d["par"].astype(float)
    g = d.groupby("course")
    out = pd.DataFrame({"rounds": g.size(), "events": g["event"].nunique(), "to_par": g["tp"].mean(),
                        "first": g["date"].min(), "last": g["date"].max()})
    info = m.sort_values("start").groupby("course").last()
    out["name"] = info["course_name"]
    out["par"] = info["par"]
    out["yards"] = info["yards"]
    out["tour"] = info["tour"]
    # field strength-adjusted difficulty: the average field par (strokes an average field takes) against par
    fp = d.groupby(["course", "event", "round"]).agg(fp=("field_par", "first"), par=("par", "first"), date=("date", "first")).reset_index()
    # the field par is what a raw rating of zero shoots; an average tour player of the day carries the display offset
    o = fp["date"].map({t: off.at(t) for t in fp["date"].unique()}) if off is not None else 0.0
    out["diff"] = (fp["fp"] - o - fp["par"].astype(float)).groupby(fp["course"]).mean()
    # what it rewards: correlation of (sg - pre) at the course with each z-scored season stat (PGA 2017 on)
    if len(stats) and cats:
        z = _z(stats)
        zz = pd.concat([stats[["pid", "season"]], z], axis=1)
        d["season"] = d["date"].dt.year
        dd = d.merge(zz, on=["pid", "season"])
        for c in FEAT:
            cc = dd.groupby("course").apply(lambda x: x["res"].corr(x[c]) if x[c].notna().sum() >= 150 else np.nan)
            out[f"rw_{c}"] = cc
    return out


def course_similar(ct: pd.DataFrame, n: int = 4) -> dict:
    f = [c for c in ("yards", "diff", "rw_dist", "rw_acc", "rw_gir", "rw_ppg") if c in ct.columns]
    X = ct[f].astype(float)
    X = (X - X.mean()) / X.std()
    out = {}
    A = X.to_numpy()
    for i, cid in enumerate(ct.index):
        v = A[i]
        ok = np.isfinite(A) & np.isfinite(v)[None, :]
        cnt = ok.sum(axis=1)
        gap = np.sqrt(np.where(ok, (A - v[None, :]) ** 2, 0).sum(axis=1) / np.maximum(cnt, 1))
        gap[cnt < 3] = np.inf
        gap[i] = np.inf
        order = [j for j in np.argsort(gap)[:n] if np.isfinite(gap[j])]
        out[cid] = [(ct.index[j], float(gap[j])) for j in order]
    return out


def course_history(rf: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Per player and course: rounds, events, strokes gained per round and against the player's own rating (shrunk)."""
    m = meta[meta["single"] & meta["course"].notna()][["event", "course"]]
    d = rf.drop(columns=[c for c in ("course",) if c in rf.columns]).merge(m, on="event")
    g = d.groupby(["pid", "course"])
    out = pd.DataFrame({"rounds": g.size(), "events": g["event"].nunique(), "sg": g["sg"].mean(), "res": g["res"].mean(),
                        "last": g["date"].max()})
    out["fit"] = out["res"] * out["rounds"] / (out["rounds"] + K_COURSE)
    return out.reset_index()
