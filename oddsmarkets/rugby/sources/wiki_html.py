"""
A small standard-library reader for Wikipedia (Parsoid) article HTML: every wikitable as a grid with rowspan and
colspan expanded, the heading each table sits under, and the rugby match boxes (`{{rugbybox}}`, rendered as a
`vevent` block) read from the template's own parameters in `data-mw` where Parsoid keeps them.

No bs4 or lxml in the project, so this is html.parser only.
"""
from __future__ import annotations

import html as _html
import json
import re
from html.parser import HTMLParser
from typing import Any

_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    s = (s or "").replace("‑", "-").replace("–", "-").replace("—", "-").replace("−", "-")
    s = s.replace("\xa0", " ").replace("​", "")
    return _WS.sub(" ", s).strip()


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self.stack: list[dict] = []
        self.row: list | None = None
        self.cell: dict | None = None
        self.heads: list[str] = ["", "", ""]         # h2, h3, h4 currently in force
        self._h: tuple[int, list[str]] | None = None
        self._skip = 0
        self._sup = 0
        self.mw: list[tuple[int, str]] = []          # (table count at that point, data-mw json) for rugbybox
        self._a_title: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag == "sup" and "reference" in (a.get("class") or ""):
            self._sup += 1
            return
        dm = a.get("data-mw")
        if dm and "ugbybox" in dm:
            self.mw.append((len(self.tables), dm))
        if tag == "table":
            t = {"rows": [], "cls": a.get("class") or "", "heads": [h for h in self.heads],
                 "caption": "", "nested": bool(self.stack)}
            self.stack.append(t)
            self.tables.append(t)
            self.row, self.cell = None, None
        elif tag == "tr" and self.stack:
            self.row = []
            self.stack[-1]["rows"].append(self.row)
        elif tag in ("td", "th") and self.stack:
            if self.row is None:
                self.row = []
                self.stack[-1]["rows"].append(self.row)

            def _n(v):
                try:
                    return max(1, int(str(v).strip().rstrip(";")))
                except (TypeError, ValueError):
                    return 1
            self.cell = {"t": "", "links": [], "th": tag == "th", "cs": _n(a.get("colspan")), "rs": _n(a.get("rowspan")),
                         "style": a.get("style") or "", "cls": a.get("class") or ""}
            self.row.append(self.cell)
        elif tag == "a":
            if self.cell is not None:
                href = a.get("href") or ""
                self.cell["links"].append([href, a.get("title") or ""])
        elif tag in ("h2", "h3", "h4"):
            self._h = (int(tag[1]), [])
        elif tag == "caption" and self.stack:
            self._h = (0, [])
        elif tag == "br" and self.cell is not None:
            self.cell["t"] += " | "
        elif tag in ("li", "p", "div") and self.cell is not None:
            self.cell["t"] += " "

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if tag == "sup" and self._sup:
            self._sup -= 1
            return
        if tag == "table" and self.stack:
            self.stack.pop()
            self.row, self.cell = None, None
            if self.stack:
                t = self.stack[-1]
                self.row = t["rows"][-1] if t["rows"] else None
                self.cell = self.row[-1] if self.row else None
        elif tag in ("td", "th"):
            self.cell = None
        elif tag == "tr":
            self.row = None
        elif tag in ("h2", "h3", "h4", "caption") and self._h is not None:
            lvl, txt = self._h
            text = norm("".join(txt)).replace("[edit]", "").strip()
            if lvl == 0:
                if self.stack:
                    self.stack[-1]["caption"] = text
            else:
                self.heads[lvl - 2] = text
                for k in range(lvl - 1, 3):
                    self.heads[k] = ""
                self.heads[lvl - 2] = text
            self._h = None

    def handle_data(self, data):
        if self._skip or self._sup:
            return
        if self.cell is not None:
            self.cell["t"] += data
        if self._h is not None:
            self._h[1].append(data)


def grid(t: dict) -> list[list[dict]]:
    """The table's rows with rowspan/colspan expanded: every row the same width, a spanned cell repeated."""
    out: list[list[dict]] = []
    carry: dict[int, tuple[dict, int]] = {}
    for row in t["rows"]:
        r: list[dict] = []
        col = 0
        cells = list(row)
        i = 0
        while i < len(cells) or col in carry:
            if col in carry:
                c, left = carry[col]
                r.append(c)
                if left <= 1:
                    del carry[col]
                else:
                    carry[col] = (c, left - 1)
                col += 1
                continue
            if i >= len(cells):
                break
            c = cells[i]
            i += 1
            for k in range(c["cs"]):
                r.append(c)
                if c["rs"] > 1:
                    carry[col] = (c, c["rs"] - 1)
                col += 1
        out.append(r)
    return out


def read(html_text: str) -> _Reader:
    p = _Reader()
    p.feed(html_text or "")
    p.close()
    for t in p.tables:
        for row in t["rows"]:
            for c in row:
                c["t"] = norm(c["t"])
    return p


def text(c: dict | None) -> str:
    return (c or {}).get("t") or ""


def wiki_titles(c: dict | None) -> list[str]:
    out = []
    for href, title in (c or {}).get("links") or []:
        if href.startswith(("./", "/wiki/", "https://en.wikipedia.org/wiki/")) and ":" not in href.split("/wiki/")[-1].lstrip("./"):
            out.append(title or _html.unescape(href.split("/")[-1].replace("_", " ")))
    return out


def rugbyboxes(html_text: str) -> list[dict]:
    """Every {{rugbybox}} template's parameters, from Parsoid's data-mw: [{"date", "team1", "score", "team2",
    "stadium", "attendance", "referee", "try1", ...}] with wiki markup stripped to plain text."""
    out = []
    for m in re.finditer(r"data-mw='([^']*ugbybox[^']*)'", html_text or ""):
        try:
            d = json.loads(_html.unescape(m.group(1)))
        except ValueError:
            continue
        for part in d.get("parts") or []:
            tpl = part.get("template") if isinstance(part, dict) else None
            if not tpl:
                continue
            name = str((tpl.get("target") or {}).get("wt") or "").strip().lower().replace("_", " ")
            if not name.startswith("rugbybox") or "end" in name or "collapsible" in name and False:
                pass
            if not name.startswith("rugbybox"):
                continue
            params = {k: strip_wt(str((v or {}).get("wt") or "")) for k, v in (tpl.get("params") or {}).items()}
            params["_tpl"] = name
            params["_raw"] = {k: str((v or {}).get("wt") or "") for k, v in (tpl.get("params") or {}).items()
                              if k in ("team1", "team2", "home", "away", "referee", "stadium")}
            out.append(params)
    return out


_TPL = re.compile(r"\{\{([^{}]*)\}\}")
_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_EXT = re.compile(r"\[(?:https?:)?//[^\s\]]+\s*([^\]]*)\]")


def _tpl_text(m: re.Match) -> str:
    parts = [p.strip() for p in m.group(1).split("|")]
    name = parts[0].lower()
    args = [p for p in parts[1:] if "=" not in p]
    if name in ("flagicon", "flagdeco", "flagicon image", "refn", "efn", "sfn", "cite web", "cite news", "small",
                "nowrap") and name not in ("small", "nowrap"):
        return ""
    if name in ("small", "nowrap"):
        return args[0] if args else ""
    if name in ("ru", "rut", "ru-rt", "flagteam", "fb", "fb-rt", "rufu", "flag", "flagcountry", "rugby union team"):
        return args[0] if args else ""
    if name.startswith(("start date", "dts")):
        return "-".join(args[:3])
    if name in ("convert",):
        return " ".join(args[:2])
    if name in ("abbr",):
        return args[0] if args else ""
    if name in ("yel", "yellow card", "sent off", "suspended", "red card", "subon", "suboff", "sub on", "sub off",
                "goal", "ref label", "lang"):
        return ""
    return args[-1] if args else ""


def strip_wt(wt: str) -> str:
    s = re.sub(r"<ref[^>]*/>", "", wt or "")
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    for _ in range(4):
        s2 = _TPL.sub(_tpl_text, s)
        if s2 == s:
            break
        s = s2
    s = _LINK.sub(lambda m: m.group(1), s)
    s = _EXT.sub(lambda m: m.group(1), s)
    s = re.sub(r"<br\s*/?>", " | ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "")
    return norm(_html.unescape(s))
