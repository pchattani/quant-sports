#!/usr/bin/env python
"""
CI helper for the seven sports sites' GitHub Actions workflows (.github/workflows/<site>.yml in the public build
repo). The workflows run the fetch and build steps themselves; this script does the parts around them, the same
way for every site:

    ctx      --site S                       season ids etc. as KEY=VALUE lines (append to $GITHUB_OUTPUT)
    gate     --site S                       run=true|false: is a game live or within its window (game-window crons)
    restore  --site S --prev DIR            the previous deploy (a shallow clone of the Pages repo at DIR) fills in
                                            payloads and stores the checkout does not have; for the committed inputs
                                            the pipeline keeps updating (stores, registries, calibrations: the
                                            site's newer_wins patterns) the copy with the newer stamp wins; the
                                            persistent logs (LOGS) always come from the deploy. Football restores
                                            only its logs (its build writes every other payload itself)
    seed     --site S                       seed-on-miss: when the site's raw inputs are incomplete (a cold or evicted
                                            cache), fetch the full working set the models need before the build
    cachekey --name N --paths P...          key=N-<hash of the files' paths and sizes>: a content key, so an Actions cache
                                            is saved only when its contents changed (not every run)
    prunecaches --prefix X --keep K         after a save: delete the repo's other Actions caches whose key starts with X,
                                            once K is listed (restores take the newest by prefix, so older copies
                                            are dead weight that pushes the repo past its 10 GB and makes GitHub evict
                                            live keys); needs GITHUB_TOKEN with actions: write
    guard    --site S                       refuse to deploy from an incomplete working set (a cold or evicted cache
                                            can otherwise publish wrong pages without any step failing)
    deploy   --site S --clone DIR           sync docs/<site>/ into the clone (the same DIR as --prev: one clone per
                                            run) with the site's excludes and prune rules, refuse over 1 GB (GitHub
                                            Pages' limit) or a mass delete, commit "Site update <stamp>" when
                                            something changed, push (never a force push)
    deploy   ... --shadow OUT               plan only: write OUT/report.json (added / removed / changed files against
                                            the live site, JSON field differences of the summary payloads) and copy
                                            the changed and added files to OUT/files/ for inspection; push nothing.
                                            Before planning, a persistent log that lost history the live copy still
                                            holds (a cold restore) is merged back from the live copy, with a
                                            warning: no run ever resets a log

The prune rules and the guards mirror scripts/local_sites.py (the PC pipeline), which this replaces site by site.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PAGES_LIMIT = 1_000_000_000
PAGES_WARN = 900_000_000
MASS_DELETE_SHARE = 0.25
MASS_DELETE_MIN = 200
STANDARD_EXCLUDED_DIRS = {"raw"}
STANDARD_EXCLUDED_SUFFIXES = (".tmp",)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ── per-site context (the workflows' "Season" steps) ─────────────────────────────────────────────

def ctx_for(site: str) -> dict:
    today = utcnow().date()
    out: dict = {"today": today, "year": today.year}
    if site == "gridiron":
        from oddsmarkets.nfl import canon
        out["season"] = int(canon.current_season())
    elif site == "rink":
        from oddsmarkets.nhl import canon
        out["season"] = int(canon.current_season())
    elif site == "hardwood":
        from oddsmarkets.basketball import canon
        lg = {}
        for name in canon.LEAGUES:
            s = canon.current_season(name, today)
            a, b = canon.season_window(name, s)
            lg[name] = {"current": int(s), "in_season": a - timedelta(days=14) <= today <= b + timedelta(days=7)}
        out["leagues"] = lg
    elif site == "campus":
        from oddsmarkets.college import canon
        out["leagues"] = {lv: {"current": int(canon.current_season(lv, today)), "in_season": canon.in_season(lv, today)}
                          for lv in canon.LEVELS}
    return out


# ── prune rules (applied to the deploy copy only) ────────────────────────────────────────────────

def prune_football(rel: PurePosixPath, ctx: dict) -> bool:
    # Raw Sofascore stores and the title-odds history stores are build inputs the pages never read; the archive too.
    return rel.name in ("store.json", "history_store.json") or (len(rel.parts) >= 2 and rel.parts[:2] == ("data", "archive"))


def prune_hardwood(rel: PurePosixPath, ctx: dict) -> bool:
    p = rel.parts
    if len(p) >= 5 and p[0] == "data" and p[3] == "games" and p[2].isdigit():
        lg = (ctx.get("leagues") or {}).get(p[1])
        return bool(lg) and int(p[2]) <= int(lg["current"]) - 3
    return False


def prune_campus(rel: PurePosixPath, ctx: dict) -> bool:
    # game pages: the current season and the previous season's postseason only (oddsmarkets/college/PAYLOADS.md);
    # anything older that a past build left behind is not published
    p = rel.parts
    if len(p) >= 5 and p[0] == "data" and p[3] == "games" and p[2].isdigit():
        lv = (ctx.get("leagues") or {}).get(p[1])
        return bool(lv) and int(p[2]) <= int(lv["current"]) - 2
    return False


ACE_MATCH = re.compile(r"-(\d{4})-(?:Q1|Q2|Q3|R128|R64|R32|R16|RR|QF|SF|BR|F|NA)-")


def prune_ace(rel: PurePosixPath, ctx: dict) -> bool:
    p = rel.parts
    if len(p) == 4 and p[0] == "data" and p[1] in ("atp", "wta") and p[2] == "matches" and p[3].endswith(".json"):
        m = ACE_MATCH.search(p[3])
        return bool(m) and int(m.group(1)) <= ctx["today"].year - 2
    return False


BULLPEN_KEEP = {"mlb": 1, "aaa": 1}


def prune_bullpen(rel: PurePosixPath, ctx: dict) -> bool:
    p = rel.parts
    if len(p) >= 5 and p[0] == "data" and p[1] in BULLPEN_KEEP and p[2].isdigit() and p[3] == "games":
        return int(p[2]) <= ctx["today"].year - BULLPEN_KEEP[p[1]]
    if len(p) >= 2 and p[0] == "data" and p[1] == "npb":          # NPB is never published (npb.jp terms)
        return True
    if len(p) >= 2 and p[0] == "assets" and p[-1] in ("npb.js", "npb.css"):
        return True
    return False


def prune_gridiron(rel: PurePosixPath, ctx: dict) -> bool:
    p = rel.parts
    if len(p) >= 4 and p[0] == "data" and p[1].isdigit() and p[2] == "games":
        return int(p[1]) <= int(ctx["season"]) - 2
    return False


def prune_rink(rel: PurePosixPath, ctx: dict) -> bool:
    p = rel.parts
    if len(p) >= 4 and p[0] == "data" and p[1].isdigit() and len(p[1]) == 8 and p[2] == "games":
        cut = (int(ctx["season"]) // 10000 - 2) * 10001 + 1
        return int(p[1]) <= cut
    return False


# ── completeness guards ──────────────────────────────────────────────────────────────────────────

def guard_gridiron(ctx: dict) -> list[str]:
    """The fantasy and awards models read every past season's nflverse play-by-play and the derived play tables;
    without them the build succeeds but publishes different playoff odds and stale fantasy pages
    (docs/HOSTING_MIGRATION.md, dry run finding 2)."""
    season = int(ctx["season"])
    raw, derived = ROOT / "data/nfl/raw", ROOT / "data/nfl/derived"
    problems = []
    missing = [y for y in range(1999, season) if not (raw / "pbp" / f"play_by_play_{y}.parquet").exists()]
    if missing:
        problems.append(f"nflverse play-by-play missing for {len(missing)} seasons ({missing[0]}..{missing[-1]})")
    missing = [y for y in range(1999, season) if not (derived / str(y) / "plays.parquet").exists()]
    if missing:
        problems.append(f"derived play tables missing for {len(missing)} seasons ({missing[0]}..{missing[-1]})")
    for rel in ("pbp_participation", "ftn_charting", "schedules", "players", "rosters"):
        if not (raw / rel / "_manifest.json").exists():
            problems.append(f"nflverse release {rel} not mirrored")
    return problems


def guard_rink(ctx: dict) -> list[str]:
    """Every season's derived events and stints, box scores, MoneyPuck benchmark files and (2021-22 on) EDGE pages:
    the careers, award boards, RAPM, lines and leaders read them; without them past seasons are rebuilt from less
    and the pages change without any step failing (shadow run of 17 Oct 2026)."""
    season = int(ctx["season"])
    raw = ROOT / "data/nhl"
    seasons = [y * 10001 + 1 for y in range(2009, season // 10000)]           # 20092010 .. the previous season
    problems = []
    for what, f in (("derived events", lambda s: raw / "derived" / str(s) / "events.parquet"),
                    ("derived stints", lambda s: raw / "derived" / str(s) / "stints.parquet"),
                    ("MoneyPuck benchmark", lambda s: raw / "moneypuck" / f"shots_{s}.parquet")):
        missing = [s for s in seasons if not f(s).exists() and not (what == "derived stints" and s < 20102011)]
        if missing:                                     # shift charts (and so stints) start in 2010-11
            problems.append(f"{what} missing for {len(missing)} seasons ({missing[0]}..{missing[-1]})")
    missing = [s for s in seasons if not any((raw / "box" / str(s)).glob("*.json.gz"))]
    if missing:
        problems.append(f"box scores missing for {len(missing)} seasons ({missing[0]}..{missing[-1]})")
    missing = [s for s in seasons if s >= 20212022 and not (raw / "edge" / str(s)).exists()]
    if missing:
        problems.append(f"EDGE pages missing for {len(missing)} seasons")
    return problems


def guard_hardwood(ctx: dict) -> list[str]:
    """The walk-forward backtests and, per league, the two latest seasons' play-by-play directories: the
    calibration and win-probability pages use the latest season with play-by-play on the machine (shadow run of
    17 Oct 2026: a cold runner published the 2026 NBA calibration instead of 2027's)."""
    problems = []
    cache, pbp = ROOT / "data/basketball/cache", ROOT / "data/basketball/pbp"
    for lg, v in (ctx.get("leagues") or {}).items():
        if not (cache / f"backtest_{lg}.json").exists():
            problems.append(f"{lg}: walk-forward backtest cache missing")
        cur = int(v["current"])
        for s in (cur - 1, cur):
            d = pbp / lg / str(s)
            if not (d.exists() and any(d.iterdir())) and not (s == cur and not v["in_season"]):
                problems.append(f"{lg} {s}: play-by-play missing")
    return problems


def guard_campus(ctx: dict) -> list[str]:
    """Every season's store per level (the walk-forward backtests, the selection / committee-proxy fits and the
    history pages read them all), every football season's plays (the EP model and the EPA ratings) and the current
    basketball season's play-by-play once games have been played. The stores are in the Actions cache; a cold
    runner seeds them from seed-campus (scripts/push_seed.py --site campus)."""
    from oddsmarkets.college import canon
    stores, plays, pbp = ROOT / "data/college/stores", ROOT / "data/college/cfb/plays", ROOT / "data/college/pbp"
    problems = []
    for lv, v in (ctx.get("leagues") or {}).items():
        cur = int(v["current"])
        missing = [s for s in range(canon.FIRST_SEASON[lv], cur + 1) if not (stores / lv / f"{s}.json.gz").exists()]
        if missing:
            problems.append(f"{lv} stores missing for {len(missing)} seasons ({missing[0]}..{missing[-1]})")
        if lv == "cfb":
            missing = [s for s in range(canon.FIRST_SEASON[lv], cur + 1) if not (plays / f"{s}.json.gz").exists()]
            if missing:
                problems.append(f"cfb plays missing for {len(missing)} seasons ({missing[0]}..{missing[-1]})")
    return problems


def guard_bullpen(ctx: dict) -> list[str]:
    """Every season's Statcast pitch tables (both levels: pitcher projections and Triple-A's preseason projections read
    the past ones), every season's prepared pitch tables (the multi-season models) and the Stats API cache (shadow run of
    17 Oct 2026: a cold runner published empty metric tables and two valuation steps failed)."""
    y = int(ctx["year"])
    sc, prep = ROOT / "data/baseball/statcast", ROOT / "data/baseball/cache/prep"
    problems = []
    for lvl, first in (("mlb", 2015), ("aaa", 2023)):
        missing = [s for s in range(first, y + 1) if not (sc / lvl / f"{s}.parquet").exists()]
        if missing:
            problems.append(f"{lvl} Statcast tables missing for {missing}")
    for lvl, first in (("mlb", 2015), ("aaa", 2023)):
        missing = [s for s in range(first, y + 1) if not any(prep.glob(f"{lvl}_{s}_*.parquet"))]
        if missing:
            problems.append(f"{lvl} prepared pitch tables missing for {missing}")
    if not any((ROOT / "data/baseball/cache/statsapi").glob("*")):
        problems.append("Stats API cache empty")
    # Retrosheet tables (1908-2014): without them history.json is rebuilt from the Statcast seasons alone (shadow run
    # of 19 Oct 2026: 12 seasons instead of 119)
    if sum(1 for _ in (ROOT / "data/baseball/retro/pa").glob("*.parquet")) < 100:
        problems.append("Retrosheet tables missing")
    return problems


def guard_ace(ctx: dict) -> list[str]:
    """The walk-forward backtests, the WTA serve/return stats pages, the Match Charting Project files and this
    year's tennis-data workbooks (shadow run of 17 Oct 2026: a cold runner lost the WTA serve/return tables; and
    tennis-data.co.uk answers 403 to datacenter addresses, so its workbooks come from the PC)."""
    y = int(ctx["year"])
    raw = ROOT / "data/tennis"
    problems = []
    for tour in ("atp", "wta"):
        if not (raw / "cache" / f"backtest_{tour}.json").exists():
            problems.append(f"{tour}: walk-forward backtest cache missing")
        if not any((raw / "td" / tour).glob(f"{y}.xls*")):
            problems.append(f"{tour}: tennis-data workbook for {y} missing")
    if sum(1 for _ in (raw / "wta").glob("*/*")) < 100:
        problems.append("WTA stats pages missing")
    if not (raw / "charting" / "charting-m-matches.csv").exists():
        problems.append("Match Charting Project files missing")
    return problems


def guard_paddock(ctx: dict) -> list[str]:
    """Raw telemetry for every session this year that has a published summary (the summary step would otherwise
    rewrite them from less), and the model caches (the fantasy backtest)."""
    y = int(ctx["year"])
    have = {d.name for d in (ROOT / "data/f1/telemetry" / str(y)).glob("*") if d.is_dir()}
    summaries = {p.stem for p in (ROOT / "docs/paddock/data" / str(y) / "telemetry").glob("*.json")}
    problems = []
    if summaries - have:
        problems.append(f"raw telemetry missing for {len(summaries - have)} of {len(summaries)} summarised sessions")
    if not (ROOT / "data/f1/cache/fantasy").exists():
        problems.append("fantasy backtest cache missing")
    return problems


def guard_payload_floor(site: str, minimum: int):
    """A deploy must not shrink the site to a fraction: the built copy keeps at least `minimum` JSON payloads."""
    def g(ctx: dict) -> list[str]:
        n = sum(1 for _ in (ROOT / "docs" / site / "data").rglob("*.json"))
        return [] if n >= minimum else [f"only {n} JSON payloads under docs/{site}/data (expected at least {minimum})"]
    return g


def chain(*fs):
    def g(ctx: dict) -> list[str]:
        out = []
        for f in fs:
            out += f(ctx)
        return out
    return g


# ── seed-on-miss ──────────────────────────────────────────────────────────────────────────────────

def seed_gridiron(ctx: dict) -> list[list[str]] | None:
    if not guard_gridiron(ctx):
        return None
    # every season's nflverse releases (CC BY 4.0 GitHub release assets; "all" leaves out OverTheCap's contracts)
    # and the derived play tables; the season stores are committed and are not rewritten here
    return [[sys.executable, "scripts/nfl_fetch.py", "--from", "1999", "--to", str(ctx["season"]),
             "--phases", "releases,plays", "--releases", "all"]]


def seed_branch(site: str, guard):
    """Seed-on-miss from the private seed branch `seed-<site>` of the stores repo (scripts/push_seed.py on the PC):
    cloned with the read-only STORES_DEPLOY_KEY, and only files the runner does not have are copied in."""
    def f(ctx: dict):
        if not guard(ctx):
            return None
        return [["SEED_BRANCH", f"seed-{site}"]]
    return f


def _seed_from_branch(branch: str) -> int:
    key = os.environ.get("STORES_DEPLOY_KEY", "")
    repo = os.environ.get("STORES_REPO") or "pchattani/quant-sports-stores"
    if not key:
        print("::error::STORES_DEPLOY_KEY not available: cannot seed")
        return 1
    import base64
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        kf = Path(d) / "k"
        kf.write_bytes(base64.b64decode(key))
        os.chmod(kf, 0o600)
        dest = Path(d) / "seed"
        env = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {kf} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"}
        r = subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", branch, f"git@github.com:{repo}.git", str(dest)],
                           env=env)
        kf.unlink()
        if r.returncode != 0:
            print(f"::error::seed branch {branch} not cloned")
            return 1
        n = 0
        copied: list[Path] = []
        mt_file = dest / ".seed-mtimes.json"
        mtimes = json.loads(mt_file.read_text(encoding="utf-8")) if mt_file.exists() else {}
        if mt_file.exists():
            mt_file.unlink()
        parts: dict[Path, list[Path]] = {}
        for p in dest.rglob("*"):
            if not p.is_file() or ".git" in p.relative_to(dest).parts:
                continue
            m = re.match(r"^(.*)\.seedpart\.(\d{3})$", p.name)
            if m:                                       # a file over 100 MB, stored in pieces
                parts.setdefault(p.parent / m.group(1), []).append(p)
                continue
            t = ROOT / p.relative_to(dest)
            if not t.exists():
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), t)
                copied.append(t)
                n += 1
        for whole, pieces in parts.items():
            t = ROOT / whole.relative_to(dest)
            if t.exists():
                continue
            t.parent.mkdir(parents=True, exist_ok=True)
            with open(t, "wb") as out:
                for piece in sorted(pieces):
                    out.write(piece.read_bytes())
            copied.append(t)
            n += 1
        # the PC's modification times, so the builds' input signatures (size + mtime) match the deployed manifests
        restored = 0
        for t in copied:
            ns = mtimes.get(t.relative_to(ROOT).as_posix())
            if ns:
                os.utime(t, ns=(ns, ns))
                restored += 1
        print(f"seeded {n} files from {branch} ({restored} with the PC's modification times)")
    return 0


SEEDS = {"gridiron": seed_gridiron, "rink": seed_branch("rink", guard_rink),
         "hardwood": seed_branch("hardwood", guard_hardwood), "bullpen": seed_branch("bullpen", guard_bullpen),
         "ace": seed_branch("ace", guard_ace), "paddock": seed_branch("paddock", guard_paddock),
         "campus": seed_branch("campus", guard_campus)}


def cmd_seed(site: str) -> int:
    """Prints seeded=true|false (for $GITHUB_OUTPUT): a seeded run saves its model caches under a new key."""
    f = SEEDS.get(site)
    cmds = f(ctx_for(site)) if f else None
    if not cmds:
        print("working set complete: nothing to seed")
        print("seeded=false")
        return 0
    print("seeded=true")
    for c in cmds:
        if c[0] == "SEED_BRANCH":
            _seed_from_branch(c[1])
            continue
        print("seeding:", " ".join(c[1:]), flush=True)
        r = subprocess.run(c, cwd=ROOT)
        if r.returncode != 0:
            print(f"::warning::seed step exited {r.returncode}")
    return 0


# ── feeds from the PC (sources that block datacenter addresses) ───────────────────────────────────

FEEDS = {"ace": ["data/tennis/td"]}      # tennis-data.co.uk answers 403 to runners: the PC fetches its workbooks


def cmd_feed(site: str) -> int:
    """Copy the PC-fetched inputs of a site from the stores repo's main snapshot (sparse, shallow clone), replacing
    the runner's copies: the snapshot is the newer one (the PC fetches it every hour)."""
    paths = FEEDS.get(site)
    if not paths:
        return 0
    key = os.environ.get("STORES_DEPLOY_KEY", "")
    repo = os.environ.get("STORES_REPO") or "pchattani/quant-sports-stores"
    if not key:
        print("::warning::STORES_DEPLOY_KEY not available: no feed")
        return 0
    import base64
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        kf = Path(d) / "k"
        kf.write_bytes(base64.b64decode(key))
        os.chmod(kf, 0o600)
        dest = Path(d) / "feed"
        env = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {kf} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"}
        r = subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                            f"git@github.com:{repo}.git", str(dest)], env=env)
        if r.returncode == 0:
            r = subprocess.run(["git", "-C", str(dest), "sparse-checkout", "set", *paths], env=env)
        kf.unlink()
        if r.returncode != 0:
            print("::warning::feed not read from the stores repo")
            return 0
        n = 0
        for base in paths:
            for q in (dest / base).rglob("*"):
                if q.is_file():
                    t = ROOT / q.relative_to(dest)
                    if not t.exists() or t.read_bytes() != q.read_bytes():
                        t.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(q, t)
                        n += 1
        print(f"feed: {n} files updated from the stores snapshot ({', '.join(paths)})")
    return 0


# ── sites ────────────────────────────────────────────────────────────────────────────────────────

# ── persistent logs ──────────────────────────────────────────────────────────────────────────────
# Payloads each build appends to, starting from the previous deploy's copy (they are never in the checkout): the
# overview chance logs (oddsmarkets/common/digest.py roll_log: {season: {metric: {"YYYY-MM-DD": {key: p}}}}, one
# snapshot a day, the last CHANCE_LOG_KEEP days) and the Footballer's frozen pre-match chances (build_site_all.py
# _forecast_log: {match id: [h, d, a, kick-off ISO, comp]}, written only before kick-off, kept FORECAST_LOG_DAYS).
CHANCE_LOG_KEEP = 10          # digest.roll_log keep
FORECAST_LOG_DAYS = 9         # build_site_all.FORECAST_LOG_DAYS (tests/test_ci_site_logs.py checks they agree)
LOGS = {
    "football": ("data/forecast_log.json",),
    "paddock": (),            # its movers read season.json title_history, which the build rewrites in full
    "hardwood": ("data/*/chance_log.json",),
    "ace": ("data/*/chance_log.json",),
    "bullpen": ("data/*/chance_log.json",),
    "gridiron": ("data/chance_log.json",),
    "rink": ("data/chance_log.json",),
    "campus": ("data/*/chance_log.json",),
}


def is_log(site: str, rel: str) -> bool:
    """rel: a path under the site root ('data/nba/chance_log.json'); True for one of the site's persistent logs."""
    p = PurePosixPath(rel)
    return any(len(p.parts) == len(PurePosixPath(pat).parts) and p.match(pat) for pat in LOGS.get(site, ()))


def _iso(x):
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def merge_log(name: str, live, new, now: datetime):
    """(merged, lost): the new log with the history it lost from the live one put back, and how many entries that
    was (0: nothing lost, merged is new itself). The build's own entries always win."""
    if not isinstance(live, dict) or not live:
        return new, 0
    new = new if isinstance(new, dict) else {}
    if name == "forecast_log.json":
        lo = now - timedelta(days=FORECAST_LOG_DAYS) + timedelta(hours=2)
        back = {}
        for k, v in live.items():
            if k in new or not isinstance(v, list) or len(v) < 4:
                continue
            ko = _iso(v[3])
            if ko is not None and ko > lo:
                back[k] = v
        return (dict(new, **back), len(back)) if back else (new, 0)
    out, lost = {k: dict(v) for k, v in new.items() if isinstance(v, dict)}, 0
    for season, metrics in live.items():
        if not isinstance(metrics, dict):
            continue
        if season not in out and any(str(k) > str(season) for k in out):
            continue                                            # a new season started: last season's log retires
        cur = out.setdefault(season, {})
        for m, days in metrics.items():
            if not isinstance(days, dict):
                continue
            mine = dict(cur.get(m) or {})
            keep = sorted(set(days) | set(mine))[-CHANCE_LOG_KEEP:]
            miss = [d for d in keep if d not in mine]
            if miss:
                lost += len(miss)
                mine.update({d: days[d] for d in miss})
                cur[m] = {d: mine[d] for d in sorted(mine) if d in keep}
    return (out, lost) if lost else (new, 0)


def repair_logs(site: str, clone: Path, now: datetime | None = None) -> list[str]:
    """Before a deploy: each persistent log on the live site (the clone) that the build's copy lost history from is
    merged back into the build's copy. One line per repaired log; empty when every log kept its history."""
    now = now or utcnow()
    src = ROOT / "docs" / SITES[site]["docs"]
    fixed = []
    for pat in LOGS.get(site, ()):
        for lp in sorted(clone.glob(pat)):
            rel = lp.relative_to(clone).as_posix()
            if not is_log(site, rel):
                continue
            try:
                live = json.loads(lp.read_text(encoding="utf-8"))
            except Exception:
                continue
            tp = src / rel
            try:
                new = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
            except Exception:
                new = {}
            merged, lost = merge_log(lp.name, live, new, now)
            if lost:
                tp.parent.mkdir(parents=True, exist_ok=True)
                tp.write_text(json.dumps(merged, separators=(",", ":")), encoding="utf-8")
                fixed.append(f"{rel}: {lost} entries the build lost were merged back from the live copy")
    return fixed


SITES = {
    "football": {"docs": "site", "repo": "the-quant-footballer", "prune": prune_football, "excluded": (),
                 "restore": "logs", "guard": guard_payload_floor("site", 2000)},
    "paddock": {"docs": "paddock", "repo": "the-quant-paddock", "prune": None, "excluded": (),
                "newer_wins": ("data/*/store.json", "data/*/sessions/*.json", "data/*/telemetry/*.json",
                               "data/calibration.json"),
                "guard": chain(guard_paddock, guard_payload_floor("paddock", 500))},
    "hardwood": {"docs": "hardwood", "repo": "the-quant-hardwood", "prune": prune_hardwood,
                 "newer_wins": ("data/*/calibration.json", "data/*/*/store.json"),
                 "excluded": ("shots.json", "stints.json"),
                 "guard": chain(guard_hardwood, guard_payload_floor("hardwood", 2000))},
    "ace": {"docs": "ace", "repo": "the-quant-ace", "prune": prune_ace, "excluded": (),
            "newer_wins": ("data/*/registry.json", "data/*/calibration.json", "data/*/*/store.json"),
            "guard": chain(guard_ace, guard_payload_floor("ace", 2000))},
    "bullpen": {"docs": "bullpen", "repo": "the-quant-bullpen", "prune": prune_bullpen, "excluded": (),
                "newer_wins": ("data/*/calibration.json", "data/*/*/store.json"),
                "guard": chain(guard_bullpen, guard_payload_floor("bullpen", 2000))},
    "gridiron": {"docs": "gridiron", "repo": "the-quant-gridiron", "prune": prune_gridiron, "excluded": (),
                 "newer_wins": ("data/calibration.json", "data/*/store.json"),
                 "guard": chain(guard_gridiron, guard_payload_floor("gridiron", 2000)),
                 "gate": ("games", "live"), "time_key": "kickoff", "after": timedelta(hours=4, minutes=30)},
    "rink": {"docs": "rink", "repo": "the-quant-rink", "prune": prune_rink, "excluded": (),
             "newer_wins": ("data/calibration.json", "data/*/store.json"),
             "guard": chain(guard_rink, guard_payload_floor("rink", 2000)),
             "gate": ("live", "today", "upcoming"), "time_key": "start", "after": timedelta(hours=3, minutes=30)},
    # The Quant Campus (college): built, not launched; the workflow runs only by hand until the user approves it
    "campus": {"docs": "campus", "repo": "the-quant-campus", "prune": prune_campus, "excluded": (),
               "guard": chain(guard_campus, guard_payload_floor("campus", 3000))},
}


# ── gate ─────────────────────────────────────────────────────────────────────────────────────────

def in_game_window(idx: dict, lists, time_key: str, after: timedelta, now: datetime | None = None) -> bool:
    now = now or utcnow()
    for key in lists:
        for g in idx.get(key) or []:
            if g.get("status") == "live":
                return True
            k = g.get(time_key)
            if not k or g.get("status") == "final":
                continue
            try:
                t = datetime.fromisoformat(str(k).replace("Z", "+00:00"))
            except ValueError:
                continue
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t - timedelta(minutes=30) <= now <= t + after:
                return True
    return False


def cmd_gate(site: str) -> int:
    cfg = SITES[site]
    run = False
    try:
        with urllib.request.urlopen(f"https://pchattani.github.io/{cfg['repo']}/data/index.json?ts={int(time.time())}",
                                    timeout=20) as r:
            idx = json.load(r)
        run = in_game_window(idx, cfg["gate"], cfg["time_key"], cfg["after"])
    except Exception as exc:                                       # no deployed index: leave it to the hourly run
        print(f"index not read: {exc}", file=sys.stderr)
    print(f"run={'true' if run else 'false'}")
    print(f"game window: {run}", file=sys.stderr)
    return 0


# ── restore from the previous deploy ─────────────────────────────────────────────────────────────

def _stamp_of(path: Path) -> str:
    """The newest fetch / update stamp a store carries ('' when none): meta.updated_at, fetched_at, updated_at."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(d, dict):
        return ""
    meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
    cands = [meta.get("updated_at"), meta.get("generated_at"), d.get("fetched_at"), d.get("updated_at"), d.get("generated_at")]
    return max((str(c) for c in cands if c), default="")


def cmd_restore(site: str, prev: Path) -> int:
    cfg = SITES[site]
    src, dst = prev / "data", ROOT / "docs" / cfg["docs"] / "data"
    if not src.exists():
        print(f"no previous deploy at {prev}: cold build")
        return 0
    added = newer = logs = 0
    patterns = cfg.get("newer_wins", ())
    only_logs = cfg.get("restore") == "logs"
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        target = dst / rel
        if is_log(site, "data/" + rel.as_posix()):
            # a persistent log: the deployed copy is the one every build appended to, so it always wins
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            logs += 1
            continue
        if only_logs:
            continue
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            added += 1
        elif patterns and any(PurePosixPath("data", rel.as_posix()).match(pat) for pat in patterns):
            a, b = _stamp_of(p), _stamp_of(target)
            if a and a > b:
                shutil.copy2(p, target)
                newer += 1
    print(f"restored {added} files the checkout did not have; {newer} stores newer on the deployed site; {logs} persistent logs")
    return 0


# ── deploy ───────────────────────────────────────────────────────────────────────────────────────

def is_excluded(rel: PurePosixPath, excluded: tuple) -> bool:
    parts = rel.parts
    if not parts or parts[0] == ".git":
        return True
    if any(p in STANDARD_EXCLUDED_DIRS for p in parts[:-1]):
        return True
    name = parts[-1]
    return name.endswith(STANDARD_EXCLUDED_SUFFIXES) or name in excluded


def scan(root: Path, keep) -> dict[str, int]:
    out: dict[str, int] = {}
    if not root.exists():
        return out
    stack = [root]
    while stack:
        d = stack.pop()
        with os.scandir(d) as it:
            for e in it:
                rel = PurePosixPath(Path(e.path).relative_to(root).as_posix())
                if e.is_dir(follow_symlinks=False):
                    if rel.parts[0] != ".git":
                        stack.append(Path(e.path))
                elif keep(rel):
                    out[str(rel)] = e.stat(follow_symlinks=False).st_size
    return out


def plan(site: str, clone: Path, ctx: dict) -> dict:
    cfg = SITES[site]
    src = ROOT / "docs" / cfg["docs"]
    pruned = 0

    def keep_src(rel):
        nonlocal pruned
        if is_excluded(rel, cfg["excluded"]):
            return False
        if cfg["prune"] and cfg["prune"](rel, ctx):
            pruned += 1
            return False
        return True

    s = scan(src, keep_src)
    d = scan(clone, lambda rel: not is_excluded(rel, cfg["excluded"]))
    added = sorted(r for r in s if r not in d)
    changed = sorted(r for r in s if r in d and (s[r] != d[r] or not filecmp.cmp(src / r, clone / r, shallow=False)))
    removed = sorted(r for r in d if r not in s)
    return {"src": src, "added": added, "changed": changed, "removed": removed, "n_files": len(s), "n_dest": len(d),
            "bytes": sum(s.values()), "pruned": pruned}


def git(args, cwd: Path, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[-600:]}")
    return r


IGNORED_KEYS = re.compile(r"(^|_)(generated|updated|fetched|built|stamp|as_of|asof|time|ts|now)(_|$)|_at$", re.I)


def json_diff(a, b, path="", out=None, limit=60):
    """Field-level differences between two JSON values, ignoring timestamp-like keys."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if IGNORED_KEYS.search(str(k)):
                continue
            if k not in a or k not in b:
                out.append(f"{path}/{k}: {'only live' if k in a else 'only CI'}")
            else:
                json_diff(a[k], b[k], f"{path}/{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} live vs {len(b)} CI")
        for i, (x, y) in enumerate(zip(a, b)):
            json_diff(x, y, f"{path}[{i}]", out, limit)
            if len(out) >= limit:
                break
    elif a != b:
        out.append(f"{path}: {json.dumps(a)[:80]} live vs {json.dumps(b)[:80]} CI")
    return out


def shadow_report(site: str, p: dict, clone: Path, out: Path, max_copy_bytes: int = 300_000_000) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    src = p["src"]
    by_dir: dict[str, dict] = {}
    for kind in ("added", "changed", "removed"):
        for r in p[kind]:
            top = "/".join(r.split("/")[:2]) if r.startswith("data/") else r.split("/")[0]
            by_dir.setdefault(top, {"added": 0, "changed": 0, "removed": 0})[kind] += 1
    field = {}
    for r in p["changed"]:
        if r.endswith(".json") and r.count("/") <= 2 and (src / r).stat().st_size < 5_000_000:
            try:
                d = json_diff(json.loads((clone / r).read_text(encoding="utf-8")),
                              json.loads((src / r).read_text(encoding="utf-8")))
            except Exception as exc:
                d = [f"unreadable: {exc}"]
            field[r] = d
    copied = 0
    for r in p["added"] + p["changed"]:
        size = (src / r).stat().st_size
        if copied + size > max_copy_bytes:
            break
        t = out / "files" / r
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / r, t)
        copied += size
    rep = {"site": site, "stamp": stamp(), "files": p["n_files"], "live_files": p["n_dest"], "bytes": p["bytes"],
           "pruned": p["pruned"], "added": len(p["added"]), "changed": len(p["changed"]), "removed": len(p["removed"]),
           "unchanged_only_in_timestamps": sum(1 for v in field.values() if not v),
           "by_dir": dict(sorted(by_dir.items(), key=lambda kv: -sum(kv[1].values()))),
           "added_sample": p["added"][:200], "removed_sample": p["removed"][:200], "changed_sample": p["changed"][:400],
           "json_field_diffs": field}
    (out / "report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def cmd_deploy(site: str, clone: Path, shadow: Path | None, allow_mass_delete: bool) -> int:
    cfg = SITES[site]
    ctx = ctx_for(site)
    if not (clone / ".git").exists():
        print(f"no clone at {clone}", file=sys.stderr)
        return 1
    for line in repair_logs(site, clone):
        print(f"::warning::persistent log repaired: {line}")
    p = plan(site, clone, ctx)
    delete_n = len(p["removed"])
    print(f"deploy plan: {p['n_files']} files, {p['bytes'] / 1e6:.0f} MB, {len(p['added'])} added, "
          f"{len(p['changed'])} changed, {delete_n} removed (of {p['n_dest']} live), {p['pruned']} pruned")
    if shadow is not None:
        rep = shadow_report(site, p, clone, shadow)
        print(json.dumps({k: rep[k] for k in ("files", "live_files", "added", "changed", "removed", "by_dir")}, indent=1)[:6000])
    if p["bytes"] > PAGES_LIMIT:
        print(f"REFUSED: the copy is {p['bytes'] / 1e6:.0f} MB, over GitHub Pages' 1 GB", file=sys.stderr)
        return 2
    if delete_n > MASS_DELETE_MIN and delete_n > MASS_DELETE_SHARE * max(p["n_dest"], 1) and not allow_mass_delete:
        print(f"REFUSED: would delete {delete_n} of {p['n_dest']} public files", file=sys.stderr)
        return 3
    if p["bytes"] > PAGES_WARN:
        print(f"::warning::the copy is {p['bytes'] / 1e6:.0f} MB, near GitHub Pages' 1 GB")
    if shadow is not None:
        print("shadow run: nothing pushed")
        return 0
    src = p["src"]
    for r in p["added"] + p["changed"]:
        t = clone / r
        if t.is_dir():
            shutil.rmtree(t)
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / r, t)
    for r in p["removed"]:
        try:
            (clone / r).unlink()
        except FileNotFoundError:
            pass
    for dirpath, _dirs, _files in os.walk(clone, topdown=False):
        d = Path(dirpath)
        if d == clone or ".git" in d.relative_to(clone).parts:
            continue
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass
    git(["config", "user.email", "github-actions[bot]@users.noreply.github.com"], clone)
    git(["config", "user.name", "github-actions[bot]"], clone)
    git(["config", "core.quotepath", "off"], clone)
    msg = f"Site update {stamp()}"
    for attempt in range(1, 4):
        git(["add", "-A", "."], clone)
        if git(["diff", "--cached", "--quiet"], clone, check=False).returncode == 0:
            print("deploy: unchanged")
            return 0
        git(["commit", "-q", "-m", msg], clone)
        r = git(["push", "origin", "HEAD:refs/heads/main"], clone, check=False)
        if r.returncode == 0:
            print("deploy: pushed", git(["rev-parse", "--short", "HEAD"], clone).stdout.strip())
            return 0
        print(f"push rejected (attempt {attempt}); refetching", file=sys.stderr)
        time.sleep(10)
        git(["fetch", "--depth", "1", "origin", "main"], clone)
        git(["reset", "--mixed", "-q", "origin/main"], clone)
    print("push failed after 3 attempts", file=sys.stderr)
    return 1


# ── cache keys ───────────────────────────────────────────────────────────────────────────────────

def cmd_cachekey(name: str, paths: list[str]) -> int:
    import hashlib
    h = hashlib.sha256()
    n = 0
    for base in paths:
        b = ROOT / base
        files = [b] if b.is_file() else sorted(q for q in b.rglob("*") if q.is_file()) if b.exists() else []
        for q in files:
            h.update(f"{q.relative_to(ROOT).as_posix()}\t{q.stat().st_size}\n".encode())
            n += 1
    print(f"key={name}-{h.hexdigest()[:16] if n else 'empty'}")
    print(f"files={n}")
    return 0


def _gh_api(method: str, path: str, token: str):
    req = urllib.request.Request(f"https://api.github.com{path}", method=method,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


def list_caches(repo: str, token: str, prefix: str) -> list[dict]:
    out, page = [], 1
    while True:
        _, r = _gh_api("GET", f"/repos/{repo}/actions/caches?per_page=100&page={page}&key={urllib.parse.quote(prefix)}", token)
        rows = (r or {}).get("actions_caches") or []
        out += [c for c in rows if str(c.get("key", "")).startswith(prefix)]
        if len(rows) < 100:
            return out
        page += 1


def cmd_prunecaches(prefix: str, keep: str) -> int:
    """Delete superseded Actions caches of one prefix, keeping `keep` (the key this run saved or restored). Does nothing
    unless `keep` is listed, so a save that did not land never leaves the prefix empty. Never fails the job."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo and prefix and keep and keep.startswith(prefix)):
        print("prunecaches: nothing to do (token, repository, prefix or keep missing)")
        return 0
    try:
        rows = list_caches(repo, token, prefix)
        if not any(c.get("key") == keep for c in rows):
            print(f"prunecaches: {keep} not listed yet; nothing deleted")
            return 0
        gone, freed = 0, 0
        for c in rows:
            if c.get("key") == keep:
                continue
            try:
                _gh_api("DELETE", f"/repos/{repo}/actions/caches/{c['id']}", token)
                gone += 1
                freed += int(c.get("size_in_bytes") or 0)
            except Exception as exc:                            # noqa: BLE001
                print(f"prunecaches: could not delete {c.get('key')}: {exc}")
        print(f"prunecaches: kept {keep}; deleted {gone} older {prefix}* caches ({freed / 1e6:.0f} MB)")
    except Exception as exc:                                    # noqa: BLE001
        print(f"::warning::prunecaches failed: {exc}")
    return 0


# ── main ─────────────────────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("ctx", "gate", "restore", "seed", "feed", "cachekey", "prunecaches", "guard", "deploy"))
    ap.add_argument("--site", choices=sorted(SITES))
    ap.add_argument("--name")
    ap.add_argument("--paths", nargs="*", default=[])
    ap.add_argument("--prev", type=Path)
    ap.add_argument("--clone", type=Path)
    ap.add_argument("--shadow", type=Path)
    ap.add_argument("--allow-mass-delete", action="store_true")
    ap.add_argument("--prefix")
    ap.add_argument("--keep")
    a = ap.parse_args(argv)
    if a.command == "cachekey":
        return cmd_cachekey(a.name, a.paths)
    if a.command == "prunecaches":
        return cmd_prunecaches(a.prefix, a.keep)
    if not a.site:
        ap.error("--site is required")
    if a.command == "ctx":
        c = ctx_for(a.site)
        print(f"year={c['year']}")
        print(f"today={c['today'].strftime('%Y%m%d')}")
        if "season" in c:
            print(f"season={c['season']}")
        for lg, v in (c.get("leagues") or {}).items():
            print(f"{lg}={'true' if v['in_season'] else 'false'}")
            print(f"{lg}_season={v['current']}")
        return 0
    if a.command == "gate":
        return cmd_gate(a.site)
    if a.command == "restore":
        return cmd_restore(a.site, a.prev)
    if a.command == "seed":
        return cmd_seed(a.site)
    if a.command == "feed":
        return cmd_feed(a.site)
    if a.command == "guard":
        problems = SITES[a.site]["guard"](ctx_for(a.site))
        for pr in problems:
            print(f"::error::incomplete working set: {pr}")
        return 1 if problems else 0
    return cmd_deploy(a.site, a.clone, a.shadow, a.allow_mass_delete)


if __name__ == "__main__":
    sys.exit(main())
