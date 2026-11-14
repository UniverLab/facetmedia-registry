/* Image viewer: the still itself, fitted by default, at 1:1 pixels on a click
   or Z and pannable by dragging once it is bigger than the stage. A toggle puts
   a checkerboard behind it, for the transparent PNGs a pipeline cuts out. The
   metrics name its pixels and the file's size, from the record's bytes. */

import { renderHeader } from "/kit/header.js";
import { assetUrl, loadAsset } from "/kit/load.js";

/*: A pointer that moved less than this is a click, not a pan. */
const DRAG_SLOP = 3;
const UNITS = ["kB", "MB", "GB"];

function main({ name, record, preview }) {
  renderHeader(document.getElementById("header"), record);
  document.getElementById("summary").textContent = preview.summary ?? "";
  const link = document.getElementById("asset-link");
  link.href = assetUrl(name);
  link.textContent = `open ${name}`;
  const stage = document.getElementById("stage");
  const image = document.getElementById("still");
  image.src = assetUrl(name);
  image.alt = preview.name ?? name;
  wireStage(stage);
  document.getElementById("bg").addEventListener("click", () => toggleBackground(stage));
  fillStats(record, preview);
  renderDetails(preview);
}

/** Fit the still to the stage, or show it at 1:1 pixels. Returns the new state. */
function toggleFit(stage) {
  const fitted = stage.classList.toggle("fit");
  stage.scrollTo(0, 0);
  return fitted;
}

function wireStage(stage) {
  let drag = null;
  stage.addEventListener("pointerdown", (event) => {
    drag = {
      x: event.clientX,
      y: event.clientY,
      left: stage.scrollLeft,
      top: stage.scrollTop,
      moved: false,
    };
    stage.setPointerCapture?.(event.pointerId);
  });
  stage.addEventListener("pointermove", (event) => {
    if (drag === null) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (Math.abs(dx) > DRAG_SLOP || Math.abs(dy) > DRAG_SLOP) drag.moved = true;
    if (stage.classList.contains("fit")) return;
    stage.scrollLeft = drag.left - dx;
    stage.scrollTop = drag.top - dy;
  });
  stage.addEventListener("pointerup", () => {
    if (drag !== null && !drag.moved) toggleFit(stage);
    drag = null;
  });
  stage.addEventListener("pointercancel", () => {
    drag = null;
  });
  window.addEventListener("keydown", (event) => {
    if (event.key !== "z" && event.key !== "Z") return;
    event.preventDefault();
    toggleFit(stage);
  });
}

function toggleBackground(stage) {
  const checked = stage.classList.toggle("checker");
  const button = document.getElementById("bg");
  button.setAttribute("aria-pressed", String(checked));
  button.textContent = checked ? "image background" : "checkerboard";
}

/** A byte count for a person: 1105638 -> `1.1 MB`. */
function formatBytes(bytes) {
  if (typeof bytes !== "number") return "—";
  if (bytes < 1000) return `${bytes} B`;
  let value = bytes / 1000;
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value.toFixed(1)} ${UNITS[unit]}`;
}

function statRows(record, preview) {
  return [
    ["pixels", `${preview.width ?? "—"} × ${preview.height ?? "—"} px`],
    ["file size", formatBytes(record.bytes)],
  ];
}

function fillStats(record, preview) {
  const body = document.querySelector("#stats tbody");
  for (const [label, value] of statRows(record, preview)) {
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
}

const loaded = await loadAsset();
if (loaded) main(loaded);
