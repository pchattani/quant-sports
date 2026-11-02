"""My Teams: the follow card, one small JSON per team, and its fact engine. One implementation for every site.

A visitor follows teams (tennis players, F1 drivers and constructors) in the browser only: the kit keeps the list in
localStorage `qk-follow-v1` (docs/_design/quant.js QK.follow), and every site's builder publishes one small, uniform
card per team at docs/<site>/data/follow/<scope>/<id>.json. Home and the sport overviews read only those cards.

    key        "<site>:<scope>:<id>": the site folder (site, bullpen, hardwood, rink, gridiron, campus, ace, paddock),
               a scope inside it (mlb, aaa, nba, club, team, atp, driver ...) and the site's own id
    card       make_card(...) -> dict (the schema below); card_bytes(card); shrink(card); write_cards(dir, scope, cards)
    facts      facts(ctx, asof) -> [{"kind", "text", "score"}]: deterministic templates, no LLM; the top 3-5 with no two
               of the same kind
    helpers    form_letters, streak_of, change_since (a chance's move over N days), upset_flag, ordinal, record_text

The card (v1). Every block is optional except the identity and the freshness; a site fills what it has:

    {"v": 1, "k": "bullpen:mlb:158", "sport": "baseball", "asof": "2026-10-29T17:28Z", "phase": "offseason",
     "season": 2026,
     "team": {"name", "short", "abbr", "colour", "alt", "href" (the site route, "#/mlb/team/158"), "league", "group"},
     "now": {"record": "103–59", "form": "WWLWW" (oldest first, QK.formDots letters), "streak": "W5",
             "standing": {"pos", "of", "group", "text", "gb"}, "rating": {"value", "text", "rank", "of", "label"}},
     "chances": [{"key", "label", "p", "d7"}]   (d7: the change over 7 days from the race logs, None without one)
     "next": [{"id", "start", "home", "opp": {"name", "abbr", "colour", "rank"}, "comp", "p", "p_draw", "mkt",
               "why": [...], "href"}]  (up to 3; p and mkt are our side's chances; with a draw, the kit's "Your week"
               shows a market only from "mkt_home", the home side's own, since 1 - mkt is not the other side's)
     "next_note": "Off-season. The 2027 schedule is not out yet.",
     "last": {"id", "start", "home", "opp", "score": [us, them], "res": "W" | "L" | "D", "p", "upset", "comp", "href"},
     "line": "Won the 2026 World Series, 4–1 over the Rays."   (one plain line on the season so far)
     "profile": {"strong": [{"id", "label", "pct", "text"}] (3), "weak": [...] (2)},
     "facts": [{"kind", "text"}] (3-5),
     "players": [{"name", "pos", "metric", "value", "text", "href"}] (2),
     "champion": {"event", "season", "text"}}

Freshness: `asof` is the build's clock and `phase` (preseason | season | postseason | offseason) tells the front end
not to show stale form as current: an off-season card says so and leads with the champion or how the season ended.

No look-ahead. Every number on a card was published before the moment it describes: a finished game carries the
pre-game chance frozen before its start, a 7-day change compares two snapshots of the race log taken on those days,
and the fact engine drops any dated input after `asof` (a result, a log point, a "next" game already started).

Size: a card targets 2-4 KB; MAX_BYTES (8 KB) is the hard ceiling. shrink() trims the optional blocks in a fixed
order until a card fits, and write_cards() refuses to write one that still does not.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

V = 1
MAX_BYTES = 8192
TARGET_BYTES = 4096
PHASES = ("preseason", "season", "postseason", "offseason")
MAX_NEXT = 3
MAX_FACTS = 5
MIN_FACTS = 3
MAX_PLAYERS = 2
UPSET_P = 0.4          # digest.upset's rule: a win we gave 40% or less is an upset
DASH = "–"


# ───────────────────────────────────────────────────────────── small helpers
def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _dt(x) -> datetime | None:
    """ISO 8601 / date / datetime -> aware UTC datetime (a bare date is noon UTC, so a date-only result counts on its
    own day); None when unreadable."""
    if x is None:
        return None
    if isinstance(x, datetime):
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    if isinstance(x, date):
        return datetime(x.year, x.month, x.day, 12, tzinfo=timezone.utc)
    s = str(x).strip()
    if not s:
        return None
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s).replace(hour=12, tzinfo=timezone.utc)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def iso_min(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def ordinal(n) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }".replace(" ", "")


def record_text(w, l, d=None, otl=None) -> str | None:
    if _num(w) is None or _num(l) is None:
        return None
    parts = [str(int(w)), str(int(l))]
    for x in (d, otl):
        if _num(x) is not None and x:
            parts.append(str(int(x)))
    return DASH.join(parts)


def pct_text(p) -> str:
    p = _num(p)
    if p is None:
        return ""
    v = p * 100
    if 0 < v < 1:
        return "<1%"
    if 99 < v < 100:
        return ">99%"
    return f"{v:.0f}%"


def card_key(site: str, scope: str, ident) -> str:
    return f"{site}:{scope}:{ident}"


# ───────────────────────────────────────────────────────────── form, streaks, changes
def _results(results: Iterable[dict] | None, asof) -> list[dict]:
    """Finished results dated at or before `asof`, oldest first. A result is {"date" or "start", "res": "W" | "L" |
    "D" | "O" (an overtime loss), ...}; anything without a result letter is skipped."""
    a = _dt(asof)
    out = []
    for r in results or []:
        t = _dt(r.get("start") or r.get("date"))
        res = str(r.get("res") or "").upper()[:1]
        if t is None or res not in ("W", "L", "D", "O") or (a is not None and t > a):
            continue
        out.append(dict(r, _t=t, res=res))
    out.sort(key=lambda r: r["_t"])
    return out


def form_letters(results: Iterable[dict] | None, asof, n: int = 5) -> str:
    """The last n results at `asof`, oldest first ('WWLWD'); an overtime loss is 'O' (QK.formDots draws it as a loss
    of its own colour)."""
    return "".join(r["res"] for r in _results(results, asof)[-n:])


def streak_of(results: Iterable[dict] | None, asof) -> tuple[str, int] | None:
    """('W', 6): the current run of the same result at `asof` (an overtime loss counts as a loss); None without results."""
    rs = _results(results, asof)
    if not rs:
        return None
    norm = lambda x: "L" if x == "O" else x       # noqa: E731
    last = norm(rs[-1]["res"])
    n = 0
    for r in reversed(rs):
        if norm(r["res"]) != last:
            break
        n += 1
    return last, n


def longest_run(results: Iterable[dict] | None, asof, kind: str = "W") -> int:
    best = cur = 0
    for r in _results(results, asof):
        cur = cur + 1 if (("L" if r["res"] == "O" else r["res"]) == kind) else 0
        best = max(best, cur)
    return best


def change_since(series: Iterable | None, asof, days: int = 7) -> float | None:
    """The change in a chance over the last `days` days at `asof`: the latest point at or before asof against the
    latest point at or before asof - days. series: [[iso_or_date, p], ...] or {"YYYY-MM-DD": p}. None without both."""
    a = _dt(asof)
    if a is None:
        return None
    items = series.items() if isinstance(series, dict) else (series or [])
    pts = []
    for ts, p in items:
        t, p = _dt(ts), _num(p)
        if t is not None and p is not None and t <= a:
            pts.append((t, p))
    if not pts:
        return None
    pts.sort()
    lo = a - timedelta(days=days)
    base = [x for x in pts if x[0] <= lo]
    if not base:
        return None
    return round(pts[-1][1] - base[-1][1], 4)


def upset_flag(p_pre, res) -> bool:
    p = _num(p_pre)
    return p is not None and str(res).upper()[:1] == "W" and p <= UPSET_P + 1e-9


# ───────────────────────────────────────────────────────────── the card
def _clean(x):
    """Drop None, empty strings, lists and dicts (recursively); round floats to 4 places."""
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            v = _clean(v)
            if v is None or v == "" or v == [] or v == {}:
                continue
            out[k] = v
        return out
    if isinstance(x, (list, tuple)):
        return [y for y in (_clean(v) for v in x) if y is not None and y != "" and y != {}]
    if isinstance(x, float):
        return None if math.isnan(x) or math.isinf(x) else round(x, 4)
    return x


def make_card(*, site: str, sport: str, scope: str, ident, team: dict, asof, phase: str, season=None,
              now: dict | None = None, chances: list | None = None, next_games: list | None = None,
              next_note: str | None = None, last: dict | None = None, line: str | None = None,
              profile: dict | None = None, facts: list | None = None, players: list | None = None,
              champion: dict | None = None) -> dict:
    """A follow card (the module docstring's schema), cleaned of empty fields and capped: up to 3 next games, 5
    facts, 2 players, 3 strengths and 2 weaknesses, the last 5 form letters."""
    if phase not in PHASES:
        raise ValueError(f"phase {phase!r} is not one of {PHASES}")
    a = _dt(asof)
    if a is None:
        raise ValueError("asof is required")
    if not team or not team.get("name"):
        raise ValueError("team.name is required")
    nw = dict(now or {})
    if nw.get("form"):
        nw["form"] = str(nw["form"])[-5:]
    prof = None
    if profile:
        prof = {"strong": list(profile.get("strong") or [])[:3], "weak": list(profile.get("weak") or [])[:2]}
    card = {
        "v": V, "k": card_key(site, scope, ident), "sport": sport, "asof": iso_min(a), "phase": phase, "season": season,
        "team": team, "now": nw, "chances": chances, "next": list(next_games or [])[:MAX_NEXT], "next_note": next_note,
        "last": last, "line": line, "profile": prof,
        "facts": [{"kind": f["kind"], "text": f["text"]} for f in (facts or [])][:MAX_FACTS],
        "players": list(players or [])[:MAX_PLAYERS], "champion": champion,
    }
    out = _clean(card)
    out["team"] = _clean(team)
    return out


def card_bytes(card: dict) -> int:
    return len(json.dumps(card, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


SHRINK_ORDER = (
    ("next", "why"), ("profile", "weak"), ("facts", 4), ("next", 2), ("players", 1), ("facts", 3), ("profile", "strong"),
    ("next", 1), ("players", 0), ("last", None), ("profile", None),
)


def shrink(card: dict, limit: int = MAX_BYTES) -> dict:
    """Trim the optional blocks in a fixed order until the card fits `limit` bytes (a copy; the input is kept)."""
    c = json.loads(json.dumps(card))
    for key, how in SHRINK_ORDER:
        if card_bytes(c) <= limit:
            break
        v = c.get(key)
        if v is None:
            continue
        if how is None:
            c.pop(key, None)
        elif how == "why" and isinstance(v, list):
            for g in v:
                g.pop("why", None)
        elif isinstance(how, int) and isinstance(v, list):
            c[key] = v[:how]
        elif isinstance(how, str) and isinstance(v, dict):
            v.pop(how, None)
    return c


def write_cards(out_dir: Path, scope: str, cards: dict, prune: bool = True) -> dict:
    """Write {id: card} to out_dir/<scope>/<id>.json (compact JSON). With prune, a card file of the scope whose id is
    not in `cards` is removed (a team that left the league). Returns {"n", "bytes", "max", "ids"}; raises ValueError
    for a card that still exceeds MAX_BYTES after shrink()."""
    d = Path(out_dir) / scope
    d.mkdir(parents=True, exist_ok=True)
    total, mx, ids = 0, 0, []
    for ident, card in cards.items():
        c = shrink(card)
        n = card_bytes(c)
        if n > MAX_BYTES:
            raise ValueError(f"follow card {scope}/{ident} is {n} bytes, over {MAX_BYTES}")
        text = json.dumps(c, ensure_ascii=False, separators=(",", ":"))
        p = d / f"{ident}.json"
        if not p.exists() or p.read_text(encoding="utf-8") != text:
            p.write_text(text, encoding="utf-8")
        total += n
        mx = max(mx, n)
        ids.append(str(ident))
    if prune:
        keep = {f"{i}.json" for i in ids}
        for p in d.glob("*.json"):
            if p.name not in keep:
                p.unlink()
    return {"n": len(ids), "bytes": total, "max": mx, "ids": sorted(ids)}


# ───────────────────────────────────────────────────────────── the fact engine
# Score scale (rough): 90+ a title or a record; 60-80 a big, current story; 40-60 a solid line; under 30 filler.
# The engine keeps the best MAX_FACTS with no two of the same kind, and drops lines under MIN_SCORE.
MIN_SCORE = 20
# recent-form kinds describe the moment; in the off-season they are stale, so they are left out
LIVE_KINDS = {"streak", "form_xp", "swing", "clinch", "big_game", "rivalry", "player_run", "rating_move"}
KINDS = ("champion", "franchise", "streak", "rating_move", "vs_last", "split", "best_start", "pctl", "best_record",
         "sos", "form_xp", "luck", "swing", "clinch", "big_game", "rivalry", "player_rank", "player_run", "call", "rating")


def _who(ctx: dict) -> str:
    """The subject: 'The Brewers' (a team: ctx["the"] true), 'Sinner' (a player or driver)."""
    nm = ctx.get("short") or ctx.get("name") or "They"
    return ("The " + nm) if ctx.get("the", True) else nm


def _f_streak(ctx, asof, out):
    s = streak_of(ctx.get("results"), asof)
    if not s:
        return
    kind, n = s
    if kind not in ("W", "L") or n < 3:
        return
    who = _who(ctx)
    hist = [h for h in (ctx.get("streak_history") or []) if h.get("kind", "W") == kind and _num(h.get("n")) is not None]
    since = None
    for h in sorted(hist, key=lambda h: -int(h.get("season") or 0)):
        if int(h["n"]) >= n:
            since = h.get("season")
            break
    word = "won" if kind == "W" else "lost"
    tail = f", their longest since {since}" if since and hist else (", their longest run this season" if longest_run(ctx.get("results"), asof, kind) == n and n >= 4 else "")
    base = (12 if kind == "W" else 10) * min(n, 8)
    out.append({"kind": "streak", "score": base + (10 if tail else 0), "text": f"{who} have {word} {n} in a row{tail}."})


def _f_form_xp(ctx, asof, out, n: int = 10):
    rs = [r for r in _results(ctx.get("results"), asof) if _num(r.get("p")) is not None and r["res"] in ("W", "L", "O", "D")][-n:]
    if len(rs) < n:
        return
    won = sum(1 for r in rs if r["res"] == "W")
    xp = sum(float(r["p"]) for r in rs)
    d = won - xp
    if abs(d) < 2:
        return
    who = _who(ctx)
    text = (f"{who} have won {won} of their last {n}, when our pre-game chances added up to {xp:.1f}." if d > 0 else
            f"{who} have won {won} of their last {n}; our pre-game chances added up to {xp:.1f}.")
    out.append({"kind": "form_xp", "score": 22 + 9 * abs(d), "text": text})


def _f_rating_move(ctx, asof, out, days: int = 30):
    a = _dt(asof)
    pts = sorted((t, int(r)) for t, r in ((_dt(x[0]), x[1]) for x in ctx.get("rating_ranks") or [])
                 if t is not None and _num(r) is not None and t <= a)
    if len(pts) < 2:
        return
    base = [p for p in pts if p[0] <= a - timedelta(days=days)]
    if not base:
        return
    d = base[-1][1] - pts[-1][1]          # rank 1 is best: a fall in rank number is a climb
    if abs(d) < 3:
        return
    who = _who(ctx)
    text = f"{who} are up {d} places in our ratings this month, to {ordinal(pts[-1][1])}." if d > 0 else \
        f"{who} are down {-d} places in our ratings this month, to {ordinal(pts[-1][1])}."
    out.append({"kind": "rating_move", "score": 30 + 4 * abs(d), "text": text})


def _f_vs_last(ctx, asof, out):
    v = ctx.get("vs_last") or {}
    now, last = v.get("now"), v.get("last")
    if not now or not last:
        return
    dw = (now[0] - now[1]) - (last[0] - last[1])
    if abs(dw) < 4:
        return
    who = _who(ctx)
    at = "" if v.get("full") else " at this point"
    s = v.get("season_last")
    better = dw > 0
    same_len = abs((now[0] + now[1]) - (last[0] + last[1])) <= 1
    gap = abs(int(now[0]) - int(last[0])) if v.get("full") and same_len else None
    if v.get("full") and gap:
        text = f"{who} won {gap} {'more' if now[0] > last[0] else 'fewer'} games than in {s} ({record_text(*last)})."
    else:
        text = (f"{who} finished {record_text(*now)}, against {record_text(*last)} in {s}." if v.get("full") else
                f"{who} are {record_text(*now)}{at}, against {record_text(*last)} in {s}.")
    out.append({"kind": "vs_last", "score": 24 + 2.5 * min(abs(dw), 20) + (6 if better else 0), "text": text})


def _f_split(ctx, asof, out):
    """The home or road record near the top or the bottom of the league (ranks 1-3, or the bottom three)."""
    sp = ctx.get("split") or {}
    of = sp.get("of")
    best = None
    for side, word in (("home", "at home"), ("away", "on the road")):
        x = sp.get(side) or {}
        rk = x.get("rank")
        if rk is None or not of or of < 6 or not x.get("record"):
            continue
        if rk <= 3:
            sc = {1: 46, 2: 34, 3: 26}[rk]
        elif rk >= of - 2:
            sc = {0: 34, 1: 24, 2: 20}[of - rk]
        else:
            continue
        if best is None or sc > best[0]:
            pl = _place(rk, of, bool(x.get("tied")))
            pl = pl if pl.startswith(("the ", "joint-")) or pl.endswith("-worst") else pl + "-best"
            best = (sc, f"{_who(ctx)} {'had' if ctx.get('final') else 'have'} {'the ' if not pl.startswith(('the ', 'joint-')) else ''}{pl} record {word} in {sp.get('league', 'the league')}: {x['record']}.")
    if best:
        out.append({"kind": "split", "score": best[0], "text": best[1]})


def _f_best_start(ctx, asof, out):
    b = ctx.get("best_start") or {}
    if not b.get("record") or not b.get("since"):
        return
    who = _who(ctx)
    out.append({"kind": "best_start", "score": 62, "text": f"{who}{chr(39) if who.endswith('s') else chr(39) + 's'} {b['record']} start is their best since {b['since']}."})


def label_case(label: str) -> str:
    """'Strikeout rate' -> 'strikeout rate' inside a sentence; 'BaseRuns win%', 'Lineup wOBA' and 'xwOBA+' keep their case
    where the first word carries its own capitals."""
    w = str(label or "").split(" ")
    if w and len(w[0]) > 1 and w[0][1:].islower() and w[0][0].isupper():
        w[0] = w[0][0].lower() + w[0][1:]
    return " ".join(w)


def _place(rk: int, of: int, tied: bool = False) -> str:
    """'the best', 'joint-best', '3rd', 'joint 3rd', 'the worst', '2nd-worst'."""
    if rk <= of / 2:
        if rk == 1:
            return "joint-best" if tied else "the best"
        return ("joint " if tied else "") + ordinal(rk)
    k = of - rk + 1
    if k == 1:
        return "joint-worst" if tied else "the worst"
    return ("joint " if tied else "") + ordinal(k) + "-worst"


def _f_pctl(ctx, asof, out):
    """A league rank on a team metric near the top or the bottom: 'The best team rating in MLB (+1.64)', '3rd-best
    barrel rate in MLB (9.1%)'. m["rank"] is 1 for the best (the builder ranks in the metric's direction)."""
    best = None
    where = ctx.get("league_name") or "the league"
    for m in ctx.get("pctl") or []:
        rk, of = m.get("rank"), m.get("of")
        if not rk or not of or of < 6:
            continue
        top, bottom = rk <= 5, rk >= of - 2 and m.get("show_worst", True)
        if not (top or bottom):
            continue
        sc = {1: 58, 2: 46, 3: 36, 4: 30, 5: 26}.get(rk, 0) if top else {0: 34, 1: 26, 2: 22}.get(of - rk, 0)
        if m.get("model"):
            sc += 4
        if best is None or sc > best[0]:
            val = f" ({m['text']})" if m.get("text") else ""
            pl = _place(rk, of, bool(m.get("tied")))
            if pl.endswith("-best") or pl.endswith("-worst") or pl.startswith("the "):
                txt = f"{pl[0].upper()}{pl[1:]} {label_case(m['label'])} in {where}{val}."
            else:
                txt = f"{pl[0].upper()}{pl[1:]}-best {label_case(m['label'])} in {where}{val}."
            best = (sc, txt)
    if best:
        out.append({"kind": "pctl", "score": best[0], "text": best[1]})


def _f_best_record(ctx, asof, out):
    """{"record", "scope": "league" | "group", "where", "rank" (default 1)}: the best (or 2nd-best) record."""
    b = ctx.get("best_record") or {}
    if not b.get("record"):
        return
    had = "had" if ctx.get("final") else "have"
    rk = int(b.get("rank") or 1)
    where = b.get("where", "the league") if b.get("scope") == "league" else f"the {b.get('where')}"
    if rk == 1:
        sc = 64 if b.get("scope") == "league" else 44
        out.append({"kind": "best_record", "score": sc, "text": f"{_who(ctx)} {had} the best record in {where}: {b['record']}."})
    elif rk == 2 and b.get("scope") == "league":
        out.append({"kind": "best_record", "score": 40, "text": f"{_who(ctx)} {had} the 2nd-best record in {where}: {b['record']}."})


def _f_sos(ctx, asof, out):
    s = ctx.get("sos") or {}
    rk, of = s.get("rank"), s.get("of")
    if not rk or not of or not s.get("left"):
        return
    if rk <= 2:
        out.append({"kind": "sos", "score": 40 - 4 * (rk - 1), "text": f"{'The toughest' if rk == 1 else 'The 2nd-toughest'} schedule left in {s.get('where', 'the league')}: {s['left']} games against an average opponent rated {s.get('text', '')}.".replace(" rated .", ".")})
    elif rk >= of - 1:
        out.append({"kind": "sos", "score": 36 - 4 * (of - rk), "text": f"{'The easiest' if rk == of else 'The 2nd-easiest'} schedule left in {s.get('where', 'the league')}: {s['left']} games to go."})


def _f_luck(ctx, asof, out):
    lk = ctx.get("luck") or {}
    d = _num(lk.get("d"))
    if d is None or abs(d) < 3:
        return
    who = _who(ctx)
    had = "won" if ctx.get("final") else "have won"
    n = abs(round(d))
    noun = "game" if n == 1 else "games"
    basis = lk.get("basis", "their play deserved")
    text = f"{who} {had} {n} more {noun} than {basis}." if d > 0 else f"{who} {had} {n} fewer {noun} than {basis}."
    out.append({"kind": "luck", "score": 24 + 4 * min(abs(d), 8), "text": text})


def _f_swing(ctx, asof, out):
    best = None
    for c in ctx.get("chances") or []:
        d = change_since(c.get("series"), asof, 7)
        p = None
        a = _dt(asof)
        pts = sorted((t, q) for t, q in ((_dt(x[0]), _num(x[1])) for x in (c.get("series").items() if isinstance(c.get("series"), dict) else c.get("series") or []))
                     if t is not None and q is not None and t <= a)
        if pts:
            p = pts[-1][1]
        if d is None or p is None or abs(d) < 0.05:
            continue
        if best is None or abs(d) > abs(best[0]):
            best = (d, p, c.get("label") or "title")
    if best:
        d, p, lab = best
        up = d > 0
        # the first letter up, the rest as given ("Stanley Cup", not str.capitalize()'s "Stanley cup")
        text = f"{lab[:1].upper() + lab[1:]} chance {'up' if up else 'down'} {round(abs(d) * 100)} points to {pct_text(p)} this week."
        out.append({"kind": "swing", "score": 34 + 90 * min(abs(d), 0.4), "text": text})


def _f_clinch(ctx, asof, out):
    c = ctx.get("clinch") or {}
    if c.get("magic"):
        n = int(c["magic"])
        out.append({"kind": "clinch", "score": 70 - 3 * min(n, 10), "text": f"Magic number {n} for {c.get('what', 'the division')}."})
    elif c.get("clinched"):
        out.append({"kind": "clinch", "score": 66, "text": f"{_who(ctx)} have clinched {c['clinched']}."})
    elif c.get("eliminated"):
        out.append({"kind": "clinch", "score": 40, "text": f"{_who(ctx)} are out of {c['eliminated']}: no simulation gets them there."})


def _f_next(ctx, asof, out):
    g = ctx.get("next") or {}
    a = _dt(asof)
    t = _dt(g.get("start"))
    if not g or t is None or (a is not None and t <= a):
        return                                    # a next game already started is not "next"
    opp = g.get("opp") or {}
    on = opp.get("short") or opp.get("name") or opp.get("abbr") or "them"
    if g.get("rivalry"):
        out.append({"kind": "rivalry", "score": 58, "text": f"Next up: {g['rivalry']}, against the {on}" + (f"; our chance {pct_text(g['p'])}." if _num(g.get("p")) is not None else ".")})
    score = _num(g.get("score"))
    if score is not None and score >= 45 and g.get("reasons"):
        why = str(g["reasons"][0])
        out.append({"kind": "big_game", "score": min(80, score), "text": f"Big one next: {why}, against the {on}" + (f". Our chance {pct_text(g['p'])}." if _num(g.get("p")) is not None else ".")})


def _f_player_rank(ctx, asof, out):
    best = None
    for p in ctx.get("players") or []:
        rk, of = p.get("rank"), p.get("of")
        if not rk or not of:
            continue
        if rk > 20:
            continue
        sc = max(MIN_SCORE + 2, 60 - 4 * (rk - 1))
        if best is None or sc > best[0]:
            pool = p.get("pool") or "the league"
            pl = _place(rk, max(of, 2 * rk), bool(p.get("tied")))
            best = (sc - (4 if p.get("tied") else 0), f"{p['name']}'s {p['text']} {p.get('metric', '')} {'was' if ctx.get('final') else 'is'} {pl} among {pool}.".replace("  ", " "))
    if best:
        out.append({"kind": "player_rank", "score": best[0], "text": best[1]})


def _f_player_run(ctx, asof, out):
    a = _dt(asof)
    for p in ctx.get("player_runs") or []:
        t = _dt(p.get("asof") or p.get("last"))
        if t is None or (a is not None and t > a) or not p.get("text"):
            continue
        out.append({"kind": "player_run", "score": 42, "text": p["text"]})
        return


def _f_champion(ctx, asof, out):
    c = ctx.get("champion") or {}
    if not c.get("event"):
        return
    res = c.get("result")
    opp = c.get("opp")
    how = f", {res[0]}{DASH}{res[1]} over the {opp}" if res and opp else (f" over the {opp}" if opp else "")
    out.append({"kind": "champion", "score": 100, "text": f"{c.get('season', '')} {c['event']} champions{how}.".strip()})
    if c.get("first_title"):
        yrs = c.get("seasons")
        out.append({"kind": "franchise", "score": 95, "text": f"The first {c['event']} title in franchise history" + (f", in their {ordinal(yrs)} season." if yrs else ".")})
    elif c.get("since"):
        out.append({"kind": "franchise", "score": 90, "text": f"Their first {c['event']} title since {c['since']}."})
    if _num(c.get("pre_p")) is not None:
        rk, n = c.get("pre_rank"), c.get("pre_n")
        tail = f", the best of the {n}" if rk == 1 and n else (f", {ordinal(rk)} of the {n}" if rk and n else "")
        out.append({"kind": "call", "score": 52, "text": f"We gave them {pct_text(c['pre_p'])} to win it before the postseason{tail}."})


def _f_franchise(ctx, asof, out):
    """The best winning percentage in franchise history: {"pct", "record", "best_pct", "best_season", "final"} (the
    franchise's best is from the seasons before this one)."""
    fr = ctx.get("franchise") or {}
    pc, bp = _num(fr.get("pct")), _num(fr.get("best_pct"))
    if pc is None or bp is None or not fr.get("final"):
        return
    rec = f" ({fr['record']})" if fr.get("record") else ""
    if pc > bp + 1e-9:
        out.append({"kind": "franchise", "score": 86, "text": f"The best record in franchise history{rec}; the old best was {fr.get('best_record') or f'{bp:.3f}'} in {fr.get('best_season')}."})


def _f_rating(ctx, asof, out):
    """Where our ratings place the team: always available, so it fills a card that has little else."""
    r = ctx.get("rating") or {}
    rk, of = r.get("rank"), r.get("of")
    if not rk or not of:
        return
    sc = 50 if rk == 1 else max(MIN_SCORE + 1, 34 - 1.5 * (rk - 1)) if rk <= of / 2 else MIN_SCORE + 1
    word = "rank" if not ctx.get("final") else "ranked"
    val = f" ({r['text']}{' ' + r['unit'] if r.get('unit') else ''})" if r.get("text") else ""
    who = _who(ctx)
    out.append({"kind": "rating", "score": sc, "text": f"{who} {word if word == 'ranked' else 'rank'} {ordinal(rk)} of {of} in our team ratings{val}."})


FACT_FUNCS = (_f_champion, _f_franchise, _f_streak, _f_form_xp, _f_rating_move, _f_vs_last, _f_split, _f_best_start,
              _f_pctl, _f_best_record, _f_sos, _f_luck, _f_swing, _f_clinch, _f_next, _f_player_rank, _f_player_run, _f_rating)


def candidates(ctx: dict, asof) -> list[dict]:
    """Every fact the context supports at `asof`, unranked: [{"kind", "text", "score"}]."""
    out: list[dict] = []
    for f in FACT_FUNCS:
        f(ctx, asof, out)
    if ctx.get("phase") == "offseason":
        out = [c for c in out if c["kind"] not in LIVE_KINDS]
    return out


def facts(ctx: dict, asof, limit: int = MAX_FACTS, min_score: float = MIN_SCORE) -> list[dict]:
    """The top `limit` facts at `asof`, best first, no two of the same kind and no repeated text.

    ctx (every key optional): name, short, the (bool: 'The Brewers' v 'Sinner'), phase, final (the season is over:
    past tense), league_name; results [{"date"/"start", "res", "p"}]; streak_history [{"season", "kind", "n"}];
    rating_ranks [[date, rank]]; vs_last {"now": [w, l], "last": [w, l], "season_last", "full"}; split {"home":
    {"record", "rank"}, "away": ..., "of", "league"}; best_start {"record", "since"}; pctl [{"label", "rank", "of",
    "text", "model"}]; best_record {"record", "scope": "league" | "group", "where"}; sos {"rank", "of", "left",
    "where", "text"}; luck {"d", "unit", "basis"}; chances [{"label", "series"}]; clinch {"magic", "what"} |
    {"clinched"} | {"eliminated"}; next {"start", "opp", "p", "score", "reasons", "rivalry"}; players [{"name", "text",
    "metric", "rank", "of", "pool"}]; player_runs [{"text", "asof"}]; champion {"event", "season", "result", "opp",
    "first_title", "seasons", "since", "pre_p", "pre_rank", "pre_n"}; franchise {"pct", "record", "best_pct", "best_record", "best_season",
    "final"}; rating {"rank", "of", "text", "unit"}."""
    seen_kind, seen_text, out = set(), set(), []
    for c in sorted(candidates(ctx, asof), key=lambda c: (-c["score"], KINDS.index(c["kind"]) if c["kind"] in KINDS else 99)):
        if c["score"] < min_score or c["kind"] in seen_kind:
            continue
        t = " ".join(c["text"].split()).strip()
        if t.lower() in seen_text:
            continue
        seen_kind.add(c["kind"])
        seen_text.add(t.lower())
        out.append({"kind": c["kind"], "text": t, "score": round(c["score"], 1)})
        if len(out) >= limit:
            break
    return out


def rivalry(a_short: str | None, b_short: str | None) -> str | None:
    """The rivalry name for two sides (featured.RIVALRIES, by the names the sites print), else None."""
    from oddsmarkets.common import featured as FT
    if not a_short or not b_short:
        return None
    return FT.RIVALRIES.get(frozenset((a_short, b_short)))
