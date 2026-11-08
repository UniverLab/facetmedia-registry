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
orders the tables by `pagina`, inlines local images and stylesheet refs beside
the deck, and writes two outputs: `<base>.present.html` (the deck plus speaker
view and notes) and `<base>.notes.md` (the `---` separated companion). The
presenter files ship beside the runner under `presenter/`.

## Judging the result

`verify` counts the rendered `page-*.png` files beside the asset — or the
PDF's own `Pages:` count from `pdfinfo` when none are rendered — and compares
them with the `page_count` the record holds; a mismatch stops the check with
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
- The page PNGs are `page-01.png`, `page-02.png`, ...; they are rasterized by
  the host poppler, never by a full-page browser screenshot.
- No browser is downloaded: `CHROME_PATH` must name the host executable.
- In the presenter build, a missing image or stylesheet ref stops the run with
  `runner_failed`; a missing video only prints the lab's `aviso` and never
  fails, so the video file has to travel beside the deck.
- The presenter never serves and never opens: there is no `--open` flag. A
  person opens the `document` asset through facet's own preview.
