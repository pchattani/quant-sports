"""
The Quant Green's payloads (docs/green/data), from the season stores (store.py) and the models.

    index.json                     this week's events per tour (live or next) with our favourites, the latest
                                   winners, the rankings' top ten and the seasons on file
    rankings.json                  men (PGA Tour, DP World Tour, LIV on one scale) and women (LPGA): our rating in
                                   strokes per round against an average PGA (LPGA) Tour player, with form and 12 months'
                                   results
    schedule/<tour>/<season>.json  the season's events: dates, course, purse, winner, our pre-event favourite
    events/<id>.json               an event: leaderboard by round, our pre-event chances (win, top 5/10/20, cut) beside
                                   the finish, strokes gained per round, live chances while it is under way, and the
                                   holes' scoring (one-course events with hole-by-hole scores)
    players/<id>.json              a player: rating history, every event with our pre-event chance, season lines
    model.json                     parameters, the tuning grid, the sealed test and calibration
    search.json                    players and events for the search box
    power.json, power/<men|women>.json   the power rankings (oddsmarkets/common/power.py), written after the payloads by
                                   power_build.py (scripts/build_green.py): the top 100 per stream by our rating, one
                                   snapshot per completed event week (the last is now), the men's strokes-gained
                                   categories and the LPGA's scoring splits as the groups

Every chance is what the model said before the event, from ratings walked forward with nothing from the event or
after it (models/ratings.py). A final event's page is written once per MODEL_VERSION and kept (CI restores it from the
live site), so the archive's simulations run once.
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import canon, store
from . import depth as DP
from .models import backtest as BT
from .models import ratings as R
from .models import sim

logger = logging.getLogger(__name__)

MODEL_VERSION = 2            # 6 Nov 2026: Korn Ferry rounds in the men's walk, partial rounds out (models/promotion.json)
STREAMS = {"men": ("pga", "eur", "liv", "ntw"), "women": ("lpga",)}
CENTRE = {"men": "pga", "women": "lpga"}
STREAM_OF = {t: s for s, ts in STREAMS.items() for t in ts}
RANK_MIN_WEIGHT = 10.0        # decayed rounds behind a rating before it is ranked
RANK_ACTIVE_DAYS = 400
PLAYER_MIN_ROUNDS = 20        # a player page needs this many scored rounds
SIMS_ARCHIVE, SIMS_NOW = 5000, 20000
DEFAULT_CUT = {"pga": (2, 65), "eur": (2, 65), "liv": (0, 0), "lpga": (2, 65)}
NO_CUT_FIELD = 80             # a field this small or smaller plays without a cut unless the event says otherwise
TUNING = Path(__file__).resolve().parent / "models" / "tuning.csv"
RESULT_OK = ("finish", "cut", "wd", "dq", "mdf")


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def _r(x, k=3):
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


class Offsets:
    """The display zero at a date: the mean pre-event rating of the centre tour's player-rounds of the trailing year
    (ratings.centre, for every date at once)."""

    def __init__(self, sg: pd.DataFrame, tour: str, days: int = 365):
        d = sg[sg["tour"] == tour].groupby("date")["pre"].agg(["sum", "count"]).sort_index()
        self.days = d.index.values.astype("datetime64[ns]")
        self.cs = np.concatenate([[0.0], d["sum"].cumsum().to_numpy()])
        self.cc = np.concatenate([[0], d["count"].cumsum().to_numpy()])
        self.span = np.timedelta64(days, "D")

    def at(self, t) -> float:
        t = np.datetime64(pd.Timestamp(t), "ns")
        hi = int(np.searchsorted(self.days, t, side="left"))
        lo = int(np.searchsorted(self.days, t - self.span, side="left"))
        n = self.cc[hi] - self.cc[lo]
        return float((self.cs[hi] - self.cs[lo]) / n) if n else 0.0


class Stream:
    """One rating stream walked forward: strokes gained per round, pre-event ratings, the book, the round sd."""

    def __init__(self, key: str, p: R.Params = R.CHOSEN):
        self.key, self.p = key, p
        self.rounds = R.load_rounds(STREAMS[key])
        self.sg, self.pre, self.book = R.walk(self.rounds, p)
        self.off = Offsets(self.sg, CENTRE[key])
        d = self.sg.merge(self.pre[["event", "pid", "weight"]], on=["event", "pid"])
        d = d[d["weight"] >= RANK_MIN_WEIGHT]
        if key == "men":
            d = d[d["date"].dt.year.isin(list(BT.TRAIN))]
        self.sd = float((d["sg"] - d["pre"]).std()) if len(d) > 100 else 3.1
        self.pre_by_event = {e: dict(zip(g["pid"], g["pre"])) for e, g in self.pre.groupby("event")}
        self.weight_by_event = {e: dict(zip(g["pid"], g["weight"])) for e, g in self.pre.groupby("event")}
        g = self.sg.groupby(["event", "pid"])["sg"]
        self.sg_mean = g.mean().to_dict()
        self.sg_n = g.size().to_dict()
        self.field_par = self.sg.groupby(["event", "round"])["field_par"].first().to_dict()
        logger.info("%s: %d rounds walked, %d events, round sd %.3f", key, len(self.sg), len(self.pre_by_event), self.sd)


def _cut_rule(e: dict, tour: str, field: int) -> tuple[int, int]:
    if e.get("cut_round"):
        return int(e["cut_round"]), int(e.get("cut_count") or 65)
    if e.get("status") == "final":
        return 0, 0
    cr, cc = DEFAULT_CUT[tour]
    return (cr, cc) if cr and field > NO_CUT_FIELD else (0, 0)


def _course_id(e: dict) -> str | None:
    cs = e.get("courses") or []
    if len(cs) != 1:
        return None
    return str(cs[0].get("id") or "") or None


def _course(e: dict) -> dict | None:
    cs = e.get("courses") or []
    host = next((c for c in cs if c.get("host")), cs[0] if cs else None)
    return {"name": host.get("name"), "par": host.get("par"), "yards": host.get("yards")} if host else None


def _hole_stats(holes: pd.DataFrame, e: dict) -> list[dict] | None:
    cs = e.get("courses") or []
    if len(cs) != 1 or not len(holes):
        return None
    card = {int(h[0]): (h[1], h[2]) for h in cs[0].get("holes") or []}
    h = holes.assign(d=holes["strokes"] - holes["par"])
    out = []
    for hole, g in h.groupby("hole"):
        d = g["d"]
        n = len(d)
        par, yards = card.get(int(hole), (g["par"].iloc[0], None))
        out.append({"h": int(hole), "par": _int(par), "yd": _int(yards), "n": n, "avg": _r(d.mean()),
                    "eagle": _r((d <= -2).mean()), "birdie": _r((d == -1).mean()), "par_": _r((d == 0).mean()),
                    "bogey": _r((d == 1).mean()), "double": _r((d >= 2).mean())})
    by = sorted(out, key=lambda x: -(x["avg"] or 0))
    for i, x in enumerate(by):
        x["rank"] = i + 1
    return out


def _live(players: list[dict], ratings: np.ndarray, sd: float, e: dict, tour: str, rounds: pd.DataFrame,
          seed: int) -> dict | None:
    """Live chances from the scores so far; None when no round has started."""
    nr = int(e.get("rounds") or (3 if tour == "liv" else 4))
    cr, cc = _cut_rule(e, tour, len(players))
    by = {pid: g for pid, g in rounds.groupby("pid")}
    base, f1, f2, on = [], [], [], []
    done_pairs = []
    cut_made = any(p["st"] == "cut" for p in players)
    for p, rt in zip(players, ratings):
        g = by.get(p["pid"])
        played = 0.0
        tp = 0.0
        if g is not None:
            for _, row in g.iterrows():
                h = float(row["holes"] or 0)
                if h <= 0 or pd.isna(row["to_par"]):
                    continue
                played += min(h, 18) / 18.0
                tp += float(row["to_par"])
                if h >= 18:
                    done_pairs.append(float(row["to_par"]) + rt)
        left = max(nr - played, 0.0)
        to_cut = max(cr - played, 0.0) if (cr and not cut_made) else 0.0
        base.append(tp)
        f1.append(min(to_cut, left))
        f2.append(left - min(to_cut, left))
        on.append(p["st"] not in ("cut", "wd", "dq", "dns"))
    if not done_pairs and not any(b != 0 for b in base):
        return None
    fp = float(np.mean(done_pairs)) if done_pairs else 0.0
    out = sim.simulate_live(ratings, sd, np.array(base), np.array(f1), np.array(f2), np.array(on),
                            cut_count=cc if (cr and not cut_made) else 0, field_par=fp, n=SIMS_NOW, seed=seed)
    return out


def event_page(e: dict, tour: str, season: int, st: Stream, res: pd.DataFrame, rnd: pd.DataFrame, holes: pd.DataFrame,
               players_meta: dict, now: datetime, D=None) -> dict | None:
    eid = e["id"]
    status = e.get("status")
    r = res[res["event"] == eid]
    rr = rnd[rnd["event"] == eid] if len(rnd) else rnd
    pre = st.pre_by_event.get(eid, {})
    wts = st.weight_by_event.get(eid, {})
    start = pd.Timestamp(e.get("start"))
    if status == "upcoming":
        pids = list(dict.fromkeys(e.get("field") or []))
        if not pids:
            return None
        rows = [{"pid": p, "st": "upcoming"} for p in pids]
        rating = np.array([st.book.rating(p, start) for p in pids])
        weight = np.array([st.book.weight(p, start) for p in pids])
    else:
        r = r[r["status"].isin(RESULT_OK + ("live", "upcoming"))].sort_values("order")
        if not len(r):
            return None
        r = r[r["pid"].isin(pre.keys()) | (status != "final")]
        rows = []
        for x in r.itertuples(index=False):
            rows.append({"pid": x.pid, "pos": _int(x.pos), "tie": bool(x.tie), "st": x.status, "tp": _int(x.to_par),
                         "tot": _int(x.strokes), "earn": _int(x.earnings), "pts": _r(x.points, 1)})
        rating = np.array([pre.get(p["pid"], st.book.rating(p["pid"], start)) for p in rows])
        weight = np.array([wts.get(p["pid"], st.book.weight(p["pid"], start)) for p in rows])
    if not rows:
        return None
    nr = int(e.get("rounds") or (3 if tour == "liv" else 4))
    cr, cc = _cut_rule(e, tour, len(rows))
    seed = int(eid) % 2**31
    fc = sim.simulate(rating, st.sd, rounds=nr, cut_round=cr, cut_count=cc,
                      n=SIMS_ARCHIVE if status == "final" else SIMS_NOW, seed=seed)
    off = st.off.at(start)
    rounds_by = {}
    for x in rr.itertuples(index=False):
        rounds_by.setdefault(x.pid, {})[int(x.round)] = (x.strokes, x.to_par, x.holes)
    for i, p in enumerate(rows):
        meta = players_meta.get(p["pid"]) or {}
        p["name"] = meta.get("name") or p["pid"]
        p["cc"] = meta.get("country")
        p["rt"] = _r(rating[i] - off, 2)
        p["wt"] = _r(weight[i], 1)
        p["win"], p["t5"], p["t10"], p["t20"] = (_r(fc[k][i], 4) for k in ("win", "top5", "top10", "top20"))
        p["cut"] = _r(fc["make_cut"][i], 4) if cr else None
        p["xr"] = _r(fc["rank"][i], 1)
        rb = rounds_by.get(p["pid"], {})
        p["r"] = [_int(rb[k][0]) if k in rb and (rb[k][2] or 0) >= 18 else None for k in range(1, nr + 1)]
        p["rtp"] = [_int(rb[k][1]) if k in rb else None for k in range(1, nr + 1)]
        p["thru"] = [_int(rb[k][2]) if k in rb else None for k in range(1, nr + 1)]
        n_sg = st.sg_n.get((eid, p["pid"]))
        p["sg"] = _r(st.sg_mean.get((eid, p["pid"])), 2) if n_sg else None
    live = None
    if status == "live":
        lv = _live(rows, rating, st.sd, e, tour, rr, seed)
        if lv is not None:
            for i, p in enumerate(rows):
                p["lwin"], p["lt10"] = _r(lv["win"][i], 4), _r(lv["top10"][i], 4)
                p["lcut"] = _r(lv["make_cut"][i], 4) if cr else None
            live = {"at": now.isoformat(timespec="minutes")}
    if status == "upcoming":
        rows.sort(key=lambda p: -(p["win"] or 0))
    fav = max(rows, key=lambda p: p["win"] or 0)
    par_by_round = []
    for k in range(1, nr + 1):
        fpv = st.field_par.get((eid, k))
        tps = [p["rtp"][k - 1] for p in rows if p["rtp"][k - 1] is not None and (p["thru"][k - 1] or 0) >= 18]
        par_by_round.append({"round": k, "avg_tp": _r(np.mean(tps), 2) if tps else None, "n": len(tps),
                             "field_par": _r(fpv, 2) if fpv is not None else None})
    hh = holes[holes["event"] == eid] if len(holes) else holes
    cs = e.get("courses") or []
    host = next((c for c in cs if c.get("host")), cs[0] if cs else None) or {}
    course_id = str(host.get("id") or "") or None if len(cs) == 1 else None
    course_guess = False
    if D is not None and status != "final" and not cs:
        # an upcoming event has no course until its leaderboard opens: the course of the last final edition of the
        # same event (by name, on the same tour), flagged as a guess on the page
        course_id = D.last_course(STREAM_OF[tour], tour, e.get("name"), start)
        course_guess = bool(course_id)
    if D is not None and status != "final" and course_id:
        try:
            fit = D.course_fit(STREAM_OF[tour], [p["pid"] for p in rows], course_id, start)
        except Exception:          # noqa: BLE001 - the course history is a garnish; the forecast must still publish
            logger.exception("course fit for %s", eid)
            fit = {}
        for p in rows:
            if p["pid"] in fit:
                p["ch"] = fit[p["pid"]]
    # who beat our forecast: finish against the mean simulated finish
    if status == "final":
        for p in rows:
            if p.get("pos") and p["st"] == "finish" and p.get("xr"):
                p["beat"] = _r(p["xr"] - p["pos"], 1)
    return {
        "id": eid, "tour": tour, "tour_name": canon.TOURS[tour]["name"], "stream": STREAM_OF[tour], "season": season,
        "name": e.get("name"), "start": e.get("start"), "end": e.get("end"), "status": status, "major": bool(e.get("major")),
        "purse": _int(e.get("purse")), "course": _course(e), "course_id": course_id, "course_guess": course_guess,
        "courses": [{"name": c.get("name"), "par": c.get("par"), "yards": c.get("yards"), "host": bool(c.get("host"))}
                    for c in e.get("courses") or []],
        "rounds": nr, "cut": {"round": cr, "count": cc, "score": _int(e.get("cut_score"))} if cr else None,
        "playoff": bool(e.get("playoff")), "winner": e.get("winner"), "fav": fav["pid"],
        "model": MODEL_VERSION, "sd": _r(st.sd, 3), "sims": SIMS_ARCHIVE if status == "final" else SIMS_NOW,
        "live": live, "round_avg": par_by_round, "holes": _hole_stats(hh, e),
        "updated_at": now.isoformat(timespec="minutes"), "players": rows,
    }


def _summary(page: dict) -> dict:
    pl = page["players"]
    win = next((p for p in pl if p.get("pos") == 1), None) if page["status"] == "final" else None
    fav = next(p for p in pl if p["pid"] == page["fav"])
    out = {"id": page["id"], "name": page["name"], "start": page["start"], "end": page["end"], "status": page["status"],
           "major": page["major"], "purse": page["purse"], "course": (page.get("course") or {}).get("name"),
           "field": len(pl), "fav": {"pid": fav["pid"], "name": fav["name"], "win": fav["win"]}, "course_id": page.get("course_id")}
    if win:
        out["winner"] = {"pid": win["pid"], "name": win["name"], "tp": win.get("tp"), "win": win.get("win"),
                         "xr": win.get("xr")}
    if page["status"] == "live":
        lead = sorted([p for p in pl if p.get("lwin") is not None], key=lambda p: -p["lwin"])[:1]
        if lead:
            out["leader"] = {"pid": lead[0]["pid"], "name": lead[0]["name"], "lwin": lead[0]["lwin"], "tp": lead[0].get("tp")}
    return out


COLUMNS = {"results": ["event", "pid", "pos", "tie", "status", "strokes", "to_par", "earnings", "points", "amateur", "order"],
           "rounds": ["event", "pid", "round", "strokes", "out", "in", "tee_time", "to_par", "holes"],
           "holes": ["event", "pid", "round", "hole", "strokes", "par"]}


def _table(tour: str, season: int, name: str) -> pd.DataFrame:
    df = store.load_table(tour, season, name)
    return df if "event" in df.columns else pd.DataFrame(columns=COLUMNS[name])


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build(out: Path, today: date | None = None, full: bool = False, seasons_back: int | None = None) -> dict:
    """Write every payload under `out` (docs/green/data). Returns counts."""
    now = datetime.now(timezone.utc)
    today = today or now.date()
    out.mkdir(parents=True, exist_ok=True)
    players_meta = store.load_players()
    streams = {k: Stream(k) for k in STREAMS}
    counts = {"events": 0, "events_built": 0, "players": 0}
    try:
        D = DP.Depth(streams, STREAMS, players_meta, today)
    except Exception:              # noqa: BLE001 - the depth payloads are optional; the forecasts must still publish
        logger.exception("depth analytics failed: the Scouting Room, Lab and courses are not rebuilt this run")
        D = None
    summaries: dict[str, dict[int, list]] = {}
    pages_index: dict[str, dict] = {}          # event id -> small facts the player pages and calibration read
    results_by_pid: dict[str, list] = {}
    for tour in canon.TOURS:
        st = streams[STREAM_OF[tour]]
        for season in store.seasons(tour):
            ev = store.load_events(tour, season)
            if not ev:
                continue
            res, rnd, hol = (_table(tour, season, t) for t in ("results", "rounds", "holes"))
            sched = []
            for e in sorted(ev.values(), key=lambda x: (x.get("start") or "", x["id"])):
                if e.get("status") == "canceled":
                    continue
                base = {"id": e["id"], "name": e.get("name"), "start": e.get("start"), "end": e.get("end"),
                        "status": e.get("status"), "major": bool(e.get("major")), "purse": _int(e.get("purse")),
                        "course": (_course(e) or {}).get("name"), "course_id": _course_id(e), "team": bool(e.get("team"))}
                if e.get("team"):
                    sched.append(base)
                    continue
                path = out / "events" / f"{e['id']}.json"
                page = _load(path) if (e.get("status") == "final" and not full) else None
                if page and page.get("model") == MODEL_VERSION and page.get("status") == "final":
                    pass
                else:
                    page = event_page(e, tour, season, st, res, rnd, hol, players_meta, now, D)
                    if page is None:
                        sched.append(base)
                        continue
                    _write(path, page)
                    counts["events_built"] += 1
                counts["events"] += 1
                s = _summary(page)
                s["team"] = False
                s["page"] = True
                sched.append(s)
                pages_index[e["id"]] = {"tour": tour, "season": season, "name": page["name"], "start": page["start"],
                                        "status": page["status"], "major": page["major"], "stream": STREAM_OF[tour]}
                if page["status"] == "final":
                    for p in page["players"]:
                        results_by_pid.setdefault(p["pid"], []).append(
                            [e["id"], tour, page["start"], p.get("pos"), p.get("tie"), p["st"], p.get("tp"),
                             p.get("earn"), p.get("sg"), p.get("win"), p.get("t10"), p.get("rt")])
            summaries.setdefault(tour, {})[season] = sched
            _write(out / "schedule" / tour / f"{season}.json", {"tour": tour, "tour_name": canon.TOURS[tour]["name"],
                                                               "season": season, "events": sched})
    rankings = _rankings(streams, players_meta, results_by_pid, today, D)
    _write(out / "rankings.json", rankings)
    counts["players"] = _player_pages(out, streams, players_meta, results_by_pid, rankings, pages_index, today, D)
    courses_index = {}
    if D is not None:
        courses_index = _depth_payloads(out, D, rankings, pages_index, results_by_pid, counts)
    _write(out / "model.json", _model(out, streams, pages_index, now, D))
    idx = _index(out, summaries, rankings, streams, now, today, counts)
    _write(out / "index.json", idx)
    if D is not None:
        try:
            _write(out / "overview.json", _overview(out, D, idx, rankings, summaries, pages_index, results_by_pid, today, now))
        except Exception:          # noqa: BLE001
            logger.exception("overview payload failed")
    _write(out / "search.json", _search(out, players_meta, pages_index, courses_index))
    return counts


def _depth_payloads(out: Path, D, rankings: dict, pages_index: dict, results_by_pid: dict, counts: dict) -> dict:
    """The Scouting Room boards, courses, Lab, records and points ranking. Each part fails alone."""
    cindex: dict = {}
    for key in STREAMS:
        try:
            _write(out / "scout" / f"{key}.json", D.scout(key, {r["pid"]: r for r in rankings[key]}))
        except Exception:          # noqa: BLE001
            logger.exception("scout %s", key)
        try:
            lst, cp = D.courses(key, pages_index)
            for cid, page in cp.items():
                _write(out / "courses" / f"{cid}.json", page)
            for c in lst:
                c["stream"] = key
                cindex[c["id"]] = c
            counts[f"courses_{key}"] = len(cp)
        except Exception:          # noqa: BLE001
            logger.exception("courses %s", key)
    _write(out / "courses.json", {"courses": list(cindex.values())})
    # the kit's metric catalogue (QK.spec: board heads, units, tips), served from data/spec/ (core.js sets the base)
    m = {k: [v[0], v[4], v[3], "h", i, 0, DP.A.TIPS.get(k, ""), v[1], ""] for i, (k, v) in enumerate(DP.A.METRICS.items())}
    _write(out / "spec" / "golf.labels.json", {"sport": "golf", "generated": date.today().isoformat(),
                                             "ours": {"models": {"sg": {"name": "Strokes gained", "about": "Strokes a round better than an average field, from every round against the field that played it."}},
                                                      "metrics": {"sg": "sg", "rt": "sg", "form": "sg"}},
                                             "m": {"player": m}, "groups": {}})
    for name, fn in (("lab", lambda: D.lab()), ("records", lambda: D.records(pages_index, results_by_pid)),
                     ("points", lambda: {k: D.points(k) for k in STREAMS})):
        try:
            _write(out / f"{name}.json", fn())
        except Exception:          # noqa: BLE001
            logger.exception("%s payload", name)
    return cindex


def _rankings(streams: dict, meta: dict, results: dict, today: date, D=None) -> dict:
    t = pd.Timestamp(today)
    out = {"updated_at": today.isoformat(), "min_weight": RANK_MIN_WEIGHT, "active_days": RANK_ACTIVE_DAYS}
    for key, st in streams.items():
        off = st.off.at(t)
        cur = R.current(st.book, today, min_rounds=PLAYER_MIN_ROUNDS, active_days=RANK_ACTIVE_DAYS, offset=off)
        cur = cur[cur["weight"] >= RANK_MIN_WEIGHT].head(500)
        pre = st.pre[st.pre["pid"].isin(set(cur["pid"]))].sort_values("start")
        then = {}
        for days in (30, 90, 365):
            cut = t - pd.Timedelta(days=days)
            p0 = pre[pre["start"] <= cut].groupby("pid").tail(1).set_index("pid")["pre"].to_dict()
            o0 = st.off.at(cut)
            then[days] = {k: v - o0 for k, v in p0.items()}
        tour_last = st.rounds.sort_values("date").groupby("pid")["tour"].last().to_dict()
        whatif = {}
        if D is not None:
            try:
                whatif = D.what_if(key, list(cur["pid"]), D.outcomes_table(key))
            except Exception:      # noqa: BLE001
                logger.exception("what-if %s", key)
        rows = []
        cutoff = (today - timedelta(days=365)).isoformat()
        for i, x in enumerate(cur.itertuples(index=False)):
            m = meta.get(x.pid) or {}
            allr = sorted(results.get(x.pid, []), key=lambda r: r[2] or "")
            yr = [r for r in allr if (r[2] or "") >= cutoff]
            last5 = [[r[0], r[3], r[4], r[5]] for r in allr[-5:]]
            rows.append({"rank": i + 1, "pid": x.pid, "name": m.get("name") or x.pid, "cc": m.get("country"),
                         "rt": _r(x.rating, 2), "wt": _r(x.weight, 1), "n": int(x.rounds), "last": str(x.last.date()),
                         "tour": tour_last.get(x.pid),
                         "d30": _r(x.rating - then[30][x.pid], 2) if x.pid in then[30] else None,
                         "d90": _r(x.rating - then[90][x.pid], 2) if x.pid in then[90] else None,
                         "d365": _r(x.rating - then[365][x.pid], 2) if x.pid in then[365] else None,
                         "starts": len(yr), "wins": sum(1 for r in yr if r[3] == 1 and r[5] == "finish"),
                         "top10": sum(1 for r in yr if r[3] is not None and r[3] <= 10 and r[5] == "finish"),
                         "cuts": sum(1 for r in yr if r[5] == "finish"), "earn": sum(r[7] or 0 for r in yr),
                         "sg12": _r(np.mean([r[8] for r in yr if r[8] is not None]), 2) if any(r[8] is not None for r in yr) else None,
                         "l5": last5, "wi": whatif.get(x.pid)})
        out[key] = rows
        if D is not None:
            try:
                out[f"{key}_whatif"] = D.outcomes_table(key)
            except Exception:      # noqa: BLE001
                pass
    return out


def _player_pages(out: Path, streams: dict, meta: dict, results: dict, rankings: dict, pages_index: dict, today: date, D=None) -> int:
    rank = {k: {r["pid"]: r for r in rankings[k]} for k in streams}
    n = 0
    for key, st in streams.items():
        cnt = st.sg.groupby("pid").size()
        keep = set(cnt[cnt >= PLAYER_MIN_ROUNDS].index) | set(rank[key])
        pre = st.pre[st.pre["pid"].isin(keep)].sort_values("start")
        for pid, g in pre.groupby("pid"):
            m = meta.get(pid) or {}
            hist = [[str(s.date()), _r(v - st.off.at(s), 2), e] for e, s, v in zip(g["event"], g["start"], g["pre"])]
            res = sorted(results.get(pid, []), key=lambda r: r[2] or "")
            rows = []
            seasons: dict = {}
            for r in res:
                pi = pages_index.get(r[0]) or {}
                if pi.get("stream") != key:
                    continue
                rows.append({"id": r[0], "tour": r[1], "date": r[2], "name": pi.get("name"), "major": pi.get("major"),
                             "pos": r[3], "tie": r[4], "st": r[5], "tp": r[6], "earn": r[7], "sg": r[8], "win": r[9],
                             "t10": r[10], "rt": r[11]})
                s = seasons.setdefault((pi.get("season"), r[1]), {"season": pi.get("season"), "tour": r[1], "starts": 0,
                                                                  "wins": 0, "top10": 0, "cuts": 0, "earn": 0, "sg": []})
                s["starts"] += 1
                if r[5] == "finish":
                    s["cuts"] += 1
                    s["wins"] += int(r[3] == 1)
                    s["top10"] += int(r[3] is not None and r[3] <= 10)
                s["earn"] += r[7] or 0
                if r[8] is not None:
                    s["sg"].append(r[8])
            lines = []
            for s in sorted(seasons.values(), key=lambda s: (s["season"] or 0, s["tour"])):
                s["sg"] = _r(np.mean(s["sg"]), 2) if s["sg"] else None
                lines.append(s)
            rk = rank[key].get(pid)
            now_rt = _r(st.book.rating(pid, pd.Timestamp(today)) - st.off.at(pd.Timestamp(today)), 2)
            page = {"pid": pid, "name": m.get("name") or pid, "cc": m.get("country"), "amateur": bool(m.get("amateur")),
                    "stream": key, "rank": rk["rank"] if rk else None, "rt": rk["rt"] if rk else now_rt,
                    "wt": _r(st.book.weight(pid, pd.Timestamp(today)), 1), "rounds": int(st.book.n.get(pid, 0)),
                    "last": str(st.book.t[pid].date()) if pid in st.book.t else None, "ranked": bool(rk),
                    "history": hist, "events": rows[::-1], "seasons": lines[::-1],
                    "summary": rk}
            if D is not None:
                try:
                    page.update(D.player_extra(key, pid))
                except Exception:  # noqa: BLE001
                    logger.exception("player depth %s", pid)
            _write(out / "players" / f"{pid}.json", page)
            n += 1
    return n


def _calibration(ps: np.ndarray, ys: np.ndarray, edges: list[float]) -> list[dict]:
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (ps >= lo) & (ps < hi)
        if m.sum() < 20:
            continue
        out.append({"lo": lo, "hi": hi, "n": int(m.sum()), "p": _r(ps[m].mean(), 4), "freq": _r(ys[m].mean(), 4)})
    return out


PROMOTION = Path(__file__).resolve().parent / "models" / "promotion.json"


def _model(out: Path, streams: dict, pages_index: dict, now: datetime, D=None) -> dict:
    men = streams["men"]
    d = men.sg.merge(men.pre[["event", "pid", "weight"]], on=["event", "pid"])
    rounds = {}
    for name, yrs in (("train", BT.TRAIN), ("valid", BT.VALID), ("test", BT.TEST)):
        s = BT.round_scores(men.sg, yrs, RANK_MIN_WEIGHT, men.pre)
        rounds[name] = {"years": [yrs.start, yrs.stop - 1], "n": s["n"], "mse": _r(s["mse"]), "mse_zero": _r(s["mse_zero"]),
                        "r": _r(s["r"]), "sd": _r(s["sd"])}
    # event level, the sealed test years: read back from the event pages (the archive forecasts)
    win_p, win_y, t10_p, t10_y, cut_p, cut_y = [], [], [], [], [], []
    ev = {"events": 0, "fav_won": 0, "win_ll": 0.0, "win_base": 0.0, "t10_ll": 0.0, "t10_base": 0.0,
          "cut_ll": 0.0, "cut_base": 0.0, "cut_events": 0}
    for eid, pi in pages_index.items():
        if pi["tour"] != "pga" or pi["status"] != "final" or int(pi["season"]) not in BT.TEST:
            continue
        page = _load(out / "events" / f"{eid}.json")
        if not page:
            continue
        pl = [p for p in page["players"] if p["st"] in ("finish", "cut")]
        if len(pl) < 30:
            continue
        won = np.array([1.0 if (p["st"] == "finish" and p.get("pos") == 1) else 0.0 for p in pl])
        if won.sum() != 1:
            continue
        N = len(pl)
        pw = np.array([p["win"] or 0 for p in pl])
        y10 = np.array([1.0 if (p["st"] == "finish" and (p.get("pos") or 999) <= 10) else 0.0 for p in pl])
        p10 = np.array([p["t10"] or 0 for p in pl])
        ev["events"] += 1
        ev["fav_won"] += int(won[int(np.argmax(pw))] == 1)
        ev["win_ll"] += BT._ll(pw, won)
        ev["win_base"] += BT._ll(np.full(N, 1 / N), won)
        ev["t10_ll"] += BT._ll(p10, y10)
        ev["t10_base"] += BT._ll(np.full(N, min(10 / N, 1)), y10)
        win_p += list(pw); win_y += list(won); t10_p += list(p10); t10_y += list(y10)
        if page.get("cut"):
            made = np.array([1.0 if p["st"] == "finish" else 0.0 for p in pl])
            pc = np.array([p["cut"] or 0 for p in pl])
            ev["cut_ll"] += BT._ll(pc, made)
            ev["cut_base"] += BT._ll(np.full(N, made.mean()), made)
            ev["cut_events"] += 1
            cut_p += list(pc); cut_y += list(made)
    E = max(ev["events"], 1)
    C = max(ev["cut_events"], 1)
    events = {"years": [BT.TEST.start, BT.TEST.stop - 1], "events": ev["events"],
              "favourite_won": _r(ev["fav_won"] / E, 4),
              "win": {"model": _r(ev["win_ll"] / E, 5), "base": _r(ev["win_base"] / E, 5)},
              "top10": {"model": _r(ev["t10_ll"] / E, 5), "base": _r(ev["t10_base"] / E, 5)},
              "cut": {"model": _r(ev["cut_ll"] / C, 5), "base": _r(ev["cut_base"] / C, 5), "events": ev["cut_events"]}}
    for k in ("win", "top10", "cut"):
        m, b = events[k]["model"], events[k]["base"]
        events[k]["skill"] = _r(1 - m / b, 4) if m and b else None
    cal = {"win": _calibration(np.array(win_p), np.array(win_y), [0, .01, .02, .04, .07, .1, .15, .25, 1.01]),
           "top10": _calibration(np.array(t10_p), np.array(t10_y), [0, .03, .06, .1, .15, .2, .3, .45, .6, 1.01]),
           "cut": _calibration(np.array(cut_p), np.array(cut_y), [0, .2, .3, .4, .5, .6, .7, .8, .9, 1.01])}
    grid = []
    if TUNING.exists():
        with TUNING.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                grid.append({"half_life": float(row["half_life"]), "k0": float(row["k0"]),
                             "train": _r(row["train_mse_all"], 4), "valid": _r(row["valid_mse"], 4)})
    return {"updated_at": now.isoformat(timespec="minutes"), "version": MODEL_VERSION,
            "params": {"half_life": men.p.half_life, "k0": men.p.k0, "min_field": men.p.min_field},
            "sd": {"men": _r(streams["men"].sd, 3), "women": _r(streams["women"].sd, 3)},
            "sims": {"archive": SIMS_ARCHIVE, "now": SIMS_NOW}, "rounds": rounds, "events": events,
            "calibration": cal, "grid": grid,
            "promotion": (_load(PROMOTION) or {}),
            "cats": (D.lab() or {}).get("cats") if D is not None and D.cats else None,
            "coverage": {t: {"name": v["name"], "seasons": store.seasons(t), "holes": v["holes"]} for t, v in canon.TOURS.items()}}


def _index(out: Path, summaries: dict, rankings: dict, streams: dict, now: datetime, today: date, counts: dict) -> dict:
    iso = today.isoformat()
    week = []
    recent = []
    for tour, by in summaries.items():
        evs = [s for season in sorted(by) for s in by[season] if not s.get("team")]
        live = [s for s in evs if s["status"] == "live"]
        nxt = [s for s in evs if s["status"] == "upcoming" and s.get("page")]
        pick = live[:1] or nxt[:1]
        for s in pick:
            page = _load(out / "events" / f"{s['id']}.json") or {}
            key = "lwin" if s["status"] == "live" and (page.get("live") or {}) else "win"
            top = sorted(page.get("players") or [], key=lambda p: -(p.get(key) or 0))[:10]
            week.append({**s, "tour": tour, "tour_name": canon.TOURS[tour]["name"], "key": key,
                         "top": [{"pid": p["pid"], "name": p["name"], "cc": p.get("cc"), "rt": p.get("rt"),
                                  "win": p.get("win"), "t10": p.get("t10"), "cut": p.get("cut"), "lwin": p.get("lwin"),
                                  "tp": p.get("tp"), "pos": p.get("pos"), "tie": p.get("tie")} for p in top]})
        for s in evs:
            if s["status"] == "final" and s.get("winner") and (s.get("end") or "") >= (today - timedelta(days=60)).isoformat():
                recent.append({**s, "tour": tour})
    recent.sort(key=lambda s: s.get("end") or "", reverse=True)
    return {"site": "The Quant Green", "updated_at": now.isoformat(timespec="minutes"), "today": iso,
            "model": MODEL_VERSION, "week": week, "recent": recent[:10],
            "top": {k: rankings[k][:10] for k in ("men", "women")},
            "seasons": {t: sorted(by) for t, by in summaries.items()},
            "tours": {t: {"name": v["name"], "short": v["short"], "stream": STREAM_OF[t]} for t, v in canon.TOURS.items()},
            "counts": counts}


def _search(out: Path, meta: dict, pages_index: dict, courses: dict | None = None) -> dict:
    players = []
    for p in sorted((out / "players").glob("*.json")):
        m = meta.get(p.stem) or {}
        try:
            stream = json.loads(p.read_text(encoding="utf-8")).get("stream")
        except (OSError, ValueError):
            stream = None
        # the stream (men / women) names the follow card: men's and women's player ids are separate id spaces
        players.append([p.stem, m.get("name") or p.stem, m.get("country"), stream])
    events = [[eid, pi["name"], pi["season"], pi["tour"]] for eid, pi in pages_index.items()]
    events.sort(key=lambda x: (-int(x[2]), x[1] or ""))
    cs = [[c["id"], c["name"], c.get("tour")] for c in (courses or {}).values() if c.get("name")]
    return {"players": players, "events": events, "courses": cs}


def _overview(out: Path, D, idx: dict, rankings: dict, summaries: dict, pages_index: dict, results: dict, today: date,
              now: datetime) -> dict:
    """The landing page: the featured event, the week's digest, the power board, stories, leaders, who's for real."""
    t = pd.Timestamp(today)
    week = idx.get("week") or []
    feat = None
    for w in sorted(week, key=lambda w: (w["status"] != "live", not w.get("major"), w.get("tour") != "pga", -(w.get("purse") or 0))):
        feat = w
        break
    # digest: final events that ended in the last 8 days (else the latest week)
    finals = []
    for tour, by in summaries.items():
        for season in by:
            for s0 in by[season]:
                if s0.get("status") == "final" and s0.get("winner") and not s0.get("team"):
                    finals.append({**s0, "tour": tour})
    finals.sort(key=lambda s0: s0.get("end") or "", reverse=True)
    recent = [f for f in finals if (f.get("end") or "") >= (today - timedelta(days=8)).isoformat()] or finals[:4]
    low = None
    for f in recent:
        page = _load(out / "events" / f"{f['id']}.json") or {}
        stn = page.get("stream")
        if not stn or stn not in D.S:
            continue
        rf = D.S[stn]["rf"]
        x = rf[(rf["event"] == f["id"]) & (rf["out"] + rf["in"] == rf["strokes"])]
        if len(x):
            r = x.loc[x["sg"].idxmax()]
            if low is None or r["sg"] > low["sg"]:
                low = {"pid": r["pid"], "name": (D.meta_p.get(r["pid"]) or {}).get("name"), "event": f["id"], "ev": f["name"],
                       "round": int(r["round"]), "strokes": _int(r["strokes"]), "sg": _r(r["sg"], 2), "field": _r(r["field_par"], 2)}
    long = min((f for f in recent if (f.get("winner") or {}).get("win") is not None), key=lambda f: f["winner"]["win"], default=None)
    digest = {"from": min((f.get("start") or "") for f in recent) if recent else None, "to": max((f.get("end") or "") for f in recent) if recent else None,
              "events": [{"id": f["id"], "name": f["name"], "tour": f["tour"], "major": f.get("major"), "winner": f.get("winner"),
                          "fav": f.get("fav")} for f in recent[:8]],
              "fav_won": sum(1 for f in recent if (f.get("winner") or {}).get("pid") == (f.get("fav") or {}).get("pid")),
              "low": low, "longshot": {"id": long["id"], "name": long["name"], "winner": long["winner"]} if long else None}
    # power board: the top 16 men and 8 women with the category parts where we have them
    power = {}
    for key in STREAMS:
        W = D.S[key]["W"]
        rows = []
        for r in rankings[key][: 16 if key == "men" else 12]:
            pid = r["pid"]
            parts = {}
            if pid in W.index:
                w = W.loc[pid]
                if all(c in W.columns and np.isfinite(w.get(c, np.nan)) for c in ("c_ott", "c_app", "c_arg", "c_putt")):
                    parts = {"ott": _r(w["c_ott"], 2), "app": _r(w["c_app"], 2), "sg": _r(w["c_arg"] + w["c_putt"], 2)}
                    parts["other"] = _r(r["rt"] - sum(parts.values()), 2)
            rows.append({**{k: r.get(k) for k in ("rank", "pid", "name", "cc", "rt", "d30", "d90", "tour", "wins", "top10", "starts", "l5")}, "parts": parts or None})
        power[key] = rows
    # stories: risers and fallers over 90 days, hottest form against rating, the longest made-cut run
    stories = []
    for key in STREAMS:
        rk = [r for r in rankings[key][:150] if r.get("d90") is not None]
        if rk:
            up = max(rk, key=lambda r: r["d90"])
            dn = min(rk, key=lambda r: r["d90"])
            for kind, r in (("riser", up), ("faller", dn)):
                st = D.S[key]["st"]
                g = st.pre[(st.pre["pid"] == r["pid"]) & (st.pre["start"] >= t - pd.Timedelta(days=365))].sort_values("start")
                spark = [_r(v - st.off.at(d0), 2) for d0, v in zip(g["start"], g["pre"])][-20:]
                stories.append({"kind": kind, "stream": key, "pid": r["pid"], "name": r["name"], "d": r["d90"], "rt": r["rt"], "spark": spark})
        W = D.S[key]["W"]
        if "form" in W.columns:
            q = W[W["q"] & W["form"].notna()]
            if len(q):
                hot = (q["form"] - q["rt"]).idxmax()
                stories.append({"kind": "hot", "stream": key, "pid": hot, "name": (D.meta_p.get(hot) or {}).get("name"),
                                "form": _r(q.loc[hot, "form"], 2), "rt": _r(q.loc[hot, "rt"], 2)})
        best = None
        for r in rankings[key][:200]:
            rs = sorted(results.get(r["pid"], []), key=lambda x: x[2] or "")
            n = 0
            for x in reversed(rs):
                if x[5] == "finish":
                    n += 1
                elif x[5] == "cut":
                    break
            if best is None or n > best[1]:
                best = (r, n)
        if best and best[1] >= 8:
            stories.append({"kind": "cuts", "stream": key, "pid": best[0]["pid"], "name": best[0]["name"], "n": best[1]})
    # leaders on the key metrics (the board's qualified players)
    stars = []
    for key in STREAMS:
        W = D.S[key]["W"]
        q = W[W["q"]]
        for m in ("sg", "form", "dist", "acc", "gir", "ppg", "h5", "bird", "bog", "sd"):
            if m not in q.columns or q[m].notna().sum() < 10:
                continue
            lower = DP.A.METRICS[m][3] == "lower"
            o = q[m].dropna().sort_values(ascending=lower)
            a, b = o.index[0], o.index[1]
            stars.append({"stream": key, "m": m, "label": DP.A.METRICS[m][0], "pid": a, "name": (D.meta_p.get(a) or {}).get("name"),
                          "v": _r(o.iloc[0], 4), "next": {"pid": b, "name": (D.meta_p.get(b) or {}).get("name"), "v": _r(o.iloc[1], 4)},
                          "tour": W.loc[a, "tour"]})
    # who's for real: rating against the top-10 rate over 12 months
    real = {}
    for key in STREAMS:
        real[key] = [{"pid": r["pid"], "name": r["name"], "x": r["rt"], "y": _r(r["top10"] / r["starts"], 3), "n": r["starts"]}
                     for r in rankings[key][:60] if r.get("starts", 0) >= 8]
    return {"updated_at": now.isoformat(timespec="minutes"), "featured": feat, "digest": digest, "power": power,
            "stories": stories, "stars": stars, "real": real}
