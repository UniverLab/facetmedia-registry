#!/usr/bin/env node
"use strict";

// The turntable recipe: a Three.js scene that turns a CAD model on a camera orbit.
//
// The piece author builds the vendored tree offline with its own build.mjs;
// this module runs in the copied workDir, embeds the model and the eight orbit
// scalars into index.html, and enforces the recipe rules before HyperFrames'
// check and render. A composition that would stop being a pure function of
// time, or that would fetch a remote asset, fails here instead.
//
// It imports only node builtins so it runs before any dependency is linked.

const fs = require("node:fs");
const path = require("node:path");

const TEXT_EXTENSIONS = new Set([
  ".html",
  ".htm",
  ".tmpl",
  ".json",
  ".js",
  ".mjs",
  ".cjs",
  ".ts",
  ".css",
  ".svg",
  ".xml",
  ".txt",
  ".md",
]);
const URL_RE = /https?:\/\/[^\s"'`<>()\\]+/g;
const METADATA_KEYS = ["$schema", "registry"];
const VENDOR_DIR = "vendor";
const GLB_MARKER = '/* GLB */""';
const TURNTABLE_MARKER = "/* TURNTABLE */";
const DATA_OPENER = "const DATA = {";
const VENDOR_PREFIX = "./vendor/";
const DEFAULTS = {
  "orbit-radius": 9,
  "orbit-height": 11,
  "orbit-start": -0.9,
  "orbit-fraction": 0.55,
  "center-x": 3.0,
  "center-y": 0.6,
  "center-z": -2.25,
  duration: 8,
};

function turntableSetup(workDir, inputs, base) {
  const encoded = modelBase64(inputs, base);
  const templateFile = path.join(workDir, "index.html");
  if (!fs.existsSync(templateFile)) throw new Error("composition: index.html not found");
  const template = fs.readFileSync(templateFile, "utf8");
  validateRecipe(template);
  refuseRemoteUrls(workDir);
  const updated = template
    .replace(GLB_MARKER, JSON.stringify(encoded))
    .replace(TURNTABLE_MARKER, turntableData(inputs));
  fs.writeFileSync(templateFile, updated);
}

// --- the model: a required .glb, embedded as base64 so no fetch happens.

function modelBase64(inputs, base) {
  if (!inputs["model-glb"]) throw new Error("model-glb is required");
  const file = resolveInput(inputs["model-glb"], base);
  if (!fs.existsSync(file)) throw new Error(`model-glb: ${file} not found`);
  if (path.extname(file).toLowerCase() !== ".glb") {
    throw new Error(`model-glb: ${file} is not a .glb`);
  }
  return fs.readFileSync(file).toString("base64");
}

// --- the recipe: a pure renderAt(t), a local importmap and the two markers.

function validateRecipe(template) {
  refusePattern(
    template,
    /\brequestAnimationFrame\s*\(/,
    "requestAnimationFrame() is not allowed; renderAt(t) must be a pure function of time",
  );
  refusePattern(
    template,
    /\bperformance\s*\.\s*now\s*\(/,
    "performance.now() is not allowed; renderAt(t) must be a pure function of time",
  );
  requireText(template, "renderAt", "renderAt(t) is required for the seek-based timeline");
  requireText(template, "hf-seek", "hf-seek is required; HyperFrames seeks each frame");
  requireText(
    template,
    "event.detail.waitUntil",
    "event.detail.waitUntil is required so HyperFrames waits for the model to load",
  );
  requireOnce(template, GLB_MARKER);
  requireTurntableMarker(template);
  validateImportmap(template);
}

function refusePattern(template, pattern, message) {
  if (pattern.test(template)) throw new Error(message);
}

function requireText(template, text, message) {
  if (!template.includes(text)) throw new Error(message);
}

function requireOnce(template, marker) {
  const count = occurrences(template, marker);
  if (count !== 1) throw new Error(`${marker} must appear exactly once, found ${count}`);
}

function requireTurntableMarker(template) {
  requireOnce(template, TURNTABLE_MARKER);
  const opener = template.indexOf(DATA_OPENER);
  if (opener === -1) throw new Error(`${DATA_OPENER} is required for the orbit scalars`);
  const closer = template.indexOf("};", opener);
  const marker = template.indexOf(TURNTABLE_MARKER);
  if (closer === -1 || marker < opener || marker > closer) {
    throw new Error(`${TURNTABLE_MARKER} must sit inside ${DATA_OPENER}`);
  }
}

function validateImportmap(template) {
  const match = /<script\b[^>]*type\s*=\s*["']importmap["'][^>]*>([\s\S]*?)<\/script>/i.exec(
    template,
  );
  if (!match) throw new Error("importmap is required; pin three and three/addons/ to ./vendor/");
  let imports;
  try {
    imports = JSON.parse(match[1]).imports || {};
  } catch (error) {
    throw new Error(`importmap: not valid JSON (${error.message})`);
  }
  for (const name of ["three", "three/addons/"]) {
    const value = imports[name];
    if (typeof value !== "string" || !value.startsWith(VENDOR_PREFIX)) {
      throw new Error(
        `importmap: ${name} must resolve to a local ${VENDOR_PREFIX} path, got ${value || "nothing"}`,
      );
    }
  }
}

function occurrences(text, needle) {
  return text.split(needle).length - 1;
}

// --- the eight flat scalars, injected into the DATA literal.

function turntableData(inputs) {
  const values = {};
  for (const [name, fallback] of Object.entries(DEFAULTS)) {
    values[name] = scalarOf(inputs, name, fallback);
  }
  const orbit = {
    radius: values["orbit-radius"],
    height: values["orbit-height"],
    start: values["orbit-start"],
    fraction: values["orbit-fraction"],
  };
  const center = [values["center-x"], values["center-y"], values["center-z"]];
  return (
    `"orbit":${JSON.stringify(orbit)},` +
    `"center":${JSON.stringify(center)},` +
    `"duration":${JSON.stringify(values.duration)},`
  );
}

function scalarOf(inputs, name, fallback) {
  const raw = inputs[name];
  if (raw === undefined || raw === null) return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error(`${name} must be a finite number, got ${raw}`);
  return value;
}

// --- the vendoring rule: the composition's own files never fetch a remote URL.
//
// The vendor/ subtree is skipped: vendored third-party files carry license and
// documentation URLs in comments that are never fetched, so scanning them
// would reject the package's own vendor files. The rest is scanned in full.

function refuseRemoteUrls(workDir) {
  const allowed = metadataUrls(path.join(workDir, "hyperframes.json"));
  for (const file of walkFiles(workDir)) {
    const relative = path.relative(workDir, file);
    if (relative.split(path.sep)[0] === VENDOR_DIR) continue;
    if (!TEXT_EXTENSIONS.has(path.extname(file).toLowerCase())) continue;
    let text = fs.readFileSync(file, "utf8");
    if (path.basename(file) === "hyperframes.json") {
      for (const url of allowed) text = text.split(url).join("");
    }
    const found = text.match(URL_RE);
    if (found) {
      throw new Error(
        `${relative}: remote URL ${found[0]} is not allowed; vendor the asset into the composition`,
      );
    }
  }
}

function metadataUrls(file) {
  try {
    const data = JSON.parse(fs.readFileSync(file, "utf8"));
    return METADATA_KEYS.map((key) => data[key]).filter(
      (value) => typeof value === "string" && value,
    );
  } catch (error) {
    return [];
  }
}

function walkFiles(dir) {
  const found = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...walkFiles(full));
    else if (entry.isFile()) found.push(full);
  }
  return found;
}

function resolveInput(value, base) {
  const text = String(value);
  return path.isAbsolute(text) ? text : path.resolve(base, text);
}

module.exports = { turntableSetup };
