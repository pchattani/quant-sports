"""
Season simulation (numpy, `n` = 20,000 by default): the rest of the regular season, conference standings and
championship games, the committee's ranking (committee.py proxy) and the College Football Playoff.

Per simulation every team draws a strength shift ~ N(0, se) (se = 15 / sqrt(3 + games played), so a season's
results stay correlated within a run), then every remaining game is decided by
margin = b_home * home + power_home - power_away + shifts + noise, noise ~ N(0, s) with
s^2 = sd^2 - 2 * mean(se^2) (sd = the game model's outcome spread). `power` = the blend's per-team linear
predictor (points v an average FBS team on a neutral field).

Conference standings: conference win percentage, then head-to-head wins among teams with the same percentage
(a mini-league), then power + shift (documented proxy for the remaining tiebreakers). Championship games: the
top two (or the division winners when the conference has divisions that season); conferences that play one
are those with a scheduled title game (real or placeholder slots in the store), neutral site.
Committee: resume features at the end of the conference-championship weekend scored by the fitted proxy,
plus Gumbel noise per team (pairwise orders then follow the fitted logistic).
CFP format by season (FORMATS): 4-team 2014-2023; 12-team with byes for the four highest-ranked conference
champions in 2024; straight seeding from 2025; 2026 on assumed = 2025 rules (unverified).
First round on the higher seed's campus (5v12, 6v11, 7v10, 8v9); quarterfinals, semifinals, final neutral.
Bowl eligibility: six wins in the regular season and conference title game (5-7 rules ignored).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import committee, data

FORMATS = {
    "bcs": {"teams": 2, "auto_bids": 0, "byes": 0, "rule": "BCS era: the top two of the BCS standings met in the title game "
            "(not simulated)", "verified": True, "seeding": None},
    "four": {"teams": 4, "auto_bids": 0, "byes": 0, "rule": "Top four of the committee ranking; semifinals 1 v 4 and 2 v 3 at "
             "bowl sites; neutral-site final", "verified": True, "seeding": "straight"},
    "twelve_2024": {"teams": 12, "auto_bids": 5, "byes": 4, "rule": "Five highest-ranked conference champions plus the seven "
                    "highest-ranked other teams; the four highest-ranked conference champions seeded 1-4 with byes, the "
                    "rest 5-12 by ranking; first round on campus (5v12, 6v11, 7v10, 8v9)", "verified": True,
                    "seeding": "champions_top4"},
    "twelve_2025": {"teams": 12, "auto_bids": 5, "byes": 4, "rule": "Five highest-ranked conference champions plus the seven "
                    "highest-ranked other teams, seeded 1-12 straight by ranking; byes for seeds 1-4; first round on "
                    "campus (5v12, 6v11, 7v10, 8v9)", "verified": True, "seeding": "straight"},
}


def cfp_format(season: int) -> dict:
    s = int(season)
    if s < 2014:
        f = dict(FORMATS["bcs"])
    elif s <= 2023:
        f = dict(FORMATS["four"])
    elif s == 2024:
        f = dict(FORMATS["twelve_2024"])
    else:
        f = dict(FORMATS["twelve_2025"])
        if s >= 2026:
            f["verified"] = False
            f["note"] = "2025 rules assumed (straight seeding, five conference champions); not verified for this season"
    f["season"] = s
    return f


def format_table(seasons: list[int]) -> list[dict]:
    out, last = [], None
    for s in sorted(seasons):
        f = cfp_format(s)
        k = (f["teams"], f.get("seeding"), f["verified"])
        if out and k == last:
            out[-1]["to"] = s
        else:
            out.append({"from": s, "to": s, "teams": f["teams"], "auto_bids": f["auto_bids"], "byes": f["byes"],
                        "rule": f["rule"], "verified": f["verified"]})
        last = k
    return out


# ── inputs ──────────────────────────────────────────────────────────────────

def power_table(season: int, pipe: dict, as_of: str | None = None) -> tuple[dict[str, float], dict[str, float], float]:
    """({team: power}, {team: points net rating}, b_home) from the season's final or as-of ratings and blend."""
    b = pipe["blends"].get(int(season)) or {}
    teams = pipe["teams"].get(int(season)) or []
    if as_of:
        snaps = pipe["snapshots"].get(int(season)) or {}
        kinds = {k: committee.snapshot_at(snaps, None, as_of, k) for k in ("pts", "epa", "sr")}
        if kinds["pts"] is None:
            kinds = {k: pipe["final"][int(season)].get(k) for k in ("pts", "epa", "sr")}
    else:
        kinds = {k: pipe["final"][int(season)].get(k) for k in ("pts", "epa", "sr")}
    net = {k: committee._net(v, teams) if v is not None else {} for k, v in kinds.items()}
    pts = net["pts"]
    full = b.get("full")
    if full and net.get("epa") and net.get("sr"):
        c = full["coef"]              # home, d_pts, d_epa, d_sr, d_rest
        power = {t: c[1] * pts[t] + c[2] * net["epa"].get(t, 0.0) + c[3] * net["sr"].get(t, 0.0) for t in pts}
        b_home = c[0]
    else:
        c = (b.get("pts") or {"coef": [2.5, 1.0, 0.0]})["coef"]
        power = {t: c[1] * pts[t] for t in pts}
        b_home = c[0]
    st = data.load_store(season)
    mem = [t for t, v in (st.get("teams") or {}).items() if v.get("member") and t in power]
    if mem:
        mu = float(np.mean([power[t] for t in mem]))
        mup = float(np.mean([pts[t] for t in mem]))
        power = {t: v - mu for t, v in power.items()}
        pts = {t: v - mup for t, v in pts.items()}
    return power, pts, float(b_home)


def ccg_conferences(st: dict, gf: pd.DataFrame) -> dict[str, tuple | None]:
    """{conference: (home, away, gid, final) | None} for conferences that play a title game this season."""
    tm = st.get("teams") or {}
    out: dict[str, tuple | None] = {}
    real = gf[(gf["stype"] == "conf") & gf["h_member"] & gf["a_member"]]
    for r in real.itertuples(index=False):
        c = (tm.get(r.home) or {}).get("conference")
        if c:
            out[c] = (r.home, r.away, r.gid, bool(r.final))
    placeholders = [g for g in (st.get("games") or {}).values()
                    if g.get("stype") == "conf" and not (data.real_team(g.get("home")) and data.real_team(g.get("away")))]
    ph = len(placeholders)
    # placeholder slots name their conference in the headline ("Big Ten Championship", "Conference USA ...")
    confs = st.get("conferences") or {}
    labels = []
    for c, v in confs.items():
        if c == data.INDEPENDENT:
            continue
        for x in (v.get("name"), (v.get("name") or "").replace(" Conference", ""), v.get("short")):
            if x and len(x) >= 3:
                labels.append((len(x), x.lower(), c))
    labels.sort(reverse=True)
    for g in placeholders:
        note = str(g.get("note") or "").lower()
        hit = next((c for _, x, c in labels if x in note), None)
        if hit and hit not in out:
            out[hit] = None
            ph -= 1
    if ph > 0:
        sizes: dict[str, int] = {}
        for t, v in tm.items():
            if v.get("member") and v.get("conference") and v.get("conference") != data.INDEPENDENT:
                sizes[v["conference"]] = sizes.get(v["conference"], 0) + 1
        for c, _ in sorted(sizes.items(), key=lambda kv: -kv[1]):
            if ph <= 0:
                break
            if c not in out:
                out[c] = None
                ph -= 1
    return out


# ── the simulation ──────────────────────────────────────────────────────────

def simulate(season: int, pipe: dict, comm: dict | None, *, n: int = 20000, as_of: str | None = None, seed: int = 2026,
             committee_model: dict | None = None) -> dict:
    rng = np.random.default_rng(seed)
    st = data.load_store(season)
    gf = data.games_frame(season, st)
    gf["as_"] = gf["as"]
    tm = st.get("teams") or {}
    power, pts, b_home = power_table(season, pipe, as_of)
    b = pipe["blends"].get(int(season)) or {}
    sd = float((b.get("sd") or {}).get("mid", 15.5))
    fbs = sorted(t for t, v in tm.items() if v.get("member"))
    allt = sorted(set(gf["home"]) | set(gf["away"]) | set(fbs))
    ix = {t: i for i, t in enumerate(allt)}
    T = len(allt)
    is_fbs = np.array([t in set(fbs) for t in allt])
    pw = np.array([power.get(t, -20.0) for t in allt])
    pr = np.array([pts.get(t, -20.0) for t in allt])
    conf = {t: (tm.get(t) or {}).get("conference") if (tm.get(t) or {}).get("member") else None for t in allt}
    reg = gf[gf["stype"].isin(["reg", "conf"])]
    if as_of:
        known = reg[reg["final"] & (reg["day"] < as_of)]
        rem = reg[~reg.index.isin(known.index)]
    else:
        known = reg[reg["final"]]
        rem = reg[~reg["final"]]
    ccg = ccg_conferences(st, gf)
    ccg_ids = {v[2] for v in ccg.values() if v}
    known_reg = known[~known["gid"].isin(ccg_ids)]
    rem_reg = rem[~rem["gid"].isin(ccg_ids)]
    gp = np.zeros(T)
    for h, a in zip(known_reg["home"], known_reg["away"]):
        gp[ix[h]] += 1
        gp[ix[a]] += 1
    se = 15.0 / np.sqrt(3.0 + gp)
    s_noise = float(np.sqrt(max(sd ** 2 - 2 * np.mean(se[is_fbs] ** 2), 10.0 ** 2)))
    shift = rng.standard_normal((n, T)) * se[None, :]
    W = np.zeros((n, T), np.int16)
    L = np.zeros((n, T), np.int16)
    CW = np.zeros((n, T), np.int16)
    CL = np.zeros((n, T), np.int16)
    # top-25 / top-60 by points rating (committee resume features), fixed for the run
    fbs_sorted = sorted(fbs, key=lambda t: -pts.get(t, -99))
    top25 = np.array([t in set(fbs_sorted[:25]) for t in allt])
    top60 = np.array([t in set(fbs_sorted[:60]) for t in allt])
    T25W = np.zeros((n, T), np.int16)
    BADL = np.zeros((n, T), np.int16)
    opp_r: dict[str, list[float]] = {t: [] for t in fbs}
    conf_games: dict[str, list[tuple[int, int, np.ndarray]]] = {}

    def record(hi, ai, hwin, is_conf):
        W[:, hi] += hwin
        L[:, hi] += ~hwin
        W[:, ai] += ~hwin
        L[:, ai] += hwin
        if is_conf:
            CW[:, hi] += hwin
            CL[:, hi] += ~hwin
            CW[:, ai] += ~hwin
            CL[:, ai] += hwin
        if top25[ai]:
            T25W[:, hi] += hwin
        if top25[hi]:
            T25W[:, ai] += ~hwin
        if not top60[ai]:
            BADL[:, hi] += ~hwin
        if not top60[hi]:
            BADL[:, ai] += hwin

    next_game: dict[str, dict] = {}
    next_win: dict[str, tuple] = {}              # gid -> (hi, ai, hwin, p_home, date): a team's next game, kept for stakes
    rem_opp: dict[str, list[float]] = {t: [] for t in fbs}     # remaining regular-season opponents' power ratings
    for df, sim_it in ((known_reg, False), (rem_reg, True)):
        for r in df.itertuples(index=False):
            hi, ai = ix[r.home], ix[r.away]
            cg = bool(r.conf_game) and conf.get(r.home) and conf.get(r.home) == conf.get(r.away) \
                and conf.get(r.home) != data.INDEPENDENT
            for t, o in ((r.home, r.away), (r.away, r.home)):
                if t in opp_r:
                    opp_r[t].append(pts.get(o, -20.0))
            if sim_it:
                m = (0.0 if r.neutral else b_home) + pw[hi] - pw[ai]
                hwin = (m + shift[:, hi] - shift[:, ai] + s_noise * rng.standard_normal(n)) > 0
                p_h = float(norm.cdf(m / sd))
                for t, o, p, home in ((r.home, r.away, p_h, not r.neutral), (r.away, r.home, 1 - p_h, False)):
                    if t not in next_game:
                        next_game[t] = {"game": r.gid, "opp": o, "p_win": round(p, 4), "date": r.date}
                        next_win.setdefault(r.gid, (hi, ai, hwin, p_h, r.date))
                    if t in rem_opp:
                        rem_opp[t].append(float(pw[ix[o]]))
            else:
                hwin = np.full(n, bool(r.hs > r.as_))
            record(hi, ai, hwin, cg)
            if cg:
                conf_games.setdefault(conf[r.home], []).append((hi, ai, hwin))
    # conference standings and title games
    members: dict[str, list[int]] = {}
    for t in fbs:
        c = conf.get(t)
        if c and c != data.INDEPENDENT:
            members.setdefault(c, []).append(ix[t])
    champ = np.full((n, T), False)
    in_ccg = np.full((n, T), False)
    for c, idx in members.items():
        idx = np.array(idx)
        g = CW[:, idx] + CL[:, idx]
        pct = np.where(g > 0, CW[:, idx] / np.maximum(g, 1), 0.0)
        h2h = np.zeros((n, len(idx)))
        loc = {t: k for k, t in enumerate(idx)}
        for hi, ai, hwin in conf_games.get(c, []):
            if hi in loc and ai in loc:
                tie = pct[:, loc[hi]] == pct[:, loc[ai]]
                h2h[:, loc[hi]] += tie & hwin
                h2h[:, loc[ai]] += tie & ~hwin
        key = pct * 1000.0 + h2h * 10.0 + (pw[idx][None, :] + shift[:, idx]) / 100.0
        divs = {}
        cdiv = ((st.get("conferences") or {}).get(c) or {}).get("divisions") or {}
        if cdiv:
            for k, t in enumerate(idx):
                d = (tm.get(allt[t]) or {}).get("division")
                if d:
                    divs.setdefault(d, []).append(k)
        if c in ccg:
            known_pair = ccg[c]
            if known_pair and known_pair[0] in ix and known_pair[1] in ix:
                a1, a2 = np.full(n, ix[known_pair[0]]), np.full(n, ix[known_pair[1]])
            elif len(divs) == 2:
                dl = list(divs.values())
                k1 = np.array(dl[0])[np.argmax(key[:, dl[0]], axis=1)]
                k2 = np.array(dl[1])[np.argmax(key[:, dl[1]], axis=1)]
                a1, a2 = idx[k1], idx[k2]
            else:
                o = np.argsort(-key, axis=1)
                a1, a2 = idx[o[:, 0]], idx[o[:, 1]]
            in_ccg[np.arange(n), a1] = True
            in_ccg[np.arange(n), a2] = True
            gr = gf[gf["gid"] == known_pair[2]].iloc[0] if known_pair else None
            if known_pair and known_pair[3] and (as_of is None or str(gr["day"]) < as_of):
                w1 = np.full(n, (gr["hs"] > gr["as"]))
            else:
                m = pw[a1] - pw[a2] + shift[np.arange(n), a1] - shift[np.arange(n), a2]
                w1 = (m + s_noise * rng.standard_normal(n)) > 0
            win = np.where(w1, a1, a2)
            lose = np.where(w1, a2, a1)
            champ[np.arange(n), win] = True
            W[np.arange(n), win] += 1
            L[np.arange(n), lose] += 1
            T25W[np.arange(n), win] += top25[lose]
            BADL[np.arange(n), lose] += ~top60[win]
        else:
            o = np.argmax(key, axis=1)
            champ[np.arange(n), idx[o]] = True
    # committee ranking at selection
    fmt = cfp_format(season)
    model = committee_model or (comm or {}).get("model")
    F = {"wins": W.astype(float), "losses": L.astype(float), "rating": pr[None, :] + shift,
         "sos": np.array([np.mean(opp_r[t]) if opp_r.get(t) else -20.0 for t in allt])[None, :].repeat(n, 0),
         "top25_wins": T25W.astype(float), "bad_losses": BADL.astype(float), "conf_champ": champ.astype(float),
         "power_conf": np.array([float(data.is_power(conf.get(t), season, t)) for t in allt])[None, :].repeat(n, 0)}
    if model is not None and np.any(model["w"]):
        sc = sum(((F[f] - model["mu"][k]) / model["sd"][k]) * model["w"][k] for k, f in enumerate(committee.FEATURES))
    else:
        sc = F["rating"] + 3.0 * (F["wins"] - F["losses"])
    sc = sc + rng.gumbel(size=(n, T))
    sc[:, ~is_fbs] = -1e9
    n_field = fmt["teams"] if fmt["teams"] in (4, 12) else 0
    seed_of = np.zeros((n, T), np.int8)
    if n_field == 4:
        order = np.argsort(-sc, axis=1)[:, :4]
        for k in range(4):
            seed_of[np.arange(n), order[:, k]] = k + 1
    elif n_field == 12:
        csc = np.where(champ, sc, -1e9)
        corder = np.argsort(-csc, axis=1)
        auto = np.zeros((n, T), bool)
        for k in range(fmt["auto_bids"]):
            auto[np.arange(n), corder[:, k]] = True
        sel = sc + np.where(auto, 1e6, 0.0)
        field = np.argsort(-sel, axis=1)[:, :12]
        fsc = np.take_along_axis(sc, field, axis=1)
        if fmt.get("seeding") == "champions_top4":
            top4c = np.zeros((n, T), bool)
            for k in range(4):
                top4c[np.arange(n), corder[:, k]] = True
            bonus = np.take_along_axis(top4c, field, axis=1) * 1e6
            o = np.argsort(-(fsc + bonus), axis=1)
        else:
            o = np.argsort(-fsc, axis=1)
        seeded = np.take_along_axis(field, o, axis=1)
        for k in range(12):
            seed_of[np.arange(n), seeded[:, k]] = k + 1
        auto_in = auto
    # bracket
    reach = {k: np.zeros((n, T), bool) for k in ("qf", "sf", "final", "title")}
    if n_field:
        by_seed = np.zeros((n, n_field + 1), int)
        for k in range(1, n_field + 1):
            by_seed[:, k] = np.argmax(seed_of == k, axis=1)

        def play(a, bb, home_a):
            m = np.where(home_a, b_home, 0.0) + pw[a] - pw[bb] + shift[np.arange(n), a] - shift[np.arange(n), bb]
            return np.where((m + s_noise * rng.standard_normal(n)) > 0, a, bb)

        if n_field == 12:
            r1 = {5: play(by_seed[:, 5], by_seed[:, 12], True), 6: play(by_seed[:, 6], by_seed[:, 11], True),
                  7: play(by_seed[:, 7], by_seed[:, 10], True), 8: play(by_seed[:, 8], by_seed[:, 9], True)}
            for k in range(1, 5):
                reach["qf"][np.arange(n), by_seed[:, k]] = True
            for k, w in r1.items():
                reach["qf"][np.arange(n), w] = True
            q = {1: play(by_seed[:, 1], r1[8], False), 2: play(by_seed[:, 2], r1[7], False),
                 3: play(by_seed[:, 3], r1[6], False), 4: play(by_seed[:, 4], r1[5], False)}
            for w in q.values():
                reach["sf"][np.arange(n), w] = True
            f1, f2 = play(q[1], q[4], False), play(q[2], q[3], False)
        else:
            for k in range(1, 5):
                reach["sf"][np.arange(n), by_seed[:, k]] = True
            f1, f2 = play(by_seed[:, 1], by_seed[:, 4], False), play(by_seed[:, 2], by_seed[:, 3], False)
        reach["final"][np.arange(n), f1] = True
        reach["final"][np.arange(n), f2] = True
        ch = play(f1, f2, False)
        reach["title"][np.arange(n), ch] = True
    # outputs
    teams_out = {}
    in_cfp = seed_of > 0
    rank_pos = np.argsort(np.argsort(-sc, axis=1), axis=1) + 1
    for t in fbs:
        i = ix[t]
        wd = np.bincount(W[:, i], minlength=16)[:16] / n
        sd_ = {str(k): round(float(np.mean(seed_of[:, i] == k)), 4) for k in range(1, n_field + 1)
               if np.mean(seed_of[:, i] == k) >= 0.0005}
        teams_out[t] = {
            "exp_w": round(float(W[:, i].mean()), 2), "exp_l": round(float(L[:, i].mean()), 2),
            "w_dist": [round(float(x), 4) for x in wd],
            "p_bowl": round(float(np.mean(W[:, i] >= 6)), 4),
            "p_conf_game": round(float(in_ccg[:, i].mean()), 4), "p_conf": round(float(champ[:, i].mean()), 4),
            "p_cfp": round(float(in_cfp[:, i].mean()), 4),
            "p_bye": round(float(np.mean((seed_of[:, i] >= 1) & (seed_of[:, i] <= 4))), 4) if n_field == 12 else 0.0,
            "p_round": {k: round(float(reach[k][:, i].mean()), 4) for k in ("qf", "sf", "final", "title")},
            "seed_dist": sd_, "p_title": round(float(reach["title"][:, i].mean()), 4),
            "p_top12": round(float(np.mean(rank_pos[:, i] <= 12)), 4),
            "p_auto": round(float(np.mean(auto_in[:, i] & in_cfp[:, i])), 4) if n_field == 12 else 0.0,
            "seed_mean": round(float(seed_of[in_cfp[:, i], i].mean()), 2) if in_cfp[:, i].any() else None,
            "rank_mean": round(float(rank_pos[:, i].mean()), 2),
            "next": ({k: v for k, v in next_game[t].items() if k != "date"} if t in next_game else None),
            "n_rem": len(rem_opp.get(t) or []),
            "sos_rem": round(float(np.mean(rem_opp[t])), 2) if rem_opp.get(t) else None}
    conf_out = {}
    for c, idx in members.items():
        rows = [{"team": allt[i], "p_appear": round(float(in_ccg[:, i].mean()), 4), "p_win": round(float(champ[:, i].mean()), 4)}
                for i in idx]
        conf_out[c] = sorted(rows, key=lambda r: (-r["p_win"], -r["p_appear"]))
    stakes = game_stakes(next_win, {"cfp": in_cfp, "conf": champ, "title": reach["title"]}, allt, set(fbs))
    return {"n_sims": n, "as_of": as_of, "format": fmt, "teams": teams_out, "conf": conf_out, "power": power, "pts": pts,
            "stakes": stakes,
            "sd": sd, "noise_sd": round(s_noise, 2), "b_home": b_home, "ccg": {c: (list(v[:2]) if v else None) for c, v in ccg.items()},
            "notes": [
                "Remaining regular-season games simulated from the blend ratings with correlated team strength draws.",
                "Conference tiebreakers: win percentage, head-to-head among tied teams, then rating (proxy).",
                "Committee ranking: resume proxy fitted on 2014-2025 CFP rankings, with noise.",
                "CFP format: " + fmt["rule"] + ("" if fmt.get("verified") else " (" + fmt.get("note", "unverified") + ")"),
                "Bowl eligibility = 6+ wins including a conference title game; bowl games are not simulated."]}


def game_stakes(next_win: dict, outcomes: dict, allt: list, members: set, *, keep: int = 25, others: int = 3,
                min_n: int = 30) -> list[dict]:
    """What rides on each team's next game, from the same simulated seasons (conditional, not a re-run).

    next_win: gid -> (home idx, away idx, home-win bool array over sims, our pre-game home chance, date).
    outcomes: metric -> (n_sims, T) bool array (cfp: in the field, conf: conference champion, title: national title).
    Per game: each side's chance of each outcome if it wins and if it loses; "swing", the CFP places we expect the
    result to move: every team's expected absolute change in its CFP chance (2 p q |change if the home side wins v
    loses|, p the home side's win share in the sims), summed and halved; and the three other teams whose CFP chance
    moves most. Sampling noise inflates a sum of absolute changes, so a team counts only when its change is more than
    3 standard errors. Only games with an FBS member, and only where each result happens in at least min_n
    simulations (and 2% of them). Largest swing first, at most `keep` games."""
    rows = []
    for gid, (hi, ai, hwin, p_h, day) in next_win.items():
        if allt[hi] not in members and allt[ai] not in members:
            continue
        nw = int(hwin.sum())
        nl = len(hwin) - nw
        if min(nw, nl) < max(min_n, 0.02 * len(hwin)):
            continue
        pw_ = nw / len(hwin)
        row = {"game": str(gid), "home": allt[hi], "away": allt[ai], "p_home": round(float(p_h), 4), "date": day}
        for m, arr in outcomes.items():
            a_w, a_l = arr[hwin].mean(0), arr[~hwin].mean(0)
            row[m] = {"home": [round(float(a_w[hi]), 4), round(float(a_l[hi]), 4)],
                      "away": [round(float(a_l[ai]), 4), round(float(a_w[ai]), 4)]}
            if m == "cfp":
                d = a_w - a_l
                se = np.sqrt(a_w * (1 - a_w) / nw + a_l * (1 - a_l) / nl)
                real = np.abs(d) > 3.0 * se
                real[[hi, ai]] = True
                row["swing"] = round(float(pw_ * (1 - pw_) * np.abs(np.where(real, d, 0.0)).sum()), 4)
                mask = real.copy()
                mask[[hi, ai]] = False
                idx = [int(i) for i in np.argsort(-np.abs(np.where(mask, d, 0.0)))[:others] if mask[i] and abs(d[i]) >= 0.02]
                row["others"] = [{"team": allt[i], "d": round(float(d[i]), 4)} for i in idx]
        rows.append(row)
    rows.sort(key=lambda r: -r.get("swing", 0.0))
    return rows[:keep]


def actual_field(season: int, st: dict | None = None) -> dict:
    """Teams and seeds of the actual CFP field of a season (from CFP games), champion if played."""
    st = st or data.load_store(season)
    games = [g for g in (st.get("games") or {}).values() if g.get("stype") == "cfp"
             and data.real_team(g.get("home")) and data.real_team(g.get("away"))]
    seeds: dict[str, int] = {}
    for g in games:
        for side in ("home", "away"):
            s = (g.get("seeds") or {}).get(side)
            if s:
                seeds[str(g[side])] = int(s)
    teams = set()
    for g in games:
        teams.add(str(g["home"]))
        teams.add(str(g["away"]))
    final = next((g for g in games if g.get("round") == "National Championship" and g.get("status") == "post"), None)
    champ = None
    if final and final.get("hs") is not None:
        champ = str(final["home"] if final["hs"] > final["as"] else final["away"])
    return {"teams": sorted(teams), "seeds": seeds, "champion": champ}


def backtest(pipe: dict, comm: dict, seasons: list[int] | None = None, n: int = 4000) -> dict:
    """Our CFP field before championship weekend (as of the first conference title game's day, ratings walk-forward,
    committee proxy fitted without the season) against the actual field, 2014 on."""
    seasons = [s for s in (seasons or pipe["seasons"]) if committee.FIRST <= s < pipe["current"]]
    tabs = None
    rows = []
    for s in seasons:
        st = data.load_store(s)
        gf = data.games_frame(s, st)
        cg = gf[gf["stype"] == "conf"]
        act = actual_field(s, st)
        if not len(cg) or not act["teams"]:
            continue
        as_of = str(cg["day"].min())
        if tabs is None:
            tabs = committee.ranking_tables(pipe, [x for x in pipe["seasons"] if committee.FIRST <= x < pipe["current"]])
        m = committee.fit([t for t in tabs if t["season"] != s])
        r = simulate(s, pipe, None, n=n, as_of=as_of, committee_model=m, seed=s)
        pin = {t: v["p_cfp"] for t, v in r["teams"].items()}
        k = r["format"]["teams"]
        pred = [t for t, _ in sorted(pin.items(), key=lambda kv: -kv[1])[:k]]
        y = np.array([1.0 if t in act["teams"] else 0.0 for t in pin])
        p = np.array(list(pin.values()))
        row = {"season": s, "field": k, "as_of": as_of, "hits": len(set(pred) & set(act["teams"])),
               "brier_in": round(float(np.mean((p - y) ** 2)), 5),
               "mean_p_actual": round(float(np.mean([pin.get(t, 0.0) for t in act["teams"]])), 4),
               "missed": [t for t in act["teams"] if t not in pred], "wrong": [t for t in pred if t not in act["teams"]]}
        if act["champion"]:
            pc = r["teams"].get(act["champion"], {}).get("p_title", 0.0)
            row["p_title_champion"] = pc
            row["logloss_title"] = round(float(-np.log(max(pc, 1e-4))), 4)
        rows.append(row)
    if not rows:
        return {"n_seasons": 0, "per_season": []}
    hits = sum(r["hits"] for r in rows)
    tot = sum(r["field"] for r in rows)
    return {"n_seasons": len(rows), "field_hit_rate": round(hits / tot, 4), "hits": hits, "slots": tot,
            "brier_in": round(float(np.mean([r["brier_in"] for r in rows])), 5),
            "mean_p_actual": round(float(np.mean([r["mean_p_actual"] for r in rows])), 4),
            "title_logloss": round(float(np.mean([r["logloss_title"] for r in rows if "logloss_title" in r])), 4)
            if any("logloss_title" in r for r in rows) else None,
            "per_season": rows,
            "method": "As of the first conference-championship day; walk-forward ratings; committee proxy fitted without the "
                      "season (leave one season out); conference title games simulated; field = top N by P(in)."}
