"""
Retrosheet: play-by-play event files (1908-2025, more complete from the 1950s), postseason event files and
game logs (1901-2025), downloaded and parsed in Python (no Chadwick binaries).

    https://www.retrosheet.org/events/<YYYY>eve.zip    regular season (team .EVA/.EVN files, deduced .EDA/.EDN
                                                        files, rosters .ROS); listed on retrosheet.org/game.htm
    https://www.retrosheet.org/events/<YYYY>post.zip   postseason (.EVE per series: ALW1, ALD1, ALCS, WS, ...)
    https://www.retrosheet.org/gamelogs/gl<YYYY>.zip   one line per game, 161 fields
Seasons 1901-1907 have box-score files only (events/<YYYY>box.zip), so no event rows; their game logs exist.

The event-file parser turns `id / version / info / start / sub / play / data / com / radj / badj / padj /
ladj / presadj` records into one row per event (CONTRACT.md section 1, `<raw>/retro/pa/<season>.parquet`):
every plate appearance (pa=True) and every running event between them (stolen bases, caught stealing,
pickoffs, wild pitches, passed balls, balks, defensive indifference, other advances; pa=False), with the
base-out state before and after and the runs that scored, so run totals reconcile with the game logs.

Play strings: basic play [/modifiers][.advances]. Basic plays: fielded outs (63, 8, 54(1), 64(1)3, 8(B)84(2)),
K[+event], W / IW / I[+event], HP, C (interference), S/D/T/H/HR/DGR, E#, FC#, FLE#, SB#, CS#(..), POCS#(..),
PO#(..), WP, PB, BK, DI, OA, NP, 99. Advances "1-3;B-2", outs "2XH(82)", an error in the out's parentheses
negates it ("1X3(5E4)" = safe). Runners not mentioned stay, except on walks, hit batters and interference,
where forced runners move up. Extra innings from 2020 start with a runner on second (`radj` records).

Required notice (shown wherever Retrosheet data appears): NOTICE.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from .. import store as st
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

NOTICE = ('The information used here was obtained free of charge from and is copyrighted by Retrosheet. '
          'Interested parties may contact Retrosheet at "www.retrosheet.org".')
BASE = "https://www.retrosheet.org"
EVENTS_FROM = 1908
GAMELOGS_FROM = 1871
INTERVAL = 1.0

PA_EVENTS = {"out", "k", "bb", "ibb", "hbp", "int", "e", "fc", "1b", "2b", "3b", "hr"}
HIT_VALUE = {"1b": 1, "2b": 2, "3b": 3, "hr": 4}
NOT_AB = {"bb", "ibb", "hbp", "int"}


# ── downloads ───────────────────────────────────────────────────────────────

def zip_url(year: int, kind: str) -> str:
    if kind == "gamelog":
        return f"{BASE}/gamelogs/gl{year}.zip"
    return f"{BASE}/events/{year}{kind}.zip"            # kind: "eve" | "post"


def zip_path(year: int, kind: str) -> Path:
    name = f"gl{year}.zip" if kind == "gamelog" else f"{year}{kind}.zip"
    return st.cache_root() / "retro" / name


def download(c: Client | None, year: int, kind: str, refresh: bool = False) -> Path | None:
    """The cached zip for a season (downloaded once; None when Retrosheet has none for that year)."""
    p = zip_path(year, kind)
    if p.exists() and p.stat().st_size > 0 and not refresh:
        return p
    missing = p.with_name(p.name + ".missing")
    if missing.exists() and not refresh:
        return None
    if c is None:
        return None
    data = c.get_bytes(zip_url(year, kind))
    if not data or data[:2] != b"PK":
        missing.parent.mkdir(parents=True, exist_ok=True)
        missing.write_text(st.now(), encoding="utf-8")
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    return p


def read_zip(path: Path) -> dict[str, str]:
    out = {}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            out[n] = z.read(n).decode("latin-1")
    return out


# ── rosters ─────────────────────────────────────────────────────────────────

def parse_rosters(files: dict[str, str]) -> dict[str, tuple[str, str]]:
    """retro id -> (bats, throws) from every .ROS file."""
    out: dict[str, tuple[str, str]] = {}
    for name, text in files.items():
        if not name.upper().endswith(".ROS"):
            continue
        for line in text.splitlines():
            f = line.strip().split(",")
            if len(f) >= 5 and f[0]:
                out[f[0]] = (f[3].strip().upper(), f[4].strip().upper())
    return out


# ── play-string helpers ─────────────────────────────────────────────────────

def split_top(s: str, sep: str) -> list[str]:
    """Split on `sep` outside parentheses."""
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _has_error(groups: Iterable[str]) -> bool:
    """True when the error negates the out: every fielding group in the parentheses has an error.
    "1X3(5E4)" and "CS2(E2)" are safe; "1XH(82)(E3/TH)" and "1XH(E1/TH)(525)" are still outs (the error
    let the runner advance, a clean relay then put him out)."""
    fielding = [g for g in groups if re.match(r"^[0-9E]", g)]
    return bool(fielding) and all(re.search(r"E\d", g) for g in fielding)


_ADV = re.compile(r"^([B123])([-X])([123H])((?:\([^()]*\))*)")
_BASE = {"B": 0, "1": 1, "2": 2, "3": 3, "H": 4}
_HITLOC = re.compile(r"^(BG|BP|BL|BF|G|L|F|P)?(\d[0-9A-Z+\-]*)?$")


def parse_advances(adv: str) -> list[dict]:
    """'1-3;B-2;2XH(82)' -> [{"from":1,"to":3,"out":False,"err":0}, ...]"""
    out = []
    for a in split_top(adv, ";"):
        a = a.strip()
        if not a:
            continue
        m = _ADV.match(a)
        if not m:
            continue
        groups = re.findall(r"\(([^()]*)\)", m.group(4))
        is_out = m.group(2) == "X" and not _has_error(groups)
        errs = sum(len(re.findall(r"E\d", g)) for g in groups)
        out.append({"from": _BASE[m.group(1)], "to": _BASE[m.group(3)], "out": is_out, "err": errs,
                    "nr": any(g in ("NR", "NORBI") for g in groups)})
    return out


def parse_event(ev: str) -> dict:
    """A play string's parts: basic, modifiers, advances, plus the classified event."""
    ev = ev.replace("#", "").replace("!", "").replace("?", "").strip()
    main, _, adv = ev.partition(".")
    pieces = split_top(main, "/")
    basic, mods = pieces[0], [m for m in pieces[1:] if m]
    return {"basic": basic, "mods": mods, "adv": parse_advances(adv)}


def _fielded_out(basic: str) -> dict:
    """Fielded play '64(1)3' / '8(B)84(2)' / '54(1)' -> runners out, batter out?"""
    marks = re.findall(r"\(([B123])\)", basic)
    runners_out = {int(x) for x in marks if x in "123"}
    tail = re.sub(r"\([^()]*\)", "|", basic)
    batter_out = "B" in marks or not tail.endswith("|")
    first = re.match(r"(\d)", basic)
    return {"runners_out": runners_out, "batter_out": batter_out, "fielder": int(first.group(1)) if first else None}


def _running(tok: str, res: dict) -> bool:
    """Apply a running event token (SB/CS/POCS/PO/WP/PB/BK/DI/OA/E/OBS) to the classification. False if unknown."""
    if not tok:
        return True
    if tok.startswith("SB"):
        for part in split_top(tok, ";"):
            m = re.match(r"SB([23H])", part)
            if m:
                tgt = _BASE[m.group(1)]
                res["implicit"][tgt - 1] = tgt
        res["run_events"].append("sb")
        return True
    m = re.match(r"(POCS|CS)([23H])((?:\([^()]*\))*)", tok)
    if m:
        tgt = _BASE[m.group(2)]
        groups = re.findall(r"\(([^()]*)\)", m.group(3))
        if _has_error(groups):
            res["implicit"][tgt - 1] = tgt
            res["err"] += sum(len(re.findall(r"E\d", g)) for g in groups)
        else:
            res["runners_out"].add(tgt - 1)
        res["run_events"].append("cs" if m.group(1) == "CS" else "po")
        return True
    m = re.match(r"PO([123])((?:\([^()]*\))*)", tok)
    if m:
        groups = re.findall(r"\(([^()]*)\)", m.group(2))
        if _has_error(groups):
            res["err"] += sum(len(re.findall(r"E\d", g)) for g in groups)
            res["run_events"].append("poe")
        else:
            res["runners_out"].add(int(m.group(1)))
            res["run_events"].append("po")
        return True
    for code, name in (("WP", "wp"), ("PB", "pb"), ("BK", "bk"), ("DI", "di"), ("OA", "oa"), ("OBS", "oa")):
        if tok.startswith(code):
            res["run_events"].append(name)
            return True
    if re.match(r"E\d", tok):
        res["err"] += 1
        res["run_events"].append("oa")
        return True
    return False


def classify(basic: str) -> dict:
    """The basic play -> event code, batter destination (None = no plate appearance, 0 = out, 1-4),
    runners put out by the fielding notation, implicit runner moves (stolen bases), fielder, errors."""
    res = {"cd": None, "batter": None, "runners_out": set(), "implicit": {}, "forced": False, "fielder": None,
           "err": 0, "run_events": [], "ok": True}
    b = basic.strip()
    plus = split_top(b, "+")
    head, extras = plus[0], plus[1:]

    def extra_ok():
        for x in extras:
            if not _running(x, res):
                res["ok"] = False

    if head in ("NP", ""):
        res["cd"] = "np"
        return res
    if re.match(r"^\d", head):
        fo = _fielded_out(head)
        res.update(cd="out", runners_out=fo["runners_out"], fielder=fo["fielder"], batter=0 if fo["batter_out"] else 1)
        res["err"] += len(re.findall(r"E\d", head))
        if "E" in head and re.search(r"\dE\d", head) and not fo["runners_out"]:
            res.update(cd="e", batter=1)
        extra_ok()
        return res
    if head.startswith("K"):
        res.update(cd="k", batter=0, fielder=2)
        extra_ok()
        return res
    if head in ("IW", "I") or head.startswith("IW"):
        res.update(cd="ibb", batter=1, forced=True)
        extra_ok()
        return res
    if head.startswith("W") and not head.startswith("WP"):
        res.update(cd="bb", batter=1, forced=True)
        extra_ok()
        return res
    if head.startswith("HP"):
        res.update(cd="hbp", batter=1, forced=True)
        return res
    if head.startswith("DGR"):
        res.update(cd="2b", batter=2, fielder=_digit(head[3:]))
        return res
    if head.startswith("DI"):
        _running(head, res)
        res["cd"] = "di"
        extra_ok()
        return res
    if head == "C" or (head.startswith("C") and not head.startswith("CS")):
        res.update(cd="int", batter=1, forced=True, fielder=2)
        return res
    if head.startswith("HR") or re.match(r"^H\d*$", head):
        res.update(cd="hr", batter=4, fielder=_digit(head.lstrip("HR")))
        return res
    for code, cd, dest in (("S", "1b", 1), ("D", "2b", 2), ("T", "3b", 3)):
        if head.startswith(code) and re.match(rf"^{code}\d*$", head):
            res.update(cd=cd, batter=dest, fielder=_digit(head[1:]))
            return res
    if head.startswith("FLE"):
        res.update(cd="foul_err", err=1)
        return res
    if head.startswith("FC"):
        res.update(cd="fc", batter=1, fielder=_digit(head[2:]))
        return res
    if re.match(r"^E\d", head):
        res.update(cd="e", batter=1, fielder=_digit(head[1:]), err=1)
        return res
    if _running(head, res):
        res["cd"] = res["run_events"][0] if res["run_events"] else "oa"
        extra_ok()
        return res
    res["ok"] = False
    res["cd"] = "unknown"
    return res


def _digit(s: str) -> int | None:
    m = re.match(r"(\d)", s or "")
    return int(m.group(1)) if m else None


def _mods_info(mods: list[str]) -> dict:
    bb, loc, sh, sf = None, None, False, False
    for m in mods:
        mu = m.upper()
        if mu == "SH":
            sh = True
            continue
        if mu == "SF":
            sf = True
            continue
        if bb is None and loc is None:
            hm = _HITLOC.match(mu)
            if hm and (hm.group(1) or hm.group(2)):
                bb, loc = hm.group(1), hm.group(2)
    return {"bb_type": bb, "hit_loc": loc, "sh": sh, "sf": sf}


# ── game simulation ─────────────────────────────────────────────────────────

class Game:
    """Base-out state of one game while its records are replayed."""

    def __init__(self, gid: str, hands: dict, gtype: str, season: int):
        self.gid, self.hands, self.gtype, self.season = gid, hands, gtype, season
        self.info: dict[str, str] = {}
        self.lineup = {0: {}, 1: {}}       # team -> slot -> retro id
        self.pitcher = {0: None, 1: None}   # team -> pitcher on the mound
        self.bases: list[str | None] = [None, None, None]
        self.inning, self.half, self.outs = 0, -1, 0
        self.score = [0, 0]
        self.pending_radj: list[tuple[str, int]] = []
        self.badj: dict[str, str] = {}
        self.padj: dict[str, str] = {}
        self.seq = 0
        self.rows: list[dict] = []
        self.unparsed = 0

    def place(self, team: int, slot: int, pid: str, pos: int) -> None:
        old = self.lineup[team].get(slot)
        if pos == 12 and old:                       # pinch runner takes the base of the player replaced
            for k in range(3):
                if self.bases[k] == old:
                    self.bases[k] = pid
            # ... including an automatic runner placed (radj) for a half-inning that has not started yet
            self.pending_radj = [(pid if r == old else r, b) for r, b in self.pending_radj]
        if pos == 1:
            self.pitcher[team] = pid
        self.lineup[team][slot] = pid

    def new_half(self, inning: int, half: int) -> None:
        self.inning, self.half, self.outs = inning, half, 0
        self.bases = [None, None, None]
        for pid, base in self.pending_radj:
            if 1 <= base <= 3:
                self.bases[base - 1] = pid
        self.pending_radj = []

    def bases_mask(self) -> int:
        return sum(1 << k for k in range(3) if self.bases[k])

    def play(self, inning: int, half: int, batter: str, count: str, pitches: str, ev: str) -> None:
        if (inning, half) != (self.inning, self.half):
            self.new_half(inning, half)
        elif self.pending_radj:
            for pid, base in self.pending_radj:
                self.bases[base - 1] = pid
            self.pending_radj = []
        p = parse_event(ev)
        cl = classify(p["basic"])
        if cl["cd"] == "np":
            return
        if not cl["ok"]:
            self.unparsed += 1
        bat_team, fld_team = half, 1 - half
        pitcher = self.pitcher[fld_team]
        pre_bases = list(self.bases)
        pre_mask, outs_pre = self.bases_mask(), self.outs
        explicit = {a["from"]: a for a in p["adv"]}
        new = [None, None, None]
        runs, outs, errs = 0, 0, cl["err"] + sum(a["err"] for a in p["adv"])
        moves: dict[int, int] = {}        # from base (1-3) -> dest (0 = out, 1-3, 4 = home); unmoved stay
        for base in (1, 2, 3):
            if not pre_bases[base - 1]:
                continue
            if base in explicit:
                a = explicit[base]
                moves[base] = 0 if a["out"] else a["to"]
            elif base in cl["runners_out"]:
                moves[base] = 0
            elif base in cl["implicit"]:
                moves[base] = cl["implicit"][base]
            else:
                moves[base] = base
        if cl["forced"]:                          # walk / HBP / interference: forced runners move up
            if pre_bases[0] and 1 not in explicit:
                moves[1] = max(moves[1], 2)
                if pre_bases[1] and 2 not in explicit:
                    moves[2] = max(moves[2], 3)
                    if pre_bases[2] and 3 not in explicit:
                        moves[3] = 4
        bdest = cl["batter"]
        if bdest is not None and 0 in explicit:
            bdest = 0 if explicit[0]["out"] else explicit[0]["to"]
        elif bdest == 0 and 0 in explicit:
            bdest = explicit[0]["to"]
        # runners put out in the fielding notation also count when no advance mentions them
        for base, dest in moves.items():
            if dest == 0:
                outs += 1
            elif dest == 4:
                runs += 1
            else:
                if new[dest - 1] is not None:          # collision: push the earlier occupant forward
                    self._push(new, dest)
                new[dest - 1] = pre_bases[base - 1]
        if bdest is not None:
            if bdest == 0:
                outs += 1
            elif bdest == 4:
                runs += 1
            else:
                if new[bdest - 1] is not None:
                    self._push(new, bdest)
                new[bdest - 1] = batter
        pa = cl["cd"] in PA_EVENTS and bdest is not None
        mods = _mods_info(p["mods"])
        bats, throws = self.hands.get(batter, ("?", "?"))[0], self.hands.get(pitcher or "", ("?", "?"))[1]
        pit_hand = self.padj.get(pitcher or "", throws)
        bat_hand = self.badj.get(batter) or (("L" if pit_hand == "R" else "R") if bats == "B" else bats)
        cnt = (count or "").strip()
        balls = int(cnt[0]) if len(cnt) == 2 and cnt[0].isdigit() else None
        strikes = int(cnt[1]) if len(cnt) == 2 and cnt[1].isdigit() else None
        self.seq += 1
        outs_post = min(3, outs_pre + outs)
        bases_post = 0 if outs_post >= 3 else sum(1 << k for k in range(3) if new[k])
        self.rows.append({
            "game_id": self.gid, "seq": self.seq, "inning": inning, "half": half,
            "batter": batter, "pitcher": pitcher, "bat_hand": bat_hand, "pit_hand": pit_hand,
            "outs_pre": outs_pre, "bases_pre": pre_mask,
            "run1_pre": pre_bases[0], "run2_pre": pre_bases[1], "run3_pre": pre_bases[2],
            "away_score_pre": self.score[0], "home_score_pre": self.score[1],
            "balls": balls, "strikes": strikes, "pitches": pitches or None,
            "event_tx": ev, "event_cd": cl["cd"], "pa": pa,
            "ab": bool(pa and cl["cd"] not in NOT_AB and not mods["sh"] and not mods["sf"]),
            "hit": HIT_VALUE.get(cl["cd"], 0), "err": errs, "runs_on_play": runs, "outs_on_play": outs,
            "outs_post": outs_post, "bases_post": bases_post, "fielded_by": cl["fielder"],
            "hit_loc": mods["hit_loc"], "bb_type": mods["bb_type"], "sh": mods["sh"], "sf": mods["sf"],
        })
        self.score[bat_team] += runs
        self.outs = outs_post
        self.bases = new if outs_post < 3 else [None, None, None]
        if pa:
            self.badj.pop(batter, None)

    @staticmethod
    def _push(new: list, dest: int) -> None:
        k = dest - 1
        carry = new[k]
        new[k] = None
        while carry is not None and k + 1 < 3:
            k += 1
            carry, new[k] = new[k], carry


def _gtype_from_name(name: str, info_type: str | None) -> str:
    """R for the regular-season zip; for postseason files the round from the file name (2025ALW1 = Wild
    Card, ALD1 = Division Series, ALCS / NLCS = LCS, WS = World Series; 1981 had extra division rounds)."""
    t = (info_type or "").lower()
    if not name.startswith("post/"):
        return "R"
    n = Path(name).stem.upper()[4:]
    if n.startswith("WS") or "world" in t:
        return "W"
    if "CS" in n or "lcs" in t:
        return "L"
    if re.search(r"^[AN]L?W|WC", n) or "wild" in t:
        return "F"
    return "D"


def iter_events(files: dict[str, str], hands: dict | None = None, season: int | None = None) -> Iterator[Game]:
    """Replay every game in the event files; yields finished Game objects (rows in .rows)."""
    hands = hands if hands is not None else parse_rosters(files)
    for name in sorted(files):
        if not re.search(r"\.E[VD][A-Z]$", name.upper()):
            continue
        g: Game | None = None
        for line in files[name].splitlines():
            if not line:
                continue
            f = _csv(line)
            rec = f[0]
            if rec == "id":
                if g is not None:
                    yield g
                g = Game(f[1].strip(), hands, "R", season or 0)
                g.file = name
            elif g is None:
                continue
            elif rec == "info" and len(f) >= 3:
                g.info[f[1]] = f[2]
            elif rec in ("start", "sub") and len(f) >= 6:
                try:
                    team, slot, pos = int(f[3]), int(f[4]), int(f[5])
                except ValueError:
                    continue
                g.place(team, slot, f[1], pos)
            elif rec == "play" and len(f) >= 7:
                try:
                    inning, half = int(f[1]), int(f[2])
                except ValueError:
                    continue
                g.play(inning, half, f[3], f[4], f[5], ",".join(f[6:]))
            elif rec == "radj" and len(f) >= 3:
                try:
                    g.pending_radj.append((f[1], int(f[2])))
                except ValueError:
                    pass
            elif rec == "badj" and len(f) >= 3:
                g.badj[f[1]] = f[2].strip().upper()
            elif rec == "padj" and len(f) >= 3:
                g.padj[f[1]] = f[2].strip().upper()
        if g is not None:
            yield g


def _csv(line: str) -> list[str]:
    if '"' not in line:
        return line.rstrip("\r").split(",")
    import csv
    return next(csv.reader([line.rstrip("\r")]))


PA_COLUMNS = ["game_id", "date", "season", "gtype", "home", "away", "park", "inning", "half", "seq", "bat_team",
              "batter", "pitcher", "bat_hand", "pit_hand", "outs_pre", "bases_pre", "run1_pre", "run2_pre", "run3_pre",
              "away_score_pre", "home_score_pre", "balls", "strikes", "pitches", "event_tx", "event_cd", "pa", "ab",
              "hit", "err", "runs_on_play", "outs_on_play", "outs_post", "bases_post", "fielded_by", "hit_loc",
              "bb_type", "sh", "sf"]


def games_to_frame(games: Iterable[Game]) -> tuple[pd.DataFrame, dict]:
    """Rows of every game (with game-level columns) as the typed PA frame, plus parse stats."""
    rows: list[dict] = []
    stats = {"games": 0, "unparsed": 0}
    for g in games:
        stats["games"] += 1
        stats["unparsed"] += g.unparsed
        info = g.info
        d = (info.get("date") or "").replace("/", "-")
        gtype = _gtype_from_name(getattr(g, "file", ""), info.get("gametype"))
        for r in g.rows:
            r.update(date=d, season=int(d[:4]) if d[:4].isdigit() else g.season, gtype=gtype,
                     home=info.get("hometeam"), away=info.get("visteam"), park=info.get("site"),
                     bat_team=info.get("hometeam") if r["half"] == 1 else info.get("visteam"))
            rows.append(r)
    df = pd.DataFrame(rows, columns=PA_COLUMNS)
    return type_pa(df), stats


def type_pa(df: pd.DataFrame) -> pd.DataFrame:
    for c in ("game_id", "home", "away", "park", "bat_team", "batter", "pitcher", "run1_pre", "run2_pre", "run3_pre",
              "event_cd", "bat_hand", "pit_hand", "gtype", "hit_loc", "bb_type"):
        df[c] = df[c].astype("category")
    for c in ("pitches", "event_tx", "date"):
        df[c] = df[c].astype("string")
    for c in ("inning", "seq", "away_score_pre", "home_score_pre", "season"):
        df[c] = pd.to_numeric(df[c]).astype("int16" if c != "season" else "int16")
    for c in ("half", "outs_pre", "bases_pre", "hit", "err", "runs_on_play", "outs_on_play", "outs_post", "bases_post"):
        df[c] = pd.to_numeric(df[c]).astype("int8")
    for c in ("balls", "strikes", "fielded_by"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int8")
    for c in ("pa", "ab", "sh", "sf"):
        df[c] = df[c].astype(bool)
    return df


# ── game logs ───────────────────────────────────────────────────────────────

_STAT = ["ab", "h", "d", "t", "hr", "rbi", "sh", "sf", "hbp", "bb", "ibb", "k", "sb", "cs", "gidp", "ci", "lob",
         "pitchers", "er", "ter", "wp", "bk", "po", "a", "e", "pb", "dp", "tp"]


def parse_gamelog(text: str) -> pd.DataFrame:
    """A gl<YYYY>.txt as a frame: identifiers, scores, line scores, both teams' 28 stats, umpires, managers,
    decisions, starting pitchers and lineups (ids and positions), and a Retrosheet-style game_id."""
    import csv
    rows = []
    for f in csv.reader(io.StringIO(text)):
        if len(f) < 159:
            continue
        r = {"date": f"{f[0][:4]}-{f[0][4:6]}-{f[0][6:8]}", "num": f[1], "dow": f[2], "away": f[3], "away_lg": f[4],
             "away_gnum": f[5], "home": f[6], "home_lg": f[7], "home_gnum": f[8], "away_score": f[9],
             "home_score": f[10], "outs": f[11], "daynight": f[12], "completion": f[13], "forfeit": f[14],
             "protest": f[15], "park": f[16], "attendance": f[17], "minutes": f[18], "away_line": f[19],
             "home_line": f[20]}
        for k, s in enumerate(_STAT):
            r[f"away_{s}"] = f[21 + k]
            r[f"home_{s}"] = f[49 + k]
        for k, pos in enumerate(("hp", "1b", "2b", "3b", "lf", "rf")):
            r[f"ump_{pos}"] = f[77 + 2 * k]
        r.update(away_mgr=f[89], home_mgr=f[91], wp=f[93], lp=f[95], sv=f[97], gwrbi=f[99], away_sp=f[101],
                 home_sp=f[103])
        for k in range(9):
            r[f"away_bat{k + 1}"] = f[105 + 3 * k]
            r[f"away_pos{k + 1}"] = f[107 + 3 * k]
            r[f"home_bat{k + 1}"] = f[132 + 3 * k]
            r[f"home_pos{k + 1}"] = f[134 + 3 * k]
        r["info"] = f[159] if len(f) > 159 else ""
        r["acq"] = f[160] if len(f) > 160 else ""
        num = r["num"] if r["num"] not in ("", "A", "B") else {"": "0", "A": "1", "B": "2"}[r["num"]]
        r["game_id"] = f"{r['home']}{f[0]}{num}"
        rows.append(r)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    num_cols = ["away_score", "home_score", "outs", "attendance", "minutes", "away_gnum", "home_gnum"] + \
               [f"{s}_{x}" for s in ("away", "home") for x in _STAT]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int32")
    for c in df.columns:
        if c not in num_cols and c not in ("game_id", "date", "away_line", "home_line", "info"):
            df[c] = df[c].replace("", None).astype("category")
    return df


def validate(pa: pd.DataFrame, gl: pd.DataFrame) -> dict:
    """Runs and hits per team from the parsed events against the game logs, game by game (regular season)."""
    if pa.empty or gl.empty:
        return {"games": 0}
    reg = pa[pa["gtype"].astype(str) == "R"]
    side = reg["half"].map({0: "away", 1: "home"})
    agg = reg.assign(side=side, h=(reg["hit"] > 0).astype(int)).groupby(["game_id", "side"], observed=True).agg(
        runs=("runs_on_play", "sum"), hits=("h", "sum")).unstack("side")
    agg.columns = [f"{a}_{b}" for a, b in agg.columns]
    agg = agg.reset_index()
    m = agg.merge(gl[["game_id", "away_score", "home_score", "away_h", "home_h"]], on="game_id", how="inner")
    ok_runs = (m["runs_away"] == m["away_score"]) & (m["runs_home"] == m["home_score"])
    ok_hits = (m["hits_away"] == m["away_h"]) & (m["hits_home"] == m["home_h"])
    bad = m[~(ok_runs & ok_hits)]
    return {"games": int(len(m)), "events_games": int(agg["game_id"].nunique()), "log_games": int(len(gl)),
            "runs_match": round(float(ok_runs.mean()), 5), "hits_match": round(float(ok_hits.mean()), 5),
            "both_match": round(float((ok_runs & ok_hits).mean()), 5),
            "runs_total": [int(m["runs_away"].sum() + m["runs_home"].sum()),
                           int(m["away_score"].sum() + m["home_score"].sum())],
            "hits_total": [int(m["hits_away"].sum() + m["hits_home"].sum()), int(m["away_h"].sum() + m["home_h"].sum())],
            "mismatches": bad["game_id"].head(10).tolist()}


def parse_season(c: Client | None, year: int) -> dict:
    """Download (once) and parse a season: events (regular + postseason) to <raw>/retro/pa/<year>.parquet,
    the game log to <raw>/retro/games/<year>.parquet; returns counts and the validation."""
    out: dict = {"season": year}
    gl_zip = download(c, year, "gamelog")
    gl = pd.DataFrame()
    if gl_zip:
        files = read_zip(gl_zip)
        text = next((v for k, v in files.items() if k.upper().endswith(".TXT")), "")
        gl = parse_gamelog(text)
        if not gl.empty:
            p = st.retro_games_path(year)
            p.parent.mkdir(parents=True, exist_ok=True)
            gl.to_parquet(p, compression="zstd", index=False)
        out["gamelog_games"] = int(len(gl))
    files: dict[str, str] = {}
    for kind in ("eve", "post"):
        z = download(c, year, kind) if year >= EVENTS_FROM else None
        if z:
            for k, v in read_zip(z).items():
                files[f"{kind}/{k}"] = v
    if not files:
        out["events"] = 0
        return out
    hands = parse_rosters(files)
    pa, stats = games_to_frame(iter_events(files, hands, year))
    out.update(events=int(len(pa)), pa=int(pa["pa"].sum()) if len(pa) else 0, event_games=stats["games"],
               unparsed=stats["unparsed"])
    if len(pa):
        p = st.retro_pa_path(year)
        p.parent.mkdir(parents=True, exist_ok=True)
        pa.to_parquet(p, compression="zstd", index=False)
    out["validation"] = validate(pa, gl)
    return out
