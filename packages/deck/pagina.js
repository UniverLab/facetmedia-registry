"use strict";

// The deck.pagina helpers: one-page pieces (infographics, posters) laid out
// from HTML + CSS + SVG and exported through the lab's default render path —
// screen media, the content's measured height, and `page.pdf` with an explicit
// width/height and `pageRanges: "1"`. The slides runner keeps its own print
// path in runner.js; this module never runs main() on load.

const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const raster = require("./raster.js");

const PLAYWRIGHT = "playwright-core";
const WIDTH = 1060;
const VIEWPORT_HEIGHT = 800;
const SCALE = 2;

const COMMENT_RE = /<!--[\s\S]*?-->/g;
const OPEN_TAG_RE = /<([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/g;
const CLASS_RE = /class\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i;
const FOOTER_CLASS_RE = /footer|fuentes|sources/i;
const CLOSE_TAG_RE = (tag) => new RegExp(`</${tag}\\s*>`, "i");
const ANY_TAG_RE = /<[^>]+>/g;
const FIGURE_BLOCK_RE = /<figure\b[^>]*>[\s\S]*?<\/figure\s*>/gi;
const FIGCAPTION_RE = /<figcaption\b[^>]*>([\s\S]*?)<\/figcaption\s*>/i;
const IMG_RE = /<img\b[^>]*>/gi;
const NUMBER_RUN_RE = /[0-9.,]+/g;
const ASCII_LETTER_RE = /[A-Za-z]/;
const ENGLISH_DECIMAL_RE = /\.\d{1,2}$/;
const ENGLISH_THOUSANDS_RE = /,\d{3}$/;
const MAX_NUMBER_RUNS = 5;

// --- the source checks: footer sources and captioned images, no browser.

function visibleText(fragment) {
  return fragment
    .replace(ANY_TAG_RE, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function elementInner(html, openEnd, tag) {
  const close = CLOSE_TAG_RE(tag).exec(html.slice(openEnd));
  if (!close) return "";
  return html.slice(openEnd, openEnd + close.index);
}

function checkFooterSources(html) {
  OPEN_TAG_RE.lastIndex = 0;
  let match = OPEN_TAG_RE.exec(html);
  while (match) {
    const tag = match[1].toLowerCase();
    const attrs = match[2] || "";
    const classMatch = CLASS_RE.exec(attrs);
    const classes = classMatch
      ? String(classMatch[1] ?? classMatch[2] ?? classMatch[3] ?? "")
      : "";
    if (tag === "footer" || FOOTER_CLASS_RE.test(classes)) {
      const inner = elementInner(html, OPEN_TAG_RE.lastIndex, tag);
      if (visibleText(inner)) return;
    }
    match = OPEN_TAG_RE.exec(html);
  }
  throw new Error(
    "pagina footer-sources: the piece needs a <footer> or a footer/fuentes/sources element with text",
  );
}

function figureBlocks(html) {
  const blocks = [];
  FIGURE_BLOCK_RE.lastIndex = 0;
  let match = FIGURE_BLOCK_RE.exec(html);
  while (match) {
    blocks.push({ start: match.index, end: match.index + match[0].length, block: match[0] });
    match = FIGURE_BLOCK_RE.exec(html);
  }
  return blocks;
}

function checkCaptionedImages(html) {
  const figures = figureBlocks(html);
  IMG_RE.lastIndex = 0;
  let match = IMG_RE.exec(html);
  while (match) {
    const figure = figures.find((item) => match.index > item.start && match.index < item.end);
    if (!figure) {
      throw new Error(
        `pagina captioned-images: an <img> at offset ${match.index} is not inside a <figure>`,
      );
    }
    const caption = FIGCAPTION_RE.exec(figure.block);
    if (!caption || !visibleText(caption[1])) {
      throw new Error(
        "pagina captioned-images: the <figure> holding an <img> needs a non-empty <figcaption>",
      );
    }
    match = IMG_RE.exec(html);
  }
}

function checkSource(html) {
  const clean = String(html).replace(COMMENT_RE, "");
  checkFooterSources(clean);
  checkCaptionedImages(clean);
}

// --- the render: the lab's default path, screen media and measured height.

function packageDir(name) {
  for (const dir of (process.env.FACET_NODE_PATH || "").split(path.delimiter).filter(Boolean)) {
    try {
      const manifest = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
      if (manifest.name === name) return dir;
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  throw new Error(`${name} is not in FACET_NODE_PATH; run this runner through facet`);
}

function renderPdf(htmlPath, pdfPath, chrome, shotsDir) {
  const playwright = require(packageDir(PLAYWRIGHT));
  return playwright.chromium
    .launch({ executablePath: chrome })
    .then(async (browser) => {
      try {
        const page = await browser.newPage({
          viewport: { width: WIDTH, height: VIEWPORT_HEIGHT },
          deviceScaleFactor: SCALE,
        });
        await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "networkidle" });
        await page.evaluate(() => document.fonts.ready);
        await page.emulateMedia({ media: "screen" });
        // scrollHeight never drops below the viewport height, so a page shorter
        // than the viewport is measured by where the body actually ends (plus
        // its bottom margin) — the lab's default render path verbatim.
        const height = await page.evaluate(() => {
          const scroll = document.documentElement.scrollHeight;
          if (scroll > window.innerHeight) return Math.ceil(scroll);
          const body = document.body;
          return Math.ceil(
            body.getBoundingClientRect().bottom +
              parseFloat(getComputedStyle(body).marginBottom || "0"),
          );
        });
        await page.pdf({
          path: pdfPath,
          printBackground: true,
          width: `${WIDTH}px`,
          height: `${height + 2}px`,
          pageRanges: "1",
        });
        if (shotsDir) {
          // A one-page piece can be taller than the viewport, and a clip would
          // stop at its edge; size the viewport to the page and shoot it whole.
          await page.setViewportSize({ width: WIDTH, height: height + 2 });
          await page.screenshot({ path: path.join(shotsDir, "page-1.png") });
        }
      } finally {
        await browser.close();
      }
    });
}

// --- the rendered-text check: Spanish number formats only.

function numberRuns(text) {
  const runs = [];
  NUMBER_RUN_RE.lastIndex = 0;
  let match = NUMBER_RUN_RE.exec(text);
  while (match && runs.length < MAX_NUMBER_RUNS) {
    const before = text[match.index - 1] || "";
    const after = text[match.index + match[0].length] || "";
    if (!ASCII_LETTER_RE.test(before) && !ASCII_LETTER_RE.test(after)) {
      runs.push(match[0]);
    }
    match = NUMBER_RUN_RE.exec(text);
  }
  return runs;
}

async function checkText(pdfPath) {
  const text = await raster.pdfText(pdfPath);
  for (const run of numberRuns(text)) {
    if (ENGLISH_DECIMAL_RE.test(run) || ENGLISH_THOUSANDS_RE.test(run)) {
      throw new Error(
        `pagina spanish-numbers: run "${run}" reads as an English decimal or thousands mark`,
      );
    }
  }
}

module.exports = { checkSource, renderPdf, checkText };
