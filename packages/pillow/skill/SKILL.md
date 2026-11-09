---
name: pillow
description: Base image operations on CPU with Pillow — convert between PNG, JPEG and WebP, resize exact or aspect-preserving, and lay contact sheets with dividers.
---
# pillow

`pillow.base` runs a list of operations on one source image, in order, all
in memory: `convertir` re-encodes the format, `redimensionar` resizes, and
`hoja` lays a contact sheet for review boards. Each operation writes one
file named `<imagen-stem>-<i>-<operacion>.<ext>` where `i` is the 1-based
position in `operaciones`.

## When to use

- When a piece needs plain format conversion, resizing or a contact sheet
  and nothing heavier — no models, no GPU, Pillow only.
- When building a review board: `hoja` tiles the image into a grid with
  white dividers so a person sees every tile at once.
- When the work is heavier — cutouts, relighting, generation — leave it to
  the specialized packages (`rembg`, `comfy`, `blender`); `pillow.base` is
  the base layer they sit on.

## Pieces

```toml
[inputs]
imagen = "foto.png"
operaciones = [
  { operacion = "convertir", formato = "webp" },
  { operacion = "redimensionar", ancho = 800 },
  { operacion = "hoja", columnas = 2, filas = 2 },
]
```

`imagen` is the source image, resolved relative to the piece file.
`operaciones` is one table per op, applied in order starting from
`imagen`; each writes `<imagen-stem>-<i>-<operacion>.<ext>` beside the
piece (png, jpg or webp for `convertir`; the current extension for
`redimensionar`; png for `hoja`).

`convertir` takes `formato` (`png`, `jpeg`, `webp`; required) and an
optional `modo` (`RGB`, `RGBA`, `L`). JPEG output is always RGB: with no
`modo` and an alpha source the runner composites onto white first, and
`modo = "RGBA"` with `formato = "jpeg"` is rejected — use png or webp for
transparency.

`redimensionar` takes `ancho` and/or `alto` (integers >= 1, at least one
required). Both dims resize exact — the aspect may change. One dim
preserves the aspect, rounded to the nearest integer (minimum 1), resampled
with Lanczos.

`hoja` takes `columnas` and `filas` (integers >= 1, both required). It
cuts the current image into equal tiles of `floor(W/columnas)` by
`floor(H/filas)` from the top-left — remainder pixels on the right and
bottom are dropped — and reassembles them row-major into one sheet with
2 px white dividers and no outer border, ideal for review boards.

## Judging the result

`verify` re-opens every written file with Pillow and compares its suffix,
mode and pixel size against a fresh in-memory pass of the same ops, so a
truncated or mis-encoded output fails. `preview` writes the image kind's
fields for each asset — `prompt` is `pillow <operacion> of <imagen-stem>`,
`seed` 0 because the ops are deterministic and the seed only labels the
record, `width`/`height` measured from the file.

## Pitfalls

- **JPEG has no alpha.** `modo = "RGBA"` with `formato = "jpeg"` fails;
  omit `modo` to get the automatic white flatten, or pick png/webp to keep
  the alpha channel.
- **`redimensionar` with both dims changes the aspect on purpose.** Give
  one dim to preserve it; the other is computed and rounded.
- **`hoja` drops the remainder.** Tiles are `floor` divisions from the
  top-left, so right and bottom pixels outside the last full tile never
  appear; size the grid to the image or accept the crop.
- **Ops chain in memory, files do not.** Each op applies to the previous
  op's image, but every output is named after `imagen`'s stem with its own
  1-based index — `foto-2-redimensionar.png` is op 2, not a file the next
  op read.
