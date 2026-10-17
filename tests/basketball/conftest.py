"""Recorded ESPN answers (no network in tests) and a small builder for hand-made play-by-play."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"

# name -> (file, league, season)
GAMES = {
    "reg": ("nba_reg_401810433.json.gz", "nba", 2026),          # Berlin, neutral site, Jan 2026
    "playoff": ("nba_playoff_401859967.json.gz", "nba", 2026),  # NBA Finals game 5, 2026
    "ot": ("nba_ot_401810445.json.gz", "nba", 2026),            # one overtime
    "flagrant": ("nba_flagrant_401810434.json.gz", "nba", 2026),  # flagrant 1s, technicals, flagrant FTs
    "wnba": ("wnba_401857068.json.gz", "wnba", 2026),
    "y2018": ("nba_2018_400975384.json.gz", "nba", 2018),        # early play-by-play era (scoreValue 0 on FTs)
    "boxonly": ("nba_2003_boxonly_230115023.json.gz", "nba", 2003),  # no play-by-play, no plus-minus
}
PBP_GAMES = [k for k in GAMES if k != "boxonly"]


def load_raw(name: str) -> dict:
    with gzip.open(FIX / GAMES[name][0], "rt", encoding="utf-8") as fh:
        return json.load(fh)


def load_json(fname: str):
    p = FIX / fname
    if fname.endswith(".gz"):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def raw_games() -> dict[str, dict]:
    return {k: load_raw(k) for k in GAMES}


# ── hand-made games ─────────────────────────────────────────────────────────

H, A = "1", "2"
HP = [f"h{i}" for i in range(1, 9)]
AP = [f"a{i}" for i in range(1, 9)]


class PBP:
    """Builds compact play-by-play rows with a running score, for a two-team NBA game
    (home "1": h1..h8, away "2": a1..a8; h1-h5 and a1-a5 start)."""

    def __init__(self, league: str = "nba"):
        self.rows: list[list] = []
        self.hs = self.as_ = 0
        self.league = league

    def add(self, period, clock, type_id, team, parts, text, sv=0, shooting=0, scoring=0, pa=0, x=None, y=None):
        if scoring and team == H:
            self.hs += sv
        elif scoring and team == A:
            self.as_ += sv
        self.rows.append([len(self.rows) + 1, period, float(clock), type_id, team, list(parts), x, y, sv, shooting, scoring,
                          self.hs, self.as_, text, pa])
        return self

    # shorthands
    def shot(self, period, clock, team, shooter, made, pa=2, x=25, y=5, assist=None, block=None, type_id=92):
        verb = "makes" if made else "misses"
        txt = f"{shooter} {verb} {'three point' if pa == 3 else 'two point'} shot"
        parts = [shooter]
        if assist and made:
            txt += f" ({assist} assists)"
            parts.append(assist)
        if block and not made:
            txt = f"{block} blocks {shooter} 's shot"
            parts.append(block)
        return self.add(period, clock, type_id, team, parts, txt, sv=pa if made else 0, shooting=1, scoring=int(made), pa=pa, x=x, y=y)

    def ft(self, period, clock, team, shooter, made, n=1, of=1, kind=""):
        verb = "makes" if made else "misses"
        k = f"{kind} " if kind else ""
        tid = {"technical": 103, "flagrant": 104}.get(kind, 97 if of == 1 else 98)
        txt = f"{shooter} {verb} {'technical free throw' if kind == 'technical' else f'free throw {k}{n} of {of}'}"
        return self.add(period, clock, tid, team, [shooter], txt, sv=1 if made else 0, shooting=1, scoring=int(made), pa=1)

    def reb(self, period, clock, team, player, off):
        txt = f"{player or 'team'} {'offensive' if off else 'defensive'} rebound"
        return self.add(period, clock, 156 if off else 155, team, [player] if player else [], txt)

    def tov(self, period, clock, team, player, steal=None):
        txt = f"{player} bad pass turnover" + (f" ({steal} steals)" if steal else "")
        return self.add(period, clock, 62, team, [player] + ([steal] if steal else []), txt)

    def foul(self, period, clock, team, player, kind="shooting"):
        tid = {"shooting": 44, "personal": 45, "technical": 35, "flagrant": 32}[kind]
        return self.add(period, clock, tid, team, [player], f"{player} {kind} foul")

    def sub(self, period, clock, team, pin, pout):
        return self.add(period, clock, 584, team, [pin, pout], f"{pin} enters the game for {pout}")

    def jump(self, period, clock, team, p1, p2, gainer):
        return self.add(period, clock, 615, team, [p1, p2, gainer], f"{p1} vs. {p2} ({gainer} gains possession)")

    def end_period(self, period):
        return self.add(period, 0.0, 412, None, [], f"End of the {period} Quarter")

    def pbp(self) -> dict:
        return {"id": "999", "periods": max(r[1] for r in self.rows), "plays": self.rows, "types": {}, "wp": {}}

    def game(self, secs: dict | None = None) -> dict:
        secs = secs or {}

        def rows(ids, team):
            out = []
            for i, pid in enumerate(ids):
                pts = 0
                out.append([pid, 1 if i < 5 else 0, secs.get(pid, 0), pts] + [0] * 13 + [None])
            return out

        return {"id": "999", "date": "2026-01-01T00:00:00Z", "status": "post", "stype": "reg", "neutral": False, "home": H, "away": A,
                "hs": self.hs, "as": self.as_, "periods": max(r[1] for r in self.rows), "line": {"home": [], "away": []},
                "box": {H: {"players": rows(HP, H), "dnp": [], "team": {}}, A: {"players": rows(AP, A), "dnp": [], "team": {}}},
                "odds": None, "injuries": {}, "venue": None, "attendance": None, "series": None, "has_pbp": True}


@pytest.fixture
def builder():
    return PBP
