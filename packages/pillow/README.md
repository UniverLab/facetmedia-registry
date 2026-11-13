# pillow

Base image operations on CPU with Pillow: `facet run pillow.base` converts
a still between PNG, JPEG and WebP, resizes it exact or
aspect-preserving, and lays contact sheets with white dividers for review
boards. CPU only, no GPU flag, no models — the whole package is a pinned
Pillow in a python-env, so it is the lightest image package in the
registry. Heavy image work (cutouts, relighting, generation) belongs to
the specialized packages; this one is the base layer.

## Capability and pieces

`pillow.base` — image kind:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `image` | path | yes | — | Source image, resolved relative to the piece |
| `operations` | array | yes | — | One table per op, min 1, applied in order in memory |

Each `operations` item carries `op` (`convert`,
`resize`, `sheet`; required) plus the fields of its op:

| Op | Fields | Notes |
|----|--------|-------|
| `convert` | `format` (png/jpeg/webp, required), `mode` (RGB/RGBA/L, optional) | Writes `.png`, `.jpg` or `.webp`; jpeg output is always RGB — an alpha source with no `mode` is composited onto white, and `RGBA`+`jpeg` is rejected |
| `resize` | `width`, `height` (integers >= 1, at least one) | Both dims resize exact (aspect may change); one dim preserves aspect, Lanczos, rounded, minimum 1; keeps the current extension |
| `sheet` | `columns`, `rows` (integers >= 1, both required) | `floor(W/columns)` x `floor(H/rows)` tiles from the top-left, remainder dropped, row-major into one png with 2 px white dividers and no outer border |

`run` writes one asset per op into the output directory (the piece
directory by default): `<image-stem>-<i>-<op>.<ext>` with `i` the
1-based op position. Each record carries the image kind, the measured
`width`/`height`, seed 0 — the ops are deterministic, so the seed only
labels the record — and `params`/`inputs` naming the `image`.

## Verification and preview

`verify` re-opens each written file with Pillow — it must be a readable
image whose suffix, mode and pixel size match a fresh in-memory pass of
the same ops. `preview` writes the image kind's fields per asset matching
`schemas/preview/image.schema.json`: `prompt` is
`pillow <op> of <image-stem>`, `seed` 0, `width`/`height` measured
from the file.

`facet doctor pillow` runs one quick check — Pillow imports at exactly the
pinned 13.0.0 — and a `full` depth adds a 2x2 PNG encode/decode roundtrip.

## Licences

Pillow is MIT-CMU (Jeffrey A. Clark and contributors); the manifest
records it. The package itself is Apache-2.0 like the rest of the
registry tooling.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `pillow.base` — `examples/base.toml`: `facet example pillow.base --run`
