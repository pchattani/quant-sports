"""
Draft-pick values for The Quant Hardwood (NBA and WNBA): the expected value of a draft slot, a traded pick's value
from the owning team's projected finish, protections, swaps and second-round picks, walk-forward validated on held-out
drafts (docs/research/pick_values.md; payloads picks.json and deals.json "pick_curve", PAYLOADS.md "Valuation, moves
and fantasy"). Used by analytics/moves.py (trade ratings) and the trade simulator (assets/js/trade.js).

Unit
----
The players' unit (valuation v2, analytics/valuation.py): wins above replacement (-2.0 HPM per 100) over a
four-season window, each later season floored at zero (a player below replacement stops being played) and discounted
0.9 a season. A pick's realised value is the same sum over the drafted player's first SEASONS (4) seasons, the length
of a first-round rookie-scale contract, from his first season (NBA: the season after the June draft; WNBA: the season
of the April draft); a pick who never played in our data counts zero. A future pick is discounted 0.9 a season from
the trade's season to its first season, as a player's later seasons are.

History (`history`)
-------------------
Slot -> player for every draft whose first SEASONS seasons are complete: the athlete records' draft field (ESPN core
API, scripts/bb_bio.py; the same ids as our value.json), then ESPN's draft lists (2003 on NBA, 2018 on WNBA; their
athlete ids often differ from the league ids, so a list entry is matched by id, else by normalised name, else by a
close spelling, among players with games in the pick's first seasons). NBA drafts 1996-2022 (1,601 picks), WNBA
2018-2023 (216). The earlier pick curve took the draft lists' ids at face value and found a player for 3 of 58 picks
in 2003 and none in 2010, so most picks counted zero (curve 3.9 WAR at No. 1; it is about 14 now).

Curve (`fit_curve`)
-------------------
Expected value by overall slot: a Gaussian kernel over the pick outcomes with a bandwidth widening down the draft
(BW0 + BW_SLOPE x slot: 1.6 picks at No. 1, 7.5 at No. 60), made non-increasing (pool-adjacent-violators). Chosen on
the development drafts (NBA 1996-2010) by leave-one-draft-out and walk-forward squared error: the kernel, the old
moving-average curve and a power law a (p + b)^-c were within noise of each other and well ahead of a round mean and
a flat mean; the kernel is the one with the fewest shape assumptions. The band is the 10th-90th percentile of the
curve over BOOT bootstrap resamples of whole drafts; q10 / q50 / q90 are kernel-weighted quantiles of single
outcomes (what one pick at that slot becomes).

Validation (`validate`)
----------------------
NBA: each draft 2011-2022 predicted from the drafts at least TRAIN_LAG (5) years older (all their seasons finished
before any trade of that draft's picks), against what the picks realised: squared and absolute error, rank
correlation, bias, the bucket means, and the paired bootstrap (by draft) of the squared-error difference against the
round mean. WNBA: six drafts only, leave-one-draft-out (no sealed test).

A traded pick (`PickModel`)
---------------------------
The owning team's slot distribution in that draft:
  * the season in progress: the season simulation (models/season_sim.py p_draft_pick, the lottery and the playoff
    teams in reverse order; p_record_rank for the second round and for the WNBA);
  * a finished season: its final standings (NBA: the lottery table over the 14 non-playoff teams until the draft);
  * later drafts: next-season win % = 0.5 + beta_k (win % now - 0.5) + e, e ~ N(0, sd_k^2), beta_k and sd_k fitted on
    every pair of seasons k apart in our standings (NBA beta 0.61, 0.36, 0.14, 0.04 for 1-4 years; 0 beyond), all
    teams drawn together N_FUTURE times and ranked (NBA: the 14 worst through the lottery table).
"At the time" uses only the standings of the last season completed before the trade (no hindsight); "now" uses
today's simulation. Value = sum over slots of P(slot) x curve(slot), x n, discounted.
  * top-N protected: the pick conveys when the slot is above N; otherwise it rolls to the next draft with the same
    protection, once, then conveys unprotected (ESPN's text rarely states the rollover terms: an assumption, shown);
    lottery-protected = top-14 (NBA) / top-4 (WNBA);
  * conditional with no terms stated: half its value (as on The Quant Gridiron);
  * a swap: the holder takes the better of the two picks: E[max(v_own, v_other)] - E[v_own], slots independent;
  * year not stated: the draft UNKNOWN_AHEAD years after the trade's season;
  * once the draft has been held, the pick is the player it became (analytics/moves.py), blended with the slot prior
    until he has ROOKIE_INFO_MIN minutes.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import math
from typing import Any, Iterable

import numpy as np

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import bio as BIO

logger = logging.getLogger(__name__)

VERSION = 1
SEASONS = 4
DISCOUNT = 0.9
BW0, BW_SLOPE = 1.5, 0.10
BOOT = 200
TRAIN_LAG = {"nba": 5, "wnba": 4}
DEV_LAST = {"nba": 2010}
YEARS_AHEAD = 7                     # NBA teams may trade picks seven drafts out
N_FUTURE = 4000
UNKNOWN_AHEAD = 2
CONDITIONAL = 0.5
ROOKIE_INFO_MIN = 1500.0
MAX_K = 7
LOTTERY_PROTECT = {"nba": 14, "wnba": 4}
PROTECT_PRESETS = {"nba": (4, 10, 14), "wnba": (2, 4)}
BUCKETS = {"nba": ((1, 3), (4, 10), (11, 20), (21, 30), (31, 45), (46, 60)),
           "wnba": ((1, 3), (4, 8), (9, 12), (13, 24), (25, 36))}


def _lg(league: str) -> str:
    return "wnba" if str(league).lower() == "wnba" else "nba"


def first_season(league: str, year: int) -> int:
    """The season a draft's picks first play (NBA June draft: the season ending the next year; WNBA April draft: the
    same year)."""
    return int(year) if _lg(league) == "wnba" else int(year) + 1


def record_season(league: str, year: int) -> int:
    """The season whose standings set a draft's order."""
    return int(year) - 1 if _lg(league) == "wnba" else int(year)


def draft_of_record(league: str, season: int) -> int:
    return int(season) + 1 if _lg(league) == "wnba" else int(season)


def ordinal(n: int) -> str:
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ---------------------------------------------------------------------------------------------- history

def _norm(name: str) -> str:
    from oddsmarkets.basketball.analytics import moves as MV
    return MV.norm(name)


def history(league: str, war_by: dict[int, dict[str, float]], rows_by: dict[int, dict[str, dict]]) -> dict[int, dict]:
    """{year: {"n": picks, "round_of": {overall: round}, "slots": {overall: pid}, "team": {overall: team id},
    "traded": {overall: bool}, "listed": bool}} for every draft we can reconstruct (see the module docstring)."""
    lg = _lg(league)
    bp = BIO.players(lg)
    dr = BIO.drafts(lg)
    names: dict[str, set[str]] = {}
    for s, rr in rows_by.items():
        for pid, x in rr.items():
            names.setdefault(_norm(x.get("name") or ""), set()).add(str(pid))
    keys = list(names)
    by_year: dict[int, dict[int, str]] = {}
    for pid, p in bp.items():
        d = p.get("draft")
        if d and d[0] and d[2]:
            by_year.setdefault(int(d[0]), {})[int(d[2])] = str(pid)
    seasons = sorted(war_by)
    first = (seasons[0] - 1) if lg == "nba" else 2018
    out: dict[int, dict] = {}
    years = sorted(set(by_year) | set(dr))
    for y in years:
        if y < first:
            continue
        lst = dr.get(y) or []
        if lg == "wnba" and not lst:
            continue                                  # WNBA athlete records carry no draft: only the listed drafts
        slots = dict(by_year.get(y) or {}) if lg == "nba" else {}
        team: dict[int, str] = {}
        traded: dict[int, bool] = {}
        round_of: dict[int, int] = {}
        fs = first_season(lg, y)
        seas = [fs + j for j in range(SEASONS)]
        for ov, rd, _pk, t, aid, nm, tr in lst:
            if not ov:
                continue
            ov = int(ov)
            team[ov] = str(t) if t else None
            traded[ov] = bool(tr)
            if rd:
                round_of[ov] = int(rd)
            if ov in slots:
                continue
            if aid and any(str(aid) in (war_by.get(s) or {}) for s in seas):
                slots[ov] = str(aid)
                continue
            k = _norm(nm or "")
            cands = set(names.get(k) or [])
            if not cands and k:
                close = difflib.get_close_matches(k, keys, n=2, cutoff=0.85)
                cands = set(names.get(close[0]) or []) if close else set()
            cands = [c for c in cands if any(c in (war_by.get(s) or {}) for s in seas)]
            if len(cands) == 1:
                slots[ov] = cands[0]
        if lst:
            n = len(lst)
        elif lg == "nba":
            n = 58 if y < 2004 else 59 if y == 2004 else 60
        else:
            continue
        per = max(1, int(round(n / max(1, max(round_of.values() or [2])))))
        for ov in range(1, n + 1):
            round_of.setdefault(ov, min(3, (ov - 1) // per + 1))
        out[y] = {"n": n, "round_of": round_of, "slots": slots, "team": team, "traded": traded, "listed": bool(lst)}
    return out


def outcome(league: str, year: int, pid: str | None, war_by: dict[int, dict[str, float]]) -> float:
    if not pid:
        return 0.0
    fs = first_season(league, year)
    return float(sum(DISCOUNT ** j * max(0.0, (war_by.get(fs + j) or {}).get(str(pid)) or 0.0) for j in range(SEASONS)))


def outcomes(league: str, hist: dict[int, dict], war_by: dict[int, dict[str, float]], last_complete: int) -> list[tuple[int, int, int, float]]:
    """[(draft year, overall, round, realised value)] for drafts whose first SEASONS seasons are complete."""
    out = []
    for y, h in sorted(hist.items()):
        if first_season(league, y) + SEASONS - 1 > last_complete:
            continue
        if any(not war_by.get(first_season(league, y) + j) for j in range(SEASONS)):
            continue
        for ov in range(1, h["n"] + 1):
            out.append((int(y), ov, int(h["round_of"].get(ov) or 1), outcome(league, y, h["slots"].get(ov), war_by)))
    return out


# ---------------------------------------------------------------------------------------------- curves

def _pava(y: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
    w = np.ones(len(y)) if w is None else w
    vals, wts, cnt = [], [], []
    for yi, wi in zip(y.tolist(), w.tolist()):
        vals.append(yi)
        wts.append(wi)
        cnt.append(1)
        while len(vals) > 1 and vals[-2] < vals[-1]:
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / max(wts[-2] + wts[-1], 1e-12)
            vals[-2:], wts[-2:], cnt[-2:] = [v], [wts[-2] + wts[-1]], [cnt[-2] + cnt[-1]]
    out = []
    for v, c in zip(vals, cnt):
        out += [v] * c
    return np.asarray(out, float)


def kernel_curve(P: np.ndarray, max_ov: int, bw0: float = BW0, slope: float = BW_SLOPE) -> np.ndarray:
    """Expected value at slots 1..max_ov from outcome rows P [[year, overall, value]]."""
    xs = np.arange(1, max_ov + 1, dtype=float)
    bw = bw0 + slope * xs
    W = np.exp(-0.5 * ((P[None, :, 1] - xs[:, None]) / bw[:, None]) ** 2)
    m = (W * P[None, :, 2]).sum(1) / np.maximum(W.sum(1), 1e-12)
    return _pava(m)


def _wquant(v: np.ndarray, w: np.ndarray, qs: Iterable[float]) -> list[float]:
    o = np.argsort(v)
    v, w = v[o], w[o]
    c = np.cumsum(w) / max(w.sum(), 1e-12)
    return [float(v[min(len(v) - 1, int(np.searchsorted(c, q)))]) for q in qs]


def _means(P: np.ndarray, max_ov: int) -> tuple[np.ndarray, np.ndarray]:
    m = np.full(max_ov, np.nan)
    n = np.zeros(max_ov)
    for i in range(max_ov):
        k = P[:, 1] == i + 1
        if k.any():
            m[i] = float(P[k, 2].mean())
            n[i] = float(k.sum())
    return m, n


def fit_old(P: np.ndarray, max_ov: int) -> np.ndarray:
    """The previous curve's method (mean by slot, non-increasing, five-pick moving average)."""
    m, n = _means(P, max_ov)
    k = n > 0
    mono = _pava(m[k], n[k])
    w = n[k]
    sm = np.array([np.average(mono[max(0, i - 2): i + 3], weights=w[max(0, i - 2): i + 3]) for i in range(len(mono))])
    sm = _pava(sm, w)
    return np.interp(np.arange(1, max_ov + 1), np.arange(1, max_ov + 1)[k], sm)


def fit_power(P: np.ndarray, max_ov: int) -> np.ndarray:
    from scipy.optimize import curve_fit
    m, n = _means(P, max_ov)
    k = n > 0
    xs = np.arange(1, max_ov + 1, dtype=float)

    def f(x, a, b, c):
        return a * np.power(x + b, -c)
    try:
        p, _ = curve_fit(f, xs[k], m[k], p0=(20.0, 1.0, 0.7), sigma=1.0 / np.sqrt(n[k]), bounds=([0, 0, 0.05], [1e4, 60, 5]), maxfev=20000)
    except Exception:                                            # noqa: BLE001
        return fit_old(P, max_ov)
    return f(xs, *p)


def fit_round(P: np.ndarray, max_ov: int, rounds: dict[int, int] | None = None, per: int = 30) -> np.ndarray:
    rd = np.array([min(3, (int(o) - 1) // per + 1) for o in P[:, 1]])
    xs = np.arange(1, max_ov + 1)
    rx = np.array([min(3, (int(o) - 1) // per + 1) for o in xs])
    means = {r: float(P[rd == r, 2].mean()) if (rd == r).any() else 0.0 for r in set(rx.tolist())}
    return np.array([means[r] for r in rx])


def fit_flat(P: np.ndarray, max_ov: int) -> np.ndarray:
    return np.full(max_ov, float(P[:, 2].mean()))


def fit_curve(pts: list[tuple[int, int, int, float]], league: str, boot: int = BOOT, seed: int = 0) -> dict:
    """The production curve over every complete draft (module docstring)."""
    if len(pts) < 60:
        return {"ok": False, "reason": f"only {len(pts)} picks with {SEASONS} complete seasons"}
    P = np.array([(y, o, v) for y, o, _r, v in pts], float)
    max_ov = int(P[:, 1].max())
    v = kernel_curve(P, max_ov)
    years = sorted({int(y) for y in P[:, 0]})
    rng = np.random.default_rng(seed)
    by = {y: P[P[:, 0] == y] for y in years}
    B = []
    for _ in range(int(boot)):
        s = rng.choice(years, len(years))
        B.append(kernel_curve(np.concatenate([by[y] for y in s]), max_ov))
    B = np.array(B)
    lo, hi = np.quantile(B, 0.1, axis=0), np.quantile(B, 0.9, axis=0)
    q = []
    zero = []
    xs = np.arange(1, max_ov + 1, dtype=float)
    for x in xs:
        w = np.exp(-0.5 * ((P[:, 1] - x) / (BW0 + BW_SLOPE * x)) ** 2)
        q.append(_wquant(P[:, 2], w, (0.1, 0.5, 0.9)))
        zero.append(float(np.sum(w * (P[:, 2] <= 0.05)) / max(w.sum(), 1e-12)))
    m, n = _means(P, max_ov)
    rounds: dict[str, list[float]] = {}
    for y, o, r, val in pts:
        rounds.setdefault(str(r), []).append(val)
    per = _per_round(league, pts)
    return {"ok": True, "league": _lg(league), "v": [round(float(x), 3) for x in v], "lo": [round(float(x), 3) for x in lo],
            "hi": [round(float(x), 3) for x in hi], "q10": [round(a, 2) for a, _b, _c in q], "q50": [round(b, 2) for _a, b, _c in q],
            "q90": [round(c, 2) for _a, _b, c in q], "p_zero": [round(z, 3) for z in zero],
            "raw": [[i + 1, round(float(m[i]), 3), int(n[i])] for i in range(max_ov) if n[i] > 0],
            "rounds": {k: round(float(np.mean(x)), 3) for k, x in sorted(rounds.items())}, "per_round": per,
            "n_drafts": len(years), "n_picks": len(pts), "years": [years[0], years[-1]], "seasons": SEASONS, "discount": DISCOUNT,
            "bandwidth": [BW0, BW_SLOPE], "boot": int(boot), "max_overall": max_ov}


def _per_round(league: str, pts) -> int:
    if _lg(league) == "nba":
        return 30
    c: dict[int, int] = {}
    for y, o, r, _v in pts:
        if r == 1:
            c[y] = max(c.get(y, 0), o)
    return int(np.median(list(c.values()))) if c else 12


def curve_at(curve: dict | None, overall: int) -> float:
    v = (curve or {}).get("v") or []
    if not v:
        return 0.0
    return float(v[max(0, min(len(v), int(overall)) - 1)])


# ---------------------------------------------------------------------------------------------- validation

def validate(pts: list[tuple[int, int, int, float]], league: str, boot: int = 2000, seed: int = 1) -> dict:
    lg = _lg(league)
    if len(pts) < 60:
        return {"ok": False}
    P = np.array([(y, o, v) for y, o, _r, v in pts], float)
    max_ov = int(P[:, 1].max())
    per = _per_round(lg, pts)
    fams = {"kernel": lambda T: kernel_curve(T, max_ov), "old": lambda T: fit_old(T, max_ov), "power": lambda T: fit_power(T, max_ov),
            "round": lambda T: fit_round(T, max_ov, per=per), "flat": lambda T: fit_flat(T, max_ov)}
    years = sorted({int(y) for y in P[:, 0]})
    out: dict[str, Any] = {"ok": True, "families": list(fams)}
    dev = [y for y in years if y <= DEV_LAST.get(lg, 9999)]
    lodo = {}
    for nm, f in fams.items():
        se = []
        for y in dev:
            T = P[np.isin(P[:, 0], dev) & (P[:, 0] != y)]
            H = P[P[:, 0] == y]
            c = f(T)
            se += list((H[:, 2] - c[H[:, 1].astype(int) - 1]) ** 2)
        lodo[nm] = round(float(np.mean(se)), 3)
    out["dev_lodo"] = {"drafts": [dev[0], dev[-1]], "mse": lodo}
    lag = TRAIN_LAG[lg]
    test = [y for y in years if y > DEV_LAST.get(lg, -1)] if lg in DEV_LAST else []
    if lg in DEV_LAST:
        wf_dev = [y for y in dev if len([z for z in years if z <= y - lag]) >= 5]
        dv = {}
        for nm, f in fams.items():
            se = []
            for y in wf_dev:
                T = P[P[:, 0] <= y - lag]
                H = P[P[:, 0] == y]
                c = f(T)
                se += list((H[:, 2] - c[H[:, 1].astype(int) - 1]) ** 2)
            dv[nm] = round(float(np.mean(se)), 3)
        out["dev_walk_forward"] = {"drafts": [wf_dev[0], wf_dev[-1]] if wf_dev else None, "mse": dv}
    else:
        # WNBA: too few drafts for a sealed test; leave-one-draft-out over all of them is the only check
        test = []
    if test:
        rows = []
        for y in test:
            T = P[P[:, 0] <= y - lag]
            H = P[P[:, 0] == y]
            cs = {nm: f(T) for nm, f in fams.items()}
            for o, v in zip(H[:, 1].astype(int), H[:, 2]):
                rows.append([y, o, v] + [cs[nm][o - 1] for nm in fams])
        R = np.array(rows)
        from scipy.stats import spearmanr
        met = {}
        for i, nm in enumerate(fams):
            pr, ob = R[:, 3 + i], R[:, 2]
            met[nm] = {"mse": round(float(np.mean((pr - ob) ** 2)), 3), "mae": round(float(np.mean(np.abs(pr - ob))), 3),
                       "spearman": round(float(spearmanr(pr, ob)[0]), 3) if np.std(pr) > 0 else None,
                       "bias": round(float(np.mean(pr - ob)), 3)}
        flat = met["flat"]["mse"]
        for nm in met:
            met[nm]["skill_v_flat"] = round(1.0 - met[nm]["mse"] / flat, 3) if flat else None
        rng = np.random.default_rng(seed)
        ty = np.array(test)
        idx_by = {y: np.where(R[:, 0] == y)[0] for y in test}
        ik, ir, iold = 3 + list(fams).index("kernel"), 3 + list(fams).index("round"), 3 + list(fams).index("old")
        d_round, d_old = [], []
        for _ in range(int(boot)):
            s = rng.choice(ty, len(ty))
            idx = np.concatenate([idx_by[y] for y in s])
            e_k = np.mean((R[idx, ik] - R[idx, 2]) ** 2)
            d_round.append(e_k - np.mean((R[idx, ir] - R[idx, 2]) ** 2))
            d_old.append(e_k - np.mean((R[idx, iold] - R[idx, 2]) ** 2))
        buckets = []
        for lo, hi in BUCKETS[lg]:
            m = (R[:, 1] >= lo) & (R[:, 1] <= hi)
            if m.any():
                buckets.append({"slots": [lo, hi], "n": int(m.sum()), "realised": round(float(R[m, 2].mean()), 2),
                                "kernel": round(float(R[m, ik].mean()), 2), "round": round(float(R[m, ir].mean()), 2)})
        out["test"] = {"drafts": [test[0], test[-1]], "train_lag": lag, "n": int(len(R)), "metrics": met, "buckets": buckets,
                       "mse_kernel_minus_round": {"diff": round(met["kernel"]["mse"] - met["round"]["mse"], 3),
                        "ci95": [round(float(np.quantile(d_round, 0.025)), 3), round(float(np.quantile(d_round, 0.975)), 3)]},
                       "mse_kernel_minus_old": {"diff": round(met["kernel"]["mse"] - met["old"]["mse"], 3),
                                                "ci95": [round(float(np.quantile(d_old, 0.025)), 3), round(float(np.quantile(d_old, 0.975)), 3)]}}
    return out


# ---------------------------------------------------------------------------------------------- standings persistence

def standings_pct(league: str, seasons: Iterable[int] | None = None) -> dict[int, dict[str, float]]:
    """{season: {team: win %}} from each season's season.json standings."""
    out: dict[int, dict[str, float]] = {}
    for s in (seasons if seasons is not None else an.seasons_on_disk(league)):
        sj = an.read_json(an.data_root() / _lg(league) / str(s) / "season.json") or {}
        rows = {}
        for _g, lst in ((sj.get("standings") or {}).items() if isinstance(sj.get("standings"), dict) else []):
            for r in lst or []:
                w, l = int(r.get("w") or 0), int(r.get("l") or 0)
                if w + l:
                    rows[str(r.get("team"))] = w / (w + l)
        if rows:
            out[int(s)] = rows
    return out


def persistence(wp: dict[int, dict[str, float]], complete: Iterable[int]) -> dict:
    """{"beta": [k=1..MAX_K], "sd": [...], "n": [...]}: win % k seasons on regressed on win % now (centred on 0.5)."""
    comp = sorted(set(int(s) for s in complete) & set(wp))
    beta, sd, nn = [], [], []
    for k in range(1, MAX_K + 1):
        x, y = [], []
        for s in comp:
            if s + k not in comp:
                continue
            for t, v in wp[s].items():
                if t in wp[s + k]:
                    x.append(v - 0.5)
                    y.append(wp[s + k][t] - 0.5)
        if len(x) < 30:
            beta.append(0.0)
            sd.append(float(np.std(y)) if y else 0.15)
            nn.append(len(x))
            continue
        x, y = np.array(x), np.array(y)
        b = float(np.sum(x * y) / max(np.sum(x * x), 1e-12))
        b = max(0.0, min(1.0, b))
        sd.append(float(np.std(y - b * x)))
        beta.append(b)
        nn.append(int(len(x)))
    # beyond the years where the fit finds persistence it is noise: zero
    for k in range(len(beta)):
        if k >= 3 and beta[k] < 0.06:
            beta[k:] = [0.0] * (len(beta) - k)
            break
    return {"beta": [round(b, 3) for b in beta], "sd": [round(s, 3) for s in sd], "n": nn}


# ---------------------------------------------------------------------------------------------- slot distributions

def _lottery(league: str):
    if _lg(league) != "nba":
        return None
    from oddsmarkets.basketball.models.config import LOTTERY_2019
    from oddsmarkets.basketball.models.season_sim import lottery_matrix
    return lottery_matrix(tuple(LOTTERY_2019), 4)


def order_dists(league: str, ranks: np.ndarray, teams: list[str], rounds: int) -> dict[str, dict[int, np.ndarray]]:
    """Slot distributions from rank draws (sims x teams, 0 = worst record): {team: {round: P over that round's slots}}.
    NBA first round: the 14 worst through the lottery table."""
    S, T = ranks.shape
    LM = _lottery(league)
    out = {}
    for j, t in enumerate(teams):
        rc = np.bincount(ranks[:, j], minlength=T).astype(float) / S
        d = {}
        if LM is not None:
            nl = LM.shape[0]
            r1 = np.zeros(T)
            r1[:nl] = rc[:nl] @ LM
            r1[nl:] = rc[nl:]
            d[1] = r1
        else:
            d[1] = rc.copy()
        for r in range(2, rounds + 1):
            d[r] = rc.copy()
        out[t] = d
    return out


def future_ranks(x: dict[str, float], beta: float, sd: float, n: int = N_FUTURE, seed: int = 0) -> tuple[list[str], np.ndarray]:
    teams = sorted(x)
    rng = np.random.default_rng(seed)
    base = np.array([0.5 + beta * (x[t] - 0.5) for t in teams])
    draws = base[None, :] + sd * rng.standard_normal((n, len(teams)))
    ranks = np.argsort(np.argsort(draws, axis=1), axis=1)
    return teams, ranks


class PickModel:
    """Slot distributions and values for one league as of today (`now`) and as of earlier trade dates (`time`)."""

    def __init__(self, league: str, season: int, curve: dict, pers: dict, wp: dict[int, dict[str, float]], complete: set[int],
                 sim: dict | None = None, members: Iterable[str] | None = None, seed: int = 0):
        self.league = _lg(league)
        self.season = int(season)
        self.curve = curve or {}
        self.pers = pers or {"beta": [], "sd": []}
        self.wp = wp
        self.complete = set(int(s) for s in complete)
        self.sim_teams = ((sim or {}).get("teams") or {}) if sim else {}
        self.sim_done = bool(sim) and int((sim or {}).get("remaining_games") or 0) == 0
        self.members = [str(t) for t in (members or [])] or sorted(self.sim_teams) or sorted((wp.get(max(wp)) if wp else {}) or {})
        self.seed = seed
        self.rounds = 3 if self.league == "wnba" else 2
        self._cache: dict[tuple, dict] = {}

    # the teams' latest information
    def _info(self, basis: str, info_season: int | None) -> tuple[int, dict[str, float], bool]:
        """(season the information is from, {team: projected final win %}, from a live simulation)."""
        if basis == "now" and self.sim_teams and not self.sim_done:
            x = {}
            for t, s in self.sim_teams.items():
                cur = s.get("current") or {}
                g = (cur.get("w") or 0) + (cur.get("l") or 0) + (cur.get("remaining") or 0)
                ew = an.fnum(s.get("exp_w"))
                if g and ew is not None:
                    x[str(t)] = ew / g
            return self.season, x, True
        if basis == "now":
            s0 = max([s for s in self.complete if s <= self.season] or [self.season - 1])
        else:
            s0 = int(info_season)
            while s0 not in self.wp and s0 > min(self.wp or {s0: 0}):
                s0 -= 1
        return s0, dict(self.wp.get(s0) or {}), False

    def dists(self, year: int, basis: str = "now", info_season: int | None = None) -> dict[str, dict[int, np.ndarray]]:
        """{team: {round: P over slots}} for a draft."""
        key = (int(year), basis, info_season)
        if key in self._cache:
            return self._cache[key]
        rs = record_season(self.league, year)
        s0, x, live = self._info(basis, info_season)
        teams = sorted(set(self.members) | set(x)) if basis == "now" else sorted(x)
        teams = [t for t in teams if t in x] or teams
        T = len(teams)
        out: dict[str, dict[int, np.ndarray]] = {}
        if live and rs == s0 and self.sim_teams:
            for t in teams:
                s = self.sim_teams.get(t) or {}
                rr = np.array(s.get("p_record_rank") or [1.0 / T] * T, float)
                r1 = np.array(s.get("p_draft_pick") or rr, float) if self.league == "nba" else rr
                out[t] = {1: r1, **{r: rr for r in range(2, self.rounds + 1)}}
        elif rs <= s0 and rs in self.wp:
            final = self.wp[rs]
            tt = sorted(final, key=lambda t: (final[t], t))
            ranks = np.array([[tt.index(t) for t in sorted(final)]])
            out = order_dists(self.league, ranks, sorted(final), self.rounds)
        else:
            k = max(1, rs - s0)
            b = self.pers["beta"][k - 1] if k - 1 < len(self.pers["beta"]) else 0.0
            sd = self.pers["sd"][k - 1] if k - 1 < len(self.pers["sd"]) else (self.pers["sd"][-1] if self.pers["sd"] else 0.15)
            seed = int(hashlib.sha1(f"{self.league}{year}{basis}{info_season}{self.seed}".encode()).hexdigest()[:8], 16)
            tl, ranks = future_ranks({t: x[t] for t in teams}, b, sd, seed=seed)
            out = order_dists(self.league, ranks, tl, self.rounds)
        self._cache[key] = out
        return out

    def slot_probs(self, team: str | None, year: int, rnd: int, basis: str = "now", info_season: int | None = None) -> tuple[np.ndarray, int]:
        """(P over the round's slots, the overall number of the round's first slot - 1)."""
        d = self.dists(year, basis, info_season)
        if team is not None and str(team) in d:
            p = d[str(team)][int(rnd)]
        else:                                           # unknown owner: the league's average pick of that round
            T = len(next(iter(d.values()))[1]) if d else 30
            p = np.full(T, 1.0 / T)
        T = len(p)
        return p, T * (int(rnd) - 1)

    def ev(self, p: np.ndarray, offset: int, protect: int | None = None) -> tuple[float, float]:
        """(expected curve value, P(conveys)) over slots, with top-`protect` slots not conveying."""
        v = np.array([curve_at(self.curve, offset + i + 1) for i in range(len(p))])
        if protect:
            mask = np.arange(1, len(p) + 1) > int(protect)
            return float(np.sum(p * v * mask)), float(np.sum(p * mask))
        return float(np.sum(p * v)), 1.0

    def value(self, origin: str | None, year: int | None, rnd: int | None, trade_season: int, basis: str = "now",
              protect: int | None = None, conditional: bool = False, swap_with: str | None = None, n: int = 1) -> dict:
        """{"v", "v_undiscounted", "slot": [p25, p75], "med", "p_convey", "first", "year", "note"} for a traded pick."""
        rnd = int(rnd or 1)
        note = []
        if year is None:
            year = draft_of_record(self.league, trade_season) + UNKNOWN_AHEAD
            note.append("year not stated: valued as the draft two years on")
        info = trade_season - 1 if basis == "time" else None
        p, off = self.slot_probs(origin, year, rnd, basis, info)
        fs = first_season(self.league, year)
        disc = DISCOUNT ** max(0, fs - int(trade_season))
        if swap_with is not None:
            q, _ = self.slot_probs(swap_with, year, rnd, basis, info)
            vv = np.array([curve_at(self.curve, off + i + 1) for i in range(len(p))])
            e_max = float(np.sum(np.outer(q, p) * np.maximum(vv[:, None], vv[None, :])))
            e_own = float(np.sum(q * vv))
            raw = max(0.0, e_max - e_own)
            note.append("swap: the better of the two picks")
            return {"v": raw * disc * n, "v_undiscounted": raw, "slot": _slot_range(p, off), "med": _slot_med(p, off), "p_convey": None,
                    "first": fs, "year": int(year), "note": "; ".join(note)}
        raw, conv = self.ev(p, off, protect)
        if protect:
            # rolls once with the same protection, then conveys unprotected
            p2, off2 = self.slot_probs(origin, year + 1, rnd, basis, info)
            r2, c2 = self.ev(p2, off2, protect)
            p3, off3 = self.slot_probs(origin, year + 2, rnd, basis, info)
            r3, _ = self.ev(p3, off3, None)
            raw = raw + (1 - conv) * DISCOUNT * (r2 + (1 - c2) * DISCOUNT * r3)
            note.append(f"top-{protect} protected: conveys {conv:.0%} of the time, else rolls a year (then unprotected)")
        if conditional:
            raw *= CONDITIONAL
            note.append("conditional, terms not stated: half value")
        return {"v": raw * disc * n, "v_undiscounted": raw, "slot": _slot_range(p, off), "med": _slot_med(p, off), "p_convey": conv if protect else None,
                "first": fs, "year": int(year), "note": "; ".join(note)}


def _slot_range(p: np.ndarray, off: int) -> list[int]:
    c = np.cumsum(p) / max(float(np.sum(p)), 1e-12)
    return [int(off + np.searchsorted(c, 0.25) + 1), int(off + np.searchsorted(c, 0.75) + 1)]


def _slot_med(p: np.ndarray, off: int) -> int:
    c = np.cumsum(p) / max(float(np.sum(p)), 1e-12)
    return int(off + np.searchsorted(c, 0.5) + 1)


# ---------------------------------------------------------------------------------------------- the model, cached

def _sig(league: str, seasons: list[int]) -> str:
    from oddsmarkets.basketball.analytics import valuation as VV
    h = hashlib.sha1(VV._sig(league, seasons).encode())
    from oddsmarkets.basketball.models import _io as _bio
    for s in seasons:
        h.update(_bio.path_sig(an.data_root() / _lg(league) / str(s) / "season.json").encode())
    return h.hexdigest()


def fits(league: str, current: int, war_by: dict | None = None, rows_by: dict | None = None, use_cache: bool = True) -> dict:
    """{"curve", "validation", "persistence", "history_info"} from the completed seasons before `current` (cached on
    their value.json / season.json files and the bio file)."""
    lg = _lg(league)
    seasons = [s for s in an.seasons_on_disk(lg) if s < int(current)]
    key = [VERSION, _sig(lg, seasons)]
    path = an.cache_root() / "value" / f"pick_model_{lg}.json"
    if use_cache:
        c = an.read_json(path)
        if isinstance(c, dict) and c.get("key") == key and c.get("fits"):
            return c["fits"]
    if war_by is None or rows_by is None:
        from oddsmarkets.basketball.analytics import moves as MV
        war_by, rows_by = MV.season_war_rows(lg, an.seasons_on_disk(lg))
    last_complete = max([s for s in war_by if s < int(current)] or [int(current) - 1])
    hist = history(lg, {s: w for s, w in war_by.items() if s <= last_complete}, rows_by)
    pts = outcomes(lg, hist, war_by, last_complete)
    curve = fit_curve(pts, lg)
    val = validate(pts, lg) if curve.get("ok") else {"ok": False}
    wp = standings_pct(lg, seasons)
    pers = persistence(wp, [s for s in seasons if s <= last_complete])
    info = {"drafts": len({y for y, *_ in pts}), "picks": len(pts), "matched": sum(1 for y, o, _r, _v in pts if hist[y]["slots"].get(o)),
            "last_complete": last_complete}
    out = {"curve": curve, "validation": val, "persistence": pers, "history_info": info}
    try:
        an.write_json(path, {"key": key, "fits": out})
    except OSError:
        pass
    return out


def model(league: str, season: int, sim: dict | None, members: Iterable[str] | None, fit: dict | None = None,
          phase: str | None = None) -> PickModel:
    lg = _lg(league)
    fit = fit or fits(lg, season)
    seasons = [s for s in an.seasons_on_disk(lg) if s <= int(season)]
    wp = standings_pct(lg, seasons)
    complete = {s for s in wp if s < int(season)}
    if sim and int(sim.get("remaining_games") or 0) == 0 and sim.get("teams"):
        cur = {}
        for t, s in sim["teams"].items():
            c = s.get("current") or {}
            if (c.get("w") or 0) + (c.get("l") or 0):
                cur[str(t)] = c["w"] / (c["w"] + c["l"])
        if cur:
            wp[int(season)] = cur
            complete.add(int(season))
    elif not sim and phase == "offseason" and int(season) in wp:
        complete.add(int(season))                       # the season is over (WNBA autumn): its standings are final
    return PickModel(lg, season, fit.get("curve") or {}, fit.get("persistence") or {}, wp, complete, sim=sim, members=members)


# ---------------------------------------------------------------------------------------------- payload

def next_draft(pm: PickModel) -> int:
    """The next draft not yet held: the current season's draft (NBA) / the next spring's (WNBA), unless the bio file
    already lists it."""
    y = draft_of_record(pm.league, pm.season)
    while BIO.drafts(pm.league).get(y):
        y += 1
    return y


def team_table(pm: PickModel, teams: Iterable[str], trade_season: int) -> dict:
    """{tid: {"years": [...], "r<k>": [[v, slot p25, slot p75, median slot]], "prot": {N: [v...]}}} for every team's own
    picks from the next draft on (values as of today, discounted to the current season)."""
    y0 = next_draft(pm)
    years = list(range(y0, y0 + YEARS_AHEAD))
    out = {}
    for t in teams:
        rec: dict[str, Any] = {"years": years}
        for r in range(1, pm.rounds + 1):
            rows = []
            for y in years:
                x = pm.value(t, y, r, trade_season)
                rows.append([round(x["v"], 2), x["slot"][0], x["slot"][1], x["med"]])
            rec[f"r{r}"] = rows
        prot = {}
        for N in PROTECT_PRESETS[pm.league]:
            prot[str(N)] = [round(pm.value(t, y, 1, trade_season, protect=N)["v"], 2) for y in years]
        rec["prot"] = prot
        out[str(t)] = rec
    return out


def payload(league: str, season: int, pm: PickModel, fit: dict, teams: Iterable[str], updated_at: str | None = None) -> dict:
    c = fit.get("curve") or {}
    return {"ok": bool(c.get("ok")), "league": _lg(league), "season": int(season), "updated_at": updated_at or an.now(), "version": VERSION,
            "curve": c, "validation": fit.get("validation"), "persistence": fit.get("persistence"), "history": fit.get("history_info"),
            "teams": team_table(pm, teams, int(season)) if c.get("ok") else {},
            "constants": {"seasons": SEASONS, "discount": DISCOUNT, "conditional": CONDITIONAL, "unknown_ahead": UNKNOWN_AHEAD,
                          "lottery_protect": LOTTERY_PROTECT[_lg(league)], "presets": list(PROTECT_PRESETS[_lg(league)]),
                          "rookie_info_min": ROOKIE_INFO_MIN, "rounds": pm.rounds},
            "note": "Values in the players' unit: wins above replacement over a drafted player's first four seasons (each season "
                    "floored at zero, discounted 0.9 a season), from our own value for every pick of past drafts; a future pick "
                    "from the owning team's projected finish. On-field value only: no rookie-scale salaries."}
