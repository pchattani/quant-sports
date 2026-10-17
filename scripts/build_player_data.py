"""
Build player_stats.csv — per-player HISTORICAL advanced stats from StatsBomb Open Data.

Source: https://github.com/statsbomb/open-data  (free, no API key)
Covers the same 6 tournaments as build_xg_data.py. These are COMPLETED events, so
the output is a fixed historical profile (career/recent-tournament pedigree), not
live WC 2026 data. One-shot: run locally, commit the CSV. Not in the hourly build.

Usage:
    uv run python scripts/build_player_data.py

Output → oddsmarkets/sports/world_cup/data/player_stats.csv (tracked path; data/ is gitignored)

Per player: minutes, goals, non-pen goals, penalties, shots, shots-on-target, xG,
npxG, assists, key passes, xA, passes, pass %, progressive passes, GK saves — plus
per-90 rates for the rate metrics. Filtered to WC 2026 national teams.
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import hypot
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).parent.parent
OUT_CSV = ROOT / "oddsmarkets" / "sports" / "world_cup" / "data" / "player_stats.csv"

SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# (label, competition_id, season_id, recency_weight) — same comps as the xG builder.
COMPETITIONS = [
    ("WC 2022",       43,   106, 1.00),
    ("EURO 2024",     55,   282, 1.00),
    ("Copa Am 2024", 223,   282, 1.00),
    ("AFCON 2023",  1267,   107, 0.90),
    ("EURO 2020",     55,    43, 0.55),
    ("WC 2018",       43,     3, 0.35),
]

# StatsBomb national-team name → our canonical WC 2026 name
SB_ALIASES: dict[str, str] = {
    "United States":          "USA",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Côte d'Ivoire":          "Ivory Coast",
    "Cote d'Ivoire":          "Ivory Coast",
    "Cape Verde Islands":     "Cape Verde",
    "Congo DR":               "DR Congo",
    "Korea Republic":         "South Korea",
    "China PR":               "China",
    "Czech Republic":         "Czech Republic",
    "Czechia":                "Czech Republic",
    "Turkey":                 "Turkey",
    "Türkiye":                "Turkey",
}

GOAL = (120.0, 40.0)  # opponent goal centre on the 120x80 StatsBomb pitch

def _role(position: str) -> str:
    if not position:
        return ""
    p = position.lower()
    if "goalkeeper" in p:
        return "GK"
    if "midfield" in p:        # incl. "Defensive Midfield" → MID (check before "back")
        return "MID"
    if "back" in p:
        return "DEF"
    if "wing" in p or "forward" in p or "striker" in p:
        return "FWD"
    return "MID"


def canon(name: str) -> str:
    return SB_ALIASES.get(name, name)


def fetch_json(url: str, retries: int = 3):
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(1)
    return None


def _new_counter() -> dict:
    return {k: 0.0 for k in (
        "goals", "npg", "penalties", "shots", "sot", "xg", "npxg",
        "assists", "key_passes", "xa", "passes", "passes_completed",
        "prog_passes", "gk_saves",
    )}


def player_stats_from_events(match_id: int, label: str, weight: float) -> list[dict]:
    events = fetch_json(f"{SB_BASE}/events/{match_id}.json")
    if not events:
        return []

    # Cleaner display names from the lineups endpoint (player_nickname), e.g.
    # "Cristiano Ronaldo dos Santos Aveiro" → "Cristiano Ronaldo".
    nick: dict[int, str] = {}
    for team_lu in (fetch_json(f"{SB_BASE}/lineups/{match_id}.json") or []):
        for p in team_lu.get("lineup", []):
            nn = p.get("player_nickname")
            if nn:
                nick[p["player_id"]] = nn

    on_min: dict[int, int] = {}
    off_min: dict[int, int] = {}
    pinfo: dict[int, dict] = {}
    pass_passer: dict[str, int] = {}     # pass event id → passer id (for xA linking)
    shot_keypass: list[tuple[str, float]] = []
    stats: dict[int, dict] = defaultdict(_new_counter)
    match_end = 0

    for e in events:
        minute = e.get("minute", 0) or 0
        match_end = max(match_end, minute)
        et = e.get("type", {}).get("name")
        pid = (e.get("player") or {}).get("id")

        if et == "Starting XI":
            team = e["team"]["name"]
            for p in e.get("tactics", {}).get("lineup", []):
                q = p["player"]["id"]
                on_min[q] = 0
                pinfo[q] = {"name": p["player"]["name"], "team": team,
                            "position": (p.get("position") or {}).get("name", "")}
            continue

        if et == "Substitution":
            if pid is not None:
                off_min[pid] = minute
            rep = (e.get("substitution") or {}).get("replacement")
            if rep:
                on_min[rep["id"]] = minute
                pinfo.setdefault(rep["id"], {"name": rep["name"], "team": e["team"]["name"],
                                             "position": (e.get("position") or {}).get("name", "")})
            continue

        card = None
        if et == "Bad Behaviour":
            card = ((e.get("bad_behaviour") or {}).get("card") or {}).get("name")
        elif et == "Foul Committed":
            card = ((e.get("foul_committed") or {}).get("card") or {}).get("name")
        if card in ("Red Card", "Second Yellow") and pid is not None:
            off_min[pid] = minute

        if pid is None:
            continue
        if pid not in pinfo:
            pinfo[pid] = {"name": (e.get("player") or {}).get("name", "?"),
                          "team": (e.get("team") or {}).get("name", "?"),
                          "position": (e.get("position") or {}).get("name", "")}

        if et == "Pass":
            p = e.get("pass", {})
            pass_passer[e["id"]] = pid
            stats[pid]["passes"] += 1
            complete = p.get("outcome") is None  # StatsBomb: no outcome ⇒ completed
            if complete:
                stats[pid]["passes_completed"] += 1
            if p.get("goal_assist"):
                stats[pid]["assists"] += 1
            if p.get("shot_assist"):
                stats[pid]["key_passes"] += 1
            # progressive: completed pass that gets ≥10m closer to goal centre
            loc, end = e.get("location"), p.get("end_location")
            if complete and loc and end:
                if hypot(GOAL[0] - loc[0], GOAL[1] - loc[1]) - hypot(GOAL[0] - end[0], GOAL[1] - end[1]) >= 10:
                    stats[pid]["prog_passes"] += 1

        elif et == "Shot":
            sh = e.get("shot", {})
            xg = sh.get("statsbomb_xg") or 0.0
            is_pen = (sh.get("type") or {}).get("name") == "Penalty"
            outcome = (sh.get("outcome") or {}).get("name")
            stats[pid]["shots"] += 1
            stats[pid]["xg"] += xg
            if not is_pen:
                stats[pid]["npxg"] += xg
            if outcome == "Goal":
                stats[pid]["goals"] += 1
                if is_pen:
                    stats[pid]["penalties"] += 1
                else:
                    stats[pid]["npg"] += 1
            if outcome in ("Goal", "Saved", "Saved to Post"):
                stats[pid]["sot"] += 1
            kp = sh.get("key_pass_id")
            if kp:
                shot_keypass.append((kp, xg))

        elif et == "Goal Keeper":  # note: StatsBomb type name has a space
            gt = (e.get("goalkeeper", {}).get("type") or {}).get("name", "")
            if gt in ("Shot Saved", "Shot Saved to Post", "Penalty Saved", "Smother"):
                stats[pid]["gk_saves"] += 1

    # xA: credit each shot's xG to the passer of its key pass
    for kp_id, xg in shot_keypass:
        passer = pass_passer.get(kp_id)
        if passer is not None:
            stats[passer]["xa"] += xg

    rows = []
    for pid, s in stats.items():
        info = pinfo.get(pid, {"name": "?", "team": "?", "position": ""})
        mins = (off_min.get(pid, match_end)) - on_min.get(pid, 0)
        mins = max(mins, 0)
        rows.append({
            "player_id": pid, "player": info["name"], "nickname": nick.get(pid, ""),
            "team": canon(info["team"]), "position": info["position"],
            "minutes": mins, "matches": 1, "weight": weight, "comp": label, **s,
        })
    return rows


def main() -> None:
    from oddsmarkets.sports.world_cup.trading.simulator import WC2026_GROUPS
    wc_teams = {t for teams in WC2026_GROUPS.values() for t in teams}

    all_rows: list[dict] = []
    for label, cid, sid, weight in COMPETITIONS:
        print(f"\nFetching {label} (comp={cid}, season={sid})...")
        matches = fetch_json(f"{SB_BASE}/matches/{cid}/{sid}.json")
        if not matches:
            print("  ERROR: could not fetch match list")
            continue
        print(f"  {len(matches)} matches — downloading events...")
        done = 0
        with ThreadPoolExecutor(max_workers=10) as pool:
            futs = {pool.submit(player_stats_from_events, m["match_id"], label, weight): m for m in matches}
            for fut in as_completed(futs):
                all_rows.extend(fut.result())
                done += 1
                if done % 20 == 0 or done == len(matches):
                    print(f"  {done}/{len(matches)} processed ({len(all_rows)} player-rows)")

    if not all_rows:
        print("No data collected — check network.")
        sys.exit(1)

    df = pd.DataFrame(all_rows)
    df = df[df["team"].isin(wc_teams)]  # only WC 2026 nations

    # Aggregate per player across all comps/matches
    counters = ["goals", "npg", "penalties", "shots", "sot", "xg", "npxg",
                "assists", "key_passes", "xa", "passes", "passes_completed",
                "prog_passes", "gk_saves", "minutes", "matches"]
    agg = df.groupby("player_id").agg(
        player=("player", "last"),
        nickname=("nickname", lambda s: next((x for x in s if x), "")),
        team=("team", lambda s: s.mode().iat[0] if not s.mode().empty else s.iat[0]),
        position=("position", lambda s: s.mode().iat[0] if not s.mode().empty else ""),
        comps=("comp", lambda s: ", ".join(sorted(set(s)))),
        **{c: (c, "sum") for c in counters},
    ).reset_index()

    agg["role"] = agg["position"].map(_role)
    # Preferred display name: nickname when StatsBomb provides one, else full name.
    agg["display"] = agg["nickname"].where(agg["nickname"].astype(bool), agg["player"])
    agg["pass_pct"] = (agg["passes_completed"] / agg["passes"].clip(lower=1) * 100).round(1)
    p90 = agg["minutes"].clip(lower=1) / 90.0
    for m in ["goals", "npg", "xg", "npxg", "assists", "key_passes", "xa", "shots", "prog_passes", "gk_saves"]:
        agg[f"{m}_90"] = (agg[m] / p90).round(3)

    # Round totals for a tidy CSV
    for m in ["xg", "npxg", "xa"]:
        agg[m] = agg[m].round(2)
    agg = agg.sort_values(["goals", "xg"], ascending=False)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(OUT_CSV, index=False)
    print(f"\nSaved {len(agg)} players to {OUT_CSV}")
    print("\nTop 10 by goals:")
    for _, r in agg.head(10).iterrows():
        line = (f"  {r['display']:22s} {r['team']:14s} {int(r['minutes']):4d}min "
                f"G={int(r['goals'])} xG={r['xg']:.1f} A={int(r['assists'])} KP={int(r['key_passes'])}")
        print(line.encode("ascii", "replace").decode())


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
