"""
College hockey game model: team attack / defence ratings from a decayed, ridge-penalised Poisson regression on
regulation goals, a home-ice term, and an outcome layer for college hockey's overtime and ties.

Ratings (fitted on games before the game day, walk-forward)
    log E[goals_h] = mu + hfa * (1 - neutral) + att_h - def_a          (regulation goals, home side)
    log E[goals_a] = mu                       + att_a - def_h
    minimise  sum_i w_i * PoissonDeviance_i  +  lam * sum_t [(att_t - m_att_t)^2 + (def_t - m_def_t)^2]
    w_i = 0.5 ^ (age_days / half_life);   priors m = carry x last season's final rating (0 for a new team).
    Fitted by Newton (IRLS) steps on the joint parameter vector; teams outside Division I share one pooled
    "non-D-I" attack / defence pair.

Outcome (one game)
    regulation  goals ~ independent Poisson(lam_h), Poisson(lam_a), with a Dixon-Coles style tie inflation `rho`
                (P(tie) scaled by 1 + rho, the rest renormalised): hockey ends level more often than Poisson says;
    overtime    P(decided in OT | level) = q[era] (regular season: 5v5 five minutes before 2021-22, 3-on-3 five
                minutes since); postseason games always decided (sudden death); P(home wins | decided) =
                lam_h^k / (lam_h^k + lam_a^k);
    record      a shootout is a tie in the NCAA record (conference points aside), so P(W), P(T), P(L).

Everything is fitted on the dev seasons only (2006-2024); 2025 and 2026 (2024-25, 2025-26) are sealed test seasons.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import numpy as np

DEFAULTS = {
    "half_life": 75.0,        # days
    "lam": 18.0,              # ridge weight, in game-equivalents
    "carry": 0.55,            # last season's rating carried into the prior
    "rho": 0.12,              # tie inflation in regulation
    "q_pre": 0.36,            # P(decided in 5-min 5v5 OT | tied), before 2021-22
    "q_3v3": 0.62,            # P(decided in 5-min 3v3 OT | tied), 2021-22 on
    "k_ot": 1.0,
    "max_goals": 12,
}
SEALED = (2025, 2026)


@dataclass
class Fit:
    teams: list[str]
    att: np.ndarray
    dfn: np.ndarray
    mu: float
    hfa: float
    n: int = 0
    idx: dict = field(default_factory=dict)

    def rating(self, t: str) -> tuple[float, float]:
        i = self.idx.get(t)
        if i is None:
            i = self.idx.get("__nd1__")
        if i is None:
            return 0.0, 0.0
        return float(self.att[i]), float(self.dfn[i])

    def means(self, h: str, a: str, neutral: bool) -> tuple[float, float]:
        ah, dh = self.rating(h)
        aa, da = self.rating(a)
        lh = math.exp(self.mu + (0.0 if neutral else self.hfa) + ah - da)
        la = math.exp(self.mu + aa - dh)
        return lh, la

    def net(self, t: str) -> float:
        """Goals per game above an average Division I team against an average team, neutral ice."""
        a, d = self.rating(t)
        base = math.exp(self.mu)
        return base * (math.exp(a) - math.exp(-d))


def regulation_goals(g: dict) -> tuple[int | None, int | None]:
    hs, as_ = g.get("hs"), g.get("as")
    per = g.get("per") or ((g.get("chn") or {}).get("per"))
    if per and len(per) == 2 and all(isinstance(x, list) and len(x) >= 3 and all(v is not None for v in x[:3]) for x in per):
        return sum(per[0][:3]), sum(per[1][:3])
    if hs is None or as_ is None:
        return None, None
    if (g.get("ot") or 0) > 0 and not g.get("so") and hs != as_:
        return (hs - 1, as_) if hs > as_ else (hs, as_ - 1)
    if g.get("so") and hs != as_:
        m = min(hs, as_)
        return m, m
    return hs, as_


def fit(rows: list[tuple], ref_day: int, prior: dict[str, tuple[float, float]], p: dict, teams: Iterable[str],
        init: Fit | None = None, iters: int = 6) -> Fit:
    """rows: (day_ordinal, home, away, neutral, gh, ga) with gh/ga regulation goals; teams: the D-I ids (others pool
    as '__nd1__')."""
    tl = sorted(set(teams)) + ["__nd1__"]
    idx = {t: i for i, t in enumerate(tl)}
    T = len(tl)
    nd = idx["__nd1__"]
    H = np.array([idx.get(r[1], nd) for r in rows], dtype=int)
    A = np.array([idx.get(r[2], nd) for r in rows], dtype=int)
    neu = np.array([1.0 if r[3] else 0.0 for r in rows])
    gh = np.array([r[4] for r in rows], dtype=float)
    ga = np.array([r[5] for r in rows], dtype=float)
    age = ref_day - np.array([r[0] for r in rows], dtype=float)
    w = 0.5 ** (np.maximum(age, 0) / p["half_life"]) if len(rows) else np.zeros(0)
    m_att = np.zeros(T)
    m_def = np.zeros(T)
    for t, (a, d) in prior.items():
        if t in idx:
            m_att[idx[t]], m_def[idx[t]] = a, d
    lam = np.full(T, p["lam"])
    lam[nd] = p["lam"] * 0.25
    # parameter vector: [mu, hfa, att(T), def(T)]
    if init is not None and init.teams == tl:
        x = np.concatenate([[init.mu, init.hfa], init.att, init.dfn])
    else:
        x = np.concatenate([[math.log(2.9), 0.08], m_att, m_def])
    n = 2 + 2 * T
    for _ in range(iters):
        mu, hfa = x[0], x[1]
        att, dfn = x[2:2 + T], x[2 + T:]
        eh = mu + hfa * (1 - neu) + att[H] - dfn[A] if len(rows) else np.zeros(0)
        ea = mu + att[A] - dfn[H] if len(rows) else np.zeros(0)
        lh, la = np.exp(eh), np.exp(ea)
        g = np.zeros(n)
        Hs = np.zeros((n, n))
        # gradient of weighted Poisson log-lik: w (y - lam) d eta
        rh, ra = w * (gh - lh), w * (ga - la)
        wh, wa = w * lh, w * la
        # mu
        g[0] = rh.sum() + ra.sum()
        g[1] = (rh * (1 - neu)).sum()
        np.add.at(g, 2 + H, rh)
        np.add.at(g, 2 + A, ra)
        np.add.at(g, 2 + T + A, -rh)
        np.add.at(g, 2 + T + H, -ra)
        # Hessian (negative information), built by design vectors
        # rows of design for home eq: [1, 1-neu, e_H (att), -e_A (def)]; away eq: [1, 0, e_A, -e_H]
        def acc(wv, i_att, j_def, hf):
            Hs[0, 0] += wv.sum()
            Hs[0, 1] += (wv * hf).sum(); Hs[1, 0] = Hs[0, 1]
            Hs[1, 1] += (wv * hf * hf).sum()
            np.add.at(Hs[0], 2 + i_att, wv); np.add.at(Hs[0], 2 + T + j_def, -wv)
            np.add.at(Hs[1], 2 + i_att, wv * hf); np.add.at(Hs[1], 2 + T + j_def, -wv * hf)
            np.add.at(Hs, (2 + i_att, 2 + i_att), wv)
            np.add.at(Hs, (2 + T + j_def, 2 + T + j_def), wv)
            np.add.at(Hs, (2 + i_att, 2 + T + j_def), -wv)
            np.add.at(Hs, (2 + T + j_def, 2 + i_att), -wv)
        acc(wh, H, A, 1 - neu)
        acc(wa, A, H, np.zeros(len(rows)))
        Hs[2:, 0] = Hs[0, 2:]
        Hs[2:, 1] = Hs[1, 2:]
        # ridge
        g[2:2 + T] -= lam * (att - m_att)
        g[2 + T:] -= lam * (dfn - m_def)
        Hs[2:2 + T, 2:2 + T] += np.diag(lam)
        Hs[2 + T:, 2 + T:] += np.diag(lam)
        Hs[0, 0] += 1e-3
        Hs[1, 1] += 4.0                                  # weak prior on home ice around its start value
        g[1] -= 4.0 * (x[1] - 0.08)
        try:
            step = np.linalg.solve(Hs, g)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(Hs, g, rcond=None)[0]
        x = x + step
        if np.max(np.abs(step)) < 1e-6:
            break
    return Fit(teams=tl, att=x[2:2 + T].copy(), dfn=x[2 + T:].copy(), mu=float(x[0]), hfa=float(x[1]), n=len(rows),
               idx=idx)


# ── outcome ────────────────────────────────────────────────────────────────────────────────────────────────

def _pois(lam: float, n: int) -> np.ndarray:
    k = np.arange(n + 1)
    lg = np.array([math.lgamma(i + 1) for i in k])
    return np.exp(k * math.log(max(lam, 1e-9)) - lam - lg)


def outcome(lh: float, la: float, p: dict, post: bool = False, season: int | None = None,
            ties_allowed: bool | None = None) -> dict:
    """{"p_home", "p_tie", "p_away", "p_reg_tie", "margin", "total"}: final record probabilities (shootouts count as
    ties). `post`: a game that cannot end level (NCAA, most conference tournament games)."""
    n = p.get("max_goals", 12)
    ph, pa = _pois(lh, n), _pois(la, n)
    M = np.outer(ph, pa)
    d = np.trace(M)
    win = np.tril(M, -1).sum()
    loss = np.triu(M, 1).sum()
    tie = d * (1 + p["rho"])
    s = win + loss + tie
    win, loss, tie = win / s, loss / s, tie / s
    k = p.get("k_ot", 1.0)
    share = lh ** k / (lh ** k + la ** k)
    if ties_allowed is None:
        ties_allowed = not post
    if not ties_allowed:
        q = 1.0
    else:
        q = p["q_3v3"] if (season or 9999) >= 2022 else p["q_pre"]
    pw = win + tie * q * share
    pl = loss + tie * q * (1 - share)
    pt = tie * (1 - q)
    return {"p_home": pw, "p_tie": pt, "p_away": pl, "p_reg_tie": tie, "margin": lh - la, "total": lh + la}


# ── walk-forward ───────────────────────────────────────────────────────────────────────────────────────────

def _ord(iso: str) -> int:
    return datetime.fromisoformat(str(iso)[:10]).date().toordinal()


def game_day(g: dict) -> int:
    t = datetime.fromisoformat(str(g["date"]).replace("Z", "+00:00"))
    return (t - timedelta(hours=9)).date().toordinal()


def postseason(g: dict) -> bool:
    return g.get("stype") in ("ncaa", "conf")


def season_ratings(season: int, games: list[dict], d1: set[str], prior: dict, p: dict,
                   through_day: int | None = None) -> Fit:
    rows = []
    for g in games:
        if g.get("status") != "post" or g.get("stype") == "exh":
            continue
        gd = game_day(g)
        if through_day is not None and gd >= through_day:
            continue
        rh, ra = regulation_goals(g)
        if rh is None:
            continue
        rows.append((gd, g["home"], g["away"], bool(g.get("neutral")), rh, ra))
    ref = through_day if through_day is not None else (max((r[0] for r in rows), default=0) + 1)
    return fit(rows, ref, prior, p, d1)


def end_prior(f: Fit | None, carry: float) -> dict[str, tuple[float, float]]:
    if f is None:
        return {}
    return {t: (carry * float(f.att[i]), carry * float(f.dfn[i])) for t, i in f.idx.items() if t != "__nd1__"}


def walk_forward(seasons: list[int], stores: dict[int, dict], p: dict | None = None,
                 collect_fits: bool = False) -> tuple[list[dict], dict]:
    """Predict every played game from games before its day (ratings refitted once per game day). Returns
    (predictions, {season: end-of-season Fit})."""
    p = {**DEFAULTS, **(p or {})}
    preds: list[dict] = []
    ends: dict[int, Fit] = {}
    prev_end = None
    for s in sorted(seasons):
        st = stores.get(s)
        if not st:
            prev_end = None
            continue
        games = [g for g in st["games"] if g.get("stype") != "exh"]
        d1 = {t for t, v in st["teams"].items() if v.get("d1")}
        prior = end_prior(prev_end, p["carry"])
        days = sorted({game_day(g) for g in games if g.get("status") == "post"})
        by_day: dict[int, list] = {}
        for g in games:
            if g.get("status") == "post":
                by_day.setdefault(game_day(g), []).append(g)
        rows: list[tuple] = []
        f = None
        for dday in days:
            f = fit(rows, dday, prior, p, d1, init=f, iters=4 if f is not None else 8)
            for g in by_day[dday]:
                lh, la = f.means(g["home"], g["away"], bool(g.get("neutral")))
                post = postseason(g)
                o = outcome(lh, la, p, post=post, season=s, ties_allowed=_ties_allowed(g, s))
                preds.append({"id": g["id"], "season": s, "day": dday, "home": g["home"], "away": g["away"],
                              "res": g.get("res"), "stype": g.get("stype"), "neutral": bool(g.get("neutral")),
                              "lh": lh, "la": la, **o, "n_fit": len(rows),
                              "d1": g["home"] in d1 and g["away"] in d1})
            for g in by_day[dday]:
                rh, ra = regulation_goals(g)
                if rh is not None:
                    rows.append((dday, g["home"], g["away"], bool(g.get("neutral")), rh, ra))
        f = fit(rows, (days[-1] + 1) if days else 0, prior, p, d1, init=f, iters=8)
        ends[s] = f
        prev_end = f
    return preds, ends


def _ties_allowed(g: dict, season: int) -> bool:
    """NCAA games and conference tournament games are played to a winner (a few early-round conference games in
    older seasons could tie; treated as decided)."""
    return g.get("stype") not in ("ncaa", "conf")


# ── scoring ────────────────────────────────────────────────────────────────────────────────────────────────

def logloss3(pr: dict) -> float | None:
    r = pr.get("res")
    if r not in ("W", "T", "L"):
        return None
    p = {"W": pr["p_home"], "T": pr["p_tie"], "L": pr["p_away"]}[r]
    return -math.log(max(p, 1e-12))


def baseline_rates(preds: list[dict], seasons: Iterable[int]) -> dict:
    """Naive base rates (home win / tie / away win) from the given seasons' regular-season and postseason games:
    the no-skill reference."""
    ss = set(seasons)
    out = {}
    for kind in ("reg", "post"):
        c = {"W": 0, "T": 0, "L": 0}
        for pr in preds:
            if pr["season"] in ss and pr.get("res") in c and (postseason(pr) == (kind == "post")) and not pr["neutral"]:
                c[pr["res"]] += 1
        n = sum(c.values())
        if kind == "post" and n < 30:
            # too few home-ice postseason games in the rate seasons (the women's early CHN-only seasons carry no
            # tournament labels): the regular season's home and away shares, renormalised without the tie
            r = out["reg"]
            d = (r["W"] + r["L"]) or 1.0
            out[kind] = {"W": r["W"] / d, "T": 0.0, "L": r["L"] / d}
            continue
        out[kind] = {k: v / (n or 1) for k, v in c.items()}
    return out


def baseline_probs(pr: dict, rates: dict) -> dict:
    kind = "post" if postseason(pr) else "reg"
    r = rates[kind]
    if pr["neutral"]:
        dec = (r["W"] + r["L"]) / 2
        return {"p_home": dec, "p_tie": r["T"], "p_away": dec}
    return {"p_home": r["W"], "p_tie": r["T"], "p_away": r["L"]}


def evaluate(preds: list[dict], seasons: Iterable[int], rate_seasons: Iterable[int] | None = None,
             d1_only: bool = True) -> dict:
    """Log-loss (3-way: win / tie / loss in the NCAA record) of the model and the naive base-rate baseline, the
    paired difference with a 95% CI, Brier on the home-win outcome, accuracy, calibration buckets."""
    ss = set(seasons)
    rs = list(rate_seasons) if rate_seasons is not None else [s - 1 for s in ss]
    rates = baseline_rates(preds, set(rs) | ({min(ss) - 1} if not rs else set()))
    m, b = [], []
    cal = []
    for pr in preds:
        if pr["season"] not in ss or (d1_only and not pr.get("d1")):
            continue
        lm = logloss3(pr)
        if lm is None:
            continue
        bp = baseline_probs(pr, rates)
        lb = logloss3({**bp, "res": pr["res"]})
        m.append(lm)
        b.append(lb)
        cal.append((pr["p_home"], 1.0 if pr["res"] == "W" else 0.0, pr["p_tie"], 1.0 if pr["res"] == "T" else 0.0))
    if not m:
        return {"n": 0}
    m, b = np.array(m), np.array(b)
    d = m - b
    se = d.std(ddof=1) / math.sqrt(len(d)) if len(d) > 1 else float("nan")
    ph = np.array([c[0] for c in cal])
    yh = np.array([c[1] for c in cal])
    bins = []
    edges = [0, .15, .25, .35, .45, .55, .65, .75, .85, 1.0001]
    for lo, hi in zip(edges[:-1], edges[1:]):
        k = (ph >= lo) & (ph < hi)
        if k.sum() >= 15:
            bins.append({"lo": round(lo, 2), "hi": round(min(hi, 1), 2), "n": int(k.sum()), "p_mean": round(float(ph[k].mean()), 4),
                         "y_mean": round(float(yh[k].mean()), 4)})
    pick = np.array([max(("W", c[0]), ("L", 1 - c[0] - c[2]), ("T", c[2]), key=lambda x: x[1])[0] for c in cal])
    res = np.array([pr["res"] for pr in preds if pr["season"] in ss and (not d1_only or pr.get("d1")) and logloss3(pr) is not None])
    return {"n": int(len(m)), "logloss": round(float(m.mean()), 4), "logloss_base": round(float(b.mean()), 4),
            "diff": round(float(d.mean()), 4), "ci95": [round(float(d.mean() - 1.96 * se), 4), round(float(d.mean() + 1.96 * se), 4)],
            "brier_home": round(float(((ph - yh) ** 2).mean()), 4), "acc": round(float((pick == res).mean()), 4),
            "tie_rate": round(float(np.mean([c[3] for c in cal])), 4), "tie_pred": round(float(np.mean([c[2] for c in cal])), 4),
            "calibration": bins, "rates": rates}
