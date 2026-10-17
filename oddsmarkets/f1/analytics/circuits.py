"""
Circuit pages (`circuits.json` per season and site-wide `data/circuits.json`).

For every circuitId in the season stores on disk:
* "profile": every field of `models.circuits.circuit_profile(circuitId)` over every race on disk (1996-;
  earlier circuits get the global priors and samples.races = 0), including "global" (the field-wide values): laps, length, pit loss, SC/VSC hazard,
  overtaking difficulty and threshold, typical stops, wet probability, retirement rates.
* "history": one row per Grand Prix held there, newest first: year, round, race name, winner,
  winning team, pole (qualifying P1; before qualifying classifications, the grid's P1).
* "records": most wins, most poles (top 5 each), most team wins (top 5), the lap record (the
  fastest race lap in the stores' fastest-lap data, 2004-; layouts change over the years, so
  this is the fastest lap on any layout that carried the circuitId), the share of races won
  from pole, races held, first and last year.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from oddsmarkets.f1 import canon
from oddsmarkets.f1.analytics import inum, seasons_on_disk

logger = logging.getLogger(__name__)



def profile(circuit_id: str) -> dict:
    try:
        from oddsmarkets.f1.models.circuits import circuit_profile
        p = circuit_profile(circuit_id)
        return dict(p)                                       # every circuit_profile field, "global" included
    except Exception as exc:                                     # pragma: no cover - defensive
        logger.warning("circuit profile %s failed: %s", circuit_id, exc)
        return {}


def _pole(race: dict) -> str | None:
    q = next((r.get("driver") for r in race.get("qualifying") or [] if inum(r.get("position")) == 1), None)
    if q:
        return q
    return next((r.get("driver") for r in race.get("results") or [] if inum(r.get("grid")) == 1), None)


def build_all(years: list[int] | None = None, with_profile: bool = True) -> dict[str, dict]:
    """{circuitId: {"name","country","locality","lat","long","profile","history","records"}} over the stores on disk."""
    years = sorted(years if years is not None else seasons_on_disk())
    out: dict[str, dict[str, Any]] = {}
    wins: dict[str, Counter] = {}
    poles: dict[str, Counter] = {}
    twins: dict[str, Counter] = {}
    lap: dict[str, dict] = {}
    from_pole: dict[str, list[int]] = {}
    for y in years:
        st = canon.season(y)
        for k, race in (st.get("races") or {}).items():
            c = race.get("circuit") or {}
            cid = c.get("id")
            if not cid:
                continue
            e = out.setdefault(cid, {"name": c.get("name"), "country": c.get("country"), "locality": c.get("locality"),
                                     "lat": c.get("lat"), "long": c.get("long"), "history": []})
            e.update({kk: c.get(kk) or e.get(kk) for kk in ("name", "country", "locality", "lat", "long")})
            res = race.get("results") or []
            if not res:
                continue
            win = next((r for r in res if inum(r.get("position")) == 1 and str(r.get("position_text") or "1").isdigit()), None)
            pole = _pole(race)
            e["history"].append({"year": y, "round": inum(k), "name": race.get("name"), "winner": (win or {}).get("driver"),
                                 "team": (win or {}).get("constructor"), "pole": pole, "date": race.get("date")})
            if win:
                wins.setdefault(cid, Counter())[win["driver"]] += 1
                twins.setdefault(cid, Counter())[win.get("constructor")] += 1
                from_pole.setdefault(cid, []).append(1 if pole and pole == win["driver"] else 0)
            if pole:
                poles.setdefault(cid, Counter())[pole] += 1
            for r in res:
                ms = inum(r.get("fastest_ms"))
                if ms and ms > 30000 and (cid not in lap or ms < lap[cid]["ms"]):
                    lap[cid] = {"driver": r.get("driver"), "team": r.get("constructor"), "ms": ms, "year": y, "round": inum(k)}
    for cid, e in out.items():
        e["history"].sort(key=lambda h: (h["year"], h["round"] or 0), reverse=True)
        yrs = [h["year"] for h in e["history"]]
        fp = from_pole.get(cid) or []
        e["records"] = {
            "most_wins": [{"driver": d, "wins": n} for d, n in (wins.get(cid) or Counter()).most_common(5)],
            "most_poles": [{"driver": d, "poles": n} for d, n in (poles.get(cid) or Counter()).most_common(5)],
            "most_team_wins": [{"team": t, "wins": n} for t, n in (twins.get(cid) or Counter()).most_common(5)],
            "lap_record": lap.get(cid), "won_from_pole": round(sum(fp) / len(fp), 4) if fp else None,
            "races": len(e["history"]), "first_year": min(yrs) if yrs else None, "last_year": max(yrs) if yrs else None,
        }
        e["profile"] = profile(cid) if with_profile else {}
    return out


def build_season(year: int, all_circuits: dict[str, dict]) -> dict[str, dict]:
    """The season's circuits (from build_all), in calendar order."""
    st = canon.season(year)
    out = {}
    for k in sorted((st.get("races") or {}), key=lambda x: inum(x) or 0):
        cid = ((st["races"][k].get("circuit") or {}).get("id"))
        if cid and cid in all_circuits and cid not in out:
            out[cid] = all_circuits[cid]
    return out
