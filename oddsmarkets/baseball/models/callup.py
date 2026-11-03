"""
How likely a prospect is to move up next season, and to reach the majors within four seasons.

The inputs are the official season lines already cached for the prospect-value model (Single-A through
Triple-A, plus MLB). A player-season is his highest level that year with at least 100 plate appearances or
batters faced. He moved up when the next season he can be seen (2021, for a 2019 season, because 2020 had
no minor-league season) is a higher level, the majors included. He was called up when an MLB line in the
next four seasons has at least 25 plate appearances or batters faced. Anyone with 130 plate appearances or
100 batters faced in the majors through that season is already a big leaguer and is left out.

A logistic regression on the same features as the prospect-value model. It is published only when it beats
a level-only regression on the sealed seasons 2021 and 2022; otherwise the level-only fit is what the
rankings use. Stat lines only: no scouting grades, so the very best prospects are under-ranked.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from oddsmarkets.baseball.analytics import valuation as VA

RANK = {"a": 0, "hia": 1, "aa": 2, "aaa": 3, "mlb": 4}
MLB_N = 25
ESTABLISHED = {"H": 130.0, "P": 100.0}
RIDGE = 2.0


def logit_fit(X: np.ndarray, y: np.ndarray, ridge: float = RIDGE, iters: int = 40) -> np.ndarray:
    """Ridge logistic regression by Newton steps. The intercept is unpenalised."""
    b = np.zeros(X.shape[1])
    pen = np.ones(X.shape[1])
    pen[0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(X @ b, -20, 20)))
        w = p * (1 - p)
        g = X.T @ (y - p) - ridge * pen * b
        H = X.T @ (X * w[:, None]) + ridge * np.diag(pen)
        step = np.linalg.solve(H, g)
        b += step
        if np.abs(step).max() < 1e-8:
            break
    return b


def prob(coef: np.ndarray, feats: list[float]) -> float:
    c = np.asarray(coef, dtype=float)
    f = np.asarray(feats, dtype=float)[:len(c)]
    z = float(np.clip(f @ c, -20, 20))
    return 1.0 / (1.0 + math.exp(-z))


def _logloss(p: np.ndarray, y: np.ndarray) -> float:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).mean())


def _next(season: int) -> int:
    return season + 2 if season + 1 == 2020 else season + 1


def _mlb_lines(seasons: range) -> dict[int, dict[str, dict]]:
    from oddsmarkets.baseball.analytics import mlbapi
    out = {}
    for s in seasons:
        h, p = mlbapi.season_lines("mlb", s, "hitting"), mlbapi.season_lines("mlb", s, "pitching")
        if h or p:
            out[s] = {"H": h or {}, "P": p or {}}
    return out


def _n(row: dict | None, kind: str) -> float:
    if not row:
        return 0.0
    return float(row.get("pa" if kind == "H" else "bf") or 0)


def _level_of(levels: dict, kind: str, pid: str) -> str | None:
    best, best_n = None, 0.0
    for lv in ("mlb",) + VA.MINORS:
        n = _n((levels.get(lv) or {}).get(kind, {}).get(pid), kind)
        if n > best_n:
            best, best_n = lv, n
    return best


def _cases(lines: dict, mlb: dict, last: int) -> dict[str, list]:
    """{kind: [(season, feats, level, moved_up or None, called_up or None, pid)]}."""
    prows = VA.prospect_rows(lines)
    out: dict[str, list] = {"H": [], "P": []}
    for (s, kind, pid), r in prows.items():
        if s < 2015 or s >= last:
            continue
        played = sum(_n((mlb.get(t) or {}).get(kind, {}).get(pid), kind) for t in mlb if t <= s)
        if played > ESTABLISHED[kind]:
            continue
        feats = [1.0] + VA._pfeats(r)
        up = None
        nxt = _next(s)
        if nxt <= last and (nxt in lines or nxt in mlb):
            there = _level_of({"mlb": mlb.get(nxt) or {}} | {lv: (lines.get(nxt) or {}).get(lv) or {} for lv in VA.MINORS}, kind, pid)
            up = 1.0 if there is not None and RANK[there] > RANK[r["level"]] else 0.0
        called = None
        if s + 4 <= last:
            called = 1.0 if any(_n((mlb.get(s + t) or {}).get(kind, {}).get(pid), kind) >= MLB_N for t in range(1, 5)) else 0.0
        out[kind].append((s, feats, r["level"], up, called, pid, r))
    return out


def _choose(rows: list, idx: int) -> dict:
    """The regression that wins the sealed 2021-2022 seasons against a level-only fit, and that check."""
    labelled = [r for r in rows if r[idx] is not None]
    if len(labelled) < 200:
        return {}
    X = np.array([r[1] for r in labelled], dtype=float)
    y = np.array([r[idx] for r in labelled], dtype=float)
    tr = [i for i, r in enumerate(labelled) if r[0] <= 2019]
    te = [i for i, r in enumerate(labelled) if r[0] in (2021, 2022)]
    full = logit_fit(X[tr], y[tr]) if len(tr) >= 200 else logit_fit(X, y)
    level = logit_fit(X[tr][:, :5], y[tr]) if len(tr) >= 200 else logit_fit(X[:, :5], y)
    check = None
    use = full
    if len(te) >= 50 and len(tr) >= 200:
        pf, pl = _predict(full, X[te]), _predict(level, X[te][:, :5])
        yt = y[te]
        lf, ll = _logloss(pf, yt), _logloss(pl, yt)
        check = {"seasons": [2021, 2022], "n": len(te), "logloss": round(lf, 4), "logloss_level": round(ll, 4),
                 "beats_level": bool(lf < ll)}
        if lf >= ll:
            use = level
    else:
        use = logit_fit(X, y)
    width = use.shape[0]
    return {"coef": [round(float(c), 5) for c in use], "width": int(width), "n": len(labelled),
            "rate": round(float(y.mean()), 4), "validation": check}


def _predict(coef: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(X[:, :len(coef)] @ coef, -20, 20)))


def _warm_lines(last: int) -> None:
    """Fetch any season line the cache does not have yet. A runner that has never seen the minors otherwise
    publishes an empty ranking; a season already on disk is not asked for again."""
    from oddsmarkets.baseball.analytics import mlbapi
    need = []
    for s in range(2015, last + 1):
        for lv in ("mlb",) + VA.MINORS:
            if lv != "mlb" and s == 2020:
                continue
            for group in ("hitting", "pitching"):
                if not mlbapi._lines_path(lv, f"season_{group}_{s}").exists():
                    need.append((lv, s, group))
    if not need:
        return
    c = mlbapi.client(max(200, len(need) + 20))
    if c is None:
        return
    for lv, s, group in need:
        try:
            mlbapi.season_lines(lv, s, group, c)
        except Exception:                                        # noqa: BLE001
            break


def fit(last: int = 2026) -> dict:
    _warm_lines(last)
    seasons = range(2015, last + 1)
    lines, mlb = VA.minor_lines(seasons), _mlb_lines(seasons)
    cases = _cases(lines, mlb, last)
    out = {}
    for kind, rows in cases.items():
        out[kind] = {"up": _choose(rows, 3), "mlb": _choose(rows, 4)}
    return out


def _names(season: int) -> tuple[dict, dict]:
    """Player names and team parents from the season stores, where a fetch has written them."""
    from oddsmarkets.baseball import store as st
    names, parents = {}, {}
    for lv in ("mlb",) + VA.MINORS:
        try:
            s = st.load(lv, season)
        except Exception:                                        # noqa: BLE001
            continue
        for pid, rec in (s.get("players") or {}).items():
            if rec.get("name") and pid not in names:
                names[pid] = rec
        for tid, rec in (s.get("teams") or {}).items():
            parents[str(tid)] = rec.get("parent")
    return names, parents


def board(season: int = 2026) -> dict:
    """The season's prospect rankings: everyone at his highest level with 100+ PA or BF, by P(MLB in four seasons)."""
    from oddsmarkets.baseball import analytics as an
    model = fit(season)
    lines = VA.minor_lines(range(season, season + 1))
    prows = VA.prospect_rows(lines)
    mlb = _mlb_lines(range(2015, season + 1))
    names, parents = _names(season)
    players = []
    for (s, kind, pid), r in prows.items():
        if s != season:
            continue
        played = sum(_n((mlb.get(t) or {}).get(kind, {}).get(pid), kind) for t in mlb if t <= s)
        if played > ESTABLISHED[kind]:
            continue
        feats = [1.0] + VA._pfeats(r)
        line = ((lines.get(s) or {}).get(r["level"]) or {}).get(kind, {}).get(pid) or {}
        team = line.get("team")
        who = names.get(pid) or {}
        up, called = model.get(kind, {}).get("up") or {}, model.get(kind, {}).get("mlb") or {}
        players.append({"pid": pid, "name": who.get("name"), "kind": "hitter" if kind == "H" else "pitcher",
                        "pos": who.get("pos"), "level": r["level"], "team": team,
                        "parent": parents.get(str(team)) if team else None, "age": r.get("age"),
                        "z": round(float(r["z"]), 2), "n": int(r["n"]),
                        "p_up": round(prob(np.array(up["coef"]), feats), 3) if up.get("coef") else None,
                        "p_mlb": round(prob(np.array(called["coef"]), feats), 3) if called.get("coef") else None})
    players.sort(key=lambda x: (-(x["p_mlb"] or 0), -(x["p_up"] or 0), x["name"] or x["pid"]))
    for i, row in enumerate(players):
        row["rank"] = i + 1
    ok = any((model.get(k) or {}).get("mlb", {}).get("coef") for k in ("H", "P"))
    return {"ok": ok, "season": season, "updated_at": an.now(), "players": players, "model": an.clean(model),
            "note": "The chance of a higher level next season, and of 25 plate appearances or batters faced in "
                    "the majors within four seasons. Stat lines only, no scouting grades. A player already established "
                    "in the majors is not listed."}


def main() -> int:
    import json
    import sys
    from pathlib import Path
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    payload = board(season)
    root = Path(__file__).resolve().parents[3]
    dest = root / "docs" / "bullpen" / "data" / "callup.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    v = payload.get("model") or {}
    for kind in ("H", "P"):
        for outcome in ("up", "mlb"):
            c = ((v.get(kind) or {}).get(outcome) or {}).get("validation")
            print(kind, outcome, "n", len(payload["players"]), c)
    print("wrote", dest, "players", len(payload["players"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
