# charts

Publication-grade editorial data charts on CPU: `charts.render` reads a
tabular data file — a local `.csv` (UTF-8, comma-delimited with a
header row) or a `.json` file holding a top-level array of row objects
— and renders one series with matplotlib on the headless Agg backend
to a verified PNG or SVG, with Pillow checking the raster side. CPU
only, no GPU flag, no models — the whole package is a pinned
matplotlib plus Pillow in a python-env, so it is the lightest
presentation package in the registry.

## Capability and pieces

`charts.render` — image kind:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `data` | path | yes | — | Source table, resolved relative to the piece: `.csv` or `.json` |
| `name` | string | yes | — | Asset base name, `^[a-z0-9][a-z0-9-]*$`; writes `<name>.png` or `<name>.svg` |
| `chart` | enum | yes | — | `bar`, `barh`, `line` or `scatter` |
| `title` | string | yes | — | Chart title, drawn above the axes |
| `subtitle` | string | no | — | Subtitle under the title in muted ink |
| `source` | string | no | — | Footer attribution line under the axes |
| `x` | string | yes | — | Column header (CSV) or key (JSON) for x values / labels |
| `y` | string | yes | — | Column header (CSV) or key (JSON) for numeric y values |
| `format` | enum | no | `png` | `png` raster or `svg` vector |
| `accent` | string | no | `#E8C547` | Single `#rrggbb` data color; the rest stays neutral |
| `width-px` | integer | no | `1200` | Output width, 400–3840 |
| `height-px` | integer | no | `675` | Output height, 300–2160 |

Every row must carry the `x` and `y` keys; `y` must parse as a finite
number. Scatter needs numeric `x`; line takes numeric `x` when every
value parses and ordered category strings otherwise; bars use string
labels. Empty data, an unsupported extension, a missing column or a
non-numeric `y` fails `run` with `ValueError`.

`run` renders at `width-px/100` by `height-px/100` inches at 100 dpi so
PNG pixels match the request exactly, and stamps the SVG root and
viewBox with the requested size. The editorial style is fixed: no
top/right spines, a hairline grid behind the data, generous margins,
title plus subtitle and source footer, and direct value labels on
`bar`/`barh` at twelve bars or fewer.

`verify` re-opens the asset — PNG must decode, match the size within
2 px and use more than one color; SVG must parse with an `svg` root, a
non-zero byte size and at least one drawing primitive. `preview`
writes `<asset>.preview.json` in the image schema with
`prompt = "<chart>: <title>"` and `seed = 0` (PNG size measured with
Pillow, SVG size from the request). `doctor` checks the matplotlib and
Pillow imports, and at full depth renders a tiny 3-bar PNG in a temp
dir at exactly 400x300.

See `skill/SKILL.md` for the data-viz rules (choose the chart by
comparison, zero chartjunk, one accent color, always cite the data
source) and `examples/render.toml` for a runnable piece.
