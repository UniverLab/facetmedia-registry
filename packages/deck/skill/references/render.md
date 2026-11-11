# Render invocation shapes

`packages/deck/runner.js` renders in two modes.

```bash
node tools/render.mjs <file>.html               # one tall page, content height
node tools/render.mjs <file>.html --png         # plus <file>.png
node tools/render.mjs <file>.html --paged       # one PDF page per CSS @page
node tools/render.mjs <file>.html --paged --png # deck: PDF + page-*.png
node tools/render.mjs <file>.html --png --scale 2 --width 1060
```

- `<file>.html` is the only positional argument; it is resolved and must exist.
- `--paged` switches the page to print media and passes
  `preferCSSPageSize: true` to Chrome's PDF. The CSS `@page` size decides each
  page. Without it the render is a single page whose height is the measured
  content height, limited to page range `1`.
- `--png` adds a screenshot of the screen-media page at the same `--width` and
  the measured height (capped at 16000 px).
- `--scale` is the device scale factor (default `2`); `--width` is the viewport
  width in CSS pixels (default `1060`).

Output names come from the input's base name in the input's own directory:
`<base>.pdf`, and `<base>.png` with `--png`. `deck.slides` additionally
screenshots each PDF page inside the same headless Chromium run — the page
count comes from the bundled pdf.js and the `@page` size (or the laid-out
scroll height over the page count) sets each clip — into `page-01.png`,
`page-02.png`, …; `deck.pagina` writes a single `page-01.png`. A placed PDF
with no source HTML is rasterized the same way through `pdfgrab.html`, which
renders it with pdf.js inside a fresh headless Chromium run.

## Chrome resolution

The renderer launches `FACET_BROWSER` — the pinned Chromium `facet pull`
installs once (~200 MB, shared by the three packages); no host lookup, no
download. When `FACET_BROWSER` is unset or not executable the render fails
with `FACET_BROWSER is not set or not executable; run facet pull deck`.
Before asking Chrome for a PDF the renderer waits for `document.fonts.ready`,
so a local font is laid out before the page is measured.
