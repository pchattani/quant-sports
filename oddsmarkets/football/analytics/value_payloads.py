"""
The Value section's payloads, the club pages' "Strengths and needs" and the
transfer simulator's inputs, from the fitted value model (value.py).

    data/value/meta.json          the method, weights, validation, replacement levels,
                                  competition offsets, ageing curve, windows
    data/value/players.json       one row per player: the last 12 months of club
                                  football, projected value, fair value index
    data/value/lines.json         one row per player per competition, current season
    data/value/club/<tid>.json    one file per club of a followed league: unit grades
                                  against the league, strengths, weaknesses, ranked
                                  targets, the depth chart the simulator reads, and
                                  (16 Oct 2026) its transfer budget and ledger
    data/value/transfers.json     the transfers feed with grades, the best and worst deals
                                  of the last 12 months, window summaries by league
                                  (transfers.py)
    data/value/moves.json         (23 Oct 2026) who moves next: each followed club's players'
                                  chance of leaving in the coming window, how and where to if
                                  they move (moves.py); the club files carry `movement` (the
                                  outlook by position and ranked targets)

Field contract: docs/site/UNIFIED_PAYLOADS.md section 11. Nothing here invents a
fee, a salary or availability: Sofascore's market value and contract dates appear
only where the stores already hold them, and are labelled as Sofascore's.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from oddsmarkets.football.analytics import moves as MV
from oddsmarkets.football.analytics import transfers as TR
from oddsmarkets.football.analytics import value as V

logger = logging.getLogger(__name__)

TARGETS_PER_NEED = 5
TARGET_MAX_AGE = 31
FREE_MAX_AGE = 33
TARGET_STRENGTH_MARGIN = 0.15        # points per game on the pooled scale: "similar or lower"
TARGET_LEAGUE_STEP = 0.25            # goals per match: a target's league at most this much stronger than the buyer's
REGULAR_SHARE = 0.85                 # minutes share a signing who starts is assumed to take
TYPICAL_SLOTS = {"GK": 1, "CB": 2, "FB": 2, "MID": 3, "ATT": 3, "ST": 1}
SURPLUS_MINUTES = 450                # a "regular" at his club for the surplus-depth hint (last 12 months)
SETTLED = 0.02                       # nothing left to play for: every band and the title below this
MINUTES_CAP = 85.0                   # a regular's average minutes per match (rotation, substitutions)
POOL_MEAN_GOALS = 1.35
AFFORD_CUTOFF = 1.5                  # a target whose fair fee is over this x the buyer's 90th-percentile budget is left out


@dataclass
class ValueContext:
    data_dir: Path
    comps: dict[str, dict]                      # slug -> {name, short, kind, scope}
    pool: dict
    people: dict[str, dict]                     # pid -> {name, dob, pos, nat, ...}
    club_of: dict[str, dict | None]             # pid -> current club {tid, name, source} or None
    clubs: dict[str, dict]                      # tid -> {name, names, national}
    squads: dict
    archive: dict
    entries: list[dict]
    today: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    transfers: dict | None = None               # the transfer store (None: read data/transfers/store.json)


def _read_store(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def _round(x, n=3):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, n) if math.isfinite(f) else None


def _age_years(dob: str | None, today: date) -> float | None:
    if not dob:
        return None
    try:
        born = date.fromisoformat(str(dob)[:10])
    except ValueError:
        return None
    return (today - born).days / 365.25


# ── competition strength on the pooled scale ─────────────────────────────────

def pool_club_xgd(pool: dict, comps: dict[str, dict]) -> dict[int, dict]:
    """team id -> {xgd, strength, rank, comp}: the club's league entry, else a continental-cup entry."""
    out: dict[int, dict] = {}
    for c in pool.get("clubs") or []:
        tid = c.get("team_id")
        if tid is None or c.get("xg_for") is None or c.get("xg_against") is None:
            continue
        kind = (comps.get(c.get("comp") or "") or {}).get("kind")
        prio = 2 if c.get("in_league") else 1 if kind == "continental_club" else 0
        if prio == 0:
            continue          # a domestic-cup entry is linked to the pool only through its own cup
        cur = out.get(int(tid))
        if cur is None or prio > cur["_prio"]:
            out[int(tid)] = {"xgd": float(c["xg_for"]) - float(c["xg_against"]), "strength": c.get("strength"),
                             "rank": c.get("rank"), "rank_rated": c.get("rank_rated"), "rated": c.get("rated"),
                             "comp": c.get("comp"), "_prio": prio}
    return out


def comp_offsets(R: V.Rows, pool: dict, comps: dict[str, dict]) -> tuple[dict[str, float], dict[str, dict]]:
    """
    Each competition's strength on the pooled scale, in goals of expected goal
    difference per match against the pool-average club:
    - a pooled league or a club cup: the minutes-weighted mean of its clubs' pooled ratings;
    - a league outside the pool (Argentina): bridged through its clubs that play in
      continental cups, as the mean of (pooled rating - own-league xG difference per match);
    - national-team competitions: 0 (not on the club scale).
    """
    clubs = pool_club_xgd(pool, comps)
    pooled_leagues = set((pool.get("leagues") or {}).keys())
    off: dict[str, float] = {}
    info: dict[str, dict] = {}
    if not len(R):
        return off, info
    # Own-league xG difference per match per club (all seasons in the data), for bridging.
    n_m = R.m_day.size
    for ci, slug in enumerate(R.comps):
        meta = comps.get(slug) or {}
        if meta.get("scope") == "international":
            off[slug] = 0.0
            info[slug] = {"method": "national teams: not on the club scale"}
            continue
        sel = R.comp == ci
        tids, mins = R.tid[sel], R.mins[sel]
        known = np.array([int(t) in clubs for t in tids]) if tids.size else np.zeros(0, dtype=bool)
        share = float(mins[known].sum() / mins.sum()) if mins.sum() > 0 else 0.0
        if meta.get("kind") == "league" and slug not in pooled_leagues:
            # Bridge: rating on the pool minus rating within this league, over the bridging clubs.
            ms = np.flatnonzero(R.m_comp == ci) if n_m else np.zeros(0, dtype=int)
            per: dict[int, list[float]] = {}
            for mi in ms:
                d = R.m_npxg[mi, 0] - R.m_npxg[mi, 1]
                for s, sign in ((0, 1.0), (1, -1.0)):
                    per.setdefault(int(R.m_tid[mi, s]), []).append(sign * d)
            gaps = [clubs[t]["xgd"] - float(np.mean(v)) for t, v in per.items() if t in clubs and len(v) >= 10]
            off[slug] = float(np.mean(gaps)) if len(gaps) >= 3 else 0.0
            info[slug] = {"method": "bridged through clubs in continental cups", "n_bridge": len(gaps), "approximate": True}
            continue
        if share <= 0:
            off[slug] = 0.0
            info[slug] = {"method": "no club in the pooled fit", "approximate": True}
            continue
        vals = np.array([clubs[int(t)]["xgd"] for t in tids[known]])
        off[slug] = float(np.average(vals, weights=mins[known]))
        info[slug] = {"method": "pooled league" if slug in pooled_leagues else "clubs in the pooled fit",
                      "coverage": round(share, 3), **({"approximate": True} if share < 0.6 else {})}
    return off, info


def ppg_per_goal(data_dir: Path, comps: dict[str, dict]) -> dict[str, float]:
    """Points per goal of expected goal difference, per league from its own scoring rate."""
    out: dict[str, float] = {}
    for slug, meta in comps.items():
        if meta.get("kind") != "league":
            continue
        try:
            cal = (json.loads((data_dir / slug / "meta.json").read_text(encoding="utf-8")) or {}).get("calibration") or {}
        except (OSError, ValueError):
            cal = {}
        out[slug] = round(V.xpts_slope(cal.get("mean_goals") or POOL_MEAN_GOALS), 4)
    out["_pool"] = round(V.xpts_slope(POOL_MEAN_GOALS), 4)
    return out


# ── ageing from the archive ───────────────────────────────────────────────────

def ageing_pairs(archive: dict, comps: dict[str, dict]) -> list[tuple[float, float, float]]:
    """(age, rating change to the next season, weight) from the archive's careers, club competitions, 900+ minutes each."""
    from oddsmarkets.football.analytics.archive import season_row

    pairs: list[tuple[float, float, float]] = []
    for pid, rec in (archive.get("players") or {}).items():
        det = rec.get("details") or {}
        dob = det.get("dob")
        if not dob:
            continue
        try:
            born = datetime.fromtimestamp(float(dob), tz=timezone.utc).date()
        except (ValueError, OSError, OverflowError, TypeError):
            continue
        by_t: dict[Any, dict[int, tuple[float, float]]] = {}
        for e in rec.get("seasons") or []:
            if e.get("empty"):
                continue
            row = season_row(e)
            mins, rt = row.get("minutes") or 0, row.get("rating")
            if not rt or mins < 900:
                continue
            year = str(e.get("year") or "")
            y = None
            if "/" in year:
                try:
                    y = 2000 + int(year.split("/")[0]) if len(year.split("/")[0]) == 2 else int(year.split("/")[0])
                    mid = date(y + 1, 1, 1)
                except ValueError:
                    y = None
            elif year[:4].isdigit():
                y = int(year[:4])
                mid = date(y, 7, 1)
            if y is None:
                continue
            by_t.setdefault(e.get("tid"), {})[y] = ((mid - born).days / 365.25, float(rt), float(mins))
        for seasons in by_t.values():
            for y, (age, rt, mins) in seasons.items():
                nxt = seasons.get(y + 1)
                if nxt:
                    w = 2.0 / (1.0 / mins + 1.0 / nxt[2])
                    pairs.append((age, nxt[1] - rt, w))
    return pairs


# ── the build ────────────────────────────────────────────────────────────────

def _season_order(R: V.Rows) -> dict[str, list[str]]:
    """comp -> its season keys, oldest first (by their latest match)."""
    out: dict[str, list[str]] = {}
    last: dict[tuple[int, int], int] = {}
    for c, s, d in zip(R.comp.tolist(), R.sid.tolist(), R.day.tolist()):
        k = (c, s)
        if d > last.get(k, 0):
            last[k] = d
    for (c, s), d in sorted(last.items(), key=lambda kv: kv[1]):
        out.setdefault(R.comps[c], []).append(R.sids[s])
    return out


def build_value(ctx: ValueContext, R: V.Rows, vm: V.ValueModel | None = None, out_dir: Path | None = None) -> dict:
    """Fit (unless given), compute every line and write the payloads. Returns a summary."""
    today = ctx.today.date()
    data_dir = ctx.data_dir
    out_dir = out_dir or (data_dir / "value")
    offsets, off_info = comp_offsets(R, ctx.pool, ctx.comps)
    if vm is None:
        vm = V.fit_model(R, offsets)
    else:
        vm.offset = dict(offsets)
    vals = V.row_values(R, vm)
    nC = len(V.COMPONENTS_OUT)
    club_rows = V._club_rows(R)
    win_lo = (today.toordinal() - V.WINDOW_DAYS)
    in_win = club_rows & (R.day >= win_lo)
    ppg = ppg_per_goal(data_dir, ctx.comps)
    ppg_pool = ppg["_pool"]

    # ── the last 12 months, per player ──────────────────────────────────────
    pid_list = R.pid.tolist()
    w_lines = V.aggregate_lines(R, vals, np.flatnonzero(in_win), lambda r: pid_list[r])
    all_roles = V.aggregate_lines(R, np.zeros_like(vals), np.flatnonzero(club_rows), lambda r: pid_list[r])
    role_of: dict[int, str] = {}
    for pid in set(pid_list):
        ln = w_lines.get(pid) or all_roles.get(pid)
        rm = (w_lines.get(pid).role_min if w_lines.get(pid) and w_lines[pid].role_min else None) or (all_roles.get(pid).role_min if all_roles.get(pid) else {})
        letter = (ln.letter() if ln else None) or ((ctx.people.get(str(pid)) or {}).get("pos"))
        role_of[pid] = V.modal_role(rm, letter)

    # Replacement levels: the 20th percentile of regulars in each fine role.
    regulars = {pid: ln for pid, ln in w_lines.items() if ln.mins >= V.REGULAR_MINUTES}
    by_role: dict[str, list[float]] = {}
    for pid, ln in regulars.items():
        by_role.setdefault(role_of[pid], []).append(ln.rate)
    all_rates = np.array([ln.rate for ln in regulars.values()]) if regulars else np.zeros(1)
    repl: dict[str, float] = {}
    for r in V.ROLES:
        xs = np.array(by_role.get(r) or [])
        if xs.size >= 10:
            repl[r] = float(np.percentile(xs, V.REPLACEMENT_PCT))
        else:
            unit_rs = [x for rr in V.roles_of_unit(V.UNIT_OF[r]) for x in by_role.get(rr, [])]
            repl[r] = float(np.percentile(unit_rs, V.REPLACEMENT_PCT)) if len(unit_rs) >= 10 else float(np.percentile(all_rates, V.REPLACEMENT_PCT))
    for coarse, fines in V.COARSE_FINE.items():
        repl[coarse] = float(np.mean([repl[f] for f in fines]))

    # Each role's mean component profile (regulars), for the "why" of a value.
    role_mean: dict[str, np.ndarray] = {}
    for r in list(V.ROLES) + list(V.COARSE_FINE):
        fines = (r,) if r in V.ROLES else V.COARSE_FINE[r]
        ms = [(ln.comp, ln.mins) for pid, ln in regulars.items() if role_of[pid] in fines]
        tot = sum(m for _, m in ms)
        role_mean[r] = (sum(c for c, _ in ms) / (tot / 90.0)) if tot > 0 else np.zeros(nC)

    # Percentiles of regulars within their role (12 months).
    reg_rates: dict[str, np.ndarray] = {r: np.sort(np.array([ln.rate for pid, ln in regulars.items() if role_of[pid] == r])) for r in set(role_of.values())}

    def pct12(pid: int, rate: float) -> int | None:
        xs = reg_rates.get(role_of[pid])
        if xs is None or xs.size < 10:
            unit = V.unit_of_role(role_of[pid])
            xs = np.sort(np.array([ln.rate for p2, ln in regulars.items() if V.unit_of_role(role_of[p2]) == unit]))
        return V.percentile_rank(xs, rate) if xs.size >= 10 else None

    # Ageing: rating change by age (delta method over the archive), turned into value by the
    # cross-sectional slope of value on rating among outfield regulars.
    pairs = ageing_pairs(ctx.archive, ctx.comps)
    n_pairs = len(pairs)
    curve = V.ageing_curve(pairs)
    xr = [(ln.rating, ln.rate) for pid, ln in regulars.items() if ln.rating and role_of[pid] != "GK"]
    slope_v = float(np.polyfit([a for a, _ in xr], [b for _, b in xr], 1)[0]) if len(xr) >= 50 else 0.15
    slope_v = max(slope_v, 0.0)

    # Careers thin out: the chance a regular of each age is still one a year later.
    reg_ages = [_age_years((ctx.people.get(str(pid)) or {}).get("dob"), today) for pid in regulars]
    survive = V.continuation_curve([a for a in reg_ages if a is not None])

    def fvi_raw(proj: float, age: float | None) -> float | None:
        if age is None:
            return None
        total, g, alive = 0.0, proj, 1.0
        for t in range(V.FVI_YEARS):
            total += (V.FVI_DISCOUNT ** t) * alive * max(g, 0.0) * (V.FVI_MINUTES / 90.0) * ppg_pool
            a = int(min(max(age + t, 17), 40))
            g += slope_v * curve.get(min(a, 38), 0.0)
            alive *= survive.get(a, 0.0)
        return total

    # Sofascore's own figures, where the stores hold them (reference only).
    mv: dict[str, tuple[float, str]] = {}
    until: dict[str, str] = {}
    for pid, rec in (ctx.archive.get("players") or {}).items():
        det = rec.get("details") or {}
        if det.get("market_value") and (det.get("market_value_currency") or "EUR") == "EUR":
            mv[str(pid)] = (float(det["market_value"]), str(rec.get("fetched_at") or "")[:10])
        if det.get("contract_until"):
            until[str(pid)] = datetime.fromtimestamp(float(det["contract_until"]), tz=timezone.utc).strftime("%Y-%m")
    for tid, rec in (ctx.squads.get("teams") or {}).items():
        for p in rec.get("players") or []:
            if p.get("mv") and not p.get("mvc"):
                mv[str(p.get("id"))] = (float(p["mv"]), str(rec.get("fetched_at") or "")[:10])
            if p.get("until"):
                try:
                    until[str(p.get("id"))] = datetime.fromtimestamp(float(p["until"]), tz=timezone.utc).strftime("%Y-%m")
                except (ValueError, OSError, OverflowError, TypeError):
                    pass
    free: dict[str, str] = {}
    for pid, rec in (ctx.squads.get("people") or {}).items():
        if str(rec.get("team") or "").strip().lower() == "no team":
            free[str(pid)] = str(rec.get("fetched_at") or "")[:10]

    pool_clubs = pool_club_xgd(ctx.pool, ctx.comps)
    club_name = lambda tid: ((ctx.clubs.get(str(tid)) or {}).get("name")) if tid is not None else None  # noqa: E731

    def home_league(pid: int, ln: V.Line | None, tid: int | None) -> str | None:
        if tid is not None and int(tid) in club_league:
            return club_league[int(tid)]
        if ln:
            best = max(((ci, m) for ci, m in ln.by_comp.items() if (ctx.comps.get(R.comps[ci]) or {}).get("kind") == "league"),
                       key=lambda kv: kv[1], default=None)
            return R.comps[best[0]] if best else None
        return None

    # ── current-season lines per competition ───────────────────────────────
    order = _season_order(R)
    cur_sid = {slug: R.current.get(slug) for slug in R.comps}
    prev_sid = {}
    for slug, sids in order.items():
        cur = cur_sid.get(slug) or (sids[-1] if sids else None)
        cur_sid[slug] = cur
        earlier = [s for s in sids if s != cur]
        prev_sid[slug] = earlier[-1] if earlier else None
    sid_ix = {s: i for i, s in enumerate(R.sids)}
    comp_ix = {c: i for i, c in enumerate(R.comps)}
    cur_pairs = {(comp_ix[c], sid_ix[s]) for c, s in cur_sid.items() if s in sid_ix}
    prev_pairs = {(comp_ix[c], sid_ix[s]) for c, s in prev_sid.items() if s in sid_ix}
    comp_l, sid_l = R.comp.tolist(), R.sid.tolist()
    cur_lines = V.aggregate_lines(R, vals, np.arange(len(R)), lambda r: (pid_list[r], comp_l[r]) if (comp_l[r], sid_l[r]) in cur_pairs else None)
    prev_lines = V.aggregate_lines(R, vals, np.arange(len(R)), lambda r: (pid_list[r], comp_l[r]) if (comp_l[r], sid_l[r]) in prev_pairs else None)

    floors = {e.get("slug"): int(e.get("_floor") or 270) for e in ctx.entries if e.get("slug")}

    # Each club's league: where it plays this season, else where it played most in the last 12 months.
    league_ix = {i for i, c in enumerate(R.comps) if (ctx.comps.get(c) or {}).get("kind") == "league"}
    cnt_cur: dict[int, dict[int, float]] = {}
    cnt_win: dict[int, dict[int, float]] = {}
    for c, s_, t, m, w in zip(comp_l, sid_l, R.tid.tolist(), R.mins.tolist(), in_win.tolist()):
        if c not in league_ix or t < 0:
            continue
        if (c, s_) in cur_pairs:
            d = cnt_cur.setdefault(t, {})
            d[c] = d.get(c, 0.0) + m
        elif w:
            d = cnt_win.setdefault(t, {})
            d[c] = d.get(c, 0.0) + m
    club_league: dict[int, str] = {}
    for t in set(cnt_cur) | set(cnt_win):
        d = cnt_cur.get(t) or cnt_win.get(t)
        club_league[t] = R.comps[max(d.items(), key=lambda kv: kv[1])[0]]

    def role_for(pid: int) -> str:
        return role_of.get(pid) or "MF"

    # Percentiles of current lines within (competition, unit), over the competition's floor.
    pools_cur: dict[tuple[int, str], list[float]] = {}
    for (pid, ci), ln in cur_lines.items():
        if ln.mins >= floors.get(R.comps[ci], 270):
            pools_cur.setdefault((ci, V.unit_of_role(role_for(pid))), []).append(ln.rate)
    pools_cur_s = {k: np.sort(np.array(v)) for k, v in pools_cur.items()}

    # ── players.json ────────────────────────────────────────────────────────
    ids = set(w_lines) | {pid for pid, _ in cur_lines}
    p_fields = ["id", "name", "age", "nat", "role", "tid", "club", "league", "min", "apps", "gar90", "gar", "par", "pct", "proj",
                "fvi", "mv", "until", "free", "rt", "c", "v2", "v2lo", "v2hi", "avail", "fee", "feelo", "feehi"]
    p_rows: list[list] = []
    player_info: dict[int, dict] = {}
    fvis: list[tuple[int, float, bool]] = []
    for pid in ids:
        sp = str(pid)
        ident = ctx.people.get(sp) or {}
        if not ident.get("name"):
            continue
        ln = w_lines.get(pid)
        role = role_for(pid)
        cc = ctx.club_of.get(sp)
        tid = cc.get("tid") if cc else None
        if tid is None and sp not in free and ln and ln.tid >= 0 and ln.last_day >= win_lo:
            tid = ln.tid
        age_f = _age_years(ident.get("dob"), today)
        rate = ln.rate if ln else None
        gar90 = (rate - repl[role]) if ln else None
        proj = (ln.mins / (ln.mins + V.PROJ_MINUTES)) * gar90 if ln else None
        info = {"role": role, "tid": tid, "club": club_name(tid) if tid is not None else None,
                "age": age_f, "min": ln.mins if ln else 0.0, "gar90": gar90, "proj": proj,
                "league": home_league(pid, ln, tid), "name": ident.get("name"), "rt": ln.rating if ln else None,
                "comp_rate": (ln.comp_rate() - role_mean.get(role, np.zeros(nC))) if ln else None}
        player_info[pid] = info
        if ln and ln.mins >= 450 and proj is not None:
            raw = fvi_raw(proj, age_f)
            if raw is not None:
                big5 = bool(ln.by_comp) and R.comps[max(ln.by_comp.items(), key=lambda kv: kv[1])[0]] in V.BIG_FIVE
                fvis.append((pid, raw, big5 and ln.mins >= 1800))
    ref_pool = [raw for _, raw, ok in fvis if ok and raw > 0]
    fvi_ref = float(np.median(ref_pool)) if len(ref_pool) >= 20 else (float(np.median([r for _, r, _ in fvis if r > 0])) if fvis else 1.0)
    fvi_ref = fvi_ref or 1.0
    fvi_of = {pid: int(round(100.0 * raw / fvi_ref)) for pid, raw, _ in fvis}
    # A sanity check, not an input: how the index ranks players against Sofascore's market value.
    both = [(fvi_of[pid], mv[str(pid)][0]) for pid in fvi_of if str(pid) in mv]
    mv_check = None
    if len(both) >= 30:
        a = np.array(both, dtype=np.float64)
        ra, rb = np.argsort(np.argsort(a[:, 0])), np.argsort(np.argsort(a[:, 1]))
        mv_check = {"n": len(both), "rho": round(float(np.corrcoef(ra, rb)[0, 1]), 3)}
    # ── valuation v2, the fee model, transfers and budgets (transfers.py) ───
    followed: set[int] = set()
    for e in ctx.entries:
        if (ctx.comps.get(e.get("slug") or "") or {}).get("kind") == "league" and e.get("ok"):
            for info_t in (e.get("_teams") or {}).values():
                if isinstance(info_t, dict) and info_t.get("team_id"):
                    followed.add(int(info_t["team_id"]))
                    club_league.setdefault(int(info_t["team_id"]), e["slug"])
    store = ctx.transfers if ctx.transfers is not None else _read_store(ctx.data_dir / "transfers" / "store.json")
    trx = TR.build_transfers(
        store, R=R, vals=vals, repl=repl, role_of=role_of, player_info=player_info, people=ctx.people, squads=ctx.squads,
        archive=ctx.archive, club_xgd={t: v["xgd"] for t, v in pool_clubs.items()}, club_league=club_league,
        club_name={int(t): (c or {}).get("name") for t, c in ctx.clubs.items() if str(t).isdigit()}, followed=followed,
        offsets=offsets, ppg_pool=ppg_pool, curve=curve, slope=slope_v, survive=survive, pairs=pairs, today=today,
        in_window_rows=in_win)
    _write(out_dir / "transfers.json", {**trx.feed, "updated_at": ctx.today.strftime("%Y-%m-%dT%H:%M:%SZ")})
    for pid in ids:
        info = player_info.get(pid)
        if not info:
            continue
        sp = str(pid)
        ln = w_lines.get(pid)
        ident = ctx.people.get(sp) or {}
        tid = info["tid"]
        tv = trx.players.get(pid) or {}
        p_rows.append([
            sp, ident.get("name"), int(info["age"]) if info["age"] is not None else None, ident.get("nat"), info["role"],
            tid, club_name(tid) if tid is not None else None, info["league"],
            int(round(ln.mins)) if ln else 0, ln.apps if ln else 0,
            _round(info["gar90"]), _round(info["gar90"] * ln.mins / 90.0, 2) if ln else None,
            _round(info["gar90"] * ln.mins / 90.0 * ppg_pool, 2) if ln else None,
            pct12(pid, ln.rate) if ln and ln.mins >= V.REGULAR_MINUTES else None,
            _round(info["proj"]), fvi_of.get(pid),
            int(mv[sp][0]) if sp in mv else None, until.get(sp), 1 if sp in free else None,
            _round(info["rt"], 2), [_round(x) for x in info["comp_rate"]] if info["comp_rate"] is not None else None,
            _round(tv.get("v2"), 2), _round(tv.get("v2lo"), 2), _round(tv.get("v2hi"), 2), _round(tv.get("avail"), 2),
            _round(tv.get("fee"), -4), _round(tv.get("fee_lo"), -4), _round(tv.get("fee_hi"), -4),
        ])
    p_rows.sort(key=lambda r: (-(r[10] if r[10] is not None else -9), r[1] or ""))
    _write(out_dir / "players.json", {"fields": p_fields, "rows": p_rows, "updated_at": ctx.today.strftime("%Y-%m-%dT%H:%M:%SZ")})

    # ── lines.json ──────────────────────────────────────────────────────────
    l_fields = ["id", "comp", "tid", "min", "apps", "gar90", "gar", "par", "pct", "role", "prev90", "rt", "c"]
    l_rows: list[list] = []
    for (pid, ci), ln in cur_lines.items():
        if ln.mins < 90 or pid not in player_info:
            continue
        slug = R.comps[ci]
        role = role_for(pid)
        g90 = ln.rate - repl[role]
        pp = prev_lines.get((pid, ci))
        prev90 = (pp.rate - repl[role]) if pp and pp.mins >= 450 else None
        k = (ci, V.unit_of_role(role))
        pc = V.percentile_rank(pools_cur_s[k], ln.rate) if ln.mins >= floors.get(slug, 270) and k in pools_cur_s and pools_cur_s[k].size >= 5 else None
        rate_pg = ppg.get(slug, ppg_pool)
        l_rows.append([str(pid), slug, ln.tid if ln.tid >= 0 else None, int(round(ln.mins)), ln.apps, _round(g90),
                       _round(g90 * ln.mins / 90.0, 2), _round(g90 * ln.mins / 90.0 * rate_pg, 2), pc, role, _round(prev90),
                       _round(ln.rating, 2), [_round(x) for x in (ln.comp_rate() - role_mean.get(role, np.zeros(nC)))]])
    l_rows.sort(key=lambda r: (r[1], -(r[6] or 0)))
    _write(out_dir / "lines.json", {"fields": l_fields, "rows": l_rows, "updated_at": ctx.today.strftime("%Y-%m-%dT%H:%M:%SZ")})

    # ── who moves next (moves.py): data/value/moves.json and the clubs' `movement` ──
    mres = build_movement(ctx, R, store, offsets, followed, player_info, trx, pool_clubs, out_dir)

    # ── clubs: strengths and needs ──────────────────────────────────────────
    n_clubs = write_club_needs(ctx, R, vals, player_info, role_of, cur_pairs, ppg, pool_clubs, mv, until, free, fvi_of, out_dir,
                               offsets, trx=trx, movement=mres["clubs"])

    # ── meta.json ───────────────────────────────────────────────────────────
    comps_meta = {}
    for slug in R.comps:
        m = ctx.comps.get(slug) or {}
        comps_meta[slug] = {"name": m.get("name") or slug, "short": m.get("short") or slug, "kind": m.get("kind"), "scope": m.get("scope"),
                            "centre": _round(vm.centre.get(slug), 4), "offset": _round(offsets.get(slug), 4), **(off_info.get(slug) or {}),
                            "ppg": ppg.get(slug, ppg_pool), "floor": floors.get(slug), "tier": V.LEAGUE_TIERS.get(slug),
                            "current": cur_sid.get(slug), "previous": prev_sid.get(slug)}
    windows = {slug: V.window_status(slug, today) for slug in V.WINDOWS}
    meta = {
        "model": {
            "currency": "goals of non-penalty expected goal difference",
            "weights": vm.weights(), "box_scale": _round(vm.scale, 4), "rating_weight": _round(vm.rating_w, 5),
            "lambda": vm.lam if vm.lam == vm.lam else None, "fitted": vm.fitted, "fit_matches": vm.n_fit,
            "prior_minutes": V.PRIOR_MINUTES, "proj_minutes": V.PROJ_MINUTES, "regular_minutes": V.REGULAR_MINUTES,
            "replacement_pct": V.REPLACEMENT_PCT, "window_days": V.WINDOW_DAYS,
        },
        "validation": vm.validation, "reliability": vm.reliability,
        "components": list(V.COMPONENTS_OUT),
        "roles": {r: V.ROLE_LABELS[r] for r in list(V.ROLES) + list(V.COARSE_FINE)},
        "units": [{"key": u, "label": lbl, "roles": list(rs)} for u, lbl, rs in V.UNITS],
        "replacement": {r: _round(v, 4) for r, v in repl.items()},
        "role_mean_rate": {r: _round(float(role_mean[r].sum()), 4) for r in role_mean},
        "regulars": {r: int(len(v)) for r, v in by_role.items()},
        "ppg": ppg, "comps": comps_meta, "tiers": sorted(set(V.LEAGUE_TIERS.values())),
        "fvi": {"minutes": V.FVI_MINUTES, "years": V.FVI_YEARS, "discount": V.FVI_DISCOUNT, "reference_raw": _round(fvi_ref, 3),
                "reference": "the median regular (1,800+ minutes in 12 months) of the top five European leagues = 100",
                "value_per_rating_point": _round(slope_v, 4), "ageing": {str(a): v for a, v in curve.items()},
                "continuation": {str(a): v for a, v in survive.items()}, "market_value_spearman": mv_check,
                "n_ageing_pairs": n_pairs},
        "market_value": {"n": len(mv), "source": "Sofascore's proposed market value (EUR), from the current squads (and the archive's player profiles); shown for reference only"},
        "fee": trx.meta["fee"], "v2": trx.meta["v2"], "budgets": trx.meta["budgets"], "transfers": {
            "coverage": trx.meta["coverage"], "grades": trx.meta["grades"], "runtime_s": trx.meta["runtime_s"],
            "source": "Sofascore: each followed club's recent transfers and players' transfer histories (fees as Sofascore publishes them)"},
        "windows": windows, "today": today.isoformat(),
        "moves": {k: v for k, v in mres["meta"].items() if k not in ("models", "reference")},
        "targets": {"max_age": TARGET_MAX_AGE, "strength_margin": TARGET_STRENGTH_MARGIN, "league_step": TARGET_LEAGUE_STEP,
                    "free_max_age": FREE_MAX_AGE, "per_need": TARGETS_PER_NEED,
                    "regular_share": REGULAR_SHARE, "minutes_cap": MINUTES_CAP},
        "counts": {"rows": int(len(R)), "players": len(p_rows), "lines": len(l_rows), "clubs": n_clubs, "regulars": len(regulars)},
        "updated_at": ctx.today.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _write(out_dir / "meta.json", meta)
    logger.info("value: %d players, %d lines, %d clubs; held-out R2 (xG diff) value %s v rating %s",
                len(p_rows), len(l_rows), n_clubs, ((vm.validation.get("r2") or {}).get("xgd") or {}).get("value"),
                ((vm.validation.get("r2") or {}).get("xgd") or {}).get("rating"))
    return {"players": len(p_rows), "lines": len(l_rows), "clubs": n_clubs, "validation": vm.validation,
            # For the fantasy step: each player's expected points above replacement next season (its price proxy).
            "_fantasy_score": {pid: v.get("v2y1", 0.0) for pid, v in trx.players.items()}}


def make_fee_fn(trx: "TR.TransferResult | None", player_info: dict[int, dict], pool_clubs: dict[int, dict]):
    """The fair fee of a player to a buyer, (fee, 25th, 75th percentile) in EUR, or None without the fee model."""
    if trx is None or trx.fee_model is None:
        return None

    def fee_fn(pid: int, buyer_tid: int) -> tuple[float, float, float] | None:
        info, tv = player_info.get(pid), trx.players.get(pid)
        if not info or not tv or info["min"] < 450:
            return None
        sx = (pool_clubs.get(info["tid"]) or {}).get("xgd") if info["tid"] is not None else None
        bx = (pool_clubs.get(buyer_tid) or {}).get("xgd")
        X = TR.features(np.array([tv["v2"]]), np.array([info["proj"]]),
                        np.array([info["age"] if info["age"] is not None else np.nan]), [V.unit_of_role(info["role"])],
                        np.array([sx if sx is not None else np.nan]), np.array([bx if bx is not None else np.nan]),
                        np.array([info["min"] / 90.0]))
        lp = float(trx.fee_model.predict_log(X)[0])
        z = 0.6745 * trx.fee_model.sigma
        return math.exp(lp), math.exp(lp - z), math.exp(lp + z)
    return fee_fn


def build_movement(ctx: ValueContext, R: V.Rows, store: dict, offsets: dict[str, float], followed: set[int],
                   player_info: dict[int, dict], trx: "TR.TransferResult", pool_clubs: dict[int, dict],
                   out_dir: Path) -> dict:
    """data/value/moves.json and each club's `movement` block (moves.py); a failure leaves {"ok": false}."""
    today = ctx.today.date()
    try:
        lg_off = {slug: float(v) for slug, v in offsets.items()
                  if (ctx.comps.get(slug) or {}).get("kind") == "league" and (ctx.comps.get(slug) or {}).get("scope", "club") == "club"}
        dob = {pid: p.get("dob") for pid, p in ctx.people.items() if p.get("dob")}
        names = {int(t): (c or {}).get("name") for t, c in ctx.clubs.items() if str(t).isdigit()}
        res = MV.build_moves(R, TR.normalise(store, today), dob, lg_off, today, followed, names, player_info,
                             club_of=ctx.club_of, fee_fn=make_fee_fn(trx, player_info, pool_clubs),
                             budgets={t: (c or {}).get("budget") for t, c in trx.clubs.items()})
    except Exception as exc:  # noqa: BLE001 - the value pages must not fail with this section
        logger.error("moves: not built: %s", exc, exc_info=True)
        res = {"players": {"fields": MV.P_FIELDS, "rows": []}, "clubs": {}, "meta": {"ok": False, "reason": str(exc)[:200]}}
    _write(out_dir / "moves.json", {**res["players"], "meta": res["meta"], "updated_at": ctx.today.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return res


def write_club_needs(ctx: ValueContext, R: V.Rows, vals: np.ndarray, player_info: dict[int, dict], role_of: dict[int, str],
                     cur_pairs: set, ppg: dict, pool_clubs: dict[int, dict], mv: dict, until: dict, free: dict,
                     fvi_of: dict[int, int], out_dir: Path, offsets: dict[str, float] | None = None,
                     trx: "TR.TransferResult | None" = None, movement: dict[int, dict] | None = None) -> int:
    today = ctx.today.date()
    fee_fn = make_fee_fn(trx, player_info, pool_clubs)
    club_dir = out_dir / "club"
    league_slugs = [s for s, m in ctx.comps.items() if m.get("kind") == "league" and m.get("scope") == "club"]
    entries = {e.get("slug"): e for e in ctx.entries if e.get("slug")}
    sens_cache: dict[str, dict] = {}

    def sens(slug: str) -> dict:
        if slug not in sens_cache:
            try:
                sens_cache[slug] = json.loads((ctx.data_dir / slug / "sensitivity.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                sens_cache[slug] = {}
        return sens_cache[slug]

    squad: dict[int, list[int]] = {}
    for pid, cc in ctx.club_of.items():
        if cc and cc.get("tid") is not None:
            try:
                squad.setdefault(int(cc["tid"]), []).append(int(pid))
            except (TypeError, ValueError):
                continue
    # This season's minutes per club, player and unit (every current competition the club plays).
    rows = np.flatnonzero(np.array([(c, s) in cur_pairs for c, s in zip(R.comp.tolist(), R.sid.tolist())]) & V._club_rows(R)) if len(R) else np.zeros(0, dtype=int)
    unit_min: dict[int, dict[int, dict[str, float]]] = {}
    club_matches: dict[int, set] = {}
    comp_mean_unit: dict[str, np.ndarray] = {}
    for r in rows:
        tid = int(R.tid[r])
        pid = int(R.pid[r])
        role = V.ROLES[int(R.role[r])] if R.role[r] >= 0 else role_of.get(pid, "MF")
        u = V.unit_of_role(role)
        d = unit_min.setdefault(tid, {}).setdefault(pid, {})
        d[u] = d.get(u, 0.0) + float(R.mins[r])
        club_matches.setdefault(tid, set()).add(int(R.match[r]))
    written: set[str] = set()
    units = [u for u, _, _ in V.UNITS]
    # Eligible targets per unit, best projection first (age, minutes; strength is checked per buyer).
    unit_cands: dict[str, list[int]] = {u: [] for u in units}
    for pid, info in player_info.items():
        if info["proj"] is None or info["age"] is None:
            continue
        is_free = str(pid) in free
        if is_free:
            if info["min"] < 450 or info["age"] > FREE_MAX_AGE:
                continue
        elif info["min"] < 900 or info["age"] > TARGET_MAX_AGE or info["tid"] is None:
            continue
        unit_cands[V.unit_of_role(info["role"])].append(pid)
    for u in units:
        unit_cands[u].sort(key=lambda p: -player_info[p]["proj"])
    # Feasibility hints the data supports: depth at the player's club, and a club with nothing left to play for.
    depth_n: dict[tuple[int, str], int] = {}
    for pid, info in player_info.items():
        if info["tid"] is not None and info["min"] >= SURPLUS_MINUTES:
            k = (int(info["tid"]), V.unit_of_role(info["role"]))
            depth_n[k] = depth_n.get(k, 0) + 1
    settled: set[int] = set()
    for slug in league_slugs:
        e = entries.get(slug) or {}
        ids = {name: int(info["team_id"]) for name, info in (e.get("_teams") or {}).items() if isinstance(info, dict) and info.get("team_id")}
        try:
            probs = json.loads((ctx.data_dir / slug / "probs.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for t in probs.get("teams") or []:
            ps = [t.get("p_title")] + list((t.get("bands") or {}).values()) + \
                 [t.get(k) for k in ("p_playoffs", "p_libertadores", "p_sudamericana", "p_relegation")]
            ps = [float(x) for x in ps if x is not None]
            if ps and max(ps) < SETTLED and ids.get(t.get("team")):
                settled.add(ids[t["team"]])
    hints_ctx = {"depth": depth_n, "settled": settled}
    unit_label = {u: lbl for u, lbl, _ in V.UNITS}
    for slug in league_slugs:
        e = entries.get(slug)
        if not e or not e.get("ok"):
            continue
        teams = e.get("_teams") or {}
        league_clubs = [(name, int(info["team_id"])) for name, info in teams.items() if isinstance(info, dict) and info.get("team_id")]
        if len(league_clubs) < 4:
            continue
        sp = sens(slug)
        rate_pg = ppg.get(slug, ppg.get("_pool", 0.33))
        grades: dict[int, dict[str, dict]] = {}
        for name, tid in league_clubs:
            mins_by = unit_min.get(tid, {})
            matches_n = max(len(club_matches.get(tid, ())), 1)
            members = squad.get(tid, [])
            g: dict[str, dict] = {}
            for u in units:
                total_u = sum(m.get(u, 0.0) for m in mins_by.values())
                slots = total_u / (matches_n * 90.0) if total_u > 0 else {"GK": 1.0, "CB": 2.0, "FB": 2.0, "MID": 2.5, "ATT": 2.5, "ST": 1.0}[u]
                cur = [(pid, mins_by.get(pid, {}).get(u, 0.0)) for pid in members if player_info.get(pid)]
                used = [(pid, m) for pid, m in cur if m > 0 and player_info[pid]["proj"] is not None]
                few = sum(m for _, m in used) < 270
                if few:
                    cand = sorted([pid for pid in members if player_info.get(pid) and player_info[pid]["proj"] is not None
                                   and V.unit_of_role(player_info[pid]["role"]) == u], key=lambda p: -player_info[p]["proj"])
                    k = max(1, int(round(slots)))
                    used = [(pid, 1.0) for pid in cand[:k]]
                if used:
                    w = sum(m for _, m in used)
                    rate = sum(player_info[p]["proj"] * m for p, m in used) / w
                    comp = sum(player_info[p]["comp_rate"] * m for p, m in used if player_info[p]["comp_rate"] is not None) / w
                else:
                    rate, comp = 0.0, np.zeros(len(V.COMPONENTS_OUT))
                depth = sorted([{"id": str(pid), "name": player_info[pid]["name"], "role": player_info[pid]["role"],
                                 "proj": _round(player_info[pid]["proj"]), "min": int(round(mins_by.get(pid, {}).get(u, 0.0))),
                                 "age": int(player_info[pid]["age"]) if player_info[pid]["age"] is not None else None}
                                for pid in members if player_info.get(pid) and player_info[pid]["proj"] is not None
                                and (V.unit_of_role(player_info[pid]["role"]) == u or mins_by.get(pid, {}).get(u, 0.0) >= 90)],
                               key=lambda d: (-(d["min"] or 0), -(d["proj"] or 0)))
                g[u] = {"rate": rate, "comp": comp, "slots": round(slots, 2), "few": few, "empty": not used, "depth": depth}
            grades[tid] = g
        # Percentiles within the league, unit by unit.
        for u in units:
            xs = np.sort(np.array([grades[t][u]["rate"] for _, t in league_clubs]))
            comp_mean_unit[f"{slug}:{u}"] = np.mean([grades[t][u]["comp"] for _, t in league_clubs], axis=0)
            for _, t in league_clubs:
                x = grades[t][u]["rate"]
                grades[t][u]["pct"] = V.percentile_rank(xs, x)
                grades[t][u]["rank"] = int((xs > x).sum()) + 1
                grades[t][u]["n"] = int(xs.size)
        for name, tid in league_clubs:
            g = grades[tid]
            pc = pool_clubs.get(tid) or {}
            buyer_strength = pc.get("strength")
            ordered = sorted(units, key=lambda u: -g[u]["pct"])
            strengths = [u for u in ordered[:3]]
            weaknesses = [u for u in sorted(units, key=lambda u: g[u]["pct"])[:3]]
            unit_rows = []
            for u in units:
                d = g[u]
                delta = d["comp"] - comp_mean_unit[f"{slug}:{u}"]
                if d["pct"] >= 50:
                    k = int(np.argmax(delta[:-1]))
                else:
                    k = int(np.argmin(delta[:-1]))
                unit_rows.append({
                    "unit": u, "label": unit_label[u], "rate": _round(d["rate"]), "pct": d["pct"], "rank": d["rank"], "n": d["n"],
                    "grade": grade_of(d["pct"]), "slots": d["slots"], "few": d["few"], "empty": d["empty"],
                    "evidence": {"component": V.COMPONENTS_OUT[k], "delta": _round(float(delta[k]))},
                    "depth": d["depth"][:8],
                })
            remaining = ((sp.get("teams") or {}).get(name) or {}).get("remaining")
            targets = {}
            for u in weaknesses:
                targets[u] = find_targets(tid, u, g[u], buyer_strength, player_info, unit_cands[u], pool_clubs, mv, until, free,
                                          fvi_of, rate_pg, remaining, today, offsets or {}, slug, hints_ctx,
                                          fee_fn=fee_fn, budget=((trx.clubs.get(tid) or {}).get("budget") if trx else None))
            payload = {
                "tid": tid, "name": name, "league": slug, "league_name": (ctx.comps.get(slug) or {}).get("name"),
                "season": e.get("season"), "as_of": today.isoformat(),
                "pool": {"strength": buyer_strength, "rank": pc.get("rank"), "rank_rated": pc.get("rank_rated"), "rated": pc.get("rated"),
                         "xgd": _round(pc.get("xgd"))} if pc else None,
                "units": unit_rows, "strengths": strengths, "weaknesses": weaknesses, "targets": targets,
                "ppg": rate_pg, "remaining": remaining, "matches_per_season": e.get("games_total") and int(round(2 * e["games_total"] / max(len(league_clubs), 1))),
                "gd_per_delta": ((sp.get("teams") or {}).get(name) or {}).get("gd_per_delta"),
                "sensitivity": bool((sp.get("teams") or {}).get(name)),
                "window": V.window_status(slug, today),
                "budget": (trx.clubs.get(tid) or {}).get("budget") if trx else None,
                "ledger": (trx.clubs.get(tid) or {}).get("ledger") if trx else None,
                "movement": (movement or {}).get(tid),
            }
            _write(club_dir / f"{tid}.json", payload)
            written.add(f"{tid}.json")
    # Prune files of clubs that left the followed leagues.
    if club_dir.exists():
        for f in club_dir.glob("*.json"):
            if f.name not in written:
                f.unlink()
    return len(written)


def grade_of(pct: int) -> str:
    return "A" if pct >= 80 else "B" if pct >= 60 else "C" if pct >= 40 else "D" if pct >= 20 else "E"


def find_targets(buyer_tid: int, unit: str, g: dict, buyer_strength: float | None, player_info: dict[int, dict],
                 cands: list[int], pool_clubs: dict[int, dict], mv: dict, until: dict, free: dict, fvi_of: dict[int, int],
                 rate_pg: float, remaining: int | None, today: date, offsets: dict[str, float] | None = None,
                 buyer_league: str | None = None, hints_ctx: dict | None = None, fee_fn=None, budget: dict | None = None) -> list[dict]:
    """
    Ranked candidates for one weak unit: the players who would add the most value
    there, among realistic targets (`cands` is the unit's eligible players, best
    projection first): at a club of similar or lower pooled strength, or without a
    club, never at the buyer, and from a league at most a step stronger than the
    buyer's (the data has no wages; a club in a much stronger league pays more).
    The gain is over the weakest of the unit's regulars.

    With the fee model and the buyer's budget (transfers.py): each target carries his fair fee to
    this buyer and whether it fits the budget ("yes" within the 25-75% summer range's top, "stretch"
    within its 90th percentile, "no" beyond); a target over AFFORD_CUTOFF times that 90th percentile
    is left out, so the list stays realistic.
    """
    offsets = offsets or {}
    cap = offsets.get(buyer_league or "", 0.0) + TARGET_LEAGUE_STEP if buyer_league in offsets else None
    depth = g["depth"]
    slots = max(int(round(g["slots"])), 1)
    regulars = sorted([d for d in depth if d["proj"] is not None], key=lambda d: -(d["min"] or 0))[:slots]
    displaced = min((d["proj"] for d in regulars), default=0.0) if regulars else 0.0
    out = []
    per_club: dict[Any, int] = {}
    for pid in cands:
        info = player_info[pid]
        gain = info["proj"] - displaced
        if gain <= 0.005:
            break
        if info["tid"] == buyer_tid:
            continue
        is_free = str(pid) in free
        if not is_free:
            pc = pool_clubs.get(info["tid"]) if info["tid"] is not None else None
            if not pc or buyer_strength is None or pc.get("strength") is None:
                continue
            if float(pc["strength"]) > float(buyer_strength) + TARGET_STRENGTH_MARGIN:
                continue
            if cap is not None and info["league"] in offsets and offsets[info["league"]] > cap:
                continue
        key = info["tid"] if not is_free else ("free", pid)
        if per_club.get(key, 0) >= 2:
            continue
        fee = fee_fn(pid, buyer_tid) if (fee_fn is not None and not is_free) else None
        afford = None
        summer_b = (budget or {}).get("summer") or {}
        if fee is not None and summer_b.get("hi80") is not None:
            if fee[0] > AFFORD_CUTOFF * max(float(summer_b["hi80"]), 1.0):
                continue
            afford = "yes" if fee[0] <= float(summer_b["hi"]) else "stretch" if fee[0] <= float(summer_b["hi80"]) else "no"
        per_club[key] = per_club.get(key, 0) + 1
        sp = str(pid)
        hint = []
        u = until.get(sp)
        if u:
            try:
                y, m = int(u[:4]), int(u[5:7])
                months = (y - today.year) * 12 + (m - today.month)
                if 0 <= months <= 12:
                    hint.append("contract ends " + V.MONTHS[m - 1] + " " + str(y) + " (Sofascore)")
            except ValueError:
                pass
        if is_free:
            hint.append("no club: Sofascore lists the player without a team (as of " + free[sp] + ")")
        elif hints_ctx and info["tid"] is not None:
            n_dep = (hints_ctx.get("depth") or {}).get((int(info["tid"]), unit), 0)
            if n_dep >= TYPICAL_SLOTS.get(unit, 2) + 2:
                hint.append(f"the player's club has {n_dep} regulars in this unit (450+ minutes in 12 months)")
            if int(info["tid"]) in (hints_ctx.get("settled") or set()):
                hint.append("the player's club has little left to play for this season (no title, band or relegation chance above 2%)")
        per_match = gain * REGULAR_SHARE
        out.append({
            "id": sp, "name": info["name"], "age": int(info["age"]) if info["age"] is not None else None, "role": info["role"],
            "tid": info["tid"] if not is_free else None, "club": info.get("club") if not is_free else None, "league": info["league"],
            "min": int(round(info["min"])), "proj": _round(info["proj"]),
            "gain90": _round(gain), "gain_pts_rest": _round(per_match * rate_pg * remaining, 2) if remaining else None,
            "gain_pts_38": _round(per_match * rate_pg * 38, 2), "fvi": fvi_of.get(pid),
            "mv": int(mv[sp][0]) if sp in mv else None, "until": u, "free": 1 if is_free else None,
            "fee": _round(fee[0], -4) if fee else None, "fee_lo": _round(fee[1], -4) if fee else None,
            "fee_hi": _round(fee[2], -4) if fee else None, "afford": afford,
            "club_strength": (pool_clubs.get(info["tid"]) or {}).get("strength") if (info["tid"] is not None and not is_free) else None,
            "hints": hint,
        })
        if len(out) >= TARGETS_PER_NEED:
            break
    return out
