---
name: svganim
description: Bake a self-contained animated SVG from a Node script and its data, with text drawn as paths, plus a 2x PNG.
---
# svganim

`svganim.bake` runs the piece's Node script and bakes its SVG: CSS
`@keyframes` only, no JavaScript, every label converted to a `<path>` with
`opentype.js` so the file renders the same on GitHub and inside HyperFrames.

## When to use

- When a piece needs a small, self-playing animation — a banner, a badge, a
  looping divider — that survives an `<img>` embed and GitHub's renderer.
- When a GIF or MP4 is the deliverable: the baked SVG embeds in HyperFrames,
  and long animations or audio belong in `hyperframes` instead.
- When no browser may be involved in the bake; `sharp` renders the agent PNG
  from the SVG directly.

## Pieces

```toml
[inputs]
script = "banner-navidad.cjs"
data = "banner-navidad.json"
```

`script` is a CommonJS script run as `node script data`; it reads the data
file path from `argv[2]` and writes the finished SVG to stdout. `data` is
that data file, resolved relative to the piece. `run` writes
`<script>.svg` and a 2x `<script>.png` beside each other in the output
directory.

## Motion that survives the bake

Three rules prevent most "it renders but moves wrong" banners:

- **Set `transform-origin` explicitly.** In SVG it defaults to the viewBox
  origin, not the element's centre, so a rotation or scale without it orbits a
  corner. Write the origin in the element's own coordinates, e.g.
  `transform-origin: 640px 170px`.
- **Bake measured dash lengths.** A stroke-draw animation needs the path's real
  length in `stroke-dasharray` and `stroke-dashoffset`; `getTotalLength()` is
  browser-only, so measure the geometry in Node at bake time and write the
  number into the document.
- **Freeze the end state.** A keyframe that only goes `from` → `to` snaps back
  to the start when the animation ends; end with `animation-fill-mode:
  forwards`, or a 100 % keyframe equal to the last visible state.

Composition and accessibility, which a baked file keeps for free:

- Leave about 8 % margin so the art never touches the viewBox edge, and ground
  a floating object with a soft shadow ellipse.
- Give every gradient and clipPath a name unique to this file: generic ids
  collide when several SVGs share a page.
- Ship a `prefers-reduced-motion: reduce` rule that stops the animation, and a
  `<title>` and `<desc>` in the document; `verify` refuses `<text>`, not these
  metadata elements.

Generative craft that keeps procedural banners sharp and reproducible:

- **Commit to one visual grammar first.** Choose the geometric motif, grid
  or stroke language before writing animation code so every element belongs to
  the same system.
- **Use a seeded PRNG, never `Math.random()`.** Drive procedural placement,
  delays and jitter from a deterministic seeded generator so every bake
  reproduces identical SVG and PNG output.
- **Keep strokes flat and crisp.** Pair clean flat geometry with a
  single accent colour and a clear focal hierarchy so the composition reads at a
  glance without visual noise.

facet bakes CSS `@keyframes` only, on purpose: HyperFrames inlines and
coordinates the document, so SMIL is not used even where it would survive an
`<img>` embed that JavaScript cannot reach.

## Judging the result

`verify` re-reads the baked SVG and passes only a well-formed document with
CSS `@keyframes`, no `<script>`, and no `<text>` element; the PNG must carry
a valid signature. `preview` writes the image kind's fields with the script
basename as the prompt and seed 0. A person then looks at the PNG: a `<text>`
that slipped through, a clipped label or a missing frame is caught by eye.

## Pitfalls

- **Text as paths.** A `<text>` element fails `runner_failed`, exit 1 —
  convert every label with `opentype.js` before writing the SVG; the
  `parse`/`getPath`/`toPathData` recipe and the minimal script skeleton are
  in `references/build-banners.md`.
- **No JavaScript.** A `<script>` is refused: GitHub strips it, so animate
  with `@keyframes` inside the document.
- **The SVG is the source.** The PNG is sharp's first frame at 2x, not a
  second render; a frame that only exists after the animation starts belongs
  in HyperFrames.
- **The first frame is the thumbnail.** Design the SVG so its opening state
  already reads as the finished banner; a reveal animation that starts empty
  ships an empty PNG.

Sources for these rules, with their licences, are in
`skill/references/sources.md`.
