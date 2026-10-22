"""The home page shows The Quant Campus like the other sports: a futures tab per level and a live-score adapter."""
import re
from pathlib import Path

from tests.college.test_site_build import _home

ROOT = Path(__file__).resolve().parents[2]
HOME_JS = ROOT / "docs" / "home" / "assets" / "home.js"


def _src():
    return HOME_JS.read_text(encoding="utf-8")


def test_every_college_futures_entry_has_a_home_tab(tmp_path, monkeypatch):
    home, _ = _home(tmp_path, monkeypatch, ["--links", "local"])
    keys = [k for k in home["futures"] if k.split("_")[0] == "college"]
    assert "college" in keys
    tabs = re.search(r"\[\['nfl', 'NFL'\].*?\]\]\.forEach", _src(), re.S).group(0)
    for k in keys:
        assert f"['{k}', " in tabs, k
        f = home["futures"][k]
        assert f["title"] and f["rows"] and all(r["href"].startswith("../campus/#/") for r in f["rows"])
    for k in ("college", "college_mbb", "college_wbb"):
        assert f"['{k}', " in tabs, k


def test_tab_sport_and_live_adapter():
    src = _src()
    # a tab id maps to its sport by the part before "_" (basketball_2 -> basketball, college_mbb -> college)
    assert "futuresPanel(p, F[id], id.split('_')[0])" in src
    m = re.search(r"\n  college: \['index\.json', (function .*?)\],\n", src)
    assert m, "no college live adapter"
    body = m.group(1)
    assert "j.levels" in body and all(k in body for k in ("today", "next_games", "last_games"))
    for f in ("id: g.id", "status: g.status", "hs: g.hs", "as: g.as"):
        assert f in body
    assert "?." not in src and "??" not in src
