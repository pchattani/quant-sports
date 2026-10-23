"""
Fielders and catchers catalogue (fielders.json): builder C's catch-probability fielding (OAA, fielding runs, by
direction) set against Savant's published OAA, Savant arm strength, and for catchers builder C's framing runs
against Savant's framing runs, plus stolen-base attempts against (estimated from the pitch data by builder C's
WAR model where available). Percentiles against fielders with 50+ chances, by position.
"""
from __future__ import annotations

from typing import Any

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import catalog as CT
from oddsmarkets.baseball.analytics.context import SeasonContext

M = an.metric
OAA_K = an.OAA_K
FLOORS = {"chances": 20, "called": 500}

METRICS = [
    M("chances", "Chances", "Fielding", "1", desc="Balls credited to the fielder: outs made plus shares of balls not turned into outs."),
    M("oaa", "OAA", "Fielding", "1", den="chances", k=OAA_K, scope="model", desc="Outs above average (our catch-probability model)."),
    M("fielding_runs", "Fielding runs", "Fielding", "1", den="chances", k=OAA_K, scope="model", desc="OAA in runs."),
    M("sra", "Success rate added", "Fielding", "pct", den="chances", k=OAA_K, scope="model", desc="OAA per chance."),
    M("oaa_back", "OAA back", "Fielding", "1", scope="model", desc="OAA on balls moving away from the plate."),
    M("oaa_in", "OAA in", "Fielding", "1", scope="model", desc="OAA on balls moving in."),
    M("oaa_3b", "OAA toward 3B", "Fielding", "1", scope="model", desc="OAA moving toward the third-base line."),
    M("oaa_1b", "OAA toward 1B", "Fielding", "1", scope="model", desc="OAA moving toward the first-base line."),
    M("oaa_savant", "Savant OAA", "Fielding", "int", scope="statcast", desc="Savant's OAA."),
    M("frp_savant", "Savant fielding runs", "Fielding", "int", scope="statcast", desc="Savant's fielding runs prevented."),
    M("oaa_gap", "OAA minus Savant", "Fielding", "1", scope="model", desc="Our OAA minus Savant's."),
    M("arm", "Arm strength", "Throwing", "mph", scope="statcast", desc="Savant arm strength (overall)."),
    M("arm_max", "Max arm", "Throwing", "mph", scope="statcast", desc="Savant's hardest tracked throw."),
    M("framing_runs", "Framing runs", "Catching", "1", den="called", stab="c_frame", scope="model",
      desc="Our framing runs (called-strike model with catcher, umpire, pitcher and batter effects)."),
    M("framing_rate", "Strike rate added", "Catching", "pct", den="called", stab="c_frame", scope="model", desc="Strikes added per called pitch."),
    M("framing_per_season", "Framing runs /7,000 called", "Catching", "1", scope="model", desc="Framing runs per 7,000 called pitches."),
    M("framing_savant", "Savant framing runs", "Catching", "1", scope="statcast", desc="Savant's catcher-framing runs."),
    M("called", "Called pitches", "Catching", "int", desc="Called pitches received."),
]


def build(ctx: SeasonContext, hitters: dict | None = None) -> dict:
    cp = ctx.model("catchprob")
    fr = ctx.model("framing")
    fld = CT.lookup(cp.get("fielders"))
    frm = CT.lookup(fr.get("catchers"))
    if not fld and not frm:
        return {"ok": False, "reason": "catch-probability and framing models not available", "level": ctx.level, "season": ctx.season,
                "errors": {k: ctx.model_errors.get(k) for k in ("catchprob", "framing")}}
    oaa_sv = CT.leaderboard("outs_above_average", ctx.season)
    arm = CT.leaderboard("arm-strength", ctx.season)
    fsv = CT.leaderboard("catcher-framing", ctx.season, ("id", "player_id"))
    hp = (hitters or {}).get("players") or {}
    rows: dict[str, dict] = {}
    role_of: dict[str, str] = {}
    for pid in set(fld) | set(frm):
        f, c = fld.get(pid) or {}, frm.get(pid) or {}
        v: dict[str, Any] = {}
        if f:
            v.update(chances=CT.g(f, "chances"), oaa=CT.g(f, "oaa"), fielding_runs=CT.g(f, "runs"), sra=CT.g(f, "sra"),
                     oaa_back=CT.g(f, "oaa_back"), oaa_in=CT.g(f, "oaa_in"), oaa_3b=CT.g(f, "oaa_toward_3b"),
                     oaa_1b=CT.g(f, "oaa_toward_1b"))
        s = oaa_sv.get(pid) or {}
        v["oaa_savant"] = CT.g(s, "outs_above_average")
        v["frp_savant"] = CT.g(s, "fielding_runs_prevented")
        if v.get("oaa") is not None and v["oaa_savant"] is not None:
            v["oaa_gap"] = v["oaa"] - v["oaa_savant"]
        a = arm.get(pid) or {}
        v["arm"] = CT.g(a, "arm_overall")
        v["arm_max"] = CT.g(a, "max_arm_strength")
        if c:
            v.update(framing_runs=CT.g(c, "runs"), framing_rate=CT.g(c, "strike_rate_added"),
                     framing_per_season=CT.g(c, "runs_per_season"), called=CT.g(c, "called"))
        v["framing_savant"] = CT.g(fsv.get(pid), "rv_tot")
        pos = None
        if f and f.get("pos") is not None:
            pos = CT.POS_NAME.get(int(f["pos"])) if str(f["pos"]).isdigit() else str(f["pos"])
        if c and (not pos or (c.get("called") or 0) > 1500):
            pos = "C"
        h = hp.get(pid) or {}
        rows[pid] = {"name": ctx.name(pid), "team": h.get("team"), "pos": pos or h.get("pos"), "values": v,
                     "n": {"chances": v.get("chances"), "called": v.get("called")}}
        role_of[pid] = pos or "-"
    reference = [p for p, r in rows.items() if (r["values"].get("chances") or 0) >= 50 or (r["values"].get("called") or 0) >= 2000]
    CT.finish(ctx, rows, METRICS, reference, role_of, FLOORS)
    return {**CT.season_meta(ctx), "kind": "fielder", "metrics": [an.public_metric(m) for m in METRICS], "players": rows,
            "validation": validation(ctx, fld, frm), "validation_model": {"oaa": cp.get("validation"), "framing": fr.get("validation")}}


def _pearson(a: list, b: list) -> float | None:
    import numpy as np
    x, y = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 5 or np.std(x[ok]) == 0 or np.std(y[ok]) == 0:
        return None
    return round(float(np.corrcoef(x[ok], y[ok])[0, 1]), 4)


def validation(ctx: SeasonContext, fld: dict | None = None, frm: dict | None = None) -> dict:
    """Our fielding (OAA, fielding runs) and framing runs against Savant's leaderboards for the same season (builder A's
    cached CSVs): Pearson r and n, fielders with 50+ chances, catchers with 1,000+ called pitches."""
    fld = fld if fld is not None else CT.lookup(ctx.model("catchprob").get("fielders"))
    frm = frm if frm is not None else CT.lookup(ctx.model("framing").get("catchers"))
    out = {"season": ctx.season}
    sv = CT.leaderboard("outs_above_average", ctx.season)
    if sv and fld:
        ids = [p for p, r in fld.items() if (an.fnum(r.get("chances")) or 0) >= 50 and p in sv]
        out["oaa"] = {"ok": len(ids) >= 5, "n": len(ids), "min_chances": 50,
                      "r_oaa": _pearson([fld[p].get("oaa") for p in ids], [sv[p].get("outs_above_average") for p in ids]),
                      "r_runs": _pearson([fld[p].get("runs") for p in ids], [sv[p].get("fielding_runs_prevented") for p in ids])}
    else:
        out["oaa"] = {"ok": False, "reason": "no Savant OAA leaderboard cached for this season" if not sv else "no fielding model"}
    fs = CT.leaderboard("catcher-framing", ctx.season, ("id", "player_id"))
    if fs and frm:
        ids = [p for p, r in frm.items() if (an.fnum(r.get("called")) or 0) >= 1000 and p in fs]
        out["framing"] = {"ok": len(ids) >= 5, "n": len(ids), "min_called": 1000,
                          "r_runs": _pearson([frm[p].get("runs") for p in ids], [fs[p].get("rv_tot") for p in ids]),
                          "r_rate": _pearson([frm[p].get("strike_rate_added") for p in ids], [fs[p].get("pct_tot") for p in ids])}
    else:
        out["framing"] = {"ok": False, "reason": "no Savant framing leaderboard cached for this season" if not fs else "no framing model"}
    return out
