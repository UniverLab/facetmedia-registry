---
name: deck
description: Author slides as HTML with a CSS @page size and one page break per slide, exported to a paginated PDF plus one PNG per page.
---
# Deck

`deck.slides` turns one slide HTML file into a paginated PDF and one PNG per
page. The HTML owns the page geometry: an `@page` rule sets each slide's size
and a page break separates the slides. The runner waits for the fonts, switches
to print media and lets the `@page` rule decide the PDF pages, then rasterizes
every page with the host `pdftoppm`.

## When to use

- When a piece is a slide deck that is quicker to iterate as HTML than as a
  layout language: titles, code, diagrams and images on fixed-size slides.
- When every slide is one `@page`-sized page with an explicit page break, so the
  PDF's page count equals the slide count.
- When the host has a Chromium (resolved from `CHROME_PATH`, then
  `/usr/bin/google-chrome`, `/usr/bin/chromium`, `/usr/bin/chromium-browser`)
  and `pdftoppm` from poppler-utils; otherwise `doctor` fails before a run.

## Pieces

```toml
[inputs]
fuente = "slides.html"
prompt = "A five-slide tour of the release"
seed = 0
```

`fuente` is the slide HTML, resolved relative to the piece. It carries one
`@page` rule for the slide size, for example `@page { size: 1280px 720px; margin:
0; }`, and one page break per slide (`.slide { break-after: page; }`, with the
last slide left without a break). Keep it self-contained: local fonts, images
and stylesheet, no remote URL.

## Judging the result

`verify` counts the rendered `page-*.png` files beside the asset — or the
PDF's own `Pages:` count from `pdfinfo` when none are rendered — and compares
them with the `page_count` the record holds; a mismatch stops the check with
`runner_failed`. The preview file carries `preview`, `kind`, `summary`,
`page_count` and `pages`, and a person's preview opens the PDF itself.

## Pitfalls

- A slide without `@page` sizing exports at the browser's default page size; set
  the size explicitly.
- A missing page break merges two slides onto one PDF page and the page count
  drops.
- The page PNGs are `page-01.png`, `page-02.png`, ...; they are rasterized by
  the host poppler, never by a full-page browser screenshot.
- No browser is downloaded: `CHROME_PATH` must name the host executable.
