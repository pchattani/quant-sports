"""Recorded tennis answers (no network in tests): tennis-data slices, ESPN scoreboards and rankings,
WTA API matches/stats/draw, and one charted match. Every test that writes runs against a temporary
data root (ACE_DATA / ACE_RAW), so the committed stores and the registry are never touched."""
from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]

# file -> what it is (recorded 1 Oct 2026)
FIXTURES = {
    "td_atp_2025_slice.csv": "tennis-data ATP 2025, the first whole events (Brisbane, Hong Kong, Adelaide, Auckland, "
                             "Australian Open, ...) plus three walkovers",
    "td_wta_2025_slice.csv": "tennis-data WTA 2025, the first whole events plus three walkovers",
    "td_atp_2026_chengdu_hangzhou.csv": "tennis-data ATP 2026 Chengdu and Hangzhou (both in the ESPN 2026-09-25 day)",
    "td_wta_2026_seoul_singapore.csv": "tennis-data WTA 2026 Seoul and Singapore (ESPN 2026-09-25; WTA API 1152)",
    "espn_atp_20260925.json.gz": "ESPN ATP scoreboard 25 Sep 2026: Chengdu, Hangzhou",
    "espn_wta_20260925.json.gz": "ESPN WTA scoreboard 25 Sep 2026: Seoul, Singapore, WTA 125s",
    "espn_atp_20261001.json.gz": "ESPN ATP scoreboard 1 Oct 2026 with live matches (Tokyo, Beijing)",
    "espn_wta_20261001.json.gz": "ESPN WTA scoreboard 1 Oct 2026 with live matches (Beijing, 125s)",
    "espn_rankings_atp.json.gz": "ESPN ATP rankings (top 150)",
    "wta_matches_1152_2026.json.gz": "WTA API matches, Singapore 2026 (walkover, tiebreaks, qualifying)",
    "wta_stats_1152_2026_LS001.json": "WTA API stats, Singapore 2026 final (Fernandez d Gibson 7-5 6-0)",
    "wta_draw_1020_2026.json.gz": "WTA API draw, Beijing 2026 (96 players in a 128 bracket)",
    "charting_m_matches.csv": "Match Charting Project: Rome 2026 final row",
    "charting_m_points.csv": "Match Charting Project: Rome 2026 final, every point",
}


def load(name: str):
    p = FIX / name
    if name.endswith(".gz"):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    if name.endswith(".json"):
        return json.loads(p.read_text(encoding="utf-8"))
    return p


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    """A clean data root for stores, the registry and raw caches."""
    monkeypatch.setenv("ACE_DATA", str(tmp_path / "ace"))
    monkeypatch.setenv("ACE_RAW", str(tmp_path / "raw"))
    return tmp_path


@pytest.fixture(scope="session")
def tn_fetch():
    """scripts/tn_fetch.py as a module (its Ingest class merges source records into a store)."""
    spec = importlib.util.spec_from_file_location("tn_fetch_mod", ROOT / "scripts" / "tn_fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── builder D: a small synthetic tennis world (stores for two years) for the analytics and build tests ──

def _ace_store(tour, year):
    return {"tour": tour, "year": year, "updated_at": "2026-10-01T00:00:00Z", "players": {}, "events": {}, "matches": {},
            "rankings": {"date": None, "rows": []}, "meta": {"sources": {}, "fetched": {}, "conflicts": []}}


def make_ace_world(root, tour="atp", today=None, n_players=40, n_matches=1400, seed=3):
    """Stores for 2025 and 2026 under root/<tour>/<year>/store.json, built from builder B's planted-strength
    simulator: monthly 250s (round of 32 results between random pairs), one 8-player knockout per year
    (QF, SF, F) and, in 2026, an 8-player event in progress (QF done, SF upcoming) plus the 2025 edition
    of it; official rankings by planted strength. Returns {"pids", "strength", "today", "live_event", ...}."""
    from datetime import date, timedelta
    from oddsmarkets.tennis import store as st
    from oddsmarkets.tennis.models.synthetic import make_tour, simulate_match
    from oddsmarkets.tennis.models.serve_return import point_prob_from_hold
    import math
    import numpy as np
    today = today or date(2026, 10, 1)
    rows, truth = make_tour(n_players=n_players, n_matches=n_matches, seed=seed, start=date(2025, 1, 6), days=(today - date(2025, 1, 6)).days - 10,
                            with_stats=(tour == "wta"))
    pids = truth["pids"]
    strength = {p: truth["s"][p] + truth["r"][p] for p in pids}
    order = sorted(pids, key=lambda p: -strength[p])
    rank = {p: i + 1 for i, p in enumerate(order)}
    stores = {y: _ace_store(tour, y) for y in (2025, 2026)}
    for y, s in stores.items():
        for p in pids:
            s["players"][p] = {"name": f"Player {p[-3:]}", "short": f"P. {p[-3:]}", "country": "XXX", "hand": "R",
                               "dob": "2000-01-01", "height": None, "espn": None, "wta": None, "aliases": []}
    surf = ["hard", "clay", "grass", "hard"]
    for m in rows:
        d = date.fromisoformat(m["date"])
        y = d.year
        tid = f"syn-m{d.month:02d}"
        eid = f"{tid}-{y}"
        s = stores[y]
        sf = surf[d.month % 4]
        ev = s["events"].setdefault(eid, {"tid": tid, "name": f"Synthetic {d.month}", "year": y, "start": d.replace(day=1).isoformat(),
                                          "end": d.replace(day=28).isoformat(), "level": "250", "surface": sf, "indoor": False,
                                          "draw_size": 32, "best_of": 3, "city": "X", "country": "X", "espn": None, "wta": None,
                                          "status": "done", "champion": None, "draw": None})
        mid = st.match_id(eid, "R32", m["p1"], m["p2"])
        if mid in s["matches"]:
            continue
        stats = m.get("stats")
        if stats:
            for k in ("p1", "p2"):
                x = stats[k]
                x.pop("_breaks", None)
                x.update(aces=1, dfs=1, fs_in=int(x["sv_pts"] * 0.6), fs_won=int(x["fs_won"] * 0.7),
                         ss_won=x["fs_won"] - int(x["fs_won"] * 0.7), bp_saved=0, rt_pts_won=None, bp_conv=None, bp_opps=None)
        s["matches"][mid] = dict(m, id=mid, event=eid, surface=sf, level="250", rank1=rank[m["p1"]], rank2=rank[m["p2"]],
                                 pts1=None, pts2=None, odds={"ps": [1.8, 2.0], "avg": [1.75, 2.0]}, live=None, sources=["td"],
                                 duration_min=90, stats=stats if stats else None)
    rng = np.random.default_rng(seed)

    def play(a, b):
        ha = 1 / (1 + math.exp(-(1.0 + truth["s"][a] - truth["r"][b])))
        hb = 1 / (1 + math.exp(-(1.0 + truth["s"][b] - truth["r"][a])))
        res = simulate_match(float(point_prob_from_hold(ha)), float(point_prob_from_hold(hb)), 3, "tb7", rng)
        if res["a_won"]:
            return a, b, res["sets"]
        return b, a, [[q, p, tq, tp] for p, q, tp, tq in res["sets"]]

    def knockout(s, eid, field, d0, upto=None):
        cur = list(field)
        for rnd, k in (("QF", 0), ("SF", 2), ("F", 4)):
            nxt = []
            for i in range(0, len(cur), 2):
                a, b = cur[i], cur[i + 1]
                mid = st.match_id(eid, rnd, a, b)
                if upto == rnd:
                    s["matches"][mid] = {"id": mid, "event": eid, "date": (d0 + timedelta(days=k + 2)).isoformat() + "T12:00",
                                         "round": rnd, "best_of": 3, "surface": "hard", "indoor": False, "level": "500", "p1": a,
                                         "p2": b, "winner": None, "status": "upcoming", "sets": [], "final_set_rule": "tb7",
                                         "rank1": rank[a], "rank2": rank[b], "pts1": None, "pts2": None, "odds": None, "stats": None,
                                         "live": None, "sources": ["espn"], "duration_min": None}
                    continue
                w, l_, sets = play(a, b)
                s["matches"][mid] = {"id": mid, "event": eid, "date": (d0 + timedelta(days=k)).isoformat(), "round": rnd,
                                     "best_of": 3, "surface": "hard", "indoor": False, "level": "500", "p1": w, "p2": l_,
                                     "winner": w, "status": "done", "sets": sets, "final_set_rule": "tb7", "rank1": rank[w],
                                     "rank2": rank[l_], "pts1": None, "pts2": None, "odds": {"ps": [1.5, 2.6]}, "stats": None,
                                     "live": None, "sources": ["td"], "duration_min": 100}
                nxt.append(w)
            if upto == rnd:
                return None
            cur = nxt
        return cur[0]

    field = order[:8]
    seeded = [field[0], field[7], field[3], field[4], field[2], field[5], field[1], field[6]]
    for y, d0, status in ((2025, date(2025, 9, 28), "done"), (2026, today - timedelta(days=3), "live")):
        s = stores[y]
        eid = f"syn-open-{y}"
        champ = knockout(s, eid, seeded, d0, upto="SF" if status == "live" else None)
        s["events"][eid] = {"tid": "syn-open", "name": "Synthetic Open", "year": y, "start": d0.isoformat(),
                            "end": (d0 + timedelta(days=7)).isoformat(), "level": "500", "surface": "hard", "indoor": False,
                            "draw_size": 8, "best_of": 3, "city": "X", "country": "X", "espn": None, "wta": None, "status": status,
                            "champion": champ, "draw": {"size": 8, "slots": [[i + 1, p, (i + 2) // 2 if i % 7 == 0 else None, None]
                                                                             for i, p in enumerate(seeded)], "source": "wta", "complete": True}}
    stores[2026]["rankings"] = {"date": (today - timedelta(days=4)).isoformat(), "rows": [[rank[p], p, 5000 - 100 * rank[p]] for p in order],
                                "source": "espn"}
    for y, s in stores.items():
        p = root / tour / str(y) / "store.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s), encoding="utf-8")
    return {"pids": pids, "strength": strength, "order": order, "rank": rank, "today": today, "live_event": "syn-open-2026",
            "done_event": "syn-open-2025", "stores": stores}


def _world(tmp_path, monkeypatch, **kw):
    data = tmp_path / "ace"
    cache = tmp_path / "cache"
    monkeypatch.setenv("ACE_DATA", str(data))
    monkeypatch.setenv("ACE_CACHE", str(cache))
    monkeypatch.setenv("ACE_RAW", str(tmp_path / "raw"))
    info = make_ace_world(data, **kw)
    info.update(data=data, cache=cache)
    return info


@pytest.fixture
def ace_world(tmp_path, monkeypatch):
    """A synthetic two-year ATP world under a temporary ACE_DATA / ACE_CACHE (builder D's tests)."""
    return _world(tmp_path, monkeypatch)


@pytest.fixture
def ace_world_small(tmp_path, monkeypatch):
    """The same world with fewer matches (end-to-end build tests)."""
    return _world(tmp_path, monkeypatch, n_matches=600)
