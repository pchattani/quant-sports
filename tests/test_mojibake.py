import gzip
import json

from oddsmarkets.common import mojibake as M

GOOD = ["Gabriel Magalhães", "Pedro Gonçalves", "Martin Ødegaard", "Vinícius Júnior", "Kylian Mbappé",
        "Thomas Müller", "Łukasz Fabiański", "Nicolò Barella", "Son Heung-min", "Ståle Solbakken", "Çağlar Söyüncü",
        "Sergio Agüero", "D'Angelo Russell", "Shohei Ohtani", "Ángel Di María", "Žan Celar", "José Ramírez",
        "Aleš Mateju", "Nicolás Machín", "Ásgeir Sigurvinsson", "Ân", "São Paulo", "Ãrbol", "Coup d’état", "Rock ’n’ roll"]


def moji(s: str) -> str:
    return s.encode("utf-8").decode("cp1252", errors="replace")


def test_correct_names_untouched():
    for s in GOOD:
        assert M.fix_text(s) == s, s


def test_mojibake_repaired():
    for s in GOOD:
        m = s.encode("utf-8").decode("latin-1")  # latin-1 keeps every byte, so the round trip is exact
        if m == s:
            continue
        assert M.fix_text(m) == s, (s, m)
    assert M.fix_text("Gabriel MagalhÃ£es") == "Gabriel Magalhães"
    assert M.fix_text("Martin Ã˜degaard") == "Martin Ødegaard"
    assert M.fix_text("NicolÃ¡s MachÃ­n") == "Nicolás Machín"
    assert M.fix_text("Coup dâ€™Ã©tat") == "Coup d’état"


def test_double_encoded_repaired():
    s = "Vinícius Júnior"
    m2 = moji(moji(s))
    assert M.fix_text(m2) == s


def test_repair_walks_keys_and_values():
    obj = {"squad": [{"name": "Gabriel MagalhÃ£es", "pos": "D"}, {"name": "Martin Ødegaard"}],
           "MÃ¼ller": 1, "n": 3}
    fixed, n = M.repair(obj)
    assert n == 2
    assert fixed == {"squad": [{"name": "Gabriel Magalhães", "pos": "D"}, {"name": "Martin Ødegaard"}],
                     "Müller": 1, "n": 3}


def test_check_file_ascii_json_and_gz(tmp_path):
    bad = {"name": "Gabriel MagalhÃ£es", "ok": "Pedro Gonçalves"}
    p = tmp_path / "a.json"
    p.write_text(json.dumps(bad), encoding="utf-8")  # ensure_ascii: "Ã£"
    assert "\\u00c3\\u00a3" in p.read_text(encoding="utf-8")
    assert M.check_file(p) == (1, 0)
    assert M.check_file(p, fix=True) == (1, 0)
    assert json.loads(p.read_text(encoding="utf-8")) == {"name": "Gabriel Magalhães", "ok": "Pedro Gonçalves"}
    assert M.check_file(p) == (0, 0)

    g = tmp_path / "b.json.gz"
    g.write_bytes(gzip.compress(json.dumps(bad, ensure_ascii=False).encode("utf-8")))
    assert M.check_file(g, fix=True) == (1, 0)
    assert json.loads(gzip.decompress(g.read_bytes()).decode("utf-8"))["name"] == "Gabriel Magalhães"


def test_check_file_clean_untouched(tmp_path):
    p = tmp_path / "c.json"
    body = json.dumps({"names": GOOD}, ensure_ascii=False, indent=1)
    p.write_text(body, encoding="utf-8")
    assert M.check_file(p, fix=True) == (0, 0)
    assert p.read_text(encoding="utf-8") == body


def test_ci_site_deploy_gate_repairs(tmp_path):
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("ci_site_moji", root / "scripts" / "ci_site.py")
    ci = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ci)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "club.json").write_text(json.dumps({"squad": [{"name": "Gabriel MagalhÃ£es"}]}),
                                                 encoding="utf-8")
    (tmp_path / "data" / "ok.json").write_text(json.dumps({"n": "Martin Ødegaard"}, ensure_ascii=False),
                                               encoding="utf-8")
    (tmp_path / "index.html").write_text("<p>MagalhÃ£es</p>", encoding="utf-8")
    rels = ["data/club.json", "data/ok.json", "index.html"]
    assert ci.mojibake_gate(tmp_path, rels, fix=False) == (1, 0, ["data/club.json"])
    assert ci.mojibake_gate(tmp_path, rels, fix=True) == (1, 0, ["data/club.json"])
    assert ci.mojibake_gate(tmp_path, rels, fix=False) == (0, 0, [])
    club = json.loads((tmp_path / "data" / "club.json").read_text(encoding="utf-8"))
    assert club["squad"][0]["name"] == "Gabriel Magalhães"


def test_check_file_keeps_layout(tmp_path):
    for kw in ({"separators": (",", ":"), "ensure_ascii": False}, {"indent": 1, "ensure_ascii": False}, {}):
        p = tmp_path / "l.json"
        p.write_text(json.dumps({"a": "Claude Giroux, Tim StÃ¼tzle", "b": [1, 2.5, None]}, **kw), encoding="utf-8")
        assert M.check_file(p, fix=True) == (1, 0)
        assert p.read_text(encoding="utf-8") == json.dumps({"a": "Claude Giroux, Tim Stützle", "b": [1, 2.5, None]},
                                                           **kw)


def test_ci_site_restore_repairs_restored_copies(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("ci_site_moji2", root / "scripts" / "ci_site.py")
    ci = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ci)
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    prev = tmp_path / "prev" / "data" / "wnba" / "2008"
    prev.mkdir(parents=True)
    (prev / "store.json").write_text(json.dumps({"749": {"name": "ChloÃ© Kerr"}}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "docs" / "hardwood" / "data").mkdir(parents=True)
    assert ci.main(["restore", "--site", "hardwood", "--prev", str(tmp_path / "prev")]) == 0
    got = json.loads((tmp_path / "docs" / "hardwood" / "data" / "wnba" / "2008" / "store.json").read_text(encoding="utf-8"))
    assert got["749"]["name"] == "Chloé Kerr"
