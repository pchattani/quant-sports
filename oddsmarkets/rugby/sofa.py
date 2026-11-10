"""
The Sofascore side store merged into the tests (store.load_all, after the Wikipedia merge). Off with
SOURCE_SOFASCORE_RUGBY_ENABLED=0: nothing is read and the tests are ESPN's and Wikipedia's alone.

  - A test ESPN or Wikipedia already has (same day +-1, same two sides, same score): Sofascore's team statistics fill
    `hstat` / `astat` when the row has none, and its players' statistics fill the ESPN line-up's empty stat slots
    (matched by shirt number, checked on the surname). Rows touched carry `stat_src: "sofascore"`.
  - A test only Sofascore has is added (`source: "sofascore"`, id "s<event id>") when both Sofascore teams are proven
    union sides: each has at least one event that matched an ESPN or Wikipedia test on the score. That keeps rugby
    league and sevens internationals (filed under the same sport) out of the ratings.

Everything here is a finished match's facts, used only for that match and later ones (no look-ahead).
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

from . import nations

# Sofascore statistic (its item key, else its name; folded to lower-case letters and digits) -> our ESPN team key
TEAM_MAP = {
    "tries": "tries", "conversions": "cons", "conversiongoals": "cons", "penaltygoals": "pen_goals", "dropgoals": "drops",
    "possession": "poss", "ballpossession": "poss", "territory": "terr",
    "metres": "metres", "meters": "metres", "metrescarried": "metres", "meterscarried": "metres", "metresmade": "metres",
    "metersmade": "metres", "metresrun": "metres", "metersrun": "metres", "carries": "carries", "runs": "carries",
    "cleanbreaks": "breaks", "linebreaks": "breaks", "defendersbeaten": "beaten", "offloads": "offloads", "passes": "passes",
    "tackles": "tackles", "tacklesmade": "tackles", "missedtackles": "missed", "tacklesmissed": "missed",
    "tacklesuccess": "tackle_pct", "tacklesuccessrate": "tackle_pct",
    "ruckswon": "rucks_won", "rucks": "rucks", "maulswon": "mauls_won",
    "scrumswon": "scrums_won", "scrums": "scrums", "lineoutswon": "lineouts_won", "lineouts": "lineouts",
    "turnoverswon": "to_won", "turnoversconceded": "to_conc", "turnovers": "to_conc",
    "penaltiesconceded": "pens", "penalties": "pens", "freekicksconceded": "free_kicks",
    "yellowcards": "yc", "redcards": "rc", "kicksfromhand": "kicks", "kicks": "kicks", "kickmetres": "kick_m",
    "handlingerrors": "handling_err", "knockons": "knock_ons",
}
# share statistics: Sofascore gives a percentage, we keep a fraction
FRACTION = {"poss", "terr", "tackle_pct", "kick_pct"}
# 'won/total' items: the total goes to this key
TOTAL_OF = {"scrums_won": "scrums", "lineouts_won": "lineouts", "rucks_won": "rucks", "mauls_won": "mauls"}

# Sofascore player statistic -> our ESPN player key (sources/espn.PLAYER_KEYS values)
PLAYER_MAP = {
    "points": "pts", "tries": "tries", "tryassists": "ta", "tryassist": "ta", "conversions": "con", "conversiongoals": "con",
    "penaltygoals": "pg", "dropgoals": "dg", "metres": "m", "meters": "m", "metrescarried": "m", "meterscarried": "m",
    "metresrun": "m", "metersrun": "m", "carries": "car", "runs": "car", "cleanbreaks": "cb", "linebreaks": "cb",
    "defendersbeaten": "db", "offloads": "off", "passes": "pas", "tackles": "tk", "tacklesmade": "tk",
    "missedtackles": "mt", "tacklesmissed": "mt", "lineoutswon": "lo", "ruckswon": "rk", "maulswon": "ml",
    "turnoversconceded": "toc", "knockons": "ko", "penaltiesconceded": "pc", "freekicksconceded": "fk",
    "yellowcards": "yc", "redcards": "rc", "kicksfromhand": "kfh", "kicks": "kfh",
}


def enabled() -> bool:
    from .sources import sofascore as sf
    return sf.enabled()


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _surname(s: str) -> str:
    parts = [p for p in re.split(r"[\s.]+", str(s or "").strip()) if p]
    return _fold(parts[-1]) if parts else ""


_LOADED: dict = {}


def load() -> dict:
    """The side store (cached per process); {} when missing or unreadable."""
    from . import store
    p = store.side_dir() / "sofascore.json.gz"
    k = str(p)
    if k not in _LOADED:
        try:
            _LOADED[k] = store.read_gz(p) if p.exists() else {}
        except (OSError, ValueError):
            _LOADED[k] = {}
    return _LOADED[k]


def team_stats(raw: dict | None) -> tuple[dict, dict]:
    """Sofascore's statistics -> (home, away) in our keys; a key we cannot map is left out (never zero-filled)."""
    h, a = {}, {}
    for k, row in (raw or {}).items():
        name = k[5:] if k.startswith("name:") else k
        ours = TEAM_MAP.get(_fold(name))
        if not ours or not isinstance(row, list) or len(row) < 2:
            continue
        for side, v, tot in ((h, row[0], row[2] if len(row) > 2 else None), (a, row[1], row[3] if len(row) > 3 else None)):
            if not isinstance(v, (int, float)):
                continue
            if ours in FRACTION:
                v = v / 100.0 if v > 1.0 else v
                side.setdefault(ours, round(float(v), 3))
            else:
                side.setdefault(ours, int(v) if float(v).is_integer() else round(float(v), 2))
            if ours in TOTAL_OF and isinstance(tot, (int, float)):
                side.setdefault(TOTAL_OF[ours], int(tot))
    for side in (h, a):
        if "tackles" in side and "missed" in side and "tackle_pct" not in side and side["tackles"] + side["missed"] > 0:
            side["tackle_pct"] = round(side["tackles"] / (side["tackles"] + side["missed"]), 3)
    return h, a


def player_stats(raw: dict | None) -> dict:
    out = {}
    for k, v in (raw or {}).items():
        ours = PLAYER_MAP.get(_fold(k))
        if ours and isinstance(v, (int, float)) and ours not in out:
            out[ours] = int(v) if float(v).is_integer() else round(float(v), 2)
    return out


def _pair(h: str, a: str) -> tuple:
    return tuple(sorted((nations.base_name(nations.canonical(h)), nations.base_name(nations.canonical(a)))))


def _attach_players(m: dict, side_row: str, lu: list) -> int:
    """Fill the empty stat slots of an ESPN line-up (`lh` / `la`) from Sofascore's players, by shirt number with the
    surname checked. Returns the players filled."""
    rows = m.get(side_row) or []
    if not rows or not lu:
        return 0
    by_shirt = {p[2]: p for p in lu if isinstance(p[2], int)}
    names = m.get("_names") or {}
    n = 0
    for r in rows:
        if len(r) < 6 or r[5]:
            continue
        sp = by_shirt.get(r[1])
        if not sp:
            continue
        nm = names.get(str(r[0]))
        if nm and _surname(nm) and _surname(sp[1]) and _surname(nm) != _surname(sp[1]):
            continue
        st = player_stats(sp[6] if len(sp) > 6 else None)
        if st:
            r[5] = st
            n += 1
    return n


def merge(scope: str, matches: list[dict], athletes: dict | None = None) -> tuple[list[dict], dict]:
    if not enabled():
        return matches, {"enabled": False}
    S = load()
    evs = [e for e in (S.get("events") or {}).values() if e.get("scope", "men") == scope and e.get("st") == "finished"
           and isinstance(e.get("hs"), int) and isinstance(e.get("as"), int)]
    if not evs:
        return matches, {"events": 0}
    det = S.get("detail") or {}
    idx = defaultdict(list)
    for m in matches:
        if m.get("status") != "final":
            continue
        idx[(str(m.get("date") or "")[:10], _pair(m["home"]["name"], m["away"]["name"]))].append(m)
    teams_by_base = {}
    for m in matches:
        for sd in ("home", "away"):
            t = m.get(sd) or {}
            b = nations.base_name(t.get("name") or "")
            if b and (b not in teams_by_base or not str(t.get("id", "")).startswith("w")):
                teams_by_base[b] = t
    rep = {"events": len(evs), "matched": 0, "conflicts": 0, "team_stats": 0, "player_stats": 0, "players": 0, "added": 0,
           "unproven": 0}
    union_ids: set = set()
    unmatched = []
    for e in sorted(evs, key=lambda x: x["ts"]):
        pair = _pair(e["h"]["name"], e["a"]["name"])
        d = date.fromisoformat(e["date"][:10])
        hit = None
        for k in (0, -1, 1):
            c = idx.get(((d + timedelta(days=k)).isoformat(), pair))
            if c:
                hit = c[0]
                break
        if hit is None:
            unmatched.append(e)
            continue
        hb = nations.base_name(nations.canonical(hit["home"]["name"]))
        eh = nations.base_name(nations.canonical(e["h"]["name"]))
        flip = hb != eh
        es = (e["as"], e["hs"]) if flip else (e["hs"], e["as"])
        if hit.get("ro") or (hit.get("hs"), hit.get("as")) != es:
            rep["conflicts"] += 1
            continue
        rep["matched"] += 1
        union_ids.update((e["h"]["id"], e["a"]["id"]))
        dd = det.get(str(e["id"])) or {}
        if not dd:
            continue
        touched = False
        if not (hit.get("hstat") and hit.get("astat")) and dd.get("stats"):
            h, a = team_stats(dd["stats"])
            if flip:
                h, a = a, h
            if h and a:
                hit["hstat"], hit["astat"] = h, a
                rep["team_stats"] += 1
                touched = True
        lu = dd.get("lu") or {}
        if lu and (hit.get("lh") or hit.get("la")):
            if athletes is not None:
                hit["_names"] = {str(r[0]): (athletes.get(str(r[0])) or {}).get("name") for r in (hit.get("lh") or []) + (hit.get("la") or [])}
            n = _attach_players(hit, "lh", lu.get("a" if flip else "h") or []) + _attach_players(hit, "la", lu.get("h" if flip else "a") or [])
            hit.pop("_names", None)
            if n:
                rep["player_stats"] += 1
                rep["players"] += n
                touched = True
        if touched:
            hit["stat_src"] = "sofascore"
    sfx = " Women" if scope == "women" else ""
    added = []
    for e in unmatched:
        if e["h"]["id"] not in union_ids or e["a"]["id"] not in union_ids:
            rep["unproven"] += 1
            continue

        def team(t):
            b = nations.base_name(nations.canonical(t["name"]))
            have = teams_by_base.get(b)
            if have:
                return {"id": have["id"], "name": b + sfx, "abbr": have.get("abbr"), "colour": have.get("colour"), "alt": have.get("alt")}
            rr = nations.lookup(b)
            code = rr["code"] if rr else (t.get("code") or b[:3].upper())
            return {"id": f"w{code}", "name": b + sfx, "abbr": code, "colour": None, "alt": None}
        m = {"id": f"s{e['id']}", "comp": _comp(e), "slug": "sofascore", "season": int(e["date"][:4]), "date": e["date"],
             "time_known": True, "status": "final", "neutral": False, "venue": {}, "home": team(e["h"]), "away": team(e["a"]),
             "hs": e["hs"], "as": e["as"], "hh": [], "ah": [], "note": e.get("utn") or "",
             "season_slug": "", "source": "sofascore"}
        dd = det.get(str(e["id"])) or {}
        if dd.get("stats"):
            h, a = team_stats(dd["stats"])
            if h and a:
                m["hstat"], m["astat"] = h, a
                m["stat_src"] = "sofascore"
        added.append(m)
    rep["added"] = len(added)
    out = matches + added
    out.sort(key=lambda m: (m.get("date") or "", m.get("id")))
    return out, rep


def _comp(e: dict) -> str:
    n = (e.get("utn") or "").lower()
    if "nations championship" in n:
        return "nc"
    if "six nations" in n:
        return "w6n" if "women" in n else "six"
    if "rugby championship" in n:
        return "trc"
    if "world cup" in n and "qualif" not in n:
        return "wrwc" if "women" in n else "rwc"
    if "wxv" in n:
        return "wxv"
    return "test"
