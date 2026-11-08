# Build banners: text as paths and the guion skeleton

Ported from the lab's banner script. Two recipes live here: outlining every
word with opentype.js, and the minimal guion a piece runs to write its SVG.

## Why every word is a path

GitHub renders README SVGs as images and does NOT load custom fonts. A
`<text>` element with `font-family` falls back to a system font or vanishes,
so the banner must carry its letters as vector `<path>` data baked at build
time. The same rule applies to any SVG facetmedia serves: the baked file has
to render identically on GitHub and inside HyperFrames.

## Text to path with opentype.js

Load each font file once with `loadSync`:

```js
const opentype = require('opentype.js');
const mono = opentype.loadSync('fonts/SometypeMono-wght.ttf');
const italic = opentype.loadSync('fonts/OldStandard-Italic.ttf');
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

## The guion skeleton

The piece's `guion` is a CommonJS script: the runner calls
`node guion datos`, so the data file path arrives as `argv[2]` and the
finished SVG goes to stdout — nothing else may be printed. Animations are
CSS `@keyframes` inside the document; there is no `<script>` and no `<text>`.

```js
#!/usr/bin/env node
// guion — node guion datos > out.svg
const fs = require('fs');
const path = require('path');
const opentype = require('opentype.js');

const datosPath = process.argv[2];
if (!datosPath) {
  console.error('usage: node guion <datos.json>');
  process.exit(1);
}
const datos = JSON.parse(fs.readFileSync(datosPath, 'utf8'));

const font = opentype.loadSync(path.join(__dirname, 'font.ttf'));

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
    <path d="${textPath(font, datos.titulo, 76, 200, 56)}" fill="#ecebe4"/>
  </g>
</svg>
`;

process.stdout.write(svg);
```

What `verify` then re-checks on the baked file: a well-formed SVG document,
CSS `@keyframes` present, no `<script>`, no `<text>` — and a valid PNG beside
it, rendered by sharp from the SVG's first frame at 2x.
