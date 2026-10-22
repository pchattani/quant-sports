"""Hardwood cache keys are path-independent: the same inputs under another root (a CI runner's checkout) or with other
modification times (git checkouts, cache restores) give the same keys, so caches fitted on the PC are reused (as
Bullpen's, commit 56f25700)."""
import os
import shutil
from pathlib import Path

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import _io


def _tree(root: Path) -> None:
    d = root / "docs" / "hardwood" / "data" / "nba"
    for s, body in ((2025, b'{"games": {}}' * 50), (2026, b'{"games": {"1": {}}}' * 50)):
        (d / str(s)).mkdir(parents=True)
        (d / str(s) / "store.json").write_bytes(body)
    (d / "2026" / "shots.json.gz").write_bytes(b"shots" * 400)


def _keys(monkeypatch, root: Path) -> tuple:
    monkeypatch.setenv("HARDWOOD_DATA", str(root / "docs" / "hardwood" / "data"))
    monkeypatch.setenv("HARDWOOD_CACHE", str(root / "data" / "basketball" / "cache"))
    monkeypatch.setenv("HARDWOOD_PBP", str(root / "data" / "basketball" / "pbp"))
    d = _io.data_root() / "nba"
    return (_io.file_key("v1", d / "2026" / "store.json", d / "2026" / "shots.json"), G.signature("nba", [2025, 2026]),
            _io.path_sig(d / "2025" / "store.json"), _io.stamp(d / "2025" / "store.json"))


def test_keys_ignore_root_and_mtime(tmp_path, monkeypatch):
    a, b = tmp_path / "pc", tmp_path / "runner"
    _tree(a)
    shutil.copytree(a, b)
    for f in (b / "docs" / "hardwood" / "data" / "nba").rglob("*"):
        if f.is_file():
            os.utime(f, ns=(1_000_000_000, 1_000_000_000))
    ka, kb = _keys(monkeypatch, a), _keys(monkeypatch, b)
    assert ka == kb
    assert ka[2].startswith("data:nba/2025/store.json|")
    assert ka[1][0][0] == 2025 and ka[1][0][1] == len(b'{"games": {}}' * 50)


def test_keys_follow_content(tmp_path, monkeypatch):
    _tree(tmp_path)
    k1 = _keys(monkeypatch, tmp_path)
    f = tmp_path / "docs" / "hardwood" / "data" / "nba" / "2026" / "store.json"
    st = f.stat()
    f.write_bytes(b'{"games": {"2": {}}}' * 50)          # same size, new content
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    k2 = _keys(monkeypatch, tmp_path)
    assert k1[0] != k2[0] and k1[1] != k2[1]
    assert k1[2] == k2[2]                                  # the untouched 2025 store keeps its key


def test_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDWOOD_DATA", str(tmp_path))
    monkeypatch.setenv("HARDWOOD_CACHE", str(tmp_path / "cache"))
    p = _io.data_root() / "nba" / "1999" / "store.json"
    assert _io.stamp(p) == "0" and _io.path_sig(p).endswith("|missing")
    assert G.signature("nba", [1999]) == [[1999, None, None]]
