"""The Quant Iron's power rankings: pages._rank_paths (the monthly ranks the build publishes) and
oddsmarkets/powerlifting/power_build.py, end to end on the tiny synthetic archive of test_pages.py, plus the fallback
on a hand-made tree."""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from oddsmarkets.powerlifting import pages, store
from oddsmarkets.powerlifting import power_build as P

from .test_pages import _archive


def test_month_starts():
    m = pages.month_starts(pd.Timestamp("2026-11-01"))
    assert len(m) == pages.PATH_MONTHS and m[-1] == pd.Timestamp("2026-11-01") and m[0] == pd.Timestamp("2026-02-01")
    assert pages.month_starts(pd.Timestamp("2026-11-20"))[-1] == pd.Timestamp("2026-11-01")
    assert pages.month_starts(pd.Timestamp("2026-03-05"), 3)[0] == pd.Timestamp("2026-01-01")


def test_rank_paths_and_power_files_end_to_end(tmp_path, monkeypatch):
    entries, meets = _archive(n_lifters=20, n_meets=8)          # a meet every 20 days to 12 Oct 2025
    monkeypatch.setenv("POWERLIFTING_DATA", str(tmp_path / "raw"))
    store.save_table(store.entries_path(), entries)
    store.save_table(store.meets_path(), meets)
    out = tmp_path / "site"
    pages.build(out, today=date(2025, 11, 1))
    rp = json.loads((out / "rank_paths.json").read_text(encoding="utf-8"))
    assert rp["dates"][-1] == "2025-10-01" and len(rp["dates"]) == pages.PATH_MONTHS
    rk = json.loads((out / "rankings.json").read_text(encoding="utf-8"))
    men = rk["streams"]["men_raw"]["rows"]
    paths = rp["streams"]["men_raw"]
    assert set(paths) == {r["pid"] for r in men[:pages.PATH_TOP]}
    first = min(meets["date"])
    for pid, path in paths.items():
        assert len(path) == len(rp["dates"])
        for d, (rank, rt) in zip(rp["dates"], path):
            if d <= first:                          # nothing lifted before that day: unrated, unranked
                assert rank is None and rt is None
        # ranked on a day only with three scored meets before it, and ranks run 1..k without gaps
    on_last = sorted(p[-1][0] for p in paths.values() if p[-1][0] is not None)
    assert on_last == list(range(1, len(on_last) + 1))
    # the power files read it
    res = P.build(out)
    assert res["leagues"] == ["men_raw", "women_raw"]
    d = json.loads((out / "power" / "men_raw.json").read_text(encoding="utf-8"))
    assert d["step"] == "month" and d["snapshots"][-1]["label"] == "Now" and d["snapshots"][0]["label"] == "Dec 24"
    assert d["kind"] == "players" and d["noun"] == "lifters" and [p["key"] for p in d["parts"]] == ["s", "b", "d"]
    for t in d["teams"]:
        assert len(t["path"]) == len(d["snapshots"]) and t["path"][-1] == t["rank"]
        assert t["path"][:-1] == [x[0] for x in paths[t["id"]][:-1]]                 # the true ranks, not the order of these
        assert t["move"] == (t["prev"] - t["rank"] if t["prev"] is not None else None)
        assert "Won " not in (t.get("note") or "")                                   # W in the form is "beat our forecast"
    g = d["players"]["groups"]
    assert g and g[0]["metric"]["key"] == "rt" and [s["key"] for s in g[0]["stats"]][:3] == ["squat", "bench", "dead"]
    assert json.loads((out / "power.json").read_text(encoding="utf-8"))["default"] == "men_raw"


def _hand_tree(root, paths_stamp=None):
    rows = [{"rank": i + 1, "pid": f"p{i}", "name": "Chris Kennedy #1" if i == 0 else f"Lifter {i}", "cc": "USA", "rt": 600.0 - 10 * i,
             "n": 5, "cls": "93", "bw": 90.0, "best12": 590.0, "form": "WLW", "mv": [2, -1, None][i], "d90": [5.0, -2.0, None][i], "pg": True}
            for i in range(3)]
    (root / "rankings.json").write_text(json.dumps({"updated_at": "2026-11-14T00:17:15+00:00", "classes": {"M": ["93"], "F": []},
                                                    "unit": "DOTS", "streams": {"men_raw": {"rows": rows}}}), encoding="utf-8")
    (root / "build.json").write_text(json.dumps({"today": "2026-11-14", "updated_at": "2026-11-14T00:20:20+00:00"}), encoding="utf-8")
    if paths_stamp:
        (root / "rank_paths.json").write_text(json.dumps({"updated_at": paths_stamp, "dates": ["2026-10-01", "2026-11-01"],
                                                          "streams": {"men_raw": {"p0": [[1, 599.0], [1, 600.0]]}}}), encoding="utf-8")


def test_fallback_is_the_exact_90_day_ranking(tmp_path):
    _hand_tree(tmp_path)
    P.build(tmp_path)
    d = json.loads((tmp_path / "power" / "men_raw.json").read_text(encoding="utf-8"))
    assert [s["label"] for s in d["snapshots"]] == ["16 Aug", "Now"] and d["step"] == "quarter"
    t = {x["id"]: x for x in d["teams"]}
    assert (t["p0"]["prev"], t["p0"]["move"], t["p0"]["rpath"]) == (3, 2, [595.0, 600.0])
    assert t["p2"]["prev"] is None and t["p0"]["short"] == "Kennedy" and t["p0"]["abbr"] == "CK"


def test_paths_from_another_build_are_not_used(tmp_path):
    _hand_tree(tmp_path, paths_stamp="2026-11-01T00:00:00+00:00")
    P.build(tmp_path)
    assert json.loads((tmp_path / "power" / "men_raw.json").read_text(encoding="utf-8"))["step"] == "quarter"
    _hand_tree(tmp_path, paths_stamp="2026-11-14T00:18:00+00:00")
    P.build(tmp_path)
    d = json.loads((tmp_path / "power" / "men_raw.json").read_text(encoding="utf-8"))
    assert d["step"] == "month" and [s["label"] for s in d["snapshots"]] == ["Sep", "Now"]


def test_helpers():
    assert P.surname("Chris Kennedy #1") == "Kennedy" and P.initials("Chris Kennedy #1") == "CK"
    assert P.kg(1044.0) == "1,044 kg" and P.kg(272.5) == "272.5 kg"
    assert P.tidy("Up 1 place this month; No meet since X (1 Jan 2025).") == "Up 1 place this month; no meet since X (1 Jan 2025)."
    assert P.pool_rule(3000).startswith("in our top 3,000") and P.pool_rule(529).startswith("3+ scored meets")
