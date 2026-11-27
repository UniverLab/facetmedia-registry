# vtracer

Crisp raster images traced into clean deterministic SVGs on CPU with
[VisionCortex VTracer](https://github.com/visioncortex/VTracer) (MIT):
`facet run vtracer.trace` turns one PNG, JPEG or WebP into `<name>.svg`,
with smooth spline paths for flat logos, icons and diagrams. CPU only,
no weights to pull — the pinned `vtracer` wheel does the whole trace.

## Capabilities and pieces

`vtracer.trace` — raster-to-SVG vectorization, image kind:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `image` | path | yes | — | PNG, JPEG or WebP, resolved relative to the piece |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.svg` |
| `colormode` | enum | no | `color` | `color` or `binary` (two-tone silhouette) |
| `mode` | enum | no | `spline` | `spline`, `polygon` or `none` (pixel steps) |
| `filter-speckle` | integer | no | `4` | 0–128; drops speckles below this size |
| `color-precision` | integer | no | `6` | 1–8; fewer merge near colours |

`run` writes exactly one asset, `<name>.svg` (mime `image/svg+xml`).
The record carries the source raster's measured `width`/`height` in
`properties` and `seed` 0 — the trace is deterministic given the
inputs, so the seed only labels the record.

Trace flat art, not photographs: continuous tones, gradients and grain
explode into thousands of paths, while flat shapes trace into a handful
that stay sharp at any zoom. JPEG halos trace as real bands, so prefer
PNG or WebP sources; small text (under ~16 px) traces as blobs and
belongs in real SVG `<text>` after the trace.

## Verification and preview

`verify` parses each SVG with ElementTree: valid XML with an `svg`
root, non-zero bytes and at least one `<path` element, with
`path_count` and `bytes` in the metrics. `preview` writes the image
kind's fields for each asset — `prompt` is `trace of <image-stem>`,
`seed` 0, `width`/`height` measured from the source raster — matching
`schemas/preview/image.schema.json`.

`facet doctor vtracer` runs two checks: `imports` proves vtracer and
Pillow import with versions, and the full depth's `trace` converts a
tiny synthetic two-block PNG (which beats the default speckle filter)
and parses the SVG for a path. Every failing check names
`facet pull vtracer` as its fix.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `vtracer.trace` — `examples/trace.toml`: `facet example vtracer.trace --run`
