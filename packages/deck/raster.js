"use strict";

// The deck raster helpers: every page PNG and text check comes from the same
// headless Chromium the render already uses, never from a host poppler.
// `pdfPageCount`/`pdfText` read the written PDF through the pinned
// `pdfjs-dist` package (no download, no host install); `rasterizePdf` loads a
// placed PDF — one with no source HTML — into pdfgrab.html inside a fresh
// headless Chromium run and screenshots each rendered page canvas.

const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const PLAYWRIGHT = "playwright-core";
const PDFJS = "pdfjs-dist";
const PDFJS_ENTRY = path.join("build", "pdf.js");
const PDFJS_WORKER = path.join("build", "pdf.worker.js");
const PDFGRAB = path.join(__dirname, "pdfgrab.html");
const VIEWPORT = { width: 1060, height: 800 };
const SCALE = 2;

function nodePathDirs() {
  return (process.env.FACET_NODE_PATH || "").split(path.delimiter).filter(Boolean);
}

function packageDir(name) {
  for (const dir of nodePathDirs()) {
    try {
      const manifest = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
      if (manifest.name === name) return { dir, version: String(manifest.version || "") };
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  throw new Error(`${name} is not in FACET_NODE_PATH; run this runner through facet`);
}

function pdfjs() {
  return require(path.join(packageDir(PDFJS).dir, PDFJS_ENTRY));
}

async function openPdf(pdf) {
  const data = new Uint8Array(fs.readFileSync(pdf));
  return pdfjs().getDocument({ data, isEvalSupported: false }).promise;
}

async function pdfPageCount(pdf) {
  const doc = await openPdf(pdf);
  return doc.numPages;
}

async function pdfText(pdf) {
  const doc = await openPdf(pdf);
  const texts = [];
  for (let index = 1; index <= doc.numPages; index += 1) {
    const page = await doc.getPage(index);
    const content = await page.getTextContent();
    for (const item of content.items || []) {
      if (item && typeof item.str === "string") texts.push(item.str);
    }
  }
  return texts.join("\n");
}

// A placed PDF has no source HTML: pdfgrab.html renders it with pdf.js inside
// the same headless Chromium and the runner screenshots one canvas per page.
async function rasterizePdf(pdf, dir, chrome) {
  const pdfjsDir = packageDir(PDFJS).dir;
  const query = new URLSearchParams({
    src: pathToFileURL(pdf).href,
    lib: pathToFileURL(path.join(pdfjsDir, PDFJS_ENTRY)).href,
    worker: pathToFileURL(path.join(pdfjsDir, PDFJS_WORKER)).href,
    scale: String(SCALE),
  });
  const url = `${pathToFileURL(PDFGRAB).href}?${query.toString()}`;
  const playwright = require(packageDir(PLAYWRIGHT).dir);
  const browser = await playwright.chromium.launch({
    executablePath: chrome,
    args: ["--allow-file-access-from-files"],
  });
  try {
    const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: SCALE });
    await page.goto(url, { waitUntil: "networkidle" });
    const count = Number(await page.evaluate(() => window.__pdfReady));
    for (let index = 1; index <= count; index += 1) {
      await page
        .locator(`canvas[data-page="${index}"]`)
        .screenshot({ path: path.join(dir, `page-${index}.png`) });
    }
    return count;
  } finally {
    await browser.close();
  }
}

module.exports = { pdfPageCount, pdfText, rasterizePdf };
