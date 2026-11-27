---
name: pillow
description: Base image ops and photo retouching on CPU with Pillow — convert, resize, contact sheets, aspect cropping, color grading, sharpening, and framing.
---
# pillow

`pillow` provides two deterministic CPU capabilities on one source image:

- `pillow.base` runs a list of operations in order in memory (`convert`,
  `resize`, `sheet`) and writes `<image-stem>-<i>-<op>.<ext>` per op.
- `pillow.retouch` crops to an aspect ratio, flips or rotates, applies
  autocontrast, white-balance warmth, brightness/contrast/saturation grading,
  unsharp-mask sharpening, and editorial border padding, writing `<name>.<ext>`.

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

For `pillow.retouch`:

```toml
[inputs]
image = "foto.png"
name = "foto-retouched"
aspect = "4:5"
autocontrast = true
contrast = 1.1
warmth = 0.1
sharpen = 0.8
pad-px = 24
pad-color = "#F6F3EC"
```

Steps run in deterministic order: EXIF transpose -> `flip` (`none`,
`horizontal`, `vertical`) -> `rotate-deg` (`expand = true` when non-zero) ->
`aspect` center-crop (`1:1`, `4:5`, `16:9`, `9:16`, `3:2`, `4:3`) -> split
alpha (preserved for `png`/`webp`; for `jpeg`, flattened onto `pad-color` when
`pad-px > 0`, otherwise `#FFFFFF`) -> `autocontrast` (`cutoff = 1`) ->
`warmth` (`-1.0..1.0`) -> `brightness` (`0.2..3.0`) -> `contrast`
(`0.2..3.0`) -> `saturation` (`0.0..3.0`) -> `sharpen` (`UnsharpMask` when
`> 0`) -> reattach alpha -> `pad-px` border in `pad-color` -> `<name>.<ext>`.

## Working on a photo

The runner opens the source once and applies its EXIF orientation first via
`ImageOps.exif_transpose`, so a phone JPEG comes out the way a viewer shows
it — upright — and the output carries no orientation tag that would rotate
it again. Images without EXIF behave exactly as before. There is no
orientation input because the tag itself is the instruction.

Ops chain in memory and each output is written once. That is deliberate: every
JPEG re-encode loses a little detail, so a chain that re-read its own files
would degrade the image twice; here only the final state of each output is
encoded. No quality knob is exposed, so Pillow's own encoder defaults apply.

`resize()` returns a new image while `thumbnail()` resizes in place; the runner
uses `resize` with `Image.Resampling.LANCZOS` (the Pillow 10 name — `ANTIALIAS`
is gone), so nothing is mutated behind you. The output suffix decides the
writer: `save` infers the format from the extension, and each op names its own
suffix, so a png op never silently writes a JPEG.

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
- **Trim before the sheet, not during it.** `sheet` only cuts equal tiles, so
  a source with a flat border tiles with that border inside every tile. Trim
  it before the piece: `getbbox()` on an RGBA conversion gives the content box
  to crop to.
- **Phone photos come out upright.** The runner applies EXIF orientation on
  open via `ImageOps.exif_transpose`, so an orientation-tagged JPEG is
  transposed before any op and the output carries no orientation tag.

Sources for these rules, with their licences, are in
`skill/references/sources.md`.
