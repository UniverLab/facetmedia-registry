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
