"""
Rest-of-season simulation: year-end No. 1, Finals qualification (Race to Turin / Riyadh) and projected
ranking points, by simulating every remaining tour event.

Points
------
* Year-end ranking points = Race points + simulated points still to come + Finals points. The year-end ranking
  (after the Finals, unchanged to Dec 31) counts the 52 weeks back to the week after last season's Finals, i.e.
  this season's events only: every one of last season's events still in today's window drops before then.
  As a check, "official points at the snapshot - drops (last season's events ending after snapshot - 364 days)
  + points since the snapshot + new" is reported per player ("via_snapshot_mean"); it differs from the Race
  route by the best-N rule and by any gap between the official total and the results in the stores.
* Race points = points from this season's finished events (results x points table) + simulated ones,
  Finals excluded.
* Points per event come from _points.table (canon's table when present): by exit round, a first-round
  bye followed by a loss earns first-round points; the Finals pay RR_win per round-robin win, SF_win, F_win.

Events
------
The remaining calendar is this season's events not yet finished (store), completed by last season's
calendar shifted by 52 weeks for events the store does not list yet. Events in progress with a DRAW are
simulated by tournament_sim with their results fixed; without a DRAW the players still alive play out
the remaining rounds in a random bracket and the eliminated keep the points they earned.

Entry model (for events not yet drawn): each of the N_PLAYERS best-ranked players enters with probability
  ENTRY["mandatory"] for Slams and Masters / WTA 1000s (ATP Monte Carlo is not mandatory), scaled down by the
  player's own 12-month participation rate in Slams and 1000s unless he played that event last season (veterans
  exempt from the commitment, injured players); ENTRY["repeat"] for 500s / 250s played last season;
  ENTRY["chase_500"] / ENTRY["chase_250"] for players in Race positions 6-20 (chasing the Finals);
  ENTRY["new_500"] / ENTRY["new_250"] otherwise (halved for the top 10 at 250s); a player who has missed
  INACTIVE["missed_big"] or more Slams / 1000s since his last match (absent, probably injured; return date unknown)
  returns this season with probability INACTIVE["factor"], one draw per simulation: if he returns he keeps his
  normal entries and plays the Finals if he qualifies, if not he plays nothing more (an absent qualifier is
  replaced by the first alternate); no player plays two events in the same week (higher level first). The draw takes entrants by rank (direct acceptances = ACCEPT_SHARE of the draw); remaining
  places go to "field" players (a qualifier-level placeholder; their points are not tracked). Seeds by
  rank (a quarter of the draw), placed in the standard seed positions with random order within each tier
  (1, 2, 3-4, 5-8, 9-16, 17-32); byes to the top seeds; the rest drawn at random.

Matches use the predict() matrix per (surface, best-of) for the tracked players (exact chain, Elo +
serve/return blend), the field placeholder at the median strength of ranks 60-120 against everyone.

Finals: the top 8 of the Race qualify (ATP: a Slam champion of the season ranked 9-20 replaces No. 8);
seeds 1 / 2 head groups A / B, 3-4, 5-6 and 7-8 split at random; round robin, top two to the semi-finals.

Simplifications (marked in the output's "simplifications"):
  * every result counts (no best-19 / best-18 rule, no mandatory zero-pointers);
  * no injuries or withdrawals beyond the entry model's random non-entry; no Finals alternates;
  * group order in the simulated Finals: wins, head to head between two, otherwise random
    (sets % and games % are not simulated here; tournament_sim does them for a drawn Finals);
  * qualifying and Challenger points are not simulated;
  * strengths are held at today's values for the rest of the season (no form drift).
"""
from __future__ import annotations

import logging
import math
import time
from datetime import date, timedelta
from typing import Any, Callable

import numpy as np

from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.models import _points
from oddsmarkets.tennis.models import tournament_sim as TS

logger = logging.getLogger(__name__)

N_SIMS = 10000
N_PLAYERS = 120
ACCEPT_SHARE = 0.8
ENTRY = {"mandatory": 0.92, "repeat": 0.7, "new_500": 0.2, "new_250": 0.08, "chase_500": 0.45, "chase_250": 0.3}
CHASE_POSITIONS = (6, 20)          # Race positions (1-based) of players chasing the last Finals places
INACTIVE = {"missed_big": 2, "factor": 0.5}   # missed >= 2 Slams / 1000s since his last match: absent (injury), entries x 0.5
TOUR_EVENT_LEVELS = ("slam", "m1000", "500", "250")
LEVEL_PRIORITY = {"slam": 5, "finals": 4, "m1000": 3, "500": 2, "250": 1}
NOT_MANDATORY = {"atp": {"monte-carlo", "monte-carlo-masters"}, "wta": set()}
SIMPLIFICATIONS = [
    "every result counts (no best-19 / best-18 rule)",
    "no injuries or withdrawals beyond random non-entry; no Finals alternates",
    "simulated Finals groups ordered by wins, head to head between two, otherwise at random",
    "no qualifying or Challenger points",
    "strengths held at today's values for the rest of the season",
    "injury absences inferred from missed Slams / 1000s since the last match (returns with probability 0.5), not from news",
    "calendar = this season's listed events plus last season's for events not yet listed (shifted 52 weeks, plus the "
    "whole weeks by which this season's calendar has been running late or early)",
]
N_SEEDS = {128: 32, 96: 32, 64: 16, 56: 16, 48: 16, 32: 8, 28: 8, 16: 4}
# The race page's "what is at stake" and clinch lines (race_extras): events starting within NEAR_DAYS of the
# simulation date (and every event in progress) keep their per-simulation points; a chance is conditioned on a
# player's result there only for players whose chance is inside STAKES_BAND, and only on outcomes with at least
# STAKES_MIN_N simulations behind them.
NEAR_DAYS = 10
STAKES_BAND = (0.005, 0.995)
STAKES_MIN_N = 40
STAKES_KEEP = 16
BOUNDS_TOP = 40


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


# ── points from results ──────────────────────────────────────────────────────

def event_points(event: dict, matches: list[dict], tour: str) -> tuple[dict, set, str | None]:
    """
    ({pid: points earned so far}, players still alive, current round) for one event from its results.
    Knockout: exit round (losers), "W" for the champion; RR: RR_win per win, SF_win, F_win.
    """
    lvl = str(event.get("level") or "250")
    yr = int(event.get("year") or str(event.get("start") or "2026")[:4])
    tab = _points.table(tour, lvl, event.get("draw_size"), yr)
    ms = [m for m in matches if m.get("round") not in ("Q1", "Q2", "Q3", "BR")]
    out: dict = {}
    alive: set = set()
    if lvl == "finals" or any(m.get("round") == "RR" for m in ms):
        for m in ms:
            if m.get("status") not in TS.FINISHED or not m.get("winner"):
                for p in (m.get("p1"), m.get("p2")):
                    if p:
                        alive.add(str(p))
                continue
            w = str(m["winner"])
            add = {"RR": tab.get("RR_win", 200.0), "SF": tab.get("SF_win", 400.0), "F": tab.get("F_win", 500.0)}.get(m.get("round"), 0.0)
            out[w] = out.get(w, 0.0) + float(add)
            for p in (m.get("p1"), m.get("p2")):
                out.setdefault(str(p), out.get(str(p), 0.0))
        return out, alive, None
    ko = [m for m in ms if m.get("round") in TS.KO_ROUNDS]
    if not ko:
        return out, alive, None
    order = {r: i for i, r in enumerate(TS.KO_ROUNDS)}
    first_round = min((m["round"] for m in ko), key=lambda r: order[r])
    played: dict = {}
    lost_in: dict = {}
    won_any: dict = {}
    for m in ko:
        for p in (m.get("p1"), m.get("p2")):
            if p:
                played.setdefault(str(p), []).append(m)
        if m.get("status") in TS.FINISHED and m.get("winner"):
            w = str(m["winner"])
            l_ = str(m["p2"] if str(m["p1"]) == w else m["p1"])
            if m.get("status") != "wo":
                won_any[w] = True
            lost_in[l_] = m["round"]
            if m["round"] == "F":
                out[w] = float(tab.get("W", 0.0))
    deepest = None
    for p, lst in played.items():
        if p in lost_in:
            r = lost_in[p]
            first = min((x["round"] for x in lst), key=lambda r: order[r])
            had_bye = order[first] > order[first_round]
            out[p] = float(_points.points_for_exit(tab, r, first_round, had_bye, won_any.get(p, False)))
        elif p not in out:
            alive.add(p)
            rr = max((x["round"] for x in lst), key=lambda r: order[r])
            if deepest is None or order[rr] > order[deepest]:
                deepest = rr
    return out, alive, deepest


# ── draws for future events ──────────────────────────────────────────────────

def std_positions(S: int) -> list[int]:
    """slot index of seed k (1-based list position k-1) in a standard bracket of size S."""
    order = [1]
    while len(order) < S:
        m = 2 * len(order)
        order = [x for o in order for x in (o, m + 1 - o)]
    pos = [0] * S
    for slot, seed in enumerate(order):
        pos[seed - 1] = slot
    return pos


def seeded_brackets(order: np.ndarray, draw_size: int, rng: np.random.Generator) -> np.ndarray:
    """
    order (n, D): players by rank (best first) for each simulation (-1 = empty) -> leaves (n, S) with
    standard seed positions (random within tiers), byes to the top seeds, unseeded at random.
    """
    n, D = order.shape
    S = TS._pow2(D)
    ns = min(N_SEEDS.get(D, max(2, D // 4)), D)
    byes = S - D
    pos = np.array(std_positions(S))
    leaves = np.full((n, S), -1, int)
    rows = np.arange(n)[:, None]
    tiers, k = [], 0
    for size in (1, 1, 2, 4, 8, 16, 32, 64):
        if k >= ns:
            break
        tiers.append(list(range(k, min(k + size, ns))))
        k += size
    slot_of = np.zeros((n, D), int)
    for t in tiers:
        tpos = pos[t]
        perm = np.argsort(rng.random((n, len(t))), axis=1)
        slot_of[:, t] = tpos[perm]
    bye_slots = set((pos[:byes] ^ 1).tolist())
    used = set(pos[:ns].tolist()) | bye_slots
    free = np.array([s for s in range(S) if s not in used])
    if D - ns > 0:
        perm = np.argsort(rng.random((n, len(free))), axis=1)
        slot_of[:, ns:] = free[perm][:, :D - ns]
    leaves[rows, slot_of] = order
    return leaves


# ── state ────────────────────────────────────────────────────────────────────

def _week(d: date) -> tuple:
    iso = d.isocalendar()
    return iso[0], iso[1]


def simulate_season(state: dict, n: int = N_SIMS, seed: int = 0) -> dict:
    """
    Pure core. state:
      "tour", "players" [pid] (rank order), "rank_pts" {pid}, "race_pts" {pid}, "drops" {pid},
      "earned_since_snapshot" {pid}, "use_snapshot" bool,
      "events" [{"id","tid","level","draw_size","surface","best_of","start","entry": {pid: p} | None,
                 "points": table, "fixed_sims": {"pids": [...], "points": (n, P) array} | None,
                 "alive": [pid] | None, "alive_round": str | None, "earned": {pid: pts} | None}],
      "logit": callable (surface, best_of) -> (P+1, P+1) logit matrix (last row/col = field),
      "slam_winners" [pid], "finals": {"points": table, "surface", "best_of"} | None, "as_of".
    """
    t0 = time.perf_counter()
    tour = _io.tour_key(state.get("tour"))
    pids = list(state["players"])
    P = len(pids)
    F = P
    idx = {p: i for i, p in enumerate(pids)}
    rng = np.random.default_rng(seed)
    rank_now = np.array([float(state.get("rank_pts", {}).get(p, 0.0)) for p in pids])
    race_now = np.array([float(state.get("race_pts", {}).get(p, 0.0)) for p in pids])
    drops = np.array([float(state.get("drops", {}).get(p, 0.0)) for p in pids])
    since = np.array([float(state.get("earned_since_snapshot", {}).get(p, 0.0)) for p in pids])
    new_pts = np.zeros((n, P))
    rows = np.arange(n)[:, None]
    busy: dict = {}
    events = sorted(state.get("events") or [], key=lambda e: (str(e.get("start")), -LEVEL_PRIORITY.get(str(e.get("level")), 0)))
    ev_log = []
    mats: dict = {}
    as_of_d = _io.day(state.get("as_of"))
    near_until = (as_of_d + timedelta(days=NEAR_DAYS)) if as_of_d else None
    tracked: list = []           # near-term and in-progress events: per-simulation points and who was in the draw
    ip_lo = np.zeros(P)          # points already certain from events in progress
    ip_hi = np.zeros(P)          # the most each player can still reach in them
    ip_w = [0.0]                 # sum of the winners' points of the events in progress (the outsider bound)
    week_w: dict = {}            # future events: the biggest winner's points in each week (one event a week)

    def winner_pts(tab):
        try:
            return float(tab.get("W") or max(float(v) for v in tab.values()))
        except (TypeError, ValueError):
            return 0.0

    def track(ev, ev_pts, entered, in_progress, tab):
        if in_progress:
            w = winner_pts(tab)
            ip_w[0] += w
            lo, hi = ev_pts.min(0), ev_pts.max(0)
            ip_lo[:] += lo
            ip_hi[:] += np.where(hi > lo, np.maximum(hi, w), hi)
        else:
            try:
                wk = _week(_io.day(ev.get("start")))
            except Exception:  # noqa: BLE001
                wk = ("?", ev.get("id"))
            week_w[wk] = max(week_w.get(wk, 0.0), winner_pts(tab))
        d0 = _io.day(ev.get("start"))
        if in_progress or (near_until is not None and d0 is not None and d0 <= near_until):
            tracked.append({"id": ev.get("id"), "start": ev.get("start"), "level": ev.get("level"), "in_progress": in_progress,
                            "pts": ev_pts.astype(np.float32), "entered": entered})

    def L_for(surface, bo):
        key = (surface or "hard", 5 if int(bo or 3) == 5 else 3)
        if key not in mats:
            mats[key] = np.asarray(state["logit"](*key), float)
        return mats[key]

    # absent players (probably injured): one draw per simulation decides whether he returns this season; if he
    # does he keeps his normal entries (and plays the Finals if he qualifies), if not he plays nothing more
    returns = np.ones((n, P), bool)
    for p in (state.get("absent") or {}):
        if p in idx:
            returns[:, idx[p]] = rng.random(n) < INACTIVE["factor"]
    for ev in events:
        lvl = str(ev.get("level") or "250")
        tab = ev.get("points") or _points.table(tour, lvl, ev.get("draw_size"))
        if ev.get("fixed_sims") is not None:
            fs = ev["fixed_sims"]
            ev_pts = np.zeros((n, P))
            ent = np.zeros(P, bool)
            for j, p in enumerate(fs["pids"]):
                if p in idx:
                    ev_pts[:, idx[p]] += fs["points"][:n, j]
                    ent[idx[p]] = True
            new_pts += ev_pts
            track(ev, ev_pts, np.broadcast_to(ent, (n, P)), True, tab)
            ev_log.append({"id": ev.get("id"), "start": ev.get("start"), "method": "tournament_sim (drawn, results fixed)"})
            continue
        L = L_for(ev.get("surface"), ev.get("best_of"))
        if ev.get("alive") is not None:
            # in progress without a draw: earned points fixed, the alive play out the remaining rounds
            ev_pts = np.zeros((n, P))
            ent = np.zeros(P, bool)
            for p, v in (ev.get("earned") or {}).items():
                if p in idx and p not in set(ev["alive"]):
                    ev_pts[:, idx[p]] += float(v)
                    ent[idx[p]] = True
            alive = [p for p in ev["alive"] if p in idx]
            k = len(ev["alive"])
            if k >= 2:
                S = TS._pow2(k)
                rnames = _points.round_names(S)
                cur = ev.get("alive_round") or rnames[0]
                lab = list(_points.ROUNDS)
                leaves0 = np.array([idx[p] if p in idx else F for p in ev["alive"]] + [-1] * (S - k))
                perm = np.argsort(rng.random((n, S)), axis=1)
                leaves = leaves0[perm]
                occ = TS.knockout(L, leaves, {}, n, rng)
                # map positions: the alive are in round `cur`; exits after that
                start_i = lab.index(cur) if cur in lab else 0
                names = lab[start_i:] + ["W"]
                pres = _presence(occ, n, P + 1)
                ex = pres.sum(0) - 1
                vals = np.array([float(tab.get(nm, 0.0)) for nm in names[:len(occ)]])
                for p in alive:
                    i = idx[p]
                    e = ex[:, i]
                    ev_pts[:, i] += np.where(e >= 0, vals[np.clip(e, 0, len(vals) - 1)], 0.0)
                    ent[i] = True
            new_pts += ev_pts
            track(ev, ev_pts, np.broadcast_to(ent, (n, P)), True, tab)
            ev_log.append({"id": ev.get("id"), "start": ev.get("start"), "method": "in progress, alive players re-drawn"})
            continue
        # a future event: entries, draw, results
        D = int(ev.get("draw_size") or 32)
        entry = ev.get("entry") or {}
        pe = np.array([float(entry.get(p, 0.0)) for p in pids])
        E = (rng.random((n, P)) < pe[None, :]) & returns
        try:
            wk = _week(_io.day(ev.get("start")))
        except Exception:  # noqa: BLE001
            wk = None
        if wk is not None:
            b = busy.get(wk)
            if b is not None:
                E &= ~b
            busy[wk] = (busy.get(wk, np.zeros((n, P), bool))) | E
        K = min(D, int(round(D * float(ev.get("accept", ACCEPT_SHARE)))))
        key = np.where(E, np.arange(P)[None, :], P + 10)            # rank order = index order
        ordr = np.sort(key, axis=1)[:, :K]
        ordr = np.where(ordr >= P, F, ordr)
        order = np.concatenate([ordr, np.full((n, D - K), F)], axis=1) if D > K else ordr[:, :D]
        leaves = seeded_brackets(order, D, rng)
        occ = TS.knockout(L, leaves, {}, n, rng)
        pres = _presence(occ, n, P + 1)
        ex = pres.sum(0) - 1                                         # (n, P+1)
        rnames = _points.round_names(leaves.shape[1]) + ["W"]
        vals = np.array([float(tab.get(nm, 0.0)) for nm in rnames])
        pts = np.where(ex >= 0, vals[np.clip(ex, 0, len(vals) - 1)], 0.0)[:, :P]
        # bye then loss: first-round points
        partner = leaves.reshape(n, -1, 2)
        had_bye = np.zeros((n, P + 2), bool)
        for side in (0, 1):
            me, other = partner[:, :, side], partner[:, :, 1 - side]
            m = (other < 0) & (me >= 0)
            rr_, cc_ = np.nonzero(m)
            had_bye[rr_, me[rr_, cc_]] = True
        hb = had_bye[:, :P] & (ex[:, :P] == 1)
        pts = np.where(hb, vals[0], pts)
        new_pts += pts
        track(ev, pts, E.copy(), False, tab)
        ev_log.append({"id": ev.get("id"), "start": ev.get("start"), "method": "entry model + seeded draw", "draw_size": D,
                       "p_enter_top10": round(float(E[:, :10].mean()), 3)})
    # Race and qualification
    race = race_now[None, :] + new_pts
    q_mask = np.zeros((n, P), bool)
    finals_pts = np.zeros((n, P))
    finals_title = np.zeros(P)
    noise = rng.random((n, P)) * 1e-6
    order = np.argsort(-(race + noise), axis=1)
    top8 = order[:, :8].copy()
    if tour == "atp":
        sw = [idx[p] for p in (state.get("slam_winners") or []) if p in idx]
        if sw:
            rank_pos = np.argsort(order, axis=1)                    # position of each player in the race
            for s in range(n):
                cands = [i for i in sw if 8 <= rank_pos[s, i] < 20]
                if cands:
                    best = min(cands, key=lambda i: rank_pos[s, i])
                    top8[s, 7] = best
    q_mask[rows, top8] = True
    fin = state.get("finals")
    if fin:
        L = L_for(fin.get("surface", "hard"), fin.get("best_of", 3))
        ftab = fin.get("points") or _points.table(tour, "finals")
        # an absent qualifier who did not return is replaced by the next player in the Race (the first alternate)
        field = top8.copy()
        abs_ix = [idx[p] for p in (state.get("absent") or {}) if p in idx]
        if abs_ix:
            nxt_alt = np.full(n, 8)
            for k in abs_ix:
                hit = (field == k).any(1) & ~returns[:, k]
                for s_ in np.nonzero(hit)[0]:
                    col = int(np.nonzero(field[s_] == k)[0][0])
                    while nxt_alt[s_] < P and order[s_, nxt_alt[s_]] in field[s_]:
                        nxt_alt[s_] += 1
                    if nxt_alt[s_] < P:
                        field[s_, col] = order[s_, nxt_alt[s_]]
                        nxt_alt[s_] += 1
            # keep the race order within the field for seeding
            pos = np.argsort(order, axis=1)
            field = np.take_along_axis(field, np.argsort(pos[rows, field], axis=1), axis=1)
        finals_pts, champs = _finals(field, L, ftab, rng)
        finals_title = np.bincount(champs, minlength=P)[:P] / n
    # The year-end ranking (published after the Finals, unchanged to Dec 31) counts the 52 weeks back to the week
    # after last season's Finals: this season's events only. So year-end points = Race points + Finals points.
    # (The snapshot route "official points - drops + new" is kept as a diagnostic: it inherits the best-N rule and
    # any gap between the official total and our results, which put Sinner 500 points short in Oct 2026.)
    year_end = race + finals_pts
    via_snapshot = rank_now[None, :] - drops[None, :] + since[None, :] + new_pts + finals_pts
    ye_order = np.argsort(-(year_end + noise), axis=1)
    ranks = np.empty((n, P), int)
    ranks[np.arange(n)[:, None], ye_order] = np.arange(1, P + 1)[None, :]
    no1 = ye_order[:, 0]
    p_no1 = np.bincount(no1, minlength=P) / n
    out_no1 = {pids[i]: round(float(p_no1[i]), 5) for i in np.argsort(-p_no1) if p_no1[i] > 0}
    qual = q_mask.mean(0)
    out_q = {pids[i]: round(float(qual[i]), 5) for i in np.argsort(-qual) if qual[i] > 0}
    rank_dist = {}
    points = {}
    race_out = {}
    for i, p in enumerate(pids[:60]):
        h = np.bincount(np.minimum(ranks[:, i], 21) - 1, minlength=21)[:21] / n
        rank_dist[p] = [round(float(x), 5) for x in h]
    for i, p in enumerate(pids):
        ye = year_end[:, i]
        points[p] = {"mean": round(float(ye.mean()), 1), "p05": round(float(np.percentile(ye, 5)), 1),
                     "p95": round(float(np.percentile(ye, 95)), 1), "now": round(float(race_now[i]), 1),
                     "ranking_now": round(float(rank_now[i]), 1), "drops": round(float(drops[i]), 1),
                     "added_mean": round(float(new_pts[:, i].mean()), 1), "finals_mean": round(float(finals_pts[:, i].mean()), 1),
                     "via_snapshot_mean": round(float(via_snapshot[:, i].mean()), 1) if state.get("use_snapshot") else None}
        rc = race[:, i]
        race_out[p] = {"now": round(float(race_now[i]), 1), "mean": round(float(rc.mean()), 1),
                       "p05": round(float(np.percentile(rc, 5)), 1), "p95": round(float(np.percentile(rc, 95)), 1)}
    extras = race_extras(tour, pids, race_now, ip_lo, ip_hi, ip_w[0], sum(week_w.values()), rank_now,
                         [idx[p] for p in (state.get("slam_winners") or []) if p in idx], q_mask, no1, qual, p_no1, tracked)
    return {"ok": True, "tour": tour, "as_of": str(state.get("as_of")), "n_sims": n, **extras,
            "year_end_no1": out_no1, "finals_qual": out_q, "rank_dist": rank_dist, "rank_dist_labels": list(range(1, 21)) + ["21+"],
            "points": points, "race": race_out,
            "finals_title": {pids[i]: round(float(finals_title[i]), 5) for i in np.argsort(-finals_title) if finals_title[i] > 0},
            "events": ev_log, "simplifications": SIMPLIFICATIONS, "runtime_s": round(time.perf_counter() - t0, 2)}


def race_extras(tour: str, pids: list, race_now: np.ndarray, ip_lo: np.ndarray, ip_hi: np.ndarray, ip_w: float,
                future_max: float, rank_now: np.ndarray, slam_ix: list, q_mask: np.ndarray, no1: np.ndarray,
                qual: np.ndarray, p_no1: np.ndarray, tracked: list) -> dict:
    """The race page's clinch lines and "what is at stake", from the simulation's own arrays.

    "bounds" {pid: [lowest, highest]}: Race points certain now (finished events plus what the events in progress
      have already paid) and the most still reachable (winning every event in progress the player is still in, then
      one event a week on the remaining calendar at that week's biggest winner's points). Finals points do not count
      towards the Race. For the top BOUNDS_TOP of the Race.
    "status" {pid: "in" | "out"}: mathematically certain, never from the simulation's share. "in": fewer than eight
      players (ATP: seven, unless every other Slam champion of the season is sure to finish ahead, because a Slam
      champion ranked 9th-20th takes the eighth place) can still reach the player's certain total, ties counted
      against; "out": eight or more are sure to finish ahead (twenty for an ATP Slam champion). Players outside the
      simulation's tracked list are bounded by the lowest tracked ranking (or Race) total plus everything left.
    "stakes" [{"metric", "pid", "event", "in_progress", "p", "p_enter", "p_win", "if_win", "if_lose", "if_title",
      "if_skip", "levels"}]: a chance (Finals qualification, year-end No. 1) conditioned on the player's result at an
      event in progress or starting within NEAR_DAYS, in the same simulations. "if_lose" = out in the next (or
      first) match, "if_win" = wins it, "if_title" = wins the event, "if_skip" = does not enter (future events
      only), "p_win" = share of the player's simulations there that win that match, "levels" [[Race points from the
      event, share of the simulations where the player plays it, chance]] by result. Kept: the STAKES_KEEP biggest
      swings (if_win - if_lose) per metric, players whose chance is inside STAKES_BAND only.
    "left" {"future_max", "in_progress_max", "near": [event ids]}."""
    P = len(pids)
    lower = race_now + ip_lo
    upper = race_now + ip_hi + future_max
    tracked_pts = rank_now[rank_now > 0]
    base = max(float(tracked_pts.min()) if tracked_pts.size else 0.0, float(race_now.min()) if P else 0.0)
    outsider = base + ip_w + future_max
    order = [int(i) for i in np.argsort(-lower, kind="stable") if race_now[i] > 0 or lower[i] > 0][:BOUNDS_TOP]
    bounds, status = {}, {}
    atp = tour == "atp"
    for i in order:
        others = np.arange(P) != i
        can_pass = int(((upper >= lower[i]) & others).sum()) + (99 if outsider >= lower[i] else 0)
        sure_ahead = int(((lower > upper[i]) & others).sum())
        is_sw = i in slam_ix
        if atp and not is_sw:
            safe = can_pass <= 6 or (can_pass <= 7 and all(lower[s] > upper[i] for s in slam_ix if s != i))
        else:
            safe = can_pass <= 7
        out = sure_ahead >= (20 if (atp and is_sw) else 8)
        bounds[pids[i]] = [round(float(lower[i]), 1), round(float(upper[i]), 1)]
        if safe:
            status[pids[i]] = "in"
        elif out:
            status[pids[i]] = "out"
    stakes = []
    n = q_mask.shape[0]
    for metric, ind_of, share in (("finals_qual", lambda i: q_mask[:, i], qual), ("year_end_no1", lambda i: no1 == i, p_no1)):
        rows = []
        for i in range(P):
            p = float(share[i])
            if not (STAKES_BAND[0] < p < STAKES_BAND[1]):
                continue
            ind = ind_of(i)
            for ev in tracked:
                ent = np.asarray(ev["entered"][:, i], bool)
                ne = int(ent.sum())
                if ne < STAKES_MIN_N or ne < 0.05 * n:
                    continue
                v = ev["pts"][:, i]
                levels = np.unique(v[ent])
                if levels.size < 2:
                    continue
                lo = levels.min()
                lose, win = ent & (v == lo), ent & (v > lo)
                if lose.sum() < STAKES_MIN_N or win.sum() < STAKES_MIN_N:
                    continue
                lv = []
                for x in levels:
                    m = ent & (v == x)
                    if m.sum() >= STAKES_MIN_N:
                        lv.append([round(float(x), 1), round(float(m.sum() / ne), 4), round(float(ind[m].mean()), 4)])
                top = ent & (v == levels.max())
                skip = ~ent
                rows.append({"metric": metric, "pid": pids[i], "event": ev["id"], "in_progress": bool(ev["in_progress"]),
                             "p": round(p, 4), "p_enter": round(ne / n, 4), "p_win": round(float(win.sum() / ne), 4),
                             "if_win": round(float(ind[win].mean()), 4), "if_lose": round(float(ind[lose].mean()), 4),
                             "if_title": round(float(ind[top].mean()), 4) if top.sum() >= STAKES_MIN_N else None,
                             "if_skip": round(float(ind[skip].mean()), 4) if skip.sum() >= STAKES_MIN_N else None,
                             "levels": lv})
        rows.sort(key=lambda r: -(r["if_win"] - r["if_lose"]))
        stakes += rows[:STAKES_KEEP]
    return {"bounds": bounds, "status": status, "stakes": stakes,
            "left": {"future_max": round(float(future_max), 1), "in_progress_max": round(float(ip_w), 1),
                     "near": [ev["id"] for ev in tracked]}}


def _presence(occ: list[np.ndarray], n: int, width: int) -> np.ndarray:
    """(rounds, n, width) bool: player present in each round's occupancy."""
    out = np.zeros((len(occ), n, width), bool)
    for r, o in enumerate(occ):
        rr_, cc_ = np.nonzero(o >= 0)
        out[r, rr_, o[rr_, cc_]] = True
    return out


def _finals(top8: np.ndarray, L: np.ndarray, tab: dict, rng) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised Finals: top8 (n, 8) race order -> (points (n, P), champion (n,))."""
    n = top8.shape[0]
    P = L.shape[0] - 1
    rows = np.arange(n)
    # groups: 1 -> A, 2 -> B, then each pair (3,4), (5,6), (7,8) split at random
    A = [top8[:, 0]]
    B = [top8[:, 1]]
    for k in (2, 4, 6):
        flip = rng.random(n) < 0.5
        A.append(np.where(flip, top8[:, k], top8[:, k + 1]))
        B.append(np.where(flip, top8[:, k + 1], top8[:, k]))
    pts = np.zeros((n, P + 1))
    firsts, seconds = [], []
    for G in (np.stack(A, 1), np.stack(B, 1)):
        wins = np.zeros((n, 4))
        h2h = np.zeros((n, 4, 4))
        for x in range(4):
            for y in range(x + 1, 4):
                a, b = G[:, x], G[:, y]
                w = rng.random(n) < _sig(L[a, b])
                wins[:, x] += w
                wins[:, y] += ~w
                h2h[:, x, y] = w
                h2h[:, y, x] = ~w
        tied = (wins[:, :, None] == wins[:, None, :])
        bonus = (h2h * tied).sum(2)
        key = wins * 10 + bonus + rng.random((n, 4)) * 0.01
        o = np.argsort(-key, axis=1)
        firsts.append(G[rows, o[:, 0]])
        seconds.append(G[rows, o[:, 1]])
        for x in range(4):
            np.add.at(pts, (rows, G[:, x]), wins[:, x] * float(tab.get("RR_win", 200.0)))

    def play(a, b):
        return np.where(rng.random(n) < _sig(L[a, b]), a, b)
    f1 = play(firsts[0], seconds[1])
    f2 = play(firsts[1], seconds[0])
    ch = play(f1, f2)
    np.add.at(pts, (rows, f1), float(tab.get("SF_win", 400.0)))
    np.add.at(pts, (rows, f2), float(tab.get("SF_win", 400.0)))
    np.add.at(pts, (rows, ch), float(tab.get("F_win", 500.0)))
    return pts[:, :P], ch


# ── building the state from the stores ──────────────────────────────────────

def _field_logit(Lr: np.ndarray, lo: int = 60, hi: int = 120) -> np.ndarray:
    P = Lr.shape[0]
    a, b = min(lo, max(P - 2, 0)), min(hi, P)
    cols = list(range(a, b)) or list(range(P))
    L = np.zeros((P + 1, P + 1))
    L[:P, :P] = Lr
    fv = np.median(Lr[:, cols], axis=1)
    L[:P, P] = fv
    L[P, :P] = -fv
    return L


def calendar_drift(ev_cur: dict, ev_prev: dict, d: date, last: int = 6) -> int:
    """Days by which this season's calendar runs from last season's shifted 52 weeks: the median, over the last
    `last` tour events of this season that have started by `d` and were also played last season, of (start - (last
    season's start + 364)), rounded to whole weeks and capped at two. 2026 runs a week later than 2025 + 364 from
    the summer on, so without it Basel and Vienna were simulated in Almaty's and Brussels' week and collided with
    Paris (one event a week per player)."""
    prev = {}
    for eid, ev in ev_prev.items():
        st = _io.day(ev.get("start"))
        if str(ev.get("level") or "") in TOUR_EVENT_LEVELS and st is not None:
            prev[str(ev.get("tid") or eid.rsplit("-", 1)[0])] = st
    offs = []
    for eid, ev in ev_cur.items():
        st = _io.day(ev.get("start"))
        p = prev.get(str(ev.get("tid") or eid.rsplit("-", 1)[0]))
        if str(ev.get("level") or "") in TOUR_EVENT_LEVELS and st is not None and p is not None and st <= d:
            offs.append((st, (st - p).days - 364))
    recent = [o for _, o in sorted(offs)[-last:]]
    if not recent:
        return 0
    return int(max(-14, min(14, 7 * round(float(np.median(recent)) / 7))))


def build_state(tour: str, as_of: Any = None, stores: dict | None = None, ctx=None, n_players: int = N_PLAYERS,
                prob: Callable | None = None, n: int = N_SIMS, seed: int = 0) -> dict:
    """State for simulate_season from the stores (this season and last). `stores` {year: store} bypasses disk;
    `prob(pids, surface, best_of) -> P` overrides predict."""
    t = _io.tour_key(tour)
    d = _io.day(as_of) or date.today()
    Y = d.year
    stores = stores or {}
    cur = stores.get(Y) or _io.load_store(t, Y) or {}
    prev = stores.get(Y - 1) or _io.load_store(t, Y - 1) or {}
    rk = (cur.get("rankings") or {})
    rows_ = rk.get("rows") or []
    snap = _io.day(rk.get("date"))
    # the snapshot route needs last season's results for the drops; without them the year-end points are the Race
    use_snap = bool(rows_) and snap is not None and bool(prev.get("events"))
    ev_cur, ev_prev = cur.get("events") or {}, prev.get("events") or {}
    m_cur = [m for m in (cur.get("matches") or {}).values() if isinstance(m, dict)]
    m_prev = [m for m in (prev.get("matches") or {}).values() if isinstance(m, dict)]

    def by_event(ms):
        out: dict = {}
        for m in ms:
            out.setdefault(m.get("event"), []).append(m)
        return out
    bc, bp = by_event(m_cur), by_event(m_prev)
    # points earned this season (race) and since the snapshot
    race: dict = {}
    since: dict = {}
    slam_w = []
    in_progress = []
    for eid, ev in ev_cur.items():
        lvl = str(ev.get("level") or "")
        if lvl not in TOUR_EVENT_LEVELS + ("finals",):
            continue
        st = _io.day(ev.get("start"))
        if st is None or st > d:
            continue
        ept, alive, rnd = event_points(ev, bc.get(eid, []), t)
        end = _io.day(ev.get("end")) or (st + timedelta(days=13))
        finished = ev.get("status") == "done" or (not alive and end <= d)
        if not finished:
            in_progress.append((eid, ev, ept, alive, rnd))
            continue
        if lvl == "slam" and ev.get("champion"):
            slam_w.append(str(ev["champion"]))
        for p, v in ept.items():
            if lvl != "finals":
                race[p] = race.get(p, 0.0) + v
            if use_snap and end > snap:
                since[p] = since.get(p, 0.0) + v
    # drops: last season's events still in the window
    drops: dict = {}
    drop_events: dict = {}
    if use_snap:
        for eid, ev in ev_prev.items():
            if str(ev.get("level") or "") not in TOUR_EVENT_LEVELS + ("finals",):
                continue
            end = _io.day(ev.get("end")) or _io.day(ev.get("start"))
            if end is None or end <= snap - timedelta(days=364):
                continue
            ept, _, _ = event_points(ev, bp.get(eid, []), t)
            for p, v in ept.items():
                drops[p] = drops.get(p, 0.0) + v
                if v:
                    drop_events.setdefault(p, []).append([eid, end.isoformat(), v])
    # tracked players: ranking order, else race order
    if use_snap:
        order = [str(r[1]) for r in sorted(rows_, key=lambda r: int(r[0]))]
        rank_pts = {str(r[1]): float(r[2] or 0.0) for r in rows_}
    else:
        order = [p for p, _ in sorted(race.items(), key=lambda kv: -kv[1])]
        rank_pts = {}
    players = order[:n_players]
    for p in slam_w:
        if p not in players:
            players.append(p)
    # entry model inputs
    played_prev: dict = {}
    for eid, ev in ev_prev.items():
        for m in bp.get(eid, []):
            for p in (m.get("p1"), m.get("p2")):
                if p:
                    played_prev.setdefault(str(ev.get("tid") or eid.rsplit("-", 1)[0]), set()).add(str(p))
    events = []
    listed = set()
    for eid, ev in ev_cur.items():
        lvl = str(ev.get("level") or "")
        if lvl not in TOUR_EVENT_LEVELS:
            continue
        listed.add(str(ev.get("tid") or eid.rsplit("-", 1)[0]))
    future = []
    for eid, ev in ev_cur.items():
        st = _io.day(ev.get("start"))
        if str(ev.get("level") or "") in TOUR_EVENT_LEVELS and st is not None and st > d and ev.get("status") != "done":
            future.append(dict(ev, id=eid))
    shift = timedelta(days=364 + calendar_drift(ev_cur, ev_prev, d))
    for eid, ev in ev_prev.items():
        tid = str(ev.get("tid") or eid.rsplit("-", 1)[0])
        st = _io.day(ev.get("start"))
        if str(ev.get("level") or "") in TOUR_EVENT_LEVELS and st is not None and tid not in listed:
            st2 = st + shift
            en2 = (_io.day(ev.get("end")) or (st + timedelta(days=6))) + shift
            # not listed yet and not over by last season's dates: still to come (calendars move by a few days);
            # one that should have started more than three days ago (after the drift) would be listed by now:
            # dropped from this season's calendar (Stockholm 2026, Lyon's week)
            if en2 > d and st2 <= date(Y, 12, 31) and st2 >= d - timedelta(days=3):
                st2 = max(st2, d + timedelta(days=1))
                future.append(dict(ev, id=f"{tid}-{Y}", start=st2.isoformat(), year=Y, status="upcoming", draw=None,
                                   shifted_from=eid))
    rank_index = {p: i for i, p in enumerate(players)}
    # participation in the big events over the last 12 months (veterans exempt from the commitment skip them)
    big_prev = [str(ev.get("tid") or eid.rsplit("-", 1)[0]) for eid, ev in ev_prev.items()
                if str(ev.get("level")) in ("slam", "m1000") and (_io.day(ev.get("start")) or date(Y - 1, 1, 1)) > d - timedelta(days=365)]
    big_cur = [str(ev.get("tid") or eid.rsplit("-", 1)[0]) for eid, ev in ev_cur.items()
               if str(ev.get("level")) in ("slam", "m1000") and (_io.day(ev.get("start")) or d) <= d]
    played_cur: dict = {}
    for eid, ev in ev_cur.items():
        for m in bc.get(eid, []):
            for p in (m.get("p1"), m.get("p2")):
                if p:
                    played_cur.setdefault(str(ev.get("tid") or eid.rsplit("-", 1)[0]), set()).add(str(p))
    n_big = max(len(big_prev) + len(big_cur), 1)

    def big_rate(p):
        k = sum(p in played_prev.get(x, set()) for x in big_prev) + sum(p in played_cur.get(x, set()) for x in big_cur)
        return k / n_big
    # current absence: a player who has missed Slams / 1000s since his last match is probably injured
    last_played: dict = {}
    for m in m_cur + m_prev:
        dd_ = _io.day(m.get("date"))
        if dd_ is None or dd_ > d or m.get("status") not in ("done", "ret", "def"):
            continue
        for p in (m.get("p1"), m.get("p2")):
            if p and (p not in last_played or dd_ > last_played[p]):
                last_played[str(p)] = dd_
    big_starts = sorted(_io.day(ev.get("start")) for ev in list(ev_cur.values()) + list(ev_prev.values())
                        if str(ev.get("level")) in ("slam", "m1000") and _io.day(ev.get("start")) and _io.day(ev.get("start")) <= d)
    absent: dict = {}
    for p in players:
        lp = last_played.get(p)
        missed = sum(1 for x in big_starts if lp is not None and x > lp + timedelta(days=3))
        if lp is not None and missed >= INACTIVE["missed_big"]:
            absent[p] = {"last_match": lp.isoformat(), "missed_big": missed}
    race_order = [p for p, _ in sorted(race.items(), key=lambda kv: -kv[1])]
    race_pos = {p: i + 1 for i, p in enumerate(race_order)}
    for ev in future:
        tid = str(ev.get("tid") or ev["id"].rsplit("-", 1)[0])
        lvl = str(ev.get("level"))
        mand = lvl == "slam" or (lvl == "m1000" and tid not in NOT_MANDATORY[t])
        prevp = played_prev.get(tid, set())
        entry = {}
        for p in players:
            chasing = CHASE_POSITIONS[0] <= race_pos.get(p, 999) <= CHASE_POSITIONS[1]
            if mand:
                # committed players play them; a player who skips big events (veteran exemption, injury) is
                # scaled by his own 12-month participation rate unless he played this event last season
                pe = ENTRY["mandatory"] * (1.0 if p in prevp else min(1.0, big_rate(p) / 0.8))
            elif p in prevp:
                pe = ENTRY["repeat"]
            elif chasing:
                pe = ENTRY["chase_500"] if lvl == "500" else ENTRY["chase_250"]
            else:
                pe = ENTRY["new_500"] if lvl == "500" else ENTRY["new_250"]
                if lvl == "250" and rank_index[p] < 10:
                    pe *= 0.5
            entry[p] = round(float(pe), 4)
        events.append({"id": ev["id"], "tid": tid, "level": lvl, "draw_size": int(ev.get("draw_size") or 32),
                       "surface": _io.fold_surface(ev.get("surface")), "best_of": int(ev.get("best_of") or 3),
                       "start": ev.get("start"), "entry": entry,
                       "points": _points.table(t, lvl, ev.get("draw_size"), Y)})
    # pricing
    from oddsmarkets.tennis.models import predict as Pr
    c = None

    def logit(surface, bo):
        nonlocal c
        if prob is not None:
            Pm = np.asarray(prob(players, surface, bo), float)
        else:
            c = c or ctx or Pr.context(t, d)
            Pm = Pr.prob_matrix(c, players, surface, bo, "500", "tb7")
        Lr = np.log(np.clip(Pm, 1e-6, 1 - 1e-6) / np.clip(1 - Pm, 1e-6, 1))
        np.fill_diagonal(Lr, 0.0)
        return _field_logit(Lr)
    # events in progress
    for eid, ev, ept, alive, rnd in in_progress:
        lvl = str(ev.get("level") or "250")
        if lvl == "finals":
            continue
        if ev.get("draw"):
            surf, bo = _io.fold_surface(ev.get("surface")), int(ev.get("best_of") or 3)
            prob_e = (lambda ps, surf=surf, bo=bo: np.asarray(prob(ps, surf, bo), float)) if prob is not None else None
            res = TS.simulate(dict(ev, id=eid), n=n, matches=bc.get(eid, []), tour=t, prob=prob_e,
                              ctx=ctx, seed=seed + 7, keep_sims=True, conditional=False)
            if res.get("ok"):
                events.append({"id": eid, "level": lvl, "start": ev.get("start"),
                               "fixed_sims": {"pids": res["_pids"], "points": res["_points"]}})
                continue
        events.append({"id": eid, "level": lvl, "start": ev.get("start"), "surface": _io.fold_surface(ev.get("surface")),
                       "best_of": int(ev.get("best_of") or 3), "alive": sorted(alive), "alive_round": rnd, "earned": ept,
                       "points": _points.table(t, lvl, ev.get("draw_size"), Y)})
    finals_done = any(str(ev.get("level")) == "finals" and ev.get("status") == "done" for ev in ev_cur.values())
    return {"tour": t, "as_of": d.isoformat(), "players": players, "rank_pts": rank_pts, "race_pts": race,
            "drops": drops, "earned_since_snapshot": since, "use_snapshot": use_snap, "events": events,
            "logit": logit, "slam_winners": slam_w,
            "finals": None if finals_done else {"points": _points.table(t, "finals"), "surface": "hard", "best_of": 3},
            "snapshot": snap.isoformat() if snap else None,
            "drop_events": drop_events, "absent": absent,
            "basis": "race + new + Finals (year-end window = this season); snapshot - drops kept as a check"}


def for_tour(tour: str, as_of: Any = None, n: int = N_SIMS, seed: int = 0, **kw) -> dict:
    """Build the state from the stores and simulate; {"ok": False, "reason"} when it cannot."""
    try:
        st = build_state(tour, as_of, n=n, seed=seed, **kw)
        if len(st["players"]) < 8:
            return {"ok": False, "reason": "fewer than eight ranked players in the store"}
        out = simulate_season(st, n=n, seed=seed)
        out["snapshot"] = st.get("snapshot")
        out["basis"] = st.get("basis")
        return out
    except Exception as exc:  # noqa: BLE001
        logger.exception("season simulation failed")
        return {"ok": False, "reason": f"error: {exc}"}
