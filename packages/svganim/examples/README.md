# The example files in this folder

- `bake-bars.js` is authored for this example: a CommonJS script that reads
  the data path from `argv[2]` and writes the whole SVG to stdout. It draws a
  7-segment stroke alphabet with `opentype.js`, so every label is a `<path>`,
  and keeps the motion in one CSS `@keyframes` rule.
- `bars.json` is authored for this example: four bar values and the canvas
  size. Change the values and re-run; the labels follow.
- `bake.toml` is the piece.
- `fonts/` carries the vendored UniverLab faces with their OFL texts. The
  shipped labels use none of them: every label is a 7-segment `<path>`.
