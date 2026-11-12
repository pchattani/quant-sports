#!/usr/bin/env python
"""
Live win chances for the live-score feed, from each site's OWN live model: the same code and the same fitted numbers
the site build uses, run between builds on the games in progress. The feed (scripts/live_feed.py) carries scores; this
adds "wp" (the home side's chance) to the entries of the games it can compute, so a live card shows a live chance for
the score it shows instead of falling back to the pregame one.

    python scripts/live_chances.py --feed site/live.json --state state.json

It runs after each feed tick, from a checkout of the public build repo (it imports the oddsmarkets package and needs
its dependencies; the feed itself does not). It prints one JSON line {"changed": bool, "n": games with a chance,
"calls": summaries fetched}. With no game in progress it returns at once, before any heavy import. A failure of any
kind leaves the feed as the tick wrote it.

Sites (one at a time; the others keep the hourly build's chance until theirs is added):
  Hardwood (NBA, WNBA)   oddsmarkets.basketball.models.winprob.live_now on the game's latest play (ESPN summary ->
                         sources.espn.compact_pbp, compact_game: what the build stores). The model is the one the
                         last build published (index.json leagues.<L>.wp_model: K and beta) and no other: the public
                         build refits it on the seasons it has on disk, so the committed fitted file is a slightly
                         different model (about one point of chance apart, measured 12 Nov 2026) and is never used
                         here. The pregame expected margin is the one the build published on the game's card
                         ("wp_s", the stored line), else the summary's own line. No published model, no chance.
  Gridiron (NFL)         oddsmarkets.nfl.models.live.live_wp on the game's ESPN summary (sources.espn.compact_summary:
                         the record the build reads), with the pregame margin the build published on the game's card
                         ("wp_mu"). The model is a committed fit (a LightGBM booster the build cannot refit), so it is
                         used only when this checkout's fit and game parameters carry the keys the build published
                         (index.json models.fits.wp, models.game_params). Keys differ, or the card is not published:
                         no chance.

Pacing: a game's summary is fetched again only when its score, period or clock moved and at least 45 s after the
last fetch, at most 12 summaries a tick, half a second apart. A chance older than four minutes is dropped from the
feed (the card then shows the pregame chance, labelled so).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_GAP = 45           # seconds between two summaries of one game
MAX_CALLS = 12         # summaries a tick
MAX_AGE = 240          # a chance older than this is not published
SKIP = object()        # a game that is not to be asked about now (no published model): no call is counted
HARDWOOD_INDEX = "https://pchattani.github.io/the-quant-hardwood/data/index.json"
GRIDIRON_INDEX = "https://pchattani.github.io/the-quant-gridiron/data/index.json"
BASKETBALL_BOARDS = {"nba": "nba", "wnba": "wnba"}     # feed board -> league


def live_ids(state: dict, boards: dict[str, str]) -> dict[str, str]:
    """{game id: league} for the games the feed's boards call live."""
    out = {}
    for key, league in boards.items():
        for gid, e in (((state.get("boards") or {}).get(key) or {}).get("g") or {}).items():
            if e.get("s") == "live":
                out[str(gid)] = league
    return out


def paced(games: dict, live: dict, entries: dict, now: int, compute, calls: int = 0) -> tuple[int, int]:
    """The pacing every sport shares. `games` (kept in the state): gid -> {"k": [hs, as, p, c], "t": when asked,
    "wp": float | None, "wt": when computed}. `compute(gid, tag)` -> the home side's chance, None when it cannot be
    had now, or SKIP. Writes "wp" on the live entries that have a fresh chance; returns (those games, calls so far)."""
    for gid in [g for g in games if g not in live]:
        del games[gid]
    for gid, tag in sorted(live.items()):
        e = entries.get(gid)
        if not e:
            continue
        key = [e.get("hs"), e.get("as"), e.get("p"), e.get("c")]
        prev = games.get(gid)
        if prev and (prev["k"] == key or now - prev["t"] < MIN_GAP):
            continue
        if calls >= MAX_CALLS:
            break
        try:
            wp = compute(gid, tag)
        except Exception as exc:  # noqa: BLE001 - one game never stops the others, or the feed
            print(f"{gid}: {type(exc).__name__}: {exc}", file=sys.stderr)
            wp = None
        if wp is SKIP:
            continue
        calls += 1
        games[gid] = {"k": key, "t": now, "wp": wp if wp is not None else (prev or {}).get("wp"),
                      "wt": now if wp is not None else (prev or {}).get("wt", 0)}
    n = 0
    for gid in live:
        g, e = games.get(gid), entries.get(gid)
        if g and e and g.get("wp") is not None and now - g.get("wt", 0) <= MAX_AGE and e.get("s") == "live":
            e["wp"] = g["wp"]
            n += 1
    return n, calls


# ============================================================================ Hardwood (NBA, WNBA)

def hardwood_published(ch: dict, now: int, getter) -> dict:
    """What the Hardwood's last build published for the live model: {"models": {league: {K, beta}}, "s": {gid: wp_s}}.
    Read at most every ten minutes; kept (as last read) when the site does not answer."""
    pub = ch.setdefault("hardwood", {"t": 0, "models": {}, "s": {}})
    if now - pub.get("t", 0) < 600:
        return pub
    idx = getter(HARDWOOD_INDEX, {"t": now // 600})
    if isinstance(idx, dict) and isinstance(idx.get("leagues"), dict):
        models, s = {}, {}
        for lg, blk in idx["leagues"].items():
            m = (blk or {}).get("wp_model")
            if isinstance(m, dict) and m.get("K") is not None and m.get("beta"):
                models[lg] = {"ok": True, "version": m.get("version"), "K": float(m["K"]), "beta": [float(b) for b in m["beta"]]}
            for k in ("today", "next_games"):
                for c in (blk or {}).get(k) or []:
                    if c.get("wp_s") is not None:
                        s[str(c.get("id"))] = float(c["wp_s"])
        pub.update(models=models, s=s)
    pub["t"] = now
    return pub


def basketball(feed: dict, state: dict, now: int, getter, summary=None, calls: int = 0) -> tuple[int, int]:
    """Adds "wp" to the live NBA / WNBA entries. Returns (games with a chance, summaries fetched so far)."""
    live = live_ids(state, BASKETBALL_BOARDS)
    ch = state.setdefault("chances", {})
    games = ch.setdefault("basketball", {})
    entries = ((feed.get("sports") or {}).get("basketball") or {}).get("g") or {}
    if not live:
        games.clear()
        return 0, calls
    from oddsmarkets.basketball.models import winprob as W
    from oddsmarkets.basketball.sources import espn
    pub = hardwood_published(ch, now, getter)
    client = espn.Client(budget=MAX_CALLS, interval=0.5, retries=1)
    summary = summary or (lambda league, gid: espn.summary(client, league, gid))

    def compute(gid, league):
        model = (pub.get("models") or {}).get(league)
        if not model:                     # the build has not published its model: no chance from any other
            return SKIP
        raw = summary(league, gid)
        if not raw:
            return None
        # (min_plays 1: the store wants 50 plays before it calls a game play-by-play; a live game has a
        #  chance from its first play, 12 Nov 2026: no chance through the first minutes of every game)
        r = W.live_now(model, espn.compact_pbp(raw, 1), espn.compact_game(raw), league, (pub.get("s") or {}).get(gid))
        return r["wp_home"] if r else None

    return paced(games, live, entries, now, compute, calls)


# ============================================================================ Gridiron (NFL)

def gridiron_published(ch: dict, now: int, getter) -> dict:
    """What the Gridiron's last build published: {"ok", "fit": the WP fit's key, "params": the game parameters' key,
    "mu": {game_id: pregame expected home margin, None = the build used none}}. Read at most every ten minutes."""
    pub = ch.setdefault("gridiron", {"t": 0, "ok": False, "fit": None, "params": None, "mu": {}})
    if now - pub.get("t", 0) < 600:
        return pub
    idx = getter(GRIDIRON_INDEX, {"t": now // 600})
    if isinstance(idx, dict) and isinstance(idx.get("models"), dict):
        m = idx["models"]
        mu = {}
        for k in ("games", "live"):
            for c in idx.get(k) or []:
                if "wp_mu" in c and c.get("game_id"):
                    mu[str(c["game_id"])] = c["wp_mu"]
        pub.update(ok=True, fit=(m.get("fits") or {}).get("wp"), params=m.get("game_params"), mu=mu)
    pub["t"] = now
    return pub


def gridiron_own() -> dict:
    """The keys of the WP fit and the game parameters THIS checkout would compute with, as the build publishes its
    own (scripts/build_gridiron.py model_versions)."""
    from oddsmarkets.nfl.models import game as GM
    from oddsmarkets.nfl.models import wp as WP
    fit = WP.current_fit()
    return {"fit": (fit or {}).get("key") if isinstance(fit, dict) else None, "params": GM.params_key()}


def gridiron(feed: dict, state: dict, now: int, getter, summary=None, calls: int = 0, own=None) -> tuple[int, int]:
    """Adds "wp" to the live NFL entries. Returns (games with a chance, summaries fetched so far)."""
    board = ((state.get("boards") or {}).get("nfl") or {}).get("g") or {}
    live = {str(gid): str(e.get("eid") or "") for gid, e in board.items() if e.get("s") == "live"}
    ch = state.setdefault("chances", {})
    games = ch.setdefault("nfl", {})
    entries = ((feed.get("sports") or {}).get("nfl") or {}).get("g") or {}
    if not live:
        games.clear()
        return 0, calls
    from oddsmarkets.nfl.models import live as L
    from oddsmarkets.nfl.sources import espn
    pub = gridiron_published(ch, now, getter)
    mine = (own or gridiron_own)() if pub.get("ok") else {}
    same = bool(pub.get("ok")) and mine.get("fit") == pub.get("fit") and mine.get("params") == pub.get("params")
    if pub.get("ok") and not same:
        print(f"gridiron: this checkout's model ({mine}) is not the build's ({pub.get('fit')}, {pub.get('params')})", file=sys.stderr)
    client = None

    def fetch(eid):
        nonlocal client
        client = client or espn.Client(budget=MAX_CALLS, interval=0.5, retries=1)
        return espn.summary(client, eid)
    summary = summary or fetch

    def compute(gid, eid):
        if not same or not eid or gid not in (pub.get("mu") or {}):
            return SKIP
        raw = summary(eid)
        if not raw:
            return None
        parts = gid.split("_")                                  # 2026_10_WAS_NYG: season, week, away, home
        season, home = int(parts[0]), parts[3]
        rec = espn.compact_summary(raw, gid, season)
        if not rec:
            return None
        w = L.live_wp(rec, {"margin": float(pub["mu"][gid] or 0.0)}, season, home)
        if not w or w.get("source") == "final" or w.get("wp_home") is None:
            return None
        return round(float(w["wp_home"]), 4)

    return paced(games, live, entries, now, compute, calls)


def get_json(url: str, params: dict | None = None):
    import importlib.util
    spec = importlib.util.spec_from_file_location("live_feed", Path(__file__).with_name("live_feed.py"))
    lf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lf)
    return lf.get_json(url, params)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--feed", default="live.json")
    ap.add_argument("--state", default="live_state.json")
    a = ap.parse_args()
    fp, sp = Path(a.feed), Path(a.state)
    try:
        feed, state = json.loads(fp.read_text(encoding="utf-8")), json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"changed": False, "n": 0, "calls": 0, "error": str(exc)[:120]}))
        return 0
    now = int(time.time())
    sys.path.insert(0, str(ROOT))
    n, calls = 0, 0
    for site in (basketball, gridiron):                  # one site failing never costs the others their chances
        try:
            k, calls = site(feed, state, now, get_json, calls=calls)
            n += k
        except Exception as exc:  # noqa: BLE001
            print(f"{site.__name__}: {type(exc).__name__}: {exc}", file=sys.stderr)
    wps = {s: {g: e["wp"] for g, e in blk["g"].items() if "wp" in e} for s, blk in (feed.get("sports") or {}).items()}
    sig = json.dumps(wps, sort_keys=True)
    changed = sig != state.get("chances_fp")
    state["chances_fp"] = sig
    if n:
        fp.write_text(json.dumps(feed, separators=(",", ":")), encoding="utf-8")
    sp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"changed": changed, "n": n, "calls": calls}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
