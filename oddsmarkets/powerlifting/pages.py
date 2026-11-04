"""The Quant Iron payloads (docs/iron/data).

    index.json                 recent meets, ranking tops, sealed-test tiles
    rankings.json              current DOTS ratings per stream (sex × equipment)
    schedule/<year>.json       that year's meets (compact)
    events/<id>.json           a meet: leaderboard with our pre-meet expected total and DOTS
    players/<id>.json          a lifter: rating history and every scored meet
    model.json                 parameters, the tuning grid, the sealed test and calibration
    search.json                lifters and recent meets for the search box
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import canon, store
from .models import backtest as BT
from .models import ratings as R

logger = logging.getLogger(__name__)

MODEL_VERSION = 1
RANK_MIN_MEETS = 5
RANK_ACTIVE_DAYS = 400
PLAYER_MIN_MEETS = 6
PLAYER_ACTIVE_DAYS = 800
PLAYER_CAP = 6000
MEET_RECENT_DAYS = 400
MEET_BIG_DAYS = 1100
MEET_BIG_N = 40
MEET_CAP = 5000
TUNING = Path(__file__).resolve().parent / "models" / "tuning.csv"


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
    """String from a parquet cell: pandas NA / NaN is truthy, so `x or \"\"` is not enough."""
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except (TypeError, ValueError):
        pass
    return str(x)


def _iso(t) -> str:
    if hasattr(t, "date"):
        return t.date().isoformat() if not isinstance(t, datetime) else t.date().isoformat()
    return str(t)[:10]


def _names(entries: pd.DataFrame) -> dict[str, dict]:
    """pid → {name, country, sex} from the latest row. Zip, not itertuples: `name` is a namedtuple attribute."""
    last = entries.sort_values("date").groupby("pid", as_index=False).tail(1)
    return {pid: {"name": _s(name), "country": _s(country), "sex": _s(sex)}
            for pid, name, country, sex in zip(last["pid"], last["name"], last["country"], last["sex"])}


def _cal_bins(walked: pd.DataFrame, lo: str, hi: str, n=8) -> list[dict]:
    d = walked[(walked["date"] > lo) & (walked["date"] <= hi) & (walked["n"] > 0)]
    if d.empty:
        return []
    qs = np.linspace(0, 1, n + 1)
    edges = np.unique(np.quantile(d["pre"].to_numpy(dtype=float), qs))
    if len(edges) < 3:
        return []
    out = []
    for i in range(len(edges) - 1):
        m = (d["pre"] >= edges[i]) & (d["pre"] < edges[i + 1] if i < len(edges) - 2 else d["pre"] <= edges[i + 1])
        g = d[m]
        if len(g) < 30:
            continue
        out.append({"lo": _r(edges[i], 1), "hi": _r(edges[i + 1], 1), "n": int(len(g)),
                    "pred": _r(g["pre"].mean(), 1), "actual": _r(g["dots"].mean(), 1)})
    return out


def build(out: Path, today: date | None = None, full: bool = False) -> dict:
    today = today or date.today()
    entries = store.load_entries()
    meets = store.load_meets()
    if entries.empty or meets.empty:
        raise RuntimeError("no powerlifting stores: run scripts/pl_fetch.py")
    scored = R.load_scored(entries)
    logger.info("loaded %s entries, %s meets, %s scored SBD", len(entries), len(meets), len(scored))
    # stream mean as the newcomer prior, from the training years (walk is then comparable on TEST)
    train_dots = scored.loc[scored["date"] <= BT.TRAIN_END, "dots"] if len(scored) else pd.Series(dtype=float)
    m0 = float(train_dots.mean()) if len(train_dots) else 400.0
    if not np.isfinite(m0):
        m0 = 400.0
    p = R.Params(half_life=R.CHOSEN.half_life, k0=R.CHOSEN.k0, m0=m0, min_field=R.CHOSEN.min_field)
    walked, books = R.walk(scored, p)
    logger.info("walked %s starts across %s streams", len(walked), len(books))
    names = _names(entries)
    _rankings(out, walked, books, names, today)
    keep = _meet_pages(out, entries, meets, walked, names, today)
    n_player = _player_pages(out, walked, meets, names, books, today)
    _schedule(out, meets, keep)
    _model(out, walked, p, m0)
    _index(out, meets, walked, names, today)
    _search(out, names, meets, today)
    return {"meets": len(keep), "players": n_player, "entries": int(len(entries)), "scored": int(len(walked))}


def _rankings(out: Path, walked: pd.DataFrame, books: dict, names: dict, today: date) -> None:
    streams = {}
    for key, meta in canon.STREAMS.items():
        book = books.get(key)
        if book is None:
            streams[key] = []
            continue
        cur = R.current(book, today, min_meets=RANK_MIN_MEETS, active_days=RANK_ACTIVE_DAYS)
        # last 12 months' best DOTS and meet count, from the walk
        last = walked[(walked["stream"] == key) & (walked["date"] > pd.Timestamp(today) - pd.Timedelta(days=365))]
        best = last.groupby("pid")["dots"].max() if len(last) else pd.Series(dtype=float)
        n12 = last.groupby("pid").size() if len(last) else pd.Series(dtype=int)
        tested_share = last.groupby("pid")["tested"].mean() if len(last) else pd.Series(dtype=float)
        rows = []
        for i, r in enumerate(cur.itertuples(index=False), 1):
            info = names.get(r.pid) or {}
            rows.append({
                "rank": i, "pid": r.pid, "name": info.get("name") or r.pid,
                "cc": _s(info.get("country")), "rt": _r(r.rating, 1), "wt": _r(r.weight, 1),
                "n": int(r.meets), "last": _iso(r.last),
                "best12": _r(best.get(r.pid), 1), "starts12": _int(n12.get(r.pid) or 0),
                "tested": _r(tested_share.get(r.pid), 2),
            })
        streams[key] = rows
    _write(out / "rankings.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_meets": RANK_MIN_MEETS, "active_days": RANK_ACTIVE_DAYS,
        "unit": "DOTS", "streams": {k: {"label": canon.STREAMS[k]["label"], "rows": streams[k]} for k in canon.STREAMS},
    })


def _meet_pages(out: Path, entries: pd.DataFrame, meets: pd.DataFrame, walked: pd.DataFrame, names: dict,
                today: date) -> set[str]:
    cutoff_recent = (today - timedelta(days=MEET_RECENT_DAYS)).isoformat()
    cutoff_big = (today - timedelta(days=MEET_BIG_DAYS)).isoformat()
    pick = meets[(meets["date"] >= cutoff_recent) |
                 ((meets["date"] >= cutoff_big) & (meets["n_sbd"] >= MEET_BIG_N))]
    pick = pick.sort_values("date", ascending=False).head(MEET_CAP)
    pre_map = {(a, b): c for a, b, c in zip(walked["meet_id"], walked["pid"], walked["pre"])}
    sub = entries[entries["meet_id"].isin(pick["meet_id"])]
    by_meet = {mid: g for mid, g in sub.groupby("meet_id", sort=False)}
    n = 0
    dest = out / "events"
    dest.mkdir(parents=True, exist_ok=True)
    keep = set(pick["meet_id"])
    for r in pick.itertuples(index=False):
        mid = r.meet_id
        rows = by_meet.get(mid)
        if rows is None:
            continue
        board = []
        for e in rows.sort_values(["dots", "total"], ascending=False).itertuples(index=False):
            pred = pre_map.get((mid, e.pid))
            exp_total = (canon.total_from_dots(e.sex, float(e.bw), pred)
                         if pred is not None and pd.notna(e.bw) else None)
            board.append({
                "pid": e.pid, "name": _s(e.name), "sex": _s(e.sex), "eq": _s(e.eq), "event": _s(e.event),
                "div": _s(e.division), "class": _s(e.wclass), "bw": _r(e.bw, 2),
                "squat": _r(e.squat, 1), "bench": _r(e.bench, 1), "dead": _r(e.dead, 1),
                "total": _r(e.total, 1), "dots": _r(e.dots, 1), "gl": _r(e.gl, 1),
                "place": _s(e.place), "tested": bool(e.tested), "cc": _s(e.country),
                "pre": _r(pred, 1), "exp": _r(exp_total, 1),
            })
        _write(dest / f"{mid}.json", {
            "id": mid, "name": _s(r.name), "date": _s(r.date), "fed": _s(r.fed), "parent": _s(r.parent),
            "country": _s(r.country), "state": _s(r.state), "n": int(r.n), "n_sbd": int(r.n_sbd),
            "board": board, "model": MODEL_VERSION,
        })
        n += 1
    logger.info("wrote %s meet pages", n)
    # drop pages we no longer keep (the live site restore would otherwise pile up forever)
    for p in dest.glob("*.json"):
        if p.stem not in keep:
            p.unlink()
    return keep


def _player_pages(out: Path, walked: pd.DataFrame, meets: pd.DataFrame, names: dict,
                  books: dict, today: date) -> int:
    last = walked.groupby("pid")["date"].max()
    nmeets = walked.groupby("pid").size()
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=PLAYER_ACTIVE_DAYS)
    pids = [pid for pid, n in nmeets.items() if n >= PLAYER_MIN_MEETS and last[pid] >= cutoff]
    # prefer currently high-rated / recently active
    pids = sorted(pids, key=lambda x: (-nmeets[x], -last[x].timestamp()))[:PLAYER_CAP]
    dest = out / "players"
    dest.mkdir(parents=True, exist_ok=True)
    keep = set(pids)
    by_pid = {pid: g.sort_values("date") for pid, g in walked[walked["pid"].isin(keep)].groupby("pid", sort=False)}
    meet_name = dict(zip(meets["meet_id"], meets["name"]))
    for pid in pids:
        info = names.get(pid) or {}
        g = by_pid.get(pid)
        if g is None or g.empty:
            continue
        hist = [{"date": _iso(r.date), "meet": r.meet_id, "meet_name": _s(meet_name.get(r.meet_id)),
                 "stream": _s(r.stream), "dots": _r(r.dots, 1), "total": _r(r.total, 1), "bw": _r(r.bw, 2),
                 "pre": _r(r.pre, 1), "exp": _r(canon.total_from_dots(r.sex, r.bw, r.pre), 1),
                 "tested": bool(r.tested)}
                for r in g.itertuples(index=False)]
        last_r = g.iloc[-1]
        stream = last_r["stream"]
        book = books.get(stream)
        rt = book.rating(pid, pd.Timestamp(today)) if book is not None and pid in book.t else last_r["dots"]
        _write(dest / f"{pid}.json", {
            "pid": pid, "name": info.get("name") or pid, "cc": info.get("country") or "",
            "sex": info.get("sex") or last_r["sex"], "eq": last_r["eq"], "stream": stream,
            "rt": _r(rt, 1),
            "n": int(len(g)), "last": _iso(last_r["date"]),
            "best": _r(g["dots"].max(), 1), "best_total": _r(g["total"].max(), 1),
            "hist": hist, "model": MODEL_VERSION,
        })
    for p in dest.glob("*.json"):
        if p.stem not in keep:
            p.unlink()
    logger.info("wrote %s lifter pages", len(pids))
    return len(pids)


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
                         "country": _s(r.country), "n": int(r.n), "n_sbd": int(r.n_sbd),
                         "page": r.meet_id in keep})
        _write(dest / f"{y}.json", {"year": int(y), "meets": rows})
    _write(dest / "years.json", {"years": [int(y) for y in years]})


def _model(out: Path, walked: pd.DataFrame, p: R.Params, m0: float) -> None:
    grid = []
    if TUNING.exists():
        for r in pd.read_csv(TUNING).itertuples(index=False):
            grid.append({c: _r(getattr(r, c), 4) if c != "test_n" else _int(getattr(r, c))
                         for c in r._fields})
    test = BT.score(walked, BT.VALID_END, BT.TEST_END)
    valid = BT.score(walked, BT.TRAIN_END, BT.VALID_END)
    train = BT.score(walked, "1990-01-01", BT.TRAIN_END)
    _write(out / "model.json", {
        "version": MODEL_VERSION, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": {"half_life": p.half_life, "k0": p.k0, "m0": _r(m0, 1), "min_field": p.min_field,
                   "unit": "DOTS"},
        "windows": {"train": f"…{BT.TRAIN_END}", "valid": f"{BT.TRAIN_END}–{BT.VALID_END}",
                    "test": f"{BT.VALID_END}–{BT.TEST_END}"},
        "train": train, "valid": valid, "test": test,
        "calibration": _cal_bins(walked, BT.VALID_END, BT.TEST_END),
        "grid": grid,
        "coverage": {
            "scored": int(len(walked)),
            "lifters": int(walked["pid"].nunique()),
            "meets": int(walked["meet_id"].nunique()),
            "from": _iso(walked["date"].min()) if len(walked) else None,
            "to": _iso(walked["date"].max()) if len(walked) else None,
        },
        "credit": "This page uses data from the OpenPowerlifting project, https://www.openpowerlifting.org. "
                  "You may download a copy of the data at https://data.openpowerlifting.org.",
    })


def _index(out: Path, meets: pd.DataFrame, walked: pd.DataFrame, names: dict, today: date) -> None:
    recent = meets.sort_values("date", ascending=False).head(12)
    ranks = json.loads((out / "rankings.json").read_text(encoding="utf-8"))
    tops = {}
    for k, v in ranks["streams"].items():
        tops[k] = [{kk: r[kk] for kk in ("rank", "pid", "name", "cc", "rt")} for r in (v.get("rows") or [])[:10]]
    test = BT.score(walked, BT.VALID_END, BT.TEST_END)
    _write(out / "index.json", {
        "site": "The Quant Iron",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "model": {"rmse": _r((test or {}).get("rmse"), 1), "r": _r((test or {}).get("r"), 3),
                  "n": (test or {}).get("n"), "unit": "DOTS"},
        "recent": [{"id": r.meet_id, "date": _s(r.date), "name": _s(r.name), "fed": _s(r.fed),
                    "country": _s(r.country), "n": int(r.n)} for r in recent.itertuples(index=False)],
        "top": tops,
        "streams": {k: v["label"] for k, v in canon.STREAMS.items()},
        "counts": {"meets": int(len(meets)), "lifters": int(len(names)),
                   "scored": int(len(walked))},
    })


def _search(out: Path, names: dict, meets: pd.DataFrame, today: date) -> None:
    rank = json.loads((out / "rankings.json").read_text(encoding="utf-8"))
    seen = set()
    players = []
    for v in rank["streams"].values():
        for r in v.get("rows") or []:
            if r["pid"] in seen:
                continue
            seen.add(r["pid"])
            players.append([r["pid"], r["name"], _s(r.get("cc"))])
    cutoff = (today - timedelta(days=MEET_RECENT_DAYS)).isoformat()
    events = [[r.meet_id, _s(r.name), _s(r.date), _s(r.fed)]
              for r in meets[meets["date"] >= cutoff].sort_values("date", ascending=False).itertuples(index=False)]
    _write(out / "search.json", {"players": players[:4000], "events": events[:1500]})
