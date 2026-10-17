"""Repository-wide test hooks.

The public build repo (pchattani/quant-sports) is an allowlisted export of this repository
(scripts/export_public.py, docs/HOSTING_MIGRATION.md). Some tests read files that are deliberately not
exported: raw third-party API responses kept out for their terms (docs/HOSTING_MIGRATION.md 2.1, D5), the NPB
package (npb.jp terms, D3), PC-only scripts and the private workflows. In that checkout, which carries the marker
file PUBLIC_SUBSET at its root, a test that fails only because such a file or module is absent is reported as
skipped rather than failed. In this repository there is no marker and the hook does nothing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SUBSET = (ROOT / "PUBLIC_SUBSET").exists()
PRIVATE_MODULES = ("oddsmarkets.baseball.npb", "oddsmarkets.fund", "oddsmarkets.screener")


def _private_absence(exc: BaseException) -> str | None:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ModuleNotFoundError) and (exc.name or "").startswith(PRIVATE_MODULES):
            return f"module {exc.name} is not in the public subset"
        if isinstance(exc, (FileNotFoundError, OSError)):
            fn = getattr(exc, "filename", None) or str(exc)
            try:
                rel = Path(str(fn).split("'")[1] if "'" in str(fn) and not getattr(exc, "filename", None) else fn).resolve().relative_to(ROOT)
            except Exception:
                rel = None
            if rel is not None and not (ROOT / rel).exists():
                return f"{rel.as_posix()} is not in the public subset"
        exc = exc.__cause__ or exc.__context__
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if not PUBLIC_SUBSET or call.excinfo is None:
        return
    rep = outcome.get_result()
    if not rep.failed:
        return
    why = _private_absence(call.excinfo.value)
    if why:
        rep.outcome = "skipped"
        rep.longrepr = (str(item.fspath), item.location[1] or 0, f"Skipped: {why}")
