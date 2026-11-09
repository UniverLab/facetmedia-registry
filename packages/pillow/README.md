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
| `imagen` | path | yes | — | Source image, resolved relative to the piece |
| `operaciones` | array | yes | — | One table per op, min 1, applied in order in memory |

Each `operaciones` item carries `operacion` (`convertir`,
`redimensionar`, `hoja`; required) plus the fields of its op:

| Op | Fields | Notes |
|----|--------|-------|
| `convertir` | `formato` (png/jpeg/webp, required), `modo` (RGB/RGBA/L, optional) | Writes `.png`, `.jpg` or `.webp`; jpeg output is always RGB — an alpha source with no `modo` is composited onto white, and `RGBA`+`jpeg` is rejected |
| `redimensionar` | `ancho`, `alto` (integers >= 1, at least one) | Both dims resize exact (aspect may change); one dim preserves aspect, Lanczos, rounded, minimum 1; keeps the current extension |
| `hoja` | `columnas`, `filas` (integers >= 1, both required) | `floor(W/columnas)` x `floor(H/filas)` tiles from the top-left, remainder dropped, row-major into one png with 2 px white dividers and no outer border |

`run` writes one asset per op into the output directory (the piece
directory by default): `<imagen-stem>-<i>-<operacion>.<ext>` with `i` the
1-based op position. Each record carries the image kind, the measured
`width`/`height`, seed 0 — the ops are deterministic, so the seed only
labels the record — and `params`/`inputs` naming the `imagen`.

## Verification and preview

`verify` re-opens each written file with Pillow — it must be a readable
image whose suffix, mode and pixel size match a fresh in-memory pass of
the same ops. `preview` writes the image kind's fields per asset matching
`schemas/preview/image.schema.json`: `prompt` is
`pillow <operacion> of <imagen-stem>`, `seed` 0, `width`/`height` measured
from the file.

`facet doctor pillow` runs one quick check — Pillow imports at exactly the
pinned 13.0.0 — and a `full` depth adds a 2x2 PNG encode/decode roundtrip.

## Licences

Pillow is MIT-CMU (Jeffrey A. Clark and contributors); the manifest
records it. The package itself is Apache-2.0 like the rest of the
registry tooling.
