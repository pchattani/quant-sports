"""
ATP Challenger main-draw singles results from English Wikipedia (CC BY-SA 4.0; facts credited to "Wikipedia
contributors"). Terms, robots.txt and the reading behind this source: docs/research/data_sources.md.

Two kinds of page, both plain article pages (`/wiki/<title>`: robots.txt welcomes low-speed bots on article pages and
disallows /w/ and /api/, so neither the Action API nor the REST API is used):

  /wiki/<year>_ATP_Challenger_Tour      the season calendar: one wikitable per month, rows grouped by "Week of"
                                        (the Monday), each tournament cell holding the event link, the city and
                                        country, "Hard – $75,000+H – 32S/32Q/16D" and a link to its Singles page
  /wiki/<year>_<Event>_–_Singles        the draw: Parsoid HTML keeps every bracket template's parameters as JSON
                                        in `data-mw` (RD1-team01, RD1-score01-1 ...), so the draw is read from the
                                        template's own wikitext, not from the rendered table

`parse_season(html, year)` -> [{"title", "week", "surface", "indoor", "city", "country", "singles"}];
`parse_draw(html)` -> [{"round", "a", "b", "winner", "sets", "status", "seeds"}] with the round labelled from the
end of the draw (F, SF, QF, R16, R32, R64) and each match once (the half brackets repeat the semi-finals that the
"Finals" bracket shows). Names are the link targets ("Daniel Rincón (tennis)" -> "Daniel Rincón"), or the plain text
for players without an article.

Dates. Wikipedia gives the week, not the day. `round_day` dates a match on or after the day it was most likely
played: final on the Sunday (Monday + 6), semi-final + 5, quarter-final + 4, second round + 3, first round + 2
(+ 1 for a sixth round). Challenger first rounds are played Monday to Tuesday, so a match is never dated before it
happened except when rain pushes a round past its usual day; that only delays a result the rating could have used.

Every page is fetched once through the paced client (`sources/_client.py`, at least `INTERVAL` seconds apart) and
cached under data/tennis/wiki/ (git-ignored); a finished season is never fetched again.
"""
from __future__ import annotations

import html as _html
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from .. import canon
from ._client import Client

BASE = "https://en.wikipedia.org/wiki/"
INTERVAL = 1.5
LICENSE = {"name": "Wikipedia", "url": "https://en.wikipedia.org/", "license": "CC BY-SA 4.0",
           "attribution": "ATP Challenger results: Wikipedia contributors (CC BY-SA 4.0)"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
ROUND_FROM_END = ["F", "SF", "QF", "R16", "R32", "R64", "R128"]
DAY_FROM_END = [6, 5, 4, 3, 2, 1, 1]


def client(budget: int = 6000) -> Client:
    return Client(budget=budget, interval=INTERVAL, name="wikipedia",
                  headers={"Accept": "text/html", "Accept-Encoding": "gzip"})


def cache_dir() -> Path:
    return canon.raw_root() / "wiki"


def page_url(title: str) -> str:
    return BASE + quote(title.replace(" ", "_"), safe="_()',.-–")


def fetch_page(c: Client, title: str, refresh: bool = False) -> str | None:
    """Article HTML for `title`, cached by title under data/tennis/wiki/pages/."""
    d = cache_dir() / "pages"
    d.mkdir(parents=True, exist_ok=True)
    p = d / (re.sub(r"[^A-Za-z0-9._-]+", "_", canon.fold(title)) + ".html")
    if p.exists() and not refresh:
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            pass
    text = c.get_text(page_url(title))
    if not text:
        return None
    p.write_text(text, encoding="utf-8")
    return text


# ── the season calendar ────────────────────────────────────────────────────────

_TD = re.compile(r"<t([dh])\b([^>]*)>(.*?)</t[dh]>", re.S)
_TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S)
_TABLE = re.compile(r"<table\b[^>]*class=\"[^\"]*wikitable[^\"]*\"[^>]*>(.*?)</table>", re.S)
_MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
_WEEK = re.compile(r"^\s*" + _MONTH + r"\s+(\d{1,2})\s*$", re.I)
_WEEK_DM = re.compile(r"^\s*(\d{1,2})\s+" + _MONTH + r"\s*$", re.I)       # "31 December" (some seasons)


def _text(fragment: str) -> str:
    s = re.sub(r"<br[^>]*>", "\n", fragment)
    s = re.sub(r"<[^>]+>", "", s)
    return _html.unescape(s).replace("\xa0", " ")


def _title_from_href(href: str) -> str:
    t = _html.unescape(href).split("/wiki/", 1)[-1].split("#", 1)[0].split("?", 1)[0]
    return unquote(t).replace("_", " ")


def _surface(info: str) -> tuple[str | None, bool]:
    s = canon.fold(info)
    indoor = bool(re.search(r"\(i\)|\bindoor", info, re.I))
    for k in ("clay", "grass", "carpet", "hard"):
        if re.search(rf"\b{k}\b", s):
            return ("hard" if k == "carpet" else k), (indoor or k == "carpet")
    return None, indoor


def parse_season(page: str, year: int) -> list[dict]:
    """Tournaments of one season page, in calendar order, each with its week (the Monday) and Singles page."""
    out: list[dict] = []
    for tb in _TABLE.findall(page or ""):
        week: date | None = None
        for row in _TR.findall(tb):
            for kind, attrs, cell in _TD.findall(row):
                txt = _text(cell).strip()
                m = _WEEK.match(txt)
                md = None if m else _WEEK_DM.match(txt)
                if (m or md) and kind == "d":
                    mon, dd = (m.group(1), m.group(2)) if m else (md.group(2), md.group(1))
                    mo = MONTHS[mon.lower()]
                    y = year - 1 if (mo == 12 and not out and not week) else year
                    try:
                        week = date(y, mo, int(dd))
                    except ValueError:
                        week = None
                    continue
                links = re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', cell, re.S)
                singles = [h for h, lab in links if _text(lab).strip().lower() in ("singles", "men's singles")]
                if not singles or week is None:
                    continue
                ev = links[0]
                lines = [ln.strip() for ln in _text(cell).split("\n") if ln.strip()]
                place = lines[1] if len(lines) > 1 else ""
                info = next((ln for ln in lines if re.search(r"hard|clay|grass|carpet", ln, re.I)), "")
                city, _, country = place.partition(",")
                surf, indoor = _surface(info)
                draw = re.search(r"(\d+)\s*S\b", info)
                out.append({"title": _title_from_href(ev[0]), "name": _text(ev[1]).strip(), "week": week.isoformat(),
                            "city": city.strip() or None, "country": country.strip() or None, "surface": surf,
                            "indoor": indoor, "draw": int(draw.group(1)) if draw else None,
                            "singles": _title_from_href(singles[0]), "info": info})
    seen, uniq = set(), []
    for t in out:
        if t["singles"] in seen:
            continue
        seen.add(t["singles"])
        uniq.append(t)
    return uniq


# ── a draw page ──────────────────────────────────────────────────────────────

_DATAMW = re.compile(r"data-mw='([^']*)'")
_BRACKET = re.compile(r"TeamBracket", re.I)
_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _templates(page: str) -> list[dict]:
    """Bracket templates' parameters ({name: wikitext}) in page order."""
    out = []
    for raw in _DATAMW.findall(page or ""):
        try:
            mw = json.loads(_html.unescape(raw))
        except ValueError:
            continue
        for part in mw.get("parts") or []:
            tpl = part.get("template") if isinstance(part, dict) else None
            if not tpl:
                continue
            name = ((tpl.get("target") or {}).get("wt") or "").strip()
            if not _BRACKET.search(name):
                continue
            prm = {k.strip(): (v or {}).get("wt", "") for k, v in (tpl.get("params") or {}).items()}
            out.append({"template": name, "params": prm})
    return out


def _clean_name(wt: str) -> tuple[str | None, str | None, bool]:
    """(name, flag code, bold) from a team cell's wikitext."""
    bold = "'''" in wt
    flag = None
    fm = re.search(r"\{\{\s*flag(?:icon|athlete|country)?\s*\|\s*([A-Za-z]{2,3})", wt, re.I)
    if fm:
        flag = fm.group(1).upper()
    s = re.sub(r"\{\{\s*flag[^}]*\}\}", "", wt, flags=re.I)
    lm = _LINK.search(s)
    if lm:
        name = lm.group(1)
    else:
        s = re.sub(r"\{\{[^}]*\}\}", "", s)
        name = re.sub(r"<[^>]+>", "", s)
    name = re.sub(r"\s*\((?:tennis|tennis player|[^)]*tennis[^)]*)\)\s*$", "", name.replace("'''", "").replace("''", ""))
    name = _html.unescape(name).replace("&nbsp;", " ").strip()
    if not name or name.lower() in ("bye", "tbd", "&nbsp;"):
        return None, flag, bold
    return name, flag, bold


def _score(wt: str) -> tuple[int | None, int | None, bool, str]:
    """(games, tiebreak points, bold, flag text) from a score cell: "'''7<sup>7</sup>'''", "6<sup>3</sup>", "3r"."""
    bold = "'''" in wt
    s = wt.replace("'''", "").replace("''", "")
    tb = None
    m = re.search(r"<sup>\s*(\d+)\s*</sup>", s)
    if m:
        tb = int(m.group(1))
        s = s[: m.start()] + s[m.end():]
    s = re.sub(r"<[^>]+>|\{\{[^}]*\}\}", "", _html.unescape(s)).strip()
    flag = ""
    if re.search(r"w/?o|walkover", s, re.I):
        flag = "wo"
    elif re.search(r"ret|\br\b|r$|def", s, re.I):
        flag = "ret"
    g = re.match(r"(\d+)", s)
    return (int(g.group(1)) if g else None), tb, bold, flag


def _rounds(prm: dict) -> dict[int, dict[int, str]]:
    """{round number: {slot number: team wikitext}}."""
    out: dict[int, dict[int, str]] = {}
    for k, v in prm.items():
        m = re.match(r"RD(\d+)-team0*(\d+)$", k)
        if m:
            out.setdefault(int(m.group(1)), {})[int(m.group(2))] = v
    return out


def _slot_param(prm: dict, rd: int, slot: int, what: str, k: int | None = None) -> str:
    for pad in (f"{slot:02d}", str(slot), f"{slot:03d}"):
        key = f"RD{rd}-{what}{pad}" + (f"-{k}" if k is not None else "")
        if key in prm:
            return prm[key] or ""
    return ""


def _template_matches(prm: dict) -> list[dict]:
    rounds = _rounds(prm)
    out = []
    for rd in sorted(rounds):
        slots = rounds[rd]
        label = canon.fold(prm.get(f"RD{rd}", ""))
        for i in range(1, max(slots) + 1, 2):
            if i not in slots and i + 1 not in slots:
                continue
            na, fa, ba = _clean_name(slots.get(i, ""))
            nb, fb, bb = _clean_name(slots.get(i + 1, ""))
            if not na or not nb:
                continue
            sets, flags, wa, wb = [], set(), 0, 0
            bold_a = bold_b = 0
            for k in range(1, 6):
                ga, ta, xa, fla = _score(_slot_param(prm, rd, i, "score", k))
                gb, tb_, xb, flb = _score(_slot_param(prm, rd, i + 1, "score", k))
                flags |= {fla, flb} - {""}
                bold_a += xa
                bold_b += xb
                if ga is None and gb is None:
                    continue
                ga, gb = ga or 0, gb or 0
                if (ta is None) != (tb_ is None):          # often only the tiebreak loser's points are shown
                    lo = ta if ta is not None else tb_
                    hi = max(7, (lo or 0) + 2)
                    ta, tb_ = (hi, lo) if ga > gb else (lo, hi)
                sets.append([ga, gb, ta, tb_])
                if ga > gb:
                    wa += 1
                elif gb > ga:
                    wb += 1
            if ba != bb:
                winner = "a" if ba else "b"
            elif bold_a != bold_b:
                winner = "a" if bold_a > bold_b else "b"
            elif wa != wb and "ret" not in flags:
                winner = "a" if wa > wb else "b"
            else:
                winner = None
            status = "wo" if "wo" in flags and not sets else ("ret" if flags & {"ret", "wo"} else "done")
            out.append({"rd": rd, "label": label, "a": na, "b": nb, "flag_a": fa, "flag_b": fb, "winner": winner,
                        "sets": sets, "status": status,
                        "seeds": [_slot_param(prm, rd, i, "seed").strip() or None,
                                  _slot_param(prm, rd, i + 1, "seed").strip() or None]})
    return out


_LABEL = [("final", "F"), ("semi", "SF"), ("quarter", "QF")]


def parse_draw(page: str) -> list[dict]:
    """Every main-draw singles match on a draw page, once, with its round label counted from the final."""
    tpls = _templates(page)
    if not tpls:
        return []
    raw = []
    for t in tpls:
        raw.append(_template_matches(t["params"]))
    # rounds counted from the end: the template holding the final has its last round = F; the half / section brackets
    # end at a semi-final or quarter-final (their last round label says which)
    labelled = []
    for ms in raw:
        if not ms:
            continue
        last = max(m["rd"] for m in ms)
        lab_last = next((m["label"] for m in ms if m["rd"] == last), "")
        n_last = sum(1 for m in ms if m["rd"] == last)
        if "semi" in lab_last and n_last == 1:
            end = 1                     # a half's last column is its semi-final
        elif "quarter" in lab_last and n_last == 1:
            end = 2
        elif "final" in lab_last and "semi" not in lab_last and "quarter" not in lab_last:
            end = 0
        else:
            end = {1: 0, 2: 1, 4: 2}.get(n_last, 1)
        for m in ms:
            k = end + (last - m["rd"])
            m["round"] = ROUND_FROM_END[k] if k < len(ROUND_FROM_END) else None
            labelled.append(m)
    seen: dict[tuple, dict] = {}
    for m in labelled:
        if not m["round"]:
            continue
        key = (m["round"], frozenset((canon.fold(m["a"]), canon.fold(m["b"]))))
        if key in seen:
            if not seen[key]["sets"] and m["sets"]:
                seen[key] = m
            continue
        seen[key] = m
    return list(seen.values())


def round_day(week: str, rnd: str) -> str:
    k = ROUND_FROM_END.index(rnd) if rnd in ROUND_FROM_END else len(ROUND_FROM_END) - 1
    return (date.fromisoformat(week) + timedelta(days=DAY_FROM_END[k])).isoformat()


def season_title(year: int) -> str:
    return f"{int(year)} ATP Challenger Tour" if int(year) >= 2009 else f"{int(year)} ATP Challenger Series"


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
