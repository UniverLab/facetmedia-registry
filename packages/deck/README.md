# deck

Build a slide deck from one HTML file into a paginated PDF and one PNG per
page. `deck.slides` is the presentation package: it owns the deck format and
the export, and wraps the pinned Chromium `facet pull` installs rather than
shipping one.

## What it wraps

- **Node**: `22.21.0`, pinned in `[engine.node]` with the sha256 of
  nodejs.org's `node-v22.21.0-linux-x64.tar.gz`, the same runtime every
  node-engine package in the registry pins.
- **`playwright-core` `1.64.0`** and **`pdfjs-dist` `3.11.174`**, the two
  `[[engine.node.packages]]` entries: the lab's `^1.64.0` range pinned to the
  exact version with its `registry.npmjs.org` tarball and SRI integrity.
  playwright-core launches the pinned browser and never downloads one;
  pdfjs-dist reads page counts and text and renders placed PDFs inside that
  same browser through `pdfgrab.html`.
- **The pinned Chromium.** `facet pull deck` installs it once (~200 MB, shared
  by the three packages); the runner reads it from `FACET_BROWSER` — no host
  lookup, no download. Every raster — the per-page PNGs, the `deck.page`
  text check and the placed-PDF preview — comes from this Chromium or from the
  bundled pdf.js, never from a host tool install.

## The deck format

A deck is one HTML file named by `source`. It owns its geometry:

```css
@page { size: 1280px 720px; margin: 0; }
html, body { margin: 0; }
.slide { width: 1280px; height: 720px; break-after: page; }
.slide:last-child { break-after: auto; }
```

- **`@page` sets the slide size.** The PDF is rendered with
  `preferCSSPageSize: true`, so the CSS size wins over any default paper size.
- **One page break per slide.** A slide without a break merges with the next
  one and the page count drops; the last slide needs no break.
- **Self-contained.** Local fonts, images and stylesheets; the file is loaded
  through a `file://` URL, so keep the pieces beside it.

The runner loads the file, waits for `document.fonts.ready`, switches to
`emulateMedia({ media: "print" })` and calls `page.pdf` with
`printBackground: true` and `preferCSSPageSize: true`. It never measures the
content into one tall page.

## Outputs

- **`<name>.pdf`** — the paginated deck, one PDF page per slide, with the
  `document` kind and `application/pdf` mime.
- **`page-01.png`, `page-02.png`, ...** — one PNG per PDF page, screenshotted
  from the same Chromium run that wrote the PDF: the runner counts the pages
  with pdf.js, reads the `@page` size (or the laid-out scroll height over the
  page count) and clips one screenshot per page. The names are normalized to
  at least two digits so `page-01.png` is stable. Each PNG travels as its own
  asset beside the PDF — kind `image`, mime `image/png`, properties
  `{ page, width, height }` read from its header — so facet copies it out of
  the run and writes its own record.
- **`<name>.pdf.preview.json`** — the document preview:
  `{ "preview": 1, "kind": "document", "summary", "page_count", "pages" }`.
  Its page rasters are written under `preview/` (`pages` entries are
  `preview/page-01.png`, ...), cleared and recreated on every preview, so a
  preview never deletes, rewrites or renames the delivered PNGs beside the
  PDF. A person's preview opens the PDF itself in the system browser; there is
  no viewer server for a document.
- **`page-NN.png.preview.json`** — a page PNG previews as the image kind:
  `{ preview, kind, summary, name, prompt, seed, width, height }`.

`verify` counts the rendered `page-*.png` files beside the PDF — falling
back to the PDF's own page count from pdf.js when none are rendered, which is
the state a placed asset is in — compares the count with the record's
`page_count`, and stops with `runner_failed` on a mismatch. The verifier it
reports is `chromium-pdfjs`. A page PNG verifies on its own: it must be a PNG
whose header size matches the `width` and `height` its record carries (and in
the run's temp directory, before a record exists, the header alone), with the
`png` verifier. `facet check` re-runs both after a preview.

## One-page pieces

`deck.page` exports a one-page piece — an infographic or a poster written as
HTML + CSS + SVG — to a single-page PDF plus its `page-01.png`. It takes the
same `source`, `prompt` and `seed` inputs as `deck.slides`, but `source` is the
piece itself: no `@page` rule, no page breaks.

The render is the lab's default path, not the slides print path: the runner
loads the piece through a `file://` URL at a 1060px viewport, waits for
`networkidle` and `document.fonts.ready`, switches to **screen** media
(`emulateMedia({ media: "screen" })`), measures the content height
(`scrollHeight`, or the body's bottom edge plus its bottom margin when the
page is shorter than the viewport), and calls `page.pdf` with `printBackground`,
an explicit `width` of `1060px`, `height` of the measured height plus 2px, and
`pageRanges: "1"`. The same Chromium screenshot stage as `deck.slides` then
writes `page-1.png`, normalized to `page-01.png`, and the preview file carries
the core document shape `{ preview, kind, summary, page_count, pages }` with
`page_count: 1`.

Before exporting, the runner enforces three exact checks, each a plain failure
that facet reports as `runner_failed` naming the check:

- **`footer-sources`** — the piece must carry a `<footer>` or an element whose
  class mentions `footer`, `fuentes` or `sources`, with non-empty text. Every
  visible number needs its source in that footer.
- **`spanish-numbers`** — the rendered text is extracted through the bundled
  pdf.js text layer and the first five number runs not adjacent to ASCII
  letters are checked: a dot-decimal like `8.04` or a comma-thousands like
  `40,300` fails, while Spanish thousands dots (`1.200`) and comma decimals
  (`0,9`, `6,00`) pass.
- **`captioned-images`** — every `<img>` must sit inside a `<figure>` that also
  holds a non-empty `<figcaption>`; a piece with no `<img>` passes vacuously.

There is no `const DATA` requirement: the piece is plain HTML + CSS + SVG and
the checks above are the whole contract.

## The presenter runner

`deck.presenter` builds the speaking copy of the same deck: one source, speaker
view and notes attached per slide. It takes the same `source` and a `notes`
array of `{ page, text }` tables — one per slide, `page` a distinct 1-based
slide number — orders them by `page`, and writes two assets:

- **`<name>.present.html`** — the deck with local resources inlined as data
  URIs, plus the presenter CSS, `window.__PZ_NOTES__` and the presenter script
  injected before `</body>`. Kind `document`, mime `text/html`, properties
  `{ slides, notes }`.
- **`<name>.notes.md`** — the materialized companion, one non-empty `---`
  separated section per note in `page` order. Kind `text`, the generic
  viewer, properties `{ slides, notes }`.

A missing local image ref throws `runner_failed` naming the ref; a missing
video only warns on stderr with the
lab's `aviso` and never fails. The presenter files ship beside the runner in
`presenter/`, the same layout as the lab's `tools/presenter/`.

The runner never serves and never opens: file output only. Serving is the
core's job, and the core opens a document asset itself in the system browser.
The lab's `--open` flag stays out; `deck.presenter` has no equivalent.

Its preview writes `<asset>.preview.json`: `document` for
`<name>.present.html` with `page_count: 1` and an empty `pages` (a
self-contained HTML page is never rasterized), and a generic `text` preview
with `{ notes }` for `<name>.notes.md`.

## Environment

- **`FACET_BROWSER`** selects the pinned Chromium `facet pull` installs.
  `doctor` reports the resolved executable and its fix is `facet pull deck`.
- **`doctor` at quick depth** checks the node runtime and the Chromium; at
  full depth it renders a one-slide throwaway, so a broken browser fails
  before a real deck does. There is no external rasterizer check: page PNGs,
  page counts and text all come from the Chromium and the bundled pdf.js.
- **`pull` fetches the browser.** `pull` installs the pinned npm closure —
  playwright-core and pdfjs-dist — and the declared `[browser]` (Chromium
  158.0.8127.18, shared by the three packages).
