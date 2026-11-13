"""Payload builder on a tiny synthetic archive (no network, no OpenPowerlifting dump)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

import numpy as np

from oddsmarkets.powerlifting import canon, pages, store


def _archive(n_lifters=10, n_meets=8, today=date(2025, 11, 1)):
    rows = []
    meets = []
    for m in range(n_meets):
        day = (today - timedelta(days=20 * (n_meets - m))).isoformat()
        mid = canon.meet_id("USAPL", day, f"Meet {m}", "USA")
        meets.append({"meet_id": mid, "date": day, "name": f"Meet {m}", "fed": "USAPL",
                      "parent": "IPF", "country": "USA", "state": "TX", "n": n_lifters, "n_sbd": n_lifters})
        for i in range(n_lifters):
            name = f"Lifter {i}"
            sex = "M" if i % 2 == 0 else "F"
            bw = 90.0 if sex == "M" else 60.0
            total = 600.0 + 10 * i + m
            rows.append({
                "pid": canon.pid(name), "name": name, "sex": sex, "event": "SBD", "eq": "raw",
                "equipment": "Raw", "age": 28.0, "bw": bw, "wclass": "90" if sex == "M" else "63",
                "squat": total * 0.4, "bench": total * 0.25, "dead": total * 0.35, "total": total,
                "place": str(i + 1), "dots": canon.dots(sex, bw, total), "gl": 90.0, "tested": True,
                "country": "USA", "fed": "USAPL", "parent": "IPF", "date": day, "meet_id": mid,
                "meet_name": f"Meet {m}", "meet_country": "USA", "meet_state": "TX", "division": "Open",
            })
    return pd.DataFrame(rows), pd.DataFrame(meets)


def test_build_writes_index_rankings_meet_and_lifter(tmp_path, monkeypatch):
    entries, meets = _archive(n_lifters=20, n_meets=8)
    monkeypatch.setenv("POWERLIFTING_DATA", str(tmp_path / "raw"))
    store.save_table(store.entries_path(), entries)
    store.save_table(store.meets_path(), meets)
    out = tmp_path / "site"
    counts = pages.build(out, today=date(2025, 11, 1))
    assert counts["meets"] >= 1 and counts["players"] >= 1
    ix = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert ix["site"] == "The Quant Iron" and ix["counts"]["scored"] == len(entries)
    rk = json.loads((out / "rankings.json").read_text(encoding="utf-8"))
    assert rk["streams"]["men_raw"]["rows"] and rk["streams"]["women_raw"]["rows"]
    event_files = list((out / "events").glob("*.json"))
    assert event_files
    board = json.loads(event_files[0].read_text(encoding="utf-8"))
    assert board["board"][0]["name"].startswith("Lifter")
    player_files = list((out / "players").glob("*.json"))
    assert player_files
    pl = json.loads(player_files[0].read_text(encoding="utf-8"))
    assert pl["log"] and "exp" in pl["log"][0] and len(pl["log"][0]["a"]) == 9
    for f in ("lab.json", "records.json", "glossary.json", "search.json", "build.json"):
        assert (out / f).exists(), f
    scout = json.loads((out / "scout" / "men_raw.json").read_text(encoding="utf-8"))
    assert scout["cols"][:2] == ["id", "n"] and {m["id"] for m in scout["metrics"]} >= {"rt", "dots", "make"}
    assert list((out / "follow" / "lifter").glob("*.json"))
    rows = rk["streams"]["men_raw"]["rows"]
    assert all("pg" in r for r in rows) and rows[0]["rank"] == 1
    years = json.loads((out / "schedule" / "years.json").read_text(encoding="utf-8"))
    sched = json.loads((out / "schedule" / f"{years['years'][-1]}.json").read_text(encoding="utf-8"))
    assert sched["meets"][0]["page"] is True
    model = json.loads((out / "model.json").read_text(encoding="utf-8"))
    assert "openpowerlifting.org" in model["credit"]


def test_a_doping_disqualification_stays_in_its_flight_on_the_meet_page(tmp_path, monkeypatch):
    """No look-ahead (13 Nov 2026): a lifter disqualified for doping after the meet (place DD) lifted in the flight, so
    the meet page forecasts the flight with them, as it stood before the meet."""
    entries, meets = _archive(n_lifters=20, n_meets=8)
    last = meets["meet_id"].iloc[-1]
    who = (entries["meet_id"] == last) & (entries["name"] == "Lifter 18")
    entries.loc[who, "place"] = "DD"
    monkeypatch.setenv("POWERLIFTING_DATA", str(tmp_path / "raw"))
    store.save_table(store.entries_path(), entries)
    store.save_table(store.meets_path(), meets)
    out = tmp_path / "site"
    pages.build(out, today=date(2025, 11, 1))
    board = json.loads((out / "events" / f"{last}.json").read_text(encoding="utf-8"))["board"]
    dd = next(r for r in board if r["name"] == "Lifter 18")
    assert dd["place"] == "DD" and dd["exp"] is not None and dd["p_pod"] is not None
    men = [r for r in board if r["sex"] == "M" and r["fsize"]]
    assert {r["fsize"] for r in men} == {10}                  # ten men in the flight, the disqualified one included


def test_s_turns_pandas_na_into_empty_string():
    assert pages._s(None) == "" and pages._s(float("nan")) == "" and pages._s(np.nan) == ""
    assert pages._s("USA") == "USA"
