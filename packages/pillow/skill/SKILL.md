---
name: pillow
description: Base image operations on CPU with Pillow — convert between PNG, JPEG and WebP, resize exact or aspect-preserving, and lay contact sheets with dividers.
---
# pillow

`pillow.base` runs a list of operations on one source image, in order, all
in memory: `convert` re-encodes the format, `resize` resizes, and
`sheet` lays a contact sheet for review boards. Each operation writes one
file named `<image-stem>-<i>-<op>.<ext>` where `i` is the 1-based
position in `operations`.

## When to use

- When a piece needs plain format conversion, resizing or a contact sheet
  and nothing heavier — no models, no GPU, Pillow only.
- When building a review board: `sheet` tiles the image into a grid with
  white dividers so a person sees every tile at once.
- When the work is heavier — cutouts, relighting, generation — leave it to
  the specialized packages (`rembg`, `comfy`, `blender`); `pillow.base` is
  the base layer they sit on.

## Pieces

```toml
[inputs]
image = "foto.png"
operations = [
  { op = "convert", format = "webp" },
  { op = "resize", width = 800 },
  { op = "sheet", columns = 2, rows = 2 },
]
```

`image` is the source image, resolved relative to the piece file.
`operations` is one table per op, applied in order starting from
`image`; each writes `<image-stem>-<i>-<op>.<ext>` beside the
piece (png, jpg or webp for `convert`; the current extension for
`resize`; png for `sheet`).

`convert` takes `format` (`png`, `jpeg`, `webp`; required) and an
optional `mode` (`RGB`, `RGBA`, `L`). JPEG output is always RGB: with no
`mode` and an alpha source the runner composites onto white first, and
`mode = "RGBA"` with `format = "jpeg"` is rejected — use png or webp for
transparency.

`resize` takes `width` and/or `height` (integers >= 1, at least one
required). Both dims resize exact — the aspect may change. One dim
preserves the aspect, rounded to the nearest integer (minimum 1), resampled
with Lanczos.

`sheet` takes `columns` and `rows` (integers >= 1, both required). It
cuts the current image into equal tiles of `floor(W/columns)` by
`floor(H/rows)` from the top-left — remainder pixels on the right and
bottom are dropped — and reassembles them row-major into one sheet with
2 px white dividers and no outer border, ideal for review boards.

## Judging the result

`verify` re-opens every written file with Pillow and compares its suffix,
mode and pixel size against a fresh in-memory pass of the same ops, so a
truncated or mis-encoded output fails. `preview` writes the image kind's
fields for each asset — `prompt` is `pillow <op> of <image-stem>`,
`seed` 0 because the ops are deterministic and the seed only labels the
record, `width`/`height` measured from the file.

## Pitfalls

- **JPEG has no alpha.** `mode = "RGBA"` with `format = "jpeg"` fails;
  omit `mode` to get the automatic white flatten, or pick png/webp to keep
  the alpha channel.
- **`resize` with both dims changes the aspect on purpose.** Give
  one dim to preserve it; the other is computed and rounded.
- **`sheet` drops the remainder.** Tiles are `floor` divisions from the
  top-left, so right and bottom pixels outside the last full tile never
  appear; size the grid to the image or accept the crop.
- **Ops chain in memory, files do not.** Each op applies to the previous
  op's image, but every output is named after `image`'s stem with its own
  1-based index — `foto-2-resize.png` is op 2, not a file the next
  op read.
