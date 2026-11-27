---
name: vtracer
description: Trace crisp raster images (PNG, JPEG, WebP) into clean deterministic SVGs on CPU with VisionCortex VTracer.
---
# vtracer

`vtracer.trace` turns one crisp raster image into a clean deterministic
SVG on CPU: flat logos, icons, diagrams and silhouettes become a handful
of smooth paths that scale forever and stay tiny. The trace is
deterministic given the inputs, so `seed` is 0 and only labels the
record — re-running the same piece byte-compares.

## When to use

- When the piece needs a logo, icon, diagram or silhouette as vectors:
  crisp edges and flat fills trace into a few smooth paths.
- When the output must stay small and sharp at any size: an SVG of flat
  shapes beats a PNG the moment it scales.
- When the source is already clean: screenshots of line art, generated
  flat illustrations, scanned ink with the paper cleaned first.

Trace when the shapes are the message; redraw in SVG by hand when the
pixels are. A trace follows the raster faithfully — wobbles, noise and
all — so a hand-drawn mark with intent (a wordmark, a mascot, a chart
with exact geometry) deserves redrawing, not tracing. Trace the
silhouette, redraw the soul.

## Pieces

```toml
capability = "vtracer.trace"

[inputs]
image = "logo.png"
name = "logo"
colormode = "color"
mode = "spline"
filter-speckle = 4
color-precision = 6
```

`image` is the raster to trace (PNG, JPEG or WebP), resolved relative
to the piece file. `name` is the asset base name (`[a-z0-9][a-z0-9-]*`);
the runner writes `<name>.svg` into the output directory.

`colormode` is `color` (default, full-colour paths) or `binary` (a
two-tone black-and-white silhouette). `mode` fits the paths: `spline`
(default, smooth curves), `polygon` (straight segments) or `none`
(pixel-aligned steps for pixel art).

`filter-speckle` (default 4, 0–128) drops isolated speckles smaller than
that many pixels; `color-precision` (default 6, 1–8) is significant bits
per channel — fewer merge near colours into one path.

## Judging the result

`verify` parses each SVG with ElementTree: valid XML, an `svg` root,
non-zero bytes and at least one `<path` element, with the measured
`path_count` and `bytes` in the metrics. `preview` writes the image
kind's fields for each asset — `prompt` is `trace of <image-stem>`,
`seed` 0 because the trace is deterministic, `width`/`height` measured
from the source raster — matching `schemas/preview/image.schema.json`.

A person judges the trace by eye at two zooms: at 100 % the SVG should
match the raster's edges, and zoomed in the curves should stay smooth
with no stair-steps (`mode = "spline"`) and no stray speck paths around
the shapes (raise `filter-speckle`). Count the paths: a logo with more
paths than shapes is tracing noise — simplify the source or lower
`color-precision`.

`facet doctor vtracer` runs two checks: `imports` proves vtracer and
Pillow import with versions, and the full depth's `trace` converts a
tiny synthetic two-block PNG and parses the SVG for a path. Every
failing check names `facet pull vtracer` as its fix.

## Pitfalls

- **Photographs trace badly.** Continuous tones, gradients, grain and
  soft shadows explode into thousands of paths and megabytes of SVG.
  Trace flat art only; for a photo use `rembg` for the silhouette or
  redraw the shapes — never trace the photo itself.
- **JPEG halos become shapes.** Lossy compression rings around edges
  trace as real bands, so prefer PNG or WebP sources; when only a JPEG
  exists, raise `filter-speckle` and accept softer corners.
- **`binary` needs contrast.** Two-tone mode thresholds the image, so a
  mid-grey-on-grey source silhouettes wrongly — raise the source
  contrast first, or stay in `color` and pick the paths apart after.
- **Small text does not survive.** Glyphs under ~16 px trace as blobs;
  set that type as real SVG `<text>` after the trace instead.
- **Transparency flattens.** The trace keeps no alpha channel:
  transparent margins trace against black, so composite onto the target
  background first when the edges touch transparency.

Sources for these rules, with their licences, are in
`skill/references/sources.md`.
