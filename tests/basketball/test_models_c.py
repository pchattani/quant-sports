"""Builder C models on synthetic data with planted truth: xPTS (shots), RAPM / box impact / HPM /
projections / roster impact (impact), win probability and WPA (winprob), award races (awards).
A smoke test runs WPA, xPTS and RAPM on builder A's recorded ESPN fixtures when they parse."""
from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.basketball.models import _io, award_winners, awards, impact, shots, winprob

FIX = Path(__file__).parent / "fixtures"


# ============================================================================ generators

def true_p(d):
    """Planted make-probability curve against distance (ft)."""
    d = np.asarray(d, float)
    return 0.62 * np.exp(-d / 5.0) + 0.38 - 0.004 * d


def synth_shots(n=60000, seed=0, assisted_bonus=0.0):
    rng = np.random.default_rng(seed)
    d = np.concatenate([rng.exponential(2.5, n // 3), rng.uniform(4, 22, n // 3), rng.uniform(23.75, 27, n - 2 * (n // 3))])
    ang = rng.uniform(-85, 85, n)
    x, y = d * np.sin(np.radians(ang)), d * np.cos(np.radians(ang))
    zone = np.where(d < 4, "rim", np.where(d < 14, "paint", np.where(d < 23.75, "mid", "ab3")))
    val = np.where(d >= 23.75, 3, 2)
    assisted = (rng.random(n) < 0.5).astype(int)
    logit = np.log(true_p(d) / (1 - true_p(d))) + assisted_bonus * assisted
    shooter = rng.integers(0, 300, n)
    skill = np.where(shooter < 10, 0.6, 0.0)           # ten planted shot-makers
    p = 1 / (1 + np.exp(-(logit + skill)))
    made = (rng.random(n) < p).astype(int)
    game = np.arange(n) // 160
    team = np.where(np.arange(n) % 2 == 0, (game * 2) % 30, (game * 2 + 1) % 30)
    return pd.DataFrame({"game_id": game.astype(str), "t": rng.uniform(0, 2880, n), "period": rng.integers(1, 5, n),
                         "team": team.astype(str), "shooter": shooter.astype(str), "x_ft": x, "y_ft": y, "dist_ft": d,
                         "angle_deg": ang, "zone": zone, "shot_type": "jumper", "value": val, "made": made,
                         "assisted": assisted, "assister": None, "blocked": 0, "putback": 0, "transition": 0,
                         "margin_before": rng.integers(-15, 16, n), "clutch": 0})


def synth_stints(n_teams=10, per_team=10, n_games=3000, per_game=40, seed=0, sd_o=3.0, sd_d=2.0, hca=3.0, cameo=None):
    """Stints.json-shaped rows with planted O and D (points per 100) and home edge `hca` (net, per 100).
    `cameo`: a player id appearing in only a few stints (for shrinkage)."""
    rng = np.random.default_rng(seed)
    P = n_teams * per_team
    o, d = rng.normal(0, sd_o, P), rng.normal(0, sd_d, P)
    pid = [f"p{i}" for i in range(P)]
    mw = np.linspace(2.0, 0.6, per_team)
    mw /= mw.sum()
    rows = []
    for g in range(n_games):
        h, a = rng.choice(n_teams, 2, replace=False)
        for s in range(per_game):
            hp = h * per_team + rng.choice(per_team, 5, replace=False, p=mw)
            ap = a * per_team + rng.choice(per_team, 5, replace=False, p=mw)
            ph = float(rng.poisson(2.5) + 1)
            pa = ph
            mh = 1.12 + (o[hp].sum() - d[ap].sum() + hca / 2) / 100
            ma = 1.12 + (o[ap].sum() - d[hp].sum() - hca / 2) / 100
            sh = rng.normal(mh * ph, 1.1 * np.sqrt(ph))
            sa = rng.normal(ma * pa, 1.1 * np.sqrt(pa))
            names_h = [pid[i] for i in hp]
            if cameo and g < 3 and s == 0:
                names_h[0] = cameo
            rows.append([f"g{g}", s * 70.0, s * 70.0 + 70, *names_h, *[pid[i] for i in ap], ph, pa, sh, sa])
    return {"cols": _io.STINT_COLS, "rows": rows}, dict(zip(pid, o)), dict(zip(pid, d))


def synth_states(n_games=2000, seed=0):
    """Game-state paths from a possession-level random walk with a pregame edge; one state per possession."""
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_games):
        s = rng.normal(0, 6)
        m, tau, poss = 0, 2880.0, int(rng.choice([1, -1]))
        st = []
        while True:
            tau -= rng.uniform(6, 22)
            if tau <= 0:
                break
            pr = 0.5 + poss * s / 200.0
            pts = rng.choice([0, 2, 3], p=[1 - pr, pr * 0.72, pr * 0.28])
            m += poss * pts
            poss = -poss
            st.append((m, tau, min(4, int((2880 - tau) // 720) + 1), poss))
        while m == 0:
            m = int(rng.choice([-3, 3]))
        hw = int(m > 0)
        rows += [{"game_id": f"g{g}", "margin": a, "t_left": b, "period": c, "poss": e, "exp_margin": s, "league": "nba",
                  "home_win": hw} for a, b, c, e in st]
    return pd.DataFrame(rows)


def synth_pbp_game(seed=0, gid="900", home="1", away="2", H=None, A=None):
    """A compact-pbp game (contract play rows) and its GAME record with a box (for team lookup)."""
    rng = np.random.default_rng(seed)
    H = H or [f"h{i}" for i in range(8)]
    A = A or [f"a{i}" for i in range(8)]
    plays, seq, hs, as_ = [], 0, 0, 0
    team = {"H": home, "A": away}
    off = "H"
    for per in range(1, 5):
        clock = 720.0
        while True:
            clock -= rng.uniform(8, 20)
            if clock <= 0:
                break
            seq += 1
            roster = H if off == "H" else A
            other = A if off == "H" else H
            shooter = str(rng.choice(roster[:5]))
            r = rng.random()
            if r < 0.12:
                stealer = str(rng.choice(other[:5]))
                plays.append([seq, per, clock, 1, team[off], [shooter, stealer], None, None, 0, 0, 0, hs, as_,
                              f"{shooter} bad pass ({stealer} steals)"])
            else:
                made = rng.random() < 0.5
                val = 3 if rng.random() < 0.35 else 2
                if made:
                    if off == "H":
                        hs += val
                    else:
                        as_ += val
                    parts = [shooter] + ([str(rng.choice([p for p in roster[:5] if p != shooter]))] if rng.random() < 0.6 else [])
                    plays.append([seq, per, clock, 2, team[off], parts, 1.0, 10.0, val, 1, 1, hs, as_,
                                  f"{shooter} makes shot" + (f" ({parts[1]} assists)" if len(parts) > 1 else "")])
                else:
                    plays.append([seq, per, clock, 3, team[off], [shooter], 1.0, 10.0, 0, 1, 0, hs, as_, f"{shooter} misses shot"])
                    seq += 1
                    reb_side = off if rng.random() < 0.25 else ("A" if off == "H" else "H")
                    rb = str(rng.choice((H if reb_side == "H" else A)[:5]))
                    kind = "offensive" if reb_side == off else "defensive"
                    plays.append([seq, per, clock, 4, team[reb_side], [rb], None, None, 0, 0, 0, hs, as_, f"{rb} {kind} rebound"])
                    if kind == "offensive":
                        continue
            off = "A" if off == "H" else "H"
        seq += 1
        plays.append([seq, per, 0.0, 5, None, [], None, None, 0, 0, 0, hs, as_, f"End of {per} Quarter"])
    if hs == as_:
        seq += 1
        hs += 2
        plays.append([seq, 4, 0.0, 2, home, [H[0]], 1.0, 1.0, 2, 1, 1, hs, as_, f"{H[0]} makes shot"])   # walk-off at the horn
    wpmap = {str(p[0]): 0.5 for p in plays}
    box = {home: {"players": [[p, int(i < 5), 1440, 0] + [0] * 14 for i, p in enumerate(H)], "dnp": []},
           away: {"players": [[p, int(i < 5), 1440, 0] + [0] * 14 for i, p in enumerate(A)], "dnp": []}}
    game = {"id": gid, "date": "2031-01-01T00:00:00Z", "status": "post", "stype": "reg", "neutral": False, "home": home,
            "away": away, "hs": hs, "as": as_, "periods": 4, "odds": {"spread_home": -3.5}, "box": box, "has_pbp": True}
    return {"id": gid, "periods": 4, "plays": plays, "wp": wpmap}, game


def _box_row(pid, starter, minutes, pts, fga, fgm, tpa, tpm, fta, ftm, oreb, dreb, ast, stl, blk, tov, pf):
    return [pid, starter, int(minutes * 60), pts, fgm, fga, tpm, tpa, ftm, fta, oreb, dreb, ast, stl, blk, tov, pf, 0]


def synth_season(seed=0, n_teams=8, per_team=9, n_games=200, standout=None, rookie_star=None, bench_star=None, played=1.0,
                 season=2031):
    """Store-shaped games (box scores) for an award test. `standout`: a player with big scoring and a
    winning team; `rookie_star`, `bench_star` likewise for ROY and 6MOY. played < 1 leaves the rest as 'pre'."""
    rng = np.random.default_rng(seed)
    teams = [str(t) for t in range(n_teams)]
    roster = {t: [f"s{season}_{t}_{i}" if False else f"t{t}p{i}" for i in range(per_team)] for t in teams}
    strength = {t: rng.normal(0, 3) for t in teams}
    star_team = None
    if standout:
        star_team = "0"
        roster["0"][0] = standout
        strength["0"] = 8.0
    if rookie_star:
        roster["1"][1] = rookie_star
    if bench_star:
        roster["2"][6] = bench_star
    games = {}
    n_played = int(n_games * played)
    for k in range(n_games):
        h, a = rng.choice(teams, 2, replace=False)
        gid = f"{season}{k:04d}"
        date = f"{season - 1}-11-{1 + k % 28:02d}" if k < n_games // 2 else f"{season}-02-{1 + k % 27:02d}"
        if k >= n_played:
            games[gid] = {"id": gid, "date": date, "status": "pre", "stype": "reg", "home": h, "away": a, "hs": None, "as": None,
                          "box": {}, "periods": 4}
            continue
        box, pts = {}, {}
        for t in (h, a):
            rows = []
            for i, p in enumerate(roster[t]):
                starter = int(i < 5)
                mins = [34, 33, 32, 30, 28, 22, 20, 14, 10][i]
                ppg = [18, 15, 13, 11, 9, 10, 8, 5, 3][i]
                if p == standout:
                    ppg, mins = 34, 37
                if p == rookie_star:
                    ppg = 24
                if p == bench_star:
                    ppg, mins = 21, 29
                pp = max(0, int(rng.normal(ppg, 4)))
                fga = max(pp // 2, 1)
                rows.append(_box_row(p, starter, mins, pp, fga, pp // 2 - pp // 6, fga // 3, pp // 9, pp // 5, pp // 6,
                                     1, 4, 3, 1, 1 if i != 4 else 2, 2, 2))
            box[t] = {"players": rows, "dnp": [], "team": {}}
            pts[t] = sum(r[3] for r in rows)
        diff = strength[h] - strength[a] + 2 + rng.normal(0, 10)
        hs, as_ = pts[h], pts[a]
        if (diff > 0) != (hs > as_) or hs == as_:      # let strength decide the winner: move points from the box tally
            hs, as_ = (max(hs, as_) + 1, min(hs, as_)) if diff > 0 else (min(hs, as_), max(hs, as_) + 1)
        games[gid] = {"id": gid, "date": date, "status": "post", "stype": "reg", "home": h, "away": a, "hs": hs, "as": as_,
                      "periods": 4, "box": box}
    players = {p: {"name": p.upper(), "pool": "G" if p.endswith(("0", "1", "2")) else "F"} for t in teams for p in roster[t]}
    return games, players


# ============================================================================ xPTS

@pytest.fixture(scope="module")
def shot_model():
    df = synth_shots()
    return df, shots.fit_xpts(df)


def test_xpts_recovers_distance_curve(shot_model):
    df, m = shot_model
    assert m["ok"] and m["n"] == len(df)
    c = shots.distance_curve(m, np.array([1, 3, 6, 10, 15, 20, 25]))
    # baseline row is unassisted; planted assisted effect is zero and the planted shot-makers are few
    err = np.abs(c["p"].to_numpy() - true_p(c["dist_ft"]))
    assert err.max() < 0.04, c.assign(true=true_p(c["dist_ft"]))
    assert np.all(np.diff(c["p"].to_numpy()) < 0.02)       # decreasing in distance (up to noise)


def test_xpts_calibrated_by_zone_and_decile(shot_model):
    df, m = shot_model
    cz = shots.calibration_table(df, m, "zone")
    assert set(cz.index) == {"rim", "paint", "mid", "ab3"}
    assert (cz["diff"].abs() < 0.01).all()
    test = synth_shots(40000, seed=7)
    cd = shots.calibration_table(test, m, "decile")
    assert (cd["diff"].abs() < 0.03).all(), cd
    x = shots.xpts(m, test)
    assert abs(x.sum() / (test["made"] * test["value"]).sum() - 1) < 0.03


def test_xpts_shot_making_finds_planted_shooters(shot_model):
    df, m = shot_model
    sm = shots.shot_making(df, m, "shooter")
    top = set(sm.sort_values("pox100", ascending=False).index[:15])
    assert len(top & {str(i) for i in range(10)}) >= 8
    assert {"pox100", "se_pox100", "pox100_shrunk", "xpps"} <= set(sm.columns)
    assert (sm["pox100_shrunk"].abs() <= sm["pox100"].abs() + 1e-9).all()


def test_xpts_tables_and_grid(shot_model):
    df, m = shot_model
    diet = shots.shot_diet(df, "team")
    z = diet[diet["kind"] == "zone"].groupby("entity")["share"].sum()
    assert np.allclose(z.to_numpy(), 1.0)
    de = shots.defense_xpts(df, m)
    assert len(de) == 30 and (de["xpps"] > 0.8).all()
    prof = shots.shot_profile(df, m, "shooter")
    assert {"rim_freq", "three_freq", "pox100_shrunk"} <= set(prof.columns)
    g = shots.league_grid(df, m, "square", 2.0)
    assert g["x"].between(-25, 25).all() and g["y"].between(0, shots.GRID_Y_MAX + 1).all()
    assert abs(g["share"].sum() - 1) < 1e-9
    h = shots.league_grid(df, m, "hex", 1.5)
    ref = h.copy()
    pg = shots.league_grid(df[df["shooter"] == "0"], m, "hex", 1.5, ref=ref)
    assert "fg_diff" in pg and pg["lg_fg"].notna().mean() > 0.9
    json.dumps(_io.clean(m))                                  # the model is JSON-serialisable


def test_xpts_fit_speed():
    df = synth_shots(220000, seed=3)
    t0 = time.time()
    m = shots.fit_xpts(df)
    assert m["ok"] and time.time() - t0 < 15


def test_xpts_empty():
    assert shots.fit_xpts([])["ok"] is False


# ============================================================================ RAPM

@pytest.fixture(scope="module")
def rapm_data():
    st, o, d = synth_stints(cameo="cameo")
    return st, o, d, impact.rapm_fit(st)


def test_rapm_recovers_planted_effects(rapm_data):
    st, o, d, r = rapm_data
    pl = r["players"]
    ids = list(o)
    co = np.corrcoef([pl[p]["o"] for p in ids], [o[p] for p in ids])[0, 1]
    cd = np.corrcoef([pl[p]["d"] for p in ids], [d[p] for p in ids])[0, 1]
    ct = np.corrcoef([pl[p]["t"] for p in ids], [o[p] + d[p] for p in ids])[0, 1]
    assert co > 0.9 and cd > 0.85 and ct > 0.9, (co, cd, ct)
    assert 1.5 < r["hca"] < 4.5
    assert r["ridge"] in impact.RIDGE_GRID and len(r["cv"]) == len(impact.RIDGE_GRID)
    assert all(pl[p]["se"] > 0 and pl[p]["poss"] > 0 for p in ids)


def test_rapm_shrinks_low_possession_players(rapm_data):
    st, o, d, r = rapm_data
    pl = r["players"]
    c = pl["cameo"]
    assert c["poss"] < 30
    assert abs(c["o"]) < 0.5 and abs(c["d"]) < 0.5
    assert c["se_o"] > 2 * np.median([pl[p]["se_o"] for p in o])


def test_rapm_prior_centre_and_contract_shape():
    st, o, d = synth_stints(n_games=200, seed=4)
    prior = {p: {"o": 5.0, "d": -5.0} for p in o}
    a = impact.rapm(st, ridge=1e6)
    b = impact.rapm(st, ridge=1e6, prior=prior)
    p0 = next(iter(o))
    assert set(a[p0]) >= {"o", "d", "t", "poss", "se"}
    assert abs(a[p0]["o"]) < 0.2 and abs(b[p0]["o"] - 5.0) < 0.2 and abs(b[p0]["d"] + 5.0) < 0.2
    seasons = impact.rapm_seasons({2030: st, 2031: st}, ridge=3000.0)
    assert set(seasons) == {2030, 2031}
    # STINT dicts (pbp.stints output) give the same answer as rows
    rows = st["rows"][:400]
    dicts = [{"game_id": r[0], "t0": r[1], "t1": r[2], "home": r[3:8], "away": r[8:13], "poss_home": r[13], "poss_away": r[14],
              "pts_home": r[15], "pts_away": r[16]} for r in rows]
    x = impact.rapm({"cols": st["cols"], "rows": rows}, ridge=2000.0)
    y = impact.rapm(dicts, ridge=2000.0)
    assert all(abs(x[p]["o"] - y[p]["o"]) < 1e-9 for p in x)


def test_rapm_full_season_speed():
    st, o, d = synth_stints(n_teams=30, per_team=15, n_games=1230, per_game=40, seed=2)
    t0 = time.time()
    r = impact.rapm_fit(st)
    assert len(r["players"]) == 450 and time.time() - t0 < 20


# ============================================================================ box impact, HPM, projections

def synth_box_rates(n=400, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({f: rng.normal(0, 1, n) for f in impact.BOX_FEATURES})
    df["pool_G"] = (rng.random(n) < 0.4).astype(float)
    df["pool_F"] = ((1 - df["pool_G"]) * (rng.random(n) < 0.6)).astype(float)
    df["poss"] = rng.uniform(300, 5000, n)
    df.index = [f"b{i}" for i in range(n)]
    o = 1.5 * df["pts100"] + 1.0 * df["ts_add"] + 0.8 * df["ast100"] - 0.7 * df["tov100"] + rng.normal(0, 0.7, n)
    d = 0.9 * df["blk100"] + 0.8 * df["stl100"] + 0.6 * df["dreb100"] - 0.3 * df["pf100"] + rng.normal(0, 0.7, n)
    rp = {p: {"o": float(o[p]), "d": float(d[p]), "se_o": 0.5, "se_d": 0.5} for p in df.index}
    return df, rp


def test_box_impact_fit_and_predict():
    df, rp = synth_box_rates()
    m = impact.box_impact_fit(df, rp)
    assert m["ok"] and "box" in m["variants"] and "full" not in m["variants"]
    v = m["variants"]["box"]
    assert v["r2_o"] > 0.7 and v["r2_d"] > 0.6
    assert 0.25 <= v["tau2_o"] < 1.0
    test, rt = synth_box_rates(200, seed=9)
    bi = impact.box_impact(test, m, team_adjust=False)
    assert np.corrcoef(bi["o"], [rt[p]["o"] for p in test.index])[0, 1] > 0.85
    assert np.corrcoef(bi["d"], [rt[p]["d"] for p in test.index])[0, 1] > 0.8
    assert (bi["variant"] == "box").all()
    # the full variant is used when shot features exist
    df2 = df.assign(rim_freq=np.random.default_rng(1).random(len(df)), three_freq=0.3, pox100_shrunk=0.0)
    m2 = impact.box_impact_fit(df2, rp)
    assert "full" in m2["variants"]
    assert (impact.box_impact(df2, m2, team_adjust=False)["variant"] == "full").all()
    assert (impact.box_impact(df, m2, team_adjust=False)["variant"] == "box").all()


def test_box_rates_and_team_adjustment():
    games, players = synth_season(seed=1)
    br = impact.box_rates(games, players)
    assert {"poss", "pts100", "ts_add", "usg", "team_net", "frac"} <= set(br.columns)
    assert br.groupby("team")["frac"].sum().between(4.99, 5.01).all()
    rp = {p: {"o": 0.05 * (br.at[p, "pts100"] - 25), "d": 0.0, "se_o": 1.0, "se_d": 1.0} for p in br.index}
    m = impact.box_impact_fit(br, rp)
    bi = impact.box_impact(br, m, team_adjust=True)
    for t, idx in br.groupby("team").groups.items():
        s = float((bi.loc[idx, "o"] * br.loc[idx, "frac"]).sum())
        assert abs(s - (br.loc[idx, "team_ortg"].iloc[0] - br["lg_ortg"].iloc[0])) < 1e-6


def test_hpm_between_inputs_weighted_by_precision():
    model = {"variants": {"box": {"tau2_o": 4.0, "tau2_d": 1.0}}}
    box = {"a": {"o": 2.0, "d": 1.0, "variant": "box"}, "b": {"o": 2.0, "d": 1.0, "variant": "box"}, "c": {"o": -1.0, "d": 0.5, "variant": "box"}}
    rp = {"a": {"o": 6.0, "d": -1.0, "se_o": 2.0, "se_d": 1.0},          # equal precision on offence -> midpoint
          "b": {"o": 6.0, "d": -1.0, "se_o": 0.5, "se_d": 3.0}}          # precise RAPM on offence, vague on defence
    h = impact.hpm(box, rp, model)
    assert h["a"]["o"] == pytest.approx(4.0)
    assert h["a"]["d"] == pytest.approx(0.0)
    assert 2.0 < h["b"]["o"] < 6.0 and h["b"]["o"] > 5.5
    assert -1.0 < h["b"]["d"] < 1.0 and h["b"]["d"] > 0.7
    assert h["a"]["se_o"] == pytest.approx((1 / 4 + 1 / 4) ** -0.5)
    assert h["c"]["o"] == -1.0 and h["c"]["se_o"] == pytest.approx(2.0) and h["c"]["w_rapm_o"] == 0.0
    assert h["b"]["t"] == pytest.approx(h["b"]["o"] + h["b"]["d"])


def test_projections_and_roster_impact():
    games, players = synth_season(seed=2, n_games=150)
    for p in players:
        players[p]["dob"] = "2005-06-01" if p.endswith("1") else "1995-06-01"
    pj = impact.projections(games, asof="2031-12-31", players=players, hpm_values={"t0p0": {"t": 3.0}})
    r = pj["t0p0"]
    assert set(r["rates"]) == set(impact.PROJ_STATS)
    assert 30 < r["min"] < 36 and 0 < r["avail"] <= 1
    assert r["hpm_next"] == pytest.approx(3.0 + r["aging"]) and r["aging"] < 0
    assert pj["t0p1"]["aging"] > 0
    # regression to the pool mean: a 3-game player's rates sit near his pool's
    assert impact.aging_delta(20) > impact.aging_delta(27) == 0.0 > impact.aging_delta(34)
    full = impact.roster_impact({"a": 4.0, "b": 2.0, "c": 0.0, "d": -1.0, "e": 1.0, "f": 0.0, "g": -2.0},
                                {"a": 36, "b": 34, "c": 34, "d": 32, "e": 30, "f": 24, "g": 20})
    assert full["minutes"] == pytest.approx(210) and full["fill_minutes"] == pytest.approx(30)
    expect = (4 * 36 + 2 * 34 + 0 - 32 + 30 + 0 - 40) / 48 + impact.REPLACEMENT_HPM * 30 / 48
    assert full["net"] == pytest.approx(expect)
    hurt = impact.roster_impact({"b": 2.0, "c": 0.0, "d": -1.0, "e": 1.0, "f": 0.0, "g": -2.0},
                                {"b": 36, "c": 36, "d": 34, "e": 34, "f": 30, "g": 26})
    assert hurt["net"] < full["net"]
    capped = impact.roster_impact({"a": 1.0}, {"a": 400}, league="wnba")
    assert capped["minutes"] == pytest.approx(200) and capped["net"] == pytest.approx(5.0)


# ============================================================================ win probability

@pytest.fixture(scope="module")
def wp_model():
    return winprob.fit_wp(synth_states(2000, seed=0))


def test_wp_tipoff_pickem_and_spread(wp_model):
    m = wp_model
    assert m["ok"]
    assert winprob.wp(m, {"margin": 0, "t_left": 2880, "period": 1, "poss": 0, "exp_margin": 0}) == pytest.approx(0.5, abs=1e-9)
    fav = winprob.wp(m, {"margin": 0, "t_left": 2880, "period": 1, "exp_margin": 6.0})
    assert 0.65 < fav < 0.85
    assert winprob.wp(m, {"margin": 0, "period": 1, "clock_s": 720, "spread_home": -6.0}) == pytest.approx(fav)


def test_wp_monotone_in_margin_and_time(wp_model):
    m = wp_model
    for tl in (2880, 1500, 600, 120, 20):
        ps = [winprob.wp(m, {"margin": x, "t_left": tl, "period": 4, "exp_margin": 2.0}) for x in range(-15, 16)]
        assert np.all(np.diff(ps) > 0)
    for lead in (3, 8):
        ps = [winprob.wp(m, {"margin": lead, "t_left": tl, "period": 4}) for tl in (2880, 2000, 1000, 500, 100, 10)]
        assert np.all(np.diff(ps) > 0)                       # a lead is worth more as time runs out
    assert winprob.wp(m, {"margin": 1, "t_left": 0, "period": 4}) == 1.0
    assert winprob.wp(m, {"margin": -1, "t_left": 0, "period": 5}) == 0.0
    assert winprob.wp(m, {"margin": 0, "t_left": 5, "period": 4, "poss": 1}) > 0.5


def test_wp_calibrated_on_synthetic_paths(wp_model):
    test = synth_states(3000, seed=11)
    cal = winprob.calibration(wp_model, test)
    for row in cal["ours"]["table"]:
        if row["n"] > 2000:
            assert abs(row["p_mean"] - row["y_mean"]) < 0.06, row
    assert cal["ours"]["brier"] < 0.15


def test_wpa_sums_to_final_wp_change(wp_model):
    for seed in range(3):
        pbp, game = synth_pbp_game(seed)
        res = winprob.wpa(game, pbp, wp_model)
        assert abs(res["check"]) < 1e-9
        assert res["wp_final"] in (0.0, 1.0) and res["home_win"] == int(game["hs"] > game["as"])
        home = sum(r["wpa"] for r in res["players"].values() if r["team"] == "1")
        away = sum(r["wpa"] for r in res["players"].values() if r["team"] == "2")
        d = res["wp_final"] - res["wp0"]
        # each team's players (plus what nobody could take) sum to that team's own WP change
        assert home + res["unattributed"]["1"] == pytest.approx(d, abs=1e-9)
        assert away + res["unattributed"]["2"] == pytest.approx(-d, abs=1e-9)
        assert home - away + res["unattributed"]["1"] - res["unattributed"]["2"] == pytest.approx(2 * d, abs=1e-9)
        assert sum(p["dwp"] for p in res["plays"]) + (res["wp_final"] - res["plays"][-1]["wp"]) == pytest.approx(res["wp_final"] - res["wp0"])
        assert res["excitement"] >= abs(res["wp_final"] - res["wp0"])
        assert 0 <= res["comeback"] <= res["wp0"] if res["home_win"] else 0 <= res["comeback"] <= 1 - res["wp0"]
        assert all(p["li"] >= 0 for p in res["plays"])
    # an assisted make credits both team-mates, in the shooter's favour
    p = next(p for p in res["plays"] if len(p["credit"]) == 2 and "assists" in p["text"])
    (s, cs), (a, ca) = list(p["credit"].items())
    assert abs(cs) > abs(ca) and np.sign(cs) == np.sign(ca)
    # a steal credits the stealer (other side) the mirror of the ball-handler's loss
    p = next(p for p in res["plays"] if "steals" in p["text"] and len(p["credit"]) == 2 and p["dwp"] != 0)
    (h_, ch), (s_, cst) = list(p["credit"].items())
    assert ch == pytest.approx(-cst)
    season = winprob.season_wpa([winprob.wpa(*synth_pbp_game(k)[::-1], wp_model) for k in range(2)])
    assert all(v["games"] == 2 for v in season.values() if v["team"] == "1")


def test_wp_states_from_pbp_and_possession_inference(wp_model):
    pbp, game = synth_pbp_game(5)
    st = winprob.states_from_pbp(pbp, game)
    assert len(st) == len(pbp["plays"]) and set(winprob.STATE_COLS) <= set(st.columns)
    assert st["margin"].iloc[-1] == game["hs"] - game["as"]
    assert st["exp_margin"].iloc[0] == 3.5
    # after a home make the ball goes to the away side; after a defensive rebound to the rebounder's team;
    # after a miss the ball is loose: the shooting side keeps it only at the offensive-rebound rate
    loose = 2 * winprob.OREB_FG - 1
    for k, p in enumerate(pbp["plays"]):
        if p[3] == 2 and p[4] == "1":
            assert st["poss"].iloc[k] == -1
        if "defensive rebound" in p[13]:
            assert st["poss"].iloc[k] == (1 if p[4] == "1" else -1)
        if " misses " in p[13]:
            assert st["poss"].iloc[k] == pytest.approx(loose if p[4] == "1" else -loose)
    cal = winprob.calibration(wp_model, st)
    assert cal["n_espn"] == len(st) and "espn" in cal


# ============================================================================ awards

def _table(seed, **kw):
    games, players = synth_season(seed=seed, **kw)
    rookies = [kw.get("rookie_star")] if kw.get("rookie_star") else []
    hp = {p: {"t": 0.0, "o": 0.0, "d": 0.0} for p in players}
    if kw.get("standout"):
        hp[kw["standout"]] = {"t": 7.0, "o": 5.0, "d": 2.0}
    return awards.season_table(games, players, hp, None, None, rookies), games, players


def test_award_model_ranks_planted_standouts():
    hist = []
    for k in range(6):
        t, _, _ = _table(k, standout=f"mvp{k}")
        hist.append((t, [f"mvp{k}"]))
    m = awards.fit_award("mvp", hist)
    assert m["fitted"] and m["top1"] == 1.0
    cur, games, _ = _table(42, standout="star", rookie_star="kid", bench_star="sixth", played=0.6)
    assert cur.at["star", "team_left"] > 0
    r = awards.race("mvp", cur, m, league="nba", season=2023, n=2000)
    assert next(iter(r)) == "star" and r["star"]["p"] > 0.5
    assert abs(sum(v["p"] for v in r.values()) - 1) < 1e-9
    roy = awards.race("roy", cur, None, n=1000)
    assert list(roy) == ["kid"]
    six = awards.race("6moy", cur, None, n=1000)
    assert next(iter(six)) == "sixth" and "star" not in six
    allr = awards.races(cur, {"mvp": m}, league="nba", season=2023, n=500)
    assert set(allr) >= {"mvp", "roy", "6moy", "dpoy"} and "mip" not in allr      # no previous season
    fin = awards.race("mvp", cur, m, final=True, n=2000)
    assert next(iter(fin)) == "star" and abs(sum(v["p"] for v in fin.values()) - 1) < 1e-9


def test_award_65_game_rule_and_team_wins_input():
    cur, games, _ = _table(3, standout="star", n_games=120, played=1.0)
    # the star's team played ~30 games: under the 65-game rule nobody qualifies at season end
    assert cur.at["star", "games"] < 65
    assert awards.race("mvp", cur, None, league="nba", season=2025, final=True) and \
        all(v["p"] == 0 for v in awards.race("mvp", cur, None, league="nba", season=2025, final=True).values())
    assert awards.race("mvp", cur, None, league="nba", season=2023, final=True)["star"]["p"] > 0.3
    assert awards.race("mvp", cur, None, league="wnba", season=2025, final=True)["star"]["p"] > 0.3
    assert awards._eligible("roy", "nba", 2025) is False
    part, _, _ = _table(4, standout="star", played=0.5)
    team = part.at["star", "team"]
    rich = awards.race("mvp", part, None, team_wins={team: {"exp_w": 60, "w_p05": 58, "w_p95": 62}}, n=2000)
    poor = awards.race("mvp", part, None, team_wins={team: {"exp_w": float(part.at["star", "team_wins"]), "w_p05": 0, "w_p95": 1}}, n=2000)
    assert rich["star"]["p"] >= poor["star"]["p"]


def test_award_winners_table_is_verified_and_complete():
    # verified against published award histories on 2026-10-01 (see the module docstring)
    assert award_winners.HAND_ENTERED is False
    assert not any(award_winners.UNSURE.values())
    for a in ("mvp", "roy", "dpoy", "6moy", "mip"):
        w = award_winners.winners("nba", a)
        assert all(y in w for y in range(1997, 2027)), a
    assert award_winners.winner_names("nba", "roy", 2000) == ["Elton Brand", "Steve Francis"]
    assert award_winners.winner_names("wnba", "dpoy", 2025) == ["Alanna Smith", "A'ja Wilson"]
    assert award_winners.winner_names("wnba", "mvp", 2026) == []      # not announced at the check date
    assert set(award_winners.winners("nba", "clutch")) >= {2023, 2024, 2025}
    t = pd.DataFrame({"name": ["Nikola Jokić", "Jaren Jackson Jr."]}, index=["1", "2"])
    assert awards.resolve_winners(["Nikola Jokic", "Jaren Jackson Jr."], t) == ["1", "2"]


# ============================================================================ real fixtures (builder A)

def _fixture(name):
    p = FIX / name
    if not p.exists():
        pytest.skip(f"fixture {name} missing")
    try:
        from oddsmarkets.basketball import pbp as P
        from oddsmarkets.basketball.sources import espn
    except Exception as exc:                                  # builder A not importable yet
        pytest.skip(f"builder A modules unavailable: {exc}")
    raw = json.loads(gzip.open(p, "rt", encoding="utf-8").read())
    g, pb = espn.compact_game(raw), espn.compact_pbp(raw)
    if not pb:
        pytest.skip("no pbp in fixture")
    return g, pb, P


def test_fixture_smoke_wpa_and_shots(wp_model):
    for name in ("nba_reg_401810433.json.gz", "nba_ot_401810445.json.gz", "wnba_401857068.json.gz"):
        g, pb, P = _fixture(name)
        league = "wnba" if name.startswith("wnba") else "nba"
        ev = P.parse(pb, g)
        res = winprob.wpa(g, pb, wp_model, ev, league=league)
        assert abs(res["check"]) < 1e-9 and res["players"]
        # with the parser's lineups nearly everything is attributed and the two teams' WPA mirror each other
        h, a = g["home"], g["away"]
        d = res["wp_final"] - res["wp0"]
        assert abs(res["unattributed"][h]) < 0.05 and abs(res["unattributed"][a]) < 0.05
        assert abs(res["teams"][h] - d) < 0.05 and abs(res["teams"][a] + d) < 0.05
        assert max(abs(r["wpa"]) for r in res["players"].values()) < 1.0
        # a missed shot costs its shooter; the defensive rebound after it moves WP less than the miss did
        rows = res["plays"]
        pairs = [(rows[k], rows[k + 1]) for k in range(len(rows) - 1)
                 if " misses " in rows[k]["text"] and "free throw" not in rows[k]["text"] and "defensive rebound" in rows[k + 1]["text"]]
        assert pairs
        assert np.mean([abs(m["dwp"]) > abs(r["dwp"]) for m, r in pairs]) > 0.6
        cal = winprob.calibration(wp_model, winprob.states_from_pbp(pb, g, ev.possessions, league))
        assert cal.get("n_espn", 0) > 100
        sh = P.shots(g, ev)
        df = shots.as_shots({"cols": _io.SHOT_COLS, "rows": sh})
        assert len(df) > 100 and set(df["zone"]) <= set(shots.ZONES) | {"None"}
        st = P.stints(g, ev)
        r = impact.rapm(st, ridge=3000.0)
        assert len(r) >= 10


# ============================================================================ season loaders on a temporary data root

def _write_root(tmp_path, monkeypatch, seasons=(2030, 2031)):
    data, cache, pbp_root = tmp_path / "data", tmp_path / "cache", tmp_path / "pbp"
    monkeypatch.setenv("HARDWOOD_DATA", str(data))
    monkeypatch.setenv("HARDWOOD_CACHE", str(cache))
    monkeypatch.setenv("HARDWOOD_PBP", str(pbp_root))
    rng = np.random.default_rng(0)
    for k, season in enumerate(seasons):
        games, players = synth_season(seed=10 + k, n_games=160, standout="star", played=1.0 if k == 0 else 0.7, season=season)
        roster = {}
        for g in games.values():
            for tid, b in (g.get("box") or {}).items():
                roster.setdefault(tid, [r[0] for r in b["players"]])
        stints, shot_rows = [], []
        for n, (gid, g) in enumerate(games.items()):
            if g["status"] != "post":
                continue
            h, a = g["home"], g["away"]
            if n < 12:                                   # play-by-play for a few games
                pb, gg = synth_pbp_game(n, gid, h, a, roster[h], roster[a])
                g["hs"], g["as"], g["has_pbp"] = gg["hs"], gg["as"], True
                path = pbp_root / "nba" / str(season) / f"{gid}.json.gz"
                path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(path, "wt", encoding="utf-8") as fh:
                    json.dump(pb, fh)
            for s_ in range(20):
                hp = list(rng.choice(roster[h][:8], 5, replace=False))
                ap = list(rng.choice(roster[a][:8], 5, replace=False))
                stints.append([gid, s_ * 140.0, s_ * 140.0 + 140, *hp, *ap, 5.0, 5.0, float(rng.poisson(5.6)), float(rng.poisson(5.6))])
            for _ in range(30):
                tm = h if rng.random() < 0.5 else a
                d = float(rng.uniform(0, 27))
                zone = "rim" if d < 4 else "paint" if d < 14 else "mid" if d < 23.75 else "ab3"
                shot_rows.append([gid, float(rng.uniform(0, 2880)), 1, tm, str(rng.choice(roster[tm][:8])), 0.0, d, d, 0.0, zone,
                                  "jumper", 3 if d >= 23.75 else 2, int(rng.random() < true_p(d)), 0, None, 0, 0, 0, 0, 0])
        root = data / "nba" / str(season)
        root.mkdir(parents=True, exist_ok=True)
        (root / "store.json").write_text(json.dumps({"league": "nba", "season": season, "teams": {}, "players": players,
                                                     "games": games, "meta": {}}), encoding="utf-8")
        (root / "stints.json").write_text(json.dumps({"cols": _io.STINT_COLS, "rows": stints}), encoding="utf-8")
        (root / "shots.json").write_text(json.dumps({"cols": _io.SHOT_COLS, "rows": shot_rows}), encoding="utf-8")
    return data, cache


def test_season_loaders(tmp_path, monkeypatch):
    data, cache = _write_root(tmp_path, monkeypatch)
    sh = shots.for_season("nba", 2031)
    assert sh["ok"] and sh["n_shots"] > 1000 and sh["players"] and sh["calibration"] and sh["grid"]
    assert (cache / "shots" / "nba_2031.json").exists()
    assert shots.for_season("nba", 2031)["n_shots"] == sh["n_shots"]            # served from cache
    im = impact.for_season("nba", 2031)
    assert im["ok"], im
    star = im["players"]["star"]
    assert {"o", "d", "t", "se", "rapm", "proj", "team", "minutes"} <= set(star)
    assert im["box_model"]["ok"]
    wp = winprob.for_season("nba", 2031)
    assert wp["ok"], wp
    assert len(wp["games"]) == 12 and wp["players"] and wp["calibration"]["n"] > 0
    aw = awards.for_season("nba", 2031, team_wins=None, n=500)
    assert aw["ok"], aw
    assert next(iter(aw["races"]["mvp"])) == "star"
    assert "mip" in aw["races"]                                                     # previous season on disk
    json.dumps(aw)
    assert shots.for_season("nba", 1990)["ok"] is False
    assert impact.for_season("nba", 1990)["ok"] is False


def test_xpts_ignores_assists_which_exist_only_on_makes():
    """The play-by-play records an assist only on a made shot. As a feature it leaked the outcome: a shooter whose makes
    were unassisted was judged against misses only (Olivia Miles, WNBA 2026: +26.9 per 100 under xpts-1, +0.9 now)."""
    df = synth_shots(30000, seed=3)
    df["assisted"] = np.where(df["made"] == 1, df["assisted"], 0)        # the real tables: assists on makes only
    m = shots.fit_xpts(df)
    assert "assisted" not in shots.BINARY and shots.MODEL_VERSION != "xpts-1"
    x = df.copy()
    x["assisted"] = 1 - x["assisted"]
    assert np.allclose(shots.p_make(m, df), shots.p_make(m, x))           # flipping the flag changes nothing
    sm = shots.shot_making(df, m, "shooter")
    self_made = df[(df["made"] == 1) & (df["assisted"] == 0)].groupby("shooter").size() / df.groupby("shooter").size()
    # shot-making no longer tracks the share of unassisted makes among ordinary (unplanted) shooters
    ordinary = [s for s in sm.index if int(s) >= 10]
    assert abs(np.corrcoef(sm.loc[ordinary, "pox100"], self_made.loc[ordinary])[0, 1]) < 0.5
