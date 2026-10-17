"""
parks.json (per level and season): builder C's multi-year park factors (from xwOBA+ residuals on contact by
outcome and batter hand; runs, K and BB from home/road games), the venue's dimensions, roof, elevation and
orientation from the store, the season's run environment at each park (runs per game, home runs per game), and
the league-wide dimension and weather effects (carry and home-run probability per 10 F and per mph of wind out).
"""
from __future__ import annotations

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import catalog as CT
from oddsmarkets.baseball.analytics.context import SeasonContext


def build(ctx: SeasonContext) -> dict:
    pk = ctx.model("parks")
    venues = ctx.store.get("venues") or {}
    teams = ctx.teams
    env = _environment(ctx)
    parks: dict[str, dict] = {}
    for abbr, p in ((pk or {}).get("parks") or {}).items():
        vid = str(p.get("venue") or (teams.get(str(p.get("team"))) or {}).get("venue") or abbr)
        v = venues.get(vid) or {}
        parks[vid] = {"id": vid, "abbr": abbr, "team": str(p.get("team")) if p.get("team") else ctx.tid(abbr),
                      "name": p.get("name") or v.get("name"), "city": v.get("city"), "state": v.get("state"),
                      "dims": p.get("dims") or v.get("dims"), "walls": p.get("walls") or v.get("walls"), "elev_ft": p.get("elev_ft") or v.get("elev_ft"),
                      "roof": p.get("roof") or v.get("roof"), "turf": v.get("turf"), "azimuth": v.get("azimuth"), "capacity": v.get("capacity"),
                      "lat": v.get("lat"), "lon": v.get("lon"),
                      "factors": an.clean({k: an.rnd(x, 3) for k, x in (p.get("factors") or {}).items()}),
                      "index": p.get("index"), "by_hand": {h: {k: an.rnd(x, 3) for k, x in (d or {}).items()} for h, d in (p.get("by_hand") or {}).items()},
                      "n_bip": p.get("n_bip"), "season": env.get(vid)}
    # venues without factors (new or neutral sites) still get their dimensions
    for t in an.real_teams(ctx.store):
        vid = str((teams.get(t) or {}).get("venue") or "")
        if vid and vid not in parks and vid in venues:
            v = venues[vid]
            parks[vid] = {"id": vid, "abbr": (teams.get(t) or {}).get("abbr"), "team": t, "name": v.get("name"), "city": v.get("city"),
                          "dims": v.get("dims"), "walls": v.get("walls"), "elev_ft": v.get("elev_ft"), "roof": v.get("roof"),
                          "turf": v.get("turf"), "azimuth": v.get("azimuth"), "factors": None, "season": env.get(vid)}
    if not parks:
        return {"ok": False, "reason": f"park factors: {(pk or {}).get('reason') or 'not available'}", "level": ctx.level, "season": ctx.season}
    return {**CT.season_meta(ctx), "parks": parks, "years": (pk or {}).get("years"), "dimension_effects": (pk or {}).get("dimensions"),
            "weather_effects": (pk or {}).get("weather"), "model_ok": bool((pk or {}).get("ok"))}


def _environment(ctx: SeasonContext) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for g in ctx.games.values():
        if (g or {}).get("gtype") != "R" or g.get("status") != "final" or g.get("hs") is None:
            continue
        vid = str(g.get("venue") or "")
        r = out.setdefault(vid, {"games": 0, "runs": 0})
        r["games"] += 1
        r["runs"] += int(g["hs"]) + int(g["as"])
    for r in out.values():
        r["runs_per_game"] = round(r["runs"] / r["games"], 2) if r["games"] else None
    return out
