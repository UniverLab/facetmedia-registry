/* Audio player: waveform with silences shaded, the played part in Hueso and
   the rest in Hueso tenue, scrubbable by click and by drag; the momentary
   loudness against its dashed target and the integrated value on the same time
   axis; the numbers; and the speech alignment with its WER.

   Space plays and pauses, the arrows seek one second, the waveform seeks
   wherever the pointer lands. */

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

  fillStats(preview, record);
  wireTransport(audio, duration);
  const wave = mountPlot(document.getElementById("wave"), () => waveSpec(preview, audio, duration));
  const loud = mountPlot(document.getElementById("loud"), () => loudSpec(preview, duration));
  seekOnDrag(document.getElementById("wave"), audio, duration);
  followPlayback(audio, wave, loud);
  renderSpeech(preview.speech);
}

/* ---- the numbers ---- */

/** `peak_limited`, from the record's verification metrics or its properties. */
function peakLimited(record) {
  const metrics = record?.verification?.metrics ?? {};
  if (metrics.peak_limited !== undefined) return metrics.peak_limited;
  if (record?.properties?.peak_limited !== undefined) return record.properties.peak_limited;
  return undefined;
}

function yesNo(value) {
  if (value === true) return "yes";
  if (value === false) return "no";
  return String(value);
}

function silenceText(silences) {
  if (silences.length === 0) return "none";
  return silences.map((silence) => `${silence.start_s}–${silence.end_s} s`).join(", ");
}

function statRows(preview, record) {
  const lufs = preview.loudness ?? {};
  const rows = [
    ["duration", `${preview.duration_s ?? 0} s`],
    ["sample rate", preview.sample_rate_hz ? `${preview.sample_rate_hz} Hz` : "—"],
    ["integrated loudness", `${lufs.integrated_lufs ?? "—"} LUFS`],
    ["true peak", `${lufs.peak_dbfs ?? "—"} dBFS`],
  ];
  const limited = peakLimited(record);
  if (limited !== undefined) rows.push(["peak limited", yesNo(limited)]);
  rows.push(
    ["clipped samples", String(preview.clipped_samples ?? 0)],
    ["silences", silenceText(preview.silences ?? [])],
  );
  return rows;
}

function fillStats(preview, record) {
  const body = document.querySelector("#stats tbody");
  for (const [label, value] of statRows(preview, record)) {
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

/* ---- the transport ---- */

/** `mm:ss.s`, for the time under the buttons. Rounded to the shown tenth
    first, so 59.96 s reads 01:00.0 and never 00:60.0. */
function clock(seconds) {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const total = Math.round(safe * 10) / 10;
  const minutes = Math.floor(total / 60);
  const rest = total - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

function togglePlay(audio) {
  if (!audio.paused) {
    audio.pause();
    return;
  }
  const started = audio.play();
  if (started) started.catch(() => {});
}

function seekBy(audio, seconds, duration) {
  const last = Math.max(0, duration - 0.05);
  const target = Math.min(Math.max((audio.currentTime || 0) + seconds, 0), last);
  audio.currentTime = target;
}

function wireTransport(audio, duration) {
  const button = document.getElementById("play");
  const time = document.getElementById("time");
  const refresh = () => {
    time.textContent = `${clock(audio.currentTime)} / ${clock(duration)}`;
    button.textContent = audio.paused ? "play" : "pause";
  };
  button.addEventListener("click", () => {
    togglePlay(audio);
    refresh();
  });
  for (const event of ["timeupdate", "seeked", "loadedmetadata", "play", "pause", "ended"]) {
    audio.addEventListener(event, refresh);
  }
  window.addEventListener("keydown", (event) => {
    if (event.key === " ") {
      event.preventDefault();
      togglePlay(audio);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      seekBy(audio, -1, duration);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      seekBy(audio, 1, duration);
    }
    refresh();
  });
  refresh();
}

function seekOnDrag(canvas, audio, duration) {
  let dragging = false;
  const seek = (event) => {
    audio.currentTime = valueAtX(canvas, event.clientX, duration);
  };
  canvas.addEventListener("pointerdown", (event) => {
    dragging = true;
    canvas.setPointerCapture?.(event.pointerId);
    seek(event);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (dragging) seek(event);
  });
  const stop = () => {
    dragging = false;
  };
  canvas.addEventListener("pointerup", stop);
  canvas.addEventListener("pointercancel", stop);
}

/* ---- the waveform and the loudness chart ---- */

function shadeSilences(ctx, geom, preview) {
  ctx.save();
  ctx.fillStyle = token("--hueso-tenue");
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
  ctx.strokeStyle = token("--hueso");
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x, geom.top);
  ctx.lineTo(x, geom.top + geom.height);
  ctx.stroke();
  ctx.restore();
}

/** The played stretch of the waveform, repainted in Hueso over the tenue band. */
function paintPlayed(ctx, geom, preview, audio) {
  const min = preview.waveform?.min ?? [];
  const max = preview.waveform?.max ?? [];
  const count = Math.min(min.length, max.length);
  if (count < 2) return;
  const end = geom.xToPx(audio.currentTime ?? 0);
  if (end <= geom.left) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(geom.left, geom.top, end - geom.left, geom.height);
  ctx.clip();
  const step = geom.width / (count - 1);
  ctx.beginPath();
  for (let index = 0; index < count; index += 1) {
    const x = geom.left + index * step;
    if (index === 0) ctx.moveTo(x, geom.yToPx(max[index]));
    else ctx.lineTo(x, geom.yToPx(max[index]));
  }
  for (let index = count - 1; index >= 0; index -= 1) {
    ctx.lineTo(geom.left + index * step, geom.yToPx(min[index]));
  }
  ctx.closePath();
  ctx.fillStyle = token("--hueso");
  ctx.globalAlpha = 0.35;
  ctx.fill();
  ctx.globalAlpha = 0.9;
  ctx.strokeStyle = token("--hueso");
  ctx.lineWidth = 1;
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
    overlay: (ctx, geom) => {
      paintPlayed(ctx, geom, preview, audio);
      drawPlayhead(ctx, geom, audio);
    },
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

/* ---- the speech alignment ---- */

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
