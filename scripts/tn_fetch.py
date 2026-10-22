#!/usr/bin/env python
"""
Fill The Quant Ace's season stores (docs/ace/data/<tour>/<year>/store.json), resumably.

Phases, per season, newest season first (so the current season is usable first), in this order
so that tennis-data's "Surname I." names resolve against full-name fields:

  espn      the season's scoreboard in one call (?dates=YYYY, about 20 MB): every tournament,
            round, status and games per set, tiebreak points, qualifying; ESPN athlete ids.
            The current season with --refresh-current reads one scoreboard a day from 3 days ago
            to 2 days ahead instead (live, upcoming and draws). Completed seasons are read once.
  wta       (WTA only) the WTA API calendar, each tour-level and WTA 125 tournament's matches
            (1 call), draw (1 call) and, for every finished main-draw tour-level match, its
            serve/return stats (1 call a match). Stats exist from 2016; a season whose first
            tournaments answer empty is marked and skipped.
  td        tennis-data.co.uk's season workbook: the official result, entry ranks and points and
            closing odds. Completed seasons are read once; the current one again whenever its
            Last-Modified moves (a conditional GET that answers 304 costs nothing).
  rankings  (current season) the latest official ranking: ESPN (ATP, top 150) and the WTA API
            (WTA, top 1000, after ESPN's top 150 to link ESPN ids).

Resolved players go into the tour registry (docs/ace/data/<tour>/registry.json). A stopped run
picks up where it left off: per-source "fetched" marks in each store's meta.

    python scripts/tn_fetch.py --tour atp --from 2026 --to 2026
    python scripts/tn_fetch.py --tour wta --from 2007 --to 2025 --budget 60000 --log logs/tn_backfill_wta.log
    python scripts/tn_fetch.py --tour atp --refresh-current --budget 300
    python scripts/tn_fetch.py --tour wta --report --from 2016 --to 2026
    python scripts/tn_fetch.py --tour wta --dedupe --from 2007 --to 2026     # repair duplicates, no fetching

Every save merges events that hold the same matches and folds rows of one real match (store.dedupe), and
folds copies of a match filed in two seasons' stores across New Year (store.dedupe_seasons).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.tennis import canon  # noqa: E402
from oddsmarkets.tennis import store as st  # noqa: E402
from oddsmarkets.tennis.sources import espn, tennisdata as td, wta  # noqa: E402
from oddsmarkets.tennis.sources._client import BudgetExhausted, Client  # noqa: E402

logger = logging.getLogger("tn_fetch")
PHASES = ("espn", "wta", "td", "rankings")
ESPN_FROM = 2007              # ESPN's season scoreboards (?dates=YYYY) are empty before 2007
WTA_EMPTY_PROBE = 6           # tour-level tournaments that must all answer empty to call a season empty


def _now_iso() -> str:
    return canon.now()


def _hours_since(iso: str | None) -> float:
    if not iso:
        return 1e9
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return 1e9
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


# ── ingest ──────────────────────────────────────────────────────────────────

class Ingest:
    """Resolves the players of source records and merges them into a store."""

    def __init__(self, s: dict, reg: canon.Registry):
        self.s, self.reg = s, reg
        self.fields: dict[str, set[str]] = {}
        self.full_fields: dict[str, set[str]] = {}
        for m in s["matches"].values():
            self.fields.setdefault(m["event"], set()).update([m["p1"], m["p2"]])
            if set(m.get("sources") or []) - {"td"}:
                self.full_fields.setdefault(m["event"], set()).update([m["p1"], m["p2"]])
        for eid, ev in s["events"].items():
            for slot in ((ev.get("draw") or {}).get("slots") or []):
                if slot[1] and (ev.get("draw") or {}).get("source") == "wta":
                    self.full_fields.setdefault(eid, set()).add(slot[1])
        self.counts: Counter = Counter()

    def side(self, src: str, side: dict, eid: str) -> str | None:
        if src == "td":
            field = self.full_fields.get(eid) or set()
            return self.reg.resolve_abbrev("td", side.get("name"), field=field, has_field=bool(field))
        return self.reg.add(src, first=side.get("first"), last=side.get("last"), full=side.get("name"),
                            espn=side.get("espn"), wta=side.get("wta"), country=side.get("country"),
                            dob=side.get("dob"), raw=side.get("name"), field=self.fields.get(eid))

    def _keys(self, pid: str) -> set[str]:
        p = self.reg.players.get(self.reg.canonical(pid)) or {}
        toks = canon.name_tokens(p.get("name"))
        out = {"".join(toks[k:]) for k in range(len(toks))} | {"".join(toks[: k + 1]) for k in range(len(toks))}
        return out | set(canon.name_tokens(p.get("last")))

    def place_td_events(self, recs: list[dict]) -> None:
        """Match each tennis-data event to a stored event by dates and by its matchups: the share of
        its matches whose two surnames ("Surname I.") meet in a stored match of the candidate event.
        Matchups are event-specific, so this survives the older ESPN scoreboards' missing cities and
        modern sponsor names, and a long event (a Slam with its qualifying) overlapping a smaller one."""
        groups: dict[int, tuple[dict, list[dict]]] = {}
        for r in recs:
            groups.setdefault(id(r["event"]), (r["event"], []))[1].append(r)
        keycache: dict[str, set[str]] = {}

        def keys(pid: str) -> set[str]:
            if pid not in keycache:
                keycache[pid] = self._keys(pid)
            return keycache[pid]

        def sur(name: str) -> str:
            pa = canon.parse_abbrev(name)
            return "".join(pa[0]) if pa else "".join(canon.name_tokens(name))

        for meta, rs in groups.values():
            pairs = [(sur(x["a"]["name"]), sur(x["b"]["name"])) for x in rs]
            found = st.event_for(self.s, meta, "td", create=False)
            scored = []
            for eid, ev in self.s["events"].items():
                if not st._overlap(ev.get("start"), ev.get("end"), meta.get("start"), meta.get("end"), slack=4):
                    continue
                ms = [m for m in self.s["matches"].values() if m["event"] == eid]
                if not ms:
                    continue
                mk = [(keys(m["p1"]), keys(m["p2"])) for m in ms]
                hit = 0
                for x, y in pairs:
                    if any((x in k1 and y in k2) or (y in k1 and x in k2) for k1, k2 in mk):
                        hit += 1
                scored.append((hit / max(1, len(pairs)), eid))
            scored.sort(reverse=True)
            best = scored[0] if scored else (0, None)
            second = scored[1][0] if len(scored) > 1 else 0
            if best[0] >= 0.3 and best[0] - second >= 0.2:
                if best[1] != found:
                    self.counts["td_event_by_matchups"] += 1
                meta["_eid"] = best[1]
            elif found:
                meta["_eid"] = found

    def rename_td_events(self, recs: list[dict]) -> None:
        """Events first made from ESPN keep tennis-data's canonical tid once tennis-data joins them."""
        done = set()
        for r in recs:
            meta = r["event"]
            eid = meta.get("_eid")
            if not eid or eid in done or eid not in self.s["events"]:
                continue
            done.add(eid)
            ev = self.s["events"][eid]
            hint = meta.get("tid_hint")
            base = ev["tid"].rsplit("-", 1)[0] if ev["tid"].rsplit("-", 1)[-1].isdigit() else ev["tid"]
            fixed = base in canon.SLAMS or base in ("atp-finals", "wta-finals", "olympics", "wta-elite-trophy")
            if hint and not fixed and ev.get("_tid_src") != "td" and base != hint and hint not in ("skip", "unknown"):
                new = st.rename_event(self.s, eid, hint)
                if new != eid:
                    for d in (self.fields, self.full_fields):
                        if eid in d:
                            d[new] = d.pop(eid)
                    meta["_eid"] = new
                    self.counts["renamed"] += 1
            ev["_tid_src"] = "td"

    def _link_identity(self, c: dict) -> None:
        """ESPN and the WTA name one player differently ("Catherine" / "Caty McNally"): when a
        same-score match ties them and their surnames agree, the two pids become one player."""
        have, got = c.get("have") or [], c.get("got") or []
        a = [x for x in have if x not in got]
        b = [x for x in got if x not in have]
        if len(a) != 1 or len(b) != 1:
            return
        pa, pb = self.reg.players.get(self.reg.canonical(a[0])), self.reg.players.get(self.reg.canonical(b[0]))
        if not pa or not pb or pa.get("_abbrev") or pb.get("_abbrev"):
            return
        la, lb = canon.name_tokens(pa.get("last") or pa.get("name")), canon.name_tokens(pb.get("last") or pb.get("name"))
        if not la or not lb or la[-1] != lb[-1]:
            return
        # only an ESPN-only profile and a WTA-only profile (twins already linked by exact names stay apart)
        kinds = {("espn" if p.get("espn") else "") + ("wta" if p.get("wta") else "") for p in (pa, pb)}
        if kinds != {"espn", "wta"}:
            return
        fa, fb = canon.name_tokens(pa.get("first") or pa.get("name")), canon.name_tokens(pb.get("first") or pb.get("name"))
        if not fa or not fb or fa[0][:1] != fb[0][:1]:
            return
        keep = self.reg.merge(a[0], b[0])
        st.remap(self.s, self.reg.canonical)
        st.drop_index(self.s)
        for d in (self.fields, self.full_fields):
            for k in d:
                d[k] = {self.reg.canonical(x) for x in d[k]}
        self.counts["identity_linked"] += 1
        logger.info("identity: %s and %s are one player (%s)", a[0], b[0], keep)

    def records(self, recs: list[dict], src: str) -> int:
        if src == "td":
            self.place_td_events(recs)
        n = self._records(recs, src)
        if src == "td":
            self.rename_td_events(recs)
        return n

    def _records(self, recs: list[dict], src: str) -> int:
        n = 0
        for rec in recs:
            if rec.get("year") and int(rec["year"]) != int(self.s["year"]):
                self.counts["other_season"] += 1
                continue
            eid = st.event_for(self.s, rec["event"], src)
            if eid is None:
                self.counts["skipped_event"] += 1
                continue
            pa, pb = self.side(src, rec["a"], eid), self.side(src, rec["b"], eid)
            if not pa or not pb or pa == pb:
                self.counts["unresolved_pair"] += 1
                continue
            conf = self.s["meta"].setdefault("conflicts", [])
            n_conf = len(conf)
            st.merge_record(self.s, rec, eid, pa, pb)
            if len(conf) > n_conf and conf[-1].get("kind") == "identity" and src != "td":
                self._link_identity(conf[-1])
            self.fields.setdefault(eid, set()).update([pa, pb])
            if src != "td":
                self.full_fields.setdefault(eid, set()).update([pa, pb])
            n += 1
        self.counts[src] += n
        return n


# ── phases ──────────────────────────────────────────────────────────────────

def phase_espn(c: Client, tour: str, s: dict, ing: Ingest, refresh: bool, today: date) -> None:
    year = s["year"]
    f = s["meta"]["fetched"]
    current = year == today.year
    if year < ESPN_FROM:
        return
    if current and refresh:
        days = [(today + timedelta(days=k)).strftime("%Y%m%d") for k in range(-3, 3)]
        n = 0
        for d in days:
            raw = espn.scoreboard(c, tour, d)
            if raw is None:
                continue
            n += ing.records(espn.parse_scoreboard(raw, tour), "espn")
        f["espn_days"] = {"at": _now_iso(), "days": days}
        logger.info("%s %d espn: %d records from %d day scoreboards", tour, year, n, len(days))
        return
    if f.get("espn_year") and (not current or _hours_since(f["espn_year"]) < 6):
        return
    t0 = time.monotonic()
    raw = espn.scoreboard(c, tour, year)
    if raw is None:
        logger.warning("%s %d espn: no season scoreboard", tour, year)
        return
    recs = espn.parse_scoreboard(raw, tour, year)
    n = ing.records(recs, "espn")
    f["espn_year"] = _now_iso()
    s["meta"]["sources"]["espn"] = {"records": len(recs), "events": len({r["event"]["espn"] for r in recs})}
    logger.info("%s %d espn: %d records (%d merged) from the season scoreboard in %.1f s",
                tour, year, len(recs), n, time.monotonic() - t0)


def _wta_draw(c: Client, s: dict, reg: canon.Registry, gid: str, eid: str) -> None:
    d = wta.parse_draw(wta.draw_raw(c, gid, s["year"]))
    if not d:
        return
    slots = []
    for pos, wid, seed, entry in d["slots"]:
        pid = reg.canonical(reg.by_wta.get(wid)) if wid else None
        if wid and pid is None and (d.get("names") or {}).get(wid):
            pid = reg.canonical(reg.find("wta", d["names"][wid]))     # not linked to her WTA id yet: by name
        slots.append([pos, pid, seed, entry])
    s["events"][eid]["draw"] = {"size": d["size"], "slots": slots, "source": "wta", "complete": True,
                                "unmatched": sum(1 for x, y in zip(d["slots"], slots) if x[1] and not y[1])}


def phase_wta(c: Client, s: dict, ing: Ingest, reg: canon.Registry, refresh: bool, today: date,
              stats: bool = True) -> None:
    year = s["year"]
    meta, f = s["meta"], s["meta"]["fetched"]
    if year < wta.STATS_FROM - 1:
        return
    src = meta["sources"].setdefault("wta", {})
    if src.get("empty_year"):
        return
    current = year == today.year
    if refresh and current:
        lo, hi = (today - timedelta(days=14)).isoformat(), (today + timedelta(days=10)).isoformat()
    else:
        lo, hi = f"{year - 1}-12-15", f"{year}-12-31"
    cal = None
    if not current and f.get("wta_calendar"):
        cal = f["wta_calendar"]
    if cal is None:
        raw_cal = wta.calendar(c, lo, hi)
        cal = [{"gid": str((t.get("tournamentGroup") or {}).get("id")), "year": t.get("year"),
                "meta": wta.tournament_meta(t)} for t in raw_cal if int(t.get("year") or 0) == year]
        if not current:
            f["wta_calendar"] = cal
    events = f.setdefault("wta_events", {})
    done_stats = f.setdefault("wta_stats", {})
    probed_empty, probed = 0, 0
    n_stats = 0
    cal = sorted(cal, key=lambda t: t["meta"].get("start") or "", reverse=True)
    for t in cal:
        gid, m = t["gid"], t["meta"]
        if not m.get("start") or m["start"] > today.isoformat():
            continue
        state = events.get(gid)
        live_now = m.get("end") and m["end"] >= (today - timedelta(days=2)).isoformat()
        if state == "complete" and not (refresh and live_now):
            continue
        raw = wta.matches(c, gid, year, use_cache=not live_now)
        recs = wta.parse_matches(raw, m, year)
        if m.get("level") not in ("ch",) and m["level"] is not None:
            probed += 1
            if not recs:
                probed_empty += 1
        if not recs:
            events[gid] = "empty" if not live_now else _now_iso()
            if probed >= WTA_EMPTY_PROBE and probed_empty == probed and not current:
                src["empty_year"] = True
                logger.info("wta %d: the first %d tour-level tournaments have no matches; season marked empty", year, probed)
                return
            continue
        # stats for finished main-draw tour-level matches (marked fetched only once merged)
        pending: dict[str, int] = {}
        exhausted = None
        if stats and m.get("level") not in ("ch", None):
            try:
                for r in recs:
                    if r["status"] not in ("done", "ret", "def") or r.get("draw_level") != "M":
                        continue
                    key = f"{gid}/{r['match_id']}"
                    if key in done_stats:
                        continue
                    parsed = wta.parse_stats(wta.stats(c, gid, year, r["match_id"]))
                    if parsed:
                        r["stats"] = parsed
                        n_stats += 1
                    pending[key] = 1 if parsed else 0
            except BudgetExhausted as exc:
                exhausted = exc
        ing.records(recs, "wta")
        done_stats.update(pending)
        if exhausted is not None:
            raise exhausted
        eid = st.event_for(s, m, "wta")
        if eid and (not s["events"][eid].get("draw") or (s["events"][eid]["draw"] or {}).get("source") != "wta" or live_now):
            _wta_draw(c, s, reg, gid, eid)
        finished = (not live_now) and all(r["status"] not in ("live", "upcoming") for r in recs)
        events[gid] = "complete" if finished else _now_iso()
        if len(events) % 10 == 0:
            st.save(s)
            logger.info("wta %d: %s done (%d stats so far, %d calls)", year, m.get("name"), n_stats, c.used)
    src.update({"tournaments": len(cal), "stats_fetched": sum(1 for v in done_stats.values() if v),
                "stats_missing": sum(1 for v in done_stats.values() if not v)})
    logger.info("wta %d: %d tournaments, %d new stats this run (%d calls used)", year, len(cal), n_stats, c.used)


def phase_td(c: Client | None, tour: str, s: dict, ing: Ingest, reg: canon.Registry, links: dict, refresh: bool,
             today: date, force: bool = False) -> None:
    year = s["year"]
    f = s["meta"]["fetched"]
    if year < td.FIRST_YEAR[tour]:
        return
    current = year >= today.year - (1 if today.month == 1 else 0)
    link = links.get((tour, year))
    if f.get("td") and not current and not force:
        return
    recs, info = td.load_year(c, tour, year, link, refresh=current and (refresh or not f.get("td")))
    if not recs:
        logger.warning("%s %d td: %s", tour, year, info.get("error") or "no rows")
        s["meta"]["sources"]["td"] = info
        return
    if f.get("td") and not force and not info.get("changed") and f.get("td_last_modified") == info.get("last_modified"):
        logger.info("%s %d td: unchanged (%s)", tour, year, info.get("last_modified"))
        return
    n = ing.records(recs, "td")
    # tennis-data lists every tour-level event: an event it does not have that ended before its last
    # date, and that the WTA calendar did not grade, is below tour level (WTA 125 / Challenger)
    td_last = max((r.get("date") or "")[:10] for r in recs)
    fixed = set(canon.SLAMS) | {"atp-finals", "wta-finals", "olympics", "wta-elite-trophy", "next-gen-finals"}
    for eid, ev in s["events"].items():
        base = ev["tid"].rsplit("-", 1)[0] if ev["tid"].rsplit("-", 1)[-1].isdigit() else ev["tid"]
        if (not ev.get("_td") and not ev.get("_lv_level") and base not in fixed and (ev.get("end") or "9") < td_last
                and ev.get("level") in ("250", "500", "m1000")):
            ev["level"] = "ch"
            ing.counts["graded_ch"] += 1
    merged = reg.link_abbrev_players()
    if merged:
        st.remap(s, reg.canonical)
        st.drop_index(s)
    f["td"] = _now_iso()
    f["td_last_modified"] = info.get("last_modified")
    s["meta"]["sources"]["td"] = {**info, "records": len(recs), "merged": n}
    logger.info("%s %d td: %d rows -> %d merged (%s; %d abbreviated players linked)", tour, year, len(recs), n,
                info.get("file"), merged)


def phase_rankings(ce: Client, cw: Client | None, tour: str, s: dict, reg: canon.Registry) -> None:
    rk = espn.parse_rankings(espn.rankings_raw(ce, tour))
    best = None
    if rk:
        rows = [[r, reg.add("espn", first=side.get("first"), last=side.get("last"), full=side.get("name"),
                            espn=side.get("espn"), country=side.get("country")), p] for r, side, p in rk["rows"]]
        best = {"date": rk["date"], "rows": rows, "source": "espn"}
    if tour == "wta" and cw is not None:
        rw = wta.rankings(cw)
        if rw:
            rows = [[r, reg.add("wta", first=side.get("first"), last=side.get("last"), full=side.get("name"),
                                wta=side.get("wta"), country=side.get("country"), dob=side.get("dob")), p]
                    for r, side, p in rw["rows"]]
            best = {"date": rw["date"], "rows": rows, "source": "wta"}
    if best:
        s["rankings"] = best
        logger.info("%s rankings: %d rows as of %s (%s)", tour, len(best["rows"]), best["date"], best["source"])


# ── one row per real match ──────────────────────────────────────────────────

def _near_new_year(s: dict) -> tuple[bool, bool]:
    """(has rows in its first January weeks, has rows in its last December weeks)."""
    y = int(s["year"])
    ds = [str(m.get("date") or "")[:10] for m in s["matches"].values()]
    return any(d <= f"{y}-01-31" for d in ds if d), any(d >= f"{y}-12-01" for d in ds if d)


def neighbours(tour: str, s: dict, reg: canon.Registry, today: date) -> int:
    """Fold the rows a neighbouring season's store holds of the same matches across New Year (store.dedupe_seasons):
    season Y-1's December copies go into Y, Y's into Y+1. A neighbour that changed is finalized and saved."""
    jan, dec = _near_new_year(s)
    n = 0
    for other_year, prev_is_other in ((int(s["year"]) - 1, True), (int(s["year"]) + 1, False)):
        if (prev_is_other and not jan) or (not prev_is_other and not dec):
            continue
        if not st.store_path(tour, other_year).exists():
            continue
        o = st.load(tour, other_year, reg)
        k = st.dedupe_seasons(o, s) if prev_is_other else st.dedupe_seasons(s, o)
        if k:
            st.finalize_events(o, today)
            st.set_players(o, reg)
            o["meta"]["sources"]["coverage"] = coverage(o)
            st.save(o)
            logger.info("%s %d: %d rows of one match folded across New Year with %d", tour, s["year"], k, other_year)
        n += k
    return n


def repair(tour: str, years: list[int], today: date) -> None:
    """Dedupe the stores on disk (no fetching): events holding the same matches merged, same-match rows folded,
    New Year copies moved to the later season."""
    reg = canon.Registry.load(tour)
    for y in sorted(years):
        if not st.store_path(tour, y).exists():
            continue
        s = st.load(tour, y, reg)
        n0 = len(s["matches"])
        dd = st.dedupe(s)
        k = neighbours(tour, s, reg, today)
        if not (dd["events"] or dd["matches"] or k):
            continue                                      # untouched: not rewritten
        st.finalize_events(s, today)
        st.set_players(s, reg)
        s["meta"]["sources"]["coverage"] = coverage(s)
        st.save(s)
        logger.info("%s %d repair: %d events merged, %d rows folded, %d New Year rows; %d -> %d matches",
                    tour, y, dd["events"], dd["matches"], k, n0, len(s["matches"]))


# ── coverage ────────────────────────────────────────────────────────────────

def coverage(s: dict) -> dict:
    ms = list(s["matches"].values())
    main = [m for m in ms if m.get("level") not in ("q", "ch")]
    srcs = Counter("+".join(sorted(m.get("sources") or [])) for m in main)
    return {"matches": len(ms), "tour_main": len(main), "qualifying": sum(1 for m in ms if m.get("level") == "q"),
            "ch": sum(1 for m in ms if m.get("level") == "ch"),
            "status": dict(Counter(m.get("status") for m in ms)),
            "with_odds": sum(1 for m in main if m.get("odds")),
            "with_ps": sum(1 for m in main if (m.get("odds") or {}).get("ps")),
            "with_stats": sum(1 for m in ms if m.get("stats")),
            "with_tb_points": sum(1 for m in ms if any(x[2] is not None for x in m.get("sets") or [])),
            "live": sum(1 for m in ms if m.get("status") == "live"),
            "upcoming": sum(1 for m in ms if m.get("status") == "upcoming"),
            "events": len(s["events"]), "players": len(s["players"]),
            "sources_main": dict(srcs.most_common()),
            "conflicts": len(s["meta"].get("conflicts") or [])}


def report(tour: str, years: list[int]) -> None:
    reg = canon.Registry.load(tour)
    rows = []
    for y in years:
        p = st.store_path(tour, y)
        if not p.exists():
            continue
        s = st.load(tour, y, reg)
        cv = coverage(s)
        rows.append((y, cv))
    print(json.dumps({str(y): cv for y, cv in rows}, indent=1))


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tour", choices=canon.TOURS, required=True)
    ap.add_argument("--from", dest="start", type=int, default=None)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--phases", default=",".join(PHASES))
    ap.add_argument("--budget", type=int, default=3000, help="calls per source (ESPN, WTA, tennis-data each)")
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between calls (0.5 = 2 a second)")
    ap.add_argument("--refresh-current", action="store_true", help="hourly mode for the current season")
    ap.add_argument("--espn-from", type=int, default=None, help=f"first season read from ESPN (default {ESPN_FROM})")
    ap.add_argument("--no-stats", action="store_true", help="skip the WTA per-match stats")
    ap.add_argument("--force-td", action="store_true", help="re-merge tennis-data even when unchanged")
    ap.add_argument("--log", default=None, help="log file (default logs/tn_fetch_<tour>.log)")
    ap.add_argument("--report", action="store_true", help="print coverage of the stores on disk and exit")
    ap.add_argument("--dedupe", action="store_true", help="merge duplicate events / rows of one match in the stores on "
                    "disk (no fetching) and exit")
    args = ap.parse_args()
    tour = args.tour
    today = datetime.now(timezone.utc).date()
    end = args.end or today.year
    start = args.start or end
    years = list(range(end, start - 1, -1))
    if args.report:
        report(tour, years)
        return 0
    if args.dedupe:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        repair(tour, years, today)
        return 0
    log = Path(args.log) if args.log else ROOT / "logs" / f"tn_fetch_{tour}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(log, encoding="utf-8")])
    if args.espn_from:
        globals()["ESPN_FROM"] = args.espn_from
    if args.refresh_current:
        years = [today.year]
    phases = [x for x in args.phases.split(",") if x in PHASES]
    ce = espn.client(args.budget, args.interval)
    cw = wta.client(args.budget, args.interval)
    ct = Client(budget=max(60, min(args.budget, 200)), interval=max(1.0, args.interval), name="tennis-data")
    reg = canon.Registry.load(tour)
    links: dict = {}
    t0 = time.monotonic()
    logger.info("tn_fetch %s %s phases=%s budget=%d interval=%.2f refresh=%s", tour, years, phases, args.budget,
                args.interval, args.refresh_current)
    try:
        if "td" in phases:
            need = [y for y in years if y >= td.FIRST_YEAR[tour] and (y >= today.year - 1 or not td.cached_file(tour, y))]
            if need:
                links = td.links(ct)
                logger.info("tennis-data: %d download links", len(links))
        for year in years:
            s = st.load(tour, year, reg)
            ing = Ingest(s, reg)
            refresh = args.refresh_current and year == today.year
            used0 = (ce.used, cw.used, ct.used)
            try:
                if "espn" in phases:
                    phase_espn(ce, tour, s, ing, refresh, today)
                if "wta" in phases and tour == "wta":
                    phase_wta(cw, s, ing, reg, refresh, today, stats=not args.no_stats)
                if "td" in phases:
                    phase_td(ct, tour, s, ing, reg, links, refresh, today, force=args.force_td)
                if "rankings" in phases and year == today.year:
                    phase_rankings(ce, cw, tour, s, reg)
            finally:
                if s["matches"] or s["events"]:
                    st.drop_index(s)
                    dd = st.dedupe(s)
                    if dd["events"] or dd["matches"]:
                        ing.counts["dedupe_events"] += dd["events"]
                        ing.counts["dedupe_rows"] += dd["matches"]
                    ing.counts["dedupe_seasons"] += neighbours(tour, s, reg, today)
                    st.fill_from_history(s)
                    st.finalize_events(s, today)
                    st.set_players(s, reg)
                    s["meta"]["sources"]["coverage"] = coverage(s)
                    s["meta"]["sources"]["identity"] = reg.report()
                    st.save(s)
                reg.save()
            cv = s["meta"]["sources"].get("coverage") or {}
            logger.info("%s %d done: %s; calls espn %d wta %d td %d; ingest %s", tour, year, json.dumps(cv),
                        ce.used - used0[0], cw.used - used0[1], ct.used - used0[2], dict(ing.counts))
    except BudgetExhausted as exc:
        logger.info("%s", exc)
    el = time.monotonic() - t0
    logger.info("identity: %s", json.dumps(reg.report()))
    logger.info("calls: espn %s | wta %s | tennis-data %s | %.0f s elapsed", ce.report(), cw.report(), ct.report(), el)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
