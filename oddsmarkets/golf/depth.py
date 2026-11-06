"""
The Quant Green's depth payloads (6 Nov 2026): the Scouting Room, player profiles, courses, the Lab, records, the
points ranking and the overview. Built from the walked streams (pages.Stream) and analytics.py, so it adds no fetching.

    scout/<stream>.json      the board: every player with MIN_BOARD rounds in the last two years, column-oriented,
                             each metric shrunk toward the peer average (analytics.METRICS)
    courses.json             every course with editions on file: difficulty, length, what it rewards, its events
    courses/<id>.json        a course: editions and winners, the players who play it best, the hardest holes,
                             courses most like it
    lab.json                 what wins, the strokes-gained category fit, age curves, waves, rounds, tours
    records.json             lowest rounds against the field, biggest wins, longest-odds winners, best seasons
    points.json              an OWGR-style points ranking rebuilt from results with our own field strengths
    overview.json            featured event, the week's digest, power board, stories, leaders, who's for real

No look-ahead: an event page's chances stay the walk-forward ones (pages.py); here, a course's "players who play it
best" and a player's course history use every final event, and the live and upcoming fields' course history uses
only editions before the event.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import analytics as A
from . import canon, store

logger = logging.getLogger(__name__)

MIN_BOARD = 12               # rounds in the window to appear on the board
SEASON_Q = 25                # rounds in a season for its percentiles (the ring, year by year)
KEY_IDS = ["sg", "sg_e", "sg_w", "sd", "great", "h3", "h4", "h5", "bird", "bog", "dist", "acc", "gir", "ppg", "t10", "cut"]
POINTS_SHARE = {1: 1.0, 2: .64, 3: .48, 4: .39, 5: .33, 6: .29, 7: .26, 8: .235, 9: .215, 10: .20, 15: .145, 20: .11,
                25: .087, 30: .07, 40: .049, 50: .034, 60: .023}
POINTS_WEEKS_FULL, POINTS_WEEKS = 13, 104
POINTS_DIV = (40, 52)


def _r(x, k=3):
    return A._r(x, k)


def _int(x):
    v = _r(x, 0)
    return None if v is None else int(v)


def _share(pos: float) -> float:
    ks = sorted(POINTS_SHARE)
    if pos <= 1:
        return 1.0
    if pos > ks[-1]:
        return 0.0
    for a, b in zip(ks[:-1], ks[1:]):
        if a <= pos <= b:
            t = (pos - a) / (b - a)
            return POINTS_SHARE[a] + t * (POINTS_SHARE[b] - POINTS_SHARE[a])
    return 0.0


def _age(dob: str | None, at: date) -> float | None:
    if not dob:
        return None
    try:
        d = date.fromisoformat(dob[:10])
    except ValueError:
        return None
    return round((at - d).days / 365.25, 1)


class Depth:
    def __init__(self, streams: dict, streams_tours: dict, players_meta: dict, today: date):
        self.today = today
        self.t = pd.Timestamp(today)
        self.since = self.t - pd.Timedelta(days=A.WINDOW_DAYS)
        self.meta_p = players_meta
        self.bios = store.load_bios()
        self.S = {}
        stats = A.stats_frame()
        for key, st in streams.items():
            tours = streams_tours[key]
            meta = A.event_meta(tours)
            rf = A.round_frame(st.sg, A.round_extras(tours))
            rf = rf.merge(meta[["event", "major", "yards", "course", "single"]], on="event", how="left")
            res = A.results_frame(tours, meta)
            hf = A.holes_frame(tours, meta, pd.Timestamp(year=today.year - 5, month=1, day=1))
            stt = stats if key == "men" else stats.iloc[0:0]
            self.S[key] = {"st": st, "tours": tours, "meta": meta, "rf": rf, "res": res, "hf": hf, "stats": stt}
        self.cats = A.fit_categories(stats, self.S["men"]["rf"]) if len(stats) else None
        for key in self.S:
            self._window(key)
            self._seasons(key)
            self._courses(key)

    # ── the window ───────────────────────────────────────────────────────
    def _window(self, key):
        d = self.S[key]
        st, rf = d["st"], d["rf"]
        w = rf[rf["date"] >= self.since]
        hf = d["hf"][d["hf"]["start"] >= self.since] if len(d["hf"]) else d["hf"]
        res = d["res"][d["res"]["start"] >= self.since]
        stt = d["stats"][d["stats"]["season"] >= self.since.year] if len(d["stats"]) else d["stats"]
        W = A.player_metrics(w, hf, res, stt, self.cats)
        W = W[W["rounds"] >= MIN_BOARD]
        off = st.off.at(self.t)
        W["rt"] = [st.book.rating(p, self.t) - off for p in W.index]
        W["tour"] = w.groupby("pid")["tour"].agg(lambda s: s.value_counts().index[0]).reindex(W.index)
        W["q"] = W["rounds"] >= A.Q_ROUNDS
        if "holes" in W.columns:
            W.loc[W["holes"].fillna(0) < 180, ["h3", "h4", "h5", "bird", "bog", "dbl", "eag"]] = np.nan
        W["age"] = [_age((self.bios.get(p) or {}).get("dob"), self.today) for p in W.index]
        pc = A.percentiles(W, W["q"])
        d["W"], d["pc"] = W, pc
        d["sim"] = A.similar(pc, KEY_IDS, W.index[W["q"]], values=W)
        d["splits"] = self._splits(w)

    def _splits(self, w: pd.DataFrame) -> dict:
        x = w.copy()
        x["long"] = np.where(x["yards"].fillna(0) >= 7400, "7,400 yards and longer", np.where(x["yards"].fillna(0) > 0, "Under 7,400 yards", ""))
        defs = [("tour", lambda s: canon.TOURS.get(s, {}).get("name", s)), ("major", lambda s: "Majors" if s else "Other events"),
                ("wave", lambda s: {"am": "Early tee times (rounds 1-2)", "pm": "Late tee times (rounds 1-2)"}.get(s, "")),
                ("long", lambda s: s)]
        prior = 0.0
        out: dict = {}
        for col, lab in defs:
            g = x.groupby(["pid", col])["sg"].agg(["mean", "size"]).reset_index()
            g = g[g[col].map(lambda v: bool(lab(v))) & (g["size"] >= 4)]
            for r in g.itertuples(index=False):
                m = (r[2] * r[3] + A.K_ROUNDS * prior) / (r[3] + A.K_ROUNDS)
                out.setdefault(r[0], []).append({"kind": col, "label": lab(r[1]), "n": int(r[3]), "sg": _r(m, 2), "raw": _r(r[2], 2)})
        return out

    # ── seasons ──────────────────────────────────────────────────────────
    def _seasons(self, key):
        d = self.S[key]
        rf = d["rf"].copy()
        rf["year"] = rf["date"].dt.year
        hf = d["hf"].copy()
        if len(hf):
            hf["year"] = hf["start"].dt.year
        res = d["res"].copy()
        res["year"] = res["start"].dt.year
        stt = d["stats"].copy()
        S = A.player_metrics(rf, hf, res, stt, self.cats, by=["pid", "year"])
        if "holes" in S.columns:
            S.loc[S["holes"].fillna(0) < 180, ["h3", "h4", "h5", "bird", "bog", "dbl", "eag"]] = np.nan
        S["q"] = S["rounds"] >= SEASON_Q
        pcs = []
        for y, g in S.groupby(level="year"):
            pcs.append(A.percentiles(g, g["q"]))
        d["Sm"] = S
        d["Spc"] = pd.concat(pcs) if pcs else pd.DataFrame()

    # ── courses ──────────────────────────────────────────────────────────
    def _courses(self, key):
        d = self.S[key]
        ct = A.course_table(d["meta"], d["rf"], d["stats"], self.cats if key == "men" else None, off=d["st"].off)
        ct = ct[ct["rounds"] >= 200]
        d["ct"] = ct
        d["csim"] = A.course_similar(ct) if len(ct) > 5 else {}
        d["ch"] = A.course_history(d["rf"], d["meta"])

    # ── per player ───────────────────────────────────────────────────────
    def player_extra(self, key: str, pid: str) -> dict:
        d = self.S[key]
        out: dict = {}
        W, pc = d["W"], d["pc"]
        if pid in W.index:
            row = W.loc[pid]
            out["cur"] = {"v": {m: _r(row.get(m), 4) for m in A.METRICS if m in W.columns and _r(row.get(m), 4) is not None},
                          "pc": {m: _int(pc.loc[pid, m]) for m in pc.columns if _int(pc.loc[pid, m]) is not None},
                          "q": bool(row["q"]), "rounds": int(row["rounds"]), "events": int(row["events"]), "from": str(self.since.date()),
                          "tour": row["tour"]}
            out["similar"] = [{"id": p, "n": (self.meta_p.get(p) or {}).get("name") or p, "d": _r(g, 1), "tour": W.loc[p, "tour"]} for p, g in d["sim"].get(pid, [])]
        out["splits"] = d["splits"].get(pid, [])
        S, Spc = d["Sm"], d["Spc"]
        if pid in S.index.get_level_values(0):
            ss = S.loc[pid]
            sp = Spc.loc[pid] if pid in Spc.index.get_level_values(0) else pd.DataFrame()
            seas = []
            for y, r in ss.iterrows():
                if r["rounds"] < 8:
                    continue
                v = {m: _r(r.get(m), 4) for m in A.METRICS if m in ss.columns and _r(r.get(m), 4) is not None}
                p = {m: _int(sp.loc[y, m]) for m in sp.columns if y in sp.index and _int(sp.loc[y, m]) is not None} if len(sp) else {}
                seas.append({"y": int(y), "n": int(r["rounds"]), "q": bool(r["q"]), "v": v, "pc": p})
            out["sm"] = seas
            prev = [s for s in seas if s["q"] and s["y"] < self.today.year]
            if prev:
                out["prev"] = {"y": prev[-1]["y"], "pc": prev[-1]["pc"]}
        ch = d["ch"]
        mine = ch[(ch["pid"] == pid) & (ch["rounds"] >= 8)]
        if len(mine):
            ct = d["ct"]
            mine = mine[mine["course"].isin(ct.index)].sort_values("fit", ascending=False)
            pick = pd.concat([mine.head(6), mine.tail(3)]).drop_duplicates("course") if len(mine) > 9 else mine
            out["courses"] = [{"id": r.course, "name": ct.loc[r.course, "name"], "rounds": int(r.rounds), "events": int(r.events),
                               "sg": _r(r.sg, 2), "fit": _r(r.fit, 2), "last": str(r.last.date())} for r in pick.itertuples()]
        b = self.bios.get(pid) or {}
        if b:
            out["bio"] = {k: v for k, v in {"age": _age(b.get("dob"), self.today), "dob": b.get("dob"), "ht": b.get("ht_in"),
                                            "pro": b.get("pro"), "born": b.get("born")}.items() if v is not None}
        # form: strokes gained per event, last 30 events
        rf = d["rf"]
        ev = rf[rf["pid"] == pid].groupby("event").agg(sg=("sg", "mean"), n=("sg", "size"), d=("date", "min"), pre=("pre", "first")).reset_index()
        ev = ev.sort_values("d").tail(40)
        off = d["st"].off
        out["form"] = [[str(r.d.date()), _r(r.sg, 2), r.n, _r(r.pre - off.at(r.d), 2)] for r in ev.itertuples()]
        return out

    def last_course(self, key: str, tour: str, name: str | None, before: pd.Timestamp) -> str | None:
        """The course of the last final single-course edition of an event of this name on this tour."""
        if not name:
            return None
        m = self.S[key]["meta"]
        norm = lambda x: " ".join(str(x or "").lower().replace("the ", "").split())
        x = m[(m["tour"] == tour) & m["single"] & (m["status"] == "final") & (m["start"] < before) & m["course"].notna()]
        x = x[x["name"].map(norm) == norm(name)]
        if not len(x):
            return None
        return str(x.sort_values("start").iloc[-1]["course"])

    def course_fit(self, key: str, pids: list[str], course: str | None, before: pd.Timestamp) -> dict:
        """Course history of a field before an event (no look-ahead): pid -> {n, ev, sg, fit}."""
        if not course:
            return {}
        d = self.S[key]
        m = d["meta"]
        evs = set(m[(m["course"] == course) & m["single"] & (m["start"] < before)]["event"])
        if not evs:
            return {}
        x = d["rf"][d["rf"]["event"].isin(evs) & d["rf"]["pid"].isin(set(pids))]
        g = x.groupby("pid")
        out = {}
        for pid, gg in g:
            n = len(gg)
            out[pid] = {"n": n, "ev": int(gg["event"].nunique()), "sg": _r(gg["sg"].mean(), 2),
                        "fit": _r(gg["res"].sum() / (n + A.K_COURSE), 2)}
        return out

    # ── the board ────────────────────────────────────────────────────────
    def scout(self, key: str, rank: dict) -> dict:
        d = self.S[key]
        W = d["W"]
        mids = [m for m in A.METRICS if m in W.columns and W[m].notna().any()]
        cols = ["id", "n", "cc", "tour", "age", "rounds", "events", "q", "rank"] + mids
        rows = []
        for pid, r in W.iterrows():
            m = self.meta_p.get(pid) or {}
            rows.append([pid, m.get("name") or pid, m.get("country"), r["tour"], _r(r["age"], 1), int(r["rounds"]), int(r["events"]),
                         1 if r["q"] else 0, (rank.get(pid) or {}).get("rank")] +
                        [(_r(r[c] * (1 if c not in A.PCT else 1), 4)) for c in mids])
        metrics = [{"id": m, "label": A.METRICS[m][0], "short": A.METRICS[m][1], "family": A.METRICS[m][2], "dir": A.METRICS[m][3],
                    "unit": A.METRICS[m][4], "tip": A.TIPS.get(m, ""), "pct": m in A.PCT} for m in mids]
        return {"stream": key, "from": str(self.since.date()), "min_q": A.Q_ROUNDS, "min_board": MIN_BOARD, "cols": cols, "rows": rows,
                "metrics": metrics, "tours": {t: canon.TOURS[t]["name"] for t in d["tours"]}}

    # ── courses ──────────────────────────────────────────────────────────
    def courses(self, key: str, pages_index: dict) -> tuple[list, dict]:
        d = self.S[key]
        ct, m = d["ct"], d["meta"]
        lst, pages = [], {}
        res = d["res"]
        winners = res[(res["pos"] == 1) & (res["status"] == "finish")]
        hf = d["hf"]
        for cid, r in ct.iterrows():
            evs = m[(m["course"] == cid) & m["single"] & ~m["team"]].sort_values("start")
            ed = []
            for e in evs.itertuples():
                w = winners[winners["event"] == e.event]
                wpid = w["pid"].iloc[0] if len(w) else None
                ed.append({"id": e.event, "y": int(e.season), "tour": e.tour, "name": e.name, "status": e.status, "page": e.event in pages_index,
                           "winner": {"pid": wpid, "name": (self.meta_p.get(wpid) or {}).get("name")} if wpid else None})
            rw = {c: _r(r.get(f"rw_{c}"), 3) for c in A.FEAT if f"rw_{c}" in ct.columns and _r(r.get(f"rw_{c}"), 3) is not None}
            item = {"id": cid, "name": r["name"], "par": _int(r["par"]), "yards": _int(r["yards"]), "tour": r["tour"], "rounds": int(r["rounds"]),
                    "events": int(r["events"]), "to_par": _r(r["to_par"], 2), "diff": _r(r["diff"], 2), "first": str(r["first"].date()),
                    "last": str(r["last"].date()), "rw": rw, "ev": [e["id"] for e in ed]}
            lst.append(item)
            ch = d["ch"][(d["ch"]["course"] == cid) & (d["ch"]["rounds"] >= 8)]
            best = ch.sort_values("fit", ascending=False).head(20)
            most = ch.sort_values("rounds", ascending=False).head(10)
            holes = None
            if len(hf):
                hh = hf[hf["event"].isin(set(evs["event"]))]
                if len(hh):
                    g = hh.groupby("hole")
                    holes = [{"h": int(h), "par": int(x["par"].mode().iloc[0]), "n": int(len(x)), "avg": _r((x["strokes"] - x["par"]).mean(), 3),
                              "bird": _r((x["rel"] <= -1).mean(), 3), "bog": _r((x["rel"] >= 1).mean(), 3)} for h, x in g]
            pages[cid] = {**item, "editions": ed[::-1],
                          "best": [{"pid": x.pid, "name": (self.meta_p.get(x.pid) or {}).get("name") or x.pid, "rounds": int(x.rounds), "events": int(x.events),
                                    "sg": _r(x.sg, 2), "fit": _r(x.fit, 2)} for x in best.itertuples()],
                          "most": [{"pid": x.pid, "name": (self.meta_p.get(x.pid) or {}).get("name") or x.pid, "rounds": int(x.rounds), "events": int(x.events),
                                    "sg": _r(x.sg, 2), "fit": _r(x.fit, 2)} for x in most.itertuples()],
                          "holes": holes,
                          "similar": [{"id": c, "name": ct.loc[c, "name"], "gap": _r(g, 2)} for c, g in d["csim"].get(cid, [])],
                          "stream": key}
        return lst, pages

    # ── what each result would do ────────────────────────────────────────
    def outcomes_table(self, key: str) -> dict:
        d = self.S[key]
        rf, res = d["rf"], d["res"]
        recent = res[res["start"] >= self.t - pd.Timedelta(days=3 * 365)]
        x = rf.merge(recent[["event", "pid", "pos", "status"]], on=["event", "pid"])
        ev = x.groupby(["event", "pid", "pos", "status"], dropna=False)["sg"].agg(["mean", "size"]).reset_index()
        out = {}
        for name, m in (("win", (ev["pos"] == 1) & (ev["status"] == "finish")), ("top10", (ev["pos"].between(2, 10)) & (ev["status"] == "finish")),
                        ("mid", (ev["pos"].between(30, 50)) & (ev["status"] == "finish")), ("mc", ev["status"] == "cut")):
            g = ev[m]
            out[name] = {"sg": _r(g["mean"].mean(), 2), "rounds": int(round(g["size"].median())) if len(g) else 0}
        return out

    def what_if(self, key: str, pids: list[str], table: dict) -> dict:
        st = self.S[key]["st"]
        b, p = st.book, st.p
        t = self.t
        off = st.off.at(t)
        out = {}
        for pid in pids:
            if pid not in b.t:
                continue
            f = b._decay(pid, t)
            s, w = b.s[pid] * f, b.w[pid] * f
            now = (p.k0 * p.m0 + s) / (p.k0 + w) - off
            row = {}
            for k, v in table.items():
                if v["sg"] is None or not v["rounds"]:
                    continue
                n = v["rounds"]
                row[k] = _r((p.k0 * p.m0 + s + n * v["sg"]) / (p.k0 + w + n) - off - now, 2)
            out[pid] = row
        return out

    # ── points ranking (OWGR-style, our method) ──────────────────────────
    def points(self, key: str) -> dict:
        d = self.S[key]
        st, m, res = d["st"], d["meta"], d["res"]
        start = self.t - pd.Timedelta(weeks=POINTS_WEEKS)
        evs = m[(m["status"] == "final") & ~m["team"] & (m["start"] >= start) & (m["start"] <= self.t)]
        strengths = {}
        for e in evs.itertuples():
            pre = st.pre_by_event.get(e.event)
            if not pre:
                continue
            off = st.off.at(e.start)
            r = np.array(list(pre.values())) - off
            strengths[e.event] = float(np.sum(np.clip(r + 1.0, 0, None) ** 1.5))
        if not strengths:
            return {"rows": []}
        ref = np.percentile([v for k, v in strengths.items() if not m.set_index("event").loc[k, "major"]], 95)
        rows = []
        info = m.set_index("event")
        for eid, s in strengths.items():
            e = info.loc[eid]
            wp = 100.0 if e["major"] else float(np.clip(80.0 * s / ref, 4.0, 80.0))
            r = res[(res["event"] == eid) & (res["status"] == "finish") & res["pos"].notna()]
            if not len(r):
                continue
            cnt = r.groupby("pos").size()
            share = {}
            for pos, k in cnt.items():
                share[pos] = np.mean([_share(pos + j) for j in range(int(k))])
            age_w = (self.t - e["start"]).days / 7.0
            dec = 1.0 if age_w <= POINTS_WEEKS_FULL else max(0.0, 1 - (age_w - POINTS_WEEKS_FULL) / (POINTS_WEEKS - POINTS_WEEKS_FULL))
            for x in res[(res["event"] == eid) & res["status"].isin(["finish", "cut", "wd", "dq", "mdf"])].itertuples():
                pts = wp * share.get(x.pos, 0.0) if x.status == "finish" and x.pos == x.pos else 0.0
                rows.append((x.pid, eid, pts, pts * dec, e["start"], wp))
        df = pd.DataFrame(rows, columns=["pid", "event", "pts", "dpts", "start", "wp"])
        g = df.groupby("pid").agg(total=("dpts", "sum"), ev=("event", "nunique"), best=("pts", "max"))
        g["div"] = g["ev"].clip(POINTS_DIV[0], POINTS_DIV[1])
        g["avg"] = g["total"] / g["div"]
        g = g.sort_values("avg", ascending=False).head(300)
        ev_pts = {eid: _r(80.0 * s / ref if not info.loc[eid, "major"] else 100.0, 1) for eid, s in strengths.items()}
        out = [{"rank": i + 1, "pid": pid, "name": (self.meta_p.get(pid) or {}).get("name") or pid, "cc": (self.meta_p.get(pid) or {}).get("country"),
                "avg": _r(r["avg"], 3), "total": _r(r["total"], 1), "ev": int(r["ev"]), "div": int(r["div"])} for i, (pid, r) in enumerate(g.iterrows())]
        top = sorted(((eid, v) for eid, v in ev_pts.items()), key=lambda x: -(x[1] or 0))[:12]
        return {"rows": out, "events": len(strengths),
                "top_events": [{"id": e, "name": info.loc[e, "name"], "tour": info.loc[e, "tour"], "wp": min(v, 100.0) if v else None} for e, v in top]}

    # ── lab ──────────────────────────────────────────────────────────────
    def lab(self) -> dict:
        out: dict = {"cats": None}
        men = self.S["men"]
        if self.cats:
            c = self.cats
            out["cats"] = {"coef": {k: _r(v, 3) for k, v in c["coef"].items()}, "r2_train": _r(c["r2_train"], 3), "r2_test": _r(c["r2_test"], 3),
                           "n_train": c["n_train"], "n_test": c["n_test"], "train": c["train"], "test": c["test"],
                           "mom": {k: [_r(v[0], 3), _r(v[1], 3)] for k, v in c["mom"].items()}}
        # what wins: the correlation of each season stat with season strokes gained, and stat by stat scatter samples
        S = men["Sm"]
        q = S[S["q"]].reset_index()
        q = q[q["year"] >= canon.STATS_FROM]
        corr = {}
        for c in ("dist", "acc", "gir", "ppg", "sand", "h3", "h4", "h5", "bird", "bog", "sd"):
            if c in q.columns and q[c].notna().sum() > 100:
                corr[c] = _r(q["sg"].corr(q[c]), 3)
        out["what_wins"] = corr
        last = q[q["year"] == q["year"].max() - (1 if self.today.month < 6 else 0)]
        out["scatter"] = {"year": int(last["year"].max()) if len(last) else None,
                          "rows": [[r.pid, (self.meta_p.get(r.pid) or {}).get("name") or r.pid] + [_r(getattr(r, c, None), 3) for c in ("sg", "dist", "acc", "gir", "ppg", "sand")]
                                   for r in last.itertuples()]}
        # age curve (delta method on season strokes gained, players with a bio)
        out["age"] = self._age_curve()
        # waves: early minus late tee times, rounds 1-2, per year
        rf = men["rf"]
        wv = rf[(rf["wave"] != "") & (rf["tour"] == "pga")]
        er = wv.groupby(["event", "round", "wave"])["res"].mean().unstack()
        if "am" in er.columns and "pm" in er.columns:
            er = (er["am"] - er["pm"]).dropna().reset_index()
            er = er.merge(men["meta"][["event", "start"]], on="event")
            er["y"] = er["start"].dt.year
            out["waves"] = {"mean": _r(er[0].mean(), 3), "abs": _r(er[0].abs().mean(), 3), "big": int((er[0].abs() >= 1).sum()), "n": int(len(er)),
                            "by_year": [[int(y), _r(g[0].mean(), 3), _r(g[0].abs().mean(), 3)] for y, g in er.groupby("y") if y >= 2005]}
        # scoring by round number: the field's average strokes gained by round (who scores at the weekend)
        out["by_round"] = []
        for key in self.S:
            r = self.S[key]["rf"]
            r = r[r["date"] >= self.t - pd.Timedelta(days=5 * 365)]
            fp = r.groupby(["event", "round"]).agg(fp=("field_par", "first"), st=("strokes", "mean")).reset_index()
            out["by_round"].append({"stream": key, "rows": [[int(k), _r(g["st"].mean() - g["fp"].mean(), 3), int(len(g))] for k, g in fp.groupby("round") if k <= 4]})
        # tours: the average rating of each tour's regulars, the round spread, the field par
        tours = []
        for key in self.S:
            W = self.S[key]["W"]
            for t, g in W[W["q"]].groupby("tour"):
                tours.append({"tour": t, "name": canon.TOURS[t]["name"], "n": int(len(g)), "rt": _r(g["rt"].mean(), 2), "top": _r(g["rt"].quantile(0.9), 2),
                              "sd": _r(g["sd"].mean(), 2)})
        out["tours"] = tours
        # course table (both streams)
        return out

    def _age_curve(self) -> dict | None:
        S = self.S["men"]["Sm"].reset_index()
        S = S[S["rounds"] >= 20]
        dob = {p: (self.bios.get(p) or {}).get("dob") for p in S["pid"].unique()}
        S["age"] = [None if not dob.get(p) else (y + 0.5 - int(dob[p][:4])) for p, y in zip(S["pid"], S["year"])]
        S = S.dropna(subset=["age"])
        if len(S) < 500:
            return None
        S = S.sort_values(["pid", "year"])
        S["prev"] = S.groupby("pid")["sg_raw"].shift()
        S["py"] = S.groupby("pid")["year"].shift()
        S["pn"] = S.groupby("pid")["rounds"].shift()
        d = S[(S["year"] - S["py"]) == 1].copy()
        d["delta"] = d["sg_raw"] - d["prev"]
        d["w"] = 1.0 / (1.0 / d["rounds"] + 1.0 / d["pn"])
        d["a"] = d["age"].round().astype(int)
        g = d.groupby("a").apply(lambda x: pd.Series({"d": float((x["delta"] * x["w"]).sum() / x["w"].sum()), "n": int(len(x))}))
        g = g[(g.index >= 20) & (g.index <= 52) & (g["n"] >= 15)]
        if not len(g):
            return None
        curve = g["d"].cumsum()
        curve = curve - curve.max()
        peak = int(curve.idxmax())
        return {"rows": [[int(a), _r(v, 3), int(g.loc[a, "n"]), _r(g.loc[a, "d"], 3)] for a, v in curve.items()], "peak": peak,
                "pairs": int(g["n"].sum())}

    # ── records ──────────────────────────────────────────────────────────
    def records(self, pages_index: dict, results_by_pid: dict) -> dict:
        out = {}
        for key in self.S:
            d = self.S[key]
            rf, m = d["rf"], d["meta"].set_index("event")
            # a record needs a whole round on file: the two nines add up to the round (partial rounds have no nines)
            full = rf[(rf["out"] + rf["in"] == rf["strokes"]) & (rf["out"] >= 27) & (rf["in"] >= 27)]
            top = full.sort_values("sg", ascending=False).head(25)
            low = []
            for r in top.itertuples():
                low.append({"pid": r.pid, "name": (self.meta_p.get(r.pid) or {}).get("name") or r.pid, "event": r.event,
                            "ev": m.loc[r.event, "name"] if r.event in m.index else None, "y": int(r.date.year), "round": int(r.round),
                            "strokes": _int(r.strokes), "sg": _r(r.sg, 2), "field": _r(r.field_par, 2), "tour": r.tour})
            res = d["res"]
            fin = res[res["status"] == "finish"]
            # winning margins from the totals (rounds summed)
            tot = rf.groupby(["event", "pid"])["strokes"].agg(["sum", "size"]).reset_index()
            margins = []
            for eid, g in fin.groupby("event"):
                w = g[g["pos"] == 1]
                if len(w) != 1:
                    continue
                t = tot[(tot["event"] == eid)]
                mx = t["size"].max()
                t = t[t["size"] == mx].sort_values("sum")
                if len(t) < 2 or t["pid"].iloc[0] != w["pid"].iloc[0]:
                    continue
                margins.append((eid, w["pid"].iloc[0], int(t["sum"].iloc[1] - t["sum"].iloc[0])))
            margins.sort(key=lambda x: -x[2])
            out_m = [{"event": e, "ev": m.loc[e, "name"], "y": int(m.loc[e, "season"]), "pid": p, "name": (self.meta_p.get(p) or {}).get("name") or p,
                      "margin": k, "tour": m.loc[e, "tour"]} for e, p, k in margins[:20]]
            # longest-odds winners: our pre-event chance (the event pages' archive)
            lo = []
            for pid, rows in results_by_pid.items():
                for r in rows:
                    pi = pages_index.get(r[0]) or {}
                    if pi.get("stream") != key or r[3] != 1 or r[5] != "finish" or r[9] is None:
                        continue
                    lo.append({"event": r[0], "ev": pi.get("name"), "y": int(pi.get("season")), "pid": pid,
                               "name": (self.meta_p.get(pid) or {}).get("name") or pid, "p": r[9], "tour": r[1]})
            lo.sort(key=lambda x: x["p"])
            # best seasons
            S = d["Sm"].reset_index()
            S = S[S["rounds"] >= 40].sort_values("sg_raw", ascending=False)
            best = [{"pid": r.pid, "name": (self.meta_p.get(r.pid) or {}).get("name") or r.pid, "y": int(r.year), "sg": _r(r.sg_raw, 2), "rounds": int(r.rounds),
                     "wins": _int(getattr(r, "wins", None))} for r in S.head(25).itertuples()]
            prog = []
            run = -99.0
            for y, g in S.groupby("year"):
                r = g.iloc[0]
                prog.append({"y": int(y), "pid": r["pid"], "name": (self.meta_p.get(r["pid"]) or {}).get("name"), "sg": _r(r["sg_raw"], 2), "record": bool(r["sg_raw"] > run)})
                run = max(run, float(r["sg_raw"]))
            wins = fin[fin["pos"] == 1].groupby("pid").size().sort_values(ascending=False).head(20)
            out[key] = {"low_rounds": low, "margins": out_m, "longshots": lo[:20], "best_seasons": best, "season_best": prog,
                        "most_wins": [{"pid": p, "name": (self.meta_p.get(p) or {}).get("name") or p, "wins": int(k)} for p, k in wins.items()],
                        "from": int(d["meta"]["season"].min())}
        return out
