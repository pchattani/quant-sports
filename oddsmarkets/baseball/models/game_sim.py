"""
Game model: a plate-appearance Monte Carlo (20,000 games, vectorised over simulations).

PA outcome probabilities (generalised log5 / odds ratio)
-------------------------------------------------------
Nine outcome classes (EVENTS): K, BB, HBP, 1B, 2B, 3B, HR, GO (ground-ball out, incl. errors / FC / DP),
AO (air out, incl. sac flies). For batter b facing pitcher p with batter hand h and pitcher hand t:

    q_i  =  b_i(t) * p_i(h) / l_i(h, t)          (b, p: the players' projected rates; l: league rates for the
    q_i *= env_i * hfa_i                           platoon matchup; env = park x weather x umpire; hfa = home bat)
    P_i  =  q_i / sum_j q_j

Switch hitters bat from the side opposite the pitcher. The starter's rates are multiplied (odds) by the
times-through-order factors TTO[k] for his k-th time through (k = 1, 2, 3+). Bullpen rates are a
team aggregate of the available relievers ("hi" leverage tier = the best available arms, "mid" = the
rest), mixed over the relievers' handedness.

Base-out transitions
--------------------
Each outcome is resolved from an empirical table T[event, bases, outs] -> {(new bases, runs, outs added): prob}
fitted on Statcast plate appearances (`fit_transitions`; pre-state read on the PA's last pitch, post-state on
the next PA's first pitch), or the documented default rules below when no data are present. Before each PA a
"running" transition (steals, caught stealing, wild pitches, pickoffs, balks) is drawn from a second table
fitted on the change between a PA's first and last pitch.

Default rules (used only without data): 1B scores a runner from 3rd, from 2nd with p 0.62 (0.80 with two
outs), takes a runner from 1st to 3rd with p 0.28 (0.35); 2B scores 2nd and 3rd and a runner from 1st with
p 0.42 (0.60); GO with a runner on 1st and < 2 outs is a double play with p 0.42, else a fielder's choice
with p 0.30; a runner on 3rd scores on a GO with p 0.45 and on an AO with p 0.50 (< 2 outs); a runner on
2nd takes 3rd on a GO with p 0.50 and on an AO with p 0.20. Running: a lone runner on 1st steals 2nd with
p 0.050 per PA and is caught with p 0.013; any runners advance one base (wild pitch / passed ball / balk)
with p 0.012.

Starter exit
------------
Per simulation the starter gets a pitch limit L ~ N(mu + b (mu - a), sd) (mu, sd from his recent starts; default
88, 12; PC_LIMIT (a, b) puts the realised mean pitch count at mu)
and a run limit R from {4: .25, 5: .35, 6: .25, 7: .15}. Before each PA he is removed when pitches >= L,
runs allowed >= R, or, at the start of an inning, when he is facing the order a third time (or later) and
pitches >= L - 15 with probability 0.35. Pitches per PA are 1 + Poisson(m_e - 1) with m_e the league
mean pitches for that outcome (fitted) times the starter's pitches-per-PA factor.
After the exit the "hi" bullpen tier pitches from the 8th inning onward when the margin is <= 3
(and in extra innings); otherwise the "mid" tier.

Game flow
---------
Nine innings (or `innings`); the home team does not bat in the last half when leading; a walk-off ends the
game at once (a non-home-run walk-off counts only the winning run). Extra innings start each half with a
runner on second when `auto_runner` (regular season 2020 onward; not in the postseason). Games past the
30th inning (never seen in practice) are decided by a coin flip.

Outputs
-------
p_home, run line (home -1.5 / away +1.5 cover), totals distribution and P(over) for half-run lines, first
five innings (home / away / tie, totals), runs per team (mean and distribution), extra-innings rate.
"""
from __future__ import annotations

import itertools
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models._dio import E, EVENTS, NE, fitted_dir

logger = logging.getLogger(__name__)

N_SIMS = 20000
VERSION = 1
KINDS = 5                         # starter TTO1, TTO2, TTO3+, bullpen hi, bullpen mid
MAX_INNINGS = 30

# MLB 2023-25 PA outcome rates (fallback league table; replaced by the fitted season table when data exist)
LEAGUE_DEFAULT = np.array([0.224, 0.083, 0.011, 0.142, 0.043, 0.0035, 0.031, 0.214, 0.2485])
LEAGUE_DEFAULT = LEAGUE_DEFAULT / LEAGUE_DEFAULT.sum()
# platoon odds multipliers (same hand / opposite hand) relative to the overall table
PLATOON_SAME = np.array([1.06, 0.93, 1.10, 0.97, 0.96, 0.95, 0.92, 1.00, 1.01])
PLATOON_OPP = 1.0 / PLATOON_SAME
# times through the order (odds multipliers on the starter's rates), relative shape ...
_TTO_RAW = np.array([[1.00] * NE,
                     [0.95, 1.00, 1.00, 1.02, 1.04, 1.04, 1.07, 0.99, 1.00],
                     [0.90, 1.02, 1.00, 1.04, 1.08, 1.08, 1.13, 0.98, 1.00]])
# ... normalised so a starter's average over a typical start (batters faced 39 % / 39 % / 22 % in his first,
# second, third+ time through) is neutral: his projected rates already average over the order
TTO_SHARE = np.array([0.39, 0.39, 0.22])
TTO = _TTO_RAW / np.exp(TTO_SHARE @ np.log(_TTO_RAW))
# home batting (odds); tuned so a league-average matchup gives the observed home win rate (2026: .529 in 2,419
# regular-season games; the simulation with these values gives ~.53)
HFA = np.array([0.981, 1.027, 1.00, 1.012, 1.024, 1.024, 1.024, 1.00, 1.00])
PITCHES_PER_EVENT = np.array([4.85, 5.70, 3.40, 3.25, 3.30, 3.30, 3.35, 3.20, 3.30])
RUN_LIMIT = (np.array([4, 5, 6, 7]), np.array([0.25, 0.35, 0.25, 0.15]))
# The pitch limit's mean sits above the starter's recent average pitch count: those counts already include the early
# exits the run limit and the third-time hook reproduce, so a limit centred on the average ended simulated starts
# short (2025, league-average teams: 84.5 pitches for an average of 88; starters' share of batters faced .567 in the
# backtest sample against .596 actual). Limit mean = mu + b (mu - a) for mu > a, (a, b) fitted so the realised mean
# pitch count equals mu over mu 75-100 (`calibrate_pitch_limit`).
PC_LIMIT = (70.5, 0.266)
# count -> odds multipliers on the rest of the PA (balls, strikes); used by live.py for the current PA
_B = np.arange(4)[:, None]
_S = np.arange(3)[None, :]


def count_mult_default() -> np.ndarray:
    """[4, 3, NE] odds multipliers for the rest of a PA given the count (default, log-linear in balls/strikes)."""
    m = np.ones((4, 3, NE))
    m[..., E["K"]] = np.exp(0.60 * _S - 0.32 * _B)
    m[..., E["BB"]] = np.exp(0.78 * _B - 0.60 * _S)
    for e in ("1B", "2B", "3B", "HR", "GO", "AO", "HBP"):
        m[..., E[e]] = np.exp(0.06 * _B - 0.12 * _S)
    return m


COUNT_MULT = count_mult_default()


# ── transitions ──────────────────────────────────────────────────────────────

@dataclass
class Transitions:
    """Sampling tables: cum/nb/runs/douts are [NE or 1, 8, 3, K]."""
    cum: np.ndarray
    nb: np.ndarray
    runs: np.ndarray
    douts: np.ndarray
    run_cum: np.ndarray
    run_nb: np.ndarray
    run_runs: np.ndarray
    run_douts: np.ndarray
    source: str = "default"

    def to_json(self) -> dict:
        return {k: getattr(self, k).tolist() for k in ("cum", "nb", "runs", "douts", "run_cum", "run_nb", "run_runs",
                                                         "run_douts")} | {"source": self.source}

    @classmethod
    def from_json(cls, d: dict) -> "Transitions":
        kw = {k: np.array(v, dtype=float if "cum" in k else np.int8) for k, v in d.items() if k != "source"}
        return cls(**kw, source=d.get("source", "fitted"))


def _walk(b: int) -> tuple[int, int]:
    if not b & 1:
        return b | 1, 0
    if not b & 2:
        return b | 3, 0
    if not b & 4:
        return 7, 0
    return 7, 1


def _default_outcomes(ev: str, b: int, o: int) -> list[tuple[float, int, int, int]]:
    r1, r2, r3 = bool(b & 1), bool(b & 2), bool(b & 4)
    two = o == 2
    if ev == "K":
        return [(1.0, b, 0, 1)]
    if ev in ("BB", "HBP"):
        nb, r = _walk(b)
        return [(1.0, nb, r, 0)]
    if ev == "HR":
        return [(1.0, 0, 1 + r1 + r2 + r3, 0)]
    if ev == "3B":
        return [(1.0, 4, r1 + r2 + r3, 0)]
    out = []
    if ev == "2B":
        p = 0.60 if two else 0.42
        for sc, pr in ((True, p), (False, 1 - p)):
            if not r1 and not sc:
                continue
            if not r1:
                out.append((1.0, 2, r2 + r3, 0))
                break
            out.append((pr, 2 | (0 if sc else 4), r2 + r3 + (1 if sc else 0), 0))
        return out
    if ev == "1B":
        p2 = 0.80 if two else 0.62
        p13 = 0.35 if two else 0.28
        for s2, q2 in ((True, p2), (False, 1 - p2)):
            if not r2 and not s2:
                continue
            q2 = q2 if r2 else 1.0
            for t1, q1 in ((True, p13), (False, 1 - p13)):
                if not r1 and not t1:
                    continue
                q1 = q1 if r1 else 1.0
                runs = int(r3) + int(r2 and s2)
                nb = 1
                third = r2 and not s2
                if third:
                    nb |= 4
                if r1:
                    if t1 and not third:
                        nb |= 4
                    else:
                        nb |= 2
                out.append((q2 * q1, nb, runs, 0))
        return out
    if ev == "AO":
        if two:
            return [(1.0, b, 0, 1)]
        res = []
        for s3, q3 in ((True, 0.50), (False, 0.50)):
            if not r3 and not s3:
                continue
            q3 = q3 if r3 else 1.0
            for a2, qa in ((True, 0.20), (False, 0.80)):
                if not r2 and not a2:
                    continue
                qa = qa if r2 else 1.0
                nb = int(r1)
                runs = 0
                if r3:
                    if s3:
                        runs += 1
                    else:
                        nb |= 4
                if r2:
                    if a2 and not (nb & 4):
                        nb |= 4
                    else:
                        nb |= 2
                res.append((q3 * qa, nb, runs, 1))
        return res
    if ev == "GO":
        if two:
            return [(1.0, b, 0, 1)]
        res = []
        pdp, pfc = (0.42, 0.30) if r1 else (0.0, 0.0)
        modes = [("dp", pdp), ("fc", (1 - pdp) * pfc), ("plain", (1 - pdp) * (1 - pfc))] if r1 else [("plain", 1.0)]
        for mode, qm in modes:
            for s3, q3 in ((True, 0.45), (False, 0.55)):
                if not r3 and not s3:
                    continue
                q3 = q3 if r3 else 1.0
                for a2, qa in ((True, 0.50), (False, 0.50)):
                    if not r2 and not a2:
                        continue
                    qa = qa if r2 else 1.0
                    douts = 2 if mode == "dp" else 1
                    nb, runs = 0, 0
                    forced3 = r3 and r2 and r1                      # bases loaded: runner on 3rd forced
                    if r3:
                        if (s3 or forced3) and o + douts < 3:
                            runs += 1
                        elif not (s3 or forced3):
                            nb |= 4
                    if r2:
                        if a2 or r1:
                            if not (nb & 4):
                                nb |= 4
                            else:
                                nb |= 2
                        else:
                            nb |= 2
                    if mode == "fc":
                        nb |= 1                                     # batter safe, runner from 1st out
                    elif mode == "plain" and r1:
                        nb |= 2 if not (nb & 2) else 0
                    if o + douts >= 3:
                        runs = 0
                    res.append((qm * q3 * qa, nb, runs, douts))
        return res
    raise ValueError(ev)


def _pack(cells: dict[tuple, list[tuple[float, int, int, int]]], shape: tuple) -> tuple[np.ndarray, ...]:
    K = max(len(v) for v in cells.values())
    cum = np.ones(shape + (K,))
    nb = np.zeros(shape + (K,), np.int8)
    rr = np.zeros(shape + (K,), np.int8)
    do = np.zeros(shape + (K,), np.int8)
    for idx, lst in cells.items():
        agg: dict[tuple, float] = {}
        for p, b2, r, d in lst:
            agg[(b2, r, d)] = agg.get((b2, r, d), 0.0) + p
        items = sorted(agg.items(), key=lambda kv: -kv[1])
        tot = sum(v for _, v in items) or 1.0
        c = 0.0
        for k, ((b2, r, d), p) in enumerate(items):
            c += p / tot
            cum[idx + (k,)] = c
            nb[idx + (k,)], rr[idx + (k,)], do[idx + (k,)] = b2, r, d
        cum[idx + (slice(len(items) - 1, None),)] = 1.0
        if len(items) < K:                                   # pad with the last outcome
            for k in range(len(items), K):
                nb[idx + (k,)], rr[idx + (k,)], do[idx + (k,)] = nb[idx + (len(items) - 1,)], rr[idx + (len(items) - 1,)], do[idx + (len(items) - 1,)]
    return cum, nb, rr, do


def _default_running(b: int, o: int) -> list[tuple[float, int, int, int]]:
    out = []
    p_sb, p_cs, p_adv = (0.050, 0.013, 0.012)
    stay = 1.0
    if b == 1:
        out += [(p_sb, 2, 0, 0), (p_cs, 0, 0, 1)]
        stay -= p_sb + p_cs
    if b:
        nb = ((b << 1) & 7)
        runs = 1 if b & 4 else 0
        out.append((p_adv, nb, runs, 0))
        stay -= p_adv
    out.append((stay, b, 0, 0))
    return out


def default_transitions() -> Transitions:
    cells = {(e, b, o): _default_outcomes(EVENTS[e], b, o) for e in range(NE) for b in range(8) for o in range(3)}
    cum, nb, rr, do = _pack(cells, (NE, 8, 3))
    rcells = {(0, b, o): _default_running(b, o) for b in range(8) for o in range(3)}
    rc, rn, rru, rd = _pack(rcells, (1, 8, 3))
    return Transitions(cum, nb, rr, do, rc, rn, rru, rd, "default")


def fit_transitions(pa: pd.DataFrame, min_cell: int = 30, prior: Transitions | None = None) -> Transitions:
    """
    Empirical tables from plate appearances (`_dio.plate_appearances`). Cells with fewer than `min_cell`
    PAs keep the default rules; others are the observed frequencies with the default as a 5-PA prior.
    The running table uses (bases_start, outs_start) -> (bases, outs, score_pre - score_start).
    """
    prior = prior or default_transitions()
    if pa is None or not len(pa):
        return prior
    ok = (pa["outs"] < 3) & (pa["outs_post"] >= pa["outs"]) & (pa["runs"] >= 0) & (pa["runs"] <= 4)
    d = pa[ok]
    dout = (d["outs_post"] - d["outs"]).clip(0, 3).to_numpy()
    nbp = np.where(d["outs_post"].to_numpy() >= 3, d["bases"].to_numpy(), d["bases_post"].to_numpy())
    key = pd.DataFrame({"e": d["ev"].to_numpy(), "b": d["bases"].to_numpy(), "o": d["outs"].to_numpy(),
                        "nb": nbp, "r": d["runs"].to_numpy(), "d": dout})
    cnt = key.groupby(["e", "b", "o", "nb", "r", "d"]).size()
    cells: dict[tuple, list] = {}
    tot = key.groupby(["e", "b", "o"]).size()
    for e in range(NE):
        for b in range(8):
            for o in range(3):
                dflt = _default_outcomes(EVENTS[e], b, o)
                n = int(tot.get((e, b, o), 0))
                if n < min_cell:
                    cells[(e, b, o)] = dflt
                    continue
                sub = cnt.loc[(e, b, o)]
                lst = [(float(c) / (n + 5.0), int(nb_), int(r), int(dd)) for (nb_, r, dd), c in sub.items()]
                lst += [(p * 5.0 / (n + 5.0), b2, r, dd) for p, b2, r, dd in dflt]
                cells[(e, b, o)] = lst
    cum, nb, rr, do = _pack(cells, (NE, 8, 3))
    # running between pitches
    rk = pd.DataFrame({"b": pa["bases_start"].to_numpy(), "o": pa["outs_start"].to_numpy(), "nb": pa["bases"].to_numpy(),
                       "r": (pa["score_pre"] - pa["score_start"]).clip(0, 3).to_numpy(),
                       "d": (pa["outs"] - pa["outs_start"]).clip(0, 2).to_numpy()})
    rk = rk[(rk["o"] < 3) & ((rk["o"] + rk["d"]) < 3)]
    rcnt = rk.groupby(["b", "o", "nb", "r", "d"]).size()
    rtot = rk.groupby(["b", "o"]).size()
    rcells = {}
    for b in range(8):
        for o in range(3):
            n = int(rtot.get((b, o), 0))
            if n < min_cell:
                rcells[(0, b, o)] = _default_running(b, o)
                continue
            sub = rcnt.loc[(b, o)]
            rcells[(0, b, o)] = [(float(c) / n, int(nb_), int(r), int(dd)) for (nb_, r, dd), c in sub.items()]
    rc, rn, rru, rd = _pack(rcells, (1, 8, 3))
    return Transitions(cum, nb, rr, do, rc, rn, rru, rd, f"fitted ({len(d)} PA)")


_TRANS: dict[str, Transitions] = {}
_PPE: dict[str, np.ndarray] = {}


def transitions(name: str = "mlb") -> Transitions:
    """Committed fitted tables (models/fitted/transitions_<name>.json) or the defaults."""
    if name in _TRANS:
        return _TRANS[name]
    p = fitted_dir() / f"transitions_{name}.json"
    t = None
    if p.exists():
        try:
            d = json.loads(p.read_text())
            if d.get("pitches_per_event"):
                _PPE[name] = np.array(d["pitches_per_event"], float)
            t = Transitions.from_json({k: v for k, v in d.items() if k in ("cum", "nb", "runs", "douts", "run_cum", "run_nb",
                                                                           "run_runs", "run_douts", "source")})
        except Exception as exc:  # noqa: BLE001
            logger.info("bad transitions file %s: %s", p, exc)
    _TRANS[name] = t or default_transitions()
    return _TRANS[name]


# ── matchup probabilities ────────────────────────────────────────────────────

def odds_ratio(b: np.ndarray, p: np.ndarray, l: np.ndarray, mult: np.ndarray | None = None) -> np.ndarray:
    """Generalised log5: q_i = b_i p_i / l_i (* mult_i), normalised. Works on [..., NE] arrays."""
    q = np.asarray(b, float) * np.asarray(p, float) / np.asarray(l, float)
    if mult is not None:
        q = q * mult
    return q / q.sum(axis=-1, keepdims=True)


def league_split(base: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """{"LL","LR","RL","RR"} league rates by (batter hand, pitcher hand) from an overall table."""
    base = LEAGUE_DEFAULT if base is None else np.asarray(base, float)
    same = base * PLATOON_SAME
    opp = base * PLATOON_OPP
    same, opp = same / same.sum(), opp / opp.sum()
    return {"LL": same, "RR": same, "LR": opp, "RL": opp}


def _bat_hand(bats: str, throws: str) -> str:
    bats = (bats or "R").upper()[:1]
    if bats == "S" or bats == "B":
        return "R" if (throws or "R").upper()[:1] == "L" else "L"
    return "L" if bats == "L" else "R"


def neutral_hitter(league: dict, bats: str = "R") -> dict:
    return {"pid": None, "bats": bats, "rates": {"L": league["RL" if bats != "L" else "LL"], "R": league["RR" if bats != "L" else "LR"]}}


def neutral_pitcher(league: dict, throws: str = "R") -> dict:
    t = throws
    return {"pid": None, "throws": t, "rates": {"L": league["L" + t], "R": league["R" + t]}, "pc_mean": 88.0, "pc_sd": 12.0,
            "ppa": 1.0}


def neutral_bullpen(league: dict) -> dict:
    mix = {"L": 0.5 * (league["LL"] + league["LR"]), "R": 0.5 * (league["RL"] + league["RR"])}
    return {"hi": {"rates": mix, "share_L": 0.3}, "mid": {"rates": mix, "share_L": 0.3}}


def neutral_side(league: dict, hands: str = "RRLRLRRLR") -> dict:
    return {"lineup": [neutral_hitter(league, h) for h in hands], "starter": neutral_pitcher(league),
            "bullpen": neutral_bullpen(league)}


def prob_table(spec: dict) -> np.ndarray:
    """P[team (0 away, 1 home batting), slot 9, kind 5, NE] for a game spec."""
    league = spec.get("league") or league_split()
    env = np.asarray(spec.get("env", np.ones(NE)), float)
    hfa = np.asarray(spec.get("hfa", HFA), float)
    out = np.zeros((2, 9, KINDS, NE))
    for t, (bat, fld) in enumerate(((spec["away"], spec["home"]), (spec["home"], spec["away"]))):
        mult = env * (hfa if t == 1 else 1.0 / hfa)
        st = fld["starter"]
        th = (st.get("throws") or "R").upper()[:1]
        for s, h in enumerate(bat["lineup"][:9]):
            bh = _bat_hand(h.get("bats"), th)
            base = odds_ratio(h["rates"][th], st["rates"][bh], league[bh + th], mult)
            for k in range(3):
                q = base * TTO[k]
                out[t, s, k] = q / q.sum()
            for k, tier in ((3, "hi"), (4, "mid")):
                bp = fld["bullpen"][tier]
                sl = float(bp.get("share_L", 0.3))
                q = np.zeros(NE)
                for ph, w in (("L", sl), ("R", 1 - sl)):
                    bh2 = _bat_hand(h.get("bats"), ph)
                    q += w * odds_ratio(h["rates"][ph], bp["rates"][bh2], league[bh2 + ph], mult)
                out[t, s, k] = q / q.sum()
    return out


# ── the simulation ───────────────────────────────────────────────────────────

def _draw(cum_rows: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Index of the first cumulative entry >= u per row."""
    return np.minimum((u[:, None] > cum_rows).sum(axis=1), cum_rows.shape[1] - 1)


def simulate(spec: dict, n: int = N_SIMS, seed: int | None = 0, state: dict | None = None,
             trans: Transitions | None = None, keep: bool = False) -> dict:
    """
    Simulate a game n times. `state` (live.py) starts mid-game:
        {"inning", "top": bool, "outs", "bases", "score": [away, home], "bidx": [away, home],
         "sp_in": [away?, home?] (starter still pitching for the team in the field), "sp_pitches": [..],
         "sp_bf": [..], "sp_runs": [..], "count": [balls, strikes] (current PA), "f5": [away, home] | None}
    Returns the summary dict (see module docstring); `keep` adds the raw score arrays.
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    trans = trans or transitions(spec.get("level", "mlb"))
    P = np.cumsum(prob_table(spec), axis=-1)
    P[..., -1] = 1.0
    n_inn = int(spec.get("innings", 9))
    auto = bool(spec.get("auto_runner", False))
    ppe = np.asarray(spec.get("pitches_per_event", _PPE.get(spec.get("level", "mlb"), PITCHES_PER_EVENT)), float)
    S = int(n)
    st = state or {}
    inn = np.full(S, int(st.get("inning", 1)), np.int16)
    top = np.full(S, bool(st.get("top", True)))
    outs = np.full(S, int(st.get("outs", 0)), np.int8)
    bases = np.full(S, int(st.get("bases", 0)), np.int8)
    score = np.tile(np.array(st.get("score", [0, 0]), np.int16), (S, 1))
    bidx = np.tile(np.array(st.get("bidx", [0, 0]), np.int16), (S, 1))
    sides = (spec["away"], spec["home"])
    sp_in = np.tile(np.array(st.get("sp_in", [True, True]), bool), (S, 1))
    sp_pc = np.tile(np.array(st.get("sp_pitches", [0, 0]), np.float32), (S, 1))
    sp_bf = np.tile(np.array(st.get("sp_bf", [0, 0]), np.int16), (S, 1))
    sp_r = np.tile(np.array(st.get("sp_runs", [0, 0]), np.int16), (S, 1))
    mu = np.array([float(s["starter"].get("pc_mean", 88.0)) for s in sides])     # indexed by fielding team
    sd = np.array([float(s["starter"].get("pc_sd", 12.0)) for s in sides])
    ppa = np.array([float(s["starter"].get("ppa", 1.0)) for s in sides])
    mu_lim = mu + PC_LIMIT[1] * np.maximum(mu - PC_LIMIT[0], 0.0)
    sp_lim = mu_lim[None, :] + sd[None, :] * rng.standard_normal((S, 2))
    sp_rlim = rng.choice(RUN_LIMIT[0], size=(S, 2), p=RUN_LIMIT[1])
    done = np.zeros(S, bool)
    f5 = None if st.get("f5") is None else np.tile(np.array(st["f5"], np.int16), (S, 1))
    f5_score = np.full((S, 2), -1, np.int16) if f5 is None else f5.copy()
    if f5 is None and (inn > 5).all():
        f5_score[:] = score            # live state already past five innings without a recorded F5 score
    count = st.get("count")
    first_pa = np.ones(S, bool) if count else np.zeros(S, bool)
    cm = COUNT_MULT[int(count[0]), int(count[1])] if count else None
    half_start = np.zeros(S, bool) if state else np.ones(S, bool)
    coin = np.zeros(S, bool)
    ar = np.arange(S)
    steps = 0
    while not done.all():
        steps += 1
        a = ~done
        idx = np.flatnonzero(a)
        bt = np.where(top[idx], 0, 1)                 # batting team
        ft = 1 - bt
        # automatic runner at the start of an extra half inning
        hs = half_start[idx]
        if auto:
            put = hs & (inn[idx] > n_inn)
            bases[idx[put]] = 2
        half_start[idx] = False
        # starter exit (before the PA)
        si = sp_in[idx, ft]
        if si.any():
            pc = sp_pc[idx, ft]
            tto3 = sp_bf[idx, ft] >= 18
            lim = sp_lim[idx, ft]
            out_ = (pc >= lim) | (sp_r[idx, ft] >= sp_rlim[idx, ft])
            out_ |= hs & tto3 & (pc >= lim - 15) & (rng.random(len(idx)) < 0.35)
            pull = si & out_
            if pull.any():
                sp_in[idx[pull], ft[pull]] = False
        si = sp_in[idx, ft]
        # pitcher kind
        tto = np.minimum(sp_bf[idx, ft] // 9, 2)
        margin = np.abs(score[idx, 0] - score[idx, 1])
        hi = (inn[idx] >= 8) & (margin <= 3)
        kind = np.where(si, tto, np.where(hi, 3, 4))
        slot = bidx[idx, bt] % 9
        # running between pitches (steals, wild pitches) before the PA resolves
        u = rng.random(len(idx))
        b0, o0 = bases[idx], outs[idx]
        k = _draw(trans.run_cum[0, b0, o0], u)
        rb = trans.run_nb[0, b0, o0, k]
        rr = trans.run_runs[0, b0, o0, k]
        rd = trans.run_douts[0, b0, o0, k]
        bases[idx] = rb
        outs[idx] = o0 + rd
        score[idx, bt] += rr
        sp_r[idx, ft] += np.where(si, rr, 0)
        ended_run = outs[idx] >= 3                     # caught stealing for the third out: no PA
        # the PA
        rows = P[bt, slot, kind]
        if cm is not None and first_pa[idx].any():
            fp = first_pa[idx]
            pr = np.diff(np.concatenate([np.zeros((fp.sum(), 1)), rows[fp]], axis=1), axis=1) * cm
            rows = rows.copy()
            rows[fp] = np.cumsum(pr / pr.sum(axis=1, keepdims=True), axis=1)
            first_pa[idx] = False
        ev = _draw(rows, rng.random(len(idx)))
        b1, o1 = bases[idx], np.minimum(outs[idx], 2)
        kk = _draw(trans.cum[ev, b1, o1], rng.random(len(idx)))
        nb = trans.nb[ev, b1, o1, kk]
        runs = trans.runs[ev, b1, o1, kk].astype(np.int16)
        dout = trans.douts[ev, b1, o1, kk]
        pa_ok = ~ended_run
        runs = np.where(pa_ok, runs, 0)
        # walk-off: bottom of the last regulation inning or later
        walk = pa_ok & (bt == 1) & (inn[idx] >= n_inn)
        new_home = score[idx, 1] + runs
        wo = walk & (new_home > score[idx, 0])
        capped = np.where(wo & (ev != E["HR"]), np.minimum(new_home, score[idx, 0] + 1), new_home)
        score[idx, 1] = np.where(bt == 1, capped, score[idx, 1])
        score[idx, 0] = np.where(bt == 0, score[idx, 0] + runs, score[idx, 0])
        real_runs = np.where(bt == 1, capped - (new_home - runs), runs)
        sp_r[idx, ft] += np.where(si & pa_ok, real_runs, 0)
        np_ = 1 + rng.poisson(np.maximum(ppe[ev] * ppa[ft] - 1.0, 0.1))
        sp_pc[idx, ft] += np.where(si & pa_ok, np_, 0)
        sp_bf[idx, ft] += (si & pa_ok).astype(np.int16)
        bidx[idx, bt] += pa_ok.astype(np.int16)
        bases[idx] = np.where(pa_ok, nb, bases[idx])
        outs[idx] = np.where(pa_ok, outs[idx] + dout, outs[idx])
        done[idx[wo]] = True
        # end of half inning
        end = (outs[idx] >= 3) & ~wo
        if end.any():
            e_idx = idx[end]
            was_top = top[e_idx]
            # F5 snapshot after the bottom of the 5th
            snap = (~was_top) & (inn[e_idx] == 5) & (f5_score[e_idx, 0] < 0)
            f5_score[e_idx[snap]] = score[e_idx[snap]]
            last = inn[e_idx] >= n_inn
            fin_top = was_top & last & (score[e_idx, 1] > score[e_idx, 0])
            fin_bot = (~was_top) & last & (score[e_idx, 1] != score[e_idx, 0])
            fin = fin_top | fin_bot
            done[e_idx[fin]] = True
            cont = e_idx[~fin]
            ct = top[cont]
            inn[cont] = np.where(ct, inn[cont], inn[cont] + 1)
            top[cont] = ~ct
            outs[cont] = 0
            bases[cont] = 0
            half_start[cont] = True
            over = cont[inn[cont] > MAX_INNINGS]
            if len(over):
                w = rng.random(len(over)) < 0.5
                score[over, 1] = np.where(w, score[over, 0] + 1, score[over, 1])
                score[over, 0] = np.where(w, score[over, 0], score[over, 1] + 1)
                coin[over] = True
                done[over] = True
    # games that ended before an F5 snapshot was possible cannot happen (>= 9 innings); fill defensively
    miss = f5_score[:, 0] < 0
    f5_score[miss] = score[miss]
    res = summarize(score, f5_score, inn, n_inn)
    res["sims"] = S
    res["steps"] = steps
    res["seconds"] = round(time.perf_counter() - t0, 3)
    res["coin_flips"] = int(coin.sum())
    if keep:
        res["_score"] = score
        res["_f5"] = f5_score
        res["_innings"] = inn
    return res


def calibrate_pitch_limit(league: dict | None = None, mus=(75, 80, 85, 90, 95, 100), sd: float = 13.0, n: int = 20000,
                          seed: int = 7) -> tuple[float, float]:
    """(a, b) for PC_LIMIT: with the limit centred on mu, regress the realised mean starter pitch count (league-
    average teams) on mu, realised = mu - c (mu - a), and invert it: limit mean = mu + c / (1 - c) (mu - a)."""
    import inspect
    global PC_LIMIT
    league = league or league_split()
    saved = PC_LIMIT
    PC_LIMIT = (0.0, 0.0)
    try:
        src = inspect.getsource(simulate).replace("    res = summarize(score, f5_score, inn, n_inn)",
                                                  "    res = summarize(score, f5_score, inn, n_inn)\n    res['_pc'] = sp_pc")
        ns = dict(globals())
        exec(src, ns)
        real = []
        for m in mus:
            spec = {"away": neutral_side(league), "home": neutral_side(league), "league": league, "hfa": np.ones(NE),
                    "auto_runner": True}
            for side in ("away", "home"):
                spec[side]["starter"].update(pc_mean=float(m), pc_sd=sd)
            real.append(float(ns["simulate"](spec, n=n, seed=seed)["_pc"].mean()))
    finally:
        PC_LIMIT = saved
    x = np.asarray(mus, float)
    slope, icpt = np.polyfit(x, np.asarray(real) - x, 1)      # realised - mu = icpt + slope mu = -c (mu - a)
    c = -slope
    a = -icpt / slope if slope else 0.0
    return float(a), float(c / (1 - c))


def summarize(score: np.ndarray, f5: np.ndarray, inn: np.ndarray | None = None, n_inn: int = 9) -> dict:
    a, h = score[:, 0].astype(int), score[:, 1].astype(int)
    tot = a + h
    m = h - a
    S = len(a)
    dist = np.bincount(np.minimum(tot, 40), minlength=41) / S
    over = {f"{k + 0.5:.1f}": round(float((tot > k + 0.5).mean()), 5) for k in range(3, 16)}
    fa, fh = f5[:, 0].astype(int), f5[:, 1].astype(int)
    f5tot = fa + fh
    marg = np.clip(m, -10, 10)
    return {
        "p_home": round(float((h > a).mean()), 5),
        "p_away": round(float((a > h).mean()), 5),
        "runline": {"home_-1.5": round(float((m >= 2).mean()), 5), "away_+1.5": round(float((m <= 1).mean()), 5),
                    "away_-1.5": round(float((m <= -2).mean()), 5), "home_+1.5": round(float((m >= -1).mean()), 5)},
        "margin_dist": {int(k): round(float((marg == k).mean()), 5) for k in range(-10, 11) if k != 0},
        "runs": {"home": round(float(h.mean()), 4), "away": round(float(a.mean()), 4), "total": round(float(tot.mean()), 4),
                 "total_sd": round(float(tot.std()), 4)},
        "total_dist": [round(float(x), 5) for x in dist],
        "total_median": float(np.median(tot)),
        "over": over,
        "f5": {"home": round(float((fh > fa).mean()), 5), "away": round(float((fa > fh).mean()), 5),
               "tie": round(float((fh == fa).mean()), 5), "total": round(float(f5tot.mean()), 4),
               "over": {f"{k + 0.5:.1f}": round(float((f5tot > k + 0.5).mean()), 5) for k in range(0, 9)},
               "home_-0.5": round(float((fh > fa).mean()), 5),
               "home_-1.5": round(float((fh - fa >= 2).mean()), 5), "away_-1.5": round(float((fa - fh >= 2).mean()), 5)},
        "extra_innings": round(float((inn > n_inn).mean()), 5) if inn is not None else None,
        "nrfi": None,
    }


def p_over(res: dict, line: float) -> float | None:
    """P(total > line) from a result's total distribution (half-run lines; whole lines push)."""
    d = np.asarray(res.get("total_dist") or [], float)
    if not len(d):
        return None
    ks = np.arange(len(d))
    if float(line).is_integer():
        win = d[ks > line].sum()
        lose = d[ks < line].sum()
        return float(win / (win + lose)) if win + lose > 0 else None
    return float(d[ks > line].sum())


# ── specs from the store ─────────────────────────────────────────────────────

def auto_runner_rule(season: int, gtype: str | None) -> bool:
    """The automatic runner on second in extra innings: regular season from 2020 (not the postseason)."""
    return int(season) >= 2020 and (gtype or "R") == "R"


WIND_DIRS = {"out to cf": 1.0, "out to lf": 0.8, "out to rf": 0.8, "in from cf": -1.0, "in from lf": -0.8,
             "in from rf": -0.8, "l to r": 0.0, "r to l": 0.0, "calm": 0.0, "varies": 0.0, "none": 0.0}
# Defaults only: the game model fits the three coefficients on earlier seasons (game_inputs.fit_weather), within
# parks. The old fixed values (HR 1.1% per degree F, 1.8% per mph blowing out) moved the simulated totals with the
# weather about 2.5 times as much as the actual totals moved (2016-2017 backtest: 3.9 runs per unit of log HR
# multiplier against 1.6 actual and 1.5 for the closing line).
TEMP_HR = 0.011            # HR odds per degree F above 70 (carry; Nathan-style ~ 1%/F)
TEMP_BIP = 0.0015          # hits-on-contact odds per degree F
WIND_HR = 0.018            # HR odds per mph blowing straight out to centre


def weather_terms(weather: dict | None, roof: str | None = None) -> tuple[float, float] | None:
    """(temperature deviation from 70 F capped at +-40, outward wind in mph capped at 30 x direction); None under a
    closed roof or without a report."""
    if not weather or str(roof or "").lower() in ("dome", "closed", "fixed"):
        return None
    cond = str(weather.get("cond") or "").lower()
    if any(x in cond for x in ("dome", "roof closed")):
        return None
    try:
        t = float(weather.get("temp"))
    except (TypeError, ValueError):
        t = 70.0
    dt = max(-40.0, min(40.0, t - 70.0))
    wind = str(weather.get("wind") or "").lower()
    import re
    mm = re.search(r"(\d+)\s*mph", wind)
    w = 0.0
    if mm:
        mph = min(30.0, float(mm.group(1)))
        dirn = next((v for k, v in WIND_DIRS.items() if k in wind), 0.0)
        w = mph * dirn
    return dt, w


def weather_mult(weather: dict | None, roof: str | None = None, coef: dict | None = None) -> np.ndarray:
    """Odds multipliers from temperature (F) and wind ("12 mph, Out To CF"); neutral under a closed roof.
    coef {"temp_hr", "wind_hr", "temp_bip"} (fitted, game_inputs.fit_weather), else the module defaults."""
    m = np.ones(NE)
    tw = weather_terms(weather, roof)
    if tw is None:
        return m
    dt, w = tw
    c = coef or {}
    t_hr, w_hr, t_bip = c.get("temp_hr", TEMP_HR), c.get("wind_hr", WIND_HR), c.get("temp_bip", TEMP_BIP)
    m[E["HR"]] *= math.exp(t_hr * dt)
    for e in ("1B", "2B", "3B"):
        m[E[e]] *= math.exp(t_bip * dt)
    m[E["HR"]] *= math.exp(w_hr * w)
    m[E["2B"]] *= math.exp(0.25 * w_hr * w)
    m[E["AO"]] *= math.exp(-0.05 * w_hr * w)
    return m


def summary_for_payload(res: dict) -> dict:
    """Drop private arrays; round for a JSON payload."""
    return {k: v for k, v in res.items() if not k.startswith("_")}


# ── committed fits ───────────────────────────────────────────────────────────

TABLE_COLS = ["ev", "bases", "outs", "runs", "bases_post", "outs_post", "bases_start", "outs_start", "score_pre",
              "score_start", "pitches"]


def fit_tables(level: str, seasons: list[int]) -> tuple[Transitions, np.ndarray] | None:
    """(base-out / running tables, pitches per outcome) fitted on the given seasons' regular-season plate
    appearances; None without data. The walk-forward backtest fits them on the two seasons before the one it
    prices (the committed tables, fitted on the latest seasons, would carry later base running, such as the 2023
    rule changes' steals, into earlier seasons)."""
    from oddsmarkets.baseball.models import projections as PJ
    parts = []
    for s in seasons:
        pa = PJ.pa_table(level, s)
        if len(pa):
            pa = pa[pa["game_type"] == "R"] if (pa["game_type"] == "R").any() else pa
            parts.append(pa[TABLE_COLS])
    if not parts:
        return None
    pa = pd.concat(parts, ignore_index=True)
    tr = fit_transitions(pa)
    tr.source = f"fitted on {sorted(seasons)} ({len(pa)} PA)"
    ppe = pa.groupby("ev")["pitches"].mean().reindex(range(NE)).fillna(pd.Series(PITCHES_PER_EVENT)).to_numpy()
    return tr, ppe


def fit_and_save(level: str = "mlb", seasons: list[int] | None = None) -> dict:
    """
    Fit the base-out / running tables and pitches per outcome on recent seasons' plate appearances (regular
    season) and write models/fitted/transitions_<level>.json (used when the cache is empty, e.g. in CI).
    """
    from oddsmarkets.baseball.models import _dio as D
    from oddsmarkets.baseball.models import projections as PJ
    seasons = seasons or D.pitch_seasons(level)[-3:]
    parts = []
    for s in seasons:
        pa = PJ.pa_table(level, s)
        if len(pa):
            pa = pa[pa["game_type"] == "R"] if (pa["game_type"] == "R").any() else pa
            parts.append(pa[["ev", "bases", "outs", "runs", "bases_post", "outs_post", "bases_start", "outs_start",
                             "score_pre", "score_start", "pitches"]])
    if not parts:
        return {"ok": False, "reason": "no plate appearances"}
    pa = pd.concat(parts, ignore_index=True)
    tr = fit_transitions(pa)
    ppe = pa.groupby("ev")["pitches"].mean().reindex(range(NE)).fillna(pd.Series(PITCHES_PER_EVENT)).to_numpy()
    out = tr.to_json() | {"pitches_per_event": [round(float(x), 4) for x in ppe], "seasons": seasons, "n_pa": int(len(pa)),
                          "version": VERSION}
    p = fitted_dir() / f"transitions_{level}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, separators=(",", ":")))
    _TRANS.pop(level, None)
    return {"ok": True, "path": str(p), "n_pa": int(len(pa)), "seasons": seasons}
