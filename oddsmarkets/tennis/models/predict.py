"""
Per-match prediction: Elo (builder B's `elo.py`) blended with the serve/return model (`serve_return.py`),
priced through the exact match chain (`match_chain.py`).

1. Serve/return: h_i = hold_prob(model, i, j, surface, level, best_of, indoor) for each server (the match's
   indoor flag, exactly as backtest.predictions scores it); the serve-point
   probabilities p_i = point_prob_from_hold(h_i) feed the chain, giving sr_p = P(player 1 wins).
2. Elo: elo_p = elo.p_win(r1, r2, surface, best_of, params).
3. Blend at the win-probability logit with fitted weights (no intercept; the model is symmetric):
       logit p = w_elo * logit(elo_p) + w_sr * logit(sr_p) + w_gelo * gelo_diff + w_mr * mr_diff
   where gelo_diff is the game-share Elo difference (gelo.py, a margin-of-victory rating; 0 when either player
   has never been rated) and mr_diff the market-rating difference on the match's logit scale (mrating.py: the
   players' strengths learnt from earlier matches' closing prices and results; a player never seen takes the
   unranked prior). w_gelo / w_mr are 0 (the term off) unless the committed fit carries them.
   `blend_w` = w_elo / (w_elo + w_sr) is the Elo share and w_elo + w_sr the sharpness. The weights are
   fitted by maximum likelihood on walk-forward predictions (backtest.py) and committed per tour in
   models/fitted/predict_<tour>.json; DEFAULT_BLEND applies until then.
4. The blended probability is turned back into serve-point probabilities by moving the serve-point edge
   (p1 + d, p2 - d) until the chain returns the blended P(win), so the set-score, total-games and
   handicap distributions are consistent with the headline probability while keeping the serve/return
   model's level of serve dominance (p1 + p2), which is what drives tiebreaks and total games.

5. Match-level dispersion: "dist" averages the chain over a per-match edge e ~ N(0, sigma^2)
   (match_chain.match_mix), re-centred so dist["p1_win"] still equals the blend; sigma is fitted per tour by the
   backtest (set-score likelihood) and stored with the blend. "p_srv" is the centre pair without dispersion,
   which reproduces P(win) exactly in the plain chain (live.py uses it for in-match probabilities).

When the serve/return model is unavailable, the serve level comes from BASE_SPW (tour x surface averages)
and Elo alone sets the edge. When Elo is unavailable, sr_p is used alone.

Deciding-set rules (`final_set_rule`) when the MATCH does not carry one: `default_final_rule`.
"""
from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Iterable

import numpy as np

from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.models import match_chain as mc

logger = logging.getLogger(__name__)

VERSION = "predict-1"
DEFAULT_BLEND = {"atp": {"w_elo": 0.55, "w_sr": 0.45, "sigma": 0.03}, "wta": {"w_elo": 0.6, "w_sr": 0.4, "sigma": 0.03}}
# average serve-point win rates at tour level (approximate, used only when the serve/return model is absent)
BASE_SPW = {"atp": {"hard": 0.645, "clay": 0.625, "grass": 0.665}, "wta": {"hard": 0.565, "clay": 0.555, "grass": 0.58}}
EPS = 1e-6


def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, float)))


def default_final_rule(level: str | None, best_of: int, year: int | None, tid: str | None = None) -> str:
    """Deciding-set rule by event and year (canon.py's table takes precedence when the MATCH carries one).
    Slams from 2022: tiebreak to 10 at 6-6. Before: US Open tb7 (since 1970); Wimbledon 12-12 tiebreak 2019-21;
    Australian Open 10-point tiebreak 2019-21; Roland Garros and the rest of the Slams advantage before 2022
    (RG: advantage until 2021). Tour events: tb7."""
    y = int(year or 2026)
    try:
        from oddsmarkets.tennis import canon
        if tid:
            rule, at = canon.final_set_rule("atp", str(tid), y, level)
            return "tb12" if (rule == "tb7" and int(at or 6) == 12) else str(rule)
    except Exception:  # noqa: BLE001
        pass
    if str(level or "") != "slam":
        return "tb7"
    if y >= 2022:
        return "tb10"
    t = str(tid or "").lower()
    if t in ("us-open", "usopen"):
        return "tb7"
    if t == "wimbledon" and y >= 2019:
        return "tb12"
    if t in ("australian-open", "ao") and y >= 2019:
        return "tb10"
    return "adv"


# ── fitted blend ─────────────────────────────────────────────────────────────

def blend_params(tour: str) -> dict:
    t = _io.tour_key(tour)
    f = _io.read_json(_io.FITTED / f"predict_{t}.json")
    if isinstance(f, dict) and "w_elo" in f and "w_sr" in f:
        return {"w_elo": float(f["w_elo"]), "w_sr": float(f["w_sr"]), "w_gelo": float(f.get("w_gelo") or 0.0),
                "w_mr": float(f.get("w_mr") or 0.0),
                "sigma": float(f["sigma"]) if f.get("sigma") is not None else DEFAULT_BLEND[t]["sigma"],
                "version": f.get("version", VERSION), "fitted": True}
    return {**DEFAULT_BLEND[t], "version": VERSION, "fitted": False}


def blend(elo_p, sr_p, w_elo: float, w_sr: float, gdiff=None, w_gelo: float = 0.0, mdiff=None, w_mr: float = 0.0):
    z = w_elo * logit(elo_p) + w_sr * logit(sr_p)
    if gdiff is not None and w_gelo:
        z = z + w_gelo * np.asarray(gdiff, float)
    if mdiff is not None and w_mr:
        z = z + w_mr * np.asarray(mdiff, float)
    return sigmoid(z)


def fit_blend(elo_p: Iterable[float], sr_p: Iterable[float], y: Iterable[int], ridge: float = 1e-3,
              gdiff: Iterable[float] | None = None, mdiff: Iterable[float] | None = None) -> dict:
    """Max-likelihood (w_elo, w_sr[, w_gelo][, w_mr]) for logit p = w_elo logit(elo) + w_sr logit(sr)
    [+ w_gelo gdiff] [+ w_mr mdiff] (Newton, tiny ridge). Without `gdiff` / `mdiff` the result has no "w_gelo" /
    "w_mr" key."""
    cols = [logit(list(elo_p)), logit(list(sr_p))]
    names = ["w_elo", "w_sr"]
    if gdiff is not None:
        cols.append(np.asarray(list(gdiff), float))
        names.append("w_gelo")
    if mdiff is not None:
        cols.append(np.asarray(list(mdiff), float))
        names.append("w_mr")
    X = np.column_stack(cols)
    k = X.shape[1]
    yy = np.asarray(list(y), float)
    if len(yy) < 50:
        return {"w_elo": None, "w_sr": None, "n": int(len(yy))}
    w = np.array([0.5, 0.5] + [0.0] * (k - 2))
    for _ in range(50):
        p = sigmoid(X @ w)
        g = X.T @ (yy - p) - ridge * w
        Hm = -(X.T * (p * (1 - p))) @ X - ridge * np.eye(k)
        step = np.linalg.solve(Hm, g)
        w = w - step
        if np.max(np.abs(step)) < 1e-9:
            break
    p = np.clip(sigmoid(X @ w), 1e-4, 1 - 1e-4)
    ll = float(-np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p)))
    out = {"w_elo": float(w[0]), "w_sr": float(w[1]), "n": int(len(yy)), "logloss": round(ll, 5)}
    for nm, v in zip(names[2:], w[2:]):
        out[nm] = float(v)
    return out


# ── model access (builder B), injectable ─────────────────────────────────────

def _mod(name: str):
    try:
        import importlib
        return importlib.import_module(f"oddsmarkets.tennis.models.{name}")
    except Exception as exc:  # noqa: BLE001
        logger.info("tennis predict: models.%s unavailable (%s)", name, exc)
        return None


class Context:
    """
    Everything predict needs at one date: Elo ratings and parameters, the serve/return model, the blend.
    Build with `context(tour, date)` or pass pieces explicitly (tests, backtests):
        elo_ratings {pid: {"all","hard","clay","grass","n"}}, elo_params, elo_mod (with p_win),
        sr_model (serve_return.fit output), sr_mod (with hold_prob, point_prob_from_hold),
        blend {"w_elo","w_sr"[,"w_gelo"][,"w_mr"]}, gelo_ratings {pid: {"all","hard","clay","grass"}} and
        gelo_params (gelo.py), mr_states {pid: state} and mr_params (mrating.py); or a `p_srv_fn(p1, p2, surface,
        level, best_of) -> (pa, pb)`, `elo_fn(p1, p2, surface, best_of) -> p`, `gelo_fn(p1, p2, surface) -> diff`
        and `mr_fn(p1, p2, surface, best_of) -> scaled diff` overriding the modules.
    """

    def __init__(self, tour: str, when: Any = None, elo_ratings: dict | None = None, elo_params: dict | None = None,
                 elo_mod=None, sr_model: dict | None = None, sr_mod=None, blend: dict | None = None,
                 p_srv_fn=None, elo_fn=None, gelo_ratings: dict | None = None, gelo_params: dict | None = None,
                 gelo_fn=None, mr_states: dict | None = None, mr_params: dict | None = None, mr_fn=None):
        self.tour = _io.tour_key(tour)
        self.date = _io.day(when)
        self.elo_ratings = elo_ratings
        self.elo_params = elo_params
        self.elo_mod = elo_mod
        self.sr_model = sr_model
        self.sr_mod = sr_mod
        self.blend = dict(blend or blend_params(self.tour))
        self.p_srv_fn = p_srv_fn
        self.elo_fn = elo_fn
        self.gelo_ratings = gelo_ratings
        self.gelo_params = gelo_params
        self.gelo_fn = gelo_fn
        self.mr_states = mr_states
        self.mr_params = mr_params
        self.mr_fn = mr_fn

    # market rating, on the match's logit scale (0 when unavailable: the blend then has no market term)
    def mr_diff(self, p1: str, p2: str, surface: str, best_of: int) -> float:
        if self.mr_fn is not None:
            v = self.mr_fn(p1, p2, surface, best_of)
            return float(v) if v is not None and math.isfinite(v) else 0.0
        if self.mr_states is None:
            return 0.0
        from oddsmarkets.tennis.models import mrating as MRt
        prm = self.mr_params or MRt.params(self.tour)
        return MRt.scale(best_of, prm) * MRt.diff(self.mr_states.get(p1), self.mr_states.get(p2), surface, prm)

    # game-share Elo (0 when unavailable: the blend then reduces to Elo + serve/return)
    def gelo_diff(self, p1: str, p2: str, surface: str) -> float:
        if self.gelo_fn is not None:
            v = self.gelo_fn(p1, p2, surface)
            return float(v) if v is not None and math.isfinite(v) else 0.0
        if self.gelo_ratings is None:
            return 0.0
        from oddsmarkets.tennis.models import gelo as G
        return float(G.diff(self.gelo_ratings.get(p1), self.gelo_ratings.get(p2), surface,
                            self.gelo_params or G.params(self.tour)))

    # Elo
    def elo_p(self, p1: str, p2: str, surface: str, best_of: int) -> float | None:
        if self.elo_fn is not None:
            return self.elo_fn(p1, p2, surface, best_of)
        if self.elo_mod is None or self.elo_ratings is None:
            return None
        r1, r2 = self.elo_ratings.get(p1), self.elo_ratings.get(p2)
        try:
            return float(self.elo_mod.p_win(r1 or {}, r2 or {}, _io.fold_surface(surface), int(best_of), self.elo_params))
        except Exception as exc:  # noqa: BLE001
            logger.debug("elo p_win failed: %s", exc)
            return None

    # serve/return
    def p_srv(self, p1: str, p2: str, surface: str, level: str, best_of: int,
              indoor: bool = False) -> tuple[float, float] | None:
        """The serve/return model's serve-point pair; `indoor` (and a raw "carpet" surface) add the fitted
        indoor term, as backtest.predictions does, so the site prices what the backtest scored."""
        if self.p_srv_fn is not None:
            return self.p_srv_fn(p1, p2, surface, level, best_of)
        if self.sr_mod is None or self.sr_model is None:
            return None
        try:
            s = surface or "hard"
            h1 = self.sr_mod.hold_prob(self.sr_model, p1, p2, s, level, int(best_of), bool(indoor))
            h2 = self.sr_mod.hold_prob(self.sr_model, p2, p1, s, level, int(best_of), bool(indoor))
            return float(self.sr_mod.point_prob_from_hold(h1)), float(self.sr_mod.point_prob_from_hold(h2))
        except Exception as exc:  # noqa: BLE001
            logger.debug("serve/return failed: %s", exc)
            return None


def _elo_state(tour: str, when) -> tuple:
    """(module, ratings at `when`, params) from builder B's elo.py; (None, None, None) when unavailable."""
    E = _mod("elo")
    if E is None:
        return None, None, None
    try:
        hist = E.for_tour(tour, through=when) if hasattr(E, "for_tour") else E.history(tour)
        rt = E.ratings_at(hist, when) if when is not None else E.ratings_at(hist, None)
        params = (hist.get("params") if isinstance(hist, dict) else None) or (E.params(tour) if hasattr(E, "params") else None)
        return E, rt, params
    except Exception as exc:  # noqa: BLE001
        logger.info("tennis predict: elo state failed (%s)", exc)
        return None, None, None


def _sr_state(tour: str, when) -> tuple:
    S = _mod("serve_return")
    if S is None:
        return None, None
    try:
        return S, S.for_tour(tour, through=when)
    except Exception as exc:  # noqa: BLE001
        logger.info("tennis predict: serve/return state failed (%s)", exc)
        return None, None


def _mr_state(tour: str) -> tuple:
    """(current market-rating states, params); (None, None) when unavailable. Current = after every match on
    disk (finished matches are priced from their exact pre-match values by the site, analytics/matches.py)."""
    try:
        from oddsmarkets.tennis.models import mrating as MRt
        hist = MRt.history(tour)
        return hist.get("current") or {}, hist.get("params") or MRt.params(tour)
    except Exception as exc:  # noqa: BLE001
        logger.info("tennis predict: market rating state failed (%s)", exc)
        return None, None


def _gelo_state(tour: str, when) -> tuple:
    """(ratings before `when`, params) of the game-share Elo; (None, None) when unavailable."""
    try:
        from oddsmarkets.tennis.models import gelo as G
        hist = G.history(tour)
        return G.ratings_at(hist, when), hist.get("params") or G.params(tour)
    except Exception as exc:  # noqa: BLE001
        logger.info("tennis predict: game-share Elo state failed (%s)", exc)
        return None, None


_CTX: dict = {}


def context(tour: str, when: Any = None, **kw) -> Context:
    """Context at `when` (default today) from the cached fits of builder B; memoised per (tour, date)."""
    t = _io.tour_key(tour)
    d = _io.day(when) or date.today()
    key = (t, d.isoformat())
    if not kw and key in _CTX:
        return _CTX[key]
    E, rt, prm = _elo_state(t, d)
    S, srm = _sr_state(t, d)
    gk: dict = {}
    if "gelo_ratings" not in kw and "gelo_fn" not in kw:
        gk["gelo_ratings"], gk["gelo_params"] = _gelo_state(t, d)
    if "mr_states" not in kw and "mr_fn" not in kw and blend_params(t).get("w_mr"):
        gk["mr_states"], gk["mr_params"] = _mr_state(t)
    ctx = Context(t, d, elo_ratings=rt, elo_params=prm, elo_mod=E, sr_model=srm, sr_mod=S, **gk, **kw)
    if not kw:
        _CTX[key] = ctx
    return ctx


# ── prediction ───────────────────────────────────────────────────────────────

def predict_many(ctx: Context, rows: list[dict], with_dist: bool = True, shift: bool = True) -> list[dict]:
    """
    rows: [{"p1","p2","surface","best_of","level","indoor"?,"final_set_rule"?}] -> one contract prediction per row:
    {"p1_win","p_srv": [p1, p2],"p_srv_sr": [..] | None,"elo_p","sr_p","blend_w","dist": match(...) | None,"version"}.
    Vectorised through the chain (rows are grouped by best-of and deciding-set rule). With shift=False and
    with_dist=False the edge move is skipped ("p_srv" is then the serve/return model's own pair).
    """
    n = len(rows)
    if n == 0:
        return []
    w_elo, w_sr = float(ctx.blend["w_elo"]), float(ctx.blend["w_sr"])
    w_g = float(ctx.blend.get("w_gelo") or 0.0)
    sigma = float(ctx.blend.get("sigma") or 0.0)
    pa, pb = np.zeros(n), np.zeros(n)
    elo = np.full(n, np.nan)
    gd = np.array([ctx.gelo_diff(r["p1"], r["p2"], r.get("surface")) for r in rows]) if w_g else np.zeros(n)
    w_m = float(ctx.blend.get("w_mr") or 0.0)
    md = (np.array([ctx.mr_diff(r["p1"], r["p2"], r.get("surface"), 5 if int(r.get("best_of") or 3) == 5 else 3)
                    for r in rows]) if w_m else np.zeros(n))
    has_sr = np.zeros(n, bool)
    for i, r in enumerate(rows):
        bo = 5 if int(r.get("best_of") or 3) == 5 else 3
        e = ctx.elo_p(r["p1"], r["p2"], r.get("surface"), bo)
        if e is not None and math.isfinite(e):
            elo[i] = e
        s = ctx.p_srv(r["p1"], r["p2"], r.get("surface"), r.get("level"), bo, bool(r.get("indoor")))
        if s is not None and all(math.isfinite(x) for x in s):
            pa[i], pb[i] = s
            has_sr[i] = True
        else:
            pa[i] = pb[i] = BASE_SPW[ctx.tour][_io.fold_surface(r.get("surface"))]
    out: list[dict | None] = [None] * n
    groups: dict = {}
    for i, r in enumerate(rows):
        bo = 5 if int(r.get("best_of") or 3) == 5 else 3
        rule = r.get("final_set_rule") or default_final_rule(r.get("level"), bo, (_io.day(r.get("date")) or ctx.date or date.today()).year,
                                                             r.get("tid"))
        groups.setdefault((bo, rule), []).append(i)
    for (bo, rule), idx in groups.items():
        ix = np.array(idx)
        sr_p = mc.match_win_prob(pa[ix], pb[ix], bo, rule)
        e = elo[ix]
        hs = has_sr[ix]
        he = np.isfinite(e)
        p = np.where(he & hs, blend(np.where(he, e, 0.5), sr_p, w_elo, w_sr, gd[ix], w_g, md[ix], w_m),
                     np.where(he, np.where(he, e, 0.5), np.where(hs, sr_p, 0.5)))
        # the serve-point edge that reproduces the blended P(win) (skipped when only probabilities are wanted)
        delta = mc.solve_shift(p, pa[ix], pb[ix], bo, rule) if (shift or with_dist) else np.zeros(len(ix))
        qa, qb = pa[ix] + delta, pb[ix] - delta
        dist = None
        if with_dist:
            dm = mc.solve_shift(p, pa[ix], pb[ix], bo, rule, sigma=sigma) if sigma > 0 else delta
            dist = mc.match_mix(pa[ix] + dm, pb[ix] - dm, bo, rule, sigma=sigma)
        for k, i in enumerate(idx):
            d = None
            if dist is not None:
                d = {"p1_win": float(dist["p1_win"][k]), "sets": {s: float(v[k]) for s, v in dist["sets"].items()},
                     "games": mc._to_scalar_dist(dist["games"][k]),
                     "handicap": mc._to_scalar_dist(dist["handicap"][k], dist["handicap_offset"]),
                     "p_tiebreak": float(dist["p_tiebreak"][k]), "p_straight": float(dist["p_straight"][k]),
                     "exp_games": float(dist["exp_games"][k]), "best_of": bo, "final_set_rule": rule}
            out[i] = {"p1_win": float(d["p1_win"]) if d else float(p[k]), "p_srv": [float(qa[k]), float(qb[k])],
                      "p_srv_sr": [float(pa[i]), float(pb[i])] if has_sr[i] else None,
                      "elo_p": float(e[k]) if he[k] else None, "sr_p": float(sr_p[k]) if hs[k] else None,
                      "blend_w": round(w_elo / (w_elo + w_sr), 4) if (w_elo + w_sr) else None,
                      "blend": {"w_elo": w_elo, "w_sr": w_sr, "w_gelo": w_g, "w_mr": w_m}, "gelo_diff": float(gd[i]),
                      "mr_diff": float(md[i]), "basis": "blend" if (he[k] and hs[k]) else
                      ("elo" if he[k] else ("serve_return" if hs[k] else "none")),
                      "best_of": bo, "final_set_rule": rule, "dist": d, "version": VERSION}
    return out  # type: ignore[return-value]


def predict(tour: str, p1: str, p2: str, surface: str, best_of: int = 3, date_: Any = None, level: str = "250",
            ctx: Context | None = None, final_set_rule: str | None = None, with_dist: bool = True, tid: str | None = None,
            indoor: bool = False, **kw) -> dict:
    """Contract: {"p1_win","p_srv": [p1, p2],"elo_p","sr_p","blend_w","dist": match(...)} (plus extras)."""
    when = kw.pop("date", date_)
    ctx = ctx or context(tour, when)
    row = {"p1": p1, "p2": p2, "surface": surface, "best_of": best_of, "level": level, "date": when,
           "final_set_rule": final_set_rule, "tid": tid, "indoor": bool(indoor)}
    return predict_many(ctx, [row], with_dist=with_dist)[0]


def prob_matrix(ctx: Context, pids: list[str], surface: str, best_of: int, level: str, final_set_rule: str = "tb7",
                indoor: bool = False) -> np.ndarray:
    """P[i, j] = P(pids[i] beats pids[j]) for every ordered pair (diagonal 0.5); one vectorised chain call."""
    n = len(pids)
    P = np.full((n, n), 0.5)
    if n < 2:
        return P
    iu, ju = np.triu_indices(n, 1)
    rows = [{"p1": pids[i], "p2": pids[j], "surface": surface, "best_of": best_of, "level": level,
             "final_set_rule": final_set_rule, "indoor": bool(indoor)} for i, j in zip(iu, ju)]
    res = predict_many(ctx, rows, with_dist=False, shift=False)
    pw = np.array([r["p1_win"] for r in res])
    P[iu, ju] = pw
    P[ju, iu] = 1 - pw
    return P
