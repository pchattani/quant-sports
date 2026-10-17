"""
Transfers for The Quant Footballer: the Sofascore transfer endpoints and the fetcher's
rotation (scripts/fetch_sofascore_history.py phase 4), and the analytics built on them
(oddsmarkets/football/analytics/transfers.py): windows, deal kinds, value at the time of a
move, the fair fee model and its validation, grades, ledgers and budgets.

Offline: monkeypatched Sofascore calls and synthetic transfers.
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from oddsmarkets.football.sources import sofascore as S  # noqa: E402

TODAY = datetime(2026, 10, 16, tzinfo=timezone.utc)


def _item(tid_from, tid_to, kind, fee=None, desc="-", pid=7, ts=1787270400, tid=1):
    out = {"player": {"id": pid, "name": f"P{pid}", "position": "M"}, "transferFrom": {"id": tid_from, "name": f"C{tid_from}"},
           "transferTo": {"id": tid_to, "name": f"C{tid_to}"}, "fromTeamName": f"C{tid_from}", "toTeamName": f"C{tid_to}",
           "type": kind, "transferFeeDescription": desc, "transferDateTimestamp": ts, "id": tid}
    if fee is not None:
        out["transferFee"] = fee
        out["transferFeeRaw"] = {"value": fee, "currency": "EUR"}
    return out


# ── the endpoints ────────────────────────────────────────────────────────────

def test_parse_transfer_keeps_fee_kind_and_clubs() -> None:
    r = S.parse_transfer(_item(40, 42, 3, fee=59600000, desc="59.6M €", tid=3665958))
    assert r == {"i": 3665958, "p": "7", "n": "P7", "ps": "M", "f": 40, "fn": "C40", "t": 42, "tn": "C42", "k": 3,
                 "fee": 59600000, "d": "59.6M €", "ts": 1787270400}
    loan = S.parse_transfer(_item(42, 99, 1, desc="-"))
    assert loan["k"] == 1 and "fee" not in loan                       # no figure published: no fee key
    assert S.parse_transfer({"player": {"id": 1}}) is None             # no date
    assert S.transfer_key(r) == "3665958" and S.transfer_key({"p": "7", "ts": 5, "f": 1, "t": 2}) == "7:5:1:2"
    usd = _item(1, 2, 3, fee=1000000)
    usd["transferFeeRaw"]["currency"] = "USD"
    assert S.parse_transfer(usd)["cur"] == "USD"


def test_team_transfers_and_player_history_parse_and_fail_soft(monkeypatch) -> None:
    payloads = {"/team/42/transfers": {"transfersIn": [_item(40, 42, 3, fee=5, tid=1)], "transfersOut": [_item(42, 50, 1, tid=2, pid=8)]},
                "/player/7/transfer-history": {"transferHistory": [{**_item(1, 2, 3, fee=0, desc="Free", tid=3), "player": None}]}}
    monkeypatch.setattr(S, "get_json", lambda path, quiet=False, timeout=20: payloads.get(path))
    monkeypatch.setattr(S, "DETAIL_PAUSE_S", 0)
    rows = S.team_transfers(42, S.CallBudget(1))
    assert [(r["p"], r["k"]) for r in rows] == [("7", 3), ("8", 1)]
    hist = S.player_transfer_history(7, S.CallBudget(1))
    assert hist[0]["p"] == "7" and hist[0]["fee"] == 0 and hist[0]["d"] == "Free"
    assert S.team_transfers(1) is None and S.player_transfer_history(1) is None
    with pytest.raises(S.BudgetExhausted):
        S.team_transfers(42, S.CallBudget(0))


# ── the rotation ─────────────────────────────────────────────────────────────

def test_transfer_queues_order_and_back_off(tmp_path) -> None:
    h = importlib.import_module("fetch_sofascore_history")
    clubs = {"1": {"priority": 1}, "2": {"priority": 0}, "3": {"priority": 0}, "4": {"priority": 0}, "5": {"priority": 0}}
    doc = {"teams": {"3": {"fetched_at": "2026-10-01T00:00:00Z"}, "4": {"fetched_at": "2026-10-15T00:00:00Z"}},
           "players": {"11": {"fetched_at": "2026-10-01T00:00:00Z"}}, "failed": {"t5": {"at": "2026-10-10T00:00:00Z"}}}
    # Followed clubs before cup clubs, never fetched before stale; "4" is fresh (7 days), "5" failed recently.
    assert h.transfer_team_queue(clubs, doc, TODAY) == ["2", "3", "1"]
    vp = tmp_path / "players.json"
    vp.write_text(json.dumps({"fields": ["id", "min"], "rows": [["10", 500], ["11", 3000], ["12", 2000], ["13", 100]]}), encoding="utf-8")
    # Most minutes first, under PLAYER_MIN_MINUTES left out, fetched within PLAYER_REFRESH_DAYS left out.
    assert h.transfer_player_queue(doc, vp, TODAY) == ["12", "10"]
    assert h.transfer_player_queue(doc, tmp_path / "missing.json", TODAY) == []


def test_fetch_transfers_spends_the_budget_followed_clubs_then_players_then_cups(monkeypatch, tmp_path) -> None:
    h = importlib.import_module("fetch_sofascore_history")
    calls = []

    def team(tid, budget=None):
        if not budget.take():
            raise S.BudgetExhausted(tid)
        calls.append("t" + str(tid))
        S.LAST_STATUS = 404 if str(tid) == "9" else 200
        return None if str(tid) == "9" else [S.parse_transfer(_item(int(tid), 100, 3, fee=1000, tid=int(tid) * 10))]

    def player(pid, budget=None):
        if not budget.take():
            raise S.BudgetExhausted(pid)
        calls.append("p" + str(pid))
        S.LAST_STATUS = 200
        return [S.parse_transfer(_item(1, 2, 3, fee=5, pid=int(pid), tid=int(pid) * 1000))]

    monkeypatch.setattr(S, "team_transfers", team)
    monkeypatch.setattr(S, "player_transfer_history", player)
    monkeypatch.setattr(h, "PAUSE_S", 0)
    vp = tmp_path / "players.json"
    vp.write_text(json.dumps({"fields": ["id", "min"], "rows": [[str(i), 3000 - i] for i in range(1, 30)]}), encoding="utf-8")
    clubs = {"2": {"priority": 0}, "9": {"priority": 0}, "3": {"priority": 0}, **{str(c): {"priority": 1} for c in range(50, 60)}}
    store = tmp_path / "store.json"
    stats = h.fetch_transfers(S.CallBudget(12), clubs=clubs, path=store, value_players=vp)
    # Three followed clubs (one without a page), then players down to the cup reserve (a fifth of
    # what is left, at most CUP_RESERVE), then the cup clubs with the rest.
    assert calls == ["t2", "t3", "t9"] + [f"p{i}" for i in range(1, 9)] + ["t50"]
    doc = json.loads(store.read_text(encoding="utf-8"))
    assert stats["failed"] == 1 and "t9" in doc["failed"] and set(doc["teams"]) == {"2", "3", "50"}
    assert len(doc["transfers"]) == stats["new"] == 11 and doc["meta"]["n_transfers"] == 11
    # The next run carries on where this one stopped and never re-asks a club that is current.
    calls.clear()
    h.fetch_transfers(S.CallBudget(3), clubs=clubs, path=store, value_players=vp)
    assert calls == ["p9", "p10", "p11"]
    # A 403 stops the run at once.
    calls.clear()
    monkeypatch.setattr(S, "player_transfer_history", lambda pid, budget=None: (budget.take(), setattr(S, "LAST_STATUS", 403))[1])
    h.fetch_transfers(S.CallBudget(10), clubs=clubs, path=store, value_players=vp)
    assert S.is_blocked() and calls == []
    S.LAST_STATUS = None


# ── the analytics (transfers.py) ─────────────────────────────────────────────

from oddsmarkets.football.analytics import transfers as TR  # noqa: E402
from oddsmarkets.football.analytics import value as V  # noqa: E402


def test_windows_and_deal_kinds() -> None:
    assert TR.window_of(date(2026, 8, 1)) == ("2026-S", "Summer 2026")
    assert TR.window_of(date(2025, 12, 1)) == ("2026-W", "Winter 2025/26") and TR.window_of(date(2026, 1, 20))[0] == "2026-W"
    assert TR.latest_windows(date(2026, 10, 16)) == ("2026-S", "2026-W", "2027-W")
    assert TR.latest_windows(date(2026, 7, 1)) == ("2025-S", "2025-W", "2026-S")
    assert TR.deal_kind({"k": 3, "fee": 5_000_000}) == "fee"
    assert TR.deal_kind({"k": 3, "fee": 0, "d": "Free"}) == "free"
    assert TR.deal_kind({"k": 3, "fee": 0, "d": "-", "fn": "Arsenal U21"}) == "youth"
    assert TR.deal_kind({"k": 3, "fee": 0, "d": "-", "fn": "Brentford"}) == "undisclosed"
    assert TR.deal_kind({"k": 3, "fee": 9, "cur": "USD"}) == "undisclosed"           # not converted, never summed
    assert TR.deal_kind({"k": 1}) == "loan" and TR.deal_kind({"k": 2}) == "loan_end"
    ts = lambda y, m, d: int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())  # noqa: E731
    store = {"transfers": {"1": {"p": "7", "ts": ts(2026, 8, 1), "f": 1, "t": 2, "k": 3, "fee": 2e6},
                           "2": {"p": "8", "ts": ts(2027, 1, 1), "f": 1, "t": 2, "k": 1}}}
    rows = TR.normalise(store, date(2026, 10, 16))
    assert [r["key"] for r in rows] == ["1"] and rows[0]["fee"] == 2e6 and rows[0]["window"] == "2026-S"   # a future date is dropped


def test_history_windows_and_availability_count_the_clubs_matches() -> None:
    import tests.test_value_football as tv

    R = tv._synthetic_rows(n_players=220, n_matches=600)
    vals = np.ones((len(R), len(V.COMPONENTS_OUT))) * 0.01
    H = TR.History(R, vals, np.zeros(len(R)))
    pid = int(R.pid[0])
    d0, d1 = int(R.day.min()), int(R.day.max()) + 1
    mins, gar, apps = H.window(pid, d0, d1)
    sel = R.pid == pid
    assert mins == pytest.approx(R.mins[sel].sum()) and apps == int(sel.sum()) and gar == pytest.approx(0.1 * apps)
    _, share, n = H.availability(pid, d1, span_days=10_000)
    # He played every match of his club in the synthetic league: a share of 1, shrunk below 1.
    assert share == pytest.approx(1.0) and n == apps
    assert TR.shrunk_availability(1.0, n) < 1.0 and TR.shrunk_availability(float("nan"), 0) == TR.AVAIL_PRIOR


def test_value_v2_rises_with_projection_and_falls_with_age_with_a_band() -> None:
    P = TR.V2Params(ppg=0.69, slope=0.3, curve={a: (0.05 if a < 25 else -0.05) for a in range(17, 39)},
                    survive={a: (1.0 if a < 30 else 0.7) for a in range(17, 41)}, var_within=0.03, sigma_age=0.03)
    proj = np.array([0.05, 0.2, 0.2, 0.2])
    mean, lo, hi, y1 = TR.value_v2(proj, np.array([30, 30, 30, 30.0]), np.array([24, 24, 34, np.nan]), np.full(4, 0.7), P)
    assert mean[1] > mean[0] and mean[1] > mean[2]
    assert np.all(lo <= mean) and np.all(mean <= hi) and np.all(y1 <= mean)


def test_fee_model_beats_the_baseline_on_a_planted_relationship() -> None:
    rng = np.random.default_rng(1)
    n = 400
    v2 = rng.gamma(2.0, 3.0, n)
    age = rng.uniform(18, 33, n)
    unit = [str(u) for u in rng.choice(["GK", "CB", "FB", "MID", "ATT", "ST"], n)]
    bx = rng.normal(0.2, 0.5, n)
    bx[:40] = np.nan
    X = TR.features(v2, rng.normal(0.1, 0.1, n), age, unit, rng.normal(0, 0.5, n), bx, rng.uniform(5, 40, n))
    y = 14.5 + 1.1 * np.log1p(v2) - 0.004 * (age - 26) ** 2 + 0.8 * np.nan_to_num(bx, nan=-0.6) + rng.normal(0, 0.4, n)
    report, cv, lam = TR.validate_fee(X, y, np.arange(n), np.arange(n) + 700_000, [(u,) for u in unit])
    assert report["cv"]["model"]["mdae_log"] < report["cv"]["baseline_median"]["mdae_log"]
    assert report["cv"]["model"]["spearman"] > 0.7 and "time_split" in report and lam in TR.FEE_LAMBDAS
    m = TR.fit_fee(X, y, lam)
    assert m.coef[0] > 0 and m.coef[TR.FEATURES.index("buyer_xgd")] > 0
    assert set(m.to_json()) >= {"features", "mean", "sd", "coef", "intercept", "sigma"}


def test_grades_perf_and_budgets() -> None:
    assert TR.grade_letters(np.arange(10.0)) == ["E", "E", "D", "D", "C", "C", "B", "B", "A", "A"]
    s_good, w = TR.perf_score(gar_post=10.0, min_post=1800.0, proj_pre=0.1, share_post=0.9)
    s_bad, _ = TR.perf_score(gar_post=-2.0, min_post=1800.0, proj_pre=0.1, share_post=0.3)
    assert s_good > 0 > s_bad and w == 1.0 and TR.perf_score(0, 450, 0.1, None)[1] == 0.25
    rng = np.random.default_rng(2)
    clubs = list(range(1, 81))
    sums = {}
    for c in clubs:
        base = rng.uniform(0, 60e6)
        sums[c] = {"2026-W": {"spend": base * 0.2, "income": base * 0.1}, "2026-S": {"spend": base * rng.uniform(0.6, 1.4), "income": base * 0.5}}
    out = TR.fit_budgets(sums, clubs, set(clubs[:70]), {c: None for c in clubs}, {c: "premier-league" for c in clubs},
                         {"premier-league": 0.7}, {c: 0.0 for c in clubs}, date(2026, 10, 16))
    rep = out["report"]
    assert rep["ok"] and rep["n_clubs"] == 70 and rep["market_values"] is False and 0 < rep["winter_ratio"] < 1
    b = out["clubs"][1]
    assert b["summer"]["lo80"] <= b["summer"]["lo"] <= b["summer"]["mid"] <= b["summer"]["hi"] <= b["summer"]["hi80"]
    assert b["next"]["window"] == "2027-W" and b["next"]["hi"] < b["summer"]["hi"]
    few = TR.fit_budgets(sums, clubs, set(clubs[:5]), {}, {}, {}, {}, date(2026, 10, 16))
    assert few["report"]["ok"] is False and few["clubs"] == {}
