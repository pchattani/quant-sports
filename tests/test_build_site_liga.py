"""
End-to-end test of the Liga site build.

The single most important property: the build must produce a complete site from a
committed store with no network access. Sofascore blocks datacenter IPs, so that is
not a fallback path — it is how CI runs every time. If this breaks, the hourly job
takes the site down rather than leaving it stale.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
REQUIRED = [
    "meta.json", "teams.json", "zones.json", "bracket.json",
    "anual.json", "relegation.json", "probs.json", "history.json",
    "market_odds.json",
]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Run the real build against a generated store, in an isolated site directory."""
    work = tmp_path_factory.mktemp("liga-build")
    store = work / "liga_store.json"

    gen = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_liga_sample_store.py"),
         str(store), "--rounds", "4"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert gen.returncode == 0, gen.stderr

    # Point the build at the temporary site directory rather than the repo's.
    env_script = work / "run_build.py"
    env_script.write_text(f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
import scripts.build_site_liga as b
b.SITE_DIR = Path({str(work)!r})
b.DATA_DIR = Path({str(work)!r})
b.STORE_PATH = Path({str(store)!r})
b.HISTORY_STORE = Path({str(work)!r}) / "history_store.json"
sys.argv = ["build", "--sims", "2000", "--no-market"]
raise SystemExit(b.main())
""")
    run = subprocess.run(
        [sys.executable, str(env_script)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    return work, run.stderr


def _load(work: Path, name: str) -> dict:
    return json.loads((work / name).read_text(encoding="utf-8"))


def test_build_succeeds_offline(built) -> None:
    work, _ = built
    for name in REQUIRED:
        assert (work / name).exists(), f"{name} was not emitted"
        assert (work / name).stat().st_size > 0, f"{name} is empty"


def test_synthetic_store_is_labelled(built) -> None:
    """
    A generated store must never be mistaken for real data just because the numbers
    look plausible. The build flags it and the front-end shows a banner.
    """
    work, stderr = built
    assert _load(work, "meta.json")["synthetic"] is True
    assert "SYNTHETIC" in stderr


def test_meta_describes_the_run(built) -> None:
    work, _ = built
    meta = _load(work, "meta.json")
    assert meta["phase"] in {"apertura", "clausura"}
    assert meta["n_sims"] == 2000
    assert meta["games_total"] > meta["games_played"] > 0
    assert meta["training_matches"] > 0
    assert meta["model"]["elo_home_advantage"] > 0
    assert 0.0 < meta["calibration"]["draw_rate"] < 1.0


def test_probabilities_are_internally_consistent(built) -> None:
    """
    The invariants must survive the whole pipeline, not just the simulator: rounding
    to five decimals on the way into JSON is the obvious place for them to drift.
    """
    work, _ = built
    probs = _load(work, "probs.json")["teams"]
    releg = _load(work, "relegation.json")["rows"]

    assert sum(t["p_title"] for t in probs) == pytest.approx(1.0, abs=1e-3)
    assert sum(t["p_libertadores"] for t in probs) == pytest.approx(6.0, abs=1e-3)
    assert sum(r["p_any"] for r in releg) == pytest.approx(2.0, abs=1e-3)
    for t in probs:
        assert 0.0 <= t["p_title"] <= 1.0


def test_zones_have_fifteen_clubs_each(built) -> None:
    work, _ = built
    zones = _load(work, "zones.json")["zones"]
    assert set(zones) == {"A", "B"}
    for key, zone in zones.items():
        assert len(zone["standings"]) == 15, key
        assert zone["total_games"] >= zone["games_played"]
        positions = [r["pos"] for r in zone["standings"]]
        assert positions == list(range(1, 16))


def test_anual_covers_every_club_with_a_full_distribution(built) -> None:
    work, _ = built
    rows = _load(work, "anual.json")["rows"]
    assert len(rows) == 30
    for r in rows:
        assert len(r["p_pos"]) == 30, r["team"]
        assert sum(r["p_pos"]) == pytest.approx(1.0, abs=1e-3), r["team"]


def test_relegation_routes_are_reported_separately(built) -> None:
    work, _ = built
    rows = _load(work, "relegation.json")["rows"]
    assert len(rows) == 30
    for r in rows:
        assert r["p_any"] == pytest.approx(r["p_promedio"] + r["p_anual"], abs=1e-3), r["team"]
        assert r["p05"] <= r["p50"] <= r["p95"], r["team"]
    # Sorted worst promedio first, which is the order the danger is read in.
    promedios = [r["promedio_now"] for r in rows]
    assert promedios == sorted(promedios)


def test_player_payloads_are_emitted(built) -> None:
    work, _ = built
    for name in ("players_live.json", "player_leaders.json", "shots.json", "match_detail.json"):
        assert (work / name).exists(), f"{name} was not emitted"

    live = _load(work, "players_live.json")
    assert live["ok"] is True
    assert live["matches_covered"] > 0
    assert len(live["players"]) > 100

    p = live["players"][0]
    # Per-90 rates are what make a rotation player comparable to an ever-present,
    # and are what the leaderboards sort on.
    for key in ("goals_90", "xg_90", "xa_90", "shots_90", "key_passes_90"):
        assert key in p, key
    for key in ("name", "team", "minutes", "matches", "rating", "is_gk"):
        assert key in p, key


def test_player_identity_is_stable_across_matches(built) -> None:
    """
    One player must aggregate into one row, not one row per appearance.

    Player ids are the only stable identity across matches. An earlier sample store
    generated them per match, which produced thousands of one-appearance players and
    made every per-90 rate meaningless — every player looked like a 90-minute cameo.
    """
    work, _ = built
    players = _load(work, "players_live.json")["players"]

    ids = [p["player_id"] for p in players]
    assert len(ids) == len(set(ids)), "player ids are not unique after aggregation"

    # With a season part-played, plenty of players must have several appearances.
    multi = [p for p in players if p["matches"] > 1]
    assert len(multi) > 50, "no player accumulated more than one appearance"
    for p in multi[:20]:
        assert p["minutes"] > 90, p["name"]


def test_top_scorer_probabilities_sum_to_one(built) -> None:
    """
    The join guard. GoldenBootModel keys output by name, so joining on name alone
    attaches the same probability to every namesake — two players sharing a name at
    different clubs would each claim it in full and the column would sum above 1.
    """
    work, _ = built
    leaders = _load(work, "player_leaders.json")

    total = sum(r["model"] or 0 for r in leaders["live"])
    assert total == pytest.approx(1.0, abs=1e-3), f"probabilities sum to {total}"

    names = [r["name"] for r in leaders["live"]]
    assert len(names) == len(set(names)), "duplicate player names in the leaderboard"

    assert leaders["top_scorer"], "no top-scorer race produced"
    probs = [r["model"] or 0 for r in leaders["top_scorer"]]
    assert probs == sorted(probs, reverse=True), "top scorers are not sorted by probability"


def test_shots_have_pitch_coordinates(built) -> None:
    work, _ = built
    players = _load(work, "shots.json")["players"]
    assert len(players) > 50

    sample = next(iter(players.values()))
    shot = sample["shots"][0]
    for key in ("x", "y", "xg", "type", "body", "time", "match"):
        assert key in shot, key
    # Coordinates must be on the 0-100 pitch the shot map draws.
    assert 0 <= shot["x"] <= 100
    assert 0 <= shot["y"] <= 100


def test_match_detail_supports_single_match_analysis(built) -> None:
    work, _ = built
    matches = _load(work, "match_detail.json")["matches"]
    assert len(matches) > 50

    m = next(iter(matches.values()))
    for key in ("home", "away", "hs", "as", "momentum", "incidents", "shots", "ratings"):
        assert key in m, key
    assert m["momentum"], "no momentum trace"
    assert m["ratings"], "no player ratings"
    # Ratings are shown best-first.
    ratings = [r["rating"] for r in m["ratings"]]
    assert ratings == sorted(ratings, reverse=True)


def test_market_odds_degrade_without_a_key(built) -> None:
    """No ODDS_API_KEY must produce a well-formed ok:false payload, not a crash."""
    work, _ = built
    market = _load(work, "market_odds.json")
    assert market["ok"] is False
    assert market["checked_at"]


def test_history_store_accumulates(built) -> None:
    work, _ = built
    history = _load(work, "history.json")
    assert len(history["snapshots"]) >= 1
    snap = history["snapshots"][-1]
    assert snap["title"] and snap["anual"] and snap["relegation"]


def test_build_fails_loudly_on_an_empty_store(tmp_path) -> None:
    """
    An empty store must be a clear error with an actionable message rather than a
    silently blank site.
    """
    store = tmp_path / "empty.json"
    store.write_text(json.dumps({"matches": {}, "lineups": {}, "meta": {}}), encoding="utf-8")
    script = tmp_path / "run.py"
    script.write_text(f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
import scripts.build_site_liga as b
b.DATA_DIR = Path({str(tmp_path)!r})
b.STORE_PATH = Path({str(store)!r})
sys.argv = ["build", "--no-market"]
raise SystemExit(b.main())
""")
    run = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 1
    assert "empty" in (run.stdout + run.stderr).lower()
