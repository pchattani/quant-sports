"""
Season tables for the college basketball models: one numpy view of a store's games.

Teams: every Division I member of the season (`teams[tid].member`) is rated individually; every non-member
opponent (Division II, NAIA, ...) is pooled into one pseudo-team `ND1` per season (a game between two non-members
is dropped). Game day = the US calendar day (UTC - 6 h).

Possessions (per game, the mean of the two teams' estimates):
    box score:   FGA - OREB + TOV + 0.475 FTA          (TOV includes team turnovers; exact boxes only, `box_ok`)
    scoreboard:  k_s * (FGA + 0.475 FTA)                (no OREB / TOV on ESPN's scoreboard line)
k_s is the season's ratio sum(box) / sum(scoreboard) over games that have both (when the season has at least
MIN_BOX such games), else the level's pooled ratio over every season with box scores, else K_DEFAULT.
Games with neither (mbb 2002-2004, most wbb games before 2017 until the summaries backfill lands) get
possessions imputed from the teams' tempo in the ratings fit (`ratings.impute_poss`).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from oddsmarkets.college import canon
from oddsmarkets.college import store as ST

LEVELS = ("mbb", "wbb")
COUNTED = ("reg", "conf", "ncaa", "nit", "wbit", "post")
POSTSEASON = ("ncaa", "nit", "wbit", "post")
ND1 = "nd1"
FTA_K = 0.475
MIN_BOX = 200
K_DEFAULT = {"mbb": 0.93, "wbb": 0.95}
DEFAULT_PACE = {"mbb": 68.0, "wbb": 70.0}
DEFAULT_ORTG = {"mbb": 104.0, "wbb": 95.0}


def level_of(level: str) -> str:
    lv = str(level).lower()
    if lv not in LEVELS:
        raise ValueError(f"not a basketball level: {level!r}")
    return lv


def local_day(iso: Any) -> date | None:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (t - timedelta(hours=6)).date()


def day_str(d: int) -> str:
    return date.fromordinal(int(d)).isoformat()


# ── store access (read only) ────────────────────────────────────────────────

_CACHE: dict[tuple[str, int], tuple[tuple, dict]] = {}


def _stat(p: Path) -> tuple:
    try:
        s = p.stat()
        return (s.st_size, s.st_mtime_ns)
    except OSError:
        return (0, 0)


def load(level: str, season: int) -> dict:
    """The store (via store.load; memoised on the file's size and mtime, so a backfill write is picked up)."""
    key = (level, int(season))
    p = ST.store_path(level, season)
    sig = _stat(p)
    hit = _CACHE.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    s = ST.load(level, season)
    _CACHE[key] = (sig, s)
    if len(_CACHE) > 60:
        _CACHE.pop(next(iter(_CACHE)))
    return s


def seasons(level: str) -> list[int]:
    return ST.seasons_on_disk(level)


def content_sig(level: str, seasons_: Iterable[int]) -> str:
    """sha1 over the stores' bytes (content, not paths or mtimes): cache keys survive a checkout."""
    h = hashlib.sha1()
    for s in sorted(int(x) for x in seasons_):
        p = ST.store_path(level, s)
        h.update(str(s).encode())
        try:
            h.update(hashlib.sha1(p.read_bytes()).digest())
        except OSError:
            h.update(b"missing")
    return h.hexdigest()[:20]


def cache_dir(*parts: str) -> Path:
    d = ST.paths()["cache"].joinpath("hoops", *parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def cached(name: str, key: Any, fn, *parts: str):
    """JSON cache under <cache>/hoops/<parts>/<name>.json keyed on `key` (no absolute paths in keys)."""
    p = cache_dir(*parts) / f"{name}.json"
    k = json.dumps(key, sort_keys=True, default=str)
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
        if c.get("key") == k:
            return c["value"]
    except (OSError, ValueError, KeyError):
        pass
    v = fn()
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"key": k, "value": v}, separators=(",", ":"), default=_jdefault), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass
    return json.loads(json.dumps(v, default=_jdefault))


def _jdefault(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o))


# ── possessions ─────────────────────────────────────────────────────────────

def box_ok(game: dict, rel: float = 0.0) -> bool:
    """A usable box score: both teams' box points (2 FGM + 3PM + FTM) within max(1, rel * score) of the final score
    and some turnovers recorded. ESPN's older women's boxes (2004-2013) are partial (a 100-point side whose box sums
    to 60, no turnovers) and about one men's game in eight 2018-2023 misses a player's line; possessions use only
    exact boxes (rel 0), player value tolerates a missing bench line (rel 0.1)."""
    b = game.get("box") or {}
    if len(b) != 2:
        return False
    score = {str(game.get("home")): game.get("hs"), str(game.get("away")): game.get("as")}
    tov = 0.0
    for t, v in b.items():
        tm = (v or {}).get("team") or {}
        try:
            pts = 2 * float(tm["fgm"]) + float(tm["tpm"]) + float(tm["ftm"])
            sc = float(score[str(t)])
        except (KeyError, TypeError, ValueError):
            return False
        if abs(pts - sc) > max(1.0, rel * sc):
            return False
        tov += float(tm.get("tov") or 0)
    return tov > 0


def box_poss(game: dict) -> float | None:
    b = game.get("box") or {}
    if len(b) != 2 or not box_ok(game):
        return None
    vals = []
    for v in b.values():
        t = (v or {}).get("team") or {}
        try:
            vals.append(float(t["fga"]) - float(t["oreb"]) + float(t["tov"]) + FTA_K * float(t["fta"]))
        except (KeyError, TypeError, ValueError):
            return None
    p = sum(vals) / 2.0
    return p if 30 <= p <= 140 else None


def scoreboard_x(game: dict) -> float | None:
    ts = game.get("team_stats") or {}
    if len(ts) != 2:
        return None
    vals = []
    for v in ts.values():
        try:
            vals.append(float(v["fga"]) + FTA_K * float(v["fta"]))
        except (KeyError, TypeError, ValueError):
            return None
    x = sum(vals) / 2.0
    return x if 30 <= x <= 160 else None


def poss_ratio(level: str, seasons_: Iterable[int] | None = None) -> dict:
    """{"pooled": k, "by_season": {S: k}, "n": {S: games}, "mae_ratio", "mae_const"} from games with both a box
    score and a scoreboard line (k = sum(box) / sum(scoreboard x))."""
    lv = level_of(level)
    ss = sorted(seasons_ if seasons_ is not None else seasons(lv))
    by, nn, xs, ys = {}, {}, [], []
    for s in ss:
        st = load(lv, s)
        a, b = [], []
        for g in (st.get("games") or {}).values():
            if g.get("status") != "post" or not g.get("box"):
                continue
            pb, x = box_poss(g), scoreboard_x(g)
            if pb and x:
                a.append(x)
                b.append(pb)
        if len(a) >= MIN_BOX:
            by[s] = float(np.sum(b) / np.sum(a))
        nn[s] = len(a)
        xs += a
        ys += b
    out = {"pooled": K_DEFAULT[lv], "by_season": by, "n": nn, "mae_ratio": None, "mae_const": None}
    if len(xs) >= MIN_BOX:
        x, y = np.array(xs), np.array(ys)
        k = float(y.sum() / x.sum())
        out["pooled"] = k
        out["mae_ratio"] = round(float(np.mean(np.abs(y - k * x))), 3)
        out["mae_const"] = round(float(np.mean(np.abs(y - y.mean()))), 3)
    return out


# ── season table ────────────────────────────────────────────────────────────

def member_ids(st: dict) -> list[str]:
    return sorted(t for t, v in (st.get("teams") or {}).items() if (v or {}).get("member"))


def _ml_p(o: dict) -> float | None:
    def p(a):
        try:
            a = float(a)
        except (TypeError, ValueError):
            return None
        if a == 0:
            return None
        return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)
    ph, pa = p(o.get("ml_home")), p(o.get("ml_away"))
    if ph is None or pa is None or ph + pa <= 0:
        return None
    return ph / (ph + pa)


TOTAL_RANGE = {"mbb": (95.0, 215.0), "wbb": (80.0, 200.0)}


def clean_odds(level: str, o: dict | None) -> dict:
    """The stored line with implausible numbers dropped (ESPN core odds sometimes carry the price in the line fields:
    304 ESPN BET games of mbb 2023 have spread and total -110). spread kept when |spread| <= 60, total when inside
    TOTAL_RANGE, moneylines when both are valid American prices (|ml| >= 100) and not equal to the spread; a spread
    equal to the total drops both. Returns {"spread","total","ml_home","ml_away","close_block","provider"}."""
    o = o or {}

    def num(x):
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None
    sp, tt = num(o.get("spread_home")), num(o.get("total"))
    mh, ma = num(o.get("ml_home")), num(o.get("ml_away"))
    if sp is not None and tt is not None and sp == tt:
        sp = tt = None
    if sp is not None and abs(sp) > 60:
        sp = None
    lo, hi = TOTAL_RANGE[level_of(level)]
    if tt is not None and not lo <= tt <= hi:
        tt = None
    sp_raw = num(o.get("spread_home"))
    if mh is None or ma is None or abs(mh) < 100 or abs(ma) < 100 or (sp_raw is not None and abs(sp_raw) >= 100):
        mh = ma = None
    return {"spread": sp, "total": tt, "ml_home": mh, "ml_away": ma, "close_block": bool(o.get("has_close_block")),
            "provider": o.get("provider")}


def neutral_map(st: dict) -> dict[str, bool]:
    """{gid: neutral} for every game. ESPN's flag where the season carries flags (at least 2% of regular-season games
    flagged); otherwise (mbb before 2008, wbb before 2011) inferred: a game is neutral when its venue differs from
    the home team's usual home venue (the venue of most of its home games, at least 3), and NCAA tournament and
    conference tournament games without a venue are neutral."""
    games = st.get("games") or {}
    reg = [g for g in games.values() if g.get("stype") == "reg"]
    flagged = sum(1 for g in reg if g.get("neutral"))
    if reg and flagged / len(reg) >= 0.02:
        return {str(g["id"]): bool(g.get("neutral")) for g in games.values()}
    from collections import Counter
    homes: dict[str, Counter] = {}
    for g in games.values():
        v = ((g.get("venue") or {}).get("name") or "").strip().lower()
        if v and g.get("home"):
            homes.setdefault(str(g["home"]), Counter())[v] += 1
    mode = {t: c.most_common(1)[0] for t, c in homes.items()}
    out = {}
    for g in games.values():
        v = ((g.get("venue") or {}).get("name") or "").strip().lower()
        mv = mode.get(str(g.get("home")))
        if v and mv and mv[1] >= 3:
            out[str(g["id"])] = v != mv[0]
        else:
            out[str(g["id"])] = g.get("stype") in ("ncaa", "conf")
    return out


def season_table(level: str, season: int, st: dict | None = None, k_poss: float | None = None) -> dict:
    """
    {"level","season","teams": [tid..., ND1],"idx","T","member": bool[T],"conf": [cid|None],
     "g": {finished games: "gid","day","h","a","hs","as","neutral","conf","ot","stype","poss","pace40","poss_src",
           "spread","total","p_ml","pred","nh","na" (non-member flags)},
     "pend": {scheduled/live games: "gid","day","h","a","neutral","conf","stype","status"},
     "k_poss"}
    """
    lv = level_of(level)
    st = st if st is not None else load(lv, season)
    members = member_ids(st)
    teams = members + [ND1]
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    tinfo = st.get("teams") or {}
    confs = [(tinfo.get(t) or {}).get("conference") for t in members] + [None]
    regp = canon.reg_periods(lv, season)
    neu = neutral_map(st)
    fin: dict[str, list] = {k: [] for k in ("gid", "day", "h", "a", "hs", "as", "neutral", "conf", "ot", "stype",
                                             "pbox", "xsb", "spread", "total", "p_ml", "pred", "nh", "na", "cblock")}
    pend: dict[str, list] = {k: [] for k in ("gid", "day", "h", "a", "neutral", "conf", "stype", "status")}
    for g in (st.get("games") or {}).values():
        stype = g.get("stype")
        if stype not in COUNTED:
            continue
        h, a = str(g.get("home") or ""), str(g.get("away") or "")
        if not h or not a or h == a:
            continue
        mh, ma = h in idx and h != ND1, a in idx and a != ND1
        if not mh and not ma:
            continue
        d = local_day(g.get("date"))
        if d is None:
            continue
        hi, ai = idx[h] if mh else idx[ND1], idx[a] if ma else idx[ND1]
        status = g.get("status")
        if status == "post" and g.get("hs") is not None and g.get("as") is not None:
            try:
                hs, as_ = float(g["hs"]), float(g["as"])
            except (TypeError, ValueError):
                continue
            if hs == as_ or hs + as_ < 40:
                continue
            o = clean_odds(lv, g.get("odds"))
            fin["gid"].append(str(g["id"]))
            fin["day"].append(d.toordinal())
            fin["h"].append(hi)
            fin["a"].append(ai)
            fin["hs"].append(hs)
            fin["as"].append(as_)
            fin["neutral"].append(neu.get(str(g["id"]), bool(g.get("neutral"))))
            fin["conf"].append(bool(g.get("conf_game")))
            per = int(g.get("periods") or regp)
            fin["ot"].append(max(0, per - regp))
            fin["stype"].append(stype)
            fin["pbox"].append(box_poss(g) or np.nan)
            fin["xsb"].append(scoreboard_x(g) or np.nan)
            sp = o["spread"]
            fin["spread"].append(sp if sp is not None else np.nan)
            tt = o["total"]
            fin["total"].append(tt if tt is not None else np.nan)
            pm = _ml_p(o)
            fin["p_ml"].append(pm if pm is not None else np.nan)
            fin["cblock"].append(o["close_block"] and sp is not None)
            pr = (g.get("predictor") or {}).get("home")
            try:
                pr = float(pr)
                pr = pr / 100.0 if pr > 1 else pr
            except (TypeError, ValueError):
                pr = np.nan
            fin["pred"].append(pr)
            fin["nh"].append(not mh)
            fin["na"].append(not ma)
        elif status in ("pre", "in", "postponed"):
            pend["gid"].append(str(g["id"]))
            pend["day"].append(d.toordinal())
            pend["h"].append(hi)
            pend["a"].append(ai)
            pend["neutral"].append(neu.get(str(g["id"]), bool(g.get("neutral"))))
            pend["conf"].append(bool(g.get("conf_game")))
            pend["stype"].append(stype)
            pend["status"].append(status)
    order = np.argsort(np.array(fin["day"], dtype=np.int64), kind="stable")
    G = {}
    for k, v in fin.items():
        arr = np.array(v, dtype=object if k in ("gid", "stype") else None)
        G[k] = arr[order] if len(arr) else arr
    for k in ("h", "a", "ot", "day"):
        G[k] = G[k].astype(np.int64) if len(G[k]) else np.zeros(0, np.int64)
    for k in ("hs", "as", "pbox", "xsb", "spread", "total", "p_ml", "pred"):
        G[k] = G[k].astype(float) if len(G[k]) else np.zeros(0)
    for k in ("neutral", "conf", "nh", "na", "cblock"):
        G[k] = G[k].astype(bool) if len(G[k]) else np.zeros(0, bool)
    if not len(G["gid"]):
        G["gid"] = np.zeros(0, dtype=object)
        G["stype"] = np.zeros(0, dtype=object)
    # season possession correction
    both = np.isfinite(G["pbox"]) & np.isfinite(G["xsb"])
    if both.sum() >= MIN_BOX:
        kp = float(G["pbox"][both].sum() / G["xsb"][both].sum())
    else:
        kp = float(k_poss) if k_poss else K_DEFAULT[lv]
    poss = np.where(np.isfinite(G["pbox"]), G["pbox"], kp * G["xsb"])
    G["poss"] = poss
    G["poss_src"] = np.where(np.isfinite(G["pbox"]), 1, np.where(np.isfinite(G["xsb"]), 2, 0))
    G["pace40"] = poss * 40.0 / (40.0 + 5.0 * G["ot"])
    P = {}
    porder = np.argsort(np.array(pend["day"], dtype=np.int64), kind="stable")
    for k, v in pend.items():
        arr = np.array(v, dtype=object if k in ("gid", "stype", "status") else None)
        P[k] = arr[porder] if len(arr) else arr
    for k in ("h", "a", "day"):
        P[k] = P[k].astype(np.int64) if len(P[k]) else np.zeros(0, np.int64)
    for k in ("neutral", "conf"):
        P[k] = P[k].astype(bool) if len(P[k]) else np.zeros(0, bool)
    return {"level": lv, "season": int(season), "teams": teams, "idx": idx, "T": T,
            "member": np.array([True] * len(members) + [False]), "conf": confs, "g": G, "pend": P, "k_poss": kp,
            "n_box": int(np.isfinite(G["pbox"]).sum())}


def subset(G: dict, m: np.ndarray) -> dict:
    return {k: v[m] for k, v in G.items()}
