"""
The Match Charting Project (Jeff Sackmann / Tennis Abstract): shot-by-shot records of charted
professional matches, parsed into per-point records and per-player style tables.

Licence: CC BY-NC-SA 4.0 - "Crowdsourced shot-by-shot professional tennis data by The Tennis
Abstract Match Charting Project" (https://github.com/JeffSackmann/tennis_MatchChartingProject,
http://www.tennisabstract.com/charting/meta.html). Attribution is required, use must be
non-commercial, and derived data (the style tables) is shared under the same licence. Raw files
are cached under data/tennis/charting (git-ignored) and never committed.

Files (per tour, "m" men / "w" women): charting-{m,w}-matches.csv (match_id, Player 1, Player 2,
Pl 1 hand, Pl 2 hand, Date, Tournament, Round, Time, Court, Surface, Umpire, Best of, Final TB?,
Charted by) and charting-{m,w}-points-{to-2009,2010s,2020s}.csv (match_id, Pt, Set1, Set2, Gm1,
Gm2, Pts, Gm#, TbSet, [TB?, TBpt,] Svr, [Ret, Serving,] 1st, 2nd, Notes, [... derived ...,] PtWinner).
Player 1 always served first; Svr / PtWinner are 1 or 2.

Shot-code grammar (MatchChart 0.3.2 "Instructions" sheet):
  serve      [c...] direction 4 wide / 5 body / 6 T / 0 unknown, optional "+" (serve and volley);
             fault letter n net, w wide, d deep, x wide+deep, g foot fault, e unknown, "!" shank,
             or "V" (time violation); "*" ace, "#" unreturnable.
  shots      letter f b (groundstrokes) r s (slices) v z (volleys) o p (overheads) u y (drop shots)
             l m (lobs) h i (half-volleys) j k (swinging volleys) t (trick) q (unknown), then
             optional "+" approach, "-" at net, "=" at baseline, ";" net cord, "^" stop volley,
             a direction 1/2/3 (0 unknown), on the return a depth 7/8/9 (0 unknown), and at the end
             an error type n w d x ! e followed by "#" forced / "@" unforced, or "*" winner,
             or "C" (play stopped for a wrong challenge).
  whole point "S" server won, "R" returner won, "P" penalty against the server, "Q" against the returner.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Iterator

from .. import canon
from ._client import Client

logger = logging.getLogger(__name__)

RAW = "https://raw.githubusercontent.com/JeffSackmann/tennis_MatchChartingProject/master"
REPO = "https://github.com/JeffSackmann/tennis_MatchChartingProject"
LICENSE = {
    "name": "CC BY-NC-SA 4.0",
    "url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "attribution": "Crowdsourced shot-by-shot professional tennis data by The Tennis Abstract Match Charting Project "
                   "(Jeff Sackmann and contributors), http://www.tennisabstract.com/charting/meta.html",
    "source": REPO,
    "derived": "Per-player style tables derived by The Quant Ace from the Match Charting Project's point files; "
               "shared under the same licence (CC BY-NC-SA 4.0). Non-commercial use only.",
}
GENDER = {"atp": "m", "wta": "w"}
POINT_FILES = ("to-2009", "2010s", "2020s")

FH = set("frvoulhj")
BH = set("bszpymik")
NET_SHOTS = set("vzophijk")
SHOT_LETTERS = "fbrsvzopuylmhijktq"
_SHOT = re.compile(r"([fbrsvzopuylmhijktq])([+\-=;^]*)([0-9]?)([0-9]?)([+\-=;^]*)([nwdx!e]?)([*#@]?)(C?)")
_SERVE = re.compile(r"^(c*)([0456])(\+?)([nwdxge!V]?)([*#]?)")


def cache_dir() -> Path:
    return canon.raw_root() / "charting"


def filenames(tour: str) -> list[str]:
    g = GENDER[canon.tour_key(tour)]
    return [f"charting-{g}-matches.csv"] + [f"charting-{g}-points-{x}.csv" for x in POINT_FILES]


def download(c: Client, tour: str, refresh: bool = False) -> dict[str, Path]:
    """Cached copies of a tour's matches and points files (downloaded once; `refresh` re-reads)."""
    out = {}
    d = cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name in filenames(tour):
        p = d / name
        if p.exists() and p.stat().st_size > 0 and not refresh:
            out[name] = p
            continue
        body, hdr = c.get_bytes(f"{RAW}/{name}")
        if body:
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_bytes(body)
            tmp.replace(p)
            out[name] = p
        elif p.exists():
            out[name] = p
        else:
            logger.warning("charting: %s not available", name)
    return out


# ── match list ──────────────────────────────────────────────────────────────

def read_matches(path: Path) -> dict[str, dict]:
    out = {}
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            mid = r.get("match_id")
            if not mid:
                continue
            out[mid] = {"p1": (r.get("Player 1") or "").strip(), "p2": (r.get("Player 2") or "").strip(),
                        "hand1": (r.get("Pl 1 hand") or "").strip() or None,
                        "hand2": (r.get("Pl 2 hand") or "").strip() or None,
                        "date": _date(r.get("Date")), "tournament": r.get("Tournament"), "round": r.get("Round"),
                        "surface": canon.surface_key(r.get("Surface")), "best_of": _int(r.get("Best of")),
                        "final_tb": r.get("Final TB?")}
    return out


def _date(v: Any) -> str | None:
    s = str(v or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if re.fullmatch(r"\d{8}", s) else None


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ── point codes ─────────────────────────────────────────────────────────────

def parse_shots(code: str) -> list[dict]:
    """Rally shots after the serve: [{"shot","wing","mods","dir","depth","err","end","net"}]."""
    out = []
    pos = 0
    s = code or ""
    while pos < len(s):
        m = _SHOT.match(s, pos)
        if not m or m.end() == pos:
            pos += 1                                   # skip unknown characters (lets, stray marks)
            continue
        letter, mods1, d1, d2, mods2, err, end, chal = m.groups()
        mods = mods1 + mods2
        out.append({"shot": letter, "wing": "fh" if letter in FH else "bh" if letter in BH else None,
                    "mods": mods, "dir": int(d1) if d1 and d1 in "123" else None,
                    "depth": int(d2) if d2 and d2 in "789" else None, "err": err or None, "end": end or None,
                    "approach": "+" in mods, "net": (letter in NET_SHOTS and "=" not in mods) or "-" in mods,
                    "challenge": bool(chal)})
        pos = m.end()
    return out


def parse_serve(code: str) -> dict | None:
    """The serve at the start of a 1st/2nd code: {"dir","snv","fault","ace","unret","rest"}."""
    s = (code or "").strip()
    m = _SERVE.match(s)
    if not m:
        return None
    _, d, snv, fault, end = m.groups()
    return {"dir": {"4": "wide", "5": "body", "6": "t"}.get(d), "snv": bool(snv), "fault": fault or None,
            "ace": end == "*", "unret": end == "#", "rest": s[m.end():]}


def side_from_score(pts: str, tiebreak: bool | None = False) -> str | None:
    """Deuce or ad court from the point score before the point: "15-30" (ad), "40-40" (deuce),
    "AD-40" (ad), and in a tiebreak "3-2" (ad: an odd number of points played). With
    `tiebreak` None (the file has no TB? column) game scores are read first."""
    p = str(pts or "").strip().upper()
    if "-" not in p:
        return None
    a, b = (x.strip() for x in p.split("-", 1))
    reg = {"0": 0, "15": 1, "30": 2, "40": 3, "AD": 4, "A": 4}
    if tiebreak and a.isdigit() and b.isdigit():
        return "deuce" if (int(a) + int(b)) % 2 == 0 else "ad"
    if a in reg and b in reg:
        if reg[a] == 4 or reg[b] == 4:
            return "ad"
        return "deuce" if (reg[a] + reg[b]) % 2 == 0 else "ad"
    if a.isdigit() and b.isdigit():
        return "deuce" if (int(a) + int(b)) % 2 == 0 else "ad"
    return None


def parse_point(first: str, second: str, server: int, pt_winner: int | None = None, pts: str = "",
                tiebreak: bool | None = False) -> dict:
    """One point -> record. `server` and `pt_winner` are 1/2 (Player 1 served first)."""
    first, second = (first or "").strip(), (second or "").strip()
    ret = 3 - server
    rec: dict[str, Any] = {"server": server, "side": side_from_score(pts, tiebreak), "serve_no": 1, "serve_dir": None,
                           "snv": False, "first_in": None, "ace": False, "unret": False, "df": False,
                           "rally_len": None, "outcome": None, "ender": None, "ender_shot": None, "ender_wing": None,
                           "winner": pt_winner, "shots": [], "return_depth": None, "return_wing": None,
                           "net": {1: False, 2: False}, "first_dir": None, "first_fault": None, "special": None}
    if first[:1] in ("S", "R", "P", "Q") and len(first) <= 2:
        rec["special"] = first[:1]
        rec["winner"] = pt_winner or (server if first[:1] in ("S", "Q") else ret)
        return rec
    sv = parse_serve(first)
    code = first
    if sv and sv["fault"] and second:
        rec["first_in"] = False
        rec["first_dir"], rec["first_fault"] = sv["dir"], sv["fault"]
        rec["serve_no"] = 2
        code = second
        if second[:1] in ("S", "R", "P", "Q") and len(second) <= 2:
            rec["special"] = second[:1]
            rec["winner"] = pt_winner or (server if second[:1] in ("S", "Q") else ret)
            return rec
        sv = parse_serve(second)
    elif sv:
        rec["first_in"] = not sv["fault"]
        rec["first_dir"] = sv["dir"]
    if not sv:
        rec["special"] = "unparsed"
        return rec
    rec["serve_dir"], rec["snv"] = sv["dir"], sv["snv"]
    if sv["snv"]:
        rec["net"][server] = True
    if sv["fault"]:                                   # double fault (or a fault with no 2nd recorded)
        rec["df"] = rec["serve_no"] == 2 or not second
        rec["outcome"], rec["ender"], rec["rally_len"] = "df", server, 0
        rec["winner"] = pt_winner or ret
        return rec
    if sv["ace"]:
        rec.update(ace=True, unret=True, outcome="ace", ender=server, rally_len=1)
        rec["winner"] = pt_winner or server
        return rec
    if sv["unret"]:
        rec.update(unret=True, outcome="unreturnable", ender=server, rally_len=1)
        rec["winner"] = pt_winner or server
        return rec
    shots = parse_shots(sv["rest"])
    hitters = []
    for k, sh in enumerate(shots):
        who = ret if k % 2 == 0 else server
        sh["by"] = who
        hitters.append(who)
        if sh["approach"] or sh["net"]:
            rec["net"][who] = True
    rec["shots"] = shots
    if shots:
        r0 = shots[0]
        rec["return_depth"] = r0["depth"]
        rec["return_wing"] = r0["wing"]
        last = shots[-1]
        rec["ender"], rec["ender_shot"], rec["ender_wing"] = last["by"], last["shot"], last["wing"]
        if last["end"] == "*":
            rec["outcome"] = "winner"
            win = last["by"]
        elif last["end"] == "#":
            rec["outcome"] = "forced"
            win = 3 - last["by"]
        elif last["end"] == "@":
            rec["outcome"] = "unforced"
            win = 3 - last["by"]
        else:
            rec["outcome"] = "challenge" if last.get("challenge") else "unknown"
            win = None
        errored = last["end"] in ("#", "@")
        rec["rally_len"] = 1 + len(shots) - (1 if errored else 0)
        if len(shots) == 1 and errored:
            rec["unret"] = True                         # a return error: the serve was not returned in play
        rec["winner"] = pt_winner or win
    else:
        rec["outcome"], rec["rally_len"] = "unknown", 1
    return rec


# ── points files ────────────────────────────────────────────────────────────

def iter_points(path: Path) -> Iterator[dict]:
    """Rows of a points file as dicts with the columns this module uses."""
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd, None)
        if not header:
            return
        ix = {h: i for i, h in enumerate(header)}
        need = ("match_id", "Svr", "1st", "2nd", "PtWinner")
        if any(k not in ix for k in need):
            logger.warning("charting %s: unexpected header %s", path.name, header[:20])
            return
        i_tb = ix.get("TB?")
        for row in rd:
            if len(row) < len(header) - 2:
                continue
            g = lambda k: row[ix[k]] if k in ix and ix[k] < len(row) else ""   # noqa: E731
            yield {"match_id": g("match_id"), "pt": g("Pt"), "svr": g("Svr"), "first": g("1st"), "second": g("2nd"),
                   "winner": g("PtWinner"), "pts": g("Pts"), "tb": (row[i_tb] if i_tb is not None and i_tb < len(row) else ""),
                   "gm1": g("Gm1"), "gm2": g("Gm2")}


def _is_tb(row: dict) -> bool | None:
    v = str(row.get("tb") or "").strip().lower()
    if v in ("1", "true"):
        return True
    if v in ("0", "false"):
        return False
    return None


# ── style tables ────────────────────────────────────────────────────────────

RALLY_BUCKETS = ((1, 3), (4, 6), (7, 9), (10, 999))


class StyleAcc:
    """Accumulates one player's counting stats over charted points."""

    def __init__(self) -> None:
        self.c: dict[str, float] = {}
        self.matches: set[str] = set()

    def add(self, k: str, v: float = 1) -> None:
        self.c[k] = self.c.get(k, 0) + v

    def get(self, k: str) -> float:
        return self.c.get(k, 0)


def accumulate(acc: dict[str, StyleAcc], match_id: str, names: tuple[str, str], rec: dict) -> None:
    if rec.get("special") == "unparsed":
        return
    s, r = rec["server"], 3 - rec["server"]
    for who in (1, 2):
        a = acc.setdefault(names[who - 1], StyleAcc())
        a.matches.add(match_id)
        won = rec.get("winner") == who
        a.add("points")
        a.add("won", won)
        if rec.get("special"):
            continue
        rl = rec.get("rally_len")
        if rl is not None and rl >= 1:
            for lo, hi in RALLY_BUCKETS:
                if lo <= rl <= hi:
                    a.add(f"rl_{lo}")
                    a.add(f"rlw_{lo}", won)
            a.add("rally_sum", rl)
            a.add("rally_n")
        if rec["net"].get(who):
            a.add("net_pts")
            a.add("net_won", won)
        hits = [sh for sh in rec.get("shots") or [] if sh.get("by") == who]
        for sh in hits:
            a.add("shots")
            if sh["shot"] in "fb":
                a.add("gs")
                a.add("gs_fh", sh["shot"] == "f")
        if rec.get("ender") == who and rec.get("outcome") in ("winner", "unforced", "forced"):
            wing = rec.get("ender_wing") or "other"
            if rec["outcome"] == "winner":
                a.add("winners")
                a.add(f"w_{wing}")
            elif rec["outcome"] == "unforced":
                a.add("ue")
                a.add(f"ue_{wing}")
            else:
                a.add("fe")
        if rec.get("ender") == 3 - who and rec.get("outcome") == "forced":
            a.add("induced_fe")
    sv = acc[names[s - 1]]
    rt = acc[names[r - 1]]
    if rec.get("special"):
        return
    sv.add("sv_pts")
    sv.add("sv_won", rec.get("winner") == s)
    rt.add("rt_pts")
    rt.add("rt_won", rec.get("winner") == r)
    if rec.get("first_in") is not None or rec.get("serve_no") == 2:
        sv.add("first_att")
        sv.add("first_in", rec.get("serve_no") == 1 and not rec.get("df") and rec.get("first_in") is not False)
    if rec.get("serve_no") == 1:
        sv.add("first_pts")
        sv.add("first_won", rec.get("winner") == s)
    else:
        sv.add("second_pts")
        sv.add("second_won", rec.get("winner") == s)
    sv.add("aces", rec.get("ace"))
    sv.add("dfs", rec.get("df"))
    sv.add("unret", rec.get("unret") and not rec.get("df"))
    sv.add("snv", rec.get("snv"))
    side = rec.get("side")
    for no, d in ((1, rec.get("first_dir")), (2, rec.get("serve_dir") if rec.get("serve_no") == 2 else None)):
        if d and side:
            sv.add(f"dir{no}_{side}_{d}")
            sv.add(f"dir{no}_{side}_n")
    if rec.get("return_depth"):
        rt.add("ret_depth_n")
        rt.add(f"ret_depth_{rec['return_depth']}")
    if rec.get("return_wing"):
        rt.add("ret_in_n")
        rt.add("ret_fh", rec["return_wing"] == "fh")


def _r(x: float, y: float, nd: int = 4) -> float | None:
    return round(x / y, nd) if y else None


def summarize(a: StyleAcc) -> dict:
    g = a.get
    pts = g("points")
    out: dict[str, Any] = {"matches": len(a.matches), "points": int(pts), "sv_pts": int(g("sv_pts")), "rt_pts": int(g("rt_pts")),
                           "points_won": _r(g("won"), pts)}
    out["serve"] = {
        "first_in": _r(g("first_in"), g("first_att")), "first_won": _r(g("first_won"), g("first_pts")),
        "second_won": _r(g("second_won"), g("second_pts")), "ace_rate": _r(g("aces"), g("sv_pts")),
        "df_rate": _r(g("dfs"), g("sv_pts")), "unret_rate": _r(g("unret"), g("sv_pts")),
        "snv_rate": _r(g("snv"), g("sv_pts")), "won": _r(g("sv_won"), g("sv_pts")),
        "direction": {f"{'first' if no == 1 else 'second'}_{side}": (
            {d: _r(g(f"dir{no}_{side}_{d}"), g(f"dir{no}_{side}_n")) for d in ("wide", "body", "t")}
            | {"n": int(g(f"dir{no}_{side}_n"))}) for no in (1, 2) for side in ("deuce", "ad")},
    }
    out["return"] = {"won": _r(g("rt_won"), g("rt_pts")),
                     "depth": {"shallow": _r(g("ret_depth_7"), g("ret_depth_n")), "mid": _r(g("ret_depth_8"), g("ret_depth_n")),
                               "deep": _r(g("ret_depth_9"), g("ret_depth_n")), "n": int(g("ret_depth_n"))},
                     "fh_share": _r(g("ret_fh"), g("ret_in_n"))}
    rn = g("rally_n")
    out["rally"] = {"mean_len": _r(g("rally_sum"), rn, 2),
                    "dist": {f"{lo}-{hi if hi < 999 else ''}".rstrip("-") + ("+" if hi >= 999 else ""): _r(g(f"rl_{lo}"), rn)
                             for lo, hi in RALLY_BUCKETS},
                    "won": {f"{lo}-{hi if hi < 999 else ''}".rstrip("-") + ("+" if hi >= 999 else ""): _r(g(f"rlw_{lo}"), g(f"rl_{lo}"))
                            for lo, hi in RALLY_BUCKETS}}
    out["shots"] = {"winners_per_pt": _r(g("winners"), pts), "ue_per_pt": _r(g("ue"), pts),
                    "fh_winners_per_pt": _r(g("w_fh"), pts), "bh_winners_per_pt": _r(g("w_bh"), pts),
                    "fh_ue_per_pt": _r(g("ue_fh"), pts), "bh_ue_per_pt": _r(g("ue_bh"), pts),
                    "induced_fe_per_pt": _r(g("induced_fe"), pts), "fh_share": _r(g("gs_fh"), g("gs")),
                    "winner_ue_ratio": _r(g("winners"), g("ue"), 3)}
    out["net"] = {"rate": _r(g("net_pts"), pts), "won": _r(g("net_won"), g("net_pts")), "n": int(g("net_pts"))}
    # aggression: share of the player's shots that end the point by their own hand (winner or unforced error)
    out["aggression"] = _r(g("winners") + g("ue"), g("shots"))
    return out


def build_style(tour: str, paths: dict[str, Path], resolve=None, min_points: int = 0) -> tuple[dict, dict]:
    """(style table keyed by pid (or charting name without `resolve`), info). `resolve(name, hand)`
    maps a charting name to a pid."""
    tour = canon.tour_key(tour)
    names = filenames(tour)
    matches = read_matches(paths[names[0]]) if names[0] in paths else {}
    acc: dict[str, StyleAcc] = {}
    info = {"matches_file": len(matches), "points": 0, "unparsed": 0, "matches_with_points": set(), "dates": [None, None],
            "files": {}}
    for name in names[1:]:
        p = paths.get(name)
        if not p:
            continue
        n = 0
        for row in iter_points(p):
            m = matches.get(row["match_id"])
            if not m:
                continue
            try:
                svr = int(row["svr"])
            except ValueError:
                continue
            try:
                pw = int(row["winner"])
            except ValueError:
                pw = None
            rec = parse_point(row["first"], row["second"], svr, pw, row["pts"], _is_tb(row))
            if rec.get("special") == "unparsed":
                info["unparsed"] += 1
            accumulate(acc, row["match_id"], (m["p1"], m["p2"]), rec)
            info["matches_with_points"].add(row["match_id"])
            n += 1
        info["files"][name] = n
        info["points"] += n
    dates = sorted(m["date"] for k, m in matches.items() if m.get("date") and k in info["matches_with_points"])
    info["dates"] = [dates[0], dates[-1]] if dates else [None, None]
    info["matches_with_points"] = len(info["matches_with_points"])
    hands = {}
    for m in matches.values():
        hands.setdefault(m["p1"], m.get("hand1"))
        hands.setdefault(m["p2"], m.get("hand2"))
    out: dict[str, dict] = {}
    unresolved = []
    for name, a in acc.items():
        if a.get("points") < min_points:
            continue
        pid = resolve(name, hands.get(name)) if resolve else name
        if not pid:
            unresolved.append(name)
            continue
        row = summarize(a)
        row["name"] = name
        row["hand"] = hands.get(name)
        if pid in out:                                 # two charting spellings of one player: keep the larger
            if out[pid]["points"] >= row["points"]:
                continue
        out[pid] = row
    info["players"] = len(out)
    info["unresolved"] = unresolved
    return out, info
