"""
The NFL tiebreaking procedure (canon.DIVISION_TWO / DIVISION_THREE / WILDCARD_TWO / WILDCARD_THREE), applied
to a season's results: division order, Wild Card order and conference seeding.

    tb = Table(games, season)                 # games: dicts with home, away, hs, as (completed regular season)
    tb.division_order("AFC North")            # all clubs of the division, first to last
    tb.order(["BUF", "MIA", "NYJ"], "wc")     # a tied group ordered by the Wild Card procedure
    tb.seed_conference("AFC")                 # {"seeds": [...], "division_winners": [...], "order": [...]}
    tb.trace                                  # (step key, clubs, winner) for every decision taken

Ties count half a win (canon.TIEBREAK_NOTES). One club advances per application of the procedure; the
remaining clubs start again at step 1 (two-club format when two remain). Clubs eliminated within a step:
two left restart at Step 1 of the two-club format; three or more restart at Step 1 (division) or Step 2 (Wild
Card) of the three-club format (the procedure's notes). Interpretations where the text is silent are in
canon.TIEBREAK_INTERPRETATION. `tds` (team -> (touchdowns scored, touchdowns allowed)) feeds the
net-touchdowns step; `rng` (random.Random) is the coin.

The season simulation (builder C) builds one Table per simulated season; everything is plain Python on at
most 32 clubs and 272-285 games, and division orders are cached per Table.
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Iterable

from . import canon

EPS = 1e-9


class Table:
    def __init__(self, games: Iterable, season: int, tds: dict | None = None, rng: random.Random | None = None,
                 teams: dict | None = None):
        self.season = int(season)
        self.teams = teams or canon.teams(season)
        self.div = {t: v["div"] for t, v in self.teams.items()}
        self.conf = {t: v["conf"] for t, v in self.teams.items()}
        self.tds = tds or {}
        self.rng = rng or random.Random(0)
        self.trace: list[tuple] = []
        self._games: dict[str, list[tuple[str, float, float]]] = defaultdict(list)   # team -> [(opp, pf, pa)]
        for g in games:
            if isinstance(g, dict):
                if g.get("gtype", "REG") != "REG":
                    continue
                h, a, hs, as_ = g.get("home"), g.get("away"), g.get("hs"), g.get("as")
            else:
                h, a, hs, as_ = g[:4]
            if hs is None or as_ is None or h not in self.div or a not in self.div:
                continue
            self._games[h].append((a, float(hs), float(as_)))
            self._games[a].append((h, float(as_), float(hs)))
        self._div_order: dict[str, list[str]] = {}
        self._pct_all = {t: self._pct(self._games[t]) for t in self.teams}
        self._ranks: dict[str, dict[str, float]] = {}

    # ── records ──────────────────────────────────────────────────────────────

    @staticmethod
    def _wlt(rows) -> tuple[int, int, int]:
        w = sum(1 for _o, pf, pa in rows if pf > pa)
        l_ = sum(1 for _o, pf, pa in rows if pf < pa)
        return w, l_, len(rows) - w - l_

    @classmethod
    def _pct(cls, rows) -> float:
        rows = list(rows)
        if not rows:
            return 0.5
        w, _l, t = cls._wlt(rows)
        return (w + 0.5 * t) / len(rows)

    def record(self, team: str) -> tuple[int, int, int]:
        return self._wlt(self._games[team])

    def pct(self, team: str) -> float:
        return self._pct_all[team]

    def games_of(self, team: str) -> list[tuple[str, float, float]]:
        return list(self._games[team])

    def _vs(self, team: str, opps) -> list:
        opps = set(opps)
        return [r for r in self._games[team] if r[0] in opps]

    def _common_opps(self, clubs) -> set[str]:
        sets = [{o for o, _pf, _pa in self._games[c]} for c in clubs]
        return set.intersection(*sets) if sets else set()

    # ── step metrics: higher is better; None = step not applicable ───────────

    def _metric(self, key: str, clubs: list[str]) -> dict[str, float] | None:
        if key == "h2h" or key == "h2h_if":
            if key == "h2h_if":
                if len(clubs) != 2 or not self._vs(clubs[0], [clubs[1]]):
                    return None
            rows = {c: self._vs(c, [x for x in clubs if x != c]) for c in clubs}
            if any(not r for r in rows.values()):
                return None if key == "h2h_if" else {c: self._pct(rows[c]) for c in clubs}
            return {c: self._pct(rows[c]) for c in clubs}
        if key == "div_pct":
            return {c: self._pct(self._vs(c, [t for t, d in self.div.items() if d == self.div[c] and t != c])) for c in clubs}
        if key == "conf_pct":
            return {c: self._pct(self._vs(c, [t for t, f in self.conf.items() if f == self.conf[c] and t != c])) for c in clubs}
        if key in ("common_pct", "common_pct4", "common_net"):
            co = self._common_opps(clubs)
            rows = {c: self._vs(c, co) for c in clubs}
            if not co:
                return None
            if key == "common_pct4" and any(len(r) < 4 for r in rows.values()):
                return None
            if key == "common_net":
                return {c: sum(pf - pa for _o, pf, pa in rows[c]) for c in clubs}
            return {c: self._pct(rows[c]) for c in clubs}
        if key == "sov":
            out = {}
            for c in clubs:
                beaten = [o for o, pf, pa in self._games[c] if pf > pa]
                out[c] = self._combined(beaten)
            return out
        if key == "sos":
            return {c: self._combined([o for o, _pf, _pa in self._games[c]]) for c in clubs}
        if key == "conf_rank":
            return {c: -self._rank(c, "conf") for c in clubs}
        if key == "all_rank":
            return {c: -self._rank(c, "all") for c in clubs}
        if key == "conf_net":
            return {c: sum(pf - pa for _o, pf, pa in self._vs(c, [t for t, f in self.conf.items() if f == self.conf[c] and t != c]))
                    for c in clubs}
        if key == "all_net":
            return {c: sum(pf - pa for _o, pf, pa in self._games[c]) for c in clubs}
        if key == "net_td":
            if not all(c in self.tds for c in clubs):
                return None
            return {c: float(self.tds[c][0]) - float(self.tds[c][1]) for c in clubs}
        raise KeyError(key)

    def _combined(self, opps: list[str]) -> float:
        """Combined won-lost-tied percentage of a list of opponents (each appearance counts)."""
        g = w = 0.0
        for o in opps:
            ww, ll, tt = self.record(o)
            n = ww + ll + tt
            g += n
            w += ww + 0.5 * tt
        return w / g if g else 0.0

    def _rank(self, team: str, scope: str) -> float:
        key = f"{scope}:{self.conf[team] if scope == 'conf' else ''}"
        if key not in self._ranks:
            pool = [t for t in self.teams if scope == "all" or self.conf[t] == self.conf[team]]
            pf = {t: sum(r[1] for r in self._games[t]) for t in pool}
            pa = {t: sum(r[2] for r in self._games[t]) for t in pool}

            def comp_rank(vals: dict, higher_better: bool) -> dict:
                return {t: 1 + sum(1 for u in pool if (vals[u] > vals[t] if higher_better else vals[u] < vals[t]))
                        for t in pool}
            rs, ra = comp_rank(pf, True), comp_rank(pa, False)
            self._ranks[key] = {t: rs[t] + ra[t] for t in pool}
        return self._ranks[key][team]

    # ── the procedure ────────────────────────────────────────────────────────

    def _pick_one(self, clubs: list[str], kind: str, start: int = 0) -> str:
        """The single club that advances from a tied group (kind "div" or "wc"), from step index `start`."""
        clubs = sorted(clubs)
        if len(clubs) == 1:
            return clubs[0]
        if kind == "wc" and len({self.div[c] for c in clubs}) == 1:
            kind = "div"
            start = 0
        if kind == "div":
            steps = canon.DIVISION_TWO if len(clubs) == 2 else canon.DIVISION_THREE
        else:
            steps = canon.WILDCARD_TWO if len(clubs) == 2 else canon.WILDCARD_THREE
        if len(clubs) == 2:
            start = 0
        pool = list(clubs)
        for key, _text in steps[start:]:
            if key == "coin":
                win = self.rng.choice(pool)
                self.trace.append((key, tuple(pool), win))
                return win
            if key == "div_reduce":
                best: dict[str, str] = {}
                for c in pool:
                    d = self.div[c]
                    order = self.division_order(d)
                    if d not in best or order.index(c) < order.index(best[d]):
                        best[d] = c
                reduced = sorted(best.values())
                if len(reduced) < len(pool):
                    self.trace.append((key, tuple(pool), tuple(reduced)))
                pool = reduced
                if len(pool) == 1:
                    return pool[0]
                if len(pool) == 2:
                    return self._pick_one(pool, "wc")
                continue
            if key == "h2h_sweep":
                swept = self._sweep(pool)
                if swept is None:
                    continue
                kind_s, club = swept
                if kind_s == "won":
                    self.trace.append((key, tuple(pool), club))
                    return club
                pool = [c for c in pool if c != club]
                self.trace.append((key + ":out", tuple(sorted(pool + [club])), club))
                return self._restart(pool, kind)
            vals = self._metric(key, pool)
            if vals is None:
                continue
            top_v = max(vals.values())
            top = [c for c in pool if vals[c] >= top_v - EPS]
            if len(top) == 1:
                self.trace.append((key, tuple(pool), top[0]))
                return top[0]
            if len(top) < len(pool):
                self.trace.append((key + ":out", tuple(pool), tuple(top)))
                return self._restart(top, kind)
        raise AssertionError("unreachable: the coin toss always decides")

    def _restart(self, pool: list[str], kind: str) -> str:
        """Clubs eliminated within a step: two left restart at Step 1 of the two-club format; three or more
        restart at Step 1 (division) or Step 2 (Wild Card, after the division reduction) of the three-club format."""
        if len(pool) == 1:
            return pool[0]
        if len(pool) == 2:
            return self._pick_one(pool, kind)
        return self._pick_one(pool, kind, start=1 if kind == "wc" else 0)

    def _sweep(self, clubs: list[str]) -> tuple[str, str] | None:
        """("won", club) if a club defeated each of the others, ("lost", club) if one lost to each."""
        for c in clubs:
            others = [x for x in clubs if x != c]
            per = [self._vs(c, [o]) for o in others]
            if all(p and all(pf > pa for _o, pf, pa in p) for p in per):
                return "won", c
        for c in clubs:
            others = [x for x in clubs if x != c]
            per = [self._vs(c, [o]) for o in others]
            if all(p and all(pf < pa for _o, pf, pa in p) for p in per):
                return "lost", c
        return None

    def order(self, clubs: Iterable[str], kind: str = "div") -> list[str]:
        """Order a group of clubs with equal percentages by the procedure (one advances at a time)."""
        rest = sorted(set(clubs))
        out = []
        while rest:
            w = self._pick_one(rest, kind)
            out.append(w)
            rest.remove(w)
        return out

    def rank(self, clubs: Iterable[str], kind: str) -> list[str]:
        """Order clubs by percentage, breaking equal percentages with the procedure."""
        clubs = list(clubs)
        groups: dict[float, list[str]] = defaultdict(list)
        for c in clubs:
            groups[round(self.pct(c), 9)].append(c)
        out = []
        for p in sorted(groups, reverse=True):
            out += self.order(groups[p], kind) if len(groups[p]) > 1 else groups[p]
        return out

    def division_order(self, division: str) -> list[str]:
        if division not in self._div_order:
            members = [t for t, d in self.div.items() if d == division]
            self._div_order[division] = self.rank(members, "div")
        return self._div_order[division]

    def seed_conference(self, conf: str) -> dict:
        """Division winners (seeded by the Wild Card procedure), then Wild Cards; `order` ranks every club
        of the conference (the non-qualifiers by the Wild Card procedure too)."""
        f = canon.formats(self.season)
        divs = sorted({d for t, d in self.div.items() if self.conf[t] == conf})
        winners = [self.division_order(d)[0] for d in divs]
        w_order = self.rank(winners, "wc")
        pool = [t for t in self.teams if self.conf[t] == conf and t not in winners]
        rest = self._wildcard_rank(pool)
        n_wc = f["wild_cards_per_conf"]
        seeds = w_order + rest[:n_wc]
        return {"conf": conf, "division_winners": w_order, "wild_cards": rest[:n_wc], "seeds": seeds,
                "byes": seeds[:f["byes_per_conf"]], "order": w_order + rest}

    def _wildcard_rank(self, pool: list[str]) -> list[str]:
        """Rank non-winners: by percentage, ties by the Wild Card procedure (division rivals by division
        order, since only the highest-ranked of a division can advance at each pick)."""
        return self.rank(pool, "wc")

    def seeds(self) -> dict[str, dict]:
        return {c: self.seed_conference(c) for c in ("AFC", "NFC")}


def table_from_store(store: dict, through_week: int | None = None, tds: dict | None = None, rng=None) -> Table:
    """A Table from a season store's final regular-season games (optionally only through a week)."""
    games = [g for g in store["games"].values() if g.get("gtype") == "REG" and g.get("status") == "final"
             and (through_week is None or (g.get("week") or 0) <= through_week)]
    return Table(games, store["season"], tds=tds, rng=rng)
