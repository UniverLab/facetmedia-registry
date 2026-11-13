"use strict";

// Bars grow to their data values. Every label is drawn as a path with
// opentype.js (a 7-segment stroke set, so no font file is needed), and the
// motion lives in one CSS @keyframes rule: no <text>, no <script>.
const fs = require("node:fs");
const opentype = require("opentype.js");

const SEGMENTS = {
  a: [0, 0, 4, 0], b: [4, 0, 4, 2.5], c: [4, 2.5, 4, 5], d: [0, 5, 4, 5],
  e: [0, 2.5, 0, 5], f: [0, 0, 0, 2.5], g: [0, 2.5, 4, 2.5],
};
const DIGITS = {
  0: "abcdef", 1: "bc", 2: "abged", 3: "abgcd", 4: "fgbc",
  5: "afgcd", 6: "afgedc", 7: "abc", 8: "abcdefg", 9: "abcdfg",
};

function labelPath(value, x, y, scale) {
  const path = new opentype.Path();
  let cursor = x;
  for (const character of String(value)) {
    for (const segment of DIGITS[character] || "") {
      const [x1, y1, x2, y2] = SEGMENTS[segment];
      path.moveTo(cursor + x1 * scale, y + y1 * scale);
      path.lineTo(cursor + x2 * scale, y + y2 * scale);
    }
    cursor += 6 * scale;
  }
  return path.toPathData(2);
}

const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const width = data.width || 1280;
const height = data.height || 720;
const baseline = height - 120;
const chart = height - 280;
const slot = (width - 240) / data.values.length;
const tallest = Math.max(...data.values);

const bars = data.values.map((value, index) => {
  const barWidth = slot * 0.52;
  const x = 120 + slot * index + (slot - barWidth) / 2;
  const barHeight = Math.max(8, Math.round((value / tallest) * chart));
  const label = labelPath(value, x + (barWidth - String(value).length * 36) / 2, baseline + 28, 6);
  return (
    `<g class="bar" style="animation-delay:${(index * 0.16).toFixed(2)}s">` +
    `<rect x="${x}" y="${baseline - barHeight}" width="${barWidth}" height="${barHeight}" rx="6" fill="#8fbf9f"/>` +
    `<path d="${label}" fill="none" stroke="#101215" stroke-width="2.4" stroke-linecap="square"/>` +
    "</g>"
  );
});

process.stdout.write(
  `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" ` +
    `viewBox="0 0 ${width} ${height}">` +
    "<style>@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}" +
    ".bar{transform-box:fill-box;transform-origin:center bottom;animation:grow 1.1s ease-out both}</style>" +
    `<rect width="${width}" height="${height}" fill="#f6f3ec"/>` +
    `<line x1="90" y1="${baseline}" x2="${width - 90}" y2="${baseline}" stroke="#101215" stroke-width="3"/>` +
    bars.join("") +
    "</svg>",
);
