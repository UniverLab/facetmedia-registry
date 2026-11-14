"""The viewers wear facet's night surface, from the brand manual.

Stdlib unittest: the seven tokens are the only colours a viewer's CSS or JS may
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
KINDS = ("audio", "cad", "document", "generic", "image", "video", "gallery", "slides")
#: The viewers that render one asset's record, and so the shared header.
RECORD_KINDS = ("audio", "cad", "document", "generic", "image", "video", "slides")
SOURCES = (".css", ".js", ".html")
#: FR1: the whole palette, and every value it may take.
TOKENS = {
    "--fondo": "#161616",
    "--hueso": "#e7ded1",
    "--hueso-tenue": "#9a938a",
    "--senal": "#e8c547",
    "--regla": "rgba(231, 222, 209, 0.16)",
    "--panel": "rgba(231, 222, 209, 0.04)",
    "--slide-black": "#000",
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
    """FR1: the seven tokens, and no other colour anywhere in the viewers."""

    def test_only_the_kit_names_a_colour(self) -> None:
        files = [path for path in sources() if path != BASE]
        self.assertGreater(len(files), len(KINDS), "no viewer sources were scanned")
        for path in files:
            source = read(path)
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertIsNone(HEX.search(source), "a hex colour outside _kit/base.css")
                self.assertIsNone(COLOUR_CALL.search(source), "rgb() outside _kit/base.css")

    def test_the_kit_defines_the_tokens(self) -> None:
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


class DocumentViewerTests(unittest.TestCase):
    """The document viewer: pages down the left, the selected page on the right."""

    def setUp(self) -> None:
        self.folder = VIEWERS / "document"
        self.html = read(self.folder / "index.html")
        self.css = read(self.folder / "document.css")
        self.main = read(self.folder / "main.js")

    def test_the_layout_is_a_thumbnail_column_beside_the_stage(self) -> None:
        body = declarations(self.css, ".doc")
        self.assertIn("display: grid", body)
        self.assertIn("grid-template-columns: 9rem 1fr", body)
        self.assertIn('id="thumbs"', self.html)
        self.assertIn('id="stage"', self.html)
        self.assertIn('id="page"', self.html)

    def test_every_thumbnail_carries_its_number_in_mono(self) -> None:
        self.assertIn('document.createElement("button")', self.main)
        self.assertIn('num.className = "num"', self.main)
        self.assertIn('padStart(2, "0")', self.main)
        self.assertIn("var(--font-mono)", declarations(read(BASE), ".num"))
        self.assertIn("var(--senal)", declarations(self.css, '#thumbs button[aria-current="page"]'))

    def test_the_page_is_fitted_to_the_width_with_a_one_to_one_toggle(self) -> None:
        self.assertIn("max-width: 100%", declarations(self.css, "#stage img"))
        self.assertIn("width: auto", declarations(self.css, "#stage.fit img"))
        self.assertIn('id="fit"', self.html)
        self.assertIn('stage.classList.toggle("fit")', self.main)
        self.assertIn('button.textContent = fit ? "fit width" : "1:1"', self.main)

    def test_the_keys_step_and_a_number_then_enter_jumps(self) -> None:
        for key in ("ArrowUp", "ArrowDown", "PageUp", "PageDown"):
            with self.subTest(key=key):
                self.assertIn(f"{key}:", self.main)
        self.assertIn('event.key === "Enter"', self.main)
        self.assertIn("/^[0-9]$/.test(event.key)", self.main)
        self.assertIn("select(Number(typed) - 1)", self.main)
        self.assertIn("Math.min(Math.max(index, 0), pages.length - 1)", self.main)

    def test_the_header_action_opens_the_pdf_from_the_asset_route(self) -> None:
        self.assertIn('id="pdf-link"', self.html)
        self.assertIn('target="_blank"', self.html)
        self.assertIn('rel="noopener"', self.html)
        self.assertIn("open PDF", self.html)
        self.assertIn("record.path ?? name", self.main)
        self.assertIn("assetUrl(asset)", self.main)

    def test_the_pages_come_from_the_preview_beside_the_asset(self) -> None:
        self.assertIn("`/asset/${folder}${page}`", self.main)
        self.assertIn("Array.isArray(preview.pages)", self.main)

    def test_a_phone_window_turns_the_column_into_a_strip(self) -> None:
        self.assertIn("@media (max-width: 40rem)", self.css)
        narrow = self.css[self.css.index("@media (max-width: 40rem)") :]
        self.assertIn("grid-template-columns: 1fr", narrow)
        self.assertIn("flex-direction: row", narrow)
        self.assertIn("overflow-x: auto", narrow)


class SlidesViewerTests(unittest.TestCase):
    """The slides viewer: three roles over one channel, black reserved."""

    def setUp(self) -> None:
        self.folder = VIEWERS / "slides"
        self.html = read(self.folder / "index.html")
        self.css = read(self.folder / "slides.css")
        self.main = read(self.folder / "main.js")

    def test_the_role_parameter_picks_three_views_over_one_channel(self) -> None:
        for view in ("view-default", "view-audience", "view-presenter"):
            with self.subTest(view=view):
                self.assertIn(f'id="{view}"', self.html)
        for role in ("audience", "presenter"):
            with self.subTest(role=role):
                self.assertIn(f'"{role}"', self.main)
        self.assertIn("BroadcastChannel(`facet-slides-${name}`)", self.main)

    def test_the_audience_view_hides_the_header_and_the_grain(self) -> None:
        self.assertIn('document.getElementById("header").hidden = view !== "default"', self.main)
        self.assertIn("display: none", declarations(self.css, 'body[data-role="audience"] .grain'))

    def test_the_views_take_their_keys_notes_counter_and_clock(self) -> None:
        for key in ("ArrowRight", "ArrowLeft", "PageDown", "PageUp"):
            with self.subTest(key=key):
                self.assertIn(f"{key}:", self.main)
        for key in ("Home", "End"):
            with self.subTest(key=key):
                self.assertIn(f'"{key}"', self.main)
        self.assertIn('event.key === "Enter"', self.main)
        self.assertIn("/^[0-9]$/.test(event.key)", self.main)
        for button in ("btn-prev", "btn-next", "btn-black", "btn-audience"):
            with self.subTest(button=button):
                self.assertIn(f'id="{button}"', self.html)
                self.assertIn(f'getElementById("{button}")', self.main)
        self.assertIn("no speaker notes", self.main)
        self.assertIn("var(--font-text)", declarations(self.css, "#pres-notes"))
        for selector in ("#pres-count", "#pres-clock"):
            with self.subTest(selector=selector):
                self.assertIn("var(--font-mono)", declarations(self.css, selector))

    def test_the_blackout_and_the_letterbox_use_the_reserved_black(self) -> None:
        for selector in ("#aud-frame", "#aud-black"):
            with self.subTest(selector=selector):
                self.assertIn("var(--slide-black)", declarations(self.css, selector))

    def test_only_the_slides_viewer_may_name_the_slide_black(self) -> None:
        users = sorted(
            path.relative_to(ROOT).as_posix()
            for path in sources()
            if path != BASE and "slide-black" in read(path)
        )
        self.assertEqual(users, ["viewers/slides/slides.css"])


if __name__ == "__main__":
    unittest.main()
