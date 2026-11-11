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
HARDWOOD_INDEX = "https://pchattani.github.io/the-quant-hardwood/data/index.json"
BASKETBALL_BOARDS = {"nba": "nba", "wnba": "wnba"}     # feed board -> league


def live_ids(state: dict, boards: dict[str, str]) -> dict[str, str]:
    """{game id: league} for the games the feed's boards call live."""
    out = {}
    for key, league in boards.items():
        for gid, e in (((state.get("boards") or {}).get(key) or {}).get("g") or {}).items():
            if e.get("s") == "live":
                out[str(gid)] = league
    return out


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


def basketball(feed: dict, state: dict, now: int, getter, summary=None) -> tuple[int, int]:
    """Adds "wp" to the live NBA / WNBA entries. Returns (games with a chance, summaries fetched)."""
    live = live_ids(state, BASKETBALL_BOARDS)
    ch = state.setdefault("chances", {})
    games = ch.setdefault("basketball", {})          # gid -> {"k": [hs, as, p, c], "t": fetched, "wp": float | None}
    for gid in [g for g in games if g not in live]:
        del games[gid]
    entries = ((feed.get("sports") or {}).get("basketball") or {}).get("g") or {}
    if not live:
        return 0, 0
    from oddsmarkets.basketball.models import winprob as W
    from oddsmarkets.basketball.sources import espn
    pub = hardwood_published(ch, now, getter)
    client = espn.Client(budget=MAX_CALLS, interval=0.5, retries=1)
    summary = summary or (lambda league, gid: espn.summary(client, league, gid))
    calls = 0
    for gid, league in sorted(live.items()):
        e = entries.get(gid)
        if not e:
            continue
        key = [e.get("hs"), e.get("as"), e.get("p"), e.get("c")]
        prev = games.get(gid)
        if prev and (prev["k"] == key or now - prev["t"] < MIN_GAP):
            continue
        model = (pub.get("models") or {}).get(league)
        if not model:                     # the build has not published its model: no chance from any other
            continue
        if calls >= MAX_CALLS:
            break
        calls += 1
        wp = None
        try:
            raw = summary(league, gid)
            if raw:
                r = W.live_now(model, espn.compact_pbp(raw), espn.compact_game(raw), league, (pub.get("s") or {}).get(gid))
                wp = r["wp_home"] if r else None
        except Exception as exc:  # noqa: BLE001 - one game never stops the others, or the feed
            print(f"basketball {gid}: {type(exc).__name__}: {exc}", file=sys.stderr)
        games[gid] = {"k": key, "t": now, "wp": wp if wp is not None else (prev or {}).get("wp"),
                      "wt": now if wp is not None else (prev or {}).get("wt", 0)}
    n = 0
    for gid in live:
        g, e = games.get(gid), entries.get(gid)
        if g and e and g.get("wp") is not None and now - g.get("wt", 0) <= MAX_AGE and e.get("s") == "live":
            e["wp"] = g["wp"]
            n += 1
    return n, calls


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
    n, calls = basketball(feed, state, now, get_json)
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
