"""Site-wide payloads of The Quant Campus (builder D): data/index.json, data/glossary.json, data/search.json.

Everything here is read from the per-level payloads the football (B) and basketball (C) builders write under
`docs/campus/data/<L>/` (PAYLOADS.md), so this module never fits a model and never touches the network:

    index.json     one block per level: current season, phase, headline, today / next / last games (CARDs),
                   the latest AP top 25, our top 25, title odds (model, with the market where known),
                   conferences, teams, champions, and "digest" ("This week in <level>": level_digest)
    glossary.json  the metric definitions every page uses (the payloads' METRIC lists plus the site's own terms)
    search.json    teams of every level and every player with a career file

A level whose payloads are missing or broken is written as {"ok": false, "reason"} inside index.json (the front
end shows the reason) and is skipped in search; nothing raises.

    from oddsmarkets.college import site
    site.build_all(data_dir, now=None)   # -> {"index": ..., "glossary": n_entries, "search": n_rows}
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import canon
from .packing import unpack

LEVELS = ("cfb", "mbb", "wbb")
NAMES = {"cfb": "College Football", "mbb": "Men's College Basketball", "wbb": "Women's College Basketball"}
SHORT = {"cfb": "CFB", "mbb": "MBB", "wbb": "WBB"}
PHASE_LABEL = {"preseason": "Preseason", "regular": "Regular season", "conf_champ": "Conference championships",
               "bowls": "Bowl season", "playoff": "College Football Playoff", "offseason": "Offseason",
               "conf_tourneys": "Conference tournaments", "ncaa": "NCAA tournament"}


def _now_iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(p: Path) -> Any:
    """A payload with its packed lists expanded (oddsmarkets/college/packing.py), or None."""
    try:
        with open(p, encoding="utf-8") as fh:
            return unpack(json.load(fh))
    except (OSError, ValueError):
        return None


def ok(d: Any) -> bool:
    return isinstance(d, dict) and d.get("ok") is not False


def write(p: Path, obj: Any) -> int:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)
    return p.stat().st_size


def parse_ts(s: Any) -> datetime | None:
    if not s:
        return None
    s = str(s)
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def seasons_built(data: Path, level: str) -> list[int]:
    """Seasons of a level with a readable season.json, newest first."""
    d = data / level
    if not d.exists():
        return []
    out = []
    for p in d.iterdir():
        if p.is_dir() and p.name.isdigit() and ok(load(p / "season.json")):
            out.append(int(p.name))
    return sorted(out, reverse=True)


def _closeness(c: dict) -> float:
    m = c.get("market") or {}
    p = m.get("p_home") if m.get("p_home") is not None else (c.get("model") or {}).get("p_home")
    return abs(p - 0.5) if isinstance(p, (int, float)) else 0.5


def _ranked(c: dict) -> bool:
    return bool(c.get("hr") or c.get("ar") or c.get("hseed") or c.get("aseed"))


_ET = None


def sports_day(t: datetime):
    """The US sports day of an instant: its US Eastern date, with games that start before 5 am Eastern (late
    West Coast and Hawaii games) kept on the evening before, as the scoreboards file them."""
    global _ET
    if _ET is None:
        from zoneinfo import ZoneInfo
        _ET = ZoneInfo("America/New_York")
    return (t.astimezone(_ET) - timedelta(hours=5)).date()


SLATE_MIN = 8                  # games on one sports day that make it a slate (a college football Saturday has 50+)


def next_slate_end(cards: list[dict], now: datetime) -> datetime:
    """The end of the next slate: the last start on the first sports day after today, within a week, with SLATE_MIN or
    more games still to play. On a Sunday to Wednesday in football that is Saturday, so "What to watch" always has
    the coming weekend; in basketball season a slate is usually tomorrow (inside the 3 days anyway). `now` when there
    is none."""
    day0 = sports_day(now)
    by: dict = {}
    for c in cards:
        t = parse_ts(c.get("date"))
        if t is None or c.get("status") != "pre" or not (now < t <= now + timedelta(days=7)):
            continue
        d = sports_day(t)
        if d != day0:
            by.setdefault(d, []).append(t)
    for d in sorted(by):
        if len(by[d]) >= SLATE_MIN:
            return max(by[d])
    return now


def pick_games(cards: list[dict], now: datetime) -> tuple[list, list, list]:
    """today / next_games / last_games of PAYLOADS.md. Today = the US sports day of `now` (`sports_day`: Eastern
    date, games before 5 am Eastern on the evening before; plus anything live), so a Wednesday-night game that ends
    after midnight UTC is not shown as Thursday's; next = the next 3 days (at most 40, ranked and close games
    first), stretched to the end of the next slate (`next_slate_end`: football's Saturday is never left out on a
    Sunday to Wednesday); when nothing falls in that window (preseason), the next 40 games within 3 weeks instead;
    last = the last 2 days before today (at most 40)."""
    today, nxt, last = [], [], []
    day0 = sports_day(now)
    end = max(now + timedelta(days=3), next_slate_end(cards, now))
    for c in cards:
        t = parse_ts(c.get("date"))
        if t is None or c.get("status") in ("canceled", "postponed") and t < now - timedelta(days=2):
            continue
        day = sports_day(t)
        if c.get("status") == "in" or day == day0:
            today.append(c)
        elif now < t <= end and c.get("status") == "pre":
            nxt.append(c)
        elif now - timedelta(days=2) <= t and day < day0 and c.get("status") == "post":
            last.append(c)
    if not today and not nxt:
        nxt = [c for c in cards if c.get("status") == "pre" and (parse_ts(c.get("date")) or now) > now
               and parse_ts(c.get("date")) <= now + timedelta(days=21)]
    nxt.sort(key=lambda c: (not _ranked(c), _closeness(c), c.get("date") or ""))
    nxt = sorted(nxt[:40], key=lambda c: c.get("date") or "")
    last.sort(key=lambda c: (not _ranked(c), c.get("date") or ""))
    last = sorted(last[:40], key=lambda c: c.get("date") or "", reverse=True)
    today.sort(key=lambda c: c.get("date") or "")
    return today, nxt, last


def _record(standings: dict) -> dict[str, str]:
    rec = {}
    for rows in (standings or {}).values():
        for r in rows or []:
            if r.get("team") is not None:
                rec[str(r["team"])] = f"{r.get('w', 0)}-{r.get('l', 0)}"
    return rec


def _market_title(markets: Any, season: int) -> dict[str, float]:
    if not ok(markets) or str(markets.get("season")) != str(season):
        return {}
    fut = markets.get("futures") or {}
    ch = fut.get("champion") or {}
    probs = ch.get("probs") if isinstance(ch, dict) else None
    return {str(k): v for k, v in (probs or {}).items() if isinstance(v, (int, float))}


def headline(level: str, season: dict, title: list[dict], teams: dict, today: list, nxt: list) -> str:
    ph = season.get("phase") or "regular"
    lab = PHASE_LABEL.get(ph, ph.title())
    fav = title[0] if title else None
    fav_s = ""
    if fav:
        t = teams.get(fav["team"]) or {}
        fav_s = f"{t.get('short') or t.get('name') or fav['team']} lead the title chances at {round(fav['p'] * 100)}%"
    if level == "cfb" and season.get("week") and ph == "regular":
        return f"Week {season['week']}" + (f" · {fav_s}" if fav_s else " · CFP chances after Saturday")
    if ph == "preseason":
        when = min((parse_ts(c.get("date")) for c in today + nxt if parse_ts(c.get("date"))), default=None)
        return ("Tip-off " + f"{when:%a} {when.day} {when:%b}" if when else lab) + (f" · {fav_s}" if fav_s else " · preseason ratings")
    return lab + (f" · {fav_s}" if fav_s else "")


# ───────────────────────────────────────────────────────────── this week (the overview's digest)
LEAGUE = {"cfb": "CFB", "mbb": "MBB", "wbb": "WBB"}
_CFP_STAGE = {"first round": "playoff", "quarterfinal": "quarter", "semifinal": "semi", "championship": "final",
              "national championship": "final"}
_NCAA_STAGE = {"elite 8": "quarter", "elite eight": "quarter", "regional final": "quarter", "final four": "semi",
               "national semifinal": "semi", "national championship": "final", "championship": "final", "final": "final"}


def _game_sig(level: str, c: dict, sim: dict, teams: dict) -> dict:
    """featured.py's sig for one card: AP ranks, the title and playoff (CFP / NCAA field) chances in our season
    simulation, the stage of a playoff or tournament game, exhibitions, rivalries."""
    from oddsmarkets.common import featured as FT
    h, a = str(c.get("home")), str(c.get("away"))
    sh, sa = sim.get(h) or {}, sim.get(a) or {}
    po = "p_cfp" if level == "cfb" else "p_ncaa"
    sig = {"comp": LEAGUE[level], "ranks": [c.get("hr"), c.get("ar")], "title": [sh.get("p_title"), sa.get("p_title")]}
    st, rd = c.get("stype"), str(c.get("round") or "").strip().lower()
    if st == "reg":
        sig["playoff"] = [sh.get(po), sa.get(po)]
    elif st == "conf":                              # a conference title game: the playoff place often rides on it
        if level == "cfb" or rd in ("championship", "final", "finals", "f"):
            sig["stage"] = "conf_final"              # football's one game, basketball's tournament final (not its early rounds)
        sig["playoff"] = [sh.get(po), sa.get(po)]
    elif st == "cfp":
        sig["stage"] = _CFP_STAGE.get(rd, "playoff")
    elif st == "ncaa":
        sig["stage"] = _NCAA_STAGE.get(rd, "knockout")
    elif st in ("pre", "exh"):
        sig["preseason"] = True
    nm = lambda t: str((teams.get(t) or {}).get("short") or (teams.get(t) or {}).get("name") or t)
    rv = FT.RIVALRIES.get(frozenset((nm(h), nm(a))))
    if rv:
        sig["rivalry"] = rv
    return sig


def _et_day(s: Any) -> str | None:
    """The US Eastern calendar date of a start ("2026-11-02"): a TBA game's midnight-Eastern placeholder keeps its day."""
    t = parse_ts(s)
    if t is None:
        return None
    sports_day(t)                                   # loads the Eastern zone
    return t.astimezone(_ET).date().isoformat()


RACE_LOG_KEEP = 400            # days: a whole season (scripts/ci_site.py RACE_LOG_KEEP restores it in full)
RACE_METRICS = {"cfb": ("p_cfp", "p_title", "p_conf"), "mbb": ("p_ncaa", "p_title", "p_conf_reg"),
                "wbb": ("p_ncaa", "p_title", "p_conf_reg")}


def write_race_log(data: Path, level: str, cur: int, sim: dict, now: datetime, floor: float | None = None) -> dict | None:
    """<L>/race_log.json: {season: {metric: {"YYYY-MM-DD": {team: p}}}}, one snapshot a UTC day of every team's
    playoff / tournament, title and conference chance at `floor` or more (default 1% for football, 2% for basketball's
    360-team fields), kept the whole season. The standings race
    tab draws its forecast lines from it ("tracking since" its first day). Snapshots of this build's sims only, never
    rebuilt or revised, so no look-ahead. None (nothing written) without sims."""
    from oddsmarkets.common import digest as DG
    if floor is None:
        floor = 0.01 if level == "cfb" else 0.02
    cur_p = {m: {str(t): v.get(m) for t, v in (sim or {}).items()
                 if isinstance(v, dict) and isinstance(v.get(m), (int, float)) and v.get(m) >= floor}
             for m in RACE_METRICS.get(level, ())}
    if not any(cur_p.values()):
        return None
    lp = data / level / "race_log.json"
    old = load(lp) or {}
    log_s = (old.get(str(cur)) or {}) if isinstance(old, dict) else {}
    if not log_s:                                   # first build: start from the digest's chance log (same snapshots)
        ch = load(data / level / "chance_log.json") or {}
        ch = (ch.get(str(cur)) or {}) if isinstance(ch, dict) else {}
        log_s = {m: {d: {t: p for t, p in (v or {}).items() if isinstance(p, (int, float)) and p >= floor}
                     for d, v in (ch.get(m) or {}).items()} for m in cur_p if ch.get(m)}
    new_log = {m: DG.roll_log(log_s.get(m), now, cur_p[m], keep=RACE_LOG_KEEP, digits=3) for m in cur_p}
    write(lp, {str(cur): new_log})
    return new_log


def level_digest(data: Path, level: str, cur: int, cards: list[dict], season: dict, now: datetime) -> dict:
    """index.json levels.<L>.digest: "This week in <level>" (oddsmarkets/common/digest.py: our record this week, the
    upset of the week, the team of the week, the biggest movers in our playoff / tournament chance from the chance
    log, the stage) and the games that matter most (oddsmarkets/common/featured.py rank_featured: "today" within
    18 hours, "next" the best of the coming week after those, "week" the biggest occasion).

    A finished game's chance is the card's: the walk-forward pregame prediction (ratings from the games before its
    day), so no look-ahead. <L>/chance_log.json keeps one snapshot a day of every team's title and playoff chance
    above half a percent; the front end never reads it."""
    from oddsmarkets.common import digest as DG
    from oddsmarkets.common import featured as FT
    sim = ((season.get("sim") or {}).get("teams") or {})
    teams = season.get("teams") or {}
    phase = season.get("phase") or "regular"
    st = lambda c: "final" if c.get("status") == "post" else "live" if c.get("status") == "in" else "pre"
    games = [{"id": c.get("id"), "sport": "college", "league": LEAGUE[level], "start": c.get("date"), "status": st(c), "home": c.get("home"),
              "away": c.get("away"), "hs": c.get("hs"), "as": c.get("as"), "p_home": (c.get("model") or {}).get("p_home")}
             for c in cards if c.get("stype") not in ("pre", "exh")]
    out: dict = {"asof": _now_iso(now)[:16] + "Z"}
    rec = DG.record(games, now)
    if rec:
        rec.pop("by", None)
        out["record"] = rec
    up = DG.upset(games, now)
    if up:
        uc = next((c for c in cards if str(c.get("id")) == str(up["id"])), {})
        wr, lr = (uc.get("hr"), uc.get("ar")) if up["side"] == "home" else (uc.get("ar"), uc.get("hr"))
        if wr or lr:
            up["ranks"] = [wr, lr]                      # AP ranks of the winner and the loser at the time
        out["upset"] = up
    hot = DG.hot(games, now)
    if hot:
        out["hot"] = hot
    po = "p_cfp" if level == "cfb" else "p_ncaa"
    metric = "p_title" if phase in ("playoff", "ncaa", "bowls") else po
    cur_p = {m: {str(t): v.get(m) for t, v in sim.items() if isinstance(v, dict) and isinstance(v.get(m), (int, float)) and v.get(m) >= 0.005}
             for m in (po, "p_title")}
    lp = data / level / "chance_log.json"
    old = load(lp) or {}
    log_s = (old.get(str(cur)) or {}) if isinstance(old, dict) else {}
    new_log = {m: DG.roll_log(log_s.get(m), now, cur_p[m]) for m in cur_p}
    if any(cur_p.values()):
        write(lp, {str(cur): new_log})
    write_race_log(data, level, cur, sim, now)
    if phase != "offseason":
        mv = DG.movers(new_log.get(metric), cur_p.get(metric) or {}, now)
        if mv:
            out["movers"] = dict(mv, metric=metric)
    reg = [c for c in cards if c.get("stype") == "reg" and c.get("date")]
    if reg:
        # the first and last day from games with a set start (a TBA game's placeholder time is not a tip-off)
        days = sorted(_et_day(c["date"]) for c in reg if not c.get("tba") and _et_day(c["date"])) or             sorted(_et_day(c["date"]) for c in reg if _et_day(c["date"]))
        weeks = [c.get("week") for c in reg if isinstance(c.get("week"), int)]
        out["stage"] = {"phase": phase, "played": sum(1 for c in reg if c.get("status") == "post"), "total": len(reg), "first": days[0],
                        "last": days[-1], "week": season.get("week") if level == "cfb" else None, "weeks": max(weeks) if weeks else None}
    fg = [{"sport": "college", "league": LEAGUE[level], "id": c.get("id"), "start": c.get("date"), "status": st(c), "home": str(c.get("home")),
           "away": str(c.get("away")), "p_home": (c.get("model") or {}).get("p_home"), "sig": _game_sig(level, c, sim, teams)}
          for c in cards if c.get("status") in ("pre", "in") and not c.get("tba")]
    r = FT.rank_featured(fg, now)
    nxt = FT.rank_featured(fg, now, horizon_h=24 * 7, limit=8)["today"]
    row = lambda x: {"id": str(x["key"].split(":", 1)[1]), "score": x["score"], "why": x.get("reasons") or []}
    seen = {y["key"] for y in r["today"]}
    out["featured"] = {"today": [row(x) for x in r["today"]], "next": [row(x) for x in nxt if x["key"] not in seen],
                       "week": row(r["week"]) if r.get("week") else None}
    return out


def level_index(data: Path, level: str, now: datetime) -> dict:
    seasons = seasons_built(data, level)
    if not seasons:
        return {"ok": False, "reason": f"no {level} season payloads built", "name": NAMES[level], "short": SHORT[level],
                "sport": canon.sport(level)}
    want = canon.current_season(level, now.date())
    cur = want if want in seasons else seasons[0]
    season = load(data / level / str(cur) / "season.json") or {}
    sched = load(data / level / str(cur) / "schedule.json")
    cards = (sched or {}).get("games") or [] if ok(sched) else []
    teams = season.get("teams") or {}
    today, nxt, last = pick_games(cards, now)
    dig = _digest_safe(data, level, cur, cards, season, now)
    nxt = with_featured(cards, today, nxt, dig.get("featured") or {})
    ap = ((season.get("polls") or {}).get("ap") or [])[:25]
    rec = _record(season.get("standings") or {})
    top25 = [{"rank": r.get("rank"), "team": str(r.get("team")), "prev": r.get("prev"), "record": rec.get(str(r.get("team")))} for r in ap]
    power = season.get("power") or []
    model_top = [{"rank": r.get("rank"), "team": str(r.get("team")), "rating": r.get("rating")} for r in power[:25] if isinstance(r, dict)]
    if not model_top:
        R = season.get("ratings") or {}
        order = sorted((t for t in R if isinstance((R[t] or {}).get("rating"), (int, float))), key=lambda t: -R[t]["rating"])[:25]
        model_top = [{"rank": i + 1, "team": t, "rating": R[t]["rating"]} for i, t in enumerate(order)]
    sim = ((season.get("sim") or {}).get("teams") or {})
    mk = _market_title(load(data / level / "markets.json"), cur)
    title = sorted(({"team": str(t), "p": v.get("p_title"), "market": mk.get(str(t))} for t, v in sim.items()
                    if isinstance(v, dict) and isinstance(v.get("p_title"), (int, float)) and v.get("p_title") > 0),
                   key=lambda r: -r["p"])[:12]
    hist = load(data / level / "history.json")
    champs = [[c.get("season"), str(c.get("team"))] for c in (hist or {}).get("champions") or [] if ok(hist) and c.get("team")]
    confs = {str(c): {"name": v.get("name"), "short": v.get("short")} for c, v in (season.get("conferences") or {}).items()}
    used = {str(c.get(k)) for c in today + nxt + last for k in ("home", "away")}
    used |= {r["team"] for r in top25 + model_top + title} | {str(c[1]) for c in champs}
    # alt: the kit's name for the second colour (MIGRATION_V4); alt_colour stays for the site's own JS
    team_out = {str(t): {**{k: v.get(k) for k in ("name", "short", "abbr", "colour", "alt_colour", "conference", "member")},
                         "alt": v.get("alt") or v.get("alt_colour")}
                for t, v in teams.items() if v.get("member") or str(t) in used}
    return {"ok": True, "name": NAMES[level], "short": SHORT[level], "sport": canon.sport(level), "current_season": cur,
            "seasons": seasons, "phase": season.get("phase"), "week": season.get("week") if level == "cfb" else None,
            "headline": headline(level, season, title, teams, today, nxt), "today": today, "next_games": nxt,
            "last_games": last, "top25": top25, "model_top": model_top, "title_odds": title, "conferences": confs,
            "teams": team_out, "champions": champs, "digest": dig}


def with_featured(cards: list[dict], today: list, nxt: list, featured: dict) -> list:
    """next_games plus any featured game (digest.featured: today / next / week) not already listed, in date order:
    the overview's hero and "What to watch" read their cards from today + next_games, so a featured game outside
    the window would otherwise vanish from the page."""
    have = {str(c.get("id")) for c in today + nxt}
    want = [str(f.get("id")) for k in ("today", "next") for f in (featured.get(k) or []) if f]
    if featured.get("week"):
        want.append(str(featured["week"].get("id")))
    add = [c for c in cards if str(c.get("id")) in set(want) - have]
    return sorted(nxt + add, key=lambda c: c.get("date") or "") if add else nxt


def _digest_safe(data: Path, level: str, cur: int, cards: list[dict], season: dict, now: datetime) -> dict:
    try:
        return level_digest(data, level, cur, cards, season, now)
    except Exception:  # noqa: BLE001 - the digest never takes the level's index block down
        return {}


def build_index(data: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    levels = {}
    for L in LEVELS:
        try:
            levels[L] = level_index(data, L, now)
        except Exception as exc:  # one level failing never takes the others down
            levels[L] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "name": NAMES[L], "short": SHORT[L],
                         "sport": canon.sport(L)}
    return {"ok": True, "updated_at": _now_iso(now), "levels": levels}


# ───────────────────────────────────────────────────────────── glossary
SITE_TERMS = [
    ("Ratings", [
        ("rating", "Rating", "Football: expected points margin against an average FBS team on a neutral field. Basketball: "
                             "adjusted efficiency margin, points per 100 possessions against an average Division I team."),
        ("off", "Offence", "Points (football: per game; basketball: per 100 possessions) the offence adds against average opposition."),
        ("def", "Defence", "Points allowed against average opposition; lower is better."),
        ("se", "Uncertainty (±)", "Standard error of the rating: how far it could be off with the games played so far."),
        ("sos", "Strength of schedule", "Mean rating of the opponents a team has played and still has to play."),
        ("tempo", "Tempo", "Possessions per 40 minutes (basketball)."),
        ("epa", "EPA", "Expected points added: the change in expected points a play produces, from field position, down and distance."),
        ("sr", "Success rate", "Share of plays that gain at least half the yards needed on first down, 70% on second, all on third or fourth."),
    ]),
    ("Games", [
        ("p_home", "Win probability", "The model's pregame chance the home side wins, from the two ratings, home field and rest."),
        ("spread_fair", "Model margin", "The points margin the model expects, written the way a points spread is (the favourite negative)."),
        ("market", "Market", "A reference beside our forecast: a prediction market's probability with its margin removed (Kalshi, Polymarket), or the closing line ESPN shows."),
        ("edge", "Model v market", "Our probability minus the market's, in percentage points: where the model and the market disagree, shown for reference."),
        ("ats", "Against the spread", "Whether a team beat the closing line; the model's side 'covers' when its pick beats the spread."),
        ("wp", "Win probability chart", "The chance of winning after each play; the steepest swings are the game's highest-leverage moments."),
    ]),
    ("Season", [
        ("sim", "Season simulation", "Every remaining game played thousands of times from the ratings, with uncertainty in the ratings themselves."),
        ("p_cfp", "Playoff chance", "Share of simulated seasons a team makes the 12-team College Football Playoff."),
        ("committee", "Committee proxy", "A model of the CFP selection committee's ranking fitted on its past rankings; an estimate of how the committee may see a team, not a prediction of its decision."),
        ("bracketology", "Bracketology", "The projected NCAA tournament field and seeds from simulated seasons and a selection model fitted on past fields."),
        ("p_round", "Reach round", "Share of simulated tournaments in which a team reaches the round."),
        ("upset", "Upset chance", "The chance the lower seed wins a game."),
    ]),
    ("Players", [
        ("value", "Value", "Football: EPA above replacement. Basketball: box-score value above replacement, scaled so a team's players add up to its margin."),
        ("pctl", "Percentile", "Where a player or team ranks among qualified peers, 0 (lowest) to 100 (highest)."),
        ("transfer", "Inferred transfer", "The same ESPN athlete id on a different team from one season to the next. Inferred from box scores and rosters; not the official transfer portal."),
        ("fantasy", "Fantasy projection", "Expected fantasy points for the coming period from usage, efficiency and the opponent; formats PPR, half-PPR and standard (football) and points leagues (basketball)."),
    ]),
]


def build_glossary(data: Path) -> dict:
    groups = [{"name": n, "entries": [{"key": k, "label": lab, "desc": d} for k, lab, d in rows]} for n, rows in SITE_TERMS]
    seen = {e["key"] for g in groups for e in g["entries"]}
    extra = []
    for L in LEVELS:
        for S in seasons_built(data, L)[:1]:
            for f in ("teams.json", "players.json"):
                d = load(data / L / str(S) / f)
                if not ok(d):
                    continue
                for m in d.get("metrics") or []:
                    k = m.get("key")
                    if not k or not m.get("desc"):
                        continue
                    key = f"{L}:{k}" if k in seen else k
                    if key in seen:
                        continue
                    seen.add(key)
                    extra.append({"key": key, "label": f"{m.get('label') or k} ({SHORT[L]})", "desc": m["desc"]})
    if extra:
        groups.append({"name": "Metrics", "entries": sorted(extra, key=lambda e: e["label"].lower())})
    return {"ok": True, "groups": groups}


# ───────────────────────────────────────────────────────────── search
def build_search(data: Path, index: dict) -> list[dict]:
    rows: list[dict] = []
    for L in LEVELS:
        li = (index.get("levels") or {}).get(L) or {}
        if not li.get("ok"):
            continue
        confs = li.get("conferences") or {}
        top = {r["team"]: r["rank"] for r in li.get("model_top") or []}
        for tid, t in (li.get("teams") or {}).items():
            if not t.get("member"):
                continue
            c = confs.get(str(t.get("conference"))) or {}
            rows.append({"t": t.get("name") or tid, "s": f"{SHORT[L]} team" + (f" · {c.get('short') or c.get('name')}" if c else ""),
                         "href": f"#/{L}/team/{tid}", "sport": "college", "w": round(30 - top[tid], 1) if tid in top else 0})
        pdir = data / L / "players"
        have = {p.stem for p in pdir.glob("*.json")} if pdir.exists() else set()
        if not have:
            continue
        names: dict[str, tuple] = {}
        for S in sorted(li.get("seasons") or [], reverse=True)[:2]:
            cat = load(data / L / str(S) / "players.json")
            if not ok(cat):
                continue
            for pid, p in (cat.get("players") or {}).items():
                if pid in have and pid not in names:
                    team = (li.get("teams") or {}).get(str(p.get("team"))) or {}
                    v = (p.get("values") or {}).get("value", (p.get("values") or {}).get("epa"))
                    names[pid] = (p.get("name"), p.get("pos"), team.get("short") or team.get("name"), v)
        for pid in have - set(names):
            d = load(pdir / f"{pid}.json")
            if ok(d) and d.get("name"):
                cur = d.get("current") or {}
                team = (li.get("teams") or {}).get(str(cur.get("team"))) or {}
                names[pid] = (d.get("name"), d.get("pos"), team.get("short") or team.get("name"), None)
        for pid, (nm, pos, team, v) in names.items():
            if not nm:
                continue
            sub = " · ".join(x for x in (SHORT[L], pos, team) if x)
            rows.append({"t": nm, "s": sub, "href": f"#/{L}/player/{pid}", "sport": "college",
                         "w": round(float(v), 2) if isinstance(v, (int, float)) else 0})
    return rows


def build_all(data: Path | str, now: datetime | None = None) -> dict:
    """Write index.json, glossary.json and search.json under `data`; returns a summary."""
    data = Path(data)
    idx = build_index(data, now)
    write(data / "index.json", idx)
    glo = build_glossary(data)
    write(data / "glossary.json", glo)
    rows = build_search(data, idx)
    write(data / "search.json", rows)
    return {"levels": {L: bool(v.get("ok")) for L, v in idx["levels"].items()},
            "glossary": sum(len(g["entries"]) for g in glo["groups"]), "search": len(rows)}
