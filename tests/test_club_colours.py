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


def test_refresh_writes_the_table_and_club_reads_it(tmp_path) -> None:
    crests = tmp_path / "crests"
    crests.mkdir()
    _crest(crests / "42.png", (200, 16, 46), inner=(0, 40, 120))
    _crest(crests / "7.png", (150, 150, 150))
    table = tmp_path / "club_colours.json"
    rows = C.refresh(crests, table)
    assert list(rows) == ["42"] and json.loads(table.read_text(encoding="utf-8")) == {"42": ["#c8102e", "#002878"]}
    assert C.club(42, table) == {"colour": "#c8102e", "alt": "#002878"} and C.club(7, table) == {}


def test_the_committed_table_is_well_formed() -> None:
    rows = C.load()
    assert len(rows) > 400
    for tid, (colour, alt) in rows.items():
        assert tid.isdigit() and C.HEX.match(colour) and (alt is None or C.HEX.match(alt))
