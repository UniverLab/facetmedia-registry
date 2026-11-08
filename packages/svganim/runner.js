#!/usr/bin/env node
"use strict";

// The svganim package runner: a Node script bakes an SVG, this wraps it.
//
// facet stages this file with the package and runs it through the managed
// node runtime (`{{node}} {{entry}} {{verb}} --input ... --result ...`).
// The piece's `guion` owns the drawing; this script only resolves the pinned
// npm tree the tarballs leave without node_modules links, runs the guion with
// the `datos` path, refuses an SVG that is not self-contained and text as
// <text>, renders the 2x PNG with the pinned sharp, and writes the image
// preview. It imports nothing but node builtins, so it runs before any
// dependency is linked.

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const MAX_SUMMARY = 160;
const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
//: sharp's density is DPI; 144 is the SVG's 72 default at 2x.
const PNG_DENSITY = 144;
const MAX_BUFFER = 64 * 1024 * 1024;
const FOREIGN_PLATFORM =
  /(darwin|win32|android|freebsd|openbsd|netbsd|sunos|aix|ia32|arm|wasm|musl|ppc64|s390x|riscv64)/i;

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
  ensureLinks();
  if (verb === "doctor") return doctor();
  if (verb === "run") return run(request);
  if (verb === "verify") return verify(request);
  if (verb === "preview") return preview(request);
  throw new Error(`${verb}: unknown verb (this runner has: run, verify, preview, doctor)`);
}

// --- the npm dependency tree: peer and optional links where ESM resolves them.

function nodePathDirs() {
  return (process.env.FACET_NODE_PATH || "").split(path.delimiter).filter(Boolean);
}

function firstPackageDir() {
  const dirs = nodePathDirs();
  if (!dirs.length) throw new Error("FACET_NODE_PATH is empty; run this runner through facet");
  return dirs[0];
}

function readManifest(dir) {
  const file = path.join(dir, "package.json");
  const manifest = JSON.parse(fs.readFileSync(file, "utf8"));
  return { dir, name: manifest.name, version: manifest.version, manifest };
}

function declaredPackages() {
  return nodePathDirs().map(readManifest);
}

function ensureLinks() {
  const packages = declaredPackages();
  const byName = new Map();
  for (const pkg of packages) {
    const found = byName.get(pkg.name) || [];
    found.push(pkg);
    byName.set(pkg.name, found);
  }
  for (const pkg of packages) {
    const dependencies = declaredDependencies(pkg.manifest);
    for (const [name, range] of Object.entries(dependencies)) {
      const chosen = maxSatisfying(byName.get(name) || [], range);
      if (!chosen) {
        throw new Error(
          `${pkg.name}@${pkg.version} needs ${name} ${range}, but no extracted package satisfies it`,
        );
      }
      linkPackage(pkg.dir, name, chosen.dir);
    }
  }
}

function declaredDependencies(manifest) {
  const dependencies = Object.assign({}, manifest.dependencies || {});
  const peers = manifest.peerDependencies || {};
  const meta = manifest.peerDependenciesMeta || {};
  for (const [name, range] of Object.entries(peers)) {
    if (meta[name] && meta[name].optional) continue;
    if (!(name in dependencies)) dependencies[name] = range;
  }
  for (const [name, range] of Object.entries(manifest.optionalDependencies || {})) {
    if (platformAllowed(name) && !(name in dependencies)) dependencies[name] = range;
  }
  return dependencies;
}

function platformAllowed(name) {
  if (FOREIGN_PLATFORM.test(name)) return false;
  if (name.includes("linux") && !name.includes("linux-x64")) return false;
  return true;
}

function linkPackage(packageDir, dependency, target) {
  const linkPath = path.join(packageDir, "node_modules", ...dependency.split("/"));
  fs.mkdirSync(path.dirname(linkPath), { recursive: true });
  const wanted = path.resolve(target);
  let existing = "";
  try {
    const stat = fs.lstatSync(linkPath);
    existing = stat.isSymbolicLink()
      ? path.resolve(path.dirname(linkPath), fs.readlinkSync(linkPath))
      : "present";
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (existing === wanted) return;
  if (existing === "present") fs.rmSync(linkPath, { recursive: true, force: true });
  else if (existing) fs.unlinkSync(linkPath);
  fs.symlinkSync(target, linkPath, "dir");
}

// --- resolution: one directory whose children are the staged package names.
//
// NODE_PATH entries are read as node_modules roots, so the staged directories
// are linked under one temp root; the guion and this runner both require
// through it (opentype.js for the former, sharp for the latter).

function moduleRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "svganim-modules-"));
  for (const pkg of declaredPackages()) {
    const linkPath = path.join(root, ...pkg.name.split("/"));
    fs.mkdirSync(path.dirname(linkPath), { recursive: true });
    fs.symlinkSync(pkg.dir, linkPath, "dir");
  }
  return root;
}

function maxSatisfying(candidates, range) {
  let best = null;
  for (const candidate of candidates) {
    if (!satisfies(candidate.version, range)) continue;
    if (best === null || compareVersions(candidate.version, best.version) > 0) best = candidate;
  }
  return best;
}

function parseVersion(text) {
  const cleaned = String(text).split("+")[0];
  const dash = cleaned.indexOf("-");
  const core = dash === -1 ? cleaned : cleaned.slice(0, dash);
  const pre = dash === -1 ? [] : cleaned.slice(dash + 1).split(".");
  const numbers = core.split(".").map((part) => Number.parseInt(part, 10) || 0);
  while (numbers.length < 3) numbers.push(0);
  return { major: numbers[0], minor: numbers[1], patch: numbers[2], pre };
}

function compareVersions(left, right) {
  const a = parseVersion(left);
  const b = parseVersion(right);
  for (const key of ["major", "minor", "patch"]) {
    if (a[key] !== b[key]) return a[key] < b[key] ? -1 : 1;
  }
  return comparePrerelease(a.pre, b.pre);
}

function comparePrerelease(a, b) {
  if (!a.length && !b.length) return 0;
  if (!a.length) return 1;
  if (!b.length) return -1;
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    if (a[index] === undefined) return -1;
    if (b[index] === undefined) return 1;
    const numericA = /^\d+$/.test(a[index]);
    const numericB = /^\d+$/.test(b[index]);
    if (numericA && numericB) {
      const difference = Number(a[index]) - Number(b[index]);
      if (difference) return difference < 0 ? -1 : 1;
    } else if (numericA !== numericB) {
      return numericA ? -1 : 1;
    } else if (a[index] !== b[index]) {
      return a[index] < b[index] ? -1 : 1;
    }
  }
  return 0;
}

function satisfies(version, range) {
  const text = String(range || "").trim().replace(/(>=|<=|>|<|=|~|\^)\s+/g, "$1");
  if (!text || text === "*" || text === "latest") return true;
  return text.split("||").some((group) => satisfiesGroup(version, group.trim()));
}

function satisfiesGroup(version, group) {
  if (!group) return true;
  const hyphen = /^(.+?)\s+-\s+(.+)$/.exec(group);
  if (hyphen) return satisfiesHyphen(version, hyphen[1], hyphen[2]);
  return group
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => satisfiesToken(version, token));
}

function satisfiesHyphen(version, low, high) {
  if (compareVersions(version, normalizeVersion(low)) < 0) return false;
  const parts = String(high).trim().split(".");
  if (parts.length >= 3) return compareVersions(version, normalizeVersion(high)) <= 0;
  const upper = parseVersion(high);
  const bumped =
    parts.length === 1 ? `${upper.major + 1}.0.0` : `${upper.major}.${upper.minor + 1}.0`;
  return compareVersions(version, bumped) < 0;
}

function satisfiesToken(version, token) {
  if (token === "*" || token === "x" || token === "X") return true;
  if (/[xX*]/.test(token)) return satisfiesWildcard(version, token);
  const caret = token.startsWith("^");
  const tilde = token.startsWith("~");
  const operator = /^(>=|<=|>|<|=)/.exec(token);
  const bare = !caret && !tilde && !operator && /^\d+(\.\d+)?$/.test(token);
  if (bare) {
    const parts = token.split(".").length;
    const upper =
      parts === 1
        ? `${Number(token) + 1}.0.0`
        : `${token.split(".")[0]}.${Number(token.split(".")[1]) + 1}.0`;
    return (
      compareVersions(version, normalizeVersion(token)) >= 0 &&
      compareVersions(version, upper) < 0
    );
  }
  const prefix = caret || tilde ? 1 : operator ? operator[1].length : 0;
  const body = normalizeVersion(token.slice(prefix));
  const order = compareVersions(version, body);
  if (caret) return order >= 0 && compareVersions(version, caretUpper(body)) < 0;
  if (tilde) {
    const base = parseVersion(body);
    return order >= 0 && compareVersions(version, `${base.major}.${base.minor + 1}.0`) < 0;
  }
  const op = operator ? operator[1] : "=";
  if (op === ">=") return order >= 0;
  if (op === "<=") return order <= 0;
  if (op === ">") return order > 0;
  if (op === "<") return order < 0;
  return order === 0;
}

function satisfiesWildcard(version, token) {
  const operator = /^(>=|<=|>|<|=)/.exec(token);
  const parts = token.slice(operator ? operator[1].length : 0).split(".");
  const parsed = parseVersion(version);
  const values = [parsed.major, parsed.minor, parsed.patch];
  for (const [index, part] of parts.entries()) {
    if (part === "x" || part === "X" || part === "*") break;
    if (Number(part) !== values[index]) return false;
  }
  return true;
}

function normalizeVersion(text) {
  const parsed = parseVersion(text);
  const pre = parsed.pre.length ? `-${parsed.pre.join(".")}` : "";
  return `${parsed.major}.${parsed.minor}.${parsed.patch}${pre}`;
}

function caretUpper(base) {
  const parsed = parseVersion(base);
  if (parsed.major > 0) return `${parsed.major + 1}.0.0`;
  if (parsed.minor > 0) return `0.${parsed.minor + 1}.0`;
  return `0.0.${parsed.patch + 1}`;
}

// --- the doctor: the two pinned packages the bake needs.

function doctor() {
  return { checks: [packageCheck("opentype.js"), packageCheck("sharp")] };
}

function packageCheck(name) {
  const found = declaredPackages().find((pkg) => pkg.name === name);
  if (found) {
    return { name, ok: true, detail: `${name} ${found.version} extracted`, fix: "" };
  }
  return {
    name,
    ok: false,
    detail: `the pinned ${name} package is not extracted`,
    fix: "run through facet so the pinned npm tarballs land under the facet home",
  };
}

function versionOf(name) {
  const found = declaredPackages().find((pkg) => pkg.name === name);
  return found ? String(found.version) : "";
}

// --- resolving the piece's paths.

function inputsOf(request) {
  return request.inputs || {};
}

function pieceBase(request) {
  return request.piece_dir || process.cwd();
}

function resolveInput(value, base, field) {
  if (!value) throw new Error(`${field} is required`);
  const text = String(value);
  const file = path.isAbsolute(text) ? text : path.resolve(base, text);
  if (!fs.existsSync(file)) throw new Error(`${field}: ${file} not found`);
  return file;
}

function slug(text) {
  const value = String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return value || "svganim";
}

function baseName(file) {
  return slug(path.basename(String(file)).replace(/\.c?js$/i, ""));
}

// --- the bake: the guion draws, this validates what it drew.

function bake(guion, datos, piece, modules) {
  const node = process.env.FACET_NODE;
  if (!node) throw new Error("FACET_NODE is not set; run this runner through facet");
  const done = spawnSync(node, [guion, datos], {
    cwd: piece,
    env: { ...process.env, NODE_PATH: modules },
    encoding: "utf8",
    maxBuffer: MAX_BUFFER,
  });
  if (done.error) throw new Error(`cannot run the guion: ${done.error.message}`);
  if (done.status !== 0) {
    const detail = `${done.stdout || ""}${done.stderr || ""}`.trim();
    throw new Error(`guion exited ${done.status}: ${detail}`);
  }
  if (!done.stdout || !done.stdout.trim()) {
    throw new Error(`guion wrote no SVG to stdout`);
  }
  return done.stdout;
}

function validateSvg(text, label) {
  const body = String(text).trim();
  if (body.indexOf("<svg") === -1 || !body.endsWith("</svg>")) {
    throw new Error(
      `${label}: not a well-formed SVG document; write one <svg ...> root ending in </svg>`,
    );
  }
  if (/<script\b/i.test(body)) {
    throw new Error(
      `${label}: the SVG carries a <script>; GitHub strips scripts, so animate with CSS @keyframes only`,
    );
  }
  if (!/@keyframes\b/.test(body)) {
    throw new Error(
      `${label}: the SVG carries no @keyframes; the animation must live in the document as CSS keyframes`,
    );
  }
  if (/<text\b/i.test(body)) {
    throw new Error(
      `${label}: the SVG carries a <text> element; opentype.js must convert every label to a <path>, so a baked SVG has no <text>`,
    );
  }
}

async function renderPng(modules, svgText, png) {
  const sharp = require(path.join(modules, "sharp"));
  await sharp(Buffer.from(svgText), { density: PNG_DENSITY }).png().toFile(png);
  if (!fs.existsSync(png)) throw new Error(`sharp wrote no ${path.basename(png)}`);
}

// --- the verbs.

async function run(request) {
  const inputs = inputsOf(request);
  const outDir = path.resolve(request.out_dir);
  fs.mkdirSync(outDir, { recursive: true });
  const piece = pieceBase(request);
  const guion = resolveInput(inputs.guion, piece, "guion");
  const datos = resolveInput(inputs.datos, piece, "datos");
  const name = baseName(guion);
  const svg = path.join(outDir, `${name}.svg`);
  const png = path.join(outDir, `${name}.png`);
  const modules = moduleRoot();
  try {
    const text = bake(guion, datos, piece, modules);
    validateSvg(text, `${name}.svg`);
    fs.writeFileSync(svg, text);
    await renderPng(modules, text, png);
  } finally {
    fs.rmSync(modules, { recursive: true, force: true });
  }
  return {
    tool: { name: "opentype.js", version: versionOf("opentype.js") },
    assets: [
      {
        file: `${name}.svg`,
        name,
        kind: "image",
        mime: "image/svg+xml",
        properties: {},
        params: inputs,
        seed: 0,
        inputs: [guion, datos],
      },
      {
        file: `${name}.png`,
        name,
        kind: "image",
        mime: "image/png",
        properties: {},
        params: inputs,
        seed: 0,
        inputs: [guion, datos],
      },
    ],
  };
}

function verify(request) {
  return { assets: (request.assets || []).map((asset) => verdictOf(asset)) };
}

function verdictOf(asset) {
  const file = path.basename(String(asset));
  try {
    const ok = file.endsWith(".png") ? pngOk(String(asset)) : svgOk(String(asset));
    return { file, passed: ok, metrics: {}, thresholds: {}, verifier: "svganim" };
  } catch (error) {
    return {
      file,
      passed: false,
      metrics: { error: error.message },
      thresholds: {},
      verifier: "svganim",
    };
  }
}

function svgOk(file) {
  validateSvg(fs.readFileSync(file, "utf8"), path.basename(file));
  return true;
}

function pngOk(file) {
  const fd = fs.openSync(file, "r");
  try {
    const buffer = Buffer.alloc(8);
    fs.readSync(fd, buffer, 0, 8, 0);
    if (!buffer.equals(PNG_SIGNATURE)) throw new Error(`${path.basename(file)}: bad PNG signature`);
  } finally {
    fs.closeSync(fd);
  }
  return true;
}

function preview(request) {
  const entries = (request.assets || []).map((asset) => previewOf(asset, request));
  return { assets: entries };
}

function previewOf(asset, request) {
  const file = path.basename(String(asset));
  const name = slug(file.replace(/\.(svg|png)$/i, ""));
  const { width, height } = imageSize(String(asset));
  const prompt = previewPrompt(request, name);
  const data = {
    preview: 1,
    kind: "image",
    summary: `${name} · ${width}x${height} · svganim`.slice(0, MAX_SUMMARY),
    name,
    prompt,
    seed: 0,
    width,
    height,
  };
  fs.writeFileSync(
    path.join(path.dirname(String(asset)), `${file}.preview.json`),
    `${JSON.stringify(data, null, 2)}\n`,
  );
  return { file, preview: `${file}.preview.json`, images: [] };
}

function previewPrompt(request, name) {
  const guion = String(inputsOf(request).guion || "");
  if (!guion) return `svganim · ${name}`.slice(0, MAX_SUMMARY);
  return path
    .basename(guion)
    .replace(/\.c?js$/i, "")
    .slice(0, MAX_SUMMARY);
}

function imageSize(file) {
  if (file.endsWith(".png")) return pngSize(file);
  return svgSize(file);
}

function pngSize(file) {
  const fd = fs.openSync(file, "r");
  try {
    const buffer = Buffer.alloc(24);
    fs.readSync(fd, buffer, 0, 24, 0);
    if (
      buffer.length < 24 ||
      buffer.readUInt32BE(8) !== 13 ||
      buffer.toString("ascii", 12, 16) !== "IHDR"
    ) {
      throw new Error(`${path.basename(file)}: no IHDR`);
    }
    return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
  } finally {
    fs.closeSync(fd);
  }
}

function svgSize(file) {
  const text = fs.readFileSync(file, "utf8");
  const tag = /<svg[^>]*>/.exec(text);
  if (!tag) throw new Error(`${path.basename(file)}: no <svg element`);
  const attrs = tag[0];
  const width = Number(/\bwidth="(\d+(?:\.\d+)?)"/.exec(attrs)?.[1]);
  const height = Number(/\bheight="(\d+(?:\.\d+)?)"/.exec(attrs)?.[1]);
  if (width > 0 && height > 0) return { width: Math.round(width), height: Math.round(height) };
  const viewBox = /\bviewBox="[^"]*?([\d.]+)\s+([\d.]+)"/.exec(attrs);
  if (viewBox) {
    return { width: Math.round(Number(viewBox[1])), height: Math.round(Number(viewBox[2])) };
  }
  return { width: 1, height: 1 };
}

main().catch((error) => {
  process.stderr.write(`svganim runner: ${error.message}\n`);
  process.exit(1);
});
