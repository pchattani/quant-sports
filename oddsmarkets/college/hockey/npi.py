"""
NCAA men's hockey selection numbers, replicated from results: the NPI (2025-26 on) and the PairWise / RPI (to
2024-25). Published rules (CHN's primers, /info/?d=npi and /info/?d=pwcrpi, read 30 Oct 2026), our code:

NPI (NCAA Percentage Index, men's hockey 2025-26 on)
    a game's value against opponent o:   win  W = 25 + 0.75 * NPI_o + QWB,   loss  L = 0.75 * NPI_o
    QWB (quality win bonus) for a win    = 0.5 * (NPI_o - 51) when NPI_o > 51        (reverse-engineered from CHN's
                                                                                    team detail: 0.90 at 52.80, 3.82 at 58.63)
    weights: home win / road loss 0.8, road win / home loss 1.2, neutral 1.0; conference tournament games unweighted;
             an overtime win counts 0.6 of a win and 0.4 of a loss, with the home/road weight on the regulation part
             only (home OT win: W = 0.4 x 0.8 + 0.2, L = 0.4 x 1.2); a tie (shootouts are ties) 0.5 / 0.5.
    NPI_t = sum_g (w_W W_g + w_L L_g) / sum_g (w_W + w_L), iterated to a fixed point from 50.
    "Bad wins" (a win's W below the team's NPI) are dropped once the team has 12 weighted wins; "good losses" (an L
    above the team's NPI) are always dropped. Games against non-Division-I teams do not count.
PairWise (to 2024-25)
    RPI = 0.25 WP + 0.21 OWP + 0.54 OOWP (2006-07 on), every component home/road weighted from 2013-14; OWP excludes
    games against the team itself; overtime wins 2/3 of a win from 2021-22; QWB from 2013-14 = sum over wins against
    the RPI top 20 of 0.050 (No. 1) down to 0.0025 (No. 20), divided by weighted games; bad wins dropped.
    Comparison of two teams: one point for the better RPI, one for the better record against common opponents (the
    mean of per-opponent win percentages from 2012-13), one per head-to-head win; before 2013-14 also record against
    teams under consideration (RPI .500+). Most points wins; a tie goes to RPI. PairWise rank = comparisons won.

Selection (men): 16 teams, six conference tournament champions plus the top ten others; seeds by bands of four,
1 v 16 serpentine, hosts kept home, first-round conference match-ups avoided by swapping within a band.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

HOME_W, ROAD_W = 0.8, 1.2


# the women's NPI as College Hockey News publishes it (checked 30 Oct 2026 against its women's table): no home / road
# weighting, an overtime win two thirds of a win; the men's: 0.8 / 1.2 and 0.6 / 0.4
NPI_RULES = {"mch": {"weighted": True, "ot_lose": 0.4, "qwb_floor": 51.0}, "wch": {"weighted": False, "ot_lose": 1.0 / 3.0, "qwb_floor": 51.5}}


def _weights(site: str, res: str, ot: bool, season: int, unweighted: bool, kind: str = "npi",
             rules: dict | None = None) -> tuple[float, float]:
    """(win weight, loss weight) of one game for the team (site 'home' | 'away' | 'neutral'; res W | L | T).
    NPI: home/road weights; OT 0.6 / 0.4 with the weight on the regulation part only. RPI: home/road weights from
    2013-14; an OT win 2/3 of a win from 2021-22 (the regulation part weighted), a full win before."""
    weighted = not unweighted and site != "neutral" and (kind == "npi" or season >= 2014)
    if rules is not None and not rules.get("weighted", True):
        weighted = False

    def hw(win: bool) -> float:
        if not weighted:
            return 1.0
        if site == "home":
            return HOME_W if win else ROAD_W
        return ROAD_W if win else HOME_W
    if res == "T":
        return 0.5 * hw(True), 0.5 * hw(False)
    if ot:
        lose_share = ((rules or {}).get("ot_lose", 0.4) if kind == "npi" else (1.0 / 3.0 if season >= 2022 else 0.0))
        if lose_share > 0:
            extra = 1.0 - 2 * lose_share
            if res == "W":
                return lose_share * hw(True) + extra, lose_share * hw(False)
            return lose_share * hw(True), lose_share * hw(False) + extra
    return (hw(True), 0.0) if res == "W" else (0.0, hw(False))


def team_games(games: Iterable[dict], d1: set[str], through: str | None = None, include_ncaa: bool = False) -> dict[str, list]:
    """{team: [(opp, site, res, ot, conf_post, date)]} over played D-I v D-I games (exhibitions out)."""
    out: dict[str, list] = defaultdict(list)
    for g in games:
        if g.get("status") != "post" or g.get("res") not in ("W", "L", "T") or g.get("stype") == "exh":
            continue
        if g.get("stype") == "ncaa" and not include_ncaa:
            continue
        if through and str(g["date"])[:10] > through:
            continue
        h, a = g["home"], g["away"]
        if h not in d1 or a not in d1:
            continue
        ot = bool((g.get("ot") or 0) > 0) and g["res"] != "T"
        cp = g.get("stype") == "conf"
        neu = bool(g.get("neutral"))
        r = g["res"]
        out[h].append((a, "neutral" if neu else "home", r, ot, cp, str(g["date"])[:10]))
        out[a].append((h, "neutral" if neu else "away", {"W": "L", "L": "W", "T": "T"}[r], ot, cp, str(g["date"])[:10]))
    return out


# ── NPI ────────────────────────────────────────────────────────────────────────────────────────────────────

def npi(games: Iterable[dict], d1: set[str], season: int, through: str | None = None, iters: int = 200,
        qwb_floor: float | None = None, qwb_rate: float = 0.5, bad_win_min: float = 12.0, wp_w: float = 0.25,
        level: str = "mch") -> dict[str, dict]:
    """{team: {"npi", "rank", "wwp" (weighted win %), "qwb", "w", "l", "t", "n"}}"""
    tg = team_games(games, d1, through)
    teams = sorted(tg)
    rules = NPI_RULES.get(level, NPI_RULES["mch"])
    if qwb_floor is None:
        qwb_floor = rules["qwb_floor"]
    x = {t: 50.0 for t in teams}
    for _ in range(iters):
        new = {}
        for t in teams:
            rows = []
            ww = 0.0
            for (o, site, res, ot, cp, _d) in tg[t]:
                wW, wL = _weights(site, res, ot, season, cp, "npi", rules)
                xo = x.get(o, 50.0)
                W = 100.0 * wp_w + (1 - wp_w) * xo + (qwb_rate * (xo - qwb_floor) if xo > qwb_floor else 0.0)
                L = (1 - wp_w) * xo
                rows.append((wW, W, wL, L))
                ww += wW
            num = sum(a * b + c * d for a, b, c, d in rows)
            den = sum(a + c for a, b, c, d in rows)
            cur = num / den if den else 50.0
            # drop bad wins (with 12+ weighted wins) and good losses, then recompute
            for _k in range(3):
                num2 = den2 = 0.0
                for wW, W, wL, L in rows:
                    if wW and not (ww >= bad_win_min and W < cur):
                        num2 += wW * W
                        den2 += wW
                    if wL and not (L > cur):
                        num2 += wL * L
                        den2 += wL
                cur = num2 / den2 if den2 else cur
            new[t] = cur
        delta = max(abs(new[t] - x[t]) for t in teams) if teams else 0
        x = new
        if delta < 1e-7:
            break
    out = {}
    for t in teams:
        w = sum(1 for r in tg[t] if r[2] == "W")
        l_ = sum(1 for r in tg[t] if r[2] == "L")
        tt = sum(1 for r in tg[t] if r[2] == "T")
        wsum = lsum = 0.0
        for (o, site, res, ot, cp, _d) in tg[t]:
            a, b = _weights(site, res, ot, season, cp, "npi", rules)
            wsum += a
            lsum += b
        out[t] = {"npi": round(x[t], 3), "wwp": round(wsum / (wsum + lsum), 4) if wsum + lsum else None, "w": w, "l": l_,
                  "t": tt, "n": len(tg[t])}
    for i, t in enumerate(sorted(out, key=lambda k: -out[k]["npi"])):
        out[t]["rank"] = i + 1
    return out


# ── RPI and PairWise ───────────────────────────────────────────────────────────────────────────────────────

def _wp(rows: list, season: int, exclude: str | None = None) -> tuple[float, float]:
    """weighted wins, weighted games for a team's rows (optionally without games against `exclude`)."""
    ww = wl = 0.0
    for (o, site, res, ot, cp, _d) in rows:
        if exclude is not None and o == exclude:
            continue
        a, b = _weights(site, res, ot, season, False, "rpi")
        ww += a
        wl += b
    return ww, ww + wl


def rpi(games: Iterable[dict], d1: set[str], season: int, through: str | None = None, bad_wins: bool = True,
        qwb: bool | None = None) -> dict[str, dict]:
    tg = team_games(games, d1, through)
    teams = sorted(tg)
    qwb = season >= 2014 if qwb is None else qwb
    WP = {}
    for t in teams:
        w, n = _wp(tg[t], season)
        WP[t] = w / n if n else 0.0
    # OWP: opponents' winning percentage excluding games against t (unweighted in the opponent's own record? the
    # NCAA hockey RPI weights every component); averaged over t's games (each game counts)
    def owp(t: str) -> float:
        vals = []
        for (o, *_r) in tg[t]:
            w, n = _wp(tg.get(o, []), season, exclude=t)
            vals.append(w / n if n else 0.0)
        return sum(vals) / len(vals) if vals else 0.0
    OWP = {t: owp(t) for t in teams}
    OOWP = {}
    for t in teams:
        vals = [OWP.get(o, 0.0) for (o, *_r) in tg[t]]
        OOWP[t] = sum(vals) / len(vals) if vals else 0.0
    base = {t: 0.25 * WP[t] + 0.21 * OWP[t] + 0.54 * OOWP[t] for t in teams}
    R = dict(base)
    # bad wins: a win that lowers the RPI is removed (the game's own contribution, approximately: a win over an
    # opponent whose RPI contribution is below the team's)
    if bad_wins:
        for t in teams:
            rows = tg[t]
            keep = []
            for r in rows:
                o, site, res = r[0], r[1], r[2]
                if res == "W":
                    g_val = 0.25 * 1.0 + 0.21 * _owp_of(o, t, tg, season) + 0.54 * OWP.get(o, 0.0)
                    if g_val < base[t]:
                        continue
                keep.append(r)
            if len(keep) < len(rows):
                w, n = _wp(keep, season)
                wp = w / n if n else 0.0
                ow = [(_owp_of(o, t, tg, season)) for (o, *_r) in keep]
                oo = [OWP.get(o, 0.0) for (o, *_r) in keep]
                R[t] = 0.25 * wp + 0.21 * (sum(ow) / len(ow) if ow else 0) + 0.54 * (sum(oo) / len(oo) if oo else 0)
    if qwb:
        order = sorted(teams, key=lambda k: -R[k])
        rk = {t: i + 1 for i, t in enumerate(order)}
        for t in teams:
            bonus = 0.0
            for (o, site, res, ot, cp, _d) in tg[t]:
                if res == "W" and rk.get(o, 99) <= 20:
                    a, b = _weights(site, res, ot, season, False, "rpi")
                    bonus += (0.050 - 0.0025 * (rk[o] - 1)) * (a if a else 1.0)
            w, n = _wp(tg[t], season)
            R[t] = R[t] + (bonus / n if n else 0.0)
    out = {}
    for i, t in enumerate(sorted(teams, key=lambda k: -R[k])):
        w = sum(1 for r in tg[t] if r[2] == "W")
        l_ = sum(1 for r in tg[t] if r[2] == "L")
        tt = sum(1 for r in tg[t] if r[2] == "T")
        out[t] = {"rpi": round(R[t], 4), "rank": i + 1, "wp": round(WP[t], 4), "owp": round(OWP[t], 4),
                  "oowp": round(OOWP[t], 4), "w": w, "l": l_, "t": tt}
    return out


def _owp_of(o: str, t: str, tg: dict, season: int) -> float:
    w, n = _wp(tg.get(o, []), season, exclude=t)
    return w / n if n else 0.0


def _rec_pct(rows: list, opp: str | None = None, season: int = 2020) -> tuple[float, float, float]:
    w = l_ = tt = 0.0
    for (o, site, res, ot, cp, _d) in rows:
        if opp is not None and o != opp:
            continue
        if res == "W":
            w += 1
        elif res == "L":
            l_ += 1
        else:
            tt += 1
    return w, l_, tt


def pairwise(games: Iterable[dict], d1: set[str], season: int, through: str | None = None,
             r: dict | None = None) -> dict[str, dict]:
    """PairWise comparisons won (PCW) with RPI tie-breaks: {team: {"pwr", "pcw", "rpi", "rank"}}."""
    games = list(games)
    r = r or rpi(games, d1, season, through)
    tg = team_games(games, d1, through)
    teams = sorted(r)
    opps = {t: {o for (o, *_x) in tg[t]} for t in teams}
    tuc = {t for t in teams if r[t]["rpi"] >= 0.5} if season < 2014 else set(teams)

    def pct(w, l_, tt):
        n = w + l_ + tt
        return (w + 0.5 * tt) / n if n else None

    def cop(a: str, b: str) -> tuple[float | None, float | None]:
        common = (opps[a] & opps[b]) - {a, b}
        if not common:
            return None, None
        if season >= 2013:
            pa = [pct(*_rec_pct(tg[a], o)) for o in common]
            pb = [pct(*_rec_pct(tg[b], o)) for o in common]
            pa = [x for x in pa if x is not None]
            pb = [x for x in pb if x is not None]
            return (sum(pa) / len(pa) if pa else None), (sum(pb) / len(pb) if pb else None)
        wa = [_rec_pct(tg[a], o) for o in common]
        wb = [_rec_pct(tg[b], o) for o in common]
        sa = [sum(x) for x in zip(*wa)] if wa else [0, 0, 0]
        sb = [sum(x) for x in zip(*wb)] if wb else [0, 0, 0]
        return pct(*sa), pct(*sb)

    def vs_tuc(a: str) -> float | None:
        w = l_ = tt = 0.0
        for (o, site, res, ot, cp, _d) in tg[a]:
            if o in tuc:
                w += res == "W"
                l_ += res == "L"
                tt += res == "T"
        if w + l_ + tt < 10:
            return None
        return pct(w, l_, tt)

    pcw = defaultdict(int)
    for i, a in enumerate(teams):
        for b in teams[i + 1:]:
            pa = pb = 0
            if r[a]["rpi"] > r[b]["rpi"]:
                pa += 1
            elif r[b]["rpi"] > r[a]["rpi"]:
                pb += 1
            ca, cb = cop(a, b)
            if ca is not None and cb is not None:
                if ca > cb:
                    pa += 1
                elif cb > ca:
                    pb += 1
            hw, hl, _ht = _rec_pct(tg[a], b)
            pa += int(hw)
            pb += int(hl)
            if season < 2014:
                ta, tb = vs_tuc(a), vs_tuc(b)
                if ta is not None and tb is not None:
                    if ta > tb:
                        pa += 1
                    elif tb > ta:
                        pb += 1
            if pa > pb or (pa == pb and r[a]["rpi"] >= r[b]["rpi"]):
                pcw[a] += 1
            else:
                pcw[b] += 1
    order = sorted(teams, key=lambda t: (-pcw[t], -r[t]["rpi"]))
    return {t: {"pwr": i + 1, "pcw": pcw[t], "rpi": r[t]["rpi"], "rank": i + 1, "w": r[t]["w"], "l": r[t]["l"], "t": r[t]["t"]}
            for i, t in enumerate(order)}


# ── selection and bracket ──────────────────────────────────────────────────────────────────────────────────

def select_field(order: list[str], auto: dict[str, str], field: int = 16) -> list[str]:
    """`order`: teams by the selection ranking (NPI or PairWise); `auto`: {conf: champion}. Returns the field in
    selection-rank order (autobids included wherever they rank)."""
    autos = set(auto.values())
    n_at = field - len(autos)
    at = [t for t in order if t not in autos][:max(0, n_at)]
    chosen = autos | set(at)
    return [t for t in order if t in chosen] + [t for t in autos if t not in order]


def seed_bracket(field: list[str], conf_of: dict[str, str], hosts: dict[str, str] | None = None,
                 regions: list[str] | None = None) -> dict:
    """Men's 16-team bracket: bands of four, No. 1 seeds 1-4 placed into regions in order (a host stays home),
    serpentine 1v16 / 2v15 / ..., first-round same-conference games avoided by swapping within the band.
    Returns {"regions": {name: [(seed, team)]}, "pairs": {name: [(a, b), (c, d)]}, "overall": {team: n}}."""
    regions = regions or ["Region 1", "Region 2", "Region 3", "Region 4"]
    hosts = hosts or {}
    overall = {t: i + 1 for i, t in enumerate(field)}
    bands = [field[i:i + 4] for i in range(0, 16, 4)]
    # regional slot k gets overall seeds k (band1), 9-k... serpentine: region i: 1-seed band1[i], 2-seed band2[3-i]...
    reg = {regions[i]: {1: bands[0][i]} for i in range(4)}
    for b in range(1, 4):
        band = bands[b] if len(bands) > b else []
        ordered = band if b % 2 == 0 else list(reversed(band))
        for i, t in enumerate(ordered):
            if i < 4:
                reg[regions[i]][b + 1] = t
    # hosts: a host team must play in its own region (swap within its band)
    for rname, host in hosts.items():
        if rname not in reg or host not in overall:
            continue
        cur = next((rn for rn, s in reg.items() if host in s.values()), None)
        if cur and cur != rname:
            sd = next(k for k, v in reg[cur].items() if v == host)
            reg[cur][sd], reg[rname][sd] = reg[rname][sd], reg[cur][sd]
    # avoid first-round conference match-ups (1v4, 2v3 within a region): swap 3-seeds, then 2-seeds
    for _ in range(4):
        clash = False
        for rn, s in reg.items():
            for a, b in ((1, 4), (2, 3)):
                if s.get(a) and s.get(b) and conf_of.get(s[a]) and conf_of.get(s[a]) == conf_of.get(s[b]):
                    clash = True
                    swap_seed = 3 if a == 2 else 4
                    for rn2, s2 in reg.items():
                        if rn2 == rn or s2.get(swap_seed) is None:
                            continue
                        x, y = s[swap_seed], s2[swap_seed]
                        ok1 = conf_of.get(y) != conf_of.get(s[5 - swap_seed if swap_seed == 4 else 2])
                        partner2 = s2[1] if swap_seed == 4 else s2[2]
                        ok2 = conf_of.get(x) != conf_of.get(partner2)
                        if ok1 and ok2:
                            s[swap_seed], s2[swap_seed] = y, x
                            break
        if not clash:
            break
    return {"regions": {rn: sorted(s.items()) for rn, s in reg.items()},
            "pairs": {rn: [(s.get(1), s.get(4)), (s.get(2), s.get(3))] for rn, s in reg.items()},
            "overall": overall}
