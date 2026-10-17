"""
awards.json (per level and season): builder D's award races (MVP, Cy Young, Rookie of the Year per league; a
conditional logit on Bullpen WAR, traditional voting features and team success, fitted on verified winners)
against Kalshi / Polymarket.

Shape (PAYLOADS: per award {model: {pid: p}, market, features}):
{"ok","level","season", "awards": {"al_mvp": {"label","league","award","model": {pid: p},"rows": [{pid,name,team,p,value}],
 "market": TITLE|null, "vs_market": [...], "features": [...], "fit": {...}}, ...}, "source", "verified_winners"}
"""
from __future__ import annotations

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics.context import SeasonContext

LABEL = {"mvp": "Most Valuable Player", "cy": "Cy Young Award", "roy": "Rookie of the Year"}


def build(ctx: SeasonContext, hitters: dict | None = None, pitchers: dict | None = None) -> dict:
    if ctx.level != "mlb":
        return {"ok": False, "reason": "awards are MLB only", "level": ctx.level, "season": ctx.season}
    r = ctx.model("awards")
    if not r.get("ok"):
        return {"ok": False, "reason": f"award model: {r.get('reason')}", "level": ctx.level, "season": ctx.season}
    try:
        from oddsmarkets.baseball.models import awards as AW
        feats = AW.FEATURES
    except Exception:                                            # noqa: BLE001
        feats = {}
    feat_vals = _features(ctx, feats)
    team_of = {}
    for cat in (hitters, pitchers):
        for pid, row in ((cat or {}).get("players") or {}).items():
            team_of.setdefault(pid, row.get("team"))
    out = {}
    for key, rec in r.items():
        if not isinstance(rec, dict) or "_" not in str(key) or key.split("_", 1)[1] not in LABEL:
            continue
        lg, aw = key.split("_", 1)
        fv = feat_vals.get(key) or {}
        rows = [{**x, "team": team_of.get(str(x.get("pid"))), "features": fv.get(str(x.get("pid")))} for x in (rec.get("model") or [])]
        out[key] = {"label": f"{lg.upper()} {LABEL[aw]}", "league": lg.upper(), "award": aw,
                    "model": {str(x["pid"]): x["p"] for x in rows if x.get("pid") is not None},
                    "rows": rows, "market": rec.get("market"), "vs_market": rec.get("vs_market"), "features": feats.get(aw),
                    "fit": rec.get("fit"), "reason": rec.get("reason")}
    return {"ok": True, "level": ctx.level, "season": ctx.season, "updated_at": an.now(), "awards": out,
            "source": r.get("source"), "verified_winners": r.get("verified_winners"), "value_source": r.get("value_source")}


def _features(ctx: SeasonContext, feats: dict) -> dict[str, dict]:
    """{award key: {pid: {feature: raw value}}} from builder D's candidate tables (the values the model scores, before
    z-scoring: value = Bullpen WAR or the proxy, hr, team win%, wOBA; k, ip, ra9; pa_ip = PA/600 or IP/180)."""
    try:
        from oddsmarkets.baseball.models import awards as AW
        tab = AW.season_table(ctx.level, ctx.season)
        prior = AW._prior_ids(ctx.level, ctx.season)
    except Exception:                                            # noqa: BLE001
        return {}
    out: dict[str, dict] = {}
    for aw, fl in feats.items():
        for lg in ("AL", "NL"):
            try:
                c = AW.candidates(tab, aw, lg, prior if aw == "roy" else None)
            except Exception:                                    # noqa: BLE001
                continue
            if c is None or not len(c):
                continue
            out[f"{lg.lower()}_{aw}"] = {str(r["pid"]): {f: an.rnd(r.get(f), 4) for f in fl} for r in c.to_dict("records")}
    return out
