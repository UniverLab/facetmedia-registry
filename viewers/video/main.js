/* Video viewer: a person judges the movement.

   By the record's mime. A playable clip gets a stage fitted to the window and
   letterboxed on the slide black, a play/pause button, a scrub bar, the time
   and the frame number, with the keyboard stepping one frame and filling the
   screen. A GIF gets the animated image on the same stage, one line that says
   what it is, and no scrub bar: it loops on its own. A file the browser cannot
   play (a MOV with alpha, say) falls back to the preview's first image when it
   lists one, and otherwise to the kind with a link to the file. The metrics sit
   under the stage in Sometype Mono. */

import { renderHeader } from "/kit/header.js";
import { assetUrl, loadAsset } from "/kit/load.js";

const GIF_MIME = "image/gif";
const FRAME_KEYS = { ",": -1, ".": 1 };
const PLAY_EVENTS = ["timeupdate", "seeked", "play", "pause", "ended"];

function main({ name, record, preview }) {
  renderHeader(document.getElementById("header"), record);
  document.getElementById("summary").textContent = preview.summary ?? "";
  const link = document.getElementById("asset-link");
  link.href = assetUrl(name);
  link.textContent = `open ${name}`;
  if (record.mime === GIF_MIME) renderGif(name, record, preview);
  else renderClip(name, record, preview);
  fillStats(record, preview);
  renderDetails(preview);
}

/* ---- a clip: stage, transport, keys ---- */

function renderClip(name, record, preview) {
  const clip = document.getElementById("clip");
  clip.hidden = false;
  clip.src = assetUrl(name);
  clip.setAttribute("aria-label", preview.name ?? name);
  const ui = {
    clip,
    fps: preview.fps ?? 25,
    total: preview.length ?? 1,
    duration: durationOf(record, preview) ?? 0,
  };
  const scrub = document.getElementById("scrub");
  scrub.max = String(ui.duration);
  const controls = document.getElementById("clip-controls");
  controls.hidden = false;
  clip.addEventListener("loadedmetadata", () => {
    if (Number.isFinite(clip.duration) && clip.duration > 0) {
      ui.duration = clip.duration;
      scrub.max = String(clip.duration);
    }
    updateReadout(ui);
  });
  for (const event of PLAY_EVENTS) {
    clip.addEventListener(event, () => {
      updateReadout(ui);
      updateButton(ui);
    });
  }
  scrub.addEventListener("input", () => {
    clip.currentTime = Number(scrub.value);
    updateReadout(ui);
  });
  document.getElementById("play").addEventListener("click", () => togglePlay(ui));
  clip.addEventListener("error", () => unplayable(name, record, preview));
  window.addEventListener("keydown", (event) => onClipKey(ui, event));
  updateReadout(ui);
}

function onClipKey(ui, event) {
  if (isTyping(event.target)) return;
  if (event.key === " ") {
    event.preventDefault();
    togglePlay(ui);
    return;
  }
  if (event.key === "f" || event.key === "F") {
    event.preventDefault();
    toggleFullscreen();
    return;
  }
  const direction = FRAME_KEYS[event.key];
  if (direction === undefined) return;
  event.preventDefault();
  if (ui.clip.paused) stepFrame(ui, direction);
}

/** A field where a keystroke is text, not a command. The scrub bar is not one:
    its keys are the viewer's, as on every other control. */
function isTyping(target) {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target instanceof HTMLTextAreaElement) return true;
  return target instanceof HTMLInputElement && target.type !== "range";
}

function togglePlay(ui) {
  if (!ui.clip.paused) {
    ui.clip.pause();
    return;
  }
  const started = ui.clip.play();
  if (started) started.catch(() => {});
}

function stepFrame(ui, direction) {
  const last = Math.max(0, ui.duration - 1 / (2 * ui.fps));
  const target = Math.min(Math.max(ui.clip.currentTime + direction / ui.fps, 0), last);
  ui.clip.currentTime = target;
  updateReadout(ui);
}

function updateButton(ui) {
  const button = document.getElementById("play");
  if (button) button.textContent = ui.clip.paused ? "play" : "pause";
}

function updateReadout(ui) {
  const current = ui.clip.currentTime || 0;
  document.getElementById("time").textContent = `${clock(current)} / ${clock(ui.duration)}`;
  const frame = Math.min(ui.total, Math.floor(current * ui.fps) + 1);
  document.getElementById("frame").textContent = `frame ${frame} / ${ui.total}`;
  const scrub = document.getElementById("scrub");
  if (document.activeElement !== scrub) scrub.value = String(current);
}

/** `mm:ss.s`, the same clock the audio viewer wears. Rounded to the shown
    tenth first, so 59.96 s reads 01:00.0 and never 00:60.0. */
function clock(seconds) {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const total = Math.round(safe * 10) / 10;
  const minutes = Math.floor(total / 60);
  const rest = total - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

function toggleFullscreen() {
  const stage = document.getElementById("stage");
  if (document.fullscreenElement) {
    const left = document.exitFullscreen?.();
    if (left) left.catch(() => {});
    return;
  }
  const entered = stage.requestFullscreen?.();
  if (entered) entered.catch(() => {});
}

/* ---- the file the browser cannot play ---- */

function imageReference(reference) {
  return String(reference).startsWith("/") ? reference : assetUrl(reference);
}

function unplayable(name, record, preview) {
  document.getElementById("clip").hidden = true;
  document.getElementById("clip-controls").hidden = true;
  document.getElementById("stage-caption").textContent = "the browser cannot play this file";
  const images = Array.isArray(preview.images) ? preview.images : [];
  const still = document.getElementById("still");
  if (images.length > 0) {
    still.src = imageReference(images[0]);
    still.alt = `${preview.name ?? name} first frame`;
    still.hidden = false;
    return;
  }
  const panel = document.getElementById("unplayable");
  panel.hidden = false;
  document.getElementById("kind-label").textContent =
    `${record.kind ?? "video"} · the browser cannot play this file`;
  document.getElementById("open-file").href = assetUrl(name);
}

/* ---- a GIF: an animated image, no transport ---- */

function gifLine(record, preview) {
  const props = record.properties ?? {};
  const frames = props.frames ?? preview.length ?? "—";
  const fps = props.fps ?? preview.fps ?? "—";
  return `GIF · loops · ${frames} frames · ${fps} fps`;
}

function renderGif(name, record, preview) {
  const gif = document.getElementById("gif");
  gif.src = assetUrl(name);
  gif.alt = preview.name ?? name;
  gif.hidden = false;
  const line = document.getElementById("gif-line");
  line.textContent = gifLine(record, preview);
  line.hidden = false;
  document.getElementById("stage-caption").textContent =
    "an animated image: it loops on its own, F fills the screen";
  window.addEventListener("keydown", (event) => {
    if (isTyping(event.target)) return;
    if (event.key !== "f" && event.key !== "F") return;
    event.preventDefault();
    toggleFullscreen();
  });
}

/* ---- the numbers ---- */

/** The clip's length in seconds: frames ÷ fps, else the record's own value. */
function durationOf(record, preview) {
  const length = preview.length;
  const fps = preview.fps;
  if (typeof length === "number" && typeof fps === "number" && fps > 0) return length / fps;
  const stated = record.properties?.duration_s;
  return typeof stated === "number" ? stated : null;
}

function loudnessRows(metrics) {
  const loud =
    metrics.loudness && typeof metrics.loudness === "object" ? metrics.loudness : metrics;
  const rows = [];
  if (typeof loud.integrated_lufs === "number") {
    rows.push(["integrated loudness", `${loud.integrated_lufs} LUFS`]);
  }
  if (typeof loud.peak_dbfs === "number") {
    rows.push(["true peak", `${loud.peak_dbfs} dBFS`]);
  }
  return rows;
}

function metricRows(record, preview) {
  const metrics = record.verification?.metrics ?? {};
  const duration = durationOf(record, preview);
  const rows = [
    ["resolution", `${preview.width ?? "—"} × ${preview.height ?? "—"} px`],
    ["fps", `${preview.fps ?? "—"} fps`],
    ["frames", String(preview.length ?? "—")],
    ["duration", duration === null ? "—" : `${duration.toFixed(2)} s`],
  ];
  if (typeof metrics.audio_streams === "number") {
    rows.push(["audio streams", String(metrics.audio_streams)]);
  }
  rows.push(...loudnessRows(metrics));
  return rows;
}

function fillStats(record, preview) {
  const body = document.querySelector("#stats tbody");
  for (const [label, value] of metricRows(record, preview)) {
    const row = document.createElement("tr");
    const term = document.createElement("th");
    term.scope = "row";
    term.textContent = label;
    const cell = document.createElement("td");
    cell.className = "num";
    cell.textContent = value;
    row.append(term, cell);
    body.append(row);
  }
}

function kvRow(list, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  list.append(dt, dd);
}

function renderDetails(preview) {
  const list = document.getElementById("details");
  kvRow(list, "name", preview.name ?? "—");
  kvRow(list, "prompt", preview.prompt ?? "—");
  kvRow(list, "seed", String(preview.seed ?? "—"));
  kvRow(list, "size", `${preview.width ?? "—"} × ${preview.height ?? "—"} px`);
  kvRow(list, "length", `${preview.length ?? "—"} frames`);
  kvRow(list, "rate", `${preview.fps ?? "—"} fps`);
}

// Boot last: every declaration above is initialized before it can run.
const loaded = await loadAsset();
if (loaded) main(loaded);
