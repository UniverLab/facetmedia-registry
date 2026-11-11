# svganim

Bake a self-contained animated SVG from a Node script and its data, then
render the agent PNG from that same SVG. `svganim.bake` is the package's only
capability: the piece's `script` owns the drawing, `opentype.js` turns every
label into a `<path>`, and CSS `@keyframes` carries the motion — no
JavaScript, so the file plays inside an `<img>` on GitHub and embeds unchanged
in HyperFrames.

## What it wraps

- **Node**: `22.21.0`, the same pinned runtime every node-engine package
  uses, with the sha256 of nodejs.org's `node-v22.21.0-linux-x64.tar.gz`.
- **opentype.js** `2.0.0`, the first `[[engine.node.packages]]` entry: the
  script imports it to draw labels as paths. It has no runtime dependencies.
- **sharp** `0.35.5` with its `semver`, `detect-libc` and `@img/*` rows: the
  runner renders the first frame of the baked SVG to PNG, at 2x.
- **No browser.** The bake is a Node process and the PNG is sharp rasterizing
  the SVG; nothing launches Chrome or downloads a browser.
- **The seven pins** are the exact versions, tarballs and SRI integrities
  from registry.npmjs.org. facet stages one directory per row on
  `FACET_NODE_PATH`; the runner links each package's dependencies and
  linux-x64 optionals, then resolves both the script's `opentype.js` and its
  own `sharp` through one temporary module root under `NODE_PATH`.

## The script shape

`script` is a CommonJS script run as `node script data` with the piece
directory as its working directory:

```js
const fs = require("node:fs");
const opentype = require("opentype.js");

const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
// ... draw with opentype.js, write <path> elements and @keyframes ...
process.stdout.write(svg);
```

It reads the data file path from `argv[2]` — never a hard-coded path — and
writes the whole SVG document to stdout. `data` is that file, resolved
relative to the piece; `run` passes its absolute path as `argv[2]`. The SVG
goes to `<script>.svg` in the output directory.

## Text as paths

A baked SVG carries **no `<text>` element**. `opentype.js` converts every
label to a `<path>` before the document is written, so the same glyphs render
under any font environment: a `<text>` would fall back to whatever font the
viewer has, and GitHub's renderer has none of the piece's.

`run` and `verify` parse the SVG for `<text>` and refuse it — a plain Error,
exit 1, which facet reports as `runner_failed` naming the opentype.js rule.
The same guards refuse a document that is not well-formed, a `<script>` (GitHub
strips it; animate with CSS) and an SVG with no `@keyframes`. `invalid_input`
is facet-side piece/schema errors only; it cannot come out of the runner.

## The PNG

The PNG is sharp's first frame, rendered from the baked SVG with
`density: 144` — the SVG's 72 DPI default at 2x, so a 1280x720 banner yields
a 2560x1440 PNG. It is the preview an agent and a person look at, not a
second render: whatever only exists after the animation starts (a moving
element mid-path, a frame that changes layout) is not in the PNG.

## When to escalate to video

The bake suits short, loopable, self-playing motion: banners, badges,
dividers, one reveal. Send the piece to `hyperframes` instead when:

- the animation is long or needs audio — the SVG has no soundtrack and GitHub
  plays it on the viewer's clock;
- text must still be selectable, or a label must re-flow at view time;
- the deliverable is an MP4, a GIF or a MOV with alpha rather than an SVG.

## The verbs

- `run` resolves `script` and `data` relative to the piece, runs the script,
  validates the SVG, writes `<name>.svg`, renders `<name>.png` with sharp, and
  reports both as image assets.
- `verify` re-applies the SVG guards (well-formed, `@keyframes`, no
  `<script>`, no `<text>`) and checks the PNG signature.
- `preview` writes `<asset>.preview.json` in the image kind's shape, with the
  script basename as the prompt and seed 0 — the bake is deterministic given
  `data`, so the seed labels the record.
- `doctor` reports the extracted `opentype.js` and `sharp` packages; a
  missing one names the fix: run through facet so the pinned npm tarballs
  land under the facet home.

## Environment

- **`FACET_NODE` and `FACET_NODE_PATH`** are set by facet; the runner refuses
  to run outside it.
- **`NODE_PATH`** is set by the runner for the script, through the temporary
  module root holding the staged packages.
