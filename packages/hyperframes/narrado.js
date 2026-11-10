#!/usr/bin/env node
"use strict";

// The narrado recipe: voice clips, a music bed and whisper subtitles on one
// timeline.
//
// The piece author produces the inputs offline: voicestudio voice files (one
// engine per file), an ffmpeg-mixed instrumental bed and a whisper .srt. This
// module runs in the copied workDir before HyperFrames' check: it copies the
// audio beside the composition, parses the .srt into subtitle cues, requires
// the cues to fit data-duration, and injects the audio elements, the burned-in
// subtitle divs and the opacity timeline into index.html.
//
// It imports only node builtins so it runs before any dependency is linked.

const fs = require("node:fs");
const path = require("node:path");

const SUBS_MARKER = "<!-- SUBS -->";
const AUDIOS_MARKER = "<!-- AUDIOS -->";
const TIMING_RE =
  /^(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})/;
const TAG_RE = /<([A-Za-z][\w:-]*)\b[^>]*>/g;

function narradoSetup(workDir, inputs, base) {
  const voices = voiceClips(inputs, base);
  const music = requiredFile(inputs, "musica", base);
  const subtitles = requiredFile(inputs, "subtitulos", base);
  const cues = readSrt(subtitles);
  const templateFile = path.join(workDir, "index.html");
  if (!fs.existsSync(templateFile)) throw new Error("composicion: index.html not found");
  const template = fs.readFileSync(templateFile, "utf8");
  const duration = compositionDuration(template);
  requireCuesFit(cues, duration);
  const updated = injectNarration(template, cues, voices, music);
  copyBeside([...voices, music], path.dirname(workDir));
  fs.writeFileSync(templateFile, updated);
}

// --- the inputs: voice clips, the bed and the whisper .srt, resolved on disk.

function voiceClips(inputs, base) {
  const raw = inputs.voz;
  if (!Array.isArray(raw) || raw.length === 0) throw new Error("voz is required");
  return raw.map((item, index) => {
    if (!item || typeof item !== "object" || !item.clip) {
      throw new Error(`voz[${index}] has no clip`);
    }
    const file = resolveInput(item.clip, base);
    if (!fs.existsSync(file)) throw new Error(`voz[${index}]: ${file} not found`);
    return file;
  });
}

function requiredFile(inputs, name, base) {
  const raw = inputs[name];
  if (!raw) throw new Error(`${name} is required`);
  const file = resolveInput(raw, base);
  if (!fs.existsSync(file)) throw new Error(`${name}: ${file} not found`);
  return file;
}

function resolveInput(value, base) {
  const text = String(value);
  return path.isAbsolute(text) ? text : path.resolve(base, text);
}

// --- the .srt: whisper's HH:MM:SS,mmm cues become { start, end, text }.

function readSrt(file) {
  const source = fs
    .readFileSync(file, "utf8")
    .replace(/^\uFEFF/, "")
    .replace(/\r\n?/g, "\n");
  const blocks = source
    .split(/\n[ \t]*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
  if (blocks.length === 0) throw new Error(`subtitulos: ${file} has no cues`);
  return blocks.map((block, index) => srtCue(block, index + 1, file));
}

function srtCue(block, number, file) {
  const lines = block
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const timingIndex = lines.findIndex((line) => TIMING_RE.test(line));
  if (timingIndex === -1) {
    throw new Error(`subtitulos: cue ${number} in ${file} has no timing line`);
  }
  const match = TIMING_RE.exec(lines[timingIndex]);
  const start = timestamp(match, 1, number);
  const end = timestamp(match, 5, number);
  if (end < start) throw new Error(`subtitulos: cue ${number} ends before it starts`);
  const text = lines.slice(timingIndex + 1).join(" ");
  if (!text) throw new Error(`subtitulos: cue ${number} in ${file} has no text`);
  return { start, end, text };
}

function timestamp(match, offset, cue) {
  const hours = Number(match[offset]);
  const minutes = Number(match[offset + 1]);
  const seconds = Number(match[offset + 2]);
  const millis = Number(match[offset + 3].padEnd(3, "0"));
  if (minutes > 59 || seconds > 59) {
    throw new Error(`subtitulos: cue ${cue} has a bad time ${match[0]}`);
  }
  return round3(hours * 3600 + minutes * 60 + seconds + millis / 1000);
}

function round3(value) {
  return Math.round(value * 1000) / 1000;
}

// --- the composition duration: data-duration on the data-composition-id tag.

function compositionDuration(template) {
  for (const match of template.matchAll(TAG_RE)) {
    const tag = match[0];
    if (!attribute(tag, "data-composition-id")) continue;
    const raw = attribute(tag, "data-duration");
    const duration = Number(raw);
    if (!Number.isFinite(duration) || duration <= 0) {
      throw new Error(
        `index.html: data-duration on the data-composition-id tag must be a ` +
          `positive number, got ${raw || "nothing"}`,
      );
    }
    return duration;
  }
  throw new Error("index.html: no data-composition-id tag");
}

function attribute(tag, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`\\b${escaped}\\s*=\\s*["']([^"']*)["']`).exec(tag);
  return match ? match[1] : "";
}

function requireCuesFit(cues, duration) {
  cues.forEach((cue, index) => {
    if (cue.end > duration) {
      throw new Error(
        `subtitulos: cue ${index + 1} ends at ${secondsText(cue.end)}s, ` +
          `past the composition duration ${secondsText(duration)}s`,
      );
    }
  });
}

function secondsText(value) {
  return String(round3(value));
}

// --- the injection: subtitle divs, audio elements and the opacity timeline.

function injectNarration(template, cues, voices, music) {
  const withSubs = replaceMarker(
    template,
    SUBS_MARKER,
    cues.map((cue, index) => subtitleLine(cue, index)).join("\n      "),
    "index.html: <!-- SUBS --> marker is required",
  );
  const withAudio = replaceMarker(
    withSubs,
    AUDIOS_MARKER,
    audioLines(voices, music),
    "index.html: <!-- AUDIOS --> marker is required",
  );
  return appendScript(withAudio, cues);
}

function replaceMarker(template, marker, replacement, message) {
  const count = template.split(marker).length - 1;
  if (count !== 1) throw new Error(`${message}; found ${count}`);
  return template.replace(marker, () => replacement);
}

function subtitleLine(cue, index) {
  return `<div class="sub" id="s${index}">${escapeHtml(cue.text)}</div>`;
}

function audioLines(voices, music) {
  const voiceLines = voices.map(
    (file, index) =>
      `<audio id="voz-${index + 1}" src="../${escapeAttr(path.basename(file))}"></audio>`,
  );
  const musicLine = `<audio id="musica" src="../${escapeAttr(path.basename(music))}"></audio>`;
  return [...voiceLines, musicLine].join("\n      ");
}

function appendScript(template, cues) {
  const script = narrationScript(cues);
  return template.includes("</body>")
    ? template.replace("</body>", [script, "</body>"].join("\n"))
    : [template, script].join("\n");
}

function narrationScript(cues) {
  const literal = JSON.stringify(cues)
    .replace(/</g, "\\u003c")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
  return [
    "<script>",
    "(function () {",
    `  var cues = ${literal};`,
    '  var root = document.querySelector("[data-composition-id]");',
    '  var name = root ? root.getAttribute("data-composition-id") : "main";',
    "  var tl = (window.__timelines || {})[name || \"main\"];",
    "  if (!tl) return;",
    "  cues.forEach(function (cue, index) {",
    '    tl.set("#s" + index, { opacity: 1 }, cue.start)',
    '      .set("#s" + index, { opacity: 0 }, cue.end);',
    "  });",
    "})();",
    "</script>",
  ].join("\n");
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// --- the audio: copied beside the composition, where ../<name> points.

function copyBeside(files, targetDir) {
  const seen = new Map();
  for (const file of files) {
    const base = path.basename(file);
    if (seen.has(base) && seen.get(base) !== file) {
      throw new Error(`narrado: ${base} is used by more than one input`);
    }
    seen.set(base, file);
    fs.copyFileSync(file, path.join(targetDir, base));
  }
}

module.exports = { narradoSetup };
