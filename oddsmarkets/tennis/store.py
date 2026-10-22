"""
Season stores for The Quant Ace: one JSON per tour and season, the single source of truth the
models and the build read (CONTRACT.md section 1).

    docs/ace/data/<tour>/<year>/store.json
    {"tour", "year", "updated_at",
     "players":  {pid: {name, short, country, hand, dob, height, espn, wta, aliases}},
     "events":   {event_id: {tid, name, year, start, end, level, surface, indoor, draw_size, best_of,
                             city, country, espn, wta, status, champion, draw}},
     "matches":  {mid: MATCH},
     "rankings": {"date", "rows": [[rank, pid, points]], "source"},
     "meta":     {"sources": {...}, "fetched": {...}, "conflicts": [...]}}

`merge_record` folds one source match record (canon.SMR_DOC) into the store: one MATCH per real
match whichever sources saw it (keyed by event + the two players, the round confirming), with
results and odds from tennis-data, tiebreak points from ESPN or the WTA, live state from ESPN or
the WTA, and serve/return stats from the WTA. `event_for` finds or creates the event a record
belongs to (by source id, then canonical tid and dates, then city and dates).

The data root can be redirected with ACE_DATA (the models read the same variable).
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Callable

from . import canon

logger = logging.getLogger(__name__)

FINAL = ("done", "ret", "wo", "def")
STATUS_RANK = {"upcoming": 0, "live": 1, "done": 2, "ret": 2, "wo": 2, "def": 2}
ROUND_DEPTH = {"Q1": -3, "Q2": -2, "Q3": -1, "R128": 0, "R64": 1, "R32": 2, "R16": 3, "RR": 3, "QF": 4, "SF": 5,
               "BR": 5, "F": 6}


def data_root() -> Path:
    return canon.data_root()


def year_dir(tour: str, year: int) -> Path:
    return data_root() / canon.tour_key(tour) / str(int(year))


def store_path(tour: str, year: int) -> Path:
    return year_dir(tour, year) / "store.json"


def new_store(tour: str, year: int) -> dict[str, Any]:
    return {"tour": canon.tour_key(tour), "year": int(year), "updated_at": None, "players": {}, "events": {},
            "matches": {}, "rankings": {"date": None, "rows": []},
            "meta": {"sources": {}, "fetched": {}, "conflicts": []}}


def load(tour: str, year: int, registry: canon.Registry | None = None) -> dict[str, Any]:
    p = store_path(tour, year)
    s = None
    if p.exists():
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            s = None
    if not isinstance(s, dict):
        s = new_store(tour, year)
    for k, v in new_store(tour, year).items():
        s.setdefault(k, v)
    for k in ("sources", "fetched", "conflicts"):
        s["meta"].setdefault(k, [] if k == "conflicts" else {})
    for eid, x in (s["meta"].get("event_src") or {}).items():
        if eid in s["events"]:
            s["events"][eid].update(x)
    if registry is not None and registry.redirects:
        remap(s, registry.canonical)
    return s


def _write_json(p: Path, obj: Any) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)
    return p


def save(s: dict[str, Any]) -> Path:
    s["updated_at"] = canon.now()
    s["events"] = dict(sorted(s["events"].items(), key=lambda kv: (kv[1].get("start") or "", kv[0])))
    s["matches"] = dict(sorted(s["matches"].items(),
                               key=lambda kv: ((kv[1].get("date") or "")[:10], kv[1].get("event") or "",
                                               ROUND_DEPTH.get(kv[1].get("round"), 0), kv[0])))
    s["meta"]["conflicts"] = s["meta"].get("conflicts", [])[-200:]
    # bookkeeping keys of events (source ids, which source set a field) live in meta, not on events
    priv = {}
    for eid, ev in s["events"].items():
        x = {k: ev.pop(k) for k in [k for k in ev if k.startswith("_")]}
        if x:
            priv[eid] = x
    s["meta"]["event_src"] = priv
    pairs = s.pop("_pairs", None)
    try:
        return _write_json(store_path(s["tour"], s["year"]), s)
    finally:
        for eid, x in priv.items():
            if eid in s["events"]:
                s["events"][eid].update(x)
        if pairs is not None:
            s["_pairs"] = pairs


def years_on_disk(tour: str) -> list[int]:
    d = data_root() / canon.tour_key(tour)
    if not d.exists():
        return []
    return sorted(int(x.name) for x in d.iterdir() if x.is_dir() and x.name.isdigit() and (x / "store.json").exists())


def match_id(event_id: str, rnd: str | None, pa: str, pb: str) -> str:
    x, y = sorted([str(pa), str(pb)])
    return f"{event_id}-{rnd or 'NA'}-{x}-{y}"


def remap(s: dict, fn: Callable[[str], str]) -> int:
    """Apply a pid mapping (registry redirects) to every pid in a store; returns matches re-keyed."""
    n = 0
    new_matches = {}
    for mid, m in s.get("matches", {}).items():
        p1, p2 = fn(m.get("p1")), fn(m.get("p2"))
        if p1 != m.get("p1") or p2 != m.get("p2"):
            n += 1
        m["p1"], m["p2"] = p1, p2
        if m.get("winner"):
            m["winner"] = fn(m["winner"])
        if m.get("live") and m["live"].get("server"):
            m["live"]["server"] = fn(m["live"]["server"])
        nid = match_id(m["event"], m.get("round"), p1, p2)
        m["id"] = nid
        if nid in new_matches:
            new_matches[nid] = _merge_match(new_matches[nid], m)
        else:
            new_matches[nid] = m
    s["matches"] = new_matches
    players = {}
    for pid, p in s.get("players", {}).items():
        players.setdefault(fn(pid), p)
    s["players"] = players
    for ev in s.get("events", {}).values():
        if ev.get("champion"):
            ev["champion"] = fn(ev["champion"])
        d = ev.get("draw")
        if d:
            for slot in d.get("slots") or []:
                if slot[1]:
                    slot[1] = fn(slot[1])
    rk = s.get("rankings") or {}
    for row in rk.get("rows") or []:
        row[1] = fn(row[1])
    return n


# ── events ──────────────────────────────────────────────────────────────────

def _overlap(a0: str | None, a1: str | None, b0: str | None, b1: str | None, slack: int = 3) -> bool:
    try:
        a0d, b0d = date.fromisoformat(str(a0)[:10]), date.fromisoformat(str(b0)[:10])
        a1d = date.fromisoformat(str(a1 or a0)[:10])
        b1d = date.fromisoformat(str(b1 or b0)[:10])
    except (TypeError, ValueError):
        return False
    return (a0d - b1d).days <= slack and (b0d - a1d).days <= slack


def _tokens(name: Any) -> set[str]:
    stop = {"open", "the", "championships", "championship", "international", "tennis", "cup", "presented", "by",
            "de", "of", "and", "atp", "wta", "masters", "classic", "trophy", "tournament", "grand", "prix", "ladies",
            "women", "s", "mens", "womens", "tour", "series"}
    return {t for t in canon.fold(name).split() if t not in stop and not t.isdigit() and len(t) > 2}


def _common(a: Any, b: Any) -> int:
    """Shared significant name tokens; a token that starts the other counts ("banc" / "banco")."""
    ta, tb = _tokens(a), _tokens(b)
    n = 0
    for x in ta:
        if any(x == y or (len(x) >= 4 and len(y) >= 4 and (x.startswith(y) or y.startswith(x))) for y in tb):
            n += 1
    return n


def rename_event(s: dict, eid: str, tid: str) -> str:
    """Give an event a new canonical tid (an ESPN-made id replaced by tennis-data's); re-keys its matches."""
    ev = s["events"].get(eid)
    if not ev or ev["tid"] == tid:
        return eid
    taken = {e["tid"] for k, e in s["events"].items() if k != eid}
    new_tid, k = tid, 2
    while new_tid in taken:
        new_tid = f"{tid}-{k}"
        k += 1
    new_eid = canon.event_id(new_tid, s["year"])
    ev["tid"] = new_tid
    s["events"] = {(new_eid if k2 == eid else k2): v for k2, v in s["events"].items()}
    out = {}
    for mid, m in s["matches"].items():
        if m["event"] == eid:
            m["event"] = new_eid
            m["id"] = match_id(new_eid, m.get("round"), m["p1"], m["p2"])
            out[m["id"]] = m
        else:
            out[mid] = m
    s["matches"] = out
    drop_index(s)
    return new_eid


def event_for(s: dict, meta: dict, src: str, create: bool = True) -> str | None:
    """The event_id a source record belongs to, creating the event when new. None for skipped events."""
    tour, year = s["tour"], s["year"]
    tid_hint = meta.get("tid_hint") or canon.tid_for(tour, meta.get("name"), meta.get("city"), meta.get("level"))
    if tid_hint in ("skip", "next-gen-finals", "unknown"):
        return None
    evs = s["events"]
    forced = meta.get("_eid")
    if forced and forced in evs:
        _fill_event(evs[forced], meta, src, tour)
        return forced
    sid = meta.get(src) if src in ("td", "espn", "wta") else None
    if sid:
        for eid, ev in evs.items():
            if str(ev.get(f"_{src}") or "") == str(sid) or f"{src}:{sid}" in (ev.get("_alias") or ()):
                _fill_event(ev, meta, src, tour)
                return eid
    city = canon.city_key(meta.get("city"))
    cands = []
    for eid, ev in evs.items():
        if not _overlap(ev.get("start"), ev.get("end"), meta.get("start"), meta.get("end")):
            continue
        if ev.get(f"_{src}") and sid and str(ev[f"_{src}"]) != str(sid):
            continue                                    # another event of the same source
        score = 0
        base = ev["tid"].rsplit("-", 1)[0] if ev["tid"].rsplit("-", 1)[-1].isdigit() else ev["tid"]
        if ev["tid"] == tid_hint or base == tid_hint:
            score += 3
        if city and canon.city_key(ev.get("city")) == city:
            score += 2
        score += min(2, _common(ev.get("name"), meta.get("name")))
        # a city named inside the other source's event name ("Barcelona Open Banc Sabadell")
        if city and city.replace("-", " ") in canon.fold(ev.get("name")):
            score += 2
        elif ev.get("city") and canon.city_key(ev.get("city")).replace("-", " ") in canon.fold(meta.get("name")):
            score += 2
        if score >= 2:
            cands.append((score, eid))
    if cands:
        cands.sort(reverse=True)
        if len(cands) == 1 or cands[0][0] > cands[1][0]:
            eid = cands[0][1]
            _fill_event(evs[eid], meta, src, tour)
            return eid
    if not create:
        return None
    taken = {ev["tid"]: ev.get("start") for ev in evs.values()}
    tid = canon.unique_tid(tid_hint, meta.get("start"), {})
    k = 2
    while tid in taken:
        tid = f"{tid_hint}-{k}"
        k += 1
    eid = canon.event_id(tid, year)
    level = meta.get("level") or canon.default_level(tour, tid_hint)
    meta["_eid"] = eid
    evs[eid] = {"_tid_src": src, "tid": tid, "name": meta.get("name"), "year": int(year), "start": meta.get("start"),
                "end": meta.get("end"), "level": level, "surface": meta.get("surface"), "indoor": meta.get("indoor"),
                "draw_size": meta.get("draw_size"), "best_of": 5 if (tour == "atp" and level == "slam") else 3,
                "city": meta.get("city"), "country": meta.get("country"), "espn": meta.get("espn"),
                "wta": meta.get("wta"), "status": "upcoming", "champion": None, "draw": None}
    _fill_event(evs[eid], meta, src, tour)
    return eid


def _fill_event(ev: dict, meta: dict, src: str, tour: str = "atp") -> None:
    sid = meta.get(src) if src in ("td", "espn", "wta") else None
    if sid:
        ev[f"_{src}"] = str(sid)
    if src == "espn" and meta.get("espn"):
        ev["espn"] = meta["espn"]
    if src == "wta" and meta.get("wta"):
        ev["wta"] = meta["wta"]
    # tennis-data's series/court/surface win; then the WTA calendar; ESPN fills gaps only
    strong = src in ("td", "wta")
    for k in ("level", "surface", "indoor"):
        v = meta.get(k)
        if v is None:
            continue
        if ev.get(k) is None or (strong and not ev.get(f"_lv_{k}")) or (src == "td"):
            ev[k] = v
            if strong:
                ev[f"_lv_{k}"] = src
    if meta.get("draw_size") and (src == "wta" or not ev.get("draw_size")):
        ev["draw_size"] = meta["draw_size"]
    for k in ("city", "country", "name"):
        if not ev.get(k) and meta.get(k):
            ev[k] = meta[k]
    if meta.get("start") and (not ev.get("start") or meta["start"] < ev["start"]):
        ev["start"] = meta["start"]
    if meta.get("end") and (not ev.get("end") or meta["end"] > ev["end"]):
        ev["end"] = meta["end"]
    ev["best_of"] = 5 if (ev.get("level") == "slam" and str(ev.get("tid", "")).startswith(
        ("australian-open", "roland-garros", "wimbledon", "us-open")) and tour == "atp") else ev.get("best_of", 3)


def public_event(ev: dict) -> dict:
    return {k: v for k, v in ev.items() if not k.startswith("_")}


# ── matches ─────────────────────────────────────────────────────────────────

def _flip_sets(sets: list) -> list:
    return [[s[1], s[0], s[3], s[2]] for s in sets or []]


def _flip_pair(x: Any) -> Any:
    return [x[1], x[0]] if isinstance(x, list) and len(x) == 2 else x


def build_match(s: dict, rec: dict, eid: str, pa: str, pb: str) -> dict:
    """A MATCH from a source record whose sides resolved to pa / pb (p1 = winner when known)."""
    ev = s["events"][eid]
    flip = rec.get("winner") == "b"
    p1, p2 = (pb, pa) if flip else (pa, pb)
    A, B = (rec["b"], rec["a"]) if flip else (rec["a"], rec["b"])
    rnd = rec.get("round")
    level = ev.get("level") or "250"
    if canon.is_qual(rnd):
        level = "q"
    rule, at = canon.final_set_rule(s["tour"], ev.get("tid", "").rsplit("-", 1)[0] if ev.get("tid", "").rsplit("-", 1)[-1].isdigit() else ev.get("tid"),
                                    s["year"], ev.get("level"))
    if canon.is_qual(rnd):
        rule, at = "tb7", 6
    odds = None
    if rec.get("odds"):
        odds = {k: (_flip_pair(v) if k != "other" else {kk: _flip_pair(vv) for kk, vv in v.items()}) if flip else v
                for k, v in rec["odds"].items()}
    stats = None
    if rec.get("stats"):
        st = rec["stats"]
        stats = {"p1": st["b"] if flip else st["a"], "p2": st["a"] if flip else st["b"],
                 "by_set": [{"set": x["set"], "p1": x["b"] if flip else x["a"], "p2": x["a"] if flip else x["b"]}
                            for x in st.get("by_set") or []]}
    live = None
    if rec.get("live"):
        lv = rec["live"]
        srv = lv.get("server")
        live = {"set": lv.get("set"), "games": _flip_pair(lv.get("games")) if flip else lv.get("games"),
                "points": _flip_pair(lv.get("points")) if flip else lv.get("points"),
                "server": (pa if srv == "a" else pb if srv == "b" else None)}
    m = {"id": match_id(eid, rnd, p1, p2), "event": eid, "date": rec.get("date"), "round": rnd,
         "best_of": rec.get("best_of") or canon.best_of(s["tour"], ev.get("level"), rnd, s["year"]),
         "surface": ev.get("surface"), "indoor": ev.get("indoor"), "level": level, "p1": p1, "p2": p2,
         "winner": p1 if rec.get("winner") in ("a", "b") else None, "status": rec.get("status"),
         "sets": _flip_sets(rec.get("sets")) if flip else [list(x) for x in rec.get("sets") or []],
         "final_set_rule": rule, "rank1": A.get("rank"), "rank2": B.get("rank"), "pts1": A.get("pts"),
         "pts2": B.get("pts"), "odds": odds, "stats": stats, "live": live, "sources": [rec["src"]],
         "duration_min": rec.get("duration_min")}
    if at not in (0, 6):
        m["final_set_tb_at"] = at
    if A.get("seed") or B.get("seed"):
        m["seeds"] = [A.get("seed"), B.get("seed")]
    if A.get("entry") or B.get("entry"):
        m["entries"] = [A.get("entry"), B.get("entry")]
    return m


def _same_games(a: list, b: list) -> bool:
    return [x[:2] for x in a or []] == [x[:2] for x in b or []]


def _same_era(a: Any, b: Any) -> bool:
    """A timestamped date replaces a plain one only within a year of it (ESPN dates some old matches 1900)."""
    try:
        return abs(int(str(a)[:4]) - int(str(b)[:4])) <= 1
    except ValueError:
        return False


# ESPN's stand-in time for a match with no start time: midnight US Eastern (04:00 UTC in summer, 05:00 in winter)
ESPN_NO_TIME = ("04:00", "05:00")


def _take_date(od: Any, nd: Any, src: str) -> bool:
    """Whether a source record's date replaces the stored one. A timestamp beats a plain date (within a year of it);
    ESPN's own times are the start times, so an ESPN time replaces a different stored time (a rescheduled match, or
    the stand-in midnight an earlier read kept), and an ESPN date with no valid time clears a stored stand-in
    midnight of the same day."""
    if not nd:
        return False
    od, nd = str(od or ""), str(nd)
    if not od:
        return True
    if not _same_era(nd, od):
        return False
    if len(nd) > len(od):
        return True
    if src == "espn" and len(nd) == len(od) == 16 and nd != od:
        return True
    return src == "espn" and len(nd) == 10 and len(od) == 16 and od[:10] == nd and od[11:16] in ESPN_NO_TIME


def _merge_match(old: dict, new: dict, conflicts: list | None = None) -> dict:
    """Fold `new` into `old` (same match). Precedence: final beats live beats upcoming; tennis-data
    owns odds/ranks and the official result; ESPN/WTA add tiebreak points, times and live state;
    the WTA owns stats and duration."""
    out = dict(old)
    so, sn = STATUS_RANK.get(old.get("status"), 0), STATUS_RANK.get(new.get("status"), 0)
    src = new["sources"][0] if new.get("sources") else "?"
    if sn > so or (sn == so == 1):
        # a newer state: take result fields wholesale (orientation from the new record)
        for k in ("p1", "p2", "winner", "status", "sets", "live", "rank1", "rank2", "pts1", "pts2", "odds", "stats",
                  "seeds", "entries"):
            if k in ("rank1", "rank2", "pts1", "pts2", "odds", "stats", "seeds", "entries") and new.get(k) is None:
                if k in old and old.get("p1") != new.get("p1"):          # keep, but re-orient old values
                    out[k] = _reorient(k, old.get(k))
                continue
            out[k] = new.get(k)
        if new.get("status") in FINAL:
            out["live"] = None
    elif sn == so and sn == 2:
        flip = old.get("p1") != new.get("p1")
        nsets = _flip_sets(new.get("sets")) if flip else new.get("sets")
        if _same_games(old.get("sets"), nsets):
            merged = []
            for x, y in zip(old.get("sets") or [], nsets or []):
                merged.append([x[0], x[1], x[2] if x[2] is not None else y[2], x[3] if x[3] is not None else y[3]])
            out["sets"] = merged
        elif old.get("status") != "wo" and new.get("status") != "wo":
            # sources disagree on the games: keep a score consistent with the result, tennis-data's
            # when both are
            ok_old = valid_score(old.get("sets"), old.get("status"), old.get("best_of"))
            ok_new = valid_score(nsets, old.get("status"), old.get("best_of"))
            if ok_new and (not ok_old or src == "td"):
                out["sets"] = nsets
            if conflicts is not None:
                conflicts.append({"match": old["id"], "kind": "sets", "have": old.get("sets"), "src": src, "got": nsets,
                                  "kept": "new" if out["sets"] is nsets else "old"})
        if src == "td":
            if flip and conflicts is not None:
                conflicts.append({"match": old["id"], "kind": "winner", "src": src})
            for k in ("rank1", "rank2", "pts1", "pts2"):
                v = new.get(k if not flip else {"rank1": "rank2", "rank2": "rank1", "pts1": "pts2", "pts2": "pts1"}[k])
                if v is not None:
                    out[k] = v
            if old.get("status") != new.get("status") and new.get("status") in FINAL:
                out["status"] = new["status"]
        for k in ("seeds", "entries"):
            if new.get(k) and not old.get(k):
                out[k] = _flip_pair(new[k]) if flip else new[k]
        if new.get("odds") and not flip:
            out["odds"] = new["odds"]
        elif new.get("odds"):
            out["odds"] = {k: (_flip_pair(v) if k != "other" else {kk: _flip_pair(vv) for kk, vv in v.items()})
                           for k, v in new["odds"].items()}
        if new.get("stats"):
            st = new["stats"]
            out["stats"] = st if not flip else {"p1": st["p2"], "p2": st["p1"],
                                                "by_set": [{"set": x["set"], "p1": x["p2"], "p2": x["p1"]} for x in st.get("by_set") or []]}
    # the ESPN rules apply to a fresh source record only, not to two stored rows being folded
    if _take_date(old.get("date"), new.get("date"), src if len(new.get("sources") or []) == 1 else "?"):
        out["date"] = new["date"]
    if new.get("duration_min") and not old.get("duration_min"):
        out["duration_min"] = new["duration_min"]
    if new.get("final_set_tb_at"):
        out["final_set_tb_at"] = new["final_set_tb_at"]
    out["sources"] = sorted(set(old.get("sources") or []) | set(new.get("sources") or []))
    return out


def set_complete(a: int, b: int, rule: str = "tb7") -> bool:
    hi, lo = max(a, b), min(a, b)
    return (hi == 6 and lo <= 4) or (hi >= 7 and hi - lo == 2) or (hi == 7 and lo == 6) or (hi > 7 and hi - lo >= 1 and lo >= 6)


def valid_score(sets: list | None, status: str | None, best_of: int | None) -> bool:
    """A finished match's set list is consistent with p1 having won it: for a completed match p1
    took the deciding number of complete sets and p2 fewer; a retirement or default only needs
    p2 not to have already won."""
    if not sets:
        return status in ("wo",)
    need = (int(best_of or 3) + 1) // 2
    w1 = sum(1 for x in sets if x[0] > x[1] and set_complete(x[0], x[1]))
    w2 = sum(1 for x in sets if x[1] > x[0] and set_complete(x[0], x[1]))
    if status == "done":
        return w1 == need and w2 < need and all(set_complete(x[0], x[1]) for x in sets) and sets[-1][0] > sets[-1][1]
    if status in ("ret", "def"):
        return w2 < need and w1 < need + 1
    return True


def _reorient(k: str, v: Any) -> Any:
    if v is None:
        return None
    if k in ("seeds", "entries"):
        return _flip_pair(v)
    if k == "odds":
        return {kk: (_flip_pair(vv) if kk != "other" else {a: _flip_pair(b) for a, b in vv.items()}) for kk, vv in v.items()}
    if k == "stats":
        return {"p1": v["p2"], "p2": v["p1"], "by_set": [{"set": x["set"], "p1": x["p2"], "p2": x["p1"]} for x in v.get("by_set") or []]}
    return v


def _pair_index(s: dict) -> dict:
    idx = s.get("_pairs")
    if idx is None:
        idx = {}
        for mid, m in s["matches"].items():
            idx.setdefault((m["event"], frozenset((m["p1"], m["p2"]))), []).append(mid)
        s["_pairs"] = idx
    return idx


def merge_record(s: dict, rec: dict, eid: str, pa: str, pb: str) -> str:
    """Insert or update the MATCH for a resolved source record; returns its mid."""
    new = build_match(s, rec, eid, pa, pb)
    idx = _pair_index(s)
    key = (eid, frozenset((pa, pb)))
    conflicts = s["meta"].setdefault("conflicts", [])
    mids = [m for m in idx.get(key, []) if m in s["matches"]]
    target = None
    if new["id"] in s["matches"]:
        target = new["id"]
    elif mids:
        same_round = [m for m in mids if s["matches"][m].get("round") == new["round"]]
        if same_round:
            target = same_round[0]
        elif len(mids) == 1:
            r_old = s["matches"][mids[0]].get("round")
            # same pair, same event, round labels disagree: one match unless one side is qualifying
            # (a lucky loser can meet the same player in qualifying and the main draw) or both are
            # finals-week rounds of a round-robin event
            if canon.is_qual(r_old) == canon.is_qual(new["round"]) and not ({r_old, new["round"]} <= {"RR", "F", "SF", "BR"}):
                target = mids[0]
    swap_identity = False
    if target is None and new.get("status") in FINAL and new.get("sets"):
        # one source names a different opponent (ESPN profile mix-ups): same event, round, one shared
        # player on the same side and the same games -> the same match; tennis-data's names win
        for mid, m in s["matches"].items():
            if m["event"] != eid or m.get("round") != new["round"] or m.get("status") not in FINAL:
                continue
            if set(m.get("sources") or []) & set(new["sources"]):
                continue
            same_side = (m["p1"] == new["p1"]) != (m["p2"] == new["p2"])
            if same_side and _same_games(m.get("sets"), new.get("sets")):
                target = mid
                swap_identity = rec["src"] == "td"
                conflicts.append({"match": mid, "kind": "identity", "src": rec["src"],
                                  "have": [m["p1"], m["p2"]], "got": [new["p1"], new["p2"]]})
                break
    if target is None:
        s["matches"][new["id"]] = new
        idx.setdefault(key, []).append(new["id"])
        return new["id"]
    old = s["matches"][target]
    merged = _merge_match(old, new, conflicts)
    if swap_identity:
        merged["p1"], merged["p2"], merged["winner"] = new["p1"], new["p2"], new["winner"]
    if old.get("round") != new.get("round") and rec["src"] in ("espn", "wta") and set(old.get("sources") or []) <= {"td"}:
        merged["round"] = new["round"]              # explicit draw labels beat tennis-data's inference
    merged["id"] = match_id(eid, merged["round"], merged["p1"], merged["p2"])
    if merged["id"] != target:
        s["matches"].pop(target, None)
        if swap_identity:
            drop_index(s)
        else:
            idx[key] = [m for m in idx.get(key, []) if m != target] + [merged["id"]]
    s["matches"][merged["id"]] = merged
    return merged["id"]


def drop_index(s: dict) -> None:
    s.pop("_pairs", None)


# ── one row per real match ──────────────────────────────────────────────────
#
# The three sources name events differently, and `event_for` creates a new event when a record's
# candidates tie (two events in one city in overlapping weeks: Adelaide 1 and 2, Melbourne Summer Set
# 1 and 2, Chicago's WTA 125 and 250; an ESPN event with the wrong dates). The same real match then
# sat under two or three events (a WTA 125 "ch" row from ESPN beside the WTA's and tennis-data's
# tour-level rows), and the models rated it twice. ESPN also files an event that starts in late
# December under that year while tennis-data and the WTA file it under the next season, so a match
# could sit in two seasons' stores. Event names and dates cannot settle identity; the matches can:
# two rows with the same two players within a day of each other and the same games are one match.
# `dedupe` merges events whose matches are the same matches, then folds same-match rows within an
# event; `dedupe_seasons` does the same across two adjacent seasons' stores. tn_fetch runs both on
# every save, so a store heals whichever way a duplicate arrived.

SRC_RANK = {"wta": 3, "espn": 2, "td": 1}                # whose round label is explicit (the WTA's draw first)


def _date(d: Any) -> date | None:
    try:
        return date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return None


def _played_games(m: dict, flip: bool = False) -> list:
    out = [[x[0], x[1]] for x in m.get("sets") or [] if (x[0] or 0) + (x[1] or 0) > 0]
    return [[b, a] for a, b in out] if flip else out


def same_match(a: dict, b: dict, days: int = 1) -> bool:
    """Two rows are one real match: the same two players, dates within `days`, and the same games
    when both have games (a row without games, upcoming or a walkover, needs the same qualifying /
    main-draw side, so a lucky loser's qualifying match and main-draw match stay two)."""
    if not a.get("p1") or not a.get("p2") or {a["p1"], a["p2"]} != {b.get("p1"), b.get("p2")}:
        return False
    da, db = _date(a.get("date")), _date(b.get("date"))
    if da is None or db is None or abs((da - db).days) > days:
        return False
    ga, gb = _played_games(a), _played_games(b, flip=a["p1"] != b["p1"])
    if ga and gb:
        return ga == gb
    return canon.is_qual(a.get("round")) == canon.is_qual(b.get("round"))


def _label_rank(m: dict) -> int:
    return max((SRC_RANK.get(x, 0) for x in m.get("sources") or []), default=0)


def fold_rows(keep: dict, drop: dict, conflicts: list | None = None) -> dict:
    """`drop` (another row of the same real match) folded into `keep`; keeps `keep`'s event. The round
    label of the row with the more explicit source wins (WTA draw, then ESPN, then tennis-data's inference)."""
    rnd = drop.get("round") if _label_rank(drop) > _label_rank(keep) else keep.get("round")
    merged = _merge_match(keep, drop, conflicts)
    merged["event"] = keep["event"]
    merged["round"] = rnd
    if canon.is_qual(rnd):
        merged["level"] = "q"
    elif merged.get("level") == "q":
        merged["level"] = keep.get("level") if keep.get("level") != "q" else drop.get("level")
    merged["id"] = match_id(merged["event"], rnd, merged["p1"], merged["p2"])
    return merged


def _put(s: dict, m: dict, conflicts: list | None) -> str:
    """Insert a row, folding it into a row already under its id."""
    mid = m["id"]
    if mid in s["matches"] and s["matches"][mid] is not m:
        m = fold_rows(s["matches"][mid], m, conflicts)
        if m["id"] != mid:
            s["matches"].pop(mid)
            return _put(s, m, conflicts)
    s["matches"][mid] = m
    return mid


def _absorb_event(s: dict, keep: str, gone: str) -> None:
    """Event `gone` (the same tournament as `keep`, from another source) folded into `keep`."""
    ek, eg = s["events"][keep], s["events"].pop(gone)
    alias = list(ek.get("_alias") or [])
    for src in ("td", "espn", "wta"):
        v = eg.get(f"_{src}")
        if v and not ek.get(f"_{src}"):
            ek[f"_{src}"] = v
        elif v and str(v) != str(ek[f"_{src}"]) and f"{src}:{v}" not in alias:
            alias.append(f"{src}:{v}")
    alias += [a for a in eg.get("_alias") or [] if a not in alias]
    if alias:
        ek["_alias"] = alias
    for k in ("espn", "wta"):
        if not ek.get(k) and eg.get(k):
            ek[k] = eg[k]
    strong_k = bool(ek.get("_td") or ek.get("_wta"))
    if not ek.get("_lv_level") and eg.get("_lv_level"):        # tennis-data's / the WTA's grading beats ESPN's
        for k in ("level", "surface", "indoor"):
            if eg.get(k) is not None:
                ek[k] = eg[k]
            if eg.get(f"_lv_{k}"):
                ek[f"_lv_{k}"] = eg[f"_lv_{k}"]
    for k in ("level", "surface", "indoor", "draw_size", "city", "country", "name"):
        if ek.get(k) is None and eg.get(k) is not None:
            ek[k] = eg[k]
    if not strong_k:                                           # ESPN's dates are sometimes a week or two out
        if eg.get("_td") or eg.get("_wta"):
            ek["start"], ek["end"] = eg.get("start") or ek.get("start"), eg.get("end") or ek.get("end")
        else:
            ek["start"] = min(x for x in (ek.get("start"), eg.get("start"), "9999") if x)
            ek["end"] = max(x for x in (ek.get("end"), eg.get("end"), "") if x is not None) or None
            if ek["start"] == "9999":
                ek["start"] = None
    if eg.get("_tid_src") == "td":
        ek["_tid_src"] = "td"
    dg, dk = eg.get("draw") or {}, ek.get("draw") or {}
    if dg.get("source") == "wta" and dk.get("source") != "wta":
        ek["draw"] = eg["draw"]
    conflicts = s["meta"].setdefault("conflicts", [])
    for mid in [k for k, m in s["matches"].items() if m.get("event") == gone]:
        m = s["matches"].pop(mid)
        m["event"] = keep
        if m.get("level") != "q" and ek.get("level"):
            m["level"] = ek["level"]
        m["id"] = match_id(keep, m.get("round"), m["p1"], m["p2"])
        _put(s, m, conflicts)


def _event_rank(ev: dict, n: int) -> tuple:
    return (bool(ev.get("_td")), bool(ev.get("_wta")), bool(ev.get("_espn")), n)


def dedupe(s: dict) -> dict:
    """Merge events that hold the same matches, then fold rows of one real match inside an event.
    Returns counts {"events": merged, "matches": rows removed}."""
    n0 = len(s["matches"])
    by_pair: dict[frozenset, list[dict]] = {}
    for m in s["matches"].values():
        if m.get("p1") and m.get("p2"):
            by_pair.setdefault(frozenset((m["p1"], m["p2"])), []).append(m)
    n_ev: dict[str, int] = {}
    for m in s["matches"].values():
        n_ev[m.get("event")] = n_ev.get(m.get("event"), 0) + 1
    shared: dict[tuple, set] = {}
    for rows in by_pair.values():
        if len(rows) < 2:
            continue
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if a["event"] != b["event"] and same_match(a, b):
                    k = tuple(sorted((a["event"], b["event"])))
                    shared.setdefault(k, set()).update([a["id"], b["id"]])
    # union the events whose overlap is most of the smaller one's matches
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    for (ea, eb), ids in shared.items():
        if ea not in s["events"] or eb not in s["events"]:
            continue
        na, nb = n_ev.get(ea, 0), n_ev.get(eb, 0)
        twins_a = sum(1 for i in ids if s["matches"].get(i, {}).get("event") == ea)
        twins_b = sum(1 for i in ids if s["matches"].get(i, {}).get("event") == eb)
        small = min(na, nb)
        t = min(twins_a, twins_b)
        if t >= 0.5 * small and (t >= 2 or t == small):
            ra, rb = find(ea), find(eb)
            if ra != rb:
                parent[ra] = rb
    groups: dict[str, list[str]] = {}
    for e in list(parent):
        groups.setdefault(find(e), []).append(e)
    merged_events = 0
    for root, members in groups.items():
        allm = sorted(set(members) | {root})
        keep = max(allm, key=lambda e: _event_rank(s["events"][e], n_ev.get(e, 0)))
        for e in allm:
            if e != keep:
                _absorb_event(s, keep, e)
                merged_events += 1
    # rows of one match inside an event under two round labels (a qualifying / main-draw or a finals-week mix-up)
    conflicts = s["meta"].setdefault("conflicts", [])
    by_key: dict[tuple, list[str]] = {}
    for mid, m in s["matches"].items():
        if m.get("p1") and m.get("p2"):
            by_key.setdefault((m["event"], frozenset((m["p1"], m["p2"]))), []).append(mid)
    for mids in by_key.values():
        alive = list(mids)
        changed = True
        while changed and len(alive) > 1:
            changed = False
            for i in range(len(alive)):
                for j in range(i + 1, len(alive)):
                    a, b = s["matches"].get(alive[i]), s["matches"].get(alive[j])
                    if a is None or b is None or not same_match(a, b):
                        continue
                    keep, drop = (a, b) if (_label_rank(a), len(a.get("sources") or [])) >= (
                        _label_rank(b), len(b.get("sources") or [])) else (b, a)
                    s["matches"].pop(keep["id"], None)
                    s["matches"].pop(drop["id"], None)
                    new = _put(s, fold_rows(keep, drop, conflicts), conflicts)
                    alive = [x for x in alive if x not in (a["id"], b["id"])] + [new]
                    changed = True
                    break
                if changed:
                    break
    drop_index(s)
    return {"events": merged_events, "matches": n0 - len(s["matches"])}


def dedupe_seasons(prev: dict, cur: dict) -> int:
    """Rows of the store `prev` (season Y-1) that are the same match as a row of `cur` (season Y), around
    New Year: folded into `cur`'s row (the season tennis-data and the WTA file the event under) and removed
    from `prev`, with any of `prev`'s events left empty. Returns rows removed from `prev`."""
    y = int(cur["year"])
    lo, hi = f"{y - 1}-12-01", f"{y}-01-31"
    idx: dict[frozenset, list[str]] = {}
    for mid, m in cur["matches"].items():
        if m.get("p1") and m.get("p2") and str(m.get("date") or "")[:10] <= hi:
            idx.setdefault(frozenset((m["p1"], m["p2"])), []).append(mid)
    if not idx:
        return 0
    conflicts = cur["meta"].setdefault("conflicts", [])
    touched, n = set(), 0
    for mid, m in list(prev["matches"].items()):
        if str(m.get("date") or "")[:10] < lo or not m.get("p1") or not m.get("p2"):
            continue
        for cid in idx.get(frozenset((m["p1"], m["p2"])), []):
            c = cur["matches"].get(cid)
            if c is None or not same_match(c, m):
                continue
            merged = fold_rows(c, m, conflicts)
            cur["matches"].pop(cid)
            new = _put(cur, merged, conflicts)
            idx[frozenset((m["p1"], m["p2"]))] = [x for x in idx[frozenset((m["p1"], m["p2"]))] if x != cid] + [new]
            prev["matches"].pop(mid)
            touched.add(m.get("event"))
            n += 1
            break
    left = {m.get("event") for m in prev["matches"].values()}
    for eid in touched:
        if eid not in left:
            prev["events"].pop(eid, None)
    drop_index(prev)
    drop_index(cur)
    return n


# ── event roll-ups ──────────────────────────────────────────────────────────

KO_ORDER = {"Q1": 0, "Q2": 1, "Q3": 2, "R128": 3, "R64": 4, "R32": 5, "R16": 6, "QF": 8, "SF": 9, "F": 11}


def drop_superseded(s: dict) -> int:
    """Drop scheduled matches the draw has moved past: an upcoming knockout match one of whose players has already
    finished a match of the same round against someone else, or of a later round, in the same event. Such rows are a
    source's provisional pairing (ESPN lists a first-round match before the draw settles, and keeps it after the
    player meets a lucky loser instead); left in, they show as upcoming for ever. Returns the number dropped."""
    by_ev: dict[str, list[tuple[str, dict]]] = {}
    for mid, m in s["matches"].items():
        by_ev.setdefault(m.get("event"), []).append((mid, m))
    gone = []
    for rows in by_ev.values():
        done: dict[str, list[tuple[str, int]]] = {}
        for mid, m in rows:
            if m.get("status") in FINAL and m.get("round") in KO_ORDER:
                for p in (m.get("p1"), m.get("p2")):
                    if p:
                        done.setdefault(str(p), []).append((mid, KO_ORDER[m["round"]]))
        for mid, m in rows:
            r = KO_ORDER.get(m.get("round"))
            if m.get("status") != "upcoming" or r is None:
                continue
            if any(k != mid and rr >= r for p in (m.get("p1"), m.get("p2")) if p for k, rr in done.get(str(p), ())):
                gone.append(mid)
    for mid in gone:
        s["matches"].pop(mid, None)
    if gone:
        drop_index(s)
        logger.info("%s %s: %d superseded scheduled matches dropped", s.get("tour"), s.get("year"), len(gone))
    return len(gone)


def prefer_tour_tids(s: dict) -> int:
    """Give a tour-level event its city's plain tid when the id went to a Challenger / WTA 125 event, or to an event
    since merged away, that was created first ("madrid-2-2026" for the 2026 Madrid 1000 because a 125 in Madrid two
    weeks earlier took "madrid"; "lyon-2-2026"): the plain tid is what links an event to its past editions (history,
    champions). The lower-level holder moves to the next free suffix. Returns the number of events renamed."""
    n = 0
    for eid in list(s["events"]):
        ev = s["events"].get(eid)
        if not ev or str(ev.get("level")) not in canon.TOUR_LEVELS:
            continue
        tid = str(ev.get("tid") or "")
        base, _, k = tid.rpartition("-")
        if not base or not k.isdigit():
            continue
        holder = next((k2 for k2, e2 in s["events"].items() if k2 != eid and e2.get("tid") == base), None)
        if holder is not None:
            if str(s["events"][holder].get("level")) in canon.TOUR_LEVELS:
                continue                          # two tour events in one city and year ("adelaide-2"): both real
            rename_event(s, holder, f"{base}-{int(k) + 1}")
        rename_event(s, eid, base)
        n += 1
    return n


def finalize_events(s: dict, today: date | None = None) -> None:
    """Event status and champion from its matches; reconstructed draws where none was fetched."""
    today = today or date.today()
    # a past season's scheduled-but-never-played matches (cancellations ESPN still lists) are dropped
    if int(s["year"]) < today.year:
        cut = (today.replace(day=1)).isoformat()
        for mid in [k for k, m in s["matches"].items() if m.get("status") in ("upcoming", "live")
                    and (s["events"].get(m["event"], {}).get("end") or "9999") < cut]:
            s["matches"].pop(mid)
        drop_index(s)
    drop_superseded(s)
    # exhibition entries ("EXW..." WTA ids) are not tour players: rows the WTA API listed before wta.py skipped them
    ex = {p for p, v in (s.get("players") or {}).items() if str((v or {}).get("wta") or "").upper().startswith("EX")}
    if ex:
        for mid in [k for k, m in s["matches"].items() if m.get("p1") in ex or m.get("p2") in ex]:
            s["matches"].pop(mid)
        drop_index(s)
    prefer_tour_tids(s)
    by_ev: dict[str, list[dict]] = {}
    for m in s["matches"].values():
        by_ev.setdefault(m["event"], []).append(m)
    for eid, ev in s["events"].items():
        for m in by_ev.get(eid, []):                 # event fields filled after a match was first built
            m["surface"], m["indoor"] = ev.get("surface"), ev.get("indoor")
            if m.get("level") != "q":
                m["level"] = ev.get("level") or m.get("level")
        ms = [m for m in by_ev.get(eid, []) if m.get("level") != "q"]
        final = [m for m in ms if m.get("round") == "F"]
        champ = next((m.get("winner") for m in final if m.get("status") in FINAL and m.get("winner")), None)
        ev["champion"] = champ
        if champ:
            ev["status"] = "done"
        elif any(m.get("status") in ("live",) for m in ms) or any(m.get("status") in FINAL for m in ms):
            end = ev.get("end")
            ev["status"] = "done" if end and end < (today.isoformat()) and not any(
                m.get("status") in ("live", "upcoming") for m in ms) else "live"
        else:
            ev["status"] = "upcoming"
        if not ev.get("draw") or (ev.get("draw") or {}).get("source") == "reconstructed":
            d = reconstruct_draw(ms)
            if d:
                ev["draw"] = d


def reconstruct_draw(ms: list[dict]) -> dict | None:
    """DRAW from a knockout event's matches (ATP: ESPN and tennis-data carry no bracket order).
    Each played match covers a block of first-round slots: its two players' blocks, each either
    the earlier-round match the player came through or the player alone with empty (bye or not
    yet known) slots. Blocks start from the final when it has been played, otherwise from the
    deepest matches; first-round pairings no later round links are appended. Seeds and entry
    types are unknown here (None). `complete` is true once the final links the whole bracket."""
    if any(m.get("round") == "RR" for m in ms):
        return None
    sizes = {"F": 2, "SF": 4, "QF": 8}

    def rsize(r: str | None) -> int | None:
        if not r:
            return None
        if r in sizes:
            return sizes[r]
        return int(r[1:]) if r.startswith("R") and r[1:].isdigit() else None

    ko = [m for m in ms if rsize(m.get("round")) and m.get("p1") and m.get("p2")]
    if not ko:
        return None
    top = max(rsize(m["round"]) for m in ko)
    by_round: dict[int, list[dict]] = {}
    for m in ko:
        by_round.setdefault(rsize(m["round"]), []).append(m)
    used: set[int] = set()

    def side(p: str, r: int) -> list:
        width = top // r
        if r >= top:
            return [p]
        for f in by_round.get(r * 2, []):
            if p in (f["p1"], f["p2"]) and id(f) not in used:
                return block(f)
        return [p] + [None] * (width - 1)

    def block(m: dict) -> list:
        used.add(id(m))
        r = rsize(m["round"])
        return side(m["p1"], r) + side(m["p2"], r)

    slots: list = []
    for r in sorted(by_round):
        for m in sorted(by_round[r], key=lambda x: (x.get("date") or "", x["id"])):
            if id(m) not in used:
                slots.extend(block(m))
    size_n = top
    while size_n < len(slots):
        size_n *= 2
    complete = bool(by_round.get(2)) and len(slots) == top
    return {"size": size_n, "slots": [[i + 1, p, None, None] for i, p in enumerate(slots)],
            "source": "reconstructed", "complete": complete}


def fill_from_history(s: dict, years_back: int = 3) -> int:
    """Surface, indoor flag, level and draw size of events no tennis-data/WTA record has described yet
    (this week's ESPN-only events) from the same tournament in earlier seasons. Returns events filled."""
    need = [ev for ev in s["events"].values() if ev.get("surface") is None or ev.get("indoor") is None]
    if not need:
        return 0
    past: dict[str, dict] = {}
    for y in range(int(s["year"]) - 1, int(s["year"]) - 1 - years_back, -1):
        p = store_path(s["tour"], y)
        if not p.exists():
            continue
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for ev in (old.get("events") or {}).values():
            past.setdefault(ev.get("tid"), ev)
    n = 0
    for ev in need:
        prev = past.get(ev.get("tid"))
        if not prev:
            continue
        for k in ("surface", "indoor"):
            if ev.get(k) is None and prev.get(k) is not None:
                ev[k] = prev[k]
        if not ev.get("_lv_level") and prev.get("level") and ev.get("level") in (None, "250") and ev.get("_tid_src") != "td":
            ev["level"] = prev["level"]
        n += 1
    return n


def set_players(s: dict, registry: canon.Registry) -> None:
    pids = set()
    for m in s["matches"].values():
        pids.update([m["p1"], m["p2"]])
    for row in (s.get("rankings") or {}).get("rows") or []:
        pids.add(row[1])
    s["players"] = {pid: registry.record(pid) for pid in sorted(p for p in pids if p)}


def public(s: dict) -> dict:
    """The store as written: private bookkeeping keys on events dropped."""
    out = dict(s)
    out["events"] = {k: public_event(v) for k, v in s["events"].items()}
    out.pop("_pairs", None)
    return out
