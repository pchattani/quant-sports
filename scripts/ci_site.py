#!/usr/bin/env python
"""
CI helper for the seven sports sites' GitHub Actions workflows (.github/workflows/<site>.yml in the public build
repo). The workflows run the fetch and build steps themselves; this script does the parts around them, the same
way for every site:

    ctx      --site S                       season ids etc. as KEY=VALUE lines (append to $GITHUB_OUTPUT)
    gate     --site S                       run=true|false: is a game live or within its window (game-window crons)
    restore  --site S --prev DIR            the previous deploy (a shallow clone of the Pages repo at DIR) fills in
                                            payloads and stores the checkout does not have; for the stores the CI
                                            run is the store of record for (Paddock), the newer copy wins
    seed     --site S                       seed-on-miss: when the site's raw inputs are incomplete (a cold or evicted
                                            cache), fetch the full working set the models need before the build
    cachekey --name N --paths P...          key=N-<hash of the files' paths and sizes>: a content key, so an Actions cache
                                            is saved only when its contents changed (not every run)
    guard    --site S                       refuse to deploy from an incomplete working set (a cold or evicted cache
                                            can otherwise publish wrong pages without any step failing)
    deploy   --site S --clone DIR           sync docs/<site>/ into the clone (the same DIR as --prev: one clone per
                                            run) with the site's excludes and prune rules, refuse over 1 GB (GitHub
                                            Pages' limit) or a mass delete, commit "Site update <stamp>" when
                                            something changed, push (never a force push)
    deploy   ... --shadow OUT               plan only: write OUT/report.json (added / removed / changed files against
                                            the live site, JSON field differences of the summary payloads) and copy
                                            the changed and added files to OUT/files/ for inspection; push nothing

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


SEEDS = {"gridiron": seed_gridiron}


def cmd_seed(site: str) -> int:
    f = SEEDS.get(site)
    cmds = f(ctx_for(site)) if f else None
    if not cmds:
        print("working set complete: nothing to seed")
        return 0
    for c in cmds:
        print("seeding:", " ".join(c[1:]), flush=True)
        r = subprocess.run(c, cwd=ROOT)
        if r.returncode != 0:
            print(f"::warning::seed step exited {r.returncode}")
    return 0


# ── sites ────────────────────────────────────────────────────────────────────────────────────────

SITES = {
    "football": {"docs": "site", "repo": "the-quant-footballer", "prune": prune_football, "excluded": (),
                 "guard": guard_payload_floor("site", 2000)},
    "paddock": {"docs": "paddock", "repo": "the-quant-paddock", "prune": None, "excluded": (),
                "newer_wins": ("data/*/store.json", "data/*/sessions/*.json", "data/*/telemetry/*.json"),
                "guard": guard_payload_floor("paddock", 500)},
    "hardwood": {"docs": "hardwood", "repo": "the-quant-hardwood", "prune": prune_hardwood,
                 "excluded": ("shots.json", "stints.json"), "guard": guard_payload_floor("hardwood", 2000)},
    "ace": {"docs": "ace", "repo": "the-quant-ace", "prune": prune_ace, "excluded": (),
            "guard": guard_payload_floor("ace", 2000)},
    "bullpen": {"docs": "bullpen", "repo": "the-quant-bullpen", "prune": prune_bullpen, "excluded": (),
                "guard": guard_payload_floor("bullpen", 2000)},
    "gridiron": {"docs": "gridiron", "repo": "the-quant-gridiron", "prune": prune_gridiron, "excluded": (),
                 "guard": chain(guard_gridiron, guard_payload_floor("gridiron", 2000)),
                 "gate": ("games", "live"), "time_key": "kickoff", "after": timedelta(hours=4, minutes=30)},
    "rink": {"docs": "rink", "repo": "the-quant-rink", "prune": prune_rink, "excluded": (),
             "guard": guard_payload_floor("rink", 2000),
             "gate": ("live", "today", "upcoming"), "time_key": "start", "after": timedelta(hours=3, minutes=30)},
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
    cands = [(d.get("meta") or {}).get("updated_at") if isinstance(d.get("meta"), dict) else None,
             d.get("fetched_at"), d.get("updated_at")]
    return max((str(c) for c in cands if c), default="")


def cmd_restore(site: str, prev: Path) -> int:
    cfg = SITES[site]
    src, dst = prev / "data", ROOT / "docs" / cfg["docs"] / "data"
    if not src.exists():
        print(f"no previous deploy at {prev}: cold build")
        return 0
    added = newer = 0
    patterns = cfg.get("newer_wins", ())
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        target = dst / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            added += 1
        elif patterns and any(PurePosixPath("data", rel.as_posix()).match(pat) for pat in patterns):
            a, b = _stamp_of(p), _stamp_of(target)
            if a and a > b:
                shutil.copy2(p, target)
                newer += 1
    print(f"restored {added} files the checkout did not have; {newer} stores newer on the deployed site")
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


# ── main ─────────────────────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("ctx", "gate", "restore", "seed", "cachekey", "guard", "deploy"))
    ap.add_argument("--site", choices=sorted(SITES))
    ap.add_argument("--name")
    ap.add_argument("--paths", nargs="*", default=[])
    ap.add_argument("--prev", type=Path)
    ap.add_argument("--clone", type=Path)
    ap.add_argument("--shadow", type=Path)
    ap.add_argument("--allow-mass-delete", action="store_true")
    a = ap.parse_args(argv)
    if a.command == "cachekey":
        return cmd_cachekey(a.name, a.paths)
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
    if a.command == "guard":
        problems = SITES[a.site]["guard"](ctx_for(a.site))
        for pr in problems:
            print(f"::error::incomplete working set: {pr}")
        return 1 if problems else 0
    return cmd_deploy(a.site, a.clone, a.shadow, a.allow_mass_delete)


if __name__ == "__main__":
    sys.exit(main())
