# Render invocation shapes

The lab's renderer is `tools/render.mjs`; `packages/deck/runner.js` ports its
two modes. The lab's source is
`/home/jheisonmblivecom/Academic/Deriverables/Grafics/tools/render.mjs`.

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
rasterizes each PDF page with the host `pdftoppm` into `page-01.png`,
`page-02.png`, …; `deck.pagina` writes a single `page-01.png`.

## Chrome resolution

The renderer tries, in order:

1. `CHROME_PATH`, when set;
2. `/usr/bin/google-chrome`;
3. `/usr/bin/chromium`;
4. `/usr/bin/chromium-browser`;
5. on macOS, `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.

If none exists the render fails with `No Chrome/Chromium found; set
CHROME_PATH.` No browser is ever downloaded. Before asking Chrome for a PDF the
renderer waits for `document.fonts.ready`, so a local font is laid out before
the page is measured.
