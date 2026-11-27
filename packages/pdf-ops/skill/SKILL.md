---
name: pdf-ops
description: Deterministic CPU PDF merge, split, compress, and rasterize with pikepdf and pypdfium2 — combine PDFs, extract pages, linearize, and render PNGs.
---
# pdf-ops

`pdf-ops` manipulates PDFs deterministically on CPU with `pikepdf`
(QPDF) for structure and `pypdfium2` (PDFium) for rendering:

- `pdf-ops.merge` concatenates 2+ PDFs into `<name>.pdf`, in order.
- `pdf-ops.split` extracts a page selection into `<name>.pdf`.
- `pdf-ops.compress` recompresses streams and linearizes into `<name>.pdf`.
- `pdf-ops.rasterize` renders pages into `<name>-page-01.png`, etc.

## When to use

- When a piece needs pages combined, extracted, shrunk, or seen as
  images — and nothing heavier: no OCR, no text reflow, no generation.
- When a reviewer must look at a PDF: `rasterize` at 150 dpi gives
  readable page PNGs the image viewer shows inline.
- When the work is heavier — scanned-page OCR, layout analysis, form
  filling — leave it to a dedicated document package; `pdf-ops` only
  moves, squeezes, and pictures pages.

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

`pdf` is an array of 2+ tables, each with a `path` resolved relative to
the piece file. Every capability takes a `name` matching
`^[a-z0-9][a-z0-9-]*$`; document capabilities write `<name>.pdf`.

```toml
capability = "pdf-ops.split"

[inputs]
pdf = "doc.pdf"
pages = "1-3,5"
name = "excerpt"
```

`pages` is a 1-based inclusive selection: single pages (`5`), ranges
(`1-3`), or comma-separated mixes (`1-3,5`). Out-of-range pages fail
the piece. `compress` takes only `pdf` and `name`.

```toml
capability = "pdf-ops.rasterize"

[inputs]
pdf = "doc.pdf"
name = "doc-shots"
pages = "1-2"
dpi = 150
```

`rasterize` writes one PNG per page as `<name>-page-01.png`, in page
order. `pages` is optional (renders every page when omitted); `dpi`
is an integer from 72 to 300, defaulting to 150.

## Judging the result

`verify` re-opens every produced PDF with `pikepdf` and demands the
exact expected page count: the sum of the inputs for `merge`, the
selection length for `split`, the input count for `compress`. A
wrong count fails. For `rasterize` it demands the expected PNG count
with positive Pillow dimensions on each. `preview` writes the
document kind's fields for each PDF — `page_count` plus per-page PNGs
rendered at 150 dpi — and the image kind's fields for each rasterized
PNG: `prompt` is `pdf-ops rasterize of <stem>`, `seed` 0 because the
render is deterministic and the seed only labels the record, and
`width`/`height` measured from the file.

## Pitfalls

- **`pdf` is tables, not strings.** `merge` takes `[[inputs.pdf]]`
  tables each with a `path`; an array of bare strings fails validation.
- **Pages are 1-based and inclusive.** `1-3` keeps pages 1, 2, and 3;
  there is no page 0, and `3-1` is rejected — write `1-3`.
- **Duplicates collapse.** `1,1-2` renders pages 1 and 2 once each, in
  first-seen order; repeat a page by running the piece twice instead.
- **Compress may not shrink.** Already-compressed PDFs can grow
  slightly after linearization; the guarantee is structural validity
  and the same page count, not fewer bytes.
- **Rasterize names carry the page.** The asset is
  `<name>-page-01.png` with 2 digits; a PDF with 100+ pages still
  numbers `100` plainly — sort by the numeric suffix, not the string.

Sources for these rules, with their licences, are in
`skill/references/sources.md`.
