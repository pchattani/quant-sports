"""Bullpen cache keys are path-independent: the same inputs under another root (a CI runner's checkout) or with other
modification times (git checkouts, cache restores) give the same keys, so caches fitted on the PC are reused."""
import os
import shutil
from pathlib import Path

from oddsmarkets.baseball.models import _c, _io


def _tree(root: Path) -> Path:
    raw = root / "data" / "baseball"
    (raw / "statcast" / "mlb").mkdir(parents=True)
    (raw / "statcast" / "mlb" / "2025.parquet").write_bytes(b"pitches" * 1000)
    return raw


def _keys(monkeypatch, root: Path) -> tuple:
    monkeypatch.setenv("BULLPEN_RAW", str(root / "data" / "baseball"))
    monkeypatch.setenv("BULLPEN_CACHE", str(root / "data" / "baseball" / "cache"))
    monkeypatch.setenv("BULLPEN_DATA", str(root / "docs" / "bullpen" / "data"))
    p = _io.pitch_path("mlb", 2025)
    return _io.file_key("v1", p), _c.file_key(p, "v1"), _io.stamp(p), _io.path_sig(p)


def test_keys_ignore_root_and_mtime(tmp_path, monkeypatch):
    a, b = tmp_path / "pc", tmp_path / "runner"
    _tree(a)
    shutil.copytree(a, b)
    f = b / "data" / "baseball" / "statcast" / "mlb" / "2025.parquet"
    os.utime(f, ns=(1_000_000_000, 1_000_000_000))
    ka, kb = _keys(monkeypatch, a), _keys(monkeypatch, b)
    assert ka == kb
    assert ka[3].startswith("raw:statcast/mlb/2025.parquet|")


def test_keys_follow_content(tmp_path, monkeypatch):
    _tree(tmp_path)
    k1 = _keys(monkeypatch, tmp_path)
    f = tmp_path / "data" / "baseball" / "statcast" / "mlb" / "2025.parquet"
    st = f.stat()
    f.write_bytes(b"PITCHES" * 1000)                       # same size, new content
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    k2 = _keys(monkeypatch, tmp_path)
    assert k1[0] != k2[0] and k1[2] != k2[2]


def test_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLPEN_RAW", str(tmp_path))
    monkeypatch.setenv("BULLPEN_CACHE", str(tmp_path / "cache"))
    p = _io.pitch_path("mlb", 1999)
    assert _io.stamp(p) == "0" and _io.path_sig(p).endswith("|missing")
