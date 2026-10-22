"""
The official WTA API (api.wtatennis.com, no key): calendar, draws, matches with set scores,
per-match serve/return stats (per set too) and the live ranking.

  /tennis/tournaments/?from=YYYY-MM-DD&to=YYYY-MM-DD&pageSize=100&page=N   calendar (ITF included;
        dropped here). Each entry: tournamentGroup {id, name, level}, year, title, startDate,
        endDate, surface, inOutdoor "I"/"O", city, country, singlesDrawSize, level, status.
  /tennis/tournaments/{gid}/{year}/matches          every match: DrawMatchType "S"/"D",
        DrawLevelType "M" (main) / "Q" (qualifying), MatchID "LS001" (main singles; 1 = final,
        2-3 semis, 4-7 quarters, 8-15, 16-31 ... so the number gives round AND bracket position),
        PlayerIDA/B, names, countries, SeedA/B, EntryTypeA/B (Q, Wc, Ll, PR ...), ScoreSet{n}A/B,
        ScoreTbSet{n} (the tiebreak loser's points), MatchState F/P/U, Winner "2" A won, "3" B won,
        "4"/"5" A/B won by retirement, "6"/"7" A/B won by walkover ("0" while live), PointA/B and
        Serve "A"/"B" while live, MatchTimeTotal "hh:mm:ss".
  /tennis/tournaments/{gid}/{year}/matches/{MatchID}/stats   list of rows, setnum 0 = match totals:
        acesa/b, dblflta/b, ptswon1stserva/b, ptsplayed1stserva/b (first serves in),
        ptstotwonserva/b, totservplayeda/b, breakptsconva/b, breakptsplayeda/b (opportunities
        as returner), servgamesplayeda/b, totptswona/b ...
  /tennis/tournaments/{gid}/{year}/draw              drawInfo: JSON strings with Draws.Events.Event
        (EventTypeCode "LS" main singles, "QS" qualifying) and DrawLine rows (Pos, Seed, EntryType,
        Players.Player.id, Bye rows with id 0).
  /tennis/players/ranked?type=rankSingles&metric=SINGLES&page=N&pageSize=100   the ranking.

Depth measured on 1 Oct 2026: tournament match lists exist from 2016 (2015 and earlier answer
empty; some events have gaps, e.g. Miami 2018); the stats endpoint answers for those matches.
Grand Slams are not served (they are ITF events) - their women's matches come from ESPN and
tennis-data only.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .. import canon
from ._client import Client

logger = logging.getLogger(__name__)

API = "https://api.wtatennis.com/tennis"
STATS_FROM = 2016
WINNER = {"2": ("a", "done"), "3": ("b", "done"), "4": ("a", "ret"), "5": ("b", "ret"), "6": ("a", "wo"),
          "7": ("b", "wo"), "8": ("a", "def"), "9": ("b", "def")}


def client(budget: int = 2000, interval: float = 0.5) -> Client:
    return Client(budget=budget, interval=interval, name="wta", headers={"Referer": "https://www.wtatennis.com/"})


# ── fetchers ────────────────────────────────────────────────────────────────

def calendar(c: Client, frm: str, to: str, include_itf: bool = False) -> list[dict]:
    out: list[dict] = []
    page = 0
    while True:
        d = c.get(f"{API}/tournaments/", {"from": frm, "to": to, "pageSize": 100, "page": page})
        if not isinstance(d, dict):
            break
        rows = d.get("content") or []
        out.extend(rows)
        info = d.get("pageInfo") or {}
        total = int(info.get("numEntries") or 0)
        page += 1
        if not rows or len(out) >= total or page > 20:
            break
    if not include_itf:
        out = [t for t in out if canon.level_from_wta(t.get("level"), (t.get("tournamentGroup") or {}).get("level"),
                                                         t.get("title")) is not None]
    return out


def cache_dir(year: int, gid: Any) -> Path:
    return canon.raw_root() / "wta" / str(int(year)) / str(gid)


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(p: Path, obj: Any) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def matches(c: Client, gid: Any, year: int, use_cache: bool = False) -> dict | None:
    """A tournament's matches. Answers are cached raw under data/tennis/wta/<year>/<gid>/ (git-ignored);
    `use_cache` reads a finished tournament from there instead of calling."""
    p = cache_dir(year, gid) / "matches.json"
    if use_cache:
        d = _read(p)
        if isinstance(d, dict):
            return d
    d = c.get(f"{API}/tournaments/{gid}/{int(year)}/matches")
    if isinstance(d, dict):
        _write(p, d)
        return d
    return None


def stats(c: Client, gid: Any, year: int, match_id: str) -> list | None:
    """One finished match's stats; cached raw (a finished match's stats do not change)."""
    p = cache_dir(year, gid) / "stats" / f"{match_id}.json"
    d = _read(p)
    if isinstance(d, list):
        return d
    d = c.get(f"{API}/tournaments/{gid}/{int(year)}/matches/{match_id}/stats")
    if isinstance(d, list):
        _write(p, d)
        return d
    return None


def draw_raw(c: Client, gid: Any, year: int) -> dict | None:
    d = c.get(f"{API}/tournaments/{gid}/{int(year)}/draw")
    return d if isinstance(d, dict) else None


def rankings(c: Client, max_rows: int = 1000) -> dict | None:
    rows: list = []
    page = 0
    date = None
    while len(rows) < max_rows:
        d = c.get(f"{API}/players/ranked", {"type": "rankSingles", "metric": "SINGLES", "page": page, "pageSize": 100})
        if not isinstance(d, list) or not d:
            break
        for x in d:
            p = x.get("player") or {}
            if not p.get("id"):
                continue
            date = date or str(x.get("rankedAt") or "")[:10] or None
            side = {"name": p.get("fullName"), "first": p.get("firstName"), "last": p.get("lastName"),
                    "wta": str(p["id"]), "country": p.get("countryCode"), "dob": p.get("dateOfBirth")}
            rows.append([x.get("ranking"), side, x.get("points")])
        page += 1
        if len(d) < 100:
            break
    return {"date": date, "rows": rows, "source": "wta"} if rows else None


# ── parsing ─────────────────────────────────────────────────────────────────

def tournament_meta(t: dict) -> dict:
    """A calendar entry (or the `tournament` block of a matches answer) -> event meta."""
    grp = t.get("tournamentGroup") or {}
    level = canon.level_from_wta(t.get("level"), grp.get("level"), t.get("title"))
    title = str(t.get("title") or "")
    name = title.rsplit(" - ", 1)[0].strip() if " - " in title else title
    city = (t.get("city") or "").title() or None
    if not city and " - " in title:
        city = title.rsplit(" - ", 1)[1].split(",")[0].strip().title() or None
    return {"name": name or grp.get("name"), "city": city, "country": t.get("country"),
            "start": t.get("startDate"), "end": t.get("endDate"), "level": level, "series": t.get("level"),
            "surface": canon.surface_key(t.get("surface")), "indoor": str(t.get("inOutdoor") or "").upper() == "I",
            "draw_size": int(t["singlesDrawSize"]) if str(t.get("singlesDrawSize") or "").isdigit() else None,
            "td": None, "espn": None, "wta": str(grp.get("id") or "") or None,
            "tid_hint": canon.tid_for("wta", name, city, level), "status": t.get("status")}


def _int(v: Any) -> int | None:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def round_from_match_id(match_id: str) -> tuple[str | None, int | None]:
    """("R32", position) from a main-draw singles MatchID: LS001 = F, LS002-3 = SF, LS004-7 = QF,
    LS008-15 = R16 ... ; position = 0-based index within the round, in bracket order."""
    m = re.fullmatch(r"LS(\d+)", str(match_id or "").upper())
    if not m:
        return None, None
    n = int(m.group(1))
    if n < 1 or n >= 256:                     # Slams use long ids ("LS67664708"): no bracket position
        return None, None
    k = n.bit_length() - 1                      # 1 -> 0 (F), 2..3 -> 1 (SF), 4..7 -> 2 (QF) ...
    size = 2 ** (k + 1)
    lab = {2: "F", 4: "SF", 8: "QF"}.get(size, f"R{size}")
    return lab, n - 2 ** k


def parse_matches(raw: dict | None, meta: dict | None = None, year: int | None = None) -> list[dict]:
    """Singles source match records (canon.SMR_DOC) from a tournament's matches answer."""
    if not raw:
        return []
    meta = dict(meta or tournament_meta(raw.get("tournament") or {}))
    if meta.get("level") is None:
        return []
    out = []
    for m in raw.get("matches") or []:
        if str(m.get("DrawMatchType") or "").upper() != "S":
            continue
        rec = parse_match(m, meta, year)
        if rec:
            out.append(rec)
    return out


def _side(m: dict, s: str) -> dict | None:
    pid = str(m.get(f"PlayerID{s}") or "").strip()
    first, last = (m.get(f"PlayerNameFirst{s}") or "").strip(), (m.get(f"PlayerNameLast{s}") or "").strip()
    if not pid or pid == "0" or not last:
        return None
    if pid.upper().startswith("EX"):
        return None             # "EXW..." ids: exhibition entries the API lists inside a draw (men at Rovereto 2026)
    entry = (m.get(f"EntryType{s}") or "").strip().upper() or None
    return {"name": f"{first} {last}".strip(), "first": first, "last": last, "wta": pid,
            "country": m.get(f"PlayerCountry{s}") or None, "seed": _int(m.get(f"Seed{s}")),
            "entry": {"WC": "WC", "Q": "Q", "LL": "LL", "PR": "PR", "SE": "SE", "ALT": "ALT"}.get(entry, entry)}


def parse_match(m: dict, meta: dict, year: int | None = None) -> dict | None:
    a, b = _side(m, "A"), _side(m, "B")
    if not a or not b:
        return None
    lvl = str(m.get("DrawLevelType") or "").upper()
    if lvl == "M":
        rnd, pos = round_from_match_id(m.get("MatchID"))
        if rnd is None:
            rnd = canon.wta_round_label(m.get("RoundID"), lvl, meta.get("draw_size"))
    else:
        rnd, pos = canon.wta_round_label(m.get("RoundID"), lvl, meta.get("draw_size")), None
    if rnd is None:                           # Slam qualifying rows carry no round: ESPN has them
        return None
    state = str(m.get("MatchState") or "").upper()
    code = str(m.get("Winner") or "")
    winner, status = WINNER.get(code, (None, None))
    if state == "P":
        status, winner = "live", None
    elif state == "U" or (status is None and state != "F"):
        status, winner = "upcoming", None
    elif status is None:
        status = "done"
    sets = []
    for i in range(1, 6):
        ga, gb = _int(m.get(f"ScoreSet{i}A")), _int(m.get(f"ScoreSet{i}B"))
        if ga is None and gb is None:
            continue
        tb_lo = _int(m.get(f"ScoreTbSet{i}"))
        ta = tbb = None
        if tb_lo is not None and ga is not None and gb is not None and abs(ga - gb) == 1 and max(ga, gb) >= 7:
            tb_hi = max(7, tb_lo + 2)
            ta, tbb = (tb_hi, tb_lo) if ga > gb else (tb_lo, tb_hi)
        sets.append([ga or 0, gb or 0, ta, tbb])
    live = None
    if status == "live":
        cur = sets[-1] if sets else [0, 0, None, None]
        done = len(sets) and _set_complete(cur[0], cur[1])
        pts = [m.get("PointA"), m.get("PointB")]
        serve = str(m.get("Serve") or "").upper()
        live = {"set": len(sets) + (1 if done else 0), "games": [0, 0] if done else cur[:2],
                "points": pts if any(p not in (None, "") for p in pts) else None,
                "server": "a" if serve == "A" else "b" if serve == "B" else None}
        if not done and sets:
            sets = sets[:-1]
    if status in ("upcoming", "wo"):
        sets = []
    dur = None
    t = str(m.get("MatchTimeTotal") or "")
    mm = re.fullmatch(r"(\d+):(\d\d):(\d\d)", t)
    if mm and status in ("done", "ret", "def"):
        dur = int(mm.group(1)) * 60 + int(mm.group(2)) + (1 if int(mm.group(3)) >= 30 else 0)
        dur = dur or None
    y = int(year or m.get("EventYear") or (meta.get("start") or "0000")[:4])
    level = meta.get("level")
    return {"src": "wta", "tour": "wta", "year": y, "event": meta, "round": rnd, "round_raw": m.get("RoundID"),
            "date": str(m.get("MatchTimeStamp") or "")[:16] or None,
            "best_of": canon.best_of("wta", level, rnd), "a": a, "b": b, "winner": winner, "status": status,
            "sets": sets, "odds": None, "stats": None, "live": live, "duration_min": dur,
            "src_id": str(m.get("MatchID") or ""), "bracket_pos": pos, "draw_level": lvl,
            "match_id": m.get("MatchID")}


def _set_complete(ga: int, gb: int) -> bool:
    hi, lo = max(ga, gb), min(ga, gb)
    return (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo == 6)


STATS_KEYS = ("aces", "dfs", "sv_pts", "fs_in", "fs_won", "ss_won", "sv_gms", "bp_saved", "bp_faced", "rt_pts_won",
              "bp_conv", "bp_opps")


def _stat_side(row: dict, me: str, opp: str) -> dict:
    g = lambda k: _int(row.get(k))                                    # noqa: E731
    sv_pts, fs_in, fs_won = g(f"totservplayed{me}"), g(f"ptsplayed1stserv{me}"), g(f"ptswon1stserv{me}")
    sv_won = g(f"ptstotwonserv{me}")
    opp_sv, opp_sv_won = g(f"totservplayed{opp}"), g(f"ptstotwonserv{opp}")
    bp_faced, bp_lost = g(f"breakptsplayed{opp}"), g(f"breakptsconv{opp}")
    return {"aces": g(f"aces{me}"), "dfs": g(f"dblflt{me}"), "sv_pts": sv_pts, "fs_in": fs_in, "fs_won": fs_won,
            "ss_won": (sv_won - fs_won) if sv_won is not None and fs_won is not None else None,
            "sv_gms": g(f"servgamesplayed{me}"),
            "bp_saved": (bp_faced - bp_lost) if bp_faced is not None and bp_lost is not None else None,
            "bp_faced": bp_faced,
            "rt_pts_won": (opp_sv - opp_sv_won) if opp_sv is not None and opp_sv_won is not None else None,
            "bp_conv": g(f"breakptsconv{me}"), "bp_opps": g(f"breakptsplayed{me}")}


def parse_stats(rows: list | None) -> dict | None:
    """{"a": STATS, "b": STATS, "by_set": [{"set", "a", "b"}]} in the matches answer's A/B order."""
    if not rows:
        return None
    tot = next((r for r in rows if _int(r.get("setnum")) == 0), None)
    if tot is None:
        return None
    a, b = _stat_side(tot, "a", "b"), _stat_side(tot, "b", "a")
    if not a.get("sv_pts") and not b.get("sv_pts"):
        return None
    by_set = []
    for r in sorted((r for r in rows if (_int(r.get("setnum")) or 0) > 0), key=lambda r: _int(r.get("setnum"))):
        by_set.append({"set": _int(r.get("setnum")), "a": _stat_side(r, "a", "b"), "b": _stat_side(r, "b", "a")})
    return {"a": a, "b": b, "by_set": by_set}


def parse_draw(raw: dict | None, code: str = "LS") -> dict | None:
    """DRAW {"size", "slots": [[slot, wta_id|None, seed|None, entry|None]]} (WTA ids; tn_fetch maps
    them to pids) from the draw answer; slot is 1-based bracket position, byes are None. Also "names":
    {wta_id: "First Surname"} so a player the registry has not linked to her WTA id yet (a seed with a bye
    who has not played) can be resolved by name."""
    if not raw:
        return None
    for s in raw.get("drawInfo") or []:
        try:
            d = json.loads(s) if isinstance(s, str) else s
        except ValueError:
            continue
        evs = (((d or {}).get("Draws") or {}).get("Events") or {}).get("Event") or []
        if isinstance(evs, dict):
            evs = [evs]
        for ev in evs:
            if str(ev.get("EventTypeCode") or "").upper() != code:
                continue
            lines = ((ev.get("Draw") or {}).get("DrawLine")) or []
            if isinstance(lines, dict):
                lines = [lines]
            slots = []
            names: dict[str, str] = {}
            for ln in lines:
                pos = _int(ln.get("Pos"))
                pl = ((ln.get("Players") or {}).get("Player")) or {}
                if isinstance(pl, list):
                    pl = pl[0] if pl else {}
                pid = str(pl.get("id") or "")
                if pid and pid != "0":
                    nm = " ".join(x for x in (str(pl.get("FirstName") or "").strip(), str(pl.get("SurName") or "").strip()) if x)
                    if nm:
                        names[pid] = nm
                entry = str(ln.get("EntryType") or "").strip().upper() or None
                slots.append([pos, pid if pid and pid != "0" else None, _int(ln.get("Seed")),
                              {"WC": "WC", "Q": "Q", "LL": "LL", "PR": "PR"}.get(entry, entry)])
            if slots:
                slots.sort(key=lambda x: x[0] or 0)
                size = 1
                while size < len(slots):
                    size *= 2
                return {"size": size, "slots": slots, "names": names}
    return None
