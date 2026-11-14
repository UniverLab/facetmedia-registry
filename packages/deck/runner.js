#!/usr/bin/env node
"use strict";

// The deck package runner: slides authored as HTML, exported to a paginated PDF.
//
// facet stages this file with the package and runs it through the managed node
// runtime (`{{node}} {{entry}} {{verb}} --input ... --result ...`). The runner
// renders the slide HTML with the pinned Chromium through the pinned
// `playwright-core`, waiting for `document.fonts.ready`, switching to print
// media and asking for `preferCSSPageSize` so the page's own `@page` rule wins.
// It then screenshots one PNG per page from the same Chromium run and reads
// page counts and text through the pinned `pdfjs-dist`, so no host poppler is
// ever needed and no browser is downloaded.

const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const onePage = require("./page.js");
const raster = require("./raster.js");

const PLAYWRIGHT = "playwright-core";
const BROWSER_VAR = "FACET_BROWSER";
const BROWSER_FIX = "facet pull deck";
const BROWSER_MISSING = `${BROWSER_VAR} is not set or not executable; run ${BROWSER_FIX}`;
const PAGE = "deck.page";
const MIN_NODE_MAJOR = 22;
const MAX_SUMMARY = 160;
const VIEWPORT = { width: 1060, height: 800 };
const SCALE = 2;
const PAGE_RE = /^page-(\d+)\.png$/;
const RAW_RE = /^\.page-raw-(\d+)\.png$/;
// The PDF preview's own rasters, cleared and recreated on every preview, the
// same folder freecad uses. The delivered page PNGs beside the PDF stay put.
const PREVIEW_DIR = "preview";
const DOCTOR_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><style>
@page { size: 1280px 720px; margin: 0; }
html, body { margin: 0; height: 100%; }
.slide { width: 1280px; height: 720px; display: grid; place-items: center; }
</style></head><body><section class="slide">deck doctor</section></body></html>
`;

// The presenter build: the same deck, speaker view and notes attached per slide.
const PACKAGE = "deck";
const PACKAGE_VERSION = "0.1.3";
const PRESENTER = `${PACKAGE}.presenter`;
const PRESENTER_DIR = path.join(__dirname, "presenter");
const MIME = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  svg: "image/svg+xml",
  gif: "image/gif",
  webp: "image/webp",
};
const VIDEO_EXTS = new Set(["mp4", "webm", "ogv", "ogg", "mov", "m4v", "mkv"]);
const VIDEO_WARNING = (ref) =>
  `aviso: el video ${ref} no se incrusta; el archivo debe viajar junto a él\n`;
const NOTES_SEPARATOR_RE = /^\s*---\s*$/m;
const EMBEDDED_NOTES_RE = /window\.__PZ_NOTES__\s*=\s*(\[[\s\S]*?\])\s*;<\/script>/g;
const SLIDE_SECTION_RE = /<section\b[^>]*\bclass\s*=\s*("([^"]*)"|'([^']*)')[^>]*>/gi;
const PRESENT_SUFFIX = ".present.html";
const NOTES_SUFFIX = ".notes.md";

// --- the entry point and the file protocol.

async function main() {
  const { verb, options } = parseArgs(process.argv.slice(2));
  const request = readRequest(options.input);
  const result = await dispatch(verb, request);
  writeResult(options.result, result);
}

function parseArgs(argv) {
  const verb = argv[0] || "";
  const options = { input: "", result: "" };
  for (let index = 1; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--input") {
      options.input = argv[index + 1] || "";
      index += 1;
    } else if (arg === "--result") {
      options.result = argv[index + 1] || "";
      index += 1;
    } else {
      throw new Error(`${verb}: unknown argument ${arg}`);
    }
  }
  if (!verb) throw new Error("no verb; expected run, verify, preview or doctor");
  if (!options.input) throw new Error(`${verb}: --input is required`);
  if (!options.result) throw new Error(`${verb}: --result is required`);
  return { verb, options };
}

function readRequest(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function writeResult(file, data) {
  fs.writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`);
}

async function dispatch(verb, request) {
  if (verb === "doctor") return doctor(request);
  const presenter = String(request.capability || "") === PRESENTER;
  if (verb === "run") {
    if (presenter) return runPresenter(request);
    return String(request.capability || "") === PAGE ? runPage(request) : runSlides(request);
  }
  if (verb === "verify") return presenter ? verifyPresenter(request) : verify(request);
  if (verb === "preview") return presenter ? previewPresenter(request) : preview(request);
  throw new Error(`${verb}: unknown verb (this runner has: run, verify, preview, doctor)`);
}

// --- inputs and the pinned npm package directory.

function inputsOf(request) {
  return request.inputs || {};
}

function pieceBase(request) {
  return request.piece_dir || process.cwd();
}

function resolveInput(value, base) {
  const text = String(value);
  return path.isAbsolute(text) ? text : path.resolve(base, text);
}

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

function seedOf(inputs) {
  return Number.isInteger(inputs.seed) ? inputs.seed : 0;
}

function slug(text) {
  const value = String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return value || "deck";
}

function deckName(inputs) {
  const source = inputs.source ? String(inputs.source) : "";
  return slug(path.basename(source, path.extname(source)));
}

function slideFile(request) {
  const source = inputsOf(request).source;
  if (!source) throw new Error("source is required");
  const file = resolveInput(source, pieceBase(request));
  let stat = null;
  try {
    stat = fs.statSync(file);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (stat === null || !stat.isFile()) throw new Error(`source: ${file} is not a file`);
  return file;
}

// --- the pinned Chromium; every raster comes from it or from pdfjs-dist.

function isExecutable(file) {
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return true;
  } catch (error) {
    return false;
  }
}

function findChrome() {
  const given = process.env[BROWSER_VAR] || "";
  return isExecutable(given) ? given : "";
}

// The page geometry a screenshot clip needs: the `@page` size in px when the
// stylesheet declares one, else the laid-out width over the pages' share of
// the scroll height.
function pageGeometry(pages) {
  const sheets = Array.from(document.styleSheets || []);
  for (const sheet of sheets) {
    let rules = [];
    try {
      rules = Array.from(sheet.cssRules || []);
    } catch (error) {
      continue;
    }
    for (const rule of rules) {
      const size = rule && rule.style ? rule.style.getPropertyValue("size") : "";
      const pair = /^(\d+(?:\.\d+)?)px\s+(\d+(?:\.\d+)?)px$/.exec(String(size).trim());
      if (pair) return { width: Number(pair[1]), height: Number(pair[2]) };
    }
  }
  return {
    width: document.documentElement.scrollWidth,
    height: Math.ceil(document.documentElement.scrollHeight / Math.max(1, pages)),
  };
}

async function renderPdf(htmlPath, pdfPath, chrome, shotsDir) {
  const { dir } = packageDir(PLAYWRIGHT);
  const playwright = require(dir);
  return playwright.chromium
    .launch({ executablePath: chrome })
    .then(async (browser) => {
      try {
        const page = await browser.newPage({
          viewport: VIEWPORT,
          deviceScaleFactor: SCALE,
        });
        await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "networkidle" });
        await page.evaluate(() => document.fonts.ready);
        await page.emulateMedia({ media: "print" });
        await page.pdf({
          path: pdfPath,
          printBackground: true,
          preferCSSPageSize: true,
        });
        if (shotsDir) {
          await page.emulateMedia({ media: "screen" });
          const count = await raster.pdfPageCount(pdfPath);
          const geometry = await page.evaluate(pageGeometry, count);
          // A screenshot clip never reaches past the visible viewport, so the
          // viewport is one page tall and each page is scrolled into view
          // before its screenshot. That keeps long decks out of one huge surface.
          await page.setViewportSize({ width: geometry.width, height: geometry.height });
          for (let index = 1; index <= count; index += 1) {
            await page.evaluate((y) => window.scrollTo(0, y), (index - 1) * geometry.height);
            await page.screenshot({ path: path.join(shotsDir, `page-${index}.png`) });
          }
        }
      } finally {
        await browser.close();
      }
    });
}

function numberedPages(dir) {
  let entries = [];
  try {
    entries = fs.readdirSync(dir);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    return [];
  }
  const found = [];
  for (const name of entries) {
    const match = PAGE_RE.exec(name);
    if (match) found.push({ name, number: Number(match[1]) });
  }
  found.sort((left, right) => left.number - right.number);
  return found;
}

function clearPages(dir) {
  for (const name of fs.readdirSync(dir)) {
    if (PAGE_RE.test(name) || RAW_RE.test(name)) fs.rmSync(path.join(dir, name), { force: true });
  }
}

function pad(number, width) {
  return String(number).padStart(width, "0");
}

function normalizePages(dir) {
  const found = numberedPages(dir);
  if (!found.length) return [];
  const width = Math.max(2, String(found[found.length - 1].number).length);
  const staged = found.map((item) => {
    const temp = path.join(dir, `.page-raw-${item.number}.png`);
    fs.renameSync(path.join(dir, item.name), temp);
    return { number: item.number, temp };
  });
  return staged.map((item) => {
    const name = `page-${pad(item.number, width)}.png`;
    fs.renameSync(item.temp, path.join(dir, name));
    return name;
  });
}

function recordedPages(asset) {
  let stored = null;
  try {
    stored = JSON.parse(fs.readFileSync(`${asset}.facet.json`, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    return null;
  }
  const metrics = stored && stored.verification && stored.verification.metrics;
  const count = metrics && metrics.page_count;
  return Number.isInteger(count) ? count : null;
}

function recordedSize(asset) {
  let stored = null;
  try {
    stored = JSON.parse(fs.readFileSync(`${asset}.facet.json`, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    return null;
  }
  const metrics = stored && stored.verification && stored.verification.metrics;
  const width = metrics && metrics.width;
  const height = metrics && metrics.height;
  if (!Number.isInteger(width) || !Number.isInteger(height)) return null;
  return { width, height };
}

// --- the run assets: the PDF, then one image asset per page PNG.

function pageNumber(file) {
  const match = PAGE_RE.exec(path.basename(String(file)));
  return match ? Number(match[1]) : 1;
}

function pdfAsset(name, pageCount, inputs, source) {
  return {
    file: `${name}.pdf`,
    name,
    kind: "document",
    mime: "application/pdf",
    properties: { page_count: pageCount },
    params: inputs,
    seed: seedOf(inputs),
    inputs: [source],
  };
}

function pageImageAsset(outDir, file, inputs, source) {
  const size = raster.pngSize(path.join(outDir, file));
  return {
    file,
    name: path.basename(file, path.extname(file)),
    kind: "image",
    mime: "image/png",
    properties: { page: pageNumber(file), width: size.width, height: size.height },
    params: inputs,
    seed: seedOf(inputs),
    inputs: [source],
  };
}

function runAssets(outDir, name, pages, inputs, source) {
  return [
    pdfAsset(name, pages.length, inputs, source),
    ...pages.map((file) => pageImageAsset(outDir, file, inputs, source)),
  ];
}

// --- the verbs.

async function runSlides(request) {
  const inputs = inputsOf(request);
  const outDir = path.resolve(request.out_dir);
  fs.mkdirSync(outDir, { recursive: true });
  const source = slideFile(request);
  const chrome = findChrome();
  if (!chrome) throw new Error(BROWSER_MISSING);
  const name = deckName(inputs);
  const pdf = path.join(outDir, `${name}.pdf`);
  clearPages(outDir);
  await renderPdf(source, pdf, chrome, outDir);
  const pages = normalizePages(outDir);
  if (!pages.length) throw new Error(`the render wrote no page PNGs for ${name}.pdf`);
  normalizeSlidesNotes(inputs, pages.length);
  const { version } = packageDir(PLAYWRIGHT);
  return {
    tool: { name: "deck", version },
    assets: runAssets(outDir, name, pages, inputs, source),
  };
}

// --- deck.page: one-page pieces through the lab's default render path.

async function runPage(request) {
  const inputs = inputsOf(request);
  const outDir = path.resolve(request.out_dir);
  fs.mkdirSync(outDir, { recursive: true });
  const source = slideFile(request);
  onePage.checkSource(fs.readFileSync(source, "utf8"));
  const chrome = findChrome();
  if (!chrome) throw new Error(BROWSER_MISSING);
  const name = deckName(inputs);
  const pdf = path.join(outDir, `${name}.pdf`);
  clearPages(outDir);
  await onePage.renderPdf(source, pdf, chrome, outDir);
  try {
    await onePage.checkText(pdf);
  } catch (error) {
    clearPages(outDir);
    throw error;
  }
  const pages = normalizePages(outDir);
  if (!pages.length) throw new Error(`the render wrote no page PNGs for ${name}.pdf`);
  const { version } = packageDir(PLAYWRIGHT);
  return {
    tool: { name: "deck", version },
    assets: runAssets(outDir, name, pages, inputs, source),
  };
}

function isPng(asset) {
  return /\.png$/i.test(String(asset));
}

async function verify(request) {
  const inputs = inputsOf(request);
  const assets = [];
  for (const asset of request.assets || []) assets.push(await verdictOf(asset, inputs));
  return { assets };
}

async function verdictOf(asset, inputs) {
  return isPng(asset) ? verdictOfImage(asset) : verdictOfSlides(asset, inputs);
}

async function verdictOfSlides(asset, inputs) {
  const file = path.basename(String(asset));
  const rendered = numberedPages(path.dirname(String(asset))).length;
  const fresh = rendered || (await raster.pdfPageCount(String(asset)));
  normalizeSlidesNotes(inputs, fresh);
  const recorded = recordedPages(asset);
  if (recorded !== null && recorded !== fresh) {
    throw new Error(
      `${file}: ${fresh} pages but the record says page_count ${recorded}`,
    );
  }
  return {
    file,
    passed: true,
    metrics: { page_count: fresh },
    thresholds: {},
    verifier: "chromium-pdfjs",
  };
}

// A page PNG passes when its header reads and any record beside it agrees on
// the size; a run verifies in its temp directory before records are written.
function verdictOfImage(asset) {
  const file = path.basename(String(asset));
  const size = raster.pngSize(String(asset));
  const recorded = recordedSize(asset);
  if (recorded !== null && (recorded.width !== size.width || recorded.height !== size.height)) {
    throw new Error(
      `${file}: ${size.width}x${size.height} but the record says ` +
        `${recorded.width}x${recorded.height}`,
    );
  }
  return {
    file,
    passed: true,
    metrics: { width: size.width, height: size.height, page: pageNumber(file) },
    thresholds: {},
    verifier: "png",
  };
}

async function preview(request) {
  const inputs = inputsOf(request);
  const prompt = String(inputs.prompt || "");
  if (!prompt) throw new Error("prompt is required");
  const seed = seedOf(inputs);
  const assets = request.assets || [];
  const browser = assets.some((asset) => !isPng(asset));
  const chrome = browser ? findChrome() : "";
  if (browser && !chrome) throw new Error(BROWSER_MISSING);
  const entries = [];
  for (const asset of assets) {
    entries.push(await previewOf(asset, seed, chrome, prompt, inputs));
  }
  return { assets: entries };
}

async function previewOf(asset, seed, chrome, prompt, inputs) {
  const file = path.basename(String(asset));
  if (isPng(file)) return previewImage(asset, file, seed, prompt);
  const dir = path.join(path.dirname(String(asset)), PREVIEW_DIR);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  await raster.rasterizePdf(String(asset), dir, chrome);
  const pages = normalizePages(dir).map((name) => `${PREVIEW_DIR}/${name}`);
  const summary = `${file} · ${pages.length} page${pages.length === 1 ? "" : "s"} · seed ${seed}`;
  const notes = normalizeSlidesNotes(inputs, pages.length);
  const data = {
    preview: 1,
    kind: "document",
    summary: summary.slice(0, MAX_SUMMARY),
    page_count: pages.length,
    pages,
    notes,
  };
  fs.writeFileSync(`${asset}.preview.json`, `${JSON.stringify(data, null, 2)}\n`);
  return { file, preview: `${file}.preview.json`, images: [] };
}

// A page PNG previews as itself: the image kind's schema, measured from the
// file, so the web app can show it without decoding the record.
function previewImage(asset, file, seed, prompt) {
  const size = raster.pngSize(String(asset));
  const page = pageNumber(file);
  const data = {
    preview: 1,
    kind: "image",
    summary: `${file} · page ${pad(page, 2)} · ${size.width}×${size.height}`.slice(0, MAX_SUMMARY),
    name: path.basename(file, path.extname(file)),
    prompt,
    seed,
    width: size.width,
    height: size.height,
  };
  fs.writeFileSync(`${asset}.preview.json`, `${JSON.stringify(data, null, 2)}\n`);
  return { file, preview: `${file}.preview.json`, images: [] };
}

// --- the presenter build: one deck, speaker view and per-slide notes.

function deckBase(source) {
  return path.basename(source, path.extname(source));
}

function countSlides(html) {
  let count = 0;
  for (const match of html.matchAll(SLIDE_SECTION_RE)) {
    const classes = (match[2] !== undefined ? match[2] : match[3] || "").split(/\s+/);
    if (classes.includes("slide")) count += 1;
  }
  return count;
}

function noteOf(item, index, seen, maxPage) {
  const label = `notes[${index}]`;
  if (item === null || typeof item !== "object" || Array.isArray(item)) {
    throw new Error(`${label}: expected a { page, text } table`);
  }
  const page = item.page;
  if (!Number.isInteger(page) || page < 1) {
    throw new Error(`${label}.page: must be an integer >= 1`);
  }
  if (seen.has(page)) throw new Error(`${label}.page: ${page} is repeated`);
  if (maxPage !== undefined && page > maxPage) {
    throw new Error(`${label}.page: ${page} is beyond the deck's ${maxPage} slides`);
  }
  seen.add(page);
  const text = typeof item.text === "string" ? item.text.trim() : "";
  if (!text) throw new Error(`${label}.text: must be a non-empty string`);
  return { page, text };
}

function normalizeNotes(inputs, maxPage) {
  const raw = inputs.notes;
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new Error("notes: one table per slide is required");
  }
  const seen = new Set();
  const notes = raw.map((item, index) => noteOf(item, index, seen, maxPage));
  notes.sort((left, right) => left.page - right.page);
  return notes;
}

// Slides notes are optional: an absent or empty table means no notes, while
// a present table follows the presenter's shape, distinctness, range and
// text checks.
function normalizeSlidesNotes(inputs, maxPage) {
  const raw = inputs.notes;
  if (raw === undefined || raw === null) return [];
  if (Array.isArray(raw) && raw.length === 0) return [];
  return normalizeNotes({ notes: raw }, maxPage);
}

function inlineData(ref, dir) {
  if (/^(?:https?:|data:|\/\/|#)/i.test(ref)) return null;
  const clean = ref.split(/[?#]/)[0];
  const ext = path.extname(clean).slice(1).toLowerCase();
  if (VIDEO_EXTS.has(ext) || !MIME[ext]) return null;
  const file = path.isAbsolute(clean) ? clean : path.join(dir, clean);
  if (!fs.existsSync(file)) {
    throw new Error(`ref ${ref}: no file beside the deck to inline`);
  }
  return `data:${MIME[ext]};base64,${fs.readFileSync(file).toString("base64")}`;
}

function inlineResources(html, dir) {
  let embedded = 0;
  const inline = (ref) => {
    const data = inlineData(ref, dir);
    if (data !== null) embedded += 1;
    return data;
  };
  const withSources = html.replace(/(src=")([^"]+)(")/g, (whole, before, ref, after) => {
    const data = inline(ref);
    return data === null ? whole : `${before}${data}${after}`;
  });
  const inlined = withSources.replace(/url\((['"]?)([^)'"]+)\1\)/g, (whole, quote, ref) => {
    const data = inline(ref);
    return data === null ? whole : `url(${data})`;
  });
  const videos = new Set();
  for (const match of inlined.matchAll(/<(?:video|source)[^>]+src="([^"]+)"/g)) {
    if (!match[1].startsWith("data:")) videos.add(match[1]);
  }
  return { html: inlined, embedded, videos: [...videos] };
}

function injectPresenter(html, notes) {
  const css = fs.readFileSync(path.join(PRESENTER_DIR, "runner.css"), "utf8");
  const js = fs.readFileSync(path.join(PRESENTER_DIR, "runner.js"), "utf8");
  const data = JSON.stringify(notes.map((note) => note.text)).replace(/</g, "\\u003c");
  const inject = `<style>${css}</style>\n<script>window.__PZ_NOTES__=${data};</script>\n<script>${js}</script>\n`;
  return html.includes("</body>") ? html.replace("</body>", `${inject}</body>`) : html + inject;
}

function materializeNotes(notes) {
  return `${notes.map((note) => note.text).join("\n---\n")}\n`;
}

function presenterAsset(file, name, kind, mime, properties, params, source) {
  return {
    file,
    name,
    kind,
    mime,
    properties,
    params,
    seed: seedOf(params),
    inputs: [source],
  };
}

function runPresenter(request) {
  const inputs = inputsOf(request);
  const outDir = path.resolve(request.out_dir);
  fs.mkdirSync(outDir, { recursive: true });
  const source = slideFile(request);
  const html = fs.readFileSync(source, "utf8");
  const slides = countSlides(html);
  const notes = normalizeNotes(inputs, slides);
  const resources = inlineResources(html, path.dirname(source));
  for (const video of resources.videos) process.stderr.write(VIDEO_WARNING(video));
  const base = deckBase(source);
  fs.writeFileSync(path.join(outDir, `${base}${PRESENT_SUFFIX}`), injectPresenter(resources.html, notes));
  fs.writeFileSync(path.join(outDir, `${base}${NOTES_SUFFIX}`), materializeNotes(notes));
  const properties = { slides, notes: notes.length };
  return {
    tool: { name: PACKAGE, version: PACKAGE_VERSION },
    assets: [
      presenterAsset(
        `${base}${PRESENT_SUFFIX}`,
        `${base}.present`,
        "document",
        "text/html",
        properties,
        inputs,
        source,
      ),
      presenterAsset(
        `${base}${NOTES_SUFFIX}`,
        `${base}.notes`,
        "text",
        "text/markdown",
        properties,
        inputs,
        source,
      ),
    ],
  };
}

function readText(file) {
  try {
    return fs.readFileSync(file, "utf8");
  } catch (error) {
    throw new Error(`${path.basename(file)}: cannot read (${error.code || error.message})`);
  }
}

function presenterBase(file) {
  if (file.endsWith(PRESENT_SUFFIX)) return file.slice(0, -PRESENT_SUFFIX.length);
  if (file.endsWith(NOTES_SUFFIX)) return file.slice(0, -NOTES_SUFFIX.length);
  throw new Error(`${file}: expected a ${PRESENT_SUFFIX} or ${NOTES_SUFFIX} output`);
}

function embeddedNotes(html) {
  for (const match of html.matchAll(EMBEDDED_NOTES_RE)) {
    try {
      const parsed = JSON.parse(match[1]);
      if (Array.isArray(parsed)) return parsed;
    } catch (error) {
      // Not the injected array; keep looking for the script that carries it.
    }
  }
  throw new Error("__PZ_NOTES__: the presenter file embeds no notes array");
}

function noteSections(text) {
  const sections = text.split(NOTES_SEPARATOR_RE).map((section) => section.trim());
  for (let index = 0; index < sections.length; index += 1) {
    if (!sections[index]) throw new Error(`notes.md: section ${index + 1} is empty`);
  }
  return sections;
}

function checkEmbeddedNotes(html, expected) {
  const embedded = embeddedNotes(html);
  if (embedded.length !== expected) {
    throw new Error(`__PZ_NOTES__: ${embedded.length} notes embedded but notes has ${expected}`);
  }
}

function checkNotesFile(file, notes) {
  const sections = noteSections(readText(file));
  if (sections.length !== notes.length) {
    throw new Error(`notes.md: ${sections.length} sections but notes has ${notes.length}`);
  }
  for (let index = 0; index < notes.length; index += 1) {
    if (sections[index] !== notes[index].text) {
      throw new Error(`notes.md: section ${index + 1} does not match page ${notes[index].page}`);
    }
  }
}

function verifyPresenter(request) {
  const inputs = inputsOf(request);
  const assets = (request.assets || []).map(String);
  if (assets.length === 0) return { assets: [] };
  const dir = path.dirname(assets[0]);
  const base = presenterBase(path.basename(assets[0]));
  const html = readText(path.join(dir, `${base}${PRESENT_SUFFIX}`));
  const notes = normalizeNotes(inputs, countSlides(html));
  checkEmbeddedNotes(html, notes.length);
  checkNotesFile(path.join(dir, `${base}${NOTES_SUFFIX}`), notes);
  return {
    assets: assets.map((asset) => ({
      file: path.basename(asset),
      passed: true,
      verifier: "presenter",
    })),
  };
}

function documentPreview(asset, file, notes) {
  const slides = countSlides(readText(asset));
  const summary = `${file} · ${slides} slide${slides === 1 ? "" : "s"} · ${notes.length} notes`;
  return {
    preview: 1,
    kind: "document",
    summary: summary.slice(0, MAX_SUMMARY),
    page_count: 1,
    pages: [],
  };
}

function notesPreview(file, notes) {
  const summary = `${file} · ${notes.length} speaker note${notes.length === 1 ? "" : "s"}`;
  return {
    preview: 1,
    kind: "text",
    summary: summary.slice(0, MAX_SUMMARY),
    fields: { notes: notes.length },
  };
}

function previewPresenterOf(asset, notes) {
  const file = path.basename(asset);
  let data = null;
  if (file.endsWith(PRESENT_SUFFIX)) data = documentPreview(asset, file, notes);
  else if (file.endsWith(NOTES_SUFFIX)) data = notesPreview(file, notes);
  if (data === null) {
    throw new Error(`${file}: preview the presenter file or its notes, not this file`);
  }
  fs.writeFileSync(`${asset}.preview.json`, `${JSON.stringify(data, null, 2)}\n`);
  return { file, preview: `${file}.preview.json`, images: [] };
}

function previewPresenter(request) {
  const notes = normalizeNotes(inputsOf(request));
  const entries = (request.assets || []).map((asset) => previewPresenterOf(String(asset), notes));
  return { assets: entries };
}

// --- doctor: the machine, and at full depth one throwaway render.

function nodeCheck() {
  const major = Number(String(process.versions.node).split(".")[0]);
  if (major >= MIN_NODE_MAJOR) {
    return { name: "node", ok: true, detail: `node ${process.version}`, fix: "" };
  }
  return {
    name: "node",
    ok: false,
    detail: `node ${process.version} is older than ${MIN_NODE_MAJOR}`,
    fix: "",
  };
}

function chromiumCheck() {
  const chrome = findChrome();
  if (chrome) {
    return { name: "chromium", ok: true, detail: `Chromium at ${chrome}`, fix: "" };
  }
  return { name: "chromium", ok: false, detail: BROWSER_MISSING, fix: BROWSER_FIX };
}

async function doctor(request) {
  const checks = [nodeCheck(), chromiumCheck()];
  const depth = String(request.depth || "quick");
  if (depth === "full") checks.push(await throwawayCheck(request));
  return { checks };
}

async function throwawayCheck(request) {
  const outDir = path.resolve(request.out_dir || process.cwd());
  const chrome = findChrome();
  if (!chrome) {
    return { name: "render", ok: false, detail: BROWSER_MISSING, fix: BROWSER_FIX };
  }
  try {
    fs.mkdirSync(outDir, { recursive: true });
    const html = path.join(outDir, "doctor-deck.html");
    fs.writeFileSync(html, DOCTOR_HTML);
    const pdf = path.join(outDir, "doctor-deck.pdf");
    clearPages(outDir);
    await renderPdf(html, pdf, chrome, outDir);
    const pages = normalizePages(outDir);
    return {
      name: "render",
      ok: true,
      detail: `rendered a one-slide throwaway (${pages.length} page)`,
      fix: "",
    };
  } catch (error) {
    return {
      name: "render",
      ok: false,
      detail: error && error.message ? error.message : String(error),
      fix: "",
    };
  }
}

main().catch((error) => {
  process.stderr.write(`${error && error.message ? error.message : String(error)}\n`);
  process.exit(1);
});
