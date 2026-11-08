#!/usr/bin/env node
"use strict";

// The deck package runner: slides authored as HTML, exported to a paginated PDF.
//
// facet stages this file with the package and runs it through the managed node
// runtime (`{{node}} {{entry}} {{verb}} --input ... --result ...`). The runner
// renders the slide HTML with the host Chromium through the pinned
// `playwright-core`, waiting for `document.fonts.ready`, switching to print
// media and asking for `preferCSSPageSize` so the page's own `@page` rule wins.
// It then rasterizes one PNG per page with the host `pdftoppm`, records the
// page count, and never downloads a browser or installs poppler.

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { pathToFileURL } = require("node:url");

const PLAYWRIGHT = "playwright-core";
const CHROME_CANDIDATES = [
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
];
const CHROME_FIX = "export CHROME_PATH=/usr/bin/google-chrome";
const CHROME_MISSING =
  "No Chrome/Chromium found; set CHROME_PATH " +
  `(${CHROME_FIX}). Tried: CHROME_PATH, ${CHROME_CANDIDATES.join(", ")}`;
const POPPLER_FIX = "sudo apt-get install -y poppler-utils";
const POPPLER_MISSING = `poppler-utils is required to rasterize the page PNGs (${POPPLER_FIX})`;
const PDFINFO_MISSING = `pdfinfo is required to count the PDF's pages (${POPPLER_FIX})`;
const PDFINFO_PAGE_RE = /^Pages:\s+(\d+)/m;
const MIN_NODE_MAJOR = 22;
const MAX_SUMMARY = 160;
const VIEWPORT = { width: 1060, height: 800 };
const SCALE = 2;
const PAGE_RE = /^page-(\d+)\.png$/;
const RAW_RE = /^\.page-raw-(\d+)\.png$/;
const DOCTOR_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><style>
@page { size: 1280px 720px; margin: 0; }
html, body { margin: 0; height: 100%; }
.slide { width: 1280px; height: 720px; display: grid; place-items: center; }
</style></head><body><section class="slide">deck doctor</section></body></html>
`;

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
  if (verb === "run") return run(request);
  if (verb === "verify") return verify(request);
  if (verb === "preview") return preview(request);
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
  const fuente = inputs.fuente ? String(inputs.fuente) : "";
  return slug(path.basename(fuente, path.extname(fuente)));
}

function slideFile(request) {
  const fuente = inputsOf(request).fuente;
  if (!fuente) throw new Error("fuente is required");
  const file = resolveInput(fuente, pieceBase(request));
  let stat = null;
  try {
    stat = fs.statSync(file);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (stat === null || !stat.isFile()) throw new Error(`fuente: ${file} is not a file`);
  return file;
}

// --- the host Chromium and poppler.

function isExecutable(file) {
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return true;
  } catch (error) {
    return false;
  }
}

function which(name) {
  for (const dir of (process.env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    const candidate = path.join(dir, name);
    if (isExecutable(candidate)) return candidate;
  }
  return "";
}

function findChrome() {
  const found = [process.env.CHROME_PATH, ...CHROME_CANDIDATES].find(
    (candidate) => candidate && isExecutable(candidate),
  );
  return found || "";
}

function renderPdf(htmlPath, pdfPath, chrome) {
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

function pageNames(dir) {
  return numberedPages(dir).map((item) => item.name);
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

function rasterize(pdf, dir) {
  const poppler = which("pdftoppm");
  if (!poppler) throw new Error(POPPLER_MISSING);
  clearPages(dir);
  const prefix = path.join(dir, "page");
  const done = spawnSync(poppler, ["-png", pdf, prefix], { encoding: "utf8" });
  if (done.error) throw new Error(`cannot run pdftoppm: ${done.error.message}`);
  if (done.status !== 0) {
    const output = `${done.stdout || ""}${done.stderr || ""}`.trim();
    throw new Error(`pdftoppm exited ${done.status}: ${output}`);
  }
  const pages = normalizePages(dir);
  if (!pages.length) throw new Error(`pdftoppm wrote no page PNGs for ${path.basename(pdf)}`);
  return pages;
}

function pdfPageCount(pdf) {
  const poppler = which("pdfinfo");
  if (!poppler) throw new Error(PDFINFO_MISSING);
  const done = spawnSync(poppler, [pdf], { encoding: "utf8" });
  if (done.error) throw new Error(`cannot run pdfinfo: ${done.error.message}`);
  const output = `${done.stdout || ""}${done.stderr || ""}`;
  const match = PDFINFO_PAGE_RE.exec(output);
  if (done.status !== 0 || !match) {
    throw new Error(`pdfinfo could not count the pages of ${path.basename(pdf)}`);
  }
  return Number(match[1]);
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

// --- the verbs.

async function run(request) {
  const inputs = inputsOf(request);
  const outDir = path.resolve(request.out_dir);
  fs.mkdirSync(outDir, { recursive: true });
  const source = slideFile(request);
  const chrome = findChrome();
  if (!chrome) throw new Error(CHROME_MISSING);
  if (!which("pdftoppm")) throw new Error(POPPLER_MISSING);
  const name = deckName(inputs);
  const pdf = path.join(outDir, `${name}.pdf`);
  await renderPdf(source, pdf, chrome);
  const pages = rasterize(pdf, outDir);
  const { version } = packageDir(PLAYWRIGHT);
  return {
    tool: { name: "deck", version },
    assets: [
      {
        file: `${name}.pdf`,
        name,
        kind: "document",
        mime: "application/pdf",
        properties: { page_count: pages.length },
        params: inputs,
        seed: seedOf(inputs),
        inputs: [source],
      },
    ],
  };
}

function verify(request) {
  return { assets: (request.assets || []).map(verdictOf) };
}

function verdictOf(asset) {
  const file = path.basename(String(asset));
  const rendered = numberedPages(path.dirname(String(asset))).length;
  const fresh = rendered || pdfPageCount(String(asset));
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
    verifier: "pdftoppm",
  };
}

async function preview(request) {
  const inputs = inputsOf(request);
  const prompt = String(inputs.prompt || "");
  if (!prompt) throw new Error("prompt is required");
  const seed = seedOf(inputs);
  const entries = (request.assets || []).map((asset) => previewOf(asset, seed));
  return { assets: entries };
}

function previewOf(asset, seed) {
  const file = path.basename(String(asset));
  const dir = path.dirname(String(asset));
  let pages = pageNames(dir);
  const recorded = recordedPages(asset);
  if (!pages.length || (recorded !== null && pages.length !== recorded)) {
    pages = rasterize(String(asset), dir);
  }
  const summary = `${file} · ${pages.length} page${pages.length === 1 ? "" : "s"} · seed ${seed}`;
  const data = {
    preview: 1,
    kind: "document",
    summary: summary.slice(0, MAX_SUMMARY),
    page_count: pages.length,
    pages,
  };
  fs.writeFileSync(`${asset}.preview.json`, `${JSON.stringify(data, null, 2)}\n`);
  return { file, preview: `${file}.preview.json`, images: [] };
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
  return { name: "chromium", ok: false, detail: CHROME_MISSING, fix: CHROME_FIX };
}

function popplerCheck() {
  const poppler = which("pdftoppm");
  if (!poppler) {
    return { name: "pdftoppm", ok: false, detail: POPPLER_MISSING, fix: POPPLER_FIX };
  }
  const done = spawnSync(poppler, ["-v"], { encoding: "utf8" });
  const output = `${done.stdout || ""}${done.stderr || ""}`.trim().split("\n")[0];
  if (done.error || (done.status !== 0 && !/pdftoppm version/i.test(output))) {
    return {
      name: "pdftoppm",
      ok: false,
      detail: output || `pdftoppm -v exited ${done.status}`,
      fix: POPPLER_FIX,
    };
  }
  return { name: "pdftoppm", ok: true, detail: output || `pdftoppm at ${poppler}`, fix: "" };
}

async function doctor(request) {
  const checks = [nodeCheck(), chromiumCheck(), popplerCheck()];
  const depth = String(request.depth || "quick");
  if (depth === "full") checks.push(await throwawayCheck(request));
  return { checks };
}

async function throwawayCheck(request) {
  const outDir = path.resolve(request.out_dir || process.cwd());
  const chrome = findChrome();
  if (!chrome) {
    return { name: "render", ok: false, detail: CHROME_MISSING, fix: CHROME_FIX };
  }
  if (!which("pdftoppm")) {
    return { name: "render", ok: false, detail: POPPLER_MISSING, fix: POPPLER_FIX };
  }
  try {
    fs.mkdirSync(outDir, { recursive: true });
    const html = path.join(outDir, "doctor-deck.html");
    fs.writeFileSync(html, DOCTOR_HTML);
    const pdf = path.join(outDir, "doctor-deck.pdf");
    await renderPdf(html, pdf, chrome);
    const pages = rasterize(pdf, outDir);
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
