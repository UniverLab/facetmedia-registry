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
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ascii_art", ROOT / "packages" / "ascii" / "art.py")
assert SPEC is not None and SPEC.loader is not None
art = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(art)

FONT = ROOT / "tests" / "fixtures" / "sometype-mono.ttf"
WORDMARK = ROOT / "tests" / "fixtures" / "canopy-dos-rebel.txt"
FONT_FIXTURES = ROOT / "tests" / "fixtures" / "fonts"
RUNNER = ROOT / "packages" / "ascii" / "runner.py"

STUB_SDK = """
import json
import sys
from pathlib import Path


class Request:
    def __init__(self, data):
        self.verb = str(data.get("verb", ""))
        self.capability = str(data.get("capability", ""))
        self.depth = str(data.get("depth", "quick"))
        self.inputs = dict(data.get("inputs") or {})
        self.out_dir = Path(str(data.get("out_dir", "")))
        self.piece_dir = Path(str(data.get("piece_dir", "")))
        self.assets = [Path(str(item)) for item in data.get("assets") or []]
        self._models = {str(k): Path(str(v)) for k, v in (data.get("models") or {}).items()}

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def model_path(self, model_id):
        return self._models[model_id]


class Runner:
    def __init__(self):
        self._verbs = {}

    def verb(self, name):
        def register(function):
            self._verbs[name] = function
            return function

        return register

    def run(self, argv):
        verb, *rest = argv
        values = {rest[index]: rest[index + 1] for index in range(0, len(rest), 2)}
        result = self._verbs[verb](Request.from_file(values["--input"]))
        Path(values["--result"]).write_text(json.dumps(result))
        return 0

    def main(self):
        raise SystemExit(self.run(sys.argv[1:]))
"""


def make_archive(path: Path, extra: dict[str, str] | None = None) -> Path:
    """A tar.gz shaped like the pinned figlet.js archive, from fixtures."""
    members = {item.name: item.read_text(encoding="utf-8") for item in FONT_FIXTURES.glob("*.flf")}
    members.update(extra or {})
    with tarfile.open(path, "w:gz") as handle:
        for name, text in members.items():
            payload = text.encode("utf-8")
            info = tarfile.TarInfo(f"fonts/{name}")
            info.size = len(payload)
            handle.addfile(info, io.BytesIO(payload))
    return path


def call_runner(
    root: Path,
    verb: str,
    capability: str,
    inputs: dict[str, Any],
    models: dict[str, Path],
    assets: tuple[Path, ...] = (),
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, Path]:
    """Run one verb in a subprocess against the stub SDK."""
    stub = root / "stub"
    stub.mkdir(exist_ok=True)
    (stub / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    out = root / "out"
    out.mkdir(exist_ok=True)
    piece = root / "piece"
    piece.mkdir(exist_ok=True)
    request = {
        "protocol": 1,
        "verb": verb,
        "capability": capability,
        "depth": "quick",
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(piece),
        "models": {key: str(value) for key, value in models.items()},
        "assets": [str(item) for item in assets],
    }
    input_path = root / f"{verb}-request.json"
    result_path = root / f"{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            verb,
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ],
        env={**os.environ, "PYTHONPATH": str(stub)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return done, result, out


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


class TestFontIndex(unittest.TestCase):
    def test_normalization_treats_case_and_separators_as_equal(self) -> None:
        expected = "linguaholic_mini_block"
        self.assertEqual(art.normalize_font("Linguaholic Mini Block"), expected)
        self.assertEqual(art.normalize_font("linguaholic-mini-block"), expected)
        self.assertEqual(art.normalize_font("  LINGUAHOLIC__mini  block "), expected)
        self.assertNotEqual(art.normalize_font("Linguaholic Mini"), expected)

    def test_pyfiglet_and_fixture_fonts_are_both_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = make_archive(Path(temp) / "fonts.tgz")
            fonts = art.list_fonts(archive)
        sources = {entry.display: entry.source for entry in fonts}
        self.assertEqual(sources["Fixture One"], "figlet.js")
        self.assertEqual(sources["Standard"], "pyfiglet")
        standards = [entry for entry in fonts if art.normalize_font(entry.display) == "standard"]
        self.assertEqual(len(standards), 1)

    def test_pyfiglet_wins_when_both_sources_have_the_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = make_archive(Path(temp) / "fonts.tgz")
            resolved = art.resolve_font("STANDARD", archive)
            self.assertEqual((resolved.display, resolved.source), ("Standard", "pyfiglet"))
            self.assertEqual(
                art.make_banner("abc", "standard", 80, archive),
                art.make_banner("abc", "standard", 80),
            )
            self.assertEqual(art.make_banner("abc", "fixture-one", 80, archive), ["XXX"])

    def test_a_broken_font_is_skipped_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = make_archive(Path(temp) / "fonts.tgz", {"Broken.flf": "not a figlet font\n"})
            index = art.load_font_index(archive)
        self.assertIn("Broken", index.skipped)
        self.assertNotIn("Broken", [entry.display for entry in index.fonts])

    def test_unknown_font_message_names_five_suggestions_and_the_fonts_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = make_archive(Path(temp) / "fonts.tgz")
            with self.assertRaises(art.UnknownFontError) as caught:
                art.make_banner("x", "no-such-font", 80, archive)
            closest = art.suggest_fonts("dos_rebe", art.load_font_index(archive))
        message = str(caught.exception)
        self.assertTrue(message.startswith('unknown font "no-such-font"; closest: '))
        self.assertTrue(message.endswith("; list them with facet run ascii.fonts"))
        listed = message.split("closest: ", 1)[1].split("; list them", 1)[0].split(", ")
        self.assertEqual(len(listed), 5)
        self.assertEqual(closest[0], "DOS Rebel")


class TestFontsCapability(unittest.TestCase):
    def _models(self, root: Path) -> dict[str, Path]:
        return {"sometype-mono": FONT, "figlet-js-fonts": make_archive(root / "fonts.tgz")}

    def test_run_lists_every_font_and_verify_matches_sheet_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            models = self._models(root)
            inputs = {"text": "facet", "name": "fonts"}
            done, result, out = call_runner(root, "run", "ascii.fonts", inputs, models)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIsNotNone(result)
            listing = (out / "fonts.txt").read_text(encoding="utf-8").splitlines()
            self.assertIn("Fixture One (figlet.js)", listing)
            self.assertIn("Standard (pyfiglet)", listing)
            with Image.open(out / "fonts.png") as sheet:
                count = int(sheet.text["fonts.count"])
            self.assertEqual(count, len(listing))
            self.assertGreater(count, 1)
            assets = (out / "fonts.txt", out / "fonts.png")
            done, verdict, _ = call_runner(root, "verify", "ascii.fonts", inputs, models, assets)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue(all(item["passed"] for item in verdict["assets"]))
            (out / "fonts.txt").write_text("only one\n", encoding="utf-8")
            done, verdict, _ = call_runner(root, "verify", "ascii.fonts", inputs, models, assets)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertFalse(all(item["passed"] for item in verdict["assets"]))

    def test_banner_records_the_resolved_font_and_its_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            models = self._models(root)
            inputs = {"text": "abc", "name": "fx", "font": "fixture-one"}
            done, result, out = call_runner(root, "run", "ascii.banner", inputs, models)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIsNotNone(result)
            asset = next(item for item in result["assets"] if item["file"] == "fx.txt")
            self.assertEqual(
                asset["properties"],
                {"columns": 3, "rows": 1, "font": "Fixture One", "source": "figlet.js"},
            )
            self.assertEqual((out / "fx.txt").read_text(encoding="utf-8"), "XXX\n")
            assets = (out / "fx.txt", out / "fx.svg")
            done, verdict, _ = call_runner(root, "verify", "ascii.banner", inputs, models, assets)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue(all(item["passed"] for item in verdict["assets"]))

    def test_an_unknown_font_fails_before_writing_any_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            models = self._models(root)
            inputs = {"text": "abc", "name": "fx", "font": "no-such-font"}
            done, result, out = call_runner(root, "run", "ascii.banner", inputs, models)
            self.assertNotEqual(done.returncode, 0)
            self.assertIsNone(result)
            self.assertIn('unknown font "no-such-font"', done.stderr)
            self.assertIn("list them with facet run ascii.fonts", done.stderr)
            self.assertEqual(list(out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
