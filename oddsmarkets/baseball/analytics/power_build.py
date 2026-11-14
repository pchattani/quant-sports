"""The Bullpen's power rankings: data/power/mlb.json and the site index data/power.json (the shape is
oddsmarkets/common/power.py; the kit's power.js draws it on #/mlb/power and on Home). MLB only: the minor-league
levels have no position catalogue worth ranking yet, and Home shows one league per sport.

Read from the payloads the build has just written (no fetching, no new model):

    index.json                  the clubs (names, colours), the MLB level's current season and phase
    mlb/<S>/teams.json          every club's game log [[gpk, date, gtype, opp, home, runs for, runs against, result, ...]]
                                and our team rating now (values.rating = off_rpg + pit_rpg + def_rpg)
    mlb/<S>/season.json         the standings rows (record, streak, division, chances), the postseason (how far each went)
    mlb/<S>/hitters.json, pitchers.json   every player's season line and WAR (the performers' qualifying rule)

    build(data_root, now=None) -> {"n", "bytes", "max", "leagues"}   (python -m oddsmarkets.baseball.analytics.power_build)

The rating ranked: the season simulation's run-differential rating (models/season_sim.team_ratings, the rating its
rebuilt dates use): each club's regular-season run differential a game, regressed toward average with RATING_G0 (50)
games of prior, in runs a game. Our full team rating (batting, pitching and fielding, the Teams page's power board) is
computed for today only: no payload keeps it through the season, so it cannot be ranked week by week without mixing
two models in every move. It is a stat on each row instead. Parts: run scoring and run prevention, each against the
league's runs a game up to that date; they add up to the rating.

Snapshots, no look-ahead: MLB plays daily, so one snapshot every 7 days, counting back from the latest completed date
(the last date whose regular-season games are all final, cancelled or postponed); the snapshot dated d uses only the
regular-season games dated d or earlier (checked on the 2026 logs: Houston lost 4-14 on 13 Sep; its rating through
12 Sep was -0.216 and the 13 Sep snapshot, -0.265, is the first to carry that game). Now adds every final game since. The postseason
is not in the rating (it is regular season only), so in October and the off-season the snapshots are the regular
season's last ten weeks and the last one reads "Final". The move is always a full week of games.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import power as PW

log = logging.getLogger(__name__)

SITE, SPORT, LEAGUE = "bullpen", "baseball", "mlb"
try:
    from oddsmarkets.baseball.models.season_sim import RATING_G0
except Exception:  # noqa: BLE001  the constant only; the build never fails over it
    RATING_G0 = 50.0
PHASE = {"preseason": "preseason", "regular": "season", "postseason": "postseason", "offseason": "offseason"}
DONE = ("W", "L", "cancelled", "canceled", "postponed", "suspended")
ROUND = {"WC": "Wild Card Series", "DS": "Division Series", "CS": "LCS", "WS": "World Series"}

# position groups: (key, label, short, positions or pitcher role, stats); the headline is WAR (our model) for all
# hitters: the performers' views (analytics/performers.py HITTER_GROUPS); pitchers: role SP / RP
HIT = [("c", "Catchers", "C", {"C"}, ["hr", "ops", "xwoba_n", "framing_runs"]),
       ("1b", "First base", "1B", {"1B"}, ["hr", "ops", "xwoba_n", "oaa"]),
       ("2b", "Second base", "2B", {"2B"}, ["hr", "ops", "sb", "oaa"]),
       ("3b", "Third base", "3B", {"3B"}, ["hr", "ops", "xwoba_n", "oaa"]),
       ("ss", "Shortstops", "SS", {"SS"}, ["hr", "ops", "sb", "oaa"]),
       ("cf", "Centre field", "CF", {"CF"}, ["hr", "ops", "sb", "oaa"]),
       ("of", "Corner outfield", "LF/RF", {"LF", "RF", "OF"}, ["hr", "ops", "xwoba_n", "oaa"]),
       ("dh", "Designated hitters", "DH", {"DH", "TWP"}, ["hr", "ops", "xwoba_n", "barrel_pct"])]
PIT = [("sp", "Starters", "SP", "SP", 300, ["ip", "ra9", "fip", "k_pct", "stuff_plus"]),
       ("rp", "Relievers", "RP", "RP", 120, ["sv", "ra9", "k_pct", "stuff_plus"])]
STAT = {"hr": ("HR", "0", "Home runs"), "ops": ("OPS", "3", "On-base plus slugging"),
        "xwoba_n": ("xwOBA+", "3", "Our expected wOBA from the quality of contact, re-scored in a standard park"),
        "framing_runs": ("Framing runs", "+1", "Runs added by called strikes gained over the league (catchers)"),
        "oaa": ("OAA", "+1", "Outs above average, from our catch-probability model"), "sb": ("SB", "0", "Stolen bases"),
        "barrel_pct": ("Barrel%", "pct1", "Barrels per ball in play"), "ip": ("IP", "1", "Innings pitched"),
        "ra9": ("RA9", "2", "Runs allowed per nine innings (all runs, not just earned)"), "fip": ("FIP", "2", "Fielding-independent pitching"),
        "k_pct": ("K%", "pct1", "Strikeouts per batter faced"), "stuff_plus": ("Stuff+", "0", "Pitch quality from its physical traits alone (100 = average)"),
        "sv": ("SV", "0", "Saves")}


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _label(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _signed(v, n: int = 0) -> str:
    v = PW.num(v)
    if v is None:
        return ""
    return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):.{n}f}"


def reg_games(log_rows: list) -> list[tuple]:
    """[(date, runs for, runs against, "W"|"L")] for a club's final regular-season games, in date order."""
    out = []
    for g in log_rows or []:
        if not isinstance(g, list) or len(g) < 8 or g[2] != "R" or g[7] not in ("W", "L"):
            continue
        d, rf, ra = _d(g[1]), PW.num(g[5]), PW.num(g[6])
        if d is None or rf is None or ra is None:
            continue
        out.append((d, rf, ra, g[7]))
    out.sort(key=lambda x: x[0])
    return out


def last_done(teams: dict) -> date | None:
    """The latest date whose regular-season games are all over (final, cancelled or postponed): a date with a game
    still to finish is not complete, and neither is anything after it."""
    final, pending = set(), set()
    for t in teams.values():
        for g in t.get("log") or []:
            if not isinstance(g, list) or len(g) < 8 or g[2] != "R":
                continue
            d = _d(g[1])
            if d is None:
                continue
            (final if g[7] in DONE else pending).add(d)
    if not final:
        return None
    if pending:
        first_open = min(pending)
        done = [d for d in final if d < first_open]
        return max(done) if done else None
    return max(final)


def ratings_at(games: dict[str, list[tuple]], through: date | None) -> dict[str, dict]:
    """{tid: {"rating", "off", "def", "n"}} from the games dated `through` or earlier (all of them for None): run
    differential a game regressed with RATING_G0 games of prior (season_sim.team_ratings in runs); off and def split it
    around the league's runs a team-game over the same games."""
    tot_r, tot_n, rows = 0.0, 0, {}
    for t, gs in games.items():
        sub = [g for g in gs if through is None or g[0] <= through]
        rs, ra = sum(g[1] for g in sub), sum(g[2] for g in sub)
        rows[t] = (len(sub), rs, ra)
        tot_r += rs
        tot_n += len(sub)
    lg = tot_r / tot_n if tot_n else 0.0
    out = {}
    for t, (n, rs, ra) in rows.items():
        den = n + RATING_G0
        out[t] = {"rating": (rs - ra) / den, "off": (rs - lg * n) / den, "def": (lg * n - ra) / den, "n": n}
    return out


def snapshots(games: dict[str, list[tuple]], done: date | None, offseason: bool) -> tuple[list[dict], list[date | None]]:
    """Snapshot dicts and their cut-off dates (None = now): every 7 days back from `done` while any game was played by
    then, oldest first, then now."""
    first = min((g[0] for gs in games.values() for g in gs), default=None)
    cuts: list[date | None] = []
    if done and first:
        for k in range(PW.MAX_SNAPSHOTS - 1, 0, -1):
            d = done - timedelta(days=7 * k)
            if d >= first:
                cuts.append(d)
    snaps = [{"key": "d" + d.isoformat(), "label": _label(d), "date": d.isoformat()} for d in cuts]
    snaps.append({"key": "now", "label": "Final" if offseason else "Now", "date": done.isoformat() if done else None})
    return snaps, cuts + [None]


def _record(r: dict) -> str | None:
    if PW.num(r.get("w")) is None or PW.num(r.get("l")) is None:
        return None
    return f"{int(r['w'])}–{int(r['l'])}"


def _post_note(pt: dict | None) -> str | None:
    if not pt:
        return None
    if pt.get("champion"):
        return "World Series champions"
    r = ROUND.get(str(pt.get("reached") or ""))
    return ("Lost in the " + r) if r else None


LOWER_FIRST = ("Won", "Lost", "Up", "Down", "Best", "Worst", "New")


def with_post(note: str | None, post: str | None) -> str:
    """The postseason's result first, then the ranking note's lead clause (power.note_for keeps one clause per first
    word, so a "Won 5 straight" would otherwise hide "Won the World Series")."""
    clauses = [c for c in str(note or "").rstrip(".").split("; ") if c]
    if not post:
        return str(note or "")
    if clauses:
        c = clauses[0]
        if c.split(" ")[0] in LOWER_FIRST:
            c = c[0].lower() + c[1:]
        return f"{post}; {c}."
    return post + "."


def _players(hj: dict | None, pj: dict | None, info: dict) -> dict | None:
    groups = []

    def stat_defs(keys):
        return [{"key": k, "label": STAT[k][0], "fmt": STAT[k][1], "tip": STAT[k][2]} for k in keys]

    def colour(p):
        return (info.get(str(p.get("team"))) or {}).get("colour")

    if (hj or {}).get("ok") and isinstance(hj.get("players"), dict):
        f = max(0.0, min(162.0, PW.num(hj.get("team_games")) or 162.0)) / 162.0
        min_pa = 200 * f
        tip = "Bullpen WAR: wins a player has added over a replacement-level player this season (batting, baserunning, fielding, framing and position): our model."
        for key, label, short, pos, stats in HIT:
            rows = [{"id": pid, "name": p.get("name"), "team": p.get("team_abbr") or "", "colour": colour(p),
                     "href": f"#/mlb/hitter/{pid}", "v": p.get("values") or {}}
                    for pid, p in hj["players"].items()
                    if isinstance(p, dict) and p.get("pos") in pos and (PW.num(p.get("pa")) or 0) >= min_pa]
            g = PW.group(key, label, rows, {"key": "war", "label": "WAR", "unit": "", "fmt": "+1", "dir": "higher", "tip": tip},
                         stat_defs(stats), short=short, min_text=f"{round(min_pa)} plate appearances (200 over a full season)")
            if g:
                groups.append(g)
    if (pj or {}).get("ok") and isinstance(pj.get("players"), dict):
        f = max(0.0, min(162.0, PW.num(pj.get("team_games")) or 162.0)) / 162.0
        tip = "Bullpen WAR from runs allowed (RA9) against a replacement-level pitcher in the same role: our model."
        for key, label, short, role, bf, stats in PIT:
            rows = [{"id": pid, "name": p.get("name"), "team": p.get("team_abbr") or "", "colour": colour(p),
                     "href": f"#/mlb/pitcher/{pid}", "v": p.get("values") or {}}
                    for pid, p in pj["players"].items()
                    if isinstance(p, dict) and p.get("role") == role and (PW.num(p.get("bf")) or 0) >= bf * f]
            g = PW.group(key, label, rows, {"key": "war", "label": "WAR", "unit": "", "fmt": "+1", "dir": "higher", "tip": tip},
                         stat_defs(stats), short=short, min_text=f"{round(bf * f)} batters faced ({bf} over a full season)")
            if g:
                groups.append(g)
    return {"noun": "players", "groups": groups} if groups else None


def build(data_root: Path, now: str | None = None) -> dict | None:
    data_root = Path(data_root)
    ix = _read(data_root / "index.json") or {}
    lv = (ix.get("levels") or {}).get(LEAGUE) or {}
    S = lv.get("season") or ix.get("season")
    if not S:
        return None
    base = data_root / LEAGUE / str(S)
    tj = _read(base / "teams.json") or {}
    teams = {str(k): v for k, v in (tj.get("teams") or {}).items() if isinstance(v, dict)}
    if not teams:
        return None
    sj = _read(base / "season.json") or {}
    srow = {}
    for rows in (sj.get("standings") or {}).values():
        for r in rows or []:
            if isinstance(r, dict) and r.get("tid") is not None:
                srow[str(r["tid"])] = r
    info = {str(k): v for k, v in (ix.get("teams") or {}).items() if isinstance(v, dict)}
    for t, v in teams.items():
        info.setdefault(t, {}).update({k: v.get(k) for k in ("name", "abbr", "short", "colour", "division") if v.get(k)})
    phase = PHASE.get(str(lv.get("phase") or sj.get("phase") or tj.get("phase") or ""), "season")
    games = {t: reg_games(v.get("log")) for t, v in teams.items()}
    games = {t: g for t, g in games.items() if g or t in srow}
    done = last_done(teams)
    snaps, cuts = snapshots(games, done, phase == "offseason")
    at = [ratings_at(games, c) for c in cuts]
    now_r = at[-1]
    comp = {t: PW.num((v.get("values") or {}).get("rating")) for t, v in teams.items()}
    comp_rank = PW._ranks({t: v for t, v in comp.items() if v is not None and t in games})
    # how far each club went: only once the season is over (a club still playing has not "lost in" anything yet)
    post = ((sj.get("postseason") or {}).get("teams") or {}) if phase == "offseason" else {}
    parts = [{"key": "off", "label": "Run scoring"}, {"key": "def", "label": "Run prevention"}]
    ents, extra = [], {}
    for t, gs in games.items():
        i, r, tm = info.get(t) or {}, srow.get(t) or {}, teams.get(t) or {}
        if not now_r.get(t, {}).get("n"):
            continue
        rpath = [x.get(t, {}).get("rating") if x.get(t, {}).get("n") else None for x in at]
        last5 = "".join(g[3] for g in gs[-5:])
        rd = PW.num(r.get("rd"))
        if rd is None:
            rd = sum(g[1] - g[2] for g in gs)
        stats = [{"label": "Run diff", "text": _signed(rd)}]
        if comp.get(t) is not None:
            stats.append({"label": "Team rating", "text": _signed(comp[t], 2) + (f" ({PW.ordinal(comp_rank[t])})" if t in comp_rank else "")})
        ent = {"id": t, "name": i.get("name") or tm.get("name") or t, "short": i.get("short") or tm.get("short"),
               "abbr": i.get("abbr") or tm.get("abbr"), "colour": i.get("colour") or tm.get("colour"), "href": f"#/mlb/team/{t}",
               "group": r.get("division") or i.get("division"), "rpath": rpath,
               "record": _record(r) or f"{sum(g[3] == 'W' for g in gs)}–{sum(g[3] == 'L' for g in gs)}",
               "form": last5 or None, "streak": r.get("streak"),
               "parts": {"off": now_r[t]["off"], "def": now_r[t]["def"]}}
        p_ws = PW.num(r.get("p_ws"))
        if phase in ("season", "preseason", "postseason") and p_ws is not None:
            ent["chance"] = {"label": "World Series", "p": round(p_ws, 4)}
            p_po = PW.num(r.get("p_postseason"))
            if phase != "postseason" and p_po is not None:
                stats.append({"label": "Postseason", "text": PW.pct_text(p_po)})
        ent["stats"] = stats[:3]
        pn = _post_note(post.get(t)) if t in post else ("Missed the postseason" if post else None)
        if pn:
            extra[t] = pn
        ents.append(ent)
    rows = PW.teams_block(ents, snaps, parts=parts, step="week", rating_fmt="+2")
    for x in rows:
        if phase == "offseason":       # the last week of a finished season, not "this week"
            x["note"] = str(x.get("note") or "").replace(" this week", " in the final week")
        if extra.get(x["id"]):
            x["note"] = with_post(x.get("note"), extra[x["id"]])
    upd = now or tj.get("updated_at") or _now()
    doc = PW.document(site=SITE, sport=SPORT, league=LEAGUE, label="MLB", season=int(S), season_label=f"{S} season",
                      updated_at=upd, asof=done.isoformat() if done else upd[:10], phase=phase,
                      rating={"label": "Run-differential rating", "short": "RD rating", "unit": "runs a game against an average club", "fmt": "+2",
                              "tip": f"Regular-season run differential a game, regressed toward average with {RATING_G0:.0f} games of prior: the rating our season simulation uses for past dates. Our full team rating (batting, pitching and fielding) is the Team rating on each row; it has no week-by-week history to rank."},
                      snapshots=snaps, teams=rows, step="week", kind="teams", noun="teams", parts=parts,
                      players=_players(_read(base / "hitters.json"), _read(base / "pitchers.json"), info),
                      notes=["Each snapshot uses only the regular-season games played up to and including its date; " +
                             ("the postseason is not in the rating." if phase in ("postseason", "offseason") else "Now adds every game finished since."),
                             "Run scoring and run prevention are measured against the league's runs a game and add up to the rating.",
                             "Players: the regular season, qualified at their position (the rule is under each group); WAR is our model."])
    return PW.write(data_root, [doc], site=SITE, sport=SPORT, updated_at=doc["updated_at"], default=LEAGUE)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "docs" / "bullpen" / "data"
    print(build(root))
