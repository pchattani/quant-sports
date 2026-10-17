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
            if str(ev.get(f"_{src}") or "") == str(sid):
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
    if new.get("date") and (not old.get("date") or (len(str(new["date"])) > len(str(old.get("date") or ""))
                                                   and _same_era(new["date"], old["date"]))):
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


# ── event roll-ups ──────────────────────────────────────────────────────────

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
