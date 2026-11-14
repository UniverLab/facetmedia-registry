# Build banners: text as paths and the script skeleton

Ported from the lab's banner script. Two recipes live here: outlining every
word with opentype.js, and the minimal script a piece runs to write its SVG.

## Why every word is a path

GitHub renders README SVGs as images and does NOT load custom fonts. A
`<text>` element with `font-family` falls back to a system font or vanishes,
so the banner must carry its letters as vector `<path>` data baked at build
time. The same rule applies to any SVG facetmedia serves: the baked file has
to render identically on GitHub and inside HyperFrames.

## Text to path with opentype.js

Never use `loadSync` — removed in opentype.js 2.0.0, it returns undefined; use `parse`.

Load each font file once with `parse` over the file bytes:

```js
const fs = require('fs');
const opentype = require('opentype.js');
const mono = opentype.parse(fs.readFileSync('fonts/SometypeMono-wght.ttf'));
const italic = opentype.parse(fs.readFileSync('fonts/OldStandard-Italic.ttf'));
```

Outline a string left-anchored at `(x, baselineY)`, kerning on:

```js
function textPath(font, text, x, baselineY, fontSize) {
  return font.getPath(text, x, baselineY, fontSize, { kerning: true }).toPathData(2);
}
```

Letter-spacing (tracking, in em) cannot go through `getPath`, so walk glyphs
one by one and advance the cursor by each glyph's advance width plus the
track — `spacedPath`, returning the path and its measured width:

```js
function spacedPath(font, text, x, baselineY, fontSize, trackEm) {
  const track = fontSize * trackEm;
  let cursor = x;
  const parts = [];
  for (const ch of text) {
    const g = font.charToGlyph(ch);
    parts.push(g.getPath(cursor, baselineY, fontSize).toPathData(2));
    cursor += (g.advanceWidth / font.unitsPerEm) * fontSize + track;
  }
  return { d: parts.join(' '), width: cursor - x - track };
}
```

Each outlined string lands in the document as its own element:

```xml
<path d="..." fill="#ecebe4"/>
```

The measured `width` is what positions rules, centering and the next line —
there is no layout engine, so every box is arithmetic on these widths.

## Embedding raster images

Raster assets go in as base64 data URIs so the finished SVG is
self-contained — nothing reaches back to the file system or a CDN:

```js
const dataUri = (file) =>
  `data:image/webp;base64,${readFileSync(file).toString('base64')}`;
```

Then reference it inside the document:

```xml
<image href="data:image/webp;base64,..." x="76" y="68" width="700" height="404"/>
```

## The script skeleton

The piece's `script` is a CommonJS script: the runner calls
`node script data`, so the data file path arrives as `argv[2]` and the
finished SVG goes to stdout — nothing else may be printed. Animations are
CSS `@keyframes` inside the document; there is no `<script>` and no `<text>`.

```js
#!/usr/bin/env node
// script — node script data > out.svg
const fs = require('fs');
const path = require('path');
const opentype = require('opentype.js');

const dataPath = process.argv[2];
if (!dataPath) {
  console.error('usage: node script <data.json>');
  process.exit(1);
}
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));

const font = opentype.parse(fs.readFileSync(path.join(__dirname, 'font.ttf')));

// ...layout arithmetic on spacedPath/textPath widths...
// ...embed rasters as data:image/...;base64...

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="340" viewBox="0 0 1280 340">
  <style>
    @keyframes drift {
      from { transform: translateX(0); }
      to { transform: translateX(24px); }
    }
    .drift { animation: drift 6s ease-in-out infinite alternate; }
  </style>
  <g class="drift">
    <path d="${textPath(font, data.titulo, 76, 200, 56)}" fill="#ecebe4"/>
  </g>
</svg>
`;

process.stdout.write(svg);
```

## Motion gotchas the bake must handle

**Transform origin.** CSS transforms on an SVG element use the viewBox origin
unless told otherwise, so a spin around the element's own centre needs an
explicit origin in user units:

```xml
<style>
  @keyframes turn { to { transform: rotate(360deg); } }
  .wheel { transform-origin: 640px 170px; animation: turn 8s linear infinite; }
</style>
```

**Measured dash lengths.** A stroke-draw needs the real path length before it
can animate. `getTotalLength()` does not exist in Node, so measure at bake
time from geometry you already have — a straight segment's length, `2πr` for
a circle, the sum of a polyline's segments — or sample the path and accumulate
distances. Write the result into the document:

```js
const length = circleLength(r); // 2 * Math.PI * r, or a measured sum
const draw = `<path d="${d}" fill="none" stroke="#ecebe4"
  stroke-dasharray="${length}" stroke-dashoffset="${length}"
  style="animation: draw 1.2s ease-out forwards"/>`;
```

with `@keyframes draw { to { stroke-dashoffset: 0; } }`.

**Frozen end state.** An animation without `forwards` (or an explicit 100 %
keyframe holding the last state) reverts to the first frame when it ends. Add
`animation-fill-mode: forwards` to every one-shot reveal.

**Reduced motion and metadata.** A `@media (prefers-reduced-motion: reduce)`
block that sets `animation: none` keeps the file usable for people who ask for
calm, and `<title>`/`<desc>` give the document an accessible name and
description. Neither is `<text>`, so `verify` accepts them.

**ID hygiene.** Prefix every gradient, clipPath and mask id with the banner's
own slug (`sale-grad-1`, not `gradient1`): several baked SVGs can share a page
and ids are document-global.

What `verify` then re-checks on the baked file: a well-formed SVG document,
CSS `@keyframes` present, no `<script>`, no `<text>` — and a valid PNG beside
it, rendered by sharp from the SVG's first frame at 2x.
