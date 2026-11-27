---
name: charts
description: Publication-grade editorial data charts (bar, barh, line, scatter) from CSV or JSON to verified PNG or SVG with matplotlib on CPU.
---
# charts

`charts.render` turns one tabular data file into one publication-grade
editorial chart: vertical bars, horizontal bars, a line or a scatter,
drawn with matplotlib on the headless Agg backend and checked by Pillow
(PNG) or an SVG parse before it is accepted. CPU only, no GPU flag, no
models — the whole package is a pinned matplotlib plus Pillow in a
python-env.

## When to use

- When a piece needs one clean data graphic for print or screen: a
  comparison of a few categories, a trend over an ordered x, or a
  relationship between two numbers.
- When the chart must be verifiable: the runner checks PNG dimensions
  and non-uniform pixels, or the SVG root and its drawing primitives,
  and writes an image-kind preview per asset.
- When the data is heavier — many series, interactivity, maps — leave
  it to a heavier tool; `charts.render` draws one series with one
  accent color.

## Pieces

```toml
[inputs]
data = "sales.csv"
name = "sales-q1"
chart = "bar"
title = "Q1 sales"
subtitle = "Thousands of units"
source = "Lab ledger, 2026"
x = "month"
y = "sales"
format = "png"
```

`data` is the table, resolved relative to the piece file: a local
`.csv` (UTF-8, comma-delimited, first row is the header) or a `.json`
file holding a top-level array of row objects. Every row must carry the
`x` and `y` keys; `y` must parse as a finite number.

`name` is the asset base name (`[a-z0-9][a-z0-9-]*`); the runner writes
`<name>.png` for `format = "png"` or `<name>.svg` for `"svg"`.
`chart` is `bar`, `barh`, `line` or `scatter` (required). `title` is
required; `subtitle` and `source` (the footer attribution line) are
optional. `x` and `y` name the exact column header (CSV) or key (JSON
object): `y` is always the numeric series; `x` is the category label
for bars, the number for a scatter, and either for a line — numeric
when every value parses, ordered categories otherwise.

Sizing and color: `width-px` (default 1200, 400–3840) and `height-px`
(default 675, 300–2160) set the PNG pixels and the SVG width, height
and viewBox. `accent` (default `#E8C547`) is the single `#rrggbb` data
color; axes, grid and text stay neutral ink, paper and hairline grid
tokens.

`run` renders headless at `width-px` by `100` by `height-px` by `100`
inches at 100 dpi, so PNG pixels match the request exactly. `verify`
re-opens the asset: PNG must decode and match the size within 2 px and
must not be one flat color; SVG must parse with an `svg` root, a
non-zero byte size and at least one drawing primitive. `preview`
writes `<asset>.preview.json` in the image schema with
`prompt = "<chart>: <title>"` and `seed = 0`. `doctor` checks the
matplotlib and Pillow imports, and at full depth renders a tiny 3-bar
PNG in a temp dir at exactly 400x300.

## Judging the result

- Open the PNG or SVG: one series in the accent color, no top or right
  spine, a hairline grid behind the data, and no shadows or 3D effects.
- Bars at twelve or fewer carry direct value labels; more than that
  stays clean without them. Zero chartjunk: nothing on the page that
  carries no data.
- The title reads first, the subtitle (when given) sits under it in
  muted ink, and the `source` line credits the data under the axes.
- The preview JSON validates against
  `schemas/preview/image.schema.json` with the chart-and-title prompt.

## Pitfalls

- A missing column or a non-numeric `y` fails `run` with `ValueError`:
  check the header spelling and that every row carries both keys.
- A scatter with non-numeric `x` fails: scatters need two numbers, use
  `line` or `bar` for categories.
- CSV must be UTF-8 with a comma delimiter and a header row; a
  delimiter-less export or a headerless file reads as one bad column.
- JSON must be a top-level array of objects: a bare object or an empty
  array is refused before anything renders.
- `name` must match `^[a-z0-9][a-z0-9-]*$` and `accent` must be
  `#rrggbb`; anything else is rejected so the asset name and the SVG
  stay predictable.
