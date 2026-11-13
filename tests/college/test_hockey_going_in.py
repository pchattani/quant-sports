"""College hockey game pages, no look-ahead (13 Nov 2026): the going-in tape of a started game (build.tape_pre) is
the walk-forward's own fit for the game day and the record before it, and nothing on or after the game day moves it.
Small synthetic seasons (no network, no CHN data)."""
from __future__ import annotations

import copy
from datetime import date

import pytest

from oddsmarkets.college.hockey import build as B, model as M

from .test_hockey_models import _season


def _ctx(st: dict) -> dict:
    preds, ends = M.walk_forward([2026], {2026: st})
    return {"level": "mch", "stores": {2026: st}, "p": dict(M.DEFAULTS), "preds": preds,
            "pred": {p["id"]: p for p in preds}, "ends": ends, "bundles": {}}


def test_going_in_replays_the_walk_forward_fit():
    st, _ = _season(n_rounds=10)
    ctx = _ctx(st)
    assert ctx["preds"]
    for pr in ctx["preds"]:
        lh, la = B.fit_before(ctx, 2026, pr["day"]).means(pr["home"], pr["away"], pr["neutral"])
        assert lh == pytest.approx(pr["lh"], rel=1e-9) and la == pytest.approx(pr["la"], rel=1e-9)


def test_going_in_uses_only_games_before_the_day():
    st, _ = _season(n_rounds=10)
    g = st["games"][len(st["games"]) // 2]
    day = M.game_day(g)
    before = B.tape_pre(_ctx(st), 2026, g)
    assert before["day"] == date.fromordinal(day).isoformat() and set(before["teams"]) == {g["home"], g["away"]}
    n = sum(1 for x in st["games"] if M.game_day(x) < day and g["home"] in (x["home"], x["away"]))
    row = before["teams"][g["home"]]
    assert n > 0 and row["games"] == n and row["w"] + row["l"] + row["t"] == n
    # turn round every result on or after the game's day, the game itself included: the block must not move
    st2 = copy.deepcopy(st)
    for x in st2["games"]:
        if M.game_day(x) >= day:
            x["hs"], x["as"] = x["as"], x["hs"]
            x["res"] = {"W": "L", "L": "W", "T": "T"}[x["res"]]
    g2 = next(x for x in st2["games"] if x["id"] == g["id"])
    assert B.tape_pre(_ctx(st2), 2026, g2) == before
    # and today's season ratings do move (the block is not today's number)
    assert B.going_in(_ctx(st2), 2026, max(M.game_day(x) for x in st2["games"]) + 1) != \
        B.going_in(_ctx(st), 2026, max(M.game_day(x) for x in st["games"]) + 1)


def test_no_tape_before_the_start():
    st, _ = _season(n_rounds=4)
    g = dict(st["games"][-1], status="pre", res=None, hs=None)
    g["as"] = None
    assert B.tape_pre(_ctx(st), 2026, g) is None
