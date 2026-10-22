"""
ATP Challenger results (Wikipedia draws, sources/wikipedia.py) as MATCH rows for the ratings.

`rows(tour, registry, known)` reads data/tennis/wiki/atp_ch_<year>.json (scripts/tn_wiki.py) and returns MATCH rows
(level "ch", best of three, ratings only; CONTRACT.md) with players resolved to the registry's pids by full name and
flag country (canon.Registry.find, never creating a player); a name the registry does not know becomes
"wk:<slug>", a player seen only at Challenger level.

Ranks. A Challenger row carries, for each player, the latest rank on an earlier tour-level or qualifying row
(`known`: the stores' MATCH rows) within RANK_DAYS before the match, else none; so a player's first Challenger match
enters Elo and the market rating from the same rank prior as a tour match would. Nothing later than the match is
read.

Dates. Each match is dated by its round from the week's Monday (sources/wikipedia.round_day: final + 6, semi-final
+ 5, quarter-final + 4, second round + 3, first round + 2), on or after the day it was played in a normal week;
`lag_days` (research) delays every match of an event to the Monday after it instead.
"""
from __future__ import annotations

import bisect
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from oddsmarkets.tennis import canon
from oddsmarkets.tennis.models import _io

RANK_DAYS = 120
ROUND_ORDER = ("R64", "R32", "R16", "QF", "SF", "F")


def wiki_dir() -> Path:
    return canon.raw_root() / "wiki"


def load_raw(years: Iterable[int] | None = None) -> list[dict]:
    out = []
    for p in sorted(wiki_dir().glob("atp_ch_*.json")):
        try:
            y = int(p.stem.rsplit("_", 1)[1])
        except ValueError:
            continue
        if years is not None and y not in set(years):
            continue
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


class Resolver:
    """Wikipedia name (+ flag) -> pid, cached; never adds a player to the registry."""

    def __init__(self, registry: canon.Registry):
        self.reg = registry
        self.memo: dict[tuple, str] = {}
        self.linked = self.created = 0

    def __call__(self, name: str, flag: str | None) -> str:
        key = (canon.fold(name), (flag or "").upper())
        if key in self.memo:
            return self.memo[key]
        pid = None
        for nm in _variants(name):
            fn, ln = canon.split_full(nm)
            if fn and ln:
                pid = self.reg._match_full(fn, ln, flag, None, None)
            if pid is None:
                pid = self.reg.find("wiki", nm)
            if pid is not None:
                break
        if pid is None:
            pid = self._by_surname(name, flag)
        if pid is None:
            pid = "wk:" + canon.slug(name)
            self.created += 1
        else:
            pid = self.reg.canonical(pid)
            self.linked += 1
        self.memo[key] = pid
        return pid

    def _by_surname(self, name: str, flag: str | None) -> str | None:
        """Same surname (any token split), same country and the same first initial, unique in the registry: "Dan
        Evans" for Daniel Evans, "Christian Garin" for Cristian Garin; or the registry's surname a prefix of this one
        ("Roberto Cid Subervi" for Roberto Cid)."""
        if not flag:
            return None
        toks = canon.name_tokens(name)
        if len(toks) < 2:
            return None
        hits = set()
        for k in range(1, len(toks)):
            first, last = toks[:k], toks[k:]
            for j in range(len(last), 0, -1):
                for c in self.reg.by_surname.get("".join(last[:j]), set()):
                    c = self.reg.canonical(c)
                    q = self.reg.players.get(c) or {}
                    if (q.get("country") or "").upper() != flag.upper() or q.get("_abbrev"):
                        continue
                    qf, ql = canon.split_full(q.get("first"), q.get("last"), q.get("name"))
                    if not qf or not ql or "".join(ql) != "".join(last[:j]):
                        continue
                    if qf[0][:1] == first[0][:1]:
                        hits.add(c)
                if hits:
                    break
            if hits:
                break
        return hits.pop() if len(hits) == 1 else None


_TRANSLIT = (("đ", "dj"), ("Đ", "Dj"), ("ö", "oe"), ("ü", "ue"), ("ä", "ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("Ä", "Ae"),
             ("ß", "ss"), ("ø", "o"), ("ć", "c"), ("č", "c"))


def _variants(name: str) -> list[str]:
    """The name, then common transliterations (Đere -> Djere, Köpfer -> Koepfer) and hyphenated given names joined
    (Lee Duck-hee -> Lee Duckhee)."""
    out = [name]
    t = name
    for a, b in _TRANSLIT:
        t = t.replace(a, b)
    out.append(t)
    for x in list(out):
        if "-" in x:
            parts = x.split()
            out.append(" ".join(p.replace("-", "") if i != len(parts) - 1 or len(parts) == 1 else p
                                for i, p in enumerate(parts)))
            out.append(" ".join(p.replace("-", "") for p in parts))
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


_ABBR = re.compile(r"^([A-Z])\.?\s+(.+)$")


def _abbr_key(initial: str, surname: str, flag: str | None) -> tuple:
    return (initial.lower(), canon.fold(surname).replace(" ", ""), (flag or "").upper())


def _full_names(seasons: list[dict]) -> dict[tuple, set]:
    """(initial, surname, flag) -> the full names seen with it, for unlinked players shown as "D Kelly"."""
    acc: dict[tuple, set] = {}
    for season in seasons:
        for m in season.get("matches") or []:
            for nm, fl in ((m.get("a"), m.get("flag_a")), (m.get("b"), m.get("flag_b"))):
                if not nm or _ABBR.match(nm):
                    continue
                toks = nm.split()
                if len(toks) < 2:
                    continue
                for k in range(1, len(toks)):
                    acc.setdefault(_abbr_key(toks[0][:1], " ".join(toks[k:]), fl), set()).add(nm)
    return acc


def _expand(name: str, flag: str | None, full: dict[tuple, set]) -> str:
    m = _ABBR.match(name or "")
    if not m:
        return name
    hits = full.get(_abbr_key(m.group(1), m.group(2), flag)) or set()
    return next(iter(hits)) if len(hits) == 1 else name


def _rank_index(known: Iterable[dict]) -> dict[str, tuple[list[int], list[float]]]:
    acc: dict[str, list[tuple[int, float]]] = {}
    for m in known:
        d = _io.day(m.get("date"))
        if d is None:
            continue
        for pid, rk in ((m.get("p1"), m.get("rank1")), (m.get("p2"), m.get("rank2"))):
            try:
                r = float(rk)
            except (TypeError, ValueError):
                continue
            if pid and r >= 1:
                acc.setdefault(str(pid), []).append((d.toordinal(), r))
    out = {}
    for pid, xs in acc.items():
        xs.sort()
        out[pid] = ([x[0] for x in xs], [x[1] for x in xs])
    return out


def _rank_before(idx: dict, pid: str, day: int) -> float | None:
    v = idx.get(pid)
    if not v:
        return None
    i = bisect.bisect_left(v[0], day) - 1          # strictly before the match day
    if i < 0 or day - v[0][i] > RANK_DAYS:
        return None
    return v[1][i]


def rows(tour: str = "atp", registry: canon.Registry | None = None, known: Iterable[dict] | None = None,
         years: Iterable[int] | None = None, lag_days: int | None = None, with_rank: bool = True) -> tuple[list[dict], dict]:
    """(MATCH rows, {"events": {eid: event}, "players": {pid: {...}}, "stats": {...}})."""
    if canon.tour_key(tour) != "atp":
        return [], {"events": {}, "players": {}, "stats": {}}
    reg = registry or canon.Registry.load("atp")
    res = Resolver(reg)
    idx = _rank_index(known or []) if with_rank else {}
    out, events, players = [], {}, {}
    seasons = load_raw(years)
    full = _full_names(seasons)
    for season in seasons:
        for ev in season.get("events") or []:
            events[ev["id"]] = {"name": ev.get("name"), "start": ev.get("week"), "level": "ch",
                                "surface": ev.get("surface"), "indoor": bool(ev.get("indoor")), "city": ev.get("city"),
                                "country": ev.get("country"), "draw_size": ev.get("draw"), "source": "wikipedia",
                                "page": ev.get("singles")}
        wk = {ev["id"]: ev.get("week") for ev in season.get("events") or []}
        for m in season.get("matches") or []:
            if m.get("status") not in ("done", "ret", "wo") or not m.get("winner"):
                continue
            na, nb = _expand(m["a"], m.get("flag_a"), full), _expand(m["b"], m.get("flag_b"), full)
            m = dict(m, a=na, b=nb)
            pa, pb = res(na, m.get("flag_a")), res(nb, m.get("flag_b"))
            if pa == pb:
                continue
            for pid, nm, fl in ((pa, m["a"], m.get("flag_a")), (pb, m["b"], m.get("flag_b"))):
                players.setdefault(pid, {"name": nm, "country": fl})
            d = m["date"]
            if lag_days is not None and wk.get(m["event"]):
                d = (date.fromisoformat(wk[m["event"]]) + timedelta(days=int(lag_days))).isoformat()
            dd = date.fromisoformat(d).toordinal()
            winner = pa if m["winner"] == "a" else pb
            rid = f"{m['event']}-{m['round']}-{canon.slug(m['a'])}-{canon.slug(m['b'])}"
            out.append({"id": rid, "event": m["event"], "date": d, "round": m["round"], "best_of": 3,
                        "surface": m.get("surface") or "hard", "indoor": bool(m.get("indoor")), "level": "ch",
                        "p1": pa, "p2": pb, "winner": winner, "status": m["status"], "sets": m.get("sets") or [],
                        "final_set_rule": "tb7", "rank1": _rank_before(idx, pa, dd), "rank2": _rank_before(idx, pb, dd),
                        "pts1": None, "pts2": None, "odds": None, "stats": None, "live": None, "sources": ["wikipedia"]})
    out.sort(key=_io.match_key)
    return out, {"events": events, "players": players,
                 "stats": {"rows": len(out), "names_linked": res.linked, "names_new": res.created}}


def merge_into_stores(tour: str = "atp", years: Iterable[int] | None = None, rank_new: float | None = None,
                      log=None) -> dict:
    """Write the Wikipedia Challenger rows into the season stores (level "ch", source "wikipedia"), replacing the
    earlier Wikipedia rows of those seasons: identity is re-resolved on every run, so a Challenger-only player who has
    since reached the tour (and the registry) is linked back. `rank_new`: the rank a player first seen on a
    Challenger row without one takes (tennis_edge.md 11.0, C2b; None keeps the unranked prior, C2a)."""
    from oddsmarkets.tennis import store as ST
    t = canon.tour_key(tour)
    if t != "atp":
        return {}
    reg = canon.Registry.load(t)
    known = [m for m in _io.load_matches(t, statuses=None) if "wikipedia" not in (m.get("sources") or [])]
    rws, meta = rows(t, reg, known, years=years)
    if rank_new is not None:
        for r in rws:
            r["rank1"] = r["rank1"] if r["rank1"] is not None else rank_new
            r["rank2"] = r["rank2"] if r["rank2"] is not None else rank_new
    by_year: dict[int, list] = {}
    for r in rws:
        by_year.setdefault(int(r["date"][:4]), []).append(r)
    touched = sorted(set(by_year) | (set(years) if years is not None else set()))
    out = {}
    for y in touched:
        if y not in _io.years_on_disk(t):
            continue
        s = ST.load(t, y)
        for mid in [k for k, m in s["matches"].items() if "wikipedia" in (m.get("sources") or [])]:
            s["matches"].pop(mid)
        for eid in [k for k, e in s["events"].items() if e.get("source") == "wikipedia"]:
            s["events"].pop(eid)
        ST.drop_index(s)
        for r in by_year.get(y, []):
            r = {k: v for k, v in r.items() if v is not None or k in ("winner",)}
            s["matches"][r["id"]] = r
            if r["event"] not in s["events"]:
                ev = meta["events"].get(r["event"]) or {}
                wk = ev.get("start")
                s["events"][r["event"]] = {**ev, "tid": r["event"], "year": y,
                                           "end": (date.fromisoformat(wk) + timedelta(days=6)).isoformat() if wk else None,
                                           "status": "done", "best_of": 3}
            for pid in (r["p1"], r["p2"]):
                if pid not in s["players"]:
                    pl = reg.players.get(pid) or meta["players"].get(pid) or {}
                    s["players"][pid] = {k: pl.get(k) for k in ("name", "short", "country", "hand", "dob", "espn")
                                         if pl.get(k) is not None}
        for eid, ev in s["events"].items():
            if ev.get("source") != "wikipedia":
                continue
            fin = [m for m in s["matches"].values() if m.get("event") == eid and m.get("round") == "F" and m.get("winner")]
            ev["champion"] = fin[0]["winner"] if fin else None
        s["meta"].setdefault("sources", {})["wikipedia"] = LICENSE_NOTE
        ST.save(s)
        out[y] = len(by_year.get(y, []))
        if log:
            log(f"{t} {y}: {out[y]} Challenger rows")
    out["stats"] = meta["stats"]
    return out


LICENSE_NOTE = {"name": "Wikipedia", "license": "CC BY-SA 4.0", "url": "https://en.wikipedia.org/",
                "attribution": "ATP Challenger main-draw results: Wikipedia contributors (CC BY-SA 4.0)",
                "use": "Challenger rows (level ch): ratings and features only, never priced or scored"}
