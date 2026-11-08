#!/usr/bin/env node
"use strict";

// The hyperframes package runner: the pinned HyperFrames CLI, wrapped.
//
// facet stages this file with the package and runs it through the managed
// node runtime (`{{node}} {{entry}} {{verb}} --input ... --result ...`).
// HyperFrames owns `check` and `render`; this script only resolves the npm
// dependency tree the pinned tarballs leave without node_modules links,
// refuses remote URLs, runs check before render, probes the MP4 with the
// host ffprobe, and writes the video preview. `hyperframes.loop` reuses the
// same check-first path for GIF and MOV-with-alpha exports. It imports
// nothing but node builtins, so it runs before any dependency is linked.

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { giroSetup } = require("./giro.js");
const { narradoSetup } = require("./narrado.js");
const { personajeSetup } = require("./personaje.js");

const BROWSER_VAR = "HYPERFRAMES_BROWSER_PATH";
const LAB_BROWSER = "/usr/bin/google-chrome";
const FFMPEG_MISSING =
  "ffmpeg and ffprobe are required to encode video (sudo apt-get install -y ffmpeg)";
const WORKERS = "2";
const MAX_SUMMARY = 160;
const LOOP_FORMATS = {
  gif: { extension: ".gif", cli: "gif", mime: "image/gif" },
  "mov-alpha": { extension: ".mov", cli: "mov", mime: "video/quicktime" },
};
const ALPHA_PIX_FMT = /a$|argb|rgba|bgra|abgr|yuva|gbrap/i;
const METADATA_KEYS = ["$schema", "registry"];
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
const FOREIGN_PLATFORM =
  /(darwin|win32|android|freebsd|openbsd|netbsd|sunos|aix|ia32|arm|wasm|musl|ppc64|s390x|riscv64)/i;

// --- the entry point and the file protocol.

function main() {
  const { verb, options } = parseArgs(process.argv.slice(2));
  const request = readRequest(options.input);
  const result = dispatch(verb, request);
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

function dispatch(verb, request) {
  ensureLinks();
  if (verb === "doctor") return doctor();
  requireBrowser();
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
  return group
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => satisfiesToken(version, token));
}

function satisfiesToken(version, token) {
  if (token === "*" || token === "x" || token === "X") return true;
  if (/[xX*]/.test(token)) return satisfiesWildcard(version, token);
  const caret = token.startsWith("^");
  const tilde = token.startsWith("~");
  const operator = /^(>=|<=|>|<|=)/.exec(token);
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

// --- the machine: the host Chromium bridge and the host ffmpeg.

function isExecutable(file) {
  if (!file) return false;
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return true;
  } catch (error) {
    return false;
  }
}

function browserProblem() {
  const given = process.env[BROWSER_VAR] || "";
  if (isExecutable(given)) return null;
  return `${BROWSER_VAR} is not set or not executable; set it to the host Chromium, for example ${LAB_BROWSER}`;
}

function requireBrowser() {
  const problem = browserProblem();
  if (problem) throw new Error(problem);
}

function which(name) {
  for (const dir of (process.env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    const candidate = path.join(dir, name);
    if (isExecutable(candidate)) return candidate;
  }
  return "";
}

function doctor() {
  return { checks: [chromiumCheck(), ffmpegCheck()] };
}

function chromiumCheck() {
  const problem = browserProblem();
  if (!problem) {
    return {
      name: "chromium",
      ok: true,
      detail: `Chromium at ${process.env[BROWSER_VAR]}`,
      fix: "",
    };
  }
  return {
    name: "chromium",
    ok: false,
    detail: problem,
    fix: `export ${BROWSER_VAR}=${LAB_BROWSER}`,
  };
}

function ffmpegCheck() {
  const missing = ["ffmpeg", "ffprobe"].filter((name) => !which(name));
  if (missing.length) {
    return { name: "ffmpeg", ok: false, detail: FFMPEG_MISSING, fix: "" };
  }
  return { name: "ffmpeg", ok: true, detail: "ffmpeg and ffprobe are on PATH", fix: "" };
}

// --- resolving the piece's paths.

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

function isDirectory(target) {
  try {
    return fs.statSync(target).isDirectory();
  } catch (error) {
    return false;
  }
}

function compositionDir(request) {
  const inputs = inputsOf(request);
  if (!inputs.composicion) throw new Error("composicion is required");
  const dir = resolveInput(inputs.composicion, pieceBase(request));
  if (!isDirectory(dir)) throw new Error(`composicion: ${dir} is not a directory`);
  for (const name of ["hyperframes.json", "index.tmpl"]) {
    if (!fs.existsSync(path.join(dir, name))) {
      throw new Error(`composicion: ${dir} has no ${name}`);
    }
  }
  return dir;
}

function slug(text) {
  const value = String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return value || "video";
}

function compositionName(inputs) {
  const raw = inputs && inputs.composicion ? String(inputs.composicion).replace(/[\\/]+$/, "") : "";
  if (!raw) return "video";
  return slug(path.basename(raw));
}

function clipPaths(inputs, base) {
  return (inputs.audio || []).map((item) => {
    if (!item || !item.clip) throw new Error("an audio item has no clip");
    return resolveInput(item.clip, base);
  });
}

function copyClips(inputs, base, target) {
  for (const clip of clipPaths(inputs, base)) {
    if (!fs.existsSync(clip)) throw new Error(`audio clip ${clip} not found`);
    fs.copyFileSync(clip, path.join(target, path.basename(clip)));
  }
}

// --- the diagram: stable Mermaid ids, a validated GSAP timeline.

const DIAGRAMA_KINDS = new Set(["show", "draw", "fade"]);
const DEFAULT_DUR = 0.4;
const SVG_NAMESPACE = /^https?:\/\/www\.w3\.org\//;

function diagramaSetup(workDir, inputs, base) {
  if (!inputs["diagrama-svg"]) throw new Error("diagrama-svg is required");
  const svgFile = resolveInput(inputs["diagrama-svg"], base);
  if (!fs.existsSync(svgFile)) throw new Error(`diagrama-svg: ${svgFile} not found`);
  const svg = fs.readFileSync(svgFile, "utf8");
  const stray = svgUrls(svg);
  if (stray) {
    throw new Error(
      `diagrama-svg: remote URL ${stray} is not allowed; vendor the asset into the diagram`,
    );
  }
  const { ids, dataIds } = svgIdentifiers(svg);
  const source = Array.isArray(inputs.animacion) ? inputs.animacion : [];
  const pasos = source.map((paso, index) => pasoOf(paso, index, ids, dataIds));
  fs.copyFileSync(svgFile, path.join(path.dirname(workDir), path.basename(svgFile)));
  injectTimeline(path.join(workDir, "index.tmpl"), pasos);
}

function svgUrls(svg) {
  for (const url of svg.match(URL_RE) || []) {
    if (!SVG_NAMESPACE.test(url)) return url;
  }
  return "";
}

function svgIdentifiers(svg) {
  const ids = new Set();
  const dataIds = new Set();
  for (const match of svg.matchAll(/\bid="([^"]+)"/g)) ids.add(match[1]);
  for (const match of svg.matchAll(/\bdata-id="([^"]+)"/g)) dataIds.add(match[1]);
  return { ids, dataIds };
}

function pasoOf(paso, index, ids, dataIds) {
  if (!paso || typeof paso !== "object") throw new Error(`animacion[${index}] is not a table`);
  const selector = String(paso.selector || "");
  validateSelector(selector, ids, dataIds);
  if (!DIAGRAMA_KINDS.has(paso.kind)) {
    const got = paso.kind === undefined ? "nothing" : String(paso.kind);
    throw new Error(`animacion[${index}]: kind must be show, draw or fade, got ${got}`);
  }
  const at = Number(paso.at);
  if (!Number.isFinite(at)) throw new Error(`animacion[${index}]: at must be a number`);
  const dur = paso.dur === undefined || paso.dur === null ? DEFAULT_DUR : Number(paso.dur);
  if (!Number.isFinite(dur) || dur <= 0) {
    throw new Error(`animacion[${index}]: dur must be a positive number`);
  }
  return { selector, at, kind: paso.kind, dur };
}

function validateSelector(selector, ids, dataIds) {
  if (!selector) throw new Error("animacion: a paso has no selector");
  const refs = selectorRefs(selector);
  if (!refs.length) throw new Error(`animacion: selector ${selector} names no id`);
  for (const ref of refs) {
    if (!refPresent(ref, ids, dataIds)) {
      throw new Error(`animacion: selector ${selector} names an unknown id`);
    }
  }
}

function selectorRefs(selector) {
  const pattern = /#[\w-]+|\[id\^="([^"]+)"\]|\[id="([^"]+)"\]|\[data-id="([^"]+)"\]/g;
  const refs = [];
  for (const match of selector.matchAll(pattern)) {
    refs.push({ token: match[0], prefix: match[1], id: match[2], dataId: match[3] });
  }
  return refs;
}

function refPresent(ref, ids, dataIds) {
  if (ref.token.startsWith("#")) return ids.has(ref.token.slice(1));
  if (ref.prefix !== undefined) return [...ids].some((id) => id.startsWith(ref.prefix));
  if (ref.id !== undefined) return ids.has(ref.id);
  return dataIds.has(ref.dataId);
}

function timelineScript(pasos) {
  const body = TIMELINE_TEMPLATE.replace("__PASOS__", JSON.stringify(pasos));
  return ["<script>", body, "</script>"].join("\n");
}

function injectTimeline(templateFile, pasos) {
  const template = fs.readFileSync(templateFile, "utf8");
  const script = timelineScript(pasos);
  const updated = template.includes("</body>")
    ? template.replace("</body>", [script, "</body>"].join("\n"))
    : [template, script].join("\n");
  fs.writeFileSync(templateFile, updated);
}

// Selectors are plain strings built by concatenation; the HyperFrames bundler
// rejects template literals in selectors, so this script carries none.
const TIMELINE_TEMPLATE = [
  "(function () {",
  "  var pasos = __PASOS__;",
  "  var tl = gsap.timeline({ paused: true });",
  "  function drawEach(targets, paso) {",
  "    Array.prototype.forEach.call(targets, function (target) {",
  '      var path = target.tagName.toLowerCase() === "path" ? target : target.querySelector("path");',
  '      if (!path || typeof path.getTotalLength !== "function") return;',
  "      var length = path.getTotalLength();",
  "      tl.fromTo(path, { strokeDasharray: length, strokeDashoffset: length },",
  '        { strokeDashoffset: 0, duration: paso.dur, ease: "power1.inOut" }, paso.at);',
  "      var head = path.nextElementSibling;",
  '      if (head && head.classList && head.classList.contains("arrow")) {',
  '        tl.from(head, { opacity: 0, duration: paso.dur * 0.5 }, paso.at + paso.dur * 0.8);',
  "      }",
  "    });",
  "  }",
  "  pasos.forEach(function (paso) {",
  "    var targets = document.querySelectorAll(paso.selector);",
  "    if (!targets.length) return;",
  '    if (paso.kind === "show") {',
  '      tl.from(targets, { opacity: 0, scale: 0.85, transformOrigin: "50% 50%", duration: paso.dur, ease: "back.out(2)" }, paso.at);',
  '    } else if (paso.kind === "fade") {',
  '      tl.from(targets, { opacity: 0, duration: paso.dur, ease: "power1.out" }, paso.at);',
  "    } else {",
  "      drawEach(targets, paso);",
  "    }",
  "  });",
  '  var root = document.querySelector("[data-composition-id]");',
  '  var name = root ? root.getAttribute("data-composition-id") : "main";',
  "  window.__timelines = window.__timelines || {};",
  '  window.__timelines[name || "main"] = tl;',
  "  tl.seek(0);",
  "})();",
].join("\n");

function seedOf(inputs) {
  return Number.isInteger(inputs.seed) ? inputs.seed : 0;
}

// --- the self-contained rule: no remote URL survives the copy.

function refuseRemoteUrls(root) {
  const allowed = metadataUrls(path.join(root, "hyperframes.json"));
  for (const file of walkFiles(root)) {
    const relative = path.relative(root, file);
    // Vendored third-party files carry license and documentation URLs in
    // comments that are never fetched; only the composition's own files are
    // held to the self-contained rule.
    if (relative.split(path.sep)[0] === "vendor") continue;
    if (!TEXT_EXTENSIONS.has(path.extname(file).toLowerCase())) continue;
    let text = fs.readFileSync(file, "utf8");
    if (path.basename(file) === "hyperframes.json") {
      for (const url of allowed) text = text.split(url).join("");
    }
    const found = text.match(URL_RE);
    if (found) {
      throw new Error(
        `${path.relative(root, file)}: remote URL ${found[0]} is not allowed; vendor the asset into the composition`,
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

// --- the verbs.

function run(request) {
  const inputs = inputsOf(request);
  const outDir = path.resolve(request.out_dir);
  fs.mkdirSync(outDir, { recursive: true });
  const source = compositionDir(request);
  refuseRemoteUrls(source);
  const name = compositionName(inputs);
  const loop = loopFormatOf(request);
  const extension = loop ? loop.extension : ".mp4";
  const workDir = path.join(outDir, "composition");
  fs.rmSync(workDir, { recursive: true, force: true });
  fs.cpSync(source, workDir, { recursive: true });
  copyClips(inputs, pieceBase(request), workDir);
  if (request.capability === "hyperframes.diagrama") {
    diagramaSetup(workDir, inputs, pieceBase(request));
  }
  if (request.capability === "hyperframes.giro") {
    giroSetup(workDir, inputs, pieceBase(request));
  }
  if (request.capability === "hyperframes.personaje") {
    personajeSetup(workDir, inputs, pieceBase(request));
  }
  if (request.capability === "hyperframes.narrado") {
    narradoSetup(workDir, inputs, pieceBase(request));
  }
  runCli(["check"], workDir);
  runCli(renderArgs(inputs, path.join(outDir, `${name}${extension}`), loop), workDir);
  const entry = readManifest(firstPackageDir());
  return {
    tool: { name: "hyperframes", version: String(entry.version) },
    assets: [
      {
        file: `${name}${extension}`,
        name,
        kind: "video",
        mime: loop ? loop.mime : "video/mp4",
        properties: {},
        params: inputs,
        seed: seedOf(inputs),
        inputs: [source, ...clipPaths(inputs, pieceBase(request))],
      },
    ],
  };
}

function loopFormatOf(request) {
  if (!request || request.capability !== "hyperframes.loop") return null;
  const format = String(inputsOf(request).format || "");
  const spec = LOOP_FORMATS[format];
  if (!spec) {
    throw new Error(`hyperframes.loop: format must be gif or mov-alpha, got ${format || "nothing"}`);
  }
  return spec;
}

function renderArgs(inputs, output, loop) {
  const args = ["render", "--workers", WORKERS];
  if (inputs.fps !== undefined && inputs.fps !== null) args.push("--fps", String(inputs.fps));
  if (loop) args.push("--format", loop.cli);
  args.push("-o", output);
  return args;
}

function runCli(args, cwd) {
  const node = process.env.FACET_NODE;
  if (!node) throw new Error("FACET_NODE is not set; run this runner through facet");
  const cli = path.join(firstPackageDir(), "bin", "hyperframes.mjs");
  const done = spawnSync(node, [cli, ...args], {
    cwd,
    env: {
      ...process.env,
      HYPERFRAMES_NO_TELEMETRY: "1",
      HYPERFRAMES_SKIP_SKILLS: "1",
    },
    encoding: "utf8",
  });
  if (done.error) throw new Error(`cannot run HyperFrames: ${done.error.message}`);
  if (done.status !== 0) {
    const output = `${done.stdout || ""}${done.stderr || ""}`.trim();
    throw new Error(`hyperframes ${args[0]} exited ${done.status}: ${output}`);
  }
  return `${done.stdout || ""}${done.stderr || ""}`;
}

function verify(request) {
  if (!which("ffprobe")) throw new Error(FFMPEG_MISSING);
  return { assets: (request.assets || []).map((asset) => verdictOf(asset, request)) };
}

function verdictOf(asset, request) {
  const file = path.basename(String(asset));
  try {
    const metrics = probe(asset);
    const passed =
      metrics.width > 0 &&
      metrics.height > 0 &&
      metrics.frames > 0 &&
      metrics.fps > 0 &&
      formatOk(asset, request, metrics);
    return { file, passed, metrics, thresholds: {}, verifier: "ffprobe" };
  } catch (error) {
    return {
      file,
      passed: false,
      metrics: { error: error.message },
      thresholds: {},
      verifier: "ffprobe",
    };
  }
}

function preview(request) {
  if (!which("ffprobe")) throw new Error(FFMPEG_MISSING);
  const inputs = inputsOf(request);
  const prompt = String(inputs.prompt || "");
  if (!prompt) throw new Error("prompt is required");
  const seed = seedOf(inputs);
  const entries = (request.assets || []).map((asset) => previewOf(asset, request, prompt, seed));
  return { assets: entries };
}

function previewOf(asset, request, prompt, seed) {
  const inputs = inputsOf(request);
  const file = path.basename(String(asset));
  const metrics = probe(asset);
  const data = {
    preview: 1,
    kind: "video",
    summary: summaryOf(inputs, metrics, seed, formatLabelOf(request)),
    name: compositionName(inputs),
    prompt,
    seed,
    width: metrics.width,
    height: metrics.height,
    length: metrics.frames,
    fps: metrics.fps,
  };
  fs.writeFileSync(
    path.join(path.dirname(String(asset)), `${file}.preview.json`),
    `${JSON.stringify(data, null, 2)}\n`,
  );
  return { file, preview: `${file}.preview.json`, images: [] };
}

function formatLabelOf(request) {
  if (!request || request.capability !== "hyperframes.loop") return "";
  return String(inputsOf(request).format || "");
}

function summaryOf(inputs, metrics, seed, format) {
  let text =
    `${compositionName(inputs)} · ${metrics.width}x${metrics.height} · ` +
    `${metrics.frames}f @ ${metrics.fps}fps · seed ${seed}`;
  if (format) text += ` · ${format}`;
  return text.slice(0, MAX_SUMMARY);
}

function formatOk(asset, request, metrics) {
  const loop = loopFormatOf(request);
  if (!loop) return true;
  if (loop.cli === "gif") return gifHasLoop(String(asset));
  return hasAlphaPixFmt(metrics.pix_fmt);
}

function hasAlphaPixFmt(pixFmt) {
  return ALPHA_PIX_FMT.test(String(pixFmt || ""));
}

function gifHasLoop(file) {
  return fs.readFileSync(file).includes("NETSCAPE2.0");
}

function probe(file) {
  const done = spawnSync(
    which("ffprobe"),
    ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", file],
    { encoding: "utf8" },
  );
  if (done.error) throw new Error(`cannot run ffprobe: ${done.error.message}`);
  if (done.status !== 0) {
    throw new Error(`ffprobe ${path.basename(String(file))} exited ${done.status}`);
  }
  const data = JSON.parse(done.stdout);
  const stream = (data.streams || []).find((item) => item.codec_type === "video");
  if (!stream) throw new Error(`${path.basename(String(file))}: no video stream`);
  const duration = Number((data.format && data.format.duration) || stream.duration || 0);
  const fps = rateOf(stream.avg_frame_rate || stream.r_frame_rate || "0/1");
  let frames = Number(stream.nb_frames || 0);
  if (!Number.isFinite(frames) || frames <= 0) frames = Math.round(duration * fps);
  return {
    width: Number(stream.width) || 0,
    height: Number(stream.height) || 0,
    pix_fmt: String(stream.pix_fmt || ""),
    duration_s: Math.round(duration * 1000) / 1000,
    frames,
    fps,
  };
}

function rateOf(text) {
  const parts = String(text).split("/").map(Number);
  if (!parts[1]) return Math.round(parts[0]) || 0;
  return Math.round(parts[0] / parts[1]);
}

try {
  main();
} catch (error) {
  process.stderr.write(`hyperframes runner: ${error.message}\n`);
  process.exit(1);
}
