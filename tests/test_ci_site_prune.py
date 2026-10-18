"""scripts/ci_site.py prunecaches: superseded Actions caches of one prefix go, the kept key stays, and nothing is
deleted unless the kept key is listed (a save that did not land must not empty the prefix)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_site", ROOT / "scripts" / "ci_site.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def _fake(monkeypatch, rows):
    deleted = []

    def api(method, path, token):
        if method == "GET":
            return 200, {"actions_caches": rows}
        deleted.append(int(path.rsplit("/", 1)[1]))
        return 204, None
    monkeypatch.setattr(ci, "_gh_api", api)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    return deleted


ROWS = [{"id": 1, "key": "rink-raw-v1-aaa", "size_in_bytes": 10}, {"id": 2, "key": "rink-raw-v1-bbb", "size_in_bytes": 10},
        {"id": 3, "key": "rink-raw-v1-ccc", "size_in_bytes": 10}, {"id": 4, "key": "rink-model-v1-x", "size_in_bytes": 10}]


def test_prune_keeps_only_the_kept_key(monkeypatch):
    deleted = _fake(monkeypatch, ROWS)
    assert ci.main(["prunecaches", "--prefix", "rink-raw-v1-", "--keep", "rink-raw-v1-bbb"]) == 0
    assert sorted(deleted) == [1, 3]


def test_prune_does_nothing_when_keep_is_not_listed(monkeypatch):
    deleted = _fake(monkeypatch, ROWS)
    assert ci.main(["prunecaches", "--prefix", "rink-raw-v1-", "--keep", "rink-raw-v1-zzz"]) == 0
    assert deleted == []


def test_prune_needs_keep_inside_prefix_and_a_token(monkeypatch):
    deleted = _fake(monkeypatch, ROWS)
    assert ci.main(["prunecaches", "--prefix", "rink-raw-v1-", "--keep", "rink-model-v1-x"]) == 0
    monkeypatch.delenv("GITHUB_TOKEN")
    assert ci.main(["prunecaches", "--prefix", "rink-raw-v1-", "--keep", "rink-raw-v1-bbb"]) == 0
    assert deleted == []


def test_generated_workflows_prune_after_saving():
    wf = (ROOT / "public_repo" / ".github" / "workflows" / "bullpen.yml").read_text(encoding="utf-8")
    assert "actions: write" in wf
    assert "prunecaches --prefix bullpen-raw-v1-" in wf and "prunecaches --prefix bullpen-model-v1-" in wf
    assert wf.index("Save raw data") < wf.index("Delete superseded raw-data caches")
