---
name: deck
description: Author slides as HTML with a CSS @page size, exported to a paginated PDF, and build a presenter file with speaker view and per-slide notes.
---
# Deck

`deck.slides` turns one slide HTML file into a paginated PDF and one PNG per
page. The HTML owns the page geometry: an `@page` rule sets each slide's size
and a page break separates the slides. The runner waits for the fonts, switches
to print media and lets the `@page` rule decide the PDF pages, then rasterizes
every page with the host `pdftoppm`.

`deck.pagina` turns one piece of HTML — an infographic or a poster — into a
single-page PDF and its page PNG. The runner renders it with screen media and
the content's measured height, then checks the piece's footer, its numbers and
its image captions before exporting.

`deck.presenter` builds the same deck for speaking: it attaches one speaker
note per slide, inlines the local resources, injects the presenter view and
writes `<base>.present.html` plus its `<base>.notes.md` companion. It never
serves and never opens anything; facet opens a document asset itself.

The invocation shapes are in `references/render.md`, the `@page` snippets in
`references/page.md` and the presenter file shapes in `references/presenter.md`.
A complete approved one-page piece — HTML, PDF and PNG — is in
`examples/modelos-de-lenguaje.*`.

## When to use

- **Slides** (`deck.slides`) when a talk is quicker to iterate as HTML than as
  a layout language: titles, code, diagrams and images on fixed-size slides.
  Every slide is one `@page`-sized page with an explicit page break, so the
  PDF's page count equals the slide count. See `references/page.md`.
- **Presenter** (`deck.presenter`) when the same deck has to be spoken, not
  just read: one note per slide, a speaker view with the next slide and the
  note, and a single self-contained file with its images inlined.
- **One-page piece** (`deck.pagina`) when the deliverable is an infographic or
  a poster: one page whose height the content decides, not a deck of slides.
  It is the same HTML + CSS + SVG as a slide, without `@page` and without
  breaks. Start from `examples/modelos-de-lenguaje.html`.
- HTML + CSS + SVG on headless Chrome is one language for print, screen and
  video, diffable in git, and renders in a cycle of export, screenshot and
  correction, with nothing extra to install. Choose it when the piece is
  visual and one or a few pages.
- Do **not** choose it for long documents with real pagination, footnotes,
  indexes or a bibliography: Chrome paginates poorly there. A deck is short by
  nature, so it fits; a report does not.
- For the charts inside a piece, a declarative specification (Vega-Lite, run
  through `vl-convert`) makes fewer mistakes than SVG written by hand when the
  chart is a standard one: bars, lines, a scatter, a Cartesian grid with axes
  and a legend. Hand-written SVG wins in editorial pieces made to measure — an
  annotated diagram, a bespoke shape, a chart that is part of the layout — where
  a declarative default fights the design.
- The host must have a Chromium (resolved from `CHROME_PATH`, then
  `/usr/bin/google-chrome`, `/usr/bin/chromium`, `/usr/bin/chromium-browser`)
  and `pdftoppm` from poppler-utils; otherwise `doctor` fails before a run.

## Pieces

```toml
[inputs]
fuente = "slides.html"
prompt = "A five-slide tour of the release"
seed = 0
```

`deck.slides` takes `fuente` (the slide HTML, resolved relative to the piece),
`prompt` (the brief the deck was authored from) and `seed`. `fuente` carries one
`@page` rule for the slide size, for example `@page { size: 1280px 720px; margin:
0; }`, and one page break per slide (`.slide { break-after: page; }`, with the
last slide left without a break). Keep it self-contained: local fonts, images
and stylesheet, no remote URL.

`deck.pagina` takes the same `fuente`, `prompt` and `seed` inputs, but `fuente`
is a one-page piece rather than a deck: no `@page` rule and no page breaks. The
runner measures the content height in screen media and exports exactly one PDF
page plus `page-01.png`. Before exporting it refuses the piece when it lacks a
`<footer>` or `footer`/`fuentes`/`sources` element with text (`footer-sources`),
when an `<img>` sits outside a `<figure>` with a non-empty `<figcaption>`
(`captioned-images`), or when the rendered text carries an English-style number
like `8.04` or `40,300` (`spanish-numbers`); each failure stops the run with
`runner_failed` naming the check.

```toml
[inputs]
fuente = "slides.html"
notas = [{ pagina = 1, texto = "Welcome" }, { pagina = 2, texto = "The result" }]
```

`deck.presenter` takes the same `fuente` and one `notas` table per slide, with
`pagina` (1-based slide number, distinct) and `texto` (the speaker note). It
orders the tables by `pagina`, inlines the local image refs beside the deck,
and writes two outputs: `<base>.present.html` (the deck plus speaker
view and notes) and `<base>.notes.md` (the `---` separated companion). The
presenter files ship beside the runner under `presenter/`. The exact file
shapes are in `references/presenter.md`.

**Data first.** Gather every figure with its source before designing. If a
figure changes over time (versions, prices, user counts), look it up; never
write it from memory. Every visible number carries its source in the footer.

**Keep the data in a `DATA` block.** All numbers, labels and rows live in one
`const DATA = { … }` at the top of the script, apart from the code that draws.
The drawing code reads `DATA`; it never carries a literal figure. Changing a
number is then a one-line edit, and the block is what a reviewer checks against
the sources.

**Numbers, labels and text.** Format every number in Spanish with
`toLocaleString('es')`: `1.200`, `0,3`, and `6,00` on dimensions. Every colour
mark in a chart carries a text label near it; colour is never the only cue.
Text and figures go in HTML or SVG, never baked into a raster or generated
image.

**Page geometry.** A deck sets its slide size with `@page` and breaks after
every slide but the last. A one-page piece sets no `@page` and owns its height
through the content. Copy the snippets from `references/page.md`.

## Judging the result

**Export, review, and repeat — never call a piece done unexported and unseen.**

1. Export with `deck.slides`, `deck.pagina` or `deck.presenter`. A deck or
   one-page run writes `<base>.pdf` and one `page-NN.png` per page beside the
   asset; a presenter run writes `<base>.present.html` and `<base>.notes.md`.
2. Open the PNG (or a screenshot) and check for overlaps, clipped text,
   overflow and hierarchy.
3. For anything that is not an image — PDF pages, a deck, an assembled
   presenter file — turn it into images with the lab's
   `tools/visualize.sh <archivo> [páginas]`, which leaves them in
   `<archivo>.viz/`, and inspect those. If your harness cannot see images,
   verify what is measurable (page count, file size, console errors) and ask a
   person to review.
4. Correct and repeat from step 1. A figure that changed means re-exporting.

`verify` counts the rendered `page-*.png` files beside the asset — or the PDF's
own `Pages:` count from `pdfinfo` when none are rendered — and compares them
with the `page_count` the record holds; a mismatch stops the check with
`runner_failed`. The preview file carries `preview`, `kind`, `summary`,
`page_count` and `pages`, and a person's preview opens the PDF itself.

`deck.presenter`'s `verify` checks the `__PZ_NOTES__` array length against the
`notas` count, the `---` sections in `notas.md` against the same count and
order, and that every `pagina` is distinct and inside the deck; each failure
stops the check with `runner_failed` naming the check.

## Pitfalls

- A slide without `@page` sizing exports at the browser's default page size; set
  the size explicitly.
- A missing page break merges two slides onto one PDF page and the page count
  drops.
- A one-page piece that declares `@page` is measured as a deck and loses its
  single measured page; leave `@page` out of `deck.pagina`.
- A `DATA` block copied into the drawing code, or a figure written from memory,
  is the usual source of a wrong number. Gather first and keep one block.
- English-style numbers (`8.04`, `40,300`) fail `deck.pagina` with
  `runner_failed`; format with `toLocaleString('es')`.
- The page PNGs are `page-01.png`, `page-02.png`, ...; they are rasterized by
  the host poppler, never by a full-page browser screenshot.
- Hand-writing SVG for a standard chart costs more corrections than a
  Vega-Lite spec; a declarative default pulled into an editorial piece that
  needs a bespoke shape costs more than drawing it. Pick per chart, not per
  piece.
- No browser is downloaded: `CHROME_PATH` must name the host executable.
- In the presenter build, a missing image or stylesheet ref stops the run with
  `runner_failed`; a missing video only prints the lab's `aviso` and never
  fails, so the video file has to travel beside the deck.
- The presenter never serves and never opens: there is no `--open` flag. A
  person opens the `document` asset through facet's own preview.
