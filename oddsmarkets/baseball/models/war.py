"""
Bullpen WAR: wins above replacement from our own components, per season.

Position players (Statcast era, 2015 onward)
--------------------------------------------
    RAR = batting + baserunning + fielding (+ framing for catchers) + positional + league adj + replacement
    WAR = RAR / RPW

* Batting runs (true talent): the park-neutral xwOBA+ (xwoba.py `xwoba_n`) regressed toward the league
  with STAB_PA pseudo-PAs (stabilise.py's 0.7-reliability point for xwOBA+ when available), converted to
  runs: (x_reg - lg) / wOBA scale * PA. The results-based version (wOBA, park-adjusted by half the
  park's run factor) is reported alongside (`bat_results`).
* Baserunning: (a) stolen bases and caught stealing as wSB = SB*runSB + CS*runCS - lgwSB*(1B+BB+HBP-IBB),
  runSB = +0.2, runCS = -(2*runs_per_out + 0.075) (FanGraphs' constants); in pitch data a steal is a
  runner moving up a base between two pitches of the same plate appearance on a pitch that was not
  blocked or put in play, a caught stealing a runner vanishing with an out added and no run (both
  marked "estimated"); in Retrosheet they are read from the event text. (b) Extra bases taken on singles
  and doubles: each runner's result (held, extra base, scored, out) valued with the season's RE matrix
  and compared with the league average for the same hit, starting base and outs.
* Fielding: catch-probability fielding runs (catchprob.py); catchers add framing runs (framing.py).
* Positional adjustment per 162 games (FanGraphs' scale): C +12.5, 1B -12.5, 2B +2.5, 3B +2.5,
  SS +7.5, LF -7.5, CF +2.5, RF -7.5, DH -17.5, prorated by games at each position (share of the team's
  defensive PAs while the player was at the position; a game batted without fielding is a DH game).
* League adjustment: a constant per PA so that batting + baserunning + fielding + positional sums to
  zero over position players.
* Replacement level: REPL_SHARE_POS of WAR_PER_SEASON wins (convention: 1,000 WAR per 2,430 games,
  57% to position players, 43% to pitchers), scaled by the games played (team-games / 4,860), spread
  per PA. RPW = 9 * runs_per_inning * 1.5 + 3.

Pitchers
--------
* RA9-based: runs scored while the pitcher was on the mound (inherited runners are not reassigned:
  documented approximation), innings = outs recorded / 3, park-adjusted by half the run factor;
  RAR = (repl_RA9 - RA9) * IP / 9.
* Expected (xwOBA+-based): expected runs = BF * (lg runs per PA + (xwOBA+_n against - lg) / scale);
  the same replacement machinery.
* Relievers (fewer than half their games as the starter) are multiplied by (1 + gmLI) / 2, gmLI = the
  average leverage index of the first PA they face in each game.
* Each version's replacement level is solved so that pitcher WAR sums to the pitchers' share.

Historical WAR (1908 onward, Retrosheet play-by-play; no event files are read before 1908)
--------------------------------------------------------------------------------------
Batting runs from that season's Retrosheet linear weights (wOBA weights from re24.retro_season);
baserunning from the Retrosheet steals and extra bases taken; fielding is a *proxy* where Statcast is
absent: Lahman range factor ((PO + A); assists only for catchers and first basemen) against the position's
league rate per team ball-in-play out (innings, or games x 8.5 before innings are recorded, times the
team's (IPouts - SO) / inning), at 0.75 runs per play, and errors against the position rate at 0.75 runs,
both regressed to 25%; positional adjustment from Lahman games by position. Pitching is
RA9-based only. Every historical row carries `fielding_source: "proxy"`.
"""
from __future__ import annotations


import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _c

MODEL_VERSION = "war-4"
WAR_PER_SEASON = 1000.0
GAMES_FULL = 4860.0            # team-games in a 2,430-game season
REPL_SHARE_POS = 0.57
REPL_SHARE_PIT = 0.43
POS_ADJ = {2: 12.5, 3: -12.5, 4: 2.5, 5: 2.5, 6: 7.5, 7: -7.5, 8: 2.5, 9: -7.5, "DH": -17.5,
           "OF": -12.5 / 3}              # Lahman's undivided outfield: the mean of LF, CF and RF
POS_NAME = {2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF", "DH": "DH", "OF": "OF"}
RUN_SB = 0.2
STAB_PA = 220.0
PROXY_RUNS_PER_PLAY = 0.75
PROXY_REGRESS = 0.25
COLUMNS = ["game_date", "home_team", "away_team", "inning", "inning_topbot", "batter", "pitcher", "stand", "p_throws",
           "outs_when_up", "bat_score", "fld_score", "post_bat_score", "on_1b", "on_2b", "on_3b", "events", "description",
           "type", "balls", "strikes", "woba_value", "woba_denom", "bb_type"] + [f"fielder_{i}" for i in range(2, 10)]


def _sid(x) -> str | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    try:
        return str(int(x))
    except (TypeError, ValueError):
        s = str(x)
        return s if s and s != "nan" else None


# ============================================================================ RE-based runner values

def runner_values(re: np.ndarray) -> dict:
    """Average marginal RE of a runner at base m (1..3) with o outs, and the average cost of an out."""
    bv = np.zeros((3, 4))
    for o in range(3):
        for m in (1, 2, 3):
            bit = 1 << (m - 1)
            diffs = [re[o, b] - re[o, b & ~bit] for b in range(8) if b & bit]
            bv[o, m] = float(np.mean(diffs))
    re4 = np.vstack([re, np.zeros((1, 8))])
    out_cost = np.array([float(np.mean(re4[o] - re4[o + 1])) for o in range(3)])
    return {"base": bv, "out_cost": out_cost}


def extra_bases(pa: pd.DataFrame, re: np.ndarray, r_cols=("r1", "r2", "r3"), n_cols=("n1", "n2", "n3")) -> pd.DataFrame:
    """Runner opportunities on singles and doubles with their RE value against the league average.
    `pa` needs hkey, cls, outs_when_up, runs_pa, last_in_half, start runner ids r1..r3 and next-state ids
    n1..n3 plus next outs n_outs. Returns rows: runner, event, base, outs, dest, value, x_value, runs."""
    rv = runner_values(re)
    rows = []
    sub = pa[pa["cls"].isin(["1B", "2B"]) & ~pa["last_in_half"].astype(bool)]
    if not len(sub):
        return pd.DataFrame(columns=["runner", "event", "base", "outs", "dest", "value"])
    R = sub[list(r_cols)].to_numpy(object); N = sub[list(n_cols)].to_numpy(object)
    cls = sub["cls"].to_numpy(); outs = sub["outs_when_up"].to_numpy(int); nouts = sub["n_outs"].to_numpy(int)
    runs = sub["runs_pa"].to_numpy(float)
    for i in range(len(sub)):
        starts = [(k + 1, R[i, k]) for k in range(3) if R[i, k] is not None]
        if not starts:
            continue
        nxt = {N[i, k]: k + 1 for k in range(3) if N[i, k] is not None}
        missing = [r for _, r in starts if r not in nxt]
        dest_missing = 4 if runs[i] >= len(missing) else (0 if runs[i] == 0 else None)
        for base, r in starts:
            if cls[i] == "1B" and base == 3:
                continue
            if cls[i] == "2B" and base >= 2:
                continue
            dest = nxt.get(r, dest_missing)
            if dest is None:
                continue
            oa = min(max(nouts[i], 0), 2)
            if dest == 4:
                v = 1.0
            elif dest == 0:
                v = -rv["out_cost"][min(outs[i], 2)]
            else:
                v = rv["base"][oa, dest]
            rows.append((r, cls[i], base, outs[i], dest, v))
    d = pd.DataFrame(rows, columns=["runner", "event", "base", "outs", "dest", "value"])
    if len(d):
        d["x_value"] = d.groupby(["event", "base", "outs"])["value"].transform("mean")
        d["runs"] = d["value"] - d["x_value"]
        d["extra"] = (d["dest"] >= d["base"] + (1 if d["event"].iloc[0] == "1B" else 2) + 1).astype(int)
    return d


def statcast_steals(p: pd.DataFrame) -> pd.DataFrame:
    """Estimated SB / CS per runner from consecutive pitches of the same PA (see module doc)."""
    if not len(p):
        return pd.DataFrame(columns=["runner", "kind"])
    same = (p["game_pk"].to_numpy()[1:] == p["game_pk"].to_numpy()[:-1]) & \
           (p["at_bat_number"].to_numpy()[1:] == p["at_bat_number"].to_numpy()[:-1])
    desc = p["description"].astype(str).to_numpy()[:-1]
    ok = same & ~np.isin(desc, ["blocked_ball", "hit_into_play", "hit_by_pitch", "pitchout", "swinging_strike_blocked"])
    rows = []
    cur = [p[c].to_numpy(object)[:-1] for c in ("on_1b", "on_2b", "on_3b")]
    nxt = [p[c].to_numpy(object)[1:] for c in ("on_1b", "on_2b", "on_3b")]
    o0 = p["outs_when_up"].to_numpy(float)[:-1]; o1 = p["outs_when_up"].to_numpy(float)[1:]
    s0 = p["bat_score"].to_numpy(float)[:-1]; s1 = p["bat_score"].to_numpy(float)[1:]
    idx = np.where(ok)[0]
    for i in idx:
        for k in range(2):           # steals of 2nd and 3rd
            r = cur[k][i]
            if r is None or (isinstance(r, float) and np.isnan(r)):
                continue
            if _same(nxt[k + 1][i], r) and not _same(nxt[k][i], r):
                rows.append((_sid(r), "sb"))
            elif not any(_same(nxt[j][i], r) for j in range(3)) and o1[i] == o0[i] + 1 and s1[i] == s0[i]:
                rows.append((_sid(r), "cs"))
    # steals recorded as the event of a pitch (inning-ending caught stealing, Savant's stolen_base_* rows)
    ev = p["events"].astype(object).fillna("").astype(str).to_numpy()
    base_col = {"2b": "on_1b", "3b": "on_2b", "home": "on_3b"}
    for i in np.where(np.char.find(ev.astype(str), "stealing") >= 0)[0].tolist() +             np.where(np.char.startswith(ev.astype(str), "stolen_base"))[0].tolist():
        e = ev[i]
        tgt = e.rsplit("_", 1)[-1]
        col = base_col.get(tgt)
        if col is None:
            continue
        r = p[col].iloc[i]
        if r is None or (isinstance(r, float) and np.isnan(r)):
            continue
        rows.append((_sid(r), "sb" if e.startswith("stolen_base") else "cs"))
    return pd.DataFrame(rows, columns=["runner", "kind"])


def _same(a, b) -> bool:
    if a is None or b is None:
        return False
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return False


def wsb(steals: pd.DataFrame, opps: pd.Series, runs_per_out: float) -> pd.DataFrame:
    """wSB per runner: SB*runSB + CS*runCS - lgwSB * opportunities (1B + BB + HBP - IBB)."""
    run_cs = -(2 * runs_per_out + 0.075)
    c = steals.groupby(["runner", "kind"]).size().unstack(fill_value=0) if len(steals) else pd.DataFrame()
    for k in ("sb", "cs"):
        if k not in c:
            c[k] = 0
    c = c.reindex(c.index.union(opps.index), fill_value=0)
    lg = float((c["sb"].sum() * RUN_SB + c["cs"].sum() * run_cs) / max(opps.sum(), 1))
    o = opps.reindex(c.index).fillna(0)
    c["wsb"] = c["sb"] * RUN_SB + c["cs"] * run_cs - lg * o
    return c


# ============================================================================ playing time

def defensive_games(pa: pd.DataFrame) -> pd.DataFrame:
    """Games by position per player from fielder_2..9 at each PA; DH games for batters who batted in a game
    without fielding. Returns long rows: pid, pos, games."""
    fld_team = np.where(pa["half"].to_numpy() == 0, pa["home_team"].to_numpy(), pa["away_team"].to_numpy())
    base = pd.DataFrame({"game_pk": pa["game_pk"].to_numpy(), "team": fld_team})
    tot = base.groupby(["game_pk", "team"]).size().rename("team_pa")
    parts = []
    for pos in range(2, 10):
        c = f"fielder_{pos}"
        if c not in pa:
            continue
        d = base.assign(pid=pa[c].map(_sid).to_numpy(), pos=pos)
        parts.append(d[d["pid"].notna()])
    if not parts:
        return pd.DataFrame(columns=["pid", "pos", "games"])
    d = pd.concat(parts)
    g = d.groupby(["game_pk", "team", "pid", "pos"]).size().rename("n").reset_index()
    g = g.join(tot, on=["game_pk", "team"])
    g["games"] = g["n"] / g["team_pa"]
    fielded = set(zip(g["game_pk"], g["pid"]))
    out = g.groupby(["pid", "pos"])["games"].sum().reset_index()
    bat = pd.DataFrame({"game_pk": pa["game_pk"].to_numpy(), "pid": pa["batter"].map(_sid).to_numpy()}).drop_duplicates()
    dh = bat[[(gp, p) not in fielded for gp, p in zip(bat["game_pk"], bat["pid"])]]
    if len(dh):
        out = pd.concat([out, dh.groupby("pid").size().rename("games").reset_index().assign(pos="DH")], ignore_index=True)
    return out


def positional_runs(games: pd.DataFrame) -> pd.DataFrame:
    g = games.copy()
    g["adj"] = g["pos"].map(lambda p: POS_ADJ.get(p, POS_ADJ.get(int(p) if str(p).isdigit() else p, 0.0))) * g["games"] / 162.0
    out = g.groupby("pid").agg(pos_runs=("adj", "sum"), games_fielded=("games", "sum"))
    prim = g.sort_values("games", ascending=False).drop_duplicates("pid").set_index("pid")["pos"]
    out["pos"] = prim.map(lambda p: POS_NAME.get(p, POS_NAME.get(int(p) if str(p).isdigit() else p, str(p))))
    return out


# ============================================================================ pitching

def pitching_lines(pa: pd.DataFrame) -> pd.DataFrame:
    """Per pitcher: BF, outs recorded, runs while pitching, games, starts, gmLI, xwOBA_n against (sum)."""
    d = pa.copy()
    d["pid"] = d["pitcher"].map(_sid)
    d["outs_rec"] = (np.minimum(d["end_outs"], 3) - d["outs_when_up"]).clip(lower=0)
    first = d.groupby(["game_pk", "half"], sort=False).head(1)
    starters = set(zip(first["game_pk"], first["pid"]))
    entry = d.groupby(["game_pk", "pid"], sort=False).head(1)
    g = d.groupby("pid")
    t = pd.DataFrame({"bf": g.size(), "outs": g["outs_rec"].sum(), "runs": g["runs_pa"].sum(), "games": g["game_pk"].nunique()})
    t["starts"] = pd.Series([p for _, p in starters]).value_counts().reindex(t.index).fillna(0)
    if "li" in entry:
        t["gmli"] = entry.groupby("pid")["li"].mean().reindex(t.index)
    if "xwoba_n" in d:
        t["x_num"] = g["xwoba_n"].sum()
        t["den"] = g["denom"].sum()
    return t


# ============================================================================ assembling WAR

def assemble(bat: pd.DataFrame, pit: pd.DataFrame, lw: dict, team_games: float, park_runs: dict | None = None) -> dict:
    """Pure assembly from component tables.

    bat: index pid, columns pa, batting (runs, above average), baserunning, fielding, framing, pos_runs
         (missing columns are zero), optional bat_results, team (for park adjustment of results).
    pit: index pid, columns bf, outs, runs, starts, games, gmli (optional), xruns (optional), park (optional).
    Returns {"batters", "pitchers", "constants"} with WAR columns; totals hit the replacement targets."""
    rpw = float(lw.get("rpw") or 10.0)
    target = WAR_PER_SEASON * team_games / GAMES_FULL
    b = bat.copy()
    for c in ("batting", "baserunning", "fielding", "framing", "pos_runs"):
        if c not in b:
            b[c] = 0.0
        b[c] = b[c].fillna(0.0)
    comp = b["batting"] + b["baserunning"] + b["fielding"] + b["framing"] + b["pos_runs"]
    pa_tot = max(float(b["pa"].sum()), 1.0)
    lg_adj = -float(comp.sum()) / pa_tot
    b["league_adj"] = lg_adj * b["pa"]
    repl_per_pa = REPL_SHARE_POS * target * rpw / pa_tot
    b["replacement"] = repl_per_pa * b["pa"]
    b["rar"] = comp + b["league_adj"] + b["replacement"]
    b["war"] = b["rar"] / rpw
    p = pit.copy()
    out = {"batters": b, "constants": {"rpw": rpw, "target_total": target, "repl_runs_per_pa": repl_per_pa,
                                       "league_adj_per_pa": lg_adj}}
    if len(p):
        ip = p["outs"] / 3.0
        pf = p["park"].map(lambda t: (park_runs or {}).get(t, 1.0)) if "park" in p else 1.0
        adj = (1.0 + pf) / 2.0
        rel = p["starts"] < 0.5 * p["games"]
        gmli = p["gmli"].astype(float).fillna(1.0) if "gmli" in p else pd.Series(1.0, index=p.index)
        lev = pd.Series(np.where(rel, (1 + gmli) / 2, 1.0), index=p.index)
        pit_target = REPL_SHARE_PIT * target * rpw
        for name, runs in (("ra9", p["runs"] / adj), ("x", p["xruns"] if "xruns" in p else None)):
            if runs is None:
                continue
            ra9 = 9 * runs / ip.replace(0, np.nan)
            # replacement RA9 solving sum((repl - RA9) * IP / 9 * lev) = pit_target
            w = (ip / 9 * lev).fillna(0.0)
            repl = float((pit_target + (runs.fillna(0) * lev).sum()) / max(w.sum(), 1e-9))
            p[f"ra9_{name}"] = ra9
            p[f"war_{name}"] = ((repl * ip / 9 - runs.fillna(0)) * lev) / rpw
            out["constants"][f"repl_ra9_{name}"] = repl
        p["ip"] = ip
        p["reliever"] = rel
    out["pitchers"] = p
    return out


def season_war(pitches: pd.DataFrame, store: dict | None = None, level: str = "mlb", season: int | None = None,
               xw: dict | None = None, fielding: pd.DataFrame | None = None, framing_t: pd.DataFrame | None = None,
               park: dict | None = None, stab_pa: float | None = None) -> dict:
    """Bullpen WAR for one season's pitch table. Component tables can be supplied (tests, cached runs);
    missing ones are computed from `pitches`."""
    from oddsmarkets.baseball.models import re24, xwoba
    p = _c.prepare_pitches(pitches.copy(), game_types=("R",))
    rs = re24.statcast_season(level, season or 0, pitches=p, with_wpa=True, count=False)
    pa = rs["pa"]
    lw = rs["lw"]
    re = rs["re"]["re"]
    # xwOBA+
    if xw is None:
        xw = xwoba.score_season(p, store)
    xpa = xw["pa"]
    key = ["game_pk", "at_bat_number"]
    pa = pa.merge(xpa[key + ["woba", "denom", "xwoba", "xwoba_n"]], on=key, how="left")
    lg_x = float(xpa["xwoba_n"].sum() / xpa["denom"].sum())
    lg_w = float(xpa["woba"].sum() / xpa["denom"].sum())
    scale = float(lw.get("woba_scale") or 1.2)
    # woba scale on Savant's weights: Savant's woba_value already scaled, so convert with our scale ratio
    k = float(stab_pa or STAB_PA)
    pa["pid"] = pa["batter"].map(_sid)
    g = pa.groupby("pid")
    bat = pd.DataFrame({"pa": g.size(), "den": g["denom"].sum(), "x_num": g["xwoba_n"].sum(), "w_num": g["woba"].sum()})
    bat["xwoba_n"] = bat["x_num"] / bat["den"].replace(0, np.nan)
    bat["x_reg"] = (bat["x_num"] + k * lg_x) / (bat["den"] + k)
    bat["batting"] = (bat["x_reg"] - lg_x) / scale * bat["den"]
    bat["bat_results"] = (bat["w_num"] / bat["den"].replace(0, np.nan) - lg_w) / scale * bat["den"]
    # baserunning
    pa = _runner_ids(pa)
    eb = extra_bases(pa, re)
    ebr = eb.groupby("runner")["runs"].sum() if len(eb) else pd.Series(dtype=float)
    steals = statcast_steals(p)
    opps = pa.assign(o=pa["cls"].isin(["1B", "BB", "HBP"]).astype(int)).groupby("pid")["o"].sum()
    ws = wsb(steals, opps, float(lw.get("runs_per_out") or 0.17))
    bat["ebt_runs"] = ebr.reindex(bat.index).fillna(0.0)
    bat["wsb"] = ws["wsb"].reindex(bat.index).fillna(0.0)
    bat["sb_est"] = ws["sb"].reindex(bat.index).fillna(0)
    bat["cs_est"] = ws["cs"].reindex(bat.index).fillna(0)
    bat["baserunning"] = bat["ebt_runs"] + bat["wsb"]
    # fielding and framing
    if fielding is None:
        from oddsmarkets.baseball.models import catchprob
        cw = catchprob._lw_from({"lw": lw.get("lw"), })
        fielding = catchprob.fielder_table(catchprob.score(p, cw))
    bat["fielding"] = fielding.set_index("pid")["runs"].reindex(bat.index).fillna(0.0) if len(fielding) else 0.0
    if framing_t is None:
        from oddsmarkets.baseball.models import framing
        d = framing.called_pitches(p, store)
        m = framing.fit(d)
        sv = rs.get("counts") or re24.count_values(p, pa)
        framing_t = framing.framing_table(d, m, sv["strike_value"])
    bat["framing"] = framing_t.set_index("pid")["runs"].reindex(bat.index).fillna(0.0) if len(framing_t) else 0.0
    # positions
    games = defensive_games(pa)
    pr = positional_runs(games)
    bat = bat.join(pr, how="left")
    bat["pos_runs"] = bat["pos_runs"].fillna(0.0)
    # pitchers
    pa["denom"] = pa["denom"].fillna(0.0)
    pl = pitching_lines(pa)
    lg_rpa = float(pa["runs_pa"].sum() / len(pa))
    pl["xruns"] = pl["bf"] * lg_rpa + (pl["x_num"] - lg_x * pl["den"]) / scale
    fld_team = np.where(pa["half"] == 0, pa["home_team"], pa["away_team"])
    pl["park"] = pd.Series(fld_team, index=pa.index).groupby(pa["pitcher"].map(_sid)).agg(lambda s: s.mode().iloc[0])
    # position players vs pitchers: a player is a pitcher when he faced more batters than he had PAs
    is_pit = pl["bf"].reindex(bat.index).fillna(0) > bat["pa"]
    park_runs = {k2: v["factors"].get("runs", 1.0) for k2, v in ((park or {}).get("parks") or {}).items()}
    team_games = float(pa.groupby("game_pk").ngroups * 2)
    res = assemble(bat[~is_pit], pl, lw, team_games, park_runs)
    res["extra_bases"] = eb
    res["lw"] = lw
    res["team_games"] = team_games
    return res


def _runner_ids(pa: pd.DataFrame) -> pd.DataFrame:
    pa = pa.copy()
    for k, c in ((1, "on_1b"), (2, "on_2b"), (3, "on_3b")):
        pa[f"r{k}"] = pa[c].map(_sid) if c in pa else None
        pa[f"n{k}"] = pa[f"r{k}"].shift(-1)
    pa["n_outs"] = pa["outs_when_up"].shift(-1).fillna(3).astype(int)
    same = pa["hkey"].shift(-1) == pa["hkey"]
    for k in (1, 2, 3):
        pa.loc[~same, f"n{k}"] = None
    return pa


# ============================================================================ season driver (Statcast)

def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    path = _c.pitch_path(level, season)
    if not path.exists():
        return {"ok": False, "reason": f"no pitch table for {level} {season}"}

    def build():
        from oddsmarkets.baseball.models import catchprob, framing, parks, xwoba
        p = _c.load_pitches(level, season, list(dict.fromkeys(COLUMNS + xwoba.COLUMNS + catchprob.COLUMNS + framing.COLUMNS)))
        if p is None or not len(p):
            return {"ok": False, "reason": "empty"}
        store = _c.load_store(level, season)
        fc = catchprob.for_season(level, season)
        fielding = _c_frame(fc.get("fielders")) if fc.get("ok") else None
        fr = framing.for_season(level, season)
        framing_t = _c_frame(fr.get("catchers")) if fr.get("ok") else None
        try:
            pk = parks.park_factors(level, season)
        except Exception:
            pk = None
        stab = None
        try:
            from oddsmarkets.baseball.models import stabilise
            stab = stabilise.shrink_k("xwoba", level)
        except Exception:
            stab = None
        xw = xwoba.score_season(p, store, xwoba.sprint_map(season))
        res = season_war(p, store, level, season, xw=xw, fielding=fielding, framing_t=framing_t, park=pk, stab_pa=stab)
        b = res["batters"].reset_index().rename(columns={"index": "pid"})
        pt = res["pitchers"].reset_index().rename(columns={"index": "pid"})
        cols_b = ["pid", "pos", "pa", "xwoba_n", "batting", "bat_results", "baserunning", "ebt_runs", "wsb", "sb_est",
                  "cs_est", "fielding", "framing", "pos_runs", "league_adj", "replacement", "rar", "war"]
        cols_p = ["pid", "games", "starts", "bf", "ip", "runs", "ra9_ra9", "war_ra9", "xruns", "ra9_x", "war_x", "gmli", "reliever"]
        return {"ok": True, "version": MODEL_VERSION, "constants": res["constants"],
                "totals": {"batters": float(b["war"].sum()), "pitchers_ra9": float(pt["war_ra9"].sum()),
                           "pitchers_x": float(pt["war_x"].sum())},
                "batters": _c.frame_rows(b[[c for c in cols_b if c in b]].sort_values("war", ascending=False)),
                "pitchers": _c.frame_rows(pt[[c for c in cols_p if c in pt]].sort_values("war_ra9", ascending=False))}
    key = _c.file_key(path, MODEL_VERSION, _c.FITTED / f"stabilise_{level}.json", _c.FITTED / f"parks_{level}.json")
    return _c.cached("war", f"{level}_{season}", key, build, use_cache)


def _c_frame(obj) -> pd.DataFrame | None:
    if not obj:
        return None
    df = pd.DataFrame(obj["rows"], columns=obj["cols"])
    df["pid"] = df["pid"].astype(str)
    return df


# ============================================================================ historical (Retrosheet)

def lahman_fielding_proxy(season: int, lw_out: float = -0.27) -> pd.DataFrame | None:
    """Fielding runs proxy and games by position from Lahman Fielding.csv (bbref ids). Marked proxy."""
    try:
        from oddsmarkets.baseball.sources import lahman
        f = lahman.load("Fielding.csv")
    except Exception:
        f = None
    if f is None:
        return None
    f = f[f["yearID"] == int(season)].copy()
    if not len(f):
        return None
    posmap = {"C": 2, "1B": 3, "2B": 4, "3B": 5, "SS": 6, "LF": 7, "CF": 8, "RF": 9, "OF": "OF"}
    f = f[f["POS"].isin(posmap)].copy()
    f["pos"] = f["POS"].map(posmap)
    for c in ("PO", "A", "E", "G", "InnOuts"):
        f[c] = pd.to_numeric(f.get(c), errors="coerce")
    exp = f["InnOuts"].notna() & (f["InnOuts"] > 0)
    f["inn"] = np.where(exp, f["InnOuts"] / 3.0, f["G"] * 8.5)
    f["plays"] = f["PO"].fillna(0) + f["A"].fillna(0)
    for pp in (2, 3):     # catcher putouts are strikeouts, first basemen's are mostly other fielders' throws
        if (f["pos"] == pp).any():
            f.loc[f["pos"] == pp, "plays"] = f.loc[f["pos"] == pp, "A"].fillna(0)
    # team context: a staff that strikes out fewer batters puts more balls in play for its fielders, so the
    # opportunity per inning is the team's outs on balls in play per inning (Lahman Teams: IPouts - SO)
    f["opp"] = 1.0
    try:
        from oddsmarkets.baseball.sources import lahman
        t = lahman.load("Teams.csv")
        t = t[t["yearID"] == int(season)]
        rate = ((pd.to_numeric(t["IPouts"], errors="coerce") - pd.to_numeric(t["SOA"], errors="coerce"))
                / (pd.to_numeric(t["IPouts"], errors="coerce") / 3.0))
        f["opp"] = f["teamID"].map(dict(zip(t["teamID"], rate))).astype(float)
        f["opp"] = f["opp"].fillna(f["opp"].mean())
    except Exception:
        pass
    f["oinn"] = f["inn"] * f["opp"]
    lg = f.groupby("pos").agg(pl=("plays", "sum"), inn=("oinn", "sum"), e=("E", "sum"))
    f["x_plays"] = f["pos"].map(lg["pl"] / lg["inn"]) * f["oinn"]
    f["x_e"] = f["pos"].map(lg["e"] / lg["inn"]) * f["oinn"]
    f["runs"] = PROXY_REGRESS * PROXY_RUNS_PER_PLAY * (f["plays"] - f["x_plays"])         - PROXY_REGRESS * PROXY_RUNS_PER_PLAY * (f["E"].fillna(0) - f["x_e"])
    f["games"] = f["inn"] / 9.0
    return f.groupby(["playerID", "pos"]).agg(runs=("runs", "sum"), games=("games", "sum")).reset_index()


def historical_season(season: int, df: pd.DataFrame | None = None, people: dict | None = None) -> dict | None:
    """Retrosheet-era WAR for one season (batting by linear weights, steals and extra bases, proxy fielding,
    positional from Lahman, RA9 pitching). Ids: MLBAM pid when the crosswalk knows the Retrosheet id, else 'r:<id>'."""
    from oddsmarkets.baseball.models import re24
    df = _c.load_pa(season) if df is None else df
    if df is None or not len(df):
        return None
    for c in df.columns:
        if isinstance(df[c].dtype, pd.CategoricalDtype):
            df[c] = df[c].astype(object)
    res = re24.retro_season(season, df, with_wpa=False)
    pa = res["pa"]
    lw = res["lw"]
    w = lw["woba_w"]
    scale = lw["woba_scale"]
    maps = _c.retro_maps(people)
    r2m, b2r = maps["r2m"], maps["b2r"]

    def pid(r):
        return r2m.get(r, f"r:{r}") if r else None
    pa["wval"] = pa["cls"].map(lambda c: w.get(c, 0.0) if c in ("BB", "HBP", "1B", "2B", "3B", "HR") else 0.0)
    pa["den"] = (~pa["cls"].isin(["IBB", "CI"]) & ~pa.get("sh", pd.Series(False, index=pa.index)).astype(bool)).astype(float)
    g = pa.groupby("batter")
    bat = pd.DataFrame({"pa": g.size(), "den": g["den"].sum(), "w_num": g["wval"].sum()})
    lg_w = float(bat["w_num"].sum() / bat["den"].sum())
    bat["woba"] = bat["w_num"] / bat["den"].replace(0, np.nan)
    bat["batting"] = (bat["woba"].fillna(lg_w) - lg_w) / scale * bat["den"]
    # baserunning: steals from event text, extra bases from runner ids
    st = re24.retro_running(df[df["gtype"].astype(str) == "R"] if "gtype" in df else df)
    opps = pa.assign(o=pa["cls"].isin(["1B", "BB", "HBP"]).astype(int)).groupby("batter")["o"].sum()
    ws = wsb(st.rename(columns={"runner": "runner"}), opps, float(lw.get("runs_per_out") or 0.17))
    pa2 = pa.copy()
    for k in (1, 2, 3):
        pa2[f"r{k}"] = pa2[f"run{k}_pre"].map(lambda x: None if pd.isna(x) else str(x))
        pa2[f"n{k}"] = pa2[f"r{k}"].shift(-1)
    pa2["n_outs"] = pa2["outs_when_up"].shift(-1).fillna(3).astype(int)
    same = pa2["hkey"].shift(-1) == pa2["hkey"]
    for k in (1, 2, 3):
        pa2.loc[~same, f"n{k}"] = None
    eb = extra_bases(pa2, res["re"]["re"])
    bat["wsb"] = ws["wsb"].reindex(bat.index).fillna(0.0)
    bat["ebt_runs"] = (eb.groupby("runner")["runs"].sum() if len(eb) else pd.Series(dtype=float)).reindex(bat.index).fillna(0.0)
    bat["baserunning"] = bat["wsb"] + bat["ebt_runs"]
    fp = lahman_fielding_proxy(season)
    bat["fielding"] = 0.0
    bat["pos_runs"] = 0.0
    if fp is not None and len(fp):
        fp["retro"] = fp["playerID"].map(b2r)
        fr = fp.groupby("retro")["runs"].sum()
        bat["fielding"] = fr.reindex(bat.index).fillna(0.0)
        gp = fp.dropna(subset=["retro"]).rename(columns={"retro": "pid"})[["pid", "pos", "games"]]
        # games batted without fielding (DH and pinch-hitting) take the DH adjustment
        gbat = pa.groupby("batter")["game_pk"].nunique()
        gfld = gp.groupby("pid")["games"].sum()
        dh = (gbat - gfld.reindex(gbat.index).fillna(0.0)).clip(lower=0.0)
        dh = dh[dh > 0]
        gp = pd.concat([gp, pd.DataFrame({"pid": dh.index, "pos": "DH", "games": dh.to_numpy()})], ignore_index=True)
        pr = positional_runs(gp)
        bat["pos_runs"] = pr["pos_runs"].reindex(bat.index).fillna(0.0)
        bat["pos"] = pr["pos"].reindex(bat.index)
    # pitchers: runs and outs over every event row while on the mound
    allrows = df[df["gtype"].astype(str) == "R"] if "gtype" in df else df
    gpit = allrows.groupby("pitcher")
    pit = pd.DataFrame({"outs": gpit["outs_on_play"].sum(), "runs": gpit["runs_on_play"].sum(),
                        "games": gpit["game_id"].nunique()})
    pit["bf"] = pa.groupby("pitcher").size().reindex(pit.index).fillna(0)
    firsts = allrows.drop_duplicates(["game_id", "half"])
    pit["starts"] = firsts["pitcher"].value_counts().reindex(pit.index).fillna(0)
    is_pit = pit["bf"].reindex(bat.index).fillna(0) > bat["pa"]
    team_games = float(allrows["game_id"].nunique() * 2)
    out = assemble(bat[~is_pit], pit, lw, team_games)
    for k in ("batters", "pitchers"):
        t = out[k]
        retro_ids = list(t.index)
        t.index = [pid(i) for i in retro_ids]
        t["retro"] = retro_ids
        t["fielding_source"] = "proxy" if fp is not None else "none"
    out["lw"] = lw
    return out


def historical_for_season(season: int, use_cache: bool = True) -> dict:
    path = _c.pa_path(season)
    if not path.exists():
        return {"ok": False, "reason": f"no Retrosheet PA table for {season}"}

    def build():
        r = historical_season(season)
        if r is None:
            return {"ok": False, "reason": "empty"}
        b = r["batters"].reset_index().rename(columns={"index": "pid"})
        p = r["pitchers"].reset_index().rename(columns={"index": "pid"})
        cb = ["pid", "retro", "pos", "pa", "woba", "batting", "baserunning", "wsb", "ebt_runs", "fielding", "pos_runs",
              "league_adj", "replacement", "rar", "war", "fielding_source"]
        cp = ["pid", "retro", "games", "starts", "bf", "ip", "runs", "ra9_ra9", "war_ra9"]
        return {"ok": True, "version": MODEL_VERSION, "season": season, "constants": r["constants"],
                "batters": _c.frame_rows(b[[c for c in cb if c in b]].sort_values("war", ascending=False)),
                "pitchers": _c.frame_rows(p[[c for c in cp if c in p]].sort_values("war_ra9", ascending=False))}
    return _c.cached("war", f"retro_{season}", _c.file_key(path, MODEL_VERSION), build, use_cache)


def export_fits(level: str = "mlb") -> dict:
    """WAR is a season output; the committed piece is the constant table (documented in the methodology)."""
    out = {"version": MODEL_VERSION, "war_per_season": WAR_PER_SEASON, "games_full": GAMES_FULL,
           "share_pos": REPL_SHARE_POS, "share_pit": REPL_SHARE_PIT, "pos_adj": {str(k): v for k, v in POS_ADJ.items()},
           "run_sb": RUN_SB, "stab_pa": STAB_PA, "proxy_runs_per_play": PROXY_RUNS_PER_PLAY, "proxy_regress": PROXY_REGRESS}
    _c.write_fit("war_constants", out)
    return out
