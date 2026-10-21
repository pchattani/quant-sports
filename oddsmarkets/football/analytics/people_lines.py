"""
One line per person: every player's match statistics consolidated across club
football, his national team and every competition, by season and scope
(docs/site/UNIFIED_PAYLOADS.md section 14).

The Player lab, the cross-competition leaderboards and the compare page used to
read one line per player per competition (players_lab.json, players_global.json),
so Lionel Messi was a dot for MLS, another for the Leagues Cup and another for
Argentina. Here a person is one row in each view, keyed by Sofascore player id, and
the view says what the row covers:

  window  season  the player's current season in his own frame (a European's 2026/27,
                  a Brazilian's 2026), every edition in it; the same season as his
                  page's year-by-year row and people_index.json `min`
          last    the season before
          365     the last twelve months
          ytd     the calendar year so far
  scope   all     every competition
          club    club competitions only
          intl    national-team football only
          <slug>  one competition

Club editions count in their own season (`Unified.season_meta` era); an
international or world-club appearance counts in the player's frame by date
(`Unified.app_era`), so the rows reconcile with the person page.

Stores are read once, inside build_unified's loop: each player-match adds its
statistics to compact accumulators keyed (person, competition, season tag); the
lines are finalised with the same arithmetic as the competition pages
(`players.finalize_player`). Memory is the accumulators (arrays of floats), not
the stores.
"""
from __future__ import annotations

import json
import logging
from array import array
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from oddsmarkets.football.analytics.players import (
    FLOOR_MIN, FLOOR_SHARE, METRICS, SUM_KEYS, _f, finalize_player, positions_from_store, tally_incidents,
)
from oddsmarkets.football.analytics.pool import ADJUSTED_KEYS

logger = logging.getLogger(__name__)

# The views. Labels are what the page shows.
WINDOWS = {
    "season": "This season (each player's own: 2026/27 in Europe, 2026 in the Americas)",
    "last": "Last season",
    "365": "Last 12 months",
    "ytd": "Calendar year so far",
}
SCOPE_LABELS = {"all": "All competitions", "club": "Club competitions", "intl": "National team"}
# A line needs this many minutes to be written (the lab's slider starts here).
MIN_MINUTES = 90
# Payload paths, relative to the data directory.
LAB_DIR = "lab"
# Files this replaces. The CI restore step copies back any file the checkout lacks from the
# previous deploy, so a retired payload is deleted here, after the build, or it would live on.
RETIRED = ("players_lab.json", "players_lab_365.json", "players_lab_ytd.json", "players_global.json")
ID_FIELDS = ["player_id", "name", "team", "tid", "position", "age", "minutes", "matches", "mix", "factor", "comp"]

# Accumulator layout: SUM_KEYS, then the non-sum slots.
_N = len(SUM_KEYS)
_IDX = {k: i for i, k in enumerate(SUM_KEYS)}
(X_MATCHES, X_STARTS, X_RW, X_RM, X_TOP, X_CONC, X_PADJ, X_YC, X_RC, X_PENS, X_OG) = range(_N, _N + 11)
_WIDTH = _N + 11
_ZERO = array("d", [0.0]) * _WIDTH


def lab_keys() -> list[str]:
    """The metrics a lab line carries: every rate, every percentile metric, the advanced group and the rating."""
    keys = [m["key"] for m in METRICS
            if m["key"].endswith("_90") or m.get("pct") or m["group"] == "Advanced" or m["key"] in ("rating", "xg_per_shot")]
    return list(dict.fromkeys(k for k in keys if k not in ID_FIELDS))


def previous_era(era: str) -> str:
    """The season before: "2026/27" -> "2025/26", "2026" -> "2025"."""
    e = str(era or "")
    if len(e) == 7 and e[4] == "/" and e[:4].isdigit():
        s = int(e[:4]) - 1
        return f"{s}/{(s + 1) % 100:02d}"
    return str(int(e) - 1) if e.isdigit() else e


def _q(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def floor_of(minutes: list[float]) -> int:
    """
    The minutes a line needs to be ranked in one view: FLOOR_SHARE of what the view's regulars
    have played (its 95th percentile of minutes), at least FLOOR_MIN. The competition pages'
    floor is the same share of the minutes a season has offered; a view mixing competitions has
    no single season, so its regulars stand in for it.
    """
    return max(FLOOR_MIN, int(round(FLOOR_SHARE * _q(minutes, 0.95))))


class PeopleLines:
    """Accumulates every store (`add_store`), then writes data/lab/ (`finish`)."""

    def __init__(self, comps: dict[str, dict], today: datetime | None = None, eras: dict[str, str] | None = None,
                 intl_split_month: int = 8, neutral: frozenset | set = frozenset()) -> None:
        from oddsmarkets.football.analytics.unified import current_era

        self.comps = comps
        self.today = today or datetime.now(timezone.utc)
        self.neutral = set(neutral)
        self.intl_split_month = intl_split_month
        cur = eras or {f: current_era(f, self.today) for f in ("split", "calendar")}
        self.eras = {f: (cur[f], previous_era(cur[f])) for f in ("split", "calendar")}
        self.wanted = {f: set(v) for f, v in self.eras.items()}
        self.end = self.today.strftime("%Y-%m-%d")
        self.start = {"365": (self.today - timedelta(days=365)).strftime("%Y-%m-%d"), "ytd": f"{self.today.year}-01-01"}
        self.acc: dict[str, dict[tuple[str, str], array]] = {}             # pid -> (slug, tag) -> accumulator
        self.team: dict[tuple[str, str, str], tuple[str, str, Any]] = {}   # (pid, slug, tag) -> (date, team, tid) of the latest match
        self.meta: dict[str, dict] = {}                                    # pid -> store metadata (first seen)
        self.names: dict[str, tuple[str, str]] = {}                        # pid -> (date, name) of the latest line-up
        self.votes: dict[str, dict[str, int]] = {}
        self.meta_pos: dict[str, str] = {}
        self.first_detail: dict[str, str] = {}

    # -- one competition ------------------------------------------------------------

    def _tags(self, slug: str, date: str, era: str | None) -> list[str]:
        from oddsmarkets.football.analytics.unified import frame_era

        tags: list[str] = []
        scope = (self.comps.get(slug) or {}).get("scope")
        if scope == "international" or slug in self.neutral:
            # In the player's frame by date: both candidates now, the frame picks one at the end.
            s = frame_era("split", date, self.intl_split_month)
            c = frame_era("calendar", date)
            if s in self.wanted["split"]:
                tags.append("S:" + s)
            if c in self.wanted["calendar"]:
                tags.append("C:" + c)
        elif era and (era in self.wanted["split"] or era in self.wanted["calendar"]):
            tags.append("E:" + era)
        if self.start["365"] <= date <= self.end:
            tags.append("365")
        if self.start["ytd"] <= date <= self.end:
            tags.append("ytd")
        return tags

    def add_store(self, slug: str, store: dict, era_of: Callable[[dict], str | None]) -> int:
        """One competition's store; `era_of(match)` is its edition's season (Unified.season_meta). Returns player-matches added."""
        if not store or slug not in self.comps:
            return 0
        matches = store.get("matches") or {}
        for pid, pm in (store.get("players") or {}).items():
            if isinstance(pm, dict):
                self.meta.setdefault(str(pid), {k: pm.get(k) for k in ("sn", "dob", "c", "h", "no") if pm.get(k) is not None})
                if pm.get("pos"):
                    self.meta_pos.setdefault(str(pid), str(pm["pos"]))
        positions = positions_from_store(store)
        sheets = store.get("team_stats") or {}
        incidents = store.get("incidents") or {}
        added = 0
        first = None
        for gid, lineup in (store.get("lineups") or {}).items():
            m = matches.get(str(gid)) or {}
            if not isinstance(lineup, dict) or not isinstance(m, dict) or m.get("superseded_by"):
                continue
            date = str(m.get("date") or "")[:10]
            if not date:
                continue
            first = date if first is None or date < first else first
            try:
                era = era_of(m)
            except Exception:  # noqa: BLE001
                era = None
            tags = self._tags(slug, date, era)
            if not tags:
                continue
            inc = tally_incidents(incidents.get(str(gid)), {})
            sheet = sheets.get(str(gid)) or {}
            home, away, hs, as_ = m.get("home"), m.get("away"), m.get("hs"), m.get("as")
            for pid, p in lineup.items():
                if not isinstance(p, dict):
                    continue
                s = p.get("s") or {}
                mins = _f(s.get("minutesPlayed"))
                if mins <= 0:
                    continue
                pid = str(pid)
                team = p.get("t")
                tid = m.get("home_id") if team == home else m.get("away_id") if team == away else None
                pos = p.get("p")
                if pos:
                    v = self.votes.setdefault(pid, {})
                    v[pos] = v.get(pos, 0) + 1
                contrib: list[tuple[int, float]] = []
                for k, val in s.items():
                    i = _IDX.get(k)
                    if i is not None:
                        fv = _f(val)
                        if fv:
                            contrib.append((i, fv))
                contrib.append((X_MATCHES, 1.0))
                if not p.get("sub"):
                    contrib.append((X_STARTS, 1.0))
                if s.get("rating") is not None:
                    contrib.append((X_RW, _f(s["rating"]) * mins))
                    contrib.append((X_RM, mins))
                # Possession-adjusted tackles + interceptions, as aggregate_players.
                own = (sheet.get("home" if team == home else "away") or {}).get("ballPossession") if sheet else None
                opp = 100.0 - min(max(_f(own), 25.0), 75.0) if own is not None else 50.0
                padj = (_f(s.get("totalTackle")) + _f(s.get("interceptionWon"))) * 50.0 / opp
                if padj:
                    contrib.append((X_PADJ, padj))
                if (pos or positions.get(pid)) == "G" and hs is not None and as_ is not None:
                    against = as_ if team == home else hs
                    contrib.append((X_CONC, _f(against) * min(mins, 90.0) / 90.0))
                t = inc.get(pid) or inc.get(str(p.get("n") or "")) or {}
                for key, slot in (("yellow", X_YC), ("red", X_RC), ("pens", X_PENS), ("own_goals", X_OG)):
                    if t.get(key):
                        contrib.append((slot, float(t[key])))
                top = _f(s.get("topSpeed"))
                per = self.acc.setdefault(pid, {})
                for tag in tags:
                    vec = per.get((slug, tag))
                    if vec is None:
                        vec = per[(slug, tag)] = array("d", _ZERO)
                    for i, v in contrib:
                        vec[i] += v
                    if top > vec[X_TOP]:
                        vec[X_TOP] = top
                    key = (pid, slug, tag)
                    if date >= (self.team.get(key) or ("",))[0]:
                        self.team[key] = (date, team, tid)
                if date >= (self.names.get(pid) or ("",))[0] and p.get("n"):
                    self.names[pid] = (date, str(p["n"]))
                added += 1
        if first and (slug not in self.first_detail or first < self.first_detail[slug]):
            self.first_detail[slug] = first
        return added

    # -- the lines ----------------------------------------------------------------------

    def merge_aliases(self, aliases: dict[str, str]) -> None:
        """Fold genuine duplicate ids (Unified.aliases: same exact name, birth date and nationality) into the canonical id."""
        for alias, canon in aliases.items():
            src = self.acc.pop(alias, None)
            if src:
                dst = self.acc.setdefault(canon, {})
                for key, vec in src.items():
                    if key in dst:
                        _add_into(dst[key], vec)
                    else:
                        dst[key] = vec
                    tk, ak = (canon, key[0], key[1]), (alias, key[0], key[1])
                    if ak in self.team and self.team[ak][0] >= (self.team.get(tk) or ("",))[0]:
                        self.team[tk] = self.team[ak]
            for d in (self.meta,):
                if alias in d:
                    d.setdefault(canon, d[alias])
            if alias in self.votes:
                v = self.votes.setdefault(canon, {})
                for k, n in self.votes.pop(alias).items():
                    v[k] = v.get(k, 0) + n

    def _position(self, pid: str) -> str | None:
        if pid in self.meta_pos:
            return self.meta_pos[pid]
        v = self.votes.get(pid)
        return max(v.items(), key=lambda kv: kv[1])[0] if v else None

    def _line(self, pid: str, vec: array, name: str, team: str | None) -> dict[str, Any]:
        a: dict[str, Any] = dict(zip(SUM_KEYS, vec[:_N]))
        a.update({"name": name, "team": team or "", "shirt": None, "matches": int(vec[X_MATCHES]), "starts": int(vec[X_STARTS]),
                  "_rat_w": vec[X_RW], "_rat_min": vec[X_RM], "top_speed": vec[X_TOP], "_conceded": vec[X_CONC], "_padj": vec[X_PADJ]})
        inc = {"yellow": int(vec[X_YC]), "red": int(vec[X_RC]), "pens": int(vec[X_PENS]), "own_goals": int(vec[X_OG])}
        return finalize_player(pid, a, self.meta.get(pid), self._position(pid), inc, self.today)

    def views(self, frames: dict[str, str]) -> dict[str, dict[str, dict[str, dict]]]:
        """window -> pid -> scope -> (vector, minutes by competition, latest team per competition)."""
        out: dict[str, dict[str, dict[str, dict]]] = {w: {} for w in WINDOWS}
        for pid, per in self.acc.items():
            frame = frames.get(pid) or "calendar"
            cur, prev = self.eras.get(frame, self.eras["calendar"])
            intl_tag = "S:" if frame == "split" else "C:"
            for w in WINDOWS:
                if w in ("season", "last"):
                    era = cur if w == "season" else prev
                    club_tag, nat_tag = "E:" + era, intl_tag + era
                else:
                    club_tag = nat_tag = w
                by_slug: dict[str, array] = {}
                for (slug, tag), vec in per.items():
                    scope = (self.comps.get(slug) or {}).get("scope")
                    want = nat_tag if (scope == "international" or slug in self.neutral) else club_tag
                    if tag == want:
                        by_slug[slug] = vec
                if by_slug:
                    out[w][pid] = {"tag": (club_tag, nat_tag), "slugs": by_slug}
        return out

    def finish(self, data_dir: Path, frames: dict[str, str], people: dict[str, dict] | None = None,
               club_of: dict[str, dict | None] | None = None, clubs: dict[str, dict] | None = None,
               factors: dict[str, float] | None = None) -> dict[str, int]:
        """Write data/lab/index.json, data/lab/<window>/<scope>.json and data/lab/leaders.json; delete the RETIRED files."""
        people = people or {}
        club_of = club_of or {}
        clubs = clubs or {}
        factors = factors or {}
        keys = lab_keys()
        fields = ID_FIELDS + keys
        lab_dir = data_dir / LAB_DIR
        counts: dict[str, int] = {}
        index_scopes: dict[str, dict[str, dict]] = {}
        leaders: dict[str, dict[str, list]] = {}
        comps_seen: set[str] = set()
        written: set[Path] = set()
        short = {s: (c.get("short") or c.get("name") or s) for s, c in self.comps.items()}
        views = self.views(frames)

        def team_name(tid) -> str | None:
            return (clubs.get(str(tid)) or {}).get("name") if tid is not None else None

        for w, persons in views.items():
            files: dict[str, list[list]] = {}
            for pid, view in persons.items():
                ident = people.get(pid) or {}
                name = ident.get("name") or (self.names.get(pid) or ("", ""))[1] or pid
                slugs = view["slugs"]
                club_tag, nat_tag = view["tag"]
                mins = {s: vec[_IDX["minutesPlayed"]] for s, vec in slugs.items()}

                def latest(sl: list[str]) -> tuple[str | None, Any]:
                    best = ("", None, None)
                    for s in sl:
                        tag = nat_tag if ((self.comps.get(s) or {}).get("scope") == "international" or s in self.neutral) else club_tag
                        t = self.team.get((pid, s, tag))
                        if t and t[0] >= best[0]:
                            best = t
                    return best[1], best[2]

                groups: dict[str, list[str]] = {"all": list(slugs)}
                club_slugs = [s for s in slugs if (self.comps.get(s) or {}).get("scope") != "international"]
                intl_slugs = [s for s in slugs if (self.comps.get(s) or {}).get("scope") == "international"]
                if club_slugs:
                    groups["club"] = club_slugs
                if intl_slugs:
                    groups["intl"] = intl_slugs
                for s in slugs:
                    groups[s] = [s]
                for scope, sl in groups.items():
                    total = sum(mins[s] for s in sl)
                    if total < MIN_MINUTES:
                        continue
                    vec = slugs[sl[0]] if len(sl) == 1 else _sum([slugs[s] for s in sl])
                    # The club shown: his current club (UNIFIED_PAYLOADS 2.3) for every competition or club
                    # football, else the latest club of the view; the national team for national-team football;
                    # the team he played for in one competition.
                    cc = (club_of.get(pid) or {}) if scope in ("all", "club") else {}
                    tid = cc.get("tid")
                    team = cc.get("name") or team_name(tid)
                    if tid is None:
                        team, tid = latest((club_slugs or sl) if scope in ("all", "club") else sl)
                        team = team_name(tid) or team
                    line = self._line(pid, vec, name, team)
                    order = sorted(sl, key=lambda s: -mins[s])
                    main = next((s for s in order if s in club_slugs), order[0]) if scope == "all" else order[0]
                    factor = sum(float(factors.get(s, 1.0)) * mins[s] for s in sl) / max(total, 1.0)
                    mix = " · ".join(f"{short.get(s, s)} {int(mins[s])}'" for s in order)
                    age = _age_iso(ident.get("dob"), self.today)
                    row = [pid, name, team, int(tid) if str(tid or "").isdigit() else tid, line.get("position") or ident.get("pos") or ("G" if line.get("is_gk") else None),
                           age if age is not None else line.get("age"), int(line.get("minutes") or 0), int(line.get("matches") or 0), mix,
                           round(factor, 4), main]
                    for k in keys:
                        v = line.get(k)
                        row.append(None if v is None else round(float(v), 3))
                    files.setdefault(scope, []).append(row)
                    comps_seen.update(sl)
                    if w == "season" and scope in SCOPE_LABELS:
                        leaders.setdefault(scope, []).append({"id": pid, "name": name, "team": team, "tid": row[3], "comp": main, "mix": mix,
                                                              "minutes": row[6], "goals": line.get("goals"), "xg": line.get("xg"),
                                                              "assists": line.get("assists"), "xa": line.get("xa"), "rating": line.get("rating")})
            index_scopes[w] = {}
            for scope, rows in files.items():
                rows.sort(key=lambda r: (-r[6], str(r[1])))
                floor = floor_of([r[6] for r in rows])
                path = lab_dir / w / f"{scope}.json"
                _write(path, {"window": w, "scope": scope, "floor": floor, "fields": fields, "rows": rows})
                written.add(path)
                index_scopes[w][scope] = {"n": len(rows), "floor": floor}
                counts[f"{w}/{scope}"] = len(rows)
        # Files of views that no longer exist (a competition with no line this window).
        if lab_dir.exists():
            for f in lab_dir.glob("*/*.json"):
                if f not in written:
                    try:
                        f.unlink()
                    except OSError:
                        pass
        metrics = [{k2: m[k2] for k2 in ("key", "label", "group", "fmt", "scope", "lower", "pct") if k2 in m} for m in METRICS if m["key"] in keys]
        windows = []
        for w, label in WINDOWS.items():
            row: dict[str, Any] = {"key": w, "label": label}
            if w in ("season", "last"):
                i = 0 if w == "season" else 1
                row["eras"] = {"split": self.eras["split"][i], "calendar": self.eras["calendar"][i]}
            else:
                row["start"], row["end"] = self.start[w], self.end
            windows.append(row)
        comps = {s: {"name": (self.comps.get(s) or {}).get("name") or s, "short": short.get(s, s), "kind": (self.comps.get(s) or {}).get("kind"),
                     "scope": (self.comps.get(s) or {}).get("scope"), "factor": round(float(factors.get(s, 1.0)), 4),
                     "first_detail": self.first_detail.get(s)} for s in sorted(comps_seen)}
        _write(lab_dir / "index.json", {
            "windows": windows, "scopes": index_scopes, "scope_labels": SCOPE_LABELS, "comps": comps, "fields": fields,
            "metrics": metrics, "adjusted_keys": list(ADJUSTED_KEYS), "min_minutes": MIN_MINUTES,
            "rule": ("One row per person in every view: his matches in the window, summed across the competitions of the scope "
                     "(every competition, club competitions, national-team football or one competition) and finalised like a "
                     "competition's season line. A season is the player's own (a European's 2026/27, a Brazilian's 2026); an "
                     "international or world-club match counts in it by date. Duplicate Sofascore ids of one person are merged "
                     "(same exact name, date of birth and nationality)."),
            "updated_at": self.today.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        board: dict[str, dict[str, list]] = {}
        for scope, rows in leaders.items():
            board[scope] = {
                "goals": [_lead(r, "goals", "xg") for r in sorted((r for r in rows if r.get("goals")), key=lambda r: (-r["goals"], -(r["xg"] or 0)))[:15]],
                "assists": [_lead(r, "assists", "xa") for r in sorted((r for r in rows if r.get("assists")), key=lambda r: (-r["assists"], -(r["xa"] or 0)))[:15]],
                "rating": [_lead(r, "rating", None) for r in sorted((r for r in rows if r.get("rating") is not None and r["minutes"] >= 450),
                                                                    key=lambda r: (-r["rating"], -r["minutes"]))[:15]],
            }
        _write(lab_dir / "leaders.json", {"window": "season", "label": WINDOWS["season"], "scopes": board,
                                          "updated_at": self.today.strftime("%Y-%m-%dT%H:%M:%SZ")})
        for name in RETIRED:
            try:
                (data_dir / name).unlink()
            except OSError:
                pass
        logger.info("people lines: %s", ", ".join(f"{w} {index_scopes[w].get('all', {}).get('n', 0)} people" for w in WINDOWS))
        return counts


def _lead(r: dict, key: str, extra: str | None) -> dict:
    out = {"id": r["id"], "name": r["name"], "team": r["team"], "tid": r["tid"], "comp": r["comp"], "mix": r["mix"],
           "value": r[key], "minutes": r["minutes"]}
    if extra and r.get(extra) is not None:
        out[extra] = r[extra]
    return out


def _add_into(dst: array, src: array) -> None:
    for i in range(_WIDTH):
        if i == X_TOP:
            if src[i] > dst[i]:
                dst[i] = src[i]
        else:
            dst[i] += src[i]


def _sum(vecs: list[array]) -> array:
    out = array("d", _ZERO)
    for v in vecs:
        _add_into(out, v)
    return out


def _age_iso(dob: str | None, today: datetime) -> int | None:
    try:
        born = datetime.strptime(str(dob)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return int((today - born).days // 365.25)


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
