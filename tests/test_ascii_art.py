"""Tests for the ascii package's pure helpers (no facet needed).

Every mode converts a synthetic 64x64 image (a black disc on white) to
the expected grid size with a disc-shaped ink pattern; ``forma``
minimises the per-cell bitmap error by construction, so its shape error
beats ``densidad``'s and its re-render similarity clears the manifest's
0.55 floor. The ``canopy`` banner in ``dos_rebel`` equals the lab's
wordmark fixture byte for byte.
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
    def test_densidad_grid_and_disc(self) -> None:
        lines = art.to_densidad(disc(), WIDTH)
        self.assertEqual((len(lines[0]), len(lines)), (16, 8))
        self.assertTrue(is_ink(lines[4][7]))
        for corner in (lines[0][0], lines[0][15], lines[7][0], lines[7][15]):
            self.assertFalse(is_ink(corner))

    def test_trazo_grid_and_disc(self) -> None:
        lines = art.to_trazo(disc(), WIDTH)
        self.assertEqual((len(lines[0]), len(lines)), (16, 8))
        self.assertTrue(is_ink(lines[4][7]))
        for corner in (lines[0][0], lines[0][15], lines[7][0], lines[7][15]):
            self.assertFalse(is_ink(corner))

    def test_trazo_vertical_edge_is_vertical_stroke(self) -> None:
        grey = np.zeros((64, 64), dtype=np.float64)
        grey[:, 32:] = 1.0
        lines = art.to_trazo(grey, WIDTH)
        strokes = [line[7] for line in lines[1:-1]]
        self.assertEqual(set(strokes), {"│"})

    def test_braille_grid_and_disc(self) -> None:
        lines = art.to_braille(disc(), WIDTH)
        self.assertEqual((len(lines[0]), len(lines)), (16, 8))
        self.assertTrue(is_ink(lines[4][7]))
        for corner in (lines[0][0], lines[0][15], lines[7][0], lines[7][15]):
            self.assertFalse(is_ink(corner))

    def test_forma_grid_and_disc(self) -> None:
        atlas = art.glyph_atlas(FONT)
        lines = art.to_forma(disc(), WIDTH, atlas)
        self.assertEqual((len(lines[0]), len(lines)), (16, 8))
        self.assertTrue(is_ink(lines[4][7]))
        for corner in (lines[0][0], lines[0][15], lines[7][0], lines[7][15]):
            self.assertFalse(is_ink(corner))

    def test_forma_beats_densidad_shape_error(self) -> None:
        grey = disc()
        atlas = art.glyph_atlas(FONT)
        forma_err = art.shape_error(grey, WIDTH, atlas, art.to_forma(grey, WIDTH, atlas))
        dense_err = art.shape_error(grey, WIDTH, atlas, art.to_densidad(grey, WIDTH))
        self.assertLess(forma_err, dense_err)

    def test_forma_similarity_clears_floor(self) -> None:
        grey = disc()
        atlas = art.glyph_atlas(FONT)
        lines = art.to_forma(grey, WIDTH, atlas)
        re_rendered = art.render_text_bitmap(lines, atlas)
        similarity = art.pearson(
            art.downsample_to_grid(grey, WIDTH, 8),
            art.downsample_to_grid(re_rendered, WIDTH, 8),
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
