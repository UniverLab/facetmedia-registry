---
name: rembg
description: Cut the background out of a photo on CPU with rembg's U2NetP, writing an alpha PNG and a checkerboard preview for edge review.
---
# rembg

`rembg.cutout` removes a photo's background with rembg's U2NetP running on
`CPUExecutionProvider`: it writes `<foto-stem>.png` with an alpha channel
and `<foto-stem>-damero.png`, the same cutout over a checkerboard so a
person can judge thin edges without touching the alpha file.

## When to use

- When a piece needs a subject cut out of its photo — a product shot, a
  portrait, an object on a plain backdrop — as an alpha PNG.
- When edge quality matters: the `-damero` asset exists so a person can
  review hair, fur and thin outlines before the cutout ships.
- When the work must stay on CPU: U2NetP is the small model, about 4.6 MB
  of weights and a couple of seconds per photo.

## Pieces

```toml
[inputs]
foto = "entrada.png"
```

`foto` is the photo, resolved relative to the piece file. `run` writes
`<foto-stem>.png` (RGBA) and `<foto-stem>-damero.png` (the cutout over a
white-and-grey checkerboard) into the output directory.

## Judging the result

`verify` re-opens both PNGs: the cutout must be RGBA, the damero RGB, and
both must be readable PNGs at the foto's size. `preview` writes the image
kind's fields for each asset with the prompt `cutout of <foto-stem>` and
seed 0 — the cutout is deterministic given the weights, so the seed only
labels the record. A person judges the edges on the damero asset: a halo,
a eaten edge or a leftover background patch is caught by eye.

## Pitfalls

- **Judge the damero, not the alpha.** Transparent pixels are invisible on
  a light page; the checkerboard makes semi-transparent and missed edges
  visible. The alpha PNG itself is never composited for review.
- **U2NetP is the small model.** Fine hair and wispy edges benefit from a
  bigger session model; `rembg.cutout` pins `u2netp` for CPU speed.
- **The weights come from `facet pull rembg`.** A missing or mismatched
  `u2netp.onnx` fails `doctor` with that fix; tests and CI never download.
- **`rembg.papel` is coming** in a later change to this same package; this
  stub names only `rembg.cutout`.
