"""
Per-race data context shared by the driver and team catalogues, the race centre and the
awards: one `RaceCtx(year, round)` loads the season-store race, the OpenF1 session records
(2023-) and the model outputs once, and derives the lap-by-lap tables everything else uses.

Lap table (`laps()`)
--------------------
* 2023- (OpenF1 race session on disk): lap L of driver i ends at end_i(L) = t_start_i(L+1)
  when the next lap's start is known, else t_start_i(L) + lap_ms_i(L). The running order
  at the end of lap L is the order in which the cars completed lap L (rank of end_i(L));
  a lapped car completes lap L later than the leader, so it ranks behind him.
  gap_i(L) = (end_i(L) - end_leader(L)) / 1000 s.
* Earlier seasons: the season store's `positions` (Jolpica lap positions) and `laps` (ms);
  gap_i(L) = cum_i(L) - min_j cum_j(L) with cum the running sum of lap times (None after a
  missing lap).
* The grid slot is `grid`; a pit-lane start (grid 0) counts as the last slot (number of starters).

Passes (`overtakes()`)
----------------------
OpenF1 `overtakes` rows, mapped to driverIds and to the overtaking car's lap (the lap whose
[start, end) contains the timestamp). A pass on a car that is on its in-lap or out-lap, or
by a car on its out-lap, is a pit-stop position change and is dropped; so are order changes
on laps under a safety car / VSC (`neutral_windows`) and passes on a car that retired within
two laps (a car stopping on track).
`derived_passes()` (any season with lap positions) finds the same thing from the lap table:
a pair (a, b) with a behind b at the end of lap L-1 and ahead at the end of lap L, neither
car pitting on L-1, L or L+1, lap L >= 2, and the lap not neutralised.

Corrected lap scatter (`lap_scatter()`)
---------------------------------------
For each driver's clean laps (laptime.assemble's exclusions: lap 1, in/out laps,
neutralised and restart laps, outliers outside 93-110% of the median clean lap):
    r_{i,L} = lap_s - fuel_coef * fuel_L - deg_{i,c} * age_L
using the race fit's fuel coefficient and the driver's own degradation slope per compound;
the scatter is sd_i = sd(r_{i,L}) over the driver's clean laps (at least 8 laps).

Wet race (`wet()`)
------------------
OpenF1 era only: wet when at least 10% of the in-race weather samples report rainfall, or
at least a quarter of the drivers ran an INTERMEDIATE or WET stint. None before 2023.
"""
from __future__ import annotations

import json
import re
from bisect import bisect_right
from typing import Any

from oddsmarkets.f1 import canon
from oddsmarkets.f1.analytics import data_root, fnum, inum, sd, started, status_kind

SESSION_NAMES = {
    "race": ("race",), "quali": ("qualifying",), "sprint": ("sprint",),
    "sprint_quali": ("sprint qualifying", "sprint shootout"),
    "fp1": ("practice 1",), "fp2": ("practice 2",), "fp3": ("practice 3",),
}
_PEN_RE = re.compile(r"CAR (\d+)")
_RED_RE = re.compile(r"\bRED FLAG")      # word boundary: "CHEQUERED FLAG" contains "RED FLAG"
_PEN_SKIP = ("SERVED", "NO FURTHER", "INVESTIGAT", "NOTED", "REVIEWED", "NO ACTION", "WARNING", "UNDER INVESTIGATION")
_CTX: dict[tuple[int, int], "RaceCtx"] = {}


def reset() -> None:
    _CTX.clear()


def get(year: int, rnd: int) -> "RaceCtx":
    key = (int(year), int(rnd))
    c = _CTX.get(key)
    if c is None:
        if len(_CTX) > 160:
            _CTX.clear()
        c = _CTX[key] = RaceCtx(*key)
    return c


class RaceCtx:
    """Everything known about one round; every accessor is cached and never raises."""

    def __init__(self, year: int, rnd: int):
        self.year, self.round = int(year), int(rnd)
        self.store = canon.season(self.year)
        self.race = canon.race(self.year, self.round)
        self.results = [r for r in self.race.get("results") or [] if r.get("driver")]
        self.qualifying = [r for r in self.race.get("qualifying") or [] if r.get("driver")]
        self.sprint = [r for r in self.race.get("sprint") or [] if r.get("driver")]
        self._c: dict[str, Any] = {}

    # ------------------------------------------------------------------ basics
    @property
    def done(self) -> bool:
        return bool(self.results)

    def _memo(self, key: str, fn):
        if key not in self._c:
            try:
                self._c[key] = fn()
            except Exception:                                    # never let one race break a build
                self._c[key] = None
        return self._c[key]

    def team_of(self, d: str) -> str | None:
        for rows in (self.results, self.qualifying, self.sprint):
            for r in rows:
                if r.get("driver") == d and r.get("constructor"):
                    return r["constructor"]
        return canon.team_for(self.year, self.round, d)

    def lineup(self) -> dict[str, str]:
        return self._memo("lineup", lambda: canon.lineup(self.year, self.round)) or {}

    def starters(self) -> list[dict]:
        return [r for r in self.results if started(r)]

    def grid_slots(self) -> dict[str, int]:
        """{driver: grid slot}; a pit-lane start (grid 0) is the last slot."""
        def f():
            rows = self.starters()
            n = len(rows)
            return {r["driver"]: (inum(r.get("grid")) if (inum(r.get("grid")) or 0) > 0 else n) for r in rows}
        return self._memo("grid", f) or {}

    def finish(self) -> dict[str, int]:
        """{driver: classified position} for classified finishers."""
        return {r["driver"]: inum(r.get("position")) for r in self.results if status_kind(r) == "finished" and inum(r.get("position"))}

    # ------------------------------------------------------------------ sessions
    def session_keys(self) -> dict[str, int | None]:
        def f():
            out = {k: None for k in SESSION_NAMES}
            for e in canon.session_index(self.year):
                if e.get("round") != self.round:
                    continue
                nm = str(e.get("name") or "").lower()
                for k, names in SESSION_NAMES.items():
                    if nm in names:
                        out[k] = e.get("key")
            return out
        return self._memo("skeys", f) or {k: None for k in SESSION_NAMES}

    def session(self, kind: str = "race") -> dict | None:
        def f():
            key = self.session_keys().get(kind)
            if key is None:
                return None
            for e in canon.session_index(self.year):
                if e.get("key") == key:
                    return canon.load_session(e["path"])
            return None
        return self._memo(f"sess:{kind}", f)

    def ids(self, kind: str = "race") -> dict[str, str]:
        def f():
            rec = self.session(kind)
            return canon.session_driver_ids(self.year, rec, self.round) if rec else {}
        return self._memo(f"ids:{kind}", f) or {}

    def telemetry(self, kind: str = "race") -> dict | None:
        def f():
            key = self.session_keys().get(kind)
            if key is None:
                return None
            p = data_root() / str(self.year) / "telemetry" / f"{key}.json"
            if not p.exists():
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        return self._memo(f"tele:{kind}", f)

    def has_telemetry(self, kind: str) -> bool:
        key = self.session_keys().get(kind)
        return bool(key is not None and (data_root() / str(self.year) / "telemetry" / f"{key}.json").exists())

    # ------------------------------------------------------------------ laps
    def laps(self) -> dict:
        """{"n", "positions": {d: [pos lap1..]}, "gaps": {d: [s]}, "times": {d: [ms]}, "source"} (see module docstring)."""
        return self._memo("laps", self._laps) or {"n": 0, "positions": {}, "gaps": {}, "times": {}, "source": None}

    def _laps(self) -> dict:
        return self._align_finish(self._laps_raw())

    def _align_finish(self, lt: dict) -> dict:
        """Make every classified driver's final recorded lap agree with the official result.

        Lap-end times rebuilt from OpenF1 lap starts carry ~1 s timestamp jitter, enough to swap a
        close finish. For each lap L, the classified drivers whose last recorded lap is L keep the
        position slots they occupy on L but are re-ordered by classification; on the leader's final
        lap the lead-lap finishers' gaps are replaced by the official gaps (time_ms - winner's).
        """
        pos, gaps = lt.get("positions") or {}, lt.get("gaps") or {}
        cls = {r["driver"]: inum(r.get("position")) for r in self.results if status_kind(r) == "finished" and inum(r.get("position"))}
        if not pos or not cls:
            return lt
        by_last: dict[int, list[str]] = {}
        for d in cls:
            p = pos.get(d) or []
            if p and p[-1] is not None:
                by_last.setdefault(len(p), []).append(d)
        for L, ds in by_last.items():
            slots = sorted(pos[d][L - 1] for d in ds)
            for d, s in zip(sorted(ds, key=lambda d: cls[d]), slots):
                pos[d][L - 1] = s
        win = next((r for r in self.results if inum(r.get("position")) == 1 and status_kind(r) == "finished"), None)
        if win and inum(win.get("time_ms")) and gaps:
            n_win = len(pos.get(win["driver"]) or [])
            for r in self.results:
                d, t = r["driver"], inum(r.get("time_ms"))
                g = gaps.get(d) or []
                if t is not None and d in cls and len(g) == n_win and n_win:
                    g[-1] = round((t - inum(win["time_ms"])) / 1000.0, 3)
        return lt

    def _laps_raw(self) -> dict:
        rec = self.session("race")
        n_res = max((inum(r.get("laps")) or 0 for r in self.results), default=0)
        if rec and rec.get("laps"):
            ids = self.ids("race")
            ends: dict[str, dict[int, float]] = {}
            times: dict[str, dict[int, int | None]] = {}
            for num, rows in (rec.get("laps") or {}).items():
                d = ids.get(str(num))
                if not d:
                    continue
                rows = [r for r in rows or [] if r and r[0] is not None]
                starts = {int(r[0]): fnum(r[1]) for r in rows}
                ms = {int(r[0]): (inum(r[2]) if r[2] is not None else None) for r in rows}
                e = {}
                for L, s in starts.items():
                    nxt = starts.get(L + 1)
                    if nxt is not None:
                        e[L] = nxt
                    elif s is not None and ms.get(L):
                        e[L] = s + ms[L]
                ends[d], times[d] = e, ms
            n = max([n_res] + [max(e) for e in ends.values() if e])
            pos: dict[str, list] = {d: [] for d in ends}
            gaps: dict[str, list] = {d: [] for d in ends}
            for L in range(1, n + 1):
                lap = sorted((e[L], d) for d, e in ends.items() if L in e)
                if not lap:
                    continue
                lead = lap[0][0]
                for k, (t, d) in enumerate(lap, 1):
                    pl, gl = pos[d], gaps[d]
                    while len(pl) < L - 1:
                        pl.append(None)
                        gl.append(None)
                    pl.append(k)
                    gl.append(round((t - lead) / 1000.0, 3))
            tl = {d: [ms.get(L) for L in range(1, max(ms) + 1)] if ms else [] for d, ms in times.items()}
            return {"n": n, "positions": pos, "gaps": gaps, "times": tl, "source": "openf1"}
        laps = self.race.get("laps") or {}
        posd = self.race.get("positions") or {}
        if not laps and not posd:
            return {"n": n_res, "positions": {}, "gaps": {}, "times": {}, "source": None}
        n = max([n_res] + [len(v or []) for v in laps.values()] + [len(v or []) for v in posd.values()])
        cum: dict[str, list] = {}
        for d, lst in laps.items():
            c, acc = [], 0.0
            for ms in lst or []:
                if ms is None or acc is None:
                    acc = None
                else:
                    acc += float(ms)
                c.append(acc)
            cum[d] = c
        gaps = {d: [] for d in cum}
        for L in range(n):
            vals = [c[L] for c in cum.values() if L < len(c) and c[L] is not None]
            lead = min(vals) if vals else None
            for d, c in cum.items():
                if L < len(c):
                    gaps[d].append(round((c[L] - lead) / 1000.0, 3) if (c[L] is not None and lead is not None) else None)
        times = {d: [inum(x) if x is not None else None for x in lst or []] for d, lst in laps.items()}
        positions = {d: [inum(x) for x in lst or []] for d, lst in posd.items()}
        if not positions and cum:
            # Positions from cumulative time when the store has times but no positions.
            positions = {d: [] for d in cum}
            for L in range(n):
                lap = sorted((c[L], d) for d, c in cum.items() if L < len(c) and c[L] is not None)
                for k, (_t, d) in enumerate(lap, 1):
                    while len(positions[d]) < L:
                        positions[d].append(None)
                    positions[d].append(k)
        return {"n": n, "positions": positions, "gaps": gaps, "times": times, "source": "jolpica"}

    def pos_at(self, d: str, lap: int) -> int | None:
        """Running position at the end of `lap` (lap 0 = grid slot)."""
        if lap <= 0:
            return self.grid_slots().get(d)
        p = self.laps()["positions"].get(d) or []
        return p[lap - 1] if 0 < lap <= len(p) else None

    # ------------------------------------------------------------------ pit stops and stints
    def in_laps(self) -> dict[str, set[int]]:
        """{driver: laps on which he entered the pit lane} from Jolpica stops, OpenF1 pit rows and stint changes."""
        def f():
            out: dict[str, set[int]] = {}
            for p in self.race.get("pitstops") or []:
                if p.get("driver") and inum(p.get("lap")):
                    out.setdefault(p["driver"], set()).add(inum(p["lap"]))
            rec = self.session("race")
            if rec:
                ids = self.ids("race")
                for p in rec.get("pit") or []:
                    d = ids.get(str(p[0]))
                    if d and inum(p[1]):
                        out.setdefault(d, set()).add(inum(p[1]))
                for s in rec.get("stints") or []:
                    d = ids.get(str(s[0]))
                    if d and (inum(s[1]) or 1) > 1 and (inum(s[2]) or 0) > 1:
                        out.setdefault(d, set()).add(inum(s[2]) - 1)
            return out
        return self._memo("inlaps", f) or {}

    def pits(self) -> list[dict]:
        """[{"driver","lap","lane_ms","stop_ms"}]: OpenF1 pit rows (2023-), else Jolpica stops (lane time only)."""
        def f():
            rec = self.session("race")
            out = []
            if rec and rec.get("pit"):
                ids = self.ids("race")
                for p in rec["pit"]:
                    d = ids.get(str(p[0]))
                    if d:
                        out.append({"driver": d, "lap": inum(p[1]), "lane_ms": inum(p[3]), "stop_ms": inum(p[4])})
            else:
                for p in self.race.get("pitstops") or []:
                    if p.get("driver"):
                        out.append({"driver": p["driver"], "lap": inum(p.get("lap")), "lane_ms": inum(p.get("duration_ms")), "stop_ms": None})
            out.sort(key=lambda r: (r["lap"] or 0, r["driver"]))
            return out
        return self._memo("pits", f) or []

    def stints(self) -> dict[str, list[dict]]:
        """{driver: [{"compound","from","to","age_start"}]}: OpenF1 stints, else inferred from in-laps (compound None)."""
        def f():
            rec = self.session("race")
            out: dict[str, list[dict]] = {}
            if rec and rec.get("stints"):
                ids = self.ids("race")
                for s in sorted(rec["stints"], key=lambda s: (str(s[0]), inum(s[1]) or 0)):
                    d = ids.get(str(s[0]))
                    if d:
                        comp = str(s[4]).upper() if s[4] else None
                        out.setdefault(d, []).append({"compound": comp, "from": inum(s[2]), "to": inum(s[3]), "age_start": inum(s[5])})
                return out
            ins = self.in_laps()
            if not ins:
                return {}
            for r in self.starters():
                d = r["driver"]
                last = inum(r.get("laps")) or 0
                if last <= 0:
                    continue
                a = 1
                for L in sorted(x for x in ins.get(d, ()) if x < last):
                    out.setdefault(d, []).append({"compound": None, "from": a, "to": L, "age_start": 0 if a == 1 else 0})
                    a = L + 1
                out.setdefault(d, []).append({"compound": None, "from": a, "to": last, "age_start": 0})
            return out
        return self._memo("stints", f) or {}

    # ------------------------------------------------------------------ race control, weather
    def control(self) -> list[dict]:
        """[{"lap","t_ms","kind","message"}]; kind SC / VSC / RED / PENALTY / FLAG / OTHER; blue flags dropped."""
        def f():
            rec = self.session("race")
            out = []
            for r in (rec or {}).get("race_control") or []:
                if not isinstance(r, (list, tuple)) or len(r) < 8:
                    continue
                t, lap, cat, flag, _scope, _sector, _dn, msg = r[:8]
                m, fl = str(msg or "").upper(), str(flag or "").upper()
                if fl == "BLUE":
                    continue
                if cat == "SafetyCar":
                    kind = "VSC" if ("VIRTUAL" in m or "VSC" in m) else "SC"
                elif fl == "RED" or _RED_RE.search(m):
                    kind = "RED"
                elif "PENALTY" in m:
                    kind = "PENALTY"
                elif cat == "Flag":
                    kind = "FLAG"
                else:
                    kind = "OTHER"
                out.append({"lap": inum(lap), "t_ms": inum(t), "kind": kind, "message": msg})
            return out
        return self._memo("control", f) or []

    def neutral_windows(self) -> list[dict]:
        """[{"from","to","kind"}] laps under SC / VSC / red flag: race control deployments (2023-), else
        runs of the lap model's neutralised laps (field-median lap > 107% of the race median)."""
        def f():
            out = []
            ctl = self.control()
            open_: dict[str, int] = {}
            for c in ctl:
                m = str(c["message"] or "").upper()
                if c["kind"] in ("SC", "VSC"):
                    if "DEPLOYED" in m and c["kind"] not in open_ and c["lap"]:
                        open_[c["kind"]] = c["lap"]
                    elif c["kind"] in open_ and ("ENDING" in m or "IN THIS LAP" in m or "ENDED" in m):
                        out.append({"from": open_.pop(c["kind"]), "to": c["lap"] or 0, "kind": c["kind"]})
                elif c["kind"] == "RED" and c["lap"]:
                    out.append({"from": c["lap"], "to": c["lap"], "kind": "RED"})
            for k, a in open_.items():
                out.append({"from": a, "to": a + 3, "kind": k})
            if out or ctl:
                return sorted(out, key=lambda w: w["from"])
            nl = sorted(set((self.pace() or {}).get("neutral_laps") or []))
            run: list[int] = []
            for L in nl + [10 ** 6]:
                if run and L != run[-1] + 1:
                    if run[0] > 1:
                        out.append({"from": run[0], "to": run[-1], "kind": "SC"})
                    run = []
                run.append(L)
            return out
        return self._memo("neutral", f) or []

    def neutral_laps(self) -> set[int]:
        s: set[int] = set()
        for w in self.neutral_windows():
            s.update(range(int(w["from"]), int(max(w["from"], w["to"])) + 1))
        return s

    def weather(self) -> list[dict]:
        def f():
            rec = self.session("race")
            return [{"t_ms": inum(w[0]), "air": fnum(w[1]), "track": fnum(w[2]), "rain": inum(w[4]), "wind": fnum(w[5])}
                    for w in (rec or {}).get("weather") or [] if isinstance(w, (list, tuple)) and len(w) >= 6]
        return self._memo("weather", f) or []

    def wet(self) -> bool | None:
        def f():
            rec = self.session("race")
            if not rec:
                return None
            w = [x for x in self.weather() if (x["t_ms"] or 0) >= 0]
            rain = sum(1 for x in w if x["rain"]) / len(w) if w else 0.0
            st = self.stints()
            wet_drivers = sum(1 for d, ss in st.items() if any(s["compound"] in ("INTERMEDIATE", "WET") for s in ss))
            return bool(rain >= 0.10 or (st and wet_drivers >= 0.25 * len(st)))
        return self._memo("wet", f)

    def penalties(self) -> dict[str, int]:
        """{driver: penalties} from race-control messages in the race and sprint naming his car number
        with a penalty (served / no-further-action / investigation notices excluded)."""
        def f():
            out: dict[str, int] = {}
            for kind in ("race", "sprint"):
                rec = self.session(kind)
                if not rec:
                    continue
                ids = self.ids(kind)
                seen = set()
                for r in rec.get("race_control") or []:
                    msg = str((r[7] if len(r) > 7 else "") or "").upper()
                    if "PENALTY" not in msg or any(s in msg for s in _PEN_SKIP) or msg in seen:
                        continue
                    seen.add(msg)
                    m = _PEN_RE.search(msg)
                    d = ids.get(m.group(1)) if m else ids.get(str(r[6])) if len(r) > 6 and r[6] is not None else None
                    if d:
                        out[d] = out.get(d, 0) + 1
            return out
        return self._memo("pen", f) or {}

    # ------------------------------------------------------------------ passes
    def _lap_index(self) -> dict[str, tuple[list[float], list[int]]]:
        def f():
            rec = self.session("race")
            ids = self.ids("race")
            out = {}
            for num, rows in ((rec or {}).get("laps") or {}).items():
                d = ids.get(str(num))
                if not d:
                    continue
                st = sorted((fnum(r[1]), int(r[0])) for r in rows or [] if r and r[0] is not None and fnum(r[1]) is not None)
                out[d] = ([s for s, _ in st], [L for _, L in st])
            return out
        return self._memo("lapidx", f) or {}

    def lap_at(self, d: str, t_ms: float | None) -> int | None:
        idx = self._lap_index().get(d)
        if not idx or t_ms is None:
            return None
        i = bisect_right(idx[0], t_ms) - 1
        return idx[1][i] if i >= 0 else 1

    def _pitting(self, d: str, lap: int | None) -> bool:
        if lap is None:
            return False
        ins = self.in_laps().get(d, set())
        return lap in ins or (lap - 1) in ins

    def overtakes(self) -> list[dict]:
        """[{"lap","by","on","pos","t_ms"}] on-track passes from OpenF1 (see module docstring)."""
        def f():
            rec = self.session("race")
            if not rec:
                return []
            ids = self.ids("race")
            neutral = self.neutral_laps()
            stopped = {r["driver"]: inum(r.get("laps")) or 0 for r in self.results if status_kind(r) not in ("finished", "dns")}
            out = []
            for o in rec.get("overtakes") or []:
                if not isinstance(o, (list, tuple)) or len(o) < 4:
                    continue
                a, b = ids.get(str(o[1])), ids.get(str(o[2]))
                if not a or not b or a == b:
                    continue
                la, lb = self.lap_at(a, fnum(o[0])), self.lap_at(b, fnum(o[0]))
                if self._pitting(b, lb) or (la is not None and (la - 1) in self.in_laps().get(a, set())):
                    continue
                if la is not None and la in neutral:                 # order changes under SC / VSC: not passes
                    continue
                if b in stopped and la is not None and stopped[b] <= la + 2:
                    continue                                         # passing a car that is about to retire
                if a in stopped and la is not None and stopped[a] <= la:
                    continue
                out.append({"lap": la, "by": a, "on": b, "pos": inum(o[3]), "t_ms": inum(o[0])})
            return out
        return self._memo("ovt", f) or []

    def derived_passes(self) -> list[dict]:
        """[{"lap","by","on","pos"}] position swaps between consecutive lap ends (see module docstring)."""
        def f():
            pos = self.laps()["positions"]
            if not pos:
                return []
            neutral = self.neutral_laps()
            stopped = {r["driver"]: inum(r.get("laps")) or 0 for r in self.results if status_kind(r) not in ("finished", "dns")}
            out = []
            n = self.laps()["n"]
            for L in range(2, n + 1):
                if L in neutral or (L - 1) in neutral:
                    continue
                prev = {d: p[L - 2] for d, p in pos.items() if len(p) >= L and p[L - 2] is not None and p[L - 1] is not None}
                cur = {d: pos[d][L - 1] for d in prev}
                movers = [d for d in prev if cur[d] < prev[d] and not any(self._pitting(d, x) for x in (L - 1, L, L + 1))]
                for a in movers:
                    for b, pb in prev.items():
                        if b == a or not (prev[a] > pb and cur[a] < cur[b]):
                            continue
                        if any(self._pitting(b, x) for x in (L - 1, L, L + 1)) or (b in stopped and stopped[b] <= L + 2):
                            continue
                        out.append({"lap": L, "by": a, "on": b, "pos": cur[a]})
            return out
        return self._memo("dpass", f) or []

    # ------------------------------------------------------------------ pace
    def pace(self) -> dict:
        def f():
            if not self.done:
                return {"drivers": {}, "fuel_coef": None}
            if not (self.race.get("laps") or (self.session("race") or {}).get("laps")):
                return {"drivers": {}, "fuel_coef": None, "reason": "no lap times on disk"}
            from oddsmarkets.f1.models.laptime import race_pace
            return race_pace(self.year, self.round)
        return self._memo("pace", f) or {"drivers": {}, "fuel_coef": None}

    def pace_rank(self) -> dict[str, int]:
        pd = (self.pace().get("drivers") or {})
        order = sorted(pd, key=lambda d: pd[d]["pace"])
        return {d: k for k, d in enumerate(order, 1)}

    def lap_scatter(self) -> dict[str, float]:
        """{driver: sd of corrected clean laps (s)} (see module docstring)."""
        def f():
            pace = self.pace()
            pd = pace.get("drivers") or {}
            if not pd:
                return {}
            from oddsmarkets.f1.models import laptime as lt
            sess = self.session("race")
            ids = self.ids("race") if sess else {}
            team = {d: (self.team_of(d) or f"_{d}") for d in pd}
            rows, _info = lt.assemble(self.race, sess, ids, team, self.year)
            fuel = fnum(pace.get("fuel_coef")) or 0.0
            res: dict[str, list[float]] = {}
            for r in rows:
                d = r["driver"]
                if r.get("excl") or d not in pd or not r.get("lap_s"):
                    continue
                deg = fnum((pd[d].get("deg") or {}).get(r["compound"])) or 0.0
                res.setdefault(d, []).append(r["lap_s"] - fuel * r["fuel"] - deg * r["age"])
            return {d: round(sd(v), 4) for d, v in res.items() if len(v) >= 8 and sd(v) is not None}
        return self._memo("scatter", f) or {}

    # ------------------------------------------------------------------ qualifying helpers
    def quali_rows(self) -> list[dict]:
        return sorted(self.qualifying, key=lambda r: inum(r.get("position")) or 99)

    def quali_deepest(self, d: str) -> tuple[str | None, int | None]:
        """(segment, ms) of the driver's deepest timed segment (q3 > q2 > q1)."""
        for r in self.qualifying:
            if r.get("driver") == d:
                for seg in ("q3", "q2", "q1"):
                    if inum(r.get(seg)):
                        return seg, inum(r.get(seg))
        return None, None

    def quali_time(self, d: str, seg: str) -> int | None:
        for r in self.qualifying:
            if r.get("driver") == d:
                return inum(r.get(seg))
        return None
