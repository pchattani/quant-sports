#!/usr/bin/env python
"""
Fill the F1 season stores from Jolpica, resumably.

Phases, each over every season newest first, skipping what is already stored:
  schedule   the calendar (1 call a season)
  results    race results, qualifying and sprint results (a few paged calls a season)
  pitstops   pit stops per race (2011 onward, 1 call a race)
  laps       lap times and lap-by-lap positions per race (1996 onward, ~10-15 calls a race)

Calls are paced to stay under Jolpica's 500 an hour (7.3 s apart), so the full
history (about 7,000 calls) takes roughly 14 hours; run it detached and it can
be stopped and restarted at any point. `--refresh-current` re-fetches the
current season's finished rounds (for the hourly job).

    python scripts/f1_fetch.py --from 1950 --to 2026 --budget 10000
    python scripts/f1_fetch.py --phases results,laps --from 2023 --budget 400
    python scripts/f1_fetch.py --refresh-current --budget 120
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.f1 import store as st  # noqa: E402
from oddsmarkets.f1.sources import jolpica as jp  # noqa: E402

logger = logging.getLogger("f1_fetch")
PHASES = ("schedule", "results", "pitstops", "laps")
PITSTOPS_FROM, LAPS_FROM = 2011, 1996


def _finished(race: dict) -> bool:
    d = race.get("date")
    if not d:
        return False
    when = datetime.fromisoformat(d + "T" + (race.get("time") or "23:59:59Z").replace("Z", "+00:00")) if "T" not in d else datetime.fromisoformat(d)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() > 4 * 3600


def schedule(p: jp.Pacer, s: dict) -> None:
    if st.has(s, "_", "schedule") and s["season"] < datetime.now(timezone.utc).year:
        return
    d = p.get(f"{s['season']}.json", {"limit": 100})
    for r in (d or {}).get("RaceTable", {}).get("Races") or []:
        rnd = str(r["round"])
        race = s["races"].setdefault(rnd, {})
        race.update(jp.race_rec(r))
    if d:
        st.mark(s, "_", "schedule")


def _merge_paged(p: jp.Pacer, s: dict, path: str, key: str, parse, field: str) -> int:
    rows: dict[str, list] = {}
    for race in jp.paged(p, path, "RaceTable", "Races"):
        rnd = str(race["round"])
        for x in race.get(key) or []:
            rows.setdefault(rnd, []).append(parse(x))
            d, c = x.get("Driver") or {}, x.get("Constructor") or {}
            if d.get("driverId"):
                s["drivers"].setdefault(d["driverId"], jp.driver_rec(d))
            if c.get("constructorId"):
                s["constructors"].setdefault(c["constructorId"], jp.constructor_rec(c))
        if rnd not in s["races"]:
            s["races"][rnd] = jp.race_rec(race)
    for rnd, lst in rows.items():
        s["races"].setdefault(rnd, {})[field] = lst
        st.mark(s, rnd, field)
    return len(rows)


def results(p: jp.Pacer, s: dict, refresh: bool) -> None:
    y = s["season"]
    done = [r for r, race in s["races"].items() if st.has(s, r, "results")]
    finished = [r for r, race in s["races"].items() if _finished(race)]
    if not refresh and finished and all(r in done for r in finished):
        return
    _merge_paged(p, s, f"{y}/results.json", "Results", jp.result_rec, "results")
    _merge_paged(p, s, f"{y}/qualifying.json", "QualifyingResults", jp.quali_rec, "qualifying")
    if y >= 2021:
        _merge_paged(p, s, f"{y}/sprint.json", "SprintResults", jp.result_rec, "sprint")


def pitstops(p: jp.Pacer, s: dict, refresh: bool) -> None:
    y = s["season"]
    if y < PITSTOPS_FROM:
        return
    for rnd in sorted(s["races"], key=int):
        race = s["races"][rnd]
        if not race.get("results") or (st.has(s, rnd, "pitstops") and not refresh):
            continue
        stops = []
        for r in jp.paged(p, f"{y}/{rnd}/pitstops.json", "RaceTable", "Races"):
            for x in r.get("PitStops") or []:
                stops.append({"driver": x.get("driverId"), "stop": jp._int(x.get("stop")), "lap": jp._int(x.get("lap")),
                              "duration_ms": jp.to_ms(x.get("duration"))})
        race["pitstops"] = stops
        st.mark(s, rnd, "pitstops")
        st.save(s)


def laps(p: jp.Pacer, s: dict, refresh: bool) -> None:
    y = s["season"]
    if y < LAPS_FROM:
        return
    for rnd in sorted(s["races"], key=int):
        race = s["races"][rnd]
        if not race.get("results") or (st.has(s, rnd, "laps") and not refresh):
            continue
        times: dict[str, dict[int, int | None]] = {}
        pos: dict[str, dict[int, int | None]] = {}
        for r in jp.paged(p, f"{y}/{rnd}/laps.json", "RaceTable", "Races"):
            for lap in r.get("Laps") or []:
                n = jp._int(lap.get("number")) or 0
                for t in lap.get("Timings") or []:
                    d = t.get("driverId")
                    times.setdefault(d, {})[n] = jp.to_ms(t.get("time"))
                    pos.setdefault(d, {})[n] = jp._int(t.get("position"))
        if not times:
            st.mark(s, rnd, "laps")             # no lap data for this race: do not ask again
            continue
        race["laps"] = {d: [v.get(i) for i in range(1, max(v) + 1)] for d, v in times.items()}
        race["positions"] = {d: [v.get(i) for i in range(1, max(v) + 1)] for d, v in pos.items()}
        st.mark(s, rnd, "laps")
        st.save(s)
        logger.info("%d round %s: laps for %d drivers (%d calls used)", y, rnd, len(times), p.used)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", type=int, default=1950)
    ap.add_argument("--to", dest="end", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--phases", default=",".join(PHASES))
    ap.add_argument("--budget", type=int, default=450)
    ap.add_argument("--interval", type=float, default=7.3, help="seconds between calls (500/hour cap)")
    ap.add_argument("--refresh-current", action="store_true", help="re-fetch the current season's finished rounds")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = jp.Pacer(budget=args.budget, interval=args.interval)
    phases = [x for x in args.phases.split(",") if x in PHASES]
    current = datetime.now(timezone.utc).year
    years = list(range(args.end, args.start - 1, -1))
    if args.refresh_current:
        years, phases = [current], ["schedule", "results", "pitstops", "laps"]
    try:
        for phase in phases:
            for y in years:
                s = st.load(y)
                refresh = args.refresh_current and y == current
                if phase == "schedule":
                    schedule(p, s)
                elif phase == "results":
                    results(p, s, refresh)
                elif phase == "pitstops":
                    pitstops(p, s, refresh)
                elif phase == "laps":
                    laps(p, s, refresh)
                st.save(s)
                logger.info("%s %d done (%d calls used)", phase, y, p.used)
    except jp.BudgetExhausted as exc:
        logger.info("%s", exc)
    logger.info("calls used: %d", p.used)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
