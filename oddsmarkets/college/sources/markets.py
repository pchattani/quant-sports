"""
College prices from Kalshi and Polymarket (and the DraftKings line ESPN carries), mapped to ESPN team and
player ids. Unreachable or thin = an unavailable TITLE / None; nothing here raises.

What exists (surveyed 2026-10-19: Kalshi /series?category=Sports, 4013 series, about 330 college ones;
Polymarket tags "cfb" (365 open events), "cbb" (1), "ncaa" (5); no women's basketball tag yet)

  Football (cfb)
    Kalshi  KXNCAAF-27           national champion, 52 markets (16 quoted), event suffix = the title game's year
            KXNCAAFPLAYOFF-26    CFP qualifiers (per-team yes/no, 57 markets, 40 quoted), suffix = season
            KXNCAAFSF-27         CFP semifinal qualifiers; KXNCAAFQF quarterfinal qualifiers (none open)
            KXHEISMAN-27         Heisman winner (48 markets, 9 quoted; players)
            KXNCAAFSEC-26, KXNCAAFB10-26, KXNCAAFB12-26, KXNCAAFACC-26, KXNCAAFAAC-26, KXNCAAFMWC-26,
            KXNCAAFMAC-26 (open); KXNCAAFSBELT, KXNCAAFCUSA, KXNCAAFPAC12 (no open event)  conference champions
            KXNCAAFWINS-26<TEAM> regular-season win ladders (73 teams; "N+ wins")
            KXNCAAFGAME-26OCT31ORSTFRES  per game, two team markets (team-code suffix); KXNCAAFSPREAD /
            KXNCAAFTOTAL per game (not used); KXNCAAFBOWLGAME bowl qualifiers (unquoted)
            not used: conference qualifiers (KXNCAAFSECQ ...), AP/CFP poll ranks, awards, coaches, props
    Polymarket (tag "cfb")
            "NCAA Football: 2027 National Champion" (109 markets, ~$1.1M), "NCAA Football: 2026 Heisman Award
            Winner", "NCAA Football 2026 <Conference> Conference: Winner" (ACC, American, American CUSA, Big 12,
            Big Ten, MAC, Mountain West, PAC-12, SEC, Sun Belt), "Team to Make National Championship", "CFB
            Playoffs team to make Semis / Quarters", "CFB Playoff Top 4 Seeds", per-team win totals, and per game
            "cfb-<a>-<b>-YYYY-MM-DD" (214 open; moneyline market sportsMarketType "moneyline", outcomes
            [team A, team B], plus spreads and totals)
  Men's basketball (mbb)
    Kalshi  KXMARMAD-27 champion (73 markets); KXMARMADROUND-27{R32,R16,R8,F4,T2} round qualifiers (112);
            KXMAKEMARMAD (field qualifiers, opens near Selection Sunday); KXNCAAMBWINS-26<TEAM> win ladders;
            KXNCAAMBGAME-26NOV02LIBHP per game; conference tournaments (KXNCAAMBSEC, KXNCAAMBBIG10, KXNCAAMBACC,
            KXNCAAMBBIG12, KXNCAAMBBIGEAST ...) and regular-season titles open in season; KXMARMADREGION, seeds,
            Naismith, AP-rank markets not used
    Polymarket (tag "cbb")  "2027 Men's College Basketball National Champion"; game events expected as
            "cbb-<a>-<b>-YYYY-MM-DD" once the season starts (none listed yet)
  Women's basketball (wbb)
    Kalshi  KXWMARMAD-27 champion (35 markets); KXWMARMADROUND-27{R32,R16,QF,SEMI}; KXNCAAWBWINS-26<TEAM>;
            KXNCAAWBGAME per game. Polymarket: nothing listed.

Prices are Hardwood's (basketball/sources/markets.py, itself F1's): a price is the midpoint of a live two-sided
quote (spread at most 0.12); a runner with no bid and an ask of 2c or less is a floor runner (priced at about 0).
The thin rule is college's own (`assemble`), one venue's book at a time, because college fields are long and
mostly unquoted and the two venues quote very different subsets (21 Oct 2026, men's champion: Kalshi 56 runners
quoted, implied total 1.02; Polymarket 33 quoted, 1.48, its tail mids sitting on 0.001-0.107 quotes):
  * a book is usable when it accounts for (quotes, floors or has settled) at least max(4, half the field) runners
    and its implied total is within BOOK_TOTAL (0.8-1.3). Below 0.8 runners are missing (a mostly unquoted
    conference book sums to 0.1-0.7) and normalising would hand their mass to the quoted ones; up to 1.3 the
    excess is overround and is removed by de-vigging; above, the book is not a price: Polymarket's 1.48 men's book
    of 21 Oct 2026 put a de-vigged 0.231 on the ten runners Kalshi prices under 1% (Kalshi 0.052, a median 4.8
    times Kalshi), noise in wide tail quotes rather than margin, and pooling it moved the second favourite from
    13.2% to 11.0%;
  * each usable book is de-vigged on its own: power when overround (the margin sits on the longshots, as with
    these wide tail quotes), proportional when underround (the missing mass is the floor runners');
  * the pooled price of a runner is the mean of its fair probabilities over the usable books that quote it,
    renormalised to 1; a thin book never enters the pool (it stays in `by_source` and `books`).
For a college champion market the field is the runners the markets list (not every FBS / D-I team).

Names: Kalshi labels ("Ohio St.", "Miami (FL)", "Hawai'i") and Polymarket outcomes are matched to the store's
member teams by folded location / short name / full name (with "St." -> "State"), then by the ticker's team code
against ESPN abbreviations, then `best_match`; players by Hardwood's `map_player`.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timezone
from typing import Any

from oddsmarkets.basketball.sources import markets as hwm
from oddsmarkets.common import prediction_markets as cpm
from oddsmarkets.common.edge import devig as dv

from .. import canon

logger = logging.getLogger(__name__)

POLY_TAG = {"cfb": "cfb", "mbb": "cbb", "wbb": None}
CHAMPION = {"cfb": ("KXNCAAF", r"^NCAA Football: \d{4} National Champion$"),
            "mbb": ("KXMARMAD", r"Men'?s College Basketball (National )?Champion"),
            "wbb": ("KXWMARMAD", r"Women'?s College Basketball (National )?Champion")}
HEISMAN = ("KXHEISMAN", r"Heisman Award Winner|Heisman Trophy Winner")
# conference champions: Kalshi series by ESPN conference abbreviation / short name (lower-case keys)
CONF_SERIES = {
    "cfb": {"sec": "KXNCAAFSEC", "big ten": "KXNCAAFB10", "big10": "KXNCAAFB10", "big 12": "KXNCAAFB12", "big12": "KXNCAAFB12",
            "acc": "KXNCAAFACC", "american": "KXNCAAFAAC", "mountain west": "KXNCAAFMWC", "mwest": "KXNCAAFMWC",
            "mac": "KXNCAAFMAC", "midam": "KXNCAAFMAC", "sun belt": "KXNCAAFSBELT", "belt": "KXNCAAFSBELT",
            "cusa": "KXNCAAFCUSA", "usa": "KXNCAAFCUSA", "pac-12": "KXNCAAFPAC12", "pac12": "KXNCAAFPAC12"},
    "mbb": {"sec": "KXNCAAMBSEC", "big ten": "KXNCAAMBBIG10", "big10": "KXNCAAMBBIG10", "acc": "KXNCAAMBACC",
            "big 12": "KXNCAAMBBIG12", "big12": "KXNCAAMBBIG12", "big east": "KXNCAAMBBIGEAST", "bige": "KXNCAAMBBIGEAST",
            "a-10": "KXNCAAMBA10", "atl10": "KXNCAAMBA10", "american": "KXNCAAMBAMER", "mountain west": "KXNCAAMBMW",
            "mwest": "KXNCAAMBMW", "wcc": "KXNCAAMBWCC", "mvc": "KXNCAAMBMVAL", "cusa": "KXNCAAMBUSA", "usa": "KXNCAAMBUSA",
            "sun belt": "KXNCAAMBSBELT", "belt": "KXNCAAMBSBELT", "mac": "KXNCAAMBMAMER", "midam": "KXNCAAMBMAMER",
            "ivy": "KXNCAAMBIVY", "big sky": "KXNCAAMBBSKY", "bsky": "KXNCAAMBBSKY", "big west": "KXNCAAMBBWEST",
            "bigw": "KXNCAAMBBWEST", "big south": "KXNCAAMBBSOU", "bsou": "KXNCAAMBBSOU", "caa": "KXNCAAMBCAA",
            "col": "KXNCAAMBCAA", "horizon": "KXNCAAMBHL", "hor": "KXNCAAMBHL", "maac": "KXNCAAMBMAA", "meac": "KXNCAAMBMEAC",
            "nec": "KXNCAAMBNEC", "neast": "KXNCAAMBNEC", "ovc": "KXNCAAMBOV", "patriot": "KXNCAAMBPAT", "pat": "KXNCAAMBPAT",
            "socon": "KXNCAAMBSOCON", "south": "KXNCAAMBSOCON", "southland": "KXNCAAMBSLC", "land": "KXNCAAMBSLC",
            "summit": "KXNCAAMBSUM", "summ": "KXNCAAMBSUM", "swac": "KXNCAAMBSWAC", "wac": "KXNCAAMBWAC",
            "asun": "KXNCAAMBASUN", "atlantic sun": "KXNCAAMBASUN", "am. east": "KXNCAAMBAE", "aeast": "KXNCAAMBAE",
            "uac": "KXNCAAMBUAC", "pac-12": "KXNCAAMBPAC12"},
    "wbb": {},
}
PLAYOFF = {"cfb": ("KXNCAAFPLAYOFF", r"^$"), "mbb": ("KXMAKEMARMAD", r"^$"), "wbb": (None, r"^$")}
ROUNDS = {"cfb": {"semis": ("KXNCAAFSF", r"team to make Semis"), "quarters": ("KXNCAAFQF", r"team to make Quarters"),
                  "final": (None, r"Team to Make National Championship")},
          "mbb": {"r32": ("KXMARMADROUND", "R32"), "s16": ("KXMARMADROUND", "R16"), "e8": ("KXMARMADROUND", "R8"),
                  "f4": ("KXMARMADROUND", "F4"), "final": ("KXMARMADROUND", "T2")},
          "wbb": {"r32": ("KXWMARMADROUND", "R32"), "s16": ("KXWMARMADROUND", "R16"), "e8": ("KXWMARMADROUND", "QF"),
                  "f4": ("KXWMARMADROUND", "SEMI"), "final": ("KXWMARMADROUND", "T2")}}
WINS_SERIES = {"cfb": "KXNCAAFWINS", "mbb": "KXNCAAMBWINS", "wbb": "KXNCAAWBWINS"}
GAME_SERIES = {"cfb": "KXNCAAFGAME", "mbb": "KXNCAAMBGAME", "wbb": "KXNCAAWBGAME"}
POLY_GAME_PREFIX = {"cfb": "cfb", "mbb": "cbb", "wbb": "cwbb"}
SPREAD_SD = {"cfb": 15.5, "mbb": 10.5, "wbb": 11.0}     # rough margin sd for a spread-only fallback probability

# indirection so tests can swap the network for canned payloads
kalshi_events = cpm.kalshi_events
polymarket_tag_events = cpm.polymarket_tag_events
_KCACHE: dict[str, tuple[float, list]] = {}
KALSHI_GAP_S = 0.35          # Kalshi answers empty pages when hit too fast: space the series reads
KCACHE_TTL_S = 600


def _kevents(series: str) -> list[dict]:
    """Every event (any status) of a Kalshi series, cached for KCACHE_TTL_S and spaced KALSHI_GAP_S apart."""
    import time
    hit = _KCACHE.get(series)
    if hit and time.monotonic() - hit[0] < KCACHE_TTL_S:
        return hit[1]
    time.sleep(KALSHI_GAP_S)
    evs = kalshi_events(series, status=None) or []
    _KCACHE[series] = (time.monotonic(), evs)
    return evs

ALIASES = {"miami (fl)": "miami", "miami fl": "miami", "miami-fl": "miami", "miami (oh)": "miami (oh)", "ole miss": "ole miss",
           "uconn": "uconn", "connecticut": "uconn", "usc": "usc", "southern california": "usc", "lsu": "lsu", "byu": "byu",
           "smu": "smu", "tcu": "tcu", "ucf": "ucf", "utsa": "utsa", "unlv": "unlv", "uab": "uab", "fiu": "fiu",
           "pitt": "pittsburgh", "nc state": "nc state", "north carolina st": "nc state", "app state": "app state",
           "appalachian st": "app state", "appalachian state": "app state", "umass": "massachusetts",
           "hawaii": "hawai'i", "texas a&m": "texas a&m", "san jose st": "san josé state", "san jose state": "san josé state",
           "mississippi": "ole miss", "university at albany": "ualbany", "albany": "ualbany", "usc upstate": "south carolina upstate",
           "liu": "long island university", "new orleans": "lsu new orleans", "uno": "lsu new orleans"}
_PLACEHOLDER = re.compile(r"^(team |player )?([a-z]{1,2}|p\d+|\d+|other|field)$", re.I)


def _level(level) -> str:
    return canon.level_of(level)


def _load_store(level: str, season: int) -> dict:
    try:
        from oddsmarkets.college import store as cst
        return cst.load(level, season)
    except Exception:  # noqa: BLE001
        return {}


def _fold(s: str) -> str:
    return " ".join(str(s or "").lower().replace("’", "'").replace(".", "").split())


def map_team(label: str | None, teams: dict[str, dict], code: str | None = None) -> str | None:
    """ESPN team id for a market label ("Ohio St.", "Miami (FL)") and/or ticker code, or None when unsure.
    Member teams are preferred over non-members with the same name."""
    if not teams or (not label and not code):
        return None
    members = {t: v for t, v in teams.items() if v.get("member")} or teams
    for pool in (members, teams):
        if label:
            lab = _fold(label)
            lab = ALIASES.get(lab, lab)
            lab2 = re.sub(r"\bst$", "state", lab)
            keys = {lab, lab2}
            hit = [t for t, v in pool.items()
                   if keys & {_fold(v.get("location")), _fold(v.get("short")), _fold(v.get("name")),
                              re.sub(r"\bst$", "state", _fold(v.get("short")))}]
            if len(hit) == 1:
                return hit[0]
            if len(hit) > 1 and code:
                c = str(code).upper()
                h2 = [t for t in hit if str(pool[t].get("abbr") or "").upper() == c]
                if len(h2) == 1:
                    return h2[0]
        if code:
            c = str(code).upper()
            hit = [t for t, v in pool.items() if str(v.get("abbr") or "").upper() == c]
            if len(hit) == 1 and (not label or cpm.name_score(label, pool[hit[0]].get("location") or "") >= 0.6):
                return hit[0]
    if not label:
        return None
    # "Mississippi Rebels", "Miami Hurricanes": a nickname ending the label, the rest naming the school
    lab = _fold(label)
    nick_teams = {t: v for t, v in members.items() if _fold(v.get("nickname")) and lab.endswith(" " + _fold(v.get("nickname")))}
    if nick_teams:
        hit = []
        for t, v in nick_teams.items():
            rest = lab[: -len(_fold(v.get("nickname")))].strip()
            rest = ALIASES.get(rest, rest)
            if rest in {_fold(v.get("location")), _fold(v.get("short")), re.sub(r"\bst$", "state", _fold(v.get("short")))}:
                hit.append(t)
        if len(hit) == 1:
            return hit[0]
        if len(nick_teams) == 1:
            t = next(iter(nick_teams))
            return t if cpm.name_score(label, nick_teams[t].get("name") or "") >= 0.72 else None
        members = nick_teams
    cand: dict[str, set] = {}
    for t, v in members.items():
        for x in (v.get("location"), v.get("short"), v.get("name")):
            if x:
                cand.setdefault(str(x), set()).add(t)
    cand1 = {k: next(iter(v)) for k, v in cand.items() if len(v) == 1}
    best = cpm.best_match(re.sub(r"\bSt\.?$", "State", str(label)), list(cand1))
    return cand1[best] if best else None


def map_player(label: str | None, players: dict[str, dict]) -> str | None:
    """ESPN athlete id for a market's player label. College rosters repeat names (two Jeremiah Smiths), so an
    exact name shared by several athletes is settled by position (QB, RB, WR, TE first: award markets list
    offensive stars), else left unmatched; otherwise Hardwood's matcher."""
    if not label or not players:
        return None
    key = _fold(label)
    exact = [pid for pid, v in players.items() if _fold((v or {}).get("name")) == key]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        skill = [pid for pid in exact if str(players[pid].get("pos") or "").upper() in ("QB", "RB", "WR", "TE")]
        return skill[0] if len(skill) == 1 else None
    return hwm.map_player(label, players)


def _clean_unmatched(t: dict) -> dict:
    if isinstance(t, dict) and t.get("unmatched"):
        t["unmatched"] = [u for u in t["unmatched"] if not _PLACEHOLDER.match(str(u).strip())]
    return t


# ── event selection ─────────────────────────────────────────────────────────

# Kalshi event-ticker years per market kind (surveyed 2026-10-19): cfb champion / Heisman / CFP rounds carry the
# title game's year (KXNCAAF-27 for the 2026 season), cfb conference / playoff / win totals the season's
# (KXNCAAFSEC-26); basketball champion, rounds and conference tournaments the season's (KXMARMAD-27), win totals
# the start year (KXNCAAMBWINS-26 for 2026-27).
YEAR_SHIFT = {"cfb": {"champion": 1, "heisman": 1, "rounds": 1, "conference": 0, "playoff": 0, "wins": 0},
              "mbb": {"champion": 0, "rounds": 0, "conference": 0, "playoff": 0, "wins": -1},
              "wbb": {"champion": 0, "rounds": 0, "conference": 0, "playoff": 0, "wins": -1}}


def _yy(level: str, season: int, kind: str) -> str:
    return f"{(int(season) + YEAR_SHIFT[level].get(kind, 0)) % 100:02d}"


def _open_count(ev: dict) -> int:
    return sum(1 for m in ev.get("markets") or [] if not str(m.get("result") or ""))


def _kalshi_event(series: str | None, level: str, season: int, kind: str, suffix: str = "") -> dict | None:
    """The season's event of a series (ticker ending -<yy><suffix>), only while it has unsettled markets."""
    if not series:
        return None
    yy = _yy(level, season, kind)
    best = None
    for e in _kevents(series):
        t = str(e.get("event_ticker") or "")
        if re.search(rf"-{yy}{re.escape(suffix)}$", t) and _open_count(e):
            if best is None or _open_count(e) > _open_count(best):
                best = e
    return best


def _poly_events(level: str) -> list[dict]:
    tag = POLY_TAG.get(level)
    if not tag:
        return []
    out: list[dict] = []
    for off in range(0, 1000, 100):
        rows = cpm._get(f"{cpm.GAMMA}/events", {"tag_slug": tag, "closed": "false", "limit": 100, "offset": off})
        if not isinstance(rows, list):
            break
        out.extend(rows)
        if len(rows) < 100:
            break
    return out


def _poly_season_ok(ev: dict, level: str, season: int) -> bool:
    title = str(ev.get("title") or "")
    ok = [str(season)] + ([str(season + 1)] if canon.is_football(level) else [f"{season - 1}-{season % 100:02d}"])
    if any(x in title for x in ok):
        return True
    return not re.search(r"\b20\d\d\b", title)


def _poly_find(events: list[dict], pattern: str, level: str, season: int) -> dict | None:
    for ev in events:
        if ev.get("closed"):
            continue
        if re.search(pattern, str(ev.get("title") or ""), re.I) and _poly_season_ok(ev, level, season):
            return ev
    return None


# ── field books (the thin rule) ─────────────────────────────────────────────

BOOK_TOTAL = (0.8, 1.3)      # a usable book's implied total (sum of mids): below = runners missing, above = not a price
BOOK_COMPLETE = 0.9          # a book this full is complete by mass, however few of the field it lists
BOOK_MIN_RUNNERS = 4         # always at least this many runners accounted for; else max(this, half the field) or complete


def book_check(src: dict, field: int) -> dict:
    """One venue's book (its mids already limited to the field): {"quoted","accounted","implied_total","need",
    "usable","reason"}. Usable = live quotes, an implied total within BOOK_TOTAL, and either max(4, half the field)
    runners accounted for (quoted, floor or settled) or at least 4 with a total of BOOK_COMPLETE or more (Kalshi lists
    only the live runners of a conference: 6 of 17 ACC teams on 21 Oct 2026, summing to 0.98)."""
    elim = set(src.get("eliminated") or ())
    mid = {r: p for r, p in (src.get("mid") or {}).items() if r not in elim}
    accounted = set(mid) | set(src.get("floor") or ()) | elim
    total = sum(mid.values())
    need = max(BOOK_MIN_RUNNERS, field // 2)
    lo, hi = BOOK_TOTAL
    reason = None
    if not mid:
        reason = "no live quotes"
    elif total < lo:
        reason = f"implied total {total:.2f} with {len(mid)} of {field} runners quoted (below {lo}: runners missing)"
    elif total > hi:
        reason = f"implied total {total:.2f} (above {hi}: not a price)"
    elif len(accounted) < BOOK_MIN_RUNNERS or (len(accounted) < need and total < BOOK_COMPLETE):
        reason = f"{len(accounted)} of {field} runners accounted for (need {need}, or {BOOK_MIN_RUNNERS} with a total of {BOOK_COMPLETE})"
    return {"quoted": len(mid), "accounted": len(accounted), "implied_total": round(total, 4), "need": need,
            "usable": reason is None, "reason": reason}


def book_fair(mid: dict[str, float]) -> dict[str, float]:
    """De-vig one book: power when overround (the margin sits on the longshots), proportional when underround."""
    ids = [r for r, p in mid.items() if p and 0 < p < 1]
    if not ids:
        return {}
    q = [mid[r] for r in ids]
    method = "power" if sum(q) > 1.0 else "multiplicative"
    fair = dv.devig([1.0 / x for x in q], method)
    return {r: float(f) for r, f in zip(ids, fair)}


def pool_books(fairs: list[dict[str, float]], iters: int = 200, tol: float = 1e-10) -> dict[str, float]:
    """Pool de-vigged books that quote different subsets of the field. A book's prices say how its own runners split
    the mass it covers; the mass of the runners it does not quote comes from the pool. Fixed point of
    p(r) = mean over books of [f_b(r) * (1 - sum of p over the runners b does not quote)] if b quotes r, else p(r).
    One book = itself; books quoting the same runners = the plain mean."""
    fairs = [f for f in fairs if f]
    if not fairs:
        return {}
    runners = sorted({r for f in fairs for r in f})
    p = {r: sum(f[r] for f in fairs if r in f) / sum(1 for f in fairs if r in f) for r in runners}
    z = sum(p.values())
    p = {r: v / z for r, v in p.items()}
    for _ in range(iters):
        new = dict.fromkeys(runners, 0.0)
        for f in fairs:
            out = sum(p[r] for r in runners if r not in f)
            for r in runners:
                new[r] += (f[r] * (1.0 - out) if r in f else p[r]) / len(fairs)
        z = sum(new.values())
        new = {r: v / z for r, v in new.items()}
        done = max(abs(new[r] - p[r]) for r in runners) < tol
        p = new
        if done:
            break
    return p


def assemble(sources: dict[str, dict], ids=None, kind: str = "", markets: dict | None = None) -> dict:
    """
    TITLE (Hardwood's shape): {"available","reason","probs","mid","odds","sources","by_source","floor","eliminated",
    "unmatched","field","quoted","accounted","implied_total","overround","markets","kind"} plus
    "books": {venue: book_check(...)}, "used": [venues pooled] and, when a venue was left out, "note".
    `ids` None = the field is every runner any venue lists. Each venue is judged on its own; only usable books are
    de-vigged and pooled (module docstring). `quoted` / `accounted` / `implied_total` / `mid` describe the pooled
    usable books (every book when none is usable).
    """
    floor, elim, unmatched, winner = set(), set(), [], None
    for src in sources.values():
        floor |= set(src.get("floor") or ())
        elim |= set(src.get("eliminated") or ())
        unmatched += list(src.get("unmatched") or [])
        winner = winner or src.get("winner")
    if ids is None:
        ids = sorted({r for v in sources.values() for r in v.get("mid") or {}} | floor | elim)
    ids = list(ids)
    keep = set(ids)
    floor &= keep
    elim &= keep
    # each venue's book on the field only (a conference market can list a non-member)
    books_in = {k: {"mid": {r: p for r, p in (v.get("mid") or {}).items() if r in keep and r not in elim},
                    "floor": set(v.get("floor") or ()) & keep, "eliminated": set(v.get("eliminated") or ()) & keep}
                for k, v in sources.items()}
    books = {k: book_check(v, len(ids)) for k, v in books_in.items()}
    used = sorted(k for k, b in books.items() if b["usable"])
    raw: dict[str, list[float]] = {}
    for k in used or sorted(sources):
        for r, p in books_in[k]["mid"].items():
            raw.setdefault(r, []).append(p)
    mid = {r: sum(ps) / len(ps) for r, ps in raw.items()}
    floor = floor - set(mid)
    total = sum(mid.values())
    accounted = set(mid) | floor | elim
    by_source = {k: {r: round(p, 4) for r, p in (v.get("mid") or {}).items()} for k, v in sources.items()}
    base = {"kind": kind, "markets": markets or {}, "field": len(ids), "quoted": len(mid), "accounted": len(accounted),
            "implied_total": round(total, 4), "overround": round(total - 1.0, 4), "unmatched": sorted(set(unmatched)),
            "sources": sorted(sources), "by_source": by_source, "eliminated": sorted(elim), "floor": sorted(floor),
            "books": books, "used": used}
    mid_out = {k: round(v, 4) for k, v in mid.items()}
    if winner:
        return {**base, "available": False, "reason": f"settled: {winner} won", "probs": {}, "mid": {}, "winner": winner}
    if not used:
        why = "; ".join(f"{k} {b['reason']}" for k, b in sorted(books.items())) or "no books"
        return {**base, "available": False, "reason": f"thin: {why}", "probs": {}, "mid": mid_out}
    pooled = pool_books([book_fair(books_in[k]["mid"]) for k in used])
    probs = {r: round(f, 5) for r, f in pooled.items()}
    for r in floor | elim:
        probs.setdefault(r, 0.0)
    probs = dict(sorted(probs.items(), key=lambda kv: -kv[1]))
    out = {**base, "available": bool(pooled), "reason": None if pooled else "no quoted runner in the field",
           "probs": probs, "mid": mid_out, "odds": {r: round(1.0 / p, 4) for r, p in mid.items() if p > 0}}
    left = [k for k in sorted(books) if k not in used]
    if left:
        out["note"] = "thin book left out: " + "; ".join(f"{k} {books[k]['reason']}" for k in left)
    return out


# ── public ──────────────────────────────────────────────────────────────────

def _title(level, season, series, pattern, ids, mapper, kind, poly_events, suffix="", ykind="champion") -> dict:
    try:
        sources, mk = {}, {}
        ev = _kalshi_event(series, level, season, ykind, suffix)
        if ev:
            sources["kalshi"] = hwm.parse_kalshi_field(ev, mapper)
            mk["kalshi"] = ev.get("event_ticker")
        pev = _poly_find(poly_events, pattern, level, season) if pattern and pattern != "^$" else None
        if pev:
            sources["polymarket"] = hwm.parse_poly_field(pev, mapper)
            mk["polymarket"] = pev.get("slug")
        if not sources:
            return {"kind": kind, "available": False, "reason": "no market listed", "probs": {}, "sources": [], "by_source": {},
                    "implied_total": None, "books": {}, "used": []}
        return _clean_unmatched(assemble(sources, ids, kind, mk))
    except Exception as exc:  # noqa: BLE001
        logger.info("college title %s %s failed: %s", level, kind, exc)
        return {"kind": kind, "available": False, "reason": f"error: {exc}", "probs": {}}


def _binary(level, season, series, pattern, mapper, kind, poly_events, suffix="", ykind="rounds") -> dict:
    """Per-team yes/no markets ("make the playoff", "reach the Final Four"): {"available","probs","by_source","markets"}."""
    try:
        srcs, mk = {}, {}
        ev = _kalshi_event(series, level, season, ykind, suffix)
        if ev:
            srcs["kalshi"] = hwm.parse_kalshi_field(ev, mapper)
            mk["kalshi"] = ev.get("event_ticker")
        pev = _poly_find(poly_events, pattern, level, season) if pattern and pattern != "^$" else None
        if pev:
            srcs["polymarket"] = hwm.parse_poly_field(pev, mapper)
            mk["polymarket"] = pev.get("slug")
        pooled: dict[str, list] = {}
        for v in srcs.values():
            for t, p in v["mid"].items():
                pooled.setdefault(t, []).append(p)
            for t in v["eliminated"]:
                pooled.setdefault(t, []).append(0.0)
            if v.get("winner"):
                pooled.setdefault(v["winner"], []).append(1.0)
        probs = {t: round(sum(v) / len(v), 4) for t, v in pooled.items()}
        return {"kind": kind, "available": bool(probs), "probs": dict(sorted(probs.items(), key=lambda kv: -kv[1])),
                "markets": mk, "by_source": {k: {t: round(p, 4) for t, p in v["mid"].items()} for k, v in srcs.items()},
                "unmatched": sorted({u for v in srcs.values() for u in v["unmatched"] if not _PLACEHOLDER.match(str(u).strip())})}
    except Exception as exc:  # noqa: BLE001
        return {"kind": kind, "available": False, "reason": f"error: {exc}", "probs": {}}


def win_totals(level: str, season: int, teams: dict) -> dict[str, dict]:
    """{tid: {"line","p_over","ladder","ticker"}} from Kalshi's per-team regular-season win ladders."""
    out = {}
    try:
        yy = _yy(level, season, "wins")
        for ev in _kevents(WINS_SERIES[level]):
            t = str(ev.get("event_ticker") or "")
            m = re.search(rf"-{yy}([A-Z0-9&]+)$", t)
            if not m or not _open_count(ev):
                continue
            label = re.sub(r"\s*\(.*\)$", "", str(ev.get("sub_title") or "")).strip()
            tid = map_team(label, teams, m.group(1))
            lad = hwm.parse_win_ladder(ev)
            if tid and lad and tid not in out:
                out[tid] = {**lad, "ticker": t}
    except Exception as exc:  # noqa: BLE001
        logger.info("college win_totals failed: %s", exc)
    return out


def futures(level: str, season: int | None = None, store: dict | None = None) -> dict:
    """{"level","season","generated_at","champion": TITLE, "conference": {cid: TITLE}, "playoff": {"probs": {tid: p}, ...},
    "rounds": {key: binary}, "final_four": binary | None (basketball), "heisman": TITLE | None (cfb),
    "win_totals": {tid: {"line","p_over","ladder","ticker"}}}. Never raises."""
    lv = _level(level)
    season = int(season or canon.current_season(lv))
    out: dict[str, Any] = {"level": lv, "season": season,
                           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        s = store if store is not None else _load_store(lv, season)
        teams, players = s.get("teams") or {}, s.get("players") or {}

        def tmap(label, code):
            if label and _PLACEHOLDER.match(str(label).strip()):
                return None
            return map_team(label, teams, code)

        pev = _poly_events(lv)
        ser, pat = CHAMPION[lv]
        out["champion"] = _title(lv, season, ser, pat, None, tmap, "champion", pev)
        out["conference"] = {}
        for cid, c in (s.get("conferences") or {}).items():
            keys = [str(c.get(k) or "").lower() for k in ("abbr", "short")]
            series = next((CONF_SERIES[lv][k] for k in keys if k in CONF_SERIES[lv]), None)
            short = str(c.get("short") or "")
            ppat = rf"{lv == 'cfb' and 'NCAA Football' or 'Basketball'} \d{{4}} (american )?{re.escape(short)} Conference: Winner" if short else None
            if lv == "cfb" and short.upper() == "CUSA":
                ppat = r"NCAA Football \d{4} American CUSA Conference: Winner"
            if not series and not ppat:
                continue
            ids = [t for t, v in teams.items() if v.get("conference") == cid and v.get("member")]
            ttl = _title(lv, season, series, ppat, ids or None, tmap, f"conference:{cid}", pev, ykind="conference")
            if ttl.get("available") or ttl.get("sources"):
                out["conference"][cid] = ttl
        pser, ppat = PLAYOFF[lv]
        out["playoff"] = _binary(lv, season, pser, ppat, tmap, "playoff", pev, ykind="playoff")
        out["rounds"] = {}
        for key, (series, x) in ROUNDS[lv].items():
            if canon.is_football(lv):
                out["rounds"][key] = _binary(lv, season, series, x, tmap, key, pev)
            else:
                out["rounds"][key] = _binary(lv, season, series, None, tmap, key, pev, suffix=x)
        if not canon.is_football(lv):
            out["final_four"] = out["rounds"].get("f4")
            out["heisman"] = None
        else:
            hs, hp = HEISMAN

            def pmap(label, code):
                if label and _PLACEHOLDER.match(str(label).strip()):
                    return None
                return map_player(label, players)
            out["heisman"] = _title(lv, season, hs, hp, None, pmap, "heisman", pev, ykind="heisman")
        out["win_totals"] = win_totals(lv, season, teams)
    except Exception as exc:  # noqa: BLE001
        logger.info("college futures %s failed: %s", lv, exc)
        out["error"] = str(exc)
    return out


# ── per game ────────────────────────────────────────────────────────────────

def _local_day(g: dict) -> date | None:
    try:
        from datetime import timedelta
        t = datetime.fromisoformat(str(g.get("date") or "").replace("Z", "+00:00"))
        return (t - timedelta(hours=6)).date()
    except ValueError:
        return None


def spread_to_p(spread_home: float | None, level: str) -> float | None:
    """P(home wins) from a point spread through a normal margin (sd SPREAD_SD[level]); a rough fallback."""
    if spread_home is None:
        return None
    z = -float(spread_home) / SPREAD_SD[_level(level)]
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def game_prices(level: str, d: Any = None, store: dict | None = None, poly_events: list[dict] | None = None) -> dict[str, dict]:
    """{gid: {"home","away","p_home","basis","sources": [{"source","p_home","market"}], "spread_home","total"}} for the
    store's games on US day `d` (+-1 day): mean of Kalshi / Polymarket two-sided mids, else ESPN's DraftKings
    moneyline (de-vigged), else its spread. Never raises."""
    lv = _level(level)
    try:
        d = d if isinstance(d, date) else (date.fromisoformat(str(d)[:10]) if d else datetime.now(timezone.utc).date())
        season = canon.current_season(lv, d)
        s = store if store is not None else _load_store(lv, season)
        teams = s.get("teams") or {}
        cands = [g for g in (s.get("games") or {}).values() if _local_day(g) and abs((_local_day(g) - d).days) <= 1]
        out: dict[str, dict] = {}

        def rec(g):
            gid = str(g["id"])
            if gid not in out:
                o = g.get("odds") or {}
                out[gid] = {"home": str(g["home"]), "away": str(g["away"]), "sources": [], "spread_home": o.get("spread_home"),
                            "total": o.get("total"), "p_home": None}
            return out[gid]

        def match(a, b, ed):
            hit = [g for g in cands if a and b and {str(g["home"]), str(g["away"])} == {a, b}]
            if ed:
                hit = [g for g in hit if _local_day(g) == ed] or hit
            return hit[0] if hit else None

        for ev in _kevents(GAME_SERIES[lv]):
            ed = hwm.kalshi_game_date(ev.get("event_ticker"))
            if not ed or abs((ed - d).days) > 1:
                continue
            q, ids = {}, []
            for m in ev.get("markets") or []:
                tid = map_team(m.get("yes_sub_title"), teams, hwm._ticker_code(m.get("ticker")))
                if tid:
                    ids.append(tid)
                    p = cpm.kalshi_price(m)
                    if p is not None:
                        q[tid] = p
            g = match(*(ids + [None, None])[:2], ed)
            if not g or not q:
                continue
            h, a = str(g["home"]), str(g["away"])
            ph = q[h] / (q[h] + q[a]) if h in q and a in q else (q[h] if h in q else 1.0 - q[a])
            rec(g)["sources"].append({"source": "kalshi", "p_home": round(ph, 4), "market": ev.get("event_ticker")})
        pevs = poly_events if poly_events is not None else _poly_events(lv)
        pre = POLY_GAME_PREFIX[lv]
        for ev in pevs:
            mm = re.fullmatch(rf"{pre}-([a-z0-9]+)-([a-z0-9]+)-(\d{{4}}-\d{{2}}-\d{{2}})", str(ev.get("slug") or ""))
            if not mm or ev.get("closed"):
                continue
            ed = date.fromisoformat(mm.group(3))
            if abs((ed - d).days) > 1:
                continue
            ml = next((m for m in ev.get("markets") or [] if m.get("sportsMarketType") == "moneyline"), None)
            outs = (ml or {}).get("outcomes")
            if isinstance(outs, str):
                try:
                    outs = json.loads(outs)
                except ValueError:
                    outs = None
            if not outs or len(outs) != 2:
                continue
            ta, tb = map_team(outs[0], teams), map_team(outs[1], teams)
            g = match(ta, tb, ed)
            p = cpm.poly_price(ml)
            if not g or p is None:
                continue
            rec(g)["sources"].append({"source": "polymarket", "p_home": round(p if str(g["home"]) == ta else 1.0 - p, 4),
                                      "market": ev.get("slug")})
        for g in cands:
            o = g.get("odds") or {}
            ph, pa = hwm._american_to_p(o.get("ml_home")), hwm._american_to_p(o.get("ml_away"))
            if ph and pa:
                rec(g)["sources"].append({"source": "espn_ml", "p_home": round(ph / (ph + pa), 4), "market": o.get("provider")})
            elif o.get("spread_home") is not None:
                rec(g)["sources"].append({"source": "espn_spread", "p_home": round(spread_to_p(o["spread_home"], lv), 4),
                                          "market": o.get("provider")})
        for r in out.values():
            pm = [x["p_home"] for x in r["sources"] if x["source"] in ("kalshi", "polymarket")]
            ml = [x["p_home"] for x in r["sources"] if x["source"] == "espn_ml"]
            sp = [x["p_home"] for x in r["sources"] if x["source"] == "espn_spread"]
            pick = pm or ml or sp
            r["p_home"] = round(sum(pick) / len(pick), 4) if pick else None
            r["basis"] = "prediction_markets" if pm else ("espn_ml" if ml else ("espn_spread" if sp else None))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("college game_prices failed: %s", exc)
        return {}
