"""
Walk-forward backtest of the tennis match model, its baselines, the score distributions and the tournament
simulator, per tour. Output feeds the Calibration page.

Matches scored: tour-level singles (slam, finals, m1000, 500, 250) with status "done" (retirements,
walkovers and defaults are excluded from scoring because bookmakers settle them differently; they still
feed the ratings), in the chosen years (default 2010 onward). Each match is oriented at random
(a fixed hash of its id), so y is 0 or 1 and the reliability bins are meaningful (p1 is the winner in the stores).

Predictions, all made before the match from data strictly before it:
* ``elo``: builder B's surface Elo pre-match probability (`elo.pre_match`; ratings run sequentially, so
  they are walk-forward; Elo's constants are B's frozen fit, tuned on 2005-2019 log-loss).
* ``serve_return``: B's serve/return model refitted every `refit_days` (default 30, warm-started) on
  matches dated before the refit date, priced through the exact chain.
* ``model``: the logit blend w_elo logit(elo) + w_sr logit(sr) (predict.py); the weights for year Y are
  fitted on the predictions of the earlier years only (the first scored year uses predict.DEFAULT_BLEND
  unless warm-up years exist; by default two warm-up years precede the first scored year).
* ``rank``: logistic in log(rank2) - log(rank1) (missing rank -> RANK_FILL), slope fitted on earlier years.
* ``pinnacle``, ``b365``, ``avg``, ``max``: tennis-data closing odds de-vigged multiplicatively, where present.
Every model is also scored on the matches that carry Pinnacle odds ("vs_pinnacle") and those with average
odds ("vs_avg"), so model and market are compared on identical matches.

Scores: log-loss -mean(y ln p + (1-y) ln(1-p)) (p clipped to [1e-4, 1-1e-4]), Brier mean((p-y)^2), 10-bin
reliability; per year and per level.

Score distributions (model's chain with match-level dispersion sigma, fitted walk-forward per year from the
set-score likelihood of earlier years over SIGMA_GRID; completed best-of-3/5 matches with full set scores):
* set-score calibration: mean predicted P of each set score ("2-0", "2-1", ...) v observed share, plus the
  multi-class log-loss of the set score;
* P(straight sets) and P(at least one tiebreak): reliability and log-loss;
* total games: P(over L) calibration at standard lines (bo3: 19.5 .. 25.5; bo5: 33.5 .. 41.5), mean
  predicted v observed total, and a randomized PIT histogram (10 bins; flat = calibrated);
* live win probability at set boundaries: P(p1 wins) from the chain after each completed set (server of the
  next set averaged), scored overall and by sets score ("bo3 1-0", ...).

Tournaments (completed knockouts in the scored years): the bracket is rebuilt from the results
(tournament_sim.bracket_from_results), every entrant priced with the Elo ratings they carried into their
first match and the serve/return fit current at the start, and tournament_sim run at two checkpoints:
"pre" (nothing fixed) and "qf" (results before the quarter-finals fixed). p_title, p_final and p_sf are
scored against what happened.

Validation (WTA): `validate_hold` fits the score-only serve/return model (stats=False) over a window and
compares each player's inferred hold % and serve-points-won % (averaged over her matches with WTA stats,
against those opponents) with the real numbers from the WTA match stats.

Results: <ACE_CACHE>/backtest_<tour>.json (full) and docs/ace/data/<tour>/calibration.json (page copy).
"""
from __future__ import annotations

import bisect
import hashlib
import json
import logging
import math
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.models import match_chain as mc
from oddsmarkets.tennis.models import predict as PR
from oddsmarkets.tennis.models import tournament_sim as TS
from oddsmarkets.common.edge import devig as _dv

logger = logging.getLogger(__name__)
VERSION = "backtest-1"
EPS = 1e-4
SCORED_LEVELS = ("slam", "finals", "m1000", "500", "250")
RANK_FILL = 300
REFIT_DAYS = 30
WARMUP_YEARS = 2
LINES = {3: [19.5, 20.5, 21.5, 22.5, 23.5, 24.5, 25.5], 5: [33.5, 35.5, 37.5, 39.5, 41.5]}
BOOKS = {"pinnacle": "ps", "b365": "b365", "avg": "avg", "max": "max"}


# ── scoring ──────────────────────────────────────────────────────────────────

def score(rows: list[tuple[float, int]], bins: int = 10) -> dict:
    """{"n","logloss","brier","base_rate","mean_p","reliability": [{"lo","hi","n","mean_p","freq"}]}"""
    if not rows:
        return {"n": 0}
    p = np.clip(np.array([a for a, _ in rows], float), EPS, 1 - EPS)
    y = np.array([b for _, b in rows], float)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    br = float(np.mean((p - y) ** 2))
    rel = []
    edges = np.linspace(0, 1, bins + 1)
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= 1))
        if m.any():
            rel.append({"lo": round(edges[i], 2), "hi": round(edges[i + 1], 2), "n": int(m.sum()),
                        "mean_p": round(float(p[m].mean()), 4), "freq": round(float(y[m].mean()), 4)})
    return {"n": int(len(p)), "logloss": round(ll, 5), "brier": round(br, 5), "base_rate": round(float(y.mean()), 4),
            "mean_p": round(float(p.mean()), 4), "reliability": rel}


def _brief(s: dict) -> dict:
    return {k: v for k, v in s.items() if k != "reliability"}


def flip(mid: str) -> bool:
    """A fixed pseudo-random orientation per match id."""
    return int(hashlib.md5(str(mid).encode()).hexdigest()[:8], 16) % 2 == 1


def devig2(o) -> float | None:
    try:
        a, b = float(o[0]), float(o[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not (a > 1.0 and b > 1.0) or not (math.isfinite(a) and math.isfinite(b)):
        return None
    return _dv.multiplicative_pair(a, b)[0]          # common/edge/devig.py


def fit_rank_slope(x: np.ndarray, y: np.ndarray) -> float:
    """MLE slope b of P = sigmoid(b x) (no intercept)."""
    if len(x) < 50:
        return 0.5
    b = 0.5
    for _ in range(40):
        p = 1 / (1 + np.exp(-b * x))
        g = float(x @ (y - p))
        h = float(-(x * x) @ (p * (1 - p)))
        if h == 0:
            break
        step = g / h
        b -= step
        if abs(step) < 1e-10:
            break
    return float(b)


# ── score distributions ──────────────────────────────────────────────────────

def observed(m: dict) -> dict | None:
    """Observed {"sets": (s1, s2), "games": total, "margin": g1-g2, "tb": bool} from p1's view, complete sets only."""
    sets = m.get("sets") or []
    s1 = s2 = g = d = 0
    tb = False
    for k, s in enumerate(sets):
        try:
            a, b = int(s[0]), int(s[1])
        except (TypeError, ValueError, IndexError):
            return None
        hi, lo = max(a, b), min(a, b)
        ok = (hi == 6 and lo <= 4) or (hi == 7 and lo in (5, 6)) or (hi == 13 and lo == 12)             or (hi > 7 and hi - lo == 2 and hi <= 40 and k == len(sets) - 1)
        if not ok:
            return None                                   # an impossible or truncated set score in the source
        g += a + b
        d += a - b
        s1 += a > b
        s2 += b > a
        tb = tb or (max(a, b) == min(a, b) + 1 and max(a, b) in (7, 13)) or (len(s) > 2 and s[2] is not None)
    need = 3 if int(m.get("best_of") or 3) == 5 else 2
    if max(s1, s2) != need:
        return None
    return {"sets": (s1, s2), "games": g, "margin": d, "tb": tb}


def _pit(games_dist: np.ndarray, x: int, rng) -> float:
    cdf = np.cumsum(games_dist)
    if x >= len(cdf):
        return float(1.0 - rng.random() * 1e-6)
    lo = cdf[x - 1] if x >= 1 else 0.0
    hi = cdf[x]
    return float(lo + rng.random() * (hi - lo))


# ── walk-forward ─────────────────────────────────────────────────────────────

def _month_starts(a: date, b: date, step: int) -> list[date]:
    out = []
    d = a
    while d <= b:
        out.append(d)
        if step >= 28:
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        else:
            d = d + timedelta(days=step)
    return out


def _rule(m: dict) -> str:
    bo = 5 if int(m.get("best_of") or 3) == 5 else 3
    ev = str(m.get("event") or "")
    tid = ev.rsplit("-", 1)[0] if "-" in ev else None
    y = (_io.day(m.get("date")) or date(2026, 1, 1)).year
    r = str(m.get("final_set_rule") or "")
    if tid == "wimbledon" and 2019 <= y <= 2021:
        return "tb12"
    return r if r in mc.RULES else PR.default_final_rule(m.get("level"), bo, y, tid)


def _sr_fit(S, matches, through: date, prior, consts: dict, tour: str, cache_dir: Path | None, use_cache: bool,
            n_window: int = 0):
    """(model, cache path | None)."""
    key = None
    if cache_dir is not None and use_cache:
        # keyed on the date, the constants and the number of matches in the window (the data it saw)
        tag = _io.file_key(consts, n_window)[:10]
        key = cache_dir / f"sr_{tour}_{through.isoformat()}_{n_window}_{tag}.json"
        c = _io.read_json(key)
        if isinstance(c, dict) and c.get("players") is not None:
            return c, key
    mdl = S.fit(matches, through=through, half_life_days=consts.get("half_life_days"),
                ridge={"s": consts.get("ridge", 2.0), "delta": consts.get("ridge_delta", 8.0), "base": consts.get("ridge_base", 1.0)},
                prior=prior, stats=False, window_days=consts.get("window_days"))
    if key is not None and not _io.write_json(key, mdl):
        key = None
    return mdl, key


def predictions(tour: str, matches: list[dict], years: Iterable[int], refit_days: int = REFIT_DAYS,
                warmup_years: int = WARMUP_YEARS, elo_hist: dict | None = None, sr_mod=None, elo_mod=None,
                use_cache: bool = True, log=None, gelo_hist: dict | None = None,
                mr_hist: dict | None = None) -> tuple[list[dict], dict]:
    """
    Walk-forward predictions for every scorable match of the chosen years plus the warm-up years:
    rows {"id","year","level","bo","rule","y","flip","elo","sr","gelo","mr","pa","pb","rank_x","books": {..},"obs",
    "event","date"} ("gelo": the game-share Elo difference for p1 before the match, gelo.py, sequential like Elo;
    "mr": the market-rating difference for p1 on the match's logit scale, mrating.py, from earlier matches' closing
    prices and results only).
    Returns (rows, sr_fits {checkpoint iso: cache path, or the model when not cached}) - reused by the
    tournament checkpoints, which load one fit at a time.
    """
    t = _io.tour_key(tour)
    years = sorted(set(int(y) for y in years))
    first = years[0] - warmup_years
    E = elo_mod or PR._mod("elo")
    S = sr_mod or PR._mod("serve_return")
    hist = elo_hist or (E.history(t, matches=matches) if E is not None else {"rows": []})
    from oddsmarkets.tennis.models import gelo as G
    gpre = G.pre_match(gelo_hist or G.history(t, matches=sorted(matches, key=_io.match_key)))
    from oddsmarkets.tennis.models import mrating as MRt
    mh = mr_hist or MRt.history(t, matches=matches)
    mpre = MRt.pre_match(mh)
    mprm = mh.get("params") or MRt.params(t)
    pre = E.pre_match(hist) if E is not None else {}
    from oddsmarkets.tennis.models import sched as SC
    xpre = SC.history(t, matches=matches, elo_pre=pre)["pre"] if SC.on(t) else {}
    consts = S.constants(t) if (S is not None and hasattr(S, "constants")) else {}
    rated = [m for m in matches if m.get("status") in _io.RATED_STATUS]
    rated_days = sorted(_io.day(m["date"]).toordinal() for m in rated if _io.day(m.get("date")))
    want = [m for m in matches if m.get("status") == "done" and str(m.get("level")) in SCORED_LEVELS
            and _io.day(m.get("date")) and first <= _io.day(m["date"]).year <= years[-1] and m.get("p1") and m.get("p2")]
    want.sort(key=_io.match_key)
    cache_dir = _io.cache_root() / "backtest_sr"
    rows: list[dict] = []
    fits: dict = {}
    if not want:
        return rows, fits
    starts = _month_starts(date(first, 1, 1), _io.day(want[-1]["date"]), refit_days)
    prior = None
    k = 0
    t0 = time.time()
    for i, st in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else date(9999, 1, 1)
        batch = []
        while k < len(want) and _io.day(want[k]["date"]) < nxt:
            batch.append(want[k])
            k += 1
        mdl = None
        if S is not None:
            th = st - timedelta(days=1)
            wd = float(consts.get("window_days") or 1460)
            nw = bisect.bisect_right(rated_days, th.toordinal()) - bisect.bisect_right(rated_days, th.toordinal() - wd)
            mdl, path = _sr_fit(S, rated, th, prior, consts, t, cache_dir, use_cache, nw)
            prior = mdl
            # keep the cache path, not the model: ~200 monthly fits in memory was the bulk of the footprint
            fits[st.isoformat()] = path if path is not None else mdl
        if log and i % 12 == 0:
            log(f"{t} {st} fits={len(fits)} rows={len(rows)} {time.time() - t0:.0f}s")
        if not batch:
            continue
        pa = np.zeros(len(batch))
        pb = np.zeros(len(batch))
        has = np.zeros(len(batch), bool)
        for j, m in enumerate(batch):
            if mdl is not None:
                try:
                    h1 = S.hold_prob(mdl, m["p1"], m["p2"], m.get("surface"), m.get("level"), int(m.get("best_of") or 3),
                                     bool(m.get("indoor")))
                    h2 = S.hold_prob(mdl, m["p2"], m["p1"], m.get("surface"), m.get("level"), int(m.get("best_of") or 3),
                                     bool(m.get("indoor")))
                    pa[j], pb[j] = float(S.point_prob_from_hold(h1)), float(S.point_prob_from_hold(h2))
                    has[j] = True
                except Exception:  # noqa: BLE001
                    pass
        groups: dict = {}
        for j, m in enumerate(batch):
            groups.setdefault((5 if int(m.get("best_of") or 3) == 5 else 3, _rule(m)), []).append(j)
        srp = np.full(len(batch), np.nan)
        for (bo, rule), idx in groups.items():
            ix = np.array(idx)
            ok = ix[has[ix]]
            if len(ok):
                srp[ok] = mc.match_win_prob(pa[ok], pb[ok], bo, rule)
        for j, m in enumerate(batch):
            fl = flip(m["id"])
            e = pre.get(m["id"])
            r1 = m.get("rank1") or RANK_FILL
            r2 = m.get("rank2") or RANK_FILL
            try:
                rx = math.log(float(r2)) - math.log(float(r1))
            except (TypeError, ValueError):
                rx = 0.0
            books = {k_: devig2((m.get("odds") or {}).get(v)) for k_, v in BOOKS.items()}
            row = {"id": m["id"], "date": str(m["date"])[:10], "year": _io.day(m["date"]).year, "level": str(m.get("level")),
                   "event": m.get("event"), "bo": 5 if int(m.get("best_of") or 3) == 5 else 3, "rule": _rule(m),
                   "elo": e, "sr": float(srp[j]) if math.isfinite(srp[j]) else None,
                   "gelo": float(gpre.get(m["id"]) or 0.0),
                   "mr": MRt.scale(m.get("best_of"), mprm) * float(mpre.get(m["id"]) or 0.0),
                   **({"x": xpre.get(m["id"])} if xpre else {}),
                   "pa": float(pa[j]) if has[j] else None, "pb": float(pb[j]) if has[j] else None,
                   "rank_x": rx, "books": {k_: v for k_, v in books.items() if v is not None},
                   "obs": observed(m), "flip": fl, "p1": m["p1"], "p2": m["p2"],
                   "_sets": [[int(x[0]), int(x[1])] for x in (m.get("sets") or []) if x and x[0] is not None and x[1] is not None]}
            rows.append(row)
    return rows, fits


def _orient(p, fl):
    return None if p is None else (1.0 - p if fl else p)


def _gorient(r: dict) -> float:
    """The row's game-share Elo difference in its random orientation (antisymmetric: negated when flipped)."""
    g = float(r.get("gelo") or 0.0)
    return -g if r["flip"] else g


def _morient(r: dict) -> float:
    """The row's market-rating difference in its random orientation."""
    g = float(r.get("mr") or 0.0)
    return -g if r["flip"] else g


def _xorient(r: dict) -> list:
    """The row's schedule / form terms (sched.py) in its random orientation (all antisymmetric)."""
    x = [float(v) for v in (r.get("x") or [0.0] * 6)]
    return [-v for v in x] if r["flip"] else x


def evaluate(rows: list[dict], years: Iterable[int], seed: int = 0, tour: str = "atp", mr: bool = True) -> dict:
    """Scores for the scored years; blend and rank slope fitted on earlier years (walk-forward). A year with
    no earlier predictions to fit on uses `tour`'s own blend (predict.blend_params: the committed fit, else
    that tour's default), never another tour's. `mr` False leaves the market-rating term out (the fundamental
    blend: "model_fund" is scored alongside in every case)."""
    years = sorted(set(int(y) for y in years))
    own = PR.blend_params(tour)
    by_year: dict = {}
    for r in rows:
        by_year.setdefault(r["year"], []).append(r)
    allm: dict = {}
    vs_ps: dict = {}
    vs_avg: dict = {}
    per_year: dict = {}
    per_level: dict = {}
    blend_by_year: dict = {}
    rank_by_year: dict = {}
    scored: list[dict] = []
    for Y in years:
        early = [r for yy, rs in by_year.items() if yy < Y for r in rs]
        both = [r for r in early if r["elo"] is not None and r["sr"] is not None]
        bf = {"w_elo": None}
        use_g = bool(both) and all("gelo" in r for r in both)
        use_m = use_g and mr and all("mr" in r for r in both)
        use_x = use_m and all(r.get("x") is not None for r in both)
        wn = None
        if both:
            # fit on the oriented targets (p1 is the winner in the stores, so unoriented y would be all ones)
            bf = PR.fit_blend([_orient(r["elo"], r["flip"]) for r in both], [_orient(r["sr"], r["flip"]) for r in both],
                              [0 if r["flip"] else 1 for r in both],
                              gdiff=[_gorient(r) for r in both] if use_g else None,
                              mdiff=[_morient(r) for r in both] if use_m else None,
                              xmat=[_xorient(r) for r in both] if use_x else None)
            if use_x:
                # the same blend without the schedule / form terms ("model_nox": the 21 October price)
                bn = PR.fit_blend([_orient(r["elo"], r["flip"]) for r in both], [_orient(r["sr"], r["flip"]) for r in both],
                                  [0 if r["flip"] else 1 for r in both], gdiff=[_gorient(r) for r in both],
                                  mdiff=[_morient(r) for r in both])
                if bn.get("w_elo") is not None:
                    wn = (bn["w_elo"], bn["w_sr"], float(bn.get("w_gelo") or 0.0), float(bn.get("w_mr") or 0.0))
        wf = None
        if both and use_m:
            bf3 = PR.fit_blend([_orient(r["elo"], r["flip"]) for r in both], [_orient(r["sr"], r["flip"]) for r in both],
                               [0 if r["flip"] else 1 for r in both], gdiff=[_gorient(r) for r in both])
            if bf3.get("w_elo") is not None:
                wf = (bf3["w_elo"], bf3["w_sr"], float(bf3.get("w_gelo") or 0.0))
        if bf.get("w_elo") is not None:
            w = (bf["w_elo"], bf["w_sr"], float(bf.get("w_gelo") or 0.0), float(bf.get("w_mr") or 0.0), bf.get("w_x") or {})
        else:
            w = (float(own["w_elo"]), float(own["w_sr"]), float(own.get("w_gelo") or 0.0),
                 float(own.get("w_mr") or 0.0) if mr else 0.0, (own.get("w_x") or {}) if mr else {})
        blend_by_year[str(Y)] = {"w_elo": round(w[0], 4), "w_sr": round(w[1], 4), "w_gelo": round(w[2], 4),
                                 "w_mr": round(w[3], 4), "n_fit": bf.get("n", 0), "fitted": bf.get("w_elo") is not None,
                                 **({"w_x": {k: round(v, 4) for k, v in w[4].items()}} if w[4] else {})}
        rk = [r for r in early]
        x = np.array([(-r["rank_x"] if r["flip"] else r["rank_x"]) for r in rk])
        yv = np.array([0 if r["flip"] else 1 for r in rk], float)
        b = fit_rank_slope(x, yv) if len(rk) else 0.5
        rank_by_year[str(Y)] = round(b, 4)
        for r in by_year.get(Y, []):
            y = 0 if r["flip"] else 1
            preds = {}
            if r["elo"] is not None:
                preds["elo"] = r["elo"]
            if r["sr"] is not None:
                preds["serve_return"] = r["sr"]
            if r["elo"] is not None and r["sr"] is not None:
                xd = None
                if w[4] and r.get("x") is not None:
                    from oddsmarkets.tennis.models import sched as SC
                    xd = SC.dot(r["x"], w[4])
                preds["model"] = float(PR.blend(r["elo"], r["sr"], w[0], w[1], r.get("gelo") or 0.0, w[2],
                                                r.get("mr") or 0.0, w[3], xd))
                if wn is not None:
                    preds["model_nox"] = float(PR.blend(r["elo"], r["sr"], wn[0], wn[1], r.get("gelo") or 0.0, wn[2],
                                                        r.get("mr") or 0.0, wn[3]))
            elif r["elo"] is not None:
                preds["model"] = r["elo"]
            if wf is not None and r["elo"] is not None and r["sr"] is not None:
                preds["model_fund"] = float(PR.blend(r["elo"], r["sr"], wf[0], wf[1], r.get("gelo") or 0.0, wf[2]))
            preds["rank"] = float(1 / (1 + math.exp(-b * r["rank_x"])))
            for k, v in r["books"].items():
                preds[k] = v
            r["_model"] = preds.get("model")
            for k, p in preds.items():
                po = _orient(p, r["flip"])
                allm.setdefault(k, []).append((po, y))
                per_year.setdefault(str(Y), {}).setdefault(k, []).append((po, y))
                per_level.setdefault(r["level"], {}).setdefault(k, []).append((po, y))
                if "pinnacle" in r["books"]:
                    vs_ps.setdefault(k, []).append((po, y))
                if "avg" in r["books"]:
                    vs_avg.setdefault(k, []).append((po, y))
            scored.append(r)
    return {"metrics": {k: score(v) for k, v in allm.items()},
            "vs_pinnacle": {k: _brief(score(v)) for k, v in vs_ps.items()},
            "vs_avg": {k: _brief(score(v)) for k, v in vs_avg.items()},
            "per_year": {y: {k: _brief(score(v)) for k, v in d.items()} for y, d in per_year.items()},
            "per_level": {lv: {k: _brief(score(v)) for k, v in d.items()} for lv, d in per_level.items()},
            "blend_by_year": blend_by_year, "rank_slope_by_year": rank_by_year, "_scored": scored}


CHUNK = 2000


def _chunked(groups: dict, size: int = CHUNK):
    """(key, index list) pairs with at most `size` indices each (bounded memory for the mixture's expansion)."""
    for k, idx in groups.items():
        for a in range(0, len(idx), size):
            yield k, idx[a:a + size]


SIGMA_GRID = (0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08)


def _set_loglik(rows: list[dict], sigma: float) -> np.ndarray:
    """log P(observed set score) per row under the dispersion mixture with `sigma`."""
    out = np.zeros(len(rows))
    groups: dict = {}
    for i, r in enumerate(rows):
        groups.setdefault((r["bo"], r["rule"]), []).append(i)
    for (bo, rule), idx in _chunked(groups):
        pa = np.array([rows[i]["pa"] for i in idx])
        pb = np.array([rows[i]["pb"] for i in idx])
        tgt = np.array([rows[i]["_model"] for i in idx])
        dl = mc.solve_shift(tgt, pa, pb, bo, rule, iters=30, sigma=sigma)
        d = mc.match_mix(pa + dl, pb - dl, bo, rule, sigma=sigma)
        for k, i in enumerate(idx):
            s1, s2 = rows[i]["obs"]["sets"]
            v = d["sets"].get(f"{s1}-{s2}")
            out[i] = math.log(max(float(v[k]), 1e-9)) if v is not None else math.log(1e-9)
    return out


def fit_sigma(rows: list[dict], years: list[int], grid=SIGMA_GRID, default: float = 0.03) -> tuple[dict, dict]:
    """Walk-forward sigma per year (max set-score likelihood on earlier scored years) and the grid's means."""
    ll = {sg: _set_loglik(rows, sg) for sg in grid}
    yr = np.array([r["year"] for r in rows])
    by_year = {}
    for Y in years:
        m = yr < Y
        by_year[str(Y)] = float(max(grid, key=lambda sg: ll[sg][m].sum())) if m.sum() >= 500 else default
    totals = {str(sg): round(float(v.mean()), 5) for sg, v in ll.items()}
    return by_year, totals


def distributions(scored: list[dict], seed: int = 0, sigma: Any = 0.0) -> dict:
    """Set-score, straight-sets, tiebreak and total-games calibration of the model's chain. `sigma` is the
    dispersion (a number, or "fit": walk-forward per year over SIGMA_GRID)."""
    rng = np.random.default_rng(seed)
    rows = [r for r in scored if r.get("obs") and r.get("pa") is not None and r.get("_model") is not None]
    out: dict = {"n": len(rows)}
    if not rows:
        return out
    if sigma == "fit":
        years = sorted({r["year"] for r in rows})
        sby, grid_ll = fit_sigma(rows, years)
        out["sigma_by_year"], out["sigma_grid_mean_loglik"] = sby, grid_ll
        out["sigma_all_years"] = float(max(grid_ll, key=lambda k: grid_ll[k]))
        for r in rows:
            r["_sigma"] = sby[str(r["year"])]
    else:
        for r in rows:
            r["_sigma"] = float(sigma or 0.0)
        out["sigma_all_years"] = float(sigma or 0.0)
    groups: dict = {}
    for i, r in enumerate(rows):
        groups.setdefault((r["bo"], r["rule"], r["_sigma"]), []).append(i)
    groups = dict(((k, n), v) for n, (k, v) in enumerate(_chunked(groups)))
    set_acc: dict = {}
    set_ll = {3: [], 5: []}
    straight, tieb = [], []
    over: dict = {}
    pits = {3: [], 5: []}
    mean_tot = {3: [[], []], 5: [[], []]}
    hcap_ll = []
    live_acc: dict = {}
    live_all: list = []
    for ((bo, rule, sg), _n), idx in groups.items():
        pa = np.array([rows[i]["pa"] for i in idx])
        pb = np.array([rows[i]["pb"] for i in idx])
        tgt = np.array([rows[i]["_model"] for i in idx])
        dl = mc.solve_shift(tgt, pa, pb, bo, rule, iters=30, sigma=sg)
        d = mc.match_mix(pa + dl, pb - dl, bo, rule, sigma=sg)
        dl0 = mc.solve_shift(tgt, pa, pb, bo, rule, iters=30)            # live: the centre pair (no mixture)
        lt = mc.LiveTable(pa + dl0, pb - dl0, bo, rule)
        need = bo // 2 + 1
        live_p = {(a, b): lt.p((a, b), (0, 0), None) for a in range(need) for b in range(need) if a + b > 0}
        for k, i in enumerate(idx):
            r = rows[i]
            o = r["obs"]
            fl = r["flip"]
            s1, s2 = o["sets"]
            lab = f"{s1}-{s2}"                                  # store orientation (p1 = winner)
            # live calibration at set boundaries: P(p1 wins) after each completed set (oriented at random)
            a_ = b_ = 0
            for sset in (rows[i].get("_sets") or [])[:-1]:
                a_ += sset[0] > sset[1]
                b_ += sset[1] > sset[0]
                pk = float(live_p[(a_, b_)][k])
                st_lab = f"bo{bo} {b_}-{a_}" if fl else f"bo{bo} {a_}-{b_}"
                live_acc.setdefault(st_lab, []).append((1 - pk if fl else pk, 0 if fl else 1))
                live_all.append((1 - pk if fl else pk, 0 if fl else 1))
            # calibration in the match's random orientation: swap predicted and observed labels together
            for key, v in d["sets"].items():
                a_, b_ = key.split("-")
                key_o = f"{b_}-{a_}" if fl else key
                lab_o = f"{s2}-{s1}" if fl else lab
                acc_ = set_acc.setdefault(bo, {}).setdefault(key_o, [0.0, 0, 0])
                acc_[0] += float(v[k])
                acc_[1] += int(key_o == lab_o)
                acc_[2] += 1
            pobs = float(d["sets"][lab][k]) if lab in d["sets"] else 1e-9
            set_ll[bo].append(-math.log(max(pobs, 1e-9)))
            straight.append((float(d["p_straight"][k]), int(min(s1, s2) == 0)))
            tieb.append((float(d["p_tiebreak"][k]), int(o["tb"])))
            gd = d["games"][k]
            G = int(o["games"])
            cdf = np.cumsum(gd)
            for L in LINES[bo]:
                p_over = float(1 - cdf[int(math.floor(L))]) if int(math.floor(L)) < len(cdf) else 0.0
                over.setdefault((bo, L), []).append((p_over, int(G > L)))
            pits[bo].append(_pit(gd, G, rng))
            mean_tot[bo][0].append(float(d["exp_games"][k]))
            mean_tot[bo][1].append(G)
            H = d["handicap_offset"]
            mg = o["margin"]
            hp = float(d["handicap"][k][H + mg]) if 0 <= H + mg < d["handicap"].shape[1] else 1e-9
            hcap_ll.append(-math.log(max(hp, 1e-9)))
    out["set_scores"] = {str(bo): {k: {"pred": round(v[0] / v[2], 4), "obs": round(v[1] / v[2], 4), "n": v[2]}
                                   for k, v in sorted(acc.items())} for bo, acc in set_acc.items()}
    out["set_score_logloss"] = {str(bo): round(float(np.mean(v)), 4) for bo, v in set_ll.items() if v}
    out["straight_sets"] = score(straight)
    out["tiebreak"] = score(tieb)
    out["total_games"] = {
        "over_lines": {f"bo{bo}_{L}": _brief(score(v)) for (bo, L), v in sorted(over.items())},
        "mean": {str(bo): {"pred": round(float(np.mean(v[0])), 3), "obs": round(float(np.mean(v[1])), 3), "n": len(v[1])}
                 for bo, v in mean_tot.items() if v[0]},
        "pit_hist": {str(bo): [int(x) for x in np.histogram(v, bins=10, range=(0, 1))[0]] for bo, v in pits.items() if v},
    }
    out["handicap_logloss"] = round(float(np.mean(hcap_ll)), 4) if hcap_ll else None
    out["live_by_sets"] = {"all": score(live_all), "by_state": {k: _brief(score(v)) for k, v in sorted(live_acc.items())}}
    return out


# ── tournaments ──────────────────────────────────────────────────────────────

def _gelo_pre_ratings(t: str, matches: list[dict]) -> tuple[dict, dict]:
    """({(match id, pid): the player's game-share ratings before that match}, params), one sequential pass."""
    from oddsmarkets.tennis.models import gelo as G
    h = G.history(t, matches=sorted(matches, key=_io.match_key))
    cur: dict = {}
    out: dict = {}
    for g in h.get("rows") or []:
        for pid, ai, si in ((g[2], 6, 7), (g[3], 8, 9)):
            rec = cur.get(pid)
            if rec is not None:
                out[(g[0], pid)] = dict(rec)
            else:
                rec = cur[pid] = {"all": 0.0, "hard": 0.0, "clay": 0.0, "grass": 0.0}
        for pid, ai, si in ((g[2], 6, 7), (g[3], 8, 9)):
            cur[pid]["all"] = g[ai]
            cur[pid][g[4]] = g[si]
    return out, h.get("params")


def tournaments(tour: str, matches: list[dict], events: dict, years: Iterable[int], fits: dict, elo_hist: dict,
                n: int = 5000, seed: int = 0, sr_mod=None, elo_mod=None, w: tuple | None = None, max_events: int | None = None,
                log=None) -> dict:
    """Tournament-odds calibration at the "pre" and "qf" checkpoints (module docstring)."""
    t = _io.tour_key(tour)
    S = sr_mod or PR._mod("serve_return")
    E = elo_mod or PR._mod("elo")
    years = set(int(y) for y in years)
    byev: dict = {}
    for m in matches:
        byev.setdefault(m.get("event"), []).append(m)
    # pre-match ratings of each player at each match
    pre_r: dict = {}
    for g in (elo_hist or {}).get("rows") or []:
        pre_r[(g[0], g[2])] = (g[8], g[9], g[4])
        pre_r[(g[0], g[3])] = (g[10], g[11], g[4])
    params = (elo_hist or {}).get("params")
    gpre_r, gparams = _gelo_pre_ratings(t, matches) if (w and len(w) > 2 and w[2]) else ({}, None)
    msnap, mparams = {}, None
    if w and len(w) > 3 and w[3]:
        from oddsmarkets.tennis.models import mrating as MRt
        mparams = MRt.params(t)
        wants: dict = {}
        for eid_, ev_ in (events or {}).items():
            if str(ev_.get("level")) in ("slam", "m1000", "500", "250") and int(ev_.get("year") or 0) in years:
                d0 = _io.day(ev_.get("start"))
                if d0 is not None:
                    wants.setdefault(d0.toordinal(), set()).update(
                        str(p) for m in byev.get(eid_, []) for p in (m.get("p1"), m.get("p2")) if p)
        msnap = MRt.snapshots(MRt.prepare(sorted(matches, key=_io.match_key), max_margin=mparams["max_margin"]),
                              mparams, wants)
    xsnap = {}
    if w and len(w) > 4 and w[4]:
        from oddsmarkets.tennis.models import sched as SC
        wants_x: dict = {}
        for eid_, ev_ in (events or {}).items():
            if str(ev_.get("level")) in ("slam", "m1000", "500", "250") and int(ev_.get("year") or 0) in years:
                d0 = _io.day(ev_.get("start"))
                if d0 is not None:
                    wants_x.setdefault(d0.toordinal(), set()).update(
                        str(p) for m in byev.get(eid_, []) for p in (m.get("p1"), m.get("p2")) if p)
        xsnap = SC.snapshots(sorted(matches, key=_io.match_key), elo_hist, wants_x)
    fit_keys = sorted(fits)
    loaded: list = [None, None]                    # the one fit in memory (fits are cache paths)
    acc = {"pre": {"title": [], "final": [], "sf": []}, "qf": {"title": [], "final": [], "sf": []}}
    champ_rank = []
    n_ev = 0
    t0 = time.time()
    evs = sorted([(eid, ev) for eid, ev in (events or {}).items()
                  if str(ev.get("level")) in ("slam", "m1000", "500", "250") and int(ev.get("year") or 0) in years],
                 key=lambda kv: str(kv[1].get("start")))
    for eid, ev in evs:
        if max_events is not None and n_ev >= max_events:
            break
        ms = [m for m in byev.get(eid, []) if m.get("round") in TS.KO_ROUNDS]
        draw = TS.bracket_from_results(ms)
        if not draw:
            continue
        final = [m for m in ms if m.get("round") == "F"]
        champ = str(final[0]["winner"])
        finalists = {str(final[0]["p1"]), str(final[0]["p2"])}
        semis = {str(p) for m in ms if m.get("round") == "SF" for p in (m.get("p1"), m.get("p2"))}
        start = _io.day(ev.get("start")) or min(_io.day(m["date"]) for m in ms if m.get("date"))
        fk = [k for k in fit_keys if k <= start.isoformat()]
        mdl = fits[fk[-1]] if fk else None
        if isinstance(mdl, (str, Path)):
            if loaded[0] != mdl:
                loaded[0], loaded[1] = mdl, _io.read_json(Path(mdl))
            mdl = loaded[1]
        # entrants' Elo at their first match here
        ratings: dict = {}
        gratings: dict = {}
        for m in sorted(ms, key=_io.match_key):
            for p in (m["p1"], m["p2"]):
                if p not in ratings and (m["id"], p) in pre_r:
                    a, s_, surf = pre_r[(m["id"], p)]
                    ratings[p] = {"all": a, surf: s_}
                if p not in gratings and (m["id"], str(p)) in gpre_r:
                    gratings[p] = gpre_r[(m["id"], str(p))]
        surface = _io.fold_surface(ev.get("surface"))
        bo = 5 if int(ev.get("best_of") or 3) == 5 else 3
        rule = PR.default_final_rule(ev.get("level"), bo, int(ev.get("year") or start.year), ev.get("tid"))
        d0 = _io.day(ev.get("start"))
        ctx = PR.Context(t, start, elo_ratings=ratings, elo_params=params, elo_mod=E, sr_model=mdl, sr_mod=S if mdl else None,
                         blend={"w_elo": w[0], "w_sr": w[1], "w_gelo": (w[2] if len(w) > 2 else 0.0),
                                "w_mr": (w[3] if len(w) > 3 else 0.0), "w_x": (w[4] if len(w) > 4 else {})} if w else None,
                         gelo_ratings=gratings if gparams else None, gelo_params=gparams,
                         mr_states=(msnap.get(d0.toordinal()) or {}) if (mparams and d0) else None, mr_params=mparams,
                         sched=(xsnap.get(d0.toordinal()) or {}) if (xsnap and d0) else None, assumed=True)

        memo: dict = {}

        def prob(pids, ctx=ctx, surface=surface, bo=bo, rule=rule, lvl=ev.get("level"), memo=memo):
            key = tuple(pids)
            if key not in memo:
                memo[key] = PR.prob_matrix(ctx, pids, surface, bo, lvl, rule)
            return memo[key]
        for cp in ("pre", "qf"):
            fixed = [] if cp == "pre" else [m for m in ms if TS.KO_ROUNDS.index(m["round"]) < TS.KO_ROUNDS.index("QF")]
            evx = {"id": eid, "draw": draw, "level": ev.get("level"), "best_of": bo, "surface": surface, "year": ev.get("year")}
            res = TS.simulate(evx, n=n, matches=fixed, tour=t, prob=prob, seed=seed, conditional=False)
            if not res.get("ok"):
                continue
            pl = res["players"]
            for p, v in pl.items():
                if str(p).startswith("tbd:"):
                    continue
                acc[cp]["title"].append((v["p_title"], int(p == champ)))
                acc[cp]["final"].append((v["p_final"], int(p in finalists)))
                acc[cp]["sf"].append((v["p_sf"], int(p in semis)))
            if cp == "pre":
                order = sorted(pl, key=lambda p: -pl[p]["p_title"])
                champ_rank.append(order.index(champ) + 1 if champ in order else None)
        n_ev += 1
        if log and n_ev % 50 == 0:
            log(f"{t} tournaments {n_ev} {time.time() - t0:.0f}s")
    cr = [x for x in champ_rank if x]
    return {"n_events": n_ev, "sims": n,
            "pre": {k: score(v) for k, v in acc["pre"].items()},
            "qf": {k: score(v) for k, v in acc["qf"].items()},
            "champion_model_rank": {"median": float(np.median(cr)) if cr else None,
                                    "share_favourite": round(float(np.mean([x == 1 for x in cr])), 4) if cr else None,
                                    "share_top3": round(float(np.mean([x <= 3 for x in cr])), 4) if cr else None}}


# ── WTA validation ───────────────────────────────────────────────────────────

def _real(st: dict) -> tuple | None:
    try:
        sv, sw = float(st["sv_pts"]), float(st["fs_won"]) + float(st.get("ss_won") or 0)
        gms = float(st["sv_gms"])
        if st.get("bp_faced") is not None and st.get("bp_saved") is not None:
            brk = float(st["bp_faced"]) - float(st["bp_saved"])
        else:
            brk = float(st["_breaks"])                         # synthetic rows carry the breaks directly
    except (TypeError, ValueError, KeyError):
        return None
    if sv <= 0 or gms <= 0:
        return None
    return sw, sv, gms - brk, gms


def validate_hold(tour: str = "wta", matches: list[dict] | None = None, through: Any = None, window_days: int = 730,
                  min_matches: int = 15, sr_mod=None) -> dict:
    """
    Inferred (score-only fit) v real hold % and serve-points-won %, per player over the window ending
    `through`: real = pooled from MATCH.stats; inferred = mean over the same matches of hold_prob(model, p,
    opponent, ...) and point_prob_from_hold of it. {"n_players","hold": {"pearson","spearman","rmse","bias"},
    "spw": {...},"players": [...]}.
    """
    S = sr_mod or PR._mod("serve_return")
    t = _io.tour_key(tour)
    ms = matches if matches is not None else _io.load_matches(t)
    # the window ends at the last completed match on or before today (scheduled matches never extend it)
    today = date.today()
    th = _io.day(through) or max((d for m in ms if m.get("status") in _io.RATED_STATUS and (d := _io.day(m.get("date")))
                                  and d <= today), default=today)
    lo = th - timedelta(days=window_days)
    win = [m for m in ms if _io.day(m.get("date")) and lo < _io.day(m["date"]) <= th]
    mdl = S.fit([m for m in ms if m.get("status") in _io.RATED_STATUS], through=th, stats=False,
                **({k: v for k, v in (S.constants(t) or {}).items() if k in ("half_life_days",)} if hasattr(S, "constants") else {}))
    agg: dict = {}
    for m in win:
        st = m.get("stats") or {}
        if not st or m.get("status") != "done":
            continue
        for side, opp, me in (("p1", m["p2"], m["p1"]), ("p2", m["p1"], m["p2"])):
            r = _real(st.get(side) or {})
            if not r:
                continue
            h = float(S.hold_prob(mdl, me, opp, m.get("surface"), m.get("level"), int(m.get("best_of") or 3), bool(m.get("indoor"))))
            a = agg.setdefault(me, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0])
            a[0] += r[0]; a[1] += r[1]; a[2] += r[2]; a[3] += r[3]
            a[4] += h
            a[5] += float(S.point_prob_from_hold(h))
            a[6] += 1
    players = []
    for p, a in agg.items():
        if a[6] < min_matches:
            continue
        players.append({"pid": p, "n": a[6], "real_hold": a[2] / a[3], "inf_hold": a[4] / a[6],
                        "real_spw": a[0] / a[1], "inf_spw": a[5] / a[6]})

    def stats(x, y):
        x, y = np.array(x), np.array(y)
        if len(x) < 3:
            return {"n": int(len(x))}
        rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
        return {"n": int(len(x)), "pearson": round(float(np.corrcoef(x, y)[0, 1]), 4),
                "spearman": round(float(np.corrcoef(rx, ry)[0, 1]), 4),
                "rmse": round(float(np.sqrt(np.mean((x - y) ** 2))), 4), "bias": round(float(np.mean(x - y)), 4)}
    return {"through": th.isoformat(), "window_days": window_days, "min_matches": min_matches, "n_players": len(players),
            "hold": stats([q["inf_hold"] for q in players], [q["real_hold"] for q in players]),
            "spw": stats([q["inf_spw"] for q in players], [q["real_spw"] for q in players]),
            "players": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in q.items()}
                        for q in sorted(players, key=lambda q: -q["n"])]}


# ── driver ───────────────────────────────────────────────────────────────────

def backtest(tour: str, years: Iterable[int] | None = None, matches: list[dict] | None = None, events: dict | None = None,
             refit_days: int = REFIT_DAYS, warmup_years: int = WARMUP_YEARS, tournament_sims: int = 3000,
             tournament_events: int | None = None, validate: bool = True, write: bool = True, use_cache: bool = True,
             sr_mod=None, elo_mod=None, export_blend: bool = True, log=None, seed: int = 0, sigma: Any = "fit") -> dict:
    """Full walk-forward backtest (module docstring). `matches`/`events` bypass the stores (tests)."""
    t0 = time.perf_counter()
    t = _io.tour_key(tour)
    if matches is None:
        matches = _io.load_matches(t, statuses=None)
    if events is None:
        events = {}
        for y in _io.years_on_disk(t):
            st = _io.load_store(t, y) or {}
            events.update(st.get("events") or {})
    yrs_avail = sorted({_io.day(m["date"]).year for m in matches if _io.day(m.get("date"))})
    years = sorted(set(int(y) for y in years)) if years is not None else [y for y in yrs_avail if y >= 2010]
    E = elo_mod or PR._mod("elo")
    hist = E.history(t, matches=[m for m in matches if m.get("status") in _io.RATED_STATUS]) if E is not None else {"rows": []}
    rows, fits = predictions(t, matches, years, refit_days, warmup_years, hist, sr_mod, elo_mod, use_cache, log)
    ev = evaluate(rows, years, seed, tour=t)
    scored = ev.pop("_scored")
    dist = distributions(scored, seed, sigma=sigma)
    last_w = ev["blend_by_year"].get(str(years[-1])) if years else None
    tourn = None
    if tournament_sims and events:
        try:
            tourn = tournaments(t, matches, events, years, fits, hist, tournament_sims, seed, sr_mod, elo_mod,
                                (last_w["w_elo"], last_w["w_sr"], last_w.get("w_gelo", 0.0), last_w.get("w_mr", 0.0),
                                 last_w.get("w_x") or {})
                                if last_w else None,
                                tournament_events, log)
        except Exception as exc:  # noqa: BLE001
            logger.exception("tournament calibration failed")
            tourn = {"error": str(exc)}
    val = None
    if validate and t == "wta":
        try:
            val = validate_hold(t, matches, sr_mod=sr_mod)
        except Exception as exc:  # noqa: BLE001
            val = {"error": str(exc)}
    # final blend on every scored year (the committed predict weights)
    blend_all = None
    both = [r for r in scored if r["elo"] is not None and r["sr"] is not None]
    if both:
        has_g = all("gelo" in r for r in both)
        has_m = has_g and all("mr" in r for r in both)
        has_x = has_m and all(r.get("x") is not None for r in both)
        blend_all = PR.fit_blend([_orient(r["elo"], r["flip"]) for r in both], [_orient(r["sr"], r["flip"]) for r in both],
                                 [0 if r["flip"] else 1 for r in both],
                                 gdiff=[_gorient(r) for r in both] if has_g else None,
                                 mdiff=[_morient(r) for r in both] if has_m else None,
                                 xmat=[_xorient(r) for r in both] if has_x else None)
        if blend_all.get("w_mr") is not None:
            # the fundamental blend (no market term) for the Value section's model rating (analytics/value.py)
            bf3 = PR.fit_blend([_orient(r["elo"], r["flip"]) for r in both], [_orient(r["sr"], r["flip"]) for r in both],
                               [0 if r["flip"] else 1 for r in both], gdiff=[_gorient(r) for r in both])
            blend_all["fundamental"] = {k: round(float(bf3[k]), 5) for k in ("w_elo", "w_sr", "w_gelo")
                                        if bf3.get(k) is not None}
    out = {"version": VERSION, "tour": t, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "years": years, "warmup_years": warmup_years, "refit_days": refit_days, "n_matches": len(scored),
           "n_with_pinnacle": sum(1 for r in scored if "pinnacle" in r["books"]),
           "n_with_avg": sum(1 for r in scored if "avg" in r["books"]),
           **ev, "distributions": dist, "tournaments": tourn, "validation": val, "blend_all_years": blend_all,
           "notes": ["Elo constants are builder B's frozen fit (tuned on 2005-2019 log-loss): ratings are walk-forward, "
                     "the constants are not.",
                     "Serve/return constants (half-life, ridges) are B's tuned values; the fits themselves are walk-forward.",
                     "Retirements, walkovers and defaults are excluded from scoring.",
                     "Bookmaker probabilities are closing prices de-vigged multiplicatively.",
                     "model = Elo + serve/return + game-share Elo + market rating (mrating.py: learnt from earlier "
                     "matches' closing prices and results, never the match's own); model_fund = the same blend "
                     "without the market rating."],
           "runtime_s": round(time.perf_counter() - t0, 1)}
    if write:
        _io.write_json(_io.cache_root() / f"backtest_{t}.json", out)
        _io.write_json(_io.data_root() / t / "calibration.json", page_copy(out))
        if export_blend and blend_all and blend_all.get("w_elo") is not None:
            _io.write_json(_io.FITTED / f"predict_{t}.json",
                           {"version": PR.VERSION, "w_elo": round(blend_all["w_elo"], 5), "w_sr": round(blend_all["w_sr"], 5),
                            **({"w_gelo": round(blend_all["w_gelo"], 5)} if blend_all.get("w_gelo") is not None else {}),
                            **({"w_mr": round(blend_all["w_mr"], 5)} if blend_all.get("w_mr") is not None else {}),
                            **({"w_x": {k: round(v, 5) for k, v in blend_all["w_x"].items()}} if blend_all.get("w_x") else {}),
                            **({"fundamental": blend_all["fundamental"]} if blend_all.get("fundamental") else {}),
                            "sigma": dist.get("sigma_all_years"),
                            "n": blend_all["n"], "logloss": blend_all.get("logloss"), "years": [years[0], years[-1]],
                            "fitted_at": out["generated_at"]}, indent=1)
    return out


def page_copy(bt: dict) -> dict:
    """The calibration page's subset (per-player validation rows trimmed to 300)."""
    keep = {k: v for k, v in bt.items() if k not in ("validation",)}
    if bt.get("validation"):
        v = dict(bt["validation"])
        v["players"] = (v.get("players") or [])[:300]
        keep["validation"] = v
    return keep


def summary_table(bt: dict) -> list[dict]:
    """Flat rows {scope, model, logloss, brier, n} for printing."""
    rows = []
    for scope in ("metrics", "vs_pinnacle", "vs_avg"):
        for m, v in (bt.get(scope) or {}).items():
            if v.get("n"):
                rows.append({"scope": scope, "model": m, "logloss": v.get("logloss"), "brier": v.get("brier"), "n": v["n"]})
    return rows
