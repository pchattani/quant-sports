"""My Teams for The Quant Green: one follow card per golfer (oddsmarkets/common/follow.py), from the payloads the
build has just written (docs/green/data). No new fetching.

    follow/golfm/<pid>.json    a men's golfer (PGA Tour, DP World Tour, LIV, Korn Ferry: one stream)
    follow/golfw/<pid>.json    a women's golfer (LPGA)

The key is "green:golfm:<pid>" / "green:golfw:<pid>" (docs/green/assets/app/core.js followItem), so the stream is part
of the key. Every player with a page (players/<pid>.json) gets a card, so every star on the site resolves.

A card carries:
    now        our rating and its rank in the stream's ranking; the form line of the last five starts, oldest first:
               W a top-10 finish, D another made cut, L a missed cut or a withdrawal
    chances    this week's event, when the player is in its field: the cut, a top 10 and the win (our pre-event
               chances; live chances from the scores so far once the event is under way)
    next_note  the week in one line
    last       the latest finished event and the finish
    profile    the three strongest and two weakest numbers of the Scouting Room's last two years (percentiles among the
               regulars), when the player has enough rounds for percentiles
    facts      the ranking and rating, the rating's move over 90 days (or a year), the last five finishes, the last 12
               months' wins and top 10s against the rest of the ranking, and our call for this week

No look-ahead: every number is from a payload published by this build (the ranking and ratings walk forward with
nothing after today; the week's chances are pre-event, or live from the rounds already played; results are finished
events only).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SITE, SPORT = "green", "golf"
SCOPE = {"men": "golfm", "women": "golfw"}
LEAGUE = {"men": "Men’s golf", "women": "Women’s golf"}
CENTRE = {"men": "PGA Tour", "women": "LPGA Tour"}
TOUR_NAME = {"pga": "PGA Tour", "eur": "DP World Tour", "liv": "LIV Golf", "lpga": "LPGA Tour", "ntw": "Korn Ferry Tour"}
# the Scouting Room numbers a card's strengths and weaknesses come from (not the rating, form or results themselves)
PROFILE = ("sg_e", "sg_w", "sd", "h3", "h4", "h5", "bird", "bog", "dist", "acc", "gir", "ppg", "sand",
           "c_ott", "c_app", "c_arg", "c_putt")
PCT = {"great", "poor", "bird", "bog", "dbl", "eag", "acc", "gir", "sand", "win", "t10", "cut"}
MISSED = ("cut", "wd", "dq", "mdf", "dns")


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def pct(p) -> str:
    v = _num(p)
    if v is None:
        return ""
    if 0 < v < 0.01:
        return "under 1%"
    if 0.99 < v < 1:
        return "over 99%"
    return f"{round(100 * v)}%"


def finish(e: dict) -> str:
    """'1', 'T4', 'MC' (a missed cut), 'WD' ...: a result row's finish as a leaderboard shows it."""
    st = e.get("st")
    if st == "finish" and _num(e.get("pos")) is not None:
        return ("T" if e.get("tie") else "") + str(int(e["pos"]))
    return {"cut": "MC", "wd": "WD", "dq": "DQ", "mdf": "MDF", "dns": "DNS"}.get(st, "")


def letter(e: dict) -> str | None:
    """The form line's letter (QK.formDots): W a top-10 finish, D another made cut, L a missed cut or worse."""
    st = e.get("st")
    if st == "finish":
        p = _num(e.get("pos"))
        return "W" if p is not None and p <= 10 else "D"
    if st in MISSED:
        return "L"
    return None


def surname(name: str) -> str:
    parts = str(name or "").split()
    if len(parts) >= 2 and parts[-1].rstrip(".").lower() in ("jr", "sr", "ii", "iii", "iv"):
        return " ".join(parts[-2:])
    return parts[-1] if parts else ""


def initials(name: str) -> str:
    return "".join(w[0] for w in str(name or "").split()[:3] if w).upper()


def _fmt(k: str, v) -> str:
    x = _num(v)
    if x is None:
        return ""
    if k in PCT:
        return f"{100 * x:.0f}%"
    if k == "dist":
        return f"{x:.1f} yd"
    if k == "ppg":
        return f"{x:.3f}"
    if k == "sd":
        return f"{x:.2f}"
    return f"{x:+.2f}".replace("-", "−")


def _labels() -> dict:
    try:
        from .analytics import METRICS
        return {k: v[0] for k, v in METRICS.items()}
    except Exception:  # noqa: BLE001 - the labels are cosmetic
        return {}


def week_fields(data: Path, idx: dict) -> dict:
    """{pid: {event, chances, ...}} for every player in this week's fields (index.json week: the live or next event
    per tour), from the event pages written by this build."""
    out: dict = {}
    for w in idx.get("week") or []:
        page = _read(data / "events" / f"{w.get('id')}.json") or {}
        live = w.get("status") == "live" and w.get("key") == "lwin"
        players = page.get("players") or []
        k_win = "lwin" if live else "win"
        ranked = sorted((p for p in players if _num(p.get(k_win)) is not None), key=lambda p: -p[k_win])
        place = {p["pid"]: i + 1 for i, p in enumerate(ranked)}
        for p in players:
            pid = str(p.get("pid") or "")
            if not pid or p.get("st") in MISSED:
                continue
            ch = {"win": _num(p.get(k_win)), "t10": _num(p.get("lt10" if live else "t10")),
                  "cut": None if live else _num(p.get("cut"))}
            prev = out.get(pid)
            if prev and (prev["status"] == "live" or not live):
                continue          # one event a player: a live one first
            out[pid] = {"id": w.get("id"), "name": w.get("name") or page.get("name"), "course": w.get("course"),
                        "start": w.get("start"), "end": w.get("end"), "status": "live" if w.get("status") == "live" else "upcoming",
                        "live": live, "ch": ch, "place": place.get(pid), "field": len(players),
                        "pos": p.get("pos") if live else None, "tie": p.get("tie"), "tp": p.get("tp") if live else None}
    return out


def _day(iso) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return ""
    return f"{d.day} {('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[d.month - 1]}"


def card(P: dict, stream: str, of: int, wk: dict | None, lead: dict, asof: datetime, labels: dict) -> dict:
    """One golfer's card (common/follow.py make_card)."""
    from oddsmarkets.common import follow as FL
    pid, nm = str(P["pid"]), P.get("name") or str(P["pid"])
    who = surname(nm) or nm
    evs = [e for e in (P.get("events") or []) if letter(e)]            # newest first, finished events only
    S = P.get("summary") or {}
    rank = P.get("rank") if P.get("ranked") else None
    rt = _num(P.get("rt"))
    tour = (evs[0].get("tour") if evs else None) or S.get("tour")
    team = {"name": nm, "short": who, "abbr": (str(P.get("cc") or "")[:3].upper() or initials(nm)),
            "href": f"#/player/{pid}", "league": LEAGUE[stream], "group": TOUR_NAME.get(tour or "", "")}
    now: dict = {}
    if rt is not None:
        now["rating"] = {"value": rt, "text": f"{rt:+.2f}".replace("-", "−"), "label": "Our rating"}
        if rank:
            now["rating"].update({"rank": int(rank), "of": of})
    if rank:
        now["standing"] = {"pos": int(rank), "of": of, "text": f"No. {int(rank)} in our {LEAGUE[stream].lower().replace('’s golf', '’s')} ranking"}
    else:
        now["standing"] = {"text": "Not in our ranking: too few recent rounds"}
    form = "".join(letter(e) for e in reversed(evs[:5]))
    if form:
        now["form"] = form

    chances, note = [], None
    if wk:
        c = wk["ch"]
        ev = wk["name"] or "this week’s event"
        if c.get("cut") is not None:
            chances.append({"key": "p_cut", "label": f"{ev} cut", "p": c["cut"]})
        if c.get("t10") is not None:
            chances.append({"key": "p_t10", "label": f"{ev} top 10", "p": c["t10"]})
        if c.get("win") is not None:
            chances.append({"key": "p_win", "label": f"{ev} win", "p": c["win"]})
        bits = [f"a win {pct(c['win'])}" if c.get("win") is not None else "", f"a top 10 {pct(c['t10'])}" if c.get("t10") is not None else "",
                f"making the cut {pct(c['cut'])}" if c.get("cut") is not None else ""]
        bits = [b for b in bits if b]
        where = f" at {wk['course']}" if wk.get("course") else ""
        if wk["live"]:
            p0, tp = _num(wk.get("pos")), _num(wk.get("tp"))
            par = ("level par" if int(tp) == 0 else f"{int(tp):+d}".replace("-", "−")) if tp is not None else ""
            at = ""
            if p0 is not None:
                at = (": leading" if p0 == 1 and not wk.get("tie") else f": {'T' if wk.get('tie') else ''}{int(p0)}") + (f" at {par}" if par else "")
            note = f"Playing the {ev}{where} now{at}. Our chance from here of {', '.join(bits)}." if bits else f"Playing the {ev}{where} now{at}."
        elif wk["status"] == "live":
            note = (f"This week: the {ev}{where}, {_day(wk.get('start'))}–{_day(wk.get('end'))}. Our pre-event chance of {', '.join(bits)}." if bits
                    else f"This week: the {ev}{where}.")
        else:
            note = (f"Next: the {ev}{where}, {_day(wk.get('start'))}–{_day(wk.get('end'))}. Our chance of {', '.join(bits)}." if bits
                    else f"Next: the {ev}{where}, {_day(wk.get('start'))}.")
    else:
        note = "Not in the field of this week’s events in our data."

    last = None
    if evs:
        e = evs[0]
        last = {"id": e.get("id"), "start": e.get("date"), "comp": f"{e.get('name') or 'Last event'} · {finish(e)}",
                "href": f"#/event/{e.get('id')}", "res": letter(e)}

    facts = []
    if rank and rt is not None:
        facts.append({"kind": "rating", "text": f"{who} is No. {int(rank)} in our {LEAGUE[stream].lower().replace('’s golf', '’s')} ranking, "
                                               f"{abs(rt):.2f} strokes a round {'better' if rt >= 0 else 'worse'} than an average {CENTRE[stream]} player."})
    elif rt is not None:
        facts.append({"kind": "rating", "text": f"Our rating for {who}: {abs(rt):.2f} strokes a round {'better' if rt >= 0 else 'worse'} than an average "
                                               f"{CENTRE[stream]} player, not ranked (too few recent rounds)."})
    for key, span in (("d90", "the last 90 days"), ("d365", "a year")):
        d = _num(S.get(key))
        if d is not None and abs(d) >= 0.15:
            facts.append({"kind": "rating_move", "text": f"Our rating is {'up' if d > 0 else 'down'} {abs(d):.2f} strokes a round over {span}."
                          if key == "d90" else f"Our rating is {'up' if d > 0 else 'down'} {abs(d):.2f} strokes a round on a year ago."})
            break
    if evs:
        fin = [finish(e) for e in reversed(evs[:5])]
        facts.append({"kind": "form_xp", "text": f"Last {len(fin)} start{'s' if len(fin) != 1 else ''}, oldest first: {', '.join(fin)} "
                                                 "(on the form line, W is a top 10, D another made cut, L a missed cut)."})
    starts, wins, t10 = int(S.get("starts") or 0), int(S.get("wins") or 0), int(S.get("top10") or 0)
    if starts:
        txt = (f"{wins} win{'s' if wins != 1 else ''} and {t10} top 10{'s' if t10 != 1 else ''} in {starts} start{'s' if starts != 1 else ''} "
               "over the last 12 months")
        if wins and wins >= lead.get("wins", 99):
            txt += f", the most wins of anyone in our {LEAGUE[stream].lower().replace('’s golf', '’s')} ranking"
        elif t10 and t10 >= lead.get("top10", 99):
            txt += f", the most top 10s of anyone in our {LEAGUE[stream].lower().replace('’s golf', '’s')} ranking"
        facts.append({"kind": "year", "text": txt + "."})
    if wk and wk["ch"].get("win") is not None and wk.get("place"):
        pl = int(wk["place"])
        rk = "the favourite" if pl == 1 else f"the {FL.ordinal(pl)} best chance in a field of {wk['field']}"
        facts.append({"kind": "call", "text": f"Our call {'from here ' if wk['live'] else ''}at the {wk['name']}: {pct(wk['ch']['win'])} to win, {rk}."})
    # the call leads in a week the player is in a field; otherwise the ranking does
    if facts and facts[-1]["kind"] == "call":
        facts.insert(0, facts.pop())

    prof = None
    C = P.get("cur") or {}
    if C.get("q") and isinstance(C.get("pc"), dict):
        rows = [(k, C["pc"][k]) for k in PROFILE if _num(C["pc"].get(k)) is not None and k in (C.get("v") or {})]
        if len(rows) >= 5:
            rows.sort(key=lambda r: -r[1])
            mk = lambda k, p: {"id": k, "label": labels.get(k, k), "pct": int(round(p)), "text": _fmt(k, C["v"][k])}
            prof = {"strong": [mk(k, p) for k, p in rows[:3]], "weak": [mk(k, p) for k, p in rows[::-1][:2]]}

    line = f"{wins} win{'s' if wins != 1 else ''}, {t10} top 10{'s' if t10 != 1 else ''} in {starts} starts over 12 months." if starts else None
    return FL.make_card(site=SITE, sport=SPORT, scope=SCOPE[stream], ident=pid, team=team, asof=asof, phase="season",
                        season=asof.year, now=now, chances=chances, next_note=note, last=last, line=line,
                        profile=prof, facts=facts)


def build(data: Path, now: datetime | None = None) -> dict:
    """Write docs/green/data/follow/<scope>/<pid>.json for every player page. -> {scope: write_cards summary}."""
    from oddsmarkets.common import follow as FL
    data = Path(data)
    asof = now or datetime.now(timezone.utc)
    rk = _read(data / "rankings.json") or {}
    idx = _read(data / "index.json") or {}
    of = {s: len(rk.get(s) or []) for s in SCOPE}
    lead = {}
    for s in SCOPE:
        rows = rk.get(s) or []
        lead[s] = {"wins": max([int(r.get("wins") or 0) for r in rows] or [0]) or 99,
                   "top10": max([int(r.get("top10") or 0) for r in rows] or [0]) or 99}
    wk = week_fields(data, idx)
    labels = _labels()
    cards: dict = {s: {} for s in SCOPE}
    for p in sorted((data / "players").glob("*.json")):
        P = _read(p)
        if not P or not P.get("pid") or P.get("stream") not in SCOPE:
            continue
        s = P["stream"]
        try:
            cards[s][str(P["pid"])] = card(P, s, of[s], wk.get(str(P["pid"])), lead[s], asof, labels)
        except Exception as exc:  # noqa: BLE001 - one bad player never stops the rest
            logger.warning("follow card %s: %s", P.get("pid"), exc)
    return {SCOPE[s]: {k: v for k, v in FL.write_cards(data / "follow", SCOPE[s], cards[s]).items() if k != "ids"} for s in SCOPE}
