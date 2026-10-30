"""
Umpire Scorecards (umpscorecards.com) for The Quant Bullpen: each MLB game's home-plate umpire scorecard as
Umpire Scorecards publishes it (accuracy, expected accuracy, consistency, favour, run impact on each side).

Terms: no terms page (umpscorecards.com/page/terms answers 404; the About page states no licence) and robots.txt is
served by the app (no rules). Approved under the user's unclear-terms rule (30 Oct 2026) and credited on the Bullpen
Terms page and in DATA_LICENSES.md as *Umpire Scorecards (umpscorecards.com)*. No lawsuit by the site over scraping or
data reuse was found (web search, 30 Oct 2026).

Everything from the source goes through this module, behind one switch:

    SOURCE_UMPSCORECARDS_ENABLED=0  -> no fetch, no parse; `season_games` returns {} and the umpire payloads carry no
                                       Umpire Scorecards fields, so the Bullpen shows its own umpire model only.

Fetch: one JSON request per season (`/api/games?startDate=<Y>-01-01&endDate=<Y>-12-31&seasonType=R`, about 2,400
rows), at least 3 s apart, cached under data/baseball/umpscorecards/ (git-ignored), local only. The current season is
re-read at most once a day (`max_age`). Raw rows are never published: the site shows per-umpire aggregates.

No look-ahead: a scorecard is published after its game, so a pre-game use may only aggregate scorecards dated
before the game (`prior_profiles`).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from oddsmarkets.common.polite import ROOT, Source

SRC = Source(name="umpscorecards", base="https://umpscorecards.com", flag="SOURCE_UMPSCORECARDS_ENABLED",
             raw_dir=ROOT / "data" / "baseball" / "umpscorecards", interval=3.0,
             credit="Umpire Scorecards (umpscorecards.com)")
CREDIT = SRC.credit
FIRST_SEASON = 2015
FIELDS = ("game_pk", "date", "type", "umpire", "home_team", "away_team", "called_pitches", "called_correct",
          "called_wrong", "overall_accuracy", "x_overall_accuracy", "accuracy_above_x", "consistency", "favor",
          "home_batter_impact", "away_batter_impact", "total_run_impact", "fully_valid", "failed")


def enabled() -> bool:
    return SRC.enabled()


def season_path(season: int, season_type: str = "R") -> str:
    return f"/api/games?startDate={int(season)}-01-01&endDate={int(season)}-12-31&seasonType={season_type}"


def parse(text: str | None) -> list[dict]:
    """Rows of the games API, trimmed to FIELDS; failed or invalid scorecards dropped."""
    if not text:
        return []
    try:
        d = json.loads(text)
    except ValueError:
        return []
    rows = d.get("rows") if isinstance(d, dict) else d
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or r.get("failed") or r.get("game_pk") is None or not r.get("umpire"):
            continue
        out.append({k: r.get(k) for k in FIELDS})
    return out


def season_games(season: int, fetch: bool = False, client=None, season_type: str = "R") -> dict[str, dict]:
    """{game_pk: row} for a season, from the cache (or the site when `fetch`). {} when the switch is off."""
    if not enabled():
        return {}
    cl = client or SRC.client(offline=not fetch)
    cur = int(season) >= date.today().year
    text = cl.get(season_path(season, season_type), max_age=86400 if (fetch and cur) else None)
    return {str(r["game_pk"]): r for r in parse(text)}


def _agg(rows: list[dict]) -> dict:
    called = sum(int(r.get("called_pitches") or 0) for r in rows)
    correct = sum(int(r.get("called_correct") or 0) for r in rows)
    n = len(rows)

    def mean(k):
        v = [float(r[k]) for r in rows if isinstance(r.get(k), (int, float))]
        return sum(v) / len(v) if v else None
    bat = [float(r["home_batter_impact"]) + float(r["away_batter_impact"]) for r in rows
           if isinstance(r.get("home_batter_impact"), (int, float)) and isinstance(r.get("away_batter_impact"), (int, float))]
    acc_x = mean("accuracy_above_x")
    return {"games": n, "called": called,
            "accuracy": round(correct / called, 4) if called else None,
            "acc_above_x": round(acc_x / 100.0, 4) if acc_x is not None else None,
            "consistency": round(mean("consistency") / 100.0, 4) if mean("consistency") is not None else None,
            "run_impact": round(mean("total_run_impact"), 3) if mean("total_run_impact") is not None else None,
            "favor": round(mean("favor"), 3) if mean("favor") is not None else None,
            "batter_runs": round(sum(bat) / len(bat), 3) if bat else None}


def umpire_season(games: dict[str, dict]) -> dict[str, dict]:
    """{umpire name: season aggregate} from `season_games` rows."""
    by = defaultdict(list)
    for r in games.values():
        by[str(r["umpire"])].append(r)
    return {u: _agg(rs) for u, rs in by.items()}


def prior_profiles(games: dict[str, dict], before: str) -> dict[str, dict]:
    """Per-umpire aggregates of scorecards dated strictly before `before` (YYYY-MM-DD): what was public pre-game."""
    return umpire_season({k: r for k, r in games.items() if str(r.get("date") or "")[:10] < before})


def norm_name(s: str | None) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(ch if ch.isalnum() or ch == " " else " " for ch in t).split())


def raw_dir() -> Path:
    return SRC.raw_dir


# ── derived, publishable table ────────────────────────────────────────────────────────────────────────────
# Per umpire and season aggregates (no per-game rows), written by scripts/usc_fetch.py on the PC and committed, so the
# CI build can show them without the raw cache. Deleting this file (or the switch) removes the source from the site.
DERIVED = Path(__file__).with_name("derived") / "umpscorecards_umpires.json"


def build_derived(first: int = FIRST_SEASON, last: int | None = None) -> dict:
    last = last or date.today().year
    seasons = {}
    for s in range(first, last + 1):
        g = {**season_games(s), **season_games(s, season_type="P")}
        if g:
            seasons[str(s)] = umpire_season(g)
    return {"source": "umpscorecards", "credit": CREDIT, "url": "https://umpscorecards.com",
            "note": "Per umpire and season, aggregated from Umpire Scorecards' per-game scorecards (regular season and "
                    "postseason): accuracy = correct / called pitches; consistency and acc_above_x are means of its "
                    "per-game figures (fractions); run_impact, favor and batter_runs are per-game means.",
            "seasons": seasons}


def write_derived() -> Path | None:
    if not enabled():
        return None
    d = build_derived()
    if not d["seasons"]:
        return None
    DERIVED.parent.mkdir(parents=True, exist_ok=True)
    DERIVED.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    return DERIVED


def load_derived() -> dict | None:
    """The committed table, or None when the switch is off or the file is gone."""
    if not enabled() or not DERIVED.exists():
        return None
    try:
        return json.loads(DERIVED.read_text(encoding="utf-8"))
    except ValueError:
        return None
