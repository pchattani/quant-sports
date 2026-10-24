"""Club kit colours derived from crests (oddsmarkets/football/analytics/colours.py), on synthetic images."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from oddsmarkets.football.analytics import colours as C

Image = pytest.importorskip("PIL.Image")


def _crest(path: Path, fill, inner=None, size=64) -> Path:
    """A shield of `fill` on a transparent square with a white ring; `inner` a stripe across the middle."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for x in range(size):
        for y in range(size):
            r = ((x - size / 2) ** 2 + (y - size / 2) ** 2) ** 0.5
            if r < size * 0.45:
                im.putpixel((x, y), (255, 255, 255, 255) if r > size * 0.4 else fill + (255,))
            if inner and r < size * 0.4 and abs(y - size / 2) < size * 0.12:
                im.putpixel((x, y), inner + (255,))
    im.save(path)
    return path


def test_main_colour_and_a_second_hue(tmp_path) -> None:
    colour, alt = C.derive(_crest(tmp_path / "1.png", (200, 16, 46), inner=(0, 40, 120)))
    assert colour == "#c8102e" and alt == "#002878"


def test_white_is_the_second_colour_only_when_nothing_else_is(tmp_path) -> None:
    colour, alt = C.derive(_crest(tmp_path / "2.png", (0, 90, 40)))
    assert colour == "#005a28" and alt in (None, "#ffffff")


def test_a_grey_crest_gives_no_colour(tmp_path) -> None:
    assert C.derive(_crest(tmp_path / "3.png", (150, 150, 150))) == (None, None)


def test_refresh_writes_the_crest_layer(tmp_path) -> None:
    crests = tmp_path / "crests"
    crests.mkdir()
    _crest(crests / "42.png", (200, 16, 46), inner=(0, 40, 120))
    _crest(crests / "7.png", (150, 150, 150))
    table = tmp_path / "crest_colours.json"
    rows = C.refresh(crests, table)
    assert list(rows) == ["42"] and json.loads(table.read_text(encoding="utf-8")) == {"42": ["#c8102e", "#002878"]}


def test_precedence_sofascore_then_override_then_crest(tmp_path) -> None:
    """Sofascore's teamColors win, a hand-checked override beats the crest, the crest fills the rest; Sofascore's
    placeholder blue counts as unknown; the source is recorded per club."""
    sofa, crest, table = tmp_path / "s.json", tmp_path / "c.json", tmp_path / "t.json"
    sofa.write_text(json.dumps({"1": ["#A50044", "#004D98", "#ffffff"], "2": ["#374df5", "#374df5", "#ffffff"],
                                "3": ["#ffffff", "#ffffff", "#000000"]}), encoding="utf-8")
    crest.write_text(json.dumps({"1": ["#e6bc05", None], "2": ["#e6bc05", "#d4182c"], "4": ["#123456", None],
                                 "5": ["#654321", None]}), encoding="utf-8")
    rows = C.rebuild(table, sofa, crest, overrides={"2": ("#004d98", "#a50044"), "5": ("#ff0000", None)})
    assert rows == {"1": ["#a50044", "#004d98", "sofascore"], "2": ["#004d98", "#a50044", "override"],
                    "3": ["#ffffff", "#000000", "sofascore"], "4": ["#123456", None, "crest"],
                    "5": ["#ff0000", None, "override"]}
    assert C.club(1, table) == {"colour": "#a50044", "alt": "#004d98"} and C.club(4, table) == {"colour": "#123456"}
    assert C.club(9, table) == {}


def test_keep_sofascore_folds_new_answers_in(tmp_path) -> None:
    sofa = tmp_path / "s.json"
    assert C.keep_sofascore({"7": ["#FF0000", "#fff", "#000000"]}, sofa) == 1
    assert C.keep_sofascore({"7": ["#ff0000", "#ffffff", "#000000"], "x": ["#000000", None, None]}, sofa) == 0
    assert C.keep_sofascore({"7": ["#00ff00", None, None], "8": ["#0000ff", "#ffffff", "#ffffff"]}, sofa) == 2
    assert json.loads(sofa.read_text(encoding="utf-8")) == {"7": ["#00ff00", None, None],
                                                           "8": ["#0000ff", "#ffffff", "#ffffff"]}


def test_get_json_answers_note_team_colours() -> None:
    """The fetchers' answers already carry teamColors on every team object: they are noted with no extra call (and
    a basketball team inside a football answer is not)."""
    from oddsmarkets.football.sources import sofascore as S

    S.SEEN_COLOURS.clear()
    answer = {"events": [{"id": 99, "homeTeam": {"id": 2817, "name": "Barcelona", "sport": {"slug": "football"},
                                                 "teamColors": {"primary": "#a50044", "secondary": "#004d98",
                                                                "text": "#ffffff"}},
                          "awayTeam": {"id": 2829, "name": "Real Madrid",
                                       "teamColors": {"primary": "#ffffff", "secondary": "#00529f", "text": "#00529f"}},
                          "tournament": {"id": 8, "name": "LaLiga"}},
                         {"id": 100, "homeTeam": {"id": 3427, "sport": {"slug": "basketball"},
                                                  "teamColors": {"primary": "#000000"}}}],
              "hasNextPage": False}
    assert S.harvest_colours(answer) == 2 and S.harvest_colours("not json") == 0
    assert S.SEEN_COLOURS == {"2817": ["#a50044", "#004d98", "#ffffff"], "2829": ["#ffffff", "#00529f", "#00529f"]}
    S.SEEN_COLOURS.clear()


def test_the_committed_tables_are_well_formed() -> None:
    rows = C.load()
    assert len(rows) > 400
    for tid, (colour, alt, source) in rows.items():
        assert tid.isdigit() and C.HEX.match(colour) and (alt is None or C.HEX.match(alt)) and source in C.SOURCES
    for tid, (colour, alt) in C.OVERRIDES.items():
        assert tid.isdigit() and C.HEX.match(colour) and (alt is None or C.HEX.match(alt))
        assert rows[tid][2] in ("sofascore", "override")
    for tid, row in C._read(C.SOFASCORE_TABLE).items():
        assert tid.isdigit() and len(row) == 3 and C.HEX.match(row[0])
