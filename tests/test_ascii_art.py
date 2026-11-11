"""Tests for the ascii package's pure helpers (no facet needed).

Every mode converts a synthetic 64x64 image (a black disc on white) to
the expected grid size with a disc-shaped ink pattern; ``shape``
minimises the per-cell bitmap error by construction, so its shape error
beats ``density``'s and its re-render similarity clears the manifest's
0.55 floor. Verify's re-render must stay meaningful for every mode:
``braille`` decodes to dot cells and ``stroke``'s marks fill their cells,
so neither re-renders to a blank grid. The ``canopy`` banner in
``dos_rebel`` equals the lab's wordmark fixture byte for byte.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ascii_art", ROOT / "packages" / "ascii" / "art.py")
assert SPEC is not None and SPEC.loader is not None
art = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(art)

FONT = ROOT / "tests" / "fixtures" / "sometype-mono.ttf"
WORDMARK = ROOT / "tests" / "fixtures" / "canopy-dos-rebel.txt"

WIDTH = 16
BLANK = (" ", "⠀")


def disc(size: int = 64, radius: int = 28) -> np.ndarray:
    """A black disc on white as a 0..1 grey array (0 is black)."""
    rows, cols = np.ogrid[:size, :size]
    grey = np.ones((size, size), dtype=np.float64)
    grey[(rows - size // 2) ** 2 + (cols - size // 2) ** 2 <= radius**2] = 0.0
    return grey


def is_ink(char: str) -> bool:
    return char not in BLANK


class TestModes(unittest.TestCase):
    def test_density_grid_and_disc(self) -> None:
        lines = art.to_density(disc(), WIDTH)
        self.assertEqual((len(lines[0]), len(lines)), (16, 8))
        self.assertTrue(is_ink(lines[4][7]))
        for corner in (lines[0][0], lines[0][15], lines[7][0], lines[7][15]):
            self.assertFalse(is_ink(corner))

    def test_stroke_grid_and_disc(self) -> None:
        lines = art.to_stroke(disc(), WIDTH)
        self.assertEqual((len(lines[0]), len(lines)), (16, 8))
        self.assertTrue(is_ink(lines[4][7]))
        for corner in (lines[0][0], lines[0][15], lines[7][0], lines[7][15]):
            self.assertFalse(is_ink(corner))

    def test_stroke_vertical_edge_is_vertical_stroke(self) -> None:
        grey = np.zeros((64, 64), dtype=np.float64)
        grey[:, 32:] = 1.0
        lines = art.to_stroke(grey, WIDTH)
        strokes = [line[7] for line in lines[1:-1]]
        self.assertEqual(set(strokes), {"│"})

    def test_braille_grid_and_disc(self) -> None:
        lines = art.to_braille(disc(), WIDTH)
        self.assertEqual((len(lines[0]), len(lines)), (16, 8))
        self.assertTrue(is_ink(lines[4][7]))
        for corner in (lines[0][0], lines[0][15], lines[7][0], lines[7][15]):
            self.assertFalse(is_ink(corner))

    def test_shape_grid_and_disc(self) -> None:
        atlas = art.glyph_atlas(FONT)
        lines = art.to_shape(disc(), WIDTH, atlas)
        self.assertEqual((len(lines[0]), len(lines)), (16, 8))
        self.assertTrue(is_ink(lines[4][7]))
        for corner in (lines[0][0], lines[0][15], lines[7][0], lines[7][15]):
            self.assertFalse(is_ink(corner))

    def test_shape_beats_density_shape_error(self) -> None:
        grey = disc()
        atlas = art.glyph_atlas(FONT)
        shape_err = art.shape_error(grey, WIDTH, atlas, art.to_shape(grey, WIDTH, atlas))
        dense_err = art.shape_error(grey, WIDTH, atlas, art.to_density(grey, WIDTH))
        self.assertLess(shape_err, dense_err)

    def test_shape_similarity_clears_floor(self) -> None:
        grey = disc()
        atlas = art.glyph_atlas(FONT)
        lines = art.to_shape(grey, WIDTH, atlas)
        re_rendered = art.render_text_bitmap(lines, atlas)
        similarity = art.pearson(
            art.downsample_to_grid(grey, WIDTH, 8),
            art.downsample_to_grid(re_rendered, WIDTH, 8),
        )
        self.assertGreaterEqual(similarity, 0.55)

    def test_every_mode_re_renders_with_ink(self) -> None:
        grey = disc()
        atlas = art.glyph_atlas(FONT)
        outputs = [
            art.to_density(grey, WIDTH),
            art.to_stroke(grey, WIDTH),
            art.to_braille(grey, WIDTH),
            art.to_shape(grey, WIDTH, atlas),
        ]
        for lines in outputs:
            self.assertGreater(art.render_text_bitmap(lines, atlas).std(), 0.0)

    def test_braille_similarity_clears_floor(self) -> None:
        grey = disc()
        atlas = art.glyph_atlas(FONT)
        rendered = art.render_text_bitmap(art.to_braille(grey, WIDTH), atlas)
        similarity = art.pearson(
            art.downsample_to_grid(grey, WIDTH, 8),
            art.downsample_to_grid(rendered, WIDTH, 8),
        )
        self.assertGreaterEqual(similarity, 0.55)


class TestBanner(unittest.TestCase):
    def test_canopy_matches_wordmark_fixture(self) -> None:
        lines = art.make_banner("canopy", "dos_rebel", 120)
        self.assertEqual("\n".join(lines) + "\n", WORDMARK.read_text(encoding="utf-8"))

    def test_svg_has_one_rect_per_inked_cell(self) -> None:
        lines = art.make_banner("canopy", "dos_rebel", 120)
        svg = art.banner_svg(lines)
        inked = sum(1 for line in lines for char in line if char != " ")
        self.assertEqual(svg.count("<rect"), inked)


if __name__ == "__main__":
    unittest.main()
