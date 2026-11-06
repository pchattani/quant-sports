"""The Quant Iron payloads (docs/iron/data). Rebuilt 6 Nov 2026 to the sister sites' depth.

    index.json                 the overview: digest, featured meet, latest meets with our pre-meet chances, power
                               board, stories, who's hot by class, "who's for real", the ranking tops (Home reads it)
    rankings.json              our rating (expected DOTS at the next meet) per stream, with class, 90-day movement and
                               "what a result would do" (the total that takes a lifter to No. 1 and up one place)
    scout/<stream>.json        the Scouting Room pool, column-oriented: every metric of analytics.METRICS
    schedule/<year>.json       that year's meets (compact)
    events/<id>.json           a meet: flights, places, attempts, our pre-meet expectation and podium chance, PRs,
                               who beat the forecast
    players/<id>.json          a lifter: hero, percentiles in the class (and last year's), year by year, splits, the
                               meet log with attempts and meet value, similar lifters
    follow/lifter/<id>.json    My Teams cards (oddsmarkets/common/follow.py)
    lab.json                   attempts, bomb-outs, age curves, class moves, federations, tested split, formulas,
                               lift ratios
    records.json               all-time records per sex, equipment and IPF class with their progressions; all-time and
                               decade lists
    model.json                 the forecast: windows, baselines, variants, paired intervals, calibration, podium
    glossary.json, search.json
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import analytics as A
from . import canon, store
from .models import backtest as BT
from .models import evaluate as EV
from .models import forecast as F
from .models import ratings as R

logger = logging.getLogger(__name__)

MODEL_VERSION = 2
RANK_MIN_MEETS = 3
RANK_ACTIVE_DAYS = 400
RANK_CAP = 3000
WHATIF_TOP = 100
PLAYER_MIN_MEETS = 4
PLAYER_ACTIVE_DAYS = 800
PLAYER_CAP = 6000
MEET_RECENT_DAYS = 400
MEET_BIG_DAYS = 1100
MEET_BIG_N = 40
MEET_CAP = 5000
SCOUT_CAP = {"men_raw": 3000, "women_raw": 3000}
SCOUT_CAP_OTHER = 1500
WINDOW_DAYS = 730
TUNING = Path(__file__).resolve().parent / "models" / "tuning.csv"
CREDIT = ("This page uses data from the OpenPowerlifting project, https://www.openpowerlifting.org. "
          "You may download a copy of the data at https://data.openpowerlifting.org.")
ATT = ["s1", "s2", "s3", "b1", "b2", "b3", "d1", "d2", "d3"]


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def _r(x, k=2):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(v) else round(v, k)


def _int(x):
    v = _r(x, 0)
    return None if v is None else int(v)


def _s(x) -> str:
    """String from a parquet cell: pandas NA / NaN is truthy, so `x or ""` is not enough."""
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except (TypeError, ValueError):
        pass
    return str(x)


def _iso(t) -> str:
    if t is None:
        return ""
    try:
        if pd.isna(t):
            return ""
    except (TypeError, ValueError):
        pass
    return pd.Timestamp(t).date().isoformat()


def _names(entries: pd.DataFrame) -> dict[str, dict]:
    """pid -> {name, country, sex} from the latest row. Zip, not itertuples: `name` is a namedtuple attribute."""
    last = entries.sort_values("date").groupby("pid", as_index=False).tail(1)
    return {pid: {"name": _s(name), "country": _s(country), "sex": _s(sex)}
            for pid, name, country, sex in zip(last["pid"], last["name"], last["country"], last["sex"])}


# ── the build ─────────────────────────────────────────────────────────────────────────────────────────────────
_T0 = [0.0]


def _tick(what: str) -> None:
    import time
    now = time.perf_counter()
    if _T0[0]:
        logger.info("  %.1fs  %s", now - _T0[0], what)
    _T0[0] = now


def build(out: Path, today: date | None = None, full: bool = False) -> dict:
    today = today or date.today()
    T = pd.Timestamp(today)
    entries = store.load_entries()
    _tick('entries = store.load_entries()')
    meets = store.load_meets()
    _tick('meets = store.load_meets()')
    if entries.empty or meets.empty:
        raise RuntimeError("no powerlifting stores: run scripts/pl_fetch.py")
    for c in ATT + ["wilks"]:
        if c not in entries.columns:
            entries[c] = np.nan               # a schema-1 store: attempts and Wilks appear after the next ingest
    scored = R.load_scored(entries)
    _tick('scored = R.load_scored(entries)')
    m0 = R.stream_means(scored, BT.TRAIN_END)
    _tick('m0 = R.stream_means(scored, BT.TRAIN_END')
    p = R.CHOSEN
    walked, books = R.walk(scored, p, m0=m0)
    _tick('walked, books = R.walk(scored, p, m0=m0)')
    logger.info("walked %s starts across %s streams", len(walked), len(books))
    rep, live, ent, models = EV.evaluate(walked, entries, p, m0)
    _tick('rep, live, ent, models = EV.evaluate(wal')
    logger.info("forecast: chosen %s, live %s", rep["chosen"], rep["live"])
    train_model = models[rep["live"]]
    # expected DOTS of every walked start, before the meet: the training fit up to the test end, the live fit after
    exp = np.where(walked["date"] <= BT.TEST_END, train_model.mu(walked), live.mu(walked))
    _tick('exp = np.where(walked["date"] <= BT.TEST')
    walked["exp"] = exp
    names = _names(entries)
    _tick('names = _names(entries)')
    meet_name = dict(zip(meets["meet_id"], meets["name"]))
    meet_fed = dict(zip(meets["meet_id"], meets["fed"]))
    cur = _ratings_at(walked, T, live, p, m0)
    _tick('cur = _ratings_at(walked, T, live, p, m0')
    prev = _ratings_at(walked, T - pd.Timedelta(days=90), live, p, m0)
    _tick('prev = _ratings_at(walked, T - pd.Timede')
    yr = _ratings_at(walked, T - pd.Timedelta(days=365), live, p, m0)
    _tick('yr = _ratings_at(walked, T - pd.Timedelt')
    prof = A.profile(walked, entries, T - pd.Timedelta(days=WINDOW_DAYS), T)
    _tick('prof = A.profile(walked, entries, T - pd')
    prof = prof.merge(cur[["stream", "pid", "rt"]], on=["stream", "pid"], how="left")
    _tick('prof = prof.merge(cur[["stream", "pid", ')
    pct = A.percentiles(prof)
    _tick('pct = A.percentiles(prof)')
    py = today.year - 1
    prof_prev = A.profile(walked, entries, pd.Timestamp(f"{py - 1}-12-31"), pd.Timestamp(f"{py}-12-31"))
    _tick('prof_prev = A.profile(walked, entries, p')
    pct_prev = A.percentiles(prof_prev) if len(prof_prev) else pd.DataFrame()
    _tick('pct_prev = A.percentiles(prof_prev) if l')
    ranks = _rankings(out, cur, prev, yr, books, live, p, m0, names, walked, T)
    _tick('ranks = _rankings(out, cur, prev, yr, bo')
    lab = _lab(out, walked, entries)
    _tick('lab = _lab(out, walked, entries)')
    recs = _records(out, entries, walked, names, meet_name)
    _tick('recs = _records(out, entries, walked, na')
    ppids = _player_pids(walked, ranks, today)
    _tick('ppids = _player_pids(walked, ranks, toda')
    pset = set(ppids)
    for v in ranks["streams"].values():
        for r in v["rows"]:
            r["pg"] = r["pid"] in pset
    _write(out / "rankings.json", ranks)
    _tick('_write(out / "rankings.json", ranks)')
    keep = _meet_pages(out, entries, meets, ent, walked, train_model, live, names, today, pset, rep.get("podium") or {})
    _tick('keep = _meet_pages(out, entries, meets, ')
    n_player = _player_pages(out, ppids, walked, entries, prof, pct, prof_prev, pct_prev, cur, ranks, names,
                             meet_name, meet_fed, T)
    _tick('player pages')
    _scout(out, prof, names, today, pset)
    _tick('_scout(out, prof, names, today, pset)')
    _follow(out, ppids, walked, cur, ranks, names, meet_name, T)
    _tick('_follow(out, ppids, walked, cur, ranks, ')
    _schedule(out, meets, keep)
    _tick('_schedule(out, meets, keep)')
    _model(out, rep, walked, p, m0, live)
    _tick('_model(out, rep, walked, p, m0, live)')
    _index(out, meets, walked, entries, ent, ranks, cur, yr, recs, names, meet_name, train_model, live, rep, today)
    _tick('_index(out, meets, walked, entries, ent,')
    _glossary(out)
    _labels(out, lab)
    _tick('_glossary(out)')
    _search(out, names, meets, ranks, ppids, today)
    _tick('_search(out, names, meets, ranks, ppids,')
    _write(out / "build.json", {"model": MODEL_VERSION, "today": today.isoformat(), "stamp": store.load_stamp().get("etag"),
                                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return {"meets": len(keep), "players": n_player, "entries": int(len(entries)), "scored": int(len(walked))}


# ── ratings on a date ─────────────────────────────────────────────────────────────────────────────────────────
def _ratings_at(walked: pd.DataFrame, at: pd.Timestamp, model: F.Model, p, m0) -> pd.DataFrame:
    """Our rating on `at`: the expected DOTS at a meet that day, from the book as it stood (rows before `at` only)."""
    w = walked[(walked["date"] < at) & walked["scored"]]
    if w.empty:
        return pd.DataFrame(columns=["stream", "pid", "rt", "n", "last", "bw", "sex", "age", "st_s", "st_w", "st_t", "best_dots", "pre"])
    last = w.groupby(["stream", "pid"], sort=False).tail(1)
    fr = last[["stream", "pid", "sex", "bw", "age", "date"]].rename(columns={"date": "last"}).copy()
    fr["age"] = fr["age"] + (at - fr["last"]).dt.days / 365.25
    fr["date"] = at
    st = F.pre_state(fr.reset_index(drop=True), walked[walked["date"] < at], p, m0)
    st["rt"] = model.mu(st)
    return st[["stream", "pid", "rt", "n", "last", "bw", "sex", "age", "st_s", "st_w", "st_t", "best_dots", "pre", "last_dots"]]


def _whatif(rows: pd.DataFrame, targets: np.ndarray, model: F.Model, p, m0, at: pd.Timestamp) -> np.ndarray:
    """The DOTS a meet on `at` must score so the next forecast reaches each target (bisection; NaN if out of reach)."""
    n = len(rows)
    if not n:
        return np.array([])
    f = np.power(0.5, (at - rows["st_t"]).dt.days.clip(lower=0).to_numpy(float) / p.half_life)
    m0v = rows["stream"].map(lambda s: m0.get(s, p.m0)).to_numpy(float)
    s, w = rows["st_s"].to_numpy(float), rows["st_w"].to_numpy(float)
    best = rows["best_dots"].to_numpy(float)

    def after(x):
        d = pd.DataFrame({"stream": rows["stream"].to_numpy(), "n": rows["n"].to_numpy() + 1, "last_dots": x,
                          "best_dots": np.maximum(best, x), "pre": (p.k0 * m0v + s * f + x) / (p.k0 + w * f + 1.0),
                          "age": rows["age"].to_numpy(float), "gap": np.full(n, 180.0)})
        return model.mu(d)

    lo, hi = np.full(n, 50.0), np.full(n, 1000.0)
    ok = after(hi) >= targets
    for _ in range(32):
        mid = (lo + hi) / 2
        up = after(mid) >= targets
        hi = np.where(up, mid, hi)
        lo = np.where(up, lo, mid)
    return np.where(ok, hi, np.nan)


# ── rankings ──────────────────────────────────────────────────────────────────────────────────────────────────
def _rankings(out: Path, cur, prev, yr, books, model, p, m0, names, walked, T) -> dict:
    act = cur[(cur["n"] >= RANK_MIN_MEETS) & ((T - cur["last"]).dt.days <= RANK_ACTIVE_DAYS)].copy()
    act["cls"] = A.ipf_class_vec(act["sex"], act["bw"])
    w12 = walked[walked["scored"] & (walked["date"] > T - pd.Timedelta(days=365))]
    best12 = w12.groupby(["stream", "pid"])["dots"].max()
    n12 = w12.groupby(["stream", "pid"]).size()
    tst = w12.groupby(["stream", "pid"])["tested"].mean()
    # form: the last five scored meets, beat (W) or missed (L) our pre-meet expectation
    ws = walked[walked["scored"] & walked["exp"].notna()].sort_values("date")
    form = ws.assign(f=np.where(ws["dots"] > ws["exp"], "W", "L")).groupby(["stream", "pid"])["f"].agg(lambda s: "".join(s.tail(5)))
    streams = {}
    for key, meta in canon.STREAMS.items():
        d = act[act["stream"] == key].sort_values("rt", ascending=False).head(RANK_CAP).reset_index(drop=True)
        d["rank"] = np.arange(1, len(d) + 1)
        pv = prev[prev["stream"] == key]
        pa = pv[(pv["n"] >= RANK_MIN_MEETS) & ((T - pd.Timedelta(days=90) - pv["last"]).dt.days <= RANK_ACTIVE_DAYS)]
        pa = pa.sort_values("rt", ascending=False).reset_index(drop=True)
        prank = dict(zip(pa["pid"], np.arange(1, len(pa) + 1)))
        prt = dict(zip(pv["pid"], pv["rt"]))
        yrt = dict(zip(yr[yr["stream"] == key]["pid"], yr[yr["stream"] == key]["rt"]))
        # what a result would do, for the top of the table: No. 1, and one place up
        top = d.head(WHATIF_TOP)
        need1 = need_up = np.full(len(top), np.nan)
        if len(top) > 1:
            r1 = float(d["rt"].iloc[0])
            t1 = np.where(top["rank"] == 1, np.nan, r1 + 0.05)
            tu = np.r_[np.nan, top["rt"].to_numpy()[:-1] + 0.05]
            need1 = _whatif(top, np.nan_to_num(t1, nan=0.0), model, p, m0, T)
            need_up = _whatif(top, np.nan_to_num(tu, nan=0.0), model, p, m0, T)
            need1 = np.where(np.isnan(t1), np.nan, need1)
            need_up = np.where(np.isnan(tu), np.nan, need_up)
        rows = []
        for i, r in enumerate(d.itertuples(index=False)):
            info = names.get(r.pid) or {}
            k = canon.dots_coeff(r.sex, r.bw) if r.bw == r.bw else np.nan
            row = {"rank": int(r.rank), "pid": r.pid, "name": info.get("name") or r.pid, "cc": _s(info.get("country")),
                   "rt": _r(r.rt, 1), "n": int(r.n), "last": _iso(r.last), "cls": _s(r.cls), "bw": _r(r.bw, 1),
                   "age": _int(r.age) if r.age == r.age else None,
                   "best12": _r(best12.get((key, r.pid)), 1), "starts12": _int(n12.get((key, r.pid), 0)),
                   "tested": _r(tst.get((key, r.pid)), 2), "form": form.get((key, r.pid), ""),
                   "mv": int(prank[r.pid] - r.rank) if r.pid in prank else None,
                   "d90": _r(r.rt - prt[r.pid], 1) if r.pid in prt else None,
                   "d365": _r(r.rt - yrt[r.pid], 1) if r.pid in yrt else None}
            if i < len(top):
                n1, nu = need1[i], need_up[i]
                row["need1"] = _r(n1 / k, 1) if np.isfinite(n1) and np.isfinite(k) else None
                row["need_up"] = _r(nu / k, 1) if np.isfinite(nu) and np.isfinite(k) else None
                row["need1_dots"] = _r(n1, 1) if np.isfinite(n1) else None
            rows.append(row)
        streams[key] = rows
    obj = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "min_meets": RANK_MIN_MEETS, "active_days": RANK_ACTIVE_DAYS, "unit": "DOTS",
           "classes": {"M": A.class_order("M"), "F": A.class_order("F")},
           "streams": {k: {"label": canon.STREAMS[k]["label"], "rows": streams[k]} for k in canon.STREAMS}}
    _write(out / "rankings.json", obj)
    return obj


# ── lab and records ───────────────────────────────────────────────────────────────────────────────────────────
def _lab(out: Path, walked, entries) -> dict:
    lab = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for k, fn in (("attempts", lambda: A.attempts(entries)), ("bombouts", lambda: A.bombouts(entries)),
                  ("ages", lambda: A.age_curves(walked, entries)), ("moves", lambda: A.class_moves(walked, entries)),
                  ("feds", lambda: A.federations(walked, entries)), ("tested", lambda: A.tested_split(walked)),
                  ("formulas", lambda: A.formulas(entries)), ("ratios", lambda: A.ratios(walked, entries)),
                  ("reliability", lambda: A.reliability(walked, entries))):
        try:
            lab[k] = fn()
        except Exception as exc:  # noqa: BLE001 - one analysis failing must not sink the site
            logger.exception("lab %s failed: %s", k, exc)
            lab[k] = {}
    _write(out / "lab.json", _clean(lab))
    return lab


def _records(out: Path, entries, walked, names, meet_name) -> dict:
    rec = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "records": A.records(entries, names), "all_time": A.all_time(walked, names, meet_name)}
    _write(out / "records.json", _clean(rec))
    return rec


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


# ── meets ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _prev_best_total(walked) -> dict:
    w = walked[walked["scored"]].sort_values("date")
    cm = w.groupby(["stream", "pid"])["total"].cummax()
    pb = cm.groupby([w["stream"], w["pid"]]).shift(1)
    return dict(zip(zip(w["meet_id"], w["pid"], w["stream"]), pb))


def _meet_pages(out: Path, entries, meets, ent, walked, train_model, live, names, today: date, pset: set, pod: dict) -> set[str]:
    cutoff_recent = (today - timedelta(days=MEET_RECENT_DAYS)).isoformat()
    cutoff_big = (today - timedelta(days=MEET_BIG_DAYS)).isoformat()
    pick = meets[(meets["date"] >= cutoff_recent) | ((meets["date"] >= cutoff_big) & (meets["n_sbd"] >= MEET_BIG_N))]
    pick = pick.sort_values("date", ascending=False).head(MEET_CAP)
    keep = set(pick["meet_id"])
    # forecasts and podium chances for the full-power entrants of these meets (pre-state: rows before the meet only)
    e = ent[ent["meet_id"].isin(keep)].copy()
    sims = pd.DataFrame()
    if len(e):
        late = e["date"] > BT.TEST_END
        fc = pd.concat([train_model.forecast(e[~late]), live.forecast(e[late])]).reindex(e.index)
        e["mu"], e["sd"], e["p_bomb"] = fc["mu"], fc["sd"], fc["p_bomb"]
        e["mu_kg"] = F.to_kg(e["sex"], e["bw"], e["mu"].to_numpy(float))
        e["sd_kg"] = F.to_kg(e["sex"], e["bw"], e["sd"].to_numpy(float))
        e = e[np.isfinite(e["mu_kg"])]
        codes = F.flights(e)
        scale = float(pod.get("sd_scale") or 1.0)
        pp, pw = F.simulate_podium(codes, e["mu_kg"].to_numpy(float), e["sd_kg"].to_numpy(float) * scale, e["p_bomb"].to_numpy(float), sims=400)
        e["fsize"] = pd.Series(codes, index=e.index).map(pd.Series(codes).value_counts()).to_numpy()
        frk = e.assign(_f=codes).groupby("_f")["mu_kg"].rank(ascending=False, method="first").to_numpy()
        tab = {(int(a), int(b)): (pp_, pw_) for a, b, pp_, pw_ in (pod.get("rank_table") or [])}
        rk = [tab.get((int(min(n_, 12)), int(min(r_, 12))), (np.nan, np.nan)) for n_, r_ in zip(e["fsize"], frk)]
        p_rank = np.array([x[0] for x in rk], dtype=float)
        w_rank = np.array([x[1] for x in rk], dtype=float)
        fs = e["fsize"].to_numpy(float)
        p_rank = np.where(np.isfinite(p_rank), p_rank, np.minimum(1.0, 3.0 / fs))
        w_rank = np.where(np.isfinite(w_rank), w_rank, 1.0 / fs)
        # the promoted blend (models/evaluate.py podium_report); without promotion the rank table alone
        eps = float(pod.get("eps") or 0.0) if pod.get("promoted") else 1.0
        e["p_pod"] = np.where(fs >= 4, (1 - eps) * pp + eps * p_rank, pp)
        e["p_win"] = np.where(fs >= 4, (1 - eps) * pw + eps * w_rank, pw)
        sims = e
    fmap = {}
    for r in sims.itertuples(index=False):
        fmap[(r.meet_id, r.pid, _s(r.division))] = r
    pb = _prev_best_total(walked)
    sub = entries[entries["meet_id"].isin(keep)]
    by_meet = {mid: g for mid, g in sub.groupby("meet_id", sort=False)}
    dest = out / "events"
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for r in pick.itertuples(index=False):
        rows = by_meet.get(r.meet_id)
        if rows is None:
            continue
        _write(dest / f"{r.meet_id}.json", _meet_payload(r, rows, fmap, pb, pset))
        n += 1
    logger.info("wrote %s meet pages", n)
    for p in dest.glob("*.json"):
        if p.stem not in keep:
            p.unlink()
    return keep


def _att(row) -> list:
    return [_r(getattr(row, c), 1) for c in ATT]


def _meet_payload(m, rows: pd.DataFrame, fmap: dict, pb: dict, pset: set) -> dict:
    board = []
    made = tried = 0
    for e in rows.sort_values(["dots", "total"], ascending=False).itertuples(index=False):
        f = fmap.get((m.meet_id, e.pid, _s(e.division)))
        stream = R.stream_of(e.sex, e.eq)
        prevb = pb.get((m.meet_id, e.pid, stream)) if stream else None
        a = _att(e)
        made += sum(1 for x in a if x is not None and x > 0)
        tried += sum(1 for x in a if x is not None and x != 0)
        exp_kg = _r(f.mu_kg, 1) if f is not None and not f.new else None
        board.append({
            "pid": e.pid, "pg": e.pid in pset, "name": _s(e.name), "sex": _s(e.sex), "eq": _s(e.eq), "equip": _s(e.equipment), "event": _s(e.event),
            "div": _s(e.division), "class": _s(e.wclass), "bw": _r(e.bw, 2), "age": _r(e.age, 1),
            "squat": _r(e.squat, 1), "bench": _r(e.bench, 1), "dead": _r(e.dead, 1), "total": _r(e.total, 1),
            "dots": _r(e.dots, 1), "gl": _r(e.gl, 1), "wilks": _r(e.wilks, 1),
            "place": _s(e.place), "tested": bool(e.tested), "cc": _s(e.country), "a": a,
            "pre": _r(f.mu, 1) if f is not None and not f.new else None, "exp": exp_kg,
            "sd": _r(f.sd_kg, 1) if f is not None and not f.new else None,
            "p_pod": _r(f.p_pod, 3) if f is not None else None, "p_win": _r(f.p_win, 3) if f is not None else None,
            "fsize": int(f.fsize) if f is not None else None, "new": bool(f.new) if f is not None else None,
            "pr": bool(prevb is not None and np.isfinite(prevb) and pd.notna(e.total) and e.total > prevb),
            "prev_best": _r(prevb, 1) if prevb is not None else None,
        })
    return {"id": m.meet_id, "name": _s(m.name), "date": _s(m.date), "fed": _s(m.fed), "parent": _s(m.parent),
            "country": _s(m.country), "state": _s(m.state), "n": int(m.n), "n_sbd": int(m.n_sbd),
            "made": _r(100 * made / tried, 1) if tried else None, "tried": int(tried),
            "board": board, "model": MODEL_VERSION}


# ── lifters ───────────────────────────────────────────────────────────────────────────────────────────────────
def _player_pids(walked, ranks, today: date) -> list[str]:
    w = walked[walked["scored"]]
    last = w.groupby("pid")["date"].max()
    nmeets = w.groupby("pid").size()
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=PLAYER_ACTIVE_DAYS)
    must = []
    for v in ranks["streams"].values():
        must += [r["pid"] for r in v["rows"][:300]]
    pids = [pid for pid, n in nmeets.items() if n >= PLAYER_MIN_MEETS and last[pid] >= cutoff]
    pids = sorted(pids, key=lambda x: (-nmeets[x], -last[x].timestamp()))
    seen, out = set(), []
    for pid in must + pids:
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
        if len(out) >= PLAYER_CAP:
            break
    return out


SIM_KEYS = ["rel_s", "rel_b", "rel_d", "make", "prog", "dots", "cons"]


def _similar(prof: pd.DataFrame, pct: pd.DataFrame, pids: set) -> dict:
    """The five lifters nearest on the class percentiles of SIM_KEYS, within the same stream and class."""
    P = pct[SIM_KEYS].to_numpy(dtype=float)
    out = {}
    for (s, c), idx in prof.groupby(["stream", "cls"]).groups.items():
        idx = np.asarray(list(idx))
        X = P[idx]
        mine = [i for i, pid in zip(idx, prof.loc[idx, "pid"]) if pid in pids]
        for i in mine:
            x = P[i]
            ok = np.isfinite(x)
            if ok.sum() < 4:
                continue
            d = np.nanmean(np.abs(X[:, ok] - x[ok]), axis=1)
            d[idx == i] = np.inf
            order = np.argsort(d)[:5]
            out[(s, prof.at[i, "pid"])] = [(prof.at[idx[j], "pid"], float(d[j])) for j in order if np.isfinite(d[j])]
    return out


def _player_pages(out: Path, pids, walked, entries, prof, pct, prof_prev, pct_prev, cur, ranks, names, meet_name, meet_fed, T) -> int:
    keep = set(pids)
    dest = out / "players"
    dest.mkdir(parents=True, exist_ok=True)
    w = walked[walked["pid"].isin(keep)].sort_values("date")
    e = entries[entries["pid"].isin(keep) & (entries["event"] == "SBD")]
    ecols = ["meet_id", "pid", "squat", "bench", "dead", "gl", "wilks", "place", "division", "wclass", "equipment"] + ATT
    w = w.merge(e[ecols].drop_duplicates(["meet_id", "pid"]), on=["meet_id", "pid"], how="left")
    A9 = w[ATT].to_numpy(dtype=float)
    w["made9"] = (A9 > 0).sum(axis=1)
    w["tried9"] = (np.isfinite(A9) & (A9 != 0)).sum(axis=1)
    w["fed"] = w["meet_id"].map(meet_fed).fillna("")
    bombs = entries[entries["pid"].isin(keep) & (entries["event"] == "SBD") & entries["total"].isna()]
    by_pid = {pid: g for pid, g in w.groupby("pid", sort=False)}
    bomb_by = {pid: g for pid, g in bombs.groupby("pid", sort=False)}
    pidx = {(s, pid): i for i, (s, pid) in enumerate(zip(prof["stream"], prof["pid"]))}
    pidx_prev = {(s, pid): i for i, (s, pid) in enumerate(zip(prof_prev["stream"], prof_prev["pid"]))} if len(prof_prev) else {}
    curx = {(s, pid): r for s, pid, r in zip(cur["stream"], cur["pid"], cur.itertuples(index=False))}
    rk = {}
    for key, v in ranks["streams"].items():
        for r in v["rows"]:
            rk[(key, r["pid"])] = (r["rank"], len(v["rows"]), r)
    sim = _similar(prof, pct, keep)
    clsn = prof.groupby(["stream", "cls"]).size().to_dict()
    for pid in pids:
        g = by_pid.get(pid)
        if g is None or g.empty:
            continue
        info = names.get(pid) or {}
        sc = g[g["scored"]]
        main = (sc if len(sc) else g).iloc[-1]
        stream = main["stream"]
        cx = curx.get((stream, pid))
        i = pidx.get((stream, pid))
        cur_blk = None
        if i is not None:
            row = prof.iloc[i]
            cur_blk = {"v": {k: _r(row.get(k), 3) for k in A.METRIC_IDS if _r(row.get(k), 3) is not None},
                       "pc": {k: _r(pct.iloc[i].get(k), 1) for k in A.METRIC_IDS if _r(pct.iloc[i].get(k), 1) is not None},
                       "n": int(row["meets"]), "from": _iso(row["first"]), "cls": _s(row["cls"]),
                       "peers": int(clsn.get((stream, row["cls"]), 0))}
        j = pidx_prev.get((stream, pid))
        prev_blk = None
        if j is not None and len(pct_prev):
            prev_blk = {"y": T.year - 1, "pc": {k: _r(pct_prev.iloc[j].get(k), 1) for k in A.METRIC_IDS
                                                 if _r(pct_prev.iloc[j].get(k), 1) is not None}}
        log = []
        for r in g.itertuples(index=False):
            k = canon.dots_coeff(r.sex, r.bw)
            log.append({"date": _iso(r.date), "meet": r.meet_id, "mn": _s(meet_name.get(r.meet_id)), "fed": _s(meet_fed.get(r.meet_id)),
                        "st": r.stream, "bw": _r(r.bw, 1), "cls": A.ipf_class(r.sex, r.bw) or "", "div": _s(r.division),
                        "sq": _r(r.squat, 1), "bp": _r(r.bench, 1), "dl": _r(r.dead, 1), "tot": _r(r.total, 1),
                        "dots": _r(r.dots, 1), "gl": _r(r.gl, 1), "wilks": _r(r.wilks, 1), "pl": _s(r.place),
                        "exp": _r(r.exp, 1), "exp_kg": _r(r.exp / k, 1) if r.exp == r.exp and k else None,
                        "a": [_r(getattr(r, c), 1) for c in ATT], "t": bool(r.tested), "sc": bool(r.scored)})
        bg = bomb_by.get(pid)
        for r in (bg.itertuples(index=False) if bg is not None else []):
            log.append({"date": _s(r.date), "meet": r.meet_id, "mn": _s(meet_name.get(r.meet_id)), "fed": _s(meet_fed.get(r.meet_id)),
                        "st": R.stream_of(r.sex, r.eq) or "", "bw": _r(r.bw, 1), "cls": A.ipf_class(r.sex, r.bw) or "",
                        "div": _s(r.division), "sq": _r(r.squat, 1), "bp": _r(r.bench, 1), "dl": _r(r.dead, 1), "tot": None,
                        "dots": None, "pl": "DQ", "a": [_r(getattr(r, c), 1) for c in ATT], "t": bool(r.tested), "sc": False, "bomb": True})
        log.sort(key=lambda x: x["date"])
        # PR flags along the main stream
        best = -1.0
        for x in log:
            if x["st"] == stream and x.get("tot") is not None:
                x["pr"] = x["tot"] > best and best > 0
                best = max(best, x["tot"])
        ms = sc[sc["stream"] == stream]
        recs = ms[["date", "total", "squat", "bench", "dead", "dots", "gl", "wilks", "bw", "exp", "tested", "fed", "made9", "tried9"]].to_dict("records")
        seasons = []
        by_y: dict = {}
        for x in recs:
            by_y.setdefault(x["date"].year, []).append(x)
        for y in sorted(by_y):
            seasons.append(_season(y, by_y[y], main["sex"]))
        splits = []
        for lab, sel in (("Tested meets", [x for x in recs if x["tested"]]), ("Untested meets", [x for x in recs if not x["tested"]])):
            if sel:
                splits.append(_split(lab, sel))
        by_f: dict = {}
        for x in recs:
            by_f.setdefault(x["fed"], []).append(x)
        for fed in sorted(by_f, key=lambda k: -len(by_f[k])):
            if len(by_f[fed]) >= 2:
                splits.append(_split(f"In {fed}", by_f[fed]))
        if len(recs) >= 6:
            splits.append(_split("Last 3 meets", recs[-3:]))
            splits.append(_split("Earlier meets", recs[:-3]))
        rkx = rk.get((stream, pid))
        simrows = [{"pid": q, "n": (names.get(q) or {}).get("name", q), "cc": (names.get(q) or {}).get("country", ""), "d": _r(dd, 1), "pg": q in keep}
                   for q, dd in sim.get((stream, pid), [])]
        feds = pd.Series([x["fed"] for x in recs]).value_counts() if recs else pd.Series(dtype=int)
        _write(dest / f"{pid}.json", _clean({
            "pid": pid, "name": info.get("name") or pid, "cc": info.get("country") or "", "sex": main["sex"],
            "eq": main["eq"], "stream": stream, "cls": A.ipf_class(main["sex"], main["bw"]) or "", "bw": _r(main["bw"], 1),
            "age": _r(cx.age, 0) if cx is not None and cx.age == cx.age else None,
            "rt": _r(cx.rt, 1) if cx is not None else None,
            "rank": rkx[0] if rkx else None, "of": rkx[1] if rkx else None,
            "mv": rkx[2].get("mv") if rkx else None, "d365": rkx[2].get("d365") if rkx else None,
            "need1": rkx[2].get("need1") if rkx else None, "need_up": rkx[2].get("need_up") if rkx else None,
            "n": int(len(ms)), "first": _iso(ms["date"].min()) if len(ms) else "", "last": _iso(ms["date"].max()) if len(ms) else "",
            "best": _r(ms["dots"].max(), 1), "best_total": _r(ms["total"].max(), 1),
            "best_sq": _r(ms["squat"].max(), 1), "best_bp": _r(ms["bench"].max(), 1), "best_dl": _r(ms["dead"].max(), 1),
            "fed": _s(feds.index[0]) if len(feds) else "", "tested": _r(ms["tested"].mean(), 2) if len(ms) else None,
            "cur": cur_blk, "prev": prev_blk, "seasons": seasons, "splits": splits, "similar": simrows,
            "log": log[-80:], "model": MODEL_VERSION,
        }))
    for f in dest.glob("*.json"):
        if f.stem not in keep:
            f.unlink()
    logger.info("wrote %s lifter pages", len(pids))
    return len(pids)


def _agg(rows: list, key: str, fn):
    v = [x[key] for x in rows if x[key] is not None and x[key] == x[key]]
    return fn(v) if v else None


def _season(y, rows: list, sex) -> dict:
    tried = sum(x["tried9"] for x in rows)
    bw = float(np.median([x["bw"] for x in rows]))
    vals = [x["dots"] - x["exp"] for x in rows if x["exp"] == x["exp"] and x["exp"] is not None]
    return {"y": int(y), "n": len(rows), "tot": _r(_agg(rows, "total", max), 1), "sq": _r(_agg(rows, "squat", max), 1),
            "bp": _r(_agg(rows, "bench", max), 1), "dl": _r(_agg(rows, "dead", max), 1), "dots": _r(_agg(rows, "dots", max), 1),
            "gl": _r(_agg(rows, "gl", max), 1), "wilks": _r(_agg(rows, "wilks", max), 1), "bw": _r(bw, 1),
            "cls": A.ipf_class(sex, bw) or "", "made": _r(100 * sum(x["made9"] for x in rows) / tried, 1) if tried else None,
            "val": _r(float(np.mean(vals)), 1) if vals else None}


def _split(label, rows: list) -> dict:
    tried = sum(x["tried9"] for x in rows)
    vals = [x["dots"] - x["exp"] for x in rows if x["exp"] == x["exp"] and x["exp"] is not None]
    return {"label": label, "n": len(rows), "dots": _r(_agg(rows, "dots", lambda v: sum(v) / len(v)), 1),
            "best": _r(_agg(rows, "dots", max), 1), "tot": _r(_agg(rows, "total", max), 1),
            "made": _r(100 * sum(x["made9"] for x in rows) / tried, 1) if tried else None,
            "val": _r(float(np.mean(vals)), 1) if vals else None}


# ── the Scouting Room ─────────────────────────────────────────────────────────────────────────────────────────
def _scout(out: Path, prof: pd.DataFrame, names: dict, today: date, pset: set) -> None:
    T = pd.Timestamp(today)
    cols = ["id", "n", "cc", "cls", "age", "bw", "tested", "last", "pg"] + A.METRIC_IDS
    metrics = [{"id": m[0], "label": m[1], "short": m[2], "family": m[3], "dir": m[4], "unit": m[5], "tip": m[6]} for m in A.METRICS]
    for key in canon.STREAMS:
        d = prof[(prof["stream"] == key) & ((T - prof["last"]).dt.days <= RANK_ACTIVE_DAYS) & prof["rt"].notna()]
        d = d.sort_values("rt", ascending=False).head(SCOUT_CAP.get(key, SCOUT_CAP_OTHER))
        rows = []
        for r in d.itertuples(index=False):
            info = names.get(r.pid) or {}
            row = [r.pid, info.get("name") or r.pid, _s(info.get("country")), _s(r.cls), _int(r.age), _r(r.bw, 1),
                   _r(r.tested, 2), _iso(r.last), r.pid in pset]
            for k in A.METRIC_IDS:
                v = getattr(r, k, None)
                row.append(_r(v, 3 if k in ("rel", "rel_s", "rel_b", "rel_d") else 1))
            rows.append(row)
        sx = "M" if key.startswith("men") else "F"
        _write(out / "scout" / f"{key}.json", {"stream": key, "label": canon.STREAMS[key]["label"], "cols": cols, "rows": rows,
                                               "metrics": metrics, "classes": A.class_order(sx), "window_days": WINDOW_DAYS,
                                               "from": (today - timedelta(days=WINDOW_DAYS)).isoformat(), "cap": len(rows)})


# ── follow cards ──────────────────────────────────────────────────────────────────────────────────────────────
def _follow(out: Path, pids, walked, cur, ranks, names, meet_name, T) -> None:
    try:
        from oddsmarkets.common import follow as FL
    except Exception as exc:  # noqa: BLE001
        logger.warning("follow cards skipped: %s", exc)
        return
    rk = {}
    for key, v in ranks["streams"].items():
        for r in v["rows"]:
            rk[(key, r["pid"])] = (r, len(v["rows"]))
    w = walked[walked["pid"].isin(set(pids)) & walked["scored"]].sort_values("date")
    curx = {(s, p): r for s, p, r in zip(cur["stream"], cur["pid"], cur.itertuples(index=False))}
    cards = {}
    for pid, g in w.groupby("pid", sort=False):
        last = g.iloc[-1]
        stream = last["stream"]
        gs = g[g["stream"] == stream]
        info = names.get(pid) or {}
        nm = info.get("name") or pid
        r = rk.get((stream, pid))
        cx = curx.get((stream, pid))
        form = "".join("W" if (x > e) else "L" for x, e in zip(gs["dots"], gs["exp"]) if e == e)[-5:]
        now = {"form": form}
        if cx is not None and cx.rt == cx.rt:
            now["rating"] = {"value": round(float(cx.rt), 1), "text": f"{cx.rt:.1f}", "label": "Our rating (DOTS)"}
            if r:
                now["rating"]["rank"], now["rating"]["of"] = r[0]["rank"], r[1]
                now["standing"] = {"pos": r[0]["rank"], "of": r[1], "text": f"No. {r[0]['rank']} of {r[1]} in our {canon.STREAMS[stream]['label']} rankings"}
        facts = []
        facts.append({"kind": "rating", "text": f"Best total {gs['total'].max():.1f} kg, best DOTS {gs['dots'].max():.1f}, over {len(gs)} meets in our data."})
        if last["exp"] == last["exp"]:
            d = last["dots"] - last["exp"]
            facts.append({"kind": "form_xp", "text": f"Last time out ({_s(meet_name.get(last['meet_id']))}): {last['total']:.1f} kg, "
                                                     f"{abs(d):.1f} DOTS {'above' if d >= 0 else 'below'} our expectation."})
        if r and r[0].get("d365") is not None:
            facts.append({"kind": "rating_move", "text": f"Our rating is {r[0]['d365']:+.1f} DOTS on a year ago."})
        if len(facts) < 3:
            facts.append({"kind": "split", "text": f"First scored meet in our data: {_iso(gs['date'].min())}."})
        try:
            cards[pid] = FL.make_card(
                site="iron", sport="powerlifting", scope="lifter", ident=pid,
                team={"name": nm, "short": nm.split(" ")[-1] if nm else nm, "abbr": _s(info.get("country"))[:3].upper(),
                      "href": f"#/player/{pid}", "league": canon.STREAMS[stream]["label"], "group": A.ipf_class(last["sex"], last["bw"]) or ""},
                asof=datetime.now(timezone.utc), phase="season", season=T.year, now=now,
                next_note="Powerlifting meets are not announced in our data: results appear after the meet.",
                last={"id": last["meet_id"], "start": _iso(last["date"]), "comp": _s(meet_name.get(last["meet_id"])),
                      "href": f"#/event/{last['meet_id']}", "res": "W" if (last["exp"] == last["exp"] and last["dots"] > last["exp"]) else "L"},
                line=f"{last['total']:.1f} kg at {_s(meet_name.get(last['meet_id']))} on {_iso(last['date'])}.",
                facts=facts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("follow card %s: %s", pid, exc)
    FL.write_cards(out / "follow", "lifter", cards)


# ── schedule, model, overview, glossary, search ───────────────────────────────────────────────────────────────
def _schedule(out: Path, meets: pd.DataFrame, keep: set[str]) -> None:
    meets = meets.copy()
    meets["year"] = meets["date"].str.slice(0, 4)
    dest = out / "schedule"
    dest.mkdir(parents=True, exist_ok=True)
    years = sorted(meets["year"].unique())[-8:]
    for y in years:
        rows = []
        for r in meets[meets["year"] == y].sort_values("date", ascending=False).itertuples(index=False):
            rows.append({"id": r.meet_id, "date": _s(r.date), "name": _s(r.name), "fed": _s(r.fed),
                         "country": _s(r.country), "n": int(r.n), "n_sbd": int(r.n_sbd), "page": r.meet_id in keep})
        _write(dest / f"{y}.json", {"year": int(y), "meets": rows})
    _write(dest / "years.json", {"years": [int(y) for y in years]})


def _model(out: Path, rep: dict, walked, p, m0, live: F.Model) -> None:
    grid = []
    if TUNING.exists():
        for r in pd.read_csv(TUNING).itertuples(index=False):
            grid.append({c: (_int(getattr(r, c)) if c == "test_n" else _r(getattr(r, c), 4)) for c in r._fields})
    _write(out / "model.json", _clean({
        "version": MODEL_VERSION, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": {"half_life": p.half_life, "k0": p.k0, "min_field": p.min_field, "unit": "DOTS",
                   "m0": {k: round(v, 1) for k, v in m0.items()}},
        "windows": {"train": f"to {BT.TRAIN_END}", "valid": f"{BT.TRAIN_END[:4]}-12-31 to {BT.VALID_END}",
                    "test": f"{BT.VALID_END} to {BT.TEST_END}"},
        "report": rep, "live": live.to_json(), "grid": grid,
        "coverage": {"scored": int(len(walked)), "lifters": int(walked["pid"].nunique()),
                     "meets": int(walked["meet_id"].nunique()), "from": _iso(walked["date"].min()),
                     "to": _iso(walked["date"].max())},
        "credit": CREDIT,
    }))


def _index(out: Path, meets, walked, entries, ent, ranks, cur, yr, recs, names, meet_name, train_model, live, rep, today: date) -> None:
    T = pd.Timestamp(today)
    recent = meets.sort_values("date", ascending=False).head(12)
    tops = {k: [{kk: r.get(kk) for kk in ("rank", "pid", "name", "cc", "rt", "cls", "mv")} for r in v["rows"][:10]]
            for k, v in ranks["streams"].items()}
    t = rep["variants"][rep["live"]]["test"]
    # the digest: the last 14 days of results in the archive
    last_day = pd.Timestamp(walked["date"].max())
    since = last_day - pd.Timedelta(days=13)
    wd = walked[(walked["date"] >= since)]
    ed = entries[(pd.to_datetime(entries["date"]) >= since) & (entries["event"] == "SBD")]
    hist = wd[wd["exp"].notna()]
    pb = _prev_best_total(walked)
    prs = [k for k in zip(wd["meet_id"], wd["pid"], wd["stream"], wd["total"]) if pb.get(k[:3]) == pb.get(k[:3]) and pb.get(k[:3]) is not None and k[3] > pb.get(k[:3])]
    over = hist.assign(v=hist["dots"] - hist["exp"]).sort_values("v", ascending=False).head(1)
    topd = wd.sort_values("dots", ascending=False).head(1)
    digest = {"from": _iso(since), "to": _iso(last_day), "meets": int(wd["meet_id"].nunique()), "lifters": int(wd["pid"].nunique()),
              "prs": len(prs), "bombs": int((ed["place"].astype(str) == "DQ").sum()), "entries": int(len(ed)),
              "mae": _r((hist["dots"] - hist["exp"]).abs().mean(), 1), "n_fc": int(len(hist))}
    if len(over):
        o = over.iloc[0]
        digest["over"] = {"pid": o["pid"], "name": (names.get(o["pid"]) or {}).get("name", o["pid"]), "v": _r(o["dots"] - o["exp"], 1),
                          "dots": _r(o["dots"], 1), "meet": o["meet_id"], "mn": _s(meet_name.get(o["meet_id"]))}
    if len(topd):
        o = topd.iloc[0]
        digest["top"] = {"pid": o["pid"], "name": (names.get(o["pid"]) or {}).get("name", o["pid"]), "dots": _r(o["dots"], 1),
                         "total": _r(o["total"], 1), "stream": o["stream"], "meet": o["meet_id"], "mn": _s(meet_name.get(o["meet_id"]))}
    # latest meets with our pre-meet chances (results only: OpenPowerlifting publishes no entry lists)
    latest = []
    lm = meets[(meets["n_sbd"] >= 8) & (meets["date"] <= today.isoformat())].sort_values("date", ascending=False).head(40)
    ev_dir = out / "events"
    for r in lm.itertuples(index=False):
        f = ev_dir / f"{r.meet_id}.json"
        if not f.exists():
            continue
        ev = json.loads(f.read_text(encoding="utf-8"))
        b = [x for x in ev["board"] if x.get("event") == "SBD" and x.get("dots") is not None]
        if not b:
            continue
        b.sort(key=lambda x: -x["dots"])
        fav = sorted([x for x in ev["board"] if x.get("p_win") is not None and (x.get("fsize") or 0) >= 4], key=lambda x: -(x["p_win"] or 0))
        latest.append({"id": r.meet_id, "name": _s(r.name), "date": _s(r.date), "fed": _s(r.fed), "country": _s(r.country),
                       "n": int(r.n_sbd), "best": {k: b[0].get(k) for k in ("pid", "name", "dots", "total", "class", "sex", "pre", "p_win")},
                       "fav": {k: fav[0].get(k) for k in ("pid", "name", "p_win", "class", "place", "dots")} if fav else None,
                       "prs": sum(1 for x in ev["board"] if x.get("pr")), "made": ev.get("made")})
        if len(latest) >= 9:
            break
    featured = max(latest[:6], key=lambda x: x["n"]) if latest else None
    # power board: top 16 per stream, the rating split by lift shares of the best total
    w12 = walked[walked["scored"] & (walked["date"] > T - pd.Timedelta(days=365))]
    lifts = entries[["meet_id", "pid", "squat", "bench", "dead"]].drop_duplicates(["meet_id", "pid"])
    power = {}
    for key, v in ranks["streams"].items():
        rows = v["rows"][:16]
        pids = [r["pid"] for r in rows]
        sub = w12[(w12["stream"] == key) & w12["pid"].isin(pids)].merge(lifts, on=["meet_id", "pid"], how="left")
        bi = sub.loc[sub.groupby("pid")["total"].idxmax()].set_index("pid") if len(sub) else pd.DataFrame()
        out_rows = []
        for r in rows:
            parts = {}
            if len(bi) and r["pid"] in bi.index:
                b = bi.loc[r["pid"]]
                tot = (b["squat"] or 0) + (b["bench"] or 0) + (b["dead"] or 0)
                if tot and np.isfinite(tot) and r["rt"] is not None:
                    parts = {k: _r(r["rt"] * b[c] / tot, 1) for k, c in (("s", "squat"), ("b", "bench"), ("d", "dead"))}
            out_rows.append({**{k: r.get(k) for k in ("rank", "pid", "name", "cc", "rt", "cls", "mv", "d90", "best12", "form", "starts12")},
                             "parts": parts})
        power[key] = out_rows
    # stories: risers and fallers over a year (ranked lifters), records set in the last 180 days, the biggest PRs
    stories = []
    for key in ("men_raw", "women_raw"):
        rows = [r for r in ranks["streams"][key]["rows"][:500] if r.get("d365") is not None]
        if rows:
            up = max(rows, key=lambda r: r["d365"])
            dn = min(rows, key=lambda r: r["d365"])
            stories.append({"kind": "riser", "stream": key, **{k: up.get(k) for k in ("pid", "name", "rt", "d365", "rank", "cls")}})
            stories.append({"kind": "faller", "stream": key, **{k: dn.get(k) for k in ("pid", "name", "rt", "d365", "rank", "cls")}})
    recent_recs = []
    cut = (today - timedelta(days=180)).isoformat()
    for rk, rv in recs["records"].items():
        if not (rk.endswith("raw") or rk.endswith("singleply")):
            continue
        for c in rv["classes"]:
            for lift, L in c["lifts"].items():
                if L["date"] >= cut:
                    prev = L["steps"][-2]["kg"] if len(L["steps"]) > 1 else None
                    recent_recs.append({"set": rk, "label": rv["label"], "cls": c["cls"], "lift": lift, "kg": L["kg"], "prev": prev,
                                        "pid": L["pid"], "name": L["name"], "date": L["date"]})
    recent_recs.sort(key=lambda x: x["date"], reverse=True)
    stories += [{"kind": "record", **x} for x in recent_recs[:3]]
    # who's hot: the top-rated lifter of each class (men and women raw)
    hot = {}
    for key in ("men_raw", "women_raw"):
        sx = "M" if key.startswith("men") else "F"
        rows = ranks["streams"][key]["rows"]
        hot[key] = []
        for c in A.class_order(sx):
            cl = [r for r in rows if r.get("cls") == c]
            if cl:
                hot[key].append({"cls": c, **{k: cl[0].get(k) for k in ("pid", "name", "rt", "cc", "best12")},
                                 "next": {k: cl[1].get(k) for k in ("name", "rt")} if len(cl) > 1 else None})
    # who's for real: rating against the share of meets above expectation, the top 80 men and women raw
    ws = walked[walked["scored"] & walked["exp"].notna() & (walked["date"] > T - pd.Timedelta(days=WINDOW_DAYS))]
    beat = ws.assign(b=(ws["dots"] > ws["exp"]).astype(float)).groupby(["stream", "pid"])["b"].agg(["sum", "size"])
    real = {}
    for key in ("men_raw", "women_raw"):
        pts = []
        for r in ranks["streams"][key]["rows"][:80]:
            b = beat.loc[(key, r["pid"])] if (key, r["pid"]) in beat.index else None
            if b is not None and b["size"] >= 2:
                pts.append({"pid": r["pid"], "name": r["name"], "rt": r["rt"], "beat": _r(100 * (b["sum"] + 2) / (b["size"] + 4), 1), "n": int(b["size"])})
        real[key] = pts
    _write(out / "index.json", _clean({
        "site": "The Quant Iron",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(), "data_to": _iso(last_day),
        "model": {"rmse": _r(t.get("rmse"), 1), "r": _r(t.get("r"), 3), "n": t.get("n"), "unit": "DOTS",
                  "rmse_last": _r(rep["variants"]["last"]["test"].get("rmse"), 1)},
        "recent": [{"id": r.meet_id, "date": _s(r.date), "name": _s(r.name), "fed": _s(r.fed),
                    "country": _s(r.country), "n": int(r.n)} for r in recent.itertuples(index=False)],
        "top": tops, "streams": {k: v["label"] for k, v in canon.STREAMS.items()},
        "counts": {"meets": int(len(meets)), "lifters": int(len(names)), "scored": int(len(walked))},
        "digest": digest, "featured": featured, "latest": latest, "power": power, "stories": stories, "hot": hot, "real": real,
    }))


GLOSSARY = [
    ("Our rating", "The DOTS we expect at the lifter's next full-power meet if it were held today: the last meet, adjusted for what the training years say about lifters at the same stage (meets so far, age, time away) and for how the last meet compares with their longer-run level and best."),
    ("DOTS", "A total adjusted for bodyweight (Konertz, 2019): total x 500 / a fourth-degree polynomial of bodyweight. Lets a 60 kg and a 120 kg lifter be compared on one scale."),
    ("IPF GL", "The IPF's own bodyweight formula (Goodlift points, 2020), used for best-lifter awards at IPF meets."),
    ("Wilks", "The older bodyweight formula (Wilks, revised 2020); some federations still rank by it."),
    ("Stream", "A ranking pool: men or women, raw (sleeves only), wraps (knee wraps allowed) or equipped (single-ply, multi-ply or unlimited suits and shirts)."),
    ("IPF class", "The weight class from the bodyweight on the day, on the IPF's 2019 classes (men 59 to 120+ kg, women 47 to 84+ kg), whatever class the federation used."),
    ("Expected total", "Our pre-meet expected DOTS turned into kilos at the bodyweight on the day. Built only from meets before this one."),
    ("Meet value", "Actual DOTS minus our pre-meet expectation: how much better (or worse) than expected the lifter did."),
    ("Podium chance", "How often the lifter finished in the top three of the flight (same meet, division, class and equipment) when we simulated the flight 400 times from our expectations, with the chance of bombing out."),
    ("Bomb-out", "A full-power meet without a total: three missed attempts on one lift (or a disqualification). OpenPowerlifting marks it DQ."),
    ("Attempts made", "The share of attempts that counted. Each lifter gets three attempts per lift; misses are negative in the archive."),
    ("Third-attempt jump", "The step from a made second attempt to the third, as a share of the second."),
    ("Thin record", "Fewer than five scored meets behind a rating: read it with care."),
    ("Tested", "A meet run under drug testing by the federation (OpenPowerlifting's Tested flag)."),
    ("Percentile", "Where a lifter sits among the active lifters of the same stream and IPF class (two or more meets in two years): 90 means better than 90 in 100. For a lower-is-better metric the percentile is turned so higher is better; for a style (lift shares, jump size) it is only a position."),
    ("PR", "A personal record: a total above the lifter's best before this meet, in the same stream."),
    ("Sealed test", "The years 2023 to 2025, scored once with a model fitted on 1990 to 2019 and chosen on 2020 to 2022."),
]


HEADLINE = ("rt", "dots", "total", "squat", "bench", "dead", "make", "beat", "prog")


def _labels(out: Path, lab: dict) -> None:
    """The kit's metric catalogue for the Scouting Room board (QK.spec, read from data/ via QK.spec.base): the kit
    labels format (scripts/design_kit.py labels), written here because Iron is not in the kit's SITE_SPORT yet.
    Each explanation carries the metric's year-to-year and predictive correlations (analytics.reliability)."""
    rel = lab.get("reliability") or {}
    m = {}
    for i, (mid, label, short, fam, d, unit, tip) in enumerate(A.METRICS, 1):
        r = rel.get(mid)
        ex = tip + (f" Year to year it repeats at r = {r['yoy_r']:.2f}; with next year's best DOTS, r = {r['pred_r']:.2f}." if r else "")
        m[mid] = [label, unit, "higher" if d == "style" else d, "h" if mid in HEADLINE else "s", i, 1 if d == "style" else 0, ex,
                  short[:12], "" if unit in ("DOTS", "GL", "Wilks") else unit]
    _write(out / "powerlifting.labels.json", {
        "sport": "powerlifting", "generated": date.today().isoformat(),
        "ours": {"models": {"forecast": {"name": "Iron forecast", "about": "The DOTS we expect at the lifter's next meet, and how lifters do against it."}},
                 "metrics": {"rt": "forecast", "beat": "forecast", "value": "forecast"}},
        "m": {"player": m},
        "groups": [{"id": "lifters", "display": "Lifters", "entity": "player", "headline": [x for x in A.METRIC_IDS if x in HEADLINE],
                    "field": "cls", "codes": A.class_order("M") + A.class_order("F"), "min": {"field": "meets", "value": 2, "unit": "meets"}}],
    })


def _glossary(out: Path) -> None:
    _write(out / "glossary.json", {"ok": True, "terms": [{"t": t, "d": d} for t, d in GLOSSARY]})


def _search(out: Path, names: dict, meets: pd.DataFrame, ranks, ppids, today: date) -> None:
    seen = set()
    players = []
    pset = set(ppids)
    for v in ranks["streams"].values():
        for r in v["rows"]:
            if r["pid"] in seen or r["pid"] not in pset:
                continue
            seen.add(r["pid"])
            players.append([r["pid"], r["name"], _s(r.get("cc"))])
    for pid in ppids:
        if pid not in seen:
            seen.add(pid)
            info = names.get(pid) or {}
            players.append([pid, info.get("name") or pid, _s(info.get("country"))])
    cutoff = (today - timedelta(days=MEET_RECENT_DAYS)).isoformat()
    events = [[r.meet_id, _s(r.name), _s(r.date), _s(r.fed)]
              for r in meets[meets["date"] >= cutoff].sort_values("date", ascending=False).itertuples(index=False)]
    _write(out / "search.json", {"players": players[:6000], "events": events[:1500]})
