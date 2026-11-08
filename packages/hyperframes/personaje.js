#!/usr/bin/env node
"use strict";

// The personaje recipe: a hand-drawn SVG character speaks with Rhubarb mouths.
//
// The piece author runs the upstream Rhubarb CLI offline to produce bocas.json
// and its own build.mjs inlines the character into the composition. This module
// runs in the copied workDir before HyperFrames' check: it validates that every
// letter Rhubarb chose has its .boca-<letter> shape and that the CSS keeps the
// rest mouth visible at frame 0, then injects the cues and the audio start.
//
// It imports only node builtins so it runs before any dependency is linked.

const fs = require("node:fs");
const path = require("node:path");

const BOCAS_MARKER = "/* BOCAS */[]";
const AUDIO_START_DECLARATION = /\bconst\s+AUDIO_START\s*=\s*[^;]+;/;
const DEFAULT_AUDIO_START = 0.5;
const BOCA_ID_RE = /\bid=["'](boca-[A-Z])["']/g;
const REST_RULES = [
  { selector: ".boca", opacity: "0" },
  { selector: "#boca-X", opacity: "1" },
];

function personajeSetup(workDir, inputs, base) {
  const cues = mouthCues(inputs, base);
  const svg = characterSvg(inputs, base);
  requireShapes(svg, cues);
  const templateFile = path.join(workDir, "index.tmpl");
  if (!fs.existsSync(templateFile)) throw new Error("composicion: index.tmpl not found");
  const template = fs.readFileSync(templateFile, "utf8");
  requireRestRule(template, svg);
  const audioStart = audioStartOf(inputs);
  const updated = inject(template, cues, audioStart);
  copyVoice(inputs, base, workDir);
  fs.writeFileSync(templateFile, updated);
}

// --- bocas.json: the mouth cues the upstream Rhubarb CLI wrote offline.

function mouthCues(inputs, base) {
  const file = resolveInput(requiredInput(inputs, "bocas"), base);
  if (!fs.existsSync(file)) throw new Error(`bocas: ${file} not found`);
  let data;
  try {
    data = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    throw new Error(`bocas: ${file} is not valid JSON (${error.message})`);
  }
  if (!Array.isArray(data.mouthCues)) {
    throw new Error(`bocas: ${file} has no mouthCues array`);
  }
  return data.mouthCues;
}

function cueLetters(cues) {
  const letters = new Set();
  cues.forEach((cue, index) => {
    if (!cue || typeof cue !== "object" || typeof cue.value !== "string") {
      throw new Error(`bocas: mouthCues[${index}] has no value`);
    }
    letters.add(cue.value);
  });
  return letters;
}

// --- the character: one .boca shape per letter Rhubarb used.

function characterSvg(inputs, base) {
  const file = resolveInput(requiredInput(inputs, "personaje-svg"), base);
  if (!fs.existsSync(file)) throw new Error(`personaje-svg: ${file} not found`);
  return { file, text: fs.readFileSync(file, "utf8") };
}

function requireShapes(svg, cues) {
  const ids = bocaIds(svg.text);
  for (const letter of cueLetters(cues)) {
    if (!ids.has(letter)) {
      throw new Error(
        `personaje-svg: ${svg.file} has no .boca-${letter} shape for Rhubarb mouth ${letter}`,
      );
    }
  }
}

function bocaIds(svg) {
  const ids = new Set();
  for (const match of svg.matchAll(BOCA_ID_RE)) ids.add(match[1].slice("boca-".length));
  return ids;
}

// --- the rest rule: the rest mouth must be visible at frame 0.
//
// A tl.set at instant 0 never renders, so the CSS carries the rest state:
// .boca { opacity: 0; } #boca-X { opacity: 1; }. Without it every mouth is
// invisible until the first cue changes.

function requireRestRule(template, svg) {
  for (const source of [template, svg.text]) {
    if (hasRestRule(source)) return;
  }
  throw new Error(
    "index.tmpl: the rest rule .boca { opacity: 0; } #boca-X { opacity: 1; } " +
      "is required so the rest mouth shows at frame 0",
  );
}

function hasRestRule(css) {
  return REST_RULES.every((rule) => ruleHasOpacity(css, rule.selector, rule.opacity));
}

function ruleHasOpacity(css, selector, opacity) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`${escaped}\\s*\\{[^}]*opacity\\s*:\\s*${opacity}\\s*(?:;|})`);
  return pattern.test(css);
}

// --- the injection: the cues literal and the audio data-start shift.

function inject(template, cues, audioStart) {
  const withCues = replaceOnce(
    template,
    BOCAS_MARKER,
    JSON.stringify(cues),
    "index.tmpl: /* BOCAS */[] marker is required",
  );
  const declarations = withCues.match(new RegExp(AUDIO_START_DECLARATION, "g")) || [];
  if (declarations.length !== 1) {
    throw new Error(
      `index.tmpl: const AUDIO_START = <number>; is required; found ${declarations.length}`,
    );
  }
  return withCues.replace(AUDIO_START_DECLARATION, `const AUDIO_START = ${audioStart};`);
}

function replaceOnce(text, marker, replacement, message) {
  const count = text.split(marker).length - 1;
  if (count !== 1) throw new Error(`${message}; found ${count}`);
  return text.replace(marker, () => replacement);
}

function audioStartOf(inputs) {
  const raw = inputs["audio-inicio"];
  if (raw === undefined || raw === null) return DEFAULT_AUDIO_START;
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    throw new Error(`audio-inicio must be a finite number, got ${raw}`);
  }
  return value;
}

// --- the voice: copied beside the composition, where the audio tag points.

function copyVoice(inputs, base, workDir) {
  const file = resolveInput(requiredInput(inputs, "voz"), base);
  if (!fs.existsSync(file)) throw new Error(`voz: ${file} not found`);
  fs.copyFileSync(file, path.join(path.dirname(workDir), path.basename(file)));
}

function requiredInput(inputs, name) {
  const raw = inputs[name];
  if (!raw) throw new Error(`${name} is required`);
  return String(raw);
}

function resolveInput(value, base) {
  const text = String(value);
  return path.isAbsolute(text) ? text : path.resolve(base, text);
}

module.exports = { personajeSetup };
