"""
Walk-forward backtest of the race simulator against simple baselines.

Every Grand Prix with results in the chosen seasons is predicted using only data strictly before it
(``race_inputs`` and the circuit profile cut off at the race; the post-qualifying variant also sees the race's
own grid). Events per driver: win, podium (top 3), points finish (classified in the top 10), DNF (not
classified; did-not-start entries are dropped).

Models
------
* ``model_pre`` / ``model_post``: ``simulate_race`` (``n_sims`` per race, default 4,000) before / after qualifying,
  with Builder A's pace where importable (blended as in ``race_sim``). ``model_post``'s win probabilities carry the
  walk-forward win temperature ``race_sim.win_temp_post`` (fitted only on earlier races), as the site's do;
  ``model_post_untempered`` in the output keeps the raw simulator's winner log-loss and temperature.
* ``model_pre_results_only``: the same with the results-only pace estimator (reported when A is importable).
* ``grid_order`` (post-qualifying baseline): per event ``p = sigmoid(a + b * slot)`` (pit-lane start = last slot),
  fitted by maximum likelihood on all races of the previous seasons on disk (earlier rounds of the same season
  when there are none; defaults when fewer than 3 races), then rescaled so the field's win / podium / points
  probabilities sum to 1 / 3 / 10.
* ``previous_results`` (pre-qualifying baseline): the driver's frequency of each event in his last 5 starts,
  shrunk to the field base rate with 2 pseudo-starts, rescaled as above.
* ``elo`` (pre): C's field Elo before the race (``elo.ratings_before``) as Plackett-Luce log-strengths
  ``theta = elo * ln(10) / 400``; DNF = previous-seasons base rate.
* ``plackett_luce`` (pre): C's ``ranking.fit_strengths`` on earlier finishing orders (current season weight 1,
  previous 0.35, two back 0.12; classified finishers in order, the rest of the field behind), sampled for
  podium / points; DNF = base rate.

Scores: binary log-loss ``-mean(y ln p + (1-y) ln(1-p))`` with p clipped to [1e-4, 1-1e-4], Brier
``mean((p-y)^2)``, multiclass winner log-loss ``-mean(ln p_winner)`` (win probabilities renormalised), and
reliability in 10 equal-width bins (mean forecast, observed frequency, count).

Also per model: ``win_temperature``, the exponent T that minimises the winner log-loss of p^T renormalised over
the field (T > 1: the model is too timid, its favourites win more often than it says; T < 1: too bold).

Results go to ``data/f1/cache/backtest.json``. Seasons whose results are not complete on disk are skipped
and listed with the reason (the current season is used to date). Races are processed one at a time and
nothing but the scores is kept, so memory stays flat over any number of seasons (``memory_mb`` records it).

    python -m oddsmarkets.f1.models.backtest --from 2014 --to 2026 --sims 4000
"""
from __future__ import annotations

import gc
import json
import logging
import math
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.optimize import minimize

from oddsmarkets.f1.models import circuits as _circ
from oddsmarkets.f1.models import race_sim as _rs

logger = logging.getLogger(__name__)

OUT = _circ.CACHE / "backtest.json"
EVENTS = ("win", "podium", "points", "dnf")
EVENT_N = {"win": 1, "podium": 3, "points": 10}
EPS = 1e-4
DEFAULT_GRID_COEF = {"win": (-0.5, -0.45), "podium": (0.8, -0.35), "points": (2.6, -0.28), "dnf": (-2.2, 0.02)}
DEFAULT_BASE_DNF = 0.12


# ----------------------------------------------------------------------------------------------- helpers

def _outcomes(race: dict) -> dict[str, dict[str, int]]:
    out = {}
    for r in race.get("results") or []:
        k = _circ.status_kind(r)
        if k == "dns" or not r.get("driver"):
            continue
        cls = k == "finished"
        try:
            pos = int(r.get("position") or 99)
        except (TypeError, ValueError):
            pos = 99
        out[r["driver"]] = {"win": int(cls and pos == 1), "podium": int(cls and pos <= 3), "points": int(cls and pos <= 10),
                            "dnf": int(not cls), "grid": int(r.get("grid") or 0)}
    return out


def _season_races(year: int) -> list[tuple[int, dict]]:
    st = _circ.load_store(year)
    out = []
    for k, race in (st.get("races") or {}).items():
        if str(k).isdigit():
            out.append((int(k), race))
    return sorted(out)


def season_status(year: int, today: date | None = None) -> tuple[bool, str, list[int]]:
    """(usable, reason, rounds with results)."""
    today = today or date.today()
    races = _season_races(year)
    if not races:
        return False, "no season store on disk", []
    done = [r for r, race in races if race.get("results")]
    past = [r for r, race in races if (race.get("date") or "9999") < today.isoformat()]
    if not done:
        return False, "no results on disk yet", []
    missing = sorted(set(past) - set(done))
    if year < today.year and missing:
        return False, f"incomplete: {len(done)}/{len(races)} races with results", done
    if missing:
        return True, f"to date ({len(done)} races; missing results for {missing})", done
    return True, ("complete" if year < today.year else f"to date ({len(done)} races)"), done


def _normalise(p: dict[str, float], total: int) -> dict[str, float]:
    s = sum(p.values())
    if s <= 0:
        return p
    k = min(total, len(p)) / s
    return {d: min(1 - EPS, max(EPS, v * k)) for d, v in p.items()}


def _fit_logistic(x: np.ndarray, y: np.ndarray, x0: tuple[float, float]) -> tuple[float, float]:
    def nll(th):
        z = th[0] + th[1] * x
        return float(np.sum(np.logaddexp(0, z) - y * z)) + 1e-3 * float(th @ th)
    try:
        res = minimize(nll, np.array(x0, float), method="L-BFGS-B")
        return float(res.x[0]), float(res.x[1])
    except Exception:
        return x0


# ----------------------------------------------------------------------------------------------- baselines

class _History:
    """All races with results across the stores on disk, oldest first, with per-driver starts."""

    def __init__(self, years: Iterable[int]):
        self.races: list[tuple[int, int, dict]] = []
        for y in sorted(set(years)):
            for r, race in _season_races(y):
                if race.get("results"):
                    self.races.append((y, r, race))
        self._grid_cache: dict[tuple, dict] = {}

    def before(self, y: int, r: int) -> list[tuple[int, int, dict]]:
        return [t for t in self.races if (t[0], t[1]) < (y, r)]

    def grid_coefs(self, y: int, r: int) -> dict:
        prior_seasons = [t for t in self.races if t[0] < y]
        train = prior_seasons if len(prior_seasons) >= 3 else self.before(y, r)
        key = (y, len(train)) if prior_seasons else (y, r)
        if key in self._grid_cache:
            return self._grid_cache[key]
        if len(train) < 3:
            coefs = dict(DEFAULT_GRID_COEF)
        else:
            xs, ys = [], {e: [] for e in EVENTS}
            for _, _, race in train:
                oc = _outcomes(race)
                N = len(oc)
                for d, o in oc.items():
                    g = o["grid"] if o["grid"] > 0 else N
                    xs.append(g)
                    for e in EVENTS:
                        ys[e].append(o[e])
            x = np.array(xs, float)
            coefs = {e: _fit_logistic(x, np.array(ys[e], float), DEFAULT_GRID_COEF[e]) for e in EVENTS}
        self._grid_cache[key] = coefs
        return coefs

    def base_dnf(self, y: int, r: int) -> float:
        prior = [t for t in self.races if t[0] < y] or self.before(y, r)
        n = k = 0
        for _, _, race in prior[-60:]:
            for o in _outcomes(race).values():
                n += 1
                k += o["dnf"]
        return (k + 20 * DEFAULT_BASE_DNF) / (n + 20)


def grid_order(hist: _History, y: int, r: int, race: dict) -> dict[str, dict[str, float]]:
    oc = _outcomes(race)
    N = len(oc)
    co = hist.grid_coefs(y, r)
    out: dict[str, dict[str, float]] = {d: {} for d in oc}
    for e in EVENTS:
        a, b = co[e]
        p = {d: 1 / (1 + math.exp(-(a + b * (o["grid"] if o["grid"] > 0 else N)))) for d, o in oc.items()}
        p = _normalise(p, EVENT_N[e]) if e in EVENT_N else p
        for d in oc:
            out[d][e] = p[d]
    return out


def previous_results(hist: _History, y: int, r: int, race: dict, last: int = 5) -> dict[str, dict[str, float]]:
    oc = _outcomes(race)
    N = max(len(oc), 1)
    base = {"win": 1 / N, "podium": 3 / N, "points": 10 / N, "dnf": hist.base_dnf(y, r)}
    starts: dict[str, list[dict]] = {}
    for _, _, rc in reversed(hist.before(y, r)):
        for d, o in _outcomes(rc).items():
            if d in oc and len(starts.setdefault(d, [])) < last:
                starts[d].append(o)
        if all(len(starts.get(d, [])) >= last for d in oc):
            break
    out: dict[str, dict[str, float]] = {d: {} for d in oc}
    for e in EVENTS:
        p = {d: (sum(o[e] for o in starts.get(d, [])) + 2 * base[e]) / (len(starts.get(d, [])) + 2) for d in oc}
        p = _normalise(p, EVENT_N[e]) if e in EVENT_N else p
        for d in oc:
            out[d][e] = p[d]
    return out


def _pl_events(theta: dict[str, float], drivers: list[str], dnf: float, n: int, seed: int) -> dict[str, dict[str, float]]:
    th = np.array([theta.get(d, min(theta.values(), default=0.0) - 0.5) for d in drivers], float)
    rng = np.random.default_rng(seed)
    g = rng.gumbel(size=(n, len(drivers)))
    order = np.argsort(-(th[None, :] + g), axis=1)
    rank = np.empty_like(order)
    rank[np.arange(n)[:, None], order] = np.arange(len(drivers))[None, :]
    e = np.exp(th - th.max())
    win = e / e.sum()
    return {d: {"win": float(win[i]), "podium": float(np.mean(rank[:, i] < 3)), "points": float(np.mean(rank[:, i] < 10)), "dnf": dnf}
            for i, d in enumerate(drivers)}


class _Elo:
    def __init__(self):
        self.mod = _rs._opt("oddsmarkets.f1.models.elo")
        self.hist = None
        self.reason = None if self.mod else "oddsmarkets.f1.models.elo not importable"
        if self.mod:
            try:
                self.hist = self.mod.elo_history()
            except Exception as exc:
                self.reason = f"elo_history failed: {exc}"
                self.mod = None

    def predict(self, y, r, drivers, dnf, n, seed):
        if not self.mod:
            return None
        try:
            rb = self.mod.ratings_before(self.hist, y, r)
        except Exception as exc:
            self.reason = f"ratings_before failed: {exc}"
            return None
        known = [rb[d]["elo"] for d in drivers if d in rb]
        if not known:
            return None
        fill = float(np.mean(known)) - 100.0
        theta = {d: (rb[d]["elo"] if d in rb else fill) * math.log(10) / 400.0 for d in drivers}
        return _pl_events(theta, drivers, dnf, n, seed)


class _PL:
    def __init__(self):
        self.mod = _rs._opt("oddsmarkets.common.ranking")
        self.fit = getattr(self.mod, "fit_strengths", None) if self.mod else None
        self.reason = None if self.fit else "oddsmarkets.common.ranking.fit_strengths not importable"

    def predict(self, hist: _History, y, r, drivers, dnf, n, seed):
        if not self.fit:
            return None
        orders, fields, weights = [], [], []
        for (yy, rr, race) in hist.before(y, r):
            if yy < y - 2:
                continue
            res = race.get("results") or []
            fin = [x["driver"] for x in sorted((x for x in res if _circ.status_kind(x) == "finished"), key=lambda x: int(x.get("position") or 99))]
            field = [x["driver"] for x in res if _circ.status_kind(x) != "dns"]
            if len(fin) >= 2:
                orders.append(fin)
                fields.append(field)
                weights.append({0: 1.0, 1: 0.35, 2: 0.12}[y - yy])
        if not orders:
            return None
        try:
            theta = self.fit(orders, fields=fields, weights=weights)
        except Exception as exc:
            self.reason = f"fit_strengths failed: {exc}"
            return None
        if not theta:
            return None
        return _pl_events(theta, drivers, dnf, n, seed)


# ----------------------------------------------------------------------------------------------- scoring

def _score(rows: list[tuple[float, int]]) -> dict:
    if not rows:
        return {"n": 0}
    p = np.clip(np.array([a for a, _ in rows], float), EPS, 1 - EPS)
    y = np.array([b for _, b in rows], float)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    br = float(np.mean((p - y) ** 2))
    bins = []
    edges = np.linspace(0, 1, 11)
    for i in range(10):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < 9 else (p <= 1))
        if m.any():
            bins.append({"lo": round(edges[i], 1), "hi": round(edges[i + 1], 1), "n": int(m.sum()),
                         "mean_p": round(float(p[m].mean()), 4), "freq": round(float(y[m].mean()), 4)})
    return {"n": int(len(p)), "logloss": round(ll, 5), "brier": round(br, 5), "base_rate": round(float(y.mean()), 4), "reliability": bins}


def _rss_mb() -> float | None:
    """Resident memory of this process in MB (psutil, /proc or the Windows API; None if none works)."""
    try:
        import psutil                                              # type: ignore
        return round(psutil.Process().memory_info().rss / 1e6, 1)
    except Exception:
        pass
    try:
        with open("/proc/self/statm") as fh:
            return round(int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6, 1)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            c = PMC()
            c.cb = ctypes.sizeof(PMC)
            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return None
            return round(c.WorkingSetSize / 1e6, 1)
        except Exception:
            return None
    return None


def win_temperature(preds: list[tuple[dict[str, float], str | None]]) -> float | None:
    """The exponent T minimising -mean ln(p_w^T / sum p^T) over races (1 = calibrated spread)."""
    rows = []
    for p, winner in preds:
        if not winner or not p or winner not in p:
            continue
        v = np.clip(np.array(list(p.values()), float), EPS, None)
        rows.append((np.log(v), list(p).index(winner)))
    if len(rows) < 10:
        return None

    def f(t):
        return float(np.mean([-(t * lv[w] - np.log(np.sum(np.exp(t * lv)))) for lv, w in rows]))
    ts = np.linspace(0.3, 3.0, 271)
    vals = [f(t) for t in ts]
    return round(float(ts[int(np.argmin(vals))]), 2)


def _win_mc(preds: list[tuple[dict[str, float], str | None]]) -> dict:
    lls = []
    for p, winner in preds:
        if not winner or not p:
            continue
        s = sum(p.values())
        q = p.get(winner, 0.0) / s if s > 0 else 0.0
        lls.append(-math.log(max(q, EPS)))
    return {"n": len(lls), "logloss": round(float(np.mean(lls)), 4) if lls else None}


# ----------------------------------------------------------------------------------------------- main

def backtest(seasons: Iterable[int] = tuple(range(2014, 2027)), n_sims: int = 4000, seed: int = 0, write: bool = True,
             rounds: dict[int, list[int]] | None = None, today: date | None = None, models: Iterable[str] | None = None) -> dict:
    """Walk-forward backtest (see module docstring). Never raises on missing data; skipped seasons are listed."""
    t0 = time.perf_counter()
    mem = {"start": _rss_mb(), "peak": _rss_mb()}
    seasons = [int(s) for s in seasons]
    skipped, used, notes = {}, {}, {}
    for y in seasons:
        ok, why, done = season_status(y, today)
        if ok:
            used[y] = [r for r in done if rounds is None or r in (rounds.get(y) or [])]
            notes[y] = why
        else:
            skipped[y] = why
    hist = _History(range(min(seasons) - 3, max(seasons) + 1))
    have_a = _rs._optional_fn("season_effects", _rs._A_MODULES) is not None
    want = set(models) if models else {"model_pre", "model_post", "model_pre_results_only", "grid_order", "previous_results", "elo", "plackett_luce"}
    if not have_a:
        want.discard("model_pre_results_only")
    elo = _Elo() if "elo" in want else None
    pl = _PL() if "plackett_luce" in want else None

    rows: dict[str, dict[str, list]] = {}
    season_rows: dict[int, dict[str, dict[str, list]]] = {}
    winmc: dict[str, list] = {}
    untempered: list = []                     # model_post's win probabilities before the win temperature
    per_race = []
    errors = []
    for y, rnds in used.items():
        races = dict(_season_races(y))
        for r in rnds:
            race = races.get(r) or {}
            oc = _outcomes(race)
            if len(oc) < 2:
                continue
            winner = next((d for d, o in oc.items() if o["win"]), None)
            drivers = list(oc)
            dnf_base = hist.base_dnf(y, r)
            preds: dict[str, dict[str, dict[str, float]] | None] = {}
            sd = seed + 1000 * y + r
            for name, bq, use_a in (("model_pre", True, True), ("model_post", False, True), ("model_pre_results_only", True, False)):
                if name not in want:
                    continue
                try:
                    inp = _rs.race_inputs(y, r, before_quali=bq, use_a=use_a)
                    res = _rs.simulate_race(inp, n=n_sims, seed=sd)
                    if name == "model_post":
                        raw = {d: v["p_win"] for d, v in res["drivers"].items()}
                        untempered.append(({d: raw.get(d, 0.0) for d in drivers}, winner))
                        _rs.temper_win(res["drivers"], _rs.win_temp_post(y, r))   # walk-forward table
                    preds[name] = {d: {"win": v["p_win"], "podium": v["p_podium"], "points": v["p_points"], "dnf": v["p_dnf"]}
                                   for d, v in res["drivers"].items()}
                    del res, inp
                except Exception as exc:                       # never let one race stop the run
                    errors.append(f"{y}/{r} {name}: {exc}")
                    preds[name] = None
            if "grid_order" in want:
                preds["grid_order"] = grid_order(hist, y, r, race)
            if "previous_results" in want:
                preds["previous_results"] = previous_results(hist, y, r, race)
            if elo:
                preds["elo"] = elo.predict(y, r, drivers, dnf_base, n_sims, sd)
            if pl:
                preds["plackett_luce"] = pl.predict(hist, y, r, drivers, dnf_base, n_sims, sd)
            rec = {"year": y, "round": r, "name": race.get("name"), "winner": winner, "p_winner": {}}
            for name, P in preds.items():
                if not P:
                    continue
                N = len(drivers)
                base = {"win": 1 / N, "podium": 3 / N, "points": 10 / N, "dnf": dnf_base}
                for e in EVENTS:
                    for d in drivers:
                        p = (P.get(d) or {}).get(e, base[e])
                        rows.setdefault(name, {}).setdefault(e, []).append((p, oc[d][e]))
                        season_rows.setdefault(y, {}).setdefault(name, {}).setdefault(e, []).append((p, oc[d][e]))
                wp = {d: (P.get(d) or {}).get("win", 1 / N) for d in drivers}
                winmc.setdefault(name, []).append((wp, winner))
                if winner:
                    s = sum(wp.values())
                    rec["p_winner"][name] = round(wp.get(winner, 0) / s, 4) if s else None
            per_race.append(rec)
            del preds
            gc.collect()                                   # one race at a time: nothing but the scores survives
            m = _rss_mb()
            if m is not None and (mem["peak"] is None or m > mem["peak"]):
                mem["peak"] = m
        logger.info("backtest %d done: %d races so far, %.0f s, rss %s MB", y, len(per_race), time.perf_counter() - t0, _rss_mb())
    metrics = {name: {e: _score(v) for e, v in ev.items()} for name, ev in rows.items()}
    for name in metrics:
        metrics[name]["win_multiclass"] = _win_mc(winmc.get(name, []))
        metrics[name]["win_temperature"] = win_temperature(winmc.get(name, []))
    per_season = {str(y): {name: {e: {k: v for k, v in _score(x).items() if k != "reliability"} for e, x in ev.items()} for name, ev in d.items()}
                  for y, d in season_rows.items()}
    unavailable = {}
    if elo and (elo.reason or "elo" not in metrics):
        unavailable["elo"] = elo.reason or "no ratings before these races"
    if pl and (pl.reason or "plackett_luce" not in metrics):
        unavailable["plackett_luce"] = pl.reason or "no earlier finishing orders"
    if not have_a:
        unavailable["A_pace"] = "Builder A's season_effects not importable: model uses the results-only estimator"
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "n_sims": n_sims,
        "seasons_used": {str(y): notes[y] for y in used}, "skipped": {str(y): v for y, v in skipped.items()},
        "races": len(per_race), "pre_quali_models": [m for m in ("model_pre", "model_pre_results_only", "previous_results", "elo", "plackett_luce") if m in metrics],
        "post_quali_models": [m for m in ("model_post", "grid_order") if m in metrics],
        "metrics": metrics, "per_season": per_season, "per_race": per_race, "unavailable": unavailable, "errors": errors[:50],
        "runtime_s": round(time.perf_counter() - t0, 1), "memory_mb": {**mem, "end": _rss_mb()},
        "race_params": getattr(_rs, "FITTED", {}).get("params") or {},
        "model_post_untempered": {"win_multiclass": _win_mc(untempered), "win_temperature": win_temperature(untempered)},
    }
    if write:
        try:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            tmp = OUT.with_suffix(".tmp")
            tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
            tmp.replace(OUT)
        except OSError as exc:
            out["write_error"] = str(exc)
    return out


def summary_table(bt: dict) -> list[dict]:
    """Flat rows {model, event, logloss, brier, n} for printing."""
    rows = []
    for m, ev in (bt.get("metrics") or {}).items():
        for e in (*EVENTS, "win_multiclass"):
            v = ev.get(e) or {}
            if v.get("n"):
                rows.append({"model": m, "event": e, "logloss": v.get("logloss"), "brier": v.get("brier"), "n": v["n"]})
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Walk-forward backtest of the F1 race simulator (writes data/f1/cache/backtest.json)")
    ap.add_argument("--from", dest="start", type=int, default=2014)
    ap.add_argument("--to", dest="end", type=int, default=date.today().year)
    ap.add_argument("--sims", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = backtest(range(args.start, args.end + 1), n_sims=args.sims, seed=args.seed)
    for row in summary_table(out):
        if row["event"] == "win_multiclass":
            print(f"{row['model']:24s} winner log-loss {row['logloss']}  (n={row['n']})")
    print("races", out["races"], "runtime", out["runtime_s"], "s", "memory", out["memory_mb"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
