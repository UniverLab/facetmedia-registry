/* Audio player: waveform with silences shaded and a playhead that follows
   playback (click to seek), momentary loudness against the target and the
   integrated value on the same time axis, the numbers, and the speech
   alignment with its WER. */

import { mountPlot, valueAtX } from "/kit/chart.js";
import { renderHeader } from "/kit/header.js";
import { assetUrl, loadAsset } from "/kit/load.js";

function main({ name, record, preview }) {
  renderHeader(document.getElementById("header"), record);
  document.getElementById("summary").textContent = preview.summary ?? "";
  const link = document.getElementById("asset-link");
  link.href = assetUrl(name);
  link.textContent = `open ${name}`;

  const audio = document.getElementById("player");
  audio.src = assetUrl(name);
  const duration = preview.duration_s ?? 1;

  fillStats(preview);
  const wave = mountPlot(document.getElementById("wave"), () => waveSpec(preview, audio, duration));
  const loud = mountPlot(document.getElementById("loud"), () => loudSpec(preview, duration));
  seekOnClick(document.getElementById("wave"), audio, duration);
  followPlayback(audio, wave, loud);
  renderSpeech(preview.speech);
}

function fillStats(preview) {
  const lufs = preview.loudness ?? {};
  const silences = preview.silences ?? [];
  const rows = [
    ["duration", `${preview.duration_s ?? 0} s`],
    ["integrated loudness", `${lufs.integrated_lufs ?? "—"} LUFS`],
    ["peak", `${lufs.peak_dbfs ?? "—"} dBFS`],
    ["clipped samples", String(preview.clipped_samples ?? 0)],
    ["silences", silences.length === 0
      ? "none"
      : silences.map((s) => `${s.start_s}–${s.end_s} s`).join(", ")],
  ];
  const body = document.querySelector("#stats tbody");
  for (const [label, value] of rows) {
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

function shadeSilences(ctx, geom, preview) {
  ctx.save();
  ctx.fillStyle = token("--muted");
  ctx.globalAlpha = 0.18;
  for (const silence of preview.silences ?? []) {
    const x = geom.xToPx(silence.start_s);
    const width = Math.max(1, geom.xToPx(silence.end_s) - x);
    ctx.fillRect(x, geom.top, width, geom.height);
  }
  ctx.restore();
}

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function drawPlayhead(ctx, geom, audio) {
  const x = geom.xToPx(audio.currentTime ?? 0);
  ctx.save();
  ctx.strokeStyle = token("--error");
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x, geom.top);
  ctx.lineTo(x, geom.top + geom.height);
  ctx.stroke();
  ctx.restore();
}

function waveSpec(preview, audio, duration) {
  return {
    min: preview.waveform?.min,
    max: preview.waveform?.max,
    xMax: duration,
    yMin: -1,
    yMax: 1,
    yTicks: [-1, 0, 1],
    paint: (ctx, geom) => shadeSilences(ctx, geom, preview),
    overlay: (ctx, geom) => drawPlayhead(ctx, geom, audio),
  };
}

function loudSpec(preview, duration) {
  const momentary = preview.loudness?.momentary ?? { step_s: 0.1, lufs: [] };
  const values = momentary.lufs.filter((value) => value !== null);
  const marks = [...values, preview.loudness?.target_lufs, preview.loudness?.integrated_lufs]
    .filter((value) => typeof value === "number");
  const low = Math.min(...marks) - 1;
  const high = Math.max(...marks) + 1;
  return {
    line: momentary.lufs,
    lineX: (index) => index * (momentary.step_s ?? 0.1),
    xMax: duration,
    yMin: Number.isFinite(low) ? low : -24,
    yMax: Number.isFinite(high) ? high : 0,
    fmtY: (value) => value.toFixed(1),
    ref: preview.loudness?.target_lufs,
    refLabel: `target ${preview.loudness?.target_lufs ?? ""} LUFS`,
    ref2: preview.loudness?.integrated_lufs,
    ref2Label: `integrated ${preview.loudness?.integrated_lufs ?? ""} LUFS`,
  };
}

function seekOnClick(canvas, audio, duration) {
  canvas.addEventListener("click", (event) => {
    audio.currentTime = valueAtX(canvas, event.clientX, duration);
  });
}

function followPlayback(audio, ...plots) {
  let frame = 0;
  const redraw = () => plots.forEach((plot) => plot.redraw());
  const tick = () => {
    redraw();
    if (!audio.paused && !audio.ended) frame = requestAnimationFrame(tick);
  };
  const stop = () => {
    cancelAnimationFrame(frame);
    redraw();
  };
  audio.addEventListener("play", () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(tick);
  });
  audio.addEventListener("pause", stop);
  audio.addEventListener("ended", stop);
  audio.addEventListener("seeked", redraw);
  audio.addEventListener("loadedmetadata", redraw);
}

const OPS = {
  ok: "w-ok",
  sub: "w-sub",
  del: "w-del",
  ins: "w-ins",
};

function wordText(op, entry) {
  if (op === "sub") return `${entry.ref}→${entry.hyp}`;
  if (op === "ins") return entry.hyp ?? "";
  return entry.ref ?? entry.hyp ?? "";
}

function renderSpeech(speech) {
  if (!speech) return;
  const section = document.getElementById("speech");
  section.hidden = false;
  document.getElementById("wer").textContent = `WER ${speech.wer}`;
  const line = document.getElementById("alignment");
  for (const entry of speech.alignment ?? []) {
    const span = document.createElement("span");
    span.className = OPS[entry.op] ?? "w-ok";
    span.textContent = wordText(entry.op, entry);
    line.append(span, " ");
  }
}

// Boot last: every declaration above is initialized before it can run.
const loaded = await loadAsset();
if (loaded) main(loaded);
