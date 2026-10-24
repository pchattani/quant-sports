"""
teams.json: per team unit ratings with week-by-week history, tendencies, pace, fourth-down aggressiveness, schedule
against the model, QB situation, roster value and simulation odds.

Unit ratings: our team_strength (opponent-adjusted, points per game) when it answers; always alongside our
EPA units: opponent-adjusted EPA per play by unit (pass and rush offence and defence) from a ridge regression of play
EPA on offence and defence indicators, plus special-teams EPA per game.

Tendencies (offence): PROE (pass rate over expected, against nflfastR's xpass) overall and by situation (neutral early
downs, third down, red zone, leading / trailing by 8+), shotgun, no-huddle; FTN charting from 2022 (play action, RPO,
motion, screens); participation 2016-2025 (personnel groupings, formations). Defence: blitz rate, box count, pass
rushers (FTN), man / zone and coverage shells (participation). Pace: seconds per play in neutral situations and in all
situations, plays per game.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics import adapters
from oddsmarkets.nfl.analytics.context import SeasonContext, flag, num
from oddsmarkets.nfl.analytics.players import reg_plays, scrimmage

logger = logging.getLogger(__name__)
M = an.metric
METRICS = [
    M("rating", "Team rating", "Ratings", "1", desc="Points per game better than an average team on a neutral field (our "
      "team strength; our EPA rating when it is not available)."),
    M("off_rating", "Offence rating", "Ratings", "1", desc="Offensive points per game over average."),
    M("def_rating", "Defence rating", "Ratings", "1", desc="Defensive points per game over average (positive = better)."),
    M("off_epa", "Offence EPA / play", "EPA units", "epa", desc="Opponent-adjusted EPA per play (offence)."),
    M("def_epa", "Defence EPA / play", "EPA units", "epa", lower=True, desc="Opponent-adjusted EPA per play allowed."),
    M("off_pass_epa", "Pass offence EPA", "EPA units", "epa", desc="Opponent-adjusted EPA per dropback."),
    M("off_rush_epa", "Rush offence EPA", "EPA units", "epa", desc="Opponent-adjusted EPA per designed run."),
    M("def_pass_epa", "Pass defence EPA", "EPA units", "epa", lower=True, desc="Opponent-adjusted EPA per dropback allowed."),
    M("def_rush_epa", "Rush defence EPA", "EPA units", "epa", lower=True, desc="Opponent-adjusted EPA per designed run allowed."),
    M("st_epa_g", "Special teams EPA / game", "EPA units", "2", desc="EPA per game on kicks, punts and returns (net of the opponent's)."),
    M("off_success", "Offence success", "EPA units", "pct", desc="Share of plays with positive EPA."),
    M("def_success", "Defence success allowed", "EPA units", "pct", lower=True, desc="Share of opponent plays with positive EPA."),
    M("proe", "PROE", "Tendencies", "pct", scope="style", desc="Pass rate over expected (nflfastR xpass), all plays."),
    M("proe_neutral", "PROE (neutral)", "Tendencies", "pct", scope="style", desc="Pass rate over expected on early downs, win "
      "probability 20-80 %, outside the last two minutes of a half."),
    M("proe_3rd", "PROE (3rd down)", "Tendencies", "pct", scope="style", desc="Pass rate over expected on third down."),
    M("proe_rz", "PROE (red zone)", "Tendencies", "pct", scope="style", desc="Pass rate over expected inside the opponent's 20."),
    M("proe_lead", "PROE (leading 8+)", "Tendencies", "pct", scope="style", desc="Pass rate over expected when leading by 8 or more."),
    M("proe_trail", "PROE (trailing 8+)", "Tendencies", "pct", scope="style", desc="Pass rate over expected when trailing by 8 or more."),
    M("shotgun", "Shotgun rate", "Tendencies", "pct", scope="style", desc="Share of scrimmage plays from shotgun."),
    M("no_huddle", "No-huddle rate", "Tendencies", "pct", scope="style", desc="Share of plays without a huddle."),
    M("pa_rate", "Play-action rate", "Tendencies", "pct", scope="style", desc="Play action per dropback (FTN, 2022 onward)."),
    M("rpo_rate", "RPO rate", "Tendencies", "pct", scope="style", desc="Run-pass options per scrimmage play (FTN, 2022 onward)."),
    M("motion_rate", "Motion rate", "Tendencies", "pct", scope="style", desc="Pre-snap motion per scrimmage play (FTN, 2022 onward)."),
    M("screen_rate", "Screen rate", "Tendencies", "pct", scope="style", desc="Screens per pass attempt (FTN, 2022 onward)."),
    M("blitz_rate", "Blitz rate", "Defence style", "pct", scope="style", desc="Dropbacks against five or more rushers or any "
      "blitzer (FTN, 2022 onward)."),
    M("box_avg", "Box count", "Defence style", "2", scope="style", desc="Average defenders in the box (FTN 2022 onward; participation before)."),
    M("man_rate", "Man coverage rate", "Defence style", "pct", scope="style", desc="Man coverage per dropback (participation, 2016-2025)."),
    M("pressure_allowed", "Pressure rate allowed", "Pressure", "pct", lower=True, desc="Share of dropbacks under pressure "
      "(our pressure model: participation 2016-2025, modelled otherwise)."),
    M("pressure_rate_def", "Pressure rate (defence)", "Pressure", "pct", desc="Share of opponent dropbacks pressured."),
    M("ed_pass_epa", "Early-down pass EPA", "Passing", "epa", desc="EPA per dropback on first and second down (offence, raw)."),
    M("ed_pass_epa_def", "Early-down pass EPA allowed", "Passing", "epa", lower=True, desc="EPA per dropback allowed on first and "
      "second down (defence, raw)."),
    M("ed_pass_rate", "Early-down pass rate", "Passing", "pct", scope="style", desc="Share of first- and second-down plays that "
      "are dropbacks."),
    M("sack_rate_def", "Sack rate (defence)", "Pass rush", "pct", desc="Sacks per opponent dropback: the pass rush when no "
      "pressure data is available."),
    M("sack_rate_allowed", "Sack rate allowed", "Pass rush", "pct", lower=True, desc="Sacks taken per dropback: pass protection "
      "(and the quarterback's part in it)."),
    M("sec_per_play_neutral", "Seconds / play (neutral)", "Pace", "1", lower=True, scope="style",
      desc="Seconds between consecutive offensive snaps in neutral situations (lower = faster)."),
    M("sec_per_play", "Seconds / play", "Pace", "1", lower=True, scope="style", desc="Seconds between consecutive offensive snaps."),
    M("plays_pg", "Plays / game", "Pace", "1", scope="style", desc="Offensive scrimmage plays per game."),
    M("go_rate", "4th-down go rate", "Fourth down", "pct", scope="style", desc="Share of fourth downs (not end-of-half kneel / "
      "desperation) where the offence went for it."),
    M("go_rate_rec", "Go when advised", "Fourth down", "pct", desc="Share of fourth downs our model says to go for where the team went."),
    M("fd_wp_lost", "WP lost on 4th downs", "Fourth down", "pct", lower=True, desc="Win probability given up against the model's "
      "recommendation, summed over the season's fourth downs."),
]


def neutral_mask(P: pd.DataFrame) -> pd.Series:
    wp = num(P, "wp")
    down = num(P, "down")
    hs = num(P, "half_seconds_remaining")
    return (wp.between(0.2, 0.8)) & (down <= 2) & (hs > 120)


def _ridge_units(S: pd.DataFrame, lam: float = 60.0) -> tuple[dict[str, float], dict[str, float], float]:
    """EPA ~ mu + off[posteam] + def[defteam] by ridge (lam in plays); returns (off, def, mu) with def positive =
    more EPA allowed."""
    S = S[["posteam", "defteam", "epa"]].dropna()
    if len(S) < 50:
        return {}, {}, 0.0
    teams = sorted(set(S["posteam"]) | set(S["defteam"]))
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    y = S["epa"].to_numpy(float)
    mu = float(y.mean())
    r = y - mu
    oi = S["posteam"].map(ix).to_numpy()
    di = S["defteam"].map(ix).to_numpy()
    off = np.zeros(n)
    dfn = np.zeros(n)
    co = np.bincount(oi, minlength=n).astype(float)
    cd = np.bincount(di, minlength=n).astype(float)
    for _ in range(30):                                          # alternating ridge (block coordinate descent)
        off = np.bincount(oi, weights=r - dfn[di], minlength=n) / (co + lam)
        dfn = np.bincount(di, weights=r - off[oi], minlength=n) / (cd + lam)
    return ({t: float(off[ix[t]]) for t in teams}, {t: float(dfn[ix[t]]) for t in teams}, mu)


def epa_units(P: pd.DataFrame) -> dict[str, dict]:
    S = scrimmage(P)
    if not len(S):
        return {}
    S = S.assign(epa=num(S, "epa"))
    db = flag(S, "qb_dropback").fillna(0) == 1
    off, dfn, mu = _ridge_units(S)
    po, pdf, pmu = _ridge_units(S[db])
    ro, rdf, rmu = _ridge_units(S[~db])
    succ_o = (S["epa"] > 0).groupby(S["posteam"]).mean()
    succ_d = (S["epa"] > 0).groupby(S["defteam"]).mean()
    # special teams: EPA of kicking plays from the kicking team's view, net of the opponent's, per game
    K = P[P["play_type"].isin(["punt", "kickoff", "field_goal", "extra_point"])] if "play_type" in P else P.iloc[0:0]
    ste: dict[str, float] = {}
    if len(K):
        e = num(K, "epa").fillna(0)
        for_ = e.groupby(K["posteam"]).sum()
        against = e.groupby(K["defteam"]).sum()
        gp = pd.concat([P[["game_id", "posteam"]].rename(columns={"posteam": "t"}), P[["game_id", "defteam"]].rename(columns={"defteam": "t"})]
                       ).dropna().drop_duplicates().groupby("t").size()
        for t in gp.index:
            ste[t] = (float(for_.get(t, 0)) - float(against.get(t, 0))) / float(gp[t])
    out = {}
    for t in sorted(set(off) | set(dfn)):
        out[t] = {"off_epa": mu + off.get(t, 0.0), "def_epa": mu + dfn.get(t, 0.0), "off_pass_epa": pmu + po.get(t, 0.0) if po else None,
                  "def_pass_epa": pmu + pdf.get(t, 0.0) if pdf else None, "off_rush_epa": rmu + ro.get(t, 0.0) if ro else None,
                  "def_rush_epa": rmu + rdf.get(t, 0.0) if rdf else None, "st_epa_g": ste.get(t),
                  "off_success": an.fnum(succ_o.get(t)), "def_success": an.fnum(succ_d.get(t)), "_off": off.get(t, 0.0), "_def": dfn.get(t, 0.0)}
    return out


def epa_history(P: pd.DataFrame) -> dict[str, list]:
    """Week-by-week cumulative opponent-adjusted net EPA rating: [[week, net, off, def], ...] with net and its parts in
    points per game (EPA per play x the league's plays per team game; def positive = better)."""
    S = scrimmage(P)
    if not len(S) or "week" not in S:
        return {}
    S = S.assign(epa=num(S, "epa"), week=num(S, "week"))
    ppg = len(S) / max(1, S[["game_id", "posteam"]].drop_duplicates().shape[0])
    out: dict[str, list] = {}
    for w in sorted(S["week"].dropna().unique()):
        part = S[S["week"] <= w]
        off, dfn, _ = _ridge_units(part)
        for t in off:
            o, d = off[t] * ppg, -dfn.get(t, 0.0) * ppg
            out.setdefault(t, []).append([int(w), round(o + d, 2), round(o, 2), round(d, 2)])
    return out


def tendencies(P: pd.DataFrame) -> dict[str, dict]:
    S = scrimmage(P)
    if not len(S):
        return {}
    S = S.copy()
    passp = flag(S, "qb_dropback").fillna(0)
    xp = num(S, "xpass")
    S["_pass"], S["_xp"] = passp, xp
    S["_oe"] = (passp - xp).where(xp.notna())
    neutral = neutral_mask(S)
    down = num(S, "down")
    yl = num(S, "yardline_100")
    sd = num(S, "score_differential")
    sit = {"proe": pd.Series(True, index=S.index), "proe_neutral": neutral, "proe_3rd": down == 3, "proe_rz": yl <= 20,
           "proe_lead": sd >= 8, "proe_trail": sd <= -8}
    out: dict[str, dict] = {}
    g_all = S.groupby("posteam")
    for k, m in sit.items():
        v = S[m].groupby("posteam")["_oe"].mean()
        for t, x in v.items():
            out.setdefault(t, {})[k] = an.fnum(x)
    for k, c in (("shotgun", "shotgun"), ("no_huddle", "no_huddle")):
        v = flag(S, c).groupby(S["posteam"]).mean()
        for t, x in v.items():
            out.setdefault(t, {})[k] = an.fnum(x)
    db = passp == 1
    if "is_play_action" in S and S["is_play_action"].notna().any():
        for k, c, base in (("pa_rate", "is_play_action", db), ("rpo_rate", "is_rpo", None), ("motion_rate", "is_motion", None),
                           ("screen_rate", "is_screen_pass", db)):
            if c not in S:
                continue
            sub = S if base is None else S[base]
            v = flag(sub, c).groupby(sub["posteam"]).mean()
            for t, x in v.items():
                out.setdefault(t, {})[k] = an.fnum(x)
        D = S[db]
        bl = ((num(D, "n_blitzers") > 0) | (num(D, "n_pass_rushers") >= 5)).astype(float).where(num(D, "n_pass_rushers").notna())
        for t, x in bl.groupby(D["defteam"]).mean().items():
            out.setdefault(t, {})["blitz_rate"] = an.fnum(x)
        for t, x in num(S, "n_defense_box").groupby(S["defteam"]).mean().items():
            out.setdefault(t, {})["box_avg"] = an.fnum(x)
    if "defense_man_zone_type" in S and S["defense_man_zone_type"].notna().any():
        D = S[db & S["defense_man_zone_type"].notna()]
        v = (D["defense_man_zone_type"].astype(str).str.upper().str.startswith("MAN")).groupby(D["defteam"]).mean()
        for t, x in v.items():
            out.setdefault(t, {})["man_rate"] = an.fnum(x)
        if "box_avg" not in next(iter(out.values()), {}):
            for t, x in num(S, "defenders_in_box").groupby(S["defteam"]).mean().items():
                out.setdefault(t, {})["box_avg"] = an.fnum(x)
    # pace
    S2 = S.sort_values(["game_id", "play_id"])
    gs = num(S2, "game_seconds_remaining")
    same = (S2["game_id"] == S2["game_id"].shift(1)) & (S2["posteam"] == S2["posteam"].shift(1)) & \
           (num(S2, "drive") == num(S2, "drive").shift(1)) & (num(S2, "qtr") == num(S2, "qtr").shift(1))
    dt = (gs.shift(1) - gs).where(same & (gs.shift(1) - gs).between(1, 60))
    S2 = S2.assign(_dt=dt)
    nm = neutral_mask(S2)
    for t, x in S2.groupby("posteam")["_dt"].mean().items():
        out.setdefault(t, {})["sec_per_play"] = an.fnum(x)
    for t, x in S2[nm].groupby("posteam")["_dt"].mean().items():
        out.setdefault(t, {})["sec_per_play_neutral"] = an.fnum(x)
    ppg = S.groupby("posteam").size() / g_all["game_id"].nunique()
    for t, x in ppg.items():
        out.setdefault(t, {})["plays_pg"] = an.fnum(x)
    return out


def passing_extras(P: pd.DataFrame) -> dict[str, dict]:
    """Early-down passing (first and second down: EPA per dropback for and against, the dropback rate) and the sack
    rates (per dropback, defence and offence): the league page's early-down passing and pass rush, raw per team."""
    S = scrimmage(P)
    if not len(S):
        return {}
    db = flag(S, "qb_dropback").fillna(0) == 1
    ed = num(S, "down").isin([1, 2])
    epa = num(S, "epa")
    sack = flag(S, "sack").fillna(0)
    out: dict[str, dict] = {}
    E = S[ed & db]
    for col, key in (("posteam", "ed_pass_epa"), ("defteam", "ed_pass_epa_def")):
        for t, x in epa[ed & db].groupby(E[col]).mean().items():
            out.setdefault(t, {})[key] = an.fnum(x)
    for t, x in db[ed].astype(float).groupby(S.loc[ed, "posteam"]).mean().items():
        out.setdefault(t, {})["ed_pass_rate"] = an.fnum(x)
    D = S[db]
    for col, key in (("defteam", "sack_rate_def"), ("posteam", "sack_rate_allowed")):
        for t, x in sack[db].groupby(D[col]).mean().items():
            out.setdefault(t, {})[key] = an.fnum(x)
    return out


def personnel(P: pd.DataFrame) -> dict[str, dict]:
    """Offensive personnel groupings ("11", "12", ...) and formations, share and EPA per play (participation)."""
    S = scrimmage(P)
    if "offense_personnel" not in S or not S["offense_personnel"].notna().any():
        return {}
    S = S[S["offense_personnel"].notna()].copy()
    S["_grp"] = S["offense_personnel"].map(personnel_code)
    S["_epa"] = num(S, "epa")
    S["_pass"] = flag(S, "qb_dropback").fillna(0)
    out: dict[str, dict] = {}
    for col, key in (("_grp", "personnel"), ("offense_formation", "formation")):
        if col not in S:
            continue
        g = S.groupby(["posteam", col]).agg(n=("_epa", "size"), epa=("_epa", "mean"), pass_rate=("_pass", "mean")).reset_index()
        tot = S.groupby("posteam").size()
        for t, sub in g.groupby("posteam"):
            sub = sub.sort_values("n", ascending=False).head(6)
            out.setdefault(t, {})[key] = [{"group": str(r[col]), "share": an.rnd(r["n"] / tot[t], 3), "epa": an.rnd(r["epa"], 3),
                                           "pass_rate": an.rnd(r["pass_rate"], 3), "n": int(r["n"])} for r in sub.to_dict("records")]
    return out


def personnel_code(s: Any) -> str:
    """"1 RB, 1 TE, 3 WR" -> "11" (RBs then TEs); other strings unchanged."""
    if not isinstance(s, str):
        return "other"
    rb = te = 0
    for part in s.split(","):
        bits = part.strip().split(" ")
        if len(bits) >= 2 and bits[0].isdigit():
            if bits[1] == "RB":
                rb = int(bits[0])
            elif bits[1] == "TE":
                te = int(bits[0])
    return f"{rb}{te}"


def fourth_rates(P: pd.DataFrame) -> dict[str, dict]:
    D = P[(num(P, "down") == 4) & P["play_type"].isin(["pass", "run", "punt", "field_goal"])] if "play_type" in P else P.iloc[0:0]
    if not len(D):
        return {}
    wp = num(D, "wp")
    hs = num(D, "half_seconds_remaining")
    D = D[(hs > 120) & wp.between(0.05, 0.95)]
    go = D["play_type"].isin(["pass", "run"]).astype(float)
    out: dict[str, dict] = {}
    for t, x in go.groupby(D["posteam"]).mean().items():
        out.setdefault(t, {})["go_rate"] = an.fnum(x)
    if "fd_rec" in D and D["fd_rec"].notna().any():
        rec_go = D["fd_rec"].astype(str).str.lower().str.startswith("go")
        for t, x in go[rec_go].groupby(D.loc[rec_go, "posteam"]).mean().items():
            out.setdefault(t, {})["go_rate_rec"] = an.fnum(x)
        if "fd_wp_lost" in D:
            for t, x in num(D, "fd_wp_lost").fillna(0).groupby(D["posteam"]).sum().items():
                out.setdefault(t, {})["fd_wp_lost"] = an.fnum(x)
    return out


def qb_situation(P: pd.DataFrame, cat: dict | None) -> dict[str, list]:
    S = scrimmage(P)
    if not len(S):
        return {}
    pid = S["passer_id"] if "passer_id" in S else S.get("passer_player_id")
    if pid is None:
        return {}
    D = S[(flag(S, "qb_dropback").fillna(0) == 1) & pid.notna()].assign(_pid=pid)
    out: dict[str, list] = {}
    last_game = D.sort_values("game_id").groupby("posteam")["game_id"].last()
    for t, sub in D.groupby("posteam"):
        g = sub.groupby("_pid").agg(dropbacks=("game_id", "size"), games=("game_id", "nunique"), epa=("epa", "mean"),
                                    last=("game_id", "max")).sort_values("dropbacks", ascending=False).head(4)
        rows = []
        for p, r in g.iterrows():
            c = ((cat or {}).get("players") or {}).get(str(p)) or {}
            rows.append({"pid": str(p), "name": c.get("name"), "dropbacks": int(r["dropbacks"]), "games": int(r["games"]),
                         "epa_db": an.rnd(r["epa"], 3), "composite": (c.get("values") or {}).get("composite"),
                         "started_last": r["last"] == last_game.get(t)})
        out[t] = rows
    return out


def build(ctx: SeasonContext, cat: dict | None, sim: dict | None, cards: list[dict] | None) -> dict | None:
    P = reg_plays(ctx)
    have_plays = bool(len(P))
    units = epa_units(P) if have_plays else {}
    tend = tendencies(P) if have_plays else {}
    extra = passing_extras(P) if have_plays else {}
    pers = personnel(P) if have_plays else {}
    fourth = fourth_rates(P) if have_plays else {}
    qbs = qb_situation(P, cat) if have_plays else {}
    tr = adapters.team_ratings(ctx, history=ctx.full)
    press = adapters.team_pressure(ctx)
    hist = epa_history(P) if have_plays and ctx.full and not (tr or {}).get("history") else {}
    ppg = 0.0
    if have_plays:
        S = scrimmage(P)
        ppg = len(S) / max(1, S[["game_id", "posteam"]].drop_duplicates().shape[0])
    # records from the store
    rec = records(ctx)
    roster_value: dict[str, float] = {}
    for p, r in ((cat or {}).get("players") or {}).items():
        v = (r.get("values") or {}).get("value")
        if r.get("team") and v is not None:
            roster_value[r["team"]] = roster_value.get(r["team"], 0.0) + float(v)
    teams = {}
    for t, info in ctx.teams.items():
        u = units.get(t, {})
        vals: dict[str, Any] = {k: v for k, v in u.items() if not k.startswith("_")}
        vals.update(tend.get(t, {}))
        vals.update(extra.get(t, {}))
        vals.update(fourth.get(t, {}))
        vals.update({k: v for k, v in (press.get(t) or {}).items() if k in ("pressure_allowed", "pressure_rate_def")})
        epa_off = u.get("_off", 0.0) * ppg if u else None
        epa_def = -u.get("_def", 0.0) * ppg if u else None
        c = ((tr or {}).get("teams") or {}).get(t) or {}
        vals["off_rating"] = c.get("off") if c.get("off") is not None else epa_off
        vals["def_rating"] = c.get("def") if c.get("def") is not None else epa_def
        vals["rating"] = c.get("overall") if c.get("overall") is not None else (
            (epa_off or 0) + (epa_def or 0) + (u.get("st_epa_g") or 0) if u else None)
        sched = [k for k in (cards or []) if t in (k.get("home"), k.get("away"))]
        teams[t] = {**info, "values": vals, "rank": {}, "record": rec.get(t),
                    "units": {"source": "team_strength" if c else "epa", "model": c or None,
                              "epa_ppg": {"off": an.rnd(epa_off, 2), "def": an.rnd(epa_def, 2), "st": an.rnd(u.get("st_epa_g"), 2)}},
                    "history": ((tr or {}).get("history") or {}).get(t) or hist.get(t) or [],
                    "history_cols": ["week", "net", "off", "def"],
                    "history_source": "team_strength" if ((tr or {}).get("history") or {}).get(t) else "epa",
                    "personnel": (pers.get(t) or {}).get("personnel"), "formation": (pers.get(t) or {}).get("formation"),
                    "qbs": qbs.get(t) or [], "roster_value": an.rnd(roster_value.get(t), 1),
                    "sim": ((sim or {}).get("teams") or {}).get(t) if (sim or {}).get("ok") else None,
                    "schedule": [{k_: k.get(k_) for k_ in ("game_id", "week", "gtype", "kickoff", "home", "away", "hs", "as", "status")}
                                 | {"model": k.get("model"), "line": (k.get("line") or {}).get("spread_home") if k.get("line") else None}
                                 for k in sched]}
    for m in METRICS:
        col = {t: r["values"].get(m["key"]) for t, r in teams.items()}
        if m.get("scope") == "style":
            rk = an.ranks(col, lower=False)
        else:
            rk = an.ranks(col, lower=m["lower"])
        for t, v in rk.items():
            teams[t]["rank"][m["key"]] = v
        pc = an.percentiles(col, lower=m["lower"]) if m.get("scope") != "style" else {}
        for t, v in pc.items():
            teams[t].setdefault("pct", {})[m["key"]] = v
    for t in teams:
        teams[t]["values"] = an.round_values(teams[t]["values"], METRICS)
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "phase": ctx.phase, "week": ctx.week,
            "metrics": [an.public_metric(m) for m in METRICS], "teams": teams,
            "ratings_source": (tr or {}).get("source") or "epa", "ratings_units": (tr or {}).get("units") or "points per game",
            "plays_per_team_game": an.rnd(ppg, 1), "model_errors": dict(ctx.model_errors)}


def records(ctx: SeasonContext) -> dict[str, dict]:
    """W-L-T, PF, PA, point differential, home / away / division / conference records from the store's final
    regular-season games."""
    out: dict[str, dict] = {t: {"w": 0, "l": 0, "t": 0, "pf": 0, "pa": 0, "home": [0, 0, 0], "away": [0, 0, 0], "div": [0, 0, 0],
                                "conf": [0, 0, 0], "streak": "", "last5": []} for t in ctx.teams}
    seq: dict[str, list] = {t: [] for t in ctx.teams}
    for g in sorted(ctx.games.values(), key=lambda x: (str(x.get("kickoff") or x.get("date") or ""), x.get("game_id"))):
        if g.get("gtype") != "REG" or g.get("status") != "final" or g.get("hs") is None:
            continue
        h, a, hs, as_ = g["home"], g["away"], int(g["hs"]), int(g["as"])
        for t, pf, pa, side in ((h, hs, as_, "home"), (a, as_, hs, "away")):
            if t not in out:
                continue
            o = out[t]
            res = 0 if pf > pa else (1 if pf < pa else 2)
            o[("w", "l", "t")[res]] += 1
            o["pf"] += pf
            o["pa"] += pa
            o[side][res] += 1
            opp = a if t == h else h
            ti, oi = ctx.teams.get(t) or {}, ctx.teams.get(opp) or {}
            if ti.get("division") and ti.get("division") == oi.get("division"):
                o["div"][res] += 1
            if ti.get("conference") and ti.get("conference") == oi.get("conference"):
                o["conf"][res] += 1
            seq[t].append("WLT"[res])
    for t, o in out.items():
        s = seq[t]
        if s:
            k = 1
            while k < len(s) and s[-k - 1] == s[-1]:
                k += 1
            o["streak"] = f"{s[-1]}{k}"
            o["last5"] = s[-5:]
        gp = o["w"] + o["l"] + o["t"]
        o["pct"] = round((o["w"] + 0.5 * o["t"]) / gp, 3) if gp else None
        o["diff"] = o["pf"] - o["pa"]
    return out
