"""The viewers wear facet's night surface, from the brand manual.

Stdlib unittest: the seven tokens are the only colours a viewer's CSS or JS may
name, the light variant and the red failure colours are gone, the three faces
are vendored under ``_kit/fonts/`` with their licences, the grain is drawn with
the manual's values behind the text, and the shared header is one line ending
in a verdict where Señal marks only what passed.

Markdown is not scanned for colours: the brand values belong in prose.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from PIL import Image

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


class GalleryLineTests(unittest.TestCase):
    """The gallery lists one line per asset under its facet, in the manual's
    order: a rule, not a card; only the verdict may carry Señal, from the kit."""

    def setUp(self) -> None:
        self.html = read(VIEWERS / "gallery" / "index.html")
        self.main = read(VIEWERS / "gallery" / "main.js")
        self.css = read(VIEWERS / "gallery" / "gallery.css")

    def test_the_facet_groups_run_in_the_manual_order(self) -> None:
        match = re.search(r"const FACETS = \[([^\]]*)\]", self.main)
        self.assertIsNotNone(match)
        assert match is not None
        ids = re.findall(r'"([a-z]+)"', match.group(1))
        self.assertEqual(
            ids,
            ["voice", "audio", "image", "video", "cad", "text", "presentation"],
        )
        self.assertIn('const OTHER = "other";', self.main)
        self.assertIn(
            "if (FACETS.includes(card.facet)) buckets.get(card.facet).push(card);", self.main
        )
        self.assertIn("else other.push(card);", self.main)
        self.assertIn("groups.push({ facet: OTHER", self.main)
        # The groups are what the grid renders, each opening with its heading.
        self.assertIn("grid.replaceChildren(...groupsOf(assets).map(groupFor))", self.main)
        self.assertIn('element("h2", null, group.facet)', self.main)

    def test_a_line_without_open_names_the_fix(self) -> None:
        self.assertIn("`facet pull --package ${card.package}`", self.main)
        self.assertIn('"no preview: the record names no package"', self.main)
        self.assertIn('typeof card.package === "string"', self.main)
        self.assertIn('document.createElement(card.open ? "a" : "article")', self.main)
        self.assertIn("if (!card.open) line.append(fixOf(card));", self.main)

    def test_a_line_without_a_thumb_shows_its_kind_in_mono(self) -> None:
        self.assertIn('element("span", "kind-icon", card.kind)', self.main)
        self.assertNotIn("GLYPHS[card.kind]", self.main)
        body = declarations(self.css, ".kind-icon")
        self.assertIn("var(--font-mono)", body)
        self.assertIn("var(--hueso-tenue)", body)

    def test_the_fix_hint_is_hueso_tenue_throughout(self) -> None:
        self.assertIn("color: var(--hueso-tenue)", declarations(self.css, ".fix"))
        self.assertNotIn("var(--hueso)", declarations(self.css, ".fix code"))

    def test_a_line_is_a_rule_with_a_thumbnail_and_its_facts(self) -> None:
        card = declarations(self.css, ".card")
        self.assertIn("grid-template-columns: 48px 1fr auto", card)
        self.assertIn("border-bottom: 1px solid var(--regla)", card)
        self.assertIn("text-decoration: none", card)
        thumb = declarations(self.css, ".thumb")
        self.assertIn("width: 48px", thumb)
        self.assertIn("height: 48px", thumb)
        self.assertIn("var(--fondo)", thumb)
        self.assertIn("object-fit: cover", declarations(self.css, ".thumb img"))
        focus = declarations(self.css, ".card:focus-visible")
        self.assertIn("outline: 2px solid var(--hueso)", focus)
        for selector in (".card-name", ".capability", ".facts", ".created", ".pill"):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.css)

    def test_only_the_kit_may_name_senal(self) -> None:
        self.assertNotIn("--senal", self.css)
        self.assertIn('"pill passed"', self.main)
        self.assertIn('"pill failed"', self.main)

    def test_the_search_matches_name_or_capability_under_the_kind_toggles(self) -> None:
        self.assertIn('id="search"', self.html)
        self.assertIn('aria-label="search name or capability"', self.html)
        self.assertIn("name.includes(needle) || capability.includes(needle)", self.main)
        self.assertIn("shown.has(line.dataset.kind)", self.main)
        self.assertIn("group.hidden = visible === 0", self.main)

    def test_the_header_names_the_gallery_and_counts_the_verified(self) -> None:
        mark = re.search(r'<h1 id="gal-mark"[^>]*>(.*?)</h1>', self.html, re.DOTALL)
        self.assertIsNotNone(mark)
        assert mark is not None
        self.assertIn("gallery", mark.group(1))
        self.assertIn('class="brand">facetMedia', mark.group(1))
        self.assertIn('id="gal-verified"', self.html)
        self.assertIn("verdict passed", self.html)
        self.assertIn("`${verified} verified`", self.main)
        self.assertIn("var(--font-mono)", declarations(self.css, "#gal-count"))


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

    def test_only_the_slides_and_video_viewers_may_name_the_slide_black(self) -> None:
        users = sorted(
            path.relative_to(ROOT).as_posix()
            for path in sources()
            if path != BASE and "slide-black" in read(path)
        )
        self.assertEqual(users, ["viewers/slides/slides.css", "viewers/video/video.css"])


class AudioViewerTests(unittest.TestCase):
    """The audio viewer: a player, a scrubbable waveform, and the numbers."""

    def setUp(self) -> None:
        self.html = read(VIEWERS / "audio" / "index.html")
        self.main = read(VIEWERS / "audio" / "main.js")

    def test_the_transport_is_a_button_and_a_clock_not_the_native_bar(self) -> None:
        self.assertIn('id="play"', self.html)
        self.assertIn('id="time"', self.html)
        player = re.search(r"<audio[^>]*>", self.html)
        self.assertIsNotNone(player)
        self.assertNotIn("controls", player.group(0), "the native bar is replaced")
        self.assertIn('button.textContent = audio.paused ? "play" : "pause"', self.main)
        self.assertIn("`${clock(audio.currentTime)} / ${clock(duration)}`", self.main)

    def test_space_toggles_and_the_arrows_seek_one_second(self) -> None:
        self.assertIn('event.key === " "', self.main)
        self.assertIn("togglePlay(audio)", self.main)
        self.assertIn("seekBy(audio, -1, duration)", self.main)
        self.assertIn("seekBy(audio, 1, duration)", self.main)
        self.assertIn("Math.min(Math.max((audio.currentTime || 0) + seconds, 0), last)", self.main)

    def test_the_waveform_is_scrubbed_by_click_and_by_drag(self) -> None:
        self.assertIn('canvas.addEventListener("pointerdown"', self.main)
        self.assertIn('canvas.addEventListener("pointermove"', self.main)
        self.assertIn("if (dragging) seek(event);", self.main)
        self.assertIn("audio.currentTime = valueAtX(canvas, event.clientX, duration);", self.main)
        # a finger drag must not scroll the page instead of seeking
        self.assertIn("touch-action: none", declarations(read(BASE), "#wave"))

    def test_the_played_part_is_hueso_and_the_rest_hueso_tenue(self) -> None:
        self.assertIn("paintPlayed(ctx, geom, preview, audio);", self.main)
        self.assertIn('ctx.fillStyle = token("--hueso");', self.main)
        self.assertIn('ctx.strokeStyle = token("--hueso");', self.main)
        # the band underneath is the kit's tenue, drawn by the shared chart
        self.assertIn("fillStyle = pal.tenue", read(KIT / "chart.js"))

    def test_the_loudness_target_keeps_its_dashed_rule(self) -> None:
        self.assertIn("ref: preview.loudness?.target_lufs,", self.main)
        self.assertIn('refLabel: `target ${preview.loudness?.target_lufs ?? ""} LUFS`', self.main)
        self.assertIn("ctx.setLineDash([5, 4]);", read(KIT / "chart.js"))

    def test_the_numbers_name_loudness_peak_rate_and_peak_limiting(self) -> None:
        for row in ('["duration"', '["sample rate"', '["integrated loudness"', '["true peak"'):
            with self.subTest(row=row):
                self.assertIn(row, self.main)
        self.assertIn('preview.sample_rate_hz ? `${preview.sample_rate_hz} Hz` : "—"', self.main)
        self.assertIn(
            "if (metrics.peak_limited !== undefined) return metrics.peak_limited;", self.main
        )
        self.assertIn(
            "if (record?.properties?.peak_limited !== undefined) "
            "return record.properties.peak_limited;",
            self.main,
        )
        self.assertIn('["peak limited", yesNo(limited)]', self.main)


class VideoViewerTests(unittest.TestCase):
    """The video viewer: a clip you play and scrub, or a GIF that loops."""

    def setUp(self) -> None:
        self.html = read(VIEWERS / "video" / "index.html")
        self.css = read(VIEWERS / "video" / "video.css")
        self.main = read(VIEWERS / "video" / "main.js")

    def test_the_stage_letterboxes_on_the_reserved_black(self) -> None:
        body = declarations(self.css, "#stage")
        self.assertIn("var(--slide-black)", body)
        self.assertIn("object-fit: contain", declarations(self.css, "#stage video"))
        self.assertIn("object-fit: contain", declarations(self.css, "#stage img"))
        self.assertIn('href="./video.css"', self.html)
        self.assertLess(
            self.html.index('href="/kit/base.css"'),
            self.html.index('href="./video.css"'),
            "the viewer's own sheet comes after the kit",
        )

    def test_the_playable_clip_plays_scrubs_and_steps_frames(self) -> None:
        for control in ('id="play"', 'id="scrub"', 'id="time"', 'id="frame"'):
            with self.subTest(control=control):
                self.assertIn(control, self.html)
        self.assertIn('const FRAME_KEYS = { ",": -1, ".": 1 };', self.main)
        self.assertIn('event.key === " "', self.main)
        self.assertIn("clip.currentTime = Number(scrub.value);", self.main)
        self.assertIn("`frame ${frame} / ${ui.total}`", self.main)
        self.assertIn("ui.clip.currentTime + direction / ui.fps", self.main)
        self.assertIn("if (ui.clip.paused) stepFrame(ui, direction);", self.main)
        self.assertIn("stage.requestFullscreen?.()", self.main)
        self.assertIn('event.key === "f" || event.key === "F"', self.main)

    def test_the_clip_is_chosen_by_mime_and_a_gif_gets_its_own_line(self) -> None:
        self.assertIn('const GIF_MIME = "image/gif";', self.main)
        self.assertIn("if (record.mime === GIF_MIME) renderGif(name, record, preview);", self.main)
        self.assertIn("return `GIF · loops · ${frames} frames · ${fps} fps`;", self.main)
        self.assertIn("const frames = props.frames ?? preview.length", self.main)
        self.assertIn("const fps = props.fps ?? preview.fps", self.main)
        # a GIF loops as GIFs do: no scrub bar, no frame stepping
        self.assertIn('id="clip-controls" class="controls" hidden', self.html)
        self.assertNotIn("stepFrame", self.html)

    def test_a_file_the_browser_cannot_play_falls_back_to_an_image_or_its_kind(self) -> None:
        self.assertIn(
            'clip.addEventListener("error", () => unplayable(name, record, preview));', self.main
        )
        self.assertIn(
            "const images = Array.isArray(preview.images) ? preview.images : [];", self.main
        )
        self.assertIn('document.getElementById("open-file").href = assetUrl(name);', self.main)
        self.assertIn("open file", self.html)
        self.assertIn('id="kind-label"', self.html)

    def test_the_metrics_name_resolution_rate_frames_duration_and_sound(self) -> None:
        for row in ('["resolution"', '["fps"', '["frames"', '["duration"'):
            with self.subTest(row=row):
                self.assertIn(row, self.main)
        self.assertIn(
            'if (typeof length === "number" && typeof fps === "number" && fps > 0) '
            "return length / fps;",
            self.main,
        )
        self.assertIn('if (typeof metrics.audio_streams === "number") {', self.main)
        self.assertIn('["integrated loudness", `${loud.integrated_lufs} LUFS`]', self.main)


class ImageViewerTests(unittest.TestCase):
    """The image viewer: fitted, 1:1 with a pan, and a checkerboard."""

    def setUp(self) -> None:
        self.html = read(VIEWERS / "image" / "index.html")
        self.main = read(VIEWERS / "image" / "main.js")

    def test_the_stage_holds_the_still_and_the_old_dialog_is_gone(self) -> None:
        self.assertIn('<div id="stage" class="stage fit"', self.html)
        self.assertIn('id="still"', self.html)
        self.assertNotIn('id="zoom"', self.html)
        self.assertNotIn("showModal", self.main)

    def test_z_and_a_click_toggle_one_to_one_and_a_drag_pans(self) -> None:
        self.assertIn('stage.classList.toggle("fit")', self.main)
        self.assertIn('if (event.key !== "z" && event.key !== "Z") return;', self.main)
        self.assertIn("if (drag !== null && !drag.moved) toggleFit(stage);", self.main)
        self.assertIn("stage.scrollLeft = drag.left - dx;", self.main)
        self.assertIn("#image .stage:not(.fit) img", read(BASE))
        self.assertIn("overflow: auto", declarations(read(BASE), "#image .stage"))

    def test_the_checkerboard_is_drawn_with_the_kit_tokens(self) -> None:
        body = declarations(read(BASE), ".checker")
        self.assertIn("var(--regla)", body)
        self.assertIn("var(--fondo)", body)
        self.assertIn('stage.classList.toggle("checker")', self.main)
        self.assertIn('button.setAttribute("aria-pressed", String(checked))', self.main)

    def test_the_metrics_name_the_pixels_and_the_file_size(self) -> None:
        self.assertIn('["pixels"', self.main)
        self.assertIn("formatBytes(record.bytes)", self.main)
        self.assertIn('if (typeof bytes !== "number") return "—";', self.main)


class CadViewerTests(unittest.TestCase):
    """The CAD viewer: every view as a panel, measures beside expectations."""

    def setUp(self) -> None:
        self.main = read(VIEWERS / "cad" / "main.js")

    def test_every_view_is_a_large_panel(self) -> None:
        self.assertIn("for (const view of views) {", self.main)
        self.assertIn('container.classList.add("panels");', self.main)
        self.assertIn("flex: 1 1 100%", declarations(read(BASE), ".views.panels figure"))

    def test_every_view_opens_from_the_keyboard(self) -> None:
        # A view is a button: focusable, labelled, and opened by Enter or space.
        self.assertIn("image.tabIndex = 0;", self.main)
        self.assertIn('image.setAttribute("role", "button");', self.main)
        self.assertIn('image.setAttribute("aria-label", `enlarge ${image.alt}`);', self.main)
        self.assertIn('if (event.key !== "Enter" && event.key !== " ") return;', self.main)
        # The dialog gives the focus back to the view that opened it.
        self.assertIn('dialog.addEventListener("close", () => opener?.focus());', self.main)
        body = declarations(read(BASE), ".views.panels img:focus-visible")
        self.assertIn("outline: 2px solid var(--hueso)", body)

    def test_the_expected_volume_and_box_sit_beside_the_measured_ones(self) -> None:
        self.assertIn('params["expect-volume-mm3"]', self.main)
        self.assertIn('params["expect-bbox-mm"]', self.main)
        self.assertIn('["expected volume"', self.main)
        self.assertIn('["expected bounding box"', self.main)
        self.assertIn('["measured volume"', self.main)
        self.assertIn('["measured bounding box"', self.main)
        # the core delivers one {x, y, z} item, and a flat triple reads too
        self.assertIn("const sides = [first.x, first.y, first.z];", self.main)
        self.assertIn("value.length === 3 ? value : null", self.main)


class GenericViewerTests(unittest.TestCase):
    """The generic viewer: text, JSON, subtitles and ASCII, each with a copy."""

    def setUp(self) -> None:
        self.html = read(VIEWERS / "generic" / "index.html")
        self.main = read(VIEWERS / "generic" / "main.js")

    def test_the_branch_is_chosen_by_the_record(self) -> None:
        # ascii is text that says how wide it is: a contact-sheet record
        # (image/png, image/svg+xml) carries columns too, but keeps the fallback
        self.assertIn(
            'if (mime === "text/plain" && typeof record.properties?.columns === "number") {',
            self.main,
        )
        self.assertIn('if (SUBTITLE_MIMES.has(mime)) return "cues";', self.main)
        self.assertIn('if (mime === "application/json") return "json";', self.main)
        self.assertIn('if (mime === "text/plain") return "text";', self.main)
        self.assertIn(
            'const SUBTITLE_MIMES = new Set(["application/x-subrip", "text/vtt", "text/srt"]);',
            self.main,
        )
        # an unlisted mime keeps the fields table and the link: the fallback
        self.assertIn("return null;", self.main)
        self.assertIn('id="fields"', self.html)
        self.assertIn('id="asset-link"', self.html)

    def test_plain_text_is_numbered_and_json_is_pretty_printed(self) -> None:
        self.assertIn('id="lines" class="linenums"', self.html)
        self.assertIn('document.createElement("li")', self.main)
        self.assertIn("JSON.stringify(JSON.parse(raw), null, 2)", self.main)
        self.assertIn('id="json" class="ascii"', self.html)

    def test_subtitles_become_a_time_and_text_list(self) -> None:
        self.assertIn('id="cues-section"', self.html)
        self.assertIn('const [start, end = ""] = lines[arrow].split("-->");', self.main)
        self.assertIn("time: `${start.trim()} --> ${trimmedEnd}`", self.main)
        self.assertIn('text: lines.slice(arrow + 1).join(" ").trim()', self.main)

    def test_ascii_art_keeps_its_width_and_scrolls(self) -> None:
        body = declarations(read(BASE), ".ascii")
        self.assertIn("white-space: pre", body)
        self.assertIn("overflow-x: auto", body)
        self.assertIn('raw.replace(/\\n+$/, "")', self.main)

    def test_every_branch_has_a_copy_button(self) -> None:
        for name in ("text", "json", "cues", "ascii"):
            with self.subTest(branch=name):
                self.assertIn(f'id="copy-{name}"', self.html)
                self.assertIn(f'wireCopy("copy-{name}"', self.main)
        self.assertIn("await navigator.clipboard.writeText(text);", self.main)
        self.assertIn('button.textContent = "copied";', self.main)


class ViewerExampleTests(unittest.TestCase):
    """Each sample exercises the part its viewer exists for."""

    def test_the_video_example_carries_a_gif_beside_the_clip(self) -> None:
        folder = VIEWERS / "_examples" / "video"
        gif = folder / "loop.gif"
        record = json.loads(read(folder / "loop.gif.facet.json"))
        preview = json.loads(read(folder / "loop.gif.preview.json"))
        self.assertTrue(gif.is_file(), "no GIF sample")
        self.assertEqual(record["kind"], "video")
        self.assertEqual(record["mime"], "image/gif")
        self.assertEqual(record["path"], "loop.gif")
        self.assertEqual(preview["kind"], record["kind"])
        properties = record["properties"]
        for key in ("frames", "fps", "duration_s", "width", "height"):
            with self.subTest(key=key):
                self.assertIn(key, properties)
        self.assertEqual(preview["length"], properties["frames"])
        self.assertEqual(preview["fps"], properties["fps"])
        # the fixture is the animation its record claims
        with Image.open(gif) as image:
            self.assertEqual(image.n_frames, properties["frames"])

    def test_the_audio_example_carries_peak_limiting(self) -> None:
        record = json.loads(read(VIEWERS / "_examples" / "audio" / "tone.wav.facet.json"))
        self.assertIs(record["verification"]["metrics"]["peak_limited"], True)

    def test_the_cad_example_declares_what_it_expected(self) -> None:
        record = json.loads(read(VIEWERS / "_examples" / "cad" / "escuadra.step.facet.json"))
        params = record["provenance"]["params"]
        self.assertEqual(params["expect-volume-mm3"], 9500)
        self.assertEqual(params["expect-bbox-mm"], [{"x": 80, "y": 40, "z": 3}])

    def test_the_generic_examples_cover_the_cues_and_ascii_branches(self) -> None:
        folder = VIEWERS / "_examples" / "generic"
        notes = json.loads(read(folder / "notes.srt.facet.json"))
        self.assertEqual(notes["mime"], "application/x-subrip")
        self.assertTrue((folder / "notes.srt").is_file())
        sheet = json.loads(read(folder / "sheet.txt.facet.json"))
        self.assertEqual(sheet["properties"]["columns"], 40)
        lines = read(folder / "sheet.txt").splitlines()
        self.assertEqual(max(len(line) for line in lines), 40, "the art is as wide as it claims")
        self.assertIn("-->", read(folder / "notes.srt"))

    def test_the_generic_examples_cover_the_json_and_vtt_branches(self) -> None:
        folder = VIEWERS / "_examples" / "generic"
        piece = json.loads(read(folder / "pieza.json.facet.json"))
        self.assertEqual(piece["mime"], "application/json")
        self.assertIsInstance(json.loads(read(folder / "pieza.json")), dict)
        # one line on disk, so the viewer's pretty-print is what is read
        self.assertEqual(len(read(folder / "pieza.json").splitlines()), 1)
        vtt = json.loads(read(folder / "notes.vtt.facet.json"))
        self.assertEqual(vtt["mime"], "text/vtt")
        text = read(folder / "notes.vtt")
        self.assertTrue(text.startswith("WEBVTT"))
        self.assertEqual(text.count("-->"), 2)

    def test_the_generic_fallback_sample_is_a_picture_that_says_its_width(self) -> None:
        """A contact-sheet record (kind text, image mime, columns) is the asset
        that must keep the fields fallback: never its bytes as text."""
        folder = VIEWERS / "_examples" / "generic"
        record = json.loads(read(folder / "plate.svg.facet.json"))
        preview = json.loads(read(folder / "plate.svg.preview.json"))
        self.assertEqual(record["kind"], "text")
        self.assertEqual(record["mime"], "image/svg+xml")
        self.assertIsInstance(record["properties"]["columns"], int)
        self.assertEqual(record["bytes"], (folder / "plate.svg").stat().st_size)
        self.assertTrue((folder / "plate.svg").is_file())
        self.assertEqual(preview["kind"], "text")

    def test_the_image_examples_carry_a_transparent_cut_out(self) -> None:
        folder = VIEWERS / "_examples" / "image"
        cutout = folder / "recorte.png"
        self.assertTrue(cutout.is_file(), "no transparent PNG sample")
        record = json.loads(read(folder / "recorte.png.facet.json"))
        preview = json.loads(read(folder / "recorte.png.preview.json"))
        self.assertEqual(record["mime"], "image/png")
        self.assertEqual(preview["kind"], "image")
        with Image.open(cutout) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getchannel("A").getextrema()[0], 0, "no see-through pixel")
            self.assertEqual(
                (image.width, image.height),
                (record["properties"]["width"], record["properties"]["height"]),
            )


if __name__ == "__main__":
    unittest.main()
