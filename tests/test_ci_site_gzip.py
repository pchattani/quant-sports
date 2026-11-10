"""scripts/ci_site.py: the Footballer's bulky payload kinds deploy gzipped (GitHub Pages' 1 GB limit), the files other
sites and the next build read stay plain, the compression is deterministic, and FB.load mirrors the rule."""
import gzip
import importlib.util
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_site", ROOT / "scripts" / "ci_site.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

GZ = ["data/people/1000015.json", "data/clubs/42.json", "data/value/club/1043961.json", "data/lab/365/all.json",
      "data/lab/index.json", "data/careers/x.json", "data/premier-league/matches/123.json",
      "data/premier-league/s/17359/table.json", "data/la-liga/players/real-madrid.json"]
PLAIN = ["data/hub.json", "data/competitions.json", "data/clubs_index.json", "data/forecast_log.json",
         "data/season_index.json", "data/people_index.json", "data/premier-league/market_odds.json",
         "data/premier-league/fixtures.json", "data/follow/club/42.json", "data/history/serie-a/s/x.json",
         "index.html", "assets/app/core.js", "data/people/readme.txt"]


def test_rule_picks_the_bulky_kinds_only():
    for r in GZ:
        assert ci.gz_football(PurePosixPath(r)), r
    for r in PLAIN:
        assert not ci.gz_football(PurePosixPath(r)), r
    assert ci.SITES["football"]["gzip"] is ci.gz_football


def test_logs_and_restored_files_are_never_gzipped():
    for pat in ci.LOGS["football"] + ci.SITES["football"]["restore_also"]:
        assert not ci.gz_football(PurePosixPath(pat.replace("*", "premier-league"))), pat


def test_gzip_payloads_round_trips_and_is_deterministic(tmp_path):
    for r in GZ + PLAIN:
        (tmp_path / r).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / r).write_text(json.dumps({"r": r, "name": "Magalhães"}), encoding="utf-8")
    n, b0, b1 = ci.gzip_payloads(tmp_path, ci.gz_football)
    assert n == len(GZ) and b0 > 0 and b1 > 0
    for r in GZ:
        assert not (tmp_path / r).exists()
        assert json.loads(gzip.decompress((tmp_path / (r + ".gz")).read_bytes()))["r"] == r
    for r in PLAIN:
        assert (tmp_path / r).exists() and not (tmp_path / (r + ".gz")).exists()
    first = (tmp_path / (GZ[0] + ".gz")).read_bytes()
    (tmp_path / GZ[0]).write_text(json.dumps({"r": GZ[0], "name": "Magalhães"}), encoding="utf-8")
    ci.gzip_payloads(tmp_path, ci.gz_football)
    assert (tmp_path / (GZ[0] + ".gz")).read_bytes() == first      # unchanged payload -> unchanged bytes, no redeploy


def test_plain_to_gz_counts_as_a_rename_not_a_deletion():
    p = {"added": ["data/people/1.json.gz", "data/people/2.json.gz"],
         "removed": ["data/people/1.json", "data/people/2.json", "data/people/3.json"]}
    assert ci.renamed_to_gz(p) == 2


def test_front_end_mirrors_the_rule():
    js = (ROOT / "docs" / "site" / "assets" / "app" / "core.js").read_text(encoding="utf-8")
    keys = lambda name: set(re.findall(r"(\w+): 1", re.search(name + r" = \{([^}]*)\}", js).group(1)))  # noqa: E731
    assert keys("GZ_TOP") == set(ci.FOOTBALL_GZ_TOP)
    assert keys("GZ_KINDS") == set(ci.FOOTBALL_GZ_KINDS)
    assert "a[0] !== 'follow' && a[0] !== 'history' && a[0] !== 'archive'" in js
    assert "getGz('data/' + p + '.gz')" in js
