"""
End-to-end test of the combined multi-competition build.

The property that matters: from synthetic stores and no network, the build must
produce a complete site — an index that lists every competition, and for each one
built, the payloads the front-end reads, internally consistent. Sofascore is
unreachable from CI, so this is exactly how the hourly job runs.

The front-end is static and there is no browser here, so the last tests check the
contract between the router (assets/app/*.js) and index.html by inspection: every module loads, every
route has a page, and every tab a manifest can name lands on a competition tab.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SITE = ROOT / "docs" / "site"

LEAGUE_PAYLOADS = [
    "meta.json", "teams.json", "table.json", "probs.json", "strength.json",
    "players_live.json", "player_leaders.json", "shots.json", "matches.json",
    "fixtures.json", "team_stats.json", "history.json", "market_odds.json",
]
SITE_PAYLOADS = ["competitions.json", "hub.json", "search.json"]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Build EPL, MLS and the Argentine sample into an isolated site directory."""
    work = tmp_path_factory.mktemp("site-build")
    data = work / "data"
    for slug, rounds in (("premier-league", 5), ("mls", 8), ("liga-mx", 6), ("belgian-pro-league", 20),
                         ("champions-league", 3), ("libertadores", 4), ("afc-champions-league", 3),
                         ("caf-champions-league", 2), ("concacaf-champions-cup", 1), ("fa-cup", 1), ("world-cup", 2)):
        out = data / slug / "store.json"
        gen = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "make_league_sample_store.py"), slug, str(out),
             "--rounds", str(rounds)],
            capture_output=True, text=True, cwd=ROOT,
        )
        assert gen.returncode == 0, gen.stderr
    liga_store = work / "liga_store.json"
    gen = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_liga_sample_store.py"), str(liga_store), "--rounds", "4"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert gen.returncode == 0, gen.stderr

    runner = work / "run_build.py"
    runner.write_text(f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
import scripts.build_site_all as b
b.SITE_DIR = Path({str(work)!r})
b.DATA_DIR = Path({str(data)!r})
b.LIGA_STORE = Path({str(liga_store)!r})
sys.argv = ["build", "--sims", "2000", "--no-market",
            "--only", "premier-league", "--only", "mls", "--only", "liga-argentina",
            "--only", "liga-mx", "--only", "belgian-pro-league",
            "--only", "champions-league", "--only", "libertadores",
            "--only", "afc-champions-league", "--only", "caf-champions-league", "--only", "concacaf-champions-cup",
            "--only", "fa-cup", "--only", "world-cup"]
raise SystemExit(b.main())
""")
    run = subprocess.run([sys.executable, str(runner)], capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0, run.stdout + run.stderr
    return data, run.stderr


def _load(data: Path, *parts: str) -> dict:
    return json.loads(data.joinpath(*parts).read_text(encoding="utf-8"))


def test_index_lists_every_competition_built(built) -> None:
    data, _ = built
    index = _load(data, "competitions.json")
    by_slug = {c["slug"]: c for c in index["competitions"]}
    assert {"premier-league", "mls", "liga-argentina"} <= set(by_slug)
    for slug in ("premier-league", "mls", "liga-argentina"):
        c = by_slug[slug]
        assert c["ok"], c
        assert c["tabs"] and c["favourite"] and 0.0 < c["p_favourite"] <= 1.0
        assert c["synthetic"] is True
    assert by_slug["premier-league"]["kind"] == "league"
    assert by_slug["mls"]["kind"] == "conference"
    assert by_slug["liga-argentina"]["kind"] == "liga"
    assert "bracket" in by_slug["mls"]["tabs"] and "bracket" not in by_slug["premier-league"]["tabs"]


def test_league_payloads_are_complete_and_consistent(built) -> None:
    data, _ = built
    for name in LEAGUE_PAYLOADS:
        assert (data / "premier-league" / name).exists(), name
    table = _load(data, "premier-league", "table.json")
    rows = table["standings"]
    assert len(rows) == 20
    assert table["total_games"] == 380
    assert table["matches_per_team"] == 38
    for row in rows:
        assert abs(sum(row["p_pos"]) - 1.0) < 1e-3
        assert row["p05"] <= row["p50"] <= row["p95"]
        assert set(row["bands"]) == {b["key"] for b in table["bands"]}
    assert abs(sum(r["p_title"] for r in rows) - 1.0) < 1e-3
    assert abs(sum(r["bands"]["rel"] for r in rows) - 3.0) < 1e-3
    probs = _load(data, "premier-league", "probs.json")
    assert len(probs["teams"]) == 20 and not probs["has_playoff"]


def test_mls_payloads_carry_conferences_and_a_bracket(built) -> None:
    data, _ = built
    table = _load(data, "mls", "table.json")
    assert set(table["conferences"]) == {"Eastern", "Western"}
    assert all(len(rows) == 15 for rows in table["conferences"].values())
    assert len(table["overall"]) == 30
    bracket = _load(data, "mls", "bracket.json")
    assert set(bracket["seeds"]) == {"Eastern", "Western"}
    assert all(len(s) == 9 for s in bracket["seeds"].values())
    assert abs(sum(bracket["p_cup"].values()) - 1.0) < 1e-3
    assert abs(sum(bracket["p_playoffs"].values()) - 18.0) < 1e-3
    probs = _load(data, "mls", "probs.json")
    assert probs["has_playoff"]
    assert all("p_cup" in t and "p_playoffs" in t for t in probs["teams"])


def test_argentina_builds_into_its_own_directory(built) -> None:
    data, _ = built
    for name in ("meta.json", "zones.json", "bracket.json", "anual.json", "relegation.json", "probs.json"):
        assert (data / "liga-argentina" / name).exists(), name
    anual = _load(data, "liga-argentina", "anual.json")
    assert anual["berths"]["note_en"]
    strength = _load(data, "liga-argentina", "strength.json")
    assert set(strength["notes_en"]) == set(strength["notes"])


def test_history_store_accumulates_per_competition(built) -> None:
    data, _ = built
    hist = _load(data, "premier-league", "history_store.json")
    assert len(hist["snapshots"]) == 1
    snap = hist["snapshots"][0]
    assert snap["title"] and snap["relegation"] and snap["band_key"] == "ucl"
    mls = _load(data, "mls", "history_store.json")["snapshots"][0]
    assert mls["shield"] and mls["title"]


def test_missing_store_degrades_to_an_index_entry(tmp_path) -> None:
    runner = tmp_path / "run.py"
    runner.write_text(f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
import scripts.build_site_all as b
b.SITE_DIR = Path({str(tmp_path)!r})
b.DATA_DIR = Path({str(tmp_path / 'data')!r})
b.LIGA_STORE = Path({str(tmp_path / 'missing.json')!r})
sys.argv = ["build", "--sims", "500", "--no-market", "--only", "serie-a", "--only", "liga-argentina"]
raise SystemExit(b.main())
""")
    run = subprocess.run([sys.executable, str(runner)], capture_output=True, text=True, cwd=ROOT)
    # Nothing could be built, so the exit code says so — but the index still exists
    # and names both competitions as unavailable rather than dropping them.
    assert run.returncode == 1
    index = json.loads((tmp_path / "data" / "competitions.json").read_text(encoding="utf-8"))
    by_slug = {c["slug"]: c for c in index["competitions"]}
    assert by_slug["serie-a"]["ok"] is False and by_slug["serie-a"]["reason"]
    assert by_slug["liga-argentina"]["ok"] is False


# ── front-end contract ───────────────────────────────────────────────────────
# The front end (docs/site/index.html + assets/app/*.js on the shared kit in assets/qk/, docs/REDESIGN.md) is a hash
# router: core.js declares the routes, each module registers its pages with FB.route(name, fn), and every older
# route is redirected by core's legacyRedirect(). There is no browser here, so these tests check that contract by
# inspection; scratchpad headless-Chrome runs check the rendering.

APP_DIR = SITE / "assets" / "app"
APP_MODULES = ["core", "charts", "overview", "matches", "competition", "clubs", "players", "value", "fantasy", "lab", "model", "boot"]


def _js() -> str:
    return "\n".join((APP_DIR / f"{m}.js").read_text(encoding="utf-8") for m in APP_MODULES)


def _html() -> str:
    return (SITE / "index.html").read_text(encoding="utf-8")


def test_shell_loads_the_kit_and_every_module_in_order() -> None:
    html = _html()
    scripts = re.findall(r'<script src="assets/([a-z]+)/([a-z-]+)\.js"', html)
    assert scripts[:2] == [("qk", "quant"), ("qk", "quant-charts")], scripts
    assert [m for d, m in scripts if d == "app"] == APP_MODULES
    for d, m in scripts:
        assert (SITE / "assets" / d / f"{m}.js").exists(), (d, m)
    for css in re.findall(r'<link rel="stylesheet" href="(assets/[^"]+)"', html):
        assert (SITE / css).exists(), css
    assert "assets/style.css" not in html and "plotly" not in html.lower()
    assert 'id="app"' in html and 'id="qk-shell"' in html and 'id="disclaimer-template"' in html
    # the older-browser rule shared with the kit
    js = _js()
    assert "?." not in re.sub(r"'[^'\n]*'|\"[^\"\n]*\"|/\*.*?\*/|//[^\n]*", "", js, flags=re.S)
    assert "??" not in js


def test_every_route_has_a_page() -> None:
    js = _js()
    core = (APP_DIR / "core.js").read_text(encoding="utf-8")
    declared = set(re.findall(r"addRoute\('[^']*', '([A-Za-z]+)'", core))
    registered = set(re.findall(r"FB\.route\('([A-Za-z]+)'", js)) | set(re.findall(r"HANDLERS\.([A-Za-z]+) = ", core))
    assert declared and declared <= registered, sorted(declared - registered)
    for section in ("overview", "matches", "competitions", "competition", "clubs", "club", "players", "player",
                    "value", "fantasy", "lab", "compare", "model"):
        assert section in declared, section


def test_every_manifest_tab_lands_on_a_competition_tab() -> None:
    import scripts.build_site_all as b

    core = (APP_DIR / "core.js").read_text(encoding="utf-8")
    block = core[core.index("var COMP_TAB_MAP = {"):]
    block = block[: block.index("};")]
    mapped = dict(re.findall(r"'?([a-z-]+)'?: \['([a-z]+)'", block))
    tabs = set(re.findall(r"'([a-z]+)'", core[core.index("var COMP_TABS = ["):].split("]")[0]))
    for manifest in (b.TABS_LEAGUE, b.TABS_CONFERENCE, b.TABS_PLAYOFF, b.TABS_CUP, b.TABS_KNOCKOUT, b.TABS_FIXED,
                     b.TABS_PRE, b.TABS_INTERNATIONAL, b.TABS_LIGA):
        for tab in manifest:
            if tab == "methodology":       # moved to #/model/methodology?c=<slug>
                continue
            assert tab in mapped, tab
            assert mapped[tab] in tabs, (tab, mapped[tab])
    comp_js = (APP_DIR / "competition.js").read_text(encoding="utf-8")
    for tab in tabs:
        assert f"'{tab}'" in comp_js, tab
    # old routes still land: per-competition tabs, match, club and player pages, and the old global pages
    for old in ("'match'", "'player'", "'team'", "'nations'", "'leaders'", "'transfer'", "'glossary'", "'methodology'", "'disclaimer'"):
        assert old in core, old


def test_script_lists_every_payload_it_reads() -> None:
    """Each payload the build writes for a competition is declared in core's FILES map; the site-wide ones are read."""
    js = _js()
    declared = set(re.findall(r"([a-z_]+\.json)'", js))
    for name in LEAGUE_PAYLOADS:
        assert name in declared, name
    for name in ("zones.json", "bracket.json", "anual.json", "relegation.json", "seasons.json", "sensitivity.json",
                 "competitions.json", "hub.json", "crests.json", "clubs_index.json", "people_index.json",
                 "pool.json", "nations.json", "glossary.json"):
        assert name in declared, name
    for prefix in ("'people/'", "'clubs/'", "'value/", "'fantasy/"):
        assert prefix in js, prefix


# ── tuned model parameters ───────────────────────────────────────────────────

def test_model_params_fall_back_to_defaults_and_read_tuned_entries(tmp_path, monkeypatch) -> None:
    import scripts.build_site_all as b

    monkeypatch.setattr(b, "MODEL_PARAMS_PATH", tmp_path / "missing.json")
    params, method = b.model_params_for("premier-league")
    assert method == "default" and params == b.DEFAULT_PARAMS

    tuned = tmp_path / "model_params.json"
    tuned.write_text(json.dumps({"leagues": {
        "premier-league": {"method": "per-league", "params": {"xi": 0.008, "dc_weight": 1.0}},
    }}), encoding="utf-8")
    monkeypatch.setattr(b, "MODEL_PARAMS_PATH", tuned)
    params, method = b.model_params_for("premier-league")
    assert method == "per-league"
    assert params["xi"] == 0.008 and params["dc_weight"] == 1.0
    # Keys the tuned entry omits keep their defaults.
    assert params["ridge"] == b.DEFAULT_PARAMS["ridge"]
    assert b.model_params_for("mls")[1] == "default"


def test_committed_model_params_cover_every_league() -> None:
    import scripts.build_site_all as b
    from oddsmarkets.football.competitions.league.config import LEAGUES

    if not b.MODEL_PARAMS_PATH.exists():
        pytest.skip("no model_params.json yet")
    payload = json.loads(b.MODEL_PARAMS_PATH.read_text(encoding="utf-8"))
    for slug in LEAGUES:
        entry = payload["leagues"].get(slug)
        assert entry, slug
        assert entry["method"] in {"global", "per-league", "pooled", "default"}
        assert set(entry["params"]) >= {"xi", "ridge", "elo_home_advantage", "k_league", "dc_weight"}
        # A tuned set must have beaten the home-advantage prior, or be the default.
        if entry["method"] != "default":
            assert entry["log_loss"] < entry["baseline_log_loss"], slug


def test_league_view_of_a_pooled_fit_matches_a_prefixed_prediction() -> None:
    """A league's view re-keys attack/defence to plain names and predicts identically."""
    import numpy as np
    import pandas as pd
    import scripts.build_site_all as b
    from oddsmarkets.football.core import DixonColesModel

    rng = np.random.default_rng(1)
    rows = []
    for i in range(400):
        h, a = rng.choice(["x:A", "x:B", "x:C", "y:D", "y:E", "y:F"], 2, replace=False)
        if h[0] != a[0]:
            continue
        rows.append({"game_id": str(i), "home_team": h, "away_team": a,
                     "home_goals": int(rng.poisson(1.4)), "away_goals": int(rng.poisson(1.1)),
                     "match_date": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=i), "weight": 1.0})
    dc = DixonColesModel(xi=0.002, ridge=1.0)
    dc.fit(pd.DataFrame(rows))

    view = b.LeagueView(dc, "x")
    assert view.is_fitted
    assert {k for k in view.params_ if k.startswith("attack_")} == {"attack_A", "attack_B", "attack_C"}
    assert "rho" in view.params_ and "home_adv" in view.params_
    assert view.params_["attack_A"] == dc.params_["attack_x:A"]
    direct = dc.predict_match("x:A", "x:B", neutral=False)
    via = view.predict_match("A", "B", neutral=False)
    assert via.home_win == pytest.approx(direct.home_win)
    # Nothing from the other league leaks into the view.
    assert not any(k.endswith((":D", ":E", ":F")) or k in ("attack_D", "attack_E") for k in view.params_)


# ── the new formats ──────────────────────────────────────────────────────────

def test_liguilla_and_split_payloads(built) -> None:
    data, _ = built
    idx = {c["slug"]: c for c in _load(data, "competitions.json")["competitions"]}
    assert idx["liga-mx"]["ok"] and idx["liga-mx"]["kind"] == "playoff" and "bracket" in idx["liga-mx"]["tabs"]
    br = _load(data, "liga-mx", "bracket.json")
    assert br["kind"] == "liguilla" and br["rounds"] == ["play_in", "qf", "sf", "final"]
    assert abs(sum(br["p_cup"].values()) - 1.0) < 1e-3
    assert abs(sum(br["p_playoffs"].values()) - 10.0) < 1e-3
    assert idx["belgian-pro-league"]["ok"] and idx["belgian-pro-league"]["kind"] == "league"
    tb = _load(data, "belgian-pro-league", "table.json")
    assert tb["split"]["top"] == 6
    assert all(len(r["p_final_pos"]) == 18 for r in tb["standings"])
    assert abs(sum(r["p_top_group"] for r in tb["standings"]) - 6.0) < 1e-3


def test_cup_payloads(built) -> None:
    data, _ = built
    idx = {c["slug"]: c for c in _load(data, "competitions.json")["competitions"]}
    for slug in ("champions-league", "libertadores"):
        assert idx[slug]["ok"] and idx[slug]["kind"] == "cup", slug
        br = _load(data, slug, "bracket.json")
        assert abs(sum(br["p_cup"].values()) - 1.0) < 1e-3
        for name in ("table.json", "probs.json", "strength.json", "players_live.json", "meta.json", "history.json"):
            assert (data / slug / name).exists(), (slug, name)
    ucl = _load(data, "champions-league", "table.json")
    assert len(ucl["standings"]) == 36
    assert abs(sum(r["bands"]["r16"] for r in ucl["standings"]) - 8.0) < 1e-3
    lib = _load(data, "libertadores", "table.json")
    assert len(lib["conferences"]) == 8 and all(len(rows) == 4 for rows in lib["conferences"].values())
    assert _load(data, "champions-league", "meta.json")["model"]["params_method"] == "pooled"


# ── analytics payloads and the hub ───────────────────────────────────────────

def test_fixtures_carry_the_model_line_and_results_carry_xg(built) -> None:
    data, _ = built
    fx = _load(data, "premier-league", "fixtures.json")["matches"]
    assert len(fx) == 380
    played = [f for f in fx if f["status"] == "finished"]
    upcoming = [f for f in fx if f["status"] == "scheduled"]
    assert played and upcoming
    assert all(f["detail"] and f["xg"] and len(f["xg"]) == 2 for f in played)
    for f in upcoming:
        m = f["model"]
        assert abs(m["h"] + m["d"] + m["a"] - 1.0) < 1e-3
        assert m["lh"] > 0 and m["la"] > 0 and 0 < m["o25"] < 1 and 0 < m["btts"] < 1
        assert re.fullmatch(r"\d-\d", m["score"]) and len(m["fair"]) == 3
        assert abs(m["fair"][0] - 1 / m["h"]) < 0.02
    # Kickoff order.
    assert [f["date"] for f in fx] == sorted(f["date"] for f in fx)


def test_players_have_positions_percentiles_and_the_catalogue(built) -> None:
    data, _ = built
    live = _load(data, "premier-league", "players_live.json")
    assert live["metrics"] and live["minutes_floor"] > 0 and live["positions"]["G"] == "Goalkeeper"
    players = live["players"]
    assert players
    keys = {m["key"] for m in live["metrics"]}
    assert {"npxg_90", "pass_pct", "tackles_90", "save_pct", "rating"} <= keys
    qualified = [p for p in players if p.get("qualified")]
    assert qualified
    for p in qualified:
        assert p["position"] in ("G", "D", "M", "F")
        assert p["pool"]["key"] == p["position"] and p["pool"]["n"] >= 3
        assert p["pct"] and all(0 <= v <= 100 for v in p["pct"].values())
        if p["is_gk"]:
            assert "save_pct" in p["pct"] and "npxg_90" not in p["pct"]
        else:
            assert "npxg_90" in p["pct"] and "save_pct" not in p["pct"]
        assert "age" in p and "starts" in p
    # No nulls are written: absent means unknown.
    assert all(v is not None for p in players for v in p.values())


def test_player_shards_and_match_pages(built) -> None:
    data, _ = built
    live = _load(data, "premier-league", "players_live.json")
    p = max(live["players"], key=lambda x: x["minutes"])
    shard = _load(data, "premier-league", "players", "".join(ch if ch.isalnum() else "-" for ch in p["team"].lower()).strip("-") + ".json")
    entry = shard["players"][p["player_id"]]
    assert entry["team"] == p["team"] and len(entry["matches"]) == p["matches"]
    row = entry["matches"][0]
    assert row["gid"] and row["opp"] and row["ha"] in ("H", "A") and row["res"] in ("W", "D", "L")
    assert "min" in row and "rt" in row
    assert [m["date"] for m in entry["matches"]] == sorted((m["date"] for m in entry["matches"]), reverse=True)

    index = _load(data, "premier-league", "matches.json")
    assert index["with_detail"] == len(index["matches"]) > 0
    first = index["matches"][0]
    page = _load(data, "premier-league", "matches", first["id"] + ".json")
    assert page["home"] == first["home"] and page["team_stats"]["home"]["expectedGoals"] is not None
    assert page["lineups"]["home"] and page["lineups"]["home"][0]["start"] is True
    assert page["lineups"]["home"][0]["pos"] == "G"          # goalkeeper listed first
    assert all("is_home" in i for i in page["incidents"])
    assert page["formation"]["home"]


def test_team_stats_have_season_means_and_percentiles(built) -> None:
    data, _ = built
    ts = _load(data, "premier-league", "team_stats.json")
    assert ts["metrics"] and len(ts["teams"]) == 20
    for team, block in ts["teams"].items():
        season = block["season"]
        assert season["matches"] == len(block["matches"]) > 0
        assert season["xg"] is not None and season["xga"] is not None and season["poss"] is not None
        assert 0 <= season["pct"]["xg"] <= 100
        assert block["matches"][0]["opp"] and block["matches"][0]["res"] in ("W", "D", "L")


ANALYTICS_KEYS = {"updated_at", "minutes_floor", "season", "rounds", "season_xi", "performers", "teams", "team_metrics", "player_metrics"}


def test_analytics_payloads_for_a_league_and_a_cup(built) -> None:
    """analytics.json: rounds newest first with a team of the week, season XIs, performers and team profiles."""
    data, _ = built
    idx = {c["slug"]: c for c in _load(data, "competitions.json")["competitions"]}
    for slug in ("premier-league", "champions-league", "mls", "fa-cup", "world-cup", "liga-argentina"):
        assert "analytics" in idx[slug]["tabs"], slug
        a = _load(data, slug, "analytics.json")
        assert set(a) == ANALYTICS_KEYS, slug
        assert a["team_metrics"] and a["player_metrics"] and a["minutes_floor"] >= 0
    a = _load(data, "premier-league", "analytics.json")
    assert a["season"] and len(a["rounds"]) == 5
    dates = [r["dates"][1] for r in a["rounds"]]
    assert dates == sorted(dates, reverse=True) and a["rounds"][0]["label"] == "Round 5"
    totw = a["rounds"][0]["team_of_week"]
    assert totw["formation"] in {"4-3-3", "4-4-2", "3-5-2", "3-4-3", "5-3-2", "5-4-1", "4-5-1", "3-6-1"} and len(totw["xi"]) == 11
    assert totw["xi"][0]["pos"] == "G" and all(p["min"] >= 45 and p["gid"] for p in totw["xi"])
    assert a["rounds"][0]["player_of_week"]["why"] and a["rounds"][0]["player_of_week"]["min"] >= 60
    assert {"finisher", "wall", "engine", "ball_winner"} <= set(a["rounds"][0]["awards"])
    assert {"best_xg_diff", "luckiest", "unluckiest"} <= set(a["rounds"][0]["team_awards"])
    for key in ("rating", "output", "defence", "form"):
        assert len(a["season_xi"][key]["xi"]) == 11 and a["season_xi"][key]["formation"], key
    perf = a["performers"]
    assert set(perf["players"]) == set(a["player_metrics"]) and len(perf["players"]["rating"]["top"]) == 8
    assert perf["players"]["goals_prevented_90"]["scope"] == "gk" and all(p["pos"] == "G" for p in perf["players"]["goals_prevented_90"]["top"])
    assert len(perf["teams"]["xg_diff"]["ranking"]) == 20 and perf["teams"]["xg_diff"]["ranking"][0]["pct"] == 100
    assert len(a["teams"]) == 20
    team = next(iter(a["teams"].values()))
    assert team["played"] == 5 and len(team["form"]) == 5 and len(team["rounds"]) == 5
    # The sample sheets carry no big chances, crosses or dribbles: a metric without a value is absent, never null.
    assert set(team["profile"]) <= {m["key"] for m in a["team_metrics"]}
    assert {"xg_for", "xg_against", "xg_diff", "xpts_per_match", "luck", "possession", "field_tilt", "ppda", "pass_pct", "km"} <= set(team["profile"])
    assert all(0 <= v["pct"] <= 100 for v in team["profile"].values())
    # A cup labels its knockout rounds.
    ucl = _load(data, "champions-league", "analytics.json")
    assert ucl["rounds"] and all(r["label"] for r in ucl["rounds"])


def test_site_wide_payloads(built) -> None:
    data, _ = built
    for name in SITE_PAYLOADS:
        assert (data / name).exists(), name
    glossary = _load(data, "glossary.json")
    assert glossary["groups"] and glossary["model"] and glossary["updated_at"]
    assert any(grp["name"] == "Team metrics" for grp in glossary["groups"])
    hub = _load(data, "hub.json")
    assert hub["window"] and hub["leaders"]["goals"] and hub["leaders"]["rating"]
    # Every competition contributes its latest results and next fixtures even
    # when nothing falls in the window.
    comps_recent = {i["comp"] for i in hub["recent"]} | {i["comp"] for d in hub["days"].values() for i in d}
    assert "premier-league" in comps_recent
    assert any(i["comp"] == "premier-league" and i["model"] for i in hub["upcoming"] + [x for d in hub["days"].values() for x in d])
    search = _load(data, "search.json")
    assert any(t["comp"] == "mls" for t in search["teams"])
    assert search["players"] and all({"id", "n", "t", "comp"} <= set(p) for p in search["players"])
    idx = {c["slug"]: c for c in _load(data, "competitions.json")["competitions"]}
    epl = idx["premier-league"]
    assert epl["leader"]["team"] and epl["top_scorer"]["goals"] >= 1 and epl["next"]["home"] and epl["last"]["hs"] is not None
    assert not any(k.startswith("_") for k in epl)


def test_the_layer_above_the_competitions(built) -> None:
    """The pooled scale and the global player table, offline; no Ballon d'Or payload any more."""
    data, _ = built
    pool = _load(data, "pool.json")
    assert pool["model"] and pool["clubs"] and pool["leagues"]
    ranks = [c["rank"] for c in pool["clubs"]]
    assert ranks == list(range(1, len(ranks) + 1))
    assert all(0 < c["strength"] < 3 and c["block"] for c in pool["clubs"])
    epl = pool["leagues"]["premier-league"]
    assert epl["n_clubs"] == 20 and epl["factor_att"] > 0 and epl["block"] == "Europe" and "connection" in epl
    assert isinstance(pool["bridges"], dict)

    g = _load(data, "players_global.json")
    assert g["players"] and g["metrics"] and g["minutes_floor"] > 0
    row = next(p for p in g["players"] if p["comp"] == "premier-league" and not p.get("is_gk") and p.get("npxg_90") is not None)
    assert row["npxg_90_adj"] == pytest.approx(row["npxg_90"] * row["adj_factor"], abs=1e-3)
    assert row["adj_factor"] == pytest.approx(epl["factor_att"], abs=1e-3)
    qualified = [p for p in g["players"] if p.get("qualified")]
    assert qualified and all(p["pct_global"] and p["pool_global"]["key"] for p in qualified)

    assert not (data / "ballon-dor").exists()

    # The unified registries: one row per person and per club, every built competition with its seasons.
    people = _load(data, "people_index.json")
    ids = [r[0] for r in people["rows"]]
    assert ids and len(ids) == len(set(ids)) and people["fields"][0] == "id"
    one = _load(data, "people", f"{ids[0]}.json")
    assert one["apps"] and all(len(a) == len(one["apps_fields"]) for a in one["apps"])
    assert {s["scope"] for s in one["seasons"]} <= {"club", "international"}
    clubs = _load(data, "clubs_index.json")
    tids = [r[0] for r in clubs["rows"]]
    assert tids and len(tids) == len(set(tids))
    idx = {c["slug"]: c for c in _load(data, "competitions.json")["competitions"]}
    for slug, c in idx.items():
        if c.get("ok"):
            assert c["current_season"]["sid"] is not None and c["seasons"][0]["source"] == "live", slug
            assert c["kind_u"] in ("league", "domestic_cup", "super_cup", "continental_club", "international")
    man = _load(data, "premier-league", "seasons.json")
    assert man["seasons"][0]["sid"] == man["current"]
    assert idx["liga-argentina"]["current_season"]["sid"].endswith(("apertura", "clausura"))
    assert (data / "careers" / "index.json").exists()


def test_value_layer_and_sensitivity_curves(built) -> None:
    """The player value payloads and every simulated league's sensitivity curves, offline."""
    data, _ = built
    meta = _load(data, "value", "meta.json")
    assert meta["model"]["weights"] and meta["components"][-1] == "League" and meta["replacement"]["CB"] is not None
    players = _load(data, "value", "players.json")
    lines = _load(data, "value", "lines.json")
    assert players["fields"][0] == "id" and players["rows"] and lines["rows"]
    assert {r[1] for r in lines["rows"]} >= {"premier-league", "mls"}
    clubs = list((data / "value" / "club").glob("*.json"))
    assert clubs
    one = json.loads(clubs[0].read_text(encoding="utf-8"))
    assert len(one["units"]) == 6 and len(one["strengths"]) == 3 and set(one["targets"]) == set(one["weaknesses"])
    for slug in ("premier-league", "mls", "liga-mx", "belgian-pro-league"):
        sens = _load(data, slug, "sensitivity.json")
        assert sens["shifts"][2] == 0.0 and sens["teams"], slug
        team = next(iter(sens["teams"].values()))
        assert team["exp_pts"][0] < team["exp_pts"][-1] and team["gd_per_delta"] > 0
    assert _load(data, "premier-league", "sensitivity.json")["metrics"][:2] == ["exp_pts", "p_title"]
    assert "p_cup" in _load(data, "mls", "sensitivity.json")["metrics"]
    # Valuation v2, the transfers layer (no transfer store offline: an empty feed, no fee model) and the fantasy layer.
    assert players["fields"][-7:] == ["v2", "v2lo", "v2hi", "avail", "fee", "feelo", "feehi"]
    assert meta["fee"]["fitted"] is False and "budgets" in meta and "coverage" in meta["transfers"]
    assert {"budget", "ledger"} <= set(one)
    feed = _load(data, "value", "transfers.json")
    assert feed["fields"][0] == "key" and feed["rows"] == [] and feed["fee_fitted"] is False
    fmeta = _load(data, "fantasy", "meta.json")
    assert fmeta["leagues"] and fmeta["scoring"]["goal"]["D"] == 6.0
    league = _load(data, "fantasy", fmeta["leagues"][0]["slug"] + ".json")
    assert league["rows"] and league["fields"][:3] == ["id", "name", "pos"] and league["gameweeks"]
    assert league["squad"] and len(league["squad"].get("xi") or league["squad"].get("squad") or []) >= 11


# ── the AFC, CAF and CONCACAF shapes ─────────────────────────────────────────

def test_regional_swiss_groups_and_knockout_cups(built) -> None:
    data, _ = built
    idx = {c["slug"]: c for c in _load(data, "competitions.json")["competitions"]}
    afc = idx["afc-champions-league"]
    assert afc["ok"] and afc["cup_kind"] == "regional_swiss" and "table" in afc["tabs"]
    tb = _load(data, "afc-champions-league", "table.json")
    assert set(tb["conferences"]) == {"East", "West"} and tb["group_label"] == "Region"
    assert all(len(rows) == 16 for rows in tb["conferences"].values())
    for rows in tb["conferences"].values():
        assert abs(sum(r["bands"]["r16"] for r in rows) - 8.0) < 1e-3
        assert all(len(r["p_pos"]) == 16 for r in rows)
    br = _load(data, "afc-champions-league", "bracket.json")
    assert br["rounds"] == ["r16", "qf", "sf", "final"]
    assert abs(sum(br["p_cup"].values()) - 1.0) < 1e-3
    assert abs(sum(v["r16"] for v in br["reach"].values()) - 16.0) < 1e-3
    assert abs(sum(v["qf"] for v in br["reach"].values()) - 8.0) < 1e-3

    caf = idx["caf-champions-league"]
    assert caf["ok"] and caf["cup_kind"] == "groups"
    tb = _load(data, "caf-champions-league", "table.json")
    assert len(tb["conferences"]) == 4 and all(len(rows) == 4 for rows in tb["conferences"].values())
    br = _load(data, "caf-champions-league", "bracket.json")
    assert br["rounds"] == ["qf", "sf", "final"]
    assert abs(sum(br["p_cup"].values()) - 1.0) < 1e-3
    assert abs(sum(v["qf"] for v in br["reach"].values()) - 8.0) < 1e-3

    ccc = idx["concacaf-champions-cup"]
    assert ccc["ok"] and ccc["cup_kind"] == "knockout" and "table" not in ccc["tabs"] and "bracket" in ccc["tabs"]
    br = _load(data, "concacaf-champions-cup", "bracket.json")
    assert set(br["known"]) == {"r16", "qf"} and len(br["known"]["r16"]) == 8 and len(br["known"]["qf"]) == 4
    assert len(br["forced"]) == 8                       # every Round-of-16 tie was played
    assert abs(sum(br["p_cup"].values()) - 1.0) < 1e-3
    assert abs(sum(v["qf"] for v in br["reach"].values()) - 8.0) < 1e-3
    assert abs(sum(v["sf"] for v in br["reach"].values()) - 4.0) < 1e-3
    fx = _load(data, "concacaf-champions-cup", "fixtures.json")["matches"]
    assert any(f["status"] == "scheduled" and f["model"] for f in fx)


def test_national_cup_and_national_team_competition(built) -> None:
    """A domestic cup simulates as a knockout; a national-team tournament builds unsimulated with the international fit's line."""
    data, _ = built
    idx = {c["slug"]: c for c in _load(data, "competitions.json")["competitions"]}
    fa = idx["fa-cup"]
    assert fa["ok"] and fa["family"] == "domestic" and fa["cup_kind"] == "knockout" and "bracket" in fa["tabs"]
    br = _load(data, "fa-cup", "bracket.json")
    assert abs(sum(br["p_cup"].values()) - 1.0) < 1e-3
    wc = idx["world-cup"]
    assert wc["ok"] and wc["family"] == "international" and wc["unsimulated"] and "probs" not in wc["tabs"] and "table" in wc["tabs"]
    table = _load(data, "world-cup", "table.json")
    assert table["unsimulated"] and len(table["conferences"]) == 8 and all(len(r) == 4 for r in table["conferences"].values())
    assert all(row["p_title"] is None for rows in table["conferences"].values() for row in rows)
    meta = _load(data, "world-cup", "meta.json")
    assert meta["unsimulated"] and meta["n_sims"] == 0 and meta["model"]["dc_fitted"]
    fx = _load(data, "world-cup", "fixtures.json")["matches"]
    upcoming = [f for f in fx if f["status"] == "scheduled"]
    assert upcoming and all(f.get("model") for f in upcoming)      # the international fit prices them
    nations = _load(data, "nations.json")
    assert nations["teams"] and nations["model"]["rho"] is not None
    assert [t["rank"] for t in nations["teams"]] == list(range(1, len(nations["teams"]) + 1))
    idx_players = _load(data, "season_index.json")["players"]
    assert idx_players and all(r["rows"] for r in idx_players.values())
    cm = _load(data, "premier-league", "club_matches.json")["clubs"]
    assert cm and all(all(m["comp"] for m in ms) for ms in cm.values())
    hub = _load(data, "hub.json")
    assert any(i.get("family") == "international" for d in [hub["recent"], hub["upcoming"]] + list(hub["days"].values()) for i in d)


def test_cup_before_its_main_phase_builds_fixtures_only(tmp_path) -> None:
    """A cup whose store holds only qualifying matches is listed, with fixtures and no simulation."""
    store = {"matches": {}, "lineups": {}, "shots": {}, "momentum": {}, "incidents": {}, "meta": {"season_id": 5, "season_name": "CAF sample"}}
    for i in range(6):
        store["matches"][str(100 + i)] = {"home": f"Club {i}", "away": f"Club {i + 6}", "round": 1, "status": "finished", "hs": 1, "as": 0,
                                          "date": f"2026-09-{10 + i:02d}T15:00:00Z", "stage": "qualifying", "season_id": 5}
    store["matches"]["200"] = {"home": "Club 0", "away": "Club 6", "round": 2, "status": "notstarted", "hs": None, "as": None,
                               "date": "2026-10-20T15:00:00Z", "stage": "qualifying", "season_id": 5}
    out = tmp_path / "data" / "caf-champions-league"
    out.mkdir(parents=True)
    out.joinpath("store.json").write_text(json.dumps(store), encoding="utf-8")
    runner = tmp_path / "run.py"
    runner.write_text(f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
import scripts.build_site_all as b
b.SITE_DIR = Path({str(tmp_path)!r})
b.DATA_DIR = Path({str(tmp_path / 'data')!r})
b.LIGA_STORE = Path({str(tmp_path / 'missing.json')!r})
sys.argv = ["build", "--sims", "500", "--no-market", "--skip-liga", "--only", "caf-champions-league"]
raise SystemExit(b.main())
""")
    run = subprocess.run([sys.executable, str(runner)], capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0, run.stdout + run.stderr
    idx = {c["slug"]: c for c in json.loads((tmp_path / "data" / "competitions.json").read_text(encoding="utf-8"))["competitions"]}
    c = idx["caf-champions-league"]
    assert c["ok"] and c["phase"] == "pre" and c["tabs"] == ["overview", "fixtures", "matches", "methodology"]
    fx = json.loads((out / "fixtures.json").read_text(encoding="utf-8"))["matches"]
    assert len(fx) == 7 and sum(1 for f in fx if f["status"] == "finished") == 6
    assert c["games_played"] == 6 and c["favourite"] is None
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["phase"] == "pre" and "November" in meta["phase_note"]
