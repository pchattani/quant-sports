"""
Synthetic NHL seasons with planted truth, for builder C's tests and for running the models before real data exists.

`league(seasons, seed)` -> {"truth": {season: {"teams": {t: units}, "goalies": {q: val}, "starters"}},
"tg": {season: team-game DataFrame (the _cdata.TG_COLS table)}, "stores": {season: store.json-shaped dict},
"games": games frame}.

Truth per team (xG per 60 above the league unless noted): ev_off, ev_def ~ N(0, 0.22) (def + = worse), pp, pk ~
N(0, 0.8), draw, take ~ N(0, 0.4) PP minutes, fin ~ N(0, 0.03); a starter (val ~ N(0, 0.05) goals allowed per xG
above average) playing 75 % of games and a backup (val + 0.04). Values carry 0.6 into the next season plus noise.
Each game: means from team_strength.expected_goals on the truth (the actual starters), x exp(+0.05) for the home
side and the schedule effects exp(-0.07) for a back-to-back side; scores from game.simulate_scores. Team-game rows:
5v5 minutes ~ N(48.5, 2), PP minutes ~ Gamma around the truth, realised xG ~ Gamma(12, mean) around each side's
true rate (score/venue adjustment is not simulated), unblocked attempts ~ Poisson(42 + 12 x xG edge), goals split
5v5 / PP in proportion to xG. Schedules: every pair twice (one home each), division rivals twice more, conference
rivals in the other division once more (84 games), each placed on the first free day at or after a random day
0-175 from 7 October (no team twice a day, at most nine games a day).
Closing lines: de-vigged truth probability with 4.5 % overround (American odds), puck line -1.5 / +1.5 and total 6.0.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _cdata as D
from oddsmarkets.nhl.models import game as GM
from oddsmarkets.nhl.models import team_strength as TS

LEAGUE = {"ev_xg60": 2.45, "ff60": 42.0, "pp_xg60": 6.6, "pp_min": 4.6, "sh_g60": 0.75, "conv": 1.0, "goals_pg": 2.95}
HOME = 0.05
B2B = -0.07


def alignment() -> dict[str, list[str]]:
    return D._alignment(2026)


def schedule(season: int, rng: np.random.Generator) -> list[dict]:
    al = alignment()
    div_of = {t: d for d, v in al.items() for t in v}
    conf = {d: D._conf_of_div(d, 2026) for d in al}
    teams = sorted(div_of)
    games = []
    for i, a in enumerate(teams):
        for b in teams[i + 1:]:
            games += [(a, b), (b, a)]
            if div_of[a] == div_of[b]:
                games += [(a, b), (b, a)]
            elif conf[div_of[a]] == conf[div_of[b]]:
                games.append((a, b) if (teams.index(a) + teams.index(b)) % 2 == 0 else (b, a))
    order = rng.permutation(len(games))
    busy: dict[int, set] = {}
    out = []
    start = pd.Timestamp(f"{D.start_year(season)}-10-07")
    for k in order:
        h, a = games[k]
        d = int(rng.integers(0, 176))
        while h in busy.get(d, set()) or a in busy.get(d, set()) or len(busy.get(d, set())) >= 18:
            d += 1
        busy.setdefault(d, set()).update((h, a))
        out.append({"home": h, "away": a, "day": d, "date": start + pd.Timedelta(days=d)})
    out.sort(key=lambda g: (g["day"], g["home"]))
    return out


def _american(p: float) -> float:
    p = min(max(p, 0.02), 0.98)
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def truth_rd(T: dict) -> dict:
    teams = {t: {**{u: v[u] for u in ("ev_off", "ev_def", "pp", "pk", "draw", "take", "fin")}, "goalie": v["starter"],
                 "g_att": 0.0, "g_def": 0.0} for t, v in T["teams"].items()}
    return {"mode": "xg", "league": dict(LEAGUE), "teams": teams, "goalies": {q: {"val": v} for q, v in T["goalies"].items()},
            "starters": {t: v["starter"] for t, v in T["teams"].items()}}


def league(seasons=(20252026, 20262027), seed: int = 7, played_through: str | None = None, sd_ev: float = 0.22,
           with_lines: bool = True, sd_goalie: float = 0.05) -> dict:
    rng = np.random.default_rng(seed)
    al = alignment()
    teams = sorted(t for v in al.values() for t in v)
    truth, tgs, stores, frames = {}, {}, {}, []
    prev = None
    gp = GM.params({"theta": 0.08, "tie_k": 0.85, "k_pull": 2.2, "r_en": 0.22})
    qn = 0
    for s in seasons:
        Tt, Gl = {}, {}
        for t in teams:
            pv = (prev or {}).get("teams", {}).get(t)

            def draw(key, sd):
                return (0.6 * pv[key] if pv else 0.0) + rng.normal(0, sd * (0.8 if pv else 1.0))
            if pv and rng.random() > 0.2:
                st, bk = pv["starter"], pv["backup"]
                Gl[st] = 0.6 * prev["goalies"][st] + rng.normal(0, 0.03)
                Gl[bk] = Gl[st] + 0.04 + rng.normal(0, 0.02)
            else:
                qn += 2
                st, bk = f"G{qn - 1:04d}", f"G{qn:04d}"
                Gl[st] = rng.normal(0, sd_goalie)
                Gl[bk] = Gl[st] + 0.04 + rng.normal(0, 0.02)
            Tt[t] = {"ev_off": draw("ev_off", sd_ev), "ev_def": draw("ev_def", sd_ev), "pp": draw("pp", 0.8),
                     "pk": draw("pk", 0.8), "draw": draw("draw", 0.4), "take": draw("take", 0.4), "fin": draw("fin", 0.03),
                     "starter": st, "backup": bk}
        Ts = {"teams": Tt, "goalies": Gl}
        truth[s] = Ts
        prev = Ts
        rd = truth_rd(Ts)
        sched = schedule(s, rng)
        n = len(sched)
        hh = np.array([g["home"] for g in sched])
        aa = np.array([g["away"] for g in sched])
        qh = np.where(rng.random(n) < 0.75, [Tt[t]["starter"] for t in hh], [Tt[t]["backup"] for t in hh])
        qa = np.where(rng.random(n) < 0.75, [Tt[t]["starter"] for t in aa], [Tt[t]["backup"] for t in aa])
        mu = np.array([TS.expected_goals(rd, hh[i], aa[i], qh[i], qa[i], detail=True) for i in range(n)], dtype=object)
        mh = np.array([m[0] for m in mu], float)
        ma = np.array([m[1] for m in mu], float)
        parts = [m[2] for m in mu]
        # back-to-backs
        last_day: dict[str, pd.Timestamp] = {}
        b2b_h, b2b_a = np.zeros(n), np.zeros(n)
        for i, g in enumerate(sched):
            for t, arr in ((g["home"], b2b_h), (g["away"], b2b_a)):
                if t in last_day and (g["date"] - last_day[t]).days == 1:
                    arr[i] = 1.0
                last_day[t] = g["date"]
        mh_t = mh * math.exp(HOME / 2) * np.exp(B2B * (b2b_h - b2b_a) / 2)
        ma_t = ma * math.exp(-HOME / 2) * np.exp(-B2B * (b2b_h - b2b_a) / 2)
        sim = GM.simulate_scores(mh_t, ma_t, rng, gp, False, s)
        o = GM.outcome_probs(mh_t, ma_t, gp, False, s) if with_lines else None
        cut = pd.Timestamp(played_through) if (played_through and s == seasons[-1]) else None
        games, rows = {}, []
        for i, g in enumerate(sched):
            gid = f"{D.start_year(s)}02{i + 1:04d}"
            played = cut is None or g["date"] <= cut
            lines = None
            if with_lines:
                ph = float(o["p_home"][i])
                vig = 1.045
                lines = {"ml": {"home": _american(min(ph * vig, 0.97)), "away": _american(min((1 - ph) * vig, 0.97))},
                         "puck_line": {"home": -1.5 if ph >= 0.5 else 1.5}, "total": {"line": 6.0, "over": -110, "under": -110},
                         "provider": "synthetic"}
            rec = {"game_id": gid, "date": g["date"].strftime("%Y-%m-%d"), "start": g["date"].strftime("%Y-%m-%dT23:00:00Z"),
                   "type": 2, "home": hh[i], "away": aa[i], "status": "final" if played else "scheduled",
                   "hs": int(sim["hs"][i]) if played else None, "as": int(sim["as_"][i]) if played else None,
                   "period": (4 if sim["ot"][i] else 3) if played else None, "ot": bool(sim["ot"][i]) if played else False,
                   "so": bool(sim["so"][i]) if played else False, "venue": f"{hh[i]} Arena", "lines": lines,
                   "goalies": {"home": qh[i], "away": qa[i]}, "attendance": None}
            games[gid] = rec
            if not played:
                continue
            pr = parts[i]
            so_adj_h = int(sim["so"][i] and sim["hs"][i] > sim["as_"][i])
            so_adj_a = int(sim["so"][i] and sim["as_"][i] > sim["hs"][i])
            gfh, gfa = int(sim["hs"][i]) - so_adj_h, int(sim["as_"][i]) - so_adj_a
            evt = float(np.clip(rng.normal(48.5, 2.0), 40, 56))
            pph = float(rng.gamma(6.0, pr["ppm_h"] / 6.0))
            ppa = float(rng.gamma(6.0, pr["ppm_a"] / 6.0))
            for side in ("h", "a"):
                o_ = "a" if side == "h" else "h"
                evx = float(rng.gamma(12.0, pr[f"ev_{side}"] * evt / 60.0 / 12.0))
                ppx = float(rng.gamma(8.0, pr[f"pp_{side}"] * (pph if side == "h" else ppa) / 60.0 / 8.0)) if (pph if side == "h" else ppa) > 0 else 0.0
                gf = gfh if side == "h" else gfa
                share_pp = ppx / max(evx + ppx, 1e-6)
                ppg = int(rng.binomial(gf, min(share_pp, 0.9)))
                rows.append({"_side": side, "_opp": o_, "game_id": gid, "season": s, "date": g["date"],
                             "team": hh[i] if side == "h" else aa[i], "opp": aa[i] if side == "h" else hh[i],
                             "home": 1.0 if side == "h" else 0.0, "gf": float(gf), "ga": float(gfa if side == "h" else gfh),
                             "ev_toi": evt, "ev_xgf": evx, "ev_ff": float(rng.poisson(max(42.0 + 12.0 * (pr[f"ev_{side}"] - 2.45), 5) * evt / 60)),
                             "ev_gf": float(gf - ppg), "pp_toi": pph if side == "h" else ppa, "pp_xgf": ppx, "pp_gf": float(ppg),
                             "xgf_all": evx + ppx, "goalie": qh[i] if side == "h" else qa[i], "en_gf": 0.0})
        tg = pd.DataFrame(rows)
        if not tg.empty:
            opp = tg.set_index(["game_id", "team"])
            k = pd.MultiIndex.from_arrays([tg["game_id"], tg["opp"]])
            for a_, b_ in (("ev_xga", "ev_xgf"), ("ev_fa", "ev_ff"), ("ev_ga", "ev_gf"), ("pk_toi", "pp_toi"),
                           ("pk_xga", "pp_xgf"), ("pk_ga", "pp_gf"), ("xga_all", "xgf_all"), ("en_ga", "en_gf")):
                tg[a_] = opp[b_].reindex(k).to_numpy()
            tg["ga_all"] = tg["ga"]
            tg["src"] = "events"
            tg = tg[D.TG_COLS].sort_values(["date", "game_id", "home"], ascending=[True, True, False]).reset_index(drop=True)
        tgs[s] = tg
        tinfo = D.teams_for(s)
        stores[s] = {"season": s, "teams": {t: {"abbr": t, "name": tinfo.get(t, {}).get("name", t), "division": div,
                                                "conference": D._conf_of_div(div, 2026)}
                                            for div, v in al.items() for t in v},
                     "games": games, "meta": {"synthetic": True}}
        frames.append(D.games_from_store(stores[s], s))
    G = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return {"truth": truth, "tg": tgs, "stores": stores, "games": G}


def tg_getter(lg: dict):
    """A `tg_of(season)` for the models from a synthetic league (empty frame for other seasons)."""
    def f(season):
        df = lg["tg"].get(int(season))
        return df.copy() if df is not None else pd.DataFrame(columns=D.TG_COLS)
    return f
