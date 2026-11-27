# PDF Ops

Deterministic CPU PDF manipulation with `pikepdf` (MPL-2.0) for
structure and `pypdfium2` (Apache-2.0) for rendering — no models, no
GPU. `pdf-ops.merge` concatenates 2+ PDFs into `<name>.pdf` in the
given order; `pdf-ops.split` extracts a 1-based inclusive page
selection (`1-3,5`) into `<name>.pdf`; `pdf-ops.compress`
recompresses streams and linearizes into `<name>.pdf` for fast web
viewing; `pdf-ops.rasterize` renders pages into `<name>-page-01.png`
files at 72–300 dpi (default 150) for visual inspection.

## When to use

- When a piece needs pages combined, extracted, shrunk, or seen as
  images — and nothing heavier: no OCR, no text reflow, no generation.
- When a reviewer must look at a PDF: `rasterize` at 150 dpi gives
  readable page PNGs the image viewer shows inline.

## Pieces

```toml
capability = "pdf-ops.merge"

[[inputs.pdf]]
path = "a.pdf"

[[inputs.pdf]]
path = "b.pdf"

[inputs]
name = "combined"
```

`pdf` is an array of 2+ tables, each with a `path` resolved relative
to the piece file. `split` and `compress` take a single `pdf` path
plus `name`; `split` also takes `pages` (`1-3,5`, 1-based inclusive).
`rasterize` takes `pdf`, `name`, an optional `pages` selection
(every page when omitted), and an optional `dpi` (72–300, default
150), writing `<name>-page-01.png` per page in order.

## Judging the result

`verify` re-opens every produced PDF with `pikepdf` and demands the
exact expected page count (the inputs' sum for `merge`, the selection
length for `split`, the input count for `compress`); for `rasterize`
it demands the expected PNG count with positive Pillow dimensions on
each. `preview` writes the document kind's fields per PDF
(`page_count` plus per-page PNGs) and the image kind's fields per
rasterized PNG. `doctor` checks the three imports, and at `full`
depth splits page 1 off a tiny 2-page PDF and rasterizes it to PNG.
See `skill/SKILL.md` for the full rules.
