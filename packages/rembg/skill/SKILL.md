---
name: rembg
description: Cut a photo's background out or return a plate to clean paper on CPU with rembg's U2NetP, writing an alpha PNG or an even-paper RGB PNG.
---
# rembg

`rembg.cutout` removes a photo's background with rembg's U2NetP running on
`CPUExecutionProvider`: it writes `<foto-stem>.png` with an alpha channel
and `<foto-stem>-damero.png`, the same cutout over a checkerboard so a
person can judge thin edges without touching the alpha file.

`rembg.papel` returns a plate to clean flat paper: the object's silhouette
keeps its original pixels while everything outside it becomes even paper
with grain, so stains and torn corners go away. It writes exactly one
asset, `<lamina-stem>-papel.png` (RGB).

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

For clean paper, give the plate instead:

```toml
[inputs]
lamina = "lamina.png"
```

`lamina` is the plate, resolved the same way relative to the piece file.
`run` writes `<lamina-stem>-papel.png` (RGB) only.

This is a port of the paper-cleaning tool; `lamina_web.py` stays
out — it is a univerlab.org pipeline, not part of this package.

## Judging the result

`verify` re-opens both PNGs: the cutout must be RGBA, the damero RGB, and
both must be readable PNGs at the foto's size. `preview` writes the image
kind's fields for each asset with the prompt `cutout of <foto-stem>` and
seed 0 — the cutout is deterministic given the weights, so the seed only
labels the record. A person judges the edges on the damero asset: a halo,
a eaten edge or a leftover background patch is caught by eye.

A 1344×768 test photo (`entrada.png`, not shipped) cut out in 1.48 s on CPU with rembg
2.0.67's U2NetP and left 66.59 % of pixels transparent; the damero view
kept the figure, the book and the lamp. The package ships that lab run:
`examples/remover.py` (the script), `examples/medicion.json` (its record),
`examples/vista-damero.png` (the damero) and `examples/README.md`.

## Pitfalls

- **Judge the damero, not the alpha.** Transparent pixels are invisible on
  a light page; the checkerboard makes semi-transparent and missed edges
  visible. The alpha PNG itself is never composited for review.
- **U2NetP is the small model.** Fine hair and wispy edges benefit from a
  bigger session model; `rembg.cutout` pins `u2netp` for CPU speed.
- **The weights come from `facet pull rembg`.** A missing or mismatched
  `u2netp.onnx` fails `doctor` with that fix; tests and CI never download.
  `rembg.papel` uses the same `u2netp` session and the same pull.
- **Attribution.** rembg's code is MIT (Daniel Gatis); the U2NetP weights
  are U-2-Net, Apache-2.0 (xuebinqin et al.), fetched by
  `facet pull rembg`; both are recorded in the manifest.
