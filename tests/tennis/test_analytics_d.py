"""Builder D: the analytics layer (oddsmarkets/tennis/analytics) on a synthetic world and hand-worked cases.
No network; every test writes under a temporary ACE_DATA / ACE_CACHE."""
from __future__ import annotations

import json
from datetime import date

import pytest

from oddsmarkets.tennis import analytics as an


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────────

def test_percentiles_direction_aware():
    v = {"a": 1.0, "b": 2.0, "c": 3.0, "d": None}
    hi = an.percentiles(v)
    lo = an.percentiles(v, lower=True)
    assert hi == {"a": 0, "b": 50, "c": 100}
    assert lo == {"a": 100, "b": 50, "c": 0}
    assert an.percentiles({"x": 5}) == {"x": 50}
    ref = [1.0, 2.0, 3.0, 4.0]
    assert an.place(ref, 4.0, False) == 88 and an.place(ref, 4.0, True) == 12
    assert an.rank_in(ref, 4.0, False) == 1 and an.rank_in(ref, 4.0, True) == 4
    assert an.rank_in(ref, 1.0, True) == 1


def test_shrink_and_devig():
    assert an.shrink(1.0, 0, 0.5, 10) == pytest.approx(0.5)
    assert an.shrink(1.0, 10, 0.5, 10) == pytest.approx(0.75)
    assert an.shrink(None, 10, 0.5, 10) is None
    assert an.devig2([2.0, 2.0]) == pytest.approx(0.5)
    assert an.devig2([1.5, 3.0]) == pytest.approx((1 / 1.5) / (1 / 1.5 + 1 / 3.0))
    assert an.devig2([1.0, 2.0]) is None and an.devig2(None) is None


def test_fname_and_score_text():
    assert an.fname("x:alena-kovackova") == "x_alena-kovackova"
    m = {"status": "done", "sets": [[6, 4, None, None], [6, 7, 5, 7], [7, 6, 7, 3]]}
    assert an.score_text(m) == "6-4 6-7(5) 7-6(3)"
    assert an.score_text(m, flip=True) == "4-6 7-6(5) 6-7(3)"
    assert an.score_text({"status": "wo"}) == "w/o"
    assert an.chain_rule({"final_set_rule": "tb7", "final_set_tb_at": 12}) == "tb12"
    assert an.chain_rule({"final_set_rule": "tb10"}) == "tb10"


# ── points to defend and the race ───────────────────────────────────────────────────────────────────

def _ko_event(eid, tid, start, end, level, rounds):
    """rounds: [(round, winner, loser)]"""
    ev = {"tid": tid, "name": tid, "year": int(eid[-4:]), "start": start, "end": end, "level": level, "surface": "hard",
          "indoor": False, "draw_size": 32, "best_of": 3, "status": "done", "champion": None, "draw": None}
    ms = {}
    for rnd, w, l_ in rounds:
        mid = f"{eid}-{rnd}-{min(w, l_)}-{max(w, l_)}"
        ms[mid] = {"id": mid, "event": eid, "date": start, "round": rnd, "best_of": 3, "surface": "hard", "indoor": False,
                   "level": level, "p1": w, "p2": l_, "winner": w, "status": "done", "sets": [[6, 4, None, None], [6, 4, None, None]],
                   "final_set_rule": "tb7"}
    return ev, ms


def _write(root, tour, year, events, matches, rankings=None):
    s = {"tour": tour, "year": year, "updated_at": "x", "players": {}, "events": events, "matches": matches,
         "rankings": rankings or {"date": None, "rows": []}, "meta": {"sources": {}, "fetched": {}, "conflicts": []}}
    p = root / tour / str(year) / "store.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s), encoding="utf-8")


def test_points_to_defend_arithmetic(tmp_path, monkeypatch):
    from oddsmarkets.tennis.analytics import rankings as RK
    monkeypatch.setenv("ACE_DATA", str(tmp_path / "ace"))
    monkeypatch.setenv("ACE_CACHE", str(tmp_path / "cache"))
    root = tmp_path / "ace"
    # last season: a 500 (A beats B in the final; C, D lose the semis; E..H the quarters; I..P the R32 losers)
    rounds = [("F", "A", "B"), ("SF", "A", "C"), ("SF", "B", "D"), ("QF", "A", "E"), ("QF", "C", "F"), ("QF", "B", "G"), ("QF", "D", "H")]
    r16 = [("R16", w, f"L{w}") for w in "ABCDEFGH"]
    ev1, ms1 = _ko_event("tokyo-2025", "tokyo", "2025-09-29", "2025-10-05", "500", rounds + r16)
    # and a 250 that ended long enough ago that its points have already dropped
    ev0, ms0 = _ko_event("doha-2025", "doha", "2025-02-17", "2025-02-23", "250", [("F", "C", "A")])
    _write(root, "atp", 2025, {"tokyo-2025": ev1, "doha-2025": ev0}, {**ms1, **ms0})
    # this season: A wins a 250 (250) and reaches a Masters semi (400)
    ev2, ms2 = _ko_event("dallas-2026", "dallas", "2026-02-09", "2026-02-15", "250", [("F", "A", "B")])
    ev3, ms3 = _ko_event("rome-2026", "rome", "2026-05-06", "2026-05-17", "m1000", [("F", "C", "D"), ("SF", "C", "A"), ("SF", "D", "B")])
    _write(root, "atp", 2026, {"dallas-2026": ev2, "rome-2026": ev3}, {**ms2, **ms3})
    td = an.TourData("atp", date(2026, 10, 1))
    pts = RK.event_points(td, 2025)
    assert pts["tokyo-2025"]["A"] == 500 and pts["tokyo-2025"]["B"] == 330
    assert pts["tokyo-2025"]["C"] == 200 and pts["tokyo-2025"]["E"] == 100 and pts["tokyo-2025"]["LA"] == 50
    d = RK.to_defend(td, date(2026, 10, 1), pts)
    wk = RK.drop_week("2025-10-05")
    assert wk == "2026-10-05" and date.fromisoformat(wk).weekday() == 0
    assert d["A"] == [["tokyo-2025", wk, 500]] and d["B"] == [["tokyo-2025", wk, 330]]
    assert "doha-2025" not in {r[0] for rows in d.values() for r in rows}          # dropped in February
    assert sum(r[2] for r in d["A"]) == 500
    race = dict(RK.race(td, 2026))
    assert race["A"] == 250 + 400 and race["C"] == 1000 and race["D"] == 650 and race["B"] == 165 + 400


# ── the catalogue on the synthetic world ────────────────────────────────────────────────────────────

def test_catalogue_keys_and_direction(ace_world):
    from oddsmarkets.tennis.analytics import players as PL
    td = an.TourData("atp", ace_world["today"])
    cat = PL.build(td, 2025)
    assert cat["ok"] and cat["metrics"] == PL.tour_metrics(cat["tour"])
    assert cat["tour"] != "atp" or not any(m.get("scope") == "wta_stats" for m in cat["metrics"])
    assert 100 <= len(PL.METRICS) <= 160
    assert len({m["key"] for m in PL.METRICS}) == len(PL.METRICS)
    for m in PL.METRICS:
        assert set(m) == {"key", "label", "group", "fmt", "lower", "scope", "desc"}
        assert m["fmt"] in ("int", "1", "2", "3", "pct", "prob", "signed") and m["scope"] in ("all", "wta_stats", "charted")
    pl = cat["players"]
    assert len(pl) >= 20
    r = next(iter(pl.values()))
    assert set(r) >= {"name", "country", "age", "rank", "matches", "qualified", "values", "pct", "pct_surface", "rank_metric"}
    assert set(r["values"]) == set(PL.METRIC_KEYS)
    q = {p: x for p, x in pl.items() if x["qualified"]}
    assert len(q) >= 10
    # higher win % -> higher percentile; more losses (lower is better) -> lower percentile
    best = max(q, key=lambda p: q[p]["values"]["win_pct"])
    worst = min(q, key=lambda p: q[p]["values"]["win_pct"])
    assert q[best]["pct"]["win_pct"] > q[worst]["pct"]["win_pct"]
    most_l = max(q, key=lambda p: q[p]["values"]["losses"])
    fewest_l = min(q, key=lambda p: q[p]["values"]["losses"])
    if q[most_l]["values"]["losses"] != q[fewest_l]["values"]["losses"]:
        assert q[most_l]["pct"]["losses"] < q[fewest_l]["pct"]["losses"]
    # ranks among the qualified: 1 for the best value
    assert min(x["rank_metric"]["win_pct"] for x in q.values()) == 1
    # planted strength shows through the inferred serve/return and Elo
    strong = ace_world["order"][:5]
    weak = ace_world["order"][-5:]
    avg = lambda ps, k: sum(pl[p]["values"][k] for p in ps if p in pl and pl[p]["values"][k] is not None) / max(1, sum(
        1 for p in ps if p in pl and pl[p]["values"][k] is not None))
    assert avg(strong, "sr_total") > avg(weak, "sr_total")
    assert avg(strong, "elo") > avg(weak, "elo")
    # clutch expectations come from the chain: a probability per tiebreak
    tbx = [x["values"]["tb_exp"] for x in pl.values() if x["values"]["tb_exp"] is not None]
    assert tbx and all(0.0 < v < 1.0 for v in tbx)
    # counts add up
    for x in pl.values():
        v = x["values"]
        assert v["wins"] + v["losses"] == v["matches"]
        assert v["tb_w"] + v["tb_l"] >= 0


def test_glossary_covers_every_metric():
    from oddsmarkets.tennis.analytics import players as PL
    from oddsmarkets.tennis.analytics.glossary import build_glossary
    g = build_glossary()
    keys = {e["key"]: e for grp in g["groups"] for e in grp["entries"]}
    assert set(PL.METRIC_KEYS) <= set(keys)
    assert all(keys[k]["desc"] and keys[k]["desc"] != keys[k]["label"] for k in PL.METRIC_KEYS)
    assert {m["key"] for m in g["model"]} >= {"elo", "serve_return", "match_chain", "tournament_sim", "season_sim"}


def test_match_page_and_event_page(ace_world):
    from oddsmarkets.tennis.analytics import events as EV
    from oddsmarkets.tennis.analytics import matches as MT
    td = an.TourData("atp", ace_world["today"])
    ms = [m for m in td.matches(2026).values() if m["event"] == ace_world["live_event"]]
    preds = MT.predictions(td, ms, with_dist=True)
    done = next(m for m in ms if m["status"] == "done")
    pg = MT.build_match(td, done, preds[done["id"]])
    assert set(pg) >= {"id", "event", "round", "date", "surface", "best_of", "status", "p1", "p2", "winner", "sets", "duration_min",
                       "pre", "wp", "swings", "excitement", "comeback", "stats", "inferred", "charting", "awards"}
    assert set(pg["pre"]) >= {"model", "elo", "sr", "market", "closing", "h2h"}
    d = pg["pre"]["model"]["dist"]
    assert set(d) >= {"p1_win", "sets", "games", "handicap", "p_tiebreak", "p_straight"}
    assert abs(sum(d["sets"].values()) - 1) < 2e-3
    assert pg["wp"] and pg["wp"][-1][-1] in (0.0, 1.0)
    assert all(len(r) == 5 for r in pg["wp"])
    assert pg["pre"]["closing"]["p1"] == pytest.approx(an.devig2([1.5, 2.6]), abs=1e-4)
    up = next(m for m in ms if m["status"] == "upcoming")
    assert preds[up["id"]]["_ctx_date"] == ace_world["today"].isoformat()
    c = MT.card(td, up, preds[up["id"]])
    assert set(c) >= {"id", "event", "round", "date", "status", "p1", "p2", "winner", "sets", "live", "model", "market", "wp_now"}
    assert set(c["model"]) == {"p1", "sets_dist_top", "exp_games"} and len(c["model"]["sets_dist_top"]) == 3
    # the tournament page of the event in progress, with a simulation
    ev = dict(td.events(2026)[ace_world["live_event"]], id=ace_world["live_event"])
    sim = EV.simulate(td, ev, ms, 400)
    page = EV.build_event(td, ace_world["live_event"], 2026, preds, sim, None, EV.history(td))
    assert set(page) >= {"event", "draw", "sim", "market", "results", "upsets", "draw_difficulty", "awards", "history"}
    assert set(page["draw"]) >= {"rounds", "slots", "matches"} and page["draw"]["rounds"] == ["QF", "SF", "F"]
    alive = [p for p, r in page["sim"]["players"].items() if r["p_title"]]
    assert len(alive) == 4 and abs(sum(r["p_title"] for r in page["sim"]["players"].values()) - 1) < 1e-3
    assert all(c.get("node") for c in page["draw"]["matches"].values())
    dd = page["draw_difficulty"]
    assert sorted(v["rank"] for v in dd.values()) == list(range(1, len(dd) + 1))
    assert page["history"] and page["history"][0][0] == 2025


def test_careers_and_elo_payloads(ace_world):
    from oddsmarkets.tennis.analytics import players as PL
    from oddsmarkets.tennis.analytics import rankings as RK
    td = an.TourData("atp", ace_world["today"])
    ents = {y: PL.season_entries(td, y) for y in td.years}
    pid = ace_world["order"][0]
    path = PL.elo_path(td)[pid]
    assert all(len(r) == 5 for r in path)
    pay = PL.career_payload(td, pid, {y: ents[y].get(pid, []) for y in td.years}, {y: td.season_sr(y) for y in td.years}, path,
                            PL.rank_paths(td).get(pid), PL.results_rows(td, pid, [m for m in td.matches(2026).values()
                                                                                 if pid in (m["p1"], m["p2"])], {}),
                            PL.h2h_lists(td).get(pid), [], {}, None)
    assert set(pay) >= {"id", "name", "country", "hand", "dob", "height", "ranks", "elo", "serve_return", "seasons", "results", "splits",
                        "clutch", "style", "h2h", "to_defend", "odds"}
    assert {s["year"] for s in pay["seasons"]} == {2025, 2026}
    assert set(pay["clutch"]) == {"tb", "deciding", "from_set_down"}
    assert all(len(r) == 8 for r in pay["serve_return"])
    assert sum(s["w"] + s["l"] for s in pay["seasons"]) == sum(len(ents[y].get(pid, [])) for y in td.years)
    h = pay["h2h"][0]
    assert len(h) == 4 and h[1] + h[2] >= 1
    e = RK.build_elo(td)
    assert set(e) >= {"current", "peaks", "history"} and set(e["peaks"]) == {"all", "hard", "clay", "grass"}
    top = next(iter(e["current"].values()))
    assert set(top) - {"g"} == {"all", "hard", "clay", "grass", "n", "rank"}
    assert "g" not in top or len(top["g"]) == 4                  # game-share Elo [all, hard, clay, grass]


# ── draws with null seeded slots, implausible source dates (fixes found on real data) ───────────────

def test_complete_draw_fills_seeded_byes_and_sim_sums_to_one(ace_world):
    """A 16-slot bracket of 12 players: seeds 1-4 have byes and the draw left them null (as the WTA draw did
    for not-yet-linked seeds). Once the R16 results / pairings name them, every seed is placed."""
    from oddsmarkets.tennis.models import tournament_sim as TS
    order = ace_world["order"]
    seeds, rest = order[:4], order[4:12]
    slots, k, r16 = [], 0, []
    for blk in range(4):                                  # each quarter: [seed (null), bye, x, y]
        a, b = rest[k], rest[k + 1]
        k += 2
        slots += [[4 * blk + 1, None, blk + 1, None], [4 * blk + 2, None, None, None], [4 * blk + 3, a, None, None],
                  [4 * blk + 4, b, None, None]]
        r16.append({"id": f"r16-{blk}", "event": "e-2026", "round": "R16", "p1": a, "p2": b, "winner": a, "status": "done",
                    "sets": [[6, 3, None, None], [6, 3, None, None]], "best_of": 3, "surface": "hard"})
        r16.append({"id": f"qf-{blk}", "event": "e-2026", "round": "QF", "p1": seeds[blk], "p2": a, "winner": None,
                    "status": "upcoming", "sets": [], "best_of": 3, "surface": "hard"})
    # rounds of a 16 bracket: R16, QF, SF, F; each quarter's QF pairs slots 1-2 (seed + bye) with the R16 winner of 3-4
    draw = {"size": 16, "slots": [list(x) for x in slots]}
    n = an.complete_draw(draw, r16)
    assert n == 4
    assert not [x for x in draw["slots"] if x[1] is None and x[2]]
    assert {x[1] for x in draw["slots"] if x[2]} == set(seeds)
    td = an.TourData("atp", ace_world["today"])
    ev = {"id": "e-2026", "year": 2026, "level": "250", "surface": "hard", "best_of": 3, "draw_size": 12, "start": "2026-09-28",
          "draw": draw}
    sim = TS.simulate(ev, n=2000, matches=r16, tour="atp", ctx=td.today_context())
    pl = sim["players"]
    assert abs(sum(v["p_title"] for v in pl.values()) - 1) < 1e-6
    assert all(pl[s]["p_title"] > 0 for s in seeds)
    # a later-round player next to a block that already holds someone is never guessed into it
    d2 = {"size": 4, "slots": [[1, "A", 1, None], [2, "B", None, None], [3, None, None, None], [4, "C", None, None]]}
    assert an.complete_draw(d2, [{"round": "SF", "p1": "A", "p2": "Z"}]) == 0


def test_espn_and_merge_reject_1900_dates():
    import gzip
    from oddsmarkets.tennis import store as st
    from oddsmarkets.tennis.sources import espn
    from pathlib import Path
    raw = json.load(gzip.open(Path(__file__).parent / "fixtures" / "espn_atp_20260925.json.gz", "rt", encoding="utf-8"))
    good = espn.parse_scoreboard(raw, "atp")
    assert good and all(r["date"] is None or r["date"][:4] == "2026" for r in good)
    for ev in raw["events"]:
        for g in ev.get("groupings") or []:
            for c in g.get("competitions") or []:
                c["date"] = "1900-01-03T05:00Z"
    bad = espn.parse_scoreboard(raw, "atp")
    assert bad and all(r["date"] is None for r in bad)
    old = {"id": "m", "date": "2007-01-15", "status": "done", "sources": ["td"], "p1": "a", "p2": "b"}
    new = {"id": "m", "date": "1900-01-03T05:00", "status": "done", "sources": ["espn"], "p1": "a", "p2": "b"}
    assert st._merge_match(old, new)["date"] == "2007-01-15"
    new2 = dict(new, date="2007-01-15T11:00")
    assert st._merge_match(old, new2)["date"] == "2007-01-15T11:00"


def test_model_payload_and_lab_surface_block(ace_world):
    from oddsmarkets.tennis.analytics import players as PL
    from oddsmarkets.tennis.analytics import site as SI
    td = an.TourData("atp", ace_world["today"])
    mj = SI.model_payload(td)
    assert set(mj) >= {"elo", "blend", "serve_return", "final_set_rules", "best_of"}
    assert mj["elo"]["w_surf"] is not None and mj["elo"]["bo5"] is not None
    assert {"mu", "clay", "grass", "indoor", "bo5", "level"} <= set(mj["serve_return"]["base"])
    assert mj["final_set_rules"]["slams"]["wimbledon"] == "tb10"
    cats = {y: PL.build(td, y) for y in td.years}
    lab = SI.lab(td, cats)
    assert lab["fields"][:5] == ["id", "name", "year", "qualified", "rank"] and lab["fields"].count("matches") == 1
    assert all(len(r) == len(lab["fields"]) for r in lab["rows"])
    sb = lab["surface"]
    assert sb["fields"][:4] == ["id", "year", "surface", "matches"] and sb["rows"]
    assert {r[2] for r in sb["rows"]} <= {"hard", "clay", "grass"} and all(r[3] >= sb["min_matches"] for r in sb["rows"])
    ra = PL.results_all_rows(td)
    p0 = ace_world["order"][0]
    assert ra[p0] and all(len(r) == 7 and r[5] in (0, 1) for r in ra[p0])
    assert [r[0] for r in ra[p0]] == sorted(r[0] for r in ra[p0])
