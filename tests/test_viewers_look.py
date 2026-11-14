"""The viewers wear facet's night surface, from the brand manual.

Stdlib unittest: the six tokens are the only colours a viewer's CSS or JS may
name, the light variant and the red failure colours are gone, the three faces
are vendored under ``_kit/fonts/`` with their licences, the grain is drawn with
the manual's values behind the text, and the shared header is one line ending
in a verdict where Señal marks only what passed.

Markdown is not scanned for colours: the brand values belong in prose.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWERS = ROOT / "viewers"
KIT = VIEWERS / "_kit"
BASE = KIT / "base.css"
#: Every viewer, gallery included: it shares the surface but its own header.
KINDS = ("audio", "cad", "generic", "image", "video", "gallery")
#: The viewers that render one asset's record, and so the shared header.
RECORD_KINDS = ("audio", "cad", "generic", "image", "video")
SOURCES = (".css", ".js", ".html")
#: FR1: the whole palette, and every value it may take.
TOKENS = {
    "--fondo": "#161616",
    "--hueso": "#e7ded1",
    "--hueso-tenue": "#9a938a",
    "--senal": "#e8c547",
    "--regla": "rgba(231, 222, 209, 0.16)",
    "--panel": "rgba(231, 222, 209, 0.04)",
}
#: FR2: the five faces, relative to viewers/_kit/fonts/.
FACES = (
    "oldstandardtt/OldStandard-Regular.ttf",
    "oldstandardtt/OldStandard-Italic.ttf",
    "ebgaramond/EBGaramond[wght].ttf",
    "ebgaramond/EBGaramond-Italic[wght].ttf",
    "sometypemono/SometypeMono[wght].ttf",
)
LICENCE_DIRS = ("oldstandardtt", "ebgaramond", "sometypemono")
#: `#abc`, but not an id selector such as `#gal-head`.
HEX = re.compile(r"#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z_-])")
COLOUR_CALL = re.compile(r"rgba?\(")
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
TOKEN_USE = re.compile(r'token\("(--[a-z-]+)"\)')


def read(path: Path) -> str:
    """The file's text, UTF-8."""
    return path.read_text(encoding="utf-8")


def sources() -> list[Path]:
    """Every CSS, JS and HTML file under viewers/."""
    return sorted(path for path in VIEWERS.rglob("*") if path.is_file() and path.suffix in SOURCES)


def strip_comments(css: str) -> str:
    """The CSS without its comments: prose about a value is not a declaration."""
    return COMMENT.sub("", css)


def rules(css: str) -> list[tuple[str, str]]:
    """(selector list, body) for every flat rule; @media wrappers are ignored."""
    return [
        (selector.strip(), body.strip()) for selector, body in RULE.findall(strip_comments(css))
    ]


def declarations(css: str, selector: str) -> str:
    """The body of the first rule whose selector list contains `selector`."""
    for selectors, body in rules(css):
        if selector in [part.strip() for part in selectors.split(",")]:
            return body
    raise AssertionError(f"no rule for {selector}")


class PaletteTests(unittest.TestCase):
    """FR1: six tokens, and no other colour anywhere in the viewers."""

    def test_only_the_kit_names_a_colour(self) -> None:
        files = [path for path in sources() if path != BASE]
        self.assertGreater(len(files), len(KINDS), "no viewer sources were scanned")
        for path in files:
            source = read(path)
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertIsNone(HEX.search(source), "a hex colour outside _kit/base.css")
                self.assertIsNone(COLOUR_CALL.search(source), "rgb() outside _kit/base.css")

    def test_the_kit_defines_the_six_tokens(self) -> None:
        css = read(BASE)
        root = re.search(r":root\s*\{([^}]*)\}", css)
        self.assertIsNotNone(root, "no :root block")
        body = root.group(1)
        for name, value in TOKENS.items():
            with self.subTest(token=name):
                self.assertRegex(body, rf"{name}:\s*{re.escape(value)};")
        # A colour literal is never used in a rule: only the tokens are.
        outside = strip_comments(css).replace(body, "")
        for value in TOKENS.values():
            with self.subTest(value=value):
                self.assertNotIn(value, outside)

    def test_no_light_variant_and_no_red(self) -> None:
        for path in sources():
            source = read(path)
            where = path.relative_to(ROOT).as_posix()
            with self.subTest(path=where):
                self.assertNotIn("prefers-color-scheme", source, "there is no day variant")
                self.assertNotIn("--warning", source, "--warning was removed")
                self.assertNotIn("--error", source, "--error was removed: failure is Hueso tenue")
                self.assertNotIn("color-mix", source, "depth comes from --regla and --panel")

    def test_javascript_asks_the_kit_for_its_colours(self) -> None:
        used = set()
        for path in sources():
            if path.suffix == ".js":
                used.update(TOKEN_USE.findall(read(path)))
        self.assertTrue(used, "no viewer JS reads a token")
        self.assertLessEqual(used, set(TOKENS), "a JS file reads a token the kit does not define")

    def test_senal_marks_only_what_passed(self) -> None:
        for selectors, body in rules(read(BASE)):
            if "--senal" in body and selectors != ":root":
                with self.subTest(selector=selectors):
                    self.assertRegex(selectors, r"\.passed|\.verified")
        self.assertIn("var(--senal)", declarations(read(BASE), ".pill.passed"))
        gallery = read(VIEWERS / "gallery" / "gallery.css")
        self.assertNotIn("--senal", gallery, "a card's badge is the only Señal, from the kit")


class FontTests(unittest.TestCase):
    """FR2: the three faces, vendored with their OFL licences."""

    def test_faces_are_vendored_with_their_licences(self) -> None:
        for face in FACES:
            path = KIT / "fonts" / face
            with self.subTest(face=face):
                self.assertTrue(path.is_file(), face)
                self.assertGreater(path.stat().st_size, 20_000, f"{face} looks truncated")
        for folder in LICENCE_DIRS:
            licence = KIT / "fonts" / folder / "OFL.txt"
            with self.subTest(folder=folder):
                self.assertTrue(licence.is_file(), licence)
                self.assertIn("SIL Open Font License", read(licence))

    def test_font_faces_load_them_from_the_kit(self) -> None:
        css = strip_comments(read(BASE))
        urls = re.findall(r'url\("([^"]+)"\)', css)
        self.assertEqual(len(urls), len(FACES), "@font-face count")
        self.assertNotRegex(css, r"url\((?![\"'])", "quote every url(): [wght] breaks it")
        loaded = {str(KIT / "fonts" / url.removeprefix("/kit/fonts/")) for url in urls}
        self.assertEqual(loaded, {str(KIT / "fonts" / face) for face in FACES})
        for family in ("Old Standard TT", "EB Garamond", "Sometype Mono"):
            with self.subTest(family=family):
                self.assertIn(f'font-family: "{family}";', css)
        self.assertRegex(css, r"--font-title:\s*\"Old Standard TT\"")
        self.assertRegex(css, r"--font-text:\s*\"EB Garamond\"")
        self.assertRegex(css, r"--font-mono:\s*\"Sometype Mono\"")

    def test_each_face_takes_its_role(self) -> None:
        css = read(BASE)
        self.assertIn("var(--font-text)", declarations(css, "body"), "body text is Garamond")
        for selector in ("h1", "h2"):
            with self.subTest(selector=selector):
                self.assertIn("var(--font-title)", declarations(css, selector), "titles")
        for selector in (".num", "th", "dd", "dt"):
            with self.subTest(selector=selector):
                self.assertIn("var(--font-mono)", declarations(css, selector), "labels")
        gallery_css = read(VIEWERS / "gallery" / "gallery.css")
        self.assertIn("var(--font-mono)", declarations(gallery_css, "#gal-count"))
        # A card's capability id and creation date are mono, like every label.
        self.assertIn('"muted mono"', read(VIEWERS / "gallery" / "main.js"))


class GrainTests(unittest.TestCase):
    """FR3: the grain, drawn once per viewer with the manual's values."""

    def test_every_viewer_mounts_the_grain(self) -> None:
        for kind in KINDS:
            html = read(VIEWERS / kind / "index.html")
            with self.subTest(kind=kind):
                self.assertIn('src="/kit/grain.js"', html)
                self.assertLess(
                    html.index('href="/kit/base.css"'),
                    html.index('src="/kit/grain.js"'),
                    "the grain loads after the kit's tokens",
                )

    def test_the_grain_uses_the_manual_values(self) -> None:
        source = read(KIT / "grain.js")
        for name, value in {"QUARTER": 4, "MIN_GREY": 40, "MAX_GREY": 240, "ALPHA": 22}.items():
            with self.subTest(constant=name):
                self.assertRegex(source, rf"const {name} = {value};")
        self.assertRegex(source, r"const FRAME_MS = 90;")
        self.assertIn('window.matchMedia("(prefers-reduced-motion: reduce)")', source)
        # Reduced motion draws once and stays still: no interval is armed.
        self.assertLess(
            source.index("if (still.matches) return;"),
            source.index("window.setInterval"),
        )
        self.assertIn('document.createElement("canvas")', source)
        self.assertIn("aria-hidden", source)

    def test_the_grain_stays_behind_the_text(self) -> None:
        css = read(BASE)
        grain = declarations(css, ".grain")
        self.assertIn("position: fixed", grain)
        self.assertIn("z-index: 0", grain)
        self.assertIn("pointer-events: none", grain)
        self.assertIn("image-rendering: pixelated", grain)
        self.assertIn("z-index: 1", declarations(css, ".wrap"))


class HeaderTests(unittest.TestCase):
    """FR4 and FR5: one header line, one verdict, Señal only when verified."""

    def test_every_record_viewer_renders_the_shared_header(self) -> None:
        for kind in RECORD_KINDS:
            with self.subTest(kind=kind):
                self.assertIn('id="header"', read(VIEWERS / kind / "index.html"))
                main = read(VIEWERS / kind / "main.js")
                self.assertIn('import { renderHeader } from "/kit/header.js"', main)
                self.assertIn('renderHeader(document.getElementById("header"), record)', main)

    def test_header_is_one_line_with_a_verdict(self) -> None:
        source = read(KIT / "header.js")
        self.assertIn('brand.textContent = "facetMedia"', source)
        self.assertIn(" · ", source)
        self.assertIn('"✓ passed"', source)
        self.assertIn("✗ ${status}", source)
        self.assertIn("provenanceOf(record).capability", source)
        css = read(BASE)
        self.assertIn("var(--font-mono)", declarations(css, ".head h1.mark"))
        self.assertIn("var(--hueso-tenue)", declarations(css, ".head h1.mark"))
        self.assertIn("var(--hueso)", declarations(css, ".head .brand"))
        self.assertIn("var(--senal)", declarations(css, ".verdict.passed"))
        self.assertIn("var(--hueso-tenue)", declarations(css, ".verdict.failed"))
        self.assertIn("var(--regla)", declarations(css, "hr.rule"))

    def test_metric_values_are_senal_only_when_verified(self) -> None:
        source = read(KIT / "header.js")
        self.assertIn('statusOf(record) === "passed"', source)
        self.assertIn("thresholds[key] !== undefined", source)
        self.assertIn('classList.add("verified")', source)
        self.assertIn("var(--senal)", declarations(read(BASE), "td.num.verified"))


if __name__ == "__main__":
    unittest.main()
