"""
Who moves next (oddsmarkets/football/analytics/moves.py): windows, move types, the panel's no-look-ahead
features and labels, the models on planted signals, the base rates and the payload contract.

Offline: a synthetic league of six clubs (weekly matches, January 2025 to October 2026) and planted moves.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from oddsmarkets.football.analytics import moves as M
from oddsmarkets.football.analytics import value as V

LETTERS = ["G"] + ["D"] * 4 + ["M"] * 5 + ["F"] * 4
CLUBS = [101, 102, 103, 104, 105, 106]


def _rows(extra=None, drop_after: dict | None = None) -> V.Rows:
    """Six clubs of 14 players (ids club * 100 + k); the first 11 start every match, the rest play little."""
    rng = np.random.default_rng(3)
    days = [date(2025, 1, 4) + timedelta(days=7 * w) for w in range(95)]
    cols = {k: [] for k in ("pid", "match", "side", "day", "comp", "sid", "tid", "start", "mins", "letter", "role", "rating")}
    m_day, m_tid, m_npxg = [], [], []
    moved = dict(drop_after or {})              # pid -> (day ordinal, new club): plays for the new club from that day
    for w, d in enumerate(days):
        order = list(np.roll(CLUBS, w % 5))
        for k in range(3):
            h, a = order[2 * k], order[2 * k + 1]
            mi = len(m_day)
            m_day.append(d.toordinal())
            m_tid.append([h, a])
            m_npxg.append([1.2 + 0.1 * (h % 3), 1.0 + 0.1 * (a % 3)])
            for side, club in ((0, h), (1, a)):
                for kk in range(14):
                    pid = club * 100 + kk
                    tid = club
                    if pid in moved and d.toordinal() >= moved[pid][0]:
                        continue
                    starter = kk < 11
                    mins = 90.0 if starter else float(rng.integers(0, 25))
                    if mins <= 0:
                        continue
                    for col, v in (("pid", pid), ("match", mi), ("side", side), ("day", d.toordinal()), ("comp", 0), ("sid", 0),
                                   ("tid", tid), ("start", 1 if starter else 0), ("mins", mins),
                                   ("letter", V.LETTERS.index(LETTERS[kk])), ("role", -1), ("rating", 6.5 + 0.05 * (kk % 4))):
                        cols[col].append(v)
            # Players who moved play for their new club in its matches.
            for pid, (d0, new) in moved.items():
                if d.toordinal() >= d0 and new in (h, a):
                    for col, v in (("pid", pid), ("match", mi), ("side", 0 if new == h else 1), ("day", d.toordinal()), ("comp", 0),
                                   ("sid", 0), ("tid", new), ("start", 1), ("mins", 90.0),
                                   ("letter", V.LETTERS.index(LETTERS[pid % 100])), ("role", -1), ("rating", 6.8)):
                        cols[col].append(v)
    n = len(cols["pid"])
    if extra:
        extra(cols)
        n = len(cols["pid"])
    a = {k: np.array(v) for k, v in cols.items()}
    return V.Rows(pid=a["pid"].astype(np.int64), match=a["match"].astype(np.int64), side=a["side"].astype(np.int64),
                  day=a["day"].astype(np.int64), comp=a["comp"].astype(np.int64), sid=a["sid"].astype(np.int64),
                  tid=a["tid"].astype(np.int64), start=a["start"].astype(np.int64), mins=a["mins"].astype(np.float32),
                  letter=a["letter"].astype(np.int64), role=a["role"].astype(np.int64), rating=a["rating"].astype(np.float32),
                  X=np.zeros((n, V.NF), dtype=np.float32), comps=["premier-league"], comp_scope=["club"], sids=["s"],
                  current={"premier-league": "s"}, m_day=np.array(m_day), m_comp=np.zeros(len(m_day), dtype=np.int64),
                  m_tid=np.array(m_tid), m_npxg=np.array(m_npxg, dtype=float), m_goals=np.zeros((len(m_day), 2)),
                  m_gid=np.arange(len(m_day)))


def _move(pid, d, frm, to, kind, to_name=None, pos="M"):
    return {"pid": pid, "date": d, "day": d.toordinal(), "from": frm, "to": to, "kind": kind,
            "to_name": to_name if to_name is not None else (f"Club {to}" if to else "No team"), "pos": pos}


OFFSETS = {"premier-league": 0.7}
DOB = {str(c * 100 + k): f"{1990 + k}-03-01" for c in CLUBS for k in range(14)}


def test_windows_are_halves_and_the_horizon_is_the_next_one() -> None:
    assert M.half_start(date(2026, 10, 22)) == date(2026, 5, 1)
    assert M.half_start(date(2026, 1, 15)) == date(2025, 11, 1)
    assert M.half_start(date(2026, 11, 3)) == date(2026, 11, 1)
    assert M.horizon_of(date(2026, 10, 22)) == date(2026, 11, 1)
    assert M.horizon_of(date(2027, 1, 10)) == date(2026, 11, 1)
    assert M.horizon_of(date(2027, 3, 10)) == date(2027, 5, 1)
    assert M.half_label(date(2026, 11, 1)) == "Winter 2026/27" and M.half_label(date(2026, 5, 1)) == "Summer 2026"
    # Windows before the store's labels are complete are never used.
    ws = M.completed_windows(date(2026, 10, 22), date(2024, 1, 1))
    assert ws == [date(2025, 11, 1), date(2026, 5, 1)]


def test_move_types() -> None:
    d = date(2026, 1, 10)
    assert M.move_type(_move(1, d, 2, 3, "fee")) == "transfer"
    assert M.move_type(_move(1, d, 2, 3, "undisclosed")) == "transfer"
    assert M.move_type(_move(1, d, 2, 3, "free")) == "free"
    assert M.move_type(_move(1, d, 2, 3, "loan")) == "loan"
    assert M.move_type(_move(1, d, 2, 3, "loan_end")) == "loan_end"
    assert M.move_type(_move(1, d, 2, None, "free", to_name="No team")) == "release"
    assert M.move_type(_move(1, d, 2, 9, "undisclosed", to_name="Retired")) == "release"
    assert M.move_type(_move(1, d, 2, 3, "youth")) is None


def test_panel_features_use_only_the_past_and_labels_come_from_the_window() -> None:
    s = date(2025, 11, 1)
    moves = [
        _move(10105, date(2026, 1, 15), 101, 102, "fee"),                  # sold in the window
        _move(10206, date(2026, 2, 1), 102, None, "free", to_name="No team"),  # released
        _move(10307, date(2026, 7, 1), 103, 104, "fee"),                   # after the window: stays
        _move(10408, date(2025, 8, 1), 105, 104, "loan"),                  # arrived on loan before s
    ]
    R = _rows(drop_after={10509: (date(2026, 2, 7).toordinal(), 106)})     # plays for another club inside the window
    L = M.Lineups(R, {"premier-league"})
    P = M.build_panel(L, M.Records.build(moves), DOB, s, OFFSETS, labels=True, until=date(2026, 10, 21))
    ix = {int(p): i for i, p in enumerate(P.pid)}
    assert P.y[ix[10105]] == 1 and P.typ[ix[10105]] == "transfer" and P.dest[ix[10105]] == "same" and P.dest_tid[ix[10105]] == 102
    assert P.y[ix[10206]] == 1 and P.typ[ix[10206]] == "release" and P.dest[ix[10206]] is None
    assert P.y[ix[10307]] == 0
    assert P.y[ix[10509]] == 1 and P.typ[ix[10509]] is None and P.dest_tid[ix[10509]] == 106
    F = {c: i for i, c in enumerate(M.FEATURES)}
    assert P.X[ix[10408], F["on_loan"]] == 1 and P.X[ix[10105], F["on_loan"]] == 0
    assert P.X[0, F["summer"]] == 0
    # Changing everything after s leaves the features as they were.
    def bump(cols):
        for i, d in enumerate(cols["day"]):
            if d >= s.toordinal():
                cols["mins"][i] = 1.0
                cols["rating"][i] = 9.9
    P2 = M.build_panel(M.Lineups(_rows(bump, drop_after={10509: (date(2026, 2, 7).toordinal(), 106)}), {"premier-league"}),
                       M.Records.build(moves), DOB, s, OFFSETS, labels=False)
    assert np.array_equal(P2.pid, P.pid) and np.allclose(P2.X, P.X)


def test_models_recover_planted_signals() -> None:
    rng = np.random.default_rng(1)
    n = 4000
    X = rng.normal(size=(n, 3))
    p = 1 / (1 + np.exp(-(-1.0 + 1.5 * X[:, 0])))
    y = (rng.random(n) < p).astype(float)
    m = M.fit_logit(X, y, ("a", "b", "c"), 1.0)
    assert m.coef[0] > 1.0 and abs(m.coef[1]) < 0.15
    assert M.logloss(y, m.predict(X)).mean() < M.logloss(y, np.full(n, y.mean())).mean() - 0.05
    a, b = M.calib_slope(y, m.predict(X))
    assert abs(b - 1) < 0.15 and abs(a) < 0.15
    # Multinomial: the class follows the sign of the first column.
    yc = np.where(X[:, 0] > 0.5, 2, np.where(X[:, 0] < -0.5, 1, 0))
    sm = M.fit_softmax(X, yc, ("a", "b", "c"), ("x", "y", "z"), 1.0)
    acc = np.mean(sm.predict(X).argmax(axis=1) == yc)
    assert acc > 0.85 and np.allclose(sm.predict(X).sum(axis=1), 1)
    # Conditional logit: the chosen option is the one with the largest first feature.
    groups = []
    for _ in range(300):
        Z = rng.normal(size=(8, 2))
        u = 2.0 * Z[:, 0]
        pr = np.exp(u - u.max())
        groups.append((Z, int(rng.choice(8, p=pr / pr.sum()))))
    cl = M.fit_clogit(groups, 1.0)
    assert cl.coef[0] > 1.2 and abs(cl.coef[1]) < 0.4


def test_paired_ci_and_calibration_tables() -> None:
    rng = np.random.default_rng(2)
    a = rng.normal(0.1, 1, 2000)
    g = rng.integers(0, 50, 2000)
    m, lo, hi = M.paired_ci(a, np.zeros(2000), g, n_boot=400)
    assert lo < m < hi and abs(m - a.mean()) < 1e-9
    p = rng.random(1000)
    y = (rng.random(1000) < p).astype(float)
    cal = M.calibration(y, p)
    assert len(cal) == 10 and sum(c["n"] for c in cal) == 1000
    assert all(c["lo"] <= c["p_mean"] <= c["hi"] for c in cal)


def test_base_rates_shrink_cells_toward_the_league_and_loans_take_the_region() -> None:
    n = 200
    share = np.r_[np.full(100, 0.9), np.full(100, 0.05)]
    y = np.r_[np.zeros(100), np.ones(100)]
    P = M.Panel(date(2025, 11, 1), np.arange(n), np.full(n, 1), np.zeros(n, dtype=int), ["mls"] * n, np.zeros((n, len(M.FEATURES))),
                y, [], [], [], {"share": share, "on_loan": np.r_[np.zeros(190), np.ones(10)]})
    B = M.base_rates(P)
    reg, frg = B.cell[("mls", "regular")], B.cell[("mls", "fringe")]
    assert reg < B.league["mls"] < frg and 0 < reg and frg < 1
    r, basis = B.rate("mls", 0.9, False)
    assert r == reg and basis == "league_band"
    r, basis = B.rate("mls", 0.9, True)
    assert basis == "loan" and r == B.loan["North America"]
    r, basis = B.rate("liga-argentina", 0.9, False)
    assert basis == "region" and r == B.region["South America"]


def test_build_moves_payload_contract() -> None:
    rng = np.random.default_rng(5)
    moves, drop = [], {}
    # Movers in both windows: transfers and loans to other clubs of the league, releases, loan ends.
    for w0, n_mv in ((date(2025, 11, 1), 18), (date(2026, 5, 1), 24)):
        cands = [c * 100 + k for c in CLUBS for k in range(1, 14)]
        for pid in rng.choice(cands, n_mv, replace=False).tolist():
            if pid in drop or any(m["pid"] == pid for m in moves):
                continue
            frm = pid // 100
            d = w0 + timedelta(days=int(rng.integers(20, 120)))
            kind = ["fee", "loan", "free", "fee"][pid % 4]
            to = CLUBS[(CLUBS.index(frm) + 1 + pid % 4) % 6]
            moves.append(_move(pid, d, frm, to, kind, pos=LETTERS[pid % 100]))
            drop[pid] = (d.toordinal(), to)
    R = _rows(drop_after=drop)
    names = {c: f"Club {c}" for c in CLUBS}
    info = {c * 100 + k: {"name": f"P{c}{k}", "role": "CM", "proj": 0.01 * k} for c in CLUBS for k in range(14)}
    res = M.build_moves(R, moves, DOB, OFFSETS, date(2026, 10, 22), set(CLUBS), names, info, min_panel=10)
    meta = res["meta"]
    assert meta["ok"] and meta["horizon"] == "Winter 2026/27" and meta["reference"]["window"] == "Winter 2025/26"
    assert res["players"]["fields"] == M.P_FIELDS and res["players"]["rows"]
    for r in res["players"]["rows"]:
        d = dict(zip(M.P_FIELDS, r))
        assert 0 <= d["p"] <= 1 and 0 <= d["p_club"] <= d["p"] + 1e-9
        assert abs(sum(d["types"]) - 1) < 0.01 and abs(sum(d["dests"]) - 1) < 0.01 and len(d["types"]) == len(M.TYPES)
        assert d["band"] in M.BANDS and d["basis"] in ("league_band", "loan", "region")
    assert set(res["clubs"]) <= set(CLUBS) and res["clubs"]
    for tid, c in res["clubs"].items():
        assert set(c["expected_out"]) == set(M.LETTER_UNITS) == set(c["p_add"]) == set(c["expected_in"])
        assert all(0 <= v <= 1 for v in c["p_add"].values())
        assert abs(sum(c["expected_out"].values()) - c["out_total"]) < 0.05
        assert all(t["tid"] != tid for t in c["targets"]) and len(c["targets"]) <= M.TARGETS_PER_CLUB
        pj = [t["p_join"] for t in c["targets"]]
        assert pj == sorted(pj, reverse=True)
        assert all(r[0] for r in c["roster"]) and [r[1] for r in c["roster"]] == sorted((r[1] for r in c["roster"]), reverse=True)
    assert meta["validation"]["leave"]["passed"] is False and meta["validation"]["dest"]["passed"] is True
    # A player Sofascore's squads list at another club has moved: not in the population.
    some = res["players"]["rows"][0]
    res2 = M.build_moves(R, moves, DOB, OFFSETS, date(2026, 10, 22), set(CLUBS), names, info, min_panel=10,
                         club_of={some[0]: {"tid": 999}})
    assert some[0] not in {r[0] for r in res2["players"]["rows"]}


def test_without_a_window_of_the_same_kind_nothing_is_invented() -> None:
    R = _rows()
    res = M.build_moves(R, [], DOB, OFFSETS, date(2026, 10, 22), set(CLUBS), {}, {}, min_panel=10 ** 6)
    assert res["meta"]["ok"] is False and res["players"]["rows"] == [] and res["clubs"] == {}
