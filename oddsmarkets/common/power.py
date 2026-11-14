"""Power rankings: one uniform file per league on every site, teams (or players) ranked by our rating, how they got
there week by week, and the best and worst players at every position with their numbers.

    docs/<site>/data/power/<league>.json   the league's power rankings (DOC below)
    docs/<site>/data/power.json            the site's index (INDEX below): its leagues, the default one and each
                                           league's top three; Home's "No. 1 in every sport" strip reads only this

The kit's power.js (QKR, docs/_design/power.js) draws both: the site's Power page (#/power) and Home's power section
(the strip, the bump chart of the climb and the position spectrum). Each site's builder calls its own adapter
(oddsmarkets/<sport>/.../power_build.py) after its payloads are written; the adapter reads those payloads from disk,
as the follow cards do, so it fetches nothing.

DOC (schema 1):
    {"schema": 1, "site", "sport", "league", "label", "season", "season_label", "updated_at", "asof", "phase",
     "kind": "teams" | "players",        what the main ranking ranks (tennis, golf and powerlifting rank players)
     "noun": "teams",                    plural noun for the ranked entities
     "rating": {"label", "short", "unit", "fmt", "tip"},
     "step": "week",                     what one snapshot step is ("since last week", "since the last race")
     "snapshots": [{"key", "label", "date"}],    oldest first; the last one is now
     "parts": [{"key", "label"}],        optional pieces of the rating (offence, defence ...), [] without
     "teams": [TEAM],                    best first
     "players": {"noun", "groups": [GROUP]} | None,
     "notes": [str]}                     method lines for the foot of the page

    TEAM = {"id", "name", "short", "abbr", "colour", "href" (a site route, "#/team/KC"), "group" (division ...),
            "rank", "prev" (the rank at the previous snapshot; None when unranked then), "move" (prev - rank),
            "rating", "delta" (the rating's change since the previous snapshot), "path" [rank at each snapshot],
            "rpath" [rating at each snapshot], "record", "form" (oldest first, W/D/L/T/O), "streak",
            "parts" {key: value}, "chance" {"label", "p"}, "stats" [{"label", "text"}], "note" (one line)}
    GROUP = {"key", "label", "short", "metric": {"key", "label", "unit", "fmt", "dir", "tip"},
             "stats": [{"key", "label", "fmt", "unit"}], "n" (qualified with a value), "min" (the qualifying rule),
             "dist" [every qualified value, sorted worst to best; evenly spaced quantiles past DIST_MAX],
             "sampled" (True when dist is quantiles), "top" [PLAYER] (best first), "bottom" [PLAYER] (the very
             bottom last; never repeats a top row)}
    PLAYER = {"id", "name", "team" (abbr), "colour", "href", "value", "pct" (0-100, 100 the best in the group),
              "rank", "stats" [values aligned to GROUP.stats]}

    fmt codes (QKR.fmt): "0", "1", "2", "3" decimals; "+1", "+2" signed; "pct0", "pct1" a 0-1 share as a percentage

INDEX:
    {"schema": 1, "site", "sport", "updated_at", "default": "<league>",
     "leagues": [{"league", "label", "file": "power/<league>.json", "phase", "season", "season_label", "kind", "noun",
                  "asof", "snapshot" (the latest snapshot's label), "rating": {"label", "unit", "fmt"},
                  "top": [{"id", "name", "short", "abbr", "colour", "href", "rank", "move", "rating", "weeks" (snapshots
                  in a row at No. 1, counted back from now), "record"}] (3)}]}

No look-ahead: a snapshot's rating is the rating after the games completed before that snapshot's date, read from the
site's own rating history (each site's adapter says which entry that is); players' numbers are season to date.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

SCHEMA = 1
N_TOP = 10
N_BOTTOM = 5
DIST_MAX = 160          # a group's dot strip: every qualified player up to this, evenly spaced quantiles past it
MAX_SNAPSHOTS = 10
MAX_BYTES = 600_000     # a league file's ceiling (the biggest, football's leagues, run about 40-90 KB)
PHASES = ("preseason", "season", "postseason", "offseason")


def num(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _digits(fmt: str | None) -> int:
    """Decimal places to keep for a fmt code: one more than shown, so the page rounds and the builder does not."""
    f = str(fmt or "")
    if f in ("pct0", "pct1"):
        return 4
    f = f.lstrip("+")
    try:
        return max(0, int(f)) + 1
    except ValueError:
        return 3


def rnd(v, fmt: str | None = None):
    v = num(v)
    return None if v is None else round(v, _digits(fmt))


def _ranks(vals: dict, higher: bool = True) -> dict:
    """Competition ranks (1, 2, 2, 4) of {id: value}; ids without a value are left out."""
    xs = sorted(((v, k) for k, v in vals.items() if num(v) is not None), key=lambda t: (-t[0] if higher else t[0], str(t[1])))
    out, prev, at = {}, None, 0
    for i, (v, k) in enumerate(xs):
        if prev is None or v != prev:
            at, prev = i + 1, v
        out[k] = at
    return out


def ordinal(n) -> str:
    n = int(n)
    s = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{s}"


def _streak_words(streak) -> str | None:
    """'W5' -> 'Won 5 straight'; 'L3' -> 'Lost 3 straight'; shorter runs say nothing."""
    s = str(streak or "").strip().upper()
    if len(s) < 2 or s[0] not in "WL" or not s[1:].isdigit():
        return None
    n = int(s[1:])
    if n < 3:
        return None
    return ("Won " if s[0] == "W" else "Lost ") + f"{n} straight"


def _run_from_form(form) -> str | None:
    f = str(form or "")
    if not f:
        return None
    last, n = f[-1], 0
    for c in reversed(f):
        if c != last:
            break
        n += 1
    return f"{last}{n}" if last in "WL" else None


def note_for(t: dict, n_teams: int, parts: list[dict], part_ranks: dict, step: str, extra: list[str] | None = None) -> str:
    """One plain line on a ranked side, from what the file already holds: a new No. 1, the move, a run, the unit it
    leads or trails the league in, its headline chance. Deterministic; the two most telling clauses, joined."""
    out: list[tuple[int, str]] = []
    rk, mv = t.get("rank"), t.get("move")
    since = {"week": "this week", "race": "since the last race", "round": "since the last round", "month": "this month",
             "event": "since the last event", "test": "since the last window"}.get(step, "since the last update")
    if rk == 1 and t.get("prev") not in (None, 1):
        out.append((100, "New No. 1, up from " + ordinal(t["prev"])))
    elif rk == 1 and t.get("path") and len(t["path"]) > 1:
        wk = 0
        for r in reversed(t["path"]):
            if r != 1:
                break
            wk += 1
        if wk >= 2:
            out.append((70, f"No. 1 for {wk} {step}s running" if step in ("week", "race", "round", "month", "event") else f"No. 1 at {wk} snapshots running"))
    if isinstance(mv, int) and mv and not (rk == 1 and t.get("prev") not in (None, 1)):
        out.append((60 + min(30, 4 * abs(mv)), ("Up " if mv > 0 else "Down ") + f"{abs(mv)} place{'s' if abs(mv) != 1 else ''} {since}"))
    if t.get("prev") is None and t.get("path") and len(t["path"]) > 1 and rk is not None:
        out.append((65, "New to the rankings"))
    run = _streak_words(t.get("streak") or _run_from_form(t.get("form")))
    if run:
        out.append((55 + (10 if run.startswith("Won") and (rk or 99) <= 5 else 0), run))
    else:
        f = str(t.get("form") or "")[-5:]
        if len(f) == 5 and (f.count("W") >= 4 or f.count("L") >= 4):
            k = "W" if f.count("W") >= 4 else "L"
            out.append((50, ("Won " if k == "W" else "Lost ") + f"{f.count(k)} of the last 5"))
    if parts and part_ranks:
        best = sorted(((part_ranks[p["key"]].get(t["id"]), p["label"]) for p in parts
                       if part_ranks.get(p["key"], {}).get(t["id"]) is not None), key=lambda x: x[0])
        if best:
            r0, lab0 = best[0]
            r1, lab1 = best[-1]
            if r0 <= 3:
                out.append((50 - r0, ("Best " if r0 == 1 else ordinal(r0) + "-best ") + lab0.lower() + " in the league"))
            if r1 >= n_teams - 2 and n_teams >= 8:
                w = n_teams - r1 + 1
                out.append((45, ("Worst " if w == 1 else ordinal(w) + "-worst ") + lab1.lower()))
    ch = t.get("chance") or {}
    p = num(ch.get("p"))
    if p is not None and ch.get("label") and p >= 0.005 and (rk or 99) <= max(5, n_teams // 4):
        out.append((40, f"{ch['label']} chance {pct_text(p)}"))
    for i, x in enumerate(extra or []):
        if x:
            out.append((58 - i, x))
    out.sort(key=lambda x: -x[0])
    seen, words = set(), []
    for _s, w in out:
        k = w.split(" ")[0]
        if k in seen:
            continue
        seen.add(k)
        if words and k in ("Won", "Lost", "Up", "Down", "Best", "Worst", "New"):
            w = w[0].lower() + w[1:]
        words.append(w)
        if len(words) == 2:
            break
    return "; ".join(words) + ("." if words else "")


def pct_text(p) -> str:
    p = num(p)
    if p is None:
        return ""
    if p >= 0.995:
        return ">99%"
    if p < 0.01:
        return "<1%"
    return f"{round(p * 100)}%"


def teams_block(entities: list[dict], snapshots: list[dict], higher: bool = True, parts: list[dict] | None = None,
                step: str = "week", rating_fmt: str = "+1", extra_notes: dict | None = None) -> list[dict]:
    """Rank the entities at every snapshot and now.

    entities: [{"id", "name", ..., "rpath": [rating at each snapshot, None when it had none]}], rpath aligned with
    `snapshots` (the last entry is now). Returns the TEAM rows, best first, with rank, prev, move, delta, path, rpath
    and a note. An entity without a current rating is left out."""
    n_s = len(snapshots)
    ranks_at = []
    for i in range(n_s):
        ranks_at.append(_ranks({e["id"]: (e.get("rpath") or [None] * n_s)[i] if i < len(e.get("rpath") or []) else None
                                for e in entities}, higher))
    now = ranks_at[-1] if ranks_at else {}
    prev = ranks_at[-2] if n_s >= 2 else {}
    part_ranks = {}
    for p in parts or []:
        part_ranks[p["key"]] = _ranks({e["id"]: (e.get("parts") or {}).get(p["key"]) for e in entities}, p.get("higher", True))
    out = []
    for e in entities:
        if e["id"] not in now:
            continue
        rp = [rnd(x, rating_fmt) for x in (e.get("rpath") or [])][:n_s]
        rp += [None] * (n_s - len(rp))
        t = {k: v for k, v in e.items() if k not in ("rpath",) and v not in (None, "", [], {})}
        t["rank"] = now[e["id"]]
        t["prev"] = prev.get(e["id"]) if n_s >= 2 else None
        t["move"] = (t["prev"] - t["rank"]) if t["prev"] is not None else None
        t["rating"] = rp[-1]
        t["delta"] = rnd(rp[-1] - rp[-2], rating_fmt) if n_s >= 2 and rp[-1] is not None and rp[-2] is not None else None
        t["path"] = [ranks_at[i].get(e["id"]) for i in range(n_s)]
        t["rpath"] = rp
        if "parts" in t:
            t["parts"] = {k: rnd(v, rating_fmt) for k, v in t["parts"].items() if num(v) is not None}
        out.append(t)
    out.sort(key=lambda t: (t["rank"], str(t.get("name") or "")))
    for t in out:
        if not t.get("note"):
            t["note"] = note_for(t, len(out), parts or [], part_ranks, step, (extra_notes or {}).get(t["id"]))
    return out


def _dist(vals: list[float], fmt: str | None) -> tuple[list, bool]:
    vals = sorted(vals)
    if len(vals) <= DIST_MAX:
        return [rnd(v, fmt) for v in vals], False
    k = DIST_MAX - 1
    return [rnd(vals[round(i * (len(vals) - 1) / k)], fmt) for i in range(DIST_MAX)], True


def group(key: str, label: str, rows: list[dict], metric: dict, stats: list[dict] | None = None, short: str | None = None,
          min_text: str = "", n_top: int = N_TOP, n_bottom: int = N_BOTTOM) -> dict | None:
    """One position group: the qualified pool ranked on its headline metric, the top n_top and the bottom n_bottom.

    rows: [{"id", "name", "team", "colour", "href", "v": {metric key: value, stat key: value ...}}], qualified only.
    metric: {"key", "label", "unit", "fmt", "dir" ("higher" | "lower"), "tip"}; stats: [{"key", "label", "fmt",
    "unit"}]. None when fewer than three rows carry the metric."""
    mk, lower = metric["key"], metric.get("dir") == "lower"
    have = [r for r in rows if num((r.get("v") or {}).get(mk)) is not None]
    if len(have) < 3:
        return None
    have.sort(key=lambda r: ((num(r["v"][mk]) if lower else -num(r["v"][mk])), str(r.get("name") or "")))
    total = len(have)
    ranks, prev, at = [], None, 0
    for i, r in enumerate(have):
        v = num(r["v"][mk])
        if prev is None or v != prev:
            at, prev = i + 1, v
        ranks.append(at)
    stats = [s for s in (stats or []) if any(num((r.get("v") or {}).get(s["key"])) is not None for r in have)]

    def player(i):
        r = have[i]
        v = r.get("v") or {}
        p = {"id": str(r.get("id")), "name": r.get("name") or "", "team": r.get("team") or "", "colour": r.get("colour"),
             "href": r.get("href"), "value": rnd(v.get(mk), metric.get("fmt")),
             "pct": round(100 * (total - ranks[i]) / (total - 1)) if total > 1 else 50, "rank": ranks[i],
             "stats": [rnd(v.get(s["key"]), s.get("fmt")) for s in stats]}
        if r.get("sub"):
            p["sub"] = r["sub"]
        return {k: x for k, x in p.items() if x is not None}

    nt = min(n_top, total)
    top = [player(i) for i in range(nt)]
    bottom = [player(i) for i in range(max(nt, total - n_bottom), total)]
    dist, sampled = _dist([num(r["v"][mk]) for r in have], metric.get("fmt"))
    if lower:
        dist = list(reversed(dist))          # worst to best: for a lower-is-better metric that is high to low
    g = {"key": key, "label": label, "short": short or label,
         "metric": {k: metric[k] for k in ("key", "label", "unit", "fmt", "dir", "tip") if metric.get(k) not in (None, "")},
         "stats": [{k: s[k] for k in ("key", "label", "fmt", "unit", "tip") if s.get(k) not in (None, "")} for s in stats],
         "n": total, "min": min_text, "dist": dist, "top": top, "bottom": bottom}
    if sampled:
        g["sampled"] = True
    return g


def document(*, site: str, sport: str, league: str, label: str, season, season_label: str, updated_at: str, asof: str,
             phase: str, rating: dict, snapshots: list[dict], teams: list[dict], step: str = "week",
             kind: str = "teams", noun: str = "teams", parts: list[dict] | None = None, players: dict | None = None,
             notes: list[str] | None = None) -> dict:
    if phase not in PHASES:
        phase = "season"
    snaps = snapshots[-MAX_SNAPSHOTS:]
    cut = len(snapshots) - len(snaps)
    if cut:
        for t in teams:
            for k in ("path", "rpath"):
                if isinstance(t.get(k), list):
                    t[k] = t[k][cut:]
    return {"schema": SCHEMA, "site": site, "sport": sport, "league": league, "label": label, "season": season,
            "season_label": season_label, "updated_at": updated_at, "asof": asof, "phase": phase, "kind": kind,
            "noun": noun, "rating": rating, "step": step, "snapshots": snaps,
            "parts": [{"key": p["key"], "label": p["label"]} for p in (parts or [])], "teams": teams,
            "players": players if players and players.get("groups") else None, "notes": notes or []}


def _weeks_at_one(t: dict) -> int:
    n = 0
    for r in reversed(t.get("path") or []):
        if r != 1:
            break
        n += 1
    return n


def summary(doc: dict, file: str) -> dict:
    """A league's line in the site's index: what Home's strip shows, and where the full file is."""
    snaps = doc.get("snapshots") or []
    top = []
    for t in (doc.get("teams") or [])[:3]:
        top.append({k: v for k, v in {"id": t.get("id"), "name": t.get("name"), "short": t.get("short"), "abbr": t.get("abbr"),
                                      "colour": t.get("colour"), "href": t.get("href"), "rank": t.get("rank"),
                                      "move": t.get("move"), "prev": t.get("prev"), "rating": t.get("rating"),
                                      "weeks": _weeks_at_one(t), "record": t.get("record")}.items() if v not in (None, "")})
    r = doc.get("rating") or {}
    return {"league": doc["league"], "label": doc["label"], "file": file, "phase": doc.get("phase"),
            "season": doc.get("season"), "season_label": doc.get("season_label"), "kind": doc.get("kind"),
            "noun": doc.get("noun"), "asof": doc.get("asof"), "step": doc.get("step"),
            "snapshot": snaps[-1]["label"] if snaps else None,
            "rating": {k: r[k] for k in ("label", "short", "unit", "fmt") if r.get(k)},
            "groups": len(((doc.get("players") or {}).get("groups")) or []), "n": len(doc.get("teams") or []), "top": top}


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write(data_root: Path, docs: list[dict], *, site: str, sport: str, updated_at: str, default: str | None = None,
          prune: bool = True) -> dict:
    """Write power/<league>.json for each doc and the site's power.json index. Returns {"n", "bytes", "max", "leagues"}.
    A doc past MAX_BYTES is refused (logged by the caller through the raised error). prune drops league files no
    longer built."""
    data_root = Path(data_root)
    out_dir = data_root / "power"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines, sizes, keep = [], [], set()
    for d in docs:
        if not d or not d.get("teams"):
            continue
        text = _dump(d)
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise ValueError(f"power/{d['league']}.json is {len(text.encode('utf-8'))} bytes, past the {MAX_BYTES} ceiling")
        name = f"{d['league']}.json"
        (out_dir / name).write_text(text, encoding="utf-8")
        keep.add(name)
        sizes.append(len(text.encode("utf-8")))
        lines.append(summary(d, f"power/{name}"))
    if prune:
        for p in out_dir.glob("*.json"):
            if p.name not in keep:
                p.unlink()
    idx = {"schema": SCHEMA, "site": site, "sport": sport, "updated_at": updated_at,
           "default": default if default in {x["league"] for x in lines} else (lines[0]["league"] if lines else None),
           "leagues": lines}
    (data_root / "power.json").write_text(_dump(idx), encoding="utf-8")
    return {"n": len(lines), "bytes": sum(sizes), "max": max(sizes) if sizes else 0, "leagues": [x["league"] for x in lines]}


def read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
