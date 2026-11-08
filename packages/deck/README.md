# deck

Build a slide deck from one HTML file into a paginated PDF and one PNG per
page. `deck.slides` is the presentation package: it owns the deck format and
the export, and wraps the host browser rather than shipping one.

## What it wraps

- **Node**: `22.21.0`, pinned in `[engine.node]` with the sha256 of
  nodejs.org's `node-v22.21.0-linux-x64.tar.gz`, the same runtime every
  node-engine package in the registry pins.
- **`playwright-core` `1.64.0`**, the first and only `[[engine.node.packages]]`
  entry: the lab's `^1.64.0` range, pinned to the exact version with its
  `registry.npmjs.org` tarball and SRI integrity. It launches the host browser
  and never downloads one.
- **The host Chromium.** The runner resolves it from `CHROME_PATH`, then
  `/usr/bin/google-chrome`, `/usr/bin/chromium`, `/usr/bin/chromium-browser`.
  There is no `[browser]` table: a node package's pull never fetches a browser,
  so the host executable is the whole browser story.
- **The host `pdftoppm`** from poppler-utils. The runner rasterizes the PDF's
  pages with it and never installs or bundles poppler.

## The deck format

A deck is one HTML file named by `fuente`. It owns its geometry:

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
- **`page-01.png`, `page-02.png`, ...** — one PNG per PDF page, rasterized
  beside the asset by the host `pdftoppm` after the PDF is written. The runner
  normalizes the names to at least two digits so `page-01.png` is stable.
- **`<name>.pdf.preview.json`** — the document preview:
  `{ "preview": 1, "kind": "document", "summary", "page_count", "pages" }`.
  A person's preview opens the PDF itself in the system browser; there is no
  viewer server for a document.

`verify` counts the rendered `page-*.png` files beside the asset — falling
back to the PDF's own `Pages:` count from `pdfinfo` when none are rendered,
which is the state a placed asset is in until `preview` rasterizes them —
compares the count with the record's `page_count`, and stops with
`runner_failed` on a mismatch.

## The presenter runner

`deck.presenter` builds the speaking copy of the same deck: one source, speaker
view and notes attached per slide. It takes the same `fuente` and a `notas`
array of `{ pagina, texto }` tables — one per slide, `pagina` a distinct 1-based
slide number — orders them by `pagina`, and writes two assets:

- **`<name>.present.html`** — the deck with local resources inlined as data
  URIs, plus the presenter CSS, `window.__PZ_NOTES__` and the presenter script
  injected before `</body>`. Kind `document`, mime `text/html`, properties
  `{ slides, notes }`.
- **`<name>.notes.md`** — the materialized companion, one non-empty `---`
  separated section per note in `pagina` order. Kind `text`, the generic
  viewer, properties `{ slides, notes }`.

A missing non-video ref (an image or stylesheet beside the deck) throws
`runner_failed` naming the ref; a missing video only warns on stderr with the
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

- **`CHROME_PATH`** selects the host browser. Without it the runner still finds
  the three standard Linux paths; `doctor` reports the resolved executable and
  its fix is `export CHROME_PATH=/usr/bin/google-chrome`.
- **poppler-utils** provides `pdftoppm` and `pdfinfo`. `doctor` runs
  `pdftoppm -v`; its fix is `sudo apt-get install -y poppler-utils`.
- **`doctor` at full depth** renders a one-slide throwaway, so a broken browser
  or a missing rasterizer fails before a real deck does.
- **No pull ever fetches the browser.** `pull` installs the pinned npm closure
  and any declared `[browser]`; deck declares neither a browser nor a browser
  asset.
